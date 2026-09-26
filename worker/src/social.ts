// Friends, codes, cheers, knocks, and what anyone may see of anyone.
//
// Consent, as firestore.rules had it: a friendship is two edges, one per
// person (friends(owner, friend)). My numbers go only to people I added
// who added me back. A cheer lands only if its recipient added the sender.
// A knock needs a squad in common or the recipient's own code.

import type { Session } from "./auth";
import { limitOrThrow } from "./limits";
import * as V from "./validate";
import { Env, HttpError, json, nowSec, readJson } from "./util";

export const CODE_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
export const CODE_LEN = 6;
const CODE_RE = /^[A-Z0-9]{6}$/;
const UID_RE = /^[A-Za-z0-9_-]{1,128}$/;

export function checkUid(uid: string): string {
  if (!UID_RE.test(uid)) throw new HttpError(404, "no_user");
  return uid;
}

/** Did `owner` add `other`? */
export async function added(env: Env, owner: string, other: string): Promise<boolean> {
  return !!(await env.DB.prepare("SELECT 1 FROM friends WHERE owner = ? AND friend = ?")
    .bind(owner, other).first());
}

export async function mutual(env: Env, a: string, b: string): Promise<boolean> {
  const row = await env.DB.prepare(
    `SELECT COUNT(*) AS n FROM friends WHERE (owner = ?1 AND friend = ?2) OR (owner = ?2 AND friend = ?1)`,
  ).bind(a, b).first<number>("n");
  return row === 2;
}

export async function nameOf(env: Env, uid: string): Promise<{ name: string; emoji: string } | null> {
  const u = await env.DB.prepare("SELECT name, emoji FROM users WHERE uid = ?").bind(uid)
    .first<{ name: string | null; emoji: string | null }>();
  return u ? { name: u.name || "?", emoji: u.emoji || "" } : null;
}

/** GET /users/{uid}: anyone signed in gets a name and an emoji, nothing
 *  more. (A Firestore profile was readable whole by anyone with the uid.) */
export async function getUser(s: Session, env: Env, [uid]: string[]): Promise<Response> {
  const u = await nameOf(env, checkUid(uid));
  if (!u) throw new HttpError(404, "no_user");
  return json({ uid, ...u });
}

// ---- friends ----

async function addEdge(env: Env, me: string, fid: string) {
  await env.DB.prepare("INSERT INTO friends (owner, friend, at) VALUES (?, ?, ?) ON CONFLICT DO NOTHING")
    .bind(me, fid, nowSec()).run();
}

/** PUT /friends/{uid}: add someone by uid (add back, a knock's Add). */
export async function putFriend(req: Request, s: Session, env: Env, [fid]: string[]): Promise<Response> {
  checkUid(fid);
  const text = await req.text();
  if (text.trim() && text.trim() !== "{}") throw V.bad("friend");  // an edge carries nothing I set
  if (fid === s.uid) throw new HttpError(400, "self");
  const u = await nameOf(env, fid);
  if (!u) throw new HttpError(404, "no_user");
  await addEdge(env, s.uid, fid);
  await env.DB.prepare("DELETE FROM knocks WHERE to_uid = ? AND from_uid = ?").bind(s.uid, fid).run();
  return json({ uid: fid, ...u, mutual: await mutual(env, s.uid, fid) });
}

/** PUT /friends {ids}: 3.0's first sync re-adds the crew by uid, once.
 *  Add-only; unknown uids are skipped. */
export async function restoreFriends(req: Request, s: Session, env: Env): Promise<Response> {
  const body = await readJson(req);
  const ids = body.ids;
  if (!Array.isArray(ids) || ids.length > 500) throw V.bad("ids");
  const want = [...new Set(ids.filter((x): x is string => typeof x === "string" && UID_RE.test(x) && x !== s.uid))];
  if (!want.length) return json({ added: [] });
  const found = await env.DB.prepare(
    `SELECT uid FROM users WHERE uid IN (${want.map(() => "?").join(",")})`,
  ).bind(...want).all<{ uid: string }>();
  const ok = found.results.map((r) => r.uid);
  const now = nowSec();
  if (ok.length) {
    // each one I add back who hasn't added me gets a knock, so a computer
    // that forgot its list sees "added you" and adds back in one click; one
    // who already added me is crew now, and their knock to me is done
    await env.DB.batch(ok.flatMap((fid) => [
      env.DB.prepare("INSERT INTO friends (owner, friend, at) VALUES (?, ?, ?) ON CONFLICT DO NOTHING").bind(s.uid, fid, now),
      env.DB.prepare(
        `INSERT INTO knocks (to_uid, from_uid, squad, at) SELECT ?1, ?2, NULL, ?3
         WHERE NOT EXISTS (SELECT 1 FROM friends WHERE owner = ?1 AND friend = ?2)
         ON CONFLICT(to_uid, from_uid) DO NOTHING`).bind(fid, s.uid, now),
      env.DB.prepare(
        `DELETE FROM knocks WHERE to_uid = ?2 AND from_uid = ?1
         AND EXISTS (SELECT 1 FROM friends WHERE owner = ?1 AND friend = ?2)`).bind(fid, s.uid),
    ]));
  }
  return json({ added: ok.sort() });
}

/** DELETE /friends/{uid}: my edge goes; so do their reads, at once. */
export async function deleteFriend(s: Session, env: Env, [fid]: string[]): Promise<Response> {
  await env.DB.prepare("DELETE FROM friends WHERE owner = ? AND friend = ?").bind(s.uid, checkUid(fid)).run();
  return json({ ok: true });
}

/** GET /friends: the Friends dialog. My code, the people I added (with
 *  whether they added me back), and my knocks. Reads only: nothing is
 *  consumed, unlike /board's cheers. */
export async function getFriends(s: Session, env: Env): Promise<Response> {
  const [me, friends] = await env.DB.batch([
    env.DB.prepare("SELECT code FROM users WHERE uid = ?").bind(s.uid),
    env.DB.prepare(
      `SELECT f.friend AS uid, u.name, u.emoji,
              EXISTS (SELECT 1 FROM friends b WHERE b.owner = f.friend AND b.friend = ?1) AS mutual
       FROM friends f JOIN users u ON u.uid = f.friend WHERE f.owner = ?1 ORDER BY f.at, f.friend`).bind(s.uid),
  ]);
  return json({
    code: (me.results[0] as any)?.code || "",
    friends: (friends.results as any[]).map((f) => ({ uid: f.uid, name: f.name || "?", emoji: f.emoji || "", mutual: !!f.mutual })),
    knocks: await listKnocks(env, s.uid),
  });
}

// ---- codes ----

function drawCode(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(CODE_LEN));
  // 36 symbols: reject bytes past the last whole multiple so every one is even
  let out = "";
  for (let i = 0; out.length < CODE_LEN; i++) {
    const b = i < bytes.length ? bytes[i] : crypto.getRandomValues(new Uint8Array(1))[0];
    if (b < 252) out += CODE_ALPHABET[b % 36];
  }
  return out;
}

/** POST /codes [{code}]: a new friend code for me, and the old one stops
 *  working. `code` asks for a particular one: 3.0's first sync keeps the
 *  code a person already handed out, when it's free. */
export async function newCode(req: Request, s: Session, env: Env): Promise<Response> {
  const text = await req.text();
  let want: string | null = null;
  if (text) {
    let body: unknown;
    try {
      body = JSON.parse(text);
    } catch {
      throw new HttpError(400, "bad_json");
    }
    if (V.isObj(body) && body.code !== undefined) {
      if (typeof body.code !== "string" || !CODE_RE.test(body.code)) throw V.bad("code");
      want = body.code;
    }
  }
  const old = await env.DB.prepare("SELECT code FROM users WHERE uid = ?").bind(s.uid).first<string>("code");
  if (want && want === old) return json({ code: old });
  for (let i = 0; i < 5; i++) {
    const code = want && i === 0 ? want : drawCode();
    const r = await env.DB.prepare("INSERT INTO codes (code, uid) VALUES (?, ?) ON CONFLICT DO NOTHING")
      .bind(code, s.uid).run();
    if (!r.meta.changes) continue;  // someone's: another draw
    await env.DB.batch([
      env.DB.prepare("UPDATE users SET code = ? WHERE uid = ?").bind(code, s.uid),
      env.DB.prepare("DELETE FROM codes WHERE uid = ? AND code != ?").bind(s.uid, code),
    ]);
    return json({ code });
  }
  throw new HttpError(503, "try_again");
}

/** POST /codes/{code}/add: add the code's owner, and knock them with it so
 *  their board offers Add back. */
export async function addByCode(s: Session, env: Env, [code]: string[]): Promise<Response> {
  await limitOrThrow(env, `addcode:${s.uid}`, 30, 3600);
  code = code.toUpperCase();
  const owner = CODE_RE.test(code)
    ? await env.DB.prepare("SELECT uid FROM codes WHERE code = ?").bind(code).first<string>("uid")
    : null;
  if (!owner) throw new HttpError(404, "no_match");
  if (owner === s.uid) throw new HttpError(400, "own_code");
  if (await added(env, s.uid, owner)) throw new HttpError(409, "already");
  await addEdge(env, s.uid, owner);
  const isMutual = await mutual(env, s.uid, owner);
  if (!isMutual) {
    await env.DB.prepare(
      `INSERT INTO knocks (to_uid, from_uid, squad, at) VALUES (?, ?, NULL, ?)
       ON CONFLICT(to_uid, from_uid) DO UPDATE SET squad = NULL, at = excluded.at`,
    ).bind(owner, s.uid, nowSec()).run();
  }
  const u = (await nameOf(env, owner))!;
  return json({ uid: owner, ...u, mutual: isMutual, knocked: !isMutual });
}

// ---- cheers ----

/** POST /cheers/{to}: one cheer per sender, overwriting the last one, and
 *  only to someone who added me. */
export async function sendCheer(req: Request, s: Session, env: Env, [to]: string[]): Promise<Response> {
  checkUid(to);
  const c = V.cheer(await readJson(req));
  if (!(await added(env, to, s.uid))) throw new HttpError(403, "not_friends");
  await env.DB.prepare(
    `INSERT INTO cheers (to_uid, from_uid, emoji, note, luck, guid, at) VALUES (?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT(to_uid, from_uid) DO UPDATE SET emoji = excluded.emoji, note = excluded.note,
       luck = excluded.luck, guid = excluded.guid, at = excluded.at`,
  ).bind(to, s.uid, c.emoji, c.note, c.luck, c.guid, nowSec()).run();
  return json({ ok: true });
}

// ---- knocks ----

/** POST /knocks/{to} {squad}: "added you", between two members of a squad. */
export async function sendKnock(req: Request, s: Session, env: Env, [to]: string[]): Promise<Response> {
  checkUid(to);
  const body = await readJson(req);
  for (const k of Object.keys(body)) if (k !== "squad") throw V.bad("knock");  // sender and names are mine
  if (!V.isStr(body.squad, 40, 1)) throw V.bad("squad");
  const both = await env.DB.prepare("SELECT COUNT(*) AS n FROM members WHERE squad = ? AND uid IN (?, ?)")
    .bind(body.squad, s.uid, to).first<number>("n");
  if (to === s.uid || both !== 2) throw new HttpError(403, "no_squad_in_common");
  await env.DB.prepare(
    `INSERT INTO knocks (to_uid, from_uid, squad, at) VALUES (?, ?, ?, ?)
     ON CONFLICT(to_uid, from_uid) DO UPDATE SET squad = excluded.squad, at = excluded.at`,
  ).bind(to, s.uid, body.squad, nowSec()).run();
  return json({ ok: true });
}

export async function listKnocks(env: Env, uid: string) {
  const rows = await env.DB.prepare(
    `SELECT k.from_uid, k.squad, k.at, u.name, u.emoji FROM knocks k JOIN users u ON u.uid = k.from_uid
     WHERE k.to_uid = ? ORDER BY k.at DESC LIMIT 50`,
  ).bind(uid).all<{ from_uid: string; squad: string | null; at: number; name: string | null; emoji: string | null }>();
  // names from the profile, never from the knock: senders can't spoof
  return rows.results.map((r) => ({ from: r.from_uid, name: r.name || "?", emoji: r.emoji || "", squad: r.squad || "" }));
}

export async function getKnocks(s: Session, env: Env): Promise<Response> {
  return json({ knocks: await listKnocks(env, s.uid) });
}

export async function deleteKnock(s: Session, env: Env, [from]: string[]): Promise<Response> {
  await env.DB.prepare("DELETE FROM knocks WHERE to_uid = ? AND from_uid = ?").bind(s.uid, checkUid(from)).run();
  return json({ ok: true });
}
