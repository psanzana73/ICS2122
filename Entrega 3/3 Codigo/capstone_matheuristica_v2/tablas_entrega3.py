"""Tablas (cuerpo LaTeX) y figuras del informe final a partir de outputs/analisis_e3.
Uso: python analisis_entrega3.py && python tablas_entrega3.py --informe "../Informe Final/latex" """
import argparse
import csv
import math
import re
import statistics as st
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

O = Path("outputs")
A = O / "analisis_e3"


def leer(n):
  return list(csv.DictReader(open(A / n, encoding="utf-8")))


def kpi(p):
  p = Path(p)
  if not p.exists():
    return None
  return {r[0]: r[1] for r in csv.reader(open(p, encoding="utf-8")) if r and r[0]}


def f(x, d=1):
  s = f"{float(x):,.{d}f}"
  return s.replace(",", "X").replace(".", ",").replace("X", ".")


def pct(x, d=1, signo=False):
  v = float(x)
  if abs(v) < 0.5 * 10 ** -d:
    v = 0.0
  s = f(abs(v) if signo else v, d)
  if signo:
    s = ("+" if v > 0 else "$-$" if v < 0 else "") + s
  return s + r"\,\%"


def sig(x, d=1):
  v = float(x)
  if abs(v) < 0.5 * 10 ** -d:
    return f(0, d)
  return ("+" if v > 0 else "$-$") + f(abs(v), d)


def tiempo_min(log):
  m = re.search(r"tiempo total (\d+)s", Path(log).read_text(encoding="utf-8", errors="ignore"))
  return int(m[1]) / 60 if m else float("nan")


def traza(suf):
  p = O / f"traza_{suf}.csv"
  return list(csv.DictReader(open(p))) if p.exists() else []


def resumen_pareado(ah):
  """Media, IC 95 % (t de Student) y p de Wilcoxon exacto de una cola si todos son positivos."""
  n = len(ah)
  m, s = st.mean(ah), st.stdev(ah)
  t975 = {39: 2.0227}.get(n - 1, 1.96)
  return m, m - t975 * s / math.sqrt(n), m + t975 * s / math.sqrt(n), m / (s / math.sqrt(n))


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--informe", required=True)
  a = ap.parse_args()
  TAB = Path(a.informe) / "tablas"
  FIG = Path(a.informe) / "figures"

  # ---------- SMALL por instancia ----------
  small = leer("small.csv")
  filas = []
  for i in range(1, 11):
    g = [r for r in small if int(r["instancia"]) == i]
    mm = lambda k: st.mean(float(r[k]) for r in g)
    filas.append(f"{i} & {f(mm('solicitudes'),0)} & {f(mm('base'),2)} & {f(mm('math'),2)} & {pct(mm('ahorro_pct'))} & "
                 f"{f(mm('veh_base'))} / {f(mm('veh_math'))} & {f(mm('ext_base'))} / {f(mm('ext_math'))} \\\\")
  (TAB / "small_instancias.tex").write_text("\n".join(filas) + "\n", encoding="utf-8")

  # ---------- escalabilidad SMALL vs BIG ----------
  big = []
  for i in range(1, 11):
    for w in range(1, 5):
      m = kpi(O / f"kpis_big_Instancia{i}_semana{w}.csv")
      b = kpi(O / "base_v2" / f"kpis_BASE_big_Instancia{i}_semana{w}.csv")
      tr = traza(f"big_Instancia{i}_semana{w}")
      big.append(dict(ahorro=100 * (float(b["costo_total"]) - float(m["costo_total"])) / float(b["costo_total"]),
                      sol=float(m["solicitudes_totales"]), veh=float(m["vehiculos_activados"]),
                      disp=float(m["vehiculos_disponibles"]), gap=float(m["gap_vs_cota_lp"]),
                      t=tiempo_min(O / f"log_big_Instancia{i}_semana{w}.txt"),
                      col=int(tr[-1]["columnas"]) if tr else float("nan"),
                      cg=sum(int(x["rondas_cg"]) for x in tr) if tr else float("nan"),
                      ext_b=float(b["solicitudes_externalizadas"]), ext_m=float(m["solicitudes_externalizadas"])))
  sm = []
  for r in small:
    i, w = r["instancia"], r["semana"]
    tr = traza(f"small_Instancia{i}_semana{w}")
    m = kpi(O / f"kpis_small_Instancia{i}_semana{w}.csv")
    sm.append(dict(ahorro=float(r["ahorro_pct"]), sol=float(r["solicitudes"]), veh=float(r["veh_math"]),
                   disp=float(m["vehiculos_disponibles"]), gap=float(r["gap_cota"]),
                   t=tiempo_min(O / f"log_small_Instancia{i}_semana{w}.txt"),
                   col=int(tr[-1]["columnas"]) if tr else float("nan"),
                   cg=sum(int(x["rondas_cg"]) for x in tr) if tr else float("nan")))
  def fila_esc(nombre, fn):
    return f"{nombre} & {fn(sm)} & {fn(big)} \\\\"
  med = lambda g, k: st.median(x[k] for x in g)
  mean = lambda g, k: st.mean(x[k] for x in g)
  esc = [
    fila_esc("Solicitudes por semana", lambda g: f"{f(mean(g,'sol'),0)} ({f(min(x['sol'] for x in g),0)}--{f(max(x['sol'] for x in g),0)})"),
    fila_esc("Vehículos disponibles", lambda g: f(mean(g, 'disp'), 0)),
    fila_esc("Vehículos contratados", lambda g: f(mean(g, 'veh'))),
    fila_esc("Rutas en el pool final", lambda g: f(mean(g, 'col'), 0)),
    fila_esc("Rondas de pricing", lambda g: f(mean(g, 'cg'))),
    fila_esc("Tiempo por semana, mediana (min)", lambda g: f(med(g, 't'))),
    fila_esc("Brecha contra la cota del pool", lambda g: pct(100 * mean(g, 'gap'))),
    fila_esc("Ahorro frente al caso base", lambda g: f"{pct(mean(g,'ahorro'))} ({f(min(x['ahorro'] for x in g))}--{f(max(x['ahorro'] for x in g))})"),
  ]
  (TAB / "escala.tex").write_text("\n".join(esc) + "\n", encoding="utf-8")

  # ---------- pruebas pareadas ----------
  est = []
  for nombre, g in (("SMALL", sm), ("BIG", big)):
    ah = [x["ahorro"] for x in g]
    m, lo, hi, t = resumen_pareado(ah)
    pos = sum(x > 0 for x in ah)
    p = 0.5 ** len(ah) if pos == len(ah) else float("nan")
    est.append(f"{nombre} & {len(ah)} & {pct(m)} & [{f(lo)}; {f(hi)}] & {f(t)} & {pos}/{len(ah)} & $<10^{{-{int(-math.log10(p))}}}$ \\\\")
  (TAB / "estadistica.tex").write_text("\n".join(est) + "\n", encoding="utf-8")

  # ---------- semillas ----------
  sem = leer("semillas.csv")
  filas = []
  for r in sem:
    cs = [float(x) for x in r["costos"].split()]
    filas.append(f"{r['instancia']} & {r['semana']} & {f(r['base'],2)} & {' & '.join(f(c,2) for c in cs)} & "
                 f"{f(r['de'],3)} & {pct(r['cv_pct'],2)} & {f(r['ahorro_min'])}--{f(r['ahorro_max'])}\\,\\% \\\\")
  (TAB / "semillas.tex").write_text("\n".join(filas) + "\n", encoding="utf-8")

  # ---------- sensibilidad extendida ----------
  E = leer("escenarios.csv")
  NOMBRES = [("demanda-20", r"Demanda $-20$\,\%"), ("demanda-10", r"Demanda $-10$\,\%"),
             ("demanda+10", r"Demanda $+10$\,\%"), ("demanda+20", r"Demanda $+20$\,\%"),
             ("demanda+30", r"Demanda $+30$\,\%"), ("flota-25", r"Flota $-25$\,\%"),
             ("congestion15", r"Congestión $+15$\,\%"), ("congestion30", r"Congestión $+30$\,\%"),
             ("congestion50", r"Congestión $+50$\,\%"), ("ventanas+30", r"Ventanas $+30$ min"),
             ("ventanas-15", r"Ventanas $-15$ min"), ("jornada7", "Jornada desde las 07:00"),
             ("sin_atraso", "Sin atraso permitido"), ("penal_x05", r"Externalización $\times0{,}5$"),
             ("penal_x2", r"Externalización $\times2$"), ("bases_fijo_x2", r"Costo de bases $\times2$"),
             ("cap_bases+50", r"Capacidad de bases $+50$\,\%"), ("cap_bases-25", r"Capacidad de bases $-25$\,\%"),
             ("hubs_todas", "Hubs para todas"), ("sin_division", "Sin división")]
  filas = []
  for e, nom in NOMBRES:
    g = [r for r in E if r["escenario"] == e]
    if not g:
      continue
    dm = [float(r["dcosto_math_pct"]) for r in g]
    ah = [float(r["ahorro_pct"]) for r in g]
    ex = [(float(r["ext_math"]) - float(ref["ext_math"])) for r in g
          for ref in E if ref["escenario"] == "base" and ref["instancia"] == r["instancia"] and ref["semana"] == r["semana"]]
    rng = lambda v, s=False: (pct(v[0], 1, s) if len(v) == 1 else
                              f"{pct(min(v),1,s)} a {pct(max(v),1,s)}")
    filas.append(f"{nom} & {len(g)} & {rng(dm, True)} & {rng(ah)} & {sig(st.mean(ex))} \\\\")
  (TAB / "sens_resumen.tex").write_text("\n".join(filas) + "\n", encoding="utf-8")

  # detalle por semana (apéndice)
  filas = []
  semanas = [(1, 1), (7, 4), (8, 3), (10, 3)]
  for e, nom in [("base", "Datos originales")] + NOMBRES:
    celdas = []
    for i, w in semanas:
      r = next((r for r in E if r["escenario"] == e and int(r["instancia"]) == i and int(r["semana"]) == w), None)
      celdas.append(f"{f(r['math'],2)} & {f(r['ahorro_pct'])}" if r else "-- & --")
    filas.append(f"{nom} & " + " & ".join(celdas) + " \\\\")
  (TAB / "sens_detalle.tex").write_text("\n".join(filas) + "\n", encoding="utf-8")

  # ---------- cierre de bases ----------
  BASES = ["quilicura", "pudahuel", "renca", "cerrillos", "san_bernardo", "macul", "penalolen", "lampa", "talagante"]
  NOMB = {"san_bernardo": "San Bernardo", "penalolen": "Peñalolén"}
  import sys
  sys.path.insert(0, ".")
  from matheuristica import datos
  cfg = datos.Config(tipo_instancia="big", hoja_instancia="Instancia 7", semana=4)
  inst = datos.cargar(cfg)
  def veh_en(i, w, b):
    p = O / f"posicionamiento_big_Instancia{i}_semana{w}.csv"
    rows = list(csv.DictReader(open(p)))
    col = next(k for k in rows[0] if "base" in k.lower())
    return sum(1 for r in rows if r[col] == "B_" + b.upper())
  filas = []
  for b in BASES:
    bb = inst.bases["B_" + b.upper()]
    celdas = []
    for i, w in ((7, 4), (10, 3)):
      r = next(r for r in E if r["escenario"] == f"sin_{b}" and int(r["instancia"]) == i and int(r["semana"]) == w)
      celdas.append(f"{veh_en(i, w, b)} & {pct(r['dcosto_math_pct'], 1, True)}")
    filas.append(f"{NOMB.get(b, b.title())} & {bb.capacidad} & {f(bb.costo_fijo/1000,0)} & " + " & ".join(celdas) + " \\\\")
  (TAB / "bases_cierre.tex").write_text("\n".join(filas) + "\n", encoding="utf-8")

  # ---------- base adicional ----------
  filas = []
  for e, nom in (("base_en_providencia", "Providencia"), ("base_en_puente_alto", "Puente Alto"), ("base_en_centro", "Centro")):
    celdas = []
    for i, w in ((7, 4), (10, 3)):
      r = next(r for r in E if r["escenario"] == e and int(r["instancia"]) == i and int(r["semana"]) == w)
      rows = list(csv.DictReader(open(O / f"posicionamiento_big_Instancia{i}_semana{w}_esc-{e}.csv")))
      nv = sum(1 for x in rows if x["base"] == "B_NUEVA")
      celdas.append(f"{nv} & {pct(r['dcosto_math_pct'], 1, True)} & {f(r['ext_math'],0)}")
    filas.append(f"{nom} & " + " & ".join(celdas) + " \\\\")
  (TAB / "base_nueva.tex").write_text("\n".join(filas) + "\n", encoding="utf-8")

  # ---------- furgones ----------
  filas = []
  for e, nom in (("base", "18 (original)"), ("furgon+2", "20"), ("furgon+4", "22"), ("furgon+8", "26")):
    celdas = []
    for i, w in ((7, 4), (10, 3)):
      r = next(r for r in E if r["escenario"] == e and int(r["instancia"]) == i and int(r["semana"]) == w)
      celdas.append(f"{f(r['math'],2)} & {f(r['furg_math'],0)} & {f(r['ext_math'],0)}")
    filas.append(f"{nom} & " + " & ".join(celdas) + " \\\\")
  (TAB / "furgones.tex").write_text("\n".join(filas) + "\n", encoding="utf-8")

  # ---------- figura demanda y congestión ----------
  plt.rcParams.update({"font.family": "serif", "font.size": 9})
  fig, axs = plt.subplots(1, 2, figsize=(7.5, 3.0), sharey=False)
  estilos = {(7, 4): ("#1f4e79", "o", "Instancia 7, semana 4"), (10, 3): ("#b85c00", "s", "Instancia 10, semana 3")}
  for ax, (pref, xs, xl) in zip(axs, (("demanda", [-20, -10, 0, 10, 20, 30], "Cambio en la demanda (%)"),
                                      ("congestion", [0, 15, 30, 50], "Aumento de los tiempos de viaje (%)"))):
    for (i, w), (c, mk, lab) in estilos.items():
      for metodo, ls, fill in (("math", "-", c), ("base", "--", "white")):
        ys = []
        for x in xs:
          e = "base" if x == 0 else (f"{pref}{x:+d}" if pref == "demanda" else f"{pref}{x}")
          r = next((r for r in E if r["escenario"] == e and int(r["instancia"]) == i and int(r["semana"]) == w), None)
          ys.append(float(r[metodo]) if r else float("nan"))
        ax.plot(xs, ys, ls, color=c, marker=mk, mfc=fill, ms=5, lw=1.2,
                label=f"{lab}, {'matheurística' if metodo == 'math' else 'caso base'}")
    ax.set_xlabel(xl)
    ax.set_ylabel("Costo semanal (MM CLP)")
    ax.grid(alpha=0.3, lw=0.5)
    ax.spines[["top", "right"]].set_visible(False)
  h, l = axs[0].get_legend_handles_labels()
  fig.legend(h, l, loc="lower center", ncol=2, frameon=False, fontsize=8)
  fig.tight_layout(rect=(0, 0.17, 1, 1))
  fig.savefig(FIG / "fig_demanda_congestion.png", dpi=200)
  print("tablas y figuras listas en", a.informe)


if __name__ == "__main__":
  main()
