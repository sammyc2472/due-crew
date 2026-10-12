import { afterEach, describe, expect, it, vi } from "vitest";
import { api, db, mailbox, person, signIn } from "./helpers";

afterEach(() => vi.restoreAllMocks());

const count = (sql: string, ...args: unknown[]) =>
  db().prepare(`SELECT COUNT(*) AS n FROM ${sql}`).bind(...args).first<number>("n");

describe("delete account", () => {
  it("takes everything of mine, sessions included, and leaves everyone else's", async () => {
    const box = mailbox();
    const sam = await signIn("sam@example.com", box, "mac");
    await signIn("sam@example.com", box, "pc");
    const dre = await signIn("dre@example.com", box);
    const t = 1_790_000_000;
    await db().batch([
      db().prepare("INSERT INTO friends VALUES (?, ?, ?), (?, ?, ?)").bind(sam.uid, dre.uid, t, dre.uid, sam.uid, t),
      db().prepare("INSERT INTO weeks VALUES (?, '{}', ?), (?, '{}', ?)").bind(sam.uid, t, dre.uid, t),
      db().prepare("INSERT INTO decks VALUES (?, '[]')").bind(sam.uid),
      db().prepare("INSERT INTO heatmaps VALUES (?, '{}')").bind(sam.uid),
      db().prepare("INSERT INTO settings VALUES (?, 1, 'x', '{}')").bind(sam.uid),
      db().prepare("INSERT INTO codes VALUES ('SAM123', ?), ('DRE123', ?)").bind(sam.uid, dre.uid),
      db().prepare("INSERT INTO cheers (to_uid, from_uid, emoji, at) VALUES (?, ?, '🎉', ?), (?, ?, '🎉', ?)")
        .bind(sam.uid, dre.uid, t, dre.uid, sam.uid, t),
      db().prepare("INSERT INTO knocks (to_uid, from_uid, at) VALUES (?, ?, ?)").bind(dre.uid, sam.uid, t),
    ]);
    const r = await api("DELETE", "/account", { token: sam.token });
    expect(r.status).toBe(200);
    for (const [table, col] of [["users", "uid"], ["sessions", "uid"], ["weeks", "uid"], ["decks", "uid"],
      ["heatmaps", "uid"], ["settings", "uid"], ["codes", "uid"]]) {
      expect(await count(`${table} WHERE ${col} = ?`, sam.uid), table).toBe(0);
    }
    expect(await count("friends WHERE owner = ?1 OR friend = ?1", sam.uid)).toBe(0);
    expect(await count("cheers WHERE to_uid = ?1 OR from_uid = ?1", sam.uid)).toBe(0);
    expect(await count("knocks WHERE to_uid = ?1 OR from_uid = ?1", sam.uid)).toBe(0);
    // Dre's own things stand
    expect(await count("users WHERE uid = ?", dre.uid)).toBe(1);
    expect(await count("weeks WHERE uid = ?", dre.uid)).toBe(1);
    expect(await count("codes WHERE uid = ?", dre.uid)).toBe(1);
    expect((await api("GET", "/auth/me", { token: sam.token })).status).toBe(401);
    expect((await api("GET", "/auth/me", { token: dre.token })).status).toBe(200);
    // the address can start over as a new account
    const again = await signIn("sam@example.com", box);
    expect(again.new).toBe(true);
    expect(again.uid).not.toBe(sam.uid);
  });

  it("a squad I founded passes to its longest-standing member; an empty one goes", async () => {
    const box = mailbox();
    const sam = await signIn("sam@example.com", box);
    const dre = await signIn("dre@example.com", box);
    const nia = await signIn("nia@example.com", box);
    await db().batch([
      db().prepare("INSERT INTO squads (id, name, founder, open, created_at) VALUES ('busm', 'busm', ?, 1, 1), ('solo', 'solo', ?, 1, 1)").bind(sam.uid, sam.uid),
      db().prepare("INSERT INTO members (squad, uid, name, joined_at) VALUES ('busm', ?, 'Sam', 1), ('busm', ?, 'Nia', 3), ('busm', ?, 'Dre', 2), ('solo', ?, 'Sam', 1)")
        .bind(sam.uid, nia.uid, dre.uid, sam.uid),
      db().prepare("INSERT INTO bans VALUES ('solo', 'someone')"),
    ]);
    expect((await api("DELETE", "/account", { token: sam.token })).status).toBe(200);
    expect(await db().prepare("SELECT founder FROM squads WHERE id = 'busm'").first("founder")).toBe(dre.uid);
    expect(await count("squads WHERE id = 'solo'")).toBe(0);
    expect(await count("bans WHERE squad = 'solo'")).toBe(0);
    expect(await count("members WHERE uid = ?", sam.uid)).toBe(0);
    expect(await count("members WHERE squad = 'busm'")).toBe(2);
  });

  it("needs a session", async () => {
    expect((await api("DELETE", "/account")).status).toBe(401);
  });
});

describe("housekeeping", () => {
  it("clears spent codes, old limit windows and idle sessions; nothing live", async () => {
    const { housekeeping } = await import("../src/index");
    const box = mailbox();
    const live = await signIn("sam@example.com", box);
    const idle = await signIn("dre@example.com", box);
    await api("POST", "/auth/code", { body: { email: "nia@example.com" } });   // a live code
    await api("POST", "/auth/code", { body: { email: "zed@example.com" } });
    await db().batch([
      db().prepare("UPDATE otp SET expires_at = 1 WHERE email = 'zed@example.com'"),
      db().prepare("UPDATE sessions SET last_used = 1 WHERE uid = ?").bind(idle.uid),
      db().prepare("INSERT INTO limits VALUES ('old', 3, 1)"),
    ]);
    await housekeeping((await import("cloudflare:workers")).env as any);
    expect(await count("otp")).toBe(1);
    expect(await count("limits WHERE key = 'old'")).toBe(0);
    expect(await count("limits")).toBeGreaterThan(0);  // this hour's windows stay
    expect(await count("sessions WHERE uid = ?", idle.uid)).toBe(0);
    expect((await api("GET", "/auth/me", { token: live.token })).status).toBe(200);
  });
});

describe("3.5.0: my accent on the site", () => {
  it("/auth/me carries the accent the add-on keeps in my settings; anything else is green", async () => {
    const { person } = await import("./helpers");
    const sam = await person("sam");
    expect((await sam.call("GET", "/auth/me")).body.accent).toBe("green");
    await sam.call("PUT", "/settings", { v: 1, at: "2026-09-28T18:00:00Z", settings: { accent: "rose" } });
    expect((await sam.call("GET", "/auth/me")).body.accent).toBe("rose");
    await sam.call("PUT", "/settings", { v: 1, at: "2026-09-28T18:01:00Z", settings: { accent: "</style>" } });
    expect((await sam.call("GET", "/auth/me")).body.accent).toBe("green");
  });
});

describe("3.8.0: the site's today is my Anki day", () => {
  it("/auth/me carries the hour my day rolls over once my add-on has said it", async () => {
    const { person } = await import("./helpers");
    const sam = await person("sam");
    expect((await sam.call("GET", "/auth/me")).body.rollover).toBeUndefined();
    expect(await sam.status("POST", "/sync", { profile: { tz: -240, rollover: 4 } })).toBe(200);
    expect((await sam.call("GET", "/auth/me")).body.rollover).toBe(4);
  });
});

describe("where I'm signed in (S6)", () => {
  it("counts computers and browsers, mine only", async () => {
    const maya = await person("maya");
    await person("dre");
    const r = await maya.call("GET", "/auth/places");
    expect(r.status).toBe(200);
    expect(r.body).toEqual({ computers: 1, browsers: 0 });
    expect((await api("GET", "/auth/places")).status).toBe(401);
  });
});

