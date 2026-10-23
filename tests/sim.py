"""Simulador headless: juega miles de manos con bots aleatorios y verifica invariantes.

Uso: python3 tests/sim.py [manos] [jugadores] [variante]
"""

from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.engine import Game, GameError  # noqa: E402

TOTAL_CHIPS = 1000 * 6


def make_players(n: int) -> list:
    return [{
        "id": f"p{i}", "name": f"J{i}", "token": "t", "seat": i, "stack": 1000,
        "ready": True, "connected": True, "color": "#fff", "stats": {},
        "bet": 0, "folded": False, "all_in": False, "cards": [],
        "total_contrib": 0, "last_action": None, "revealed": False,
    } for i in range(n)]


def play_hand(game: Game, rng: random.Random) -> None:
    game.start_hand()
    guard = 0
    while True:
        if game.variant == "blackjack":
            if game.phase != "betting":
                break
            guard += 1
            if guard > 500:
                raise AssertionError("bucle infinito en el black jack")
            pid = game.to_act
            assert pid, "no hay jugador en turno"
            legal = game.legal_actions(pid)
            assert legal, "el jugador en turno no tiene acciones legales"
            total = legal.get("total", 0)
            if total < 17 and rng.random() < 0.75:
                game.act(pid, "hit")
            elif rng.random() < 0.05:
                game.act(pid, "fold")
            else:
                game.act(pid, "stand")
            continue
        if game.phase == "discard":
            for pid in list(game.discard_requests):
                n_cards = len(game.player(pid)["cards"])
                n = rng.randint(0, min(2, n_cards))
                idxs = rng.sample(range(n_cards), n)
                game.submit_discard(pid, idxs)
            continue
        if game.phase != "betting":
            break
        guard += 1
        if guard > 500:
            raise AssertionError("bucle infinito en la ronda de apuestas")
        pid = game.to_act
        assert pid, "no hay jugador en turno"
        legal = game.legal_actions(pid)
        assert legal, "el jugador en turno no tiene acciones legales"
        choice = rng.random()
        if legal["bet"] and choice < 0.25:
            lo, hi = legal["bet"]["min"], legal["bet"]["max"]
            amount = rng.choice([lo, hi, rng.randint(lo, hi)])
            game.act(pid, "bet", amount)
        elif legal["raise"] and choice < 0.45:
            lo, hi = legal["raise"]["min"], legal["raise"]["max"]
            amount = rng.choice([lo, hi, rng.randint(lo, hi)])
            game.act(pid, "raise", amount)
        elif legal["to_call"] > 0 and choice < 0.85:
            game.act(pid, "call")
        elif legal["check"]:
            game.act(pid, "check")
        else:
            game.act(pid, "fold")

    assert game.phase == "hand_over", f"fase inesperada: {game.phase}"


def check_invariants(game: Game, players: list, total: int) -> None:
    chips = sum(p["stack"] for p in players) + game.pot
    assert chips == total, f"fichas descuadradas: {chips} != {total}"


def main() -> None:
    hands = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    n_players = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    variant = sys.argv[3] if len(sys.argv) > 3 else "holdem"
    rng = random.Random(1234)

    players = make_players(n_players)
    game = Game(players, variant=variant, small_blind=10, big_blind=20, start_stack=1000)
    total = 1000 * n_players
    errors = 0
    for i in range(hands):
        # los que se quedan sin fichas vuelven a comprar (como en una mesa real)
        added = 0
        for p in players:
            if p["stack"] == 0:
                p["stack"] = 1000
                p["all_in"] = False
                p["folded"] = False
                p["cards"] = []
                added += 1000
        total += added
        try:
            play_hand(game, rng)
            check_invariants(game, players, total)
        except GameError as exc:
            if "fichas" in str(exc):
                continue
            print(f"ERROR mano {i}: {exc}")
            errors += 1
        except AssertionError as exc:
            print(f"INVARIANTE roto en la mano {i}: {exc}")
            errors += 1
    print(f"variante={variant} jugadores={n_players} manos={hands} errores={errors}")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
