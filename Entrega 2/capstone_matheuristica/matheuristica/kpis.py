"""Cálculo y exportación de los KPI del informe."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import Config
from .datos import Instancia
from .maestro import Solucion
from .planes import Catalogo


def calcular(inst: Instancia, cat: Catalogo, cfg: Config, sol: Solucion) -> dict:
    total_sol = len(inst.solicitudes)
    n_ext = len(sol.externalizadas)
    dist = sum(r.distancia for r in sol.rutas)
    ot = sum(r.sobretiempo for r in sol.rutas)
    tard = [max(0.0, (t + cat.tramos[tid].serv_delivery) - cat.tramos[tid].due_delivery)
            for r in sol.rutas for (tid, tipo), t in zip(r.paradas, r.tiempos) if tipo == 1]
    tard_pos = sorted(tard)
    transferencias = sum(cat.planes[p].n_ops_hub for p in sol.planes)
    divididas = sum(1 for p in sol.planes if cat.planes[p].tipo == "split")

    ocupacion = []
    for r in sol.rutas:
        ocupacion.append((r.retorno - r.salida) / cfg.horizonte)

    return {
        "costo_total": sol.costo,
        "cota_inferior_pool": sol.cota_inferior,
        "gap_maestro": sol.gap,
        # distancia relativa a la cota LP del pool (no es una cota del problema)
        "gap_vs_cota_lp": ((sol.costo - sol.cota_inferior) / sol.costo) if sol.costo else 0.0,
        **{f"costo_{k}": v for k, v in sol.desglose.items()},
        "solicitudes_totales": total_sol,
        "solicitudes_atendidas": total_sol - n_ext,
        "solicitudes_externalizadas": n_ext,
        "tasa_externalizacion": n_ext / total_sol if total_sol else 0.0,
        "distancia_total_km": dist,
        "sobretiempo_total_min": ot,
        "vehiculo_dias_con_sobretiempo": sum(1 for r in sol.rutas if r.sobretiempo > 1e-6),
        "vehiculo_dias_usados": len(sol.rutas),
        "tardanza_media_min": (sum(tard_pos) / len(tard_pos)) if tard_pos else 0.0,
        "tardanza_p90_min": tard_pos[int(0.9 * (len(tard_pos) - 1))] if tard_pos else 0.0,
        "utilizacion_jornada_media": (sum(ocupacion) / len(ocupacion)) if ocupacion else 0.0,
        "vehiculos_activados": len(sol.vehiculos),
        "vehiculos_disponibles": len(inst.vehiculos),
        "bases_usadas": len(sol.bases),
        "bases_disponibles": len(inst.bases),
        "hubs_habilitados": len(sol.hubs),
        "hubs_disponibles": len(inst.hubs),
        "transferencias": transferencias,
        "solicitudes_divididas": divididas,
    }


def exportar(inst: Instancia, cat: Catalogo, cfg: Config, sol: Solucion,
             kpis: dict, sufijo: str) -> None:
    out = Path(cfg.dir_salida)
    out.mkdir(parents=True, exist_ok=True)

    pd.DataFrame([kpis]).T.rename(columns={0: "valor"}).to_csv(out / f"kpis_{sufijo}.csv")

    filas = []
    for r in sol.rutas:
        for orden, ((tid, tipo), t) in enumerate(zip(r.paradas, r.tiempos)):
            tr = cat.tramos[tid]
            filas.append({
                "dia": r.dia, "vehiculo": r.vehiculo, "base": r.base, "orden": orden,
                "tramo": tid, "plan": tr.plan, "solicitud": tr.solicitud,
                "tipo": "retiro" if tipo == 0 else "entrega",
                "nodo": tr.origen if tipo == 0 else tr.destino,
                "clase": tr.clase, "cantidad": tr.cantidad,
                "inicio_servicio_min": round(t, 1),
                "fin_servicio_min": round(t + (tr.serv_pickup if tipo == 0 else tr.serv_delivery), 1),
                "due_min": tr.due_delivery if tipo == 1 else "",
            })
    pd.DataFrame(filas).to_csv(out / f"rutas_{sufijo}.csv", index=False)

    pd.DataFrame([{
        "dia": r.dia, "vehiculo": r.vehiculo, "base": r.base,
        "n_tramos": len(r.tramos), "distancia_km": round(r.distancia, 2),
        "salida_min": round(r.salida, 1), "retorno_min": round(r.retorno, 1),
        "sobretiempo_min": round(r.sobretiempo, 1), "tardanza_min": round(r.tardanza, 1),
        "costo": round(r.costo, 0),
    } for r in sol.rutas]).to_csv(out / f"vehiculo_dia_{sufijo}.csv", index=False)

    pd.DataFrame([{"vehiculo": k, "base": b} for k, b in sorted(sol.posicionamiento.items())]
                 ).to_csv(out / f"posicionamiento_{sufijo}.csv", index=False)

    pd.DataFrame([{
        "solicitud": p if isinstance(p, str) else p,
        "plan": cat.planes[p].id, "tipo": cat.planes[p].tipo,
        "hub": cat.planes[p].hub or "", "dia": cat.planes[p].dia,
    } for p in sol.planes if cat.planes[p].tipo != "directo"]
    ).to_csv(out / f"coordinacion_{sufijo}.csv", index=False)

    pd.DataFrame([{"solicitud": r} for r in sol.externalizadas]
                 ).to_csv(out / f"externalizadas_{sufijo}.csv", index=False)
