import { afterEach, describe, expect, it, vi } from "vitest";
import { api, db, mailbox, signIn } from "./helpers";

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
      db().prepare("INSERT INTO squads VALUES ('busm', 'busm', ?, 1, 1), ('solo', 'solo', ?, 1, 1)").bind(sam.uid, sam.uid),
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

describe("identity import", () => {
  const users = [
    { uid: "fbSam0000000000000000000001", email: "Sam@Example.com", name: "Sammy" },
    { uid: "fbDre0000000000000000000002", email: "dre@example.com" },
  ];

  it("is closed without the admin token, and absent when none is set", async () => {
    expect((await api("POST", "/admin/import-users", { body: { users } })).status).toBe(401);
    expect((await api("POST", "/admin/import-users", { body: { users }, token: "wrong" })).status).toBe(401);
    expect((await api("POST", "/admin/import-users", { body: { users }, token: "test-admin", env: { ADMIN_TOKEN: undefined } })).status).toBe(404);
  });

  it("imports by uid, idempotently; the first 3.0 sign-in lands on the old uid", async () => {
    const box = mailbox();
    const r = await api("POST", "/admin/import-users", { body: { users }, token: "test-admin" });
    expect(r.body).toEqual({ imported: 2, skipped: [] });
    const again = await api("POST", "/admin/import-users", { body: { users }, token: "test-admin" });
    expect(again.body).toEqual({ imported: 0, skipped: [] });
    const sam = await signIn("sam@example.com", box);
    expect(sam.uid).toBe(users[0].uid);
    expect(sam.new).toBe(false);
    expect(sam.name).toBe("Sammy");
    const dre = await signIn("dre@example.com", box);
    expect(dre.uid).toBe(users[1].uid);
    expect(dre.name).toBeNull();
  });

  it("carries the name and friend code across, when the import has them", async () => {
    const box = mailbox();
    const withCodes = [{ ...users[0], code: "SAM123" }, { ...users[1], code: "bad" },
                       { uid: "fbEve0000000000000000000003", email: "eve@example.com", code: "SAM123" }];
    expect((await api("POST", "/admin/import-users", { body: { users: withCodes }, token: "test-admin" })).body.imported).toBe(3);
    const sam = await signIn("sam@example.com", box);
    expect((await api("GET", "/board", { token: sam.token })).body.me.code).toBe("SAM123");
    expect(await db().prepare("SELECT code FROM users WHERE uid = ?").bind(withCodes[2].uid).first("code")).toBeNull();
    expect(await db().prepare("SELECT COUNT(*) AS n FROM codes").first("n")).toBe(1);
  });

  it("an address that already signed in to 3.0 under a new uid is skipped and reported", async () => {
    const box = mailbox();
    const early = await signIn("dre@example.com", box);
    const r = await api("POST", "/admin/import-users", { body: { users: [...users, { uid: "bad uid!", email: "x@y.com" }] }, token: "test-admin" });
    expect(r.body.imported).toBe(1);
    expect(r.body.skipped).toEqual(["bad uid!", users[1].uid]);
    expect((await signIn("dre@example.com", box)).uid).toBe(early.uid);
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
