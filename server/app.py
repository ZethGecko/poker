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

    # ------------------------------------------------------------ manejadores
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/"):
            self.handle_api_get(path)
        else:
            self.handle_static(path)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/"):
            self.handle_api_post(path)
        else:
            self.send_error(404, "Endpoint no permitido")

    # ------------------------------------------------------------ api
    def handle_api_get(self, path):
        path_parts = path.strip("/").split("/")
        if len(path_parts) >= 3 and path_parts[0] == "api" and path_parts[1] == "rooms":
            room_code = path_parts[2]

            if len(path_parts) == 4 and path_parts[3] == "stream":
                self.handle_stream(room_code)
            elif len(path_parts) == 3:
                self.send_json(self.get_room_state(room_code), 200)
            else:
                self.send_error(404, f"Unknown API endpoint: {path}")
        else:
            self.send_error(404, f"Unknown API endpoint: {path}")

    def handle_api_post(self, path):
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length).decode()
        path_parts = path.strip("/").split("/")

        if len(path_parts) >= 3 and path_parts[0] == "api" and path_parts[1] == "rooms":
            room_code = path_parts[2]

            try:
                data = json.loads(post_data)
                action = data.get("action")
                amount = data.get("amount", 0)
                pid = data.get("pid")
                token = data.get("token")
                indexes = data.get("indexes", [])

                if not all([action, pid, token]):
                    self.send_error(400, "Faltan campos requeridos")
                    return

                room = manager.get_room(room_code)
                if not room:
                    self.send_error(404, f"Sala no encontrada: {room_code}")
                    return

                player = room.authenticate(pid, token)
                if not player:
                    self.send_error(401, "Token inválido")
                    return

                if action == "discard":
                    room.submit_discard(pid, indexes)
                else:
                    room.act(pid, action, int(amount))

                self.send_json({"status": "ok"}, 200)

            except json.JSONDecodeError:
                self.send_error(400, "JSON inválido")
            except GameError as e:
                self.send_error(400, str(e))
            except Exception as e:
                self.send_error(500, f"Error del servidor: {str(e)}")

        else:
            self.send_error(404, f"Unknown API endpoint: {path}")

    # ------------------------------------------------------------ respuesta
    def send_json(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def send_error(self, code, message=None):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"error": message or HTTPStatus(code).phrase}).encode())

    # ------------------------------------------------------------ activos
    def handle_stream(self, room_code):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        room = manager.get_room(room_code)
        if not room:
            return

        def stream_generator():
            while True:
                try:
                    state = room.state_for(None)
                    self.wfile.write(f"data: {json.dumps(state)}\n\n".encode())
                    self.wfile.flush()
                    time.sleep(1)
                except:
                    break

        stream_generator()

    def handle_static(self, path):
        if path == "/":
            path = "/index.html"
        elif path == "/style.css":
            path = "/styles.css"
        elif path.startswith("/js/"):
            pass
        else:
            self.send_error(404, "Archivo no encontrado")
            return

        static_path = os.path.join(PUBLIC_DIR, path.lstrip("/"))
        try:
            with open(static_path, "rb") as f:
                content_type = self.guess_type(path)
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.end_headers()
                self.wfile.write(f.read())
        except FileNotFoundError:
            self.send_error(404, f"Archivo no encontrado: {path}")

    def guess_type(self, path):
        return mimetypes.guess_type(path)[0] or "application/octet-stream"

    def get_room_state(self, room_code):
        room = manager.get_room(room_code)
        return room.state_for(None) if room else None


# ----------------------------------------------------------------------------- entrada ws (para gunicorn)
def app(environ, start_response):
    """WSGI application entry point for Gunicorn"""
    path = environ.get("PATH_INFO", "")
    method = environ.get("REQUEST_METHOD", "")

    if path.startswith("/api/"):
        return handle_api_request(environ, start_response)
    else:
        return handle_static_request(environ, start_response)

def handle_api_request(environ, start_response):
    path = environ.get("PATH_INFO", "")
    method = environ.get("REQUEST_METHOD", "")
    content_length = int(environ.get("CONTENT_LENGTH", 0))

    body = environ["wsgi.input"].read(content_length).decode() if content_length > 0 else ""

    path_parts = path.strip("/").split("/")

    if len(path_parts) >= 3 and path_parts[0] == "api" and path_parts[1] == "rooms":
        room_code = path_parts[2]

        if len(path_parts) == 4 and path_parts[3] == "stream":
            return handle_stream_endpoint(environ, start_response, room_code)
        elif len(path_parts) == 3:
            return handle_room_endpoint(environ, start_response, room_code)
        else:
            return error_response(start_response, 404, f"Unknown API endpoint: {path}")

    return error_response(start_response, 404, f"Unknown API endpoint: {path}")

def handle_room_endpoint(environ, start_response, room_code):
    room = manager.get_room(room_code)
    if room:
        state = room.state_for(None)
        return json_response(start_response, 200, state)
    else:
        return error_response(start_response, 404, f"Room not found: {room_code}")

def handle_stream_endpoint(environ, start_response, room_code):
    room = manager.get_room(room_code)
    if not room:
        return error_response(start_response, 404, f"Room not found: {room_code}")

    start_response("200 OK", [
        ("Content-Type", "text/event-stream"),
        ("Cache-Control", "no-cache"),
        ("Connection", "keep-alive"),
        ("X-Accel-Buffering", "no")
    ])

    def generate():
        while True:
            time.sleep(1)

    return generate()

def error_response(start_response, status_code, message):
    start_response(f"{status_code} {HTTPStatus(status_code).phrase}", [
        ("Content-Type", "application/json")
    ])
    return [json.dumps({"error": message}).encode()]

def json_response(start_response, status_code, data):
    start_response(f"{status_code} {HTTPStatus(status_code).phrase}", [
        ("Content-Type", "application/json")
    ])
    return [json.dumps(data).encode()]

def handle_static_request(environ, start_response):
    path = environ.get("PATH_INFO", "")

    if path == "/":
        path = "/index.html"
    elif path == "/style.css":
        path = "/styles.css"
    elif path.startswith("/js/"):
        pass
    else:
        return error_response(start_response, 404, f"File not found: {path}")

    static_path = os.path.join(PUBLIC_DIR, path.lstrip("/"))

    try:
        with open(static_path, "rb") as f:
            content = f.read()
            content_type = "text/html"
            if path.endswith(".css"):
                content_type = "text/css"
            elif path.endswith(".js"):
                content_type = "application/javascript"

            start_response("200 OK", [("Content-Type", content_type)])
            return [content]
    except FileNotFoundError:
        return error_response(start_response, 404, f"File not found: {path}")


# ----------------------------------------------------------------------------- servidor original (para desarrollo local)
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "PokerEntreAmigos"

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/"):
            self.handle_api_get(path)
        else:
            self.handle_static(path)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/"):
            self.handle_api_post(path)
        else:
            self.send_error(404, "Endpoint no permitido")

    def send_json(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def send_error(self, code, message=None):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"error": message or HTTPStatus(code).phrase}).encode())

    def handle_api_get(self, path):
        path_parts = path.strip("/").split("/")
        if len(path_parts) >= 3 and path_parts[0] == "api" and path_parts[1] == "rooms":
            room_code = path_parts[2]

            if len(path_parts) == 4 and path_parts[3] == "stream":
                self.handle_stream(room_code)
            elif len(path_parts) == 3:
                self.send_json(self.get_room_state(room_code), 200)
            else:
                self.send_error(404, f"Unknown API endpoint: {path}")
        else:
            self.send_error(404, f"Unknown API endpoint: {path}")

    def handle_api_post(self, path):
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length).decode()
        path_parts = path.strip("/").split("/")

        if len(path_parts) >= 3 and path_parts[0] == "api" and path_parts[1] == "rooms":
            room_code = path_parts[2]

            try:
                data = json.loads(post_data)
                action = data.get("action")
                amount = data.get("amount", 0)
                pid = data.get("pid")
                token = data.get("token")
                indexes = data.get("indexes", [])

                if not all([action, pid, token]):
                    self.send_error(400, "Faltan campos requeridos")
                    return

                room = manager.get_room(room_code)
                if not room:
                    self.send_error(404, f"Sala no encontrada: {room_code}")
                    return

                player = room.authenticate(pid, token)
                if not player:
                    self.send_error(401, "Token inválido")
                    return

                if action == "discard":
                    room.submit_discard(pid, indexes)
                else:
                    room.act(pid, action, int(amount))

                self.send_json({"status": "ok"}, 200)

            except json.JSONDecodeError:
                self.send_error(400, "JSON inválido")
            except GameError as e:
                self.send_error(400, str(e))
            except Exception as e:
                self.send_error(500, f"Error del servidor: {str(e)}")

        else:
            self.send_error(404, f"Unknown API endpoint: {path}")

    def handle_stream(self, room_code):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        room = manager.get_room(room_code)
        if not room:
            return

        def stream_generator():
            while True:
                try:
                    state = room.state_for(None)
                    self.wfile.write(f"data: {json.dumps(state)}\n\n".encode())
                    self.wfile.flush()
                    time.sleep(1)
                except:
                    break

        stream_generator()

    def handle_static(self, path):
        if path == "/":
            path = "/index.html"
        elif path == "/style.css":
            path = "/styles.css"
        elif path.startswith("/js/"):
            pass
        else:
            self.send_error(404, "Archivo no encontrado")
            return

        static_path = os.path.join(PUBLIC_DIR, path.lstrip("/"))
        try:
            with open(static_path, "rb") as f:
                content_type = self.guess_type(path)
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.end_headers()
                self.wfile.write(f.read())
        except FileNotFoundError:
            self.send_error(404, f"Archivo no encontrado: {path}")

    def guess_type(self, path):
        return mimetypes.guess_type(path)[0] or "application/octet-stream"

    def get_room_state(self, room_code):
        room = manager.get_room(room_code)
        return room.state_for(None) if room else None


def run_server():
    server = ThreadingHTTPServer(("0.0.0.0", 8000), Handler)
    print("Servidor iniciado en http://localhost:8000")
    server.serve_forever()

if __name__ == "__main__":
    run_server()