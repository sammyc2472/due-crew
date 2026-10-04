// 3.7.1, D2: Account › Your data. Everything the server keeps about me, as
// one file, and two things deleted on their own: my log (cards.ts
// deleteLog) and my to-dos. Mine only; nothing here reads anyone else's
// rows beyond the names on my own lists.

import type { Session } from "./auth";
import { limitOrThrow } from "./limits";
import { Env, HttpError, json } from "./util";

const parse = (t: unknown) => {
  if (typeof t !== "string") return t ?? null;
  try { return JSON.parse(t); } catch { return t; }
};
const when = (sec: unknown) => typeof sec === "number" ? new Date(sec * 1000).toISOString() : null;

/** GET /account/data: one JSON file. Ten a day. */
export async function getData(s: Session, env: Env): Promise<Response> {
  await limitOrThrow(env, `mydata:${s.uid}`, 10, 86400);
  const db = env.DB;
  const q = (sql: string) => db.prepare(sql).bind(s.uid);
  const r = await db.batch([
    q("SELECT name, emoji, email, code, client_version, created_at, last_seen FROM users WHERE uid = ?1"),
    q("SELECT at, json FROM settings WHERE uid = ?1"),
    q("SELECT doc FROM weeks WHERE uid = ?1"),
    q("SELECT json FROM decks WHERE uid = ?1"),
    q("SELECT json FROM heatmaps WHERE uid = ?1"),
    q("SELECT json FROM logs WHERE uid = ?1"),
    q("SELECT year, n FROM cheer_counts WHERE uid = ?1 ORDER BY year"),
    q(`SELECT f.friend AS uid, u.name, EXISTS (SELECT 1 FROM friends b WHERE b.owner = f.friend AND b.friend = ?1) AS mutual, f.at
       FROM friends f LEFT JOIN users u ON u.uid = f.friend WHERE f.owner = ?1 ORDER BY f.at`),
    q(`SELECT q.name, m.joined_at, m.day, m.reviews, m.study_time_ms, m.accuracy, m.streak, m.week, m.new_cards, m.play
       FROM members m JOIN squads q ON q.id = m.squad WHERE m.uid = ?1 ORDER BY m.joined_at`),
    q("SELECT id, code, name, line, audience, doc, version, created_at, updated_at, listed FROM plans WHERE owner = ?1"),
    q(`SELECT p.name, f.share, f.paused, f.progress, f.at, f.sched, f.shift, f.pause_until, f.pause_since, f.skipped, f.hist
       FROM plan_follows f JOIN plans p ON p.id = f.plan WHERE f.uid = ?1`),
    q("SELECT p.name AS plan, n.day, n.text, n.at FROM plan_notes n JOIN plans p ON p.id = n.plan WHERE n.uid = ?1"),
    q("SELECT guid, text, at FROM tips WHERE uid = ?1"),
    q("SELECT guid FROM knows WHERE uid = ?1"),
    q("SELECT at, text FROM feedback WHERE uid = ?1 ORDER BY at"),
    q("SELECT device, created_at, last_used FROM sessions WHERE uid = ?1 ORDER BY last_used DESC"),
  ]);
  const rows = (i: number) => r[i].results as Record<string, unknown>[];
  const one = (i: number) => rows(i)[0];
  const me = one(0);
  if (!me) throw new HttpError(401, "auth");
  const out = {
    about: "Everything Due Crew keeps about you, as of this file. duecrew.com/privacy says who sees each part.",
    made: new Date().toISOString(),
    you: { ...me, created_at: when(me.created_at), last_seen: when(me.last_seen) },
    settings: one(1) ? { at: one(1).at, ...parse(one(1).json) } : null,
    week: parse(one(2)?.doc),
    sharedDecks: parse(one(3)?.json),
    heatmap: parse(one(4)?.json),
    log: parse(one(5)?.json),
    cheersReceived: rows(6),
    crew: rows(7).map((f) => ({ name: f.name ?? "(deleted)", mutual: f.mutual === 1, since: when(f.at) })),
    squads: rows(8).map((m) => ({ ...m, joined_at: when(m.joined_at), week: parse(m.week), play: parse(m.play) })),
    plansMade: rows(9).map((p) => ({ ...p, doc: parse(p.doc), created_at: when(p.created_at), updated_at: when(p.updated_at) })),
    plansFollowed: rows(10).map((f) => ({ ...f, progress: parse(f.progress), sched: parse(f.sched), skipped: parse(f.skipped), hist: parse(f.hist), at: when(f.at) })),
    planNotes: rows(11).map((n) => ({ ...n, at: when(n.at) })),
    tips: rows(12).map((t) => ({ ...t, at: when(t.at) })),
    cardsYouHaveDown: rows(13).map((k) => k.guid),
    feedback: rows(14).map((f) => ({ ...f, at: when(f.at) })),
    signedIn: rows(15).map((x) => ({ device: x.device, since: when(x.created_at), lastUsed: when(x.last_used) })),
  };
  return new Response(JSON.stringify(out, null, 1), {
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store",
               "content-disposition": 'attachment; filename="due-crew-data.json"' },
  });
}

/** DELETE /account/todos: my Due to-dos and ticks. A fresh save time, so
 *  each add-on takes it at its next refresh (board's settingsAt). */
export async function deleteTodos(s: Session, env: Env): Promise<Response> {
  const row = await env.DB.prepare("SELECT v, json FROM settings WHERE uid = ?").bind(s.uid)
    .first<{ v: number; json: string }>();
  if (!row) return json({ ok: true });
  const doc = JSON.parse(row.json) as Record<string, unknown>;
  doc.due_items = [];
  doc.due_ticks = {};
  // the add-on's own timestamp shape (microseconds), so newest-wins compares
  const at = new Date().toISOString().replace("Z", "000Z");
  await env.DB.prepare("UPDATE settings SET at = ?, json = ? WHERE uid = ?").bind(at, JSON.stringify(doc), s.uid).run();
  return json({ ok: true, at });
}
