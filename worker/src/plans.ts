// Plans (3.1): a list of dates for one shared deck, made by its author and
// followed by anyone with its code (or, for a squad plan, the squad). A
// follower's add-on unsuspends each date's cards on the morning it opens;
// the server only holds names, counts, note guids with card numbers, dates
// and progress counts. Never card text. See docs/plans-design.md.

import type { Session } from "./auth";
import { limitOrThrow } from "./limits";
import { SQUAD_ALPHABET, normalizeCode } from "./squads";
import * as V from "./validate";
import { Env, HttpError, clientIp, json, nowSec, readJson } from "./util";

export const PLAN_CODE_LEN = 8;
const UNITS_MAX = 200;
const EVENTS_MAX = 200;  // F1: named days (a lecture, a quiz, the exam) the dates prep for
const CARDS_MAX = 50000;  // 3.3: a class lead's own lecture tags, for a year
const IDS_MAX = 50000;    // 3.3, C5: note ids kept behind a plan's tags and subdecks
const SEARCH_MAX = 10;
const IDLIST_MAX = 5000;  // E1: note or card ids pasted onto one date
const SEARCH_LEN = 500;
const REVIEWS_MAX = 60;
export const PLAN_BODY_MAX = 1600 * 1024;
const SOURCES_MAX = 50;
const PATH_MAX = 200;
const COVER_MAX = 500;
const DOC_MAX = 1536 * 1024;  // 3.3: 50,000 cards; one D1 row holds 2 MB
const TREE_MAX = 5000;
const NEST_MAX = 100000;  // names in a nested tree; the body's size binds first
const TREE_BODY_MAX = 1536 * 1024;  // a big deck's tags, nested; one D1 row holds 2 MB
const NEST_DEPTH = 20;
const LINE_MAX = 120;
const SUMMARY_MAX = 120;
const LOG_KEEP = 30;
const EDITORS_MAX = 10;
const NOTES_MAX = 500;
const NOTE_TEXT_MAX = 280;
export const FOLLOWS_MAX = 20;
const TREES_MAX = 20;
export const PLANS_MAX = 50;
const UNIT_ID = /^[a-z0-9]{1,12}$/;

type Obj = Record<string, unknown>;
export type Plan = { id: string; code: string; owner: string; name: string; line: string; audience: string;
  squad: string | null; doc: string; version: number; updated_at: number;
  listed?: number; listed_note?: string | null; lib?: string | null; based_on?: string | null };

export function draw(n: number): string {
  const bytes = crypto.getRandomValues(new Uint8Array(n));
  return [...bytes].map((b) => SQUAD_ALPHABET[b % 32]).join("");
}

const newUnitId = () => draw(8).toLowerCase().replace(/[^a-z0-9]/g, "x");

// ---- shapes ----

function path(v: unknown): string {
  if (!V.isStr(v, PATH_MAX, 1) || /[\u0000-\u001f]/.test(v)) throw V.bad("plan");
  return v;
}

/** A date's new cards as far as the server knows: its tags' and subdecks'
 *  count, single cards, what its searches and pasted ids found. */
export function unitCount(u: Obj): number {
  return ((u.n as number) || 0) + ((u.cards as unknown[]) || []).length
    + Object.values((u.sn as Record<string, number>) || {}).reduce((a, x) => a + x, 0)
    + ((u.idn as number | undefined) ?? (((u.nids as unknown[]) || []).length + ((u.cids as unknown[]) || []).length));
}

function cardRef(v: unknown): [string, number] {
  if (!Array.isArray(v) || v.length !== 2 || !V.isStr(v[0], V.GUID_MAX, 1) || !V.isInt(v[1], 0, 1000)) throw V.bad("plan");
  return [v[0], v[1]];
}

function unit(v: unknown): Obj {
  if (!V.isObj(v)) throw V.bad("plan");
  for (const k of Object.keys(v)) if (!["id", "name", "opens", "due", "lead", "check", "tags", "decks", "cards", "n", "even", "search", "sn", "ids", "nids", "cids", "idn", "for"].includes(k)) throw V.bad("plan");
  if (!V.isStr(v.id, 12) || !UNIT_ID.test(v.id)) throw V.bad("plan");
  if (!V.isDate(v.opens)) throw V.bad("plan");
  const out: Obj = { id: v.id, name: V.displayName(v.name), opens: v.opens };
  if (v.due !== undefined && v.due !== null) {
    if (!V.isDate(v.due) || v.due < v.opens) throw V.bad("plan");
    out.due = v.due;
  }
  if (v.even !== undefined && v.even !== null && v.even !== false) {
    // 3.3: split evenly over its days, the same slices for everyone (needs a due date after it opens)
    if (v.even !== true || !out.due || out.due === out.opens) throw V.bad("plan");
    out.even = true;
  }
  if (v.check !== undefined && v.check !== null) {
    // 3.2: a checkpoint, the morning a filtered deck of this date's cards is built
    if (!V.isDate(v.check) || v.check < v.opens) throw V.bad("plan");
    out.check = v.check;
  }
  if (v.lead !== undefined && v.lead !== null) {  // 3.1 docs only; the builder no longer writes it
    if (!V.isStr(v.lead, 128, 1)) throw V.bad("plan");
    out.lead = v.lead;
  }
  if (v.n !== undefined && v.n !== null) {
    // how many cards the tags and subdecks hold in the author's copy, so a
    // follower sees "204 of 212"; a number, never which cards
    if (!V.isInt(v.n, 0, 1_000_000)) throw V.bad("plan");
    out.n = v.n;
  }
  for (const k of ["tags", "decks"] as const) {
    const x = v[k] ?? [];
    if (!Array.isArray(x) || x.length > SOURCES_MAX) throw V.bad("plan");
    out[k] = [...new Set(x.map(path))];
  }
  // 3.3, C3: Anki searches, run by each follower's Anki inside the plan's deck
  const search = v.search ?? [];
  if (!Array.isArray(search) || search.length > SEARCH_MAX
      || !search.every((q) => V.isStr(q, SEARCH_LEN, 1) && !/[\u0000-\u001f]/.test(q as string))) throw V.bad("plan");
  if (search.length) out.search = [...new Set(search as string[])];
  if (v.sn !== undefined && v.sn !== null) {
    // how many cards each search found in the author's Anki, when it was added there
    if (!V.isObj(v.sn) || Object.keys(v.sn).length > SEARCH_MAX
        || !Object.entries(v.sn).every(([q, n]) => (out.search as string[] | undefined)?.includes(q) && V.isInt(n, 0, 1_000_000))) throw V.bad("plan");
    if (Object.keys(v.sn).length) out.sn = v.sn;
  }
  if (v.ids !== undefined && v.ids !== null) {
    // 3.3, C5: the note ids behind its tags and subdecks in the author's Anki
    if (!Array.isArray(v.ids) || v.ids.length > IDS_MAX || !v.ids.every((g) => V.isStr(g, V.GUID_MAX, 1))) throw V.bad("plan");
    if (v.ids.length) out.ids = [...new Set(v.ids as string[])];
  }
  const cards = v.cards ?? [];
  if (!Array.isArray(cards)) throw V.bad("plan");
  const seen = new Set<string>();
  out.cards = cards.map(cardRef).filter(([g, o]) => !seen.has(`${g}:${o}`) && seen.add(`${g}:${o}`));
  // E1: note ids and card ids pasted onto the date, run in each follower's
  // Anki inside the plan's deck; numbers only, and `idn` how many cards they
  // found in the author's Anki
  for (const k of ["nids", "cids"]) {
    const a = v[k];
    if (a === undefined || a === null) continue;
    if (!Array.isArray(a) || a.length > IDLIST_MAX || !a.every((x) => Number.isSafeInteger(x) && (x as number) > 0)) throw V.bad("plan");
    if (a.length) out[k] = [...new Set(a as number[])];
  }
  // F1: the event this date preps for, by its id
  if (v.for !== undefined && v.for !== null) {
    if (!V.isStr(v.for, 12) || !UNIT_ID.test(v.for)) throw V.bad("plan");
    out.for = v.for;
  }
  if (v.idn !== undefined && v.idn !== null) {
    if (!V.isInt(v.idn, 0, 1_000_000)) throw V.bad("plan");
    if (out.nids || out.cids) out.idn = v.idn;
  }
  return out;
}

/** 3.2: the plan's shape over time. `catchup`: every nth week opens nothing
 *  new (0: none); `taper`: the last days before `end` open nothing new. */
function phases(v: unknown): Obj {
  if (!V.isObj(v)) throw V.bad("plan");
  for (const k of Object.keys(v)) if (!["catchup", "taper"].includes(k)) throw V.bad("plan");
  const catchup = v.catchup ?? 0;
  const taper = v.taper ?? 0;
  if (!V.isInt(catchup, 0, 8) || catchup === 1 || !V.isInt(taper, 0, 60)) throw V.bad("plan");
  return { catchup, taper };
}

/** 3.3: the builder's pace. `days`, Monday first: the plan's study days
 *  (1) and days off (0); `mode`: an end date, cards a day, or each day as
 *  placed; `daily`: cards a day; `cover`: what the plan means to cover
 *  ("tag:path" or "deck:path"), for laying it out. Only `days` reaches a
 *  follower: an even split spreads over them. */
function pace(v: unknown): Obj {
  if (!V.isObj(v)) throw V.bad("plan");
  for (const k of Object.keys(v)) if (!["mode", "days", "daily", "cover"].includes(k)) throw V.bad("plan");
  if (!["end", "daily", "placed"].includes(v.mode as string)) throw V.bad("plan");
  if (!Array.isArray(v.days) || v.days.length !== 7 || !v.days.every((d) => d === 0 || d === 1) || !v.days.some((d) => d === 1)) throw V.bad("plan");
  const out: Obj = { mode: v.mode, days: v.days };
  if (v.daily !== undefined && v.daily !== null) {
    if (!V.isInt(v.daily, 1, 5000)) throw V.bad("plan");
    out.daily = v.daily;
  }
  if (v.cover !== undefined && v.cover !== null) {
    if (!Array.isArray(v.cover) || v.cover.length > COVER_MAX) throw V.bad("plan");
    out.cover = [...new Set(v.cover.map((c) => {
      if (!V.isStr(c, PATH_MAX + 5, 5) || !/^(tag|deck):./.test(c)) throw V.bad("plan");
      path(c.slice(c.indexOf(":") + 1));
      return c;
    }))];
  }
  return out;
}

/** A plan's doc: {deck, exam?, end?, phases?, pace?, units}. Units sorted by when they open. */
export function planDoc(v: unknown): Obj {
  if (!V.isObj(v)) throw V.bad("plan");
  for (const k of Object.keys(v)) if (!["deck", "exam", "end", "phases", "pace", "reviews", "units", "events"].includes(k)) throw V.bad("plan");
  const out: Obj = { deck: path(v.deck) };
  if (v.pace !== undefined && v.pace !== null) out.pace = pace(v.pace);
  if (v.end !== undefined && v.end !== null) {
    if (!V.isDate(v.end)) throw V.bad("plan");
    out.end = v.end;
  }
  if (v.phases !== undefined && v.phases !== null) {
    const ph = phases(v.phases);
    if (ph.catchup || ph.taper) out.phases = ph;
    if (ph.taper && !out.end) throw V.bad("plan");  // a taper runs up to the end date
  }
  if (v.exam !== undefined && v.exam !== null) {
    const e = v.exam as Obj;
    if (!V.isObj(e) || !V.isDate(e.date) || !V.isInt(e.target, 50, 100)
        || (e.by !== undefined && !V.isDate(e.by))) throw V.bad("plan");
    out.exam = { date: e.date, target: e.target, ...(e.by ? { by: e.by } : {}) };
  }
  if (!Array.isArray(v.units) || v.units.length > UNITS_MAX) throw V.bad("plan");
  const units = v.units.map(unit);
  if (new Set(units.map((u) => u.id)).size !== units.length) throw V.bad("plan");
  const idLen = (u: Obj) => ((u.nids as unknown[] | undefined)?.length ?? 0) + ((u.cids as unknown[] | undefined)?.length ?? 0);
  if (units.reduce((n, u) => n + (u.cards as unknown[]).length + idLen(u), 0) > CARDS_MAX) throw V.bad("plan");
  if (units.reduce((n, u) => n + ((u.ids as unknown[] | undefined)?.length ?? 0), 0) > IDS_MAX) throw V.bad("plan");
  if (v.reviews !== undefined && v.reviews !== null) {
    // 3.3, C4: a review day: that morning, a filtered deck of the dates from `from` to `to`
    const ids = new Set(units.map((u) => u.id));
    if (!Array.isArray(v.reviews) || v.reviews.length > REVIEWS_MAX) throw V.bad("plan");
    const rs = v.reviews.map((r) => {
      if (!V.isObj(r) || Object.keys(r).some((k) => !["day", "from", "to"].includes(k)) || !V.isDate(r.day)
          || !ids.has(r.from as string) || !ids.has(r.to as string)) throw V.bad("plan");
      return { day: r.day, from: r.from, to: r.to };
    });
    if (rs.length) out.reviews = rs.sort((a, b) => String(a.day).localeCompare(String(b.day)));
  }
  // F1: events: a name on a day; a date's `for` names one (a `for` whose
  // event went, in a merge, is dropped rather than refused)
  const evIds = new Set<string>();
  if (v.events !== undefined && v.events !== null) {
    if (!Array.isArray(v.events) || v.events.length > EVENTS_MAX) throw V.bad("plan");
    const evs = v.events.map((e) => {
      if (!V.isObj(e) || Object.keys(e).some((k) => !["id", "day", "name"].includes(k)) || !V.isStr(e.id, 12) || !UNIT_ID.test(e.id as string)
          || !V.isDate(e.day)) throw V.bad("plan");
      const name = V.displayName(e.name);
      if (!name) throw V.bad("plan");
      if (evIds.has(e.id as string)) throw V.bad("plan");
      evIds.add(e.id as string);
      return { id: e.id, day: e.day, name };
    });
    if (evs.length) out.events = evs.sort((a, b) => String(a.day).localeCompare(String(b.day)));
  }
  for (const u of units) if (u.for && !evIds.has(u.for as string)) delete u.for;
  units.sort((a, b) => String(a.opens).localeCompare(String(b.opens)));
  out.units = units;
  if (JSON.stringify(out).length > DOC_MAX) throw V.bad("plan");
  return out;
}

/** 3.5, B: what a library card shows, so the library never reads a doc:
 *  the deck, how many dates over how many days, about how many new cards a
 *  study day, review days, events, and whether dates hold pasted ids. */
export function libCard(doc: Obj): Obj {
  const units = (doc.units as Obj[]) || [];
  const from = units.length ? (units[0].opens as string) : null;  // sorted by when they open
  const to = units.reduce<string | null>((m, u) => { const e = (u.due as string) || (u.opens as string); return !m || e > m ? e : m; }, null);
  const days = from && to ? Math.round((Date.parse(to) - Date.parse(from)) / 86400000) + 1 : 0;
  const week = ((doc.pace as Obj | undefined)?.days as number[] | undefined) || [1, 1, 1, 1, 1, 1, 1];
  let study = 0;
  for (let i = 0; i < days; i++) if (week[(new Date(Date.parse(`${from}T00:00:00Z`) + i * 86400000).getUTCDay() + 6) % 7]) study++;
  const n = units.reduce((a, u) => a + unitCount(u), 0);
  return { deck: doc.deck, dates: units.length, from, to, days, n, perDay: study ? Math.round(n / study) : 0,
    reviews: ((doc.reviews as unknown[]) || []).length, events: ((doc.events as unknown[]) || []).length,
    ids: units.some((u) => u.nids || u.cids) ? 1 : 0 };
}

/** A save's library card: redone from the new doc while it's listed. */
export function keepLib(p: Plan, doc: string): string | null {
  return p.listed === 1 ? JSON.stringify(libCard(JSON.parse(doc))) : (p.lib ?? null);
}

/** 3.2: a follower's own schedule. `days`, Monday first: 0 rest, 1 study,
 *  2 a double share. `minutes` a day; `start` when later than the plan. */
export function schedule(v: unknown): Obj | null {
  if (v === null) return null;
  if (!V.isObj(v)) throw V.bad("sched");
  for (const k of Object.keys(v)) if (!["start", "days", "minutes"].includes(k)) throw V.bad("sched");
  if (!Array.isArray(v.days) || v.days.length !== 7 || !v.days.every((d) => V.isInt(d, 0, 2))
      || !v.days.some((d) => d > 0)) throw V.bad("sched");
  if (!V.isInt(v.minutes, 10, 600)) throw V.bad("sched");
  const out: Obj = { days: v.days, minutes: v.minutes };
  if (v.start !== undefined && v.start !== null) {
    if (!V.isDate(v.start)) throw V.bad("sched");
    out.start = v.start;
  }
  return out;
}

export function planLine(v: unknown): string {
  if (v === undefined || v === null || v === "") return "";
  if (!V.isStr(v, LINE_MAX * 2)) throw V.bad("line");
  return V.oneLine(v, LINE_MAX);
}

// ---- access ----

export async function getPlan(env: Env, id: string): Promise<Plan> {
  const p = await env.DB.prepare("SELECT * FROM plans WHERE id = ?").bind(id).first<Plan>();
  if (!p) throw new HttpError(404, "no_plan");
  return p;
}

async function isMember(env: Env, squad: string | null, uid: string): Promise<boolean> {
  return !!squad && !!(await env.DB.prepare("SELECT 1 FROM members WHERE squad = ? AND uid = ?").bind(squad, uid).first());
}

// a follow as a row: mine only (G3, G4: my shift, my pause's days, my skips)
const FOLLOW_COLS = "share, paused, sched, progress, early, shift, pause_until, pause_since, skipped";

async function following(env: Env, plan: string, uid: string) {
  return env.DB.prepare(`SELECT ${FOLLOW_COLS} FROM plan_follows WHERE plan = ? AND uid = ?`).bind(plan, uid).first<Follow>();
}

/** My follow's own days, as the add-on and the site read them. */
function followDays(f: { shift?: number | null; pause_until?: string | null; pause_since?: string | null; skipped?: string | null }) {
  return { shift: f.shift ?? 0, until: f.pause_until ?? null, since: f.pause_since ?? null,
    skipped: f.skipped ? JSON.parse(f.skipped) as string[] : [] };
}

/** Who may see a plan: its author, its followers, and whoever may follow it. */
async function mayRead(env: Env, p: Plan, uid: string, code?: string): Promise<boolean> {
  if (p.owner === uid || (await isEditor(env, p.id, uid))) return true;
  if (p.audience === "squad") return isMember(env, p.squad, uid);  // leaving the squad ends it, follow or not
  if (p.listed === 1) return true;  // 3.5, B: in the library, for anyone signed in
  if (await following(env, p.id, uid)) return true;
  return (!!code && normalizeCode(code) === p.code) || isMember(env, p.squad, uid);
}

/** 3.3: the owner and co-authors edit; the owner alone deletes, picks the
 *  audience and the co-authors. */
export async function isEditor(env: Env, plan: string, uid: string): Promise<boolean> {
  return !!(await env.DB.prepare("SELECT 1 FROM plan_editors WHERE plan = ? AND uid = ?").bind(plan, uid).first());
}

async function authorOnly(env: Env, id: string, s: Session): Promise<Plan> {
  const p = await getPlan(env, id);
  if (p.owner !== s.uid && !(await isEditor(env, id, s.uid))) throw new HttpError(403, "not_author");
  return p;
}

async function role(env: Env, p: Plan, uid: string): Promise<"owner" | "editor" | "follower" | "reader"> {
  if (p.owner === uid) return "owner";
  if (await isEditor(env, p.id, uid)) return "editor";
  if (await following(env, p.id, uid)) return "follower";
  return "reader";
}

async function ownerOnly(env: Env, id: string, s: Session): Promise<Plan> {
  const p = await getPlan(env, id);
  if (p.owner !== s.uid) throw new HttpError(403, "not_author");
  return p;
}

type Follow = { share: number; paused: number; sched: string | null; progress: string | null; early: number;
  shift: number; pause_until: string | null; pause_since: string | null; skipped: string | null };
type Editor = { uid: string; name: string; emoji: string };

/** A plan as its page shows it. What it needs about me comes in `ctx`, so
 *  a list of plans reads it in a few queries, not a few per plan. */
function shape(p: Plan & { owner_name?: string | null }, uid: string, doc: unknown,
               ctx: { f: Follow | null; n: number; editors: Editor[]; mySquads: Set<string> }) {
  const { f, editors } = ctx;
  const r = p.owner === uid ? "owner" : editors.some((e) => e.uid === uid) ? "editor" : f ? "follower" : "reader";
  return {
    role: r, editors,
    id: p.id, name: p.name, line: p.line, owner: p.owner, ownerName: p.owner_name || "?",
    audience: p.audience, version: p.version, doc, followers: ctx.n,
    // which squad it's offered to: only for the author and that squad's members (an id is not an invite)
    squad: p.owner === uid || (!!p.squad && ctx.mySquads.has(p.squad)) ? p.squad : null,
    ...(r === "owner" || r === "editor" || (r === "follower" && p.audience === "code") || p.listed === 1 ? { code: p.code } : {}),
    // 3.5, B: in the library (the code shows there); the authors also see if the admin took it out, and why
    library: p.listed === 1,
    ...(r === "owner" || r === "editor" ? { listed: p.listed ?? 0, ...(p.listed === -1 ? { listedNote: p.listed_note || "" } : {}) } : {}),
    ...(p.based_on ? { basedOn: JSON.parse(p.based_on) } : {}),
    // mine only: my schedule, and my own progress (3.2's on-track line on the site)
    ...(f ? { following: { share: f.share === 1, paused: f.paused === 1, sched: f.sched ? JSON.parse(f.sched) : null, early: f.early ?? 0,
                           progress: f.progress ? JSON.parse(f.progress) : null, ...followDays(f) } } : {}),
  };
}

const editorsOf = (env: Env, ids: string[]) => env.DB.prepare(
  `SELECT e.plan, e.uid, u.name, u.emoji FROM plan_editors e JOIN users u ON u.uid = e.uid
    WHERE e.plan IN (${ids.map(() => "?").join(",")}) ORDER BY e.at`,
).bind(...ids).all<{ plan: string; uid: string; name: string | null; emoji: string | null }>();

export async function view(env: Env, p: Plan, uid: string) {
  const [f, n, eds, owner, member] = await env.DB.batch<any>([
    env.DB.prepare(`SELECT ${FOLLOW_COLS} FROM plan_follows WHERE plan = ? AND uid = ?`).bind(p.id, uid),
    env.DB.prepare("SELECT COUNT(*) AS n FROM plan_follows WHERE plan = ?").bind(p.id),
    env.DB.prepare(`SELECT e.plan, e.uid, u.name, u.emoji FROM plan_editors e JOIN users u ON u.uid = e.uid WHERE e.plan = ? ORDER BY e.at`).bind(p.id),
    env.DB.prepare("SELECT name FROM users WHERE uid = ?").bind(p.owner),
    env.DB.prepare("SELECT squad FROM members WHERE squad = ? AND uid = ?").bind(p.squad ?? "", uid),
  ]);
  return shape({ ...p, owner_name: owner.results[0]?.name }, uid, JSON.parse(p.doc), {
    f: (f.results[0] as Follow) ?? null, n: n.results[0]?.n ?? 0,
    editors: eds.results.map((e: any) => ({ uid: e.uid, name: e.name || "?", emoji: e.emoji || "" })),
    mySquads: new Set(member.results.map((m: any) => m.squad)),
  });
}

// ---- the deck's tree, from the add-on ----

/** A tree as the add-on sends it since 3.3: nested, each name once,
 *  [name, n, [children]?]; paths (the names joined by ::) up to PATH_MAX. */
function nested(v: unknown, budget: { nodes: number }, prefix = 0, depth = 0): unknown[] {
  if (!Array.isArray(v) || depth > NEST_DEPTH) throw V.bad("tree");
  return v.map((x) => {
    if (!Array.isArray(x) || x.length < 2 || x.length > 3 || !V.isInt(x[1])) throw V.bad("tree");
    const name = x[0];
    if (!V.isStr(name, PATH_MAX, 1) || /[\u0000-\u001f]/.test(name) || name.includes("::")) throw V.bad("tree");
    const len = prefix + (prefix ? 2 : 0) + name.length;
    if (len > PATH_MAX || --budget.nodes < 0) throw V.bad("tree");
    return x.length === 3 ? [name, x[1], nested(x[2], budget, len, depth + 1)] : [name, x[1]];
  });
}

/** PUT /plans/trees {deck, tags, decks}: names and counts only. 3.3 sends
 *  them nested ({v: 2}); 3.1 and 3.2 send [[path, n]] lists. */
export async function putTree(req: Request, s: Session, env: Env): Promise<Response> {
  const body = await readJson(req, TREE_BODY_MAX);
  const deck = path(body.deck);
  const list = (v: unknown) => {
    if (!Array.isArray(v) || v.length > TREE_MAX) throw V.bad("tree");
    return v.map((x) => {
      if (!Array.isArray(x) || x.length !== 2 || !V.isInt(x[1])) throw V.bad("tree");
      return [path(x[0]), x[1]];
    });
  };
  let doc: string;
  if (body.v === 2) {
    const budget = { nodes: NEST_MAX };
    doc = JSON.stringify({ v: 2, tags: nested(body.tags ?? [], budget), decks: nested(body.decks ?? [], budget) });
  } else {
    doc = JSON.stringify({ tags: list(body.tags ?? []), decks: list(body.decks ?? []) });
  }
  await limitOrThrow(env, `tree:${s.uid}`, 30, 3600);
  const n = await env.DB.prepare("SELECT COUNT(*) AS n FROM plan_trees WHERE uid = ? AND deck != ?").bind(s.uid, deck).first<number>("n");
  if ((n ?? 0) >= TREES_MAX) {
    // the oldest tree makes room: a tree is only ever the latest upload
    await env.DB.prepare("DELETE FROM plan_trees WHERE uid = ?1 AND deck = (SELECT deck FROM plan_trees WHERE uid = ?1 ORDER BY at LIMIT 1)")
      .bind(s.uid).run();
  }
  const now = nowSec();
  await env.DB.prepare(
    `INSERT INTO plan_trees (uid, deck, doc, at) VALUES (?, ?, ?, ?)
     ON CONFLICT(uid, deck) DO UPDATE SET doc = excluded.doc, at = excluded.at WHERE plan_trees.doc != excluded.doc`,
  ).bind(s.uid, deck, doc, now).run();
  return json({ ok: true });
}

/** GET /plans/trees?deck=: that deck's tree, for the builder; without a
 *  deck, which decks I have trees for (names and when, not the trees). */
export async function getTrees(req: Request, s: Session, env: Env): Promise<Response> {
  const deck = new URL(req.url).searchParams.get("deck");
  if (deck !== null) {
    const r = await env.DB.prepare("SELECT deck, doc, at FROM plan_trees WHERE uid = ? AND deck = ?").bind(s.uid, deck)
      .first<{ deck: string; doc: string; at: number }>();
    return json({ trees: r ? [{ deck: r.deck, at: r.at, ...JSON.parse(r.doc) }] : [] });
  }
  const rows = await env.DB.prepare("SELECT deck, at FROM plan_trees WHERE uid = ? ORDER BY at DESC").bind(s.uid)
    .all<{ deck: string; at: number }>();
  return json({ trees: rows.results });
}

// ---- authoring ----

/** POST /plans {name, deck, line?}: a new plan, no units yet; I'm its author. */
export async function create(req: Request, s: Session, env: Env): Promise<Response> {
  const body = await readJson(req);
  const name = V.displayName(body.name);
  const doc = JSON.stringify(planDoc({ deck: body.deck, units: [] }));
  const line = planLine(body.line);
  await limitOrThrow(env, `plannew:${s.uid}`, 20, 3600);
  const mine = await env.DB.prepare("SELECT COUNT(*) AS n FROM plans WHERE owner = ?").bind(s.uid).first<number>("n");
  if ((mine ?? 0) >= PLANS_MAX) throw new HttpError(409, "too_many_plans");
  const now = nowSec();
  for (let i = 0; i < 3; i++) {
    const id = draw(16).toLowerCase();
    const code = draw(PLAN_CODE_LEN);
    const r = await env.DB.prepare(
      `INSERT INTO plans (id, code, owner, name, line, doc, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING`,
    ).bind(id, code, s.uid, name, line, doc, now, now).run();
    if (r.meta.changes) return json(await view(env, await getPlan(env, id), s.uid));
  }
  throw new HttpError(503, "try_again");
}

/** GET /plans/{id}[?code=]: the plan, for whoever may see it. */
export async function get(req: Request, s: Session, env: Env, [id]: string[]): Promise<Response> {
  const p = await getPlan(env, id);
  if (!(await mayRead(env, p, s.uid, new URL(req.url).searchParams.get("code") || undefined))) throw new HttpError(404, "no_plan");
  return json(await view(env, p, s.uid));
}

/** GET /plans/peek?code=: the plan behind a code, before following. 60 an hour. */
export async function peek(req: Request, s: Session, env: Env): Promise<Response> {
  await limitOrThrow(env, `planpeek:${s.uid}`, 60, 3600);
  const code = normalizeCode(new URL(req.url).searchParams.get("code") || "");
  const p = code.length === PLAN_CODE_LEN
    ? await env.DB.prepare("SELECT * FROM plans WHERE code = ?").bind(code).first<Plan>() : null;
  if (!p || !(await mayRead(env, p, s.uid, code))) throw new HttpError(404, "no_plan");
  return json(await view(env, p, s.uid));
}

/** PUT /plans/{id} {version, name?, line?, audience?, squad?, doc?}: the
 *  author's save. A stale version is refused with the current one. */
export async function put(req: Request, s: Session, env: Env, [id]: string[]): Promise<Response> {
  const p = await authorOnly(env, id, s);
  const body = await readJson(req, PLAN_BODY_MAX);
  for (const k of Object.keys(body)) if (!["version", "name", "line", "audience", "squad", "doc", "summary"].includes(k)) throw V.bad("plan");
  if (p.owner !== s.uid && ((body.audience !== undefined && body.audience !== p.audience)
      || (body.squad !== undefined && body.squad !== p.squad))) throw new HttpError(403, "not_owner");
  const summary = body.summary === undefined ? "" : V.oneLine(String(body.summary), SUMMARY_MAX);
  if (!V.isInt(body.version, 1)) throw V.bad("version");
  const next = {
    name: body.name !== undefined ? V.displayName(body.name) : p.name,
    line: body.line !== undefined ? planLine(body.line) : p.line,
    audience: p.audience,
    squad: p.squad,
    doc: body.doc !== undefined ? JSON.stringify(planDoc(body.doc)) : p.doc,
  };
  if (body.audience !== undefined) {
    if (body.audience !== "code" && body.audience !== "squad") throw V.bad("audience");
    next.audience = body.audience;
  }
  if (body.squad !== undefined) {
    if (body.squad !== null && (!V.isStr(body.squad, 64, 1) || !(await isMember(env, body.squad, s.uid)))) throw V.bad("squad");
    next.squad = body.squad;
  }
  if (next.audience === "squad" && !next.squad) throw V.bad("squad");
  if (next.name === p.name && next.line === p.line && next.audience === p.audience
      && next.squad === p.squad && next.doc === p.doc) {
    return json(await view(env, p, s.uid));  // nothing changed: nothing written
  }
  // 3.5, B: a plan for one squad leaves the library; a listed plan's card follows its doc
  const listed = next.audience === "squad" && p.listed === 1 ? 0 : (p.listed ?? 0);
  const lib = listed === 1 && next.doc !== p.doc ? JSON.stringify(libCard(JSON.parse(next.doc))) : (p.lib ?? null);
  const r = await env.DB.prepare(
    `UPDATE plans SET name = ?, line = ?, audience = ?, squad = ?, doc = ?, listed = ?, lib = ?, version = version + 1, updated_at = ?
     WHERE id = ? AND version = ?`,
  ).bind(next.name, next.line, next.audience, next.squad, next.doc, listed, lib, nowSec(), id, body.version).run();
  if (!r.meta.changes) throw new HttpError(409, "stale", { version: (await getPlan(env, id)).version });
  await logSave(env, id, (body.version as number) + 1, s.uid, summary || "changed the plan", next.doc !== p.doc ? p.doc : null);
  return json(await view(env, await getPlan(env, id), s.uid));
}

/** One row of the plan's history: who saved, what they said it did, and
 *  the doc it replaced (for Undo). The last LOG_KEEP stay. */
export async function logSave(env: Env, plan: string, version: number, uid: string, summary: string, prev: string | null) {
  await env.DB.batch([
    env.DB.prepare("INSERT OR REPLACE INTO plan_log (plan, version, uid, at, summary, prev) VALUES (?, ?, ?, ?, ?, ?)")
      .bind(plan, version, uid, nowSec(), summary, prev),
    env.DB.prepare("DELETE FROM plan_log WHERE plan = ? AND version <= ?").bind(plan, version - LOG_KEEP),
  ]);
}

/** PUT /plans/{id}/ids {units: {unitId: [tags, decks, [guid]]}}: 3.3, C5.
 *  An author's Anki keeps the note ids behind each date's tags and
 *  subdecks, so a follower whose AnKing renamed a tag still gets the date.
 *  A unit's ids are taken only while its tags and subdecks are still the
 *  ones they were read from. Never a history entry; a new version. */
export async function putIds(req: Request, s: Session, env: Env, [id]: string[]): Promise<Response> {
  const p = await authorOnly(env, id, s);
  const body = await readJson(req, PLAN_BODY_MAX);
  if (!V.isObj(body.units) || Object.keys(body).some((k) => k !== "units" && k !== "counts")) throw V.bad("ids");
  if (body.counts !== undefined && !V.isObj(body.counts)) throw V.bad("ids");
  const doc = JSON.parse(p.doc) as Obj & { units: Obj[] };
  const same = (a: unknown, b: unknown) => JSON.stringify(a ?? []) === JSON.stringify(b ?? []);
  for (const [uid, v] of Object.entries(body.units)) {
    if (!Array.isArray(v) || v.length !== 3 || !Array.isArray(v[2])) throw V.bad("ids");
    const u = doc.units.find((x) => x.id === uid);
    if (!u || !same(u.tags, v[0]) || !same(u.decks, v[1])) continue;  // changed since: the next refresh sends it again
    if (v[2].length) u.ids = v[2]; else delete u.ids;
  }
  // 3.4, D1: how many cards each of a date's searches finds in my copy
  for (const [uid, v] of Object.entries((body.counts as Obj) || {})) {
    const u = doc.units.find((x) => x.id === uid);
    if (!u || !V.isObj(v)) continue;
    const qs = (u.search as string[]) || [];
    const sn: Obj = { ...((u.sn as Obj) || {}) };
    for (const [q, n] of Object.entries(v)) {
      // E1: "#ids" is how many cards the date's pasted ids found
      if (q === "#ids") { if ((u.nids || u.cids) && V.isInt(n, 0, 1_000_000)) u.idn = n; continue; }
      if (!qs.includes(q) || !V.isInt(n, 0, 1_000_000)) continue;  // a search taken off since: skipped
      sn[q] = n;
    }
    if (Object.keys(sn).length) u.sn = sn;
  }
  const clean = JSON.stringify(planDoc(doc));
  if (clean === p.doc) return json({ version: p.version });
  const r = await env.DB.prepare("UPDATE plans SET doc = ?, lib = ?, version = version + 1, updated_at = ? WHERE id = ? AND version = ?")
    .bind(clean, keepLib(p, clean), nowSec(), id, p.version).run();
  if (!r.meta.changes) throw new HttpError(409, "stale", { version: (await getPlan(env, id)).version });
  return json({ version: p.version + 1 });
}

/** GET /plans/{id}/log: the history, newest first, for the authors. */
export async function log(s: Session, env: Env, [id]: string[]): Promise<Response> {
  const p = await authorOnly(env, id, s);
  const rows = await env.DB.prepare(
    `SELECT l.version, l.uid, l.at, l.summary, l.prev IS NOT NULL AS undoable, u.name FROM plan_log l
       LEFT JOIN users u ON u.uid = l.uid WHERE l.plan = ? ORDER BY l.version DESC LIMIT ?`,
  ).bind(id, LOG_KEEP).all<{ version: number; uid: string; at: number; summary: string; undoable: number; name: string | null }>();
  return json({ log: rows.results.map((r) => ({ version: r.version, uid: r.uid, name: r.name || "?", at: r.at, summary: r.summary,
    undo: r.version === p.version && r.undoable === 1 })) });
}

/** POST /plans/{id}/undo {version}: puts back what the latest save replaced. */
export async function undo(req: Request, s: Session, env: Env, [id]: string[]): Promise<Response> {
  const p = await authorOnly(env, id, s);
  const body = await readJson(req);
  if (body.version !== p.version) throw new HttpError(409, "stale", { version: p.version });
  const row = await env.DB.prepare("SELECT summary, prev FROM plan_log WHERE plan = ? AND version = ?").bind(id, p.version)
    .first<{ summary: string; prev: string | null }>();
  if (!row || !row.prev) throw new HttpError(404, "nothing_to_undo");
  const r = await env.DB.prepare("UPDATE plans SET doc = ?, lib = ?, version = version + 1, updated_at = ? WHERE id = ? AND version = ?")
    .bind(row.prev, keepLib(p, row.prev), nowSec(), id, p.version).run();
  if (!r.meta.changes) throw new HttpError(409, "stale", { version: (await getPlan(env, id)).version });
  await logSave(env, id, p.version + 1, s.uid, V.oneLine(`undid: ${row.summary}`, SUMMARY_MAX), p.doc);
  return json(await view(env, await getPlan(env, id), s.uid));
}

// ---- co-authors ----

/** POST /plans/{id}/editors {uid}: the owner adds a co-author from their crew. */
export async function addEditor(req: Request, s: Session, env: Env, [id]: string[]): Promise<Response> {
  const p = await ownerOnly(env, id, s);
  const body = await readJson(req);
  if (!V.isStr(body.uid, 128, 1) || body.uid === s.uid) throw V.bad("editor");
  const mutual = await env.DB.prepare(
    "SELECT 1 FROM friends a JOIN friends b ON b.owner = a.friend AND b.friend = a.owner WHERE a.owner = ? AND a.friend = ?",
  ).bind(s.uid, body.uid).first();
  if (!mutual) throw new HttpError(403, "not_crew");
  const n = await env.DB.prepare("SELECT COUNT(*) AS n FROM plan_editors WHERE plan = ?").bind(id).first<number>("n");
  if ((n ?? 0) >= EDITORS_MAX) throw new HttpError(409, "too_many_editors");
  await env.DB.prepare("INSERT INTO plan_editors (plan, uid, at) VALUES (?, ?, ?) ON CONFLICT DO NOTHING").bind(id, body.uid, nowSec()).run();
  return json(await view(env, p, s.uid));
}

/** DELETE /plans/{id}/editors/{uid}: the owner removes a co-author, or one leaves. */
export async function removeEditor(s: Session, env: Env, [id, uid]: string[]): Promise<Response> {
  const p = await getPlan(env, id);
  if (p.owner !== s.uid && uid !== s.uid) throw new HttpError(403, "not_owner");
  await env.DB.prepare("DELETE FROM plan_editors WHERE plan = ? AND uid = ?").bind(id, uid).run();
  return json({ ok: true });
}

// ---- notes on a day ----

/** Who may read and write a plan's notes: its authors and followers. */
async function inPlan(env: Env, id: string, uid: string): Promise<Plan> {
  const p = await getPlan(env, id);
  if ((await role(env, p, uid)) === "reader") throw new HttpError(404, "no_plan");
  return p;
}

/** GET /plans/{id}/notes: every note, oldest first. Names as on the board. */
export async function notes(s: Session, env: Env, [id]: string[]): Promise<Response> {
  const p = await inPlan(env, id, s.uid);
  const rows = await env.DB.prepare(
    `SELECT n.id, n.uid, n.day, n.text, n.at, u.name, u.emoji FROM plan_notes n LEFT JOIN users u ON u.uid = n.uid
      WHERE n.plan = ? ORDER BY n.id LIMIT ?`,
  ).bind(id, NOTES_MAX).all<{ id: number; uid: string; day: string; text: string; at: number; name: string | null; emoji: string | null }>();
  const author = p.owner === s.uid || (await isEditor(env, id, s.uid));
  return json({ notes: rows.results.map((r) => ({ id: r.id, uid: r.uid, name: r.name || "?", emoji: r.emoji || "", day: r.day,
    text: r.text, at: r.at, mine: r.uid === s.uid, remove: r.uid === s.uid || author })) });
}

/** POST /plans/{id}/notes {day, text}: a note on a day ("lab day, keep it light"). */
export async function addNote(req: Request, s: Session, env: Env, [id]: string[]): Promise<Response> {
  await inPlan(env, id, s.uid);
  const body = await readJson(req);
  if (!V.isDate(body.day) || !V.isStr(body.text, NOTE_TEXT_MAX * 4, 1)) throw V.bad("note");
  const text = V.oneLine(body.text as string, NOTE_TEXT_MAX);
  if (!text) throw V.bad("note");
  await limitOrThrow(env, `plannote:${s.uid}`, 60, 3600);
  const n = await env.DB.prepare("SELECT COUNT(*) AS n FROM plan_notes WHERE plan = ?").bind(id).first<number>("n");
  if ((n ?? 0) >= NOTES_MAX) throw new HttpError(409, "too_many_notes");
  const r = await env.DB.prepare("INSERT INTO plan_notes (plan, uid, day, text, at) VALUES (?, ?, ?, ?, ?)")
    .bind(id, s.uid, body.day, text, nowSec()).run();
  return json({ id: r.meta.last_row_id, day: body.day, text });
}

/** DELETE /plans/{id}/notes/{nid}: its writer, or an author (done with it). */
export async function removeNote(s: Session, env: Env, [id, nid]: string[]): Promise<Response> {
  const p = await inPlan(env, id, s.uid);
  const author = p.owner === s.uid || (await isEditor(env, id, s.uid));
  await env.DB.prepare(`DELETE FROM plan_notes WHERE plan = ? AND id = ?${author ? "" : " AND uid = ?"}`)
    .bind(...(author ? [id, Number(nid)] : [id, Number(nid), s.uid])).run();
  return json({ ok: true });
}

/** POST /plans/{id}/cards {cards, unit? | opens (+ name?)}: single cards
 *  picked in Anki's browser, added to a date that exists or a new one. */
export async function addCards(req: Request, s: Session, env: Env, [id]: string[]): Promise<Response> {
  const p = await authorOnly(env, id, s);
  const body = await readJson(req, PLAN_BODY_MAX);
  // 3.3, C3: or an Anki search, with how many it found here
  const search = body.search !== undefined ? body.search : null;
  if (search !== null && (!V.isStr(search, SEARCH_LEN, 1) || !V.isInt(body.n, 0, 1_000_000))) throw V.bad("cards");
  if (search === null && (!Array.isArray(body.cards) || !body.cards.length)) throw V.bad("cards");
  const cards = search === null ? (body.cards as unknown[]).map(cardRef) : [];
  const doc = JSON.parse(p.doc) as { units: Obj[] };
  let u: Obj | undefined;
  if (body.unit !== undefined) {
    u = doc.units.find((x) => x.id === body.unit);
    if (!u) throw new HttpError(404, "no_unit");
  } else {
    if (!V.isDate(body.opens)) throw V.bad("opens");
    u = { id: newUnitId(), name: body.name !== undefined ? V.displayName(body.name) : `Cards · ${body.opens}`,
          opens: body.opens, tags: [], decks: [], cards: [] };
    doc.units.push(u);
  }
  u.cards = [...(u.cards as [string, number][]), ...cards];
  if (search !== null) {
    u.search = [...new Set([...((u.search as string[]) || []), search as string])];
    u.sn = { ...((u.sn as Obj) || {}), [search as string]: body.n };
  }
  const clean = JSON.stringify(planDoc(doc));  // dedupes, re-sorts, enforces the caps
  if (clean === p.doc) return json(await view(env, p, s.uid));
  const r = await env.DB.prepare("UPDATE plans SET doc = ?, lib = ?, version = version + 1, updated_at = ? WHERE id = ? AND version = ?")
    .bind(clean, keepLib(p, clean), nowSec(), id, p.version).run();
  if (!r.meta.changes) throw new HttpError(409, "stale", { version: (await getPlan(env, id)).version });
  await logSave(env, id, p.version + 1, s.uid, search !== null ? "added a search in Anki"
    : `added ${cards.length} single card${cards.length === 1 ? "" : "s"} in Anki`, p.doc);
  return json(await view(env, await getPlan(env, id), s.uid));
}

/** DELETE /plans/{id}: the author takes it down. Followers keep every card
 *  they have open; nothing is suspended anywhere. */
export async function remove(s: Session, env: Env, [id]: string[]): Promise<Response> {
  await ownerOnly(env, id, s);
  await env.DB.batch([
    env.DB.prepare("DELETE FROM plan_follows WHERE plan = ?").bind(id),
    env.DB.prepare("DELETE FROM plan_editors WHERE plan = ?").bind(id),
    env.DB.prepare("DELETE FROM plan_notes WHERE plan = ?").bind(id),
    env.DB.prepare("DELETE FROM plan_log WHERE plan = ?").bind(id),
    env.DB.prepare("DELETE FROM plans WHERE id = ?").bind(id),
  ]);
  return json({ ok: true });
}

// ---- 3.4, D2: the plan as a calendar ----

const icsText = (t: string) => t.replace(/\\/g, "\\\\").replace(/;/g, "\\;").replace(/,/g, "\\,").replace(/\r?\n/g, "\\n");
const icsDate = (d: string) => d.replace(/-/g, "");
const dayAfter = (d: string) => new Date(Date.parse(`${d}T00:00:00Z`) + 86400000).toISOString().slice(0, 10);

/** RFC 5545: lines of at most 75 octets, continued with a space, never
 *  splitting a character. */
function fold(line: string): string {
  const enc = new TextEncoder();
  if (enc.encode(line).length <= 75) return line;
  const out: string[] = [];
  let cur = "";
  let n = 0;
  for (const ch of line) {
    const b = enc.encode(ch).length;
    if (n + b > (out.length ? 74 : 75)) { out.push(cur); cur = ""; n = 0; }
    cur += ch;
    n += b;
  }
  out.push(cur);
  return out.join("\r\n ");
}

/** GET /plans/ics?code=: the plan's dates as a calendar to subscribe to.
 *  No sign-in (a calendar app can't), like the shared link; the code opens
 *  it, and a plan for one squad has none. Names of people never appear. */
export async function ics(req: Request, env: Env): Promise<Response> {
  const code = normalizeCode(new URL(req.url).searchParams.get("code") || "");
  if (code.length !== PLAN_CODE_LEN) throw new HttpError(404, "no_plan");
  // by address, not by code: guessing codes stays slow, and nobody holding a
  // code can use up its calendar for everyone (Google polls from few addresses)
  await limitOrThrow(env, `ics:ip:${clientIp(req)}`, 1000, 3600);
  const p = await env.DB.prepare("SELECT * FROM plans WHERE code = ?").bind(code).first<Plan>();
  if (!p || p.audience === "squad") throw new HttpError(404, "no_plan");
  const doc = JSON.parse(p.doc) as { units: Obj[]; reviews?: { day: string; from: string; to: string }[]; events?: { id: string; day: string; name: string }[] };
  const stamp = new Date(p.updated_at * 1000).toISOString().replace(/[-:]/g, "").replace(/\.\d+Z$/, "Z");
  const link = `https://duecrew.com/p/${p.code}`;
  const lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Due Crew//Plans//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
    `X-WR-CALNAME:${icsText(p.name)}`, "REFRESH-INTERVAL;VALUE=DURATION:PT6H", "X-PUBLISHED-TTL:PT6H"];
  const event = (uid: string, start: string, end: string, summary: string) => lines.push("BEGIN:VEVENT",
    `UID:${uid}.${p.id}@duecrew.com`, `DTSTAMP:${stamp}`, `DTSTART;VALUE=DATE:${icsDate(start)}`, `DTEND;VALUE=DATE:${icsDate(end)}`,
    `SUMMARY:${icsText(summary)}`, `DESCRIPTION:${icsText(p.name)}`, `URL:${link}`, "TRANSP:TRANSPARENT", "END:VEVENT");
  const byId = new Map(doc.units.map((u) => [u.id as string, u]));
  for (const u of doc.units) {
    const n = unitCount(u);
    const last = u.even && u.due ? (u.due as string) : (u.opens as string);
    event(u.id as string, u.opens as string, dayAfter(last), `${u.name}${n ? ` · ${n.toLocaleString("en-US")} new` : ""}`);
  }
  // F1: an event is its own day, with how many dates prep for it
  for (const ev of doc.events || []) {
    const prep = doc.units.filter((u) => u.for === ev.id).length;
    event(`e${ev.id}`, ev.day, dayAfter(ev.day), `${ev.name}${prep ? ` · ${prep} day${prep === 1 ? "" : "s"} of prep` : ""}`);
  }
  for (const r of doc.reviews || []) {
    const a = byId.get(r.from), b = byId.get(r.to);
    if (!a || !b) continue;
    event(`r${icsDate(r.day)}${r.from}${r.to}`, r.day, dayAfter(r.day), `Review · ${a.name}${a !== b ? ` – ${b.name}` : ""}`);
  }
  lines.push("END:VCALENDAR");
  return new Response(lines.map(fold).join("\r\n") + "\r\n", { headers: {
    "content-type": "text/calendar; charset=utf-8", "cache-control": "public, max-age=10800",
    "content-disposition": `inline; filename="due-crew-${p.code}.ics"` } });
}

/** GET /plans/public?code=: what a plan's shared link shows before anyone
 *  signs in (3.4 review, C1): its name, whose, the one line, how many
 *  follow, and each date's name, day and card count. The calendar link
 *  already gives the dates to anyone with the code; a squad's plan has none. */
export async function publicPeek(req: Request, env: Env): Promise<Response> {
  const code = normalizeCode(new URL(req.url).searchParams.get("code") || "");
  if (code.length !== PLAN_CODE_LEN) throw new HttpError(404, "no_plan");
  await limitOrThrow(env, `pub:ip:${clientIp(req)}`, 300, 3600);  // guessing codes stays slow
  const p = await env.DB.prepare(
    `SELECT p.id, p.name, p.line, p.audience, p.version, p.doc, u.name AS owner_name,
            (SELECT COUNT(*) FROM plan_follows f WHERE f.plan = p.id) AS followers
       FROM plans p LEFT JOIN users u ON u.uid = p.owner WHERE p.code = ?`,
  ).bind(code).first<{ id: string; name: string; line: string; audience: string; version: number; doc: string; owner_name: string | null; followers: number }>();
  if (!p || p.audience === "squad") throw new HttpError(404, "no_plan");
  const doc = JSON.parse(p.doc) as { deck: string; units: Obj[]; events?: { day: string; name: string }[] };
  const n = unitCount;
  return json({
    name: p.name, ownerName: p.owner_name || "?", line: p.line || "", deck: doc.deck, followers: p.followers ?? 0,
    // 3.5, A: the version keys the link's preview picture; events are in the calendar feed already
    v: p.version, events: (doc.events || []).map((e) => ({ day: e.day, name: e.name })),
    units: doc.units.map((u) => ({ name: u.name, opens: u.opens, ...(u.due ? { due: u.due } : {}), n: n(u) })),
  });
}

// ---- following ----

/** POST /plans/follow {code, share?, sched?}: follow the plan behind a code. */
export async function follow(req: Request, s: Session, env: Env): Promise<Response> {
  const body = await readJson(req);
  if (typeof body.code !== "string") throw V.bad("code");
  const sched = body.sched !== undefined ? schedule(body.sched) : undefined;
  const code = normalizeCode(body.code);
  await limitOrThrow(env, `planpeek:${s.uid}`, 60, 3600);  // the same guesses as peek's
  const p = await env.DB.prepare("SELECT * FROM plans WHERE code = ?").bind(code).first<Plan>();
  if (!p || !(await mayRead(env, p, s.uid, code))) throw new HttpError(404, "no_plan");
  const share = body.share === false ? 0 : 1;
  if (!(await following(env, p.id, s.uid))) {
    // a bound on what every board carries (and on one query's parameters)
    const n = await env.DB.prepare("SELECT COUNT(*) AS n FROM plan_follows WHERE uid = ?").bind(s.uid).first<number>("n");
    if ((n ?? 0) >= FOLLOWS_MAX) throw new HttpError(409, "too_many_plans");
  }
  const sj = sched === undefined ? null : sched === null ? null : JSON.stringify(sched);
  await env.DB.prepare(
    `INSERT INTO plan_follows (plan, uid, share, paused, sched, at) VALUES (?, ?, ?, 0, ?, ?)
     ON CONFLICT(plan, uid) DO UPDATE SET share = excluded.share, paused = 0
       ${sched === undefined ? "" : ", sched = excluded.sched"}`,
  ).bind(p.id, s.uid, share, sj, nowSec()).run();
  return json(await view(env, p, s.uid));
}

/** PATCH /plans/{id}/follow {share?, paused?, sched?, early?, shift?, until?, since?, skipped?}.
 *  G3, G4: my own days: how many days my dates run later than the plan's
 *  (0-365), a pause's first and last day, the dates I skip (unit ids). */
export async function patchFollow(req: Request, s: Session, env: Env, [id]: string[]): Promise<Response> {
  const body = await readJson(req);
  for (const k of Object.keys(body)) if (!["share", "paused", "sched", "early", "shift", "until", "since", "skipped"].includes(k)) throw V.bad("follow");
  if (body.early !== undefined && !V.isInt(body.early, 0, 7)) throw V.bad("follow");
  if (body.shift !== undefined && !V.isInt(body.shift, 0, 365)) throw V.bad("follow");
  for (const k of ["until", "since"]) if (body[k] !== undefined && body[k] !== null && !V.isDate(body[k])) throw V.bad("follow");
  if (body.skipped !== undefined && (!Array.isArray(body.skipped) || body.skipped.length > UNITS_MAX
      || !body.skipped.every((u) => typeof u === "string" && UNIT_ID.test(u)))) throw V.bad("follow");
  const f = await following(env, id, s.uid);
  if (!f) throw new HttpError(404, "not_following");
  const share = typeof body.share === "boolean" ? (body.share ? 1 : 0) : f.share;
  const paused = typeof body.paused === "boolean" ? (body.paused ? 1 : 0) : f.paused;
  const sched = body.sched !== undefined ? schedule(body.sched) : undefined;
  const sj = sched === undefined ? f.sched : sched === null ? null : JSON.stringify(sched);
  const early = body.early !== undefined ? body.early as number : f.early ?? 0;
  const shift = body.shift !== undefined ? body.shift as number : f.shift ?? 0;
  const until = body.until !== undefined ? (body.until as string | null) : f.pause_until;
  const since = body.since !== undefined ? (body.since as string | null) : f.pause_since;
  const skipped = body.skipped !== undefined ? ((body.skipped as string[]).length ? JSON.stringify([...new Set(body.skipped as string[])]) : null) : f.skipped;
  if (share !== f.share || paused !== f.paused || sj !== f.sched || early !== (f.early ?? 0) || shift !== (f.shift ?? 0)
      || until !== f.pause_until || since !== f.pause_since || skipped !== f.skipped) {
    await env.DB.prepare(
      `UPDATE plan_follows SET share = ?, paused = ?, sched = ?, early = ?, shift = ?, pause_until = ?, pause_since = ?, skipped = ?${share ? "" : ", progress = NULL"}
        WHERE plan = ? AND uid = ?`,
    ).bind(share, paused, sj, early, shift, until, since, skipped, id, s.uid).run();
  }
  return json({ share: share === 1, paused: paused === 1, sched: sj ? JSON.parse(sj) : null, early,
    ...followDays({ shift, pause_until: until, pause_since: since, skipped }) });
}

/** DELETE /plans/{id}/follow: stop. My progress goes with it. */
export async function unfollow(s: Session, env: Env, [id]: string[]): Promise<Response> {
  await env.DB.prepare("DELETE FROM plan_follows WHERE plan = ? AND uid = ?").bind(id, s.uid).run();
  return json({ ok: true });
}

/** GET /plans/mine: plans I wrote and plans I follow. Each doc without its
 *  single cards and note ids (a list never needs them; they're most of a
 *  big plan), and everything else in five queries, however many plans. */
export async function mine(s: Session, env: Env): Promise<Response> {
  const rows = await env.DB.prepare(
    `SELECT p.id, p.code, p.owner, p.name, p.line, p.audience, p.squad, p.version, p.updated_at, u.name AS owner_name,
            p.listed, p.listed_note, p.based_on,
            json_remove(p.doc, '$.units') AS rest,
            (SELECT json_group_array(json_remove(x.value, '$.ids', '$.cards')) FROM json_each(p.doc, '$.units') x) AS units
       FROM plans p LEFT JOIN users u ON u.uid = p.owner
      WHERE p.id IN (SELECT id FROM plans WHERE owner = ?1 UNION SELECT plan FROM plan_follows WHERE uid = ?1
                     UNION SELECT plan FROM plan_editors WHERE uid = ?1)
      ORDER BY p.updated_at DESC`,  // each part by index, not a scan of every plan
  ).bind(s.uid).all<Plan & { owner_name: string | null; rest: string; units: string }>();
  const ids = rows.results.map((p) => p.id);
  if (!ids.length) return json({ plans: [] });
  const inIds = ids.map(() => "?").join(",");
  const [fs, ns, eds, sq] = await Promise.all([
    env.DB.prepare(`SELECT plan, ${FOLLOW_COLS} FROM plan_follows WHERE uid = ?`).bind(s.uid)
      .all<Follow & { plan: string }>(),
    env.DB.prepare(`SELECT plan, COUNT(*) AS n FROM plan_follows WHERE plan IN (${inIds}) GROUP BY plan`).bind(...ids)
      .all<{ plan: string; n: number }>(),
    editorsOf(env, ids),
    env.DB.prepare("SELECT squad FROM members WHERE uid = ?").bind(s.uid).all<{ squad: string }>(),
  ]);
  const follows = new Map(fs.results.map((f) => [f.plan, f]));
  const counts = new Map(ns.results.map((r) => [r.plan, r.n]));
  const editors = new Map<string, Editor[]>();
  for (const e of eds.results) editors.set(e.plan, [...(editors.get(e.plan) ?? []), { uid: e.uid, name: e.name || "?", emoji: e.emoji || "" }]);
  const mySquads = new Set(sq.results.map((m) => m.squad));
  return json({ plans: rows.results.map((p) => {
    const units = (JSON.parse(p.units) as Obj[]).sort((a, b) => String(a.opens).localeCompare(String(b.opens)));
    return shape(p, s.uid, { ...JSON.parse(p.rest), units },
      { f: follows.get(p.id) ?? null, n: counts.get(p.id) ?? 0, editors: editors.get(p.id) ?? [], mySquads });
  }) });
}

// ---- progress ----

/** Validates a sync's `plans` part: {planId: {unitId: [opened, seen, total]}}. */
export function progressPart(v: unknown): Record<string, Record<string, [number, number, number]>> {
  if (!V.isObj(v) || Object.keys(v).length > 50) throw V.bad("plans");
  const out: Record<string, Record<string, [number, number, number]>> = {};
  for (const [pid, units] of Object.entries(v)) {
    if (!/^[a-z0-9]{1,32}$/.test(pid) || !V.isObj(units) || Object.keys(units).length > UNITS_MAX) throw V.bad("plans");
    out[pid] = {};
    for (const [uid, t] of Object.entries(units)) {
      if (!UNIT_ID.test(uid) || !Array.isArray(t) || t.length !== 3 || !t.every((n) => V.isInt(n))) throw V.bad("plans");
      const [opened, seen, total] = t as number[];
      if (opened > total || seen > total) throw V.bad("plans");
      out[pid][uid] = [opened, seen, total];
    }
  }
  return out;
}

/** The statements that store my progress: only for plans I follow with
 *  sharing on, and only where it changed. */
export async function progressWrites(env: Env, uid: string, part: ReturnType<typeof progressPart>) {
  const ids = Object.keys(part);
  if (!ids.length) return [];
  const rows = await env.DB.prepare(
    `SELECT plan, progress FROM plan_follows WHERE uid = ? AND share = 1 AND plan IN (${ids.map(() => "?").join(",")})`,
  ).bind(uid, ...ids).all<{ plan: string; progress: string | null }>();
  return rows.results
    .map((r) => ({ r, doc: JSON.stringify(part[r.plan]) }))
    .filter(({ r, doc }) => r.progress !== doc)
    .map(({ r, doc }) => env.DB.prepare("UPDATE plan_follows SET progress = ? WHERE plan = ? AND uid = ?").bind(doc, r.plan, uid));
}

/** GET /plans/{id}/progress: for its authors, per unit, how many followers
 *  (among those sharing) have it opened and done. Counts, never names. */
export async function progress(s: Session, env: Env, [id]: string[]): Promise<Response> {
  const p = await authorOnly(env, id, s);
  const rows = await env.DB.prepare("SELECT progress FROM plan_follows WHERE plan = ? AND share = 1 AND progress IS NOT NULL")
    .bind(id).all<{ progress: string }>();
  const units: Record<string, { opened: number; done: number }> = {};
  for (const u of (JSON.parse(p.doc).units as Obj[])) units[u.id as string] = { opened: 0, done: 0 };
  for (const r of rows.results) {
    for (const [uid, [opened, seen, total]] of Object.entries(JSON.parse(r.progress) as Record<string, number[]>)) {
      if (!units[uid]) continue;
      if (opened > 0) units[uid].opened++;
      if (total > 0 && seen >= total) units[uid].done++;
    }
  }
  const followers = await env.DB.prepare("SELECT COUNT(*) AS n FROM plan_follows WHERE plan = ?").bind(id).first<number>("n");
  return json({ followers: followers ?? 0, sharing: rows.results.length, units });
}

// ---- the board ----

/** What the day's first refresh carries: the plans I follow, and plans
 *  offered to my squads that I don't follow yet. */
export async function forBoard(env: Env, uid: string) {
  const mineRows = await env.DB.prepare(
    `SELECT p.id, p.name, p.owner, p.version, p.doc, f.share, f.paused, f.sched, f.early,
            f.shift, f.pause_until, f.pause_since, f.skipped, u.name AS owner_name
       FROM plan_follows f JOIN plans p ON p.id = f.plan LEFT JOIN users u ON u.uid = p.owner
      WHERE f.uid = ?1 AND (p.audience != 'squad' OR p.owner = ?1
            OR EXISTS (SELECT 1 FROM members m WHERE m.squad = p.squad AND m.uid = ?1))`,
  ).bind(uid).all<any>();
  const offers = await env.DB.prepare(
    `SELECT p.id, p.name, p.code, p.squad, u.name AS owner_name FROM plans p
       JOIN members m ON m.squad = p.squad AND m.uid = ?1 LEFT JOIN users u ON u.uid = p.owner
      WHERE p.owner != ?1 AND NOT EXISTS (SELECT 1 FROM plan_follows f WHERE f.plan = p.id AND f.uid = ?1)`,
  ).bind(uid).all<any>();
  // per plan: how many follow, and per unit how many sharing followers have it done. Counts only.
  const crew = new Map<string, { followers: number; done: Record<string, number> }>();
  if (mineRows.results.length) {
    const ids = mineRows.results.map((r) => r.id);
    const rows = await env.DB.prepare(
      `SELECT plan, share, progress FROM plan_follows WHERE plan IN (${ids.map(() => "?").join(",")})`,
    ).bind(...ids).all<{ plan: string; share: number; progress: string | null }>();
    for (const r of rows.results) {
      const c = crew.get(r.plan) ?? { followers: 0, done: {} };
      c.followers++;
      if (r.share === 1 && r.progress) {
        for (const [u, [, seen, total]] of Object.entries(JSON.parse(r.progress) as Record<string, number[]>)) {
          if (total > 0 && seen >= total) c.done[u] = (c.done[u] ?? 0) + 1;
        }
      }
      crew.set(r.plan, c);
    }
  }
  // 3.3, C5: the plans I write, so my Anki can keep the note ids behind their
  // tags. Only what that needs, cut in SQL: a plan's ids are most of its doc.
  const authored = await env.DB.prepare(
    `SELECT p.id, p.version, json_extract(p.doc, '$.deck') AS deck,
            (SELECT json_group_array(json_object('id', json_extract(x.value, '$.id'), 'tags', json_extract(x.value, '$.tags'),
                      'decks', json_extract(x.value, '$.decks'), 'search', json_extract(x.value, '$.search'),
                      'nids', json_extract(x.value, '$.nids'), 'cids', json_extract(x.value, '$.cids')))
               FROM json_each(p.doc, '$.units') x
              WHERE json_array_length(x.value, '$.tags') + json_array_length(x.value, '$.decks')
                    + coalesce(json_array_length(x.value, '$.search'), 0) + coalesce(json_array_length(x.value, '$.nids'), 0)
                    + coalesce(json_array_length(x.value, '$.cids'), 0) > 0) AS units
       FROM plans p WHERE p.id IN (SELECT id FROM plans WHERE owner = ?1 UNION SELECT plan FROM plan_editors WHERE uid = ?1)`,
  ).bind(uid).all<{ id: string; version: number; deck: string; units: string }>();
  const lean = (r: { deck: string; units: string }) => ({ deck: r.deck, units: (JSON.parse(r.units) as Obj[])
    .map((u) => (u.search || u.nids || u.cids ? Object.fromEntries(Object.entries(u).filter(([, x]) => x !== null)) : { id: u.id, tags: u.tags, decks: u.decks })) });
  return {
    authored: authored.results.map((r) => ({ id: r.id, version: r.version, doc: lean(r) })),
    plans: mineRows.results.map((r) => ({ id: r.id, name: r.name, owner: r.owner, ownerName: r.owner_name || "?",
      version: r.version, doc: JSON.parse(r.doc), share: r.share === 1, paused: r.paused === 1,
      sched: r.sched ? JSON.parse(r.sched) : null, early: r.early ?? 0, ...followDays(r),
      followers: crew.get(r.id)?.followers ?? 0, crewDone: crew.get(r.id)?.done ?? {} })),
    planOffers: offers.results.map((r) => ({ id: r.id, name: r.name, code: r.code, squad: r.squad, ownerName: r.owner_name || "?" })),
  };
}
