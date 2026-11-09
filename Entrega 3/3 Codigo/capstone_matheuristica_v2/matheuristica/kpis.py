"""Cálculo y exportación de los KPI del informe."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import Config
from .datos import Instancia
from .maestro import Solucion
from .planes import Catalogo


def _uso_capacidad(r, cat, M, cap):
    """(carga media a bordo / capacidad ponderada por km, carga máxima / capacidad,
    fracción de km recorridos vacío)."""
    pos, carga, km, km_carga, km_vacio, pico = r.base, 0, 0.0, 0.0, 0.0, 0
    for tid, tipo in r.paradas:
        tr = cat.tramos[tid]
        nodo = tr.origen if tipo == 0 else tr.destino
        d = M.dist(pos, nodo)
        km += d
        km_carga += d * carga
        if carga == 0:
            km_vacio += d
        carga += tr.cantidad if tipo == 0 else -tr.cantidad
        pico = max(pico, carga)
        pos = nodo
    d = M.dist(pos, r.base)
    km += d
    km_vacio += d
    if km <= 0:
        return 0.0, pico / cap, 0.0
    return km_carga / (km * cap), pico / cap, km_vacio / km


def calcular(inst: Instancia, cat: Catalogo, cfg: Config, sol: Solucion, M=None) -> dict:
    total_sol = len(inst.solicitudes)
    inst_sol = {s.id: s for s in inst.solicitudes}
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

    # [v2] indicadores pedidos en la corrección del Informe 2
    atendidas = total_sol - n_ext
    ext_set = set(sol.externalizadas)
    entregas_tarde = set()
    for r in sol.rutas:
        for (tid, tipo), t in zip(r.paradas, r.tiempos):
            tr = cat.tramos[tid]
            # solo la entrega final (en una transferencia, el tramo B)
            es_final = tr.destino == inst_sol[tr.solicitud].destino
            if tipo == 1 and es_final and t + tr.serv_delivery > tr.due_delivery + 1e-6:
                entregas_tarde.add(tr.solicitud)
    usos = [_uso_capacidad(r, cat, M, inst.vehiculos[r.vehiculo].capacidad)
            for r in sol.rutas] if M is not None else []
    km_directos = (sum(M.dist(s.origen, s.destino) for s in inst.solicitudes
                       if s.id not in ext_set) if M is not None else 0.0)
    n_tramos = [len(r.tramos) for r in sol.rutas]
    por_clase = {}
    for k in sol.vehiculos:
        c = inst.vehiculos[k].clase
        por_clase[c] = por_clase.get(c, 0) + 1
    n_dias = max(1, len(inst.dias))

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
        # ---- v2
        "costo_por_solicitud": sol.costo / total_sol if total_sol else 0.0,
        "km_por_solicitud_atendida": dist / atendidas if atendidas else 0.0,
        "pct_entregas_atrasadas": len(entregas_tarde) / atendidas if atendidas else 0.0,
        "km_directos_atendidas": km_directos,
        "factor_recorrido": dist / km_directos if km_directos else 0.0,
        "uso_capacidad_medio": (sum(u[0] for u in usos) / len(usos)) if usos else 0.0,
        "uso_capacidad_pico": (sum(u[1] for u in usos) / len(usos)) if usos else 0.0,
        "fraccion_km_vacio": (sum(u[2] * r.distancia for u, r in zip(usos, sol.rutas)) / dist)
                             if usos and dist else 0.0,
        "pct_rutas_1_2_tramos": (sum(1 for n in n_tramos if n <= 2) / len(n_tramos))
                                if n_tramos else 0.0,
        "tramos_por_ruta": (sum(n_tramos) / len(n_tramos)) if n_tramos else 0.0,
        "uso_semanal_flota": (len(sol.rutas) / (len(sol.vehiculos) * n_dias))
                             if sol.vehiculos else 0.0,
        "vehiculo_dias_ociosos_pagados": len(sol.vehiculos) * n_dias - len(sol.rutas),
        "veh_VAN_GENERAL": por_clase.get("VAN_GENERAL", 0),
        "veh_VAN_FRIO": por_clase.get("VAN_FRIO", 0),
        "veh_FURGON_FRIO": por_clase.get("FURGON_FRIO", 0),
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
