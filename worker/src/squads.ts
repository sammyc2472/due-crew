// Squads: private boards behind an invite code. The id derives from the
// code (sha1, as in 2.x), so holding the code is the invite and nothing is
// listed. Members read the squad; only a join makes a member; the founder
// locks, blocks, removes and hands over.

import type { Session } from "./auth";
import * as B from "./bingo";
import { limitOrThrow } from "./limits";
import { checkUid, nameOf } from "./social";
import * as V from "./validate";
import { Env, HttpError, json, nowSec, readJson } from "./util";

export const SQUAD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";  // no 0/O/1/I
export const SQUAD_CODE_LEN = 8;
const BANS_MAX = 200;
const MEMBERS_MAX = 500;  // a squad's board is one query: it stays bounded

export function normalizeCode(code: string): string {
  return [...code.toUpperCase()].filter((c) => SQUAD_ALPHABET.includes(c)).join("");
}

export async function squadId(code: string): Promise<string> {
  const buf = await crypto.subtle.digest("SHA-1", new TextEncoder().encode(`due-crew-squad:${normalizeCode(code)}`));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, 24);
}

/** The squad a code opens, or null: a new code (the admin's, in
 *  squad_codes) first, else the squad whose id came from this code, unless
 *  it has had a new code since. */
export async function idForCode(env: Env, code: string): Promise<string | null> {
  const h = await squadId(code);
  const alias = await env.DB.prepare("SELECT squad FROM squad_codes WHERE code_id = ?").bind(h).first<string>("squad");
  if (alias) return alias;
  const sq = await env.DB.prepare("SELECT code_id FROM squads WHERE id = ?").bind(h).first<{ code_id: string | null }>();
  return sq && !sq.code_id ? h : null;
}

/** Whether a code is this squad's live one. */
async function codeIsLive(env: Env, id: string, code: string): Promise<boolean> {
  const sq = await env.DB.prepare("SELECT code_id FROM squads WHERE id = ?").bind(id).first<{ code_id: string | null }>();
  return !!sq && (await squadId(code)) === (sq.code_id || id);
}

export function drawCode(): string {
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
  await limitOrThrow(env, `squadnew:${s.uid}`, 10, 86400);
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
  const id = await idForCode(env, code);
  if (!id) throw new HttpError(404, "no_squad");
  const sq = await getSquad(env, id);
  // 3.7.1, D5: the founder's name comes with the code (/users/{uid} is for
  // people I'm connected to)
  return json({ ...info(sq, code), founderName: (await nameOf(env, sq.founder))?.name ?? "" });
}

/** POST /squads/{id}/join: the only way in. The door must be open and I
 *  mustn't be blocked. Joining twice is a no-op. */
export async function join(req: Request, s: Session, env: Env, [id]: string[]): Promise<Response> {
  // The code is what only a join sends, and it must be this squad's (since
  // 3.6.2, with MIN_CLIENT 3.1.0: 3.0.x add-ons sent none, and an id alone,
  // which members and past members know, let anyone back in).
  const body = await readJson(req);
  const code = typeof body.code === "string" ? body.code : null;
  if (code === null || !(await codeIsLive(env, id, code))) throw new HttpError(403, "wrong_code");
  return joinById(s, env, id);
}

/** The join itself, once whoever called has shown the code (or is 3.0.x). */
async function joinById(s: Session, env: Env, id: string): Promise<Response> {
  const sq = await getSquad(env, id);
  if (await isMember(env, id, s.uid)) return json(info(sq));
  if (await env.DB.prepare("SELECT 1 FROM bans WHERE squad = ? AND uid = ?").bind(id, s.uid).first()) {
    throw new HttpError(403, "blocked");
  }
  if (sq.open !== 1) throw new HttpError(403, "locked");
  const n = await env.DB.prepare("SELECT COUNT(*) AS n FROM members WHERE squad = ?").bind(id).first<number>("n");
  if ((n ?? 0) >= MEMBERS_MAX) throw new HttpError(403, "full");  // the add-on says the door is shut
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
  await limitOrThrow(env, `squadrestore:${s.uid}`, 30, 86400);  // a 2.x computer's squads, once; not a way round create's limit
  // a code the admin replaced opens nothing, and isn't made again
  let id = await idForCode(env, code);
  const exists = !!id;
  if (!id) {
    id = await squadId(code);
    if (await env.DB.prepare("SELECT 1 FROM squads WHERE id = ?").bind(id).first()) throw new HttpError(403, "wrong_code");
  }
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
  const r = await joinById(s, env, id);  // restore demanded the code
  if (r.status !== 200) return r;
  return json({ ...(await r.json() as object), code });
}

/** GET /squads/{id}[?wk=2026-W40]: the squad and every member's row, one
 *  query. Members only. 3.6: with wk, the week's bingo card too. */
export async function fetchSquad(req: Request, s: Session, env: Env, [id]: string[]): Promise<Response> {
  const sq = await getSquad(env, id);
  if (!(await isMember(env, id, s.uid))) throw new HttpError(403, "not_member");
  const [rows, bans] = await env.DB.batch([
    env.DB.prepare(
      `SELECT uid, name, emoji, day, reviews, study_time_ms, accuracy, streak, week, new_cards,
              joined_at, updated_at, play FROM members WHERE squad = ? ORDER BY joined_at, uid`).bind(id),
    env.DB.prepare("SELECT uid FROM bans WHERE squad = ?").bind(id),
  ]);
  const wk = new URL(req.url).searchParams.get("wk");
  return json({
    ...info(sq),
    banned: sq.founder === s.uid ? (bans.results as any[]).map((b) => b.uid) : [],
    rows: (rows.results as any[]).map((m) => ({
      uid: m.uid, name: m.name, emoji: m.emoji || "", day: m.day || "",
      reviews: m.reviews, studyTimeMs: m.study_time_ms, accuracy: m.accuracy, streak: m.streak,
      week: m.week, newCards: m.new_cards,
      joined: new Date(m.joined_at * 1000).toISOString().slice(0, 10), play: m.play ? JSON.parse(m.play) : null,
    })),
    ...(B.askable(wk) ? await bingoFor(env, wk, rows.results as any[]) : {}),
  });
}

/** The week's card, and (for the site, which doesn't work squares out)
 *  where this squad stands on it: the same evaluate the add-on runs. */
async function bingoFor(env: Env, wk: string, rows: any[]) {
  const card = await B.cardFor(env, wk);
  const ev = B.evaluate(card, rows.map((m) => ({ uid: m.uid, emoji: m.emoji, day: m.day,
    joined: new Date(m.joined_at * 1000).toISOString().slice(0, 10), play: m.play ? JSON.parse(m.play) : null })));
  return { bingo: card, bingoEv: { squares: ev.squares.map((q) => ({ done: q.done })), middle: { done: ev.middle.done, have: ev.middle.have, goal: ev.middle.goal },
    lines: ev.lines, closest: B.closest(card, ev) } };
}

/** PUT /squads/{id}/row: my numbers, as an update. Never a join. */
export async function putRow(req: Request, s: Session, env: Env, [id]: string[]): Promise<Response> {
  const r = V.memberRow(await readJson(req));
  const res = await env.DB.prepare(
    `UPDATE members SET name = COALESCE(?, name), day = ?, reviews = ?, study_time_ms = ?, accuracy = ?,
       streak = ?, week = ?, emoji = ?, new_cards = ?, play = ?, updated_at = ? WHERE squad = ? AND uid = ?`,
  ).bind(r.name, r.day, r.reviews, r.study_time_ms, r.accuracy, r.streak, r.week, r.emoji, r.new_cards,
         r.play, nowSec(), id, s.uid).run();
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

/** GET /squads/mine: the squads I'm in, for the site's plan settings (3.1). */
export async function mine(s: Session, env: Env): Promise<Response> {
  const rows = await env.DB.prepare(
    "SELECT q.id, q.name, q.founder FROM members m JOIN squads q ON q.id = m.squad WHERE m.uid = ? ORDER BY q.name",
  ).bind(s.uid).all<{ id: string; name: string; founder: string }>();
  return json({ squads: rows.results });
}
