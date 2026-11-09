# python3 graficar_ruta_dia.py --tipo small --instancia 4 --semana 3 --dia 3 --grafo data/grafo_santiago


from __future__ import annotations

import argparse
import math
import pickle
import sys
from pathlib import Path

import folium
import numpy as np
import pandas as pd

try:
    import networkx as nx
    import osmnx as ox
    HAS_OSMNX = True
except ImportError:
    HAS_OSMNX = False

sys.path.insert(0, ".")

# paleta cualitativa de 20 colores bien distinguibles entre sí (tipo tab20)
PALETA = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b",
    "#e377c2", "#7f7f7f", "#bcbd22", "#17becf", "#aec7e8", "#ffbb78",
    "#98df8a", "#ff9896", "#c5b0d5", "#c49c94", "#f7b6d2", "#c7c7c7",
    "#dbdb8d", "#9edae5",
]


# grafo vial

class Ruteador:
    def __init__(self, ruta_grafo: str | None):
        self.G = None
        if ruta_grafo and HAS_OSMNX and Path(ruta_grafo).exists():
            with open(ruta_grafo, "rb") as fh:
                self.G = pickle.load(fh)
            if self.G.graph.get("crs") is None:
                self.G.graph["crs"] = "EPSG:4326"
        self._snap, self._tramo = {}, {}

    @property
    def modo(self):
        return "red vial real (OSMnx)" if self.G is not None else "línea recta (sin grafo)"

    def _nodo(self, lat, lon):
        k = (round(lat, 6), round(lon, 6))
        if k not in self._snap:
            self._snap[k] = ox.distance.nearest_nodes(self.G, X=lon, Y=lat)
        return self._snap[k]

    def polilinea(self, paradas: list[dict]) -> list[list[float]]:
        if self.G is None or len(paradas) < 2:
            return [[p["lat"], p["lon"]] for p in paradas]
        coords = [[paradas[0]["lat"], paradas[0]["lon"]]]
        for a, b in zip(paradas[:-1], paradas[1:]):
            na, nb = self._nodo(a["lat"], a["lon"]), self._nodo(b["lat"], b["lon"])
            if (na, nb) not in self._tramo:
                try:
                    path = nx.shortest_path(self.G, na, nb, weight="travel_time")
                    self._tramo[(na, nb)] = [[float(self.G.nodes[n]["y"]),
                                             float(self.G.nodes[n]["x"])] for n in path]
                except nx.NetworkXNoPath:
                    self._tramo[(na, nb)] = [[a["lat"], a["lon"]], [b["lat"], b["lon"]]]
            coords += self._tramo[(na, nb)][1:]
        return coords


def stop_icon(numero, color, tipo, es_hub):
    if es_hub:
        html = (f'<div style="width:22px;height:22px;transform:rotate(45deg);'
               f'background:{color};border:3px solid #111;box-sizing:border-box;">'
               f'<div style="transform:rotate(-45deg);color:#fff;font-size:9px;'
               f'font-weight:bold;text-align:center;line-height:16px;">{numero}</div></div>')
        return folium.DivIcon(html=html, icon_size=(22, 22), icon_anchor=(11, 11))
    forma = "border-radius:50%;" if tipo == "retiro" else "border-radius:4px;"
    html = (f'<div style="background:{color};color:#fff;border:2px solid white;{forma}'
           f'width:22px;height:22px;line-height:18px;text-align:center;font-size:10px;'
           f'font-weight:bold;box-shadow:0 1px 3px rgba(0,0,0,.5);">{numero}</div>')
    return folium.DivIcon(html=html, icon_size=(22, 22), icon_anchor=(11, 11))


def base_icon(color):
    html = (f'<div style="background:white;border:3px solid {color};border-radius:50%;'
           'width:24px;height:24px;display:flex;align-items:center;justify-content:center;'
           'font-size:13px;box-shadow:0 1px 3px rgba(0,0,0,.5);">🏠</div>')
    return folium.DivIcon(html=html, icon_size=(24, 24), icon_anchor=(12, 12))


def hub_context_icon():
    html = ('<div style="width:16px;height:16px;transform:rotate(45deg);'
           'background:#9ca3af;border:2px solid #4b5563;"></div>')
    return folium.DivIcon(html=html, icon_size=(16, 16), icon_anchor=(8, 8))


def externalizada_icon():
    html = ('<div style="color:#dc2626;font-size:20px;font-weight:bold;'
           'text-shadow:0 0 3px white,0 0 3px white,0 0 3px white;">✕</div>')
    return folium.DivIcon(html=html, icon_size=(20, 20), icon_anchor=(10, 10))


def separar_solapados(marcadores: list[dict], radio_m: float = 14.0) -> list[dict]:
    from collections import defaultdict
    grupos = defaultdict(list)
    for i, m in enumerate(marcadores):
        grupos[(round(m["lat"], 5), round(m["lon"], 5))].append(i)
    for (lat0, _), idxs in grupos.items():
        n = len(idxs)
        if n <= 1:
            continue
        m_lat = 111_320.0
        m_lon = 111_320.0 * math.cos(math.radians(lat0)) or 1.0
        for j, i in enumerate(idxs):
            ang = 2 * math.pi * j / n
            marcadores[i]["lat"] += radio_m * math.sin(ang) / m_lat
            marcadores[i]["lon"] += radio_m * math.cos(ang) / m_lon
    return marcadores


# --------------------------------------------------------------------------- #
def paradas_de(rutas: pd.DataFrame, dia: int, vehiculo: str, coords: dict,
              hub_ids: set[str]) -> list[dict]:
    g = rutas[(rutas.dia == dia) & (rutas.vehiculo == vehiculo)].sort_values("orden")
    out = []
    for _, r in g.iterrows():
        if r.nodo not in coords:
            continue
        lat, lon = coords[r.nodo]
        out.append(dict(lat=lat, lon=lon, nodo=r.nodo, tipo=r.tipo,
                        solicitud=r.solicitud, clase=r.clase, es_hub=r.nodo in hub_ids))
    return out


LEYENDA_BASE_HTML = """
<div style="position:fixed;bottom:20px;left:20px;z-index:9999;background:white;
     padding:8px 12px;border-radius:6px;border:1px solid #999;font-size:11px;
     line-height:1.5;box-shadow:0 1px 4px rgba(0,0,0,.3);">
  <b>Símbolos</b><br>
  ● retiro &nbsp; ■ entrega &nbsp;
  <span style="display:inline-block;width:11px;height:11px;transform:rotate(45deg);
        background:#666;border:2px solid #111;"></span> parada en hub<br>
  <span style="display:inline-block;width:13px;height:13px;transform:rotate(45deg);
        background:#9ca3af;border:2px solid #4b5563;"></span> hub disponible (no usado) &nbsp;
  🏠 base &nbsp; <span style="color:#dc2626;font-weight:bold;">✕</span> externalizada
</div>
"""

def formato_clp(valor):
    return f"${valor:,.0f}".replace(",", ".")


def calcular_metricas_dia(
    rutas,
    externalizadas,
    dia,
    inst,
    M,
    cfg
):
    """
    Reconstruye los costos variables diarios usando las mismas
    definiciones de ruta.py y maestro.py.

    Incluye:
      - kilómetros
      - sobretiempo
      - tardanza
      - operaciones en hubs
      - externalización

    Excluye:
      - costo fijo de vehículos
      - costo fijo de bases
      - costo fijo de hubs
    """

    rutas_dia = (
        rutas[rutas["dia"] == dia]
        .copy()
        .sort_values(
            ["vehiculo", "orden"]
        )
    )

    solicitudes = {
        solicitud.id: solicitud
        for solicitud in inst.solicitudes
    }

    # ---------------------------------------------------------
    # 1. Kilómetros, sobretiempo y costo por vehículo
    # ---------------------------------------------------------

    distancia_total = 0.0
    sobretiempo_total = 0.0

    costo_km_total = 0.0
    costo_sobretiempo_total = 0.0

    detalle_vehiculos = []

    for (vehiculo_id, base), grupo in rutas_dia.groupby(
        ["vehiculo", "base"],
        sort=False
    ):
        grupo = grupo.sort_values("orden")

        vehiculo = inst.vehiculos[vehiculo_id]

        # La ruta sale desde la base, visita todas las paradas
        # y finalmente vuelve a la misma base.
        nodos = (
            [base]
            + grupo["nodo"].tolist()
            + [base]
        )

        distancia_vehiculo = sum(
            M.dist(origen, destino)
            for origen, destino in zip(
                nodos[:-1],
                nodos[1:]
            )
        )

        # El retorno incluye el viaje desde la última parada
        # hasta la base.
        ultima_parada = grupo.iloc[-1]

        retorno = (
            float(ultima_parada["fin_servicio_min"])
            + M.tiempo(
                ultima_parada["nodo"],
                base
            )
        )

        sobretiempo_vehiculo = max(
            0.0,
            retorno - cfg.jornada_fin
        )

        costo_km_vehiculo = (
            distancia_vehiculo
            * vehiculo.costo_km
        )

        costo_sobretiempo_vehiculo = (
            sobretiempo_vehiculo
            * vehiculo.costo_sobretiempo
        )

        distancia_total += distancia_vehiculo
        sobretiempo_total += sobretiempo_vehiculo

        costo_km_total += costo_km_vehiculo
        costo_sobretiempo_total += (
            costo_sobretiempo_vehiculo
        )

        detalle_vehiculos.append({
            "vehiculo": vehiculo_id,
            "base": base,
            "distancia_km": distancia_vehiculo,
            "retorno_min": retorno,
            "sobretiempo_min": sobretiempo_vehiculo,
            "costo_km": costo_km_vehiculo,
            "costo_sobretiempo": (
                costo_sobretiempo_vehiculo
            )
        })

    # ---------------------------------------------------------
    # 2. Tardanza
    # ---------------------------------------------------------

    tardanza_total = 0.0
    costo_tardanza_total = 0.0

    entregas = rutas_dia[
        rutas_dia["tipo"] == "entrega"
    ]

    for _, entrega in entregas.iterrows():

        if pd.isna(entrega["due_min"]):
            continue

        atraso = max(
            0.0,
            float(entrega["fin_servicio_min"])
            - float(entrega["due_min"])
        )

        solicitud = solicitudes.get(
            entrega["solicitud"]
        )

        if solicitud is None:
            continue

        tardanza_total += atraso

        costo_tardanza_total += (
            atraso
            * solicitud.penal_tardanza
        )

    # ---------------------------------------------------------
    # 3. Costos de transferencia en hubs
    # ---------------------------------------------------------

    paradas_hub = rutas_dia[
        rutas_dia["nodo"].isin(inst.hubs)
    ]

    operaciones_hub = len(paradas_hub)

    costo_transferencias_total = sum(
        inst.hubs[fila["nodo"]].costo_handling
        for _, fila in paradas_hub.iterrows()
    )

    # ---------------------------------------------------------
    # 4. Externalización
    # ---------------------------------------------------------

    if (
        externalizadas is not None
        and not externalizadas.empty
        and "solicitud" in externalizadas.columns
    ):
        ids_externalizadas = set(
            externalizadas["solicitud"].astype(str)
        )
    else:
        ids_externalizadas = set()

    externalizadas_dia = [
        solicitud
        for solicitud in inst.solicitudes
        if (
            solicitud.dia == dia
            and solicitud.id in ids_externalizadas
        )
    ]

    costo_externalizacion_total = sum(
        solicitud.penal_externalizacion
        for solicitud in externalizadas_dia
    )

    # ---------------------------------------------------------
    # 5. Costo variable diario total
    # ---------------------------------------------------------

    costo_variable_total = (
        costo_km_total
        + costo_sobretiempo_total
        + costo_tardanza_total
        + costo_transferencias_total
        + costo_externalizacion_total
    )

    return {
        "kilometros": distancia_total,

        "sobretiempo_min": sobretiempo_total,
        "tardanza_min": tardanza_total,

        "operaciones_hub": operaciones_hub,
        "externalizadas": len(externalizadas_dia),

        "costo_km": costo_km_total,
        "costo_sobretiempo": (
            costo_sobretiempo_total
        ),
        "costo_tardanza": costo_tardanza_total,
        "costo_transferencias": (
            costo_transferencias_total
        ),
        "costo_externalizacion": (
            costo_externalizacion_total
        ),

        "costo_variable_total": (
            costo_variable_total
        ),

        "detalle_vehiculos": (
            pd.DataFrame(detalle_vehiculos)
        )
    }

def construir_mapa(rutas: pd.DataFrame, coords: dict, hub_ids: set[str],
                   todos_los_hubs: dict, externalizadas_dia: pd.DataFrame,
                   dia: int, titulo: str, R: Ruteador, salida: Path,
                   color_por_vehiculo: dict, metricas) -> bool:
    vehiculos_dia = sorted(rutas[rutas.dia == dia].vehiculo.unique())
    if not vehiculos_dia:
        print(f"    [aviso] '{titulo}': no hay rutas para el día {dia}, se omite este mapa")
        return False

    todas_paradas = []
    por_vehiculo = {}
    for v in vehiculos_dia:
        p = paradas_de(rutas, dia, v, coords, hub_ids)
        por_vehiculo[v] = p
        todas_paradas += p
    centro = [np.mean([p["lat"] for p in todas_paradas]),
             np.mean([p["lon"] for p in todas_paradas])]


    fmap = folium.Map(location=centro, zoom_start=11, tiles=None)
    folium.TileLayer(
        tiles=(
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}"
        ),
        attr="Tiles &copy; Esri",
        name="Mapa base gris claro",
        overlay=False,
        control=False,
        max_zoom=16,
    ).add_to(fmap)

    # Capa de nombres y referencias geográficas
    folium.TileLayer(
        tiles=(
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}"
        ),
        attr="Labels &copy; Esri",
        name="Nombres de lugares",
        overlay=True,
        control=False,
        max_zoom=16,
    ).add_to(fmap)

    marcadores = []
    for v in vehiculos_dia:
        color = color_por_vehiculo[v]
        paradas = por_vehiculo[v]
        base = rutas[(rutas.dia == dia) & (rutas.vehiculo == v)].base.iloc[0]
        etiqueta = f"{v} (día {dia})"
        folium.PolyLine(R.polilinea(paradas), color=color, weight=4, opacity=0.85,
                        tooltip=f"{etiqueta} · {len(paradas)} paradas").add_to(fmap)
        for i, p in enumerate(paradas, start=1):
            tipo_legible = "retiro" if p["tipo"] == "retiro" else "entrega"
            if p["es_hub"]:
                tipo_legible += " en HUB"
            marcadores.append(dict(
                lat=p["lat"], lon=p["lon"], icon=stop_icon(i, color, p["tipo"], p["es_hub"]),
                tooltip=f"{etiqueta} · parada {i} — {tipo_legible}<br>"
                        f"nodo: {p['nodo']} · solicitud: {p['solicitud']} ({p['clase']})"))
        if base in coords:
            marcadores.append(dict(lat=coords[base][0], lon=coords[base][1],
                                   icon=base_icon(color), tooltip=f"Base — {etiqueta}"))

 

    for _, s in externalizadas_dia.iterrows():
        if s.origen not in coords:
            continue
        lat, lon = coords[s.origen]
        marcadores.append(dict(lat=lat, lon=lon, icon=externalizada_icon(),
                               tooltip=f"EXTERNALIZADA: {s.id} ({s.clase})"))

    for m in separar_solapados(marcadores):
        folium.Marker([m["lat"], m["lon"]], icon=m["icon"], tooltip=m["tooltip"]).add_to(fmap)

    filas_leyenda = "".join(
        f'<span style="color:{color_por_vehiculo[v]};">■</span> {v} '
        f'({len(por_vehiculo[v])//2} solic.) &nbsp;&nbsp;' for v in vehiculos_dia)

    resumen_costos = (
        f'<div style="margin-top:7px;'
        f'padding-top:7px;'
        f'border-top:1px solid #d1d5db;">'

        f'<b>Recorrido:</b> '
        f'{metricas["kilometros"]:.1f} km'

        f'&nbsp;&nbsp;|&nbsp;&nbsp;'

        f'<b>Costo variable diario:</b> '
        f'{formato_clp(metricas["costo_variable_total"])}'

        f'<br>'

        f'<span style="font-size:11px;color:#555;">'

        f'Kilómetros: '
        f'{formato_clp(metricas["costo_km"])} · '

        f'Sobretiempo: '
        f'{formato_clp(metricas["costo_sobretiempo"])} · '

        f'Tardanza: '
        f'{formato_clp(metricas["costo_tardanza"])} · '

        f'Transferencias: '
        f'{formato_clp(metricas["costo_transferencias"])} · '

        f'Externalización: '
        f'{formato_clp(metricas["costo_externalizacion"])}'

        f'</span></div>'
    )

    cabecera = (f'<div style="position:fixed;top:10px;left:50px;z-index:9999;background:white;'
               f'padding:8px 12px;border-radius:6px;border:1px solid #999;font-size:12px;'
               f'max-width:70%;"><b>{titulo} — día {dia}</b><br>{filas_leyenda}'
               f'<br><span style="color:#dc2626;">✕</span> '
               f'{len(externalizadas_dia)} externalizadas'
               f'{resumen_costos}</div>')
    fmap.get_root().html.add_child(folium.Element(cabecera))
    fmap.get_root().html.add_child(folium.Element(LEYENDA_BASE_HTML))
    fmap.save(str(salida))
    print(f"    mapa: {salida}  ({len(vehiculos_dia)} vehículos, "
          f"{len(externalizadas_dia)} externalizadas)")
    return True



# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default="outputs")
    ap.add_argument("--tipo", default="small", choices=["small", "big"])
    ap.add_argument("--instancia", type=int, required=True)
    ap.add_argument("--semana", type=int, required=True)
    ap.add_argument("--dia", type=int, required=True)
    ap.add_argument("--grafo", default="data/grafo_santiago")
    ap.add_argument("--clase_vehiculo", default=None,
                    help="Filtra a UNA clase (p.ej. VAN_GENERAL, VAN_FRIO, FURGON_FRIO). "
                        "Por defecto muestra toda la flota.")
    a = ap.parse_args()

    from matheuristica.config import Config
    from matheuristica import datos as datos_mod
    from matheuristica import matriz as matriz_mod

    cfg = Config()
    cfg.tipo_instancia, cfg.hoja_instancia, cfg.semana = a.tipo, f"Instancia {a.instancia}", a.semana
    inst = datos_mod.cargar(cfg)
    M = matriz_mod.construir(
        cfg,
        inst.coords
    )
    coords = inst.coords
    hub_ids = set(inst.hubs)
    todos_los_hubs = {h.id: coords[h.id] for h in inst.hubs.values() if h.id in coords}
    sol_por_id = {s.id: s for s in inst.solicitudes}

    dir_out = Path(a.dir)
    base_sufijo = f"BASE_{a.tipo}_Instancia{a.instancia}_semana{a.semana}"
    metodo_sufijo = f"{a.tipo}_Instancia{a.instancia}_semana{a.semana}"

    R = Ruteador(a.grafo)
    print(f"Modo de trazado: {R.modo}")
    print(f"Red: {len(inst.bases)} bases, {len(inst.hubs)} hubs disponibles\n")

  
    vehiculos_union = set()
    externalizadas_por_sufijo = {}
    for suf in (base_sufijo, metodo_sufijo):
        try:
            r = pd.read_csv(dir_out / f"rutas_{suf}.csv")
            vehiculos_union |= set(r[r.dia == a.dia].vehiculo.unique())
        except FileNotFoundError:
            pass
        try:
            ext = pd.read_csv(dir_out / f"externalizadas_{suf}.csv")
            externalizadas_por_sufijo[suf] = ext
        except FileNotFoundError:
            externalizadas_por_sufijo[suf] = pd.DataFrame(columns=["solicitud"])
    color_por_vehiculo = {v: PALETA[i % len(PALETA)]
                         for i, v in enumerate(sorted(vehiculos_union))}

    generados = 0
    resultados_comparacion = []
    for suf, titulo in [(base_sufijo, "Caso base"), (metodo_sufijo, "Matheurística")]:
        ruta_csv = dir_out / f"rutas_{suf}.csv"
        if not ruta_csv.exists():
            print(f"[{titulo}] no encontrado: {ruta_csv} (¿corriste esa solución para "
                  f"esta instancia/semana?) -- se omite\n")
            continue
        rutas = pd.read_csv(ruta_csv)
        ext_ids = set(externalizadas_por_sufijo[suf]["solicitud"]) if len(
            externalizadas_por_sufijo[suf]) else set()
        ext_dia = pd.DataFrame([
            dict(id=rid, clase=sol_por_id[rid].clase, origen=sol_por_id[rid].origen)
            for rid in ext_ids if rid in sol_por_id and sol_por_id[rid].dia == a.dia
        ])

        externalizadas_completas = (
            externalizadas_por_sufijo[suf]
        )

        metricas = calcular_metricas_dia(
            rutas=rutas,
            externalizadas=externalizadas_completas,
            dia=a.dia,
            inst=inst,
            M=M,
            cfg=cfg
        )

        resultados_comparacion.append({
            "caso": titulo,
            "kilometros": metricas["kilometros"],
            "sobretiempo_min": (
                metricas["sobretiempo_min"]
            ),
            "tardanza_min": (
                metricas["tardanza_min"]
            ),
            "externalizadas": (
                metricas["externalizadas"]
            ),
            "operaciones_hub": (
                metricas["operaciones_hub"]
            ),
            "costo_km": metricas["costo_km"],
            "costo_sobretiempo": (
                metricas["costo_sobretiempo"]
            ),
            "costo_tardanza": (
                metricas["costo_tardanza"]
            ),
            "costo_transferencias": (
                metricas["costo_transferencias"]
            ),
            "costo_externalizacion": (
                metricas["costo_externalizacion"]
            ),
            "costo_variable_total": (
                metricas["costo_variable_total"]
            )
        })

        salida = dir_out / f"flota_dia{a.dia}_{suf}.html"
        print(f"[{titulo}] ({suf})")
        if construir_mapa(rutas, coords, hub_ids, todos_los_hubs, ext_dia, a.dia,
                          titulo, R, salida, color_por_vehiculo, metricas):
            generados += 1
        print()

    if resultados_comparacion:

        comparacion = pd.DataFrame(
            resultados_comparacion
        )

        archivo_comparacion = dir_out / (
            f"comparacion_costos_dia{a.dia}_"
            f"{a.tipo}_Instancia{a.instancia}_"
            f"semana{a.semana}.csv"
        )

        comparacion.to_csv(
            archivo_comparacion,
            index=False
        )

        print("\n")
        print("=" * 70)
        print("COMPARACIÓN DE COSTOS VARIABLES DEL DÍA")
        print("=" * 70)

        columnas_mostrar = [
            "caso",
            "kilometros",
            "costo_km",
            "costo_sobretiempo",
            "costo_tardanza",
            "costo_transferencias",
            "costo_externalizacion",
            "costo_variable_total"
        ]

        print(
            comparacion[columnas_mostrar]
            .to_string(
                index=False,
                formatters={
                    "kilometros": (
                        lambda x: f"{x:.1f}"
                    ),
                    "costo_km": formato_clp,
                    "costo_sobretiempo": formato_clp,
                    "costo_tardanza": formato_clp,
                    "costo_transferencias": formato_clp,
                    "costo_externalizacion": formato_clp,
                    "costo_variable_total": formato_clp
                }
            )
        )

        casos = comparacion.set_index("caso")

        if (
            "Caso base" in casos.index
            and "Matheurística" in casos.index
        ):
            base = casos.loc["Caso base"]
            modelo = casos.loc["Matheurística"]

            ahorro_total = (
                base["costo_variable_total"]
                - modelo["costo_variable_total"]
            )

            ahorro_pct = (
                100 * ahorro_total
                / base["costo_variable_total"]
                if base["costo_variable_total"] > 0
                else 0
            )

            ahorro_km = (
                base["kilometros"]
                - modelo["kilometros"]
            )

            ahorro_km_pct = (
                100 * ahorro_km
                / base["kilometros"]
                if base["kilometros"] > 0
                else 0
            )

            print("\nAHORRO DE LA MATHEURÍSTICA")
            print(
                f"Kilómetros: "
                f"{ahorro_km:+.1f} km "
                f"({ahorro_km_pct:+.1f}%)"
            )
            print(
                f"Costo variable: "
                f"{formato_clp(ahorro_total)} "
                f"({ahorro_pct:+.1f}%)"
            )

        print(
            f"\nArchivo generado: "
            f"{archivo_comparacion}"
        )

    if generados == 0:
        print("No se generó ningún mapa: revisá que existan los rutas_*.csv de "
              "esta instancia/semana en", dir_out)


if __name__ == "__main__":
    main()
