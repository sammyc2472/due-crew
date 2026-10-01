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
    expect(await maya.status("GET", `/plans/${p.id}/progress`)).toBe(200);  // the counts are the authors'
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

describe("3.3: a class through Step (C1–C5)", () => {
  it("C2: open early is mine, 0 to 7 days, and rides the board", async () => {
    const { dre, p } = await plan();
    const nia = await person("nia");
    await nia.call("POST", "/plans/follow", { code: p.code });
    expect(await nia.status("PATCH", `/plans/${p.id}/follow`, { early: 9 })).toBe(400);
    expect((await nia.call("PATCH", `/plans/${p.id}/follow`, { early: 2 })).body.early).toBe(2);
    const b = await nia.call("GET", "/board?decks=1");
    expect(b.body.plans[0].early).toBe(2);
    expect(b.body.authored).toEqual([]);  // she writes none
    const mine = await dre.call("GET", "/board?decks=1");
    expect(mine.body.authored.map((a: any) => a.id)).toEqual([p.id]);
  });

  it("C3: a date can hold Anki searches; Anki adds one with its count", async () => {
    const { dre, p } = await plan();
    const q = "tag:*Cardio* tag:*#V&B* -tag:*Pharm*";
    const put = await dre.call("PUT", `/plans/${p.id}`, { version: p.version,
      doc: { deck: "Step 1", units: [{ ...UNITS[0], search: [q, q] }, UNITS[1]] } });
    expect(put.body.doc.units[0].search).toEqual([q]);
    expect(await dre.status("PUT", `/plans/${p.id}`, { version: put.body.version,
      doc: { deck: "Step 1", units: [{ ...UNITS[0], search: ["a\nb"] }] } })).toBe(400);
    const added = await dre.call("POST", `/plans/${p.id}/cards`, { search: "tag:L14", n: 212, unit: "arr" });
    const arr = added.body.doc.units.find((u: any) => u.id === "arr");
    expect(arr.search).toEqual(["tag:L14"]);
    expect(arr.sn).toEqual({ "tag:L14": 212 });
  });

  it("C4: review days point at dates that exist", async () => {
    const { dre, p } = await plan();
    const put = (reviews: unknown) => dre.status("PUT", `/plans/${p.id}`, { version: p.version, doc: { deck: "Step 1", units: UNITS, reviews } });
    expect(await put([{ day: "2026-10-19", from: "hf", to: "nope" }])).toBe(400);
    expect(await put([{ day: "2026-10-19", from: "hf", to: "arr" }])).toBe(200);
  });

  it("C5: an author's Anki keeps the note ids behind a date, only while its tags are the same", async () => {
    const { dre, maya, p } = await plan();
    expect(await maya.status("PUT", `/plans/${p.id}/ids`, { units: {} })).toBe(403);
    const r = await dre.call("PUT", `/plans/${p.id}/ids`, { units: {
      hf: [UNITS[0].tags, [], ["g1", "g2"]],
      arr: [["Old::tag"], [], ["g3"]],  // read from tags it no longer has: ignored
    } });
    expect(r.body.version).toBe(p.version + 1);
    const got = await dre.call("GET", `/plans/${p.id}`);
    expect(got.body.doc.units.map((u: any) => u.ids)).toEqual([["g1", "g2"], undefined]);
    const again = await dre.call("PUT", `/plans/${p.id}/ids`, { units: { hf: [UNITS[0].tags, [], ["g1", "g2"]] } });
    expect(again.body.version).toBe(p.version + 1);  // unchanged: nothing written
  });

  it("the list of my plans leaves out single cards and note ids, keeps the rest in order", async () => {
    const { dre, maya, p } = await plan();
    const units = [{ ...UNITS[1], cards: [["gA", 0]], n: 40 }, { ...UNITS[0], search: ["tag:x"] }];
    const put = await dre.call("PUT", `/plans/${p.id}`, { version: p.version, doc: { deck: "Step 1", end: "2026-12-01", units } });
    await dre.call("PUT", `/plans/${p.id}/ids`, { units: { hf: [UNITS[0].tags, [], ["g1"]] } });
    await dre.call("POST", `/plans/${p.id}/editors`, { uid: maya.uid });
    await maya.call("POST", "/plans/follow", { code: p.code });
    const [row] = (await maya.call("GET", "/plans/mine")).body.plans;
    expect(row.doc).toEqual({ deck: "Step 1", end: "2026-12-01", units: [
      { id: "hf", name: "Heart failure", opens: "2026-10-05", tags: UNITS[0].tags, decks: [], search: ["tag:x"] },
      { id: "arr", name: "Arrhythmia", opens: "2026-10-06", tags: UNITS[1].tags, decks: [], n: 40 }] });
    expect(row).toMatchObject({ role: "editor", followers: 1, ownerName: "Dre", code: p.code,
      editors: [{ uid: "maya", name: "Maya", emoji: "" }], following: { share: true, paused: false, early: 0 } });
    expect(put.body.version).toBeGreaterThan(p.version);
    expect((await dre.call("GET", `/plans/${p.id}`)).body.doc.units[1].cards).toEqual([["gA", 0]]);  // the plan itself keeps them
  });

  it("3.4, D1: a pasted search's count comes from the author's Anki; the plans I write carry their searches", async () => {
    const { dre, p } = await plan();
    const q = "tag:*Cardio* -tag:*Pharm*";
    const put = await dre.call("PUT", `/plans/${p.id}`, { version: p.version, doc: { deck: "Step 1", units: [UNITS[0], { ...UNITS[1], search: [q] }] } });
    const b = await dre.call("GET", "/board?decks=1");
    expect(b.body.authored[0].doc).toEqual({ deck: "Step 1", units: [
      { id: "hf", tags: UNITS[0].tags, decks: [], opens: "2026-10-05" }, { id: "arr", tags: UNITS[1].tags, decks: [], search: [q], opens: "2026-10-06" }] });
    const r = await dre.call("PUT", `/plans/${p.id}/ids`, { units: {}, counts: { arr: { [q]: 212, "tag:gone": 5 }, nope: { x: 1 } } });
    expect(r.body.version).toBe(put.body.version + 1);
    const got = await dre.call("GET", `/plans/${p.id}`);
    expect(got.body.doc.units.find((u: any) => u.id === "arr").sn).toEqual({ [q]: 212 });
  });
});

describe("3.4, D2: the plan as a calendar", () => {
  it("each date and review day as an all-day event, escaped and folded; no sign-in; a squad plan has none", async () => {
    const { dre, p } = await plan();
    const long = "Lecture 14, Arrhythmias; the long one with a very long name that goes past seventy-five octets ñ";
    await dre.call("PUT", `/plans/${p.id}`, { version: p.version, doc: { deck: "Step 1",
      units: [{ ...UNITS[0], n: 61, name: long.slice(0, 60) }, { ...UNITS[1], opens: "2026-10-06", due: "2026-10-08", even: true, tags: ["x"] }],
      reviews: [{ day: "2026-10-09", from: "hf", to: "arr" }] } });
    const { env } = await import("cloudflare:workers");
    const worker = (await import("../src/index")).default;
    const res = await worker.fetch(new Request(`https://api.duecrew.com/plans/ics?code=${p.code.toLowerCase()}`), { ...env } as any);
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toContain("text/calendar");
    const text = await res.text();
    expect(text.startsWith("BEGIN:VCALENDAR\r\n")).toBe(true);
    const unfolded = text.replace(/\r\n /g, "");
    expect(unfolded).toContain("SUMMARY:Lecture 14\\, Arrhythmias\\; the long one with a very long name · 61 new");
    expect(unfolded).toContain("DTSTART;VALUE=DATE:20261006\r\nDTEND;VALUE=DATE:20261009");  // evenly to the 8th
    expect(unfolded).toContain("SUMMARY:Review · Lecture 14");
    expect(text.split("\r\n").every((l) => new TextEncoder().encode(l).length <= 75)).toBe(true);
    expect(text).not.toContain("Dre");  // nobody's name
    const none = await worker.fetch(new Request("https://api.duecrew.com/plans/ics?code=NOPE2345"), { ...env } as any);
    expect(none.status).toBe(404);
    const sq = await dre.call("POST", "/squads", { name: "Busm" });
    await dre.call("PUT", `/plans/${p.id}`, { version: p.version + 1, audience: "squad", squad: sq.body.id });
    const squad = await worker.fetch(new Request(`https://api.duecrew.com/plans/ics?code=${p.code}`), { ...env } as any);
    expect(squad.status).toBe(404);
  });

  it("a follower of a plan anyone with the code can follow sees its code; a stranger doesn't", async () => {
    const { p } = await plan();
    const nia = await person("nia");
    expect((await nia.call("GET", `/plans/peek?code=${p.code}`)).body.code).toBeUndefined();
    await nia.call("POST", "/plans/follow", { code: p.code });
    expect((await nia.call("GET", `/plans/${p.id}`)).body.code).toBe(p.code);
  });
});
