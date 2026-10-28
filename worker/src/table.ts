// Game night (duecrew.com/table): a table is a live room for one night, a
// Durable Object per code. Someone signed in opens it (POST /table) and is
// its host, the TV; a phone joins with the code (GET /table/{code}/ws). Each
// seat keeps one presence object (a name, an answer; the host's is the game
// itself) that the table hands to everyone sitting at it. Only the host's
// connection is marked host, so a phone can't pass itself off as the TV.
//
// The door: the host's crew (signed in here, mutual friends) sit straight
// down; anyone else waits at the door till the host lets them in ("ask", the
// default). The host can make it crew only, or let in anyone with the code;
// lock the table, so only who's sat down can come back; and turn someone
// away for the night. Only the host hears the door, and only the host learns
// who's crew (their name on the account). A phone at the door hears nothing.
// The host whispers each seat its own part of a game (a hand, a topic, the
// key): to that phone alone, never kept.
//
// Nothing goes to D1 but the rate limits, and nothing is kept: a table
// closes after TABLE_HOURS, or once its host has been gone HOST_GONE_MIN.
// No card's words come here: the games' packs are the page's own.

import { DurableObject } from "cloudflare:workers";
import { authenticate } from "./auth";
import { limitOrThrow } from "./limits";
import { isAdmin } from "./notices";
import { Env, HttpError, clientIp, json, newToken, sha256Hex, timingSafeEqual } from "./util";

/** While Sam tests it, only the admins (ADMINS, ADMIN_UIDS) open a table, and
 *  duecrew.com/table is theirs alone; anyone they let in still plays from a
 *  join link. Set it false, here and in site/src/index.ts, when it goes wider. */
export const ADMINS_ONLY = true;
export const TABLE_HOURS = 4;
export const HOST_GONE_MIN = 15;
export const SEATS = 12;            // sat down at once, the TV's included: eight players, and room to reconnect
export const DOOR = 6;              // waiting at the door at once
export const PRESENCE_MAX = 4096;   // one connection's presence, as JSON
export const DOORS = ["ask", "crew", "open"] as const;
export type Door = (typeof DOORS)[number];
/** Why a socket closed, for the page to say (a refused socket can't read a body). */
export const SHUT = { closed: 4000, replaced: 4001, anotherHost: 4002, away: 4003, crewOnly: 4004, locked: 4005, full: 4006 } as const;
const MSG_MAX = 6000;
const RATE = 30;                    // messages a second, a connection (a dial being turned)
const HOST_RATE = 120;              // the host's: a presence and a whisper a seat, each step
const TABLES_PER_HOUR = 10;         // tables one person opens
const JOINS_PER_HOUR = 200;         // connections and checks from one address
const REMEMBER = 64;                // who sat down, who was turned away: the newest
const LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ";  // no I or O: read off a TV across a room
const CREW = "x-dc-crew";           // set by connect() alone (it drops a client's own): the crew's name

type Opened = { key: string; until: number; uid: string };
type Room = { door: Door; locked: boolean; seated: string[]; away: string[] };
type Conn = { peer: string; host: boolean; ok: boolean; crew: string | null; p: Record<string, unknown>; hits: number[] };

const tableCode = () => Array.from(crypto.getRandomValues(new Uint8Array(4)), (b) => LETTERS[b % LETTERS.length]).join("");
const KEY_RE = /^[A-Za-z_][A-Za-z0-9_]{0,31}$/;
const PEER_RE = /^[0-9a-f]{16}$/;
const keepNewest = (xs: string[], x: string) => (xs.includes(x) ? xs : xs.concat(x).slice(-REMEMBER));

/** A presence a table passes on: a plain object of up to 24 named fields,
 *  plain JSON at most 8 deep, PRESENCE_MAX as text. */
export function okPresence(p: unknown): p is Record<string, unknown> {
  if (!p || typeof p !== "object" || Array.isArray(p)) return false;
  const keys = Object.keys(p);
  if (keys.length > 24 || !keys.every((k) => KEY_RE.test(k))) return false;
  let nodes = 0;
  const plain = (v: unknown, depth: number): boolean => {
    if (++nodes > 2000 || depth > 8) return false;
    if (v === null || typeof v === "string" || typeof v === "boolean") return true;
    if (typeof v === "number") return Number.isFinite(v);
    if (Array.isArray(v)) return v.length <= 64 && v.every((x) => plain(x, depth + 1));
    if (typeof v === "object") return Object.keys(v as object).length <= 64 && Object.values(v as object).every((x) => plain(x, depth + 1));
    return false;
  };
  if (!plain(p, 1)) return false;
  return new TextEncoder().encode(JSON.stringify(p)).length <= PRESENCE_MAX;
}

/** What someone at the door shows the host: a name, nothing more. */
const atDoor = (p: Record<string, unknown>) => ({ r: "p", n: typeof p.n === "string" ? p.n.slice(0, 16) : "", ...(typeof p.t === "number" ? { t: p.t } : {}) });

/** One connection as another hears it; the host also hears who's crew and who's waiting. */
const view = (c: Conn, toHost: boolean) => ({ peer: c.peer, host: c.host, p: c.p, ...(toHost ? { crew: c.crew, ...(c.ok ? {} : { wait: true }) } : {}) });

export class Table extends DurableObject<Env> {
  socks = new Map<WebSocket, Conn>();
  room: Room | null = null;

  private async rules(): Promise<Room> {
    if (!this.room) this.room = (await this.ctx.storage.get<Room>("room")) ?? { door: "ask", locked: false, seated: [], away: [] };
    return this.room;
  }
  private async keep() { if (this.room) await this.ctx.storage.put("room", this.room); }

  /** Opened by its host, once: false when the code is someone's table now. */
  async open(key: string, uid: string): Promise<boolean> {
    const cur = await this.ctx.storage.get<Opened>("open");
    if (cur && cur.until > Date.now()) return false;
    await this.ctx.storage.deleteAll();  // an old night's door doesn't carry over
    this.room = null;
    const until = Date.now() + TABLE_HOURS * 3600_000;
    await this.ctx.storage.put("open", { key, until, uid });
    await this.ctx.storage.setAlarm(Math.min(until, Date.now() + HOST_GONE_MIN * 60_000));  // a host who never comes
    return true;
  }

  /** For the API: open or not, whose, its door, a seat free. */
  async info(): Promise<{ open: boolean; uid: string; door: Door; full: boolean }> {
    const open = await this.ctx.storage.get<Opened>("open");
    const ok = !!open && open.until > Date.now();
    return { open: ok, uid: ok ? open!.uid : "", door: (await this.rules()).door, full: this.count(true) >= SEATS };
  }

  private count(ok: boolean) { let n = 0; for (const c of this.socks.values()) if (c.ok === ok) n++; return n; }

  async fetch(req: Request): Promise<Response> {
    const open = await this.ctx.storage.get<Opened>("open");
    if (!open || open.until <= Date.now()) return json({ error: "no_table" }, 404);
    const room = await this.rules();
    const url = new URL(req.url);
    const cid = url.searchParams.get("c") || "";
    if (!/^[A-Za-z0-9_-]{16,64}$/.test(cid)) return json({ error: "bad_client" }, 400);
    const k = url.searchParams.get("k");
    const host = !!k && timingSafeEqual(await sha256Hex(`table:${k}`), open.key);
    let crew: string | null = null;
    try { const c = req.headers.get(CREW); crew = c === null ? null : decodeURIComponent(c).slice(0, 40) || "Crew"; } catch { crew = null; }
    // the label everyone sees; only its own page knows the id it comes from
    const peer = (await sha256Hex(`peer:${cid}`)).slice(0, 16);
    const back = room.seated.includes(peer);
    let shut = 0;
    if (!host) {
      if (room.away.includes(peer)) shut = SHUT.away;
      else if (room.door === "crew" && crew === null && !back) shut = SHUT.crewOnly;
      else if (room.locked && !back) shut = SHUT.locked;
    }
    let carried: Record<string, unknown> = {};
    if (!shut) {
      for (const [ws, c] of this.socks) {
        if (c.peer === peer) { carried = c.p; this.socks.delete(ws); this.closeOne(ws, SHUT.replaced, "replaced"); }  // the same phone again: its seat stays
        else if (host && c.host) { this.socks.delete(ws); this.closeOne(ws, SHUT.anotherHost, "another host"); this.gone(c); }
      }
    }
    const ok = host || crew !== null || back || room.door === "open";
    if (!shut && this.count(ok) >= (ok ? SEATS : DOOR)) shut = SHUT.full;
    const [client, server] = Object.values(new WebSocketPair());
    server.accept();
    if (shut) {
      this.closeOne(server, shut, "no");
      return new Response(null, { status: 101, webSocket: client });
    }
    const me: Conn = { peer, host, ok, crew, p: ok ? carried : atDoor(carried), hits: [] };
    this.socks.set(server, me);
    server.addEventListener("message", (e) => { void this.message(server, e.data); });
    server.addEventListener("close", () => this.drop(server));
    server.addEventListener("error", () => this.drop(server));
    if (ok && !host && !back) { room.seated = keepNewest(room.seated, peer); await this.keep(); }
    this.greet(server, me, room);
    this.tell(server, me);
    return new Response(null, { status: 101, webSocket: client });
  }

  /** Hello: who I am, and who's sitting here (the host also sees the door). */
  private greet(ws: WebSocket, me: Conn, room: Room) {
    if (!me.ok) { this.send(ws, { t: "hi", you: me.peer, host: false, wait: true, peers: [] }); return; }
    const peers = [...this.socks.values()].filter((c) => c !== me && (c.ok || me.host)).map((c) => view(c, me.host));
    this.send(ws, { t: "hi", you: me.peer, host: me.host, p: me.p, peers, ...(me.host ? { door: room.door, locked: room.locked } : {}) });
  }

  async message(ws: WebSocket, data: unknown) {
    const me = this.socks.get(ws);
    if (!me) return;
    if (typeof data !== "string" || data.length > MSG_MAX) { this.socks.delete(ws); this.closeOne(ws, 1009, "too big"); this.gone(me); return; }
    const now = Date.now();
    me.hits = me.hits.filter((t) => t > now - 1000);
    if (me.hits.length >= (me.host ? HOST_RATE : RATE)) return;
    me.hits.push(now);
    let m: { t?: unknown; p?: unknown; peer?: unknown; to?: unknown; door?: unknown; on?: unknown };
    try { m = JSON.parse(data); } catch { return; }
    if (!m || typeof m !== "object") return;
    if (m.t === "p") {
      if (!okPresence(m.p)) { this.send(ws, { t: "err", error: "bad_presence" }); return; }
      me.p = me.ok ? m.p : atDoor(m.p);
      this.tell(ws, me);
      return;
    }
    if (!me.host) return;  // the door and whispers are the host's alone
    if (m.t === "w") {
      if (typeof m.to !== "string" || !PEER_RE.test(m.to) || !okPresence(m.p)) { this.send(ws, { t: "err", error: "bad_whisper" }); return; }
      const t = JSON.stringify({ t: "w", p: m.p });
      for (const [w, c] of this.socks) if (c.peer === m.to && c.ok && !c.host) this.raw(w, t);
      return;
    }
    const room = await this.rules();
    const peer = typeof m.peer === "string" && PEER_RE.test(m.peer) ? m.peer : "";
    if (m.t === "admit" && peer) {
      for (const [w, c] of this.socks) if (c.peer === peer && !c.ok && this.count(true) < SEATS) this.seat(w, c, room);
      await this.keep();
    } else if (m.t === "away" && peer) {
      room.away = keepNewest(room.away, peer);
      room.seated = room.seated.filter((x) => x !== peer);
      await this.keep();
      for (const [w, c] of this.socks) if (c.peer === peer && !c.host) { this.socks.delete(w); this.closeOne(w, SHUT.away, "turned away"); this.gone(c); }
    } else if (m.t === "door" && DOORS.includes(m.door as Door)) {
      room.door = m.door as Door;
      for (const [w, c] of this.socks) {
        if (c.ok) continue;
        if (room.door === "crew") { this.socks.delete(w); this.closeOne(w, SHUT.crewOnly, "crew only"); this.gone(c); }
        else if (room.door === "open" && !room.locked && this.count(true) < SEATS) this.seat(w, c, room);
      }
      await this.keep();
    } else if (m.t === "lock" && typeof m.on === "boolean") {
      room.locked = m.on;
      await this.keep();
    } else return;
    this.send(ws, { t: "door", door: room.door, locked: room.locked });
  }

  /** In from the door: hello again, now with the table, and the table hears it. */
  private seat(ws: WebSocket, c: Conn, room: Room) {
    c.ok = true;
    room.seated = keepNewest(room.seated, c.peer);
    this.greet(ws, c, room);
    this.tell(ws, c);
  }

  drop(ws: WebSocket) {
    const me = this.socks.get(ws);
    if (!me || !this.socks.delete(ws)) return;
    this.gone(me);
  }

  async alarm() {
    const open = await this.ctx.storage.get<Opened>("open");
    const now = Date.now();
    const hosted = [...this.socks.values()].some((c) => c.host);
    if (!open || open.until <= now || !hosted) {
      for (const ws of this.socks.keys()) this.closeOne(ws, SHUT.closed, "table closed");
      this.socks.clear();
      this.room = null;
      await this.ctx.storage.deleteAll();
      return;
    }
    await this.ctx.storage.setAlarm(Math.min(open.until, now + HOST_GONE_MIN * 60_000));
  }

  /** Someone's presence, to everyone who may hear it but `from`: the table
   *  when they're sitting at it, the host alone while they're at the door. */
  private tell(from: WebSocket, c: Conn) {
    const toHost = JSON.stringify({ t: "p", ...view(c, true) }), toRest = JSON.stringify({ t: "p", ...view(c, false) });
    for (const [ws, o] of this.socks) if (ws !== from && (o.host || (o.ok && c.ok))) this.raw(ws, o.host ? toHost : toRest);
  }
  private gone(c: Conn) {
    const t = JSON.stringify({ t: "bye", peer: c.peer });
    for (const [ws, o] of this.socks) if (o.host || (o.ok && c.ok)) this.raw(ws, t);
  }
  send(ws: WebSocket, m: unknown) { this.raw(ws, JSON.stringify(m)); }
  private raw(ws: WebSocket, t: string) { try { ws.send(t); } catch { /* it's gone; its close says so */ } }
  closeOne(ws: WebSocket, code: number, why: string) { try { ws.close(code, why); } catch { /* already closed */ } }
}

/** The name on a signed-in visitor's account when they're the host's crew
 *  (mutual friends, or the host on their own phone); null for anyone else. */
async function crewName(req: Request, env: Env, hostUid: string): Promise<string | null> {
  if (!hostUid || !(req.headers.get("cookie") || "").includes("dc_session=")) return null;
  let uid: string;
  try { uid = (await authenticate(req, env)).uid; } catch { return null; }
  const row = uid === hostUid
    ? await env.DB.prepare("SELECT name FROM users WHERE uid = ?").bind(uid).first<{ name: string | null }>()
    : await env.DB.prepare(
      `SELECT u.name FROM friends a JOIN friends b ON b.owner = a.friend AND b.friend = a.owner
         JOIN users u ON u.uid = a.friend WHERE a.owner = ? AND a.friend = ?`).bind(hostUid, uid).first<{ name: string | null }>();
  return row ? (row.name || "Crew") : null;
}

/** POST /table: open a table; its code for the phones, and the key that
 *  makes this page its host. Signed in only (and while testing, an admin:
 *  anyone else gets the 404 an admin route gives). */
export async function create(uid: string, env: Env): Promise<Response> {
  if (ADMINS_ONLY && !isAdmin(env, uid)) throw new HttpError(404, "not_found");
  await limitOrThrow(env, `table:${uid}`, TABLES_PER_HOUR, 3600);
  for (let i = 0; i < 6; i++) {
    const code = tableCode();
    const key = newToken();
    if (await env.TABLES.get(env.TABLES.idFromName(code)).open(await sha256Hex(`table:${key}`), uid)) return json({ code, key, hours: TABLE_HOURS });
  }
  throw new HttpError(503, "busy");
}

/** GET /table/{code}: before a socket, is there a table, a seat, its door,
 *  and is this visitor the host's crew (so they go straight in). */
export async function check(req: Request, env: Env, [code]: string[]): Promise<Response> {
  await limitOrThrow(env, `tablews:${clientIp(req)}`, JOINS_PER_HOUR, 3600);
  const t = await env.TABLES.get(env.TABLES.idFromName(code.toUpperCase())).info();
  if (!t.open) throw new HttpError(404, "no_table");
  return json({ open: true, full: t.full, door: t.door, crew: (await crewName(req, env, t.uid)) !== null });
}

/** GET /table/{code}/ws: a seat at a table, from a page of ours. */
export async function connect(req: Request, env: Env, [code]: string[]): Promise<Response> {
  if ((req.headers.get("upgrade") || "").toLowerCase() !== "websocket") throw new HttpError(426, "websocket");
  await limitOrThrow(env, `tablews:${clientIp(req)}`, JOINS_PER_HOUR, 3600);
  const stub = env.TABLES.get(env.TABLES.idFromName(code.toUpperCase()));
  const t = await stub.info();
  if (!t.open) throw new HttpError(404, "no_table");
  const headers = new Headers(req.headers);
  headers.delete(CREW);  // only this says who's crew
  const crew = await crewName(req, env, t.uid);
  if (crew !== null) headers.set(CREW, encodeURIComponent(crew));
  return stub.fetch(new Request(req.url, { method: "GET", headers }));
}
