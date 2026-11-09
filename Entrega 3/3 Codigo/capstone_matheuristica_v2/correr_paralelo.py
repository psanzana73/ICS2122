"""Corre muchas instancia-semana (y escenarios) en paralelo, reanudable.

    caffeinate -i python correr_paralelo.py --tipo big --procesos 4 -- --hilos 2
    caffeinate -i python correr_paralelo.py --tipo big --instancias 3 10 --semanas 1 \
        --escenarios demanda+20 flota-25 --procesos 4 -- --hilos 2

    python correr_paralelo.py --lista tareas.txt --procesos 2 -- --hilos 2
      (una tarea por línea: tipo instancia semana [escenario] [semilla]; # comenta)

Cada tarea es un subproceso de main.py con su log en outputs/log_*.txt. Si ya
existe outputs/kpis_<sufijo>.csv, la tarea se salta. Lo que va después de --
se pasa tal cual a main.py.
"""
import argparse
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

OUT = Path("outputs")


def sufijo(tipo, i, w, esc, sem=None):
    s = f"{tipo}_Instancia{i}_semana{w}"
    if esc and esc != "base":
        s += f"_esc-{esc}"
    if sem is not None:
        s += f"_sem{sem}"
    return s


DESCANSO = {"pausa": 0, "cada": 0, "larga": 0}
_ultimo_descanso = [time.time()]


def descansar():
    """Pausas para no exigir el computador: una corta después de cada tarea y
    una larga cada `cada` segundos."""
    if DESCANSO["pausa"]:
        time.sleep(DESCANSO["pausa"])
    if DESCANSO["cada"] and time.time() - _ultimo_descanso[0] > DESCANSO["cada"]:
        _ultimo_descanso[0] = time.time() + DESCANSO["larga"]
        print(f"[paralelo] descanso de {DESCANSO['larga'] // 60} min", flush=True)
        time.sleep(DESCANSO["larga"])


def correr(tipo, i, w, esc, sem, extra):
    suf = sufijo(tipo, i, w, esc, sem)
    if (OUT / f"kpis_{suf}.csv").exists():
        return suf, "ya existía", 0.0
    cmd = [sys.executable, "-u", "main.py", "--tipo", tipo, "--instancia", f"Instancia {i}",
           "--semana", str(w), *extra]
    if esc and esc != "base":
        cmd += ["--escenario", esc]
    if sem is not None:
        cmd += ["--semilla", str(sem), "--etiqueta", f"sem{sem}"]
    t0 = time.time()
    with open(OUT / f"log_{suf}.txt", "w", encoding="utf-8") as log:
        r = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT)
    descansar()
    return suf, "OK" if r.returncode == 0 else f"FALLÓ ({r.returncode})", time.time() - t0


def leer_lista(ruta):
    tareas = []
    for linea in Path(ruta).read_text(encoding="utf-8").splitlines():
        p = linea.split("#")[0].split()
        if not p:
            continue
        esc = p[3] if len(p) > 3 else "base"
        sem = int(p[4]) if len(p) > 4 else None
        tareas.append((p[0], int(p[1]), int(p[2]), esc, sem))
    return tareas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tipo", default="big", choices=["small", "big"])
    ap.add_argument("--instancias", type=int, nargs="*", default=list(range(1, 11)))
    ap.add_argument("--semanas", type=int, nargs="*", default=[1, 2, 3, 4])
    ap.add_argument("--escenarios", nargs="*", default=["base"])
    ap.add_argument("--semillas", type=int, nargs="*", default=None,
                    help="corre cada tarea con estas semillas (salidas con sufijo _semN)")
    ap.add_argument("--lista", default=None, help="archivo con una tarea por línea")
    ap.add_argument("--procesos", type=int, default=4)
    ap.add_argument("--pausa-min", type=float, default=0, help="pausa después de cada tarea")
    ap.add_argument("--descanso-cada-min", type=float, default=0)
    ap.add_argument("--descanso-min", type=float, default=0)
    ap.add_argument("extra", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    extra = [x for x in a.extra if x != "--"]
    DESCANSO.update(pausa=a.pausa_min * 60, cada=a.descanso_cada_min * 60, larga=a.descanso_min * 60)
    OUT.mkdir(exist_ok=True)
    sems = a.semillas if a.semillas else [None]
    if a.lista:
        tareas = leer_lista(a.lista)
    else:
        tareas = [(a.tipo, i, w, e, s) for e in a.escenarios for i in a.instancias
                  for w in a.semanas for s in sems]
    t0 = time.time()
    print(f"[paralelo] {len(tareas)} tareas con {a.procesos} procesos", flush=True)
    with ThreadPoolExecutor(max_workers=a.procesos) as ex:
        futs = [ex.submit(correr, *t, extra) for t in tareas]
        for k, f in enumerate(as_completed(futs), 1):
            suf, estado, dt = f.result()
            print(f"[paralelo] {k}/{len(tareas)} {suf}: {estado} ({dt/60:.0f} min) "
                  f"| {((time.time()-t0)/60):.0f} min totales", flush=True)


if __name__ == "__main__":
    main()
