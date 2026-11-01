// duecrew.com's plan pages (site/public/planface.js) driven in node: the
// face on builder.js's plan, the shared page (site/public/planpage/*.js)
// drawing its view in a small DOM of its own, every control fired, and
// every message it sends handled by the face. A save goes out as the
// builder's own (PUT /plans/{id}, its body); with followers, changes wait
// for Review and send. Standard library only.
//
//   node tests/planface_test.js        prints {checks: [[name, ok, detail]]}; exit 1 on a failed one
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.join(__dirname, "..");
const read = (p) => fs.readFileSync(path.join(ROOT, p), "utf8");
const checks = [];
const check = (name, ok, detail) => { checks.push([name, !!ok, ok ? "" : JSON.stringify(detail === undefined ? "" : detail).slice(0, 600)]); };

// ---- a small DOM: enough for app.js's h(), builder.js and the page ----
function makeDom() {
  class Node {}
  class Text extends Node { constructor(t) { super(); this.data = String(t); this.parent = null; } get textContent() { return this.data; } remove() { El.prototype.remove.call(this); } }
  class El extends Node {
    constructor(tag) {
      super();
      this.tagName = String(tag).toUpperCase(); this.children = []; this.attrs = {}; this.style = {}; this.className = ""; this.parent = null;
      this.ls = {}; this.value = ""; this.dataset = {}; this.disabled = false; this.checked = false;
      const self = this;
      this.classList = {
        add: (...cs) => { for (const c of cs) if (!self.classList.contains(c)) self.className = `${self.className} ${c}`.trim(); },
        remove: (...cs) => { self.className = self.className.split(/\s+/).filter((x) => x && !cs.includes(x)).join(" "); },
        toggle: (c, on) => { const has = self.classList.contains(c); if (on === undefined ? has : !on) self.classList.remove(c); else self.classList.add(c); },
        contains: (c) => self.className.split(/\s+/).includes(c),
      };
    }
    get textContent() { return this.children.map((c) => c.textContent || "").join(""); }
    set textContent(v) { for (const c of this.children) c.parent = null; this.children = v === "" || v === null || v === undefined ? [] : [new Text(v)]; }
    get childNodes() { return this.children; }
    get parentNode() { return this.parent; }
    appendChild(c) { if (c.parent) c.remove(); c.parent = this; this.children.push(c); return c; }
    append(...cs) { for (const c of cs) this.appendChild(c instanceof Node ? c : new Text(c)); }
    replaceChildren(...cs) { for (const c of this.children) c.parent = null; this.children = []; this.append(...cs); }
    remove() { if (this.parent) { const i = this.parent.children.indexOf(this); if (i >= 0) this.parent.children.splice(i, 1); this.parent = null; } }
    setAttribute(k, v) { this.attrs[k] = String(v); if (k === "disabled") this.disabled = true; if (k === "checked") this.checked = true; if (k === "class") this.className = String(v); }
    getAttribute(k) { return k === "class" ? this.className : k in this.attrs ? this.attrs[k] : null; }
    removeAttribute(k) { delete this.attrs[k]; }
    addEventListener(t, f) { (this.ls[t] = this.ls[t] || []).push(f); }
    removeEventListener() {}
    getBoundingClientRect() { return { left: 0, top: 0, right: 10, bottom: 10, width: 10, height: 10 }; }
    focus() {} blur() {} select() {} scrollIntoView() {} setSelectionRange() {} click() { fire(this, "click"); }
    contains(x) { for (let n = x; n; n = n.parent) if (n === this) return true; return false; }
    querySelectorAll(sel) { const out = []; walk(this, (el) => { if (el !== this && matches(el, sel, this)) out.push(el); }); return out; }
    querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  }
  // selectors as the page writes them: tag, .class, [attr] and [attr=v], a descendant of another
  const part = (el, s) => {
    const m = /^([a-z]*)((?:\.[\w-]+)*)(?:\[([\w-]+)(?:=([\w-]+))?\])?$/i.exec(s);
    if (!m || !(el instanceof El)) return false;
    if (m[1] && el.tagName !== m[1].toUpperCase()) return false;
    for (const c of m[2].split(".").filter(Boolean)) if (!el.classList.contains(c)) return false;
    if (m[3]) { const v = el.getAttribute(m[3]); if (v === null || (m[4] !== undefined && v !== m[4])) return false; }
    return true;
  };
  function matches(el, sel, top) {
    return sel.split(",").some((one) => {
      const ps = one.trim().split(/\s+/);
      if (!part(el, ps[ps.length - 1])) return false;
      let i = ps.length - 2;
      for (let n = el.parent; n && n !== top.parent && i >= 0; n = n.parent) if (part(n, ps[i])) i--;
      return i < 0;
    });
  }
  function walk(el, fn) { fn(el); for (const c of el.children || []) if (c instanceof El) walk(c, fn); }
  function fire(el, t, extra) {
    const ev = { target: el, currentTarget: el, stopPropagation() {}, preventDefault() {}, key: "Enter", dataTransfer: { setData() {}, getData: () => "[]" }, ...(extra || {}) };
    for (const f of el.ls[t] || []) f.call(el, ev);
  }
  const body = new El("body"), app = new El("main"); app.attrs.id = "app";
  body.appendChild(app);
  const docLs = {};
  const document = {
    createElement: (t) => new El(t), createTextNode: (t) => new Text(t), body, activeElement: null,
    getElementById: (id) => { let got = null; walk(body, (el) => { if (!got && el.attrs.id === id) got = el; }); return got; },
    querySelector: (s) => body.querySelector(s), querySelectorAll: (s) => body.querySelectorAll(s),
    addEventListener: (t, f) => { (docLs[t] = docLs[t] || []).push(f); }, contains: (x) => body.contains(x), onkeydown: null,
  };
  return { Node, El, Text, document, body, app, walk, fire };
}

// ---- the site's scripts in a context of their own ----
function makeSite(store) {
  const dom = makeDom();
  const sent = [], went = [], copied = [], calls = [];
  const ctx = {
    console, JSON, Math, Date, Promise, Set, Map, Object, Array, String, Number, RegExp, Error, URLSearchParams, structuredClone, Intl,
    setTimeout: (f) => { try { f(); } catch { /* a focus */ } return 0; }, clearTimeout() {},
    requestAnimationFrame: () => 0, matchMedia: () => ({ matches: false }), navigator: { platform: "Linux", clipboard: { writeText: async (t) => { copied.push(t); } } },
    location: { origin: "https://duecrew.com", pathname: "/plans", search: "", hash: "" }, history: { pushState() {}, replaceState() {} },
    document: dom.document, Node: dom.Node, innerWidth: 1240, innerHeight: 820, crypto: { getRandomValues: (a) => { for (let i = 0; i < a.length; i++) a[i] = (Math.random() * 256) | 0; return a; } },
    scrollTo() {}, scrollY: 0, addEventListener() {}, open: (u) => went.push(`open:${u}`),
  };
  ctx.window = ctx;
  vm.createContext(ctx);
  const app = read("site/public/app.js");
  // the helpers (h, page, the dates, deckLink…) and Sched; api is the store's
  const helpers = app.slice(app.indexOf("// ---- small helpers ----"), app.indexOf("// ---- my accent")).replace("async function api(method, path, body) {", "async function realApi(method, path, body) {");
  const sched = app.slice(app.indexOf("const Sched = (() => {"), app.indexOf("// ---- 3.2: home"));
  const src = [helpers, "let me = { uid: 'sam', name: 'Sam' };", sched, read("site/public/builder.js"),
    read("site/public/planpage/plan.js"), read("site/public/planpage/tabs.js"), read("site/public/planpage/new.js"), read("site/public/planface.js"),
    "this.PlanFace = PlanFace; this.builder = builder; this.dcPlan = dcPlan; this.Sched = Sched; this.today = today; this.addDays = addDays;"].join("\n;\n");
  ctx.api = async (method, p, body) => {
    calls.push([method, p, body === undefined ? undefined : JSON.parse(JSON.stringify(body))]);
    return store(method, p, body);
  };
  ctx.go = (p) => went.push(p);
  vm.runInContext(src, ctx, { filename: "site.js" });
  ctx.pycmd = (m) => sent.push(m);
  return { ctx, dom, sent, went, copied, calls };
}

// ---- a sample plan and the API, as the Worker answers (worker/README.md) ----
const ROOTTAG = "#Big_Step_1";
const TREE = {
  deck: "Big Step 1", v: 2, at: 1790000000,
  tags: [[ROOTTAG, 900, [["#Path_Book", 500, [["01_Cell_injury", 120, [["Adaptations", 40], ["Cell_death", 60], ["Extra", 20]]],
    ["02_Inflammation", 160, [["Acute", 70], ["Chronic", 90]]], ["03_Neoplasia", 220, [["Progression", 120], ["Nomenclature", 100]]]]],
  ["^Systems", 300, [["Heme", 180], ["Cardio", 120]]], ["#Bank", 100, [["10230", 50], ["10231", 50]]]]]],
  decks: [["Big Step 1::Extras", 30]],
};
function plans(day, followers) {
  const units = [
    { id: "u1", name: "Cell injury", opens: day(0), due: day(2), tags: [`${ROOTTAG}::#Path_Book::01_Cell_injury`], decks: [], cards: [], todo: [{ k: "watch", t: "Lecture 3" }] },
    { id: "u2", name: "Inflammation", opens: day(7), tags: [`${ROOTTAG}::#Path_Book::02_Inflammation`], decks: [], cards: [["g1", 0]], search: [`"tag:${ROOTTAG}::^Systems::Heme"`], for: "q1" },
    { id: "u3", name: "Questions", opens: day(14), tags: [`${ROOTTAG}::#Bank::10230`, `${ROOTTAG}::#Bank::10231`], decks: ["Big Step 1::Extras"], cards: [] },
  ];
  const doc = { deck: "Big Step 1", pace: { mode: "daily", days: [1, 1, 1, 1, 1, 0, 0], daily: 30 }, end: day(28), phases: { catchup: 0, taper: 3 },
    units, events: [{ id: "q1", day: day(10), name: "Path quiz" }, { id: "x1", day: day(28), name: "Block exam" }], reviews: [{ day: day(9), from: "u1", to: "u2" }],
    tags: [{ id: "t1", name: "SLG 12", notes: ["n1"] }], tagroot: "Path_plan", remarks: [{ id: "r1", card: ["g1", 0], text: "on the quiz" }] };
  return { id: "planaaaaaaaaaaaa", code: "PATH2026", name: "Path plan", line: "Path, then questions.", role: "owner", owner: "sam", ownerName: "Sam",
    audience: "code", squad: null, followers, version: 3, editors: [{ uid: "maya", name: "Maya" }], listed: 0, doc };
}
function makeStore(plan) {
  const log = [];
  let p = JSON.parse(JSON.stringify(plan));
  const fn = async (method, url, body) => {
    const [pth] = url.split("?");
    if (method === "GET" && pth === `/plans/${p.id}`) return JSON.parse(JSON.stringify(p));
    if (method === "GET" && pth === "/plans/trees") return { trees: url.includes("deck=") ? [TREE] : [{ deck: TREE.deck, at: TREE.at }] };
    if (method === "GET" && pth === "/squads/mine") return { squads: [{ id: "sq1", name: "Orca" }] };
    if (method === "GET" && pth === `/plans/${p.id}/notes`) return { notes: [{ id: "n9", day: p.doc.units[0].opens, text: "Lab day", name: "Maya", mine: false, remove: false }] };
    if (method === "GET" && pth === "/plans/mine") return { plans: [{ ...p, doc: undefined }, { id: "otherplanxxxxxxx", name: "Theirs", role: "follower", ownerName: "Dre", followers: 4 }] };
    if (method === "PUT" && pth === `/plans/${p.id}`) {
      if (body.version !== p.version) { const e = new Error("stale"); e.status = 409; e.body = { error: "stale" }; throw e; }
      log.push(body);
      p = { ...p, version: p.version + 1, name: body.name ?? p.name, line: body.line ?? p.line, doc: body.doc ? JSON.parse(JSON.stringify(body.doc)) : p.doc,
        audience: body.audience ?? p.audience, squad: body.squad !== undefined ? body.squad : p.squad, posted: body.post ? { id: "p1", text: body.post } : undefined };
      return JSON.parse(JSON.stringify(p));
    }
    if (method === "POST" && pth === `/plans/${p.id}/undo`) { p = { ...p, version: p.version + 1, doc: JSON.parse(JSON.stringify(plan.doc)) }; return JSON.parse(JSON.stringify(p)); }
    if (method === "GET" && pth === `/plans/${p.id}/log`) return { log: [{ version: p.version, uid: "sam", name: "Sam", at: 1790000000, summary: "moved a set", undo: true }] };
    if (method === "GET" && pth === `/plans/${p.id}/posts`) return { posts: [{ id: "p1", uid: "sam", name: "Sam", text: "Hi all", at: 1790000000, remove: true }] };
    if (method === "POST" && pth === `/plans/${p.id}/posts`) return { id: "p2", text: body.text };
    if (method === "DELETE") return {};
    if (method === "GET" && pth === "/friends") return { friends: [{ uid: "kai", name: "Kai", mutual: true }, { uid: "maya", name: "Maya", mutual: true }] };
    if (method === "POST" && pth === `/plans/${p.id}/editors`) return { editors: [...(p.editors || []), { uid: body.uid, name: "Kai", pending: true }] };
    if (method === "POST" && pth === `/plans/${p.id}/owner`) return { editors: p.editors, handover: body.uid };
    if (method === "PUT" && pth === `/plans/${p.id}/listed`) { p = { ...p, listed: body.listed ? 1 : 0 }; return JSON.parse(JSON.stringify(p)); }
    if (method === "POST" && pth === `/plans/${p.id}/notes`) return { id: "n10", text: body.text };
    if (method === "POST" && pth === `/plans/${p.id}/copy`) return { id: "copyplanxxxxxxxx", version: 1, name: "Path plan (copy)" };
    if (method === "PUT" && pth === "/plans/copyplanxxxxxxxx") return { id: "copyplanxxxxxxxx", version: 2, name: body.name };
    if (method === "POST" && pth === "/plans") return { id: "newplanxxxxxxxxx", version: 1, name: body.name, code: "NEW12345", doc: { deck: body.deck, units: [] } };
    if (method === "PUT" && pth === "/plans/newplanxxxxxxxxx") { log.push(body); return { id: "newplanxxxxxxxxx", version: 2, name: body.name, code: "NEW12345", doc: body.doc }; }
    if (method === "POST" && pth === "/plans/follow") return { ok: true };
    const e = new Error(`no route ${method} ${url}`); e.status = 404; e.body = { error: "no_route" }; throw e;
  };
  return { fn, log, now: () => p };
}

// ---- a face on a sample plan ----
async function face(followers, opts = {}) {
  const store = makeStore(plans((n) => null, followers));
  const site = makeSite(store.fn);
  const { ctx } = site;
  const t0 = ctx.today(), mon = ctx.Sched.monday(t0);
  const day = (n) => ctx.addDays(mon, n);
  const p = plans(day, followers);
  const st2 = makeStore(p);
  ctx.api = async (method, url, body) => {
    site.calls.push([method, url, body === undefined ? undefined : JSON.parse(JSON.stringify(body))]);
    if (opts.noTree && url.startsWith("/plans/trees")) return { trees: [] };  // the deck's tags not sent from Anki yet
    return st2.fn(method, url, body);
  };
  let f = null;
  const got = await ctx.api("GET", `/plans/${p.id}`);
  const B = await ctx.builder(p.id, { attach: (x) => x, drawn: () => { if (f) f.push(); } }, got);
  const shown = [], sheets = [], said = [];
  f = ctx.PlanFace.make(B, { plans: (await ctx.api("GET", "/plans/mine")).plans, tab: opts.tab, go: (u) => site.went.push(u),
    copy: async (t) => { site.copied.push(t); },
    out: { show: (v) => shown.push(v), sheet: (s) => sheets.push(s), status: (s) => said.push(s.status), openUndo() {}, pasted() {},
      download: (u) => site.went.push(`download:${u}`) } });
  f.cmd("dcplan:" + JSON.stringify({ c: "ready", a: {} }));
  return { site, ctx, f, B, store: st2, shown, sheets, said, day, p };
}
const msg = (c, a) => "dcplan:" + JSON.stringify({ c, a: a || {} });
const settle = () => new Promise((r) => setImmediate(r));
async function run(x, c, a) { x.f.cmd(msg(c, a)); for (let i = 0; i < 6; i++) await settle(); return x.shown[x.shown.length - 1]; }

// ---- the page, drawn from the face's view, every control fired ----
function drawAll(x, view, sheet) {
  const { ctx, dom } = x.site;
  const root = new dom.El("div"); root.attrs.id = "dcp"; root.className = "dcp";
  dom.app.replaceChildren(root);
  const sent = [], errors = [];
  ctx.pycmd = (m) => sent.push(m);
  const draw = () => { ctx.dcPlan.show(JSON.parse(JSON.stringify(view))); if (sheet) ctx.dcPlan.sheet(JSON.parse(JSON.stringify(sheet))); };
  try { ctx.dcPlan.start(JSON.parse(JSON.stringify(view)), true); if (sheet) ctx.dcPlan.sheet(JSON.parse(JSON.stringify(sheet))); } catch (e) { errors.push(`draw: ${e.stack}`); }
  const text = root.textContent;
  const controls = () => { const xs = []; dom.walk(root, (el) => { if (el !== root && (el.ls.click || el.ls.change)) xs.push(el); }); return xs; };
  const menus = () => root.children.filter((c) => / menu/.test(` ${c.className}`));
  const items = (m) => m.children.filter((c) => c.ls && c.ls.click);
  const act = (el) => {
    if (el.tagName === "SELECT") { const o = el.children.filter((c) => c.tagName === "OPTION"); el.value = o.length ? o[o.length - 1].attrs.value : ""; dom.fire(el, "change"); return; }
    if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") {
      const ty = el.attrs.type || "text";
      el.value = ty === "date" ? x.day(3) : ty === "number" ? "4" : "Typed here"; el.checked = !el.checked;
      dom.fire(el, "input"); dom.fire(el, "change"); dom.fire(el, "keydown"); return;
    }
    dom.fire(el, "click");
  };
  const n = controls().length;
  for (let i = 0; i < n; i++) {
    try {
      draw();
      const el = controls()[i];
      if (!el || el.disabled) continue;
      act(el);
      const opened = menus();
      if (opened.length) {
        items(opened[0]).forEach((_mi, j) => {
          draw(); act(controls()[i]);
          const again = items(menus()[0] || { children: [] })[j];
          if (!again) return;
          act(again);
          const subs = menus().slice(1);
          if (subs.length) items(subs[0]).forEach((s) => act(s));
        });
      }
    } catch (e) { errors.push(`control ${i}: ${e.stack}`); }
  }
  ctx.dcPlan.start(null, true);
  return { sent: sent.map((m) => JSON.parse(m.slice("dcplan:".length))), errors, text, controls: n };
}

(async () => {
  // -- the commands: every one the page or the face's view can send has its handler --
  const pageJs = ["plan.js", "tabs.js", "new.js"].map((n) => read(`site/public/planpage/${n}`)).join("\n");
  const named = new Set([...pageJs.matchAll(/send\("([a-z_]+)"/g), ...pageJs.matchAll(/cmd: "([a-z_]+)"/g)].map((m) => m[1]));
  const tabNamed = new Set([...pageJs.matchAll(/run\(\w+(?:\.\w+)?, "([a-z_]+)"/g), ...pageJs.matchAll(/item\("([a-z_]+)"/g)].map((m) => m[1]));
  const a = await face(0);
  const missing = [...named].filter((c) => !a.f.handlers[c]);
  check("planface: every command the shared page sends has a handler in the face", named.size > 40 && !missing.length, missing);
  const missingT = [...tabNamed].filter((c) => !a.f.tabHandlers[c]);
  check("planface: every Insights and Settings click (tabcmd) has a handler in the face", tabNamed.size > 30 && !missingT.length, missingT);
  const viewCmds = (v, out = new Set(), tabs = new Set()) => {
    if (Array.isArray(v)) v.forEach((x) => viewCmds(x, out, tabs));
    else if (v && typeof v === "object") {
      if (typeof v.cmd === "string") { out.add(v.cmd); if (v.cmd === "tabcmd" && v.args && v.args.name) tabs.add(v.args.name); }
      Object.values(v).forEach((x) => viewCmds(x, out, tabs));
    }
    return [out, tabs];
  };

  // -- the view: JSON, the shape the page reads; nothing only Anki does --
  let v = a.shown[a.shown.length - 1];
  check("planface: the view is the page's: a head, the plan's weeks, the picked set's panel", v && v.head && v.head.author && v.plan && v.plan.weeks.length >= 2
    && v.panel && v.panel.kind === "date" && JSON.stringify(v) === JSON.stringify(JSON.parse(JSON.stringify(v))), v && Object.keys(v));
  const all = JSON.stringify(v);
  check("planface: a set is a set (the site's word), nothing says lesson", !/lesson/i.test(JSON.stringify([v.plan, v.panel])), all.match(/.{30}lesson.{30}/i));
  check("planface: Browse is hidden on the site (S.without), no Study now, no Open its cards", v.without.includes("browse") && !v.plan.now
    && !all.includes("open_now") && !all.includes('"cmd":"study"') && !/Study now|in my Anki/.test(all), v.without);
  check("planface: the first set picked is today's, or the next one ahead (webface.plan_shown)", v.picked && v.picked[1] === "u2", v.picked);
  const u1 = (await run(a, "pick", { key: ["date", "u1"] })).panel;
  check("planface: a set's sources have the deck tree's counts", u1.sources.length && u1.sources[0].n === 120 && /Path Book › 1 · Cell injury/.test(u1.sources[0].name), u1.sources);
  check("planface: the source menu: Spread, Leave out its extras, Move to, a note, Copy its search, Take it off",
    ["Spread it…", "Leave out its extras (20 cards)", "Move to", "A note for followers on it…", "Copy its search", "Take it off this set"].every((l) => (u1.sources[0].menu || []).some((m) => m.label === l)),
    (u1.sources[0].menu || []).map((m) => m.label));
  const week1 = v.plan.weeks[0];
  check("planface: a week's line says what it asks: 120 cards over three study days is over a pace of 30",
    week1.words === "40 new a day (over your 30), 25 reviews" && week1.warn && /^Week 1 · /.test(week1.label)
    && v.plan.weeks[1].words && !v.plan.weeks[1].warn && /new, \d+ reviews a day/.test(v.plan.weeks[1].words), [week1.words, v.plan.weeks[1].words]);
  check("planface: a week over the pace says what fixes it", v.plan.weeks.some((wk) => wk.heavy && /new a day, your pace is 30/.test(wk.heavy.words) && wk.heavy.spread), v.plan.weeks.map((wk) => wk.heavy));
  check("planface: Month and Week have each set's days and each day's load", v.plan.cal.length === 5 && Object.keys(v.plan.load).length > 0 && v.plan.cap === 30, v.plan.cal);
  check("planface: the plan's shape in a line", v.plan.shape.some(([k]) => k === "Study days") && v.plan.shape.some(([k, w]) => k === "Dates" && /Block exam/.test(w)), v.plan.shape);
  const qs = (await run(a, "pick", { key: ["date", "u3"] })).panel.sources;
  check("planface: a bank's questions are one row", qs.some((s) => /Bank · 2 questions/.test(s.name) && s.n === 100), qs.map((s) => s.name));

  // -- the page draws every view the face makes, every control fires, every message has its handler --
  const views = {};
  views.plan = await run(a, "pick", { key: ["date", "u1"] });
  views.event = await run(a, "pick", { key: ["event", "q1"] });
  views.review = await run(a, "pick", { key: ["review", a.day(9)] });
  await run(a, "pick", { key: ["date", "u1"] });
  views.deck = await run(a, "deck", { uid: "u1" });
  views.cover = await run(a, "deck", {});
  views.insights = await run(a, "tab", { tab: "insights" });
  views.settings = await run(a, "tab", { tab: "settings" });
  await run(a, "tabcmd", { name: "shape", args: { key: "start", value: a.day(1) } });
  views.shape = a.shown[a.shown.length - 1];
  await run(a, "tabcmd", { name: "shape_back" });
  await run(a, "tab", { tab: "plan" });
  await run(a, "deck_done");
  const sheetsOf = {};
  for (const [c, args] of [["new_date_form"], ["new_event_form"], ["new_review_form"], ["text"], ["see_prompt", { which: "plan" }], ["remark", { path: `${ROOTTAG}::^Systems::Heme` }],
    ["todo"], ["add_search"], ["breather"], ["move_from"], ["spread", { key: ["tag", `${ROOTTAG}::#Path_Book::01_Cell_injury`] }]]) {
    await run(a, c, args);
    sheetsOf[c] = a.sheets[a.sheets.length - 1];
  }
  for (const [n, args] of [["posts"], ["history"], ["coauthor_ask"], ["every"], ["delete_plan"]]) {
    await run(a, "tabcmd", { name: n, args });
    sheetsOf[n] = a.sheets[a.sheets.length - 1];
  }
  const sent = [], drawn = {};
  for (const [k, view] of Object.entries(views)) { const d = drawAll(a, view); drawn[k] = d; sent.push(...d.sent); }
  for (const [k, sh] of Object.entries(sheetsOf)) { const d = drawAll(a, views.plan, sh); drawn[`sheet ${k}`] = d; sent.push(...d.sent); }
  for (const [k, d] of Object.entries(drawn)) check(`planface: the page draws ${k} and every control fires without an error (${d.controls} controls)`, !d.errors.length && d.controls > 0, d.errors.slice(0, 2));
  const [vc, vt] = viewCmds([views, sheetsOf]);
  const unknown = [...new Set([...sent.map((m) => m.c), ...vc])].filter((c) => !a.f.handlers[c]);
  const unknownT = [...new Set([...sent.filter((m) => m.c === "tabcmd").map((m) => m.a.name), ...vt])].filter((c) => !a.f.tabHandlers[c]);
  check("planface: every message the page sent, and every command in the view and its sheets, has its handler", !unknown.length && !unknownT.length && sent.length > 60, [unknown, unknownT, sent.length]);
  check("planface: the page says the site's words", /Tick what the plan covers; then lay it out/.test(drawn.cover.text) && /new a day \(over your 30\)/.test(drawn.plan.text)
    && /This plan/.test(drawn.settings.text) && !/Your AI app/.test(drawn.settings.text) && /Its page: progress, poster/.test(drawn.settings.text)
    && !/in Browse/.test(drawn.plan.text) && /Workload/.test(drawn.insights.text), [drawn.cover.text.slice(0, 200), drawn.settings.text.slice(0, 300)]);
  // each message the page sent, back through a fresh face: nothing it sends throws
  const b = await face(0);
  let threw = [];
  for (const m of sent) { try { b.f.cmd(msg(m.c, m.a)); await settle(); } catch (e) { threw.push([m.c, e.message]); } }
  check("planface: each message the page sent, sent back through a face: none throws", !threw.length, threw.slice(0, 3));

  // -- a change, with nobody following: saved at once, as the builder's save --
  const c = await face(0);
  const before = c.store.log.length;
  await run(c, "rename", { uid: "u1", name: "Cell injury, all of it" });
  const put = c.store.log[before];
  check("planface: with nobody following, a change saves at once (PUT /plans/{id})", c.store.log.length === before + 1 && put && put.version === 3, c.store.log.length);
  // the same change, made in builder.js's own page logic: the same save
  const d0 = makeSite(makeStore(c.p).fn);
  let B2 = null;
  const st3 = makeStore(c.p);
  d0.ctx.api = async (m, u, body) => st3.fn(m, u, body);
  B2 = await d0.ctx.builder(c.p.id, { attach: (x) => x, drawn() {} }, await st3.fn("GET", `/plans/${c.p.id}`));
  B2.nameIt(B2.doc.units.find((u) => u.id === "u1"), "Cell injury, all of it");
  await B2.save();
  const put2 = st3.log[0];
  check("planface: a save goes out as the builder's (the same PUT body: version, name, line, the lean doc, its summary)",
    put2 && JSON.stringify(put) === JSON.stringify(put2) && put.summary === put2.summary && put.doc && put.name === "Path plan", [put && put.summary, put2 && put2.summary]);
  v = c.shown[c.shown.length - 1];
  check("planface: saved: nothing waits, Undo has the save", !v.plan.sending && v.head.undo.some((x) => x.label === "Undo your last save" && x.on) && v.status === "Saved.", [v.status, v.head.undo]);
  await run(c, "undo", { what: ["undo"] });
  check("planface: Undo your last save: POST /plans/{id}/undo, the plan as it was", c.site.calls.some(([m, u]) => m === "POST" && u.endsWith("/undo"))
    && c.B.doc.units.find((u) => u.id === "u1").name === "Cell injury", c.B.doc.units.find((u) => u.id === "u1").name);

  // -- with followers: changes wait under the plan till Review and send --
  const w = await face(2);
  const n0 = w.store.log.length;
  await run(w, "move", { uid: "u3", to: w.day(15) });
  await run(w, "op", { op: { op: "set_due", date: "u2", due: w.day(9) } });
  v = w.shown[w.shown.length - 1];
  check("planface: with followers, changes wait (nothing sent) and the foot says so", w.store.log.length === n0 && v.plan.sending && v.plan.sending.n === 2
    && v.plan.weeks.some((wk) => wk.items.some((it) => it.notSent)), v.plan.sending);
  check("planface: Undo's first line takes back the last change, not sent", /Take back the last change, not sent/.test(v.head.undo[0].label), v.head.undo);
  await run(w, "undo", { what: ["take", 1] });
  check("planface: taken back: the set's finish-by day as it was", !w.B.doc.units.find((u) => u.id === "u2").due && w.f.F.changes.length === 1, w.B.doc.units.find((u) => u.id === "u2"));
  await run(w, "review_send");
  const sh = w.sheets[w.sheets.length - 1];
  check("planface: Review and send: the changes, a line to followers, Send to 2", sh.kind === "send" && sh.rows.length === 1 && sh.yes === "Send to 2" && sh.cmd === "send", sh);
  await run(w, "send", { why: "Questions moved a day" });
  const sentPut = w.store.log[n0];
  check("planface: Send: one save, its line to followers with it", w.store.log.length === n0 + 1 && sentPut.post === "Questions moved a day"
    && sentPut.doc.units.find((u) => u.id === "u3").opens === w.day(15), sentPut && sentPut.post);
  v = w.shown[w.shown.length - 1];
  check("planface: sent: nothing waits; Undo says the send", !v.plan.sending && /Sent to 2 following/.test(v.status) && v.head.undo.some((x) => /Undo your send of/.test(x.label)), [v.status, v.head.undo]);

  // -- the deck beside the plan: ticks, then Lay them out --
  const l = await face(0);
  await run(l, "deck", {});
  await run(l, "deck_tick", { key: `tag:${ROOTTAG}::#Path_Book::03_Neoplasia`, on: true });
  v = l.shown[l.shown.length - 1];
  check("planface: a tick is what the plan covers, laid out on a click", v.deck.fill && /ticked, not on a set/.test(v.deck.fill.head) && v.deck.fill.keep, v.deck.fill);
  const k0 = l.store.log.length;
  await run(l, "deck_lay", { how: v.deck.fill.go.how });
  check("planface: Lay them out puts sets on study days, and saves", l.store.log.length === k0 + 1
    && l.B.doc.units.some((u) => (u.tags || []).some((t) => /03_Neoplasia/.test(t))), l.B.note);
  await run(l, "deck", { uid: "u1" });
  await run(l, "deck_tick", { key: `deck:Big Step 1::Extras`, on: true });
  check("planface: a tick with a set picked adds to that set", l.B.doc.units.find((u) => u.id === "u1").decks.includes("Big Step 1::Extras"), l.B.doc.units.find((u) => u.id === "u1"));

  // -- Add to my calendar: the site's own calendar file of the plan (GET /plans/ics, at /p/CODE.ics) --
  await run(c, "calendar");
  check("planface: Add to my calendar: the plan's calendar file the site serves (/p/CODE.ics), nothing new on the server",
    c.site.went.includes("download:/p/PATH2026.ics") && /calendar/.test(c.f.F.status), [c.site.went, c.f.F.status]);

  // -- the deck's tags not here yet (Anki sends them): no counts, nothing to tick, the page still whole --
  const nt = await face(0, { noTree: true });
  const vn = await run(nt, "pick", { key: ["date", "u1"] });
  const dn = drawAll(nt, vn), vd = await run(nt, "deck", {}), dd = drawAll(nt, vd);
  check("planface: before Anki sends the deck's tags: names without counts, the panel says where they come from, the deck says why it's empty",
    vn.panel.sources.length && vn.panel.sources.every((x) => x.n === null) && /come from your Anki/.test(vn.panel.said) && vd.deck && vd.deck.none
    && !dn.errors.length && !dd.errors.length && (await run(nt, "tab", { tab: "insights" })).insights.none, [vn.panel.said, dn.errors[0], dd.errors[0]]);

  // -- nobody following: a new set waits for its cards, then saves with them --
  const e0 = await face(0);
  await run(e0, "new_date", { name: "Neoplasia", day: e0.day(22) });
  const ns0 = e0.store.log.length, mk = e0.B.doc.units.find((u) => u.name === "Neoplasia");
  check("planface: a set with no cards yet isn't saved (the builder's save would drop it): it waits for them",
    ns0 === 0 && mk && e0.shown[e0.shown.length - 1].plan.sending && /saved once it has cards/.test(e0.shown[e0.shown.length - 1].status), [ns0, e0.shown[e0.shown.length - 1].status]);
  await run(e0, "deck_tick", { key: `tag:${ROOTTAG}::#Path_Book::03_Neoplasia`, on: true });
  const put0 = e0.store.log[0];
  check("planface: …then its first cards save it, the two changes as one save", e0.store.log.length === 1
    && put0.doc.units.some((u) => u.name === "Neoplasia" && u.tags.includes(`${ROOTTAG}::#Path_Book::03_Neoplasia`)) && !e0.f.F.changes.length, e0.store.log.length);
  await run(e0, "deck_lay", { how: ["daily", false, null] });
  check("planface: Lay them out with nothing ticked changes nothing and says so", e0.store.log.length === 1 && !e0.f.F.changes.length, e0.f.F.status);

  // -- a new set, a quiz, a review day, a source moved --
  const s = await face(2);
  await run(s, "new_date", { name: "Neoplasia", day: s.day(21) });
  const made = s.B.doc.units.find((u) => u.name === "Neoplasia");
  v = s.shown[s.shown.length - 1];
  check("planface: A set…: on the plan, picked, the deck beside it adding to it", made && v.side === "deck" && v.deck.target === made.id, v.side);
  await run(s, "new_event", { name: "Heme quiz", day: s.day(12), for_uid: "u2" });
  check("planface: A quiz, exam or day…: on its day, a set leading up to it", s.B.events().some((e) => e.name === "Heme quiz") && s.B.doc.units.find((u) => u.id === "u2").for === s.B.events().find((e) => e.name === "Heme quiz").id);
  await run(s, "pick", { key: ["date", "u2"] });
  await run(s, "op", { op: { op: "move_source", date: "u2", key: ["search", `"tag:${ROOTTAG}::^Systems::Heme"`], to: "u3" } });
  check("planface: Move to: a search moves to another set", (s.B.doc.units.find((u) => u.id === "u3").search || []).length === 1 && !(s.B.doc.units.find((u) => u.id === "u2").search || []).length);
  await run(s, "paste", { text: `${s.day(22)} | Pasted | tag:${ROOTTAG}::^Systems::Cardio`, sure: true });
  check("planface: plan lines pasted go on as the builder's text does", s.B.doc.units.some((u) => u.name === "Pasted"), s.B.doc.units.map((u) => u.name));
  await run(s, "discard", { sure: true });
  check("planface: Discard: the plan as it was saved", !s.B.doc.units.some((u) => u.name === "Neoplasia") && !s.f.F.changes.length);

  // -- Settings: the name saves at once; the shape is a change --
  const t = await face(2, { tab: "settings" });
  await run(t, "tabcmd", { name: "meta", args: { name: "Path, all of it", line: "Path." } });
  check("planface: Settings' name and line: one PUT, nothing else of the plan's", t.store.log.length === 1 && t.store.log[0].name === "Path, all of it" && !t.store.log[0].doc, t.store.log);
  await run(t, "tabcmd", { name: "shape", args: { key: "day", value: 5 } });
  v = t.shown[t.shown.length - 1];
  check("planface: the shape's preview, then Add to the changes", v.settings.shape.preview && v.settings.shape.go === "Add to the changes", v.settings.shape);
  await run(t, "tabcmd", { name: "shape_save" });
  check("planface: the shape's change waits with the others", t.f.F.changes.length === 1 && t.B.pace.days[5] === 1, t.B.pace);

  // -- New plan: someone's plan, start empty --
  const ns = makeSite(makeStore(plans(() => "2030-01-01", 0)).fn);
  const nshown = [];
  const nf = ns.ctx.PlanFace.make(null, { plans: [], go: (u) => ns.went.push(u), out: { show: (x) => nshown.push(x), sheet() {}, status() {} }, newPlan: { decks: ["Big Step 1", "Other deck"], deck: "" } });
  nf.cmd(msg("ready"));
  check("planface: New plan: someone's plan and start empty; no resource on the site", nshown[0].new && nshown[0].new.step === "pick" && nshown[0].new.ways.join() === "someone", nshown[0].new);
  const nd = drawAll({ site: ns, day: () => "2030-01-06" }, nshown[0]);
  check("planface: New plan's page: no resource, no Today's set", !/A resource, at my pace/.test(nd.text) && /Someone's plan/.test(nd.text) && !nd.errors.length, [nd.text.slice(0, 200), nd.errors[0]]);
  nf.cmd(msg("new_step", { step: "empty" }));
  nf.cmd(msg("new_set", { key: "name", value: "Block 2" }));
  nf.cmd(msg("new_set", { key: "end_name", value: "Block 2 exam" }));
  const ne = drawAll({ site: ns, day: () => "2030-01-06" }, nshown[nshown.length - 1]);
  check("planface: Start empty: a name, the deck, the exam it ends with; no Today's set", /Start empty/.test(ne.text) && !/Today's (set|lesson)/.test(ne.text) && !ne.errors.length, ne.errors[0]);
  nf.cmd(msg("new_make", { start: false }));
  for (let i = 0; i < 8; i++) await settle();
  check("planface: Make it: POST /plans, its exam, then its page", ns.went.includes("/plans/newplanxxxxxxxxx/edit"), ns.went);
  nf.cmd(msg("new_follow", { code: "ab12 cd34" }));
  check("planface: Someone's plan: its code's page", ns.went.includes("/p/AB12CD34"), ns.went);

  process.stdout.write(JSON.stringify({ checks }));
  process.exit(checks.every((x) => x[1]) ? 0 : 1);
})().catch((e) => { process.stdout.write(JSON.stringify({ checks, crash: e.stack })); process.exit(1); });
