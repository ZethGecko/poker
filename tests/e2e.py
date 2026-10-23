"""Prueba end-to-end contra el servidor HTTP real: sala, SSE, acciones y showdown.

Uso: python3 tests/e2e.py [http://127.0.0.1:8765]
"""

from __future__ import annotations

import json
import sys
import threading
import time
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"


def post(path, body):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode()}


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=10) as r:
        return json.loads(r.read().decode())


def sse_listen(code, pid, token, out, stop):
    req = urllib.request.Request(
        f"{BASE}/api/rooms/{code}/stream?pid={pid}&token={token}")
    with urllib.request.urlopen(req, timeout=60) as r:
        buf = ""
        while not stop.is_set():
            chunk = r.read1(4096).decode("utf-8", "ignore")
            if not chunk:
                break
            buf += chunk
            while "\n\n" in buf:
                block, buf = buf.split("\n\n", 1)
                for line in block.splitlines():
                    if line.startswith("data:"):
                        out.append(json.loads(line[5:].strip()))


def main() -> None:
    variant = sys.argv[2] if len(sys.argv) > 2 else "holdem"
    con_bots = len(sys.argv) > 3 and sys.argv[3] == "bots"
    errors = []

    # 1. crear sala
    res = post("/api/rooms", {"name": "Ana"})
    if "code" not in res:
        print("FALLO al crear la sala:", res)
        sys.exit(1)
    code = res["code"]
    print(f"  mesa creada: {code}")

    host = {"code": code, "pid": res["pid"], "token": res["token"], "name": "Ana"}
    players = [host]
    if con_bots:
        r = post(f"/api/rooms/{code}/bots", {
            "pid": res["pid"], "token": res["token"], "count": 3})
        if "error" in r:
            errors.append(f"bots: {r['error']}")
    else:
        for name in ("Beto", "Caro"):
            r = post(f"/api/rooms/{code}/join", {"name": name})
            if "pid" not in r:
                errors.append(f"no se pudo unir {name}: {r}")
            players.append({"code": code, "pid": r["pid"], "token": r["token"], "name": name})
    print(f"  {len(players)} jugadores en la mesa")

    # 2. flujo SSE
    events = []
    stop = threading.Event()
    threads = [
        threading.Thread(target=sse_listen, args=(code, p["pid"], p["token"], events, stop), daemon=True)
        for p in players
    ]
    for t in threads:
        t.start()
    time.sleep(0.6)

    # 3. ajustes + inicio
    r = post(f"/api/rooms/{code}/settings", {
        "pid": host["pid"], "token": host["token"],
        "settings": {"variant": variant, "small_blind": 5, "big_blind": 10, "start_stack": 500},
    })
    if "error" in r:
        errors.append(f"ajustes: {r['error']}")
    r = post(f"/api/rooms/{code}/start", {"pid": host["pid"], "token": host["token"]})
    if "error" in r:
        errors.append(f"start: {r['error']}")
    time.sleep(0.4)

    state = get(f"/api/rooms/{code}/state?pid={host['pid']}&token={host['token']}")["state"]
    if state["phase"] != "playing":
        errors.append(f"la partida no arrancó: fase={state['phase']}")
    if state["game"]["to_act"] is None:
        errors.append("no hay jugador en turno tras el reparto")
    print(f"  partida en marcha, turno de {state['game']['to_act']}")
    if con_bots:
        bots = [p for p in state["players"] if p.get("is_bot")]
        if len(bots) != 3:
            errors.append(f"se esperaban 3 bots, hay {len(bots)}")
        for b in bots:
            if b.get("cards"):
                errors.append(f"se filtran las cartas del bot {b['name']}")
            if b.get("total") is not None:
                errors.append(f"se filtra el total del bot {b['name']}")
    # el total de los rivales no puede filtrarse con la mano en curso
    if variant == "blackjack":
        for p in state["players"]:
            if p["id"] != host["pid"] and p["total"] is not None:
                errors.append(f"se filtra el total de {p['name']} antes del showdown")
                break
        if not state["me"]["cards"]:
            errors.append("no se ven las propias cartas en el black jack")

    # 4. jugar hasta el final de la mano
    def legal_of(st, pid):
        me = st.get("me") or {}
        return me.get("legal")

    guard = 0
    descartado = set()
    while guard < 400:
        guard += 1
        st = get(f"/api/rooms/{code}/state?pid={host['pid']}&token={host['token']}")["state"]
        g = st["game"]
        if g["phase"] == "hand_over":
            break
        if g["phase"] == "discard":
            for p in players:
                if p["pid"] in descartado:
                    continue
                own = get(f"/api/rooms/{code}/state?pid={p['pid']}&token={p['token']}")["state"]
                if own["me"]["can_discard"]:
                    post(f"/api/rooms/{code}/action", {
                        "pid": p["pid"], "token": p["token"],
                        "action": "discard", "indexes": [0]})
                    descartado.add(p["pid"])
            time.sleep(0.35)   # los bots tardan un poco en descartar
            continue
        pid = g["to_act"]
        if not pid:
            errors.append("to_act vacío con la partida en curso")
            break
        actor = next((p for p in players if p["pid"] == pid), None)
        if actor is None:
            # es un bot: esperamos a que juegue
            time.sleep(0.4)
            continue
        own = get(f"/api/rooms/{code}/state?pid={pid}&token={actor['token']}")["state"]
        legal = legal_of(own, pid)
        if not legal:
            errors.append("el jugador en turno no tiene acciones legales")
            break
        if g.get("variant") == "blackjack":
            if legal.get("hit") and legal.get("total", 0) < 17 and guard % 3:
                action, amount = "hit", 0
            else:
                action, amount = "stand", 0
        elif legal.get("bet") and guard % 3 == 0:
            action, amount = "bet", legal["bet"]["min"]
        elif legal.get("raise") and guard % 5 == 0:
            action, amount = "raise", legal["raise"]["min"]
        elif legal["to_call"] > 0:
            action, amount = "call", 0
        elif legal.get("check"):
            action, amount = "check", 0
        else:
            action, amount = "fold", 0
        r = post(f"/api/rooms/{code}/action", {
            "pid": pid, "token": actor["token"], "action": action, "amount": amount})
        if "error" in r:
            errors.append(f"acción {action}: {r['error']}")
            break
    else:
        errors.append("la mano no terminó")

    st = get(f"/api/rooms/{code}/state?pid={host['pid']}&token={host['token']}")["state"]
    total = sum(p["stack"] for p in st["players"])
    esperado = 500 * len(st["players"])
    if total != esperado:
        errors.append(f"fichas descuadradas: {total} != {esperado}")
    if variant == "blackjack":
        res = st["game"].get("result") or {}
        if res.get("type") != "blackjack":
            errors.append(f"showdown inesperado: {res.get('type')}")
        else:
            for pid, hand in (res.get("hands") or {}).items():
                if hand.get("total") is None:
                    errors.append(f"el jugador {pid} no tiene total en el black jack")
                if not hand.get("cards"):
                    errors.append(f"el jugador {pid} no muestra sus cartas")
            if not res.get("winners") and st["game"]["pot"] != 0:
                errors.append("el bote quedo sin repartir")
    print(f"  mano terminada · fichas totales {total}")

    # 5. el SSE ha seguido difundeiendo
    time.sleep(0.4)
    if len(events) < 3:
        errors.append(f"el SSE solo mandó {len(events)} eventos")
    last = events[-1] if events else {}
    if "state" not in last:
        errors.append("el último evento SSE no trae estado")
    else:
        own_cards = last["state"]["me"]["cards"]
        others = [p for p in last["state"]["players"] if p["id"] != last["state"]["you"]]
        leaked = [p for p in others if p["cards"]]
        if leaked and last["state"]["game"]["phase"] not in ("showdown", "hand_over"):
            errors.append("se filtraron cartas privadas de otro jugador")
        if not own_cards:
            errors.append("no se ven las propias cartas")
    print(f"  eventos SSE recibidos: {len(events)}")

    # 5b. recarga de fichas
    stack_antes = next(p["stack"] for p in st["players"] if p["id"] == host["pid"])
    r = post(f"/api/rooms/{code}/rebuy", {
        "pid": host["pid"], "token": host["token"], "amount": 100})
    if "error" in r:
        errores.append(f"rebuy: {r['error']}")
    else:
        st = get(f"/api/rooms/{code}/state?pid={host['pid']}&token={host['token']}")["state"]
        stack_despues = next(p["stack"] for p in st["players"] if p["id"] == host["pid"])
        if stack_despues != stack_antes + 100:
            errores.append(f"la recarga no sumo fichas: {stack_antes} -> {stack_despues}")

    # 6. chat
    r = post(f"/api/rooms/{code}/chat", {"pid": host["pid"], "token": host["token"], "text": "buena mano"})
    if "error" in r:
        errors.append(f"chat: {r['error']}")
    st = get(f"/api/rooms/{code}/state?pid={host['pid']}&token={host['token']}")["state"]
    if not any(m["text"] == "buena mano" for m in st["chat"]):
        errors.append("el chat no llegó")

    # 7. salir
    if len(players) > 1:
        antes = len(get(f"/api/rooms/{code}/state?pid={host['pid']}&token={host['token']}")["state"]["players"])
        r = post(f"/api/rooms/{code}/leave", {"pid": players[1]["pid"], "token": players[1]["token"]})
        if "error" in r:
            errors.append(f"leave: {r['error']}")
        despues = len(get(f"/api/rooms/{code}/state?pid={host['pid']}&token={host['token']}")["state"]["players"])
        if despues != antes - 1:
            errors.append(f"el jugador no salio de la mesa ({antes} -> {despues})")

    stop.set()
    time.sleep(0.2)

    if errors:
        print("\n  ERRORES:")
        for e in errors:
            print("   -", e)
        sys.exit(1)
    print(f"\n  E2E OK ({variant}): sala, SSE, acciones, showdown, chat y salida")


if __name__ == "__main__":
    main()
