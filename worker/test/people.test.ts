import { describe, expect, it } from "vitest";
import { api, db, person } from "./helpers";

// The admin's account lookup: one person at a time, never how they study.

const env = { ADMIN_UIDS: "sam" } as any;
const admin = (who: { token: string }, path: string, method = "GET", body?: unknown) => api(method, path, { token: who.token, env, body });

describe("the admin's account lookup", () => {
  it("only the admin; anyone else gets not found", async () => {
    await person("sam");
    const maya = await person("maya");
    for (const [m, p] of [["GET", "/admin/people?q=maya"], ["GET", "/admin/people/maya"], ["POST", "/admin/people/maya/signout"], ["DELETE", "/admin/people/maya"]]) {
      expect((await api(m, p, { token: maya.token, env, body: m === "DELETE" ? { email: "maya@example.com" } : undefined })).status).toBe(404);
    }
    expect(await db().prepare("SELECT COUNT(*) AS n FROM sessions WHERE uid = 'maya'").first<number>("n")).toBe(1);
  });

  it("search: an exact email, uid or friend code, or up to ten names that start with it; emails partly hidden", async () => {
    const sam = await person("sam");
    await person("maya", "Maya Chen");
    await person("mayb", "Maya R");
    await db().prepare("UPDATE users SET code = 'K7PMWQ2R' WHERE uid = 'maya'").run();
    await db().prepare("INSERT INTO codes (code, uid) VALUES ('K7PMWQ2R', 'maya')").run();
    for (let i = 0; i < 12; i++) await person(`zz${i}`, `Zed ${i}`);
    expect((await admin(sam, "/admin/people?q=ma")).status).toBe(400);  // at least 3
    const byName = (await admin(sam, "/admin/people?q=MAYA")).body.people;
    expect(byName.map((p: any) => p.name)).toEqual(["Maya Chen", "Maya R"]);
    expect(byName[0]).toMatchObject({ uid: "maya", email: "m•••@example.com" });
    expect(JSON.stringify(byName)).not.toContain("maya@example.com");
    expect((await admin(sam, "/admin/people?q=maya@example.com")).body.people.map((p: any) => p.uid)).toEqual(["maya"]);
    expect((await admin(sam, "/admin/people?q=k7pm wq2r")).body.people.map((p: any) => p.uid)).toEqual(["maya"]);
    expect((await admin(sam, "/admin/people?q=Zed")).body.people).toHaveLength(10);
    expect((await admin(sam, "/admin/people?q=%25%25%25")).body.people).toEqual([]);  // a wildcard is a character
  });

  it("one account: who, where, and counts; never how they study, who their crew are, or their settings", async () => {
    const sam = await person("sam");
    const maya = await person("maya", "Maya Chen");
    const dre = await person("dre");
    await person("kai");
    await maya.call("PUT", "/friends/dre"); await dre.call("PUT", "/friends/maya");
    await maya.call("PUT", "/friends/kai");
    const sq = await maya.call("POST", "/squads", { name: "MS2 Squad" });
    expect(sq.status).toBe(200);
    await maya.call("PUT", "/settings", { v: 1, at: new Date().toISOString(), settings: { muted: ["zed"] } });
    await maya.call("POST", "/sync", { week: { v: 1, days: {} } });
    await maya.call("POST", "/plans", { name: "Renal block", deck: "D" });
    await db().prepare("UPDATE users SET tz = -300, client_version = '3.4.0' WHERE uid = 'maya'").run();
    const r = await admin(sam, "/admin/people/maya");
    expect(r.status).toBe(200);
    expect(r.body).toMatchObject({ uid: "maya", name: "Maya Chen", email: "maya@example.com", version: "3.4.0", tz: -300,
      signedIn: { computers: 1, browsers: 0 }, crew: { mutual: 1, addedNotBack: 1, addedThem: 0, muted: 1 } });
    expect(r.body.squads).toEqual([{ name: "MS2 Squad", members: 1, founder: true }]);
    expect(r.body.made).toEqual([{ name: "Renal block", audience: "code", listed: false, followers: 0 }]);
    const text = JSON.stringify(r.body);
    for (const never of ["dre", "kai", "zed", "days", "week", "heatmap", "settings", "progress"]) expect(text).not.toContain(never);
    expect((await admin(sam, "/admin/people/nobody")).status).toBe(404);
  });

  it("sign out everywhere ends their sessions, not mine; delete needs their email typed and never takes mine", async () => {
    const sam = await person("sam");
    const maya = await person("maya");
    expect((await admin(sam, "/admin/people/maya/signout", "POST")).body.ended).toBe(1);
    expect(await maya.status("GET", "/auth/me")).toBe(401);
    expect(await sam.status("GET", "/auth/me")).toBe(200);
    expect((await admin(sam, "/admin/people/maya", "DELETE", { email: "wrong@example.com" })).body.error).toBe("confirm");
    expect(await db().prepare("SELECT COUNT(*) AS n FROM users WHERE uid = 'maya'").first<number>("n")).toBe(1);
    expect((await admin(sam, "/admin/people/sam", "DELETE", { email: "sam@example.com" })).body.error).toBe("self");
    expect((await admin(sam, "/admin/people/maya", "DELETE", { email: " Maya@Example.com " })).status).toBe(200);
    expect(await db().prepare("SELECT COUNT(*) AS n FROM users WHERE uid = 'maya'").first<number>("n")).toBe(0);
  });
});
