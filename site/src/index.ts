// duecrew.com. Static files, plus what only a Worker can do: /api/* goes to
// the API Worker (a service binding, so the session is a same-site cookie),
// the app's paths get the one app page with a CSP that lets its own script
// run, and a plan's link previews as the plan (3.5, A: its name and one
// line in the page head, and a picture drawn in ./og.ts).

import { Peek, describe, draw, drawInvite, png } from "./og";

interface Env {
  ASSETS: { fetch(req: Request): Promise<Response> };
  API: { fetch(req: Request): Promise<Response> };
}

const APP = /^\/(sign-in|account|home|log|admin|library|plans|plans\/[A-Za-z0-9-]+(\/edit)?|plans\/new|p\/[A-Za-z0-9]{1,16}|i\/[A-Za-z0-9]{1,12})\/?$/;
const PLAN_PAGE = /^\/p\/([A-Za-z0-9]{8})\/?$/;
const PLAN_PNG = /^\/p\/([A-Za-z0-9]{8})\.png$/;
const INVITE_PAGE = /^\/i\/([A-Za-z0-9]{6}|[A-Za-z0-9]{10})\/?$/;
const INVITE_PNG = /^\/i\/([A-Za-z0-9]{6}|[A-Za-z0-9]{10})\.png$/;
const CSP = [
  "default-src 'self'", "img-src 'self' data:", "style-src 'self' 'unsafe-inline'", "script-src 'self'", "connect-src 'self'",
  "base-uri 'none'", "form-action 'none'", "frame-ancestors 'none'",
].join("; ");

/** What a plan's link shows signed out (GET /plans/public), kept five
 *  minutes: a chat app, the picture and the page all ask for it at once. */
async function peek(code: string, req: Request, env: Env, ctx: ExecutionContext): Promise<Peek | null> {
  const key = new Request(`https://duecrew.com/__peek/${code}`);
  let res = await caches.default.match(key);
  if (!res) {
    const r = await env.API.fetch(new Request(new URL(`/api/plans/public?code=${code}`, req.url), { method: "GET", headers: req.headers }));
    if (r.status !== 200 && r.status !== 404) return null;  // slowed down, or the API is away: no preview, nothing kept
    res = new Response(await r.text(), { status: r.status, headers: {
      "content-type": "application/json", "cache-control": `public, max-age=${r.status === 200 ? 300 : 60}` } });
    ctx.waitUntil(caches.default.put(key, res.clone()));
  }
  return res.status === 200 ? ((await res.json()) as Peek) : null;
}

type Invite = { kind: string; name: string; emoji: string; state: string };

/** Whose invite a link is (GET /invites/{code}), kept five minutes like a plan's. */
async function peekInvite(code: string, req: Request, env: Env, ctx: ExecutionContext): Promise<Invite | null> {
  const key = new Request(`https://duecrew.com/__invite/${code}`);
  let res = await caches.default.match(key);
  if (!res) {
    const r = await env.API.fetch(new Request(new URL(`/api/invites/${code}`, req.url), { method: "GET", headers: req.headers }));
    if (r.status !== 200 && r.status !== 404) return null;
    res = new Response(await r.text(), { status: r.status, headers: {
      "content-type": "application/json", "cache-control": `public, max-age=${r.status === 200 ? 300 : 60}` } });
    ctx.waitUntil(caches.default.put(key, res.clone()));
  }
  return res.status === 200 ? ((await res.json()) as Invite) : null;
}

/** The page head for an invite: "Sam invited you", and its picture. */
export function inviteTags(inv: Invite, code: string, origin: string): string {
  const url = `${origin}/i/${code}`;
  const title = `${inv.emoji ? `${inv.emoji} ` : ""}${inv.name} invited you to Due Crew`;
  const text = "Study together in Anki. Due Crew is a free add-on.";
  return [
    ["name", "description", text],
    ["property", "og:type", "website"], ["property", "og:site_name", "Due Crew"],
    ["property", "og:title", title], ["property", "og:description", text], ["property", "og:url", url],
    ["property", "og:image", `${url}.png`], ["property", "og:image:width", "1200"], ["property", "og:image:height", "630"],
    ["property", "og:image:alt", `${inv.name} invited you to Due Crew`],
    ["name", "twitter:card", "summary_large_image"], ["name", "twitter:title", title],
    ["name", "twitter:description", text], ["name", "twitter:image", `${url}.png`],
  ].map(([k, n, v]) => `<meta ${k}="${n}" content="${attr(v)}">`).join("");
}

const attr = (s: string) => s.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

/** The page head a chat app reads: the plan's name, one line, its picture. */
export function previewTags(p: Peek, code: string, origin: string): string {
  const url = `${origin}/p/${code}`;
  const img = `${url}.png?v=${p.v ?? 0}`;
  const text = describe(p);
  return [
    ["name", "description", text],
    ["property", "og:type", "website"], ["property", "og:site_name", "Due Crew"],
    ["property", "og:title", p.name], ["property", "og:description", text], ["property", "og:url", url],
    ["property", "og:image", img], ["property", "og:image:width", "1200"], ["property", "og:image:height", "630"],
    ["property", "og:image:alt", `${p.name}, a plan on Due Crew`],
    ["name", "twitter:card", "summary_large_image"], ["name", "twitter:title", p.name],
    ["name", "twitter:description", text], ["name", "twitter:image", img],
  ].map(([k, n, v]) => `<meta ${k}="${n}" content="${attr(v)}">`).join("");
}

export default {
  async fetch(req: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(req.url);
    if (url.pathname.startsWith("/api/")) return env.API.fetch(req);
    // 3.4: a plan's calendar, for Google, Apple and Outlook to subscribe to
    const cal = /^\/p\/([A-Za-z0-9]{8})\.ics$/.exec(url.pathname);
    if (cal) return env.API.fetch(new Request(new URL(`/api/plans/ics?code=${cal[1]}`, url), { method: "GET", headers: req.headers }));
    // 3.5, A2: a plan's picture, drawn once per version of the plan
    const pic = PLAN_PNG.exec(url.pathname);
    if (pic) {
      const code = pic[1].toUpperCase();
      const p = await peek(code, req, env, ctx);
      if (!p) return new Response("No plan with that code", { status: 404, headers: { "cache-control": "public, max-age=60" } });
      // any ?v= is the current version's picture: asking for many can't draw many
      const key = new Request(`https://duecrew.com/p/${code}.png?v=${p.v ?? 0}`);
      const hit = await caches.default.match(key);
      if (hit) return hit;
      const res = new Response(await png(await draw(p, code)), { headers: {
        "content-type": "image/png", "x-content-type-options": "nosniff", "cache-control": url.searchParams.get("v") === String(p.v) ? "public, max-age=604800" : "public, max-age=3600" } });
      ctx.waitUntil(caches.default.put(key, res.clone()));
      return res;
    }
    // 3.4.1: an invite's picture: the name only, drawn per name
    const ipic = INVITE_PNG.exec(url.pathname);
    if (ipic) {
      const inv = await peekInvite(ipic[1].toUpperCase(), req, env, ctx);
      if (!inv) return new Response("No invite with that code", { status: 404, headers: { "cache-control": "public, max-age=60" } });
      return new Response(await png(await drawInvite(inv.name)), { headers: {
        "content-type": "image/png", "x-content-type-options": "nosniff", "cache-control": "public, max-age=3600" } });
    }
    // 3.2: signed in, duecrew.com opens on your home, not the landing page.
    // The cookie is only a hint here: the home asks the API who you are.
    if (url.pathname === "/" && /(?:^|;\s*)dc_session=/.test(req.headers.get("cookie") || "")) {
      return new Response(null, { status: 302, headers: { location: "/home", "cache-control": "no-store" } });
    }
    if (APP.test(url.pathname)) {
      const page = await env.ASSETS.fetch(new Request(new URL("/app", url), { method: "GET" }));
      const headers = new Headers(page.headers);
      headers.set("content-security-policy", CSP);
      headers.set("cache-control", "no-store");
      headers.set("referrer-policy", "no-referrer");  // the link's token never leaves in a Referer
      const out = new Response(page.body, { status: page.status, headers });
      // 3.5, A1: a plan's link previews as the plan in a chat
      // 3.4.1: and an invite's as who sent it
      const inv = INVITE_PAGE.exec(url.pathname);
      const ip = inv && page.status === 200 ? await peekInvite(inv[1].toUpperCase(), req, env, ctx) : null;
      if (inv && ip) {
        return new HTMLRewriter()
          .on("title", { element(e) { e.setInnerContent(`${ip.name} invited you · Due Crew`); } })
          .on("head", { element(e) { e.append(inviteTags(ip, inv[1].toUpperCase(), "https://duecrew.com"), { html: true }); } })
          .transform(out);
      }
      const plan = PLAN_PAGE.exec(url.pathname);
      const p = plan && page.status === 200 ? await peek(plan[1].toUpperCase(), req, env, ctx) : null;
      if (!plan || !p) return out;
      const code = plan[1].toUpperCase();
      return new HTMLRewriter()
        .on("title", { element(e) { e.setInnerContent(`${p.name} · Due Crew`); } })
        .on("head", { element(e) { e.append(previewTags(p, code, "https://duecrew.com"), { html: true }); } })
        .transform(out);
    }
    return env.ASSETS.fetch(req);
  },
};
