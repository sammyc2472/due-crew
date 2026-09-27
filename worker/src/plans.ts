// Plans (3.1): a list of dates for one shared deck, made by its author and
// followed by anyone with its code (or, for a squad plan, the squad). A
// follower's add-on unsuspends each date's cards on the morning it opens;
// the server only holds names, counts, note guids with card numbers, dates
// and progress counts. Never card text. See docs/plans-design.md.

import type { Session } from "./auth";
import { limitOrThrow } from "./limits";
import { SQUAD_ALPHABET, normalizeCode } from "./squads";
import * as V from "./validate";
import { Env, HttpError, json, nowSec, readJson } from "./util";

export const PLAN_CODE_LEN = 8;
const UNITS_MAX = 200;
const CARDS_MAX = 5000;
const SOURCES_MAX = 50;
const PATH_MAX = 200;
const DOC_MAX = 256 * 1024;
const TREE_MAX = 5000;
const LINE_MAX = 120;
export const FOLLOWS_MAX = 20;
const TREES_MAX = 20;
const PLANS_MAX = 50;
const UNIT_ID = /^[a-z0-9]{1,12}$/;

type Obj = Record<string, unknown>;
type Plan = { id: string; code: string; owner: string; name: string; line: string; audience: string;
  squad: string | null; doc: string; version: number; updated_at: number };

function draw(n: number): string {
  const bytes = crypto.getRandomValues(new Uint8Array(n));
  return [...bytes].map((b) => SQUAD_ALPHABET[b % 32]).join("");
}

const newUnitId = () => draw(8).toLowerCase().replace(/[^a-z0-9]/g, "x");

// ---- shapes ----

function path(v: unknown): string {
  if (!V.isStr(v, PATH_MAX, 1) || /[\u0000-\u001f]/.test(v)) throw V.bad("plan");
  return v;
}

function cardRef(v: unknown): [string, number] {
  if (!Array.isArray(v) || v.length !== 2 || !V.isStr(v[0], V.GUID_MAX, 1) || !V.isInt(v[1], 0, 1000)) throw V.bad("plan");
  return [v[0], v[1]];
}

function unit(v: unknown): Obj {
  if (!V.isObj(v)) throw V.bad("plan");
  for (const k of Object.keys(v)) if (!["id", "name", "opens", "due", "lead", "check", "tags", "decks", "cards", "n"].includes(k)) throw V.bad("plan");
  if (!V.isStr(v.id, 12) || !UNIT_ID.test(v.id)) throw V.bad("plan");
  if (!V.isDate(v.opens)) throw V.bad("plan");
  const out: Obj = { id: v.id, name: V.displayName(v.name), opens: v.opens };
  if (v.due !== undefined && v.due !== null) {
    if (!V.isDate(v.due) || v.due < v.opens) throw V.bad("plan");
    out.due = v.due;
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
  const cards = v.cards ?? [];
  if (!Array.isArray(cards)) throw V.bad("plan");
  const seen = new Set<string>();
  out.cards = cards.map(cardRef).filter(([g, o]) => !seen.has(`${g}:${o}`) && seen.add(`${g}:${o}`));
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

/** A plan's doc: {deck, exam?, end?, phases?, units}. Units sorted by when they open. */
export function planDoc(v: unknown): Obj {
  if (!V.isObj(v)) throw V.bad("plan");
  for (const k of Object.keys(v)) if (!["deck", "exam", "end", "phases", "units"].includes(k)) throw V.bad("plan");
  const out: Obj = { deck: path(v.deck) };
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
  if (units.reduce((n, u) => n + (u.cards as unknown[]).length, 0) > CARDS_MAX) throw V.bad("plan");
  units.sort((a, b) => String(a.opens).localeCompare(String(b.opens)));
  out.units = units;
  if (JSON.stringify(out).length > DOC_MAX) throw V.bad("plan");
  return out;
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

function planLine(v: unknown): string {
  if (v === undefined || v === null || v === "") return "";
  if (!V.isStr(v, LINE_MAX * 2)) throw V.bad("line");
  return V.oneLine(v, LINE_MAX);
}

// ---- access ----

async function getPlan(env: Env, id: string): Promise<Plan> {
  const p = await env.DB.prepare("SELECT * FROM plans WHERE id = ?").bind(id).first<Plan>();
  if (!p) throw new HttpError(404, "no_plan");
  return p;
}

async function isMember(env: Env, squad: string | null, uid: string): Promise<boolean> {
  return !!squad && !!(await env.DB.prepare("SELECT 1 FROM members WHERE squad = ? AND uid = ?").bind(squad, uid).first());
}

async function following(env: Env, plan: string, uid: string) {
  return env.DB.prepare("SELECT share, paused, sched FROM plan_follows WHERE plan = ? AND uid = ?").bind(plan, uid)
    .first<{ share: number; paused: number; sched: string | null }>();
}

/** Who may see a plan: its author, its followers, and whoever may follow it. */
async function mayRead(env: Env, p: Plan, uid: string, code?: string): Promise<boolean> {
  if (p.owner === uid) return true;
  if (p.audience === "squad") return isMember(env, p.squad, uid);  // leaving the squad ends it, follow or not
  if (await following(env, p.id, uid)) return true;
  return (!!code && normalizeCode(code) === p.code) || isMember(env, p.squad, uid);
}

async function ownerOnly(env: Env, id: string, s: Session): Promise<Plan> {
  const p = await getPlan(env, id);
  if (p.owner !== s.uid) throw new HttpError(403, "not_author");
  return p;
}

async function ownerName(env: Env, uid: string): Promise<string> {
  return (await env.DB.prepare("SELECT name FROM users WHERE uid = ?").bind(uid).first<string>("name")) || "?";
}

async function view(env: Env, p: Plan, uid: string) {
  const f = await following(env, p.id, uid);
  const n = await env.DB.prepare("SELECT COUNT(*) AS n FROM plan_follows WHERE plan = ?").bind(p.id).first<number>("n");
  return {
    id: p.id, name: p.name, line: p.line, owner: p.owner, ownerName: await ownerName(env, p.owner),
    audience: p.audience, version: p.version, doc: JSON.parse(p.doc), followers: n ?? 0,
    // which squad it's offered to: only for the author and that squad's members (an id is not an invite)
    squad: p.owner === uid || (await isMember(env, p.squad, uid)) ? p.squad : null,
    ...(p.owner === uid ? { code: p.code } : {}),
    ...(f ? { following: { share: f.share === 1, paused: f.paused === 1, sched: f.sched ? JSON.parse(f.sched) : null } } : {}),
  };
}

// ---- the deck's tree, from the add-on ----

/** PUT /plans/trees {deck, tags: [[path, n]], decks: [[path, n]]}: names and counts only. */
export async function putTree(req: Request, s: Session, env: Env): Promise<Response> {
  const body = await readJson(req);
  const deck = path(body.deck);
  const list = (v: unknown) => {
    if (!Array.isArray(v) || v.length > TREE_MAX) throw V.bad("tree");
    return v.map((x) => {
      if (!Array.isArray(x) || x.length !== 2 || !V.isInt(x[1])) throw V.bad("tree");
      return [path(x[0]), x[1]];
    });
  };
  const doc = JSON.stringify({ tags: list(body.tags ?? []), decks: list(body.decks ?? []) });
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

/** GET /plans/trees: my decks' trees, for the builder. */
export async function getTrees(s: Session, env: Env): Promise<Response> {
  const rows = await env.DB.prepare("SELECT deck, doc, at FROM plan_trees WHERE uid = ? ORDER BY at DESC").bind(s.uid)
    .all<{ deck: string; doc: string; at: number }>();
  return json({ trees: rows.results.map((r) => ({ deck: r.deck, at: r.at, ...JSON.parse(r.doc) })) });
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
  const p = await ownerOnly(env, id, s);
  const body = await readJson(req);
  for (const k of Object.keys(body)) if (!["version", "name", "line", "audience", "squad", "doc"].includes(k)) throw V.bad("plan");
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
  const r = await env.DB.prepare(
    `UPDATE plans SET name = ?, line = ?, audience = ?, squad = ?, doc = ?, version = version + 1, updated_at = ?
     WHERE id = ? AND version = ?`,
  ).bind(next.name, next.line, next.audience, next.squad, next.doc, nowSec(), id, body.version).run();
  if (!r.meta.changes) throw new HttpError(409, "stale", { version: (await getPlan(env, id)).version });
  return json(await view(env, await getPlan(env, id), s.uid));
}

/** POST /plans/{id}/cards {cards, unit? | opens (+ name?)}: single cards
 *  picked in Anki's browser, added to a date that exists or a new one. */
export async function addCards(req: Request, s: Session, env: Env, [id]: string[]): Promise<Response> {
  const p = await ownerOnly(env, id, s);
  const body = await readJson(req);
  if (!Array.isArray(body.cards) || !body.cards.length) throw V.bad("cards");
  const cards = body.cards.map(cardRef);
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
  const clean = JSON.stringify(planDoc(doc));  // dedupes, re-sorts, enforces the caps
  if (clean === p.doc) return json(await view(env, p, s.uid));
  const r = await env.DB.prepare("UPDATE plans SET doc = ?, version = version + 1, updated_at = ? WHERE id = ? AND version = ?")
    .bind(clean, nowSec(), id, p.version).run();
  if (!r.meta.changes) throw new HttpError(409, "stale", { version: (await getPlan(env, id)).version });
  return json(await view(env, await getPlan(env, id), s.uid));
}

/** DELETE /plans/{id}: the author takes it down. Followers keep every card
 *  they have open; nothing is suspended anywhere. */
export async function remove(s: Session, env: Env, [id]: string[]): Promise<Response> {
  await ownerOnly(env, id, s);
  await env.DB.batch([
    env.DB.prepare("DELETE FROM plan_follows WHERE plan = ?").bind(id),
    env.DB.prepare("DELETE FROM plans WHERE id = ?").bind(id),
  ]);
  return json({ ok: true });
}

// ---- following ----

/** POST /plans/follow {code, share?, sched?}: follow the plan behind a code. */
export async function follow(req: Request, s: Session, env: Env): Promise<Response> {
  const body = await readJson(req);
  if (typeof body.code !== "string") throw V.bad("code");
  const sched = body.sched !== undefined ? schedule(body.sched) : undefined;
  const code = normalizeCode(body.code);
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

/** PATCH /plans/{id}/follow {share?, paused?, sched?}. */
export async function patchFollow(req: Request, s: Session, env: Env, [id]: string[]): Promise<Response> {
  const body = await readJson(req);
  for (const k of Object.keys(body)) if (!["share", "paused", "sched"].includes(k)) throw V.bad("follow");
  const f = await following(env, id, s.uid);
  if (!f) throw new HttpError(404, "not_following");
  const share = typeof body.share === "boolean" ? (body.share ? 1 : 0) : f.share;
  const paused = typeof body.paused === "boolean" ? (body.paused ? 1 : 0) : f.paused;
  const sched = body.sched !== undefined ? schedule(body.sched) : undefined;
  const sj = sched === undefined ? f.sched : sched === null ? null : JSON.stringify(sched);
  if (share !== f.share || paused !== f.paused || sj !== f.sched) {
    await env.DB.prepare(
      `UPDATE plan_follows SET share = ?, paused = ?, sched = ?${share ? "" : ", progress = NULL"} WHERE plan = ? AND uid = ?`,
    ).bind(share, paused, sj, id, s.uid).run();
  }
  return json({ share: share === 1, paused: paused === 1, sched: sj ? JSON.parse(sj) : null });
}

/** DELETE /plans/{id}/follow: stop. My progress goes with it. */
export async function unfollow(s: Session, env: Env, [id]: string[]): Promise<Response> {
  await env.DB.prepare("DELETE FROM plan_follows WHERE plan = ? AND uid = ?").bind(id, s.uid).run();
  return json({ ok: true });
}

/** GET /plans/mine: plans I wrote and plans I follow. */
export async function mine(s: Session, env: Env): Promise<Response> {
  const rows = await env.DB.prepare(
    `SELECT * FROM plans WHERE id IN (SELECT id FROM plans WHERE owner = ?1 UNION SELECT plan FROM plan_follows WHERE uid = ?1)
     ORDER BY updated_at DESC`,  // both halves by index, not a scan of every plan
  ).bind(s.uid).all<Plan>();
  const out = [];
  for (const p of rows.results) out.push(await view(env, p, s.uid));
  return json({ plans: out });
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

/** GET /plans/{id}/progress: for the author, per unit, how many followers
 *  (among those sharing) have it opened and done. Counts, never names. */
export async function progress(s: Session, env: Env, [id]: string[]): Promise<Response> {
  const p = await ownerOnly(env, id, s);
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
    `SELECT p.id, p.name, p.owner, p.version, p.doc, f.share, f.paused, f.sched, u.name AS owner_name
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
  return {
    plans: mineRows.results.map((r) => ({ id: r.id, name: r.name, owner: r.owner, ownerName: r.owner_name || "?",
      version: r.version, doc: JSON.parse(r.doc), share: r.share === 1, paused: r.paused === 1,
      sched: r.sched ? JSON.parse(r.sched) : null,
      followers: crew.get(r.id)?.followers ?? 0, crewDone: crew.get(r.id)?.done ?? {} })),
    planOffers: offers.results.map((r) => ({ id: r.id, name: r.name, code: r.code, squad: r.squad, ownerName: r.owner_name || "?" })),
  };
}
