"""Bots: decisiones simples pero creibles para que la mesa nunca se quede vacia.

No buscan la jugada perfecta, sino jugar como una persona normal: mirar su mano,
avalar las pot odds y arriesgar de vez en cuando.
"""

from __future__ import annotations

import random
from typing import List, Tuple

from .hands import best_of, evaluate5

BOT_NAMES = [
    "Rita", "Hugo", "Nora", "Félix", "Marta", "Bruno", "Lena", "César",
    "Olga", "Pablo", "Vera", "Tino", "Sonia", "Ramiro", "Elsa", "Dani",
    "Irene", "Lucas", "Chelo", "Fermín",
]

# fuerza estimada de cada categoria de poker (0..1)
CATEGORY_STRENGTH = {
    0: 0.18,  # carta alta
    1: 0.44,  # pareja
    2: 0.58,  # doble pareja
    3: 0.70,  # trio
    4: 0.80,  # escalera
    5: 0.84,  # color
    6: 0.92,  # full house
    7: 0.96,  # poker
    8: 1.00,  # escalera de color
    9: 1.00,  # escalera real
}

PREFLOP_PAIRS = {14: 0.84, 13: 0.76, 12: 0.68, 11: 0.60}


def nombre_bot(existentes: List[str]) -> str:
    """Un nombre que no choque con los que ya estan en la mesa."""
    libres = [n for n in BOT_NAMES if n not in existentes]
    if not libres:
        return f"Bot {random.randint(10, 99)}"
    return random.choice(libres)


def fuerza_mano(game, player: dict) -> float:
    """Fuerza estimada de la mano del bot entre 0 y 1."""
    if game.variant == "draw":
        cat, _tie, _name = evaluate5(player["cards"])
        return CATEGORY_STRENGTH.get(cat, 0.3)
    # hold'em
    if len(game.board) >= 3 and player["cards"]:
        ev, _ = best_of(player["cards"] + game.board)
        return CATEGORY_STRENGTH.get(ev[0], 0.25)
    ranks = sorted((c.rank for c in player["cards"]), reverse=True)
    if len(ranks) == 2 and ranks[0] == ranks[1]:
        return PREFLOP_PAIRS.get(ranks[0], 0.44)
    if not ranks:
        return 0.2
    if ranks[0] == 14:
        return 0.56
    if ranks[0] == 13:
        return 0.50
    if ranks[0] == 12:
        return 0.44
    suited = len({c.suit for c in player["cards"]}) == 1
    return 0.40 if suited else 0.33


def decide(game, player: dict) -> Tuple[str, int]:
    """Devuelve la accion del bot: (accion, cantidad)."""
    if game.is_blackjack():
        total = player.get("total", 0)
        if total < 17:
            return ("hit", 0)
        if total == 17 and random.random() < 0.35:
            return ("hit", 0)
        return ("stand", 0)

    legal = game.legal_actions(player["id"])
    if not legal:
        return ("check", 0)

    to_call = legal["to_call"]
    pot = legal["pot"]
    stack = legal["stack"]
    fuerza = fuerza_mano(game, player)

    if to_call == 0:
        # nobody bets: sometimes open with a bet if the hand is good
        if legal.get("bet") and fuerza > 0.70 and random.random() < 0.40:
            lo, hi = legal["bet"]["min"], legal["bet"]["max"]
            cantidad = min(hi, max(lo, int(pot * 0.5) + lo))
            return ("bet", cantidad)
        return ("check", 0)

    # there is a bet on the table
    if legal.get("raise") and fuerza > 0.86 and random.random() < 0.22:
        lo, hi = legal["raise"]["min"], legal["raise"]["max"]
        objetivo = player["bet"] + to_call + int(pot * 0.7)
        return ("raise", min(hi, max(lo, objetivo)))

    if stack > 0 and to_call > stack * 0.35 and fuerza < 0.5:
        return ("fold", 0)

    # pot odds: si la llamada es barata respecto al bote, sigue incluso con mano floja
    if fuerza > 0.40 or to_call <= pot * 0.25:
        return ("call", 0)
    return ("fold", 0)


def choose_discard(game, player: dict) -> List[int]:
    """Cartas que el bot descarta en el 5-card draw (indices de su mano)."""
    cards = player["cards"]
    if len(cards) <= 2:
        return []
    cat, tie, _name = evaluate5(cards)

    if cat in (2, 4, 5, 6, 7):
        # doble pareja, escalera, color, full house o poker: no se descarta nada
        return []
    if cat == 3:
        # trio: quedarse con el trio y un kicker
        keep = set(tie[:2])
    elif cat == 1:
        # pareja: quedarse con la pareja y dos kickers
        keep = set(tie[:3])
    else:
        # carta alta: quedarse con las cuatro mas altas
        keep = set(tie[:4])

    descartar = [i for i, c in enumerate(cards) if c.rank not in keep]
    # a veces se descarta una carta mas, para no ser siempre igual
    if len(descartar) == 1 and random.random() < 0.20:
        extra = [i for i in range(len(cards)) if i not in descartar]
        if extra:
            candidato = min(extra, key=lambda i: cards[i].rank)
            if cards[candidato].rank not in keep:
                descartar.append(candidato)
    return sorted(descartar)
