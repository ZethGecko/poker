"""Pruebas de las reglas de black jack sobre el motor.

Uso: python3 tests/test_blackjack.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.engine import Game  # noqa: E402
from server.hands import Card, blackjack_total, make_deck  # noqa: E402

errores: list[str] = []


def check(cond, msg):
    if not cond:
        errores.append(msg)


def nuevo_juego(n=2, ante=10):
    players = [{
        "id": f"p{i}", "name": f"J{i}", "token": "t", "seat": i, "stack": 1000,
        "ready": True, "connected": True, "color": "#fff", "stats": {},
        "bet": 0, "folded": False, "all_in": False, "cards": [],
        "total_contrib": 0, "last_action": None, "revealed": False,
    } for i in range(n)]
    return Game(players, variant="blackjack", small_blind=ante, big_blind=ante)


def fijar_cartas(game, cartas):
    """Reparte cartas concretas a cada jugador."""
    for p in game.players:
        p["cards"] = list(cartas[p["id"]])
        p["total"] = blackjack_total(p["cards"])
        p["natural"] = len(p["cards"]) == 2 and p["total"] == 21


def fijar_mazo(game, cartas):
    """Fuerza el orden del mazo: la primera carta de la lista es la siguiente."""
    game.deck = list(reversed(cartas))


def mazo_para(asignaciones):
    """Construye el mazo para que cada jugador reciba sus cartas concretas."""
    orden = []
    for i in range(2):
        for pid in asignaciones:
            orden.append(asignaciones[pid][i])
    return list(reversed(orden))


def mazo_con(asignaciones):
    usadas = [c for cartas in asignaciones.values() for c in cartas]
    relleno = [c for c in make_deck() if c not in usadas]
    return relleno + mazo_para(asignaciones)


class MazoFijo:
    """Baraja que no se baraja: permite controlar el reparto."""

    def __init__(self, cartas):
        self.cartas = cartas

    def shuffle(self, deck):
        deck[:] = self.cartas


def preparar(game):
    game.start_hand()
    # se vacian las fichas para controlar el bote y se reinicia la mano
    for p in game.players:
        p["stack"] = 1000
        p["bet"] = 0
        p["total_contrib"] = 0
    game.pot = 0
    game.result = None
    game.phase = "betting"
    game.to_act = None
    return game


# --- 1. el reparto: 2 cartas y un ante para cada uno
g = nuevo_juego(3, ante=15)
g.rng = MazoFijo(mazo_con({
    "p0": [Card(10, "s"), Card(5, "h")],
    "p1": [Card(9, "c"), Card(7, "d")],
    "p2": [Card(8, "s"), Card(6, "h")],
}))
g.start_hand()
check(all(len(p["cards"]) == 2 for p in g.players), "no se repartieron 2 cartas a cada uno")
check(g.pot == 45, f"el ante no es 15 x 3 (pot={g.pot})")
check(g.phase == "betting", f"la mano deberia estar en juego (fase={g.phase})")
check(all(p["total"] > 0 for p in g.players), "alguien se quedo sin total")

# --- 2. pedir carta mantiene el turno; plantarse lo pasa
g = preparar(nuevo_juego(2, ante=10))
fijar_cartas(g, {"p0": [Card(10, "s"), Card(5, "h")], "p1": [Card(8, "c"), Card(6, "d")]})
fijar_mazo(g, [Card(4, "d")])
g.to_act = "p0"
antes = len(g.player("p0")["cards"])
g.act("p0", "hit")
check(len(g.player("p0")["cards"]) == antes + 1, "pedir carta no repartio carta")
check(g.to_act == "p0", "tras pedir carta debe seguir jugando el mismo")
g.act("p0", "stand")
check(g.to_act == "p1", "tras plantarse le toca al siguiente")
check(g.player("p0")["stood"], "el jugador no quedo plantado")

# --- 3. pasarse (>21) es el final de la mano
g = preparar(nuevo_juego(2, ante=10))
fijar_cartas(g, {"p0": [Card(10, "s"), Card(10, "h")], "p1": [Card(9, "c"), Card(7, "d")]})
fijar_mazo(g, [Card(5, "d")])
g.to_act = "p0"
g.act("p0", "hit")
check(g.player("p0")["busted"], "no se marco como pasado")
check(g.player("p0")["total"] == 25, f"total inesperado tras pedir carta: {g.player('p0')['total']}")

# --- 4. 21 natural: gana al instante
g = nuevo_juego(2, ante=10)
g.rng = MazoFijo(mazo_con({
    "p0": [Card(14, "s"), Card(10, "h")],   # 21 natural
    "p1": [Card(13, "c"), Card(8, "d")],    # 18
}))
g.start_hand()
check(g.phase == "hand_over", "el 21 natural deberia terminar la mano")
check(g.result["winners"] == ["p0"], f"ganador inesperado: {g.result.get('winners')}")
check(g.result["hands"]["p0"]["natural"], "no se marco como 21 natural")
check(g.result["hands"]["p0"]["total"] == 21, "el total del 21 natural no es 21")

# --- 5. gana el mas cercano a 21 sin pasarse
g = preparar(nuevo_juego(3, ante=10))
fijar_cartas(g, {
    "p0": [Card(10, "s"), Card(9, "h")],   # 19
    "p1": [Card(10, "c"), Card(10, "d")],  # 20
    "p2": [Card(8, "c"), Card(5, "d")],    # 13
})
g.to_act = "p0"
g.act("p0", "stand")
g.act("p1", "stand")
g.act("p2", "stand")
check(g.phase == "hand_over", "la mano deberia haber terminado")
check(g.result["winners"] == ["p1"], f"deberia ganar el 20, ganó {g.result.get('winners')}")
check(g.result["payouts"]["p1"] == g.result["pot_total"], "el bote no se entrego entero")

# --- 6. empate: se reparte el bote
g = preparar(nuevo_juego(2, ante=10))
fijar_cartas(g, {"p0": [Card(10, "s"), Card(9, "h")], "p1": [Card(10, "c"), Card(9, "d")]})
g.to_act = "p0"
g.act("p0", "stand")
g.act("p1", "stand")
check(g.result["winners"] == ["p0", "p1"], f"deberia ser empate: {g.result.get('winners')}")
check(g.result["payouts"]["p0"] == g.result["payouts"]["p1"], "el empate no se reparte igual")

# --- 7. todos se pasan: el bote vuelve a cada uno
g = preparar(nuevo_juego(2, ante=10))
fijar_cartas(g, {"p0": [Card(10, "s"), Card(10, "h")], "p1": [Card(9, "c"), Card(9, "d")]})
fijar_mazo(g, [Card(5, "d"), Card(6, "c")])
g.to_act = "p0"
g.act("p0", "hit")
g.act("p1", "hit")
check(g.result["winners"] == [], "no deberia haber ganador si todos se pasan")
check(g.result["pots"][0].get("refund"), "el bote deberia devolverse")
check(g.pot == 0, "el bote quedo sin repartir")
total = sum(p["stack"] for p in g.players)
check(total == 2000, f"las fichas no se conservan: {total}")

# --- 8. el as vale 1 u 11
check(blackjack_total([Card(14, "s"), Card(10, "h")]) == 21, "A+10 deberia ser 21")
check(blackjack_total([Card(14, "s"), Card(9, "h")]) == 20, "A+9 deberia ser 20")
check(blackjack_total([Card(14, "s"), Card(14, "h")]) == 12, "A+A deberia ser 12")
check(blackjack_total([Card(13, "s"), Card(13, "h")]) == 20, "K+K deberia ser 20")
check(blackjack_total([Card(12, "s"), Card(11, "h"), Card(10, "d")]) == 30, "las figuras valen 10")

if errores:
    print("  ERRORES:")
    for e in errores:
        print("   -", e)
    sys.exit(1)
print("  BlackJack OK: reparto, turnos, 21 natural, ganador, empate y devoluciones")
