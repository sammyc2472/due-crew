import { describe, expect, it } from "vitest";
import { api, db, person } from "./helpers";

// 3.5, B: the plan library, and A's public peek additions

const UNITS = [
  { id: "hf", name: "Heart failure", opens: "2026-10-05", due: "2026-10-07", tags: ["Step1::Cardio::HF"], n: 120 },
  { id: "arr", name: "Arrhythmia", opens: "2026-10-12", tags: ["Step1::Cardio::Arr"], n: 80, for: "quiz" },
];
const EVENTS = [{ id: "quiz", day: "2026-10-16", name: "Cardio quiz" }];

async function plan(who: Awaited<ReturnType<typeof person>>, name = "Cardio block", deck = "AnKing Step 1", units: unknown[] = UNITS) {
  const made = await who.call("POST", "/plans", { name, deck });
  const extra = units === UNITS ? { events: EVENTS, reviews: [{ day: "2026-10-15", from: "hf", to: "arr" }] } : {};
  const put = await who.call("PUT", `/plans/${made.body.id}`, { version: 1, doc: { deck, units, ...extra } });
  expect(put.status).toBe(200);
  return put.body;
}

const asAdmin = (who: { token: string }, method: string, path: string, body?: unknown) =>
  api(method, path, { token: who.token, body, env: { ADMIN_UIDS: "sam" } as any });

describe("the library (3.5, B)", () => {
  it("the owner lists a code plan with dates; anyone signed in finds it, with its code", async () => {
    const dre = await person("dre");
    const p = await plan(dre);
    expect(p.listed).toBe(0);
    expect(p.library).toBe(false);
    const maya = await person("maya");
    expect(await maya.status("PUT", `/plans/${p.id}/listed`, { listed: true })).toBe(403);  // the owner's call
    expect(await maya.status("GET", `/plans/${p.id}`)).toBe(404);  // not listed: no code, no plan
    const on = await dre.call("PUT", `/plans/${p.id}/listed`, { listed: true });
    expect(on.status).toBe(200);
    expect(on.body).toMatchObject({ listed: 1, library: true });
    const lib = await maya.call("GET", "/library");
    expect(lib.status).toBe(200);
    expect(lib.body.plans).toHaveLength(1);
    expect(lib.body.plans[0]).toMatchObject({ id: p.id, code: p.code, name: "Cardio block", ownerName: "Dre", followers: 0, mine: false,
      deck: "AnKing Step 1", dates: 2, from: "2026-10-05", to: "2026-10-12", days: 8, n: 200, perDay: 25, reviews: 1, events: 1, ids: 0 });
    expect(lib.body.decks).toEqual([["AnKing Step 1", 1]]);
    // a listed plan reads like one shared by code, without the code in hand
    const read = await maya.call("GET", `/plans/${p.id}`);
    expect(read.status).toBe(200);
    expect(read.body).toMatchObject({ role: "reader", code: p.code, library: true });
    expect(read.body.listed).toBeUndefined();  // the authors' own
    expect(await (await person("zed")).status("GET", "/library")).toBe(200);
    expect((await api("GET", "/library")).status).toBe(401);
  });

  it("in the library, only its authors write notes; a stranger's earlier ones reach nobody else", async () => {
    const dre = await person("dre");
    const p = await plan(dre);
    const kai = await person("kai");  // a co-author
    await dre.call("PUT", `/friends/kai`); await kai.call("PUT", `/friends/dre`);
    expect(await dre.status("POST", `/plans/${p.id}/editors`, { uid: "kai" })).toBe(200);
    const zed = await person("zed");  // a stranger who follows from the code, before it's listed
    await zed.call("POST", "/plans/follow", { code: p.code });
    expect(await zed.status("POST", `/plans/${p.id}/notes`, { day: "2026-10-05", text: "early note" })).toBe(200);
    await dre.call("PUT", `/plans/${p.id}/listed`, { listed: true });
    const maya = await person("maya");  // follows it from the library
    expect((await maya.call("POST", "/plans/follow", { code: p.code })).status).toBe(200);
    const no = await maya.call("POST", `/plans/${p.id}/notes`, { day: "2026-10-05", text: "buy essays at spam.example" });
    expect([no.status, no.body.error]).toEqual([403, "authors_only"]);
    expect(await dre.status("POST", `/plans/${p.id}/notes`, { day: "2026-10-05", text: "quiz is closed-book" })).toBe(200);
    expect(await kai.status("POST", `/plans/${p.id}/notes`, { day: "2026-10-06", text: "lab day" })).toBe(200);
    const texts = async (who: typeof dre) => (await who.call("GET", `/plans/${p.id}/notes`)).body.notes.map((n: any) => n.text).sort();
    expect(await texts(maya)).toEqual(["lab day", "quiz is closed-book"]);
    expect(await texts(zed)).toEqual(["early note", "lab day", "quiz is closed-book"]);  // my own stays mine
    expect(await texts(dre)).toEqual(["lab day", "quiz is closed-book"]);
    const feed = (await maya.call("GET", "/board?keep=1&feed=1")).body.feed.filter((x: any) => x.kind === "note").map((x: any) => x.text).sort();
    expect(feed).toEqual(["lab day", "quiz is closed-book"]);
    // out of the library, it's a code plan again: followers write notes
    await dre.call("PUT", `/plans/${p.id}/listed`, { listed: false });
    expect(await maya.status("POST", `/plans/${p.id}/notes`, { day: "2026-10-05", text: "thanks" })).toBe(200);
    expect(await texts(dre)).toContain("early note");
  });

  it("refuses a squad plan, a plan with no dates, and a bad body; taking it out is the owner's", async () => {
    const dre = await person("dre");
    const empty = await dre.call("POST", "/plans", { name: "Empty", deck: "D" });
    expect((await dre.call("PUT", `/plans/${empty.body.id}/listed`, { listed: true })).body.error).toBe("no_dates");
    const p = await plan(dre);
    expect(await dre.status("PUT", `/plans/${p.id}/listed`, { listed: "yes" })).toBe(400);
    expect(await dre.status("PUT", `/plans/${p.id}/listed`, { listed: true, extra: 1 })).toBe(400);
    await dre.call("PUT", `/plans/${p.id}/listed`, { listed: true });
    const off = await dre.call("PUT", `/plans/${p.id}/listed`, { listed: false });
    expect(off.body.listed).toBe(0);
    expect((await dre.call("GET", "/library")).body.plans).toEqual([]);
  });

  it("a plan made for one squad leaves the library", async () => {
    const dre = await person("dre");
    const p = await plan(dre);
    await dre.call("PUT", `/plans/${p.id}/listed`, { listed: true });
    const sq = await dre.call("POST", "/squads", { name: "Block 2" });
    expect(sq.status).toBe(200);
    const moved = await dre.call("PUT", `/plans/${p.id}`, { version: p.version, audience: "squad", squad: sq.body.id });
    expect(moved.status).toBe(200);
    expect(moved.body.listed).toBe(0);
    expect((await dre.call("GET", "/library")).body.plans).toEqual([]);
  });

  it("the card follows the plan's saves", async () => {
    const dre = await person("dre");
    const p = await plan(dre);
    await dre.call("PUT", `/plans/${p.id}/listed`, { listed: true });
    const more = [...UNITS, { id: "vd", name: "Valves", opens: "2026-11-02", tags: ["Step1::Cardio::Valves"], n: 40 }];
    const put = await dre.call("PUT", `/plans/${p.id}`, { version: p.version, doc: { deck: "AnKing Step 1", units: more } });
    expect(put.status).toBe(200);
    const card = (await dre.call("GET", "/library")).body.plans[0];
    expect(card).toMatchObject({ dates: 3, to: "2026-11-02", n: 240, events: 0, reviews: 0 });
    const cards = await dre.call("POST", `/plans/${p.id}/cards`, { unit: "vd", cards: [["g1", 0], ["g2", 0]] });
    expect(cards.status).toBe(200);
    expect((await dre.call("GET", "/library")).body.plans[0].n).toBe(242);
  });

  it("filters by deck, length and words; newest first, never by followers", async () => {
    const dre = await person("dre");
    const jo = await person("jo", "Jordan");
    const a = await plan(dre, "Cardio block", "AnKing Step 1");
    const long = Array.from({ length: 12 }, (_, i) => ({ id: `w${i}`, name: `Week ${i + 1}`, opens: `2026-${String(10 + Math.floor(i / 4)).padStart(2, "0")}-${String(1 + (i % 4) * 7).padStart(2, "0")}`, tags: [`T::${i}`], n: 10 }));
    const b = await plan(jo, "Step 1 in 12 weeks", "AnKing Step 1", long);
    const c = await plan(jo, "Bugs first", "Sketchy Micro", [{ id: "m1", name: "Staph", opens: "2026-10-05", tags: ["Micro::Staph"], n: 30 }]);
    for (const [who, p] of [[dre, a], [jo, b], [jo, c]] as const) {
      await (who as any).call("PUT", `/plans/${(p as any).id}/listed`, { listed: true });
      await db().prepare("UPDATE plans SET listed_at = ? WHERE id = ?").bind({ [a.id]: 100, [b.id]: 200, [c.id]: 300 }[(p as any).id], (p as any).id).run();
    }
    // the oldest has the most followers: the order doesn't care
    for (const f of ["f1", "f2", "f3"]) await (await person(f)).call("POST", "/plans/follow", { code: a.code });
    const maya = await person("maya");
    const names = async (q: string) => (await maya.call("GET", `/library${q}`)).body.plans.map((x: any) => x.name);
    expect(await names("")).toEqual(["Bugs first", "Step 1 in 12 weeks", "Cardio block"]);
    expect(await names("?deck=AnKing%20Step%201")).toEqual(["Step 1 in 12 weeks", "Cardio block"]);
    expect(await names("?len=short")).toEqual(["Bugs first", "Cardio block"]);
    expect(await names("?len=mid")).toEqual(["Step 1 in 12 weeks"]);
    expect(await names("?q=step")).toEqual(["Step 1 in 12 weeks", "Cardio block"]);  // a name match first, then the deck's
    expect(await names("?q=100%25")).toEqual([]);  // % is a letter here, not a wildcard
    expect((await maya.call("GET", "/library")).body.decks).toEqual([["AnKing Step 1", 2], ["Sketchy Micro", 1]]);
    expect((await maya.call("GET", "/library")).body.plans[2].followers).toBe(3);
  });

  it("copy: my own plan from a listed one, moved to my start, crediting the original", async () => {
    const dre = await person("dre");
    const p = await plan(dre);
    const maya = await person("maya");
    expect(await maya.status("POST", `/plans/${p.id}/copy`, { start: "2027-01-04" })).toBe(404);  // not listed
    await (await person("fol")).call("POST", "/plans/follow", { code: p.code });
    await dre.call("POST", `/plans/${p.id}/notes`, { day: "2026-10-05", text: "lab day" });
    await dre.call("PUT", `/plans/${p.id}/listed`, { listed: true });
    expect(await maya.status("POST", `/plans/${p.id}/copy`, { start: "soon" })).toBe(400);
    const cp = await maya.call("POST", `/plans/${p.id}/copy`, { start: "2027-01-04" });
    expect(cp.status).toBe(200);
    expect(cp.body).toMatchObject({ role: "owner", name: "Cardio block", followers: 0, listed: 0, library: false,
      basedOn: { id: p.id, name: "Cardio block", owner: "Dre" } });
    expect(cp.body.id).not.toBe(p.id);
    expect(cp.body.code).not.toBe(p.code);
    const d = cp.body.doc;
    expect(d.units.map((u: any) => [u.opens, u.due])).toEqual([["2027-01-04", "2027-01-06"], ["2027-01-11", undefined]]);
    expect(d.events).toEqual([{ id: "quiz", day: "2027-01-15", name: "Cardio quiz" }]);
    expect(d.reviews).toEqual([{ day: "2027-01-14", from: "hf", to: "arr" }]);
    expect(d.units[1].for).toBe("quiz");
    expect((await maya.call("GET", `/plans/${cp.body.id}/notes`)).body.notes).toEqual([]);
    expect((await maya.call("GET", `/plans/${cp.body.id}/log`)).body.log[0].summary).toBe("copied from Cardio block");
    // the original is untouched
    expect((await dre.call("GET", `/plans/${p.id}`)).body.doc.units[0].opens).toBe("2026-10-05");
    // an author copies their own, even unlisted: "(copy)", no credit
    await dre.call("PUT", `/plans/${p.id}/listed`, { listed: false });
    const own = await dre.call("POST", `/plans/${p.id}/copy`, { start: "2026-10-05" });
    expect(own.body).toMatchObject({ name: "Cardio block (copy)" });
    expect(own.body.basedOn).toBeUndefined();
  });

  it("the admin takes a plan out; its author reads why and can't list it again until it's put back", async () => {
    const dre = await person("dre");
    const sam = await person("sam");
    const p = await plan(dre);
    await dre.call("PUT", `/plans/${p.id}/listed`, { listed: true });
    expect((await dre.call("POST", `/admin/library/${p.id}`, { note: "x" })).status).toBe(404);  // not the admin
    expect((await asAdmin(sam, "POST", `/admin/library/${p.id}`, {})).status).toBe(400);
    expect((await asAdmin(sam, "POST", `/admin/library/${p.id}`, { note: "Not a study plan" })).status).toBe(200);
    expect((await dre.call("GET", "/library")).body.plans).toEqual([]);
    const mine = await dre.call("GET", `/plans/${p.id}`);
    expect(mine.body).toMatchObject({ listed: -1, listedNote: "Not a study plan", library: false });
    expect((await dre.call("PUT", `/plans/${p.id}/listed`, { listed: true })).body.error).toBe("taken_out");
    expect(await (await person("maya")).status("GET", `/plans/${p.id}`)).toBe(404);
    const out = await asAdmin(sam, "GET", "/admin/library");
    expect(out.body.plans).toEqual([{ id: p.id, code: p.code, name: "Cardio block", note: "Not a study plan", ownerName: "Dre" }]);
    expect((await dre.call("GET", "/admin/library")).status).toBe(404);
    expect((await asAdmin(sam, "DELETE", `/admin/library/${p.id}`)).status).toBe(200);
    expect((await dre.call("GET", `/plans/${p.id}`)).body.listed).toBe(0);
    expect((await dre.call("PUT", `/plans/${p.id}/listed`, { listed: true })).body.listed).toBe(1);
  });

  it("a listed plan can be reported (stores nothing); an unlisted one can't", async () => {
    const dre = await person("dre");
    const p = await plan(dre);
    const maya = await person("maya");
    expect(await maya.status("POST", `/plans/${p.id}/report`, { reason: "spam" })).toBe(404);
    await dre.call("PUT", `/plans/${p.id}/listed`, { listed: true });
    expect(await maya.status("POST", `/plans/${p.id}/report`, { reason: "rude" })).toBe(400);
    expect(await maya.status("POST", `/plans/${p.id}/report`, { reason: "spam", note: "ads" })).toBe(200);
    expect(await dre.status("POST", `/plans/${p.id}/report`, { reason: "spam" })).toBe(400);  // your own
  });

  it("deleting an account takes its name out of copies' credit", async () => {
    const dre = await person("dre");
    const p = await plan(dre);
    await dre.call("PUT", `/plans/${p.id}/listed`, { listed: true });
    const maya = await person("maya");
    const cp = await maya.call("POST", `/plans/${p.id}/copy`, { start: "2027-01-04" });
    expect((await api("DELETE", "/account", { token: dre.token })).status).toBe(200);
    expect((await maya.call("GET", `/plans/${cp.body.id}`)).body.basedOn).toEqual({ id: p.id, name: "Cardio block", owner: "?" });
  });

  it("A: a shared link's peek carries the plan's version and its events", async () => {
    const dre = await person("dre");
    const p = await plan(dre);
    const pub = await api("GET", `/plans/public?code=${p.code}`);
    expect(pub.status).toBe(200);
    expect(pub.body).toMatchObject({ v: p.version, events: [{ day: "2026-10-16", name: "Cardio quiz" }] });
  });
});
