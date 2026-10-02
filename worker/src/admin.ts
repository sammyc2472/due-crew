// The admin's page (3.2, 3.5 X): counts only, never names or emails. Today's
// counts, their history (a daily snapshot in admin_days), sign-in steps
// and the bridge's runs as counters on today's row, how far the cutover
// from 2.x has come, and the bridge's last run.

import type { Session } from "./auth";
import { isAdmin } from "./notices";
import { Env, HttpError, json, nowSec, ulid } from "./util";

const day = (t = nowSec()) => new Date(t * 1000).toISOString().slice(0, 10);
const RANGES = [30, 90, 365];

/** Adds to one of today's counters. A counter never stops what it counts. */
export async function bump(env: Env, key: string, by = 1): Promise<void> {
  try {
    await env.DB.prepare(
      "INSERT INTO admin_days (day, key, n) VALUES (?, ?, ?) ON CONFLICT(day, key) DO UPDATE SET n = n + excluded.n",
    ).bind(day(), key, by).run();
  } catch { /* a count, not the sign-in */ }
}

/** One line in the admin's audit log (mock "Admin, grown up", A5): what,
 *  to whose account or which squad, and a detail that never holds an
 *  email, a code or a token. Kept a year. */
export async function logAction(env: Env, action: string, at: { uid?: string; squad?: string; detail?: string } = {}): Promise<void> {
  try {
    await env.DB.prepare("INSERT INTO admin_actions (id, at, action, uid, squad, detail) VALUES (?, ?, ?, ?, ?, ?)")
      .bind(ulid(), nowSec(), action, at.uid ?? null, at.squad ?? null, (at.detail ?? "").slice(0, 200)).run();
  } catch {
    // what was done is done: a lost log line mustn't send a code or an email twice on a retry
    console.log(`due crew: couldn't log an admin action (${action})`);
  }
}

const ACTION_ROWS = `SELECT a.id, a.at, a.action, a.uid, a.squad, a.detail, u.uid AS uhere, u.name AS uname, q.name AS qname
  FROM admin_actions a LEFT JOIN users u ON u.uid = a.uid LEFT JOIN squads q ON q.id = a.squad`;

/** The log's rows as the page shows them: names looked up now, so a
 *  deleted account reads as one. */
export function actionRows(rows: any[]) {
  return rows.map((r) => ({
    id: r.id, at: r.at, action: r.action, detail: r.detail,
    uid: r.uid || "", who: r.uid ? (r.uhere ? r.uname || "?" : "a deleted account") : "",
    squad: r.squad || "", squadName: r.squad ? (r.qname ?? "a deleted squad") : "",
  }));
}

export async function actionsFor(env: Env, where: "uid" | "squad", id: string, limit = 20) {
  const rows = await env.DB.prepare(`${ACTION_ROWS} WHERE a.${where} = ? ORDER BY a.at DESC, a.id DESC LIMIT ?`).bind(id, limit).all();
  return actionRows(rows.results as any[]);
}

/** GET /admin/actions[?before=id]: the audit log, newest first, 100 a page. */
export async function actions(req: Request, s: Session, env: Env): Promise<Response> {
  if (!isAdmin(env, s.uid)) throw new HttpError(404, "not_found");
  const before = new URL(req.url).searchParams.get("before") || "";
  const rows = /^[0-9A-Z]{26}$/.test(before)
    ? await env.DB.prepare(`${ACTION_ROWS} WHERE a.id < ? ORDER BY a.id DESC LIMIT 100`).bind(before).all()
    : await env.DB.prepare(`${ACTION_ROWS} ORDER BY a.id DESC LIMIT 100`).all();
  const out = actionRows(rows.results as any[]);
  return json({ actions: out, more: out.length === 100 ? out[out.length - 1].id : null });
}

/** The counts the page shows and the cron keeps. */
async function counts(env: Env) {
  const now = nowSec();
  const q = (sql: string, ...b: unknown[]) => env.DB.prepare(sql).bind(...b);
  const rs = await env.DB.batch([
    q("SELECT COUNT(*) AS n FROM users"),
    q("SELECT COUNT(*) AS n FROM users WHERE client_version LIKE '3.%'"),
    q("SELECT COUNT(*) AS n FROM users WHERE last_seen > ?", now - 7 * 86400),
    q("SELECT COUNT(*) AS n FROM users WHERE last_seen > ?", now - 86400),
    q("SELECT COUNT(*) AS n FROM friends"),
    q("SELECT COUNT(*) AS n FROM friends f JOIN friends b ON b.owner = f.friend AND b.friend = f.owner"),
    q("SELECT COUNT(*) AS n FROM squads"),
    q("SELECT COUNT(*) AS n FROM members"),
    q("SELECT COUNT(*) AS n FROM plans"),
    q("SELECT COUNT(*) AS n FROM plan_follows"),
    q("SELECT COUNT(*) AS n FROM tips"),
    // the cutover: on 2.x and still studying (the bridge brings their week in)
    q(`SELECT COUNT(*) AS n FROM users u JOIN weeks w ON w.uid = u.uid
        WHERE (u.client_version IS NULL OR u.client_version NOT LIKE '3.%') AND w.updated_at > ?`, now - 7 * 86400),
    q("SELECT COUNT(*) AS n FROM plans WHERE listed = 1"),
    q("SELECT COUNT(*) AS n FROM plans WHERE listed = -1"),
  ]);
  const n = (i: number) => (rs[i].results[0] as { n: number }).n;
  return {
    accounts: n(0), on3: n(1), seenWeek: n(2), seenDay: n(3),
    friendEdges: n(4), mutualPairs: n(5) / 2, squads: n(6), memberships: n(7),
    plans: n(8), follows: n(9), tips: n(10), active2: n(11), listed: n(12), takenOut: n(13),
  };
}

// the daily snapshot's keys (accounts come from users.created_at instead)
const KEPT = ["on3", "seenWeek", "seenDay", "mutualPairs", "squads", "memberships", "plans", "follows", "tips", "active2", "listed"] as const;

/** The daily cron: today's counts, kept. */
export async function snapshot(env: Env): Promise<void> {
  const c = await counts(env);
  const d = day();
  await env.DB.batch(KEPT.map((k) => env.DB.prepare("INSERT OR REPLACE INTO admin_days (day, key, n) VALUES (?, ?, ?)").bind(d, `n.${k}`, c[k])));
}

/** After each bridge run: its numbers, or the first line of what went wrong. */
export async function bridgeRan(env: Env, ms: number, r: { pulled: number; pushed: number } | null, error?: unknown): Promise<void> {
  const msg = error === undefined ? null : String((error as Error)?.message || error).split("\n")[0].slice(0, 120);
  await env.DB.prepare(
    "INSERT OR REPLACE INTO bridge_last (id, at, ms, pulled, pushed, error) VALUES (1, ?, ?, ?, ?, ?)",
  ).bind(nowSec(), Math.round(ms), r?.pulled ?? 0, r?.pushed ?? 0, msg).run();
  await bump(env, "bridge.runs");
  if (msg !== null) await bump(env, "bridge.failed");
}

function adminOnly(env: Env, s: Session) {
  if (!isAdmin(env, s.uid)) throw new HttpError(404, "not_found");
}

/** GET /admin/stats: today's counts, the cutover, sign-in codes over the
 *  last 7 days, the bridge's last run, the library, versions. */
export async function stats(s: Session, env: Env): Promise<Response> {
  adminOnly(env, s);
  const c = await counts(env);
  const since = day(nowSec() - 6 * 86400);
  const [codes, bridge, versions, fbOpen, moving] = await env.DB.batch<any>([
    env.DB.prepare("SELECT key, SUM(n) AS n FROM admin_days WHERE day >= ? AND key LIKE 'codes.%' GROUP BY key").bind(since),
    env.DB.prepare("SELECT at, ms, pulled, pushed, error FROM bridge_last WHERE id = 1"),
    env.DB.prepare("SELECT client_version AS v, COUNT(*) AS n FROM users GROUP BY client_version ORDER BY n DESC LIMIT 12"),
    // what's waiting on the admin (A2's Needs you): new feedback, email changes not yet finished
    env.DB.prepare("SELECT COUNT(*) AS n FROM feedback WHERE done = 0"),
    env.DB.prepare(`SELECT c.uid, u.name, c.at FROM email_changes c JOIN users u ON u.uid = c.uid
                      WHERE c.at > ? ORDER BY c.at DESC LIMIT 10`).bind(nowSec() - 7 * 86400),
  ]);
  const code = Object.fromEntries((codes.results as { key: string; n: number }[]).map((r) => [r.key.slice(6), r.n]));
  const today = await env.DB.prepare("SELECT key, n FROM admin_days WHERE day = ? AND key LIKE 'bridge.%'").bind(day()).all<{ key: string; n: number }>();
  const b = bridge.results[0] as { at: number; ms: number; pulled: number; pushed: number; error: string | null } | undefined;
  return json({
    ...c,
    cutover: { on3: c.on3, active2: c.active2, quiet: Math.max(0, c.accounts - c.on3 - c.active2) },
    codes: { sent: code.sent ?? 0, ok: code.ok ?? 0, wrong: code.wrong ?? 0, out: code.out ?? 0, limited: code.limited ?? 0 },
    bridge: b ? { ...b, runsToday: today.results.find((r) => r.key === "bridge.runs")?.n ?? 0,
                  failedToday: today.results.find((r) => r.key === "bridge.failed")?.n ?? 0 } : null,
    versions: (versions.results as { v: string | null; n: number }[]).map((r) => [r.v || "2.x", r.n]),
    feedbackOpen: (fbOpen.results[0] as { n: number }).n,
    emailChanges: (moving.results as { uid: string; name: string | null; at: number }[]).map((r) => ({ uid: r.uid, name: r.name || "?", at: r.at })),
  });
}

/** GET /admin/trends?days=30|90|365: each kept count by day (null before it
 *  was kept), and accounts by day from when each was made. */
export async function trends(req: Request, s: Session, env: Env): Promise<Response> {
  adminOnly(env, s);
  const asked = Number(new URL(req.url).searchParams.get("days"));
  const n = RANGES.includes(asked) ? asked : 90;
  const days = Array.from({ length: n }, (_, i) => day(nowSec() - (n - 1 - i) * 86400));
  const [rows, made, before] = await env.DB.batch<any>([
    env.DB.prepare("SELECT day, key, n FROM admin_days WHERE day >= ? AND key LIKE 'n.%'").bind(days[0]),
    env.DB.prepare("SELECT date(created_at, 'unixepoch') AS d, COUNT(*) AS n FROM users WHERE created_at >= ? GROUP BY d")
      .bind(Math.floor(Date.parse(`${days[0]}T00:00:00Z`) / 1000)),
    env.DB.prepare("SELECT COUNT(*) AS n FROM users WHERE created_at < ?").bind(Math.floor(Date.parse(`${days[0]}T00:00:00Z`) / 1000)),
  ]);
  const at = new Map(days.map((d, i) => [d, i]));
  const series: Record<string, (number | null)[]> = {};
  for (const k of KEPT) series[k] = days.map(() => null);
  for (const r of rows.results as { day: string; key: string; n: number }[]) {
    const i = at.get(r.day), k = r.key.slice(2);
    if (i !== undefined && series[k]) series[k][i] = r.n;
  }
  const perDay = new Map((made.results as { d: string; n: number }[]).map((r) => [r.d, r.n]));
  let total = (before.results[0] as { n: number }).n;
  series.accounts = days.map((d) => (total += perDay.get(d) ?? 0));
  return json({ days, series });
}
