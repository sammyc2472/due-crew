// Sign-in by emailed code, our own sessions, sign-out, account deletion,
// and the one-shot identity import from Firebase Auth.
//
// Never log emails, codes or tokens. Codes and tokens are stored hashed.

import { hit, limitOrThrow, peek } from "./limits";
import { sendCode } from "./mail";
import {
  Env, HttpError, clientIp, json, newCode, newToken, normEmail, nowSec, readJson,
  sha256Hex, timingSafeEqual, ulid,
} from "./util";

export const CODE_TTL = 10 * 60;            // a code lives ten minutes
export const CODE_ATTEMPTS = 5;             // wrong tries before a code dies
export const LIMIT_WINDOW = 60 * 60;        // rate limits count per hour
export const CODES_PER_EMAIL = 5;
export const CODES_PER_IP = 20;
export const FAILS_TO_LOCK = 6;             // the sixth wrong code locks the email
export const VERIFIES_PER_IP = 60;
export const SESSION_IDLE = 180 * 86400;    // idle sessions end after 180 days
const TOUCH_EVERY = 86400;                  // last_used is written at most daily

const codeHash = (email: string, code: string) => sha256Hex(`otp:${email}:${code}`);
const emailKey = async (kind: string, email: string) => `${kind}:e:${(await sha256Hex(email)).slice(0, 32)}`;
const ipKey = (kind: string, req: Request) => `${kind}:ip:${clientIp(req)}`;

async function locked(env: Env, email: string): Promise<boolean> {
  return (await peek(env, await emailKey("fail", email), LIMIT_WINDOW)) >= FAILS_TO_LOCK;
}

/** POST /auth/code {email}: send a code. The answer is the same whether or
 *  not the address has an account. */
export async function requestCode(req: Request, env: Env): Promise<Response> {
  const body = await readJson(req);
  const email = normEmail(body.email);
  if (!email) throw new HttpError(400, "bad_email");
  if (await locked(env, email)) throw new HttpError(429, "locked", { retryAfter: LIMIT_WINDOW });
  await limitOrThrow(env, ipKey("code", req), CODES_PER_IP, LIMIT_WINDOW);
  await limitOrThrow(env, await emailKey("code", email), CODES_PER_EMAIL, LIMIT_WINDOW);
  const code = newCode();
  await env.DB.prepare(
    `INSERT INTO otp (email, code_hash, expires_at, attempts) VALUES (?1, ?2, ?3, 0)
     ON CONFLICT(email) DO UPDATE SET code_hash = ?2, expires_at = ?3, attempts = 0`,
  ).bind(email, await codeHash(email, code), nowSec() + CODE_TTL).run();
  await sendCode(env, email, code);
  return json({ ok: true });
}

/** POST /auth/verify {email, code, device} -> {token, uid, new, name}. An
 *  unknown address becomes a new account; `new` says to ask for a name. */
export async function verifyCode(req: Request, env: Env): Promise<Response> {
  const body = await readJson(req);
  const email = normEmail(body.email);
  const code = typeof body.code === "string" ? body.code.replace(/\s+/g, "") : "";
  const device = typeof body.device === "string" ? body.device.slice(0, 60) : "";
  if (!email) throw new HttpError(400, "bad_email");
  await limitOrThrow(env, ipKey("verify", req), VERIFIES_PER_IP, LIMIT_WINDOW);
  if (await locked(env, email)) throw new HttpError(429, "locked", { retryAfter: LIMIT_WINDOW });

  const row = await env.DB.prepare("SELECT code_hash, expires_at, attempts FROM otp WHERE email = ?")
    .bind(email).first<{ code_hash: string; expires_at: number; attempts: number }>();
  if (!row || row.expires_at <= nowSec()) {
    if (row) await env.DB.prepare("DELETE FROM otp WHERE email = ?").bind(email).run();
    throw new HttpError(400, "expired");
  }
  const good = /^\d{6}$/.test(code) && timingSafeEqual(await codeHash(email, code), row.code_hash);
  if (!good) {
    const attempts = row.attempts + 1;
    await (attempts >= CODE_ATTEMPTS
      ? env.DB.prepare("DELETE FROM otp WHERE email = ?").bind(email)
      : env.DB.prepare("UPDATE otp SET attempts = ? WHERE email = ?").bind(attempts, email)).run();
    await hit(env, await emailKey("fail", email), FAILS_TO_LOCK, LIMIT_WINDOW);
    throw new HttpError(400, attempts >= CODE_ATTEMPTS ? "expired" : "wrong_code");
  }

  // a code works once: gone before the session exists
  await env.DB.prepare("DELETE FROM otp WHERE email = ?").bind(email).run();
  const now = nowSec();
  let user = await env.DB.prepare("SELECT uid, name FROM users WHERE email = ?")
    .bind(email).first<{ uid: string; name: string | null }>();
  let isNew = false;
  if (!user) {
    const uid = ulid();
    await env.DB.prepare("INSERT INTO users (uid, email, created_at) VALUES (?, ?, ?)").bind(uid, email, now).run();
    user = { uid, name: null };
    isNew = true;
  }
  const token = newToken();
  await env.DB.prepare(
    "INSERT INTO sessions (token_hash, uid, device, created_at, last_used) VALUES (?, ?, ?, ?, ?)",
  ).bind(await sha256Hex(token), user.uid, device, now, now).run();
  return json({ token, uid: user.uid, new: isNew, name: user.name });
}

export interface Session {
  uid: string;
  tokenHash: string;
}

/** The session behind `Authorization: Bearer <token>`: one indexed read. */
export async function authenticate(req: Request, env: Env): Promise<Session> {
  const m = /^Bearer ([A-Za-z0-9_-]{43})$/.exec(req.headers.get("authorization") || "");
  if (!m) throw new HttpError(401, "auth");
  const tokenHash = await sha256Hex(m[1]);
  const row = await env.DB.prepare("SELECT uid, last_used FROM sessions WHERE token_hash = ?")
    .bind(tokenHash).first<{ uid: string; last_used: number }>();
  if (!row) throw new HttpError(401, "auth");
  const now = nowSec();
  if (row.last_used <= now - SESSION_IDLE) {
    await env.DB.prepare("DELETE FROM sessions WHERE token_hash = ?").bind(tokenHash).run();
    throw new HttpError(401, "auth");
  }
  if (row.last_used <= now - TOUCH_EVERY) {
    await env.DB.prepare("UPDATE sessions SET last_used = ? WHERE token_hash = ?").bind(now, tokenHash).run();
  }
  return { uid: row.uid, tokenHash };
}

/** GET /auth/me: who this session is. */
export async function me(s: Session, env: Env): Promise<Response> {
  const u = await env.DB.prepare("SELECT uid, email, name, emoji FROM users WHERE uid = ?")
    .bind(s.uid).first<{ uid: string; email: string; name: string | null; emoji: string | null }>();
  if (!u) throw new HttpError(401, "auth");
  return json(u);
}

export async function signOut(s: Session, env: Env): Promise<Response> {
  await env.DB.prepare("DELETE FROM sessions WHERE token_hash = ?").bind(s.tokenHash).run();
  return json({ ok: true });
}

export async function signOutAll(s: Session, env: Env): Promise<Response> {
  await env.DB.prepare("DELETE FROM sessions WHERE uid = ?").bind(s.uid).run();
  return json({ ok: true });
}

/** DELETE /account: everything of mine, sessions included. A squad I
 *  founded passes to its longest-standing member, or goes when I was the
 *  last one in it. */
export async function deleteAccount(s: Session, env: Env): Promise<Response> {
  const uid = s.uid;
  const db = env.DB;
  const user = await db.prepare("SELECT email FROM users WHERE uid = ?").bind(uid).first<{ email: string }>();
  const founded = await db.prepare("SELECT id FROM squads WHERE founder = ?").bind(uid).all<{ id: string }>();
  const stmts: D1PreparedStatement[] = [];
  for (const { id } of founded.results) {
    stmts.push(db.prepare(
      `UPDATE squads SET founder = (SELECT uid FROM members WHERE squad = ?1 AND uid != ?2
         ORDER BY joined_at, uid LIMIT 1) WHERE id = ?1
         AND EXISTS (SELECT 1 FROM members WHERE squad = ?1 AND uid != ?2)`).bind(id, uid));
    stmts.push(db.prepare(
      `DELETE FROM squads WHERE id = ?1 AND NOT EXISTS
         (SELECT 1 FROM members WHERE squad = ?1 AND uid != ?2)`).bind(id, uid));
    stmts.push(db.prepare(
      "DELETE FROM bans WHERE squad = ?1 AND NOT EXISTS (SELECT 1 FROM squads WHERE id = ?1)").bind(id));
  }
  for (const sql of [
    "DELETE FROM members WHERE uid = ?1",
    "DELETE FROM bans WHERE uid = ?1",
    "DELETE FROM friends WHERE owner = ?1 OR friend = ?1",
    "DELETE FROM cheers WHERE to_uid = ?1 OR from_uid = ?1",
    "DELETE FROM knocks WHERE to_uid = ?1 OR from_uid = ?1",
    "DELETE FROM weeks WHERE uid = ?1",
    "DELETE FROM decks WHERE uid = ?1",
    "DELETE FROM heatmaps WHERE uid = ?1",
    "DELETE FROM settings WHERE uid = ?1",
    "DELETE FROM codes WHERE uid = ?1",
    "DELETE FROM sessions WHERE uid = ?1",
    "DELETE FROM users WHERE uid = ?1",
  ]) stmts.push(db.prepare(sql).bind(uid));
  if (user) stmts.push(db.prepare("DELETE FROM otp WHERE email = ?").bind(user.email));
  await db.batch(stmts);  // one transaction: all of it or none
  return json({ ok: true });
}

/** POST /admin/import-users {users: [{uid, email, name?, code?}]}: the
 *  one-shot import of `firebase auth:export`, so a first 3.0 sign-in lands
 *  on the account's old uid, under the name and friend code it had (when
 *  the import carries them). Idempotent by uid. An address already on
 *  another uid (someone signed in to 3.0 before the import) is skipped and
 *  reported; a code someone already holds stays theirs. */
export async function importUsers(req: Request, env: Env): Promise<Response> {
  const want = env.ADMIN_TOKEN;
  const got = (req.headers.get("authorization") || "").replace(/^Bearer /, "");
  if (!want) throw new HttpError(404, "not_found");
  if (!timingSafeEqual(await sha256Hex(got), await sha256Hex(want))) throw new HttpError(401, "auth");
  const body = await readJson(req);
  if (!Array.isArray(body.users)) throw new HttpError(400, "bad_users");
  const now = nowSec();
  let imported = 0;
  let reclaimed = 0;
  const skipped: string[] = [];
  const rows: { uid: string; email: string; name: string | null; code: string | null }[] = [];
  for (const u of body.users as Record<string, unknown>[]) {
    const email = normEmail(u?.email);
    const uid = typeof u?.uid === "string" && /^[A-Za-z0-9_-]{1,128}$/.test(u.uid) ? u.uid : null;
    if (!email || !uid) {
      skipped.push(String(u?.uid ?? "?"));
      continue;
    }
    const name = typeof u.name === "string" && u.name.trim() ? u.name.trim().slice(0, 60) : null;
    const code = typeof u.code === "string" && /^[A-Z0-9]{6}$/.test(u.code) ? u.code : null;
    rows.push({ uid, email, name, code });
  }
  for (let i = 0; i < rows.length; i += 50) {
    const chunk = rows.slice(i, i + 50);
    const results = await env.DB.batch(chunk.map((r) => env.DB.prepare(
      `INSERT INTO users (uid, email, name, created_at) VALUES (?, ?, ?, ?)
       ON CONFLICT DO NOTHING`).bind(r.uid, r.email, r.name, now)));
    const coded = chunk.filter((r, j) => results[j].meta.changes && r.code);
    if (coded.length) {
      const claims = await env.DB.batch(coded.map((r) => env.DB.prepare(
        "INSERT INTO codes (code, uid) VALUES (?, ?) ON CONFLICT DO NOTHING").bind(r.code, r.uid)));
      const won = coded.filter((_r, j) => claims[j].meta.changes);
      if (won.length) {
        await env.DB.batch(won.map((r) => env.DB.prepare("UPDATE users SET code = ? WHERE uid = ?").bind(r.code, r.uid)));
      }
    }
    if (body.reclaimCodes === true) {
      // 3.0.0's first sync swapped imported codes for new ones: an account
      // already here gets its imported code back when nobody else holds it
      const back = chunk.filter((r, j) => !results[j].meta.changes && r.code);
      for (const r of back) {
        const claim = await env.DB.prepare("INSERT INTO codes (code, uid) VALUES (?, ?) ON CONFLICT DO NOTHING")
          .bind(r.code, r.uid).run();
        const mine = await env.DB.prepare("SELECT uid FROM codes WHERE code = ?").bind(r.code).first<string>("uid");
        if (!claim.meta.changes && mine !== r.uid) continue;
        await env.DB.batch([
          env.DB.prepare("UPDATE users SET code = ? WHERE uid = ?").bind(r.code, r.uid),
          env.DB.prepare("DELETE FROM codes WHERE uid = ? AND code != ?").bind(r.uid, r.code),
        ]);
        reclaimed++;
      }
    }
    for (let j = 0; j < chunk.length; j++) {
      if (results[j].meta.changes) {
        imported++;
        continue;
      }
      // already there by uid (a re-run: fine) or the address is on another uid
      const owner = await env.DB.prepare("SELECT uid FROM users WHERE email = ?")
        .bind(chunk[j].email).first<{ uid: string }>();
      if (owner?.uid !== chunk[j].uid) skipped.push(chunk[j].uid);
    }
  }
  return json({ imported, skipped, reclaimed });
}
