"""Generación de columnas: GRASP + VND (pool inicial) y pricing con duales.

Todos los movimientos son *par-preservantes*: la unidad atómica que se inserta,
mueve o intercambia es el tramo completo (retiro + entrega). Nunca se extrae un
nodo sin su par.

Dos generadores de columnas:
  * `generar_columnas_semana`: multi-arranque GRASP + VND. Construye soluciones
    diarias completas (todas las solicitudes del día) y aporta al pool las rutas
    de la solución final del GRASP y de la solución final del VND de cada
    arranque y día. Es un generador PRIMAL: no usa precios duales.
  * `pricing_dia`: subproblema de la generación de columnas. Con los precios
    duales de la relajación lineal del maestro, construye rutas por inserción
    con premios (cada tramo "paga" su precio dual) y devuelve solo las rutas de
    costo reducido negativo.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from .config import Config
from .datos import Instancia
from .matriz import Matriz
from .planes import Catalogo
from .ruta import DROP, PICK, Evaluador, Ruta


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
    mejor = None
    cap = ev.inst.vehiculos[veh].capacidad
    for i, j in ev.posiciones_por_carga(paradas, tid, cap, ev.cfg.max_desfase_insercion):
        parcial = paradas[:i] + [(tid, PICK)] + paradas[i:]
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
    """Asigna cada vehículo a una base, en proporción a la demanda que cada base
    tiene cerca, con ruido para diversificar entre arranques.

    [v2] Antes cada vehículo iba a una de las 3 bases más cercanas al centroide
    de su demanda compatible; como todos los vehículos de un tipo tienen el
    mismo centroide, se amontonaban en las mismas bases hasta llenarlas. Ahora,
    para cada tipo de vehículo, cada base pesa según cuántos orígenes
    compatibles tiene como base más cercana, y los vehículos se reparten
    eligiendo la base con mayor peso / (1 + vehículos de ese tipo ya asignados),
    multiplicado por un factor aleatorio en [0,6; 1,4].
    """
    if getattr(inst.cfg, "posicionamiento_antiguo", False):
        return _sortear_asignacion_v1(rng, inst, M, vehiculos, tramos, cat)
    bases = sorted(inst.bases)
    cupo = {b: inst.bases[b].capacidad for b in bases}
    cercana = {}
    por_tipo: dict[str, list[str]] = {}
    for v in vehiculos:
        por_tipo.setdefault(inst.vehiculos[v].clase, []).append(v)
    pesos: dict[str, dict[str, float]] = {}
    for tipo, vs in por_tipo.items():
        veh = inst.vehiculos[vs[0]]
        w = {b: 0.0 for b in bases}
        for t in tramos:
            tr = cat.tramos[t]
            if vs[0] in tr.vehiculos and tr.clase in veh.clases_compatibles:
                o = tr.origen
                if o not in cercana:
                    cercana[o] = min(bases, key=lambda b: (M.tiempo(b, o), b))
                w[cercana[o]] += 1.0
        pesos[tipo] = w
    asignacion: dict[str, str] = {}
    ya: dict[tuple, int] = {}
    orden = list(vehiculos)
    rng.shuffle(orden)
    for v in orden:
        tipo = inst.vehiculos[v].clase
        libres = [b for b in bases if cupo[b] > 0]
        if not libres:
            break
        b = max(libres, key=lambda b: ((pesos[tipo][b] + 0.5) / (1 + ya.get((tipo, b), 0))
                                       * rng.uniform(0.6, 1.4), b))
        asignacion[v] = b
        cupo[b] -= 1
        ya[(tipo, b)] = ya.get((tipo, b), 0) + 1
    return asignacion


def _sortear_asignacion_v1(rng, inst, M, vehiculos, tramos, cat):
    """Posicionamiento de la v1 (se conserva para comparar)."""
    bases = list(inst.bases.values())
    cupo = {b.id: b.capacidad for b in bases}
    asignacion: dict[str, str] = {}
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
                    asignacion: dict[str, str], rng: random.Random) -> SolucionDia:
    """Algoritmo 2: inserción greedy aleatorizada guiada por arrepentimiento.

    El arrepentimiento de un tramo es c2 - c1 (segunda mejor inserción menos la
    mejor). La lista restringida (RCL) guarda los tramos con arrepentimiento de
    al menos (1 - eps) veces el máximo y se elige uno al azar. Los tramos que
    caben en un solo vehículo tienen arrepentimiento infinito y entran primero.

    [v2] Antes se restaba el precio dual del tramo a c1 y a c2, lo que se
    cancela en la diferencia: los duales no influían. Ahora el GRASP es un
    generador primal puro y los duales se usan donde sí sirven, en `pricing_dia`.
    """
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

    todos = sorted(asignacion)
    for tid in sorted(pendientes):
        recomputar(tid, todos)

    while pendientes:
        mejores = []
        # [v2] orden fijo: antes se recorría un set de strings y el resultado
        # dependía de PYTHONHASHSEED (no se podía repetir una corrida)
        for tid in sorted(pendientes):
            opciones = cache.get(tid, {})
            if not opciones:
                continue
            ordenadas = sorted(opciones.items(), key=lambda kv: (kv[1][0], kv[0]))
            c1 = ordenadas[0][1][0]
            c2 = ordenadas[1][1][0] if len(ordenadas) > 1 else None
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
        for otro in sorted(pendientes):
            recomputar(otro, [veh])

    return sol


def construir_cronologico(ev: Evaluador, inst: Instancia, M: Matriz, cfg: Config,
                          cat: Catalogo, dia: int, tramos: list[str],
                          asignacion: dict[str, str], rng: random.Random,
                          k_rcl: int = 3) -> SolucionDia:
    """[v2] GRASP cronológico: inserción en orden de urgencia, aleatorizada.

    Los tramos se ordenan por fin de la ventana de retiro y luego por
    compromiso de entrega; en cada paso se elige al azar uno de los `k_rcl`
    primeros pendientes (lista restringida) y se inserta en la posición y el
    vehículo de menor costo heurístico. Con ventanas estrechas, el orden
    temporal arma rutas más encadenadas que el orden por arrepentimiento.
    """
    sol = SolucionDia(dia=dia, asignacion=asignacion)
    for v in asignacion:
        sol.paradas[v] = []
    orden = sorted(tramos, key=lambda t: (cat.tramos[t].fin_pickup,
                                          cat.tramos[t].due_delivery, t))
    vehs = sorted(asignacion)
    while orden:
        i = rng.randrange(min(k_rcl, len(orden)))
        tid = orden.pop(i)
        tr = cat.tramos[tid]
        mejor = None
        for v in vehs:
            if v not in tr.vehiculos or tr.clase not in inst.vehiculos[v].clases_compatibles:
                continue
            if any(cat.tramos[t].solicitud == tr.solicitud for t, _ in sol.paradas[v]):
                continue
            actual = sol.rutas.get(v)
            m = mejor_insercion(ev, sol.paradas[v], tid, v, asignacion[v], dia,
                                actual.costo_heuristico if actual else 0.0)
            if m is not None and (mejor is None or (m[0], v) < (mejor[0], mejor[1])):
                mejor = (m[0], v, m[1], m[2])
        if mejor is None:
            sol.sin_asignar.add(tid)
            continue
        _, v, nuevas, r = mejor
        sol.paradas[v] = nuevas
        sol.rutas[v] = r
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
def limpiar_planes_incompletos(ev: Evaluador, cat: Catalogo, sol: SolucionDia) -> SolucionDia:
    """[v2] Saca de las rutas los tramos de planes que quedaron a medias.

    Si el GRASP inserta una parte de una división pero no la otra, el plan no
    se puede elegir en el maestro, y la restricción de cobertura (m2) obliga a
    que NINGUNA ruta que contenga esa parte se use. Como las rutas llevan varias
    solicitudes, una sola parte huérfana inutilizaba la ruta completa (en la
    Instancia 10, semana 1, con un arranque: 378 de 599 solicitudes quedaban
    externalizadas por esto). Al sacar las partes huérfanas la ruta vuelve a
    ser elegible; la solicitud queda sin asignar y la recuperan otras columnas,
    la reparación o la post-optimización.
    """
    while True:
        asignados = {t for ps in sol.paradas.values() for t, _ in ps}
        incompletos = {cat.tramos[t].plan for t in asignados
                       if any(x not in asignados for x in cat.planes[cat.tramos[t].plan].tramos)}
        if not incompletos:
            return sol
        for v in sorted(sol.paradas):
            ps = sol.paradas[v]
            nuevas = [p for p in ps if cat.tramos[p[0]].plan not in incompletos]
            if len(nuevas) == len(ps):
                continue
            sol.sin_asignar |= {t for t, _ in ps if cat.tramos[t].plan in incompletos}
            r = ev.evaluar(nuevas, v, sol.asignacion[v], sol.dia) if nuevas else None
            if r is None:                      # (muy raro) la ruta recortada no es factible
                sol.sin_asignar |= {t for t, _ in nuevas}
                sol.paradas[v] = []
                sol.rutas.pop(v, None)
            else:
                sol.paradas[v] = nuevas
                sol.rutas[v] = r


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
                            asignacion_sugerida: dict[str, str] | None = None) -> list:
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
    soluciones = []          # [v2] (asignación, rutas de la semana) de cada arranque

    for arranque in range(cfg.n_arranques):
        if asignacion_sugerida and arranque % 2 == 0:
            asignacion = dict(asignacion_sugerida)
        else:
            # [v2] flota sorteada: cada arranque usa una fracción aleatoria de
            # cada tipo de vehículo. Con los 60 vehículos siempre disponibles la
            # construcción repartía la carga entre todos (43-52 vehículos) y
            # consolidaba poco; así el pool también tiene soluciones con flotas
            # chicas y el maestro elige el tamaño.
            flota = vehiculos
            lo, hi = cfg.fraccion_flota
            if hi < 1.0 or lo < 1.0:
                f = rng.uniform(lo, hi)
                por_tipo: dict[str, list[str]] = {}
                for v in vehiculos:
                    por_tipo.setdefault(inst.vehiculos[v].clase, []).append(v)
                flota = []
                for tipo in sorted(por_tipo):
                    vs = por_tipo[tipo]
                    flota += vs[: max(1, round(f * len(vs)))]
            asignacion = sortear_asignacion(rng, inst, M, flota, tramos_semana, cat)
        if not asignacion:
            continue
        rutas_semana = []
        for dia in inst.dias:
            tramos = _tramos_del_dia(inst, cat, seleccion, dia)
            if not tramos:
                continue
            if cfg.constructor == "cronologico" or (
                    cfg.constructor == "mixto" and arranque % 2 == 1):
                sol = construir_cronologico(ev, inst, M, cfg, cat, dia, tramos, asignacion, rng)
            else:
                sol = construir_grasp(ev, inst, M, cfg, cat, dia, tramos, asignacion, rng)
            sol = limpiar_planes_incompletos(ev, cat, sol)
            pool.agregar_solucion(sol)
            sol = vnd(ev, cfg, cat, sol)
            pool.agregar_solucion(sol)
            rutas_semana.extend(sol.rutas.values())
        soluciones.append((dict(asignacion), rutas_semana))
    return soluciones


# --------------------------------------------------------------------------- #
# Subproblema de pricing (generación de columnas con duales)
# --------------------------------------------------------------------------- #
def costo_reducido(r: Ruta, duales) -> float:
    """c_rho - sum_l pi_l - mu_kd - nu_kbd (signos de Gurobi: mu, nu <= 0)."""
    return (r.costo - sum(duales.precio(t) for t in r.tramos)
            - duales.mu.get((r.vehiculo, r.dia), 0.0)
            - duales.nu.get((r.vehiculo, r.base, r.dia), 0.0))


def pricing_dia(ev: Evaluador, inst: Instancia, cfg: Config, cat: Catalogo,
                dia: int, asignacion: dict[str, str], duales) -> list[Ruta]:
    """Pricing heurístico del día `dia` para un posicionamiento dado.

    Cada tramo candidato paga su precio dual pi_l. Se inserta repetidamente el
    par (tramo, vehículo) de menor valor  delta_costo - pi_l  (más el costo de
    usar el vehículo-día, -mu_kd - nu_kbd, si la ruta estaba vacía) mientras
    ese valor sea negativo; cada tramo se usa a lo más una vez y, por
    solicitud, solo tramos de un mismo plan. Luego el VND acorta las rutas.
    Devuelve las rutas con costo reducido negativo, que son las que pueden
    mejorar la relajación lineal del maestro.
    """
    candidatos = []
    for s in inst.por_dia(dia):
        for pid in cat.por_solicitud.get(s.id, []):
            for tid in cat.planes[pid].tramos:
                if duales.precio(tid) > 1e-6:
                    candidatos.append(tid)
    candidatos = sorted(set(candidatos))
    if not candidatos:
        return []

    sol = SolucionDia(dia=dia, asignacion=asignacion)
    for v in asignacion:
        sol.paradas[v] = []
    plan_de_sol: dict[str, str] = {}          # solicitud -> plan ya usado
    usados: set[str] = set()
    cache: dict[str, dict[str, tuple]] = {}

    def uso_vd(v):
        return (-duales.mu.get((v, dia), 0.0)
                - duales.nu.get((v, asignacion[v], dia), 0.0))

    def recomputar(tid, vehs):
        d = cache.setdefault(tid, {})
        tr = cat.tramos[tid]
        for v in vehs:
            d.pop(v, None)
            if v not in tr.vehiculos or tr.clase not in inst.vehiculos[v].clases_compatibles:
                continue
            if any(cat.tramos[t].solicitud == tr.solicitud for t, _ in sol.paradas[v]):
                continue
            actual = sol.rutas.get(v)
            mejor = None
            cap = inst.vehiculos[v].capacidad
            for i, j in ev.posiciones_por_carga(sol.paradas[v], tid, cap,
                                                 cfg.max_desfase_insercion):
                parcial = sol.paradas[v][:i] + [(tid, PICK)] + sol.paradas[v][i:]
                nuevas = parcial[:j] + [(tid, DROP)] + parcial[j:]
                r = ev.evaluar(nuevas, v, asignacion[v], dia)
                if r is None:
                    continue
                delta = r.costo - (actual.costo if actual else 0.0)
                if mejor is None or delta < mejor[0] - 1e-9:
                    mejor = (delta, nuevas, r)
            if mejor is not None:
                extra = 0.0 if actual else uso_vd(v)
                d[v] = (mejor[0] + extra - duales.precio(tid), mejor[1], mejor[2])

    vehs = sorted(asignacion)
    for tid in candidatos:
        recomputar(tid, vehs)

    while True:
        mejor = None
        for tid in candidatos:
            if tid in usados:
                continue
            tr = cat.tramos[tid]
            if plan_de_sol.get(tr.solicitud, tr.plan) != tr.plan:
                continue
            for v, (val, nuevas, r) in cache.get(tid, {}).items():
                if val < -1e-6 and (mejor is None or (val, tid, v) < mejor[:3]):
                    mejor = (val, tid, v, nuevas, r)
        if mejor is None:
            break
        _, tid, v, nuevas, r = mejor
        sol.paradas[v] = nuevas
        sol.rutas[v] = r
        usados.add(tid)
        plan_de_sol.setdefault(cat.tramos[tid].solicitud, cat.tramos[tid].plan)
        cache.pop(tid, None)
        for otro in candidatos:
            if otro not in usados:
                recomputar(otro, [v])

    rutas = list(sol.rutas.values())
    sol = vnd(ev, cfg, cat, sol)
    rutas += list(sol.rutas.values())
    vistas, salida = set(), []
    for r in rutas:
        clave = (r.vehiculo, r.base, r.dia, r.tramos)
        if clave in vistas:
            continue
        vistas.add(clave)
        if costo_reducido(r, duales) < -1.0:
            salida.append(r)
    return salida
