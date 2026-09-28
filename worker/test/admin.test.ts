import { describe, expect, it } from "vitest";
import { housekeeping } from "../src/index";
import { api, db, mailbox, person, signIn } from "./helpers";

// 3.5: the admin's history (X), the home's feed (H), a plan's history for my log (L)

const env = { ADMIN_UIDS: "sam" } as any;
const admin = (who: { token: string }, path: string, method = "GET", body?: unknown) => api(method, path, { token: who.token, env, body });
const today = () => new Date().toISOString().slice(0, 10);

describe("X: the admin's page keeps its history", () => {
  it("the daily cron keeps today's counts; trends read them, accounts from when each was made", async () => {
    const sam = await person("sam");
    await person("maya");
    const { snapshot } = await import("../src/admin");
    await snapshot({ DB: db() } as any);
    await snapshot({ DB: db() } as any);  // twice in a day: one row a count
    const rows = await db().prepare("SELECT COUNT(*) AS n FROM admin_days WHERE day = ? AND key = 'n.plans'").bind(today()).first<number>("n");
    expect(rows).toBe(1);
    expect((await api("GET", "/admin/trends", { token: (await person("x1")).token, env })).status).toBe(404);
    const t = await admin(sam, "/admin/trends?days=30");
    expect(t.status).toBe(200);
    expect(t.body.days).toHaveLength(30);
    expect(t.body.days.at(-1)).toBe(today());
    expect(t.body.series.accounts.at(-1)).toBe(3);
    expect(t.body.series.plans.at(-1)).toBe(0);
    expect(t.body.series.plans[0]).toBeNull();  // not kept yet then
    expect((await admin(sam, "/admin/trends?days=7")).body.days).toHaveLength(90);  // 30, 90 or 365
    expect(JSON.stringify(t.body)).not.toMatch(/sam|maya|@/);
  });

  it("counts sign-in steps, never who", async () => {
    const box = mailbox();
    await signIn("new@school.edu", box);
    await api("POST", "/auth/code", { body: { email: "new@school.edu" } });
    await api("POST", "/auth/verify", { body: { email: "new@school.edu", code: "000000", device: "x" } });
    const sam = await person("sam");
    const s = await admin(sam, "/admin/stats");
    expect(s.body.codes).toMatchObject({ sent: 2, ok: 1, wrong: 1 });
    const keys = await db().prepare("SELECT key FROM admin_days").all<{ key: string }>();
    expect(JSON.stringify(keys.results)).not.toContain("school");
  });

  it("the cutover and the bridge's last run", async () => {
    const sam = await person("sam");
    const old = await person("old");
    await db().prepare("UPDATE users SET client_version = '3.5.0' WHERE uid = 'sam'").run();
    await db().prepare("UPDATE users SET client_version = '2.13.0' WHERE uid = 'old'").run();
    await db().prepare("INSERT INTO weeks (uid, doc, updated_at) VALUES ('old', '{}', ?)").bind(Math.floor(Date.now() / 1000)).run();
    await person("gone");
    const { bridgeRan } = await import("../src/admin");
    await bridgeRan({ DB: db() } as any, 1800, { pulled: 23, pushed: 61 });
    await bridgeRan({ DB: db() } as any, 900, null, new Error("403 PERMISSION_DENIED\nmore detail"));
    const s = (await admin(sam, "/admin/stats")).body;
    expect(s.cutover).toEqual({ on3: 1, active2: 1, quiet: 1 });
    expect(s.bridge).toMatchObject({ ms: 900, pulled: 0, pushed: 0, error: "403 PERMISSION_DENIED", runsToday: 2, failedToday: 1 });
    expect(old.uid).toBe("old");
  });

  it("a notice taken down stays in the list of past notices", async () => {
    const sam = await person("sam");
    const a = await admin(sam, "/admin/notices", "POST", { text: "One" });
    await admin(sam, "/admin/notices", "POST", { text: "Two" });
    await admin(sam, `/admin/notices/${a.body.id}`, "DELETE");
    expect((await admin(sam, "/admin/notices")).body.notices.map((n: any) => n.text)).toEqual(["Two"]);
    const all = (await admin(sam, "/admin/notices?all=1")).body.notices;
    expect(all.map((n: any) => [n.text, n.state])).toEqual([["Two", "showing"], ["One", "taken down"]]);
  });

  it("housekeeping still runs alone", async () => {
    await housekeeping({ DB: db() } as any);
  });
});

describe("H: the home's feed", () => {
  it("who added me back, notes and saves by others on plans I'm in; none from someone I muted; only on request", async () => {
    const sam = await person("sam");
    const dre = await person("dre");
    const maya = await person("maya");
    await sam.call("PUT", "/friends/dre");
    await sam.call("PUT", "/friends/maya");
    await db().prepare("UPDATE friends SET at = at - 10 WHERE owner = 'sam'").run();
    await dre.call("PUT", "/friends/sam");
    await maya.call("PUT", "/friends/sam");
    const made = await dre.call("POST", "/plans", { name: "Cardio", deck: "D" });
    const p = (await dre.call("PUT", `/plans/${made.body.id}`, { version: 1, summary: "moved Renal pharm to Fri",
      doc: { deck: "D", units: [{ id: "a", name: "A", opens: "2026-10-05", tags: ["X"] }] } })).body;
    await sam.call("POST", "/plans/follow", { code: p.code });
    await dre.call("POST", `/plans/${p.id}/notes`, { day: "2026-10-05", text: "quiz is closed-book" });
    await sam.call("POST", `/plans/${p.id}/notes`, { day: "2026-10-05", text: "mine" });
    const feed = async () => (await sam.call("GET", "/board?keep=1&feed=1")).body.feed;
    const f = await feed();
    expect(f.map((x: any) => x.kind).sort()).toEqual(["back", "back", "change", "note"]);
    expect(f.find((x: any) => x.kind === "note")).toMatchObject({ name: "Dre", planName: "Cardio", day: "2026-10-05", text: "quiz is closed-book" });
    expect(f.find((x: any) => x.kind === "change")).toMatchObject({ name: "Dre", summary: "moved Renal pharm to Fri" });
    await sam.call("PUT", "/settings", { v: 1, at: new Date().toISOString(), settings: { muted: ["maya"] } });
    expect((await feed()).map((x: any) => x.uid)).not.toContain("maya");
    expect((await sam.call("GET", "/board?keep=1")).body.feed).toBeUndefined();
    expect((await sam.call("GET", "/board?feed=1")).body.feed).toBeUndefined();  // the add-on's board never carries it
  });
});

describe("L: my plan's history", () => {
  it("a point a day, kept with my progress, mine only", async () => {
    const dre = await person("dre");
    const sam = await person("sam");
    const made = await dre.call("POST", "/plans", { name: "Cardio", deck: "D" });
    const p = (await dre.call("PUT", `/plans/${made.body.id}`, { version: 1,
      doc: { deck: "D", units: [{ id: "a", name: "A", opens: "2026-10-05", tags: ["X"] }, { id: "b", name: "B", opens: "2026-10-06", tags: ["Y"] }] } })).body;
    await sam.call("POST", "/plans/follow", { code: p.code });
    expect(await sam.status("POST", "/sync", { plans: { [p.id]: { a: [10, 4, 10], b: [5, 1, 20] } } })).toBe(200);
    const mine = (await sam.call("GET", "/plans/mine")).body.plans.find((x: any) => x.id === p.id);
    expect(mine.following.hist).toEqual({ [today()]: [15, 5] });
    const { histNext } = await import("../src/plans");
    const long = Object.fromEntries(Array.from({ length: 130 }, (_, i) => [`2026-01-${String(i).padStart(3, "0")}`, [1, 1]]));
    expect(Object.keys(JSON.parse(histNext(JSON.stringify(long), { a: [1, 1, 1] }, "2026-12-31")))).toHaveLength(120);
    expect((await dre.call("GET", `/plans/${p.id}`)).body.following).toBeUndefined();
  });
});
