// duecrew.com's plan builder (3.3): the calendar is the plan. Loaded before
// app.js, whose helpers (h, api, page, Sched, the dates) it uses when it
// runs. Names and counts only: the site never sees a card. See
// docs/plans-design.md, "3.3".

/** Readable tag names: "#Step1_v12::#Videos::01_Growth" reads
 *  "Step 1 › Videos › 1 · Growth" (a leading AK_ goes too). The raw tag is
 *  always shown too. */
/** Someone's emoji, or the first letter of their name in a circle when
 *  they haven't picked one (board.face in the add-on: change one, change both). */
const initial = (name) => { const m = /[\p{L}\p{N}]/u.exec(String(name || "")); return m ? m[0].toUpperCase() : "?"; };
const face = (emoji, name) => (emoji ? emoji : h("span", { class: "ini" }, initial(name)));

const Tags = (() => {
  function word(seg) {
    let s = String(seg).replace(/^[#^$!]+/, "").replace(/^AK_/i, "").replace(/_v\d+$/i, "");
    s = s.replace(/_/g, " ").replace(/\s+/g, " ").trim();
    const m = /^0*(\d+)\s*[.)-]?\s+(\S.*)$/.exec(s);
    if (m) s = `${m[1]} · ${m[2]}`;
    s = s.replace(/([a-z])(\d)/g, "$1 $2");
    return s || String(seg);
  }
  const name = (path) => path.split("::").map(word).join(" › ");
  const kind = (path) => {
    const segs = path.split("::");
    return segs.some((s) => s.startsWith("^")) ? "system" : segs.some((s) => s.startsWith("#")) ? "resource" : "other";
  };
  const natural = (a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });
  return { word, name, kind, natural };
})();

/** Due: a date's lines to tick by hand ({k, t, url}), as the Worker keeps
 *  them (worker/src/plans.ts, TODO_MAX) and the add-on shows them. */
const Todo = (() => {
  const MAX = 8;
  const LABEL = { watch: "Watch", read: "Read", do: "Do" };
  const okUrl = (v) => /^https:\/\/[^\s"'<>]{1,492}$/.test(v);
  /** "watch: lecture 14 https://…" -> {k, t, url} */
  const parse = (k, rest) => {
    const m = /^(.*?)\s+(https:\/\/\S+)$/.exec(rest.trim());
    const t = (m && okUrl(m[2]) ? m[1] : rest).trim().slice(0, 140);
    return m && okUrl(m[2]) ? { k: k.toLowerCase(), t, url: m[2] } : { k: k.toLowerCase(), t };
  };
  /** what a save sends: lines with words, at most MAX */
  const clean = (lines) => (lines || []).filter((x) => x && LABEL[x.k] && String(x.t || "").trim())
    .slice(0, MAX).map((x) => (x.url && okUrl(x.url) ? { k: x.k, t: x.t.trim().slice(0, 140), url: x.url } : { k: x.k, t: x.t.trim().slice(0, 140) }));
  return { MAX, LABEL, okUrl, parse, clean };
})();

/** Searches about one person's own Anki (due_crew/plans.py, _PERSONAL). */
const PERSONAL = /(?:^|[\s("-])(?:deck:current|is:(?:due|new|learn|review|suspended|buried|susp)|rated:|prop:|introduced:|added:|edited:|resched:|flag:|nid:|cid:)/i;

/** 3.6.5: notes: and cards: in the plan as text. A note's guid (Anki's own
 *  name for it, the same in every copy of a deck) can hold | , : and `, so
 *  these are read before the line is split: space-separated, up to a |
 *  standing alone. cards: is GUID:N, split on the last colon, N the card's
 *  number from 1 (a cloze's c2 is 2). */
const Picks = (() => {
  const SEG = /(^|\|)\s*(notes|cards):[ \t]*(.*?)[ \t]*(?=\s\|(?:\s|$)|$)/i;
  const OK = (g) => g.length >= 1 && g.length <= 40;
  /** {line: what's left, notes, cards: [[guid, ord]], bad: [tokens]} */
  function take(line) {
    const out = { line, notes: [], cards: [], bad: [] };
    let m;
    while ((m = SEG.exec(out.line))) {
      for (const tok of m[3].split(/\s+/).filter(Boolean)) {
        if (m[2].toLowerCase() === "notes") { (OK(tok) ? out.notes : out.bad).push(tok); continue; }
        const at = tok.lastIndexOf(":");
        const g = tok.slice(0, at); const n = Number(tok.slice(at + 1));
        if (at > 0 && OK(g) && Number.isInteger(n) && n >= 1 && n <= 1001) out.cards.push([g, n - 1]); else out.bad.push(tok);
      }
      out.line = `${out.line.slice(0, m.index)}${m[1]} ${out.line.slice(m.index + m[0].length)}`;
    }
    out.notes = [...new Set(out.notes)];
    const seen = new Set();
    out.cards = out.cards.filter(([g, o]) => !seen.has(`${g}:${o}`) && seen.add(`${g}:${o}`));
    return out;
  }
  const notesText = (gs) => `notes:${gs.join(" ")}`;
  const cardsText = (cs) => `cards:${cs.map(([g, o]) => `${g}:${o + 1}`).join(" ")}`;
  return { take, notesText, cardsText };
})();

/** The plan's page. Its authors (the owner and co-authors) edit it; anyone
 *  following sees the same calendar, read-only, with the notes. */
async function builder(id) {
  let plan = await api("GET", `/plans/${id}`);
  const author = plan.role === "owner" || plan.role === "editor";
  const owner = plan.role === "owner";
  const inPlan = plan.role !== "reader";
  const [{ trees }, { squads }, notesR] = await Promise.all([
    author ? api("GET", `/plans/trees?deck=${encodeURIComponent(plan.doc.deck)}`) : { trees: [] },
    owner ? api("GET", "/squads/mine") : { squads: [] },
    inPlan ? api("GET", `/plans/${id}/notes`).catch(() => ({ notes: [] })) : { notes: [] }]);
  let notes = notesR.notes;
  const raw = trees.find((t) => t.deck === plan.doc.deck) || { tags: [], decks: [] };
  // 3.3's add-on sends it nested, each name once: [name, n, [children]?]
  const flat = (rows) => {
    if (raw.v !== 2) return rows || [];
    const out = [];
    const walk = (level, pre) => { for (const [name, n, kids] of level) { const p = pre ? `${pre}::${name}` : name; out.push([p, n]); if (kids) walk(kids, p); } };
    walk(rows || [], "");
    return out;
  };
  const tree = { tags: flat(raw.tags), decks: flat(raw.decks) };

  // ---- the deck's tree: counts, children, order ----
  const count = new Map();
  const kids = new Map([["root:tag", []], ["root:deck", []]]);
  const pathOf = (key) => key.slice(key.indexOf(":") + 1);
  const kindOf = (key) => key.slice(0, key.indexOf(":"));
  for (const [kind, rows] of [["tag", tree.tags], ["deck", tree.decks]]) {
    const have = new Set(rows.map(([p]) => p));
    for (const [p, n] of rows) {
      count.set(`${kind}:${p}`, n);
      const parts = p.split("::");
      let parent = `root:${kind}`;
      for (let i = parts.length - 1; i >= 1; i--) {
        const anc = parts.slice(0, i).join("::");
        if (have.has(anc)) { parent = `${kind}:${anc}`; break; }
      }
      if (!kids.has(parent)) kids.set(parent, []);
      kids.get(parent).push(`${kind}:${p}`);
    }
  }
  for (const list of kids.values()) list.sort((a, b) => Tags.natural(pathOf(a), pathOf(b)));
  const kidsOf = (key) => kids.get(key) || [];
  const order = new Map();
  const walk = (key) => { for (const k of kidsOf(key)) { order.set(k, order.size); walk(k); } };
  walk("root:tag"); walk("root:deck");
  const n = (key) => count.get(key) || 0;
  const under = (a, b) => kindOf(a) === kindOf(b) && pathOf(b).toLowerCase().startsWith(`${pathOf(a).toLowerCase()}::`);  // b is below a
  // which views the tags have: by resource, by system, the rest
  const tagKind = new Map(tree.tags.map(([p]) => [`tag:${p}`, Tags.kind(p)]));
  const subKinds = new Map();
  const kindsBelow = (key) => {
    if (subKinds.has(key)) return subKinds.get(key);
    const s = new Set(tagKind.has(key) ? [tagKind.get(key)] : []);
    for (const k of kidsOf(key)) for (const x of kindsBelow(k)) s.add(x);
    subKinds.set(key, s);
    return s;
  };
  const views = [["resource", "Resource"], ["system", "System"], ["other", "Other"]].filter(([k]) => kindsBelow("root:tag").has(k));
  if (tree.decks.length) views.push(["deck", "Deck"]);

  // ---- the working copy ----
  let doc = structuredClone(plan.doc);
  for (const u of doc.units) if (u.check) { (doc.reviews ||= []).push({ day: u.check, from: u.id, to: u.id }); delete u.check; }
  let base = structuredClone(doc);  // what this page loaded: a save that meets another merges onto it
  let meta = { name: plan.name, line: plan.line || "", audience: plan.audience, squad: plan.squad || "" };
  // a new plan starts at Anki's own 20 new cards a day
  const pace = { mode: doc.units.length ? "placed" : "daily", days: [1, 1, 1, 1, 1, 1, 1], daily: 20, ...(doc.pace || {}) };
  if (!doc.pace && doc.end) pace.mode = "end";
  let cover = new Set(pace.cover || []);
  let start = Sched.start(doc) || nextMonday();
  let dirty = false;
  let tab = "calendar";
  let view = matchMedia("(max-width: 700px)").matches ? "week" : "month";
  let anchor = today() >= start ? today() : start;
  let picked = null;        // the day open in the day panel
  let splitting = null;     // {u, key} while the split panel is open
  let moving = null;        // the day whose "Move this day…" is open
  let sideTab = "cover";
  let shareOpen = false;    // the Share menu, open across redraws
  let flash = false;        // B8: "Saved" shows for a moment    // B1: the side panel shows what to cover, or the picked day
  let treeView = views[0]?.[0] || "deck";
  let note = "";            // the last thing Lay it out or a split did
  const opened = new Set(); // the tree's expanded nodes
  let term0 = "";

  const status = h("span", { class: "status", role: "status" });
  const saveBtn = h("button", { onclick: () => save() }, "Save");
  // 3.7.3: a line to the plan's followers, with the save (it lands in Updates)
  const tell = h("input", { class: "tell", type: "text", maxlength: 200, placeholder: "Tell followers…",
    "aria-label": "Tell followers, with this save" });
  tell.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); save(); } });
  let posts = null;  // 3.7.3: the Updates tab's list, loaded when it opens
  const mark = () => {
    dirty = true; status.className = "status"; status.textContent = "Unsaved changes";
    document.querySelector(".savebar")?.classList.remove("clean");  // C6: on a phone, Save shows now
  };
  const narrow = () => matchMedia("(max-width: 700px)").matches;
  let coverOpen = null;   // H3: What to cover, open or not, across redraws (a phone opens it while there are no dates)
  let paceOpen = false;   // C6: the pace, folded to one line on a phone
  window.onbeforeunload = () => (dirty ? true : undefined);
  // B8: ⌘S / Ctrl+S saves (only while this page is the one showing)
  document.onkeydown = (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s" && document.contains(saveBtn)) { e.preventDefault(); if (dirty) save(); }
  };

  // ---- units and sources ----
  const srcs = (u) => [...(u.tags || []).map((t) => `tag:${t}`), ...(u.decks || []).map((d) => `deck:${d}`)];
  const placedKeys = () => new Set(doc.units.flatMap(srcs));
  const isPlaced = (key, placed = placedKeys()) => placed.has(key) || [...placed].some((p) => under(p, key));
  /** The placed keys strictly below `key` that aren't below another one. */
  function placedBelow(key, placed = placedKeys()) {
    const below = [...placed].filter((p) => under(key, p));
    return below.filter((p) => !below.some((q) => q !== p && under(q, p)));
  }
  /** A source's cards not already on another date through a tag below it. */
  const eff = (key, placed) => Math.max(0, n(key) - placedBelow(key, placed).reduce((a, p) => a + n(p), 0));
  const unitTotal = (u, placed = placedKeys()) => (count.size ? srcs(u).reduce((a, k) => a + eff(k, placed), 0) : u.n || 0) + (u.cards || []).length + searchN(u) + idsN(u);
  const label = (key, placed) => {
    const w = Tags.word(pathOf(key).split("::").pop());
    return placedBelow(key, placed).length ? `${w} · the rest` : w;
  };
  const searchN = (u) => (u.search || []).reduce((a, q) => a + (u.sn?.[q] || 0), 0);
  // (defined before autoName: the first names are worked out as the page opens)
  // E1: note ids and card ids pasted onto a date; `idn` is what they found in an author's Anki
  // 3.6.5: and notes by guid (`notes`); `idr` is the server's, from the author's Anki
  const idsLen = (u) => (u.nids || []).length + (u.cids || []).length + (u.notes || []).length;
  const hasIds = (u) => idsLen(u) > 0;
  const idsN = (u) => (hasIds(u) ? u.idn ?? idsLen(u) : 0);
  // one number, never notes vs cards (a novice doesn't know the difference);
  // what they come to in cards shows once an author's Anki has counted them
  const idsText = (u) => `${idsLen(u).toLocaleString()} added by ID`;
  const autoName = (u) => {
    const ks = srcs(u);
    if (!ks.length) return (u.search || []).length ? "Search" : hasIds(u) ? idsText(u) : (u.cards || []).length ? `${u.cards.length} single card${u.cards.length === 1 ? "" : "s"}` : "?";
    return `${label(ks[0])}${ks.length > 1 ? ` + ${ks.length - 1} more` : ""}`.slice(0, 60);
  };
  const auto = new Set(doc.units.filter((u) => !u.name || u.name === autoName(u)).map((u) => u.id));
  const renameAll = () => { for (const u of doc.units) if (auto.has(u.id)) u.name = autoName(u); };
  const byOpens = () => doc.units.sort((a, b) => a.opens.localeCompare(b.opens));
  const study = { days: pace.days };
  const isStudy = (d) => Sched.weight(doc, study, d, 0) > 0;
  function nextStudy(d) {
    for (let i = 1; i <= 400; i++) { const x = addDays(d, i); if (isStudy(x)) return x; }
    return addDays(d, 1);
  }
  const firstStudy = (d) => (isStudy(d) ? d : nextStudy(d));
  function studyDays(a, b) { let k = 0; for (let x = a; x <= b; x = addDays(x, 1)) if (isStudy(x)) k++; return k; }
  const lastDay = () => doc.units.reduce((m, u) => { const e = u.even && u.due ? u.due : u.opens; return e > m ? e : m; }, "");
  const cleanup = () => {
    doc.units = doc.units.filter((u) => srcs(u).length || (u.cards || []).length || (u.search || []).length || hasIds(u));
    const ids = new Set(doc.units.map((u) => u.id));
    if (doc.reviews) { doc.reviews = doc.reviews.filter((r) => ids.has(r.from) && ids.has(r.to)); if (!doc.reviews.length) delete doc.reviews; }
  };
  function takeIds(u) { delete u.nids; delete u.cids; delete u.notes; delete u.idn; delete u.idr; }
  // F1: events: named days (a lecture, a quiz, the exam) that dates prep for
  const events = () => doc.events || [];
  const evById = (id) => events().find((x) => x.id === id);
  const evOn = (d) => events().filter((x) => x.day === d);
  const prepOf = (id) => doc.units.filter((u) => u.for === id);
  /** the days (not dates: a day can hold several) that prep for an event */
  const prepDays = (id) => [...new Set(prepOf(id).map((u) => u.opens))].sort();
  function addEvent(day, name) {
    const ev = { id: uid8(), day, name: (name || "").trim().slice(0, 60) || "Event" };
    doc.events = [...events(), ev].sort((a, b) => a.day.localeCompare(b.day));
    return ev;
  }
  function takeEvent(ev) {
    doc.events = events().filter((x) => x !== ev);
    if (!doc.events.length) delete doc.events;
    for (const u of doc.units) if (u.for === ev.id) delete u.for;
  }
  let aimFor = null;        // F1: Fill aims at this event (its day before is the finish date)
  /** "Search: Cardio…", by its first tag (3.4 review, N7). */
  const searchName = (q) => { const m = /tag:"?([^\s"]+)/i.exec(q); const w = m ? Tags.word(m[1].split("::").filter((x) => x.replace(/\*/g, "")).pop() || "").replace(/\*/g, "") : ""; return w ? `Search: ${w}` : "Search"; };

  function unitOn(d) {
    let u = doc.units.find((x) => x.opens === d && !x.even);
    if (!u) { u = { id: uid8(), name: "", opens: d, tags: [], decks: [], cards: [] }; doc.units.push(u); auto.add(u.id); byOpens(); }
    return u;
  }
  function addTo(d, key) {
    const u = unitOn(d);
    const f = kindOf(key) === "tag" ? "tags" : "decks";
    u[f] = u[f] || [];
    if (!u[f].includes(pathOf(key))) u[f].push(pathOf(key));
    return u;
  }
  function takeSearch(u, q) {
    u.search = (u.search || []).filter((x) => x !== q);
    if (u.sn) { delete u.sn[q]; if (!Object.keys(u.sn).length) delete u.sn; }
    if (!u.search.length) delete u.search;
  }
  function takeOut(u, key) {
    const f = kindOf(key) === "tag" ? "tags" : "decks";
    u[f] = (u[f] || []).filter((p) => p !== pathOf(key));
  }
  function evenUnit(d, key, days) {
    let last = d;
    for (let i = 1; i < days; i++) last = nextStudy(last);
    if (last === d) return addTo(d, key);
    const u = { id: uid8(), name: "", opens: d, due: last, even: true, tags: [], decks: [], cards: [] };
    u[kindOf(key) === "tag" ? "tags" : "decks"].push(pathOf(key));
    doc.units.push(u); auto.add(u.id); byOpens();
    return u;
  }
  function shiftUnit(u, delta) {
    u.opens = addDays(u.opens, delta);
    if (u.due) u.due = addDays(u.due, delta);
    if (u.check) u.check = addDays(u.check, delta);
  }

  // ---- what to cover, and laying it out ----
  const coverItems = () => [...cover].filter((k) => count.has(k) && ![...cover].some((c) => c !== k && under(c, k)))
    .sort((a, b) => (order.get(a) ?? 0) - (order.get(b) ?? 0));
  /** Cards ticked but on no date yet. */
  function left(key, placed = placedKeys()) {
    if (isPlaced(key, placed)) return 0;
    return eff(key, placed);
  }
  const coverTotal = () => coverItems().reduce((a, k) => a + n(k), 0);
  const coverLeft = () => { const p = placedKeys(); return coverItems().reduce((a, k) => a + left(k, p), 0); };
  /** The pieces of `key` still to place, chapters kept whole where they
   *  fit `cap`: a bigger one splits by its own tags, the part only on it
   *  goes last, and a big one with nothing below splits evenly. */
  function pieces(key, cap, placed) {
    if (isPlaced(key, placed)) return [];
    const below = placedBelow(key, placed);
    const whole = eff(key, placed);
    if (!whole) return [];
    if (!below.length && (!cap || n(key) <= cap)) return [{ key, n: n(key) }];
    const ks = kidsOf(key);
    if (!ks.length) return [{ key, n: whole, even: !!cap && whole > cap }];
    const out = ks.flatMap((k) => pieces(k, cap, placed));
    const rest = only(key);
    if (rest > 0) out.push({ key, n: rest, rest: true, even: !!cap && rest > cap });
    return out;
  }
  /** The cards on a tag and on none below it (overlaps make this a guess). */
  const only = (key) => Math.max(0, n(key) - kidsOf(key).reduce((a, k) => a + n(k), 0));
  const paceDaily = () => (pace.mode === "placed" ? 0 : Math.max(1, pace.daily || 0));
  /** Puts `items` on study days from `from` (to `until`), `cap` a day. */
  function fill(items, from, until, cap) {
    let d = firstStudy(from);
    let room = cap || Infinity;
    let used = 0;
    let placedN = 0;
    let lastD = null;
    for (const it of items) {
      if (until && d > until) break;
      if (it.even) {
        if (used) { d = nextStudy(d); room = cap; used = 0; if (until && d > until) break; }
        const k = Math.max(2, Math.ceil(it.n / cap));
        const u = evenUnit(d, it.key, k);
        placedN += it.n; lastD = u.due || d;
        d = nextStudy(u.due || d); room = cap; used = 0;
        continue;
      }
      if (!cap) { if (used) d = nextStudy(d); if (until && d > until) break; addTo(d, it.key); used = 1; placedN += it.n; lastD = d; continue; }
      if (it.n > room && used) { d = nextStudy(d); room = cap; used = 0; if (until && d > until) break; }
      addTo(d, it.key); room -= it.n; used++; placedN += it.n; lastD = d;
    }
    return { placedN, lastD };
  }
  function layOut(weekAhead) {
    if (pace.mode === "end") pace.daily = endDaily();
    const cap = paceDaily();
    const placed = placedKeys();
    const items = coverItems().flatMap((k) => pieces(k, cap, placed));
    if (!items.length) return draw();
    const after = lastDay() ? addDays(lastDay(), 1) : start;
    let from = after > start ? after : start;
    let until = null;
    if (weekAhead) {
      const nm = nextMonday();
      if (from < nm) from = nm;
      const mon = Sched.monday(from);
      from = from < mon ? mon : from;
      until = addDays(mon, 6);
      anchor = mon; view = "week";
    }
    const r = fill(items, from, until, cap);
    renameAll(); byOpens(); mark();
    note = r.placedN ? `Put ${r.placedN.toLocaleString()} cards on ${pretty(firstStudy(from))} to ${pretty(r.lastD)}.`
      : weekAhead ? "No study days left in that week." : "Nothing fit.";
    if (!weekAhead && r.lastD) anchor = firstStudy(from);
    if (r.lastD) requestAnimationFrame(() => document.querySelector(".cal2")?.scrollIntoView({ block: "nearest", behavior: "smooth" }));
    draw();
  }
  /** 3.4 review, H2: Fill with nothing to place says why, and the panel on the left flashes. */
  function fillOrSay(weekAhead) {
    if (coverLeft()) {
      const before = new Set(doc.units.map((u) => u.id));
      layOut(weekAhead);
      // F1: aimed at an event, the new dates before it prep for it
      const ev = pace.mode === "end" && aimFor && evById(aimFor);
      if (ev) { for (const u of doc.units) if (!before.has(u.id) && u.opens < ev.day && !u.for) u.for = ev.id; draw(); }
      return;
    }
    note = cover.size ? "Everything ticked is on the calendar already." : "Tick what to cover on the left first.";
    if (!cover.size) coverOpen = true;
    draw();
    const t = document.querySelector(".tree2");
    if (t) { t.classList.add("flash"); setTimeout(() => t.classList.remove("flash"), 900); }
  }
  function endDaily() {
    if (!doc.end) return pace.daily || 0;
    const after = lastDay() ? addDays(lastDay(), 1) : start;
    const from = after > start ? after : start;
    const days = studyDays(from, doc.end);
    const rest = coverLeft();
    return days && rest ? Math.max(1, Math.ceil(rest / days)) : 0;
  }
  function finishBy(daily) {
    let rest = coverLeft();
    if (!daily || !rest) return null;
    const after = lastDay() ? addDays(lastDay(), 1) : start;
    let d = firstStudy(after > start ? after : start);
    for (let i = 0; i < 2000 && rest > 0; i++) { rest -= daily; if (rest > 0) d = nextStudy(d); }
    return d;
  }

  // ---- days: what's on each ----
  function dayMap(from, to) {
    const out = new Map();
    const at = (d) => { if (!out.has(d)) out.set(d, { chips: [], load: 0 }); return out.get(d); };
    const placed = placedKeys();
    for (const u of doc.units) {
      if (u.even && u.due) {
        const total = unitTotal(u, placed);
        const days = [];
        for (let d = u.opens; d <= u.due; d = addDays(d, 1)) {
          const s = Sched.quota(doc, u, null, total, d) - Sched.quota(doc, u, null, total, addDays(d, -1));
          if (s > 0) days.push([d, s]);
        }
        days.forEach(([d, s], i) => {
          if (d < from || d > to) return;
          const e = at(d);
          e.chips.push({ u, key: srcs(u)[0], text: `${u.name || autoName(u)} (${i + 1}/${days.length})`, n: s, even: true });
          e.load += s;
        });
        if (days.length) continue;  // no count to slice (a follower's view): on its first day
      }
      if (u.opens < from || u.opens > to) continue;
      const e = at(u.opens);
      if (!count.size) {
        // a follower's view: the author's count for the date, its names
        for (const k of srcs(u)) e.chips.push({ u, key: k, text: label(k, placed), n: null, raw: pathOf(k) });
        e.load += u.n || 0;
      } else for (const k of srcs(u)) { const c = eff(k, placed); e.chips.push({ u, key: k, text: label(k, placed), n: c, raw: pathOf(k) }); e.load += c; }
      if ((u.cards || []).length) { e.chips.push({ u, cards: true, text: `${u.cards.length} single card${u.cards.length === 1 ? "" : "s"}`, n: u.cards.length }); e.load += u.cards.length; }
      for (const q of u.search || []) { const c = u.sn?.[q] ?? null; e.chips.push({ u, search: q, text: searchName(q), raw: q, n: c }); e.load += c || 0; }
      if (hasIds(u)) { e.chips.push({ u, ids: true, text: idsText(u), n: u.idn ?? null }); e.load += idsN(u); }
    }
    const byId = new Map(doc.units.map((u) => [u.id, u]));
    for (const r of doc.reviews || []) {
      if (r.day < from || r.day > to) continue;
      const a = byId.get(r.from), b = byId.get(r.to);
      if (a && b) at(r.day).chips.push({ review: r, text: `Review · ${a.name}${a !== b ? ` – ${b.name}` : ""}`, n: null });
    }
    return out;
  }
  const hue = (key) => {
    if (!key) return "c9";
    const segs = pathOf(key).split("::");
    const res = segs.find((s, i) => i > 0 && /^[#^]/.test(s)) || segs[0];
    let x = 0; for (const ch of res) x = (x * 31 + ch.charCodeAt(0)) >>> 0;
    return `c${x % 5}`;
  };

  // ---- drag and drop ----
  let dragging = null;  // {key} from the tree, or {chip}
  const dropOn = (el, onDrop) => {
    el.addEventListener("dragover", (e) => { if (dragging) { e.preventDefault(); el.classList.add("over"); } });
    el.addEventListener("dragleave", () => el.classList.remove("over"));
    el.addEventListener("drop", (e) => { e.preventDefault(); el.classList.remove("over"); const d = dragging; dragging = null; if (d) onDrop(d); });
  };
  function moveChip(c, d) {
    if (c.even) { shiftUnit(c.u, Sched.diff(d, c.u.opens)); }
    else if (c.cards) { if (c.u.opens === d) return; const t = unitOn(d); t.cards = [...(t.cards || []), ...c.u.cards]; c.u.cards = []; }
    else if (c.ids) { if (c.u.opens === d) return; const t = unitOn(d); for (const k of ["nids", "cids", "notes"]) { t[k] = [...new Set([...(t[k] || []), ...(c.u[k] || [])])]; if (!t[k].length) delete t[k]; } delete t.idn; delete t.idr; takeIds(c.u); }
    else if (c.search) { if (c.u.opens === d) return; const t = unitOn(d); t.search = [...new Set([...(t.search || []), c.search])]; if (c.u.sn?.[c.search] != null) t.sn = { ...(t.sn || {}), [c.search]: c.u.sn[c.search] }; takeSearch(c.u, c.search); }
    else { if (c.u.opens === d) return; takeOut(c.u, c.key); addTo(d, c.key); }
    cleanup(); renameAll(); byOpens(); mark(); draw();
  }
  function dropped(d, what) {
    if (what.key) { addTo(d, what.key); renameAll(); mark(); picked = d; draw(); }
    else if (what.chip) moveChip(what.chip, d);
  }

  // ---- the left panel: what to cover ----
  function treePanel() {
    const q = h("input", { type: "search", placeholder: "Search tags and subdecks", "aria-label": "Search tags and subdecks", value: term0 });
    const list = h("div", { class: "tlist" });
    const placed = placedKeys();
    const covered = (k) => cover.has(k) || [...cover].some((c) => under(c, k));
    const partly = (k) => [...cover].some((c) => under(k, c));
    // a tag holding more than one view (a big shared deck's top tag holds resources and
    // systems, the same cards twice) covers only what this view shows of it
    const inView = (k) => (treeView === "deck" || kindOf(k) === "deck" ? [k]
      : kindsBelow(k).size > 1 ? kidsOf(k).filter((c) => kindsBelow(c).has(treeView)).flatMap(inView) : [k]);
    const toggle = (k) => {
      if (cover.has(k)) cover.delete(k);
      else if (!covered(k)) for (const x of inView(k)) { for (const c of [...cover]) if (under(x, c)) cover.delete(c); cover.add(x); }
      mark(); draw();
    };
    const row = (k, depth, full, dup) => {
      const hasKids = kidsOf(k).length > 0 && !full;
      const p = pathOf(k);
      const seg = p.split("::").pop();
      const tw = hasKids ? h("button", { class: "tw", "aria-label": opened.has(k) ? "Collapse" : "Expand", "aria-expanded": String(opened.has(k)),
        onclick: (e) => { e.stopPropagation(); opened.has(k) ? opened.delete(k) : opened.add(k); fillList(); } }, opened.has(k) ? "▾" : "▸") : h("span");
      const all = inView(k);
      const on = covered(k) || (all.length > 1 && all.every(covered));
      const cb = h("input", { type: "checkbox", checked: on, "aria-label": `Cover ${Tags.name(p)}`, title: covered(k) && !cover.has(k) ? "Covered by the tag above it" : "What the plan covers",
        disabled: covered(k) && !cover.has(k), onchange: () => { if (on && all.length > 1) { for (const x of all) cover.delete(x); mark(); draw(); } else toggle(k); } });
      if (!on && partly(k)) cb.indeterminate = true;
      const onCal = isPlaced(k, placed);
      const el = h("div", { class: `tn${onCal ? " used" : ""}`, draggable: "true", style: `padding-left:${4 + depth * 14}px`, title: `${p}${onCal ? " · on the calendar" : ""}` },
        tw, cb,
        h("span", { class: "nm" }, full ? Tags.name(p) : Tags.word(seg), dup ? h("span", { class: "raw" }, full ? p : seg) : null),
        h("small", {}, n(k).toLocaleString()),
        h("button", { class: "add", title: picked ? `Put it on ${pretty(picked)}` : "Put it on the next free day", "aria-label": `Put ${Tags.word(seg)} on ${picked ? pretty(picked) : "the next free day"}`,
          onclick: () => { const d = picked || firstStudy(lastDay() ? addDays(lastDay(), 1) : start); dropped(d, { key: k }); } }, "+"));
      el.addEventListener("dragstart", (e) => { dragging = { key: k }; e.dataTransfer.setData("text/plain", p); });
      return el;
    };
    function fillList() {
      term0 = q.value;
      const term = q.value.trim().toLowerCase();
      const out = [];
      if (term) {
        for (const k of order.keys()) {
          const p = pathOf(k);
          if (n(k) && (p.toLowerCase().includes(term) || Tags.name(p).toLowerCase().includes(term))) out.push(row(k, 0, true, false));
          if (out.length >= 200) break;
        }
      } else {
        const shown = (k) => (treeView === "deck" ? kindOf(k) === "deck" : kindOf(k) === "tag" && kindsBelow(k).has(treeView));
        const rec = (key, depth) => {
          const ks = kidsOf(key).filter((k) => shown(k) && n(k) > 0);
          const words = new Map();
          for (const k of ks) { const w = Tags.word(pathOf(k).split("::").pop()); words.set(w, (words.get(w) || 0) + 1); }
          for (const k of ks) {
            out.push(row(k, depth, false, words.get(Tags.word(pathOf(k).split("::").pop())) > 1));
            if (opened.has(k)) rec(k, depth + 1);
          }
        };
        const root = treeView === "deck" ? "root:deck" : "root:tag";
        // one root with one path down it: open the way to the first choice
        let only = kidsOf(root).filter((k) => shown(k) && n(k) > 0);
        while (only.length === 1 && !opened.has(`seen:${only[0]}`)) { opened.add(only[0]); opened.add(`seen:${only[0]}`); only = kidsOf(only[0]).filter((k) => shown(k) && n(k) > 0); }
        rec(root, 0);
      }
      if (!out.length) out.push(h("p", { class: "muted small" }, count.size ? "Nothing matches." : "No tags yet. In Anki: Tools › Due Crew › Make a plan from a deck."));
      list.replaceChildren(...out);
    }
    q.addEventListener("input", fillList);
    fillList();
    const seg = views.length > 1 ? h("div", { class: "seg", role: "tablist" }, views.map(([k, t]) =>
      h("button", { role: "tab", "aria-selected": String(treeView === k), class: treeView === k ? "on" : "", onclick: () => { treeView = k; draw(); } }, t))) : null;
    const tot = coverTotal();
    return h("div", { class: "tree2" },
      h("div", { class: "thead" }, h("small", { class: "muted" }, tot ? `${tot.toLocaleString()} cards ticked` : "Tick what the plan covers.")),
      picked ? h("div", { class: "adding" }, h("b", {}, `Adding to ${pretty(picked)}`), h("span", { class: "muted" }, " · + puts a tag there")) : null,
      seg, q, list);
  }

  // ---- the pace ----
  function pacePanel() {
    // B2: one line; the kind of pace is a menu, and only its own field shows
    const kind = h("select", { "aria-label": "Pace", onchange: (e) => {
      pace.mode = e.target.value; if (pace.mode === "end" && !doc.end) doc.end = addDays(start, 55); mark(); draw(); } },
      [["end", "Finish by"], ["daily", "Cards a day"], ["placed", "I'll place each day"]].map(([v, t]) => h("option", { value: v, selected: pace.mode === v }, t)));
    const endIn = h("input", { type: "date", value: doc.end || "", "aria-label": "Finish by",
      onchange: (e) => { if (e.target.value) doc.end = e.target.value; else delete doc.end; if (!doc.end && doc.phases) { doc.phases.taper = 0; } mark(); draw(); } });
    const dailyIn = h("input", { type: "number", min: 1, max: 5000, value: pace.daily || 20, "aria-label": "New cards a day", style: "width:5.5em",
      onchange: (e) => { pace.daily = Math.max(1, Math.min(5000, Math.round(Number(e.target.value) || 1))); mark(); draw(); } });
    const d1 = pace.mode === "end" ? endDaily() : 0;
    const fin = pace.mode === "daily" ? finishBy(pace.daily || 20) : null;
    const startIn = h("input", { type: "date", value: start, "aria-label": "Starts",
      onchange: (e) => {
        if (!e.target.value) return;
        const delta = Sched.diff(e.target.value, start);
        start = e.target.value;
        for (const u of doc.units) shiftUnit(u, delta);  // every date moves with the start
        mark(); draw();
      } });
    const dayBtns = h("span", { class: "wdays", role: "group", "aria-label": "Study days" }, ["M", "T", "W", "T", "F", "S", "S"].map((l, i) =>
      h("button", { class: pace.days[i] ? "on" : "", "aria-pressed": String(!!pace.days[i]), title: ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][i],
        onclick: () => { const next = pace.days.slice(); next[i] = next[i] ? 0 : 1; if (next.some(Boolean)) { pace.days = next; study.days = next; mark(); draw(); } } }, l)));
    // F1: or aim at an event: finish the day before it, and the new dates prep for it
    const aim = events().length ? h("select", { "aria-label": "Or an event", onchange: (e) => {
      const ev = evById(e.target.value); aimFor = ev ? ev.id : null;
      if (ev) doc.end = addDays(ev.day, -1);
      mark(); draw(); } },
      h("option", { value: "" }, "or an event…"), events().map((x) => h("option", { value: x.id, selected: aimFor === x.id }, `${x.name} · ${pretty(x.day)}`))) : null;
    const how = pace.mode === "end" ? h("span", { class: "row", style: "gap:6px" }, aimFor && evById(aimFor) ? null : endIn, aim, h("small", { class: "muted" }, d1 ? `≈ ${d1.toLocaleString()} new a day` : ""))
      : pace.mode === "daily" ? h("span", { class: "row", style: "gap:6px" }, dailyIn, h("small", { class: "muted" }, fin ? `done ≈ ${pretty(fin)}` : ""))
      : h("small", { class: "muted" }, "drag a tag onto a day, or use +");
    return h("div", { class: "pace2" },
      h("span", { class: "pi" }, "Starts ", startIn), h("span", { class: "psep" }),
      h("span", { class: "pi" }, "Study days ", dayBtns), h("span", { class: "psep" }),
      h("span", { class: "pi" }, kind, how));
  }

  // ---- the calendar ----
  // 3.3: "Month" is the next five weeks from the week in view, so what's
  // coming is always on screen (a calendar month hides a plan starting on the 28th)
  function range() {
    const m = Sched.monday(anchor);
    return view === "week" ? [m, addDays(m, 6)] : [m, addDays(m, 34)];
  }
  function step(k) {
    anchor = addDays(Sched.monday(anchor), (view === "week" ? 7 : 28) * k);
    draw();
  }
  function calTitle() {
    const [a, b] = range();
    return `${pretty(a)} – ${pretty(b)}`;
  }
  function calendar() {
    const [a, b] = range();
    const days = dayMap(a, b);
    const cap = pace.mode === "end" ? endDaily() || pace.daily : pace.mode === "daily" ? pace.daily : 0;
    const t = today();
    const maxLoad = Math.max(1, ...[...days.values()].map((e) => e.load));
    const cells = [];
    for (let d = a; d <= b; d = addDays(d, 1)) {
      const e = days.get(d) || { chips: [], load: 0 };
      const ph = Sched.phase(doc, d, 0);
      const off = !pace.days[(parseIso(d).getUTCDay() + 6) % 7];
      const heavy = cap && e.load > cap * 1.25;
      const cls = ["d", off ? "off" : "", ph !== "build" ? ph : "", d === t ? "today" : "", d === picked ? "picked" : "", heavy ? "heavy" : "",
        doc.units.some((u) => u.opens === d && u.for && evById(u.for)) ? "lead" : ""].filter(Boolean).join(" ");
      const dd = parseIso(d);
      const num = dd.getUTCDate() === 1 || view === "week" ? `${dd.getUTCDate()} ${MONTHS[dd.getUTCMonth()]}` : String(dd.getUTCDate());
      const evs = evOn(d).map((x) => {
        const k = prepDays(x.id).length;
        const el = h("button", { class: "ch evc", title: `${x.name}${k ? ` · ${k} day${k === 1 ? "" : "s"} of prep` : ""}`,
          onclick: (ev) => { ev.stopPropagation(); picked = d; moving = null; sideTab = "day"; draw(); } },
          h("span", {}, x.name), k ? h("small", {}, `${k} day${k === 1 ? "" : "s"} of prep`) : null);
        // pointing at an event lights up the days that prep for it
        el.addEventListener("mouseenter", () => document.querySelectorAll(`.cal2 .d[data-for~="${x.id}"]`).forEach((c) => c.classList.add("hl")));
        el.addEventListener("mouseleave", () => document.querySelectorAll(".cal2 .d.hl").forEach((c) => c.classList.remove("hl")));
        return el;
      });
      const fors = [...new Set(doc.units.filter((u) => u.opens === d && u.for && evById(u.for)).map((u) => u.for))];
      const you = myLine(d);
      const chips = e.chips.map((c) => {
        const el = h("button", { class: `ch ${c.review ? "rv" : c.cards || c.ids ? "single" : c.search && c.n === 0 ? "warn" : c.search ? "c2" : hue(c.key)}${c.even ? " ev" : ""}`, draggable: author && !c.review ? "true" : null,
          title: `${c.raw || c.text}${c.n != null ? ` · ${c.n.toLocaleString()} cards` : ""}`,
          onclick: (ev) => { ev.stopPropagation(); picked = d; splitting = null; moving = null; sideTab = "day"; draw(); } }, h("span", {}, c.text), c.n != null ? h("small", {}, c.n.toLocaleString()) : null);
        if (author) el.addEventListener("dragstart", (ev) => { dragging = { chip: c }; ev.dataTransfer.setData("text/plain", c.text); ev.stopPropagation(); });
        return el;
      });
      const bar = e.load ? h("div", { class: `load${heavy ? " hi" : ""}` }, h("i", { style: `width:${Math.min(100, Math.round((100 * e.load) / (cap || maxLoad)))}%` })) : null;
      const cell = h("div", { class: cls, role: "gridcell", tabindex: "0", "aria-label": `${pretty(d)}${off ? ", a day off" : ""}${ph !== "build" ? `, ${ph === "catchup" ? "catch-up week" : "review-only days"}` : ""}: ${e.load ? `${e.load.toLocaleString()} cards` : "nothing new"}`,
        onclick: () => { picked = picked === d ? null : d; splitting = null; moving = null; sideTab = picked ? "day" : "cover"; draw(); },
        onkeydown: (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); picked = picked === d ? null : d; moving = null; sideTab = picked ? "day" : "cover"; draw(); } } },
        h("div", { class: "dn2" }, h("span", {}, num), nNotes(d) ? h("span", { class: "nb", title: "Notes" }, `💬 ${nNotes(d)}`) : null, e.load ? h("b", {}, e.load.toLocaleString()) : null), ...evs, ...chips,
        fors.map((id) => h("span", { class: "for" }, "for ", h("b", {}, evById(id).name))), bar,
        you ? h("span", { class: "you" }, you) : null);
      if (fors.length) cell.dataset.for = fors.join(" ");
      if (author) dropOn(cell, (what) => dropped(d, what));
      cells.push(cell);
    }
    return h("div", { class: `cal2 ${view}`, role: "grid", "aria-label": calTitle() },
      ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((x) => h("div", { class: "dh" }, x)), cells);
  }
  const nNotes = (d) => notes.filter((x) => x.day === d).length;
  /** K4: every date of it open and every card seen (what my Anki shares):
   *  a card to share, with its code when it's a code plan. */
  function finished() {
    const f = plan.following, prog = f.progress || {};
    const us = Sched.units(plan.doc).filter((u) => !(f.skipped || []).includes(u.id));
    if (!us.length || !us.every((u) => prog[u.id] && prog[u.id][2] > 0 && prog[u.id][1] >= prog[u.id][2])) return null;
    const days = us.map((u) => u.opens).sort();
    const cards = us.reduce((a, u) => a + prog[u.id][2], 0);
    const open = () => Cards.open({ kind: "plan", title: "Share this plan", file: `due-crew-plan-${plan.id}`, sizes: ["story"],
      data: { name: plan.name, cards, weeks: Math.max(1, Math.ceil((Sched.diff(days[days.length - 1], days[0]) + 1) / 7)), code: plan.audience === "code" ? plan.code : null },
      switches: plan.audience === "code" && plan.code ? [{ k: "code", label: "Its code, so others can follow" }] : [] });
    return h("p", { class: "done-line" }, h("b", {}, "Finished. "), `You’ve seen all ${cards.toLocaleString()} cards. `, h("button", { class: "linkish", onclick: open }, "Share a card ›"));
  }
  /** G6: a follower's own progress on a date, from what their Anki sends (only
   *  when they share it), and the dates they skip. Theirs alone to see. */
  function myLine(d) {
    const f = !author && plan.following;
    if (!f || d > today()) return null;
    const us = doc.units.filter((u) => u.opens === d && !u.even);
    if (!us.length) return null;
    if (us.every((u) => (f.skipped || []).includes(u.id))) return "you: skipped";
    const pr = us.map((u) => (f.progress || {})[u.id]).filter(Boolean);
    if (!pr.length) return null;
    const seen = pr.reduce((a, x) => a + x[1], 0), tot = pr.reduce((a, x) => a + x[2], 0);
    return tot && seen >= tot ? "you: all seen" : `you: ${seen.toLocaleString()} of ${tot.toLocaleString()}`;
  }
  function heavyNote() {
    if (!author) return null;
    const cap = pace.mode === "end" ? endDaily() || pace.daily : pace.mode === "daily" ? pace.daily : 0;
    if (!cap) return null;
    const [a, b] = range();
    const days = dayMap(a, b);
    for (const [d, e] of [...days.entries()].sort()) {
      if (e.load <= cap * 1.25) continue;
      const big = e.chips.filter((c) => !c.even && !c.cards).sort((x, y) => y.n - x.n)[0];
      return h("div", { class: "hnote" }, h("span", {}, h("b", {}, pretty(d)), ` is heavy: ${e.load.toLocaleString()} new (pace ${cap.toLocaleString()}).`),
        big ? h("button", { class: "ghost", onclick: () => { picked = d; splitting = { u: big.u, key: big.key }; sideTab = "day"; draw(); } }, `Split ${big.text}`) : null);
    }
    return null;
  }

  // ---- a day: what opens, split, searches, a review day, notes ----
  function dayPanel(inSide) {
    if (!picked) return null;
    const d = picked;
    const e = dayMap(d, d).get(d) || { chips: [], load: 0 };
    const own = doc.units.filter((u) => u.opens === d && !u.even);
    const spans = doc.units.filter((u) => u.even && u.due && u.opens <= d && d <= u.due);
    const rows = [];
    // 3.4, D1: a pasted search is counted by an author's Anki at its next refresh
    const count = (c) => (c.ids && c.n == null ? null
      : c.ids && c.n > 0 ? h("small", {}, `${c.n.toLocaleString()} card${c.n === 1 ? "" : "s"}`)
      : c.search && c.n == null ? h("small", {}, "counted in your Anki soon")
      : (c.search || c.ids) && c.n === 0 ? h("small", { class: "w" }, "finds nothing") : c.n != null ? h("small", {}, c.n.toLocaleString()) : null);
    const chipEl = (u, c) => h("span", { class: `ch2 ${c.cards || c.ids ? "single" : c.search && c.n === 0 ? "warn" : c.search ? "c2" : hue(c.key)}`, title: c.raw || "" },
      h("span", {}, c.text, c.raw && (c.search || Tags.name(c.raw) !== c.raw) ? h("span", { class: "raw" }, c.raw) : null), count(c),
      author && !c.cards && !c.search && !c.ids ? h("button", { class: "linkish", onclick: () => { splitting = { u, key: c.key }; draw(); } }, "Split") : null,
      author ? h("button", { class: "x", "aria-label": `Take ${c.text} off`, onclick: () => {
        if (c.cards) u.cards = []; else if (c.ids) takeIds(u); else if (c.search) takeSearch(u, c.search); else takeOut(u, c.key);
        cleanup(); renameAll(); mark(); draw(); } }, "×") : null);
    // 3.6.5, P1: what the date opens, as the author's Anki counted it
    const picksOf = (x) => JSON.stringify([x.opens, srcs(x), x.search || [], x.nids || [], x.cids || [], x.notes || []]);
    const opensLine = (u) => {
      // a count is for the date as it was loaded; one changed here is counted again after Save
      const was = (base.units || []).find((x) => x.id === u.id);
      if (u.pn && was && picksOf(was) !== picksOf(u)) return author ? h("small", { class: "muted" }, "Changed: your Anki counts it again after you save.") : null;
      if (author && ((u.nids || []).length || (u.cids || []).length) && !u.idr && !u.pn) return h("small", { class: "warn" }, "Pasted numbers work only in copies like yours until your Anki opens after you save.");
      if (!u.pn) return author && (srcs(u).length || (u.search || []).length || hasIds(u)) ? h("small", { class: "muted" }, "Your Anki counts what this opens at its next refresh.") : null;
      const [n, rep, miss] = u.pn;
      const single = (u.cards || []).length;
      return h("small", { class: "opens" }, h("b", {}, `${(n + single).toLocaleString()} new here`),
        rep ? h("span", { class: "muted" }, ` · ${rep.toLocaleString()} already on an earlier date`) : null,
        miss ? h("span", { class: "warn" }, ` · ${miss.toLocaleString()} picked note${miss === 1 ? "" : "s"} not in your deck`) : null);
    };
    for (const u of own) {
      const chips = e.chips.filter((c) => c.u === u).map((c) => chipEl(u, c));
      if (!author) { rows.push(h("div", { class: "du" }, h("b", {}, u.name), h("div", { class: "chips2" }, chips), opensLine(u))); continue; }
      const name = h("input", { class: "uname", value: u.name, maxlength: 60, placeholder: "Name this day",
        oninput: (ev) => { u.name = ev.target.value; auto.delete(u.id); mark(); } });
      rows.push(h("div", { class: "du" }, h("label", { class: "dl" }, h("span", { class: "lbl" }, "Name"), name), h("div", { class: "chips2" }, chips), opensLine(u)));
    }
    for (const u of spans) {
      const total = unitTotal(u);
      rows.push(h("div", { class: "du" }, h("b", {}, u.name || autoName(u)),
        h("span", { class: "muted small" }, `${total.toLocaleString()} cards, ${pretty(u.opens)} to ${pretty(u.due)}, evenly`),
        author ? h("div", { class: "row" },
          h("button", { class: "quiet", onclick: () => { delete u.even; delete u.due; renameAll(); mark(); draw(); } }, `All on ${pretty(u.opens)}`),
          h("button", { class: "quiet", onclick: () => { doc.units = doc.units.filter((x) => x !== u); mark(); draw(); } }, "Take it off")) : null));
    }
    // B7: the date picker opens on this day, never on today
    const moveIn = author && own.length && moving === d ? h("input", { type: "date", value: d, "aria-label": "Move this day to", onchange: (ev) => {
      const to = ev.target.value; if (!to || to === d) return;
      for (const u of own) { const other = doc.units.find((x) => x.opens === to && !x.even && x !== u); if (other) { for (const k of srcs(u)) addTo(to, k); other.cards = [...(other.cards || []), ...(u.cards || [])]; for (const k of ["nids", "cids", "notes"]) if ((u[k] || []).length) { other[k] = [...new Set([...(other[k] || []), ...u[k]])]; delete other.idn; delete other.idr; } for (const q of u.search || []) { other.search = [...new Set([...(other.search || []), q])]; if (u.sn?.[q] != null) other.sn = { ...(other.sn || {}), [q]: u.sn[q] }; } for (const r of doc.reviews || []) { if (r.from === u.id) r.from = other.id; if (r.to === u.id) r.to = other.id; } doc.units = doc.units.filter((x) => x !== u); } else shiftUnit(u, Sched.diff(to, u.opens)); }
      picked = to; moving = null; renameAll(); byOpens(); mark(); draw(); } }) : null;
    const rv = reviewBox(d);
    const evBoxes = evOn(d).map((x) => eventBox(x));
    const prep = own.length ? prepBox(d, own) : null;
    const makeEv = author && !own.length && !evOn(d).length ? newEventLink(d, null, "Make it an event") : null;
    const rvLink = rv && rv.tagName === "BUTTON" ? rv : null;
    const moveLink = author && own.length && moving !== d ? h("button", { class: "linkish", onclick: () => { moving = d; draw(); } }, "Move this day…") : null;
    return h("section", { class: `dayp${inSide ? " side" : ""}`, "aria-label": pretty(d) },
      inSide ? null : h("div", { class: "row", style: "justify-content:space-between" }, h("b", {}, `${pretty(d)}${e.load ? ` · ${e.load.toLocaleString()} cards` : ""}`),
        h("button", { class: "quiet", "aria-label": "Close", onclick: () => { picked = null; splitting = null; moving = null; draw(); } }, "×")),
      inSide && e.load ? h("span", { class: "muted small" }, `${e.load.toLocaleString()} new cards`) : null,
      splitting ? splitPanel() : null,
      evBoxes,
      rows.length ? rows : evBoxes.length ? null : h("p", { class: "muted small" }, author ? "Nothing yet. Drag a tag here, or use + in What to cover." : "Nothing new this day."),
      prep,
      own.length ? todoBox(own[0]) : null,
      author ? h("div", { class: "addc" }, h("span", { class: "lbl" }, "Add cards"), searchBox(d),
        // 3.6.5: a follower's Anki opens a date once; what's added after comes the next morning
        d <= today() && rows.length ? h("small", { class: "muted" }, "This date has opened. Followers who opened it get what you add tomorrow morning.") : null) : null,
      moveIn ? h("label", { class: "inline" }, "Move to ", moveIn, h("button", { class: "quiet", onclick: (ev) => { ev.preventDefault(); moving = null; draw(); } }, "Cancel")) : null,
      moveLink || rvLink || makeEv ? h("div", { class: "acts" }, moveLink, rvLink, makeEv) : null,
      rv && !rvLink ? rv : null,
      inPlan ? h("div", { class: "notesw" }, author ? h("span", { class: "lbl" }, "Notes for followers") : null, notesBox(d)) : null);
  }

  /** Due: what a date asks that cards can't measure (a lecture to watch,
   *  a chapter to read). Each follower ticks it by hand in Due. */
  function todoBox(u) {
    const lines = u.todo || [];
    if (!author) {
      return lines.length ? h("div", { class: "addc" }, h("span", { class: "lbl" }, "To do"),
        lines.map((x) => h("span", { class: "small" }, h("b", {}, Todo.LABEL[x.k]), ` · ${x.t}`,
          x.url && Todo.okUrl(x.url) ? [" ", h("a", { href: x.url, target: "_blank", rel: "noopener" }, "link")] : null))) : null;
    }
    const set = () => { if (lines.length) u.todo = lines; else delete u.todo; mark(); };
    const rows = lines.map((x, i) => h("div", { class: "todo" },
      h("select", { "aria-label": "Kind", onchange: (e) => { x.k = e.target.value; set(); } },
        Object.entries(Todo.LABEL).map(([k, lb]) => h("option", { value: k, selected: x.k === k }, lb))),
      h("input", { value: x.t, maxlength: 140, placeholder: "Lecture 14, renal clearance", "aria-label": "What to do",
        oninput: (e) => { x.t = e.target.value; set(); } }),
      h("input", { value: x.url || "", maxlength: 500, placeholder: "https:// (optional)", "aria-label": "A link",
        onchange: (e) => { const v = e.target.value.trim(); if (!v) delete x.url; else if (Todo.okUrl(v)) x.url = v; else { e.target.value = x.url || ""; e.target.placeholder = "A link starts with https://"; } set(); } }),
      h("button", { class: "x", "aria-label": "Take this line off", onclick: () => { lines.splice(i, 1); set(); draw(); } }, "×")));
    return h("div", { class: "addc" }, h("span", { class: "lbl" }, "To do"),
      rows,
      lines.length < Todo.MAX ? h("button", { class: "linkish", onclick: () => {
        u.todo = [...lines, { k: "watch", t: "" }]; mark(); draw(); } }, "+ Add a line") : null);
  }

  /** F1: "Prep for": the event this day's dates lead up to. */
  let newEv = null;  // {day, forDay}: the new-event form, open
  function prepBox(d, own) {
    const cur = own[0].for && evById(own[0].for);
    if (!author) return cur ? h("p", { class: "muted small" }, "For ", h("b", {}, cur.name), ` on ${pretty(cur.day)}`) : null;
    const later = events().filter((x) => x.day >= d);
    const sel = h("select", { "aria-label": "Prep for", onchange: (e) => {
      if (e.target.value === "+") { newEv = { day: addDays(d, 3), forDay: d }; draw(); return; }
      for (const u of own) { if (e.target.value) u.for = e.target.value; else delete u.for; }
      mark(); draw(); } },
      h("option", { value: "" }, "Nothing"),
      later.map((x) => h("option", { value: x.id, selected: cur && cur.id === x.id }, `${x.name} · ${pretty(x.day)}`)),
      h("option", { value: "+" }, "+ New event…"));
    return h("div", { class: "addc" }, h("span", { class: "lbl" }, "Prep for"), sel, newEv && newEv.forDay === d ? newEventForm(d, own) : null);
  }
  function newEventForm(d, own) {
    const name = h("input", { placeholder: "Lecture 12, Micro quiz, Block 2 exam", maxlength: 60, "aria-label": "The event's name" });
    const day = h("input", { type: "date", value: newEv.day, min: d, "aria-label": "Its day" });
    const make = () => {
      if (!name.value.trim() || !day.value) { name.focus(); return; }
      const ev = addEvent(day.value, name.value);
      for (const u of own || []) u.for = ev.id;
      newEv = null; mark(); draw();
    };
    name.addEventListener("keydown", (e) => { if (e.key === "Enter") make(); });
    setTimeout(() => name.focus(), 0);
    return h("div", { class: "evform" }, name, h("div", { class: "row" }, day, h("button", { onclick: make }, "Add event"),
      h("button", { class: "quiet", onclick: () => { newEv = null; draw(); } }, "Cancel")));
  }
  function newEventLink(d, own, text) {
    if (newEv && newEv.day === d && newEv.forDay === null) return h("span", {}, newEventForm(d, own));
    return h("button", { class: "linkish", onclick: () => { newEv = { day: d, forDay: null }; draw(); } }, text);
  }
  /** F1: an event's own day: its name, the days that prep for it. */
  let movingEv = null;
  function eventBox(x) {
    const prep = prepOf(x.id).sort((a, b) => a.opens.localeCompare(b.opens));
    const n = prep.reduce((a, u) => a + unitTotal(u), 0);
    const days = prepDays(x.id);
    const say = prep.length ? `${days.length} day${days.length === 1 ? "" : "s"} of prep: ${days.slice(0, 4).map((d) => pretty(d)).join(", ")}${days.length > 4 ? "…" : ""}${n ? ` · ${n.toLocaleString()} cards` : ""}`
      : "No days prep for it yet. Pick it under Prep for on a day.";
    if (!author) return h("div", { class: "evbox" }, h("span", { class: "lbl" }, "Event"), h("b", {}, x.name), h("span", { class: "muted small" }, say));
    const name = h("input", { value: x.name, maxlength: 60, "aria-label": "The event's name", oninput: (e) => { x.name = e.target.value.slice(0, 60); mark(); } });
    const move = movingEv === x.id ? h("label", { class: "inline" }, "Move to ", h("input", { type: "date", value: x.day, "aria-label": "Move the event to", onchange: (e) => {
      if (!e.target.value) return; x.day = e.target.value; doc.events.sort((a, b) => a.day.localeCompare(b.day)); picked = x.day; movingEv = null; mark(); draw(); } }),
      h("button", { class: "quiet", onclick: (ev) => { ev.preventDefault(); movingEv = null; draw(); } }, "Cancel")) : null;
    return h("div", { class: "evbox" }, h("span", { class: "lbl" }, "Event"), name, h("span", { class: "muted small" }, say), move,
      h("div", { class: "acts" }, movingEv === x.id ? null : h("button", { class: "linkish", onclick: () => { movingEv = x.id; draw(); } }, "Move it…"),
        h("button", { class: "linkish", onclick: () => { takeEvent(x); mark(); draw(); } }, "Take it off")));
  }

  /** 3.3, C3: an Anki search as part of a day; each follower's Anki runs it.
   *  E1: or a pasted list of note ids or card ids (a spreadsheet's column). */
  function searchBox(d) {
    const input = h("textarea", { class: "mono addin", rows: 1, placeholder: "Anki search or note IDs", "aria-label": `Cards for ${pretty(d)}: an Anki search, or note IDs` });
    const why = h("small", { class: "warn", role: "status" });
    const found = h("div", { class: "found", hidden: true });
    let kind = "nids";
    const idsIn = () => {
      const t = input.value.trim();
      if (!t || !/^[\d\s,;]+$/.test(t)) return null;
      const got = [...new Set(t.split(/[\s,;]+/).filter(Boolean).map(Number))].filter((x) => Number.isSafeInteger(x) && x > 0);
      return got.length ? got : null;
    };
    // 3.6.5: notes:… or cards:… as Anki's browser copies them (Due Crew › Copy as plan selector)
    const picksIn = () => {
      const t = input.value.trim();
      if (!/^(notes|cards):/i.test(t)) return null;
      const r = Picks.take(t.replace(/\s+/g, " "));
      return r.bad.length || !(r.notes.length || r.cards.length) ? null : r;
    };
    const addPicks = () => {
      const r = picksIn(); if (!r) return;
      const u = unitOn(d);
      const notes = [...new Set([...(u.notes || []), ...r.notes])];
      if (notes.length > 5000) { why.textContent = "A date takes up to 5,000 notes."; return; }
      if (r.notes.length) { u.notes = notes; delete u.idn; }
      const have = new Set((u.cards || []).map(([g, o]) => `${g}:${o}`));
      u.cards = [...(u.cards || []), ...r.cards.filter(([g, o]) => !have.has(`${g}:${o}`))];
      renameAll(); mark(); draw();
    };
    const show = () => {
      const pk = picksIn();
      if (pk) {
        input.rows = 4; found.hidden = false;
        const n = pk.notes.length || pk.cards.length;
        const what = pk.notes.length ? `${n.toLocaleString()} note${n === 1 ? "" : "s"}` : `${n.toLocaleString()} card${n === 1 ? "" : "s"}`;
        found.replaceChildren(h("span", {}, h("b", {}, what), h("span", { class: "muted" }, pk.notes.length ? " · all their cards" : " · just those cards")),
          h("span", { class: "row" }, h("button", { onclick: addPicks }, `Add ${what}`)));
        return;
      }
      const ids = idsIn();
      input.rows = ids || input.value.includes("\n") ? 4 : 1;
      found.hidden = !ids;
      if (!ids) return;
      const seg = h("span", { class: "seg" }, [["nids", "Note IDs"], ["cids", "Card IDs"]].map(([k, t]) =>
        h("button", { class: kind === k ? "on" : "", "aria-pressed": String(kind === k), onclick: () => { kind = k; show(); } }, t)));
      const n = ids.length;
      found.replaceChildren(
        h("span", {}, h("b", {}, `${n.toLocaleString()} ${kind === "nids" ? "note" : "card"} ID${n === 1 ? "" : "s"}`),
          h("span", { class: "muted" }, kind === "nids" ? " · all their cards" : " · just those cards")),
        n > 5000 ? h("span", { class: "warn" }, "A date takes up to 5,000. Split the list over two dates.") : h("span", { class: "muted small" }, "Your Anki counts them at its next refresh, as it does a search."),
        h("span", { class: "row" }, seg, n <= 5000 ? h("button", { onclick: addIds }, `Add ${n.toLocaleString()} ${kind === "nids" ? "note" : "card"}${n === 1 ? "" : "s"}`) : null));
    };
    const addIds = () => {
      const ids = idsIn(); if (!ids || ids.length > 5000) return;
      const u = unitOn(d);
      const all = [...new Set([...(u[kind] || []), ...ids])];
      if (all.length > 5000) { why.textContent = "A date takes up to 5,000 IDs of each kind."; return; }
      u[kind] = all; delete u.idn;
      renameAll(); mark(); draw();
    };
    const add = () => {
      if (picksIn()) return addPicks();
      if (idsIn()) return addIds();
      const q = input.value.trim(); if (!q) return;
      if (q.length > 500) { why.textContent = "A search is at most 500 characters."; return; }
      // the same rule as the add-on's (plans.shareable_search): nothing about one person's own Anki
      if (PERSONAL.test(q)) { why.textContent = "That finds different cards in each person's Anki. Use tags or decks."; return; }
      const u = unitOn(d);
      u.search = [...new Set([...(u.search || []), q])];
      renameAll(); mark(); draw();
    };
    input.addEventListener("input", () => { why.textContent = ""; show(); });
    input.addEventListener("keydown", (ev) => { if (ev.key === "Enter" && !ev.shiftKey && !idsIn() && !picksIn()) { ev.preventDefault(); add(); } });
    return h("div", { class: "stack", style: "gap:6px" }, h("div", { class: "row", style: "align-items:flex-start" }, input, h("button", { class: "quiet", onclick: add }, "Add")), found, why);
  }

  /** 3.3, C4: a review day: that morning, a filtered deck of a range of dates. */
  function reviewBox(d) {
    const us = [...doc.units].sort((a, b) => a.opens.localeCompare(b.opens));
    const r = (doc.reviews || []).find((x) => x.day === d);
    const byId = new Map(us.map((u) => [u.id, u]));
    if (!author) return r && byId.get(r.from) ? h("p", { class: "muted small" }, `Review day: ${byId.get(r.from).name} to ${byId.get(r.to).name}.`) : null;
    const before = us.filter((u) => u.opens <= d);
    if (!before.length) return null;
    if (!r) return h("button", { class: "linkish", onclick: () => {
      (doc.reviews ||= []).push({ day: d, from: before[Math.max(0, before.length - 5)].id, to: before[before.length - 1].id }); mark(); draw(); } }, "Make it a review day");
    const pick = (k) => h("select", { "aria-label": k === "from" ? "Review from" : "Review to", onchange: (e) => { r[k] = e.target.value; mark(); draw(); } },
      us.map((u) => h("option", { value: u.id, selected: r[k] === u.id }, `${u.name} · ${pretty(u.opens)}`)));
    return h("div", { class: "rvbox" }, h("b", {}, "Review day"),
      h("div", { class: "row" }, pick("from"), "to", pick("to"),
        h("button", { class: "quiet", "aria-label": "No review day", onclick: () => { doc.reviews = doc.reviews.filter((x) => x !== r); if (!doc.reviews.length) delete doc.reviews; mark(); draw(); } }, "×")));
  }

  /** Notes on a day, from anyone in the plan ("lab day, keep it light").
   *  In the library, where anyone can follow, only the authors write them. */
  function notesBox(d) {
    const list = notes.filter((x) => x.day === d);
    if (plan.library && !author) {
      return list.length ? h("div", { class: "notes" }, list.map((x) => h("div", { class: "note" }, h("b", {}, x.mine ? "You" : x.name), " ", h("span", {}, x.text)))) : null;
    }
    const input = h("input", { placeholder: "Add a note", maxlength: 280, "aria-label": `A note on ${pretty(d)}`, style: "width:100%" });
    const add = async () => {
      const text = input.value.trim(); if (!text) return;
      input.disabled = true;
      try {
        const r = await api("POST", `/plans/${id}/notes`, { day: d, text });
        notes.push({ id: r.id, uid: me.uid, name: me.name || "You", emoji: "", day: d, text: r.text, at: Date.now() / 1000, mine: true, remove: true });
        draw();
      } catch { input.disabled = false; input.value = text; }
    };
    input.addEventListener("keydown", (ev) => { if (ev.key === "Enter") add(); });
    return h("div", { class: "notes" },
      list.map((x) => h("div", { class: "note" }, h("b", {}, x.mine ? "You" : x.name), " ", h("span", {}, x.text),
        x.remove ? h("button", { class: "x", "aria-label": "Remove this note", onclick: async () => {
          try { await api("DELETE", `/plans/${id}/notes/${x.id}`); } catch { return; }
          notes = notes.filter((y) => y !== x); draw(); } }, "×") : null)),
      input);
  }

  function splitPanel() {
    const { u, key } = splitting;
    const placed = placedKeys();
    const total = eff(key, placed);
    const ks = kidsOf(key).filter((k) => !isPlaced(k, placed) && eff(k, placed) > 0);
    const cap = paceDaily() || 0;
    let how = ks.length ? "tags" : "even";
    const days = h("input", { type: "number", min: 2, max: 60, value: Math.max(2, cap ? Math.ceil(total / cap) : 3), style: "width:5em", "aria-label": "Days" });
    const per = h("span", { class: "muted small" });
    const upd = () => { per.textContent = `≈ ${Math.ceil(total / Math.max(2, Number(days.value) || 2)).toLocaleString()} a day`; };
    days.addEventListener("input", upd); upd();
    const opt = (v, body, disabled) => h("label", { class: `opt3${disabled ? " dis" : ""}` },
      h("input", { type: "radio", name: "how", value: v, checked: how === v, disabled, onchange: () => { how = v; } }), body);
    const search = `"tag:${pathOf(key)}"`;
    const rest = only(key);
    const go2 = () => {
      if (how === "tags") {
        takeOut(u, key);
        const items = ks.map((k) => ({ key: k, n: eff(k, placed) }));
        if (rest > 0) items.push({ key, n: rest, rest: true, even: !!cap && rest > cap });
        const r = fill(items, u.opens, null, cap);
        note = `Split over ${pretty(firstStudy(u.opens))} to ${pretty(r.lastD || u.opens)}.`;
      } else if (how === "even") {
        takeOut(u, key);
        const e = evenUnit(u.opens, key, Math.max(2, Math.min(60, Math.round(Number(days.value) || 2))));
        note = `Split evenly over ${pretty(e.opens)} to ${pretty(e.due || e.opens)}.`;
      } else return;
      splitting = null; cleanup(); renameAll(); byOpens(); mark(); draw();
    };
    return h("div", { class: "splitp" },
      h("b", {}, `Split “${label(key, placed)}” · ${total.toLocaleString()} cards`),
      opt("tags", h("span", {}, h("b", {}, "By its tags"), " ", h("span", { class: "muted small" },
        ks.length ? `${ks.slice(0, 6).map((k) => `${Tags.word(pathOf(k).split("::").pop())} ${eff(k, placed)}`).join(" · ")}${ks.length > 6 ? ` · ${ks.length - 6} more` : ""}${rest > 0 ? ` · the rest ${rest}` : ""}, ${cap ? `at ${cap} a day` : "one a study day"}` : "nothing below this tag")), !ks.length),
      opt("even", h("span", {}, h("b", {}, "Evenly over "), days, " study days ", per)),
      opt("anki", h("span", {}, h("b", {}, "Pick cards in Anki"), " ", h("code", {}, search), " ",
        h("button", { class: "quiet", onclick: (ev) => { ev.preventDefault(); copy(search, ev.target); } }, "Copy"),
        h("span", { class: "muted small" }, " · browse, select, Due Crew: add to a plan"))),
      h("div", { class: "row", style: "justify-content:flex-end" }, h("button", { class: "quiet", onclick: () => { splitting = null; draw(); } }, "Cancel"), h("button", { onclick: go2 }, "Split")));
  }

  // ---- the list: every date, with its dates to type ----
  function listView() {
    byOpens();
    if (!doc.units.length) return h("p", { class: "muted" }, "No dates yet. Tick what to cover and Lay it out, or drag a tag onto the calendar.");
    const placed = placedKeys();
    return h("div", { class: "units" }, doc.units.map((u) => {
      const name = h("input", { class: "uname", value: u.name, maxlength: 60, "aria-label": "Date name", oninput: (e) => { u.name = e.target.value; auto.delete(u.id); mark(); } });
      const opens = h("input", { type: "date", value: u.opens, "aria-label": "Opens", onchange: (e) => { if (e.target.value) { const k = Sched.diff(e.target.value, u.opens); shiftUnit(u, k); if (u.check && u.check < u.opens) delete u.check; byOpens(); mark(); draw(); } } });
      const due = h("input", { type: "date", value: u.due || "", min: u.opens, "aria-label": "Due", onchange: (e) => { u.due = e.target.value && e.target.value >= u.opens ? e.target.value : undefined; if (!u.due || u.due === u.opens) delete u.even; mark(); draw(); } });
      const even = h("input", { type: "checkbox", checked: !!u.even, disabled: !u.due || u.due === u.opens, onchange: (e) => { if (e.target.checked) u.even = true; else delete u.even; mark(); draw(); } });
      const chips = h("div", { class: "chips2" }, srcs(u).map((k) => h("span", { class: `ch2 ${hue(k)}`, title: pathOf(k) }, h("span", {}, label(k, placed), h("span", { class: "raw" }, pathOf(k))), h("small", {}, eff(k, placed).toLocaleString()),
        h("button", { class: "x", "aria-label": `Remove ${pathOf(k)}`, onclick: () => { takeOut(u, k); cleanup(); renameAll(); mark(); draw(); } }, "×"))),
        (u.search || []).map((q) => h("span", { class: `ch2 ${u.sn?.[q] === 0 ? "warn" : "c2"}`, title: q }, h("span", {}, searchName(q), h("span", { class: "raw" }, q)),
          u.sn?.[q] != null ? h("small", {}, u.sn[q].toLocaleString()) : null,
          h("button", { class: "x", "aria-label": `Remove the search ${q}`, onclick: () => { takeSearch(u, q); cleanup(); renameAll(); mark(); draw(); } }, "×"))),
        (u.cards || []).length ? h("span", { class: "ch2 single" }, `${u.cards.length} single card${u.cards.length === 1 ? "" : "s"}`) : null,
        hasIds(u) ? h("span", { class: "ch2 single" }, idsText(u), u.idn ? h("small", {}, `${u.idn.toLocaleString()} card${u.idn === 1 ? "" : "s"}`) : null,
          h("button", { class: "x", "aria-label": "Remove the IDs", onclick: () => { takeIds(u); cleanup(); renameAll(); mark(); draw(); } }, "×")) : null);
      return h("div", { class: "unit" }, h("span"), h("div", {}, name, chips),
        h("div", { class: "dates" }, h("span", {}, "Opens ", opens), h("span", {}, "Due ", due), h("label", { class: "inline" }, even, " evenly over its days"),
          h("button", { class: "del", "aria-label": `Delete ${u.name}`, onclick: () => { doc.units = doc.units.filter((x) => x !== u); mark(); draw(); } }, "×")));
    }));
  }

  // ---- as text ----
  const CARDS_TEXT = 500;
  const toText = () => { byOpens(); return [...events().map((x) => `${x.day} | event | ${x.name}`), ...doc.units.map((u) => [u.opens, u.name,
    [...(u.tags || []).map((t) => `tag:${t}`), ...(u.decks || []).map((d) => `deck:${d}`)].join(", "),
    ...(u.search || []).map((q) => `search:${q}`),
    (u.nids || []).length ? `nids:${u.nids.join(",")}` : "", (u.cids || []).length ? `cids:${u.cids.join(",")}` : "",
    (u.notes || []).length ? Picks.notesText(u.notes) : "",
    u.due ? `due ${u.due}` : "", u.even ? "even" : "",
    // 3.6.5: single cards as cards: (a long list stays a count, kept as it is)
    (u.cards || []).length > CARDS_TEXT ? `${u.cards.length} single cards` : (u.cards || []).length ? Picks.cardsText(u.cards) : "",
    u.for && evById(u.for) ? `for ${evById(u.for).name}` : "",
    // Due: the author's lines, each one part ("watch: lecture 14 https://…")
    ...(u.todo || []).map((x) => `${x.k}: ${x.t}${x.url ? ` ${x.url}` : ""}`)].filter(Boolean).join(" | "))].sort().join("\n"); };

  // what an AI (or a person) might write for a tag: the exact path, any
  // case, or its readable name
  const byLower = new Map([...count.keys()].map((k) => [k.toLowerCase(), k]));
  const byName = new Map([...count.keys()].map((k) => [`${kindOf(k)}:${Tags.name(pathOf(k)).toLowerCase()}`, k]));
  const findKey = (kind, p) => byLower.get(`${kind}:${p.toLowerCase()}`) || byName.get(`${kind}:${p.toLowerCase()}`) || `${kind}:${p}`;

  function fromText(text) {
    const errors = [];
    const units = [];
    const notes = [];
    const evs = [];     // F1: "2026-10-15 | event | Micro quiz"
    const forName = new Map();  // unit id -> the event name it's for
    const warns = [];
    let localIds = 0;  // dates with pasted numbers not yet turned into note IDs by the author's Anki
    const why = [];  // 3.6.5: the AI's own notes (which video, and why), shown, never imported
    text.split("\n").forEach((raw, i) => {
      let line = raw.trim().replace(/^[-*•]\s+/, "").replace(/^`([^`].*)`$/, "$1");
      if (!line || /^```/.test(raw.trim())) return;
      // 3.6.5: notes: and cards: first; a guid can hold | and `
      const picks = line.startsWith("#") ? null : Picks.take(line);
      if (picks) line = picks.line;
      line = line.replace(/`/g, "");
      if (line.startsWith("#")) { (/\bpick\b|\bsingle\b/i.test(line) ? notes : why).push(line.replace(/^#+\s*/, "")); return; }
      const parts = line.split(/\s*\|\s*|\s{2,}/).filter(Boolean);
      if (parts.length >= 3 && /^\d{4}-\d{2}-\d{2}$/.test(parts[0]) && /^event$/i.test(parts[1])) {
        const full = parts.slice(2).join(" ");
        const name = full.slice(0, 60);
        if (full.length > 60) warns.push(`Line ${i + 1}: the event's name is cut to 60 characters.`);
        const old = events().find((x) => x.name.toLowerCase() === name.toLowerCase());
        evs.push({ id: old?.id || uid8(), day: parts[0], name });
        return;
      }
      let forN = null; let keepCards = false;
      let opens = null; let due; let even = false; let name = ""; const tags = []; const decks = []; const searches = []; const ids = { nids: [], cids: [] };
      const todo = [];  // Due: "watch: lecture 14 https://…", "read: …", "do: …"
      for (const part of parts) {
        let m;
        if (!opens && (m = /^(\d{4}-\d{2}-\d{2})$/.exec(part))) opens = m[1];
        else if (!opens && (m = /^week\s+(\d+)$/i.exec(part))) opens = addDays(start, (Number(m[1]) - 1) * 7);
        else if ((m = /^due\s+(\d{4}-\d{2}-\d{2})$/i.exec(part))) due = m[1];
        else if (/^even(ly)?$/i.test(part)) even = true;
        else if ((m = /^for\s+(.+)$/i.exec(part))) forN = m[1].trim();
        else if (/^\d+ single cards?$/.test(part)) keepCards = true;
        else if (/^search:/i.test(part)) searches.push(part.slice(7).trim());
        else if ((m = /^(watch|read|do):\s*(.+)$/i.exec(part))) todo.push(Todo.parse(m[1], m[2]));
        else if ((m = /^(nids|cids|ids):\s*([\d\s,;]+)$/i.exec(part))) ids[m[1].toLowerCase() === "cids" ? "cids" : "nids"].push(...m[2].split(/[\s,;]+/).filter(Boolean).map(Number).filter((x) => Number.isSafeInteger(x) && x > 0));
        else if (/^(tag|deck):/i.test(part)) {
          for (const x of part.split(/\s*[,;]\s*(?=(?:tag|deck):)/i)) {
            const kind = x.slice(0, 4).toLowerCase() === "deck" ? "deck" : "tag";
            const key = findKey(kind, x.slice(x.indexOf(":") + 1).trim());
            (kind === "tag" ? tags : decks).push(pathOf(key));
          }
        } else name = name ? `${name} ${part}` : part;
      }
      if (!opens) { errors.push(`Line ${i + 1}: starts with a date (2026-10-05) or "week 3".`); return; }
      if (searches.some((q) => PERSONAL.test(q))) { errors.push(`Line ${i + 1}: that search finds different cards in each person's Anki; use tags.`); return; }
      if (picks.bad.length) { errors.push(`Line ${i + 1}: "${picks.bad[0].slice(0, 30)}" isn't a note's ID from Anki (cards: takes ID:N, N the card's number from 1).`); return; }
      if (!tags.length && !decks.length && !searches.length && !ids.nids.length && !ids.cids.length && !picks.notes.length && !picks.cards.length && !keepCards) { errors.push(`Line ${i + 1}: needs a tag:, a deck:, a search: or notes:.`); return; }
      if (ids.nids.length > 5000 || ids.cids.length > 5000 || picks.notes.length > 5000) { errors.push(`Line ${i + 1}: a date takes up to 5,000 IDs.`); return; }
      if (due && due < opens) { errors.push(`Line ${i + 1}: due is before it opens.`); return; }
      if (even && !(due && due > opens)) { errors.push(`Line ${i + 1}: "even" needs a due date after it opens.`); return; }
      // 3.6.5: names compared as they're kept (60 at most, trimmed), so a long one still finds its date
      const key = (name || leaf(tags[0] || decks[0]) || "").slice(0, 60).trim();
      const old = doc.units.find((u) => u.opens === opens && String(u.name || "").trim() === key);
      if (name.length > 60) warns.push(`Line ${i + 1}: the name is cut to 60 characters.`);
      // single cards: as written (cards:), plus the ones a count stands for; neither keeps what it had
      const had = picks.cards.length && !keepCards ? [] : old?.cards || [];
      const seen = new Set(had.map(([g, o]) => `${g}:${o}`));
      const cards = [...had, ...picks.cards.filter(([g, o]) => !seen.has(`${g}:${o}`))];
      if (!tags.length && !decks.length && !searches.length && !ids.nids.length && !ids.cids.length && !picks.notes.length && !cards.length) { errors.push(`Line ${i + 1}: needs a tag:, a deck:, a search: or notes:.`); return; }
      const u = { id: old?.id || uid8(), name: (name || "").slice(0, 60), opens, due, tags: [...new Set(tags)], decks: [...new Set(decks)], cards };
      if (even) u.even = true;
      if (searches.length) {
        u.search = [...new Set(searches)];
        const sn = Object.fromEntries(u.search.filter((q) => old?.sn?.[q] != null).map((q) => [q, old.sn[q]]));
        if (Object.keys(sn).length) u.sn = sn;  // a search kept as it was keeps its count
      }
      for (const k of ["nids", "cids"]) if (ids[k].length) u[k] = [...new Set(ids[k])];
      if (picks.notes.length) u.notes = picks.notes;
      if (hasIds(u) && old && JSON.stringify([old.nids, old.cids, old.notes]) === JSON.stringify([u.nids, u.cids, u.notes]) && old.idn != null) u.idn = old.idn;
      if ((u.nids || u.cids) && !(old?.idr && JSON.stringify([old.nids, old.cids]) === JSON.stringify([u.nids, u.cids]))) localIds++;
      if (todo.length > Todo.MAX) warns.push(`Line ${i + 1}: a date keeps ${Todo.MAX} lines to tick; the rest are left off.`);
      if (todo.length) u.todo = todo.slice(0, Todo.MAX);
      if (forN) forName.set(u.id, forN);
      if (!u.due) delete u.due;
      if (!u.name) { u.name = autoName(u); auto.add(u.id); }
      units.push(u);
    });
    const missing = units.flatMap((u) => [...u.tags.map((t) => `tag:${t}`), ...u.decks.map((d) => `deck:${d}`)]).filter((k) => count.size && !count.has(k));
    for (const u of units) {
      const n = forName.get(u.id); if (!n) continue;
      const ev = [...evs, ...events()].find((x) => x.name.toLowerCase() === n.toLowerCase());
      if (ev) u.for = ev.id; else errors.push(`"for ${n}": no event by that name. Add a line like 2026-10-15 | event | ${n}`);
    }
    // 3.6.5: pasted ids are this Anki's own numbers until the author's Anki sends what they are
    if (localIds) warns.push(`${localIds} date${localIds === 1 ? " uses" : "s use"} nids: or cids:, your Anki's own numbers. Open Anki after you save, and they'll work in everyone's copy.`);
    return { units, errors, missing, notes, events: evs, warns, why: why.filter(Boolean).slice(0, 60) };
  }

  /** The prompt for your own AI: the plan so far, the format, the deck's tags. */
  function aiPrompt() {
    const dayNames = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].filter((_, i) => pace.days[i]).join(", ");
    const ph = doc.phases || {};
    // the tags: what's ticked, whole; else the top levels, and resources
    // (a # part, a video or a book) five levels down; at most 600 lines.
    // 3.6.5: a tag whose last part has no readable name (a number, a hash)
    // isn't listed; a branch of mostly those is one line.
    const keys = [];
    const segs = (k) => pathOf(k).split("::");
    const unreadable = (k) => { const w = segs(k).pop().replace(/^[#^$!]+/, ""); return /^\d+$/.test(w) || /^[0-9a-f-]{12,}$/i.test(w) || (/^[A-Za-z0-9_-]{24,}$/.test(w) && /\d/.test(w)); };
    const inRes = (k) => segs(k).slice(1).some((x) => x.startsWith("#"));
    const rank = (k) => { const last = segs(k).pop(); return last.startsWith("#") ? 0 : last.startsWith("^") ? 1 : 2; };
    const order = (ks) => ks.slice().sort((a, b) => rank(a) - rank(b));
    const collapsed = new Map();  // key -> how many unreadable tags it stands for
    const walk2 = (k, depth) => {
      if (keys.length >= 600 || unreadable(k)) return;
      keys.push(k);
      const ks = kidsOf(k);
      const odd = ks.filter(unreadable).length;
      if (ks.length >= 10 && odd >= ks.length * 0.8) { collapsed.set(k, odd); return; }
      if (cover.size || depth < 2 || (inRes(k) && depth < 5)) for (const c of order(ks)) walk2(c, depth + 1);
    };
    for (const k of order(cover.size ? coverItems() : kidsOf("root:tag").concat(kidsOf("root:deck")))) walk2(k, 0);
    const more = count.size - keys.length;
    const lines = keys.map((k) => `${kindOf(k)}:${pathOf(k)}  (${n(k).toLocaleString()} cards) ${Tags.name(pathOf(k))}`
      + (collapsed.has(k) ? ` [${collapsed.get(k).toLocaleString()} numbered tags under it, not listed]` : ""));
    return [
      `I'm planning what to study in Anki, day by day, for "${meta.name || plan.name}" on the deck "${doc.deck}". Due Crew opens each day's cards (unsuspends them) on the morning of that day, for me and everyone following the plan.`,
      "",
      "The plan so far:",
      `- Starts ${start}${doc.end ? `, ends ${doc.end}` : ", no end date yet"}.`,
      `- Study days: ${dayNames}.`,
      pace.mode === "daily" && pace.daily ? `- About ${pace.daily} new cards a study day.` : pace.mode === "end" && doc.end ? "- Finish everything by the end date, at an even pace." : "- Each date's cards are for that date; nothing spreads over days unless its line says even.",
      ph.catchup ? `- Every ${ph.catchup}th week is a catch-up week: nothing new opens.` : null,
      ph.taper ? `- The last ${ph.taper} days before the end open nothing new.` : null,
      doc.units.length ? `- ${doc.units.length} dates are already planned (as text below the tags); keep or change them.` : null,
      "",
      "Write the plan in exactly this format, one line per date, and nothing else (no table; anything you want to explain goes on a line starting with #):",
      "",
      "YYYY-MM-DD | a short name (60 characters at most) | tag:FULL::TAG::PATH, tag:ANOTHER::PATH | due YYYY-MM-DD | even | for EVENT NAME",
      "YYYY-MM-DD | a short name (60 characters at most) | notes:ID ID ID | cards:ID:2 ID:1",
      "",
      "Rules:",
      "- The first part is the date those cards open: YYYY-MM-DD, or \"week 3\" for the Monday of the plan's third week.",
      "- A tag brings every card under it. A whole chapter is its tag; a smaller part is a deeper tag (a section, a lecture). Copy tags exactly from the list below, the part before the two spaces; never invent one.",
      "- A subdeck works the same way: deck:FULL::DECK::PATH.",
      "- When a lecture is only part of a tag (two tags at once, or one without another), use an Anki search instead: search:tag:A tag:B -tag:C.",
      "- Several tags can open the same day: separate them with commas on one line.",
      "- Exact notes: notes:ID ID ID brings every card of those notes (every cloze), the IDs separated by spaces. Exact cards: cards:ID:N ID:N brings card N of each note (1 is the first). These IDs can hold any character but a space; copy each exactly. For a plan others follow, use notes: and cards:; numeric nids: and cids: only work in my own Anki. Use only IDs I give you below; never invent, guess or round one. At most 5,000 on a line; split a longer list over dates.",
      "- An Anki search never uses deck:current, is:due, is:new, is:learn, is:review, is:suspended, is:buried, rated:, prop:, introduced:, added:, edited:, resched:, flag:, nid: or cid: (they find different cards for each person), and stays under 500 characters.",
      "- Events are named days with no cards (a lecture, a quiz, an exam): YYYY-MM-DD | event | Micro quiz. A date that preps for one ends with | for Micro quiz, the name exactly as on its event line.",
      "- A date can ask for things cards can't measure, ticked by hand (up to 8): | watch: Lecture 14, renal clearance | read: chapter 6 | do: practice block 3. A link may follow the words: | watch: Lecture 14 https://example.com/l14",
      "- A chapter too big for one day: put its deeper tags on different days, or give it a due date and the word even to spread it evenly from its date to its due date (\"| due 2026-10-09 | even\").",
      "- Without a due date, a date's cards are meant to be done before the next date opens.",
      "- If a day needs specific cards and I gave you no IDs for them, don't guess: add a line starting with # that says which (\"# Pick in Anki for 2026-10-06: the iron-study cards from Lecture 17\"); I'll pick them in Anki.",
      "- Leave out days off and catch-up weeks.",
      "",
      "Resources, and my cards if I attached them:",
      "- Many decks file cards under a resource: a video, a lecture, a book's chapter. If tags below look like that, a resource's tag brings every card filed under it. For each topic, pick the resource that best matches what my course needs, and keep its cards together on one date; a few extra cards from a good match are fine, and so is opening something a little before it's taught.",
      "- What my course needs to know decides what goes in, not which resource it's filed under: look beyond the chosen tags for other cards it needs.",
      "- If I attached a text file exported from Anki, it's my cards: one note per line, tab-separated. Its first lines say which column is which (#guid column:N is the note's ID, #tags column:N its tags). Use the card text to judge what each resource and tag actually covers; a tag doesn't prove every card under it is taught.",
      "- To add cards the chosen tags miss, use notes: with IDs from the #guid column, copied exactly (they can hold any character but a space). Never quote or copy card text into the plan.",
      "- If my course needs something no card covers, say so on a # line; don't invent cards.",
      "- After the plan, one # line per date at most: what you chose for it, and why.",
      "",
      "Before you answer, check the plan (yours and what's already planned):",
      "- Every topic or objective I gave is on a date, or named on a # Missing: line. Look through all the deck's tags before saying the deck doesn't have it.",
      "- No date mostly repeats an earlier one, and none brings many cards my course doesn't need. A good video's whole set can bring a few extra; keep it and say so.",
      "- A date that's for an event opens before that event, with time to study it.",
      "- Name each problem on its own line: # Problem: (something that's wrong), # Tradeoff: (a choice I might make differently), # Question: (something you can't tell from what I gave). Name the date. Skip what's fine.",
      "- If I only ask you to check the plan, answer with # lines only.",
      doc.units.length ? "- Write only new dates, or what to add to a date already planned: a line with the same date and name as one below adds to it. Dates below stay as they are unless I ask to change them; then give the whole plan." : null,
      doc.units.length ? "- Keep every notes:, cards:, nids: and cids: in the plan below on its line, exactly as written, unless I ask to move or drop it." : null,
      "",
      "Example:",
      "2026-10-05 | Microcytic anemias | tag:Heme::Red_cells::Microcytic",
      "2026-10-06 | Hemolysis | tag:Heme::Red_cells::Hemolytic | due 2026-10-08 | even | for Heme quiz",
      "2026-10-07 | Lecture 12 cards | notes:Ab3$kL9qZ1 p&x8Hk!eQ2 | for Heme quiz",
      "2026-10-09 | event | Heme quiz",
      "",
      "My syllabus, learning objectives and exam dates, or what I want (edit this part):",
      "",
      "",
      "Note IDs or card IDs I have, and what each list is for (in Anki's browser: select them, right-click, Due Crew: copy as plan selector; paste here, or leave this empty):",
      "",
      "",
      `The deck's tags${cover.size ? " for what the plan covers" : ""} (tag or subdeck, card count, readable name)${more > 0 ? `; ${more.toLocaleString()} more aren't listed, ask me for a branch` : ""}:`,
      ...lines,
      doc.units.length ? ["", "Already planned:", toText()] : [],
      // 3.6.5, P1: what each planned date opens, as the author's Anki counted it
      doc.units.some((u) => u.pn) ? ["", "What each planned date opens, as my Anki counted it (new to that date, already on an earlier date, picked notes not in my deck):",
        ...doc.units.filter((u) => u.pn).map((u) => `${u.opens} ${u.name}: ${u.pn[0] + (u.cards || []).length} new, ${u.pn[1]} repeat, ${u.pn[2]} not in my deck`)] : [],
    ].flat().filter((x) => x !== null).join("\n");
  }

  // 3.6.5: Text opens on Add dates (pasting can't take anything off); Edit
  // the whole plan is the box with every date in it
  let textMode = "add";
  function textTab() {
    const adding = textMode === "add";
    const ta = h("textarea", { rows: adding ? 8 : Math.max(10, doc.units.length + 3), "aria-label": adding ? "New dates as text" : "The plan as text",
      placeholder: adding ? "Paste new lines here: an AI's answer, or your own.\n2026-10-07 | Adrenergics | tag:… | for Quiz 2" : "" });
    ta.value = adding ? "" : toText();
    const out = h("div", { class: "status", role: "status" });
    const preview = h("div");
    const read = () => {
      const r = fromText(ta.value);
      preview.replaceChildren();
      if (r.errors.length) { out.className = "status bad"; out.textContent = r.errors.slice(0, 6).join(" "); return; }
      if (!r.units.length && !r.events.length && !r.why.length && !r.notes.length) { out.className = "status"; out.textContent = "Nothing to read yet."; return; }
      out.className = r.missing.length ? "status bad" : "status";
      out.textContent = `${r.units.length} date${r.units.length === 1 ? "" : "s"}${r.events.length ? `, ${r.events.length} event${r.events.length === 1 ? "" : "s"}` : ""}.${r.missing.length ? ` Not in your deck (they'd find nothing): ${r.missing.slice(0, 5).map((k) => pathOf(k)).join(", ")}${r.missing.length > 5 ? "…" : ""}` : ""}`;
      const placed = new Set(r.units.flatMap(srcs));
      const joins = (u) => adding && doc.units.some((x) => x.id === u.id);
      // P1: a date as it was keeps its count from the author's Anki
      const counted = (u) => {
        const was = doc.units.find((x) => x.id === u.id);
        if (!was?.pn || adding || JSON.stringify([srcs(was), was.search, was.nids, was.cids, was.notes, was.opens]) !== JSON.stringify([srcs(u), u.search, u.nids, u.cids, u.notes, u.opens])) return "";
        return `${(was.pn[0] + (u.cards || []).length).toLocaleString()} new · ${was.pn[1].toLocaleString()} repeat · ${was.pn[2].toLocaleString()} not in your deck`;
      };
      const rows = r.units.slice().sort((a, b) => a.opens.localeCompare(b.opens)).map((u) => h("div", { class: "pvrow" },
        h("span", {}, pretty(u.opens)), h("span", {}, h("b", {}, u.name), joins(u) ? h("span", { class: "muted small" }, " · adds to this date") : null, " ",
          h("span", { class: "muted small" }, srcs(u).map((k) => (count.has(k) ? label(k, placed) : `${pathOf(k)} (not found)`)).join(", "))),
        h("span", { class: "muted small" }, `${u.due ? `to ${pretty(u.due)}${u.even ? ", evenly" : ""} · ` : ""}${counted(u) || `${unitTotal(u, placed).toLocaleString()} cards`}`)));
      // Add: new dates go on; a line with a date's own day and name adds its picks to it
      const merge = (into, u) => {
        for (const k of ["tags", "decks", "search", "nids", "cids", "notes"]) {
          if (!(u[k] || []).length) continue;
          const was = JSON.stringify(into[k] || []);
          into[k] = [...new Set([...(into[k] || []), ...u[k]])];
          if (JSON.stringify(into[k]) !== was && (k === "nids" || k === "cids" || k === "notes")) delete into.idn;
        }
        const have = new Set((into.cards || []).map(([g, o]) => `${g}:${o}`));
        into.cards = [...(into.cards || []), ...(u.cards || []).filter(([g, o]) => !have.has(`${g}:${o}`))];
        for (const k of ["due", "even", "for"]) if (u[k]) into[k] = u[k];
        if ((u.todo || []).length) {  // Due: its lines, each once
          const had = new Set((into.todo || []).map((x) => `${x.k}:${x.t.toLowerCase()}`));
          into.todo = [...(into.todo || []), ...u.todo.filter((x) => !had.has(`${x.k}:${x.t.toLowerCase()}`))].slice(0, Todo.MAX);
        }
      };
      const use = (replace) => {
        if (r.events.length || replace) {
          const keep = replace ? [] : events().filter((x) => !r.events.some((y) => y.id === x.id));
          doc.events = [...keep, ...r.events].sort((a, b) => a.day.localeCompare(b.day));
          if (!doc.events.length) delete doc.events;
        }
        if (replace) doc.units = r.units;
        else for (const u of r.units) { const x = doc.units.find((y) => y.id === u.id); if (x) merge(x, u); else doc.units.push(u); }
        byOpens(); mark(); preview.replaceChildren(); out.className = "status";
        out.textContent = replace ? `Now ${doc.units.length} dates. Save to keep them.` : `Added. Now ${doc.units.length} dates. Save to keep them.`;
        ta.value = replace ? toText() : "";
      };
      const gone = adding ? [] : doc.units.filter((x) => !r.units.some((u) => u.id === x.id));
      // 3.6.5: a day over the pace, as it would be after this
      const cap = pace.mode === "end" ? endDaily() || pace.daily : pace.mode === "daily" ? pace.daily : 0;
      const after = adding ? [...doc.units.filter((x) => !r.units.some((u) => u.id === x.id)), ...r.units] : r.units;
      const byDay = new Map();
      for (const u of after) if (!u.even) byDay.set(u.opens, (byDay.get(u.opens) || 0) + unitTotal(u, placed));
      const heavy = cap ? [...byDay].filter(([, n]) => n > cap * 1.25).sort() : [];
      const goneText = gone.slice(0, 6).map((u) => `${pretty(u.opens)}, ${u.name}`).join(" · ") + (gone.length > 6 ? ` and ${gone.length - 6} more` : "");
      preview.append(h("div", { class: "pv" }, rows,
        gone.length ? h("p", { class: "warn small" }, h("b", {}, `Takes off ${gone.length} date${gone.length === 1 ? "" : "s"}: `), goneText) : null,
        heavy.length ? h("p", { class: "warn small" }, h("b", {}, "Over your pace: "), heavy.slice(0, 6).map(([d, n]) => `${pretty(d)}, ${n.toLocaleString()} new`).join(" · "),
          ` (pace ${cap.toLocaleString()} a day)`) : null,
        r.warns.length ? h("p", { class: "warn small" }, r.warns.slice(0, 4).join(" ")) : null,
        r.notes.length ? h("div", { class: "hnote" }, h("span", {}, h("b", {}, "To pick in Anki: "), r.notes.join(" · "))) : null,
        r.why.length ? h("details", { class: "small", open: !r.units.length }, h("summary", {}, `The AI's notes (${r.why.length})`),
          h("ul", { class: "muted", style: "margin:4px 0 0;padding-left:20px;text-align:left" }, r.why.map((x) => h("li", {}, x.slice(0, 300))))) : null,
        h("div", { class: "row" },
          adding ? (r.units.length || r.events.length ? h("button", { onclick: () => use(false) }, "Add to the plan") : null)
            : h("button", { class: gone.length ? "danger" : "", onclick: () => use(true) }, "Replace the plan's dates"),
          h("button", { class: "quiet", onclick: () => { preview.replaceChildren(); out.textContent = ""; } }, "Cancel"))));
    };
    // N6: Read it turns solid once the text is new
    const readBtn = h("button", { class: "ghost", onclick: read }, "Read it");
    ta.addEventListener("input", () => readBtn.classList.remove("ghost"));
    const modes = h("span", { class: "seg", role: "group", "aria-label": "Text" }, [["add", "Add dates"], ["all", "Edit the whole plan"]].map(([k, t]) =>
      h("button", { class: textMode === k ? "on" : "", "aria-pressed": String(textMode === k), onclick: () => { textMode = k; draw(); } }, t)));
    const aiBox = h("div", { class: "aibox" },
      h("b", {}, "Draft it with your own AI"),
      h("p", { class: "muted small" }, "Copy this prompt into any AI chat, add your syllabus or what you want where it says, and paste its answer into Add dates. It can also check the plan you have. The prompt carries the plan's dates and your deck's tag names with counts; never a card."),
      // 3.6.5: to pick card by card, the AI reads the cards themselves: the person's own export, to their own AI
      h("details", { class: "small" }, h("summary", {}, "Pick card by card: attach your cards"),
        h("ol", { class: "muted", style: "margin:6px 0 0;padding-left:20px;text-align:left" },
          h("li", {}, "In Anki: Tools › Due Crew › Export cards for my AI, and pick this plan."),
          h("li", {}, "Attach the .txt file to the chat with the prompt. A big course works better a block at a time.")),
        h("p", { class: "muted" }, "On an older Due Crew: in Anki's browser, select the notes, then Notes › Export Notes as Notes in Plain Text, with Include unique identifier ticked. Your cards go only to your AI. Due Crew never sees them.")),
      h("div", { class: "row" }, h("button", { class: "ghost", onclick: (e) => copy(aiPrompt(), e.target) }, "Copy the prompt"),
        h("details", {}, h("summary", { class: "small" }, "See it"), h("pre", { class: "mono small muted aipre" }, aiPrompt()))));
    return h("div", { class: "stack" },
      aiBox,
      h("details", { class: "fmt" }, h("summary", { class: "small" }, "Format"),
        h("p", { class: "muted small" }, "One line per date: when it opens, a name, the tags and subdecks (or notes: with note IDs: in Anki's browser, Due Crew › Copy as plan selector), and an optional due date, separated by |. Add even to split a date evenly up to its due date. For example:"),
        h("pre", { class: "mono small muted", style: "margin:0;white-space:pre-wrap" }, "2026-10-05 | Heart failure | tag:Step1::Cardio::Heart_failure | due 2026-10-09 | even\nweek 2 | Arrhythmia | tag:Step1::Cardio::Arrhythmia\n2026-10-19 | Lecture 12 | notes:Ab3$kL9qZ1 p&x8Hk!eQ2")),
      h("div", { class: "row" }, modes, h("span", { class: "muted small" }, adding
        ? `Adds to the plan's ${doc.units.length} date${doc.units.length === 1 ? "" : "s"}. Changes nothing already there.`
        : "Saving replaces the plan's dates with this text.")),
      ta, h("div", { class: "row" }, readBtn), out, preview);
  }


  // ---- settings ----
  function settingsTab() {
    const name = h("input", { id: "sname", maxlength: 60, value: meta.name, style: "width:100%", oninput: (e) => { meta.name = e.target.value; mark(); } });
    const line = h("input", { id: "sline", maxlength: 120, value: meta.line, style: "width:100%", placeholder: "Organ systems, one a week, done by January.", oninput: (e) => { meta.line = e.target.value; mark(); } });
    const sq = h("select", { id: "ssquad", onchange: (e) => { meta.squad = e.target.value; if (!meta.squad) meta.audience = "code"; mark(); draw(); } },
      h("option", { value: "" }, "No squad"), squads.map((s) => h("option", { value: s.id, selected: s.id === meta.squad }, s.name)));
    const aud = (v, text) => h("label", { style: "display:flex;gap:8px;align-items:center;color:var(--ink);font-size:14px" },
      h("input", { type: "radio", name: "aud", value: v, checked: meta.audience === v, disabled: v === "squad" && !meta.squad,
        onchange: () => { meta.audience = v; mark(); } }), text);
    const ph = doc.phases || { catchup: 0, taper: 0 };
    const setPh = (k, v) => { doc.phases = { ...ph, ...(doc.phases || {}), [k]: v }; if (!doc.phases.catchup && !doc.phases.taper) delete doc.phases; mark(); };
    const endIn = h("input", { type: "date", id: "pend", value: doc.end || "", onchange: (e) => {
      if (e.target.value) doc.end = e.target.value; else { delete doc.end; if (doc.phases) { doc.phases.taper = 0; if (!doc.phases.catchup) delete doc.phases; } }
      mark(); draw(); } });
    const catchup = h("select", { id: "pcatch", onchange: (e) => { setPh("catchup", Number(e.target.value)); draw(); } },
      [[0, "None"], [3, "Every 3rd week"], [4, "Every 4th week"]].map(([v, t]) => h("option", { value: v, selected: (ph.catchup || 0) === v }, t)));
    const taper = h("input", { type: "number", id: "ptaper", min: 0, max: 60, value: ph.taper || 0, disabled: !doc.end, style: "width:6em",
      onchange: (e) => setPh("taper", Math.max(0, Math.min(60, Math.round(Number(e.target.value) || 0)))) });
    const del = h("button", { class: "danger", onclick: async () => {
      if (del.dataset.sure !== "1") { del.dataset.sure = "1"; del.textContent = "Delete it: followers keep their cards open"; return; }
      try { await api("DELETE", `/plans/${id}`); } catch { del.textContent = "That didn't work. Try again."; del.dataset.sure = ""; return; }
      dirty = false; go("/plans");
    } }, "Delete this plan");
    return h("div", { class: "stack", style: "max-width:560px" },
      h("label", { for: "sname" }, "Name"), name,
      h("label", { for: "sline" }, "One line"), line,
      h("label", { for: "ssquad" }, "Offer it to a squad"), sq,
      h("label", {}, "Who can follow"), aud("code", "Anyone with the code"), aud("squad", meta.squad ? "Only people in that squad" : "Only people in a squad (choose one above)"),
      h("label", { for: "pend" }, "Ends (optional)"), h("div", { class: "row" }, endIn, h("span", { class: "muted small" }, "the exam, or the course's last day")),
      h("label", { for: "pcatch" }, "Catch-up weeks (nothing new)"), catchup,
      h("label", { for: "ptaper" }, "Review-only days at the end"), h("div", { class: "row" }, taper, h("span", { class: "muted small" }, "before the end date: no new cards")),
      h("label", {}, "Library"), libraryBox(),
      h("div", { style: "margin-top:18px" }, del));
  }

  /** 3.5, B: list the plan in the library, or take it out. At once, not with Save. */
  function libraryBox() {
    if (plan.listed === -1) {
      return h("div", { class: "libnote out" }, h("b", {}, "Taken out of the library"), h("span", {}, plan.listedNote || ""),
        h("span", { class: "muted small" }, "It stays yours, and its followers keep following. Send feedback if it's a mistake."));
    }
    const why = plan.audience !== "code" ? "Only a plan anyone with the code can follow goes in the library."
      : !plan.doc.units.length ? "Put some dates on it first." : null;
    const status = h("span", { class: "status", role: "status" });
    const box = h("input", { type: "checkbox", id: "slisted", checked: plan.listed === 1, disabled: !!why && plan.listed !== 1, onchange: async (e) => {
      box.disabled = true;
      try { plan = await api("PUT", `/plans/${id}/listed`, { listed: e.target.checked }); status.textContent = plan.listed === 1 ? "In the library." : "Out of the library."; }
      catch (err) {
        e.target.checked = !e.target.checked; status.className = "status bad";
        status.textContent = err.body?.error === "too_many_listed" ? "You have 20 plans in the library. Take one out first." : "That didn't work. Try again.";
      }
      box.disabled = false;
    } });
    return h("div", { class: "libnote" },
      h("label", { class: "inline", for: "slisted", style: "margin:0;color:var(--ink);font-size:14px" }, box, " List it in the library"),
      h("span", { class: "muted small" }, why || "Anyone signed in can find it, look at its calendar, follow it, or copy it into a plan of their own. Your name shows as its author, and its code shows there."),
      status);
  }

  /** B4: under the name, one line: whose it is, with whom, who follows. */
  function subline() {
    const eds = (plan.editors || []).filter((x) => x.uid !== me.uid).map((x) => x.name);
    const whose = plan.owner === me.uid ? "Yours" : `${plan.ownerName}'s plan`;
    const with_ = author && plan.owner !== me.uid ? ["you", ...eds] : eds;
    const f = !author && plan.following;
    const bits = [whose, with_.length ? `with ${with_.join(", ")}` : null, `${plan.followers} following`, meta.name === plan.doc.deck ? null : plan.doc.deck,
      f && f.shift ? `your dates run ${f.shift} day${f.shift === 1 ? "" : "s"} later` : null,
      f && Object.keys(f.moved || {}).length ? `${Object.keys(f.moved).length} date${Object.keys(f.moved).length === 1 ? "" : "s"} moved` : null,
      f && f.paused ? (f.until ? `paused until ${pretty(f.until)}` : "paused") : null,
      plan.basedOn ? credit(plan.basedOn) : null, author && plan.listed === 1 ? "in the library" : null];
    return bits.filter(Boolean).join(" · ");
  }

  /** 3.7.6: Reset to default, while my own days differ from the plan's:
   *  asks once with what goes back; cards already open in Anki stay open. */
  let resetAsk = false;
  function resetBtn() {
    const f = !author && plan.following;
    if (!f || !(f.shift || (f.skipped || []).length || Object.keys(f.moved || {}).length || f.paused || f.until)) return null;
    if (!resetAsk) return h("span", {}, " · ", h("button", { class: "linkish", onclick: () => { resetAsk = true; draw(); } }, "Reset to default…"));
    const n = (k) => (f[k] || []).length;
    const what = [f.shift ? `dates back on time (now ${f.shift} day${f.shift === 1 ? "" : "s"} later)` : null,
      n("skipped") ? `${n("skipped")} skipped date${n("skipped") === 1 ? "" : "s"} back` : null,
      Object.keys(f.moved || {}).length ? `${Object.keys(f.moved).length} moved date${Object.keys(f.moved).length === 1 ? "" : "s"} back` : null,
      f.paused || f.until ? "your pause ends" : null].filter(Boolean).join(", ");
    return h("span", { class: "resetask" }, h("br"), `Reset to default? ${what}. Cards already open stay open. `,
      h("button", { class: "linkish", onclick: async () => {
        try {
          await api("PATCH", `/plans/${id}/follow`, { shift: 0, skipped: [], moved: {}, paused: false, until: null, since: null });
          plan = await api("GET", `/plans/${id}`);
        } catch (e) { if (!e.status) console.error(e); }
        resetAsk = false; draw();
      } }, "Reset"), " · ",
      h("button", { class: "linkish", onclick: () => { resetAsk = false; draw(); } }, "Cancel"));
  }

  /** B4: everything about sharing the plan, in one menu. */
  function share() {
    const url = `${location.origin}/p/${plan.code}`;
    return h("details", { class: "sharemenu", open: shareOpen, ontoggle: (e) => { shareOpen = e.target.open; } },
      h("summary", {}, "Share"),
      h("div", { class: "sharepop" },
        plan.code && meta.audience !== "squad" ? [
          h("span", { class: "lbl" }, "The plan's code"),
          h("div", { class: "row", style: "justify-content:space-between" }, h("span", { class: "code" }, spaced(plan.code)),
            h("button", { class: "ghost", title: "Send this to your class: the page says how to follow", onclick: (e) => copy(url, e.target) }, "Copy link")),
          calMenu(plan.code),
          h("button", { class: "linkish", onclick: () => { tab = "calendar"; view = "print"; printOpt.poster = true; shareOpen = false; draw(); } }, "A poster for the class, with a QR code")]
          : h("p", { class: "muted small" }, "Only your squad can follow it. They'll find it in Anki."),
        h("span", { class: "lbl" }, "Planning it with"),
        people()));
  }

  /** The people who write the plan; the owner adds co-authors from the crew. */
  function people() {
    const all = [{ uid: plan.owner, name: plan.ownerName }, ...(plan.editors || [])];
    const chips = all.map((p) => h("span", { class: "who2", title: p.uid === plan.owner ? "Made it" : "Co-author" },
      p.uid === me.uid ? "You" : p.name,
      (owner && p.uid !== plan.owner) || (plan.role === "editor" && p.uid === me.uid)
        ? h("button", { class: "x", "aria-label": p.uid === me.uid ? "Leave" : `Remove ${p.name}`, onclick: async () => {
          try { await api("DELETE", `/plans/${id}/editors/${p.uid}`); } catch { return; }
          if (p.uid === me.uid) return go("/plans");
          plan = { ...plan, editors: plan.editors.filter((x) => x.uid !== p.uid) }; draw(); } }, "×") : null));
    const pick = h("span");
    const addBtn = owner ? h("button", { class: "linkish", onclick: async () => {
      let b;
      try { b = await api("GET", "/friends"); } catch { return; }
      const have = new Set(all.map((x) => x.uid));
      const crew = (b.friends || []).filter((f) => f.mutual && !have.has(f.uid));
      pick.replaceChildren(crew.length
        ? h("select", { "aria-label": "Add a co-author", onchange: async (e) => {
          if (!e.target.value) return;
          try { plan = { ...plan, editors: (await api("POST", `/plans/${id}/editors`, { uid: e.target.value })).editors }; } catch { /* stays as it was */ }
          pick.replaceChildren(); draw(); } },
          h("option", { value: "" }, "Pick from your crew"), crew.map((f) => h("option", { value: f.uid }, f.name)))
        : h("span", { class: "muted small" }, "Co-authors come from your crew."));
    } }, "+ Co-author") : null;
    return h("div", { class: "people2" }, chips, addBtn, pick);
  }

  function calendarTab() {
    const vbtn = (k, t) => h("button", { class: view === k ? "on" : "", "aria-pressed": String(view === k), onclick: () => { view = k; draw(); } }, t);
    const placedTotal = doc.units.reduce((a, u) => a + unitTotal(u), 0);
    // B1: on a wide screen the picked day lives in the side panel, so there are never three columns
    const sideDay = author && !narrow();
    const nav = h("div", { class: "caltool2" },
      view === "month" || view === "week" ? h("span", { class: "row", style: "gap:4px" },
        h("button", { class: "quiet", "aria-label": "Earlier", onclick: () => step(-1) }, "‹"),
        h("button", { class: "quiet", onclick: () => { anchor = today(); draw(); } }, "Today"),
        h("button", { class: "quiet", "aria-label": "Later", onclick: () => step(1) }, "›"),
        h("b", { class: "ctitle" }, calTitle())) : h("b", {}, view === "text" ? "As text" : view === "print" ? "Print" : `${doc.units.length} dates`),
      h("span", { class: "sp" }),
      // B5: the plan as text is a view of the calendar
      h("span", { class: "seg" }, vbtn("month", "Month"), vbtn("week", "Week"), author ? vbtn("list", "List") : null, author ? vbtn("text", "Text") : null, vbtn("print", "Print")));
    const paceLine = () => {
      const days = ["M", "T", "W", "T", "F", "S", "S"].filter((_, i) => pace.days[i]).join("");
      const how = pace.mode === "end" && doc.end ? `Finish by ${pretty(doc.end)}` : pace.mode === "daily" ? `${pace.daily || 20} new a day` : "I'll place each day";
      return `${how} · ${days === "MTWTFSS" ? "every day" : days}`;
    };
    const paceBox = author ? (narrow()
      ? h("details", { class: "pacefold", open: paceOpen, ontoggle: (e) => { paceOpen = e.target.open; } }, h("summary", {}, h("b", {}, paceLine())), pacePanel())
      : pacePanel()) : null;
    // B3: one fill button, named for what it does; none when placing by hand
    const left = coverLeft();
    const fillLabel = pace.mode === "end" && aimFor && evById(aimFor) ? `Fill up to ${evById(aimFor).name}`
      : pace.mode === "end" && doc.end ? `Fill to ${pretty(doc.end)}` : `Fill at ${(pace.daily || 20).toLocaleString()} a day`;
    const fillRow = author && view !== "text" && view !== "print" ? h("div", { class: "caltool2" },
      pace.mode !== "placed" ? h("button", { onclick: () => fillOrSay(false) }, fillLabel) : null,
      pace.mode !== "placed" ? h("button", { class: "linkish", onclick: () => fillOrSay(true) }, "just next week") : null,
      h("span", { class: "muted small" }, left ? `${left.toLocaleString()} card${left === 1 ? "" : "s"} not on a day yet` : placedTotal ? `${placedTotal.toLocaleString()} cards on the calendar` : ""),
      note ? h("span", { class: "muted small", role: "status" }, note) : null) : null;
    const inner = view === "print" ? printView()
      : view === "text" && author ? textTab()
      : view === "list" && author ? h("div", {}, sideDay ? null : dayPanel(), listView())
      : sideDay ? calendar()
      : h("div", { class: `calwrap${picked ? " has-day" : ""}` }, calendar(), dayPanel());
    const main = h("div", { class: "main2" },
      paceBox,
      h("div", { class: "calcard" }, nav, fillRow, view === "text" || view === "print" ? null : heavyNote(), inner));
    if (!author) return main;
    if (sideDay) {
      if (!picked) sideTab = "cover";
      const ptab = (k, label, extra) => h("div", { class: `ptab${sideTab === k ? " on" : ""}` },
        h("button", { role: "tab", "aria-selected": String(sideTab === k), onclick: () => { sideTab = k; draw(); } }, label), extra);
      return h("div", { class: "bl2" },
        h("div", { class: "side3" },
          h("div", { class: "ptabs", role: "tablist" }, ptab("cover", "What to cover"),
            picked ? ptab("day", pretty(picked), h("button", { class: "x", "aria-label": "Close the day", onclick: () => { picked = null; splitting = null; moving = null; sideTab = "cover"; draw(); } }, "×")) : null),
          sideTab === "day" && picked ? dayPanel(true) : treePanel()),
        main);
    }
    return h("div", { class: "bl2" },
      h("details", { class: "side2", open: !narrow() || (coverOpen ?? !doc.units.length), ontoggle: (e) => { if (narrow()) coverOpen = e.target.open; } },
        h("summary", {}, h("b", {}, "What to cover"), h("span", { class: "muted" }, ` · ${cover.size ? `${coverItems().length} ticked` : "nothing ticked"}`)), treePanel()),
      main);
  }

  // ---- E2: print: a list to study from, a line per study day ----
  const printOpt = { counts: true, notes: true, off: false, from: null, to: null, poster: false };
  /** A day's topics by where they come from: "Videos: Heart failure · Book: Ch 8". */
  function topics(u) {
    const groups = new Map();
    const put = (g, x) => { if (!groups.has(g)) groups.set(g, []); if (!groups.get(g).includes(x)) groups.get(g).push(x); };
    for (const t of u.tags || []) {
      const segs = t.split("::");
      const ri = segs.findIndex((x, i) => i > 0 && /^[#^]/.test(x));
      const last = Tags.word(segs[segs.length - 1]);
      if (ri >= 0 && ri < segs.length - 1) put(Tags.word(segs[ri]), last);
      else put("", last);
    }
    for (const d of u.decks || []) put("", Tags.word(d.split("::").pop()));
    for (const q of u.search || []) put("Search", searchName(q).replace(/^Search:\s*/, ""));
    if (hasIds(u)) put("By ID", idsText(u).replace(/ by ID$/, ""));
    if ((u.cards || []).length) put("Picked", `${u.cards.length} single card${u.cards.length === 1 ? "" : "s"}`);
    return [...groups.entries()];
  }
  /** 3.5, C3: a page for the classroom wall: the plan, a QR code of its
   *  link, the code to type. Only a plan anyone with the code can follow. */
  function posterView(bar) {
    const url = `https://duecrew.com/p/${plan.code}`;
    const qr = h("div", { class: "qr" });
    const draw1 = () => qr.replaceChildren(QR.svg(url, 300));
    if (typeof QR !== "undefined") draw1();
    else {
      const sc = h("script", { src: "/qr.js" });
      sc.onload = draw1;
      sc.onerror = () => qr.replaceChildren(h("p", { class: "muted" }, "The QR code didn't load. Try again."));
      document.head.append(sc);
    }
    const us = doc.units;
    const last = us.reduce((m, u) => ((u.due || u.opens) > m ? u.due || u.opens : m), us[0]?.opens || "");
    const paper = h("div", { class: "printout poster" },
      h("h2", {}, meta.name || plan.name),
      us.length ? h("p", { class: "pm" }, [(meta.name || plan.name) === plan.doc.deck ? null : plan.doc.deck,
        `${us.length} date${us.length === 1 ? "" : "s"}, ${pretty(us[0].opens)}${last !== us[0].opens ? ` – ${pretty(last)}` : ""}`].filter(Boolean).join(" · ")) : null,
      qr,
      h("p", { class: "pcode" }, spaced(plan.code)),
      h("ol", { class: "psteps" },
        h("li", {}, "Scan it, or open ", h("b", {}, `duecrew.com/p/${plan.code}`)),
        h("li", {}, "In Anki on a computer: Tools › Due Crew › Follow a plan, and type the code")),
      h("p", { class: "pfoot" }, "Each morning, that day's cards open in your deck."));
    return h("div", { class: "stack" }, bar, h("div", { class: "paperwrap" }, paper));
  }

  function printView() {
    byOpens();
    const dates = doc.units.map((u) => u.opens).sort();
    const first = dates[0] || start, lastD = doc.units.reduce((m, u) => ((u.even && u.due ? u.due : u.opens) > m ? (u.even && u.due ? u.due : u.opens) : m), first);
    const from = printOpt.from || first, to = printOpt.to || lastD;
    const box = (k, t) => h("label", { class: "inline" }, h("input", { type: "checkbox", checked: printOpt[k], onchange: (e) => { printOpt[k] = e.target.checked; draw(); } }), t);
    const dateIn = (k, v) => h("input", { type: "date", value: v, "aria-label": k === "from" ? "From" : "To", onchange: (e) => { printOpt[k] = e.target.value || null; draw(); } });
    const posterOk = !!plan.code && plan.audience === "code";
    const kind = posterOk ? h("span", { class: "seg" }, ...[[false, "Dates"], [true, "Poster"]].map(([v, t]) =>
      h("button", { class: printOpt.poster === v ? "on" : "", "aria-pressed": String(printOpt.poster === v), onclick: () => { printOpt.poster = v; draw(); } }, t))) : null;
    if (posterOk && printOpt.poster) return posterView(h("div", { class: "printbar" }, kind, h("button", { onclick: () => window.print() }, "Print")));
    const bar = h("div", { class: "printbar" }, kind, box("counts", "card counts"), box("notes", "notes"), box("off", "days off"),
      h("span", { class: "muted" }, "From"), dateIn("from", from), h("span", { class: "muted" }, "to"), dateIn("to", to),
      h("button", { onclick: () => window.print() }, "Print"));
    // the rows: each day with something new, a review day, or (ticked) a day off
    const reviews = new Map((doc.reviews || []).map((r) => [r.day, r]));
    const byId = new Map(doc.units.map((u) => [u.id, u]));
    const weeks = [];
    let week = null;
    for (let d = from; d <= to; d = addDays(d, 1)) {
      const off = !pace.days[(parseIso(d).getUTCDay() + 6) % 7];
      const own = doc.units.filter((u) => u.opens === d);
      const spans = doc.units.filter((u) => u.even && u.due && u.opens < d && d <= u.due && !off);
      const r = reviews.get(d);
      const dn = printOpt.notes ? notes.filter((x) => x.day === d) : [];
      const evd = evOn(d);
      if (!own.length && !spans.length && !r && !evd.length && !(off && printOpt.off)) continue;
      const m = Sched.monday(d);
      if (!week || week.m !== m) { week = { m, rows: [] }; weeks.push(week); }
      const dd = parseIso(d);
      const when = `${DAYS[dd.getUTCDay()]} ${dd.getUTCDate()} ${MONTHS[dd.getUTCMonth()]}`;
      const cells = [];
      for (const x of evd) cells.push(h("span", { class: "t evt" }, x.name));
      for (const u of [...own, ...spans]) {
        const part = u.even && u.due ? ` (${u.opens === d ? "starts; " : ""}evenly to ${pretty(u.due)})` : "";
        const fx = u.for && evById(u.for);
        cells.push(h("span", { class: "t" }, `${u.name}${part}`, fx ? h("span", { class: "fx" }, ` · for ${fx.name}, ${pretty(fx.day)}`) : null),
          h("span", { class: "src" }, topics(u).flatMap(([g, xs], i) => [i ? " · " : "", g ? h("b", {}, `${g} `) : null, xs.join(" · ")])));
      }
      if (r && byId.get(r.from)) cells.push(h("span", { class: "t" }, "Review day"), h("span", { class: "src" }, `${byId.get(r.from).name}${r.to !== r.from && byId.get(r.to) ? ` – ${byId.get(r.to).name}` : ""}, in Anki's own filtered deck`));
      if (off && !cells.length) cells.push(h("span", { class: "t muted" }, "Day off"));
      for (const x of dn) cells.push(h("span", { class: "nt" }, `${x.mine ? "You" : x.name}: ${x.text}`));
      const n = own.reduce((a, u) => a + unitTotal(u), 0);
      week.rows.push(h("tr", { class: evd.length ? "evr" : r && !own.length ? "rv" : off && !own.length ? "off" : "" },
        h("td", { class: "bx" }, h("i")), h("td", { class: "dt" }, when), h("td", {}, cells),
        h("td", { class: "n" }, printOpt.counts && n ? n.toLocaleString() : "")));
    }
    const link = plan.code && plan.audience !== "squad" ? ` · duecrew.com/p/${plan.code}` : "";
    const paper = h("div", { class: "printout" },
      h("h2", {}, meta.name || plan.name),
      h("p", { class: "pm" }, `${plan.owner === me?.uid ? "Your" : `${plan.ownerName}'s`} plan · ${plan.doc.deck} · ${pretty(from)} – ${pretty(to)}${link}`),
      weeks.length ? weeks.flatMap((w) => [h("div", { class: "wk" }, `Week of ${pretty(w.m)}`), h("table", {}, h("tbody", {}, w.rows))])
        : h("p", { class: "muted" }, "Nothing in these dates."),
      h("p", { class: "pfoot" }, "Each day's cards open in Anki that morning."));
    return h("div", { class: "stack" }, bar, h("div", { class: "paperwrap" }, paper));
  }

  // ---- progress (the authors'): counts only ----
  let progressData = null;
  function progressTab() {
    if (!progressData) {
      api("GET", `/plans/${id}/progress`).then((r) => { progressData = r; draw(); })
        .catch(() => { progressData = { followers: 0, sharing: 0, units: {}, failed: true }; draw(); });
      return h("p", { class: "muted" }, "Loading…");
    }
    const pr = progressData;
    if (pr.failed) { progressData = null; return h("p", { class: "muted" }, "Couldn't load it. Open the tab again."); }
    byOpens();
    return h("div", {},
      classHints(pr),
      h("p", { class: "muted small" }, `${pr.sharing} of ${pr.followers} are on the team; these counts are theirs.`),
      h("div", { class: "prog" }, h("span", { class: "h" }, "Date"), h("span", { class: "h" }, "Opened"), h("span", { class: "h" }, "Done"), h("span"),
        doc.units.flatMap((u) => {
          const c = pr.units[u.id] || { opened: 0, done: 0 };
          const w = (k) => `${pr.sharing ? Math.round((100 * k) / pr.sharing) : 0}%`;
          return [h("span", {}, u.name), h("span", { class: "bar" }, h("i", { style: `width:${w(c.opened)}` })),
            h("span", { class: "bar" }, h("i", { style: `width:${w(c.done)}` })), h("span", { class: "n" }, `${c.opened} · ${c.done}`)];
        })));
  }

  /** 3.5, C2: a date most of the class hasn't finished two days after it
   *  (3 or more sharing, under half done). Counts only; nobody named. What
   *  helps is on the dates still to come: a day's breather, or a look at
   *  that day to split what's like it. */
  function classHints(pr) {
    if (pr.sharing < 3) return null;
    const t = today();
    const behind = doc.units.filter((u) => addDays(u.due || u.opens, 2) <= t && (pr.units[u.id]?.done || 0) < pr.sharing / 2)
      .sort((a, b) => (b.due || b.opens).localeCompare(a.due || a.opens)).slice(0, 2);
    if (!behind.length) return null;
    const later = doc.units.filter((u) => u.opens > t);
    const breather = () => {
      // every date still to come, one study day later; events stay on their days
      for (const u of [...later].sort((a, b) => b.opens.localeCompare(a.opens))) shiftUnit(u, Sched.diff(nextStudy(u.opens), u.opens));
      for (const r of doc.reviews || []) if (r.day > t) r.day = nextStudy(r.day);
      byOpens(); mark(); tab = "calendar"; note = `Moved the ${later.length} date${later.length === 1 ? "" : "s"} after today one study day later. Save to keep it.`; draw();
    };
    return h("div", { class: "stack", style: "margin-bottom:12px" }, behind.map((u) => {
      const done = pr.units[u.id]?.done || 0;
      const late = Sched.diff(t, u.due || u.opens);
      return h("div", { class: "hint" },
        h("span", {}, h("b", {}, u.name), ` (${unitTotal(u).toLocaleString()} cards): ${done} of ${pr.sharing} finished, ${late} days after its date.`),
        h("span", { class: "row" },
          h("button", { class: "linkish", onclick: () => { tab = "calendar"; picked = u.opens; sideTab = "day"; anchor = u.opens; draw(); } }, "Look at that day"),
          later.length ? h("button", { class: "linkish", onclick: breather }, "Give the class a day") : null));
    }));
  }

  // ---- history: every save, who and what; the latest undoes ----
  let history = null;
  function historyTab() {
    if (!history) {
      api("GET", `/plans/${id}/log`).then((r) => { history = r.log; draw(); }).catch(() => { history = []; draw(); });
      return h("p", { class: "muted" }, "Loading…");
    }
    if (!history.length) return h("p", { class: "muted" }, "Nothing yet. Each save shows here.");
    const ago2 = (t) => { const m = Math.round((Date.now() / 1000 - t) / 60); return m < 1 ? "just now" : m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : pretty(iso(new Date(t * 1000))); };
    return h("div", { class: "hist" }, history.map((l) => h("div", { class: "hrow" },
      h("span", {}, h("b", {}, l.uid === me.uid ? "You" : l.name), ` ${l.summary}`), h("small", { class: "muted" }, ago2(l.at)),
      l.undo ? h("button", { class: "linkish", onclick: async () => {
        if (dirty && !confirm("Undo drops your unsaved changes here too.")) return;
        try {
          plan = await api("POST", `/plans/${id}/undo`, { version: l.version });
          doc = structuredClone(plan.doc); base = structuredClone(plan.doc); dirty = false; history = null;
          status.className = "status"; status.textContent = "Undone";
        } catch { status.className = "status bad"; status.textContent = "That changed since. Reload."; }
        draw(); } }, "Undo") : h("span"))));
  }

  /** 3.7.3: what the authors said to followers, newest first; the authors post
   *  here any time (a save's "Tell followers" lands here too). Anki shows
   *  the newest unread on the plan, the site's home lists them. */
  function updatesTab() {
    if (!posts) {
      api("GET", `/plans/${id}/posts`).then((r) => { posts = r.posts; draw(); }).catch(() => { posts = []; draw(); });
      return h("p", { class: "muted" }, "Loading…");
    }
    const ago2 = (t) => { const m = Math.round((Date.now() / 1000 - t) / 60); return m < 1 ? "just now" : m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : pretty(iso(new Date(t * 1000))); };
    const st = h("span", { class: "status", role: "status" });
    let box = null;
    if (author) {
      const ta = h("textarea", { rows: 2, maxlength: 200, style: "font-family:inherit;font-size:14px", placeholder: `Post to the ${plan.followers.toLocaleString()} following`, "aria-label": "Post to followers" });
      const cnt = h("small", { class: "muted" }, "0 / 200");
      ta.addEventListener("input", () => { ta.value = ta.value.replace(/[\r\n]+/g, " "); cnt.textContent = `${ta.value.length} / 200`; });
      const go = h("button", { onclick: async () => {
        const text = ta.value.trim();
        if (!text) return;
        go.disabled = true;
        try { await api("POST", `/plans/${id}/posts`, { text }); posts = null; draw(); }
        catch (err) { go.disabled = false; st.className = "status bad"; st.textContent = err.status === 429 ? "Five posts a day per plan. Try tomorrow." : "That didn't post. Try again."; }
      } }, "Post");
      const [r, of] = plan.reached || [0, 0];
      box = h("div", { class: "stack", style: "max-width:720px;margin-bottom:14px" }, ta,
        h("div", { class: "row" }, of ? h("small", { class: "muted" }, `This version is in ${r.toLocaleString()} of ${of.toLocaleString()} followers' Anki`) : null,
          h("span", { style: "flex:1" }), cnt, st, go));
    }
    if (!posts.length) return h("div", {}, box, h("p", { class: "muted" }, author ? "Nothing posted yet. Followers see a post in Anki and on their home page." : "Nothing from the authors yet."));
    return h("div", {}, box, h("div", { class: "hist" }, posts.map((x) => h("div", { class: "hrow" },
      h("span", {}, h("b", {}, x.uid === me.uid ? "You" : x.name), x.coauthor ? h("small", { class: "muted" }, " (co-author)") : null, ` ${x.text}`,
        x.withSave ? h("small", { class: "muted" }, " · with a save") : null),
      h("small", { class: "muted" }, ago2(x.at)),
      x.remove ? h("button", { class: "linkish", onclick: async () => {
        try { await api("DELETE", `/plans/${id}/posts/${x.id}`); posts = posts.filter((y) => y.id !== x.id); draw(); }
        catch { st.className = "status bad"; st.textContent = "That didn't work. Try again."; }
      } }, "Remove") : h("span")))));
  }

  /** 3.7.3: the plan's team. Opt-in: who showed up today (answered one of the
   *  plan's cards), questions to the team and their answers, the team's
   *  bingo. Never anyone's numbers. Each click is one request. */
  let team = null;          // GET /plans/{id}/team, loaded when the tab opens
  let replyTo = null;       // the thread whose reply box is open
  let bingoOpen = false;
  const wkOf = (d) => {
    const x = parseIso(d); const dow = (x.getUTCDay() + 6) % 7; x.setUTCDate(x.getUTCDate() - dow + 3);
    const y = x.getUTCFullYear(); const first = new Date(Date.UTC(y, 0, 4));
    return `${y}-W${String(1 + Math.round(((x - first) / 86400000 - 3 + ((first.getUTCDay() + 6) % 7)) / 7)).padStart(2, "0")}`;
  };
  const ago = (t) => { const m = Math.round((Date.now() / 1000 - t) / 60); return m < 1 ? "now" : m < 60 ? `${m}m` : m < 1440 ? `${Math.round(m / 60)}h` : m < 2880 ? "yesterday" : `${Math.round(m / 1440)}d`; };
  const LINES = [[0, 1, 2], [3, 4, 5], [6, 7, 8], [0, 3, 6], [1, 4, 7], [2, 5, 8], [0, 4, 8], [2, 4, 6]];
  const CELLS = [0, 1, 2, 3, 5, 6, 7, 8];
  /** "3 of 9 · one away from bingo" (team.py bingo_line: change one, change both). */
  function bingoLine(ev) {
    const done = (c) => (c === 4 ? ev.middle.done : ev.squares[CELLS.indexOf(c)].done);
    const stamps = ev.squares.filter((q) => q.done).length + (ev.middle.done ? 1 : 0);
    const left = Math.min(...LINES.map((l) => l.filter((c) => !done(c)).length));
    const state = ev.lines >= 8 ? "the whole card" : ev.lines ? (ev.lines === 1 ? "BINGO" : `${ev.lines} lines`)
      : left === 1 ? "one away from bingo" : `${left} away from bingo`;
    return `${stamps} of 9 · ${state}`;
  }
  function teamTab() {
    if (!team) {
      api("GET", `/plans/${id}/team?wk=${wkOf(today())}`).then((r) => { team = r; draw(); }).catch(() => { team = { failed: true }; draw(); });
      return h("p", { class: "muted" }, "Loading…");
    }
    const st = h("span", { class: "status", role: "status" });
    const again = (p, bad = "That didn't work. Try again.") => p.then(() => { team = null; draw(); }).catch((err) => {
      st.className = "status bad"; st.textContent = err.status === 429 ? "That's a lot of questions today. Try tomorrow."
        : err.body?.error === "team_full" ? "This team is full." : bad; });
    if (team.failed) return h("p", { class: "muted" }, "Couldn't load the team. ", h("button", { class: "linkish", onclick: () => { team = null; draw(); } }, "Try again"));
    if (!team.on) {
      return h("div", { class: "panel", style: "max-width:560px" },
        h("h4", {}, h("span", {}, team.count ? `${team.count.toLocaleString()} on the team` : "No team yet")),
        h("p", { class: "muted small", style: "margin:0" }, "The team sees that you showed up today, and your questions and answers; your progress counts for the plan\u2019s authors. Never your numbers."),
        h("div", { class: "row" }, h("button", { onclick: (e) => { e.target.disabled = true; again(api("POST", `/plans/${id}/team`)); } }, "Join the team"), st));
    }
    const ask = h("input", { placeholder: "Ask anything…", maxlength: 280, "aria-label": "Ask the team" });
    const send = () => { const text = ask.value.trim(); if (text) again(api("POST", `/plans/${id}/asks`, { text })); };
    ask.addEventListener("keydown", (e) => { if (e.key === "Enter") send(); });
    const who = (x) => (x.mine ? "You" : [x.emoji ? `${x.emoji} ` : "", h("b", {}, x.name)]);
    const thread = (a) => {
      const reps = a.replies.map((r) => h("div", { class: "rep" }, h("b", {}, r.mine ? "You" : r.name), r.author ? " (author)" : "", `: ${r.text}`,
        a.mine && !r.mine ? h("button", { class: "linkish", onclick: () => again(api("POST", `/plans/${id}/asks/${r.id}/helped`, { on: !r.helped })) }, r.helped ? "Helped ✓" : "That helped")
          : r.helped ? h("span", { class: "ok" }, " ✓ helped") : null,
        r.remove ? h("button", { class: "linkish", onclick: () => again(api("DELETE", `/plans/${id}/asks/${r.id}`)) }, "Remove") : null));
      const bits = [a.topic, a.replies.length ? `${a.replies.length} repl${a.replies.length === 1 ? "y" : "ies"}` : ""].filter(Boolean).join(" · ");
      let box = null;
      if (replyTo === a.id) {
        const r = h("input", { placeholder: "Your answer…", maxlength: 280, "aria-label": "Your answer" });
        const go = () => { const text = r.value.trim(); if (text) { replyTo = null; again(api("POST", `/plans/${id}/asks`, { text, parent: a.id })); } };
        r.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
        requestAnimationFrame(() => r.focus());
        box = h("div", { class: "ask3" }, r, h("button", { onclick: go }, "Reply"));
      }
      return h("div", { class: "tq" },
        h("div", { class: "t" }, a.guid ? h("span", {}, who(a), " on a card") : h("span", {}, who(a), `: ${a.text}`), h("span", { class: "m" }, ago(a.act || a.at))),
        a.guid ? h("div", {}, `“${a.text}”`) : null, ...reps, box,
        h("div", { class: "t" }, h("span", { class: "card" }, bits), h("span", { class: "m" },
          h("button", { class: "linkish", onclick: () => { replyTo = replyTo === a.id ? null : a.id; draw(); } }, a.guid ? "Answer" : "Reply"),
          a.remove ? h("button", { class: "linkish quiet2", onclick: () => again(api("DELETE", `/plans/${id}/asks/${a.id}`)) }, "Remove") : null)));
    };
    const faces = h("div", { class: "faces" }, team.faces.map((f) => h("div", { class: `face${f.shown ? "" : " away"}` },
      h("span", { class: "e" }, face(f.emoji, f.name)), h("b", {}, f.uid === me.uid ? "You" : f.name))),
      team.more ? h("div", { class: "face away" }, h("span", { class: "e" }, "+"), h("b", {}, `${team.more} more`)) : null);
    const b = team.bingo;
    let bingo = null;
    if (b) {
      const cell = (c) => (c === 4 ? b.ev.middle.done : b.ev.squares[CELLS.indexOf(c)].done);
      const sq = (c) => (c === 4 ? b.card.middle : b.card.squares[CELLS.indexOf(c)]);
      bingo = h("div", { class: "panel" }, h("h4", {}, h("span", {}, "Team bingo"), h("span", { class: "muted small", style: "font-weight:500" }, bingoLine(b.ev).split(" · ")[0])),
        h("div", { class: "bgrow" }, h("span", { class: "bgmini" }, [0, 1, 2, 3, 4, 5, 6, 7, 8].map((c) => h("i", { class: cell(c) ? "on" : "" }))),
          h("span", { class: "small" }, bingoLine(b.ev).split(" · ")[1]), h("span", { style: "flex:1" }),
          h("button", { class: "linkish", onclick: () => { bingoOpen = !bingoOpen; draw(); } }, bingoOpen ? "Close" : "Open")),
        bingoOpen ? h("div", { class: "bggrid" }, [0, 1, 2, 3, 4, 5, 6, 7, 8].map((c) => h("div", { class: cell(c) ? "on" : "" },
          h("span", {}, sq(c).icon || ""), h("b", {}, c === 4 ? sq(c).name : sq(c).title),
          h("small", {}, c === 4 ? `${b.ev.middle.have} of ${b.ev.middle.goal}` : sq(c).rule || "")))) : null);
    }
    return h("div", { class: "wb" },
      h("div", { class: "panel" }, h("h4", {}, h("span", {}, "Ask the team")),
        h("div", { class: "ask3" }, ask, h("button", { onclick: send }, "Ask")), st,
        team.asks.length ? team.asks.map(thread) : h("p", { class: "muted small", style: "margin:0" }, "No questions yet.")),
      h("div", { class: "rail" },
        h("div", { class: "panel" }, h("h4", {}, h("span", {}, "Showed up today"),
          h("span", { class: "muted small", style: "font-weight:500" }, `${team.shown} of ${team.count}${team.streak > 1 ? ` · ${team.streak} days` : ""}`)), faces),
        bingo,
        h("div", {}, h("button", { class: "quiet", onclick: () => { if (confirm("Leave the team? Your questions and answers stay.")) again(api("DELETE", `/plans/${id}/team`)); } }, "Leave the team"))));
  }

  /** 3.7.3: a follower sees the authors' newest post above the tabs until they
   *  close it (Updates is the authors' tab now). Per browser. */
  let postNote = undefined;
  function postLine() {
    if (author || !plan.following) return null;
    if (postNote === undefined) {
      postNote = null;
      api("GET", `/plans/${id}/posts`).then((r) => { postNote = (r.posts || [])[0] || null; if (postNote) draw(); }).catch(() => {});
      return null;
    }
    if (!postNote) return null;
    const key = `dc-post-${id}`;
    let seen = 0;
    try { seen = Number(localStorage.getItem(key)) || 0; } catch { /* private window: shown */ }
    if (postNote.id <= seen) return null;
    return h("div", { class: "postnote" }, h("b", {}, postNote.name), h("span", { class: "muted small" }, ago(postNote.at)),
      h("span", {}, postNote.text), h("span", { style: "flex:1" }),
      h("button", { class: "linkish", onclick: () => { try { localStorage.setItem(key, String(postNote.id)); } catch { /* none */ } postNote = null; draw(); } }, "Close"));
  }

  /** Someone looking at a plan they don't follow (from its code or the
   *  library): follow it here, or copy it into a plan of their own. */
  let copying = false;
  function readerActions() {
    const status = h("span", { class: "status", role: "status" });
    const follow = plan.code ? h("button", { onclick: async () => {
      follow.disabled = true;
      try { plan = await api("POST", "/plans/follow", { code: plan.code }); draw(); }
      catch (err) { follow.disabled = false; status.className = "status bad"; status.textContent = err.body?.error === "too_many_plans" ? "You follow 20 plans. Stop one first." : "That didn't work. Try again."; }
    } }, "Follow") : null;
    return h("div", { class: "stack", style: "margin:6px 0 12px" },
      h("div", { class: "row" }, follow,
        plan.library ? h("button", { class: "ghost", onclick: () => { copying = !copying; draw(); } }, "Copy to my plans") : null, status),
      copying ? copyForm(plan, () => { copying = false; draw(); }) : null,
      h("p", { class: "muted small" }, "Following opens each date's cards in Anki on its day", plan.code ? ["; or in Anki, Tools › Due Crew › Follow a plan, and paste ", h("b", { class: "mono" }, plan.code)] : null, "."));
  }

  function draw() {
    const tabBtn = (k, t) => h("button", { role: "tab", "aria-selected": String(tab === k), onclick: () => { tab = k; draw(); } }, t);
    // the plan's name, edited in place: it wraps and grows, so a long name is never cut off
    function titleBox() {
      const t = h("textarea", { class: "tname", rows: 1, maxlength: 60, "aria-label": "The plan's name", spellcheck: "false" });
      t.value = meta.name;
      const fit = () => { t.style.height = "auto"; t.style.height = `${t.scrollHeight}px`; };
      t.addEventListener("input", () => { t.value = t.value.replace(/[\r\n]+/g, " "); meta.name = t.value; mark(); fit(); });
      t.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); t.blur(); } });
      requestAnimationFrame(fit);
      // and again whenever its width changes (a window resized, the page laid out late)
      if (window.ResizeObserver) { let w = 0; new ResizeObserver(() => { if (t.clientWidth !== w) { w = t.clientWidth; fit(); } }).observe(t); }
      return t;
    }
    // 3.7.3: followers: Calendar and Team (the authors' posts show above the tabs); authors keep Updates
    const tabs = author ? [["calendar", "Calendar"], ["team", "Team"], ["updates", "Updates"], ["progress", "Progress"], ["history", "History"], owner ? ["settings", "Settings"] : null].filter(Boolean)
      : plan.following ? [["calendar", "Calendar"], ["team", "Team"]] : [];
    if (!tabs.some(([k]) => k === tab)) tab = "calendar";
    const body = tab === "settings" ? settingsTab() : tab === "progress" ? progressTab() : tab === "history" ? historyTab()
      : tab === "updates" ? updatesTab() : tab === "team" ? teamTab() : calendarTab();
    page(
      h("div", { class: "bhead" },
        h("div", { class: "btitle" }, owner ? titleBox() : h("h1", {}, meta.name || "Untitled"),
          h("p", { class: "muted small bsub" }, subline(), resetBtn())),
        author ? share() : plan.code && plan.audience !== "squad" ? calMenu(plan.code) : null),
      !author && plan.following ? onTrack(plan, false) : null,
      !author && plan.following ? finished() : null,
      !author && !plan.following ? readerActions() : null,
      postLine(),
      tabs.length ? h("div", { class: "tabs", role: "tablist" }, tabs.map(([k, t]) => tabBtn(k, t))) : null,
      body,
      author ? h("div", { class: `savebar${dirty || status.classList.contains("bad") || flash ? "" : " clean"}` }, status,
        plan.followers > (plan.following ? 1 : 0) ? tell : null, saveBtn) : null);
    $app().classList.add("wide");
  }

  // a date the same but for its refreshed card count hasn't changed
  const same = (x, y) => JSON.stringify({ ...x, n: 0 }) === JSON.stringify({ ...y, n: 0 });

  /** What a save did, in a few words, for the history. */
  function describe(before, after) {
    const b = new Map((before.units || []).map((u) => [u.id, u]));
    const a = new Map((after.units || []).map((u) => [u.id, u]));
    const out = [];
    const added = [...a.values()].filter((u) => !b.has(u.id));
    const gone = [...b.values()].filter((u) => !a.has(u.id));
    const moved = [...a.values()].filter((u) => b.has(u.id) && b.get(u.id).opens !== u.opens);
    const changed = [...a.values()].filter((u) => b.has(u.id) && b.get(u.id).opens === u.opens && !same(b.get(u.id), u));
    if (moved.length === 1) out.push(`moved ${moved[0].name} to ${pretty(moved[0].opens)}`); else if (moved.length) out.push(`moved ${moved.length} dates`);
    if (added.length === 1) out.push(`added ${added[0].name} on ${pretty(added[0].opens)}`); else if (added.length) out.push(`added ${added.length} dates`);
    if (gone.length === 1) out.push(`took off ${gone[0].name}`); else if (gone.length) out.push(`took off ${gone.length} dates`);
    if (changed.length === 1) out.push(`changed ${changed[0].name}`); else if (changed.length) out.push(`changed ${changed.length} dates`);
    for (const [k, w] of [["pace", "the pace"], ["end", "the end date"], ["phases", "catch-up weeks"], ["reviews", "the review days"], ["events", "the events"]]) {
      if (JSON.stringify(before[k] ?? null) !== JSON.stringify(after[k] ?? null) && !(k === "pace" && out.length)) out.push(`changed ${w}`);
    }
    return (out.join("; ") || "changed the plan").slice(0, 120);
  }

  /** Two authors saved: put my changes (against what I loaded) onto theirs. */
  function merge(mine, mineBase, theirs) {
    const out = structuredClone(theirs);
    const b = new Map((mineBase.units || []).map((u) => [u.id, u]));
    const m = new Map((mine.units || []).map((u) => [u.id, u]));
    let units = out.units || [];
    for (const [uid] of b) if (!m.has(uid)) units = units.filter((u) => u.id !== uid);
    for (const [uid, u] of m) {
      if (b.has(uid) && same(b.get(uid), u)) continue;
      units = units.filter((x) => x.id !== uid).concat([structuredClone(u)]);
    }
    out.units = units.sort((x, y) => x.opens.localeCompare(y.opens));
    for (const k of ["pace", "end", "phases", "reviews", "events"]) {
      if (JSON.stringify(mine[k] ?? null) !== JSON.stringify(mineBase[k] ?? null)) { if (mine[k] === undefined) delete out[k]; else out[k] = structuredClone(mine[k]); }
    }
    // a review day of a date one of us took off goes with it
    const ids = new Set(out.units.map((u) => u.id));
    if (out.reviews) { out.reviews = out.reviews.filter((r) => ids.has(r.from) && ids.has(r.to)); if (!out.reviews.length) delete out.reviews; }
    return out;
  }

  async function save() {
    saveBtn.disabled = true;
    status.className = "status"; status.textContent = "Saving…";
    try {
      cleanup(); byOpens();
      // each date keeps its tags' and subdecks' card count here, for a follower's "204 of 212"
      for (const u of doc.units) {
        const c = srcs(u).reduce((a, k) => a + n(k), 0);
        if (count.size && srcs(u).length) u.n = c; else if (count.size) delete u.n;
        delete u.lead;
        if (!u.check) delete u.check;
        if (!u.due) delete u.due;
        if (!(u.even && u.due && u.due > u.opens)) delete u.even;
      }
      delete doc.exam;
      const p = { mode: pace.mode, days: pace.days };
      if (pace.mode === "daily") p.daily = pace.daily || 20;
      if (pace.mode === "end" && endDaily()) p.daily = endDaily();
      if (cover.size) p.cover = coverItems().slice(0, 500);
      doc.pace = p;
      if (doc.phases && doc.phases.taper && !doc.end) doc.phases.taper = 0;
      if (doc.phases && !doc.phases.taper && !doc.phases.catchup) delete doc.phases;
      const summary = describe(base, doc);
      // 3.6.5: `idr` is the server's (from the author's Anki) and kept there; sending it back only costs size
      const lean = (d) => ({ ...d, units: (d.units || []).map(({ idr: _idr, pn: _pn, todo, ...u }) => {
        const t = Todo.clean(todo);  // Due: a line with no words yet isn't sent
        return t.length ? { ...u, todo: t } : u;
      }) });
      const body = { version: plan.version, name: meta.name.trim() || plan.name, line: meta.line, doc: lean(doc), summary };
      if (tell.value.trim()) body.post = tell.value.trim();  // 3.7.3
      if (owner && meta.squad !== (plan.squad || "")) body.squad = meta.squad || null;
      if (owner && meta.audience !== plan.audience) body.audience = meta.audience;
      let merged = false;
      try {
        plan = await api("PUT", `/plans/${id}`, body);
      } catch (err) {
        if (err.status !== 409) throw err;
        // someone else saved first: theirs, with mine on top
        const theirs = await api("GET", `/plans/${id}`);
        body.version = theirs.version;
        body.doc = lean(merge(doc, base, theirs.doc));
        plan = await api("PUT", `/plans/${id}`, body);
        merged = true;
      }
      doc = structuredClone(plan.doc);
      base = structuredClone(plan.doc);
      dirty = false; history = null; progressData = null; posts = null;
      const postFailed = plan.posted && plan.posted.error;
      if (!postFailed) tell.value = "";
      status.textContent = postFailed ? "Saved. Five posts a day per plan: your line didn't go."
        : merged ? "Saved, with the other changes kept" : "Saved";
      flash = true; draw();
      setTimeout(() => { flash = false; if (!dirty) document.querySelector(".savebar")?.classList.add("clean"); }, merged ? 5000 : 2200);
    } catch (err) {
      status.className = "status bad";
      status.textContent = err.body?.error === "plans_full" ? "Your plans hold as much as one account can. Make this one smaller, or delete a plan."
        : err.status === 409 ? "It changed again while saving. Save once more."
        : err.body?.error === "bad_plan" ? "A date isn't valid: a due date can't be before it opens, and review-only days need an end date."
        : "That didn't save. Try again.";
    } finally { saveBtn.disabled = false; }
  }

  draw();
}
