// Friends, codes, cheers, knocks, and what anyone may see of anyone.
//
// Consent, as firestore.rules had it: a friendship is two edges, one per
// person (friends(owner, friend)). My numbers go only to people I added
// who added me back. A cheer lands only if its recipient added the sender.
// A knock needs a squad in common or the recipient's own code.

import type { Session } from "./auth";
import { tipWrite } from "./cards";
import { hit, limitOrThrow } from "./limits";
import { sendMail } from "./mail";
import * as V from "./validate";
import { ankiDay, Env, HttpError, json, nowSec, readJson, readText } from "./util";

export const CODE_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
export const CODE_LEN = 6;
const CODE_RE = /^[A-Z0-9]{6}$/;
const UID_RE = /^[A-Za-z0-9_-]{1,128}$/;

export function checkUid(uid: string): string {
  if (!UID_RE.test(uid)) throw new HttpError(404, "no_user");
  return uid;
}

/** Did `owner` add `other`? */
export async function added(env: Env, owner: string, other: string): Promise<boolean> {
  return !!(await env.DB.prepare("SELECT 1 FROM friends WHERE owner = ? AND friend = ?")
    .bind(owner, other).first());
}

export async function mutual(env: Env, a: string, b: string): Promise<boolean> {
  const row = await env.DB.prepare(
    `SELECT COUNT(*) AS n FROM friends WHERE (owner = ?1 AND friend = ?2) OR (owner = ?2 AND friend = ?1)`,
  ).bind(a, b).first<number>("n");
  return row === 2;
}

export async function nameOf(env: Env, uid: string): Promise<{ name: string; emoji: string } | null> {
  const u = await env.DB.prepare("SELECT name, emoji FROM users WHERE uid = ?").bind(uid)
    .first<{ name: string | null; emoji: string | null }>();
  return u ? { name: u.name || "?", emoji: u.emoji || "" } : null;
}

/** 3.7.1, D5: a crew edge either way, a knock either way, a squad or a
 *  plan in common (its owner, a co-author or a follower). One query. */
export async function connected(env: Env, a: string, b: string): Promise<boolean> {
  if (a === b) return true;
  const row = await env.DB.prepare(
    `SELECT EXISTS (SELECT 1 FROM friends WHERE (owner = ?1 AND friend = ?2) OR (owner = ?2 AND friend = ?1))
         OR EXISTS (SELECT 1 FROM knocks WHERE (to_uid = ?1 AND from_uid = ?2) OR (to_uid = ?2 AND from_uid = ?1))
         OR EXISTS (SELECT 1 FROM members x JOIN members y ON y.squad = x.squad WHERE x.uid = ?1 AND y.uid = ?2)
         OR EXISTS (SELECT 1 FROM (SELECT id AS plan FROM plans WHERE owner = ?1
                                   UNION SELECT plan FROM plan_editors WHERE uid = ?1
                                   UNION SELECT plan FROM plan_follows WHERE uid = ?1) m
                    WHERE m.plan IN (SELECT id FROM plans WHERE owner = ?2
                                     UNION SELECT plan FROM plan_editors WHERE uid = ?2
                                     UNION SELECT plan FROM plan_follows WHERE uid = ?2)) AS ok`,
  ).bind(a, b).first<number>("ok");
  return row === 1;
}

/** GET /users/{uid}: a name and an emoji, nothing more, and since 3.7.1
 *  (D5) only to someone connected to them; anyone else gets the same 404
 *  as no such account. Codes and invites carry their own names. */
export async function getUser(s: Session, env: Env, [uid]: string[]): Promise<Response> {
  const u = await nameOf(env, checkUid(uid));
  if (!u || !await connected(env, s.uid, uid)) throw new HttpError(404, "no_user");
  return json({ uid, ...u });
}

// ---- friends ----

/** 3.7.1 review: an account that came from 2.x and hasn't synced from 3.x
 *  yet (users.from2x: the import sets it, a 3.x sync clears it). The
 *  client version alone was anyone's to set. */
export async function from2x(env: Env, uid: string): Promise<boolean> {
  const u = await env.DB.prepare("SELECT from2x FROM users WHERE uid = ?").bind(uid).first<{ from2x: number }>();
  if (!u || !u.from2x) return false;
  // 1: imported, not synced from 3.x yet. Since the first 3.x sync, the time
  // of it: the restore stays open a week, so one that failed (a 5xx, a
  // timeout) tries again at the next sync instead of being lost for good
  if (u.from2x === 1) return true;
  return nowSec() - u.from2x < FROM2X_GRACE;
}

const FROM2X_GRACE = 7 * 86400;

async function addEdge(env: Env, me: string, fid: string) {
  await env.DB.prepare("INSERT INTO friends (owner, friend, at) VALUES (?, ?, ?) ON CONFLICT DO NOTHING")
    .bind(me, fid, nowSec()).run();
}

/** PUT /friends/{uid}: add someone by uid (add back, a knock's Add). */
export async function putFriend(req: Request, s: Session, env: Env, [fid]: string[]): Promise<Response> {
  checkUid(fid);
  const text = await readText(req);
  if (text.trim() && text.trim() !== "{}") throw V.bad("friend");  // an edge carries nothing I set
  if (fid === s.uid) throw new HttpError(400, "self");
  const u = await nameOf(env, fid);
  if (!u) throw new HttpError(404, "no_user");
  // every way to this call (add back, a knock's Add, someone from a squad or
  // a plan) is a connection already; a uid alone, with none, is a stranger:
  // the same 404 as no such account, and no edge (it would hand over the
  // name: D5). Codes and invites are their own calls.
  if (!(await connected(env, s.uid, fid))) throw new HttpError(404, "no_user");
  await addEdge(env, s.uid, fid);
  await env.DB.prepare("DELETE FROM knocks WHERE to_uid = ? AND from_uid = ?").bind(s.uid, fid).run();
  return json({ uid: fid, ...u, mutual: await mutual(env, s.uid, fid) });
}

/** PUT /friends {ids}: 3.0's first sync re-adds the crew by uid, once.
 *  Add-only; unknown uids are skipped. */
export async function restoreFriends(req: Request, s: Session, env: Env): Promise<Response> {
  const body = await readJson(req);
  const ids = body.ids;
  if (!Array.isArray(ids) || ids.length > 500) throw V.bad("ids");
  const want = [...new Set(ids.filter((x): x is string => typeof x === "string" && UID_RE.test(x) && x !== s.uid))];
  if (!want.length) return json({ added: [] });
  // 3.0's first sync brings back a 2.x crew, once: only before this account
  // has synced from 3.x, and rarely. Otherwise it would let anyone knock
  // anyone, again and again, with no code and no squad in common.
  if (!(await from2x(env, s.uid))) return json({ added: [] });
  await limitOrThrow(env, `restore:${s.uid}`, 3, 86400);
  // D1 binds at most 100 parameters a query and runs at most 1,000 queries
  // a request: 90 at a time keeps a 500-friend restore well inside both
  const ok: string[] = [];
  for (let i = 0; i < want.length; i += 90) {
    const part = want.slice(i, i + 90);
    const found = await env.DB.prepare(`SELECT uid FROM users WHERE uid IN (${part.map(() => "?").join(",")})`)
      .bind(...part).all<{ uid: string }>();
    ok.push(...found.results.map((r) => r.uid));
  }
  const now = nowSec();
  for (let i = 0; i < ok.length; i += 90) {
    const part = ok.slice(i, i + 90);
    // each one I add back who hasn't added me gets a knock, so a computer
    // that forgot its list sees "added you" and adds back in one click; one
    // who already added me is crew now, and their knock to me is done
    await env.DB.batch(part.flatMap((fid) => [
      env.DB.prepare("INSERT INTO friends (owner, friend, at) VALUES (?, ?, ?) ON CONFLICT DO NOTHING").bind(s.uid, fid, now),
      env.DB.prepare(
        `INSERT INTO knocks (to_uid, from_uid, squad, at) SELECT ?1, ?2, NULL, ?3
         WHERE NOT EXISTS (SELECT 1 FROM friends WHERE owner = ?1 AND friend = ?2)
         ON CONFLICT(to_uid, from_uid) DO NOTHING`).bind(fid, s.uid, now),
      env.DB.prepare(
        `DELETE FROM knocks WHERE to_uid = ?2 AND from_uid = ?1
         AND EXISTS (SELECT 1 FROM friends WHERE owner = ?1 AND friend = ?2)`).bind(fid, s.uid),
    ]));
  }
  return json({ added: ok.sort() });
}

/** DELETE /friends/{uid}: my edge goes; so do their reads, at once. */
export async function deleteFriend(s: Session, env: Env, [fid]: string[]): Promise<Response> {
  await env.DB.prepare("DELETE FROM friends WHERE owner = ? AND friend = ?").bind(s.uid, checkUid(fid)).run();
  return json({ ok: true });
}

/** GET /friends: the Friends dialog. My code, the people I added (with
 *  whether they added me back), and my knocks. Reads only: nothing is
 *  consumed, unlike /board's cheers. */
export async function getFriends(s: Session, env: Env): Promise<Response> {
  const [me, friends] = await env.DB.batch([
    env.DB.prepare("SELECT code FROM users WHERE uid = ?").bind(s.uid),
    env.DB.prepare(
      `SELECT f.friend AS uid, u.name, u.emoji,
              EXISTS (SELECT 1 FROM friends b WHERE b.owner = f.friend AND b.friend = ?1) AS mutual
       FROM friends f JOIN users u ON u.uid = f.friend WHERE f.owner = ?1 ORDER BY f.at, f.friend`).bind(s.uid),
  ]);
  return json({
    code: (me.results[0] as any)?.code || "",
    friends: (friends.results as any[]).map((f) => ({ uid: f.uid, name: f.name || "?", emoji: f.emoji || "", mutual: !!f.mutual })),
    knocks: await listKnocks(env, s.uid),
  });
}

// ---- codes ----

function drawCode(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(CODE_LEN));
  // 36 symbols: reject bytes past the last whole multiple so every one is even
  let out = "";
  for (let i = 0; out.length < CODE_LEN; i++) {
    const b = i < bytes.length ? bytes[i] : crypto.getRandomValues(new Uint8Array(1))[0];
    if (b < 252) out += CODE_ALPHABET[b % 36];
  }
  return out;
}

/** POST /codes [{code}]: a new friend code for me, and the old one stops
 *  working. `code` asks for a particular one: 3.0's first sync keeps the
 *  code a person already handed out, when it's free. */
export async function newCode(req: Request, s: Session, env: Env): Promise<Response> {
  const text = await readText(req);
  let want: string | null = null;
  if (text) {
    let body: unknown;
    try {
      body = JSON.parse(text);
    } catch {
      throw new HttpError(400, "bad_json");
    }
    if (V.isObj(body) && body.code !== undefined) {
      if (typeof body.code !== "string" || !CODE_RE.test(body.code)) throw V.bad("code");
      want = body.code;
    }
  }
  const old = await env.DB.prepare("SELECT code FROM users WHERE uid = ?").bind(s.uid).first<string>("code");
  // a wanted code is only for an account without one (the 2.x restore):
  // it must never undo a code someone chose to change
  if (want && old) return json({ code: old });
  // a code someone retired (a new code, a deleted account) is never
  // handed to a stranger who asks for it by name: only a 2.x account's own
  if (want && !(await from2x(env, s.uid))) want = null;
  for (let i = 0; i < 5; i++) {
    const code = want && i === 0 ? want : drawCode();
    const r = await env.DB.prepare("INSERT INTO codes (code, uid) VALUES (?, ?) ON CONFLICT DO NOTHING")
      .bind(code, s.uid).run();
    if (!r.meta.changes) continue;  // someone's: another draw
    await env.DB.batch([
      env.DB.prepare("UPDATE users SET code = ? WHERE uid = ?").bind(code, s.uid),
      env.DB.prepare("DELETE FROM codes WHERE uid = ? AND code != ?").bind(s.uid, code),
      // 3.5.0: a new code also ends every invite link I've sent
      env.DB.prepare("DELETE FROM invites WHERE uid = ?").bind(s.uid),
    ]);
    return json({ code });
  }
  throw new HttpError(503, "try_again");
}

/** GET /codes/{code}: whose code this is, before adding them (the site's
 *  "Got a code?", 3.4 review). A name and an emoji, as anyone signed in
 *  may see for a uid; the same limit as adding by code. */
export async function peekCode(s: Session, env: Env, [code]: string[]): Promise<Response> {
  await limitOrThrow(env, `addcode:${s.uid}`, 30, 3600);
  code = code.toUpperCase();
  const owner = CODE_RE.test(code)
    ? await env.DB.prepare("SELECT uid FROM codes WHERE code = ?").bind(code).first<string>("uid")
    : null;
  if (!owner) throw new HttpError(404, "no_match");
  const u = (await nameOf(env, owner))!;
  return json({ uid: owner, ...u, mine: owner === s.uid, added: owner !== s.uid && (await added(env, s.uid, owner)) });
}

/** POST /codes/{code}/add: add the code's owner, and knock them with it so
 *  their board offers Add back. */
export async function addByCode(s: Session, env: Env, [code]: string[]): Promise<Response> {
  await limitOrThrow(env, `addcode:${s.uid}`, 30, 3600);
  code = code.toUpperCase();
  const owner = CODE_RE.test(code)
    ? await env.DB.prepare("SELECT uid FROM codes WHERE code = ?").bind(code).first<string>("uid")
    : null;
  if (!owner) throw new HttpError(404, "no_match");
  if (owner === s.uid) throw new HttpError(400, "own_code");
  if (await added(env, s.uid, owner)) throw new HttpError(409, "already");
  await addEdge(env, s.uid, owner);
  const isMutual = await mutual(env, s.uid, owner);
  if (!isMutual) {
    await env.DB.prepare(
      `INSERT INTO knocks (to_uid, from_uid, squad, at) VALUES (?, ?, NULL, ?)
       ON CONFLICT(to_uid, from_uid) DO UPDATE SET squad = NULL, at = excluded.at`,
    ).bind(owner, s.uid, nowSec()).run();
  }
  const u = (await nameOf(env, owner))!;
  return json({ uid: owner, ...u, mutual: isMutual, knocked: !isMutual });
}

// ---- cheers ----

/** POST /cheers/{to}: one cheer per sender, overwriting the last one, and
 *  only to someone who added me. */
export async function sendCheer(req: Request, s: Session, env: Env, [to]: string[]): Promise<Response> {
  checkUid(to);
  const c = V.cheer(await readJson(req));
  if (!(await added(env, to, s.uid))) throw new HttpError(403, "not_friends");
  // a cheer overwrites the last, but each is a write: a ceiling (a room's
  // cheer goes to every member, a card script could loop it)
  await limitOrThrow(env, `cheer:${s.uid}`, 200, 3600);
  const now = nowSec();
  if (!c.guid) {
    // 3.7.1: a cheer received counts on my year card, a sender once a day,
    // read or not (a key of its own: the cheer row goes when it's read)
    // 3.7.2: by the recipient's own day and year, not UTC's
    const clock = await env.DB.prepare("SELECT tz, rollover FROM users WHERE uid = ?").bind(to)
      .first<{ tz: number | null; rollover: number | null }>();
    const day = ankiDay(now, clock?.tz, clock?.rollover);
    if (await hit(env, `cheerday:${s.uid}:${to}:${day}`, 1, 86400)) {
      await env.DB.prepare(
        `INSERT INTO cheer_counts (uid, year, n) VALUES (?, ?, 1) ON CONFLICT(uid, year) DO UPDATE SET n = n + 1`,
      ).bind(to, Number(day.slice(0, 4))).run();
    }
  }
  await env.DB.prepare(
    `INSERT INTO cheers (to_uid, from_uid, emoji, note, luck, guid, at) VALUES (?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT(to_uid, from_uid) DO UPDATE SET emoji = excluded.emoji, note = excluded.note,
       luck = excluded.luck, guid = excluded.guid, at = excluded.at`,
  ).bind(to, s.uid, c.emoji, c.note, c.luck, c.guid, now).run();
  // 3.2: a tip with words stays on its card, for the crew who has it
  if (c.guid && c.note) await tipWrite(env, s.uid, c.guid, c.note).run();
  // 3.0.1: the first tip on a flagged card takes the flag down for the whole
  // crew. Only a tip from someone the flag was shown to (mutual) counts.
  if (c.guid && (await added(env, s.uid, to))) await unflag(env, to, c.guid);
  return json({ ok: true });
}

/** Take `guid` off `uid`'s flagged cards. Written only when it was there,
 *  and only over the doc just read, so a sync landing in between wins.
 *  updated_at stays: a tip isn't the owner being active. */
export async function unflag(env: Env, uid: string, guid: string): Promise<void> {
  const doc = await env.DB.prepare("SELECT doc FROM weeks WHERE uid = ?").bind(uid).first<string>("doc");
  if (!doc) return;
  const week = JSON.parse(doc);
  const next = withoutFlags(week, new Set([guid]));
  if (next === week) return;
  await env.DB.prepare("UPDATE weeks SET doc = ? WHERE uid = ? AND doc = ?")
    .bind(JSON.stringify(next), uid, doc).run();
}

/** The week without the flags on these guids; the same object when none
 *  of them is flagged. An empty list goes, as the client leaves it out. */
export function withoutFlags<T extends Record<string, unknown>>(week: T, guids: Set<string>): T {
  const tricky = week.tricky;
  if (!Array.isArray(tricky) || !tricky.some((t) => guids.has(t?.guid))) return week;
  const out: Record<string, unknown> = { ...week };
  const left = tricky.filter((t) => !guids.has(t?.guid));
  if (left.length) out.tricky = left;
  else delete out.tricky;
  return out as T;
}

// ---- knocks ----

/** POST /knocks/{to} {squad}: "added you", between two members of a squad. */
export async function sendKnock(req: Request, s: Session, env: Env, [to]: string[]): Promise<Response> {
  checkUid(to);
  const body = await readJson(req);
  for (const k of Object.keys(body)) if (k !== "squad") throw V.bad("knock");  // sender and names are mine
  if (!V.isStr(body.squad, 40, 1)) throw V.bad("squad");
  const both = await env.DB.prepare("SELECT COUNT(*) AS n FROM members WHERE squad = ? AND uid IN (?, ?)")
    .bind(body.squad, s.uid, to).first<number>("n");
  if (to === s.uid || both !== 2) throw new HttpError(403, "no_squad_in_common");
  await env.DB.prepare(
    `INSERT INTO knocks (to_uid, from_uid, squad, at) VALUES (?, ?, ?, ?)
     ON CONFLICT(to_uid, from_uid) DO UPDATE SET squad = excluded.squad, at = excluded.at`,
  ).bind(to, s.uid, body.squad, nowSec()).run();
  return json({ ok: true });
}

export async function listKnocks(env: Env, uid: string) {
  const rows = await env.DB.prepare(
    `SELECT k.from_uid, k.squad, k.at, u.name, u.emoji FROM knocks k JOIN users u ON u.uid = k.from_uid
     WHERE k.to_uid = ? ORDER BY k.at DESC LIMIT 50`,
  ).bind(uid).all<{ from_uid: string; squad: string | null; at: number; name: string | null; emoji: string | null }>();
  // names from the profile, never from the knock: senders can't spoof
  return rows.results.map((r) => ({ from: r.from_uid, name: r.name || "?", emoji: r.emoji || "", squad: r.squad || "" }));
}

export async function getKnocks(s: Session, env: Env): Promise<Response> {
  return json({ knocks: await listKnocks(env, s.uid) });
}

export async function deleteKnock(s: Session, env: Env, [from]: string[]): Promise<Response> {
  await env.DB.prepare("DELETE FROM knocks WHERE to_uid = ? AND from_uid = ?").bind(s.uid, checkUid(from)).run();
  return json({ ok: true });
}

// ---- reports ----

export const REPORT_REASONS: Record<string, string> = {
  cheers: "Unwanted cheers or knocks",
  name: "A name or emoji that shouldn't be here",
  other: "Something else",
};
export const REPORT_NOTE_MAX = 500;

/** POST /reports {uid, reason, note?}: stores nothing. The report goes by
 *  mail to REPORT_TO: who reported whom, the reported name and emoji, the
 *  reason and note, and their last cheer to me if one is waiting. Never
 *  the reporter's email. Muting is the client's; nobody is told. */
export async function report(req: Request, s: Session, env: Env): Promise<Response> {
  const body = await readJson(req);
  for (const k of Object.keys(body)) if (!["uid", "reason", "note"].includes(k)) throw V.bad("report");
  if (typeof body.uid !== "string") throw new HttpError(404, "no_user");
  const uid = checkUid(body.uid);
  const reason = body.reason;
  if (typeof reason !== "string" || !Object.prototype.hasOwnProperty.call(REPORT_REASONS, reason)) throw V.bad("reason");
  if (body.note !== undefined && body.note !== null && !V.isStr(body.note, REPORT_NOTE_MAX)) throw V.bad("note");
  if (uid === s.uid) throw new HttpError(400, "self");
  const who = await nameOf(env, uid);
  if (!who) throw new HttpError(404, "no_user");
  await limitOrThrow(env, `report:${s.uid}`, 10, 3600);
  const note = typeof body.note === "string" ? V.oneLine(body.note, REPORT_NOTE_MAX) : "";
  if (!env.REPORT_TO) {
    console.log("due crew: report received");
    return json({ ok: true });
  }
  const c = await env.DB.prepare(
    "SELECT emoji, note, luck, guid, at FROM cheers WHERE to_uid = ? AND from_uid = ?",
  ).bind(s.uid, uid).first<{ emoji: string; note: string | null; luck: number | null; guid: string | null; at: number }>();
  const cheer = c
    ? `${c.emoji}${c.note ? ` "${c.note}"` : ""}${c.luck ? " (good-luck line)" : ""}${c.guid ? " (tip on a card)" : ""}`
      + `, ${new Date(c.at * 1000).toISOString()}`
    : "none waiting (cheers go once they're read)";
  const text = [
    `Reason: ${REPORT_REASONS[reason]}`,
    `Note: ${note || "(none)"}`,
    "",
    `Reported: ${uid}`,
    `Name: ${who.name}`,
    `Emoji: ${who.emoji || "(none)"}`,
    `Last cheer to the reporter: ${cheer}`,
    "",
    `Reporter: ${s.uid}`,
  ].join("\n");
  await sendMail(env, env.REPORT_TO, "Due Crew report", text);
  return json({ ok: true });
}
