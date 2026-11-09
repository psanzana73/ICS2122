# Matheurística para la red semanal de transporte sanitario (G12)

ICS2122 Taller de Investigación Operativa (Capstone), proyecto P4.

Para cada semana, la herramienta decide qué vehículos contratar, en qué base ubicarlos, qué hubs habilitar,
cómo atender cada solicitud (directa, dividida, transferida o externalizada) y la ruta diaria de cada vehículo.
Usa GRASP + VND para generar rutas, un modelo maestro de particionamiento de conjuntos en Gurobi para elegir
entre ellas y generación de columnas con los precios duales del maestro. Se compara contra un caso base que
planifica con reglas.

## 1. Instalación

Requiere Python 3.11 o más nuevo y una licencia de Gurobi (la académica es gratis con el correo UC).

```bash
python3 -m venv .venv
source .venv/bin/activate          # en Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

La licencia: crear una cuenta en gurobi.com con el correo UC, pedir una licencia "Academic WLS",
descargar `gurobi.lic` y dejarla en la carpeta personal (`~/gurobi.lic` en Mac, `C:\Users\<usuario>\gurobi.lic`
en Windows). Para comprobarla: `python -c "import gurobipy; gurobipy.Model()"` no debe mostrar errores.

Los datos van en `data/`. La matriz de tiempos y distancias ya está calculada en `data/matriz_osmnx_120.npz`,
así que no se necesita el grafo vial ni `osmnx`.

## 2. Uso

Una semana con la matheurística (BIG tarda unos 25 minutos; SMALL, menos):

```bash
python main.py --tipo big --instancia "Instancia 7" --semana 4 --hilos 2
```

El caso base para todas las semanas (segundos por semana):

```bash
python caso_base_2.py --tipo big --salida outputs/base_v2
```

Muchas semanas o escenarios en paralelo. Es reanudable: salta lo que ya tiene `outputs/kpis_*.csv`.

```bash
python correr_paralelo.py --tipo small --procesos 2 -- --hilos 2
python correr_paralelo.py --tipo big --instancias 7 --semanas 4 --escenarios demanda+10 sin_atraso --procesos 2 -- --hilos 2
python correr_paralelo.py --tipo big --instancias 3 --semanas 2 --semillas 1 2 3 --procesos 2 -- --hilos 2
```

También se puede pasar una lista de tareas, una por línea (`tipo instancia semana [escenario] [semilla]`):

```bash
python correr_paralelo.py --lista tareas.txt --procesos 2 -- --hilos 2
```

`--pausa-min`, `--descanso-cada-min` y `--descanso-min` agregan pausas para no exigir el computador.

### Escenarios de sensibilidad (`--escenario`)

| Nombre | Cambio |
| --- | --- |
| `demanda+N`, `demanda-N` | N % más o menos solicitudes (por ejemplo `demanda+10`) |
| `flota-25` | Un cuarto menos de vehículos de cada tipo |
| `furgon+N` | N furgones fríos adicionales |
| `congestionN` | Tiempos de viaje N % más largos |
| `jornada7` | La jornada parte a las 07:00 |
| `sin_atraso` | Ninguna clase admite atraso |
| `penal_x2`, `penal_x05` | Costo de externalizar ×2 o ×0,5 |
| `bases_fijo_x2` | Costo fijo de las bases ×2 |
| `sin_<base>` | Cierra una base (`sin_talagante`, `sin_macul`, `sin_san_bernardo`, ...) |
| `hubs_todas` | Planes de transferencia para todas las solicitudes transferibles |
| `base_en_<punto>` | Abre una base nueva en un punto de transferencia (`base_en_providencia`, `base_en_centro`, ...) |
| `cap_bases+N`, `cap_bases-N` | Capacidad de cada base N % mayor o menor |
| `ventanas+N`, `ventanas-N` | Ventanas de retiro y entrega N minutos más anchas o angostas |
| `sin_division` | Ninguna solicitud se puede dividir |

`--hubs-todas` en main.py equivale al escenario `hubs_todas`.

## 3. Salidas (`outputs/`)

Por cada corrida, con sufijo `<tipo>_Instancia<i>_semana<w>[_esc-<escenario>][_sem<semilla>]`:

- `kpis_*.csv`: costo desglosado e indicadores.
- `rutas_*.csv`, `posicionamiento_*.csv`, `coordinacion_*.csv`, `externalizadas_*.csv`: la solución.
- `traza_*.csv`: cota lineal, columnas y tiempos por vuelta.
- `log_*.txt`: el registro de la corrida, con la validación independiente al final.

Las corridas son deterministas: Gurobi se detiene por un límite de trabajo y no de tiempo, así que la misma
corrida da el mismo resultado en cualquier computador.

## 4. Tablas y figuras del informe

```bash
python analisis_resultados.py --math outputs --base outputs/base_v2 --out outputs/analisis
python analisis_sensibilidad.py --out outputs/analisis
python figuras_datos.py
bash correr_base_entrega3.sh          # caso base de SMALL y de todos los escenarios
python analisis_entrega3.py           # resume SMALL, escenarios y semillas
python tablas_entrega3.py --informe "../Informe Final/latex"
```

## 5. Estructura

| Archivo | Función |
| --- | --- |
| `matheuristica/datos.py`, `matriz.py` | Lectura de datos y matriz de tiempos |
| `matheuristica/planes.py` | Planes directos, de división y de transferencia |
| `matheuristica/ruta.py` | Evaluación y factibilidad de rutas |
| `matheuristica/heuristica.py` | GRASP + VND y pricing con duales |
| `matheuristica/maestro.py` | Modelo maestro y relajación lineal |
| `matheuristica/completar.py` | Post-optimización por inserción |
| `matheuristica/validacion.py` | Validación independiente de cada solución |
| `matheuristica/escenarios.py` | Escenarios de sensibilidad |
| `matheuristica/kpis.py` | Indicadores |
| `main.py` | Matheurística completa para una semana |
| `caso_base_2.py` | Caso base |
| `correr_paralelo.py` | Corridas en lote |
| `experimento_*.py` | Experimentos de calibración del informe |
