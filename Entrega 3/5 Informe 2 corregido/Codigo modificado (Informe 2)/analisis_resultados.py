"""Genera TODAS las tablas y figuras de resultados del informe desde las salidas.

    python analisis_resultados.py --math outputs/math_v2 --base outputs/base_v2 \
        --out outputs/analisis

Lee los kpis_*.csv, rutas_*.csv, vehiculo_dia_*.csv y posicionamiento_*.csv de
la matheurística y del caso base (mismo evaluador, mismos KPI) y escribe:
  - tabla_kpis.csv            indicadores promedio de las semanas comparables
  - tabla_desglose.csv        desglose del costo semanal promedio
  - tabla_instancias.csv      resultados promedio por instancia
  - tabla_semanal.csv         una fila por instancia-semana y método
  - tabla_estructura.csv      vehículos por clase y uso de bases
  - fig_*.png                 figuras del capítulo de resultados
Responde a la observación de la corrección: "la directitud y las Tablas 6.3-6.6
no se generan con el código entregado".
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

PAT = re.compile(r"(?:BASE_)?big_Instancia(\d+)_semana(\d)(.*)")

AZUL, NARANJA, GRIS = "#1f4e79", "#d9822b", "#7f7f7f"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                     "axes.spines.top": False, "axes.spines.right": False})


def leer_kpis(carpeta: Path, prefijo: str, etiqueta: str = "") -> pd.DataFrame:
    filas = []
    for f in sorted(carpeta.glob(f"kpis_{prefijo}big_Instancia*_semana*.csv")):
        m = PAT.search(f.stem)
        if not m or m.group(3) != etiqueta:
            continue
        k = pd.read_csv(f, index_col=0)["valor"]
        k = pd.to_numeric(k, errors="coerce").to_dict()
        k.update(instancia=int(m.group(1)), semana=int(m.group(2)))
        filas.append(k)
    return pd.DataFrame(filas)


def leer_tabla(carpeta: Path, tipo: str, prefijo: str, etiqueta: str = "") -> pd.DataFrame:
    partes = []
    for f in sorted(carpeta.glob(f"{tipo}_{prefijo}big_Instancia*_semana*.csv")):
        m = PAT.search(f.stem)
        if not m or m.group(3) != etiqueta:
            continue
        try:
            d = pd.read_csv(f)
        except pd.errors.EmptyDataError:
            continue
        d["instancia"], d["semana"] = int(m.group(1)), int(m.group(2))
        partes.append(d)
    return pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()


INDICADORES = [
    ("costo_total", "Costo total semanal (MM CLP)", 1e-6, "{:.2f}"),
    ("costo_por_solicitud", "Costo por solicitud (miles CLP)", 1e-3, "{:.1f}"),
    ("solicitudes_externalizadas", "Solicitudes externalizadas por semana", 1, "{:.1f}"),
    ("tasa_externalizacion", "Solicitudes externalizadas (%)", 100, "{:.2f}"),
    ("vehiculos_activados", "Vehículos activados", 1, "{:.1f}"),
    ("uso_semanal_flota", "Vehículo-días usados / pagados (%)", 100, "{:.1f}"),
    ("utilizacion_jornada_media", "Jornada usada por vehículo-día (%)", 100, "{:.1f}"),
    ("distancia_total_km", "Kilómetros por semana", 1, "{:,.0f}"),
    ("km_por_solicitud_atendida", "Kilómetros por solicitud atendida", 1, "{:.1f}"),
    ("factor_recorrido", "Factor de recorrido (km reales / km directos)", 1, "{:.2f}"),
    ("fraccion_km_vacio", "Kilómetros recorridos vacío (%)", 100, "{:.1f}"),
    ("uso_capacidad_medio", "Uso medio de capacidad a bordo (%)", 100, "{:.1f}"),
    ("tramos_por_ruta", "Tramos por ruta", 1, "{:.2f}"),
    ("pct_rutas_1_2_tramos", "Rutas con 1 o 2 tramos (%)", 100, "{:.1f}"),
    ("pct_entregas_atrasadas", "Entregas atrasadas (%)", 100, "{:.2f}"),
    ("sobretiempo_total_min", "Sobretiempo (min por semana)", 1, "{:.0f}"),
]

DESGLOSE = [("costo_fijo_vehiculos", "Costo fijo de vehículos"),
            ("costo_fijo_bases", "Costo fijo de bases"),
            ("costo_fijo_hubs", "Costo fijo de hubs"),
            ("costo_km", "Kilómetros recorridos"),
            ("costo_sobretiempo", "Sobretiempo"),
            ("costo_tardanza", "Tardanza"),
            ("costo_handling_hubs", "Manipulación en hubs"),
            ("costo_externalizacion", "Externalización")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--math", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--out", default="outputs/analisis")
    ap.add_argument("--etiqueta", default="", help="sufijo de los archivos de la matheurística")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    etq = ("_" + a.etiqueta) if a.etiqueta else ""

    km = leer_kpis(Path(a.math), "", etq)
    kb = leer_kpis(Path(a.base), "BASE_")
    comunes = km.merge(kb[["instancia", "semana"]], on=["instancia", "semana"])
    km = comunes
    kb = kb.merge(km[["instancia", "semana"]], on=["instancia", "semana"])
    km, kb = km.sort_values(["instancia", "semana"]), kb.sort_values(["instancia", "semana"])
    n = len(km)
    print(f"semanas comparables: {n}")

    # ---- tabla de KPI ----------------------------------------------------
    filas = []
    for col, nombre, f, fmt in INDICADORES:
        if col not in km or col not in kb:
            continue
        b, m = kb[col].mean() * f, km[col].mean() * f
        cambio = (m - b) / b * 100 if b else np.nan
        filas.append(dict(indicador=nombre, caso_base=fmt.format(b), matheuristica=fmt.format(m),
                          cambio=f"{cambio:+.1f} %" if np.isfinite(cambio) else "–",
                          base_num=b, math_num=m))
    pd.DataFrame(filas).to_csv(out / "tabla_kpis.csv", index=False)

    # ---- desglose --------------------------------------------------------
    filas = []
    for col, nombre in DESGLOSE:
        b, m = kb[col].mean() / 1e6, km[col].mean() / 1e6
        filas.append(dict(componente=nombre, caso_base=b, matheuristica=m, diferencia=m - b,
                          pct_base=100 * b / (kb.costo_total.mean() / 1e6),
                          pct_math=100 * m / (km.costo_total.mean() / 1e6)))
    pd.DataFrame(filas).to_csv(out / "tabla_desglose.csv", index=False)

    # ---- por semana e instancia -----------------------------------------
    sem = km[["instancia", "semana", "solicitudes_totales"]].copy()
    for col in ["costo_total", "solicitudes_externalizadas", "vehiculos_activados",
                "distancia_total_km", "gap_maestro", "gap_vs_cota_lp"]:
        if col in km:
            sem[f"{col}_math"] = km[col].values
        if col in kb:
            sem[f"{col}_base"] = kb[col].values
    sem["ahorro_pct"] = 100 * (sem.costo_total_base - sem.costo_total_math) / sem.costo_total_base
    sem.to_csv(out / "tabla_semanal.csv", index=False)
    inst = sem.groupby("instancia").mean(numeric_only=True).drop(columns="semana")
    inst.to_csv(out / "tabla_instancias.csv")
    print(f"ahorro medio {sem.ahorro_pct.mean():.1f} % (min {sem.ahorro_pct.min():.1f}, "
          f"max {sem.ahorro_pct.max():.1f}); semanas donde gana: "
          f"{(sem.ahorro_pct > 0).sum()}/{n}")
    print(f"correlación ahorro vs externalizaciones del caso base: "
          f"{np.corrcoef(sem.ahorro_pct, sem.solicitudes_externalizadas_base)[0, 1]:.2f}")

    # ---- estructura: vehículos por clase y bases -------------------------
    est = []
    for nom, k in (("caso_base", kb), ("matheuristica", km)):
        est.append(dict(metodo=nom, van_general=k.get("veh_VAN_GENERAL", pd.Series()).mean(),
                        van_frio=k.get("veh_VAN_FRIO", pd.Series()).mean(),
                        furgon_frio=k.get("veh_FURGON_FRIO", pd.Series()).mean(),
                        bases=k.bases_usadas.mean(), hubs=k.hubs_habilitados.mean(),
                        transferencias=k.transferencias.mean(),
                        divididas=k.solicitudes_divididas.mean()))
    pd.DataFrame(est).to_csv(out / "tabla_estructura.csv", index=False)

    # ---- figuras ---------------------------------------------------------
    # 1) costo por semana, ambos métodos
    fig, ax = plt.subplots(figsize=(8, 3.2))
    x = np.arange(n)
    ax.plot(x, sem.costo_total_base / 1e6, "o-", color=GRIS, ms=3, lw=1.2, label="Caso base")
    ax.plot(x, sem.costo_total_math / 1e6, "o-", color=AZUL, ms=3, lw=1.2, label="Matheurística")
    for i in range(1, sem.instancia.nunique()):
        ax.axvline(4 * i - 0.5, color="#dddddd", lw=0.8, zorder=0)
    ax.set_xticks([4 * i + 1.5 for i in range(sem.instancia.nunique())])
    ax.set_xticklabels([f"I{i}" for i in sorted(sem.instancia.unique())])
    ax.set_ylabel("Costo semanal (MM CLP)")
    ax.legend(frameon=False, ncol=2, loc="upper left")
    fig.tight_layout()
    fig.savefig(out / "fig_costo_semanal.png", dpi=200)
    plt.close(fig)

    # 2) desglose apilado
    d = pd.read_csv(out / "tabla_desglose.csv")
    d = d[d[["caso_base", "matheuristica"]].sum(axis=1) > 0.01]
    fig, ax = plt.subplots(figsize=(6.5, 3.2))
    colores = ["#1f4e79", "#5b8db8", "#a9c4de", "#d9822b", "#f2c38b", "#e8a87c", "#999999", "#c0392b"]
    izq = np.zeros(2)
    for (_, r), c in zip(d.iterrows(), colores):
        vals = np.array([r.caso_base, r.matheuristica])
        ax.barh([1, 0], vals, left=izq, color=c, label=r.componente, height=0.55)
        izq += vals
    ax.set_yticks([1, 0])
    ax.set_yticklabels(["Caso base", "Matheurística"])
    ax.set_xlabel("Costo semanal promedio (MM CLP)")
    ax.legend(frameon=False, fontsize=8, ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.25))
    fig.tight_layout()
    fig.savefig(out / "fig_desglose.png", dpi=200)
    plt.close(fig)

    # 3) estructura de rutas: tramos por ruta y uso de capacidad
    rm = leer_tabla(Path(a.math), "vehiculo_dia", "", etq)
    rb = leer_tabla(Path(a.base), "vehiculo_dia", "BASE_")
    if len(rm) and len(rb):
        fig, axs = plt.subplots(1, 2, figsize=(8, 3))
        bins = np.arange(1, 14) - 0.5
        axs[0].hist([rb.n_tramos, rm.n_tramos], bins=bins, color=[GRIS, AZUL],
                    label=["Caso base", "Matheurística"], density=True)
        axs[0].set_xlabel("Tramos por ruta")
        axs[0].set_ylabel("Fracción de rutas")
        axs[0].legend(frameon=False)
        axs[1].hist([(rb.retorno_min - rb.salida_min) / 60, (rm.retorno_min - rm.salida_min) / 60],
                    bins=np.arange(0, 12, 1), color=[GRIS, AZUL], density=True)
        axs[1].set_xlabel("Duración de la ruta (h)")
        fig.tight_layout()
        fig.savefig(out / "fig_rutas.png", dpi=200)
        plt.close(fig)

    # 4) posicionamiento por base (promedio de vehículos por semana)
    pm = leer_tabla(Path(a.math), "posicionamiento", "", etq)
    pb = leer_tabla(Path(a.base), "posicionamiento", "BASE_")
    if len(pm) and len(pb):
        cm = pm.groupby("base").size() / n
        cb = pb.groupby("base").size() / n
        bases = sorted(set(cm.index) | set(cb.index))
        fig, ax = plt.subplots(figsize=(8, 3))
        xx = np.arange(len(bases))
        ax.bar(xx - 0.2, [cb.get(b, 0) for b in bases], 0.4, color=GRIS, label="Caso base")
        ax.bar(xx + 0.2, [cm.get(b, 0) for b in bases], 0.4, color=AZUL, label="Matheurística")
        ax.set_xticks(xx)
        ax.set_xticklabels([b.replace("B_", "").replace("_", " ").title().replace("Penalolen", "Peñalolén") for b in bases],
                           rotation=30, ha="right")
        ax.set_ylabel("Vehículos por semana")
        ax.legend(frameon=False)
        fig.tight_layout()
        fig.savefig(out / "fig_bases.png", dpi=200)
        plt.close(fig)
        pd.DataFrame({"caso_base": cb, "matheuristica": cm}).fillna(0).to_csv(out / "tabla_bases.csv")


if __name__ == "__main__":
    main()
