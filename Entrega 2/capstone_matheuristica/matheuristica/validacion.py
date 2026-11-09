"""Validación independiente de la solución final.

No reutiliza `Evaluador`: vuelve a revisar, desde los datos originales, cada
restricción del modelo sobre la solución que se va a reportar. Si algo falla
acá, hay un bug en la generación de columnas o en el maestro.

Errores (la solución viola el modelo):
  cobertura, un plan por solicitud, ventanas de retiro, apertura de entrega,
  tardanza en clases que no la admiten, max_transport extremo a extremo (S2,
  sin reinicio en el hub), capacidad, incompatibilidad a bordo, una ruta por
  vehículo-día desde su base semanal, capacidad de bases, jornada 08:00 +
  sobretiempo <= Θ (S1), sobretiempo reportado = retorno - 17:00, partes de
  una división / piernas de una transferencia en vehículos distintos.

Alertas de coherencia (la solución es factible pero sospechosa):
  solicitudes externalizadas que un vehículo-día ya pagado y ocioso podía
  atender (se verifica con `Evaluador`: capacidad, ventanas, jornada, plazos).
"""

from __future__ import annotations

from collections import defaultdict

from .config import Config
from .datos import Instancia
from .maestro import Solucion
from .planes import Catalogo

EPS = 1e-6


def _atendible_con_ociosos(ev, cat, s, ociosos, posic) -> list[str] | None:
    """¿Algún plan de `s` se puede atender completo usando solo vehículo-días
    ociosos (ruta vacía, un tramo por vehículo distinto)? Devuelve los vehículos
    que lo harían, o None. Revisa capacidad, ventanas, jornada y plazos reales."""
    for pid in cat.por_solicitud.get(s.id, []):
        libres = list(ociosos)
        usados = []
        for tr in sorted(cat.tramos_de(pid), key=lambda t: -t.cantidad):
            elegido = next((k for k in libres
                            if ev.evaluar([(tr.id, 0), (tr.id, 1)], k, posic[k], s.dia)),
                           None)
            if elegido is None:
                usados = None
                break
            libres.remove(elegido)
            usados.append(elegido)
        if usados:
            return usados
    return None


def validar(inst: Instancia, cat: Catalogo, cfg: Config, sol: Solucion,
            ev=None) -> dict:
    err: list[str] = []
    alerta: list[str] = []
    S = {s.id: s for s in inst.solicitudes}

    # ------------------------------------------------ un plan por solicitud
    planes_por_sol = defaultdict(list)
    for p in sol.planes:
        planes_por_sol[cat.planes[p].solicitud].append(p)
    ext = set(sol.externalizadas)
    for s in inst.solicitudes:
        n = len(planes_por_sol.get(s.id, [])) + (1 if s.id in ext else 0)
        if n != 1:
            err.append(f"{s.id}: {n} modalidades (planes + externalización), debe ser 1")

    # ------------------------------------------------ cobertura de tramos
    donde: dict[str, list] = defaultdict(list)       # tramo -> [(ruta, idx_pick, idx_drop)]
    for r in sol.rutas:
        pos = {}
        for i, (tid, tipo) in enumerate(r.paradas):
            pos.setdefault(tid, {})[tipo] = i
        for tid, d in pos.items():
            donde[tid].append((r, d.get(0), d.get(1)))
    for p in sol.planes:
        for tid in cat.planes[p].tramos:
            if len(donde.get(tid, [])) != 1:
                err.append(f"tramo {tid}: cubierto {len(donde.get(tid, []))} veces")
    planes_sel = set(sol.planes)
    for tid in donde:
        if cat.tramos[tid].plan not in planes_sel:
            err.append(f"tramo {tid} en una ruta pero su plan no está elegido")

    # ------------------------------------------------ por plan
    for p in sol.planes:
        pl = cat.planes[p]
        s = S[pl.solicitud]
        ts = [cat.tramos[t] for t in pl.tramos]
        if any(len(donde.get(t.id, [])) != 1 for t in ts):
            continue
        vehs = [donde[t.id][0][0].vehiculo for t in ts]
        if len(set(vehs)) != len(vehs):
            err.append(f"{p}: {len(vehs)} tramos en solo {len(set(vehs))} vehículo(s)")
        if pl.tipo == "split":
            if not s.divisible:
                err.append(f"{p}: división de una solicitud no divisible")
            if len(ts) > s.max_vehiculos_split:
                err.append(f"{p}: {len(ts)} partes > max_split_vehicles={s.max_vehiculos_split}")
            if min(t.cantidad for t in ts) < s.min_cantidad_split:
                err.append(f"{p}: parte bajo min_split_quantity")
            if sum(t.cantidad for t in ts) != s.cantidad:
                err.append(f"{p}: las partes no suman la cantidad")
        if pl.tipo == "transferencia" and not s.transferible:
            err.append(f"{p}: transferencia de una solicitud no transferible")

        # unidades de servicio: (tramo que retira en el origen, tramo que entrega en el destino)
        if pl.tipo == "transferencia":
            a, b = ts
            ra, ia_p, ia_d = donde[a.id][0]
            rb, ib_p, ib_d = donde[b.id][0]
            drop_fin = ra.tiempos[ia_d] + a.serv_delivery
            if rb.tiempos[ib_p] < drop_fin - EPS:
                err.append(f"{p}: se recarga en el hub antes de terminar la descarga")
            hh = inst.hubs[pl.hub]
            if ra.tiempos[ia_d] < hh.apertura - EPS or rb.tiempos[ib_p] + b.serv_pickup > hh.cierre + EPS:
                err.append(f"{p}: operación fuera del horario del hub")
            unidades = [(ra, ia_p, rb, ib_d)]
        else:
            unidades = [(donde[t.id][0][0], donde[t.id][0][1], donde[t.id][0][0], donde[t.id][0][2])
                        for t in ts]
        for rp, ip, rd, idd in unidades:
            if ip is None or idd is None or (rp is rd and ip > idd):
                err.append(f"{p}: retiro/entrega faltante o en orden inverso")
                continue
            t_pick, t_drop = rp.tiempos[ip], rd.tiempos[idd]
            if rp.dia != s.dia or rd.dia != s.dia:
                err.append(f"{p}: atendida en un día distinto")
            if not (s.ini_pickup - EPS <= t_pick <= s.fin_pickup + EPS):
                err.append(f"{p}: retiro a los {t_pick:.1f} fuera de [{s.ini_pickup},{s.fin_pickup}]")
            if t_drop < s.ini_delivery - EPS:
                err.append(f"{p}: entrega antes de la apertura")
            fin_entrega = t_drop + s.serv_delivery
            tarde = fin_entrega - s.due_delivery
            if tarde > EPS and not s.tardanza_ok:
                err.append(f"{p}: tardanza {tarde:.1f} min en una clase que no la admite")
            if tarde > cfg.tardanza_max + EPS:
                err.append(f"{p}: tardanza {tarde:.1f} min > tope {cfg.tardanza_max}")
            viaje = fin_entrega - (t_pick + s.serv_pickup)            # (S2)
            if viaje > s.max_transport + EPS:
                err.append(f"{p}: max_transport {viaje:.1f} > {s.max_transport} (S2)")

    # ------------------------------------------------ por ruta
    vd = defaultdict(int)
    for r in sol.rutas:
        vd[(r.vehiculo, r.dia)] += 1
        veh = inst.vehiculos[r.vehiculo]
        if sol.posicionamiento.get(r.vehiculo) != r.base:
            err.append(f"{r.vehiculo} d{r.dia}: sale de {r.base}, su base semanal es "
                       f"{sol.posicionamiento.get(r.vehiculo)}")
        carga, abordo = 0, {}
        fin_prev = r.salida
        for (tid, tipo), t in zip(r.paradas, r.tiempos):
            tr = cat.tramos[tid]
            if r.vehiculo not in tr.vehiculos or tr.clase not in veh.clases_compatibles:
                err.append(f"{r.vehiculo} d{r.dia}: vehículo incompatible con {tid}")
            if t < fin_prev - EPS:
                err.append(f"{r.vehiculo} d{r.dia}: servicios solapados en {tid}")
            fin_prev = t + (tr.serv_pickup if tipo == 0 else tr.serv_delivery)
            if tipo == 0:
                carga += tr.cantidad
                abordo[tid] = tr.clase
            else:
                carga -= tr.cantidad
                abordo.pop(tid, None)
            if carga > veh.capacidad:
                err.append(f"{r.vehiculo} d{r.dia}: carga {carga} > capacidad {veh.capacidad}")
            clases = set(abordo.values())
            for par in inst.incompatibles:
                if set(par) <= clases:
                    err.append(f"{r.vehiculo} d{r.dia}: {sorted(par)} a bordo a la vez")
        if r.salida < cfg.jornada_inicio - EPS:
            err.append(f"{r.vehiculo} d{r.dia}: sale antes de las 08:00")
        ot = max(0.0, r.retorno - cfg.jornada_fin)                     # (S1)
        if ot > cfg.sobretiempo_max + EPS:
            err.append(f"{r.vehiculo} d{r.dia}: sobretiempo {ot:.1f} > Θ={cfg.sobretiempo_max}")
        if abs(ot - r.sobretiempo) > 0.01:
            err.append(f"{r.vehiculo} d{r.dia}: sobretiempo reportado {r.sobretiempo:.1f} "
                       f"≠ retorno-17:00 = {ot:.1f}")
    for (k, d), n in vd.items():
        if n > 1:
            err.append(f"{k} d{d}: {n} rutas el mismo día")
    ocup = defaultdict(int)
    for k, b in sol.posicionamiento.items():
        ocup[b] += 1
    for b, n in ocup.items():
        if n > inst.bases[b].capacidad:
            err.append(f"base {b}: {n} vehículos > capacidad {inst.bases[b].capacidad}")

    # ------------------------------------------------ coherencia económica
    usados = {(r.vehiculo, r.dia) for r in sol.rutas}
    n_pagados = len(sol.posicionamiento) * len(inst.dias)
    for rid in sorted(ext):
        s = S[rid]
        ociosos = [k for k in sol.posicionamiento
                   if k in s.vehiculos and s.clase in inst.vehiculos[k].clases_compatibles
                   and (k, s.dia) not in usados]
        if not ociosos:
            continue
        # [fix] antes bastaba con que el vehículo fuera compatible: D1_R20
        # (EQUIPO_RETORNO, q=46, no divisible) generaba alerta por una
        # VAN_GENERAL de capacidad 30 que nunca podría llevarla. Ahora se exige
        # que el vehículo ocioso pueda de verdad atender algún plan completo.
        if ev is not None:
            quienes = _atendible_con_ociosos(ev, cat, s, sorted(ociosos), sol.posicionamiento)
            if quienes is None:
                continue
        else:
            quienes = [k for k in ociosos if inst.vehiculos[k].capacidad >= s.cantidad]
            if not quienes and not (s.divisible and sum(sorted(
                    (inst.vehiculos[k].capacidad for k in ociosos), reverse=True)
                    [:s.max_vehiculos_split]) >= s.cantidad):
                continue
        alerta.append(f"{rid} (día {s.dia}, {s.clase}, q={s.cantidad}, "
                      f"penalización ${s.penal_externalizacion:,.0f}) externalizada aunque "
                      f"vehículos ya pagados sin salir podían atenderla: {', '.join(quienes or ociosos)}")

    return {"errores": err, "alertas": alerta,
            "vehiculo_dias_usados": len(usados), "vehiculo_dias_pagados": n_pagados}


def imprimir(res: dict) -> None:
    print("\n" + "=" * 74)
    print("  VALIDACIÓN INDEPENDIENTE")
    print("=" * 74)
    print(f"  vehículo-días usados / pagados: {res['vehiculo_dias_usados']} / "
          f"{res['vehiculo_dias_pagados']}")
    if not res["errores"]:
        print("  OK: la solución cumple todas las restricciones del modelo")
    else:
        print(f"  {len(res['errores'])} ERRORES:")
        for e in res["errores"][:40]:
            print("    x", e)
    if res["alertas"]:
        print(f"  {len(res['alertas'])} alertas de coherencia:")
        for a in res["alertas"][:40]:
            print("    !", a)
    else:
        print("  OK: ninguna externalización con vehículos ya pagados ociosos ese día")
