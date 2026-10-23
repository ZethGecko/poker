/* Render de la mesa: asientos, cartas comunitarias, pozo y barra de acciones. */

import { cardEl, cardBackEl, emptyCardEl, fmt, sfx } from "./cards.js";

const seatCache = new Map();
let lastPot = 0;

const ACTION_TEXT = {
  fold: "se retira", check: "pasa", call: "iguala", bet: "apuesta",
  raise: "sube", allin: "all-in", post: "ante", hit: "pide carta",
  stand: "se planta", bust: "se pasa",
};

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function initials(name) {
  return (name || "?").trim().slice(0, 2).toUpperCase();
}

/* ------------------------------------------------------------ asientos */
function buildSeat(p, state) {
  const root = document.createElement("div");
  root.className = "seat";
  root.dataset.pid = p.id;

  const cards = document.createElement("div");
  cards.className = "seat__cards";

  const body = document.createElement("div");
  body.className = "seat__body";

  const av = document.createElement("div");
  av.className = "avatar";
  av.style.background = p.color || "#3d8bfd";
  av.textContent = initials(p.name);

  const info = document.createElement("div");
  const name = document.createElement("div");
  name.className = "seat__name";
  const stack = document.createElement("div");
  stack.className = "seat__stack";

  const flag = document.createElement("span");
  flag.className = "seat__flag";
  flag.hidden = true;

  const botTag = document.createElement("span");
  botTag.className = "bot-tag";
  botTag.textContent = "bot";
  botTag.hidden = true;

  name.append(document.createTextNode(p.name), flag, botTag);
  info.append(name, stack);

  body.append(av, info);

  const bet = document.createElement("div");
  bet.className = "seat__bet";
  bet.hidden = true;

  const action = document.createElement("div");
  action.className = "seat__action";
  action.hidden = true;

  const total = document.createElement("div");
  total.className = "seat__total";
  total.hidden = true;

  const timer = document.createElement("div");
  timer.className = "seat__timer";
  const bar = document.createElement("i");
  timer.append(bar);

  root.append(cards, body, total, bet, action, timer);
  return { root, cards, name, stack, flag, botTag, bet, action, total, bar, cardsKey: null, body };
}

function updateSeat(entry, p, state) {
  const { root, cards, name, stack, flag, botTag, bet, action, total } = entry;
  const isMe = p.id === state.you;

  root.classList.toggle("is-me", isMe);
  root.classList.toggle("seat--me", isMe);
  root.classList.toggle("is-turn", !!p.is_to_act);
  root.classList.toggle("is-folded", !!p.folded);
  root.classList.toggle("is-out", p.stack <= 0 && !p.all_in);
  root.classList.toggle("is-winner", (state.game.result?.winners || []).includes(p.id));

  const label = p.name + (isMe ? " (tú)" : "");
  if (name.firstChild.nodeValue !== label) name.firstChild.nodeValue = label;
  flag.hidden = !p.is_button;
  if (p.is_button) flag.textContent = "D";
  botTag.hidden = !p.is_bot;
  stack.textContent = fmt(p.stack);

  bet.hidden = !p.bet;
  if (p.bet) bet.textContent = fmt(p.bet);

  const la = p.last_action;
  action.hidden = !la || la === "post";
  if (!action.hidden) {
    const text = ACTION_TEXT[la] || la;
    action.textContent = text;
    action.className = "seat__action" + (la === "fold" ? " is-fold" : la === "allin" || la === "bust" ? " is-allin" : "");
  }

  // total de la mano (black jack)
  if (p.total !== null && p.total !== undefined) {
    entry.total.hidden = false;
    entry.total.textContent = p.bust ? `${p.total}` : (p.natural ? "21 BJ" : `${p.total}`);
    entry.total.className = "seat__total" + (p.bust ? " is-bust" : p.natural ? " is-natural" : p.total === 21 ? " is-21" : "");
  } else {
    entry.total.hidden = true;
  }

  // cartas
  const best = state.game.result?.bestCards?.[p.id]?.join("") || "";
  const key = p.cards.map((c) => `${c.r}${c.s}`).join(",") + "|" + p.card_count + "|" + best;
  if (entry.cardsKey !== key) {
    entry.cardsKey = key;
    cards.textContent = "";
    const size = isMe && state.game.variant !== "draw" ? "md" : "sm";
    const count = p.card_count || 0;
    if (p.cards.length) {
      for (const c of p.cards) {
        const el = cardEl(c, size);
        if (best.includes(`${c.r}${c.s}`)) el.classList.add("is-best");
        cards.append(el);
      }
    } else {
      for (let i = 0; i < count; i++) cards.append(cardBackEl(size));
    }
  }
  return key;
}

export function renderSeats(seatsEl, state) {
  const visible = state.players;
  const myIdx = Math.max(0, visible.findIndex((p) => p.id === state.you));
  const n = visible.length;

  // crea / elimina asientos
  const seen = new Set();
  visible.forEach((p, i) => {
    seen.add(p.id);
    let entry = seatCache.get(p.id);
    if (!entry) {
      entry = buildSeat(p, state);
      seatCache.set(p.id, entry);
      seatsEl.append(entry.root);
    }
    updateSeat(entry, p, state);

    // posición: el jugador local abajo, el resto en sentido horario
    const rel = (i - myIdx + n) % n;
    const angle = ((90 + (360 * rel) / n) * Math.PI) / 180;
    const W = seatsEl.clientWidth || 1;
    const H = seatsEl.clientHeight || 1;
    const rx = W * 0.395;
    const ry = H * 0.335;
    const x = W / 2 + rx * Math.cos(angle);
    const y = H / 2 + ry * Math.sin(angle);
    entry.root.style.left = `${x}px`;
    entry.root.style.top = `${y}px`;
    entry.root.style.zIndex = rel === 0 ? 30 : 20 - rel;
  });

  for (const [pid, entry] of seatCache) {
    if (!seen.has(pid)) {
      entry.root.remove();
      seatCache.delete(pid);
    }
  }
}

/* ------------------------------------------------------------- tablero */
export function renderBoard(boardEl, state) {
  const g = state.game;
  const cards = g.board || [];
  boardEl.textContent = "";
  if (g.variant === "blackjack") {
    const target = document.createElement("div");
    target.className = "target";
    target.innerHTML =
      `<span class="target__num">${g.target || 21}</span>` +
      `<span class="target__label">BlackJack</span>`;
    boardEl.append(target);
    return;
  }
  const need = g.variant === "holdem" ? 5 : 0;
  for (let i = 0; i < need; i++) {
    if (i < cards.length) {
      const el = cardEl(cards[i]);
      boardEl.append(el);
    } else {
      boardEl.append(emptyCardEl());
    }
  }
  if (g.variant === "draw") {
    const label = document.createElement("div");
    label.className = "street";
    label.textContent = "Póker de mano · 5 cartas para cada uno";
    boardEl.append(label);
  }
}

export function renderPot(potBox, potValue, state) {
  const pot = state.game.pot || 0;
  if (pot !== lastPot) {
    lastPot = pot;
    potValue.textContent = fmt(pot);
    if (pot > 0) {
      potBox.classList.remove("is-big");
      void potBox.offsetWidth;
      potBox.classList.add("is-big");
    }
  }
}

export function renderStreet(streetLabel, state) {
  const g = state.game;
  const variante = {
    holdem: "Texas Hold'em", draw: "5-Card Draw", blackjack: "BlackJack",
  }[g.variant] || "";
  const parts = [];
  if (g.street_name && g.street_name !== variante) parts.push(g.street_name);
  if (variante) parts.push(variante);
  if (g.hand_number) parts.push(`mano ${g.hand_number}`);
  streetLabel.textContent = parts.join(" · ");
}

/* -------------------------------------------------------- barra de acción */
function actionButton(label, cls, onClick) {
  const b = document.createElement("button");
  b.className = `btn ${cls}`;
  b.textContent = label;
  b.addEventListener("click", () => { sfx.click(); onClick(); });
  return b;
}

export function renderActions(els, state, handlers) {
  const { actions, actionStatus, raisePanel, raiseRange, raiseAmount, raiseUnit,
    discardPanel, discardCards } = els;
  const me = state.me;
  const g = state.game;
  actions.textContent = "";
  raisePanel.hidden = true;
  discardPanel.hidden = true;

  if (!me) { actionStatus.textContent = "Espera a que empiece la partida…"; return; }

  // --- black jack: pedir carta o plantarse
  if (g.variant === "blackjack" && g.phase === "betting") {
    const legal = me.legal;
    if (!legal) {
      const turnPlayer = state.players.find((p) => p.is_to_act);
      actionStatus.innerHTML = turnPlayer
        ? `Turno de <b>${escapeHtml(turnPlayer.name)}</b>`
        : "Esperando…";
      return;
    }
    actionStatus.innerHTML =
      `Te toca. Tu mano suma <b>${legal.total}</b> <span class="countdown" id="turnClock"></span>`;
    actions.append(actionButton("Pedir carta", "btn--raise", () => handlers.act("hit")));
    actions.append(actionButton("Plantarse", "btn--check", () => handlers.act("stand")));
    actions.append(actionButton("Retirarse", "btn--fold", () => handlers.act("fold")));
    return;
  }

  // --- fase de descarte (5-card draw)
  if (g.phase === "discard" && me.can_discard) {
    const pending = g.discard_pending || [];
    actionStatus.innerHTML = `Fase de descarte: elige las cartas que quieres cambiar <span class="countdown">(${pending.length} por decidir)</span>`;
    const sel = handlers.getSelection ? handlers.getSelection() : [];
    discardPanel.hidden = false;
    discardCards.textContent = "";
    (me.cards || []).forEach((c, i) => {
      const el = cardEl(c, "md");
      el.classList.add("is-selectable");
      el.dataset.idx = String(i);
      if (sel.includes(i)) el.classList.add("is-selected");
      discardCards.append(el);
    });
    actions.append(
      actionButton(sel.length ? `Descartar ${sel.length}` : "No descartar", "btn--raise", () => handlers.discard(sel)),
    );
    return;
  }

  // jugador sin fichas: puede recargar entre manos
  if (me.stack <= 0 && g.phase !== "betting" && g.phase !== "discard") {
    const cantidad = state.settings.rebuy || state.settings.start_stack;
    actionStatus.innerHTML =
      `Te has quedado sin fichas. <b>Recarga ${fmt(cantidad)}</b> para seguir jugando.`;
    actions.append(
      actionButton(`Recargar ${fmt(cantidad)} fichas`, "btn--primary", handlers.rebuy)
    );
    return;
  }

  if (g.phase === "hand_over" || g.phase === "showdown") {
    const w = g.result?.winners || [];
    actionStatus.innerHTML = w.length
      ? `Mano terminada. Pulsa <b>Siguiente mano</b> para continuar.`
      : "Mano terminada.";
    if (handlers.canStartNext && handlers.canStartNext()) {
      actions.append(actionButton("Siguiente mano", "btn--primary", handlers.nextHand));
    }
    return;
  }

  if (g.phase !== "betting") { actionStatus.textContent = "…"; return; }

  const legal = me.legal;
  if (!legal) {
    const turnPlayer = state.players.find((p) => p.is_to_act);
    if (turnPlayer) {
      actionStatus.innerHTML = `Turno de <b>${turnPlayer.name}</b>`;
    } else {
      actionStatus.textContent = "Esperando…";
    }
    return;
  }

  actionStatus.innerHTML = `Te toca. <span class="countdown" id="turnClock"></span>`;

  actions.append(actionButton("Retirarse", "btn--fold", () => handlers.act("fold")));

  if (legal.check) {
    actions.append(actionButton("Pasar", "btn--check", () => handlers.act("check")));
  } else {
    const amount = legal.call || 0;
    actions.append(
      actionButton(amount > 0 ? `Igualar ${fmt(amount)}` : "Pasar", "btn--call", () => handlers.act("call"))
    );
  }

  const spec = legal.bet || legal.raise;
  if (spec) {
    const isRaise = !!legal.raise;
    const label = isRaise ? "Subir" : "Apostar";
    actions.append(
      actionButton(label, "btn--raise", () => {
        raisePanel.hidden = false;
        const min = spec.min;
        const max = spec.max;
        raiseRange.min = min;
        raiseRange.max = max;
        raiseRange.value = Math.min(Math.max(min, Math.round(min * 1.6)), max);
        raiseAmount.min = min;
        raiseAmount.max = max;
        raiseAmount.value = raiseRange.value;
        raiseUnit.textContent = isRaise ? "fichas (total en la calle)" : "fichas";
        raiseRange.focus();
      })
    );
  }
}

export function renderRaiseValue(els, value) {
  els.raiseAmount.value = value;
  els.raiseRange.value = value;
}

export function resetTables() {
  seatCache.clear();
  lastPot = 0;
}
