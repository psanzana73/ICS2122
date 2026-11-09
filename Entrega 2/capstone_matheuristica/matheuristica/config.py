"""Parámetros globales del modelo y de la matheurística.

Todo lo que sea un supuesto declarable en el informe vive acá, para que el
análisis de sensibilidad sea cambiar un número y volver a correr.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    # ------------------------------------------------------------------ datos
    dir_datos: Path = Path("data")
    dir_salida: Path = Path("outputs")
    tipo_instancia: str = "small"          # "small" | "big"
    hoja_instancia: str = "Instancia 1"
    semana: int = 1                        # week_of_month: 1..4

    # -------------------------------------------------------------- jornada
    # Supuesto (S1): jornada 08:00-17:00 recomendada por el ayudante.
    # Sobretiempo = minutos de RETORNO después de jornada_fin (no duración).
    jornada_inicio: int = 8 * 60           # 480
    jornada_fin: int = 17 * 60             # 1020
    sobretiempo_max: int = 120             # minutos extra admisibles por vehículo-día
    # Supuesto: tope operativo de tardanza (no viene en los datos).
    tardanza_max: int = 180

    # ------------------------------------------------------------- red vial
    usar_osmnx: bool = True                # False -> haversine x factor
    archivo_grafo: str = "grafo_santiago"
    factor_circuidad: float = 1.30         # solo modo haversine
    velocidad_kmh: float = 26.0            # solo modo haversine
    cache_matriz: bool = True

    # ---------------------------------------------------------------- GRASP
    n_arranques: int = 10                  # arranques multi-start por día e iteración
    eps_rcl: float = 0.15                  # amplitud de la lista restringida
    n_vecinos: int = 30                    # Upsilon: candidatos por cercanía (0 = sin poda)
    semilla: int = 20262

    # ------------------------------------------------------------------ VND
    # Penalización de espera usada SOLO por la heurística al comparar
    # inserciones (el maestro optimiza el costo real). Sin ella el GRASP arma
    # rutas temporalmente dispersas -- una solicitud de la mañana y otra de la
    # tarde -- que consumen la jornada y bloquean inserciones posteriores.
    peso_espera: float = 150.0
    vnd_activo: bool = True
    vnd_max_pasadas: int = 60

    # ------------------------------------------------------------------ pool
    max_cols_por_vehiculo_dia: int = 300

    # -------------------------------------------------------- matheurística
    max_iteraciones: int = 3               # vueltas del Algoritmo 1
    reparacion_activa: bool = True
    max_criticas_por_dia: int = 25         # cuántas solicitudes reparar por día
    # post-optimización por inserción (completar.py): antes de aceptar una
    # externalización se intenta insertar la solicitud en las rutas del maestro
    # o en vehículo-días ociosos ya pagados.
    completar_activo: bool = True

    # --------------------------------------------------------------- planes
    # Discretización que introduce la formulación por planes (ver informe).
    ancho_ventana_pickup: int = 30         # W: ancho de la ventana de retiro comprometida
    paso_slot_hub: int = 30                # granularidad del instante de intercambio
    holgura_hub: int = 60                  # cuánto puede esperar la carga en el hub
    max_hubs_por_solicitud: int = 3        # hubs candidatos más cercanos al par (o,d)
    max_slots_por_hub: int = 3             # instantes de intercambio por hub candidato

    # -------------------------------------------------------------- maestro
    mip_gap: float = 0.01
    time_limit_maestro: float = 300.0
    log_gurobi: bool = False

    # ---------------------------------------------------------------- otros
    dias: tuple = field(default=(1, 2, 3, 4, 5))

    @property
    def horizonte(self) -> int:
        """Duración nominal de la jornada H."""
        return self.jornada_fin - self.jornada_inicio

    @property
    def fin_duro(self) -> int:
        """Último instante admisible de retorno a base."""
        return self.jornada_fin + self.sobretiempo_max

    @property
    def archivo_transversal(self) -> Path:
        return self.dir_datos / "set_datos_transversal.xlsx"

    @property
    def archivo_instancias(self) -> Path:
        return self.dir_datos / f"instancias_{self.tipo_instancia}.xlsx"
