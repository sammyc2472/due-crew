// duecrew.com's plan pages (Your plans: site/public/planface.js on the
// add-on's page) against a stub API: site/public served as the site's
// Worker serves it, /api/* answered from a sample plan held here (an
// author's, two following, a deck tree as Anki sends it). No wrangler, no
// database; nothing leaves this computer.
//
//   node tools/plan_site_preview.js              # serves http://localhost:8790 (Ctrl-C stops it)
//   node tools/plan_site_preview.js --shots DIR  # screenshots: each page light and dark, 1240 and 760 wide
"use strict";
const http = require("http");
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..", "site", "public");
const PORT = Number(process.env.PORT || 8790);
const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png" };
const APP = /^\/(sign-in|account|home|log|admin|library|feedback|plans|plans\/[A-Za-z0-9-]+(\/edit)?|plans\/new|p\/[A-Za-z0-9]{1,16}|i\/[A-Za-z0-9]{1,12})\/?$/;  // site/src/index.ts's

// ---- the sample: a deck's tree (as PUT /plans/trees keeps it) and an author's plan ----
const iso = (d) => d.toISOString().slice(0, 10);
const now = new Date();
const mon = new Date(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()));
mon.setUTCDate(mon.getUTCDate() - ((mon.getUTCDay() + 6) % 7) - 7);
const day = (n) => { const d = new Date(mon); d.setUTCDate(d.getUTCDate() + n); return iso(d); };
const R = "#Big_Step_1";
const TREE = {
  deck: "Big Step 1", v: 2, at: Math.floor(Date.now() / 1000) - 86400,
  tags: [[R, 2400, [["#Path_Book", 1300, [
    ["01_Cell_injury", 180, [["Adaptations", 60], ["Cell_death", 90], ["Extra", 30]]], ["02_Inflammation", 220, [["Acute", 100], ["Chronic", 120]]],
    ["03_Neoplasia", 260, [["Nomenclature", 110], ["Progression", 150]]], ["04_Hemostasis", 200, [["Platelets", 90], ["Coagulation", 110]]],
    ["05_Red_cell_disorders", 240, [["Microcytic", 80], ["Hemolytic", 100], ["Macrocytic", 60]]], ["06_White_cell_disorders", 200, [["Leukemias", 110], ["Lymphomas", 90]]]]],
  ["#Video_Series", 700, [["Heme", 300, [["Anemia", 180], ["Coagulation", 120]]], ["Cardio", 400, [["Heart_Failure", 220], ["Arrhythmias", 180]]]]],
  ["^Systems", 1100, [["Heme", 600], ["Cardio", 500]]], ["#Bank", 300, [["10230", 100], ["10231", 100], ["10232", 100]]]]]],
  decks: [["Big Step 1::Extras", 60], ["Big Step 1::Extras::Images", 25]],
};
const P = (k) => `${R}::#Path_Book::${k}`;
function sample() {
  const units = [
    { id: "u1", name: "Cell injury", opens: day(0), due: day(2), tags: [P("01_Cell_injury")], decks: [], cards: [], todo: [{ k: "watch", t: "Lecture 3, cell injury", url: "https://example.org/l3" }] },
    { id: "u2", name: "Inflammation", opens: day(3), tags: [P("02_Inflammation")], decks: [], cards: [["g1", 0], ["g2", 1]] },
    { id: "u3", name: "Neoplasia", opens: day(7), due: day(9), tags: [P("03_Neoplasia")], decks: [], cards: [], for: "q1" },
    { id: "u4", name: "Hemostasis", opens: day(10), tags: [P("04_Hemostasis"), `${R}::#Video_Series::Heme::Coagulation`], decks: [], cards: [], for: "q1" },
    { id: "u5", name: "Red cells", opens: day(14), due: day(16), even: true, tags: [P("05_Red_cell_disorders")], decks: [], cards: [] },
    { id: "u6", name: "White cells", opens: day(17), tags: [P("06_White_cell_disorders")], decks: ["Big Step 1::Extras"], cards: [] },
    { id: "u7", name: "Questions", opens: day(21), tags: [`${R}::#Bank::10230`, `${R}::#Bank::10231`, `${R}::#Bank::10232`], decks: [], cards: [],
      search: [`"tag:${R}::^Systems::Heme" -"tag:${R}::#Bank::*"`], sn: {} },
  ];
  return { id: "pathplanpreview1", code: "PATH2026", name: "Path, six weeks", line: "Path book in order, then questions.", role: "owner", owner: "sam", ownerName: "Sam",
    audience: "code", squad: null, followers: 2, version: 7, listed: 0, editors: [{ uid: "maya", name: "Maya" }],
    doc: { deck: "Big Step 1", pace: { mode: "daily", days: [1, 1, 1, 1, 1, 0, 0], daily: 60, cover: [`tag:${R}::#Path_Book`] }, end: day(30), phases: { catchup: 0, taper: 3 }, units,
      events: [{ id: "q1", day: day(11), name: "Heme quiz" }, { id: "x1", day: day(30), name: "Block exam" }], reviews: [{ day: day(13), from: "u1", to: "u4" }],
      tags: [{ id: "t1", name: "SLG 12", notes: ["n1", "n2"] }], tagroot: "Path_six_weeks", every: [{ k: "do", t: "Practice questions", r: "13" }] } };
}
let plan = sample();
const log = [{ version: 7, uid: "maya", name: "Maya", at: Math.floor(Date.now() / 1000) - 3600, summary: "moved Neoplasia to Mon", undo: true }];
const json = (res, code, body) => { res.writeHead(code, { "content-type": "application/json" }); res.end(JSON.stringify(body)); };
function api(req, res, url, body) {
  const p = url.pathname.replace(/^\/api/, ""), m = req.method;
  const id = plan.id;
  if (p === "/auth/me") return json(res, 200, { uid: "sam", name: "Sam", accent: process.env.ACCENT || "green", rollover: 4 });
  if (m === "GET" && p === "/plans/mine") return json(res, 200, { plans: [{ ...plan, doc: { ...plan.doc, units: plan.doc.units } },
    { id: "theirplanpreview", name: "Boards sprint", role: "follower", ownerName: "Maya", followers: 9, doc: { deck: "Big Step 1", units: [] } }] });
  if (m === "GET" && p === "/plans/trees") return json(res, 200, { trees: url.searchParams.get("deck") ? [TREE] : [{ deck: "Big Step 1", at: TREE.at }, { deck: "Español 1", at: TREE.at }] });
  if (m === "GET" && p === "/squads/mine") return json(res, 200, { squads: [{ id: "orca", name: "Orca" }] });
  if (m === "GET" && p === `/plans/${id}`) return json(res, 200, plan);
  if (m === "GET" && p === `/plans/${id}/notes`) return json(res, 200, { notes: [{ id: "n1", day: day(0), text: "Lab day, keep it light?", name: "Maya", mine: false, remove: false }] });
  if (m === "PUT" && p === `/plans/${id}`) {
    if (body.version !== plan.version) return json(res, 409, { error: "stale" });
    plan = { ...plan, version: plan.version + 1, name: body.name ?? plan.name, line: body.line ?? plan.line, doc: body.doc || plan.doc };
    log.unshift({ version: plan.version, uid: "sam", name: "Sam", at: Math.floor(Date.now() / 1000), summary: body.summary || "changed the plan", undo: true });
    return json(res, 200, plan);
  }
  if (m === "POST" && p === `/plans/${id}/undo`) { plan = { ...sample(), version: plan.version + 1 }; return json(res, 200, plan); }
  if (m === "GET" && p === `/plans/${id}/log`) return json(res, 200, { log });
  if (m === "GET" && p === `/plans/${id}/posts`) return json(res, 200, { posts: [{ id: "p1", uid: "sam", name: "Sam", text: "Week 2 is the big one.", at: Math.floor(Date.now() / 1000) - 7200, remove: true }] });
  if (m === "GET" && p === "/friends") return json(res, 200, { friends: [{ uid: "kai", name: "Kai", mutual: true }] });
  if (m === "GET" && p === "/plans/public") return json(res, 404, { error: "no_plan" });
  return json(res, 200, {});
}
function serve() {
  return http.createServer((req, res) => {
    const url = new URL(req.url, `http://localhost:${PORT}`);
    if (url.pathname.startsWith("/api/")) {
      let raw = "";
      req.on("data", (c) => { raw += c; });
      req.on("end", () => api(req, res, url, raw ? JSON.parse(raw) : undefined));
      return;
    }
    let f = APP.test(url.pathname) || url.pathname === "/" ? "app.html" : url.pathname.slice(1);
    f = path.join(ROOT, path.normalize(f).replace(/^(\.\.[/\\])+/, ""));
    fs.readFile(f, (err, data) => {
      if (err) { res.writeHead(404); res.end("not here"); return; }
      res.writeHead(200, { "content-type": TYPES[path.extname(f)] || "application/octet-stream" });
      res.end(data);
    });
  }).listen(PORT);
}

async function shots(dir) {
  const { chromium } = require("playwright");
  fs.mkdirSync(dir, { recursive: true });
  const server = serve();
  const b = await chromium.launch();
  const base = `http://localhost:${PORT}`;
  const cmd = (c, a) => `dcplan:${JSON.stringify({ c, a: a || {} })}`;
  // [name, path, steps on the page before the shot]
  const pages = [
    ["plan-list", "/plans/pathplanpreview1/edit", []],
    ["plan-set", "/plans/pathplanpreview1/edit", [cmd("pick", { key: ["date", "u4"] })]],
    ["plan-week", "/plans/pathplanpreview1/edit", ["ui:week"]],
    ["plan-month", "/plans/pathplanpreview1/edit", ["ui:month"]],
    ["plan-deck", "/plans/pathplanpreview1/edit", [cmd("deck", { uid: "u3" })]],
    ["plan-cover", "/plans/pathplanpreview1/edit", [cmd("deck", {})]],
    ["plan-waiting", "/plans/pathplanpreview1/edit", [cmd("move", { uid: "u6", to: day(18) }), cmd("rename", { uid: "u2", name: "Inflammation, acute and chronic" })]],
    ["plan-send", "/plans/pathplanpreview1/edit", [cmd("move", { uid: "u6", to: day(18) }), cmd("review_send")]],
    ["plan-menu", "/plans/pathplanpreview1/edit", [cmd("pick", { key: ["date", "u4"] }), "click:.side .src"]],
    ["insights", "/plans/pathplanpreview1/edit", [cmd("tab", { tab: "insights" })]],
    ["settings", "/plans/pathplanpreview1/edit", [cmd("tab", { tab: "settings" })]],
    ["settings-shape", "/plans/pathplanpreview1/edit", [cmd("tab", { tab: "settings" }), cmd("tabcmd", { name: "shape", args: { key: "start", value: day(7) } })]],
    ["new-pick", "/plans/new", []],
    ["new-empty", "/plans/new?deck=Big%20Step%201", []],
  ];
  let bad = 0;
  for (const [name, url, steps] of pages) {
    for (const [w, scheme] of [[1240, "light"], [1240, "dark"], [760, "light"], [760, "dark"]]) {
      plan = sample();
      const pg = await b.newPage({ viewport: { width: w, height: 860 }, colorScheme: scheme });
      const errs = [];
      pg.on("pageerror", (e) => errs.push(e.message));
      pg.on("console", (m) => { if (m.type() === "error") errs.push(m.text()); });
      await pg.goto(base + url);
      await pg.waitForSelector("#dcp .foot", { timeout: 8000 }).catch(() => errs.push("the page didn't draw"));
      for (const s of steps) {
        if (s.startsWith("ui:")) await pg.evaluate((m) => dcPlan.set({ mode: m }), s.slice(3));
        else if (s.startsWith("click:")) await pg.click(s.slice(6));
        else await pg.evaluate((m) => window.pycmd(m), s);
        await pg.waitForTimeout(120);
      }
      await pg.waitForTimeout(200);
      // nothing wider than the window: a page that scrolls sideways is clipped somewhere
      const over = await pg.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      if (over > 1) errs.push(`${over}px wider than the window`);
      await pg.screenshot({ path: path.join(dir, `${name}-${w}-${scheme}.png`), fullPage: w < 1000 });
      if (errs.length) { bad++; console.log(name, w, scheme, errs); }
      await pg.close();
    }
  }
  await b.close();
  server.close();
  console.log(bad ? `${bad} with errors` : "ok");
  process.exit(bad ? 1 : 0);
}

const at = process.argv.indexOf("--shots");
if (at >= 0) shots(process.argv[at + 1] || path.join(__dirname, "plan_site_shots"));
else { serve(); console.log(`http://localhost:${PORT}/plans/pathplanpreview1/edit  ·  /plans/new  (Ctrl-C stops it)`); }
