#!/bin/zsh
# Análisis por tamaño: 6 tamaños (0,25 a 2 veces BIG) x 3 réplicas generadas.
# Primero el caso base (rápido), después la matheurística con 2 procesos.
for r in 1 2 3; do for p in 025 050 075 100 150 200; do
  .venv/bin/python caso_base_2.py --tipo big --instancias 1 --semanas 1 --escenario tam${p}_r$r --salida outputs/tamanos | tail -1
done; done
caffeinate -i .venv/bin/python -u correr_paralelo.py --lista outputs/tamanos/tareas.txt --procesos 2 -- --hilos 2
echo "tamaños listos $(date)"
