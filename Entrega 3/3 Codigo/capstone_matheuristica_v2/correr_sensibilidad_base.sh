#!/bin/zsh
# Caso base en los escenarios de sensibilidad (semanas representativas) y
# sensibilidad de su utilización objetivo (40 semanas).
mkdir -p outputs/sens_base outputs/sens_util
for esc in base demanda+20 demanda-20 flota-25 congestion30 congestion50 jornada7 penal_x2 penal_x05 bases_fijo_x2 sin_talagante; do
  .venv/bin/python caso_base_2.py --tipo big --instancias 7 --semanas 4 --escenario $esc --salida outputs/sens_base > /dev/null 2>&1
  mv outputs/sens_base/resumen_base_informado_big*.csv outputs/sens_base/resumen_I7S4_$esc.csv 2>/dev/null
  .venv/bin/python caso_base_2.py --tipo big --instancias 10 --semanas 3 --escenario $esc --salida outputs/sens_base > /dev/null 2>&1
  mv outputs/sens_base/resumen_base_informado_big*.csv outputs/sens_base/resumen_I10S3_$esc.csv 2>/dev/null
  echo "base $esc listo"
done
for u in 0.6 0.7 0.9 1.0; do
  mkdir -p outputs/sens_util/u$u
  .venv/bin/python caso_base_2.py --tipo big --utilizacion $u --salida outputs/sens_util/u$u > /dev/null 2>&1
  echo "utilizacion $u lista"
done
