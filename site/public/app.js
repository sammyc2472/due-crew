// duecrew.com's app: sign in, your plans, the builder, a plan's page, account.
// No framework. Everything the server sends is set as text, never as HTML.
// The session is an HttpOnly cookie; this script never sees it.
"use strict";

// ---- small helpers ----

const $app = () => document.getElementById("app");

/** h("div", {class: "x", onclick}, child, "text") -> an element. Strings become text nodes. */
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, String(v));
  }
  for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) el.append(kid instanceof Node ? kid : String(kid));
  return el;
}

function page(...kids) {
  const m = $app();
  m.className = "";
  m.replaceChildren(...kids.flat().filter((k) => k !== null && k !== undefined && k !== false));
  window.scrollTo(0, 0);
  return m;
}

class ApiError extends Error {
  constructor(status, body) { super(body?.error || String(status)); this.status = status; this.body = body || {}; }
}

async function api(method, path, body) {
  const headers = { "x-due-crew": "1" };
  const init = { method, headers, credentials: "same-origin" };
  if (body !== undefined) { headers["content-type"] = "application/json"; init.body = JSON.stringify(body); }
  const res = await fetch(`/api${path}`, init);
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) throw new ApiError(res.status, data);
  return data;
}

function go(path) { history.pushState(null, "", path); route(); }

document.addEventListener("click", (e) => {
  const a = e.target.closest && e.target.closest("a[data-go]");
  if (a && !e.metaKey && !e.ctrlKey) { e.preventDefault(); go(a.getAttribute("href")); }
});
window.addEventListener("popstate", () => route());

const link = (href, text, cls) => h("a", { href, "data-go": "", class: cls }, text);

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const iso = (d) => d.toISOString().slice(0, 10);
const parseIso = (s) => new Date(`${s}T00:00:00Z`);
const addDays = (s, n) => { const d = parseIso(s); d.setUTCDate(d.getUTCDate() + n); return iso(d); };
const pretty = (s) => { const d = parseIso(s); return `${DAYS[d.getUTCDay()]} ${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`; };
const today = () => iso(new Date(Date.now() - new Date().getTimezoneOffset() * 60000));
const nextMonday = () => { let d = today(); while (parseIso(d).getUTCDay() !== 1) d = addDays(d, 1); return d; };
const spaced = (code) => `${code.slice(0, 4)} ${code.slice(4)}`;
const leaf = (p) => p.split("::").pop().replace(/_/g, " ");
const uid8 = () => Array.from(crypto.getRandomValues(new Uint8Array(8)), (b) => "abcdefghijkmnpqrstuvwxyz23456789"[b % 32]).join("");

async function copy(text, btn) {
  try { await navigator.clipboard.writeText(text); btn.textContent = "Copied"; }
  catch { btn.textContent = "Select and copy"; }
  setTimeout(() => { btn.textContent = "Copy"; }, 1600);
}

// ---- who's signed in ----

let me = null;  // {uid, name} or null

async function whoami() {
  try { me = await api("GET", "/auth/me"); } catch { me = null; }
  renderNav();
  return me;
}

function renderNav() {
  const nav = document.getElementById("nav");
  nav.replaceChildren(...(me
    ? [link("/home", "Home"), link("/plans", "Plans"), link("/log", "Log"), me.admin ? link("/admin", "Admin") : null,
       link("/account", me.name || "Account")].filter(Boolean)
    : [link("/sign-in", "Sign in")]));
}

function needSignIn() {
  go(`/sign-in?next=${encodeURIComponent(location.pathname + location.search)}`);
}

// ---- sign in ----

function signIn() {
  const next = new URLSearchParams(location.search).get("next") || "/home";
  const m = page();
  m.className = "narrow";
  const status = h("p", { class: "status", role: "status" });
  const email = h("input", { type: "email", id: "email", autocomplete: "email", required: true, style: "width:100%" });
  const form = h("form", { class: "stack", novalidate: true },
    h("h1", {}, "Sign in"),
    h("p", { class: "muted" }, "The same email you use in Anki. We send a six-digit code."),
    h("label", { for: "email" }, "Email"), email,
    h("div", {}, h("button", { type: "submit" }, "Send code")), status);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    status.className = "status"; status.textContent = "Sending…";
    try {
      await api("POST", "/auth/code", { email: email.value });
      codeStep(email.value, next);
    } catch (err) {
      status.className = "status bad";
      status.textContent = err.status === 429 ? "Too many codes for now. Try again in an hour." : "That doesn't look like an email address.";
    }
  });
  m.append(form);
  email.focus();
}

function codeStep(address, next) {
  const m = page();
  m.className = "narrow";
  const status = h("p", { class: "status", role: "status" });
  const code = h("input", { id: "code", class: "otp", inputmode: "numeric", autocomplete: "one-time-code", maxlength: 7 });
  const form = h("form", { class: "stack", novalidate: true },
    h("h1", {}, "Check your email"),
    h("p", { class: "muted" }, "We sent a code to ", h("b", {}, address), ". It expires in 10 minutes."),
    h("label", { for: "code" }, "Code"), code,
    h("div", {}, h("button", { type: "submit" }, "Sign in")), status);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    status.className = "status"; status.textContent = "Checking…";
    try {
      const r = await api("POST", "/auth/verify", { email: address, code: code.value.replace(/\D/g, ""), device: "duecrew.com", web: true });
      if (r.new || !r.name) return nameStep(next);
      await whoami();
      go(next);
    } catch (err) {
      status.className = "status bad";
      status.textContent = { wrong_code: "That code isn't right.", expired: "That code has expired. Send a new one.",
        locked: "Too many tries. Try again in an hour." }[err.body?.error] || (err.status === 429 ? "Too many tries. Try again in an hour." : "That didn't work. Try again.");
    }
  });
  m.append(form);
  code.focus();
}

function nameStep(next) {
  const m = page();
  m.className = "narrow";
  const name = h("input", { id: "name", maxlength: 60, autocomplete: "nickname", style: "width:100%" });
  const status = h("p", { class: "status", role: "status" });
  const form = h("form", { class: "stack", novalidate: true },
    h("h1", {}, "What should your crew call you?"),
    h("label", { for: "name" }, "Name"), name, h("div", {}, h("button", { type: "submit" }, "Continue")), status);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!name.value.trim()) return;
    try { await api("POST", "/sync", { profile: { name: name.value.trim() } }); await whoami(); go(next); }
    catch { status.className = "status bad"; status.textContent = "That didn't save. Try again."; }
  });
  m.append(form);
  name.focus();
}

// ---- plans ----

async function plansList() {
  const { plans } = await api("GET", "/plans/mine");
  const mineP = plans.filter((p) => p.owner === me.uid);
  const followed = plans.filter((p) => p.owner !== me.uid);
  const row = (p) => h("a", { class: "plan-row", href: p.owner === me.uid ? `/plans/${p.id}/edit` : `/plans/${p.id}`, "data-go": "" },
    h("b", {}, p.name), h("small", {}, `${p.followers} following`),
    h("small", {}, p.owner === me.uid ? `${p.doc.units.length} dates · ${p.doc.deck}` : `${p.ownerName}'s plan · ${p.doc.deck}`), h("span"));
  page(
    h("h1", {}, "Plans"),
    h("h2", {}, "Yours"),
    mineP.length ? h("div", { class: "plans" }, mineP.map(row))
      : h("p", { class: "muted" }, "To make one: in Anki, Tools › Due Crew › Make a plan from a deck."),
    h("h2", {}, "Following"),
    followed.length ? h("div", { class: "plans" }, followed.map(row))
      : h("p", { class: "muted" }, "To follow one: in Anki, Tools › Due Crew › Follow a plan, then paste its code."),
  );
}

/** /plans/new?deck=…#token: signed in by the add-on's link, then a plan for that deck. */
async function newPlan() {
  const token = location.hash.slice(1);
  if (token) {
    history.replaceState(null, "", location.pathname + location.search);  // the token leaves the address bar
    try { await api("POST", "/auth/link/redeem", { token }); }
    catch { /* expired or used: if there's a session already, carry on */ }
    await whoami();
  }
  if (!me) {
    page(h("h1", {}, "That link has expired"),
      h("p", { class: "muted" }, "Links from Anki work once, for five minutes. Open the builder from Anki again, or sign in here."),
      link("/sign-in?next=/plans", "Sign in", "btn"));
    return;
  }
  const deck = new URLSearchParams(location.search).get("deck") || "";
  const { plans } = await api("GET", "/plans/mine");
  const same = plans.filter((p) => p.owner === me.uid && p.doc.deck === deck);
  const status = h("p", { class: "status", role: "status" });
  const name = h("input", { id: "pname", maxlength: 60, value: deck ? `${deck} plan` : "", style: "width:100%" });
  const make = async () => {
    try {
      const p = await api("POST", "/plans", { name: name.value.trim() || deck, deck });
      go(`/plans/${p.id}/edit`);
    } catch { status.className = "status bad"; status.textContent = "That didn't work. Try again."; }
  };
  page(
    h("h1", {}, deck ? `A plan for ${deck}` : "A new plan"),
    same.length ? h("div", { class: "stack" }, h("p", { class: "muted" }, "You already have plans for this deck:"),
      h("div", { class: "plans" }, same.map((p) => h("a", { class: "plan-row", href: `/plans/${p.id}/edit`, "data-go": "" },
        h("b", {}, p.name), h("small", {}, `${p.doc.units.length} dates`))))) : null,
    deck ? h("div", { class: "stack", style: "max-width:460px;margin-top:14px" },
      h("label", { for: "pname" }, "Name"), name, h("div", {}, h("button", { onclick: make }, "Make the plan")), status)
      : h("p", { class: "muted" }, "Start from Anki: Tools › Due Crew › Make a plan from a deck."),
  );
}

// ---- the builder ----

async function builder(id) {
  let plan = await api("GET", `/plans/${id}`);
  if (plan.owner !== me.uid) return go(`/plans/${id}`);
  const { trees } = await api("GET", "/plans/trees");
  const tree = trees.find((t) => t.deck === plan.doc.deck) || { tags: [], decks: [] };
  const { squads } = await api("GET", "/squads/mine");
  const counts = new Map([...tree.tags.map(([p, n]) => [`tag:${p}`, n]), ...tree.decks.map(([p, n]) => [`deck:${p}`, n])]);

  // the working copy
  let doc = structuredClone(plan.doc);
  let meta = { name: plan.name, line: plan.line || "", audience: plan.audience, squad: plan.squad || "" };
  let start = doc.units[0]?.opens || nextMonday();
  // an existing plan keeps its dates until you change the rhythm or the start
  const gaps = doc.units.slice(1).map((u, i) => (parseIso(u.opens) - parseIso(doc.units[i].opens)) / 86400000);
  let rhythm = !gaps.length ? "7" : gaps.every((g) => g === 7) ? "7" : gaps.every((g) => g === 1) ? "1" : "hand";
  let dirty = false;
  let tab = "units";

  const status = h("span", { class: "status", role: "status" });
  const saveBtn = h("button", { onclick: () => save() }, "Save");
  const mark = () => { dirty = true; status.className = "status"; status.textContent = "Not saved"; };
  window.onbeforeunload = () => (dirty ? true : undefined);

  const unitCards = (u) => (u.tags || []).reduce((n, t) => n + (counts.get(`tag:${t}`) || 0), 0)
    + (u.decks || []).reduce((n, d) => n + (counts.get(`deck:${d}`) || 0), 0) + (u.cards || []).length;
  const used = () => new Set(doc.units.flatMap((u) => [...(u.tags || []).map((t) => `tag:${t}`), ...(u.decks || []).map((d) => `deck:${d}`)]));

  function refill() {
    if (rhythm === "hand") return;
    const step = Number(rhythm);
    doc.units.forEach((u, i) => {
      const gap = u.due ? (parseIso(u.due) - parseIso(u.opens)) / 86400000 : null;
      u.opens = addDays(start, Math.round(i * step));
      if (gap !== null) u.due = addDays(u.opens, gap);
    });
  }

  function addSource(key, toUnit) {
    const [kind, ...rest] = key.split(":");
    const p = rest.join(":");
    const field = kind === "tag" ? "tags" : "decks";
    if (toUnit) {
      if (!toUnit[field].includes(p)) toUnit[field].push(p);
    } else {
      const last = doc.units[doc.units.length - 1];
      const opens = last ? addDays(last.opens, rhythm === "hand" ? 7 : Number(rhythm)) : start;
      doc.units.push({ id: uid8(), name: leaf(p).slice(0, 60), opens, due: addDays(opens, 7), tags: kind === "tag" ? [p] : [], decks: kind === "deck" ? [p] : [], cards: [] });
    }
    mark(); draw();
  }

  // drag and drop, with + buttons for anyone not using a mouse
  let dragging = null;  // {source: key} or {unit: index}
  const dropTarget = (el, onDrop) => {
    el.addEventListener("dragover", (e) => { if (dragging) { e.preventDefault(); el.classList.add("over"); } });
    el.addEventListener("dragleave", () => el.classList.remove("over"));
    el.addEventListener("drop", (e) => { e.preventDefault(); el.classList.remove("over"); if (dragging) onDrop(dragging); dragging = null; });
  };

  const open = new Set();  // the tree's expanded nodes and search survive redraws
  let term0 = "";

  function treeView() {
    const q = h("input", { type: "search", placeholder: "Search tags and subdecks", "aria-label": "Search tags and subdecks", value: term0 });
    const list = h("div");
    const u = used();
    const node = (key, label, depth, n, hasKids) => {
      const tw = hasKids ? h("button", { class: "tw", "aria-label": open.has(key) ? "Collapse" : "Expand",
        onclick: (e) => { e.stopPropagation(); open.has(key) ? open.delete(key) : open.add(key); fill(); } }, open.has(key) ? "▾" : "▸") : h("span");
      const el = h("div", { class: `tnode${u.has(key) ? " used" : ""}`, draggable: "true", style: `padding-left:${6 + depth * 14}px`, title: key.slice(key.indexOf(":") + 1) },
        tw, h("span", {}, label), h("small", {}, n ?? ""), h("button", { class: "add", "aria-label": `Add ${label} as a new date`, onclick: () => addSource(key) }, "+"));
      el.addEventListener("dragstart", (e) => { dragging = { source: key }; e.dataTransfer.setData("text/plain", key); });
      return el;
    };
    function fill() {
      term0 = q.value;
      const term = q.value.trim().toLowerCase();
      const out = [];
      const section = (kind, rows, title) => {
        if (!rows.length) return;
        out.push(h("div", { class: "tsec" }, title));
        const paths = new Set(rows.map(([p]) => p));
        for (const [p, n] of rows) {
          const parts = p.split("::");
          const key = `${kind}:${p}`;
          if (term) { if (p.toLowerCase().includes(term)) out.push(node(key, p, 0, n, false)); continue; }
          // collapsed tree: a node shows when every ancestor that exists is open
          let show = true;
          for (let i = 1; i < parts.length; i++) {
            const anc = parts.slice(0, i).join("::");
            if (paths.has(anc) && !open.has(`${kind}:${anc}`)) { show = false; break; }
          }
          if (!show) continue;
          const hasKids = rows.some(([o]) => o.startsWith(`${p}::`));
          out.push(node(key, parts[parts.length - 1].replace(/_/g, " ") || p, parts.length - 1, n, hasKids));
        }
      };
      section("tag", [...tree.tags].sort((a, b) => a[0].localeCompare(b[0])), "Tags");
      section("deck", [...tree.decks].sort((a, b) => a[0].localeCompare(b[0])), "Subdecks");
      if (!out.length) out.push(h("p", { class: "muted small" }, tree.tags.length || tree.decks.length ? "Nothing matches." : "No tags or subdecks yet. In Anki: Tools › Due Crew › Make a plan from a deck."));
      list.replaceChildren(...out);
    }
    q.addEventListener("input", fill);
    fill();
    return h("div", { class: "tree" }, q, list, h("p", { class: "muted small" }, "Drag a tag or subdeck onto a date, or press + to give it a date of its own. A tag brings everything under it."));
  }

  function unitRow(u, i) {
    const name = h("input", { class: "uname", value: u.name, maxlength: 60, "aria-label": "Date name", oninput: (e) => { u.name = e.target.value; mark(); } });
    const opens = h("input", { type: "date", value: u.opens, "aria-label": "Opens", onchange: (e) => { if (e.target.value) { u.opens = e.target.value; if (u.due && u.due < u.opens) u.due = u.opens; mark(); } } });
    const due = h("input", { type: "date", value: u.due || "", "aria-label": "Due", onchange: (e) => { u.due = e.target.value && e.target.value >= u.opens ? e.target.value : undefined; mark(); draw(); } });
    // 3.2: a checkpoint, the morning followers get a filtered deck of this date's most-missed cards
    const check = h("input", { type: "date", value: u.check || "", "aria-label": "Checkpoint", title: "A checkpoint: that morning, followers get a filtered deck of this date's cards they've missed most",
      onchange: (e) => { u.check = e.target.value && e.target.value >= u.opens ? e.target.value : undefined; mark(); draw(); } });
    const chips = h("div", { class: "chips" },
      ...(u.tags || []).map((t) => h("span", { class: "chip", title: t }, `tag ${t}`, h("button", { "aria-label": `Remove ${t}`, onclick: () => { u.tags = u.tags.filter((x) => x !== t); mark(); draw(); } }, "×"))),
      ...(u.decks || []).map((d) => h("span", { class: "chip", title: d }, `deck ${d}`, h("button", { "aria-label": `Remove ${d}`, onclick: () => { u.decks = u.decks.filter((x) => x !== d); mark(); draw(); } }, "×"))),
      (u.cards || []).length ? h("span", { class: "chip cards", title: "Picked in Anki's browser" }, `${u.cards.length} single card${u.cards.length === 1 ? "" : "s"}`) : null);
    const n = unitCards(u);
    const el = h("div", { class: "unit" },
      h("span", { class: "grip", draggable: "true", title: "Drag to reorder" }, "⋮⋮"),
      h("div", {}, name, chips, h("div", { class: "muted small", style: "margin:4px 5px 0" }, n ? `about ${n} cards` : "no cards yet: drag a tag here")),
      h("div", { class: "dates" }, h("span", {}, "Opens ", opens), h("span", {}, "Due ", due), h("span", {}, "Checkpoint ", check),
        h("button", { class: "del", "aria-label": `Delete ${u.name}`, title: "Delete this date", onclick: () => { doc.units.splice(i, 1); refill(); mark(); draw(); } }, "×")));
    el.querySelector(".grip").addEventListener("dragstart", (e) => { dragging = { unit: i }; e.dataTransfer.setData("text/plain", String(i)); });
    dropTarget(el, (d) => {
      if (d.source) return addSource(d.source, u);
      if (d.unit !== undefined && d.unit !== i) {
        const [moved] = doc.units.splice(d.unit, 1);
        doc.units.splice(i, 0, moved);
        refill(); mark(); draw();
      }
    });
    return el;
  }

  /** 3.2: the plan's weeks at a glance: build, catch-up, taper, checkpoints. */
  function phaseStrip() {
    const us = Sched.units(doc);
    if (!us.length) return null;
    const first = Sched.monday(Sched.start(doc));
    const lastDay = [doc.end, ...us.map((u) => u.due || u.opens)].filter(Boolean).sort().pop();
    const weeks = Math.min(52, Math.floor(Sched.diff(lastDay, first) / 7) + 1);
    const checks = new Set(us.filter((u) => u.check).map((u) => Sched.monday(u.check)));
    const cells = [];
    for (let i = 0; i < weeks; i++) {
      const m = addDays(first, 7 * i);
      const kinds = [0, 1, 2, 3, 4, 5, 6].map((k) => Sched.phase(doc, addDays(m, k), 0));
      const kind = kinds.every((k) => k === "taper") || kinds.includes("taper") && i === weeks - 1 ? "taper" : kinds[0] === "catchup" ? "catchup" : "build";
      cells.push(h("div", { class: `ph ${kind}${checks.has(m) ? " cp" : ""}`, title: `${pretty(m)}: ${kind === "catchup" ? "catch-up week" : kind}${checks.has(m) ? ", a checkpoint" : ""}` }, `W${i + 1}`));
    }
    // a date that opens in a catch-up week or the taper waits for the next build day
    const held = us.filter((u) => Sched.phase(doc, u.opens, 0) !== "build");
    return h("div", {}, h("div", { class: "phases" }, cells),
      held.length ? h("p", { class: "status bad" }, `${held.map((u) => u.name).slice(0, 3).join(", ")}${held.length > 3 ? "…" : ""} ${held.length === 1 ? "opens" : "open"} in a catch-up week or the taper: followers start ${held.length === 1 ? "it" : "them"} on their next study day after it.`) : null);
  }

  function unitsTab() {
    const startIn = h("input", { type: "date", value: start, "aria-label": "Starts", onchange: (e) => { if (e.target.value) { start = e.target.value; refill(); mark(); draw(); } } });
    const rhythmIn = h("select", { "aria-label": "Rhythm", onchange: (e) => { rhythm = e.target.value; refill(); mark(); draw(); } },
      [["7", "One date a week"], ["3.5", "Two a week"], ["1", "One a day"], ["hand", "Dates by hand"]].map(([v, t]) => h("option", { value: v, selected: v === rhythm }, t)));
    const total = doc.units.reduce((n, u) => n + unitCards(u), 0);
    const last = doc.units[doc.units.length - 1];
    const drop = h("div", { class: "drop" }, "Drop a tag or subdeck here for a new date");
    dropTarget(drop, (d) => d.source && addSource(d.source));
    return h("div", {},
      phaseStrip(),
      h("div", { class: "tool" }, "Starts", startIn, rhythmIn,
        h("span", {}, `${doc.units.length} date${doc.units.length === 1 ? "" : "s"} · about ${total} cards${last ? ` · ends ${pretty(last.due || last.opens)}` : ""}`)),
      h("div", { class: "builder" }, treeView(), h("div", { class: "units" }, doc.units.map(unitRow), drop)),
      h("p", { class: "muted small", style: "margin-top:10px" }, "Single cards are added in Anki: select them in the browser, then Due Crew: add to a plan."));
  }

  // "As text": one line per date: date | name | tag:…, deck:… | due date
  const toText = () => doc.units.map((u) => [u.opens, u.name,
    [...(u.tags || []).map((t) => `tag:${t}`), ...(u.decks || []).map((d) => `deck:${d}`)].join(", "),
    u.due ? `due ${u.due}` : "", (u.cards || []).length ? `${u.cards.length} single cards` : ""].filter(Boolean).join(" | ")).join("\n");

  function fromText(text) {
    const errors = [];
    const units = [];
    text.split("\n").forEach((raw, i) => {
      const line = raw.trim();
      if (!line || line.startsWith("#")) return;
      const parts = line.split(/\s*\|\s*|\s{2,}/).filter(Boolean);
      let opens = null; let due; let name = ""; const tags = []; const decks = [];
      for (const part of parts) {
        let m;
        if (!opens && (m = /^(\d{4}-\d{2}-\d{2})$/.exec(part))) opens = m[1];
        else if (!opens && (m = /^week\s+(\d+)$/i.exec(part))) opens = addDays(start, (Number(m[1]) - 1) * 7);
        else if ((m = /^due\s+(\d{4}-\d{2}-\d{2})$/i.exec(part))) due = m[1];
        else if (/^\d+ single cards?$/.test(part)) continue;
        else if (/^(tag|deck):/.test(part)) {
          for (const s of part.split(/\s*,\s*(?=(?:tag|deck):)/)) (s.startsWith("tag:") ? tags : decks).push(s.slice(s.indexOf(":") + 1).trim());
        } else name = name ? `${name} ${part}` : part;
      }
      if (!opens) { errors.push(`Line ${i + 1}: starts with a date (2026-10-05) or "week 3".`); return; }
      if (!tags.length && !decks.length) { errors.push(`Line ${i + 1}: needs a tag: or a deck:.`); return; }
      if (due && due < opens) { errors.push(`Line ${i + 1}: due is before it opens.`); return; }
      const old = doc.units.find((u) => u.opens === opens && u.name === (name || leaf(tags[0] || decks[0])));
      units.push({ id: old?.id || uid8(), name: (name || leaf(tags[0] || decks[0])).slice(0, 60), opens, due, tags, decks, cards: old?.cards || [] });
    });
    const known = (k) => counts.size === 0 || counts.has(k);
    const missing = units.flatMap((u) => [...u.tags.map((t) => `tag:${t}`), ...u.decks.map((d) => `deck:${d}`)]).filter((k) => !known(k));
    return { units, errors, missing };
  }

  function textTab() {
    const ta = h("textarea", { rows: Math.max(10, doc.units.length + 3), "aria-label": "The plan as text" });
    ta.value = toText();
    const out = h("div", { class: "status", role: "status" });
    const apply = () => {
      const r = fromText(ta.value);
      if (r.errors.length) { out.className = "status bad"; out.textContent = r.errors.join(" "); return; }
      doc.units = r.units;
      mark();
      out.className = r.missing.length ? "status bad" : "status";
      out.textContent = r.missing.length ? `Read ${r.units.length} dates. Not in your deck: ${r.missing.slice(0, 5).map((k) => k.slice(k.indexOf(":") + 1)).join(", ")}${r.missing.length > 5 ? "…" : ""}` : `Read ${r.units.length} dates.`;
    };
    return h("div", { class: "stack" },
      h("p", { class: "muted small" }, "One line per date: when it opens, a name, the tags and subdecks, and an optional due date, separated by |. For example:"),
      h("pre", { class: "mono small muted", style: "margin:0" }, "2026-10-05 | Heart failure | tag:Step1::Cardio::Heart_failure | due 2026-10-12\nweek 2 | Arrhythmia | tag:Step1::Cardio::Arrhythmia"),
      ta, h("div", { class: "row" }, h("button", { class: "ghost", onclick: apply }, "Use this text")), out);
  }

  function settingsTab() {
    const name = h("input", { id: "sname", maxlength: 60, value: meta.name, style: "width:100%", oninput: (e) => { meta.name = e.target.value; mark(); } });
    const line = h("input", { id: "sline", maxlength: 120, value: meta.line, style: "width:100%", placeholder: "Organ systems, one a week, done by January.", oninput: (e) => { meta.line = e.target.value; mark(); } });
    const sq = h("select", { id: "ssquad", onchange: (e) => { meta.squad = e.target.value; if (!meta.squad) meta.audience = "code"; mark(); draw(); } },
      h("option", { value: "" }, "No squad"), squads.map((s) => h("option", { value: s.id, selected: s.id === meta.squad }, s.name)));
    const aud = (v, text) => h("label", { style: "display:flex;gap:8px;align-items:center;color:var(--ink);font-size:14px" },
      h("input", { type: "radio", name: "aud", value: v, checked: meta.audience === v, disabled: v === "squad" && !meta.squad,
        onchange: () => { meta.audience = v; mark(); } }), text);
    // 3.2: the plan's shape over time: an end date, catch-up weeks, a taper
    const ph = doc.phases || { catchup: 0, taper: 0 };
    const setPh = (k, v) => { doc.phases = { ...ph, ...(doc.phases || {}), [k]: v }; if (!doc.phases.catchup && !doc.phases.taper) delete doc.phases; mark(); };
    const endIn = h("input", { type: "date", id: "pend", value: doc.end || "", onchange: (e) => {
      if (e.target.value) doc.end = e.target.value; else { delete doc.end; if (doc.phases) { doc.phases.taper = 0; if (!doc.phases.catchup) delete doc.phases; } }
      mark(); draw(); } });
    const catchup = h("select", { id: "pcatch", onchange: (e) => setPh("catchup", Number(e.target.value)) },
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

  function draw() {
    const tabBtn = (k, t) => h("button", { role: "tab", "aria-selected": String(tab === k), onclick: () => { tab = k; draw(); } }, t);
    page(
      h("div", { class: "bhead" },
        h("div", {}, h("h1", {}, meta.name || "Untitled"), h("p", { class: "muted" }, `${plan.doc.deck} · ${meta.line || "no line yet"}`)),
        share()),
      h("div", { class: "tabs", role: "tablist" }, tabBtn("units", "Dates"), tabBtn("text", "As text"), tabBtn("settings", "Settings")),
      tab === "units" ? unitsTab() : tab === "text" ? textTab() : settingsTab(),
      h("div", { class: "savebar" }, saveBtn, status,
        h("span", { class: "muted small" }, "Followers get changes the next morning. Nothing they've opened is ever suspended again.")));
  }

  async function save() {
    saveBtn.disabled = true;
    status.className = "status"; status.textContent = "Saving…";
    try {
      // each date keeps its tags' and subdecks' card count here, for a follower's "204 of 212"
      for (const u of doc.units) {
        const n = (u.tags || []).reduce((a, t) => a + (counts.get(`tag:${t}`) || 0), 0)
          + (u.decks || []).reduce((a, d) => a + (counts.get(`deck:${d}`) || 0), 0);
        if (counts.size && (u.tags?.length || u.decks?.length)) u.n = n; else delete u.n;
      }
      delete doc.exam;  // 3.2: the exam projection is gone; the end date and the taper replace it
      for (const u of doc.units) { delete u.lead; if (!u.check) delete u.check; }
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

// ---- a plan's own page (author: progress; follower: the dates) ----

async function planPage(id) {
  const plan = await api("GET", `/plans/${id}`);
  const units = plan.doc.units;
  const parts = [h("h1", {}, plan.name), h("p", { class: "muted" }, `${plan.ownerName}'s plan · ${plan.doc.deck} · ${plan.followers} following`)];
  if (plan.line) parts.push(h("p", {}, plan.line));
  if (plan.owner === me.uid) {
    const pr = await api("GET", `/plans/${id}/progress`);
    parts.push(h("div", { class: "row" }, link(`/plans/${id}/edit`, "Edit", "btn ghost")),
      h("h2", {}, "Progress"),
      h("p", { class: "muted small" }, `${pr.sharing} of ${pr.followers} share their progress. Counts only.`),
      h("div", { class: "prog" }, h("span", { class: "h" }, "Date"), h("span", { class: "h" }, "Opened"), h("span", { class: "h" }, "Done"), h("span"),
        units.flatMap((u) => {
          const c = pr.units[u.id] || { opened: 0, done: 0 };
          const w = (n) => `${pr.sharing ? Math.round((100 * n) / pr.sharing) : 0}%`;
          return [h("span", {}, u.name), h("span", { class: "bar" }, h("i", { style: `width:${w(c.opened)}` })),
            h("span", { class: "bar" }, h("i", { style: `width:${w(c.done)}` })), h("span", { class: "n" }, `${c.opened} · ${c.done}`)];
        })));
  } else {
    if (plan.following) parts.push(onTrack(plan, false), onTrackChart(plan));
    parts.push(h("h2", {}, "Dates"), h("div", { class: "plans" }, units.map((u) =>
      h("div", { class: "plan-row" }, h("b", {}, u.name), h("small", {}, pretty(u.opens)), h("small", {}, u.due ? `due ${pretty(u.due)}` : ""), h("span")))));
  }
  page(...parts);
}

/** /p/CODE: what a shared link shows. */
async function codePage(code) {
  const how = h("p", {}, "In Anki: ", h("b", {}, "Tools › Due Crew › Follow a plan"), ", then paste ", h("span", { class: "mono" }, code), ".");
  if (!me) {
    page(h("h1", {}, "A Due Crew plan"), how,
      h("p", { class: "muted" }, "Due Crew is a free Anki add-on. ", h("a", { href: "/" }, "What it is"), "."),
      link(`/sign-in?next=${encodeURIComponent(`/p/${code}`)}`, "Sign in to see the plan", "btn ghost"));
    return;
  }
  try {
    const p = await api("GET", `/plans/peek?code=${encodeURIComponent(code)}`);
    const u = p.doc.units;
    page(h("h1", {}, p.name),
      h("p", { class: "muted" }, `${p.ownerName}'s plan · ${p.doc.deck} · ${u.length} dates${u.length ? `, ${pretty(u[0].opens)} to ${pretty(u[u.length - 1].due || u[u.length - 1].opens)}` : ""} · ${p.followers} following`),
      p.line ? h("p", {}, p.line) : null, how);
  } catch {
    page(h("h1", {}, "No plan with that code"), h("p", { class: "muted" }, "Check the code with whoever sent it. A plan for one squad only opens for its members."));
  }
}

async function account() {
  const out = async (all) => { await api("POST", all ? "/auth/signout-all" : "/auth/signout"); me = null; renderNav(); go("/sign-in"); };
  page(h("h1", {}, me.name || "Account"), h("p", { class: "muted" }, me.email),
    h("div", { class: "row" }, h("button", { class: "quiet", onclick: () => out(false) }, "Sign out"),
      h("button", { class: "quiet", onclick: () => out(true) }, "Sign out everywhere")),
    h("p", { class: "muted small", style: "margin-top:16px" }, "Deleting your account is in Anki: Tools › Due Crew › Settings › Account."));
}

// ---- routing ----

// ---- 3.2: a schedule's arithmetic (due_crew/schedule.py, the same rules) ----

const Sched = (() => {
  const day = 86400000;
  const units = (doc) => (doc?.units || []).filter((u) => u.id && u.opens);
  const start = (doc) => { const us = units(doc); return us.length ? us.map((u) => u.opens).sort()[0] : null; };
  const monday = (s) => { const d = parseIso(s); const k = (d.getUTCDay() + 6) % 7; return addDays(s, -k); };
  const diff = (a, b) => Math.round((parseIso(a) - parseIso(b)) / day);
  const shift = (doc, sched) => (sched?.start && start(doc) ? Math.max(0, diff(sched.start, start(doc))) : 0);
  function phase(doc, d, sh) {
    const ph = doc.phases || {}; const first = start(doc); const pd = addDays(d, -sh);
    if (doc.end && ph.taper && diff(doc.end, pd) < ph.taper && pd <= doc.end) return "taper";
    if (ph.catchup >= 2 && first && pd >= first && ((diff(monday(pd), monday(first)) / 7 + 1) % ph.catchup) === 0) return "catchup";
    return "build";
  }
  const weight = (doc, sched, d, sh) => (phase(doc, d, sh) !== "build" ? 0 : ((sched?.days || [1, 1, 1, 1, 1, 1, 1])[(parseIso(d).getUTCDay() + 6) % 7] || 0));
  function win(doc, u, sh) {
    let last = u.due;
    if (!last) { const later = units(doc).map((x) => x.opens).filter((o) => o > u.opens).sort(); last = later.length ? addDays(later[0], -1) : u.opens; }
    if (last < u.opens) last = u.opens;
    return [addDays(u.opens, sh), addDays(last, sh)];
  }
  function quota(doc, u, sched, total, d) {
    const sh = shift(doc, sched); const [a, b] = win(doc, u, sh);
    if (d < a || total <= 0) return 0;
    if (!sched) return total;
    let whole = 0; let upto = 0;
    for (let x = a; x <= b; x = addDays(x, 1)) { const w = weight(doc, sched, x, sh); whole += w; if (x <= d) upto += w; }
    if (whole) return Math.min(total, Math.ceil((total * upto) / whole));
    // no study day in the window: all of it on my first study day after it
    let next = b;
    for (let i = 1; i <= 60; i++) { const x = addDays(b, i); if (weight(doc, sched, x, sh)) { next = x; break; } }
    return d >= next ? total : 0;
  }
  return { units, start, shift, win, quota, phase, monday, diff };
})();

// ---- 3.2: home, my log, the admin's counts ----

const squares = (days, mon) => h("span", { class: "sqs" }, [0, 1, 2, 3, 4, 5, 6].map((i) => {
  const d = addDays(mon, i); const v = days?.[d];
  return h("i", { class: v?.studied || v?.reviews ? "on" : d > today() ? "later" : "", title: pretty(d) });
}));

// ---- 3.3: the board, as the add-on draws it (due_crew/board.py) ----

const Board = (() => {
  const MEDALS = ["🥇", "🥈", "🥉"];
  const HEADS = [["reviews", "📚 Reviews"], ["time", "⏱ Time"], ["retention", "🎯 Retention"], ["streak", "🔥 Streak"]];
  const SQUAD_HEADS = [...HEADS, ["week", "📅 7 days"]];
  const QUICK = ["🎉", "💪", "🔥", "👏", "🚀", "☕"];
  const fmtTime = (ms) => { const m = Math.floor(ms / 60000); return m >= 60 ? `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m` : `${m}m`; };
  const store = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch { return null; } return v; };
  function ago(ts) {
    if (!ts) return ["", "faded"];
    const s = Math.max(0, (Date.now() - Date.parse(ts)) / 1000);
    if (isNaN(s)) return ["", "faded"];
    if (s < 300) return ["just now", "fresh"];
    if (s < 3600) return [`${Math.floor(s / 60)}m ago`, "fresh"];
    if (s < 86400) return [`${Math.floor(s / 3600)}h ago`, "hours"];
    return [`${Math.floor(s / 86400)}d ago`, "faded"];
  }
  const showed = (d) => !!d && ("studied" in d ? !!d.studied : !!(d.reviews || d.studyTimeMs || "accuracy" in d));
  const metrics = (d) => ({ reviews: d.reviews ?? null, time: d.studyTimeMs ?? null, retention: d.accuracy ?? null, streak: d.streak ?? null, new: d.newCards ?? null });
  function weekAgg(days, labels) {
    const found = labels.map((l) => days[l]).filter(Boolean);
    if (!found.length) return null;
    const sum = (k) => { const v = found.filter((d) => k in d).map((d) => d[k]); return v.length ? v.reduce((a, b) => a + b, 0) : null; };
    const accs = found.filter((d) => "accuracy" in d);
    let ret = null;
    if (accs.length) { const w = accs.reduce((n, d) => n + Math.max(d.reviews || 1, 1), 0); ret = accs.reduce((n, d) => n + d.accuracy * Math.max(d.reviews || 1, 1), 0) / w; }
    return { reviews: sum("reviews"), time: sum("studyTimeMs"), retention: ret, streak: (found.find((d) => "streak" in d) || {}).streak ?? null, new: sum("newCards") };
  }
  function examText(iso, today) {
    if (!iso) return "";
    const d = Sched.diff(iso, today);
    if (d < 0 || d > 14) return "";
    if (d === 0) return "exam today";
    if (d === 1) return "exam tomorrow";
    const x = parseIso(iso);
    return d < 7 ? `exam ${DAYS[x.getUTCDay()]}` : `exam ${MONTHS[x.getUTCMonth()]} ${x.getUTCDate()}`;
  }
  function awayText(week, today) {
    if (!week?.awayFrom || !(week.awayFrom <= today && today <= week.awayTo)) return "";
    const back = addDays(week.awayTo, 1);
    return back === addDays(today, 1) ? "back tomorrow" : `back ${MONTHS[parseIso(back).getUTCMonth()]} ${parseIso(back).getUTCDate()}`;
  }
  /** rows for Today or Week, sorted as the add-on sorts them: [fresh, dormant]. */
  function rows(people, period, sort, today) {
    const yest = addDays(today, -1), tomorrow = addDays(today, 1);
    const mon = Sched.monday(today);
    const wk = []; for (let x = mon; x <= today; x = addDays(x, 1)) wk.push(x);
    const fresh = [], dormant = [];
    for (const p of people) {
      const w = p.week || {}; const days = w.days || {};
      const r = { p, you: p.you, paused: !!w.paused, last: p.updatedAt || "", reviews: null, time: null, retention: null, streak: null, new: null,
        stale: false, quiet: false, status: "", exam: examText(w.examDate, today), away: awayText(w, today),
        live: !!(w.liveUntil && Date.parse(w.liveUntil) > Date.now()), recap: w.recap && w.recap.day === today ? w.recap : null,
        daysWk: wk.filter((l) => showed(days[l])).length };
      if (r.paused) { dormant.push(r); continue; }
      if (period === "week") {
        const agg = weekAgg(days, wk);
        if (!agg) { if (r.you) fresh.push(r); else { r.quiet = true; dormant.push(r); } continue; }
        Object.assign(r, agg);
        fresh.push(r);
      } else {
        const t = days[tomorrow] || days[today]; const y = days[yest];
        if (t) { Object.assign(r, metrics(t)); r.status = t.status || ""; r.showup = showed(t) && [r.reviews, r.time, r.retention, r.streak].every((v) => v === null); fresh.push(r); }
        else if (y && !r.you) { Object.assign(r, metrics(y)); r.status = y.status || ""; r.stale = true; dormant.push(r); }
        else if (r.you) fresh.push(r);
        else { r.quiet = true; dormant.push(r); }
      }
    }
    const key = { reviews: "reviews", time: "time", retention: "retention", streak: "streak" }[sort] || "reviews";
    const val = (r) => (r[key] ?? -1);
    fresh.sort((a, b) => val(b) - val(a));
    const stale = dormant.filter((r) => r.stale).sort((a, b) => val(b) - val(a));
    const quiet = dormant.filter((r) => r.quiet).sort((a, b) => (b.last || "").localeCompare(a.last || ""));
    const paused = dormant.filter((r) => r.paused);
    return [fresh, [...stale, ...quiet, ...paused]];
  }

  function cheerMenu(uid, anchor) {
    document.querySelectorAll(".cheer-pop").forEach((x) => x.remove());
    const pop = h("div", { class: "cheer-pop", role: "menu" }, QUICK.map((e) => h("button", { class: "linkish", title: `Send ${e}`, onclick: async () => {
      pop.remove();
      try { await api("POST", `/cheers/${uid}`, { emoji: e }); anchor.textContent = "✓"; anchor.title = "Cheered"; }
      catch { anchor.title = "Couldn't send. Try again."; }
    } }, e)));
    anchor.after(pop);
    setTimeout(() => document.addEventListener("click", function off(ev) { if (!pop.contains(ev.target) && ev.target !== anchor) { pop.remove(); document.removeEventListener("click", off); } }), 0);
  }

  function nameCell(r) {
    const p = r.p;
    const cell = h("td", { class: "nm" }, h("span", { class: "who" }, `${p.emoji ? p.emoji + " " : ""}${p.name || "?"}${r.you ? "" : ""}`));
    if (r.paused) cell.append(h("span", { class: "note" }, " · on a break"));
    else if (r.quiet) { const [t, tone] = ago(r.last); if (t) cell.append(h("span", { class: `ago ${tone}` }, ` (${t})`)); }
    else if (r.stale) cell.append(h("span", { class: "ago faded" }, " · yesterday"));
    else { const [t, tone] = ago(r.last); if (t) cell.append(h("span", { class: `ago ${tone}` }, ` (${t})`)); }
    if (r.live) cell.append(h("span", { class: "ago fresh" }, " · studying now"));
    if (r.exam) cell.append(h("span", { class: "badge" }, ` 📖 ${r.exam}`));
    if (r.away) cell.append(h("span", { class: "badge" }, ` ✈️ ${r.away}`));
    if (r.recap) cell.append(h("span", { class: "ago fresh", title: r.recap.name }, ` · week ${r.recap.n} done`));
    if (r.status) cell.append(h("div", {}, h("span", { class: "bub", title: r.status }, r.status)));
    return cell;
  }

  function table(people, period, today, onSort) {
    const kept = store("dc-sort") || "reviews";  // "week" is the squads' own column
    const sort = HEADS.some(([k]) => k === kept) ? kept : "reviews";
    const [fresh, dormant] = rows(people, period, sort, today);
    const head = h("tr", {}, h("th"), h("th"), HEADS.map(([k, l]) => h("th", { class: k === sort ? "on" : "" },
      h("button", { class: "linkish", onclick: () => { store("dc-sort", k); onSort(); } }, l + (k === sort ? " ▾" : "")))), h("th"));
    let n = 0;
    const tr = (r, rank) => {
      const rv = r.reviews === null ? "—" : h("span", {}, r.reviews.toLocaleString(), r.new > 0 && r.reviews > 0 ? h("small", {}, r.new >= r.reviews ? "all new" : `${Math.min(r.new, r.reviews).toLocaleString()} new`) : null);
      const dash = r.paused || r.quiet;
      const cheer = r.you ? h("td") : h("td", { class: "chc" }, h("button", { class: "linkish cheer", title: "Send a cheer", onclick: (e) => cheerMenu(r.p.uid, e.currentTarget) }, "🎉"));
      return h("tr", { class: [r.you ? "you" : "", r.stale || r.quiet || r.paused ? "dim" : ""].join(" ").trim() },
        h("td", { class: "rk" }, rank), nameCell(r),
        h("td", { class: "n" }, dash ? "—" : rv), h("td", { class: "n" }, dash || r.time === null ? "—" : fmtTime(r.time)),
        h("td", { class: "n" }, dash || r.retention === null ? "—" : `${r.retention.toFixed(1)}%`),
        h("td", { class: "n" }, dash || r.streak === null ? "—" : String(r.streak)), cheer);
    };
    const body = [...fresh.map((r) => { if (r.showup) return tr(r, "✓"); n++; return tr(r, n <= 3 ? MEDALS[n - 1] : `#${n}`); }), ...dormant.map((r) => tr(r, "—"))];
    return h("div", { class: "scrollx" }, h("table", { class: "brdt" }, h("thead", {}, head), h("tbody", {}, body)));
  }

  /** show-up mode: a square a day, Monday to today, nothing ranked. */
  function presence(people, today) {
    const mon = Sched.monday(today); const wk = []; for (let x = mon; x <= today; x = addDays(x, 1)) wk.push(x);
    const lit = (p) => wk.filter((l) => showed((p.week?.days || {})[l])).length;
    const sorted = [...people].sort((a, b) => lit(b) - lit(a) || (a.name || "").localeCompare(b.name || ""));
    const todayN = people.filter((p) => showed((p.week?.days || {})[today])).length;
    return h("div", { class: "scrollx" }, h("table", { class: "brdt" },
      h("thead", {}, h("tr", {}, h("th", { class: "lt", colspan: 2 }, `${todayN} showed up today`), wk.map((l) => h("th", { class: l === today ? "sqh on" : "sqh" }, "MTWTFSS"[(parseIso(l).getUTCDay() + 6) % 7])))),
      h("tbody", {}, sorted.map((p) => h("tr", { class: p.you ? "you" : "" }, h("td", { class: "rk" }), h("td", { class: "nm" }, h("span", { class: "who" }, `${p.emoji ? p.emoji + " " : ""}${p.name}`)),
        wk.map((l) => h("td", { class: "sqc" }, h("i", { class: `sq${showed((p.week?.days || {})[l]) ? " on" : ""}` }))))))));
  }

  function decks(me, crew, decksBy) {
    const mine = decksBy[me.uid] || [];
    if (!mine.length) return h("p", { class: "muted small" }, "No shared decks yet. In Anki: Settings › Shared decks.");
    const match = (a, b) => { const x = new Set(a.sig || []); return (b.sig || []).some((g) => x.has(g)); };
    const bar = (name, d, isMe) => {
      const total = Math.max(d.total || 0, 1); const pct = (v) => Math.min(100, Math.round((100 * (v || 0)) / total));
      return h("div", { class: `dr${isMe ? " me" : ""}`, title: `${(d.seen || 0).toLocaleString()} seen · ${(d.mature || 0).toLocaleString()} mature · ${(d.total || 0).toLocaleString()} total` },
        h("span", { class: "dn" }, name), h("span", { class: "dtrack" }, h("i", { class: "fo", style: `left:${pct(d.seen)}%;width:${Math.max(0, pct(d.open) - pct(d.seen))}%` }),
          h("i", { class: "fs", style: `width:${pct(d.seen)}%` }), h("i", { class: "fm", style: `width:${pct(d.mature)}%` })),
        h("span", { class: "n" }, `${(d.seen || 0).toLocaleString()} / ${(d.total || 0).toLocaleString()}`));
    };
    return h("div", {}, mine.map((d) => h("div", { class: "dg" }, h("b", { class: "dgh" }, d.name),
      bar(me.name || "You", d, true), crew.map((f) => { const od = (decksBy[f.uid] || []).find((x) => match(d, x)); return od ? bar(f.name, od, false) : null; }))),
      h("p", { class: "muted small" }, "solid = mature · faded = seen · hatched = unlocked · % of each person's own copy"));
  }

  /** A squad board, as _squads_html: plain ranks, no medals, no cheers;
   *  these aren't necessarily people you know. */
  async function squads(showUp, crewUids, onSort) {
    const { squads: list } = await api("GET", "/squads/mine");
    if (!list.length) return h("p", { class: "muted small" }, "A private board for any group. Join with a code, or create one in Anki: Tools › Due Crew › Squads.");
    const sort = store("dc-sort") || "reviews";
    const field = { reviews: "reviews", time: "studyTimeMs", retention: "accuracy", streak: "streak", week: "week" }[sort] || "reviews";
    const day = todayLocal(), yday = addDays(day, -1);
    const out = [];
    for (const sq of await Promise.all(list.map((q) => api("GET", `/squads/${q.id}`)))) {
      const rows = sq.rows || [];
      const live = rows.filter((r) => r.day === day);
      const rest = rows.filter((r) => r.day !== day).sort((x, y) => (y.day || "").localeCompare(x.day || ""));
      if (showUp) live.sort((x, y) => (y.week || 0) - (x.week || 0) || x.name.localeCompare(y.name));
      else live.sort((x, y) => (y[field] ?? -1) - (x[field] ?? -1));
      const together = live.reduce((n, r) => n + (r.reviews || 0), 0);
      let line = `${rows.length.toLocaleString()} in ${sq.name}` + (sq.open === false ? " · locked" : "");
      if (live.length) line += showUp ? ` · ${live.length.toLocaleString()} showed up today` : ` · ${live.length.toLocaleString()} studying today · ${together.toLocaleString()} reviews together`;
      const heads = showUp ? [h("th", {}, "📅 7 days")] : SQUAD_HEADS.map(([k, l]) => h("th", { class: k === sort ? "on" : "" },
        h("button", { class: "linkish", onclick: () => { store("dc-sort", k); onSort(); } }, l + (k === sort ? " ▾" : ""))));
      const numberless = (r) => ["reviews", "studyTimeMs", "accuracy", "streak"].every((k) => r[k] == null);
      let n = 0;
      const body = [...live, ...rest].map((r) => {
        const you = r.uid === me.uid, today = r.day === day;
        const note = you ? null : crewUids.has(r.uid) ? h("span", { class: "ago faded" }, " · crew") : null;
        const when = today ? null : h("span", { class: "ago faded" }, ` · ${r.day === yday ? "yesterday" : "quiet"}`);
        const rank = !today ? "" : showUp || numberless(r) ? "✓" : `#${++n}`;
        const cells = showUp ? [h("td", { class: "n" }, r.week != null ? `${r.week}/7` : "—")] : [
          h("td", { class: "n" }, r.reviews == null ? "—" : h("span", {}, r.reviews.toLocaleString(), r.newCards > 0 && r.reviews > 0 ? h("small", {}, r.newCards >= r.reviews ? "all new" : `${r.newCards.toLocaleString()} new`) : null)),
          h("td", { class: "n" }, r.studyTimeMs != null ? fmtTime(r.studyTimeMs) : "—"),
          h("td", { class: "n" }, r.accuracy != null ? `${r.accuracy.toFixed(1)}%` : "—"),
          h("td", { class: "n" }, r.streak != null ? String(r.streak) : "—"),
          h("td", { class: "n" }, r.week != null ? `${r.week}/7` : "—")];
        return h("tr", { class: [you ? "you" : "", today ? "" : "dim"].join(" ").trim() },
          h("td", { class: "rk" }, rank), h("td", { class: "nm" }, h("span", { class: "who" }, `${r.emoji ? r.emoji + " " : ""}${r.name}`), note, when), cells);
      });
      out.push(h("div", { class: "scrollx sqb" }, h("table", { class: "brdt" },
        h("thead", {}, h("tr", {}, h("th", { class: "sqh", colspan: 2 }, line), heads)), h("tbody", {}, body))));
    }
    return h("div", {}, out);
  }

  function shareText(people, today) {
    const me = people.find((p) => p.you); const d = (me?.week?.days || {})[today] || {};
    const bits = [d.reviews != null ? `${d.reviews.toLocaleString()} reviews` : null, d.studyTimeMs ? fmtTime(d.studyTimeMs) : null, d.accuracy != null ? `${d.accuracy.toFixed(1)}%` : null, d.streak ? `🔥 ${d.streak}` : null].filter(Boolean);
    return `Due Crew · ${pretty(today)}: ${bits.join(" · ") || "showed up"}`;
  }

  return { table, presence, decks, squads, shareText, ago, store };
})();

const todayLocal = () => today();

async function home() {
  const [b, plansR, sett] = await Promise.all([api("GET", "/board?keep=1&decks=1"), api("GET", "/plans/mine"), api("GET", "/settings").catch(() => null)]);
  const t = today();
  const mon = Sched.monday(t);
  const showUp = !!sett?.settings?.show_up;
  const people = [{ ...b.me, you: true }, ...b.friends.filter((f) => f.mutual)];
  const crew = b.friends.filter((f) => f.mutual);
  const waiting = b.friends.filter((f) => !f.mutual);
  const tabs = showUp ? [["today", "Crew"], ["decks", "Decks"], ["squads", "Squads"]] : [["today", "Today"], ["week", "Week"], ["decks", "Decks"], ["squads", "Squads"]];
  let tab = Board.store("dc-tab") || "today";
  if (!tabs.some(([k]) => k === tab)) tab = "today";
  const pills = h("span", { class: "pills" });
  const panel = h("div");
  const fetched = Date.now();
  const updated = h("span", { class: "muted" });
  async function draw() {
    pills.replaceChildren(...tabs.map(([k, l]) => h("button", { class: tab === k ? "on" : "", onclick: () => { tab = k; Board.store("dc-tab", k); draw(); } }, l)));
    const mins = Math.floor((Date.now() - fetched) / 60000);
    updated.textContent = mins < 1 ? "Updated just now" : `Updated ${mins}m ago`;
    if (tab === "decks") return panel.replaceChildren(Board.decks(b.me, crew, b.decks || {}));
    if (tab === "squads") { panel.replaceChildren(h("p", { class: "muted small" }, "Loading…")); return panel.replaceChildren(await Board.squads(showUp, new Set(crew.map((f) => f.uid)), draw)); }
    panel.replaceChildren(...[showUp ? Board.presence(people, t) : Board.table(people, tab, t, draw),
      crew.length ? null : h("p", { class: "muted small" }, "Just you so far. ", b.me.code ? `Your code ${spaced(b.me.code)} · ` : "", "add your crew in Anki: Tools › Due Crew › Friends."),
      waiting.length ? h("p", { class: "muted small" }, `Waiting for ${waiting.map((f) => f.name).join(", ")} to add you back.`) : null].filter(Boolean));
  }
  const friendsBox = h("div", { class: "note-inline", hidden: true },
    h("span", {}, "Your code ", h("b", { class: "mono" }, b.me.code ? spaced(b.me.code) : "—"), ". Friends add you by it in Anki (Tools › Due Crew › Friends)."),
    b.me.code ? h("button", { class: "quiet", onclick: (e) => copy(`Study with me on Due Crew · my code ${b.me.code}`, e.target) }, "Copy") : null);
  const shareBtn = h("button", { class: "linkish", onclick: async () => {
    try { await navigator.clipboard.writeText(Board.shareText(people, t)); shareBtn.textContent = "Copied"; } catch { shareBtn.textContent = Board.shareText(people, t); }
    setTimeout(() => { shareBtn.textContent = "Share today"; }, 1800);
  } }, "Share today");
  await draw();
  const my = b.me.week?.days || {};
  const studied = Object.entries(my).filter(([d, v]) => d >= mon && (v.studied || v.reviews)).length;
  const minutes = Object.entries(my).filter(([d]) => d >= mon).reduce((n, [, v]) => n + (v.studyTimeMs || 0), 0) / 60000;
  const followed = plansR.plans.filter((p) => p.following);
  page(h("div", { class: "wb" },
    h("section", { class: "brd" },
      h("div", { class: "top2" }, pills),
      panel,
      h("div", { class: "foot" },
        h("span", {}, h("button", { class: "linkish", onclick: () => { friendsBox.hidden = !friendsBox.hidden; } }, "Friends"), " · ", shareBtn),
        h("span", {}, updated, " · ", h("button", { class: "linkish", onclick: () => route() }, "Refresh"))),
      friendsBox),
    h("aside", { class: "rail" },
      h("section", { class: "panel" }, h("h4", {}, "This week", h("span", { class: "muted" }, "Mon–Sun")),
        h("div", { class: "row" }, squares(my, mon), h("span", { class: "muted small" }, `${studied} day${studied === 1 ? "" : "s"} · ${Math.floor(minutes / 60)}h ${Math.round(minutes % 60)}m`))),
      h("section", { class: "panel" }, h("h4", {}, "Cheers", h("span", { class: "muted" }, String(b.cheers.length))),
        b.cheers.length ? b.cheers.map((c) => h("div", { class: "cheer" }, h("b", {}, `${c.emoji} ${c.name}`), c.note ? ` ${c.note}` : "")) : h("p", { class: "muted small" }, "None waiting."),
        b.cheers.length ? h("small", { class: "muted" }, "They play in Anki too.") : null),
      followed.length ? h("section", { class: "panel" }, h("h4", {}, "Plans", link("/log", "Log")), followed.map((p) => onTrack(p, true))) : null)));
}

/** A plan I follow: cards seen against my schedule, from what my Anki last shared. */
function onTrack(p, compact) {
  const prog = p.following?.progress || {};
  const sched = p.following?.sched || null;
  const seen = Object.values(prog).reduce((n, t) => n + t[1], 0);
  const total = Object.values(prog).reduce((n, t) => n + t[2], 0);
  const want = Sched.units(p.doc).reduce((n, u) => n + Sched.quota(p.doc, u, sched, prog[u.id]?.[2] || 0, today()), 0);
  const gap = want - seen;
  const words = !total ? "Your progress shows once you share it (in Anki: Plan ▾)." :
    gap > 0 ? `${gap.toLocaleString()} behind your schedule` : "on track";
  if (compact) {
    return h("div", { class: "prow" }, link(`/plans/${p.id}`, p.name), h("span", { class: "bar" }, h("i", { style: `width:${total ? Math.round((100 * seen) / total) : 0}%` })),
      h("small", { class: gap > 0 ? "warn" : "muted" }, total ? words : ""));
  }
  return h("p", { class: gap > 0 ? "warn" : "muted" }, total ? `${seen.toLocaleString()} of ${total.toLocaleString()} seen · ${words}` : words);
}

/** Cards seen against my schedule, as a line: the schedule dashed, me as a dot today. */
function onTrackChart(p) {
  const prog = p.following?.progress || {};
  const sched = p.following?.sched || null;
  const us = Sched.units(p.doc);
  if (!us.length || !Object.keys(prog).length) return null;
  const sh = Sched.shift(p.doc, sched);
  const first = addDays(Sched.start(p.doc), sh);
  const last = us.map((u) => Sched.win(p.doc, u, sh)[1]).sort().pop();
  const span = Math.max(1, Sched.diff(last, first));
  const step = Math.max(1, Math.ceil(span / 60));
  const pts = [];
  for (let i = 0; i <= span; i += step) {
    const d = addDays(first, i);
    pts.push([i, us.reduce((n, u) => n + Sched.quota(p.doc, u, sched, prog[u.id]?.[2] || 0, d), 0)]);
  }
  const seen = Object.values(prog).reduce((n, t) => n + t[1], 0);
  const top = Math.max(1, ...pts.map((x) => x[1]), seen) * 1.08;
  const W = 560; const H = 190; const L = 44; const R = 70; const T = 12; const B = 24;
  const x = (i) => L + ((W - L - R) * i) / span; const y = (v) => T + (H - T - B) * (1 - v / top);
  const ns = "http://www.w3.org/2000/svg";
  const s = (tag, attrs, text) => { const e = document.createElementNS(ns, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v)); if (text !== undefined) e.textContent = text; return e; };
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img", "aria-label": "Cards seen against my schedule" });
  for (let k = 0; k <= 4; k++) {
    const v = Math.round((top / 1.08) * (k / 4));
    svg.append(s("line", { x1: L, x2: W - R, y1: y(v), y2: y(v), class: "grid" }), s("text", { x: L - 6, y: y(v) + 4, class: "tick", "text-anchor": "end" }, v.toLocaleString()));
  }
  svg.append(s("text", { x: L, y: H - 6, class: "tick" }, pretty(first)), s("text", { x: W - R, y: H - 6, class: "tick", "text-anchor": "end" }, pretty(last)));
  svg.append(s("polyline", { points: pts.map(([i, v]) => `${x(i)},${y(v)}`).join(" "), class: "ln plan" }));
  const ti = Math.min(span, Math.max(0, Sched.diff(today(), first)));
  const dot = s("circle", { cx: x(ti), cy: y(seen), r: 4.5, class: "dot" });
  dot.append(s("title", {}, `You, ${pretty(today())}: ${seen.toLocaleString()} seen`));
  svg.append(dot, s("text", { x: x(ti) + 8, y: y(seen) + 4, class: "lab" }, `You ${seen.toLocaleString()}`));
  return h("div", {}, h("div", { class: "key" }, h("span", {}, h("i", { class: "k-you" }), "you"), h("span", {}, h("i", { class: "k-plan" }), sched ? "your schedule" : "the plan's dates")), svg);
}

function barChart(values, labels, cap, unit) {
  const W = 560; const H = 170; const L = 34; const R = 8; const T = 14; const B = 22;
  const top = Math.max(1, ...values, cap || 0) * 1.12;
  const ns = "http://www.w3.org/2000/svg";
  const s = (tag, attrs, text) => { const e = document.createElementNS(ns, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v)); if (text !== undefined) e.textContent = text; return e; };
  const y = (v) => T + (H - T - B) * (1 - v / top);
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img", "aria-label": `${unit} by week` });
  for (let k = 0; k <= 3; k++) {
    const v = Math.round((top / 1.12) * (k / 3));
    svg.append(s("line", { x1: L, x2: W - R, y1: y(v), y2: y(v), class: "grid" }), s("text", { x: L - 6, y: y(v) + 4, class: "tick", "text-anchor": "end" }, v));
  }
  const slot = (W - L - R) / values.length; const bw = Math.max(6, slot - 6);
  values.forEach((v, i) => {
    const x0 = L + i * slot + (slot - bw) / 2;
    const r = s("rect", { x: x0, y: y(v), width: bw, height: Math.max(0, y(0) - y(v)), rx: 3, class: "barm" });
    r.append(s("title", {}, `${labels[i]}: ${v} ${unit}`));
    svg.append(r, s("text", { x: x0 + bw / 2, y: H - 6, class: "tick", "text-anchor": "middle" }, labels[i]));
  });
  if (cap) svg.append(s("line", { x1: L, x2: W - R, y1: y(cap), y2: y(cap), class: "cap" }), s("text", { x: W - R, y: y(cap) - 5, class: "capl", "text-anchor": "end" }, `your ${cap} min`));
  return svg;
}

async function logPage() {
  const [log, plansR] = await Promise.all([api("GET", "/log"), api("GET", "/plans/mine")]);
  const days = log.days || {};
  const mon = Sched.monday(today());
  const week = Object.entries(days).filter(([d]) => d >= mon);
  const sum = (rows, i) => rows.reduce((n, [, r]) => n + (r[i] || 0), 0);
  const graded = week.filter(([, r]) => r[3] !== null);
  const ret = graded.length ? graded.reduce((n, [, r]) => n + r[3] * r[1], 0) / graded.reduce((n, [, r]) => n + r[1], 0) : null;
  let streak = 0;
  for (let d = today(); days[d] || (d === today() && streak === 0 && days[addDays(d, -1)]); d = addDays(d, -1)) if (days[d]) streak++;
  const mins = sum(week, 0);
  const metric = { i: 0, unit: "minutes a day" };
  const box = h("div");
  const minutesPlan = plansR.plans.find((p) => p.following?.sched)?.following.sched.minutes || 0;
  function drawChart() {
    const vals = []; const labels = [];
    for (let w = 11; w >= 0; w--) {
      const m0 = addDays(mon, -7 * w);
      const rows = Object.entries(days).filter(([d]) => d >= m0 && d < addDays(m0, 7));
      let v;
      if (metric.i === 3) {
        const g = rows.filter(([, r]) => r[3] !== null);
        v = g.length ? Math.round(g.reduce((n, [, r]) => n + r[3] * r[1], 0) / g.reduce((n, [, r]) => n + r[1], 0)) : 0;
      } else v = Math.round(sum(rows, metric.i) / 7);
      vals.push(v);
      const d = parseIso(m0);
      labels.push(w % 3 === 0 || w === 11 ? `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}` : "");
    }
    box.replaceChildren(barChart(vals, labels, metric.i === 0 ? minutesPlan : 0, metric.unit));
  }
  const pills = h("div", { class: "pills" });
  const pick = [["Minutes", 0, "minutes a day"], ["Reviews", 1, "reviews a day"], ["New", 2, "new cards a day"], ["Retention", 3, "% retention"]];
  const drawPills = () => pills.replaceChildren(...pick.map(([l, i, u]) => h("button", { class: metric.i === i ? "on" : "", onclick: () => { metric.i = i; metric.unit = u; drawPills(); drawChart(); } }, l)));
  drawPills(); drawChart();
  const followed = plansR.plans.filter((p) => p.following);
  page(h("h1", {}, "Your log"), h("p", { class: "muted" }, "Only you see this. It fills in from Anki's syncs."),
    h("div", { class: "tiles" },
      h("div", {}, h("b", {}, `${week.length} of 7`), h("small", {}, "days this week")),
      h("div", {}, h("b", {}, `${Math.floor(mins / 60)}h ${Math.round(mins % 60)}m`), h("small", {}, "studied")),
      h("div", {}, h("b", {}, sum(week, 1).toLocaleString()), h("small", {}, "reviews")),
      h("div", {}, h("b", {}, sum(week, 2).toLocaleString()), h("small", {}, "new cards")),
      h("div", {}, h("b", {}, ret === null ? "—" : `${ret.toFixed(1)}%`), h("small", {}, "retention")),
      h("div", {}, h("b", {}, String(streak)), h("small", {}, "day streak"))),
    h("div", { class: "row", style: "justify-content:space-between;margin-top:18px" }, h("h2", { style: "margin:0" }, "By week"), pills), box,
    followed.length ? h("h2", {}, "Plans") : null,
    followed.map((p) => h("section", { class: "panel", style: "margin-bottom:12px" }, h("h4", {}, link(`/plans/${p.id}`, p.name)), onTrack(p, false), onTrackChart(p))));
}

async function adminPage() {
  const [s, nl] = await Promise.all([api("GET", "/admin/stats"), api("GET", "/admin/notices")]);
  const tile = (v, l) => h("div", {}, h("b", {}, typeof v === "number" ? v.toLocaleString() : v), h("small", {}, l));

  // 3.2.1: a notice on everyone's board (3.2.1 and later), one line
  const status = h("p", { class: "status", role: "status" });
  const text = h("input", { id: "ntext", maxlength: 200, style: "width:100%", placeholder: "Due Crew 3.2 is out: plans your crew can follow together." });
  const nlink = h("input", { id: "nlink", type: "url", style: "width:100%", placeholder: "https://duecrew.com (optional)" });
  const below = h("input", { id: "nbelow", style: "width:8em", placeholder: "3.2.1" });
  const days = h("input", { id: "ndays", type: "number", min: 1, max: 60, value: 14, style: "width:6em" });
  const count = h("small", { class: "muted" }, "0 / 200");
  text.addEventListener("input", () => { count.textContent = `${text.value.length} / 200`; });
  const list = h("div", { class: "plans" });
  const drawList = (notices) => list.replaceChildren(...(notices.length ? notices.map((n) => {
    const rm = h("button", { class: "quiet", onclick: async () => {
      rm.disabled = true;
      try { await api("DELETE", `/admin/notices/${n.id}`); drawList((await api("GET", "/admin/notices")).notices); }
      catch { rm.disabled = false; rm.textContent = "Try again"; }
    } }, "Take down");
    const until = new Date(n.until * 1000);
    return h("div", { class: "plan-row" }, h("b", {}, n.text), rm,
      h("small", {}, [n.below ? `to add-ons before ${n.below}` : "to everyone", `until ${DAYS[until.getDay()]} ${until.getDate()} ${MONTHS[until.getMonth()]}`, n.link || ""].filter(Boolean).join(" · ")));
  }) : [h("p", { class: "muted small" }, "No notice showing.")]));
  drawList(nl.notices);
  const send = h("button", { onclick: async () => {
    if (!text.value.trim()) { status.className = "status bad"; status.textContent = "Write the notice first."; return; }
    send.disabled = true; status.className = "status"; status.textContent = "Posting…";
    try {
      await api("POST", "/admin/notices", { text: text.value, link: nlink.value.trim() || null, below: below.value.trim() || null, days: Number(days.value) || 14 });
      text.value = ""; nlink.value = ""; count.textContent = "0 / 200";
      status.textContent = "Posted. It shows at each board's next refresh.";
      drawList((await api("GET", "/admin/notices")).notices);
    } catch (err) {
      status.className = "status bad";
      status.textContent = err.body?.error === "bad_link" ? "The link must start with https://."
        : err.body?.error === "bad_below" ? "The version looks like 3.2.1." : "That didn't post. Try again.";
    } finally { send.disabled = false; }
  } }, "Post notice");

  page(h("h1", {}, "Admin"), h("p", { class: "muted" }, "Counts only. Never names or emails."),
    h("div", { class: "tiles" }, tile(`${s.on3} / ${s.accounts}`, "on 3.x"), tile(s.seenDay, "seen today"), tile(s.seenWeek, "seen this week"),
      tile(s.mutualPairs, "mutual friendships"), tile(s.squads, `squads · ${s.memberships} in them`), tile(s.plans, `plans · ${s.follows} following`), tile(s.tips, "tips on cards")),
    h("h2", {}, "A notice"),
    h("p", { class: "muted small" }, "One line at the top of everyone's board in Anki (3.2.1 and later), with More when there's a link, until they dismiss it. The newest one shows."),
    h("div", { class: "stack", style: "max-width:600px" },
      h("label", { for: "ntext" }, "Text"), text, count,
      h("label", { for: "nlink" }, "Link"), nlink,
      h("div", { class: "row" }, h("span", { class: "muted small" }, "Only to add-ons older than"), below, h("span", { class: "muted small" }, "for"), days, h("span", { class: "muted small" }, "days")),
      h("div", {}, send), status),
    h("h2", {}, "Showing now"), list,
    h("h2", {}, "Versions"), h("table", { class: "crew" }, h("tbody", {}, s.versions.map(([v, n]) => h("tr", {}, h("td", { class: "nm" }, v), h("td", { class: "n" }, n.toLocaleString()))))));
}

async function route() {
  const path = location.pathname.replace(/\/+$/, "") || "/";
  try {
    if (path === "/sign-in") return signIn();
    if (path === "/plans/new") return await newPlan();
    let m;
    if ((m = /^\/p\/([A-Za-z0-9]{1,16})$/.exec(path))) return await codePage(m[1].toUpperCase());
    if (!me) return needSignIn();
    if (path === "/plans") return await plansList();
    if (path === "/home" || path === "/") return await home();
    if (path === "/log") return await logPage();
    if (path === "/admin") return await adminPage();
    if (path === "/account") return account();
    if ((m = /^\/plans\/([a-z0-9]{16})\/edit$/.exec(path))) return await builder(m[1]);
    if ((m = /^\/plans\/([a-z0-9]{16})$/.exec(path))) return await planPage(m[1]);
    page(h("h1", {}, "Not here"), link("/plans", "Your plans"));
  } catch (err) {
    if (err.status === 401) { me = null; renderNav(); return needSignIn(); }
    page(h("h1", {}, err.status === 404 ? "Not found" : "Something went wrong"),
      h("p", { class: "muted" }, err.status === 404 ? "It may have been deleted, or it isn't yours to see." : "Try again in a moment."));
  }
}

whoami().then(route);
