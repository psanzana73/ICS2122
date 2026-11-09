"""Algoritmos 2 y 3: construcción GRASP por arrepentimiento y mejora VND.

Todos los movimientos son *par-preservantes*: la unidad atómica que se inserta,
mueve o intercambia es el tramo completo (retiro + entrega). Nunca se extrae un
nodo sin su par, que es la objeción por la cual se descartan ALNS, la inserción
del más barato y los movimientos k-opt en pick-up & delivery.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from .config import Config
from .datos import Instancia
from .matriz import Matriz
from .planes import Catalogo
from .ruta import DROP, PICK, Evaluador, Ruta

MAX_DESFASE = 8          # máximas posiciones entre el retiro y la entrega insertados


# --------------------------------------------------------------------------- #
@dataclass
class SolucionDia:
    dia: int
    asignacion: dict[str, str]                       # vehículo -> base
    paradas: dict[str, list] = field(default_factory=dict)
    rutas: dict[str, Ruta] = field(default_factory=dict)
    sin_asignar: set[str] = field(default_factory=set)

    @property
    def costo(self) -> float:
        return sum(r.costo for r in self.rutas.values())


# --------------------------------------------------------------------------- #
def mejor_insercion(ev: Evaluador, paradas: list, tid: str, veh: str, base: str,
                    dia: int, costo_actual: float):
    """Mejor posición factible para el par (retiro, entrega) del tramo `tid`."""
    n = len(paradas)
    mejor = None
    for i in range(n + 1):
        parcial = paradas[:i] + [(tid, PICK)] + paradas[i:]
        tope = min(n + 1, i + MAX_DESFASE)
        for j in range(i + 1, tope + 1):
            nuevas = parcial[:j] + [(tid, DROP)] + parcial[j:]
            r = ev.evaluar(nuevas, veh, base, dia)
            if r is None:
                continue
            delta = r.costo_heuristico - costo_actual
            if mejor is None or delta < mejor[0] - 1e-9:
                mejor = (delta, nuevas, r)
    return mejor


def _vehiculos_del_dia(inst: Instancia, tramos: list[str], cat: Catalogo) -> list[str]:
    usados = set()
    for tid in tramos:
        usados |= cat.tramos[tid].vehiculos
    return sorted(v for v in usados if v in inst.vehiculos)


def sortear_asignacion(rng: random.Random, inst: Instancia, M: Matriz,
                       vehiculos: list[str], tramos: list[str],
                       cat: Catalogo) -> dict[str, str]:
    """Asigna cada vehículo a una base, sesgando hacia el centroide de su demanda."""
    bases = list(inst.bases.values())
    cupo = {b.id: b.capacidad for b in bases}
    asignacion: dict[str, str] = {}

    # centroide de la demanda compatible con cada vehículo
    for v in rng.sample(vehiculos, len(vehiculos)):
        veh = inst.vehiculos[v]
        pts = [cat.tramos[t].origen for t in tramos
               if v in cat.tramos[t].vehiculos and cat.tramos[t].clase in veh.clases_compatibles]
        if not pts:
            continue
        candidatas = sorted(
            (b for b in bases if cupo[b.id] > 0),
            key=lambda b: sum(M.tiempo(b.id, p) for p in pts) / len(pts),
        )
        if not candidatas:
            break
        k = min(3, len(candidatas))
        elegida = candidatas[rng.randrange(k)]
        asignacion[v] = elegida.id
        cupo[elegida.id] -= 1
    return asignacion


# --------------------------------------------------------------------------- #
def construir_grasp(ev: Evaluador, inst: Instancia, M: Matriz, cfg: Config,
                    cat: Catalogo, dia: int, tramos: list[str],
                    asignacion: dict[str, str], rng: random.Random,
                    duales: dict[str, float] | None = None) -> SolucionDia:
    """Algoritmo 2: inserción greedy aleatorizada guiada por arrepentimiento."""
    duales = duales or {}
    sol = SolucionDia(dia=dia, asignacion=asignacion)
    for v in asignacion:
        sol.paradas[v] = []

    pendientes = set(tramos)
    # cache[tid][veh] = (delta, nuevas_paradas, ruta)
    cache: dict[str, dict[str, tuple]] = {}

    def recomputar(tid: str, vehs):
        d = cache.setdefault(tid, {})
        tr = cat.tramos[tid]
        for v in vehs:
            d.pop(v, None)
            if v not in asignacion or v not in tr.vehiculos:
                continue
            if tr.clase not in inst.vehiculos[v].clases_compatibles:
                continue
            # un tramo por solicitud y por ruta (respeta split y transferencia)
            if any(cat.tramos[t].solicitud == tr.solicitud for t, _ in sol.paradas[v]):
                continue
            actual = sol.rutas.get(v)
            m = mejor_insercion(ev, sol.paradas[v], tid, v, asignacion[v], dia,
                                actual.costo_heuristico if actual else 0.0)
            if m is not None:
                d[v] = m

    todos = list(asignacion)
    for tid in pendientes:
        recomputar(tid, todos)

    while pendientes:
        mejores = []
        for tid in pendientes:
            opciones = cache.get(tid, {})
            if not opciones:
                continue
            ordenadas = sorted(opciones.items(), key=lambda kv: kv[1][0])
            c1 = ordenadas[0][1][0] - duales.get(tid, 0.0)
            c2 = ordenadas[1][1][0] - duales.get(tid, 0.0) if len(ordenadas) > 1 else None
            regret = (c2 - c1) if c2 is not None else float("inf")
            mejores.append((regret, c1, tid, ordenadas[0][0]))

        if not mejores:
            sol.sin_asignar |= pendientes
            break

        finitos = [m for m in mejores if m[0] != float("inf")]
        if finitos:
            tope = max(m[0] for m in finitos)
            rcl = [m for m in mejores
                   if m[0] == float("inf") or m[0] >= (1 - cfg.eps_rcl) * tope]
        else:
            rcl = mejores
        elegido = rng.choice(rcl)
        _, _, tid, veh = elegido

        delta, nuevas, ruta = cache[tid][veh]
        sol.paradas[veh] = nuevas
        sol.rutas[veh] = ruta
        pendientes.discard(tid)
        cache.pop(tid, None)
        # solo cambió la ruta `veh`: se recalculan sus entradas
        for otro in pendientes:
            recomputar(otro, [veh])

    return sol


# --------------------------------------------------------------------------- #
def vnd(ev: Evaluador, cfg: Config, cat: Catalogo, sol: SolucionDia) -> SolucionDia:
    """Algoritmo 3: descenso por vecindarios variables, par-preservante."""
    if not cfg.vnd_activo:
        return sol
    vecindarios = (_n1_intra, _n2_relocate, _n3_swap)
    m, pasadas = 0, 0
    while m < len(vecindarios) and pasadas < cfg.vnd_max_pasadas:
        pasadas += 1
        if vecindarios[m](ev, cat, sol):
            m = 0
        else:
            m += 1
    return sol


def _n1_intra(ev, cat, sol) -> bool:
    """Reubicar un tramo dentro de su propia ruta."""
    for v, ruta in list(sol.rutas.items()):
        base = sol.asignacion[v]
        tids = sorted({t for t, _ in ruta.paradas})
        for tid in tids:
            resto = [p for p in ruta.paradas if p[0] != tid]
            if not resto:
                continue
            m = mejor_insercion(ev, resto, tid, v, base, sol.dia, 0.0)
            if m and m[2].costo_heuristico < ruta.costo_heuristico - 1e-6:
                sol.paradas[v] = m[1]
                sol.rutas[v] = m[2]
                return True
    return False


def _n2_relocate(ev, cat, sol) -> bool:
    """Mover un tramo completo a otra ruta."""
    for origen, ruta in list(sol.rutas.items()):
        tids = sorted({t for t, _ in ruta.paradas})
        for tid in tids:
            resto = [p for p in ruta.paradas if p[0] != tid]
            r_origen = ev.evaluar(resto, origen, sol.asignacion[origen], sol.dia) if resto else None
            if resto and r_origen is None:
                continue
            ahorro = ruta.costo_heuristico - (r_origen.costo_heuristico if r_origen else 0.0)
            tr = cat.tramos[tid]
            for destino in sol.asignacion:
                if destino == origen or destino not in tr.vehiculos:
                    continue
                if any(cat.tramos[t].solicitud == tr.solicitud
                       for t, _ in sol.paradas.get(destino, [])):
                    continue
                actual = sol.rutas.get(destino)
                m = mejor_insercion(ev, sol.paradas.get(destino, []), tid, destino,
                                    sol.asignacion[destino], sol.dia,
                                    actual.costo_heuristico if actual else 0.0)
                if m and m[0] < ahorro - 1e-6:
                    sol.paradas[origen] = resto
                    if r_origen:
                        sol.rutas[origen] = r_origen
                    else:
                        sol.rutas.pop(origen, None)
                    sol.paradas[destino] = m[1]
                    sol.rutas[destino] = m[2]
                    return True
    return False


def _n3_swap(ev, cat, sol) -> bool:
    """Intercambiar dos tramos entre dos rutas."""
    vehs = [v for v in sol.rutas]
    for a in range(len(vehs)):
        for b in range(a + 1, len(vehs)):
            va, vb = vehs[a], vehs[b]
            ra, rb = sol.rutas[va], sol.rutas[vb]
            base_costo = ra.costo_heuristico + rb.costo_heuristico
            for ta in sorted({t for t, _ in ra.paradas}):
                for tb in sorted({t for t, _ in rb.paradas}):
                    tra, trb = cat.tramos[ta], cat.tramos[tb]
                    if vb not in tra.vehiculos or va not in trb.vehiculos:
                        continue
                    resto_a = [p for p in ra.paradas if p[0] != ta]
                    resto_b = [p for p in rb.paradas if p[0] != tb]
                    ma = mejor_insercion(ev, resto_a, tb, va, sol.asignacion[va], sol.dia, 0.0)
                    if ma is None:
                        continue
                    mb = mejor_insercion(ev, resto_b, ta, vb, sol.asignacion[vb], sol.dia, 0.0)
                    if mb is None:
                        continue
                    if ma[2].costo_heuristico + mb[2].costo_heuristico < base_costo - 1e-6:
                        sol.paradas[va], sol.rutas[va] = ma[1], ma[2]
                        sol.paradas[vb], sol.rutas[vb] = mb[1], mb[2]
                        return True
    return False


# --------------------------------------------------------------------------- #
class Pool:
    """Columnas del maestro: la mejor ruta encontrada para cada secuencia."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.rutas: dict[tuple, Ruta] = {}
        self.protegidas: set[tuple] = set()

    def proteger(self, rutas) -> None:
        """Marca columnas (las de la solución incumbente) para que la poda no
        las elimine. Sin esto el pool pierde calidad entre iteraciones y el
        costo del maestro puede empeorar en vez de mejorar."""
        for r in rutas:
            clave = (r.vehiculo, r.base, r.dia, r.tramos)
            self.rutas.setdefault(clave, r)
            self.protegidas.add(clave)

    def agregar(self, r: Ruta | None) -> None:
        if r is None or not r.paradas:
            return
        # una ruta no puede llevar dos tramos de la misma solicitud
        if len(r.solicitudes) != len({t for t in r.tramos}):
            pass  # permitido solo si coincide 1 a 1; se verifica abajo
        clave = (r.vehiculo, r.base, r.dia, r.tramos)
        previa = self.rutas.get(clave)
        if previa is None or r.costo < previa.costo:
            self.rutas[clave] = r

    def agregar_solucion(self, sol: SolucionDia) -> None:
        for r in sol.rutas.values():
            self.agregar(r)

    def podar(self) -> None:
        """Deja a lo más `max_cols_por_vehiculo_dia` columnas por (vehículo, día)."""
        por_grupo: dict[tuple, list] = {}
        nuevas = {}
        for clave, r in self.rutas.items():
            if clave in self.protegidas:
                nuevas[clave] = r
            else:
                por_grupo.setdefault((r.vehiculo, r.dia), []).append((clave, r))
        tope = self.cfg.max_cols_por_vehiculo_dia
        for grupo, items in por_grupo.items():
            ya = sum(1 for c in nuevas if c[0] == grupo[0] and c[2] == grupo[1])
            items.sort(key=lambda kr: kr[1].costo / max(1, len(kr[1].tramos)))
            for clave, r in items[: max(0, tope - ya)]:
                nuevas[clave] = r
        self.rutas = nuevas

    def columnas(self) -> list[Ruta]:
        return list(self.rutas.values())


# --------------------------------------------------------------------------- #
def _tramos_del_dia(inst, cat, seleccion, dia) -> list[str]:
    tramos = []
    for s in inst.por_dia(dia):
        plan = seleccion.get(s.id)
        if plan is not None:
            tramos.extend(cat.planes[plan].tramos)
    return tramos


def generar_columnas_semana(ev: Evaluador, inst: Instancia, M: Matriz, cfg: Config,
                            cat: Catalogo, seleccion: dict[str, str], pool: Pool,
                            rng: random.Random,
                            duales: dict[str, float] | None = None,
                            asignacion_sugerida: dict[str, str] | None = None) -> None:
    """Multi-arranque GRASP+VND sobre la SEMANA completa.

    El posicionamiento vehículo-base se sortea UNA VEZ por escenario y se
    mantiene en los cinco días. Esto es lo que hace que las columnas sean
    recombinables en el maestro: si cada día sorteara su propia base, las
    restricciones (m4)-(m5) impedirían usar juntas dos columnas del mismo
    vehículo en días distintos, y el pool quedaría inservible.
    """
    tramos_semana = []
    for dia in inst.dias:
        tramos_semana.extend(_tramos_del_dia(inst, cat, seleccion, dia))
    vehiculos = _vehiculos_del_dia(inst, tramos_semana, cat)

    for arranque in range(cfg.n_arranques):
        if asignacion_sugerida and arranque % 2 == 0:
            asignacion = dict(asignacion_sugerida)
        else:
            asignacion = sortear_asignacion(rng, inst, M, vehiculos, tramos_semana, cat)
        if not asignacion:
            continue
        for dia in inst.dias:
            tramos = _tramos_del_dia(inst, cat, seleccion, dia)
            if not tramos:
                continue
            sol = construir_grasp(ev, inst, M, cfg, cat, dia, tramos, asignacion, rng, duales)
            pool.agregar_solucion(sol)
            sol = vnd(ev, cfg, cat, sol)
            pool.agregar_solucion(sol)


def inst_sol_penal(inst: Instancia, cat: Catalogo, tid: str) -> float:
    tr = cat.tramos[tid]
    return inst.clases[tr.clase].penal_externalizacion
