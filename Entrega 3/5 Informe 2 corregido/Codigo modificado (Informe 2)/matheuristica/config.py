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
    n_arranques: int = 10                  # arranques multi-start por iteración (cada uno = 1 posicionamiento x 5 días)
    posicionamiento_antiguo: bool = False  # True = sorteo de la v1 (para comparar)
    # constructor del pool inicial: "regret" (GRASP por arrepentimiento),
    # "cronologico" (GRASP por urgencia) o "mixto" (mitad y mitad)
    constructor: str = "mixto"
    fraccion_flota: tuple = (0.6, 1.0)   # fracción de cada tipo disponible en cada arranque
    eps_rcl: float = 0.15                  # amplitud de la lista restringida
    semilla: int = 20262
    # Regla de inserción (antes estaba escondida como constante en el código):
    # la entrega se inserta a lo más esta cantidad de posiciones después del retiro.
    max_desfase_insercion: int = 8
    max_desfase_completar: int = 10        # idem en la post-optimización por inserción
    # Costo fijo en la heurística. El costo fijo del vehículo es semanal; al
    # abrir un vehículo-día vacío la heurística le carga f_k / |D| (su cuota
    # diaria). Sin esto, abrir un vehículo nuevo parecía gratis y el pool se
    # llenaba de rutas cortas en muchos vehículos. 0 = comportamiento antiguo.
    peso_costo_fijo: float = 0.0          # 1 = cobra f_k/|D|; empeoró en los experimentos (ver informe)

    # ------------------------------------------------------------------ VND
    # Penalización de espera usada SOLO por la heurística al comparar
    # inserciones (el maestro optimiza el costo real). Sin ella el GRASP arma
    # rutas temporalmente dispersas -- una solicitud de la mañana y otra de la
    # tarde -- que consumen la jornada y bloquean inserciones posteriores.
    peso_espera: float = 0.0              # v1 usaba 150; experimento: 0 da mejores soluciones
    vnd_activo: bool = True
    vnd_max_pasadas: int = 60

    # ------------------------------------------------------------------ pool
    max_cols_por_vehiculo_dia: int = 300

    # ------------------------------------------------ generación de columnas
    # Después de cada relajación lineal del maestro se resuelve un problema de
    # pricing heurístico por día: inserción por arrepentimiento con premios
    # (precios duales) que solo agrega rutas de costo reducido negativo.
    # Se repite hasta que no aparecen columnas negativas o se llega al tope.
    cg_activa: bool = True
    cg_max_rondas: int = 6
    cg_tol_mejora: float = 0.001           # corta si la cota LP mejora menos de 0,1 %
    cg_posicionamientos: int = 2           # posicionamientos probados por ronda

    # -------------------------------------------------------- matheurística
    max_iteraciones: int = 3               # vueltas del Algoritmo 1
    reparacion_activa: bool = True
    max_criticas_por_dia: int = 25         # tope de solicitudes críticas que se reparan (x 5 días = 125 por semana)
    # Extensión: generar planes de transferencia para TODAS las solicitudes
    # transferibles (no solo las críticas) a partir de la 2.ª iteración.
    hubs_todas: bool = False
    # post-optimización por inserción (completar.py): antes de aceptar una
    # externalización se intenta insertar la solicitud en las rutas del maestro
    # o en vehículo-días ociosos ya pagados.
    completar_activo: bool = True
    # la solución del caso base entra al pool y como candidata a punto de partida
    arranque_caso_base: bool = True

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
    # Límite determinista de Gurobi (unidades de trabajo, ~1 s c/u). Con
    # TimeLimit el resultado depende de la velocidad del computador; con
    # WorkLimit dos corridas iguales dan la misma solución. None = usar TimeLimit.
    work_limit_maestro: float | None = 300.0
    hilos_gurobi: int = 0                  # 0 = todos los núcleos
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
