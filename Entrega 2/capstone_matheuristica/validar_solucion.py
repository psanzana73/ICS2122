"""
Validador independiente de las salidas de la matheurística.

Revisa una solución (los CSV de outputs/) contra los datos originales y los
supuestos del informe (S1 jornada 08:00-17:00, S2 max_transport desde fin de
retiro a fin de entrega, sin reinicio en hub). No usa la matriz de tiempos:
revisa todo lo que se puede revisar sin ella.

Uso:
    python validar_solucion.py --excel data/instancias_small.xlsx --hoja "Instancia 1" \
        --semana 1 --tag small_Instancia1_semana1 [--outputs outputs] \
        [--transversal data/set_datos_transversal.xlsx] [--flota Vehiculos_Small]

Para la corrida de prueba (python main.py --test):
    python validar_solucion.py --excel data/instancias_small.xlsx --hoja "Instancia 1" \
        --semana 1 --dias 1 5 --tag TEST_small_Instancia1_semana1
"""
import argparse, json, sys
import pandas as pd

T_INI, T_FIN, THETA = 480, 1020, 120  # (S1)
INCOMPATIBLES = [{"FARMACO_REFRIGERADO", "INSUMO_GENERAL"}]


def hm(s):
    h, m = str(s).split(":")[:2]
    return int(h) * 60 + int(m)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--excel", required=True)
    ap.add_argument("--hoja", required=True)
    ap.add_argument("--semana", type=int, required=True)
    ap.add_argument("--tag", required=True, help="p.ej. small_Instancia1_semana1")
    ap.add_argument("--outputs", default="outputs")
    ap.add_argument("--transversal", default="data/set_datos_transversal.xlsx")
    ap.add_argument("--flota", default="Vehiculos_Small")
    ap.add_argument("--dias", type=int, nargs="*", default=None,
                    help="solo estos días (p.ej. --dias 1 5 para la corrida --test)")
    a = ap.parse_args()

    I = pd.read_excel(a.excel, sheet_name=a.hoja)
    I = I[I.week_of_month == a.semana].copy()
    if a.dias:
        I = I[I.day.isin(a.dias)].copy()
    for c in ["pickup_window_start", "pickup_window_end", "delivery_window_start", "delivery_due"]:
        I[c + "_m"] = I[c].map(hm)
    I = I.set_index("request_id")
    V = pd.read_excel(a.transversal, sheet_name=a.flota).set_index("vehicle_id")
    C = pd.read_excel(a.transversal, sheet_name="Clases_Solicitud").set_index("cargo_class")

    f = lambda k: f"{a.outputs}/{k}_{a.tag}.csv"
    R = pd.read_csv(f("rutas"))
    VD = pd.read_csv(f("vehiculo_dia"))
    EXT = set(pd.read_csv(f("externalizadas")).solicitud)
    POS = pd.read_csv(f("posicionamiento")).set_index("vehiculo").base
    K = pd.read_csv(f("kpis"), index_col=0)["valor"]

    err, warn = [], []
    E = lambda *x: err.append(" | ".join(map(str, x)))
    W = lambda *x: warn.append(" | ".join(map(str, x)))

    # ---------- cobertura ----------
    R["es_hub"] = R.tramo.str.contains("#T")
    R["pierna"] = R.tramo.str[-1].where(R.es_hub, "")
    ret_origen = R[(R.tipo == "retiro") & ((~R.es_hub) | (R.pierna == "A"))]
    q_serv = ret_origen.groupby("solicitud").cantidad.sum()
    for r in I.index:
        if r in EXT and r in q_serv.index:
            E("atendida y externalizada", r)
        elif r not in EXT and r not in q_serv.index:
            E("ni atendida ni externalizada", r)
        elif r in q_serv.index and q_serv[r] != I.quantity[r]:
            E("cantidad atendida distinta", r, q_serv[r], I.quantity[r])

    # ---------- por unidad de servicio (retiro en origen -> entrega en destino) ----------
    for plan, g in R.groupby("plan"):
        s = g.solicitud.iloc[0]
        q = I.loc[s]
        comp = json.loads(q.compatible_vehicles)
        for v in g.vehiculo.unique():
            if v not in comp:
                E("vehículo incompatible", s, v)
        if g.es_hub.any():
            A = g[g.pierna == "A"]; B = g[g.pierna == "B"]
            if A.vehiculo.nunique() != 1 or B.vehiculo.nunique() != 1:
                E("transferencia mal formada", plan); continue
            if A.vehiculo.iloc[0] == B.vehiculo.iloc[0]:
                E("TRANSFERENCIA con el mismo vehículo en ambas piernas (hub inútil)", plan, A.vehiculo.iloc[0])
            if not q.transferable:
                E("transferencia de clase no transferible", s)
            drop = A[A.tipo == "entrega"].fin_servicio_min.iloc[0]
            pick = B[B.tipo == "retiro"].inicio_servicio_min.iloc[0]
            if pick < drop - 1e-6:
                E("recarga en hub antes de la descarga", plan, pick, drop)
            unidades = [(A[A.tipo == "retiro"], B[B.tipo == "entrega"])]
        else:
            unidades = []
            for tr, gt in g.groupby("tramo"):
                rt, en = gt[gt.tipo == "retiro"], gt[gt.tipo == "entrega"]
                if len(rt) != 1 or len(en) != 1:
                    E("tramo sin par retiro/entrega", tr); continue
                if rt.vehiculo.iloc[0] != en.vehiculo.iloc[0]:
                    E("retiro y entrega de un tramo directo en vehículos distintos", tr)
                unidades.append((rt, en))
            if g.tramo.nunique() > 1:  # división
                n_tr, n_veh = g.tramo.nunique(), g.vehiculo.nunique()
                if not q.split_allowed:
                    E("división de clase no divisible", s)
                if n_veh < n_tr:
                    E("DIVISIÓN con dos partes en el mismo vehículo", s, f"{n_tr} partes en {n_veh} vehículos")
                if n_veh > q.max_split_vehicles:
                    E("división excede max_split_vehicles", s, n_veh)
                qmin = g[g.tipo == "retiro"].cantidad.min()
                if qmin < q.min_split_quantity:
                    E("parte de división bajo min_split_quantity", s, qmin)
        for rt, en in unidades:
            a0, a1 = rt.inicio_servicio_min.iloc[0], rt.fin_servicio_min.iloc[0]
            b0, b1 = en.inicio_servicio_min.iloc[0], en.fin_servicio_min.iloc[0]
            if rt.nodo.iloc[0] != q.origin_id: E("nodo de retiro distinto", plan)
            if en.nodo.iloc[0] != q.destination_id: E("nodo de entrega distinto", plan)
            if rt.dia.iloc[0] != q.day: E("día distinto", plan)
            if not (q.pickup_window_start_m - 1e-6 <= a0 <= q.pickup_window_end_m + 1e-6):
                E("ventana de retiro", plan, a0, (q.pickup_window_start_m, q.pickup_window_end_m))
            if b0 < q.delivery_window_start_m - 1e-6:
                E("entrega antes de apertura", plan, b0, q.delivery_window_start_m)
            late = b0 - q.delivery_due_m
            if late > 1e-6 and not q.late_allowed:
                E("tardanza en clase que no la permite", plan, round(late, 1))
            if b1 - a1 > q.max_transport_min + 1e-6:  # (S2)
                E("max_transport (S2)", plan, round(b1 - a1, 1), q.max_transport_min)

    # ---------- por ruta ----------
    for (d, v), g in R.groupby(["dia", "vehiculo"]):
        g = g.sort_values("orden")
        load, abordo, fin_prev = 0, {}, None
        if v not in POS.index:
            E("vehículo con ruta pero no posicionado", v)
        elif g.base.iloc[0] != POS[v]:
            E("ruta sale de una base distinta a la semanal", d, v)
        for _, x in g.iterrows():
            if fin_prev is not None and x.inicio_servicio_min < fin_prev - 1e-6:
                E("servicios solapados", d, v, x.orden)
            fin_prev = x.fin_servicio_min
            if x.tipo == "retiro":
                load += x.cantidad; abordo[x.tramo] = x.clase
            else:
                load -= x.cantidad; abordo.pop(x.tramo, None)
            if load > V.capacity[v]:
                E("capacidad", d, v, load, V.capacity[v])
            for par in INCOMPATIBLES:
                if par <= set(abordo.values()):
                    E("clases incompatibles a bordo", d, v, x.orden)

    # ---------- jornada (S1) ----------
    VD["ot_S1"] = (VD.retorno_min - T_FIN).clip(lower=0)
    VD["costo_ot_S1"] = VD.ot_S1 * VD.vehiculo.map(V.overtime_cost_per_min)
    if (VD.salida_min < T_INI - 1e-6).any():
        E("salidas antes de las 08:00", int((VD.salida_min < T_INI - 1e-6).sum()))
    if (VD.ot_S1 > THETA + 1e-6).any():
        E("sobretiempo > Θ=120", int((VD.ot_S1 > THETA).sum()))
    mal = VD[(VD.ot_S1 > 1e-6) & (VD.sobretiempo_min + 1e-6 < VD.ot_S1)]
    if len(mal):
        E(f"SOBRETIEMPO SUBESTIMADO: {len(mal)} vehículo-días vuelven después de las 17:00 y el "
          f"código reporta {VD.sobretiempo_min.sum():.1f} min en vez de {VD.ot_S1.sum():.1f} min "
          f"(${VD.costo_ot_S1.sum():,.0f} en vez de ${K.get('costo_sobretiempo', 0):,.0f})")

    # ---------- coherencia económica ----------
    usados = set(zip(VD.dia, VD.vehiculo))
    for r in sorted(EXT):
        q = I.loc[r]
        comp = json.loads(q.compatible_vehicles)
        ociosos = [v for v in POS.index if v in comp and (q.day, v) not in usados]
        # capacidad: un vehículo ocioso que no puede llevar la carga no cuenta
        # (D1_R20: q=46 no divisible vs VAN_GENERAL de capacidad 30)
        caps = sorted((V.capacity[v] for v in ociosos), reverse=True)
        puede = (caps and caps[0] >= q.quantity) or (
            q.split_allowed and sum(caps[:int(q.max_split_vehicles)]) >= q.quantity)
        if ociosos and puede:
            W("externalizada teniendo vehículos YA PAGADOS ociosos ese día", r, f"día {q.day}",
              q.cargo_class, f"q={q.quantity}", f"penalización {C.externalization_penalty[q.cargo_class]:,}",
              ",".join(ociosos))

    # ---------- resumen ----------
    costo_rep = K["costo_total"]
    costo_S1 = costo_rep - K.get("costo_sobretiempo", 0) + VD.costo_ot_S1.sum()
    print("=" * 78)
    print(f"Validación {a.tag}")
    print("=" * 78)
    print(f"costo reportado ........ {costo_rep:14,.0f}")
    print(f"costo con jornada S1 ... {costo_S1:14,.0f}")
    print(f"externalizadas ......... {len(EXT):14d}  ({len(EXT)/len(I):.1%})")
    print(f"gap maestro ............ {K.get('gap_maestro', float('nan')):14.2%}")
    print(f"vehículo-días usados / pagados: {len(VD)} / {len(POS)*I.day.nunique()}")
    print(f"\nERRORES ({len(err)})")
    for e in err: print("  x", e)
    print(f"\nALERTAS DE COHERENCIA ({len(warn)})")
    for w in warn: print("  !", w)
    sys.exit(1 if err else 0)


if __name__ == "__main__":
    main()
