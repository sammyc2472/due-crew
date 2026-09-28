// The admin's account lookup (mock "Admin Account Lookup"): one person at a
// time, to answer a support email or check a report. A search gives at most
// ten, emails partly hidden; one account gives who they are, where they are
// (squads, plans) and counts of their crew. Never how they study (their
// week, days, heatmap, decks, log or plan progress), never who their crew
// are or whom they muted, never their settings, never a list of everyone.
// Nothing here logs an email, a name or what was searched.

import type { Session } from "./auth";
import { deleteAccount } from "./auth";
import { isAdmin } from "./notices";
import { Env, HttpError, json, normEmail, readJson } from "./util";

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
  return json({ people: found.map((r) => ({ uid: r.uid, name: r.name || "?", emoji: r.emoji || "", email: masked(r.email),
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
    env.DB.prepare(`SELECT q.name, q.founder = ?1 AS founder, (SELECT COUNT(*) FROM members m2 WHERE m2.squad = q.id) AS n
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
  return json({
    uid: u.uid, name: u.name || "?", emoji: u.emoji || "", email: u.email, code: u.code || "",
    joined: u.created_at, lastSeen: u.last_seen, version: u.client_version || "", tz: u.tz,
    signedIn: { computers: sess.computers, browsers: sess.browsers, last: sess.last || null },
    squads: squads.results.map((q: any) => ({ name: q.name, members: q.n, founder: q.founder === 1 })),
    crew: { mutual: m, addedNotBack: (added.results[0]?.n ?? 0) - m, addedThem: (back.results[0]?.n ?? 0) - m, muted },
    made: made.results.map((p: any) => ({ name: p.name, audience: p.audience, listed: p.listed === 1, followers: p.followers })),
    following: follows.results.map((p: any) => ({ name: p.name, owner: p.owner_name || "?", paused: p.paused === 1, listed: p.listed === 1 })),
  });
}

/** POST /admin/people/{uid}/signout: every session of theirs ends. */
export async function signOut(s: Session, env: Env, [uid]: string[]): Promise<Response> {
  adminOnly(env, s);
  const r = await env.DB.prepare("DELETE FROM sessions WHERE uid = ?").bind(uid).run();
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
  return deleteAccount({ uid, tokenHash: "" }, env);
}
