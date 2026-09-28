// 3.5, A2: a plan link's preview picture, 1200x630, the size chat apps and
// social sites show. Drawn here pixel by pixel from what the shared link
// already shows signed out (GET /plans/public): the plan's name, whose it
// is, its deck, dates and followers, its weeks as a strip (events
// outlined), and its code. No font engine and no WebAssembly: the glyphs
// and the logo come drawn from tools/og_assets.py, and the PNG is
// CompressionStream's deflate in the format's chunks.

import { ATLAS, FACES, LOGO } from "./og_assets";

export type Peek = {
  name: string; ownerName: string; line?: string; deck: string; followers: number; v?: number;
  events?: { day: string; name: string }[];
  units: { name: string; opens: string; due?: string; n?: number }[];
};

export const W = 1200;
export const H = 630;
const X0 = 80;
const X1 = W - 80;
const BG = [0xfb, 0xfb, 0xf8];
const INK = [0x2a, 0x2c, 0x28];
const MUTED = [0x6b, 0x6f, 0x68];
const GREEN = [0x2e, 0x7d, 0x32];
const PALE = [0xe9, 0xf2, 0xe9];
const EMPTY = [0xef, 0xef, 0xe8];
const WEEKS_SHOWN = 26;

type Rgb = number[];
type Glyph = { adv: number; l: number; t: number; w: number; h: number; off: number };
type Face = { ascent: number; glyphs: Map<number, Glyph> };

// ---- the assets, unpacked once per isolate ----

const bytes = (b64: string) => Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));

async function stream(data: Uint8Array, s: CompressionStream | DecompressionStream): Promise<Uint8Array> {
  const w = s.writable.getWriter();
  w.write(data);
  w.close();
  return new Uint8Array(await new Response(s.readable).arrayBuffer());
}

let assets: Promise<{ atlas: Uint8Array; logo: Uint8Array; faces: Record<keyof typeof FACES, Face> }> | null = null;

function load() {
  assets ||= (async () => {
    const [atlas, logo] = await Promise.all([stream(bytes(ATLAS), new DecompressionStream("deflate")),
      stream(bytes(LOGO.rgba), new DecompressionStream("deflate"))]);
    const faces = {} as Record<keyof typeof FACES, Face>;
    for (const [k, f] of Object.entries(FACES)) {
      faces[k as keyof typeof FACES] = { ascent: f.ascent,
        glyphs: new Map(f.glyphs.map(([cp, adv, l, t, w, h, off]) => [cp, { adv: adv / 16, l, t, w, h, off }])) };
    }
    return { atlas, logo, faces };
  })();
  return assets;
}

// ---- drawing ----

class Canvas {
  px = new Uint8Array(W * H * 3);
  constructor(bg: Rgb) {
    for (let x = 0; x < W; x++) this.px.set(bg, x * 3);
    for (let y = 1; y < H; y++) this.px.copyWithin(y * W * 3, 0, W * 3);
  }
  blend(x: number, y: number, c: Rgb, a: number) {
    if (a <= 0 || x < 0 || y < 0 || x >= W || y >= H) return;
    const i = (y * W + x) * 3;
    if (a >= 1) { this.px[i] = c[0]; this.px[i + 1] = c[1]; this.px[i + 2] = c[2]; return; }
    for (let k = 0; k < 3; k++) this.px[i + k] = Math.round(this.px[i + k] * (1 - a) + c[k] * a);
  }
  /** A rounded rectangle, its corners antialiased. */
  rrect(x: number, y: number, w: number, h: number, r: number, c: Rgb) {
    for (let j = 0; j < h; j++) {
      for (let i = 0; i < w; i++) {
        const dx = i < r ? r - i - 0.5 : i >= w - r ? i - (w - r) + 0.5 : 0;
        const dy = j < r ? r - j - 0.5 : j >= h - r ? j - (h - r) + 0.5 : 0;
        const a = dx && dy ? Math.min(1, Math.max(0, r + 0.5 - Math.hypot(dx, dy))) : 1;
        this.blend(x + i, y + j, c, a);
      }
    }
  }
}

type Assets = Awaited<ReturnType<typeof load>>;

/** Only the characters there are glyphs for; a missing one is left out. */
const drawable = (f: Face, s: string) => [...s].filter((ch) => f.glyphs.has(ch.codePointAt(0)!)).join("");
/** Worth drawing: a letter or a number survives (a name in a script with no glyphs here doesn't). */
const legible = (f: Face, s: string) => /\p{L}|\p{N}/u.test(drawable(f, s));
const width = (f: Face, s: string) => [...s].reduce((n, ch) => n + (f.glyphs.get(ch.codePointAt(0)!)?.adv ?? 0), 0);

function text(cv: Canvas, a: Assets, f: Face, s: string, x: number, base: number, c: Rgb): number {
  for (const ch of s) {
    const g = f.glyphs.get(ch.codePointAt(0)!);
    if (!g) continue;
    const gx = Math.round(x) + g.l, gy = base + g.t;
    for (let j = 0; j < g.h; j++) {
      for (let i = 0; i < g.w; i++) {
        const k = j * g.w + i;
        const b = a.atlas[g.off + (k >> 1)];
        const v = k & 1 ? b & 15 : b >> 4;
        if (v) cv.blend(gx + i, gy + j, c, v / 15);
      }
    }
    x += g.adv;
  }
  return x;
}

/** At most `lines` lines no wider than `max`, broken at spaces; the last one
 *  ends in … when there's more. */
export function wrap(f: Face, s: string, max: number, lines: number): string[] {
  const words = s.split(/\s+/).filter(Boolean);
  const out: string[] = [];
  let cur = "";
  let i = 0;
  for (; i < words.length; i++) {
    const next = cur ? `${cur} ${words[i]}` : words[i];
    if (!cur || width(f, next) <= max) { cur = next; continue; }
    if (out.length === lines - 1) break;  // the last line takes the rest, cut
    out.push(cur);
    cur = words[i];
  }
  if (i < words.length) cur = `${cur} ${words.slice(i).join(" ")}`;
  if (cur) out.push(cur);
  return out.map((l) => fit(f, l, max));
}

function fit(f: Face, s: string, max: number): string {
  if (width(f, s) <= max) return s;
  let t = [...s];
  while (t.length && width(f, `${t.join("").trimEnd()}…`) > max) t = t.slice(0, -1);
  return `${t.join("").trimEnd()}…`;
}

// ---- the plan's weeks ----

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const day = (s: string) => Date.parse(`${s}T00:00:00Z`) / 86400000;
const when = (a: string, b: string) => (a === b ? pretty(a) : `${pretty(a)} – ${pretty(b)}`);
const pretty = (s: string) => { const d = new Date(`${s}T00:00:00Z`); return `${DAYS[d.getUTCDay()]} ${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`; };

/** Each week from the plan's first Monday to its last day: its new cards and
 *  whether an event falls in it. More than WEEKS_SHOWN weeks go in pairs (or
 *  threes…), so the strip fits. */
export function weeks(p: Peek): { n: number; event: boolean }[] {
  if (!p.units.length) return [];
  const days = [...p.units.flatMap((u) => [u.opens, u.due || u.opens]), ...(p.events || []).map((e) => e.day)].map(day);
  const first = Math.min(...days), last = Math.max(...days);
  const mon = first - ((new Date(first * 86400000).getUTCDay() + 6) % 7);
  const count = Math.floor((last - mon) / 7) + 1;
  const per = Math.ceil(count / WEEKS_SHOWN);
  const out = Array.from({ length: Math.ceil(count / per) }, () => ({ n: 0, event: false }));
  const at = (d: number) => out[Math.floor(Math.floor((d - mon) / 7) / per)];
  for (const u of p.units) at(day(u.opens)).n += u.n || 0;
  for (const e of p.events || []) at(day(e.day)).event = true;
  return out;
}

const mix = (a: Rgb, b: Rgb, t: number) => a.map((x, i) => Math.round(x + (b[i] - x) * t));

// ---- the picture ----

export async function draw(p: Peek, code: string): Promise<Canvas> {
  const a = await load();
  const cv = new Canvas(BG);
  // the one-line logo, as drawn
  for (let j = 0; j < LOGO.h; j++) {
    for (let i = 0; i < LOGO.w; i++) {
      const k = (j * LOGO.w + i) * 4;
      cv.blend(X0 + i, 64 + j, [a.logo[k], a.logo[k + 1], a.logo[k + 2]], a.logo[k + 3] / 255);
    }
  }
  const { title, text: body, strong } = a.faces;
  const name = legible(title, p.name) ? p.name : "A study plan";
  const lines = wrap(title, name, X1 - X0, 2);
  let y = 200;
  for (const l of lines) { text(cv, a, title, l, X0, y, INK); y += 74; }
  y += -74 + 58;
  const us = p.units;
  const lastDay = us.length ? us.reduce((m, u) => ((u.due || u.opens) > m ? u.due || u.opens : m), us[0].opens) : "";
  const whose = [legible(body, p.ownerName) ? `${p.ownerName}'s plan` : "A plan", legible(body, p.deck) ? p.deck : null].filter(Boolean).join(" · ");
  text(cv, a, body, fit(body, whose, X1 - X0), X0, y, MUTED);
  y += 44;
  const span = us.length ? `${us.length} date${us.length === 1 ? "" : "s"}, ${when(us[0].opens, lastDay)}` : "No dates yet";
  text(cv, a, body, fit(body, `${span} · ${p.followers.toLocaleString("en-US")} following`, X1 - X0), X0, y, MUTED);
  // the weeks: darker with more new cards; an event's week outlined
  const ws = weeks(p);
  if (ws.length) {
    const top = Math.max(1, ...ws.map((w) => w.n));
    const gap = ws.length > 16 ? 6 : 10;
    const cell = Math.floor((X1 - X0 - gap * (ws.length - 1)) / ws.length);
    const sy = 452, sh = 48;
    ws.forEach((w, i) => {
      const x = X0 + i * (cell + gap);
      const fill = w.n ? mix(PALE, GREEN, 0.25 + 0.75 * (w.n / top)) : EMPTY;
      if (w.event) { cv.rrect(x, sy, cell, sh, 7, INK); cv.rrect(x + 4, sy + 4, cell - 8, sh - 8, 4, fill); }
      else cv.rrect(x, sy, cell, sh, 7, fill);
    });
  }
  // the code, to type into Anki
  const spaced = `${code.slice(0, 4)} ${code.slice(4)}`;
  const cw = width(strong, spaced);
  text(cv, a, strong, spaced, X1 - cw, 574, INK);
  const lw = width(body, "Code  ");
  text(cv, a, body, "Code", X1 - cw - lw, 574, MUTED);
  text(cv, a, body, "Follow it in Anki", X0, 574, MUTED);
  return cv;
}

/** 3.4.1: an invite link's picture: who invited you, and what to. */
export async function drawInvite(name: string): Promise<Canvas> {
  const a = await load();
  const cv = new Canvas(BG);
  for (let j = 0; j < LOGO.h; j++) {
    for (let i = 0; i < LOGO.w; i++) {
      const k = (j * LOGO.w + i) * 4;
      cv.blend(X0 + i, 64 + j, [a.logo[k], a.logo[k + 1], a.logo[k + 2]], a.logo[k + 3] / 255);
    }
  }
  const { title, text: body } = a.faces;
  const head = legible(title, name) ? `${name} invited you` : "You're invited";
  let y = 260;
  for (const l of wrap(title, head, X1 - X0, 2)) { text(cv, a, title, l, X0, y, INK); y += 74; }
  text(cv, a, body, "to study together in Anki", X0, y - 74 + 62, MUTED);
  text(cv, a, body, "Due Crew · a free Anki add-on", X0, 574, MUTED);
  return cv;
}

// ---- PNG ----

const CRC = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; }
  return t;
})();

function chunk(type: string, data: Uint8Array): Uint8Array {
  const out = new Uint8Array(12 + data.length);
  const dv = new DataView(out.buffer);
  dv.setUint32(0, data.length);
  for (let i = 0; i < 4; i++) out[4 + i] = type.charCodeAt(i);
  out.set(data, 8);
  let c = 0xffffffff;
  for (let i = 4; i < 8 + data.length; i++) c = CRC[(c ^ out[i]) & 255] ^ (c >>> 8);
  dv.setUint32(8 + data.length, (c ^ 0xffffffff) >>> 0);
  return out;
}

export async function png(cv: Canvas): Promise<Uint8Array> {
  const raw = new Uint8Array(H * (W * 3 + 1));  // each row: filter 0, then its pixels
  for (let y = 0; y < H; y++) raw.set(cv.px.subarray(y * W * 3, (y + 1) * W * 3), y * (W * 3 + 1) + 1);
  const ihdr = new Uint8Array(13);
  const dv = new DataView(ihdr.buffer);
  dv.setUint32(0, W); dv.setUint32(4, H);
  ihdr.set([8, 2, 0, 0, 0], 8);  // 8-bit RGB
  const parts = [new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]), chunk("IHDR", ihdr),
    chunk("IDAT", await stream(raw, new CompressionStream("deflate"))), chunk("IEND", new Uint8Array())];
  const out = new Uint8Array(parts.reduce((n, x) => n + x.length, 0));
  let o = 0;
  for (const x of parts) { out.set(x, o); o += x.length; }
  return out;
}

/** The description a link preview shows under the plan's name. */
export function describe(p: Peek): string {
  const us = p.units;
  const lastDay = us.length ? us.reduce((m, u) => ((u.due || u.opens) > m ? u.due || u.opens : m), us[0].opens) : "";
  const span = us.length ? `${us.length} date${us.length === 1 ? "" : "s"}, ${when(us[0].opens, lastDay)}` : "no dates yet";
  return [p.line || null, `${p.ownerName}'s plan for ${p.deck}: ${span}, ${p.followers.toLocaleString("en-US")} following.`,
    "Follow it in Anki."].filter(Boolean).join(" ");
}
