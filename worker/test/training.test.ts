// 3.2: schedules, phases and checkpoints, who knows this, tips, the log, admin counts.
import { describe, expect, it } from "vitest";
import { WEEK, api, befriend, db, person } from "./helpers";

const SCHED = { days: [1, 1, 1, 1, 1, 2, 0], minutes: 90 };

let authors = 0;
async function planWith(doc: Record<string, unknown>) {
  const dre = await person(`dre${authors++}`);
  const made = await dre.call("POST", "/plans", { name: "Step 1", deck: "Step 1" });
  const put = await dre.call("PUT", `/plans/${made.body.id}`, { version: 1, doc: { deck: "Step 1", ...doc } });
  return { dre, put };
}

async function crew() {
  const sam = await person("sam");
  const dre = await person("dre");
  const mo = await person("mo");
  const stranger = await person("zed");
  for (const [a, b] of [[sam, dre], [dre, sam], [sam, mo], [mo, sam]] as const) await befriend(a, b);
  await befriend(stranger, sam);  // one way only
  return { sam, dre, mo, stranger };
}

describe("plans: phases and checkpoints", () => {
  it("keeps an end date, phases and a unit's checkpoint", async () => {
    const { put } = await planWith({
      end: "2026-12-20", phases: { catchup: 4, taper: 10 },
      units: [{ id: "c", name: "Cardio", opens: "2026-10-05", due: "2026-10-20", check: "2026-10-24", tags: ["Cardio"] }],
    });
    expect(put.status).toBe(200);
    expect(put.body.doc.end).toBe("2026-12-20");
    expect(put.body.doc.phases).toEqual({ catchup: 4, taper: 10 });
    expect(put.body.doc.units[0].check).toBe("2026-10-24");
  });

  it("refuses a taper without an end, a catch-up every week, and a checkpoint before its date opens", async () => {
    const u = { id: "c", name: "Cardio", opens: "2026-10-05", tags: ["Cardio"] };
    expect((await planWith({ phases: { taper: 7 }, units: [u] })).put.status).toBe(400);
    expect((await planWith({ end: "2026-12-20", phases: { catchup: 1 }, units: [u] })).put.status).toBe(400);
    expect((await planWith({ units: [{ ...u, check: "2026-10-01" }] })).put.status).toBe(400);
  });

  it("no phases at all is left out of the doc", async () => {
    const { put } = await planWith({ phases: { catchup: 0, taper: 0 }, units: [] });
    expect(put.body.doc.phases).toBeUndefined();
  });
});

describe("plans: my schedule", () => {
  it("rides the follow, the patch, the board and the plan's view; only mine", async () => {
    const { dre, put } = await planWith({ units: [] });
    const maya = await person("maya");
    const f = await maya.call("POST", "/plans/follow", { code: put.body.code, sched: SCHED });
    expect(f.status).toBe(200);
    expect(f.body.following.sched).toEqual(SCHED);
    const later = { ...SCHED, start: "2026-10-12" };
    const p = await maya.call("PATCH", `/plans/${put.body.id}/follow`, { sched: later });
    expect(p.body.sched).toEqual(later);
    const b = await maya.call("GET", "/board?decks=1");
    expect(b.body.plans[0].sched).toEqual(later);
    // following again without a schedule keeps the one I set
    await maya.call("POST", "/plans/follow", { code: put.body.code });
    expect((await maya.call("GET", `/plans/${put.body.id}`)).body.following.sched).toEqual(later);
    // the author sees no one's schedule
    expect(JSON.stringify((await dre.call("GET", `/plans/${put.body.id}`)).body)).not.toContain("minutes");
    // and it can go
    expect((await maya.call("PATCH", `/plans/${put.body.id}/follow`, { sched: null })).body.sched).toBeNull();
  });

  it("refuses a week with no study day, silly minutes, or extra keys", async () => {
    const { put } = await planWith({ units: [] });
    const maya = await person("maya");
    await maya.call("POST", "/plans/follow", { code: put.body.code });
    for (const sched of [{ days: [0, 0, 0, 0, 0, 0, 0], minutes: 60 }, { days: [1, 1], minutes: 60 },
      { days: [1, 1, 1, 1, 1, 1, 3], minutes: 60 }, { ...SCHED, minutes: 5 }, { ...SCHED, extra: 1 }]) {
      expect(await maya.status("PATCH", `/plans/${put.body.id}/follow`, { sched })).toBe(400);
    }
  });
});

describe("who knows this", () => {
  it("answers a stuck card with the mutual friends who know it, and keeps nothing about the ask", async () => {
    const { sam, dre, mo, stranger } = await crew();
    expect((await dre.call("POST", "/sync", { knows: { reset: true, add: ["g1", "g2"] } })).body.wrote.knows).toBe(true);
    await mo.call("POST", "/sync", { knows: { add: ["g1"] } });
    await stranger.call("POST", "/sync", { knows: { add: ["g1"] } });
    const r = await sam.call("POST", "/sync", { stuck: ["g1", "g3"] });
    expect(r.status).toBe(200);
    expect(r.body.cards.g1.knows.sort()).toEqual(["dre", "mo"]);  // not zed: they added me, I didn't add them
    expect(r.body.cards.g3).toBeUndefined();
    // and one way only doesn't count: zed asking learns nothing from me
    await sam.call("POST", "/sync", { knows: { add: ["g9"] } });
    expect((await stranger.call("POST", "/sync", { stuck: ["g9"] })).body.cards).toEqual({});
    const rows = await db().prepare("SELECT COUNT(*) AS n FROM knows").first<number>("n");
    expect(rows).toBe(5);  // dre 2, mo 1, zed 1, sam 1: the asks left nothing
  });

  it("del and reset take cards off", async () => {
    const { sam, dre } = await crew();
    await dre.call("POST", "/sync", { knows: { add: ["g1", "g2"] } });
    await dre.call("POST", "/sync", { knows: { del: ["g1"] } });
    expect((await sam.call("POST", "/sync", { stuck: ["g1", "g2"] })).body.cards).toEqual({ g2: { knows: ["dre"], tips: [] } });
    await dre.call("POST", "/sync", { knows: { reset: true, add: [] } });
    expect((await sam.call("POST", "/sync", { stuck: ["g2"] })).body.cards).toEqual({});
  });

  it("holds many cards in one sync, and refuses too many", async () => {
    const { sam, dre } = await crew();
    const many = Array.from({ length: 2000 }, (_, i) => `g${i}`);
    expect((await dre.call("POST", "/sync", { knows: { reset: true, add: many } })).status).toBe(200);
    const stuck = many.slice(0, 300);
    const r = await sam.call("POST", "/sync", { stuck });
    expect(Object.keys(r.body.cards)).toHaveLength(300);
    expect(await dre.status("POST", "/sync", { knows: { add: [...many, "x"] } })).toBe(400);
    expect(await sam.status("POST", "/sync", { stuck: [...stuck, "x"] })).toBe(400);
  });

  it("keeps at most 100,000 a person: past it new ones aren't taken, and one out lets one in", async () => {
    const { sam, dre } = await crew();
    await db().prepare(`WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c WHERE x < 100000)
      INSERT INTO knows (uid, guid) SELECT 'dre', 'k' || x FROM c`).run();
    expect((await dre.call("POST", "/sync", { knows: { add: ["new1"] } })).status).toBe(200);
    expect((await sam.call("POST", "/sync", { stuck: ["new1"] })).body.cards).toEqual({});
    await dre.call("POST", "/sync", { knows: { del: ["k1"], add: ["new2"] } });
    expect((await sam.call("POST", "/sync", { stuck: ["new2"] })).body.cards).toEqual({ new2: { knows: ["dre"], tips: [] } });
  });
});

describe("tips stay on the card", () => {
  it("a person keeps at most 5,000 tips; one already kept still changes", async () => {
    const { sam, dre } = await crew();
    await db().prepare(`WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c WHERE x < 5000)
      INSERT INTO tips (guid, uid, text, at) SELECT 't' || x, 'dre', 'old', 0 FROM c`).run();
    expect(await dre.status("POST", "/cheers/sam", { emoji: "💡", note: "one more", guid: "fresh" })).toBe(200);  // the cheer still goes
    expect(await db().prepare("SELECT COUNT(*) AS n FROM tips WHERE guid = 'fresh'").first<number>("n")).toBe(0);
    await dre.call("POST", "/cheers/sam", { emoji: "💡", note: "better", guid: "t1" });
    expect(await db().prepare("SELECT text FROM tips WHERE guid = 't1' AND uid = 'dre'").first<string>("text")).toBe("better");
  });


  it("a tip with words is kept, shown to mutual friends stuck on it, the most helpful first", async () => {
    const { sam, dre, mo } = await crew();
    await befriend(dre, mo);
    await befriend(mo, dre);
    const priya = await person("priya");
    for (const [a, b] of [[sam, priya], [priya, sam]] as const) await befriend(a, b);
    await sam.call("POST", "/sync", { week: { ...WEEK("2026-10-22"), tricky: [{ guid: "g1", deck: "Step 1", at: "2026-10-22", q: "Trick?" }] } });
    const w = await dre.call("GET", "/board");
    expect(w.body.friends.find((f: any) => f.uid === "sam").week.tricky[0].q).toBe("Trick?");
    expect((await dre.call("POST", "/cheers/sam", { emoji: "💡", note: "Loop of Henle", guid: "g1" })).status).toBe(200);
    expect((await mo.call("POST", "/cheers/sam", { emoji: "💡", note: "NKCC2 = loops", guid: "g1" })).status).toBe(200);
    // the flag came down at the first tip
    expect((await dre.call("GET", "/board")).body.friends.find((f: any) => f.uid === "sam").week.tricky).toBeUndefined();
    // priya is stuck on it too, and sees mo's and dre's tips (both her mutual? only sam is)
    expect((await priya.call("POST", "/sync", { stuck: ["g1"] })).body.cards).toEqual({});
    // mo marks dre's tip helpful; sam sees dre's first
    expect(await mo.status("POST", "/tips/helped", { guid: "g1", from: "dre" })).toBe(200);
    const r = await sam.call("POST", "/sync", { stuck: ["g1"] });
    expect(r.body.cards.g1.tips.map((t: any) => t.from)).toEqual(["dre", "mo"]);
    expect(r.body.cards.g1.tips[0]).toMatchObject({ text: "Loop of Henle", helped: false });
    expect(JSON.stringify(r.body)).not.toMatch(/"n"|count/);  // no counts, ever
    await sam.call("POST", "/tips/helped", { guid: "g1", from: "mo" });
    await sam.call("POST", "/tips/helped", { guid: "g1", from: "mo" });  // twice is once
    const again = await sam.call("POST", "/sync", { stuck: ["g1"] });
    expect(again.body.cards.g1.tips.find((t: any) => t.from === "mo").helped).toBe(true);
    await sam.call("POST", "/tips/helped", { guid: "g1", from: "mo", helped: false });
    const off = await sam.call("POST", "/sync", { stuck: ["g1"] });
    expect(off.body.cards.g1.tips.find((t: any) => t.from === "mo").helped).toBe(false);
  });

  it("a cheer without words, or without a card, isn't a tip; helped needs a mutual friend's tip", async () => {
    const { sam, dre, stranger } = await crew();
    await dre.call("POST", "/cheers/sam", { emoji: "🔥" });
    await dre.call("POST", "/cheers/sam", { emoji: "💡", guid: "g1" });
    expect(await db().prepare("SELECT COUNT(*) AS n FROM tips").first<number>("n")).toBe(0);
    await stranger.call("POST", "/cheers/sam", { emoji: "💡", note: "hi", guid: "g1" });
    expect(await sam.status("POST", "/tips/helped", { guid: "g1", from: "zed" })).toBe(404);
    expect(await sam.status("POST", "/tips/helped", { guid: "g1", from: "dre" })).toBe(404);
  });

  it("leaving the crew hides a tip; deleting the account takes it", async () => {
    const { sam, dre } = await crew();
    await dre.call("POST", "/cheers/sam", { emoji: "💡", note: "Loop", guid: "g1" });
    await dre.call("POST", "/sync", { knows: { add: ["g1"] } });
    await dre.call("DELETE", "/friends/sam");
    expect((await sam.call("POST", "/sync", { stuck: ["g1"] })).body.cards).toEqual({});
    expect(await dre.status("DELETE", "/account")).toBe(200);
    for (const t of ["tips", "knows", "tip_helped"]) {
      expect(await db().prepare(`SELECT COUNT(*) AS n FROM ${t}`).first<number>("n")).toBe(0);
    }
  });
});

describe("the site's home", () => {
  it("keep=1 shows the cheers waiting and leaves them for Anki", async () => {
    const { sam, dre } = await crew();
    await dre.call("POST", "/cheers/sam", { emoji: "🔥", note: "go" });
    const site = await sam.call("GET", "/board?keep=1");
    expect(site.body.cheers.map((c: any) => c.from)).toEqual(["dre"]);
    const anki = await sam.call("GET", "/board");
    expect(anki.body.cheers.map((c: any) => c.from)).toEqual(["dre"]);  // still there for Anki
    expect((await sam.call("GET", "/board")).body.cheers).toEqual([]);
    // the site's home has its decks, and reads its plans elsewhere (/plans/mine)
    const home = await sam.call("GET", "/board?keep=1&decks=1");
    expect(home.body.decks).toBeDefined();
    expect(home.body.plans).toBeUndefined();
  });

  it("my plan view carries my own progress, and nobody else's", async () => {
    const { put, dre } = await planWith({ units: [{ id: "a", name: "A", opens: "2026-10-05", tags: ["A"] }] });
    const maya = await person("maya");
    await maya.call("POST", "/plans/follow", { code: put.body.code });
    await maya.call("POST", "/sync", { plans: { [put.body.id]: { a: [3, 2, 5] } } });
    expect((await maya.call("GET", `/plans/${put.body.id}`)).body.following.progress).toEqual({ a: [3, 2, 5] });
    expect((await dre.call("GET", `/plans/${put.body.id}`)).body.following).toBeUndefined();
  });
});

describe("the log", () => {
  it("merges days, writes only what changed, and is mine alone", async () => {
    const sam = await person("sam");
    const a = await sam.call("POST", "/sync", { log: { days: { "2026-10-21": [80, 300, 50, 89.46], "2026-10-22": [60, 200, 40, null] } } });
    expect(a.body.wrote.log).toBe(true);
    const b = await sam.call("POST", "/sync", { log: { days: { "2026-10-22": [60, 200, 40, null] } } });
    expect(b.body.wrote.log).toBe(false);
    await sam.call("POST", "/sync", { log: { days: { "2026-10-23": [90, 320, 52, 91] } } });
    const got = await sam.call("GET", "/log");
    expect(got.body.days).toEqual({
      "2026-10-21": [80, 300, 50, 89.5], "2026-10-22": [60, 200, 40, null], "2026-10-23": [90, 320, 52, 91],
    });
    const dre = await person("dre");
    expect((await dre.call("GET", "/log")).body.days).toEqual({});
  });

  it("3.7.1: keeps years of it, a year a sync, and says so (logAll)", async () => {
    const sam = await person("sam");
    const day = (n: number) => new Date(Date.UTC(2026, 9, 1) - n * 86400000).toISOString().slice(0, 10);
    for (let y = 0; y < 4; y++) {
      const days = Object.fromEntries(Array.from({ length: 366 }, (_, i) => [day(y * 366 + i), [10, 50, 5, null]]));
      const r = await sam.call("POST", "/sync", { log: { days } });
      expect(r.status).toBe(200);
      expect(r.body.logAll).toBe(true);
    }
    expect(Object.keys((await sam.call("GET", "/log")).body.days).length).toBe(4 * 366);
  });

  it("3.7.1: cheers my crew sent me, a sender once a day, mine alone, gone with my account", async () => {
    const sam = await person("sam");
    const dre = await person("dre");
    const maya = await person("maya");
    await befriend(sam, dre);
    await befriend(sam, maya);
    for (const p of [dre, dre, maya]) expect((await p.call("POST", "/cheers/sam", { emoji: "🎉" })).status).toBe(200);
    await dre.call("POST", "/cheers/sam", { emoji: "🎉", note: "a tip", guid: "g1" });  // a tip isn't a cheer
    const year = String(new Date().getUTCFullYear());
    expect((await sam.call("GET", "/log")).body.cheers).toEqual({ [year]: 2 });
    expect((await dre.call("GET", "/log")).body.cheers).toEqual({});
    await sam.call("DELETE", "/account");
    expect(await db().prepare("SELECT COUNT(*) AS n FROM cheer_counts").first("n")).toBe(0);
  });

  it("refuses a bad row", async () => {
    const sam = await person("sam");
    for (const days of [{ "2026-10-21": [80, 300, 50] }, { "x": [1, 1, 1, null] }, { "2026-10-21": [2000, 1, 1, null] },
      { "2026-10-21": [1, 1, 1, 101] }]) {
      expect(await sam.status("POST", "/sync", { log: { days } })).toBe(400);
    }
  });
});

describe("admin counts", () => {
  it("only for ADMIN_UIDS, counts only", async () => {
    const { sam } = await crew();
    const env = { ADMIN_UIDS: "sam" };
    expect((await api("GET", "/admin/stats", { token: (await person("x1")).token, env })).status).toBe(404);
    expect((await api("GET", "/admin/stats", { token: sam.token })).status).toBe(404);
    const r = await api("GET", "/admin/stats", { token: sam.token, env });
    expect(r.status).toBe(200);
    expect(r.body).toMatchObject({ accounts: 5, mutualPairs: 2, friendEdges: 5 });
    expect(JSON.stringify(r.body)).not.toMatch(/@|dre|sam/);
  });
});

describe("the week's 3.2 extras", () => {
  it("carries a recap, and it never goes to Firestore", async () => {
    const { outbound } = await import("../src/bridge");
    const { sam, dre } = await crew();
    const recap = { name: "Step 1", n: 3, day: "2026-10-26" };
    expect(await sam.status("POST", "/sync", { week: { ...WEEK("2026-10-26"), recap } })).toBe(200);
    expect((await dre.call("GET", "/board")).body.friends.find((f: any) => f.uid === "sam").week.recap).toEqual(recap);
    const doc = await db().prepare("SELECT doc FROM weeks WHERE uid = 'sam'").first<string>("doc");
    expect(outbound(doc!, 1)).not.toHaveProperty("recap");
    expect(await sam.status("POST", "/sync", { week: { ...WEEK("2026-10-26"), recap: { name: "", n: 0, day: "x" } } })).toBe(400);
  });
});

describe("3.2.1: the admin's notice", () => {
  it("only an admin posts; the board carries the newest live one for my version", async () => {
    const sam = await person("sam");
    const maya = await person("maya");
    const env = { ADMIN_UIDS: "sam" };
    const post = (who: { token: string }, body: unknown) => api("POST", "/admin/notices", { token: who.token, body, env });
    expect((await post(maya, { text: "hi" })).status).toBe(404);
    expect((await post(sam, { text: "Update to 3.2", link: "http://x.com" })).status).toBe(400);
    expect((await post(sam, { text: "  " })).status).toBe(400);
    const all = await post(sam, { text: "New:   plans on duecrew.com", link: "https://duecrew.com/plans" });
    expect(all.status).toBe(200);
    expect(all.body.text).toBe("New: plans on duecrew.com");
    const board = async (who: { token: string }) => (await api("GET", "/board", { token: who.token, env })).body.notice;
    expect(await board(maya)).toEqual({ id: all.body.id, text: "New: plans on duecrew.com", link: "https://duecrew.com/plans" });
    // one for older add-ons only: 3.1 sees it, 3.2.1 doesn't
    const upd = await post(sam, { text: "Please update", below: "3.2.1" });
    await maya.call("POST", "/sync", { profile: { clientVersion: "3.1.1" } });
    expect((await board(maya)).text).toBe("Please update");
    await sam.call("POST", "/sync", { profile: { clientVersion: "3.2.1" } });
    expect((await board(sam)).text).toBe("New: plans on duecrew.com");
    // taken down
    expect((await api("DELETE", `/admin/notices/${upd.body.id}`, { token: sam.token, env })).status).toBe(200);
    expect((await board(maya)).text).toBe("New: plans on duecrew.com");
    expect((await api("GET", "/admin/notices", { token: sam.token, env })).body.notices).toHaveLength(1);
    expect((await api("GET", "/auth/me", { token: sam.token, env })).body.admin).toBe(true);
    expect((await api("GET", "/auth/me", { token: maya.token, env })).body.admin).toBeUndefined();
  });

  it("versions compare as numbers", async () => {
    const { older } = await import("../src/notices");
    expect(older("3.1.10", "3.2")).toBe(true);
    expect(older("3.2.1", "3.2.1")).toBe(false);
    expect(older("3.10.0", "3.9.9")).toBe(false);
  });
});

describe("3.7.1: your data, and names to people you're connected to", () => {
  it("D5: a name for a uid only to someone connected (crew either way, a squad), else no_user", async () => {
    const sam = await person("sam");
    const dre = await person("dre");
    const eve = await person("eve");
    expect(await eve.status("GET", "/users/sam")).toBe(404);
    expect((await sam.call("GET", "/users/sam")).body.name).toBe("Sam");
    await sam.call("PUT", "/friends/dre", {});  // one edge is enough, both ways
    expect((await dre.call("GET", "/users/sam")).body.name).toBe("Sam");
    expect((await sam.call("GET", "/users/dre")).body.name).toBe("Dre");
    const sq = (await sam.call("POST", "/squads", { name: "Night owls" })).body;
    const peek = (await eve.call("GET", `/squads/peek?code=${sq.code}`)).body;
    expect(peek.founderName).toBe("Sam");  // the code carries the founder's name
    expect(await eve.status("GET", "/users/sam")).toBe(404);
    expect(await eve.status("POST", `/squads/${sq.id}/join`, { code: sq.code })).toBe(200);
    expect((await eve.call("GET", "/users/sam")).body.name).toBe("Sam");
  });

  it("D2: Delete my log keeps nothing older than 8 days and tells the add-on its import is done", async () => {
    const sam = await person("sam");
    const day = (n: number) => new Date(Date.now() - n * 86400000).toISOString().slice(0, 10);
    const old = Object.fromEntries(Array.from({ length: 40 }, (_, i) => [day(i), [10, 50, 5, null]]));
    await sam.call("POST", "/sync", { log: { days: old } });
    expect((await sam.call("POST", "/sync", { log: { days: { [day(1)]: [1, 1, 1, null] } } })).body.logCut).toBeUndefined();
    expect((await sam.call("GET", "/log?summary=1")).body).toEqual({ n: 40, first: day(39) });
    expect((await sam.call("DELETE", "/log")).status).toBe(200);
    expect((await sam.call("GET", "/log")).body.days).toEqual({});
    const r = await sam.call("POST", "/sync", { log: { days: old } });
    expect(r.body.logCut).toBe(true);
    expect(Object.keys((await sam.call("GET", "/log")).body.days).sort()).toEqual(Array.from({ length: 9 }, (_, i) => day(8 - i)));
  });

  it("D2: Delete my to-dos empties them under a newer save; the board says when", async () => {
    const sam = await person("sam");
    const at = "2026-10-01T10:00:00.000000Z";
    await sam.call("PUT", "/settings", { v: 1, at, settings: { due_items: [{ id: "a", t: "read ch 4" }], due_ticks: { a: "2026-10-01" }, accent: "teal" } });
    expect((await sam.call("GET", "/board")).body.settingsAt).toBe(at);
    expect((await sam.call("DELETE", "/account/todos")).status).toBe(200);
    const s = (await sam.call("GET", "/settings")).body;
    expect(s.settings).toEqual({ due_items: [], due_ticks: {}, accent: "teal" });
    expect(s.at > at).toBe(true);
    expect((await sam.call("GET", "/board")).body.settingsAt).toBe(s.at);
  });

  it("D2: Download is mine, whole, and names no one's email but mine", async () => {
    const sam = await person("sam");
    const dre = await person("dre");
    await befriend(sam, dre);
    await befriend(dre, sam);
    await sam.call("POST", "/sync", { log: { days: { "2026-10-01": [10, 50, 5, null] } } });
    const r = await sam.call("GET", "/account/data");
    expect(r.status).toBe(200);
    expect(r.body.you.name).toBe("Sam");
    expect(r.body.crew).toEqual([expect.objectContaining({ name: "Dre", mutual: true })]);
    expect(r.body.log.days["2026-10-01"]).toBeTruthy();
    expect(JSON.stringify(r.body)).not.toMatch(/dre@|token_hash/);
  });
});
