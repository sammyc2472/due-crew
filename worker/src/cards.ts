// 3.2: who knows this one, tips that stay on a card, and my log. All of it
// rides POST /sync except "This helped", which is one request on a click.
// Cards are note guids; never their text. See docs/plans-design.md.

import type { Session } from "./auth";
import * as V from "./validate";
import { Env, HttpError, json, nowSec, readJson } from "./util";

export const KNOWS_PER_SYNC = 2000;
export const KNOWS_MAX = 100000;  // a person's cards "down": a big shared deck has ~35,000 notes
export const TIPS_MAX = 5000;     // tips a person keeps on cards
export const STUCK_MAX = 300;
export const TIP_MAX = V.NOTE_MAX;
const CHUNK = 90;           // D1: at most 100 bound parameters a statement
const LOG_DAYS = 400;      // days one sync carries
const LOG_KEEP = 15 * 366;  // 3.7.1: days kept, so a year card reaches back (the history import)
const KNOWERS_SHOWN = 5;
const TIPS_SHOWN = 3;

type Obj = Record<string, unknown>;

function guids(v: unknown, max: number, what: string): string[] {
  if (!Array.isArray(v) || v.length > max || !v.every((g) => V.isStr(g, V.GUID_MAX, 1))) throw V.bad(what);
  return [...new Set(v as string[])];
}

function chunks<T>(xs: T[], n = CHUNK): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < xs.length; i += n) out.push(xs.slice(i, i + n));
  return out;
}

// ---- knows ----

/** A sync's `knows` part: {reset?, add, del}. `reset` clears what the
 *  server has first (a first upload, or the list rebuilt). */
export function knowsPart(v: unknown) {
  if (!V.isObj(v)) throw V.bad("knows");
  for (const k of Object.keys(v)) if (!["reset", "add", "del"].includes(k)) throw V.bad("knows");
  if (v.reset !== undefined && typeof v.reset !== "boolean") throw V.bad("knows");
  const add = guids(v.add ?? [], KNOWS_PER_SYNC, "knows");
  const del = guids(v.del ?? [], KNOWS_PER_SYNC, "knows");
  return { reset: v.reset === true, add, del };
}

export function knowsWrites(env: Env, uid: string, k: ReturnType<typeof knowsPart>): D1PreparedStatement[] {
  const db = env.DB;
  const out: D1PreparedStatement[] = [];
  if (k.reset) out.push(db.prepare("DELETE FROM knows WHERE uid = ?").bind(uid));
  for (const c of chunks(k.del)) {
    out.push(db.prepare(`DELETE FROM knows WHERE uid = ? AND guid IN (${c.map(() => "?").join(",")})`).bind(uid, ...c));
  }
  for (const c of chunks(k.add, 49)) {
    out.push(db.prepare(`INSERT INTO knows (uid, guid) VALUES ${c.map(() => "(?, ?)").join(",")} ON CONFLICT DO NOTHING`)
      .bind(...c.flatMap((g) => [uid, g])));
  }
  return out;
}

// ---- stuck: who knows it, and its tips ----

export function stuckPart(v: unknown): string[] {
  return guids(v, STUCK_MAX, "stuck");
}

/** For each card I'm stuck on: which mutual friends have it down, and the
 *  tips mutual friends left on it (the one that helped most first). The
 *  server answers and keeps nothing about the question. */
export async function forStuck(env: Env, uid: string, stuck: string[]): Promise<Obj> {
  if (!stuck.length) return {};
  const db = env.DB;
  const mutual = `SELECT f.friend FROM friends f JOIN friends b ON b.owner = f.friend AND b.friend = ?1 WHERE f.owner = ?1`;
  const out: Record<string, { knows: string[]; tips: Obj[] }> = {};
  const at = (g: string) => (out[g] ??= { knows: [], tips: [] });
  for (const c of chunks(stuck)) {
    const inList = c.map((_, i) => `?${i + 2}`).join(",");
    const [k, t] = await db.batch([
      db.prepare(`SELECT guid, uid FROM knows WHERE guid IN (${inList}) AND uid IN (${mutual}) ORDER BY guid, uid`).bind(uid, ...c),
      db.prepare(
        `SELECT t.guid, t.uid, t.text, t.at,
                (SELECT COUNT(*) FROM tip_helped h WHERE h.guid = t.guid AND h.tip_uid = t.uid) AS n,
                EXISTS (SELECT 1 FROM tip_helped h WHERE h.guid = t.guid AND h.tip_uid = t.uid AND h.by_uid = ?1) AS mine
           FROM tips t WHERE t.guid IN (${inList}) AND t.uid IN (${mutual})
          ORDER BY t.guid, n DESC, t.at DESC`).bind(uid, ...c),
    ]);
    for (const r of k.results as { guid: string; uid: string }[]) {
      const e = at(r.guid);
      if (e.knows.length < KNOWERS_SHOWN) e.knows.push(r.uid);
    }
    for (const r of t.results as { guid: string; uid: string; text: string; at: number; mine: number }[]) {
      const e = at(r.guid);
      if (e.tips.length < TIPS_SHOWN) e.tips.push({ from: r.uid, text: r.text, at: r.at, helped: r.mine === 1 });
    }
  }
  return out;
}

/** Keep a tip on its card (called when a cheer carries a guid and a note).
 *  A new one only while I have fewer than TIPS_MAX; an old one always updates. */
export function tipWrite(env: Env, from: string, guid: string, text: string): D1PreparedStatement {
  return env.DB.prepare(
    `INSERT INTO tips (guid, uid, text, at) SELECT ?1, ?2, ?3, ?4
      WHERE (SELECT COUNT(*) FROM tips WHERE uid = ?2) < ?5 OR EXISTS (SELECT 1 FROM tips WHERE guid = ?1 AND uid = ?2)
     ON CONFLICT(guid, uid) DO UPDATE SET text = excluded.text, at = excluded.at`,
  ).bind(guid, from, text, nowSec(), TIPS_MAX);
}

/** POST /tips/helped {guid, from, helped?}: "This helped" on a mutual
 *  friend's tip. Only orders tips; nobody sees a count. */
export async function helped(req: Request, s: Session, env: Env): Promise<Response> {
  const body = await readJson(req);
  for (const k of Object.keys(body)) if (!["guid", "from", "helped"].includes(k)) throw V.bad("helped");
  if (!V.isStr(body.guid, V.GUID_MAX, 1) || !V.isStr(body.from, 128, 1)) throw V.bad("helped");
  if (body.helped !== undefined && typeof body.helped !== "boolean") throw V.bad("helped");
  const tip = await env.DB.prepare(
    `SELECT 1 FROM tips t WHERE t.guid = ?1 AND t.uid = ?2
       AND EXISTS (SELECT 1 FROM friends WHERE owner = ?3 AND friend = ?2)
       AND EXISTS (SELECT 1 FROM friends WHERE owner = ?2 AND friend = ?3)`,
  ).bind(body.guid, body.from, s.uid).first();
  if (!tip) throw new HttpError(404, "no_tip");
  await env.DB.prepare(body.helped === false
    ? "DELETE FROM tip_helped WHERE guid = ? AND tip_uid = ? AND by_uid = ?"
    : "INSERT INTO tip_helped (guid, tip_uid, by_uid) VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
  ).bind(body.guid, body.from, s.uid).run();
  return json({ ok: true });
}

// ---- the log, only mine ----

/** A sync's `log` part: {days: {date: [minutes, reviews, new, retention|null]}}. */
export function logPart(v: unknown): Record<string, (number | null)[]> {
  if (!V.isObj(v) || !V.isObj(v.days) || Object.keys(v).some((k) => k !== "days")) throw V.bad("log");
  const days = v.days;
  if (Object.keys(days).length > LOG_DAYS) throw V.bad("log");
  const out: Record<string, (number | null)[]> = {};
  for (const [d, row] of Object.entries(days)) {
    if (!V.isDate(d) || !Array.isArray(row) || row.length !== 4) throw V.bad("log");
    const [m, r, n, ret] = row;
    if (!V.isInt(m, 0, 1440) || !V.isInt(r, 0, 100000) || !V.isInt(n, 0, 100000)) throw V.bad("log");
    if (ret !== null && !(typeof ret === "number" && ret >= 0 && ret <= 100)) throw V.bad("log");
    out[d] = [m, r, n, ret === null ? null : Math.round(ret * 10) / 10];
  }
  return out;
}

/** Merged into what the server has, newest LOG_KEEP kept; written only when changed. */
export function logMerge(have: string | null, part: Record<string, (number | null)[]>): string | null {
  const cur = have ? (JSON.parse(have).days as Record<string, unknown>) : {};
  const all = { ...cur, ...part };
  const keep = Object.keys(all).sort().slice(-LOG_KEEP);
  const next = JSON.stringify({ days: Object.fromEntries(keep.map((d) => [d, all[d]])) });
  return next === have ? null : next;
}

/** GET /log: my log, for the site. */
export async function getLog(s: Session, env: Env): Promise<Response> {
  const row = await env.DB.prepare("SELECT json FROM logs WHERE uid = ?").bind(s.uid).first<string>("json");
  return json(row ? JSON.parse(row) : { days: {} });
}
