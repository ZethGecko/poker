"""Evaluacion de manos de poker y utilidades de baraja.

Ranking usado (de mejor a peor):
  9 Escalera Real | 8 Escalera de Color | 7 Poker (4 de un tipo) | 6 Full House
  5 Color | 4 Escalera | 3 Trio | 2 Doble Pareja | 1 Pareja | 0 Carta Alta
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass
from itertools import combinations
from typing import Dict, List, Optional, Sequence, Tuple

RANK_LABELS: Dict[int, str] = {
    2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8",
    9: "9", 10: "T", 11: "J", 12: "Q", 13: "K", 14: "A",
}

RANK_NAMES: Dict[int, str] = {
    2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8", 9: "9",
    10: "10", 11: "J", 12: "Q", 13: "K", 14: "A",
}

SUIT_SYMBOLS: Dict[str, str] = {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}
SUIT_NAMES: Dict[str, str] = {"s": "picas", "h": "corazones", "d": "diamantes", "c": "tréboles"}


@dataclass(frozen=True)
class Card:
    rank: int  # 2..14 (14 = As)
    suit: str  # 's' | 'h' | 'd' | 'c'

    def to_json(self) -> dict:
        return {"r": self.rank, "s": self.suit}

    @property
    def label(self) -> str:
        return RANK_LABELS[self.rank]

    @property
    def symbol(self) -> str:
        return SUIT_SYMBOLS[self.suit]

    @property
    def name(self) -> str:
        return f"{RANK_NAMES[self.rank]} de {SUIT_NAMES[self.suit]}"

    def __str__(self) -> str:  # pragma: no cover - debug helper
        return f"{self.label}{self.symbol}"


def make_deck() -> List[Card]:
    return [Card(rank, suit) for suit in SUIT_SYMBOLS for rank in RANK_LABELS]


def shuffled_deck(rng: random.Random | None = None, decks: int = 1) -> List[Card]:
    """Baraja barajada. Con varias barajas se reparten mas cartas (5-card draw)."""
    deck = make_deck() * max(1, int(decks))
    (rng or random).shuffle(deck)
    return deck


def evaluate5(cards: Sequence[Card]) -> Tuple[int, List[int], str]:
    """Evalua una mano de 5 cartas -> (categoria, desempates, nombre)."""
    counts = Counter(c.rank for c in cards)
    suits = Counter(c.suit for c in cards)
    flush = len(suits) == 1

    ranks = sorted(counts)
    straight_high = 0
    if len(ranks) == 5:
        if ranks[-1] - ranks[0] == 4:
            straight_high = ranks[-1]
        elif ranks == [2, 3, 4, 5, 14]:  # rueda A-2-3-4-5
            straight_high = 5

    four = [r for r, c in counts.items() if c == 4]
    three = [r for r, c in counts.items() if c == 3]
    pairs = sorted([r for r, c in counts.items() if c == 2], reverse=True)

    if flush and straight_high:
        if straight_high == 14:
            return 9, [14], "Escalera Real"
        return 8, [straight_high], "Escalera de Color"
    if four:
        quad = four[0]
        kicker = max(r for r in counts if r != quad)
        return 7, [quad, kicker], "Póker"
    if three and pairs:
        return 6, [three[0], pairs[0]], "Full House"
    if flush:
        return 5, sorted(counts, reverse=True), "Color"
    if straight_high:
        return 4, [straight_high], "Escalera"
    if three:
        trio = three[0]
        kickers = sorted([r for r in counts if r != trio], reverse=True)
        return 3, [trio] + kickers, "Trío"
    if len(pairs) == 2:
        hi, lo = pairs
        kicker = max(r for r in counts if r not in pairs)
        return 2, [hi, lo, kicker], "Doble Pareja"
    if len(pairs) == 1:
        pair = pairs[0]
        kickers = sorted([r for r in counts if r != pair], reverse=True)
        return 1, [pair] + kickers, "Pareja"
    return 0, sorted(counts, reverse=True), "Carta Alta"


def best_of(cards: Sequence[Card]) -> Tuple[Tuple[int, List[int], str], List[Card]]:
    """Mejor combinacion de 5 cartas dentro de 5, 6 o 7 cartas."""
    if len(cards) == 5:
        return evaluate5(cards), list(cards)
    best_eval: Tuple[int, List[int], str] | None = None
    best_cards: List[Card] = []
    for combo in combinations(cards, 5):
        ev = evaluate5(combo)
        if best_eval is None or (ev[0], ev[1]) > (best_eval[0], best_eval[1]):
            best_eval = ev
            best_cards = list(combo)
    assert best_eval is not None
    return best_eval, best_cards


def blackjack_total(cards: Sequence[Card]) -> int:
    """Total de una mano de black jack: el as vale 1 u 11, las figuras valen 10."""
    total = 0
    aces = 0
    for c in cards:
        if c.rank == 14:
            aces += 1
            total += 1
        elif c.rank >= 10:
            total += 10
        else:
            total += c.rank
    # solo un as puede valer 11 (dos serian 22)
    if aces and total + 10 <= 21:
        total += 10
    return total


def evaluate_golpes(cards: Sequence[Card]) -> Tuple[int, List[int], str]:
    """Evalua una mano para el juego de Golpes: 1 = Trio, 2 = Escalera, 0 = Ninguno."""
    if len(cards) != 3:
        return 0, [], ""
    
    ranks = [c.rank for c in cards]
    suits = [c.suit for c in cards]
    
    # Verificar trío: 3 cartas del mismo valor, palos diferentes
    if len(set(ranks)) == 1:
        return 1, ranks, "Trío"
    
    # Verificar escalera: 3 cartas consecutivas del mismo palo
    if len(set(suits)) == 1:
        sorted_ranks = sorted(ranks)
        if len(set(sorted_ranks)) == 3:
            is_consecutive = (sorted_ranks[2] - sorted_ranks[1] == 1 and 
                            sorted_ranks[1] - sorted_ranks[0] == 1)
            if is_consecutive:
                return 2, sorted_ranks, "Escalera"
    
    return 0, [], ""


def get_golpes_groups(cards: Sequence[Card]) -> List[Tuple[int, List[int], str]]:
    """Encuentra todas las combinaciones válidas de 3 cartas en una mano para Golpes."""
    groups = []
    
    for combo in combinations(cards, 3):
        grupo = evaluate_golpes(combo)
        if grupo[0] > 0:  # Es un trío o escalera válido
            groups.append(grupo)
    
    return groups


def has_golpes_win(cards: Sequence[Card]) -> bool:
    """Verifica si una mano tiene 2 grupos válidos + 1 extra para ganar en Golpes."""
    if len(cards) < 4:
        return False
    
    # Encontrar dos grupos válidos no superpuestos
    # Iterar sobre todas las combinaciones posibles de 3 cartas para el primer grupo
    for combo1 in combinations(cards, 3):
        grupo1 = evaluate_golpes(combo1)
        if grupo1[0] > 0:  # Primer grupo válido
            # Crear lista de cartas restantes
            remaining = list(cards)
            for c in combo1:
                remaining.remove(c)
            
            # Verificar si el resto puede formar un segundo grupo válido
            for combo2 in combinations(remaining, 3):
                grupo2 = evaluate_golpes(combo2)
                if grupo2[0] > 0:  # Segundo grupo válido
                    # Encontramos dos grupos no superpuestos
                    return True
    
    return False


def get_golpes_winning_combination(cards: Sequence[Card]) -> Optional[List[Card]]:
    """Devuelve la primera combinación ganadora de 3 cartas que forma una combinación de win."""
    all_groups = get_golpes_groups(cards)
    
    if len(all_groups) >= 2:
        # Encontrar 2 grupos que no se solapan
        for i, group1 in enumerate(all_groups):
            # Obtener las cartas de este grupo (necesitamos las cartas reales, no solo eval)
            # Como get_golpes_groups devuelve solo la evaluación, necesitamos buscar nuevamente
            for combo in combinations(cards, 3):
                grupo = evaluate_golpes(combo)
                if grupo[0] == group1[0]:
                    # Encontrado un grupo del mismo tipo
                    remaining = list(cards)
                    remaining.remove(combo[0])
                    remaining.remove(combo[1])
                    remaining.remove(combo[2])
                    
                    # Verificar si el resto también forma un grupo válido
                    for combo2 in combinations(remaining, 3):
                        if combo2[0] in remaining and combo2[1] in remaining and combo2[2] in remaining:
                            grupo2 = evaluate_golpes(combo2)
                            if grupo2[0] > 0:
                                # Devolver las 6 cartas ganadoras + 1 extra
                                return list(combo) + list(combo2) + [remaining[0]] if remaining else list(combo) + list(combo2)
    
    return None


CATEGORY_NAMES: Dict[int, str] = {
    0: "Carta Alta", 1: "Pareja", 2: "Doble Pareja", 3: "Trío", 4: "Escalera",
    5: "Color", 6: "Full House", 7: "Póker", 8: "Escalera de Color", 9: "Escalera Real",
}
