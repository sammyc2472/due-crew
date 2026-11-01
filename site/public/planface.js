// Your plans on duecrew.com: the add-on's own plan page (planpage/plan.js,
// tabs.js, new.js: due_crew/planner/page, copied by tools/gen_plan_page.py),
// drawn from builder.js's plan. This is its face, as webface.py is Anki's:
// the view it draws (JSON, the same shape webface.view() makes) and what
// each click does ("dcplan:" + JSON, the page's c names). builder.js keeps
// the plan, its working copy and its logic (builder(id, face)); app.js's
// helpers (api, go, the dates, Sched) are its. Every name is set as text
// by the page, never as markup.
//
// What only Anki can do is left out: Browse, Study, opening cards, a
// search's own count, Your AI app, Today's set. A source's count is the
// deck tree's (the author's Anki sends it, PUT /plans/trees). A change waits
// under the plan when anyone follows it (Review and send: one save, with a
// line to followers), as the builder's Save did; with nobody following it
// saves at once, and Undo takes it back (POST /plans/{id}/undo).
"use strict";

const PlanFace = (() => {
  const PREFIX = "dcplan:";
  const WITHOUT = ["browse"];  // the page's S.without: what only Anki does (Study and Your AI app aren't in this view at all)
  const VIEWS = [["resource", "By resource"], ["system", "By system"], ["other", "Other"], ["deck", "Subdecks"], ["plan", "The plan's own tags"]];
  const MODES = [["daily", "Up to"], ["end", "Fit to the end"], ["placed", "I set each set"]];
  const CATCHUP = [[0, "None"], [3, "Every 3rd week"], [4, "Every 4th week"]];
  const WEEK = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const LONG = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
  const WHY_MAX = 200;
  const FOUND_MAX = 200;

  // ---- words ----
  const pl = (n, one, many) => `${Number(n).toLocaleString()} ${n === 1 ? one : many || `${one}s`}`;
  const wd = (s) => (parseIso(s).getUTCDay() + 6) % 7;
  /** "Mon 9" (the week's line says the month): model.day_words */
  const dw = (s) => { if (!/^\d{4}-\d\d-\d\d$/.test(String(s || ""))) return String(s || ""); const d = parseIso(s); return `${WEEK[wd(s)]} ${d.getUTCDate()}`; };
  /** "Mon 9 Nov": plans.fmt_day */
  const fmt = (s) => (/^\d{4}-\d\d-\d\d$/.test(String(s || "")) ? pretty(s) : String(s || ""));
  const M3 = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  /** "9–13 Nov", "30 Nov–4 Dec", "Mon 9 Nov" for one day: model.span_words */
  function spanWords(a, b) {
    if (a === b) return fmt(a);
    const x = parseIso(a), y = parseIso(b);
    if (x.getUTCFullYear() === y.getUTCFullYear() && x.getUTCMonth() === y.getUTCMonth()) return `${x.getUTCDate()}–${y.getUTCDate()} ${M3[y.getUTCMonth()]}`;
    return `${x.getUTCDate()} ${M3[x.getUTCMonth()]}–${y.getUTCDate()} ${M3[y.getUTCMonth()]}`;
  }
  const monday = (s) => Sched.monday(s);
  const nth = (n) => `${n}${n === 1 ? "st" : n === 2 ? "nd" : n === 3 ? "rd" : "th"}`;
  const norm = (s) => String(s || "").split(/\s+/).join(" ").trim();
  /** "Mon–Fri", "Mon, Wed, Fri", "every day": view.days_words */
  function daysWords(days) {
    const on = [0, 1, 2, 3, 4, 5, 6].filter((i) => (days || [1, 1, 1, 1, 1, 1, 1])[i]);
    if (on.length === 7) return "every day";
    if (on.length > 2 && on.every((x, i) => x === on[0] + i)) return `${WEEK[on[0]]}–${WEEK[on[on.length - 1]]}`;
    return on.map((i) => WEEK[i]).join(", ") || "no days";
  }
  /** a tag as the window names it: [group, topic] (model.split); "Path Book", "01 · Cell injury › Adaptations" */
  function split(path) {
    const segs = String(path).split("::");
    const ri = segs.findIndex((x, i) => i > 0 && /^[#^]/.test(x));
    if (ri >= 0) return [Tags.word(segs[ri]), segs.slice(ri + 1).map(Tags.word).join(" › ")];
    const rest = segs.length > 1 && /^[#^]/.test(segs[0]) ? segs.slice(1) : segs;
    return ["", rest.map(Tags.word).join(" › ")];
  }
  /** one line for a deck tag: "Path Book › 01 · Cell injury" (model.label) */
  const tagLabel = (path) => split(path).filter(Boolean).join(" › ") || String(path);
  const isQuestion = (path) => /^\s*\d+\s*$/.test(String(path).split("::").pop());
  const bankOf = (path) => { const segs = String(path).split("::"); const ri = segs.findIndex((x, i) => i > 0 && /^[#^]/.test(x)); return Tags.word(ri >= 0 && ri < segs.length - 1 ? segs[ri] : segs[0]); };
  /** a row's name: "Group › Name", or the name (webmodel.chip_name) */
  const chipName = (g, n, kind) => (["search", "picks", "plan", "deck", "cut"].includes(kind) || !g || n.toLowerCase().includes(g.toLowerCase()) ? n : `${g} › ${n}`);
  const canon = (v) => (Array.isArray(v) ? v.map(canon) : v && typeof v === "object"
    ? Object.fromEntries(Object.keys(v).sort().filter((k) => v[k] !== undefined && k !== "n").map((k) => [k, canon(v[k])])) : v);
  const sameUnit = (a, b) => JSON.stringify(canon(a)) === JSON.stringify(canon(b));
  const ago = (t) => { const m = Math.round((Date.now() / 1000 - t) / 60); return m < 1 ? "just now" : m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : fmt(iso(new Date(t * 1000))); };
  const isAuthor = (p) => p && (p.role === "owner" || p.role === "editor");
  /** who besides me follows it: an author studying their own plan isn't someone its changes wait for (core.others) */
  const others = (p) => Math.max(0, Number(p?.followers || 0) - (p?.following ? 1 : 0));
  function pickLabel(p) {
    const who = p.ownerName && p.ownerName !== "?" ? p.ownerName : null;
    const whose = isAuthor(p) ? (p.role === "owner" ? "yours" : who ? `with ${who}` : "a co-author") : who ? `${who}’s · following` : "following";
    const bits = [p.name || "Plan", whose];
    if (isAuthor(p)) { const n = others(p); bits.push(n ? `${n.toLocaleString()} following` : "nobody following yet"); }
    return bits.join(" · ");
  }
  const sortPlans = (ps) => (ps || []).filter((p) => p && p.id).sort((a, b) => (isAuthor(a) ? 0 : 1) - (isAuthor(b) ? 0 : 1)
    || String(a.name || "").toLowerCase().localeCompare(String(b.name || "").toLowerCase()));

  /** Add to my calendar (due_crew/planner/ics.py: change one, change both; the suite checks): a plan's
   *  sets and its quizzes and exams as a calendar file (.ics, RFC 5545). Each set an all-day event on its
   *  days, each quiz or exam one, each review day one. A follower's has their own days, skipped sets left out. */
  const Ics = (() => {
    const PRODID = "-//Due Crew//Plans//EN";
    const esc = (t) => String(t ?? "").replace(/\\/g, "\\\\").replace(/;/g, "\\;").replace(/,/g, "\\,").replace(/\r\n|\n|\r/g, "\\n");
    /** lines over 75 octets folded (a CRLF and a space), never inside a character */
    function fold(line) {
      const out = []; let cur = "", n = 0;
      for (const ch of line) {
        const c = ch.codePointAt(0), k = c < 0x80 ? 1 : c < 0x800 ? 2 : c < 0x10000 ? 3 : 4;  // its UTF-8 octets
        if (n + k > (out.length ? 74 : 75)) { out.push(cur); cur = ""; n = 0; }
        cur += ch; n += k;
      }
      out.push(cur);
      return out.join("\r\n ");
    }
    const ok = (s) => /^\d{4}-\d\d-\d\d$/.test(String(s || "")) && !Number.isNaN(Date.parse(`${s}T00:00:00Z`));
    const ymd = (s) => String(s).replace(/-/g, "");
    function event(uid, stamp, first, last, summary, desc) {
      const lines = ["BEGIN:VEVENT", `UID:${uid}`, `DTSTAMP:${stamp}`, `DTSTART;VALUE=DATE:${ymd(first)}`, `DTEND;VALUE=DATE:${ymd(addDays(last, 1))}`,
        `SUMMARY:${esc(summary)}`, "TRANSP:TRANSPARENT"];
      if (desc) lines.push(`DESCRIPTION:${esc(desc)}`);
      lines.push("END:VEVENT");
      return lines;
    }
    function calendar(pid, name, doc, counts = {}, skipped = [], now = new Date()) {
      const stamp = now.toISOString().replace(/[-:]/g, "").replace(/\.\d+Z$/, "Z");
      const plan = String(name || "Plan").split(/\s+/).filter(Boolean).join(" ");
      let lines = ["BEGIN:VCALENDAR", "VERSION:2.0", `PRODID:${PRODID}`, "CALSCALE:GREGORIAN", "METHOD:PUBLISH", `X-WR-CALNAME:${esc(plan)}`];
      const skip = new Set(skipped || []);
      for (const u of (doc || {}).units || []) {
        if (!u || typeof u !== "object" || skip.has(u.id) || !ok(u.opens)) continue;
        let last = u.due && ok(u.due) ? u.due : u.opens;
        if (last < u.opens) last = u.opens;
        const n = (counts || {})[u.id];
        lines = lines.concat(event(`${pid}-${u.id}@duecrew.com`, stamp, u.opens, last, `${u.name || "Set"} · ${plan}`,
          `${plan}${n ? ` · ${Number(n).toLocaleString("en-US")} card${Number(n) !== 1 ? "s" : ""}` : ""}`));
      }
      for (const e of (doc || {}).events || []) if (e && ok(e.day)) lines = lines.concat(event(`${pid}-${e.id}@duecrew.com`, stamp, e.day, e.day, `${e.name || "Exam"} · ${plan}`, plan));
      for (const r of (doc || {}).reviews || []) if (r && ok(r.day)) lines = lines.concat(event(`${pid}-r${ymd(r.day)}@duecrew.com`, stamp, r.day, r.day, `Review day · ${plan}`, plan));
      lines.push("END:VCALENDAR");
      return `${lines.map(fold).join("\r\n")}\r\n`;
    }
    /** a file name for it: the plan's name, safe on every system */
    const fileName = (name) => `${String(name || "Plan").replace(/[^\p{L}\p{N} \-_.]/gu, " ").split(/\s+/).filter(Boolean).join(" ").slice(0, 60) || "Plan"}.ics`;
    return { calendar, fileName };
  })();

  // ---- the face: one plan's page ----

  /** B: builder.js's plan (builder(id, face)'s attach), or null for New plan
   *  alone. o: {plans, tab, out: {show, sheet, status, openUndo, pasted}, go, copy, newPlan}. */
  function make(B, o = {}) {
    const F = {
      B, plans: sortPlans(o.plans || (B ? [B.plan] : [])), tab: ["insights", "settings"].includes(o.tab) ? o.tab : "plan",
      picked: null, side: "panel", status: "", busy: false,
      changes: [], hold: false, undoable: null, sent: null,
      deck: { target: null, view: "resource", find: "", opened: new Set(), dirty: false },
      shape: {}, posts: [], crew: null, newSt: null, ready: false,
    };
    const out = o.out || {};
    const today0 = () => today();
    const goTo = o.go || ((p) => go(p));
    const copyText = o.copy || ((t) => navigator.clipboard.writeText(t));

    // ---- the plan, as builder.js keeps it ----
    const doc = () => B.doc;
    const plan = () => B.plan;
    const units = () => (B ? B.doc.units || [] : []);
    const unit = (uid) => units().find((u) => u.id === uid) || null;
    const eventOf = (eid) => B.events().find((e) => e.id === eid) || null;
    const reviewOf = (day) => (B.doc.reviews || []).find((r) => r.day === day) || null;
    const author = () => !!B && B.author;
    const owner = () => !!B && B.owner;
    const tree = () => !!B && B.count.size > 0;
    const pickedUnit = () => (F.picked && F.picked[0] === "date" ? unit(F.picked[1]) : null);
    const byOpens = () => units().slice().sort((a, b) => String(a.opens).localeCompare(String(b.opens)) || String(a.name || "").localeCompare(String(b.name || "")));
    /** what's changed since the plan as saved (the not-sent marks): a date's ids */
    const fresh = () => {
      if (!B || !F.changes.length) return new Set();
      const was = new Map((B.base.units || []).map((u) => [u.id, u]));
      return new Set(units().filter((u) => !was.has(u.id) || !sameUnit(was.get(u.id), u)).map((u) => u.id));
    };
    /** changes wait under the plan: someone follows it, or a save of them didn't go (core.waiting) */
    const waiting = () => author() && (others(plan()) > 0 || F.hold);
    const planStart = () => B.start || Sched.start(B.doc) || nextMonday();
    const paceOf = () => B.pace;
    /** the quiz or exam the plan ends with, and its day (view.ends_with) */
    const endsWith = () => { const end = B.doc.end || ""; return [end ? B.events().find((e) => e.day === end) || null : null, end]; };
    /** new cards a day the plan asks at most; 0: each set placed by hand (view.cap_of) */
    const capOf = () => { const p = paceOf(); return p.mode === "placed" ? 0 : p.mode === "end" ? (B.endDaily() || p.daily || 0) : p.daily || 0; };
    const lastEvent = () => B.events().slice().sort((a, b) => a.day.localeCompare(b.day)).pop() || null;
    const prep = (e) => B.prepOf(e.id);

    // ---- a follower's: my follow, my progress (what my Anki syncs), the plan on my days ----
    const follower = () => !!B && !B.author && !!(B.plan && B.plan.following);
    const follow = () => (B && B.plan && B.plan.following) || {};
    /** [opened, seen, total] a set, as my Anki last synced it (POST /sync's plans) */
    const progOf = (u) => { const p = (follow().progress || {})[u.id]; return Array.isArray(p) && p[2] > 0 ? p : null; };
    /** a set's cards: my Anki's count, else the plan's (plans.unit_total; the tree's for an author) */
    const totalOf = (u, placed) => { const p = !author() && progOf(u); return p ? p[2] : B.unitTotal(u, placed); };
    /** the work each day asks (Work.map): the deck tree's counts for an author, my Anki's for me */
    const workMap = () => (author() ? (tree() ? B.workMap() : new Map()) : Work.map(B.doc, (u) => totalOf(u), (paceOf().days || [1, 1, 1, 1, 1, 1, 1])));
    /** the plan as I run it: my shift, my skips left out, a set I moved (plans.my_doc) */
    function myDoc(d, f) {
      const skipped = new Set(f.skipped || []), shift = Number(f.shift || 0);
      const moved = Object.fromEntries(Object.entries(f.moved || {}).filter(([, v]) => Number.isInteger(v) && v > 0));
      if (!shift && !skipped.size && !Object.keys(moved).length) return d;
      const out2 = { ...d, units: (d.units || []).filter((u) => !skipped.has(u.id)).map((u) => {
        const v = { ...u }, by = shift + (moved[u.id] || 0);
        if (by) for (const k of ["opens", "due", "check"]) if (v[k]) v[k] = addDays(v[k], by);
        if (moved[u.id]) v._moved = moved[u.id];
        return v;
      }) };
      if (shift) {
        if (out2.end) out2.end = addDays(out2.end, shift);
        if (out2.reviews) out2.reviews = out2.reviews.map((r) => ({ ...r, day: addDays(r.day, shift) }));
      }
      return out2;
    }
    /** my days in the builder's working copy (a follower's is never saved: builder.js saves only an author's) */
    const runMine = () => { if (follower()) B.reload(myDoc(B.plan.doc, follow())); };

    // ---- showing ----
    function push() { if (F.ready && out.show) out.show(view()); }
    function say(t) { F.status = String(t || ""); if (F.ready && out.status) out.status({ status: F.status }); }
    function sheet(sh) { if (out.sheet) out.sheet(sh); }
    function ask(title, words, yes, cmd, args, danger) { sheet({ title, words, yes, danger: !!danger, cmd, args: { ...(args || {}), sure: true } }); }
    async function copy(text, said) {
      try { await copyText(text); say(said); } catch { sheet({ kind: "read", title: "Copy it from here", text, yes: null, no: "Close" }); }
    }

    // ---- a change: the builder's edits, then its Undo step ----
    const sig = () => JSON.stringify([B.doc, B.pace, [...B.cover], B.start, B.meta]);
    /** fn edits the working copy (builder.js's edits); a change made is
     *  an Undo step and, with nobody following, a save */
    function change(fn, words, key) {
      if (!author() || F.busy) return false;
      const was = sig(), docWas = JSON.stringify(B.doc), paceWas = JSON.stringify(B.pace);
      B.note = "";
      const r = fn();
      if (r === false) {  // refused: the working copy as it was (an edit can stop halfway)
        const d = JSON.parse(docWas);
        for (const k of Object.keys(B.doc)) delete B.doc[k];
        Object.assign(B.doc, d);
        B.pace = JSON.parse(paceWas);
      }
      if (r === false || sig() === was) {
        if (B.note) say(B.note);
        push();
        return false;
      }
      B.mark();
      const said = B.note;
      const w = typeof words === "function" ? words() : words;
      F.changes.push({ verb: w[0], what: w[1], detail: w[2] || "", key: key || null });
      if (said) say(said);
      after();
      return true;
    }
    /** a change in: saved now when nobody follows (a set with no cards yet waits for them) */
    function after() {
      if (waiting()) { push(); return; }
      if (units().some((u) => !(B.srcs(u).length || (u.cards || []).length || (u.search || []).length || (u.cut || []).length || B.hasIds(u)))) {
        say("A set is saved once it has cards: add some from the deck.");
        push();
        return;
      }
      saveNow(false);
    }
    async function saveNow(sending, why = "") {
      if (F.busy || !author()) return;
      const v0 = plan().version, n = F.changes.length;
      F.busy = true;
      say(sending ? "Sending…" : "Saving…");
      push();
      B.tell.value = sending ? norm(why).slice(0, WHY_MAX) : "";
      try { await B.save(); } catch { /* the builder said why */ }
      F.busy = false;
      const said = B.status.textContent;
      if (!B.dirty && plan().version !== v0) {
        F.changes = []; F.hold = false; F.undoable = plan().version;
        F.sent = sending && others(plan()) ? [new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }), n] : null;
        say(/didn't go|kept/.test(said) ? said : sending && others(plan())
          ? `Sent to ${others(plan()).toLocaleString()} following. They get it at their next refresh.` : "Saved.");
        relabel();
      } else {
        F.hold = F.changes.length > 0;
        say(said && said !== "Saving…" ? said : "That didn't save. Try again.");
      }
      push();
    }
    function relabel() {
      const p = plan();
      F.plans = F.plans.map((x) => (x.id === p.id ? { ...x, name: p.name, followers: p.followers, role: p.role, following: p.following } : x));
    }
    /** a settings request's answer: the plan as it is now, the working copy kept */
    function took(r, said) {
      if (!r || !r.id) return;
      B.plan = { ...plan(), ...r };
      B.meta = { name: r.name ?? B.meta.name, line: r.line ?? B.meta.line, audience: r.audience ?? B.meta.audience, squad: r.squad ?? "" };
      if (!F.changes.length && r.doc) B.reload(r.doc);
      relabel();
      if (said) say(said);
      push();
    }
    function failed(err, words) {
      const code = err && err.body && err.body.error;
      say(words && words[code] ? words[code] : err && err.status === 429 ? "That's a lot today. Try again later."
        : err && !err.status ? "That didn't work: check your connection, then try again." : "That didn't work. Try again.");
      push();
    }

    // ---- the head ----
    function undoEntries() {
      const es = [];
      if (!author()) return es;
      if (F.changes.length) {
        const c = F.changes[F.changes.length - 1];
        es.push({ label: `Take back the last change, not sent (${c.what} ${String(c.verb).toLowerCase()})`, what: ["take", F.changes.length - 1], on: B.undos > 0 && !F.busy });
      }
      if (F.undoable) {
        es.push({ label: F.sent ? `Undo your send of ${F.sent[0]} (${pl(F.sent[1], "change")})` : "Undo your last save", what: ["undo"], on: !F.busy });
      }
      if (!es.length) es.push({ label: "Nothing of yours to undo here", what: null, on: false });
      es.push({ label: "History: every save…", what: ["history"], on: true });
      return es;
    }
    function head() {
      const p = B ? plan() : null;
      return {
        plans: B ? F.plans.map((x) => ({ id: x.id, label: pickLabel(x) })) : [],  // New plan alone: the site's Plans has them
        pid: p ? p.id : null, author: author(), loaded: !!B, owner: owner(), name: p ? p.name : "",
        followers: p ? others(p) : 0, busy: F.busy, undo: undoEntries(),
      };
    }

    // ---- a set's sources: one row each (model.sources, as the site counts them) ----
    function rows(u) {
      const placed = B.placedKeys(), t = tree();
      const own = new Map(B.ptags().map((x) => [B.ptagPath(x).toLowerCase(), x]));
      const cnt = (k) => (t && !B.uncounted(k) ? B.eff(k, placed) : null);
      const out = [], banks = new Map();
      for (const p of u.tags || []) {
        const k = `tag:${p}`, pt = own.get(p.toLowerCase());
        if (pt) { out.push({ key: ["tag", p], kind: "plan", group: "This plan’s tags", name: pt.name, n: cnt(k), raw: p }); continue; }
        if (isQuestion(p)) {
          const b = banks.get(bankOf(p)) || { tags: [], n: 0 };
          b.tags.push(p); b.n += cnt(k) || 0; banks.set(bankOf(p), b);
          continue;
        }
        const [g, topic] = split(p), kind = Tags.kind(p);
        out.push({ key: ["tag", p], kind, group: g || (kind === "other" ? "Other tags" : "?"), name: topic || "all of it", n: cnt(k), raw: p });
      }
      for (const c of u.cut || []) {
        const pt = B.ptags().find((x) => x.id === c.in);
        if (!pt) continue;
        out.push({ key: ["cut", c.tag, c.in], kind: "cut", group: "", name: B.cutName(c), n: u.sn?.[c.q] ?? null, raw: c.tag });
      }
      for (const [name, b] of banks) {
        out.push({ key: ["questions", b.tags], kind: "question", group: name, name: `${name} · ${pl(b.tags.length, "question")}`,
          n: t ? b.n : null, raw: `${b.tags.slice(0, 3).join(" ")}${b.tags.length > 3 ? " …" : ""}` });
      }
      for (const d of u.decks || []) {
        const segs = d.split("::");
        out.push({ key: ["deck", d], kind: "deck", group: "Subdecks", name: (segs.slice(1).length ? segs.slice(1) : segs).map(Tags.word).join(" › "), n: cnt(`deck:${d}`), raw: d });
      }
      for (const q of u.search || []) {
        if (B.cutOf(u, q)) continue;
        out.push({ key: ["search", q], kind: "search", group: "Searches", name: B.searchName(q), n: u.sn?.[q] ?? null, raw: q });
      }
      if ((u.cards || []).length || B.hasIds(u)) {
        out.push({ key: ["picks"], kind: "picks", group: "Picked cards", name: B.picksText(u), n: B.hasIds(u) && u.idn == null ? null : B.picksN(u), raw: B.picksList(u) || "" });
      }
      if (!author()) for (const r of out) r.n = null;  // a follower's counts are their own Anki's (the set's, from what it syncs)
      const ORDER = ["plan", "resource", "system", "other", "cut", "question", "deck", "search", "picks"];
      const first = new Map();
      out.forEach((r, i) => { const k = `${ORDER.indexOf(r.kind)}|${r.group}`; if (!first.has(k)) first.set(k, i); });
      return out.sort((a, b) => ORDER.indexOf(a.kind) - ORDER.indexOf(b.kind)
        || first.get(`${ORDER.indexOf(a.kind)}|${a.group}`) - first.get(`${ORDER.indexOf(b.kind)}|${b.group}`));
    }
    const rowName = (r) => chipName(r.group, r.name, r.kind);
    /** the cards a set holds, as the deck tree counts them (null: not counted here) */
    const total = (u, placed = B.placedKeys()) => (tree() ? B.unitTotal(u, placed) : null);

    // ---- the Plan tab ----
    /** {Monday: {new, reviews, top, over, cap, new_week, reviews_week}} (view.week_asks) */
    function weekAsks() {
      const work = workMap();
      if (!work.size) return {};
      const per = new Map([...work].map(([d, e]) => [d, e.n]));
      const rv = new Map();
      for (const [d, n] of per) for (let k = 1; k < Reviews.CURVE.length; k++) { const x = addDays(d, k); rv.set(x, (rv.get(x) || 0) + n * Reviews.CURVE[k]); }
      const cap = capOf(), days = paceOf().days || [1, 1, 1, 1, 1, 1, 1];
      const study = days.filter(Boolean).length || 7;
      const out = {};
      for (const mon of [...new Set([...per.keys(), ...rv.keys()].map(monday))].sort()) {
        let nw = 0, top = 0, rw = 0;
        for (let i = 0; i < 7; i++) { const x = addDays(mon, i); nw += per.get(x) || 0; top = Math.max(top, per.get(x) || 0); rw += rv.get(x) || 0; }
        out[mon] = { new: nw ? Math.ceil(nw / study) : 0, reviews: rw / 7, new_week: nw, reviews_week: rw, top, over: !!cap && top > cap * 1.25, cap };
      }
      return out;
    }
    /** "9 new, 34 reviews a day", or the amber "41 new a day (over your 20), 52 reviews" (view.week_words) */
    function weekWords(a) {
      if (!a) return ["", false];
      const r = Reviews.about(a.reviews);
      if (a.over) return [`${a.top.toLocaleString()} new a day (over your ${a.cap.toLocaleString()}), ${r} reviews`, true];
      if (!a.new && r === "0") return ["", false];
      return [`${a.new.toLocaleString()} new, ${r} reviews a day`, false];
    }
    /** the sets that need a look: no cards here, or a week over the pace (view.needs_look) */
    function needsLook(asks) {
      const out = new Map();
      if (!tree()) return out;
      const placed = B.placedKeys();
      for (const u of units()) {
        const counted = !B.srcs(u).some((k) => B.uncounted(k)) && !(u.search || []).length && !(u.cut || []).length && !B.hasIds(u);
        if (counted && !B.unitTotal(u, placed)) out.set(u.id, "no cards here yet");
        else if ((asks[monday(u.opens)] || {}).over) out.set(u.id, "its week asks too much");
      }
      return out;
    }
    /** a week over the pace, and what fixes it (build.heavy, as the builder's heavyNote) */
    function heavy() {
      const cap = capOf();
      if (!cap || !tree()) return null;
      const work = B.workMap();
      const runs = Work.over(work, cap);
      const run = runs.find((r) => r.b >= today0()) || runs[0];
      if (!run) return null;
      const by = work.get(run.a).by.slice().sort((x, y) => y[1] - x[1]);
      const u = by[0][0], tot = B.unitTotal(u), last = Sched.win(B.doc, u, 0)[1];
      const big = u.even ? null : B.srcs(u).filter((k) => !B.uncounted(k) && B.eff(k) > 0).sort((x, y) => B.eff(y) - B.eff(x))[0];
      const need = Math.ceil(tot / cap);
      let till = u.opens, k = B.isStudy(u.opens) ? 1 : 0;
      while (k < need && till < addDays(u.opens, 366)) { till = addDays(till, 1); if (B.isStudy(till)) k++; }
      const when = run.a === run.b ? dw(run.a) : `${dw(run.a)} – ${dw(run.b)}`;
      return { week: monday(run.a), uid: u.id,
        words: `${when}: ${run.top.toLocaleString()} new a day, your pace is ${cap.toLocaleString()}. ${u.name || B.autoName(u)} is ${tot.toLocaleString()} cards by ${dw(last)}.`,
        spread: big ? { label: `Spread ${B.chipLabel(big)}…`, kind: B.kindOf(big), path: B.pathOf(big) } : null,
        till: till > last ? { label: `Let it finish by ${fmt(till)}`, due: till } : null };
    }
    function taper() {
      const n = Number((B.doc.phases || {}).taper || 0), end = B.doc.end;
      return n && end ? [addDays(end, -n), addDays(end, -1)] : null;
    }
    /** the plan's shape, label by label (view.shape_line) */
    function shapeLine(asks) {
      const parts = [], start = Sched.start(B.doc), [ev, end] = endsWith(), p = paceOf();
      if (start || end) {
        const last = B.lastDay();
        parts.push(["Dates", `${start ? fmt(start) : "Not started"} – ${ev ? `${ev.name || "the exam"}, ${fmt(end)}` : end ? fmt(end) : last ? `${fmt(last)}, no end set` : "no end set"}`]);
      }
      parts.push(["Study days", daysWords(p.days)]);
      const cap = capOf();
      if (p.mode !== "placed" && cap) parts.push(["New a day", `${cap.toLocaleString()}${p.mode === "end" ? ", to fit the end" : ""}`]);
      let best = null;
      Object.keys(asks).sort().forEach((m, i) => { if (!best || asks[m].reviews > best[1]) best = [i + 1, asks[m].reviews]; });
      if (best && best[1] >= 5) parts.push(["Reviews peak", `~${Reviews.about(best[1])} a day, week ${best[0]}`]);
      const ph = B.doc.phases || {};
      if (ph.taper) parts.push(["Last days", `${ph.taper} with no new cards`]);
      if (ph.catchup) parts.push(["Catch-up", `every ${nth(ph.catchup)} week`]);
      return parts;
    }
    function sending() {
      if (!author() || !F.changes.length) return null;
      const items = F.changes.slice(0, 3).map((c) => {
        const words = `${c.what.split(" · ").slice(1).join(" · ") || c.what} ${String(c.verb || "changed").toLowerCase()}`;
        const k = c.key && ((c.key[0] === "date" && unit(c.key[1])) || (c.key[0] === "event" && eventOf(c.key[1]))) ? c.key : null;
        return { words, key: k };
      });
      return { n: F.changes.length, items, more: F.changes.length - items.length };
    }
    function dateItem(u, fr, look, placed, t0) {
      const n = author() ? total(u, placed) : null;
      const it = { kind: "date", key: ["date", u.id], day: u.opens, dayw: dw(u.opens), name: String(u.name || "?"), notSent: fr.has(u.id),
        past: String(u.due || u.opens) < t0, right: n !== null ? n.toLocaleString() : "", tone: "n" };
      if (u.due && u.due !== u.opens) it.span = `${dw(u.opens)} – ${dw(u.due)}`;
      if (!author()) {  // mine: opens, what's left of it, behind (webmodel._date_item, from what my Anki synced)
        const due = String(u.due || u.opens), p = progOf(u), left = p ? Math.max(0, p[2] - p[1]) : 0;
        if (u.opens > t0) it.right = `opens ${dw(u.opens)}`;
        else if (p) {
          it.right = !left ? "all seen" : `${left.toLocaleString()} left${due >= t0 ? "" : ", behind"}`;
          it.tone = due >= t0 || !left ? "n" : "warn";
          it.state = !left ? "done" : due < t0 ? "late" : u.opens <= t0 ? "now" : "ahead";
        }
      }
      it.state = it.state || (u.opens <= t0 && t0 <= (u.due || u.opens) ? "now" : String(u.due || u.opens) < t0 ? "past" : "ahead");
      const rs = rows(u);
      const bits = rs.slice(0, 6).map((r) => rowName(r) + (r.n !== null && r.n !== undefined ? ` (${r.n.toLocaleString()})` : ""));
      if (rs.length > 6) bits.push(`and ${(rs.length - 6).toLocaleString()} more`);
      if (bits.length) { it.under = bits.join(", "); it.underTone = "muted"; } else if (look.has(u.id)) { it.under = "No cards yet"; it.underTone = "warn"; }
      it.hay = [it.name, ...rs.map(rowName), ...(u.tags || []), ...(u.decks || [])].join(" ").toLowerCase();
      return it;
    }
    function eventItem(e) {
      const us = prep(e);
      let words;
      if (us.length) {
        const a = us.map((u) => u.opens).sort()[0], b = us.map((u) => u.due || u.opens).sort().pop();
        words = a !== b ? `tests ${dw(a)} – ${dw(b)}` : `tests ${dw(a)}`;
      } else words = e === lastEvent() ? "tests everything" : "tests no set yet";
      const it = { kind: "event", key: ["event", e.id], day: e.day, dayw: dw(e.day), name: String(e.name || "?"), right: words, tone: "n", hay: String(e.name || "").toLowerCase() };
      const [cards, seen, has] = mine(us);
      if (us.length && !author() && has) { it.under = `${pl(cards, "card")}, ${seen.toLocaleString()} seen`; it.underTone = "muted"; }
      return it;
    }
    /** [cards, seen, opened, any counted] of these sets, as my Anki synced them */
    function mine(us) {
      let cards = 0, seen = 0, opened = 0, has = false;
      for (const u of us) { const p = progOf(u); if (p) { has = true; cards += p[2]; seen += Math.min(p[1], p[2]); opened += Math.min(p[0], p[2]); } }
      return [cards, seen, has, opened];
    }
    /** a follower's today and behind (webmodel.strips), from my days and my progress; nothing to study here */
    function strips() {
      const o = { now: null, behind: null };
      if (author()) return o;
      const t0 = today0(), us = byOpens();
      const now = us.filter((u) => u.opens <= t0 && t0 <= (u.due || u.opens)).pop(), next = us.find((u) => u.opens > t0);
      const u = now || next;
      if (u) {
        const name = String(u.name || "?"), p = progOf(u);
        o.now = now ? { head: "Today", words: p ? `${name}, ${Math.max(0, p[2] - p[1]).toLocaleString()} new of ${p[2].toLocaleString()}` : name, uid: u.id, study: false }
          : { head: "Next", words: `${fmt(u.opens)}, ${name}`, uid: u.id, study: false };
      }
      const behind = us.filter((x) => String(x.due || x.opens) < t0).map((x) => [x, progOf(x)]).filter(([, p]) => p && p[2] > p[1]).map(([x, p]) => [x, p[2] - p[1]]);
      if (behind.length) {
        const left = behind.reduce((a, [, n]) => a + n, 0);
        const names = behind.slice(0, 2).map(([x]) => `${dw(x.opens)} ${x.name || "?"}`).join(", ");
        o.behind = { words: `${names}${behind.length > 2 ? `, and ${(behind.length - 2).toLocaleString()} more` : ""}: ${pl(left, "card")} not seen yet. Your Anki has them.`,
          button: "", uids: behind.map(([x]) => x.id) };
      }
      return o;
    }
    /** what my sets hold: seen, open and not seen, still shut (webmodel.cover, from my progress) */
    function coverMine() {
      if (author()) return null;
      const [cards, seen, has, opened] = mine(units());
      if (!has || !cards) return null;
      const open = Math.max(0, opened - seen);
      return { cards, seen, open, shut: Math.max(0, cards - seen - open), outside: 0 };
    }
    function reviewUnits(r) {
      const a = unit(r.from), b = unit(r.to);
      if (!a || !b) return [];
      const [lo, hi] = [a.opens, b.opens].sort();
      return byOpens().filter((u) => lo <= u.opens && u.opens <= hi);
    }
    function planTab() {
      const t0 = today0(), asks = weekAsks(), look = needsLook(asks), hv = heavy(), fr = fresh(), tp = taper(), placed = B.placedKeys();
      const by = new Map();
      for (const u of byOpens()) { const m = monday(u.opens); if (!by.has(m)) by.set(m, { dates: [], events: [] }); by.get(m).dates.push(u); }
      for (const e of B.events().slice().sort((a, b) => a.day.localeCompare(b.day))) { const m = monday(e.day); if (!by.has(m)) by.set(m, { dates: [], events: [] }); by.get(m).events.push(e); }
      const mons = [...by.keys()].sort(), first = mons[0];
      const weeks = mons.map((mon) => {
        const w = by.get(mon), end = addDays(mon, 6);
        const on = [...w.dates.map((u) => u.opens), ...w.events.map((e) => e.day)].sort();
        const n = Math.round(Sched.diff(mon, first) / 7) + 1;
        const now = monday(t0) === mon;
        const items = [...w.dates.map((u) => dateItem(u, fr, look, placed, t0)), ...w.events.map(eventItem)];
        for (const r of B.doc.reviews || []) {
          if (mon <= r.day && r.day <= end) {
            const us = reviewUnits(r);
            const sp = us.length > 1 ? `${dw(us[0].opens)} – ${dw(us[us.length - 1].opens)}` : us.length ? dw(us[0].opens) : "?";
            items.push({ kind: "review", key: ["review", r.day], day: r.day, dayw: dw(r.day), name: `Review: ${sp}`, hay: "review" });
          }
        }
        if (tp && tp[0] <= end && tp[1] >= mon) {
          const d = tp[0] > mon ? tp[0] : mon;
          items.push({ kind: "taper", key: null, day: d, dayw: dw(d), name: `No new cards: ${dw(tp[0])} – ${dw(tp[1])}` });
        }
        const order = { date: 0, event: 1, review: 2, taper: 3 };
        items.sort((a, b) => String(a.day).localeCompare(String(b.day)) || order[a.kind] - order[b.kind]);
        const [words, warn] = weekWords(asks[mon]);
        const evs = w.events.map((e) => e.name || "?").join(", ");
        return { start: mon, label: `Week ${n} · ${spanWords(on[0], on[on.length - 1])}${now ? ", this week" : ""}`, now, past: end < t0, words, warn,
          folded: `${pl(w.dates.length, "set")}${evs ? `, ${evs}` : ""}`,
          look: items.some((x) => x.kind === "date" && look.has(x.key[1])), heavy: hv && hv.week === mon ? hv : null, items };
      });
      const cal = byOpens().map((u) => ({ kind: "date", key: ["date", u.id], day: u.opens, last: u.due || u.opens, name: String(u.name || "?") }))
        .concat(B.events().map((e) => ({ kind: "event", key: ["event", e.id], day: e.day, last: e.day, name: String(e.name || "?") })));
      const load = {};
      for (const [d, e] of workMap()) if (e.n) load[d] = e.n;
      const out2 = { weeks, today: t0, todayw: dw(t0), look: [...look.keys()].sort(), lookN: look.size, cal, load, cap: capOf(),
        days: (paceOf().days || [1, 1, 1, 1, 1, 1, 1]).slice(), taper: tp, sending: sending(), cover: coverMine(), hasDeck: tree() && author(),
        empty: !units().length && !B.events().length ? (author() ? "No sets yet. Tick what the plan covers in the deck, or Add › A set." : "No sets on this plan yet.") : "",
        ...strips() };
      if (author()) out2.shape = shapeLine(asks);
      return out2;
    }

    // ---- the picked one, beside the plan ----
    function moveTo(u, most = 10) {
      const us = byOpens().filter((x) => x.id !== u.id);
      if (!us.length) return [];
      const at = us.filter((x) => x.opens < u.opens).length;
      const lo = Math.max(0, Math.min(at - Math.floor(most / 2), us.length - most));
      return us.slice(lo, lo + most).map((x) => [`${x.name || "?"} · ${fmt(x.opens)}`, x.id]);
    }
    /** a tag's extras ("Leave out its extras"): [path, without now, n without] (webmodel.extras) */
    function extras(key) {
      if (!tree() || !key) return null;
      let path, without;
      if (key[0] === "tag") { path = key[1]; without = false; } else if (key[0] === "search") { path = B.extrasOf(key[1]); without = true; if (!path) return null; } else return null;
      const kids = B.extraKids(`tag:${path}`);
      if (!kids.length) return null;
      return [path, without, Math.max(0, B.n(`tag:${path}`) - kids.reduce((a, k) => a + B.n(k), 0))];
    }
    function datePanel(u) {
      const a = author(), t0 = today0();
      const out = { kind: "date", uid: u.id, name: String(u.name || ""), label: `${dw(u.opens)} · ${u.name || "?"}`, opens: u.opens, due: u.due || "",
        even: !!u.even, for: u.for || "", author: a };
      out.events = B.events().slice().sort((x, y) => x.day.localeCompare(y.day))
        .map((e) => ({ id: e.id, label: `${e.name || "?"} · ${fmt(e.day)}${e.day < u.opens ? " (after it)" : ""}` }));
      const rs = rows(u), fr = fresh();
      out.sources = rs.map((r, i) => {
        const key = r.key, s = { i, name: rowName(r), n: r.n, raw: String(r.raw || ""), key: key[0] === "questions" ? null : key };
        if (!a) return s;
        const menu = [];
        if ((key[0] === "tag" || key[0] === "deck") && tree()) menu.push({ label: "Spread it…", cmd: "spread", args: { key } });
        if ((key[0] === "tag" || key[0] === "cut") && B.ptags().length && !B.isOwnTag(key[1])) {
          const now = key[0] === "cut" ? key[2] : null;
          menu.push({ label: "Keep only cards also tagged", sub: [["All of it", null], ...B.ptags().map((x) => [x.name || "?", x.id])]
            .map(([lb, pid]) => ({ label: lb, on: pid === now, cmd: "set_cut", args: { tag: key[1], ptag: pid } })) });
        }
        const ex = extras(key);
        if (ex) {
          const [path, without, main] = ex, nx = without || r.n === null ? 0 : Math.max(0, r.n - main);
          menu.push({ label: !without && nx ? `Leave out its extras (${nx.toLocaleString()} cards)` : without ? "Put its extras back" : "Leave out its extras",
            cmd: "op", args: { op: { op: "set_extras", date: u.id, path, without: !without } } });
        }
        const moves = moveTo(u);
        menu.push({ label: "Move to", sub: [...moves.map(([lb, uid]) => ({ label: lb, cmd: "op", args: { op: { op: "move_source", date: u.id, key, to: uid } } })),
          ...(moves.length ? [{ sep: true }] : []), { label: "Another day…", cmd: "move_source_form", args: { i } }] });
        if (key[0] === "tag" || key[0] === "cut") menu.push({ label: "A note for followers on it…", cmd: "remark", args: { path: key[1] } });
        menu.push({ label: "Copy its search", cmd: "copy_source", args: { i } });
        menu.push({ sep: true });
        menu.push({ label: "Take it off this set", cmd: "op", args: { op: { op: "take_cards", date: u.id, key } } });
        s.menu = menu;
        return s;
      });
      if (!a) {  // mine: when it opens, its finish-by day, what it's for (webmodel.date_panel), on my days
        const ev = u.for && B.evById(u.for);
        out.meta = [u.opens > t0 ? `Opens ${fmt(u.opens)}` : `Opened ${fmt(u.opens)}`, u.due ? `finish by ${fmt(u.due)}` : "",
          ev ? `${B.forWord(u)} ${ev.name || "?"}` : "", u._moved ? `${pl(u._moved, "day")} later on your copy` : ""].filter(Boolean).join(" · ");
      }
      const p = !a ? progOf(u) : null;
      const n = a ? total(u) : p ? p[2] : null;
      out.n = n;
      const bits = a && fr.has(u.id) ? ["changed, not sent"] : [];
      if (!a) {
        if (!p) bits.push("your Anki counts it at its next sync");
        else {
          const opened = Math.min(p[0], p[2]), shut = p[2] - opened;
          bits.push(shut ? `${opened.toLocaleString()} open, ${shut.toLocaleString()} still shut` : `all ${opened.toLocaleString()} open`, `${Math.min(p[1], p[2]).toLocaleString()} seen`);
        }
      } else if (!tree()) bits.push(`the deck's tags come from your Anki (Due Crew sends them once ${B.doc.deck || "the deck"} has a plan there)`);
      else if (n) {
        bits.push(`${pl(n, "card")}`);
        const [x, y] = Sched.win(B.doc, u, 0);
        let k = 0;
        for (let d = x; d <= y; d = addDays(d, 1)) if (B.isStudy(d)) k++;
        if (k > 1) bits.push(`over ${k} study days, about ${Math.ceil(n / k).toLocaleString()} a day`);
      }
      if (a && rs.some((r) => r.n === null && r.kind !== "question")) bits.push("searches and picks are counted in your Anki");
      out.said = bits.join(", ");
      const lines = (u.todo || []).filter((x) => x && typeof x === "object");
      out.todo = lines.map((x) => `${Todo.LABEL[x.k] || "Do"}: ${x.t || ""}`);
      const first = Sched.start(B.doc), lastD = B.lastDay();
      out.every = Every.clean(B.doc.every || []).filter((x) => first && u.opens >= first && u.opens <= lastD && x.r.includes(String(wd(u.opens))))
        .map((x) => `${Todo.LABEL[x.k] || "Do"}: ${x.t || ""} (every week)`);
      if (a) {
        const after = units().filter((x) => x.opens > u.opens).length;
        const more = [{ label: after ? `Move this and the ${pl(after, "set")} after it…` : "Move this set…", cmd: "move_from" }, { sep: true }];
        if (B.ptags().length && rs.some((r) => r.key[0] === "tag")) {
          more.push({ label: "Keep only cards also tagged", sub: B.ptags().map((x) => ({ label: String(x.name || "?"), cmd: "keep_only", args: { ptag: x.id } })) });
        }
        if (u.due && u.due > u.opens) more.push({ label: `Spread its cards evenly to ${fmt(u.due)}`, on: !!u.even, cmd: "op", args: { op: { op: "set_even", date: u.id, on: !u.even } } });
        else more.push({ label: "Spread its cards evenly (give it a finish-by day first)", off: true });
        more.push({ sep: true }, { label: "Copy the set's search", cmd: "copy_search" }, { sep: true }, { label: "Delete this set…", cmd: "delete", bad: true });
        out.more = more;
      }
      // notes are on the plan's day (everyone's): a follower's set on a day of their own reads and writes its plan day's
      const own = !a && ((plan().doc || {}).units || []).find((x) => x.id === u.id);
      out.notes = notesView(own ? own.opens : u.opens, u.opens);
      return out;
    }
    function eventPanel(e) {
      const us = prep(e), placed = B.placedKeys(), a = author();
      let cards = 0;
      const items = us.map((u) => {
        const p = !a ? progOf(u) : null, n = a ? total(u, placed) : p ? p[2] : null;
        cards += n || 0;
        return { key: ["date", u.id], label: `${dw(u.opens)} · ${u.name || "?"}${n !== null ? ` · ${n.toLocaleString()}` : ""}` };
      });
      const [, seen, has] = mine(us);
      const counted = a ? (tree() ? ` · ${pl(cards, "card")}` : "") : has ? ` · ${pl(cards, "card")}, ${seen.toLocaleString()} seen` : "";
      return { kind: "event", eid: e.id, name: String(e.name || ""), day: e.day, title: `${fmt(e.day)} · ${e.name || "?"}`, author: a, items, n: us.length,
        said: us.length ? `Tests ${pl(us.length, "set")}${counted}` : a ? "No set leads up to it yet: pick it as a set's Leads up to." : "No set leads up to it yet." };
    }
    function reviewPanel(r) {
      const us = reviewUnits(r), a = unit(r.from), b = unit(r.to);
      const names = `${(a || {}).name || "?"}${b && b !== a ? ` – ${b.name || "?"}` : ""}`;
      return { kind: "review", day: r.day, title: `${dw(r.day)} · Review · ${names}`, author: author(),
        said: `That morning, followers get a Due Crew deck of what they've seen from these ${pl(us.length, "set")}, most missed first.` };
    }
    function panel(key) {
      const none = { kind: "none", words: "Pick a set on the left to see its cards here." };
      if (!key || !B) return none;
      if (key[0] === "date") { const u = unit(key[1]); return u ? datePanel(u) : none; }
      if (key[0] === "event") { const e = eventOf(key[1]); return e ? eventPanel(e) : none; }
      if (key[0] === "review") { const r = reviewOf(key[1]); return r ? reviewPanel(r) : none; }
      return none;
    }
    function notesView(day, shown = day) {
      const writes = !(plan().library && !author());
      const list = (B.notes || []).filter((x) => x.day === day).sort((a, b) => String(a.id).localeCompare(String(b.id)));
      return { rows: list.map((x) => ({ id: x.id, who: x.mine ? "You" : String(x.name || "?"), text: String(x.text || ""), remove: !!x.remove })),
        writes, day, dayw: fmt(shown), loading: false };
    }

    // ---- the deck beside the plan ----
    const shown = (key, v = F.deck.view) => (v === "deck" ? B.kindOf(key) === "deck" : B.kindOf(key) === "tag" && B.kindsBelow(key).has(v));
    /** what's ticked as the plan's cover (builder.js's treePanel's rules) */
    const covered = (k) => B.cover.has(k) || [...B.cover].some((c) => B.under(c, k));
    const partly = (k) => [...B.cover].some((c) => B.under(k, c));
    const inView = (k) => (F.deck.view === "deck" || B.kindOf(k) === "deck" ? [k]
      : B.kindsBelow(k).size > 1 ? B.kidsOf(k).filter((c) => B.kindsBelow(c).has(F.deck.view)).flatMap(inView) : [k]);
    function where(key) {
      const path = B.pathOf(key).toLowerCase(), f = B.kindOf(key) === "tag" ? "tags" : "decks";
      const u = byOpens().find((x) => (x[f] || []).some((p) => p.toLowerCase() === path));
      return u ? [u.id === F.deck.target ? "on this set" : `on ${dw(u.opens)}`, u.id] : ["", null];
    }
    function node(key, name, kids = true) {
      const [wh, uid] = where(key);
      const has = kids && B.kidsOf(key).some((k) => shown(k) && B.n(k));
      return { key, name: name || Tags.word(B.pathOf(key).split("::").pop()), path: B.pathOf(key), where: wh, uid, n: B.n(key),
        kids: has, open: has && F.deck.opened.has(key), children: [] };
    }
    function fillOpen(nd) {
      if (!nd.open) return;
      for (const k of B.kidsOf(nd.key)) if (shown(k) && B.n(k)) { const c = node(k); fillOpen(c); nd.children.push(c); }
    }
    function marks(nodes) {
      const placed = B.placedKeys(), u = F.deck.target ? unit(F.deck.target) : null;
      const on = new Set(u ? B.srcs(u) : []);
      const mark = (nd) => {
        const k = nd.key;
        if (u) { nd.check = on.has(k) ? 1 : 0; nd.off = !on.has(k) && [...on].some((x) => B.under(x, k)); }
        else {
          const all = inView(k), tk = covered(k) || (all.length > 1 && all.every(covered));
          nd.check = tk ? 1 : partly(k) ? 2 : 0;
          nd.off = covered(k) && !B.cover.has(k);
        }
        nd.placed = B.isPlaced(k, placed) && !on.has(k);
        nd.children.forEach(mark);
      };
      nodes.forEach(mark);
    }
    function deckPanel() {
      if (!tree()) return { none: `This plan's deck (${B.doc.deck || "?"}) hasn't come from your Anki yet: open Due Crew there, and its tags come with it.` };
      const st = F.deck, have = B.kindsBelow("root:tag");
      const views = VIEWS.slice(0, 2).filter(([k]) => have.has(k)).map(([key, label]) => ({ key, label }));
      const more = VIEWS.slice(2).filter(([k]) => (k === "other" ? have.has("other") : k === "deck" ? B.kidsOf("root:deck").length > 0 : B.ptags().length > 0))
        .map(([key, label]) => ({ key, label }));
      if ((st.view === "resource" || st.view === "system") && !have.has(st.view)) st.view = views[0]?.key || (have.has("other") ? "other" : "deck");
      if (st.target && !unit(st.target)) st.target = null;
      const u = st.target ? unit(st.target) : null;
      const o = { target: st.target, targetLabel: u ? `${dw(u.opens)} · ${u.name || "?"}` : "", view: st.view, views, more, find: st.find, notes: [], nodes: [], lines: [] };
      if (st.view === "plan") {
        for (const x of B.ptags()) {
          const key = `tag:${B.ptagPath(x)}`, [wh, uid] = where(key);
          o.nodes.push({ key, name: String(x.name || "?"), path: B.ptagPath(x), where: wh, uid, n: B.n(key), kids: false, open: false, children: [],
            ptag: x.id, check: wh === "on this set" ? 1 : 0, off: !st.target });
        }
      } else {
        const term = st.find.trim().toLowerCase();
        if (term) {
          const found = [];
          for (const k of B.order.keys()) {
            const p = B.pathOf(k);
            if (shown(k) && B.n(k) && (p.toLowerCase().includes(term) || Tags.name(p).toLowerCase().includes(term))) found.push(k);
            if (found.length > FOUND_MAX) break;
          }
          if (!found.length) {
            const elsewhere = VIEWS.slice(0, 4).filter(([v]) => v !== st.view).map(([v, lb]) => [v, lb, [...B.order.keys()].filter((k) => shown(k, v) && B.n(k)
              && (B.pathOf(k).toLowerCase().includes(term) || Tags.name(B.pathOf(k)).toLowerCase().includes(term))).length]).filter((x) => x[2]);
            o.lines.push({ words: elsewhere.length ? `Nothing here has “${st.find.trim()}”.` : `Nothing in this deck has “${st.find.trim()}”.` });
            for (const [v, lb, n] of elsewhere) o.lines.push({ words: `${lb} has ${n.toLocaleString()}`, view: v });
          } else {
            o.nodes = found.slice(0, FOUND_MAX).map((k) => { const nd = node(k, Tags.name(B.pathOf(k))); fillOpen(nd); return nd; });
            if (found.length > FOUND_MAX) o.lines.push({ words: `The first ${FOUND_MAX.toLocaleString()}: type more of a name to narrow them.` });
          }
        } else {
          const root = st.view === "deck" ? "root:deck" : "root:tag";
          const nodes = B.kidsOf(root).filter((k) => shown(k) && B.n(k)).map((k) => node(k));
          if (nodes.length === 1 && !st.opened.size) {  // one way down: opened to the first choice
            let nd = nodes[0];
            while (nd && nd.kids) { st.opened.add(nd.key); nd.open = true; fillOpen(nd); nd = nd.children.length === 1 ? nd.children[0] : null; }
          } else nodes.forEach(fillOpen);
          o.nodes = nodes;
        }
        marks(o.nodes);
      }
      o.fill = u ? null : fillView();
      o.cardNotes = u ? [] : B.remarks().filter((r) => r.card && r.id).map((r) => ({ id: r.id, label: `${r.card[0]} · card ${Number(r.card[1]) + 1}: ${String(r.text || "").slice(0, 40)}` }));
      return o;
    }
    /** what's ticked, laid out: the words and the buttons (webmodel._fill) */
    function fillView() {
      const st = F.deck, o = { words: "", bad: false, go: null, alt: null, week: false, keep: st.dirty };
      if (!B.cover.size) { o.words = "Tick what the plan covers; then lay it out on its study days."; return o; }
      const left = B.coverLeft();
      if (!left) { o.words = "Everything ticked is on a set."; return o; }
      const daily = paceOf().daily || 20, start = planStart(), [ev, end] = endsWith(), who = (ev || {}).name || "the end";
      const fin = B.finishBy(daily);
      o.upto = B.events().filter((e) => e.day > start).sort((a, b) => a.day.localeCompare(b.day))
        .map((e) => ({ label: `Before ${e.name || "?"} · ${fmt(e.day)}`, eid: e.id }));
      o.week = true;
      o.head = `${left.toLocaleString()} ticked, not on a set.`;
      if (end && fin && fin >= end) {
        const fitEnd = ev ? addDays(end, -1) : end;
        const d1 = fitDaily(fitEnd) || daily;
        o.bad = true;
        o.words = `At ${daily.toLocaleString()} a day they'd end ${fmt(fin)}, ${pl(Sched.diff(fin, end), "day")} after ${who}.`;
        o.go = { label: `Fit them before ${who}: ${d1.toLocaleString()} a day`, how: ["end", false, [fitEnd, ev ? ev.id : null]] };
        o.alt = { label: `Lay them out at ${daily.toLocaleString()} anyway`, how: ["daily", false, null] };
      } else if (end && fin) {
        o.words = `At ${daily.toLocaleString()} a day they end ${fmt(fin)}, before ${who}.`;
        o.go = { label: `Lay them out at ${daily.toLocaleString()} a day`, how: ["daily", false, null] };
      } else {
        o.words = fin ? `At ${daily.toLocaleString()} a day they end ${fmt(fin)}.` : "";
        o.go = { label: `Lay them out at ${daily.toLocaleString()} a day`, how: ["daily", false, null] };
      }
      return o;
    }
    /** the pace that fits what's ticked by a day (builder.endDaily, to that day) */
    function fitDaily(day) {
      const was = B.doc.end;
      B.doc.end = day;
      try { return B.endDaily(); } finally { if (was) B.doc.end = was; else delete B.doc.end; }
    }

    // ---- Insights: the site's (the deck tree's counts; nobody's cards) ----
    function insights() {
      if (!units().length) return { none: "Nothing to count yet: the plan has no sets." };
      if (author() && !tree()) return { none: `Nothing to count yet: ${B.doc.deck || "the deck"}'s tags come from your Anki.` };
      const asks = weekAsks(), t0 = today0(), work = workMap();
      const days = [...units().map((u) => u.opens), ...B.events().map((e) => e.day)].sort();
      const lastD = [B.lastDay(), B.doc.end || "", ...B.events().map((e) => e.day)].filter(Boolean).sort().pop();
      const rowsW = [];
      if (days.length && Object.keys(asks).length) {
        for (let mon = monday(days[0]), n = 1; mon <= monday(lastD); mon = addDays(mon, 7), n++) {
          const a = asks[mon] || {}, sun = addDays(mon, 6);
          rowsW.push({ start: mon, n, span: spanWords(mon, sun), events: B.events().filter((e) => mon <= e.day && e.day <= sun).map((e) => e.name || "?"),
            new: a.new || 0, reviews: a.reviews || 0, cards: (a.new_week || 0) + (a.reviews_week || 0), over: !!a.over, top: a.top || 0, cap: a.cap || 0,
            now: mon <= t0 && t0 <= sun, past: sun < t0 });
        }
      }
      const rvW = (x) => { const r = Reviews.about(x.reviews); return r === "0" ? "0" : `~${r}`; };
      const newW = (x) => (x.over ? `${x.new.toLocaleString()} · busiest day ${x.top.toLocaleString()}` : x.new.toLocaleString());
      const tip = (x) => `Week ${x.n}, ${x.span}: ${x.new.toLocaleString()} new a study day${x.over ? ` (${x.top.toLocaleString()} on its busiest day, over the pace of ${x.cap.toLocaleString()})` : ""}, ${rvW(x)} reviews a day${x.events.length ? `; ${x.events.join(", ")}` : ""}`;
      let wk;
      if (!rowsW.length) wk = { empty: "No new cards on its sets yet." };
      else {
        const all = [...work.values()].reduce((a, e) => a + e.n, 0);
        const best = rowsW.reduce((b, x) => (!b || x.cards > b.cards ? x : b), null);
        let words = `${pl(all, "new card")} over ${pl(rowsW.length, "week")}.`;
        if (best && best.cards > 0) words += ` Busiest: week ${best.n}, ${best.span}: ${best.new.toLocaleString()} new a study day, ${rvW(best)} reviews a day.`;
        const over = rowsW.filter((x) => x.over).map((x) => x.n);
        const cap = Math.max(...rowsW.map((x) => x.cap)), newTop = Math.max(...rowsW.map((x) => x.new), cap) || 1, rvTop = Math.max(...rowsW.map((x) => x.reviews)) || 1;
        const pct = (v, whole) => (whole ? Math.max(0, Math.min(100, Math.round((10000 * v) / whole) / 100)) : 0);
        wk = { words, over: over.length ? `Over the pace: ${over.length === 1 ? `week ${over[0]}` : `weeks ${over.slice(0, -1).join(", ")} and ${over[over.length - 1]}`}` : "",
          newHead: `New a study day${cap ? ` · the line, your pace: ${cap.toLocaleString()}` : ""}`, rvHead: "Reviews a day", line: cap ? pct(cap, newTop) : null,
          rows: rowsW.map((x) => ({ week: `Week ${x.n}${x.now ? ", this week" : ""}`, now: x.now, past: x.past, span: x.span, events: x.events.join(", "), tip: tip(x),
            new: pct(x.new, newTop), has: !!x.new, over: x.over, newWords: newW(x), rv: pct(x.reviews, rvTop), hasRv: x.reviews > 0, rvWords: rvW(x) })) };
      }
      return { work: wk, deck: author() ? deckInsight() : myDeck(), has: contents() };
    }
    /** a follower's: what my sets hold, what I've seen of it and what's to go (webtabs._deck's key), as my Anki synced it */
    function myDeck() {
      const [, seen, has] = mine(units());
      const all = units().reduce((a, u) => a + totalOf(u), 0);  // my Anki's count of a set, else the plan's
      const pct = (v, w) => (w ? Math.max(0, Math.min(100, Math.round((10000 * v) / w) / 100)) : 0);
      const o = { words: `${pl(all, "card")} on your sets`, tip: "", bar: [{ v: has ? pct(seen, all) : 0, k: "fill", has: has && seen > 0 }] };
      if (has) {
        o.bar.push({ v: pct(all - seen, all), k: "soft", has: all > seen });
        o.tip = `${seen.toLocaleString()} of ${all.toLocaleString()} seen`;
        o.key = `You've seen ${seen.toLocaleString()} of them; ${(all - seen).toLocaleString()} to go.`;
      } else o.by = "Your Anki counts what you've seen at its next sync.";
      return o;
    }
    function deckInsight() {
      const placed = B.placedKeys();
      const held = units().reduce((a, u) => a + B.unitTotal(u, placed), 0);
      const tops = B.kidsOf("root:tag").filter((k) => B.n(k));
      const root = tops.length === 1 ? tops[0] : null;
      const whole = B.n(`deck:${B.doc.deck}`) || (root ? B.n(root) : Math.max(0, ...tops.map((k) => B.n(k))));
      const pct = (v, w) => (w ? Math.max(0, Math.min(100, Math.round((10000 * v) / w) / 100)) : 0);
      const share = (v, w) => (!w || !v ? "none" : v >= w ? "all" : (v * 100) / w < 1 ? "<1%" : `${Math.min(99, Math.round((v * 100) / w))}%`);
      const name = String(B.doc.deck || "").split("::").pop();
      const o = { words: whole ? `${held.toLocaleString()} of ${name}'s ${whole.toLocaleString()} tagged cards (${share(held, whole)})` : `${pl(held, "card")} on its sets`,
        tip: whole ? `${held.toLocaleString()} of the deck's ${whole.toLocaleString()} tagged cards (${share(held, whole)})` : "",
        bar: [{ v: pct(held, whole || held), k: "fill", has: held > 0 }] };
      // its parts: the tags just under the deck's own (a resource, a system), the plan's share of each
      const parts = (root ? B.kidsOf(root) : tops).filter((k) => B.n(k));
      const heldIn = (k) => [...placed].filter((p) => p === k || B.under(k, p)).filter((p, _i, all) => !all.some((q) => q !== p && B.under(q, p))).reduce((a, p) => a + B.n(p), 0);
      const rowsP = parts.map((k) => ({ name: Tags.word(B.pathOf(k).split("::").pop()), held: Math.min(B.n(k), heldIn(k) || (placed.has(k) ? B.n(k) : 0)), total: B.n(k) }))
        .sort((a, b) => b.held - a.held || b.total - a.total);
      const some = rowsP.filter((r) => r.held), none = rowsP.filter((r) => !r.held);
      if (some.length) {
        const shownR = some.slice(0, 12), scale = Math.max(...shownR.map((r) => r.total)) || 1;
        o.by = root ? `By ${Tags.word(B.pathOf(root).split("::").pop())}'s parts` : "By its tags";
        o.parts = { rows: shownR.map((r) => ({ name: r.name, fill: pct(r.held, scale), track: pct(r.total, scale), words: `${r.held.toLocaleString()} of ${r.total.toLocaleString()} · ${share(r.held, r.total)}` })),
          more: some.length > 12 ? `and ${(some.length - 12).toLocaleString()} smaller ones with some of their cards in it` : "",
          none: none.length ? `Not in it: ${none.slice(0, 4).map((r) => r.name).join(", ")}${none.length > 4 ? ` and ${(none.length - 4).toLocaleString()} more` : ""}` : "" };
      }
      return o;
    }
    function contents() {
      const placed = B.placedKeys(), last = lastEvent(), of = (u) => totalOf(u, placed);
      const held = units().reduce((a, u) => a + of(u), 0);
      const exams = B.events().slice().sort((a, b) => a.day.localeCompare(b.day)).map((e) => {
        const us = prep(e), cards = us.reduce((a, u) => a + of(u), 0);
        const words = !us.length && e === last ? `everything: ${pl(held, "card")}` : !us.length ? "no set for it yet" : `${pl(cards, "card")} from ${pl(us.length, "set")}`;
        return { key: ["event", e.id], day: e.day, dayw: dw(e.day), name: String(e.name || "?"), words };
      });
      const big = units().map((u) => [u, of(u)]).filter(([, n]) => n > 0).sort((a, b) => b[1] - a[1] || a[0].opens.localeCompare(b[0].opens)).slice(0, 5)
        .map(([u, n]) => ({ key: ["date", u.id], day: u.opens, dayw: dw(u.opens), name: String(u.name || "?"), words: pl(n, "card") }));
      return { exams, big, lines: [author() ? "Counts are the deck's tags as your Anki last sent them; searches and picked cards are counted in Anki."
        : "Counts are your Anki's, as it last synced; a set it hasn't counted yet shows the plan's count."] };
    }

    // ---- Settings: an author's ----
    function shapeBase() {
      const p = paceOf(), start = planStart(), [ev, end] = endsWith(), ph = B.doc.phases || {};
      return { start, end: ev ? `event:${ev.id}` : end ? "day" : "none", end_day: end || addDays(start, 55), days: (p.days || [1, 1, 1, 1, 1, 1, 1]).map((x) => (x ? 1 : 0)),
        mode: MODES.some(([k]) => k === p.mode) ? p.mode : "daily", daily: Number(p.daily || 20), taper: Number(ph.taper || 0), catchup: Number(ph.catchup || 0) };
    }
    const endOf = (v) => { const k = String(v.end || "none"); if (k.startsWith("event:")) { const e = eventOf(k.slice(6)); return e ? e.day : null; } return k === "day" ? v.end_day : null; };
    /** the shape's rows, on the working copy (shape.Shape.ops, done as the builder's pace box does) */
    function applyShape(base, v) {
      const delta = Sched.diff(v.start, base.start);
      const shifted = !!delta && (units().length || B.events().length || (B.doc.reviews || []).length || B.doc.end);
      if (shifted) {
        for (const u of units()) B.shiftUnit(u, delta);
        for (const r of B.doc.reviews || []) r.day = addDays(r.day, delta);
        for (const x of B.events()) x.day = addDays(x.day, delta);
        if (B.doc.end) B.doc.end = addDays(B.doc.end, delta);
      }
      if (delta) B.start = v.start;
      let end = endOf(v);
      if (end && shifted && !(v.end === "day" && "end_day" in F.shape)) end = v.end.startsWith("event:") ? endOf(v) : addDays(end, delta);
      if ((end || null) !== (B.doc.end || null)) { if (end) B.doc.end = end; else delete B.doc.end; }
      const p = paceOf();
      B.pace = { ...p, mode: v.mode, days: v.days.slice(), daily: v.daily };
      const c = Number(v.catchup || 0), t = B.doc.end ? Number(v.taper || 0) : 0;
      if (c || t) B.doc.phases = { catchup: c, taper: t }; else delete B.doc.phases;
    }
    function shapeEdits() {
      const base = shapeBase(), v = { ...base, ...F.shape };
      const changed = Object.keys(F.shape).some((k) => k !== "end_day" && JSON.stringify(F.shape[k]) !== JSON.stringify(base[k]))
        || ("end_day" in F.shape && v.end === "day" && F.shape.end_day !== base.end_day);
      return [base, v, changed];
    }
    function shapePreview(base, v) {
      const before = JSON.parse(JSON.stringify([B.doc, B.pace, B.start]));
      applyShape(base, v);
      const opens = new Map((before[0].units || []).map((u) => [u.id, u.opens]));
      const moved = units().filter((u) => opens.has(u.id) && opens.get(u.id) !== u.opens).length;
      const evs = new Map((before[0].events || []).map((e) => [e.id, e.day]));
      const evMoved = B.events().filter((e) => evs.has(e.id) && evs.get(e.id) !== e.day).length;
      const opened = (before[0].units || []).filter((u) => u.opens <= today0() && units().some((x) => x.id === u.id && x.opens !== u.opens)).length;
      const ph = B.doc.phases || {}, end = B.doc.end;
      // back as it was: a preview changes nothing
      B.doc.units = before[0].units; B.doc.events = before[0].events; B.doc.reviews = before[0].reviews;
      for (const k of ["events", "reviews", "end", "phases"]) { if (before[0][k] === undefined) delete B.doc[k]; else B.doc[k] = before[0][k]; }
      B.pace = before[1]; B.start = before[2];
      const parts = [];
      if (moved || evMoved) {
        parts.push(["", "Saving moves "], ["b", [moved ? pl(moved, "set") : "", evMoved ? `${evMoved.toLocaleString()} quiz${evMoved !== 1 ? "zes" : ""} or exam${evMoved !== 1 ? "s" : ""}` : ""].filter(Boolean).join(" and ")], ["", "."]);
        if (opened) parts.push(["", ` ${opened.toLocaleString()} of them opened already: followers who have their cards keep them.`]);
      } else parts.push(["", "No set moves."]);
      if (ph.taper && end) parts.push(["", ` The last ${pl(Number(ph.taper), "day")} before ${fmt(end)} have no new cards.`]);
      return { parts, bad: false };
    }
    function shapeView() {
      const [base, v, changed] = shapeEdits();
      const evs = B.events().slice().sort((a, b) => a.day.localeCompare(b.day));
      const ends = [...evs.map((e) => ({ v: `event:${e.id}`, label: `${e.name || "?"} · ${fmt(e.day)}` })), { v: "day", label: "A day…" }, { v: "none", label: "Nothing yet" }];
      const catchups = CATCHUP.map(([c, label]) => ({ v: c, label }));
      if (!CATCHUP.some(([c]) => c === v.catchup)) catchups.push({ v: v.catchup, label: `Every ${nth(v.catchup)} week` });
      return { start: v.start, ends, end: ends.some((x) => x.v === v.end) ? v.end : "none", endDay: v.end_day, days: v.days,
        modes: MODES.map(([k, label]) => ({ v: k, label })), mode: v.mode, daily: v.daily, taper: v.taper, taperOff: !endOf(v),
        catchups, catchup: v.catchup, go: waiting() || others(plan()) ? "Add to the changes" : "Save", preview: changed ? shapePreview(base, v) : null };
    }
    /** Reset to default's lines: what goes back to the plan's (plan_flow.reset_lines, the old page's resetBtn) */
    function resetLines() {
      const f = follow(), n = (f.skipped || []).length, m = Object.keys(f.moved || {}).length;
      return [f.shift ? `Your sets back on time (now ${pl(f.shift, "day")} later)` : "", n ? `${pl(n, "skipped set")} back` : "",
        m ? `${pl(m, "moved set")} back` : "", f.paused || f.until ? "Your pause ends" : ""].filter(Boolean);
    }
    const inTeam = () => !!(follow().share && !follow().teamAsk);
    /** Settings, a follower's: my follow (webtabs._follower), wired to PATCH /plans/{id}/follow as the old page and Anki send it */
    function mySettings() {
      const p = plan(), f = follow();
      if (!f || !Object.keys(f).length) return { role: "follower", pid: p.id, gone: "You don't follow it on this account any more." };
      const shift = Number(f.shift || 0), own = String(f.own || ""), have = new Set(f.skipped || []);
      const names = new Map(((p.doc || {}).units || []).map((u) => [u.id, u]));
      const label = (u) => `${fmt(u.opens)} · ${u.name || "?"}`;
      const t0 = today0(), early = Number(f.early || 0);
      return { role: "follower", pid: p.id, busy: F.busy,
        head: `Following ${p.name || "the plan"}${f.paused ? `, paused${f.until ? ` until ${fmt(f.until)}` : ""}` : ""}`,
        shift, later: shift ? `${pl(shift, "day")} later` : "Some days later…",
        skips: [...have].map((uid) => ({ uid, label: names.has(uid) ? label(names.get(uid)) : "a set taken off" })),
        ahead: [...names.values()].filter((u) => String(u.opens || "") >= t0 && !have.has(u.id)).sort((a, b) => String(a.opens).localeCompare(String(b.opens)))
          .slice(0, 20).map((u) => ({ uid: u.id, label: label(u) })),
        own, held: null, lesson: null,
        squad: inTeam() ? "You're in it" : "Not in it", squadTip: inTeam() ? "Its squad sees that you showed up, never your numbers" : "",
        team: inTeam() ? "Leave its squad" : "Join its squad",
        paused: !!f.paused, copy: !!(p.library || p.listed),
        early: [[0, "Off"], [1, "1 day"], [2, "2 days"], [3, "3 days"], [5, "5 days"], [7, "7 days"]].map(([k, lb]) => ({ n: k, label: lb, on: early === k })),
        sched: false, reset: resetLines().length > 0, hide: ["held", "change_deck", "open_everything", "schedule", "lesson_deck"],
        more: [{ label: "Its page: posts, calendar link ›", name: "its_page" }] };
    }
    function settings() {
      if (!author()) return mySettings();
      const p = plan(), d = B.doc, own = owner(), eds = (p.editors || []).filter((e) => e && e.uid);
      const offered = p.handover;
      const coas = eds.map((e) => ({ uid: String(e.uid), name: String(e.name || "?"),
        what: e.pending ? "invited, waiting for a yes" : e.uid === offered ? "offered the plan" : "co-author",
        hand: own && !e.pending && !offered, off: own ? (e.pending ? "Take back the invite" : "Take them off") : "" }));
      const why = p.audience !== "code" ? "Only a plan anyone with the code can follow goes in the library." : !units().length ? "Put some sets on it first." : "";
      const n = others(p);
      const squads = (B.squads || []).map((q) => ({ id: q.id, name: String(q.name || "?") }));
      if (p.squad && !squads.some((q) => q.id === p.squad)) squads.push({ id: p.squad, name: "A squad of mine" });
      return { role: "author", pid: p.id, owner: own, busy: F.busy, name: String(B.meta.name || ""), line: String(B.meta.line || ""), url: String(d.deckUrl || ""),
        urlTip: `On its link page and poster, and in Anki for anyone with no deck called ${d.deck || "?"}.`, shape: shapeView(),
        every: Every.clean(d.every || []).map((x) => `${Todo.LABEL[x.k] || "Do"}: ${x.t || ""}, ${Every.label(x.r)}`).join("; ") || "None",
        code: p.code || "none yet", hasCode: !!p.code, squads, squad: p.squad || null, audience: p.audience === "squad" ? "squad" : "code",
        ownerOnly: own ? "" : p.audience === "squad" ? "Only people in a squad of its owner's can follow it. Its owner sets that." : "Anyone with the code can follow it. Its owner sets that.",
        following: n ? `${n.toLocaleString()} following` : "Nobody follows it yet",
        coauthors: coas, canAsk: own && coas.length < 10, offered: own && !!offered, leave: !own,
        library: { shown: own && p.listed !== -1, on: p.listed === 1, off: !(own && !F.busy && (!why || p.listed === 1)),
          said: p.listed === -1 ? `Taken out of the library. ${p.listedNote || ""} It stays yours, and its followers keep following. Send feedback if it's a mistake.`
            : !own ? "Its owner lists it in the library." : why },
        ai: null, here: "More", canCopy: !!Sched.start(d) || B.events().length > 0, delete: own,
        more: [{ label: "Its page: progress, poster ›", name: "its_page" }] };
    }

    // ---- the view ----
    function view(statusOnly) {
      const st = { head: head(), status: F.status, tab: F.tab, picked: F.picked, side: F.side, without: WITHOUT };
      if (statusOnly) return st;
      if (B) {
        st.plan = planTab();
        st.panel = panel(F.picked);
        if (F.side === "deck" && author()) st.deck = deckPanel();
        if (F.tab === "insights") st.insights = insights();
        else if (F.tab === "settings") st.settings = settings();
      } else { st.plan = null; st.welcome = false; }
      if (F.newSt) st.new = newView();
      return st;
    }

    // ---- the ops the page and the view send (ops.py's names), on the working copy ----
    function srcKey(key) { return key[0] === "tag" ? `tag:${key[1]}` : key[0] === "deck" ? `deck:${key[1]}` : null; }
    /** a source off a set: its tag or subdeck, a cut, a search, its picks, a bank's questions */
    function takeSource(u, key) {
      if (key[0] === "tag" || key[0] === "deck") B.takeOut(u, srcKey(key));
      else if (key[0] === "cut") { const c = (u.cut || []).find((x) => x.tag === key[1] && x.in === key[2]); if (c) B.takeCut(u, c); }
      else if (key[0] === "search") B.takeSearch(u, key[1]);
      else if (key[0] === "picks") { u.cards = []; B.takeIds(u); }
      else if (key[0] === "questions") for (const t of key[1] || []) B.takeOut(u, `tag:${t}`);
    }
    /** a source onto a set (moved there): false when the set can't take it (B.note says why) */
    function putSource(t, from, key) {
      const L = B.LIMITS;
      if (key[0] === "tag" || key[0] === "deck") {
        const f = key[0] === "tag" ? "tags" : "decks";
        if (!(t[f] || []).includes(key[1]) && (t[f] || []).length >= L.SOURCES_MAX) { B.note = `A set holds up to ${L.SOURCES_MAX} ${f === "tags" ? "tags" : "subdecks"}.`; return false; }
        t[f] = [...new Set([...(t[f] || []), key[1]])];
      } else if (key[0] === "questions") t.tags = [...new Set([...(t.tags || []), ...key[1]])];
      else if (key[0] === "cut") {
        const c = (from.cut || []).find((x) => x.tag === key[1] && x.in === key[2]);
        if (!c) return false;
        if (!B.addSearch(t, c.q)) return false;
        if (from.sn?.[c.q] != null) t.sn = { ...(t.sn || {}), [c.q]: from.sn[c.q] };
        t.cut = [...(t.cut || []).filter((x) => !(x.tag === c.tag && x.in === c.in)), c];
      } else if (key[0] === "search") {
        if (!B.addSearch(t, key[1])) return false;
        if (from.sn?.[key[1]] != null) t.sn = { ...(t.sn || {}), [key[1]]: from.sn[key[1]] };
      } else if (key[0] === "picks") {
        for (const k of ["nids", "cids", "notes"]) if ((from[k] || []).length) { t[k] = [...new Set([...(t[k] || []), ...from[k]])]; delete t.idn; delete t.idr; }
        const have = new Set((t.cards || []).map(([g, x]) => `${g}:${x}`));
        t.cards = [...(t.cards || []), ...(from.cards || []).filter(([g, x]) => !have.has(`${g}:${x}`))];
      }
      return true;
    }
    /** a change's entry, as ops.py's: [verb, what, detail]: Changed, Added, Moved, Gone, Renamed, Split, Laid out, Tested on */
    const setW = (u, verb, detail = "") => [verb, `${dw(u.opens)} · ${u.name || "?"}`, detail];
    function op(o) {
      if (!o || typeof o !== "object") return false;
      const u = o.date ? unit(o.date) : null;
      if (o.date && !u) { say("That set isn't on the plan now."); push(); return false; }
      switch (o.op) {
        case "set_due": return change(() => {
          const due = o.due && o.due >= u.opens ? o.due : null;
          if (due) u.due = due; else { delete u.due; delete u.even; }
        }, setW(u, "Changed", o.due && o.due >= u.opens ? `finish by ${fmt(o.due)}` : "no finish-by day"), ["date", u.id]);
        case "take_cards": return change(() => { takeSource(u, o.key); B.renameAll(); }, () => setW(u, "Changed", "cards taken off"), ["date", u.id]);
        case "set_even": return change(() => { if (o.on && u.due && u.due > u.opens) u.even = true; else delete u.even; }, setW(u, "Changed", o.on ? "spread evenly" : "not spread evenly"), ["date", u.id]);
        case "set_extras": return change(() => {
          const q = B.withoutQ(o.path);
          if (o.without) { B.takeOut(u, `tag:${o.path}`); if (!B.addSearch(u, q)) { u.tags = [...new Set([...(u.tags || []), o.path])]; return false; } }
          else { B.takeSearch(u, q); u.tags = [...new Set([...(u.tags || []), o.path])]; }
          B.renameAll();
        }, setW(u, "Changed", o.without ? "its extras left out" : "its extras back"), ["date", u.id]);
        case "move_source": {
          const t = unit(o.to);
          if (!t) return false;
          return change(() => {
            if (!putSource(t, u, o.key)) return false;
            takeSource(u, o.key);
            B.cleanup(); B.renameAll(); B.byOpens();
          }, () => setW(u, "Moved", `some of its cards to ${dw(t.opens)} · ${t.name || "?"}`), ["date", t.id]);
        }
        default:
          say("That isn't something this page can do yet.");
          push();
          return false;
      }
    }

    // ---- what each click does (the page's c names: webface.c_<name>) ----
    const C = {};
    C.ready = () => { F.ready = true; push(); };
    C.close = () => goTo("/plans");
    C.follow_plan = () => goTo("/plans");
    C.new_plan = () => goTo("/plans/new");
    C.pick_plan = ({ pid }) => {
      if (B && pid === plan().id) { if (F.newSt) { F.newSt = null; push(); } return; }
      const p = F.plans.find((x) => x.id === pid);
      if (p) goTo(isAuthor(p) ? `/plans/${pid}/edit` : `/plans/${pid}`);
    };
    C.tab = ({ tab }) => { if (["plan", "insights", "settings"].includes(tab) && B) { F.tab = tab; push(); } };

    // -- Undo, and the changes waiting --
    C.undo = ({ what }) => {
      if (!Array.isArray(what) || !what.length) return;
      if (what[0] === "take") takeBack();
      else if (what[0] === "undo") undoSave();
      else if (what[0] === "history") C.tabcmd({ name: "history" });
    };
    function takeBack() {
      if (!F.changes.length || !B.undos || F.busy) return;
      F.changes.pop();
      B.undo();  // the builder's step back (its draw is this page's push)
      if (!F.changes.length) F.hold = false;
      say("Taken back.");
      push();
    }
    async function undoSave(version = F.undoable) {
      if (!version || F.busy) return;
      F.busy = true; say("Undoing…"); push();
      try {
        const r = await api("POST", `/plans/${B.id}/undo`, { version });
        F.undoable = null; F.sent = null; F.busy = false;
        took(r, "Undone.");
      } catch (err) {
        F.busy = false; F.undoable = null;
        say(err && err.status === 409 ? "Someone saved this plan since, so there's nothing of yours to undo now." : "That didn't undo. Try again.");
        push();
      }
    }
    C.undo_key = () => {
      if (!author() || F.busy) return;
      if (F.changes.length) return takeBack();
      if (F.undoable && !F.sent) return undoSave();
      if (out.openUndo) out.openUndo();
    };
    C.discard = ({ sure } = {}) => {
      if (!F.changes.length) return;
      if (!sure) { ask(`Discard ${pl(F.changes.length, "change")}?`, "They were never sent: nobody saw them.", "Discard", "discard", {}, true); return; }
      B.reload(B.base);
      F.changes = []; F.hold = false; F.deck.dirty = false;
      say("Discarded.");
      push();
    };
    /** a send's line to followers, from its changes (ops.why_line): "Shock moved from Wed 21 to Thu 22; Valve disease added." */
    function whyLine(cs) {
      const bits = cs.map((x) => {
        const i = x.what.indexOf(" · "), dayw = i >= 0 ? x.what.slice(0, i) : "", name = i >= 0 ? x.what.slice(i + 3) : x.what, d = x.detail || "";
        if (x.verb === "Moved" && d.startsWith("from ") && dayw) return `${name} moved ${d} to ${dayw}`;
        if (x.verb === "Moved") return `${x.what} moved ${d}`.trim();
        if (x.verb === "Laid out") return `${x.what} laid out ${d}`.trim();
        if (x.verb === "Gone") return `${name} taken off`;
        if (x.verb === "Tested on") return d !== "nothing" ? `${name} now for ${d}` : `${name} for no quiz now`;
        if (["Added", "Split", "Renamed"].includes(x.verb)) return `${name} ${x.verb.toLowerCase()}`;
        return `${name} changed`;
      });
      let line = "";
      for (const b of [...new Set(bits)]) { const nxt = (line ? `${line}; ` : "") + b; if (nxt.length + 1 > WHY_MAX) break; line = nxt; }
      return line ? `${line[0].toUpperCase()}${line.slice(1)}.` : "";
    }
    function sendView() {
      const n = F.changes.length, f = others(plan());
      const rows2 = F.changes.map((c, i) => ({ i: i === n - 1 && B.undos > 0 ? i : null, verb: c.verb, what: c.what, detail: c.detail || "", who: "", warn: false, ai: false }));
      return { kind: "send", title: f ? `Send ${pl(n, "change")} to ${f.toLocaleString()} following` : `Save ${pl(n, "change")}`, rows: rows2,
        why: whyLine(F.changes), max: WHY_MAX, yes: f ? `Send to ${f.toLocaleString()}` : "Save", cmd: "send" };
    }
    C.review_send = () => { if (F.changes.length && !F.busy) sheet(sendView()); };
    C.take_change = ({ i, again }) => {
      if (Number(i) !== F.changes.length - 1) return;  // the last one: a step back of the builder's
      takeBack();
      if (again && F.changes.length) sheet(sendView());
    };
    C.send = ({ why } = {}) => saveNow(true, why);

    // -- picking --
    C.pick = ({ key }) => {
      if (!Array.isArray(key) || key.length < 2) return;
      F.picked = key.slice(0, 2);
      if (F.side === "deck") { if (key[0] === "date" && F.deck.target) F.deck.target = key[1]; else if (key[0] !== "date") F.side = "panel"; }
      push();
    };

    // -- a set --
    C.rename = ({ uid, name }) => {
      const u = unit(uid), v = norm(name).slice(0, 60);
      if (!u || !v || v === u.name) return;
      const was = u.name;
      change(() => { B.nameIt(u, v); }, ["Renamed", `${dw(u.opens)} · ${v}`, `was ${was || "?"}`], ["date", uid]);
    };
    C.move = ({ uid, to, sure }) => {
      const u = unit(uid);
      if (!u || !to || to === u.opens) return;
      const other = units().find((x) => x.opens === to && x.id !== uid);
      if (other && !sure) {
        ask(`${fmt(to)} has ${other.name || "a set"} already`, "Put this one on that day too? Followers see both.", "Put it on", "move", { uid, to });
        push();
        return;
      }
      const from = u.opens;
      change(() => { B.shiftUnit(u, Sched.diff(to, u.opens)); B.byOpens(); }, () => setW(u, "Moved", `from ${dw(from)}`), ["date", uid]);
    };
    C.set_due = ({ uid, due }) => { const u = unit(uid); if (u && (due || null) !== (u.due || null)) op({ op: "set_due", date: uid, due }); };
    C.set_for = ({ uid, eid }) => {
      const u = unit(uid);
      if (!u) return;
      if (eid === "new") { C.new_event_form({ for_uid: uid }); return; }
      if ((eid || null) === (u.for || null)) return;
      change(() => { if (eid) u.for = eid; else delete u.for; }, setW(u, "Tested on", eid ? (eventOf(eid) || {}).name || "?" : "nothing"), ["date", uid]);
    };
    C.nudge = ({ k }) => {
      if (!author() || !F.picked) return;
      const d = Number(k) > 0 ? 1 : -1;
      if (F.picked[0] === "date") { const u = unit(F.picked[1]); if (u) C.move({ uid: u.id, to: addDays(u.opens, d) }); }
      else if (F.picked[0] === "event") { const e = eventOf(F.picked[1]); if (e) C.move_event({ eid: e.id, to: addDays(e.day, d) }); }
    };
    C.op = ({ op: o }) => op(o);
    C.spread = ({ key, how, days: n }) => {
      const u = pickedUnit();
      if (!u || !tree() || !Array.isArray(key) || !["tag", "deck"].includes(key[0])) return;
      const k = srcKey(key), placed = B.placedKeys(), tot = B.eff(k, placed);
      const kids = B.kidsOf(k).filter((x) => !B.isPlaced(x, placed) && B.eff(x, placed) > 0);
      const cap = B.paceDaily() || 0;
      if (!how) {
        const rest = B.only(k);
        const parts = kids.slice(0, 6).map((x) => `${Tags.word(B.pathOf(x).split("::").pop())} ${B.eff(x, placed).toLocaleString()}`).join(" · ")
          + (kids.length > 6 ? ` · ${kids.length - 6} more` : "") + (kids.length && rest > 0 ? ` · the rest ${rest.toLocaleString()}` : "");
        const even = Math.max(2, cap ? Math.ceil(tot / cap) : 3);
        sheet({ title: `Spread ${B.label(k, placed)} · ${pl(tot, "card")}`,
          words: kids.length ? `By its tags (${parts}), ${cap ? `at ${cap.toLocaleString()} a day` : "one a study day"}; or evenly: give it a number of study days.`
            : "Evenly over a number of study days.",
          fields: [{ name: "days", label: kids.length ? "Study days (empty: by its tags)" : "Study days", type: "number", value: kids.length ? "" : String(even), hint: String(even) }],
          yes: "Spread it", cmd: "spread", args: { key, how: "ask" } });
        return;
      }
      const days = Math.round(Number(n) || 0);
      if (how === "ask" && !days && !kids.length) return;
      change(() => {
        if (days >= 2 || !kids.length) {
          B.takeOut(u, k);
          const e = B.evenUnit(u.opens, k, Math.max(2, Math.min(60, days || 2)));
          if (!e) return false;
          B.note = `Spread evenly over ${fmt(e.opens)} to ${fmt(e.due || e.opens)}.`;
        } else {
          B.takeOut(u, k);
          const items = kids.map((x) => ({ key: x, n: B.eff(x, placed) }));
          const rest = B.only(k);
          if (rest > 0) items.push({ key: k, n: rest, rest: true, even: !!cap && rest > cap });
          const r = B.fill(items, u.opens, null, cap);
          const leftN = r.left.reduce((a, x) => a + x.n, 0);
          B.note = `Spread over ${fmt(B.firstStudy(u.opens))} to ${fmt(r.lastD || u.opens)}.${leftN ? ` ${leftN.toLocaleString()} didn't fit: ${B.leftNames(r.left)}.` : ""}`;
        }
        B.cleanup(); B.renameAll(); B.byOpens();
      }, ["Split", `${dw(u.opens)} · ${B.label(k, placed)}`, ""], ["date", u.id]);
    };
    C.spread_heavy = ({ kind, path, uid }) => { F.picked = ["date", uid]; C.spread({ key: [kind, path] }); };
    C.set_cut = ({ tag, ptag }) => {
      const u = pickedUnit();
      if (u) change(() => { B.setCut(u, tag, ptag || null); B.renameAll(); }, setW(u, "Changed", ptag ? `a tag kept to ${(B.ptags().find((x) => x.id === ptag) || {}).name || "a tag"}` : "all of a tag again"), ["date", u.id]);
    };
    C.keep_only = ({ ptag }) => {
      const u = pickedUnit();
      if (!u) return;
      const tags = (u.tags || []).filter((t) => !B.isOwnTag(t));
      if (tags.length) change(() => { for (const t of tags) B.setCut(u, t, ptag); B.renameAll(); }, setW(u, "Changed", `kept to ${(B.ptags().find((x) => x.id === ptag) || {}).name || "a tag"}`), ["date", u.id]);
    };
    C.remark = ({ path, text }) => {
      const had = B.tagRemark(path);
      if (text === undefined || text === null) {
        sheet({ title: "A note for followers", words: `On ${tagLabel(path)}, shown in their Anki when it comes up. Empty takes it off.`,
          fields: [{ name: "text", value: String((had || {}).text || ""), max: Remarks.TEXT }], yes: "Save the note", cmd: "remark", args: { path } });
        return;
      }
      change(() => { B.setTagRemark(path, text); }, ["Note", tagLabel(path), norm(text) ? "for followers" : "taken off"]);
    };
    function sourceAt(i) {
      const u = pickedUnit(), rs = u ? rows(u) : [];
      const k = Number(i);
      return u && Number.isInteger(k) && k >= 0 && k < rs.length ? [u, rs[k].key] : [null, null];
    }
    C.move_source_form = ({ i, day }) => {
      const [u, key] = sourceAt(i);
      if (!u) return;
      if (day === undefined || day === null) {
        sheet({ title: "Move it to a day", words: "That day's set takes it, or it gets a set of its own there.",
          fields: [{ name: "day", type: "date", value: u.opens || "" }], yes: "Move it", cmd: "move_source_form", args: { i } });
        return;
      }
      if (!/^\d{4}-\d\d-\d\d$/.test(String(day)) || day === u.opens) return;
      change(() => {
        const t = B.unitOn(day);
        if (!t || !putSource(t, u, key)) return false;
        takeSource(u, key);
        B.cleanup(); B.renameAll(); B.byOpens();
      }, setW(u, "Moved", `some of its cards to ${dw(day)}`), ["date", u.id]);
    };
    /** a source as an Anki search, to paste into Browse (model.source_search) */
    function sourceSearch(u, key) {
      if (key[0] === "tag") return Tags.ankiSearch("tag", key[1]);
      if (key[0] === "deck") return Tags.ankiSearch("deck", key[1]);
      if (key[0] === "cut") { const c = (u.cut || []).find((x) => x.tag === key[1] && x.in === key[2]); return c && c.q ? String(c.q) : null; }
      if (key[0] === "search") return String(key[1]);
      if (key[0] === "questions") { const qs = (key[1] || []).map((t) => Tags.ankiSearch("tag", t)); return qs.length > 1 ? `(${qs.join(" OR ")})` : qs[0] || null; }
      return null;
    }
    C.copy_source = ({ i }) => {
      const [u, key] = sourceAt(i);
      if (!u) return;
      const q = sourceSearch(u, key);
      if (!q) { say("Its cards are picked one by one: in Anki, Browse finds them."); return; }
      copy(q, "Copied: its search, for Anki's Browse.");
    };
    C.copy_search = () => {
      const u = pickedUnit();
      if (!u) return;
      const parts = [...(u.tags || []).map((t) => Tags.ankiSearch("tag", t)), ...(u.decks || []).map((d) => Tags.ankiSearch("deck", d)), ...(u.search || []).map((q) => `(${q})`)];
      if (!parts.length) { say("Its cards are picked one by one: in Anki, Browse finds them."); return; }
      copy(parts.length > 1 ? parts.join(" OR ") : parts[0], "Copied: its search, for Anki's Browse.");
    };
    const anki = () => say("That's done in Anki, where your cards are: Tools › Due Crew › Plans.");
    C.browse = anki; C.study = anki; C.open_now = anki;
    C.delete = ({ sure } = {}) => {
      if (!author() || !F.picked) return;
      const [kind, k] = F.picked;
      if (kind === "date") {
        const u = unit(k);
        if (!u) return;
        if (!sure) {
          ask(`Delete ${fmt(u.opens)} · ${u.name || "?"}?`, (u.opens <= today0() ? "It comes off the plan. What opened stays open." : "It comes off the plan.")
            + (waiting() ? " With people following, it waits with your other changes till you send them." : ""), "Delete", "delete", {}, true);
          return;
        }
        const w = setW(u, "Gone");
        if (change(() => { B.doc.units = units().filter((x) => x !== u); if (B.doc.reviews) { B.doc.reviews = B.doc.reviews.filter((r) => r.from !== u.id && r.to !== u.id); if (!B.doc.reviews.length) delete B.doc.reviews; } }, w)) {
          F.picked = null; pickDefault(); push();
        }
      } else if (kind === "event") {
        const e = eventOf(k);
        if (!e) return;
        if (!sure) {
          const n = prep(e).length;
          ask(`Take ${e.name || "it"} off?`, n ? `${pl(n, "set")} lead${n === 1 ? "s" : ""} up to it; they stay, leading up to nothing.` : "It comes off the plan.", "Take it off", "delete", {}, true);
          return;
        }
        if (change(() => { B.takeEvent(e); }, ["Gone", `${dw(e.day)} · ${e.name || "?"}`])) { F.picked = null; pickDefault(); push(); }
      } else if (kind === "review") {
        const r = reviewOf(k);
        if (r && change(() => { B.doc.reviews = B.doc.reviews.filter((x) => x !== r); if (!B.doc.reviews.length) delete B.doc.reviews; }, ["Gone", `${dw(k)} · Review`])) {
          F.picked = null; pickDefault(); push();
        }
      }
    };
    C.move_from = ({ days } = {}) => {
      const u = pickedUnit();
      if (!u) return;
      const after = units().filter((x) => x.opens > u.opens);
      if (days === undefined || days === null) {
        sheet({ title: after.length ? `Move ${u.name || "this set"} and the ${pl(after.length, "set")} after it` : `Move ${u.name || "this set"}`,
          words: "How many days later (a minus for earlier). Their finish-by days move with them.",
          fields: [{ name: "days", type: "number", value: "7" }], yes: "Move them", cmd: "move_from" });
        return;
      }
      const n = Math.round(Number(days) || 0);
      if (!n) return;
      change(() => { for (const x of [u, ...after]) B.shiftUnit(x, n); B.byOpens(); },
        () => setW(u, "Moved", `${pl(Math.abs(n), "day")} ${n > 0 ? "later" : "earlier"}${after.length ? `, the ${pl(after.length, "set")} after it too` : ""}`), ["date", u.id]);
    };
    /** a search, IDs or picks onto the picked set (builder.js's searchBox rules) */
    C.add_search = ({ text } = {}) => {
      const u = pickedUnit();
      if (!u) return;
      if (text === undefined) {
        sheet({ title: `Add cards to ${fmt(u.opens)}`, words: "An Anki search, note IDs, or notes:… or cards:… as Anki's browser copies them (Due Crew › Copy as plan selector). Your Anki counts them at its next refresh.",
          fields: [{ name: "text", type: "area", max: 20000, value: "" }], yes: "Add them", cmd: "add_search" });
        return;
      }
      const t = String(text || "").trim();
      if (!t) return;
      if (/^(notes|cards):/i.test(t)) {
        const r = Picks.take(t.replace(/\s+/g, " "));
        if (r.bad.length || !(r.notes.length || r.cards.length)) { say("That doesn't read as notes:… or cards:…"); return; }
        change(() => {
          const notes = [...new Set([...(u.notes || []), ...r.notes])];
          if (notes.length > 5000) { B.note = "A set takes up to 5,000 notes."; return false; }
          if (r.notes.length) { u.notes = notes; delete u.idn; }
          const have = new Set((u.cards || []).map(([g, x]) => `${g}:${x}`));
          u.cards = [...(u.cards || []), ...r.cards.filter(([g, x]) => !have.has(`${g}:${x}`))];
          B.renameAll();
        }, setW(u, "Changed", "cards picked"), ["date", u.id]);
        return;
      }
      if (/^[\d\s,;]+$/.test(t)) {
        const ids = [...new Set(t.split(/[\s,;]+/).filter(Boolean).map(Number))].filter((x) => Number.isSafeInteger(x) && x > 0);
        change(() => {
          const all = [...new Set([...(u.nids || []), ...ids])];
          if (all.length > 5000) { B.note = "A set takes up to 5,000 IDs of each kind."; return false; }
          u.nids = all; delete u.idn;
          B.renameAll();
        }, setW(u, "Changed", "note IDs added"), ["date", u.id]);
        return;
      }
      if (t.length > 500) { say("A search is at most 500 characters."); return; }
      if (PERSONAL.test(t)) { say("That finds different cards in each person's Anki. Use tags or decks."); return; }
      change(() => { if (!B.addSearch(u, t)) return false; B.renameAll(); }, setW(u, "Changed", "a search added"), ["date", u.id]);
    };
    /** "watch: Lecture 14 https://…", one a line (builder.js's Todo) */
    const todoLines = (text) => String(text || "").split("\n").map((l) => /^\s*(watch|read|do)\s*[:-]\s*(.+)$/i.exec(l)).filter(Boolean).map((m) => Todo.parse(m[1], m[2]));
    C.todo = ({ text } = {}) => {
      const u = pickedUnit();
      if (!u) return;
      if (text === undefined) {
        sheet({ title: `To do on ${fmt(u.opens)}`, words: `One a line, up to ${Todo.MAX}: watch:, read: or do:, its words, and a link if it has one.`,
          fields: [{ name: "text", type: "area", max: 2000, value: (u.todo || []).map((x) => `${x.k}: ${x.t}${x.url ? ` ${x.url}` : ""}`).join("\n"),
            hint: "watch: Lecture 14 https://…" }], yes: "Save", cmd: "todo" });
        return;
      }
      const lines = Todo.clean(todoLines(text));
      change(() => { if (lines.length) u.todo = lines; else delete u.todo; }, setW(u, "Changed", "its to-dos"), ["date", u.id]);
    };
    C.todo_off = ({ i }) => {
      const u = pickedUnit(), lines = (u && u.todo) || [];
      if (u && i >= 0 && i < lines.length) change(() => { u.todo = lines.filter((_x, j) => j !== Number(i)); if (!u.todo.length) delete u.todo; }, setW(u, "Changed", "a to-do taken off"), ["date", u.id]);
    };

    // -- new sets, quizzes, review days --
    function afterPicked() {
      const u = pickedUnit();
      if (u) return B.nextStudy(u.opens);
      const ld = B.lastDay();
      return B.firstStudy(ld ? addDays(ld, 1) : today0());
    }
    C.new_date_form = () => {
      if (!author()) return;
      sheet({ title: "A new set", words: "Its name as followers see it, and the day its cards open.",
        fields: [{ name: "name", label: "Name", value: "", max: 60 }, { name: "day", label: "Opens", type: "date", value: afterPicked() }], yes: "Put it on", cmd: "new_date" });
    };
    C.new_date = ({ name, day, sure }) => {
      const v = norm(name).slice(0, 60);
      if (!v || !day) return;
      const other = units().find((x) => x.opens === day);
      if (other && !sure) { ask(`${fmt(day)} has ${other.name || "a set"} already`, "Put this one on that day too? Followers see both.", "Put it on", "new_date", { name: v, day }); return; }
      if (units().length >= B.LIMITS.UNITS_MAX) { say(B.LIMITS.FULL); return; }
      const u = { id: uid8(), name: v, opens: day, tags: [], decks: [], cards: [] };
      if (change(() => { B.doc.units.push(u); B.byOpens(); }, ["Added", `${dw(day)} · ${v}`], ["date", u.id])) {
        F.picked = ["date", u.id];
        F.side = "deck"; F.deck.target = u.id;  // its cards next: the deck beside it, ticks adding to it
        push();
      }
    };
    C.new_event_form = ({ for_uid } = {}) => {
      if (!author()) return;
      const u = for_uid ? unit(for_uid) : null;
      sheet({ title: "A quiz, exam or day", words: "Sets before it can lead up to it.",
        fields: [{ name: "name", label: "Name", value: "", max: 60, hint: "Cardio quiz 1, Block 2 exam, a lecture" },
          { name: "day", label: "Day", type: "date", value: u ? addDays(u.opens, 3) : afterPicked() }],
        yes: "Put it on", cmd: "new_event", args: { for_uid: for_uid || null } });
    };
    C.new_event = ({ name, day, for_uid }) => {
      const v = norm(name).slice(0, 60);
      if (!v || !day) return;
      let ev = null;
      change(() => {
        ev = B.addEvent(day, v);
        if (!ev) return false;
        const u = for_uid ? unit(for_uid) : null;
        if (u) u.for = ev.id;
      }, ["Added", `${dw(day)} · ${v}`], for_uid ? ["date", for_uid] : null);
      if (ev && !for_uid) { F.picked = ["event", ev.id]; push(); }
    };
    C.rename_event = ({ eid, name }) => {
      const e = eventOf(eid), v = norm(name).slice(0, 60);
      if (e && v && v !== e.name) { const was = e.name; change(() => { e.name = v; }, ["Renamed", `${dw(e.day)} · ${v}`, `was ${was || "?"}`], ["event", eid]); }
    };
    C.move_event = ({ eid, to }) => {
      const e = eventOf(eid);
      if (e && to && to !== e.day) { const from = e.day; change(() => { e.day = to; B.doc.events.sort((a, b) => a.day.localeCompare(b.day)); }, ["Moved", `${dw(to)} · ${e.name || "?"}`, `from ${dw(from)}`], ["event", eid]); }
    };
    C.new_review_form = () => {
      if (!author()) return;
      sheet({ title: "A review day", words: "The morning followers get a deck of what they've seen so far.",
        fields: [{ name: "day", label: "Day", type: "date", value: afterPicked() }], yes: "Next", cmd: "review_day" });
    };
    C.review_day = ({ day, from, to }) => {
      const before = byOpens().filter((u) => u.opens <= day);
      if (!before.length) { say("A review day comes after the sets it reviews: none open by then."); return; }
      const r = reviewOf(day);
      if (from === undefined) {
        const was = r ? [unit(r.from), unit(r.to)] : [before[Math.max(0, before.length - 5)], before[before.length - 1]];
        sheet({ title: `Review day · ${fmt(day)}`, words: `It reviews the sets that opened from one day to another, ${fmt(before[0].opens)} at the earliest. Empty takes the review day off.`,
          fields: [{ name: "from", label: "From the set on", type: "date", value: (was[0] || before[0]).opens }, { name: "to", label: "To the set on", type: "date", value: (was[1] || before[before.length - 1]).opens }],
          yes: r ? "Change it" : "Make it a review day", cmd: "review_day", args: { day } });
        return;
      }
      if (!from || !to) {
        if (r) change(() => { B.doc.reviews = B.doc.reviews.filter((x) => x !== r); if (!B.doc.reviews.length) delete B.doc.reviews; }, ["Gone", `${dw(day)} · Review`]);
        return;
      }
      const [lo, hi] = [from, to].sort();
      const a = before.find((u) => u.opens >= lo), b = before.filter((u) => u.opens <= hi).pop();
      if (!a || !b || a.opens > b.opens) { say("No set opens between those days."); return; }
      if (!r && (B.doc.reviews || []).length >= B.LIMITS.REVIEWS_MAX) { say(`A plan holds up to ${B.LIMITS.REVIEWS_MAX} review days.`); return; }
      if (change(() => { if (r) { r.from = a.id; r.to = b.id; } else (B.doc.reviews ||= []).push({ day, from: a.id, to: b.id }); }, [r ? "Changed" : "Added", `${dw(day)} · Review`, `${a.name || "?"}${a !== b ? ` – ${b.name || "?"}` : ""}`], ["review", day])) {
        F.picked = ["review", day]; push();
      }
    };

    // -- the deck beside the plan --
    C.deck = ({ uid } = {}) => {
      if (!author()) return;
      if (!tree()) { F.side = "deck"; push(); return; }
      if (uid) F.picked = ["date", uid];
      F.deck.target = uid || null;
      F.side = "deck";
      push();
    };
    C.deck_done = () => { const uid = F.deck.target; F.deck.target = null; F.side = "panel"; if (uid) F.picked = ["date", uid]; push(); };
    C.deck_view = ({ view: v }) => { if (VIEWS.some(([k]) => k === v)) { F.deck.view = v; push(); } };
    C.deck_find = ({ text }) => { F.deck.find = String(text || "").slice(0, 80); push(); };
    C.deck_open = ({ key, on = true }) => { if (on) F.deck.opened.add(key); else F.deck.opened.delete(key); push(); };
    C.deck_tick = ({ key, on }) => {
      if (F.busy || !key || !tree()) return;
      const st = F.deck;
      if (st.target) {
        const u = unit(st.target);
        if (!u) return;
        const k = String(key), kind = B.kindOf(k), path = B.pathOf(k);
        if (on) change(() => { const f = kind === "tag" ? "tags" : "decks"; if ((u[f] || []).length >= B.LIMITS.SOURCES_MAX) { B.note = `A set holds up to ${B.LIMITS.SOURCES_MAX} ${f === "tags" ? "tags" : "subdecks"}.`; return false; } u[f] = [...new Set([...(u[f] || []), path])]; B.renameAll(); },
          () => setW(u, "Changed", `${tagLabel(path)} added`), ["date", u.id]);
        else change(() => { B.takeOut(u, k); B.renameAll(); }, () => setW(u, "Changed", `${tagLabel(path)} taken off`), ["date", u.id]);
        return;
      }
      // what the plan covers: ticked here, kept till it's laid out or saved
      const all = inView(key), was = covered(key) || (all.length > 1 && all.every(covered));
      if (was && all.length > 1) for (const x of all) B.cover.delete(x);
      else if (B.cover.has(key)) B.cover.delete(key);
      else if (!covered(key)) for (const x of all) { for (const c of [...B.cover]) if (B.under(x, c)) B.cover.delete(c); B.cover.add(x); }
      st.dirty = true;
      push();
    };
    C.deck_lay = ({ how, upto }) => {
      if (!Array.isArray(how) || how.length < 3 || F.busy) return;
      const [mode, weekAhead, fitting] = how;
      const ev = upto ? eventOf(upto) : null;
      const until = fitting ? fitting[0] : ev ? addDays(ev.day, -1) : null;
      const wasEnd = B.doc.end, had = new Set(units().map((u) => u.id)), unitsWas = JSON.stringify(units());
      const laid = () => { const us = byOpens().filter((u) => !had.has(u.id)); return us.length ? ["Laid out", pl(us.length, "new set"), `${fmt(us[0].opens)} to ${fmt(us[us.length - 1].due || us[us.length - 1].opens)}`] : ["Laid out", "What's ticked", ""]; };
      if (change(() => {
        B.pace = { ...B.pace, mode: mode === "end" ? "end" : "daily" };
        if (until) { B.doc.end = until; B.aimFor = fitting ? fitting[1] : ev ? ev.id : null; }
        try { B.layOut(!!weekAhead); } finally {
          if (until) { if (wasEnd) B.doc.end = wasEnd; else delete B.doc.end; B.aimFor = null; }
        }
        if (JSON.stringify(units()) === unitsWas) return false;  // nothing went on a day: B.note says why
      }, laid)) F.deck.dirty = false;
    };
    C.deck_week = () => C.deck_lay({ how: ["daily", true, null] });
    C.deck_keep = () => {
      if (change(() => { B.pace = { ...B.pace, cover: B.coverItems().slice(0, 500) }; B.doc.pace = { ...(B.doc.pace || {}), cover: B.coverItems().slice(0, 500) }; },
        ["Changed", "What the plan covers"])) F.deck.dirty = false;
    };
    C.lesson_from = ({ key, day, sure }) => {
      if (F.busy || !key || !author()) return;
      const kind = B.kindOf(String(key));
      if (kind !== "tag" && kind !== "deck") return;
      if (day === null || day === undefined) {
        sheet({ title: "A set of its own", words: `${tagLabel(B.pathOf(key))}, on a day.`, fields: [{ name: "day", type: "date", value: today0() }],
          yes: "Add it", cmd: "lesson_from", args: { key } });
        return;
      }
      const d = day === "next" ? B.firstStudy(B.lastDay() ? addDays(B.lastDay(), 1) : planStart() > today0() ? planStart() : today0()) : String(day);
      if (units().length >= B.LIMITS.UNITS_MAX) { say(B.LIMITS.FULL); return; }
      const u = { id: uid8(), name: "", opens: d, tags: kind === "tag" ? [B.pathOf(key)] : [], decks: kind === "deck" ? [B.pathOf(key)] : [], cards: [] };
      if (change(() => { B.doc.units.push(u); B.auto.add(u.id); B.renameAll(); B.byOpens(); }, () => ["Added", `${dw(d)} · ${u.name}`], ["date", u.id])) {
        F.picked = ["date", u.id]; push();
      }
    };
    C.breather = ({ sure } = {}) => {
      if (F.busy || !author()) return;
      const t0 = today0(), ahead = units().filter((u) => u.opens > t0);
      if (!sure) {
        if (!ahead.length) { say("Nothing is still to come to move."); return; }
        ask("Give everyone a day?", `The ${pl(ahead.length, "set")} still to come move a study day later, their finish-by days and review days with them. Quizzes and exams stay.`, "Move them", "breather");
        return;
      }
      change(() => {
        for (const u of ahead) B.shiftUnit(u, Sched.diff(B.nextStudy(u.opens), u.opens));
        for (const r of B.doc.reviews || []) if (r.day > t0) r.day = B.nextStudy(r.day);
        B.byOpens();
      }, ["Moved", `${pl(ahead.length, "set")} still to come`, "a study day later"]);
    };
    C.ptag_rename = ({ ptag, name }) => {
      const t = B.ptags().find((x) => x.id === ptag);
      if (!t) return;
      if (name === undefined || name === null) {
        sheet({ title: "Rename the tag", words: "Its name (40 characters); the sets, searches and notes using it change with it.",
          fields: [{ name: "name", value: String(t.name || ""), max: 40 }], yes: "Rename", cmd: "ptag_rename", args: { ptag } });
        return;
      }
      const v = norm(name).slice(0, 40);
      if (!v || v === t.name) return;
      const clash = B.ptagByName(v);
      if (clash && clash !== t) { say(`There's a tag called ${clash.name} already.`); return; }
      const path = B.ptagPath(t);
      const was = t.name;
      change(() => { t.name = v; B.retag(path, B.ptagPath(t)); }, ["Renamed", `The tag ${v}`, `was ${was}`]);
    };
    C.ptag_delete = ({ ptag, sure }) => {
      const t = B.ptags().find((x) => x.id === ptag);
      if (!t) return;
      if (!sure) { ask(`Delete ${t.name || "the tag"}?`, `${B.dropSay(t)} Followers' Anki takes it off their notes.`, "Delete it", "ptag_delete", { ptag }, true); return; }
      const path = B.ptagPath(t);
      change(() => { B.putTags(B.ptags().filter((x) => x !== t)); B.retag(path, null); }, ["Gone", `The tag ${t.name}`]);
    };
    C.card_note_off = ({ rid }) => {
      if (B.remarks().some((r) => r.id === rid)) change(() => { B.putRemarks(B.remarks().filter((r) => r.id !== rid)); }, ["Took off", "A note on a card"]);
    };

    // -- paste, the plan as text, AI prompts --
    C.paste = ({ text, sure }) => {
      const t = String(text || "");
      if (!t.trim()) return;
      const r = B.fromText(t, false);
      if (r.errors.length) { say(r.errors.slice(0, 2).join(" ")); return; }
      if (!(r.units.length || r.events.length || r.tags.length || r.remarks.length)) {
        say("Nothing in that reads as plan lines: a set's line starts with its day (2026-11-02 | Cell injury | tag:…).");
        return;
      }
      if (!sure) {
        const joins = (u) => units().some((x) => x.id === u.id);
        const lines = [...r.tags.map((x) => `Tag: ${x.name}`), ...r.events.map((e) => `${fmt(e.day)} · ${e.name}`),
          ...r.units.slice().sort((a, b) => a.opens.localeCompare(b.opens)).map((u) => `${fmt(u.opens)} · ${u.name}${joins(u) ? " (adds to this set)" : ""}`),
          ...r.remarks.map((x) => `Note: ${x.text}`)];
        sheet({ kind: "read", title: "The changes these lines make",
          words: [`${pl(r.units.length, "set")}${r.events.length ? `, ${pl(r.events.length, "quiz or exam", "quizzes or exams")}` : ""}${r.tags.length ? `, ${pl(r.tags.length, "tag")}` : ""}.`,
            r.missing.length ? `Not in your deck (they'd find nothing): ${r.missing.slice(0, 5).map((k) => B.pathOf(k)).join(", ")}${r.missing.length > 5 ? "…" : ""}` : "",
            r.warns.slice(0, 2).join(" ")].filter(Boolean).join(" "),
          text: lines.join("\n"), yes: "Add to the plan", cmd: "paste", args: { text: t } });
        return;
      }
      if (change(() => {
        // builder.js's Add dates (its text tab's use(false)): new sets on, a set's own line adds to it
        if (r.events.length) { const keep = B.events().filter((x) => !r.events.some((y) => y.id === x.id)); B.doc.events = [...keep, ...r.events].sort((a, b) => a.day.localeCompare(b.day)); }
        for (const u of r.units) {
          const x = units().find((y) => y.id === u.id);
          if (!x) { B.doc.units.push(u); continue; }
          for (const c of u.cut || []) if (!(x.cut || []).some((y) => y.tag === c.tag && y.in === c.in)) x.cut = [...(x.cut || []), c];
          for (const k of ["tags", "decks", "search", "nids", "cids", "notes"]) if ((u[k] || []).length) { x[k] = [...new Set([...(x[k] || []), ...u[k]])]; if (k === "nids" || k === "cids" || k === "notes") delete x.idn; }
          const have = new Set((x.cards || []).map(([g, o2]) => `${g}:${o2}`));
          x.cards = [...(x.cards || []), ...(u.cards || []).filter(([g, o2]) => !have.has(`${g}:${o2}`))];
          for (const k of ["due", "even", "for"]) if (u[k]) x[k] = u[k];
          if ((u.todo || []).length) { const had = new Set((x.todo || []).map((y) => `${y.k}:${y.t.toLowerCase()}`)); x.todo = [...(x.todo || []), ...u.todo.filter((y) => !had.has(`${y.k}:${y.t.toLowerCase()}`))].slice(0, Todo.MAX); }
        }
        if (r.remarks.length) {
          const list = B.remarks().map((y) => ({ ...y }));
          for (const x of r.remarks) { const y = list.find((z) => Remarks.same(x, z)); if (y) y.text = x.text; else list.push({ id: uid8(), ...x }); }
          B.putRemarks(list);
        }
        if (r.tags.length) {
          const list = B.ptags().map((x) => structuredClone(x));
          for (const x of r.tags) {
            const y = list.find((z) => z.id === x.id);
            if (!y) { list.push(x); continue; }
            for (const k of ["notes", "tags", "decks", "search"]) if ((x[k] || []).length) y[k] = [...new Set([...(y[k] || []), ...x[k]])];
          }
          B.putTags(list);
        }
        B.syncCuts(); B.byOpens();
      }, ["Added", `${pl(r.units.length, "set")} from plan lines`])) { if (out.pasted) out.pasted(); }
    };
    /** Add to my calendar (webface.c_calendar): the plan as it shows here as a calendar file (Ics, ics.py's twin):
     *  an author's with the changes waiting, mine on my days without the sets I skip; each set's cards as counted here */
    C.calendar = () => {
      if (!B) return;
      const p = plan(), counts = {}, placed = B.placedKeys();
      for (const u of units()) { const n = author() ? (tree() ? B.unitTotal(u, placed) : 0) : (progOf(u) || [0, 0, 0])[2]; if (n) counts[u.id] = n; }
      const text = Ics.calendar(p.id || "plan", p.name, B.doc, counts, author() ? [] : follow().skipped || []);
      const url = typeof Blob === "function" && typeof URL === "function" && URL.createObjectURL
        ? URL.createObjectURL(new Blob([text], { type: "text/calendar" })) : `data:text/calendar;charset=utf-8,${encodeURIComponent(text)}`;
      if (out.download) out.download(url, Ics.fileName(p.name), text);
      say("Saved. Open the file to add the plan to your calendar.");
    };
    C.text = () => sheet({ kind: "read", title: "The plan as text", words: "Every set, quiz and tag as plan lines (the builder's format: duecrew.com/plan-text).",
      text: B.toText(), yes: "Copy it", cmd: "copy_text" });
    C.copy_text = () => copy(B.toText(), "Copied: the plan as text.");
    const promptText = (which) => (!tree() ? null : which === "plan" ? B.aiPrompt() : B.tagPrompt());
    C.prompt = ({ which }) => {
      const t = promptText(which);
      if (!t) { say("The plan's deck hasn't come from your Anki yet: a prompt needs its tags."); return; }
      copy(t, "Copied. Paste it in your AI; paste what it answers in the box below, then Show the changes. It has the deck's tag names and counts, never a card.");
    };
    C.see_prompt = ({ which }) => {
      const t = promptText(which);
      if (!t) { say("The plan's deck hasn't come from your Anki yet: a prompt needs its tags."); return; }
      sheet({ kind: "read", title: "The prompt, as your AI gets it", text: t, yes: "Copy it", cmd: "prompt", args: { which } });
    };

    // -- notes on a day (one request each) --
    C.note_add = async ({ day, text }) => {
      const t = norm(text).slice(0, 280);
      if (!t) return;
      try {
        const r = await api("POST", `/plans/${B.id}/notes`, { day, text: t });
        B.notes = [...(B.notes || []), { id: r.id, uid: me && me.uid, name: "You", day, text: r.text || t, at: Date.now() / 1000, mine: true, remove: true }];
        push();
      } catch (err) {
        failed(err, { too_many_notes: "That's as many notes as this plan holds from you. Remove one first.", authors_only: "On a plan in the library, only its authors write notes." });
      }
    };
    C.note_off = async ({ nid }) => {
      const x = (B.notes || []).find((y) => y.id === nid);
      if (!x || !x.remove) return;
      try { await api("DELETE", `/plans/${B.id}/notes/${nid}`); B.notes = B.notes.filter((y) => y !== x); push(); } catch { say("That note didn't go. Try again."); }
    };

    // ---- Insights' and Settings' own clicks (webtabs.c_<name>, the page's tabcmd) ----
    const T = {};
    C.tabcmd = ({ name, args, ...more }) => {
      const fn = T[String(name)];
      if (fn) fn({ ...(args && typeof args === "object" ? args : {}), ...more });
    };
    T.go = ({ key }) => {
      if (!Array.isArray(key) || key.length < 2 || !((key[0] === "date" && unit(key[1])) || (key[0] === "event" && eventOf(key[1])))) return;
      F.tab = "plan"; F.picked = key.slice(0, 2); F.side = "panel"; push();
    };
    T.map_by = () => push();  // one way here: the deck's tags under its own
    T.shape = ({ key, value }) => {
      if (!author()) return;
      const base = shapeBase(), v = { ...base, ...F.shape }, e = F.shape, iso10 = (s) => /^\d{4}-\d\d-\d\d$/.test(String(s || ""));
      if (key === "start" && iso10(value)) e.start = String(value);
      else if (key === "end" && (value === "day" || value === "none" || (String(value).startsWith("event:") && endOf({ end: value })))) e.end = String(value);
      else if (key === "end_day" && iso10(value)) e.end_day = String(value);
      else if (key === "day" && Number(value) >= 0 && Number(value) <= 6) { const d = v.days.slice(); d[Number(value)] = d[Number(value)] ? 0 : 1; if (d.some(Boolean)) e.days = d; }
      else if (key === "mode" && MODES.some(([k]) => k === value)) e.mode = value;
      else if (key === "daily" && Number(value) > 0) e.daily = Math.max(1, Math.min(5000, Math.round(Number(value))));
      else if (key === "taper" && Number(value) >= 0) e.taper = Math.max(0, Math.min(60, Math.round(Number(value))));
      else if (key === "catchup" && Number(value) >= 0 && Number(value) <= 52) e.catchup = Number(value);
      for (const k of Object.keys(e)) if (k !== "end_day" && JSON.stringify(e[k]) === JSON.stringify(base[k])) delete e[k];
      push();
    };
    T.shape_back = () => { F.shape = {}; push(); };
    T.shape_save = () => {
      const [base, v, changed] = shapeEdits();
      if (!changed || F.busy) return;
      if (change(() => { applyShape(base, v); }, ["Changed", "The plan's dates and pace"])) { F.shape = {}; push(); }
    };
    /** "watch: Practice questions | Mon, Wed": a line a row (builder.js's Every) */
    const everyLines = (text) => String(text || "").split("\n").map((l) => {
      const [what, when = ""] = l.split("|");
      const m = /^\s*(watch|read|do)\s*[:-]\s*(.+)$/i.exec(what || "");
      if (!m) return null;
      const w = when.trim().toLowerCase();
      const r = w === "every day" || w === "daily" ? "0123456" : w === "weekdays" ? "01234"
        : [...new Set(w.split(/[\s,]+/).map((x) => WEEK.findIndex((d) => d.toLowerCase() === x.slice(0, 3))).filter((i) => i >= 0))].sort().join("");
      return { ...Todo.parse(m[1], m[2]), r: r || "0" };
    }).filter(Boolean);
    T.every = ({ text } = {}) => {
      if (!author() || F.busy) return;
      if (text === undefined) {
        sheet({ title: "Every week", words: `Lines followers tick in Due on the same weekdays every week of the plan, up to ${Every.MAX}: watch:, read: or do:, its words, then | and its days (Mon, Wed; weekdays; every day).`,
          fields: [{ name: "text", type: "area", max: 2000, value: Every.clean(B.doc.every || []).map((x) => `${x.k}: ${x.t}${x.url ? ` ${x.url}` : ""} | ${[...x.r].map((k) => WEEK[Number(k)]).join(", ")}`).join("\n"),
            hint: "do: Practice questions | Mon, Wed" }], yes: "Save", cmd: "tabcmd", args: { name: "every" } });
        return;
      }
      const lines = Every.clean(everyLines(text));
      change(() => { if (lines.length) B.doc.every = lines; else delete B.doc.every; }, ["Changed", "Every week's lines"]);
    };
    /** a settings change that's the plan's own (PUT /plans/{id}, the version it read): saved now */
    async function putMeta(fields, summary, said) {
      if (F.busy) return;
      F.busy = true; push();
      const body = { version: plan().version, summary, ...fields };
      try {
        let r;
        try { r = await api("PUT", `/plans/${B.id}`, body); } catch (err) {
          if (err.status !== 409) throw err;
          const theirs = await api("GET", `/plans/${B.id}`);
          r = await api("PUT", `/plans/${B.id}`, { ...body, version: theirs.version });
        }
        F.busy = false;
        took(r, said);
      } catch (err) {
        F.busy = false;
        failed(err, { bad_name: "A plan needs a name.", bad_line: "The plan's one line is too long.", bad_squad: "You're not in that squad any more. Pick another.",
          not_owner: "Only the plan's owner changes who can follow it.", slow_down: "That's a lot of saves today. Try again tomorrow." });
      }
    }
    T.meta = ({ name, line }) => {
      if (!author() || F.busy) return;
      const n = norm(name).slice(0, 60), l = norm(line).slice(0, 120);
      if (n && (n !== plan().name || l !== (plan().line || ""))) putMeta({ name: n, line: l }, "renamed it", "Saved. Followers see the new name at their next refresh.");
    };
    T.deck_url = ({ url }) => {
      if (!author()) return;
      const v = String(url || "").trim().slice(0, 300);
      if (v === String(B.doc.deckUrl || "")) return;
      if (v && !deckLink(v)) { say("A link starts with https://, has no spaces or quotes, and is 300 characters at most."); push(); return; }
      change(() => { if (v) B.doc.deckUrl = v; else delete B.doc.deckUrl; }, ["Changed", "Where to get the deck"]);
    };
    T.who = ({ squad, audience }) => {
      if (!owner() || F.busy) return;
      const q = (B.squads || []).find((x) => squad && x.id === squad);
      const sq = q ? q.id : null, aud = audience === "squad" && sq ? "squad" : "code";
      if (sq === (plan().squad || null) && aud === (plan().audience || "code")) { push(); return; }
      putMeta({ audience: aud, squad: sq }, "who can follow", aud === "squad" ? `Only people in ${q.name} can follow it now.` : sq ? `Offered to ${q.name}. Anyone with the code can follow it.` : "Anyone with the code can follow it.");
    };
    T.copy_link = () => { if (plan().code) copy(`${location.origin}/p/${plan().code}`, "Copied: its link. Anyone who opens it can follow with the code, as Who can follow says."); };
    T.open_page = () => { if (plan().code) window.open(`/p/${plan().code}`, "_blank", "noopener"); };
    function postsSheet(rows3, said = "", text = "") {
      const n = others(plan());
      sheet({ kind: "posts", title: n ? `Posts to the ${n.toLocaleString()} following` : "Posts",
        words: said || (rows3.length ? "" : "Nothing posted yet. Followers see a post in Anki and on their home page."),
        fields: [{ name: "text", value: text, max: 200, hint: n ? `A line to the ${n.toLocaleString()} following` : "A line to its followers (nobody follows it yet)" }],
        rows: rows3.map((x) => ({ id: x.id, who: `${me && x.uid === me.uid ? "You" : String(x.name || "?")}${x.coauthor ? " (co-author)" : ""}`,
          text: `${String(x.text || "")}${x.withSave ? " (sent with changes)" : ""}`, ago: ago(x.at), remove: !!x.remove })),
        yes: "Post", no: "Close", cmd: "tabcmd", args: { name: "post" } });
    }
    T.posts = async ({ said } = {}) => {
      if (!author()) return;
      say("Loading…");
      try { F.posts = (await api("GET", `/plans/${B.id}/posts`)).posts || []; say(""); postsSheet(F.posts, said); }
      catch { say("Couldn't load the updates."); }
    };
    T.post = async ({ text }) => {
      const t = norm(text).slice(0, 200);
      if (!author() || !t || F.postBusy) return;
      F.postBusy = true; say("Posting…");
      try { await api("POST", `/plans/${B.id}/posts`, { text: t }); F.postBusy = false; T.posts({ said: "Posted. Followers see it in Anki and on their home page." }); }
      catch (err) { F.postBusy = false; const why = err && err.status === 429 ? "Five posts a day per plan. Try tomorrow." : "That didn't post. Try again."; say(why); postsSheet(F.posts, why, t); }
    };
    T.unpost = async ({ id }) => {
      const x = F.posts.find((p) => p.id === id && p.remove);
      if (!x) return;
      try { await api("DELETE", `/plans/${B.id}/posts/${x.id}`); T.posts(); } catch { postsSheet(F.posts, "That didn't work. Try again."); }
    };
    T.history = async () => {
      if (!author()) return;
      try {
        const log = (await api("GET", `/plans/${B.id}/log`)).log || [];
        const u0 = log[0] && log[0].undo ? log[0] : null;
        sheet({ kind: "history", title: `History · ${plan().name || "the plan"}`,
          words: log.length ? "" : "No saves yet. Each one shows here, who made it and what it changed, and the latest can be undone.",
          rows: log.map((x) => ({ who: me && x.uid === me.uid ? "You" : String(x.name || "?"), text: String(x.summary || ""), ago: ago(x.at) })),
          yes: u0 ? "Undo the latest" : null, no: "Close", tip: "Puts back what the latest save changed, for everyone",
          cmd: "tabcmd", args: { name: "history_undo", version: u0 ? u0.version : null } });
      } catch { say("Couldn't load the history."); }
    };
    T.history_undo = ({ version }) => {
      if (!author() || version === null || version === undefined) return;
      if (F.changes.length) { say("Send or discard your changes first: Undo puts back the plan as it was saved."); return; }
      undoSave(Number(version));
    };
    T.coauthor_ask = async () => {
      if (!owner() || F.busy) return;
      const have = new Set([plan().owner, ...(plan().editors || []).map((e) => e.uid)]);
      let crew;
      try { crew = ((await api("GET", "/friends")).friends || []).filter((f) => f.mutual && !have.has(f.uid)); } catch { say("Couldn't load your crew. Try again."); return; }
      if (!crew.length) { say("Co-authors come from your crew: you add each other."); return; }
      const seen = new Map();
      F.crew = new Map(crew.map((f) => [f.uid, f.name || "?"]));
      sheet({ kind: "pick", title: "Ask a co-author", words: "From your crew:", yes: "Ask",
        options: crew.map((f) => { const n = f.name || "?"; seen.set(n, (seen.get(n) || 0) + 1); return { v: f.uid, label: seen.get(n) === 1 ? n : `${n} (${seen.get(n)})` }; }),
        cmd: "tabcmd", args: { name: "coauthor_add", uid: crew[0].uid } });
    };
    T.coauthor_add = async ({ uid }) => {
      if (!owner() || !F.crew || !F.crew.has(uid)) return;
      try { const r = await api("POST", `/plans/${B.id}/editors`, { uid }); took({ ...plan(), editors: r.editors || plan().editors }, `Asked ${F.crew.get(uid)}. They'll see it on their home page and in Anki.`); }
      catch (err) { failed(err, { too_many_editors: "A plan has up to 10 co-authors.", not_crew: "Co-authors come from your crew: you add each other." }); }
    };
    async function offer(uid) {
      try {
        const r = await api("POST", `/plans/${B.id}/owner`, { uid });
        took({ ...plan(), editors: (r && r.editors) || plan().editors, handover: r && "handover" in r ? r.handover : uid },
          uid ? "They'll see it on their home page and in Anki. It's theirs once they say yes." : "Taken back.");
      } catch (err) { failed(err, { not_coauthor: "Only a co-author who said yes can be handed it." }); }
    }
    const ed = (uid) => (plan().editors || []).find((e) => String(e.uid) === String(uid));
    T.hand = ({ uid }) => { const e = ed(uid); if (owner() && e && !e.pending && !plan().handover) offer(e.uid); };
    T.unhand = () => { if (owner() && plan().handover) offer(null); };
    T.coauthor_off = async ({ uid }) => {
      const e = ed(uid);
      if (!owner() || !e) return;
      try {
        await api("DELETE", `/plans/${B.id}/editors/${e.uid}`);
        took({ ...plan(), editors: (plan().editors || []).filter((x) => x.uid !== e.uid), handover: plan().handover === e.uid ? null : plan().handover }, "");
      } catch { say(`${e.name || "?"} is still ${e.pending ? "asked" : "a co-author"}. Try again.`); }
    };
    T.leave = async ({ sure } = {}) => {
      if (!author() || owner()) return;
      if (!sure) { sheet({ title: `Leave ${plan().name || "this plan"}?`, words: "You stop co-writing it. Its tags stay on your notes until you take them off.", yes: "Leave", cmd: "tabcmd", args: { name: "leave", sure: true } }); return; }
      try { await api("DELETE", `/plans/${B.id}/editors/${me.uid}`); goTo("/plans"); } catch { say("That didn't work. Try again."); }
    };
    T.listed = async ({ on }) => {
      if (!owner() || F.busy || plan().listed === -1) return;
      try { took(await api("PUT", `/plans/${B.id}/listed`, { listed: !!on }), on ? "In the library." : "Out of the library."); }
      catch (err) { failed(err, { too_many_listed: "You have 20 plans in the library. Take one out first." }); }
    };
    T.next_year = async () => {
      if (!author() || F.busy) return;
      if (F.changes.length) { say("Send or discard your changes first, so the copy is the plan as it's saved."); return; }
      const firstOf = (d) => [...(d.units || []).map((u) => u.opens), ...(d.events || []).map((e) => e.day)].filter(Boolean).sort()[0];
      const named = (n) => { let b = String(n || "").replace(/\s*\((?:next year|copy)\)\s*$/i, "").trim(); if (b.length > 48) { b = b.slice(0, 48); const sp = b.lastIndexOf(" "); if (sp > 24) b = b.slice(0, sp); } return `${b.trimEnd()} (next year)`; };
      F.busy = true; say("Copying…"); push();
      try {
        const got = await api("GET", `/plans/${B.id}`);
        const first = firstOf(got.doc || {});
        if (!first) { F.busy = false; say("The plan has no sets to copy."); push(); return; }
        let mine = await api("POST", `/plans/${B.id}/copy`, { start: addDays(first, 364) });
        try { mine = await api("PUT", `/plans/${mine.id}`, { version: mine.version, name: named(got.name || plan().name), summary: "named for next year" }); } catch { /* it stands, named "(copy)" */ }
        F.busy = false;
        goTo(`/plans/${mine.id}/edit`);
      } catch (err) {
        F.busy = false;
        failed(err, { too_many_plans: "You have 50 plans. Delete one first.", plans_full: "Your plans hold as much as one account can. Delete one first." });
      }
    };
    T.table = () => {
      const lines = ["Day\tSet\tFinish by\tTested on\tCards"], placed = B.placedKeys();
      for (const u of byOpens()) lines.push([u.opens, u.name || "", u.due || "", (eventOf(u.for) || {}).name || "", tree() ? B.unitTotal(u, placed) : ""].join("\t"));
      for (const e of B.events()) lines.push([e.day, e.name || "", "", "(quiz or exam)", ""].join("\t"));
      copy(`${lines.join("\n")}\n`, `Copied: ${pl(units().length, "set")} as a table. Paste it into a spreadsheet.`);
    };
    T.delete_plan = async ({ sure } = {}) => {
      if (!owner() || F.busy) return;
      if (!sure) { sheet({ title: `Delete ${plan().name || "this plan"}?`, words: "It's gone for everyone. Followers keep every card they have open; nothing is suspended.", yes: "Delete it", danger: true, cmd: "tabcmd", args: { name: "delete_plan", sure: true } }); return; }
      try { await api("DELETE", `/plans/${B.id}`); F.changes = []; window.onbeforeunload = null; goTo("/plans"); } catch { say("That didn't work. Try again."); }
    };
    T.ai_app = () => say("Your AI app is the add-on's, on your computer: in Anki, Your plans › Settings.");
    // the plan's own page (builder.js's, as it was): its followers' progress by set, the poster, the calendar menu
    T.its_page = () => goTo(`/plans/${B.id}?page`);
    // ---- a follower's: my follow (webtabs.c_<name>, plan_flow's steps), one PATCH /plans/{id}/follow a click ----
    /** my follow changed on the server, then the plan as it is now (what the old page did: PATCH, then GET) */
    async function patchFollow(body, said) {
      if (!follower() || F.busy) return false;
      F.busy = true; push();
      try {
        await api("PATCH", `/plans/${B.id}/follow`, body);
        await reread(said);
        return true;
      } catch (err) {
        F.busy = false;
        failed(err, { not_following: "You don't follow it on this account any more.", bad_follow: "That didn't change. Try again." });
        return false;
      }
    }
    /** the plan read again, on my days; what's picked kept when it's still there */
    async function reread(said) {
      const r = await api("GET", `/plans/${B.id}`);
      B.plan = r;
      runMine();
      F.busy = false;
      if (F.picked && !((F.picked[0] === "date" && unit(F.picked[1])) || (F.picked[0] === "event" && eventOf(F.picked[1])) || (F.picked[0] === "review" && reviewOf(F.picked[1])))) {
        F.picked = null; pickDefault();
      }
      relabel();
      if (said) say(said);
      push();
    }
    T.shift = ({ later, days } = {}) => {
      if (!follower()) return;
      const was = Number(follow().shift || 0);
      if (!later) { if (was) patchFollow({ shift: 0 }, "Back on the plan's days."); else push(); return; }
      if (days === undefined || days === null) {
        sheet({ title: "My sets, some days later", words: "How many days after the plan's your sets open (up to 365). Quizzes and exams stay on their days.",
          fields: [{ name: "days", label: "Days later", type: "number", value: String(was || 7) }], yes: "Move my sets", cmd: "tabcmd", args: { name: "shift", later: true } });
        return;
      }
      const n = Math.max(0, Math.min(365, Math.round(Number(days) || 0)));
      if (n !== was) patchFollow({ shift: n }, n ? `Your sets open ${pl(n, "day")} after the plan's.` : "Back on the plan's days.");
    };
    T.skip = ({ uid, on = true }) => {
      const f = follow(), had = f.skipped || [];
      if (!follower() || typeof uid !== "string") return;
      if (on && !((plan().doc || {}).units || []).some((u) => u.id === uid)) return;
      if (!on && !had.includes(uid)) return;
      patchFollow({ skipped: [...had.filter((x) => x !== uid), ...(on ? [uid] : [])] }, on ? "Skipped: it's not on your days now." : "Back on your days.");
    };
    T.own = ({ own }) => {
      const v = own === "ready" ? "ready" : "";
      if (follower() && String(follow().own || "") !== v) patchFollow({ own: v || null }, v ? "Its cards open when you're ready: Up next on the board in Anki." : "Its cards open each morning, on their days.");
      else push();
    };
    T.own_next = ({ on }) => { if (follower() && follow().own) patchFollow({ own: on ? "next" : "ready" }); };
    T.early = ({ n }) => {
      const k = Number(n);
      if (follower() && !follow().own && [0, 1, 2, 3, 5, 7].includes(k)) patchFollow({ early: k }, k ? `Each set opens ${pl(k, "day")} early.` : "Each set opens on its day.");
    };
    T.pause = ({ until, uid } = {}) => {
      const f = follow(), t0 = today0();
      if (!follower()) return;
      if (f.paused) {  // back: my sets later by the days I was away, or as they are (plan_flow.back)
        const days = Math.max(0, f.since ? Sched.diff(t0, f.since) : 0);
        if (days && !f.own && uid === undefined) {
          sheet({ kind: "pick", title: "Resume", words: `You paused ${pl(days, "day")} ago.`, yes: "Resume",
            options: [{ v: "push", label: `Push my sets back ${pl(days, "day")}` }, { v: "open", label: "Keep my days: what opened meanwhile is behind" }],
            cmd: "tabcmd", args: { name: "pause", uid: "push" } });
          return;
        }
        const shift = Math.min(365, Number(f.shift || 0) + (uid === "push" ? days : 0));
        patchFollow({ paused: false, since: null, until: null, shift }, "Resumed.");
        return;
      }
      if (until === undefined) {
        sheet({ title: "Pause until…", words: "Nothing opens till then; your Anki asks what to do when you're back.",
          fields: [{ name: "until", label: "Until", type: "date", value: addDays(t0, 7) }], yes: "Pause", cmd: "tabcmd", args: { name: "pause" } });
        return;
      }
      if (/^\d{4}-\d\d-\d\d$/.test(String(until)) && until >= t0) patchFollow({ paused: true, since: t0, until }, `Paused until ${fmt(until)}.`);
    };
    T.reset = ({ sure } = {}) => {
      const lines = resetLines();
      if (!follower() || !lines.length) return;
      if (!sure) {
        sheet({ title: "Reset to default?", words: `${lines.join(". ")}. Cards already open stay open. Sets that come back and have passed count as behind.`,
          yes: "Reset", cmd: "tabcmd", args: { name: "reset", sure: true } });
        return;
      }
      patchFollow({ shift: 0, skipped: [], moved: {}, paused: false, until: null, since: null }, "Back to the plan's days.");
    };
    T.team = async () => {
      if (!follower() || F.busy) return;
      const leaving = inTeam();
      F.busy = true; push();
      try {
        await api(leaving ? "DELETE" : "POST", `/plans/${B.id}/team`);
        await reread(leaving ? "You left its squad. Your questions and answers stay." : "You're in its squad: it's on the board's Squads tab.");
      } catch (err) { F.busy = false; failed(err, { team_full: "This squad is full." }); }
    };
    T.stop_following = async ({ sure } = {}) => {
      if (!follower()) return;
      if (!sure) {
        sheet({ title: `Stop following ${plan().name || "it"}?`, words: "Its cards you have open stay open in your Anki; nothing new opens.", yes: "Stop following", danger: true,
          cmd: "tabcmd", args: { name: "stop_following", sure: true } });
        return;
      }
      try { await api("DELETE", `/plans/${B.id}/follow`); goTo("/plans"); } catch (err) { failed(err); }
    };
    T.copy_mine = async ({ start } = {}) => {
      const p = plan();
      if (!follower() || !(p.library || p.listed)) return;
      if (start === undefined) {
        sheet({ title: "Make my own copy", words: "The same sets, yours to change. Its first set opens on:",
          fields: [{ name: "start", type: "date", value: nextMonday() }], yes: "Copy it", cmd: "tabcmd", args: { name: "copy_mine" } });
        return;
      }
      if (!/^\d{4}-\d\d-\d\d$/.test(String(start))) return;
      try { const mine2 = await api("POST", `/plans/${B.id}/copy`, { start }); goTo(`/plans/${mine2.id}/edit`); }
      catch (err) {
        failed(err, { too_many_plans: "You have 50 plans. Delete one first.", plans_full: "Your plans hold as much as one account can. Delete one first." });
      }
    };
    for (const k of ["held", "change_deck", "open_everything", "schedule", "lesson_deck"]) T[k] = anki;  // Anki's own (hidden here)

    // ---- New plan (webnew's, as the site has it: someone's plan, or start empty) ----
    function newOpen(o2 = {}) {
      const decks = (o2.decks || []).slice();
      if (o2.deck && !decks.includes(o2.deck)) decks.unshift(o2.deck);
      F.newSt = { step: o2.deck ? "empty" : "pick", decks, deck: o2.deck ? decks.indexOf(o2.deck) : decks.length ? 0 : null,
        name: o2.deck ? (String(o2.deck).split("::").pop().trim() || o2.deck).slice(0, 60) : "", end_name: "", end_day: addDays(today0(), 28), code: "", said: "", busy: false };
    }
    function newView() {
      const st = F.newSt, deck = st.deck !== null ? st.decks[st.deck] : null;
      return { step: st.step, back: F.plans.length > 0, busy: st.busy, said: st.said, decks: st.decks.map((d, i) => ({ id: i, label: d })), deck: st.deck,
        deckName: deck ? String(deck).split("::").pop() : "", name: st.name, endName: st.end_name, endDay: st.end_day, lesson: null, code: st.code,
        today: today0(), ways: ["someone"], canMake: !!norm(st.name) && deck !== null && !st.busy };
    }
    C.new_step = ({ step }) => {
      if (!F.newSt || F.newSt.busy || !["pick", "someone", "empty"].includes(step)) return;
      if (step === "empty" && !F.newSt.decks.length) { F.newSt.said = "A plan is for a deck of yours: in Anki, open Due Crew once, and its decks come here."; push(); return; }
      F.newSt.step = step; F.newSt.said = ""; push();
    };
    C.new_set = ({ key, value }) => {
      const st = F.newSt;
      if (!st || st.busy) return;
      if (key === "deck" && Number.isInteger(Number(value)) && st.decks[Number(value)] !== undefined) st.deck = Number(value);
      else if (key === "name") st.name = norm(value).slice(0, 60);
      else if (key === "end_name") st.end_name = norm(value).slice(0, 60);
      else if (key === "end_day" && /^\d{4}-\d\d-\d\d$/.test(String(value))) st.end_day = String(value);
      push();
    };
    C.new_cancel = () => { if (B) { F.newSt = null; push(); } else goTo("/plans"); };
    C.new_follow = ({ code }) => { const c = String(code || "").replace(/[^A-Za-z0-9]/g, "").toUpperCase(); if (c) goTo(`/p/${c}`); };
    C.new_library = () => goTo("/library");
    C.new_make = async ({ start: st0 } = {}) => {
      const st = F.newSt;
      if (!st || st.busy || !norm(st.name) || st.deck === null) return;
      st.busy = true; st.said = "Making the plan…"; push();
      try {
        let p = await api("POST", "/plans", { name: norm(st.name), deck: st.decks[st.deck] });
        const end = norm(st.end_name);
        if (end && st.end_day) {
          const ev = { id: uid8(), day: st.end_day, name: end };
          try { p = await api("PUT", `/plans/${p.id}`, { version: p.version, name: p.name, doc: { ...p.doc, events: [ev], end: st.end_day }, summary: "the exam it ends with" }); }
          catch { /* the plan stands; its exam goes on from Add */ }
        }
        if (st0 && p.code) { try { await api("POST", "/plans/follow", { code: p.code }); } catch { /* made: following is one click on its page */ } }
        st.busy = false;
        goTo(`/plans/${p.id}/edit`);
      } catch (err) {
        const code = err && err.body && err.body.error;
        st.busy = false;
        st.said = code === "too_many_plans" ? "You have 50 plans, as many as an account keeps. Delete one first."
          : code === "plans_full" ? "Your plans hold as much as one account can. Delete one first."
            : code === "bad_plan" ? "That deck's name is too long for a plan: 200 characters at most, with its parent decks."
              : err && err.status === 429 ? "That's a lot of new plans. Try again in an hour." : "That didn't work. Try again.";
        push();
      }
    };

    // ---- the first view ----
    function pickDefault() {
      if (!B || F.picked) return;
      const t0 = today0(), us = byOpens();
      const now = us.filter((u) => u.opens <= t0 && t0 <= (u.due || u.opens)).pop() || us.find((u) => u.opens > t0) || us[us.length - 1];
      F.picked = now ? ["date", now.id] : null;
    }
    if (B) {
      runMine();  // a follower's: the plan on my days
      if (B.cover && B.cover.size === 0 && !units().length && tree()) F.side = "deck";  // a new plan: its deck first
      const vs = B.kindsBelow("root:tag");
      F.deck.view = vs.has("resource") ? "resource" : vs.has("system") ? "system" : vs.has("other") ? "other" : "deck";
      pickDefault();
    }
    if (o.newPlan) newOpen(o.newPlan);

    /** a message from the page: "dcplan:" + JSON {c, a} (webface._on_cmd) */
    function cmd(m) {
      if (typeof m !== "string" || !m.startsWith(PREFIX)) return;
      let d;
      try { d = JSON.parse(m.slice(PREFIX.length)); } catch { return; }
      if (!d || typeof d !== "object") return;
      const fn = /^[a-z_]+$/.test(String(d.c || "")) ? C[d.c] : null;
      if (!fn) return;
      try {
        const r = fn(d.a && typeof d.a === "object" ? d.a : {});
        if (r && typeof r.catch === "function") r.catch((err) => { console.error(err); say("Something went wrong. Reload the page."); });
      } catch (err) { console.error(err); say("Something went wrong. Reload the page."); }
    }
    return { F, view, cmd, handlers: C, tabHandlers: T, push, drawn: push, op };
  }

  // ---- on the page ----
  let face = null;
  function mount(f) {
    stop();
    face = f;
    document.body.classList.add("dcplan");
    const root = h("div", { id: "dcp", class: "dcp" });
    page(root);
    $app().classList.add("dcplan-main");
    window.pycmd = (m) => { if (face === f) f.cmd(m); };
    dcPlan.start(f.view(), false);  // it says "ready": the face draws it whole
  }
  /** off the plan pages: the page stops listening (dcPlan's keys and clicks) */
  function stop() {
    if (!face) return;
    face = null;
    try { dcPlan.start(null, true); } catch { /* the page's script didn't load */ }
    window.pycmd = undefined;
    document.body.classList.remove("dcplan");
  }
  const out = { show: (v) => dcPlan.show(v), sheet: (s) => dcPlan.sheet(s), status: (s) => dcPlan.status(s),
    openUndo: () => dcPlan.openUndo(), pasted: () => dcPlan.pasted(),
    download: (url, name) => {
      const a = h("a", { href: url, download: name || "" });
      document.body.append(a); a.click(); a.remove();
      if (url.startsWith("blob:")) setTimeout(() => URL.revokeObjectURL(url), 30000);
    } };
  async function mine() { try { return (await api("GET", "/plans/mine")).plans || []; } catch { return []; } }

  /** /plans/{id}/edit and /plans/{id}: a plan I write or follow on the shared page (a follower's on my
   *  days); anyone else's (looked at from its code or the library), its page (builder.js) as before */
  async function open(id, tab = null) {
    const got = await api("GET", `/plans/${id}`);
    if (!isAuthor(got) && !got.following) return builder(id, null, got);
    let f = null;
    const plans = mine();
    const hook = { attach: (B) => B, drawn: () => { if (f) f.push(); } };
    const B = await builder(id, hook, got);
    f = make(B, { plans: await plans, tab, out });
    if (!f.F.plans.some((p) => p.id === id)) f.F.plans.unshift(got);
    mount(f);
    window.onbeforeunload = () => (f.F.changes.length ? true : undefined);
  }
  /** /plans/new: New plan, in the page's place of the tabs (?deck= from Anki's link) */
  async function newPlan() {
    const deck = new URLSearchParams(location.search).get("deck") || "";
    const [plans, trees] = await Promise.all([mine(), api("GET", "/plans/trees").catch(() => ({ trees: [] }))]);
    const decks = [...new Set((trees.trees || []).map((t) => t.deck).filter(Boolean))];
    mount(make(null, { plans, out, newPlan: { decks, deck } }));
  }
  return { open, newPlan, stop, make, Ics, _now: () => face };
})();
