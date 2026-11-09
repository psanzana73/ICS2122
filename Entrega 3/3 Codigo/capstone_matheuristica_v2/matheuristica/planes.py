"""Planes de servicio y tramos (legs).

Un *plan* es una forma completa de atender una solicitud:
  - directo            : 1 tramo, origen -> destino.
  - transferencia      : 2 tramos sincronizados por un hub y un instante gamma.
  - división (split)   : k tramos directos con cantidades que suman q_r.

Un *tramo* es un par recogida-entrega elemental que un solo vehículo debe
servir completo. Esta indirección es lo que permite que el maestro sea un
particionamiento de conjuntos puro: la sincronización temporal queda congelada
dentro del plan (ver Proposición 2 del informe).

Sobre `max_transport` en una transferencia: el plan compromete una ventana de
retiro [pi_lo, pi_lo + W]. Como el fin real del retiro es >= pi_lo + s+, exigir
que la entrega termine antes de `pi_lo + s+ + M_r` es condición *suficiente*
para respetar el plazo extremo a extremo (que, por indicación del profesor, no
se reinicia al pasar por el hub).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import Config
from .datos import Instancia, Solicitud
from .matriz import Matriz


@dataclass(frozen=True)
class Tramo:
    id: str
    plan: str
    solicitud: str
    dia: int
    clase: str
    cantidad: int
    origen: str
    destino: str
    ini_pickup: int          # ventana de inicio del servicio de retiro
    fin_pickup: int
    ini_delivery: int        # no se puede empezar a entregar antes
    due_delivery: int        # compromiso para el FIN del servicio de entrega
    serv_pickup: int
    serv_delivery: int
    max_transport: int | None      # cota relativa (fin entrega - fin retiro)
    tope_fin_delivery: int | None  # cota absoluta (tramo B de una transferencia)
    tardanza_ok: bool
    penal_tardanza: float
    vehiculos: frozenset[str]


@dataclass(frozen=True)
class Plan:
    id: str
    solicitud: str
    dia: int
    tipo: str                 # "directo" | "transferencia" | "split"
    tramos: tuple[str, ...]
    hub: str | None
    n_ops_hub: int
    cantidad_hub: float
    costo_handling: float


@dataclass
class Catalogo:
    planes: dict[str, Plan] = field(default_factory=dict)
    tramos: dict[str, Tramo] = field(default_factory=dict)
    por_solicitud: dict[str, list[str]] = field(default_factory=dict)

    def agregar(self, plan: Plan, tramos: list[Tramo]) -> None:
        if plan.id in self.planes:
            return
        self.planes[plan.id] = plan
        for t in tramos:
            self.tramos[t.id] = t
        self.por_solicitud.setdefault(plan.solicitud, []).append(plan.id)

    def tramos_de(self, plan_id: str) -> list[Tramo]:
        return [self.tramos[t] for t in self.planes[plan_id].tramos]


# --------------------------------------------------------------------------- #
def plan_directo(s: Solicitud) -> tuple[Plan, list[Tramo]]:
    tid = f"{s.id}#D"
    tramo = Tramo(
        id=tid, plan=tid, solicitud=s.id, dia=s.dia, clase=s.clase,
        cantidad=s.cantidad, origen=s.origen, destino=s.destino,
        ini_pickup=s.ini_pickup, fin_pickup=s.fin_pickup,
        ini_delivery=s.ini_delivery, due_delivery=s.due_delivery,
        serv_pickup=s.serv_pickup, serv_delivery=s.serv_delivery,
        max_transport=s.max_transport, tope_fin_delivery=None,
        tardanza_ok=s.tardanza_ok, penal_tardanza=s.penal_tardanza,
        vehiculos=s.vehiculos,
    )
    plan = Plan(id=tid, solicitud=s.id, dia=s.dia, tipo="directo",
                tramos=(tid,), hub=None, n_ops_hub=0, cantidad_hub=0.0,
                costo_handling=0.0)
    return plan, [tramo]


def planes_split(s: Solicitud, cfg: Config) -> list[tuple[Plan, list[Tramo]]]:
    """Divisiones en 2..max_vehiculos partes lo más parejas posible."""
    if not s.divisible or s.max_vehiculos_split < 2:
        return []
    salida = []
    for k in range(2, s.max_vehiculos_split + 1):
        base = s.cantidad // k
        resto = s.cantidad % k
        partes = [base + (1 if i < resto else 0) for i in range(k)]
        if min(partes) < max(1, s.min_cantidad_split):
            continue
        pid = f"{s.id}#S{k}"
        tramos = []
        for i, q in enumerate(partes):
            tramos.append(Tramo(
                id=f"{pid}.{i}", plan=pid, solicitud=s.id, dia=s.dia, clase=s.clase,
                cantidad=q, origen=s.origen, destino=s.destino,
                ini_pickup=s.ini_pickup, fin_pickup=s.fin_pickup,
                ini_delivery=s.ini_delivery, due_delivery=s.due_delivery,
                serv_pickup=s.serv_pickup, serv_delivery=s.serv_delivery,
                max_transport=s.max_transport, tope_fin_delivery=None,
                tardanza_ok=s.tardanza_ok, penal_tardanza=s.penal_tardanza,
                vehiculos=s.vehiculos,
            ))
        salida.append((Plan(id=pid, solicitud=s.id, dia=s.dia, tipo="split",
                            tramos=tuple(t.id for t in tramos), hub=None,
                            n_ops_hub=0, cantidad_hub=0.0, costo_handling=0.0),
                       tramos))
    return salida


def planes_transferencia(s: Solicitud, inst: Instancia, M: Matriz,
                         cfg: Config) -> list[tuple[Plan, list[Tramo]]]:
    """Un plan por (hub candidato, instante de intercambio gamma, ventana de retiro)."""
    if not s.transferible or not inst.hubs:
        return []

    # hubs candidatos: los que menos desvían el par (origen, destino)
    ranking = sorted(
        inst.hubs.values(),
        key=lambda h: M.tiempo(s.origen, h.id) + M.tiempo(h.id, s.destino),
    )[: cfg.max_hubs_por_solicitud]

    salida = []
    for h in ranking:
        t_oh = M.tiempo(s.origen, h.id)
        t_hd = M.tiempo(h.id, s.destino)
        # el intercambio no puede ocurrir antes de que el emisor alcance a llegar
        gamma_min = max(h.apertura + h.serv_drop,
                        s.ini_pickup + s.serv_pickup + t_oh + h.serv_drop)
        # ni tan tarde que el receptor no alcance a entregar dentro de la jornada
        gamma_max = min(h.cierre - h.serv_pick,
                        cfg.fin_duro - (h.serv_pick + t_hd + s.serv_delivery),
                        s.due_delivery + (cfg.tardanza_max if s.tardanza_ok else 0)
                        - (h.serv_pick + t_hd + s.serv_delivery))
        if gamma_max < gamma_min:
            continue

        # se toman a lo más `max_slots_por_hub` instantes repartidos en el rango:
        # más slots dan más flexibilidad pero diluyen la cobertura del pool
        paso = max(1, cfg.paso_slot_hub)
        crudos = list(range(int(gamma_min), int(gamma_max) + 1, paso))
        if not crudos:
            continue
        if len(crudos) > cfg.max_slots_por_hub:
            k = cfg.max_slots_por_hub
            idx = [round(i * (len(crudos) - 1) / (k - 1)) if k > 1 else 0 for i in range(k)]
            crudos = [crudos[i] for i in sorted(set(idx))]

        for g in crudos:
            # ventana de retiro comprometida por el plan
            pi_lo = s.ini_pickup
            pi_hi = min(s.fin_pickup,
                        g - h.serv_drop - t_oh - s.serv_pickup,
                        pi_lo + cfg.ancho_ventana_pickup)
            if pi_hi < pi_lo:
                continue

            pid = f"{s.id}#T:{h.id}:{g}"
            tope = int(pi_lo + s.serv_pickup + s.max_transport)   # cota suficiente
            if tope < g + h.serv_pick + t_hd + s.serv_delivery:
                continue

            tramo_a = Tramo(
                id=f"{pid}.A", plan=pid, solicitud=s.id, dia=s.dia, clase=s.clase,
                cantidad=s.cantidad, origen=s.origen, destino=h.id,
                ini_pickup=pi_lo, fin_pickup=int(pi_hi),
                ini_delivery=h.apertura, due_delivery=g,
                serv_pickup=s.serv_pickup, serv_delivery=h.serv_drop,
                max_transport=None, tope_fin_delivery=g,
                tardanza_ok=False, penal_tardanza=0.0, vehiculos=s.vehiculos,
            )
            tramo_b = Tramo(
                id=f"{pid}.B", plan=pid, solicitud=s.id, dia=s.dia, clase=s.clase,
                cantidad=s.cantidad, origen=h.id, destino=s.destino,
                ini_pickup=g, fin_pickup=int(min(g + cfg.holgura_hub, h.cierre - h.serv_pick)),
                ini_delivery=s.ini_delivery, due_delivery=s.due_delivery,
                serv_pickup=h.serv_pick, serv_delivery=s.serv_delivery,
                max_transport=None, tope_fin_delivery=tope,
                tardanza_ok=s.tardanza_ok, penal_tardanza=s.penal_tardanza,
                vehiculos=s.vehiculos,
            )
            plan = Plan(id=pid, solicitud=s.id, dia=s.dia, tipo="transferencia",
                        tramos=(tramo_a.id, tramo_b.id), hub=h.id, n_ops_hub=1,
                        cantidad_hub=float(s.cantidad),
                        costo_handling=h.costo_handling)
            salida.append((plan, [tramo_a, tramo_b]))
    return salida


def capacidad_maxima(s: Solicitud, inst: Instancia) -> int:
    """Mayor capacidad entre los vehículos compatibles con la solicitud."""
    caps = [inst.vehiculos[v].capacidad for v in s.vehiculos
            if v in inst.vehiculos and s.clase in inst.vehiculos[v].clases_compatibles]
    return max(caps) if caps else 0


def catalogo_inicial(inst: Instancia, cfg: Config) -> tuple[Catalogo, dict[str, str]]:
    """Planes directos + las divisiones *estructuralmente necesarias*.

    Una solicitud cuya cantidad excede la capacidad de todo vehículo compatible
    no puede atenderse de forma directa: su plan de división no es una mejora
    opcional sino la única alternativa a externalizarla, así que entra desde la
    primera iteración en vez de esperar a la fase de reparación.

    Devuelve el catálogo y la selección inicial (un plan por solicitud) que usa
    el GRASP.
    """
    cat = Catalogo()
    seleccion: dict[str, str] = {}
    for s in inst.solicitudes:
        plan, tramos = plan_directo(s)
        cat.agregar(plan, tramos)
        seleccion[s.id] = plan.id
        if s.cantidad > capacidad_maxima(s, inst):
            alternativas = planes_split(s, cfg)
            for p, ts in alternativas:
                cat.agregar(p, ts)
            if alternativas:
                # la división con menos vehículos que sí alcanza
                viables = [p for p, ts in alternativas
                           if max(t.cantidad for t in ts) <= capacidad_maxima(s, inst)]
                seleccion[s.id] = (viables[0].id if viables else alternativas[-1][0].id)
    return cat, seleccion
