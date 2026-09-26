import { env } from "cloudflare:workers";
import { vi } from "vitest";
import worker from "../src/index";

export const BASE = "https://api.duecrew.com";

/** One request to the Worker, as a client would send it. */
export async function api(
  method: string, path: string,
  opts: { body?: unknown; token?: string; ip?: string; raw?: string; env?: Partial<Cloudflare.Env> } = {},
): Promise<{ status: number; body: any; headers: Headers }> {
  const headers: Record<string, string> = { "CF-Connecting-IP": opts.ip ?? "203.0.113.7" };
  if (opts.token) headers.authorization = `Bearer ${opts.token}`;
  const init: RequestInit = { method, headers };
  if (opts.raw !== undefined) init.body = opts.raw;
  else if (opts.body !== undefined) {
    init.body = JSON.stringify(opts.body);
    headers["content-type"] = "application/json";
  }
  // the EMAIL binding only when a test brings one: the rest see Resend's path
  const res = await worker.fetch(new Request(BASE + path, init), { ...env, EMAIL: undefined, ...(opts.env ?? {}) } as any);
  const text = await res.text();
  return { status: res.status, body: text ? JSON.parse(text) : null, headers: res.headers };
}

/** Catches the mail Resend would send; returns what was sent. */
export function mailbox() {
  const sent: { to: string; subject: string; text: string; auth: string }[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input: any, init?: any) => {
    const url = typeof input === "string" ? input : input.url;
    if (!url.startsWith("https://api.resend.com/")) throw new Error(`unexpected fetch ${url}`);
    const b = JSON.parse(init.body);
    sent.push({ to: b.to[0], subject: b.subject, text: b.text, auth: init.headers.authorization });
    return new Response(JSON.stringify({ id: "x" }), { status: 200 });
  });
  return {
    sent,
    /** the digits of the last code sent to `email` */
    code(email: string): string {
      const m = [...sent].reverse().find((s) => s.to === email);
      const d = /code: (\d{3}) (\d{3})\./.exec(m?.text ?? "");
      if (!d) throw new Error(`no code for ${email}`);
      return d[1] + d[2];
    },
  };
}

/** Sign in end to end; returns the session. */
export async function signIn(email: string, box: ReturnType<typeof mailbox>, device = "test") {
  const a = await api("POST", "/auth/code", { body: { email } });
  if (a.status !== 200) throw new Error(`code: ${a.status} ${JSON.stringify(a.body)}`);
  const v = await api("POST", "/auth/verify", { body: { email, code: box.code(email.trim().toLowerCase()), device } });
  if (v.status !== 200) throw new Error(`verify: ${v.status} ${JSON.stringify(v.body)}`);
  return v.body as { token: string; uid: string; new: boolean; name: string | null };
}

export const db = () => env.DB;

/** A signed-in person without the mail round trip: a user row and a
 *  session, straight into D1. Returns a caller bound to their token. */
export async function person(uid: string, name = uid[0].toUpperCase() + uid.slice(1)) {
  const { newToken, sha256Hex } = await import("../src/util");
  const token = newToken();
  const now = Math.floor(Date.now() / 1000);
  await env.DB.batch([
    env.DB.prepare("INSERT INTO users (uid, email, name, created_at) VALUES (?, ?, ?, ?)").bind(uid, `${uid}@example.com`, name, now),
    env.DB.prepare("INSERT INTO sessions (token_hash, uid, device, created_at, last_used) VALUES (?, ?, 'test', ?, ?)")
      .bind(await sha256Hex(token), uid, now, now),
  ]);
  const call = (method: string, path: string, body?: unknown) => api(method, path, { token, body });
  return { uid, token, call, status: async (method: string, path: string, body?: unknown) => (await call(method, path, body)).status };
}

export async function befriend(a: { call: Function }, b: { uid: string }) {
  const r = await (a.call as any)("PUT", `/friends/${b.uid}`);
  if (r.status !== 200) throw new Error(`befriend ${r.status}`);
}

export const WEEK = (label: string, reviews = 10) =>
  ({ v: 1, paused: false, days: { [label]: { studied: true, reviews, studyTimeMs: 1000, accuracy: 90.5, streak: 3 } } });
