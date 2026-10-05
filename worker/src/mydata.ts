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
    // the rest of what's kept about me (bug run, Oct): deck trees, invites,
    // waiting cheers and knocks either way, co-authoring, plan saves,
    // "this helped", squads I'm blocked from, an email change, the admin's note
    q("SELECT deck, doc, at FROM plan_trees WHERE uid = ?1"),
    q("SELECT expires_at, used_at FROM invites WHERE uid = ?1 ORDER BY expires_at"),
    q(`SELECT u.name AS from_name, c.emoji, c.note, c.at FROM cheers c LEFT JOIN users u ON u.uid = c.from_uid WHERE c.to_uid = ?1`),
    q(`SELECT u.name AS to_name, c.emoji, c.note, c.at FROM cheers c LEFT JOIN users u ON u.uid = c.to_uid WHERE c.from_uid = ?1`),
    q(`SELECT u.name AS from_name, k.at FROM knocks k LEFT JOIN users u ON u.uid = k.from_uid WHERE k.to_uid = ?1`),
    q(`SELECT u.name AS to_name, k.at FROM knocks k LEFT JOIN users u ON u.uid = k.to_uid WHERE k.from_uid = ?1`),
    q("SELECT p.name AS plan, e.at FROM plan_editors e JOIN plans p ON p.id = e.plan WHERE e.uid = ?1"),
    q("SELECT p.name AS plan, l.version, l.summary, l.at FROM plan_log l JOIN plans p ON p.id = l.plan WHERE l.uid = ?1 ORDER BY l.at"),
    q("SELECT guid FROM tip_helped WHERE by_uid = ?1"),
    q("SELECT q.name FROM bans b JOIN squads q ON q.id = b.squad WHERE b.uid = ?1"),
    q("SELECT email, at FROM email_changes WHERE uid = ?1"),
    q("SELECT text, at FROM admin_notes WHERE uid = ?1"),
    q("SELECT p.name AS plan, t.text, t.at FROM plan_posts t JOIN plans p ON p.id = t.plan WHERE t.uid = ?1 ORDER BY t.at"),  // 3.7.3
    // 3.7.3: the teams I'm on (the days I showed up, my squares), what I asked and answered
    q("SELECT p.name AS plan, t.joined_at, t.days, t.play FROM plan_team t JOIN plans p ON p.id = t.plan WHERE t.uid = ?1"),
    q(`SELECT p.name AS plan, a.parent IS NOT NULL AS answer, a.text, a.guid, a.ord, a.topic, a.helped, a.at
         FROM plan_asks a JOIN plans p ON p.id = a.plan WHERE a.uid = ?1 ORDER BY a.at`),
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
    deckTrees: rows(16).map((t) => ({ deck: t.deck, tree: parse(t.doc), at: when(t.at) })),
    invites: rows(17).map((i) => ({ expires: when(i.expires_at), used: when(i.used_at) })),
    cheersWaiting: rows(18).map((c) => ({ ...c, at: when(c.at) })),
    cheersSentNotYetRead: rows(19).map((c) => ({ ...c, at: when(c.at) })),
    knocksToYou: rows(20).map((k) => ({ ...k, at: when(k.at) })),
    knocksYouSent: rows(21).map((k) => ({ ...k, at: when(k.at) })),
    plansCoAuthored: rows(22).map((e) => ({ ...e, at: when(e.at) })),
    planSaves: rows(23).map((l) => ({ ...l, at: when(l.at) })),
    tipsYouSaidHelped: rows(24).map((t) => t.guid),
    squadsBlockedFrom: rows(25).map((b) => b.name),
    emailChange: one(26) ? { ...one(26), at: when(one(26).at) } : null,
    adminNote: one(27) ? { ...one(27), at: when(one(27).at) } : null,
    planPosts: rows(28).map((t) => ({ ...t, at: when(t.at) })),
    teams: rows(29).map((t) => ({ plan: t.plan, joined: when(t.joined_at), daysShowedUp: parse(t.days), bingo: parse(t.play) })),
    teamQuestionsAndAnswers: rows(30).map((a) => ({ ...a, answer: a.answer === 1, helped: a.helped === 1, at: when(a.at) })),
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
