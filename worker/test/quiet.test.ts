import { describe, expect, it } from "vitest";
import { env } from "cloudflare:workers";
import { api, db, person, befriend } from "./helpers";
import * as Quiet from "../src/quiet";

// "The next round", Q1-Q6: quiet accounts. Trimmed at 6 months (only what a
// sync rebuilds), deleted at 12 (24 paused), a few a day; a followed plan
// outlives its owner; a hash says why to an add-on that comes back.

const DAY = 86400;
const now = Math.floor(Date.now() / 1000);
const age = async (uid: string, days: number) => {
  const t = now - days * DAY;
  await db().prepare("UPDATE users SET last_seen = ?, created_at = ? WHERE uid = ?").bind(t, t, uid).run();
  await db().prepare("UPDATE weeks SET updated_at = ? WHERE uid = ?").bind(t, uid).run();
};
const has = async (table: string, uid: string) => !!(await db().prepare(`SELECT 1 FROM ${table} WHERE uid = ?`).bind(uid).first());

describe("quiet accounts", () => {
  it("6 months quiet: only what a sync rebuilds goes; the account, crew, squads and week stay", async () => {
    const maya = await person("maya");
    const dre = await person("dre");
    await befriend(maya, { uid: "dre" }); await befriend(dre, { uid: "maya" });
    await maya.call("POST", "/sync", { week: { v: 1, days: {} }, heatmap: { "2026-01-01": 3 } });
    await db().prepare("INSERT INTO weeks (uid, doc, updated_at) VALUES ('maya', '{}', 0) ON CONFLICT(uid) DO NOTHING").run();
    await db().prepare("INSERT INTO decks (uid, json) VALUES ('maya', '{}') ON CONFLICT(uid) DO NOTHING").run();
    await db().prepare("INSERT INTO knows (uid, guid) VALUES ('maya', 'g1')").run();
    await age("maya", 200);
    await age("dre", 100);
    const r = await Quiet.run(env as any, now);
    expect(r.deleted).toBe(0);
    for (const t of ["decks", "heatmaps", "plan_trees", "knows"]) expect(await has(t, "maya")).toBe(false);
    expect(await has("users", "maya")).toBe(true);
    expect(await has("weeks", "maya")).toBe(true);
    expect(await db().prepare("SELECT COUNT(*) AS n FROM friends").first<number>("n")).toBe(2);
  });

  it("12 months quiet goes, 24 when paused; a recent sync, a 2.x week or an admin keeps it; at most 50 a day", async () => {
    for (const u of ["old", "pausedold", "pausedolder", "fresh", "bridged", "sam"]) await person(u);
    await age("old", 400); await age("pausedold", 400); await age("pausedolder", 800); await age("fresh", 10); await age("sam", 900);
    for (const u of ["pausedold", "pausedolder"]) await db().prepare("INSERT INTO settings (uid, v, at, json) VALUES (?, 1, '', '{\"paused\":true}')").bind(u).run();
    await age("bridged", 400);
    await db().prepare("INSERT INTO weeks (uid, doc, updated_at) VALUES ('bridged', '{}', ?) ON CONFLICT(uid) DO UPDATE SET updated_at = excluded.updated_at").bind(now - 5 * DAY).run();
    const r = await Quiet.run({ ...(env as any), ADMIN_UIDS: "sam" }, now);
    const left = (await db().prepare("SELECT uid FROM users ORDER BY uid").all<{ uid: string }>()).results.map((x) => x.uid);
    expect(left).toEqual(["bridged", "fresh", "pausedold", "sam"]);
    expect(r.deleted).toBe(2);
    const log = (await db().prepare("SELECT action FROM admin_actions ORDER BY action").all<{ action: string }>()).results.map((x) => x.action);
    expect(log).toEqual(["deleted, 12 months quiet", "deleted, 24 months quiet (paused)"]);
    const many = Array.from({ length: 55 }, (_, i) => `q${i}`);
    for (const u of many) { await person(u); await age(u, 500); }
    expect((await Quiet.run(env as any, now)).deleted).toBe(50);
  });

  it("a plan someone follows outlives a quiet owner: its first co-author takes it, or it stays by a former member", async () => {
    const dre = await person("dre");
    const kai = await person("kai");
    const maya = await person("maya");
    await befriend(dre, { uid: "kai" }); await befriend(kai, { uid: "dre" });
    const mk = async (name: string) => {
      const made = await dre.call("POST", "/plans", { name, deck: "D" });
      return (await dre.call("PUT", `/plans/${made.body.id}`, { version: 1, doc: { deck: "D", units: [{ id: "a", name: "A", opens: "2026-10-05", tags: ["X"] }] } })).body;
    };
    const withEd = await mk("Cardio"), alone = await mk("Renal"), nobody = await mk("Neuro");
    await dre.call("POST", `/plans/${withEd.id}/editors`, { uid: "kai" });
    await maya.call("POST", "/plans/follow", { code: withEd.code });
    await maya.call("POST", "/plans/follow", { code: alone.code });
    await age("dre", 400);
    await Quiet.run(env as any, now);
    const owners = Object.fromEntries((await db().prepare("SELECT name, owner FROM plans").all<{ name: string; owner: string }>()).results.map((p) => [p.name, p.owner]));
    expect(owners).toEqual({ Cardio: "kai", Renal: "" });  // Neuro, followed by no one, went with its owner
    expect(await db().prepare("SELECT COUNT(*) AS n FROM plan_editors WHERE plan = ?").bind(withEd.id).first<number>("n")).toBe(0);
    const peek = await api("GET", `/plans/public?code=${alone.code}`);
    expect(peek.body.ownerName).toBe("a former member");
    expect((await maya.call("GET", `/plans/${alone.id}`)).status).toBe(200);
    expect((await maya.call("PUT", `/plans/${alone.id}`, { version: 2, doc: { deck: "D", units: [] } })).status).toBe(403);
    void nobody;
  });

  it("an add-on that comes back can ask why: yes for a deleted quiet uid, no otherwise, nothing else", async () => {
    await person("gone1"); await person("here");
    await age("gone1", 400);
    await Quiet.run(env as any, now);
    expect((await api("GET", "/auth/gone?uid=gone1")).body).toEqual({ gone: true, after: 365 });
    expect((await api("GET", "/auth/gone?uid=here")).body).toEqual({ gone: false });
    expect((await api("GET", "/auth/gone?uid=nobody")).body).toEqual({ gone: false });
    expect((await api("GET", "/auth/gone?uid=%27%3B")).body).toEqual({ gone: false });
    const row = await db().prepare("SELECT h FROM gone").first<string>("h");
    expect(row).not.toContain("gone1");
  });

  it("the admin's housekeeping counts", async () => {
    for (const [u, d] of [["a", 100], ["b", 200], ["c", 350], ["d", 5]] as const) { await person(u); await age(u, d); }
    expect(await Quiet.counts(env as any, now)).toEqual({ folded: 1, quiet: 2, dueSoon: 1 });
  });
});
