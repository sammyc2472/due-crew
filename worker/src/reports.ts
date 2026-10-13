/** 3.8.1 (the audit): reports, kept for the admin. A report used to go only by
 *  mail, and without REPORT_TO it went nowhere while the reporter was told it was
 *  sent. Now each is a row the admin's Inbox lists (and a mail when REPORT_TO is
 *  set): kept 180 days (housekeeping), deleted with either person's account, in
 *  the reporter's Your data. Never the reporter's email, never logged. */

import type { Session } from "./auth";
import { sendMail } from "./mail";
import { isAdmin } from "./notices";
import { HttpError, json, nowSec, readJson, ulid, type Env } from "./util";
import * as V from "./validate";

export const REPORTS_KEPT_DAYS = 180;

export type Report = { by: string; kind: "person" | "plan"; target: string; reason: string; note: string; detail: string };

/** Keep it, then mail it if REPORT_TO is set. A mail that fails doesn't fail the
 *  report: it's kept, and the reporter doesn't send it twice. */
export async function keep(env: Env, r: Report, subject: string, mail: string): Promise<void> {
  await env.DB.prepare(
    "INSERT INTO reports (id, by_uid, kind, target, reason, note, detail, at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
  ).bind(ulid(), r.by, r.kind, r.target, r.reason, r.note, r.detail, nowSec()).run();
  if (!env.REPORT_TO) return;
  try { await sendMail(env, env.REPORT_TO, subject, mail); } catch { console.log("due crew: a report's mail didn't go; it's in the Inbox"); }
}

function adminOnly(env: Env, s: Session) {
  if (!isAdmin(env, s.uid)) throw new HttpError(404, "not_found");
}

type Row = { id: string; by_uid: string; kind: string; target: string; reason: string; note: string; detail: string;
             at: number; done: number; by_name: string | null; by_emoji: string | null; t_name: string | null;
             t_emoji: string | null; p_name: string | null; p_code: string | null };

/** GET /admin/reports?state=new|done|all: newest first, 100 at most, with both
 *  people's names and emoji as they are now (never an email). */
export async function list(req: Request, s: Session, env: Env): Promise<Response> {
  adminOnly(env, s);
  const state = new URL(req.url).searchParams.get("state") || "new";
  const where = state === "done" ? "WHERE r.done = 1" : state === "all" ? "" : "WHERE r.done = 0";
  const rows = await env.DB.prepare(
    `SELECT r.id, r.by_uid, r.kind, r.target, r.reason, r.note, r.detail, r.at, r.done,
            b.name AS by_name, b.emoji AS by_emoji, t.name AS t_name, t.emoji AS t_emoji, p.name AS p_name, p.code AS p_code
       FROM reports r LEFT JOIN users b ON b.uid = r.by_uid
       LEFT JOIN users t ON r.kind = 'person' AND t.uid = r.target
       LEFT JOIN plans p ON r.kind = 'plan' AND p.id = r.target
       ${where} ORDER BY r.at DESC LIMIT 100`).all<Row>();
  const open = await env.DB.prepare("SELECT COUNT(*) AS n FROM reports WHERE done = 0").first<{ n: number }>();
  return json({ open: open?.n ?? 0, reports: rows.results.map((r) => ({
    id: r.id, kind: r.kind, at: r.at, reason: r.reason, note: r.note, detail: r.detail, done: !!r.done,
    by: { uid: r.by_uid, name: r.by_name || "?", emoji: r.by_emoji || "" },
    target: r.kind === "plan"
      ? { plan: r.target, name: r.p_name || "(deleted plan)", code: r.p_code || "" }
      : { uid: r.target, name: r.t_name || "?", emoji: r.t_emoji || "" },
  })) });
}

/** PATCH /admin/reports/{id} {done} */
export async function mark(req: Request, s: Session, env: Env, [id]: string[]): Promise<Response> {
  adminOnly(env, s);
  const body = await readJson(req, 1024);
  if (typeof body.done !== "boolean" || Object.keys(body).length !== 1) throw V.bad("report");
  const r = await env.DB.prepare("UPDATE reports SET done = ? WHERE id = ?").bind(body.done ? 1 : 0, id).run();
  if (!r.meta.changes) throw new HttpError(404, "not_found");
  return json({ ok: true });
}

/** DELETE /admin/reports/{id} */
export async function remove(s: Session, env: Env, [id]: string[]): Promise<Response> {
  adminOnly(env, s);
  await env.DB.prepare("DELETE FROM reports WHERE id = ?").bind(id).run();
  return json({ ok: true });
}
