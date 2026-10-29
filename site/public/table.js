// duecrew.com/table, Pip Party (3.9.5; game night until its last round,
// and still in code): party games for a table of friends, from the host's
// own cards. One screen is the TV and holds the game: a window in Anki
// (You › Pip Party, or Tools › Due Crew › Pip Party), which opens a
// table on the API and hands this page tonight's pack (due_crew/gamenight.py)
// with window.dcAnki. Phones join with the code and answer in their
// presence (worker/src/table.ts passes presences round, marks only the TV's
// as the host's, and whispers each seat its own secret). Try it with bots
// runs the TV, a phone and three bots in the one window, with no table.
"use strict";
(() => {
let D = null;  // tonight's pack, from Anki (in the lobby and a game, the vote's part of it)
let ALL = null;  // the whole of it
const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;
const NS = "http://www.w3.org/2000/svg";

// ---------- helpers ----------
function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v == null) continue;
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (k === "value") e.value = v;
    else e.setAttribute(k, v === true ? "" : String(v));
  }
  for (const c of kids.flat(Infinity)) if (c != null && c !== false && c !== "") e.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return e;
}
function svgEl(tag, attrs) { const e = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, String(v)); return e; }
const rnd = () => Math.random();
const int = (n) => Math.floor(rnd() * n);
const pick = (a) => a[int(a.length)];
function shuffle(a) { const b = a.slice(); for (let i = b.length - 1; i > 0; i--) { const j = int(i + 1); [b[i], b[j]] = [b[j], b[i]]; } return b; }
const norm = (w) => String(w == null ? "" : w).toLowerCase().replace(/[^a-z0-9]/g, "");
const clip = (w, n) => String(w || "").replace(/[\u0000-\u001f\u007f\u200b-\u200f\u2028-\u202e\u2060-\u206f\ufeff]/g, "").trim().slice(0, n);
const plural = (n, a, b) => `${n} ${n === 1 ? a : b}`;
const clone = (v) => (v === undefined ? undefined : JSON.parse(JSON.stringify(v)));
const merge = (obj, patch) => { const o = Object.assign({}, obj); for (const [k, v] of Object.entries(patch)) { if (v === null) delete o[k]; else o[k] = clone(v); } return o; };
const you = (n) => n === "You";
const says = (n, mine, theirs) => (you(n) ? mine : `${n} ${theirs}`);  // says("Maya", "You have", "has") is "Maya has"
const poss = (n) => (you(n) ? "your" : `${n}'s`);
const Poss = (n) => (you(n) ? "Your" : `${n}'s`);
const frag = (...kids) => h("div", { class: "stack" }, ...kids);
const btn = (label, fn, cls) => h("button", { type: "button", class: "btn" + (cls ? " " + cls : ""), onclick: fn }, label);
const warn = (e) => console.warn("pip party:", e && (e.code || e.message || e));
// Pip (sev.js, the add-on's own drawing): at a place of the night's, moving; a seat's, still, in its colour
const pip = (place, size, accent) => (typeof Sev !== "undefined" && Sev.stage ? Sev.stage(place, size, accent) : null);
const SEAT_COLORS = [["#2e7d32", "#7cc47f"], ["#3b6fd8", "#8fb0ff"], ["#7b4fc9", "#b9a2f2"], ["#00897b", "#5fd3c2"], ["#b26a00", "#dda45c"], ["#b03a6b", "#e58bb0"]];
const seatPip = (i, label, pair) => (typeof Sev !== "undefined" && Sev.row ? Sev.row([], pair || SEAT_COLORS[i % SEAT_COLORS.length], label) : null);
const REACTS = ["🎉", "😂", "😮", "👏", "❤️"];

// ---------- drawings: strokes as text, two characters a point ----------
const ALPHA = (() => { let s = ""; for (let c = 33; c <= 126; c++) if (c !== 34 && c !== 92) s += String.fromCharCode(c); return s; })();
const G = ALPHA.length - 1;
const enc = (x, y) => ALPHA[x] + ALPHA[y];
function decode(strokes) {
  return (Array.isArray(strokes) ? strokes : []).filter((s) => typeof s === "string").map((s) => {
    const pts = [];
    for (let i = 0; i + 1 < s.length; i += 2) { const x = ALPHA.indexOf(s[i]), y = ALPHA.indexOf(s[i + 1]); if (x >= 0 && y >= 0) pts.push([x, y]); }
    return pts;
  });
}
function drawingSvg(strokes, cls) {
  const svg = svgEl("svg", { viewBox: `-3 -3 ${G + 6} ${G + 6}`, class: cls || "dw", role: "img", "aria-label": "A drawing" });
  for (const pts of decode(strokes)) {
    if (!pts.length) continue;
    if (pts.length === 1) svg.append(svgEl("circle", { cx: pts[0][0], cy: pts[0][1], r: 1.2 }));
    else svg.append(svgEl("polyline", { points: pts.map((p) => p.join(",")).join(" ") }));
  }
  return svg;
}
function pad(onChange) {
  const MAX = 2800, strokes = [];
  let cur = null, last = null;
  const cv = h("canvas", { class: "pad", width: 600, height: 600, "aria-label": "Draw here" });
  const g = cv.getContext("2d");
  const used = () => strokes.reduce((n, s) => n + s.length, 0) + (cur ? cur.length : 0);
  let color = "";
  const pen = () => { g.lineWidth = 10; g.lineCap = "round"; g.lineJoin = "round"; g.strokeStyle = color || (color = getComputedStyle(cv).color || "#222"); };
  const px = (v) => (v / G) * 600;
  function piece(a, b) { pen(); g.beginPath(); g.moveTo(px(a[0]), px(a[1])); g.lineTo(px(b[0]) + (a === b ? 0.5 : 0), px(b[1])); g.stroke(); }
  function paint() {
    g.clearRect(0, 0, 600, 600);
    color = "";
    pen();
    for (const s of cur ? strokes.concat([cur]) : strokes) {
      const pts = decode([s])[0];
      if (!pts.length) continue;
      g.beginPath();
      pts.forEach(([x, y], i) => { const X = (x / G) * 600, Y = (y / G) * 600; if (i) g.lineTo(X, Y); else g.moveTo(X, Y); });
      if (pts.length === 1) g.lineTo((pts[0][0] / G) * 600 + 0.5, (pts[0][1] / G) * 600);
      g.stroke();
    }
  }
  const at = (e) => { const r = cv.getBoundingClientRect(); const f = (v, a, b) => Math.max(0, Math.min(G, Math.round(((v - a) / b) * G))); return [f(e.clientX, r.left, r.width), f(e.clientY, r.top, r.height)]; };
  cv.addEventListener("pointerdown", (e) => { if (used() + 2 > MAX) return; e.preventDefault(); try { cv.setPointerCapture(e.pointerId); } catch (_) { /* fine */ } const [x, y] = at(e); cur = enc(x, y); last = [x, y]; piece(last, last); onChange(); });
  cv.addEventListener("pointermove", (e) => {
    if (cur == null) return;
    const [x, y] = at(e);
    if (Math.abs(x - last[0]) + Math.abs(y - last[1]) < 2 || used() + 2 > MAX) return;
    const was = last;
    cur += enc(x, y); last = [x, y];
    if (cur.length >= 996) { strokes.push(cur); cur = enc(x, y); }
    piece(was, last); onChange();  // only the new piece; undo and clear paint it all
  });
  const end = () => { if (cur != null) { strokes.push(cur); cur = null; onChange(); } };
  cv.addEventListener("pointerup", end);
  cv.addEventListener("pointercancel", end);
  return { el: cv, strokes: () => strokes.slice(0, 12), undo() { strokes.pop(); paint(); onChange(); }, clear() { strokes.length = 0; paint(); onChange(); }, left: () => Math.max(0, 1 - used() / MAX), repaint: paint };
}

// ---------- the dial (Somewhere between) ----------
function dial(o) {
  const cx = 180, cy = 176, R = 146;
  const pt = (v, r) => { const a = Math.PI * (1 - v / 100); return [cx + r * Math.cos(a), cy - r * Math.sin(a)]; };
  const arc = (v1, v2, r) => { const [x1, y1] = pt(v1, r), [x2, y2] = pt(v2, r); return `M${x1.toFixed(1)} ${y1.toFixed(1)} A ${r} ${r} 0 0 1 ${x2.toFixed(1)} ${y2.toFixed(1)}`; };
  const svg = svgEl("svg", { viewBox: "0 0 360 196", class: "dial", role: "img", "aria-label": o.target != null ? `Target at ${o.target} of 100` : "The dial" });
  svg.append(svgEl("path", { d: arc(0, 100, R), class: "d-base" }));
  if (o.target != null) {
    for (const [w, cls] of [[15, "d-b2"], [9, "d-b3"], [4, "d-b4"]]) svg.append(svgEl("path", { d: arc(Math.max(0, o.target - w), Math.min(100, o.target + w), R), class: cls }));
  }
  for (const [v, name] of o.dots || []) { const [x, y] = pt(v, R); const c = svgEl("circle", { cx: x.toFixed(1), cy: y.toFixed(1), r: 6, class: "d-dot" }); const t = svgEl("title", {}); t.textContent = `${name}: ${v}`; c.append(t); svg.append(c); }
  if (o.needle != null) { const [x, y] = pt(o.needle, R - 10); svg.append(svgEl("line", { x1: cx, y1: cy, x2: x.toFixed(1), y2: y.toFixed(1), class: "d-needle" })); }
  svg.append(svgEl("circle", { cx, cy, r: 8, class: "d-hub" }));
  return h("div", { class: "dialw" }, svg, h("div", { class: "ends" }, h("span", {}, o.L), h("span", {}, o.R)));
}

// ---------- trivia's shapes ----------
const SHAPES = ['<path d="M12 3 L22 20 L2 20 Z"/>', '<path d="M12 2 L22 12 L12 22 L2 12 Z"/>', '<circle cx="12" cy="12" r="10"/>', '<rect x="3" y="3" width="18" height="18" rx="2"/>'];
const SHAPE_NAMES = ["Triangle", "Diamond", "Circle", "Square"];
const shape = (i) => { const s = h("span", { class: "shp", "aria-hidden": "true" }); s.innerHTML = `<svg viewBox="0 0 24 24">${SHAPES[i]}</svg>`; return s; };

// ---------- the games ----------
// Each one: start(ctx) → state; pub(state, ctx), what every phone may see;
// secrets(state, ctx), what one seat sees (a hand, a topic, the key),
// whispered to that phone alone; collect/force/timeout move it on; tv and
// phone draw it; bot is a stand-in player (Try it with bots).
const seatsBut = (c, i) => c.seats.map((_, k) => k).filter((k) => k !== i);

const Imposter = {
  id: "imposter", name: "Imposter", kind: "Find the odd one out", min: 3, max: 8,
  line: "Every phone shows the topic but the imposter's. A word each round the room, then vote.",
  learn: "A topic in one word, and what it's easy to mix up with.",
  start(c) {
    const pr = pick(D.twins.slice(0, Math.max(3, Math.ceil(D.twins.length / 2))));  // the likeliest mix-ups come first
    const [A, B] = rnd() < 0.5 ? [pr.a, pr.b] : [pr.b, pr.a];  // the topic, and its twin: the guess's closest wrong answer
    const first = int(c.N), order = c.seats.map((_, k) => (first + k) % c.N);  // round the room from someone, said out loud
    return { ph: "clue", laps: Imposter.laps, order, a: A.t, b: B.t, facts: { a: A.facts || [], b: B.facts || [] }, part: pr.part, imp: int(c.N), votes: null, last: null, opts: null, caught: null, most: null };
  },
  pub(S) {
    const x = { ph: S.ph, laps: S.laps, part: S.part, order: S.order };
    if (S.ph === "last" || S.ph === "end") Object.assign(x, { imp: S.imp, votes: S.votes, caught: S.caught });
    if (S.ph === "last") x.opts = S.opts;
    if (S.ph === "end") Object.assign(x, { a: S.a, last: S.last });  // the topic, every phone's, once the guess is in
    return x;
  },
  secrets(S, c) { return c.seats.map((_, i) => (i === S.imp ? { imp: 1 } : { top: S.a })); },
  collect(S, A, c) {
    const all = (f) => A.every((a, i) => (a && f(a)) || !c.here(i));
    if (S.ph === "vote" && (c.N < 2 || all((a) => Number.isInteger(a.v)))) return Imposter.force(S, c);  // alone, nobody to vote for
    if (S.ph === "last" && A[S.imp] && typeof A[S.imp].g === "string") return Imposter.force(S, c);
    return null;  // the words are said round the room; the TV's Vote ends them
  },
  force(S, c) {
    const A = c.A;
    if (S.ph === "clue") return Object.assign({}, S, { ph: "vote" });
    if (S.ph === "vote") {
      const votes = A.map((a, i) => (a && Number.isInteger(a.v) && a.v >= 0 && a.v < c.N && a.v !== i ? a.v : -1));
      const tally = Array(c.N).fill(0);
      votes.forEach((v) => { if (v >= 0) tally[v]++; });
      const top = Math.max(0, ...tally);
      const most = top ? tally.map((n, i) => (n === top ? i : -1)).filter((i) => i >= 0) : [];
      if (most.length === 1 && most[0] === S.imp) {
        const names = D.twins.flatMap((t) => [t.a.t, t.b.t]).concat(D.prompts);
        const others = shuffle([...new Set(names)].filter((t) => norm(t) !== norm(S.a) && norm(t) !== norm(S.b))).slice(0, 2);
        return Object.assign({}, S, { ph: "last", votes, caught: true, most, opts: shuffle([S.a, S.b].concat(others)) });
      }
      return Object.assign({}, S, { ph: "end", votes, caught: false, most });
    }
    if (S.ph === "last") {
      const a = A[S.imp];
      return Object.assign({}, S, { ph: "end", last: a && typeof a.g === "string" ? clip(a.g, 40) : "" });
    }
    return null;
  },
  laps: 2,  // once or twice round: the TV's pick, kept for Another round
  // what tells the two apart, as their cards say it: each card's sentence, its answer in bold
  apart(S) {
    const fact = (f) => {
      if (typeof f === "string" || !f.s) return h("li", {}, typeof f === "string" ? f : f.a);
      const at = f.s.toLowerCase().indexOf(String(f.a).toLowerCase());
      return at < 0 ? h("li", {}, f.s) : h("li", {}, f.s.slice(0, at), h("b", {}, f.s.slice(at, at + f.a.length)), f.s.slice(at + f.a.length));
    };
    return h("div", { class: "apart" }, [[S.a, S.facts.a], [S.b, S.facts.b]].map(([t, facts], k) => h("div", { class: k ? "them" : "" }, h("b", {}, t), h("ul", {}, (facts || []).map(fact)))));
  },
  tv(S, c) {
    const A = c.A, nm = c.name;
    const head = h("div", { class: "sub" }, `Imposter · ${S.part}`);
    const status = (f) => h("div", { class: "ppl" }, c.seats.map((_, i) => { const ok = A[i] && f(A[i]); return h("span", { class: ok ? "ok" : "" }, nm(i), ok ? " ✓" : ""); }));
    if (S.ph === "clue") {  // the TV sets the order; the words are said out loud
      const first = nm(S.order[0]);
      return frag(head, h("div", { class: "h" }, you(first) ? "You start." : `${first} starts.`),
        h("div", { class: "ppl big order" }, S.order.map((i, k) => h("span", {}, h("i", {}, `${k + 1}`), nm(i)))),
        h("div", { class: "row" }, h("span", { class: "seg" }, [[1, "Once round"], [2, "Twice round"]].map(([n, label]) => h("button", { type: "button", "aria-pressed": String(S.laps === n),
          onclick: () => { Imposter.laps = n; c.set(Object.assign({}, S, { laps: n })); } }, label))),
          h("button", { type: "button", class: "btn", "data-next": "", onclick: () => c.go(Imposter.force(S, c)) }, "Vote")));
    }
    if (S.ph === "vote") return frag(head, h("div", { class: "h" }, "Who's the imposter?"), status((a) => Number.isInteger(a.v)));
    const imp = nm(S.imp);
    if (S.ph === "last") return frag(head, h("div", { class: "h" }, `Caught: ${you(imp) ? "you" : imp}.`), h("p", { class: "lead" }, `${says(imp, "You get", "gets")} one guess at the topic.`));
    const named = S.caught && norm(S.last) === norm(S.a);
    const headline = !S.caught ? `${imp} got away.` : named ? `${imp} named it and ${you(imp) ? "get" : "gets"} away.` : `Caught: ${you(imp) ? "you" : imp}.`;
    const why = !S.caught ? (S.most && S.most.length > 1 ? "The votes tied." : S.most && S.most.length ? `The votes landed on ${S.most.map(nm).join(" and ")}.` : "Nobody voted.") : named ? "" : S.last ? `Guessed ${S.last}.` : "";
    const tally = Array(c.N).fill(0);
    (S.votes || []).forEach((v) => { if (v >= 0) tally[v]++; });
    return frag(head, h("div", { class: "h" }, headline), h("p", { class: "lead" }, [why, `The topic was ${S.a}.`].filter(Boolean).join(" ")),
      h("div", { class: "ppl" }, c.seats.map((_, i) => h("span", { class: i === S.imp ? "bad" : "" }, nm(i), tally[i] ? h("i", {}, " " + plural(tally[i], "vote", "votes")) : null))),
      S.facts.a.length || S.facts.b.length ? frag(h("div", { class: "lbl" }, "What tells them apart"), Imposter.apart(S)) : null,
      h("div", { class: "row" }, btn("Another round", () => c.again()), btn("Back to games", () => c.lobby(), "plain")));
  },
  // a phone: the topic, or that it's the imposter's and has none
  phone(x, seat, p) {
    const me = p.me, mine = p.mine();
    if (!me || (!me.top && !me.imp)) return h("p", { class: "small" }, "…");
    const card = me.imp ? h("div", { class: "secret imp" }, h("div", { class: "big" }, "You're the imposter"))
      : h("div", { class: "secret" }, h("div", { class: "small" }, "The topic"), h("div", { class: "big" }, me.top));
    if (x.ph === "clue") return card;
    if (x.ph === "vote") {
      if (mine) return frag(h("div", { class: "big" }, `You voted ${p.name(mine.v)}.`));
      return frag(h("div", { class: "who" }, "Who's the imposter?"), h("div", { class: "vote" }, p.seats.map((_, i) => (i === seat ? null : h("button", { type: "button", onclick: () => p.answer({ v: i }) }, p.name(i))))), card);
    }
    if (x.ph === "last") {
      if (seat !== x.imp) return frag(h("div", { class: "big" }, `Caught: ${p.name(x.imp)}.`), h("p", { class: "small" }, "One guess left for them."));
      if (mine) return frag(h("div", { class: "big" }, `You guessed ${mine.g}.`));
      return frag(h("div", { class: "who" }, "Caught"), h("div", { class: "big" }, "What's the topic?"),
        h("div", { class: "vote" }, (x.opts || []).map((o) => h("button", { type: "button", onclick: () => p.answer({ g: o }) }, o))));
    }
    return frag(h("div", { class: "who" }, me.imp ? "You were the imposter" : `${p.name(x.imp)} was the imposter`), h("div", { class: "small" }, "The topic"), h("div", { class: "big" }, x.a));
  },
  mood(S) { return { clue: "peek", vote: "focus", last: "ready" }[S.ph] || (S.caught && norm(S.last) !== norm(S.a) ? "cheer" : "peek"); },
  bot(x, seat, b) {
    if (x.ph === "vote") { const o = seatsBut(b, seat); return o.length ? { a: { v: pick(o) } } : null; }
    if (x.ph === "last" && seat === x.imp) return { a: { g: pick(x.opts || [""]) } };
    return null;
  },
};

function fixRound(S) {
  const ans = D.blacks[S.order[S.bi]].a;
  if (!ans) return Object.assign({}, S);  // a written card: no answer to deal
  const hands = S.hands.map((hd) => hd.slice());
  const deck = S.deck.filter((x) => norm(x) !== norm(ans));
  const ai = S.att >= 0 ? hands[S.att].findIndex((x) => norm(x) === norm(ans)) : -1;
  if (ai >= 0) hands[S.att].splice(ai, 1, ...deck.splice(0, 1));  // the Attending doesn't play it; next round refills
  const holders = hands.map((hd, i) => (i !== S.att && hd.some((x) => norm(x) === norm(ans)) ? i : -1)).filter((i) => i >= 0);
  if (!holders.length) {
    const j = pick(hands.map((_, i) => i).filter((i) => i !== S.att));
    if (j != null && hands[j].length) {
      const k = int(hands[j].length);
      deck.push(hands[j][k]);
      hands[j][k] = ans;
    }
  }
  return Object.assign({}, S, { hands, deck });
}
const Rounds = {
  id: "rounds", name: "Rounds", kind: "Fill in the blank", min: 3, max: 8, HAND: 7,
  line: "One of your cards with its answer blanked, or one of Pip's. Everyone plays an answer from your other cards. The Attending picks a favorite, then the card says what it really was.",
  learn: "A wrong card is only funny if you know why it's wrong.",
  // a hand's size: seven, or an even share of a small pack's cards
  per(N) { return Math.max(1, Math.min(Rounds.HAND, Math.floor(D.whites.length / Math.max(1, N)))); },
  start(c) {
    const deck = shuffle(D.whites);
    const per = Rounds.per(c.N);
    const hands = c.seats.map(() => deck.splice(0, per));
    // a written card (w) has no answer: only an Attending's pick makes it a round, so alone there are none
    const order = shuffle(D.blacks.map((_, i) => i).filter((i) => c.N > 1 || !D.blacks[i].w));
    return fixRound({ per, ph: "play", att: c.N > 1 ? 1 % c.N : -1, order, bi: 0, hands, deck, played: null, flip: null, fseat: null, fav: null });
  },
  pub(S) {
    const b = D.blacks[S.order[S.bi]];
    const x = { ph: S.ph, att: S.att, black: b.q };
    if (S.ph !== "play") x.flip = S.flip;
    if (S.ph === "chart") Object.assign(x, { fav: S.fav, fseat: S.fseat, ans: b.a, w: b.w ? 1 : 0 });
    return x;
  },
  secrets(S, c) { return c.seats.map((_, i) => ({ hand: S.hands[i] || [] })); },
  collect(S, A, c) {
    if (S.ph === "play" && c.seats.every((_, i) => i === S.att || !c.here(i) || (A[i] && typeof A[i].c === "string"))) return Rounds.force(S, c);
    if (S.ph === "pick" && A[S.att] && Number.isInteger(A[S.att].f)) return Rounds.force(S, c);
    return null;
  },
  force(S, c) {
    const A = c.A;
    if (S.ph === "play") {
      const seats = c.seats.map((_, i) => i).filter((i) => i !== S.att && A[i] && typeof A[i].c === "string" && S.hands[i].includes(A[i].c));
      if (!seats.length) return null;
      const fseat = shuffle(seats);
      const played = c.seats.map((_, i) => (seats.includes(i) ? A[i].c : null));
      return Object.assign({}, S, { ph: S.att < 0 ? "chart" : "pick", played, fseat, flip: fseat.map((i) => played[i]) });
    }
    if (S.ph === "pick") {
      const a = A[S.att];
      const f = a && Number.isInteger(a.f) && a.f >= 0 && a.f < S.flip.length ? a.f : int(S.flip.length);
      return Object.assign({}, S, { ph: "chart", fav: f });
    }
    return null;
  },
  next(S, c) {
    let deck = S.deck.slice();
    const hands = S.hands.map((hd, i) => hd.filter((x) => x !== (S.played && S.played[i])));
    const held = new Set(hands.flat().map(norm));  // no card twice, in a hand or across them
    for (const keep of hands) {
      while (keep.length < (S.per || Rounds.HAND)) {
        if (!deck.length) deck = shuffle(D.whites.filter((x) => !held.has(norm(x))));
        if (!deck.length) break;
        const x = deck.shift();
        if (held.has(norm(x))) continue;
        held.add(norm(x));
        keep.push(x);
      }
    }
    return fixRound(Object.assign({}, S, { ph: "play", att: S.att < 0 ? -1 : (S.att + 1) % c.N, bi: (S.bi + 1) % S.order.length, hands, deck, played: null, flip: null, fseat: null, fav: null }));
  },
  tv(S, c) {
    const b = D.blacks[S.order[S.bi]], att = c.name(S.att), A = c.A, alone = S.att < 0;
    const black = h("div", { class: "black" }, h("p", {}, b.q), h("small", {}, alone ? b.tag : `${b.tag ? b.tag + " · " : ""}the Attending: ${att}`));
    if (S.ph === "play") {
      const others = c.seats.map((_, i) => i).filter((i) => i !== S.att);
      return frag(black, h("p", { class: "lead" }, alone ? "Play a card." : `${you(att) ? "You read" : att + " reads"} it out. Everyone else, play a card.`),
        h("div", { class: "whites" }, others.map((i) => { const ok = A[i] && A[i].c; return h("div", { class: "white down" + (ok ? " ok" : "") }, ok ? "Played" : "", h("small", {}, c.name(i))); })));
    }
    const right = (card) => norm(card) === norm(b.a);
    const cards = h("div", { class: "whites" }, S.flip.map((card, k) => {
      const fav = S.ph === "chart" && k === S.fav, ok = S.ph === "chart" && right(card);
      return h("div", { class: ["white", fav ? "fav" : "", ok ? "right" : ""].join(" ") }, card, h("small", {}, S.ph === "chart" ? c.name(S.fseat[k]) : ""));
    }));
    if (S.ph === "pick") return frag(black, cards, h("p", { class: "lead" }, `${says(att, "You pick", "picks")} a favorite.`));
    const rightBy = S.fseat.filter((_, k) => right(S.flip[k])).map(c.name);
    return frag(black, cards,
      alone ? null : h("div", { class: "honor" }, h("b", { class: "f" }, `${Poss(att)} pick:`), ` “${S.flip[S.fav]}”, ${you(c.name(S.fseat[S.fav])) ? "yours" : c.name(S.fseat[S.fav]) + "'s"}.`),
      b.w ? null : h("div", { class: "honor" }, h("b", { class: "c" }, `The card says: ${b.a}.`), rightBy.length ? ` ${rightBy.join(" and ")} played it.` : " Nobody played it."),
      b.full ? h("p", { class: "sub" }, b.full) : null,
      h("div", { class: "row" }, btn(alone ? "Next round" : `Next round: ${you(c.name((S.att + 1) % c.N)) ? "you're" : c.name((S.att + 1) % c.N) + "'s"} the Attending`, () => c.go(Rounds.next(S, c))), btn("Back to games", () => c.lobby(), "plain")));
  },
  phone(x, seat, p) {
    const mine = p.mine(), att = p.name(x.att), hand = (p.me && p.me.hand) || [];
    const black = h("div", { class: "black sm" }, h("p", {}, x.black));
    const card = (t, extra, fn) => h(fn ? "button" : "div", Object.assign({ class: "white" + (extra || "") }, fn ? { type: "button", onclick: fn } : {}), t);
    if (x.ph === "play") {
      if (seat === x.att) return frag(h("div", { class: "who" }, "You're the Attending"), black, h("p", { class: "small" }, "Read it out. You pick a favorite once the cards are in."));
      if (mine) return frag(h("div", { class: "who" }, "Played"), card(mine.c));
      return frag(h("div", { class: "who" }, x.att < 0 ? "Play a card" : `${att}'s the Attending`), black, h("div", { class: "hand" }, hand.map((t) => card(t, "", () => p.answer({ c: t })))));
    }
    if (x.ph === "pick") {
      if (seat !== x.att) return frag(h("div", { class: "big" }, `${att}'s picking.`));
      if (mine) return frag(h("div", { class: "big" }, "Picked."));
      return frag(h("div", { class: "who" }, "Pick a favorite"), black, h("div", { class: "hand" }, (x.flip || []).map((t, k) => card(t, "", () => p.answer({ f: k })))));
    }
    const k = (x.fseat || []).indexOf(seat), myCard = k >= 0 ? x.flip[k] : null, ok = myCard && !x.w && norm(myCard) === norm(x.ans);
    const lines = [];
    if (myCard && k === x.fav && x.att >= 0) lines.push(`${att} picked yours.`);
    if (ok) lines.push("That's the card's answer.");
    const top = x.w ? (seat === x.att ? `You picked “${(x.flip || [])[x.fav] || ""}”` : `${Poss(att)} pick: “${(x.flip || [])[x.fav] || ""}”`) : `The card says: ${x.ans}`;
    return frag(h("div", { class: "who" }, top), myCard ? card(myCard, (k === x.fav ? " fav" : "") + (ok ? " right" : "")) : null, lines.length ? h("p", { class: "small" }, lines.join(" ")) : null);
  },
  mood(S) { if (S.ph !== "chart") return "focus"; const b = D.blacks[S.order[S.bi]]; return b.w || S.flip.some((card) => norm(card) === norm(b.a)) ? "hop" : "peek"; },
  bot(x, seat, b) {
    if (x.ph === "play" && seat !== x.att) { const hand = (b.me && b.me.hand) || []; return hand.length ? { a: { c: pick(hand) } } : null; }
    if (x.ph === "pick" && seat === x.att) return { a: { f: int((x.flip || [0]).length) } };
    return null;
  },
};

const Trivia = {
  id: "trivia", name: "Trivia", kind: "Quiz", min: 1, max: 8, SECS: 20,
  line: "Your cards on the TV, four shapes on every phone. Most of you right on 7 of 10 clears the block.",
  learn: "Recall, ten at a time, and the card after each.",
  TOPIC_MIN: 6,  // a subject's questions for a block of its own
  // a question's subject for a topic round: the pack's ("Renal", gamenight.rounds), else its topic
  subj: (q) => q.round || q.tag || "",
  // tonight's subjects with a block's worth of questions, the most first; none when the table voted on what to play (round three)
  topics() {
    if (Vote.subs(D).length >= 2) return [];
    const n = {};
    for (const q of D.qs) { const t = Trivia.subj(q); if (t) n[t] = (n[t] || 0) + 1; }
    return Object.keys(n).filter((t) => n[t] >= Trivia.TOPIC_MIN).sort((a, b) => n[b] - n[a]).slice(0, 8).map((t) => [t, n[t]]);
  },
  // two topics or more: the TV picks one, or mixes them; fewer: a mixed block
  start() {
    const ts = Trivia.topics();
    return ts.length >= 2 ? { ph: "topic", ts, k: 0, qs: [], log: [], gots: [], res: null, call: null, ends: 0, topic: null } : Trivia.block(null);
  },
  block(topic) {
    const qs = shuffle(topic ? D.qs.filter((q) => Trivia.subj(q) === topic) : D.qs).slice(0, 10);
    return { ph: "ask", k: 0, qs, ends: Date.now() + Trivia.SECS * 1000, call: null, log: [], gots: [], res: null, topic, ts: Trivia.topics() };
  },
  // the card after the reveal: its sentence with the answer in bold, and its Extra (the TV's alone)
  card(q) {
    if (!q.full && !q.extra) return null;
    let say = null;
    if (q.full) {
      const at = q.full.toLowerCase().indexOf(String(q.a).toLowerCase());
      say = at < 0 ? h("p", {}, q.full) : h("p", {}, q.full.slice(0, at), h("b", {}, q.full.slice(at, at + q.a.length)), q.full.slice(at + q.a.length));
    }
    return h("div", { class: "cardsay" }, say, q.extra ? h("p", { class: "x" }, q.extra) : null);
  },
  pub(S) {
    if (S.ph === "topic") return { ph: "topic", k: 0, n: 0 };
    const x = { ph: S.ph, k: S.k, n: S.qs.length };  // the words stay on the TV
    if (S.ph !== "ask") Object.assign(x, { ans: S.qs[S.k].ans, picks: S.res ? S.res.picks : null, log: S.log });
    return x;
  },
  collect(S, A, c) { return S.ph === "ask" && A.every((a, i) => (a && Number.isInteger(a.o)) || !c.here(i)) ? Trivia.force(S, c) : null; },
  timeout(S, A, c) { return S.ph === "ask" && Date.now() > S.ends ? Trivia.force(S, c) : null; },
  force(S, c) {
    if (S.ph !== "ask") return null;  // a topic is the TV's to pick
    const q = S.qs[S.k], counts = [0, 0, 0, 0];
    const picks = c.A.map((a) => (a && Number.isInteger(a.o) && a.o >= 0 && a.o < 4 ? a.o : -1));
    picks.forEach((o) => { if (o >= 0) counts[o]++; });
    const got = counts[q.ans];
    return Object.assign({}, S, { ph: "show", res: { counts, got, picks }, log: S.log.concat([got * 2 > c.N]), gots: S.gots.concat([got]) });
  },
  tv(S, c) {
    if (S.ph === "topic") {
      return frag(h("div", { class: "sub" }, "Trivia · tonight's topics"), h("div", { class: "h" }, "Pick a topic"),
        h("div", { class: "topics" }, btn("Mixed", () => c.go(Trivia.block(null))),
          S.ts.map(([t, n]) => h("button", { type: "button", class: "btn plain", onclick: () => c.go(Trivia.block(t)) }, t, h("small", {}, ` ${n}`)))));
    }
    const q = S.qs[S.k], A = c.A;
    const meter = h("div", { class: "meter", "aria-label": "The block so far" }, S.qs.map((_, i) => h("i", { class: S.log[i] == null ? "" : S.log[i] ? "on" : "miss" })));
    const where = S.topic ? ` · ${S.topic}` : q.tag ? " · " + q.tag : "";
    const top = h("div", { class: "row sp" }, h("span", { class: "sub" }, S.ph === "end" ? `Trivia · the block${S.topic ? " · " + S.topic : ""}` : `Trivia · question ${S.k + 1} of ${S.qs.length}${where}`), meter);
    if (S.ph === "end") {
      const right = S.log.filter(Boolean).length, need = Math.ceil(S.qs.length * 0.7);
      const missed = S.qs.map((qq, i) => [qq, S.gots[i]]).sort((a, b) => a[1] - b[1]).slice(0, 3);
      return frag(top, h("div", { class: "h" }, right >= need ? `Block cleared: most of you right on ${right} of ${S.qs.length}.` : `Most of you right on ${right} of ${S.qs.length}. ${need} clears it.`),
        h("div", { class: "lbl" }, "Most missed"),
        h("div", { class: "missed" }, missed.map(([qq, g]) => h("div", {}, h("span", {}, qq.q), h("b", {}, qq.opts[qq.ans]), h("em", {}, `${g} of ${c.N}`)))),
        h("div", { class: "row" }, btn(S.topic ? `More ${S.topic}` : "Another block", () => c.go(Trivia.block(S.topic))),
          (S.ts || []).length >= 2 ? btn("Pick a topic", () => c.go(Trivia.start()), "plain") : null, btn("Back to games", () => c.lobby(), "plain")));
    }
    const shown = S.ph === "show", res = S.res;
    const opts = h("div", { class: "opts" }, q.opts.map((t, i) => h("div", { class: "opt" + (shown ? (i === q.ans ? " right" : " dim") : ""), style: `--oc: var(--o${i + 1})` },
      shape(i), h("span", {}, t), h("em", {}, shown ? String(res.counts[i]) : ""),
      shown ? h("span", { class: "barx" }, h("i", { style: `width:${(100 * res.counts[i]) / Math.max(1, c.N)}%` })) : null)));
    if (!shown) {
      const inN = A.filter((a) => a && Number.isInteger(a.o)).length;
      const calls = h("div", { class: "calls" }, h("span", {}, "How many get it?"), Array.from({ length: c.N + 1 }, (_, n) => h("button", { type: "button", "aria-pressed": String(S.call === n), onclick: () => c.set(Object.assign({}, S, { call: n })) }, String(n))));
      return frag(top, h("div", { class: "h" }, q.q), opts, calls, h("div", { class: "row" }, h("span", { class: "tm", "data-end": S.ends }), h("span", { class: "sub" }, `${inN} of ${c.N} in`), btn("Reveal", () => c.go(Trivia.force(S, c)), "plain")));
    }
    let run = 0;
    for (let i = S.log.length - 1; i >= 0 && S.log[i]; i--) run++;
    const said = `${res.got} of ${c.N} got it.` + (S.call == null ? "" : S.call === res.got ? " Called it." : ` You called ${S.call}.`) + (run >= 3 ? ` ${run} in a row.` : "");
    const last = S.k + 1 >= S.qs.length;
    return frag(top, h("div", { class: "h" }, q.q), opts, h("div", { class: "say" }, said), Trivia.card(q),
      h("div", { class: "row" }, btn(last ? "See the block" : "Next question", () => c.go(last ? Object.assign({}, S, { ph: "end" }) : Object.assign({}, S, { ph: "ask", k: S.k + 1, ends: Date.now() + Trivia.SECS * 1000, call: null, res: null })))));
  },
  phone(x, seat, p) {
    const mine = p.mine();
    if (x.ph === "topic") return frag(h("div", { class: "big" }, "Picking a topic…"));
    if (x.ph === "end") return frag(h("div", { class: "big" }, `Most of you right on ${(x.log || []).filter(Boolean).length} of ${x.n}.`));
    const s = (i, tap) => h(tap ? "button" : "div", Object.assign({ class: "sh" + (x.ph === "show" ? (i === x.ans ? " right" : " dim") : "") + (mine && mine.o === i ? " mine" : ""), style: `--oc: var(--o${i + 1})`, "aria-label": SHAPE_NAMES[i] },
      tap ? { type: "button", onclick: () => p.answer({ o: i }) } : {}), shape(i));
    if (x.ph === "ask") {
      if (mine) return frag(h("div", { class: "who" }, `Question ${x.k + 1} · locked in`), h("div", { class: "shapes" }, [0, 1, 2, 3].map((i) => s(i, false))));
      return frag(h("div", { class: "who" }, `Question ${x.k + 1} of ${x.n}`), h("div", { class: "shapes" }, [0, 1, 2, 3].map((i) => s(i, true))));
    }
    const my = x.picks ? x.picks[seat] : -1;
    return frag(h("div", { class: "big" }, my < 0 ? "Time's up." : my === x.ans ? "Right." : "Not this one."), h("div", { class: "shapes" }, [0, 1, 2, 3].map((i) => s(i, false))));
  },
  mood(S, c) {
    if (S.ph === "topic") return "ready";
    if (S.ph === "ask") return "focus";
    if (S.ph === "end") return S.log.filter(Boolean).length >= Math.ceil(S.qs.length * 0.7) ? "cheer" : "again";
    return S.res && S.res.got * 2 > c.N ? "hop" : "again";
  },
  pmood(x, seat) { return x.ph === "show" && x.picks && x.picks[seat] === x.ans ? "hop" : null; },
  bot(x) { return x.ph === "ask" ? { a: { o: int(4) } } : null; },
  botDelay: () => 1500 + int(5000),
};

const DrawIt = {
  id: "draw", name: "Draw it", kind: "Draw, guess, pass it on", min: 3, max: 8, DRAW: 75, GUESS: 35,
  line: "One of your topics goes round the phones: draw it, the next one guesses from the drawing, the next draws the guess. The reveal is every chain.",
  learn: "Drawing a thing means knowing what it looks like.",
  chainOf: (i, st, N) => (((i - st) % N) + N) % N,
  // a chain's start: tonight's topics and answers, and about one in four a written prompt (D.draws)
  starts(N) {
    const k = Math.min((D.draws || []).length, Math.round(N / 4));
    const own = shuffle(D.prompts).slice(0, N - k);
    while (own.length < N - k) own.push(pick(D.prompts));
    return shuffle(shuffle(D.draws || []).slice(0, k).concat(own));
  },
  start(c) {
    const prompts = DrawIt.starts(c.N);
    const T = c.N >= 4 ? 4 : c.N;
    return { ph: "step", st: 0, T, chains: prompts.map((t, i) => [{ k: "p", t, by: i }]), ends: Date.now() + DrawIt.DRAW * 1000, rc: 0, ri: 0 };
  },
  text(ch) { for (let k = ch.length - 1; k >= 0; k--) if (ch[k].t && ch[k].t !== "(no guess)") return ch[k].t; return "?"; },
  pub(S) { return { ph: S.ph, st: S.st, T: S.T, kind: S.st % 2 === 0 ? "draw" : "guess" }; },
  secrets(S, c) { return c.seats.map((_, i) => (S.ph === "step" && S.st % 2 === 0 ? { text: DrawIt.text(S.chains[DrawIt.chainOf(i, S.st, c.N)]), st: S.st } : {})); },
  done(S, A, c, i) {
    const a = A[i];
    if (!a) return false;
    if (S.st % 2 === 0) { const d = c.pres(i).d; return a.ok === 1 && !!d && d.s === a.s; }
    return typeof a.g === "string";
  },
  collect(S, A, c) { return S.ph === "step" && c.seats.every((_, i) => DrawIt.done(S, A, c, i) || !c.here(i)) ? DrawIt.force(S, c) : null; },
  timeout(S, A, c) { return S.ph === "step" && Date.now() > S.ends ? DrawIt.force(S, c) : null; },
  force(S, c) {
    if (S.ph !== "step") return null;
    const draw = S.st % 2 === 0, chains = S.chains.map((ch) => ch.slice());
    c.seats.forEach((_, i) => {
      const ci = DrawIt.chainOf(i, S.st, c.N), a = c.A[i];
      if (draw) {
        const d = c.pres(i).d;
        const k = a && a.ok === 1 && d && d.s === a.s && Array.isArray(d.k) ? d.k.filter((s) => typeof s === "string").slice(0, 12).map((s) => s.slice(0, 1000)) : [];
        chains[ci].push({ k: "d", d: k, by: i });
      } else {
        chains[ci].push({ k: "g", t: a && typeof a.g === "string" && clip(a.g, 40) ? clip(a.g, 40) : "(no guess)", by: i });
      }
    });
    const st = S.st + 1;
    if (st >= S.T) return Object.assign({}, S, { chains, st, ph: "reveal", rc: 0, ri: 0 });
    return Object.assign({}, S, { chains, st, ends: Date.now() + (st % 2 === 0 ? DrawIt.DRAW : DrawIt.GUESS) * 1000 });
  },
  tv(S, c) {
    if (S.ph === "step") {
      const draw = S.st % 2 === 0;
      return frag(h("div", { class: "sub" }, `Draw it · step ${S.st + 1} of ${S.T}`),
        h("div", { class: "h" }, draw ? (S.st === 0 ? "Draw your topic." : "Draw what you were given.") : "What did they draw?"),
        h("p", { class: "lead" }, draw ? "No letters, no numbers." : "Type a guess."),
        h("div", { class: "row" }, h("span", { class: "tm", "data-end": S.ends }), h("div", { class: "ppl" }, c.seats.map((_, i) => { const ok = DrawIt.done(S, c.A, c, i); return h("span", { class: ok ? "ok" : "" }, c.name(i), ok ? " ✓" : ""); }))));
    }
    const ch = S.chains[S.rc], shown = ch.slice(0, S.ri + 1);
    const lastChain = S.rc + 1 >= S.chains.length, lastItem = S.ri + 1 >= ch.length;
    const step = () => c.set(Object.assign({}, S, lastItem ? { rc: S.rc + 1, ri: 0 } : { ri: S.ri + 1 }));
    return frag(h("div", { class: "sub" }, `Draw it · ${Poss(c.name(S.rc))} chain, ${S.rc + 1} of ${S.chains.length}`),
      h("div", { class: "chain2" }, shown.map((e) => (e.k === "d"
        ? h("div", { class: "cl d" }, e.d.length ? drawingSvg(e.d, "dw") : h("span", { class: "sub" }, "(no drawing)"), h("small", {}, `${c.name(e.by)} drew`))
        : h("div", { class: "cl t" + (e.k === "p" ? " p" : "") }, h("b", {}, e.t), h("small", {}, e.k === "p" ? "the topic" : `${c.name(e.by)} guessed`))))),
      h("div", { class: "row" },
        lastChain && lastItem ? btn("Another round", () => c.again()) : btn(lastItem ? `Next: ${poss(c.name(S.rc + 1))} chain` : "Show the next", step),
        btn("Back to games", () => c.lobby(), "plain")));
  },
  mood(S) { return S.ph === "reveal" ? "hello" : "focus"; },
  phoneDeps(x, seat, p) {
    if (x.ph !== "step" || x.kind !== "guess") return 0;
    const d = p.pres((seat - 1 + p.seats.length) % p.seats.length).d;
    return d && d.s === p.s - 1 ? [d.s, (d.k || []).length] : null;
  },
  phone(x, seat, p) {
    const mine = p.mine(), N = p.seats.length, prev = (seat - 1 + N) % N;
    if (x.ph === "reveal") return frag(h("div", { class: "big" }, "Watch the TV."));
    if (x.kind === "draw") {
      if (mine) return frag(h("div", { class: "big" }, "Sent."));
      const text = p.me && p.me.st === x.st ? p.me.text : null;
      if (!text) return h("p", { class: "small" }, "…");
      const ink = h("i");
      const pd = pad(() => { ink.style.width = Math.round(pd.left() * 100) + "%"; });
      requestAnimationFrame(() => pd.repaint());
      return frag(h("div", { class: "who" }, x.st === 0 ? "Draw your topic" : `Draw what ${p.name(prev)} guessed`), h("div", { class: "big" }, text), pd.el,
        h("div", { class: "ink", "aria-label": "Ink left" }, ink),
        h("div", { class: "row" }, btn("Undo", () => pd.undo(), "plain"), btn("Clear", () => pd.clear(), "plain"), btn("Send", () => p.answer({ ok: 1 }, { d: { s: p.s, k: pd.strokes() } }))));
    }
    if (mine) return frag(h("div", { class: "big" }, `You guessed: ${mine.g}`));
    const d = p.pres(prev).d, got = d && d.s === p.s - 1 ? d.k : null;
    const inp = p.draft("g", h("input", { type: "text", maxlength: 40, placeholder: "What is it?", "aria-label": "Your guess", autocomplete: "off" }));
    return frag(h("div", { class: "who" }, `${p.name(prev)} drew this`), got ? drawingSvg(got, "dw big") : h("p", { class: "small" }, "Waiting for the drawing…"),
      h("form", { class: "f", onsubmit: (e) => { e.preventDefault(); const g = clip(inp.value, 40); if (g) p.answer({ g }); } }, inp, h("button", { class: "btn", type: "submit" }, "Send")));
  },
  bot(x, seat, b) {
    if (x.ph !== "step") return null;
    if (x.kind === "draw") {
      const k = [];
      for (let s = 0; s < 3; s++) { let px = 10 + int(G - 20), py = 10 + int(G - 20), str = ""; for (let j = 0; j < 18; j++) { px = Math.max(0, Math.min(G, px + int(11) - 5)); py = Math.max(0, Math.min(G, py + int(11) - 5)); str += enc(px, py); } k.push(str); }
      return { a: { ok: 1 }, d: { k } };
    }
    const d = b.pres((seat - 1 + b.N) % b.N).d;
    if (!d || d.s !== b.s - 1) return null;
    return { a: { g: pick(D.prompts) } };
  },
  botDelay: () => 2000 + int(3000),
};

// the dial's ends: what a topic is placed between; the pack adds a few about study life (D.scales)
const SCALES = [["Rare", "Common"], ["Harmless", "Deadly"], ["Comes on slowly", "Comes on suddenly"], ["Cheap", "Pricey"],
  ["Easy to remember", "Impossible to remember"], ["Mild", "Severe"], ["In kids", "In old age"], ["Boring", "Fascinating"],
  ["Never asked", "On every exam"], ["Treat at home", "Straight to the ICU"], ["Clinic", "Emergency"], ["Ancient", "Brand new"]];
const Between = {
  id: "between", name: "Somewhere between", kind: "Read the dial", min: 2, max: 8,
  line: "One person sees where a hidden target sits between two ends and names something there, from tonight's topics or their own. Everyone turns their dial; the table's dial is the average.",
  learn: "How bad, how common, how fast: putting what you know on a scale.",
  pts: (d) => (d <= 4 ? 4 : d <= 9 ? 3 : d <= 15 ? 2 : 0),
  sugg: () => shuffle(D.prompts).slice(0, 6),
  ends: () => SCALES.concat((D.scales || []).filter((x) => Array.isArray(x) && x.length === 2)),
  start() { const ends = shuffle(Between.ends()); return { ph: "clue", psy: 0, ends, wi: 0, target: 6 + int(89), clue: null, score: 0, rounds: 0, res: null, sugg: Between.sugg() }; },
  pub(S) {
    const [L, R] = S.ends[S.wi];
    const x = { ph: S.ph, psy: S.psy, L, R, score: S.score, rounds: S.rounds };
    if (S.clue) x.clue = S.clue;
    if (S.res) Object.assign(x, { res: S.res, target: S.target });
    return x;
  },
  secrets(S, c) { return c.seats.map((_, i) => (i === S.psy && S.ph !== "show" ? { target: S.target, sugg: S.sugg, r: S.rounds } : {})); },
  collect(S, A, c) {
    if (S.ph === "clue" && A[S.psy] && typeof A[S.psy].c === "string" && A[S.psy].c.trim()) return Between.force(S, c);
    if (S.ph === "guess" && c.seats.every((_, i) => i === S.psy || !c.here(i) || (A[i] && A[i].lock === 1))) return Between.force(S, c);
    return null;
  },
  force(S, c) {
    if (S.ph === "clue") { const a = c.A[S.psy]; return Object.assign({}, S, { ph: "guess", clue: clip(a && a.c, 40) || "(no clue)" }); }
    if (S.ph === "guess") {
      const g = c.A.map((a, i) => (i !== S.psy && a && typeof a.g === "number" && isFinite(a.g) ? Math.max(0, Math.min(100, Math.round(a.g))) : -1));
      const vals = g.filter((v) => v >= 0);
      const avg = vals.length ? Math.round(vals.reduce((s, v) => s + v, 0) / vals.length) : 50;
      const pts = Between.pts(Math.abs(avg - S.target));
      return Object.assign({}, S, { ph: "show", res: { g, avg, pts }, score: S.score + pts, rounds: S.rounds + 1 });
    }
    return null;
  },
  tv(S, c) {
    const [L, R] = S.ends[S.wi], psy = c.name(S.psy), A = c.A;
    const head = h("div", { class: "row sp" }, h("span", { class: "sub" }, `Somewhere between · ${says(psy, "you have", "has")} the dial`), h("span", { class: "sub" }, `The table: ${plural(S.score, "point", "points")}`));
    if (S.ph === "clue") return frag(head, h("div", { class: "h" }, `${says(psy, "You're", "is")} picking a clue.`), dial({ L, R }));
    if (S.ph === "guess") {
      const live = A.map((a, i) => (i !== S.psy && a && typeof a.g === "number" ? a.g : null)).filter((v) => v != null);
      const avg = live.length ? live.reduce((s, v) => s + v, 0) / live.length : 50;
      const locked = A.filter((a, i) => i !== S.psy && a && a.lock === 1).length;
      return frag(head, h("div", { class: "h q" }, `“${S.clue}”`), dial({ L, R, needle: avg }),
        h("div", { class: "row" }, h("span", { class: "sub" }, `${locked} of ${c.N - 1} locked in`), btn("Reveal now", () => c.go(Between.force(S, c)), "plain")));
    }
    const r = S.res, words = { 4: "Bullseye.", 3: "Close.", 2: "In the zone.", 0: "Missed it." }[r.pts];
    const last = S.rounds >= c.N, nxt = (S.psy + 1) % c.N;
    return frag(head, h("div", { class: "h q" }, `“${S.clue}”`),
      dial({ L, R, needle: r.avg, target: S.target, dots: r.g.map((v, i) => (v >= 0 ? [v, c.name(i)] : null)).filter(Boolean) }),
      h("div", { class: "say" }, `${words} ${r.pts ? "+" + r.pts : "No points"}, and the table has ${plural(S.score, "point", "points")}.`),
      last ? h("p", { class: "sub" }, `Everyone's had the dial: ${plural(S.score, "point", "points")} in ${plural(S.rounds, "round", "rounds")}.`) : null,
      h("div", { class: "row" }, last ? btn("Play again", () => c.again()) : btn(`Next: ${says(c.name(nxt), "you have", "has")} the dial`, () => c.go(Object.assign({}, S, { ph: "clue", psy: nxt, wi: (S.wi + 1) % S.ends.length, target: 6 + int(89), clue: null, res: null, sugg: Between.sugg() }))),
        btn("Back to games", () => c.lobby(), "plain")));
  },
  phone(x, seat, p) {
    const psy = seat === x.psy, mine = p.mine();
    const ends = h("div", { class: "ends" }, h("span", {}, x.L), h("span", {}, x.R));
    if (x.ph === "clue") {
      if (!psy) return frag(h("div", { class: "big" }, `${p.name(x.psy)} has the dial.`), ends);
      if (mine) return frag(h("div", { class: "big" }, `Your clue: ${mine.c}`));
      if (!p.me || p.me.target == null) return h("p", { class: "small" }, "…");
      const inp = p.draft("c", h("input", { type: "text", maxlength: 40, placeholder: "Or your own", "aria-label": "Your clue", autocomplete: "off" }));
      return frag(h("div", { class: "who" }, "Only you see the target"), dial({ L: x.L, R: x.R, target: p.me.target }),
        h("div", { class: "vote" }, (p.me.sugg || []).map((t) => h("button", { type: "button", onclick: () => p.answer({ c: t }) }, t))),
        h("form", { class: "f", onsubmit: (e) => { e.preventDefault(); const cl = clip(inp.value, 40); if (cl) p.answer({ c: cl }); } }, inp, h("button", { class: "btn", type: "submit" }, "Send")));
    }
    if (x.ph === "guess") {
      if (psy) return frag(h("div", { class: "big" }, "Keep a straight face."), h("p", { class: "small" }, `Your clue: “${x.clue}”`));
      if (mine && mine.lock === 1) return frag(h("div", { class: "big" }, "Locked in."));
      const out = h("output", {}, "50");
      const rng = h("input", { type: "range", min: 0, max: 100, value: 50, "aria-label": "Your dial", class: "rng" });
      rng.addEventListener("input", () => { out.textContent = rng.value; p.live({ g: Number(rng.value) }); });
      return frag(h("div", { class: "who" }, `“${x.clue}”`), rng, ends, h("div", { class: "row sp" }, out, btn("Lock in", () => p.answer({ g: Number(rng.value), lock: 1 }))));
    }
    const my = x.res && x.res.g ? x.res.g[seat] : -1;
    return frag(h("div", { class: "big" }, x.res && x.res.pts ? `+${x.res.pts} for the table` : "No points this time"), h("p", { class: "small" }, !psy && my >= 0 ? `You said ${my}. The target was ${x.target}.` : `The target was ${x.target}.`));
  },
  mood(S) { return S.ph === "clue" ? "peek" : S.ph === "guess" ? "focus" : S.res.pts >= 3 ? "hop" : S.res.pts ? "ready" : "again"; },
  bot(x, seat, b) {
    if (x.ph === "clue" && seat === x.psy) { const s = b.me && b.me.sugg; return s && s.length ? { a: { c: pick(s) } } : null; }
    if (x.ph === "guess" && seat !== x.psy) return { a: { g: 15 + int(70), lock: 1 } };
    return null;
  },
};

// Links: two teams on one board, a clue giver each. The key goes to the two
// clue givers alone; everyone else sees what's been turned over.
const TEAM = { g: "Green", p: "Purple" };
const other = (t) => (t === "g" ? "p" : "g");
const Links = {
  id: "links", name: "Links", kind: "Two teams, one board", min: 4, max: 10, TIMERS: [0, 60, 90, 120],
  line: "Two teams, 25 of your topics. The clue givers know whose is whose: one word, and how many. Find yours first; stay off Code blue.",
  learn: "One mechanism, three diseases: finding what ties your deck together.",
  board() {
    const tiles = shuffle(D.words).slice(0, 25), first = rnd() < 0.5 ? "g" : "p";
    return { tiles, first, key: shuffle(Array(9).fill(first).concat(Array(8).fill(other(first)), Array(7).fill("n"), ["x"])), shown: Array(25).fill("") };
  },
  start(c) {
    const teams = c.seats.map((_, i) => (i % 2 ? "p" : "g"));
    return Object.assign({ ph: "teams", teams, givers: Links.givers(teams, {}), timer: 0, turn: null, clue: null, left: 0, last: null, result: null, ends: 0 }, Links.board());
  },
  givers(teams, was) {
    const g = {};
    for (const t of ["g", "p"]) g[t] = was[t] != null && teams[was[t]] === t ? was[t] : teams.indexOf(t);
    return g;
  },
  members: (S, t) => S.teams.map((x, i) => (x === t ? i : -1)).filter((i) => i >= 0),
  leftOf: (S, t) => S.key.filter((k, i) => k === t && !S.shown[i]).length,
  tappers(S) { const m = Links.members(S, S.turn); return m.length > 1 ? m.filter((i) => i !== S.givers[S.turn]) : m; },
  begin(S, t) { return Object.assign({}, S, { ph: "clue", turn: t, clue: null, left: 0, ends: S.timer ? Date.now() + S.timer * 1000 : 0 }); },
  play(S) { const t = Links.members(S, S.first).length ? S.first : other(S.first); return Links.begin(Object.assign({}, S, { last: null }), t); },
  endTurn(S) { const t = Links.members(S, other(S.turn)).length ? other(S.turn) : S.turn; return Links.begin(S, t); },
  pub(S) {
    const x = { ph: S.ph, tiles: S.tiles, shown: S.shown, first: S.first, turn: S.turn, teams: S.teams, givers: S.givers, timer: S.timer, clue: S.clue, left: S.left, last: S.last, ends: S.ends,
      counts: { g: Links.leftOf(S, "g"), p: Links.leftOf(S, "p") } };
    if (S.ph === "end") Object.assign(x, { key: S.key, result: S.result });
    return x;
  },
  secrets(S, c) { return c.seats.map((_, i) => (S.ph !== "teams" && (S.givers.g === i || S.givers.p === i) ? { key: S.key } : {})); },
  collect(S, A, c) {
    if (S.ph === "teams") {
      const teams = S.teams.slice(), was = Object.assign({}, S.givers);
      let changed = false;
      A.forEach((a, i) => {
        if (!a) return;
        if ((a.team === "g" || a.team === "p") && teams[i] !== a.team) { teams[i] = a.team; changed = true; }
        if (a.giver === 1 && was[teams[i]] !== i) { was[teams[i]] = i; changed = true; }
      });
      return changed ? Object.assign({}, S, { teams, givers: Links.givers(teams, was) }) : null;
    }
    if (S.ph === "clue") {
      if (!Links.members(S, S.turn).length) return Links.endTurn(S);
      const a = A[S.givers[S.turn]];
      return a && Number.isInteger(a.n) ? Links.force(S, c) : null;  // the word's said out loud; the phone sends how many
    }
    if (S.ph === "guess") {
      for (const i of Links.tappers(S)) {
        const a = A[i];
        if (!a) continue;
        if (a.pass === 1) return Object.assign(Links.endTurn(S), { last: { pass: 1, by: i } });
        if (Number.isInteger(a.t) && a.t >= 0 && a.t < 25 && !S.shown[a.t]) return Links.tap(S, a.t, i);
      }
    }
    return null;
  },
  timeout(S) { return (S.ph === "clue" || S.ph === "guess") && S.ends && Date.now() > S.ends ? Object.assign(Links.endTurn(S), { last: { time: 1 } }) : null; },
  force(S, c) {
    if (S.ph === "clue") {
      const a = c.A[S.givers[S.turn]];
      if (!a || !Number.isInteger(a.n)) return Links.endTurn(S);
      const n = Math.max(1, Math.min(9, a.n));
      return Object.assign({}, S, { ph: "guess", clue: { n }, left: n + 1 });
    }
    if (S.ph === "guess") return Links.endTurn(S);
    return null;
  },
  tap(S, t, by) {
    const kind = S.key[t], shown = S.shown.slice();
    shown[t] = kind;
    const S2 = Object.assign({}, S, { shown, last: { t, kind, by } });
    if (kind === "x") return Object.assign(S2, { ph: "end", result: { win: other(S.turn), blue: 1 } });
    for (const team of [S.turn, other(S.turn)]) if (!Links.leftOf(S2, team)) return Object.assign(S2, { ph: "end", result: { win: team } });
    if (kind !== S.turn) return Object.assign(Links.endTurn(S2), { last: S2.last });
    return S.left - 1 <= 0 ? Object.assign(Links.endTurn(S2), { last: S2.last }) : Object.assign(S2, { left: S.left - 1 });
  },
  arrange(S, how) {
    const order = how === "shuffle" ? shuffle(S.teams.map((_, i) => i)) : S.teams.map((_, i) => i);
    const teams = S.teams.slice();
    order.forEach((i, k) => { teams[i] = k % 2 ? "p" : "g"; });
    return Object.assign({}, S, { teams, givers: Links.givers(teams, S.givers) });
  },
  grid(x, o) {
    return h("div", { class: "grid5" }, x.tiles.map((t, k) => {
      const shown = x.shown[k], key = o.key ? o.key[k] : "";
      const tap = o.tap && !shown;
      const fresh = shown && x.last && x.last.t === k;
      return h(tap ? "button" : "div", Object.assign({ class: "lt5" + (shown ? ` r-${shown}` : key ? ` k-${key}` : "") + (fresh ? " new" : "") }, tap ? { type: "button", onclick: () => o.tap(k) } : {}), t);
    }));
  },
  // the clue giver's key: the board's places in their colours, the words on the TV
  blocks(x, key) {
    const say = { g: "Green", p: "Purple", n: "Nobody's", x: "Code blue" };
    return h("div", { class: "key5" }, key.map((k, i) => h("i", { class: `k-${k}${x.shown[i] ? " done" : ""}`, role: "img", "aria-label": `${x.tiles[i]}: ${say[k]}` })));
  },
  names(x, c, t) { return x.teams.map((tt, i) => (tt === t ? i : -1)).filter((i) => i >= 0).map((i) => c.name(i) + (x.givers[t] === i ? " · clues" : "")); },
  tv(S, c) {
    const x = Links.pub(S);
    const box = (t) => h("div", { class: `team5 ${t}${S.turn === t && S.ph !== "end" ? " on" : ""}` }, h("small", {}, `${TEAM[t]}${S.givers[t] >= 0 ? " · " + c.name(S.givers[t]) : ""}`), h("b", {}, S.ph === "teams" ? `${Links.members(S, t).length} in` : `${x.counts[t]} left`));
    if (S.ph === "teams") {
      return frag(h("div", { class: "sub" }, `Links · ${TEAM[S.first]} goes first, with 9 to find`),
        h("div", { class: "teams5" }, ["g", "p"].map((t) => h("div", { class: t }, h("b", {}, TEAM[t]), Links.names(x, c, t).map((n) => h("span", { class: "mem" }, seatPip(0, "Pip", t === "g" ? ["#2e7d32", "#7cc47f"] : ["#6a4fb3", "#b9a2f2"]), n))))),
        h("div", { class: "row" }, btn("Even out", () => c.go(Links.arrange(S, "even")), "plain"), btn("Shuffle", () => c.go(Links.arrange(S, "shuffle")), "plain"),
          h("span", { class: "seg" }, Links.TIMERS.map((s) => h("button", { type: "button", "aria-pressed": String(S.timer === s), onclick: () => c.set(Object.assign({}, S, { timer: s })) }, s ? `${s}s` : "No timer")))),
        h("div", { class: "row" }, btn("Start", () => c.go(Links.play(S)))));
    }
    const lastLine = S.last ? (S.last.pass ? `${c.name(S.last.by)} ended the turn.` : S.last.time ? "Time." : `${S.tiles[S.last.t]}: ${S.last.kind === "x" ? "Code blue." : S.last.kind === "n" ? "nobody's." : TEAM[S.last.kind] + "'s."}`) : "";
    const turn = S.ph === "end"
      ? h("div", { class: "turn5" }, h("b", {}, S.result.blue ? `Code blue. ${TEAM[S.result.win]} takes it.` : `${TEAM[S.result.win]} found all theirs.`))
      : h("div", { class: "turn5" }, h("b", { class: S.turn }, `${TEAM[S.turn]}'s turn`), S.clue ? h("span", { class: "clue5" }, "Clue for ", h("i", {}, String(S.clue.n)), ` · ${S.left} left`) : h("span", { class: "clue5" }, `${Poss(c.name(S.givers[S.turn]))} clue…`),
        S.ends ? h("span", { class: "tm", "data-end": S.ends }) : null);
    return frag(h("div", { class: "head5" }, box("g"), turn, box("p")), lastLine ? h("p", { class: "lead" }, lastLine) : null,
      Links.grid(x, { key: S.ph === "end" ? S.key : null, tap: S.ph === "guess" ? (k) => c.go(Links.tap(S, k, -1)) : null }),  // the team picks on the TV
      S.ph === "end" ? h("div", { class: "row" }, btn("New board", () => c.go(Links.play(Object.assign({}, S, Links.board())))), btn("Back to games", () => c.lobby(), "plain"))
        : S.ph === "guess" ? h("div", { class: "row" }, btn(`End ${TEAM[S.turn]}'s turn`, () => c.go(Links.endTurn(S)), "plain")) : null);
  },
  // a phone: its team and what the team has found; the clue giver's, the key
  // in colours (found places empty) and how many their clue's for, the word said out
  // loud. Picks are made on the TV's board.
  phone(x, seat, p) {
    const mine = p.mine(), t = x.teams[seat], key = p.me && p.me.key, giver = x.givers[t] === seat;
    const chip = h("div", { class: `who team-${t}` }, `${TEAM[t]}${giver ? " · you give the clues" : ""}`);
    if (x.ph === "teams") {
      return frag(chip, h("div", { class: "row" }, ["g", "p"].map((tt) => h("button", { type: "button", class: `btn ${tt === t ? "" : "plain"}`, onclick: () => p.answer({ team: tt }) }, TEAM[tt])),
        giver ? null : btn("I'll give the clues", () => p.answer({ giver: 1 }), "plain")));
    }
    const words = (list, cls) => (list.length ? h("div", { class: "words5" }, list.map((w) => h("span", { class: cls }, w))) : h("p", { class: "small" }, "None yet."));
    const found = (team) => x.tiles.filter((_, k) => x.shown[k] === team);
    const foundOf = (team) => frag(h("div", { class: "lbl" }, `Found · ${found(team).length} of ${team === x.first ? 9 : 8}`), words(found(team), `w-${team}`));
    if (x.ph === "end") return frag(chip, h("div", { class: "big" }, x.result.blue ? `Code blue. ${TEAM[x.result.win]} takes it.` : `${TEAM[x.result.win]} found all theirs.`), foundOf(t));
    const ours = x.turn === t;
    const status = ours ? (x.clue ? `Clue for ${x.clue.n}` : giver ? "Your clue" : `${p.name(x.givers[t])}'s clue…`) : `${TEAM[x.turn]}'s turn`;
    const sub = ours && x.clue ? h("p", { class: "small" }, `${x.left} left`) : null;
    if (giver && key) {
      const grid = Links.blocks(x, key);
      if (x.ph === "clue" && ours && !mine) {
        return frag(chip, h("div", { class: "big" }, "Your clue. How many?"),
          h("div", { class: "nums", role: "group", "aria-label": "How many it's for" }, [1, 2, 3, 4, 5].map((n) => h("button", { type: "button", onclick: () => p.answer({ n }) }, String(n)))), grid);
      }
      return frag(chip, h("div", { class: "big" }, mine && x.ph === "clue" ? `Clue for ${mine.n}` : status), sub, grid);
    }
    return frag(chip, h("div", { class: "big" }, status), sub, foundOf(t));
  },
  mood(S) { return S.ph === "teams" ? "hello" : S.ph === "end" ? (S.result.blue ? "again" : "cheer") : S.last && S.last.kind && S.last.kind === S.turn ? "ready" : "focus"; },
  pmood(x, seat) { return x.ph === "end" && x.result && x.result.win === x.teams[seat] ? "cheer" : null; },
  bot(x, seat, b) {
    if (x.ph === "clue" && x.givers[x.turn] === seat) return { a: { n: 1 + int(2) } };
    if (x.ph === "guess" && x.teams[seat] === x.turn && (x.givers[x.turn] !== seat || x.teams.filter((t) => t === x.turn).length === 1)) {
      const open = x.tiles.map((_, k) => k).filter((k) => !x.shown[k]);
      return rnd() < 0.25 || !open.length ? { a: { pass: 1 } } : { a: { t: pick(open) } };
    }
    return null;
  },
  botDelay: () => 2500 + int(2500),
};

// While we're testing, before game night goes wider: any game starts with
// one player. Each game's own min stays on its tile and in the lobby's word;
// set FEW to Infinity then, and every game needs its min again.
const FEW = 1;
const need = (g) => Math.min(g.min, FEW);
// what each game needs from tonight's pack (gamenight.NEEDS, the twin: the suite checks)
const NEEDS = { trivia: ["qs", 10], rounds: ["blacks", 1], links: ["words", 25], imposter: ["twins", 1], draw: ["prompts", 1], between: ["prompts", 1] };
const ready = (g) => !!D && (D[NEEDS[g.id][0]] || []).length >= NEEDS[g.id][1];

const GAMES = { imposter: Imposter, rounds: Rounds, trivia: Trivia, draw: DrawIt, between: Between, links: Links };
// on the menu (gamenight.GAMES): Rounds, Draw it and Somewhere between are off it, their code kept
const ORDER = ["trivia", "imposter", "links"];
const UNITS = { trivia: ["question", "questions"], imposter: ["topic", "topics"], links: ["word", "words"] };

// ---------- the table's vote (round three): what we play on ----------
// Anki marks every question, word and pair with its pick, or its subject when
// nothing was picked (gamenight.build's "sub"; "subs", each with its cards).
// Phones vote; the host's taps on the TV win; nothing chosen is all of it.
const Vote = {
  subs(P) { return ((P && P.subs) || []).filter((x) => x && typeof x.name === "string" && x.name).slice(0, 16); },
  // what's picked: the host's taps once made, else what any phone voted for ([] is all of it)
  picked(names, mine, votes) { return names.filter((n) => (mine ? mine.includes(n) : votes.some((v) => v.includes(n)))); },
  // the pack, the picked ones' part of it; Links' board filled from around them when short
  only(P, on) {
    if (!P || !on || !on.length) return P;
    const ok = new Set(on), ws = P.wsubs || {};
    const words = (P.words || []).filter((w) => ok.has(ws[w]));
    const fill = words.length < 40 ? (P.words || []).filter((w) => !ws[w]).slice(0, 40 - words.length) : [];
    return Object.assign({}, P, { qs: (P.qs || []).filter((q) => ok.has(q.sub)), words: words.concat(fill), twins: (P.twins || []).filter((t) => ok.has(t.sub)) });
  },
  count(P, id) { return P ? (P[NEEDS[id][0]] || []).length : 0; },
};

// ---------- hubs: what a client needs is presence(patch), peers(), onPeers(fn) ----------
class LocalHub {
  constructor() { this.cs = []; this.pending = false; }
  list(viewer) { return this.cs.map((c) => ({ peer: c.peer, isMe: c.peer === viewer, sameTab: c.peer === viewer, host: c.host, presence: c.p })); }
  tick() {
    if (this.pending) return;
    this.pending = true;
    queueMicrotask(() => { this.pending = false; for (const c of this.cs) { const ps = this.list(c.peer); for (const f of c.subs.slice()) f({ peers: ps }); } });
  }
  client(peer, host) {
    const hub = this, me = { peer, host: !!host, p: {}, subs: [], secret: null };
    hub.cs.push(me);
    return {
      peer,
      get secret() { return me.secret; },
      whisper(to, p) { const c = hub.cs.find((x) => x.peer === to); if (c) { c.secret = clone(p); hub.tick(); } },
      presence(patch) { me.p = Object.freeze(merge(me.p, patch)); hub.tick(); return Promise.resolve(); },
      peers: () => hub.list(peer),
      onPeers(fn) { me.subs.push(fn); queueMicrotask(() => fn({ peers: hub.list(peer) })); return () => { me.subs = me.subs.filter((f) => f !== fn); }; },
      leave() { hub.cs = hub.cs.filter((c) => c !== me); hub.tick(); return Promise.resolve(); },
    };
  }
}
/** A seat at a table on the API: one socket, my presence sent whole (at most
 *  25 times a second), everyone's kept as the table hands them on. Lost, it
 *  comes back with the same id, so its seat is still its own. A phone the
 *  table hasn't let in yet waits at the door (`waiting`); the host's also
 *  holds the door (`door`, and admit, away, setDoor, lock) and whispers each
 *  seat its own part of the game; a phone keeps the last it was told (`secret`). */
function wsClient(code, key, onState) {
  const cid = clientId();
  let ws = null, you = null, isHost = false, mine = {}, timer = null, backoff = 600, hello = false, misses = 0, done = false;
  let waiting = false, door = null, shut = "", secret = null;
  const others = new Map(), subs = [];
  let queued = false;
  const list = () => [{ peer: you, isMe: true, sameTab: true, host: isHost, presence: mine }].concat([...others].map(([peer, o]) => ({ peer, isMe: false, sameTab: false, host: o.host, wait: o.wait, crew: o.crew, presence: o.p })));
  const fire = () => { if (queued) return; queued = true; queueMicrotask(() => { queued = false; const ps = list(); subs.slice().forEach((f) => f({ peers: ps })); }); };
  const flush = () => { timer = null; if (ws && ws.readyState === 1 && hello) ws.send(JSON.stringify({ t: "p", p: mine })); };
  const one = (o) => ({ host: o.host === true, wait: o.wait === true, crew: typeof o.crew === "string" ? o.crew : null, p: Object.freeze(o.p && typeof o.p === "object" ? o.p : {}) });
  const tell = (m) => { if (isHost && ws && ws.readyState === 1 && hello) ws.send(JSON.stringify(m)); };
  function open() {
    const q = new URLSearchParams({ c: cid });
    if (key) q.set("k", key);
    ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/table/${encodeURIComponent(code)}/ws?${q}`);
    ws.onmessage = (e) => {
      let m;
      try { m = JSON.parse(e.data); } catch (_) { return; }
      if (!m || typeof m !== "object") return;
      if (m.t === "hi") {
        you = String(m.you || ""); isHost = m.host === true; waiting = m.wait === true; hello = true; backoff = 600; misses = 0;
        if (isHost) door = { door: String(m.door || "ask"), locked: m.locked === true };
        others.clear();
        for (const o of Array.isArray(m.peers) ? m.peers : []) if (o && typeof o.peer === "string") others.set(o.peer, one(o));
        flush(); fire(); onState(waiting ? "waiting" : "open");
      } else if (m.t === "p" && typeof m.peer === "string" && m.peer !== you) {
        others.set(m.peer, one(m)); fire();
      } else if (m.t === "bye" && typeof m.peer === "string") { others.delete(m.peer); fire(); }
      else if (m.t === "door" && isHost) { door = { door: String(m.door || "ask"), locked: m.locked === true }; fire(); }
      else if (m.t === "w" && m.p && typeof m.p === "object") { secret = Object.freeze(m.p); fire(); }
      else if (m.t === "err") warn(m.error);
    };
    ws.onclose = (e) => {
      ws = null; hello = false;
      if (done) return;
      const why = { 4000: "closed", 4001: "elsewhere", 4002: "another", 4003: "away", 4004: "crewonly", 4005: "locked", 4006: "full" }[e.code];
      if (why && !(key && why === "full")) { done = true; shut = why; others.clear(); fire(); onState(why); return; }  // the TV is no seat: tried again
      if (++misses > 12) { done = true; shut = "gone"; fire(); onState("gone"); return; }
      onState("reconnecting");
      setTimeout(open, backoff);
      backoff = Math.min(backoff * 2, 8000);
    };
  }
  open();
  return {
    get peer() { return you; },
    get waiting() { return waiting; },
    get door() { return door; },
    get shut() { return shut; },
    get secret() { return secret; },
    whisper(to, p) { tell({ t: "w", to, p }); },
    presence(patch) { mine = Object.freeze(merge(mine, patch)); if (!timer) timer = setTimeout(flush, 40); fire(); return Promise.resolve(); },
    peers: list,
    onPeers(fn) { subs.push(fn); queueMicrotask(() => fn({ peers: list() })); return () => {}; },
    admit(peer) { tell({ t: "admit", peer }); },
    away(peer) { tell({ t: "away", peer }); },
    setDoor(d) { tell({ t: "door", door: d }); },
    lock(on) { tell({ t: "lock", on }); },
    leave() { done = true; try { if (ws) ws.close(1000, "bye"); } catch (_) { /* gone */ } return Promise.resolve(); },
  };
}

/** This tab's id at a table: kept for the tab, so a reload keeps the seat. */
function clientId() {
  try {
    let c = sessionStorage.getItem("gn-cid");
    if (!c) { c = Array.from(crypto.getRandomValues(new Uint8Array(18)), (b) => "abcdefghijklmnopqrstuvwxyz0123456789"[b % 36]).join(""); sessionStorage.setItem("gn-cid", c); }
    return c;
  } catch (_) {
    return Array.from(crypto.getRandomValues(new Uint8Array(18)), (b) => "abcdefghijklmnopqrstuvwxyz0123456789"[b % 36]).join("");
  }
}

// ---------- the TV: holds the game ----------
function TV(root, client, opt) {
  const T = { mode: "lobby", chosen: ORDER.includes(opt.first) ? opt.first : ORDER.find((id) => ready(GAMES[id])) || "trivia", mine: null,
    game: null, S: null, step: 0, seats: [], peers: [], key: "", sure: "", told: {}, mood: "", rx: {}, rxAt: {}, joined: 0 };
  const players = () => T.peers.filter((p) => !(p.isMe && p.sameTab) && !p.wait && p.presence && p.presence.r === "p" && typeof p.presence.n === "string")
    .sort((a, b) => (Number(a.presence.t) || 0) - (Number(b.presence.t) || 0) || (a.peer < b.peer ? -1 : 1));
  const peerOf = (i) => (T.seats[i] ? T.peers.find((x) => x.peer === T.seats[i].peer) : null);
  const presOf = (i) => { const p = peerOf(i); return (p && p.presence) || {}; };
  const answers = () => T.seats.map((_, i) => { const a = presOf(i).a; return a && typeof a === "object" && a.s === T.step ? a : null; });
  // the vote: tonight's picks (or subjects), what the phones want, what the host tapped; D is the picked part
  const names = () => Vote.subs(ALL).map((x) => x.name);
  const votes = () => players().map((p) => (Array.isArray(p.presence.v) ? p.presence.v.filter((x) => typeof x === "string").slice(0, 16) : []));
  const picked = () => Vote.picked(names(), T.mine, votes());
  const tonight = () => { const on = picked(); D = Vote.only(ALL, on.length < names().length ? on : []); return D; };  // every one picked: all of it
  const play = () => (ready(GAMES[T.chosen]) ? T.chosen : ORDER.find((id) => ready(GAMES[id])) || null);  // the one picked, or the next that fits
  function ctx() {
    return { N: T.seats.length, seats: T.seats, name: (i) => (T.seats[i] ? T.seats[i].n : "?"), A: answers(), pres: presOf, here: (i) => !!peerOf(i), bots: !!opt.bots, go, set, again, lobby };
  }
  function publish() {
    if (T.mode !== "game") tonight();
    const g = T.mode === "game" ? { m: "game", gm: T.game.id, s: T.step, seats: T.seats.map((s) => ({ peer: s.peer, n: s.n })), x: T.game.pub(T.S, ctx()) }
      : { m: "lobby", gm: play() || T.chosen, s: T.step, subs: names().length > 1 ? names() : [] };  // phones vote on the names, nothing more
    client.presence({ r: "tv", code: opt.code, g }).catch(warn);
    whisper();
  }
  // each seat's own part (a hand, a topic, the key), to that phone alone, when it changes
  function whisper() {
    const sec = T.mode === "game" && T.game.secrets ? T.game.secrets(T.S, ctx()) : [];
    T.seats.forEach((s, i) => {
      if (!peerOf(i)) { delete T.told[s.peer]; return; }  // gone: told again when it's back
      const v = Object.assign({ gm: T.mode === "game" ? T.game.id : "" }, sec[i] || {}), k = JSON.stringify(v);
      if (T.told[s.peer] !== k) { T.told[s.peer] = k; client.whisper(s.peer, v); }
    });
  }
  function go(S) { if (!S) return; T.S = S; T.step++; publish(); draw(true); }
  function set(S) { T.S = S; publish(); draw(true); }
  function again() { go(T.game.start(ctx())); }
  function lobby() { T.mode = "lobby"; T.game = null; T.S = null; T.step++; publish(); draw(true); }
  function start() {
    tonight();
    const id = play(), g = GAMES[id], ps = players();
    if (!id || ps.length < need(g)) return;
    T.game = g;
    T.seats = ps.slice(0, g.max).map((p) => ({ peer: p.peer, n: clip(p.presence.n, 16) || "Someone" }));
    T.mode = "game";
    go(g.start(ctx()));
  }
  function check() { if (T.mode !== "game") return; const c = ctx(); const S2 = T.game.collect(T.S, c.A, c); if (S2) go(S2); }
  let drawing = false;  // one draw a frame, however many phones moved (a dial sends often)
  const soon = () => { if (drawing) return; drawing = true; (typeof requestAnimationFrame === "function" ? requestAnimationFrame : setTimeout)(() => { drawing = false; draw(); }); };
  client.onPeers((ch) => { T.peers = ch.peers || []; check(); whisper(); reactions(); soon(); }, (e) => { root.replaceChildren(h("div", { class: "note" }, `The room closed (${e && e.code}).`)); });
  // a phone's reaction (one of REACTS, a count that moves) floats up the TV, with its name
  function reactions() {
    if (!opt.fx) return;
    for (const p of T.peers) {
      const rx = p.presence && p.presence.rx;
      if (!rx || typeof rx.n !== "number" || !Number.isInteger(rx.e) || !REACTS[rx.e]) continue;
      const seen = T.rx[p.peer], now = Date.now();
      T.rx[p.peer] = rx.n;
      if (seen == null || rx.n <= seen || now - (T.rxAt[p.peer] || 0) < 500) continue;
      T.rxAt[p.peer] = now;
      const el = h("span", { class: "rxf", style: `left:${8 + int(84)}%` }, REACTS[rx.e], h("small", {}, clip(p.presence.n, 16)));
      opt.fx.append(el);
      setTimeout(() => el.remove(), 2600);
    }
  }
  // Pip in the TV's corner: the game's mood, a wave when someone sits down; drawn again only when it changes
  function corner() {
    if (!opt.corner) return;
    const n = players().length;
    let mood = "idle";
    if (T.mode === "game" && T.game.mood) { try { mood = T.game.mood(T.S, ctx()) || "idle"; } catch (e) { mood = "idle"; } }
    else if (T.mode === "lobby" && n > T.joined) mood = "hello";
    if (T.mode === "lobby") T.joined = n;
    const key = `${T.mode}:${T.step}:${mood}:${T.mode === "lobby" ? n : ""}`;
    if (key === T.mood || (T.mode === "lobby" && mood === "idle" && T.mood.startsWith("lobby:"))) return;
    T.mood = key;
    const el = pip(mood, 120);
    opt.corner.replaceChildren(...(el ? [el] : []));
  }
  const iv = setInterval(() => {
    if (!root.isConnected) { clearInterval(iv); return; }
    if (T.mode === "game" && T.game.timeout) { const c = ctx(); const S2 = T.game.timeout(T.S, c.A, c); if (S2) { go(S2); return; } }
    tick();
  }, 250);
  function tick() {
    root.querySelectorAll("[data-end]").forEach((el) => { const left = Math.max(0, Number(el.dataset.end) - Date.now()); el.textContent = `${Math.ceil(left / 1000)}s`; el.classList.toggle("low", left < 6000); });
  }
  function lobbyView() {
    tonight();
    const ps = players(), id = play(), g = GAMES[id || T.chosen];
    // the code, where to join, and the QR beside them (room left for the vote under them)
    const code = h("div", { class: "code" }, h("div", { class: "lbl" }, opt.bots ? "Playing with bots" : "Join on your phones"),
      opt.bots ? h("p", { class: "lead" }, "Maya, Dre and Jo are bots.") : h("div", { class: "joinat" },
        h("div", { class: "stack" }, h("div", { class: "letters" }, opt.code), h("p", { class: "lead" }, h("b", {}, `${location.host}/t/${opt.code}`))),
        typeof QR !== "undefined" ? QR.svg(`${location.origin}/t/${opt.code}`, 112) : null),
      ALL && ALL.n ? h("p", { class: "sub" }, `${Number(ALL.n).toLocaleString("en-US")} of your cards`) : null);
    const people = h("div", { class: "ppl big" }, ps.length ? ps.map((p, i) => h("span", { class: "ok" }, seatPip(i, `${clip(p.presence.n, 16) || "Someone"}'s Pip`), clip(p.presence.n, 16) || "Someone",
      p.crew ? h("i", { title: `Signed in as ${clip(p.crew, 40)}` }, " crew") : null,
      client.door ? h("button", { type: "button", class: "x", "aria-label": `Turn ${clip(p.presence.n, 16) || "them"} away`, onclick: () => { T.sure = p.peer; draw(true); } }, "×") : null)) : h("span", {}, "Nobody's here yet."));
    const tiles = h("div", { class: "tiles" }, ORDER.map((gid) => {
      const gg = GAMES[gid], ok = ready(gg), u = UNITS[gid];
      return h("button", { type: "button", class: "tile" + (gid === id ? " on" : "") + (ok ? "" : " thin"), disabled: !ok, "aria-pressed": String(gid === id), onclick: () => { T.chosen = gid; publish(); draw(true); } },
        h("span", { class: "kind" }, gg.kind), h("b", {}, gg.name), h("span", { class: "ln" }, gg.line),
        h("span", { class: "np" }, ok ? `${plural(Vote.count(D, gid), u[0], u[1])} · ${gg.min}–${gg.max} players` : "Not enough cards for this one"));
    }));
    const on = picked(), short = !id || ps.length < need(g), few = !short && ps.length < g.min;
    const what = !on.length ? "" : on.length === 1 ? ` on ${clip(on[0], 36)}` : ` on these ${on.length}`;
    const why = !id ? (on.length ? "Too few cards in these for any game. Pick another." : "Too few cards for any game.")
      : ps.length < need(g) ? (ps.length ? `${g.name} needs ${plural(need(g), "player", "players")} or more.` : "Waiting for a phone to join.")
      : id !== T.chosen ? `${GAMES[T.chosen].name} needs more than these. ${g.name} it is.` : few ? `Made for ${g.min} or more.` : "";
    return frag(h("div", { class: "lobby" }, code, h("div", { class: "stack" }, h("div", { class: "lbl" }, `At the table · ${ps.length}`), people, sureView(), doorView())),
      voteView(), h("div", { class: "lbl" }, "Pick a game"), tiles,
      h("div", { class: "row" }, h("button", { type: "button", class: "btn", disabled: short, onclick: start }, `Play ${g.name}${what}`),
        why ? h("span", { class: "sub" }, why) : null));
  }
  // what we play on: a tile a pick (or subject), sized by its cards, with who voted for it; a tap is the host's say
  function voteView() {
    const ss = Vote.subs(ALL);
    if (ss.length < 2) return null;
    const on = picked(), ps = players(), big = Math.max(1, ...ss.map((x) => Number(x.n) || 0));
    const tap = (n) => { const base = picked(); T.mine = base.includes(n) ? base.filter((x) => x !== n) : base.concat(n); publish(); draw(true); };
    return h("div", { class: "stack" },
      h("div", { class: "row vhead" }, h("div", { class: "lbl" }, "What are we playing on?"),
        T.mine && votes().some((v) => v.length) ? btn("Go with the votes", () => { T.mine = null; publish(); draw(true); }, "ghost") : null),
      h("div", { class: "vmap" + (on.length ? " picking" : "") }, ss.map((x) => {
        const n = Number(x.n) || 0, sel = on.includes(x.name);
        const who = ps.map((p, i) => [p, i]).filter(([p]) => Array.isArray(p.presence.v) && p.presence.v.includes(x.name));
        return h("button", { type: "button", class: "vt" + (sel ? " on" : ""), "aria-pressed": String(sel), style: `flex:${Math.max(1, n)} 1 ${120 + Math.round(110 * n / big)}px`, onclick: () => tap(x.name) },
          h("b", {}, clip(x.name, 36)), h("span", { class: "vn" }, plural(n, "card", "cards")),
          who.length ? h("span", { class: "vv", "aria-label": `Votes: ${who.map(([p]) => clip(p.presence.n, 16) || "Someone").join(", ")}` },
            who.map(([p, i]) => h("i", { style: `background:${SEAT_COLORS[i % SEAT_COLORS.length][0]}`, title: clip(p.presence.n, 16) }, (clip(p.presence.n, 16) || "?").slice(0, 1).toUpperCase()))) : null);
      })));
  }
  // the door, the host's alone: who gets in, the lock, who's waiting
  const waiting = () => T.peers.filter((p) => p.wait && !p.isMe);
  function doorView() {
    const d = client.door;
    if (!d) return null;
    const ways = [["ask", "Ask me"], ["crew", "Crew only"], ["open", "Anyone with the code"]];
    const at = waiting();
    return h("div", { class: "door stack" },
      h("div", { class: "lbl" }, "Who gets in"),
      h("div", { class: "seg", role: "group", "aria-label": "Who gets in" }, ways.map(([id, label]) => h("button", { type: "button", class: id === d.door ? "on" : "", "aria-pressed": String(id === d.door), onclick: () => client.setDoor(id) }, label)),
        h("button", { type: "button", class: "lock" + (d.locked ? " on" : ""), "aria-pressed": String(d.locked), onclick: () => client.lock(!d.locked) }, d.locked ? "Locked" : "Lock")),
      d.locked || d.door === "ask" ? h("p", { class: "small" }, d.locked ? "Nobody new. Anyone who sat down can come back." : "Your crew come straight in.") : null,
      at.length ? knocks(at) : null);
  }
  function knocks(at) {
    return h("div", { class: "knocks" }, h("div", { class: "lbl" }, `At the door · ${at.length}`),
      at.map((p) => h("div", { class: "row" }, h("b", {}, clip(p.presence && p.presence.n, 16) || "Someone"),
        btn("Let in", () => client.admit(p.peer)), btn("Turn away", () => client.away(p.peer), "plain"))));
  }
  function sureView() {
    const p = T.sure && T.peers.find((x) => x.peer === T.sure);
    if (!p) return null;
    const nm = clip(p.presence && p.presence.n, 16) || "them";
    return h("div", { class: "row sure" }, h("span", {}, `Turn ${nm} away for tonight?`),
      btn("Turn away", () => { client.away(p.peer); T.sure = ""; draw(true); }, "plain"), btn("Keep", () => { T.sure = ""; draw(true); }, "ghost"));
  }
  function gameView(c) {
    let body;
    try { body = T.game.tv(T.S, c); } catch (e) { warn(e); body = h("p", {}, "Something went wrong. Back to games, and start again."); }
    const own = [...body.querySelectorAll("button")].some((b) => b.textContent === "Back to games");  // an end screen has its own way out
    const at = client.door ? waiting() : [];
    if (at.length) body = frag(knocks(at), body);
    let skips = false;
    try { skips = !!(T.game.force && T.game.force(T.S, ctx())); } catch (e) { skips = false; }
    if (body.querySelector("[data-next]")) skips = false;  // the game's own way on (Imposter's Vote)
    return own ? body : frag(body, h("div", { class: "row foot" }, skips ? btn("Skip ahead", () => { const S2 = T.game.force(T.S, ctx()); if (S2) go(S2); }, "ghost") : null, btn("Back to games", lobby, "ghost")));
  }
  function draw(force) {
    const c = ctx();
    const key = JSON.stringify([T.mode, T.chosen, T.mine, T.step, T.S, c.A, players().map((p) => [p.peer, p.presence.n, p.crew, T.mode === "lobby" ? p.presence.v : 0]),
      waiting().map((p) => [p.peer, p.presence.n]), client.door || null, T.sure]);
    if (!force && key === T.key) return;
    T.key = key;
    root.replaceChildren(T.mode === "lobby" ? lobbyView() : gameView(c));
    corner();
    tick();
  }
  publish();
  draw(true);
  return T;
}

// ---------- a phone: answers in its own presence ----------
function Phone(root, client, name) {
  const P = { key: "", myA: null, drafts: {}, peers: [], mood: "", rxn: 0, rxAt: 0, votes: [] };
  const top = h("div", { class: "ph-top" }), face = h("span", { class: "ph-pip", "aria-hidden": "true" }), box = h("div", { class: "ph-body" });
  const react = h("div", { class: "rxbar", role: "group", "aria-label": "React" }, REACTS.map((e, i) => h("button", { type: "button", "aria-label": `React ${e}`, onclick: () => {
    if (Date.now() - P.rxAt < 600) return;
    P.rxAt = Date.now();
    client.presence({ rx: { e: i, n: ++P.rxn } }).catch(warn);
  } }, e)));
  root.replaceChildren(top, box, react);
  client.presence({ r: "p", n: name, t: Date.now() }).catch(warn);
  const tvOf = () => P.peers.find((p) => p.host && p.presence && p.presence.r === "tv" && p.presence.g && typeof p.presence.g === "object");
  const myPeer = () => { const me = P.peers.find((p) => p.isMe && p.sameTab); return (me && me.peer) || client.peer; };
  client.onPeers((ch) => { P.peers = ch.peers || []; draw(); }, (e) => { root.replaceChildren(h("div", { class: "note" }, `The room closed (${e && e.code}).`)); });
  function pc(pub, seat) {
    return {
      s: pub.s, seat, seats: pub.seats, name: (i) => (pub.seats[i] ? clip(pub.seats[i].n, 16) : "?"),
      me: client.secret && client.secret.gm === pub.gm ? client.secret : null,
      mine: () => (P.myA && P.myA.s === pub.s ? P.myA : null),
      answer(fields, extra) { const a = Object.assign({ s: pub.s }, fields); P.myA = a; client.presence(Object.assign({ a }, extra || {})).catch(warn); draw(true); },
      live(fields) {  // as it moves (a dial): about eight a second, its last place always sent
        P.live = Object.assign({ s: pub.s }, fields);
        if (!P.liveT) P.liveT = setTimeout(() => { P.liveT = null; client.presence({ a: P.live }).catch(() => {}); }, 120);
      },
      pres(i) { const s = pub.seats[i], p = s && P.peers.find((x) => x.peer === s.peer); return (p && p.presence) || {}; },
      draft(id, el) { const k = pub.s + ":" + id; if (P.drafts[k] != null) el.value = P.drafts[k]; el.addEventListener("input", () => { P.drafts[k] = el.value; }); return el; },
    };
  }
  // the lobby: what should we play on? a tap's my vote (the TV shows it; the host has the say)
  function lobby(pub) {
    const subs = Array.isArray(pub.subs) ? pub.subs.filter((x) => typeof x === "string").slice(0, 16) : [];
    const vote = (n) => { P.votes = P.votes.includes(n) ? P.votes.filter((x) => x !== n) : P.votes.concat(n); client.presence({ v: P.votes }).catch(warn); draw(true); };
    return frag(h("div", { class: "big" }, you(name) ? "You're in." : `You're in, ${name}.`),
      subs.length > 1 ? h("div", { class: "stack" }, h("div", { class: "say" }, "What should we play on?"),
        h("div", { class: "vlist" }, subs.map((n) => h("button", { type: "button", "aria-pressed": String(P.votes.includes(n)), onclick: () => vote(n) }, clip(n, 36))))) : null,
      GAMES[pub.gm] ? h("p", { class: "small" }, `Up next: ${GAMES[pub.gm].name}`) : null);
  }
  function draw(force) {
    const tv = tvOf(), pub = tv ? tv.presence.g : null, me = myPeer();
    let seat = -1, deps = 0;
    if (pub && pub.m === "game" && Array.isArray(pub.seats)) {
      seat = pub.seats.findIndex((s) => s && s.peer === me);
      const g = GAMES[pub.gm];
      if (g && g.phoneDeps && seat >= 0) { try { deps = g.phoneDeps(pub.x, seat, pc(pub, seat)); } catch (e) { deps = 0; } }
    }
    const key = JSON.stringify([!!tv, pub, seat, P.myA, deps, !!client.waiting, client.shut || "", client.secret || null, P.votes]);
    if (!force && key === P.key) return;
    P.key = key;
    top.replaceChildren(face, h("b", {}, name), h("span", {}, client.shut ? "" : client.waiting ? "At the door" : tv ? `Pip Party · ${clip(tv.presence.code, 8)}` : "Looking for the TV"));
    let body, mood = "idle";
    if (client.shut && SHUT[client.shut]) body = frag(h("div", { class: "big" }, SHUT[client.shut][0]), h("p", { class: "small" }, SHUT[client.shut][1]), h("div", { class: "row" }, btn("Join again", () => { bye(); joinView(""); }, "plain")));
    else if (client.waiting) { body = frag(h("div", { class: "big" }, `At the door, ${name}.`), h("p", { class: "small" }, "The host lets you in from the TV.")); mood = "peek"; }
    else if (!tv) body = frag(h("div", { class: "big" }, "Looking for the TV…"));
    else if (pub.m !== "game") { body = lobby(pub); mood = "hello"; }
    else if (!GAMES[pub.gm]) body = h("p", {}, "…");
    else if (seat < 0) body = frag(h("div", { class: "big" }, "This one started without you."), h("p", { class: "small" }, "You're in the next one."));
    else {
      try { body = GAMES[pub.gm].phone(pub.x, seat, pc(pub, seat)); } catch (e) { warn(e); body = h("p", { class: "small" }, "Waiting for the TV…"); }
      try { mood = (GAMES[pub.gm].pmood && GAMES[pub.gm].pmood(pub.x, seat)) || "idle"; } catch (e) { mood = "idle"; }
    }
    box.replaceChildren(body);
    react.hidden = !(pub && pub.m === "game" && seat >= 0) || !!client.shut;
    const mk = `${pub ? pub.s : ""}:${mood}`;
    if (mk !== P.mood && !(mood === "idle" && P.mood.endsWith(":idle"))) { P.mood = mk; const el = pip(mood, 40); face.replaceChildren(...(el ? [el] : [])); }
  }
  draw(true);
}

// ---------- bots: the same answers a phone would give ----------
function runBots(hub, names) {
  names.forEach((n, k) => {
    const c = hub.client("bot" + k), done = {};
    c.presence({ r: "p", n, t: Date.now() + 10 + k });
    c.onPeers((ch) => {
      const tv = ch.peers.find((p) => p.host && p.presence && p.presence.r === "tv"), pub = tv && tv.presence.g;
      if (!pub || pub.m !== "game") return;
      const seat = pub.seats.findIndex((s) => s.peer === c.peer);
      const g = GAMES[pub.gm];
      if (seat < 0 || done[pub.s] || !g || !g.bot) return;
      const bc = { s: pub.s, seat, seats: pub.seats, N: pub.seats.length, me: c.secret && c.secret.gm === pub.gm ? c.secret : null,
        pres: (i) => { const s = pub.seats[i], p = s && ch.peers.find((x) => x.peer === s.peer); return (p && p.presence) || {}; } };
      let patch = null;
      try { patch = g.bot(pub.x, seat, bc); } catch (e) { warn(e); }
      if (!patch) return;
      done[pub.s] = true;
      if (patch.a) patch.a.s = pub.s;
      if (patch.d) patch.d.s = pub.s;
      if (rnd() < 0.2) patch.rx = { e: int(REACTS.length), n: (done.rx = (done.rx || 0) + 1) };
      setTimeout(() => c.presence(patch), calm ? 30 : g.botDelay ? g.botDelay() : 700 + int(1800));
    });
  });
}

// ---------- the page ----------
const app = document.getElementById("app");
const conn = document.getElementById("conn");
const store = {
  get(k, s) { try { return (s ? sessionStorage : localStorage).getItem(k) || ""; } catch (_) { return ""; } },
  set(k, v, s) { try { (s ? sessionStorage : localStorage).setItem(k, v); } catch (_) { /* fine */ } },
  drop(k, s) { try { (s ? sessionStorage : localStorage).removeItem(k); } catch (_) { /* fine */ } },
};
let leaving = null;
const joinOnly = /^\/t\//.test(location.pathname);  // a join link: a phone's page, nothing to host from
function bye() { if (leaving) { try { leaving(); } catch (_) { /* fine */ } leaving = null; } conn.textContent = ""; }
const back = () => (joinOnly ? document.createTextNode("") : h("button", { type: "button", class: "back", onclick: () => { bye(); history.replaceState(null, "", "/table"); home(); } }, "← Pip Party"));
const STATES = { open: "", waiting: "", reconnecting: "Reconnecting…", closed: "The table closed.", elsewhere: "This seat is open in another tab.", another: "This table's TV is open on another screen.", gone: "Lost the table. Check your connection, then join again." };
// why a table sent a phone off, as the phone says it
const SHUT = {
  away: ["Not tonight.", "The host turned this phone away."],
  crewonly: ["Crew only.", "This table is for the host's crew now. Sign in to Due Crew on this phone, then join again."],
  locked: ["The table's locked.", "The host locked it once everyone was in."],
  full: ["That table's full.", "Try again when someone leaves."],
  closed: ["The table closed.", "Thanks for playing."],
  elsewhere: ["Open somewhere else.", "This seat moved to another tab or screen."],
  gone: ["Lost the table.", "Check your connection, then join again."],
};
const onState = (s) => { conn.textContent = STATES[s] || ""; conn.classList.toggle("bad", !!STATES[s]); };
const codeOf = (v) => String(v || "").toUpperCase().replace(/[^A-Z]/g, "").slice(0, 4);
async function apiCall(method, path) {
  const r = await fetch(`/api${path}`, { method, headers: { "x-due-crew": "1" }, credentials: "same-origin" });
  let body = null;
  try { body = await r.json(); } catch (_) { body = null; }
  return { status: r.status, body };
}
const connect = (code, key) => wsClient(code, key, onState);

function home() {
  bye();
  app.className = "home";
  app.replaceChildren(
    h("header", { class: "hero" }, h("h1", {}, "Pip Party"),
      h("p", { class: "lede" }, "Party games on your own cards. The TV is Anki: You › Pip Party on the Decks screen. Everyone else plays on their phone."),
      h("div", { class: "modes" }, h("button", { type: "button", class: "mode go", onclick: () => joinView("") }, h("b", {}, "Join from your phone"), h("span", {}, "The four letters on the TV.")))),
    h("section", { class: "games" }, h("div", { class: "lbl" }, `${["No", "One", "Two", "Three", "Four", "Five", "Six"][ORDER.length]} games`), h("div", { class: "tiles static" }, ORDER.map((id) => { const g = GAMES[id]; return h("div", { class: "tile" }, h("span", { class: "kind" }, g.kind), h("b", {}, g.name), h("span", { class: "ln" }, g.line), h("span", { class: "lr" }, g.learn), h("span", { class: "np" }, `${g.min}–${g.max} players`)); }))));
}

/** The TV, in Anki's window: the table Anki opened, with tonight's pack. */
function tvView(code, key, first) {
  bye();
  app.className = "host";
  const client = connect(code, key);
  leaving = () => client.leave();
  const tv = h("div", { class: "tv big", id: "tv" }, h("div", { class: "bar" }, h("b", {}, `Due Crew · Pip Party · ${code}`),
    h("button", { type: "button", class: "ghost", onclick: () => { const el = document.getElementById("tv"); if (el && el.requestFullscreen) el.requestFullscreen().catch(() => {}); } }, "Full screen")),
    h("div", { class: "in", id: "tv-in", "aria-live": "polite" }), h("div", { class: "pipc", id: "tv-pip", "aria-hidden": "true" }), h("div", { class: "fx", id: "tv-fx", "aria-hidden": "true" }));
  app.replaceChildren(tv);
  TV(document.getElementById("tv-in"), client, { code, first, corner: document.getElementById("tv-pip"), fx: document.getElementById("tv-fx") });
}

function joinView(pre) {
  bye();
  app.className = "join";
  const nm = h("input", { id: "j-name", type: "text", maxlength: 16, placeholder: "Your name", "aria-label": "Your name", value: store.get("gn-name"), autocomplete: "nickname" });
  const cd = h("input", { id: "j-code", type: "text", maxlength: 4, placeholder: "Code", "aria-label": "The TV's code", autocomplete: "off", autocapitalize: "characters", class: "codein", value: pre || "" });
  // from the TV's link or its QR the code's in hand: a name and Join (a remembered name, Join alone)
  const linked = codeOf(pre || "").length === 4;
  const lbl = h("div", { class: "lbl" }, linked ? `Join table ${codeOf(pre)}` : "Join a game");
  const typeIt = () => { cd.hidden = false; other.hidden = true; lbl.textContent = "Join a game"; };
  const other = btn("Another table", () => { typeIt(); cd.select(); cd.focus(); }, "ghost");
  cd.hidden = linked;
  other.hidden = !linked;
  const go = h("button", { class: "btn", type: "submit" }, "Join");
  const said = h("p", { class: "small", role: "status" });
  const foot = h("p", { class: "small" }, "No account needed. The host lets you in.");
  const form = h("form", { class: "f card", onsubmit: async (e) => {
    e.preventDefault();
    const name = clip(nm.value, 16), code = codeOf(cd.value);
    if (!name) { said.textContent = "Your name, so the table knows who you are."; nm.focus(); return; }
    if (code.length !== 4) { typeIt(); said.textContent = "The code is the four letters on the TV."; cd.focus(); return; }
    store.set("gn-name", name);
    said.textContent = "Finding the table…";
    const r = await apiCall("GET", `/table/${code}`).catch(() => ({ status: 0 }));
    if (r.status === 404) { typeIt(); said.textContent = "No table with that code. Check the TV."; return; }
    if (r.status === 429) { said.textContent = "That's a lot of tries. Wait a little, then try again."; return; }
    if (r.status !== 200) { said.textContent = "Couldn't reach the table. Check your connection."; return; }
    if (r.body && r.body.full) { said.textContent = "That table's full."; return; }
    if (r.body && r.body.door === "crew" && !r.body.crew) {
      said.replaceChildren("This table is for the host's crew. ", h("a", { href: `/sign-in?next=${encodeURIComponent("/t/" + code)}` }, "Sign in"), " on this phone, then join.");
      foot.hidden = true;
      return;
    }
    const client = connect(code, null);
    leaving = () => client.leave();
    const ph = h("div", { class: "phone-solo", "aria-live": "polite" });
    app.replaceChildren(ph);
    Phone(ph, client, name);
  } }, lbl, nm, cd, go, other, said, foot);
  app.replaceChildren(back(), form);
  (nm.value ? (linked ? go : cd) : nm).focus();
}

function botsView() {
  bye();
  app.className = "bots";
  const hub = new LocalHub();
  const tv = h("div", { class: "tv" }, h("div", { class: "bar" }, h("b", {}, "Due Crew · Pip Party · the TV"), h("span", {}, "bots")), h("div", { class: "in", id: "tv-in", "aria-live": "polite" }),
    h("div", { class: "pipc", id: "tv-pip", "aria-hidden": "true" }), h("div", { class: "fx", id: "tv-fx", "aria-hidden": "true" }));
  const phone = h("div", {}, h("div", { class: "lbl" }, "Your phone"), h("div", { class: "phone" }, h("div", { class: "st" }, h("span", {}, "9:41"), h("span", {}, "●●●")), h("div", { class: "in", id: "ph-in", "aria-live": "polite" })));
  app.replaceChildren(h("div", { class: "stage" }, tv, phone));
  Phone(document.getElementById("ph-in"), hub.client("you"), "You");
  runBots(hub, ["Maya", "Dre", "Jo"]);
  TV(document.getElementById("tv-in"), hub.client("tv", true), { code: "BOTS", bots: true, corner: document.getElementById("tv-pip"), fx: document.getElementById("tv-fx") });
}

// Anki's window: it hands over the table (or bots) and tonight's pack.
// duecrew.com/t/MKQZ is a join link: the code filled in.
const fromLink = /^\/t\/([A-Za-z]{4})\/?$/.exec(location.pathname);
let started = false;
function fromAnki(d) {
  if (started || !d || typeof d !== "object" || !d.pack || typeof d.pack !== "object") return;
  started = true;
  ALL = D = d.pack;
  if (d.mode === "bots") botsView();
  else tvView(codeOf(d.code), String(d.key || ""), String(d.first || ""));
}
if (typeof Sev !== "undefined" && Sev.sheet) Sev.sheet();  // Pip's sheet, before any seat's Pip
if (location.hash === "#anki") {
  app.replaceChildren(h("p", { class: "sub" }, "Starting…"));
  window.dcAnki = fromAnki;
  if (window.__dcAnki) fromAnki(window.__dcAnki);
} else if (fromLink) joinView(codeOf(fromLink[1]));
else home();
})();
