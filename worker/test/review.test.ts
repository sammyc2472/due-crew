// The UI review's server side: a plan's link before signing in (C1), a
// phone emailing itself the link (C2), and a code looked up before it's
// added (H1).
import { describe, expect, it } from "vitest";
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
