// Fixed-window counters in D1. One upsert per hit; enough at this scale.

import { Env, HttpError, nowSec } from "./util";

/** Count one hit on `key`; true while the window's count is within `max`. */
export async function hit(env: Env, key: string, max: number, windowSec: number): Promise<boolean> {
  const now = nowSec();
  const stale = now - windowSec;
  const row = await env.DB.prepare(
    `INSERT INTO limits (key, count, window_start) VALUES (?1, 1, ?2)
     ON CONFLICT(key) DO UPDATE SET
       count = CASE WHEN window_start <= ?3 THEN 1 ELSE count + 1 END,
       window_start = CASE WHEN window_start <= ?3 THEN ?2 ELSE window_start END
     RETURNING count`,
  ).bind(key, now, stale).first<{ count: number }>();
  return (row?.count ?? 1) <= max;
}

/** The window's count so far, without counting. */
export async function peek(env: Env, key: string, windowSec: number): Promise<number> {
  const row = await env.DB.prepare("SELECT count, window_start FROM limits WHERE key = ?")
    .bind(key).first<{ count: number; window_start: number }>();
  if (!row || row.window_start <= nowSec() - windowSec) return 0;
  return row.count;
}

export async function limitOrThrow(env: Env, key: string, max: number, windowSec: number): Promise<void> {
  if (!(await hit(env, key, max, windowSec))) throw new HttpError(429, "slow_down", { retryAfter: windowSec });
}
