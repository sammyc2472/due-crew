import { afterEach, describe, expect, it, vi } from "vitest";
import { api, db, mailbox, signIn } from "./helpers";

afterEach(() => vi.restoreAllMocks());

describe("version", () => {
  it("answers without auth: the api and the oldest client it serves", async () => {
    const r = await api("GET", "/version");
    expect(r.status).toBe(200);
    expect(r.body).toEqual({ api: 1, minClient: "3.0.0" });
  });
  it("unknown paths are 404, wrong methods 405", async () => {
    expect((await api("GET", "/nope")).status).toBe(404);
    expect((await api("GET", "/auth/code")).status).toBe(405);
  });
});

describe("codes", () => {
  it("sends six digits by plain text, no links, from the Resend key", async () => {
    const box = mailbox();
    const r = await api("POST", "/auth/code", { body: { email: "  Sam@Example.COM " } });
    expect(r.status).toBe(200);
    expect(box.sent).toHaveLength(1);
    expect(box.sent[0].to).toBe("sam@example.com");
    expect(box.sent[0].auth).toBe("Bearer test-resend");
    expect(box.sent[0].text).toMatch(/^Your Due Crew code: \d{3} \d{3}\. It expires in 10 minutes\.$/);
    expect(box.sent[0].text).not.toMatch(/http|www\./);
  });

  it("sends through Cloudflare's binding when there is one, and Resend is left alone", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const sent: any[] = [];
    const EMAIL = { send: async (m: any) => { sent.push(m); } };
    const r = await api("POST", "/auth/code", { body: { email: "sam@example.com" }, env: { EMAIL } as any });
    expect(r.status).toBe(200);
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(sent).toHaveLength(1);
    expect(sent[0]).toMatchObject({ to: "sam@example.com", from: "codes@duecrew.com", subject: "Your Due Crew code" });
    expect(sent[0].text).toMatch(/^Your Due Crew code: \d{3} \d{3}\. It expires in 10 minutes\.$/);
    const failing = { send: async () => { throw new Error("nope"); } };
    expect((await api("POST", "/auth/code", { body: { email: "dre@example.com" }, env: { EMAIL: failing } as any })).status).toBe(502);
  });

  it("stores the code hashed, never the digits", async () => {
    const box = mailbox();
    await api("POST", "/auth/code", { body: { email: "sam@example.com" } });
    const row = await db().prepare("SELECT * FROM otp").first<any>();
    expect(row.code_hash).toMatch(/^[0-9a-f]{64}$/);
    expect(JSON.stringify(row)).not.toContain(box.code("sam@example.com"));
  });

  it("with no Resend key, logs the code and sends nothing; the address stays out of the log", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const log = vi.spyOn(console, "log").mockImplementation(() => {});
    const r = await api("POST", "/auth/code", { body: { email: "dev@example.com" }, env: { RESEND_API_KEY: undefined } });
    expect(r.status).toBe(200);
    expect(fetchSpy).not.toHaveBeenCalled();
    const line = log.mock.calls.map((c) => c.join(" ")).join("\n");
    expect(line).toMatch(/code: \d{3} \d{3}/);
    expect(line).not.toContain("dev@example.com");
  });

  it("refuses what isn't an address", async () => {
    mailbox();
    for (const email of ["", "nope", "a@b", 7, null]) {
      expect((await api("POST", "/auth/code", { body: { email } })).status).toBe(400);
    }
    expect((await api("POST", "/auth/code", { raw: "{not json" })).status).toBe(400);
  });

  it("five codes an hour per address, then slow down", async () => {
    mailbox();
    for (let i = 0; i < 5; i++) expect((await api("POST", "/auth/code", { body: { email: "a@x.com" } })).status).toBe(200);
    const r = await api("POST", "/auth/code", { body: { email: "a@x.com" } });
    expect(r.status).toBe(429);
    expect(r.body.error).toBe("slow_down");
    expect(r.headers.get("retry-after")).toBe("3600");
  });

  it("twenty codes an hour per IP, across addresses", async () => {
    mailbox();
    for (let i = 0; i < 20; i++) {
      expect((await api("POST", "/auth/code", { body: { email: `p${i}@x.com` }, ip: "198.51.100.1" })).status).toBe(200);
    }
    expect((await api("POST", "/auth/code", { body: { email: "late@x.com" }, ip: "198.51.100.1" })).status).toBe(429);
    expect((await api("POST", "/auth/code", { body: { email: "late@x.com" }, ip: "198.51.100.2" })).status).toBe(200);
  });

  it("a new code replaces the old one", async () => {
    const box = mailbox();
    await api("POST", "/auth/code", { body: { email: "sam@example.com" } });
    const first = box.code("sam@example.com");
    await api("POST", "/auth/code", { body: { email: "sam@example.com" } });
    const second = box.code("sam@example.com");
    if (first !== second) {
      const r = await api("POST", "/auth/verify", { body: { email: "sam@example.com", code: first } });
      expect(r.status).toBe(400);
    }
    expect((await api("POST", "/auth/verify", { body: { email: "sam@example.com", code: second } })).status).toBe(200);
  });
});

describe("verify", () => {
  it("an unknown address becomes a new account with a ULID uid", async () => {
    const box = mailbox();
    const s = await signIn("new@example.com", box);
    expect(s.new).toBe(true);
    expect(s.name).toBeNull();
    expect(s.uid).toMatch(/^[0-9A-HJKMNP-TV-Z]{26}$/);
    expect(s.token).toMatch(/^[A-Za-z0-9_-]{43}$/);
  });

  it("the same address, any case or spacing, lands on the same uid", async () => {
    const box = mailbox();
    const a = await signIn("Sam@Example.com", box);
    const b = await signIn("  sam@example.COM", box);
    expect(b.uid).toBe(a.uid);
    expect(b.new).toBe(false);
    expect(b.token).not.toBe(a.token);
  });

  it("accepts the code with its space, as the mail shows it", async () => {
    const box = mailbox();
    await api("POST", "/auth/code", { body: { email: "sam@example.com" } });
    const c = box.code("sam@example.com");
    const r = await api("POST", "/auth/verify", { body: { email: "sam@example.com", code: `${c.slice(0, 3)} ${c.slice(3)}` } });
    expect(r.status).toBe(200);
  });

  it("a code cannot be replayed", async () => {
    const box = mailbox();
    await api("POST", "/auth/code", { body: { email: "sam@example.com" } });
    const code = box.code("sam@example.com");
    expect((await api("POST", "/auth/verify", { body: { email: "sam@example.com", code } })).status).toBe(200);
    const again = await api("POST", "/auth/verify", { body: { email: "sam@example.com", code } });
    expect(again.status).toBe(400);
    expect(again.body.error).toBe("expired");
  });

  it("a code expires after ten minutes", async () => {
    const box = mailbox();
    await api("POST", "/auth/code", { body: { email: "sam@example.com" } });
    await db().prepare("UPDATE otp SET expires_at = expires_at - 601").run();
    const r = await api("POST", "/auth/verify", { body: { email: "sam@example.com", code: box.code("sam@example.com") } });
    expect(r.status).toBe(400);
    expect(r.body.error).toBe("expired");
  });

  it("a code dies after five wrong tries, even the right digits after", async () => {
    const box = mailbox();
    await api("POST", "/auth/code", { body: { email: "sam@example.com" } });
    const right = box.code("sam@example.com");
    const wrong = right === "000000" ? "111111" : "000000";
    for (let i = 0; i < 4; i++) {
      expect((await api("POST", "/auth/verify", { body: { email: "sam@example.com", code: wrong } })).body.error).toBe("wrong_code");
    }
    expect((await api("POST", "/auth/verify", { body: { email: "sam@example.com", code: wrong } })).body.error).toBe("expired");
    expect((await api("POST", "/auth/verify", { body: { email: "sam@example.com", code: right } })).status).toBe(400);
  });

  it("six wrong codes lock the address for the window: no sign-in, no new code", async () => {
    const box = mailbox();
    const email = "sam@example.com";
    await api("POST", "/auth/code", { body: { email } });
    const wrong = box.code(email) === "000000" ? "111111" : "000000";
    for (let i = 0; i < 5; i++) await api("POST", "/auth/verify", { body: { email, code: wrong } });
    await api("POST", "/auth/code", { body: { email } });
    const w2 = box.code(email) === "000000" ? "111111" : "000000";
    expect((await api("POST", "/auth/verify", { body: { email, code: w2 } })).status).toBe(400);  // the sixth
    const right = await api("POST", "/auth/verify", { body: { email, code: box.code(email) } });
    expect(right.status).toBe(429);
    expect(right.body.error).toBe("locked");
    expect((await api("POST", "/auth/code", { body: { email } })).body.error).toBe("locked");
    // another address is untouched
    expect((await signIn("other@example.com", box)).token).toBeTruthy();
    // the window passes
    await db().prepare("UPDATE limits SET window_start = window_start - 3601").run();
    expect((await signIn(email, box)).token).toBeTruthy();
  });

  it("no code on file is the same answer as an expired one", async () => {
    const r = await api("POST", "/auth/verify", { body: { email: "ghost@example.com", code: "123456" } });
    expect(r.status).toBe(400);
    expect(r.body.error).toBe("expired");
  });
});

describe("sessions", () => {
  it("stores the token's SHA-256 with the device label, never the token", async () => {
    const box = mailbox();
    const s = await signIn("sam@example.com", box, "Sam's MacBook");
    const row = await db().prepare("SELECT * FROM sessions").first<any>();
    expect(row.uid).toBe(s.uid);
    expect(row.device).toBe("Sam's MacBook");
    expect(row.token_hash).toMatch(/^[0-9a-f]{64}$/);
    expect(JSON.stringify(row)).not.toContain(s.token);
  });

  it("a bad or missing token is 401", async () => {
    expect((await api("POST", "/auth/signout")).status).toBe(401);
    expect((await api("POST", "/auth/signout", { token: "x".repeat(43) })).status).toBe(401);
    expect((await api("POST", "/auth/signout", { token: "short" })).status).toBe(401);
  });

  it("a session token is unusable after sign-out; the other device carries on", async () => {
    const box = mailbox();
    const mac = await signIn("sam@example.com", box, "mac");
    const pc = await signIn("sam@example.com", box, "pc");
    expect((await api("POST", "/auth/signout", { token: mac.token })).status).toBe(200);
    expect((await api("POST", "/auth/signout", { token: mac.token })).status).toBe(401);
    expect((await api("POST", "/auth/signout-all", { token: pc.token })).status).toBe(200);
  });

  it("sign out everywhere ends every session of mine, and only mine", async () => {
    const box = mailbox();
    const mac = await signIn("sam@example.com", box, "mac");
    const pc = await signIn("sam@example.com", box, "pc");
    const dre = await signIn("dre@example.com", box);
    expect((await api("POST", "/auth/signout-all", { token: mac.token })).status).toBe(200);
    expect((await api("POST", "/auth/signout", { token: pc.token })).status).toBe(401);
    expect((await api("POST", "/auth/signout", { token: dre.token })).status).toBe(200);
  });

  it("an idle session ends after 180 days", async () => {
    const box = mailbox();
    const s = await signIn("sam@example.com", box);
    await db().prepare("UPDATE sessions SET last_used = last_used - 180 * 86400").run();
    expect((await api("GET", "/auth/me", { token: s.token })).status).toBe(401);
    expect(await db().prepare("SELECT COUNT(*) AS n FROM sessions").first("n")).toBe(0);
  });

  it("a session in use stays alive, and is touched at most once a day", async () => {
    const box = mailbox();
    const s = await signIn("sam@example.com", box);
    const at = () => db().prepare("SELECT last_used FROM sessions").first<number>("last_used");
    await db().prepare("UPDATE sessions SET last_used = last_used - 179 * 86400").run();
    const old = await at();
    const me = await api("GET", "/auth/me", { token: s.token });
    expect(me.status).toBe(200);
    expect(me.body).toEqual({ uid: s.uid, email: "sam@example.com", name: null, emoji: null });
    const touched = await at();
    expect(touched).toBeGreaterThan(old!);
    await api("GET", "/auth/me", { token: s.token });
    expect(await at()).toBe(touched);  // same day: no second write
  });
});
