"use strict";
// Share cards (mock "Share Cards", K1–K5): pictures of my own studying,
// drawn here in the browser from numbers the page already has. Nothing is
// sent or kept: the picture goes out through the phone's share sheet, or
// downloads. One person's own numbers, no names, no ranks. The cards wear
// their own green, light or dark, whatever the site's theme or accent,
// because they leave the site.

const Cards = (() => {
  const FONT = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Noto Color Emoji"';
  const LOOKS = {
    light: { bg: "#fbfbf6", ink: "#1f2a1f", mut: "#6a7568", g: "#2e7d32", g3: "#e3efe3", line: "#e3efe3", on: "#ffffff" },
    dark: { bg: "#141813", ink: "#eef2ea", mut: "#9fae9b", g: "#7cc47f", g3: "#243223", line: "#2c3a2b", on: "#122912" },
  };
  const SIZES = { story: [1080, 1350], link: [1200, 630], square: [1080, 1080] };
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  // "#rrggbb" mixed: k of a, the rest b (the Log's heat levels: 28/52/76/100%)
  const mix = (a, b, k) => {
    const p = (s) => [1, 3, 5].map((i) => parseInt(s.slice(i, i + 2), 16));
    const [x, y] = [p(a), p(b)];
    return `#${x.map((v, i) => Math.round(v * k + y[i] * (1 - k)).toString(16).padStart(2, "0")).join("")}`;
  };
  const level = (pal, l) => (l <= 0 ? pal.g3 : mix(pal.g, pal.g3, [0, 0.28, 0.52, 0.76, 1][Math.min(4, l)]));

  // the logo is final artwork: drawn from its own file, never re-typeset
  const logos = {};
  const logo = (look) => (logos[look] ||= new Promise((ok) => {
    const img = new Image();
    img.onload = () => ok(img); img.onerror = () => ok(null);
    img.src = look === "dark" ? "/logo-line-dark.svg" : "/logo-line.svg";
  }));

  function rr(c, x, y, w, h, r) {
    c.beginPath(); c.moveTo(x + r, y); c.arcTo(x + w, y, x + w, y + h, r); c.arcTo(x + w, y + h, x, y + h, r);
    c.arcTo(x, y + h, x, y, r); c.arcTo(x, y, x + w, y, r); c.closePath();
  }
  function text(c, s, x, y, size, color, o = {}) {
    c.font = `${o.weight || 400} ${size}px ${FONT}`;
    c.fillStyle = color; c.textAlign = o.align || "left"; c.textBaseline = o.base || "alphabetic";
    if ("letterSpacing" in c) c.letterSpacing = o.track ? `${o.track}px` : "0px";
    c.fillText(s, x, y);
    const w = c.measureText(s).width;
    if ("letterSpacing" in c) c.letterSpacing = "0px";
    return w;
  }
  // a line that fits: shrinks to min, then ends in …
  function fit(c, s, max, size, min, weight) {
    let z = size;
    for (; z > min; z -= 2) { c.font = `${weight} ${z}px ${FONT}`; if (c.measureText(s).width <= max) return [s, z]; }
    c.font = `${weight} ${min}px ${FONT}`;
    let t = s;
    while (t.length > 1 && c.measureText(`${t}…`).width > max) t = t.slice(0, -1);
    return [t === s ? s : `${t.trimEnd()}…`, min];
  }
  // up to n lines, words kept whole where they fit
  function wrap(c, s, max, size, weight, n) {
    c.font = `${weight} ${size}px ${FONT}`;
    const out = []; let cur = "";
    for (const w of s.split(/\s+/)) {
      const t = cur ? `${cur} ${w}` : w;
      if (c.measureText(t).width <= max || !cur) cur = t; else { out.push(cur); cur = w; }
    }
    if (cur) out.push(cur);
    if (out.length > n) { out.length = n; out[n - 1] = fit(c, `${out[n - 1]} …`, max, size, size, weight)[0]; }
    return out.map((l) => fit(c, l, max, size, size, weight)[0]);
  }
  const eyebrow = (c, s, x, y, size, pal, align) => text(c, s.toUpperCase(), x, y, size, pal.mut, { weight: 700, track: size * 0.12, align });
  async function head(c, pal, look, x, y, hgt) {
    const img = await logo(look);
    if (img) c.drawImage(img, x, y, (hgt * 910) / 76, hgt);
  }
  const hm = (ms) => { const m = Math.round(ms / 60000); return m >= 60 ? `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m` : `${m}m`; };
  const n = (v) => Number(v).toLocaleString("en-US");

  // ---- K1: my week ----
  async function week(c, W, H, size, d, on, pal, look) {
    const time = on.time && d.time ? hm(d.time) : null;
    const rev = on.reviews && d.reviews != null ? d.reviews : null;
    const big = time || (rev != null ? `${n(rev)} reviews` : d.one ? (d.studied ? "Studied" : "Not yet") : `${d.studied} day${d.studied === 1 ? "" : "s"}`);
    const days = d.one ? "today" : `${d.studied} of ${d.elapsed} day${d.elapsed === 1 ? "" : "s"}${d.elapsed < 7 ? " so far" : ""}`;
    const crew = on.crew && d.crew ? `with ${d.crew} crew ${d.one ? "today" : "this week"}` : "";
    const brow = d.one ? `Today · ${d.range}` : `My week · ${d.range}`;
    const streak = on.streak && d.streak ? d.streak : null;
    if (size === "link") {
      const P = 64;
      await head(c, pal, look, P, P, 34);
      eyebrow(c, brow, P, 214, 24, pal);
      text(c, big, P, 330, 104, pal.ink, { weight: 700 });
      const bits = [time && rev != null ? `${n(rev)} reviews` : null, on.reviews && d.newCards ? `${n(d.newCards)} new` : null, d.one ? null : days, streak ? `🔥 ${streak}` : null].filter(Boolean);
      text(c, fit(c, bits.join(" · "), 600, 30, 24, 400)[0], P, 392, 30, pal.mut);
      const x0 = 720, w = W - P - x0, gap = 12, s = (w - 6 * gap) / 7;
      d.days.forEach((x, i) => dayCell(c, x0 + i * (s + gap), 230, s, x, pal, 12, 4));
      d.days.forEach((x, i) => text(c, x.label, x0 + i * (s + gap) + s / 2, 230 + s + 38, 22, pal.mut, { weight: 700, align: "center" }));
      text(c, [crew, "duecrew.com"].filter(Boolean).join(" · "), P, H - P, 26, pal.mut);
      return;
    }
    const P = 78;
    await head(c, pal, look, P, P, 40);
    eyebrow(c, brow, P, 236, 30, pal);
    text(c, big, P, 396, 150, pal.ink, { weight: 700 });
    text(c, d.one ? (d.studied || time || rev ? "studied today" : "nothing yet today") : `studied, ${days}`, P, 462, 38, pal.mut);
    const w = W - 2 * P, gap = 20, s = (w - 6 * gap) / 7;
    d.days.forEach((x, i) => {
      dayCell(c, P + i * (s + gap), 560, s, x, pal, 26, 8);
      text(c, x.label, P + i * (s + gap) + s / 2, 560 + s + 54, 30, pal.mut, { weight: 700, align: "center" });
    });
    c.fillStyle = pal.line; c.fillRect(P, 812, w, 3);
    const stats = [
      rev != null && time ? [n(rev), "reviews"] : null,
      on.reviews && d.newCards != null ? [n(d.newCards), "new cards"] : null,
      streak ? [`🔥 ${streak}`, "day streak"] : null,
    ].filter(Boolean);
    stats.forEach(([v, l], i) => {
      const x = P + (i * w) / 3;
      text(c, v, x, 912, 64, pal.ink, { weight: 700 });
      text(c, l, x, 962, 32, pal.mut);
    });
    if (crew) text(c, crew, P, H - P, 34, pal.mut);
    text(c, "duecrew.com", W - P, H - P, 34, pal.mut, { align: "right" });
  }
  function dayCell(c, x, y, s, d, pal, r, ring) {
    if (d.future) { c.strokeStyle = pal.g3; c.lineWidth = 3; rr(c, x + 1.5, y + 1.5, s - 3, s - 3, r); c.stroke(); return; }
    c.fillStyle = level(pal, d.lvl); rr(c, x, y, s, s, r); c.fill();
    if (d.today) { c.strokeStyle = pal.ink; c.lineWidth = ring * 0.75; rr(c, x - ring, y - ring, s + 2 * ring, s + 2 * ring, r + ring); c.stroke(); }
  }

  // ---- K2: my year in Anki ----
  async function year(c, W, H, size, d, on, pal, look) {
    const P = 72;
    await head(c, pal, look, P, P, 40);
    eyebrow(c, `My year in Anki · ${d.year}`, P, 236, 30, pal);
    text(c, `${n(d.studied)} day${d.studied === 1 ? "" : "s"}`, P, 380, 132, pal.ink, { weight: 700 });
    text(c, d.since ? `studied, since ${d.since}` : `studied in ${d.year}`, P, 446, 38, pal.mut);
    const w = W - 2 * P, cols = d.cols, gap = 4, s = (w - (cols - 1) * gap) / cols;
    d.cells.forEach((x, i) => {
      const cx = P + Math.floor(i / 7) * (s + gap), cy = 520 + (i % 7) * (s + gap);
      if (x.pre) { c.strokeStyle = pal.g3; c.lineWidth = 2; c.setLineDash([4, 3]); rr(c, cx + 1, cy + 1, s - 2, s - 2, 3); c.stroke(); c.setLineDash([]); return; }
      if (x.out) return;
      c.fillStyle = x.fut ? mix(pal.g3, pal.bg, 0.5) : level(pal, x.lvl); rr(c, cx, cy, s, s, 3); c.fill();
    });
    const top = 520 + 7 * (s + gap) + 40;
    c.fillStyle = pal.line; c.fillRect(P, top, w, 3);
    const stats = [
      on.time && d.minutes ? [`${n(Math.round(d.minutes / 60))}h`, "studied"] : null,
      on.reviews && d.reviews != null ? [n(d.reviews), "reviews"] : null,
      on.streak && d.streak ? [`${n(d.streak)} day${d.streak === 1 ? "" : "s"}`, "longest streak"] : null,
      on.best && d.best ? [n(d.best.n), `biggest day · ${d.best.day}`] : null,
    ].filter(Boolean);
    stats.forEach(([v, l], i) => {
      const x = P + (i % 2) * (w / 2), y = top + 110 + Math.floor(i / 2) * 150;
      text(c, v, x, y, 64, pal.ink, { weight: 700 });
      text(c, l, x, y + 48, 32, pal.mut);
    });
    text(c, "duecrew.com", P, H - P, 34, pal.mut);
  }

  // ---- K3: our squad's bingo ----
  async function bingo(c, W, H, size, d, on, pal, look) {
    const P = 66;
    eyebrow(c, fit(c, `${d.name} · week ${d.week}`.toUpperCase(), 560, 28, 22, 700)[0], P, P + 26, 28, pal);
    text(c, d.shout, P, P + 112, 76, pal.g, { weight: 800, track: d.shout === "BINGO" ? 6 : 0 });
    await head(c, pal, look, W - P - (30 * 910) / 76, P, 30);
    const top = 230, bot = H - 120, gap = 22, w = W - 2 * P;
    const cw = (w - 2 * gap) / 3, ch = (bot - top - 2 * gap) / 3;
    for (let i = 0; i < 9; i++) {
      const x = P + (i % 3) * (cw + gap), y = top + Math.floor(i / 3) * (ch + gap);
      if (i === 4 && !d.done[4]) { c.strokeStyle = pal.g; c.lineWidth = 8; rr(c, x + 4, y + 4, cw - 8, ch - 8, 30); c.stroke(); }
      else { c.fillStyle = d.done[i] ? pal.g : pal.g3; rr(c, x, y, cw, ch, 30); c.fill(); }
      if (d.inLine[i]) { c.strokeStyle = pal.ink; c.lineWidth = 8; rr(c, x - 9, y - 9, cw + 18, ch + 18, 38); c.stroke(); }
      text(c, d.icons[i] || "", x + cw / 2, y + ch / 2 + 4, 104, pal.ink, { align: "center", base: "middle" });
      if (d.done[i]) text(c, "✓", x + cw - 26, y + ch - 22, 40, pal.on, { weight: 800, align: "right" });
    }
    text(c, `${d.stamps} of 9 · ${d.state}`, P, H - P + 6, 32, pal.mut);
    text(c, "duecrew.com", W - P, H - P + 6, 32, pal.mut, { align: "right" });
  }

  // ---- K4: a plan, finished ----
  async function plan(c, W, H, size, d, on, pal, look) {
    const P = 78;
    await head(c, pal, look, P, P, 40);
    const cx = P + 170, cy = 420;
    c.strokeStyle = pal.g; c.lineWidth = 46; c.beginPath(); c.arc(cx, cy, 147, 0, Math.PI * 2); c.stroke();
    text(c, "✓", cx, cy + 6, 120, pal.g, { weight: 800, align: "center", base: "middle" });
    eyebrow(c, "Finished", P, 700, 32, pal);
    const lines = wrap(c, d.name, W - 2 * P, 92, 700, 3);
    lines.forEach((l, i) => text(c, l, P, 812 + i * 104, 92, pal.ink, { weight: 700 }));
    const y = 812 + (lines.length - 1) * 104 + 76;
    text(c, `${n(d.cards)} card${d.cards === 1 ? "" : "s"}${d.weeks ? ` over ${d.weeks} week${d.weeks === 1 ? "" : "s"}` : ""}`, P, y, 38, pal.mut);
    if (on.code && d.code) text(c, `Follow it: ${d.code.slice(0, 4)} ${d.code.slice(4)}`, P, H - P, 34, pal.mut);
    text(c, "duecrew.com", W - P, H - P, 34, pal.mut, { align: "right" });
  }

  const DRAW = { week, today: week, year, bingo, plan };

  /** The sheet (K5): the card, switches for each number, size and look,
   *  then Share… (the phone's own sheet) or Download. Nothing is posted. */
  function open({ kind, title, data, file, sizes, switches }) {
    const st = { size: sizes[0], look: (() => { try { return localStorage.getItem("dc-card-look") || "light"; } catch { return "light"; } })(),
      on: Object.fromEntries(switches.map((s) => [s.k, s.on !== false && !s.off])) };
    const cv = document.createElement("canvas");
    cv.className = "sc-canvas";
    let seq = 0;
    async function paint() {
      const mine = ++seq;
      const [W, H] = SIZES[st.size];
      const off = document.createElement("canvas"); off.width = W; off.height = H;
      const c = off.getContext("2d");
      const pal = LOOKS[st.look];
      c.fillStyle = pal.bg; c.fillRect(0, 0, W, H);
      await DRAW[kind](c, W, H, st.size, data, st.on, pal, st.look);
      if (mine !== seq) return;  // a later switch drew over this one
      cv.width = W; cv.height = H; cv.getContext("2d").drawImage(off, 0, 0);
      cv.style.aspectRatio = `${W} / ${H}`;
    }
    const seg = (key, opts, label) => h("div", { class: "sc-row" }, h("span", {}, label), h("span", { class: "seg" }, opts.map(([v, l]) =>
      h("button", { class: st[key] === v ? "on" : "", "aria-pressed": String(st[key] === v), onclick: (e) => {
        st[key] = v; if (key === "look") { try { localStorage.setItem("dc-card-look", v); } catch { /* fine */ } }
        e.currentTarget.parentNode.querySelectorAll("button").forEach((b) => { const me = b === e.currentTarget; b.className = me ? "on" : ""; b.setAttribute("aria-pressed", String(me)); });
        paint();
      } }, l))));
    const rows = switches.map((s) => h("label", { class: `sc-row${s.off ? " off" : ""}`, title: s.off || "" },
      h("span", {}, s.label, s.off ? h("small", { class: "muted" }, ` · ${s.off}`) : null),
      h("input", { type: "checkbox", role: "switch", ...(st.on[s.k] ? { checked: "" } : {}), ...(s.off ? { disabled: "" } : {}),
        onchange: (e) => { st.on[s.k] = e.target.checked; paint(); } })));
    const say = h("small", { class: "muted", role: "status" }, "Made here, from your own numbers. Nothing is posted or kept.");
    const blob = () => new Promise((ok) => cv.toBlob(ok, "image/png"));
    const name = () => `${file}-${st.size}.png`;
    const download = async () => {
      const b = await blob(); if (!b) return;
      const url = URL.createObjectURL(b);
      const a = h("a", { href: url, download: name() }); document.body.append(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      say.textContent = "Downloaded.";
    };
    const canShare = (() => { try { return !!navigator.canShare && navigator.canShare({ files: [new File([""], "x.png", { type: "image/png" })] }); } catch { return false; } })();
    // K8: on a computer, most chats take a pasted picture (Safari wants the promise at once)
    const canCopy = !canShare && !!(navigator.clipboard && navigator.clipboard.write && window.ClipboardItem);
    const copyPic = async () => {
      try { await navigator.clipboard.write([new ClipboardItem({ "image/png": blob() })]); say.textContent = "Copied. Paste it into a chat."; }
      catch { say.textContent = "Couldn’t copy here. Download works."; }
    };
    const share = async () => {
      const b = await blob(); if (!b) return;
      try { await navigator.share({ files: [new File([b], name(), { type: "image/png" })] }); }
      catch (err) { if (err && err.name !== "AbortError") say.textContent = "Couldn’t open sharing here. Download works."; }
    };
    const dlg = h("dialog", { class: "sc-dlg", "aria-label": title },
      h("div", { class: "sc-head" }, h("b", {}, title), h("button", { class: "linkish", "aria-label": "Close", onclick: () => dlg.close() }, "✕")),
      h("div", { class: "sc-body" }, h("div", { class: "sc-pic" }, cv),
        h("div", { class: "sc-side" }, rows,
          sizes.length > 1 ? seg("size", sizes.map((s) => [s, s === "story" ? "Story" : s === "link" ? "Link" : "Square"]), "Size") : null,
          seg("look", [["light", "Light"], ["dark", "Dark"]], "Look"),
          h("div", { class: "row" }, canShare ? h("button", { onclick: share }, "Share…") : null,
            canCopy ? h("button", { onclick: copyPic }, "Copy picture") : null,
            h("button", { class: canShare || canCopy ? "ghost" : "", onclick: download }, "Download")),
          say)));
    dlg.addEventListener("close", () => dlg.remove());
    dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });  // a click outside the sheet
    document.body.append(dlg);
    dlg.showModal();
    paint();
    return dlg;
  }

  /** A date as the cards say it: "28 Sep". */
  const short = (iso) => { const [y, m, d] = iso.split("-").map(Number); return `${d} ${MONTHS[m - 1]}`; };
  return { open, short, SIZES };
})();
