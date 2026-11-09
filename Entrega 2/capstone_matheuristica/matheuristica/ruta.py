"""Representación y evaluación de rutas diarias.

Una ruta es una secuencia de paradas (tramo, tipo) que un vehículo recorre
saliendo y volviendo a su base. `Evaluador.evaluar` hace el chequeo completo de
factibilidad (ventanas, plazo máximo de traslado, capacidad, incompatibilidad
de clases a bordo, jornada + sobretiempo) y devuelve el costo de la columna.

El scheduling usa dos pasadas:
  1. hacia adelante: tiempos más tempranos posibles;
  2. hacia atrás: tiempos más tardíos admisibles -> *forward time slack*, que
     se usa para atrasar la salida de la base y reducir espera y sobretiempo
     sin alterar el orden de visitas (vecindario N5 del VND).
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import Config
from .datos import Instancia
from .matriz import Matriz
from .planes import Catalogo, Tramo

PICK, DROP = 0, 1
INF = float("inf")


@dataclass
class Ruta:
    vehiculo: str
    base: str
    dia: int
    paradas: tuple[tuple[str, int], ...]
    tramos: frozenset[str]
    solicitudes: frozenset[str]
    planes: frozenset[str]
    distancia: float
    sobretiempo: float
    tardanza: float
    costo: float
    salida: float
    retorno: float
    espera: float = 0.0
    costo_heuristico: float = 0.0
    tiempos: tuple[float, ...] = ()

    @property
    def clave(self):
        return (self.vehiculo, self.base, self.dia, self.paradas)


class Evaluador:
    def __init__(self, inst: Instancia, M: Matriz, cfg: Config, cat: Catalogo):
        self.inst, self.M, self.cfg, self.cat = inst, M, cfg, cat
        self._cache_parada: dict[tuple[str, int], tuple] = {}
        self.pares_incompatibles = inst.incompatibles

    # ------------------------------------------------------------------ #
    def parada(self, tid: str, tipo: int):
        """(nodo, servicio, ventana_lo, ventana_hi, clase, delta_carga)."""
        k = (tid, tipo)
        c = self._cache_parada.get(k)
        if c is not None:
            return c
        t: Tramo = self.cat.tramos[tid]
        if tipo == PICK:
            c = (t.origen, t.serv_pickup, float(t.ini_pickup), float(t.fin_pickup),
                 t.clase, t.cantidad)
        else:
            hi = t.due_delivery - t.serv_delivery
            if t.tardanza_ok:
                hi += self.cfg.tardanza_max
            if t.tope_fin_delivery is not None:
                hi = min(hi, t.tope_fin_delivery - t.serv_delivery)
            c = (t.destino, t.serv_delivery, float(t.ini_delivery), float(hi),
                 t.clase, -t.cantidad)
        self._cache_parada[k] = c
        return c

    # ------------------------------------------------------------------ #
    def _adelante(self, paradas, base, t0):
        """Tiempos de inicio de servicio más tempranos. None si infactible."""
        M = self.M
        pos, t = base, t0
        tiempos = []
        for tid, tipo in paradas:
            nodo, serv, lo, hi, _, _ = self.parada(tid, tipo)
            llegada = t + M.tiempo(pos, nodo)
            ini = llegada if llegada > lo else lo
            if ini > hi:
                return None, None
            tiempos.append(ini)
            t = ini + serv
            pos = nodo
        retorno = t + M.tiempo(pos, base)
        if retorno > self.cfg.fin_duro:
            return None, None
        return tiempos, retorno

    def _atras(self, paradas, base):
        """Tiempos de inicio más tardíos admisibles."""
        M = self.M
        n = len(paradas)
        lat = [0.0] * n
        siguiente_nodo, siguiente_lat = base, self.cfg.fin_duro
        for i in range(n - 1, -1, -1):
            tid, tipo = paradas[i]
            nodo, serv, lo, hi, _, _ = self.parada(tid, tipo)
            lim = siguiente_lat - M.tiempo(nodo, siguiente_nodo) - serv
            lat[i] = hi if hi < lim else lim
            if lat[i] < lo:
                return None
            siguiente_nodo, siguiente_lat = nodo, lat[i]
        return lat

    def _carga_ok(self, paradas, cap):
        carga = {}
        total = 0
        for tid, tipo in paradas:
            _, _, _, _, clase, delta = self.parada(tid, tipo)
            total += delta
            if total > cap:
                return False
            carga[clase] = carga.get(clase, 0) + delta
            if carga[clase] < 0:
                return False
            activas = [c for c, q in carga.items() if q > 0]
            if len(activas) > 1:
                for i in range(len(activas)):
                    for j in range(i + 1, len(activas)):
                        if frozenset((activas[i], activas[j])) in self.pares_incompatibles:
                            return False
        return True

    def _precedencia_ok(self, paradas):
        vistos = set()
        for tid, tipo in paradas:
            if tipo == PICK:
                vistos.add(tid)
            elif tid not in vistos:
                return False
        return True

    def _plazos_ok(self, paradas, tiempos):
        ini_pick = {}
        for (tid, tipo), t in zip(paradas, tiempos):
            tr = self.cat.tramos[tid]
            if tipo == PICK:
                ini_pick[tid] = t + tr.serv_pickup
            else:
                fin = t + tr.serv_delivery
                if tr.tope_fin_delivery is not None and fin > tr.tope_fin_delivery + 1e-6:
                    return False
                if tr.max_transport is not None:
                    if fin - ini_pick[tid] > tr.max_transport + 1e-6:
                        return False
        return True

    # ------------------------------------------------------------------ #
    def evaluar(self, paradas, vehiculo: str, base: str, dia: int) -> Ruta | None:
        if not paradas:
            return None
        veh = self.inst.vehiculos[vehiculo]
        tramos = {tid for tid, _ in paradas}
        # [fix] una ruta nunca lleva dos tramos de la misma solicitud: dos partes
        # de una división en el mismo vehículo no son una división, y las dos
        # piernas de una transferencia en el mismo vehículo hacen el hub inútil.
        # Antes solo lo revisaban GRASP y N2; el swap N3 lo violaba.
        sols = [self.cat.tramos[t].solicitud for t in tramos]
        if len(sols) != len(set(sols)):
            return None
        for tid in tramos:
            tr = self.cat.tramos[tid]
            if vehiculo not in tr.vehiculos or tr.clase not in veh.clases_compatibles:
                return None
        if not self._precedencia_ok(paradas):
            return None
        if not self._carga_ok(paradas, veh.capacidad):
            return None

        tiempos, retorno = self._adelante(paradas, base, float(self.cfg.jornada_inicio))
        if tiempos is None:
            return None
        lat = self._atras(paradas, base)
        if lat is None:
            return None

        # N5: atrasar la salida usando el forward time slack. Con la jornada fija
        # (S1) atrasar la salida NO es gratis: si empuja el retorno más allá de
        # las 17:00 genera sobretiempo. Se evalúan tres horarios (el más
        # temprano, el atraso completo y el atraso que no pasa de las 17:00) y se
        # elige el factible con menos sobretiempo y, a igualdad, menos espera.
        holgura = min(l - t for l, t in zip(lat, tiempos))
        fin = self.cfg.jornada_fin
        candidatos = [(tiempos, retorno)]
        if holgura > 1e-9:
            atrasos = {holgura, min(holgura, max(0.0, fin - retorno))}
            for at in atrasos:
                if at > 1e-9:
                    t2, r2 = self._adelante(paradas, base, self.cfg.jornada_inicio + at)
                    if t2 is not None:
                        candidatos.append((t2, r2))
        mejor_h = None
        for t_c, r_c in candidatos:
            if not self._plazos_ok(paradas, t_c):
                continue
            ot = max(0.0, r_c - fin)
            clave = (round(ot, 6), -t_c[0])   # menos sobretiempo; luego salir más tarde
            if mejor_h is None or clave < mejor_h[0]:
                mejor_h = (clave, t_c, r_c)
        if mejor_h is None:
            return None
        _, tiempos, retorno = mejor_h

        # métricas
        M = self.M
        pos = base
        dist = 0.0
        for tid, tipo in paradas:
            nodo = self.parada(tid, tipo)[0]
            dist += M.dist(pos, nodo)
            pos = nodo
        dist += M.dist(pos, base)

        salida = tiempos[0] - M.tiempo(base, self.parada(*paradas[0])[0])
        duracion = retorno - salida
        # [fix S1] sobretiempo = minutos de retorno después del fin de jornada
        # (17:00). Antes se medía como duración - 540, lo que dejaba volver a las
        # 18:30 sin costo si el vehículo había salido tarde.
        sobretiempo = max(0.0, retorno - self.cfg.jornada_fin)
        if sobretiempo > self.cfg.sobretiempo_max + 1e-6:
            return None

        tardanza = 0.0
        costo_tard = 0.0
        for (tid, tipo), t in zip(paradas, tiempos):
            if tipo == DROP:
                tr = self.cat.tramos[tid]
                d = max(0.0, (t + tr.serv_delivery) - tr.due_delivery)
                if d > 1e-9:
                    tardanza += d
                    costo_tard += d * tr.penal_tardanza

        costo = dist * veh.costo_km + sobretiempo * veh.costo_sobretiempo + costo_tard
        servicio = sum(self.parada(tid, tipo)[1] for tid, tipo in paradas)
        viaje = sum(
            M.tiempo(a, b) for a, b in zip(
                [base] + [self.parada(t, k)[0] for t, k in paradas],
                [self.parada(t, k)[0] for t, k in paradas] + [base]))
        espera = max(0.0, duracion - servicio - viaje)
        return Ruta(
            vehiculo=vehiculo, base=base, dia=dia, paradas=tuple(paradas),
            tramos=frozenset(tramos),
            solicitudes=frozenset(self.cat.tramos[t].solicitud for t in tramos),
            planes=frozenset(self.cat.tramos[t].plan for t in tramos),
            distancia=dist, sobretiempo=sobretiempo, tardanza=tardanza,
            costo=costo, salida=salida, retorno=retorno, espera=espera,
            costo_heuristico=costo + self.cfg.peso_espera * espera,
            tiempos=tuple(tiempos),
        )
