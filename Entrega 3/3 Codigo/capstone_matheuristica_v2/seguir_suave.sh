#!/bin/zsh
# Espera a que terminen las semanas que ya estaban corriendo y sigue con carga
# reducida: 2 procesos, Gurobi con 2 hilos, pausa de 5 min tras cada semana y
# descanso de 15 min cada hora.
while pgrep -f "main.py --tipo big" > /dev/null; do sleep 30; done
echo "[suave] semanas en curso terminadas, sigo con 2 procesos" >> outputs/paralelo_big.log
caffeinate -i .venv/bin/python -u correr_paralelo.py --tipo big --procesos 2 \
  --pausa-min 5 --descanso-cada-min 60 --descanso-min 15 -- --hilos 2 >> outputs/paralelo_big.log 2>&1
