#!/bin/zsh
# Sensibilidad de la matheurística en I7S4 e I10S3, con la misma carga suave.
while pgrep -f "correr_paralelo.py" > /dev/null; do sleep 30; done
L=outputs/paralelo_sens.log
ESC=(demanda+20 demanda-20 flota-25 congestion30 congestion50 jornada7 penal_x2 penal_x05 bases_fijo_x2 sin_talagante)
PAUSA=(--procesos 2 --pausa-min 5 --descanso-cada-min 60 --descanso-min 15)
echo "[sens] inicio $(date)" >> $L
caffeinate -i .venv/bin/python -u correr_paralelo.py --tipo big --instancias 7 --semanas 4 --escenarios $ESC $PAUSA -- --hilos 2 >> $L 2>&1
caffeinate -i .venv/bin/python -u correr_paralelo.py --tipo big --instancias 10 --semanas 3 --escenarios $ESC $PAUSA -- --hilos 2 >> $L 2>&1
for iw in "7 4" "10 3"; do
  i=${iw% *}; w=${iw#* }
  f=outputs/kpis_big_Instancia${i}_semana${w}_esc-hubs_todas.csv
  [ -f $f ] && continue
  caffeinate -i .venv/bin/python -u main.py --tipo big --instancia "Instancia $i" --semana $w --hubs-todas --etiqueta esc-hubs_todas --hilos 2 > outputs/log_big_Instancia${i}_semana${w}_esc-hubs_todas.txt 2>&1 &
done
wait
echo "[sens] fin $(date)" >> $L
