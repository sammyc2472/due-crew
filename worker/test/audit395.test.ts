import { env } from "cloudflare:workers";
import { describe, expect, it } from "vitest";
import { api, db, mailbox, person } from "./helpers";

// 3.9.5, the security and efficiency audit of 4cbb6c9: a squad's door holds
// while someone is mid-join (S3), one person's squads have a ceiling (A2),
// and a board with more than 100 teams still comes back (A1). S1 and S2,
// the plan counts, are in plans.test.ts.

type P = Awaited<ReturnType<typeof person>>;

async function squadOf(founder: P, name = "busm") {
  const r = await founder.call("POST", "/squads", { name });
  expect(r.status).toBe(200);
  return r.body as { id: string; code: string };
}

/** The real D1, but `land` runs (and commits) just before the first
 *  statement that puts someone in a squad: what a block or a lock from the
 *  founder, arriving while a join is under way, looks like. */
function racing(land: () => Promise<unknown>) {
  const real = env.DB;
  let fired = false;
  const pass = (o: any, k: PropertyKey) => { const v = o[k]; return typeof v === "function" ? v.bind(o) : v; };
  const statement = (st: D1PreparedStatement): D1PreparedStatement => new Proxy(st, {
    get(o, k) {
      if (k === "bind") return (...a: unknown[]) => statement(o.bind(...a));
      if (k === "run") return async () => { if (!fired) { fired = true; await land(); } return o.run(); };
      return pass(o, k);
    },
  });
  return new Proxy(real, {
    get(o, k) {
      if (k === "prepare") return (sql: string) => (/^\s*INSERT INTO members/.test(sql) ? statement(o.prepare(sql)) : o.prepare(sql));
      return pass(o, k);
    },
  });
}

const joinWhile = (who: P, id: string, code: string, land: () => Promise<unknown>) =>
  api("POST", `/squads/${id}/join`, { token: who.token, body: { code }, env: { DB: racing(land) } as any });

describe("S3: the door holds mid-join", () => {
  it("a block, a lock or a new code that lands just before the insert keeps them out", async () => {
    const [alice, bob, carol, dave] = await Promise.all(["alice", "bob", "carol", "dave"].map((u) => person(u)));
    const { id, code } = await squadOf(alice);
    const blocked = await joinWhile(bob, id, code, () => alice.call("POST", `/squads/${id}/block/bob`));
    expect(blocked.status).toBe(403);
    expect(blocked.body.error).toBe("blocked");
    expect(await bob.status("GET", `/squads/${id}`), "and can't read it").toBe(403);
    const locked = await joinWhile(carol, id, code, () => alice.call("PATCH", `/squads/${id}`, { open: false }));
    expect([locked.status, locked.body.error]).toEqual([403, "locked"]);
    await alice.call("PATCH", `/squads/${id}`, { open: true });
    // with nothing landing, the door works as before
    const eve = await person("eve");
    expect(await eve.status("POST", `/squads/${id}/join`, { code })).toBe(200);
    expect(await eve.status("POST", `/squads/${id}/join`, { code }), "twice is a no-op").toBe(200);
    // the admin's new code: the old one stops opening the door, even mid-join (the founder is mailed it)
    mailbox();
    const admin = await person("admin");
    const renewed = await joinWhile(dave, id, code, () => api("POST", `/admin/squads/${id}/code`, {
      token: admin.token, env: { ADMIN_UIDS: "admin" } as any }));
    expect([renewed.status, renewed.body.error]).toEqual([403, "wrong_code"]);
  });

  it("the ceiling holds too: two joins at once can't both take the last place", async () => {
    const alice = await person("alice");
    const { id, code } = await squadOf(alice);
    await db().prepare("UPDATE squads SET open = 1 WHERE id = ?").bind(id).run();
    // 499 in, the founder among them: one place left
    const now = Math.floor(Date.now() / 1000);
    const fill = [];
    for (let i = 0; i < 498; i++) fill.push(db().prepare("INSERT INTO members (squad, uid, name, joined_at) VALUES (?, ?, 'x', ?)").bind(id, `fill${i}`, now));
    await db().batch(fill);
    const [bob, carol] = await Promise.all(["bob", "carol"].map((u) => person(u)));
    const first = await joinWhile(bob, id, code, () => carol.call("POST", `/squads/${id}/join`, { code }));
    expect(first.status).toBe(403);
    expect(first.body.error).toBe("full");
    expect(await db().prepare("SELECT COUNT(*) AS n FROM members WHERE squad = ?").bind(id).first("n")).toBe(500);
  });
});

describe("A2: one person's squads have a ceiling", () => {
  it("20 squads: the 21st join and a 21st squad are refused, said so; leave one and the door opens", async () => {
    const founders = await Promise.all(["alice", "bob", "carol"].map((u) => person(u)));
    const dave = await person("dave");
    const made: { id: string; code: string }[] = [];
    for (let i = 0; i < 21; i++) made.push(await squadOf(founders[Math.floor(i / 10)], `s${i}`));
    for (const s of made.slice(0, 20)) expect(await dave.status("POST", `/squads/${s.id}/join`, { code: s.code })).toBe(200);
    const over = await dave.call("POST", `/squads/${made[20].id}/join`, { code: made[20].code });
    expect([over.status, over.body.error]).toEqual([409, "too_many_squads"]);
    const own = await dave.call("POST", "/squads", { name: "mine" });
    expect([own.status, own.body.error]).toEqual([409, "too_many_squads"]);
    expect((await dave.call("GET", "/board?decks=1")).body.squads).toHaveLength(20);
    await dave.call("DELETE", `/squads/${made[0].id}/members/dave`);
    expect(await dave.status("POST", `/squads/${made[20].id}/join`, { code: made[20].code })).toBe(200);
  });

  it("someone in more from before keeps them, and the board brings back what a sync can carry", async () => {
    const [alice, dave] = await Promise.all(["alice", "dave"].map((u) => person(u)));
    const now = Math.floor(Date.now() / 1000);
    const st = [];
    for (let i = 0; i < 25; i++) {
      st.push(db().prepare("INSERT INTO squads (id, name, founder, open, created_at) VALUES (?, ?, 'alice', 1, ?)").bind(`old${i}`, `old ${i}`, now));
      st.push(db().prepare("INSERT INTO members (squad, uid, name, joined_at) VALUES (?, 'dave', 'Dave', ?)").bind(`old${i}`, now + i));
    }
    await db().batch(st);
    expect((await dave.call("GET", "/squads/mine")).body.squads).toHaveLength(25);
    expect((await dave.call("GET", "/board?decks=1")).body.squads).toHaveLength(20);
    const s = await squadOf(alice, "new");
    expect((await dave.call("POST", `/squads/${s.id}/join`, { code: s.code })).body.error).toBe("too_many_squads");
  });

  it("join tries have a budget, right code or not", async () => {
    const [alice, mal] = await Promise.all(["alice", "mal"].map((u) => person(u)));
    const { id } = await squadOf(alice);
    for (let i = 0; i < 30; i++) expect(await mal.status("POST", `/squads/${id}/join`, { code: "AAAAAAAA" })).toBe(403);
    expect(await mal.status("POST", `/squads/${id}/join`, { code: "AAAAAAAA" })).toBe(429);
  });
});

describe("A1: more than 100 teams", () => {
  it("a board with 101 co-written plans' teams comes back whole", async () => {
    const owners = await Promise.all(["own1", "own2", "own3"].map((u) => person(u)));
    const sam = await person("sam");
    const made = await owners[0].call("POST", "/plans", { name: "Base", deck: "Step 1" });
    expect(made.status).toBe(200);
    const now = Math.floor(Date.now() / 1000);
    // 101 copies of one plan, by row: three owners, each under their own ceiling of 50
    const base = (await db().prepare("SELECT * FROM plans WHERE id = ?").bind(made.body.id).first<Record<string, unknown>>())!;
    const cols = Object.keys(base);
    const st: D1PreparedStatement[] = [];
    for (let i = 0; i < 101; i++) {
      const id = `cw${String(i).padStart(3, "0")}`;
      const row = { ...base, id, code: `CODE${String(i).padStart(4, "0")}`, owner: owners[i % 3].uid, tagroot: null };
      st.push(db().prepare(`INSERT INTO plans (${cols.join(", ")}) VALUES (${cols.map(() => "?").join(", ")})`)
        .bind(...cols.map((c) => (row as Record<string, unknown>)[c] ?? null)));
      st.push(db().prepare("INSERT INTO plan_editors (plan, uid, at, accepted_at) VALUES (?, 'sam', ?, ?)").bind(id, now, now));
      st.push(db().prepare("INSERT INTO plan_team (plan, uid, joined_at) VALUES (?, 'sam', ?)").bind(id, now));
    }
    await db().batch(st);
    const b = await sam.call("GET", "/board");
    expect(b.status).toBe(200);
    expect(Object.keys(b.body.teams ?? {})).toHaveLength(101);
  });
});
