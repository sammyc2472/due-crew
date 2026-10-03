import { describe, expect, it } from "vitest";
import { api, db, mailbox, person } from "./helpers";

// Mock "Admin, grown up": sign-in help, the note, the audit log (A3, A5)
// and the squad tools (A4). Admin only; the founder is told; nothing logged
// holds an email or a code.

const env = { ADMIN_UIDS: "sam" } as any;
const admin = (who: { token: string }, path: string, method = "GET", body?: unknown) => api(method, path, { token: who.token, env, body });

describe("the admin's tools: only the admin", () => {
  it("anyone else gets not found, and nothing happens", async () => {
    await person("sam");
    const maya = await person("maya");
    const sq = (await maya.call("POST", "/squads", { name: "MS2" })).body;
    for (const [m, p, b] of [
      ["POST", "/admin/people/maya/code"], ["POST", "/admin/people/maya/limits"], ["PUT", "/admin/people/maya/email", { email: "x@example.com" }],
      ["DELETE", "/admin/people/maya/email"], ["PUT", "/admin/people/maya/note", { text: "x" }], ["GET", "/admin/actions"],
      ["GET", `/admin/squads/${sq.id}`], ["PATCH", `/admin/squads/${sq.id}`, { open: false }], ["POST", `/admin/squads/${sq.id}/code`],
      ["POST", `/admin/squads/${sq.id}/remove/maya`, {}], ["DELETE", `/admin/squads/${sq.id}`, { name: "MS2" }],
    ] as [string, string, unknown?][]) {
      expect((await api(m, p, { token: maya.token, env, body: b })).status).toBe(404);
    }
    expect(await db().prepare("SELECT open FROM squads WHERE id = ?").bind(sq.id).first<number>("open")).toBe(1);
    expect(await db().prepare("SELECT COUNT(*) AS n FROM admin_actions").first<number>("n")).toBe(0);
  });
});

describe("sign-in help", () => {
  it("a fresh code past the limits works in the add-on's code box, and the admin never sees it", async () => {
    const box = mailbox();
    const sam = await person("sam");
    await person("maya");
    // used up: ten codes this hour from everywhere
    for (let i = 0; i < 10; i++) await api("POST", "/auth/code", { body: { email: "maya@example.com" }, ip: `198.51.100.${i}` });
    expect((await api("POST", "/auth/code", { body: { email: "maya@example.com" }, ip: "198.51.100.99" })).status).toBe(429);
    let r = await admin(sam, "/admin/people/maya");
    expect(r.body.limits.codesHour).toBeGreaterThanOrEqual(10);
    r = await admin(sam, "/admin/people/maya/code", "POST");
    expect(r.status).toBe(200);
    const code = box.code("maya@example.com");
    expect(JSON.stringify(r.body)).not.toContain(code);
    const v = await api("POST", "/auth/verify", { body: { email: "maya@example.com", code, device: "anki" } });
    expect(v.status).toBe(200);
    expect(v.body.uid).toBe("maya");
    const log = (await admin(sam, "/admin/actions")).body.actions;
    expect(log[0]).toMatchObject({ action: "sent a sign-in code", uid: "maya", who: "Maya" });
    expect(JSON.stringify(log)).not.toContain("example.com");
    expect(JSON.stringify(log)).not.toContain(code);
  });

  it("clearing the limits lets them ask again", async () => {
    mailbox();
    const sam = await person("sam");
    await person("maya");
    for (let i = 0; i < 10; i++) await api("POST", "/auth/code", { body: { email: "maya@example.com" }, ip: `198.51.100.${i}` });
    expect((await api("POST", "/auth/code", { body: { email: "maya@example.com" }, ip: "198.51.100.50" })).status).toBe(429);
    expect((await admin(sam, "/admin/people/maya/limits", "POST")).status).toBe(200);
    expect((await admin(sam, "/admin/people/maya")).body.limits).toEqual({ codesHour: 0, codesDay: 0, failsDay: 0 });
    expect((await api("POST", "/auth/code", { body: { email: "maya@example.com" }, ip: "198.51.100.50" })).status).toBe(200);
  });

  it("an email change: both told, it happens at the new address's first sign-in, and a typo hands nothing over", async () => {
    const box = mailbox();
    const sam = await person("sam");
    const maya = await person("maya");
    await person("dre");
    expect((await admin(sam, "/admin/people/maya/email", "PUT", { email: "dre@example.com" })).status).toBe(409);  // someone's already
    expect((await admin(sam, "/admin/people/maya/email", "PUT", { email: "maya@example.com" })).body.error).toBe("same");
    expect((await admin(sam, "/admin/people/maya/email", "PUT", { email: " Maya.New@School.edu " })).body).toEqual({ ok: true, email: "maya.new@school.edu" });
    expect(box.sent.map((m) => m.to).sort()).toEqual(["maya.new@school.edu", "maya@example.com"]);
    expect((await admin(sam, "/admin/people/maya")).body.emailChange.email).toBe("maya.new@school.edu");
    // nothing changes until the new address signs in; the old one still works meanwhile
    expect(await maya.status("GET", "/auth/me")).toBe(200);
    expect(await db().prepare("SELECT email FROM users WHERE uid = 'maya'").first<string>("email")).toBe("maya@example.com");
    await api("POST", "/auth/code", { body: { email: "maya.new@school.edu" } });
    const v = await api("POST", "/auth/verify", { body: { email: "maya.new@school.edu", code: box.code("maya.new@school.edu"), device: "anki" } });
    expect(v.body).toMatchObject({ uid: "maya", new: false, name: "Maya" });
    expect(await db().prepare("SELECT email FROM users WHERE uid = 'maya'").first<string>("email")).toBe("maya.new@school.edu");
    expect(await db().prepare("SELECT COUNT(*) AS n FROM email_changes").first<number>("n")).toBe(0);
    // stopped before it happens: the new address makes a new account, as anyone's would
    await admin(sam, "/admin/people/dre/email", "PUT", { email: "dre2@example.com" });
    expect((await admin(sam, "/admin/people/dre/email", "DELETE")).status).toBe(200);
    await api("POST", "/auth/code", { body: { email: "dre2@example.com" } });
    const w = await api("POST", "/auth/verify", { body: { email: "dre2@example.com", code: box.code("dre2@example.com"), device: "anki" } });
    expect(w.body.uid).not.toBe("dre");
    expect(w.body.new).toBe(true);
  });

  it("a week later the change lapses", async () => {
    const box = mailbox();
    const sam = await person("sam");
    await person("maya");
    await admin(sam, "/admin/people/maya/email", "PUT", { email: "late@example.com" });
    await db().prepare("UPDATE email_changes SET at = at - 8 * 86400").run();
    await api("POST", "/auth/code", { body: { email: "late@example.com" } });
    const v = await api("POST", "/auth/verify", { body: { email: "late@example.com", code: box.code("late@example.com"), device: "anki" } });
    expect(v.body.uid).not.toBe("maya");
  });

  it("the note is the admin's, and goes with the account", async () => {
    const sam = await person("sam");
    await person("maya");
    expect((await admin(sam, "/admin/people/maya/note", "PUT", { text: "  School filter eats codes.  " })).status).toBe(200);
    expect((await admin(sam, "/admin/people/maya")).body.note.text).toBe("School filter eats codes.");
    expect((await admin(sam, "/admin/people/maya/note", "PUT", { text: "x".repeat(2001) })).status).toBe(400);
    await admin(sam, "/admin/people/maya/email", "PUT", { email: "maya2@example.com" });
    expect((await admin(sam, "/admin/people/maya", "DELETE", { email: "maya@example.com" })).status).toBe(200);
    expect(await db().prepare("SELECT COUNT(*) AS n FROM admin_notes").first<number>("n")).toBe(0);
    expect(await db().prepare("SELECT COUNT(*) AS n FROM email_changes").first<number>("n")).toBe(0);
    const log = (await admin(sam, "/admin/actions")).body.actions;
    expect(log[0]).toMatchObject({ action: "deleted an account", who: "a deleted account" });
  });
});

describe("the admin's squad tools", () => {
  async function squadOf3() {
    const box = mailbox();
    const sam = await person("sam");
    const maya = await person("maya");
    const dre = await person("dre");
    const kai = await person("kai");
    const sq = (await maya.call("POST", "/squads", { name: "MS2 Squad" })).body;
    for (const p of [dre, kai]) expect((await p.call("POST", `/squads/${sq.id}/join`, { code: sq.code })).status).toBe(200);
    return { box, sam, maya, dre, kai, sq };
  }

  it("found by its code; shows members by name, never their numbers", async () => {
    const { sam, sq } = await squadOf3();
    const hit = (await admin(sam, `/admin/people?q=${sq.code.slice(0, 4)} ${sq.code.slice(4)}`)).body;
    expect(hit.squad).toEqual({ id: sq.id, name: "MS2 Squad", members: 3 });
    const r = (await admin(sam, `/admin/squads/${sq.id}`)).body;
    expect(r).toMatchObject({ name: "MS2 Squad", founder: "maya", founderName: "Maya", open: true, removed: 0 });
    expect(r.members.map((m: any) => m.uid)).toEqual(["maya", "dre", "kai"]);  // the founder first
    for (const never of ["reviews", "streak", "study", "accuracy", "play"]) expect(JSON.stringify(r)).not.toContain(never);
    // an account's squads link to it
    expect((await admin(sam, "/admin/people/dre")).body.squads[0].id).toBe(sq.id);
  });

  it("remove: out, can't rejoin with the code, the founder is told; never the founder", async () => {
    const { box, sam, kai, sq } = await squadOf3();
    expect((await admin(sam, `/admin/squads/${sq.id}/remove/maya`, "POST", {})).body.error).toBe("founder");
    expect((await admin(sam, `/admin/squads/${sq.id}/remove/kai`, "POST", { why: "Not in our class" })).status).toBe(200);
    expect((await kai.call("POST", `/squads/${sq.id}/join`, { code: sq.code })).body.error).toBe("blocked");
    const mail = box.sent.find((m) => m.to === "maya@example.com")!;
    expect(mail.text).toContain("Sam removed Kai from your squad");
    expect(mail.text).toContain("Why: Not in our class");
    expect((await admin(sam, `/admin/squads/${sq.id}`)).body.actions[0]).toMatchObject({ action: "removed from a squad", who: "Kai" });
  });

  it("a new code: the old one opens nothing, the new one does, the id stays, members stay", async () => {
    const { box, sam, maya, sq } = await squadOf3();
    const zed = await person("zed");
    const r = await admin(sam, `/admin/squads/${sq.id}/code`, "POST");
    expect(r.status).toBe(200);
    const code = r.body.code as string;
    expect(code).toMatch(/^[A-Z2-9]{8}$/);
    expect(r.body.told).toBe(true);
    expect(box.sent.find((m) => m.to === "maya@example.com")!.text).toContain(`${code.slice(0, 4)} ${code.slice(4)}`);
    // the old code: no peek, no join, no restore that makes the squad again
    expect((await zed.call("GET", `/squads/peek?code=${sq.code}`)).status).toBe(404);
    expect((await zed.call("POST", `/squads/${sq.id}/join`, { code: sq.code })).body.error).toBe("wrong_code");
    expect((await zed.call("POST", "/squads/restore", { code: sq.code, name: "MS2 Squad" })).body.error).toBe("wrong_code");
    expect(await db().prepare("SELECT COUNT(*) AS n FROM squads").first<number>("n")).toBe(1);
    // the new one: peek gives the same id, and the join works
    const peek = await zed.call("GET", `/squads/peek?code=${code}`);
    expect(peek.body.id).toBe(sq.id);
    expect((await zed.call("POST", `/squads/${sq.id}/join`, { code })).status).toBe(200);
    expect((await zed.call("POST", "/squads/restore", { code, name: "MS2 Squad" })).status).toBe(200);  // a join, as before
    expect((await maya.call("GET", `/squads/${sq.id}`)).body.rows).toHaveLength(4);
    // a second new code retires the first
    const again = (await admin(sam, `/admin/squads/${sq.id}/code`, "POST")).body.code;
    expect((await zed.call("GET", `/squads/peek?code=${code}`)).status).toBe(404);
    expect((await zed.call("GET", `/squads/peek?code=${again}`)).body.id).toBe(sq.id);
    // the log never holds a code
    expect(JSON.stringify((await admin(sam, "/admin/actions")).body)).not.toContain(code);
  });

  it("close, rename and hand over, as the founder would; the founder and the new one are told", async () => {
    const { box, sam, dre, sq } = await squadOf3();
    const zed = await person("zed");
    expect((await admin(sam, `/admin/squads/${sq.id}`, "PATCH", { open: false, name: "MS2 Study" })).status).toBe(200);
    expect((await zed.call("POST", `/squads/${sq.id}/join`, { code: sq.code })).body.error).toBe("locked");
    expect((await admin(sam, `/admin/squads/${sq.id}`, "PATCH", { founder: "zed" })).body.error).toBe("not_member");
    expect((await admin(sam, `/admin/squads/${sq.id}`, "PATCH", { founder: "dre" })).status).toBe(200);
    expect((await dre.call("GET", `/squads/${sq.id}`)).body).toMatchObject({ name: "MS2 Study", founder: "dre", open: false });
    expect(box.sent.some((m) => m.to === "dre@example.com" && m.text.includes("made Dre its founder"))).toBe(true);
    expect((await admin(sam, `/admin/squads/${sq.id}`, "PATCH", { code: "X" })).status).toBe(400);
  });

  it("delete: the name typed out; members, bans and codes go with it", async () => {
    const { sam, sq } = await squadOf3();
    await admin(sam, `/admin/squads/${sq.id}/remove/kai`, "POST", {});
    await admin(sam, `/admin/squads/${sq.id}/code`, "POST");
    expect((await admin(sam, `/admin/squads/${sq.id}`, "DELETE", { name: "MS2" })).body.error).toBe("confirm");
    expect((await admin(sam, `/admin/squads/${sq.id}`, "DELETE", { name: "MS2 Squad" })).status).toBe(200);
    for (const t of ["squads", "members", "bans", "squad_codes"]) {
      expect(await db().prepare(`SELECT COUNT(*) AS n FROM ${t}`).first<number>("n")).toBe(0);
    }
    expect((await admin(sam, "/admin/actions")).body.actions[0]).toMatchObject({ squadName: "a deleted squad" });
  });
});
