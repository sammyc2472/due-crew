import { describe, expect, it } from "vitest";
import { env } from "cloudflare:workers";
import { api, befriend, db, person } from "./helpers";
import * as Quiet from "../src/quiet";

// Plans, round three (3.8.1): a co-author says yes first, and a plan can be
// handed over; where to get the deck (deckUrl); the authors' notes on a tag
// or a card (remarks); what a date's picked cards are (pl, from "#lbl").

const UNITS = [
  { id: "hf", name: "Heart failure", opens: "2026-10-05", tags: ["Step1::Cardio::Heart_failure"] },
  { id: "pk", name: "Picked", opens: "2026-10-06", tags: [], cards: [["gA", 0], ["gB", 1]] },
];

type Who = Awaited<ReturnType<typeof person>>;

async function plan(name = "MS2 Block 1") {
  const dre = await person("dre");
  const maya = await person("maya");
  await befriend(dre, maya);
  await befriend(maya, dre);
  const made = await dre.call("POST", "/plans", { name, deck: "Step 1" });
  const put = await dre.call("PUT", `/plans/${made.body.id}`, { version: 1, doc: { deck: "Step 1", units: UNITS } });
  expect(put.status).toBe(200);
  return { dre, maya, p: put.body };
}

const board = async (who: Who, q = "?decks=1") => (await who.call("GET", `/board${q}`)).body;
const saveDoc = (who: Who, p: { id: string }, version: number, doc: unknown) => who.call("PUT", `/plans/${p.id}`, { version, doc });

describe("3.8.1: a co-author says yes first", () => {
  it("an invite is nothing until it's answered: no saves, no tags in Anki, listed only to the authors", async () => {
    const { dre, maya, p } = await plan();
    const kai = await person("kai");
    await kai.call("POST", "/plans/follow", { code: p.code });
    const asked = await dre.call("POST", `/plans/${p.id}/editors`, { uid: maya.uid });
    expect(asked.status).toBe(200);
    expect(asked.body.editors).toEqual([{ uid: "maya", name: "Maya", emoji: "", pending: true }]);
    // not a co-author anywhere
    expect(await maya.status("PUT", `/plans/${p.id}`, { version: p.version, name: "Mine now" })).toBe(403);
    expect(await maya.status("POST", `/plans/${p.id}/tags`, { name: "SLG 1", add: ["g1"] })).toBe(403);
    expect(await maya.status("PUT", `/plans/${p.id}/ids`, { units: {} })).toBe(403);
    expect(await maya.status("POST", `/plans/${p.id}/remarks`, { add: { card: ["gA", 0], text: "x" } })).toBe(403);
    expect(await maya.status("GET", `/plans/${p.id}/log`)).toBe(403);
    expect((await board(maya)).authored).toEqual([]);
    expect((await maya.call("GET", "/plans/mine")).body.plans).toEqual([]);
    // she may look before she says yes: as a reader, who sees no invites
    const looks = await maya.call("GET", `/plans/${p.id}`);
    expect(looks.status).toBe(200);
    expect(looks.body.role).toBe("reader");
    expect(looks.body.editors).toEqual([]);
    expect(looks.body.code).toBeUndefined();
    // a follower sees co-authors, never invites
    expect((await kai.call("GET", `/plans/${p.id}`)).body.editors).toEqual([]);
    // the day's first board, and the site's home, carry it: who asked, by name and emoji only
    await db().prepare("UPDATE users SET emoji = '🦊' WHERE uid = 'dre'").run();
    const want = [{ id: p.id, name: "MS2 Block 1", kind: "coauthor", by: { name: "Dre", emoji: "🦊" } }];
    expect((await board(maya)).planInvites).toEqual(want);
    expect((await board(maya, "?keep=1")).planInvites).toEqual(want);
    expect((await board(dre)).planInvites).toEqual([]);
    expect((await board(maya, "")).planInvites).toBeUndefined();  // a plain refresh carries none
  });

  it("yes makes a co-author; no takes the invite away; either moves the stamp", async () => {
    const { dre, maya, p } = await plan();
    const b0 = await board(maya, "?pv=");
    await dre.call("POST", `/plans/${p.id}/editors`, { uid: maya.uid });
    const b1 = await board(maya, `?pv=${b0.pv}`);
    expect(b1.pv).not.toBe(b0.pv);  // one arrived
    expect(b1.planInvites.map((x: any) => x.kind)).toEqual(["coauthor"]);
    expect((await board(maya, `?pv=${b1.pv}`)).planInvites).toBeUndefined();  // nothing moved
    const yes = await maya.call("POST", `/plans/${p.id}/invite`, { yes: true });
    expect(yes.status).toBe(200);
    expect(yes.body).toMatchObject({ role: "editor", code: p.code, editors: [{ uid: "maya", name: "Maya", emoji: "" }] });
    const b2 = await board(maya, `?pv=${b1.pv}`);
    expect(b2.pv).not.toBe(b1.pv);
    expect(b2.planInvites).toEqual([]);
    expect(b2.authored.map((a: any) => a.id)).toEqual([p.id]);  // her Anki tags for it now
    expect(await maya.status("PUT", `/plans/${p.id}`, { version: p.version, name: "Block 1" })).toBe(200);
    // answered: nothing more to answer
    const again = await maya.call("POST", `/plans/${p.id}/invite`, { yes: true });
    expect([again.status, again.body.error]).toEqual([404, "no_invite"]);
    // no, to another
    const kai = await person("kai");
    await befriend(dre, kai); await befriend(kai, dre);
    await dre.call("POST", `/plans/${p.id}/editors`, { uid: kai.uid });
    const no = await kai.call("POST", `/plans/${p.id}/invite`, { yes: false });
    expect(no.status).toBe(200);
    expect(no.body.role).toBe("reader");
    expect(await db().prepare("SELECT COUNT(*) AS n FROM plan_editors WHERE uid = 'kai'").first<number>("n")).toBe(0);
    expect((await board(kai)).planInvites).toEqual([]);
    expect(await kai.status("POST", `/plans/${p.id}/invite`, { yes: "yes" })).toBe(400);
    expect(await kai.status("POST", `/plans/${p.id}/invite`, { yes: true, extra: 1 })).toBe(400);
    expect(await kai.status("POST", "/plans/nosuchplan/invite", { yes: true })).toBe(404);
  });

  it("only someone the owner could add today; an invite counts toward the plan's co-authors; the owner takes it back", async () => {
    const { dre, maya, p } = await plan();
    const kai = await person("kai");
    expect(await dre.status("POST", `/plans/${p.id}/editors`, { uid: kai.uid })).toBe(403);  // not crew
    await befriend(dre, kai);  // one way only: still not crew
    expect(await dre.status("POST", `/plans/${p.id}/editors`, { uid: kai.uid })).toBe(403);
    expect(await maya.status("POST", `/plans/${p.id}/editors`, { uid: maya.uid })).toBe(403);  // only the owner asks
    await dre.call("POST", `/plans/${p.id}/editors`, { uid: maya.uid });
    expect(await dre.status("DELETE", `/plans/${p.id}/editors/maya`)).toBe(200);  // taken back
    expect((await board(maya)).planInvites).toEqual([]);
    expect(await maya.status("POST", `/plans/${p.id}/invite`, { yes: true })).toBe(404);
    // ten in all, invites and co-authors together
    const now = Math.floor(Date.now() / 1000);
    await db().batch(Array.from({ length: 10 }, (_, i) => db().prepare("INSERT INTO plan_editors (plan, uid, at) VALUES (?, ?, ?)").bind(p.id, `x${i}`, now)));
    const full = await dre.call("POST", `/plans/${p.id}/editors`, { uid: maya.uid });
    expect([full.status, full.body.error]).toEqual([409, "too_many_editors"]);
  });

  it("a board carries at most ten invites, the plans offered to me first", async () => {
    const maya = await person("maya");
    const dre = await person("dre");
    const now = Math.floor(Date.now() / 1000);
    const rows = [];
    for (let i = 0; i < 12; i++) {
      const id = `plan${String(i).padStart(12, "0")}`;
      rows.push(db().prepare("INSERT INTO plans (id, code, owner, name, line, audience, doc, version, created_at, updated_at) VALUES (?, ?, 'dre', ?, '', 'code', ?, 1, ?, ?)")
        .bind(id, `C${String(i).padStart(7, "0")}`, `P${i}`, JSON.stringify({ deck: "D", units: [] }), now, now));
      rows.push(i === 11
        ? db().prepare("INSERT INTO plan_editors (plan, uid, at, accepted_at) VALUES (?, 'maya', ?, ?)").bind(id, now, now)
        : db().prepare("INSERT INTO plan_editors (plan, uid, at) VALUES (?, 'maya', ?)").bind(id, now + i));
    }
    rows.push(db().prepare("UPDATE plans SET handover = 'maya' WHERE id = ?").bind(`plan${"0".repeat(10)}11`));
    await db().batch(rows);
    const got = (await board(maya)).planInvites;
    expect(got).toHaveLength(10);
    expect(got[0]).toEqual({ id: `plan${"0".repeat(10)}11`, name: "P11", kind: "owner", by: { name: "Dre", emoji: "" } });
    expect(got.slice(1).map((x: any) => x.name)).toEqual(["P10", "P9", "P8", "P7", "P6", "P5", "P4", "P3", "P2"]);
    void dre;
  });
});

describe("3.8.1: handing a plan over", () => {
  async function coWritten() {
    const { dre, maya, p } = await plan();
    await dre.call("POST", `/plans/${p.id}/tags`, { name: "SLG 12", add: ["g1"] });
    await dre.call("POST", `/plans/${p.id}/editors`, { uid: maya.uid });
    await maya.call("POST", `/plans/${p.id}/invite`, { yes: true });
    const nia = await person("nia");
    await nia.call("POST", "/plans/follow", { code: p.code });
    return { dre, maya, nia, p };
  }

  it("the owner offers it to a co-author; yes makes it theirs, the owner a co-author; code, tag root and followers stay", async () => {
    const { dre, maya, nia, p } = await coWritten();
    const kai = await person("kai");
    await befriend(dre, kai); await befriend(kai, dre);
    await dre.call("POST", `/plans/${p.id}/editors`, { uid: kai.uid });  // invited, not yet a co-author
    const notYet = await dre.call("POST", `/plans/${p.id}/owner`, { uid: kai.uid });
    expect([notYet.status, notYet.body.error]).toEqual([400, "not_coauthor"]);
    expect((await dre.call("POST", `/plans/${p.id}/owner`, { uid: nia.uid })).body.error).toBe("not_coauthor");  // a follower
    expect(await maya.status("POST", `/plans/${p.id}/owner`, { uid: maya.uid })).toBe(403);  // the owner's alone
    expect(await dre.status("POST", `/plans/${p.id}/owner`, { uid: 7 })).toBe(400);
    const before = (await dre.call("GET", `/plans/${p.id}`)).body;
    const offered = await dre.call("POST", `/plans/${p.id}/owner`, { uid: maya.uid });
    expect(offered.status).toBe(200);
    expect(offered.body.handover).toBe("maya");  // the authors see whom it's offered to
    expect((await maya.call("GET", `/plans/${p.id}`)).body.handover).toBe("maya");
    expect((await nia.call("GET", `/plans/${p.id}`)).body.handover).toBeUndefined();
    expect((await board(maya)).planInvites).toEqual([{ id: p.id, name: "MS2 Block 1", kind: "owner", by: { name: "Dre", emoji: "" } }]);
    const yes = await maya.call("POST", `/plans/${p.id}/invite`, { yes: true });
    expect(yes.status).toBe(200);
    expect(yes.body).toMatchObject({ role: "owner", owner: "maya", ownerName: "Maya", code: p.code, followers: 1 });
    // the invite the old owner sent goes with them (Kai is Dre's crew, not Maya's)
    expect(yes.body.editors.map((e: any) => [e.uid, !!e.pending]).sort()).toEqual([["dre", false]]);
    expect(yes.body.handover).toBeUndefined();
    expect(yes.body.doc.tagroot).toBe(before.doc.tagroot);
    expect((await board(maya)).planInvites).toEqual([]);
    // the old owner co-writes it now: saves, but can't take it down or pick its co-authors
    const dreView = (await dre.call("GET", `/plans/${p.id}`)).body;
    expect(dreView.role).toBe("editor");
    expect(await dre.status("PUT", `/plans/${p.id}`, { version: dreView.version, name: "Block 1" })).toBe(200);
    expect(await dre.status("DELETE", `/plans/${p.id}`)).toBe(403);
    expect(await dre.status("POST", `/plans/${p.id}/owner`, { uid: "dre" })).toBe(403);
    expect((await board(kai)).planInvites).toEqual([]);
    // the follower's plan is the same plan, its new owner's name on it
    const followed = (await board(nia)).plans.find((x: any) => x.id === p.id);
    expect(followed).toMatchObject({ ownerName: "Maya", owner: "maya" });
    // and it can go back the same way
    await maya.call("POST", `/plans/${p.id}/owner`, { uid: "dre" });
    expect((await dre.call("POST", `/plans/${p.id}/invite`, { yes: true })).body.role).toBe("owner");
  });

  it("no leaves it theirs; the owner takes an offer back; removing the one it's offered to ends the offer", async () => {
    const { dre, maya, p } = await coWritten();
    await dre.call("POST", `/plans/${p.id}/owner`, { uid: maya.uid });
    const no = await maya.call("POST", `/plans/${p.id}/invite`, { yes: false });
    expect(no.body).toMatchObject({ role: "editor", owner: "dre" });
    expect(no.body.handover).toBeUndefined();
    expect((await maya.call("POST", `/plans/${p.id}/invite`, { yes: true })).status).toBe(404);  // nothing to answer
    // taken back
    await dre.call("POST", `/plans/${p.id}/owner`, { uid: maya.uid });
    const back = await dre.call("POST", `/plans/${p.id}/owner`, { uid: null });
    expect(back.body.handover).toBeUndefined();
    expect((await board(maya)).planInvites).toEqual([]);
    // removed (or leaving), the offer goes with her
    await dre.call("POST", `/plans/${p.id}/owner`, { uid: maya.uid });
    expect(await maya.status("DELETE", `/plans/${p.id}/editors/maya`)).toBe(200);
    expect(await db().prepare("SELECT handover FROM plans WHERE id = ?").bind(p.id).first("handover")).toBeNull();
    expect(await maya.status("POST", `/plans/${p.id}/invite`, { yes: true })).toBe(404);
  });

  it("a plan handed over counts toward its new owner's plans", async () => {
    const { dre, maya, p } = await coWritten();
    const now = Math.floor(Date.now() / 1000);
    await db().batch(Array.from({ length: 50 }, (_, i) => db().prepare(
      "INSERT INTO plans (id, code, owner, name, line, audience, doc, version, created_at, updated_at) VALUES (?, ?, 'maya', 'x', '', 'code', ?, 1, ?, ?)",
    ).bind(`mine${String(i).padStart(12, "0")}`, `M${String(i).padStart(7, "0")}`, JSON.stringify({ deck: "D", units: [] }), now, now)));
    await dre.call("POST", `/plans/${p.id}/owner`, { uid: maya.uid });
    const full = await maya.call("POST", `/plans/${p.id}/invite`, { yes: true });
    expect([full.status, full.body.error]).toEqual([409, "too_many_plans"]);
    expect(await db().prepare("SELECT owner FROM plans WHERE id = ?").bind(p.id).first("owner")).toBe("dre");
  });

  it("a quiet owner's plan goes to a co-author who said yes, never to an invite; the owner's invites and offer go", async () => {
    const { dre, maya, p } = await coWritten();
    const kai = await person("kai");
    await befriend(dre, kai); await befriend(kai, dre);
    await dre.call("POST", `/plans/${p.id}/editors`, { uid: kai.uid });
    await db().prepare("UPDATE plan_editors SET at = 1 WHERE uid = 'kai'").run();  // asked first, never answered
    await dre.call("POST", `/plans/${p.id}/owner`, { uid: maya.uid });
    const now = Math.floor(Date.now() / 1000);
    await db().prepare("UPDATE users SET last_seen = ?, created_at = ? WHERE uid = 'dre'").bind(now - 400 * 86400, now - 400 * 86400).run();
    await Quiet.run(env as any, now);
    expect(await db().prepare("SELECT owner, handover FROM plans WHERE id = ?").bind(p.id).first()).toEqual({ owner: "maya", handover: null });
    expect(await db().prepare("SELECT COUNT(*) AS n FROM plan_editors WHERE plan = ?").bind(p.id).first("n")).toBe(0);
    expect((await board(kai)).planInvites).toEqual([]);
  });

  it("Your data says which plans I was asked to co-write and which was offered to me", async () => {
    const { dre, maya, p } = await coWritten();
    await dre.call("POST", `/plans/${p.id}/owner`, { uid: maya.uid });
    const mine = (await maya.call("GET", "/account/data")).body.plansCoAuthored;
    expect(mine).toEqual([{ plan: "MS2 Block 1", at: expect.any(String), offeredToYou: true }]);
    // deleting my account ends an offer made to me
    expect(await maya.status("DELETE", "/account")).toBe(200);
    expect(await db().prepare("SELECT handover FROM plans WHERE id = ?").bind(p.id).first("handover")).toBeNull();
  });
});

describe("3.8.1: where to get the deck", () => {
  it("an https link, at most 300 characters, no spaces; the plan's link page shows it", async () => {
    const { dre, p } = await plan();
    const url = "https://example.org/decks/step-1?v=2#top";
    const ok = await saveDoc(dre, p, p.version, { deck: "Step 1", deckUrl: url, units: UNITS });
    expect(ok.status).toBe(200);
    expect(ok.body.doc.deckUrl).toBe(url);
    const pub = await api("GET", `/plans/public?code=${p.code}`);
    expect(pub.body.deckUrl).toBe(url);
    for (const bad of ["http://example.org/deck", "https://example.org/a deck", "https:///nohost", "https://", `https://e.org/${"x".repeat(300)}`,
                       "javascript:alert(1)", "https://e.org/\"><script>", 42]) {
      expect(await dre.status("PUT", `/plans/${p.id}`, { version: ok.body.version, doc: { deck: "Step 1", deckUrl: bad, units: UNITS } }), String(bad)).toBe(400);
    }
    const none = await saveDoc(dre, p, ok.body.version, { deck: "Step 1", deckUrl: "", units: UNITS });
    expect(none.body.doc.deckUrl).toBeUndefined();
    expect((await api("GET", `/plans/public?code=${p.code}`)).body.deckUrl).toBeUndefined();
  });
});

describe("3.8.1: the authors' notes on a tag or a card (remarks)", () => {
  it("ride the doc: exactly one of a tag or a card, one line of at most 280, 300 a plan", async () => {
    const { dre, p } = await plan();
    const doc = (remarks: unknown) => ({ deck: "Step 1", units: UNITS, remarks });
    const ok = await saveDoc(dre, p, p.version, doc([
      { id: "r1", tag: "Step1::Micro::Herpes_Viruses", text: "  Watch the\nvideo first  " },
      { id: "r2", card: ["gA", 0], text: "Easy to mix up with the next one" },
    ]));
    expect(ok.status).toBe(200);
    expect(ok.body.doc.remarks).toEqual([
      { id: "r1", tag: "Step1::Micro::Herpes_Viruses", text: "Watch the video first" },
      { id: "r2", card: ["gA", 0], text: "Easy to mix up with the next one" }]);
    const v = ok.body.version;
    for (const bad of [
      [{ id: "r1", tag: "T", card: ["gA", 0], text: "both" }],
      [{ id: "r1", text: "neither" }],
      [{ id: "r1", tag: "T\u0001x", text: "a control character" }],
      [{ id: "r1", tag: "x".repeat(201), text: "too long a path" }],
      [{ id: "r1", card: ["gA", -1], text: "a card number below 0" }],
      [{ id: "r1", card: ["gA"], text: "half a card" }],
      [{ id: "R1", tag: "T", text: "an id out of shape" }],
      [{ id: "r1", tag: "T", text: "x".repeat(281) }],
      [{ id: "r1", tag: "T", text: "   " }],
      [{ id: "r1", tag: "T", text: "a" }, { id: "r1", tag: "U", text: "the same id twice" }],
      [{ id: "r1", tag: "T", text: "a", extra: 1 }],
      Array.from({ length: 301 }, (_, i) => ({ id: `r${i}`, tag: "T", text: "many" })),
    ]) {
      const r = await saveDoc(dre, p, v, doc(bad));
      expect([r.status, r.body.error], JSON.stringify(bad).slice(0, 80)).toEqual([400, "bad_plan"]);
    }
    expect((await saveDoc(dre, p, v, doc(Array.from({ length: 300 }, (_, i) => ({ id: `r${i}`, tag: "T", text: "many" }))))).status).toBe(200);
  });

  it("a note on a plan tag follows the plan's tag root", async () => {
    const { dre } = await plan();  // MS2_Block_1 is taken by the time the second plan saves
    const first = (await dre.call("POST", "/plans", { name: "MS2 Block 1", deck: "Step 1" })).body;
    await dre.call("POST", `/plans/${first.id}/tags`, { name: "SLG 12", add: ["g1"] });
    const second = (await dre.call("POST", "/plans", { name: "MS2 Block 1", deck: "Step 1" })).body;
    const saved = await saveDoc(dre, second, 1, { deck: "Step 1", units: UNITS, tagroot: "MS2_Block_1",
      tags: [{ id: "t1", name: "SLG 12", notes: ["g2"] }],
      remarks: [{ id: "r1", tag: "DueCrew::MS2_Block_1::SLG_12", text: "Start here" }, { id: "r2", tag: "Step1::Other", text: "Not ours" }] });
    expect(saved.body.doc.tagroot).toBe("MS2_Block_1_2");
    expect(saved.body.doc.remarks.map((r: any) => r.tag)).toEqual(["DueCrew::MS2_Block_1_2::SLG_12", "Step1::Other"]);
  });

  it("POST /plans/{id}/remarks: an author's note on a card from Browse, a save with its line in History", async () => {
    const { dre, maya, p } = await plan();
    const add = (who: Who, body: unknown) => who.call("POST", `/plans/${p.id}/remarks`, body);
    const a = await add(dre, { add: { card: ["gA", 0], text: "Read the explanation\ntwice" } });
    expect(a.status).toBe(200);
    expect(a.body.version).toBe(p.version + 1);
    expect(a.body.doc.remarks).toEqual([{ id: expect.stringMatching(/^[a-z0-9]{8}$/), card: ["gA", 0], text: "Read the explanation twice" }]);
    const id = a.body.doc.remarks[0].id;
    // one note on a card: a second one changes its text
    const b = await add(dre, { add: { card: ["gA", 0], text: "Read it once" } });
    expect(b.body.doc.remarks).toEqual([{ id, card: ["gA", 0], text: "Read it once" }]);
    const same = await add(dre, { add: { card: ["gA", 0], text: "Read it once" } });
    expect(same.body.version).toBe(b.body.version);  // nothing new: nothing written
    const c = await add(dre, { add: { tag: "Step1::Micro::Herpes_Viruses", text: "Start with the overview" } });
    expect(c.body.doc.remarks.map((r: any) => r.tag ?? r.card)).toEqual([["gA", 0], "Step1::Micro::Herpes_Viruses"]);
    const gone = await add(dre, { remove: id });
    expect(gone.body.doc.remarks.map((r: any) => r.tag)).toEqual(["Step1::Micro::Herpes_Viruses"]);
    expect((await add(dre, { remove: id })).body.version).toBe(gone.body.version);  // gone already
    const log = (await dre.call("GET", `/plans/${p.id}/log`)).body.log.map((l: any) => l.summary);
    expect(log.slice(0, 4)).toEqual(["took off a note on a card in Anki", "added a note on Herpes Viruses in Anki",
      "changed a note on a card in Anki", "added a note on a card in Anki"]);
    expect((await dre.call("GET", `/plans/${p.id}/log`)).body.log[0].undo).toBe(true);
    // the plans I write carry their notes, for my Anki's Browse
    expect((await board(dre)).authored[0].doc.remarks).toEqual(gone.body.doc.remarks);
    // shapes
    for (const bad of [{}, { add: { card: ["gA", 0], text: "x" }, remove: "r1" }, { add: "x" }, { remove: "R!" },
                       { add: { id: "mine", card: ["gA", 0], text: "x" } }]) {
      expect(await dre.status("POST", `/plans/${p.id}/remarks`, bad), JSON.stringify(bad)).toBe(400);
    }
    expect((await add(dre, { add: { tag: "T", card: ["gA", 0], text: "both" } })).body.error).toBe("bad_plan");
    expect((await add(dre, { add: { card: ["gA", 0], text: "x".repeat(281) } })).body.error).toBe("bad_plan");
    // the authors alone: a follower can't, a co-author can
    const kai = await person("kai");
    await kai.call("POST", "/plans/follow", { code: p.code });
    expect(await kai.status("POST", `/plans/${p.id}/remarks`, { add: { card: ["gB", 1], text: "x" } })).toBe(403);
    await dre.call("POST", `/plans/${p.id}/editors`, { uid: maya.uid });
    await maya.call("POST", `/plans/${p.id}/invite`, { yes: true });
    expect(await maya.status("POST", `/plans/${p.id}/remarks`, { add: { card: ["gB", 1], text: "Mine" } })).toBe(200);
  });

  it("300 a plan; the saves' daily ceiling", async () => {
    const { dre, p } = await plan();
    const full = await saveDoc(dre, p, p.version, { deck: "Step 1", units: UNITS,
      remarks: Array.from({ length: 300 }, (_, i) => ({ id: `r${i}`, card: [`g${i}`, 0], text: "n" })) });
    expect(full.status).toBe(200);
    const more = await dre.call("POST", `/plans/${p.id}/remarks`, { add: { card: ["gNew", 0], text: "one more" } });
    expect([more.status, more.body.error]).toEqual([409, "too_many_remarks"]);
    expect((await dre.call("POST", `/plans/${p.id}/remarks`, { add: { card: ["g1", 0], text: "an edit fits" } })).status).toBe(200);
    await db().prepare("INSERT OR REPLACE INTO limits (key, count, window_start) VALUES ('planput:dre', 500, ?)").bind(Math.floor(Date.now() / 1000)).run();
    expect(await dre.status("POST", `/plans/${p.id}/remarks`, { remove: "r1" })).toBe(429);
  });
});

describe("3.8.1: what a date's picked cards are (pl)", () => {
  it("the author's Anki names them (#lbl); kept while the picks are the same, dropped when they change", async () => {
    const { dre, p } = await plan();
    const lbl = [["Step1::Micro::Herpes_Viruses", 88], ["Step1::Micro::Pox", 2]];
    const up = await dre.call("PUT", `/plans/${p.id}/ids`, { units: {}, counts: { pk: { "#lbl": lbl }, hf: { "#lbl": lbl } } });
    expect(up.status).toBe(200);
    expect(up.body.version).toBe(p.version + 1);
    let doc = (await dre.call("GET", `/plans/${p.id}`)).body.doc;
    expect(doc.units.find((u: any) => u.id === "pk").pl).toEqual(lbl);
    expect(doc.units.find((u: any) => u.id === "hf").pl).toBeUndefined();  // no picks: nothing to name
    // only that shape is kept; anything else is skipped, and the upload stands
    for (const bad of [[["a", 1], ["b", 2], ["c", 3], ["d", 4]], [["a", -1]], [["x".repeat(201), 1]], [["a\nb", 1]], [["a"]], "a", [[1, 2]]]) {
      const r = await dre.call("PUT", `/plans/${p.id}/ids`, { units: {}, counts: { pk: { "#lbl": bad } } });
      expect(r.status, JSON.stringify(bad)).toBe(200);
      expect(r.body.version).toBe(up.body.version);
    }
    // a site save with the same picks keeps it, whatever the save sends
    const kept = await saveDoc(dre, p, up.body.version, { deck: "Step 1",
      units: doc.units.map((u: any) => (u.id === "pk" ? { ...u, name: "Herpes", pl: [["Forged", 1]] } : u)) });
    expect(kept.body.doc.units.find((u: any) => u.id === "pk")).toMatchObject({ name: "Herpes", pl: lbl });
    const notSent = await saveDoc(dre, p, kept.body.version, { deck: "Step 1",
      units: kept.body.doc.units.map((u: any) => { const { pl, ...rest } = u; void pl; return rest; }) });
    expect(notSent.body.doc.units.find((u: any) => u.id === "pk").pl).toEqual(lbl);
    // other picks: gone until the author's Anki names them again
    const changed = await saveDoc(dre, p, notSent.body.version, { deck: "Step 1",
      units: notSent.body.doc.units.map((u: any) => (u.id === "pk" ? { ...u, cards: [["gA", 0]] } : u)) });
    expect(changed.body.doc.units.find((u: any) => u.id === "pk").pl).toBeUndefined();
    // a card added from Anki's Browse changes them too; one it has already doesn't
    await dre.call("PUT", `/plans/${p.id}/ids`, { units: {}, counts: { pk: { "#lbl": lbl } } });
    doc = (await dre.call("GET", `/plans/${p.id}`)).body;
    const dup = await dre.call("POST", `/plans/${p.id}/cards`, { unit: "pk", cards: [["gA", 0]] });
    expect(dup.body.version).toBe(doc.version);
    expect(dup.body.doc.units.find((u: any) => u.id === "pk").pl).toEqual(lbl);
    const more = await dre.call("POST", `/plans/${p.id}/cards`, { unit: "pk", cards: [["gC", 0]] });
    expect(more.body.doc.units.find((u: any) => u.id === "pk").pl).toBeUndefined();
    // an empty list takes it off
    await dre.call("PUT", `/plans/${p.id}/ids`, { units: {}, counts: { pk: { "#lbl": lbl } } });
    await dre.call("PUT", `/plans/${p.id}/ids`, { units: {}, counts: { pk: { "#lbl": [] } } });
    expect((await dre.call("GET", `/plans/${p.id}`)).body.doc.units.find((u: any) => u.id === "pk").pl).toBeUndefined();
  });

  it("rides the plan to its followers and the site's list; a doc's pl out of shape is refused", async () => {
    const { dre, p } = await plan();
    const lbl = [["Step1::Micro::Herpes_Viruses", 88]];
    await dre.call("PUT", `/plans/${p.id}/ids`, { units: {}, counts: { pk: { "#lbl": lbl } } });
    const nia = await person("nia");
    await nia.call("POST", "/plans/follow", { code: p.code });
    expect((await board(nia)).plans[0].doc.units.find((u: any) => u.id === "pk").pl).toEqual(lbl);
    expect((await dre.call("GET", "/plans/mine")).body.plans[0].doc.units.find((u: any) => u.id === "pk").pl).toEqual(lbl);
    const v = (await dre.call("GET", `/plans/${p.id}`)).body.version;
    const bad = UNITS.map((u) => (u.id === "pk" ? { ...u, pl: [["a", 1], ["b", 1], ["c", 1], ["d", 1]] } : u));
    expect(await dre.status("PUT", `/plans/${p.id}`, { version: v, doc: { deck: "Step 1", units: bad } })).toBe(400);
  });
});
