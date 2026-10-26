// 3.5, B: the plan library. An author lists a plan ("anyone with the code"
// plans only); anyone signed in can find it by deck and length, look at its
// calendar, follow it, or copy it into a plan of their own that credits
// the original. Newest first, or by how well it matches a search: never by
// followers (no ranking). The admin can take a plan out; its author reads
// why. See docs/plans-design.md, "3.5". 3.9.5: the admin marks a few as
// starters, which the library shows in a row of their own under Due Crew
// and the day's first board offers to someone with no plan.

import { logAction } from "./admin";
import type { Session } from "./auth";
import { limitOrThrow } from "./limits";
import { isAdmin } from "./notices";
import * as P from "./plans";
import * as R from "./reports";
import * as V from "./validate";
import { Env, HttpError, json, nowSec, readJson } from "./util";

export const LISTED_MAX = P.LISTED_MAX;  // plans one person keeps in the library (a hand-over checks it too)
const PAGE = 24;
const PAGES_MAX = 20;
const Q_MAX = 60;
const NOTE_MAX = 200;
const REPORT_NOTE_MAX = 500;
// how long a plan runs, as the library's filter says it
const LENGTHS: Record<string, [number, number]> = { short: [0, 28], mid: [29, 84], long: [85, 100000] };
// 3.9.5: the starters the library's own row shows, and the board offers;
// a starter's card names Due Crew in place of its owner
export const STARTERS_LIBRARY = 8;
export const STARTERS_BOARD = 4;
export const STARTER_BY = "Due Crew";

type Obj = Record<string, unknown>;
type Row = { id: string; code: string; owner: string; name: string; line: string; lib: string; listed_at: number; based_on: string | null;
  version: number; totals: string | null; totals_at: number | null; owner_name: string | null; starter: number };
const ROWS = `SELECT p.id, p.code, p.owner, p.name, p.line, p.lib, p.listed_at, p.based_on, p.version, p.totals, p.totals_at, p.starter,
                     u.name AS owner_name
                FROM plans p LEFT JOIN users u ON u.uid = p.owner`;

/** 3.9.5: the starters, newest listed first: plans in the library the
 *  admin marked (migration 0030's index holds them alone). */
async function starterRows(env: Env, n: number): Promise<Row[]> {
  return (await env.DB.prepare(
    `${ROWS} WHERE p.starter = 1 AND p.listed = 1 AND p.audience = 'code' ORDER BY p.listed_at DESC LIMIT ?`,
  ).bind(n).all<Row>()).results;
}

/** 3.9.5: what the day's first board offers someone who owns and follows
 *  no plan (board.ts): a few starters, each as its line on the board says it. */
export async function startersForBoard(env: Env): Promise<{ id: string; name: string; deck: string; days: number; perDay: number; line: string }[]> {
  return (await starterRows(env, STARTERS_BOARD)).map((r) => {
    const lib = JSON.parse(r.lib || "{}") as Obj;
    return { id: r.id, name: r.name, deck: typeof lib.deck === "string" ? lib.deck : "",
             days: Number(lib.days) || 0, perDay: Number(lib.perDay) || 0, line: r.line || "" };
  });
}

/** GET /library?deck=&len=short|mid|long&q=&page=: listed plans, newest
 *  first (a search puts name matches first). Each with its card, whose it
 *  is, how many follow, and its code; plus the decks there are, A to Z.
 *  3.9.5: with no filter and no search, the starters come apart (page 0's
 *  `starters`, STARTERS_LIBRARY at most) and the grid leaves them out; a
 *  starter, wherever it shows, says `starter` and names Due Crew. */
export async function list(req: Request, s: Session, env: Env): Promise<Response> {
  const u = new URL(req.url).searchParams;
  const deck = u.get("deck") || "";
  const len = LENGTHS[u.get("len") || ""];
  const q = V.oneLine(u.get("q") || "", Q_MAX);
  const page = Math.min(PAGES_MAX - 1, Math.max(0, Number(u.get("page")) | 0));
  const like = `%${q.replace(/[\\%_]/g, (c) => `\\${c}`)}%`;
  const plain = !deck && !len && !q;
  const where = ["p.listed = 1", "p.audience = 'code'"];
  const binds: unknown[] = [];
  if (plain) where.push("p.starter = 0");
  if (deck) { where.push("json_extract(p.lib, '$.deck') = ?"); binds.push(deck); }
  if (len) { where.push("json_extract(p.lib, '$.days') BETWEEN ? AND ?"); binds.push(...len); }
  if (q) {
    where.push("(p.name LIKE ? ESCAPE '\\' OR p.line LIKE ? ESCAPE '\\' OR json_extract(p.lib, '$.deck') LIKE ? ESCAPE '\\')");
    binds.push(like, like, like);
  }
  const order = q ? "(p.name LIKE ? ESCAPE '\\') DESC, p.listed_at DESC" : "p.listed_at DESC";
  const rows = await env.DB.prepare(
    `${ROWS} WHERE ${where.join(" AND ")} ORDER BY ${order} LIMIT ? OFFSET ?`,
  ).bind(...binds, ...(q ? [like] : []), PAGE + 1, page * PAGE).all<Row>();
  const decks = await env.DB.prepare(
    `SELECT json_extract(lib, '$.deck') AS deck, COUNT(*) AS n FROM plans WHERE listed = 1 AND audience = 'code'
      GROUP BY deck ORDER BY deck COLLATE NOCASE LIMIT 40`,
  ).all<{ deck: string; n: number }>();
  const starters = plain && page === 0 ? await starterRows(env, STARTERS_LIBRARY) : null;
  // how many follow each: its totals (migration 0025), not every follower's row, up to an hour old
  const shown = rows.results.slice(0, PAGE);
  const tot = await P.totals(env, [...shown, ...(starters ?? [])]);
  const card = (r: Row) => ({
    id: r.id, code: r.code, name: r.name, line: r.line,
    ownerName: r.starter === 1 ? STARTER_BY : r.owner_name || (r.owner ? "?" : "a former member"), followers: tot.get(r.id)?.n ?? 0,
    listedAt: r.listed_at, mine: r.owner === s.uid, ...(r.starter === 1 ? { starter: true } : {}),
    ...(JSON.parse(r.lib || "{}") as Obj), ...(r.based_on ? { basedOn: JSON.parse(r.based_on) } : {}),
  });
  return json({
    plans: shown.map(card),
    ...(starters ? { starters: starters.map(card) } : {}),
    more: rows.results.length > PAGE,
    decks: decks.results.filter((d) => d.deck).map((d) => [d.deck, d.n]),
  });
}

/** PUT /plans/{id}/listed {listed}: the owner lists the plan, or takes it
 *  out. Only a plan anyone with the code can follow, with dates; not one
 *  the admin took out. */
export async function setListed(req: Request, s: Session, env: Env, [id]: string[]): Promise<Response> {
  const p = await P.getPlan(env, id);
  if (p.owner !== s.uid) throw new HttpError(403, "not_owner");
  const body = await readJson(req);
  if (typeof body.listed !== "boolean" || Object.keys(body).some((k) => k !== "listed")) throw V.bad("listed");
  if (p.listed === -1) throw new HttpError(403, "taken_out");
  await limitOrThrow(env, `list:${s.uid}`, 30, 3600);
  if (!body.listed) {
    // 3.9.5: out of the library, out of the starters
    if (p.listed === 1) await env.DB.prepare("UPDATE plans SET listed = 0, starter = 0 WHERE id = ? AND listed = 1").bind(id).run();
  } else if (p.listed !== 1) {
    if (p.audience !== "code") throw new HttpError(409, "squad_plan");
    const doc = JSON.parse(p.doc) as Obj;
    if (!((doc.units as unknown[]) || []).length) throw new HttpError(409, "no_dates");
    const n = await env.DB.prepare("SELECT COUNT(*) AS n FROM plans WHERE owner = ? AND listed = 1").bind(s.uid).first<number>("n");
    if ((n ?? 0) >= LISTED_MAX) throw new HttpError(409, "too_many_listed");
    await env.DB.prepare("UPDATE plans SET listed = 1, listed_at = ?, lib = ? WHERE id = ? AND listed = 0")
      .bind(nowSec(), JSON.stringify(P.libCard(doc)), id).run();
  }
  return json(await P.view(env, await P.getPlan(env, id), s.uid));
}

const shiftDay = (d: string, n: number) => new Date(Date.parse(`${d}T00:00:00Z`) + n * 86400000).toISOString().slice(0, 10);

/** A plan's dates moved by n days: its dates, review days, events, end and exam. */
export function shifted(doc: Obj, n: number): Obj {
  const out = structuredClone(doc) as Obj & { units: Obj[] };
  for (const u of out.units) for (const k of ["opens", "due", "check"]) if (typeof u[k] === "string") u[k] = shiftDay(u[k] as string, n);
  for (const r of (out.reviews as Obj[] | undefined) || []) r.day = shiftDay(r.day as string, n);
  for (const e of (out.events as Obj[] | undefined) || []) e.day = shiftDay(e.day as string, n);
  if (typeof out.end === "string") out.end = shiftDay(out.end, n);
  const ex = out.exam as Obj | undefined;
  if (ex) for (const k of ["date", "by"]) if (typeof ex[k] === "string") ex[k] = shiftDay(ex[k] as string, n);
  return out;
}

/** POST /plans/{id}/copy {start}: a plan of my own from a listed one (or
 *  one I write), its first date on `start`. It keeps the dates' contents,
 *  events and review days; no followers, notes or co-authors; and it says
 *  whose it was based on. */
export async function copy(req: Request, s: Session, env: Env, [id]: string[]): Promise<Response> {
  const p = await P.getPlan(env, id);
  const author = p.owner === s.uid || (await P.isEditor(env, id, s.uid));
  if (!author && !(p.listed === 1 && p.audience === "code")) throw new HttpError(404, "no_plan");
  const body = await readJson(req);
  if (!V.isDate(body.start) || Object.keys(body).some((k) => k !== "start")) throw V.bad("start");
  await limitOrThrow(env, `plannew:${s.uid}`, 20, 3600);
  const mine = await env.DB.prepare("SELECT COUNT(*) AS n FROM plans WHERE owner = ?").bind(s.uid).first<number>("n");
  if ((mine ?? 0) >= P.PLANS_MAX) throw new HttpError(409, "too_many_plans");
  const doc = JSON.parse(p.doc) as Obj & { units: Obj[] };
  const firsts = [...doc.units.map((u) => u.opens as string), ...((doc.events as Obj[] | undefined) || []).map((e) => e.day as string)].sort();
  const n = firsts.length ? Math.round((Date.parse(body.start as string) - Date.parse(firsts[0])) / 86400000) : 0;
  let clean = JSON.stringify(P.planDoc(shifted(doc, n)));
  await P.roomFor(env, s.uid, clean.length);  // 3.7.2
  const owner = await env.DB.prepare("SELECT name FROM users WHERE uid = ?").bind(p.owner).first<string>("name");
  // 3.9.5: a starter's copy is based on Due Crew's, as its card says
  const credit = JSON.stringify({ id: p.id, name: p.name, owner: p.starter === 1 ? STARTER_BY : owner || "?" });
  const name = p.owner === s.uid ? V.displayName(`${p.name} (copy)`.slice(0, V.NAME_MAX)) : p.name;
  const now = nowSec();
  for (let i = 0; i < 3; i++) {
    const nid = P.draw(16).toLowerCase();
    // 3.8.0: a copy's tags are its own: its root from its own name, its dates following
    const parsed = JSON.parse(clean) as Obj;
    const { doc: own, root } = parsed.tagroot
      ? await P.rooted(env, nid, null, P.reroot(parsed, parsed.tagroot as string, P.tagRoot(name)))
      : { doc: parsed, root: null };
    clean = JSON.stringify(own);
    const r = await env.DB.prepare(
      `INSERT INTO plans (id, code, owner, name, line, doc, based_on, tagroot, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING`,
    ).bind(nid, P.draw(P.PLAN_CODE_LEN), s.uid, name, p.line, clean, p.owner === s.uid ? null : credit, root, now, now).run();
    if (r.meta.changes) {
      await P.logSave(env, nid, 1, s.uid, V.oneLine(`copied from ${p.name}`, 120), null);
      return json(await P.view(env, await P.getPlan(env, nid), s.uid));
    }
  }
  throw new HttpError(503, "try_again");
}

export const PLAN_REPORT_REASONS: Record<string, string> = {
  spam: "Not a study plan",
  copied: "Copied without credit",
  other: "Something else",
};

/** POST /plans/{id}/report {reason, note?}: a listed plan, reported. Kept for
 *  the admin's Inbox (3.8.1) and mailed to REPORT_TO when it's set, with the
 *  plan's id, name and author's uid. Never the reporter's email. */
export async function report(req: Request, s: Session, env: Env, [id]: string[]): Promise<Response> {
  const p = await P.getPlan(env, id);
  if (p.listed !== 1) throw new HttpError(404, "no_plan");
  const body = await readJson(req);
  if (Object.keys(body).some((k) => k !== "reason" && k !== "note")) throw V.bad("report");
  if (typeof body.reason !== "string" || !Object.prototype.hasOwnProperty.call(PLAN_REPORT_REASONS, body.reason)) throw V.bad("reason");
  if (body.note !== undefined && body.note !== null && !V.isStr(body.note, REPORT_NOTE_MAX)) throw V.bad("note");
  if (p.owner === s.uid) throw new HttpError(400, "self");
  await limitOrThrow(env, `report:${s.uid}`, 10, 3600);
  const note = typeof body.note === "string" ? V.oneLine(body.note, REPORT_NOTE_MAX) : "";
  await R.keep(env, { by: s.uid, kind: "plan", target: p.id, reason: body.reason, note,
                      detail: `${p.name} · duecrew.com/p/${p.code} · author ${p.owner}` },
               "Due Crew report: a plan in the library", [
    `Reason: ${PLAN_REPORT_REASONS[body.reason]}`,
    `Note: ${note || "(none)"}`,
    "",
    `Plan: ${p.name} (${p.id})`,
    `Link: https://duecrew.com/p/${p.code}`,
    `Author: ${p.owner}`,
    "",
    `Reporter: ${s.uid}`,
    "",
    "To take it out: duecrew.com/library, Take out on its card.",
  ].join("\n"));
  return json({ ok: true });
}

/** POST /admin/library/{id} {note}: the admin takes a plan out of the
 *  library; its author reads the note on the plan's Settings and can't list
 *  it again. DELETE puts it back to unlisted (the author may list it).
 *  3.9.5: a starter taken out is a starter no more. */
export async function takeOut(req: Request, s: Session, env: Env, [id]: string[]): Promise<Response> {
  if (!isAdmin(env, s.uid)) throw new HttpError(404, "not_found");
  const body = await readJson(req);
  if (!V.isStr(body.note, NOTE_MAX * 4, 1)) throw V.bad("note");
  await P.getPlan(env, id);
  await env.DB.prepare("UPDATE plans SET listed = -1, listed_note = ?, starter = 0 WHERE id = ?").bind(V.oneLine(body.note, NOTE_MAX), id).run();
  return json({ ok: true });
}

export async function putBack(s: Session, env: Env, [id]: string[]): Promise<Response> {
  if (!isAdmin(env, s.uid)) throw new HttpError(404, "not_found");
  await env.DB.prepare("UPDATE plans SET listed = 0, listed_note = NULL WHERE id = ? AND listed = -1").bind(id).run();
  return json({ ok: true });
}

/** 3.9.5, POST /admin/library/{id}/starter {on}: the admin makes a plan
 *  in the library a starter, or not. Only a listed plan is one (taking it
 *  out of the library, by its owner or the admin, ends it). Kept in the
 *  audit log by the plan's name and id. */
export async function setStarter(req: Request, s: Session, env: Env, [id]: string[]): Promise<Response> {
  if (!isAdmin(env, s.uid)) throw new HttpError(404, "not_found");
  const body = await readJson(req);
  if (typeof body.on !== "boolean" || Object.keys(body).some((k) => k !== "on")) throw V.bad("on");
  const p = await P.getPlan(env, id);
  if (body.on && !(p.listed === 1 && p.audience === "code")) throw new HttpError(409, "not_listed");
  if ((p.starter ?? 0) !== (body.on ? 1 : 0)) {
    // still listed as it's written, or nothing is
    const r = await env.DB.prepare(`UPDATE plans SET starter = ? WHERE id = ?${body.on ? " AND listed = 1 AND audience = 'code'" : ""}`)
      .bind(body.on ? 1 : 0, id).run();
    if (!r.meta.changes) throw new HttpError(409, "not_listed");
    await logAction(env, body.on ? "made a starter" : "took a starter off", { detail: `${p.name.slice(0, 80)} (plan ${id})` });
  }
  return json({ ok: true, starter: body.on });
}

/** For the admin: plans taken out, to put back. Public names only. */
export async function takenOut(s: Session, env: Env): Promise<Response> {
  if (!isAdmin(env, s.uid)) throw new HttpError(404, "not_found");
  const rows = await env.DB.prepare(
    `SELECT p.id, p.code, p.name, p.listed_note, u.name AS owner_name FROM plans p LEFT JOIN users u ON u.uid = p.owner
      WHERE p.listed = -1 ORDER BY p.updated_at DESC LIMIT 100`,
  ).all<{ id: string; code: string; name: string; listed_note: string | null; owner_name: string | null }>();
  return json({ plans: rows.results.map((r) => ({ id: r.id, code: r.code, name: r.name, note: r.listed_note || "", ownerName: r.owner_name || "?" })) });
}
