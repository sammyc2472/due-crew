// Due Crew API. One Worker, D1 underneath; every consent rule lives in
// this code. JSON in, JSON out.

import * as Ad from "./admin";
import * as Fb from "./feedback";
import * as Rp from "./reports";
import * as A from "./auth";
import * as B from "./board";
import * as C from "./cards";
import * as I from "./invites";
import * as L from "./library";
import * as N from "./notices";
import * as P from "./plans";
import * as T from "./team";
import * as People from "./people";
import * as AS from "./adminsquads";
import * as Q from "./squads";
import * as Bingo from "./bingo";
import * as S from "./social";
import * as Quiet from "./quiet";
import * as Mine from "./mydata";
import * as Tb from "./table";
import { ANY_BODY_MAX, Env, HttpError, json } from "./util";

export { Table } from "./table";  // game night's Durable Object


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
open("POST", r("/auth/link/redeem"), A.redeemLink);
open("GET", r("/plans/ics"), (q, env) => P.ics(q, env));  // 3.4: a calendar app can't sign in
open("GET", r("/plans/public"), (q, env) => P.publicPeek(q, env));  // a plan's link, before signing in
open("GET", r("/auth/gone"), (q, env) => Quiet.gone(q, env));  // Q4: signed out, the add-on asks why
open("POST", r("/links/email"), (q, env) => A.emailLink(q, env));  // a phone sends itself the link
authed("POST", r("/auth/link"), (_q, s, env) => A.createLink(s, env));
authed("GET", r("/auth/me"), (_q, s, env) => A.me(s, env));
authed("POST", r("/auth/signout"), (q, s, env) => A.signOut(s, env, q));
authed("POST", r("/auth/signout-all"), (q, s, env) => A.signOutAll(s, env, q));
authed("GET", r("/auth/places"), (_q, s, env) => A.places(s, env));
authed("DELETE", r("/account"), (_q, s, env) => A.deleteAccount(s, env));
// 3.9.5: game night (duecrew.com/table). The host opens a table signed in; a
// phone joins with the code alone, from a page of ours (a socket's Origin)
authed("POST", r("/table"), (_q, s, env) => Tb.create(s.uid, env));
open("GET", r("/table/([A-Za-z]{4})"), (q, env, p) => Tb.check(q, env, p));
open("GET", r("/table/([A-Za-z]{4})/ws"), (q, env, p) => {
  if (!ourPage(q.headers.get("origin"))) throw new HttpError(403, "csrf");
  return Tb.connect(q, env, p);
});

authed("GET", r("/board"), B.board);
authed("POST", r("/sync"), B.sync);
authed("GET", r("/decks"), (_q, s, env) => B.getDecks(s, env));
authed("GET", r(`/heatmap/${ID}`), (_q, s, env, p) => B.getHeatmap(s, env, p));
authed("GET", r("/settings"), (_q, s, env) => B.getSettings(s, env));
authed("PUT", r("/settings"), B.putSettings);

authed("GET", r(`/users/${ID}`), (_q, s, env, p) => S.getUser(s, env, p));
authed("GET", r("/friends"), (_q, s, env) => S.getFriends(s, env));
authed("PUT", r(`/friends/${ID}`), S.putFriend);
authed("DELETE", r(`/friends/${ID}`), (_q, s, env, p) => S.deleteFriend(s, env, p));
authed("POST", r("/codes"), S.newCode);
authed("GET", r("/codes/([A-Za-z0-9]{1,12})"), (_q, s, env, p) => S.peekCode(s, env, p));
authed("POST", r("/codes/([A-Za-z0-9]{1,12})/add"), (_q, s, env, p) => S.addByCode(s, env, p));
// 3.5.0: one-time invites (duecrew.com/i/CODE); the page asks signed out
open("GET", r("/invites/([A-Za-z0-9]{1,12})"), (q, env, p) => I.peek(q, env, p));
authed("POST", r("/invites"), (_q, s, env) => I.create(s, env));
authed("POST", r("/invites/([A-Za-z0-9]{1,12})/redeem"), (_q, s, env, p) => I.redeem(s, env, p));
authed("POST", r(`/cheers/${ID}`), S.sendCheer);
authed("GET", r("/knocks"), (_q, s, env) => S.getKnocks(s, env));
authed("POST", r(`/knocks/${ID}`), S.sendKnock);
authed("DELETE", r(`/knocks/${ID}`), (_q, s, env, p) => S.deleteKnock(s, env, p));
authed("POST", r("/reports"), S.report);

// 3.2: tips, my log, the admin's counts
authed("POST", r("/tips/helped"), C.helped);
authed("GET", r("/log"), (q, s, env) => C.getLog(q, s, env));
// 3.7.1, D2: Account › Your data
authed("DELETE", r("/log"), (_q, s, env) => C.deleteLog(s, env));
authed("GET", r("/account/data"), (_q, s, env) => Mine.getData(s, env));
authed("DELETE", r("/account/todos"), (_q, s, env) => Mine.deleteTodos(s, env));
authed("GET", r("/admin/stats"), (_q, s, env) => Ad.stats(s, env));
authed("GET", r("/admin/trends"), Ad.trends);  // 3.5, X
// the admin's account lookup: one person at a time
authed("GET", r("/admin/people"), People.search);
authed("GET", r(`/admin/people/${ID}`), (_q, s, env, p) => People.person(s, env, p));
authed("POST", r(`/admin/people/${ID}/signout`), (_q, s, env, p) => People.signOut(s, env, p));
authed("DELETE", r(`/admin/people/${ID}`), People.remove);
// The admin: sign-in help, a note, the audit log, squads
authed("POST", r(`/admin/people/${ID}/code`), (_q, s, env, p) => People.sendFreshCode(s, env, p));
authed("POST", r(`/admin/people/${ID}/limits`), (_q, s, env, p) => People.clearLimits(s, env, p));
authed("PUT", r(`/admin/people/${ID}/email`), People.changeEmail);
authed("DELETE", r(`/admin/people/${ID}/email`), (_q, s, env, p) => People.cancelEmail(s, env, p));
authed("PUT", r(`/admin/people/${ID}/note`), People.putNote);
authed("GET", r(`/admin/people/${ID}/crew`), (_q, s, env, p) => People.crew(s, env, p));
authed("DELETE", r(`/admin/people/${ID}/crew/${ID}`), People.removeEdge);
authed("GET", r("/admin/actions"), Ad.actions);
authed("GET", r(`/admin/squads/${ID}`), (_q, s, env, p) => AS.get(s, env, p));
authed("PATCH", r(`/admin/squads/${ID}`), AS.patch);
authed("POST", r(`/admin/squads/${ID}/code`), (_q, s, env, p) => AS.newCode(s, env, p));
authed("POST", r(`/admin/squads/${ID}/remove/${ID}`), AS.remove);
authed("DELETE", r(`/admin/squads/${ID}`), AS.del);
// 3.6: squad bingo's pool, the admin's to edit
authed("GET", r("/admin/bingo"), (_q, s, env) => Bingo.adminGet(s, env));
// 3.6.5, P6: feedback, from anyone signed in, to the admin's page
authed("POST", r("/feedback"), Fb.send);
authed("GET", r("/admin/feedback"), Fb.list);
authed("PATCH", r("/admin/feedback/([0-9A-Z]{26})"), Fb.mark);
authed("DELETE", r("/admin/feedback/([0-9A-Z]{26})"), (_q, s, env, p) => Fb.remove(s, env, p));
authed("POST", r("/admin/feedback/([0-9A-Z]{26})/reply"), Fb.reply);
// 3.8.1 (the audit): reports, kept for the admin (they went only by mail)
authed("GET", r("/admin/reports"), Rp.list);
authed("PATCH", r("/admin/reports/([0-9A-Z]{26})"), Rp.mark);
authed("DELETE", r("/admin/reports/([0-9A-Z]{26})"), (_q, s, env, p) => Rp.remove(s, env, p));
authed("PUT", r("/admin/bingo/([a-z0-9]{1,12})"), Bingo.adminPut);
// 3.2.1: the admin's notice on everyone's board
authed("GET", r("/admin/notices"), N.list);
authed("POST", r("/admin/notices"), N.post);
authed("DELETE", r("/admin/notices/([0-9]{1,9})"), (_q, s, env, p) => N.remove(s, env, p));

// 3.1: plans (the fixed paths before /plans/{id})
authed("PUT", r("/plans/trees"), P.putTree);
authed("GET", r("/plans/trees"), (q, s, env) => P.getTrees(q, s, env));
authed("GET", r("/plans/mine"), (_q, s, env) => P.mine(s, env));
authed("GET", r("/plans/peek"), P.peek);
authed("POST", r("/plans/follow"), P.follow);
authed("POST", r("/plans"), P.create);
authed("GET", r(`/plans/${ID}`), P.get);
authed("PUT", r(`/plans/${ID}`), P.put);
authed("DELETE", r(`/plans/${ID}`), (_q, s, env, p) => P.remove(s, env, p));
authed("POST", r(`/plans/${ID}/cards`), P.addCards);
authed("POST", r(`/plans/${ID}/tags`), P.tagNotes);  // 3.8.0: plan tags, from an author's Anki
authed("GET", r(`/plans/${ID}/progress`), (_q, s, env, p) => P.progress(s, env, p));
authed("PATCH", r(`/plans/${ID}/follow`), P.patchFollow);
authed("DELETE", r(`/plans/${ID}/follow`), (_q, s, env, p) => P.unfollow(s, env, p));
// 3.5, B: the library
authed("GET", r("/library"), L.list);
authed("PUT", r(`/plans/${ID}/listed`), L.setListed);
authed("POST", r(`/plans/${ID}/copy`), L.copy);
authed("POST", r(`/plans/${ID}/report`), L.report);
authed("GET", r("/admin/library"), (_q, s, env) => L.takenOut(s, env));
authed("POST", r(`/admin/library/${ID}`), L.takeOut);
authed("DELETE", r(`/admin/library/${ID}`), (_q, s, env, p) => L.putBack(s, env, p));
// 3.3: plans together
authed("GET", r(`/plans/${ID}/log`), (_q, s, env, p) => P.log(s, env, p));
authed("PUT", r(`/plans/${ID}/ids`), P.putIds);
authed("POST", r(`/plans/${ID}/undo`), P.undo);
authed("POST", r(`/plans/${ID}/editors`), P.addEditor);
authed("DELETE", r(`/plans/${ID}/editors/${ID}`), (_q, s, env, p) => P.removeEditor(s, env, p));
authed("POST", r(`/plans/${ID}/invite`), P.answerInvite);  // 3.8.1: yes or no to co-writing it, or to keeping it
authed("POST", r(`/plans/${ID}/owner`), P.offerPlan);      // 3.8.1: the owner offers it to a co-author
authed("POST", r(`/plans/${ID}/remarks`), P.remarks);       // 3.8.1: a note on a card or tag, from Anki's Browse
authed("GET", r(`/plans/${ID}/notes`), (_q, s, env, p) => P.notes(s, env, p));
authed("POST", r(`/plans/${ID}/notes`), P.addNote);
authed("DELETE", r(`/plans/${ID}/notes/(\\d{1,12})`), (_q, s, env, p) => P.removeNote(s, env, p));
authed("GET", r(`/plans/${ID}/posts`), (_q, s, env, p) => P.posts(s, env, p));         // 3.7.3
authed("POST", r(`/plans/${ID}/posts`), P.addPost);
authed("DELETE", r(`/plans/${ID}/posts/(\\d{1,12})`), (_q, s, env, p) => P.removePost(s, env, p));
// 3.7.3: a plan's team
authed("GET", r(`/plans/${ID}/team`), T.get);
authed("POST", r(`/plans/${ID}/team`), T.join);
authed("DELETE", r(`/plans/${ID}/team`), (_q, s, env, p) => T.leave(s, env, p));
authed("POST", r(`/plans/${ID}/asks`), T.ask);
authed("DELETE", r(`/plans/${ID}/asks/(\\d{1,12})`), (_q, s, env, p) => T.removeAsk(s, env, p));
authed("POST", r(`/plans/${ID}/asks/(\\d{1,12})/helped`), T.helped);

authed("POST", r("/squads"), Q.create);
authed("GET", r("/squads/peek"), Q.peek);
authed("GET", r("/squads/mine"), (_q, s, env) => Q.mine(s, env));
authed("GET", r(`/squads/${ID}`), Q.fetchSquad);
authed("PATCH", r(`/squads/${ID}`), Q.patch);
authed("POST", r(`/squads/${ID}/join`), Q.join);
authed("PUT", r(`/squads/${ID}/row`), Q.putRow);
authed("DELETE", r(`/squads/${ID}/members/${ID}`), (_q, s, env, p) => Q.removeMember(s, env, p));
authed("POST", r(`/squads/${ID}/block/${ID}`), (_q, s, env, p) => Q.block(s, env, p));

/** Daily: what has expired goes. Nothing anyone would miss. */
export async function housekeeping(env: Env, now = Math.floor(Date.now() / 1000)): Promise<void> {
  await env.DB.batch([
    env.DB.prepare("DELETE FROM otp WHERE expires_at <= ?").bind(now),
    env.DB.prepare("DELETE FROM limits WHERE window_start <= ?").bind(now - 86400),
    env.DB.prepare("DELETE FROM sessions WHERE last_used <= ?").bind(now - A.SESSION_IDLE),
    env.DB.prepare("DELETE FROM login_links WHERE expires_at <= ?").bind(now),
    // 3.5.0: an invite keeps working as an add (then Add back) for a year
    env.DB.prepare("DELETE FROM invites WHERE expires_at <= ?").bind(now - 351 * 86400),
    // 3.6.5, P6: feedback is kept a year
    env.DB.prepare("DELETE FROM feedback WHERE at <= ?").bind(now - 365 * 86400),
    env.DB.prepare("DELETE FROM reports WHERE at <= ?").bind(now - Rp.REPORTS_KEPT_DAYS * 86400),  // 3.8.1
    // the admin's audit log is kept a year; an email change lapses after a week
    env.DB.prepare("DELETE FROM admin_actions WHERE at <= ?").bind(now - 365 * 86400),
    env.DB.prepare("DELETE FROM email_changes WHERE at <= ?").bind(now - 7 * 86400),
  ]);
  // Q1-Q6: quiet accounts trimmed, then deleted, a few a day
  try {
    const q = await Quiet.run(env, now);
    if (q.trimmed || q.deleted) console.log(`quiet: trimmed ${q.trimmed}, deleted ${q.deleted}`);
  } catch (e) {
    console.log(`quiet failed: ${String((e as Error)?.message || e).slice(0, 120)}`);
  }
}

/** No Origin (the add-on, a calendar app), or a page of ours: duecrew.com,
 *  its subdomains, or a local preview (whose proxy names the route it came in by). */
export function ourPage(origin: string | null): boolean {
  if (origin === null) return true;
  let host: string;
  try { host = new URL(origin).hostname; } catch { return false; }  // "null": a sandboxed frame or a file
  return host === "duecrew.com" || host.endsWith(".duecrew.com") || host === "localhost" || host === "127.0.0.1";
}

export default {
  async scheduled(event: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    // the 2.x bridge's cron can fire for a while after a deploy drops it: not housekeeping
    if (event.cron === "*/15 * * * *") return;
    // 3.5, X: the day's counts, kept; 3.6: bingo's counts per square
    ctx.waitUntil(housekeeping(env).then(() => Ad.snapshot(env)).then(() => Bingo.keepStats(env)));
  },

  async fetch(req: Request, env: Env): Promise<Response> {
    let path = new URL(req.url).pathname;
    // the site reaches the API as duecrew.com/api/* (3.1), through its service binding
    if (path.startsWith("/api/")) path = path.slice(4);
    try {
      if (Number(req.headers.get("content-length") || 0) > ANY_BODY_MAX) throw new HttpError(413, "too_big");
      // A browser names the page that sent a request; the add-on sends no
      // Origin. Nothing that changes anything comes from another site's page
      // (sign-in included: another page can't send codes or spend my tries).
      if (req.method !== "GET" && req.method !== "HEAD" && !ourPage(req.headers.get("origin"))) throw new HttpError(403, "csrf");
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
