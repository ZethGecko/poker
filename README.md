# Mesa de poker entre amigos

**Texas Hold'em**, **5-Card Draw** y **BlackJack** para jugar con los amigos, cada uno
desde su propia red. Fichas de mentira, **sin dinero real, sin cuentas y sin base de datos**:
todo el estado de la mesa vive en la memoria del proceso y desaparece al cerrar el
servidor.

```
proyecto/
├── run.sh                 arranque rápido
├── server/
│   ├── app.py             servidor HTTP + Server-Sent Events (sin dependencias)
│   ├── rooms.py           salas en memoria, lobby, chat, temporizadores
│   ├── engine.py          motor de la mesa (apuestas, botes, showdown, black jack)
│   └── hands.py           baraja, evaluación de manos y total de black jack
├── public/                el front (HTML + CSS + JS sin frameworks ni build)
│   ├── index.html
│   ├── styles.css
│   └── js/{net,cards,table,app}.js
└── tests/
    ├── sim.py             simulador headless del motor
    ├── e2e.py             prueba contra el servidor real
    ├── test_blackjack.py  reglas de black jack
    └── check_front.py     comprobaciones estáticas del front
```

## Arrancar

No hace falta instalar nada: solo **Python 3** (probado con 3.14).

```bash
cd proyecto
python3 -m server.app            # http://localhost:8000
# o
./run.sh 8000
```

Al arrancar, el servidor imprime las direcciones accesibles:

```
  En esta maquina:  http://localhost:8000
  En la red local:  http://192.168.1.42:8000
```

## Jugar

1. Una persona entra, escribe su nombre y pulsa **Crear mesa**.
2. Copia el **código** de 5 letras (el botón lo copia al portapapeles) y se lo pasa al grupo.
3. Los demás entran en `http://<ip-del-anfitrión>:8000`, escriben su nombre y el código.
4. El anfitrión ajusta la variante, las ciegas y las fichas iniciales, y pulsa **Empezar**.

### Si no estáis en la misma wifi

El servidor está pensado para una red local. Para jugar desde redes distintas, publica el
puerto con un túnel y comparte esa URL:

```bash
cloudflared tunnel --url http://localhost:8000
# o
ngrok http 8000
```

## Qué incluye

- **Tres variantes**: Texas Hold'em (2 cartas privadas + 5 comunitarias) y 5-Card Draw
  (5 cartas privadas y descarte). En 5-Card Draw se mezclan varias barajas cuando los
  jugadores no caben en un solo mazo.
- **Bots para jugar sin compañía**: el anfitrión puede añadir bots (hasta 7) que
  se sentan y juegan como una persona normal (miran su mano, calculan las pot odds y
  arriesgan de vez en cuando). Con la opción de *relleno automático*, si alguien se va
  entra un bot en su hueco; y los bots se recargan solos cuando se quedan sin fichas.
- **Recargas de fichas**: si te quedas sin fichas, un botón en la barra de acciones
  (y en el marcador) te devuelve las fichas iniciales al momento.
- **BlackJack**: dos cartas por jugador, un ante para todos y el que más se acerca a 21
  sin pasarse se lleva el bote. El as vale 1 u 11 y las figuras valen 10. Con 21 natural
  (as + figura) se gana al instante; los empates se reparten y si todos se pasan el bote
  vuelve a cada uno.
- **Reglas completas**: ciegas, botón de dealer, subida mínima, all-in corto, botes
  laterales, división de empates y devolución de apuestas sin igualar.
- **Mesa en vivo**: asientos repartidos en óvalo con tu posición abajo, pozo con animación,
  temporizador de turno (30 s, pasa o se retira solo), registro de la mano, chat y marcador.
  Los bots juegan con un retardo corto para que la mesa no parezca automática.
- **Showdown**: se muestran las manos, se resalta la mejor combinación de 5 y se reparte el bote.
  En BlackJack se ve el total de cada uno y la mejor mano queda resaltada.
- **Reconexión**: tu asiento y tu ficha se guardan en el navegador; si se cae la conexión,
  el cliente se reconecta solo y te devuelve a la mesa.
- **Sonido** generado en el navegador (sin ficheros de audio) y pantalla adaptable a móvil.

## Detalles técnicos

- **Sin base de datos**: `server/rooms.py` mantiene un diccionario de salas en RAM. Cuando
  todos se van, la sala se elimina.
- **Tiempo real**: el servidor difunde el estado con **Server-Sent Events** (`GET
  /api/rooms/<código>/stream`). El estado que recibe cada jugador va filtrado: **nunca te
  llegan las cartas privadas de los demás** (solo al showdown y las tuyas).
- **API**: `POST /api/rooms` (crear), `POST /api/rooms/<código>/join`, `POST
  /api/rooms/<código>/action`, `.../chat`, `.../settings`, `.../start`, `.../next`,
  `.../rebuy`, `.../leave`.
- **Seguridad ligera**: cada jugador recibe un token opaco; el servidor lo exige para leer o
  modificar la sala.

## Pruebas

```bash
python3 tests/sim.py 400 4 holdem   # miles de manos con bots: fichas, bucles y botes
python3 tests/sim.py 400 3 draw
python3 tests/sim.py 400 4 blackjack
python3 tests/test_blackjack.py      # reglas de black jack (21 natural, empate, etc.)
python3 tests/test_bots.py           # bots: llenado, juego autonomo y recargas
python3 tests/e2e.py http://127.0.0.1:8000 holdem   # sala real: SSE, acciones, showdown
python3 tests/e2e.py http://127.0.0.1:8000 blackjack
python3 tests/check_front.py         # ids, imports y clases CSS del front
```

`tests/sim.py` juega manos completas con decisiones aleatorias y comprueba que las fichas
se conservan, que no hay bucles infinitos y que todas las botes se reparten.

## Límites conocidos

- Las salas son efímeras: si reinicias el servidor, las mesas y las partidas se pierden.
- No hay emparejamiento automático ni persistencia de manos entre sesiones.
- El temporizador de turno es fijo (30 s) y no se puede ajustar desde la interfaz.
