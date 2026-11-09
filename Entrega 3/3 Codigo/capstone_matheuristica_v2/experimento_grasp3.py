"""Experimento: calidad de la solución inicial GRASP+VND según su configuración.

    python experimento_grasp.py --instancia 10 --semana 1
Para cada configuración corre 5 arranques y reporta la mejor solución completa
(después de la post-optimización), como la usa main.py para partir.
"""
import argparse, itertools, random, time
import pandas as pd
from matheuristica import datos, matriz, planes
from matheuristica.config import Config
from matheuristica.heuristica import Pool, generar_columnas_semana
from matheuristica.ruta import Evaluador
import main as mn

ap = argparse.ArgumentParser()
ap.add_argument("--instancia", type=int, default=10)
ap.add_argument("--semana", type=int, default=1)
ap.add_argument("--arranques", type=int, default=5)
a = ap.parse_args()
filas = []
import sys
CONFIGS = [(c, fr, esp, 0.0) for c in ["cronologico", "regret"] for fr in [(0.5, 0.85), (1.0, 1.0)] for esp in (50.0, 0.0)]
for constr, pos_ant, espera, fijo in CONFIGS:
    cfg = Config(tipo_instancia="big", hoja_instancia=f"Instancia {a.instancia}", semana=a.semana)
    cfg.peso_espera, cfg.peso_costo_fijo = espera, fijo
    cfg.fraccion_flota = pos_ant
    cfg.constructor = constr
    cfg.n_arranques = a.arranques
    inst = datos.cargar(cfg); M = matriz.construir(cfg, inst.coords)
    cat, sel = planes.catalogo_inicial(inst, cfg); ev = Evaluador(inst, M, cfg, cat)
    t0 = time.time()
    sols = generar_columnas_semana(ev, inst, M, cfg, cat, sel, Pool(cfg), random.Random(cfg.semilla))
    s = mn._solucion_inicial(inst, cat, cfg, ev, sols)
    filas.append(dict(constructor=constr, fraccion=str(pos_ant), peso_espera=espera, peso_fijo=fijo,
                      costo=round(s.costo / 1e6, 3), ext=len(s.externalizadas),
                      vehiculos=len(s.vehiculos), km=round(sum(r.distancia for r in s.rutas)),
                      t=round(time.time() - t0)))
    print(filas[-1], flush=True)
pd.DataFrame(filas).to_csv(f"outputs/pruebas/experimento3_grasp_I{a.instancia}S{a.semana}.csv", index=False)
