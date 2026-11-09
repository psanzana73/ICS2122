"""Convierte las tablas de analisis_resultados.py en tablas LaTeX para el informe.

    python tablas_latex.py --analisis outputs/analisis --out ../"Informe 2 corregido"/latex/tablas
"""
import argparse
from pathlib import Path

import pandas as pd


def num(x, d=2):
    return f"{x:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--analisis", default="outputs/analisis")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    A, O = Path(a.analisis), Path(a.out)
    O.mkdir(parents=True, exist_ok=True)

    k = pd.read_csv(A / "tabla_kpis.csv")
    es = lambda t: str(t).replace(",", "X").replace(".", ",").replace("X", ".")
    filas = []
    for _, r in k.iterrows():
        b, m = r.base_num, r.math_num
        if "(%)" in r.indicador:          # porcentajes: diferencia en puntos porcentuales
            dif = m - b
            txt = f"{'+' if dif > 0 else ''}{num(dif, 1)} pp"
        else:
            cambio = (m - b) / b * 100 if b else 0
            txt = f"{'+' if cambio > 0 else ''}{num(cambio, 1)}\\,\\%"
        filas.append(f"{r.indicador} & {es(r.caso_base)} & {es(r.matheuristica)} & {txt} \\\\")
    (O / "kpis.tex").write_text("\n".join(filas).replace("(%)", "(\\%)"))

    d = pd.read_csv(A / "tabla_desglose.csv")
    d = d[(d.caso_base.abs() > 0.005) | (d.matheuristica.abs() > 0.005)]
    filas = [f"{r.componente} & {num(r.caso_base)} & {num(r.pct_base, 1)} & {num(r.matheuristica)} & "
             f"{num(r.pct_math, 1)} & {'+' if r.diferencia > 0 else ''}{num(r.diferencia)} \\\\"
             for _, r in d.iterrows()]
    tb, tm = d.caso_base.sum(), d.matheuristica.sum()
    filas.append(f"\\midrule\nTotal & {num(tb)} & 100 & {num(tm)} & 100 & {num(tm - tb)} \\\\")
    (O / "desglose.tex").write_text("\n".join(filas))

    i = pd.read_csv(A / "tabla_instancias.csv")
    filas = [f"{int(r.instancia)} & {num(r.solicitudes_totales, 0)} & {num(r.costo_total_base / 1e6)} & "
             f"{num(r.costo_total_math / 1e6)} & {num(r.ahorro_pct, 1)}\\,\\% & "
             f"{num(r.vehiculos_activados_base, 1)} / {num(r.vehiculos_activados_math, 1)} & "
             f"{num(r.solicitudes_externalizadas_base, 1)} / {num(r.solicitudes_externalizadas_math, 1)} \\\\"
             for _, r in i.iterrows()]
    (O / "instancias.tex").write_text("\n".join(filas))
    print("tablas en", O)


if __name__ == "__main__":
    main()
