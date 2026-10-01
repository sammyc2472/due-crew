import { describe, expect, it } from "vitest";
import { api, db, person } from "./helpers";

// 3.6.5, P6: Send feedback, to the admin's page; replies by mail from Due Crew.

const env = { ADMIN_UIDS: "sam" } as any;

describe("feedback (3.6.5, P6)", () => {
  it("signed in only; the text and the versions; 2,000 characters; 5 a day", async () => {
    const maya = await person("maya", "Maya");
    expect((await api("POST", "/feedback", { body: { text: "hi" } })).status).toBe(401);
    expect((await maya.call("POST", "/feedback", { text: "   " })).status).toBe(400);
    expect((await maya.call("POST", "/feedback", { text: "x".repeat(2001) })).status).toBe(400);
    expect((await maya.call("POST", "/feedback", { text: "hi", uid: "sam" })).status).toBe(400);
    const ok = await maya.call("POST", "/feedback", { text: "  The Plans tab\r\nis great  ", ver: "add-on 3.6.5 · Anki 24.11 · Mac\nx" });
    expect(ok.status).toBe(201);
    const row = await db().prepare("SELECT uid, text, ver, done FROM feedback").first<any>();
    expect(row).toEqual({ uid: "maya", text: "The Plans tab\nis great", ver: "add-on 3.6.5 · Anki 24.11 · Mac x", done: 0 });
    for (let i = 0; i < 4; i++) expect((await maya.call("POST", "/feedback", { text: `more ${i}` })).status).toBe(201);
    expect((await maya.call("POST", "/feedback", { text: "one too many" })).status).toBe(429);
  });

  it("the admin's panel: newest first, name and emoji (never the email), done and back, delete; nobody else", async () => {
    const sam = await person("sam", "Sam");
    const maya = await person("maya", "Maya");
    await maya.call("POST", "/sync", { profile: { emoji: "🦊" } });
    await maya.call("POST", "/feedback", { text: "first" });
    await maya.call("POST", "/feedback", { text: "second" });
    const admin = (method: string, path: string, body?: unknown) => api(method, path, { token: sam.token, env, body });
    expect((await api("GET", "/admin/feedback", { token: maya.token, env })).status).toBe(404);
    const got = (await admin("GET", "/admin/feedback")).body;
    expect(got.open).toBe(2);
    expect(got.feedback.map((f: any) => f.text)).toEqual(["second", "first"]);
    expect(got.feedback[0]).toMatchObject({ uid: "maya", name: "Maya", emoji: "🦊", done: false });
    expect(JSON.stringify(got)).not.toContain("@example.com");
    const id = got.feedback[0].id;
    expect((await api("PATCH", `/admin/feedback/${id}`, { token: maya.token, env, body: { done: true } })).status).toBe(404);
    expect((await admin("PATCH", `/admin/feedback/${id}`, { done: true })).status).toBe(200);
    expect((await admin("GET", "/admin/feedback")).body.feedback.map((f: any) => f.text)).toEqual(["first"]);
    expect((await admin("GET", "/admin/feedback?state=done")).body.feedback.map((f: any) => f.text)).toEqual(["second"]);
    expect((await admin("DELETE", `/admin/feedback/${id}`)).status).toBe(200);
    expect((await admin("GET", "/admin/feedback?state=all")).body.feedback).toHaveLength(1);
  });

  it("reply: mailed from Due Crew to the sender with what they wrote quoted; marked replied and done", async () => {
    const sam = await person("sam", "Sam");
    const maya = await person("maya", "Maya");
    await maya.call("POST", "/feedback", { text: "Bingo counted wrong\nfor me" });
    const sent: any[] = [];
    const EMAIL = { send: async (m: any) => { sent.push(m); } };
    const id = (await api("GET", "/admin/feedback", { token: sam.token, env })).body.feedback[0].id;
    const r = await api("POST", `/admin/feedback/${id}/reply`, { token: sam.token, env: { ...env, EMAIL }, body: { text: "Thanks! Fixed in 3.6.6." } });
    expect(r.status).toBe(200);
    expect(sent).toHaveLength(1);
    expect(sent[0]).toMatchObject({ to: "maya@example.com", subject: "Sam from Due Crew, about your feedback" });
    expect(sent[0].text).toContain("Thanks! Fixed in 3.6.6.");
    expect(sent[0].text).toContain("> Bingo counted wrong\n> for me");
    expect(await db().prepare("SELECT replied, done FROM feedback").first<any>()).toEqual({ replied: 1, done: 1 });
    expect((await api("POST", `/admin/feedback/${id}/reply`, { token: maya.token, env: { ...env, EMAIL }, body: { text: "x" } })).status).toBe(404);
  });

  it("deleting an account deletes its feedback", async () => {
    const maya = await person("maya", "Maya");
    await maya.call("POST", "/feedback", { text: "bye" });
    expect((await maya.call("DELETE", "/account", {})).status).toBeLessThan(300);
    expect(await db().prepare("SELECT COUNT(*) AS n FROM feedback").first<number>("n")).toBe(0);
  });
});
