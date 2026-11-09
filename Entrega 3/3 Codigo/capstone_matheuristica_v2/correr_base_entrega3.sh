#!/bin/bash
# Caso base de todo lo nuevo de la Entrega 3: 40 semanas SMALL y los escenarios nuevos.
PY=.venv/bin/python
$PY caso_base_2.py --tipo small --salida outputs/base_small > outputs/log_base_small.txt 2>&1 && echo "small listo"
SENS="base bases_fijo_x2 congestion30 congestion50 demanda+20 demanda-20 flota-25 hubs_todas jornada7 penal_x05 penal_x2 sin_talagante"
INTER="demanda+30 demanda+10 demanda-10 congestion15 sin_atraso"
BASES="sin_quilicura sin_pudahuel sin_renca sin_cerrillos sin_san_bernardo sin_macul sin_penalolen sin_lampa"
FURG="furgon+2 furgon+4 furgon+8"
uno() { $PY caso_base_2.py --tipo big --instancias $1 --semanas $2 --escenario $3 --salida outputs/sens_base > /dev/null 2>&1 || echo "FALLÓ base $1 $2 $3"; }
for e in $SENS; do uno 1 1 $e; uno 8 3 $e; done
for e in hubs_todas $INTER $BASES $FURG; do uno 7 4 $e; uno 10 3 $e; done
echo "escenarios listos"
# Escenarios agregados después: base nueva, ventanas, sin división y capacidad de bases
for e in base_en_providencia base_en_puente_alto base_en_centro ventanas+30 ventanas-15 sin_division cap_bases+50 cap_bases-25; do uno 7 4 $e; uno 10 3 $e; done
echo "escenarios nuevos listos"
