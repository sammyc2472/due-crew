import { createExecutionContext, waitOnExecutionContext } from "cloudflare:test";
import { env } from "cloudflare:workers";
import { describe, expect, it } from "vitest";
import site from "../../site/src/index";
import { W, H, draw, png, weeks, wrap } from "../../site/src/og";
import worker from "../src/index";
import { person } from "./helpers";

// 3.5, A: duecrew.com's Worker, with the API behind its binding as in production

const APP_HTML = `<!doctype html><html><head><meta charset="utf-8"><title>Due Crew</title></head><body><main id="app"></main></body></html>`;
const siteEnv = {
  ASSETS: { fetch: async (req: Request) => new URL(req.url).pathname === "/app"
    ? new Response(APP_HTML, { headers: { "content-type": "text/html" } }) : new Response("static", { status: 200 }) },
  API: { fetch: (req: Request) => worker.fetch(req, { ...env, EMAIL: undefined } as any) },
};

async function get(path: string) {
  const ctx = createExecutionContext();
  const res = await site.fetch(new Request(`https://duecrew.com${path}`, { headers: { "CF-Connecting-IP": "198.51.100.9" } }), siteEnv, ctx);
  const body = res.headers.get("content-type")?.startsWith("image/") ? new Uint8Array(await res.arrayBuffer()) : await res.text();
  await waitOnExecutionContext(ctx);
  return { res, body };
}

async function plan(name = 'Cardio "block" <1>', uid = "priya") {
  const priya = await person(uid);
  const made = await priya.call("POST", "/plans", { name, deck: "Big Step 1", line: "One lecture a day" });
  const put = await priya.call("PUT", `/plans/${made.body.id}`, { version: 1, doc: { deck: "Big Step 1",
    events: [{ id: "q", day: "2026-10-16", name: "Quiz" }],
    units: [{ id: "a", name: "L1", opens: "2026-10-05", tags: ["C::1"], n: 80 }, { id: "b", name: "L2", opens: "2026-10-13", tags: ["C::2"], n: 40 }] } });
  return { priya, p: put.body };
}

describe("a plan's link previews as the plan (3.5, A)", () => {
  it("A1: the page head carries its name, one line and picture, escaped", async () => {
    const { p } = await plan();
    const { res, body } = await get(`/p/${p.code.toLowerCase()}`);
    expect(res.status).toBe(200);
    expect(res.headers.get("content-security-policy")).toContain("script-src 'self'");
    const html = body as string;
    expect(html).toContain(`<title>Cardio &quot;block&quot; &lt;1&gt; · Due Crew</title>`.replace(/&quot;/g, '"'));
    expect(html).toContain(`<meta property="og:title" content="Cardio &quot;block&quot; &lt;1&gt;">`);
    expect(html).toContain(`<meta property="og:image" content="https://duecrew.com/p/${p.code}.png?v=${p.version}">`);
    expect(html).toContain(`<meta name="twitter:card" content="summary_large_image">`);
    expect(html).toContain("One lecture a day Priya&#39;s plan".replace("&#39;", "'"));
    expect(html).not.toContain("<1>");
  });

  it("an unknown code, a squad's plan or another page gets the plain head", async () => {
    const { priya, p } = await plan();
    expect((await get("/p/NOPE2345")).body).not.toContain("og:title");
    expect((await get("/plans")).body).not.toContain("og:title");
    const sq = await priya.call("POST", "/squads", { name: "busm" });
    await priya.call("PUT", `/plans/${p.id}`, { version: p.version, audience: "squad", squad: sq.body.id });
    const q = await plan("Another", "dre");
    expect((await get(`/p/${p.code}`)).body).not.toContain("og:title");  // a squad's plan
    expect((await get(`/p/${q.p.code}`)).body).toContain("og:title");
  });

  it("A2: the picture is a 1200x630 PNG, drawn once per version whatever ?v= asks", async () => {
    const { p } = await plan();
    const { res, body } = await get(`/p/${p.code}.png?v=${p.version}`);
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toBe("image/png");
    expect(res.headers.get("cache-control")).toBe("public, max-age=604800");
    const b = body as Uint8Array;
    expect([...b.slice(0, 8)]).toEqual([137, 80, 78, 71, 13, 10, 26, 10]);
    const dv = new DataView(b.buffer, b.byteOffset);
    expect([dv.getUint32(16), dv.getUint32(20)]).toEqual([1200, 630]);
    expect(b.length).toBeGreaterThan(5000);
    expect((await get(`/p/${p.code}.png?v=999`)).res.status).toBe(200);
    expect((await get("/p/NOPE2345.png")).res.status).toBe(404);
  });
});

describe("og.ts", () => {
  it("weeks: a plan's weeks from its first Monday, events marked, long plans in pairs", () => {
    const w = weeks({ name: "x", ownerName: "y", deck: "d", followers: 0, events: [{ day: "2026-10-16", name: "Q" }],
      units: [{ name: "a", opens: "2026-10-07", n: 5 }, { name: "b", opens: "2026-10-19", due: "2026-10-27", n: 7 }] });
    expect(w).toEqual([{ n: 5, event: false }, { n: 0, event: true }, { n: 7, event: false }, { n: 0, event: false }]);
    const long = weeks({ name: "x", ownerName: "y", deck: "d", followers: 0,
      units: [{ name: "a", opens: "2026-01-05", n: 1 }, { name: "b", opens: "2026-12-28", n: 1 }] });
    expect(long.length).toBeLessThanOrEqual(26);
  });

  it("draws a picture whatever the name's script, and wraps a long name to two lines", async () => {
    const cv = await draw({ name: "日本語", ownerName: "Ken", deck: "日本語", followers: 0, units: [] }, "7KQ4MX2D");
    expect(cv.px.length).toBe(W * H * 3);
    const p = await png(cv);
    expect(p.length).toBeGreaterThan(1000);
    const { FACES } = await import("../../site/src/og_assets");
    const f = { ascent: FACES.title.ascent, glyphs: new Map(FACES.title.glyphs.map(([c, adv, l, t, w, h, off]) => [c, { adv: adv / 16, l, t, w, h, off }])) };
    const lines = wrap(f, "Step 1 in 8 weeks, a system a week, V&B then Path Book, with review weeks before the NBME forms", 1040, 2);
    expect(lines).toHaveLength(2);
    expect(lines[1].endsWith("…")).toBe(true);
    expect(wrap(f, "Short", 1040, 2)).toEqual(["Short"]);
  });
});

describe("3.5.0: an invite's link previews as who sent it", () => {
  it("the head says who, escaped; the picture draws; an unknown code gets the plain head", async () => {
    const sam = await person("sam", 'Sam "<b>"');
    const code = (await sam.call("POST", "/invites")).body.code;
    const { res, body } = await get(`/i/${code.toLowerCase()}`);
    expect(res.status).toBe(200);
    expect(res.headers.get("referrer-policy")).toBe("no-referrer");
    const html = body as string;
    expect(html).toContain(`<meta property="og:title" content="Sam &quot;&lt;b&gt;&quot; invited you to Due Crew">`);
    expect(html).toContain(`<meta property="og:image" content="https://duecrew.com/i/${code}.png">`);
    expect(html).not.toContain("<b>");
    const pic = await get(`/i/${code}.png`);
    expect(pic.res.headers.get("content-type")).toBe("image/png");
    expect((pic.body as Uint8Array).slice(1, 4)).toEqual(new Uint8Array([80, 78, 71]));
    expect((await get("/i/ZZZZZZZZZZ")).body).not.toContain("og:title");
    expect((await get("/i/ZZZZZZZZZZ.png")).res.status).toBe(404);
  });
});
