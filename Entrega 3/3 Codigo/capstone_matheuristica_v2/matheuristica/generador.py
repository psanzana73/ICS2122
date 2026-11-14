"""Generador de instancias de distinto tamaño para el análisis por tamaño.

Escenario "tamPPP_rR": una semana nueva con la red BIG (las 9 bases y los 8 hubs)
y un tamaño de PPP % respecto de BIG (tam050 = la mitad, tam200 = el doble).
R es la réplica (cambia la semilla).

Cómo se generan los datos (siguiendo a los datos reales de las 40 semanas BIG):
  - Solicitudes por día: normal con la media y la desviación observadas para ese
    día de la semana, multiplicadas por el factor de tamaño.
  - Clase de carga: con las proporciones observadas.
  - Cada solicitud parte de una solicitud real de esa clase (plantilla), de la
    que hereda origen, destino, reglas (dividir, transferir, atraso) y el ancho
    de sus ventanas. Así los viajes siguen siendo entre puntos reales de la red.
  - Horario: las ventanas de la plantilla se desplazan con una normal de media 0
    y desviación de 30 min (redondeada a 15 min), dentro del rango observado.
  - Cantidad: normal con la media y desviación observadas para esa clase,
    truncada al mínimo y máximo observados.
  - Flota, cupo de las bases y capacidad de los hubs se multiplican por el
    mismo factor, para que el tamaño sea lo único que cambia.
"""

from __future__ import annotations

import math
import random
from dataclasses import replace
from functools import lru_cache

import pandas as pd

from .datos import Solicitud, a_bool, a_lista, a_minutos

DESV_HORARIO = 30      # min
GRILLA = 15            # min


@lru_cache(maxsize=1)
def _pool(archivo: str):
    hojas = pd.read_excel(archivo, sheet_name=None)
    df = pd.concat([h.assign(hoja=k) for k, h in hojas.items()], ignore_index=True)
    for c in ("pickup_window_start", "pickup_window_end", "delivery_window_start", "delivery_due"):
        df[c + "_m"] = df[c].map(a_minutos)
    por_dia = df.groupby(["hoja", "week_of_month", "day"]).size().groupby("day").agg(["mean", "std"])
    clases = df["cargo_class"].value_counts(normalize=True)
    cant = df.groupby("cargo_class")["quantity"].agg(["mean", "std", "min", "max"])
    lo = int(df["pickup_window_start_m"].min())
    hi = int(df["delivery_due_m"].max())
    plantillas = {c: g.reset_index(drop=True) for c, g in df.groupby("cargo_class")}
    return por_dia, clases, cant, lo, hi, plantillas


def generar(inst, cfg, factor: float, semilla: int) -> None:
    """Reemplaza solicitudes, flota, cupo de bases y hubs de `inst` (en el lugar)."""
    rng = random.Random(semilla)
    por_dia, clases, cant, lo, hi, plantillas = _pool(str(cfg.archivo_instancias))

    # ---- flota escalada ------------------------------------------------------
    por_clase: dict[str, list] = {}
    for k, v in sorted(inst.vehiculos.items()):
        por_clase.setdefault(v.clase, []).append(v)
    vehiculos = {}
    for clase, vs in por_clase.items():
        n = max(1, round(factor * len(vs)))
        for j in range(n):
            molde = vs[j % len(vs)]
            vid = molde.id if j < len(vs) else f"{clase}_{j + 1:02d}"
            vehiculos[vid] = replace(molde, id=vid)
    inst.vehiculos = vehiculos
    ids_por_clase: dict[str, set] = {}
    for k, v in vehiculos.items():
        ids_por_clase.setdefault(v.clase, set()).add(k)
    clase_de_id = {k: v.clase for k, v in vehiculos.items()}

    # ---- bases y hubs escalados ---------------------------------------------
    inst.bases = {b: replace(bb, capacidad=max(1, math.ceil(factor * bb.capacidad)))
                  for b, bb in inst.bases.items()}
    inst.hubs = {h: replace(hh, cap_diaria_ops=max(1, math.ceil(factor * hh.cap_diaria_ops)),
                            cap_diaria_cantidad=max(1.0, factor * hh.cap_diaria_cantidad))
                 for h, hh in inst.hubs.items()}

    # ---- solicitudes ----------------------------------------------------------
    nombres = list(clases.index)
    pesos = list(clases.values)
    solicitudes = []
    for d in sorted(por_dia.index):
        mu, sd = por_dia.loc[d, "mean"], por_dia.loc[d, "std"]
        n = max(1, round(rng.gauss(factor * mu, factor * sd)))
        for j in range(n):
            c = rng.choices(nombres, pesos)[0]
            t = plantillas[c].iloc[rng.randrange(len(plantillas[c]))]
            cl = inst.clases[c]

            # horario: se desplaza toda la plantilla, se mantiene el ancho
            delta = GRILLA * round(rng.gauss(0, DESV_HORARIO) / GRILLA)
            ini_p, fin_p = t["pickup_window_start_m"], t["pickup_window_end_m"]
            ini_d, due_d = t["delivery_window_start_m"], t["delivery_due_m"]
            delta = max(lo - ini_p, min(hi - due_d, delta))

            # cantidad: normal de la clase, truncada al rango observado
            q = cant.loc[c]
            cantidad = int(min(q["max"], max(q["min"], round(rng.gauss(q["mean"], q["std"])))))

            # compatibilidad: todos los vehículos de las clases compatibles
            clases_veh = {clase_de_id.get(v) or v.rsplit("_", 1)[0]
                          for v in a_lista(t["compatible_vehicles"])}
            vehs = frozenset().union(*(ids_por_clase.get(cv, set()) for cv in clases_veh))

            solicitudes.append(Solicitud(
                id=f"G{int(factor * 100):03d}_D{d}_{j + 1:04d}", dia=int(d),
                origen=t["origin_id"], destino=t["destination_id"],
                clase=c, cantidad=cantidad,
                ini_pickup=int(ini_p + delta), fin_pickup=int(fin_p + delta),
                ini_delivery=int(ini_d + delta), due_delivery=int(due_d + delta),
                serv_pickup=int(t["pickup_service_min"]),
                serv_delivery=int(t["delivery_service_min"]),
                max_transport=int(t["max_transport_min"]),
                vehiculos=vehs,
                transferible=a_bool(t["transferable"]) and cl.transferible,
                divisible=a_bool(t["split_allowed"]) and cl.divisible,
                tardanza_ok=a_bool(t["late_allowed"]) and cl.tardanza_ok,
                penal_tardanza=float(t["late_penalty_per_min"]),
                min_cantidad_split=int(t["min_split_quantity"]),
                max_vehiculos_split=int(t["max_split_vehicles"]),
                penal_externalizacion=cl.penal_externalizacion,   # hoja de clases
            ))
            for nodo, la, lo_ in ((t["origin_id"], t["origin_lat"], t["origin_lon"]),
                                  (t["destination_id"], t["destination_lat"], t["destination_lon"])):
                inst.coords.setdefault(nodo, (float(la), float(lo_)))
    inst.solicitudes = solicitudes
