// The admin's squad tools (mock "Admin, grown up", A4): one squad at a
// time, reached by its code or from an account, never a list of every
// squad. Each action is a founder's own tool done from the admin's side:
// remove (and block), a new code, open or close, rename, hand over, delete.
// The founder gets one plain email saying what Sam did, and every action
// goes in the audit log. Never how anyone studies: names, emoji and when
// they joined, nothing from their rows.

import type { Session } from "./auth";
import { actionsFor, logAction } from "./admin";
import { sendMail } from "./mail";
import { isAdmin } from "./notices";
import { checkUid } from "./social";
import { drawCode, squadId } from "./squads";
import * as V from "./validate";
import { Env, HttpError, json, readJson } from "./util";

const BANS_MAX = 200;
const LIST = 500;

function adminOnly(env: Env, s: Session) {
  if (!isAdmin(env, s.uid)) throw new HttpError(404, "not_found");
}

type Sq = { id: string; name: string; founder: string; open: number; created_at: number; code_id: string | null };

async function squad(env: Env, id: string): Promise<Sq> {
  const q = await env.DB.prepare("SELECT id, name, founder, open, created_at, code_id FROM squads WHERE id = ?").bind(id).first<Sq>();
  if (!q) throw new HttpError(404, "no_squad");
  return q;
}

async function nameOf(env: Env, uid: string): Promise<string> {
  return (await env.DB.prepare("SELECT name FROM users WHERE uid = ?").bind(uid).first<string>("name")) || "someone";
}

/** One plain line to the squad's founder. A failed send doesn't undo what was done. */
async function tellFounder(env: Env, q: Sq, text: string): Promise<boolean> {
  const to = await env.DB.prepare("SELECT email FROM users WHERE uid = ?").bind(q.founder).first<string>("email");
  if (!to) return false;
  try {
    await sendMail(env, to, `Your Due Crew squad, ${q.name}`, `${text}\n\nQuestions? Reply in Due Crew with Send feedback.\n\n— Sam, Due Crew (duecrew.com)\n`);
    return true;
  } catch {
    return false;
  }
}

/** GET /admin/squads/{id}: the squad, its members by name, and what the admin has done there. */
export async function get(s: Session, env: Env, [id]: string[]): Promise<Response> {
  adminOnly(env, s);
  const q = await squad(env, id);
  const [members, bans] = await env.DB.batch<any>([
    env.DB.prepare(`SELECT m.uid, COALESCE(u.name, m.name) AS name, u.emoji, m.joined_at FROM members m
                      LEFT JOIN users u ON u.uid = m.uid WHERE m.squad = ?1 ORDER BY m.uid = ?2 DESC, m.joined_at, m.uid LIMIT ?3`).bind(id, q.founder, LIST),
    env.DB.prepare("SELECT COUNT(*) AS n FROM bans WHERE squad = ?").bind(id),
  ]);
  return json({
    id: q.id, name: q.name, founder: q.founder, founderName: await nameOf(env, q.founder), open: q.open === 1,
    created: q.created_at, newCode: !!q.code_id, removed: bans.results[0]?.n ?? 0,
    members: (members.results as any[]).map((m) => ({ uid: m.uid, name: m.name || "?", emoji: m.emoji || "", joined: m.joined_at })),
    actions: await actionsFor(env, "squad", id),
  });
}

/** PATCH /admin/squads/{id} {open?, name?, founder?}: as the founder would.
 *  The squad passes only to someone already in it. */
export async function patch(req: Request, s: Session, env: Env, [id]: string[]): Promise<Response> {
  adminOnly(env, s);
  const q = await squad(env, id);
  const body = await readJson(req);
  for (const k of Object.keys(body)) if (!["open", "name", "founder"].includes(k)) throw V.bad("squad");
  const stmts: D1PreparedStatement[] = [];
  const said: string[] = [];
  if ("open" in body) {
    if (typeof body.open !== "boolean") throw V.bad("open");
    stmts.push(env.DB.prepare("UPDATE squads SET open = ? WHERE id = ?").bind(body.open ? 1 : 0, id));
    said.push(body.open ? "opened it to new members" : "closed it to new members");
  }
  if ("name" in body) {
    const name = V.squadName(body.name);
    stmts.push(env.DB.prepare("UPDATE squads SET name = ? WHERE id = ?").bind(name, id));
    said.push(`renamed it "${name}"`);
  }
  let newFounder: string | null = null;
  if ("founder" in body) {
    if (typeof body.founder !== "string") throw V.bad("founder");
    if (!(await env.DB.prepare("SELECT 1 FROM members WHERE squad = ? AND uid = ?").bind(id, body.founder).first())) {
      throw new HttpError(403, "not_member");
    }
    newFounder = body.founder;
    stmts.push(env.DB.prepare("UPDATE squads SET founder = ? WHERE id = ?").bind(newFounder, id));
    said.push(`made ${await nameOf(env, newFounder)} its founder`);
  }
  if (!stmts.length) return json({ ok: true });
  await env.DB.batch(stmts);
  const line = `Sam ${said.join(", and ")}.`;
  await tellFounder(env, q, line);  // the founder it had
  if (newFounder && newFounder !== q.founder) await tellFounder(env, { ...q, founder: newFounder }, line);
  await logAction(env, said.join("; "), { squad: id });
  return json({ ok: true });
}

/** POST /admin/squads/{id}/code: a new code. The old one stops opening the
 *  squad; everyone in it stays, and its id never changes. The code is in
 *  this answer once, and in the founder's email. */
export async function newCode(s: Session, env: Env, [id]: string[]): Promise<Response> {
  adminOnly(env, s);
  const q = await squad(env, id);
  for (let i = 0; i < 3; i++) {
    const code = drawCode();
    const h = await squadId(code);
    if (await env.DB.prepare("SELECT 1 FROM squads WHERE id = ? UNION ALL SELECT 1 FROM squad_codes WHERE code_id = ?").bind(h, h).first()) continue;
    await env.DB.batch([
      env.DB.prepare("DELETE FROM squad_codes WHERE squad = ?").bind(id),  // only the newest code opens it
      env.DB.prepare("INSERT INTO squad_codes (code_id, squad) VALUES (?, ?)").bind(h, id),
      env.DB.prepare("UPDATE squads SET code_id = ? WHERE id = ?").bind(h, id),
    ]);
    const told = await tellFounder(env, q,
      `Sam gave your squad a new code: ${code.slice(0, 4)} ${code.slice(4)}. The old code no longer lets anyone join; everyone in the squad stays. ` +
      "Share the new one with anyone you still want to invite.");
    await logAction(env, "gave a new code", { squad: id });
    return json({ code, told });
  }
  throw new HttpError(503, "try_again");
}

/** POST /admin/squads/{id}/remove/{uid} {why?}: out, and can't rejoin with
 *  the code (the founder's Block). Never the founder: hand it over first. */
export async function remove(req: Request, s: Session, env: Env, [id, uid]: string[]): Promise<Response> {
  adminOnly(env, s);
  checkUid(uid);
  const q = await squad(env, id);
  if (uid === q.founder) throw new HttpError(400, "founder");
  const body = await readJson(req, 4 * 1024);
  const why = typeof body.why === "string" ? body.why.replace(/\s+/g, " ").trim().slice(0, 300) : "";
  const n = await env.DB.prepare("SELECT COUNT(*) AS n FROM bans WHERE squad = ?").bind(id).first<number>("n");
  if ((n ?? 0) >= BANS_MAX) throw new HttpError(409, "too_many_blocked");
  const who = await nameOf(env, uid);
  await env.DB.batch([
    env.DB.prepare("INSERT INTO bans (squad, uid) VALUES (?, ?) ON CONFLICT DO NOTHING").bind(id, uid),
    env.DB.prepare("DELETE FROM members WHERE squad = ? AND uid = ?").bind(id, uid),
  ]);
  await tellFounder(env, q, `Sam removed ${who} from your squad. They can't rejoin with its code.${why ? `\n\nWhy: ${why}` : ""}`);
  await logAction(env, "removed from a squad", { uid, squad: id });
  return json({ ok: true });
}

/** DELETE /admin/squads/{id} {name}: the squad, for everyone. Its name, typed
 *  out, is the confirmation. Plans offered to it stay with their authors. */
export async function del(req: Request, s: Session, env: Env, [id]: string[]): Promise<Response> {
  adminOnly(env, s);
  const q = await squad(env, id);
  const body = await readJson(req);
  if (typeof body.name !== "string" || body.name.trim() !== q.name) throw new HttpError(400, "confirm");
  await tellFounder(env, q, "Sam deleted your squad. Its members are still each other's crew where they added each other.");
  await env.DB.batch([
    env.DB.prepare("DELETE FROM members WHERE squad = ?").bind(id),
    env.DB.prepare("DELETE FROM bans WHERE squad = ?").bind(id),
    env.DB.prepare("DELETE FROM squad_codes WHERE squad = ?").bind(id),
    env.DB.prepare("DELETE FROM squads WHERE id = ?").bind(id),
  ]);
  await logAction(env, `deleted a squad (${q.name.slice(0, 60)})`, { squad: id });
  return json({ ok: true });
}
