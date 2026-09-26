// Sign-in codes go out through Resend. Plain text, no links. With no key
// (dev, tests) the code is logged instead; the address never is.

import { Env, HttpError } from "./util";

export function codeText(code: string): string {
  return `Your Due Crew code: ${code.slice(0, 3)} ${code.slice(3)}. It expires in 10 minutes.`;
}

export async function sendCode(env: Env, email: string, code: string): Promise<void> {
  const text = codeText(code);
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
