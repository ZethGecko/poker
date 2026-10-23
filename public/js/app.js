/* App: pantallas, estado en vivo y glue de la interfaz. */

import { api, connect, loadSession, saveSession, dropSession } from "./net.js";
import { cardEl, fmt, sfx, setMuted, isMuted } from "./cards.js";
import {
  renderSeats, renderBoard, renderPot, renderStreet, renderActions, renderRaiseValue, resetTables,
} from "./table.js";

const $ = (id) => document.getElementById(id);

const els = {
  home: $("view-home"), lobby: $("view-lobby"), table: $("view-table"),
  inputName: $("inputName"), inputCode: $("inputCode"),
  btnCreate: $("btnCreate"), btnJoin: $("btnJoin"), homeError: $("homeError"),
  roomInfo: $("roomInfo"), roomCode: $("roomCode"), roomCodeText: $("roomCodeText"),
  roomPhase: $("roomPhase"), btnLeave: $("btnLeave"), btnSound: $("btnSound"), btnHelp: $("btnHelp"),
  setVariant: $("setVariant"), setSb: $("setSb"), setBb: $("setBb"), setStack: $("setStack"),
  valSb: $("valSb"), valBb: $("valBb"), valStack: $("valStack"), settingsHint: $("settingsHint"),
  fieldBb: $("fieldBb"), labelSb: $("labelSb"),
  setBots: $("setBots"), valBots: $("valBots"), setAutoFill: $("setAutoFill"), btnBots: $("btnBots"),
  lobbyPlayers: $("lobbyPlayers"), playerCount: $("playerCount"), btnStart: $("btnStart"), lobbyNote: $("lobbyNote"),
  lobbyChat: $("lobbyChat"), lobbyChatForm: $("lobbyChatForm"), lobbyChatInput: $("lobbyChatInput"),
  felt: $("felt"), seats: $("seats"), board: $("board"), potBox: $("potBox"), potValue: $("potValue"),
  streetLabel: $("streetLabel"), actionStatus: $("actionStatus"), actions: $("actions"),
  raisePanel: $("raisePanel"), raiseRange: $("raiseRange"), raiseAmount: $("raiseAmount"),
  raiseUnit: $("raiseUnit"), raiseConfirm: $("raiseConfirm"),
  discardPanel: $("discardPanel"), discardCards: $("discardCards"),
  logList: $("logList"), chatList: $("chatList"), scoreboard: $("scoreboard"), chatForm: $("chatForm"), chatInput: $("chatInput"),
  showdown: $("showdown"), showdownTitle: $("showdownTitle"), showdownBody: $("showdownBody"),
  showdownNext: $("showdownNext"), showdownClose: $("showdownClose"), btnNextHand: $("btnNextHand"),
  help: $("help"), helpClose: $("helpClose"), btnHelp2: $("btnHelp2"),
  toasts: $("toasts"), rankList: $("rankList"),
};

let state = null;
let prev = null;
let stream = null;
let session = null;
let selected = new Set();
let showdownDismissedFor = null;
let clockTimer = null;

/* --------------------------------------------------------------- utils */
function toast(msg, kind = "") {
  const el = document.createElement("div");
  el.className = `toast${kind ? ` is-${kind}` : ""}`;
  el.textContent = msg;
  els.toasts.append(el);
  setTimeout(() => el.remove(), 3600);
}

function showView(name) {
  for (const [key, el] of [["home", els.home], ["lobby", els.lobby], ["table", els.table]]) {
    el.classList.toggle("is-active", key === name);
  }
}

function routeCode() {
  const m = location.hash.match(/#\/mesa\/([A-Za-z0-9]{4,6})/);
  return m ? m[1].toUpperCase() : null;
}

/* ------------------------------------------------------------- inicio */
async function createRoom() {
  const name = els.inputName.value.trim() || "Jugador";
  try {
    els.btnCreate.disabled = true;
    const data = await api("/api/rooms", { name });
    session = { code: data.code, pid: data.pid, token: data.token, name };
    saveSession(session);
    location.hash = `#/mesa/${data.code}`;
    startSession(data.state);
  } catch (err) {
    els.homeError.textContent = err.message;
    els.homeError.hidden = false;
  } finally {
    els.btnCreate.disabled = false;
  }
}

async function joinRoom() {
  const code = els.inputCode.value.trim().toUpperCase();
  const name = els.inputName.value.trim() || "Jugador";
  if (!code) { els.homeError.textContent = "Escribe el código de la mesa"; els.homeError.hidden = false; return; }
  try {
    els.btnJoin.disabled = true;
    const data = await api(`/api/rooms/${encodeURIComponent(code)}/join`, { name });
    session = { code: data.code, pid: data.pid, token: data.token, name };
    saveSession(session);
    location.hash = `#/mesa/${data.code}`;
    startSession(data.state);
  } catch (err) {
    els.homeError.textContent = err.message;
    els.homeError.hidden = false;
  } finally {
    els.btnJoin.disabled = false;
  }
}

async function leaveRoom() {
  if (!session) return;
  try { await api(`/api/rooms/${session.code}/leave`, { pid: session.pid, token: session.token }); } catch { /* nada */ }
  dropSession(session.code);
  if (stream) stream.close();
  stream = null;
  session = null;
  state = null;
  resetTables();
  location.hash = "";
  showView("home");
  els.btnLeave.hidden = true;
  els.roomInfo.hidden = true;
}

/* ------------------------------------------------------------- sesión */
function startSession(initial) {
  showView("lobby");
  els.btnLeave.hidden = false;
  els.roomInfo.hidden = false;
  els.roomCodeText.textContent = session.code;
  els.roomPhase.textContent = "en línea";
  els.roomPhase.classList.add("is-live");
  if (initial) onState(initial);

  if (stream) stream.close();
  stream = connect(session.code, session.pid, session.token, {
    onState,
    onStatus: (s) => {
      els.roomPhase.textContent = s === "online" ? "en línea" : "reconectando…";
      els.roomPhase.classList.toggle("is-live", s === "online");
    },
    onGone: () => {
      toast("La mesa ya no existe (¿se reinició el servidor?)", "error");
      dropSession(session.code);
      if (stream) stream.close();
      stream = null;
      session = null;
      state = null;
      resetTables();
      location.hash = "";
      showView("home");
      els.btnLeave.hidden = true;
      els.roomInfo.hidden = true;
    },
  });

  if (clockTimer) clearInterval(clockTimer);
  clockTimer = setInterval(updateClock, 250);
}

function onState(next) {
  const first = !state;
  state = next;
  state.__sel = selected;
  // highlights del showdown
  if (state.game.result?.hands) {
    state.game.result.bestCards = {};
    for (const [pid, hand] of Object.entries(state.game.result.hands)) {
      state.game.result.bestCards[pid] = hand.best.map((c) => `${c.r}${c.s}`);
    }
  }

  if (first) renderAll();
  else {
    detectEffects();
    renderAll();
  }
  prev = state;
}

function detectEffects() {
  if (!prev) return;
  const a = prev.game || {};
  const b = state.game || {};
  if (b.hand_number !== a.hand_number) { sfx.deal(); selected = new Set(); }
  else if ((b.board || []).length !== (a.board || []).length) sfx.deal();
  if ((b.pot || 0) > (a.pot || 0)) sfx.chip();
  if (b.result && !a.result) {
    const mine = (b.result.winners || []).includes(state.you);
    if (mine) sfx.win(); else sfx.lose();
  }
  if (b.to_act === state.you && a.to_act !== state.you) sfx.turn();
}

/* ------------------------------------------------------------- render */
function renderAll() {
  const s = state;
  els.roomCodeText.textContent = s.code;
  els.roomPhase.textContent = s.phase === "lobby" ? "vestíbulo" : "en juego";
  els.roomPhase.classList.add("is-live");

  if (s.phase === "lobby") { showView("lobby"); renderLobby(); }
  else { showView("table"); renderTableView(); }

  renderSidebar();
  renderShowdown();
}

function renderLobby() {
  const s = state;
  const isHost = s.you === s.host;
  els.playerCount.textContent = `${s.players.length}/${s.settings.max_players}`;
  els.settingsHint.textContent = isHost ? "Puedes cambiarlos" : "Solo el anfitrión puede cambiarlos";

  els.lobbyPlayers.textContent = "";
  for (const p of s.players) {
    const li = document.createElement("li");
    const av = document.createElement("div");
    av.className = "avatar";
    av.style.background = p.color || "#3d8bfd";
    av.textContent = (p.name || "?").slice(0, 2).toUpperCase();
    const nm = document.createElement("span");
    nm.className = "pname";
    nm.textContent = p.name + (p.id === s.you ? " (tú)" : "");
    li.append(av, nm);
    if (p.id === s.host) {
      const b = document.createElement("span");
      b.className = "badge";
      b.textContent = "anfitrión";
      li.append(b);
    }
    if (p.is_bot) {
      const b = document.createElement("span");
      b.className = "badge badge--bot";
      b.textContent = "bot";
      li.append(b);
    }
    if (p.connected) {
      const b = document.createElement("span");
      b.className = "badge badge--ready";
      b.textContent = "en línea";
      li.append(b);
    }
    els.lobbyPlayers.append(li);
  }

  // ajustes
  const isBJ = s.settings.variant === "blackjack";
  els.fieldBb.hidden = isBJ;
  els.labelSb.textContent = isBJ ? "Ante por mano" : "Ciega pequeña";
  for (const btn of els.setVariant.children) {
    btn.classList.toggle("is-active", btn.dataset.value === s.settings.variant);
    btn.disabled = !isHost;
  }
  els.setSb.value = s.settings.small_blind;
  els.setBb.value = s.settings.big_blind;
  els.setStack.value = s.settings.start_stack;
  els.valSb.textContent = s.settings.small_blind;
  els.valBb.textContent = s.settings.big_blind;
  els.valStack.textContent = s.settings.start_stack;
  els.setSb.disabled = !isHost;
  els.setBb.disabled = !isHost;
  els.setStack.disabled = !isHost;

  const bots = s.settings.bots || 0;
  els.setBots.value = bots;
  els.valBots.textContent = bots;
  els.setBots.disabled = !isHost;
  els.setAutoFill.checked = !!s.settings.auto_fill;
  els.setAutoFill.disabled = !isHost;
  const hayBots = s.players.some((p) => p.is_bot);
  els.btnBots.textContent = hayBots ? "Quitar los bots" : "Rellenar mesa con bots";
  els.btnBots.disabled = !isHost;

  const ready = s.players.length >= 2;
  els.btnStart.disabled = !(isHost && ready);
  els.lobbyNote.textContent = ready
    ? (isHost ? "Cuando estéis todos, empieza la partida." : "Esperando a que el anfitrión empiece.")
    : "Comparte el código con tus amigos para que se unan.";

  renderChat(els.lobbyChat, s.chat);
}

function renderTableView() {
  const s = state;
  renderSeats(els.seats, s);
  renderBoard(els.board, s);
  renderPot(els.potBox, els.potValue, s);
  renderStreet(els.streetLabel, s);
  renderActions(els, s, {
    act: (action, amount) => sendAction(action, amount),
    discard: (idxs) => sendDiscard(idxs),
    getSelection: () => [...selected],
    canStartNext: () => s.you === s.host,
    nextHand: () => post("next", {}),
    rebuy: () => {
      const cantidad = s.settings.rebuy || s.settings.start_stack;
      post("rebuy", { amount: cantidad }).then((r) => {
        if (r && !r.error) toast(`Has recargado ${fmt(cantidad)} fichas`, "ok");
      });
    },
  });
}

function renderSidebar() {
  const s = state;
  els.logList.textContent = "";
  for (const entry of s.log || []) {
    const li = document.createElement("li");
    li.className = `kind-${entry.kind}`;
    li.textContent = entry.text;
    els.logList.append(li);
  }
  els.logList.scrollTop = els.logList.scrollHeight;
  renderChat(els.chatList, s.chat);

  els.scoreboard.textContent = "";
  const sorted = [...s.players].sort((a, b) => b.stack - a.stack);
  for (const p of sorted) {
    const li = document.createElement("li");
    const av = document.createElement("div");
    av.className = "avatar";
    av.style.background = p.color || "#3d8bfd";
    av.textContent = (p.name || "?").slice(0, 2).toUpperCase();
    const nm = document.createElement("div");
    nm.innerHTML = `<div>${escapeHtml(p.name)}</div><div class="sc-meta">${p.stats?.wins || 0} victorias · ${p.stats?.hands || 0} manos</div>`;
    const st = document.createElement("div");
    st.className = "sc-stack";
    st.textContent = fmt(p.stack);
    li.append(av, nm, st);
    if (p.id === s.you && p.stack <= 0) {
      const rec = document.createElement("button");
      rec.className = "btn btn--tiny btn--raise";
      rec.textContent = "+ Fichas";
      rec.addEventListener("click", () => {
        const cantidad = s.settings.rebuy || s.settings.start_stack;
        post("rebuy", { amount: cantidad }).then((r) => {
          if (r && !r.error) toast(`Has recargado ${fmt(cantidad)} fichas`, "ok");
        });
      });
      li.append(rec);
    }
    els.scoreboard.append(li);
  }
}

function renderChat(target, messages) {
  target.textContent = "";
  for (const m of messages || []) {
    const li = document.createElement("li");
    li.innerHTML = `<b>${escapeHtml(m.name)}</b> ${escapeHtml(m.text)}`;
    target.append(li);
  }
  target.scrollTop = target.scrollHeight;
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/* --------------------------------------------------------- showdown */
function renderShowdown() {
  const res = state.game.result;
  if (!res || state.game.phase !== "hand_over") { els.showdown.hidden = true; return; }
  const key = `${state.game.hand_number}:${JSON.stringify(res.winners)}`;
  if (showdownDismissedFor === key) { els.showdown.hidden = true; return; }
  els.showdown.hidden = false;

  const winners = res.winners || [];
  const isMine = winners.includes(state.you);
  const bj = res.type === "blackjack";
  els.showdownTitle.textContent = winners.length
    ? (isMine ? "¡Has ganado!" : winners.length > 1 ? "Empate" : `Gana ${playerName(winners[0])}`)
    : (bj ? "Nadie se pasó" : "Showdown");
  if (bj && winners.length === 1) {
    const h = res.hands?.[winners[0]];
    if (h) els.showdownTitle.textContent += ` con ${h.total} puntos`;
  }

  els.showdownBody.textContent = "";
  const rows = [...(res.hands || {})].sort((a, b) => {
    const ha = a[1], hb = b[1];
    return (hb.cat - ha.cat) || (hb.tie[0] - ha.tie[0]);
  });
  for (const [pid, hand] of rows) {
    const row = document.createElement("div");
    row.className = "showdown__row" + (winners.includes(pid) ? " is-winner" : "");
    const cards = document.createElement("div");
    cards.className = "sr-cards";
    for (const c of hand.cards || hand.best || []) cards.append(cardEl(c, "sm"));
    const txt = document.createElement("div");
    txt.innerHTML = `<div class="sr-name">${escapeHtml(playerName(pid))}</div><div class="sr-hand">${hand.name}</div>`;
    const amt = document.createElement("div");
    amt.className = "sr-amount";
    amt.textContent = res.payouts?.[pid] ? `+${fmt(res.payouts[pid])}` : "";
    row.append(cards, txt, amt);
    els.showdownBody.append(row);
  }
  if (bj && !winners.length) {
    const p = document.createElement("p");
    p.className = "hint";
    p.textContent = "Todos se pasaron de 21: el bote se devuelve a cada uno.";
    els.showdownBody.append(p);
  }
  if (res.type === "fold_win" && winners.length) {
    const p = document.createElement("p");
    p.className = "hint";
    p.textContent = "Todos los demás se retiraron: la mesa se lleva el bote sin enseñar cartas.";
    els.showdownBody.append(p);
  }
  els.showdownNext.textContent = state.you === state.host
    ? "Puedes pasar a la siguiente mano cuando quieras."
    : "La siguiente mano empieza en breve.";
  els.btnNextHand.hidden = state.you !== state.host;
}

function playerName(pid) {
  return state.players.find((p) => p.id === pid)?.name || "—";
}

/* ------------------------------------------------------------- reloj */
function updateClock() {
  if (!state) return;
  const deadline = state.turn_deadline;
  const g = state.game;
  const active = state.players.find((p) => p.is_to_act);

  if (active && active.id !== state.you && g.phase === "betting") {
    const html = `Turno de <b>${escapeHtml(active.name)}</b> <span class="countdown" id="turnClock"></span>`;
    if (els.actionStatus.dataset.turn !== html) {
      els.actionStatus.dataset.turn = html;
      els.actionStatus.innerHTML = html;
    }
  } else {
    els.actionStatus.dataset.turn = "";
  }

  const clock = document.getElementById("turnClock");
  if (clock) {
    if (deadline) {
      const left = Math.max(0, Math.round(deadline - Date.now() / 1000));
      clock.textContent = `${left}s`;
    } else clock.textContent = "";
  }

  for (const p of state.players) {
    const el = els.seats.querySelector(`.seat[data-pid="${p.id}"] .seat__timer i`);
    if (!el) continue;
    if (p.is_to_act && deadline) {
      const total = state.turn_seconds || 30;
      const left = Math.max(0, deadline - Date.now() / 1000);
      el.style.transition = "none";
      el.style.width = `${Math.max(0, Math.min(100, (left / total) * 100))}%`;
    } else {
      el.style.width = "0%";
    }
  }
}

/* ------------------------------------------------------------ acciones */
async function post(path, body) {
  if (!session) return null;
  try {
    const res = await api(`/api/rooms/${session.code}/${path}`, {
      pid: session.pid, token: session.token, ...body,
    });
    if (res.state) onState(res.state);
    return res;
  } catch (err) {
    toast(err.message, "error");
    return null;
  }
}

function sendAction(action, amount) {
  if (action === "fold") sfx.fold();
  else if (action === "check") sfx.check();
  else sfx.chip();
  post("action", { action, amount: amount || 0 });
}

function sendDiscard(idxs) {
  post("action", { action: "discard", indexes: idxs });
  selected = new Set();
  if (state) { state.__sel = selected; renderTableView(); }
}

/* ------------------------------------------------------------ eventos */
els.btnCreate.addEventListener("click", createRoom);
els.btnJoin.addEventListener("click", joinRoom);
els.inputCode.addEventListener("keydown", (e) => { if (e.key === "Enter") joinRoom(); });
els.inputName.addEventListener("keydown", (e) => { if (e.key === "Enter") createRoom(); });
els.btnLeave.addEventListener("click", leaveRoom);

els.roomCode.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(session.code);
    toast("Código copiado: " + session.code, "ok");
  } catch {
    toast("Código de la mesa: " + session.code);
  }
});

els.btnSound.addEventListener("click", () => {
  const muted = !isMuted();
  setMuted(muted);
  els.btnSound.classList.toggle("is-off", muted);
  els.btnSound.textContent = muted ? "♪̸" : "♪";
  if (!muted) sfx.click();
});

els.setVariant.addEventListener("click", (e) => {
  const btn = e.target.closest("button");
  if (!btn || btn.disabled) return;
  saveSettings({ variant: btn.dataset.value });
});
els.setSb.addEventListener("change", () => saveSettings({ small_blind: +els.setSb.value, big_blind: +els.setBb.value }));
els.setBb.addEventListener("change", () => saveSettings({ small_blind: +els.setSb.value, big_blind: +els.setBb.value }));
els.setStack.addEventListener("change", () => saveSettings({ start_stack: +els.setStack.value }));
els.setSb.addEventListener("input", () => { els.valSb.textContent = els.setSb.value; });
els.setBb.addEventListener("input", () => { els.valBb.textContent = els.setBb.value; });
els.setStack.addEventListener("input", () => { els.valStack.textContent = els.setStack.value; });

function saveSettings(settings) {
  post("settings", { settings });
}

els.setBots.addEventListener("input", () => { els.valBots.textContent = els.setBots.value; });
els.setBots.addEventListener("change", () => saveSettings({ bots: +els.setBots.value }));
els.setAutoFill.addEventListener("change", () => saveSettings({ auto_fill: els.setAutoFill.checked }));
els.btnBots.addEventListener("click", () => {
  const hayBots = state?.players?.some((p) => p.is_bot);
  post("bots", hayBots ? { remove: true } : { count: -1 });
});

els.btnStart.addEventListener("click", () => post("start", {}));

els.lobbyChatForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = els.lobbyChatInput.value.trim();
  if (!text) return;
  els.lobbyChatInput.value = "";
  post("chat", { text });
});
els.chatForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = els.chatInput.value.trim();
  if (!text) return;
  els.chatInput.value = "";
  post("chat", { text });
});

// barra de acciones
els.raiseRange.addEventListener("input", () => {
  els.raiseAmount.value = els.raiseRange.value;
});
els.raiseAmount.addEventListener("input", () => {
  const v = +els.raiseAmount.value;
  els.raiseRange.value = v;
});
els.raisePanel.addEventListener("click", (e) => {
  const btn = e.target.closest(".chip-btn");
  if (!btn || !state) return;
  const legal = state.me?.legal;
  if (!legal) return;
  const spec = legal.bet || legal.raise;
  if (!spec) return;
  const frac = btn.dataset.frac;
  const pot = state.game.pot || 0;
  const base = legal.bet ? 0 : state.game.current_bet || 0;
  let value;
  if (frac === "allin") value = spec.max;
  else value = Math.round(base + pot * parseFloat(frac));
  value = Math.max(spec.min, Math.min(spec.max, value));
  renderRaiseValue(els, value);
});
function confirmRaise() {
  const legal = state?.me?.legal;
  const spec = legal?.bet || legal?.raise;
  if (!spec) return;
  const value = +els.raiseAmount.value;
  const clamped = Math.max(spec.min, Math.min(spec.max, value || spec.min));
  els.raisePanel.hidden = true;
  sendAction(legal.bet ? "bet" : "raise", clamped);
}

els.raiseConfirm.addEventListener("click", confirmRaise);
els.raisePanel.addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); confirmRaise(); }
});

// selección de cartas para descartar
els.discardCards.addEventListener("click", (e) => {
  const card = e.target.closest(".card.is-selectable");
  if (!card) return;
  const idx = +card.dataset.idx;
  if (selected.has(idx)) { selected.delete(idx); card.classList.remove("is-selected"); }
  else { selected.add(idx); card.classList.add("is-selected"); }
  if (state) { state.__sel = selected; renderTableView(); }
});

// sidebar tabs
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("is-active", t === tab));
    const name = tab.dataset.tab;
    els.logList.hidden = name !== "log";
    els.chatList.hidden = name !== "chat";
    els.scoreboard.hidden = name !== "stats";
  });
});

// overlays
els.showdownClose.addEventListener("click", () => {
  els.showdown.hidden = true;
  if (state?.game.result) showdownDismissedFor = `${state.game.hand_number}:${JSON.stringify(state.game.result.winners)}`;
});
els.btnNextHand.addEventListener("click", () => post("next", {}));
els.btnHelp.addEventListener("click", () => { els.help.hidden = false; });
els.btnHelp2.addEventListener("click", () => { els.help.hidden = false; });
els.helpClose.addEventListener("click", () => { els.help.hidden = true; });
els.help.addEventListener("click", (e) => { if (e.target === els.help) els.help.hidden = true; });

window.addEventListener("hashchange", () => {
  const code = routeCode();
  if (!code) return;
  const stored = loadSession(code);
  if (stored && (!session || session.code !== code)) {
    session = stored;
    startSession(null);
  } else if (!stored) {
    els.inputCode.value = code;
    showView("home");
  }
});

window.addEventListener("resize", () => { if (state) renderTableView(); });

/* ------------------------------------------------------------- arranque */
(function boot() {
  els.btnSound.classList.toggle("is-off", isMuted());
  els.btnSound.textContent = isMuted() ? "♪̸" : "♪";

  const ranks = [
    ["Escalera Real", "10-J-Q-K-A del mismo palo"],
    ["Escalera de Color", "5 seguidas del mismo palo"],
    ["Póker", "4 cartas del mismo valor"],
    ["Full House", "Trío + pareja"],
    ["Color", "5 cartas del mismo palo"],
    ["Escalera", "5 seguidas de palos distintos"],
    ["Trío", "3 cartas del mismo valor"],
    ["Doble Pareja", "dos pares"],
    ["Pareja", "2 cartas del mismo valor"],
    ["Carta Alta", "sin combinación"],
  ];
  ranks.forEach(([name, desc], i) => {
    const row = document.createElement("div");
    row.className = "rank";
    row.innerHTML = `<b>${name}</b><span>${desc}</span><span class="n">${i + 1}</span>`;
    els.rankList.append(row);
  });

  const code = routeCode();
  if (code) {
    const stored = loadSession(code);
    if (stored) {
      session = stored;
      els.inputName.value = stored.name || "";
      startSession(null);
      return;
    }
    els.inputCode.value = code;
    els.homeError.textContent = `No hay sesión guardada para ${code}. Únete con tu nombre.`;
    els.homeError.hidden = false;
  }
  showView("home");
})();
