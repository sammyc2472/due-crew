import { env } from "cloudflare:workers";
import { beforeEach, describe, expect, it } from "vitest";
import { bridge, fv, pv, _resetToken } from "../src/bridge";

const DOCS = "projects/anki-leaderboard-f6691/databases/(default)/documents";

/** A service account key made fresh for the test. */
async function serviceAccount(): Promise<string> {
  const kp = (await crypto.subtle.generateKey(
    { name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" },
    true, ["sign", "verify"])) as CryptoKeyPair;
  const der = new Uint8Array((await crypto.subtle.exportKey("pkcs8", kp.privateKey)) as ArrayBuffer);
  let s = "";
  for (const b of der) s += String.fromCharCode(b);
  const pem = `-----BEGIN PRIVATE KEY-----\n${btoa(s)}\n-----END PRIVATE KEY-----\n`;
  return JSON.stringify({ client_email: "bridge@example.iam.gserviceaccount.com", private_key: pem });
}

/** Firestore, as far as the bridge uses it: plain docs by path. */
function fakeFirestore(docs: Record<string, Record<string, unknown>>) {
  const log = { tokens: 0, gets: 0, commits: [] as any[] };
  const fetcher = async (url: string, init?: RequestInit): Promise<Response> => {
    if (url.startsWith("https://oauth2.googleapis.com/token")) {
      log.tokens++;
      expect(String(init?.body)).toContain("assertion=");
      return Response.json({ access_token: "tok", expires_in: 3600 });
    }
    expect((init?.headers as any).authorization).toBe("Bearer tok");
    const body = JSON.parse(String(init?.body));
    if (url.endsWith(":batchGet")) {
      log.gets++;
      return Response.json(body.documents.map((name: string) => {
        const path = name.slice(DOCS.length + 1);
        return docs[path] ? { found: { name, fields: (fv(docs[path]) as any).mapValue.fields } } : { missing: name };
      }));
    }
    if (url.endsWith(":commit")) {
      log.commits.push(body.writes);
      for (const w of body.writes) {
        const path = w.update.name.slice(DOCS.length + 1);
        const next = { ...(docs[path] || {}) };
        for (const f of w.updateMask.fieldPaths) delete next[f];
        Object.assign(next, pv({ mapValue: { fields: w.update.fields } }));
        docs[path] = next;
      }
      return Response.json({});
    }
    return new Response("?", { status: 404 });
  };
  return { fetcher, log, docs };
}

async function user(uid: string, name: string, version: string | null, week?: object, at = 1_790_000_000) {
  await env.DB.prepare("INSERT INTO users (uid, email, name, client_version, created_at) VALUES (?, ?, ?, ?, 0)")
    .bind(uid, `${uid}@example.com`, name, version).run();
  if (week) await env.DB.prepare("INSERT INTO weeks (uid, doc, updated_at) VALUES (?, ?, ?)").bind(uid, JSON.stringify(week), at).run();
}

const week = (reviews: number, extra: object = {}) =>
  ({ v: 1, days: { "2026-09-26": { studied: true, reviews } }, paused: false, ...extra });

describe("the 2.x bridge", () => {
  beforeEach(() => _resetToken());

  it("does nothing without a service account", async () => {
    expect(await bridge({ ...env, FIREBASE_SA: undefined } as any)).toBeNull();
  });

  it("brings a 2.x week in and sends a 3.x week out, then has nothing to do", async () => {
    await user("old", "Dre", "2.13.0");
    await user("new", "Sam", "3.0.1", week(120));
    const fs = fakeFirestore({
      "users/old": { displayName: "Dre", clientVersion: "2.13.0" },
      "users/old/shared/week": { ...week(88), updatedAt: { timestampValue: "2026-09-26T10:00:00Z" },
        tricky: [{ guid: "g1", text: "card text", deck: "Pharm", at: "2026-09-26" }] },
      "users/new": { displayName: "Sam", clientVersion: "2.13.0", friends: ["old"] },
    });
    const sa = await serviceAccount();
    const r = await bridge({ ...env, FIREBASE_SA: sa } as any, fs.fetcher);
    expect(r).toEqual({ pulled: 1, pushed: 2 });

    // in: Dre's 2.x week, minus the flag's card text
    const inRow = await env.DB.prepare("SELECT doc, updated_at FROM weeks WHERE uid = 'old'").first<any>();
    expect(JSON.parse(inRow.doc).days["2026-09-26"].reviews).toBe(88);
    expect(inRow.doc).not.toContain("card text");
    expect(inRow.updated_at).toBe(Date.parse("2026-09-26T10:00:00Z") / 1000);

    // out: Sam's 3.x week where 2.x reads it, and a profile that says to read it
    expect((fs.docs["users/new/shared/week"].days as any)["2026-09-26"].reviews).toBe(120);
    expect(fs.docs["users/new"].clientVersion).toBe("3.0.1");
    expect(fs.docs["users/new"].friends).toEqual(["old"]);  // only the masked fields change

    // a second run with nothing new writes nothing, on either side
    const again = await bridge({ ...env, FIREBASE_SA: sa } as any, fs.fetcher);
    expect(again).toEqual({ pulled: 0, pushed: 0 });
    expect(fs.log.tokens).toBe(1);  // the token is reused
  });

  it("follows each side's changes", async () => {
    await user("old", "Dre", null);
    await user("new", "Sam", "3.0.1", week(10), 1_790_000_000);
    const fs = fakeFirestore({
      "users/old": { displayName: "Dre" },
      "users/old/shared/week": { ...week(1), updatedAt: { timestampValue: "2026-09-26T08:00:00Z" } },
      "users/new": { displayName: "Sam" },
    });
    const sa = await serviceAccount();
    await bridge({ ...env, FIREBASE_SA: sa } as any, fs.fetcher);

    fs.docs["users/old/shared/week"] = { ...week(5), updatedAt: "2026-09-26T09:00:00Z" };
    fs.docs["users/old"].displayName = "Dre C";
    await env.DB.prepare("UPDATE weeks SET doc = ?, updated_at = ? WHERE uid = 'new'").bind(JSON.stringify(week(40)), 1_790_000_900).run();
    const r = await bridge({ ...env, FIREBASE_SA: sa } as any, fs.fetcher);
    expect(r?.pulled).toBe(1);
    const dre = await env.DB.prepare("SELECT u.name, w.doc FROM users u JOIN weeks w ON w.uid = u.uid WHERE u.uid = 'old'").first<any>();
    expect(dre.name).toBe("Dre C");
    expect(JSON.parse(dre.doc).days["2026-09-26"].reviews).toBe(5);
    expect((fs.docs["users/new/shared/week"].days as any)["2026-09-26"].reviews).toBe(40);
  });

  it("never sends flags out, and never creates a profile 2.x never had", async () => {
    await user("new", "Sam", "3.0.1", week(3, { tricky: [{ guid: "g", deck: "Pharm", at: "2026-09-26" }] }));
    const fs = fakeFirestore({});
    await bridge({ ...env, FIREBASE_SA: await serviceAccount() } as any, fs.fetcher);
    expect(fs.docs["users/new/shared/week"].tricky).toBeUndefined();
    expect(fs.docs["users/new"]).toBeUndefined();
  });

  it("skips a 2.x week that won't pass the validator, and keeps going", async () => {
    await user("bad", "X", "2.13.0");
    await user("ok", "Y", "2.13.0");
    const fs = fakeFirestore({
      "users/bad/shared/week": { v: 1, days: { "not-a-date": { studied: true } } },
      "users/ok/shared/week": { ...week(7), updatedAt: "2026-09-26T08:00:00Z" },
    });
    const r = await bridge({ ...env, FIREBASE_SA: await serviceAccount() } as any, fs.fetcher);
    expect(r?.pulled).toBe(1);
    expect(await env.DB.prepare("SELECT 1 FROM weeks WHERE uid = 'bad'").first()).toBeNull();
  });
});
