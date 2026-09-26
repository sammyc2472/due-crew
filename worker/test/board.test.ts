import { beforeEach, describe, expect, it } from "vitest";
import { WEEK, befriend, db, person } from "./helpers";

type P = Awaited<ReturnType<typeof person>>;
let sam: P, dre: P, nia: P;
const TODAY = "2026-09-26";

beforeEach(async () => {
  [sam, dre, nia] = await Promise.all(["sam", "dre", "nia"].map((u) => person(u)));
  await befriend(sam, dre);
  await befriend(dre, sam);
  await befriend(sam, nia);  // Nia hasn't added Sam back
});

const writes = async () => (await db().prepare("SELECT COUNT(*) AS n FROM weeks").first<number>("n"));

describe("GET /board", () => {
  it("me, my crew with their weeks, pending people by name only", async () => {
    await dre.call("POST", "/sync", { week: WEEK(TODAY, 42), profile: { emoji: "🐢" } });
    await nia.call("POST", "/sync", { week: WEEK(TODAY, 7) });
    await sam.call("POST", "/sync", { week: WEEK(TODAY, 100) });
    const b = (await sam.call("GET", "/board")).body;
    expect(b.me.uid).toBe("sam");
    expect(b.me.week.days[TODAY].reviews).toBe(100);
    expect(b.me.updatedAt).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/);
    const dreRow = b.friends.find((f: any) => f.uid === "dre");
    expect(dreRow).toMatchObject({ name: "Dre", emoji: "🐢", mutual: true });
    expect(dreRow.week.days[TODAY].reviews).toBe(42);
    expect(b.friends.find((f: any) => f.uid === "nia")).toEqual({ uid: "nia", name: "Nia", emoji: "", mutual: false });
    expect(b.cheers).toEqual([]);
    expect(b.knocks).toEqual([]);
    expect(b.decks).toBeUndefined();
  });

  it("cheers are delivered once, from the crew only, with the sender's real name", async () => {
    await dre.call("POST", "/cheers/sam", { emoji: "🎉", note: "go  go\ngo", luck: true, guid: "g1" });
    await db().prepare("INSERT INTO cheers (to_uid, from_uid, emoji, at) VALUES ('sam', 'nia', '🔥', 1)").run();
    const first = (await sam.call("GET", "/board")).body.cheers;
    expect(first).toHaveLength(1);
    expect(first[0]).toMatchObject({ from: "dre", name: "Dre", emoji: "🎉", note: "go go go", luck: true, guid: "g1" });
    expect((await sam.call("GET", "/board")).body.cheers).toEqual([]);
    expect(await db().prepare("SELECT COUNT(*) AS n FROM cheers").first("n")).toBe(0);  // the stray went too
  });

  it("a new cheer overwrites the last one from the same person, words and all", async () => {
    await dre.call("POST", "/cheers/sam", { emoji: "🎉", note: "first", guid: "g1" });
    await dre.call("POST", "/cheers/sam", { emoji: "🔥" });
    const c = (await sam.call("GET", "/board")).body.cheers;
    expect(c).toHaveLength(1);
    expect(c[0]).toMatchObject({ emoji: "🔥", note: "", guid: "", luck: false });
  });

  it("decks come along when asked, mine and my crew's only", async () => {
    const deck = { name: "AnKing", sig: ["a", "b"], total: 100, seen: 40, mature: 10 };
    for (const p of [sam, dre, nia]) await p.call("POST", "/sync", { decks: [deck] });
    const b = (await sam.call("GET", "/board?decks=1")).body;
    expect(Object.keys(b.decks).sort()).toEqual(["dre", "sam"]);
    expect((await sam.call("GET", "/decks")).body.decks.dre[0]).toMatchObject({ name: "AnKing", seen: 40 });
  });

  it("knocks ride the board", async () => {
    await db().prepare("INSERT INTO codes VALUES ('SAM123', 'sam')").run();
    const zed = await person("zed");
    await zed.call("POST", "/codes/SAM123/add");
    expect((await sam.call("GET", "/board")).body.knocks).toEqual([{ from: "zed", name: "Zed", emoji: "", squad: "" }]);
    await sam.call("PUT", "/friends/zed");  // adding back clears it
    expect((await sam.call("GET", "/board")).body.knocks).toEqual([]);
  });
});

describe("POST /sync", () => {
  it("an unchanged part is not written again", async () => {
    const body = { profile: { name: "Sammy", tz: -240, rollover: 4, clientVersion: "3.0.0" }, week: WEEK(TODAY),
                   decks: [], heatmap: { counts: { [TODAY]: 3 } } };
    const a = (await sam.call("POST", "/sync", body)).body.wrote;
    expect(a).toEqual({ profile: true, week: true, decks: true, heatmap: true });
    const stamp = await db().prepare("SELECT updated_at FROM weeks WHERE uid = 'sam'").first("updated_at");
    const b = (await sam.call("POST", "/sync", body)).body.wrote;
    expect(b).toEqual({ profile: false, week: false, decks: false, heatmap: false });
    expect(await db().prepare("SELECT updated_at FROM weeks WHERE uid = 'sam'").first("updated_at")).toBe(stamp);
    expect(await writes()).toBe(1);
  });

  it("null takes the heatmap down", async () => {
    await sam.call("POST", "/sync", { heatmap: { counts: { [TODAY]: 3 } } });
    expect((await sam.call("POST", "/sync", { heatmap: null })).body.wrote.heatmap).toBe(true);
    expect((await dre.call("GET", "/heatmap/sam")).body.counts).toBeNull();
  });

  it("a flagged card is its guid, deck and day: the text never reaches the server", async () => {
    const week = { ...WEEK(TODAY), tricky: [{ guid: "Ab3$kQ", text: "The capital of Kentucky is […]", deck: "Geo", at: TODAY }] };
    expect((await sam.call("POST", "/sync", { week })).status).toBe(200);
    const stored = await db().prepare("SELECT doc FROM weeks WHERE uid = 'sam'").first<string>("doc");
    expect(stored).not.toContain("Kentucky");
    expect(JSON.parse(stored!).tricky).toEqual([{ guid: "Ab3$kQ", deck: "Geo", at: TODAY }]);
  });

  it("the week's shape is checked, and a bad part writes nothing at all", async () => {
    const bads = [
      { days: { nope: {} } },
      { days: { [TODAY]: { reviews: -1 } } },
      { days: { [TODAY]: { accuracy: 101 } } },
      { days: { [TODAY]: { status: "x".repeat(81) } } },
      { days: { [TODAY]: { secret: 1 } } },
      { examDate: "soon" },
      { awayFrom: TODAY },
      { tricky: new Array(4).fill({ guid: "g", at: TODAY }) },
      { room: { host: "sam", start: "2026-09-26T18:00:00Z", rounds: 9, round: 25, brk: 5 } },
      { extra: true },
    ];
    for (const w of bads) {
      const r = await sam.call("POST", "/sync", { profile: { name: "Changed" }, week: { v: 1, ...w } });
      expect(r.status, JSON.stringify(w)).toBe(400);
    }
    expect(await db().prepare("SELECT name FROM users WHERE uid = 'sam'").first("name")).toBe("Sam");
    expect(await writes()).toBe(0);
  });

  it("a room and studying-now ride the week", async () => {
    const room = { host: "sam", start: "2026-09-26T18:00:00Z", rounds: 4, round: 25, brk: 5 };
    await sam.call("POST", "/sync", { week: { ...WEEK(TODAY), room, liveUntil: "2026-09-26T19:00:00Z" } });
    const w = (await dre.call("GET", "/board")).body.friends[0].week;
    expect(w.room).toEqual(room);
    expect(w.liveUntil).toBe("2026-09-26T19:00:00Z");
  });

  it("unknown parts are refused", async () => {
    expect((await sam.call("POST", "/sync", { friends: ["x"] })).status).toBe(400);
  });

  it("squad rows update, never insert, and say which squads I'm out of", async () => {
    const sq = (await sam.call("POST", "/squads", { name: "busm" })).body;
    const row = { name: "Sam", day: TODAY, reviews: 5, newCards: 2 };
    const a = (await sam.call("POST", "/sync", { squads: { row, ids: [sq.id, "f".repeat(24)] } })).body;
    expect(a.gone).toEqual(["f".repeat(24)]);
    expect(a.wrote.squads).toBe(true);
    expect((await sam.call("POST", "/sync", { squads: { row, ids: [sq.id] } })).body.wrote.squads).toBe(false);
    const got = (await sam.call("GET", `/squads/${sq.id}`)).body.rows[0];
    expect(got).toMatchObject({ uid: "sam", reviews: 5, newCards: 2, studyTimeMs: null });
    // show-up mode: a numbers-free row clears the numbers that stood
    await sam.call("POST", "/sync", { squads: { row: { name: "Sam", day: TODAY, week: 3 }, ids: [sq.id] } });
    expect((await sam.call("GET", `/squads/${sq.id}`)).body.rows[0]).toMatchObject({ reviews: null, week: 3 });
  });
});

describe("friends and codes", () => {
  it("add by code: errors say what happened", async () => {
    await db().prepare("INSERT INTO codes VALUES ('SAM123', 'sam'), ('DRE123', 'dre')").run();
    expect((await sam.call("POST", "/codes/SAM123/add")).body.error).toBe("own_code");
    expect((await sam.call("POST", "/codes/DRE123/add")).body.error).toBe("already");
    expect((await sam.call("POST", "/codes/ZZZZZZ/add")).body.error).toBe("no_match");
    const back = await nia.call("POST", "/codes/sam123/add");  // typed in lower case
    expect(back.body).toMatchObject({ uid: "sam", mutual: true, knocked: false });
  });

  it("a code is claimed once; a new one retires the old", async () => {
    const a = (await sam.call("POST", "/codes")).body.code;
    expect(a).toMatch(/^[A-Z0-9]{6}$/);
    const b = (await sam.call("POST", "/codes")).body.code;
    expect(b).not.toBe(a);
    expect(await db().prepare("SELECT code FROM codes WHERE uid = 'sam'").all().then((r) => r.results)).toEqual([{ code: b }]);
    expect((await sam.call("GET", "/board")).body.me.code).toBe(b);
    expect((await sam.call("POST", "/codes", { code: b })).body.code).toBe(b);  // asking for mine: no change
  });

  it("thirty code tries an hour", async () => {
    for (let i = 0; i < 30; i++) await dre.call("POST", `/codes/Q${String(i).padStart(5, "0")}/add`);
    expect((await dre.call("POST", "/codes/ZZZZZZ/add")).status).toBe(429);
  });

  it("the first 3.0 sync re-adds the crew by uid: add-only, unknown uids skipped", async () => {
    const r = await nia.call("PUT", "/friends", { ids: ["sam", "dre", "ghost", "nia", "sam"] });
    expect(r.body.added).toEqual(["dre", "sam"]);
    expect((await sam.call("GET", "/board")).body.friends.find((f: any) => f.uid === "nia").mutual).toBe(true);
    expect((await nia.call("PUT", "/friends", { ids: "sam" })).status).toBe(400);
  });

  it("GET /friends: the dialog's view, and it consumes nothing", async () => {
    await dre.call("POST", "/cheers/sam", { emoji: "🎉" });
    const f = (await sam.call("GET", "/friends")).body;
    expect(f.friends).toEqual([
      { uid: "dre", name: "Dre", emoji: "", mutual: true },
      { uid: "nia", name: "Nia", emoji: "", mutual: false },
    ]);
    expect(f.knocks).toEqual([]);
    expect((await sam.call("GET", "/board")).body.cheers).toHaveLength(1);  // still there
  });

  it("adding someone who doesn't exist, or myself, is refused", async () => {
    expect((await sam.call("PUT", "/friends/ghost")).status).toBe(404);
    expect((await sam.call("PUT", "/friends/sam")).status).toBe(400);
  });
});

describe("squads", () => {
  it("create hands back a code whose peek finds it, however it's typed", async () => {
    const sq = (await sam.call("POST", "/squads", { name: "  busm  study " })).body;
    expect(sq.name).toBe("busm study");
    expect(sq.code).toMatch(/^[A-HJ-NP-Z2-9]{8}$/);
    const typed = sq.code.toLowerCase().replace(/(.{4})/, "$1-");
    expect((await dre.call("GET", `/squads/peek?code=${typed}`)).body.id).toBe(sq.id);
    expect((await dre.call("GET", "/squads/peek?code=AAAAAAAA")).status).toBe(404);
  });

  it("the id is 2.x's: sha1 of the code, so config from 2.x still points at it", async () => {
    const { squadId } = await import("../src/squads");
    // due_crew.backend.firebase.squad_id("KQ9P2X3A"), computed by 2.x
    expect(await squadId("KQ9P2X3A")).toBe("612af6ba77ba48200974a238");
    expect(await squadId("kq9p-2x3a")).toBe("612af6ba77ba48200974a238");
  });

  it("restore: the first member back recreates it with its founder; the rest join", async () => {
    const r1 = await dre.call("POST", "/squads/restore", { code: "KQ9P2X3A", name: "busm", founder: "sam" });
    expect(r1.body).toMatchObject({ name: "busm", founder: "sam", open: true, code: "KQ9P2X3A" });
    const r2 = await sam.call("POST", "/squads/restore", { code: "KQ9P2X3A", name: "other name", founder: "dre" });
    expect(r2.body).toMatchObject({ id: r1.body.id, name: "busm", founder: "sam" });
    expect((await sam.call("GET", `/squads/${r1.body.id}`)).body.rows.map((r: any) => r.uid).sort()).toEqual(["dre", "sam"]);
    // a founder nobody knows falls back to whoever restores it
    const r3 = await nia.call("POST", "/squads/restore", { code: "ABCDEFGH", name: "x", founder: "ghost" });
    expect(r3.body.founder).toBe("nia");
    // a locked squad stays locked to a restore
    await sam.call("PATCH", `/squads/${r1.body.id}`, { open: false });
    expect((await nia.call("POST", "/squads/restore", { code: "KQ9P2X3A", name: "busm", founder: "sam" })).status).toBe(403);
  });

  it("only the founder sees the block list", async () => {
    const sq = (await sam.call("POST", "/squads", { name: "busm" })).body;
    await dre.call("POST", `/squads/${sq.id}/join`);
    await nia.call("POST", `/squads/${sq.id}/join`);
    await sam.call("POST", `/squads/${sq.id}/block/nia`);
    expect((await sam.call("GET", `/squads/${sq.id}`)).body.banned).toEqual(["nia"]);
    expect((await dre.call("GET", `/squads/${sq.id}`)).body.banned).toEqual([]);
  });
});
