"""Pruebas de los bots y de la recarga de fichas (sobre la sala, sin HTTP).

Uso: python3 tests/test_bots.py
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.engine import GameError  # noqa: E402
from server.rooms import Room  # noqa: E402

errores: list[str] = []


def check(cond, msg):
    if not cond:
        errores.append(msg)


def esperar(cond, timeout=8.0, paso=0.1):
    limite = time.time() + timeout
    while time.time() < limite:
        if cond():
            return True
        time.sleep(paso)
    return False


def nueva_mesa(variant="holdem", bots=2):
    room = Room("TEST")
    host = room.add_player("Ana")
    room.update_settings(host["id"], {
        "variant": variant, "small_blind": 10, "big_blind": 20, "start_stack": 500,
    })
    room.set_bots(host["id"], bots)
    return room, host


# --- 1. los bots se sentan y son recognoscibles
room, host = nueva_mesa(bots=3)
bots = [p for p in room.players if p.get("is_bot")]
check(len(bots) == 3, f"se esperaban 3 bots, hay {len(bots)}")
check(all(p["stack"] == 500 for p in bots), "los bots no arrancan con fichas")
check(len({p["name"] for p in bots}) == 3, "los bots tienen nombres repetidos")
check(room.settings["bots"] == 3, "el ajuste de bots no se guardo")

# --- 2. el anfitrion puede quitar los bots
room.set_bots(host["id"], 0, remove=True)
check(not [p for p in room.players if p.get("is_bot")], "no se quitaron los bots")
check(len(room.players) == 1, "se fueron los bots pero tambien los humanos")

# --- 3. los bots juegan solos (hold'em)
room, host = nueva_mesa(variant="holdem", bots=2)
room.start_game(host["id"])
game = room.game
check(game.to_act is not None, "no hay nadie en turno")
movimientos = 0
for _ in range(80):
    time.sleep(0.2)
    if game.phase != "betting":
        break
    if not game.to_act:
        continue
    if room.player(game.to_act).get("is_bot"):
        movimientos += 1
    else:
        # el humano tambien juega, para que la mano avance
        legal = game.legal_actions(game.to_act)
        accion = "check" if legal["to_call"] == 0 else "call"
        room.player_action(game.to_act, accion, 0)
check(movimientos >= 1, "los bots no han jugado ninguna vez")
check(len([l for l in room.log if l["kind"] == "action"]) >= 1, "no hay acciones en el registro")

# --- 4. en black jack los bots se plantan por encima de 17
room, host = nueva_mesa(variant="blackjack", bots=2)
room.start_game(host["id"])
game = room.game
esperar(lambda: game.phase == "hand_over" or game.phase == "betting")
time.sleep(2)
for p in room.players:
    if p.get("is_bot") and p.get("total", 0) > 21:
        check(p.get("busted"), f"{p['name']} se paso pero no esta marcado")

# --- 5. el bot se recarga solo cuando se queda sin fichas
room, host = nueva_mesa(variant="blackjack", bots=1)
room.start_game(host["id"])
game = room.game
bot_jugador = next(p for p in room.players if p.get("is_bot"))
bot_jugador["stack"] = 0
room._start_next_hand()
check(bot_jugador["stack"] > 0, f"el bot no se recargo: {bot_jugador['stack']}")
check(any("recupera" in l["text"] for l in room.log), "no se registro la recarga del bot")

# --- 6. el humano se puede recargar a mano
room, host = nueva_mesa(variant="holdem", bots=1)
host["stack"] = 0
room.rebuy(host["id"], 250)
check(host["stack"] == 250, f"la recarga no funciono: {host['stack']}")
room.start_game(host["id"])
try:
    room.rebuy(host["id"], 5)
    errores.append("se permitio recargar durante una partida en curso")
except GameError:
    pass

# --- 7. si alguien se va y esta el relleno automatico, entra un bot
room, host = nueva_mesa(variant="holdem", bots=0)
room.settings["auto_fill"] = True
room.set_bots(host["id"], 1)   # para poder empezar la partida
room.start_game(host["id"])
room.remove_player(host["id"])
check(len([p for p in room.players if p.get("is_bot")]) >= 1,
      "no entro un bot en el hueco libre")

if errores:
    print("  ERRORES:")
    for e in errores:
        print("   -", e)
    sys.exit(1)
print("  Bots OK: llenado, juego autonomo, recargas y relleno automatico")
