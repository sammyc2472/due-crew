import { describe, expect, it } from "vitest";
import { befriend, person } from "./helpers";
import { tagPart, tagRoot } from "../src/plans";

// 3.8.0, plan tags: the plan's own tags (SLG 12), in its doc beside its
// dates; made in an author's Anki (POST /plans/{id}/tags, note guids) or
// from the site's text (a tag's, a subdeck's or a search's cards). Names
// and guids only, never card text.

const UNITS = [{ id: "hf", name: "Heart failure", opens: "2026-10-05", tags: ["Step1::Cardio::Heart_failure"] }];

async function plan() {
  const dre = await person("dre");
  const maya = await person("maya");
  await befriend(dre, maya);
  await befriend(maya, dre);
  const made = await dre.call("POST", "/plans", { name: "MS2 Block 1", deck: "Step 1" });
  const put = await dre.call("PUT", `/plans/${made.body.id}`, { version: 1, doc: { deck: "Step 1", units: UNITS } });
  expect(put.status).toBe(200);
  return { dre, maya, p: put.body };
}

describe("3.8.0: plan tags", () => {
  it("a name is one part of an Anki tag; the plan's part comes from its name", () => {
    expect(tagPart("SLG 12")).toBe("SLG_12");
    expect(tagPart("  SLG  12: receptors ")).toBe("SLG_12-_receptors");
    expect(tagPart('a "quoted"*\\%name')).toBe("a_quotedname");
    expect(tagPart("___")).toBe("tag");
    expect(tagRoot("MS2 Block 1")).toBe("MS2_Block_1");
    expect(tagRoot("x".repeat(80))).toHaveLength(60);
    expect(tagRoot(":::")).toBe("plan");
  });

  it("an author tags notes from Anki; the tag is made, added to, taken from, and goes when it's empty", async () => {
    const { dre, maya, p } = await plan();
    const first = await dre.call("POST", `/plans/${p.id}/tags`, { name: "SLG 12", add: ["g1", "g2", "g2"], n: 4 });
    expect(first.status).toBe(200);
    expect(first.body.doc.tagroot).toBe("MS2_Block_1");
    expect(first.body.doc.tags).toEqual([{ id: expect.stringMatching(/^[a-z0-9]{8}$/), name: "SLG 12", notes: ["g1", "g2"], n: 4 }]);
    const id = first.body.doc.tags[0].id;
    // the same tag by any spelling of its name; the notes merge
    const more = await dre.call("POST", `/plans/${p.id}/tags`, { name: "slg_12", add: ["g3"], remove: ["g1"] });
    expect(more.body.doc.tags).toEqual([{ id, name: "SLG 12", notes: ["g2", "g3"], n: 4 }]);
    expect(more.body.version).toBe(first.body.version + 1);
    // a co-author can; a follower can't
    expect((await dre.call("POST", `/plans/${p.id}/editors`, { uid: maya.uid })).status).toBe(200);
    expect(await maya.status("POST", `/plans/${p.id}/tags`, { name: "SLG 13", add: ["g9"] })).toBe(200);
    const kai = await person("kai");
    await kai.call("POST", "/plans/follow", { code: p.code });
    expect(await kai.status("POST", `/plans/${p.id}/tags`, { name: "SLG 12", add: ["g9"] })).toBe(403);
    // taking the last note off a tag takes the tag; the plan's part stays
    const gone = await dre.call("POST", `/plans/${p.id}/tags`, { name: "SLG 12", remove: ["g2", "g3"] });
    expect(gone.body.doc.tags.map((t: any) => t.name)).toEqual(["SLG 13"]);
    expect(await dre.status("POST", `/plans/${p.id}/tags`, { name: "SLG 99", remove: ["g1"] })).toBe(404);
    const log = await dre.call("GET", `/plans/${p.id}/log`);
    expect(log.body.log.slice(0, 2).map((x: any) => x.summary)).toEqual(["took 2 notes off SLG 12 in Anki", "tagged 1 note as SLG 13 in Anki"]);
    // the day's first board: the plans I write or co-author carry their own tags, so my Anki can too
    for (const who of [dre, maya]) {
      const a = (await who.call("GET", "/board?decks=1")).body.authored.find((x: any) => x.id === p.id);
      expect(a).toMatchObject({ name: "MS2 Block 1", doc: { tagroot: "MS2_Block_1", tags: [{ name: "SLG 13", notes: ["g9"] }] } });
    }
    expect((await kai.call("GET", "/board?decks=1")).body.authored.find((x: any) => x.id === p.id)).toBeUndefined();
  });

  it("refuses what isn't a note list, past the ceilings", async () => {
    const { dre, p } = await plan();
    const post = (body: unknown) => dre.status("POST", `/plans/${p.id}/tags`, body);
    expect(await post({ name: "SLG 12" })).toBe(400);  // nothing to do
    expect(await post({ name: "SLG 12", add: [1, 2] })).toBe(400);
    expect(await post({ name: "SLG 12", add: ["g"], text: "card text" })).toBe(400);
    expect(await post({ name: "x".repeat(41), add: ["g"] })).toBe(400);
    expect(await post({ name: "SLG 12", add: Array.from({ length: 5001 }, (_, i) => `g${i}`) })).toBe(400);
    expect(await post({ name: "SLG 12", add: Array.from({ length: 3000 }, (_, i) => `a${i}`) })).toBe(200);
    const r = await dre.call("POST", `/plans/${p.id}/tags`, { name: "SLG 12", add: Array.from({ length: 2001 }, (_, i) => `b${i}`) });
    expect(r.status).toBe(400);
    expect(r.body.error).toBe("too_many");
  });

  it("the site's save carries the tags: from tags, a subdeck or a search, unique by their Anki name", async () => {
    const { dre, p } = await plan();
    const put = (doc: unknown) => dre.call("PUT", `/plans/${p.id}`, { version: p.version, doc });
    const tags = [{ id: "t1", name: "SLG 14", tags: ["#Book::Pharm::Ch07"] },
                  { id: "t2", name: "SLG 15", search: ["tag:#Video::Pharm -tag:#Video::Pharm::Extra"], decks: ["Step 1::Pharm"] }];
    const ok = await put({ deck: "Step 1", units: UNITS, tagroot: "MS2_Block_1", tags });
    expect(ok.status).toBe(200);
    expect(ok.body.doc.tags).toEqual(tags);
    const bad = async (doc: unknown) => (await put(doc)).status;
    expect(await bad({ deck: "Step 1", units: UNITS, tags })).toBe(400);  // a part for them to live under
    expect(await bad({ deck: "Step 1", units: UNITS, tagroot: "MS2 Block 1", tags })).toBe(400);  // as an Anki tag part
    expect(await bad({ deck: "Step 1", units: UNITS, tagroot: "R", tags: [tags[0], { ...tags[1], name: "slg_14" }] })).toBe(400);  // the same tag
    expect(await bad({ deck: "Step 1", units: UNITS, tagroot: "R", tags: [{ id: "t1", name: "Empty" }] })).toBe(400);  // holds nothing
    expect(await bad({ deck: "Step 1", units: UNITS, tagroot: "R", tags: [{ ...tags[0], text: "card text" }] })).toBe(400);
    expect(await bad({ deck: "Step 1", units: UNITS, tagroot: "R", tags: Array.from({ length: 101 }, (_, i) => ({ id: `t${i}`, name: `T${i}`, tags: ["A"] })) })).toBe(400);
    // their notes count with the plan's other picks (50,000)
    const big = (i: number) => ({ id: `b${i}`, name: `B${i}`, notes: Array.from({ length: 5000 }, (_, j) => `g${i}-${j}`) });
    expect(await bad({ deck: "Step 1", units: UNITS, tagroot: "R", tags: Array.from({ length: 11 }, (_, i) => big(i)) })).toBe(400);
  });

  it("a plan's root is its own: another plan's, any case, makes _2 with its dates following; a save never moves it; a copy gets its own", async () => {
    const { dre, maya, p } = await plan();
    const first = await dre.call("POST", `/plans/${p.id}/tags`, { name: "SLG 12", add: ["g1"] });
    expect(first.body.doc.tagroot).toBe("MS2_Block_1");
    // Maya's own plan of the same name, from the site: the builder asks for the same root
    const mine = await maya.call("POST", "/plans", { name: "ms2 block 1", deck: "Step 1" });
    const doc = { deck: "Step 1", tagroot: "ms2_block_1", tags: [{ id: "t1", name: "SLG 12", tags: ["Step1::Cardio"] }],
      pace: { mode: "placed", days: [1, 1, 1, 1, 1, 1, 1], cover: ["tag:DueCrew::ms2_block_1::SLG_12", "tag:Step1::Cardio"] },
      units: [{ id: "u1", name: "SLG 12 but not Pharm", opens: "2026-10-05", tags: ["DueCrew::ms2_block_1::SLG_12"],
        search: ['"tag:DueCrew::ms2\\_block\\_1::SLG\\_12" -"tag:Step1::Pharm"', "tag:DueCrew::ms2_block_1::SLG_12 is:new"] }] };
    const put = await maya.call("PUT", `/plans/${mine.body.id}`, { version: 1, doc });
    expect(put.status).toBe(200);
    expect(put.body.doc.tagroot).toBe("ms2_block_1_2");
    expect(put.body.doc.units[0].tags).toEqual(["DueCrew::ms2_block_1_2::SLG_12"]);
    expect(put.body.doc.units[0].search).toEqual(['"tag:DueCrew::ms2\\_block\\_1\\_2::SLG\\_12" -"tag:Step1::Pharm"',
      "tag:DueCrew::ms2_block_1_2::SLG_12 is:new"]);
    expect(put.body.doc.pace.cover).toEqual(["tag:DueCrew::ms2_block_1_2::SLG_12", "tag:Step1::Cardio"]);
    // a stale page asking for the old root again: the plan keeps the one it holds
    const again = await maya.call("PUT", `/plans/${mine.body.id}`, { version: put.body.version, doc: { ...doc, units: [{ ...doc.units[0], name: "Renamed" }] } });
    expect(again.body.doc.tagroot).toBe("ms2_block_1_2");
    expect(again.body.doc.units[0].tags).toEqual(["DueCrew::ms2_block_1_2::SLG_12"]);
    // Dre's plan, listed, with a date on its tag; Maya's copy has its own root, its date following
    const withTag = await dre.call("PUT", `/plans/${p.id}`, { version: first.body.version, doc: { ...first.body.doc,
      units: [...UNITS, { id: "s1", name: "SLG 12", opens: "2026-10-06", tags: ["DueCrew::MS2_Block_1::SLG_12"] }] } });
    expect(withTag.status).toBe(200);
    expect((await dre.call("PUT", `/plans/${p.id}/listed`, { listed: true })).status).toBe(200);
    const copy = await maya.call("POST", `/plans/${p.id}/copy`, { start: "2026-11-02" });
    expect(copy.status).toBe(200);
    expect(copy.body.doc.tagroot).toBe("MS2_Block_1_3");
    expect(copy.body.doc.units.find((u: { id: string }) => u.id === "s1").tags).toEqual(["DueCrew::MS2_Block_1_3::SLG_12"]);
    expect(copy.body.doc.tags[0].notes).toEqual(["g1"]);
  });
});
