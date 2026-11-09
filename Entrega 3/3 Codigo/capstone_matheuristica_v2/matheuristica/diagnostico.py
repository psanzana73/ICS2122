"""Diagnóstico de factibilidad estructural previo a optimizar.

Responde, antes de correr nada, la pregunta del objetivo específico 2:
¿qué solicitudes son imposibles de atender y por qué? Separa las que
la red *no puede* servir (y por lo tanto se externalizan sí o sí, en
cualquier solución) de las que sí podría servir y se externalizan por
decisión económica del maestro.

El número que entrega es una cota inferior a la externalización y es la
referencia honesta contra la cual leer la tasa de externalización final.
"""

from __future__ import annotations

from collections import Counter

from .config import Config
from .datos import Instancia
from .matriz import Matriz
from .planes import Catalogo, capacidad_maxima
from .ruta import Evaluador


MOTIVOS = {
    "cantidad_excede_capacidad":
        "la cantidad supera la capacidad de todo vehículo compatible (requiere división)",
    "max_transport_insuficiente":
        "el plazo máximo de traslado es menor que viaje + tiempos de atención",
    "due_inalcanzable":
        "el compromiso de entrega no se alcanza ni saliendo al abrir la ventana de retiro",
    "no_cabe_en_la_jornada":
        "base -> origen -> destino -> base no cabe en la jornada + sobretiempo",
}


def analizar(inst: Instancia, M: Matriz, cfg: Config, cat: Catalogo) -> dict:
    ev = Evaluador(inst, M, cfg, cat)
    motivos: Counter = Counter()
    detalle: list[dict] = []
    rescatables_por_division = 0

    for s in inst.solicitudes:
        tid = f"{s.id}#D"
        factible_directo = any(
            ev.evaluar([(tid, 0), (tid, 1)], v, b, s.dia)
            for v in s.vehiculos for b in inst.bases
        )
        if factible_directo:
            continue

        capmax = capacidad_maxima(s, inst)
        t_od = M.tiempo(s.origen, s.destino)
        if s.cantidad > capmax:
            motivo = "cantidad_excede_capacidad"
            if any(cat.planes[p].tipo == "split" for p in cat.por_solicitud.get(s.id, [])):
                rescatables_por_division += 1
        elif s.serv_pickup + t_od + s.serv_delivery > s.max_transport:
            motivo = "max_transport_insuficiente"
        elif (s.ini_pickup + s.serv_pickup + t_od + s.serv_delivery
              > s.due_delivery + (cfg.tardanza_max if s.tardanza_ok else 0)):
            motivo = "due_inalcanzable"
        else:
            motivo = "no_cabe_en_la_jornada"

        motivos[motivo] += 1
        detalle.append({
            "solicitud": s.id, "dia": s.dia, "clase": s.clase, "motivo": motivo,
            "cantidad": s.cantidad, "capacidad_max_compatible": capmax,
            "viaje_min": round(t_od, 1), "max_transport": s.max_transport,
        })

    irrecuperables = sum(v for k, v in motivos.items() if k != "cantidad_excede_capacidad")
    return {
        "motivos": dict(motivos),
        "detalle": detalle,
        "infactibles_directo": sum(motivos.values()),
        "rescatables_por_division": rescatables_por_division,
        "externalizacion_forzosa": irrecuperables,
        "cota_inferior_tasa_externalizacion":
            irrecuperables / len(inst.solicitudes) if inst.solicitudes else 0.0,
    }


def imprimir(d: dict) -> None:
    print(f"[diagnóstico] {d['infactibles_directo']} solicitudes no son atendibles "
          f"de forma directa:")
    for motivo, n in sorted(d["motivos"].items(), key=lambda kv: -kv[1]):
        print(f"    {n:4d}  {MOTIVOS.get(motivo, motivo)}")
    print(f"    -> {d['rescatables_por_division']} se recuperan con división")
    print(f"    -> {d['externalizacion_forzosa']} son externalización forzosa "
          f"({100*d['cota_inferior_tasa_externalizacion']:.1f}% de la demanda): "
          f"cota inferior de la tasa de externalización de CUALQUIER solución")
