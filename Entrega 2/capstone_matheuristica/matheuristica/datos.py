"""Lectura del set transversal y de las hojas de instancia.

Convierte los .xlsx en estructuras tipadas. Todas las horas quedan en minutos
desde medianoche (07:15 -> 435), que es la unidad del resto del código.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .config import Config


# --------------------------------------------------------------------------- #
# utilidades de parseo
# --------------------------------------------------------------------------- #
def a_minutos(valor) -> int:
    """'07:15' | datetime.time | 435 -> 435."""
    if valor is None:
        raise ValueError("hora vacía")
    if isinstance(valor, (int, float)):
        return int(valor)
    if hasattr(valor, "hour"):
        return valor.hour * 60 + valor.minute
    txt = str(valor).strip()
    if ":" in txt:
        h, m = txt.split(":")[:2]
        return int(h) * 60 + int(m)
    return int(float(txt))


def a_bool(valor) -> bool:
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, (int, float)):
        return bool(int(valor))
    return str(valor).strip().lower() in {"true", "1", "si", "sí", "yes"}


def a_lista(valor) -> list[str]:
    """Acepta JSON ('["A","B"]') o separado por pipes ('A | B')."""
    if valor is None:
        return []
    if isinstance(valor, (list, tuple)):
        return list(valor)
    txt = str(valor).strip()
    if txt.startswith("["):
        return [str(x) for x in json.loads(txt)]
    return [t.strip() for t in txt.split("|") if t.strip()]


# --------------------------------------------------------------------------- #
# entidades
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Vehiculo:
    id: str
    clase: str
    capacidad: int
    costo_fijo: float
    costo_km: float
    costo_sobretiempo: float
    clases_compatibles: frozenset[str]


@dataclass(frozen=True)
class Base:
    id: str
    lat: float
    lon: float
    capacidad: int
    costo_fijo: float


@dataclass(frozen=True)
class Hub:
    id: str
    lat: float
    lon: float
    costo_fijo: float
    costo_handling: float
    cap_diaria_ops: int
    cap_diaria_cantidad: float
    apertura: int
    cierre: int
    serv_drop: int
    serv_pick: int


@dataclass(frozen=True)
class ClaseCarga:
    nombre: str
    serv_pickup: int
    serv_delivery: int
    max_transport: int
    transferible: bool
    divisible: bool
    tardanza_ok: bool
    penal_tardanza: float
    penal_externalizacion: float      # <- la que manda (indicación del profesor)
    min_cantidad_split: int
    max_vehiculos_split: int


@dataclass(frozen=True)
class Solicitud:
    id: str
    dia: int
    origen: str
    destino: str
    clase: str
    cantidad: int
    ini_pickup: int
    fin_pickup: int
    ini_delivery: int
    due_delivery: int
    serv_pickup: int
    serv_delivery: int
    max_transport: int
    vehiculos: frozenset[str]
    transferible: bool
    divisible: bool
    tardanza_ok: bool
    penal_tardanza: float
    min_cantidad_split: int
    max_vehiculos_split: int
    penal_externalizacion: float


@dataclass
class Instancia:
    cfg: Config
    vehiculos: dict[str, Vehiculo]
    bases: dict[str, Base]
    hubs: dict[str, Hub]
    clases: dict[str, ClaseCarga]
    incompatibles: set[frozenset]
    coords: dict[str, tuple[float, float]]     # id lógico -> (lat, lon)
    solicitudes: list[Solicitud]

    def por_dia(self, dia: int) -> list[Solicitud]:
        return [s for s in self.solicitudes if s.dia == dia]

    @property
    def dias(self) -> list[int]:
        return sorted({s.dia for s in self.solicitudes})


# --------------------------------------------------------------------------- #
# carga
# --------------------------------------------------------------------------- #
def cargar(cfg: Config) -> Instancia:
    tx = pd.read_excel(cfg.archivo_transversal, sheet_name=None)
    es_small = cfg.tipo_instancia == "small"

    # ---- bases -----------------------------------------------------------
    bases: dict[str, Base] = {}
    for _, f in tx["Bases"].iterrows():
        if es_small and not a_bool(f["available_small_instances"]):
            continue
        bases[f["base_id"]] = Base(
            id=f["base_id"], lat=float(f["lat"]), lon=float(f["lon"]),
            capacidad=int(f["capacity"]), costo_fijo=float(f["weekly_fixed_cost"]),
        )

    # ---- hubs ------------------------------------------------------------
    hubs: dict[str, Hub] = {}
    for _, f in tx["Transferencias"].iterrows():
        if es_small and not a_bool(f["available_small_instances"]):
            continue
        hubs[f["transfer_id"]] = Hub(
            id=f["transfer_id"], lat=float(f["lat"]), lon=float(f["lon"]),
            costo_fijo=float(f["fixed_cost"]), costo_handling=float(f["handling_cost"]),
            cap_diaria_ops=int(f["daily_capacity_count"]),
            cap_diaria_cantidad=float(f["daily_capacity_quantity"]),
            apertura=a_minutos(f["open_min"]), cierre=a_minutos(f["close_min"]),
            serv_drop=int(f["service_drop_min"]), serv_pick=int(f["service_pick_min"]),
        )

    # ---- vehículos -------------------------------------------------------
    hoja_veh = "Vehiculos_Small" if es_small else "Vehiculos_Big"
    vehiculos: dict[str, Vehiculo] = {}
    for _, f in tx[hoja_veh].iterrows():
        vehiculos[f["vehicle_id"]] = Vehiculo(
            id=f["vehicle_id"], clase=f["vehicle_class"], capacidad=int(f["capacity"]),
            costo_fijo=float(f["fixed_cost"]), costo_km=float(f["cost_per_km"]),
            costo_sobretiempo=float(f["overtime_cost_per_min"]),
            clases_compatibles=frozenset(a_lista(f["compatible_classes"])),
        )

    # ---- clases ----------------------------------------------------------
    clases: dict[str, ClaseCarga] = {}
    for _, f in tx["Clases_Solicitud"].iterrows():
        clases[f["cargo_class"]] = ClaseCarga(
            nombre=f["cargo_class"],
            serv_pickup=int(f["pickup_service_min"]),
            serv_delivery=int(f["delivery_service_min"]),
            max_transport=int(f["max_transport_min"]),
            transferible=a_bool(f["transferable"]),
            divisible=a_bool(f["split_allowed"]),
            tardanza_ok=a_bool(f["late_allowed"]),
            penal_tardanza=float(f["late_penalty_per_min"]),
            penal_externalizacion=float(f["externalization_penalty"]),
            min_cantidad_split=int(f["min_split_quantity"]),
            max_vehiculos_split=int(f["max_split_vehicles"]),
        )

    # ---- incompatibilidades ---------------------------------------------
    incompatibles = {
        frozenset((f["clase_1"], f["clase_2"]))
        for _, f in tx["Incompatibilidades"].iterrows()
    }

    # ---- coordenadas -----------------------------------------------------
    coords: dict[str, tuple[float, float]] = {}
    for _, f in tx["Nodos"].iterrows():
        coords[f["node_id"]] = (float(f["lat"]), float(f["lon"]))
    for b in bases.values():
        coords[b.id] = (b.lat, b.lon)
    for h in hubs.values():
        coords[h.id] = (h.lat, h.lon)

    # ---- solicitudes de la instancia/semana ------------------------------
    df = pd.read_excel(cfg.archivo_instancias, sheet_name=cfg.hoja_instancia)
    df = df[df["week_of_month"] == cfg.semana]

    solicitudes: list[Solicitud] = []
    for _, f in df.iterrows():
        cl = clases[f["cargo_class"]]
        vehs = frozenset(v for v in a_lista(f["compatible_vehicles"]) if v in vehiculos)
        # coordenadas: la hoja de instancia las trae; sirven de respaldo
        coords.setdefault(f["origin_id"], (float(f["origin_lat"]), float(f["origin_lon"])))
        coords.setdefault(f["destination_id"],
                          (float(f["destination_lat"]), float(f["destination_lon"])))
        solicitudes.append(Solicitud(
            id=f["request_id"], dia=int(f["day"]),
            origen=f["origin_id"], destino=f["destination_id"],
            clase=f["cargo_class"], cantidad=int(f["quantity"]),
            ini_pickup=a_minutos(f["pickup_window_start"]),
            fin_pickup=a_minutos(f["pickup_window_end"]),
            ini_delivery=a_minutos(f["delivery_window_start"]),
            due_delivery=a_minutos(f["delivery_due"]),
            serv_pickup=int(f["pickup_service_min"]),
            serv_delivery=int(f["delivery_service_min"]),
            max_transport=int(f["max_transport_min"]),
            vehiculos=vehs,
            transferible=a_bool(f["transferable"]) and cl.transferible,
            divisible=a_bool(f["split_allowed"]) and cl.divisible,
            tardanza_ok=a_bool(f["late_allowed"]) and cl.tardanza_ok,
            penal_tardanza=float(f["late_penalty_per_min"]),
            min_cantidad_split=int(f["min_split_quantity"]),
            max_vehiculos_split=int(f["max_split_vehicles"]),
            # >>> indicación del profesor: se ignora la columna de la instancia
            penal_externalizacion=cl.penal_externalizacion,
        ))

    return Instancia(cfg=cfg, vehiculos=vehiculos, bases=bases, hubs=hubs,
                     clases=clases, incompatibles=incompatibles,
                     coords=coords, solicitudes=solicitudes)
