import { describe, expect, it } from "vitest";
import { api, befriend, db, person } from "./helpers";

// 3.8.1, the outside audit of 3.8.0: mute is a block on the server too (cheers and
// knocks never land, on any screen), knocks have ceilings, and a report is kept for
// the admin instead of going nowhere without REPORT_TO.

const mute = (p: { call: Function }, ...uids: string[]) =>
  (p.call as any)("PUT", "/settings", { v: 1, at: new Date().toISOString(), settings: { muted: uids } });

async function crew() {
  const sam = await person("sam");
  const dre = await person("dre");
  await befriend(sam, dre);
  await befriend(dre, sam);
  return { sam, dre };
}

async function squad(founder: { call: Function }, ...members: { call: Function }[]) {
  const r = await (founder.call as any)("POST", "/squads", { name: "busm" });
  for (const m of members) await (m.call as any)("POST", `/squads/${r.body.id}/join`, { code: r.body.code });
  return r.body.id as string;
}

describe("muted cheers (audit #3)", () => {
  it("a muted person's cheer reads as sent and goes nowhere: not stored, not counted, not on any screen", async () => {
    const { sam, dre } = await crew();
    await mute(sam, "dre");
    expect((await dre.call("POST", "/cheers/sam", { emoji: "🔥", note: "hey" })).body).toEqual({ ok: true });
    expect(await db().prepare("SELECT COUNT(*) AS n FROM cheers").first("n")).toBe(0);
    expect(await db().prepare("SELECT COUNT(*) AS n FROM cheer_counts").first("n")).toBe(0);
    expect((await sam.call("GET", "/board?keep=1")).body.cheers).toEqual([]);
    // unmuted: the next one lands as ever
    await mute(sam);
    await dre.call("POST", "/cheers/sam", { emoji: "🎉" });
    expect((await sam.call("GET", "/board?keep=1")).body.cheers.map((c: any) => c.emoji)).toEqual(["🎉"]);
  });

  it("one waiting from before the mute isn't shown on the site's home, and the add-on's read lets it go", async () => {
    const { sam, dre } = await crew();
    await dre.call("POST", "/cheers/sam", { emoji: "🔥", note: "before" });
    await mute(sam, "dre");
    const home = (await sam.call("GET", "/board?keep=1")).body;
    expect(home.cheers).toEqual([]);
    const first = (await sam.call("GET", "/board?got=0")).body;
    expect(first.cheers).toEqual([]);
    expect(first.cheersAt).toBeGreaterThan(0);  // acknowledged like any read cheer
    await sam.call("GET", `/board?got=${first.cheersAt}`);
    expect(await db().prepare("SELECT COUNT(*) AS n FROM cheers").first("n")).toBe(0);
  });
});

describe("knocks (audit #10)", () => {
  it("never from someone the recipient muted; one they had waits until they unmute", async () => {
    const alice = await person("alice");
    const bob = await person("bob");
    const id = await squad(alice, bob);
    await bob.call("POST", "/knocks/alice", { squad: id });
    await mute(alice, "bob");
    expect((await alice.call("GET", "/knocks")).body.knocks).toEqual([]);
    expect((await alice.call("GET", "/board")).body.knocks).toEqual([]);
    await mute(alice);
    expect((await alice.call("GET", "/knocks")).body.knocks.map((k: any) => k.from)).toEqual(["bob"]);
    // a fresh knock while muted isn't kept (and reads as sent)
    await alice.call("DELETE", "/knocks/bob");
    await db().prepare("DELETE FROM limits").run();  // a new day for the pair
    await mute(alice, "bob");
    expect((await bob.call("POST", "/knocks/alice", { squad: id })).body).toEqual({ ok: true });
    expect(await db().prepare("SELECT COUNT(*) AS n FROM knocks").first("n")).toBe(0);
  });

  it("one a day a pair: a knock dismissed isn't back within the day", async () => {
    const alice = await person("alice");
    const bob = await person("bob");
    const id = await squad(alice, bob);
    expect(await bob.status("POST", "/knocks/alice", { squad: id })).toBe(200);
    await alice.call("DELETE", "/knocks/bob");
    expect(await bob.status("POST", "/knocks/alice", { squad: id })).toBe(200);
    expect((await alice.call("GET", "/knocks")).body.knocks).toEqual([]);
    // the other way round is its own pair
    expect(await alice.status("POST", "/knocks/bob", { squad: id })).toBe(200);
    expect((await bob.call("GET", "/knocks")).body.knocks.map((k: any) => k.from)).toEqual(["alice"]);
  });

  it("a sender's ceiling: 60 an hour", async () => {
    const alice = await person("alice");
    const bob = await person("bob");
    const id = await squad(alice, bob);
    for (let i = 0; i < 60; i++) expect(await bob.status("POST", "/knocks/alice", { squad: id })).toBe(200);
    expect(await bob.status("POST", "/knocks/alice", { squad: id })).toBe(429);
  });

  it("adding by code or by a used invite knocks nobody who muted me; the answer reads the same", async () => {
    const alice = await person("alice");
    const bob = await person("bob");
    await db().prepare("INSERT INTO codes (code, uid) VALUES ('ALICE1', 'alice')").run();
    await mute(alice, "bob");
    const r = await bob.call("POST", "/codes/ALICE1/add");
    expect(r.body).toMatchObject({ uid: "alice", mutual: false, knocked: true });
    expect(await db().prepare("SELECT COUNT(*) AS n FROM knocks").first("n")).toBe(0);
  });
});

describe("reports, kept for the admin (audit #4)", () => {
  const env = { ADMIN_UIDS: "sam" } as any;

  it("the Inbox: newest first, both names as they are now (never an email), done and back, delete; nobody else", async () => {
    const sam = await person("sam");
    const maya = await person("maya");
    const dre = await person("dre");
    await dre.call("POST", "/sync", { profile: { emoji: "🐢" } });
    await maya.call("POST", "/reports", { uid: "dre", reason: "name", note: "rude name" });
    await maya.call("POST", "/reports", { uid: "dre", reason: "cheers" });
    const admin = (method: string, path: string, body?: unknown) => api(method, path, { token: sam.token, env, body });
    expect((await api("GET", "/admin/reports", { token: maya.token, env })).status).toBe(404);
    const got = (await admin("GET", "/admin/reports")).body;
    expect(got.open).toBe(2);
    expect(got.reports.map((r: any) => r.reason)).toEqual(["cheers", "name"]);
    expect(got.reports[1]).toMatchObject({ kind: "person", note: "rude name", done: false,
      by: { uid: "maya", name: "Maya" }, target: { uid: "dre", name: "Dre", emoji: "🐢" } });
    expect(JSON.stringify(got)).not.toContain("@example.com");
    const id = got.reports[0].id;
    expect((await api("PATCH", `/admin/reports/${id}`, { token: maya.token, env, body: { done: true } })).status).toBe(404);
    expect((await admin("PATCH", `/admin/reports/${id}`, { done: true })).status).toBe(200);
    expect((await admin("GET", "/admin/reports")).body.reports).toHaveLength(1);
    expect((await admin("GET", "/admin/reports?state=done")).body.reports.map((r: any) => r.id)).toEqual([id]);
    expect((await admin("GET", "/admin/stats")).body.reportsOpen).toBe(1);
    expect((await admin("DELETE", `/admin/reports/${id}`)).status).toBe(200);
    expect((await admin("GET", "/admin/reports?state=all")).body.reports).toHaveLength(1);
  });

  it("in the reporter's Your data; gone with either account; gone after 180 days", async () => {
    const maya = await person("maya");
    const dre = await person("dre");
    const nia = await person("nia");
    await maya.call("POST", "/reports", { uid: "dre", reason: "other", note: "x" });
    await nia.call("POST", "/reports", { uid: "maya", reason: "other" });
    const mine = (await maya.call("GET", "/account/data")).body;
    expect(mine.reportsYouMade).toEqual([expect.objectContaining({ kind: "person", reason: "other", note: "x" })]);
    expect(JSON.stringify(mine.reportsYouMade)).not.toContain("dre");
    expect(await dre.status("DELETE", "/account")).toBe(200);
    expect(await db().prepare("SELECT by_uid, target FROM reports").all().then((r) => r.results))
      .toEqual([{ by_uid: "nia", target: "maya" }]);
    await db().prepare("UPDATE reports SET at = at - 181 * 86400").run();
    const { housekeeping } = await import("../src/index");
    await housekeeping((await import("cloudflare:workers")).env as any);
    expect(await db().prepare("SELECT COUNT(*) AS n FROM reports").first("n")).toBe(0);
  });
});
