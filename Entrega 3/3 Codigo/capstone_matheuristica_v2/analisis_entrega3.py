"""Resume los resultados nuevos de la Entrega 3 (SMALL, sensibilidad extendida, bases,
furgones y semillas) en outputs/analisis_e3/*.csv."""
import csv
import statistics as st
from pathlib import Path

O = Path("outputs")
SAL = O / "analisis_e3"
SAL.mkdir(exist_ok=True)


def kpi(p):
  p = Path(p)
  if not p.exists():
    return None
  return {r[0]: r[1] for r in csv.reader(open(p, encoding="utf-8")) if r and r[0]}


def num(d, k):
  return float(d[k]) if d and k in d and d[k] not in ("", "nan") else float("nan")


def fila(m, b, **extra):
  cm, cb = num(m, "costo_total"), num(b, "costo_total")
  return dict(extra, base=round(cb / 1e6, 3), math=round(cm / 1e6, 3),
              ahorro_pct=round(100 * (cb - cm) / cb, 2),
              veh_base=num(b, "vehiculos_activados"), veh_math=num(m, "vehiculos_activados"),
              ext_base=num(b, "solicitudes_externalizadas"), ext_math=num(m, "solicitudes_externalizadas"),
              km_base=round(num(b, "distancia_total_km")), km_math=round(num(m, "distancia_total_km")),
              furg_math=num(m, "veh_FURGON_FRIO"), bases_math=num(m, "bases_usadas"),
              atraso_pct_base=num(b, "pct_entregas_atrasadas"), atraso_pct_math=num(m, "pct_entregas_atrasadas"),
              gap_cota=num(m, "gap_vs_cota_lp"), solicitudes=num(m, "solicitudes_totales"))


def guardar(nombre, filas):
  with open(SAL / nombre, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(filas[0]))
    w.writeheader()
    w.writerows(filas)


# 1. SMALL
small = []
for i in range(1, 11):
  for s in range(1, 5):
    m = kpi(O / f"kpis_small_Instancia{i}_semana{s}.csv")
    b = kpi(O / "base_small" / f"kpis_BASE_small_Instancia{i}_semana{s}.csv")
    small.append(fila(m, b, instancia=i, semana=s))
guardar("small.csv", small)

# 2. escenarios (todas las semanas con sensibilidad)
SEMANAS = [(1, 1), (7, 4), (8, 3), (10, 3)]
esc = []
for i, s in SEMANAS:
  for p in sorted(O.glob(f"kpis_big_Instancia{i}_semana{s}_esc-*.csv")):
    e = p.stem.split("_esc-")[1]
    b = kpi(O / "sens_base" / f"kpis_BASE_big_Instancia{i}_semana{s}_esc-{e}.csv")
    if b is None:
      print("sin base:", i, s, e)
      continue
    esc.append(fila(kpi(p), b, instancia=i, semana=s, escenario=e))
  b0 = kpi(O / "base_v2" / f"kpis_BASE_big_Instancia{i}_semana{s}.csv")
  esc.append(fila(kpi(O / f"kpis_big_Instancia{i}_semana{s}.csv"), b0, instancia=i, semana=s, escenario="base"))
# cambio de costo respecto del escenario base de esa semana
ref = {(f["instancia"], f["semana"]): f for f in esc if f["escenario"] == "base"}
for f in esc:
  r = ref[(f["instancia"], f["semana"])]
  f["dcosto_math_pct"] = round(100 * (f["math"] - r["math"]) / r["math"], 2)
  f["dcosto_base_pct"] = round(100 * (f["base"] - r["base"]) / r["base"], 2)
guardar("escenarios.csv", esc)

# 3. semillas
sem = []
for i, s in SEMANAS:
  cs = [kpi(O / f"kpis_big_Instancia{i}_semana{s}.csv")] + \
       [kpi(O / f"kpis_big_Instancia{i}_semana{s}_sem{k}.csv") for k in (1, 2, 3)]
  v = [num(c, "costo_total") / 1e6 for c in cs]
  b = num(kpi(O / "base_v2" / f"kpis_BASE_big_Instancia{i}_semana{s}.csv"), "costo_total") / 1e6
  sem.append(dict(instancia=i, semana=s, base=round(b, 3), costos=" ".join(f"{x:.3f}" for x in v),
                  media=round(st.mean(v), 3), de=round(st.stdev(v), 3), cv_pct=round(100 * st.stdev(v) / st.mean(v), 2),
                  ahorro_min=round(100 * (b - max(v)) / b, 2), ahorro_max=round(100 * (b - min(v)) / b, 2)))
guardar("semillas.csv", sem)

if __name__ == "__main__":
  ah = [f["ahorro_pct"] for f in small]
  print(f"SMALL: ahorro medio {st.mean(ah):.1f} % (min {min(ah):.1f}, max {max(ah):.1f}); "
        f"math más barata en {sum(a > 0 for a in ah)}/40; costo medio base {st.mean(f['base'] for f in small):.2f} "
        f"math {st.mean(f['math'] for f in small):.2f}; ext {st.mean(f['ext_base'] for f in small):.1f}/"
        f"{st.mean(f['ext_math'] for f in small):.1f}; veh {st.mean(f['veh_base'] for f in small):.1f}/"
        f"{st.mean(f['veh_math'] for f in small):.1f}; km {st.mean(f['km_base'] for f in small):.0f}/"
        f"{st.mean(f['km_math'] for f in small):.0f}; gap {st.mean(f['gap_cota'] for f in small):.3f}")
  print("escenarios:", len(esc), "| ahorro", min(f["ahorro_pct"] for f in esc), "a", max(f["ahorro_pct"] for f in esc))
  for f in sorted(esc, key=lambda f: (f["escenario"], f["instancia"])):
    print(f"  {f['escenario']:18s} I{f['instancia']}S{f['semana']}  base {f['base']:6.2f} math {f['math']:6.2f} "
          f"ahorro {f['ahorro_pct']:5.1f}  dmath {f['dcosto_math_pct']:+6.1f}%  dbase {f['dcosto_base_pct']:+6.1f}%  "
          f"veh {f['veh_math']:.0f} ext {f['ext_base']:.0f}/{f['ext_math']:.0f} bases {f['bases_math']:.0f}")
  for f in sem:
    print("semillas", f)
