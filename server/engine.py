"""Motor de mesa: Texas Hold'em, 5-Card Draw y BlackJack (todo en memoria)."""

from __future__ import annotations

import math
import random
import time
from typing import Any, Dict, List, Optional, Sequence

from .hands import Card, best_of, evaluate5, shuffled_deck, blackjack_total


class GameError(Exception):
    """Error de reglas (turno incorrecto, apuesta invalida, etc.)."""


STREET_PLANS: Dict[str, List[tuple]] = {
    # (tipo, nombre) -> tipo 'bet' = ronda de apuestas, 'discard' = eleccion de descarte
    "holdem": [("bet", "preflop"), ("bet", "flop"), ("bet", "turn"), ("bet", "river")],
    "draw": [("bet", "preflop"), ("discard", "discard"), ("bet", "final")],
    "blackjack": [("bet", "blackjack")],
}

STREET_LABELS = {
    "preflop": "Pre-flop",
    "flop": "Flop",
    "turn": "Turn",
    "river": "River",
    "discard": "Descarte",
    "final": "Ronda final",
    "blackjack": "BlackJack",
}

ACTION_LABELS = {
    "fold": "se retira",
    "check": "pasa",
    "call": "iguala",
    "bet": "apuesta",
    "raise": "sube",
    "allin": "va all-in",
    "post": "pone",
    "hit": "pide carta",
    "stand": "se planta",
    "bust": "se pasa de 21",
}


class Game:
    """Estado completo de la mesa. Comparte la lista de jugadores con la sala."""

    def __init__(
        self,
        players: List[dict],
        variant: str = "holdem",
        small_blind: int = 10,
        big_blind: int = 20,
        start_stack: int = 1000,
        seed: Optional[int] = None,
    ) -> None:
        self.players = players
        self.variant = variant if variant in STREET_PLANS else "holdem"
        self.small_blind = int(small_blind)
        self.big_blind = int(big_blind)
        self.start_stack = int(start_stack)
        self.rng = random.Random(seed)

        self.deck: List[Card] = []
        self.board: List[Card] = []
        self.pot = 0
        self.pots: List[dict] = []
        self.button_index = -1
        self.hand_number = 0
        self.street = 0
        self.phase = "idle"  # idle | betting | discard | showdown | hand_over
        self.current_bet = 0
        self.min_raise = self.big_blind
        self.acted: set[str] = set()
        self.to_act: Optional[str] = None
        self.last_aggressor: Optional[str] = None
        self.result: Optional[dict] = None
        self.discard_requests: Dict[str, List[int]] = {}
        self._discard_done: set[str] = set()
        self.last_winner: Optional[str] = None

    # ------------------------------------------------------------------ util
    def is_blackjack(self) -> bool:
        return self.variant == "blackjack"

    def player(self, pid: str) -> dict:
        for p in self.players:
            if p["id"] == pid:
                return p
        raise GameError("Jugador no encontrado")

    def index_of(self, pid: str) -> int:
        for i, p in enumerate(self.players):
            if p["id"] == pid:
                return i
        raise GameError("Jugador no encontrado")

    def live_players(self) -> List[dict]:
        return [p for p in self.players if p["stack"] > 0]

    def contenders(self) -> List[dict]:
        """Jugadores que siguen en la mano y pueden seguir apostando."""
        return [p for p in self.players
                if not p["folded"] and not p["all_in"] and p["stack"] > 0]

    def in_hand(self) -> List[dict]:
        """Jugadores que aun pueden ganar algo (incluye los que estan all-in)."""
        return [p for p in self.players
                if not p["folded"] and (p["all_in"] or p["stack"] > 0)]

    def street_name(self) -> str:
        plan = STREET_PLANS[self.variant]
        if self.street >= len(plan):
            return "Showdown"
        return STREET_LABELS[plan[self.street][1]]

    # ------------------------------------------------------------- baraja
    def _deal(self, n: int) -> List[Card]:
        dealt = []
        for _ in range(n):
            if not self.deck:
                raise GameError("Se ha agotado la baraja")
            dealt.append(self.deck.pop())
        return dealt

    def _deal_hole_cards(self) -> None:
        count = 5 if self.variant == "draw" else 2
        for _ in range(count):
            for p in self.live_players():
                p["cards"].append(self._deal(1)[0])

    def _commit(self, p: dict, amount: int) -> int:
        amount = max(0, min(int(amount), p["stack"]))
        p["stack"] -= amount
        p["bet"] += amount
        p["total_contrib"] += amount
        self.pot += amount
        if p["stack"] == 0:
            p["all_in"] = True
        return amount

    # --------------------------------------------------------- ciclo de mano
    def start_hand(self) -> None:
        if self.is_blackjack():
            return self._start_blackjack_hand()
        eligible = self.live_players()
        if len(eligible) < 2:
            raise GameError("Se necesitan al menos 2 jugadores con fichas")

        # en 5-card draw hacen falta hasta 5 cartas de replacement por jugador:
        # se usan varias barajas si un solo mazo no da para todos
        decks = 1
        if self.variant == "draw":
            decks = max(1, math.ceil(len(self.live_players()) * 10 / 52))
        self.deck = shuffled_deck(self.rng, decks)
        self.board = []
        self.pot = 0
        self.pots = []
        self.result = None
        self.last_winner = None
        self.hand_number += 1
        self.street = 0
        self.discard_requests = {}
        self._discard_done = set()

        for p in self.players:
            p.update(
                bet=0, folded=False, all_in=False, cards=[],
                total_contrib=0, last_action=None, revealed=False,
            )

        self._rotate_button()
        # se reparten las cartas antes de las ciegas: asi los all-in cortos
        # (stack menor que la ciega) tambien reciben su mano
        self._deal_hole_cards()
        self._post_blinds()
        self._start_betting_round("preflop")
        # la apuesta vigente en pre-flop es la ciega grande
        self.current_bet = max((p["bet"] for p in self.players), default=0)
        self.phase = "betting"

    # ------------------------------------------------------------- black jack
    def _start_blackjack_hand(self) -> None:
        """BlackJack: dos cartas por jugador, ante para todos y luego pedir o plantarse."""
        eligible = self.live_players()
        if len(eligible) < 2:
            raise GameError("Se necesitan al menos 2 jugadores con fichas")
        # una mano puede alargarse mucho (muchos ases): mejor varias barajas
        decks = max(1, math.ceil(len(eligible) * 16 / 52))
        self.deck = shuffled_deck(self.rng, decks)
        self.board = []
        self.pot = 0
        self.pots = []
        self.result = None
        self.last_winner = None
        self.hand_number += 1
        self.street = 0
        self.discard_requests = {}
        self._discard_done = set()

        for p in self.players:
            p.update(
                bet=0, folded=False, all_in=False, cards=[],
                total_contrib=0, last_action=None, revealed=False,
                stood=False, busted=False, total=0, natural=False,
            )

        self._rotate_button()
        for _ in range(2):
            for p in self.live_players():
                p["cards"].append(self._deal(1)[0])

        ante = max(1, self.small_blind)
        for p in self.live_players():
            self._commit(p, ante)
            p["last_action"] = "post"
            p["total"] = blackjack_total(p["cards"])
            p["natural"] = len(p["cards"]) == 2 and p["total"] == 21
            if p["all_in"]:
                p["stood"] = True  # sin fichas no puede pedir mas cartas

        naturals = [p for p in self.live_players() if p["natural"]]
        if naturals:
            # 21 natural: gana al instante
            for p in naturals:
                p["stood"] = True
            self._showdown_blackjack()
            return

        self.phase = "betting"
        self.current_bet = 0
        self.min_raise = 0
        self.acted = set()
        self.to_act = self._first_to_act("blackjack")

    def _legal_blackjack(self, pid: str) -> dict:
        p = self.player(pid)
        return {
            "fold": True, "hit": True, "stand": True,
            "check": False, "call": 0, "to_call": 0,
            "bet": None, "raise": None,
            "stack": p["stack"], "pot": self.pot,
            "total": p["total"], "cards": len(p["cards"]),
        }

    def _act_blackjack(self, pid: str, action: str) -> dict:
        p = self.player(pid)
        if action == "fold":
            p["folded"] = True
            p["last_action"] = "fold"
        elif action == "stand":
            p["stood"] = True
            p["last_action"] = "stand"
        elif action == "hit":
            p["cards"].append(self._deal(1)[0])
            p["total"] = blackjack_total(p["cards"])
            if p["total"] > 21:
                p["busted"] = True
                p["last_action"] = "bust"
            elif p["total"] == 21:
                p["stood"] = True
                p["last_action"] = "stand"
            else:
                p["last_action"] = "hit"
        else:
            raise GameError("Accion desconocida")

        # el que pide carta sigue jugando hasta plantarse o pasarse
        if p["last_action"] != "hit":
            self._advance_blackjack_turn()
        if self._blackjack_done():
            self._showdown_blackjack()
        return {"action": action, "amount": 0, "total": p["total"]}

    def _advance_blackjack_turn(self) -> None:
        n = len(self.players)
        idx = self.index_of(self.to_act) if self.to_act else self.button_index
        for step in range(1, n + 1):
            cand = self.players[(idx + step) % n]
            if (cand["folded"] or cand["all_in"] or cand["stood"]
                    or cand["busted"] or cand["stack"] <= 0):
                continue
            self.to_act = cand["id"]
            return
        self.to_act = None

    def _blackjack_done(self) -> bool:
        for p in self.players:
            if p["folded"] or p["stood"] or p["busted"] or p["all_in"]:
                continue
            return False
        return True

    def _showdown_blackjack(self) -> None:
        """Gana el que mas se acerca a 21 sin pasarse; los empates se reparten."""
        self.phase = "hand_over"
        self.to_act = None
        alive = [p for p in self.players if not p["folded"]]
        hands: Dict[str, dict] = {}
        for p in alive:
            total = p["total"]
            if p["natural"]:
                name = "BlackJack natural"
            elif total > 21:
                name = f"{total} · se pasó"
            else:
                name = f"{total} puntos"
            hands[p["id"]] = {
                "cat": 100,
                "name": name,
                "tie": [total, 1 if p["natural"] else 0],
                "best": [],
                "cards": [c.to_json() for c in p["cards"]],
                "total": total,
                "bust": total > 21,
                "natural": p["natural"],
            }

        def rank(p: dict) -> tuple:
            return (p["total"], 1 if p["natural"] else 0)

        valid = [p for p in alive if p["total"] <= 21]
        winners: List[dict] = []
        if valid:
            best = max(rank(p) for p in valid)
            winners = [p for p in valid if rank(p) == best]

        pot = self.pot
        payouts: Dict[str, int] = {}
        details: List[dict] = []
        if winners:
            share = pot // len(winners)
            rest = pot - share * len(winners)
            for i, p in enumerate(winners):
                amount = share + (rest if i == 0 else 0)
                p["stack"] += amount
                payouts[p["id"]] = amount
            details.append({
                "amount": pot, "winners": [p["id"] for p in winners],
                "label": "Bote", "split": len(winners) > 1,
            })
        else:
            # todos se pasaron: cada uno recupera su ante
            contributors = [p for p in self.players if p["total_contrib"] > 0]
            if contributors:
                share = pot // len(contributors)
                rest = pot - share * len(contributors)
                for i, p in enumerate(contributors):
                    amount = share + (rest if i == 0 else 0)
                    p["stack"] += amount
                    payouts[p["id"]] = amount
            details.append({
                "amount": pot, "winners": [], "label": "Bote devuelto", "refund": True,
            })

        for p in alive:
            p["revealed"] = True
        for p in winners:
            hands[p["id"]]["best"] = hands[p["id"]]["cards"]

        self.pot = 0
        self.pots = []
        self.result = {
            "type": "blackjack",
            "pot_total": pot,
            "pots": details,
            "hands": hands,
            "payouts": payouts,
            "winners": [p["id"] for p in winners],
        }
        self.last_winner = winners[0]["id"] if winners else None

    def _rotate_button(self) -> None:
        n = len(self.players)
        if n == 0:
            return
        for step in range(1, n + 1):
            idx = (self.button_index + step) % n
            if self.players[idx]["stack"] > 0:
                self.button_index = idx
                return

    def button_player(self) -> Optional[dict]:
        if 0 <= self.button_index < len(self.players):
            return self.players[self.button_index]
        return None

    def _post_blinds(self) -> None:
        live = self.live_players()
        n = len(live)
        if n == 2:
            sb = self.button_player() or live[0]
            bb = live[1] if live[1]["id"] != sb["id"] else live[0]
        else:
            sb = self._next_with_chips(self.button_index)
            bb = self._next_with_chips(self.index_of(sb["id"]))
        self._sb_id = sb["id"]
        self._bb_id = bb["id"]
        self._commit(sb, self.small_blind)
        sb["last_action"] = "post"
        self._commit(bb, self.big_blind)
        bb["last_action"] = "post"

    def _next_with_chips(self, idx: int) -> dict:
        n = len(self.players)
        for step in range(1, n + 1):
            cand = self.players[(idx + step) % n]
            if cand["stack"] > 0:
                return cand
        raise GameError("No hay jugadores con fichas")

    def _first_to_act(self, street: str) -> Optional[str]:
        """Primer jugador en actuar de la ronda."""
        contenders = [p for p in self.players if not p["folded"] and not p["all_in"]]
        if not contenders:
            return None
        if street == "preflop":
            start = self.index_of(self._bb_id) if getattr(self, "_bb_id", None) else self.button_index
        else:
            start = self.button_index
        n = len(self.players)
        for step in range(1, n + 1):
            cand = self.players[(start + step) % n]
            if not cand["folded"] and not cand["all_in"] and cand["stack"] > 0:
                return cand["id"]
        return None

    def _start_betting_round(self, street: str) -> None:
        self.current_bet = 0
        self.min_raise = self.big_blind
        self.acted = set()
        self.to_act = self._first_to_act(street)
        self.phase = "betting"

    # ------------------------------------------------------------- acciones
    def legal_actions(self, pid: str) -> Optional[dict]:
        if self.phase != "betting" or self.to_act != pid:
            return None
        p = self.player(pid)
        if self.is_blackjack():
            return self._legal_blackjack(pid)
        stack = p["stack"]
        to_call = max(0, self.current_bet - p["bet"])
        res: Dict[str, Any] = {
            "fold": True,
            "check": to_call == 0,
            "call": 0,
            "to_call": to_call,
            "stack": stack,
            "pot": self.pot,
            "bet": None,
            "raise": None,
        }
        if to_call > 0:
            res["call"] = min(to_call, stack)
        contenders = self.contenders()
        can_open = len(contenders) > 1 or self.current_bet == 0
        if stack > 0 and can_open:
            if self.current_bet == 0:
                res["bet"] = {"min": min(self.big_blind, stack), "max": stack, "total": False}
            elif pid not in self.acted:
                min_to = self.current_bet + self.min_raise
                max_to = p["bet"] + stack
                res["raise"] = {"min": min(min_to, max_to), "max": max_to, "total": True}
        return res

    def act(self, pid: str, action: str, amount: int = 0) -> dict:
        if self.phase != "betting":
            raise GameError("No se puede actuar ahora")
        if self.to_act != pid:
            raise GameError("No es tu turno")
        p = self.player(pid)
        if p["folded"] or p["all_in"]:
            raise GameError("Ya no puedes actuar")
        if self.is_blackjack():
            return self._act_blackjack(pid, action)

        info: Dict[str, Any] = {"action": action, "amount": 0}

        if action == "fold":
            p["folded"] = True
            p["last_action"] = "fold"
        elif action == "check":
            if self.current_bet > p["bet"]:
                raise GameError("Debes igualar la apuesta antes de pasar")
            p["last_action"] = "check"
        elif action == "call":
            due = min(self.current_bet - p["bet"], p["stack"])
            if due > 0 and p["stack"] == 0:
                raise GameError("No tienes fichas")
            self._commit(p, due)
            info["amount"] = due
            p["last_action"] = "allin" if p["all_in"] else "call"
        elif action in ("bet", "raise"):
            total = int(amount)
            if total <= 0:
                raise GameError("Cantidad invalida")
            if action == "bet":
                if self.current_bet != 0:
                    raise GameError("Ya hay una apuesta en esta ronda")
                min_total = min(self.big_blind, p["stack"])
                if total < min_total:
                    raise GameError(f"Apuesta minima: {min_total}")
            else:
                if self.current_bet == 0:
                    raise GameError("No hay nada que subir")
                if pid in self.acted:
                    raise GameError("No puedes subir mas en esta ronda")
                min_total = self.current_bet + self.min_raise
                if total < min_total and total < p["stack"] + p["bet"]:
                    raise GameError(f"Subida minima: {min_total}")
            prev_bet = self.current_bet
            self._commit(p, total - p["bet"])
            info["amount"] = total - prev_bet
            info["total"] = total
            if total > prev_bet:
                raise_size = total - prev_bet
                if raise_size >= self.min_raise:
                    # subida completa: vuelve a abrir las apuestas para todos
                    self.min_raise = raise_size
                    self.acted = {pid}
                else:
                    # all-in corto: no reabre las apuestas a quien ya actuo
                    self.acted = set(self.acted) | {pid}
                self.current_bet = total
                self.last_aggressor = pid
            p["last_action"] = "allin" if p["all_in"] else action
        else:
            raise GameError("Accion desconocida")

        self._after_action()
        return info

    def _after_action(self) -> None:
        """Cierra la ronda si toca y prepara el siguiente turno."""
        self._advance_turn()
        if len(self.in_hand()) <= 1:
            self._finish_by_fold()
            return
        if self._betting_done():
            self._next_street()

    def _betting_done(self) -> bool:
        contenders = self.contenders()
        if len(contenders) <= 1:
            if not contenders:
                return True
            return contenders[0]["bet"] >= self.current_bet
        for p in contenders:
            if p["bet"] != self.current_bet:
                return False
            if p["id"] not in self.acted:
                return False
        return True

    def _advance_turn(self) -> None:
        """Marca la accion del jugador actual y calcula el siguiente."""
        acted = self.to_act
        if acted:
            self.acted.add(acted)
        n = len(self.players)
        idx = self.index_of(acted) if acted else self.button_index
        for step in range(1, n + 1):
            cand = self.players[(idx + step) % n]
            if cand["folded"] or cand["all_in"] or cand["stack"] <= 0:
                continue
            self.to_act = cand["id"]
            return
        self.to_act = None

    def _next_street(self) -> None:
        if len(self.in_hand()) <= 1:
            self._finish_by_fold()
            return
        # la ronda se cierra: las apuestas de la calle pasan al bote
        for p in self.players:
            p["bet"] = 0
        plan = STREET_PLANS[self.variant]
        while True:
            self.street += 1
            if self.street >= len(plan):
                self._showdown()
                return
            kind, name = plan[self.street]
            if kind == "discard":
                if len(self.contenders()) <= 1:
                    continue  # nadie puede descartar: siguiente calle
                self.phase = "discard"
                self.discard_requests = {p["id"]: [] for p in self.in_hand()}
                self._discard_done = set()
                self.to_act = None
                return
            if name == "flop":
                self.board.extend(self._deal(3))
            elif name == "turn":
                self.board.append(self._deal(1)[0])
            elif name == "river":
                self.board.append(self._deal(1)[0])
            if len(self.contenders()) <= 1:
                continue  # nadie puede apostar: siguiente calle
            self._start_betting_round(name)
            return

    # ------------------------------------------------------------ descarte
    def submit_discard(self, pid: str, indexes: Sequence[int]) -> dict:
        if self.phase != "discard":
            raise GameError("No estamos en fase de descarte")
        p = self.player(pid)
        if pid not in self.discard_requests:
            raise GameError("No puedes descartar")
        cards = p["cards"]
        idxs = sorted({int(i) for i in indexes})
        if any(i < 0 or i >= len(cards) for i in idxs):
            raise GameError("Carta invalida")
        if len(idxs) > len(cards):
            raise GameError("No puedes descartar mas cartas de las que tienes")
        self.discard_requests[pid] = idxs
        self._discard_done.add(pid)
        if self._discard_done.issuperset(self.discard_requests.keys()):
            self._apply_discards()
        return {"discarded": len(idxs)}

    def _apply_discards(self) -> None:
        for pid, idxs in self.discard_requests.items():
            p = self.player(pid)
            if not idxs:
                continue
            keep = [c for i, c in enumerate(p["cards"]) if i not in idxs]
            new = self._deal(len(idxs))
            p["cards"] = keep + new
        self.discard_requests = {}
        self._discard_done = set()
        self.street += 1
        self._start_betting_round("final")

    def _auto_discard_all(self) -> None:
        for pid in list(self.discard_requests):
            self.discard_requests[pid] = []
            self._discard_done.add(pid)
        self._apply_discards()

    # ------------------------------------------------------------ showdown
    def _build_pots(self) -> List[dict]:
        """Reparte las contribuciones en pozo principal y botes laterales."""
        contrib = {p["id"]: p["total_contrib"] for p in self.players if p["total_contrib"] > 0}
        if not contrib:
            return []
        alive = {p["id"] for p in self.in_hand()}
        levels = sorted(set(contrib.values()))
        pots: List[dict] = []
        prev = 0
        for lvl in levels:
            amount = 0
            eligible: List[str] = []
            contributors: List[str] = []
            for pid, c in contrib.items():
                if c > prev:
                    amount += min(c, lvl) - prev
                    contributors.append(pid)
                    if pid in alive:
                        eligible.append(pid)
            if amount > 0:
                pots.append({
                    "amount": amount, "eligible": eligible,
                    "level": lvl, "contributors": contributors,
                })
            prev = lvl
        return pots

    def _split(self, amount: int, pids: List[str]) -> None:
        """Reparte un bote a partes iguales (el resto va al primero)."""
        if not pids:
            return
        share = amount // len(pids)
        rest = amount - share * len(pids)
        for i, pid in enumerate(pids):
            self.player(pid)["stack"] += share + (rest if i == 0 else 0)

    def _evaluate_player(self, p: dict) -> dict:
        if self.variant == "holdem":
            ev, best = best_of(p["cards"] + self.board)
        else:
            ev, best = best_of(p["cards"])
        return {
            "cat": ev[0],
            "name": ev[2],
            "tie": ev[1],
            "best": [c.to_json() for c in best],
        }

    def _showdown(self) -> None:
        self.phase = "showdown"
        self.to_act = None
        hands = {p["id"]: self._evaluate_player(p) for p in self.in_hand()}
        pots = self._build_pots()
        self.pots = pots
        payouts: Dict[str, int] = {}
        details: List[dict] = []

        for pot in pots:
            eligible = [pid for pid in pot["eligible"]]
            if not eligible:
                # bote sin destinatario (todos se retiraron): se devuelve
                self._split(pot["amount"], pot.get("contributors") or [])
                details.append({
                    "amount": pot["amount"], "winners": [],
                    "label": "Bote devuelto", "refund": True,
                })
                continue
            if len(eligible) == 1:
                # apuesta sin igualar: se devuelve
                winner = eligible[0]
                self.player(winner)["stack"] += pot["amount"]
                payouts[winner] = payouts.get(winner, 0) + pot["amount"]
                details.append({
                    "amount": pot["amount"], "winners": [winner],
                    "label": "Bote sin igualar (devuelto)", "refund": True,
                })
                continue
            best_pid = None
            best_key = None
            for pid in eligible:
                key = (hands[pid]["cat"], hands[pid]["tie"])
                if best_key is None or key > best_key:
                    best_key = key
                    best_pid = pid
            winners = [pid for pid in eligible
                       if (hands[pid]["cat"], hands[pid]["tie"]) == best_key]
            before = {pid: self.player(pid)["stack"] for pid in winners}
            self._split(pot["amount"], winners)
            for pid in winners:
                gained = self.player(pid)["stack"] - before[pid]
                payouts[pid] = payouts.get(pid, 0) + gained
            details.append({
                "amount": pot["amount"], "winners": winners,
                "label": "Bote principal" if len(pots) == 1 else "Bote lateral",
                "split": len(winners) > 1,
            })

        for p in self.in_hand():
            p["revealed"] = True
        self.pot = 0
        self.result = {
            "type": "showdown",
            "pot_total": sum(p["amount"] for p in details),
            "pots": details,
            "hands": hands,
            "payouts": payouts,
            "winners": [pid for pid, amt in payouts.items() if amt > 0],
        }
        self.last_winner = self.result["winners"][0] if self.result["winners"] else None
        self.phase = "hand_over"

    def _finish_by_fold(self) -> None:
        alive = self.in_hand()
        winner = alive[0]["id"] if alive else None
        amount = self.pot
        payouts: Dict[str, int] = {}
        if winner:
            self.player(winner)["stack"] += amount
            payouts[winner] = amount
        else:
            # todos se retiraron: cada uno recupera lo que puso
            contributors = [p for p in self.players if p["total_contrib"] > 0]
            self._split(amount, [p["id"] for p in contributors])
            for p in contributors:
                payouts[p["id"]] = p["total_contrib"]
        self.pot = 0
        self.pots = []
        self.result = {
            "type": "fold_win",
            "pot_total": amount,
            "pots": [{"amount": amount, "winners": [winner] if winner else [], "label": "Bote"}],
            "hands": {},
            "payouts": payouts,
            "winners": [winner] if winner else [],
        }
        self.last_winner = winner
        self.phase = "hand_over"

    # --------------------------------------------------------------- utiles
    def player_left(self, pid: str) -> None:
        """Un jugador abandona la mesa a mitad de mano: le pasa el turno."""
        if len(self.in_hand()) <= 1:
            self._finish_by_fold()
            return
        if self.to_act == pid:
            self.to_act = None
            self._after_action()

    def only_one_left(self) -> bool:
        return len([p for p in self.players if p["stack"] > 0]) <= 1

    def snapshot(self) -> dict:
        return {
            "variant": self.variant,
            "phase": self.phase,
            "street": self.street,
            "street_name": self.street_name(),
            "hand_number": self.hand_number,
            "board": [c.to_json() for c in self.board],
            "pot": self.pot,
            "pots": self.pots,
            "current_bet": self.current_bet,
            "min_raise": self.min_raise,
            "to_act": self.to_act,
            "result": self.result,
            "target": 21 if self.is_blackjack() else None,
            "discard_pending": sorted(
                pid for pid in self.discard_requests if pid not in self._discard_done),
        }
