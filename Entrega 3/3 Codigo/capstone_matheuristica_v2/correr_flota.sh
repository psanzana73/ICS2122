#!/bin/zsh
# Curva de flota: -40, -10 y +25 % en las semanas mediana (I7S4) y de mayor demanda (I10S3).
while pgrep -f "correr_tamanos.sh" > /dev/null; do sleep 60; done
for e in flota-40 flota-10 flota+25; do for iw in "7 4" "10 3"; do
  .venv/bin/python caso_base_2.py --tipo big --instancias ${iw% *} --semanas ${iw#* } --escenario $e --salida outputs/sens_base | tail -1
done; done
caffeinate -i .venv/bin/python -u correr_paralelo.py --tipo big --instancias 7 --semanas 4 --escenarios flota-40 flota-10 flota+25 --procesos 2 -- --hilos 2
caffeinate -i .venv/bin/python -u correr_paralelo.py --tipo big --instancias 10 --semanas 3 --escenarios flota-40 flota-10 flota+25 --procesos 2 -- --hilos 2
echo "flota lista $(date)"
