"""Servidor HTTP + Server-Sent Events para el poker entre amigos.

No hay base de datos: todo el estado vive en memoria del proceso.
Uso:  python3 -m server.app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import queue
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

if __package__ in (None, ""):  # permite ejecutar el fichero directamente
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from server.engine import GameError
    from server.rooms import RoomManager
else:
    from .engine import GameError
    from .rooms import RoomManager

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC_DIR = os.path.join(BASE_DIR, "public")

manager = RoomManager()


def cleanup_loop() -> None:
    while True:
        time.sleep(60)
        try:
            manager.cleanup()
        except Exception:
            pass


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "PokerEntreAmigos"

    # ------------------------------------------------------------- utilidades
    def log_message(self, fmt, *args):  # silencia el log por defecto
        pass

    def _send_json(self, obj, status: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _error(self, message: str, status: int = 400) -> None:
        self._send_json({"error": message}, status)

    # ------------------------------------------------------------------ GET
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path.startswith("/api/"):
            return self._api_get(path, query)
        return self._serve_static(path)

    def _api_get(self, path: str, query: dict) -> None:
        parts = [p for p in path.split("/") if p]  # ['api','rooms',CODE,action]
        if parts == ["api", "health"]:
            return self._send_json({"ok": True, "rooms": len(manager.rooms), "time": time.time()})

        if len(parts) >= 3 and parts[1] == "rooms":
            code = parts[2].upper()
            room = manager.get(code)
            if room is None:
                return self._error("La mesa no existe", 404)
            action = parts[3] if len(parts) > 3 else "state"
            pid = (query.get("pid") or [""])[0]
            token = (query.get("token") or [""])[0]
            if action == "state":
                if not room.authenticate(pid, token):
                    return self._error("Sesion no valida", 403)
                return self._send_json({"state": room.state_for(pid)})
            if action == "stream":
                return self._stream(room, pid, token)
        return self._error("Ruta no encontrada", 404)

    def _stream(self, room, pid: str, token: str) -> None:
        if not room.authenticate(pid, token):
            return self._error("Sesion no valida", 403)
        sub = room.subscribe(pid, token)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-transform")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            self._sse(json.dumps({"type": "state", "state": room.state_for(pid)},
                                  ensure_ascii=False))
            while True:
                try:
                    msg = sub.queue.get(timeout=15)
                except queue.Empty:
                    self._chunk(": ping\n\n")
                    continue
                self._sse(json.dumps(msg, ensure_ascii=False))
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            room.unsubscribe(sub)
            try:
                self._chunk("")
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            except Exception:
                pass
            self.close_connection = True

    def _sse(self, data: str, event: str = "state") -> None:
        """Envia un mensaje SSE con el formato que espera EventSource."""
        self._chunk(f"event: {event}\ndata: {data}\n\n")

    def _chunk(self, data: str) -> None:
        payload = data.encode("utf-8")
        self.wfile.write(f"{len(payload):X}\r\n".encode("ascii") + payload + b"\r\n")
        self.wfile.flush()

    def _serve_static(self, path: str) -> None:
        if path in ("/", "", "/index.html"):
            rel = "index.html"
        else:
            rel = path.lstrip("/")
        target = os.path.normpath(os.path.join(PUBLIC_DIR, rel))
        if not target.startswith(PUBLIC_DIR) or not os.path.isfile(target):
            target = os.path.join(PUBLIC_DIR, "index.html")
        ctype, _ = mimetypes.guess_type(target)
        with open(target, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    # ----------------------------------------------------------------- POST
    def do_POST(self) -> None:
        parts = [p for p in urlparse(self.path).path.split("/") if p]
        body = self._read_json()
        if len(parts) < 2 or parts[0] != "api" or parts[1] != "rooms":
            return self._error("Ruta no encontrada", 404)
        if len(parts) == 2:  # POST /api/rooms -> crear mesa
            return self._create_room(body)

        code = parts[2].upper() if len(parts) > 2 else ""
        action = parts[3] if len(parts) > 3 else ""

        if len(parts) == 2:  # POST /api/rooms -> crear mesa
            return self._create_room(body)

        room = manager.get(code)
        if room is None:
            return self._error("La mesa no existe", 404)
        pid = body.get("pid") or ""
        token = body.get("token") or ""

        if action == "join":
            return self._join(room, body)
        if action == "leave":
            return self._leave(room, pid, token)

        player = room.authenticate(pid, token)
        if player is None:
            return self._error("Sesion no valida", 403)
        player["connected"] = True
        player["last_seen"] = time.time()

        try:
            if action == "action":
                act = body.get("action")
                if act == "discard":
                    indexes = body.get("indexes") or []
                    room.player_action(pid, "discard", indexes)
                else:
                    room.player_action(pid, act, int(body.get("amount") or 0))
            elif action == "chat":
                room.add_chat(pid, body.get("text") or "")
            elif action == "ready":
                player["ready"] = bool(body.get("ready", not player.get("ready")))
            elif action == "settings":
                room.update_settings(pid, body.get("settings") or {})
            elif action == "start":
                room.start_game(pid)
            elif action == "next":
                room.request_next_hand(pid)
            elif action == "bots":
                count = int(body.get("count", 0))
                n = room.set_bots(pid, count, bool(body.get("remove")))
                room.add_log(
                    f"{'Se quitan' if body.get('remove') else 'Se anaden'} {n} bot(s)", "info")
            elif action == "rebuy":
                room.rebuy(pid, body.get("amount"))
            else:
                return self._error("Accion desconocida", 404)
        except GameError as exc:
            return self._error(str(exc), 400)

        room.publish()
        return self._send_json({"ok": True, "state": room.state_for(pid)})

    def _create_room(self, body: dict) -> None:
        try:
            room = manager.create()
        except GameError as exc:
            return self._error(str(exc), 500)
        player = room.add_player(body.get("name") or "Jugador")
        return self._send_json({
            "ok": True,
            "code": room.code,
            "pid": player["id"],
            "token": player["token"],
            "state": room.state_for(player["id"]),
        })

    def _join(self, room, body: dict) -> None:
        try:
            player = room.add_player(body.get("name") or "Jugador")
        except GameError as exc:
            return self._error(str(exc), 400)
        room.publish()
        return self._send_json({
            "ok": True,
            "code": room.code,
            "pid": player["id"],
            "token": player["token"],
            "state": room.state_for(player["id"]),
        })

    def _leave(self, room, pid: str, token: str) -> None:
        if not room.authenticate(pid, token):
            return self._error("Sesion no valida", 403)
        room.remove_player(pid)
        room.publish()
        return self._send_json({"ok": True})


def local_ips() -> list:
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except Exception:
        pass
    return sorted(ips)


def main() -> None:
    parser = argparse.ArgumentParser(description="Mesa de poker entre amigos (sin DB)")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    threading.Thread(target=cleanup_loop, daemon=True).start()
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    httpd.daemon_threads = True

    print("\n  Mesa de poker lista")
    print("  --------------------------------------------------------")
    print(f"  En esta maquina:  http://localhost:{args.port}")
    for ip in local_ips():
        print(f"  En la red local:  http://{ip}:{args.port}")
    print("  Comparte esa IP (o un tunel) con tus amigos.")
    print("  --------------------------------------------------------\n")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Cerrando...")
        httpd.shutdown()


if __name__ == "__main__":
    main()
