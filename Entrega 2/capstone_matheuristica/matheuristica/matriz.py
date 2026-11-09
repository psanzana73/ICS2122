"""Matriz de tiempos y distancias entre los puntos lógicos del problema.

Dos fuentes:
  * OSMnx / NetworkX sobre `grafo_santiago` (MultiDiGraph pickleado que entregó
    el curso, con atributos `travel_time` [s] y `length` [m]). Se corre un
    Dijkstra por cada punto de origen -- no un shortest_path por par -- y se
    cachea el resultado en un .npz.
  * Haversine x factor de circuidad a velocidad constante (fallback, y el
    mismo supuesto que usa el caso base).
"""

from __future__ import annotations

import math
import pickle
import time
from pathlib import Path

import numpy as np

from .config import Config


R_TIERRA_KM = 6371.0088


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * R_TIERRA_KM * math.asin(math.sqrt(h))


class Matriz:
    """Acceso O(1) a tiempo [min] y distancia [km] entre dos ids lógicos."""

    def __init__(self, ids: list[str], tiempos: np.ndarray, distancias: np.ndarray):
        self.ids = ids
        self.idx = {k: i for i, k in enumerate(ids)}
        self.t = tiempos
        self.d = distancias

    def tiempo(self, a: str, b: str) -> float:
        return float(self.t[self.idx[a], self.idx[b]])

    def dist(self, a: str, b: str) -> float:
        return float(self.d[self.idx[a], self.idx[b]])

    def vecinos(self, a: str, k: int) -> list[str]:
        fila = self.t[self.idx[a]]
        orden = np.argsort(fila)[: k + 1]
        return [self.ids[i] for i in orden if self.ids[i] != a][:k]


# --------------------------------------------------------------------------- #
def construir(cfg: Config, coords: dict[str, tuple[float, float]]) -> Matriz:
    ids = sorted(coords)
    etiqueta = "osmnx" if cfg.usar_osmnx else "haversine"
    cache = cfg.dir_datos / f"matriz_{etiqueta}_{len(ids)}.npz"

    if cfg.cache_matriz and cache.exists():
        z = np.load(cache, allow_pickle=True)
        if list(z["ids"]) == ids:
            print(f"[matriz] cache: {cache.name}")
            return Matriz(ids, z["t"], z["d"])

    if cfg.usar_osmnx:
        t, d = _matriz_osmnx(cfg, ids, coords)
    else:
        t, d = _matriz_haversine(cfg, ids, coords)

    if cfg.cache_matriz:
        cfg.dir_datos.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(cache, ids=np.array(ids, dtype=object), t=t, d=d)
    return Matriz(ids, t, d)


def _matriz_haversine(cfg, ids, coords):
    n = len(ids)
    t = np.zeros((n, n))
    d = np.zeros((n, n))
    for i, a in enumerate(ids):
        for j, b in enumerate(ids):
            if i == j:
                continue
            km = haversine_km(coords[a], coords[b]) * cfg.factor_circuidad
            d[i, j] = km
            t[i, j] = km / cfg.velocidad_kmh * 60.0
    return t, d


def _matriz_osmnx(cfg, ids, coords):
    import networkx as nx
    import osmnx as ox

    ruta = cfg.dir_datos / cfg.archivo_grafo
    if not ruta.exists():
        cand = sorted(cfg.dir_datos.glob("grafo_santiago*")) + sorted(cfg.dir_datos.glob("*.graphml"))
        if not cand:
            raise FileNotFoundError(
                f"No se encontró el grafo vial en {cfg.dir_datos}. "
                "Poné `grafo_santiago` ahí o usá cfg.usar_osmnx=False."
            )
        ruta = cand[0]

    with open(ruta, "rb") as fh:
        es_pickle = fh.read(1) == b"\x80"
    G = pickle.load(open(ruta, "rb")) if es_pickle else ox.io.load_graphml(filepath=ruta)

    if G.graph.get("crs") is None:
        G.graph["crs"] = "EPSG:4326"
    elif ox.projection.is_projected(G.graph["crs"]):
        G = ox.project_graph(G, to_crs="EPSG:4326")
    G = G.subgraph(max(nx.strongly_connected_components(G), key=len)).copy()
    if not all(dd.get("travel_time") is not None for _, _, _, dd in G.edges(keys=True, data=True)):
        G = ox.routing.add_edge_speeds(G)
        G = ox.routing.add_edge_travel_times(G)

    lats = [coords[i][0] for i in ids]
    lons = [coords[i][1] for i in ids]
    snap = ox.distance.nearest_nodes(G, X=lons, Y=lats)
    snap = [int(s) for s in np.atleast_1d(snap)]

    unicos = sorted(set(snap))
    pos = {s: k for k, s in enumerate(unicos)}
    m = len(unicos)
    Tu = np.full((m, m), np.inf)
    Du = np.full((m, m), np.inf)

    print(f"[matriz] Dijkstra sobre {G.number_of_nodes():,} nodos "
          f"para {m} orígenes (esto toma unos minutos la primera vez)")
    t0 = time.time()
    for k, s in enumerate(unicos):
        lt = nx.single_source_dijkstra_path_length(G, s, weight="travel_time")
        ll = nx.single_source_dijkstra_path_length(G, s, weight="length")
        for j, u in enumerate(unicos):
            if u in lt:
                Tu[k, j] = lt[u] / 60.0        # s -> min
            if u in ll:
                Du[k, j] = ll[u] / 1000.0      # m -> km
        if (k + 1) % 10 == 0:
            print(f"  {k+1}/{m}  ({time.time()-t0:.0f}s)")

    # pares desconectados (no debería haber en el grafo final): respaldo geométrico
    if not np.isfinite(Tu).all():
        print("[matriz] aviso: hay pares sin ruta; se completan con haversine")
    n = len(ids)
    T = np.zeros((n, n))
    D = np.zeros((n, n))
    for i, a in enumerate(ids):
        for j, b in enumerate(ids):
            if i == j:
                continue
            tt = Tu[pos[snap[i]], pos[snap[j]]]
            dd = Du[pos[snap[i]], pos[snap[j]]]
            if not np.isfinite(tt) or not np.isfinite(dd):
                km = haversine_km(coords[a], coords[b]) * cfg.factor_circuidad
                tt, dd = km / cfg.velocidad_kmh * 60.0, km
            T[i, j], D[i, j] = tt, dd
    return T, D
