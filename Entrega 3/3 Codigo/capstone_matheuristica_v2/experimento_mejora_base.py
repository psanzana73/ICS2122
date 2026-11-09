"""¿Cuánto mejora la solución del caso base si se le aplica VND y se generan
rutas con su misma flota y posicionamiento?"""
import pickle, random, time
from matheuristica import datos, matriz, planes, maestro
from matheuristica.config import Config
from matheuristica.heuristica import (Pool, SolucionDia, vnd, construir_cronologico,
                                      construir_grasp, limpiar_planes_incompletos, _tramos_del_dia)
from matheuristica.ruta import Evaluador
from matheuristica.completar import completar
import main as mn

cfg = Config(tipo_instancia="big", hoja_instancia="Instancia 10", semana=1)
cfg.peso_espera = 0.0; cfg.peso_costo_fijo = 0.0; cfg.hilos_gurobi = 4; cfg.mip_gap = 0.001
inst = datos.cargar(cfg); M = matriz.construir(cfg, inst.coords)
cat, sel = planes.catalogo_inicial(inst, cfg); ev = Evaluador(inst, M, cfg, cat)
sb = mn._solucion_caso_base(inst, M, cfg, cat)
print("base", round(sb.costo), len(sb.externalizadas), len(sb.vehiculos), flush=True)
pool = Pool(cfg); pool.proteger(sb.rutas)
# 1) VND sobre las rutas del caso base, día por día
rutas_v = []
for d in inst.dias:
    s = SolucionDia(dia=d, asignacion=dict(sb.posicionamiento))
    for v in s.asignacion: s.paradas[v] = []
    for r in sb.rutas:
        if r.dia == d: s.paradas[r.vehiculo] = list(r.paradas); s.rutas[r.vehiculo] = r
    s = vnd(ev, cfg, cat, s); rutas_v += list(s.rutas.values()); pool.agregar_solucion(s)
sv = maestro.armar_solucion(inst, cat, rutas_v, sb.planes, sb.externalizadas, sb.vehiculos,
                            sb.posicionamiento, [], sb.hubs, cota=0, gap=0)
print("base+VND", round(sv.costo), flush=True)
s2, n = completar(ev, inst, cat, cfg, sv)
print("base+VND+completar", round(s2.costo), len(s2.externalizadas), len(s2.vehiculos), flush=True)
# 2) multiarranque con la flota y posicionamiento del caso base
rng = random.Random(1)
asig = dict(sb.posicionamiento)
sels = []
for k in range(8):
    rs = []
    for d in inst.dias:
        tr = _tramos_del_dia(inst, cat, sel, d)
        s = (construir_cronologico if k % 2 else construir_grasp)(ev, inst, M, cfg, cat, d, tr, asig, rng)
        s = limpiar_planes_incompletos(ev, cat, s); s = vnd(ev, cfg, cat, s)
        pool.agregar_solucion(s); rs += list(s.rutas.values())
print("pool", len(pool.rutas), flush=True)
t0 = time.time()
sol = maestro.resolver(inst, cat, cfg, pool.columnas(), inicio=s2 if s2.costo < sb.costo else sb)
print("maestro", round(sol.costo), len(sol.externalizadas), len(sol.vehiculos), "gap", round(100*sol.gap, 2), round(time.time()-t0), flush=True)
s3, n = completar(ev, inst, cat, cfg, sol)
print("maestro+completar", round(s3.costo), len(s3.externalizadas), len(s3.vehiculos), flush=True)
