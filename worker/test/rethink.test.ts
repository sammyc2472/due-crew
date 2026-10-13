import { describe, expect, it } from "vitest";
import { person } from "./helpers";

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
