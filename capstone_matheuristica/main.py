"""Algoritmo 1: matheurística de generación de columnas heurística
+ maestro semanal de particionamiento de conjuntos en Gurobi.

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

from matheuristica import (datos, diagnostico, kpis as kpis_mod, maestro,
                           matriz, planes, validacion)
from matheuristica.completar import completar
from matheuristica.config import Config
from matheuristica.heuristica import Pool, generar_columnas_semana
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


def main() -> None:
    cfg, args = parsear()
    t_inicio = time.time()
    rng = random.Random(cfg.semilla)

    print("=" * 74)
    print(f"  {cfg.hoja_instancia} ({cfg.tipo_instancia}) — semana {cfg.semana}")
    print("=" * 74)

    inst = datos.cargar(cfg)
    recortar(inst, args)
    print(f"[datos] {len(inst.solicitudes)} solicitudes | {len(inst.vehiculos)} vehículos "
          f"| {len(inst.bases)} bases | {len(inst.hubs)} hubs")

    M = matriz.construir(cfg, inst.coords)
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
    duales: dict[str, float] = {}
    posicionamiento: dict[str, str] | None = None
    mejor: maestro.Solucion | None = None
    completo_mejoro = False

    for it in range(1, cfg.max_iteraciones + 1):
        print(f"\n--- iteración {it}/{cfg.max_iteraciones} " + "-" * 44)
        t0 = time.time()
        # pasada base: planes directos (+ divisiones estructurales)
        generar_columnas_semana(ev, inst, M, cfg, cat, seleccion, pool, rng,
                                duales, posicionamiento)
        # pasadas de coordinación: se fuerzan los planes alternativos de las
        # solicitudes críticas, para que el pool contenga columnas que cubran
        # AMBOS tramos de una transferencia (si no, el maestro no puede elegirla)
        if alternativas:
            for _ in range(2):
                sel = dict(seleccion)
                for r, ps in alternativas.items():
                    if ps:
                        sel[r] = rng.choice(ps)
                generar_columnas_semana(ev, inst, M, cfg, cat, sel, pool, rng,
                                        duales, posicionamiento)
        pool.podar()
        print(f"[pool] {len(pool.rutas)} columnas ({time.time()-t0:.0f}s)")

        t0 = time.time()
        sol = maestro.resolver(inst, cat, cfg, pool.columnas(), inicio=mejor)
        duales = sol.duales
        print(f"[maestro] costo = ${sol.costo:,.0f} | cota LP pool = ${sol.cota_inferior:,.0f} "
              f"| gap MIP = {100*sol.gap:.2f}% | externalizadas = {len(sol.externalizadas)} "
              f"({time.time()-t0:.0f}s)")

        # post-optimización: insertar externalizadas en rutas / vehículo-días ociosos
        if cfg.completar_activo and sol.externalizadas:
            t0 = time.time()
            sol2, n = completar(ev, inst, cat, cfg, sol)
            completo_mejoro = bool(n) and sol2.costo < sol.costo - 1e-6
            if n:
                print(f"[completar] {n} externalizadas rescatadas por inserción: "
                      f"${sol.costo:,.0f} -> ${sol2.costo:,.0f} "
                      f"| externalizadas = {len(sol2.externalizadas)} ({time.time()-t0:.0f}s)")
                sol = sol2
            else:
                print(f"[completar] ninguna inserción factible más barata que externalizar "
                      f"({time.time()-t0:.0f}s)")

        posicionamiento = sol.posicionamiento or None
        if mejor is None or sol.costo <= mejor.costo + 1e-6:   # a igual costo, la más nueva (cota LP vigente)
            mejor = sol
        # las columnas de la incumbente nunca se podan y arrancan el próximo maestro
        pool.proteger(mejor.rutas)

        if it < cfg.max_iteraciones and cfg.reparacion_activa:
            criticas = set(sol.externalizadas)
            for r in sol.rutas:
                for (tid, tipo), t in zip(r.paradas, r.tiempos):
                    tr = cat.tramos[tid]
                    if tipo == 1 and (t + tr.serv_delivery) > tr.due_delivery + 1e-6:
                        criticas.add(tr.solicitud)
            criticas = set(list(criticas)[: cfg.max_criticas_por_dia * len(inst.dias)])
            if criticas:
                nuevos = ampliar_catalogo(inst, cat, M, cfg, criticas)
                for r, ps in nuevos.items():
                    alternativas.setdefault(r, []).extend(ps)
                n_planes = sum(len(v) for v in nuevos.values())
                print(f"[reparación] {len(criticas)} solicitudes críticas "
                      f"-> {n_planes} planes nuevos (transferencia/división)")

    assert mejor is not None
    if completo_mejoro:
        # cierre: el maestro vuelve a resolverse con las columnas de la
        # inserción en el pool y la incumbente como arranque, para que la cota
        # LP y el gap reportados correspondan al pool final.
        t0 = time.time()
        pool.proteger(mejor.rutas)
        fin = maestro.resolver(inst, cat, cfg, pool.columnas(), inicio=mejor)
        print(f"\n[maestro final] costo = ${fin.costo:,.0f} | cota LP pool = "
              f"${fin.cota_inferior:,.0f} | gap MIP = {100*fin.gap:.2f}% ({time.time()-t0:.0f}s)")
        if fin.costo <= mejor.costo + 1e-6:
            mejor = fin
        else:
            mejor.cota_inferior = fin.cota_inferior
    k = kpis_mod.calcular(inst, cat, cfg, mejor)
    sufijo = (f"{cfg.tipo_instancia}_{cfg.hoja_instancia.replace(' ', '')}"
              f"_semana{cfg.semana}")
    if args.test:
        sufijo = "TEST_" + sufijo
    elif args.dias:
        sufijo += "_dias" + "".join(map(str, args.dias))
    k["externalizacion_forzosa"] = diag["externalizacion_forzosa"]
    k["externalizacion_evitable"] = max(
        0, k["solicitudes_externalizadas"] - diag["externalizacion_forzosa"])
    kpis_mod.exportar(inst, cat, cfg, mejor, k, sufijo)
    import pandas as pd
    pd.DataFrame(diag["detalle"]).to_csv(
        cfg.dir_salida / f"diagnostico_{sufijo}.csv", index=False)

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
