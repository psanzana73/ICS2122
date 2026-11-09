"""Genera un mapa global de SMALL y otro de BIG.

Cada mapa consolida TODAS las hojas, semanas y dias del archivo de instancias
correspondiente. Muestra todos los nodos de origen/destino presentes en esa
base de datos, todas sus bases disponibles y todos sus hubs disponibles.

No lee soluciones, rutas, activaciones ni archivos CSV de resultados.

Uso:
    python3 graficar_red_completa.py
    python3 graficar_red_completa.py --dir outputs
"""

from __future__ import annotations

import argparse
import html
import sys
from collections import Counter, defaultdict
from pathlib import Path

import folium
import pandas as pd
from folium.plugins import Fullscreen

sys.path.insert(0, ".")


# Paleta de la presentacion
AZUL = "#0B6BD3"
AZUL_OSCURO = "#173F6B"
NARANJO = "#E79A3B"
TEXTO = "#202124"


def a_bool(valor) -> bool:
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, (int, float)) and not pd.isna(valor):
        return bool(int(valor))
    return str(valor).strip().lower() in {"true", "1", "si", "sí", "yes"}


def formato_clp(valor) -> str:
    return f"${float(valor):,.0f}".replace(",", ".")


def icono_base():
    contenido = (
        f'<div style="width:29px;height:29px;border-radius:7px;'
        f'background:{AZUL_OSCURO};border:2px solid white;'
        'box-shadow:0 1px 5px rgba(0,0,0,.45);color:white;'
        'font:700 15px/25px Arial;text-align:center;">B</div>'
    )
    return folium.DivIcon(html=contenido, icon_size=(29, 29), icon_anchor=(14, 14))


def icono_hub():
    contenido = (
        f'<div style="width:25px;height:25px;transform:rotate(45deg);'
        f'background:{NARANJO};border:2px solid white;'
        'box-shadow:0 1px 5px rgba(0,0,0,.45);">'
        '<div style="transform:rotate(-45deg);color:white;'
        'font:700 12px/21px Arial;text-align:center;">H</div></div>'
    )
    return folium.DivIcon(html=contenido, icon_size=(25, 25), icon_anchor=(12, 12))


def agregar_fondo(fmap: folium.Map) -> None:
    """Usa el mismo mapa gris claro de los mapas de las soluciones."""
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


def cargar_universo(tipo: str):
    """Lee la base completa SMALL o BIG, sin escoger instancia ni semana."""
    from matheuristica.config import Config

    cfg = Config()
    cfg.tipo_instancia = tipo

    # Datos transversales: catalogo de nodos y recursos.
    transversal = pd.read_excel(cfg.archivo_transversal, sheet_name=None)

    bases = transversal["Bases"].copy()
    hubs = transversal["Transferencias"].copy()

    # Tal como en datos.py: SMALL usa solo recursos habilitados para small;
    # BIG dispone del catalogo completo.
    if tipo == "small":
        bases = bases[bases["available_small_instances"].apply(a_bool)].copy()
        hubs = hubs[hubs["available_small_instances"].apply(a_bool)].copy()

    # Coordenadas del catalogo transversal.
    coords = {
        str(f["node_id"]): (float(f["lat"]), float(f["lon"]))
        for _, f in transversal["Nodos"].iterrows()
    }

    # Lee TODAS las hojas del archivo de instancias del tamano elegido.
    hojas = pd.read_excel(cfg.archivo_instancias, sheet_name=None)
    frames = []
    columnas_minimas = {"origin_id", "destination_id"}
    for nombre_hoja, df in hojas.items():
        if not columnas_minimas.issubset(df.columns):
            continue
        bloque = df.copy()
        bloque["_hoja"] = nombre_hoja
        frames.append(bloque)

    if not frames:
        raise ValueError(
            f"El archivo {cfg.archivo_instancias} no contiene hojas con "
            "origin_id y destination_id."
        )

    solicitudes = pd.concat(frames, ignore_index=True)

    # Respalda coordenadas con las incluidas en las propias solicitudes.
    for _, fila in solicitudes.iterrows():
        origen = str(fila["origin_id"])
        destino = str(fila["destination_id"])
        if pd.notna(fila.get("origin_lat")) and pd.notna(fila.get("origin_lon")):
            coords.setdefault(origen, (float(fila["origin_lat"]), float(fila["origin_lon"])))
        if pd.notna(fila.get("destination_lat")) and pd.notna(fila.get("destination_lon")):
            coords.setdefault(
                destino,
                (float(fila["destination_lat"]), float(fila["destination_lon"])),
            )

    return solicitudes, bases, hubs, coords, len(frames)


def leyenda_html(n_nodos: int, n_bases: int, n_hubs: int) -> str:
    return f"""
    <div style="position:fixed;bottom:22px;left:22px;z-index:9999;
         background:rgba(255,255,255,.96);padding:12px 15px;border-radius:9px;
         border:1px solid #d1d5db;box-shadow:0 2px 8px rgba(0,0,0,.18);
         color:{TEXTO};font:13px/1.65 Arial,sans-serif;">
      <b style="font-size:14px;">Elementos disponibles</b><br>
      <span style="display:inline-block;width:11px;height:11px;border-radius:50%;
            background:{AZUL};border:1.5px solid white;box-shadow:0 0 0 1px {AZUL};">
      </span>&nbsp; Nodos ({n_nodos})<br>
      <span style="display:inline-block;width:17px;height:17px;border-radius:4px;
            background:{AZUL_OSCURO};color:white;font:bold 11px/17px Arial;
            text-align:center;">B</span>&nbsp; Bases ({n_bases})<br>
      <span style="display:inline-block;width:15px;height:15px;transform:rotate(45deg);
            background:{NARANJO};border:1px solid white;"></span>
      &nbsp;&nbsp; Hubs ({n_hubs})
    </div>
    """


def cabecera_html(tipo: str, n_hojas: int, n_registros: int, n_semanas: int) -> str:
    contenido = f"""
    <div style="position:fixed;top:12px;left:55px;z-index:9999;
         background:rgba(255,255,255,.96);padding:10px 15px;border-radius:9px;
         border:1px solid #d1d5db;box-shadow:0 2px 8px rgba(0,0,0,.18);
         color:{TEXTO};font:13px/1.45 Arial,sans-serif;">
      <b style="color:{AZUL_OSCURO};font-size:16px;">
        Red completa de nodos y recursos — {tipo.upper()}
      </b><br>
      Todas las instancias, semanas y dias · {n_hojas} hojas ·
      {n_semanas} semanas identificadas · {n_registros:,} registros
    </div>
    """
    return contenido.replace(",", ".")


def construir_mapa_global(tipo: str, dir_salida: Path) -> Path:
    solicitudes, bases, hubs, coords, n_hojas = cargar_universo(tipo)

    usos = Counter()
    roles: dict[str, set[str]] = defaultdict(set)
    clases: dict[str, set[str]] = defaultdict(set)
    hojas_por_nodo: dict[str, set[str]] = defaultdict(set)

    for _, solicitud in solicitudes.iterrows():
        origen = str(solicitud["origin_id"])
        destino = str(solicitud["destination_id"])
        clase = str(solicitud.get("cargo_class", "No informada"))
        hoja = str(solicitud["_hoja"])

        usos[origen] += 1
        usos[destino] += 1
        roles[origen].add("origen")
        roles[destino].add("destino")
        clases[origen].add(clase)
        clases[destino].add(clase)
        hojas_por_nodo[origen].add(hoja)
        hojas_por_nodo[destino].add(hoja)

    ids_bases = set(bases["base_id"].astype(str))
    ids_hubs = set(hubs["transfer_id"].astype(str))
    nodos = sorted((set(roles) - ids_bases - ids_hubs) & set(coords))

    puntos = [coords[nodo] for nodo in nodos]
    puntos += [(float(f["lat"]), float(f["lon"])) for _, f in bases.iterrows()]
    puntos += [(float(f["lat"]), float(f["lon"])) for _, f in hubs.iterrows()]
    if not puntos:
        raise ValueError(f"No se encontraron coordenadas para la base {tipo.upper()}.")

    centro = [
        sum(lat for lat, _ in puntos) / len(puntos),
        sum(lon for _, lon in puntos) / len(puntos),
    ]
    fmap = folium.Map(
        location=centro,
        zoom_start=10,
        tiles=None,
        control_scale=True,
        prefer_canvas=True,
    )
    agregar_fondo(fmap)

    capa_nodos = folium.FeatureGroup(name=f"Nodos ({len(nodos)})", show=True)
    capa_bases = folium.FeatureGroup(name=f"Bases ({len(bases)})", show=True)
    capa_hubs = folium.FeatureGroup(name=f"Hubs ({len(hubs)})", show=True)

    for nodo in nodos:
        lat, lon = coords[nodo]
        tooltip = (
            f"<b>Nodo:</b> {html.escape(nodo)}<br>"
            f"<b>Rol:</b> {html.escape(' y '.join(sorted(roles[nodo])))}<br>"
            f"<b>Apariciones en la base:</b> {usos[nodo]}<br>"
            f"<b>Clases:</b> {html.escape(', '.join(sorted(clases[nodo])))}<br>"
            f"<b>Instancias:</b> {html.escape(', '.join(sorted(hojas_por_nodo[nodo])))}"
        )
        folium.CircleMarker(
            [lat, lon], radius=5, color="white", weight=1.5,
            fill=True, fill_color=AZUL, fill_opacity=0.88,
            tooltip=folium.Tooltip(tooltip, sticky=True),
        ).add_to(capa_nodos)

    for _, base in bases.iterrows():
        tooltip = (
            f"<b>Base:</b> {html.escape(str(base['base_id']))}<br>"
            f"<b>Capacidad:</b> {int(base['capacity'])} vehiculos<br>"
            f"<b>Costo fijo semanal:</b> {formato_clp(base['weekly_fixed_cost'])}"
        )
        folium.Marker(
            [float(base["lat"]), float(base["lon"])],
            icon=icono_base(), tooltip=folium.Tooltip(tooltip, sticky=True),
        ).add_to(capa_bases)

    for _, hub in hubs.iterrows():
        tooltip = (
            f"<b>Hub:</b> {html.escape(str(hub['transfer_id']))}<br>"
            f"<b>Capacidad diaria:</b> {int(hub['daily_capacity_count'])} operaciones<br>"
            f"<b>Costo de apertura:</b> {formato_clp(hub['fixed_cost'])}"
        )
        folium.Marker(
            [float(hub["lat"]), float(hub["lon"])],
            icon=icono_hub(), tooltip=folium.Tooltip(tooltip, sticky=True),
        ).add_to(capa_hubs)

    capa_nodos.add_to(fmap)
    capa_bases.add_to(fmap)
    capa_hubs.add_to(fmap)
    folium.LayerControl(collapsed=False, position="topright").add_to(fmap)
    Fullscreen(position="topleft", title="Pantalla completa").add_to(fmap)

    fmap.fit_bounds(
        [[min(lat for lat, _ in puntos), min(lon for _, lon in puntos)],
         [max(lat for lat, _ in puntos), max(lon for _, lon in puntos)]],
        padding=(25, 25),
    )

    n_semanas = (
        solicitudes["week_of_month"].nunique()
        if "week_of_month" in solicitudes.columns else 0
    )
    fmap.get_root().html.add_child(
        folium.Element(leyenda_html(len(nodos), len(bases), len(hubs)))
    )
    fmap.get_root().html.add_child(
        folium.Element(cabecera_html(tipo, n_hojas, len(solicitudes), int(n_semanas)))
    )

    dir_salida.mkdir(parents=True, exist_ok=True)
    destino = dir_salida / f"red_completa_{tipo}.html"
    fmap.save(str(destino))
    print(
        f"[{tipo.upper()}] {destino} | {len(nodos)} nodos, "
        f"{len(bases)} bases, {len(hubs)} hubs | "
        f"{n_hojas} hojas y {len(solicitudes)} registros"
    )
    return destino


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default="outputs")
    args = parser.parse_args()

    salida = Path(args.dir)
    construir_mapa_global("small", salida)
    construir_mapa_global("big", salida)


if __name__ == "__main__":
    main()
