// duecrew.com. Static files, plus two things only a Worker can do:
// /api/* goes to the API Worker (a service binding, so the session is a
// same-site cookie), and the app's paths get the one app page with a CSP
// that lets its own script run.

interface Env {
  ASSETS: { fetch(req: Request): Promise<Response> };
  API: { fetch(req: Request): Promise<Response> };
}

const APP = /^\/(sign-in|account|home|log|admin|plans|plans\/[A-Za-z0-9-]+(\/edit)?|plans\/new|p\/[A-Za-z0-9]{1,16})\/?$/;
const CSP = [
  "default-src 'self'", "img-src 'self' data:", "style-src 'self' 'unsafe-inline'", "script-src 'self'", "connect-src 'self'",
  "base-uri 'none'", "form-action 'none'", "frame-ancestors 'none'",
].join("; ");

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    const url = new URL(req.url);
    if (url.pathname.startsWith("/api/")) return env.API.fetch(req);
    // 3.4: a plan's calendar, for Google, Apple and Outlook to subscribe to
    const cal = /^\/p\/([A-Za-z0-9]{8})\.ics$/.exec(url.pathname);
    if (cal) return env.API.fetch(new Request(new URL(`/api/plans/ics?code=${cal[1]}`, url), { method: "GET" }));
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
      return new Response(page.body, { status: page.status, headers });
    }
    return env.ASSETS.fetch(req);
  },
};
