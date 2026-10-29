"""Salas de juego: estado en memoria, sin base de datos.

Cada sala es efimera: vive en RAM y desaparece cuando todos se van.
El estado se difunde a los clientes mediante Server-Sent Events.
"""

from __future__ import annotations

import queue
import random
import secrets
import threading
import time
from typing import Any, Dict, List, Optional

from . import bot
from .engine import ACTION_LABELS, Game, GameError

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
AVATAR_COLORS = [
    "#e4572e", "#3d8bfd", "#26a69a", "#f2b705", "#8e44ad",
    "#e91e63", "#2ecc71", "#ff8c42", "#00bcd4", "#9c27b0",
]

TURN_SECONDS = 30
NEXT_HAND_DELAY = 10
RECONNECT_GRACE = 600  # segundos que se conserva el asiento

TURN_SECONDS = 30
NEXT_HAND_DELAY = 10
RECONNECT_GRACE = 600  # segundos que se conserva el asiento


def new_code(rng_len: int = 5) -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(rng_len))


class Subscriber:
    """Conexion SSE de un cliente."""

    def __init__(self, pid: str, token: str) -> None:
        self.pid = pid
        self.token = token
        self.queue: "queue.Queue[dict]" = queue.Queue(maxsize=64)
        self.active = True


class Room:
    def __init__(self, code: str) -> None:
        self.code = code
        self.created_at = time.time()
        self.touched_at = time.time()
        self.players: List[dict] = []
        self.host_id: Optional[str] = None
        self.phase = "lobby"  # lobby | playing | finished
        self.settings: Dict[str, Any] = {
            "variant": "holdem",
            "small_blind": 10,
            "big_blind": 20,
            "start_stack": 1000,
            "max_players": 5,
            "bots": 0,
            "auto_fill": False,
            "rebuy": 0,   # 0 = usar el stack inicial
        }
        self.game = self._new_game()
        self.log: List[dict] = []
        self.chat: List[dict] = []
        self.subscribers: List[Subscriber] = []
        self.lock = threading.RLock()
        self._turn_timer: Optional[threading.Timer] = None
        self._next_timer: Optional[threading.Timer] = None
        self._bot_timer: Optional[threading.Timer] = None
        self.turn_deadline: Optional[float] = None
        self._log_seq = 0
        self._chat_seq = 0

    # ------------------------------------------------------------- utilidades
    def _new_game(self) -> Game:
        return Game(
            self.players,
            variant=self.settings["variant"],
            small_blind=self.settings["small_blind"],
            big_blind=self.settings["big_blind"],
            start_stack=self.settings["start_stack"],
        )

    def touch(self) -> None:
        self.touched_at = time.time()

    def player(self, pid: str) -> Optional[dict]:
        for p in self.players:
            if p["id"] == pid:
                return p
        return None

    def authenticate(self, pid: str, token: str) -> Optional[dict]:
        p = self.player(pid)
        if p and secrets.compare_digest(p["token"], token):
            return p
        return None

    def is_host(self, pid: str) -> bool:
        return self.host_id == pid

    # ----------------------------------------------------------------- logs
    def add_log(self, text: str, kind: str = "info", pid: Optional[str] = None) -> None:
        self._log_seq += 1
        self.log.append({
            "id": self._log_seq, "t": time.time(), "kind": kind, "text": text, "pid": pid,
        })
        if len(self.log) > 300:
            del self.log[:-300]

    def add_chat(self, pid: str, text: str) -> dict:
        p = self.player(pid)
        if not p:
            raise GameError("Jugador no encontrado")
        text = text.strip()[:240]
        if not text:
            raise GameError("Mensaje vacio")
        self._chat_seq += 1
        msg = {"id": self._chat_seq, "t": time.time(), "pid": pid, "name": p["name"], "text": text}
        self.chat.append(msg)
        if len(self.chat) > 120:
            del self.chat[:-120]
        return msg

    # ------------------------------------------------------------- jugadores
    def add_player(self, name: str) -> dict:
        name = (name or "").strip()[:18] or "Jugador"
        if len(self.players) >= int(self.settings["max_players"]):
            raise GameError("La mesa esta llena")
        pid = secrets.token_hex(6)
        token = secrets.token_urlsafe(12)
        player = {
            "id": pid,
            "name": name,
            "token": token,
            "seat": len(self.players),
            "stack": int(self.settings["start_stack"]),
            "ready": False,
            "connected": False,
            "color": AVATAR_COLORS[len(self.players) % len(AVATAR_COLORS)],
            "stats": {"hands": 0, "wins": 0, "chips": 0},
            # campos de poker (los usa Game)
            "bet": 0, "folded": False, "all_in": False, "cards": [],
            "total_contrib": 0, "last_action": None, "revealed": False,
        }
        self.players.append(player)
        if self.host_id is None:
            self.host_id = pid
        self.add_log(f"{name} entra en la mesa", "info", pid)
        return player

    def add_bot(self) -> dict:
        """Mete un bot en la mesa."""
        max_p = int(self.settings["max_players"])
        if len(self.players) >= max_p:
            raise GameError("La mesa esta llena")
        nombres = [p["name"] for p in self.players]
        nombre = bot.nombre_bot(nombres)
        player = {
            "id": "bot-" + secrets.token_hex(4),
            "name": nombre,
            "token": secrets.token_urlsafe(12),
            "seat": len(self.players),
            "stack": int(self.settings["start_stack"]),
            "ready": True,
            "connected": True,
            "is_bot": True,
            "color": AVATAR_COLORS[len(self.players) % len(AVATAR_COLORS)],
            "stats": {"hands": 0, "wins": 0, "chips": 0},
            # campos de poker (los usa Game)
            "bet": 0, "folded": False, "all_in": False, "cards": [],
            "total_contrib": 0, "last_action": None, "revealed": False,
        }
        self.players.append(player)
        self.add_log(f"{nombre} se sienta (bot)", "info", player["id"])
        return player

    def fill_with_bots(self, count: Optional[int] = None) -> int:
        """Anade bots a la mesa. count=None => rellena hasta el maximo."""
        max_p = int(self.settings["max_players"])
        objetivo = (max_p - len(self.players)) if count is None else max(0, int(count))
        anadidos = 0
        while anadidos < objetivo and len(self.players) < max_p:
            self.add_bot()
            anadidos += 1
        return anadidos

    def set_bots(self, pid: str, count: int, remove: bool = False) -> int:
        """El anfitrion anade o quita bots (fuera de una mano en curso)."""
        if not self.is_host(pid):
            raise GameError("Solo el anfitrion puede managear los bots")
        if self.game.phase in ("betting", "discard"):
            raise GameError("Espera a que termine la mano para cambiar los bots")
        if remove:
            n = self.remove_bots()
            self.settings["bots"] = 0
            return n
        n = self.fill_with_bots(None if count < 0 else count)
        self.settings["bots"] = len([p for p in self.players if p.get("is_bot")])
        return n

    def remove_bots(self) -> int:
        """Saca a todos los bots de la mesa."""
        bots = [p for p in self.players if p.get("is_bot")]
        if not bots:
            return 0
        ids = {p["id"] for p in bots}
        self.players = [p for p in self.players if p["id"] not in ids]
        for i, p in enumerate(self.players):
            p["seat"] = i
        self.game.players = self.players
        for p in bots:
            self.add_log(f"{p['name']} se levanta (bot)", "info", p["id"])
        if self.host_id in ids:
            self.host_id = self.players[0]["id"] if self.players else None
        return len(bots)

    def sync_bots(self) -> None:
        """Deja la mesa con el numero de bots que pide el anfitrion."""
        objetivo = int(self.settings.get("bots") or 0)
        actuales = len([p for p in self.players if p.get("is_bot")])
        if actuales > objetivo:
            sobrantes = [p for p in self.players if p.get("is_bot")][objetivo:]
            ids = {p["id"] for p in sobrantes}
            self.players = [p for p in self.players if p["id"] not in ids]
            for i, p in enumerate(self.players):
                p["seat"] = i
            self.game.players = self.players
            for p in sobrantes:
                self.add_log(f"{p['name']} se levanta (bot)", "info", p["id"])
        elif actuales < objetivo:
            self.fill_with_bots(objetivo - actuales)

    def remove_player(self, pid: str) -> None:
        p = self.player(pid)
        if not p:
            return
        self.players = [x for x in self.players if x["id"] != pid]
        # recolocar asientos
        for i, x in enumerate(self.players):
            x["seat"] = i
        self.game.players = self.players
        if self.game.phase in ("betting", "discard"):
            self.game.player_left(pid)
        self.add_log(f"{p['name']} sale de la mesa", "info", pid)
        if self.host_id == pid:
            self.host_id = self.players[0]["id"] if self.players else None
        if not self.players:
            self.phase = "lobby"
        elif self.phase == "playing" and self.settings.get("auto_fill"):
            self.fill_with_bots()

    def rebuy(self, pid: str, amount: Optional[int] = None) -> int:
        p = self.player(pid)
        if not p:
            raise GameError("Jugador no encontrado")
        if self.game.phase in ("betting", "discard"):
            raise GameError("No se puede recargar durante una mano")
        amount = int(amount or self.settings.get("rebuy") or self.settings["start_stack"])
        amount = max(0, min(amount, 100000))
        p["stack"] += amount
        self.add_log(f"{p['name']} recarga {amount} fichas", "info", pid)
        return p["stack"]

    # ----------------------------------------------------------------- juego
    def update_settings(self, pid: str, patch: Dict[str, Any]) -> None:
        if not self.is_host(pid):
            raise GameError("Solo el anfitrion puede cambiar los ajustes")
        if self.phase != "lobby":
            raise GameError("Solo se pueden cambiar los ajustes en el vestibulo")
        variant = patch.get("variant", self.settings["variant"])
        if variant not in ("holdem", "draw", "blackjack", "golpes"):
            raise GameError("Variante no valida")
        sb = int(patch.get("small_blind", self.settings["small_blind"]))
        bb = int(patch.get("big_blind", self.settings["big_blind"]))
        stack = int(patch.get("start_stack", self.settings["start_stack"]))
        sb = max(1, min(sb, 1000))
        bb = max(sb, min(bb, 2000))
        stack = max(20, min(stack, 1000000))
        bots = int(patch.get("bots", self.settings.get("bots", 0)))
        auto_fill = bool(patch.get("auto_fill", self.settings.get("auto_fill", False)))
        rebuy = int(patch.get("rebuy", self.settings.get("rebuy", 0)))
        max_p = int(self.settings["max_players"])
        humanos = len([p for p in self.players if not p.get("is_bot")])
        bots = max(0, min(bots, max(0, max_p - humanos)))
        self.settings.update(variant=variant, small_blind=sb, big_blind=bb,
                             start_stack=stack, bots=bots, auto_fill=auto_fill,
                             rebuy=max(0, min(rebuy, 100000)))
        self.game = self._new_game()
        for p in self.players:
            p["stack"] = stack
        self.sync_bots()
        self.add_log("Ajustes de la mesa actualizados", "info")

    def start_game(self, pid: str) -> None:
        if not self.is_host(pid):
            raise GameError("Solo el anfitrion puede empezar la partida")
        if self.phase != "lobby":
            raise GameError("La partida ya ha empezado")
        if self.settings.get("auto_fill"):
            self.fill_with_bots()
        if len([p for p in self.players if p["stack"] > 0]) < 2:
            raise GameError("Hacen falta al menos 2 jugadores con fichas")
        self.phase = "playing"
        self.add_log("Comienza la partida", "info")
        self._start_next_hand()

    def _start_next_hand(self) -> None:
        self._cancel_next_timer()
        with self.lock:
            # los bots que se han quedado sin fichas vuelven a comprar
            for p in self.players:
                if p.get("is_bot") and p["stack"] <= 0:
                    p["stack"] = int(self.settings["start_stack"])
                    self.add_log(f"{p['name']} recupera {p['stack']} fichas", "info", p["id"])
            eligible = [p for p in self.players if p["stack"] > 0]
            if len(eligible) < 2:
                self.phase = "finished"
                self.add_log("La partida ha terminado: no quedan fichas suficientes", "info")
                self._schedule_turn_timer()
                self.publish()
                return
            self.game.start_hand()
            self.add_log(f"Reparto de la mano #{self.game.hand_number}", "info")
            self._describe_blinds()
            self._schedule_turn_timer()
        self.publish()

    def _describe_blinds(self) -> None:
        blackjack = self.game.is_blackjack()
        for p in self.game.players:
            if p.get("last_action") == "post" and p["total_contrib"] > 0:
                if blackjack:
                    label = "ante"
                else:
                    label = ("ciega grande" if p["total_contrib"] >= self.settings["big_blind"]
                             else "ciega pequena")
                self.add_log(f"{p['name']} pone {p['total_contrib']} ({label})", "info", p["id"])

    def player_action(self, pid: str, action: str, amount: int = 0) -> None:
        with self.lock:
            p = self.player(pid)
            if not p:
                raise GameError("Jugador no encontrado")
            if action == "discard":
                indexes = amount if isinstance(amount, list) else []
                result = self.game.submit_discard(pid, indexes)
                self.add_log(
                    f"{p['name']} descarta {result['discarded']} carta(s)", "info", pid)
            else:
                result = self.game.act(pid, action, int(amount or 0))
                self._log_action(p, result)
            self._schedule_turn_timer()
        self.publish()

    def _log_action(self, p: dict, result: dict) -> None:
        verb = ACTION_LABELS.get(result.get("action", ""), result.get("action", ""))
        amt = result.get("amount", 0)
        text = f"{p['name']} {verb}"
        if amt:
            text += f" {amt}"
        if p.get("all_in"):
            text += " (all-in)"
        self.add_log(text, "action", p["id"])

    # ------------------------------------------------------------- temporizador
    def _schedule_turn_timer(self) -> None:
        """Prepara el siguiente movimiento: bot (rapido) o persona (30 s)."""
        self._cancel_turn_timer()
        self._cancel_bot_timer()
        g = self.game
        if g.phase == "discard":
            self.turn_deadline = None
            self._schedule_bot_discards()
            return
        if g.phase != "betting" or not g.to_act:
            self.turn_deadline = None
            return
        self.turn_deadline = time.time() + TURN_SECONDS
        pid = g.to_act
        p = self.player(pid)
        if p and p.get("is_bot"):
            # los bots juegan solos, con un retardo corto para que se vea natural
            timer = threading.Timer(random.uniform(1.0, 2.6), self._bot_turn, args=(pid,))
            timer.daemon = True
            self._bot_timer = timer
            timer.start()
            return
        timer = threading.Timer(TURN_SECONDS, self._on_turn_timeout, args=(pid,))
        timer.daemon = True
        self._turn_timer = timer
        timer.start()

    def _cancel_turn_timer(self) -> None:
        if self._turn_timer:
            self._turn_timer.cancel()
            self._turn_timer = None

    def _cancel_bot_timer(self) -> None:
        if self._bot_timer:
            self._bot_timer.cancel()
            self._bot_timer = None

    def _schedule_bot_discards(self) -> None:
        """Los bots eligen sus cartas de descarte por su cuenta."""
        g = self.game
        pendientes = [
            pid for pid in g.discard_requests
            if pid not in g._discard_done and (self.player(pid) or {}).get("is_bot")
        ]
        if not pendientes:
            return
        timer = threading.Timer(random.uniform(0.7, 1.9), self._bot_discard,
                                args=(pendientes[0],))
        timer.daemon = True
        self._bot_timer = timer
        timer.start()

    def _bot_turn(self, pid: str) -> None:
        with self.lock:
            g = self.game
            if g.phase != "betting" or g.to_act != pid:
                return
            p = self.player(pid)
            if not p:
                return
            try:
                action, amount = bot.decide(g, p)
                self.player_action(pid, action, amount)
            except GameError:
                pass
            except Exception as exc:  # que un bot no rompa la mesa
                self.add_log(f"El bot {p['name']} se equivocó: {exc}", "info", pid)
        self.publish()

    def _bot_discard(self, pid: str) -> None:
        with self.lock:
            g = self.game
            if g.phase != "discard" or pid not in g.discard_requests:
                return
            p = self.player(pid)
            if not p:
                return
            try:
                self.player_action(pid, "discard", bot.choose_discard(g, p))
            except GameError:
                pass
            except Exception as exc:
                self.add_log(f"El bot {p['name']} se equivocó: {exc}", "info", pid)
        self.publish()

    def _cancel_next_timer(self) -> None:
        if self._next_timer:
            self._next_timer.cancel()
            self._next_timer = None

    def _on_turn_timeout(self, pid: str) -> None:
        with self.lock:
            g = self.game
            if g.phase != "betting" or g.to_act != pid:
                return
            p = self.player(pid)
            if not p:
                return
            try:
                if g.is_blackjack():
                    g.act(pid, "stand")
                    self.add_log(f"{p['name']} se planta (tiempo agotado)", "action", pid)
                elif g.current_bet <= p["bet"]:
                    g.act(pid, "check")
                    self.add_log(f"{p['name']} pasa (tiempo agotado)", "action", pid)
                else:
                    g.act(pid, "fold")
                    self.add_log(f"{p['name']} se retira (tiempo agotado)", "action", pid)
            except GameError:
                pass
            self._after_hand()
            self._schedule_turn_timer()
        self.publish()

    def _after_hand(self) -> None:
        """Tras un showdown: reparto de botes, estadisticas y siguiente mano."""
        g = self.game
        if g.phase != "hand_over" or not g.result:
            return
        for p in self.players:
            if not p["folded"] and p["total_contrib"] > 0:
                p["stats"]["hands"] = p["stats"]["hands"] + 1
        for pid, amount in (g.result.get("payouts") or {}).items():
            p = self.player(pid)
            if not p:
                continue
            p["stats"]["wins"] = p["stats"]["wins"] + 1
            p["stats"]["chips"] = p["stats"]["chips"] + amount
        winners = g.result.get("winners") or []
        for pid in winners:
            p = self.player(pid)
            hand = (g.result.get("hands") or {}).get(pid)
            detail = f"con {hand['name']}" if hand else ""
            self.add_log(
                f"{p['name']} gana {g.result.get('payouts', {}).get(pid, 0)} fichas {detail}".strip(),
                "result", pid)
        self._schedule_next_hand()

    def _schedule_next_hand(self) -> None:
        self._cancel_next_timer()
        timer = threading.Timer(NEXT_HAND_DELAY, self._next_hand_now)
        timer.daemon = True
        self._next_timer = timer
        timer.start()

    def _next_hand_now(self) -> None:
        with self.lock:
            if self.phase != "playing":
                return
            if self.game.phase != "hand_over":
                return
            self._start_next_hand()
        self.publish()

    def request_next_hand(self, pid: str) -> None:
        if not self.is_host(pid):
            raise GameError("Solo el anfitrion puede avanzar de mano")
        with self.lock:
            if self.game.phase != "hand_over":
                raise GameError("La mano aun no ha terminado")
            self._cancel_next_timer()
            self._start_next_hand()
        self.publish()

    # ----------------------------------------------------------------- estado
    def state_for(self, pid: Optional[str]) -> dict:
        g = self.game
        button = g.button_player()
        button_id = button["id"] if button else None
        players = []
        for p in self.players:
            show_cards = p["id"] == pid or (g.phase in ("showdown", "hand_over") and not p["folded"])
            entry = {
                "id": p["id"],
                "name": p["name"],
                "seat": p["seat"],
                "stack": p["stack"],
                "bet": p["bet"],
                "folded": p["folded"],
                "all_in": p["all_in"],
                "last_action": p.get("last_action"),
                "ready": p.get("ready", False),
                "connected": p.get("connected", False),
                "color": p.get("color"),
                "is_host": p["id"] == self.host_id,
                "is_bot": bool(p.get("is_bot")),
                "is_button": p["id"] == button_id,
                "is_to_act": p["id"] == g.to_act and g.phase == "betting",
                "stats": p.get("stats", {}),
                "cards": [c.to_json() for c in p["cards"]] if show_cards else [],
                "card_count": len(p["cards"]),
                # el total y el "pasado" solo se ven al final, como el.black jack real
                "total": p.get("total") if show_cards else None,
                "bust": p.get("busted", False) if show_cards else False,
                "stood": p.get("stood", False),
                "natural": p.get("natural", False) if show_cards else False,
            }
            players.append(entry)

        me = None
        if pid:
            p = self.player(pid)
            if p:
                legal = g.legal_actions(pid)
                me = {
                    "id": p["id"],
                    "name": p["name"],
                    "stack": p["stack"],
                    "bet": p["bet"],
                    "cards": [c.to_json() for c in p["cards"]],
                    "legal": legal,
                    "can_discard": g.phase == "discard" and pid in g.discard_requests,
                    "discarded": g.discard_requests.get(pid),
                    "is_host": p["id"] == self.host_id,
                "is_bot": bool(p.get("is_bot")),
                    "can_start": self.is_host(pid) and self.phase == "lobby"
                    and len([x for x in self.players if x["stack"] > 0]) >= 2,
                }
        return {
            "code": self.code,
            "phase": self.phase,
            "you": pid,
            "host": self.host_id,
            "settings": dict(self.settings),
            "players": players,
            "game": g.snapshot(),
            "log": self.log[-60:],
            "chat": self.chat[-40:],
            "turn_deadline": self.turn_deadline,
            "turn_seconds": TURN_SECONDS,
            "me": me,
        }

    # ------------------------------------------------------------- difusion
    def publish(self) -> None:
        self.touch()
        for sub in list(self.subscribers):
            if not sub.active:
                self.subscribers.remove(sub)
                continue
            try:
                payload = {"type": "state", "state": self.state_for(sub.pid)}
                sub.queue.put_nowait(payload)
            except queue.Full:
                try:
                    sub.queue.get_nowait()
                    sub.queue.put_nowait(payload)
                except Exception:
                    pass

    def subscribe(self, pid: str, token: str) -> Subscriber:
        sub = Subscriber(pid, token)
        with self.lock:
            self.subscribers.append(sub)
            p = self.authenticate(pid, token)
            if p:
                p["connected"] = True
                p["last_seen"] = time.time()
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        sub.active = False
        with self.lock:
            if sub in self.subscribers:
                self.subscribers.remove(sub)
            p = self.player(sub.pid)
            if p:
                p["connected"] = False
                p["last_seen"] = time.time()

    def close(self) -> None:
        self._cancel_turn_timer()
        self._cancel_next_timer()
        for sub in self.subscribers:
            sub.active = False


class RoomManager:
    def __init__(self) -> None:
        self.rooms: Dict[str, Room] = {}
        self.lock = threading.RLock()

    def create(self) -> Room:
        with self.lock:
            for _ in range(50):
                code = new_code()
                if code not in self.rooms:
                    room = Room(code)
                    self.rooms[code] = room
                    return room
            raise GameError("No se pudo crear la mesa")

    def get(self, code: str) -> Optional[Room]:
        with self.lock:
            return self.rooms.get((code or "").strip().upper())

    def drop(self, code: str) -> None:
        with self.lock:
            room = self.rooms.pop(code, None)
        if room:
            room.close()

    def cleanup(self) -> None:
        now = time.time()
        with self.lock:
            for code, room in list(self.rooms.items()):
                room.touch()
                empty = not room.players
                idle = now - room.touched_at > 3600
                if empty and now - room.created_at > 120:
                    self.rooms.pop(code, None)
                    room.close()
                elif idle:
                    self.rooms.pop(code, None)
                    room.close()
