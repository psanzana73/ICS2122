#!/bin/zsh
# Turno extra: últimos 3 escenarios de I10S3 (el otro turno va desde el principio) y luego hubs_todas.
L=outputs/paralelo_sens_rapido.log
caffeinate -i .venv/bin/python -u correr_paralelo.py --tipo big --instancias 10 --semanas 3 --escenarios penal_x05 bases_fijo_x2 sin_talagante --procesos 3 -- --hilos 2 >> $L 2>&1
for iw in "7 4" "10 3"; do
  i=${iw% *}; w=${iw#* }
  f=outputs/kpis_big_Instancia${i}_semana${w}_esc-hubs_todas.csv
  [ -f $f ] && continue
  caffeinate -i .venv/bin/python -u main.py --tipo big --instancia "Instancia $i" --semana $w --hubs-todas --etiqueta esc-hubs_todas --hilos 2 > outputs/log_big_Instancia${i}_semana${w}_esc-hubs_todas.txt 2>&1 &
done
wait
echo "[rapido] fin $(date)" >> $L
