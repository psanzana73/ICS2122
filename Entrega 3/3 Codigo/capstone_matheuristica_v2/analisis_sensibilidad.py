"""Tabla y figura del análisis de sensibilidad (ambos métodos, semanas representativas).

    python analisis_sensibilidad.py --out outputs/analisis
"""
import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ESC = ["base", "demanda-20", "demanda+20", "flota-25", "congestion30", "congestion50", "jornada7",
       "penal_x05", "penal_x2", "bases_fijo_x2", "sin_talagante", "hubs_todas"]
NOMBRE = {"base": "Datos originales", "demanda-20": "Demanda $-20$\\,\\%", "demanda+20": "Demanda $+20$\\,\\%",
          "flota-25": "Flota $-25$\\,\\%", "congestion30": "Congestión $+30$\\,\\%",
          "congestion50": "Congestión $+50$\\,\\%", "jornada7": "Jornada desde 07:00",
          "penal_x05": "Externalización $\\times0{,}5$", "penal_x2": "Externalización $\\times2$",
          "bases_fijo_x2": "Costo de bases $\\times2$", "sin_talagante": "Sin base Talagante",
          "hubs_todas": "Hubs para todas"}
SEMANAS = [(7, 4), (10, 3)]


def leer(f):
    if not f.exists():
        return None
    return pd.to_numeric(pd.read_csv(f, index_col=0)["valor"], errors="coerce").to_dict()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="outputs/analisis")
    ap.add_argument("--latex", default=None)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    filas = []
    for esc in ESC:
        for i, w in SEMANAS:
            suf = "" if esc == "base" else f"_esc-{esc}"
            m = leer(Path("outputs") / f"kpis_big_Instancia{i}_semana{w}{suf}.csv")
            besc = "base" if esc == "hubs_todas" else esc
            bsuf = "" if besc == "base" else f"_esc-{besc}"
            b = leer(Path("outputs/sens_base") / f"kpis_BASE_big_Instancia{i}_semana{w}{bsuf}.csv")
            if m is None or b is None:
                continue
            filas.append(dict(escenario=esc, semana=f"I{i}S{w}", costo_base=b["costo_total"] / 1e6,
                              costo_math=m["costo_total"] / 1e6,
                              ahorro=100 * (b["costo_total"] - m["costo_total"]) / b["costo_total"],
                              veh_base=b["vehiculos_activados"], veh_math=m["vehiculos_activados"],
                              ext_base=b["solicitudes_externalizadas"], ext_math=m["solicitudes_externalizadas"],
                              bases_math=m["bases_usadas"], hubs_math=m["hubs_habilitados"],
                              transf_math=m["transferencias"], furgon_math=m.get("veh_FURGON_FRIO"),
                              vg_math=m.get("veh_VAN_GENERAL"), vf_math=m.get("veh_VAN_FRIO"),
                              km_math=m["distancia_total_km"]))
    df = pd.DataFrame(filas)
    df.to_csv(out / "tabla_sensibilidad.csv", index=False)
    print(df.round(2).to_string())
    if a.latex and len(df):
        lineas = []
        for esc in ESC:
            sub = df[df.escenario == esc]
            if sub.empty:
                continue
            celdas = []
            for _, r in sub.iterrows():
                celdas.append(f"{r.costo_base:.2f} & {r.costo_math:.2f} & {r.ahorro:.1f} & "
                              f"{r.veh_math:.0f} & {r.ext_math:.0f}".replace(".", ","))
            while len(celdas) < 2:
                celdas.append("-- & -- & -- & -- & --")
            lineas.append(f"{NOMBRE[esc]} & " + " & ".join(celdas) + " \\\\")
        Path(a.latex).write_text("\n".join(lineas))
    if len(df):
        fig, ax = plt.subplots(figsize=(7.5, 3.4))
        orden = [e for e in ESC if e in set(df.escenario)]
        for (i, w), c, mk in zip(SEMANAS, ["#1f4e79", "#d9822b"], ["o", "s"]):
            s = df[df.semana == f"I{i}S{w}"].set_index("escenario").reindex(orden)
            ax.plot(range(len(orden)), s.ahorro, mk, color=c, label=f"Instancia {i}, semana {w}", ms=6)
        ax.axhline(0, color="#999999", lw=0.8)
        ax.set_xticks(range(len(orden)))
        ax.set_xticklabels([NOMBRE[e].replace("$", "").replace("\\,", " ").replace("\\%", "%")
                            .replace("\\times", "x").replace("{,}", ",") for e in orden],
                           rotation=35, ha="right", fontsize=8)
        ax.set_ylabel("Ahorro vs caso base (%)")
        ax.legend(frameon=False, fontsize=8)
        ax.spines[["top", "right"]].set_visible(False)
        fig.tight_layout()
        fig.savefig(out / "fig_sensibilidad.png", dpi=200)


if __name__ == "__main__":
    main()
