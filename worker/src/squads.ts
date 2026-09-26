// Squads: private boards behind an invite code. The id derives from the
// code (sha1, as in 2.x), so holding the code is the invite and nothing is
// listed. Members read the squad; only a join makes a member; the founder
// locks, blocks, removes and hands over.

import type { Session } from "./auth";
import { limitOrThrow } from "./limits";
import { checkUid, nameOf } from "./social";
import * as V from "./validate";
import { Env, HttpError, json, nowSec, readJson } from "./util";

export const SQUAD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";  // no 0/O/1/I
export const SQUAD_CODE_LEN = 8;
const BANS_MAX = 200;

export function normalizeCode(code: string): string {
  return [...code.toUpperCase()].filter((c) => SQUAD_ALPHABET.includes(c)).join("");
}

export async function squadId(code: string): Promise<string> {
  const buf = await crypto.subtle.digest("SHA-1", new TextEncoder().encode(`due-crew-squad:${normalizeCode(code)}`));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, 24);
}

function drawCode(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(SQUAD_CODE_LEN));
  return [...bytes].map((b) => SQUAD_ALPHABET[b % 32]).join("");  // 256 = 8 x 32: even
}

type Squad = { id: string; name: string; founder: string; open: number };

async function getSquad(env: Env, id: string): Promise<Squad> {
  const sq = await env.DB.prepare("SELECT id, name, founder, open FROM squads WHERE id = ?").bind(id).first<Squad>();
  if (!sq) throw new HttpError(404, "no_squad");
  return sq;
}

async function isMember(env: Env, id: string, uid: string): Promise<boolean> {
  return !!(await env.DB.prepare("SELECT 1 FROM members WHERE squad = ? AND uid = ?").bind(id, uid).first());
}

async function founderOnly(env: Env, id: string, s: Session): Promise<Squad> {
  const sq = await getSquad(env, id);
  if (sq.founder !== s.uid) throw new HttpError(403, "not_founder");
  return sq;
}

const info = (sq: Squad, code?: string) =>
  ({ id: sq.id, ...(code ? { code } : {}), name: sq.name, founder: sq.founder, open: sq.open === 1 });

async function myName(env: Env, uid: string): Promise<string> {
  return (await nameOf(env, uid))?.name ?? "?";
}

function joinStmt(env: Env, id: string, uid: string, name: string) {
  return env.DB.prepare(
    "INSERT INTO members (squad, uid, name, joined_at) VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING",
  ).bind(id, uid, name, nowSec());
}

/** POST /squads {name}: a new squad, its code, and me as founder and member. */
export async function create(req: Request, s: Session, env: Env): Promise<Response> {
  const body = await readJson(req);
  for (const k of Object.keys(body)) if (k !== "name") throw V.bad("squad");  // founder is always me
  const name = V.squadName(body.name);
  const me = await myName(env, s.uid);
  for (let i = 0; i < 3; i++) {
    const code = drawCode();
    const id = await squadId(code);
    const r = await env.DB.prepare(
      "INSERT INTO squads (id, name, founder, open, created_at) VALUES (?, ?, ?, 1, ?) ON CONFLICT DO NOTHING",
    ).bind(id, name, s.uid, nowSec()).run();
    if (!r.meta.changes) continue;
    await joinStmt(env, id, s.uid, me).run();
    return json({ id, code, name, founder: s.uid, open: true });
  }
  throw new HttpError(503, "try_again");
}

/** GET /squads/peek?code=: the join preview. Anyone signed in who holds
 *  the code; nothing else about the squad. */
export async function peek(req: Request, s: Session, env: Env): Promise<Response> {
  await limitOrThrow(env, `peek:${s.uid}`, 60, 3600);
  const code = normalizeCode(new URL(req.url).searchParams.get("code") || "");
  if (code.length !== SQUAD_CODE_LEN) throw new HttpError(404, "no_squad");
  return json(info(await getSquad(env, await squadId(code)), code));
}

/** POST /squads/{id}/join: the only way in. The door must be open and I
 *  mustn't be blocked. Joining twice is a no-op. */
export async function join(s: Session, env: Env, [id]: string[]): Promise<Response> {
  const sq = await getSquad(env, id);
  if (await isMember(env, id, s.uid)) return json(info(sq));
  if (await env.DB.prepare("SELECT 1 FROM bans WHERE squad = ? AND uid = ?").bind(id, s.uid).first()) {
    throw new HttpError(403, "blocked");
  }
  if (sq.open !== 1) throw new HttpError(403, "locked");
  await joinStmt(env, id, s.uid, await myName(env, s.uid)).run();
  return json(info(sq));
}

/** POST /squads/restore {code, name, founder}: 3.0's first sync brings back
 *  a squad from 2.x, which the client knows by its code. If someone got
 *  there first it's a join; if not, the squad comes back with the founder
 *  its members remember, and me in it. Block lists don't come back. */
export async function restore(req: Request, s: Session, env: Env): Promise<Response> {
  const body = await readJson(req);
  const code = normalizeCode(typeof body.code === "string" ? body.code : "");
  if (code.length !== SQUAD_CODE_LEN) throw V.bad("code");
  const name = V.squadName(body.name);
  const id = await squadId(code);
  const exists = await env.DB.prepare("SELECT 1 FROM squads WHERE id = ?").bind(id).first();
  if (!exists) {
    let founder = s.uid;
    if (typeof body.founder === "string" && body.founder !== s.uid
        && await env.DB.prepare("SELECT 1 FROM users WHERE uid = ?").bind(body.founder).first()) {
      founder = body.founder;
    }
    await env.DB.prepare(
      "INSERT INTO squads (id, name, founder, open, created_at) VALUES (?, ?, ?, 1, ?) ON CONFLICT DO NOTHING",
    ).bind(id, name, founder, nowSec()).run();
  }
  const r = await join(s, env, [id]);
  if (r.status !== 200) return r;
  return json({ ...(await r.json() as object), code });
}

/** GET /squads/{id}: the squad and every member's row, one query. Members only. */
export async function fetchSquad(s: Session, env: Env, [id]: string[]): Promise<Response> {
  const sq = await getSquad(env, id);
  if (!(await isMember(env, id, s.uid))) throw new HttpError(403, "not_member");
  const [rows, bans] = await env.DB.batch([
    env.DB.prepare(
      `SELECT uid, name, emoji, day, reviews, study_time_ms, accuracy, streak, week, new_cards,
              joined_at, updated_at FROM members WHERE squad = ? ORDER BY joined_at, uid`).bind(id),
    env.DB.prepare("SELECT uid FROM bans WHERE squad = ?").bind(id),
  ]);
  return json({
    ...info(sq),
    banned: sq.founder === s.uid ? (bans.results as any[]).map((b) => b.uid) : [],
    rows: (rows.results as any[]).map((m) => ({
      uid: m.uid, name: m.name, emoji: m.emoji || "", day: m.day || "",
      reviews: m.reviews, studyTimeMs: m.study_time_ms, accuracy: m.accuracy, streak: m.streak,
      week: m.week, newCards: m.new_cards,
    })),
  });
}

/** PUT /squads/{id}/row: my numbers, as an update. Never a join. */
export async function putRow(req: Request, s: Session, env: Env, [id]: string[]): Promise<Response> {
  const r = V.memberRow(await readJson(req));
  const res = await env.DB.prepare(
    `UPDATE members SET name = COALESCE(?, name), day = ?, reviews = ?, study_time_ms = ?, accuracy = ?,
       streak = ?, week = ?, emoji = ?, new_cards = ?, updated_at = ? WHERE squad = ? AND uid = ?`,
  ).bind(r.name, r.day, r.reviews, r.study_time_ms, r.accuracy, r.streak, r.week, r.emoji, r.new_cards,
         nowSec(), id, s.uid).run();
  if (!res.meta.changes) throw new HttpError(403, "not_member");
  return json({ ok: true });
}

/** DELETE /squads/{id}/members/{uid}: leave, or (founder) remove. */
export async function removeMember(s: Session, env: Env, [id, uid]: string[]): Promise<Response> {
  checkUid(uid);
  if (uid !== s.uid) await founderOnly(env, id, s);
  else await getSquad(env, id);
  await env.DB.prepare("DELETE FROM members WHERE squad = ? AND uid = ?").bind(id, uid).run();
  return json({ ok: true });
}

/** POST /squads/{id}/block/{uid}: founder only. Out, and can't rejoin. */
export async function block(s: Session, env: Env, [id, uid]: string[]): Promise<Response> {
  checkUid(uid);
  await founderOnly(env, id, s);
  if (uid === s.uid) throw new HttpError(400, "self");
  const n = await env.DB.prepare("SELECT COUNT(*) AS n FROM bans WHERE squad = ?").bind(id).first<number>("n");
  if ((n ?? 0) >= BANS_MAX) throw new HttpError(409, "too_many_blocked");
  await env.DB.batch([
    env.DB.prepare("INSERT INTO bans (squad, uid) VALUES (?, ?) ON CONFLICT DO NOTHING").bind(id, uid),
    env.DB.prepare("DELETE FROM members WHERE squad = ? AND uid = ?").bind(id, uid),
  ]);
  return json({ ok: true });
}

/** PATCH /squads/{id} {open?, founder?}: founder only. The squad passes
 *  only to someone already in it. */
export async function patch(req: Request, s: Session, env: Env, [id]: string[]): Promise<Response> {
  await founderOnly(env, id, s);
  const body = await readJson(req);
  for (const k of Object.keys(body)) if (!["open", "founder"].includes(k)) throw V.bad("squad");
  const stmts: D1PreparedStatement[] = [];
  if ("open" in body) {
    if (typeof body.open !== "boolean") throw V.bad("open");
    stmts.push(env.DB.prepare("UPDATE squads SET open = ? WHERE id = ?").bind(body.open ? 1 : 0, id));
  }
  if ("founder" in body) {
    if (typeof body.founder !== "string" || !(await isMember(env, id, body.founder))) {
      throw new HttpError(403, "not_member");
    }
    stmts.push(env.DB.prepare("UPDATE squads SET founder = ? WHERE id = ?").bind(body.founder, id));
  }
  if (stmts.length) await env.DB.batch(stmts);
  return json(info(await getSquad(env, id)));
}
