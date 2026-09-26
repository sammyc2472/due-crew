// Due Crew API. One Worker, D1 underneath; every consent rule the Firestore
// rules used to hold lives in this code now. JSON in, JSON out.

import * as A from "./auth";
import * as B from "./board";
import * as Q from "./squads";
import * as S from "./social";
import { Env, HttpError, json } from "./util";

const BODY_MAX = 512 * 1024;

type Open = (req: Request, env: Env, params: string[]) => Promise<Response>;
type Authed = (req: Request, s: A.Session, env: Env, params: string[]) => Promise<Response>;

const routes: [string, RegExp, Open][] = [];
const open = (method: string, re: RegExp, h: Open) => routes.push([method, re, h]);
const authed = (method: string, re: RegExp, h: Authed) =>
  routes.push([method, re, async (req, env, p) => h(req, await A.authenticate(req, env), env, p)]);

const ID = "([A-Za-z0-9_-]{1,128})";
const r = (path: string) => new RegExp(`^${path}$`);

open("GET", r("/version"), async (_q, env) => json({ api: Number(env.API_VERSION), minClient: env.MIN_CLIENT }));
open("POST", r("/auth/code"), A.requestCode);
open("POST", r("/auth/verify"), A.verifyCode);
open("POST", r("/admin/import-users"), A.importUsers);
authed("GET", r("/auth/me"), (_q, s, env) => A.me(s, env));
authed("POST", r("/auth/signout"), (_q, s, env) => A.signOut(s, env));
authed("POST", r("/auth/signout-all"), (_q, s, env) => A.signOutAll(s, env));
authed("DELETE", r("/account"), (_q, s, env) => A.deleteAccount(s, env));

authed("GET", r("/board"), B.board);
authed("POST", r("/sync"), B.sync);
authed("GET", r("/decks"), (_q, s, env) => B.getDecks(s, env));
authed("GET", r(`/heatmap/${ID}`), (_q, s, env, p) => B.getHeatmap(s, env, p));
authed("GET", r("/settings"), (_q, s, env) => B.getSettings(s, env));
authed("PUT", r("/settings"), B.putSettings);

authed("GET", r(`/users/${ID}`), (_q, s, env, p) => S.getUser(s, env, p));
authed("GET", r("/friends"), (_q, s, env) => S.getFriends(s, env));
authed("PUT", r("/friends"), S.restoreFriends);
authed("PUT", r(`/friends/${ID}`), S.putFriend);
authed("DELETE", r(`/friends/${ID}`), (_q, s, env, p) => S.deleteFriend(s, env, p));
authed("POST", r("/codes"), S.newCode);
authed("POST", r("/codes/([A-Za-z0-9]{1,12})/add"), (_q, s, env, p) => S.addByCode(s, env, p));
authed("POST", r(`/cheers/${ID}`), S.sendCheer);
authed("GET", r("/knocks"), (_q, s, env) => S.getKnocks(s, env));
authed("POST", r(`/knocks/${ID}`), S.sendKnock);
authed("DELETE", r(`/knocks/${ID}`), (_q, s, env, p) => S.deleteKnock(s, env, p));

authed("POST", r("/squads"), Q.create);
authed("GET", r("/squads/peek"), Q.peek);
authed("POST", r("/squads/restore"), Q.restore);
authed("GET", r(`/squads/${ID}`), (_q, s, env, p) => Q.fetchSquad(s, env, p));
authed("PATCH", r(`/squads/${ID}`), Q.patch);
authed("POST", r(`/squads/${ID}/join`), (_q, s, env, p) => Q.join(s, env, p));
authed("PUT", r(`/squads/${ID}/row`), Q.putRow);
authed("DELETE", r(`/squads/${ID}/members/${ID}`), (_q, s, env, p) => Q.removeMember(s, env, p));
authed("POST", r(`/squads/${ID}/block/${ID}`), (_q, s, env, p) => Q.block(s, env, p));

/** Daily: what has expired goes. Nothing anyone would miss. */
export async function housekeeping(env: Env, now = Math.floor(Date.now() / 1000)): Promise<void> {
  await env.DB.batch([
    env.DB.prepare("DELETE FROM otp WHERE expires_at <= ?").bind(now),
    env.DB.prepare("DELETE FROM limits WHERE window_start <= ?").bind(now - 86400),
    env.DB.prepare("DELETE FROM sessions WHERE last_used <= ?").bind(now - A.SESSION_IDLE),
  ]);
}

export default {
  async scheduled(_event: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    ctx.waitUntil(housekeeping(env));
  },

  async fetch(req: Request, env: Env): Promise<Response> {
    const path = new URL(req.url).pathname;
    try {
      if (Number(req.headers.get("content-length") || 0) > BODY_MAX) throw new HttpError(413, "too_big");
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
