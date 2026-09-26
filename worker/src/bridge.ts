// The 2.x bridge, for the weeks while the crew updates: every 15 minutes,
// the week of everyone still on 2.x comes from Firestore into D1, and the
// week of everyone on 3.x goes from D1 to Firestore, so both versions see
// each other's squares. Weeks only (and names, emoji): cheers, knocks and
// squads stay on their own side. Off unless FIREBASE_SA (a service account
// key with Firestore access) is set. Delete this file, its cron and the
// secret when Firestore goes.
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

type Fetch = (url: string, init?: RequestInit) => Promise<Response>;
type Row = { uid: string; name: string | null; emoji: string | null; client_version: string | null;
  doc: string | null; updated_at: number | null };

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

// ---- the two directions ----

const on3 = (r: Row) => /^3\./.test(r.client_version || "");

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
  try {
    return JSON.stringify(V.week(w));
  } catch {
    return null;
  }
}

/** A D1 week as the Firestore doc 2.x reads (no flags: 2.x shows their text, which we never hold). */
export function outbound(doc: string, updatedAt: number): Record<string, unknown> {
  const w = JSON.parse(doc) as Record<string, unknown>;
  delete w.tricky;
  w.updatedAt = new Date(updatedAt * 1000).toISOString().replace(/\.\d{3}Z$/, "Z");
  return w;
}

const sameTime = (a: unknown, b: unknown) => Date.parse(String(a || "")) === Date.parse(String(b || ""));

export async function bridge(env: Env, fetcher: Fetch = fetch): Promise<{ pulled: number; pushed: number } | null> {
  if (!env.FIREBASE_SA) return null;
  const token = await accessToken(env.FIREBASE_SA, fetcher);
  const auth = { authorization: `Bearer ${token}`, "content-type": "application/json" };
  const rows = (await env.DB.prepare(
    `SELECT u.uid, u.name, u.emoji, u.client_version, w.doc, w.updated_at
       FROM users u LEFT JOIN weeks w ON w.uid = u.uid`).all<Row>()).results;

  // one batchGet per 100 people: their week and their profile
  const got = new Map<string, Record<string, unknown>>();
  for (let i = 0; i < rows.length; i += 100) {
    const names = rows.slice(i, i + 100).flatMap((r) => [`${DOCS}/users/${r.uid}/shared/week`, `${DOCS}/users/${r.uid}`]);
    const res = await fetcher(`${API}:batchGet`, { method: "POST", headers: auth, body: JSON.stringify({ documents: names }) });
    if (!res.ok) throw new Error(`firestore batchGet: ${res.status}`);
    for (const item of (await res.json()) as { found?: { name: string; fields?: Record<string, unknown> } }[]) {
      if (item.found) got.set(item.found.name.slice(DOCS.length + 1), fields(item.found.fields));
    }
  }

  let pulled = 0;
  const d1 = [];
  const writes: unknown[] = [];
  for (const r of rows) {
    const fsWeek = got.get(`users/${r.uid}/shared/week`);
    const prof = got.get(`users/${r.uid}`);
    if (!on3(r)) {
      // still on 2.x: Firestore is the truth for their week and name
      if (fsWeek) {
        const doc = inbound(fsWeek);
        if (doc !== null && doc !== r.doc) {
          const at = Math.floor((Date.parse(String(fsWeek.updatedAt || "")) || Date.now()) / 1000);
          d1.push(env.DB.prepare(
            `INSERT INTO weeks (uid, doc, updated_at) VALUES (?, ?, ?)
             ON CONFLICT(uid) DO UPDATE SET doc = excluded.doc, updated_at = excluded.updated_at`).bind(r.uid, doc, at));
          pulled++;
        }
      }
      const name = typeof prof?.displayName === "string" ? prof.displayName.trim().slice(0, 60) : "";
      if (name && name !== r.name) d1.push(env.DB.prepare("UPDATE users SET name = ? WHERE uid = ?").bind(name, r.uid));
      continue;
    }
    // on 3.x: D1 is the truth; 2.x friends read the copy
    if (r.doc && r.updated_at) {
      const want = outbound(r.doc, r.updated_at);
      const have = fsWeek ? { ...fsWeek } : null;
      const same = have && sameTime(have.updatedAt, want.updatedAt)
        && stable({ ...have, updatedAt: 0 }) === stable({ ...want, updatedAt: 0 });
      if (!same) {
        const { updatedAt, ...rest } = want;
        writes.push({
          update: { name: `${DOCS}/users/${r.uid}/shared/week`,
            fields: (fv({ ...rest, updatedAt: { timestampValue: updatedAt } }) as any).mapValue.fields },
          updateMask: { fieldPaths: WEEK_FIELDS },
        });
      }
    }
    // the profile says 2.9+ (so 2.x reads the week doc), with the current name and emoji
    const p = { displayName: r.name || "", emoji: r.emoji || "", clientVersion: r.client_version || "3.0.0" };
    if (prof && (prof.displayName !== p.displayName || (prof.emoji || "") !== p.emoji || prof.clientVersion !== p.clientVersion)) {
      writes.push({
        update: { name: `${DOCS}/users/${r.uid}`, fields: (fv(p) as any).mapValue.fields },
        updateMask: { fieldPaths: ["displayName", "emoji", "clientVersion"] },
        currentDocument: { exists: true },  // never create a profile 2.x never had
      });
    }
  }
  if (d1.length) await env.DB.batch(d1);
  for (let i = 0; i < writes.length; i += 400) {
    const res = await fetcher(`${API}:commit`, { method: "POST", headers: auth, body: JSON.stringify({ writes: writes.slice(i, i + 400) }) });
    if (!res.ok) throw new Error(`firestore commit: ${res.status}`);
  }
  return { pulled, pushed: writes.length };
}

/** For tests: forget the cached Google token. */
export function _resetToken(): void {
  cached = null;
}
