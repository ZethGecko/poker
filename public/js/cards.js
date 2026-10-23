/* Cartas, textos y sonidos (todo generado en el navegador, sin ficheros). */

export const SUIT = {
  s: { symbol: "♠", red: false, name: "picas" },
  h: { symbol: "♥", red: true, name: "corazones" },
  d: { symbol: "♦", red: true, name: "diamantes" },
  c: { symbol: "♣", red: false, name: "tréboles" },
};

export const RANK_LABEL = {
  2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8", 9: "9",
  10: "10", 11: "J", 12: "Q", 13: "K", 14: "A",
};

export function cardName(card) {
  return `${RANK_LABEL[card.r]} de ${SUIT[card.s].name}`;
}

export function cardEl(card, size = "md") {
  const el = document.createElement("div");
  const suit = SUIT[card.s] || SUIT.s;
  el.className = `card${suit.red ? " card--red" : ""}${size !== "md" ? ` card--${size}` : ""}`;
  el.dataset.rank = RANK_LABEL[card.r];
  el.dataset.suit = card.s;
  el.title = cardName(card);
  el.innerHTML =
    `<span class="card__corner">${RANK_LABEL[card.r]}<span class="pip">${suit.symbol}</span></span>` +
    `<span class="card__pip">${suit.symbol}</span>`;
  return el;
}

export function cardBackEl(size = "md") {
  const el = document.createElement("div");
  el.className = `card card--back${size !== "md" ? ` card--${size}` : ""}`;
  return el;
}

export function emptyCardEl() {
  const el = document.createElement("div");
  el.className = "card card--back";
  el.style.opacity = ".18";
  return el;
}

export const fmt = (n) => Number(n || 0).toLocaleString("es-ES");

/* ----------------------------------------------------------- sonidos */
let ctx = null;
let muted = localStorage.getItem("mesa-poker:mute") === "1";

function audio() {
  if (muted) return null;
  if (!ctx) {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    ctx = new AC();
  }
  if (ctx.state === "suspended") ctx.resume();
  return ctx;
}

export function setMuted(value) {
  muted = value;
  localStorage.setItem("mesa-poker:mute", value ? "1" : "0");
}

export function isMuted() {
  return muted;
}

function tone(freq, duration, type = "sine", gain = 0.06, delay = 0) {
  const ac = audio();
  if (!ac) return;
  const t0 = ac.currentTime + delay;
  const osc = ac.createOscillator();
  const vol = ac.createGain();
  osc.type = type;
  osc.frequency.setValueAtTime(freq, t0);
  vol.gain.setValueAtTime(0.0001, t0);
  vol.gain.exponentialRampToValueAtTime(gain, t0 + 0.012);
  vol.gain.exponentialRampToValueAtTime(0.0001, t0 + duration);
  osc.connect(vol).connect(ac.destination);
  osc.start(t0);
  osc.stop(t0 + duration + 0.05);
}

export const sfx = {
  deal() { tone(720, 0.09, "triangle", 0.045); tone(940, 0.07, "triangle", 0.03, 0.05); },
  chip() { tone(1180, 0.07, "square", 0.035); tone(760, 0.1, "square", 0.028, 0.05); },
  fold() { tone(300, 0.13, "sawtooth", 0.03); },
  check() { tone(540, 0.08, "sine", 0.04); },
  turn() { tone(880, 0.11, "sine", 0.05); tone(1180, 0.13, "sine", 0.045, 0.1); },
  win() {
    [523, 659, 784, 1046].forEach((f, i) => tone(f, 0.22, "triangle", 0.05, i * 0.09));
  },
  lose() { [420, 340, 260].forEach((f, i) => tone(f, 0.2, "sine", 0.04, i * 0.09)); },
  click() { tone(440, 0.045, "square", 0.02); },
};
