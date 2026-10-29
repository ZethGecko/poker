"""Servidor HTTP + Server-Sent Events para el poker entre amigos.

No hay base de datos: todo el estado vive en memoria del proceso.
Uso:  python3 -m server.app --host 0.0.0.0 --port 8000
Como WSGI (Gunicorn):  gunicorn server.app:app
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import queue
import sys
import threading
import time
from http import HTTPStatus
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


# ---------------------------------------------------------------------------
# Utilidades de respuesta JSON
# ---------------------------------------------------------------------------

def _json(data) -> bytes:
    return json.dumps(data).encode("utf-8")


def _ok(data=None):
    return 200, data if data is not None else {"status": "ok"}


def _fail(status, message):
    return status, {"error": message or HTTPStatus(status).phrase}


# ---------------------------------------------------------------------------
# API REST compartida (servidor nativo y Gunicorn WSGI)
# Devuelve (codigo_http, diccionario_respuesta)
# ---------------------------------------------------------------------------

def _api_dispatch(method, path, body, query):
    parts = [p for p in (path or "/").strip("/").split("/") if p]

    def get_room(code):
        return manager.get(code)

    # ---------------- GET ----------------
    if method == "GET":
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "rooms":
            code = parts[2]
            room = get_room(code)
            if not room:
                return _fail(404, f"Sala no encontrada: {code}")
            pid = (query.get("pid") or [None])[0]
            token = (query.get("token") or [None])[0]
            if pid and token and not room.authenticate(pid, token):
                return _fail(401, "Token invalido")
            return _ok(room.state_for(pid or None))
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "rooms" and parts[3] == "state":
            code = parts[2]
            room = get_room(code)
            if not room:
                return _fail(404, f"Sala no encontrada: {code}")
            pid = (query.get("pid") or [None])[0]
            token = (query.get("token") or [None])[0]
            if pid and token and not room.authenticate(pid, token):
                return _fail(401, "Token invalido")
            return _ok(room.state_for(pid or None))
        return _fail(404, f"Endpoint no permitido: {path}")

    # ---------------- POST ----------------
    if method == "POST":
        # Crear mesa: POST /api/rooms   body: { name }
        if parts == ["api", "rooms"]:
            name = (body or {}).get("name", "Jugador")
            room = manager.create()
            player = room.add_player(name)
            room.publish()
            return _ok({
                "code": room.code,
                "pid": player["id"],
                "token": player["token"],
                "state": room.state_for(player["id"]),
            })

        if len(parts) == 4 and parts[0] == "api" and parts[1] == "rooms":
            code = parts[2]
            action = parts[3]
            room = get_room(code)
            if not room:
                return _fail(404, f"Sala no encontrada: {code}")

            pid = (body or {}).get("pid")
            token = (body or {}).get("token")

            if action == "join":
                # Unirse: POST /api/rooms/<code>/join  body: { name }
                name = (body or {}).get("name", "Jugador")
                try:
                    player = room.add_player(name)
                except GameError as e:
                    return _fail(400, str(e))
                room.publish()
                return _ok({
                    "code": room.code,
                    "pid": player["id"],
                    "token": player["token"],
                    "state": room.state_for(player["id"]),
                })

            # El resto requiere autenticacion
            player = room.authenticate(pid, token) if (pid and token) else None
            if not player:
                return _fail(401, "Token invalido")

            if action == "leave":
                room.remove_player(pid)
                room.publish()
                return _ok()

            if action == "start":
                try:
                    room.start_game(pid)
                except GameError as e:
                    return _fail(400, str(e))
                return _ok({"state": room.state_for(pid)})

            if action == "next":
                room.request_next_hand(pid)
                return _ok({"state": room.state_for(pid)})

            if action == "rebuy":
                amount = int(
                    (body or {}).get("amount")
                    or room.settings.get("rebuy")
                    or room.settings.get("start_stack", 1000)
                )
                try:
                    room.rebuy(pid, amount)
                except GameError as e:
                    return _fail(400, str(e))
                return _ok({"state": room.state_for(pid)})

            if action == "chat":
                text = (body or {}).get("text", "")
                try:
                    room.add_chat(pid, text)
                except GameError as e:
                    return _fail(400, str(e))
                room.publish()
                return _ok({"state": room.state_for(pid)})

            if action == "settings":
                patch = (body or {}).get("settings", {})
                try:
                    room.update_settings(pid, patch)
                except GameError as e:
                    return _fail(400, str(e))
                room.publish()
                return _ok({"state": room.state_for(pid)})

            if action == "bots":
                if (body or {}).get("remove"):
                    room.remove_bots()
                else:
                    count = int((body or {}).get("count", -1))
                    room.fill_with_bots(None if count < 0 else count)
                room.publish()
                return _ok({"state": room.state_for(pid)})

            if action == "action":
                act = (body or {}).get("action")
                amount = int((body or {}).get("amount", 0))
                indexes = (body or {}).get("indexes", [])
                if act == "discard":
                    room.submit_discard(pid, indexes)
                else:
                    room.player_action(pid, act, amount)
                room.publish()
                return _ok({"state": room.state_for(pid)})

        return _fail(404, f"Endpoint no permitido: {path}")

    return _fail(405, "Metodo no permitido")

# ---------------------------------------------------------------------------
# Servidor HTTP nativo (desarrollo local y despliegue sencillo con hilos)
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "PokerEntreAmigos"

    def log_message(self, fmt, *args):  # silencia el log por defecto
        pass

    # ------------------------------------------------------------- utilidades
    def _send(self, status, data, content_type="application/json"):
        body = _json(data) if not isinstance(data, bytes) else data
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _dispatch_http(self, method):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        body = {}
        if method == "POST":
            try:
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length).decode() if length > 0 else "{}"
                body = json.loads(raw) if raw.strip() else {}
            except Exception:
                body = {}
        try:
            status, data = _api_dispatch(method, path, body, query)
            self._send(status, data)
        except GameError as e:
            self._send(400, {"error": str(e)})
        except Exception as e:
            self._send(500, {"error": f"Error del servidor: {e}"})

    def do_GET(self):
        if self.path.startswith("/api/"):
            parts = [p for p in self.path.strip("/").split("/") if p]
            if len(parts) == 4 and parts[:2] == ["api", "rooms"] and parts[3] == "stream":
                self.handle_stream(parts[2])
            else:
                self._dispatch_http("GET")
        else:
            self.handle_static()

    def do_POST(self):
        if self.path.startswith("/api/"):
            self._dispatch_http("POST")
        else:
            self._send(404, {"error": "Endpoint no permitido"})

    # ------------------------------------------------------------- stream SSE
    def handle_stream(self, room_code):
        room = manager.get(room_code)
        if not room:
            self._send(404, {"error": f"Sala no encontrada: {room_code}"})
            return

        query = parse_qs(urlparse(self.path).query)
        pid = (query.get("pid") or [None])[0]
        token = (query.get("token") or [None])[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        sub = None
        if pid and token and room.authenticate(pid, token):
            sub = room.subscribe(pid, token)

        try:
            payload0 = _json({'type': 'state', 'state': room.state_for(pid)}).decode()
            self.wfile.write(f"event: state\ndata: {payload0}\n\n".encode())
            self.wfile.flush()
            while True:
                if sub is not None and not sub.active:
                    break
                try:
                    payload = sub.queue.get(timeout=1) if sub else None
                except queue.Empty:
                    payload = None
                if payload:
                    self.wfile.write(f"event: state\ndata: {_json(payload).decode()}\n\n".encode())
                    self.wfile.flush()
                time.sleep(0.5)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            if sub:
                room.unsubscribe(sub)

    def handle_static(self):
        path = urlparse(self.path).path
        if path == "/":
            path = "/index.html"
        static_path = os.path.join(PUBLIC_DIR, path.lstrip("/"))
        try:
            with open(static_path, "rb") as f:
                content = f.read()
            content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
            self._send(200, content, content_type)
        except FileNotFoundError:
            self._send(404, {"error": f"Archivo no encontrado: {path}"})


# ---------------------------------------------------------------------------
# Punto de entrada WSGI para Gunicorn
# ---------------------------------------------------------------------------

def _wsgi_body(environ):
    length = int(environ.get("CONTENT_LENGTH", 0))
    raw = environ["wsgi.input"].read(length).decode() if length > 0 else "{}"
    try:
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}


def _serve_static(environ, start_response, path):
    """Sirve un archivo estatico desde PUBLIC_DIR (/, /styles.css, /js/...)."""
    if path == "/":
        path = "/index.html"
    static_path = os.path.join(PUBLIC_DIR, path.lstrip("/"))
    try:
        with open(static_path, "rb") as f:
            content = f.read()
    except FileNotFoundError:
        body = _json({"error": f"Archivo no encontrado: {path}"})
        start_response("404 Not Found", [
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(body))),
        ])
        return [body]

    content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
    method = environ.get("REQUEST_METHOD", "")
    start_response("200 OK", [
        ("Content-Type", content_type),
        ("Content-Length", str(len(content))),
    ])
    if method == "HEAD":
        return [b""]
    return [content]


def app(environ, start_response):
    """WSGI application entry point for Gunicorn."""
    method = environ.get("REQUEST_METHOD", "")
    path = environ.get("PATH_INFO", "/")
    query = parse_qs(environ.get("QUERY_STRING", ""))

    parts = [p for p in path.strip("/").split("/") if p]

    # SSE bajo Gunicorn: envia estado periodicamente mientras la conexione viva.
    if method in ("GET", "HEAD") and len(parts) == 4 and parts[:2] == ["api", "rooms"] and parts[3] == "stream":
        room_code = parts[2]
        room = manager.get(room_code)
        if not room:
            body = _json({"error": f"Sala no encontrada: {room_code}"})
            start_response("404 Not Found", [
                ("Content-Type", "application/json"),
                ("Content-Length", str(len(body))),
            ])
            return [body]

        pid = (query.get("pid") or [None])[0]
        token = (query.get("token") or [None])[0]

        def generate():
            try:
                payload0 = _json({'type': 'state', 'state': room.state_for(pid)}).decode()
                yield f"event: state\ndata: {payload0}\n\n".encode()
                while True:
                    time.sleep(2)
                    try:
                        payload = _json({'type': 'state', 'state': room.state_for(pid)}).decode()
                        yield f"event: state\ndata: {payload}\n\n".encode()
                    except Exception:
                        return
            except GeneratorExit:
                return

        return generate()

    if path.startswith("/api/"):
        if method == "HEAD":
            # Health-check: responder 200 vacio sin body
            start_response("200 OK", [("Content-Length", "0")])
            return [b""]
        body = _wsgi_body(environ)
        try:
            status, data = _api_dispatch(method, path, body, query)
            body_bytes = _json(data)
            start_response(f"{status} {HTTPStatus(status).phrase}", [
                ("Content-Type", "application/json"),
                ("Content-Length", str(len(body_bytes))),
            ])
            return [body_bytes]
        except GameError as e:
            body_bytes = _json({"error": str(e)})
            start_response("400 Bad Request", [
                ("Content-Type", "application/json"),
                ("Content-Length", str(len(body_bytes))),
            ])
            return [body_bytes]
        except Exception as e:
            body_bytes = _json({"error": f"Error del servidor: {e}"})
            start_response("500 Internal Server Error", [
                ("Content-Type", "application/json"),
                ("Content-Length", str(len(body_bytes))),
            ])
            return [body_bytes]

    # Rutas estaticas (/, /styles.css, /js/app.js, etc.)
    return _serve_static(environ, start_response, path)


# ---------------------------------------------------------------------------
# Arranque del servidor nativo
# ---------------------------------------------------------------------------

def run_server(host="0.0.0.0", port=8000):
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Servidor iniciado en http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mesa de poker entre amigos")
    parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    args = parser.parse_args()
    t = threading.Thread(target=cleanup_loop, daemon=True)
    t.start()
    run_server(args.host, args.port)
