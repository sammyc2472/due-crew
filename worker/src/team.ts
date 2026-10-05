// 3.7.3: a plan's team. Followers and authors who join (opt-in, per plan) see
// who on the team showed up today (answered one of the plan's cards), ask
// the team anything and answer, and play the week's bingo card together. Joining
// shares that I showed up, my questions and answers, and my bingo squares;
// never my numbers. Each add-on says it showed up (and its squares, the same
// as on its squad rows) with the sync it already makes; the board
// carries a few counts; the tab itself is one request when it opens.

import type { Session } from "./auth";
import * as B from "./bingo";
import { limitOrThrow } from "./limits";
import * as P from "./plans";
import * as V from "./validate";
import { ankiDay, Env, HttpError, json, nowSec, readJson } from "./util";

const TEXT_MAX = 280;
const TOPIC_MAX = 80;
const DAYS_KEEP = 60;        // a member's showed-up days kept, for the streak
const FACES_MAX = 24;        // a big library plan shows the first 24, then "+N"
const THREADS_SHOWN = 30;
const THREADS_KEEP = 200;    // a plan keeps its newest
const REPLIES_MAX = 50;      // a thread's replies
const THREADS_PER_DAY = 10;  // one person's new questions to one plan, a day
const TEAMS_PER_SYNC = 20;   // P.FOLLOWS_MAX
const ACT_ON_BOARD = 20;
const TEAM_MAX = 500;        // members of one plan's team

/** A team row whose member may still see the plan: an author, or a
 *  follower (of a squad's plan, while in the squad). Losing that ends what
 *  the team shows of them and to them, without a write. `t` is plan_team. */
const STILL_IN = `(EXISTS (SELECT 1 FROM plans o WHERE o.id = t.plan AND o.owner = t.uid)
  OR EXISTS (SELECT 1 FROM plan_editors e WHERE e.plan = t.plan AND e.uid = t.uid)
  OR EXISTS (SELECT 1 FROM plan_follows f JOIN plans fp ON fp.id = f.plan WHERE f.plan = t.plan AND f.uid = t.uid
             AND (fp.audience != 'squad' OR fp.squad IN (SELECT squad FROM members WHERE uid = t.uid))))`;

type Obj = Record<string, unknown>;
type Member = { uid: string; days: string | null; play: string | null; joined_at: number; name: string | null;
  emoji: string | null; tz: number | null; rollover: number | null };

const parseDays = (s: string | null): string[] => {
  try {
    const d = s ? JSON.parse(s) : [];
    return Array.isArray(d) ? d.filter((x) => typeof x === "string") : [];
  } catch {
    return [];
  }
};
const dayOf = (sec: number) => new Date(sec * 1000).toISOString().slice(0, 10);
const prevDay = (d: string) => new Date(Date.parse(`${d}T00:00:00Z`) - 86400000).toISOString().slice(0, 10);

/** Days in a row when more than half the team showed up, back from today.
 *  Today counts once it's past half; until then it doesn't end the run.
 *  Each day is out of the members who had joined by then. Pure. */
export function streak(members: { days: string[]; joined: string }[], today: string, max = DAYS_KEEP): number {
  const sets = members.map((m) => ({ days: new Set(m.days), joined: m.joined }));
  const past = (d: string) => {
    const on = sets.filter((m) => m.joined <= d);
    return on.length > 0 && 2 * on.filter((m) => m.days.has(d)).length > on.length;
  };
  let n = past(today) ? 1 : 0;
  for (let d = prevDay(today), i = 0; i < max && past(d); d = prevDay(d), i++) n++;
  return n;
}

async function mutedOf(env: Env, uid: string): Promise<Set<string>> {
  const raw = await env.DB.prepare("SELECT json FROM settings WHERE uid = ?").bind(uid).first<string>("json");
  try {
    return new Set((JSON.parse(raw || "{}").muted as string[]) || []);
  } catch {
    return new Set();
  }
}

async function members(env: Env, plan: string): Promise<Member[]> {
  return (await env.DB.prepare(
    `SELECT t.uid, t.days, t.play, t.joined_at, u.name, u.emoji, u.tz, u.rollover FROM plan_team t
       JOIN users u ON u.uid = t.uid WHERE t.plan = ? AND ${STILL_IN} ORDER BY t.joined_at, t.uid LIMIT ${TEAM_MAX}`,
  ).bind(plan).all<Member>()).results;
}

/** Who showed up today (each in their own Anki day), the streak, from the
 *  viewer's today. */
function showed(rows: Member[], me: { tz: number | null; rollover: number | null }, now = nowSec()) {
  const shown = new Set(rows.filter((m) => parseDays(m.days).includes(ankiDay(now, m.tz, m.rollover))).map((m) => m.uid));
  const run = streak(rows.map((m) => ({ days: parseDays(m.days), joined: dayOf(m.joined_at) })), ankiDay(now, me.tz, me.rollover));
  return { shown, run };
}

async function teamPlan(env: Env, id: string, uid: string) {
  const p = await P.getPlan(env, id);
  if ((await P.role(env, p, uid)) === "reader") throw new HttpError(404, "no_plan");
  return p;
}

async function onTeam(env: Env, id: string, uid: string): Promise<boolean> {
  return !!(await env.DB.prepare("SELECT 1 FROM plan_team WHERE plan = ? AND uid = ?").bind(id, uid).first());
}

/** GET /plans/{id}/team[?wk=2026-W41]: the team as its tab shows it. Not on
 *  the team: how many are. */
export async function get(req: Request, s: Session, env: Env, [id]: string[]): Promise<Response> {
  const p = await teamPlan(env, id, s.uid);
  return json(await view(env, p, s.uid, new URL(req.url).searchParams.get("wk")));
}

export async function view(env: Env, p: P.Plan, uid: string, wk: unknown) {
  const rows = await members(env, p.id);
  const mine = rows.find((m) => m.uid === uid);
  if (!mine) return { on: false, count: rows.length };
  const now = nowSec();
  const { shown, run } = showed(rows, mine, now);
  const muted = await mutedOf(env, uid);
  const order = [...rows].sort((a, b) => Number(shown.has(b.uid)) - Number(shown.has(a.uid)));
  const faces = order.slice(0, FACES_MAX).map((m) => ({ uid: m.uid, name: m.name || "?", emoji: m.emoji || "", shown: shown.has(m.uid) }));
  const authors = await P.authorUids(env, p);
  const threads = (await env.DB.prepare(
    `SELECT a.id, a.uid, a.text, a.guid, a.ord, a.topic, a.at, a.act, u.name, u.emoji
       FROM plan_asks a LEFT JOIN users u ON u.uid = a.uid
      WHERE a.plan = ?1 AND a.parent IS NULL
      ORDER BY a.act DESC, (SELECT MAX(r.id) FROM plan_asks r WHERE r.id = a.id OR r.parent = a.id) DESC LIMIT ?2`,
  ).bind(p.id, THREADS_SHOWN).all<Obj>()).results.filter((t) => !muted.has(t.uid as string));
  const ids = threads.map((t) => t.id as number);
  const replies = ids.length ? (await env.DB.prepare(
    `SELECT a.id, a.parent, a.uid, a.text, a.helped, a.at, u.name, u.emoji FROM plan_asks a LEFT JOIN users u ON u.uid = a.uid
      WHERE a.parent IN (${ids.map(() => "?").join(",")}) ORDER BY a.id`,
  ).bind(...ids).all<Obj>()).results.filter((r) => !muted.has(r.uid as string)) : [];
  const isAuthor = authors.has(uid);
  const asks = threads.map((t) => ({
    id: t.id, uid: t.uid, name: (t.name as string) || "?", emoji: (t.emoji as string) || "", text: t.text, at: t.at, act: t.act,
    ...(t.guid ? { guid: t.guid, ord: t.ord ?? 0 } : {}), topic: (t.topic as string) || "",
    mine: t.uid === uid, remove: t.uid === uid || isAuthor,
    author: authors.has(t.uid as string),
    replies: replies.filter((r) => r.parent === t.id).map((r) => ({
      id: r.id, uid: r.uid, name: (r.name as string) || "?", emoji: (r.emoji as string) || "", text: r.text, at: r.at,
      helped: r.helped === 1, author: authors.has(r.uid as string), mine: r.uid === uid, remove: r.uid === uid || isAuthor })),
  }));
  const out: Obj = { on: true, count: rows.length, shown: shown.size, streak: run, faces, more: Math.max(0, rows.length - FACES_MAX), asks };
  if (B.askable(wk)) out.bingo = await bingo(env, wk, rows);
  return out;
}

/** The team's card is the squad's (B.cardFor): the same squares and the
 *  same middle, each member's play the same as on their squad rows (worked
 *  out from all their studying), so a square stamped once counts in every
 *  squad and team they're in. Counts, never who. */
async function bingo(env: Env, wk: string, rows: Member[]) {
  const card = await B.cardFor(env, wk);
  const brows: B.Row[] = rows.map((m) => {
    const days = parseDays(m.days);
    let play: Obj | null = null;
    try { play = m.play ? JSON.parse(m.play) : null; } catch { /* none */ }
    return { uid: m.uid, emoji: m.emoji, day: days.length ? days[days.length - 1] : null, joined: dayOf(m.joined_at), play };
  });
  const ev = B.evaluate(card, brows);
  return { card, ev: { squares: ev.squares.map((q) => ({ n: q.who.length, need: q.need, done: q.done })),
    middle: ev.middle, lines: ev.lines, players: ev.players, active: ev.active, older: ev.older } };
}

/** POST /plans/{id}/team: join. DELETE: leave (my questions stay). */
export async function join(req: Request, s: Session, env: Env, [id]: string[]): Promise<Response> {
  const p = await teamPlan(env, id, s.uid);
  const n = await env.DB.prepare("SELECT COUNT(*) AS n FROM plan_team WHERE plan = ?").bind(id).first<number>("n");
  if ((n ?? 0) >= TEAM_MAX && !(await onTeam(env, id, s.uid))) throw new HttpError(409, "team_full");
  await env.DB.prepare("INSERT INTO plan_team (plan, uid, joined_at) VALUES (?, ?, ?) ON CONFLICT DO NOTHING")
    .bind(id, s.uid, nowSec()).run();
  return json(await view(env, p, s.uid, new URL(req.url).searchParams.get("wk")));
}

export async function leave(s: Session, env: Env, [id]: string[]): Promise<Response> {
  await env.DB.prepare("DELETE FROM plan_team WHERE plan = ? AND uid = ?").bind(id, s.uid).run();
  return json({ ok: true });
}

/** POST /plans/{id}/asks {text, parent?, guid?, ord?, topic?}: a question to
 *  the team (a card's, with the card as guid + number), or a reply to one.
 *  Team members only; one line; ceilings per person, plan and thread. */
export async function ask(req: Request, s: Session, env: Env, [id]: string[]): Promise<Response> {
  await teamPlan(env, id, s.uid);
  if (!(await onTeam(env, id, s.uid))) throw new HttpError(403, "not_on_team");
  const body = await readJson(req);
  for (const k of Object.keys(body)) if (!["text", "parent", "guid", "ord", "topic"].includes(k)) throw V.bad("ask");
  if (!V.isStr(body.text, TEXT_MAX * 4, 1)) throw V.bad("ask");
  const text = V.oneLine(body.text as string, TEXT_MAX);
  if (!text) throw V.bad("ask");
  const now = nowSec();
  await limitOrThrow(env, `teamask:${s.uid}`, 60, 3600);
  if (body.parent !== undefined) {
    if (!V.isInt(body.parent, 1) || body.guid !== undefined || body.topic !== undefined) throw V.bad("ask");
    const t = await env.DB.prepare("SELECT id FROM plan_asks WHERE id = ? AND plan = ? AND parent IS NULL").bind(body.parent, id).first();
    if (!t) throw new HttpError(404, "no_ask");
    const n = await env.DB.prepare("SELECT COUNT(*) AS n FROM plan_asks WHERE parent = ?").bind(body.parent).first<number>("n");
    if ((n ?? 0) >= REPLIES_MAX) throw new HttpError(409, "too_many_replies");
    const r = await env.DB.batch([
      env.DB.prepare("INSERT INTO plan_asks (plan, uid, parent, text, at, act) VALUES (?, ?, ?, ?, ?, ?)")
        .bind(id, s.uid, body.parent, text, now, now),
      env.DB.prepare("UPDATE plan_asks SET act = ?, act_by = ? WHERE id = ?").bind(now, s.uid, body.parent),
    ]);
    return json({ id: r[0].meta.last_row_id, text });
  }
  let guid: string | null = null, ord: number | null = null;
  if (body.guid !== undefined) {
    if (!V.isStr(body.guid, V.GUID_MAX, 1) || !V.isInt(body.ord ?? 0, 0, 500)) throw V.bad("ask");
    guid = body.guid as string;
    ord = (body.ord as number) ?? 0;
  } else if (body.ord !== undefined) throw V.bad("ask");
  if (body.topic !== undefined && !V.isStr(body.topic, TOPIC_MAX * 2)) throw V.bad("ask");
  const topic = body.topic === undefined ? null : V.oneLine(body.topic as string, TOPIC_MAX) || null;
  const mine = await env.DB.prepare("SELECT COUNT(*) AS n FROM plan_asks WHERE plan = ? AND uid = ? AND parent IS NULL AND at > ?")
    .bind(id, s.uid, now - 86400).first<number>("n");
  if ((mine ?? 0) >= THREADS_PER_DAY) throw new HttpError(429, "too_many_asks");
  const r = await env.DB.prepare("INSERT INTO plan_asks (plan, uid, text, guid, ord, topic, at, act, act_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)")
    .bind(id, s.uid, text, guid, ord, topic, now, now, s.uid).run();
  // the plan keeps its newest threads; their replies go with them
  const old = `SELECT id FROM plan_asks WHERE plan = ?1 AND parent IS NULL AND id NOT IN
                 (SELECT id FROM plan_asks WHERE plan = ?1 AND parent IS NULL ORDER BY act DESC, id DESC LIMIT ?2)`;
  await env.DB.batch([
    env.DB.prepare(`DELETE FROM plan_asks WHERE parent IN (${old})`).bind(id, THREADS_KEEP),
    env.DB.prepare(`DELETE FROM plan_asks WHERE id IN (${old})`).bind(id, THREADS_KEEP),
  ]);
  return json({ id: r.meta.last_row_id, text });
}

/** DELETE /plans/{id}/asks/{aid}: its writer, or an author. A question
 *  takes its replies with it. */
export async function removeAsk(s: Session, env: Env, [id, aid]: string[]): Promise<Response> {
  const p = await teamPlan(env, id, s.uid);
  const a = await env.DB.prepare("SELECT uid, parent FROM plan_asks WHERE id = ? AND plan = ?").bind(Number(aid), id)
    .first<{ uid: string; parent: number | null }>();
  if (!a) return json({ ok: true });
  if (a.uid !== s.uid && !(await P.authorUids(env, p)).has(s.uid)) throw new HttpError(403, "not_yours");
  await env.DB.batch([
    env.DB.prepare("DELETE FROM plan_asks WHERE parent = ?").bind(Number(aid)),
    env.DB.prepare("DELETE FROM plan_asks WHERE id = ?").bind(Number(aid)),
  ]);
  return json({ ok: true });
}

/** POST /plans/{id}/asks/{aid}/helped {on}: the asker marks an answer that helped. */
export async function helped(req: Request, s: Session, env: Env, [id, aid]: string[]): Promise<Response> {
  await teamPlan(env, id, s.uid);
  const body = await readJson(req);
  if (typeof body.on !== "boolean") throw V.bad("helped");
  const r = await env.DB.prepare(
    "SELECT q.uid AS asker FROM plan_asks a JOIN plan_asks q ON q.id = a.parent WHERE a.id = ? AND a.plan = ?",
  ).bind(Number(aid), id).first<{ asker: string }>();
  if (!r) throw new HttpError(404, "no_ask");
  if (r.asker !== s.uid) throw new HttpError(403, "not_yours");
  await env.DB.prepare("UPDATE plan_asks SET helped = ? WHERE id = ? AND helped != ?").bind(body.on ? 1 : 0, Number(aid), body.on ? 1 : 0).run();
  return json({ ok: true });
}

// ---- the sync and the board ----

/** A sync's `team` part: {planId: {days?, play?}}: the days of my last
 *  eight (my Anki days) I answered one of the plan's cards, and my squares
 *  from its cards. A phone's reviews reach my computer's Anki only with the
 *  AnkiWeb sync, so yesterday can arrive today; days outside the last nine
 *  (or after tomorrow) are left out. */
export function teamPart(v: unknown, now = nowSec()): Record<string, { days: string[]; play: string | null }> {
  if (!V.isObj(v) || Object.keys(v).length > TEAMS_PER_SYNC) throw V.bad("team");
  const lo = dayOf(now - 9 * 86400), hi = dayOf(now + 86400);
  const out: Record<string, { days: string[]; play: string | null }> = {};
  for (const [pid, x] of Object.entries(v)) {
    if (!/^[a-z0-9]{1,32}$/.test(pid) || !V.isObj(x)) throw V.bad("team");
    for (const k of Object.keys(x)) if (!["days", "play"].includes(k)) throw V.bad("team");
    const days = x.days ?? [];
    if (!Array.isArray(days) || days.length > 9 || !days.every((d) => V.isDate(d))) throw V.bad("team");
    out[pid] = { days: [...new Set(days as string[])].filter((d) => d >= lo && d <= hi), play: V.play(x.play) };
  }
  return out;
}

/** What a sync writes: only rows I hold (an update never makes me a member),
 *  and only what changed. */
export async function teamWrites(env: Env, uid: string, part: ReturnType<typeof teamPart>) {
  const ids = Object.keys(part);
  if (!ids.length) return [];
  const rows = await env.DB.prepare(
    `SELECT plan, days, last_day, play FROM plan_team WHERE uid = ? AND plan IN (${ids.map(() => "?").join(",")})`,
  ).bind(uid, ...ids).all<{ plan: string; days: string | null; last_day: string | null; play: string | null }>();
  const out: D1PreparedStatement[] = [];
  for (const r of rows.results) {
    const x = part[r.plan];
    let days = parseDays(r.days);
    if (x.days.some((d) => !days.includes(d))) days = [...new Set([...days, ...x.days])].sort().slice(-DAYS_KEEP);
    const dj = days.length ? JSON.stringify(days) : null;
    const play = x.play ?? r.play;
    const last = days.length ? days[days.length - 1] : null;  // what the board reads, not the whole list
    if (dj !== r.days || play !== r.play || last !== r.last_day) {
      out.push(env.DB.prepare("UPDATE plan_team SET days = ?, last_day = ?, play = ? WHERE plan = ? AND uid = ?").bind(dj, last, play, r.plan, uid));
    }
  }
  return out;
}

/** For an add-on's refresh: per plan I'm on the team of, the counts its
 *  Plan tab line and badge need: who showed up today (each member's last
 *  day, not their history), and when the newest threads moved. The streak
 *  waits for the tab. Three reads, however many teams. */
export async function forBoard(env: Env, uid: string) {
  const mine = (await env.DB.prepare(`SELECT t.plan FROM plan_team t WHERE t.uid = ? AND ${STILL_IN}`)
    .bind(uid).all<{ plan: string }>()).results.map((r) => r.plan);
  if (!mine.length) return undefined;
  const qs = mine.map(() => "?").join(",");
  const [mem, acts] = await env.DB.batch<any>([
    env.DB.prepare(
      `SELECT t.plan, t.uid, t.last_day, u.emoji, u.tz, u.rollover FROM plan_team t
         JOIN users u ON u.uid = t.uid WHERE t.plan IN (${qs}) AND ${STILL_IN}`).bind(...mine),
    env.DB.prepare(
      `SELECT plan, uid, act, act_by, text, name FROM (
         SELECT a.plan, a.uid, a.act, a.act_by, a.text, u.name,
                ROW_NUMBER() OVER (PARTITION BY a.plan ORDER BY a.act DESC, a.id DESC) AS k
           FROM plan_asks a LEFT JOIN users u ON u.uid = a.uid WHERE a.plan IN (${qs}) AND a.parent IS NULL)
        WHERE k <= ${ACT_ON_BOARD} ORDER BY act DESC`).bind(...mine),
  ]);
  const muted = await mutedOf(env, uid);
  const now = nowSec();
  const out: Record<string, Obj> = {};
  for (const plan of mine) {
    const rows = (mem.results as { plan: string; uid: string; last_day: string | null; emoji: string | null; tz: number | null; rollover: number | null }[])
      .filter((m) => m.plan === plan);
    const shown = rows.filter((m) => m.last_day && m.last_day === ankiDay(now, m.tz, m.rollover));
    const threads = (acts.results as Obj[]).filter((a) => a.plan === plan && !muted.has(a.uid as string));
    const last = threads.find((a) => a.uid !== uid);
    out[plan] = { shown: shown.length, of: rows.length, faces: shown.slice(0, 4).map((m) => m.emoji || ""),
      // what moved since I looked: not by me (my own question, my own reply)
      act: threads.filter((a) => (a.act_by ?? a.uid) !== uid).map((a) => a.act), ...(last ? { last: { name: (last.name as string) || "?", text: last.text } } : {}) };
  }
  return out;
}
