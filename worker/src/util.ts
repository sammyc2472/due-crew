// Small helpers: responses, hashing, tokens, ids. No I/O here but crypto.

export interface Env {
  DB: D1Database;
  API_VERSION: string;
  MIN_CLIENT: string;
  MAIL_FROM: string;
  RESEND_API_KEY?: string;
  /** Cloudflare Email Service's send_email binding, when configured. */
  EMAIL?: { send(message: { to: string; from: string; subject: string; text: string }): Promise<unknown> };
  ADMIN_TOKEN?: string;
  /** The 2.x bridge's Google service account key (JSON); unset, the bridge is off. */
  FIREBASE_SA?: string;
  /** Where reports go (POST /reports). Unset: the log counts them, and they go nowhere. */
  REPORT_TO?: string;
  /** 3.2: comma-separated uids that may read GET /admin/stats. */
  ADMIN_UIDS?: string;
  /** 3.2.1: the admin's uid(s), in wrangler.toml [vars]; not a secret, a uid alone opens nothing. */
  ADMINS?: string;
}

export class HttpError extends Error {
  constructor(public status: number, public code: string, public extra: Record<string, unknown> = {}) {
    super(code);
  }
}

export function json(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", ...headers },
  });
}

export function nowSec(): number {
  return Math.floor(Date.now() / 1000);
}

export const BODY_MAX = 512 * 1024;
/** The most any route reads (a plan, a deck's tree, its note ids). Each
 *  route's own limit (readJson's `max`) is checked as it streams; this is
 *  only the early refusal of a declared length past all of them. */
export const ANY_BODY_MAX = 1600 * 1024;

/** The body as text, at most `max` bytes: counted as it streams, since a
 *  chunked request has no content-length to check first. */
export async function readText(req: Request, max = BODY_MAX): Promise<string> {
  if (!req.body) return "";
  const reader = req.body.getReader();
  const parts: Uint8Array[] = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > max) {
      await reader.cancel();
      throw new HttpError(413, "too_big");
    }
    parts.push(value);
  }
  const all = new Uint8Array(size);
  let at = 0;
  for (const p of parts) {
    all.set(p, at);
    at += p.byteLength;
  }
  return new TextDecoder().decode(all);
}

export async function readJson(req: Request, max = BODY_MAX): Promise<Record<string, unknown>> {
  const text = await readText(req, max);
  let body: unknown;
  try {
    body = JSON.parse(text);
  } catch {
    throw new HttpError(400, "bad_json");
  }
  if (typeof body !== "object" || body === null || Array.isArray(body)) throw new HttpError(400, "bad_json");
  return body as Record<string, unknown>;
}

const enc = new TextEncoder();

export async function sha256Hex(text: string): Promise<string> {
  const buf = await crypto.subtle.digest("SHA-256", enc.encode(text));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** Equal-length strings compared without an early exit. */
export function timingSafeEqual(a: string, b: string): boolean {
  const x = enc.encode(a);
  const y = enc.encode(b);
  let diff = x.length ^ y.length;
  for (let i = 0; i < Math.max(x.length, y.length); i++) diff |= (x[i] ?? 0) ^ (y[i] ?? 0);
  return diff === 0;
}

export function base64url(bytes: Uint8Array): string {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** A session token: 32 random bytes, base64url. */
export function newToken(): string {
  return base64url(crypto.getRandomValues(new Uint8Array(32)));
}

/** Six digits, uniform (rejection sampling), as a string with leading zeros. */
export function newCode(): string {
  const buf = new Uint32Array(1);
  const limit = Math.floor(0x100000000 / 1_000_000) * 1_000_000;
  for (;;) {
    crypto.getRandomValues(buf);
    if (buf[0] < limit) return String(buf[0] % 1_000_000).padStart(6, "0");
  }
}

const CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";

/** A ULID: 48 bits of milliseconds, 80 random bits, Crockford base32. */
export function ulid(ms = Date.now()): string {
  let time = "";
  for (let i = 0; i < 10; i++) {
    time = CROCKFORD[ms % 32] + time;
    ms = Math.floor(ms / 32);
  }
  const rand = crypto.getRandomValues(new Uint8Array(16));
  let r = "";
  for (let i = 0; i < 16; i++) r += CROCKFORD[rand[i] % 32];
  return time + r;
}

/** Lower-cased and trimmed, before any comparison. null if it isn't one. */
export function normEmail(v: unknown): string | null {
  if (typeof v !== "string") return null;
  const e = v.trim().toLowerCase();
  if (e.length > 254 || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e)) return null;
  return e;
}

export function clientIp(req: Request): string {
  return req.headers.get("CF-Connecting-IP") || "local";
}
