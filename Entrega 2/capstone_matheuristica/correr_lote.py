"""Corre todas las instancias-semana de un tipo y consolida los KPI.

    python correr_lote.py --tipo small                    # 10 instancias x 4 semanas
    python correr_lote.py --tipo small --instancias 1 2 --semanas 1
    python correr_lote.py --tipo big -- --arranques 4     # lo que va después de --
                                                          # se pasa tal cual a main.py

Se puede cortar y relanzar: salta las instancia-semana que ya tienen
outputs/kpis_*.csv (usar --rehacer para forzar). Al final (y después de cada
corrida) escribe outputs/resumen_<tipo>.csv con una fila por instancia-semana,
incluyendo el n.º de errores y alertas de la validación.
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

OUT = Path("outputs")


def sufijo(tipo, i, w):
    return f"{tipo}_Instancia{i}_semana{w}"


def resumir(tipo):
    filas = []
    for f in sorted(OUT.glob(f"kpis_{tipo}_Instancia*_semana*.csv")):
        suf = f.stem[len("kpis_"):]
        k = pd.read_csv(f, index_col=0)["valor"].to_dict()
        inst, sem = suf.split("_")[1], suf.split("_")[2]
        k = {"instancia": int(inst.replace("Instancia", "")),
             "semana": int(sem.replace("semana", "")), **k}
        v = OUT / f"validacion_{suf}.txt"
        if v.exists():
            txt = v.read_text(encoding="utf-8").split("ALERTAS")
            k["errores_validacion"] = sum(1 for l in txt[0].splitlines()[1:] if l.strip() and l.strip() != "(ninguno)")
            k["alertas_validacion"] = sum(1 for l in txt[1].splitlines()[1:] if l.strip() and l.strip() != "(ninguna)")
        filas.append(k)
    if filas:
        df = pd.DataFrame(filas).sort_values(["instancia", "semana"])
        df.to_csv(OUT / f"resumen_{tipo}.csv", index=False)
        return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tipo", default="small", choices=["small", "big"])
    ap.add_argument("--instancias", type=int, nargs="*", default=list(range(1, 11)))
    ap.add_argument("--semanas", type=int, nargs="*", default=[1, 2, 3, 4])
    ap.add_argument("--rehacer", action="store_true")
    ap.add_argument("extra", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    extra = [x for x in a.extra if x != "--"]

    OUT.mkdir(exist_ok=True)
    t0 = time.time()
    for i in a.instancias:
        for w in a.semanas:
            suf = sufijo(a.tipo, i, w)
            if (OUT / f"kpis_{suf}.csv").exists() and not a.rehacer:
                print(f"[lote] {suf}: ya existe, se salta")
                continue
            cmd = [sys.executable, "main.py", "--tipo", a.tipo,
                   "--instancia", f"Instancia {i}", "--semana", str(w), *extra]
            print(f"\n[lote] {suf}  ({(time.time()-t0)/60:.0f} min acumulados)")
            with open(OUT / f"log_{suf}.txt", "w", encoding="utf-8") as log:
                r = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT)
            print(f"[lote] {suf}: {'OK' if r.returncode == 0 else 'FALLÓ, ver log'}")
            resumir(a.tipo)
    df = resumir(a.tipo)
    if df is not None:
        cols = [c for c in ["instancia", "semana", "costo_total", "tasa_externalizacion",
                            "sobretiempo_total_min", "gap_maestro",
                            "errores_validacion", "alertas_validacion"] if c in df]
        print("\n" + df[cols].to_string(index=False))
        print(f"\n[lote] resumen en {OUT / ('resumen_' + a.tipo + '.csv')} "
              f"| {(time.time()-t0)/60:.0f} min")


if __name__ == "__main__":
    main()
