// Sign-in by emailed code, our own sessions, sign-out and account deletion.
//
// Never log emails, codes or tokens. Codes and tokens are stored hashed.

import { bump } from "./admin";
import { isAdmin } from "./notices";
import { hit, limitOrThrow, peek } from "./limits";
import { sendCode, sendMail } from "./mail";
import {
  Env, HttpError, clientIp, json, newCode, newToken, normEmail, nowSec, readJson,
  sha256Hex, timingSafeEqual, ulid,
} from "./util";

export const CODE_TTL = 10 * 60;            // a code lives ten minutes
export const CODE_ATTEMPTS = 5;             // wrong tries before a code dies
export const LIMIT_WINDOW = 60 * 60;        // rate limits count per hour
// Limits are per address from one IP first, so someone who knows my address
// can't use up my codes or lock me out from where they are; the address's
// own ceilings, higher, stop the same thing spread over many IPs.
export const CODES_PER_EMAIL = 5;           // an hour, to one address from one IP
export const CODES_PER_EMAIL_ALL = 10;      // an hour, to one address from anywhere
export const CODES_PER_EMAIL_IP_DAY = 8;    // a day, to one address from one IP
export const CODES_PER_EMAIL_DAY = 20;      // a day, to one inbox from anywhere
export const CODES_PER_IP = 20;
export const FAILS_TO_LOCK = 6;             // the sixth wrong code locks the address, from that IP, for the hour
export const FAILS_PER_EMAIL_DAY = 20;      // wrong codes from anywhere that lock the address for the day
export const DAY = 86400;
export const VERIFIES_PER_IP = 60;
export const SESSION_IDLE = 180 * 86400;    // idle sessions end after 180 days
const TOUCH_EVERY = 86400;                  // last_used is written at most daily

export const codeHash = (email: string, code: string) => sha256Hex(`otp:${email}:${code}`);
export const emailKey = async (kind: string, email: string) => `${kind}:e:${(await sha256Hex(email)).slice(0, 32)}`;
const ipKey = (kind: string, req: Request) => `${kind}:ip:${clientIp(req)}`;
// an address from one IP: hashed together, so no row pairs an address with where it was typed
const emailIpKey = async (kind: string, email: string, req: Request) =>
  `${kind}:ei:${(await sha256Hex(`${email}|${clientIp(req)}`)).slice(0, 32)}`;

async function locked(env: Env, email: string, req: Request): Promise<boolean> {
  return (await peek(env, await emailIpKey("fail", email, req), LIMIT_WINDOW)) >= FAILS_TO_LOCK
    || (await peek(env, await emailKey("failday", email), DAY)) >= FAILS_PER_EMAIL_DAY;
}

/** POST /auth/code {email}: send a code. The answer is the same whether or
 *  not the address has an account. */
export async function requestCode(req: Request, env: Env): Promise<Response> {
  const body = await readJson(req);
  const email = normEmail(body.email);
  if (!email) throw new HttpError(400, "bad_email");
  try {
    if (await locked(env, email, req)) throw new HttpError(429, "locked", { retryAfter: LIMIT_WINDOW });
    await limitOrThrow(env, ipKey("code", req), CODES_PER_IP, LIMIT_WINDOW);
    await limitOrThrow(env, await emailIpKey("code", email, req), CODES_PER_EMAIL, LIMIT_WINDOW);
    await limitOrThrow(env, await emailIpKey("codeday", email, req), CODES_PER_EMAIL_IP_DAY, DAY);
    await limitOrThrow(env, await emailKey("code", email), CODES_PER_EMAIL_ALL, LIMIT_WINDOW);
    await limitOrThrow(env, await emailKey("codeday", email), CODES_PER_EMAIL_DAY, DAY);
  } catch (e) {
    if (e instanceof HttpError && e.status === 429) await bump(env, "codes.limited");  // 3.5, X: counts only
    throw e;
  }
  const code = newCode();
  await env.DB.prepare(
    `INSERT INTO otp (email, code_hash, expires_at, attempts) VALUES (?1, ?2, ?3, 0)
     ON CONFLICT(email) DO UPDATE SET code_hash = ?2, expires_at = ?3, attempts = 0`,
  ).bind(email, await codeHash(email, code), nowSec() + CODE_TTL).run();
  await sendCode(env, email, code);
  await bump(env, "codes.sent");
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
  // the site's sign-in comes only from its own script: checked before the
  // code is spent, so another page can't use up someone's code
  if (body.web === true && req.headers.get("x-due-crew") !== "1") throw new HttpError(403, "csrf");
  try {
    await limitOrThrow(env, ipKey("verify", req), VERIFIES_PER_IP, LIMIT_WINDOW);
    if (await locked(env, email, req)) throw new HttpError(429, "locked", { retryAfter: LIMIT_WINDOW });
  } catch (e) {
    if (e instanceof HttpError && e.status === 429) await bump(env, "codes.limited");
    throw e;
  }

  // Claim one try in one statement, before comparing: a flood of parallel
  // guesses gets at most CODE_ATTEMPTS claims between them, never more.
  const claim = await env.DB.prepare(
    `UPDATE otp SET attempts = attempts + 1 WHERE email = ? AND attempts < ? AND expires_at > ?
     RETURNING code_hash, attempts`,
  ).bind(email, CODE_ATTEMPTS, nowSec()).first<{ code_hash: string; attempts: number }>();
  if (!claim) {
    await env.DB.prepare("DELETE FROM otp WHERE email = ?").bind(email).run();  // expired or out of tries
    await bump(env, "codes.out");
    throw new HttpError(400, "expired");
  }
  const good = /^\d{6}$/.test(code) && timingSafeEqual(await codeHash(email, code), claim.code_hash);
  if (!good) {
    if (claim.attempts >= CODE_ATTEMPTS) await env.DB.prepare("DELETE FROM otp WHERE email = ?").bind(email).run();
    await hit(env, await emailIpKey("fail", email, req), FAILS_TO_LOCK, LIMIT_WINDOW);
    await hit(env, await emailKey("failday", email), FAILS_PER_EMAIL_DAY, DAY);
    await bump(env, claim.attempts >= CODE_ATTEMPTS ? "codes.out" : "codes.wrong");
    throw new HttpError(400, claim.attempts >= CODE_ATTEMPTS ? "expired" : "wrong_code");
  }

  // a code works once: consumed in one statement, so one request wins it
  const won = await env.DB.prepare("DELETE FROM otp WHERE email = ? AND code_hash = ? RETURNING email")
    .bind(email, claim.code_hash).first();
  if (!won) throw new HttpError(400, "expired");
  const now = nowSec();
  let user = await env.DB.prepare("SELECT uid, name FROM users WHERE email = ?")
    .bind(email).first<{ uid: string; name: string | null }>();
  let isNew = false;
  if (!user) {
    // an email change the admin started finishes here: this address just
    // proved itself, so the account moves to it
    const moving = await env.DB.prepare("DELETE FROM email_changes WHERE email = ? AND at > ? RETURNING uid")
      .bind(email, now - 7 * DAY).first<{ uid: string }>();
    if (moving) {
      await env.DB.prepare("UPDATE users SET email = ? WHERE uid = ?").bind(email, moving.uid).run();
      user = await env.DB.prepare("SELECT uid, name FROM users WHERE uid = ?").bind(moving.uid).first<{ uid: string; name: string | null }>();
    }
  }
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
  await bump(env, "codes.ok");
  if (body.web === true) {
    // the site (3.1): the session is a same-site cookie, never in page script
    return json({ uid: user.uid, new: isNew, name: user.name }, 200, { "set-cookie": sessionCookie(token, SESSION_IDLE, req) });
  }
  return json({ token, uid: user.uid, new: isNew, name: user.name });
}

export interface Session {
  uid: string;
  tokenHash: string;
}

/** The session behind `Authorization: Bearer <token>`: one indexed read. */
export const COOKIE = "dc_session";

/** The session cookie the site signs in with (3.1): same-site only. */
export function sessionCookie(token: string, maxAge = SESSION_IDLE, req?: Request): string {
  // Secure everywhere but a local preview on http://localhost, where some browsers drop it
  const secure = req && new URL(req.url).hostname === "localhost" ? "" : "; Secure";
  return `${COOKIE}=${token}; Path=/; HttpOnly${secure}; SameSite=Strict; Max-Age=${maxAge}`;
}

function cookieToken(req: Request): string | null {
  for (const part of (req.headers.get("cookie") || "").split(";")) {
    const [k, v] = part.trim().split("=");
    if (k === COOKIE && /^[A-Za-z0-9_-]{43}$/.test(v || "")) return v;
  }
  return null;
}

export async function authenticate(req: Request, env: Env): Promise<Session> {
  const m = /^Bearer ([A-Za-z0-9_-]{43})$/.exec(req.headers.get("authorization") || "");
  let token = m ? m[1] : null;
  if (!token) {
    // the site: a cookie, and for anything that changes something a header
    // no other site can make a browser send (a cross-site form can't)
    token = cookieToken(req);
    if (token && req.method !== "GET" && req.headers.get("x-due-crew") !== "1") throw new HttpError(403, "csrf");
  }
  if (!token) throw new HttpError(401, "auth");
  const tokenHash = await sha256Hex(token);
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

export const ACCENTS = ["green", "blue", "purple", "teal", "amber", "rose"];
/** An accent from a settings doc, if it's one of ours; else null. */
export const accentOf = (v: unknown): string | null => (typeof v === "string" && ACCENTS.includes(v) ? v : null);

/** GET /auth/me: who this session is. */
export async function me(s: Session, env: Env): Promise<Response> {
  // 3.5.0: and my accent, from the settings the add-on keeps, so the site wears it too;
  // 3.8.0: and the hour my Anki's day rolls over, so the site's today is Anki's
  const u = await env.DB.prepare(
    `SELECT u.uid, u.email, u.name, u.emoji, u.rollover, json_extract(t.json, '$.accent') AS accent
       FROM users u LEFT JOIN settings t ON t.uid = u.uid WHERE u.uid = ?`,
  ).bind(s.uid).first<{ uid: string; email: string; name: string | null; emoji: string | null; rollover: number | null; accent: unknown }>();
  if (!u) throw new HttpError(401, "auth");
  const out = { uid: u.uid, email: u.email, name: u.name, emoji: u.emoji,
    accent: accentOf(u.accent) ?? "green",
    ...(u.rollover == null ? {} : { rollover: Number(u.rollover) }) };
  return json(isAdmin(env, u.uid) ? { ...out, admin: true } : out);  // 3.2.1: the site shows Admin
}

export async function signOut(s: Session, env: Env, req?: Request): Promise<Response> {
  await env.DB.prepare("DELETE FROM sessions WHERE token_hash = ?").bind(s.tokenHash).run();
  return json({ ok: true }, 200, { "set-cookie": sessionCookie("", 0, req) });
}

/** GET /auth/places (S6): where I'm signed in, as counts: computers (the
 *  add-on) and browsers (duecrew.com). Nothing about which, or where. */
export async function places(s: Session, env: Env): Promise<Response> {
  const rows = await env.DB.prepare("SELECT device FROM sessions WHERE uid = ?").bind(s.uid).all<{ device: string }>();
  const browsers = rows.results.filter((r) => r.device === "duecrew.com").length;
  return json({ computers: rows.results.length - browsers, browsers });
}

export async function signOutAll(s: Session, env: Env, req?: Request): Promise<Response> {
  await env.DB.prepare("DELETE FROM sessions WHERE uid = ?").bind(s.uid).run();
  return json({ ok: true }, 200, { "set-cookie": sessionCookie("", 0, req) });
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
    stmts.push(db.prepare(
      "DELETE FROM squad_codes WHERE squad = ?1 AND NOT EXISTS (SELECT 1 FROM squads WHERE id = ?1)").bind(id));
  }
  for (const sql of [
    // 3.9.5 (the audit's S2): the plans I follow, or am on the team of (a co-author's three), count
    // again without me, not in an hour
    `UPDATE plans SET totals_at = NULL WHERE totals_at IS NOT NULL
       AND (id IN (SELECT plan FROM plan_follows WHERE uid = ?1) OR id IN (SELECT plan FROM plan_team WHERE uid = ?1))`,
    "DELETE FROM members WHERE uid = ?1",
    "DELETE FROM bans WHERE uid = ?1",
    "DELETE FROM friends WHERE owner = ?1 OR friend = ?1",
    "DELETE FROM cheers WHERE to_uid = ?1 OR from_uid = ?1",
    "DELETE FROM knocks WHERE to_uid = ?1 OR from_uid = ?1",
    "DELETE FROM weeks WHERE uid = ?1",
    "DELETE FROM decks WHERE uid = ?1",
    "DELETE FROM heatmaps WHERE uid = ?1",
    "DELETE FROM settings WHERE uid = ?1",
    // 3.1: my plans go (followers keep every card they have open), and my follows
    "DELETE FROM plan_follows WHERE uid = ?1 OR plan IN (SELECT id FROM plans WHERE owner = ?1)",
    // 3.3: my plans' co-authors, notes and history, and mine on others' plans
    "DELETE FROM plan_editors WHERE uid = ?1 OR plan IN (SELECT id FROM plans WHERE owner = ?1)",
    // 3.8.1: a plan offered to me isn't any more
    "UPDATE plans SET handover = NULL WHERE handover = ?1",
    "DELETE FROM plan_notes WHERE uid = ?1 OR plan IN (SELECT id FROM plans WHERE owner = ?1)",
    "DELETE FROM plan_log WHERE uid = ?1 OR plan IN (SELECT id FROM plans WHERE owner = ?1)",
    "DELETE FROM plan_posts WHERE uid = ?1 OR plan IN (SELECT id FROM plans WHERE owner = ?1)",  // 3.7.3
    // 3.7.3: my place on teams, my questions (with their replies) and answers; my plans' teams
    "DELETE FROM plan_team WHERE uid = ?1 OR plan IN (SELECT id FROM plans WHERE owner = ?1)",
    "DELETE FROM plan_asks WHERE parent IN (SELECT id FROM plan_asks WHERE uid = ?1)",
    "DELETE FROM plan_asks WHERE uid = ?1 OR plan IN (SELECT id FROM plans WHERE owner = ?1)",
    // 3.5, B: copies of my plans keep the plan's name in their credit, not mine
    "UPDATE plans SET based_on = json_set(based_on, '$.owner', '?') WHERE based_on IS NOT NULL AND json_extract(based_on, '$.id') IN (SELECT id FROM plans WHERE owner = ?1)",
    "DELETE FROM plans WHERE owner = ?1",
    "DELETE FROM plan_trees WHERE uid = ?1",
    "DELETE FROM login_links WHERE uid = ?1",
    "DELETE FROM invites WHERE uid = ?1",
    // an invite I used stays used (so it can't make someone else crew at once), but not by me
    "UPDATE invites SET used_by = '-' WHERE used_by = ?1",
    // 3.2
    "DELETE FROM knows WHERE uid = ?1",
    "DELETE FROM tips WHERE uid = ?1",
    "DELETE FROM tip_helped WHERE tip_uid = ?1 OR by_uid = ?1",
    "DELETE FROM logs WHERE uid = ?1",
    "DELETE FROM cheer_counts WHERE uid = ?1",  // 3.7.1
    "DELETE FROM feedback WHERE uid = ?1",  // 3.6.5, P6
    "DELETE FROM reports WHERE by_uid = ?1 OR (kind = 'person' AND target = ?1)",  // 3.8.1
    "DELETE FROM admin_notes WHERE uid = ?1",
    "DELETE FROM email_changes WHERE uid = ?1",
    "DELETE FROM codes WHERE uid = ?1",
    "DELETE FROM sessions WHERE uid = ?1",
    "DELETE FROM users WHERE uid = ?1",
  ]) stmts.push(db.prepare(sql).bind(uid));
  if (user) stmts.push(db.prepare("DELETE FROM otp WHERE email = ?").bind(user.email));
  await db.batch(stmts);  // one transaction: all of it or none
  return json({ ok: true });
}

// ---- a link to open on the computer (3.4 review, C2) ----

const LINK_PATH = /^\/(p\/[A-Z0-9]{8}|i\/[A-Z0-9]{6}|i\/[A-Z0-9]{10})?$/;  // 3.5.0: an invite too

/** POST /links/email {email, path}: someone on a phone sends themselves the
 *  page they're on, to open where Anki is. One fixed message with that link
 *  and nothing of theirs in it; no account is made or looked up. A few an
 *  hour from an address, and a few a day to an inbox. */
export async function emailLink(req: Request, env: Env): Promise<Response> {
  if (req.headers.get("x-due-crew") !== "1") throw new HttpError(403, "csrf");  // only the site's own pages
  const body = await readJson(req);
  const email = normEmail(body.email);
  if (!email) throw new HttpError(400, "bad_email");
  const path = typeof body.path === "string" ? body.path : "";
  if (!LINK_PATH.test(path)) throw new HttpError(400, "bad_path");
  await limitOrThrow(env, ipKey("emaillink", req), 5, LIMIT_WINDOW);
  await limitOrThrow(env, await emailKey("emaillink", email), 3, 86400);
  const url = `https://duecrew.com${path}`;
  await sendMail(env, email, "Your Due Crew link",
    `Here's the link you asked for:\n\n${url}\n\nOpen it on the computer where you use Anki. Due Crew is a free Anki add-on.`);
  return json({ ok: true });
}

// ---- the site, signed in from the add-on (3.1) ----

const LINK_TTL = 300;

/** POST /auth/link: a one-time token the add-on puts in a duecrew.com link
 *  (after the #, so no server log sees it). Five minutes, single use. */
export async function createLink(s: Session, env: Env): Promise<Response> {
  await limitOrThrow(env, `link:${s.uid}`, 20, 3600);
  const token = newToken();
  await env.DB.prepare("INSERT INTO login_links (hash, uid, expires_at) VALUES (?, ?, ?)")
    .bind(await sha256Hex(token), s.uid, nowSec() + LINK_TTL).run();
  return json({ token, expiresIn: LINK_TTL });
}

/** POST /auth/link/redeem {token}: the site trades the link for a session
 *  cookie. The link dies on first use. */
export async function redeemLink(req: Request, env: Env): Promise<Response> {
  if (req.headers.get("x-due-crew") !== "1") throw new HttpError(403, "csrf");  // only the site's own script
  await limitOrThrow(env, `redeem:${clientIp(req)}`, 60, 3600);
  const body = await readJson(req);
  if (typeof body.token !== "string" || !/^[A-Za-z0-9_-]{43}$/.test(body.token)) throw new HttpError(400, "bad_token");
  const hash = await sha256Hex(body.token);
  const row = await env.DB.prepare("DELETE FROM login_links WHERE hash = ? RETURNING uid, expires_at")
    .bind(hash).first<{ uid: string; expires_at: number }>();
  const now = nowSec();
  if (!row || row.expires_at <= now) throw new HttpError(401, "link_expired");
  const token = newToken();
  await env.DB.prepare(
    "INSERT INTO sessions (token_hash, uid, device, created_at, last_used) VALUES (?, ?, ?, ?, ?)",
  ).bind(await sha256Hex(token), row.uid, "duecrew.com", now, now).run();
  return json({ ok: true, uid: row.uid }, 200, { "set-cookie": sessionCookie(token, SESSION_IDLE, req) });
}
