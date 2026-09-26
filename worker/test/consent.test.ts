// The consent model. Every check of tests/rules/emulator_rules_test.py
// (the Firestore rules, 2.x), in its order and under its label, restated
// against the Worker. Where a check was about Firestore machinery (a
// listing, a batch's access-call cap, a rules marker), the 3.0 statement of
// the same promise stands in its place, and says so.

import { beforeEach, describe, expect, it } from "vitest";
import { WEEK, api, befriend, db, person } from "./helpers";

type P = Awaited<ReturnType<typeof person>>;
let alice: P, bob: P, carol: P, dave: P;
const DAY = "2026-09-10";

beforeEach(async () => {
  // dave and alice are friends; nobody is in a squad yet
  [alice, bob, carol, dave] = await Promise.all(["alice", "bob", "carol", "dave"].map((u) => person(u)));
  await befriend(alice, dave);
  await befriend(dave, alice);
});

async function squadOf(founder: P, name = "busm") {
  const r = await founder.call("POST", "/squads", { name });
  expect(r.status).toBe(200);
  return r.body as { id: string; code: string };
}
const rowsOf = async (p: P, id: string) => ((await p.call("GET", `/squads/${id}`)).body.rows ?? []) as any[];
const row = { day: DAY, reviews: 10, studyTimeMs: 1000, accuracy: 91.5, streak: 3 };

describe("squads: the id is the invite; only the founder shapes it", () => {
  it("creation", async () => {
    const sq = await squadOf(alice);
    expect(sq.id, "squad: founder creates").toMatch(/^[0-9a-f]{24}$/);
    expect(await bob.status("POST", "/squads", { name: "busm", founder: "alice" }), "squad: cannot name someone else as founder").toBe(400);
    expect((await bob.call("POST", "/squads", { name: "mine" })).body.founder, "squad: the founder is whoever creates it").toBe("bob");
    expect(await bob.status("POST", "/squads", { name: "x".repeat(25) }), "squad: name too long rejected").toBe(400);
    expect(await bob.status("POST", "/squads", { name: "busm", code: "KQ9P2X3A" }), "squad: extra field rejected").toBe(400);
    const peek = await carol.call("GET", `/squads/peek?code=${sq.code}`);
    expect(peek.status, "squad: anyone signed in may get it").toBe(200);
    expect(Object.keys(peek.body).sort(), "squad: the preview is the name and the door, nothing else").toEqual(["code", "founder", "id", "name", "open"]);
    expect((await api("GET", `/squads/peek?code=${sq.code}`)).status, "squad: signed out cannot").toBe(401);
    expect([404, 405], "squad: no listing").toContain(await alice.status("GET", "/squads"));
  });
});

describe("members: join while open, own row only, allowed shape only", () => {
  it("joins and rows", async () => {
    const { id } = await squadOf(alice);
    expect((await rowsOf(alice, id)).map((r) => r.uid), "member: founder joins own squad").toEqual(["alice"]);
    expect(await bob.status("POST", `/squads/${id}/join`), "member: bob joins while open").toBe(200);
    expect((await rowsOf(alice, id)).map((r) => r.uid).sort(), "member: cannot join as someone else (a join is always the caller)").toEqual(["alice", "bob"]);
    expect(await bob.status("PUT", `/squads/${id}/row`, row), "row: member writes own numbers").toBe(200);
    expect(await bob.status("PUT", `/squads/${id}/row`, { server: "x" }), "row: extra field rejected").toBe(400);
    expect(await bob.status("PUT", `/squads/${id}/row`, { reviews: -1 }), "row: negative reviews rejected").toBe(400);
    expect(await bob.status("PUT", `/squads/${id}/row`, { day: "nope" }), "row: bad day rejected").toBe(400);
    const a = (await rowsOf(alice, id)).find((r) => r.uid === "alice");
    expect(a.reviews, "row: cannot write someone else's (a row is always the caller's)").toBeNull();
  });

  it("reads: members only", async () => {
    const { id } = await squadOf(alice);
    await bob.call("POST", `/squads/${id}/join`);
    expect(await bob.status("GET", `/squads/${id}`), "board: member lists rows").toBe(200);
    expect(await carol.status("GET", `/squads/${id}`), "board: non-member cannot list").toBe(403);
    expect(await carol.status("GET", `/squads/${id}`), "board: non-member cannot get a row").toBe(403);
    expect((await bob.call("GET", `/squads/${id}`)).body.rows, "board: member query allowed (one query)").toHaveLength(2);
    expect(await carol.status("GET", `/squads/${id}`), "board: non-member query denied").toBe(403);
    expect(await carol.status("PUT", `/squads/${id}/row`, row), "a non-member cannot write a row either").toBe(403);
  });

  it("the door: lock, founder only; existing members keep syncing", async () => {
    const { id } = await squadOf(alice);
    await bob.call("POST", `/squads/${id}/join`);
    expect(await alice.status("PATCH", `/squads/${id}`, { open: false }), "lock: founder locks").toBe(200);
    expect(await bob.status("PATCH", `/squads/${id}`, { open: true }), "lock: non-founder cannot").toBe(403);
    expect(await carol.status("POST", `/squads/${id}/join`), "lock: join refused while locked").toBe(403);
    expect(await bob.status("PUT", `/squads/${id}/row`, { reviews: 11 }), "lock: existing member still writes").toBe(200);
    expect(await alice.status("PATCH", `/squads/${id}`, { founder: "dave" }), "lock: founder cannot be handed to a non-member").toBe(403);
  });
});

describe("knocks: both in the same squad", () => {
  it("squad knocks", async () => {
    const { id } = await squadOf(alice);
    await bob.call("POST", `/squads/${id}/join`);
    expect(await bob.status("POST", "/knocks/alice", { squad: id }), "knock: squadmate to squadmate").toBe(200);
    expect(await bob.status("POST", "/knocks/carol", { squad: id }), "knock: to a non-member rejected").toBe(403);
    expect(await carol.status("POST", "/knocks/alice", { squad: id }), "knock: from a non-member rejected").toBe(403);
    const list = (await alice.call("GET", "/knocks")).body.knocks;
    expect(list, "knock: cannot forge sender id (the sender is the caller, the name is the profile's)")
      .toEqual([{ from: "bob", name: "Bob", emoji: "", squad: id }]);
    expect(await bob.status("POST", "/knocks/alice", { squad: id, crew: "x" }), "knock: extra fields rejected").toBe(400);
    expect(await alice.status("POST", "/knocks/bob", {}), "knock: a squad or a code is required").toBe(400);
    expect(await alice.status("DELETE", "/knocks/bob"), "knock: owner reads and deletes").toBe(200);
    expect((await alice.call("GET", "/knocks")).body.knocks).toEqual([]);
  });
});

describe("remove and leave", () => {
  it("founder removes; members leave; reads close", async () => {
    const { id } = await squadOf(alice);
    await bob.call("POST", `/squads/${id}/join`);
    expect(await alice.status("DELETE", `/squads/${id}/members/bob`), "member: founder removes anyone").toBe(200);
    await bob.call("POST", `/squads/${id}/join`);
    expect(await bob.status("DELETE", `/squads/${id}/members/alice`), "member: cannot remove someone else").toBe(403);
    expect(await bob.status("DELETE", `/squads/${id}/members/bob`), "member: leaves").toBe(200);
    expect(await bob.status("GET", `/squads/${id}`), "board: after leaving, reads are denied").toBe(403);
  });
});

describe("cheers: friends only, one emoji, optional note <= 80", () => {
  const cheer = { emoji: "🔥" };
  it("shape and consent", async () => {
    expect(await dave.status("POST", "/cheers/alice", cheer), "cheer: friend sends").toBe(200);
    expect(await dave.status("POST", "/cheers/alice", { ...cheer, note: "you're on fire" }), "cheer: with a note").toBe(200);
    expect(await dave.status("POST", "/cheers/alice", { ...cheer, note: "x".repeat(81) }), "cheer: note over 80 chars rejected").toBe(400);
    expect(await dave.status("POST", "/cheers/alice", { ...cheer, note: 5 }), "cheer: note must be a string").toBe(400);
    expect(await dave.status("POST", "/cheers/alice", { ...cheer, link: "http://x" }), "cheer: extra field rejected").toBe(400);
    expect(await bob.status("POST", "/cheers/alice", cheer), "cheer: non-friend rejected").toBe(403);
    expect([404, 405], "cheer: only the owner reads (there's no way to read another's)").toContain(await dave.status("GET", "/cheers/alice"));
  });

  it("any one emoji (rules-v8): a shape, not a list", async () => {
    for (const [label, em] of [["a new emoji", "🥳"], ["a skin tone, 4 units", "👍🏽"], ["a family, 8 units", "👨‍👩‍👧"]]) {
      expect(await dave.status("POST", "/cheers/alice", { emoji: em }), `cheer: ${label} accepted`).toBe(200);
    }
    for (const [label, em] of [["letters", "lol"], ["an emoji then a letter (whole-string match)", "🔥x"],
      ["nine emoji, 18 units", "🎉".repeat(9)], ["empty", ""], ["a trailing space", "🎉 "]]) {
      expect(await dave.status("POST", "/cheers/alice", { emoji: em }), `cheer: ${label} rejected`).toBe(400);
    }
    expect(await dave.status("POST", "/cheers/alice", { emoji: 7 }), "cheer: emoji must be a string").toBe(400);
  });
});

describe("hardening: no listing of people or codes; bounded strings", () => {
  it("profiles, codes, bounds", async () => {
    const got = await bob.call("GET", "/users/alice");
    expect(got.status, "profile: get by uid allowed").toBe(200);
    expect(got.body, "profile: and it's a name and an emoji, nothing more (3.0)").toEqual({ uid: "alice", name: "Alice", emoji: "" });
    expect([404, 405], "profile: listing users denied").toContain(await bob.status("GET", "/users"));
    expect([404, 405], "profile: listing friend codes denied").toContain(await bob.status("GET", "/codes"));
    expect(await bob.status("POST", "/sync", { profile: { name: "x".repeat(61) } }), "profile: 61-char display name rejected").toBe(400);
    expect(await bob.status("POST", "/sync", { profile: { name: "x".repeat(60) } }), "profile: 60-char display name allowed").toBe(200);
    expect(await dave.status("POST", "/cheers/alice", { emoji: "🔥", at: "t" }), "cheer: at is the server's, never the sender's").toBe(400);
    const { id } = await squadOf(alice);
    expect(await alice.status("PUT", `/squads/${id}/row`, { studyTimeMs: -5 }), "member: negative study time rejected").toBe(400);
    expect(await alice.status("PUT", `/squads/${id}/row`, { accuracy: 101.5 }), "member: retention over 100 rejected").toBe(400);
  });
});

describe("friend edges, emoji, week, ban list, founder handoff (v2.5)", () => {
  it("edges", async () => {
    await alice.call("POST", "/sync", { week: WEEK("2026-09-13") });
    expect(await alice.status("PUT", "/friends/carol"), "edge: owner creates").toBe(200);
    expect(await alice.status("PUT", "/friends/bob", { at: 1, note: "x" }), "edge: extra field rejected").toBe(400);
    expect((await bob.call("GET", "/board")).body.friends, "edge: cannot write someone else's (edges are always the caller's)").toEqual([]);
    expect((await carol.call("PUT", "/friends/alice")).body.mutual, "edge: the named friend may learn of it (adding back says mutual)").toBe(true);
    expect(Object.keys((await bob.call("GET", "/users/alice")).body).sort(), "edge: a third person may not").toEqual(["emoji", "name", "uid"]);
    expect((await alice.call("GET", "/board")).body.friends.map((f: any) => f.uid).sort(), "edge: only the owner lists (her board is hers)").toEqual(["carol", "dave"]);
    const carolSees = (await carol.call("GET", "/board")).body.friends.find((f: any) => f.uid === "alice");
    expect(carolSees.week?.days?.["2026-09-13"]?.reviews, "edge: grants stats like the array does").toBe(10);
    expect(await alice.status("DELETE", "/friends/carol"), "edge: owner deletes").toBe(200);
    const after = (await carol.call("GET", "/board")).body.friends.find((f: any) => f.uid === "alice");
    expect(after, "edge: stats close with it, the same request").toEqual({ uid: "alice", name: "Alice", emoji: "", mutual: false });
    expect(await bob.status("POST", "/sync", { profile: { emoji: "🦊" } }), "profile: emoji within bounds").toBe(200);
    expect(await bob.status("POST", "/sync", { profile: { emoji: "x".repeat(17) } }), "profile: 17-char emoji field rejected").toBe(400);
  });

  it("member week, emoji, new cards", async () => {
    const { id } = await squadOf(alice);
    expect(await alice.status("PUT", `/squads/${id}/row`, { week: 5, emoji: "🐢" }), "member: week and emoji accepted").toBe(200);
    expect(await alice.status("PUT", `/squads/${id}/row`, { week: 8 }), "member: week over 7 rejected").toBe(400);
    expect(await alice.status("PUT", `/squads/${id}/row`, { newCards: 20 }), "member: newCards accepted").toBe(200);
    expect(await alice.status("PUT", `/squads/${id}/row`, { newCards: -1 }), "member: negative newCards rejected").toBe(400);
    expect(await alice.status("PUT", `/squads/${id}/row`, { newCards: "20" }), "member: newCards must be an int").toBe(400);
  });

  it("block and handoff", async () => {
    const { id } = await squadOf(alice);
    await bob.call("POST", `/squads/${id}/join`);
    expect(await alice.status("POST", `/squads/${id}/block/bob`), "ban: founder sets the list").toBe(200);
    expect(await bob.status("POST", `/squads/${id}/block/alice`), "ban: non-founder cannot").toBe(403);
    expect(await bob.status("POST", `/squads/${id}/join`), "ban: a blocked person cannot rejoin an open squad").toBe(403);
    expect(await carol.status("POST", `/squads/${id}/join`), "ban: others still can").toBe(200);
    expect(await alice.status("PATCH", `/squads/${id}`, { founder: "dave" }), "handoff: to a non-member rejected").toBe(403);
    expect(await alice.status("PATCH", `/squads/${id}`, { founder: "carol" }), "handoff: to a member allowed").toBe(200);
    expect(await alice.status("PATCH", `/squads/${id}`, { open: false }), "handoff: the old founder lost the keys").toBe(403);
    expect(await carol.status("PATCH", `/squads/${id}`, { open: false }), "handoff: the new founder has them").toBe(200);
  });
});

describe("friendship consent unchanged", () => {
  it("stats", async () => {
    await alice.call("POST", "/sync", { week: WEEK("2026-09-06"), heatmap: { counts: { "2026-09-06": 10 } } });
    const d = (await dave.call("GET", "/board")).body.friends.find((f: any) => f.uid === "alice");
    expect(d.week.days["2026-09-06"].reviews, "stats: friend reads").toBe(10);
    expect((await bob.call("GET", "/board")).body.friends, "stats: stranger denied (not on the board)").toEqual([]);
    expect(await bob.status("GET", "/heatmap/alice"), "stats: stranger denied (the heatmap)").toBe(403);
    expect((await dave.call("GET", "/heatmap/alice")).body.counts, "stats: friend reads the heatmap").toEqual({ "2026-09-06": 10 });
  });
});

describe("retired paths: nothing answers", () => {
  it("2.0 and older", async () => {
    expect(await alice.status("GET", `/boards/${DAY}/rows/alice`), "retired: Everyone rows unreadable").toBe(404);
    expect(await alice.status("PUT", `/boards/${DAY}/rows/alice`, { name: "x" }), "retired: Everyone rows unwritable").toBe(404);
    expect(await alice.status("PUT", "/server_board/alice", { name: "y" }), "retired: old server_board unwritable").toBe(404);
    expect(await alice.status("GET", "/server_names/busm"), "retired: directory is gone").toBe(404);
  });
});

describe("a row update must never become a join (v2.5.1)", () => {
  it("Remove sticks", async () => {
    const { id } = await squadOf(alice, "open");
    expect(await dave.status("PUT", `/squads/${id}/row`, { name: "Dave" }), "join: refused without joining (a row is no join)").toBe(403);
    expect(await dave.status("PUT", `/squads/${id}/row`, { name: "Dave", joinedAt: "t" }), "join: joinedAt isn't a row field").toBe(400);
    expect(await dave.status("POST", `/squads/${id}/join`), "join: accepted through the join").toBe(200);
    expect(await dave.status("PUT", `/squads/${id}/row`, { reviews: 7 }), "row: a member's update needs no joinedAt in the request").toBe(200);
    const s1 = await dave.call("POST", "/sync", { squads: { row: { reviews: 8 }, ids: [id] } });
    expect(s1.body.gone, "row: and works as an update-only write too (sync)").toEqual([]);
    expect(await alice.status("DELETE", `/squads/${id}/members/dave`), "remove: founder removes dave from an OPEN squad").toBe(200);
    expect(await dave.status("PUT", `/squads/${id}/row`, { name: "Dave", reviews: 9 }), "remove: an old client's next row sync cannot re-create him").toBe(403);
    expect((await rowsOf(alice, id)).map((r) => r.uid), "remove: he is really gone").toEqual(["alice"]);
    const s2 = await dave.call("POST", "/sync", { squads: { row: { reviews: 10 }, ids: [id] } });
    expect(s2.body.gone, "remove: a sync's update-only write is refused, says so, and creates nothing").toEqual([id]);
    expect((await rowsOf(alice, id)).map((r) => r.uid)).toEqual(["alice"]);
    expect(await dave.status("POST", `/squads/${id}/join`), "remove: a deliberate rejoin with the code still works (Block is what stops that)").toBe(200);
  });

  it("emoji: 16 UTF-8 bytes, the 2.x client's ceiling, is accepted", async () => {
    expect(await bob.status("POST", "/sync", { profile: { emoji: "😀".repeat(4) } })).toBe(200);
    expect(await bob.status("POST", "/sync", { profile: { emoji: "😀".repeat(9) } }), "and 18 UTF-16 units are not").toBe(400);
  });
});

describe("a code knocks its owner (v2.9)", () => {
  it("code knocks", async () => {
    await db().prepare("INSERT INTO codes VALUES ('BOB123', 'bob'), ('ALI123', 'alice')").run();
    const r = await carol.call("POST", "/codes/BOB123/add");
    expect(r.body.knocked, "code knock: holding the recipient's code opens the door").toBe(true);
    expect((await bob.call("GET", "/knocks")).body.knocks.map((k: any) => k.from)).toEqual(["carol"]);
    expect((await dave.call("GET", "/knocks")).body.knocks, "code knock: someone else's code doesn't (a code only knocks its owner)").toEqual([]);
    expect(await carol.status("POST", "/codes/NOPE00/add"), "code knock: a code that isn't anyone's doesn't").toBe(404);
    expect(await carol.status("POST", "/codes/ALI123X/add"), "code knock: the code must be six characters").toBe(404);
    expect(await dave.status("POST", "/knocks/bob", { squad: "nope" }), "code knock: no squad and no code is still refused").toBe(403);
    expect((await bob.call("GET", "/knocks")).body.knocks[0], "code knock: cannot forge the sender")
      .toEqual({ from: "carol", name: "Carol", emoji: "", squad: "" });
  });

  it("New Code (2.10)", async () => {
    await db().prepare("INSERT INTO codes VALUES ('BOB123', 'bob')").run();
    await db().prepare("UPDATE users SET code = 'BOB123' WHERE uid = 'bob'").run();
    expect((await bob.call("POST", "/codes", { code: "BOB999" })).body.code, "new code: a fresh code is claimed by its maker").toBe("BOB999");
    const theirs = (await carol.call("POST", "/codes", { code: "BOB999" })).body.code;
    expect(theirs, "new code: someone else's code can't be repointed at me").not.toBe("BOB999");
    expect(await db().prepare("SELECT uid FROM codes WHERE code = 'BOB999'").first("uid"), "new code: nor retired by anyone but its owner").toBe("bob");
    expect(await dave.status("POST", "/codes/BOB123/add"), "new code: the owner's new code retires the old one").toBe(404);
    expect(await dave.status("POST", "/codes/BOB123/add"), "new code: a knock on the retired code is refused").toBe(404);
    expect((await dave.call("POST", "/codes/BOB999/add")).body.knocked, "new code: the new one knocks").toBe(true);
  });
});

describe("my settings follow me (2.13): one doc, mine only", () => {
  it("settings", async () => {
    const mine = { v: 1, at: "2026-09-24T10:00:00Z", settings: { share_retention: false, status: "hi" } };
    expect(await bob.status("PUT", "/settings", mine), "settings: I save mine").toBe(200);
    expect((await bob.call("GET", "/settings")).body, "settings: I read mine").toEqual(mine);
    expect(await alice.status("GET", "/settings"), "settings: a friend can't read them (GET /settings is always the caller's)").toBe(404);
    await carol.call("PUT", "/settings", { ...mine, settings: { status: "carol's" } });
    expect((await bob.call("GET", "/settings")).body.settings.status, "settings: nobody else can write them").toBe("hi");
    expect([404, 405], "settings: only the one doc").toContain(await bob.status("PUT", "/settings/other", mine));
    expect(await bob.status("PUT", "/settings", { ...mine, extra: 1 }), "settings: only its three fields").toBe(400);
    expect(await bob.status("PUT", "/settings", { ...mine, settings: "all of them" }), "settings: settings must be a map").toBe(400);
    expect(await bob.status("DELETE", "/account"), "settings: I can delete mine (account deletion)").toBe(200);
    expect(await db().prepare("SELECT COUNT(*) AS n FROM settings WHERE uid = 'bob'").first("n")).toBe(0);
  });
});

describe("no batch cap in 3.0", () => {
  it("a crew of any size is one request", async () => {
    const me = await person("me", "Me");
    for (let i = 0; i < 25; i++) {
      const pal = await person(`pal${i}`);
      await pal.call("POST", "/sync", { week: WEEK(DAY, 5) });
      await befriend(pal, me);
      await befriend(me, pal);
    }
    const b = await me.call("GET", "/board");
    expect(b.status, "batch: ten friends fit one read (and so do twenty-five)").toBe(200);
    expect(b.body.friends.filter((f: any) => f.week?.days?.[DAY]?.reviews === 5), "batch: eleven don't (they do now)").toHaveLength(25);
  });
});

describe("a cheer may carry luck or a card's guid (v2.10)", () => {
  it("luck and tips", async () => {
    const lucky = { emoji: "🍀", note: "Go get it", luck: true };
    expect(await dave.status("POST", "/cheers/alice", lucky), "cheer: a good-luck line from someone added").toBe(200);
    expect(await dave.status("POST", "/cheers/alice", { ...lucky, luck: "yes" }), "cheer: luck must be a bool").toBe(400);
    const tip = { emoji: "💡", note: "Ken-tuck-y", guid: "Ab3$kQ9+zX" };
    expect(await dave.status("POST", "/cheers/alice", tip), "cheer: a tip naming a card").toBe(200);
    expect(await dave.status("POST", "/cheers/alice", { ...tip, guid: "x".repeat(41) }), "cheer: a guid past 40 characters is refused").toBe(400);
    expect(await carol.status("POST", "/cheers/alice", tip), "cheer: still only from someone the owner added").toBe(403);
  });
});

describe("markers: /version takes their place", () => {
  it("version", async () => {
    expect((await api("GET", "/version")).body, "marker: the client asks /version, once a day").toEqual({ api: 1, minClient: "3.0.0" });
    for (const m of ["rules-v2", "rules-v11", "rules-v12"]) {
      expect(await alice.status("GET", `/meta/${m}`), `marker ${m}: there are no markers any more`).toBe(404);
    }
  });
});
