// 3.2.1: a notice from the admin, one line at the top of everyone's board
// (an update to get, something new). The admin posts it from the site's
// /admin; GET /board carries the newest live one that applies to the
// asking add-on's version. Nobody but ADMIN_UIDS can post.

import type { Session } from "./auth";
import * as V from "./validate";
import { Env, HttpError, json, nowSec, readJson } from "./util";

export const NOTICE_MAX = 200;
const LINK_MAX = 300;
const DAYS_MAX = 60;
const VERSION = /^\d{1,3}(\.\d{1,3}){0,3}$/;

export type Notice = { id: number; text: string; link: string | null; below: string | null; created_at: number; until: number };

/** The admin: the uids in ADMINS (wrangler.toml: Sam's "sammy" account)
 *  and in the optional ADMIN_UIDS secret. */
export function isAdmin(env: Env, uid: string): boolean {
  return [env.ADMINS, env.ADMIN_UIDS].join(",").split(",").map((x) => x.trim()).filter(Boolean).includes(uid);
}

function adminOnly(env: Env, s: Session) {
  if (!isAdmin(env, s.uid)) throw new HttpError(404, "not_found");
}

const parts = (v: string) => v.split(".").map((x) => Number(x) || 0);

/** a < b, as versions ("3.1.10" > "3.1.9"). */
export function older(a: string, b: string): boolean {
  const x = parts(a), y = parts(b);
  for (let i = 0; i < Math.max(x.length, y.length); i++) {
    if ((x[i] ?? 0) !== (y[i] ?? 0)) return (x[i] ?? 0) < (y[i] ?? 0);
  }
  return false;
}

/** POST /admin/notices {text, link?, below?, days?}. */
export async function post(req: Request, s: Session, env: Env): Promise<Response> {
  adminOnly(env, s);
  const body = await readJson(req);
  for (const k of Object.keys(body)) if (!["text", "link", "below", "days"].includes(k)) throw V.bad("notice");
  if (!V.isStr(body.text, NOTICE_MAX * 2)) throw V.bad("notice");
  const text = V.oneLine(body.text, NOTICE_MAX);
  if (!text) throw V.bad("notice");
  let link: string | null = null;
  if (body.link !== undefined && body.link !== null && body.link !== "") {
    if (!V.isStr(body.link, LINK_MAX)) throw V.bad("link");
    let u: URL;
    try { u = new URL(body.link); } catch { throw V.bad("link"); }
    if (u.protocol !== "https:") throw V.bad("link");
    link = u.toString();
  }
  let below: string | null = null;
  if (body.below !== undefined && body.below !== null && body.below !== "") {
    if (typeof body.below !== "string" || !VERSION.test(body.below)) throw V.bad("below");
    below = body.below;
  }
  const days = body.days === undefined ? 14 : body.days;
  if (!V.isInt(days, 1, DAYS_MAX)) throw V.bad("days");
  const now = nowSec();
  const r = await env.DB.prepare("INSERT INTO notices (text, link, below, created_at, until) VALUES (?, ?, ?, ?, ?) RETURNING id")
    .bind(text, link, below, now, now + days * 86400).first<{ id: number }>();
  return json({ id: r!.id, text, link, below, until: now + days * 86400 });
}

/** GET /admin/notices: the ones still showing, newest first. */
export async function list(s: Session, env: Env): Promise<Response> {
  adminOnly(env, s);
  const rows = await env.DB.prepare("SELECT * FROM notices WHERE until > ? ORDER BY id DESC LIMIT 20").bind(nowSec()).all<Notice>();
  return json({ notices: rows.results });
}

/** DELETE /admin/notices/{id}: it stops showing. */
export async function remove(s: Session, env: Env, [id]: string[]): Promise<Response> {
  adminOnly(env, s);
  if (!/^\d{1,9}$/.test(id)) throw new HttpError(404, "not_found");
  await env.DB.prepare("DELETE FROM notices WHERE id = ?").bind(Number(id)).run();
  return json({ ok: true });
}

/** For GET /board: the newest live notice for this add-on's version, or null.
 *  A version the server doesn't know yet (the add-on hasn't synced) gets
 *  only the notices for everyone. */
export async function forBoard(env: Env, clientVersion: string | null): Promise<{ id: number; text: string; link: string | null } | null> {
  const rows = await env.DB.prepare("SELECT id, text, link, below FROM notices WHERE until > ? ORDER BY id DESC LIMIT 5")
    .bind(nowSec()).all<{ id: number; text: string; link: string | null; below: string | null }>();
  for (const n of rows.results) {
    if (!n.below || (clientVersion && VERSION.test(clientVersion) && older(clientVersion, n.below))) {
      return { id: n.id, text: n.text, link: n.link };
    }
  }
  return null;
}
