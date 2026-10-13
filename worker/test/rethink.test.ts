import { describe, expect, it } from "vitest";
import { befriend, person } from "./helpers";

// Plans, rethought (3.8.1): what the morning sends when nothing moved.

const UNITS = [
  { id: "hf", name: "Heart failure", opens: "2026-10-05", tags: ["Step1::Cardio::Heart_failure"] },
  { id: "ar", name: "Arrhythmia", opens: "2026-10-06", tags: ["Step1::Cardio::Arrhythmia"] },
];

describe("3.8.1: the morning keeps the docs it has", () => {
  it("same=1 and an unmoved stamp: each plan without its doc; a moved stamp or an older add-on: every doc", async () => {
    const dre = await person("dre");
    const maya = await person("maya");
    const made = await dre.call("POST", "/plans", { name: "Step 1", deck: "Step 1" });
    const p = (await dre.call("PUT", `/plans/${made.body.id}`, { version: 1, doc: { deck: "Step 1", units: UNITS } })).body;
    expect((await maya.call("POST", "/plans/follow", { code: p.code })).status).toBe(200);

    const first = (await maya.call("GET", "/board?decks=1&pv=&same=1")).body;
    expect(first.plans[0].doc.units.map((u: { id: string }) => u.id)).toEqual(["hf", "ar"]);
    expect(first.plans[0].same).toBeUndefined();
    const pv = first.pv as string;

    const lean = (await maya.call("GET", `/board?decks=1&pv=${pv}&same=1`)).body;
    expect(lean.pv).toBe(pv);
    expect(lean.plans).toHaveLength(1);
    expect(lean.plans[0].doc).toBeUndefined();
    expect(lean.plans[0].same).toBe(true);
    // everything but the doc still comes: the version, the follow, the counts
    expect(lean.plans[0]).toMatchObject({ id: p.id, version: first.plans[0].version, followers: first.plans[0].followers });

    // an add-on before 3.8.1 never asks with same=1: it gets every doc
    const old = (await maya.call("GET", `/board?decks=1&pv=${pv}`)).body;
    expect(old.plans[0].doc.units).toHaveLength(2);

    // a save moves the stamp: the doc comes again, same=1 or not
    await dre.call("PUT", `/plans/${p.id}`, { version: p.version, doc: { deck: "Step 1", units: UNITS.slice(0, 1) } });
    const moved = (await maya.call("GET", `/board?decks=1&pv=${pv}&same=1`)).body;
    expect(moved.pv).not.toBe(pv);
    expect(moved.plans[0].doc.units).toHaveLength(1);
    expect(moved.plans[0].same).toBeUndefined();
  });
});

describe("3.8.1: the author's Anki sees a date's single cards", () => {
  it("authored carries a date made only of single cards, with them, so its picks can be named (#lbl)", async () => {
    const dre = await person("dre");
    const made = await dre.call("POST", "/plans", { name: "Step 1", deck: "Step 1" });
    const units = [...UNITS, { id: "pk", name: "Picked", opens: "2026-10-07", tags: [], decks: [], cards: [["gA", 0], ["gB", 1]] }];
    expect((await dre.call("PUT", `/plans/${made.body.id}`, { version: 1, doc: { deck: "Step 1", units } })).status).toBe(200);
    const mine = (await dre.call("GET", "/board?decks=1&pv=")).body.authored[0];
    const pk = mine.doc.units.find((u: { id: string }) => u.id === "pk");
    expect(pk.cards).toEqual([["gA", 0], ["gB", 1]]);
    // a date of tags alone stays lean
    expect(mine.doc.units.find((u: { id: string }) => u.id === "hf")).toEqual({ id: "hf", tags: ["Step1::Cardio::Heart_failure"], decks: [], opens: "2026-10-05" });
  });
});

describe("3.8.1 review: answers, offers and links", () => {
  async function two() {
    const dre = await person("dre");
    const maya = await person("maya");
    await befriend(dre, maya);
    await befriend(maya, dre);
    const made = await dre.call("POST", "/plans", { name: "Step 1", deck: "Step 1" });
    const p = (await dre.call("PUT", `/plans/${made.body.id}`, { version: 1, doc: { deck: "Step 1", units: UNITS } })).body;
    return { dre, maya, p };
  }

  it("a stale co-write Yes never takes the plan: the answer says which question it answers", async () => {
    const { dre, maya, p } = await two();
    await dre.call("POST", `/plans/${p.id}/editors`, { uid: maya.uid });
    expect((await maya.call("POST", `/plans/${p.id}/invite`, { yes: true, kind: "coauthor" })).body.role).toBe("editor");
    await dre.call("POST", `/plans/${p.id}/owner`, { uid: maya.uid });
    // her Anki still shows the old "co-write?" card: answering it again doesn't hand her the plan
    expect((await maya.call("POST", `/plans/${p.id}/invite`, { yes: true, kind: "coauthor" })).status).toBe(404);
    expect((await dre.call("GET", `/plans/${p.id}`)).body.role).toBe("owner");
    expect((await maya.call("POST", `/plans/${p.id}/invite`, { yes: true, kind: "boss" })).status).toBe(400);
    // the offer itself, answered as one
    expect((await maya.call("POST", `/plans/${p.id}/invite`, { yes: true, kind: "owner" })).body.role).toBe("owner");
  });

  it("a hand-over moves the followers' stamp (its owner's name on their board)", async () => {
    const { dre, maya, p } = await two();
    const nia = await person("nia");
    await nia.call("POST", "/plans/follow", { code: p.code });
    const pv = (await nia.call("GET", "/board?decks=1&pv=")).body.pv;
    await dre.call("POST", `/plans/${p.id}/editors`, { uid: maya.uid });
    await maya.call("POST", `/plans/${p.id}/invite`, { yes: true });
    await dre.call("POST", `/plans/${p.id}/owner`, { uid: maya.uid });
    await maya.call("POST", `/plans/${p.id}/invite`, { yes: true });
    const after = (await nia.call("GET", `/board?pv=${pv}`)).body;
    expect(after.pv).not.toBe(pv);
    expect(after.plans[0]).toMatchObject({ owner: "maya" });
  });

  it("a deck link is printable ASCII: no control or direction-flipping character", async () => {
    const { dre, p } = await two();
    const put = (deckUrl: string) => dre.status("PUT", `/plans/${p.id}`, { version: p.version, doc: { deck: "Step 1", units: UNITS, deckUrl } });
    expect(await put("https://example.com/deck\u0085x")).toBe(400);
    expect(await put("https://example.com/\u202egpj.exe")).toBe(400);
    expect(await put("https://example.com/caf\u00e9")).toBe(400);
    expect(await put("https://example.com/deck?id=12&v=2#top")).toBe(200);
  });
});
