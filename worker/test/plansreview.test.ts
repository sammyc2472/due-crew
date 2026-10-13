// The plans review before 3.8.1 ships, the server's side: tag roots that
// never run out, a date's note ids kept only while what they came from is,
// a post with a save that changes nothing, the follow ceiling counting what
// I see, one total per plan (kept on its row, at most an hour old), and the
// smaller ones: room and ceilings for every save, Undo after an upload from
// the author's Anki, and a stamp that moves with all the board carries.
import { env } from "cloudflare:test";
import { describe, expect, it } from "vitest";
import { anHourOn, api, db, person } from "./helpers";
import { PLAN_BYTES_MAX, ownerBytes, rootTries } from "../src/plans";

const UNITS = [
  { id: "hf", name: "Heart failure", opens: "2026-10-05", tags: ["Step1::Cardio::Heart_failure"] },
  { id: "ar", name: "Arrhythmia", opens: "2026-10-12", tags: ["Step1::Cardio::Arrhythmia"] },
];
type Who = Awaited<ReturnType<typeof person>>;

async function plan(who: Who, name = "MS2 Block 1", units: unknown[] = UNITS) {
  const made = await who.call("POST", "/plans", { name, deck: "Step 1" });
  const put = await who.call("PUT", `/plans/${made.body.id}`, { version: 1, doc: { deck: "Step 1", units } });
  expect(put.status).toBe(200);
  return put.body;
}

/** Other plans holding these tag roots, as other authors' would. */
let taken = 0;
async function takeRoots(...roots: string[]) {
  const now = Math.floor(Date.now() / 1000);
  await db().batch(roots.map((r) => {
    const i = taken++;
    return db().prepare("INSERT INTO plans (id, code, owner, name, doc, tagroot, created_at, updated_at) VALUES (?, ?, 'someone', ?, ?, ?, ?, ?)")
      .bind(`taken${String(i).padStart(11, "0")}`, `T${String(i).padStart(7, "0")}`, r, JSON.stringify({ deck: "Step 1", units: [] }), r, now, now);
  }));
}

/** The owner's plans fill all but `room` bytes of what one account keeps. */
async function fillTo(owner: string, room: number) {
  const now = Math.floor(Date.now() / 1000);
  let left = PLAN_BYTES_MAX - room - (await ownerBytes(env, owner));
  const rows = [];
  for (let i = 0; left > 0; i++) {
    const n = Math.min(1024 * 1024, left);
    rows.push(db().prepare("INSERT INTO plans (id, code, owner, name, doc, created_at, updated_at) VALUES (?, ?, ?, 'F', ?, ?, ?)")
      .bind(`fill${String(i).padStart(12, "0")}`, `F${String(i).padStart(7, "0")}`, owner, "x".repeat(n), now, now));
    left -= n;
  }
  await db().batch(rows);
}

/** A ceiling's window, used up. */
const usedUp = (key: string, n: number) => db().prepare("INSERT OR REPLACE INTO limits (key, count, window_start) VALUES (?, ?, ?)")
  .bind(key, n, Math.floor(Date.now() / 1000)).run();

const kept = (id: string) => db().prepare("SELECT totals, totals_at FROM plans WHERE id = ?").bind(id)
  .first<{ totals: string | null; totals_at: number | null }>();

describe("tag roots never run out", () => {
  it("past _50, a root ending in the plan's own id, which fits; the id alone after that", () => {
    const tries = rootTries("Block", "abcd2345efgh6789");
    expect(tries.slice(0, 3)).toEqual(["Block", "Block_2", "Block_3"]);
    expect(tries[49]).toBe("Block_50");
    expect(tries.slice(50)).toEqual(["Block_abcd2345efgh6789", "abcd2345efgh6789"]);
    const long = rootTries("x".repeat(60), "abcd2345efgh6789");
    expect(long.every((r) => r.length <= 60)).toBe(true);
    expect(long[50]).toBe(`${"x".repeat(43)}_abcd2345efgh6789`);
  });

  it("the 51st plan of one name still makes its first tag", async () => {
    const dre = await person("dre");
    const p = await plan(dre, "Block");
    await takeRoots("block", ...rootTries("Block", p.id).slice(1, 50));  // case aside, as Anki's tags
    const r = await dre.call("POST", `/plans/${p.id}/tags`, { name: "SLG 12", add: ["g1"] });
    expect(r.status).toBe(200);
    expect(r.body.doc.tagroot).toBe(`Block_${p.id}`);
    // and with that one taken too (a plan named so), the id alone; every one taken is "try again"
    const q = await plan(dre, "Block");
    await takeRoots(`Block_${q.id}`.toUpperCase());
    expect((await dre.call("POST", `/plans/${q.id}/tags`, { name: "SLG 1", add: ["g1"] })).body.doc.tagroot).toBe(q.id);
    const s = await plan(dre, "Block");
    await takeRoots(`Block_${s.id}`, s.id);
    expect((await dre.call("POST", `/plans/${s.id}/tags`, { name: "SLG 1", add: ["g1"] })).status).toBe(503);
  });

  it("a listed plan copied for the 50th time: the copy gets a root of its own", async () => {
    const jo = await person("jo");
    const p = await plan(jo, "Cardio");
    const tagged = await jo.call("POST", `/plans/${p.id}/tags`, { name: "SLG 1", add: ["g1"] });
    expect(tagged.body.doc.tagroot).toBe("Cardio");
    const cur = await jo.call("PUT", `/plans/${p.id}`, { version: tagged.body.version, doc: { ...tagged.body.doc,
      units: [{ ...UNITS[0], tags: ["DueCrew::Cardio::SLG_1"] }] } });
    expect(cur.status).toBe(200);
    expect((await jo.call("PUT", `/plans/${p.id}/listed`, { listed: true })).status).toBe(200);
    await takeRoots(...rootTries("Cardio", "x").slice(1, 50));
    const maya = await person("maya");
    const cp = await maya.call("POST", `/plans/${p.id}/copy`, { start: "2027-01-04" });
    expect(cp.status).toBe(200);
    expect(cp.body.doc.tagroot).toBe(`Cardio_${cp.body.id}`);
    expect(cp.body.doc.units[0].tags).toEqual([`DueCrew::Cardio_${cp.body.id}::SLG_1`]);  // its dates follow
  });
});

describe("a date's note ids, kept while what they came from is", () => {
  const VIDEO = "Lectures::Pharm::Cephalosporins";
  const Q1 = '"tag:DueCrew::MS2\\_Block\\_1::SLG\\_1" "tag:Lectures::Pharm::Cephalosporins"';
  const Q2 = '"tag:DueCrew::MS2\\_Block\\_1::SLG\\_2" "tag:Lectures::Pharm::Cephalosporins"';
  const TAGS = [{ id: "t1", name: "SLG 1", notes: ["g1"] }, { id: "t2", name: "SLG 2", notes: ["g2"] }];
  const CUT = { id: "c1", name: "Cephalosporins", opens: "2026-10-19", tags: [], search: [Q1], cut: [{ tag: VIDEO, in: "t1", q: Q1 }] };

  it("a site save keeps a date's ids while its tags, subdecks and cuts are the same, never as it sends them", async () => {
    const dre = await person("dre");
    const p = await plan(dre);
    const put0 = await dre.call("PUT", `/plans/${p.id}`, { version: p.version,
      doc: { deck: "Step 1", tagroot: "MS2_Block_1", tags: TAGS, units: [...UNITS, CUT] } });
    expect(put0.status).toBe(200);
    expect((await dre.call("PUT", `/plans/${p.id}/ids`, { units: {
      hf: [UNITS[0].tags, [], ["n1", "n2"]], ar: [UNITS[1].tags, [], ["n3"]], c1: [[], [], ["n4"], [[VIDEO, "t1"]]] } })).status).toBe(200);
    let cur = (await dre.call("GET", `/plans/${p.id}`)).body;
    const ids = (doc: any) => Object.fromEntries(doc.units.map((u: any) => [u.id, u.ids]));
    expect(ids(cur.doc)).toEqual({ hf: ["n1", "n2"], ar: ["n3"], c1: ["n4"] });
    const save = async (units: unknown[]) => {
      const r = await dre.call("PUT", `/plans/${p.id}`, { version: cur.version, doc: { ...cur.doc, units } });
      expect(r.status).toBe(200);
      cur = r.body;
      return ids(cur.doc);
    };
    // the builder sends the doc back as it got it: a rename keeps them
    expect(await save(cur.doc.units.map((u: any) => (u.id === "hf" ? { ...u, name: "HF" } : u))))
      .toEqual({ hf: ["n1", "n2"], ar: ["n3"], c1: ["n4"] });
    // a tag added to a date: its ids were worked out from the tags it had, and go
    expect(await save(cur.doc.units.map((u: any) => (u.id === "hf" ? { ...u, tags: [...u.tags, "Step1::Cardio::Cardiomyopathy"] } : u))))
      .toEqual({ hf: undefined, ar: ["n3"], c1: ["n4"] });
    // a subdeck, the same
    expect(await save(cur.doc.units.map((u: any) => (u.id === "ar" ? { ...u, decks: ["Step 1::Extras"] } : u))))
      .toEqual({ hf: undefined, ar: undefined, c1: ["n4"] });
    // a cut kept to another of the plan's tags, the same
    expect(await save(cur.doc.units.map((u: any) => (u.id === "c1" ? { ...u, search: [Q2], cut: [{ tag: VIDEO, in: "t2", q: Q2 }] } : u))))
      .toEqual({ hf: undefined, ar: undefined, c1: undefined });
    // and a save can't put any there: only the author's Anki does
    expect(await save(cur.doc.units.map((u: any) => ({ ...u, ids: ["forged"] })))).toEqual({ hf: undefined, ar: undefined, c1: undefined });
    expect((await dre.call("PUT", `/plans/${p.id}/ids`, { units: { hf: [cur.doc.units[0].tags, [], ["n9"]] } })).status).toBe(200);
    cur = (await dre.call("GET", `/plans/${p.id}`)).body;
    expect(ids(cur.doc).hf).toEqual(["n9"]);
  });
});

describe("a post with a save that changes nothing", () => {
  it("goes all the same, on its own, and the ceiling is said as with a save", async () => {
    const dre = await person("dre");
    const p = await plan(dre);
    const same = { version: p.version, name: p.name, line: p.line, doc: p.doc, summary: "" };
    const r = await dre.call("PUT", `/plans/${p.id}`, { ...same, post: "Week 2 is up" });
    expect(r.status).toBe(200);
    expect(r.body.version).toBe(p.version);  // nothing saved
    expect(r.body.posted).toMatchObject({ text: "Week 2 is up" });
    const posts = (await dre.call("GET", `/plans/${p.id}/posts`)).body.posts;
    expect(posts.map((x: any) => [x.text, x.withSave])).toEqual([["Week 2 is up", false]]);
    for (let i = 0; i < 4; i++) await dre.call("PUT", `/plans/${p.id}`, { ...same, post: `line ${i}` });
    const sixth = await dre.call("PUT", `/plans/${p.id}`, { ...same, post: "one too many" });
    expect(sixth.status).toBe(200);
    expect(sixth.body.posted).toEqual({ error: "too_many_posts" });
    expect(await dre.status("PUT", `/plans/${p.id}`, { ...same, post: "\n" })).toBe(400);
  });
});

describe("the follow ceiling counts what I see", () => {
  it("squad plans I left don't count toward the 20; past what's kept in all, it's still refused", async () => {
    const dre = await person("dre");
    const maya = await person("maya");
    const sq = (await dre.call("POST", "/squads", { name: "MS2" })).body;
    await maya.call("POST", `/squads/${sq.id}/join`, { code: sq.code });
    for (let i = 0; i < 20; i++) {
      const made = await dre.call("POST", "/plans", { name: `Week ${i + 1}`, deck: "Step 1" });
      expect(await dre.status("PUT", `/plans/${made.body.id}`, { version: 1, audience: "squad", squad: sq.id })).toBe(200);
      expect(await maya.status("POST", "/plans/follow", { code: made.body.code })).toBe(200);
    }
    const jo = await person("jo");
    const other = await plan(jo, "Renal");
    expect((await maya.call("POST", "/plans/follow", { code: other.code })).body.error).toBe("too_many_plans");
    const pv = (await maya.call("GET", "/board?pv=")).body.pv;
    expect(await maya.status("DELETE", `/squads/${sq.id}/members/maya`)).toBe(200);
    // the board and my list show none of them now, and the stamp moved, so the add-on hears it
    const after = (await maya.call("GET", `/board?pv=${pv}`)).body;
    expect(after.pv).not.toBe(pv);
    expect(after.plans).toEqual([]);
    expect((await maya.call("GET", "/plans/mine")).body.plans).toEqual([]);
    expect(await maya.status("POST", "/plans/follow", { code: other.code })).toBe(200);
    // what's kept in all has a ceiling too: 100 follows, seen or not
    const now = Math.floor(Date.now() / 1000);
    await db().batch(Array.from({ length: 79 }, (_, i) => db().prepare(
      "INSERT INTO plan_follows (plan, uid, share, paused, at) VALUES (?, 'maya', 0, 0, ?)").bind(`gone${String(i).padStart(12, "0")}`, now)));
    await db().batch(Array.from({ length: 79 }, (_, i) => db().prepare(
      "INSERT INTO plans (id, code, owner, name, audience, squad, doc, created_at, updated_at) VALUES (?, ?, 'dre', 'Old', 'squad', 'gone', '{}', ?, ?)")
      .bind(`gone${String(i).padStart(12, "0")}`, `G${String(i).padStart(7, "0")}`, now, now)));
    const last = await plan(jo, "Neuro");
    expect((await maya.call("POST", "/plans/follow", { code: last.code })).body.error).toBe("too_many_plans");
  });
});

describe("one total per plan, kept on its row", () => {
  it("read as kept while it's under an hour old; older, counted again and kept; mine stays live", async () => {
    const dre = await person("dre");
    const p = await plan(dre);
    expect(await kept(p.id)).toEqual({ totals: null, totals_at: null });  // no one follows: nothing written
    const maya = await person("maya");
    const nia = await person("nia");
    expect((await maya.call("POST", "/plans/follow", { code: p.code, team: true })).body.followers).toBe(1);
    const k1 = await kept(p.id);
    expect(JSON.parse(k1!.totals!)).toEqual({ v: p.version, n: 1, m: 1, r: 0, done: {} });
    await maya.call("POST", "/sync", { plans: { [p.id]: { hf: [10, 10, 10] } } });
    await nia.call("POST", "/plans/follow", { code: p.code, team: true });
    // under an hour old: every reader reads it as kept, and nothing is written
    const onBoard = async (who: Who) => (await who.call("GET", "/board?decks=1")).body.plans.find((x: any) => x.id === p.id);
    expect(await onBoard(maya)).toMatchObject({ followers: 1, crewDone: {} });
    // ...but the authors' "reached" is counted live: both follow, and Maya's board just carried this version
    expect((await dre.call("GET", `/plans/${p.id}`)).body).toMatchObject({ followers: 1, reached: [1, 2] });
    expect((await dre.call("GET", "/plans/mine")).body.plans[0].followers).toBe(1);
    expect((await nia.call("GET", `/plans/peek?code=${p.code}`)).body.followers).toBe(1);
    expect((await api("GET", `/plans/public?code=${p.code}`)).body.followers).toBe(1);
    expect(await kept(p.id)).toEqual(k1);
    // mine alone is live: my progress, as I synced it
    await maya.call("POST", "/sync", { plans: { [p.id]: { hf: [10, 10, 10], ar: [3, 1, 9] } } });
    expect((await maya.call("GET", `/plans/${p.id}`)).body.following.progress).toEqual({ hf: [10, 10, 10], ar: [3, 1, 9] });
    // an hour on: counted again, once, and kept with its time
    await anHourOn();
    expect(await onBoard(nia)).toMatchObject({ followers: 2, crewDone: { hf: 1 } });
    const k2 = await kept(p.id);
    expect(JSON.parse(k2!.totals!)).toEqual({ v: p.version, n: 2, m: 2, r: 1, done: { hf: 1 } });  // Maya's board carried it; Nia's is this one
    expect(k2!.totals_at).toBeGreaterThan(Math.floor(Date.now() / 1000) - 60);
    expect((await dre.call("GET", `/plans/${p.id}`)).body).toMatchObject({ followers: 2, reached: [2, 2] });  // live: Nia's board too
    expect(await kept(p.id)).toEqual(k2);
    // a save moves the version: none have it yet, at once, with nothing counted or written
    const saved = await dre.call("PUT", `/plans/${p.id}`, { version: p.version, doc: { deck: "Step 1", units: UNITS.slice(0, 1) } });
    expect(saved.body.reached).toEqual([0, 2]);
    expect(await kept(p.id)).toEqual(k2);
    // the library reads the same totals
    await dre.call("PUT", `/plans/${p.id}/listed`, { listed: true });
    await (await person("zoe")).call("POST", "/plans/follow", { code: p.code });
    expect((await nia.call("GET", "/library")).body.plans[0].followers).toBe(2);
    await anHourOn();
    expect((await nia.call("GET", "/library")).body.plans[0].followers).toBe(3);
  });
});

describe("room and ceilings for every save", () => {
  it("cards from Anki's browser: the saves' daily ceiling, and room for the doc Undo keeps", async () => {
    const dre = await person("dre");
    const p = await plan(dre);
    const add = () => dre.call("POST", `/plans/${p.id}/cards`, { unit: "hf", cards: [["gA", 0]] });
    await fillTo("dre", 100);  // room for a few bytes more, not for the new doc beside the old
    const full = await add();
    expect(full.status).toBe(409);
    expect(full.body.error).toBe("plans_full");
    await db().prepare("DELETE FROM plans WHERE id LIKE 'fill%'").run();
    expect((await add()).status).toBe(200);
    await usedUp("planput:dre", 500);
    expect((await dre.call("POST", `/plans/${p.id}/cards`, { unit: "ar", cards: [["gB", 0]] })).status).toBe(429);
  });

  it("a tag from Anki counts the doc it keeps for Undo", async () => {
    const dre = await person("dre");
    const p = await plan(dre);
    await fillTo("dre", 150);  // the tag's own bytes fit; the new doc beside the old doesn't
    const r = await dre.call("POST", `/plans/${p.id}/tags`, { name: "SLG 12", add: ["g1"] });
    expect(r.status).toBe(409);
    expect(r.body.error).toBe("plans_full");
  });

  it("an upload from the author's Anki keeps Undo; Undo and the uploads have ceilings of their own", async () => {
    const dre = await person("dre");
    const p = await plan(dre);
    const saved = await dre.call("PUT", `/plans/${p.id}`, { version: p.version, summary: "added cardiomyopathy",
      doc: { deck: "Step 1", units: [...UNITS, { id: "cm", name: "Cardiomyopathy", opens: "2026-10-19", tags: ["Step1::Cardio::CM"] }] } });
    const up = await dre.call("PUT", `/plans/${p.id}/ids`, { units: { cm: [["Step1::Cardio::CM"], [], ["n1"]] } });
    expect(up.body.version).toBe(saved.body.version + 1);  // a new version, no row of its own
    const log = (await dre.call("GET", `/plans/${p.id}/log`)).body.log;
    expect(log[0]).toMatchObject({ version: saved.body.version, summary: "added cardiomyopathy", undo: true });
    expect(log.slice(1).every((x: any) => !x.undo)).toBe(true);
    expect(await dre.status("POST", `/plans/${p.id}/undo`, { version: saved.body.version })).toBe(409);  // the plan's version, as read
    const undone = await dre.call("POST", `/plans/${p.id}/undo`, { version: up.body.version });
    expect(undone.status).toBe(200);
    expect(undone.body.doc.units.map((u: any) => u.id)).toEqual(["hf", "ar"]);
    expect((await dre.call("GET", `/plans/${p.id}/log`)).body.log[0]).toMatchObject({ summary: "undid: added cardiomyopathy", undo: true });
    // the uploads' ceiling is their own: it never takes a save's, nor a save its
    await usedUp("planids:dre", 500);
    expect(await dre.status("PUT", `/plans/${p.id}/ids`, { units: {} })).toBe(429);
    expect(await dre.status("PUT", `/plans/${p.id}`, { version: undone.body.version, name: "Block 1" })).toBe(200);
    await db().prepare("DELETE FROM limits WHERE key = 'planids:dre'").run();
    await usedUp("planput:dre", 500);
    const v = (await dre.call("GET", `/plans/${p.id}`)).body.version;
    expect(await dre.status("POST", `/plans/${p.id}/undo`, { version: v })).toBe(429);
    expect(await dre.status("PUT", `/plans/${p.id}/ids`, { units: {} })).toBe(200);
  });
});

describe("the plans' stamp moves with all the board carries", () => {
  it("a co-author's plan saved, a plan offered to my squad, and leaving that squad", async () => {
    const dre = await person("dre");
    const maya = await person("maya");
    const p = await plan(dre);
    await db().prepare("INSERT INTO plan_editors (plan, uid, at, accepted_at) VALUES (?, 'maya', 0, 0)").bind(p.id).run();
    const board = (pv: string) => maya.call("GET", `/board?pv=${pv}`).then((r) => r.body);
    const b0 = await board("");
    expect(b0.authored.map((a: any) => a.id)).toEqual([p.id]);
    expect((await board(b0.pv)).authored).toBeUndefined();  // nothing moved: nothing comes
    // a co-author I am, following it or not: the save reaches my Anki's tags at the next refresh
    await dre.call("PUT", `/plans/${p.id}`, { version: p.version, name: "Block 1" });
    const b1 = await board(b0.pv);
    expect(b1.pv).not.toBe(b0.pv);
    expect(b1.authored[0]).toMatchObject({ id: p.id, name: "Block 1", version: p.version + 1 });
    // a plan offered to a squad I'm in
    const sq = (await dre.call("POST", "/squads", { name: "MS2" })).body;
    await maya.call("POST", `/squads/${sq.id}/join`, { code: sq.code });
    const q = await plan(dre, "Renal");
    expect((await board(b1.pv)).pv).toBe(b1.pv);
    await dre.call("PUT", `/plans/${q.id}`, { version: q.version, audience: "squad", squad: sq.id });
    const b2 = await board(b1.pv);
    expect(b2.pv).not.toBe(b1.pv);
    expect(b2.planOffers.map((o: any) => o.id)).toEqual([q.id]);
    // following it, then leaving the squad: the plan goes from my board at the next refresh
    await maya.call("POST", "/plans/follow", { code: q.code });
    const b3 = await board(b2.pv);
    expect(b3.plans.map((x: any) => x.id)).toEqual([q.id]);
    await maya.call("DELETE", `/squads/${sq.id}/members/maya`);
    const b4 = await board(b3.pv);
    expect(b4.pv).not.toBe(b3.pv);
    expect(b4.plans).toEqual([]);
  });
});

describe("my list of plans", () => {
  it("keeps what the add-on and the site read from it: a date's notes and pasted ids' cards, the plan tags' notes and cards", async () => {
    const dre = await person("dre");
    const p = await plan(dre, "MS2 Block 1", [{ ...UNITS[0], nids: [11], notes: ["gN"], cards: [["gC", 0]] }]);
    await dre.call("PUT", `/plans/${p.id}/ids`, { units: { hf: [UNITS[0].tags, [], ["n1"]] }, refs: { hf: [[11], [], [["gI", 1]]] } });
    const cur = (await dre.call("GET", `/plans/${p.id}`)).body;
    await dre.call("PUT", `/plans/${p.id}`, { version: cur.version,
      doc: { ...cur.doc, tagroot: "MS2_Block_1", tags: [{ id: "t1", name: "SLG 1", notes: ["g1"], cards: [["g2", 1]] }] } });
    const [row] = (await dre.call("GET", "/plans/mine")).body.plans;
    expect(row.doc.units[0]).toMatchObject({ notes: ["gN"], idr: [["gI", 1]] });
    expect(row.doc.units[0].ids).toBeUndefined();  // a list never needs these
    expect(row.doc.units[0].cards).toBeUndefined();
    expect(row.doc.tags).toEqual([{ id: "t1", name: "SLG 1", notes: ["g1"], cards: [["g2", 1]] }]);
  });
});
