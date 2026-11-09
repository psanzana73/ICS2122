"""Algoritmo 1: matheurística de generación de columnas (GRASP + VND para el
pool inicial, pricing heurístico con duales) + maestro semanal de
particionamiento de conjuntos en Gurobi.

Uso:
    python main.py                                  # Instancia 1 small, semana 1
    python main.py --instancia "Instancia 3" --semana 2
    python main.py --tipo big --arranques 6 --iteraciones 2
    python main.py --sin-osmnx                      # fallback haversine
    python main.py --test                           # instancia de prueba (~5-10 min)
"""

from __future__ import annotations

import argparse
import random
import time

from matheuristica import (datos, diagnostico, escenarios, kpis as kpis_mod, maestro,
                           matriz, planes, validacion)
from matheuristica.completar import completar
from matheuristica.config import Config
from matheuristica.heuristica import (Pool, generar_columnas_semana, pricing_dia,
                                      sortear_asignacion, _tramos_del_dia,
                                      _vehiculos_del_dia)
from matheuristica.ruta import Evaluador


def parsear() -> Config:
    p = argparse.ArgumentParser(description="Matheurística de la red semanal de transporte sanitario")
    p.add_argument("--tipo", default="small", choices=["small", "big"])
    p.add_argument("--instancia", default="Instancia 1")
    p.add_argument("--semana", type=int, default=1)
    p.add_argument("--arranques", type=int, default=None)
    p.add_argument("--iteraciones", type=int, default=None)
    p.add_argument("--sin-osmnx", action="store_true")
    p.add_argument("--sin-reparacion", action="store_true")
    p.add_argument("--semilla", type=int, default=None)
    p.add_argument("--log-gurobi", action="store_true")
    p.add_argument("--time-limit", type=float, default=None)
    # recortes para prueba de concepto / licencia restringida de Gurobi
    p.add_argument("--dias", type=int, nargs="*", default=None,
                   help="subconjunto de días a resolver, p.ej. --dias 1 2")
    p.add_argument("--max-solicitudes", type=int, default=None,
                   help="trunca la instancia (prototipo o licencia pip de Gurobi)")
    p.add_argument("--max-vehiculos", type=int, default=None)
    p.add_argument("--max-columnas", type=int, default=None,
                   help="columnas por (vehículo, día) que sobreviven a la poda")
    p.add_argument("--test", action="store_true",
                   help="instancia de prueba: Instancia 1 small, semana 1, días 1 y 5 "
                        "(100 solicitudes, 17 divisiones obligatorias) con parámetros livianos")
    p.add_argument("--sin-completar", action="store_true",
                   help="desactiva la post-optimización por inserción (para comparar)")
    p.add_argument("--sin-cg", action="store_true",
                   help="desactiva el pricing con duales (solo pool GRASP+VND, como la v1)")
    p.add_argument("--cg-rondas", type=int, default=None, help="tope de rondas de pricing")
    p.add_argument("--peso-fijo", type=float, default=None,
                   help="peso de la cuota diaria del costo fijo en la heurística (0 = v1)")
    p.add_argument("--hubs-todas", action="store_true",
                   help="planes de transferencia para todas las solicitudes transferibles")
    p.add_argument("--sin-arranque-base", action="store_true",
                   help="no usar la solución del caso base como punto de partida")
    p.add_argument("--constructor", choices=["regret", "cronologico", "mixto"], default=None)
    p.add_argument("--peso-espera", type=float, default=None)
    p.add_argument("--posicionamiento-antiguo", action="store_true")
    p.add_argument("--hilos", type=int, default=None, help="hilos de Gurobi")
    p.add_argument("--work-limit", type=float, default=None,
                   help="límite determinista del maestro (unidades de trabajo de Gurobi)")
    p.add_argument("--escenario", default=None,
                   help="escenario de sensibilidad (ver matheuristica/escenarios.py)")
    p.add_argument("--etiqueta", default=None, help="sufijo extra para los archivos de salida")
    a = p.parse_args()

    if a.test:
        # Instancia de prueba. Días 1 y 5 de la Instancia 1 small, semana 1:
        #  - 100 solicitudes de 258, de las 4 clases;
        #  - 17 divisiones obligatorias (cantidad > 70) y 17 de las 23
        #    externalizaciones de la corrida completa original (el día 5 es el
        #    más cargado);
        #  - mantiene el acople semanal (activación de flota, bases, hubs),
        #    que se perdería con un solo día.
        # Usa la misma matriz cacheada que la corrida completa (mismos nodos).
        a.tipo, a.instancia, a.semana = "small", "Instancia 1", 1
        if a.dias is None:
            a.dias = [1, 5]
        if a.arranques is None:
            a.arranques = 4
        if a.iteraciones is None:
            a.iteraciones = 2
        if a.time_limit is None:
            a.time_limit = 120.0

    cfg = Config(tipo_instancia=a.tipo, hoja_instancia=a.instancia, semana=a.semana)
    if a.arranques is not None:
        cfg.n_arranques = a.arranques
    if a.iteraciones is not None:
        cfg.max_iteraciones = a.iteraciones
    if a.sin_osmnx:
        cfg.usar_osmnx = False
    if a.sin_reparacion:
        cfg.reparacion_activa = False
    if a.semilla is not None:
        cfg.semilla = a.semilla
    if a.time_limit is not None:
        cfg.time_limit_maestro = a.time_limit
    if a.max_columnas is not None:
        cfg.max_cols_por_vehiculo_dia = a.max_columnas
    cfg.log_gurobi = a.log_gurobi
    cfg.completar_activo = not a.sin_completar
    if a.sin_cg:
        cfg.cg_activa = False
    if a.cg_rondas is not None:
        cfg.cg_max_rondas = a.cg_rondas
    if a.peso_fijo is not None:
        cfg.peso_costo_fijo = a.peso_fijo
    if a.hubs_todas:
        cfg.hubs_todas = True
    if a.sin_arranque_base:
        cfg.arranque_caso_base = False
    if a.constructor:
        cfg.constructor = a.constructor
    if a.peso_espera is not None:
        cfg.peso_espera = a.peso_espera
    if a.posicionamiento_antiguo:
        cfg.posicionamiento_antiguo = True
    if a.hilos is not None:
        cfg.hilos_gurobi = a.hilos
    if a.work_limit is not None:
        cfg.work_limit_maestro = a.work_limit
    return cfg, a


def recortar(inst: datos.Instancia, a) -> None:
    """Recortes opcionales para la prueba de concepto."""
    if a.dias:
        inst.solicitudes = [s for s in inst.solicitudes if s.dia in set(a.dias)]
    if a.max_solicitudes:
        inst.solicitudes = inst.solicitudes[: a.max_solicitudes]
    if a.max_vehiculos:
        activos = set(list(inst.vehiculos)[: a.max_vehiculos])
        inst.vehiculos = {k: v for k, v in inst.vehiculos.items() if k in activos}
        inst.solicitudes = [
            datos.Solicitud(**{**s.__dict__, "vehiculos": frozenset(s.vehiculos & activos)})
            for s in inst.solicitudes
        ]


def ampliar_catalogo(inst, cat, M, cfg, criticas):
    """Genera planes de transferencia y división solo para las solicitudes críticas."""
    nuevos: dict[str, list[str]] = {}
    for s in inst.solicitudes:
        if s.id not in criticas:
            continue
        antes = set(cat.por_solicitud.get(s.id, []))
        for plan, tramos in planes.planes_split(s, cfg):
            cat.agregar(plan, tramos)
        for plan, tramos in planes.planes_transferencia(s, inst, M, cfg):
            cat.agregar(plan, tramos)
        despues = [p for p in cat.por_solicitud.get(s.id, []) if p not in antes]
        if despues:
            nuevos[s.id] = despues
    return nuevos


def _mejorar_con_vnd(ev, inst, cat, cfg, sol, pool):
    """[v2] Aplica el VND a las rutas de una solución completa, día por día, con
    su misma flota y posicionamiento. Las rutas mejoradas entran al pool."""
    from matheuristica.heuristica import SolucionDia, vnd
    rutas = []
    for d in inst.dias:
        s = SolucionDia(dia=d, asignacion=dict(sol.posicionamiento))
        for v in s.asignacion:
            s.paradas[v] = []
        for r in sol.rutas:
            if r.dia == d:
                s.paradas[r.vehiculo] = list(r.paradas)
                s.rutas[r.vehiculo] = r
        s = vnd(ev, cfg, cat, s)
        rutas += list(s.rutas.values())
        pool.agregar_solucion(s)
    nueva = maestro.armar_solucion(inst, cat, rutas, sol.planes, sol.externalizadas,
                                   sol.vehiculos, sol.posicionamiento, sol.bases, sol.hubs,
                                   cota=sol.cota_inferior, gap=sol.gap, duales=sol.duales)
    return nueva if nueva.costo < sol.costo - 1e-6 else sol


def _solucion_caso_base(inst, M, cfg, cat):
    """Resuelve el caso base y copia sus planes al catálogo de la matheurística."""
    import caso_base_2 as cb
    try:
        sol_b, cat_b, _, _ = cb.resolver_caso_base(inst, M, cfg)
    except Exception as err:            # el caso base nunca debe botar la corrida
        print(f"[inicial] caso base no disponible: {err}")
        return None
    for pid in sol_b.planes:
        if pid not in cat.planes:
            cat.agregar(cat_b.planes[pid], cat_b.tramos_de(pid))
    usados = {r.vehiculo for r in sol_b.rutas}
    return maestro.armar_solucion(inst, cat, sol_b.rutas, sol_b.planes, sol_b.externalizadas,
                                  sorted(usados),
                                  {k: b for k, b in sol_b.posicionamiento.items() if k in usados},
                                  [], sorted(sol_b.hubs), cota=0.0, gap=float("nan"))


def _solucion_inicial(inst, cat, cfg, ev, sols_grasp):
    """Convierte el mejor arranque GRASP+VND en una solución completa."""
    mejor = None
    for asignacion, rutas in sols_grasp:
        cubiertos = {t for r in rutas for t in r.tramos}
        planes_ok = sorted({cat.tramos[t].plan for t in cubiertos
                            if all(x in cubiertos for x in cat.planes[cat.tramos[t].plan].tramos)})
        rutas_ok = [r for r in rutas if all(cat.tramos[t].plan in set(planes_ok) for t in r.tramos)]
        atendidas = {cat.planes[p].solicitud for p in planes_ok}
        ext = sorted(s.id for s in inst.solicitudes if s.id not in atendidas)
        usados = {r.vehiculo for r in rutas_ok}
        sol = maestro.armar_solucion(inst, cat, rutas_ok, planes_ok, ext, sorted(usados),
                                     {k: b for k, b in asignacion.items() if k in usados},
                                     [], [], cota=0.0, gap=float("nan"))
        if mejor is None or sol.costo < mejor.costo:
            mejor = sol
    if mejor is not None and cfg.completar_activo and mejor.externalizadas:
        sol2, n = completar(ev, inst, cat, cfg, mejor)
        if n and sol2.costo < mejor.costo:
            mejor = sol2
    return mejor


def _posicionamientos_pricing(inst, M, cat, seleccion, lp, mejor, rng, cfg):
    """Posicionamientos vehículo-base sobre los que se resuelve el pricing.

    1) el sugerido por la relajación lineal (para cada vehículo, la base con
       mayor z_kb fraccional; si no tiene, la de la incumbente), completando con
       el sorteo sesgado a la demanda para los vehículos que quedan libres;
    2) en adelante, sorteos sesgados a la demanda (diversificación).
    """
    tramos = [t for d in inst.dias for t in _tramos_del_dia(inst, cat, seleccion, d)]
    vehiculos = _vehiculos_del_dia(inst, tramos, cat)
    salida = []
    zfrac = lp[2]
    base_lp = {}
    for (k, b), val in sorted(zfrac.items()):
        if val > base_lp.get(k, (None, 0.0))[1]:
            base_lp[k] = (b, val)
    parcial = {k: b for k, (b, _) in base_lp.items()}
    if mejor is not None:
        for k, b in mejor.posicionamiento.items():
            parcial.setdefault(k, b)
    cupo = {b: bb.capacidad for b, bb in inst.bases.items()}
    pos1 = {}
    for k in sorted(parcial):
        b = parcial[k]
        if cupo[b] > 0:
            pos1[k] = b
            cupo[b] -= 1
    resto = [v for v in vehiculos if v not in pos1]
    if resto:
        extra = sortear_asignacion(rng, inst, M, resto, tramos, cat)
        for k, b in extra.items():
            if cupo.get(b, 0) > 0:
                pos1[k] = b
                cupo[b] -= 1
    salida.append(pos1)
    for _ in range(max(0, cfg.cg_posicionamientos - 1)):
        salida.append(sortear_asignacion(rng, inst, M, vehiculos, tramos, cat))
    return salida


def main() -> None:
    cfg, args = parsear()
    t_inicio = time.time()
    rng = random.Random(cfg.semilla)

    print("=" * 74)
    print(f"  {cfg.hoja_instancia} ({cfg.tipo_instancia}) — semana {cfg.semana}")
    print("=" * 74)

    inst = datos.cargar(cfg)
    recortar(inst, args)
    escenarios.aplicar(args.escenario, inst, cfg)
    print(f"[datos] {len(inst.solicitudes)} solicitudes | {len(inst.vehiculos)} vehículos "
          f"| {len(inst.bases)} bases | {len(inst.hubs)} hubs")

    M = matriz.construir(cfg, inst.coords)
    escenarios.aplicar_matriz(args.escenario, M)
    cat, seleccion = planes.catalogo_inicial(inst, cfg)
    forzadas = sum(1 for s in inst.solicitudes if seleccion[s.id] != f"{s.id}#D")
    if forzadas:
        print(f"[planes] {forzadas} solicitudes exceden la capacidad de todo vehículo "
              f"compatible: entran con plan de división desde la primera iteración")
    diag = diagnostico.analizar(inst, M, cfg, cat)
    diagnostico.imprimir(diag)

    ev = Evaluador(inst, M, cfg, cat)
    pool = Pool(cfg)

    alternativas: dict[str, list[str]] = {}
    posicionamiento: dict[str, str] | None = None
    mejor: maestro.Solucion | None = None
    traza = []                    # una fila por iteración, para el informe

    for it in range(1, cfg.max_iteraciones + 1):
        print(f"\n--- iteración {it}/{cfg.max_iteraciones} " + "-" * 44)
        t0 = time.time()
        # (a) pool inicial: GRASP + VND con los planes vigentes
        sb = None
        sols_grasp = generar_columnas_semana(ev, inst, M, cfg, cat, seleccion, pool, rng,
                                             posicionamiento)
        if mejor is None and cfg.arranque_caso_base:
            # [v2] la solución del caso base (reglas) entra como columnas y
            # como candidata a solución inicial: la matheurística parte de la
            # mejor entre ella y el GRASP, y el maestro con generación de
            # columnas debe mejorarla.
            sb = _solucion_caso_base(inst, M, cfg, cat)
            if sb is not None:
                pool.proteger(sb.rutas)
                sb = _mejorar_con_vnd(ev, inst, cat, cfg, sb, pool)
                pool.proteger(sb.rutas)
                print(f"[inicial] caso base + VND como punto de partida: ${sb.costo:,.0f} "
                      f"| externalizadas = {len(sb.externalizadas)}")
        if mejor is None:
            # [v2] solución inicial: el mejor arranque GRASP+VND (una semana
            # completa y consistente) pasado por la post-optimización. Sirve de
            # punto de partida (MIP start) al primer maestro, que sin él no
            # alcanzaba a encontrar una buena solución entera en su límite.
            mejor = _solucion_inicial(inst, cat, cfg, ev, sols_grasp)
            if mejor is not None:
                pool.proteger(mejor.rutas)
                print(f"[inicial] mejor arranque GRASP+VND: ${mejor.costo:,.0f} "
                      f"| externalizadas = {len(mejor.externalizadas)}")
            if cfg.arranque_caso_base and sb is not None and (mejor is None or sb.costo < mejor.costo):
                mejor = sb
        # pasadas de coordinación: se fuerzan los planes alternativos de las
        # solicitudes críticas, para que el pool contenga columnas que cubran
        # AMBOS tramos de una transferencia (si no, el maestro no puede elegirla)
        if alternativas:
            for _ in range(2):
                sel = dict(seleccion)
                for r in sorted(alternativas):
                    if alternativas[r]:
                        sel[r] = rng.choice(alternativas[r])
                generar_columnas_semana(ev, inst, M, cfg, cat, sel, pool, rng,
                                        posicionamiento)
        pool.podar()
        t_grasp = time.time() - t0
        print(f"[pool] {len(pool.rutas)} columnas GRASP+VND ({t_grasp:.0f}s)")

        # (b) generación de columnas: relajación lineal -> pricing con duales
        t0 = time.time()
        lp = maestro.relajacion(inst, cat, cfg, pool.columnas())
        cota0 = lp[0]
        rondas, n_cg = 0, 0
        if cfg.cg_activa:
            for ronda in range(1, cfg.cg_max_rondas + 1):
                nuevas = 0
                for pos in _posicionamientos_pricing(inst, M, cat, seleccion, lp, mejor, rng, cfg):
                    for dia in inst.dias:
                        for r in pricing_dia(ev, inst, cfg, cat, dia, pos, lp[1]):
                            antes = len(pool.rutas)
                            pool.agregar(r)
                            nuevas += len(pool.rutas) - antes
                rondas = ronda
                n_cg += nuevas
                if not nuevas:
                    print(f"[cg] ronda {ronda}: sin columnas de costo reducido negativo")
                    break
                cota_ant = lp[0]
                lp = maestro.relajacion(inst, cat, cfg, pool.columnas())
                mejora = (cota_ant - lp[0]) / cota_ant if cota_ant else 0.0
                print(f"[cg] ronda {ronda}: +{nuevas} columnas | cota LP ${cota_ant:,.0f} "
                      f"-> ${lp[0]:,.0f} ({100*mejora:.2f}%)")
                if mejora < cfg.cg_tol_mejora:
                    break
        t_cg = time.time() - t0

        # (c) maestro entero sobre el pool final
        t0 = time.time()
        sol = maestro.resolver(inst, cat, cfg, pool.columnas(), inicio=mejor, lp=lp)
        t_maestro = time.time() - t0
        print(f"[maestro] costo = ${sol.costo:,.0f} | cota LP pool = ${sol.cota_inferior:,.0f} "
              f"| gap MIP = {100*sol.gap:.2f}% | externalizadas = {len(sol.externalizadas)} "
              f"({t_maestro:.0f}s)")
        costo_maestro, ext_maestro = sol.costo, len(sol.externalizadas)

        # (d) post-optimización: insertar externalizadas en rutas / vehículo-días ociosos
        n_resc = 0
        if cfg.completar_activo and sol.externalizadas:
            t0 = time.time()
            sol2, n_resc = completar(ev, inst, cat, cfg, sol)
            if n_resc and sol2.costo < sol.costo - 1e-6:
                print(f"[completar] {n_resc} externalizadas rescatadas por inserción: "
                      f"${sol.costo:,.0f} -> ${sol2.costo:,.0f} "
                      f"| externalizadas = {len(sol2.externalizadas)} ({time.time()-t0:.0f}s)")
                sol = sol2
            else:
                n_resc = 0
                print(f"[completar] ninguna inserción factible más barata que externalizar "
                      f"({time.time()-t0:.0f}s)")

        # [v2] el VND también mejora la solución de esta vuelta
        sol = _mejorar_con_vnd(ev, inst, cat, cfg, sol, pool)
        posicionamiento = sol.posicionamiento or None
        if mejor is None or sol.costo <= mejor.costo + 1e-6:
            mejor = sol
        # las columnas de la incumbente nunca se podan y arrancan el próximo maestro
        pool.proteger(mejor.rutas)
        traza.append(dict(iteracion=it, columnas=len(pool.rutas), cota_lp_grasp=cota0,
                          cota_lp_final=lp[0], rondas_cg=rondas, columnas_cg=n_cg,
                          costo_maestro=costo_maestro, ext_maestro=ext_maestro,
                          rescatadas=n_resc, costo_incumbente=mejor.costo,
                          t_grasp=t_grasp, t_cg=t_cg, t_maestro=t_maestro))

        if it < cfg.max_iteraciones and cfg.reparacion_activa:
            criticas = set(sol.externalizadas)
            for r in sol.rutas:
                for (tid, tipo), t in zip(r.paradas, r.tiempos):
                    tr = cat.tramos[tid]
                    if tipo == 1 and (t + tr.serv_delivery) > tr.due_delivery + 1e-6:
                        criticas.add(tr.solicitud)
            # [v2] orden determinista: primero las externalizadas y, entre ellas,
            # las de mayor penalización (antes se cortaba un set sin orden)
            pen = {s.id: s.penal_externalizacion for s in inst.solicitudes}
            ext_set = set(sol.externalizadas)
            orden = sorted(criticas, key=lambda r: (r not in ext_set, -pen[r], r))
            criticas = set(orden[: cfg.max_criticas_por_dia * len(inst.dias)])
            if cfg.hubs_todas:
                criticas |= {s.id for s in inst.solicitudes if s.transferible}
            if criticas:
                nuevos = ampliar_catalogo(inst, cat, M, cfg, criticas)
                for r, ps in nuevos.items():
                    alternativas.setdefault(r, []).extend(ps)
                n_planes = sum(len(v) for v in nuevos.values())
                print(f"[reparación] {len(criticas)} solicitudes críticas "
                      f"-> {n_planes} planes nuevos (transferencia/división)")

    assert mejor is not None
    if traza and traza[-1]["rescatadas"]:
        # cierre: el maestro vuelve a resolverse con las columnas de la
        # inserción en el pool y la incumbente como arranque, para que la cota
        # LP y el gap reportados correspondan al pool final.
        t0 = time.time()
        pool.proteger(mejor.rutas)
        fin = maestro.resolver(inst, cat, cfg, pool.columnas(), inicio=mejor)
        print(f"\n[maestro final] costo = ${fin.costo:,.0f} | cota LP pool = "
              f"${fin.cota_inferior:,.0f} | gap MIP = {100*fin.gap:.2f}% ({time.time()-t0:.0f}s)")
        # [v2] la solución del maestro final también pasa por la post-optimización
        if cfg.completar_activo and fin.externalizadas:
            fin2, n = completar(ev, inst, cat, cfg, fin)
            if n and fin2.costo < fin.costo - 1e-6:
                fin = fin2
        if fin.costo <= mejor.costo + 1e-6:
            mejor = fin
        else:
            mejor.cota_inferior = fin.cota_inferior
    k = kpis_mod.calcular(inst, cat, cfg, mejor, M)
    sufijo = (f"{cfg.tipo_instancia}_{cfg.hoja_instancia.replace(' ', '')}"
              f"_semana{cfg.semana}")
    if args.test:
        sufijo = "TEST_" + sufijo
    elif args.dias:
        sufijo += "_dias" + "".join(map(str, args.dias))
    if args.escenario and args.escenario != "base":
        sufijo += "_esc-" + args.escenario
    if args.etiqueta:
        sufijo += "_" + args.etiqueta
    k["externalizacion_forzosa"] = diag["externalizacion_forzosa"]
    k["externalizacion_evitable"] = max(
        0, k["solicitudes_externalizadas"] - diag["externalizacion_forzosa"])
    kpis_mod.exportar(inst, cat, cfg, mejor, k, sufijo)
    import pandas as pd
    pd.DataFrame(diag["detalle"]).to_csv(
        cfg.dir_salida / f"diagnostico_{sufijo}.csv", index=False)
    pd.DataFrame(traza).to_csv(cfg.dir_salida / f"traza_{sufijo}.csv", index=False)

    print("\n" + "=" * 74)
    print("  RESULTADOS")
    print("=" * 74)
    for nombre, valor in k.items():
        if isinstance(valor, float):
            print(f"  {nombre:.<44} {valor:>14,.2f}")
        else:
            print(f"  {nombre:.<44} {valor:>14}")
    res = validacion.validar(inst, cat, cfg, mejor, ev=ev)
    validacion.imprimir(res)
    with open(cfg.dir_salida / f"validacion_{sufijo}.txt", "w", encoding="utf-8") as fh:
        fh.write("ERRORES\n" + "\n".join(res["errores"] or ["(ninguno)"]))
        fh.write("\n\nALERTAS\n" + "\n".join(res["alertas"] or ["(ninguna)"]) + "\n")

    print(f"\n  tiempo total {time.time()-t_inicio:.0f}s "
          f"| salidas en {cfg.dir_salida}/*_{sufijo}.csv")


if __name__ == "__main__":
    main()
