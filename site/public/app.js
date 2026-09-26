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
    ? [link("/plans", "Plans"), link("/account", me.name || "Account")]
    : [link("/sign-in", "Sign in")]));
}

function needSignIn() {
  go(`/sign-in?next=${encodeURIComponent(location.pathname + location.search)}`);
}

// ---- sign in ----

function signIn() {
  const next = new URLSearchParams(location.search).get("next") || "/plans";
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
    const chips = h("div", { class: "chips" },
      ...(u.tags || []).map((t) => h("span", { class: "chip", title: t }, `tag ${t}`, h("button", { "aria-label": `Remove ${t}`, onclick: () => { u.tags = u.tags.filter((x) => x !== t); mark(); draw(); } }, "×"))),
      ...(u.decks || []).map((d) => h("span", { class: "chip", title: d }, `deck ${d}`, h("button", { "aria-label": `Remove ${d}`, onclick: () => { u.decks = u.decks.filter((x) => x !== d); mark(); draw(); } }, "×"))),
      (u.cards || []).length ? h("span", { class: "chip cards", title: "Picked in Anki's browser" }, `${u.cards.length} single card${u.cards.length === 1 ? "" : "s"}`) : null);
    const n = unitCards(u);
    const el = h("div", { class: "unit" },
      h("span", { class: "grip", draggable: "true", title: "Drag to reorder" }, "⋮⋮"),
      h("div", {}, name, chips, h("div", { class: "muted small", style: "margin:4px 5px 0" }, n ? `about ${n} cards` : "no cards yet: drag a tag here")),
      h("div", { class: "dates" }, h("span", {}, "Opens ", opens), h("span", {}, "Due ", due),
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

  function unitsTab() {
    const startIn = h("input", { type: "date", value: start, "aria-label": "Starts", onchange: (e) => { if (e.target.value) { start = e.target.value; refill(); mark(); draw(); } } });
    const rhythmIn = h("select", { "aria-label": "Rhythm", onchange: (e) => { rhythm = e.target.value; refill(); mark(); draw(); } },
      [["7", "One date a week"], ["3.5", "Two a week"], ["1", "One a day"], ["hand", "Dates by hand"]].map(([v, t]) => h("option", { value: v, selected: v === rhythm }, t)));
    const total = doc.units.reduce((n, u) => n + unitCards(u), 0);
    const last = doc.units[doc.units.length - 1];
    const drop = h("div", { class: "drop" }, "Drop a tag or subdeck here for a new date");
    dropTarget(drop, (d) => d.source && addSource(d.source));
    return h("div", {},
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
    const exam = doc.exam || null;
    const examDate = h("input", { type: "date", id: "edate", value: exam?.date || "", onchange: (e) => { if (e.target.value) doc.exam = { ...(doc.exam || { target: 85 }), date: e.target.value, by: addDays(e.target.value, -35) }; else delete doc.exam; mark(); draw(); } });
    const target = h("input", { type: "number", id: "etarget", min: 50, max: 100, value: exam?.target ?? 85, disabled: !exam, style: "width:6em",
      onchange: (e) => { const v = Math.max(50, Math.min(100, Math.round(Number(e.target.value) || 85))); if (doc.exam) { doc.exam.target = v; mark(); } } });
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
      h("label", { for: "edate" }, "Exam (optional)"),
      h("div", { class: "row" }, examDate, h("span", { class: "muted small" }, "target"), target, h("span", { class: "muted small" }, "% of the plan's cards mature, five weeks before")),
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
        : err.body?.error === "bad_plan" ? "Something in the plan isn't valid: check the dates (due can't be before it opens)."
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

async function route() {
  const path = location.pathname.replace(/\/+$/, "") || "/";
  try {
    if (path === "/sign-in") return signIn();
    if (path === "/plans/new") return await newPlan();
    let m;
    if ((m = /^\/p\/([A-Za-z0-9]{1,16})$/.exec(path))) return await codePage(m[1].toUpperCase());
    if (!me) return needSignIn();
    if (path === "/plans") return await plansList();
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
