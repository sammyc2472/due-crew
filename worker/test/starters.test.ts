import { describe, expect, it } from "vitest";
import { api, db, person } from "./helpers";

// 3.9.5: starter plans. The admin marks a few plans in the library as
// starters; the library shows them in their own row under Due Crew, and the
// day's first board offers them to someone who owns and follows no plan.

const UNITS = [
  { id: "hf", name: "Heart failure", opens: "2026-10-05", due: "2026-10-07", tags: ["Step1::Cardio::HF"], n: 120 },
  { id: "arr", name: "Arrhythmia", opens: "2026-10-26", tags: ["Step1::Cardio::Arr"], n: 80 },
];

type Who = Awaited<ReturnType<typeof person>>;

async function plan(who: Who, name = "A chapter a day", deck = "Big Step 1", line = "") {
  const made = await who.call("POST", "/plans", { name, deck });
  const put = await who.call("PUT", `/plans/${made.body.id}`, { version: 1, doc: { deck, units: UNITS }, ...(line ? { line } : {}) });
  expect(put.status).toBe(200);
  return put.body;
}

async function listed(who: Who, name?: string, deck?: string, line?: string) {
  const p = await plan(who, name, deck, line);
  expect(await who.status("PUT", `/plans/${p.id}/listed`, { listed: true })).toBe(200);
  return p;
}

const asAdmin = (who: { token: string }, method: string, path: string, body?: unknown) =>
  api(method, path, { token: who.token, body, env: { ADMIN_UIDS: "sam" } as any });
const starter = (sam: Who, id: string, on = true) => asAdmin(sam, "POST", `/admin/library/${id}/starter`, { on });
const flag = async (id: string) => (await db().prepare("SELECT starter FROM plans WHERE id = ?").bind(id).first<number>("starter"));

describe("starter plans (3.9.5)", () => {
  it("only the admin marks one, only a listed plan, with a plain body; the audit log keeps it", async () => {
    const sam = await person("sam");
    const dre = await person("dre");
    const p = await listed(dre);
    // not the admin: as if there were no such route, even for the plan's owner
    const no = await dre.call("POST", `/admin/library/${p.id}/starter`, { on: true });
    expect([no.status, no.body.error]).toEqual([404, "not_found"]);
    expect(await flag(p.id)).toBe(0);
    expect((await starter(sam, "nosuchplan")).status).toBe(404);
    expect((await asAdmin(sam, "POST", `/admin/library/${p.id}/starter`, { on: "yes" })).status).toBe(400);
    expect((await asAdmin(sam, "POST", `/admin/library/${p.id}/starter`, { on: true, extra: 1 })).status).toBe(400);
    expect((await asAdmin(sam, "POST", `/admin/library/${p.id}/starter`, {})).status).toBe(400);
    const on = await starter(sam, p.id);
    expect([on.status, on.body]).toEqual([200, { ok: true, starter: true }]);
    expect(await flag(p.id)).toBe(1);
    expect((await starter(sam, p.id)).status).toBe(200);  // again: nothing changes
    // a plan not in the library can't be one
    const quiet = await plan(dre, "Not listed");
    const refused = await starter(sam, quiet.id);
    expect([refused.status, refused.body.error]).toEqual([409, "not_listed"]);
    expect(await flag(quiet.id)).toBe(0);
    expect((await starter(sam, quiet.id, false)).status).toBe(200);  // not one: fine either way
    const off = await starter(sam, p.id, false);
    expect([off.status, off.body]).toEqual([200, { ok: true, starter: false }]);
    expect(await flag(p.id)).toBe(0);
    const log = (await asAdmin(sam, "GET", "/admin/actions")).body.actions.map((a: any) => [a.action, a.detail]);
    expect(log).toEqual([["took a starter off", `A chapter a day (plan ${p.id})`], ["made a starter", `A chapter a day (plan ${p.id})`]]);
  });

  it("leaving the library ends it: the owner's switch, the admin's Take out, a plan for one squad", async () => {
    const sam = await person("sam");
    const dre = await person("dre");
    const a = await listed(dre, "One");
    const b = await listed(dre, "Two");
    const c = await listed(dre, "Three");
    for (const p of [a, b, c]) expect((await starter(sam, p.id)).status).toBe(200);
    // a save that keeps it listed keeps the mark
    const saved = await dre.call("PUT", `/plans/${a.id}`, { version: a.version, line: "a chapter of the videos a day" });
    expect(saved.status).toBe(200);
    expect(await flag(a.id)).toBe(1);
    // the owner takes it out of the library
    expect((await dre.call("PUT", `/plans/${a.id}/listed`, { listed: false })).body.listed).toBe(0);
    expect(await flag(a.id)).toBe(0);
    expect((await dre.call("PUT", `/plans/${a.id}/listed`, { listed: true })).body.listed).toBe(1);
    expect(await flag(a.id)).toBe(0);  // listed again, a starter only when the admin says so
    // the admin takes it out, and puts it back
    expect((await asAdmin(sam, "POST", `/admin/library/${b.id}`, { note: "Not a study plan" })).status).toBe(200);
    expect(await flag(b.id)).toBe(0);
    expect((await starter(sam, b.id)).body.error).toBe("not_listed");
    expect((await asAdmin(sam, "DELETE", `/admin/library/${b.id}`)).status).toBe(200);
    expect(await flag(b.id)).toBe(0);
    // made for one squad: out of the library, out of the starters
    const sq = await dre.call("POST", "/squads", { name: "Block 2" });
    const moved = await dre.call("PUT", `/plans/${c.id}`, { version: c.version, audience: "squad", squad: sq.body.id });
    expect([moved.status, moved.body.listed]).toEqual([200, 0]);
    expect(await flag(c.id)).toBe(0);
    expect((await (await person("maya")).call("GET", "/library")).body.starters).toEqual([]);
  });

  it("the library: starters apart on the first page, newest first, eight at most, under Due Crew; a filter shows them in the grid", async () => {
    const sam = await person("sam", "Sam Caplan");
    const dre = await person("dre");
    const plain = await listed(dre, "Dre's own block", "Big Step 1", "by system");
    const starters = [];
    for (let i = 1; i <= 9; i++) starters.push(await listed(sam, `Starter ${i}`, i === 9 ? "Spanish" : "Big Step 1", "a chapter a day"));
    for (const [i, p] of starters.entries()) {
      expect((await starter(sam, p.id)).status).toBe(200);
      await db().prepare("UPDATE plans SET listed_at = ? WHERE id = ?").bind(1000 + i, p.id).run();
    }
    await db().prepare("UPDATE plans SET listed_at = ? WHERE id = ?").bind(500, plain.id).run();
    const maya = await person("maya");
    const lib = await maya.call("GET", "/library");
    expect(lib.status).toBe(200);
    expect(lib.body.starters.map((x: any) => x.name)).toEqual(["Starter 9", "Starter 8", "Starter 7", "Starter 6",
                                                               "Starter 5", "Starter 4", "Starter 3", "Starter 2"]);
    expect(lib.body.plans.map((x: any) => x.name)).toEqual(["Dre's own block"]);  // the grid leaves them out
    expect(lib.body.plans[0].starter).toBeUndefined();
    expect(lib.body.plans[0].ownerName).toBe("Dre");
    const s9 = lib.body.starters[0];
    expect(s9).toMatchObject({ id: starters[8].id, code: starters[8].code, name: "Starter 9", line: "a chapter a day", ownerName: "Due Crew",
      starter: true, mine: false, followers: 0, deck: "Spanish", dates: 2, from: "2026-10-05", to: "2026-10-26", days: 22 });
    expect(JSON.stringify(lib.body.starters)).not.toContain("Sam Caplan");
    // the admin's own starters say they're his, still under Due Crew
    expect((await sam.call("GET", "/library")).body.starters[0]).toMatchObject({ mine: true, ownerName: "Due Crew" });
    // a later page has none apart (the grid still leaves them out)
    const p1 = await maya.call("GET", "/library?page=1");
    expect(p1.body.starters).toBeUndefined();
    expect(p1.body.plans).toEqual([]);
    // a filter or a search: no row apart; the starters that match are in the grid, as starters
    const deck = await maya.call("GET", "/library?deck=Spanish");
    expect(deck.body.starters).toBeUndefined();
    expect(deck.body.plans.map((x: any) => [x.name, x.ownerName, x.starter])).toEqual([["Starter 9", "Due Crew", true]]);
    const q = await maya.call("GET", "/library?q=block");
    expect(q.body.starters).toBeUndefined();
    expect(q.body.plans.map((x: any) => x.name)).toEqual(["Dre's own block"]);
    const len = await maya.call("GET", "/library?len=short");
    expect(len.body.starters).toBeUndefined();
    expect(len.body.plans).toHaveLength(10);
    // a copy of a starter is based on Due Crew's
    const cp = await maya.call("POST", `/plans/${starters[0].id}/copy`, { start: "2027-01-04" });
    expect(cp.status).toBe(200);
    expect(cp.body.basedOn).toEqual({ id: starters[0].id, name: "Starter 1", owner: "Due Crew" });
    expect(cp.body.doc.units[0].opens).toBe("2027-01-04");
  });

  it("the board: on the day's first refresh, four at most, only to someone who owns and follows no plan", async () => {
    const sam = await person("sam");
    const made = [];
    for (let i = 1; i <= 5; i++) made.push(await listed(sam, `Starter ${i}`, "Big Step 1", i === 1 ? "the videos, <b>a chapter</b> a day" : ""));
    const maya = await person("maya");
    expect((await maya.call("GET", "/board?decks=1")).body.starters).toEqual([]);  // listed, none marked yet
    for (const [i, p] of made.entries()) {
      await starter(sam, p.id);
      await db().prepare("UPDATE plans SET listed_at = ? WHERE id = ?").bind(1000 + i, p.id).run();
    }
    const first = await maya.call("GET", "/board?decks=1&wk=2026-W44&got=0&pv=");
    expect(first.status).toBe(200);
    expect(first.body.plans).toEqual([]);
    expect(first.body.starters.map((x: any) => x.name)).toEqual(["Starter 5", "Starter 4", "Starter 3", "Starter 2"]);
    expect(first.body.starters[3]).toEqual({ id: made[1].id, name: "Starter 2", deck: "Big Step 1", days: 22, perDay: 9, line: "" });
    // only these: no code, no owner
    expect(Object.keys(first.body.starters[0]).sort()).toEqual(["days", "deck", "id", "line", "name", "perDay"]);
    // the rest of the day's refreshes don't carry them, nor does the site's home
    expect((await maya.call("GET", "/board?got=0&pv=")).body.starters).toBeUndefined();
    expect((await maya.call("GET", "/board")).body.starters).toBeUndefined();
    expect((await maya.call("GET", "/board?keep=1&decks=1")).body.starters).toBeUndefined();
    // the line comes as written (the add-on escapes it)
    await starter(sam, made[0].id);
    await db().prepare("UPDATE plans SET listed_at = 2000 WHERE id = ?").bind(made[0].id).run();
    expect((await maya.call("GET", "/board?decks=1")).body.starters[0].line).toBe("the videos, <b>a chapter</b> a day");
    // following a plan: none
    const kai = await person("kai");
    expect((await kai.call("POST", "/plans/follow", { code: made[0].code })).status).toBe(200);
    expect((await kai.call("GET", "/board?decks=1")).body.starters).toBeUndefined();
    // owning one (a copy of a starter, say): none
    const cp = await maya.call("POST", `/plans/${made[1].id}/copy`, { start: "2026-10-26" });
    expect(cp.status).toBe(200);
    expect((await maya.call("GET", "/board?decks=1")).body.starters).toBeUndefined();
    // the admin who wrote them owns plans: none
    expect((await sam.call("GET", "/board?decks=1")).body.starters).toBeUndefined();
    // with no starters at all, someone with no plan gets an empty list
    await db().prepare("UPDATE plans SET starter = 0").run();
    expect((await (await person("zed")).call("GET", "/board?decks=1")).body.starters).toEqual([]);
  });

  it("co-writing a plan counts as having one", async () => {
    const sam = await person("sam");
    const p = await listed(sam, "Starter");
    await starter(sam, p.id);
    const dre = await person("dre");
    const kai = await person("kai");
    const own = await plan(dre, "Dre's");
    // kai and dre are crew, so dre can ask kai to co-write
    await db().prepare("INSERT INTO friends (owner, friend, at) VALUES ('dre', 'kai', 1), ('kai', 'dre', 1)").run();
    expect((await kai.call("GET", "/board?decks=1")).body.starters.map((x: any) => x.id)).toEqual([p.id]);
    expect(await dre.status("POST", `/plans/${own.id}/editors`, { uid: "kai" })).toBe(200);
    // asked, not yet said yes: still no plan
    expect((await kai.call("GET", "/board?decks=1")).body.starters).toHaveLength(1);
    expect(await kai.status("POST", `/plans/${own.id}/invite`, { yes: true })).toBe(200);
    expect((await kai.call("GET", "/board?decks=1")).body.starters).toBeUndefined();
  });
});
