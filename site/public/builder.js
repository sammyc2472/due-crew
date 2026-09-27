// duecrew.com's plan builder (3.3): the calendar is the plan. Loaded before
// app.js, whose helpers (h, api, page, Sched, the dates) it uses when it
// runs. Names and counts only: the site never sees a card. See
// docs/plans-design.md, "3.3".

/** Readable tag names: "#AK_Step1_v12::#Pathoma::01_Growth" reads
 *  "Step 1 › Pathoma › 1 · Growth". The raw tag is always shown too. */
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

async function builder(id) {
  let plan = await api("GET", `/plans/${id}`);
  if (plan.owner !== me.uid) return go(`/plans/${id}`);
  const [{ trees }, { squads }] = await Promise.all([api("GET", `/plans/trees?deck=${encodeURIComponent(plan.doc.deck)}`), api("GET", "/squads/mine")]);
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
  const views = [["resource", "By resource"], ["system", "By system"], ["other", "Other tags"]].filter(([k]) => kindsBelow("root:tag").has(k));
  if (tree.decks.length) views.push(["deck", "Subdecks"]);

  // ---- the working copy ----
  let doc = structuredClone(plan.doc);
  let meta = { name: plan.name, line: plan.line || "", audience: plan.audience, squad: plan.squad || "" };
  const pace = { mode: "placed", days: [1, 1, 1, 1, 1, 1, 1], ...(doc.pace || {}) };
  if (!doc.pace && doc.end) pace.mode = "end";
  let cover = new Set(pace.cover || []);
  let start = Sched.start(doc) || nextMonday();
  let dirty = false;
  let tab = "calendar";
  let view = matchMedia("(max-width: 700px)").matches ? "week" : "month";
  let anchor = today() >= start ? today() : start;
  let picked = null;        // the day open in the day panel
  let splitting = null;     // {u, key} while the split panel is open
  let treeView = views[0]?.[0] || "resource";
  let note = "";            // the last thing Lay it out or a split did
  const opened = new Set(); // the tree's expanded nodes
  let term0 = "";

  const status = h("span", { class: "status", role: "status" });
  const saveBtn = h("button", { onclick: () => save() }, "Save");
  const mark = () => { dirty = true; status.className = "status"; status.textContent = "Not saved"; };
  window.onbeforeunload = () => (dirty ? true : undefined);

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
  const unitTotal = (u, placed = placedKeys()) => srcs(u).reduce((a, k) => a + eff(k, placed), 0) + (u.cards || []).length;
  const label = (key, placed) => {
    const w = kindOf(key) === "deck" ? Tags.word(pathOf(key).split("::").pop()) : Tags.word(pathOf(key).split("::").pop());
    return placedBelow(key, placed).length ? `${w} · the rest` : w;
  };
  const autoName = (u) => {
    const ks = srcs(u);
    if (!ks.length) return (u.cards || []).length ? `${u.cards.length} single card${u.cards.length === 1 ? "" : "s"}` : "?";
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
  const cleanup = () => { doc.units = doc.units.filter((u) => srcs(u).length || (u.cards || []).length); };

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
    if (!cover.size) { note = "Tick what the plan covers on the left first."; return draw(); }
    if (!items.length) { note = "Everything you ticked is on the calendar. Tick more, or drop tags on days."; return draw(); }
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
    note = r.placedN ? `Laid out ${r.placedN.toLocaleString()} cards, ${pretty(firstStudy(from))} to ${pretty(r.lastD)}.`
      : weekAhead ? "No study days left in that week." : "Nothing fit.";
    if (!weekAhead && r.lastD) anchor = firstStudy(from);
    draw();
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
        continue;
      }
      if (u.opens < from || u.opens > to) continue;
      const e = at(u.opens);
      for (const k of srcs(u)) { const c = eff(k, placed); e.chips.push({ u, key: k, text: label(k, placed), n: c, raw: pathOf(k) }); e.load += c; }
      if ((u.cards || []).length) { e.chips.push({ u, cards: true, text: `${u.cards.length} single card${u.cards.length === 1 ? "" : "s"}`, n: u.cards.length }); e.load += u.cards.length; }
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
    // a tag holding more than one view (AnKing's top tag holds resources and
    // systems, the same cards twice) covers only what this view shows of it
    const inView = (k) => (treeView === "deck" || kindOf(k) === "deck" ? [k]
      : kindsBelow(k).size > 1 ? kidsOf(k).filter((c) => kindsBelow(c).has(treeView)).flatMap(inView) : [k]);
    const toggle = (k) => {
      if (cover.has(k)) cover.delete(k);
      else if (!covered(k)) for (const x of inView(k)) { for (const c of [...cover]) if (under(x, c)) cover.delete(c); cover.add(x); }
      mark(); draw();
    };
    const row = (k, depth, full) => {
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
        h("span", { class: "nm" }, full ? Tags.name(p) : Tags.word(seg), h("span", { class: "raw" }, full ? p : seg)),
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
          if (p.toLowerCase().includes(term) || Tags.name(p).toLowerCase().includes(term)) out.push(row(k, 0, true));
          if (out.length >= 200) break;
        }
      } else {
        const shown = (k) => (treeView === "deck" ? kindOf(k) === "deck" : kindOf(k) === "tag" && kindsBelow(k).has(treeView));
        const rec = (key, depth) => {
          for (const k of kidsOf(key)) {
            if (!shown(k)) continue;
            out.push(row(k, depth, false));
            if (opened.has(k)) rec(k, depth + 1);
          }
        };
        const root = treeView === "deck" ? "root:deck" : "root:tag";
        // one root with one path down it: open the way to the first choice
        let only = kidsOf(root).filter(shown);
        while (only.length === 1 && !opened.has(`seen:${only[0]}`)) { opened.add(only[0]); opened.add(`seen:${only[0]}`); only = kidsOf(only[0]).filter(shown); }
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
      h("div", { class: "thead" }, h("b", {}, "What to cover"), h("small", { class: "muted" }, tot ? `${tot.toLocaleString()} cards ticked` : "")),
      seg, q, list,
      h("p", { class: "muted small" }, "Tick what the plan covers, then Lay it out. Or drag a tag onto a day (or press +). A tag brings everything under it."));
  }

  // ---- the pace ----
  function pacePanel() {
    const mode = (m, title, body) => h("button", { class: `pc${pace.mode === m ? " on" : ""}`, "aria-pressed": String(pace.mode === m),
      onclick: () => { if (pace.mode !== m) { pace.mode = m; if (m === "end" && !doc.end) doc.end = addDays(start, 55); mark(); draw(); } } },
      h("span", { class: "muted small" }, title), body);
    const endIn = h("input", { type: "date", value: doc.end || "", "aria-label": "Finish by", onclick: (e) => e.stopPropagation(),
      onchange: (e) => { if (e.target.value) doc.end = e.target.value; else delete doc.end; if (!doc.end && doc.phases) { doc.phases.taper = 0; } mark(); draw(); } });
    const dailyIn = h("input", { type: "number", min: 1, max: 5000, value: pace.daily || 100, "aria-label": "New cards a day", style: "width:6em", onclick: (e) => e.stopPropagation(),
      onchange: (e) => { pace.daily = Math.max(1, Math.min(5000, Math.round(Number(e.target.value) || 1))); mark(); draw(); } });
    const d1 = pace.mode === "end" ? endDaily() : 0;
    const fin = pace.mode === "daily" ? finishBy(pace.daily || 100) : null;
    const leftN = coverLeft();
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
    return h("div", { class: "pace2" },
      h("div", { class: "prow2" }, h("span", {}, "Starts ", startIn), h("span", {}, "Study days ", dayBtns),
        h("span", { class: "muted small" }, leftN ? `${leftN.toLocaleString()} ticked cards not on a day yet` : cover.size ? "Everything ticked is on a day" : "")),
      h("div", { class: "pcs" },
        mode("end", "Finish by", h("span", {}, endIn, h("small", {}, d1 ? ` ≈ ${d1.toLocaleString()} new a day` : doc.end ? " " : ""))),
        mode("daily", "New cards a day", h("span", {}, dailyIn, h("small", {}, fin ? ` finishes ≈ ${pretty(fin)}` : ""))),
        mode("placed", "Day by day", h("small", {}, "each day is what's on it: a class's syllabus"))));
  }

  // ---- the calendar ----
  function range() {
    if (view === "week") { const m = Sched.monday(anchor); return [m, addDays(m, 6)]; }
    const d = parseIso(anchor);
    const first = iso(new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1)));
    const last = iso(new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 0)));
    return [Sched.monday(first), addDays(Sched.monday(last), 6)];
  }
  function step(k) {
    if (view === "week") anchor = addDays(Sched.monday(anchor), 7 * k);
    else { const d = parseIso(anchor); anchor = iso(new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + k, 1))); }
    draw();
  }
  function calTitle() {
    const [a, b] = range();
    if (view === "week") return `${pretty(a)} – ${pretty(b)}`;
    const d = parseIso(anchor);
    return `${["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"][d.getUTCMonth()]} ${d.getUTCFullYear()}`;
  }
  function calendar() {
    const [a, b] = range();
    const days = dayMap(a, b);
    const cap = pace.mode === "end" ? endDaily() || pace.daily : pace.mode === "daily" ? pace.daily : 0;
    const month = parseIso(anchor).getUTCMonth();
    const t = today();
    const maxLoad = Math.max(1, ...[...days.values()].map((e) => e.load));
    const cells = [];
    for (let d = a; d <= b; d = addDays(d, 1)) {
      const e = days.get(d) || { chips: [], load: 0 };
      const ph = Sched.phase(doc, d, 0);
      const off = !pace.days[(parseIso(d).getUTCDay() + 6) % 7];
      const heavy = cap && e.load > cap * 1.25;
      const cls = ["d", off ? "off" : "", ph !== "build" ? ph : "", d === t ? "today" : "", view === "month" && parseIso(d).getUTCMonth() !== month ? "other" : "", d === picked ? "picked" : "", heavy ? "heavy" : ""].filter(Boolean).join(" ");
      const dd = parseIso(d);
      const num = dd.getUTCDate() === 1 || view === "week" ? `${dd.getUTCDate()} ${MONTHS[dd.getUTCMonth()]}` : String(dd.getUTCDate());
      const chips = e.chips.map((c) => {
        const el = h("button", { class: `ch ${c.cards ? "single" : hue(c.key)}${c.even ? " ev" : ""}`, draggable: "true", title: `${c.raw || c.text} · ${c.n.toLocaleString()} cards`,
          onclick: (ev) => { ev.stopPropagation(); picked = d; splitting = null; draw(); } }, h("span", {}, c.text), h("small", {}, c.n.toLocaleString()));
        el.addEventListener("dragstart", (ev) => { dragging = { chip: c }; ev.dataTransfer.setData("text/plain", c.text); ev.stopPropagation(); });
        return el;
      });
      const bar = e.load ? h("div", { class: `load${heavy ? " hi" : ""}` }, h("i", { style: `width:${Math.min(100, Math.round((100 * e.load) / (cap || maxLoad)))}%` })) : null;
      const cell = h("div", { class: cls, role: "gridcell", tabindex: "0", "aria-label": `${pretty(d)}${off ? ", a day off" : ""}${ph !== "build" ? `, ${ph === "catchup" ? "catch-up week" : "taper"}` : ""}: ${e.load ? `${e.load.toLocaleString()} cards` : "nothing new"}`,
        onclick: () => { picked = picked === d ? null : d; splitting = null; draw(); },
        onkeydown: (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); picked = picked === d ? null : d; draw(); } } },
        h("div", { class: "dn2" }, h("span", {}, num), e.load ? h("b", {}, e.load.toLocaleString()) : null), ...chips, bar);
      dropOn(cell, (what) => dropped(d, what));
      cells.push(cell);
    }
    return h("div", { class: `cal2 ${view}`, role: "grid", "aria-label": calTitle() },
      ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((x) => h("div", { class: "dh" }, x)), cells);
  }
  function heavyNote() {
    const cap = pace.mode === "end" ? endDaily() || pace.daily : pace.mode === "daily" ? pace.daily : 0;
    if (!cap) return null;
    const [a, b] = range();
    const days = dayMap(a, b);
    for (const [d, e] of [...days.entries()].sort()) {
      if (e.load <= cap * 1.25) continue;
      const big = e.chips.filter((c) => !c.even && !c.cards).sort((x, y) => y.n - x.n)[0];
      return h("div", { class: "hnote" }, h("span", {}, h("b", {}, pretty(d)), ` is heavy: ${e.load.toLocaleString()} new (pace ${cap.toLocaleString()}).`),
        big ? h("button", { class: "ghost", onclick: () => { picked = d; splitting = { u: big.u, key: big.key }; draw(); } }, `Split ${big.text}`) : null);
    }
    return null;
  }

  // ---- a day: what opens, split, checkpoint ----
  function dayPanel() {
    if (!picked) return null;
    const d = picked;
    const [a, b] = [d, d];
    const e = dayMap(a, b).get(d) || { chips: [], load: 0 };
    const own = doc.units.filter((u) => u.opens === d && !u.even);
    const spans = doc.units.filter((u) => u.even && u.due && u.opens <= d && d <= u.due);
    const rows = [];
    for (const u of own) {
      const name = h("input", { class: "uname", value: u.name, maxlength: 60, "aria-label": "This date's name",
        oninput: (ev) => { u.name = ev.target.value; auto.delete(u.id); mark(); } });
      const check = h("input", { type: "date", value: u.check || "", min: u.opens, "aria-label": "Checkpoint",
        onchange: (ev) => { u.check = ev.target.value && ev.target.value >= u.opens ? ev.target.value : undefined; mark(); } });
      const chips = e.chips.filter((c) => c.u === u).map((c) => h("span", { class: `ch2 ${c.cards ? "single" : hue(c.key)}`, title: c.raw || "" },
        h("span", {}, c.text, c.raw ? h("span", { class: "raw" }, c.raw) : null), h("small", {}, c.n.toLocaleString()),
        c.cards ? null : h("button", { class: "linkish", onclick: () => { splitting = { u, key: c.key }; draw(); } }, "Split…"),
        h("button", { class: "x", "aria-label": `Take ${c.text} off this day`, onclick: () => {
          if (c.cards) u.cards = []; else takeOut(u, c.key);
          cleanup(); renameAll(); mark(); draw(); } }, "×")));
      rows.push(h("div", { class: "du" }, name, h("div", { class: "chips2" }, chips),
        h("label", { class: "inline" }, "Checkpoint ", check, h("span", { class: "muted small" }, " that morning, followers get Anki's filtered deck of this date's most-missed cards"))));
    }
    for (const u of spans) {
      const total = unitTotal(u);
      rows.push(h("div", { class: "du" }, h("b", {}, u.name || autoName(u)),
        h("p", { class: "muted small" }, `${total.toLocaleString()} cards evenly over ${pretty(u.opens)} – ${pretty(u.due)}, the same slices for everyone, on the plan's study days.`),
        h("div", { class: "row" },
          h("button", { class: "quiet", onclick: () => { delete u.even; delete u.due; renameAll(); mark(); draw(); } }, `All on ${pretty(u.opens)}`),
          h("button", { class: "quiet", onclick: () => { doc.units = doc.units.filter((x) => x !== u); mark(); draw(); } }, "Take it off"))));
    }
    const moveIn = own.length ? h("input", { type: "date", "aria-label": "Move this day's cards to", onchange: (ev) => {
      const to = ev.target.value; if (!to || to === d) return;
      for (const u of own) { const other = doc.units.find((x) => x.opens === to && !x.even && x !== u); if (other) { for (const k of srcs(u)) addTo(to, k); other.cards = [...(other.cards || []), ...(u.cards || [])]; doc.units = doc.units.filter((x) => x !== u); } else shiftUnit(u, Sched.diff(to, u.opens)); }
      picked = to; renameAll(); byOpens(); mark(); draw(); } }) : null;
    return h("section", { class: "dayp", "aria-label": pretty(d) },
      h("div", { class: "row", style: "justify-content:space-between" }, h("b", {}, `${pretty(d)}${e.load ? ` · ${e.load.toLocaleString()} cards` : ""}`),
        h("button", { class: "quiet", onclick: () => { picked = null; splitting = null; draw(); } }, "Close")),
      splitting ? splitPanel() : null,
      rows.length ? rows : h("p", { class: "muted small" }, isStudy(d) ? "Nothing opens this day. Drag a tag here, or press + beside one on the left." : "A day off in the plan's study days. You can still put something here."),
      moveIn ? h("label", { class: "inline" }, "Move this day to ", moveIn) : null);
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
      opt("even", h("span", {}, h("b", {}, "Evenly over "), days, " study days ", per, h("span", { class: "muted small" }, " · everyone gets the same cards the same day, in the deck's order"))),
      opt("anki", h("span", {}, h("b", {}, "Pick single cards in Anki"), h("span", { class: "muted small" }, " · in the browser, search ", h("code", {}, search),
        ", select cards, then Due Crew: add to a plan, and pick this date "), h("button", { class: "quiet", onclick: (ev) => { ev.preventDefault(); copy(search, ev.target); } }, "Copy the search"))),
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
      const check = h("input", { type: "date", value: u.check || "", min: u.opens, "aria-label": "Checkpoint", onchange: (e) => { u.check = e.target.value && e.target.value >= u.opens ? e.target.value : undefined; mark(); } });
      const chips = h("div", { class: "chips2" }, srcs(u).map((k) => h("span", { class: `ch2 ${hue(k)}`, title: pathOf(k) }, h("span", {}, label(k, placed), h("span", { class: "raw" }, pathOf(k))), h("small", {}, eff(k, placed).toLocaleString()),
        h("button", { class: "x", "aria-label": `Remove ${pathOf(k)}`, onclick: () => { takeOut(u, k); cleanup(); renameAll(); mark(); draw(); } }, "×"))),
        (u.cards || []).length ? h("span", { class: "ch2 single" }, `${u.cards.length} single cards`) : null);
      return h("div", { class: "unit" }, h("span"), h("div", {}, name, chips),
        h("div", { class: "dates" }, h("span", {}, "Opens ", opens), h("span", {}, "Due ", due), h("label", { class: "inline" }, even, " evenly over its days"), h("span", {}, "Checkpoint ", check),
          h("button", { class: "del", "aria-label": `Delete ${u.name}`, onclick: () => { doc.units = doc.units.filter((x) => x !== u); mark(); draw(); } }, "×")));
    }));
  }

  // ---- as text ----
  const toText = () => { byOpens(); return doc.units.map((u) => [u.opens, u.name,
    [...(u.tags || []).map((t) => `tag:${t}`), ...(u.decks || []).map((d) => `deck:${d}`)].join(", "),
    u.due ? `due ${u.due}` : "", u.even ? "even" : "", (u.cards || []).length ? `${u.cards.length} single cards` : ""].filter(Boolean).join(" | ")).join("\n"); };

  // what an AI (or a person) might write for a tag: the exact path, any
  // case, or its readable name
  const byLower = new Map([...count.keys()].map((k) => [k.toLowerCase(), k]));
  const byName = new Map([...count.keys()].map((k) => [`${kindOf(k)}:${Tags.name(pathOf(k)).toLowerCase()}`, k]));
  const findKey = (kind, p) => byLower.get(`${kind}:${p.toLowerCase()}`) || byName.get(`${kind}:${p.toLowerCase()}`) || `${kind}:${p}`;

  function fromText(text) {
    const errors = [];
    const units = [];
    const notes = [];
    text.split("\n").forEach((raw, i) => {
      let line = raw.trim().replace(/^[-*•]\s+/, "").replace(/`/g, "");
      if (!line || /^```/.test(raw.trim())) return;
      if (line.startsWith("#")) { if (/\bpick\b|single|anki/i.test(line)) notes.push(line.replace(/^#+\s*/, "")); return; }
      const parts = line.split(/\s*\|\s*|\s{2,}/).filter(Boolean);
      let opens = null; let due; let even = false; let name = ""; const tags = []; const decks = [];
      for (const part of parts) {
        let m;
        if (!opens && (m = /^(\d{4}-\d{2}-\d{2})$/.exec(part))) opens = m[1];
        else if (!opens && (m = /^week\s+(\d+)$/i.exec(part))) opens = addDays(start, (Number(m[1]) - 1) * 7);
        else if ((m = /^due\s+(\d{4}-\d{2}-\d{2})$/i.exec(part))) due = m[1];
        else if (/^even(ly)?$/i.test(part)) even = true;
        else if (/^\d+ single cards?$/.test(part)) continue;
        else if (/^(tag|deck):/i.test(part)) {
          for (const x of part.split(/\s*[,;]\s*(?=(?:tag|deck):)/i)) {
            const kind = x.slice(0, 4).toLowerCase() === "deck" ? "deck" : "tag";
            const key = findKey(kind, x.slice(x.indexOf(":") + 1).trim());
            (kind === "tag" ? tags : decks).push(pathOf(key));
          }
        } else name = name ? `${name} ${part}` : part;
      }
      if (!opens) { errors.push(`Line ${i + 1}: starts with a date (2026-10-05) or "week 3".`); return; }
      if (!tags.length && !decks.length) { errors.push(`Line ${i + 1}: needs a tag: or a deck:.`); return; }
      if (due && due < opens) { errors.push(`Line ${i + 1}: due is before it opens.`); return; }
      if (even && !(due && due > opens)) { errors.push(`Line ${i + 1}: "even" needs a due date after it opens.`); return; }
      const old = doc.units.find((u) => u.opens === opens && u.name === (name || leaf(tags[0] || decks[0])));
      const u = { id: old?.id || uid8(), name: (name || "").slice(0, 60), opens, due, tags: [...new Set(tags)], decks: [...new Set(decks)], cards: old?.cards || [] };
      if (even) u.even = true;
      if (!u.due) delete u.due;
      if (!u.name) { u.name = autoName(u); auto.add(u.id); }
      units.push(u);
    });
    const missing = units.flatMap((u) => [...u.tags.map((t) => `tag:${t}`), ...u.decks.map((d) => `deck:${d}`)]).filter((k) => count.size && !count.has(k));
    return { units, errors, missing, notes };
  }

  /** The prompt for your own AI: the plan so far, the format, the deck's tags. */
  function aiPrompt() {
    const dayNames = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].filter((_, i) => pace.days[i]).join(", ");
    const ph = doc.phases || {};
    // the tags: what's ticked, whole; else the top three levels; at most 600 lines
    const keys = [];
    const want = cover.size ? coverItems() : kidsOf("root:tag").concat(kidsOf("root:deck"));
    const walk2 = (k, depth) => {
      if (keys.length >= 600) return;
      keys.push(k);
      if (cover.size || depth < 2) for (const c of kidsOf(k)) walk2(c, depth + 1);
    };
    for (const k of want) walk2(k, 0);
    const more = count.size - keys.length;
    const lines = keys.map((k) => `${kindOf(k)}:${pathOf(k)}  (${n(k).toLocaleString()} cards) ${Tags.name(pathOf(k))}`);
    return [
      `I'm planning what to study in Anki, day by day, for "${meta.name || plan.name}" on the deck "${doc.deck}". Due Crew opens each day's cards (unsuspends them) on the morning of that day, for me and everyone following the plan.`,
      "",
      "The plan so far:",
      `- Starts ${start}${doc.end ? `, ends ${doc.end}` : ", no end date yet"}.`,
      `- Study days: ${dayNames}.`,
      pace.mode === "daily" && pace.daily ? `- About ${pace.daily} new cards a study day.` : pace.mode === "end" && doc.end ? "- Finish everything by the end date, at an even pace." : "- Each day is exactly what's on it (a class's schedule).",
      ph.catchup ? `- Every ${ph.catchup}th week is a catch-up week: nothing new opens.` : null,
      ph.taper ? `- The last ${ph.taper} days before the end open nothing new.` : null,
      doc.units.length ? `- ${doc.units.length} dates are already planned (as text below the tags); keep or change them.` : null,
      "",
      "Write the plan in exactly this format, one line per date, and nothing else (no commentary, no table):",
      "",
      "YYYY-MM-DD | a short name | tag:FULL::TAG::PATH, tag:ANOTHER::PATH | due YYYY-MM-DD | even",
      "",
      "Rules:",
      "- The first part is the date those cards open: YYYY-MM-DD, or \"week 3\" for the Monday of the plan's third week.",
      "- A tag brings every card under it. A whole chapter is its tag; a smaller part is a deeper tag (a section, a lecture). Copy tags exactly from the list below, the part before the two spaces; never invent one.",
      "- A subdeck works the same way: deck:FULL::DECK::PATH.",
      "- Several tags can open the same day: separate them with commas on one line.",
      "- A chapter too big for one day: put its deeper tags on different days, or give it a due date and the word even to spread it evenly from its date to its due date (\"| due 2026-10-09 | even\").",
      "- Without a due date, a date's cards are meant to be done before the next date opens.",
      "- Single cards can't be chosen here (you can't see the cards). If some day needs specific cards, add a line starting with # that says which (\"# Pick in Anki for 2026-10-06: the iron-study cards from Lecture 17\"); I'll pick them in Anki.",
      "- Leave out days off and catch-up weeks.",
      "",
      "Example:",
      "2026-10-05 | Microcytic anemias | tag:#AK_Step1_v12::#Pathoma::04_Red_Blood_Cells::01_Microcytic",
      "2026-10-06 | Hemolysis | tag:#AK_Step1_v12::#Pathoma::04_Red_Blood_Cells::03_Hemolytic | due 2026-10-08 | even",
      "",
      "My syllabus, or what I want (edit this part):",
      "",
      "",
      `The deck's tags${cover.size ? " for what the plan covers" : ""} (tag or subdeck, card count, readable name)${more > 0 ? `; ${more.toLocaleString()} more aren't listed, ask me for a branch` : ""}:`,
      ...lines,
      doc.units.length ? ["", "Already planned:", toText()] : [],
    ].flat().filter((x) => x !== null).join("\n");
  }

  function textTab() {
    const ta = h("textarea", { rows: Math.max(10, doc.units.length + 3), "aria-label": "The plan as text" });
    ta.value = toText();
    const out = h("div", { class: "status", role: "status" });
    const preview = h("div");
    const read = () => {
      const r = fromText(ta.value);
      preview.replaceChildren();
      if (r.errors.length) { out.className = "status bad"; out.textContent = r.errors.slice(0, 6).join(" "); return; }
      out.className = r.missing.length ? "status bad" : "status";
      out.textContent = `${r.units.length} dates.${r.missing.length ? ` Not in your deck (they'd find nothing): ${r.missing.slice(0, 5).map((k) => pathOf(k)).join(", ")}${r.missing.length > 5 ? "…" : ""}` : ""}`;
      const placed = new Set(r.units.flatMap(srcs));
      const rows = r.units.slice().sort((a, b) => a.opens.localeCompare(b.opens)).map((u) => h("div", { class: "pvrow" },
        h("span", {}, pretty(u.opens)), h("span", {}, h("b", {}, u.name), " ", h("span", { class: "muted small" }, srcs(u).map((k) => (count.has(k) ? label(k, placed) : `${pathOf(k)} (not found)`)).join(", "))),
        h("span", { class: "muted small" }, `${u.due ? `to ${pretty(u.due)}${u.even ? ", evenly" : ""} · ` : ""}${unitTotal(u, placed).toLocaleString()} cards`)));
      const use = (replace) => {
        if (replace) doc.units = r.units;
        else for (const u of r.units) { if (!doc.units.some((x) => x.id === u.id)) doc.units.push(u); }
        byOpens(); mark(); preview.replaceChildren(); out.className = "status"; out.textContent = replace ? `Now ${doc.units.length} dates. Save to keep them.` : `Added. Now ${doc.units.length} dates. Save to keep them.`;
        ta.value = toText();
      };
      preview.append(h("div", { class: "pv" }, rows,
        r.notes.length ? h("div", { class: "hnote" }, h("span", {}, h("b", {}, "To pick in Anki: "), r.notes.join(" · "))) : null,
        h("div", { class: "row" }, h("button", { onclick: () => use(true) }, "Replace the plan's dates"), h("button", { class: "ghost", onclick: () => use(false) }, "Add to the plan"),
          h("button", { class: "quiet", onclick: () => { preview.replaceChildren(); out.textContent = ""; } }, "Cancel"))));
    };
    const aiBox = h("div", { class: "aibox" },
      h("b", {}, "Draft it with your own AI"),
      h("p", { class: "muted small" }, "Copy this prompt into any AI chat, add your syllabus or what you want where it says, and paste its answer into the box below. The prompt carries the plan's dates and your deck's tag names with counts; never a card."),
      h("div", { class: "row" }, h("button", { class: "ghost", onclick: (e) => copy(aiPrompt(), e.target) }, "Copy the prompt"),
        h("details", {}, h("summary", { class: "small" }, "See it"), h("pre", { class: "mono small muted aipre" }, aiPrompt()))));
    return h("div", { class: "stack" },
      aiBox,
      h("p", { class: "muted small" }, "One line per date: when it opens, a name, the tags and subdecks, and an optional due date, separated by |. Add even to split a date evenly up to its due date. For example:"),
      h("pre", { class: "mono small muted", style: "margin:0;white-space:pre-wrap" }, "2026-10-05 | Heart failure | tag:Step1::Cardio::Heart_failure | due 2026-10-09 | even\nweek 2 | Arrhythmia | tag:Step1::Cardio::Arrhythmia"),
      ta, h("div", { class: "row" }, h("button", { class: "ghost", onclick: read }, "Read it")), out, preview);
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
      await api("DELETE", `/plans/${id}`); dirty = false; go("/plans");
    } }, "Delete this plan");
    return h("div", { class: "stack", style: "max-width:560px" },
      h("label", { for: "sname" }, "Name"), name,
      h("label", { for: "sline" }, "One line"), line,
      h("label", { for: "ssquad" }, "Offer it to a squad"), sq,
      h("p", { class: "muted small" }, "Everyone in that squad sees it on their board in Anki."),
      h("label", {}, "Who can follow"), aud("code", "Anyone with the code"), aud("squad", meta.squad ? "Only people in that squad" : "Only people in a squad (choose one above)"),
      h("label", { for: "pend" }, "Ends (optional)"), h("div", { class: "row" }, endIn, h("span", { class: "muted small" }, "the exam, or the course's last day")),
      h("label", { for: "pcatch" }, "Catch-up weeks"), catchup,
      h("p", { class: "muted small" }, "Nothing new opens in a catch-up week: anyone behind closes the gap."),
      h("label", { for: "ptaper" }, "Taper"), h("div", { class: "row" }, taper, h("span", { class: "muted small" }, "days before the end date with no new cards, only reviews")),
      h("div", { style: "margin-top:18px" }, del));
  }

  function share() {
    const btn1 = h("button", { class: "quiet", onclick: (e) => copy(plan.code, e.target) }, "Copy");
    const url = `${location.origin}/p/${plan.code}`;
    const btn2 = h("button", { class: "quiet", onclick: (e) => copy(url, e.target) }, "Copy");
    return h("div", { class: "share" },
      h("span", { class: "muted small" }, "Code"), h("div", { class: "row" }, h("span", { class: "code" }, spaced(plan.code)), btn1),
      h("div", { class: "row" }, h("span", { class: "mono small" }, url.replace(/^https?:\/\//, "")), btn2),
      link(`/plans/${id}`, `${plan.followers} following · progress`, "small"));
  }

  function calendarTab() {
    const vbtn = (k, t) => h("button", { class: view === k ? "on" : "", "aria-pressed": String(view === k), onclick: () => { view = k; draw(); } }, t);
    const placedTotal = doc.units.reduce((a, u) => a + unitTotal(u), 0);
    return h("div", { class: "bl2" },
      h("details", { class: "side2", open: !matchMedia("(max-width: 700px)").matches }, h("summary", {}, "What to cover"), treePanel()),
      h("div", { class: "main2" },
        pacePanel(),
        h("div", { class: "caltool2" },
          view !== "list" ? h("span", { class: "row", style: "gap:4px" },
            h("button", { class: "quiet", "aria-label": "Earlier", onclick: () => step(-1) }, "‹"),
            h("button", { class: "quiet", onclick: () => { anchor = today(); draw(); } }, "Today"),
            h("button", { class: "quiet", "aria-label": "Later", onclick: () => step(1) }, "›"),
            h("b", { class: "ctitle" }, calTitle())) : h("b", {}, `${doc.units.length} dates`),
          h("span", { class: "sp" }),
          h("span", { class: "muted small" }, `${placedTotal.toLocaleString()} cards on the calendar`),
          h("span", { class: "seg" }, vbtn("month", "Month"), vbtn("week", "Week"), vbtn("list", "List"))),
        h("div", { class: "caltool2" },
          h("button", { onclick: () => layOut(false), title: "Put what you ticked on the study days, in order, at the pace" }, "Lay it out"),
          h("button", { class: "ghost", onclick: () => layOut(true), title: "Just the coming week" }, "Plan next week"),
          note ? h("span", { class: "muted small", role: "status" }, note) : null),
        heavyNote(),
        view === "list" ? h("div", {}, dayPanel(), listView()) : h("div", { class: `calwrap${picked ? " has-day" : ""}` }, calendar(), dayPanel()),
        h("p", { class: "muted small", style: "margin-top:8px" }, "Single cards come from Anki: select them in the browser, then Due Crew: add to a plan, and pick a date. Shaded weeks open nothing new (catch-up weeks, the taper).")));
  }

  function draw() {
    const tabBtn = (k, t) => h("button", { role: "tab", "aria-selected": String(tab === k), onclick: () => { tab = k; draw(); } }, t);
    page(
      h("div", { class: "bhead" },
        h("div", {}, h("h1", {}, meta.name || "Untitled"), h("p", { class: "muted" }, `${plan.doc.deck} · ${meta.line || "no line yet"}`)),
        share()),
      h("div", { class: "tabs", role: "tablist" }, tabBtn("calendar", "Calendar"), tabBtn("text", "As text"), tabBtn("settings", "Settings")),
      tab === "calendar" ? calendarTab() : tab === "text" ? textTab() : settingsTab(),
      h("div", { class: "savebar" }, saveBtn, status,
        h("span", { class: "muted small" }, "Followers get changes the next morning. Nothing they've opened is ever suspended again.")));
    $app().classList.add("wide");
  }

  async function save() {
    saveBtn.disabled = true;
    status.className = "status"; status.textContent = "Saving…";
    try {
      cleanup(); byOpens();
      // each date keeps its tags' and subdecks' card count here, for a follower's "204 of 212"
      for (const u of doc.units) {
        const c = srcs(u).reduce((a, k) => a + n(k), 0);
        if (count.size && srcs(u).length) u.n = c; else delete u.n;
        delete u.lead;
        if (!u.check) delete u.check;
        if (!u.due) delete u.due;
        if (!(u.even && u.due && u.due > u.opens)) delete u.even;
      }
      delete doc.exam;
      const p = { mode: pace.mode, days: pace.days };
      if (pace.mode === "daily") p.daily = pace.daily || 100;
      if (pace.mode === "end" && endDaily()) p.daily = endDaily();
      if (cover.size) p.cover = coverItems().slice(0, 500);
      doc.pace = p;
      if (doc.phases && doc.phases.taper && !doc.end) doc.phases.taper = 0;
      if (doc.phases && !doc.phases.taper && !doc.phases.catchup) delete doc.phases;
      const body = { version: plan.version, name: meta.name.trim() || plan.name, line: meta.line, doc };
      if (meta.squad !== (plan.squad || "")) body.squad = meta.squad || null;
      if (meta.audience !== plan.audience) body.audience = meta.audience;
      plan = await api("PUT", `/plans/${id}`, body);
      doc = structuredClone(plan.doc);
      dirty = false;
      status.textContent = "Saved";
      draw();
    } catch (err) {
      status.className = "status bad";
      status.textContent = err.status === 409 ? "This plan changed somewhere else. Reload to see it (your changes here will be lost)."
        : err.body?.error === "bad_plan" ? "Something in the plan isn't valid: check the dates (due and checkpoints can't be before a date opens; a taper needs an end date)."
        : "That didn't save. Try again.";
    } finally { saveBtn.disabled = false; }
  }

  draw();
}
