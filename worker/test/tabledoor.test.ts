import { env } from "cloudflare:workers";
import { describe, expect, it } from "vitest";
import worker from "../src/index";
import { SHUT } from "../src/table";
import { BASE, api, befriend, person } from "./helpers";

// 3.9.9's review of Pip Party's door: what a new tab's id, a script's ids and a seat's own presence could do.

type Sock = { ws: WebSocket; got: any[]; closed: { code: number } | null };

async function seat(code: string, cid: string, opts: { key?: string; ip?: string; token?: string } = {}) {
  const q = new URLSearchParams({ c: cid });
  if (opts.key) q.set("k", opts.key);
  const headers: Record<string, string> = { Upgrade: "websocket", Origin: "https://duecrew.com", "CF-Connecting-IP": opts.ip ?? "203.0.113.9" };
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
  for (let i = 0; i < 400; i++) { const v = f(); if (v) return v; await new Promise((r) => setTimeout(r, 5)); }
  throw new Error(`waited for ${what}`);
}
const said = (s: Sock, f: (m: any) => boolean) => s.got.find(f);
const say = (s: Sock, p: unknown) => s.ws.send(JSON.stringify({ t: "p", p }));
const tell = (s: Sock, m: unknown) => s.ws.send(JSON.stringify(m));
const cid = (n: string) => `client-${n}`.padEnd(20, "x");
const hello = (s: Sock) => until(() => [...s.got].reverse().find((m) => m.t === "hi"), "a hello");
async function refused(code: string, c: string, opts: Parameters<typeof seat>[2] = {}) {
  const r = await seat(code, c, opts);
  expect(r.status).toBe(101);
  return (await until(() => r.s!.closed, "the close")).code;
}
async function leave(...socks: Sock[]) {
  for (const s of socks) if (!s.closed) { try { s.ws.close(1000, "done"); } catch { /* closed */ } }
  await until(() => socks.every((s) => s.closed), "everyone gone");
}
async function opened(uid = "sam") {
  const sam = await person(uid);
  const t = await api("POST", "/table", { token: sam.token });
  expect(t.status).toBe(200);
  return { ...(t.body as { code: string; key: string }), sam };
}
async function tvAt(code: string, key: string, door = "ask") {
  const tv = (await seat(code, cid("tv"), { key })).s!;
  await hello(tv);
  if (door !== "ask") { tell(tv, { t: "door", door }); await until(() => said(tv, (m) => m.t === "door" && m.door === door), "the door"); }
  return tv;
}

describe("Pip Party's door, after the review (3.9.9)", () => {
  it("turned away stays away: a stranger's new tab waits at an open door, a crewmate's is refused under any id", async () => {
    const { code, key, sam } = await opened();
    const tv = await tvAt(code, key, "open");
    const kai = (await seat(code, cid("kai"))).s!;
    const k = await hello(kai);
    expect(k.wait).toBeUndefined();
    tell(tv, { t: "away", peer: k.you });
    expect((await until(() => kai.closed, "Kai sent off")).code).toBe(SHUT.away);
    expect(await refused(code, cid("kai"))).toBe(SHUT.away);
    const kai2 = (await seat(code, cid("kai-new-tab"))).s!;  // a new tab: a new id, the same network
    const k2 = await hello(kai2);
    expect(k2.wait).toBe(true);        // at the door, for the host to answer
    expect(k2.peers).toEqual([]);      // and hearing nothing
    // another network walks through the open door as before
    const ana = (await seat(code, cid("ana"), { ip: "198.51.100.20" })).s!;
    expect((await hello(ana)).wait).toBeUndefined();
    // the host changing the door to open again doesn't seat who waits from that network
    tell(tv, { t: "door", door: "open" });
    await until(() => tv.got.filter((m) => m.t === "door" && m.door === "open").length >= 2, "open again");
    expect(said(kai2, (m) => m.t === "hi" && !m.wait)).toBeUndefined();
    // a crewmate turned away: refused under a new tab's id too
    const dre = await person("dre", "Dre Lee");
    await befriend(sam, dre);
    await befriend(dre, sam);
    const d = (await seat(code, cid("dre"), { token: dre.token, ip: "203.0.113.77" })).s!;
    const dh = await hello(d);
    expect(dh.wait).toBeUndefined();
    tell(tv, { t: "away", peer: dh.you });
    expect((await until(() => d.closed, "Dre sent off")).code).toBe(SHUT.away);
    expect(await refused(code, cid("dre-new-tab"), { token: dre.token, ip: "203.0.113.77" })).toBe(SHUT.away);
    // and nobody else on Dre's network is held at the door for it (a crewmate is known by who they are)
    const lee = (await seat(code, cid("lee"), { ip: "203.0.113.77" })).s!;
    expect((await hello(lee)).wait).toBeUndefined();
    await leave(tv, kai2, ana, lee);
  });

  it("a seat outlasts 64 other ids: her own phone comes back to a locked table", async () => {
    const { code, key } = await opened();
    const tv = await tvAt(code, key, "open");
    const ana = (await seat(code, cid("ana"), { ip: "198.51.100.20" })).s!;
    expect((await hello(ana)).wait).toBeUndefined();
    for (let i = 0; i < 64; i++) {
      const s = (await seat(code, cid(`churn${i}`), { ip: "192.0.2.66" })).s!;
      await hello(s);
      await leave(s);
    }
    tell(tv, { t: "lock", on: true });
    await until(() => said(tv, (m) => m.t === "door" && m.locked), "locked");
    await leave(ana);  // her phone sleeps
    const again = (await seat(code, cid("ana"), { ip: "198.51.100.20" })).s!;
    expect((await hello(again)).wait).toBeUndefined();
    await leave(tv, again);
  });

  it("a seat's answer goes to the TV alone: another seat hears the name, never the pick", async () => {
    const { code, key } = await opened();
    const tv = await tvAt(code, key, "open");
    const ana = (await seat(code, cid("ana"))).s!, kai = (await seat(code, cid("kai"), { ip: "198.51.100.20" })).s!;
    await hello(ana); await hello(kai);
    say(ana, { r: "p", n: "Ana", a: { s: 3, o: 2 } });
    const atTv = await until(() => said(tv, (m) => m.t === "p" && m.p && m.p.n === "Ana"), "the TV hears Ana");
    expect(atTv.p.a).toEqual({ s: 3, o: 2 });
    const heard = await until(() => said(kai, (m) => m.t === "p" && m.p && m.p.n === "Ana"), "Kai hears Ana");
    expect(heard.p).toEqual({ r: "p", n: "Ana" });
    // someone sitting down later is told who's here without their picks either
    const lee = (await seat(code, cid("lee"), { ip: "198.51.100.21" })).s!;
    const hi = await hello(lee);
    expect(hi.peers.find((p: any) => p.p && p.p.n === "Ana").p).toEqual({ r: "p", n: "Ana" });
    await leave(tv, ana, kai, lee);
  });
});
