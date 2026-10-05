import { describe, expect, it } from "vitest";
import * as B from "../src/bingo";
import * as T from "../src/team";
import { db, person } from "./helpers";

// 3.9 a plan's team: opt-in per plan; who showed up today, the streak,
// questions and replies, the team's bingo. Never numbers.

const today = () => new Date().toISOString().slice(0, 10);
const back = (n: number) => new Date(Date.now() - n * 86400000).toISOString().slice(0, 10);

async function setup() {
  const dre = await person("dre");
  const sam = await person("sam");
  const kai = await person("kai");
  const made = (await dre.call("POST", "/plans", { name: "Cardio", deck: "D" })).body;
  const p = (await dre.call("PUT", `/plans/${made.id}`, { version: 1,
    doc: { deck: "D", units: [{ id: "a", name: "A", opens: "2026-10-05", tags: ["X"] }] } })).body;
  for (const x of [sam, kai]) expect((await x.call("POST", "/plans/follow", { code: p.code })).status).toBe(200);
  return { dre, sam, kai, p };
}

describe("a plan's team (3.9)", () => {
  it("is opt-in, for people in the plan; leaving and unfollowing take you off", async () => {
    const { dre, sam, p } = await setup();
    const out = await person("out");
    expect((await out.call("GET", `/plans/${p.id}/team`)).status).toBe(404);
    expect((await out.call("POST", `/plans/${p.id}/team`)).status).toBe(404);
    expect((await sam.call("GET", `/plans/${p.id}/team`)).body).toEqual({ on: false, count: 0 });
    // not on it: no asking
    expect((await sam.call("POST", `/plans/${p.id}/asks`, { text: "hi" })).status).toBe(403);
    const j = (await sam.call("POST", `/plans/${p.id}/team`)).body;
    expect(j).toMatchObject({ on: true, count: 1, shown: 0, faces: [{ uid: "sam", name: "Sam", shown: false }], asks: [] });
    // the author, who doesn't follow, can join too
    expect((await dre.call("POST", `/plans/${p.id}/team`)).body.count).toBe(2);
    expect((await sam.call("DELETE", `/plans/${p.id}/team`)).status).toBe(200);
    expect((await sam.call("GET", `/plans/${p.id}/team`)).body).toEqual({ on: false, count: 1 });
    await sam.call("POST", `/plans/${p.id}/team`);
    await sam.call("DELETE", `/plans/${p.id}/follow`);
    expect((await dre.call("GET", `/plans/${p.id}/team`)).body.count).toBe(1);
  });

  it("showed up rides the sync: only rows I hold, only when it changed", async () => {
    const { sam, kai, p } = await setup();
    // not on the team: the sync writes nothing (an update never joins)
    const r0 = (await sam.call("POST", "/sync", { team: { [p.id]: { day: today() } } })).body;
    expect(r0.wrote.team).toBe(false);
    expect(await db().prepare("SELECT COUNT(*) AS n FROM plan_team").first("n")).toBe(0);
    await sam.call("POST", `/plans/${p.id}/team`);
    await kai.call("POST", `/plans/${p.id}/team`);
    expect((await sam.call("POST", "/sync", { team: { [p.id]: { day: today() } } })).body.wrote.team).toBe(true);
    expect((await sam.call("POST", "/sync", { team: { [p.id]: { day: today() } } })).body.wrote.team).toBe(false);
    const v = (await kai.call("GET", `/plans/${p.id}/team`)).body;
    expect(v.shown).toBe(1);
    expect(v.faces.map((f: any) => [f.uid, f.shown])).toEqual([["sam", true], ["kai", false]]);
    // never a number of anyone's
    expect(JSON.stringify(v)).not.toMatch(/reviews|studyTime|accuracy/);
    // the board carries the counts for the Plan tab
    const b = (await kai.call("GET", "/board")).body;
    expect(b.teams[p.id]).toMatchObject({ shown: 1, of: 2, act: [] });
    expect((await kai.call("GET", "/board?keep=1")).body.teams).toBeUndefined();
    // bad parts
    expect((await sam.call("POST", "/sync", { team: { [p.id]: { day: "nope" } } })).status).toBe(400);
    expect((await sam.call("POST", "/sync", { team: { [p.id]: { day: today(), x: 1 } } })).status).toBe(400);
  });

  it("the streak: days more than half the team showed up", () => {
    const j = "2026-01-01";
    const m = (...days: string[]) => ({ days, joined: j });
    const t = "2026-10-05";
    expect(T.streak([m("2026-10-04", "2026-10-03"), m("2026-10-04", "2026-10-03"), m()], t)).toBe(2);
    expect(T.streak([m("2026-10-05", "2026-10-04"), m("2026-10-05", "2026-10-04"), m()], t)).toBe(2);
    // today under half doesn't end it; a past day under half does
    expect(T.streak([m("2026-10-04", "2026-10-02"), m("2026-10-04", "2026-10-02")], t)).toBe(1);
    // half is not more than half
    expect(T.streak([m("2026-10-04"), m()], t)).toBe(0);
    // someone who joined today doesn't count against yesterday
    expect(T.streak([m("2026-10-04"), { days: [], joined: t }], t)).toBe(1);
  });

  it("questions, replies, helped, removal; muted people's go", async () => {
    const { dre, sam, kai, p } = await setup();
    for (const x of [dre, sam, kai]) await x.call("POST", `/plans/${p.id}/team`);
    const q = (await kai.call("POST", `/plans/${p.id}/asks`, { text: "Does Friday's quiz\ninclude complement?" })).body;
    expect(q.text).toBe("Does Friday's quiz include complement?");
    const card = (await sam.call("POST", `/plans/${p.id}/asks`, { text: "why C5a first?", guid: "g1", ord: 0, topic: "Complement" })).body;
    const rep = (await dre.call("POST", `/plans/${p.id}/asks`, { text: "Both.", parent: q.id })).body;
    expect((await sam.call("POST", `/plans/${p.id}/asks`, { text: "x", parent: rep.id })).status).toBe(404);  // one level
    expect((await sam.call("POST", `/plans/${p.id}/asks`, { text: "x", parent: q.id, guid: "g" })).status).toBe(400);
    expect((await sam.call("POST", `/plans/${p.id}/asks/${rep.id}/helped`, { on: true })).status).toBe(403);  // only the asker
    expect((await kai.call("POST", `/plans/${p.id}/asks/${rep.id}/helped`, { on: true })).status).toBe(200);
    const v = (await sam.call("GET", `/plans/${p.id}/team`)).body;
    expect(v.asks.map((a: any) => a.id)).toEqual([q.id, card.id]);  // the reply moved it up
    expect(v.asks[0]).toMatchObject({ name: "Kai", mine: false, remove: false,
      replies: [{ name: "Dre", text: "Both.", helped: true, author: true }] });
    expect(v.asks[1]).toMatchObject({ guid: "g1", ord: 0, topic: "Complement", mine: true, remove: true });
    // the board: activity times and the latest question from someone else
    expect((await sam.call("GET", "/board")).body.teams[p.id]).toMatchObject({ last: { name: "Kai" } });
    // sam mutes kai: kai's question goes from sam's view
    await sam.call("PUT", "/settings", { v: 1, at: "2026-10-05T00:00:00.000000Z", settings: { muted: ["kai"] } });
    expect((await sam.call("GET", `/plans/${p.id}/team`)).body.asks.map((a: any) => a.id)).toEqual([card.id]);
    // removal: not someone else's (unless an author), and a question takes its replies
    expect((await sam.call("DELETE", `/plans/${p.id}/asks/${q.id}`)).status).toBe(403);
    expect((await dre.call("DELETE", `/plans/${p.id}/asks/${q.id}`)).status).toBe(200);
    expect(await db().prepare("SELECT COUNT(*) AS n FROM plan_asks WHERE parent = ?").bind(q.id).first("n")).toBe(0);
    // ten new questions a day each
    for (let i = 0; i < 9; i++) await sam.call("POST", `/plans/${p.id}/asks`, { text: `q${i}` });
    expect((await sam.call("POST", `/plans/${p.id}/asks`, { text: "one more" })).status).toBe(429);
  });

  it("the team's bingo: the week's squares, the team's middle, counts never who", async () => {
    const { sam, kai, p } = await setup();
    for (const x of [sam, kai]) await x.call("POST", `/plans/${p.id}/team`);
    const wk = B.isoWeek(new Date());
    const n = B.wkNum(wk);
    await sam.call("POST", "/sync", { team: { [p.id]: { day: today(), play: { wk: n, s: 1 } } } });
    const v = (await kai.call("GET", `/plans/${p.id}/team?wk=${wk}`)).body;
    expect(v.bingo.card.wk).toBe(wk);
    expect(v.bingo.card.middle.group).toBe("team");
    expect(v.bingo.card.squares).toEqual((await B.cardFor((await import("cloudflare:workers")).env as any, wk)).squares);
    expect(v.bingo.ev.squares[0].n).toBe(1);
    expect(JSON.stringify(v.bingo.ev)).not.toMatch(/sam|kai/);
    // no week, no card
    expect((await kai.call("GET", `/plans/${p.id}/team`)).body.bingo).toBeUndefined();
    // the middle, by turn
    expect(T.teamMiddle("2026-W41", 8).goal).toBe([3, 5, 4][B.wkNum("2026-W41") % 3]);
  });

  it("goes with the plan and with an account; is in my data", async () => {
    const { dre, sam, kai, p } = await setup();
    for (const x of [sam, kai]) await x.call("POST", `/plans/${p.id}/team`);
    const q = (await sam.call("POST", `/plans/${p.id}/asks`, { text: "mine" })).body;
    await kai.call("POST", `/plans/${p.id}/asks`, { text: "answer", parent: q.id });
    const data = await sam.call("GET", "/account/data");
    expect(data.body.teamQuestionsAndAnswers[0]).toMatchObject({ plan: "Cardio", answer: false, text: "mine" });
    expect(data.body.teams[0].plan).toBe("Cardio");
    expect((await sam.call("DELETE", "/account")).status).toBe(200);
    expect(await db().prepare("SELECT COUNT(*) AS n FROM plan_asks").first("n")).toBe(0);  // kai's answer went with the thread
    expect(await db().prepare("SELECT COUNT(*) AS n FROM plan_team WHERE uid = 'sam'").first("n")).toBe(0);
    await kai.call("POST", `/plans/${p.id}/asks`, { text: "again" });
    expect((await dre.call("DELETE", `/plans/${p.id}`)).status).toBe(200);
    expect(await db().prepare("SELECT COUNT(*) AS n FROM plan_asks").first("n")).toBe(0);
    expect(await db().prepare("SELECT COUNT(*) AS n FROM plan_team").first("n")).toBe(0);
    void back;
  });
});
