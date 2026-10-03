// The admin's account lookup (mock "Admin Account Lookup"): one person at a
// time, to answer a support email or check a report. A search gives at most
// ten, emails partly hidden, and a squad code gives that squad; one account
// gives who they are, where they are (squads, plans), counts of their crew,
// the admin's note and what the admin has done there. Who their crew are
// only behind a click, and each look goes in the audit log ("The next
// round", F1-F3). Never how they study (their week, days, heatmap, decks,
// log or plan progress), never whom they muted, never their settings,
// never a list of everyone. Sign-in help (mock "Admin, grown up", A3): a fresh code past
// the limits, the limits cleared, an email change that finishes at the new
// address's first sign-in. Every action goes in the audit log. Nothing here
// logs an email, a name, a code or what was searched.

import type { Session } from "./auth";
import { CODE_TTL, DAY, LIMIT_WINDOW, codeHash, deleteAccount, emailKey } from "./auth";
import { actionsFor, bump, logAction } from "./admin";
import { peek as peekLimit } from "./limits";
import { sendCode, sendMail } from "./mail";
import { SQUAD_CODE_LEN, idForCode, normalizeCode } from "./squads";
import { isAdmin } from "./notices";
import { Env, HttpError, json, newCode, normEmail, nowSec, readJson } from "./util";

const HITS = 10;

function adminOnly(env: Env, s: Session) {
  if (!isAdmin(env, s.uid)) throw new HttpError(404, "not_found");
}

/** "m•••@school.edu": enough to tell two Mayas apart, not to write to one. */
export function masked(email: string): string {
  const [local, domain] = email.split("@");
  return `${local.slice(0, 1)}•••@${domain}`;
}

type Row = { uid: string; name: string | null; emoji: string | null; email: string; created_at: number; client_version: string | null };
const COLS = "uid, name, emoji, email, created_at, client_version";

/** GET /admin/people?q=: an exact email, uid or friend code, or up to ten
 *  whose name starts with q. At least 3 characters. */
export async function search(req: Request, s: Session, env: Env): Promise<Response> {
  adminOnly(env, s);
  const q = (new URL(req.url).searchParams.get("q") || "").trim().slice(0, 254);
  if (q.length < 3) throw new HttpError(400, "short");
  const found: Row[] = [];
  const add = (rows: Row[]) => { for (const r of rows) if (found.length < HITS && !found.some((f) => f.uid === r.uid)) found.push(r); };
  const email = normEmail(q);
  if (email) add((await env.DB.prepare(`SELECT ${COLS} FROM users WHERE email = ?`).bind(email).all<Row>()).results);
  if (/^[A-Za-z0-9_-]{1,128}$/.test(q)) add((await env.DB.prepare(`SELECT ${COLS} FROM users WHERE uid = ?`).bind(q).all<Row>()).results);
  const code = q.replace(/\s+/g, "").toUpperCase();
  if (/^[A-Z0-9]{6,12}$/.test(code)) {
    add((await env.DB.prepare(`SELECT ${COLS} FROM users WHERE uid = (SELECT uid FROM codes WHERE code = ?)`).bind(code).all<Row>()).results);
  }
  if (!email) {
    const like = `${q.replace(/[\\%_]/g, (c) => `\\${c}`)}%`;
    add((await env.DB.prepare(`SELECT ${COLS} FROM users WHERE name LIKE ? ESCAPE '\\' ORDER BY name COLLATE NOCASE LIMIT ?`)
      .bind(like, HITS).all<Row>()).results);
  }
  // a squad's code (8 of its letters, nothing else) opens that squad
  let squad = null;
  const sc = normalizeCode(q);
  if (sc.length === SQUAD_CODE_LEN && q.replace(/[\s-]+/g, "").length === SQUAD_CODE_LEN) {
    const id = await idForCode(env, sc);
    if (id) squad = await env.DB.prepare("SELECT id, name, (SELECT COUNT(*) FROM members WHERE squad = squads.id) AS members FROM squads WHERE id = ?")
      .bind(id).first<{ id: string; name: string; members: number }>();
  }
  return json({ squad, people: found.map((r) => ({ uid: r.uid, name: r.name || "?", emoji: r.emoji || "", email: masked(r.email),
    joined: r.created_at, version: r.client_version || "" })) });
}

/** GET /admin/people/{uid}: one account. */
export async function person(s: Session, env: Env, [uid]: string[]): Promise<Response> {
  adminOnly(env, s);
  const u = await env.DB.prepare(
    "SELECT uid, name, emoji, email, code, created_at, client_version, tz, last_seen FROM users WHERE uid = ?",
  ).bind(uid).first<{ uid: string; name: string | null; emoji: string | null; email: string; code: string | null; created_at: number;
    client_version: string | null; tz: number | null; last_seen: number | null }>();
  if (!u) throw new HttpError(404, "no_user");
  const [sessions, squads, mutual, added, back, made, follows, sett] = await env.DB.batch<any>([
    env.DB.prepare("SELECT device, last_used FROM sessions WHERE uid = ?").bind(uid),
    env.DB.prepare(`SELECT q.id, q.name, q.founder = ?1 AS founder, (SELECT COUNT(*) FROM members m2 WHERE m2.squad = q.id) AS n
                      FROM members m JOIN squads q ON q.id = m.squad WHERE m.uid = ?1 ORDER BY q.name COLLATE NOCASE`).bind(uid),
    env.DB.prepare("SELECT COUNT(*) AS n FROM friends a JOIN friends b ON b.owner = a.friend AND b.friend = a.owner WHERE a.owner = ?").bind(uid),
    env.DB.prepare("SELECT COUNT(*) AS n FROM friends WHERE owner = ?").bind(uid),
    env.DB.prepare("SELECT COUNT(*) AS n FROM friends WHERE friend = ?").bind(uid),
    env.DB.prepare(`SELECT p.name, p.audience, p.listed, (SELECT COUNT(*) FROM plan_follows f WHERE f.plan = p.id) AS followers
                      FROM plans p WHERE p.owner = ? ORDER BY p.updated_at DESC LIMIT 20`).bind(uid),
    env.DB.prepare(`SELECT p.name, p.listed, f.paused, o.name AS owner_name FROM plan_follows f JOIN plans p ON p.id = f.plan
                      LEFT JOIN users o ON o.uid = p.owner WHERE f.uid = ? ORDER BY f.at DESC LIMIT 20`).bind(uid),
    env.DB.prepare("SELECT json FROM settings WHERE uid = ?").bind(uid),
  ]);
  const sess = { computers: 0, browsers: 0, last: 0 };
  for (const r of sessions.results as { device: string; last_used: number }[]) {
    if (r.device === "duecrew.com") sess.browsers++; else sess.computers++;
    sess.last = Math.max(sess.last, r.last_used);
  }
  let muted = 0;
  try { muted = (JSON.parse((sett.results[0] as any)?.json || "{}").muted || []).length; } catch { /* none */ }
  const m = mutual.results[0]?.n ?? 0;
  const [note, pending, limits, log] = await Promise.all([
    env.DB.prepare("SELECT text, at FROM admin_notes WHERE uid = ?").bind(uid).first<{ text: string; at: number }>(),
    env.DB.prepare("SELECT email, at FROM email_changes WHERE uid = ? AND at > ?").bind(uid, nowSec() - 7 * DAY).first<{ email: string; at: number }>(),
    signInLimits(env, u.email),
    actionsFor(env, "uid", uid),
  ]);
  return json({
    uid: u.uid, name: u.name || "?", emoji: u.emoji || "", email: u.email, code: u.code || "",
    joined: u.created_at, lastSeen: u.last_seen, version: u.client_version || "", tz: u.tz,
    signedIn: { computers: sess.computers, browsers: sess.browsers, last: sess.last || null },
    note: note ? { text: note.text, at: note.at } : null,
    emailChange: pending ? { email: pending.email, at: pending.at } : null,
    limits, actions: log,
    squads: squads.results.map((q: any) => ({ id: q.id, name: q.name, members: q.n, founder: q.founder === 1 })),
    crew: { mutual: m, addedNotBack: (added.results[0]?.n ?? 0) - m, addedThem: (back.results[0]?.n ?? 0) - m, muted },
    made: made.results.map((p: any) => ({ name: p.name, audience: p.audience, listed: p.listed === 1, followers: p.followers })),
    following: follows.results.map((p: any) => ({ name: p.name, owner: p.owner_name || "?", paused: p.paused === 1, listed: p.listed === 1 })),
  });
}

/** POST /admin/people/{uid}/signout: every session of theirs ends. */
export async function signOut(s: Session, env: Env, [uid]: string[]): Promise<Response> {
  adminOnly(env, s);
  const r = await env.DB.prepare("DELETE FROM sessions WHERE uid = ?").bind(uid).run();
  await logAction(env, "signed out everywhere", { uid, detail: `${r.meta.changes ?? 0} place(s)` });
  return json({ ok: true, ended: r.meta.changes ?? 0 });
}

/** DELETE /admin/people/{uid} {email}: their account, as their own Delete
 *  does it. The email, typed out, is the confirmation. Never my own. */
export async function remove(req: Request, s: Session, env: Env, [uid]: string[]): Promise<Response> {
  adminOnly(env, s);
  if (uid === s.uid) throw new HttpError(400, "self");
  const body = await readJson(req);
  const u = await env.DB.prepare("SELECT email FROM users WHERE uid = ?").bind(uid).first<{ email: string }>();
  if (!u) throw new HttpError(404, "no_user");
  if (normEmail(body.email) !== u.email) throw new HttpError(400, "confirm");
  const out = await deleteAccount({ uid, tokenHash: "" }, env);
  await logAction(env, "deleted an account", { uid });
  return out;
}

// ---- sign-in help (A3): Due Crew has no passwords; these are its resets ----

async function account(env: Env, uid: string) {
  const u = await env.DB.prepare("SELECT uid, email, name FROM users WHERE uid = ?").bind(uid).first<{ uid: string; email: string; name: string | null }>();
  if (!u) throw new HttpError(404, "no_user");
  return u;
}

/** Where they stand with the per-address sign-in limits (the ones the admin
 *  can see: the per-address-and-place ones are keyed by where they typed it). */
async function signInLimits(env: Env, email: string) {
  const [codesHour, codesDay, failsDay] = await Promise.all([
    peekLimit(env, await emailKey("code", email), LIMIT_WINDOW),
    peekLimit(env, await emailKey("codeday", email), DAY),
    peekLimit(env, await emailKey("failday", email), DAY),
  ]);
  return { codesHour, codesDay, failsDay };
}

/** POST /admin/people/{uid}/code: a fresh sign-in code to their address,
 *  past the limits, for someone stuck at the code box. The admin never sees
 *  it; it replaces any code they had. */
export async function sendFreshCode(s: Session, env: Env, [uid]: string[]): Promise<Response> {
  adminOnly(env, s);
  const u = await account(env, uid);
  const code = newCode();
  await env.DB.prepare(
    `INSERT INTO otp (email, code_hash, expires_at, attempts) VALUES (?1, ?2, ?3, 0)
     ON CONFLICT(email) DO UPDATE SET code_hash = ?2, expires_at = ?3, attempts = 0`,
  ).bind(u.email, await codeHash(u.email, code), nowSec() + CODE_TTL).run();
  await sendCode(env, u.email, code);
  await bump(env, "codes.sent");
  await logAction(env, "sent a sign-in code", { uid });
  return json({ ok: true });
}

/** POST /admin/people/{uid}/limits: the address's code and wrong-code
 *  counts start again, and any half-used code goes. */
export async function clearLimits(s: Session, env: Env, [uid]: string[]): Promise<Response> {
  adminOnly(env, s);
  const u = await account(env, uid);
  const keys = await Promise.all(["code", "codeday", "failday"].map((k) => emailKey(k, u.email)));
  await env.DB.batch([
    ...keys.map((k) => env.DB.prepare("DELETE FROM limits WHERE key = ?").bind(k)),
    env.DB.prepare("DELETE FROM otp WHERE email = ?").bind(u.email),
  ]);
  await logAction(env, "cleared sign-in limits", { uid });
  return json({ ok: true });
}

/** PUT /admin/people/{uid}/email {email}: start moving the account to a new
 *  address. Both are told; it happens the first time someone signs in with
 *  a code at the new one (within a week), so a typo hands nothing over. */
export async function changeEmail(req: Request, s: Session, env: Env, [uid]: string[]): Promise<Response> {
  adminOnly(env, s);
  const u = await account(env, uid);
  const email = normEmail((await readJson(req)).email);
  if (!email) throw new HttpError(400, "bad_email");
  if (email === u.email) throw new HttpError(400, "same");
  if (await env.DB.prepare("SELECT 1 FROM users WHERE email = ?").bind(email).first()) throw new HttpError(409, "taken");
  if (await env.DB.prepare("SELECT 1 FROM email_changes WHERE email = ? AND uid != ?").bind(email, uid).first()) throw new HttpError(409, "taken");
  await env.DB.prepare("INSERT INTO email_changes (uid, email, at) VALUES (?1, ?2, ?3) ON CONFLICT(uid) DO UPDATE SET email = ?2, at = ?3")
    .bind(uid, email, nowSec()).run();
  await sendMail(env, email, "Your Due Crew account is moving here",
    "Sam from Due Crew is moving your Due Crew account to this address, as you asked.\n\n" +
    "To finish, sign in to Due Crew with this address in the next 7 days (in Anki or at duecrew.com). " +
    "Until then nothing changes.\n\nDidn't ask for this? Ignore this email and nothing happens.");
  await sendMail(env, u.email, "Your Due Crew account is moving",
    "Sam from Due Crew is moving your Due Crew account to a new email address, as asked. " +
    "It moves when that address signs in, and from then on this one no longer signs in.\n\n" +
    "Didn't ask for this? Sign in and use Send feedback before then, and it will be stopped.");
  await logAction(env, "started an email change", { uid });
  return json({ ok: true, email });
}

/** DELETE /admin/people/{uid}/email: stop a change before it happens. */
export async function cancelEmail(s: Session, env: Env, [uid]: string[]): Promise<Response> {
  adminOnly(env, s);
  const r = await env.DB.prepare("DELETE FROM email_changes WHERE uid = ?").bind(uid).run();
  if (r.meta.changes) await logAction(env, "stopped an email change", { uid });
  return json({ ok: true });
}

const NOTE_MAX = 2000;

/** PUT /admin/people/{uid}/note {text}: the admin's own note on the
 *  account; empty takes it off. Deleted with the account. */
export async function putNote(req: Request, s: Session, env: Env, [uid]: string[]): Promise<Response> {
  adminOnly(env, s);
  await account(env, uid);
  const body = await readJson(req, 16 * 1024);
  if (typeof body.text !== "string") throw new HttpError(400, "bad_note");
  const text = body.text.replace(/\r\n?/g, "\n").trim();
  if (text.length > NOTE_MAX) throw new HttpError(400, "too_long");
  if (!text) await env.DB.prepare("DELETE FROM admin_notes WHERE uid = ?").bind(uid).run();
  else await env.DB.prepare("INSERT INTO admin_notes (uid, text, at) VALUES (?1, ?2, ?3) ON CONFLICT(uid) DO UPDATE SET text = ?2, at = ?3")
    .bind(uid, text, nowSec()).run();
  return json({ ok: true });
}

// ---- an account's crew (F1-F3): by name, behind a click, every look logged ----

const CREW_MAX = 500;

/** GET /admin/people/{uid}/crew: everyone on either side of a friendship
 *  with them, by name and emoji, with which side added whom and when.
 *  Nothing about how anyone studies. The look itself goes in the audit log. */
export async function crew(s: Session, env: Env, [uid]: string[]): Promise<Response> {
  adminOnly(env, s);
  await account(env, uid);
  const rows = await env.DB.prepare(
    `SELECT o.other AS uid, u.name, u.emoji, MAX(o.mine) AS mine, MAX(o.theirs) AS theirs FROM (
       SELECT friend AS other, at AS mine, NULL AS theirs FROM friends WHERE owner = ?1
       UNION ALL
       SELECT owner AS other, NULL AS mine, at AS theirs FROM friends WHERE friend = ?1
     ) o LEFT JOIN users u ON u.uid = o.other
     GROUP BY o.other ORDER BY (MAX(o.mine) IS NOT NULL AND MAX(o.theirs) IS NOT NULL) DESC, u.name COLLATE NOCASE LIMIT ?2`,
  ).bind(uid, CREW_MAX).all<{ uid: string; name: string | null; emoji: string | null; mine: number | null; theirs: number | null }>();
  await logAction(env, "looked at their crew", { uid });
  return json({ crew: rows.results.map((r) => ({ uid: r.uid, name: r.name || "a deleted account", emoji: r.emoji || "", mine: r.mine, theirs: r.theirs })) });
}

/** DELETE /admin/people/{uid}/crew/{other}?side=mine|theirs: one side of a
 *  friendship, on their request. "mine" takes the other person off their
 *  list (what their own Remove does); "theirs" takes them off the other
 *  person's list (someone they don't know added them). Never adds anyone:
 *  a friendship is two people's yes. They get one email saying what was done. */
export async function removeEdge(req: Request, s: Session, env: Env, [uid, other]: string[]): Promise<Response> {
  adminOnly(env, s);
  const side = new URL(req.url).searchParams.get("side");
  if (side !== "mine" && side !== "theirs") throw new HttpError(400, "side");
  const u = await account(env, uid);
  const [owner, friend] = side === "mine" ? [uid, other] : [other, uid];
  const r = await env.DB.prepare("DELETE FROM friends WHERE owner = ? AND friend = ?").bind(owner, friend).run();
  if (!r.meta.changes) throw new HttpError(404, "no_edge");
  const them = (await env.DB.prepare("SELECT name FROM users WHERE uid = ?").bind(other).first<string>("name")) || "someone";
  try {
    await sendMail(env, u.email, "Your Due Crew list",
      (side === "mine" ? `As you asked, Sam took ${them} off your Due Crew list.` : `As you asked, Sam took you off ${them}'s Due Crew list.`) +
      "\n\nQuestions? Reply in Due Crew with Send feedback.\n\n— Sam, Due Crew (duecrew.com)\n");
  } catch { /* what was done stays done */ }
  await logAction(env, side === "mine" ? "took someone off their list" : "took them off someone's list", { uid });
  return json({ ok: true });
}

