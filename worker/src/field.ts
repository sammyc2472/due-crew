// 3.9.9, Know when it breaks (Sam's sign-off): each install counts what went
// wrong in it by code (the add-on's errs.py: save:bad_plan, py:<module>:
// <function>:<type>, cmd:unknown, req:plans.:id:400), never by content, and a
// day's counts ride the first sync after that day ends, once (POST /sync's
// errs). Kept only added up, by day, version and code (field_errs, migration
// 0030): no uid, and `people` counts people because a person sends a day
// once. The admin's Inbox reads a day of it (GET /admin/field). Kept 30 days
// (housekeeping).

import type { Session } from "./auth";
import { isAdmin } from "./notices";
import { Env, HttpError, json } from "./util";
import * as V from "./validate";

export const DAYS_MAX = 7;       // days a sync carries, within the sender's last 7 (their Anki day)
export const CODES_MAX = 50;     // a day's codes
export const COUNT_MAX = 9999;   // a code's count, a day
export const KEEP_DAYS = 30;
export const ROWS_MAX = 500;     // a day's codes the admin's page lists
export const CODE_RE = /^[a-z0-9_.:-]{1,80}$/;
export const VERSION_RE = /^\d{1,4}(\.\d{1,4}){0,3}$/;
const ROWS_PER_STATEMENT = 30;   // 1 + 3 bound values a row: under D1's 100

export type Errs = { v: string; days: { day: string; codes: [string, number][] }[] };

/** A day `n` days from `day` (both ISO dates). */
export const dayShift = (day: string, n: number) =>
  new Date(Date.parse(`${day}T00:00:00Z`) + n * 86400_000).toISOString().slice(0, 10);

/** A sync's errs, {days: {"2026-11-07": {"save:bad_plan": 2}}, v: "3.9.9"}: at
 *  most DAYS_MAX days, each a real date with 1 to CODES_MAX codes, each code of
 *  the alphabet and at most 80 long, each count 1 to COUNT_MAX; else bad_errs. */
export function errsPart(v: unknown): Errs {
  if (!V.isObj(v) || Object.keys(v).some((k) => k !== "v" && k !== "days")
      || !V.isStr(v.v, 20, 1) || !VERSION_RE.test(v.v) || !V.isObj(v.days)) throw V.bad("errs");
  const days = Object.entries(v.days);
  if (days.length > DAYS_MAX) throw V.bad("errs");
  return {
    v: v.v,
    days: days.map(([day, codes]) => {
      if (!V.isDate(day) || !V.isObj(codes)) throw V.bad("errs");
      const list = Object.entries(codes);
      if (!list.length || list.length > CODES_MAX
          || !list.every(([c, n]) => CODE_RE.test(c) && V.isInt(n, 1, COUNT_MAX))) throw V.bad("errs");
      return { day, codes: list as [string, number][] };
    }),
  };
}

/** A sync's errs as writes: each code's count added to its day's and one more
 *  person, for the days in the sender's last DAYS_MAX (today, their Anki day,
 *  included: a clock a little ahead). Any other day isn't kept. A few rows a
 *  statement; none when there's nothing. */
export function errsWrites(env: Env, e: Errs, today: string): D1PreparedStatement[] {
  const lo = dayShift(today, -DAYS_MAX);
  const rows = e.days.filter((d) => d.day >= lo && d.day <= today)
    .flatMap((d) => d.codes.map(([code, n]) => [d.day, code, n] as const));
  const out: D1PreparedStatement[] = [];
  for (let i = 0; i < rows.length; i += ROWS_PER_STATEMENT) {
    const chunk = rows.slice(i, i + ROWS_PER_STATEMENT);
    const values = chunk.map((_, j) => `(?${3 * j + 2}, ?1, ?${3 * j + 3}, ?${3 * j + 4}, 1)`).join(", ");
    out.push(env.DB.prepare(
      `INSERT INTO field_errs (day, version, code, n, people) VALUES ${values}
       ON CONFLICT(day, version, code) DO UPDATE SET n = n + excluded.n, people = people + 1`,
    ).bind(e.v, ...chunk.flat()));
  }
  return out;
}

/** Housekeeping's part: what's older than KEEP_DAYS goes (daily, so at most once a day). */
export function keepStmt(env: Env, now: number): D1PreparedStatement {
  const today = new Date(now * 1000).toISOString().slice(0, 10);
  return env.DB.prepare("DELETE FROM field_errs WHERE day < ?").bind(dayShift(today, -KEEP_DAYS));
}

const newestFirst = (a: string, b: string) => {
  const x = a.split(".").map(Number), y = b.split(".").map(Number);
  for (let i = 0; i < Math.max(x.length, y.length); i++) if ((x[i] ?? 0) !== (y[i] ?? 0)) return (y[i] ?? 0) - (x[i] ?? 0);
  return 0;
};

/** GET /admin/field[?day=2026-11-07]: a day's codes (yesterday's, UTC, unless
 *  asked), most first, each with how many times, how many people and the
 *  versions it came from; and which are new since the day before. Admins only. */
export async function field(req: Request, s: Session, env: Env): Promise<Response> {
  if (!isAdmin(env, s.uid)) throw new HttpError(404, "not_found");
  const asked = new URL(req.url).searchParams.get("day") || "";
  const day = V.isDate(asked) ? asked : dayShift(new Date().toISOString().slice(0, 10), -1);
  const before = dayShift(day, -1);
  const [rows, prev] = await env.DB.batch<any>([
    env.DB.prepare(
      `SELECT code, SUM(n) AS n, SUM(people) AS people, group_concat(DISTINCT version) AS versions
         FROM field_errs WHERE day = ? GROUP BY code ORDER BY n DESC, code LIMIT ?`).bind(day, ROWS_MAX),
    env.DB.prepare("SELECT DISTINCT code FROM field_errs WHERE day = ?").bind(before),
  ]);
  const had = new Set((prev.results as { code: string }[]).map((r) => r.code));
  const list = (rows.results as { code: string; n: number; people: number; versions: string | null }[]).map((r) => ({
    code: r.code, n: r.n, people: r.people,
    versions: String(r.versions || "").split(",").filter(Boolean).sort(newestFirst),
  }));
  return json({ day, before, beforeCodes: had.size, rows: list, new: list.filter((r) => !had.has(r.code)).map((r) => r.code) });
}
