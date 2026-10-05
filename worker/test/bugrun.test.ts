import { describe, expect, it } from "vitest";
import { db, person } from "./helpers";

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
});
