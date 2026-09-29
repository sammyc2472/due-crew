import { describe, expect, it } from "vitest";
import * as B from "../src/bingo";
import { api, db, person } from "./helpers";

// 3.6: squad bingo. The server draws a card a week from a pool the admin
// edits, and keeps it; each member's row carries `play`; boards add it up.

const env = { ADMIN_UIDS: "sam" } as any;
const admin = (who: { token: string }, path: string, method = "GET", body?: unknown) => api(method, path, { token: who.token, env, body });
const thisWeek = () => B.isoWeek(new Date());

async function pool() {
  const rows = await db().prepare("SELECT id, kind, json FROM bingo_pool WHERE enabled = 1").all<{ id: string; kind: string; json: string }>();
  const squares: B.Square[] = [], middles: B.Middle[] = [];
  for (const r of rows.results) (r.kind === "square" ? squares : middles).push({ id: r.id, ...JSON.parse(r.json) });
  return { squares, middles };
}

describe("weeks", () => {
  it("names ISO weeks, and finds their Mondays", () => {
    expect(B.isoWeek(new Date("2026-09-28T12:00:00Z"))).toBe("2026-W40");
    expect(B.isoWeek(new Date("2026-10-04T23:00:00Z"))).toBe("2026-W40");  // Sunday
    expect(B.isoWeek(new Date("2026-01-01T00:00:00Z"))).toBe("2026-W01");
    expect(B.isoWeek(new Date("2027-01-01T00:00:00Z"))).toBe("2026-W53");
    expect(B.isoWeek(new Date("2024-12-30T00:00:00Z"))).toBe("2025-W01");
    expect(B.mondayOf("2026-W40").toISOString().slice(0, 10)).toBe("2026-09-28");
    expect(B.mondayOf("2025-W01").toISOString().slice(0, 10)).toBe("2024-12-30");
    expect(B.wkNum("2026-W40")).toBe(202640);
  });

  it("a client may ask for last week, this week or next, nothing further", () => {
    const now = new Date("2026-09-30T12:00:00Z");
    expect(["2026-W39", "2026-W40", "2026-W41"].every((w) => B.askable(w, now))).toBe(true);
    expect(B.askable("2026-W42", now)).toBe(false);
    expect(B.askable("2025-W40", now)).toBe(false);
    expect(B.askable("2026-40", now)).toBe(false);
    expect(B.askable(undefined, now)).toBe(false);
  });
});

describe("the draw", () => {
  it("one square a family, 3 easy / 3 medium / 2 hard, four team squares, hard ones never", async () => {
    const { squares, middles } = await pool();
    for (let w = 1; w <= 52; w++) {
      const wk = `2026-W${String(w).padStart(2, "0")}`;
      const c = B.draw(wk, squares, middles);
      expect(c.squares).toHaveLength(8);
      expect(new Set(c.squares.map((s) => s.fam)).size).toBe(8);
      expect(c.squares.map((s) => s.diff).sort().join("")).toBe("eeehhmmm");
      const needs = c.squares.map((s) => s.need);
      expect(needs.filter((n) => n === "half")).toHaveLength(1);
      expect(needs.filter((n) => n === 3)).toHaveLength(1);
      expect(needs.filter((n) => n === 2)).toHaveLength(2);
      expect(c.squares.filter((s) => s.diff === "h").every((s) => s.need === 1)).toBe(true);
      expect(c.squares.filter((s) => s.need !== 1).every((s) => s.team)).toBe(true);
      expect(B.draw(wk, squares, middles)).toEqual(c);  // the same week draws the same card
    }
  });

  it("the middle: a season first, every sixth week free, else study and crew weeks take turns", async () => {
    const { squares, middles } = await pool();
    const group = (wk: string) => B.draw(wk, squares, middles).middle.group;
    expect(group("2026-W42")).toBe("free");
    expect(group("2026-W41")).toBe("study");
    expect(group("2026-W40")).toBe("crew");
    expect(B.draw("2026-W44", squares, middles).middle.id).toBe("spooky");   // 26 Oct – 1 Nov
    expect(B.draw("2027-W01", squares, middles).middle.id).toBe("newyear");  // across New Year
    expect(B.draw("2026-W53", squares, middles).middle.id).toBe("newyear");
  });

  it("a card is drawn once and kept: an edit shows from the next draw", async () => {
    const sam = await person("sam");
    const sq = (await sam.call("POST", "/squads", { name: "busm" })).body;
    const wk = thisWeek();
    const first = (await sam.call("GET", `/squads/${sq.id}?wk=${wk}`)).body.bingo;
    expect(first.wk).toBe(wk);
    await db().prepare("UPDATE bingo_pool SET enabled = 0 WHERE kind = 'square' AND id = ?").bind(first.squares[0].id).run();
    expect((await sam.call("GET", `/squads/${sq.id}?wk=${wk}`)).body.bingo).toEqual(first);
    expect((await sam.call("GET", `/squads/${sq.id}`)).body.bingo).toBeUndefined();
    expect((await sam.call("GET", `/squads/${sq.id}?wk=2020-W01`)).body.bingo).toBeUndefined();
  });
});

describe("the board and my row", () => {
  it("GET /board brings the card on the day's first refresh, only to someone in a squad", async () => {
    const sam = await person("sam");
    const wk = thisWeek();
    expect((await sam.call("GET", `/board?decks=1&wk=${wk}`)).body.bingo).toBeUndefined();
    await sam.call("POST", "/squads", { name: "busm" });
    expect((await sam.call("GET", `/board?decks=1&wk=${wk}`)).body.bingo.wk).toBe(wk);
    expect((await sam.call("GET", `/board?wk=${wk}`)).body.bingo).toBeUndefined();          // not every refresh
    expect((await sam.call("GET", `/board?decks=1&keep=1&wk=${wk}`)).body.bingo).toBeUndefined();  // not the site's home
  });

  it("play rides the squad row: kept, compared before writing, cleared when absent, checked", async () => {
    const sam = await person("sam");
    const sq = (await sam.call("POST", "/squads", { name: "busm" })).body;
    const play = { wk: 202640, s: 5, d: 0b0010011, ch: 2 };
    const row = { name: "Sam", day: "2026-09-30", reviews: 40, play };
    expect((await sam.call("POST", "/sync", { squads: { row, ids: [sq.id] } })).body.wrote.squads).toBe(true);
    expect((await sam.call("POST", "/sync", { squads: { row, ids: [sq.id] } })).body.wrote.squads).toBe(false);
    const got = (await sam.call("GET", `/squads/${sq.id}`)).body.rows[0];
    expect(got.play).toEqual(play);
    expect(got.joined).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect((await sam.call("POST", "/sync", { squads: { row: { ...row, play: { ...play, s: 7 } }, ids: [sq.id] } })).body.wrote.squads).toBe(true);
    await sam.call("POST", "/sync", { squads: { row: { name: "Sam", day: "2026-09-30" }, ids: [sq.id] } });
    expect((await sam.call("GET", `/squads/${sq.id}`)).body.rows[0].play).toBeNull();
    for (const bad of [{ s: 1 }, { wk: 202640, S: 1 }, { wk: 202640, s: -1 }, { wk: 202640, s: 1.5 }, { wk: "2026-W40" },
                       Object.fromEntries(Array.from({ length: 25 }, (_, i) => [`k${i}`, 1]))]) {
      expect(await sam.status("POST", "/sync", { squads: { row: { ...row, play: bad }, ids: [sq.id] } })).toBe(400);
    }
    expect(await sam.status("PUT", `/squads/${sq.id}/row`, { ...row, play })).toBe(200);
  });
});

describe("a squad's card, from its rows", () => {
  const card = (need: (number | "half")[], middle: Partial<B.Middle>): B.Card => ({
    wk: "2026-W40",
    squares: need.map((n, i) => ({ id: `q${i}`, fam: "early", diff: "e", icon: "☀️", title: "t", rule: "r", detail: "d",
                                   type: "days", params: { days: 1 }, team: true, need: n })),
    middle: { id: "m", group: "crew", icon: "🎨", name: "m", rule: "r", detail: "d", type: "free", params: {}, goal: 1, unit: "", ...middle },
  });
  const row = (uid: string, play: Record<string, number> | null, extra: Partial<B.Row> = {}): B.Row =>
    ({ uid, emoji: null, day: "2026-09-29", joined: "2026-01-01", play: play && { wk: 202640, ...play }, ...extra });

  it("team squares need that many of you; half is half the active, at most 6; never more than there are", () => {
    const c = card(["half", 3, 2, 1, 1, 1, 1, 1], {});
    const rows = [row("a", { s: 0b111 }), row("b", { s: 0b011 }), row("c", { s: 0b001 }), row("d", null),
                  row("gone", null, { day: "2026-08-01" })];
    const e = B.evaluate(c, rows);
    expect(e.active).toBe(4);
    expect(e.squares.slice(0, 3).map((s) => [s.who.length, s.need, s.done])).toEqual([[3, 2, true], [2, 3, false], [1, 2, false]]);
    const big = Array.from({ length: 30 }, (_, i) => row(`p${i}`, { s: i < 6 ? 1 : 0 }));
    expect(B.evaluate(c, big).squares[0]).toMatchObject({ need: 6, done: true });
    const two = B.evaluate(c, [row("a", { s: 0b10 }), row("b", { s: 0b10 })]);
    expect(two.squares[1]).toMatchObject({ need: 2, done: true });  // "3 of you" in a squad of two
    // last week's play counts for nothing this week
    expect(B.evaluate(c, [row("a", null, { play: { wk: 202639, s: 255 } as any })]).squares[3].done).toBe(false);
  });

  it("the middle's kinds, and lines through it", () => {
    const rows = [row("a", { d: 0b1000001, ch: 3, z: 1 }, { emoji: "🦊" }), row("b", { d: 0b0000001, ch: 2 }, { emoji: "🐙" }),
                  row("c", { d: 0b1000000 }, { joined: "2026-09-30" })];
    const m = (x: Partial<B.Middle>) => B.evaluate(card([1, 1, 1, 1, 1, 1, 1, 1], x), rows).middle;
    expect(m({ type: "day", params: { key: "d" }, goal: "all" })).toMatchObject({ have: 2, goal: 3, done: false });
    expect(m({ type: "day", params: { key: "d", day: 6 }, goal: 2 })).toMatchObject({ done: true });
    expect(m({ type: "people", params: { key: "d" }, goal: "all" })).toMatchObject({ done: true });
    expect(m({ type: "sum", params: { key: "ch" }, goal: 5 })).toMatchObject({ have: 5, done: true });
    expect(m({ type: "sum", params: { key: "ch" }, goal: 9 })).toMatchObject({ goal: 9, done: false });  // a sum isn't capped
    expect(m({ type: "people", params: { key: "z" }, goal: 4 })).toMatchObject({ goal: 3, done: false });
    expect(m({ type: "emoji", params: {}, goal: "all" })).toMatchObject({ have: 2, done: false });
    expect(m({ type: "joined", params: {}, goal: 1 })).toMatchObject({ done: true });
    // the middle row: squares 3 and 4 around the middle (cells 3 and 5)
    const lined = B.evaluate(card([1, 1, 1, 1, 1, 1, 1, 1], {}), [row("a", { s: 0b11000 })]);
    expect(lined.lines).toBe(1);
    const whole = B.evaluate(card([1, 1, 1, 1, 1, 1, 1, 1], {}), [row("a", { s: 255 })]);
    expect(whole.lines).toBe(8);
  });
});

describe("the admin's pool", () => {
  it("only the admin; the whole pool, this week's card; add, change and turn off an entry", async () => {
    const sam = await person("sam");
    const dre = await person("dre");
    expect((await admin(dre, "/admin/bingo")).status).toBe(404);
    const got = (await admin(sam, "/admin/bingo")).body;
    expect(got.week).toBe(thisWeek());
    expect(got.pool.filter((p: any) => p.kind === "square")).toHaveLength(26);
    expect(got.cards[0].wk).toBe(thisWeek());
    const f20 = got.pool.find((p: any) => p.id === "f20");
    const put = (id: string, body: unknown) => admin(sam, `/admin/bingo/${id}`, "PUT", body);
    const easier = { ...f20.entry, rule: "15 minutes, no break", params: { minutes: 15, gap: 5 } };
    expect((await put("f20", { kind: "square", entry: easier, enabled: true })).status).toBe(200);
    expect((await admin(sam, "/admin/bingo")).body.pool.find((p: any) => p.id === "f20").entry.params.minutes).toBe(15);
    expect((await put("f20", { kind: "square", entry: easier, enabled: false })).status).toBe(200);
    expect((await put("f20", { kind: "middle", entry: easier, enabled: true })).status).toBe(400);
    const winter = { group: "season", icon: "❄️", name: "Snow week", rule: "Half of you, due zero", detail: "Half of you end a day with nothing due.",
                     type: "people", params: { key: "z" }, goal: "half", unit: "clean", season: { from: "12-10", to: "12-16" } };
    expect((await put("snow", { kind: "middle", entry: winter, enabled: true })).status).toBe(200);
    expect((await put("snow", { kind: "square", entry: easier, enabled: true })).status).toBe(409);
    for (const bad of [
      { ...easier, type: "teleport" }, { ...easier, params: { minutes: 999, gap: 5 } }, { ...easier, params: { minutes: 20 } },
      { ...easier, params: { minutes: 20, gap: 5, extra: 1 } }, { ...easier, icon: "abc" }, { ...easier, fam: "sleep" },
      { ...easier, title: "" }, { ...easier, team: "yes" },
    ]) expect((await put("f20", { kind: "square", entry: bad, enabled: true })).status).toBe(400);
    for (const bad of [{ ...winter, season: undefined }, { ...winter, season: { from: "13-01", to: "12-16" } },
                       { ...winter, params: { key: "s" } }, { ...winter, goal: 0 }, { ...winter, group: "party" }]) {
      expect((await put("snow", { kind: "middle", entry: bad, enabled: true })).status).toBe(400);
    }
    expect((await admin(sam, "/admin/bingo/Bad-Id", "PUT", { kind: "square", entry: easier, enabled: true })).status).toBe(404);
  });

  it("the daily counts: per square, by people and by squads, and nobody named", async () => {
    const sam = await person("sam");
    const dre = await person("dre");
    const sq = (await sam.call("POST", "/squads", { name: "busm" })).body;
    await dre.call("POST", `/squads/${sq.id}/join`, { code: sq.code });
    const now = new Date();
    const wk = B.isoWeek(now);
    const card = (await sam.call("GET", `/squads/${sq.id}?wk=${wk}`)).body.bingo as B.Card;
    const day = now.toISOString().slice(0, 10);
    const n = B.wkNum(wk);
    await sam.call("POST", "/sync", { squads: { row: { name: "Sam", day, play: { wk: n, s: 0b11111111, d: 1 } }, ids: [sq.id] } });
    await dre.call("POST", "/sync", { squads: { row: { name: "Dre", day, play: { wk: n, s: 0b00000001, d: 1 } }, ids: [sq.id] } });
    await B.keepStats({ DB: db() } as any, now);
    const stats = (await admin(sam, "/admin/bingo")).body.cards.find((c: any) => c.wk === wk).stats;
    expect(stats).toMatchObject({ players: 2, squads: 1 });
    expect(stats.squares[0].people).toBe(2);
    expect(stats.squares[1].people).toBe(1);
    // two active: a square is done by Sam alone when it needs one (1, or half of two);
    // square 0 has both of them, so it's done whatever it needs
    const done = card.squares.map((sq, i) => i === 0 || sq.need === 1 || sq.need === "half" ? 1 : 0);
    expect(stats.squares.map((x: any) => x.squads)).toEqual(done);
    expect(JSON.stringify(stats)).not.toMatch(/sam|dre/);
  });
});
