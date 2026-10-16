"""Post-optimización por inserción: completar la solución del maestro.

Problema que corrige: el maestro solo puede combinar columnas que ya están en
el pool. Si ninguna columna de un vehículo-día ocioso (vehículo ya activado y
pagado, que ese día no sale) contiene a una solicitud externalizada, el maestro
paga la penalización de $190-230 mil aunque atenderla cueste $20-60 mil en km.
En la Instancia 1 small las 23 externalizadas estaban en días con vehículos
compatibles ociosos.

Qué hace: parte de la solución del maestro y, para cada solicitud
externalizada, prueba cada uno de sus planes (directo, divisiones,
transferencias) insertando cada tramo en un vehículo DISTINTO (ruta existente o
vehículo-día ocioso; opcionalmente activando un vehículo nuevo en una base
abierta con cupo). Acepta el plan si su costo marginal real es menor que la
penalización. Las rutas modificadas forman una solución completa y consistente
que (i) entra al pool protegida y (ii) se usa como arranque (MIP start) del
maestro siguiente, así que el costo nunca empeora entre iteraciones.
"""

from __future__ import annotations

from .config import Config
from .datos import Instancia
from .maestro import Solucion, armar_solucion
from .planes import Catalogo
from .ruta import DROP, PICK, Evaluador, Ruta

MAX_DESFASE = 10


def _insertar(ev: Evaluador, paradas: list, tid: str, veh: str, base: str, dia: int,
              costo_actual: float):
    """Mejor inserción del par (retiro, entrega) por costo REAL (no heurístico)."""
    n = len(paradas)
    mejor = None
    for i in range(n + 1):
        parcial = paradas[:i] + [(tid, PICK)] + paradas[i:]
        for j in range(i + 1, min(n + 1, i + MAX_DESFASE) + 1):
            nuevas = parcial[:j] + [(tid, DROP)] + parcial[j:]
            r = ev.evaluar(nuevas, veh, base, dia)
            if r is None:
                continue
            delta = r.costo - costo_actual
            if mejor is None or delta < mejor[0] - 1e-9:
                mejor = (delta, r)
    return mejor


def completar(ev: Evaluador, inst: Instancia, cat: Catalogo, cfg: Config,
              sol: Solucion) -> tuple[Solucion, int]:
    """Inserción + activación de vehículos. Devuelve (solución, n.º rescatadas).

    Fase 1: insertar en vehículos ya activados (rutas existentes o días ociosos).
    Fase 2: activar vehículos nuevos. El costo fijo semanal de un vehículo no se
    puede cargar a una sola solicitud (casi nunca convendría), así que se prueba
    activar un vehículo de cada clase en cada base abierta con cupo, se corre la
    fase 1 con él disponible y se acepta la activación si el ahorro total de la
    semana supera su costo fijo. Se repite mientras haya mejora.
    """
    sol, n = _insertar_externalizadas(ev, inst, cat, cfg, sol)
    total = n
    while sol.externalizadas:
        mejor = None
        activos = set(sol.posicionamiento)
        libres = [k for k in inst.vehiculos if k not in activos]
        # un representante por clase de vehículo (son idénticos salvo el id)
        reps = {}
        for k in sorted(libres):
            reps.setdefault(inst.vehiculos[k].clase, k)
        ocup = {b: 0 for b in inst.bases}
        for b in sol.posicionamiento.values():
            ocup[b] += 1
        for k in reps.values():
            for b in sorted(set(sol.posicionamiento.values())):
                if ocup[b] >= inst.bases[b].capacidad:
                    continue
                prueba = armar_solucion(
                    inst, cat, sol.rutas, sol.planes, sol.externalizadas,
                    sol.vehiculos, sol.posicionamiento, sol.bases, sol.hubs,
                    cota=sol.cota_inferior, gap=sol.gap, duales=sol.duales)
                prueba.posicionamiento[k] = b
                prueba.vehiculos.append(k)
                cand, m = _insertar_externalizadas(ev, inst, cat, cfg, prueba,
                                                   gratis={k})
                if m and (mejor is None or cand.costo < mejor[0].costo):
                    mejor = (cand, m)
        if mejor is None or mejor[0].costo >= sol.costo - 1e-6:
            break
        sol, m = mejor
        total += m
    return sol, total


def _insertar_externalizadas(ev: Evaluador, inst: Instancia, cat: Catalogo, cfg: Config,
                             sol: Solucion, gratis: set[str] = frozenset()
                             ) -> tuple[Solucion, int]:
    """Fase 1. `gratis`: vehículos recién activados cuyo costo fijo se evalúa
    afuera (en `completar`), sobre el ahorro de toda la semana."""
    if not sol.externalizadas:
        return sol, 0

    rutas: dict[tuple, Ruta] = {(r.vehiculo, r.dia): r for r in sol.rutas}
    posic = dict(sol.posicionamiento)
    vehs = set(sol.vehiculos)
    bases = set(sol.bases)
    hubs = set(sol.hubs)
    planes = list(sol.planes)
    ext = set(sol.externalizadas)
    ocupacion = {b: sum(1 for v in posic.values() if v == b) for b in inst.bases}
    uso_hub: dict[tuple, list[float]] = {}
    for p in planes:
        pl = cat.planes[p]
        if pl.hub:
            u = uso_hub.setdefault((pl.hub, pl.dia), [0, 0.0])
            u[0] += pl.n_ops_hub
            u[1] += pl.cantidad_hub

    sol_por_id = {s.id: s for s in inst.solicitudes}
    orden = sorted(ext, key=lambda r: (sol_por_id[r].dia, -sol_por_id[r].penal_externalizacion))
    rescatadas = 0

    for rid in orden:
        s = sol_por_id[rid]
        mejor_plan = None      # (costo_marginal, plan_id, {(v,d): Ruta}, activaciones{v: base})
        for pid in cat.por_solicitud.get(rid, []):
            pl = cat.planes[pid]
            costo = pl.costo_handling * pl.n_ops_hub
            if pl.hub:
                hh = inst.hubs[pl.hub]
                u = uso_hub.get((pl.hub, pl.dia), [0, 0.0])
                if (u[0] + pl.n_ops_hub > hh.cap_diaria_ops
                        or u[1] + pl.cantidad_hub > hh.cap_diaria_cantidad):
                    continue
                if pl.hub not in hubs:
                    costo += hh.costo_fijo
            cambios: dict[tuple, Ruta] = {}
            activ: dict[str, str] = {}
            usados: set[str] = set()
            ok = True
            tramos = sorted(cat.tramos_de(pid), key=lambda t: -t.cantidad)
            for tr in tramos:
                best = None
                for v in tr.vehiculos:
                    if v in usados or v not in inst.vehiculos:
                        continue
                    if tr.clase not in inst.vehiculos[v].clases_compatibles:
                        continue
                    if v not in posic:
                        continue           # activar vehículos: fase 2
                    opciones = [(posic[v], 0.0)]
                    for b, fijo in opciones:
                        actual = cambios.get((v, s.dia)) or rutas.get((v, s.dia))
                        par = list(actual.paradas) if actual else []
                        m = _insertar(ev, par, tr.id, v, b, s.dia,
                                      actual.costo if actual else 0.0)
                        if m is None:
                            continue
                        c = m[0] + fijo
                        if best is None or c < best[0]:
                            best = (c, v, b, m[1], fijo > 0)
                if best is None:
                    ok = False
                    break
                c, v, b, r, nuevo = best
                costo += c
                usados.add(v)
                cambios[(v, s.dia)] = r
                if nuevo:
                    activ[v] = b
            if not ok:
                continue
            if mejor_plan is None or costo < mejor_plan[0]:
                mejor_plan = (costo, pid, cambios, activ)

        if mejor_plan is None or mejor_plan[0] >= s.penal_externalizacion - 1e-6:
            continue
        _, pid, cambios, activ = mejor_plan
        rutas.update(cambios)
        for v, b in activ.items():
            posic[v] = b
            vehs.add(v)
            ocupacion[b] += 1
        pl = cat.planes[pid]
        if pl.hub:
            hubs.add(pl.hub)
            u = uso_hub.setdefault((pl.hub, pl.dia), [0, 0.0])
            u[0] += pl.n_ops_hub
            u[1] += pl.cantidad_hub
        planes.append(pid)
        ext.discard(rid)
        rescatadas += 1

    if not rescatadas:
        return sol, 0
    nueva = armar_solucion(inst, cat, list(rutas.values()), planes, sorted(ext),
                           sorted(vehs), posic, sorted(bases), sorted(hubs),
                           cota=sol.cota_inferior, gap=sol.gap, duales=sol.duales)
    return nueva, rescatadas
