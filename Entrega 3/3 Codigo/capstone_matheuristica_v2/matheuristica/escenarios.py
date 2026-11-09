"""Escenarios para el análisis de sensibilidad ("¿qué pasaría si...?").

Cada escenario modifica la instancia (o la matriz de tiempos) ANTES de
optimizar, con una semilla fija para que sea reproducible. Se usan igual en
la matheurística (main.py --escenario X) y en el caso base
(caso_base_2.py --escenario X), así la comparación es justa.

Nombres fijos:  base | flota-25 | jornada7 | penal_x2 | penal_x05 | bases_fijo_x2 | sin_atraso |
                hubs_todas
Paramétricos:   demanda+N / demanda-N (N en %), congestionN (N en %),
                furgon+N (N furgones fríos extra), sin_<base> (cierra esa base,
                p. ej. sin_talagante, sin_macul, sin_san_bernardo),
                base_en_<hub> (abre una base nueva en ese punto, p. ej. base_en_providencia),
                ventanas+N / ventanas-N (ventanas N min más anchas o angostas),
                sin_division, cap_bases+N / cap_bases-N (capacidad de cada base N % mayor o menor)
"""

from __future__ import annotations

import random
import re
from dataclasses import replace

DESCRIPCION = {
    "base": "Datos originales",
    "demanda+20": "20 % más solicitudes (copias de solicitudes del mismo día)",
    "demanda-20": "20 % menos solicitudes (se eliminan al azar)",
    "flota-25": "25 % menos vehículos disponibles de cada clase",
    "congestion30": "Tiempos de viaje 30 % más largos (velocidad media ~47 km/h)",
    "congestion50": "Tiempos de viaje 50 % más largos (velocidad media ~41 km/h)",
    "jornada7": "La jornada parte a las 07:00 en vez de las 08:00 (termina igual a las 17:00)",
    "penal_x2": "Penalización de externalización x2 (valores de la hoja de instancias)",
    "penal_x05": "Penalización de externalización x0,5",
    "bases_fijo_x2": "Costo fijo semanal de las bases x2",
    "sin_talagante": "Se cierra la base de Talagante (la más periférica)",
    "sin_atraso": "Ninguna clase admite atraso",
    "sin_division": "Ninguna solicitud se puede dividir (las que no caben en un vehículo se externalizan)",
    "hubs_todas": "Se ofrecen planes de transferencia a todas las solicitudes transferibles",
}


def describir(nombre: str) -> str:
    if nombre in DESCRIPCION:
        return DESCRIPCION[nombre]
    m = re.fullmatch(r"demanda([+-])(\d+)", nombre)
    if m:
        return f"{m[2]} % {'más' if m[1] == '+' else 'menos'} solicitudes"
    m = re.fullmatch(r"congestion(\d+)", nombre)
    if m:
        return f"Tiempos de viaje {m[1]} % más largos"
    m = re.fullmatch(r"furgon\+(\d+)", nombre)
    if m:
        return f"{m[1]} furgones fríos adicionales disponibles"
    m = re.fullmatch(r"cap_bases([+-])(\d+)", nombre)
    if m:
        return f"Capacidad de cada base {m[2]} % {'mayor' if m[1] == '+' else 'menor'}"
    m = re.fullmatch(r"base_en_([a-z_]+)", nombre)
    if m:
        return f"Se abre una base nueva en {m[1].replace('_', ' ').title()} (8 vehículos, costo fijo medio)"
    m = re.fullmatch(r"ventanas([+-])(\d+)", nombre)
    if m:
        return f"Ventanas de retiro y entrega {m[2]} min más {'anchas' if m[1] == '+' else 'angostas'}"
    m = re.fullmatch(r"sin_([a-z_]+)", nombre)
    if m:
        return f"Se cierra la base {m[1].replace('_', ' ').title()}"
    raise ValueError(f"escenario desconocido: {nombre}")


def aplicar(nombre: str | None, inst, cfg, semilla: int = 7) -> None:
    """Modifica `inst` y `cfg` en el lugar."""
    if not nombre or nombre == "base":
        return
    describir(nombre)                      # valida el nombre
    rng = random.Random(semilla)
    m_dem = re.fullmatch(r"demanda([+-])(\d+)", nombre)
    m_fur = re.fullmatch(r"furgon\+(\d+)", nombre)
    m_sin = re.fullmatch(r"sin_([a-z_]+)", nombre) if nombre not in ("sin_atraso", "sin_division") else None
    m_nueva = re.fullmatch(r"base_en_([a-z_]+)", nombre)
    m_ven = re.fullmatch(r"ventanas([+-])(\d+)", nombre)
    m_cap = re.fullmatch(r"cap_bases([+-])(\d+)", nombre)

    if m_dem and m_dem[1] == "+":
        f = int(m_dem[2]) / 100
        nuevas = []
        for d in inst.dias:
            del_dia = [s for s in inst.solicitudes if s.dia == d]
            for s in rng.sample(del_dia, round(f * len(del_dia))):
                nuevas.append(replace(s, id=s.id + "_c"))
        inst.solicitudes = inst.solicitudes + nuevas
    elif m_dem:
        f = int(m_dem[2]) / 100
        quitar = set(s.id for s in rng.sample(inst.solicitudes, round(f * len(inst.solicitudes))))
        inst.solicitudes = [s for s in inst.solicitudes if s.id not in quitar]
    elif nombre == "flota-25":
        por_clase = {}
        for k, v in sorted(inst.vehiculos.items()):
            por_clase.setdefault(v.clase, []).append(k)
        quedan = set()
        for clase, ks in por_clase.items():
            quedan |= set(ks[: len(ks) - round(0.25 * len(ks))])
        inst.vehiculos = {k: v for k, v in inst.vehiculos.items() if k in quedan}
        inst.solicitudes = [replace(s, vehiculos=frozenset(s.vehiculos & quedan))
                            for s in inst.solicitudes]
    elif m_fur:
        furgones = sorted(k for k, v in inst.vehiculos.items() if v.clase == "FURGON_FRIO")
        molde = inst.vehiculos[furgones[0]]
        nuevos = [f"FURGON_FRIO_X{j + 1:02d}" for j in range(int(m_fur[1]))]
        for k in nuevos:
            inst.vehiculos[k] = replace(molde, id=k)
        fs = set(furgones)
        inst.solicitudes = [replace(s, vehiculos=frozenset(s.vehiculos | set(nuevos)))
                            if s.vehiculos & fs else s for s in inst.solicitudes]
    elif nombre == "sin_division":
        inst.solicitudes = [replace(s, divisible=False) for s in inst.solicitudes]
        inst.clases = {c: replace(cl, divisible=False) for c, cl in inst.clases.items()}
    elif m_nueva:
        h = inst.hubs[hub_de(m_nueva[1], inst)]
        costo = sum(b.costo_fijo for b in inst.bases.values()) / len(inst.bases)
        b = next(iter(inst.bases.values()))
        inst.bases[BASE_NUEVA] = replace(b, id=BASE_NUEVA, lat=h.lat, lon=h.lon, capacidad=8,
                                         costo_fijo=round(costo, -3))
    elif m_cap:
        fac = 1 + int(m_cap[2]) / 100 * (1 if m_cap[1] == "+" else -1)
        inst.bases = {b: replace(bb, capacidad=max(1, round(bb.capacidad * fac)))
                      for b, bb in inst.bases.items()}
    elif m_ven:
        n = int(m_ven[2]) * (1 if m_ven[1] == "+" else -1)
        inst.solicitudes = [replace(s, fin_pickup=max(s.ini_pickup, s.fin_pickup + n),
                                    due_delivery=max(s.ini_delivery, s.due_delivery + n))
                            for s in inst.solicitudes]
    elif nombre == "hubs_todas":
        cfg.hubs_todas = True
    elif nombre == "jornada7":
        cfg.jornada_inicio = 7 * 60
    elif nombre == "sin_atraso":
        inst.solicitudes = [replace(s, tardanza_ok=False) for s in inst.solicitudes]
        inst.clases = {c: replace(cl, tardanza_ok=False) for c, cl in inst.clases.items()}
    elif nombre in ("penal_x2", "penal_x05"):
        f = 2.0 if nombre == "penal_x2" else 0.5
        inst.solicitudes = [replace(s, penal_externalizacion=s.penal_externalizacion * f)
                            for s in inst.solicitudes]
        inst.clases = {c: replace(cl, penal_externalizacion=cl.penal_externalizacion * f)
                       for c, cl in inst.clases.items()}
    elif nombre == "bases_fijo_x2":
        inst.bases = {b: replace(bb, costo_fijo=2 * bb.costo_fijo) for b, bb in inst.bases.items()}
    elif m_sin:
        b = "B_" + m_sin[1].upper()
        if b not in inst.bases:
            raise ValueError(f"base desconocida: {b}. Opciones: {sorted(inst.bases)}")
        inst.bases = {k: v for k, v in inst.bases.items() if k != b}
    # congestión: se aplica sobre la matriz (ver aplicar_matriz)


BASE_NUEVA = "B_NUEVA"


def hub_de(nombre: str, inst) -> str:
    h = "T_" + nombre.upper()
    if h not in inst.hubs:
        raise ValueError(f"punto desconocido: {h}. Opciones: {sorted(inst.hubs)}")
    return h


def aplicar_matriz(nombre: str | None, M) -> None:
    m_nueva = re.fullmatch(r"base_en_([a-z_]+)", nombre or "")
    if m_nueva:
        # la base nueva queda en el mismo nodo que el punto de transferencia
        M.alias(BASE_NUEVA, "T_" + m_nueva[1].upper())
    m = re.fullmatch(r"congestion(\d+)", nombre or "")
    if m:
        M.escalar_tiempos(1 + int(m[1]) / 100)
