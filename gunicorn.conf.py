# gunicorn.conf.py
import os

# Render inyecta el puerto en la variable de entorno PORT
bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"

# Un solo proceso: así todos los workers comparten la misma memoria de salas.
# Con varios procesos de Gunicorn cada uno tiene su propio diccionario de salas
# y una mesa creada en un worker no se encuentra en otro -> 404 "mesa no existe".
workers = 1

# gthread permite atender peticiones HTTP normales mientras una conexion SSE
# permanece abierta (sin bloquear todo el servidor).
worker_class = "gthread"
threads = 8

timeout = 120
keepalive = 2
accesslog = "-"
errorlog = "-"
loglevel = "info"

proc_name = "poker-game-v"
