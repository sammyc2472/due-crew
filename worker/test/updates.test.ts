import { describe, expect, it } from "vitest";
import { anHourOn, befriend, db, person } from "./helpers";

// 3.7.3 plan updates: the plans ride a refresh when their stamp moved; authors
// post to followers (with a save or on their own); the authors see how many
// followers' Anki has the latest version.

async function setup() {
  const dre = await person("dre");
  const sam = await person("sam");
  const made = (await dre.call("POST", "/plans", { name: "Cardio", deck: "D" })).body;
  const p = (await dre.call("PUT", `/plans/${made.id}`, { version: 1,
    doc: { deck: "D", units: [{ id: "a", name: "A", opens: "2026-10-05", tags: ["X"] }] } })).body;
  expect((await sam.call("POST", "/plans/follow", { code: p.code })).status).toBe(200);
  return { dre, sam, p };
}

const doc = (n: number) => ({ deck: "D", units: Array.from({ length: n }, (_, i) => ({ id: `u${i}`, name: `U${i}`, opens: "2026-10-05", tags: [`T${i}`] })) });

describe("plan updates (3.7.3)", () => {
  it("a refresh carries the plans only when their stamp moved", async () => {
    const { dre, sam, p } = await setup();
    const first = (await sam.call("GET", "/board?pv=")).body;
    expect(first.plans.map((x: any) => x.id)).toEqual([p.id]);
    expect(first.pv).toMatch(/^[0-9a-f]{16}$/);
    const same = (await sam.call("GET", `/board?pv=${first.pv}`)).body;
    expect(same.plans).toBeUndefined();
    expect(same.pv).toBe(first.pv);
    // my progress moves at every sync: not a change
    await sam.call("POST", "/sync", { plans: { [p.id]: { a: [1, 1, 3] } } });
    expect((await sam.call("GET", `/board?pv=${first.pv}`)).body.plans).toBeUndefined();
    // the author saves: the next refresh brings it
    await dre.call("PUT", `/plans/${p.id}`, { version: p.version, doc: doc(2) });
    const moved = (await sam.call("GET", `/board?pv=${first.pv}`)).body;
    expect(moved.pv).not.toBe(first.pv);
    expect(moved.plans[0].version).toBe(p.version + 1);
    // my own days changed on the site: also a change
    await sam.call("PATCH", `/plans/${p.id}/follow`, { shift: 2 });
    expect((await sam.call("GET", `/board?pv=${moved.pv}`)).body.plans[0].shift).toBe(2);
    // without pv (older add-ons) or on the site's home (keep=1): as before
    expect((await sam.call("GET", "/board")).body.plans).toBeUndefined();
    expect((await sam.call("GET", "/board?keep=1&pv=")).body.plans).toBeUndefined();
  });

  it("3.8.0: how a plan's cards open is mine: on its dates, when I'm ready, or the next once I've seen the last", async () => {
    const { dre, sam, p } = await setup();
    const kai = await person("kai");
    // chosen at Follow
    const f = await kai.call("POST", "/plans/follow", { code: p.code, own: "ready" });
    expect(f.status).toBe(200);
    expect(f.body.following.own).toBe("ready");
    expect(await kai.status("POST", "/plans/follow", { code: p.code, own: "whenever" })).toBe(400);
    // changed later; the refresh's stamp moves so every computer hears it
    const first = (await sam.call("GET", "/board?pv=")).body;
    expect(first.plans[0].own).toBeUndefined();  // on the plan's dates: nothing to say
    const set = await sam.call("PATCH", `/plans/${p.id}/follow`, { own: "next" });
    expect(set.body.own).toBe("next");
    const moved = (await sam.call("GET", `/board?pv=${first.pv}`)).body;
    expect(moved.plans[0].own).toBe("next");
    expect((await sam.call("GET", `/plans/${p.id}`)).body.following.own).toBe("next");
    expect(await sam.status("PATCH", `/plans/${p.id}/follow`, { own: "fast" })).toBe(400);
    // back to the plan's dates
    expect((await sam.call("PATCH", `/plans/${p.id}/follow`, { own: null })).body.own).toBeUndefined();
    // mine only: the author sees nothing of it
    expect(JSON.stringify((await dre.call("GET", `/plans/${p.id}/progress`)).body)).not.toContain("ready");
  });

  it("authors post; followers read; a post can ride a save; ceilings", async () => {
    const { dre, sam, p } = await setup();
    expect((await sam.call("POST", `/plans/${p.id}/posts`, { text: "hi" })).status).toBe(403);
    const r = await dre.call("POST", `/plans/${p.id}/posts`, { text: "Quiz moved to Friday.\nSame material." });
    expect(r.status).toBe(200);
    expect(r.body.text).toBe("Quiz moved to Friday. Same material.");
    const saved = await dre.call("PUT", `/plans/${p.id}`, { version: p.version, doc: doc(3), post: "Added week 2." });
    expect(saved.status).toBe(200);
    expect(saved.body.posted.text).toBe("Added week 2.");
    const list = (await sam.call("GET", `/plans/${p.id}/posts`)).body.posts;
    expect(list.map((x: any) => [x.text, x.withSave, x.remove])).toEqual([["Added week 2.", true, false], ["Quiz moved to Friday. Same material.", false, false]]);
    const board = (await sam.call("GET", "/board?pv=")).body;
    expect(board.plans[0].posts.map((x: any) => x.text)).toEqual(["Added week 2.", "Quiz moved to Friday. Same material."]);
    expect(board.plans[0].posts[0]).toMatchObject({ name: "Dre", withSave: true });
    // a new post moves the stamp
    await dre.call("POST", `/plans/${p.id}/posts`, { text: "Three" });
    expect((await sam.call("GET", `/board?pv=${board.pv}`)).body.plans[0].posts[0].text).toBe("Three");
    // five a day per plan; a save past it still saves, and says so
    await dre.call("POST", `/plans/${p.id}/posts`, { text: "Four" });
    await dre.call("POST", `/plans/${p.id}/posts`, { text: "Five" });
    expect((await dre.call("POST", `/plans/${p.id}/posts`, { text: "Six" })).status).toBe(429);
    const v = (await dre.call("GET", `/plans/${p.id}`)).body.version;
    const over = await dre.call("PUT", `/plans/${p.id}`, { version: v, doc: doc(4), post: "Seven" });
    expect(over.status).toBe(200);
    expect(over.body.version).toBe(v + 1);
    expect(over.body.posted).toEqual({ error: "too_many_posts" });
    // only the newest few ride the board
    expect((await sam.call("GET", "/board?pv=")).body.plans[0].posts).toHaveLength(3);
    // a bad post fails the save before anything is written
    expect((await dre.call("PUT", `/plans/${p.id}`, { version: v + 1, doc: doc(5), post: "   " })).status).toBe(400);
    expect((await dre.call("GET", `/plans/${p.id}`)).body.version).toBe(v + 1);
    // the owner removes a post
    const id = list[0].id;
    expect((await dre.call("DELETE", `/plans/${p.id}/posts/${id}`)).status).toBe(200);
    expect((await sam.call("GET", `/plans/${p.id}/posts`)).body.posts.some((x: any) => x.id === id)).toBe(false);
  });

  it("reached N of M: followers whose Anki has the latest version, for the authors only", async () => {
    const { dre, sam, p } = await setup();
    const kai = await person("kai");
    await kai.call("POST", "/plans/follow", { code: p.code });
    await dre.call("POST", "/plans/follow", { code: p.code });  // the author following their own plan isn't counted
    // the counts are the plan's totals, up to an hour old (migration 0025): an hour on, they're counted again
    await anHourOn();
    expect((await dre.call("GET", `/plans/${p.id}`)).body.reached).toEqual([0, 2]);
    await sam.call("GET", "/board?pv=");
    await anHourOn();
    expect((await dre.call("GET", `/plans/${p.id}`)).body.reached).toEqual([1, 2]);
    expect((await sam.call("GET", `/plans/${p.id}`)).body.reached).toBeUndefined();
    await dre.call("PUT", `/plans/${p.id}`, { version: p.version, doc: doc(2) });
    // a save moves the version: none have it, at once, without counting again
    expect((await dre.call("GET", `/plans/${p.id}`)).body.reached).toEqual([0, 2]);
    // the site's home doesn't count: it isn't Anki
    await kai.call("GET", "/board?keep=1");
    await anHourOn();
    expect((await dre.call("GET", `/plans/${p.id}`)).body.reached).toEqual([0, 2]);
  });

  it("posts reach the site's feed, Your data, and go with the plan or the account", async () => {
    const { dre, sam, p } = await setup();
    await befriend(sam, dre);
    await dre.call("POST", `/plans/${p.id}/posts`, { text: "Week 2 is up" });
    const feed = (await sam.call("GET", "/board?keep=1&feed=1")).body.feed;
    expect(feed.find((x: any) => x.kind === "post")).toMatchObject({ name: "Dre", text: "Week 2 is up", planName: "Cardio" });
    expect((await dre.call("GET", "/account/data")).body.planPosts.map((x: any) => x.text)).toEqual(["Week 2 is up"]);
    await dre.call("DELETE", `/plans/${p.id}`);
    expect(await db().prepare("SELECT COUNT(*) AS n FROM plan_posts").first("n")).toBe(0);
    const again = await setup2(dre, sam);
    await dre.call("POST", `/plans/${again}/posts`, { text: "x" });
    expect((await dre.call("DELETE", "/account")).status).toBe(200);
    expect(await db().prepare("SELECT COUNT(*) AS n FROM plan_posts WHERE uid = 'dre'").first("n")).toBe(0);
  });
});

async function setup2(dre: any, sam: any) {
  const made = (await dre.call("POST", "/plans", { name: "Pulm", deck: "D" })).body;
  const p = (await dre.call("PUT", `/plans/${made.id}`, { version: 1, doc: doc(1) })).body;
  await sam.call("POST", "/plans/follow", { code: p.code });
  return p.id as string;
}
