import { describe, expect, it } from "vitest";
import { befriend, db, person } from "./helpers";

// The October bug run: what the Worker got wrong, pinned.

async function codePlan(who: Awaited<ReturnType<typeof person>>, name = "Cardio") {
  const made = (await who.call("POST", "/plans", { name, deck: "D" })).body;
  return (await who.call("PUT", `/plans/${made.id}`, { version: 1,
    doc: { deck: "D", units: [{ id: "a", name: "A", opens: "2026-10-05", tags: ["X"] }] } })).body;
}

describe("the October bug run", () => {
  it("a founder who leaves hands the squad to its longest-standing member; the last one out ends it", async () => {
    const alice = await person("alice");
    const bob = await person("bob");
    const carol = await person("carol");
    const sq = (await alice.call("POST", "/squads", { name: "busm" })).body;
    for (const p of [bob, carol]) expect((await p.call("POST", `/squads/${sq.id}/join`, { code: sq.code })).status).toBe(200);
    expect((await alice.call("DELETE", `/squads/${sq.id}/members/alice`)).status).toBe(200);
    expect(await db().prepare("SELECT founder FROM squads WHERE id = ?").bind(sq.id).first("founder")).toBe("bob");
    expect(await alice.status("POST", `/squads/${sq.id}/block/carol`)).toBe(403);  // gone means gone
    await bob.call("DELETE", `/squads/${sq.id}/members/bob`);
    await carol.call("DELETE", `/squads/${sq.id}/members/carol`);
    expect(await db().prepare("SELECT COUNT(*) AS n FROM squads WHERE id = ?").bind(sq.id).first("n")).toBe(0);
    expect(await db().prepare("SELECT COUNT(*) AS n FROM squad_codes WHERE squad = ?").bind(sq.id).first("n")).toBe(0);
  });

  it("one follower can't fill a plan's notes; its authors still write", async () => {
    const dre = await person("dre");
    const eve = await person("eve");
    const p = await codePlan(dre);
    expect((await eve.call("POST", "/plans/follow", { code: p.code })).status).toBe(200);
    const rows = Array.from({ length: 50 }, (_, i) =>
      db().prepare("INSERT INTO plan_notes (plan, uid, day, text, at) VALUES (?, 'eve', '2026-10-05', ?, ?)").bind(p.id, `n${i}`, i));
    await db().batch(rows);
    expect((await eve.call("POST", `/plans/${p.id}/notes`, { day: "2026-10-05", text: "one more" })).body.error).toBe("too_many_notes");
    expect((await dre.call("POST", `/plans/${p.id}/notes`, { day: "2026-10-05", text: "authors still can" })).status).toBe(200);
  });

  it("GET /plans/mine past 100 plans (D1's 100 bound parameters)", async () => {
    const kai = await person("kai");
    const owner = await person("owner");
    const now = Math.floor(Date.now() / 1000);
    const stmts = [];
    for (let i = 0; i < 120; i++) {
      stmts.push(db().prepare("INSERT INTO plans (id, code, owner, name, line, audience, doc, version, created_at, updated_at) VALUES (?, ?, 'owner', ?, '', 'code', ?, 1, ?, ?)")
        .bind(`plan${String(i).padStart(10, "0")}`, `C${String(i).padStart(7, "0")}`, `P${i}`, JSON.stringify({ deck: "D", units: [] }), now, now));
      stmts.push(db().prepare("INSERT INTO plan_editors (plan, uid, at) VALUES (?, 'kai', ?)").bind(`plan${String(i).padStart(10, "0")}`, now));
    }
    await db().batch(stmts);
    const r = await kai.call("GET", "/plans/mine");
    expect(r.status).toBe(200);
    expect(r.body.plans.length).toBe(120);
    void owner;
  });

  it("a date that doesn't exist is refused (Date.parse takes Feb 31)", async () => {
    const dre = await person("dre");
    const made = (await dre.call("POST", "/plans", { name: "X", deck: "D" })).body;
    expect((await dre.call("PUT", `/plans/${made.id}`, { version: 1,
      doc: { deck: "D", units: [{ id: "a", name: "A", opens: "2026-02-31", tags: ["X"] }] } })).status).toBe(400);
  });

  it("Your data carries the rest of what's kept", async () => {
    const sam = await person("sam");
    const r = await sam.call("GET", "/account/data");
    for (const k of ["deckTrees", "invites", "cheersWaiting", "knocksToYou", "knocksYouSent", "plansCoAuthored",
                     "planSaves", "tipsYouSaidHelped", "squadsBlockedFrom", "emailChange", "adminNote"]) {
      expect(r.body).toHaveProperty(k);
    }
  });

  it("got= keeps a cheer until the next refresh says it arrived (a lost reply loses nothing)", async () => {
    const sam = await person("sam");
    const dre = await person("dre");
    await befriend(sam, dre);
    await befriend(dre, sam);
    await dre.call("POST", "/cheers/sam", { emoji: "🎉" });
    const first = (await sam.call("GET", "/board?got=0")).body;
    expect(first.cheers).toHaveLength(1);
    expect(first.cheersAt).toBeGreaterThan(0);
    // that reply never arrived: the next one carries the same cheer
    expect((await sam.call("GET", "/board?got=0")).body.cheers).toHaveLength(1);
    const after = (await sam.call("GET", `/board?got=${first.cheersAt}`)).body;
    expect(after.cheers).toEqual([]);
    expect(await db().prepare("SELECT COUNT(*) AS n FROM cheers").first("n")).toBe(0);
    // without got= (older add-ons) they still go as they're read
    await dre.call("POST", "/cheers/sam", { emoji: "🔥" });
    expect((await sam.call("GET", "/board")).body.cheers).toHaveLength(1);
    expect((await sam.call("GET", "/board")).body.cheers).toEqual([]);
  });

  it("days are the person's own Anki day: a plan's history, cheers by year, the log's cut", async () => {
    const { ankiDay } = await import("../src/util");
    const t = Date.UTC(2026, 11, 31, 23, 30) / 1000;          // 31 Dec, 23:30 UTC
    expect(ankiDay(t, 0, 0)).toBe("2026-12-31");
    expect(ankiDay(t, 60, 4)).toBe("2026-12-31");             // Berlin: 00:30 on 1 Jan, before the 4am rollover
    expect(ankiDay(t, 120, 0)).toBe("2027-01-01");            // Athens, midnight rollover
    expect(ankiDay(Date.UTC(2027, 0, 1, 3) / 1000, -300, 4)).toBe("2026-12-31");  // New York, 10pm
    expect(ankiDay(t, null, null)).toBe("2026-12-31");
    const dre = await person("dre");
    const sam = await person("sam");
    // a clock 15 hours behind with a 23:00 rollover: always a day or two before UTC's date
    expect(await sam.status("POST", "/sync", { profile: { tz: -900, rollover: 23 } })).toBe(200);
    const p = await codePlan(dre);
    await sam.call("POST", "/plans/follow", { code: p.code });
    await sam.call("POST", "/sync", { plans: { [p.id]: { a: [10, 4, 10] } } });
    const mine = (await sam.call("GET", "/plans/mine")).body.plans.find((x: any) => x.id === p.id);
    const now = Math.floor(Date.now() / 1000);
    expect(Object.keys(mine.following.hist)).toEqual([ankiDay(now, -900, 23)]);
    expect(Object.keys(mine.following.hist)[0]).not.toBe(new Date().toISOString().slice(0, 10));
    await befriend(sam, dre);
    await befriend(dre, sam);
    await dre.call("POST", "/cheers/sam", { emoji: "🎉" });
    expect(await db().prepare("SELECT year FROM cheer_counts WHERE uid = 'sam'").first("year"))
      .toBe(Number(ankiDay(now, -900, 23).slice(0, 4)));
    expect((await sam.call("DELETE", "/log")).body.cut).toBe(ankiDay(now - 8 * 86400, -900, 23));
  });

  it("PUT /settings with the save the server already holds writes nothing", async () => {
    const sam = await person("sam");
    const doc = { v: 1, at: "2026-10-05T10:00:00.000000Z", settings: { emoji: "🐢" } };
    expect(await sam.status("PUT", "/settings", doc)).toBe(200);
    await db().batch([
      db().prepare("CREATE TABLE settings_writes (n INTEGER)"),
      db().prepare("CREATE TRIGGER settings_w AFTER UPDATE ON settings BEGIN INSERT INTO settings_writes VALUES (1); END"),
    ]);
    expect(await sam.status("PUT", "/settings", doc)).toBe(200);
    expect(await db().prepare("SELECT COUNT(*) AS n FROM settings_writes").first("n")).toBe(0);
    expect(await sam.status("PUT", "/settings", { ...doc, at: "2026-10-05T11:00:00.000000Z" })).toBe(200);
    expect(await db().prepare("SELECT COUNT(*) AS n FROM settings_writes").first("n")).toBe(1);
  });

  it("what one account's plans keep has a ceiling; Undo keeps only the latest save's copy", async () => {
    const dre = await person("dre");
    const p = await codePlan(dre);
    const save = (v: number, n: number) => dre.call("PUT", `/plans/${p.id}`, { version: v,
      doc: { deck: "D", units: Array.from({ length: n }, (_, i) => ({ id: `u${i}`, name: `U${i}`, opens: "2026-10-05",
        tags: Array.from({ length: n > 10 ? 50 : 1 }, (_, j) => `T${i}_${j}_${"x".repeat(n > 10 ? 180 : 1)}`) })) } });
    let v = p.version;
    for (const n of [2, 3, 4]) v = (await save(v, n)).body.version;
    expect(await db().prepare("SELECT COUNT(*) AS n FROM plan_log WHERE plan = ? AND prev IS NOT NULL").bind(p.id).first("n")).toBe(1);
    expect((await dre.call("POST", `/plans/${p.id}/undo`, { version: v })).status).toBe(200);
    // fill the account to just under the ceiling with other plans' docs
    const { PLAN_BYTES_MAX } = await import("../src/plans");
    const now = Math.floor(Date.now() / 1000);
    const fill = 1024 * 1024;
    const have = Number(await db().prepare("SELECT SUM(LENGTH(doc)) AS n FROM plans WHERE owner = 'dre'").first("n"))
      + Number(await db().prepare("SELECT COALESCE(SUM(LENGTH(prev)), 0) AS n FROM plan_log").first("n"));
    const k = Math.floor((PLAN_BYTES_MAX - have) / fill);
    await db().batch(Array.from({ length: k }, (_, i) => db().prepare(
      "INSERT INTO plans (id, code, owner, name, line, audience, doc, version, created_at, updated_at) VALUES (?, ?, 'dre', 'F', '', 'code', ?, 1, ?, ?)")
      .bind(`fill${String(i).padStart(10, "0")}`, `F${String(i).padStart(7, "0")}`, "x".repeat(fill), now, now)));
    const cur = (await dre.call("GET", `/plans/${p.id}`)).body.version;
    const big = await save(cur, 120);
    expect(big.status).toBe(409);
    expect(big.body.error).toBe("plans_full");
    expect((await save(cur, 1)).status).toBe(200);  // smaller always saves
  });

  it("deck trees make room by size as well as count", async () => {
    const sam = await person("sam");
    const tags = (k: string) => Array.from({ length: 3000 }, (_, i) => [`${k}::${"t".repeat(40)}${i}`, 5]);
    for (let i = 0; i < 6; i++) {
      expect(await sam.status("PUT", "/plans/trees", { deck: `Deck ${i}`, tags: tags(`D${i}`), decks: [] })).toBe(200);
    }
    const total = Number(await db().prepare("SELECT SUM(LENGTH(doc)) AS n FROM plan_trees WHERE uid = 'sam'").first("n"));
    expect(total).toBeLessThanOrEqual(6 * 1024 * 1024);
    expect(await db().prepare("SELECT COUNT(*) AS n FROM plan_trees WHERE uid = 'sam' AND deck = 'Deck 5'").first("n")).toBe(1);
  });
});
