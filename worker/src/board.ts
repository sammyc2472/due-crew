// The two calls a client makes all day: GET /board (everything a refresh
// shows, in one request) and POST /sync (everything a sync uploads, in
// one request). Plus the lazy reads: shared decks, a heatmap, settings.

import type { Session } from "./auth";
import { listKnocks } from "./social";
import * as V from "./validate";
import { Env, HttpError, json, nowSec, readJson } from "./util";

const SEEN_EVERY = 3600;  // users.last_seen is written at most hourly
const SQUADS_PER_SYNC = 20;

export const iso = (sec: number | null | undefined) => (sec ? new Date(sec * 1000).toISOString().replace(/\.\d{3}Z$/, "Z") : "");

async function touchSeen(env: Env, uid: string) {
  const now = nowSec();
  await env.DB.prepare("UPDATE users SET last_seen = ? WHERE uid = ? AND (last_seen IS NULL OR last_seen <= ?)")
    .bind(now, uid, now - SEEN_EVERY).run();
}

/** GET /board[?decks=1]: me, the people I added (with their week when they
 *  added me back, name and emoji only when they haven't yet), my cheers
 *  (delivered once: they go as they're read), my knocks. One request. */
export async function board(req: Request, s: Session, env: Env): Promise<Response> {
  const withDecks = new URL(req.url).searchParams.get("decks") === "1";
  const db = env.DB;
  const [meRes, friendsRes, cheersRes] = await db.batch([
    db.prepare(
      `SELECT u.uid, u.name, u.emoji, u.code, w.doc, w.updated_at FROM users u
       LEFT JOIN weeks w ON w.uid = u.uid WHERE u.uid = ?`).bind(s.uid),
    // a week leaves the server only for someone its owner added
    db.prepare(
      `SELECT f.friend AS uid, u.name, u.emoji,
              EXISTS (SELECT 1 FROM friends b WHERE b.owner = f.friend AND b.friend = ?1) AS mutual,
              CASE WHEN EXISTS (SELECT 1 FROM friends b WHERE b.owner = f.friend AND b.friend = ?1)
                   THEN w.doc END AS doc,
              CASE WHEN EXISTS (SELECT 1 FROM friends b WHERE b.owner = f.friend AND b.friend = ?1)
                   THEN w.updated_at END AS updated_at
       FROM friends f JOIN users u ON u.uid = f.friend LEFT JOIN weeks w ON w.uid = f.friend
       WHERE f.owner = ?1 ORDER BY f.at, f.friend`).bind(s.uid),
    db.prepare(
      `SELECT c.from_uid, c.emoji, c.note, c.luck, c.guid, c.at FROM cheers c WHERE c.to_uid = ?`).bind(s.uid),
  ]);
  const me = meRes.results[0] as any;
  if (!me) throw new HttpError(401, "auth");
  const friends = (friendsRes.results as any[]).map((f) => f.mutual
    ? { uid: f.uid, name: f.name || "?", emoji: f.emoji || "", mutual: true,
        week: f.doc ? JSON.parse(f.doc) : null, updatedAt: iso(f.updated_at) }
    : { uid: f.uid, name: f.name || "?", emoji: f.emoji || "", mutual: false });
  const byUid = new Map(friends.map((f) => [f.uid, f]));
  const cheers = [];
  for (const c of cheersRes.results as any[]) {
    const from = byUid.get(c.from_uid);
    if (!from?.mutual) continue;  // added me once, not any more (or never back): dropped
    cheers.push({ from: c.from_uid, name: from.name, emoji: c.emoji, note: c.note || "",
                  luck: c.luck === 1, guid: c.guid || "", at: iso(c.at) });
  }
  if (cheersRes.results.length) {
    // delivered, or no longer deliverable: either way done. Only the ones
    // read go: a cheer landing mid-request waits for the next refresh.
    await db.batch((cheersRes.results as any[]).map((c) => db.prepare(
      "DELETE FROM cheers WHERE to_uid = ? AND from_uid = ? AND at = ?").bind(s.uid, c.from_uid, c.at)));
  }
  const out: Record<string, unknown> = {
    me: { uid: me.uid, name: me.name || "", emoji: me.emoji || "", code: me.code || "",
          week: me.doc ? JSON.parse(me.doc) : null, updatedAt: iso(me.updated_at) },
    friends, cheers, knocks: await listKnocks(env, s.uid),
  };
  if (withDecks) out.decks = await decksFor(env, s.uid);
  await touchSeen(env, s.uid);
  return json(out);
}

async function decksFor(env: Env, uid: string): Promise<Record<string, unknown>> {
  const rows = await env.DB.prepare(
    `SELECT d.uid, d.json FROM decks d WHERE d.uid = ?1 OR d.uid IN
       (SELECT f.friend FROM friends f JOIN friends b ON b.owner = f.friend AND b.friend = ?1 WHERE f.owner = ?1)`,
  ).bind(uid).all<{ uid: string; json: string }>();
  return Object.fromEntries(rows.results.map((r) => [r.uid, JSON.parse(r.json)]));
}

/** GET /decks: shared-deck progress, mine and my mutual friends'. */
export async function getDecks(s: Session, env: Env): Promise<Response> {
  return json({ decks: await decksFor(env, s.uid) });
}

/** GET /heatmap/{uid}: mine, or a mutual friend's. {counts: null} when
 *  they don't share one. */
export async function getHeatmap(s: Session, env: Env, [uid]: string[]): Promise<Response> {
  if (uid !== s.uid) {
    const n = await env.DB.prepare(
      "SELECT COUNT(*) AS n FROM friends WHERE (owner = ?1 AND friend = ?2) OR (owner = ?2 AND friend = ?1)",
    ).bind(s.uid, uid).first<number>("n");
    if (n !== 2) throw new HttpError(403, "not_friends");
  }
  const row = await env.DB.prepare("SELECT json FROM heatmaps WHERE uid = ?").bind(uid).first<string>("json");
  return json({ counts: row ? JSON.parse(row).counts : null });
}

/** POST /sync: whatever changed since the last one, in one body. Each part
 *  is optional, and a part the server already holds verbatim isn't written:
 *  an unchanged day costs no writes. */
export async function sync(req: Request, s: Session, env: Env): Promise<Response> {
  const body = await readJson(req);
  for (const k of Object.keys(body)) {
    if (!["profile", "week", "decks", "heatmap", "squads", "settings"].includes(k)) throw V.bad("sync");
  }
  // validate everything before writing anything
  const profile = "profile" in body ? V.profile(body.profile) : null;
  const week = "week" in body ? JSON.stringify(V.week(body.week)) : null;
  const decks = "decks" in body ? JSON.stringify(V.decks(body.decks)) : null;
  const heat = "heatmap" in body ? (body.heatmap === null ? null : JSON.stringify(V.heatmap(body.heatmap))) : undefined;
  const settings = "settings" in body ? V.settingsDoc(body.settings) : null;
  let squads: { row: ReturnType<typeof V.memberRow>; ids: string[] } | null = null;
  if ("squads" in body) {
    const sq = body.squads;
    if (!V.isObj(sq) || !Array.isArray(sq.ids) || sq.ids.length > SQUADS_PER_SYNC
        || !sq.ids.every((x) => V.isStr(x, 40, 1))) throw V.bad("squads");
    squads = { row: V.memberRow(sq.row), ids: [...new Set(sq.ids as string[])] };
  }

  const db = env.DB;
  const now = nowSec();
  const wrote: Record<string, boolean> = {};
  const [cur] = await db.batch([
    db.prepare(`SELECT u.name, u.emoji, u.client_version, u.tz, u.rollover, w.doc AS week,
                d.json AS decks, h.json AS heat, st.v AS sv, st.at AS sat, st.json AS sjson
                FROM users u LEFT JOIN weeks w ON w.uid = u.uid LEFT JOIN decks d ON d.uid = u.uid
                LEFT JOIN heatmaps h ON h.uid = u.uid LEFT JOIN settings st ON st.uid = u.uid
                WHERE u.uid = ?`).bind(s.uid),
  ]);
  const have = cur.results[0] as any;
  if (!have) throw new HttpError(401, "auth");
  const writes: D1PreparedStatement[] = [];

  if (profile) {
    const sets: string[] = [];
    const vals: unknown[] = [];
    for (const [k, v] of Object.entries(profile)) {
      if (have[k] !== v) {
        sets.push(`${k} = ?`);
        vals.push(v);
      }
    }
    wrote.profile = sets.length > 0;
    if (sets.length) writes.push(db.prepare(`UPDATE users SET ${sets.join(", ")} WHERE uid = ?`).bind(...vals, s.uid));
  }
  if (week !== null) {
    wrote.week = week !== have.week;
    if (wrote.week) {
      writes.push(db.prepare(
        `INSERT INTO weeks (uid, doc, updated_at) VALUES (?, ?, ?)
         ON CONFLICT(uid) DO UPDATE SET doc = excluded.doc, updated_at = excluded.updated_at`).bind(s.uid, week, now));
    }
  }
  if (decks !== null) {
    wrote.decks = decks !== have.decks;
    if (wrote.decks) {
      writes.push(db.prepare(
        "INSERT INTO decks (uid, json) VALUES (?, ?) ON CONFLICT(uid) DO UPDATE SET json = excluded.json").bind(s.uid, decks));
    }
  }
  if (heat !== undefined) {
    wrote.heatmap = heat !== (have.heat ?? null);
    if (wrote.heatmap) {
      writes.push(heat === null
        ? db.prepare("DELETE FROM heatmaps WHERE uid = ?").bind(s.uid)
        : db.prepare("INSERT INTO heatmaps (uid, json) VALUES (?, ?) ON CONFLICT(uid) DO UPDATE SET json = excluded.json")
          .bind(s.uid, heat));
    }
  }
  if (settings) {
    wrote.settings = !(have.sv === settings.v && have.sat === settings.at && have.sjson === settings.json);
    if (wrote.settings) writes.push(putSettingsStmt(env, s.uid, settings));
  }

  // squad rows: an UPDATE, never an insert. A row can't make me a member;
  // only a join does (the bug where Remove undid itself, 2.3.0-2.5.0).
  let gone: string[] = [];
  const squadAt: number[] = [];
  if (squads && squads.ids.length) {
    const r = squads.row;
    const mine = await db.prepare(
      `SELECT squad FROM members WHERE uid = ? AND squad IN (${squads.ids.map(() => "?").join(",")})`,
    ).bind(s.uid, ...squads.ids).all<{ squad: string }>();
    const member = new Set(mine.results.map((m) => m.squad));
    gone = squads.ids.filter((id) => !member.has(id));
    for (const id of member) {
      squadAt.push(writes.length);
      writes.push(db.prepare(
        `UPDATE members SET name = COALESCE(?3, name), day = ?4, reviews = ?5, study_time_ms = ?6,
           accuracy = ?7, streak = ?8, week = ?9, emoji = ?10, new_cards = ?11, updated_at = ?12
         WHERE squad = ?1 AND uid = ?2 AND NOT (name IS COALESCE(?3, name) AND day IS ?4
           AND reviews IS ?5 AND study_time_ms IS ?6 AND accuracy IS ?7 AND streak IS ?8
           AND week IS ?9 AND emoji IS ?10 AND new_cards IS ?11)`,
      ).bind(id, s.uid, r.name, r.day, r.reviews, r.study_time_ms, r.accuracy, r.streak, r.week,
             r.emoji, r.new_cards, now));
    }
  }
  if (writes.length) {
    const results = await db.batch(writes);  // one transaction
    // a row UPDATE that matched nothing had nothing new to say
    if (squads) wrote.squads = squadAt.some((i) => (results[i].meta.changes ?? 0) > 0);
  } else if (squads) wrote.squads = false;
  await touchSeen(env, s.uid);
  return json({ ok: true, gone, wrote });
}

// ---- settings (2.13): mine only ----

function putSettingsStmt(env: Env, uid: string, s: { v: number; at: string; json: string }) {
  return env.DB.prepare(
    `INSERT INTO settings (uid, v, at, json) VALUES (?, ?, ?, ?)
     ON CONFLICT(uid) DO UPDATE SET v = excluded.v, at = excluded.at, json = excluded.json`,
  ).bind(uid, s.v, s.at, s.json);
}

export async function getSettings(s: Session, env: Env): Promise<Response> {
  const row = await env.DB.prepare("SELECT v, at, json FROM settings WHERE uid = ?").bind(s.uid)
    .first<{ v: number; at: string; json: string }>();
  if (!row) throw new HttpError(404, "no_settings");
  return json({ v: row.v, at: row.at, settings: JSON.parse(row.json) });
}

export async function putSettings(req: Request, s: Session, env: Env): Promise<Response> {
  await putSettingsStmt(env, s.uid, V.settingsDoc(await readJson(req))).run();
  return json({ ok: true });
}
