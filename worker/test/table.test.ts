import { createExecutionContext, runDurableObjectAlarm, waitOnExecutionContext } from "cloudflare:test";
import { env } from "cloudflare:workers";
import { describe, expect, it } from "vitest";
import site from "../../site/src/index";
import worker from "../src/index";
import { DOOR, PRESENCE_MAX, SEATS, SHUT, okPresence } from "../src/table";
import { BASE, api, befriend, person } from "./helpers";

// 3.9.5, game night: a table is a live room for one night. Its host opens it
// signed in; a phone joins with the code. The host's crew (signed in, mutual
// friends) sit straight down; anyone else waits at the door till the host
// lets them in. Each seated socket's presence goes to everyone at the table,
// and only the host's socket is marked host.

type Sock = { ws: WebSocket; got: any[]; closed: { code: number } | null };

async function seat(code: string, cid: string, opts: { key?: string; origin?: string; ip?: string; token?: string } = {}) {
  const q = new URLSearchParams({ c: cid });
  if (opts.key) q.set("k", opts.key);
  const headers: Record<string, string> = { Upgrade: "websocket", Origin: opts.origin ?? "https://duecrew.com", "CF-Connecting-IP": opts.ip ?? "203.0.113.9" };
  if (opts.token) headers.Cookie = `dc_session=${opts.token}`;
  const res = await worker.fetch(new Request(`${BASE}/table/${code}/ws?${q}`, { headers }), { ...env } as any);
  if (res.status !== 101) return { status: res.status, body: await res.json() as any };
  const ws = res.webSocket!;
  const s: Sock = { ws, got: [], closed: null };
  ws.accept();
  ws.addEventListener("message", (e) => { s.got.push(JSON.parse(e.data as string)); });
  ws.addEventListener("close", (e) => { s.closed = { code: e.code }; });
  return { status: 101, s };
}

async function until<T>(f: () => T | undefined | null | false, what: string): Promise<T> {
  for (let i = 0; i < 200; i++) {
    const v = f();
    if (v) return v;
    await new Promise((r) => setTimeout(r, 5));
  }
  throw new Error(`waited for ${what}`);
}
const said = (s: Sock, f: (m: any) => boolean) => s.got.find(f);
const say = (s: Sock, p: unknown) => s.ws.send(JSON.stringify({ t: "p", p }));
const tell = (s: Sock, m: unknown) => s.ws.send(JSON.stringify(m));
const cid = (n: string) => `client-${n}`.padEnd(20, "x");
const hello = (s: Sock) => until(() => [...s.got].reverse().find((m) => m.t === "hi"), "a hello");
/** Turned away at the socket: why, as its close code. */
async function refused(code: string, c: string, opts: Parameters<typeof seat>[2] = {}) {
  const r = await seat(code, c, opts);
  expect(r.status).toBe(101);
  return (await until(() => r.s!.closed, "the close")).code;
}
/** Hang up and wait for the table to hear it, so nothing is left open when the test ends. */
async function leave(...socks: Sock[]) {
  for (const s of socks) if (!s.closed) { try { s.ws.close(1000, "done"); } catch { /* closed */ } }
  await until(() => socks.every((s) => s.closed), "everyone gone");
}

// while Sam tests it, an admin opens a table (ADMINS_ONLY)
const ADMIN = { ADMIN_UIDS: "sam" } as any;
const open = (who: { token: string }) => api("POST", "/table", { token: who.token, env: ADMIN });

async function opened() {
  const sam = await person("sam");
  const t = await open(sam);
  expect(t.status).toBe(200);
  expect(t.body.code).toMatch(/^[A-HJ-NP-Z]{4}$/);
  return { ...(t.body as { code: string; key: string }), sam };
}
/** The host's TV, with the door as given. */
async function tvAt(code: string, key: string, door = "ask") {
  const tv = (await seat(code, cid("tv"), { key })).s!;
  await hello(tv);
  if (door !== "ask") { tell(tv, { t: "door", door }); await until(() => said(tv, (m) => m.t === "door" && m.door === door), "the door"); }
  return tv;
}

describe("game night: a table", () => {
  it("is opened signed in, joined with its code; the host lets a stranger in, presence goes round, and only the host is host", async () => {
    expect((await api("POST", "/table")).status).toBe(401);
    const { code, key } = await opened();
    const tv = (await seat(code, cid("tv"), { key })).s!;
    const hi = await hello(tv);
    expect(hi).toMatchObject({ host: true, peers: [], door: "ask", locked: false });
    // no account: at the door, hearing nothing, and the host hears only a name
    const ana = (await seat(code.toLowerCase(), cid("ana"))).s!;
    const waiting = await hello(ana);
    expect(waiting).toMatchObject({ host: false, wait: true, peers: [] });
    expect(waiting.you).toMatch(/^[0-9a-f]{16}$/);
    expect(waiting.you).not.toContain("client");  // the label isn't the id it came from
    say(ana, { r: "p", n: "Ana", t: 5, a: { s: 1, w: "edema" }, host: true });
    const knock = await until(() => said(tv, (m) => m.t === "p" && m.peer === waiting.you && m.p.n === "Ana"), "the knock");
    expect(knock).toMatchObject({ host: false, wait: true, crew: null, p: { r: "p", n: "Ana", t: 5 } });
    expect(knock.p.a).toBeUndefined();  // a name, nothing more, till they're in
    say(tv, { r: "tv", code, g: { m: "lobby", gm: "imposter", s: 1 } });
    // a phone can't open the door for itself
    tell(ana, { t: "admit", peer: waiting.you });
    tell(ana, { t: "door", door: "open" });
    await new Promise((r) => setTimeout(r, 30));
    expect(ana.got.filter((m) => m.t !== "hi")).toEqual([]);
    // the host lets them in: hello again, with the table
    tell(tv, { t: "admit", peer: waiting.you });
    const inside = await until(() => said(ana, (m) => m.t === "hi" && !m.wait), "in");
    expect(inside.peers).toEqual([{ peer: hi.you, host: true, p: { r: "tv", code, g: { m: "lobby", gm: "imposter", s: 1 } } }]);
    expect(inside.p).toEqual({ r: "p", n: "Ana", t: 5 });
    const sat = await until(() => said(tv, (m) => m.t === "p" && m.peer === waiting.you && !m.wait), "the TV hears them sit down");
    expect(sat.host).toBe(false);
    // a phone's presence reaches the TV; claiming to be the host in it changes nothing
    say(ana, { r: "p", n: "Ana", host: true, a: { s: 1, w: "edema" } });
    const named = await until(() => said(tv, (m) => m.t === "p" && m.p.a), "the answer");
    expect(named.host).toBe(false);
    say(tv, { r: "tv", code, g: { m: "game", gm: "imposter", s: 2 } });
    const game = await until(() => said(ana, (m) => m.t === "p" && m.p.g?.m === "game"), "the game");
    expect(game).toMatchObject({ host: true, peer: hi.you });
    expect(game.crew).toBeUndefined();  // who's crew is the host's to know
    // a key that isn't the table's is a phone like any other
    const fake = (await seat(code, cid("fake"), { key: "not-the-key" })).s!;
    expect(await hello(fake)).toMatchObject({ host: false, wait: true });
    // someone leaves: everyone hears it
    await leave(ana);
    await until(() => said(tv, (m) => m.t === "bye" && m.peer === waiting.you), "the goodbye");
    await leave(tv, fake);
  });

  it("seats the host's crew straight away, by the name on their account; anyone else waits", async () => {
    const { code, key, sam } = await opened();
    const dre = await person("dre", "Dre Lee"), maya = await person("maya");
    await befriend(sam, dre);
    await befriend(dre, sam);
    await befriend(maya, sam);  // one way: not crew
    expect((await api("GET", `/table/${code}`, { headers: { Cookie: `dc_session=${dre.token}` } })).body).toEqual({ open: true, full: false, door: "ask", crew: true });
    expect((await api("GET", `/table/${code}`, { headers: { Cookie: `dc_session=${maya.token}` } })).body.crew).toBe(false);
    expect((await api("GET", `/table/${code}`)).body).toEqual({ open: true, full: false, door: "ask", crew: false });
    const tv = await tvAt(code, key);
    const d = (await seat(code, cid("dre"), { token: dre.token })).s!;
    const dh = await hello(d);
    expect(dh.wait).toBeUndefined();
    expect(dh.peers).toEqual([{ peer: (await hello(tv)).you, host: true, p: {} }]);
    expect(await until(() => said(tv, (m) => m.t === "p" && m.peer === dh.you), "Dre sits down")).toMatchObject({ crew: "Dre Lee" });
    const m = (await seat(code, cid("maya"), { token: maya.token })).s!;
    expect(await hello(m)).toMatchObject({ wait: true });
    expect(await until(() => said(tv, (x) => x.t === "p" && x.wait), "Maya waits")).toMatchObject({ crew: null });
    // the host on their own phone is their own crew
    const own = (await seat(code, cid("sam-phone"), { token: sam.token })).s!;
    expect((await hello(own)).wait).toBeUndefined();
    // a crew name a phone sends itself is dropped on the way in
    const fake = await worker.fetch(new Request(`${BASE}/table/${code}/ws?c=${cid("liar")}`, { headers: {
      Upgrade: "websocket", Origin: "https://duecrew.com", "CF-Connecting-IP": "203.0.113.9", "x-dc-crew": "Sam" } }), { ...env } as any);
    const fs: Sock = { ws: fake.webSocket!, got: [], closed: null };
    fs.ws.accept();
    fs.ws.addEventListener("message", (e) => { fs.got.push(JSON.parse(e.data as string)); });
    fs.ws.addEventListener("close", (e) => { fs.closed = { code: e.code }; });
    expect(await hello(fs)).toMatchObject({ wait: true });
    await leave(tv, d, m, own, fs);
  });

  it("is the host's door: crew only, anyone with the code, locked, and turned away for the night", async () => {
    const { code, key, sam } = await opened();
    const dre = await person("dre");
    await befriend(sam, dre);
    await befriend(dre, sam);
    const tv = await tvAt(code, key);
    const ana = (await seat(code, cid("ana"))).s!;
    const a = await hello(ana);
    // crew only: who's waiting goes, a stranger can't come, crew still can
    tell(tv, { t: "door", door: "crew" });
    expect((await until(() => ana.closed, "Ana sent off")).code).toBe(SHUT.crewOnly);
    await until(() => said(tv, (m) => m.t === "bye" && m.peer === a.you), "the host hears it");
    expect(await refused(code, cid("kai"))).toBe(SHUT.crewOnly);
    expect((await api("GET", `/table/${code}`)).body.door).toBe("crew");
    const d = (await seat(code, cid("dre"), { token: dre.token })).s!;
    expect((await hello(d)).wait).toBeUndefined();
    // anyone with the code: who's waiting comes in, and so does a newcomer
    tell(tv, { t: "door", door: "ask" });
    const jo = (await seat(code, cid("jo"))).s!;
    expect(await hello(jo)).toMatchObject({ wait: true });
    tell(tv, { t: "door", door: "open" });
    await until(() => said(jo, (m) => m.t === "hi" && !m.wait), "Jo let in");
    const kai = (await seat(code, cid("kai"))).s!;
    expect((await hello(kai)).wait).toBeUndefined();
    // locked: nobody new, but who sat down can come back
    tell(tv, { t: "lock", on: true });
    await until(() => said(tv, (m) => m.t === "door" && m.locked), "locked");
    expect(await refused(code, cid("lee"))).toBe(SHUT.locked);
    await leave(kai);
    const kai2 = (await seat(code, cid("kai"))).s!;
    expect((await hello(kai2)).wait).toBeUndefined();
    // turned away: gone, and not back tonight, even unlocked
    const k = await hello(kai2);
    tell(tv, { t: "away", peer: k.you });
    expect((await until(() => kai2.closed, "Kai sent off")).code).toBe(SHUT.away);
    await until(() => said(jo, (m) => m.t === "bye" && m.peer === k.you), "the table hears it");
    tell(tv, { t: "lock", on: false });
    await until(() => said(tv, (m) => m.t === "door" && !m.locked), "unlocked");
    expect(await refused(code, cid("kai"))).toBe(SHUT.away);
    // and none of it from a phone
    tell(jo, { t: "away", peer: (await hello(tv)).you });
    tell(jo, { t: "lock", on: true });
    await new Promise((r) => setTimeout(r, 30));
    expect(tv.closed).toBeNull();
    const lee = (await seat(code, cid("lee"))).s!;  // still unlocked, still open
    expect((await hello(lee)).wait).toBeUndefined();
    await leave(tv, d, jo, lee);
  });

  it("whispers a seat its own part, from the host alone, and never to the door", async () => {
    const { code, key } = await opened();
    const tv = await tvAt(code, key);
    const ana = (await seat(code, cid("ana"))).s!, kai = (await seat(code, cid("kai"))).s!;
    const a = await hello(ana), k = await hello(kai);
    tell(tv, { t: "admit", peer: a.you });
    await until(() => said(ana, (m) => m.t === "hi" && !m.wait), "Ana in");
    tell(tv, { t: "w", to: a.you, p: { gm: "rounds", hand: ["Na-K-2Cl", "ATN"] } });
    tell(tv, { t: "w", to: k.you, p: { gm: "rounds", hand: ["at the door"] } });
    const w = await until(() => said(ana, (m) => m.t === "w"), "Ana's whisper");
    expect(w).toEqual({ t: "w", p: { gm: "rounds", hand: ["Na-K-2Cl", "ATN"] } });
    await new Promise((r) => setTimeout(r, 30));
    expect(kai.got.filter((m) => m.t === "w")).toEqual([]);  // not let in: nothing
    expect(tv.got.filter((m) => m.t === "w")).toEqual([]);
    // a phone can't whisper; a bad one gets an error
    tell(ana, { t: "w", to: k.you, p: { gm: "x" } });
    tell(tv, { t: "w", to: "nobody", p: { a: 1 } });
    await until(() => said(tv, (m) => m.t === "err" && m.error === "bad_whisper"), "a bad whisper");
    await new Promise((r) => setTimeout(r, 30));
    expect(kai.got.filter((m) => m.t === "w")).toEqual([]);
    await leave(tv, ana, kai);
  });

  it("passes on only plain presences of a size", async () => {
    const { code, key } = await opened();
    const tv = await tvAt(code, key, "open");
    const ana = (await seat(code, cid("ana"))).s!;
    await hello(ana);
    say(ana, { r: "p", n: "x".repeat(PRESENCE_MAX) });
    await until(() => said(ana, (m) => m.t === "err" && m.error === "bad_presence"), "too big");
    say(ana, { "not a key": 1 });
    ana.ws.send(JSON.stringify({ t: "nope", p: { n: "Ana" } }));
    ana.ws.send("{broken");
    say(ana, { r: "p", n: "Ana" });
    await until(() => said(tv, (m) => m.t === "p" && m.p.n === "Ana"), "the good one");
    expect(tv.got.filter((m) => m.t === "p" && m.p && (m.p["not a key"] || String(m.p.n || "").length > 100))).toEqual([]);
    expect(okPresence({ a: { b: { c: { d: { e: { f: { g: { h: 1 } } } } } } } })).toBe(false);  // nine deep
    expect(okPresence({ a: [1, "two", null, true, { b: 3 }] })).toBe(true);
    expect(okPresence([1])).toBe(false);
    await leave(tv, ana);
  });

  it("keeps a phone's seat when it comes back, and has room for twelve at the table and six at the door", async () => {
    const { code, key } = await opened();
    const tv = await tvAt(code, key);
    const ana = (await seat(code, cid("ana"))).s!;
    const first = await hello(ana);
    tell(tv, { t: "admit", peer: first.you });
    await until(() => said(ana, (m) => m.t === "hi" && !m.wait), "in");
    say(ana, { r: "p", n: "Ana" });
    await until(() => said(tv, (m) => m.t === "p" && m.p.n === "Ana"), "name");
    const again = (await seat(code, cid("ana"))).s!;
    const back = await hello(again);
    expect(back.you).toBe(first.you);
    expect(back.wait).toBeUndefined();  // let in once is let in for the night
    expect(back.p).toEqual({ r: "p", n: "Ana" });  // what it had said, still there
    await until(() => ana.closed, "the old line closed");
    expect(ana.closed!.code).toBe(SHUT.replaced);
    const door: Sock[] = [];
    for (let i = 0; i < DOOR; i++) door.push((await seat(code, cid(`d${i}`), { ip: `198.51.100.${100 + i}` })).s!);
    expect(await refused(code, cid("d-late"), { ip: "198.51.100.199" })).toBe(SHUT.full);
    tell(tv, { t: "door", door: "open" });
    await until(() => door.every((s) => said(s, (m) => m.t === "hi" && !m.wait)), "the door let in");
    const more: Sock[] = [];
    for (let i = 0; more.length + door.length + 2 < SEATS; i++) more.push((await seat(code, cid(`p${i}`), { ip: `198.51.100.${i}` })).s!);
    expect(await refused(code, cid("late"), { ip: "198.51.100.200" })).toBe(SHUT.full);
    expect((await api("GET", `/table/${code}`)).body.full).toBe(true);
    await leave(tv, again, ...door, ...more);
  });

  it("is no table without its code, from another site, or without a socket", async () => {
    const { code } = await opened();
    const none = await seat(code === "ZZZZ" ? "YYYY" : "ZZZZ", cid("x"));
    expect([none.status, none.body?.error]).toEqual([404, "no_table"]);
    expect((await seat(code, cid("x"), { origin: "https://evil.example" })).status).toBe(403);
    expect((await seat(code, "short")).status).toBe(400);
    expect((await api("GET", `/table/${code}/ws`)).status).toBe(426);
    // before a socket, a phone asks whether there's a table at all
    expect((await api("GET", `/table/${code}`)).body).toEqual({ open: true, full: false, door: "ask", crew: false });
    expect((await api("GET", `/table/${code === "ZZZZ" ? "YYYY" : "ZZZZ"}`)).status).toBe(404);
  });

  it("closes once its host is gone, and stays while they're here", async () => {
    const { code, key } = await opened();
    const stub = env.TABLES.get(env.TABLES.idFromName(code));
    const tv = await tvAt(code, key, "open");
    const ana = (await seat(code, cid("ana"))).s!;
    await hello(ana);
    expect(await runDurableObjectAlarm(stub)).toBe(true);  // the host is here: it stays
    expect(ana.closed).toBeNull();
    await leave(tv);
    await until(() => said(ana, (m) => m.t === "bye"), "the host left");
    expect(await runDurableObjectAlarm(stub)).toBe(true);
    await until(() => ana.closed, "closed");
    expect(ana.closed!.code).toBe(SHUT.closed);
    expect((await seat(code, cid("ana"))).status).toBe(404);
  });

  it("is opened by an admin alone while Sam tests it, and has a ceiling", async () => {
    const sam = await person("sam"), dre = await person("dre");
    expect((await api("POST", "/table", { token: dre.token, env: ADMIN })).body).toEqual({ error: "not_found" });  // as an admin route answers
    expect((await sam.call("POST", "/table")).status).toBe(404);  // sam, with no admins set
    for (let i = 0; i < 10; i++) expect((await open(sam)).status).toBe(200);
    expect((await open(sam)).status).toBe(429);
  });

  it("is reached through duecrew.com: the page with a policy that lets its socket out, and the socket through the API's binding", async () => {
    const siteEnv = {
      ASSETS: { fetch: async (req: Request) => new Response(new URL(req.url).pathname === "/table" ? "<main id=app></main>" : "static", { headers: { "content-type": "text/html" } }) },
      API: { fetch: (req: Request) => worker.fetch(req, { ...env, EMAIL: undefined, ...ADMIN } as any) },
    };
    const via = async (path: string, headers: Record<string, string> = {}) => {
      const ctx = createExecutionContext();
      const res = await site.fetch(new Request(`https://duecrew.com${path}`, { headers: { "CF-Connecting-IP": "198.51.100.77", ...headers } }), siteEnv, ctx);
      await waitOnExecutionContext(ctx);
      return res;
    };
    const sam = await person("sam"), dre = await person("dre");
    // while Sam tests it, /table is an admin's alone; a join link is anyone's
    const signedOut = await via("/table");
    expect([signedOut.status, signedOut.headers.get("location")]).toEqual([302, "/sign-in?next=/table"]);
    const notAdmin = await via("/table", { Cookie: `dc_session=${dre.token}` });
    expect([notAdmin.status, notAdmin.headers.get("location")]).toEqual([302, "/home"]);
    for (const [path, who] of [["/table", sam.token], ["/table/", sam.token], ["/t/MKQZ", ""], ["/t/mkqz/", ""], ["/t/MKQZ", dre.token]]) {
      const res = await via(path, who ? { Cookie: `dc_session=${who}` } : {});
      expect(res.status).toBe(200);
      expect(await res.text()).toContain("<main id=app>");
      expect(res.headers.get("content-security-policy")).toContain("connect-src 'self' wss://duecrew.com");
      expect(res.headers.get("cache-control")).toBe("no-store");
    }
    expect(await (await via("/t/MKQZ5")).text()).toBe("static");  // not a code: the static files', as before
    const t = await open(sam);
    const { code, key } = t.body;
    const res = await via(`/api/table/${code}/ws?c=${cid("tv")}&k=${key}`, { Upgrade: "websocket", Origin: "https://duecrew.com" });
    expect(res.status).toBe(101);
    const ws = res.webSocket!;
    const s: Sock = { ws, got: [], closed: null };
    ws.accept();
    ws.addEventListener("message", (e) => { s.got.push(JSON.parse(e.data as string)); });
    ws.addEventListener("close", (e) => { s.closed = { code: e.code }; });
    expect((await until(() => said(s, (m) => m.t === "hi"), "hello through the site")).host).toBe(true);
    await leave(s);
  });
});
