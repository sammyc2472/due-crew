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
  const res = await worker.fetch(new Request(BASE + path, init), { ...env, ...(opts.env ?? {}) } as any);
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
