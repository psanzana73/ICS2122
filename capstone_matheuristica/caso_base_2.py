from __future__ import annotations

"""

Para correr instancia-semana-dia de matheurística y caso base:

terminal en capstone_matheurística
correr: python3 caso_base_2.py --tipo small --instancias 4 --semanas 3
correr: 
python3 validar_solucion.py \
  --excel data/instancias_small.xlsx \
  --hoja "Instancia 4" \
  --semana 3 \
  --tag BASE_small_Instancia4_semana3 \
  --flota Vehiculos_Small

correr:
python3 graficar_ruta_dia.py \
  --tipo small \
  --instancia 4 \
  --semana 3 \
  --dia 3 \
  --grafo data/grafo_santiago

para resumen general de todas las instancias correr: python3 caso_base_2.py --tipo small





Caso base informado por demanda para la red de transporte sanitario.

Este script reemplaza la asignación rotativa del caso base original por una
política determinista que puede aplicar un planificador sin optimización
matemática:

1. Mantiene activas todas las bases durante la semana.
2. Estima carga de trabajo por base, día y clase de vehículo.
3. Dimensiona la flota con una utilización objetivo (80 % por defecto).
4. Posiciona los vehículos proporcionalmente a la demanda esperada.
5. Ordena las solicitudes por urgencia operacional.
6. Asigna secuencialmente el vehículo compatible, suficiente y de menor costo.
7. Permite una consolidación local limitada entre dos solicitudes evidentes.
8. Si el servicio directo falla, intenta división, transferencia y finalmente
   compara tardanza/sobretiempo con el costo de externalización.

No usa Gurobi, precios duales, generación de columnas, GRASP ni VND. Tampoco
reordena globalmente las decisiones ya tomadas.

Debe guardarse en la raíz del proyecto, al mismo nivel que ``main.py``.

Ejemplos:
    python caso_base_informado.py --tipo small --instancias 4 --semanas 3
    python caso_base_informado.py --tipo big
    python caso_base_informado.py --tipo small --sin-consolidacion
"""

# from __future__ import annotations

import argparse
import math
import time
from collections import defaultdict
from dataclasses import dataclass

import pandas as pd

from matheuristica import datos, kpis, matriz, planes, validacion
from matheuristica.config import Config
from matheuristica.maestro import armar_solucion
from matheuristica.ruta import Evaluador


EPS = 1e-6


# ---------------------------------------------------------------------------
# Estructuras auxiliares
# ---------------------------------------------------------------------------
@dataclass
class AsignacionTramo:
    vehiculo: str
    tramo: str
    nuevas_paradas: list[tuple[str, int]]
    ruta: object


@dataclass
class AsignacionPlan:
    plan: str
    asignaciones: list[AsignacionTramo]
    costo_marginal: float
    tardanza_marginal: float
    sobretiempo_marginal: float
    costo_total_comparable: float


# ---------------------------------------------------------------------------
# Reglas de prioridad y compatibilidad
# ---------------------------------------------------------------------------
def prioridad_solicitud(s) -> tuple:
    """Prioridad lexicográfica usada por el despachador.

    1) cierre más próximo de la ventana de retiro;
    2) solicitudes sin tardanza permitida;
    3) vencimiento de entrega más próximo;
    4) menor cantidad de vehículos compatibles;
    5) mayor carga;
    6) identificador, para asegurar determinismo.
    """
    return (
        s.fin_pickup,
        int(s.tardanza_ok),
        s.due_delivery,
        len(s.vehiculos),
        -s.cantidad,
        s.id,
    )


def ventanas_solapadas(a, b) -> bool:
    pickup = max(a.ini_pickup, b.ini_pickup) <= min(a.fin_pickup, b.fin_pickup)
    delivery = max(a.ini_delivery, b.ini_delivery) <= min(a.due_delivery, b.due_delivery)
    return pickup and delivery


def cargas_compatibles(inst, clase_a: str, clase_b: str) -> bool:
    if clase_a == clase_b:
        return True
    return frozenset((clase_a, clase_b)) not in inst.incompatibles


def ubicacion_actual(k, paradas, base_de, cat):
    if not paradas[k]:
        return base_de[k]
    ultimo_tid, ultimo_tipo = paradas[k][-1]
    tr = cat.tramos[ultimo_tid]
    return tr.origen if ultimo_tipo == 0 else tr.destino


# ---------------------------------------------------------------------------
# Planificación semanal
# ---------------------------------------------------------------------------
def tipo_vehiculo_preferente(inst, s):
    """Escoge una clase vehicular razonable para estimar la carga semanal.

    Se prioriza una clase con capacidad suficiente y menor costo. Si ninguna
    unidad puede transportar la carga completa y la solicitud es divisible, se
    usa la clase compatible que requiere menos vehículos.
    """
    por_clase = defaultdict(list)
    for k in s.vehiculos:
        if k in inst.vehiculos:
            v = inst.vehiculos[k]
            if s.clase in v.clases_compatibles:
                por_clase[v.clase].append(v)

    if not por_clase:
        return None, 0

    opciones = []
    for clase, vehs in por_clase.items():
        capacidad = max(v.capacidad for v in vehs)
        if capacidad >= s.cantidad:
            n = 1
        elif s.divisible:
            n = math.ceil(s.cantidad / capacidad)
            if n > s.max_vehiculos_split:
                continue
        else:
            continue

        costo_fijo = min(v.costo_fijo for v in vehs)
        costo_km = min(v.costo_km for v in vehs)
        holgura_cap = max(0, n * capacidad - s.cantidad)
        opciones.append(((n, costo_fijo, costo_km, holgura_cap, clase), clase, n))

    if not opciones:
        return None, 0
    _, clase, n = min(opciones, key=lambda x: x[0])
    return clase, n


def estimar_carga_semanal(inst, M):
    """Retorna carga estimada en minutos por (base, clase vehículo, día)."""
    carga = defaultdict(float)
    asignacion_demanda = {}

    for s in inst.solicitudes:
        base = min(inst.bases, key=lambda b: (M.tiempo(b, s.origen), b))
        clase_veh, n_servicios = tipo_vehiculo_preferente(inst, s)
        asignacion_demanda[s.id] = (base, clase_veh, n_servicios)
        if clase_veh is None:
            continue

        minutos = (
            M.tiempo(base, s.origen)
            + s.serv_pickup
            + M.tiempo(s.origen, s.destino)
            + s.serv_delivery
            + M.tiempo(s.destino, base)
        )
        carga[(base, clase_veh, s.dia)] += minutos * n_servicios

    return carga, asignacion_demanda


def dimensionar_flota(inst, carga, cfg, utilizacion_objetivo: float):
    """Selecciona vehículos mediante la carga del día de mayor demanda."""
    clases = sorted({v.clase for v in inst.vehiculos.values()})
    seleccionados = []
    requeridos = {}
    jornada = float(cfg.horizonte)

    for clase in clases:
        disponibles = [
            k for k, v in inst.vehiculos.items() if v.clase == clase
        ]
        disponibles.sort(key=lambda k: (
            inst.vehiculos[k].costo_fijo,
            inst.vehiculos[k].costo_km,
            -inst.vehiculos[k].capacidad,
            k,
        ))

        carga_dia = {
            d: sum(carga.get((b, clase, d), 0.0) for b in inst.bases)
            for d in inst.dias
        }
        peak = max(carga_dia.values(), default=0.0)
        n = math.ceil(peak / (utilizacion_objetivo * jornada)) if peak > EPS else 0
        n = min(n, len(disponibles))
        requeridos[clase] = n
        seleccionados.extend(disponibles[:n])

    # No se puede posicionar una flota mayor que el cupo total de las bases.
    capacidad_total = sum(b.capacidad for b in inst.bases.values())
    if len(seleccionados) > capacidad_total:
        seleccionados = seleccionados[:capacidad_total]

    return seleccionados, requeridos


def _objetivos_proporcionales(inst, carga, clase: str, cantidad: int):
    pesos = {
        b: sum(carga.get((b, clase, d), 0.0) for d in inst.dias)
        for b in inst.bases
    }
    total = sum(pesos.values())
    if cantidad == 0:
        return {b: 0 for b in inst.bases}
    if total <= EPS:
        # Fallback determinista si una clase no tiene demanda atribuida.
        orden = sorted(inst.bases)
        return {b: cantidad // len(orden) + (i < cantidad % len(orden))
                for i, b in enumerate(orden)}

    ideal = {b: cantidad * pesos[b] / total for b in inst.bases}
    objetivo = {b: math.floor(ideal[b]) for b in inst.bases}
    faltan = cantidad - sum(objetivo.values())
    restos = sorted(inst.bases, key=lambda b: (-(ideal[b] - objetivo[b]), -pesos[b], b))
    for b in restos[:faltan]:
        objetivo[b] += 1
    return objetivo


def posicionar_flota(inst, carga, vehiculos_activos):
    """Distribuye la flota por clase con regla proporcional y mayores restos."""
    por_clase = defaultdict(list)
    for k in vehiculos_activos:
        por_clase[inst.vehiculos[k].clase].append(k)

    base_de = {}
    ocupacion = {b: 0 for b in inst.bases}

    for clase in sorted(por_clase):
        vehs = sorted(por_clase[clase])
        objetivo = _objetivos_proporcionales(inst, carga, clase, len(vehs))
        destinos = []
        for b in sorted(inst.bases):
            destinos.extend([b] * objetivo[b])

        for k, preferida in zip(vehs, destinos):
            if ocupacion[preferida] < inst.bases[preferida].capacidad:
                elegida = preferida
            else:
                libres = [b for b in inst.bases
                          if ocupacion[b] < inst.bases[b].capacidad]
                if not libres:
                    raise RuntimeError("El cupo de las bases no permite posicionar la flota activa.")
                elegida = max(
                    libres,
                    key=lambda b: (
                        sum(carga.get((b, clase, d), 0.0) for d in inst.dias)
                        / (1 + ocupacion[b]),
                        -ocupacion[b],
                        b,
                    ),
                )
            base_de[k] = elegida
            ocupacion[elegida] += 1

    # Si hay suficientes vehículos, se evita dejar una base activa sin flota.
    if len(base_de) >= len(inst.bases):
        vacias = [b for b in inst.bases if ocupacion[b] == 0]
        for destino in vacias:
            candidatos = [k for k, b in base_de.items() if ocupacion[b] > 1]
            if not candidatos:
                break
            k = max(
                candidatos,
                key=lambda kk: (
                    sum(carga.get((destino, inst.vehiculos[kk].clase, d), 0.0)
                        for d in inst.dias),
                    -inst.vehiculos[kk].costo_km,
                    kk,
                ),
            )
            origen = base_de[k]
            base_de[k] = destino
            ocupacion[origen] -= 1
            ocupacion[destino] += 1

    return base_de


# ---------------------------------------------------------------------------
# Catálogo de planes alternativos
# ---------------------------------------------------------------------------
def agregar_planes_nuevos(cat, generador):
    ids = []
    for plan, tramos in generador:
        pid = plan.id
        if pid not in cat.planes:
            cat.agregar(plan, tramos)
        ids.append(pid)
    return ids


def planes_split_disponibles(s, cat, cfg):
    if not s.divisible:
        return []
    return agregar_planes_nuevos(cat, planes.planes_split(s, cfg))


def planes_transferencia_disponibles(s, inst, M, cat, cfg):
    if not s.transferible:
        return []
    ids = agregar_planes_nuevos(cat, planes.planes_transferencia(s, inst, M, cfg))
    return sorted(ids, key=lambda p: (
        M.tiempo(s.origen, cat.planes[p].hub)
        + M.tiempo(cat.planes[p].hub, s.destino),
        p,
    ))


# ---------------------------------------------------------------------------
# Evaluación secuencial de un plan
# ---------------------------------------------------------------------------
def capacidad_hub_ok(inst, cat, pid, uso_hub):
    plan = cat.planes[pid]
    if not plan.hub:
        return True
    hub = inst.hubs[plan.hub]
    ops, cantidad = uso_hub.get((plan.hub, plan.dia), (0, 0.0))
    return (
        ops + plan.n_ops_hub <= hub.cap_diaria_ops
        and cantidad + plan.cantidad_hub <= hub.cap_diaria_cantidad + EPS
    )


def costo_adicional_plan(inst, cat, pid, hubs_abiertos):
    plan = cat.planes[pid]
    costo = plan.costo_handling * plan.n_ops_hub
    if plan.hub and plan.hub not in hubs_abiertos:
        costo += inst.hubs[plan.hub].costo_fijo
    return costo


def evaluar_plan(
    pid,
    inst,
    M,
    cat,
    ev,
    dia,
    vehiculos_activos,
    base_de,
    paradas,
    rutas_actuales,
    hubs_abiertos,
    uso_hub,
):
    """Asigna los tramos de un plan de forma greedy y sin deshacer rutas."""
    if pid not in cat.planes or not capacidad_hub_ok(inst, cat, pid, uso_hub):
        return None

    tramos = list(cat.tramos_de(pid))
    # Primero se atiende el tramo con menos vehículos activos compatibles.
    tramos.sort(key=lambda tr: (
        len(set(tr.vehiculos) & set(vehiculos_activos)),
        tr.fin_pickup,
        tr.id,
    ))

    asignaciones = []
    usados_en_plan = set()
    costo_marginal = 0.0
    tardanza_marginal = 0.0
    sobretiempo_marginal = 0.0

    for tr in tramos:
        candidatos = []
        for k in sorted(set(tr.vehiculos) & set(vehiculos_activos)):
            if k in usados_en_plan or k not in base_de:
                continue
            prev = rutas_actuales.get(k)
            nuevas_paradas = paradas[k] + [(tr.id, 0), (tr.id, 1)]
            nueva = ev.evaluar(nuevas_paradas, k, base_de[k], dia)
            if nueva is None:
                continue

            delta_costo = nueva.costo - (prev.costo if prev else 0.0)
            delta_tard = nueva.tardanza - (prev.tardanza if prev else 0.0)
            delta_ot = nueva.sobretiempo - (prev.sobretiempo if prev else 0.0)
            ubicacion = ubicacion_actual(k, paradas, base_de, cat)
            veh = inst.vehiculos[k]
            clave = (
                int(delta_tard > EPS),
                int(delta_ot > EPS),
                max(0, veh.capacidad - tr.cantidad),
                veh.costo_km,
                M.tiempo(ubicacion, tr.origen),
                delta_costo,
                k,
            )
            candidatos.append((clave, k, nuevas_paradas, nueva,
                               delta_costo, delta_tard, delta_ot))

        if not candidatos:
            return None

        _, k, nuevas_paradas, nueva, dc, dt, do = min(candidatos, key=lambda x: x[0])
        asignaciones.append(AsignacionTramo(k, tr.id, nuevas_paradas, nueva))
        usados_en_plan.add(k)
        costo_marginal += dc
        tardanza_marginal += max(0.0, dt)
        sobretiempo_marginal += max(0.0, do)

    costo_total = costo_marginal + costo_adicional_plan(inst, cat, pid, hubs_abiertos)
    return AsignacionPlan(
        plan=pid,
        asignaciones=asignaciones,
        costo_marginal=costo_marginal,
        tardanza_marginal=tardanza_marginal,
        sobretiempo_marginal=sobretiempo_marginal,
        costo_total_comparable=costo_total,
    )


def clave_asignacion(a: AsignacionPlan):
    return (
        int(a.tardanza_marginal > EPS),
        int(a.sobretiempo_marginal > EPS),
        a.costo_total_comparable,
        a.plan,
    )


def comprometer_asignacion(a, paradas, rutas_actuales, cat, hubs_abiertos, uso_hub):
    for asignacion in a.asignaciones:
        paradas[asignacion.vehiculo] = list(asignacion.nuevas_paradas)
        rutas_actuales[asignacion.vehiculo] = asignacion.ruta

    plan = cat.planes[a.plan]
    if plan.hub:
        hubs_abiertos.add(plan.hub)
        clave = (plan.hub, plan.dia)
        ops, cantidad = uso_hub.get(clave, (0, 0.0))
        uso_hub[clave] = (
            ops + plan.n_ops_hub,
            cantidad + plan.cantidad_hub,
        )


# ---------------------------------------------------------------------------
# Consolidación local limitada
# ---------------------------------------------------------------------------
def probar_consolidacion(
    solicitud,
    pid,
    asignacion,
    pendientes,
    seleccion,
    inst,
    M,
    cat,
    ev,
    dia,
    base_de,
    paradas,
    rutas_actuales,
    radio_min,
    max_candidatos,
):
    """Prueba como máximo una solicitud adicional en el mismo vehículo."""
    if len(asignacion.asignaciones) != 1:
        return None
    if cat.planes[pid].tipo != "directo":
        return None

    asignacion_1 = asignacion.asignaciones[0]
    k = asignacion_1.vehiculo
    veh = inst.vehiculos[k]
    tramos_1 = list(cat.tramos_de(pid))
    if len(tramos_1) != 1:
        return None
    t1 = tramos_1[0]

    candidatos = []
    for s2 in pendientes:
        pid2 = seleccion.get(s2.id)
        if pid2 not in cat.planes or cat.planes[pid2].tipo != "directo":
            continue
        tramos_2 = list(cat.tramos_de(pid2))
        if len(tramos_2) != 1:
            continue
        t2 = tramos_2[0]
        if k not in t2.vehiculos:
            continue
        if not ventanas_solapadas(solicitud, s2):
            continue
        if not cargas_compatibles(inst, solicitud.clase, s2.clase):
            continue
        if solicitud.cantidad + s2.cantidad > veh.capacidad:
            continue
        cercania = M.tiempo(solicitud.origen, s2.origen)
        if cercania > radio_min:
            continue
        candidatos.append((cercania, prioridad_solicitud(s2), s2, pid2, t2))

    candidatos.sort(key=lambda x: (x[0], x[1]))
    candidatos = candidatos[:max_candidatos]
    prev = rutas_actuales.get(k)
    prefijo = list(paradas[k])
    mejor = None

    for _, _, s2, pid2, t2 in candidatos:
        secuencias = [
            [(t1.id, 0), (t2.id, 0), (t1.id, 1), (t2.id, 1)],
            [(t1.id, 0), (t2.id, 0), (t2.id, 1), (t1.id, 1)],
        ]
        for cola in secuencias:
            nueva_paradas = prefijo + cola
            ruta = ev.evaluar(nueva_paradas, k, base_de[k], dia)
            if ruta is None:
                continue
            delta_tard = ruta.tardanza - (prev.tardanza if prev else 0.0)
            delta_ot = ruta.sobretiempo - (prev.sobretiempo if prev else 0.0)
            # La consolidación local se acepta solo si no crea penalizaciones.
            if delta_tard > EPS or delta_ot > EPS:
                continue
            delta = ruta.costo - (prev.costo if prev else 0.0)
            clave = (delta, ruta.retorno, s2.id)
            if mejor is None or clave < mejor[0]:
                mejor = (clave, s2, pid2, nueva_paradas, ruta)

    return mejor


# ---------------------------------------------------------------------------
# Resolución semanal del caso base
# ---------------------------------------------------------------------------
def resolver_caso_base(
    inst,
    M,
    cfg,
    utilizacion_objetivo=0.80,
    radio_consolidacion_min=15.0,
    max_candidatos_consolidacion=12,
    usar_consolidacion=True,
):
    cat, seleccion = planes.catalogo_inicial(inst, cfg)
    ev = Evaluador(inst, M, cfg, cat)

    carga, asignacion_demanda = estimar_carga_semanal(inst, M)
    vehiculos_activos, requeridos = dimensionar_flota(
        inst, carga, cfg, utilizacion_objetivo
    )
    base_de = posicionar_flota(inst, carga, vehiculos_activos)

    rutas_finales = []
    planes_usados = []
    externalizadas = []
    hubs_abiertos = set()
    uso_hub = {}

    for dia in inst.dias:
        paradas = {k: [] for k in vehiculos_activos}
        rutas_actuales = {}
        pendientes = sorted(list(inst.por_dia(dia)), key=prioridad_solicitud)

        while pendientes:
            s = pendientes.pop(0)
            pid_inicial = seleccion[s.id]
            tipo_inicial = cat.planes[pid_inicial].tipo

            # 1) Servicio directo limpio: sin tardanza ni sobretiempo marginal.
            directa = None
            penalizada_directa = None
            if tipo_inicial == "directo":
                intento = evaluar_plan(
                    pid_inicial, inst, M, cat, ev, dia, vehiculos_activos,
                    base_de, paradas, rutas_actuales, hubs_abiertos, uso_hub,
                )
                if intento is not None:
                    if intento.tardanza_marginal <= EPS and intento.sobretiempo_marginal <= EPS:
                        directa = intento
                    else:
                        penalizada_directa = intento

            if directa is not None:
                consolidada = None
                if usar_consolidacion:
                    consolidada = probar_consolidacion(
                        s, pid_inicial, directa, pendientes, seleccion,
                        inst, M, cat, ev, dia, base_de, paradas,
                        rutas_actuales, radio_consolidacion_min,
                        max_candidatos_consolidacion,
                    )

                if consolidada is None:
                    comprometer_asignacion(
                        directa, paradas, rutas_actuales, cat,
                        hubs_abiertos, uso_hub,
                    )
                    planes_usados.append(pid_inicial)
                else:
                    _, s2, pid2, nuevas_paradas, ruta = consolidada
                    k = directa.asignaciones[0].vehiculo
                    paradas[k] = list(nuevas_paradas)
                    rutas_actuales[k] = ruta
                    planes_usados.extend([pid_inicial, pid2])
                    pendientes = [x for x in pendientes if x.id != s2.id]
                continue

            # 2) Alternativas internas. Si el plan inicial ya era una división
            # estructural, se prueba antes de generar nuevas alternativas.
            alternativas = []
            if tipo_inicial == "split":
                alternativas.append(pid_inicial)
            alternativas.extend(
                p for p in planes_split_disponibles(s, cat, cfg)
                if p not in alternativas
            )
            alternativas.extend(
                p for p in planes_transferencia_disponibles(s, inst, M, cat, cfg)
                if p not in alternativas
            )

            evaluadas = []
            for pid in alternativas:
                intento = evaluar_plan(
                    pid, inst, M, cat, ev, dia, vehiculos_activos,
                    base_de, paradas, rutas_actuales, hubs_abiertos, uso_hub,
                )
                if intento is not None:
                    evaluadas.append(intento)

            # La alternativa directa con tardanza/sobretiempo se considera al
            # final, junto con las demás opciones internas penalizadas.
            if penalizada_directa is not None:
                evaluadas.append(penalizada_directa)

            if evaluadas:
                mejor = min(evaluadas, key=clave_asignacion)
                if mejor.costo_total_comparable < s.penal_externalizacion:
                    comprometer_asignacion(
                        mejor, paradas, rutas_actuales, cat,
                        hubs_abiertos, uso_hub,
                    )
                    planes_usados.append(mejor.plan)
                    continue

            # 3) No existe alternativa interna conveniente.
            externalizadas.append(s.id)

        rutas_finales.extend(rutas_actuales.values())

    sol = armar_solucion(
        inst, cat, rutas_finales, planes_usados, externalizadas,
        vehiculos_activos, base_de, sorted(inst.bases), sorted(hubs_abiertos),
        cota=0.0, gap=0.0,
    )

    # armar_solucion elimina recursos activados pero no usados. Para este caso
    # base la activación semanal es una decisión previa y todos esos costos se
    # pagan, aunque un vehículo quede ocioso. Todas las bases permanecen activas.
    sol.vehiculos = list(vehiculos_activos)
    sol.posicionamiento = dict(base_de)
    sol.bases = sorted(inst.bases)
    sol.hubs = sorted(hubs_abiertos)
    sol.desglose["fijo_vehiculos"] = sum(
        inst.vehiculos[k].costo_fijo for k in vehiculos_activos
    )
    sol.desglose["fijo_bases"] = sum(b.costo_fijo for b in inst.bases.values())
    sol.desglose["fijo_hubs"] = sum(inst.hubs[h].costo_fijo for h in hubs_abiertos)
    sol.costo = sum(sol.desglose.values())

    diagnostico_planificacion = {
        "carga": carga,
        "asignacion_demanda": asignacion_demanda,
        "requeridos": requeridos,
        "vehiculos_activos": list(vehiculos_activos),
        "posicionamiento": dict(base_de),
    }
    return sol, cat, ev, diagnostico_planificacion


# ---------------------------------------------------------------------------
# Exportación adicional del diseño semanal
# ---------------------------------------------------------------------------
def exportar_planificacion(inst, cfg, diag, sufijo):
    filas = []
    carga = diag["carga"]
    posicion = diag["posicionamiento"]
    for b in sorted(inst.bases):
        for clase in sorted({v.clase for v in inst.vehiculos.values()}):
            vehs = [k for k, bb in posicion.items()
                    if bb == b and inst.vehiculos[k].clase == clase]
            for d in inst.dias:
                filas.append({
                    "base": b,
                    "clase_vehiculo": clase,
                    "dia": d,
                    "carga_estimada_min": round(carga.get((b, clase, d), 0.0), 2),
                    "vehiculos_posicionados": len(vehs),
                    "ids_vehiculos": " | ".join(sorted(vehs)),
                })
    pd.DataFrame(filas).to_csv(
        cfg.dir_salida / f"planificacion_{sufijo}.csv", index=False
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--tipo", default="big", choices=["small", "big"])
    ap.add_argument("--instancias", type=int, nargs="*", default=list(range(1, 11)))
    ap.add_argument("--semanas", type=int, nargs="*", default=[1, 2, 3, 4])
    ap.add_argument("--utilizacion", type=float, default=0.80,
                    help="utilización objetivo de la jornada (default: 0.80)")
    ap.add_argument("--radio-consolidacion-min", type=float, default=15.0,
                    help="máxima distancia temporal entre retiros consolidables")
    ap.add_argument("--max-candidatos-consolidacion", type=int, default=12)
    ap.add_argument("--sin-consolidacion", action="store_true")
    a = ap.parse_args()

    if not 0 < a.utilizacion <= 1:
        ap.error("--utilizacion debe estar en el intervalo (0, 1].")

    filas = []
    for i in a.instancias:
        for w in a.semanas:
            t0 = time.time()
            cfg = Config()
            cfg.tipo_instancia = a.tipo
            cfg.hoja_instancia = f"Instancia {i}"
            cfg.semana = w
            cfg.dir_salida.mkdir(parents=True, exist_ok=True)

            inst = datos.cargar(cfg)
            M = matriz.construir(cfg, inst.coords)
            sol, cat, ev, diag = resolver_caso_base(
                inst,
                M,
                cfg,
                utilizacion_objetivo=a.utilizacion,
                radio_consolidacion_min=a.radio_consolidacion_min,
                max_candidatos_consolidacion=a.max_candidatos_consolidacion,
                usar_consolidacion=not a.sin_consolidacion,
            )

            valores = kpis.calcular(inst, cat, cfg, sol)
            revision = validacion.validar(inst, cat, cfg, sol, ev=ev)
            # Se conserva el prefijo BASE usado por graficar_ruta_dia.py y
            # validar_solucion.py. Así el nuevo caso base reemplaza al antiguo
            # sin modificar esas herramientas.
            sufijo = f"BASE_{a.tipo}_Instancia{i}_semana{w}"

            kpis.exportar(inst, cat, cfg, sol, valores, sufijo)
            exportar_planificacion(inst, cfg, diag, sufijo)

            with open(
                cfg.dir_salida / f"validacion_{sufijo}.txt",
                "w",
                encoding="utf-8",
            ) as fh:
                fh.write("ERRORES\n" + "\n".join(revision["errores"] or ["(ninguno)"]))
                fh.write("\n\nALERTAS\n" + "\n".join(revision["alertas"] or ["(ninguna)"]) + "\n")

            valores.update({
                "instancia": i,
                "semana": w,
                "errores_validacion": len(revision["errores"]),
                "alertas_validacion": len(revision["alertas"]),
                "tiempo_s": time.time() - t0,
            })
            filas.append(valores)

            print(
                f"[caso base informado] {a.tipo} I{i} S{w}: "
                f"costo ${valores['costo_total']:,.0f} | "
                f"{valores['vehiculos_activados']} vehículos | "
                f"ext {valores['solicitudes_externalizadas']} | "
                f"errores {len(revision['errores'])} | "
                f"{time.time() - t0:.0f}s"
            )

    resumen = pd.DataFrame(filas)
    columnas = ["instancia", "semana"] + [
        c for c in resumen.columns if c not in ("instancia", "semana")
    ]
    resumen = resumen[columnas]
    ruta_csv = Config().dir_salida / f"resumen_base_informado_{a.tipo}.csv"
    resumen.to_csv(ruta_csv, index=False)
    try:
        resumen.to_excel(
            Config().dir_salida / f"resumen_base_informado_{a.tipo}.xlsx",
            index=False,
        )
    except Exception:
        pass


if __name__ == "__main__":
    main()
