// 3.6: squad bingo. Every squad plays the same 3×3 card each week: eight
// squares about studying (one from each family: 3 easy, 3 medium, 2 hard,
// four of them team squares) around a middle the squad unlocks together.
// The server draws the card once from the pool, which the admin edits, and
// keeps it, so every board plays the same card and an edit shows from the
// next draw. It never works out a square: each add-on sends `play` on its
// squad rows (validate.play), and boards add the rows up (`evaluate`, which
// the add-on restates in bingo.py). The daily cron keeps counts per square
// for the admin, to tune the pool with.

import type { Session } from "./auth";
import { isAdmin } from "./notices";
import * as V from "./validate";
import { Env, HttpError, json, nowSec, readJson } from "./util";

export const FAMILIES = ["early", "spread", "focus", "volume", "fresh", "often", "clean", "wild"] as const;
const DIFFS = ["e", "m", "h"] as const;
const GROUPS = ["study", "crew", "free", "season"] as const;
/** What a member's play may carry; a middle's rule reads one of these. */
export const PLAY_KEYS = ["s", "d", "e8", "n10", "z", "ch", "rm", "lv", "aq", "tp", "dk", "st"] as const;
/** A team square's need, or a middle's goal, as a share of the squad:
 *  never fewer than 2 of you (1 in a squad of one), never more than there
 *  are. A bigger squad needs more of you. */
export const SHARES = { half: 1 / 2, third: 1 / 3, quarter: 1 / 4 } as const;
type Share = keyof typeof SHARES;
const CARDS_SHOWN = 6;       // the admin's page: this week's card and the last few
const STATS_ROWS_MAX = 50000;

type Obj = Record<string, unknown>;
export type Square = { id: string; fam: string; diff: string; icon: string; title: string; rule: string; detail: string;
  type: string; params: Obj; team: boolean; need?: number | Share };
export type Middle = { id: string; group: string; icon: string; name: string; rule: string; detail: string;
  type: string; params: Obj; goal: number | "all" | Share; unit: string; season?: { from: string; to: string } };
export type Card = { wk: string; squares: Square[]; middle: Middle };

// ---- the pool: what an entry may say ----

const int = (lo: number, hi: number) => (x: unknown) => V.isInt(x, lo, hi);
const dows = (x: unknown) => Array.isArray(x) && x.length >= 1 && x.length <= 7 && x.every((d) => V.isInt(d, 0, 6));
const hm = (x: unknown) => Array.isArray(x) && x.length >= 1 && x.length <= 4
  && x.every((t) => typeof t === "string" && /^([01]\d|2[0-3]):[0-5]\d$/.test(t));
const parts = (x: unknown) => Array.isArray(x) && x.length >= 2 && x.length <= 3
  && x.every((p) => Array.isArray(p) && p.length === 2 && V.isInt(p[0], 0, 23) && V.isInt(p[1], 1, 24) && p[0] < p[1]);
const bool = (x: unknown) => typeof x === "boolean";
const ratio = (x: unknown) => typeof x === "number" && x >= 1 && x <= 3 && Math.round(x * 10) === x * 10;
const playKey = (x: unknown) => (PLAY_KEYS as readonly unknown[]).includes(x) && x !== "s";

/** Each rule type the add-on knows, with its numbers: [required, optional]. */
const SQUARE_TYPES: Record<string, [Record<string, (x: unknown) => boolean>, Record<string, (x: unknown) => boolean>]> = {
  // row: the days must be in a row (a streak), not just that many this week
  window: [{ from: int(0, 23), to: int(1, 24), days: int(1, 7) }, { dow: dows, row: bool }],
  minute: [{ hm }, {}],
  sittings: [{ n: int(2, 8), gap: int(15, 240) }, {}],
  parts: [{ parts, days: int(1, 7) }, { row: bool }],
  focus: [{ minutes: int(5, 180), gap: int(1, 30) }, { days: int(1, 7), row: bool }],
  beat: [{ run: int(1, 7) }, {}],
  rel: [{ x: ratio }, { days: int(1, 7), row: bool }],  // days: that many days at x times my usual
  best: [{ days: int(7, 90) }, {}],
  newdays: [{ days: int(1, 7) }, { row: bool }],
  newdone: [{ days: int(1, 7) }, { row: bool }],
  days: [{ days: int(1, 7) }, { dow: dows, row: bool }],
  zero: [{ days: int(1, 7) }, { row: bool }],
  samehour: [{ run: int(2, 7) }, {}],
};
const MIDDLE_TYPES: typeof SQUARE_TYPES = {
  people: [{ key: playKey }, {}],
  sum: [{ key: playKey }, {}],
  day: [{ key: playKey }, { day: int(0, 6) }],
  emoji: [{}, {}],
  joined: [{}, {}],
  free: [{}, {}],
};

function checkParams(types: typeof SQUARE_TYPES, type: unknown, params: unknown): Obj {
  if (typeof type !== "string" || !(type in types) || !V.isObj(params)) throw V.bad("rule");
  const [req, opt] = types[type];
  for (const k of Object.keys(params)) if (!(k in req) && !(k in opt)) throw V.bad("rule");
  for (const [k, ok] of Object.entries(req)) if (!ok(params[k])) throw V.bad("rule");
  for (const [k, ok] of Object.entries(opt)) if (k in params && !ok(params[k])) throw V.bad("rule");
  return params;
}

const words = (v: unknown, max: number, what: string) => {
  if (!V.isStr(v, max * 2, 1)) throw V.bad(what);
  const t = V.oneLine(v, max);
  if (!t) throw V.bad(what);
  return t;
};
const icon = (v: unknown) => {
  if (!V.isEmoji(v)) throw V.bad("icon");
  return v;
};
const mmdd = (v: unknown) => typeof v === "string" && /^(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/.test(v);

/** An entry as the admin may save it. Throws 400 on anything else. */
export function entry(kind: unknown, v: unknown): Obj {
  if (!V.isObj(v)) throw V.bad("entry");
  if (kind === "square") {
    const known = ["fam", "diff", "icon", "title", "rule", "detail", "type", "params", "team"];
    for (const k of Object.keys(v)) if (!known.includes(k)) throw V.bad("entry");
    if (!(FAMILIES as readonly unknown[]).includes(v.fam) || !(DIFFS as readonly unknown[]).includes(v.diff)) throw V.bad("entry");
    if (typeof v.team !== "boolean") throw V.bad("entry");
    return { fam: v.fam, diff: v.diff, icon: icon(v.icon), title: words(v.title, 28, "title"), rule: words(v.rule, 48, "rule"),
             detail: words(v.detail, 160, "detail"), type: v.type, params: checkParams(SQUARE_TYPES, v.type, v.params), team: v.team };
  }
  if (kind === "middle") {
    const known = ["group", "icon", "name", "rule", "detail", "type", "params", "goal", "unit", "season"];
    for (const k of Object.keys(v)) if (!known.includes(k)) throw V.bad("entry");
    if (!(GROUPS as readonly unknown[]).includes(v.group)) throw V.bad("entry");
    if (!(V.isInt(v.goal, 1, 500) || v.goal === "all" || (typeof v.goal === "string" && v.goal in SHARES))) throw V.bad("goal");
    const out: Obj = { group: v.group, icon: icon(v.icon), name: words(v.name, 28, "name"), rule: words(v.rule, 48, "rule"),
                       detail: words(v.detail, 160, "detail"), type: v.type, params: checkParams(MIDDLE_TYPES, v.type, v.params),
                       goal: v.goal, unit: V.isStr(v.unit, 20) ? V.oneLine(v.unit, 20) : "" };
    if (v.group === "season") {
      const s = v.season;
      if (!V.isObj(s) || !mmdd(s.from) || !mmdd(s.to)) throw V.bad("season");
      out.season = { from: s.from, to: s.to };
    } else if (v.season !== undefined) throw V.bad("season");
    return out;
  }
  throw V.bad("kind");
}

// ---- weeks ----

const WK = /^(\d{4})-W(\d{2})$/;

/** The ISO week a date is in, as "2026-W40". */
export function isoWeek(d: Date): string {
  const t = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()));
  const dow = (t.getUTCDay() + 6) % 7;
  t.setUTCDate(t.getUTCDate() - dow + 3);  // that week's Thursday names it
  const y = t.getUTCFullYear();
  const jan4 = new Date(Date.UTC(y, 0, 4));
  const w = 1 + Math.round(((t.getTime() - jan4.getTime()) / 86400000 - 3 + ((jan4.getUTCDay() + 6) % 7)) / 7);
  return `${y}-W${String(w).padStart(2, "0")}`;
}

/** The Monday of an ISO week (UTC midnight). */
export function mondayOf(wk: string): Date {
  const m = WK.exec(wk)!;
  const y = Number(m[1]), w = Number(m[2]);
  const jan4 = new Date(Date.UTC(y, 0, 4));
  return new Date(Date.UTC(y, 0, 4 - ((jan4.getUTCDay() + 6) % 7) + (w - 1) * 7));
}

export const wkNum = (wk: string) => Number(wk.slice(0, 4)) * 100 + Number(wk.slice(6));

/** A week a client may ask for: last week, this one or next (someone's
 *  Monday can come a day early or late). Nothing further, so nobody
 *  freezes a far week's card from today's pool. */
export function askable(wk: unknown, now = new Date()): wk is string {
  if (typeof wk !== "string" || !WK.exec(wk)) return false;
  return [-8, 0, 8].some((d) => isoWeek(new Date(now.getTime() + d * 86400000)) === wk);
}

// ---- the draw ----

function rng(seed: string) {
  let h = 2166136261;
  for (const ch of seed) { h ^= ch.charCodeAt(0); h = Math.imul(h, 16777619); }
  return () => {
    h = (h + 0x6D2B79F5) | 0;
    let t = h;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
function shuffle<T>(a: T[], r: () => number): T[] {
  a = a.slice();
  for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(r() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; }
  return a;
}

/** A yearly window (mm-dd to mm-dd, across New Year too) that holds any day of the week. */
function inSeason(season: { from: string; to: string }, monday: Date): boolean {
  for (let i = 0; i < 7; i++) {
    const d = new Date(monday.getTime() + i * 86400000).toISOString().slice(5, 10);
    if (season.from <= season.to ? (d >= season.from && d <= season.to) : (d >= season.from || d <= season.to)) return true;
  }
  return false;
}

/** Pure: the week's card from the enabled pool. The same week and pool
 *  always draw the same card. */
/** A square that wants days in a row (3.6.1): `row`, or a run of 2+. */
export const isStreak = (s: Square) => s.params?.row === true || (typeof s.params?.run === "number" && (s.params.run as number) >= 2);

export function draw(wk: string, squares: Square[], middles: Middle[]): Card {
  const r = rng(wk);
  // 3 easy, 3 medium, 2 hard, dealt across the families
  const diffs = shuffle(["e", "e", "e", "m", "m", "m", "h", "h"], r);
  const picks: Square[] = [];
  FAMILIES.forEach((f, k) => {
    const fam = squares.filter((s) => s.fam === f);
    if (!fam.length) return;
    const want = fam.filter((s) => s.diff === diffs[k]);
    // a medium or hard square is a streak when the family has one
    const streaks = want.filter(isStreak);
    const from = streaks.length ? streaks : want.length ? want : fam;
    picks.push({ ...from[Math.floor(r() * from.length)] });
  });
  const card = shuffle(picks, r);
  // team squares: all but one. The easier the square, the more of you it
  // takes (easy: half, medium: a third); one hard square takes a quarter,
  // and the other stays one person's
  const hard = shuffle(card.map((_, i) => i).filter((i) => card[i].diff === "h" && card[i].team), r);
  card.forEach((s, i) => {
    s.need = !s.team ? 1 : s.diff === "e" ? "half" : s.diff === "m" ? "third" : hard[0] === i && card.filter((q) => q.diff === "h").length > 1 ? "quarter" : 1;
  });
  // the middle: a season's first; every sixth week free; else study and crew weeks take turns
  const n = Number(wk.slice(6));
  const season = middles.filter((m) => m.group === "season" && m.season && inSeason(m.season, mondayOf(wk)));
  const free = middles.filter((m) => m.group === "free");
  const turn = middles.filter((m) => m.group === (n % 2 ? "study" : "crew"));
  const pool = season.length ? season : n % 6 === 0 && free.length ? free : turn.length ? turn : middles;
  const middle = pool.length ? pool[Math.floor(r() * pool.length)]
    : { id: "coffee", group: "free", icon: "☕", name: "Coffee week", rule: "Free.", detail: "", type: "free", params: {}, goal: 1, unit: "" } as Middle;
  return { wk, squares: card, middle: { ...middle } };
}

async function loadPool(env: Env): Promise<{ squares: Square[]; middles: Middle[] }> {
  const rows = await env.DB.prepare("SELECT id, kind, json FROM bingo_pool WHERE enabled = 1 ORDER BY id").all<{ id: string; kind: string; json: string }>();
  const squares: Square[] = [], middles: Middle[] = [];
  for (const r of rows.results) {
    const e = { id: r.id, ...JSON.parse(r.json) };
    (r.kind === "square" ? squares : middles).push(e);
  }
  return { squares, middles };
}

/** The week's card: drawn the first time anyone asks, then kept. */
export async function cardFor(env: Env, wk: string): Promise<Card> {
  const have = await env.DB.prepare("SELECT json FROM bingo_cards WHERE wk = ?").bind(wk).first<string>("json");
  if (have) return JSON.parse(have);
  const { squares, middles } = await loadPool(env);
  const card = draw(wk, squares, middles);
  await env.DB.prepare("INSERT INTO bingo_cards (wk, json, created_at) VALUES (?, ?, ?) ON CONFLICT DO NOTHING")
    .bind(wk, JSON.stringify(card), nowSec()).run();
  // two first askers at once: whichever was kept is the card
  return JSON.parse((await env.DB.prepare("SELECT json FROM bingo_cards WHERE wk = ?").bind(wk).first<string>("json"))!);
}

/** For GET /board and a squad: the card, when I'm in a squad (or on a plan's team) and asked for a week I may. */
export async function forMember(env: Env, uid: string, wk: unknown): Promise<Card | undefined> {
  if (!askable(wk)) return undefined;
  // 3.7.3: a plan's team plays the week's squares too
  const any = await env.DB.prepare("SELECT 1 FROM members WHERE uid = ?1 UNION ALL SELECT 1 FROM plan_team WHERE uid = ?1 LIMIT 1").bind(uid).first();
  return any ? cardFor(env, wk) : undefined;
}

// ---- a squad's card, from its rows (bingo.py restates this) ----

export type Row = { uid: string; emoji: string | null; day: string | null; joined: string; play: Obj | null };
export const CELLS = [0, 1, 2, 3, 5, 6, 7, 8];  // the squares' places around the middle (4)
export const LINES = [[0, 1, 2], [3, 4, 5], [6, 7, 8], [0, 3, 6], [1, 4, 7], [2, 5, 8], [0, 4, 8], [2, 4, 6]];

/** Whose play counts this week, who's active, and what each square and
 *  the middle stand at. Active: an add-on that plays (it has sent play;
 *  an older one never does, and can't be counted on), which played this
 *  week or studied since last week's Monday. A share (half, a third, a
 *  quarter) is of the active, at least 2 (howMany); a need is never more
 *  than the active count, so a small squad, or one still updating, can
 *  fill its card. */
/** How many of you a need or a goal means, with this many active. Numbers
 *  from before 3.6.1's cards are taken as they are, never more than there are. */
export function howMany(need: number | Share | "all", count: number): number {
  if (need === "all") return count;
  if (typeof need === "string") return count <= 1 ? 1 : Math.min(count, Math.max(2, Math.ceil(SHARES[need] * count)));
  return Math.min(need, count);
}

export function evaluate(card: Card, rows: Row[]) {
  const n = wkNum(card.wk);
  const monday = mondayOf(card.wk).toISOString().slice(0, 10);
  const since = new Date(mondayOf(card.wk).getTime() - 7 * 86400000).toISOString().slice(0, 10);
  const play = (r: Row) => (r.play && r.play.wk === n ? r.play : null);
  const active = rows.filter((r) => play(r) || (r.play && r.day && r.day >= since));
  const older = rows.filter((r) => !r.play && r.day && r.day >= since).length;  // studying, on an add-on that can't play
  // a share is of everyone studying, older add-ons too: a squad of 3 where
  // two haven't updated still needs 2 of you, not 1
  const count = Math.max(1, active.length + older);
  const cap = (need: number | Share | "all") => howMany(need, count);
  const squares = card.squares.map((s, i) => {
    const who = rows.filter((r) => ((play(r)?.s as number) ?? 0) & (1 << i)).map((r) => r.uid);
    const need = cap(s.need ?? 1);
    return { who, need, done: who.length >= need };
  });
  const m = card.middle, key = String(m.params?.key ?? "");
  const val = (r: Row) => Number(play(r)?.[key] ?? 0);
  let have = 0;
  if (m.type === "free") have = 1;
  else if (m.type === "people") have = rows.filter((r) => val(r) > 0).length;
  else if (m.type === "sum") have = rows.reduce((a, r) => a + val(r), 0);
  else if (m.type === "day") {
    const days = typeof m.params.day === "number" ? [m.params.day as number] : [0, 1, 2, 3, 4, 5, 6];
    have = Math.max(...days.map((d) => rows.filter((r) => val(r) & (1 << d)).length));
  } else if (m.type === "emoji") have = rows.filter((r) => r.emoji && (play(r) || (r.day && r.day >= since))).length;
  else if (m.type === "joined") have = rows.filter((r) => r.joined >= monday).length;
  const goal = m.type === "free" ? 1 : m.type === "sum" && typeof m.goal === "number" ? m.goal : cap(m.goal);
  const middle = { have: Math.min(have, goal), goal, done: have >= goal };
  const cell = (c: number) => (c === 4 ? middle.done : squares[CELLS.indexOf(c)]?.done ?? false);
  const lines = LINES.filter((l) => l.every(cell)).length;
  return { active: active.length, players: rows.filter(play).length, older, squares, middle, lines };
}

/** The fewest cells left for a line: their names, closest first (bingo.py closest). */
export function closest(card: Card, ev: ReturnType<typeof evaluate>): string[] {
  const done = (c: number) => (c === 4 ? ev.middle.done : ev.squares[CELLS.indexOf(c)].done);
  let best = LINES[0];
  for (const l of LINES) if (l.filter((c) => !done(c)).length < best.filter((c) => !done(c)).length) best = l;
  return best.filter((c) => !done(c)).map((c) => (c === 4 ? card.middle.name : card.squares[CELLS.indexOf(c)].title));
}

// ---- the daily counts, for tuning the pool ----

/** For this week's and last week's cards: how many people played, and per
 *  square how many stamped it and in how many squads it was done; the
 *  middle, lines and whole cards by squad. Counts only. */
export async function keepStats(env: Env, now = new Date()): Promise<void> {
  for (const wk of [isoWeek(now), isoWeek(new Date(now.getTime() - 7 * 86400000))]) {
    const json = await env.DB.prepare("SELECT json FROM bingo_cards WHERE wk = ?").bind(wk).first<string>("json");
    if (!json) continue;
    const card = JSON.parse(json) as Card;
    const like = `%"wk":${wkNum(wk)}%`;
    const rows = await env.DB.prepare(
      `SELECT squad, uid, emoji, day, joined_at, play FROM members
        WHERE squad IN (SELECT DISTINCT squad FROM members WHERE play LIKE ?) LIMIT ?`,
    ).bind(like, STATS_ROWS_MAX).all<{ squad: string; uid: string; emoji: string | null; day: string | null; joined_at: number; play: string | null }>();
    const bySquad = new Map<string, Row[]>();
    for (const r of rows.results) {
      const list = bySquad.get(r.squad) ?? [];
      list.push({ uid: r.uid, emoji: r.emoji, day: r.day, joined: new Date(r.joined_at * 1000).toISOString().slice(0, 10),
                  play: r.play ? JSON.parse(r.play) : null });
      bySquad.set(r.squad, list);
    }
    const out = { at: nowSec(), players: 0, squads: 0, squares: card.squares.map(() => ({ people: 0, squads: 0 })),
                  middle: 0, lines: 0, whole: 0 };
    for (const list of bySquad.values()) {
      const e = evaluate(card, list);
      if (!e.players) continue;
      out.players += e.players;
      out.squads += 1;
      e.squares.forEach((s, i) => { out.squares[i].people += s.who.length; out.squares[i].squads += s.done ? 1 : 0; });
      out.middle += e.middle.done ? 1 : 0;
      out.lines += e.lines ? 1 : 0;
      out.whole += e.lines === LINES.length ? 1 : 0;
    }
    await env.DB.prepare("UPDATE bingo_cards SET stats = ? WHERE wk = ?").bind(JSON.stringify(out), wk).run();
  }
}

// ---- the admin's table ----

function adminOnly(env: Env, s: Session) {
  if (!isAdmin(env, s.uid)) throw new HttpError(404, "not_found");
}

/** GET /admin/bingo: the whole pool (off ones too), this week's card and
 *  the last few with their counts. */
export async function adminGet(s: Session, env: Env): Promise<Response> {
  adminOnly(env, s);
  const wk = isoWeek(new Date());
  await cardFor(env, wk);  // so the page always has this week's
  const [pool, cards] = await env.DB.batch<any>([
    env.DB.prepare("SELECT id, kind, json, enabled, updated_at FROM bingo_pool ORDER BY kind DESC, id"),
    env.DB.prepare("SELECT wk, json, stats FROM bingo_cards ORDER BY wk DESC LIMIT ?").bind(CARDS_SHOWN),
  ]);
  return json({
    week: wk,
    pool: pool.results.map((r: any) => ({ id: r.id, kind: r.kind, enabled: r.enabled === 1, updatedAt: r.updated_at, entry: JSON.parse(r.json) })),
    cards: cards.results.map((r: any) => ({ wk: r.wk, card: JSON.parse(r.json), stats: r.stats ? JSON.parse(r.stats) : null })),
  });
}

/** PUT /admin/bingo/{id} {kind, entry, enabled}: add or change an entry.
 *  Cards already drawn keep what they were drawn with. */
export async function adminPut(req: Request, s: Session, env: Env, [id]: string[]): Promise<Response> {
  adminOnly(env, s);
  if (!/^[a-z0-9]{1,12}$/.test(id)) throw V.bad("id");
  const body = await readJson(req);
  for (const k of Object.keys(body)) if (!["kind", "entry", "enabled"].includes(k)) throw V.bad("entry");
  if (typeof body.enabled !== "boolean") throw V.bad("enabled");
  const e = entry(body.kind, body.entry);
  const was = await env.DB.prepare("SELECT kind FROM bingo_pool WHERE id = ?").bind(id).first<string>("kind");
  if (was && was !== body.kind) throw new HttpError(409, "kind");
  await env.DB.prepare(
    `INSERT INTO bingo_pool (id, kind, json, enabled, updated_at) VALUES (?, ?, ?, ?, ?)
     ON CONFLICT(id) DO UPDATE SET json = excluded.json, enabled = excluded.enabled, updated_at = excluded.updated_at`,
  ).bind(id, body.kind, JSON.stringify(e), body.enabled ? 1 : 0, nowSec()).run();
  return json({ id, kind: body.kind, enabled: body.enabled, entry: e });
}
