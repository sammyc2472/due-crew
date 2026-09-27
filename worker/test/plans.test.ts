import { describe, expect, it } from "vitest";
import { api, db, person } from "./helpers";

const SITE = { "x-due-crew": "1" };  // what the site's own script sends

const UNITS = [
  { id: "hf", name: "Heart failure", opens: "2026-10-05", due: "2026-10-12", tags: ["Step1::Cardio::Heart_failure"] },
  { id: "arr", name: "Arrhythmia", opens: "2026-10-12", tags: ["Step1::Cardio::Arrhythmia"], cards: [["g1", 0], ["g1", 0], ["g2", 1]] },
];

async function authored() {
  const dre = await person("dre");
  const made = await dre.call("POST", "/plans", { name: "Step 1", deck: "Step 1" });
  expect(made.status).toBe(200);
  const put = await dre.call("PUT", `/plans/${made.body.id}`, { version: 1, doc: { deck: "Step 1", units: UNITS } });
  expect(put.status).toBe(200);
  return { dre, plan: put.body };
}

describe("plans: authoring", () => {
  it("a new plan is the author's, with a code only they see", async () => {
    const { dre, plan } = await authored();
    expect(plan.version).toBe(2);
    expect(plan.code).toMatch(/^[A-Z2-9]{8}$/);
    expect(plan.doc.units.map((u: any) => u.id)).toEqual(["hf", "arr"]);
    expect(plan.doc.units[1].cards).toEqual([["g1", 0], ["g2", 1]]);  // deduped
    const maya = await person("maya");
    expect(await maya.status("GET", `/plans/${plan.id}`)).toBe(404);  // no code, no plan
    const peek = await maya.call("GET", `/plans/peek?code=${plan.code.toLowerCase()}`);
    expect(peek.status).toBe(200);
    expect(peek.body.code).toBeUndefined();  // the code is the author's to hand out
    expect(await dre.status("GET", "/plans/mine")).toBe(200);
  });

  it("only the author edits; a stale version is refused with the current one", async () => {
    const { dre, plan } = await authored();
    const maya = await person("maya");
    expect(await maya.status("PUT", `/plans/${plan.id}`, { version: 2, name: "Mine now" })).toBe(403);
    const stale = await dre.call("PUT", `/plans/${plan.id}`, { version: 1, name: "Late" });
    expect(stale.status).toBe(409);
    expect(stale.body).toEqual({ error: "stale", version: 2 });
    const same = await dre.call("PUT", `/plans/${plan.id}`, { version: 2, name: "Step 1" });
    expect(same.body.version).toBe(2);  // nothing changed, nothing written
  });

  it("refuses bad shapes: due before opens, card text, too many cards", async () => {
    const { dre, plan } = await authored();
    const put = (doc: unknown) => dre.status("PUT", `/plans/${plan.id}`, { version: 2, doc });
    expect(await put({ deck: "Step 1", units: [{ id: "a", name: "A", opens: "2026-10-05", due: "2026-10-01" }] })).toBe(400);
    expect(await put({ deck: "Step 1", units: [{ id: "a", name: "A", opens: "2026-10-05", text: "card text" }] })).toBe(400);
    expect(await put({ deck: "Step 1", units: [{ id: "a", name: "A", opens: "2026-10-05",
      cards: Array.from({ length: 50001 }, (_, i) => [`g${i}`, 0]) }] })).toBe(400);
    expect(await put({ deck: "Step 1", units: [UNITS[0], UNITS[0]] })).toBe(400);  // ids are unique
    expect(await put({ deck: "Step 1", units: [{ ...UNITS[0], n: "212" }] })).toBe(400);  // a count is a number
    const counted = await dre.call("PUT", `/plans/${plan.id}`, { version: 2, doc: { deck: "Step 1", units: [{ ...UNITS[0], n: 212 }] } });
    expect(counted.body.doc.units[0].n).toBe(212);
  });

  it("3.3: an even split needs a window; the pace is the builder's, shaped", async () => {
    const { dre, plan } = await authored();
    const put = (doc: unknown) => dre.call("PUT", `/plans/${plan.id}`, { version: 2, doc });
    const even = { id: "a", name: "A", opens: "2026-10-05", due: "2026-10-09", even: true, tags: ["Step1"] };
    expect((await put({ deck: "Step 1", units: [{ ...even, due: undefined }] })).status).toBe(400);  // no window
    expect((await put({ deck: "Step 1", units: [{ ...even, due: "2026-10-05" }] })).status).toBe(400);  // one day
    expect((await put({ deck: "Step 1", units: [{ ...even, even: "yes" }] })).status).toBe(400);
    const days = [1, 1, 1, 1, 1, 0, 0];
    expect((await put({ deck: "Step 1", pace: { mode: "fast", days }, units: [] })).status).toBe(400);
    expect((await put({ deck: "Step 1", pace: { mode: "end", days: [0, 0, 0, 0, 0, 0, 0] }, units: [] })).status).toBe(400);
    expect((await put({ deck: "Step 1", pace: { mode: "end", days, cover: ["Step1"] }, units: [] })).status).toBe(400);  // tag: or deck:
    expect((await put({ deck: "Step 1", pace: { mode: "end", days, daily: 0 }, units: [] })).status).toBe(400);
    const ok = await put({ deck: "Step 1", pace: { mode: "daily", days, daily: 150, cover: ["tag:Step1", "tag:Step1", "deck:Step 1::Extras"] },
      units: [even, { ...even, id: "b", even: false }] });
    expect(ok.status).toBe(200);
    expect(ok.body.doc.pace).toEqual({ mode: "daily", days, daily: 150, cover: ["tag:Step1", "deck:Step 1::Extras"] });
    expect(ok.body.doc.units.map((u: any) => u.even)).toEqual([true, undefined]);
  });

  it("single cards go onto a date that exists, or a new one", async () => {
    const { dre, plan } = await authored();
    const onto = await dre.call("POST", `/plans/${plan.id}/cards`, { unit: "hf", cards: [["g9", 2]] });
    expect(onto.body.doc.units[0].cards).toEqual([["g9", 2]]);
    const fresh = await dre.call("POST", `/plans/${plan.id}/cards`, { opens: "2026-10-08", cards: [["g7", 0]] });
    const units = fresh.body.doc.units;
    expect(units.map((u: any) => u.opens)).toEqual(["2026-10-05", "2026-10-08", "2026-10-12"]);
    expect(units[1]).toMatchObject({ name: "Cards · 2026-10-08", cards: [["g7", 0]] });
    expect(fresh.body.version).toBe(4);
  });
});

describe("plans: following", () => {
  it("anyone with the code follows; the plan rides the day's first board", async () => {
    const { plan } = await authored();
    const maya = await person("maya");
    const f = await maya.call("POST", "/plans/follow", { code: plan.code });
    expect(f.status).toBe(200);
    expect(f.body.following).toEqual({ share: true, paused: false, sched: null, early: 0, progress: null });
    const light = await maya.call("GET", "/board");
    expect(light.body.plans).toBeUndefined();  // not on every refresh
    const first = await maya.call("GET", "/board?decks=1");
    expect(first.body.plans).toHaveLength(1);
    expect(first.body.plans[0]).toMatchObject({ id: plan.id, ownerName: "Dre", version: 2, share: true });
    expect(await maya.status("GET", `/plans/${plan.id}`)).toBe(200);  // a follower reads it without the code
  });

  it("a squad plan: only members follow it, and members are offered it", async () => {
    const { dre, plan } = await authored();
    const sq = (await dre.call("POST", "/squads", { name: "busm" })).body;
    const maya = await person("maya");
    const zed = await person("zed");
    await maya.call("POST", `/squads/${sq.id}/join`);
    expect(await dre.status("PUT", `/plans/${plan.id}`, { version: 2, audience: "squad", squad: sq.id })).toBe(200);
    expect(await zed.status("POST", "/plans/follow", { code: plan.code })).toBe(404);  // the code alone isn't enough
    const offers = (await maya.call("GET", "/board?decks=1")).body.planOffers;
    expect(offers).toEqual([{ id: plan.id, name: "Step 1", code: plan.code, squad: sq.id, ownerName: "Dre" }]);
    expect(await maya.status("POST", "/plans/follow", { code: plan.code })).toBe(200);
    expect((await maya.call("GET", "/board?decks=1")).body.planOffers).toEqual([]);
    expect(await dre.status("PUT", `/plans/${plan.id}`, { version: 3, squad: "someone-elses" })).toBe(400);
    // a plan's code shows outsiders nothing about the squad: an id isn't an invite
    const outsider = (await zed.call("GET", `/plans/peek?code=${plan.code}`));
    expect(outsider.status).toBe(404);  // a squad-only plan: not even a peek
    await dre.call("PUT", `/plans/${plan.id}`, { version: 3, audience: "code" });
    const peeked = await zed.call("GET", `/plans/peek?code=${plan.code}`);
    expect(peeked.status).toBe(200);
    expect(peeked.body.squad).toBeNull();
    expect((await maya.call("GET", `/plans/${plan.id}`)).body.squad).toBe(sq.id);  // a member still sees it
    // and a join that sends a code must send that squad's
    expect(await zed.status("POST", `/squads/${sq.id}/join`, { code: "WRONGCOD" })).toBe(403);
    expect(await zed.status("POST", `/squads/${sq.id}/join`, { code: sq.code })).toBe(200);
  });

  it("progress: stored only while sharing, only when it changed; the author sees counts", async () => {
    const { dre, plan } = await authored();
    const maya = await person("maya");
    const nia = await person("nia");
    await maya.call("POST", "/plans/follow", { code: plan.code });
    await nia.call("POST", "/plans/follow", { code: plan.code, share: false });
    const prog = { [plan.id]: { hf: [48, 48, 48], arr: [30, 10, 61] } };
    const s1 = await maya.call("POST", "/sync", { plans: prog });
    expect(s1.body.wrote.plans).toBe(true);
    expect((await maya.call("POST", "/sync", { plans: prog })).body.wrote.plans).toBe(false);
    expect((await nia.call("POST", "/sync", { plans: prog })).body.wrote.plans).toBe(false);  // not sharing
    const p = await dre.call("GET", `/plans/${plan.id}/progress`);
    expect(p.body).toEqual({ followers: 2, sharing: 1, units: { hf: { opened: 1, done: 1 }, arr: { opened: 1, done: 0 } } });
    const b = (await nia.call("GET", "/board?decks=1")).body.plans[0];
    expect(b).toMatchObject({ followers: 2, crewDone: { hf: 1 } });  // a follower sees counts, never names
    expect(await maya.status("GET", `/plans/${plan.id}/progress`)).toBe(403);
    expect(await maya.status("POST", "/sync", { plans: { [plan.id]: { hf: [49, 1, 48] } } })).toBe(400);
    // sharing off takes what was stored with it
    await maya.call("PATCH", `/plans/${plan.id}/follow`, { share: false });
    expect((await dre.call("GET", `/plans/${plan.id}/progress`)).body.sharing).toBe(0);
  });

  it("stop following, or the author deletes: nothing left behind", async () => {
    const { dre, plan } = await authored();
    const maya = await person("maya");
    await maya.call("POST", "/plans/follow", { code: plan.code });
    expect(await maya.status("DELETE", `/plans/${plan.id}/follow`)).toBe(200);
    expect((await maya.call("GET", "/board?decks=1")).body.plans).toEqual([]);
    await maya.call("POST", "/plans/follow", { code: plan.code });
    expect(await dre.status("DELETE", `/plans/${plan.id}`)).toBe(200);
    expect((await maya.call("GET", "/board?decks=1")).body.plans).toEqual([]);
    expect(await db().prepare("SELECT COUNT(*) AS n FROM plan_follows").first("n")).toBe(0);
  });

  it("deleting an account takes its plans and follows", async () => {
    const { dre, plan } = await authored();
    const maya = await person("maya");
    await maya.call("POST", "/plans/follow", { code: plan.code });
    expect(await dre.status("DELETE", "/account")).toBe(200);
    expect(await db().prepare("SELECT COUNT(*) AS n FROM plans").first("n")).toBe(0);
    expect(await db().prepare("SELECT COUNT(*) AS n FROM plan_follows").first("n")).toBe(0);
  });
});

describe("plans: the deck's tree and the site's sign-in", () => {
  it("a tree is names and counts, one per deck, rewritten only when it changed", async () => {
    const dre = await person("dre");
    const tree = { deck: "Step 1", tags: [["Step1::Cardio", 312]], decks: [["Step 1::Extras", 96]] };
    expect(await dre.status("PUT", "/plans/trees", tree)).toBe(200);
    expect(await dre.status("PUT", "/plans/trees", tree)).toBe(200);
    expect(await dre.status("PUT", "/plans/trees", { deck: "Step 1", tags: [["Step1::Cardio", "312 cards"]] })).toBe(400);
    const got = await dre.call("GET", "/plans/trees?deck=Step%201");
    expect(got.body.trees).toEqual([expect.objectContaining({ deck: "Step 1", tags: [["Step1::Cardio", 312]] })]);
    const list = await dre.call("GET", "/plans/trees");
    expect(list.body.trees).toEqual([{ deck: "Step 1", at: expect.any(Number) }]);  // which decks, not the trees
  });

  it("3.3: a nested tree, each name once, deep tags and a big deck", async () => {
    const dre = await person("dre");
    const deep = ["#AK", 9000, [["#Bootcamp", 3000, [["Cardiology", 900, [["02_Anatomy", 120, [["04_Penetrating_Cardiac_Trauma", 7]]]]]]]]];
    expect(await dre.status("PUT", "/plans/trees", { deck: "AnKing", v: 2, tags: [deep], decks: [] })).toBe(200);
    const got = await dre.call("GET", "/plans/trees?deck=AnKing");
    expect(got.body.trees[0].v).toBe(2);
    expect(got.body.trees[0].tags).toEqual([deep]);
    expect(await dre.status("PUT", "/plans/trees", { deck: "AnKing", v: 2, tags: [["A::B", 1]] })).toBe(400);  // a name, not a path
    expect(await dre.status("PUT", "/plans/trees", { deck: "AnKing", v: 2, tags: [["x".repeat(150), 1, [["y".repeat(60), 1]]]] })).toBe(400);  // path over 200
    // past the usual 512 KB body: a big deck's tags still fit
    const many = Array.from({ length: 30000 }, (_, i) => [`Lecture_${String(i).padStart(5, "0")}_Some_Topic`, 3]);
    expect(await dre.status("PUT", "/plans/trees", { deck: "Big", v: 2, tags: [["Big", 90000, many]] })).toBe(200);
  });

  it("a one-time link signs the site in once, with a same-site cookie", async () => {
    const dre = await person("dre");
    const link = await dre.call("POST", "/auth/link");
    expect(link.body.expiresIn).toBe(300);
    const r = await api("POST", "/auth/link/redeem", { body: { token: link.body.token }, headers: SITE });
    expect(r.status).toBe(200);
    const cookie = r.headers.get("set-cookie") || "";
    expect(cookie).toMatch(/^dc_session=[A-Za-z0-9_-]{43}; Path=\/; HttpOnly; Secure; SameSite=Strict/);
    expect((await api("POST", "/auth/link/redeem", { body: { token: link.body.token }, headers: SITE })).status).toBe(401);  // once

    // the cookie reads; a change needs the header a cross-site form can't send
    const session = cookie.split(";")[0];
    const { env } = await import("cloudflare:workers");
    const worker = (await import("../src/index")).default;
    const call = async (method: string, path: string, headers: Record<string, string> = {}, body?: unknown) =>
      (await worker.fetch(new Request(`https://duecrew.com/api${path}`.replace("/api", ""), {
        method, headers: { cookie: session, "content-type": "application/json", ...headers },
        body: body === undefined ? undefined : JSON.stringify(body),
      }), { ...env } as any)).status;
    expect(await call("GET", "/plans/mine")).toBe(200);
    expect(await call("POST", "/plans", {}, { name: "X", deck: "D" })).toBe(403);
    expect(await call("POST", "/plans", { "x-due-crew": "1" }, { name: "X", deck: "D" })).toBe(200);
  });

  it("the site signs in by code with a cookie, and signs out", async () => {
    const { mailbox } = await import("./helpers");
    const box = mailbox();
    await api("POST", "/auth/code", { body: { email: "maya@example.com" } });
    const v = await api("POST", "/api/auth/verify", { body: { email: "maya@example.com", code: box.code("maya@example.com"), web: true }, headers: SITE });
    expect(v.status).toBe(200);
    expect(v.body.token).toBeUndefined();  // never in page script
    const cookie = (v.headers.get("set-cookie") || "").split(";")[0];
    expect(cookie).toMatch(/^dc_session=/);
    const { env } = await import("cloudflare:workers");
    const worker = (await import("../src/index")).default;
    const go = (method: string, path: string) => worker.fetch(new Request(`https://duecrew.com${path}`,
      { method, headers: { cookie, "x-due-crew": "1" } }), { ...env } as any);
    expect((await go("GET", "/api/squads/mine")).status).toBe(200);
    const out = await go("POST", "/api/auth/signout");
    expect(out.headers.get("set-cookie")).toMatch(/^dc_session=; .*Max-Age=0/);
    expect((await go("GET", "/api/plans/mine")).status).toBe(401);
  });

  it("the endpoints that set a cookie refuse a request another site could make", async () => {
    const dre = await person("dre");
    const link = await dre.call("POST", "/auth/link");
    expect((await api("POST", "/auth/link/redeem", { body: { token: link.body.token } })).status).toBe(403);
    expect((await api("POST", "/auth/link/redeem", { body: { token: link.body.token }, headers: SITE })).status).toBe(200);
  });

  it("an expired link doesn't work", async () => {
    const dre = await person("dre");
    const link = await dre.call("POST", "/auth/link");
    await db().prepare("UPDATE login_links SET expires_at = 0").run();
    expect((await api("POST", "/auth/link/redeem", { body: { token: link.body.token }, headers: SITE })).status).toBe(401);
  });
});

describe("limits the audit asked for", () => {
  it("a body past the limit is refused even with no content-length (streamed)", async () => {
    const dre = await person("dre");
    const { env } = await import("cloudflare:workers");
    const worker = (await import("../src/index")).default;
    const big = new ReadableStream({
      start(c) { for (let i = 0; i < 90; i++) c.enqueue(new TextEncoder().encode("x".repeat(20_000))); c.close(); },  // 1.8 MB: past even a tree's 1.5 MB
    });
    const res = await worker.fetch(new Request("https://api.duecrew.com/plans/trees", {
      method: "PUT", body: big, headers: { authorization: `Bearer ${dre.token}` }, duplex: "half",
    } as any), { ...env } as any);
    expect(res.status).toBe(413);
  });

  it("PUT /friends only restores once, before the account's first 3.x sync", async () => {
    const nia = await person("nia");
    await person("sam");
    expect((await nia.call("PUT", "/friends", { ids: ["sam"] })).body.added).toEqual(["sam"]);
    await nia.call("POST", "/sync", { profile: { name: "Nia", clientVersion: "3.0.1" } });
    await nia.call("DELETE", "/friends/sam");
    expect((await nia.call("PUT", "/friends", { ids: ["sam"] })).body.added).toEqual([]);
    expect(await db().prepare("SELECT COUNT(*) AS n FROM friends WHERE owner = 'nia'").first("n")).toBe(0);
  });

  it("a squad plan closes to someone who leaves the squad, follow or not", async () => {
    const { dre, plan } = await authored();
    const sq = (await dre.call("POST", "/squads", { name: "busm" })).body;
    const maya = await person("maya");
    await maya.call("POST", `/squads/${sq.id}/join`, { code: sq.code });
    await dre.call("PUT", `/plans/${plan.id}`, { version: 2, audience: "squad", squad: sq.id });
    await maya.call("POST", "/plans/follow", { code: plan.code });
    expect((await maya.call("GET", "/board?decks=1")).body.plans).toHaveLength(1);
    await dre.call("DELETE", `/squads/${sq.id}/members/maya`);
    expect((await maya.call("GET", "/board?decks=1")).body.plans).toEqual([]);
    expect(await maya.status("GET", `/plans/${plan.id}`)).toBe(404);
  });
});
