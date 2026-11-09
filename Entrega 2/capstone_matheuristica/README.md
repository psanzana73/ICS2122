# Matheurística para la red semanal de transporte sanitario

Implementación de la estrategia descrita en el informe: **generación heurística
de columnas (GRASP + VND, par-preservante) + maestro semanal de particionamiento
de conjuntos en Gurobi**, con descomposición diaria del ruteo.

El maestro decide simultáneamente qué vehículos activar, en qué base
posicionarlos, qué hubs habilitar, qué modalidad usa cada solicitud (directa /
transferencia / división / externalización) y qué ruta hace cada vehículo cada
día. La heurística no decide nada: solo propone columnas.

---

## 0. Instancia de prueba (correr esto primero)

```bash
python main.py --test
```

Resuelve **Instancia 1 small, semana 1, días 1 y 5**: 100 de las 258
solicitudes, las 4 clases, 17 divisiones obligatorias y 17 de las 23
externalizaciones de la corrida completa original. Mantiene el acople semanal
(activación de flota, bases, hubs) y reutiliza la matriz ya cacheada. Usa
4 arranques, 2 iteraciones y 120 s por maestro: debería tomar **~5-10 min**.
Todo lo de la línea de comando sigue funcionando (`--test --arranques 6`, etc.).

Al final imprime una **validación independiente** (`matheuristica/validacion.py`)
que revisa desde los datos cada restricción del modelo y alerta si queda alguna
solicitud externalizada teniendo vehículos compatibles ya pagados sin salir ese
día. Queda en `outputs/validacion_TEST_*.txt`. Criterio para pasar a small/big:
**0 errores y 0 alertas**, costo y tasa de externalización razonables.

Validación cruzada desde los CSV (script aparte, no usa el código del paquete):

```bash
python validar_solucion.py --excel data/instancias_small.xlsx --hoja "Instancia 1" \
    --semana 1 --dias 1 5 --tag TEST_small_Instancia1_semana1
```

### Correcciones de esta versión (respecto de la corrida del 21-09)

| Problema observado | Corrección |
| --- | --- |
| Sobretiempo medido como *duración* − 540: 30 vehículo-días volvían después de las 17:00 (hasta 18:35) sin pagar; se reportaban $16 mil en vez de $2,05 M. Violaba (S1) e invalidaba la comparación con el caso base | `ruta.py`: sobretiempo = retorno − 17:00. El atraso de salida (N5) ya no puede empujar el retorno más allá de las 17:00 si eso agrega sobretiempo |
| 23 externalizadas en días con vehículos compatibles ya pagados y ociosos (día 5: 4 furgones sin salir y 11 externalizadas a $190 mil c/u) | `completar.py`: post-optimización por inserción después de cada maestro (en rutas existentes y vehículo-días ociosos, con divisiones en vehículos distintos) + activación de vehículos cuando el ahorro semanal supera su costo fijo |
| Maestro cortado por tiempo con gap 27 % en iteraciones 2-3 | `maestro.py`: MIP start con la incumbente; el costo nunca empeora entre iteraciones. Cierre final del maestro sobre el pool completo |
| Transferencia con el mismo vehículo en ambas piernas (D1_R37, paga hub sin usarlo) y división con dos partes en el mismo vehículo (D4_R170) — los generaba el swap N3 | `ruta.py`: una ruta nunca contiene dos tramos de la misma solicitud |
| Cota LP reportada podía no corresponder a la solución final | se reporta `gap_vs_cota_lp` y el maestro final recalcula la cota |

`--sin-completar` desactiva la post-optimización, para medir su aporte.

### Cómo leer las dos brechas

- `gap_maestro` es el gap MIP de Gurobi: 0 % = óptimo **entre las columnas del pool**.
- `gap_vs_cota_lp` compara con la relajación lineal del pool. Es naturalmente
  alto (~10-15 %) porque la relajación "paga" fracciones de los costos fijos
  semanales de vehículos y bases; no indica que la solución sea mala.

## 0.b Corridas en lote (small / big)

```bash
python correr_lote.py --tipo small -- --arranques 4 --iteraciones 2
python correr_lote.py --tipo small --instancias 1 2 --semanas 1 2
python correr_lote.py --tipo big -- --arranques 4 --iteraciones 2
```

Lo que va después de `--` se pasa tal cual a `main.py`. Cada corrida deja su log
en `outputs/log_*.txt`; se puede cortar y relanzar (salta lo ya resuelto,
`--rehacer` para forzar). `outputs/resumen_<tipo>.csv` junta los KPI de todas
las instancia-semana más el n.º de errores y alertas de la validación.

Referencia de tiempo: `--test` (2 días, 4 arranques, 2 iteraciones) tomó 228 s
en el PC del grupo, así que una semana completa con esos parámetros debería
tomar ~10 min (≈ 7 h las 40 corridas small). Con los valores por defecto
(10 arranques, 3 iteraciones) la corrida original tomó 51 min.

## 1. Instalación

```bash
python -m venv .venv && source .venv/bin/activate     # opcional
pip install -r requirements.txt
```

**Licencia de Gurobi.** La que instala `pip install gurobipy` está limitada a
2.000 variables y 2.000 restricciones, y el maestro semanal completo la supera
apenas el pool pasa de ~1.000 columnas. Con la licencia académica de la UC no
hay problema. Si aparece `LicenciaInsuficiente`, bajá el pool con
`--max-columnas 10` o resolvé menos días con `--dias 1 2`.

## 2. Datos

```
data/
  set_datos_transversal.xlsx
  instancias_small.xlsx
  instancias_big.xlsx
  grafo_santiago            <- MultiDiGraph pickleado que entregó el curso
```

La primera corrida con OSMnx construye la matriz de tiempos y distancias con un
Dijkstra por punto de origen (no un `shortest_path` por par) y la deja cacheada
en `data/matriz_osmnx_<n>.npz`. Toma varios minutos una sola vez; después es
instantánea. Con `--sin-osmnx` se usa haversine × 1.30 a 26 km/h, el mismo
supuesto del caso base.

## 3. Uso

```bash
python main.py                                     # Instancia 1 small, semana 1
python main.py --instancia "Instancia 3" --semana 2
python main.py --tipo big --arranques 8 --iteraciones 3
python main.py --sin-osmnx --sin-reparacion        # caso "sin coordinación"
python main.py --dias 1 --max-columnas 10          # prototipo rápido
python main.py --test                              # instancia de prueba (ver §0)
```

Banderas principales:

| Bandera | Qué controla |
| --- | --- |
| `--arranques` | arranques multi-start del GRASP por iteración (calidad ↔ tiempo) |
| `--iteraciones` | vueltas del ciclo generar columnas → resolver maestro → reparar |
| `--max-columnas` | columnas por (vehículo, día) que sobreviven a la poda del pool |
| `--sin-reparacion` | desactiva transferencias y divisiones nuevas → **mide el valor de la coordinación** |
| `--sin-osmnx` | red vial aproximada en vez del grafo real |
| `--dias`, `--max-solicitudes`, `--max-vehiculos` | recortes para la prueba de concepto |
| `--time-limit`, `--log-gurobi` | control del solver |

Salidas en `outputs/`: `kpis_*`, `rutas_*` (secuencia completa con horarios),
`vehiculo_dia_*`, `posicionamiento_*`, `coordinacion_*` (transferencias y
divisiones elegidas), `externalizadas_*`, `diagnostico_*`.

## 4. Estructura

| Archivo | Rol | Correspondencia con el informe |
| --- | --- | --- |
| `config.py` | parámetros y supuestos | supuestos (S1)-(S8) |
| `datos.py` | lectura de los .xlsx | conjuntos y parámetros |
| `matriz.py` | tiempos y distancias | red vial |
| `planes.py` | planes de servicio y tramos | Sección "Planes de servicio y tramos" |
| `ruta.py` | evaluación de una columna | restricciones de ruteo, tiempo, carga |
| `heuristica.py` | GRASP + VND + pool | Algoritmos 2 y 3 |
| `maestro.py` | MILP en Gurobi | modelo maestro (m1)-(m7) |
| `diagnostico.py` | factibilidad estructural | objetivo específico 2 |
| `completar.py` | post-optimización por inserción + activación | reparación de la solución del maestro |
| `validacion.py` | chequeo independiente de la solución final | verificación |
| `kpis.py` | indicadores y export | tabla de KPI |
| `main.py` | orquestación | Algoritmo 1 |

## 5. Tres decisiones de implementación que conviene explicar en el informe

**El posicionamiento se sortea por semana, no por día.** Las restricciones
(m4)-(m5) obligan a que un vehículo tenga una sola base en toda la semana. Si
cada día sorteara su base, las columnas del mismo vehículo en días distintos
serían mutuamente excluyentes y el pool quedaría inservible. Cada escenario
GRASP fija un posicionamiento y construye los cinco días con él.

**Las columnas de la solución incumbente se protegen de la poda.** Sin eso el
costo del maestro puede *empeorar* entre iteraciones, porque las columnas nuevas
(peores, generadas forzando planes alternativos) desplazan a las buenas.

**Las divisiones estructuralmente necesarias entran en la primera iteración.**
Una solicitud cuya cantidad excede la capacidad de todo vehículo compatible no
es un caso de mejora opcional: su plan de división es la única alternativa a
externalizarla. En la Instancia 1 small son 39 de 258.

## 6. Lo que el diagnóstico encuentra en la Instancia 1 small (semana 1)

```
50 solicitudes no son atendibles de forma directa:
    39  la cantidad supera la capacidad de todo vehículo compatible
     7  base -> origen -> destino -> base no cabe en la jornada + sobretiempo
     3  el plazo máximo de traslado es menor que viaje + tiempos de atención
     1  el compromiso de entrega no se alcanza
 -> 39 se recuperan con división
 -> 11 son externalización forzosa (4,3 % de la demanda)
```

Ese 4,3 % es una **cota inferior a la tasa de externalización de cualquier
solución** y es la referencia honesta contra la cual leer el resultado final.
Las tres solicitudes con `max_transport` insuficiente son todas
`MUESTRA_CLINICA` (165 min de plazo contra ~130 min de viaje más 40 min de
atención): ninguna transferencia las salva, porque el plazo no se reinicia en
el hub y el *handling* agrega 30 min más.

## 7. Limitaciones conocidas

- Los planes de transferencia discretizan el instante de intercambio
  (`paso_slot_hub`, `max_slots_por_hub`) y comprometen una ventana de retiro de
  ancho `ancho_ventana_pickup`. Es la única fuente de pérdida de optimalidad
  respecto del modelo monolítico, y es conservadora: nunca produce una solución
  infactible.
- Los planes de división usan tramos directos; no se combina división con
  transferencia en la misma solicitud.
- La cota inferior que reporta el maestro es sobre **el pool**, no sobre el
  problema: un gap de 1 % significa "casi óptimo entre las columnas generadas",
  no "casi óptimo global".
- El VND explora N1, N2 y N3. El cross-exchange (N4) del informe no está
  implementado; N5 (re-scheduling) sí, dentro de `Evaluador.evaluar`.
- Los controles documentales no restringen la asignación porque los datos no
  asocian certificaciones a los vehículos (supuesto S4).
