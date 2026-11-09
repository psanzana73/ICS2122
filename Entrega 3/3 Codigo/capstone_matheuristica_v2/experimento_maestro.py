"""Experimento: cuánto mejora el maestro entero con más trabajo o con otro énfasis.
Paso 1 (--armar): genera un pool (GRASP+VND, caso base, 3 rondas de pricing) y lo guarda.
Paso 2: resuelve el maestro sobre ese pool con varias configuraciones de Gurobi."""
import argparse, pickle, random, time, sys
from matheuristica import datos, matriz, planes, maestro
from matheuristica.config import Config
from matheuristica.heuristica import Pool, generar_columnas_semana, pricing_dia
from matheuristica.ruta import Evaluador
import main as mn

ap = argparse.ArgumentParser(); ap.add_argument("--armar", action="store_true")
ap.add_argument("--configs", nargs="*", default=None)
a = ap.parse_args()
F = "outputs/pruebas/pool_I10S1.pkl"
cfg = Config(tipo_instancia="big", hoja_instancia="Instancia 10", semana=1)
cfg.peso_espera = 50.0; cfg.hilos_gurobi = 4
inst = datos.cargar(cfg); M = matriz.construir(cfg, inst.coords)
if a.armar:
    cat, sel = planes.catalogo_inicial(inst, cfg); ev = Evaluador(inst, M, cfg, cat)
    rng = random.Random(cfg.semilla); pool = Pool(cfg)
    sb = mn._solucion_caso_base(inst, M, cfg, cat); pool.proteger(sb.rutas)
    sols = generar_columnas_semana(ev, inst, M, cfg, cat, sel, pool, rng)
    ini = mn._solucion_inicial(inst, cat, cfg, ev, sols)
    mejor = sb if sb.costo < ini.costo else ini
    pool.proteger(mejor.rutas); pool.podar()
    lp = maestro.relajacion(inst, cat, cfg, pool.columnas())
    for ronda in range(3):
        for pos in mn._posicionamientos_pricing(inst, M, cat, sel, lp, mejor, rng, cfg):
            for d in inst.dias:
                for r in pricing_dia(ev, inst, cfg, cat, d, pos, lp[1]): pool.agregar(r)
        lp = maestro.relajacion(inst, cat, cfg, pool.columnas())
        print("ronda", ronda, round(lp[0]), len(pool.rutas), flush=True)
    pickle.dump(dict(cat=cat, cols=pool.columnas(), mejor=mejor, lp=lp, base=sb.costo, ini=ini.costo), open(F, "wb"))
    print("base", round(sb.costo), "grasp", round(ini.costo), flush=True)
    sys.exit()
D = pickle.load(open(F, "rb"))
print("base", round(D["base"]), "grasp", round(D["ini"]), "cols", len(D["cols"]), "LP", round(D["lp"][0]))
import gurobipy as gp
CONF = {"w300": dict(work=300), "w900": dict(work=900), "w300_f1": dict(work=300, focus=1),
        "w900_f1": dict(work=900, focus=1), "w300_h": dict(work=300, heur=0.5)}
for nombre in (a.configs or CONF):
    c = CONF[nombre]
    cfg.work_limit_maestro = c["work"]
    orig = maestro._modelo
    def mod(*args, **kw):
        m, v = orig(*args, **kw)
        if "focus" in c: m.Params.MIPFocus = c["focus"]
        if "heur" in c: m.Params.Heuristics = c["heur"]
        return m, v
    maestro._modelo = mod
    t0 = time.time()
    s = maestro.resolver(inst, D["cat"], cfg, D["cols"], inicio=D["mejor"], lp=D["lp"])
    maestro._modelo = orig
    print(nombre, "costo", round(s.costo), "ext", len(s.externalizadas), "veh", len(s.vehiculos), "gap", round(100*s.gap, 1), "t", round(time.time()-t0), flush=True)
