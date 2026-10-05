// The 2.x bridge, for the weeks while the crew updates: every 15 minutes,
// what people still on 2.x wrote to Firestore comes into D1, and what
// people on 3.x wrote to D1 goes out to Firestore, so both versions see
// each other as they did before the move. Off unless FIREBASE_SA (a service
// account key with Firestore access) is set. Delete this file, its cron and
// the secret when Firestore goes.
//
// What crosses, per person: the week, name and emoji, shared decks, the
// heatmap, and their row in each squad they're in on both sides. Squad rows
// are updates only, in both directions: the bridge never makes anyone a
// member anywhere, so a removal on either side stays a removal. Cheers,
// knocks and memberships themselves don't cross.
//
// Nothing is logged but counts. Card text never crosses: a 2.x flag's text
// is dropped by the week validator on the way in, and flags don't go out.

import { Env } from "./util";
import * as V from "./validate";

export const PROJECT = "anki-leaderboard-f6691";
/** Every 15 minutes while 2.x clients remain (wrangler.toml). Not exported from
 *  index.ts: a Worker's main module may export only handlers. */
export const BRIDGE_CRON = "*/15 * * * *";
const DOCS = `projects/${PROJECT}/databases/(default)/documents`;
const API = `https://firestore.googleapis.com/v1/${DOCS}`;
const WEEK_FIELDS = ["v", "days", "updatedAt", "paused", "examDate", "awayFrom", "awayTo", "liveUntil", "tricky", "room"];
const DAY_KEYS = new Set(["studied", "reviews", "studyTimeMs", "accuracy", "streak", "newCards", "status"]);
const ROW_FIELDS = ["name", "day", "reviews", "studyTimeMs", "accuracy", "streak", "week", "emoji", "newCards"];
const ROW_COLS = ["day", "reviews", "study_time_ms", "accuracy", "streak", "week", "emoji", "new_cards"] as const;

type Fetch = (url: string, init?: RequestInit) => Promise<Response>;
type Row = { uid: string; name: string | null; emoji: string | null; client_version: string | null;
  doc: string | null; updated_at: number | null; decks: string | null; heat: string | null };
type Member = { squad: string; uid: string; name: string; day: string | null; reviews: number | null;
  study_time_ms: number | null; accuracy: number | null; streak: number | null; week: number | null;
  emoji: string | null; new_cards: number | null; client_version: string | null };
export type BridgeCounts = { pulled: number; pushed: number };

// ---- Firestore values ----

export function fv(v: unknown): unknown {
  if (v === null || v === undefined) return { nullValue: null };
  if (typeof v === "boolean") return { booleanValue: v };
  if (typeof v === "number") return Number.isInteger(v) ? { integerValue: String(v) } : { doubleValue: v };
  if (typeof v === "string") return { stringValue: v };
  if (Array.isArray(v)) return { arrayValue: { values: v.map(fv) } };
  if (typeof v === "object") {
    const o = v as Record<string, unknown>;
    if ("timestampValue" in o && Object.keys(o).length === 1) return o;
    return { mapValue: { fields: Object.fromEntries(Object.entries(o).map(([k, x]) => [k, fv(x)])) } };
  }
  return { nullValue: null };
}

export function pv(f: any): unknown {
  if (!f || typeof f !== "object") return null;
  if ("integerValue" in f) return Number(f.integerValue);
  if ("doubleValue" in f) return Number(f.doubleValue);
  if ("booleanValue" in f) return f.booleanValue;
  if ("stringValue" in f) return f.stringValue;
  if ("timestampValue" in f) return f.timestampValue;
  if ("arrayValue" in f) return (f.arrayValue.values || []).map(pv);
  if ("mapValue" in f) return fields(f.mapValue.fields);
  return null;
}

function fields(fs: Record<string, unknown> | undefined): Record<string, unknown> {
  return Object.fromEntries(Object.entries(fs || {}).map(([k, x]) => [k, pv(x)]));
}

const mapFields = (v: Record<string, unknown>) => (fv(v) as any).mapValue.fields;

/** JSON with sorted keys, so two docs compare by content, not key order. */
export function stable(v: unknown): string {
  if (Array.isArray(v)) return `[${v.map(stable).join(",")}]`;
  if (v && typeof v === "object") {
    const o = v as Record<string, unknown>;
    return `{${Object.keys(o).filter((k) => o[k] !== undefined).sort().map((k) => `${JSON.stringify(k)}:${stable(o[k])}`).join(",")}}`;
  }
  return JSON.stringify(v);
}

// ---- Google auth: a service account's JWT, traded for an access token ----

let cached: { token: string; exp: number; key: string } | null = null;

function b64url(bytes: ArrayBuffer | Uint8Array | string): string {
  const b = typeof bytes === "string" ? new TextEncoder().encode(bytes) : new Uint8Array(bytes);
  let s = "";
  for (const x of b) s += String.fromCharCode(x);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function accessToken(saJson: string, fetcher: Fetch): Promise<string> {
  const now = Math.floor(Date.now() / 1000);
  if (cached && cached.key === saJson && cached.exp > now + 60) return cached.token;
  const sa = JSON.parse(saJson) as { client_email: string; private_key: string; token_uri?: string };
  const aud = sa.token_uri || "https://oauth2.googleapis.com/token";
  const head = b64url(JSON.stringify({ alg: "RS256", typ: "JWT" }));
  const claims = b64url(JSON.stringify({ iss: sa.client_email, scope: "https://www.googleapis.com/auth/datastore",
    aud, iat: now, exp: now + 3600 }));
  const der = Uint8Array.from(atob(sa.private_key.replace(/-----[^-]+-----/g, "").replace(/\s+/g, "")), (c) => c.charCodeAt(0));
  const key = await crypto.subtle.importKey("pkcs8", der, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("RSASSA-PKCS1-v1_5", key, new TextEncoder().encode(`${head}.${claims}`));
  const res = await fetcher(aud, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: `grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Ajwt-bearer&assertion=${head}.${claims}.${b64url(sig)}`,
  });
  if (!res.ok) throw new Error(`google token: ${res.status}`);
  const data = (await res.json()) as { access_token: string; expires_in?: number };
  cached = { token: data.access_token, exp: now + (data.expires_in || 3600), key: saJson };
  return data.access_token;
}

// ---- shapes, each way ----

const on3 = (v: string | null) => /^3\./.test(v || "");
const isoZ = (sec: number) => new Date(sec * 1000).toISOString().replace(/\.\d{3}Z$/, "Z");
const sameTime = (a: unknown, b: unknown) => Date.parse(String(a || "")) === Date.parse(String(b || ""));

function attempt<T>(f: () => T): T | null {
  try {
    return f();
  } catch {
    return null;
  }
}

/** A Firestore week (2.x) as the week D1 keeps, or null if it won't pass. */
export function inbound(doc: Record<string, unknown>): string | null {
  const w: Record<string, unknown> = {};
  for (const [k, x] of Object.entries(doc)) {
    if (k === "updatedAt") continue;
    if (k === "days" && x && typeof x === "object") {
      w.days = Object.fromEntries(Object.entries(x as Record<string, unknown>).map(([lb, d]) =>
        [lb, Object.fromEntries(Object.entries((d || {}) as Record<string, unknown>).filter(([dk]) => DAY_KEYS.has(dk)))]));
    } else if (WEEK_FIELDS.includes(k)) {
      w[k] = x;
    }
  }
  return attempt(() => JSON.stringify(V.week(w)));
}

/** A D1 week as the Firestore doc 2.x reads (no flags: 2.x shows their text, which we never hold). */
export function outbound(doc: string, updatedAt: number): Record<string, unknown> {
  const w = JSON.parse(doc) as Record<string, unknown>;
  delete w.tricky;
  delete w.recap;  // 3.2, which 2.x doesn't show
  w.updatedAt = isoZ(updatedAt);
  return w;
}

/** A 2.x squad row (Firestore) as D1's columns, or null if it won't pass. */
function rowIn(doc: Record<string, unknown>) {
  const v = Object.fromEntries(ROW_FIELDS.filter((k) => k in doc && doc[k] !== undefined).map((k) => [k, doc[k]]));
  return attempt(() => V.memberRow(v));
}

/** A D1 squad row as the fields 2.x writes. */
function rowOut(m: Member): Record<string, unknown> {
  return { name: m.name, day: m.day, reviews: m.reviews, studyTimeMs: m.study_time_ms, accuracy: m.accuracy,
    streak: m.streak, week: m.week, emoji: m.emoji, newCards: m.new_cards };
}

// ---- one run ----

export async function bridge(env: Env, fetcher: Fetch = fetch): Promise<BridgeCounts | null> {
  if (!env.FIREBASE_SA) return null;
  const token = await accessToken(env.FIREBASE_SA, fetcher);
  const auth = { authorization: `Bearer ${token}`, "content-type": "application/json" };
  const db = env.DB;
  // Only people it matters for: everyone on 3.x (2.x friends read their
  // copies), and people on 2.x whom someone on 3.x has added or shares a
  // squad with (the only ones whose Firestore data a 3.x screen shows).
  // Firestore's free tier is 50k reads a day; reading everyone every 15
  // minutes came close to it.
  const V3 = "SELECT uid FROM users WHERE client_version LIKE '3.%'";
  const SQUADS3 = `SELECT squad FROM members WHERE uid IN (${V3})`;
  const [peopleRes, membersRes] = await db.batch([
    db.prepare(`SELECT u.uid, u.name, u.emoji, u.client_version, w.doc, w.updated_at, d.json AS decks, h.json AS heat
                  FROM users u LEFT JOIN weeks w ON w.uid = u.uid LEFT JOIN decks d ON d.uid = u.uid
                  LEFT JOIN heatmaps h ON h.uid = u.uid
                 WHERE u.client_version LIKE '3.%'
                    OR u.uid IN (SELECT friend FROM friends WHERE owner IN (${V3}))
                    OR u.uid IN (SELECT uid FROM members WHERE squad IN (${SQUADS3}))`),
    db.prepare(`SELECT m.squad, m.uid, m.name, m.day, m.reviews, m.study_time_ms, m.accuracy, m.streak, m.week,
                       m.emoji, m.new_cards, u.client_version
                  FROM members m JOIN users u ON u.uid = m.uid WHERE m.squad IN (${SQUADS3})`),
  ]);
  const people = peopleRes.results as Row[];
  const members = membersRes.results as Member[];
  // who may read a 3.x person's copies on 2.x: their mutual friends, and nobody else
  const mutualRows = await db.prepare(
    `SELECT a.owner, a.friend FROM friends a JOIN friends b ON b.owner = a.friend AND b.friend = a.owner
      WHERE a.owner IN (${V3})`).all<{ owner: string; friend: string }>();
  const mutual = new Map<string, string[]>();
  for (const r of mutualRows.results) mutual.set(r.owner, [...(mutual.get(r.owner) ?? []), r.friend]);

  // everything this run compares, in batchGets of 100 documents
  const paths = [
    ...people.flatMap((r) => [`users/${r.uid}`, `users/${r.uid}/shared/week`, `users/${r.uid}/shared/decks`,
      `users/${r.uid}/shared/heatmap`]),
    ...members.map((m) => `squads/${m.squad}/members/${m.uid}`),
  ];
  const got = new Map<string, Record<string, unknown>>();
  for (let i = 0; i < paths.length; i += 100) {
    const res = await fetcher(`${API}:batchGet`, { method: "POST", headers: auth,
      body: JSON.stringify({ documents: paths.slice(i, i + 100).map((p) => `${DOCS}/${p}`) }) });
    if (!res.ok) throw new Error(`firestore batchGet: ${res.status}`);
    for (const item of (await res.json()) as { found?: { name: string; fields?: Record<string, unknown> } }[]) {
      if (item.found) got.set(item.found.name.slice(DOCS.length + 1), fields(item.found.fields));
    }
  }

  let pulled = 0;
  const d1: D1PreparedStatement[] = [];
  const writes: unknown[] = [];
  const put = (path: string, doc: Record<string, unknown>, mask: string[], mustExist = false) => writes.push({
    update: { name: `${DOCS}/${path}`, fields: mapFields(doc) }, updateMask: { fieldPaths: mask },
    ...(mustExist ? { currentDocument: { exists: true } } : {}),
  });

  for (const r of people) {
    const prof = got.get(`users/${r.uid}`);
    const fsWeek = got.get(`users/${r.uid}/shared/week`);
    const fsDecks = got.get(`users/${r.uid}/shared/decks`);
    const fsHeat = got.get(`users/${r.uid}/shared/heatmap`);
    if (!on3(r.client_version)) {
      // still on 2.x: Firestore is the truth
      if (fsWeek) {
        const doc = inbound(fsWeek);
        if (doc !== null && doc !== r.doc) {
          const at = Math.floor((Date.parse(String(fsWeek.updatedAt || "")) || Date.now()) / 1000);
          d1.push(db.prepare(`INSERT INTO weeks (uid, doc, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(uid) DO UPDATE SET doc = excluded.doc, updated_at = excluded.updated_at`).bind(r.uid, doc, at));
          pulled++;
        }
      }
      if (prof) {
        const name = typeof prof.displayName === "string" ? V.oneLine(prof.displayName, V.NAME_MAX) : "";
        const emoji = V.isEmoji(prof.emoji) ? prof.emoji : null;
        if ((name && name !== r.name) || emoji !== r.emoji) {
          d1.push(db.prepare("UPDATE users SET name = ?, emoji = ? WHERE uid = ?").bind(name || r.name, emoji, r.uid));
          pulled++;
        }
      }
      if (fsDecks) {
        const decks = attempt(() => JSON.stringify(V.decks(fsDecks.decks)));
        if (decks !== null && decks !== r.decks) {
          d1.push(db.prepare("INSERT INTO decks (uid, json) VALUES (?, ?) ON CONFLICT(uid) DO UPDATE SET json = excluded.json")
            .bind(r.uid, decks));
          pulled++;
        }
      }
      const heat = fsHeat ? attempt(() => JSON.stringify(V.heatmap({ counts: fsHeat.counts }))) : null;
      if (heat !== r.heat && !(fsHeat && heat === null)) {  // an unreadable heatmap leaves ours alone
        d1.push(heat === null
          ? db.prepare("DELETE FROM heatmaps WHERE uid = ?").bind(r.uid)
          : db.prepare("INSERT INTO heatmaps (uid, json) VALUES (?, ?) ON CONFLICT(uid) DO UPDATE SET json = excluded.json")
            .bind(r.uid, heat));
        pulled++;
      }
      continue;
    }
    // on 3.x: D1 is the truth; 2.x friends read the copies
    if (r.doc && r.updated_at) {
      const want = outbound(r.doc, r.updated_at);
      const same = fsWeek && sameTime(fsWeek.updatedAt, want.updatedAt)
        && stable({ ...fsWeek, updatedAt: 0 }) === stable({ ...want, updatedAt: 0 });
      if (!same) {
        const { updatedAt, ...rest } = want;
        put(`users/${r.uid}/shared/week`, { ...rest, updatedAt: { timestampValue: updatedAt } }, WEEK_FIELDS);
      }
    }
    if (r.decks !== null) {
      const decks = JSON.parse(r.decks);
      if (!fsDecks || stable(fsDecks.decks ?? null) !== stable(decks)) put(`users/${r.uid}/shared/decks`, { decks }, ["decks"]);
    }
    if (r.heat !== null) {
      const counts = JSON.parse(r.heat).counts;
      if (!fsHeat || stable(fsHeat.counts ?? null) !== stable(counts)) put(`users/${r.uid}/shared/heatmap`, { counts }, ["counts"]);
    } else if (fsHeat) {
      writes.push({ delete: `${DOCS}/users/${r.uid}/shared/heatmap` });  // turned off in 3.x
    }
    // 2.x's rules let whoever this person's Firestore edges name read those
    // copies; the edges must say what D1 says (removals, no one-sided adds)
    if (prof) {
      const want = [...(mutual.get(r.uid) ?? [])].sort();
      const have = Array.isArray(prof.friends) ? (prof.friends as unknown[]).map(String).sort() : [];
      const differs = stable(have) !== stable(want);
      if (differs) put(`users/${r.uid}`, { friends: want }, ["friends"], true);
      // listing the edges is a Firestore request a person: only when the
      // array was off, and otherwise once a day each (a run every 15 min is
      // 96 slots), so a run stays well inside the subrequest limit
      if (differs || dailySlot(r.uid)) {
        for (const edge of await listIds(fetcher, auth, `users/${r.uid}/friends`)) {
          if (!want.includes(edge)) writes.push({ delete: `${DOCS}/users/${r.uid}/friends/${edge}` });
        }
      }
    }
    // the profile says 2.9+ (so 2.x reads the week doc), with the current name and emoji
    const p = { displayName: r.name || "", emoji: r.emoji || "", clientVersion: r.client_version || "3.0.0" };
    if (prof && (prof.displayName !== p.displayName || (prof.emoji || "") !== p.emoji || prof.clientVersion !== p.clientVersion)) {
      put(`users/${r.uid}`, p, ["displayName", "emoji", "clientVersion"], true);  // never create a profile 2.x never had
    }
  }

  // squad rows: only where the person is a member on both sides
  for (const m of members) {
    const fsRow = got.get(`squads/${m.squad}/members/${m.uid}`);
    if (!fsRow) continue;
    if (!on3(m.client_version)) {
      const r = rowIn(fsRow);
      if (r && ROW_COLS.some((k) => (r as Record<string, unknown>)[k] !== (m as Record<string, unknown>)[k])) {
        d1.push(db.prepare(
          `UPDATE members SET day = ?, reviews = ?, study_time_ms = ?, accuracy = ?, streak = ?, week = ?, emoji = ?,
             new_cards = ?, updated_at = ? WHERE squad = ? AND uid = ?`,  // an update: never a join
        ).bind(r.day, r.reviews, r.study_time_ms, r.accuracy, r.streak, r.week, r.emoji, r.new_cards,
               Math.floor(Date.now() / 1000), m.squad, m.uid));
        pulled++;
      }
    } else {
      const want = rowOut(m);
      const have = Object.fromEntries(ROW_FIELDS.map((k) => [k, fsRow[k] ?? null]));
      if (stable(have) !== stable(want)) put(`squads/${m.squad}/members/${m.uid}`, want, ROW_FIELDS, true);
    }
  }

  if (d1.length) await db.batch(d1);
  for (let i = 0; i < writes.length; i += 400) {
    const res = await fetcher(`${API}:commit`, { method: "POST", headers: auth, body: JSON.stringify({ writes: writes.slice(i, i + 400) }) });
    if (!res.ok) throw new Error(`firestore commit: ${res.status}`);
  }
  return { pulled, pushed: writes.length };
}

/** The ids in a Firestore collection (names only, no fields read: the mask
 *  is `__name__`, the one reserved name a mask takes; `__none__` was a 400). */
async function listIds(fetcher: Fetch, auth: Record<string, string>, path: string): Promise<string[]> {
  const out: string[] = [];
  let page = "";
  do {
    const res = await fetcher(`${API}/${path}?pageSize=300&mask.fieldPaths=__name__${page ? `&pageToken=${encodeURIComponent(page)}` : ""}`,
      { headers: auth });
    if (!res.ok) throw new Error(`firestore list: ${res.status}`);
    const data = (await res.json()) as { documents?: { name: string }[]; nextPageToken?: string };
    for (const d of data.documents ?? []) out.push(d.name.slice(d.name.lastIndexOf("/") + 1));
    page = data.nextPageToken ?? "";
  } while (page);
  return out;
}

/** An account deleted in 3.x: its copies on 2.x go too, and nobody can
 *  read what's left. Best effort: the bridge's next run can't bring any of
 *  it back (the account is gone from D1). */
export async function forget(env: Env, uid: string, fetcher: Fetch = fetch): Promise<void> {
  if (!env.FIREBASE_SA || !/^[A-Za-z0-9_-]{1,128}$/.test(uid)) return;
  const token = await accessToken(env.FIREBASE_SA, fetcher);
  const auth = { authorization: `Bearer ${token}`, "content-type": "application/json" };
  const writes: unknown[] = ["week", "decks", "heatmap"].map((d) => ({ delete: `${DOCS}/users/${uid}/shared/${d}` }));
  for (const edge of await listIds(fetcher, auth, `users/${uid}/friends`)) writes.push({ delete: `${DOCS}/users/${uid}/friends/${edge}` });
  await fetcher(`${API}:commit`, { method: "POST", headers: auth, body: JSON.stringify({ writes }) });
  await fetcher(`${API}:commit`, { method: "POST", headers: auth, body: JSON.stringify({ writes: [{
    update: { name: `${DOCS}/users/${uid}`, fields: mapFields({ friends: [] }) }, updateMask: { fieldPaths: ["friends"] },
    currentDocument: { exists: true } }] }) });  // a profile 2.x never had stays absent
}

/** For tests: forget the cached Google token. */
export function _resetToken(): void {
  cached = null;
}

/** Whether this 15-minute run is this person's turn of the day (96 a day). */
function dailySlot(uid: string): boolean {
  let h = 0;
  for (let i = 0; i < uid.length; i++) h = (h * 31 + uid.charCodeAt(i)) >>> 0;
  return h % 96 === Math.floor(Date.now() / 900_000) % 96;
}
