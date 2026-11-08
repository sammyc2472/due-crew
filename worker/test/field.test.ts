import { beforeEach, describe, expect, it } from "vitest";
import { housekeeping } from "../src/index";
import { dayShift } from "../src/field";
import { WEEK, api, db, person } from "./helpers";

// 3.9.9, Know when it breaks: a sync's error counts (errs), kept only added
// up by day, version and code; the admin's Inbox reads a day of them.

type P = Awaited<ReturnType<typeof person>>;
let sam: P, dre: P, nia: P;
const env = { ADMIN_UIDS: "sam" } as any;
const admin = (who: { token: string }, path: string) => api("GET", path, { token: who.token, env });
const today = () => new Date().toISOString().slice(0, 10);  // their Anki day: a profile at UTC, rollover 0
const CLOCK = { tz: 0, rollover: 0 };
const errs = (days: Record<string, unknown>, v = "3.9.9") => ({ days, v });
const rows = async () => (await db().prepare("SELECT day, version, code, n, people FROM field_errs ORDER BY day, version, code").all()).results;

beforeEach(async () => {
  [sam, dre, nia] = await Promise.all(["sam", "dre", "nia"].map((u) => person(u)));
});

describe("POST /sync's errs", () => {
  it("/board says the Worker takes them (an add-on sends none till it reads this)", async () => {
    expect((await sam.call("GET", "/board")).body.errs).toBe(true);
  });

  it("every part is checked; a bad one turns the whole sync away, nothing written", async () => {
    const y = dayShift(today(), -1);
    const many = (n: number, pre = "c") => Object.fromEntries(Array.from({ length: n }, (_, i) => [`${pre}${i}`, 1]));
    const days8 = Object.fromEntries(Array.from({ length: 8 }, (_, i) => [dayShift(y, -i), { a: 1 }]));
    const bad: unknown[] = [
      "x", null, [], {}, { days: { [y]: { a: 1 } } }, { v: "3.9.9" },
      errs({ [y]: { a: 1 } }, "3.9.9-beta"), errs({ [y]: { a: 1 } }, "x"), errs({ [y]: { a: 1 } }, ""),
      { ...errs({ [y]: { a: 1 } }), uid: "sam" },
      { v: "3.9.9", days: [] }, errs(days8),
      errs({ yesterday: { a: 1 } }), errs({ "2026-02-31": { a: 1 } }), errs({ [y]: [] }), errs({ [y]: {} }),
      errs({ [y]: many(51) }),
      errs({ [y]: { "Save:bad_plan": 1 } }), errs({ [y]: { "req:/plans/:id:404": 1 } }), errs({ [y]: { "py:x:y:z the card said": 1 } }),
      errs({ [y]: { ["a".repeat(81)]: 1 } }), errs({ [y]: { "": 1 } }),
      errs({ [y]: { a: 0 } }), errs({ [y]: { a: 10000 } }), errs({ [y]: { a: 1.5 } }), errs({ [y]: { a: "2" } }), errs({ [y]: { a: true } }),
    ];
    for (const e of bad) {
      const r = await sam.call("POST", "/sync", { week: WEEK(today()), errs: e });
      expect([r.status, r.body.error, JSON.stringify(e).slice(0, 60)]).toEqual([400, "bad_errs", JSON.stringify(e).slice(0, 60)]);
    }
    expect(await rows()).toEqual([]);
    expect(await db().prepare("SELECT COUNT(*) AS n FROM weeks").first<number>("n")).toBe(0);
    const ok = await sam.call("POST", "/sync", {
      profile: CLOCK, week: WEEK(today()),
      errs: errs({ [y]: { ...many(49), ["x".repeat(80)]: 1 } }),  // 50 codes, one 80 long
    });
    expect(ok.status).toBe(200);
    expect((await rows()).length).toBe(50);  // 50 codes, a few to a statement
  });

  it("added up by day, version and code: n summed, a person a time, versions kept apart; no uid", async () => {
    const y = dayShift(today(), -1), y2 = dayShift(today(), -2);
    await sam.call("POST", "/sync", { profile: CLOCK, errs: errs({ [y]: { "save:bad_plan": 2, "py:plan_flow:maybe_morning:keyerror": 1 }, [y2]: { "save:bad_plan": 4 } }) });
    await dre.call("POST", "/sync", { profile: CLOCK, errs: errs({ [y]: { "save:bad_plan": 3, "req:plans.:id:400": 9999 } }) });
    await nia.call("POST", "/sync", { profile: CLOCK, errs: errs({ [y]: { "save:bad_plan": 1 } }, "3.9.10") });
    expect(await rows()).toEqual([
      { day: y2, version: "3.9.9", code: "save:bad_plan", n: 4, people: 1 },
      { day: y, version: "3.9.10", code: "save:bad_plan", n: 1, people: 1 },
      { day: y, version: "3.9.9", code: "py:plan_flow:maybe_morning:keyerror", n: 1, people: 1 },
      { day: y, version: "3.9.9", code: "req:plans.:id:400", n: 9999, people: 1 },
      { day: y, version: "3.9.9", code: "save:bad_plan", n: 5, people: 2 },
    ]);
    const cols = (await db().prepare("SELECT name FROM pragma_table_info('field_errs')").all<{ name: string }>()).results.map((r) => r.name);
    expect(cols).toEqual(["day", "version", "code", "n", "people"]);
    expect(JSON.stringify(await rows())).not.toMatch(/sam|dre|nia/);
  });

  it("people counts people: one sync is one person for each code, however big its count", async () => {
    const y = dayShift(today(), -1);
    const r = await sam.call("POST", "/sync", { profile: CLOCK, errs: errs({ [y]: { a: 7, b: 1 } }) });
    expect(r.body.wrote.errs).toBe(true);
    expect((await rows()).map((x: any) => [x.code, x.n, x.people])).toEqual([["a", 7, 1], ["b", 1, 1]]);
    await dre.call("POST", "/sync", { profile: CLOCK, errs: errs({ [y]: { b: 2 } }) });
    expect((await rows()).map((x: any) => [x.code, x.n, x.people])).toEqual([["a", 7, 1], ["b", 3, 2]]);
  });

  it("only the days in the sender's last 7 (their Anki day) are kept; the sync still goes", async () => {
    const t = today();
    const r = await sam.call("POST", "/sync", {
      profile: CLOCK, week: WEEK(t),
      errs: errs({ [dayShift(t, 1)]: { ahead: 1 }, [t]: { today: 1 }, [dayShift(t, -7)]: { week: 1 }, [dayShift(t, -8)]: { old: 1 } }),
    });
    expect(r.status).toBe(200);
    expect((await rows()).map((x: any) => x.code).sort()).toEqual(["today", "week"]);
    expect(await db().prepare("SELECT COUNT(*) AS n FROM weeks").first<number>("n")).toBe(1);
    // a day by the sender's own clock: at UTC+14 it's already tomorrow there
    await dre.call("POST", "/sync", { profile: { tz: 14 * 60, rollover: 0 }, errs: errs({ [dayShift(t, 1)]: { east: 1 } }) });
    expect((await rows()).map((x: any) => x.code)).toContain("east");
  });

  it("nothing to write, nothing written: no errs, or none in the window", async () => {
    const a = await sam.call("POST", "/sync", { profile: CLOCK, week: WEEK(today()) });
    expect(a.body.wrote.errs).toBeUndefined();
    const b = await sam.call("POST", "/sync", { profile: CLOCK, errs: errs({ [dayShift(today(), -30)]: { old: 1 } }) });
    expect([b.status, b.body.wrote.errs]).toEqual([200, false]);
    expect(await rows()).toEqual([]);
  });
});

describe("the 30-day keep", () => {
  it("housekeeping (daily) drops what's older than 30 days", async () => {
    const t = today();
    for (const d of [dayShift(t, -31), dayShift(t, -30), dayShift(t, -1)]) {
      await db().prepare("INSERT INTO field_errs (day, version, code, n, people) VALUES (?, '3.9.9', 'a', 1, 1)").bind(d).run();
    }
    await housekeeping({ DB: db() } as any);
    expect((await rows()).map((x: any) => x.day)).toEqual([dayShift(t, -30), dayShift(t, -1)]);
  });
});

describe("GET /admin/field", () => {
  it("admins only: anyone else gets the same 404 as no route", async () => {
    expect((await dre.call("GET", "/admin/field")).status).toBe(404);
    expect((await api("GET", "/admin/field", { token: dre.token, env })).status).toBe(404);
    expect((await api("GET", "/admin/field")).status).toBe(401);
    expect((await admin(sam, "/admin/field")).status).toBe(200);
  });

  it("yesterday's table: code, n, people, versions, most first; and the codes new since the day before", async () => {
    const y = dayShift(today(), -1), y2 = dayShift(today(), -2);
    await sam.call("POST", "/sync", { profile: CLOCK, errs: errs({ [y]: { old: 1, "save:bad_plan": 2 }, [y2]: { old: 3 } }) });
    await dre.call("POST", "/sync", { profile: CLOCK, errs: errs({ [y]: { "save:bad_plan": 5 } }, "3.9.10") });
    const r = (await admin(sam, "/admin/field")).body;
    expect(r).toEqual({
      day: y, before: y2, beforeCodes: 1,
      rows: [{ code: "save:bad_plan", n: 7, people: 2, versions: ["3.9.10", "3.9.9"] }, { code: "old", n: 1, people: 1, versions: ["3.9.9"] }],
      new: ["save:bad_plan"],
    });
    const d2 = (await admin(sam, `/admin/field?day=${y2}`)).body;
    expect([d2.day, d2.rows.map((x: any) => [x.code, x.n]), d2.new, d2.beforeCodes]).toEqual([y2, [["old", 3]], ["old"], 0]);
    expect((await admin(sam, "/admin/field?day=nonsense")).body.day).toBe(y);
    expect(JSON.stringify(r)).not.toMatch(/sam|dre/);
  });
});
