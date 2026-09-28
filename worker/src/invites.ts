// 3.4.1: one-time invites (duecrew.com/i/CODE). Copy invite makes one; the
// first person to redeem it within 14 days and the one who made it are crew
// at once, both edges, with no Add back: sending the link was the inviter's
// yes, for one person. Anyone after that (a link in a group chat), or later,
// gets what the friend code gives: add, then the inviter's Add back. Stored
// as a hash, kept a year for that. A friend code (six) in the same link
// works as it always has.

import type { Session } from "./auth";
import { limitOrThrow } from "./limits";
import { CODE_ALPHABET, added, mutual, nameOf } from "./social";
import { Env, HttpError, clientIp, json, nowSec, sha256Hex } from "./util";

export const INVITE_LEN = 10;
export const INVITE_TTL = 14 * 86400;
const INVITES_PER_DAY = 20;
const INVITE_RE = /^[A-Z0-9]{10}$/;
const FRIEND_RE = /^[A-Z0-9]{6}$/;

function draw(): string {
  let out = "";
  while (out.length < INVITE_LEN) {
    for (const b of crypto.getRandomValues(new Uint8Array(INVITE_LEN))) {
      if (b < 252 && out.length < INVITE_LEN) out += CODE_ALPHABET[b % 36];
    }
  }
  return out;
}

const hashOf = (code: string) => sha256Hex(`invite:${code}`);

/** POST /invites: a new one-time invite. The code is returned once. */
export async function create(s: Session, env: Env): Promise<Response> {
  await limitOrThrow(env, `invite:${s.uid}`, INVITES_PER_DAY, 86400);
  const code = draw();
  const expires = nowSec() + INVITE_TTL;
  await env.DB.prepare("INSERT INTO invites (hash, uid, expires_at) VALUES (?, ?, ?)")
    .bind(await hashOf(code), s.uid, expires).run();
  return json({ code, expiresAt: expires });
}

/** GET /invites/{code}: the invite page, signed out. Whose it is (a name
 *  and an emoji, as anyone may see for a uid) and whether it still works.
 *  A friend code answers too. Guessing stays slow: 300 an hour an address. */
export async function peek(req: Request, env: Env, [raw]: string[]): Promise<Response> {
  const code = raw.toUpperCase();
  await limitOrThrow(env, `invpeek:ip:${clientIp(req)}`, 300, 3600);
  if (FRIEND_RE.test(code)) {
    const uid = await env.DB.prepare("SELECT uid FROM codes WHERE code = ?").bind(code).first<string>("uid");
    const u = uid ? await nameOf(env, uid) : null;
    if (!u) throw new HttpError(404, "no_match");
    return json({ kind: "code", ...u, state: "ok" });
  }
  if (!INVITE_RE.test(code)) throw new HttpError(404, "no_match");
  const row = await env.DB.prepare("SELECT uid, expires_at, used_by FROM invites WHERE hash = ?")
    .bind(await hashOf(code)).first<{ uid: string; expires_at: number; used_by: string | null }>();
  const u = row ? await nameOf(env, row.uid) : null;
  if (!row || !u) throw new HttpError(404, "no_match");
  // used or expired, it still adds (they add back): the page says which
  const state = row.used_by ? "used" : row.expires_at <= nowSec() ? "expired" : "ok";
  return json({ kind: "invite", ...u, state });
}

/** POST /invites/{code}/redeem: I'm crew with whoever made it. Only the
 *  first redeem, within 14 days, makes both edges. After that (someone
 *  else used it, or it's old) it works as their friend code: I add them,
 *  they're knocked, and Add back is theirs to click. The same person
 *  asking again is told where things stand (a removal stays a removal). */
export async function redeem(s: Session, env: Env, [raw]: string[]): Promise<Response> {
  await limitOrThrow(env, `addcode:${s.uid}`, 30, 3600);  // the same guesses as adding by code
  const code = raw.toUpperCase();
  if (!INVITE_RE.test(code)) throw new HttpError(404, "no_match");
  const hash = await hashOf(code);
  const row = await env.DB.prepare("SELECT uid, expires_at, used_by FROM invites WHERE hash = ?")
    .bind(hash).first<{ uid: string; expires_at: number; used_by: string | null }>();
  const u = row ? await nameOf(env, row.uid) : null;
  if (!row || !u) throw new HttpError(404, "no_match");
  if (row.uid === s.uid) throw new HttpError(400, "own_code");
  const now = nowSec();
  if (row.used_by === s.uid) {
    return json({ uid: row.uid, ...u, mutual: await mutual(env, s.uid, row.uid), knocked: false });
  }
  if (!row.used_by && row.expires_at > now) {
    // the claim and both edges in one transaction; the claim's WHERE makes a
    // race lose cleanly (its edges insert nothing new), and the loser adds below
    const [claim] = await env.DB.batch([
      env.DB.prepare("UPDATE invites SET used_by = ?1, used_at = ?2 WHERE hash = ?3 AND used_by IS NULL AND expires_at > ?2")
        .bind(s.uid, now, hash),
      env.DB.prepare(
        `INSERT INTO friends (owner, friend, at) SELECT ?1, ?2, ?3
         WHERE EXISTS (SELECT 1 FROM invites WHERE hash = ?4 AND used_by = ?1)
         ON CONFLICT DO NOTHING`).bind(s.uid, row.uid, now, hash),
      env.DB.prepare(
        `INSERT INTO friends (owner, friend, at) SELECT ?2, ?1, ?3
         WHERE EXISTS (SELECT 1 FROM invites WHERE hash = ?4 AND used_by = ?1)
         ON CONFLICT DO NOTHING`).bind(s.uid, row.uid, now, hash),
      env.DB.prepare(
        `DELETE FROM knocks WHERE ((to_uid = ?1 AND from_uid = ?2) OR (to_uid = ?2 AND from_uid = ?1))
         AND EXISTS (SELECT 1 FROM invites WHERE hash = ?3 AND used_by = ?1)`).bind(s.uid, row.uid, hash),
    ]);
    if (claim.meta.changes) return json({ uid: row.uid, ...u, mutual: true, knocked: false });
  }
  // used by someone else, or past 14 days: as their friend code
  const already = await added(env, s.uid, row.uid);
  if (!already) {
    await env.DB.prepare("INSERT INTO friends (owner, friend, at) VALUES (?, ?, ?) ON CONFLICT DO NOTHING")
      .bind(s.uid, row.uid, now).run();
  }
  const isMutual = await mutual(env, s.uid, row.uid);
  if (!isMutual) {
    await env.DB.prepare(
      `INSERT INTO knocks (to_uid, from_uid, squad, at) VALUES (?, ?, NULL, ?)
       ON CONFLICT(to_uid, from_uid) DO UPDATE SET squad = NULL, at = excluded.at`,
    ).bind(row.uid, s.uid, now).run();
  }
  return json({ uid: row.uid, ...u, mutual: isMutual, knocked: !isMutual });
}
