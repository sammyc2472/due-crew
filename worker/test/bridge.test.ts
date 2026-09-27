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
    if (!init?.method || init.method === "GET") {
      // a collection listing: the docs directly under the path
      const path = decodeURIComponent(url.split("/documents/")[1].split("?")[0]);
      const names = Object.keys(docs).filter((d) => d.startsWith(path + "/") && !d.slice(path.length + 1).includes("/"));
      return Response.json({ documents: names.map((n) => ({ name: `${DOCS}/${n}` })) });
    }
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
      // like Firestore: a failed precondition fails the whole commit
      for (const w of body.writes) {
        if (w.currentDocument?.exists && !docs[w.update.name.slice(DOCS.length + 1)]) return new Response("precondition", { status: 400 });
      }
      for (const w of body.writes) {
        if (w.delete) {
          delete docs[w.delete.slice(DOCS.length + 1)];
          continue;
        }
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

/** `new` (on 3.x) has added `uid`, so the bridge brings their 2.x data in. */
async function seenBy3(...uids: string[]) {
  for (const u of uids) await env.DB.prepare("INSERT INTO friends (owner, friend, at) VALUES ('new', ?, 0)").bind(u).run();
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
    await seenBy3("old");
    await env.DB.prepare("INSERT INTO friends (owner, friend, at) VALUES ('old', 'new', 0)").run();  // mutual
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
    await seenBy3("old");
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
    expect(r?.pulled).toBe(2);  // the week and the name
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
    await user("new", "Sam", "3.0.1");
    await seenBy3("bad", "ok");
    const fs = fakeFirestore({
      "users/bad/shared/week": { v: 1, days: { "not-a-date": { studied: true } } },
      "users/ok/shared/week": { ...week(7), updatedAt: "2026-09-26T08:00:00Z" },
    });
    const r = await bridge({ ...env, FIREBASE_SA: await serviceAccount() } as any, fs.fetcher);
    expect(r?.pulled).toBe(1);
    expect(await env.DB.prepare("SELECT 1 FROM weeks WHERE uid = 'bad'").first()).toBeNull();
  });

  it("carries shared decks, heatmaps and emoji both ways; a heatmap turned off goes on the other side", async () => {
    const deck = { name: "Step 1", sig: ["g1", "g2"], total: 100, seen: 40, mature: 10 };
    await user("old", "Dre", "2.13.0");
    await user("new", "Sam", "3.0.1", week(1));
    await seenBy3("old");
    await env.DB.batch([
      env.DB.prepare("UPDATE users SET emoji = '🔥' WHERE uid = 'new'"),
      env.DB.prepare("INSERT INTO decks (uid, json) VALUES ('new', ?)").bind(JSON.stringify([{ ...deck, seen: 70 }])),
      env.DB.prepare("INSERT INTO heatmaps (uid, json) VALUES ('new', ?)").bind(JSON.stringify({ counts: { "2026-09-25": 30 } })),
    ]);
    const fs = fakeFirestore({
      "users/old": { displayName: "Dre", emoji: "🌿" },
      "users/old/shared/decks": { decks: [deck] },
      "users/old/shared/heatmap": { counts: { "2026-09-24": 12 } },
      "users/new": { displayName: "Sam", clientVersion: "2.13.0" },
      "users/new/shared/heatmap": { counts: { "2026-01-01": 1 } },
    });
    const sa = await serviceAccount();
    await bridge({ ...env, FIREBASE_SA: sa } as any, fs.fetcher);
    const old = await env.DB.prepare(
      "SELECT u.emoji, d.json AS decks, h.json AS heat FROM users u LEFT JOIN decks d ON d.uid = u.uid LEFT JOIN heatmaps h ON h.uid = u.uid WHERE u.uid = 'old'",
    ).first<any>();
    expect(old.emoji).toBe("🌿");
    expect(JSON.parse(old.decks)[0].seen).toBe(40);
    expect(JSON.parse(old.heat).counts["2026-09-24"]).toBe(12);
    expect((fs.docs["users/new/shared/decks"].decks as any)[0].seen).toBe(70);
    expect((fs.docs["users/new/shared/heatmap"].counts as any)["2026-09-25"]).toBe(30);
    expect(fs.docs["users/new"].emoji).toBe("🔥");
    // Sam turns the heatmap off in 3.x; Dre turns his off in 2.x
    await env.DB.prepare("DELETE FROM heatmaps WHERE uid = 'new'").run();
    delete fs.docs["users/old/shared/heatmap"];
    await bridge({ ...env, FIREBASE_SA: sa } as any, fs.fetcher);
    expect(fs.docs["users/new/shared/heatmap"]).toBeUndefined();
    expect(await env.DB.prepare("SELECT 1 FROM heatmaps WHERE uid = 'old'").first()).toBeNull();
    expect(await bridge({ ...env, FIREBASE_SA: sa } as any, fs.fetcher)).toEqual({ pulled: 0, pushed: 0 });
  });

  it("squad rows cross as updates only: nobody is made a member on either side", async () => {
    await user("old", "Dre", "2.13.0");
    await user("new", "Sam", "3.0.1", week(1));
    await user("gone", "Nia", "2.13.0");
    const now = 1_790_000_000;
    await env.DB.batch([
      env.DB.prepare("INSERT INTO squads (id, name, founder, open, created_at) VALUES ('sq', 'Busm', 'new', 1, 0)"),
      env.DB.prepare("INSERT INTO members (squad, uid, name, joined_at, reviews) VALUES ('sq', 'old', 'Dre', 0, 1)"),
      env.DB.prepare("INSERT INTO members (squad, uid, name, joined_at, reviews, day, updated_at) VALUES ('sq', 'new', 'Sam', 0, 88, '2026-09-26', ?)").bind(now),
    ]);
    const fs = fakeFirestore({
      "squads/sq/members/old": { name: "Dre", reviews: 150, day: "2026-09-26", streak: 9 },
      "squads/sq/members/gone": { name: "Nia", reviews: 5 },   // removed in 3.x: no D1 row
      "users/old": { displayName: "Dre" },
      "users/new": { displayName: "Sam" },
    });
    const sa = await serviceAccount();
    await bridge({ ...env, FIREBASE_SA: sa } as any, fs.fetcher);
    const dre = await env.DB.prepare("SELECT reviews, streak FROM members WHERE squad = 'sq' AND uid = 'old'").first<any>();
    expect(dre).toEqual({ reviews: 150, streak: 9 });
    expect(await env.DB.prepare("SELECT 1 FROM members WHERE uid = 'gone'").first()).toBeNull();  // never a join
    expect(fs.docs["squads/sq/members/new"]).toBeUndefined();  // Sam has no row in 2.x's squad: none made
    // once Sam's 2.x row exists, it follows D1
    fs.docs["squads/sq/members/new"] = { name: "Sam", reviews: 1 };
    await bridge({ ...env, FIREBASE_SA: sa } as any, fs.fetcher);
    expect(fs.docs["squads/sq/members/new"]).toMatchObject({ reviews: 88, day: "2026-09-26" });
    expect(await bridge({ ...env, FIREBASE_SA: sa } as any, fs.fetcher)).toEqual({ pulled: 0, pushed: 0 });
  });

  it("reads nobody a 3.x screen can't show", async () => {
    await user("new", "Sam", "3.0.1", week(1));
    await user("friend", "Dre", "2.13.0");
    await user("mate", "Nia", "2.13.0");
    await user("stranger", "Zed", "2.13.0");
    await seenBy3("friend");
    await env.DB.batch([
      env.DB.prepare("INSERT INTO squads (id, name, founder, open, created_at) VALUES ('sq', 'Busm', 'new', 1, 0)"),
      env.DB.prepare("INSERT INTO members (squad, uid, name, joined_at) VALUES ('sq', 'new', 'Sam', 0), ('sq', 'mate', 'Nia', 0)"),
    ]);
    const fs = fakeFirestore({});
    const asked: string[] = [];
    const spy = async (url: string, init?: RequestInit) => {
      if (url.endsWith(":batchGet")) asked.push(...JSON.parse(String(init?.body)).documents);
      return fs.fetcher(url, init);
    };
    await bridge({ ...env, FIREBASE_SA: await serviceAccount() } as any, spy);
    const who = new Set(asked.map((d) => d.split("/documents/")[1].split("/")[1]));
    expect([...who].sort()).toEqual(["friend", "mate", "new", "sq"]);  // "sq": the squad rows' documents
    expect(asked.some((d) => d.includes("stranger"))).toBe(false);
  });

  it("2.x reads a 3.x person's copies only while D1 says they're mutual friends", async () => {
    await user("new", "Sam", "3.0.1", week(1));
    await user("pal", "Dre", "2.13.0");
    await user("ex", "Zed", "2.13.0");
    await user("fan", "Nia", "2.13.0");
    await env.DB.batch([
      env.DB.prepare("INSERT INTO friends (owner, friend, at) VALUES ('new', 'pal', 0), ('pal', 'new', 0), ('new', 'fan', 0)"),
    ]);
    const fs = fakeFirestore({
      "users/new": { displayName: "Sam", friends: ["pal", "ex", "fan"] },
      "users/new/friends/pal": { at: "x" }, "users/new/friends/ex": { at: "x" }, "users/new/friends/fan": { at: "x" },
    });
    const sa = await serviceAccount();
    await bridge({ ...env, FIREBASE_SA: sa } as any, fs.fetcher);
    expect(fs.docs["users/new"].friends).toEqual(["pal"]);        // ex was removed; fan never added back
    expect(Object.keys(fs.docs).filter((d) => d.startsWith("users/new/friends/"))).toEqual(["users/new/friends/pal"]);
    expect(await bridge({ ...env, FIREBASE_SA: sa } as any, fs.fetcher)).toEqual({ pulled: 0, pushed: 0 });
  });

  it("a deleted account's 2.x copies go, and its edges with them", async () => {
    const { forget } = await import("../src/bridge");
    const fs = fakeFirestore({
      "users/gone": { displayName: "Sam", friends: ["pal"] }, "users/gone/friends/pal": { at: "x" },
      "users/gone/shared/week": week(3), "users/gone/shared/decks": { decks: [] }, "users/gone/shared/heatmap": { counts: {} },
    });
    await forget({ ...env, FIREBASE_SA: await serviceAccount() } as any, "gone", fs.fetcher);
    expect(Object.keys(fs.docs).sort()).toEqual(["users/gone"]);
    expect(fs.docs["users/gone"].friends).toEqual([]);
  });
});
