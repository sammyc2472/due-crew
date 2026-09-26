// Sign-in codes go out by Cloudflare Email Service (the EMAIL binding),
// else Resend (RESEND_API_KEY). Plain text, no links. With neither (dev,
// tests) the code is logged instead; the address never is.

import { Env, HttpError } from "./util";

export function codeText(code: string): string {
  return `Your Due Crew code: ${code.slice(0, 3)} ${code.slice(3)}. It expires in 10 minutes.`;
}

export async function sendCode(env: Env, email: string, code: string): Promise<void> {
  const text = codeText(code);
  if (env.EMAIL) {
    try {
      // the address alone: "codes@duecrew.com" out of "Due Crew <codes@duecrew.com>"
      const from = /<([^>]+)>/.exec(env.MAIL_FROM)?.[1] ?? env.MAIL_FROM;
      await env.EMAIL.send({ to: email, from, subject: "Your Due Crew code", text });
    } catch {
      throw new HttpError(502, "mail_failed");
    }
    return;
  }
  if (!env.RESEND_API_KEY) {
    console.log(`due crew (dev, no RESEND_API_KEY): ${text}`);
    return;
  }
  const res = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { authorization: `Bearer ${env.RESEND_API_KEY}`, "content-type": "application/json" },
    body: JSON.stringify({ from: env.MAIL_FROM, to: [email], subject: "Your Due Crew code", text }),
  });
  if (!res.ok) throw new HttpError(502, "mail_failed");
}
