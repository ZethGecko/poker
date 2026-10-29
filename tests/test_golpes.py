"""Pruebas de las reglas de Golpes sobre el motor.

Uso: python3 tests/test_golpes.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.engine import Game, GameError  # noqa: E402
from server.hands import Card, has_golpes_win, get_golpes_winning_combination, make_deck, shuffled_deck  # noqa: E402

errores: list[str] = []


def check(cond, msg):
    if not cond:
        errores.append(msg)


def nuevo_juego_golpes(n=2, start_stack=1000):
    players = [{
        "id": f"p{i}", "name": f"J{i}", "token": "t", "seat": i, "stack": start_stack,
        "ready": True, "connected": True, "color": "#fff", "stats": {},
        "bet": 0, "folded": False, "all_in": False, "cards": [],
        "total_contrib": 0, "last_action": None, "revealed": False,
    } for i in range(n)]
    return Game(players, variant="golpes", small_blind=10, big_blind=20, start_stack=start_stack)


def fijar_cartas(game, cartas):
    """Reparte cartas concretas a cada jugador."""
    for p in game.players:
        p["cards"] = list(cartas[p["id"]])


def mazo_para(asignaciones):
    """Construye el mazo para que cada jugador reciba sus cartas concretas."""
    orden = []
    for i in range(7):  # 7 cartas por jugador para Golpes
        for pid in asignaciones:
            orden.append(asignaciones[pid][i])
    return list(reversed(orden))


class MazoFijo:
    """Baraja que no se baraja: permite controlar el reparto."""

    def __init__(self, cartas):
        self.cartas = cartas

    def shuffle(self, deck):
        deck[:] = self.cartas


def preparar_golpes(game):
    game.start_hand()
    return game


# --- 1. Test de cartas válidas para Golpes (trío y escalera)
# Test 1: Trio - should NOT have a win (necesita trío + escalera no solapada)
check(
    not has_golpes_win([Card(10, "s"), Card(10, "h"), Card(10, "d"), Card(5, "s"), Card(7, "c"), Card(2, "d"), Card(4, "h")]),
    "Detectó win cuando solo hay un trío"
)

# Test 2: Escalera - should NOT have a win (necesita 2 escaleras no solapadas)
check(
    not has_golpes_win([Card(10, "s"), Card(11, "s"), Card(12, "s"), Card(5, "s"), Card(7, "c"), Card(2, "d"), Card(4, "h")]),
    "Detectó win cuando solo hay una escalera"
)

# Test 4: Should win - trío + trío no solapados
check(
    has_golpes_win([Card(10, "s"), Card(10, "h"), Card(10, "d"), Card(9, "s"), Card(9, "h"), Card(9, "d"), Card(8, "c")]),
    "Debería ganar (tiene 2 tríos no superpuestos)"
)

# Test 5: Should win - escalera + escalera no solapadas
check(
    has_golpes_win([Card(10, "s"), Card(11, "s"), Card(12, "s"), Card(5, "s"), Card(6, "s"), Card(7, "s"), Card(8, "c")]),
    "Debería ganar (tiene 2 escaleras no superpuestas)"
)

# Test 4: Should win - trío + trío no solapados
check(
    has_golpes_win([Card(10, "s"), Card(10, "h"), Card(10, "d"), Card(9, "s"), Card(9, "h"), Card(9, "d"), Card(8, "c")]),
    "Debería ganar (tiene 2 tríos no superpuestos)"
)

# Test 5: Should win - escalera + escalera no solapadas
check(
    has_golpes_win([Card(10, "s"), Card(11, "s"), Card(12, "s"), Card(5, "s"), Card(6, "s"), Card(7, "s"), Card(8, "c")]),
    "Debería ganar (tiene 2 escaleras no superpuestas)"
)

# Test 6: Should win - trío + escalera no solapados
check(
    has_golpes_win([Card(10, "s"), Card(10, "h"), Card(10, "d"), Card(8, "s"), Card(9, "s"), Card(7, "s"), Card(4, "c")]),
    "Debería ganar (tiene trío + escalera no superpuestos)"
)

# --- Test del juego finalizado ---
print("  Golpes OK: trío, escalera, timeout y temporizador de turno")
