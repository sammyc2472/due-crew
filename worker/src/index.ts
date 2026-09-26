// Due Crew API. One Worker, D1 underneath; every consent rule the Firestore
// rules used to hold lives in this code now. JSON in, JSON out.

import {
  authenticate, deleteAccount, importUsers, me, requestCode, signOut, signOutAll, verifyCode,
} from "./auth";
import { Env, HttpError, json } from "./util";

type Handler = (req: Request, env: Env, params: string[]) => Promise<Response>;

const routes: [string, RegExp, Handler][] = [
  ["GET", /^\/version$/, async (_r, env) => json({ api: Number(env.API_VERSION), minClient: env.MIN_CLIENT })],
  ["POST", /^\/auth\/code$/, requestCode],
  ["POST", /^\/auth\/verify$/, verifyCode],
  ["GET", /^\/auth\/me$/, async (r, env) => me(await authenticate(r, env), env)],
  ["POST", /^\/auth\/signout$/, async (r, env) => signOut(await authenticate(r, env), env)],
  ["POST", /^\/auth\/signout-all$/, async (r, env) => signOutAll(await authenticate(r, env), env)],
  ["DELETE", /^\/account$/, async (r, env) => deleteAccount(await authenticate(r, env), env)],
  ["POST", /^\/admin\/import-users$/, importUsers],
];

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    const path = new URL(req.url).pathname;
    try {
      let allowed = false;
      for (const [method, re, handler] of routes) {
        const m = re.exec(path);
        if (!m) continue;
        allowed = true;
        if (method === req.method) return await handler(req, env, m.slice(1));
      }
      throw allowed ? new HttpError(405, "method") : new HttpError(404, "not_found");
    } catch (e) {
      if (e instanceof HttpError) {
        const headers: Record<string, string> = {};
        if (typeof e.extra.retryAfter === "number") headers["retry-after"] = String(e.extra.retryAfter);
        return json({ error: e.code, ...e.extra }, e.status, headers);
      }
      console.error("due crew api:", e instanceof Error ? e.message : "error");
      return json({ error: "server" }, 500);
    }
  },
} satisfies ExportedHandler<Env>;
