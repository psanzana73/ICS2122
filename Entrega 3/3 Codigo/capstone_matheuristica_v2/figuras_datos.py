"""Figuras y cifras del análisis de datos (capítulo 3 del informe).

    python figuras_datos.py --out outputs/figuras_datos

Todo se calcula sobre las 80 semanas (10 instancias x 4 semanas x 2 tamaños).
"""

from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.collections import LineCollection

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                     "axes.spines.top": False, "axes.spines.right": False})
AZUL, NARANJA, GRIS, VERDE = "#1f4e79", "#d9822b", "#8c8c8c", "#4a7f3b"


def minutos(x):
    if hasattr(x, "hour"):
        return x.hour * 60 + x.minute
    h, m = str(x).split(":")[:2]
    return int(h) * 60 + int(m)


def cargar(tipo):
    hojas = pd.read_excel(f"data/instancias_{tipo}.xlsx", sheet_name=None)
    df = pd.concat(hojas.values(), ignore_index=True)
    for c in ["pickup_window_start", "pickup_window_end", "delivery_window_start", "delivery_due"]:
        df[c] = df[c].map(minutos)
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="outputs/figuras_datos")
    ap.add_argument("--sin-mapa", action="store_true")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    tx = pd.read_excel("data/set_datos_transversal.xlsx", sheet_name=None)
    S, B = cargar("small"), cargar("big")
    cifras = {}

    # ------------------------------------------------ tabla SMALL vs BIG
    filas = []
    for nom, df, hv in (("SMALL", S, "Vehiculos_Small"), ("BIG", B, "Vehiculos_Big")):
        sem = df.groupby(["instance", "week_of_month"]).size()
        dia = df.groupby(["instance", "week_of_month", "day"]).size()
        ins = df[df.cargo_class == "INSUMO_GENERAL"]
        ancho_r = df.pickup_window_end - df.pickup_window_start
        ancho_e = df.delivery_due - df.delivery_window_start
        disp = (lambda t: t["available_small_instances"].astype(bool).sum()) if nom == "SMALL" else len
        filas.append({
            "Instancias x semanas": "10 x 4",
            "Solicitudes por semana (mín.–máx.)": f"{sem.min()}–{sem.max()}",
            "Solicitudes por día (mediana; máx.)": f"{int(dia.median())}; {dia.max()}",
            "Flota (van general / van frío / furgón frío)":
                "/".join(str(x) for x in tx[hv].vehicle_class.value_counts()
                         .reindex(["VAN_GENERAL", "VAN_FRIO", "FURGON_FRIO"]).values),
            "Bases disponibles (cupos)": f"{disp(tx['Bases'])} "
                f"({tx['Bases'][tx['Bases'].available_small_instances.astype(bool)].capacity.sum() if nom == 'SMALL' else tx['Bases'].capacity.sum()})",
            "Hubs disponibles": disp(tx["Transferencias"]),
            "Ventana de retiro, mediana (min)": int(ancho_r.median()),
            "Retiros con ventana < 90 min (%)": f"{100 * (ancho_r < 90).mean():.1f}",
            "Ventana de entrega, mediana (min)": int(ancho_e.median()),
            "Insumos sobre 70 unidades (%)": f"{100 * (ins.quantity > 70).mean():.1f}",
            "Distancia OD media (km)": None,
        })
    tabla = pd.DataFrame(filas, index=["SMALL", "BIG"]).T
    # distancia OD con la matriz OSMnx
    z = np.load("data/matriz_osmnx_120.npz", allow_pickle=True)
    ids = list(z["ids"]) if "ids" in z else None
    if ids is not None:
        idx = {k: i for i, k in enumerate(ids)}
        D = z["distancias"] if "distancias" in z else z[z.files[-1]]
        for nom, df in (("SMALL", S), ("BIG", B)):
            d = [D[idx[o], idx[t]] for o, t in zip(df.origin_id, df.destination_id)]
            tabla.loc["Distancia OD media (km)", nom] = f"{np.mean(d):.1f}"
    tabla.to_csv(out / "tabla_small_big.csv")
    print(tabla.to_string())

    # ------------------------------------------------ composición por clase
    comp = pd.DataFrame({n: 100 * df.cargo_class.value_counts(normalize=True)
                         for n, df in (("SMALL", S), ("BIG", B))}).round(1)
    comp.to_csv(out / "tabla_composicion.csv")
    print(comp)

    # ------------------------------------------------ concurrencia de solicitudes
    # Una solicitud está "en curso" entre la apertura de su ventana de retiro y
    # su compromiso de entrega: en ese intervalo ocupa (al menos en parte) a un
    # vehículo. Se cuenta cada 15 min en cada uno de los 200 días de cada tamaño.
    grilla = np.arange(7 * 60, 20 * 60 + 1, 15)
    fig, axs = plt.subplots(1, 2, figsize=(9, 3.2), sharey=True)
    for ax, (nom, df, flota) in zip(axs, (("SMALL", S, 20), ("BIG", B, 60))):
        curvas = []
        for _, g in df.groupby(["instance", "week_of_month", "day"]):
            ini, fin = g.pickup_window_start.values, g.delivery_due.values
            curvas.append([(np.sum((ini <= t) & (fin > t))) for t in grilla])
        C = np.array(curvas)
        med, p10, p90 = np.median(C, 0), np.percentile(C, 10, 0), np.percentile(C, 90, 0)
        h = grilla / 60
        ax.fill_between(h, p10, p90, color=AZUL, alpha=0.18, lw=0, label="Días entre p10 y p90")
        ax.plot(h, med, color=AZUL, lw=2, label="Mediana de los 200 días")
        ax.axhline(flota, color=NARANJA, lw=1.5, ls="--", label=f"Flota disponible")
        ax.text(7.1, flota + 2, f"flota = {flota}", color=NARANJA, fontsize=9)
        ax.set_title(nom, fontsize=10, loc="left")
        ax.set_xlabel("Hora del día")
        ax.set_xticks(range(7, 21, 2))
        ax.set_xticklabels([f"{x}:00" for x in range(7, 21, 2)])
        pico = int(med.argmax())
        cifras[f"pico_{nom}"] = dict(hora=f"{grilla[pico] // 60}:{grilla[pico] % 60:02d}",
                                     mediana=float(med[pico]), p90=float(p90[pico]),
                                     max_dia=int(C.max()),
                                     dias_sobre_flota=float(100 * (C.max(1) > flota).mean()))
    axs[0].set_ylabel("Solicitudes en curso")
    axs[1].legend(frameon=False, fontsize=8, loc="upper right")
    fig.tight_layout()
    fig.savefig(out / "fig_concurrencia.png", dpi=200)
    plt.close(fig)

    # ------------------------------------------------ insumo vs capacidad
    fig, ax = plt.subplots(figsize=(7, 3))
    bins = np.arange(10, 100, 5)
    for nom, df, c in (("SMALL", S, GRIS), ("BIG", B, AZUL)):
        q = df[df.cargo_class == "INSUMO_GENERAL"].quantity
        ax.hist(q, bins=bins, density=True, histtype="step", lw=2, color=c, label=nom)
        cifras[f"insumo_{nom}"] = {f"sobre_{k}": float(100 * (q > k).mean()) for k in (24, 30, 70)}
    for cap, nom in ((24, "van frío"), (30, "van general"), (70, "furgón frío")):
        ax.axvline(cap, color=NARANJA, ls=":", lw=1.3)
        ax.text(cap + 0.8, ax.get_ylim()[1] * 0.92, nom, color=NARANJA, fontsize=8, rotation=90, va="top")
    ax.set_xlabel("Unidades por solicitud de insumo general")
    ax.set_ylabel("Densidad")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(out / "fig_insumo_capacidad.png", dpi=200)
    plt.close(fig)

    # ------------------------------------------------ demanda refrigerada vs flota
    refri = {}
    for nom, df, hv in (("SMALL", S, "Vehiculos_Small"), ("BIG", B, "Vehiculos_Big")):
        fl = tx[hv].vehicle_class.value_counts()
        solo_frio = df.cargo_class.isin(["MUESTRA_CLINICA", "FARMACO_REFRIGERADO"]).mean()
        refri[nom] = dict(pct_solicitudes_solo_frio=100 * solo_frio,
                          pct_flota_fria=100 * (fl.get("VAN_FRIO", 0) + fl.get("FURGON_FRIO", 0)) / fl.sum(),
                          pct_flota_furgon=100 * fl.get("FURGON_FRIO", 0) / fl.sum(),
                          pct_equipo_sobre_30=100 * (df[df.cargo_class == "EQUIPO_RETORNO"].quantity > 30).mean())
    cifras["refrigerado"] = refri

    # incompatibilidad: pares (fármaco, insumo) del mismo día con retiros solapados
    pares = {}
    for nom, df in (("SMALL", S), ("BIG", B)):
        n = []
        for _, g in df.groupby(["instance", "week_of_month", "day"]):
            f = g[g.cargo_class == "FARMACO_REFRIGERADO"]
            i = g[g.cargo_class == "INSUMO_GENERAL"]
            a1, b1 = f.pickup_window_start.values[:, None], f.delivery_due.values[:, None]
            a2, b2 = i.pickup_window_start.values[None, :], i.delivery_due.values[None, :]
            n.append(int(((a1 < b2) & (a2 < b1)).sum()))
        pares[nom] = float(np.mean(n))
    cifras["pares_farmaco_insumo_solapados_por_dia"] = pares

    # ------------------------------------------------ mapa
    if not a.sin_mapa:
        with open("data/grafo_santiago", "rb") as fh:
            G = pickle.load(fh)
        xs = {n: (d["x"], d["y"]) for n, d in G.nodes(data=True)}
        seg = [(xs[u], xs[v]) for u, v in G.edges() if u in xs and v in xs]
        nodos = tx["Nodos"].set_index("node_id")
        fig, axs = plt.subplots(1, 2, figsize=(9.5, 5.2))
        for ax, (nom, df) in zip(axs, (("SMALL", S), ("BIG", B))):
            ax.add_collection(LineCollection(seg, colors="#e3e3e3", linewidths=0.25, zorder=0))
            uso = pd.concat([df.origin_id, df.destination_id]).value_counts()
            pts = nodos.loc[uso.index]
            ax.scatter(pts.lon, pts.lat, s=4 + 120 * uso / uso.max(), color=AZUL, alpha=0.6,
                       lw=0, zorder=3, label="Nodos (tamaño = solicitudes)")
            bs = tx["Bases"] if nom == "BIG" else tx["Bases"][tx["Bases"].available_small_instances.astype(bool)]
            hs = tx["Transferencias"] if nom == "BIG" else \
                tx["Transferencias"][tx["Transferencias"].available_small_instances.astype(bool)]
            ax.scatter(bs.lon, bs.lat, marker="s", s=55, color="black", zorder=4, label=f"Bases ({len(bs)})")
            ax.scatter(hs.lon, hs.lat, marker="D", s=45, color=NARANJA, edgecolor="white", zorder=5,
                       label=f"Hubs ({len(hs)})")
            ax.set_xlim(-70.95, -70.45)
            ax.set_ylim(-33.75, -33.25)
            ax.set_aspect(1 / np.cos(np.radians(33.5)))
            ax.set_xticks([])
            ax.set_yticks([])
            for s in ax.spines.values():
                s.set_visible(False)
            ax.set_title(nom, loc="left", fontsize=10)
            ax.legend(frameon=False, fontsize=7.5, loc="lower left")
        fig.tight_layout()
        fig.savefig(out / "fig_mapa.png", dpi=220)
        plt.close(fig)

    (out / "cifras_datos.json").write_text(json.dumps(cifras, indent=2, ensure_ascii=False))
    print(json.dumps(cifras, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
