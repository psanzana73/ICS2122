"""Perfil de las solicitudes externalizadas (ambos métodos, 40 semanas BIG)."""
import pandas as pd
from pathlib import Path
from matheuristica.config import Config
from matheuristica import datos

filas = []
for i in range(1, 11):
    for w in range(1, 5):
        cfg = Config(tipo_instancia="big", hoja_instancia=f"Instancia {i}", semana=w)
        inst = datos.cargar(cfg)
        ext = {}
        for met, f in [("math", Path(f"outputs/externalizadas_big_Instancia{i}_semana{w}.csv")),
                       ("base", Path(f"outputs/base_v2/externalizadas_BASE_big_Instancia{i}_semana{w}.csv"))]:
            ext[met] = set(pd.read_csv(f).iloc[:, 0]) if f.exists() and f.stat().st_size > 10 else set()
        for s in inst.solicitudes:
            filas.append(dict(inst=i, sem=w, id=s.id, clase=s.clase, q=s.cantidad, dia=s.dia,
                              vent_pick=s.fin_pickup - s.ini_pickup, ini_pick=s.ini_pickup,
                              divisible=s.divisible, transferible=s.transferible,
                              ext_math=s.id in ext["math"], ext_base=s.id in ext["base"]))
df = pd.DataFrame(filas)
df.to_csv("outputs/analisis/solicitudes_ext.csv", index=False)
for col in ["ext_base", "ext_math"]:
    e = df[df[col]]
    print(col, len(e), "por semana", len(e) / 40)
    print(e.clase.value_counts(normalize=True).round(3).to_dict())
    print("q media", e.q.mean().round(1), "| todas", df.q.mean().round(1))
    print("insumo q>70:", (e.q > 70).mean().round(3), "| todas", (df.q > 70).mean().round(3))
    print("ventana retiro media", e.vent_pick.mean().round(0), "| todas", df.vent_pick.mean().round(0))
    print("ventana <=60:", (e.vent_pick <= 60).mean().round(3), "| todas", (df.vent_pick <= 60).mean().round(3))
    print("abre retiro antes 9:00", (e.ini_pick < 9 * 60).mean().round(3), "| todas", (df.ini_pick < 9 * 60).mean().round(3))
    print("por dia", e.dia.value_counts().sort_index().to_dict())
print("ambos:", (df.ext_math & df.ext_base).sum(), "solo math", (df.ext_math & ~df.ext_base).sum(), "solo base", (~df.ext_math & df.ext_base).sum())
