// duecrew.com/table, game night (3.9.5): party games for a table of
// friends. One screen is the TV and holds the game; everyone else plays on
// their phone. The TV opens a table on the API (POST /table, signed in) and
// shares the game as its presence there; phones join with the code alone and
// answer in theirs (worker/src/table.ts passes presences round, and marks
// only the TV's as the host's). Bots mode runs the same TV, phone and bots in
// one page; #local runs real tabs over BroadcastChannel, for trying it out.
// The packs are table-packs.js: Due Crew's own, nothing from anyone's deck.
"use strict";
(() => {
const D = GN_PACKS;
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
const one = (w) => String(w || "").trim().split(/\s+/)[0].slice(0, 24);
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
const warn = (e) => console.warn("game night:", e && (e.code || e.message || e));
const pip = () => null;  // Pip stays in Anki

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
  function paint() {
    g.clearRect(0, 0, 600, 600);
    g.lineWidth = 10; g.lineCap = "round"; g.lineJoin = "round"; g.strokeStyle = getComputedStyle(cv).color || "#222";
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
  cv.addEventListener("pointerdown", (e) => { if (used() + 2 > MAX) return; e.preventDefault(); try { cv.setPointerCapture(e.pointerId); } catch (_) { /* fine */ } const [x, y] = at(e); cur = enc(x, y); last = [x, y]; paint(); onChange(); });
  cv.addEventListener("pointermove", (e) => {
    if (cur == null) return;
    const [x, y] = at(e);
    if (Math.abs(x - last[0]) + Math.abs(y - last[1]) < 2 || used() + 2 > MAX) return;
    cur += enc(x, y); last = [x, y];
    if (cur.length >= 996) { strokes.push(cur); cur = enc(x, y); }
    paint(); onChange();
  });
  const end = () => { if (cur != null) { strokes.push(cur); cur = null; paint(); onChange(); } };
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
const shape = (i) => { const s = h("span", { class: "shp", "aria-hidden": "true" }); s.innerHTML = `<svg viewBox="0 0 24 24">${SHAPES[i]}</svg>`; return s; };

// ---------- the games ----------
const IMPT = {};
D.imp.forEach((p) => { IMPT[p.a.t] = Object.assign({ part: p.part }, p.a); IMPT[p.b.t] = Object.assign({ part: p.part }, p.b); });
const apart = (a, b) => h("div", { class: "apart" }, [a, b].map((t, k) => h("div", { class: k ? "them" : "" }, h("b", {}, t), h("ul", {}, (IMPT[t] ? IMPT[t].facts : []).map((f) => h("li", {}, f))))));

const Imposter = {
  id: "imposter", name: "Imposter", like: "Like the imposter game", min: 3, max: 8,
  line: "Every phone shows the same topic but one. That one gets its twin, the topic it's easiest to mix up with, and doesn't know.",
  learn: "Spotting what separates two things you'd confuse.",
  start(c) {
    const pr = pick(D.imp);
    const [a, b] = rnd() < 0.5 ? [pr.a.t, pr.b.t] : [pr.b.t, pr.a.t];
    return { ph: "clue", r: 1, a, b, part: pr.part, imp: int(c.N), clues: [], votes: null, last: null, opts: null, caught: null, most: null };
  },
  pub(S, c) {
    const x = { ph: S.ph, r: S.r, part: S.part, top: c.seats.map((_, i) => (i === S.imp ? S.b : S.a)), clues: S.clues };
    if (S.ph === "last" || S.ph === "end") Object.assign(x, { imp: S.imp, a: S.a, b: S.b, votes: S.votes, caught: S.caught });
    if (S.ph === "last") x.opts = S.opts;
    if (S.ph === "end") x.last = S.last;
    return x;
  },
  collect(S, A, c) {
    const all = (f) => A.every((a, i) => (a && f(a)) || !c.here(i));
    if (S.ph === "clue" && all((a) => typeof a.w === "string" && a.w)) return Imposter.force(S, c);
    if (S.ph === "vote" && (c.N < 2 || all((a) => Number.isInteger(a.v)))) return Imposter.force(S, c);  // alone, nobody to vote for
    if (S.ph === "last" && A[S.imp] && typeof A[S.imp].g === "string") return Imposter.force(S, c);
    return null;
  },
  force(S, c) {
    const A = c.A;
    if (S.ph === "clue") {
      const clues = S.clues.concat([A.map((a) => (a && typeof a.w === "string" && one(clip(a.w, 24)) ? one(clip(a.w, 24)) : "…"))]);
      return Object.assign({}, S, S.r === 1 ? { r: 2, clues } : { ph: "vote", clues });
    }
    if (S.ph === "vote") {
      const votes = A.map((a, i) => (a && Number.isInteger(a.v) && a.v >= 0 && a.v < c.N && a.v !== i ? a.v : -1));
      const tally = Array(c.N).fill(0);
      votes.forEach((v) => { if (v >= 0) tally[v]++; });
      const top = Math.max(0, ...tally);
      const most = top ? tally.map((n, i) => (n === top ? i : -1)).filter((i) => i >= 0) : [];
      if (most.length === 1 && most[0] === S.imp) {
        const others = shuffle(Object.keys(IMPT).filter((t) => t !== S.a && t !== S.b)).slice(0, 3);
        return Object.assign({}, S, { ph: "last", votes, caught: true, most, opts: shuffle([S.a].concat(others)) });
      }
      return Object.assign({}, S, { ph: "end", votes, caught: false, most });
    }
    if (S.ph === "last") {
      const a = A[S.imp];
      return Object.assign({}, S, { ph: "end", last: a && typeof a.g === "string" ? clip(a.g, 40) : "" });
    }
    return null;
  },
  tv(S, c) {
    const A = c.A, nm = c.name;
    const head = h("div", { class: "sub" }, `Imposter · ${S.part}`);
    const table = () => (S.clues.length ? h("div", { class: "ct" }, c.seats.map((_, i) => h("div", { class: "ct-r" + (S.ph === "end" && i === S.imp ? " bad" : "") }, h("b", {}, nm(i)), S.clues.map((r) => h("span", {}, r[i] || "…"))))) : null);
    const status = (f) => h("div", { class: "ppl" }, c.seats.map((_, i) => { const ok = A[i] && f(A[i]); return h("span", { class: ok ? "ok" : "" }, nm(i), ok ? " ✓" : ""); }));
    if (S.ph === "clue") {
      return frag(head, h("div", { class: "h" }, `Clues, round ${S.r} of 2`),
        h("p", { class: "lead" }, S.r === 1 ? "One word on your phone that fits your topic. Not too obvious: one of you has a different topic, and doesn't know it." : "One more word each, now you've heard everyone's."),
        status((a) => a.w), table(), S.r === 1 ? pip("peek") : null);
    }
    if (S.ph === "vote") return frag(head, h("div", { class: "h" }, "Who's the imposter?"), h("p", { class: "lead" }, "Vote on your phones."), table(), status((a) => Number.isInteger(a.v)));
    const imp = nm(S.imp);
    if (S.ph === "last") {
      return frag(head, h("div", { class: "h" }, `Caught: ${you(imp) ? "you" : imp} had ${S.b}.`), h("p", { class: "lead" }, `Everyone else had ${S.a}. ${says(imp, "You get", "gets")} one last chance: name it, and ${you(imp) ? "you get" : "they get"} away.`), table(), pip("ready"));
    }
    const named = S.caught && norm(S.last) === norm(S.a);
    const headline = !S.caught ? `${imp} got away with ${S.b}.` : named ? `${imp} named it. ${you(imp) ? "You get" : "They get"} away.` : `Caught: ${you(imp) ? "you" : imp} had ${S.b}.`;
    const why = !S.caught ? (S.most && S.most.length > 1 ? "The votes tied." : S.most && S.most.length ? `The votes landed on ${S.most.map(nm).join(" and ")}.` : "Nobody voted.") : named ? `${imp} had ${S.b} and guessed ${S.a}.` : S.last ? `${you(imp) ? "Your" : "Their"} last guess: ${S.last}.` : "";
    const tally = Array(c.N).fill(0);
    (S.votes || []).forEach((v) => { if (v >= 0) tally[v]++; });
    return frag(head, h("div", { class: "h" }, headline), h("p", { class: "lead" }, [why, `Everyone else had ${S.a}.`].filter(Boolean).join(" ")),
      h("div", { class: "ppl" }, c.seats.map((_, i) => h("span", { class: i === S.imp ? "bad" : "" }, nm(i), tally[i] ? h("i", {}, " " + plural(tally[i], "vote", "votes")) : null))),
      table(), h("div", { class: "lbl" }, "What tells them apart"), apart(S.a, S.b),
      h("div", { class: "row" }, btn("Another round", () => c.again()), btn("Back to games", () => c.lobby(), "plain")));
  },
  phone(x, seat, p) {
    const my = x.top[seat], mine = p.mine();
    const secret = h("div", { class: "secret" }, h("div", { class: "small" }, "Your topic"), h("div", { class: "big" }, my), h("div", { class: "small" }, "Don't show anyone."));
    if (x.ph === "clue") {
      if (mine) return frag(secret, h("p", {}, `Sent: ${mine.w}. Watch the TV.`));
      const inp = p.draft("w", h("input", { type: "text", maxlength: 24, placeholder: "One word", "aria-label": "Your one word", autocomplete: "off", autocapitalize: "off" }));
      return frag(h("div", { class: "who" }, `Clues, round ${x.r} of 2`), secret, x.r === 2 && x.clues[0] ? h("p", { class: "small" }, `Your first word: ${x.clues[0][seat]}`) : null,
        h("form", { class: "f", onsubmit: (e) => { e.preventDefault(); const w = one(clip(inp.value, 24)); if (w) p.answer({ w }); } }, inp, h("button", { class: "btn", type: "submit" }, "Send")));
    }
    if (x.ph === "vote") {
      if (mine) return frag(h("div", { class: "big" }, `You voted ${p.name(mine.v)}.`), h("p", { class: "small" }, "Watch the TV."));
      return frag(h("div", { class: "who" }, "Who had a different topic?"), h("div", { class: "vote" }, p.seats.map((_, i) => (i === seat ? null : h("button", { type: "button", onclick: () => p.answer({ v: i }) }, p.name(i))))), h("p", { class: "small" }, `Your topic: ${my}`));
    }
    if (x.ph === "last") {
      if (seat !== x.imp) return frag(h("div", { class: "big" }, `Caught: ${p.name(x.imp)}.`), h("p", { class: "small" }, "They get one last guess."));
      if (mine) return frag(h("div", { class: "big" }, `You guessed ${mine.g}.`), h("p", { class: "small" }, "Watch the TV."));
      return frag(h("div", { class: "who" }, "You were the imposter"), h("div", { class: "big" }, `Your topic was the twin: ${x.b}.`), h("p", { class: "small" }, "What did everyone else have? Get it right and you get away."),
        h("div", { class: "vote" }, (x.opts || []).map((o) => h("button", { type: "button", onclick: () => p.answer({ g: o }) }, o))));
    }
    const me = seat === x.imp;
    return frag(h("div", { class: "who" }, me ? "You were the imposter" : "You had the topic"), h("div", { class: "big" }, my), h("p", { class: "small" }, me ? `Everyone else had ${x.a}.` : `${p.name(x.imp)} had ${x.b}.`), h("p", { class: "small" }, "Watch the TV."));
  },
  bot(x, seat, b) {
    const info = IMPT[x.top[seat]] || { clues: ["hmm"] };
    if (x.ph === "clue") { const used = new Set((x.clues || []).flat().map(norm)); const w = shuffle(info.clues).find((w2) => !used.has(norm(w2))) || pick(info.clues); return { a: { w } }; }
    if (x.ph === "vote") {
      const ours = new Set(info.clues.map(norm));
      const others = b.seats.map((_, i) => i).filter((i) => i !== seat);
      const odd = others.filter((i) => (x.clues || []).some((r) => r[i] && !ours.has(norm(r[i]))));
      return { a: { v: pick(odd.length && rnd() < 0.8 ? odd : others) } };
    }
    if (x.ph === "last" && seat === x.imp) return { a: { g: rnd() < 0.5 ? x.a : pick(x.opts || [x.a]) } };
    return null;
  },
};

const BLK = D.blacks;
const WILD = new Set(D.wild);
function fixRound(S) {
  const ans = BLK[S.order[S.bi]].a;
  const hands = S.hands.map((hd) => hd.slice());
  const deck = S.deck.filter((x) => x !== ans);
  const ai = S.att >= 0 ? hands[S.att].indexOf(ans) : -1;
  if (ai >= 0 && deck.length) hands[S.att][ai] = deck.shift();
  const holders = hands.map((hd, i) => (i !== S.att && hd.includes(ans) ? i : -1)).filter((i) => i >= 0);
  if (!holders.length) {
    const j = pick(hands.map((_, i) => i).filter((i) => i !== S.att));
    const k = int(hands[j].length);
    deck.push(hands[j][k]);
    hands[j][k] = ans;
  }
  return Object.assign({}, S, { hands, deck });
}
const Rounds = {
  id: "rounds", name: "Rounds", like: "Like Cards Against Humanity", min: 3, max: 8,
  line: "A black card from your deck, its answer blanked. Everyone plays a white card. The Attending picks a favorite, then the chart says what it really was.",
  learn: "A wrong card is only funny if you know why it's wrong.",
  start(c) {
    const deck = shuffle(D.whites.concat(D.wild));
    const hands = c.seats.map(() => deck.splice(0, 6));
    return fixRound({ ph: "play", att: c.N > 1 ? 1 % c.N : -1, order: shuffle(BLK.map((_, i) => i)), bi: 0, hands, deck, played: null, flip: null, fseat: null, fav: null });
  },
  pub(S) {
    const b = BLK[S.order[S.bi]];
    const x = { ph: S.ph, att: S.att, black: b.t, hands: S.hands };
    if (S.ph !== "play") x.flip = S.flip;
    if (S.ph === "chart") Object.assign(x, { fav: S.fav, fseat: S.fseat, ans: b.a });
    return x;
  },
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
    const hands = S.hands.map((hd, i) => {
      const keep = hd.filter((x) => x !== (S.played && S.played[i]));
      while (keep.length < 6) {
        if (!deck.length) deck = shuffle(D.whites.concat(D.wild).filter((x) => !S.hands.some((h2) => h2.includes(x))));
        if (!deck.length) break;
        keep.push(deck.shift());
      }
      return keep;
    });
    return fixRound(Object.assign({}, S, { ph: "play", att: S.att < 0 ? -1 : (S.att + 1) % c.N, bi: (S.bi + 1) % BLK.length, hands, deck, played: null, flip: null, fseat: null, fav: null }));
  },
  tv(S, c) {
    const b = BLK[S.order[S.bi]], att = c.name(S.att), A = c.A, alone = S.att < 0;
    const black = h("div", { class: "black" }, h("p", {}, b.t), h("small", {}, alone ? "Rounds" : `Rounds · the Attending: ${att}`));
    if (S.ph === "play") {
      const others = c.seats.map((_, i) => i).filter((i) => i !== S.att);
      return frag(black, h("p", { class: "lead" }, alone ? "Play a card on your phone. With one of you, there's no Attending: the chart says it straight." : `${you(att) ? "You're the Attending: read" : att + ", read"} it out loud. Everyone else: play a card on your phone.`),
        h("div", { class: "whites" }, others.map((i) => { const ok = A[i] && A[i].c; return h("div", { class: "white down" + (ok ? " ok" : "") }, ok ? "Played" : "", h("small", {}, c.name(i))); })));
    }
    const cards = h("div", { class: "whites" }, S.flip.map((card, k) => {
      const fav = S.ph === "chart" && k === S.fav, right = S.ph === "chart" && card === b.a;
      return h("div", { class: ["white", WILD.has(card) ? "wild" : "", fav ? "fav" : "", right ? "right" : ""].join(" ") }, card, h("small", {}, S.ph === "chart" ? c.name(S.fseat[k]) : WILD.has(card) ? "wild card" : ""));
    }));
    if (S.ph === "pick") return frag(black, cards, h("p", { class: "lead" }, `${says(att, "You pick", "picks")} a favorite on ${you(att) ? "your" : "their"} phone: the funniest, the cleverest, or the one that's nearly right.`));
    const rightBy = S.fseat.filter((_, k) => S.flip[k] === b.a).map(c.name);
    return frag(black, cards,
      alone ? null : h("div", { class: "honor" }, h("b", { class: "f" }, `${Poss(att)} pick:`), ` “${S.flip[S.fav]}”, ${you(c.name(S.fseat[S.fav])) ? "yours" : c.name(S.fseat[S.fav]) + "'s"}.`),
      h("div", { class: "honor" }, h("b", { class: "c" }, `The chart says: ${b.a}.`), rightBy.length ? ` ${rightBy.join(" and ")} played it.` : " Nobody played it."),
      h("p", { class: "sub" }, b.why),
      h("div", { class: "row" }, btn(alone ? "Next round" : `Next round: ${you(c.name((S.att + 1) % c.N)) ? "you're" : c.name((S.att + 1) % c.N) + "'s"} the Attending`, () => c.go(Rounds.next(S, c))), btn("Back to games", () => c.lobby(), "plain")));
  },
  phone(x, seat, p) {
    const mine = p.mine(), att = p.name(x.att);
    const black = h("div", { class: "black sm" }, h("p", {}, x.black));
    const card = (t, extra, fn) => h(fn ? "button" : "div", Object.assign({ class: "white" + (WILD.has(t) ? " wild" : "") + (extra || "") }, fn ? { type: "button", onclick: fn } : {}), t, WILD.has(t) ? h("small", {}, "wild card") : null);
    if (x.ph === "play") {
      if (seat === x.att) return frag(h("div", { class: "who" }, "You're the Attending"), black, h("p", { class: "small" }, "Read it out loud. When the cards are in, you pick a favorite."));
      if (mine) return frag(h("div", { class: "who" }, x.att < 0 ? "Played" : `${att}'s the Attending`), card(mine.c), h("p", { class: "small" }, "Played. Watch the TV."));
      return frag(h("div", { class: "who" }, x.att < 0 ? "Play a card" : `${att}'s the Attending · play a card`), black, h("div", { class: "hand" }, (x.hands[seat] || []).map((t) => card(t, "", () => p.answer({ c: t })))));
    }
    if (x.ph === "pick") {
      if (seat !== x.att) return frag(h("div", { class: "big" }, `${att}'s picking.`), h("p", { class: "small" }, "Watch the TV."));
      if (mine) return frag(h("div", { class: "big" }, "Picked."), h("p", { class: "small" }, "Watch the TV."));
      return frag(h("div", { class: "who" }, "Pick a favorite"), black, h("div", { class: "hand" }, (x.flip || []).map((t, k) => card(t, "", () => p.answer({ f: k })))));
    }
    const k = (x.fseat || []).indexOf(seat), myCard = k >= 0 ? x.flip[k] : null;
    const lines = [];
    if (myCard && k === x.fav && x.att >= 0) lines.push(`${att} picked yours.`);
    if (myCard && myCard === x.ans) lines.push("Chart-right.");
    return frag(h("div", { class: "who" }, `The chart says: ${x.ans}`), myCard ? card(myCard, (k === x.fav ? " fav" : "") + (myCard === x.ans ? " right" : "")) : null, h("p", { class: "small" }, lines.join(" ") || "Watch the TV."));
  },
  bot(x, seat) {
    if (x.ph === "play" && seat !== x.att) {
      const hand = x.hands[seat] || [], blk = BLK.find((k) => k.t === x.black), ans = blk && blk.a, wild = hand.filter((t) => WILD.has(t));
      const cd = ans && hand.includes(ans) && rnd() < 0.55 ? ans : wild.length && rnd() < 0.4 ? pick(wild) : pick(hand);
      return cd ? { a: { c: cd } } : null;
    }
    if (x.ph === "pick" && seat === x.att) { const wild = (x.flip || []).map((t, k) => (WILD.has(t) ? k : -1)).filter((k) => k >= 0); return { a: { f: wild.length && rnd() < 0.5 ? pick(wild) : int((x.flip || [0]).length) } }; }
    return null;
  },
};

const Trivia = {
  id: "trivia", name: "Trivia", like: "Like pub trivia", min: 1, max: 8, SECS: 20,
  line: "Questions on the TV, four answers on every phone. Before the reveal, call how many of you got it. Most of you right on 7 of 10 clears the block.",
  learn: "Recall, ten at a time, and a check on what the table thinks it knows.",
  start() {
    const qs = shuffle(D.trivia).slice(0, 10).map((q) => { const o = shuffle([0, 1, 2, 3]); return { q: q.q, opts: o.map((i) => q.opts[i]), ans: o.indexOf(q.ans) }; });
    return { ph: "ask", k: 0, qs, ends: Date.now() + Trivia.SECS * 1000, call: null, log: [], gots: [], res: null };
  },
  pub(S) {
    const q = S.qs[S.k];
    const x = { ph: S.ph, k: S.k, n: S.qs.length, opts: q.opts };
    if (S.ph !== "ask") Object.assign(x, { ans: q.ans, picks: S.res ? S.res.picks : null, log: S.log });
    return x;
  },
  collect(S, A, c) { return S.ph === "ask" && A.every((a, i) => (a && Number.isInteger(a.o)) || !c.here(i)) ? Trivia.force(S, c) : null; },
  timeout(S, A, c) { return S.ph === "ask" && Date.now() > S.ends ? Trivia.force(S, c) : null; },
  force(S, c) {
    if (S.ph !== "ask") return null;
    const q = S.qs[S.k], counts = [0, 0, 0, 0];
    const picks = c.A.map((a) => (a && Number.isInteger(a.o) && a.o >= 0 && a.o < 4 ? a.o : -1));
    picks.forEach((o) => { if (o >= 0) counts[o]++; });
    const got = counts[q.ans];
    return Object.assign({}, S, { ph: "show", res: { counts, got, picks }, log: S.log.concat([got * 2 > c.N]), gots: S.gots.concat([got]) });
  },
  tv(S, c) {
    const q = S.qs[S.k], A = c.A;
    const meter = h("div", { class: "meter", "aria-label": "The block so far" }, S.qs.map((_, i) => h("i", { class: S.log[i] == null ? "" : S.log[i] ? "on" : "miss" })));
    const top = h("div", { class: "row sp" }, h("span", { class: "sub" }, S.ph === "end" ? "Trivia · the block" : `Trivia · question ${S.k + 1} of ${S.qs.length}`), meter);
    if (S.ph === "end") {
      const right = S.log.filter(Boolean).length, need = Math.ceil(S.qs.length * 0.7);
      const missed = S.qs.map((qq, i) => [qq, S.gots[i]]).sort((a, b) => a[1] - b[1]).slice(0, 3);
      return frag(top, h("div", { class: "row" }, pip(right >= need ? "cheer" : "again"), h("div", { class: "h" }, right >= need ? `Block cleared: most of you right on ${right} of ${S.qs.length}.` : `Most of you right on ${right} of ${S.qs.length}. ${need} clears it.`)),
        h("div", { class: "lbl" }, "Most missed"),
        h("div", { class: "missed" }, missed.map(([qq, g]) => h("div", {}, h("span", {}, qq.q), h("b", {}, qq.opts[qq.ans]), h("em", {}, `${g} of ${c.N}`)))),
        h("div", { class: "row" }, btn("Another block", () => c.again()), btn("Back to games", () => c.lobby(), "plain")));
    }
    const shown = S.ph === "show", res = S.res;
    const opts = h("div", { class: "opts" }, q.opts.map((t, i) => h("div", { class: "opt" + (shown ? (i === q.ans ? " right" : " dim") : ""), style: `--oc: var(--o${i + 1})` },
      shape(i), h("span", {}, t), h("em", {}, shown ? String(res.counts[i]) : ""),
      shown ? h("span", { class: "barx" }, h("i", { style: `width:${(100 * res.counts[i]) / Math.max(1, c.N)}%` })) : null)));
    if (!shown) {
      const inN = A.filter((a) => a && Number.isInteger(a.o)).length;
      const calls = h("div", { class: "calls" }, h("span", {}, "Call it: how many of you get it?"), Array.from({ length: c.N + 1 }, (_, n) => h("button", { type: "button", "aria-pressed": String(S.call === n), onclick: () => c.set(Object.assign({}, S, { call: n })) }, String(n))));
      return frag(top, h("div", { class: "h" }, q.q), opts, calls, h("div", { class: "row" }, h("span", { class: "tm", "data-end": S.ends }), h("span", { class: "sub" }, `${inN} of ${c.N} in`), btn("Reveal", () => c.go(Trivia.force(S, c)), "plain")));
    }
    const said = `${res.got} of ${c.N} got it.` + (S.call == null ? "" : S.call === res.got ? " Called it." : ` You called ${S.call}.`);
    const last = S.k + 1 >= S.qs.length;
    return frag(top, h("div", { class: "h" }, q.q), opts, h("div", { class: "say" }, said),
      h("div", { class: "row" }, btn(last ? "See the block" : "Next question", () => c.go(last ? Object.assign({}, S, { ph: "end" }) : Object.assign({}, S, { ph: "ask", k: S.k + 1, ends: Date.now() + Trivia.SECS * 1000, call: null, res: null })))));
  },
  phone(x, seat, p) {
    const mine = p.mine();
    if (x.ph === "end") return frag(h("div", { class: "big" }, `The block: most of you right on ${(x.log || []).filter(Boolean).length} of ${x.n}.`), h("p", { class: "small" }, "Watch the TV."));
    const o = (t, i, tap) => h(tap ? "button" : "div", Object.assign({ class: "opt" + (x.ph === "show" ? (i === x.ans ? " right" : " dim") : ""), style: `--oc: var(--o${i + 1})` }, tap ? { type: "button", onclick: () => p.answer({ o: i }) } : {}), shape(i), h("span", {}, t));
    if (x.ph === "ask") {
      if (mine) return frag(h("div", { class: "who" }, `Question ${x.k + 1} · locked in`), o(x.opts[mine.o], mine.o, false), h("p", { class: "small" }, "Watch the TV."));
      return frag(h("div", { class: "who" }, `Question ${x.k + 1} of ${x.n} · it's on the TV`), h("div", { class: "opts" }, x.opts.map((t, i) => o(t, i, true))));
    }
    const my = x.picks ? x.picks[seat] : -1;
    return frag(h("div", { class: "big" }, my < 0 ? "Time's up." : my === x.ans ? "Right." : "Not this one."), my === x.ans ? null : h("p", { class: "small" }, `It was ${x.opts[x.ans]}.`), o(x.opts[x.ans], x.ans, false));
  },
  bot(x) {
    if (x.ph !== "ask") return null;
    const key = (o) => o.slice().sort().join("|");
    const q = D.trivia.find((qq) => key(qq.opts) === key(x.opts));
    const right = q ? x.opts.indexOf(q.opts[q.ans]) : -1;
    return { a: { o: right >= 0 && rnd() < 0.65 ? right : int(4) } };
  },
  botDelay: () => 1500 + int(5000),
};

const DrawIt = {
  id: "draw", name: "Draw it", like: "Like Telestrations", min: 3, max: 8, DRAW: 75, GUESS: 35,
  line: "A topic goes round the phones: draw it, the next one guesses from the drawing, the next draws the guess. The reveal is every chain.",
  learn: "Drawing a thing means knowing what it looks like.",
  chainOf: (i, st, N) => (((i - st) % N) + N) % N,
  start(c) {
    const pool = c.bots ? Object.keys(D.doodles) : D.draw;
    const prompts = shuffle(pool).slice(0, c.N);
    while (prompts.length < c.N) prompts.push(pick(D.draw));
    const T = c.N >= 4 ? 4 : c.N;
    return { ph: "step", st: 0, T, chains: prompts.map((t, i) => [{ k: "p", t, by: i }]), ends: Date.now() + DrawIt.DRAW * 1000, rc: 0, ri: 0 };
  },
  text(ch) { for (let k = ch.length - 1; k >= 0; k--) if (ch[k].t && ch[k].t !== "(no guess)") return ch[k].t; return "?"; },
  pub(S, c) {
    const x = { ph: S.ph, st: S.st, T: S.T, kind: S.st % 2 === 0 ? "draw" : "guess" };
    if (S.ph === "step" && x.kind === "draw") x.texts = c.seats.map((_, i) => DrawIt.text(S.chains[DrawIt.chainOf(i, S.st, c.N)]));
    return x;
  },
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
        h("p", { class: "lead" }, draw ? "On your phones. No letters, no numbers." : "Type your guess on your phone."),
        h("div", { class: "row" }, h("span", { class: "tm", "data-end": S.ends }), h("div", { class: "ppl" }, c.seats.map((_, i) => { const ok = DrawIt.done(S, c.A, c, i); return h("span", { class: ok ? "ok" : "" }, c.name(i), ok ? " ✓" : ""); }))),
        pip(draw ? "focus" : "peek"));
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
  phoneDeps(x, seat, p) {
    if (x.ph !== "step" || x.kind !== "guess") return 0;
    const d = p.pres((seat - 1 + p.seats.length) % p.seats.length).d;
    return d && d.s === p.s - 1 ? [d.s, (d.k || []).length] : null;
  },
  phone(x, seat, p) {
    const mine = p.mine(), N = p.seats.length, prev = (seat - 1 + N) % N;
    if (x.ph === "reveal") return frag(h("div", { class: "big" }, "Watch the TV."), h("p", { class: "small" }, "The chains are coming out."));
    if (x.kind === "draw") {
      if (mine) return frag(h("div", { class: "big" }, "Sent."), h("p", { class: "small" }, "Watch the TV while the others finish."));
      const text = (x.texts || [])[seat] || "?";
      const ink = h("i");
      const pd = pad(() => { ink.style.width = Math.round(pd.left() * 100) + "%"; });
      requestAnimationFrame(() => pd.repaint());
      return frag(h("div", { class: "who" }, x.st === 0 ? "Draw your topic" : `Draw what ${p.name(prev)} guessed`), h("div", { class: "big" }, text), pd.el,
        h("div", { class: "ink", "aria-label": "Ink left" }, ink),
        h("div", { class: "row" }, btn("Undo", () => pd.undo(), "plain"), btn("Clear", () => pd.clear(), "plain"), btn("Send", () => p.answer({ ok: 1 }, { d: { s: p.s, k: pd.strokes() } }))));
    }
    if (mine) return frag(h("div", { class: "big" }, `You guessed: ${mine.g}`), h("p", { class: "small" }, "Watch the TV."));
    const d = p.pres(prev).d, got = d && d.s === p.s - 1 ? d.k : null;
    const inp = p.draft("g", h("input", { type: "text", maxlength: 40, placeholder: "What is it?", "aria-label": "Your guess", autocomplete: "off" }));
    return frag(h("div", { class: "who" }, `${p.name(prev)} drew this. What is it?`), got ? drawingSvg(got, "dw big") : h("p", { class: "small" }, "Waiting for the drawing…"),
      h("form", { class: "f", onsubmit: (e) => { e.preventDefault(); const g = clip(inp.value, 40); if (g) p.answer({ g }); } }, inp, h("button", { class: "btn", type: "submit" }, "Send")));
  },
  bot(x, seat, b) {
    if (x.ph !== "step") return null;
    const all = Object.values(D.doodles);
    if (x.kind === "draw") {
      const t = (x.texts || [])[seat];
      const dd = D.doodles[t] || all.find((v) => v.guess === t) || pick(all);
      return { a: { ok: 1 }, d: { k: dd.k } };
    }
    const d = b.pres((seat - 1 + b.N) % b.N).d;
    if (!d || d.s !== b.s - 1) return null;
    const hit = all.find((v) => JSON.stringify(v.k) === JSON.stringify(d.k));
    return { a: { g: hit ? hit.guess : pick(D.botGuess) } };
  },
  botDelay: () => 2000 + int(3000),
};

const Between = {
  id: "between", name: "Somewhere between", like: "Like Wavelength", min: 2, max: 8,
  line: "One person sees where a hidden target sits between two ends and names something that sits there. Everyone turns their dial; the table's dial is the average.",
  learn: "How bad, how common, how fast: putting what you know on a scale.",
  pts: (d) => (d <= 4 ? 4 : d <= 9 ? 3 : d <= 15 ? 2 : 0),
  start() { return { ph: "clue", psy: 0, order: shuffle(D.waves.map((_, i) => i)), wi: 0, target: 6 + int(89), clue: null, score: 0, rounds: 0, res: null }; },
  pub(S) {
    const w = D.waves[S.order[S.wi]];
    const x = { ph: S.ph, psy: S.psy, L: w.L, R: w.R, target: S.target, score: S.score, rounds: S.rounds };
    if (S.clue) x.clue = S.clue;
    if (S.res) x.res = S.res;
    return x;
  },
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
    const w = D.waves[S.order[S.wi]], psy = c.name(S.psy), A = c.A;
    const head = h("div", { class: "row sp" }, h("span", { class: "sub" }, `Somewhere between · ${says(psy, "you have", "has")} the dial`), h("span", { class: "sub" }, `The table: ${plural(S.score, "point", "points")}`));
    if (S.ph === "clue") return frag(head, h("div", { class: "h" }, `${says(psy, "You're", "is")} thinking of a clue.`), dial({ L: w.L, R: w.R }), h("p", { class: "lead" }, `${says(psy, "You can", "can")} see where the target is. ${you(psy) ? "Your" : "Their"} clue is something that sits right there.`));
    if (S.ph === "guess") {
      const live = A.map((a, i) => (i !== S.psy && a && typeof a.g === "number" ? a.g : null)).filter((v) => v != null);
      const avg = live.length ? live.reduce((s, v) => s + v, 0) / live.length : 50;
      const locked = A.filter((a, i) => i !== S.psy && a && a.lock === 1).length;
      return frag(head, h("div", { class: "h q" }, `“${S.clue}”`), dial({ L: w.L, R: w.R, needle: avg }),
        h("div", { class: "row" }, h("span", { class: "sub" }, `Turn your dial on your phone, then lock in · ${locked} of ${c.N - 1} locked`), btn("Reveal now", () => c.go(Between.force(S, c)), "plain")));
    }
    const r = S.res, words = { 4: "Bullseye.", 3: "Close.", 2: "In the zone.", 0: "Missed it." }[r.pts];
    const last = S.rounds >= c.N, nxt = (S.psy + 1) % c.N;
    return frag(head, h("div", { class: "h q" }, `“${S.clue}”`),
      dial({ L: w.L, R: w.R, needle: r.avg, target: S.target, dots: r.g.map((v, i) => (v >= 0 ? [v, c.name(i)] : null)).filter(Boolean) }),
      h("div", { class: "say" }, `${words} ${r.pts ? "+" + r.pts : "No points"}, and the table has ${plural(S.score, "point", "points")}.`),
      last ? h("p", { class: "sub" }, `Everyone's had the dial: ${plural(S.score, "point", "points")} together in ${plural(S.rounds, "round", "rounds")}.`) : null,
      h("div", { class: "row" }, last ? btn("Play again", () => c.again()) : btn(`Next: ${says(c.name(nxt), "you have", "has")} the dial`, () => c.go(Object.assign({}, S, { ph: "clue", psy: nxt, wi: (S.wi + 1) % D.waves.length, target: 6 + int(89), clue: null, res: null }))),
        btn("Back to games", () => c.lobby(), "plain")));
  },
  phone(x, seat, p) {
    const psy = seat === x.psy, mine = p.mine();
    const ends = h("div", { class: "ends" }, h("span", {}, x.L), h("span", {}, x.R));
    if (x.ph === "clue") {
      if (!psy) return frag(h("div", { class: "big" }, `${p.name(x.psy)} has the dial.`), ends, h("p", { class: "small" }, "Wait for their clue."));
      if (mine) return frag(h("div", { class: "big" }, `Your clue: ${mine.c}`), h("p", { class: "small" }, "Keep a straight face."));
      const inp = p.draft("c", h("input", { type: "text", maxlength: 40, placeholder: "Something that sits there", "aria-label": "Your clue", autocomplete: "off" }));
      return frag(h("div", { class: "who" }, "You have the dial. Only you can see this."), dial({ L: x.L, R: x.R, target: x.target }),
        h("p", { class: "small" }, "Name a disease, a drug, anything medical that sits right there."),
        h("form", { class: "f", onsubmit: (e) => { e.preventDefault(); const cl = clip(inp.value, 40); if (cl) p.answer({ c: cl }); } }, inp, h("button", { class: "btn", type: "submit" }, "Send")));
    }
    if (x.ph === "guess") {
      if (psy) return frag(h("div", { class: "big" }, "Keep a straight face."), h("p", { class: "small" }, `Your clue: “${x.clue}”`));
      if (mine && mine.lock === 1) return frag(h("div", { class: "big" }, "Locked in."), h("p", { class: "small" }, "Watch the TV."));
      const out = h("output", {}, "50");
      const rng = h("input", { type: "range", min: 0, max: 100, value: 50, "aria-label": "Your dial", class: "rng" });
      rng.addEventListener("input", () => { out.textContent = rng.value; p.live({ g: Number(rng.value) }); });
      return frag(h("div", { class: "who" }, `“${x.clue}”`), h("p", { class: "small" }, "Where does it sit? The TV shows the table's dial as you all turn."), rng, ends, h("div", { class: "row sp" }, out, btn("Lock in", () => p.answer({ g: Number(rng.value), lock: 1 }))));
    }
    const my = x.res && x.res.g ? x.res.g[seat] : -1;
    return frag(h("div", { class: "big" }, x.res && x.res.pts ? `+${x.res.pts} for the table` : "No points this time"), h("p", { class: "small" }, !psy && my >= 0 ? `You said ${my}. The target was ${x.target}.` : `The target was ${x.target}.`), h("p", { class: "small" }, "Watch the TV."));
  },
  bot(x, seat) {
    const w = D.waves.find((ww) => ww.L === x.L);
    if (x.ph === "clue" && seat === x.psy) { const ex = w ? w.ex.slice().sort((a, b) => Math.abs(a[1] - x.target) - Math.abs(b[1] - x.target))[0] : null; return { a: { c: ex ? ex[0] : "Hmm" } }; }
    if (x.ph === "guess" && seat !== x.psy) { const ex = w && w.ex.find((e) => e[0] === x.clue); const base = ex ? ex[1] : x.target; return { a: { g: Math.max(0, Math.min(100, Math.round(base + (rnd() - 0.5) * 24))), lock: 1 } }; }
    return null;
  },
};

const LINKPOOL = [...new Set(Object.values(D.links).flat())];
const KIND = ["neutral", "target", "Code blue"];
const Links = {
  id: "links", name: "Links", like: "Like Codenames, all on one team", min: 2, max: 8, TARGETS: 6, TURNS: 5,
  line: "Sixteen topics on the TV. One person sees which six are the table's and gives a one-word clue that links some of them. Find all six in five clues, and stay off Code blue.",
  learn: "One mechanism, three diseases: finding what ties the deck together.",
  start(c) {
    const tiles = shuffle(LINKPOOL).slice(0, 16);
    const kinds = shuffle([1, 1, 1, 1, 1, 1, 2].concat(Array(9).fill(0)));
    return { ph: "clue", giver: 0, tiles, key: kinds, shown: Array(16).fill(-1), clue: null, left: 0, turns: Links.TURNS, found: 0, last: null, result: null };
  },
  pub(S) {
    const x = { ph: S.ph, giver: S.giver, tiles: S.tiles, key: S.key, shown: S.shown, left: S.left, turns: S.turns, found: S.found, need: Links.TARGETS };
    if (S.clue) x.clue = S.clue;
    if (S.last) x.last = S.last;
    if (S.result) x.result = S.result;
    return x;
  },
  okClue(S, w) { const n = norm(w); return !!n && !S.tiles.some((t) => norm(t) === n || t.toLowerCase().split(/[\s-]+/).map(norm).includes(n)); },
  collect(S, A, c) {
    if (S.ph === "clue") { const a = A[S.giver]; return a && typeof a.w === "string" && Number.isInteger(a.n) ? Links.force(S, c) : null; }
    if (S.ph === "guess") {
      for (let i = 0; i < c.N; i++) {
        const a = A[i];
        if ((i === S.giver && c.N > 1) || !a) continue;  // alone, the giver guesses too
        if (a.pass === 1 || (Number.isInteger(a.t) && a.t >= 0 && a.t < 16 && S.shown[a.t] < 0)) return Links.apply(S, a, c, i);
      }
    }
    return null;
  },
  force(S, c) {
    if (S.ph === "clue") {
      const a = c.A[S.giver];
      const w = a && typeof a.w === "string" && Links.okClue(S, one(clip(a.w, 24))) ? one(clip(a.w, 24)) : "(no clue)";
      const n = a && Number.isInteger(a.n) ? Math.max(1, Math.min(4, a.n)) : 1;
      return Object.assign({}, S, { ph: "guess", clue: { w, n }, left: n + 1, last: null });
    }
    if (S.ph === "guess") return Links.endTurn(S, c);
    return null;
  },
  endTurn(S, c) {
    const turns = S.turns - 1;
    if (turns <= 0) return Object.assign({}, S, { ph: "end", turns, result: "out" });
    return Object.assign({}, S, { ph: "clue", giver: (S.giver + 1) % c.N, clue: null, left: 0, turns });
  },
  apply(S, a, c, i) {
    if (a.pass === 1) return Object.assign(Links.endTurn(S, c), { last: { pass: 1, by: i } });
    const t = a.t, kind = S.key[t], shown = S.shown.slice();
    shown[t] = kind;
    const last = { t, kind, by: i };
    const S2 = Object.assign({}, S, { shown, last });
    if (kind === 2) return Object.assign(S2, { ph: "end", result: "blue" });
    if (kind === 0) return Object.assign(Links.endTurn(S2, c), { last });
    const found = S.found + 1;
    if (found >= Links.TARGETS) return Object.assign(S2, { ph: "end", found, result: "win" });
    const left = S.left - 1;
    if (left <= 0) return Object.assign(Links.endTurn(Object.assign(S2, { found }), c), { last });
    return Object.assign(S2, { found, left });
  },
  grid(S, opts) {
    return h("div", { class: "grid4" + (opts.small ? " sm" : "") }, S.tiles.map((t, k) => {
      const shown = S.shown[k], key = opts.key ? S.key[k] : -1;
      const cls = shown >= 0 ? ["n", "y", "x"][shown] + " open" : key >= 0 ? ["kn", "ky", "kx"][key] : "";
      const tap = opts.tap && shown < 0;
      return h(tap ? "button" : "div", Object.assign({ class: "lt " + cls }, tap ? { type: "button", onclick: () => opts.tap(k) } : {}), t, shown >= 0 ? h("small", {}, KIND[shown]) : key === 2 ? h("small", {}, "Code blue") : null);
    }));
  },
  tv(S, c) {
    const giver = c.name(S.giver);
    const status = h("div", { class: "row sp" }, h("span", { class: "sub" }, `Links · ${S.found} of ${Links.TARGETS} found · ${plural(S.turns, "clue", "clues")} left`),
      h("div", { class: "meter" }, Array.from({ length: Links.TARGETS }, (_, k) => h("i", { class: k < S.found ? "on" : "" }))));
    const lastLine = S.last ? (S.last.pass ? says(c.name(S.last.by), "You passed.", "passed.") : `${says(c.name(S.last.by), "You picked", "picked")} ${S.tiles[S.last.t]}: ${S.last.kind === 1 ? "one of ours." : S.last.kind === 0 ? "not ours, so the clue's over." : "Code blue."}`) : "";
    if (S.ph === "end") {
      const words = { win: "All six, together.", blue: "Code blue. The round's over.", out: `Out of clues with ${S.found} of ${Links.TARGETS}.` }[S.result];
      return frag(status, h("div", { class: "row" }, pip(S.result === "win" ? "cheer" : "again"), h("div", { class: "h" }, words)), h("p", { class: "lead" }, lastLine),
        Links.grid(S, { key: true }), h("div", { class: "row" }, btn("Another board", () => c.again()), btn("Back to games", () => c.lobby(), "plain")));
    }
    if (S.ph === "clue") return frag(status, h("div", { class: "h" }, `${says(giver, "You're", "is")} thinking of a clue.`), h("p", { class: "lead" }, lastLine || `${says(giver, "You see", "sees")} which six are the table's. One word, and how many it links.`), Links.grid(S, {}));
    return frag(status, h("div", { class: "row sp" }, h("div", { class: "h q" }, `“${S.clue.w}” · ${S.clue.n}`), h("span", { class: "sub" }, `${plural(S.left, "guess", "guesses")} left on this clue`)),
      h("p", { class: "lead" }, lastLine || "Talk it over, then tap a topic on your phone. Anyone can tap."), Links.grid(S, {}));
  },
  phone(x, seat, p) {
    const S = x, giver = seat === x.giver, mine = p.mine();
    if (x.ph === "end") return frag(h("div", { class: "big" }, x.result === "win" ? "All six, together." : x.result === "blue" ? "Code blue." : "Out of clues."), h("p", { class: "small" }, "Watch the TV."));
    if (x.ph === "clue") {
      if (!giver) return frag(h("div", { class: "big" }, `${p.name(x.giver)} is thinking of a clue.`), Links.grid(S, { small: true }));
      if (mine) return frag(h("div", { class: "big" }, `Your clue: ${mine.w} · ${mine.n}`), h("p", { class: "small" }, "Watch them guess. No faces."));
      const said = h("p", { class: "small", role: "status" });
      const inp = p.draft("w", h("input", { type: "text", maxlength: 24, placeholder: "One word", "aria-label": "Your clue", autocomplete: "off", autocapitalize: "off" }));
      const num = h("select", { "aria-label": "How many it links" }, [1, 2, 3, 4].map((n) => h("option", { value: n }, String(n))));
      return frag(h("div", { class: "who" }, "You give the clue. Only you see the colors."), Links.grid(S, { key: true, small: true }),
        h("form", { class: "f two", onsubmit: (e) => { e.preventDefault(); const w = one(clip(inp.value, 24)); if (!w) return; if (!Links.okClue(S, w)) { said.textContent = "That word's on the board. Pick another."; return; } p.answer({ w, n: Number(num.value) }); } },
          inp, num, h("button", { class: "btn", type: "submit" }, "Send")), said,
        h("p", { class: "small" }, "Green are the table's. Stay away from Code blue."));
    }
    if (giver && p.seats.length > 1) return frag(h("div", { class: "big" }, `“${x.clue.w}” · ${x.clue.n}`), h("p", { class: "small" }, "Say nothing. Watch them guess."), Links.grid(S, { key: true, small: true }));
    return frag(h("div", { class: "who" }, `“${x.clue.w}” · ${x.clue.n} · ${plural(x.left, "guess", "guesses")} left`),
      Links.grid(S, { small: true, tap: (k) => p.answer({ t: k }) }),
      h("div", { class: "row" }, btn("Pass", () => p.answer({ pass: 1 }), "plain"), h("span", { class: "small" }, "Anyone at the table can tap.")));
  },
  bot(x, seat) {
    if (x.ph === "clue" && seat === x.giver) {
      const open = (k) => x.shown[k] < 0;
      let best = null;
      for (const [w, ts] of Object.entries(D.links)) {
        if (!Links.okClue(x, w)) continue;
        const idx = x.tiles.map((t, k) => (ts.includes(t) && open(k) ? k : -1)).filter((k) => k >= 0);
        if (idx.some((k) => x.key[k] === 2)) continue;
        const hits = idx.filter((k) => x.key[k] === 1).length, misses = idx.filter((k) => x.key[k] === 0).length;
        const score = hits - 0.6 * misses;
        if (hits && (!best || score > best.score)) best = { w, n: Math.min(3, hits), score };
      }
      return { a: best ? { w: best.w, n: best.n } : { w: "hmm", n: 1 } };
    }
    if (x.ph === "guess" && seat !== x.giver) {
      const used = x.clue.n + 1 - x.left;
      const ts = D.links[norm(x.clue.w)] || [];
      const cand = x.tiles.map((t, k) => (x.shown[k] < 0 && ts.includes(t) ? k : -1)).filter((k) => k >= 0);
      if (!cand.length || used >= x.clue.n) return { a: { pass: 1 } };
      return { a: { t: pick(cand) } };
    }
    return null;
  },
  botDelay: () => 3500 + int(3000),
};

// While we're testing, before game night goes wider: any game starts with
// one player. Each game's own min stays on its tile and in the lobby's word;
// set FEW to Infinity then, and every game needs its min again.
const FEW = 1;
const need = (g) => Math.min(g.min, FEW);

const GAMES = { imposter: Imposter, rounds: Rounds, trivia: Trivia, draw: DrawIt, between: Between, links: Links };
const ORDER = ["imposter", "rounds", "trivia", "draw", "between", "links"];

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
    const hub = this, me = { peer, host: !!host, p: {}, subs: [] };
    hub.cs.push(me);
    return {
      peer,
      presence(patch) { me.p = Object.freeze(merge(me.p, patch)); hub.tick(); return Promise.resolve(); },
      peers: () => hub.list(peer),
      onPeers(fn) { me.subs.push(fn); queueMicrotask(() => fn({ peers: hub.list(peer) })); return () => { me.subs = me.subs.filter((f) => f !== fn); }; },
      leave() { hub.cs = hub.cs.filter((c) => c !== me); hub.tick(); return Promise.resolve(); },
    };
  }
}
function tabClient(name, host) {
  const peer = "t" + Math.random().toString(36).slice(2, 10);
  const ch = new BroadcastChannel("gn-" + name);
  const others = new Map(), subs = [];
  let mine = {};
  const list = () => [{ peer, isMe: true, sameTab: true, host: !!host, presence: mine }].concat([...others].map(([k, v]) => ({ peer: k, isMe: false, sameTab: false, host: v.host, presence: v.p })));
  let queued = false;
  const fire = () => { if (queued) return; queued = true; queueMicrotask(() => { queued = false; const ps = list(); subs.slice().forEach((f) => f({ peers: ps })); }); };
  const say = () => ch.postMessage({ t: "p", peer, host: !!host, p: mine });
  ch.onmessage = (e) => {
    const m = e.data || {};
    if (m.t === "hi") say();
    if (m.t === "p" && m.peer !== peer) { others.set(m.peer, { host: !!m.host, p: Object.freeze(m.p || {}) }); fire(); }
    if (m.t === "bye") { others.delete(m.peer); fire(); }
  };
  addEventListener("pagehide", () => ch.postMessage({ t: "bye", peer }));
  ch.postMessage({ t: "hi" });
  return {
    peer,
    presence(patch) { mine = Object.freeze(merge(mine, patch)); say(); fire(); return Promise.resolve(); },
    peers: list,
    onPeers(fn) { subs.push(fn); queueMicrotask(() => fn({ peers: list() })); return () => {}; },
    leave() { ch.postMessage({ t: "bye", peer }); ch.close(); return Promise.resolve(); },
  };
}

/** A seat at a table on the API: one socket, my presence sent whole (at most
 *  25 times a second), everyone's kept as the table hands them on. Lost, it
 *  comes back with the same id, so its seat is still its own. A phone the
 *  table hasn't let in yet waits at the door (`waiting`); the host's also
 *  holds the door (`door`, and admit, away, setDoor, lock). */
function wsClient(code, key, onState) {
  const cid = clientId();
  let ws = null, you = null, isHost = false, mine = {}, timer = null, backoff = 600, hello = false, misses = 0, done = false;
  let waiting = false, door = null, shut = "";
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
      else if (m.t === "err") warn(m.error);
    };
    ws.onclose = (e) => {
      ws = null; hello = false;
      if (done) return;
      const why = { 4000: "closed", 4001: "elsewhere", 4002: "another", 4003: "away", 4004: "crewonly", 4005: "locked", 4006: "full" }[e.code];
      if (why) { done = true; shut = why; others.clear(); fire(); onState(why); return; }
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
  const T = { mode: "lobby", chosen: "imposter", game: null, S: null, step: 0, seats: [], peers: [], key: "", sure: "" };
  const players = () => T.peers.filter((p) => !(p.isMe && p.sameTab) && !p.wait && p.presence && p.presence.r === "p" && typeof p.presence.n === "string")
    .sort((a, b) => (Number(a.presence.t) || 0) - (Number(b.presence.t) || 0) || (a.peer < b.peer ? -1 : 1));
  const peerOf = (i) => (T.seats[i] ? T.peers.find((x) => x.peer === T.seats[i].peer) : null);
  const presOf = (i) => { const p = peerOf(i); return (p && p.presence) || {}; };
  const answers = () => T.seats.map((_, i) => { const a = presOf(i).a; return a && typeof a === "object" && a.s === T.step ? a : null; });
  function ctx() {
    return { N: T.seats.length, seats: T.seats, name: (i) => (T.seats[i] ? T.seats[i].n : "?"), A: answers(), pres: presOf, here: (i) => !!peerOf(i), bots: !!opt.bots, go, set, again, lobby };
  }
  function publish() {
    const g = T.mode === "game" ? { m: "game", gm: T.game.id, s: T.step, seats: T.seats.map((s) => ({ peer: s.peer, n: s.n })), x: T.game.pub(T.S, ctx()) } : { m: "lobby", gm: T.chosen, s: T.step };
    client.presence({ r: "tv", code: opt.code, g }).catch(warn);
  }
  function go(S) { if (!S) return; T.S = S; T.step++; publish(); draw(true); }
  function set(S) { T.S = S; publish(); draw(true); }
  function again() { go(T.game.start(ctx())); }
  function lobby() { T.mode = "lobby"; T.game = null; T.S = null; T.step++; publish(); draw(true); }
  function start() {
    const g = GAMES[T.chosen], ps = players();
    if (ps.length < need(g)) return;
    T.game = g;
    T.seats = ps.slice(0, g.max).map((p) => ({ peer: p.peer, n: clip(p.presence.n, 16) || "Someone" }));
    T.mode = "game";
    go(g.start(ctx()));
  }
  function check() { if (T.mode !== "game") return; const c = ctx(); const S2 = T.game.collect(T.S, c.A, c); if (S2) go(S2); }
  client.onPeers((ch) => { T.peers = ch.peers || []; check(); draw(); }, (e) => { root.replaceChildren(h("div", { class: "note" }, `The room closed (${e && e.code}).`)); });
  const iv = setInterval(() => {
    if (!root.isConnected) { clearInterval(iv); return; }
    if (T.mode === "game" && T.game.timeout) { const c = ctx(); const S2 = T.game.timeout(T.S, c.A, c); if (S2) { go(S2); return; } }
    tick();
  }, 250);
  function tick() {
    root.querySelectorAll("[data-end]").forEach((el) => { const left = Math.max(0, Number(el.dataset.end) - Date.now()); el.textContent = `${Math.ceil(left / 1000)}s`; el.classList.toggle("low", left < 6000); });
  }
  function lobbyView() {
    const ps = players(), g = GAMES[T.chosen];
    const code = h("div", { class: "code" }, h("div", { class: "lbl" }, opt.bots ? "Playing with bots" : "Join on your phones"),
      opt.bots ? h("p", { class: "lead" }, "Maya, Dre, Jo and Kai are bots. You play on the phone beside the TV.") : h("div", { class: "letters" }, opt.code),
      opt.bots ? null : h("div", { class: "joinat" }, typeof QR !== "undefined" ? QR.svg(`${location.origin}/t/${opt.code}`, 132) : null,
        h("p", { class: "lead" }, "On your phone: scan this, or go to ", h("b", {}, `${location.host}/t/${opt.code}`), ". No account needed.")));
    const people = h("div", { class: "ppl big" }, ps.length ? ps.map((p) => h("span", { class: "ok" }, clip(p.presence.n, 16) || "Someone",
      p.crew ? h("i", { title: `Signed in as ${clip(p.crew, 40)}` }, " crew") : null,
      client.door ? h("button", { type: "button", class: "x", "aria-label": `Turn ${clip(p.presence.n, 16) || "them"} away`, onclick: () => { T.sure = p.peer; draw(true); } }, "×") : null)) : h("span", {}, "Nobody's here yet."));
    const tiles = h("div", { class: "tiles" }, ORDER.map((id) => { const gg = GAMES[id]; return h("button", { type: "button", class: "tile" + (id === T.chosen ? " on" : ""), "aria-pressed": String(id === T.chosen), onclick: () => { T.chosen = id; publish(); draw(true); } },
      h("span", { class: "like" }, gg.like), h("b", {}, gg.name), h("span", { class: "ln" }, gg.line), h("span", { class: "lr" }, gg.learn), h("span", { class: "np" }, `${gg.min}–${gg.max} players`)); }));
    const short = ps.length < need(g), few = !short && ps.length < g.min;
    return frag(h("div", { class: "lobby" }, code, h("div", { class: "stack" }, h("div", { class: "lbl" }, `At the table · ${ps.length}`), people, sureView(), doorView())), h("div", { class: "lbl" }, "Pick a game"), tiles,
      h("div", { class: "row" }, h("button", { type: "button", class: "btn", disabled: short, onclick: start }, `Start ${g.name}`),
        short ? h("span", { class: "sub" }, ps.length ? `${g.name} needs ${plural(need(g), "player", "players")} or more.` : "Waiting for a phone to join.") : few ? h("span", { class: "sub" }, `Made for ${g.min} or more. While we're testing, it starts with fewer.`) : null));
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
      h("p", { class: "small" }, d.locked ? "Locked: nobody new, though anyone who sat down can come back." : { ask: "Your crew, signed in, come straight in. Anyone else waits here till you let them in.", crew: "Only your crew, signed in on their phones.", open: "Anyone with the code comes straight in." }[d.door] || ""),
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
    return own ? body : frag(body, h("div", { class: "row foot" }, T.game.force ? btn("Skip ahead", () => { const S2 = T.game.force(T.S, ctx()); if (S2) go(S2); }, "ghost") : null, btn("Back to games", lobby, "ghost")));
  }
  function draw(force) {
    const c = ctx();
    const key = JSON.stringify([T.mode, T.chosen, T.step, T.S, c.A, players().map((p) => [p.peer, p.presence.n, p.crew]), waiting().map((p) => [p.peer, p.presence.n]), client.door, T.sure]);
    if (!force && key === T.key) return;
    T.key = key;
    root.replaceChildren(T.mode === "lobby" ? lobbyView() : gameView(c));
    tick();
  }
  publish();
  draw(true);
  return T;
}

// ---------- a phone: answers in its own presence ----------
function Phone(root, client, name) {
  const P = { key: "", myA: null, drafts: {}, peers: [] };
  client.presence({ r: "p", n: name, t: Date.now() }).catch(warn);
  const tvOf = () => P.peers.find((p) => p.host && p.presence && p.presence.r === "tv" && p.presence.g && typeof p.presence.g === "object");
  const myPeer = () => { const me = P.peers.find((p) => p.isMe && p.sameTab); return (me && me.peer) || client.peer; };
  client.onPeers((ch) => { P.peers = ch.peers || []; draw(); }, (e) => { root.replaceChildren(h("div", { class: "note" }, `The room closed (${e && e.code}).`)); });
  function pc(pub, seat) {
    return {
      s: pub.s, seat, seats: pub.seats, name: (i) => (pub.seats[i] ? clip(pub.seats[i].n, 16) : "?"),
      mine: () => (P.myA && P.myA.s === pub.s ? P.myA : null),
      answer(fields, extra) { const a = Object.assign({ s: pub.s }, fields); P.myA = a; client.presence(Object.assign({ a }, extra || {})).catch(warn); draw(true); },
      live(fields) { client.presence({ a: Object.assign({ s: pub.s }, fields) }).catch(() => {}); },
      pres(i) { const s = pub.seats[i], p = s && P.peers.find((x) => x.peer === s.peer); return (p && p.presence) || {}; },
      draft(id, el) { const k = pub.s + ":" + id; if (P.drafts[k] != null) el.value = P.drafts[k]; el.addEventListener("input", () => { P.drafts[k] = el.value; }); return el; },
    };
  }
  function draw(force) {
    const tv = tvOf(), pub = tv ? tv.presence.g : null, me = myPeer();
    let seat = -1, deps = 0;
    if (pub && pub.m === "game" && Array.isArray(pub.seats)) {
      seat = pub.seats.findIndex((s) => s && s.peer === me);
      const g = GAMES[pub.gm];
      if (g && g.phoneDeps && seat >= 0) { try { deps = g.phoneDeps(pub.x, seat, pc(pub, seat)); } catch (e) { deps = 0; } }
    }
    const key = JSON.stringify([!!tv, pub, seat, P.myA, deps, !!client.waiting, client.shut || ""]);
    if (!force && key === P.key) return;
    P.key = key;
    const head = h("div", { class: "ph-top" }, h("b", {}, name), h("span", {}, client.shut ? "" : client.waiting ? "At the door" : tv ? `Game night · ${clip(tv.presence.code, 8)}` : "Looking for the TV"));
    let body;
    if (client.shut && SHUT[client.shut]) body = frag(h("div", { class: "big" }, SHUT[client.shut][0]), h("p", { class: "small" }, SHUT[client.shut][1]), h("div", { class: "row" }, btn("Back to game night", () => { bye(); history.replaceState(null, "", "/table"); home(); }, "plain")));
    else if (client.waiting) body = frag(h("div", { class: "big" }, `At the door, ${name}.`), h("p", { class: "small" }, "The host lets you in from the TV."));
    else if (!tv) body = frag(h("div", { class: "big" }, "Looking for the TV…"), h("p", { class: "small" }, "The code has to match the one on the TV."));
    else if (pub.m !== "game") body = frag(h("div", { class: "big" }, `You're in, ${name}.`), h("p", { class: "small" }, `Watch the TV.${GAMES[pub.gm] ? ` Up next: ${GAMES[pub.gm].name}.` : ""}`), pip("hello"));
    else if (!GAMES[pub.gm]) body = h("p", {}, "…");
    else if (seat < 0) body = frag(h("div", { class: "big" }, "This one started without you."), h("p", { class: "small" }, "You're in the next game."));
    else { try { body = GAMES[pub.gm].phone(pub.x, seat, pc(pub, seat)); } catch (e) { warn(e); body = h("p", { class: "small" }, "Waiting for the TV…"); } }
    root.replaceChildren(head, body);
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
      const bc = { s: pub.s, seat, seats: pub.seats, N: pub.seats.length, pres: (i) => { const s = pub.seats[i], p = s && ch.peers.find((x) => x.peer === s.peer); return (p && p.presence) || {}; } };
      let patch = null;
      try { patch = g.bot(pub.x, seat, bc); } catch (e) { warn(e); }
      if (!patch) return;
      done[pub.s] = true;
      if (patch.a) patch.a.s = pub.s;
      if (patch.d) patch.d.s = pub.s;
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
function bye() { if (leaving) { try { leaving(); } catch (_) { /* fine */ } leaving = null; } conn.textContent = ""; }
const back = () => h("button", { type: "button", class: "back", onclick: () => { bye(); history.replaceState(null, "", "/table"); home(); } }, "← Game night");
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
const makeCode = () => Array.from({ length: 4 }, () => "ABCDEFGHJKLMNPQRSTUVWXYZ"[int(24)]).join("");  // #local only: the API picks real ones
const codeOf = (v) => String(v || "").toUpperCase().replace(/[^A-Z]/g, "").slice(0, 4);
async function apiCall(method, path) {
  const r = await fetch(`/api${path}`, { method, headers: { "x-due-crew": "1" }, credentials: "same-origin" });
  let body = null;
  try { body = await r.json(); } catch (_) { body = null; }
  return { status: r.status, body };
}
function connect(code, key) {
  if (location.hash === "#local") return tabClient("gn-" + code.toLowerCase(), !!key);
  return wsClient(code, key, onState);
}

function home() {
  bye();
  app.className = "home";
  const saved = (() => { try { return JSON.parse(store.get("gn-host", true) || "null"); } catch (_) { return null; } })();
  app.replaceChildren(
    h("header", { class: "hero" }, h("h1", {}, "Game night"),
      h("p", { class: "lede" }, "Party games for a table of friends, with the studying inside them. One screen is the TV; everyone else plays on their phone."),
      h("div", { class: "modes" },
        h("button", { type: "button", class: "mode go", onclick: () => hostView() }, h("b", {}, "Host on this screen"), h("span", {}, "This screen is the TV. Friends join on their phones with a code. You sign in to host; they don't.")),
        h("button", { type: "button", class: "mode", onclick: () => joinView("") }, h("b", {}, "Join from your phone"), h("span", {}, "Type the four letters the TV shows.")),
        h("button", { type: "button", class: "mode", onclick: botsView }, h("b", {}, "Try it with bots"), h("span", {}, "The TV and your phone side by side, with four bots at the table."))),
      saved && saved.code ? h("p", { class: "sub" }, "Your table ", h("b", {}, saved.code), " may still be open: ", h("button", { type: "button", class: "back inline", onclick: () => hostView(saved) }, "go back to it"), ".") : null),
    h("section", { class: "games" }, h("div", { class: "lbl" }, "Six games"), h("div", { class: "tiles static" }, ORDER.map((id) => { const g = GAMES[id]; return h("div", { class: "tile" }, h("span", { class: "like" }, g.like), h("b", {}, g.name), h("span", { class: "ln" }, g.line), h("span", { class: "lr" }, g.learn), h("span", { class: "np" }, `${g.min}–${g.max} players`)); }))),
    h("section", { class: "fine" }, h("div", { class: "lbl" }, "How it works"),
      h("ul", {},
        h("li", {}, "The topics and questions are Due Crew's own sample packs: nothing from anyone's deck goes anywhere."),
        h("li", {}, "Who sits down is the host's say. Their crew, signed in, come straight in; anyone else waits at the door till the host lets them in. The host can make it crew only, lock the table, or turn someone away."),
        h("li", {}, "A table lasts the night: it closes after four hours, or once its TV has been gone a while. Nothing anyone types is kept."),
        h("li", {}, "Bots mode works on any one screen. The bots peek in Somewhere between, and they aren't much at drawing."))));
}

async function hostView(saved) {
  bye();
  app.className = "host";
  app.replaceChildren(back(), h("p", { class: "sub" }, "Opening a table…"));
  let code = saved && saved.code, key = saved && saved.key;
  if (location.hash === "#local") { code = code || makeCode(); key = key || "local"; }
  else if (!code) {
    const r = await apiCall("POST", "/table");
    if (r.status === 401) {
      app.replaceChildren(back(), h("div", { class: "card stack" }, h("div", { class: "h" }, "Sign in to host"),
        h("p", {}, "The TV's table is opened by someone signed in to Due Crew. Friends joining from their phones don't need an account."),
        h("div", { class: "row" }, h("a", { class: "btn", href: "/sign-in?next=/table" }, "Sign in"), btn("Try it with bots", botsView, "plain"))));
      return;
    }
    if (r.status !== 200 || !r.body || !r.body.code) {
      app.replaceChildren(back(), h("div", { class: "card stack" }, h("div", { class: "h" }, r.status === 429 ? "That's a lot of tables for one hour." : "Couldn't open a table."), h("p", {}, r.status === 429 ? "Try again in a while." : "Check your connection and try again."), btn("Back", home, "plain")));
      return;
    }
    code = r.body.code; key = r.body.key;
    store.set("gn-host", JSON.stringify({ code, key }), true);
  }
  const client = connect(code, key);
  leaving = () => client.leave();
  const tv = h("div", { class: "tv big", id: "tv" }, h("div", { class: "bar" }, h("b", {}, `Due Crew · Game night · ${code}`),
    h("button", { type: "button", class: "ghost", onclick: () => { const el = document.getElementById("tv"); if (el && el.requestFullscreen) el.requestFullscreen().catch(() => {}); } }, "Full screen")),
    h("div", { class: "in", id: "tv-in", "aria-live": "polite" }));
  app.replaceChildren(back(), tv);
  TV(document.getElementById("tv-in"), client, { code });
}

function joinView(pre) {
  bye();
  app.className = "join";
  const nm = h("input", { id: "j-name", type: "text", maxlength: 16, placeholder: "Your name", "aria-label": "Your name", value: store.get("gn-name"), autocomplete: "nickname" });
  const cd = h("input", { id: "j-code", type: "text", maxlength: 4, placeholder: "Code", "aria-label": "The TV's code", autocomplete: "off", autocapitalize: "characters", class: "codein", value: pre || "" });
  const said = h("p", { class: "small", role: "status" });
  const foot = h("p", { class: "small" }, "No account needed: the host lets you in from the TV. Their crew, signed in, go straight in.");
  const form = h("form", { class: "f card", onsubmit: async (e) => {
    e.preventDefault();
    const name = clip(nm.value, 16), code = codeOf(cd.value);
    if (!name) { said.textContent = "Your name, so the table knows who you are."; nm.focus(); return; }
    if (code.length !== 4) { said.textContent = "The code is the four letters on the TV."; cd.focus(); return; }
    store.set("gn-name", name);
    if (location.hash !== "#local") {
      said.textContent = "Finding the table…";
      const r = await apiCall("GET", `/table/${code}`).catch(() => ({ status: 0 }));
      if (r.status === 404) { said.textContent = "No table with that code. Check the TV."; return; }
      if (r.status === 429) { said.textContent = "That's a lot of tries. Wait a little, then try again."; return; }
      if (r.status !== 200) { said.textContent = "Couldn't reach the table. Check your connection."; return; }
      if (r.body && r.body.full) { said.textContent = "That table's full."; return; }
      if (r.body && r.body.door === "crew" && !r.body.crew) {
        said.replaceChildren("This table is for the host's crew. ", h("a", { href: `/sign-in?next=${encodeURIComponent("/t/" + code)}` }, "Sign in"), " on this phone, then join.");
        foot.hidden = true;
        return;
      }
    }
    const client = connect(code, null);
    leaving = () => client.leave();
    const ph = h("div", { class: "phone-solo", "aria-live": "polite" });
    app.replaceChildren(ph);
    Phone(ph, client, name);
  } }, h("div", { class: "lbl" }, "Join a game"), nm, cd, h("button", { class: "btn", type: "submit" }, "Join"), said, foot);
  app.replaceChildren(back(), form);
  (nm.value ? cd : nm).focus();
}

function botsView() {
  bye();
  app.className = "bots";
  const hub = new LocalHub();
  const tv = h("div", { class: "tv" }, h("div", { class: "bar" }, h("b", {}, "Due Crew · Game night · the TV"), h("span", {}, "bots")), h("div", { class: "in", id: "tv-in", "aria-live": "polite" }));
  const phone = h("div", {}, h("div", { class: "lbl" }, "Your phone"), h("div", { class: "phone" }, h("div", { class: "st" }, h("span", {}, "9:41"), h("span", {}, "●●●")), h("div", { class: "in", id: "ph-in", "aria-live": "polite" })));
  app.replaceChildren(back(), h("div", { class: "stage" }, tv, phone));
  Phone(document.getElementById("ph-in"), hub.client("you"), "You");
  runBots(hub, ["Maya", "Dre", "Jo", "Kai"]);
  TV(document.getElementById("tv-in"), hub.client("tv", true), { code: "BOTS", bots: true });
}

// duecrew.com/t/MKQZ is a join link: the code filled in
const fromLink = /^\/t\/([A-Za-z]{4})\/?$/.exec(location.pathname);
if (fromLink) joinView(codeOf(fromLink[1]));
else home();
})();
