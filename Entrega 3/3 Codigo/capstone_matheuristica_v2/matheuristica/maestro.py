"""Problema maestro semanal en Gurobi: particionamiento de conjuntos con
decisiones de diseño (flota, posicionamiento en bases, apertura de hubs).

    min  sum f_k y_k + sum g_b u_b + sum F_p h_p
         + sum pi_r e_r + sum gamma_o xi_o + sum c_rho lambda_rho

    s.a. (m1)  sum_o xi_o + e_r = 1                        para cada solicitud
         (m2)  sum_rho a_{rho,l} lambda_rho = sum_{o: l in o} xi_o   cada tramo
         (m3)  sum_{b,rho in Omega_kbd} lambda_rho <= y_k           cada (k,d)
         (m4)  sum_{rho in Omega_kbd} lambda_rho <= z_kb            cada (k,b,d)
         (m5)  sum_b z_kb = y_k ; z_kb <= u_b ; sum_k z_kb <= kappa_b u_b
         (m6)  xi_o <= h_p
         (m7)  capacidad diaria del hub (operaciones y cantidad)

La relajación lineal entrega la cota inferior sobre el pool y los precios
duales que usa el subproblema de pricing (heuristica.pricing_dia):
  alpha_r (m1), pi_l (m2), mu_kd (m3) y nu_kbd (m4).
Costo reducido de una ruta rho de k desde b el día d:
  c_rho - sum_{l in rho} pi_l - mu_kd - nu_kbd.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import gurobipy as gp
from gurobipy import GRB

from .config import Config
from .datos import Instancia
from .planes import Catalogo
from .ruta import Ruta


@dataclass
class Duales:
    """Precios duales de la relajación lineal del maestro."""
    pi: dict = field(default_factory=dict)       # tramo -> dual de (m2)
    alpha: dict = field(default_factory=dict)    # solicitud -> dual de (m1)
    mu: dict = field(default_factory=dict)       # (k, d) -> dual de (m3), <= 0
    nu: dict = field(default_factory=dict)       # (k, b, d) -> dual de (m4), <= 0
    cat: "Catalogo | None" = None

    def precio(self, tid: str) -> float:
        """Precio del tramo. Si el tramo no tiene restricción (m2) en el LP
        (ninguna columna lo cubre todavía), se estima desde el dual de la
        solicitud: lo que vale atender r, menos el handling del plan, repartido
        entre los tramos del plan en proporción a su cantidad."""
        if tid in self.pi:
            return self.pi[tid]
        if self.cat is None or tid not in self.cat.tramos:
            return 0.0
        tr = self.cat.tramos[tid]
        a = self.alpha.get(tr.solicitud)
        if a is None:
            return 0.0
        pl = self.cat.planes[tr.plan]
        valor = a - pl.costo_handling * pl.n_ops_hub
        total = sum(self.cat.tramos[t].cantidad for t in pl.tramos) or 1
        return max(0.0, valor * tr.cantidad / total)


@dataclass
class Solucion:
    costo: float
    cota_inferior: float
    gap: float
    rutas: list[Ruta]
    planes: list[str]
    externalizadas: list[str]
    vehiculos: list[str]
    posicionamiento: dict[str, str]
    bases: list[str]
    hubs: list[str]
    duales: dict[str, float] = field(default_factory=dict)
    desglose: dict[str, float] = field(default_factory=dict)
    rondas_cg: int = 0
    columnas_cg: int = 0


def _modelo(inst: Instancia, cat: Catalogo, cfg: Config, columnas: list[Ruta],
            planes_activos: set[str] | None, relajado: bool,
            inicio: "Solucion | None" = None):
    m = gp.Model("maestro_semanal")
    m.Params.OutputFlag = 1 if cfg.log_gurobi else 0
    m.Params.MIPGap = cfg.mip_gap
    if cfg.work_limit_maestro:
        m.Params.WorkLimit = cfg.work_limit_maestro     # determinista
    else:
        m.Params.TimeLimit = cfg.time_limit_maestro
    if cfg.hilos_gurobi:
        m.Params.Threads = cfg.hilos_gurobi
    m.Params.Seed = cfg.semilla % 2_000_000_000

    tipo = GRB.CONTINUOUS if relajado else GRB.BINARY
    ub = 1.0

    planes = {p: pl for p, pl in cat.planes.items()
              if planes_activos is None or p in planes_activos}

    # tramos que efectivamente alguna columna puede cubrir
    cubiertos = set()
    for r in columnas:
        cubiertos |= r.tramos
    # un plan solo es utilizable si TODOS sus tramos son cubribles
    planes = {p: pl for p, pl in planes.items()
              if all(t in cubiertos for t in pl.tramos)}

    lam = {i: m.addVar(vtype=tipo, ub=ub, obj=r.costo, name=f"lam[{i}]")
           for i, r in enumerate(columnas)}
    xi = {p: m.addVar(vtype=tipo, ub=ub,
                      obj=pl.costo_handling * pl.n_ops_hub, name=f"xi[{p}]")
          for p, pl in planes.items()}
    e = {s.id: m.addVar(vtype=tipo, ub=ub, obj=s.penal_externalizacion, name=f"e[{s.id}]")
         for s in inst.solicitudes}
    y = {k: m.addVar(vtype=tipo, ub=ub, obj=v.costo_fijo, name=f"y[{k}]")
         for k, v in inst.vehiculos.items()}
    z = {(k, b): m.addVar(vtype=tipo, ub=ub, name=f"z[{k},{b}]")
         for k in inst.vehiculos for b in inst.bases}
    u = {b: m.addVar(vtype=tipo, ub=ub, obj=bb.costo_fijo, name=f"u[{b}]")
         for b, bb in inst.bases.items()}
    h = {p: m.addVar(vtype=tipo, ub=ub, obj=hh.costo_fijo, name=f"h[{p}]")
         for p, hh in inst.hubs.items()}
    m.ModelSense = GRB.MINIMIZE

    # --- (m1) cada solicitud: un plan o externalización -------------------
    por_sol: dict[str, list[str]] = {}
    for p, pl in planes.items():
        por_sol.setdefault(pl.solicitud, []).append(p)
    restr_m1 = {}
    for s in inst.solicitudes:
        restr_m1[s.id] = m.addConstr(
            gp.quicksum(xi[p] for p in por_sol.get(s.id, [])) + e[s.id] == 1,
            name=f"m1[{s.id}]")

    # --- (m2) cobertura de tramos ----------------------------------------
    cols_por_tramo: dict[str, list[int]] = {}
    for i, r in enumerate(columnas):
        for t in r.tramos:
            cols_por_tramo.setdefault(t, []).append(i)
    planes_por_tramo: dict[str, list[str]] = {}
    for p, pl in planes.items():
        for t in pl.tramos:
            planes_por_tramo.setdefault(t, []).append(p)

    restr_m2 = {}
    for t in set(cols_por_tramo) | set(planes_por_tramo):
        izq = gp.quicksum(lam[i] for i in cols_por_tramo.get(t, []))
        der = gp.quicksum(xi[p] for p in planes_por_tramo.get(t, []))
        restr_m2[t] = m.addConstr(izq == der, name=f"m2[{t}]")

    # --- (m3)/(m4) una ruta por vehículo y día, desde su base -------------
    por_kd: dict[tuple, list[int]] = {}
    por_kbd: dict[tuple, list[int]] = {}
    for i, r in enumerate(columnas):
        por_kd.setdefault((r.vehiculo, r.dia), []).append(i)
        por_kbd.setdefault((r.vehiculo, r.base, r.dia), []).append(i)
    restr_m3, restr_m4 = {}, {}
    for (k, d), idxs in por_kd.items():
        restr_m3[k, d] = m.addConstr(gp.quicksum(lam[i] for i in idxs) <= y[k],
                                     name=f"m3[{k},{d}]")
    for (k, b, d), idxs in por_kbd.items():
        restr_m4[k, b, d] = m.addConstr(gp.quicksum(lam[i] for i in idxs) <= z[k, b],
                                        name=f"m4[{k},{b},{d}]")

    # --- (m5) diseño semanal ---------------------------------------------
    for k in inst.vehiculos:
        m.addConstr(gp.quicksum(z[k, b] for b in inst.bases) == y[k], name=f"m5a[{k}]")
    for b, bb in inst.bases.items():
        for k in inst.vehiculos:
            m.addConstr(z[k, b] <= u[b], name=f"m5b[{k},{b}]")
        m.addConstr(gp.quicksum(z[k, b] for k in inst.vehiculos) <= bb.capacidad * u[b],
                    name=f"m5c[{b}]")

    # --- (m6)/(m7) hubs ---------------------------------------------------
    for p, pl in planes.items():
        if pl.hub:
            m.addConstr(xi[p] <= h[pl.hub], name=f"m6[{p}]")
    uso: dict[tuple, list[str]] = {}
    for p, pl in planes.items():
        if pl.hub:
            uso.setdefault((pl.hub, pl.dia), []).append(p)
    for (hub, d), ps in uso.items():
        hh = inst.hubs[hub]
        m.addConstr(gp.quicksum(cat.planes[p].n_ops_hub * xi[p] for p in ps)
                    <= hh.cap_diaria_ops * h[hub], name=f"m7a[{hub},{d}]")
        m.addConstr(gp.quicksum(cat.planes[p].cantidad_hub * xi[p] for p in ps)
                    <= hh.cap_diaria_cantidad * h[hub], name=f"m7b[{hub},{d}]")

    # --- MIP start: la mejor solución conocida ----------------------------
    # [fix] Sin arranque el maestro (7.000+ columnas) se cortaba por tiempo con
    # gap ~27 %. Con la incumbente como punto de partida el costo nunca empeora
    # entre iteraciones y Gurobi parte con una cota superior buena.
    if inicio is not None and not relajado:
        claves = {(r.vehiculo, r.base, r.dia, r.tramos) for r in inicio.rutas}
        for i, r in enumerate(columnas):
            lam[i].Start = 1.0 if (r.vehiculo, r.base, r.dia, r.tramos) in claves else 0.0
        pl_ini = set(inicio.planes)
        for p, var in xi.items():
            var.Start = 1.0 if p in pl_ini else 0.0
        ext_ini = set(inicio.externalizadas)
        for r_id, var in e.items():
            var.Start = 1.0 if r_id in ext_ini else 0.0
        for k, var in y.items():
            var.Start = 1.0 if k in inicio.posicionamiento else 0.0
        for (k, b), var in z.items():
            var.Start = 1.0 if inicio.posicionamiento.get(k) == b else 0.0
        bases_ini = set(inicio.posicionamiento.values())
        for b, var in u.items():
            var.Start = 1.0 if b in bases_ini else 0.0
        hubs_ini = {cat.planes[p].hub for p in pl_ini if cat.planes[p].hub}
        for p, var in h.items():
            var.Start = 1.0 if p in hubs_ini else 0.0

    m.update()
    return m, dict(lam=lam, xi=xi, e=e, y=y, z=z, u=u, h=h, m1=restr_m1, m2=restr_m2,
                   m3=restr_m3, m4=restr_m4, planes=planes)


class LicenciaInsuficiente(RuntimeError):
    pass


def _optimizar(modelo):
    try:
        modelo.optimize()
    except gp.GurobiError as err:
        if "size-limited" in str(err).lower():
            raise LicenciaInsuficiente(
                f"El maestro tiene {modelo.NumVars} variables y {modelo.NumConstrs} "
                "restricciones, por encima del límite de la licencia gratuita de "
                "gurobipy (2000/2000). Usá la licencia académica, o bajá el pool con "
                "--max-columnas / --arranques."
            ) from err
        raise


def armar_solucion(inst: Instancia, cat: Catalogo, rutas: list[Ruta], planes: list[str],
                   externalizadas: list[str], vehiculos: list[str],
                   posicionamiento: dict[str, str], bases: list[str], hubs: list[str],
                   cota: float, gap: float, duales: dict | None = None) -> Solucion:
    """Arma una Solucion y recalcula su costo desde cero (lo usan el maestro y
    la post-optimización por inserción, para que ambos midan igual)."""
    # solo se pagan vehículos y bases que efectivamente se usan en alguna ruta
    usados = {r.vehiculo for r in rutas}
    vehiculos = [k for k in vehiculos if k in usados]
    posicionamiento = {k: b for k, b in posicionamiento.items() if k in usados}
    bases = sorted(set(posicionamiento.values()))
    penal = {s.id: s.penal_externalizacion for s in inst.solicitudes}
    desglose = {
        "fijo_vehiculos": sum(inst.vehiculos[k].costo_fijo for k in vehiculos),
        "fijo_bases": sum(inst.bases[b].costo_fijo for b in bases),
        "fijo_hubs": sum(inst.hubs[p].costo_fijo for p in hubs),
        "km": sum(r.distancia * inst.vehiculos[r.vehiculo].costo_km for r in rutas),
        "sobretiempo": sum(r.sobretiempo * inst.vehiculos[r.vehiculo].costo_sobretiempo
                           for r in rutas),
        "tardanza": sum(sum(max(0.0, (t + cat.tramos[tid].serv_delivery)
                                - cat.tramos[tid].due_delivery) * cat.tramos[tid].penal_tardanza
                            for (tid, tipo), t in zip(r.paradas, r.tiempos) if tipo == 1)
                        for r in rutas),
        "handling_hubs": sum(cat.planes[p].costo_handling * cat.planes[p].n_ops_hub
                             for p in planes),
        "externalizacion": sum(penal[r] for r in externalizadas),
    }
    return Solucion(costo=sum(desglose.values()), cota_inferior=cota, gap=gap,
                    rutas=list(rutas), planes=list(planes),
                    externalizadas=list(externalizadas), vehiculos=list(vehiculos),
                    posicionamiento=dict(posicionamiento), bases=bases,
                    hubs=list(hubs), duales=duales or {}, desglose=desglose)


def relajacion(inst: Instancia, cat: Catalogo, cfg: Config, columnas: list[Ruta],
               planes_activos: set[str] | None = None):
    """Relajación lineal del maestro sobre el pool: (cota, Duales, z fraccional)."""
    ml, vl = _modelo(inst, cat, cfg, columnas, planes_activos, relajado=True)
    _optimizar(ml)
    duales, cota, zfrac = Duales(cat=cat), 0.0, {}
    if ml.Status == GRB.OPTIMAL:
        cota = ml.ObjVal
        duales.pi = {t: c.Pi for t, c in vl["m2"].items()}
        duales.alpha = {r: c.Pi for r, c in vl["m1"].items()}
        duales.mu = {kd: c.Pi for kd, c in vl["m3"].items()}
        duales.nu = {kbd: c.Pi for kbd, c in vl["m4"].items()}
        zfrac = {kb: v.X for kb, v in vl["z"].items() if v.X > 1e-6}
    ml.dispose()
    return cota, duales, zfrac


def resolver(inst: Instancia, cat: Catalogo, cfg: Config, columnas: list[Ruta],
             planes_activos: set[str] | None = None,
             inicio: Solucion | None = None, lp=None) -> Solucion:
    # --- relajación lineal: cota inferior + precios duales ----------------
    if lp is None:
        lp = relajacion(inst, cat, cfg, columnas, planes_activos)
    cota, duales_lp, _ = lp
    duales = duales_lp.pi

    # --- maestro entero ---------------------------------------------------
    m, v = _modelo(inst, cat, cfg, columnas, planes_activos, relajado=False, inicio=inicio)
    _optimizar(m)
    if m.SolCount == 0:
        raise RuntimeError("El maestro no encontró solución factible. "
                           "Revisá que el pool cubra todos los tramos de algún plan.")

    lam, xi, e, y, z, u, h = (v["lam"], v["xi"], v["e"], v["y"], v["z"], v["u"], v["h"])
    sel = [columnas[i] for i, var in lam.items() if var.X > 0.5]
    planes_sel = [p for p, var in xi.items() if var.X > 0.5]
    ext = [r for r, var in e.items() if var.X > 0.5]
    vehs = [k for k, var in y.items() if var.X > 0.5]
    posic = {k: b for (k, b), var in z.items() if var.X > 0.5}
    bases = [b for b, var in u.items() if var.X > 0.5]
    hubs = [p for p, var in h.items() if var.X > 0.5]

    gap = m.MIPGap if m.SolCount else float("nan")
    m.dispose()
    return armar_solucion(inst, cat, sel, planes_sel, ext, vehs, posic, bases, hubs,
                          cota=cota, gap=gap, duales=duales)
