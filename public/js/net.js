/* Red: API REST + flujo de estado en vivo (SSE) + sesión en localStorage. */

const SESSION_PREFIX = "mesa-poker:sesion:";

export function sessionKey(code) {
  return SESSION_PREFIX + code;
}

export function loadSession(code) {
  try {
    const raw = localStorage.getItem(sessionKey(code));
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function saveSession(session) {
  try {
    localStorage.setItem(sessionKey(session.code), JSON.stringify(session));
  } catch { /* almacenamiento no disponible */ }
}

export function dropSession(code) {
  try {
    localStorage.removeItem(sessionKey(code));
  } catch { /* ignorar */ }
}

export async function api(path, body) {
  let res;
  try {
    res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
  } catch {
    throw new Error("No se pudo contactar con la mesa. Revisa la conexión.");
  }
  let data = {};
  try { data = await res.json(); } catch { /* respuesta sin cuerpo */ }
  if (!res.ok) throw new Error(data.error || `Error ${res.status}`);
  return data;
}

/** Conexión de estado en vivo. Reconecta sola si se cae la red. */
export function connect(code, pid, token, { onState, onStatus, onGone }) {
  let source = null;
  let closed = false;
  let retry = 0;

  const open = () => {
    if (closed) return;
    source = new EventSource(
      `/api/rooms/${encodeURIComponent(code)}/stream?pid=${encodeURIComponent(pid)}&token=${encodeURIComponent(token)}`
    );
    source.addEventListener("state", (ev) => {
      retry = 0;
      onStatus("online");
      try { onState(JSON.parse(ev.data).state); } catch { /* datos corruptos */ }
    });
    source.onopen = () => { retry = 0; onStatus("online"); };
    source.onerror = () => {
      if (closed) return;
      onStatus("offline");
      source.close();
      // ¿sigue existiendo la mesa?
      fetch(`/api/rooms/${encodeURIComponent(code)}/state?pid=${encodeURIComponent(pid)}&token=${encodeURIComponent(token)}`)
        .then((r) => {
          if (r.status === 404 || r.status === 403) {
            closed = true;
            onGone();
          } else {
            retry = Math.min(retry + 1, 6);
            setTimeout(open, 400 * retry);
          }
        })
        .catch(() => {
          retry = Math.min(retry + 1, 6);
          setTimeout(open, 400 * retry);
        });
    };
  };

  open();
  return {
    close() {
      closed = true;
      if (source) source.close();
    },
  };
}
