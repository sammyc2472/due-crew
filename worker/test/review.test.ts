// The UI review's server side: a plan's link before signing in (C1), a
// phone emailing itself the link (C2), and a code looked up before it's
// added (H1).
import { env } from "cloudflare:test";
import { describe, expect, it } from "vitest";
import worker from "../src/index";
import { api, befriend, mailbox, person } from "./helpers";

const SITE = { "x-due-crew": "1" };

async function plan() {
  const priya = await person("priya", "Priya");
  const made = await priya.call("POST", "/plans", { name: "MS2 Cardio block", deck: "Step 1", line: "One lecture a day" });
  const put = await priya.call("PUT", `/plans/${made.body.id}`, { version: 1, doc: { deck: "Step 1", units: [
    { id: "a", name: "Lecture 12", opens: "2026-10-05", tags: ["C::12"], n: 84 },
    { id: "b", name: "Lecture 13", opens: "2026-10-06", due: "2026-10-08", tags: ["C::13"], n: 61, cards: [["g1", 0]] },
  ] } });
  return { priya, p: put.body };
}

describe("C1: a plan's link shows the plan before signing in", () => {
  it("name, whose, the line, followers and each date's day and count; a squad's plan shows nothing", async () => {
    const { priya, p } = await plan();
    const r = await api("GET", `/plans/public?code=${p.code.toLowerCase()}`);
    expect(r.status).toBe(200);
    expect(r.body).toEqual({ name: "MS2 Cardio block", ownerName: "Priya", line: "One lecture a day", deck: "Step 1", followers: 0,
      v: p.version, events: [],
      units: [{ name: "Lecture 12", opens: "2026-10-05", n: 84 }, { name: "Lecture 13", opens: "2026-10-06", due: "2026-10-08", n: 62 }] });
    expect(JSON.stringify(r.body)).not.toContain("C::12");  // days and counts, not what's in them
    expect((await api("GET", "/plans/public?code=NOPE2345")).status).toBe(404);
    const sq = await priya.call("POST", "/squads", { name: "busm" });
    await priya.call("PUT", `/plans/${p.id}`, { version: p.version, audience: "squad", squad: sq.body.id });
    expect((await api("GET", `/plans/public?code=${p.code}`)).status).toBe(404);
  });
});

describe("C2: a phone sends itself the link", () => {
  it("one fixed message with the page's link, only from the site, only to a plan's page or home, a few a day", async () => {
    const box = mailbox();
    expect((await api("POST", "/links/email", { body: { email: "maya@school.edu", path: "/p/7KQ4MX2D" } })).status).toBe(403);
    const ok = await api("POST", "/links/email", { body: { email: "Maya@School.edu", path: "/p/7KQ4MX2D" }, headers: SITE });
    expect(ok.status).toBe(200);
    expect(box.sent.at(-1)).toMatchObject({ to: "maya@school.edu", subject: "Your Due Crew link" });
    expect(box.sent.at(-1)!.text).toContain("https://duecrew.com/p/7KQ4MX2D");
    for (const path of ["https://evil.example", "/p/7KQ4MX2D?x=1", "//evil", "/home"]) {
      expect((await api("POST", "/links/email", { body: { email: "maya@school.edu", path }, headers: SITE })).status).toBe(400);
    }
    expect((await api("POST", "/links/email", { body: { email: "maya@school.edu", path: "/" }, headers: SITE, ip: "198.51.100.9" })).status).toBe(200);
    expect((await api("POST", "/links/email", { body: { email: "maya@school.edu", path: "/" }, headers: SITE, ip: "198.51.100.10" })).status).toBe(200);
    expect((await api("POST", "/links/email", { body: { email: "maya@school.edu", path: "/" }, headers: SITE, ip: "198.51.100.11" })).status).toBe(429);  // 3 a day to one inbox
  });
});

describe("H1: a code, looked up before it's added", () => {
  it("whose it is, whether it's mine, whether I added them; nothing is added", async () => {
    const maya = await person("maya", "Maya");
    const dre = await person("dre", "Dre");
    const code = (await dre.call("POST", "/codes")).body.code;
    const r = await maya.call("GET", `/codes/${code.toLowerCase()}`);
    expect(r.body).toEqual({ uid: "dre", name: "Dre", emoji: "", mine: false, added: false });
    expect((await maya.call("GET", "/friends")).body.friends).toEqual([]);  // a look-up adds nobody
    await befriend(maya, dre);
    expect((await maya.call("GET", `/codes/${code}`)).body.added).toBe(true);
    expect((await dre.call("GET", `/codes/${code}`)).body.mine).toBe(true);
    expect(await maya.status("GET", "/codes/ZZZZZZ")).toBe(404);
  });
});

describe("E1: note and card ids pasted onto a date", () => {
  it("whole positive numbers, deduped, up to 5,000 a date; the author's Anki counts them; the public page counts them", async () => {
    const { priya, p } = await plan();
    const base = p.doc.units;
    const put = (units: unknown[], version: number) => priya.call("PUT", `/plans/${p.id}`, { version, doc: { deck: "Step 1", units } });
    const ok = await put([{ ...base[0], nids: [1628174531284, 1628174531284, 1628174531301], cids: [] }, base[1]], p.version);
    expect(ok.status).toBe(200);
    expect(ok.body.doc.units[0].nids).toEqual([1628174531284, 1628174531301]);
    expect(ok.body.doc.units[0].cids).toBeUndefined();
    for (const bad of [[0], [-3], [1.5], ["123"], Array.from({ length: 5001 }, (_, i) => i + 1)]) {
      expect((await put([{ ...base[0], nids: bad }, base[1]], ok.body.version)).status).toBe(400);
    }
    // the author's Anki: "#ids" is how many cards they found
    const ids = await priya.call("PUT", `/plans/${p.id}/ids`, { units: {}, counts: { [base[0].id]: { "#ids": 3 } } });
    expect(ids.status).toBe(200);
    const after = await priya.call("GET", `/plans/${p.id}`);
    expect(after.body.doc.units[0].idn).toBe(3);
    const pub = await api("GET", `/plans/public?code=${p.code}`);
    expect(pub.body.units[0].n).toBe(84 + 3);
    // the lean copy the author's Anki counts from carries them
    const board = await priya.call("GET", "/board?decks=1");
    expect(board.body.authored[0].doc.units.find((u: { id: string }) => u.id === base[0].id).nids).toEqual([1628174531284, 1628174531301]);
  });
});

describe("3.6.5: picks that work in anyone's copy", () => {
  it("notes by guid; the author's Anki turns pasted ids into card refs, kept only while those ids hold", async () => {
    const { priya, p } = await plan();
    const base = p.doc.units;
    const put = (units: unknown[], version: number) => priya.call("PUT", `/plans/${p.id}`, { version, doc: { deck: "Step 1", units } });
    const ok = await put([{ ...base[0], nids: [11, 12], notes: ["gA", "gA", "gB"], idr: [["forged", 0]] }, base[1]], p.version);
    expect(ok.status).toBe(200);
    expect(ok.body.doc.units[0].notes).toEqual(["gA", "gB"]);
    expect(ok.body.doc.units[0].idr).toBeUndefined();  // only the author's Anki sets them
    for (const bad of [[""], [5], ["x".repeat(41)], Array.from({ length: 5001 }, (_, i) => `g${i}`)]) {
      expect((await put([{ ...base[0], notes: bad }, base[1]], ok.body.version)).status).toBe(400);
    }
    const uid = base[0].id;
    const refs = [["gN", 0], ["gN", 1]];
    expect((await priya.call("PUT", `/plans/${p.id}/ids`, { units: {}, refs: { [uid]: [[11, 12], [], refs] } })).status).toBe(200);
    let doc = (await priya.call("GET", `/plans/${p.id}`)).body;
    expect(doc.doc.units[0].idr).toEqual(refs);
    // refs worked out from other ids than the date has now: ignored
    await priya.call("PUT", `/plans/${p.id}/ids`, { units: {}, refs: { [uid]: [[99], [], [["gZ", 0]]] } });
    doc = (await priya.call("GET", `/plans/${p.id}`)).body;
    expect(doc.doc.units[0].idr).toEqual(refs);
    expect((await priya.call("PUT", `/plans/${p.id}/ids`, { units: {}, refs: { [uid]: "x" } })).status).toBe(400);
    // a site save keeps them while the ids hold, and drops them when they change
    const kept = await put([{ ...doc.doc.units[0], idr: [["forged", 0]] }, base[1]], doc.version);
    expect(kept.body.doc.units[0].idr).toEqual(refs);
    const { idr: _drop, ...without } = kept.body.doc.units[0];  // the builder leaves them out of a save
    const bare = await put([without, base[1]], kept.body.version);
    expect(bare.body.doc.units[0].idr).toEqual(refs);
    // P1: what each date opens, from the author's Anki, kept like idr
    expect((await priya.call("PUT", `/plans/${p.id}/ids`, { units: {}, counts: { [uid]: { "#pn": [80, 3, 1] } } })).status).toBe(200);
    const counted = (await priya.call("GET", `/plans/${p.id}`)).body;
    expect(counted.doc.units[0].pn).toEqual([80, 3, 1]);
    const keptPn = await put([{ ...counted.doc.units[0], pn: [9, 9, 9] }, base[1]], counted.version);
    expect(keptPn.body.doc.units[0].pn).toEqual([80, 3, 1]);
    const moved = await put([{ ...keptPn.body.doc.units[0], nids: [11] }, base[1]], keptPn.body.version);
    expect(moved.body.doc.units[0].idr).toBeUndefined();
    expect(moved.body.doc.units[0].pn).toBeUndefined();
    // the lean copy carries the notes, so the author's Anki can count them
    const board = await priya.call("GET", "/board?decks=1");
    expect(board.body.authored[0].doc.units.find((u: { id: string }) => u.id === uid).notes).toEqual(["gA", "gB"]);
  });
});

describe("F1: events, and the dates that prep for them", () => {
  it("named days a date can be for; a for whose event went is dropped; the calendar feed shows them", async () => {
    const { priya, p } = await plan();
    const [a, b] = p.doc.units;
    const events = [{ id: "quiz1", day: "2026-10-09", name: "Micro quiz" }];
    const ok = await priya.call("PUT", `/plans/${p.id}`, { version: p.version, doc: { deck: "Step 1", events, units: [{ ...a, for: "quiz1" }, { ...b, for: "quiz1" }] } });
    expect(ok.status).toBe(200);
    expect(ok.body.doc.events).toEqual(events);
    expect(ok.body.doc.units.map((u: { for?: string }) => u.for)).toEqual(["quiz1", "quiz1"]);
    const gone = await priya.call("PUT", `/plans/${p.id}`, { version: ok.body.version, doc: { deck: "Step 1", units: [{ ...a, for: "quiz1" }, b] } });
    expect(gone.status).toBe(200);
    expect(gone.body.doc.units[0].for).toBeUndefined();
    for (const bad of [[{ id: "x", day: "soon", name: "Quiz" }], [{ id: "x", day: "2026-10-09", name: "" }],
                       [{ id: "x", day: "2026-10-09", name: "A" }, { id: "x", day: "2026-10-10", name: "B" }]]) {
      expect((await priya.call("PUT", `/plans/${p.id}`, { version: gone.body.version, doc: { deck: "Step 1", events: bad, units: [a, b] } })).status).toBe(400);
    }
    const again = await priya.call("PUT", `/plans/${p.id}`, { version: gone.body.version, doc: { deck: "Step 1", events, units: [{ ...a, for: "quiz1" }, { ...b, for: "quiz1" }] } });
    expect(again.status).toBe(200);
    const feed = await worker.fetch(new Request(`https://api.duecrew.com/plans/ics?code=${p.code}`), { ...env } as any);
    expect(await feed.text()).toContain("SUMMARY:Micro quiz · 2 days of prep");
    // 3.7.8: days, not dates: a third date on a's day is still 2 days of prep
    const three = await priya.call("PUT", `/plans/${p.id}`, { version: again.body.version, doc: { deck: "Step 1", events,
      units: [{ ...a, for: "quiz1" }, { ...b, for: "quiz1" }, { ...a, id: "samedayx", name: "Same day", for: "quiz1" }] } });
    expect(three.status).toBe(200);
    const feed2 = await worker.fetch(new Request(`https://api.duecrew.com/plans/ics?code=${p.code}`), { ...env } as any);
    expect(await feed2.text()).toContain("SUMMARY:Micro quiz · 2 days of prep");
  });
});

describe("G3, G4: a follower's own days", () => {
  it("shift, a pause's days and skips are mine, kept on the server, and come back on the board and the page", async () => {
    const { p } = await plan();
    const maya = await person("maya", "Maya");
    expect((await maya.call("POST", "/plans/follow", { code: p.code })).status).toBe(200);
    const [a] = p.doc.units;
    const ok = await maya.call("PATCH", `/plans/${p.id}/follow`, { paused: true, since: "2026-10-12", until: "2026-10-18", shift: 5, skipped: [a.id, a.id] });
    expect(ok.status).toBe(200);
    expect(ok.body).toMatchObject({ paused: true, shift: 5, until: "2026-10-18", since: "2026-10-12", skipped: [a.id] });
    for (const bad of [{ shift: -1 }, { shift: 400 }, { until: "soon" }, { skipped: ["NOT OK"] }, { skipped: "x" }, { other: 1 }]) {
      expect((await maya.call("PATCH", `/plans/${p.id}/follow`, bad)).status).toBe(400);
    }
    const board = await maya.call("GET", "/board?decks=1");
    expect(board.body.plans[0]).toMatchObject({ shift: 5, until: "2026-10-18", since: "2026-10-12", skipped: [a.id] });
    const page = await maya.call("GET", `/plans/${p.id}`);
    expect(page.body.following).toMatchObject({ shift: 5, skipped: [a.id] });
    const back = await maya.call("PATCH", `/plans/${p.id}/follow`, { paused: false, until: null, since: null, skipped: [] });
    expect(back.body).toMatchObject({ paused: false, until: null, since: null, skipped: [], shift: 5 });
  });

  it("3.7.6: one date moved later is mine; Reset to default is one PATCH of everything", async () => {
    const { p } = await plan();
    const maya = await person("maya", "Maya");
    await maya.call("POST", "/plans/follow", { code: p.code });
    const [a] = p.doc.units;
    const m = await maya.call("PATCH", `/plans/${p.id}/follow`, { moved: { [a.id]: 3 }, shift: 2 });
    expect(m.body).toMatchObject({ moved: { [a.id]: 3 }, shift: 2 });
    for (const bad of [{ moved: { [a.id]: 0 } }, { moved: { [a.id]: 400 } }, { moved: { "NOT OK": 1 } }, { moved: [1] }, { moved: null }]) {
      expect((await maya.call("PATCH", `/plans/${p.id}/follow`, bad)).status).toBe(400);
    }
    expect((await maya.call("GET", "/board?decks=1")).body.plans[0].moved).toEqual({ [a.id]: 3 });
    expect((await maya.call("GET", `/plans/${p.id}`)).body.following.moved).toEqual({ [a.id]: 3 });
    expect((await (await import("./helpers")).db().prepare("SELECT version FROM plans WHERE id = ?").bind(p.id).first("version")))
      .toBe(p.version);  // the plan itself never changes
    const reset = await maya.call("PATCH", `/plans/${p.id}/follow`,
      { shift: 0, skipped: [], moved: {}, paused: false, until: null, since: null });
    expect(reset.body).toMatchObject({ shift: 0, skipped: [], moved: {}, paused: false, until: null, since: null });
  });
});
