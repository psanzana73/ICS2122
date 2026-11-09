"""Escenarios para el análisis de sensibilidad ("¿qué pasaría si...?").

Cada escenario modifica la instancia (o la matriz de tiempos) ANTES de
optimizar, con una semilla fija para que sea reproducible. Se usan igual en
la matheurística (main.py --escenario X) y en el caso base
(caso_base_2.py --escenario X), así la comparación es justa.

Nombres:  base | demanda+20 | demanda-20 | flota-25 | congestion30 | congestion50
          jornada7 | penal_x2 | penal_x05 | bases_fijo_x2 | sin_talagante
"""

from __future__ import annotations

import random
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
}


def aplicar(nombre: str | None, inst, cfg, semilla: int = 7) -> None:
    """Modifica `inst` y `cfg` en el lugar."""
    if not nombre or nombre == "base":
        return
    if nombre not in DESCRIPCION:
        raise ValueError(f"escenario desconocido: {nombre}. Opciones: {list(DESCRIPCION)}")
    rng = random.Random(semilla)

    if nombre == "demanda+20":
        nuevas = []
        for d in inst.dias:
            del_dia = [s for s in inst.solicitudes if s.dia == d]
            for s in rng.sample(del_dia, round(0.2 * len(del_dia))):
                nuevas.append(replace(s, id=s.id + "_c"))
        inst.solicitudes = inst.solicitudes + nuevas
    elif nombre == "demanda-20":
        quitar = set(s.id for s in rng.sample(inst.solicitudes, round(0.2 * len(inst.solicitudes))))
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
    elif nombre == "jornada7":
        cfg.jornada_inicio = 7 * 60
    elif nombre in ("penal_x2", "penal_x05"):
        f = 2.0 if nombre == "penal_x2" else 0.5
        inst.solicitudes = [replace(s, penal_externalizacion=s.penal_externalizacion * f)
                            for s in inst.solicitudes]
        inst.clases = {c: replace(cl, penal_externalizacion=cl.penal_externalizacion * f)
                       for c, cl in inst.clases.items()}
    elif nombre == "bases_fijo_x2":
        inst.bases = {b: replace(bb, costo_fijo=2 * bb.costo_fijo) for b, bb in inst.bases.items()}
    elif nombre == "sin_talagante":
        inst.bases = {b: bb for b, bb in inst.bases.items() if b != "B_TALAGANTE"}
    # congestión: se aplica sobre la matriz (ver aplicar_matriz)


def aplicar_matriz(nombre: str | None, M) -> None:
    if nombre == "congestion30":
        M.escalar_tiempos(1.30)
    elif nombre == "congestion50":
        M.escalar_tiempos(1.50)
