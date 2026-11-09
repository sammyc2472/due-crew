// 3.9.9: a save refused at one of a plan's ceilings says which, and the
// numbers (plans.ts over/sizeOver, roomFor): still bad_plan, plans_full or
// too_big as before, so an older client keeps its words; a doc whose shape is
// wrong is plain bad_plan. The add-on (remote.py LIMIT_WORDS) and the site
// (Ceilings in builder.js) say each in words.
import { env } from "cloudflare:workers";
import { describe, expect, it } from "vitest";
import worker from "../src/index";
import { PLAN_BYTES_MAX, ownerBytes } from "../src/plans";
import { db, person } from "./helpers";

const DOC_MAX = 1536 * 1024;
const day = (n: number) => new Date(Date.UTC(2026, 9, 5 + n)).toISOString().slice(0, 10);
const set = (i: number, extra: Record<string, unknown> = {}) =>
  ({ id: `u${i}`, name: `Set ${i}`, opens: day(i % 300), tags: [], decks: [], cards: [], ...extra });

async function authored() {
  const dre = await person("dre");
  const made = await dre.call("POST", "/plans", { name: "Step 1", deck: "Step 1" });
  expect(made.status).toBe(200);
  const put = (doc: Record<string, unknown>, version = made.body.version) =>
    dre.call("PUT", `/plans/${made.body.id}`, { version, doc: { deck: "Step 1", ...doc } });
  return { dre, id: made.body.id as string, version: made.body.version as number, put };
}

describe("a save refused at a ceiling says which, and the numbers", () => {
  it("sets, events, review days, tags: the count it would make and the ceiling", async () => {
    const { put } = await authored();
    const sets = await put({ units: Array.from({ length: 214 }, (_, i) => set(i)) });
    expect([sets.status, sets.body]).toEqual([400, { error: "bad_plan", limit: "sets", have: 214, max: 200 }]);
    const events = await put({ units: [set(0)], events: Array.from({ length: 203 }, (_, i) => ({ id: `e${i}`, day: day(i), name: `Quiz ${i}` })) });
    expect([events.status, events.body]).toEqual([400, { error: "bad_plan", limit: "events", have: 203, max: 200 }]);
    const reviews = await put({ units: [set(0), set(1)], reviews: Array.from({ length: 61 }, (_, i) => ({ day: day(i + 2), from: "u0", to: "u1" })) });
    expect([reviews.status, reviews.body]).toEqual([400, { error: "bad_plan", limit: "reviews", have: 61, max: 60 }]);
    const tags = await put({ units: [set(0)], tagroot: "Step_1", tags: Array.from({ length: 104 }, (_, i) => ({ id: `t${i}`, name: `SLG ${i}`, notes: [`n${i}`] })) });
    expect([tags.status, tags.body]).toEqual([400, { error: "bad_plan", limit: "tags", have: 104, max: 100 }]);
    // at the ceiling is fine
    expect((await put({ units: Array.from({ length: 200 }, (_, i) => set(i)) })).status).toBe(200);
  });

  it("picked cards and IDs: every set's single cards, IDs and notes, and the plan tags' notes and cards, each once", async () => {
    const { put } = await authored();
    const cards = Array.from({ length: 40_000 }, (_, i) => [`g${i}`, 0]);
    const doc = {
      units: [
        set(0, { cards: [...cards, ["g1", 0], ["g2", 0]] }),  // the two again count once, as they're kept
        set(1, { nids: Array.from({ length: 5000 }, (_, i) => i + 1) }),
        set(2, { notes: Array.from({ length: 5000 }, (_, i) => `n${i}`), cids: [7, 7, 8] }),
      ],
      tagroot: "Step_1", tags: [{ id: "t1", name: "SLG 12", notes: ["a", "b", "a"], cards: [["c", 1], ["c", 1], ["c", 2]] }],
    };
    const r = await put(doc);
    // 40,000 + 5,000 + 5,000 + 2 + 2 notes + 2 cards
    expect([r.status, r.body]).toEqual([400, { error: "bad_plan", limit: "cards", have: 50_006, max: 50_000 }]);
  });

  it("ids: a date's note ids (from the author's Anki), or its pasted ids' cards, in all", async () => {
    const { put } = await authored();
    const guids = (n: number, p: string) => Array.from({ length: n }, (_, i) => `${p}${i}`);
    const ids = await put({ units: [set(0, { ids: guids(30_000, "a") }), set(1, { ids: guids(20_001, "b") })] });
    expect([ids.status, ids.body]).toEqual([400, { error: "bad_plan", limit: "ids", have: 50_001, max: 50_000 }]);
    const refs = (n: number) => Array.from({ length: n }, (_, i) => [`r${i}`, 0]);
    const idr = await put({ units: [0, 1, 2].map((i) => set(i, { nids: [i + 1], idr: refs(i < 2 ? 20_000 : 10_001) })) });
    expect([idr.status, idr.body]).toEqual([400, { error: "bad_plan", limit: "ids", have: 50_001, max: 50_000 }]);
  });

  it("size: the doc as kept, as JSON, past 1,536 KB", async () => {
    const { put } = await authored();
    // fifty long tags a set: what's kept is what's sent here (every set has its lists), so its JSON is the count
    const units: Record<string, unknown>[] = [];
    const doc = { deck: "Step 1", units };
    for (let i = 0; JSON.stringify(doc).length <= DOC_MAX + 20_000; i++) {
      units.push(set(i, { tags: Array.from({ length: 50 }, (_, j) => `Big::${"x".repeat(180)}::${i}_${j}`) }));
    }
    const have = JSON.stringify(doc).length;
    expect(have).toBeLessThan(1600 * 1024 - 1000);  // under what the API reads at all: planDoc's own ceiling says it
    const r = await put({ units });
    expect([r.status, r.body]).toEqual([400, { error: "bad_plan", limit: "size", have, max: DOC_MAX }]);
  });

  it("too_big: a save past what the API reads says the bytes it is, as the plan's size; anything else as before", async () => {
    const { dre, id, version } = await authored();
    const body = JSON.stringify({ version, doc: { deck: "Step 1", units: [set(0, { tags: ["x".repeat(150)] })] }, summary: "y".repeat(1_700_000) });
    const send = (path: string, method = "PUT") => worker.fetch(new Request(`https://api.duecrew.com${path}`, {
      method, body, headers: { authorization: `Bearer ${dre.token}`, "content-type": "application/json", "content-length": String(body.length) } }), { ...env } as any);
    const r = await send(`/plans/${id}`);
    expect([r.status, await r.json()]).toEqual([413, { error: "too_big", limit: "size", have: body.length, max: DOC_MAX }]);
    for (const [path, method] of [["/plans/trees", "PUT"], [`/plans/${id}/ids`, "PUT"], ["/sync", "POST"]]) {
      const x = await send(path, method);
      expect([path, x.status, await x.json()]).toEqual([path, 413, { error: "too_big" }]);
    }
  });

  it("plans_full: what the account's plans hold now, and the ceiling", async () => {
    const { dre, id, version, put } = await authored();
    const now = Math.floor(Date.now() / 1000);
    let left = PLAN_BYTES_MAX - 200 - (await ownerBytes(env, "dre"));
    const rows = [];
    for (let i = 0; left > 0; i++) {
      const n = Math.min(1024 * 1024, left);
      rows.push(db().prepare("INSERT INTO plans (id, code, owner, name, doc, created_at, updated_at) VALUES (?, ?, 'dre', 'F', ?, ?, ?)")
        .bind(`fill${String(i).padStart(12, "0")}`, `F${String(i).padStart(7, "0")}`, "x".repeat(n), now, now));
      left -= n;
    }
    await db().batch(rows);
    const held = await ownerBytes(env, "dre");
    const r = await put({ units: Array.from({ length: 5 }, (_, i) => set(i)) }, version);
    expect([r.status, r.body]).toEqual([409, { error: "plans_full", limit: "total", have: held, max: PLAN_BYTES_MAX }]);
    expect(await dre.status("GET", `/plans/${id}`)).toBe(200);
  });

  it("a doc whose shape is wrong is plain bad_plan, with no limit", async () => {
    const { put } = await authored();
    for (const doc of [
      { units: "all of them" },
      { units: [{ id: "a", name: "A", opens: "2026-10-05", due: "2026-10-01" }] },  // due before it opens
      { units: [set(0, { text: "card text" })] },
      { units: [set(0), set(0)] },  // the same id twice
      { units: [set(0)], events: "quiz" },
      { units: [set(0)], reviews: [{ day: day(3), from: "u0", to: "gone" }] },
      { units: [set(0)], tags: [{ id: "t1", name: "Empty" }], tagroot: "Step_1" },  // a tag holds something
      { units: [set(0, { nids: Array.from({ length: 5001 }, (_, i) => i + 1) })] },  // one date's pasted ids: its own shape, not the plan's
    ]) {
      const r = await put(doc as Record<string, unknown>);
      expect([JSON.stringify(doc).slice(0, 60), r.status, r.body]).toEqual([JSON.stringify(doc).slice(0, 60), 400, { error: "bad_plan" }]);
    }
  });
});
