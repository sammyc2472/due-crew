import { describe, expect, it } from "vitest";
import { housekeeping } from "../src/index";
import { env } from "cloudflare:workers";
import { api, befriend, db, mailbox, person } from "./helpers";

describe("3.4.1: one-time invites", () => {
  it("the link makes us crew at once, both edges, one use", async () => {
    const sam = await person("sam");
    const maya = await person("maya");
    const kai = await person("kai");
    const made = await sam.call("POST", "/invites");
    expect(made.status).toBe(200);
    const code = made.body.code as string;
    expect(code).toMatch(/^[A-Z0-9]{10}$/);
    // only the hash is kept
    const row = await db().prepare("SELECT hash FROM invites WHERE uid = 'sam'").first<string>("hash");
    expect(row).not.toContain(code);
    // signed out, the page sees whose it is and that it works
    const peek = await api("GET", `/invites/${code.toLowerCase()}`);
    expect(peek.body).toEqual({ kind: "invite", name: "Sam", emoji: "", state: "ok" });
    const r = await maya.call("POST", `/invites/${code}/redeem`);
    expect(r.body).toEqual({ uid: "sam", name: "Sam", emoji: "", mutual: true, knocked: false });
    const edges = await db().prepare("SELECT owner, friend FROM friends ORDER BY owner").all();
    expect(edges.results).toEqual([{ owner: "maya", friend: "sam" }, { owner: "sam", friend: "maya" }]);
    // once only: after that it adds, and Sam adds back (a link in a group chat)
    const late = await kai.call("POST", `/invites/${code}/redeem`);
    expect(late.body).toMatchObject({ uid: "sam", mutual: false, knocked: true });
    expect(await db().prepare("SELECT COUNT(*) AS n FROM friends WHERE owner = 'sam' AND friend = 'kai'").first<number>("n")).toBe(0);
    expect(await db().prepare("SELECT COUNT(*) AS n FROM knocks WHERE to_uid = 'sam' AND from_uid = 'kai'").first<number>("n")).toBe(1);
    expect((await api("GET", `/invites/${code}`)).body.state).toBe("used");
    // the same person again writes nothing: a removal since stays a removal
    await sam.call("DELETE", "/friends/maya");
    const again = await maya.call("POST", `/invites/${code}/redeem`);
    expect(again.body.mutual).toBe(false);
    expect(await db().prepare("SELECT COUNT(*) AS n FROM friends WHERE owner = 'sam'").first<number>("n")).toBe(0);
  });

  it("not my own; after 14 days an add; gone with a new code; a knock between us goes", async () => {
    const sam = await person("sam");
    const maya = await person("maya");
    await befriend(maya, sam);
    await db().prepare("INSERT INTO knocks (to_uid, from_uid, squad, at) VALUES ('sam', 'maya', NULL, 1)").run();
    const a = (await sam.call("POST", "/invites")).body.code;
    expect((await sam.call("POST", `/invites/${a}/redeem`)).status).toBe(400);
    const now = Math.floor(Date.now() / 1000);
    await db().prepare("UPDATE invites SET expires_at = ?").bind(now - 86400).run();
    expect((await api("GET", `/invites/${a}`)).body.state).toBe("expired");
    await housekeeping(env as any);  // kept a year, for the add
    expect((await api("GET", `/invites/${a}`)).body.state).toBe("expired");
    await db().prepare("UPDATE invites SET expires_at = ?").bind(now - 360 * 86400).run();
    await housekeeping(env as any);
    expect((await api("GET", `/invites/${a}`)).status).toBe(404);
    const b = (await sam.call("POST", "/invites")).body.code;
    await sam.call("POST", "/codes");
    expect((await maya.call("POST", `/invites/${b}/redeem`)).status).toBe(404);
    const c = (await sam.call("POST", "/invites")).body.code;
    expect((await maya.call("POST", `/invites/${c}/redeem`)).body.mutual).toBe(true);
    expect(await db().prepare("SELECT COUNT(*) AS n FROM knocks").first<number>("n")).toBe(0);
  });

  it("expired, it adds and knocks; already crew, it says so and adds nothing", async () => {
    const sam = await person("sam");
    const maya = await person("maya");
    const a = (await sam.call("POST", "/invites")).body.code;
    await db().prepare("UPDATE invites SET expires_at = 1").run();
    const r = await maya.call("POST", `/invites/${a}/redeem`);
    expect(r.body).toMatchObject({ mutual: false, knocked: true });
    await sam.call("PUT", "/friends/maya");  // Add back
    const again = await maya.call("POST", `/invites/${a}/redeem`);
    expect(again.body).toMatchObject({ mutual: true, knocked: false });
    expect(await db().prepare("SELECT COUNT(*) AS n FROM knocks").first<number>("n")).toBe(0);
  });

  it("a friend code answers the page signed out: a name and an emoji, nothing more", async () => {
    const sam = await person("sam");
    const code = (await sam.call("POST", "/codes")).body.code;
    const r = await api("GET", `/invites/${code}`);
    expect(r.body).toEqual({ kind: "code", name: "Sam", emoji: "", state: "ok" });
    expect((await api("GET", "/invites/ZZZZZZ")).status).toBe(404);
    expect((await api("GET", "/invites/ABC")).status).toBe(404);
  });

  it("a ceiling on making them, and guessing stays slow", async () => {
    const sam = await person("sam");
    for (let i = 0; i < 20; i++) expect(await sam.status("POST", "/invites")).toBe(200);
    expect(await sam.status("POST", "/invites")).toBe(429);
    let last = 0;
    for (let i = 0; i < 301; i++) last = (await api("GET", "/invites/AAAAAAAAAA", { ip: "198.51.100.9" })).status;
    expect(last).toBe(429);
  });

  it("the phone can email itself an invite link", async () => {
    const box = mailbox();
    const ok = await api("POST", "/links/email", { body: { email: "a@example.com", path: "/i/K7Q2ZPAB12" }, headers: { "x-due-crew": "1" } });
    expect(ok.status).toBe(200);
    expect(box.sent[0].text).toContain("https://duecrew.com/i/K7Q2ZPAB12");
    const bad = await api("POST", "/links/email", { body: { email: "a@example.com", path: "/i/K7Q" }, headers: { "x-due-crew": "1" } });
    expect(bad.status).toBe(400);
  });
});
