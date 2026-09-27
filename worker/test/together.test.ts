import { describe, expect, it } from "vitest";
import { befriend, db, person } from "./helpers";

const UNITS = [
  { id: "hf", name: "Heart failure", opens: "2026-10-05", tags: ["Step1::Cardio::Heart_failure"] },
  { id: "arr", name: "Arrhythmia", opens: "2026-10-06", tags: ["Step1::Cardio::Arrhythmia"] },
];

async function plan() {
  const dre = await person("dre");
  const maya = await person("maya");
  await befriend(dre, maya);
  await befriend(maya, dre);
  const made = await dre.call("POST", "/plans", { name: "Block 1", deck: "Step 1" });
  const put = await dre.call("PUT", `/plans/${made.body.id}`, { version: 1, doc: { deck: "Step 1", units: UNITS }, summary: "laid out week 1" });
  expect(put.status).toBe(200);
  return { dre, maya, p: put.body };
}

describe("3.3: plans together", () => {
  it("a co-author comes from the owner's crew, edits, sees the code, and can't take the plan", async () => {
    const { dre, maya, p } = await plan();
    const kai = await person("kai");
    expect(await dre.status("POST", `/plans/${p.id}/editors`, { uid: kai.uid })).toBe(403);  // not crew
    expect(await maya.status("POST", `/plans/${p.id}/editors`, { uid: maya.uid })).toBe(403);  // only the owner adds
    const added = await dre.call("POST", `/plans/${p.id}/editors`, { uid: maya.uid });
    expect(added.body.editors).toEqual([{ uid: "maya", name: "Maya", emoji: "" }]);
    const mine = await maya.call("GET", "/plans/mine");
    expect(mine.body.plans.map((x: any) => [x.id, x.role])).toEqual([[p.id, "editor"]]);
    const seen = await maya.call("GET", `/plans/${p.id}`);
    expect(seen.body.role).toBe("editor");
    expect(seen.body.code).toBe(p.code);
    const doc = { deck: "Step 1", units: [UNITS[0], { ...UNITS[1], opens: "2026-10-07" }] };
    expect((await maya.call("PUT", `/plans/${p.id}`, { version: p.version, doc, summary: "moved Arrhythmia to Wed" })).status).toBe(200);
    expect(await maya.status("PUT", `/plans/${p.id}`, { version: p.version + 1, audience: "squad" })).toBe(403);
    expect(await maya.status("DELETE", `/plans/${p.id}`)).toBe(403);
    // she leaves; then she's a stranger to it again
    expect(await maya.status("DELETE", `/plans/${p.id}/editors/maya`)).toBe(200);
    expect(await maya.status("GET", `/plans/${p.id}`)).toBe(404);
  });

  it("history: each save with who and what; the latest one undoes", async () => {
    const { dre, maya, p } = await plan();
    await dre.call("POST", `/plans/${p.id}/editors`, { uid: maya.uid });
    const moved = await maya.call("PUT", `/plans/${p.id}`, { version: p.version, summary: "moved Arrhythmia to Wed",
      doc: { deck: "Step 1", units: [UNITS[0], { ...UNITS[1], opens: "2026-10-07" }] } });
    const log = await dre.call("GET", `/plans/${p.id}/log`);
    expect(log.body.log.map((l: any) => [l.name, l.summary, l.undo])).toEqual([
      ["Maya", "moved Arrhythmia to Wed", true], ["Dre", "laid out week 1", false]]);
    expect(await dre.status("POST", `/plans/${p.id}/undo`, { version: p.version })).toBe(409);  // not the latest
    const undone = await dre.call("POST", `/plans/${p.id}/undo`, { version: moved.body.version });
    expect(undone.status).toBe(200);
    expect(undone.body.doc.units[1].opens).toBe("2026-10-06");
    const after = await dre.call("GET", `/plans/${p.id}/log`);
    expect(after.body.log[0]).toMatchObject({ name: "Dre", summary: "undid: moved Arrhythmia to Wed", undo: true });
    expect(await (await person("kai")).status("GET", `/plans/${p.id}/log`)).toBe(403);
  });

  it("notes on a day: authors and followers, removed by their writer or an author", async () => {
    const { dre, maya, p } = await plan();
    const nia = await person("nia");
    expect(await nia.status("POST", `/plans/${p.id}/notes`, { day: "2026-10-05", text: "hi" })).toBe(404);  // not in it
    expect((await nia.call("POST", "/plans/follow", { code: p.code })).status).toBe(200);
    const n1 = await nia.call("POST", `/plans/${p.id}/notes`, { day: "2026-10-06", text: "  Lab day,\nkeep it light  " });
    expect(n1.body.text).toBe("Lab day, keep it light");
    expect(await nia.status("POST", `/plans/${p.id}/notes`, { day: "Tuesday", text: "x" })).toBe(400);
    await dre.call("POST", `/plans/${p.id}/notes`, { day: "2026-10-06", text: "Agreed" });
    const got = await nia.call("GET", `/plans/${p.id}/notes`);
    expect(got.body.notes.map((x: any) => [x.name, x.text, x.mine, x.remove])).toEqual([
      ["Nia", "Lab day, keep it light", true, true], ["Dre", "Agreed", false, false]]);
    // a follower can't take down the author's note; the author can take down anyone's
    await nia.call("DELETE", `/plans/${p.id}/notes/${got.body.notes[1].id}`);
    expect((await nia.call("GET", `/plans/${p.id}/notes`)).body.notes.length).toBe(2);
    await dre.call("DELETE", `/plans/${p.id}/notes/${got.body.notes[0].id}`);
    expect((await dre.call("GET", `/plans/${p.id}/notes`)).body.notes.map((x: any) => x.text)).toEqual(["Agreed"]);
    expect(await maya.status("GET", `/plans/${p.id}/notes`)).toBe(404);  // crew, but not in the plan
  });

  it("deleting the plan, or an account, takes its co-authors, notes and history", async () => {
    const { dre, maya, p } = await plan();
    await dre.call("POST", `/plans/${p.id}/editors`, { uid: maya.uid });
    await maya.call("POST", `/plans/${p.id}/notes`, { day: "2026-10-05", text: "Mine" });
    expect(await maya.status("DELETE", "/account")).toBe(200);
    expect(await db().prepare("SELECT COUNT(*) AS n FROM plan_editors").first("n")).toBe(0);
    expect(await db().prepare("SELECT COUNT(*) AS n FROM plan_notes").first("n")).toBe(0);
    expect(await dre.status("DELETE", `/plans/${p.id}`)).toBe(200);
    expect(await db().prepare("SELECT COUNT(*) AS n FROM plan_log").first("n")).toBe(0);
  });
});
