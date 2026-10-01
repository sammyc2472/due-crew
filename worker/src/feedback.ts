/** 3.6.5, P6: Send feedback. Signed in only; the text, who sent it, and
 *  (if they ticked it) their versions or the page they were on, for the
 *  admin's Feedback panel. The admin replies by mail from Due Crew and
 *  never sees the address. Kept a year (housekeeping), and deleted with
 *  the account. Never logged. */

import type { Session } from "./auth";
import { sendMail } from "./mail";
import { isAdmin } from "./notices";
import { HttpError, json, nowSec, readJson, ulid, type Env } from "./util";
import * as V from "./validate";

export const FEEDBACK_MAX = 2000;
export const FEEDBACK_A_DAY = 5;
const VER_MAX = 120;

function adminOnly(env: Env, s: Session) {
  if (!isAdmin(env, s.uid)) throw new HttpError(404, "not_found");
}

/** POST /feedback {text, ver?}: one row; 5 a day a person. */
export async function send(req: Request, s: Session, env: Env): Promise<Response> {
  const body = await readJson(req, 16 * 1024);
  if (Object.keys(body).some((k) => !["text", "ver"].includes(k))) throw V.bad("feedback");
  if (typeof body.text !== "string") throw V.bad("feedback");
  const text = body.text.replace(/\r\n?/g, "\n").replace(/[\u0000-\u0008\u000b-\u001f\u007f]/g, "").trim();
  if (!text || text.length > FEEDBACK_MAX) throw V.bad("feedback");
  const ver = body.ver === undefined || body.ver === null ? "" : typeof body.ver === "string" ? V.oneLine(body.ver, VER_MAX) : null;
  if (ver === null) throw V.bad("feedback");
  const now = nowSec();
  const n = await env.DB.prepare("SELECT COUNT(*) AS n FROM feedback WHERE uid = ? AND at > ?").bind(s.uid, now - 86400).first<{ n: number }>();
  if ((n?.n ?? 0) >= FEEDBACK_A_DAY) throw new HttpError(429, "too_many");
  await env.DB.prepare("INSERT INTO feedback (id, uid, at, text, ver) VALUES (?, ?, ?, ?, ?)").bind(ulid(), s.uid, now, text, ver).run();
  return json({ ok: true }, 201);
}

type Row = { id: string; uid: string; at: number; text: string; ver: string; done: number; replied: number; name: string | null; emoji: string | null };

/** GET /admin/feedback?state=new|done|all: newest first, 100 at most, with
 *  each sender's name and emoji (never their email). */
export async function list(req: Request, s: Session, env: Env): Promise<Response> {
  adminOnly(env, s);
  const state = new URL(req.url).searchParams.get("state") || "new";
  const where = state === "done" ? "WHERE f.done = 1" : state === "all" ? "" : "WHERE f.done = 0";
  const rows = await env.DB.prepare(
    `SELECT f.id, f.uid, f.at, f.text, f.ver, f.done, f.replied, u.name, u.emoji
       FROM feedback f LEFT JOIN users u ON u.uid = f.uid ${where} ORDER BY f.at DESC LIMIT 100`).all<Row>();
  const open = await env.DB.prepare("SELECT COUNT(*) AS n FROM feedback WHERE done = 0").first<{ n: number }>();
  return json({ open: open?.n ?? 0, feedback: rows.results.map((r) => ({
    id: r.id, uid: r.uid, at: r.at, text: r.text, ver: r.ver, done: !!r.done, replied: !!r.replied,
    name: r.name || "?", emoji: r.emoji || "" })) });
}

/** PATCH /admin/feedback/{id} {done}: mark it done, or new again. */
export async function mark(req: Request, s: Session, env: Env, [id]: string[]): Promise<Response> {
  adminOnly(env, s);
  const body = await readJson(req, 1024);
  if (typeof body.done !== "boolean" || Object.keys(body).length !== 1) throw V.bad("feedback");
  const r = await env.DB.prepare("UPDATE feedback SET done = ? WHERE id = ?").bind(body.done ? 1 : 0, id).run();
  if (!r.meta.changes) throw new HttpError(404, "not_found");
  return json({ ok: true });
}

/** DELETE /admin/feedback/{id} */
export async function remove(s: Session, env: Env, [id]: string[]): Promise<Response> {
  adminOnly(env, s);
  await env.DB.prepare("DELETE FROM feedback WHERE id = ?").bind(id).run();
  return json({ ok: true });
}

/** POST /admin/feedback/{id}/reply {text}: mailed from Due Crew to the
 *  sender, with what they wrote quoted; marks it replied and done. */
export async function reply(req: Request, s: Session, env: Env, [id]: string[]): Promise<Response> {
  adminOnly(env, s);
  const body = await readJson(req, 16 * 1024);
  if (typeof body.text !== "string" || Object.keys(body).length !== 1) throw V.bad("feedback");
  const text = body.text.replace(/\r\n?/g, "\n").trim();
  if (!text || text.length > FEEDBACK_MAX) throw V.bad("feedback");
  const f = await env.DB.prepare(
    "SELECT f.text, u.email, u.name FROM feedback f JOIN users u ON u.uid = f.uid WHERE f.id = ?").bind(id)
    .first<{ text: string; email: string; name: string | null }>();
  if (!f) throw new HttpError(404, "not_found");
  const quoted = f.text.split("\n").map((l) => `> ${l}`).join("\n");
  await sendMail(env, f.email, "Sam from Due Crew, about your feedback",
    `${text}\n\nYou wrote:\n${quoted}\n\n— Sam, Due Crew (duecrew.com)\n`);
  await env.DB.prepare("UPDATE feedback SET replied = 1, done = 1 WHERE id = ?").bind(id).run();
  return json({ ok: true });
}
