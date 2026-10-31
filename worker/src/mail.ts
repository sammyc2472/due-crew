// Mail goes out by Cloudflare Email Service (the EMAIL binding), else
// Resend (RESEND_API_KEY). Plain text, no links. With neither (dev, tests)
// a sign-in code is logged instead, only with DEV_MAIL_LOG=1; the address never is.

import { Env, HttpError } from "./util";

export function codeText(code: string): string {
  return `Your Due Crew code: ${code.slice(0, 3)} ${code.slice(3)}. It expires in 10 minutes.`;
}

export async function sendCode(env: Env, email: string, code: string): Promise<void> {
  const text = codeText(code);
  if (!env.EMAIL && !env.RESEND_API_KEY) {
    // only where asked (tools/site_preview.sh): a deploy that lost its mail
    // binding refuses rather than writing codes into Workers Logs
    if (env.DEV_MAIL_LOG !== "1") throw new HttpError(503, "mail_unavailable");
    console.log(`due crew (dev, no RESEND_API_KEY): ${text}`);
    return;
  }
  await sendMail(env, email, "Your Due Crew code", text);
}

/** One plain-text message, from MAIL_FROM's address (under `name` when
 *  given), answered to `replyTo` when given. Without a way to send, nothing goes. */
export async function sendMail(env: Env, to: string, subject: string, text: string,
  opts: { name?: string; replyTo?: string } = {}): Promise<void> {
  // the address alone: "codes@duecrew.com" out of "Due Crew <codes@duecrew.com>"
  const addr = /<([^>]+)>/.exec(env.MAIL_FROM)?.[1] ?? env.MAIL_FROM;
  if (env.EMAIL) {
    try {
      await env.EMAIL.send({ to, from: opts.name ? { name: opts.name, email: addr } : addr, subject, text,
        ...(opts.replyTo ? { replyTo: opts.replyTo } : {}) });
    } catch {
      throw new HttpError(502, "mail_failed");
    }
    return;
  }
  if (!env.RESEND_API_KEY) return;
  const res = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { authorization: `Bearer ${env.RESEND_API_KEY}`, "content-type": "application/json" },
    body: JSON.stringify({ from: opts.name ? `${opts.name} <${addr}>` : env.MAIL_FROM, to: [to], subject, text,
      ...(opts.replyTo ? { reply_to: opts.replyTo } : {}) }),
    signal: AbortSignal.timeout(10000),  // a slow mail service answers "try again", not a hung sign-in
  }).catch(() => { throw new HttpError(502, "mail_failed"); });
  if (!res.ok) throw new HttpError(502, "mail_failed");
}
