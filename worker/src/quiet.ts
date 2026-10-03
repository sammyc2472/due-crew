// Quiet accounts ("The next round", Q1-Q6). Activity is the newest of a
// sync or a board read (users.last_seen), a week the 2.x bridge brought
// in, and the account's creation. Three steps, each undone by coming back:
// after 90 days crewmates' boards fold the person into one line (the
// clients do that, from when they last synced); after 6 months only what
// a sync rebuilds goes (shared decks, the heatmap, a plan's deck tree,
// cards known); after 12 months (24 when paused) the account is deleted as
// Delete my account does it, except that a plan anyone follows outlives
// its owner (its first co-author takes it, or it stays as it is, "by a
// former member"). A hash of the uid is kept a year so the add-on can say
// why. At most PER_DAY of each a day, so a bug can't empty the server.

import { deleteAccount } from "./auth";
import { logAction } from "./admin";
import { isAdmin } from "./notices";
import { Env, json, nowSec, sha256Hex } from "./util";

export const DAY = 86400;
export const FOLD_DAYS = 90;
export const TRIM_DAYS = 183;
export const DELETE_DAYS = 365;
export const PAUSED_DAYS = 730;
const PER_DAY = 50;
const GONE_KEEP = 365 * DAY;

const ACTIVE = "MAX(COALESCE(u.last_seen, 0), u.created_at, COALESCE(w.updated_at, 0))";
const PAUSED = "COALESCE(json_extract(t.json, '$.paused'), 0) = 1";
const FROM = "FROM users u LEFT JOIN weeks w ON w.uid = u.uid LEFT JOIN settings t ON t.uid = u.uid";

export const goneHash = (uid: string) => sha256Hex(`gone:${uid}`);

/** The daily job's part: trim, then delete. Returns the counts. */
export async function run(env: Env, now = nowSec()): Promise<{ trimmed: number; deleted: number }> {
  const db = env.DB;
  const trim = await db.prepare(
    `SELECT u.uid ${FROM} WHERE ${ACTIVE} < ?1 AND (
       EXISTS (SELECT 1 FROM decks WHERE uid = u.uid) OR EXISTS (SELECT 1 FROM heatmaps WHERE uid = u.uid)
       OR EXISTS (SELECT 1 FROM plan_trees WHERE uid = u.uid) OR EXISTS (SELECT 1 FROM knows WHERE uid = u.uid))
     LIMIT ?2`).bind(now - TRIM_DAYS * DAY, PER_DAY).all<{ uid: string }>();
  for (const { uid } of trim.results) {
    await db.batch(["decks", "heatmaps", "plan_trees", "knows"].map((t) => db.prepare(`DELETE FROM ${t} WHERE uid = ?`).bind(uid)));
  }
  const del = await db.prepare(
    `SELECT u.uid, ${PAUSED} AS paused ${FROM}
      WHERE (NOT ${PAUSED} AND ${ACTIVE} < ?1) OR (${PAUSED} AND ${ACTIVE} < ?2) LIMIT ?3`,
  ).bind(now - DELETE_DAYS * DAY, now - PAUSED_DAYS * DAY, PER_DAY).all<{ uid: string; paused: number }>();
  let deleted = 0;
  for (const { uid, paused } of del.results) {
    if (isAdmin(env, uid)) continue;
    await keepFollowedPlans(env, uid);
    await deleteAccount({ uid, tokenHash: "" }, env);
    await db.prepare("INSERT INTO gone (h, at) VALUES (?, ?) ON CONFLICT(h) DO UPDATE SET at = excluded.at").bind(await goneHash(uid), now).run();
    await logAction(env, paused ? "deleted, 24 months quiet (paused)" : "deleted, 12 months quiet", { uid });
    deleted++;
  }
  await db.prepare("DELETE FROM gone WHERE at <= ?").bind(now - GONE_KEEP).run();
  return { trimmed: trim.results.length, deleted };
}

/** Q6: a plan someone follows passes to its first co-author, or stays as it
 *  is with no owner ("by a former member": followable, never edited). */
async function keepFollowedPlans(env: Env, uid: string) {
  const db = env.DB;
  const plans = await db.prepare(
    "SELECT id FROM plans p WHERE owner = ? AND EXISTS (SELECT 1 FROM plan_follows f WHERE f.plan = p.id AND f.uid != p.owner)",
  ).bind(uid).all<{ id: string }>();
  for (const { id } of plans.results) {
    const ed = await db.prepare("SELECT uid FROM plan_editors WHERE plan = ? AND uid != ? ORDER BY at, uid LIMIT 1").bind(id, uid).first<string>("uid");
    await db.batch(ed
      ? [db.prepare("UPDATE plans SET owner = ? WHERE id = ?").bind(ed, id), db.prepare("DELETE FROM plan_editors WHERE plan = ? AND uid = ?").bind(id, ed)]
      : [db.prepare("UPDATE plans SET owner = '' WHERE id = ?").bind(id)]);
  }
}

/** For the admin's Today: how many are folded, trimmed, and due to go in 30 days. */
export async function counts(env: Env, now = nowSec()) {
  const q = (where: string, ...b: number[]) => env.DB.prepare(`SELECT COUNT(*) AS n ${FROM} WHERE ${where}`).bind(...b);
  const [f, t, d] = await env.DB.batch<{ n: number }>([
    q(`${ACTIVE} < ?1 AND ${ACTIVE} >= ?2`, now - FOLD_DAYS * DAY, now - TRIM_DAYS * DAY),
    q(`${ACTIVE} < ?1`, now - TRIM_DAYS * DAY),
    q(`(NOT ${PAUSED} AND ${ACTIVE} < ?1) OR (${PAUSED} AND ${ACTIVE} < ?2)`, now - (DELETE_DAYS - 30) * DAY, now - (PAUSED_DAYS - 30) * DAY),
  ]);
  return { folded: f.results[0]?.n ?? 0, quiet: t.results[0]?.n ?? 0, dueSoon: d.results[0]?.n ?? 0 };
}

/** GET /auth/gone?uid=: was this account deleted for being quiet? Signed
 *  out, so the add-on can say so; a yes or no, nothing else. */
export async function gone(req: Request, env: Env): Promise<Response> {
  const uid = new URL(req.url).searchParams.get("uid") || "";
  if (!/^[A-Za-z0-9_-]{1,128}$/.test(uid)) return json({ gone: false });
  const hit = await env.DB.prepare("SELECT 1 FROM gone WHERE h = ?").bind(await goneHash(uid)).first();
  return json({ gone: !!hit, after: hit ? DELETE_DAYS : undefined });
}
