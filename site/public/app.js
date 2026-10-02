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

// the builder sets onbeforeunload while it has unsaved changes; moving
// within the site asks the same question a closing tab does
let here = location.pathname + location.search;
function leaveOk() {
  const unsaved = window.onbeforeunload;
  if (unsaved && unsaved() && !confirm("Leave without saving your changes?")) return false;
  window.onbeforeunload = null;
  return true;
}

function go(path) {
  if (!leaveOk()) return;
  history.pushState(null, "", path);
  route();
}

document.addEventListener("click", (e) => {
  const a = e.target.closest && e.target.closest("a[data-go]");
  if (a && !e.metaKey && !e.ctrlKey) { e.preventDefault(); go(a.getAttribute("href")); }
});
window.addEventListener("popstate", () => {
  if (!leaveOk()) { history.pushState(null, "", here); return; }
  route();
});
// a menu (Add to calendar) closes when you click anywhere else
document.addEventListener("click", (e) => {
  for (const d of document.querySelectorAll("details.calmenu[open], details.sharemenu[open]")) if (!d.contains(e.target)) d.open = false;
});

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

// ---- my accent (3.5.0): the one I picked in Anki, here too ----

// [accent, ink on it, my row's fill], by day and by night: board.py's ACCENTS
const ACCENTS = {
  green: [["#2e7d32", "#ffffff", "#e9f2e9"], ["#7cc47f", "#122912", "#2c372b"]],
  blue: [["#1e5fb4", "#ffffff", "#e8f0fb"], ["#7fb2f0", "#0b1f3a", "#263244"]],
  purple: [["#6b3fb5", "#ffffff", "#f0eafb"], ["#b89cf0", "#22143d", "#322a46"]],
  teal: [["#0f766e", "#ffffff", "#e5f4f2"], ["#7dd3c8", "#0b2a28", "#22383a"]],
  amber: [["#a35f00", "#ffffff", "#fbf1e2"], ["#e0a458", "#2d1d05", "#3d3323"]],
  rose: [["#b03052", "#ffffff", "#fbe9ee"], ["#f08fa8", "#3a1220", "#3f2a31"]],
};
let worn = "green";
let brandImgs = null;

function wearAccent(name) {
  if (!ACCENTS[name] || name === worn) return;
  worn = name;
  try { localStorage.setItem("dc-accent", name); } catch { /* private window: this page only */ }
  const [day, night] = ACCENTS[name];
  const vars = (t) => `--accent:${t[0]};--accent-ink:${t[1]};--you:${t[2]};`;
  let tag = document.getElementById("dc-accent");
  if (!tag) { tag = document.createElement("style"); tag.id = "dc-accent"; document.head.append(tag); }
  tag.textContent = name === "green" ? "" : `:root{${vars(day)}}@media (prefers-color-scheme: dark){:root{${vars(night)}}}`;
  // the logo's studied days wear it too, as in Anki: our own file, drawn inline
  const brand = document.querySelector("header .brand");
  if (!brand) return;
  brandImgs ||= [...brand.children];
  if (name === "green") { brand.replaceChildren(...brandImgs); return; }
  fetch("/logo.svg").then((r) => r.text()).then((text) => {
    if (worn !== name) return;
    const svg = new DOMParser().parseFromString(text.replace(/fill="#2e7d32"/g, 'style="fill:var(--accent)"')
      .replace(/fill="#242424"/g, 'style="fill:var(--ink)"').replace(/fill="#e2e2da"/g, 'style="fill:var(--line)"'), "image/svg+xml").documentElement;
    svg.setAttribute("class", "logo-inline");
    brand.replaceChildren(svg);
  }).catch(() => {});
}

try { wearAccent(localStorage.getItem("dc-accent") || "green"); } catch { /* no storage: green until I know */ }

/** 3.5.0: Copy invite makes a one-time link, as in Anki; offline it
 *  carries my friend code. Safari only lets a click write the clipboard
 *  if it starts writing at once, so the text goes in as a promise. */
function copyInvite(friendCode, btn) {
  const text = api("POST", "/invites").then((r) => r.code, () => friendCode)
    .then((code) => `Study with me on Due Crew: duecrew.com/i/${code}`);
  const done = (ok) => {
    btn.textContent = ok ? "Copied. Send one per friend." : "Couldn't copy";
    setTimeout(() => { btn.textContent = "Copy invite"; }, 2400);
  };
  try {
    if (window.ClipboardItem) {
      navigator.clipboard.write([new ClipboardItem({ "text/plain": text.then((t) => new Blob([t], { type: "text/plain" })) })])
        .then(() => done(true), () => text.then((t) => navigator.clipboard.writeText(t)).then(() => done(true), () => done(false)));
    } else text.then((t) => navigator.clipboard.writeText(t)).then(() => done(true), () => done(false));
  } catch { done(false); }
}

// ---- who's signed in ----

let me = null;  // {uid, name} or null

async function whoami() {
  try { me = await api("GET", "/auth/me"); } catch { me = null; }
  if (me) wearAccent(me.accent || "green");
  renderNav();
  return me;
}

function renderNav() {
  const nav = document.getElementById("nav");
  // 3.6.5, P6: Feedback in the footer of every signed-in page, carrying the page it came from
  const foot = document.getElementById("foot");
  if (foot) foot.replaceChildren(...(me ? [h("a", { href: "/feedback", onclick: (e) => {
    e.preventDefault(); go(`/feedback?from=${encodeURIComponent(location.pathname)}`); } }, "Feedback")] : []));
  if (!me) { nav.replaceChildren(link("/sign-in", "Sign in")); return; }
  // 3.4 review, N4: on a phone, Home and Plans, and the rest under me
  const rest = () => [link("/log", "Log"), me.admin ? link("/admin", "Admin") : null, link("/account", me.name || "Account")].filter(Boolean);
  nav.replaceChildren(link("/home", "Home"), link("/plans", "Plans"), link("/library", "Library"),
    h("span", { class: "wide-only" }, rest()),
    h("details", { class: "navme calmenu" }, h("summary", { "aria-label": "More" }, (me.name || "?").slice(0, 1).toUpperCase()),
      h("div", { class: "calpop" }, rest())));
}

/** "5 days (7 blocks)": the calendar days a plan opens on, and its named
 *  blocks only when some day holds more than one. */
function daysText(days, blocks) {
  return `${days} day${days === 1 ? "" : "s"}${blocks > days ? ` (${blocks} blocks)` : ""}`;
}
const planDays = (doc) => daysText(new Set((doc.units || []).map((u) => u.opens)).size, (doc.units || []).length);

function needSignIn() {
  go(`/sign-in?next=${encodeURIComponent(location.pathname + location.search)}`);
}

// ---- sign in ----

function signIn() {
  // only a page of this site: "//elsewhere" would leave it
  const asked = new URLSearchParams(location.search).get("next") || "";
  const next = /^\/(?![/\\])/.test(asked) ? asked : "/home";
  const m = page();
  m.className = "narrow";
  const status = h("p", { class: "status", role: "status" });
  const email = h("input", { type: "email", id: "email", autocomplete: "email", required: true, style: "width:100%" });
  const title = h("h1", {}, "Sign in");
  const plan = /^\/p\/([A-Za-z0-9]{8})/.exec(next);
  if (plan) {
    title.textContent = "Sign in to open the plan";
    api("GET", `/plans/public?code=${plan[1]}`).then((p) => { title.textContent = `Sign in to open ${p.name}`; }).catch(() => {});
  }
  const form = h("form", { class: "stack", novalidate: true },
    title,
    h("p", { class: "muted" }, "The same email you use in Anki. New here? The same code makes your account."),
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
  const writes = (p) => p.role === "owner" || p.role === "editor";
  const mineP = plans.filter(writes);
  const followed = plans.filter((p) => !writes(p));
  // 3.4 review, H10: the name, then what it runs on and when, and who follows
  const span = (p) => { const u = Sched.units(p.doc); return u.length ? `${pretty(u[0].opens)} – ${pretty(u[u.length - 1].due || u[u.length - 1].opens)}` : "no dates yet"; };
  const row = (p) => h("a", { class: "plan-row", href: `/plans/${p.id}`, "data-go": "" },
    h("b", {}, p.name), h("small", { class: "fol" }, `${p.followers} following`),
    h("small", {}, [writes(p) ? (p.role === "editor" ? `with ${p.ownerName}` : null) : `${p.ownerName}'s plan`,
      p.doc.deck !== p.name ? p.doc.deck : null, planDays(p.doc), span(p)].filter(Boolean).join(" · ")));
  const how = h("p", { class: "muted small", hidden: true }, "Pick the deck in Anki: Tools › Due Crew › Make a plan from a deck. It opens here.");
  page(
    h("h1", {}, "Plans"),
    codeBox(),
    h("div", { class: "row", style: "justify-content:space-between;margin-top:18px" }, h("h2", { style: "margin:0" }, "Yours"),
      h("button", { class: "ghost", onclick: () => { how.hidden = !how.hidden; } }, "New plan")), how,
    mineP.length ? h("div", { class: "plans" }, mineP.map(row))
      : h("p", { class: "muted" }, "None yet."),
    h("h2", {}, "Following"),
    followed.length ? h("div", { class: "plans" }, followed.map(row))
      : h("p", { class: "muted" }, "None yet. A plan's code goes in the box above."),
    h("p", { class: "muted small", style: "margin-top:12px" }, "Or find one to follow or copy in the ", link("/library", "library"), "."),
  );
}

// ---- 3.5, B: the library ----

/** "Jordan's plan", or the copy's credit: "based on Step 1 in 8 weeks, Jordan's". */
const credit = (b) => (b ? `based on ${b.name}${b.owner && b.owner !== "?" ? `, ${b.owner}'s` : ""}` : null);

/** Copy a plan into one of my own: its first date on the day I pick. */
function copyForm(p, done) {
  const start = h("input", { type: "date", value: nextMonday(), "aria-label": "Its first date" });
  const status = h("span", { class: "status", role: "status" });
  const btn = h("button", { onclick: async () => {
    if (!start.value) return;
    btn.disabled = true; status.className = "status"; status.textContent = "Copying…";
    try {
      const mine = await api("POST", `/plans/${p.id}/copy`, { start: start.value });
      go(`/plans/${mine.id}`);
    } catch (err) {
      btn.disabled = false; status.className = "status bad";
      status.textContent = err.body?.error === "too_many_plans" ? "You have 50 plans. Delete one first." : err.status === 429 ? "That's a lot of new plans. Try again in an hour." : "That didn't work. Try again.";
    }
  } }, "Copy");
  return h("div", { class: "copyform" }, h("span", { class: "muted small" }, "Starting"), start, btn,
    done ? h("button", { class: "linkish", onclick: done }, "Cancel") : null, status);
}

/** Report a plan in the library: it goes to Sam by mail; nothing is stored. */
function reportForm(p, done) {
  const why = h("select", { "aria-label": "Why" }, [["spam", "Not a study plan"], ["copied", "Copied without credit"], ["other", "Something else"]]
    .map(([v, t]) => h("option", { value: v }, t)));
  const note = h("input", { maxlength: 200, placeholder: "Anything to add (optional)", "aria-label": "Note" });
  const status = h("span", { class: "status", role: "status" });
  const send = h("button", { class: "ghost", onclick: async () => {
    send.disabled = true;
    try { await api("POST", `/plans/${p.id}/report`, { reason: why.value, note: note.value.trim() || null }); status.textContent = "Sent. Thanks."; setTimeout(done, 1400); }
    catch { send.disabled = false; status.className = "status bad"; status.textContent = "That didn't send. Try again."; }
  } }, "Send");
  return h("div", { class: "copyform" }, why, note, send, h("button", { class: "linkish", onclick: done }, "Cancel"), status);
}

async function libraryPage() {
  const q = new URLSearchParams(location.search);
  const f = { deck: q.get("deck") || "", len: q.get("len") || "", q: q.get("q") || "" };
  let pg = 0;
  const grid = h("div", { class: "lib" });
  const more = h("button", { class: "quiet", hidden: true }, "More");
  const filters = h("div", { class: "filters" });
  const search = h("input", { type: "search", value: f.q, placeholder: "Search plans", "aria-label": "Search plans", style: "flex:1 1 200px" });
  const empty = h("p", { class: "muted", hidden: true });
  const tags = (p) => [daysText(p.daysOn ?? p.dates, p.dates), p.perDay ? `~${p.perDay.toLocaleString()} new a study day` : null,
    p.days ? `${Math.max(1, Math.round(p.days / 7))} week${Math.round(p.days / 7) > 1 ? "s" : ""}` : null,
    p.reviews ? `${p.reviews} review day${p.reviews === 1 ? "" : "s"}` : null, p.events ? `${p.events} event${p.events === 1 ? "" : "s"}` : null].filter(Boolean);
  function card(p) {
    const extra = h("div");
    const el = h("div", { class: "lc" },
      h("a", { href: `/plans/${p.id}`, "data-go": "", class: "lcname" }, p.name),
      h("span", { class: "muted small" }, [`${p.ownerName}'s plan`, p.deck, credit(p.basedOn)].filter(Boolean).join(" · ")),
      p.line ? h("span", { class: "small" }, p.line) : null,
      h("div", { class: "lctags" }, tags(p).map((t) => h("span", {}, t))),
      h("span", { class: "muted small" }, `${p.followers.toLocaleString()} following`),
      h("div", { class: "row" },
        link(`/plans/${p.id}`, "Look", "btn ghost"),
        h("button", { onclick: () => extra.replaceChildren(copyForm(p, () => extra.replaceChildren())) }, "Copy"),
        p.mine ? h("span", { class: "muted small", style: "margin-left:auto" }, "Yours") : h("button", { class: "linkish", style: "margin-left:auto", onclick: () => extra.replaceChildren(reportForm(p, () => extra.replaceChildren())) }, "Report"),
        me.admin ? h("button", { class: "linkish", onclick: async () => {
          const note = prompt("Take it out of the library. Its author reads why:", "Not a study plan");
          if (!note) return;
          try { await api("POST", `/admin/library/${p.id}`, { note }); el.remove(); } catch { alert("That didn't work."); }
        } }, "Take out") : null),
      extra);
    return el;
  }
  function pill(k, v, t) {
    return h("button", { class: `pill${f[k] === v ? " on" : ""}`, onclick: () => { f[k] = f[k] === v ? "" : v; load(true); } }, t);
  }
  async function load(fresh) {
    if (fresh) pg = 0;
    const qs = new URLSearchParams(Object.entries(f).filter(([, v]) => v));
    history.replaceState(null, "", `/library${qs.toString() ? `?${qs}` : ""}`);
    here = location.pathname + location.search;
    qs.set("page", pg);
    let r;
    try { r = await api("GET", `/library?${qs}`); } catch { empty.hidden = false; empty.textContent = "Couldn't load the library. Try again."; return; }
    filters.replaceChildren(
      ...r.decks.map(([d]) => pill("deck", d, d)),
      r.decks.length ? h("span", { class: "muted" }, "·") : null,
      pill("len", "short", "Up to 4 weeks"), pill("len", "mid", "4–12 weeks"), pill("len", "long", "Longer"));
    if (fresh) grid.replaceChildren();
    grid.append(...r.plans.map(card));
    more.hidden = !r.more;
    empty.hidden = grid.children.length > 0;
    empty.textContent = f.deck || f.len || f.q ? "Nothing matches. Try fewer filters." : "Nothing here yet. List a plan of yours from its Settings.";
  }
  more.addEventListener("click", () => { pg++; load(false); });
  let t = null;
  search.addEventListener("input", () => { clearTimeout(t); t = setTimeout(() => { f.q = search.value.trim(); load(true); }, 300); });
  page(h("h1", {}, "Library"),
    h("p", { class: "muted" }, "Plans people list for anyone to follow or copy. Newest first."),
    h("div", { class: "row" }, search), filters, grid, empty, more);
  await load(true);
}

/** /plans/new?deck=…#token: signed in by the add-on's link, then a plan for that deck. */
async function newPlan() {
  // the link's token was traded for a session at start
  if (!me) {
    page(h("h1", {}, "That link has expired"),
      h("p", { class: "muted" }, "Links from Anki work once, for five minutes. Open the builder from Anki again, or sign in here."),
      link("/sign-in?next=/plans", "Sign in", "btn"));
    return;
  }
  const deck = new URLSearchParams(location.search).get("deck") || "";
  if (!deck) { page(h("h1", {}, "A new plan"), h("p", { class: "muted" }, "Start from Anki: Tools › Due Crew › Make a plan from a deck.")); return; }
  const { plans } = await api("GET", "/plans/mine");
  const same = plans.filter((p) => (p.role === "owner" || p.role === "editor") && p.doc.deck === deck);
  const status = h("p", { class: "status", role: "status" });
  const make = async () => {
    try {
      const p = await api("POST", "/plans", { name: deck, deck });
      history.replaceState(null, "", `/plans/${p.id}`);
      route();
    } catch { status.className = "status bad"; status.textContent = "That didn't work. Try again."; }
  };
  // 3.3: straight to the calendar; only a deck that has plans already asks which
  if (!same.length) return make();
  page(
    h("h1", {}, deck),
    h("div", { class: "plans" }, same.map((p) => h("a", { class: "plan-row", href: `/plans/${p.id}`, "data-go": "" },
      h("b", {}, p.name), h("small", {}, planDays(p.doc))))),
    h("div", { style: "margin-top:12px" }, h("button", { class: "ghost", onclick: make }, "New plan")), status,
  );
}

// ---- the builder: builder.js ----

// ---- a plan's own page (author: progress; follower: the dates) ----

/** 3.4 review, H1: any code someone sent: a friend's (6), a plan's or a
 *  squad's (8). It says what it is before anything happens. */
function codeBox() {
  const input = h("input", { id: "anycode", placeholder: "A friend's, a plan's or a squad's code", "aria-label": "A code", autocomplete: "off" });
  const out = h("div", { class: "codeout", role: "status" });
  const say = (cls, ...kids) => out.replaceChildren(h("div", { class: `res ${cls}` }, ...kids));
  const code = () => {
    const t = input.value.toUpperCase();
    const inLink = /\/I\/([A-Z0-9]{10}|[A-Z0-9]{6})(?![A-Z0-9])/.exec(t);  // 3.5.0: an invite's link
    if (inLink) return inLink[1];
    const bare = t.replace(/[^A-Z0-9]/g, "");
    if (bare.length === 6 || bare.length === 8 || bare.length === 10) return bare;
    const m = /(?:^|[^A-Z0-9])([A-Z0-9]{4}\s?[A-Z0-9]{4}|[A-Z0-9]{6})(?:[^A-Z0-9]|$)/.exec(t);  // pasted with its invite
    return m ? m[1].replace(/\s/g, "") : "";
  };
  const done = (text) => { say("ok", h("span", {}, text)); input.value = ""; };
  async function look() {
    const c = code();
    if (!c) { say("bad", h("span", {}, "That doesn't look like a code. Pasting the whole invite works too.")); return; }
    say("", h("span", { class: "muted" }, "Looking…"));
    try {
      if (c.length === 10) {
        const inv = await api("GET", `/invites/${c}`);
        const who = `${inv.emoji ? `${inv.emoji} ` : ""}${inv.name}`;
        return say("", h("b", {}, who), h("span", { class: "muted" }, "an invite"), h("button", { onclick: async () => {
          try {
            const r = await api("POST", `/invites/${c}/redeem`);
            done(r.mutual ? `You and ${r.name} are crew.` : r.knocked ? `Added ${r.name}. You're crew once they add you back.` : `${r.name} isn't in your crew now.`);
          } catch (err) { say("bad", h("span", {}, err.status === 400 ? "That's your own invite." : "That didn't work. Try again.")); }
        } }, `Add ${inv.name}`));
      }
      if (c.length === 6) {
        const f = await api("GET", `/codes/${c}`);
        const who = `${f.emoji ? `${f.emoji} ` : ""}${f.name}`;
        if (f.mine) return say("bad", h("span", {}, "That's your own code."));
        if (f.added) return say("", h("b", {}, who), h("span", { class: "muted" }, "already in your crew"));
        return say("", h("b", {}, who), h("span", { class: "muted" }, "a friend's code"), h("button", { onclick: async () => {
          try { const r = await api("POST", `/codes/${c}/add`); done(r.mutual ? `You and ${r.name} are crew.` : `Added ${r.name}. You're crew once they add you back.`); }
          catch { say("bad", h("span", {}, "That didn't work. Try again.")); }
        } }, `Add ${f.name}`));
      }
      let plan = null;
      try { plan = await api("GET", `/plans/peek?code=${c}`); } catch (err) { if (err.status === 429) throw err; }
      if (plan) {
        if (plan.following) return say("", h("b", {}, plan.name), h("span", { class: "muted" }, "you follow it"), link(`/plans/${plan.id}`, "Open"));
        return say("", h("b", {}, plan.name), h("span", { class: "muted" }, `${plan.ownerName}'s plan · ${planDays(plan.doc)}`), h("button", { onclick: async () => {
          try { await api("POST", "/plans/follow", { code: c }); done("Following. Each date's cards open in Anki on their day; the first time, Anki asks about holding later ones back."); }
          catch { say("bad", h("span", {}, "That didn't work. Try again.")); }
        } }, "Follow"));
      }
      const sq = await api("GET", `/squads/peek?code=${c}`);
      return say("", h("b", {}, sq.name), h("span", { class: "muted" }, sq.open ? "a squad" : "a squad · locked"), sq.open ? h("button", { onclick: async () => {
        try {
          await api("POST", `/squads/${sq.id}/join`, { code: c });
          // the add-on keeps my squads in my settings: this one joins them there too
          let doc = null;
          try { doc = await api("GET", "/settings"); } catch { doc = null; }
          const set = { ...(doc?.settings || {}) };
          const list = Array.isArray(set.squads) ? set.squads.filter((q) => q && q.id !== sq.id) : [];
          set.squads = [...list, { id: sq.id, code: sq.code, name: sq.name, founder: sq.founder }];
          await api("PUT", "/settings", { v: doc?.v || 1, at: new Date().toISOString(), settings: set }).catch(() => {});
          done(`You're in ${sq.name}. It shows in Anki's Squads next time Anki opens.`);
        } catch { say("bad", h("span", {}, "That didn't work. The squad may have just closed.")); }
      } }, "Join") : null);
    } catch (err) {
      say("bad", h("span", {}, err.status === 429 ? "That's a lot of codes. Try again in an hour." : "That code doesn't match a friend, a plan or a squad."));
    }
  }
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") look(); });
  return h("div", { class: "codebox" }, h("label", { for: "anycode" }, "Got a code?"),
    h("div", { class: "row" }, input, h("button", { class: "ghost", onclick: look }, "Look up")), out);
}

/** 3.4: a plan's dates in any calendar, as a subscription that follows changes. */
function calMenu(code) {
  const https = `${location.origin}/p/${code}.ics`;
  const webcal = https.replace(/^https?:/, "webcal:");
  return h("details", { class: "calmenu" }, h("summary", {}, "Add to calendar"),
    h("div", { class: "calpop" },
      h("a", { href: `https://calendar.google.com/calendar/render?cid=${encodeURIComponent(webcal)}`, target: "_blank", rel: "noopener" }, "Google Calendar"),
      h("a", { href: webcal }, "Apple Calendar or Outlook"),
      h("button", { class: "linkish", onclick: (e) => copy(https, e.target) }, "Copy the calendar link")));
}

/** 3.4 review, C2: on a phone, send yourself the link for the computer. */
function emailMe(path) {
  const email = h("input", { type: "email", id: "mailme", autocomplete: "email", placeholder: "you@school.edu", "aria-label": "Your email" });
  const status = h("p", { class: "status", role: "status" });
  const send = h("button", { class: "ghost", onclick: async () => {
    if (!email.value.trim()) return;
    send.disabled = true; status.className = "status"; status.textContent = "Sending…";
    try { await api("POST", "/links/email", { email: email.value, path }); status.textContent = `Sent. Open it on your computer.`; email.value = ""; }
    catch (err) { status.className = "status bad"; status.textContent = err.status === 429 ? "That's a few already. Try again later." : "That doesn't look like an email address."; }
    finally { send.disabled = false; }
  } }, "Email it");
  return h("div", { class: "phone-only mailme" },
    h("p", {}, "It's for Anki on a computer. Send yourself the link:"),
    h("div", { class: "row" }, email, send),
    h("p", { class: "muted small" }, "One email with this link. No account, nothing else."), status);
}

/** A plan as its link shows it: name, whose, the dates. From
 *  /plans/public (signed out) or a peek (signed in). */
function planIntro(p) {
  const u = p.units || [];
  const last = u.length ? u[u.length - 1] : null;
  const shown = u.slice(0, 4);
  return [h("h1", {}, p.name),
    h("p", { class: "muted" }, `${p.ownerName}'s plan · ${u.length} date${u.length === 1 ? "" : "s"}${u.length ? `, ${pretty(u[0].opens)} to ${pretty(last.due || last.opens)}` : ""} · ${p.followers} following`),
    p.line ? h("p", {}, p.line) : null,
    u.length ? h("div", { class: "pdates" }, shown.map((x) => h("div", {}, h("small", {}, pretty(x.opens)), h("span", {}, x.name), h("small", {}, x.n ? x.n.toLocaleString() : ""))),
      u.length > shown.length ? h("div", {}, h("small", {}), h("span", { class: "muted" }, `and ${u.length - shown.length} more, to ${pretty(last.due || last.opens)}`), h("small", {})) : null) : null];
}

/** /p/CODE: what a shared link shows. */
async function codePage(code) {
  // 3.3: someone who has never heard of Due Crew gets here from a teacher's link
  const copyBtn = (text) => h("button", { class: "quiet", onclick: (e) => copy(text, e.target) }, "Copy");
  const steps = (deck) => h("ol", { class: "steps" },
    h("li", {}, "Open Anki on your computer (", h("a", { href: "https://apps.ankiweb.net" }, "get it free"), ")", deck ? [", with the deck ", h("b", {}, deck), " in it"] : null, "."),
    h("li", {}, "Add Due Crew: Tools › Add-ons › Get Add-ons, paste ", h("b", { class: "mono" }, "2035408484"), " ", copyBtn("2035408484"), ", then restart Anki."),
    h("li", {}, "Tools › Due Crew › Follow a plan, and paste ", h("b", { class: "mono" }, code), " ", copyBtn(code), ". The first time, it signs you in with your email."));
  let p = null;
  try {
    if (me) {
      const peek = await api("GET", `/plans/peek?code=${encodeURIComponent(code)}`);
      const n = (x) => (x.n || 0) + (x.cards || []).length + Object.values(x.sn || {}).reduce((a, v) => a + v, 0);
      p = { name: peek.name, ownerName: peek.ownerName, line: peek.line, followers: peek.followers, deck: peek.doc.deck, audience: peek.audience,
            units: peek.doc.units.map((x) => ({ name: x.name, opens: x.opens, due: x.due, n: n(x) })) };
    } else p = await api("GET", `/plans/public?code=${encodeURIComponent(code)}`);
  } catch { p = null; }
  if (!p) {
    page(h("h1", {}, "No plan with that code"), h("p", { class: "muted" }, "Check the code with whoever sent it. A plan for one squad only opens for its members."),
      me ? null : h("p", { class: "muted small" }, link(`/sign-in?next=${encodeURIComponent(`/p/${code}`)}`, "Sign in"), " if it's your squad's."));
    return;
  }
  const cal = p.audience === "squad" ? null : calMenu(code);
  page(...planIntro(p),
    cal ? h("div", { class: "phone-only" }, cal) : null,
    emailMe(`/p/${code}`),
    h("h2", {}, "Follow it in Anki"), steps(p.deck),
    cal ? h("div", { class: "wide-only" }, calMenu(code)) : null,
    me ? null : h("p", { class: "muted small" }, "Each morning, that day's cards open in your deck."));
}

/** 3.5.0: /i/CODE, a friend's invite. A one-time invite (10) makes you crew
 *  at once; a friend code (6) adds them, and they add you back. */
async function invitePage(code) {
  let inv = null;
  try { inv = await api("GET", `/invites/${encodeURIComponent(code)}`); } catch (err) { inv = err.status === 429 ? "slow" : null; }
  if (!inv || inv === "slow") {
    page(h("h1", {}, inv ? "Too many tries" : "No invite with that code"),
      h("p", { class: "muted" }, inv ? "Try again in an hour." : "Check the link with whoever sent it."),
      h("p", { class: "muted small" }, h("a", { href: "/" }, "What's Due Crew?")));
    return;
  }
  // a one-time invite, first use within 14 days: crew at once. Used or old,
  // it still adds, and the one who sent it adds back
  const once = inv.kind === "invite" && inv.state === "ok";
  const head = h("div", { class: "invwho" }, inv.emoji ? h("span", { class: "em" }, inv.emoji) : null,
    h("h1", {}, `${inv.name} invited you to study together`));
  if (me) {
    const out = h("p", { class: "status", role: "status" });
    const btn = h("button", { onclick: async () => {
      btn.disabled = true;
      try {
        const r = inv.kind === "invite" ? await api("POST", `/invites/${code}/redeem`) : await api("POST", `/codes/${code}/add`);
        out.textContent = r.mutual ? `You and ${r.name} are crew.` : r.knocked === false ? `${r.name} isn't in your crew now.`
          : `Added ${r.name}. You're crew once they add you back.`;
        btn.hidden = true;
      } catch (err) {
        btn.disabled = false;
        out.className = "status bad";
        out.textContent = err.status === 400 ? "That's your own invite." : err.status === 409 ? `${inv.name} is already in your crew.`
          : "That didn't work. Try again.";
      }
    } }, `Add ${inv.name}`);
    page(head, h("div", { class: "row" }, btn, link("/home", "Home", "quiet")), out);
    return;
  }
  const copyBtn = (text) => h("button", { class: "quiet", onclick: (e) => copy(text, e.target) }, "Copy");
  const shown = code.length === 10 ? `${code.slice(0, 5)} ${code.slice(5)}` : code;
  page(head,
    emailMe(`/i/${code}`),
    h("ol", { class: "steps wide-only" },
      h("li", {}, h("b", {}, "Add Due Crew to Anki. "), "Tools › Add-ons › Get Add-ons, paste ", h("b", { class: "mono" }, "2035408484"), " ",
        copyBtn("2035408484"), ", then restart Anki.", h("br"),
        h("span", { class: "muted small" }, "No Anki yet? ", h("a", { href: "https://apps.ankiweb.net" }, "Get it free"))),
      h("li", {}, h("b", {}, "Start with your email. "), "On Anki's Decks screen. We'll email you a code."),
      h("li", {}, h("b", {}, `Paste ${inv.name}'s code `), h("b", { class: "mono" }, shown), " ", copyBtn(code),
        once ? " on the welcome screen, and you're crew." : ` on the welcome screen. You're crew once ${inv.name} adds you back.`)),
    h("p", { class: "muted small" }, "Free · your studying goes only to people you add · ", h("a", { href: "/" }, "What's Due Crew?")));
}

async function account() {
  const out = async (all) => {
    try { await api("POST", all ? "/auth/signout-all" : "/auth/signout"); } catch { return; }
    me = null; wearAccent("green"); renderNav(); go("/sign-in");  // the next person here starts green
  };
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
  const planDays = (doc) => { const p = doc.pace?.days; return Array.isArray(p) && p.length === 7 && p.some(Boolean) ? p.map((x) => (x ? 1 : 0)) : [1, 1, 1, 1, 1, 1, 1]; };
  const weight = (doc, sched, d, sh) => (phase(doc, d, sh) !== "build" ? 0 : ((sched?.days || planDays(doc))[(parseIso(d).getUTCDay() + 6) % 7] || 0));
  function win(doc, u, sh) {
    let last = u.due;
    if (!last) { const later = units(doc).map((x) => x.opens).filter((o) => o > u.opens).sort(); last = later.length ? addDays(later[0], -1) : u.opens; }
    if (last < u.opens) last = u.opens;
    return [addDays(u.opens, sh), addDays(last, sh)];
  }
  function quota(doc, u, sched, total, d) {
    const sh = shift(doc, sched); const [a, b] = win(doc, u, sh);
    if (d < a || total <= 0) return 0;
    if (!sched) { if (!u.even) return total; sched = { days: planDays(doc) }; }  // an even split: the plan's own days
    let whole = 0; let upto = 0;
    for (let x = a; x <= b; x = addDays(x, 1)) { const w = weight(doc, sched, x, sh); whole += w; if (x <= d) upto += w; }
    if (whole) return Math.min(total, Math.ceil((total * upto) / whole));
    // no study day in the window: all of it on my first study day after it
    let next = b;
    for (let i = 1; i <= 60; i++) { const x = addDays(b, i); if (weight(doc, sched, x, sh)) { next = x; break; } }
    return d >= next ? total : 0;
  }
  return { units, start, shift, win, quota, phase, monday, diff, weight, planDays };
})();

// ---- 3.2: home, my log, the admin's counts ----

const squares = (days, mon) => h("span", { class: "sqs" }, [0, 1, 2, 3, 4, 5, 6].map((i) => {
  const d = addDays(mon, i); const v = days?.[d];
  return h("i", { class: v?.studied || v?.reviews ? "on" : d > today() ? "later" : "", title: pretty(d) });
}));

// ---- 3.3: the board, as the add-on draws it (due_crew/board.py) ----

const Board = (() => {
  const MEDALS = ["🥇", "🥈", "🥉"];
  // 3.4 review, T3: headings as words (the medals keep the emoji)
  const HEADS = [["reviews", "Reviews"], ["time", "Time"], ["retention", "Retention"], ["streak", "Streak"]];
  const SQUAD_HEADS = [...HEADS, ["week", "7 days"]];
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
    return { reviews: sum("reviews"), time: sum("studyTimeMs"), retention: ret, streak: ([...found].reverse().find((d) => "streak" in d) || {}).streak ?? null, new: sum("newCards") };
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
  /** board.py _away_text: when they're back, from a day flagged away. */
  function awayText(awayTo, today) {
    if (!awayTo) return "away";
    const back = addDays(awayTo, 1);
    if (back <= today) return "away";
    if (back === addDays(today, 1)) return "back tomorrow";
    const d = parseIso(back);
    return `back ${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}`;
  }
  /** A day's doc, with the away spell flagged on the days inside it, as the
   *  add-on reads a week (shapes._week_days). */
  function dayOf(w, l) {
    const d = (w.days || {})[l];
    if (w.awayFrom && w.awayTo && w.awayFrom <= l && l <= w.awayTo) return { ...(d || {}), away: true, awayTo: w.awayTo };
    return d;
  }
  /** room_model: a room counts until its last round ends. */
  function roomLive(room) {
    if (!room?.start) return false;
    const end = Date.parse(room.start) + (room.rounds * room.round + Math.max(0, room.rounds - 1) * (room.brk || 0)) * 60000;
    return end > Date.now();
  }
  /** rows for Today or Week, as board.build_rows: [ranked and show-up, the rest]. */
  function rows(people, period, sort, today) {
    const yest = addDays(today, -1), tomorrow = addDays(today, 1);
    const mon = Sched.monday(today);
    const wk = []; for (let x = mon; x <= today; x = addDays(x, 1)) wk.push(x);
    const last7 = []; for (let i = 0; i < 7; i++) last7.push(addDays(today, -i));
    const fresh = [], notyet = [], stale = [], quiet = [], paused = [];
    for (const p of people) {
      const w = p.week || {};
      const host = w.room && roomLive(w.room) ? people.find((x) => x.uid === w.room.host) : null;
      const r = { p, you: p.you, paused: !!w.paused, last: p.updatedAt || "", reviews: null, time: null, retention: null, streak: null, new: null,
        stale: false, quiet: false, notyet: false, status: "", away: "", exam: w.paused ? "" : examText(w.examDate, today),
        live: !w.paused && !!(w.liveUntil && Date.parse(w.liveUntil) > Date.now()),
        room: !w.paused && w.room && roomLive(w.room) ? (host ? `${(host.name || "?").split(" ")[0]}’s room` : "A study room") : "",
        recap: !w.paused && w.recap && w.recap.day === today ? w.recap : null,
        days7: last7.filter((l) => showed(dayOf(w, l))).length, daysWk: wk.filter((l) => showed(dayOf(w, l))).length, showup: false };
      if (r.paused) { paused.push(r); continue; }
      const flags = (d) => { r.status = d.status || ""; r.away = d.away ? awayText(d.awayTo, today) : ""; };
      if (period === "week") {
        const agg = weekAgg(w.days || {}, wk);
        if (!agg) {
          if (r.you || r.days7) { r.showup = !!r.days7; fresh.push(r); } else { r.quiet = true; quiet.push(r); }
          continue;
        }
        if (!r.daysWk) { r.notyet = true; notyet.push(r); continue; }  // a week of zeros: nothing to rank
        Object.assign(r, agg);
        r.showup = !!r.days7 && [r.reviews, r.time, r.retention, r.streak].every((v) => v === null);
        fresh.push(r);
      } else {
        // a friend whose day rolled over ahead of mine writes my "tomorrow"
        const t = dayOf(w, tomorrow) || dayOf(w, today), y = dayOf(w, yest);
        if (t && !showed(t)) { flags(t); r.notyet = !r.away; notyet.push(r); }  // synced, nothing studied yet
        else if (t) { Object.assign(r, metrics(t)); flags(t); r.showup = [r.reviews, r.time, r.retention, r.streak].every((v) => v === null); fresh.push(r); }
        else if (y && !r.you) { Object.assign(r, metrics(y)); flags(y); r.stale = true; stale.push(r); }
        else if (r.you) fresh.push(r);
        else { r.quiet = true; quiet.push(r); }
      }
    }
    const key = { reviews: "reviews", time: "time", retention: "retention", streak: "streak" }[sort] || "reviews";
    const val = (r) => (r[key] ?? -1);
    const byLast = (a, b) => (b.last || "").localeCompare(a.last || "");
    fresh.sort((a, b) => val(b) - val(a));
    stale.sort((a, b) => val(b) - val(a));
    return [fresh, [...notyet.sort(byLast), ...stale, ...quiet.sort(byLast), ...paused]];
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

  /** board.plan_target: a status that starts with a number is a plan. */
  const planTarget = (st) => { const m = /^\s*(\d{1,5})(?!\d)/.exec(st || ""); const n = m ? Number(m[1]) : 0; return n > 0 && n <= 20000 ? n : null; };

  function nameCell(r, period) {
    const p = r.p;
    const cell = h("td", { class: "nm" }, h("span", { class: "who" }, `${p.emoji ? p.emoji + " " : ""}${p.name || "?"}`));
    // board.py _chip: one chip, the most time-bound; green only for studying
    // now or a room, amber only for an exam
    if (!r.quiet) {
      if (r.room) cell.append(h("span", { class: "chip live" }, `in ${r.room}`));
      else if (r.live) cell.append(h("span", { class: "chip live" }, "studying now"));
      else if (r.exam) cell.append(h("span", { class: "chip exam" }, r.exam));
      else if (r.away) cell.append(h("span", { class: "chip" }, r.away === "away" ? "away" : `away · ${r.away}`));
      else if (r.recap) cell.append(h("span", { class: "chip", title: r.recap.name }, `week ${r.recap.n} done`));
    }
    if (r.paused) cell.append(h("span", { class: "ago faded it" }, " · on a break"));
    else if (r.quiet) { const [t] = ago(r.last); if (t) cell.append(h("span", { class: "ago faded" }, ` (${t})`)); }
    else if (r.notyet) {
      // a phone's reviews reach us only once their computer's Anki syncs:
      // say when we last heard, not that they haven't studied
      const [t] = ago(r.last);
      cell.append(h("span", { class: "ago faded" }, ` · nothing ${period === "week" ? "this week" : "yet"}${t && t !== "just now" ? ` as of ${t}` : ""}`));
    }
    else if (r.stale) cell.append(h("span", { class: "ago faded" }, " · yesterday"));
    else if (r.showup && r.daysWk) cell.append(h("span", { class: "ago faded" }, ` · ${r.daysWk} day${r.daysWk === 1 ? "" : "s"} this week`));
    if (r.status) {
      // 2.10: a status that starts with a number is a plan, ticked by the day's reviews
      const target = planTarget(r.status), done = r.reviews;
      const lead = target && Number.isInteger(done) && !r.stale
        ? (done >= target ? "✓ " : h("span", {}, "📝 ", h("span", { class: "plan" }, h("i", { style: `width:${Math.min(100, Math.round((100 * done) / target))}%` })), `${done.toLocaleString()} · `))
        : null;
      cell.append(h("div", {}, h("span", { class: "bub", title: r.status }, lead, r.status)));
    }
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
      // T5: how many were new, on the Week tab
      const rv = r.reviews === null ? "—" : h("span", {}, r.reviews.toLocaleString(), period === "week" && r.new > 0 && r.reviews > 0 ? h("small", {}, r.new >= r.reviews ? "all new" : `${Math.min(r.new, r.reviews).toLocaleString()} new`) : null);
      const dash = r.paused || r.quiet || r.notyet;
      const cheer = r.you ? h("td") : h("td", { class: "chc" }, h("button", { class: "linkish cheer", title: "Send a cheer", onclick: (e) => cheerMenu(r.p.uid, e.currentTarget) }, "🎉"));
      return h("tr", { class: [r.you ? "you" : "", r.stale || r.quiet || r.paused || r.notyet ? "dim" : ""].join(" ").trim() },
        h("td", { class: "rk" }, rank), nameCell(r, period),
        h("td", { class: "n" }, dash ? "—" : rv), h("td", { class: "n" }, dash || r.time === null ? "—" : fmtTime(r.time)),
        h("td", { class: "n" }, dash || r.retention === null ? "—" : `${r.retention.toFixed(1)}%`),
        h("td", { class: "n" }, dash || r.streak === null ? "—" : String(r.streak)), cheer);
    };
    const body = [...fresh.map((r) => { if (r.showup) return tr(r, "✓"); n++; return tr(r, n <= 3 ? MEDALS[n - 1] : `#${n}`); }), ...dormant.map((r) => tr(r, "—"))];
    return h("div", { class: "scrollx" }, h("table", { class: "brdt" }, h("thead", {}, head), h("tbody", {}, body)));
  }

  /** show-up mode, as _presence_html: a square a day, Monday to today,
   *  nothing ranked; sorted by squares lit, then name. */
  function presence(people, today) {
    const mon = Sched.monday(today); const wk = []; for (let x = mon; x <= today; x = addDays(x, 1)) wk.push(x);
    const [fresh, dormant] = rows(people, "today", "reviews", today);
    const lit = (r) => wk.filter((l) => showed(dayOf(r.p.week || {}, l))).length;
    fresh.sort((a, b) => lit(b) - lit(a) || (a.p.name || "").toLowerCase().localeCompare((b.p.name || "").toLowerCase()));
    const todayN = fresh.filter((r) => showed(dayOf(r.p.week || {}, today) || dayOf(r.p.week || {}, addDays(today, 1)))).length;
    const note = (r) => r.paused ? h("span", { class: "ago faded it" }, " · on a break")
      : r.quiet ? (ago(r.last)[0] ? h("span", { class: "ago faded" }, ` (${ago(r.last)[0]})`) : null)
      : r.stale ? h("span", { class: "ago faded" }, " · yesterday")
      : r.away ? h("span", { class: "ago faded" }, ` ✈️ ${r.away}`) : null;
    return h("div", { class: "scrollx" }, h("table", { class: "brdt" },
      h("thead", {}, h("tr", {}, h("th", { class: "lt", colspan: 2 }, `${todayN} showed up today`), wk.map((l) => h("th", { class: l === today ? "sqh on" : "sqh" }, "MTWTFSS"[(parseIso(l).getUTCDay() + 6) % 7])))),
      h("tbody", {}, [...fresh, ...dormant].map((r) => h("tr", { class: [r.you ? "you" : "", r.paused || r.quiet || r.stale ? "dim" : ""].join(" ").trim() },
        h("td", { class: "rk" }), h("td", { class: "nm" }, h("span", { class: "who" }, `${r.p.emoji ? r.p.emoji + " " : ""}${r.p.name}`), note(r)),
        wk.map((l) => { const d = dayOf(r.p.week || {}, l); return h("td", { class: "sqc" }, h("i", { class: `sq${showed(d) ? " on" : d?.away ? " away" : ""}` })); }))))));
  }

  /** The Decks tab, as _decks_body: a group per deck I share, my bar and
   *  each crewmate's with the same deck. */
  function decks(me, crew, decksBy, today) {
    const mine = decksBy[me.uid] || [];
    if (!mine.length) return h("p", { class: "muted small" }, "No shared decks yet. In Anki: Settings › Shared decks. Matching decks pair up on their own.");
    const match = (a, b) => { const x = new Set(a.sig || []); return (b.sig || []).some((g) => x.has(g)); };
    const days = [today, addDays(today, 1)];
    const bar = (name, d, isMe) => {
      const total = Math.max(d.total || 0, 1); const pct = (v) => Math.min(100, Math.round((100 * (v || 0)) / total));
      const counts = `${(d.seen || 0).toLocaleString()} / ${(d.total || 0).toLocaleString()}${d.ret != null ? ` · ${Math.round(d.ret)}%` : ""}`;
      const tip = [`${(d.seen || 0).toLocaleString()} seen`, `${(d.mature || 0).toLocaleString()} mature`, d.open != null ? `${Number(d.open).toLocaleString()} unlocked` : null,
        `${(d.total || 0).toLocaleString()} total`, d.ret != null ? `${Number(d.ret).toFixed(1)}% retention, last 7 days` : null].filter(Boolean).join(" · ");
      return h("div", { class: `dr${isMe ? " me" : ""}`, title: tip },
        h("span", { class: "dn" }, name), h("span", { class: "dtrack" }, d.open != null ? h("i", { class: "fo", style: `left:${pct(d.seen)}%;width:${Math.max(0, pct(d.open) - pct(d.seen))}%` }) : null,
          h("i", { class: "fs", style: `width:${pct(d.seen)}%` }), h("i", { class: "fm", style: `width:${pct(d.mature)}%` })),
        h("span", { class: "n" }, h("span", {}, counts), d.today && days.includes(d.day) ? h("small", { class: "dd" }, `+${Number(d.today).toLocaleString()} today`) : null));
    };
    return h("div", {}, mine.map((d) => h("div", { class: "dg" }, h("b", { class: "dgh" }, d.name),
      bar(me.name || "You", d, true), crew.map((f) => { const od = (decksBy[f.uid] || []).find((x) => match(d, x)); return od ? bar(f.name, od, false) : null; }))),
      h("p", { class: "muted small dleg" }, "solid = mature · faded = seen · hatched = unlocked · % of each person’s own copy · hover for numbers"));
  }

  /** A squad board, as _squads_html: one squad at a time behind a
   *  switcher, plain ranks, no medals, no cheers; these aren't necessarily
   *  people you know. Synced today with nothing studied yet sits under the
   *  ranked, with dashes. */
  let squadsGot = null;  // {at, list, boards}: a sort redraws from these, not the network
  const isoWeek = (iso) => {
    const d = parseIso(iso); const dow = (d.getUTCDay() + 6) % 7; d.setUTCDate(d.getUTCDate() - dow + 3);
    const y = d.getUTCFullYear(); const first = new Date(Date.UTC(y, 0, 4));
    return `${y}-W${String(1 + Math.round(((d - first) / 86400000 - 3 + ((first.getUTCDay() + 6) % 7)) / 7)).padStart(2, "0")}`;
  };
  async function squads(showUp, crewUids, pendingUids, onSort, refresh) {
    const day = todayLocal(), yday = addDays(day, -1);
    if (!squadsGot || Date.now() - squadsGot.at > 60000) {
      const { squads: got } = await api("GET", "/squads/mine");
      squadsGot = { at: Date.now(), list: got, boards: await Promise.all(got.map((q) => api("GET", `/squads/${q.id}?wk=${isoWeek(day)}`).catch(() => null))) };
    }
    const list = squadsGot.list;
    const joinOrCreate = h("button", { class: "linkish add", onclick: () => { const box = document.querySelector(".rail .codebox input, .rail input"); if (box) { box.focus(); box.scrollIntoView({ block: "center" }); } } }, "+ join or create");
    if (!list.length) return h("div", {}, h("div", { class: "sqsw" }, joinOrCreate),
      h("p", { class: "muted small" }, "A private board for any group. Join with a code, or create one in Anki: Tools › Due Crew › Squads."));
    let cur = store("dc-squad");
    if (!list.some((q) => q.id === cur)) cur = list[0].id;
    const sq = squadsGot.boards[list.findIndex((q) => q.id === cur)];
    const sw = h("div", { class: "sqsw" }, list.map((q) => h("button", { class: `linkish${q.id === cur ? " on" : ""}`, onclick: () => { store("dc-squad", q.id); onSort(); } }, q.name)), joinOrCreate);
    if (!sq) return h("div", {}, sw, h("p", { class: "muted small" }, "Couldn’t load. Check your connection and Refresh."));
    const sort = store("dc-sort") || "reviews";
    const field = { reviews: "reviews", time: "studyTimeMs", retention: "accuracy", streak: "streak", week: "week" }[sort] || "reviews";
    const rows = sq.rows || [];
    const zero = (r) => r.reviews === 0 && !r.studyTimeMs;
    const live = rows.filter((r) => r.day === day && !zero(r));
    const waitingToday = rows.filter((r) => r.day === day && zero(r));
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
    const body = [...live, ...waitingToday, ...rest].map((r) => {
      const you = r.uid === me.uid, today = r.day === day, nyet = today && zero(r);
      const notes = [];
      if (!you) {
        if (crewUids.has(r.uid)) notes.push(h("span", { class: "ago faded" }, " · crew"));
        else if (pendingUids.has(r.uid)) notes.push(h("span", { class: "ago faded" }, " · waiting"));
      }
      if (!today) notes.push(h("span", { class: "ago faded" }, ` · ${r.day === yday ? "yesterday" : "quiet"}`));
      else if (nyet) notes.push(h("span", { class: "ago faded" }, " · nothing yet today"));
      const rank = !today ? "" : nyet ? "—" : showUp || numberless(r) ? "✓" : `#${++n}`;
      const wk7 = h("td", { class: "n" }, r.week != null ? `${r.week}/7` : "—");
      const cells = showUp ? [wk7] : nyet ? [h("td", { class: "n" }, "—"), h("td", { class: "n" }, "—"), h("td", { class: "n" }, "—"), h("td", { class: "n" }, "—"), wk7] : [
        h("td", { class: "n" }, r.reviews == null ? "—" : h("span", {}, r.reviews.toLocaleString(), r.newCards > 0 && r.reviews > 0 ? h("small", {}, r.newCards >= r.reviews ? "all new" : `${r.newCards.toLocaleString()} new`) : null)),
        h("td", { class: "n" }, r.studyTimeMs != null ? fmtTime(r.studyTimeMs) : "—"),
        h("td", { class: "n" }, r.accuracy != null ? `${r.accuracy.toFixed(1)}%` : "—"),
        h("td", { class: "n" }, r.streak != null ? String(r.streak) : "—"), wk7];
      return h("tr", { class: [you ? "you" : "", today && !nyet ? "" : "dim"].join(" ").trim() },
        h("td", { class: "rk" }, rank), h("td", { class: "nm" }, h("span", { class: "who" }, `${r.emoji ? r.emoji + " " : ""}${r.name}`), notes), cells);
    });
    // 3.6: the Squads tab's bingo card, as board.py bingo_card_html: the
    // grid small, how many stamped, what's closest to a line. The Worker
    // works it out with the add-on's own evaluate; never who stamped what.
    let bingo = null;
    if (sq.bingo && sq.bingoEv) {
      const ev = sq.bingoEv, CELLS = [0, 1, 2, 3, 5, 6, 7, 8];
      const cells = [0, 1, 2, 3, 4, 5, 6, 7, 8].map((c) => h("i", { class: c === 4 ? (ev.middle.done ? "on" : "m") : (ev.squares[CELLS.indexOf(c)]?.done ? "on" : "") }));
      const stamps = ev.squares.filter((q) => q.done).length + (ev.middle.done ? 1 : 0);
      const state = ev.lines >= 8 ? "the whole card" : ev.lines ? (ev.lines === 1 ? "BINGO" : `${ev.lines} lines`)
        : (ev.closest || []).length === 1 ? "one away from bingo" : `${(ev.closest || []).length} away from bingo`;
      bingo = h("div", { class: "bgcard" }, h("span", { class: "bgmini" }, cells),
        h("span", { class: "bgt" }, h("b", {}, "Squad bingo"), h("span", { class: "muted" }, `${stamps} of 9 · ${state}`)),
        h("span", { class: "muted small", title: ev.closest?.length ? `Closest line: ${ev.closest.join(", ")}` : "" }, "The whole card is in Anki"));
    }
    // the squad's own line, as the add-on's (its code lives only in Anki)
    const acts = [];
    if (sq.founder === me.uid) acts.push(h("button", { class: "linkish", onclick: async (e) => {
      e.target.disabled = true;
      try { await api("PATCH", `/squads/${sq.id}`, { open: sq.open === false }); squadsGot = null; refresh(); } catch { e.target.disabled = false; }
    } }, sq.open === false ? "Open" : "Lock"));
    const leave = h("button", { class: "linkish", onclick: async (e) => {
      if (e.target.dataset.sure !== "1") { e.target.dataset.sure = "1"; e.target.textContent = `Leave ${sq.name}? Click again`; return; }
      try { await api("DELETE", `/squads/${sq.id}/members/${me.uid}`); store("dc-squad", ""); squadsGot = null; refresh(); } catch { e.target.textContent = "Couldn’t leave. Try again."; }
    } }, "Leave");
    acts.push(leave);
    const foot = h("div", { class: "sqline" }, acts.flatMap((a, i) => (i ? [" · ", a] : [a])));
    if (!body.length) return h("div", {}, sw, bingo, h("p", { class: "muted small" }, "No one’s synced yet."), foot);
    return h("div", {}, sw, bingo, h("div", { class: "scrollx sqb" }, h("table", { class: "brdt" },
      h("thead", {}, h("tr", {}, h("th", { class: "sqt", colspan: 2 }, line), heads)), h("tbody", {}, body))), foot);
  }

  function shareText(people, today) {
    const me = people.find((p) => p.you); const d = (me?.week?.days || {})[today] || {};
    const bits = [d.reviews != null ? `${d.reviews.toLocaleString()} reviews` : null, d.studyTimeMs ? fmtTime(d.studyTimeMs) : null, d.accuracy != null ? `${d.accuracy.toFixed(1)}%` : null, d.streak ? `🔥 ${d.streak}` : null].filter(Boolean);
    return `Due Crew · ${pretty(today)}: ${bits.join(" · ") || "showed up"}`;
  }

  function shareWeek(people, today) {
    const me = people.find((p) => p.you); const mon = Sched.monday(today);
    const wk = []; for (let x = mon; x <= today; x = addDays(x, 1)) wk.push(x);
    const a = weekAgg(me?.week?.days || {}, wk) || {};
    const n = wk.filter((l) => showed((me?.week?.days || {})[l])).length;
    const bits = [a.reviews != null ? `${a.reviews.toLocaleString()} reviews` : null, a.time ? fmtTime(a.time) : null, `${n} of ${wk.length} days`].filter(Boolean);
    return `Due Crew · week of ${pretty(mon)}: ${bits.join(" · ")}`;
  }
  const forget = () => { squadsGot = null; };  // a page load or Refresh reads them again
  return { table, presence, decks, squads, shareText, shareWeek, ago, store, forget };
})();

const todayLocal = () => today();

async function home() {
  Board.forget();
  const [b, plansR, sett, logR] = await Promise.all([api("GET", "/board?keep=1&decks=1&feed=1"), api("GET", "/plans/mine"),
    api("GET", "/settings").catch(() => null), api("GET", "/log").catch(() => ({ days: {} }))]);
  const t = today();
  const mon = Sched.monday(t);
  const showUp = !!sett?.settings?.show_up;
  const people = [{ ...b.me, you: true }, ...b.friends.filter((f) => f.mutual)];
  const crew = b.friends.filter((f) => f.mutual);
  const waiting = b.friends.filter((f) => !f.mutual);
  // board.py _head: the add-on's tabs, Plans included
  const tabs = showUp ? [["today", "Crew"], ["decks", "Decks"], ["squads", "Squads"], ["plans", "Plans"]] : [["today", "Today"], ["week", "Week"], ["decks", "Decks"], ["squads", "Squads"], ["plans", "Plans"]];
  let tab = Board.store("dc-tab") || "today";
  if (!tabs.some(([k]) => k === tab)) tab = "today";
  const pills = h("span", { class: "pills" });
  const panel = h("div");
  const fetched = Date.now();
  const updated = h("span", { class: "muted" });
  async function draw() {
    if (typeof drawFoot === "function") drawFoot();
    pills.replaceChildren(...tabs.map(([k, l]) => h("button", { class: tab === k ? "on" : "", onclick: () => { tab = k; Board.store("dc-tab", k); draw(); } }, l)));
    const mins = Math.floor((Date.now() - fetched) / 60000);
    updated.textContent = mins < 1 ? "Updated just now" : `Updated ${mins}m ago`;
    if (tab === "decks") return panel.replaceChildren(Board.decks(b.me, crew, b.decks || {}, t));
    if (tab === "squads") { panel.replaceChildren(h("p", { class: "muted small" }, "Loading…")); return panel.replaceChildren(await Board.squads(showUp, new Set(crew.map((f) => f.uid)), new Set(waiting.map((f) => f.uid)), draw, draw)); }
    if (tab === "plans") return panel.replaceChildren(plansTab());
    panel.replaceChildren(...[showUp ? Board.presence(people, t) : Board.table(people, tab, t, draw), crew.length ? null : solo()].filter(Boolean));
  }
  // board.py C5: until a friend adds me back, the invite is the board
  function solo() {
    const wait = !waiting.length ? "They show up here once they add you back." : waiting.length <= 2
      ? `Waiting for ${waiting.map((f) => f.name).join(" and ")} to add you back.` : `Waiting for ${waiting.length} people to add you back.`;
    return h("div", { class: "solo" }, h("b", {}, "Bring your crew"), h("span", { class: "muted" }, wait),
      h("div", { class: "row" }, b.me.code ? h("span", { class: "mono codepill" }, spaced(b.me.code)) : null,
        b.me.code ? h("button", { onclick: (e) => copyInvite(b.me.code, e.target) }, "Copy invite") : null,
        h("button", { class: "linkish", onclick: () => { const i = document.getElementById("anycode"); if (i) { i.focus(); i.scrollIntoView({ block: "center" }); } } }, "Got a code?")));
  }
  // 3.5.0's Plans tab, as far as the site can show it: each plan I follow,
  // on track or behind; the day-by-day lives on its page and in Anki
  function plansTab() {
    if (!followed.length) return h("div", { class: "solo" }, h("b", {}, "Following no plans"),
      h("span", { class: "muted" }, "A plan opens a deck's cards on their days. Paste a plan's code in Got a code?, find one in the library, or make one in Anki: Tools › Due Crew › Make a plan from a deck."),
      h("div", { class: "row" }, link("/library", "The library ›"), link("/plans", "Your plans ›")));
    return h("div", { class: "ptab" }, followed.map((p) => h("div", { class: "pcard" }, h("div", { class: "row", style: "justify-content:space-between" },
      h("b", {}, link(`/plans/${p.id}`, p.name)), h("small", { class: "muted" }, p.ownerName ? `${p.ownerName}’s` : "")), onTrack(p, true))),
      h("p", { class: "muted small" }, "Today’s cards open in Anki each morning. ", link("/plans", "All plans ›")));
  }
  // board.py's footer: Crew ▾ and who I'm waiting on; Refresh as a quiet icon
  const footLeft = h("span", { class: "fl" });
  function drawFoot() {
    const items = [["Friends…", () => { const i = document.getElementById("anycode"); if (i) { i.focus(); i.scrollIntoView({ block: "center" }); } }]];
    if (tab === "today" && !showUp) items.push(["Share today", () => share(Board.shareText(people, t))]);
    if (tab === "week" || (showUp && tab === "today")) items.push(["Share the week", () => share(Board.shareWeek(people, t))]);
    if (tab === "decks") items.push(["Shared decks…", () => { crewBtn.textContent = "In Anki: Settings › Shared decks"; setTimeout(() => { crewBtn.textContent = "Crew ▾"; }, 2400); }]);
    const crewBtn = h("button", { class: "linkish", "aria-haspopup": "menu", onclick: (e) => {
      document.querySelectorAll(".crew-pop").forEach((x) => x.remove());
      const pop = h("div", { class: "cheer-pop crew-pop", role: "menu" }, items.map(([l, go]) => h("button", { class: "linkish", role: "menuitem", onclick: () => { pop.remove(); go(); } }, l)));
      e.currentTarget.after(pop);
      setTimeout(() => document.addEventListener("click", function off(ev) { if (!pop.contains(ev.target)) { pop.remove(); document.removeEventListener("click", off); } }), 0);
    } }, "Crew ▾");
    footLeft.replaceChildren(crewBtn, waiting.length ? h("button", { class: "pillw", title: `Waiting for ${waiting.map((f) => f.name).join(", ")} to add you back`,
      onclick: () => { const i = document.getElementById("anycode"); if (i) i.scrollIntoView({ block: "center" }); } }, `${waiting.length} waiting`) : null);
  }
  const share = async (text) => {
    try { await navigator.clipboard.writeText(text); updated.textContent = "Copied"; } catch { updated.textContent = text; }
    setTimeout(() => { updated.textContent = "Updated just now"; }, 1800);
  };
  const followed = plansR.plans.filter((p) => p.following);
  await draw();
  const my = b.me.week?.days || {};
  const studied = Object.entries(my).filter(([d, v]) => d >= mon && (v.studied || v.reviews)).length;
  const minutes = Object.entries(my).filter(([d]) => d >= mon).reduce((n, [, v]) => n + (v.studyTimeMs || 0), 0) / 60000;
  // 3.4 review, H1 / 3.5, H: my code to give, and any code I was sent, in the rail
  const friends = h("section", { class: "panel" }, h("h4", {}, "Friends"),
    h("div", { class: "row" }, h("span", { class: "small" }, "Your code ", h("b", { class: "mono" }, b.me.code ? spaced(b.me.code) : "—")),
      b.me.code ? h("button", { class: "linkish", onclick: (e) => copyInvite(b.me.code, e.target) }, "Copy invite") : null),
    codeBox());
  page(todayStrip(followed, my[t]), h("div", { class: "wb" },
    h("div", { class: "stack" },
      h("section", { class: "brd" },
        h("div", { class: "top2" }, pills),
        panel,
        h("div", { class: "foot" }, footLeft,
          h("span", {}, updated, " ", h("button", { class: "linkish ico", title: "Refresh", "aria-label": "Refresh", onclick: () => route() }, "↻")))),
      h("section", { class: "panel" }, h("h4", {}, "Your year", h("span", { class: "muted" }, "only you see this · ", link("/log", "Log ›"))),
        yearHeat(logR.days || {}), h("small", { class: "muted" }, "One square a day, by minutes. Point at a day for its numbers."))),
    h("aside", { class: "rail" },
      h("section", { class: "panel" }, h("h4", {}, "This week", h("span", { class: "muted" }, "Mon–Sun")),
        h("div", { class: "row" }, squares(my, mon), h("span", { class: "muted small" }, `${studied} day${studied === 1 ? "" : "s"} · ${Math.floor(minutes / 60)}h ${Math.round(minutes % 60)}m`))),
      sinceYouWereHere(b, crew, t),
      followed.length ? h("section", { class: "panel" }, h("h4", {}, "Plans", link("/log", "Log")), followed.map((p) => onTrack(p, true))) : null,
      friends)));
}

/** 3.5, H: what today holds, from the plans I follow and my week so far. */
function todayStrip(followed, mine) {
  const t = today(), y = addDays(t, -1);
  let fresh = 0, behind = 0;
  const opening = [];
  let next = null;
  for (const p of followed.filter((x) => !x.following?.paused)) {
    const prog = p.following?.progress || {};
    const sched = p.following?.sched || null;
    const total = (u) => prog[u.id]?.[2] || u.n || 0;
    const q = (u, d) => Sched.quota(p.doc, u, sched, total(u), d);
    const us = Sched.units(p.doc).filter((u) => !(p.following?.skipped || []).includes(u.id));
    for (const u of us) {
      const n = q(u, t) - q(u, y);
      if (n > 0) { fresh += n; opening.push([p, u]); }
    }
    if (Object.keys(prog).length) {
      const seen = Object.values(prog).reduce((n, x) => n + x[1], 0);
      behind += Math.max(0, us.reduce((n, u) => n + q(u, y), 0) - seen);
    }
    for (const ev of p.doc.events || []) if (ev.day >= t && (!next || ev.day < next.ev.day)) next = { ev, p };
  }
  const card = (cls, label, big, ...rest) => h("div", { class: `ts ${cls}` }, h("small", {}, label), h("b", {}, big), ...rest);
  const cards = [];
  if (followed.length) {
    cards.push(fresh ? card("on", "Opens today", `${fresh.toLocaleString()} new`,
      h("span", {}, link(`/plans/${opening[0][0].id}`, opening[0][0].name), ` · ${opening.slice(0, 3).map(([, u]) => u.name).join(", ")}${opening.length > 3 ? "…" : ""}`),
      h("small", { class: "muted" }, "Your Anki opens them in the morning"))
      : card("", "Opens today", "Nothing new", h("small", { class: "muted" }, "A day for reviews")));
  }
  if (behind) cards.push(card("", "From earlier dates", behind.toLocaleString(), h("span", {}, "new cards waiting"), h("small", { class: "muted" }, "In Anki: Plan ▾ › Catch up")));
  if (next) {
    const preps = followed.some((p) => Sched.units(p.doc).some((u) => u.for === next.ev.id && opening.some(([, o]) => o.id === u.id)));
    cards.push(card("", "Next", next.ev.name, h("span", {}, `${next.ev.day === t ? "Today" : pretty(next.ev.day)}${preps ? " · today preps for it" : ""}`),
      h("small", { class: "muted" }, next.p.name)));
  }
  const m = mine || {};
  cards.push(card("", "So far today", (m.reviews || 0).toLocaleString(),
    h("span", {}, `reviews · ${Math.round((m.studyTimeMs || 0) / 60000)}m · ${(m.newCards || 0).toLocaleString()} new`),
    h("small", { class: "muted" }, "As of your last sync")));
  return h("div", { class: "tstrip" }, cards);
}

/** 3.5, H: since I was last here (this browser): who added me back, notes on
 *  my plans' days, their authors' changes. Cheers waiting and a crewmate's
 *  exam in the next two weeks show whenever they're true. */
function sinceYouWereHere(b, crew, t) {
  let prev = null;
  try {
    prev = sessionStorage.getItem("dc-since");
    if (!prev) { prev = localStorage.getItem("dc-seen") || ""; sessionStorage.setItem("dc-since", prev); localStorage.setItem("dc-seen", new Date().toISOString()); }
  } catch { prev = ""; }
  const items = (b.feed || []);
  const fresh = prev ? items.filter((x) => x.at > prev) : items;
  const older = items.filter((x) => !fresh.includes(x));
  const when = (iso) => { const d = new Date(iso); return `${DAYS[d.getDay()]} ${d.getHours() % 12 || 12}:${String(d.getMinutes()).padStart(2, "0")} ${d.getHours() < 12 ? "am" : "pm"}`; };
  const who = (x) => `${x.emoji ? `${x.emoji} ` : ""}${x.name}`;
  const row = (icon, main, sub) => h("div", { class: "fi" }, h("span", { class: "ic" }, icon), h("div", {}, h("span", {}, main), sub ? h("small", { class: "muted" }, sub) : null));
  const item = (x) => x.kind === "back" ? row("🤝", [h("b", {}, who(x)), " added you back"], "Now in your crew")
    : x.kind === "note" ? row("✎", [h("b", {}, x.name), ` on ${pretty(x.day)}, `, link(`/plans/${x.plan}`, x.planName), `: ${x.text}`], "A note on a day")
    : row("↻", [h("b", {}, x.name), " changed ", link(`/plans/${x.plan}`, x.planName), `: ${x.summary}`], "Your Anki follows it next morning");
  const cheers = b.cheers.length ? row(b.cheers[0].emoji, [h("b", {}, b.cheers[0].name), " cheered", b.cheers[0].note ? `: ${b.cheers[0].note}` : ""],
    `${b.cheers.length === 1 ? "It waits" : `${b.cheers.length} cheers wait`} for your Anki screen`) : null;
  const exams = crew.map((f) => [f, f.week?.examDate]).filter(([, d]) => d && d >= t && d <= addDays(t, 14)).sort((a, c) => a[1].localeCompare(c[1]))
    .map(([f, d]) => {
      const box = h("div");
      const send = h("button", { class: "linkish", onclick: () => box.replaceChildren(luckForm(f, () => box.replaceChildren())) }, "Send good luck");
      return h("div", { class: "fi" }, h("span", { class: "ic" }, f.emoji || "🍀"),
        h("div", {}, h("span", {}, h("b", {}, f.name), `'s exam is ${d === t ? "today" : pretty(d)}`), send, box));
    });
  const earlier = h("div", { class: "stack", hidden: true }, older.map(item));
  const body = [cheers, ...fresh.map(item), ...exams].filter(Boolean);
  return h("section", { class: "panel feed" }, h("h4", {}, "Since you were here", prev ? h("span", { class: "muted" }, when(prev)) : null),
    body.length ? body : h("p", { class: "muted small" }, "Nothing new."),
    older.length ? [h("button", { class: "linkish", onclick: (e) => { earlier.hidden = !earlier.hidden; e.target.textContent = earlier.hidden ? "Earlier, the last two weeks" : "Hide earlier"; } }, "Earlier, the last two weeks"), earlier] : null);
}

/** A good-luck line for a crewmate's exam morning (the add-on's Good-luck card). */
function luckForm(f, done) {
  const line = h("input", { maxlength: 80, placeholder: `A line for ${f.name.split(" ")[0]}'s exam morning`, "aria-label": "Your line" });
  const status = h("span", { class: "status", role: "status" });
  const send = h("button", { class: "ghost", onclick: async () => {
    if (!line.value.trim()) return;
    send.disabled = true;
    try { await api("POST", `/cheers/${f.uid}`, { emoji: "🍀", note: line.value.trim(), luck: true }); status.textContent = "Sent. They see it when they open Anki that morning."; line.remove(); send.remove(); }
    catch { send.disabled = false; status.className = "status bad"; status.textContent = "That didn't send. Try again."; }
  } }, "Send");
  return h("div", { class: "copyform" }, line, send, h("button", { class: "linkish", onclick: done }, "Cancel"), status);
}

/** A year of my log, a square a day (Monday at the top), darker with more
 *  minutes; days before my log began are dashed. */
function yearHeat(days) {
  const t = today();
  const lastMon = Sched.monday(t);
  const first = addDays(lastMon, -52 * 7);
  const logged = Object.keys(days).sort();
  const start = logged[0] || t;
  const mins = Object.values(days).map((r) => r[0]).filter((m) => m > 0).sort((a, c) => a - c);
  const cut = [0.25, 0.5, 0.75].map((q) => mins[Math.floor(q * (mins.length - 1))] || 0);
  const level = (m) => (!m ? 0 : m <= cut[0] ? 1 : m <= cut[1] ? 2 : m <= cut[2] ? 3 : 4);
  const cells = [];
  const months = [];
  let lastLabel = -9;
  for (let w = 0; w < 53; w++) {
    const wd = addDays(first, w * 7);
    const d0 = parseIso(wd);
    if ((w === 0 || parseIso(addDays(wd, -7)).getUTCMonth() !== d0.getUTCMonth()) && (w === 0 || w - lastLabel >= 3) && w <= 50) {
      months.push(h("span", { style: `grid-column:${w + 1}` }, MONTHS[d0.getUTCMonth()]));
      lastLabel = w;
    }
    for (let k = 0; k < 7; k++) {
      const d = addDays(wd, k);
      if (d > t) { cells.push(h("i", { class: "fut" })); continue; }
      const r = days[d];
      const title = r ? `${pretty(d)}: ${r[0]} min, ${r[1].toLocaleString()} reviews` : `${pretty(d)}${d < start ? ", before your log" : ""}`;
      cells.push(h("i", { class: d < start ? "pre" : `l${level(r?.[0] || 0)}${d === t ? " now" : ""}`, title }));
    }
  }
  const wrap = h("div", { class: "heatwrap" }, h("div", { class: "heat" },
    h("div", { class: "hm" }, months), h("div", { class: "hd" }, h("span", {}, "Mon"), h("span", {}, "Wed"), h("span", {}, "Fri")),
    h("div", { class: "hg" }, cells)),
    h("div", { class: "hk" }, "Less ", [1, 2, 3, 4].map((l) => h("i", { class: `l${l}` })), " More", h("i", { class: "pre", style: "margin-left:12px" }), " before your log"));
  setTimeout(() => { wrap.scrollLeft = wrap.scrollWidth; }, 0);  // narrow: today's end shows first
  return wrap;
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
    gap > 0 ? `${gap.toLocaleString()} behind` : "on track";
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
  // 3.5, L: my history on it (a point a day, from when it began being kept)
  const hist = Object.entries(p.following?.hist || {}).sort(([a], [b]) => a.localeCompare(b));
  const first = [addDays(Sched.start(p.doc), sh), ...hist.map(([d]) => d)].sort()[0];
  const last = us.map((u) => Sched.win(p.doc, u, sh)[1]).sort().pop();
  const span = Math.max(1, Sched.diff(last, first));
  const step = Math.max(1, Math.ceil(span / 60));
  const pts = [];
  for (let i = 0; i <= span; i += step) {
    const d = addDays(first, i);
    pts.push([i, us.reduce((n, u) => n + Sched.quota(p.doc, u, sched, prog[u.id]?.[2] || 0, d), 0)]);
  }
  const seen = Object.values(prog).reduce((n, t) => n + t[1], 0);
  const top = Math.max(1, ...pts.map((x) => x[1]), seen, ...hist.map(([, v]) => v[0])) * 1.08;
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
  if (hist.length > 1) {
    const line = (k, cls) => s("polyline", { points: hist.map(([d, v]) => `${x(Sched.diff(d, first))},${y(v[k])}`).join(" "), class: cls });
    svg.append(line(0, "ln open"), line(1, "ln seen"));
  }
  const ti = Math.min(span, Math.max(0, Sched.diff(today(), first)));
  const dot = s("circle", { cx: x(ti), cy: y(seen), r: 4.5, class: "dot" });
  dot.append(s("title", {}, `You, ${pretty(today())}: ${seen.toLocaleString()} seen`));
  svg.append(dot, s("text", { x: x(ti) + 8, y: y(seen) + 4, class: "lab" }, `You ${seen.toLocaleString()}`));
  return h("div", {}, h("div", { class: "key" }, h("span", {}, h("i", { class: "k-you" }), "you"),
    hist.length > 1 ? [h("span", {}, h("i", { class: "k-seen" }), "seen"), h("span", {}, h("i", { class: "k-open" }), "opened for you")] : null,
    h("span", {}, h("i", { class: "k-plan" }), sched ? "your schedule" : "the plan's dates")), svg,
    h("small", { class: "muted" }, "A point a day from what your Anki shares (Plan ▾ › Share my progress)."));
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

/** 3.5, L: this week and last, day by day, as pairs of bars (last week grey). */
function weekPairs(days, metric, unit) {
  const W = 560; const H = 180; const L = 34; const R = 8; const T = 14; const B = 22;
  const mon = Sched.monday(today()), prev = addDays(mon, -7);
  const val = (d) => { const r = days[d]; if (!r) return 0; return metric === 3 ? r[3] ?? 0 : r[metric] || 0; };
  const pairs = [0, 1, 2, 3, 4, 5, 6].map((k) => [val(addDays(prev, k)), addDays(mon, k) <= today() ? val(addDays(mon, k)) : null]);
  const top = Math.max(1, ...pairs.flat().filter((v) => v !== null)) * 1.12;
  const y = (v) => T + (H - T - B) * (1 - v / top);
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img", "aria-label": `${unit}, this week and last` });
  for (let k = 0; k <= 3; k++) {
    const v = Math.round((top / 1.12) * (k / 3));
    svg.append(svgEl("line", { x1: L, x2: W - R, y1: y(v), y2: y(v), class: "grid" }), svgEl("text", { x: L - 6, y: y(v) + 4, class: "tick", "text-anchor": "end" }, v));
  }
  const slot = (W - L - R) / 7, bw = Math.max(6, (slot - 14) / 2);
  pairs.forEach(([a, c], k) => {
    const x0 = L + k * slot + 4;
    const bar = (v, x, cls, when) => { const r = svgEl("rect", { x, y: y(v), width: bw, height: Math.max(0, y(0) - y(v)), rx: 3, class: cls }); r.append(svgEl("title", {}, `${pretty(when)}: ${v} ${unit}`)); svg.append(r); };
    bar(a, x0, "barp", addDays(prev, k));
    if (c !== null) bar(c, x0 + bw + 3, "barm", addDays(mon, k));
    svg.append(svgEl("text", { x: L + k * slot + slot / 2, y: H - 6, class: "tick", "text-anchor": "middle" }, ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][k]));
  });
  return svg;
}

async function logPage() {
  const [log, plansR] = await Promise.all([api("GET", "/log"), api("GET", "/plans/mine")]);
  const days = log.days || {};
  const t = today();
  const mon = Sched.monday(t);
  const dow = (parseIso(t).getUTCDay() + 6) % 7;  // Monday 0
  const range = (a, b) => Object.entries(days).filter(([d]) => d >= a && d <= b);
  const sum = (rows, i) => rows.reduce((n, [, r]) => n + (r[i] || 0), 0);
  const ret = (rows) => { const g = rows.filter(([, r]) => r[3] !== null && r[1]); return g.length ? g.reduce((n, [, r]) => n + r[3] * r[1], 0) / g.reduce((n, [, r]) => n + r[1], 0) : null; };
  const week = range(mon, t);
  const lastSoFar = range(addDays(mon, -7), addDays(mon, dow - 7));
  const byDay = DAYS[parseIso(t).getUTCDay()];
  const hm = (m) => `${Math.floor(m / 60)}h ${String(Math.round(m % 60)).padStart(2, "0")}m`;
  const last30 = range(addDays(t, -29), t);
  const studied30 = last30.filter(([, r]) => r[0] || r[1]);
  const tile = (big, small, extra) => h("div", {}, h("b", {}, big), h("small", {}, small), extra ? h("small", { class: "muted" }, extra) : null);

  // this week and last, by a metric
  const metric = { i: 0, unit: "minutes" };
  const pairsBox = h("div");
  const pills = h("div", { class: "pills" });
  const pick = [["Minutes", 0, "minutes"], ["Reviews", 1, "reviews"], ["New", 2, "new cards"], ["Retention", 3, "% retention"]];
  const drawPairs = () => {
    pills.replaceChildren(...pick.map(([l, i, u]) => h("button", { class: metric.i === i ? "on" : "", onclick: () => { metric.i = i; metric.unit = u; drawPairs(); } }, l)));
    pairsBox.replaceChildren(weekPairs(days, metric.i, metric.unit),
      h("div", { class: "key" }, h("span", {}, h("i", { class: "k-prev" }), `${pretty(addDays(mon, -7))} – ${pretty(addDays(mon, -1))}`), h("span", {}, h("i", { class: "k-now" }), "This week")));
  };
  drawPairs();

  // by week, 12 weeks (3.2's chart), folded
  const weeks = h("div");
  const minutesPlan = plansR.plans.find((p) => p.following?.sched)?.following.sched.minutes || 0;
  const drawWeeks = () => {
    const vals = []; const labels = [];
    for (let w = 11; w >= 0; w--) {
      const m0 = addDays(mon, -7 * w);
      vals.push(Math.round(sum(range(m0, addDays(m0, 6)), 0) / 7));
      const d = parseIso(m0);
      labels.push(w % 3 === 0 || w === 11 ? `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}` : "");
    }
    weeks.replaceChildren(barChart(vals, labels, minutesPlan, "minutes a day"));
  };
  drawWeeks();

  // day by day, the last 30 days: by date only
  let newest = true, all = false;
  const table = h("div");
  const order = h("span", { class: "seg" });
  const drawTable = () => {
    order.replaceChildren(h("button", { class: newest ? "on" : "", onclick: () => { newest = true; drawTable(); } }, "Newest first"),
      h("button", { class: newest ? "" : "on", onclick: () => { newest = false; drawTable(); } }, "Oldest first"));
    const ds = []; for (let k = 0; k < 30; k++) ds.push(addDays(t, -k));
    if (!newest) ds.reverse();
    const shown = all ? ds : ds.slice(0, 10);
    table.replaceChildren(h("table", { class: "crew daytab" },
      h("thead", {}, h("tr", {}, h("th", { class: "nm" }, "Day"), ["Minutes", "Reviews", "New", "Retention"].map((x) => h("th", { class: "n" }, x)))),
      h("tbody", {}, shown.map((d) => {
        const r = days[d];
        return h("tr", { class: r ? "" : "off" }, h("td", { class: "nm" }, `${pretty(d)}${d === t ? " · today" : ""}`),
          r ? [h("td", { class: "n" }, r[0]), h("td", { class: "n" }, r[1].toLocaleString()), h("td", { class: "n" }, r[2].toLocaleString()), h("td", { class: "n" }, r[3] === null ? "—" : `${r[3].toFixed(1)}%`)]
            : [0, 1, 2, 3].map(() => h("td", { class: "n" }, "—")));
      }))),
    all ? null : h("button", { class: "linkish", onclick: () => { all = true; drawTable(); } }, "20 more days"));
  };
  drawTable();

  const csv = () => {
    const rows = Object.entries(days).sort(([a], [c]) => a.localeCompare(c)).map(([d, r]) => [d, ...r.map((x) => (x === null ? "" : x))].join(","));
    const url = URL.createObjectURL(new Blob([`date,minutes,reviews,new,retention\n${rows.join("\n")}\n`], { type: "text/csv" }));
    const a = h("a", { href: url, download: `due-crew-log-${t}.csv` });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  const logged = Object.keys(days).sort();
  const followed = plansR.plans.filter((p) => p.following);
  const wret = ret(week);
  const r30 = ret(studied30);
  page(
    h("div", { class: "row", style: "justify-content:space-between" }, h("h1", {}, "Your log"),
      logged.length ? h("button", { class: "ghost", onclick: csv }, "Export CSV") : null),
    h("p", { class: "muted" }, "Only you see this. It fills in from Anki's syncs."),
    h("div", { class: "tiles" },
      tile(`${week.filter(([, r]) => r[0] || r[1]).length} of 7`, "days this week"),
      tile(hm(sum(week, 0)), "studied", `last week by ${byDay}: ${hm(sum(lastSoFar, 0))}`),
      tile(sum(week, 1).toLocaleString(), "reviews", `by ${byDay}: ${sum(lastSoFar, 1).toLocaleString()}`),
      tile(sum(week, 2).toLocaleString(), "new cards", `by ${byDay}: ${sum(lastSoFar, 2).toLocaleString()}`),
      tile(wret === null ? "—" : `${wret.toFixed(1)}%`, "retention"),
      tile(`${studied30.length} of 30`, "days studied, last 30")),
    h("section", { class: "panel", style: "margin-top:14px" }, h("h4", {}, "The last year", h("span", { class: "muted" }, `${logged.length} day${logged.length === 1 ? "" : "s"} in your log`)),
      yearHeat(days), logged.length ? h("small", { class: "muted" }, `Your log starts ${pretty(logged[0])}, when Anki first sent it.`) : h("small", { class: "muted" }, "Nothing yet: Anki sends it with a full sync.")),
    h("div", { class: "agrid2", style: "margin-top:12px" },
      h("section", { class: "panel" }, h("h4", {}, "This week and last", pills), pairsBox),
      h("section", { class: "panel" }, h("h4", {}, "On days you studied", h("span", { class: "muted" }, "last 30 days")),
        studied30.length ? h("div", { class: "mini2" },
          tile(`${Math.round(sum(studied30, 0) / studied30.length)}m`, "a day"),
          tile(Math.round(sum(studied30, 1) / studied30.length).toLocaleString(), "reviews a day"),
          tile(Math.round(sum(studied30, 2) / studied30.length).toLocaleString(), "new cards a day"),
          tile(r30 === null ? "—" : `${r30.toFixed(1)}%`, "retention")) : h("p", { class: "muted small" }, "No study days yet."),
        h("small", { class: "muted" }, "Averages leave out days off, so a rest day doesn't pull them down."),
        h("details", {}, h("summary", { class: "small" }, "By week, 12 weeks"), weeks))),
    h("section", { class: "panel", style: "margin-top:12px" }, h("h4", {}, h("span", {}, "Day by day ", h("span", { class: "muted" }, "last 30 days")), order), table),
    followed.length ? h("h2", {}, "Plans") : null,
    followed.map((p) => h("section", { class: "panel", style: "margin-bottom:12px" }, h("h4", {}, link(`/plans/${p.id}`, p.name)), onTrack(p, false), onTrackChart(p))));
}

// ---- 3.5, X: the admin's page: counts, their history, the cutover, the bridge ----

const svgEl = (tag, attrs, text) => {
  const e = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
  if (text !== undefined) e.textContent = text;
  return e;
};

/** A small line of a count over time; days not kept yet are left out. */
function sparkline(values, w = 150, h = 34) {
  const pts = values.map((v, i) => [i, v]).filter(([, v]) => v !== null && v !== undefined);
  const svg = svgEl("svg", { viewBox: `0 0 ${w} ${h}`, class: "spark", role: "img", "aria-label": "over time" });
  if (pts.length < 2) return svg;
  const lo = Math.min(...pts.map((p) => p[1])), hi = Math.max(...pts.map((p) => p[1]));
  const x = (i) => 2 + ((w - 6) * i) / Math.max(1, values.length - 1);
  const y = (v) => h - 3 - ((h - 6) * (v - lo)) / Math.max(1, hi - lo);
  svg.append(svgEl("polyline", { points: pts.map(([i, v]) => `${x(i)},${y(v)}`).join(" "), class: "sl" }));
  const [li, lv] = pts[pts.length - 1];
  svg.append(svgEl("circle", { cx: x(li), cy: y(lv), r: 2.5, class: "sd" }));
  return svg;
}

/** Bars of labelled counts, one row each, to one scale. */
function hbars(rows, grey) {
  const top = Math.max(1, ...rows.map((r) => r[1]));
  return h("div", { class: "hbars" }, rows.flatMap(([label, n], i) => [h("span", {}, label),
    h("span", { class: "hb" }, h("i", { class: grey && grey(label, i) ? "g" : "", style: `width:${Math.round((100 * n) / top)}%` })),
    h("b", {}, n.toLocaleString())]));
}

const ago = (t) => { const m = Math.round((Date.now() / 1000 - t) / 60); return m < 1 ? "just now" : m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} days ago`; };

/** The admin's account lookup: one person at a time (never a list of
 *  everyone, never how anyone studies), with sign-in help, a note of mine
 *  and what I've done there (mock "Admin, grown up", A3, A5). */
function peoplePanel(nav) {
  const when = (t) => (t ? new Date(t * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "never");
  const seen = (t) => (t ? new Date(t * 1000).toLocaleString(undefined, { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }) : "not yet");
  const offset = (m) => (m === null || m === undefined ? "" : ` · UTC${m < 0 ? "−" : "+"}${Math.floor(Math.abs(m) / 60)}${Math.abs(m) % 60 ? `:${String(Math.abs(m) % 60).padStart(2, "0")}` : ""}`);
  const q = h("input", { type: "search", placeholder: "An email, a name, a friend code, a squad code or a uid", "aria-label": "Look up an account or a squad", style: "flex:1 1 220px" });
  const hits = h("div", { class: "hits" });
  const one = h("div");
  const status = h("p", { class: "muted small", role: "status" });
  const tile = (n, label) => h("div", {}, h("b", {}, String(n)), h("small", {}, label));
  async function open(uid) {
    one.replaceChildren(h("p", { class: "muted small" }, "Loading…"));
    let p;
    try { p = await api("GET", `/admin/people/${encodeURIComponent(uid)}`); } catch { one.replaceChildren(h("p", { class: "status bad" }, "Couldn't open that account.")); return; }
    const base = `/admin/people/${encodeURIComponent(p.uid)}`;
    const copyBtn = h("button", { class: "quiet", onclick: () => copy(p.uid, copyBtn) }, "Copy uid");
    const outStatus = h("span", { class: "muted small", role: "status" });
    const act = (label, method, path, done, cls = "quiet") => {
      const b = h("button", { class: cls, onclick: async () => {
        b.disabled = true; outStatus.textContent = "…";
        try { const r = await api(method, path); outStatus.textContent = done(r); setTimeout(() => open(p.uid), 1200); }
        catch (e) { outStatus.textContent = e.status === 502 ? "The mail didn't go. Try again." : "That didn't work."; b.disabled = false; }
      } }, label);
      return b;
    };

    // sign-in help: Due Crew has no passwords; these are its resets
    const lim = p.limits;
    const limLine = lim.codesHour || lim.codesDay || lim.failsDay
      ? `${lim.codesHour} code${lim.codesHour === 1 ? "" : "s"} this hour, ${lim.codesDay} today, ${lim.failsDay} wrong today`
      : "No codes asked for today.";
    const newEmail = h("input", { type: "email", placeholder: "their new address", "aria-label": "New email", style: "flex:1 1 200px" });
    const emailStatus = h("span", { class: "muted small", role: "status" });
    const emailBox = h("div", { class: "stack", hidden: true },
      h("div", { class: "row" }, newEmail, h("button", { onclick: async (e) => {
        e.target.disabled = true; emailStatus.textContent = "…";
        try { await api("PUT", `${base}/email`, { email: newEmail.value }); open(p.uid); }
        catch (err) {
          e.target.disabled = false;
          emailStatus.textContent = err.body?.error === "taken" ? "Another account has that address." : err.body?.error === "same" ? "That's their address now."
            : err.body?.error === "bad_email" ? "That isn't an email address." : "That didn't work.";
        }
      } }, "Move it"), emailStatus),
      h("small", { class: "muted" }, "Both addresses get a line. It moves the first time they sign in with the new one, within a week; until then nothing changes."));
    const help = h("section", { class: "box" }, h("h4", {}, "Sign-in help", h("small", { class: "muted" }, "no passwords: these are the resets")),
      h("div", { class: "stack" }, act("Email them a fresh code", "POST", `${base}/code`, () => "Sent. It works for 10 minutes.", ""),
        h("small", { class: "muted" }, "For someone at the code box whose code never came: a new one, past the limits. You never see it.")),
      h("div", { class: "sep" }, h("div", { class: "row", style: "justify-content:space-between" }, h("span", {}, "Limits"), h("span", { class: lim.codesHour >= 10 || lim.failsDay >= 20 ? "warn" : "muted" }, limLine)),
        act("Clear their sign-in limits", "POST", `${base}/limits`, () => "Cleared. They can ask for a code again.")),
      h("div", { class: "sep" },
        p.emailChange
          ? h("div", { class: "row", style: "justify-content:space-between" }, h("span", {}, "Moving to ", h("b", {}, p.emailChange.email), h("small", { class: "muted" }, ` · started ${when(p.emailChange.at)}`)),
            act("Stop", "DELETE", `${base}/email`, () => "Stopped."))
          : h("button", { class: "quiet", style: "justify-self:start", onclick: () => { emailBox.hidden = !emailBox.hidden; if (!emailBox.hidden) newEmail.focus(); } }, "Change their email…"),
        emailBox));

    // my note, and what's been done here
    const note = h("textarea", { rows: 4, maxlength: 2000, "aria-label": "Your note on this account", placeholder: "What you told them, what to check next time…" });
    note.value = p.note?.text || "";
    const noteStatus = h("small", { class: "muted", role: "status" }, p.note ? `Saved ${seen(p.note.at)}` : "Only you see it. It goes with the account.");
    let saved = note.value;
    note.addEventListener("blur", async () => {
      if (note.value === saved) return;
      try { await api("PUT", `${base}/note`, { text: note.value }); saved = note.value; noteStatus.textContent = "Saved."; }
      catch { noteStatus.textContent = "Couldn't save the note."; }
    });
    const notes = h("section", { class: "box" }, h("h4", {}, "Your note"), note, noteStatus);
    const done = h("section", { class: "box" }, h("h4", {}, "What's been done here"),
      p.actions.length ? h("div", { class: "alog" }, p.actions.map((a) => h("div", {}, h("span", {}, a.action, a.squadName ? h("span", { class: "muted" }, ` · ${a.squadName}`) : null), h("small", { class: "muted" }, seen(a.at)))))
        : h("p", { class: "muted small" }, "Nothing yet."));

    const confirmBox = h("div", { class: "confirm", hidden: true });
    const typed = h("input", { type: "email", placeholder: p.email, "aria-label": "Type their email to confirm", style: "width:100%" });
    const delBtn = h("button", { class: "danger", onclick: async () => {
      delBtn.disabled = true;
      try { await api("DELETE", base, { email: typed.value }); one.replaceChildren(h("p", { class: "status" }, `${p.name}'s account is deleted.`)); hits.replaceChildren(); }
      catch (e) { delBtn.disabled = false; outStatus.textContent = e.body?.error === "confirm" ? "That isn't their email." : "That didn't work."; }
    } }, "Delete");
    confirmBox.append(h("b", {}, `Delete ${p.name}'s account?`),
      h("span", {}, "Everything of theirs goes, as when they delete it themselves. It can't be undone, and they aren't told."),
      h("label", {}, h("span", {}, "Type ", h("b", {}, p.email), " to confirm"), typed),
      h("div", { class: "row" }, h("button", { class: "quiet", onclick: () => { confirmBox.hidden = true; } }, "Cancel"), delBtn));
    const list = (title, rows) => h("div", { class: "plist" }, h("span", { class: "lbl" }, title),
      rows.length ? rows : h("span", { class: "muted small" }, "None"));
    one.replaceChildren(h("div", { class: "person" },
      h("div", { class: "who" }, h("span", { class: "em" }, p.emoji || "🙂"),
        h("div", {}, h("b", {}, p.name), h("small", { class: "muted" }, ` · last seen ${seen(p.lastSeen)}`))),
      h("div", { class: "agrid2" },
        h("dl", { class: "kv" },
          h("dt", {}, "Email"), h("dd", {}, p.email),
          h("dt", {}, "uid"), h("dd", { class: "mono" }, p.uid),
          h("dt", {}, "Friend code"), h("dd", { class: "mono" }, p.code ? spaced(p.code) : "none"),
          h("dt", {}, "Joined"), h("dd", {}, when(p.joined)),
          h("dt", {}, "Add-on"), h("dd", {}, `${p.version || "not yet"}${offset(p.tz)}`),
          h("dt", {}, "Signed in on"), h("dd", {}, `${p.signedIn.computers} computer${p.signedIn.computers === 1 ? "" : "s"}, ${p.signedIn.browsers} browser${p.signedIn.browsers === 1 ? "" : "s"}`)),
        h("div", { class: "tiles" }, tile(p.crew.mutual, "crew, mutual"), tile(p.crew.addedNotBack, "added, not back"),
          tile(p.crew.addedThem, "added them, not back"), tile(p.squads.length, "squads"), tile(p.following.length, "plans followed"),
          tile(p.made.length, "plans made"), tile(p.crew.muted, "muted"))),
      h("div", { class: "agrid3" }, help, notes, done),
      h("div", { class: "agrid2" },
        list("Squads", p.squads.map((x) => h("div", {}, h("button", { class: "linkish", onclick: () => nav.squad(x.id) }, x.name),
          h("small", { class: "muted" }, `${x.members} member${x.members === 1 ? "" : "s"}${x.founder ? " · founder" : ""}`)))),
        list("Plans", [...p.made.map((x) => h("div", {}, h("span", {}, x.name, " ", h("span", { class: "madetag" }, "made")),
          h("small", { class: "muted" }, `${x.audience === "squad" ? "squad" : "code"} · ${x.followers} following${x.listed ? " · in the library" : ""}`))),
          ...p.following.map((x) => h("div", {}, h("span", {}, x.name), h("small", { class: "muted" }, `following · ${x.owner}'s${x.paused ? " · paused" : ""}${x.listed ? " · in the library" : ""}`)))])),
      h("div", { class: "row" },
        act("Sign out everywhere", "POST", `${base}/signout`, (r) => `Signed out of ${r.ended} place${r.ended === 1 ? "" : "s"}.`),
        copyBtn, h("span", { style: "flex:1" }),
        h("button", { class: "danger", onclick: () => { confirmBox.hidden = false; typed.focus(); } }, "Delete account…")),
      outStatus, confirmBox));
  }
  async function look() {
    const text = q.value.trim();
    one.replaceChildren();
    if (text.length < 3) { status.textContent = "At least 3 characters."; hits.replaceChildren(); return; }
    status.textContent = "Looking…";
    let r;
    try { r = await api("GET", `/admin/people?q=${encodeURIComponent(text)}`); } catch { status.textContent = "That didn't work."; return; }
    const n = r.people.length + (r.squad ? 1 : 0);
    status.textContent = n ? `${n} match${n === 1 ? "" : "es"}` : "No one found.";
    const sq = r.squad ? [h("button", { class: "hit", onclick: () => nav.squad(r.squad.id) },
      h("span", {}, h("b", {}, r.squad.name), h("small", { class: "muted" }, ` · squad · ${r.squad.members} member${r.squad.members === 1 ? "" : "s"}`)), h("small", { class: "muted" }, "Open ›"))] : [];
    hits.replaceChildren(...sq, ...r.people.map((x) => h("button", { class: "hit", onclick: (e) => {
      for (const b of hits.children) b.classList.toggle("on", b === e.currentTarget); open(x.uid);
    } }, h("span", {}, `${x.emoji ? x.emoji + " " : ""}`, h("b", {}, x.name), h("small", { class: "muted" }, ` · ${x.email} · joined ${when(x.joined)}`)),
      h("small", { class: "muted" }, x.version || ""))));
    if (r.people.length === 1 && !r.squad) { hits.firstChild.classList.add("on"); open(r.people[0].uid); }
    else if (r.squad && !r.people.length) nav.squad(r.squad.id);
  }
  q.addEventListener("keydown", (e) => { if (e.key === "Enter") look(); });
  const el = h("section", { class: "panel people" }, h("h4", {}, "Look up an account", h("span", { class: "muted" }, "one at a time")),
    h("div", { class: "row" }, q, h("button", { onclick: look }, "Look up")), status, hits, one);
  return { el, open: (uid) => { q.value = uid; hits.replaceChildren(); status.textContent = ""; open(uid); } };
}

/** One squad at a time, by its code or from an account (mock "Admin,
 *  grown up", A4): its members by name, and the founder's tools done from
 *  here. The founder gets an email for each. */
function squadPanel(nav) {
  const el = h("section", { class: "panel people" });
  const when = (t) => new Date(t * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
  const seen = (t) => new Date(t * 1000).toLocaleString(undefined, { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
  const q = h("input", { type: "search", placeholder: "A squad's code", "aria-label": "A squad's code", style: "flex:1 1 200px" });
  const status = h("p", { class: "muted small", role: "status" });
  const body = h("div");
  async function find() {
    status.textContent = "Looking…";
    try {
      const r = await api("GET", `/admin/people?q=${encodeURIComponent(q.value.trim())}`);
      if (r.squad) { status.textContent = ""; open(r.squad.id); } else status.textContent = "No squad has that code.";
    } catch { status.textContent = q.value.trim().length < 3 ? "That's not a squad code." : "That didn't work."; }
  }
  q.addEventListener("keydown", (e) => { if (e.key === "Enter") find(); });
  async function open(id) {
    body.replaceChildren(h("p", { class: "muted small" }, "Loading…"));
    let s;
    try { s = await api("GET", `/admin/squads/${encodeURIComponent(id)}`); } catch { body.replaceChildren(h("p", { class: "status bad" }, "Couldn't open that squad.")); return; }
    const base = `/admin/squads/${encodeURIComponent(s.id)}`;
    const out = h("span", { class: "muted small", role: "status" });
    const fail = (e) => (e.body?.error === "not_member" ? "They aren't in the squad." : e.body?.error === "confirm" ? "That isn't its name." : e.body?.error === "bad_name" ? "Give it a name, up to 24 characters." : "That didn't work.");
    const patch = async (b, btn) => {
      btn.disabled = true;
      try { await api("PATCH", base, b); open(s.id); } catch (e) { btn.disabled = false; out.textContent = fail(e); }
    };

    // a new code: asks once, shows the code once
    const codeBox = h("div", { class: "confirm", hidden: true },
      h("b", {}, `New code for ${s.name}?`),
      h("span", {}, "The old code stops working. Everyone in it stays; anyone with the old code can't join. The founder gets the new one by email."),
      h("div", { class: "row" }, h("button", { class: "quiet", onclick: () => { codeBox.hidden = true; } }, "Cancel"),
        h("button", { onclick: async (e) => {
          e.target.disabled = true;
          try {
            const r = await api("POST", `${base}/code`);
            codeBox.replaceChildren(h("span", { class: "bigcode" }, `${r.code.slice(0, 4)} ${r.code.slice(4)}`),
              h("small", { class: "muted" }, r.told ? `Shown once. ${s.founderName} has it by email too.` : "Shown once, and the email to the founder didn't go: send it yourself."));
          } catch (err) { e.target.disabled = false; out.textContent = fail(err); }
        } }, "Make a new code")));
    const nameIn = h("input", { value: s.name, maxlength: 24, "aria-label": "Squad name", style: "flex:1 1 200px" });
    const renameBox = h("div", { class: "row", hidden: true }, nameIn, h("button", { onclick: (e) => patch({ name: nameIn.value }, e.target) }, "Rename"));
    const founderSel = h("select", { "aria-label": "New founder" }, s.members.filter((m) => m.uid !== s.founder).map((m) => h("option", { value: m.uid }, m.name)));
    const founderBox = h("div", { class: "row", hidden: true }, founderSel, h("button", { onclick: (e) => patch({ founder: founderSel.value }, e.target) }, "Make founder"));
    const typed = h("input", { placeholder: s.name, "aria-label": "Type the squad's name to confirm", style: "width:100%" });
    const delBox = h("div", { class: "confirm", hidden: true }, h("b", {}, `Delete ${s.name}?`),
      h("span", {}, "The squad goes for everyone. Friendships stay. The founder is told. It can't be undone."),
      h("label", {}, h("span", {}, "Type ", h("b", {}, s.name), " to confirm"), typed),
      h("div", { class: "row" }, h("button", { class: "quiet", onclick: () => { delBox.hidden = true; } }, "Cancel"),
        h("button", { class: "danger", onclick: async (e) => {
          e.target.disabled = true;
          try { await api("DELETE", base, { name: typed.value }); body.replaceChildren(h("p", { class: "status" }, `${s.name} is deleted.`)); }
          catch (err) { e.target.disabled = false; out.textContent = fail(err); }
        } }, "Delete")));
    const shut = () => { for (const b of [codeBox, renameBox, founderBox, delBox]) b.hidden = true; };
    const toggle = (box, focus) => () => { const was = box.hidden; shut(); box.hidden = !was; if (!box.hidden && focus) focus.focus(); };

    const member = (m) => {
      const why = h("input", { placeholder: "Why (only the founder sees it; optional)", maxlength: 300, "aria-label": `Why remove ${m.name}`, style: "flex:1 1 200px" });
      const rm = h("div", { class: "confirm", hidden: true }, h("b", {}, `Remove ${m.name}?`),
        h("span", {}, "They leave the squad and can't rejoin with its code. The founder is told."), why,
        h("div", { class: "row" }, h("button", { class: "quiet", onclick: () => { rm.hidden = true; } }, "Cancel"),
          h("button", { class: "danger", onclick: async (e) => {
            e.target.disabled = true;
            try { await api("POST", `${base}/remove/${encodeURIComponent(m.uid)}`, { why: why.value }); open(s.id); }
            catch (err) { e.target.disabled = false; out.textContent = fail(err); }
          } }, "Remove")));
      return h("div", { class: "mrow" },
        h("span", {}, m.emoji ? `${m.emoji} ` : "", h("b", {}, m.name), h("small", { class: "muted" }, m.uid === s.founder ? " · founder" : ` · joined ${when(m.joined)}`)),
        h("span", { class: "acts" }, h("button", { class: "linkish", onclick: () => nav.person(m.uid) }, "Open"),
          m.uid === s.founder ? null : h("button", { class: "linkish warn", onclick: () => { rm.hidden = !rm.hidden; } }, "Remove…")),
        rm);
    };
    body.replaceChildren(h("div", { class: "person" },
      h("div", { class: "who" }, h("div", {}, h("b", {}, s.name), h("small", { class: "muted" }, ` · ${s.open ? "open to join" : "closed to new members"}${s.newCode ? " · has a new code" : ""}`))),
      h("dl", { class: "kv" },
        h("dt", {}, "Founder"), h("dd", {}, h("button", { class: "linkish", onclick: () => nav.person(s.founder) }, s.founderName)),
        h("dt", {}, "Made"), h("dd", {}, `${when(s.created)} · ${s.members.length} member${s.members.length === 1 ? "" : "s"}${s.removed ? ` · ${s.removed} removed` : ""}`)),
      h("div", { class: "row" },
        h("button", { class: "quiet", onclick: toggle(codeBox) }, "New code…"),
        h("button", { class: "quiet", onclick: (e) => patch({ open: !s.open }, e.target) }, s.open ? "Close joins" : "Open joins"),
        h("button", { class: "quiet", onclick: toggle(renameBox, nameIn) }, "Rename…"),
        s.members.length > 1 ? h("button", { class: "quiet", onclick: toggle(founderBox, founderSel) }, "Make founder…") : null,
        h("span", { style: "flex:1" }),
        h("button", { class: "danger", onclick: toggle(delBox, typed) }, "Delete squad…")),
      codeBox, renameBox, founderBox, delBox, out,
      h("div", { class: "agrid2" },
        h("div", { class: "plist" }, h("span", { class: "lbl" }, `Members · ${s.members.length}`), s.members.map(member)),
        h("div", { class: "plist" }, h("span", { class: "lbl" }, "What's been done here"),
          s.actions.length ? s.actions.map((a) => h("div", {}, h("span", {}, a.action, a.who ? h("span", { class: "muted" }, ` · ${a.who}`) : null), h("small", { class: "muted" }, seen(a.at))))
            : h("span", { class: "muted small" }, "Nothing yet.")))));
  }
  el.append(h("h4", {}, "A squad", h("span", { class: "muted" }, "by its code, or from an account")),
    h("div", { class: "row" }, q, h("button", { onclick: find }, "Find")), status, body);
  return { el, open };
}

/** Today's one list of what's waiting (A2): new feedback, email changes
 *  not yet finished, a bridge run that failed. */
function needsYou(s, show) {
  const row = (tag, text, label, go, warn) => h("div", { class: "nrow2" }, h("span", { class: `pill${warn ? " w" : ""}` }, tag), h("span", {}, text),
    h("button", { class: "linkish", onclick: go }, label));
  const rows = [];
  if (s.feedbackOpen) rows.push(row("Feedback", `${s.feedbackOpen} new`, "Open", () => show("inbox")));
  for (const c of s.emailChanges || []) rows.push(row("Email", [h("b", {}, c.name), " is moving to a new address (waiting for their first sign-in there)"], "Open", () => show("people", c.uid)));
  if (s.bridge?.error) rows.push(row("System", "The 2.x bridge's last run failed", "Look", () => show("system"), true));
  return h("section", { class: "panel" }, h("h4", {}, "Needs you", h("span", { class: "muted" }, "everything waiting, in one list")),
    rows.length ? h("div", { class: "nlist" }, rows) : h("p", { class: "muted small" }, "Nothing waiting."));
}

/** Everything done from this page, newest first, kept a year (A5). */
function auditPanel(nav) {
  const list = h("div", { class: "alog" });
  const more = h("button", { class: "quiet", hidden: true }, "Older");
  const seen = (t) => new Date(t * 1000).toLocaleString(undefined, { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
  async function load(before) {
    let r;
    try { r = await api("GET", `/admin/actions${before ? `?before=${before}` : ""}`); } catch { list.append(h("p", { class: "status bad" }, "Couldn't load the log.")); return; }
    if (!before && !r.actions.length) list.replaceChildren(h("p", { class: "muted small" }, "Nothing yet. Everything you do from this page shows here."));
    for (const a of r.actions) {
      list.append(h("div", {}, h("span", {}, a.action,
        a.uid ? [" · ", a.who === "a deleted account" ? h("span", { class: "muted" }, a.who) : h("button", { class: "linkish", onclick: () => nav.person(a.uid) }, a.who)] : null,
        a.squad ? [" · ", a.squadName === "a deleted squad" ? h("span", { class: "muted" }, a.squadName) : h("button", { class: "linkish", onclick: () => nav.squad(a.squad) }, a.squadName)] : null,
        a.detail ? h("span", { class: "muted" }, ` · ${a.detail}`) : null), h("small", { class: "muted" }, seen(a.at))));
    }
    more.hidden = !r.more;
    more.onclick = () => load(r.more);
  }
  load("");
  return h("section", { class: "panel" }, h("h4", {}, "Audit log", h("span", { class: "muted" }, "everything done from this page · kept a year")), list, more);
}

/** 3.6: squad bingo's pool, the admin's to tune. This week's card with how
 *  many squads have each square done; every square and middle (on or off)
 *  with its rule, last week's rate, and an editor. A card already drawn
 *  keeps what it was drawn with: an edit shows from the next week. */
const BINGO_FAMS = { early: "Early", spread: "Spread out", focus: "Focus", volume: "Bigger day", fresh: "New cards", often: "Showing up", clean: "Keeping up", wild: "Wildcard" };
const BINGO_DIFF = { e: "easy", m: "medium", h: "hard" };
const BINGO_SQUARE_TYPES = ["window", "minute", "sittings", "parts", "focus", "beat", "rel", "best", "newdays", "newdone", "days", "zero", "samehour"];
const BINGO_MIDDLE_TYPES = ["people", "sum", "day", "emoji", "joined", "free"];
const BINGO_GROUPS = { study: "studying together", crew: "Due Crew", free: "free", season: "a season" };

function bingoPanel() {
  const box = h("section", { class: "panel" }, h("h4", {}, "Squad bingo", h("span", { class: "muted" }, "loading…")));
  let data = null;
  const status = h("p", { class: "status", role: "status" });
  const errText = (e) => ({ bad_rule: "The rule's numbers don't fit its type.", bad_icon: "The icon must be one emoji.", bad_season: "A season needs from and to as MM-DD.",
    bad_goal: "The goal is a number, all, half, third or quarter.", bad_entry: "Something in it isn't allowed.", bad_title: "It needs a title.", bad_name: "It needs a name.", bad_detail: "Say exactly what counts.", kind: "That id is already the other kind." }[e] || "That didn't save.");
  // last week's rate for an entry: the share of playing squads it was done in
  const rateOf = (id) => {
    for (const c of data.cards) {
      if (!c.stats || !c.stats.squads) continue;
      const i = c.card.squares.findIndex((q) => q.id === id);
      if (i >= 0) return `${Math.round((100 * c.stats.squares[i].squads) / c.stats.squads)}% of ${c.stats.squads} squads (${c.wk})`;
      if (c.card.middle.id === id) return `${Math.round((100 * c.stats.middle) / c.stats.squads)}% of ${c.stats.squads} squads (${c.wk})`;
    }
    return "";
  };
  function editor(item, isNew) {
    const e = item.entry, sq = item.kind === "square";
    const f = {};
    const inp = (k, v, attrs = {}) => (f[k] = h("input", { value: v ?? "", ...attrs }));
    const sel = (k, opts, v) => (f[k] = h("select", {}, Object.entries(opts).map(([val, label]) => h("option", { value: val, selected: val === v }, label))));
    const id = isNew ? h("input", { placeholder: "short id: a-z 0-9", maxlength: 12, style: "width:9em" }) : null;
    const en = h("input", { type: "checkbox", checked: item.enabled });
    const params = h("textarea", { rows: 2, style: "width:100%;font-family:monospace", title: "Add \"row\": true for days in a row" }, JSON.stringify(e.params || {}));
    const row = (label, el) => h("label", { class: "brow" }, h("span", {}, label), el);
    const fields = [
      isNew ? row("Id", id) : null,
      row("Icon", inp("icon", e.icon, { style: "width:4em" })),
      row(sq ? "Title" : "Name", inp(sq ? "title" : "name", sq ? e.title : e.name, { maxlength: 28 })),
      row("On the square", inp("rule", e.rule, { maxlength: 48, style: "width:100%" })),
      row("Exactly", inp("detail", e.detail, { maxlength: 160, style: "width:100%" })),
      sq ? row("Family", sel("fam", BINGO_FAMS, e.fam)) : row("Kind", sel("group", BINGO_GROUPS, e.group)),
      sq ? row("Difficulty", sel("diff", BINGO_DIFF, e.diff)) : row("Goal", inp("goal", e.goal, { placeholder: "3, all, half, third, quarter", style: "width:12em" })),
      sq ? row("Team square", (f.team = h("input", { type: "checkbox", checked: e.team }))) : row("Unit", inp("unit", e.unit, { maxlength: 20, style: "width:10em" })),
      !sq ? row("Season", h("span", { class: "row" }, inp("sfrom", e.season?.from, { placeholder: "10-26", style: "width:6em" }), "to", inp("sto", e.season?.to, { placeholder: "11-01", style: "width:6em" }))) : null,
      row("Rule", sel("type", Object.fromEntries((sq ? BINGO_SQUARE_TYPES : BINGO_MIDDLE_TYPES).map((t) => [t, t])), e.type)),
      row("Numbers", params),
      row("On", en),
    ].filter(Boolean);
    const msg = h("span", { class: "muted small" });
    const save = h("button", { onclick: async () => {
      let p;
      try { p = JSON.parse(params.value || "{}"); } catch { msg.textContent = "Numbers must be JSON, like {\"days\": 3}."; return; }
      const entry = sq
        ? { fam: f.fam.value, diff: f.diff.value, icon: f.icon.value.trim(), title: f.title.value, rule: f.rule.value, detail: f.detail.value, type: f.type.value, params: p, team: f.team.checked }
        : { group: f.group.value, icon: f.icon.value.trim(), name: f.name.value, rule: f.rule.value, detail: f.detail.value, type: f.type.value, params: p,
            goal: /^\d+$/.test(f.goal.value.trim()) ? Number(f.goal.value.trim()) : f.goal.value.trim(), unit: f.unit.value,
            ...(f.group.value === "season" ? { season: { from: f.sfrom.value.trim(), to: f.sto.value.trim() } } : {}) };
      const key = isNew ? id.value.trim() : item.id;
      if (!/^[a-z0-9]{1,12}$/.test(key)) { msg.textContent = "The id is 1 to 12 of a-z and 0-9."; return; }
      save.disabled = true;
      try {
        await api("PUT", `/admin/bingo/${key}`, { kind: item.kind, entry, enabled: en.checked });
        status.className = "status"; status.textContent = "Saved. It shows from next week's card.";
        await load();
      } catch (err) { msg.textContent = errText(err.body?.error); save.disabled = false; }
    } }, "Save");
    return h("div", { class: "bedit" }, fields, h("div", { class: "row" }, save, h("button", { class: "quiet", onclick: () => draw() }, "Cancel"), msg));
  }
  function table(kind) {
    const items = data.pool.filter((p) => p.kind === kind);
    const order = kind === "square" ? Object.keys(BINGO_FAMS) : Object.keys(BINGO_GROUPS);
    items.sort((a, b) => order.indexOf(kind === "square" ? a.entry.fam : a.entry.group) - order.indexOf(kind === "square" ? b.entry.fam : b.entry.group)
      || (a.entry.diff || "").localeCompare(b.entry.diff || "") || a.id.localeCompare(b.id));
    const list = h("div", { class: "blist" });
    list.append(...items.map((item) => {
      const e = item.entry;
      const holder = h("div", { class: `bitem${item.enabled ? "" : " off"}` });
      const line = h("div", { class: "bline" },
        h("span", { class: "bic" }, e.icon),
        h("div", {}, h("b", {}, kind === "square" ? e.title : e.name), h("small", { class: "muted" }, ` ${e.rule}`),
          h("div", { class: "muted small" }, [kind === "square" ? `${BINGO_FAMS[e.fam]} · ${BINGO_DIFF[e.diff]}${e.team ? " · can be a team square" : ""}`
            : `${BINGO_GROUPS[e.group]} · goal ${e.goal}${e.season ? ` · ${e.season.from} to ${e.season.to}` : ""}`,
            `${e.type} ${JSON.stringify(e.params)}`, rateOf(item.id), item.enabled ? null : "off"].filter(Boolean).join(" · "))),
        h("button", { class: "linkish", onclick: () => holder.replaceChildren(editor(item, false)) }, "Edit"));
      holder.append(line);
      return holder;
    }));
    return list;
  }
  function draw() {
    const cur = data.cards.find((c) => c.wk === data.week);
    const st = cur?.stats;
    const cardView = cur ? h("div", { class: "bcard" }, [0, 1, 2, 3, 4, 5, 6, 7, 8].map((cell) => {
      if (cell === 4) return h("div", { class: "bcell mid" }, h("span", {}, cur.card.middle.icon), h("b", {}, cur.card.middle.name),
        h("small", {}, st && st.squads ? `${Math.round((100 * st.middle) / st.squads)}% unlocked` : cur.card.middle.rule));
      const i = [0, 1, 2, 3, null, 4, 5, 6, 7][cell], q = cur.card.squares[i];
      return h("div", { class: "bcell" }, h("span", {}, q.icon), h("b", {}, q.title),
        h("small", {}, [q.need !== 1 ? ({ half: "half of you", third: "a third of you", quarter: "a quarter of you" }[q.need] || `${q.need} of you`) : BINGO_DIFF[q.diff],
          st && st.squads ? `${Math.round((100 * st.squares[i].squads) / st.squads)}% done` : null].filter(Boolean).join(" · ")));
    })) : h("p", { class: "muted small" }, "No card yet this week.");
    const add = (kind) => h("button", { class: "quiet", onclick: (ev) => {
      const blank = kind === "square"
        ? { kind, enabled: true, entry: { fam: "wild", diff: "m", icon: "✨", title: "", rule: "", detail: "", type: "days", params: { days: 3 }, team: true } }
        : { kind, enabled: true, entry: { group: "crew", icon: "✨", name: "", rule: "", detail: "", type: "people", params: { key: "d" }, goal: 3, unit: "" } };
      ev.target.replaceWith(editor(blank, true));
    } }, kind === "square" ? "Add a square" : "Add a middle");
    box.replaceChildren(
      h("h4", {}, "Squad bingo", h("span", { class: "muted" }, st ? `${data.week} · ${st.players} playing in ${st.squads} squads · ${st.lines} with a line · ${st.whole} whole cards` : data.week)),
      cardView,
      h("small", { class: "muted" }, "Every squad plays this card. The counts are kept daily. Tune a square whose rate is far from its difficulty: easy ones should be done in most squads, hard ones in a few."),
      status,
      h("h3", {}, "Squares"), table("square"), add("square"),
      h("h3", {}, "The middle"), table("middle"), add("middle"),
      h("small", { class: "muted" }, "A card already drawn keeps what it was drawn with; an edit or a new entry shows from next week. A season's middle comes first in any week its dates touch."));
  }
  async function load() {
    try { data = await api("GET", "/admin/bingo"); draw(); } catch { box.replaceChildren(h("h4", {}, "Squad bingo"), h("p", { class: "muted small" }, "Couldn't load the pool.")); }
  }
  load();
  return box;
}

async function adminPage() {
  let range = 90;
  const [s, nl, out] = await Promise.all([api("GET", "/admin/stats"), api("GET", "/admin/notices?all=1"), api("GET", "/admin/library").catch(() => ({ plans: [] }))]);
  const tilesBox = h("div", { class: "atiles" });
  const rangeSeg = h("span", { class: "seg" });
  async function drawTiles() {
    rangeSeg.replaceChildren(...[30, 90, 365].map((d) => h("button", { class: range === d ? "on" : "", onclick: () => { range = d; drawTiles(); } }, d === 365 ? "A year" : `${d} days`)));
    let t = null;
    try { t = await api("GET", `/admin/trends?days=${range}`); } catch { t = null; }
    const ser = (k) => (t ? t.series[k] : []);
    const since = (k) => {
      const v = ser(k).filter((x) => x !== null && x !== undefined);
      if (v.length < 2) return "kept from today on";
      const d = v[v.length - 1] - v[0];
      return `${d >= 0 ? "+" : ""}${d.toLocaleString()} in ${ser(k).length - ser(k).findIndex((x) => x !== null && x !== undefined)} days`;
    };
    const tile = (label, value, key, note) => h("div", { class: "at" }, h("small", {}, label), h("b", {}, value),
      key ? sparkline(ser(key)) : h("span", { class: "spark" }), h("small", { class: "muted" }, note ?? (key ? since(key) : "")));
    const pct = s.accounts ? Math.round((100 * s.on3) / s.accounts) : 0;
    tilesBox.replaceChildren(
      tile("accounts", s.accounts.toLocaleString(), "accounts"),
      tile("on 3.x", h("span", {}, s.on3.toLocaleString(), h("small", { class: "muted" }, ` ${pct}%`)), "on3"),
      tile("seen today", s.seenDay.toLocaleString(), "seenDay"),
      tile("seen this week", s.seenWeek.toLocaleString(), "seenWeek"),
      tile("mutual friendships", s.mutualPairs.toLocaleString(), "mutualPairs"),
      tile("plans · following", `${s.plans.toLocaleString()} · ${s.follows.toLocaleString()}`, "follows"),
      tile("squads · in them", `${s.squads.toLocaleString()} · ${s.memberships.toLocaleString()}`, "memberships"),
      tile("tips on cards", s.tips.toLocaleString(), null, ""));
  }

  // sign-in codes, the last 7 days: counters only
  const c = s.codes;
  const codes = h("section", { class: "panel" }, h("h4", {}, "Sign-in codes", h("span", { class: "muted" }, "last 7 days")),
    hbars([["codes sent", c.sent], ["signed in", c.ok], ["wrong code tries", c.wrong], ["ran out of tries or time", c.out], ["held by the rate limit", c.limited]], (l, i) => i > 1),
    h("small", { class: "muted" }, c.sent ? `${Math.round((100 * c.ok) / c.sent)}% of codes end in a sign-in. Counters only: no address, no code.` : "Counters only: no address, no code."));

  // the cutover from 2.x
  const cu = s.cutover, all = Math.max(1, cu.on3 + cu.active2 + cu.quiet);
  const seg = (n, cls) => h("i", { class: cls, style: `width:${(100 * n) / all}%` });
  const cutover = h("section", { class: "panel" }, h("h4", {}, "The cutover", h("span", { class: "muted" }, `of ${s.accounts.toLocaleString()} accounts`)),
    h("div", { class: "stackbar" }, seg(cu.on3, "a"), seg(cu.active2, "b"), seg(cu.quiet, "c")),
    h("div", { class: "legend" }, h("span", {}, h("i", { class: "a" }), `on 3.x · ${cu.on3.toLocaleString()}`),
      h("span", {}, h("i", { class: "b" }), `on 2.x, studied in 7 days · ${cu.active2.toLocaleString()}`),
      h("span", {}, h("i", { class: "c" }), `quiet · ${cu.quiet.toLocaleString()}`)),
    h("small", { class: "muted" }, "2.x counts people whose week the bridge brought in during the last 7 days."));

  // the 2.x bridge
  const b = s.bridge;
  const bridge = h("section", { class: "panel" }, h("h4", {}, "The 2.x bridge", b ? h("span", { class: b.error ? "warn" : "muted" }, `ran ${ago(b.at)}`) : null),
    b ? [h("div", { class: "mini3" }, h("div", {}, h("b", {}, b.pulled.toLocaleString()), h("small", {}, "pulled")),
        h("div", {}, h("b", {}, b.pushed.toLocaleString()), h("small", {}, "pushed")),
        h("div", {}, h("b", {}, `${(b.ms / 1000).toFixed(1)}s`), h("small", {}, "took"))),
      h("small", { class: "muted" }, `Today: ${b.runsToday} run${b.runsToday === 1 ? "" : "s"}, ${b.failedToday} failed.`),
      b.error ? h("p", { class: "warn small" }, `Last error: ${b.error}`) : null]
      : h("p", { class: "muted small" }, "It hasn't run since this page began keeping track (it runs every 15 minutes while the FIREBASE_SA secret is set)."));

  // the library: what's taken out, to put back (Take out is on each card in the library)
  const libList = h("div", { class: "plans" });
  const drawLib = (plans) => libList.replaceChildren(...(plans.length ? plans.map((p) => {
    const back = h("button", { class: "quiet", onclick: async () => {
      back.disabled = true;
      try { await api("DELETE", `/admin/library/${p.id}`); drawLib((await api("GET", "/admin/library")).plans); } catch { back.disabled = false; back.textContent = "Try again"; }
    } }, "Put back");
    return h("div", { class: "plan-row" }, h("b", {}, p.name), back, h("small", {}, `${p.ownerName}'s · taken out: “${p.note}”`));
  }) : [h("p", { class: "muted small" }, "Nothing taken out.")]));
  drawLib(out.plans);
  const library = h("section", { class: "panel" }, h("h4", {}, "The library", h("span", { class: "muted" }, `${s.listed} listed · ${s.takenOut} taken out`)),
    libList, h("small", { class: "muted" }, "Take out is on each card in ", link("/library", "the library"), "; it asks for one line the author reads."));

  // notices: post one, and every recent one with what became of it
  const status = h("p", { class: "status", role: "status" });
  const text = h("input", { id: "ntext", maxlength: 200, style: "width:100%", placeholder: "Due Crew 3.5 is out: a library of plans." });
  const nlink = h("input", { id: "nlink", type: "url", style: "width:100%", placeholder: "https://duecrew.com (optional)" });
  const below = h("input", { id: "nbelow", style: "width:8em", placeholder: "3.5.0" });
  const days = h("input", { id: "ndays", type: "number", min: 1, max: 60, value: 14, style: "width:6em" });
  const count = h("small", { class: "muted" }, "0 / 200");
  text.addEventListener("input", () => { count.textContent = `${text.value.length} / 200`; });
  const form = h("div", { class: "stack", style: "max-width:600px", hidden: true },
    h("label", { for: "ntext" }, "Text"), text, count,
    h("label", { for: "nlink" }, "Link"), nlink,
    h("div", { class: "row" }, h("span", { class: "muted small" }, "Only to add-ons older than"), below, h("span", { class: "muted small" }, "for"), days, h("span", { class: "muted small" }, "days")),
    h("div", {}, h("button", { onclick: () => post() }, "Post notice")), status);
  const list = h("div", { class: "nlist" });
  const until = (t) => { const d = new Date(t * 1000); return `${DAYS[d.getDay()]} ${d.getDate()} ${MONTHS[d.getMonth()]}`; };
  const drawList = (notices) => list.replaceChildren(...(notices.length ? notices.map((n) => {
    const act = n.state === "showing"
      ? h("button", { class: "linkish", onclick: async () => { try { await api("DELETE", `/admin/notices/${n.id}`); drawList((await api("GET", "/admin/notices?all=1")).notices); } catch { /* next load */ } } }, "Take down")
      : h("button", { class: "linkish", onclick: () => { form.hidden = false; text.value = n.text; nlink.value = n.link || ""; below.value = n.below || ""; count.textContent = `${n.text.length} / 200`; text.focus(); } }, "Post again");
    return h("div", { class: "nrow" }, h("div", {}, h("b", {}, n.text),
      h("small", { class: "muted" }, [n.below ? `to add-ons before ${n.below}` : "everyone", n.state === "showing" ? `until ${until(n.until)}` : `from ${until(n.created_at)}`, n.link ? "with a link" : null].filter(Boolean).join(" · "))),
      h("span", { class: `state ${n.state.replace(" ", "")}` }, n.state), act);
  }) : [h("p", { class: "muted small" }, "No notices yet.")]));
  drawList(nl.notices);
  async function post() {
    if (!text.value.trim()) { status.className = "status bad"; status.textContent = "Write the notice first."; return; }
    status.className = "status"; status.textContent = "Posting…";
    try {
      await api("POST", "/admin/notices", { text: text.value, link: nlink.value.trim() || null, below: below.value.trim() || null, days: Number(days.value) || 14 });
      text.value = ""; nlink.value = ""; count.textContent = "0 / 200";
      status.textContent = "Posted. It shows at each board's next refresh.";
      drawList((await api("GET", "/admin/notices?all=1")).notices);
    } catch (err) {
      status.className = "status bad";
      status.textContent = err.body?.error === "bad_link" ? "The link must start with https://."
        : err.body?.error === "bad_below" ? "The version looks like 3.2.1." : "That didn't post. Try again.";
    }
  }
  const notices = h("section", { class: "panel" }, h("h4", {}, "Notices", h("button", { class: "linkish", onclick: () => { form.hidden = !form.hidden; } }, "New notice")),
    h("p", { class: "muted small" }, "One line at the top of everyone's board in Anki (3.2.1 and later) until they dismiss it. The newest one shows."),
    form, list);

  const versions = h("section", { class: "panel" }, h("h4", {}, "Versions", h("span", { class: "muted" }, "accounts by the add-on they last used")),
    hbars(s.versions, (label) => !/^3\./.test(label)));

  // mock "Admin, grown up", A2: a sidebar of pages, one set of gaps
  const nav = {};
  const people = peoplePanel(nav);
  const squads = squadPanel(nav);
  const today = h("div", { class: "apage" },
    h("div", { class: "row", style: "justify-content:space-between" }, h("h2", {}, "Today"), rangeSeg),
    tilesBox, needsYou(s, (p, uid) => (uid ? nav.person(uid) : show(p))), versions);
  const pages = {
    today: ["Today", today],
    people: ["People", h("div", { class: "apage" }, people.el)],
    squads: ["Squads", h("div", { class: "apage" }, squads.el)],
    plans: ["Plans & library", h("div", { class: "apage" }, library)],
    inbox: ["Inbox", h("div", { class: "apage" }, feedbackPanel(nav))],
    notices: ["Notices", h("div", { class: "apage" }, notices)],
    bingo: ["Bingo", h("div", { class: "apage" }, bingoPanel())],
    system: ["System", h("div", { class: "apage" }, h("div", { class: "agrid3" }, codes, cutover, bridge))],
    log: ["Audit log", h("div", { class: "apage" }, auditPanel(nav))],
  };
  const side = h("nav", { class: "aside", "aria-label": "Admin" });
  function show(key) {
    if (!pages[key]) key = "today";
    for (const [k, [, el]] of Object.entries(pages)) el.hidden = k !== key;
    side.replaceChildren(...Object.entries(pages).map(([k, [label]]) =>
      h("button", { class: k === key ? "on" : "", "aria-current": k === key ? "page" : null, onclick: () => show(k) },
        label, k === "inbox" && s.feedbackOpen ? h("i", { class: "ct" }, String(s.feedbackOpen)) : null)));
    history.replaceState(null, "", key === "today" ? "/admin" : `/admin?p=${key}`);
    window.scrollTo(0, 0);
  }
  nav.person = (uid) => { show("people"); people.open(uid); };
  nav.squad = (id) => { show("squads"); squads.open(id); };
  page(h("h1", {}, "Admin"),
    h("p", { class: "muted" }, "Counts, and one account or squad at a time when you look one up. Never how anyone studies."),
    h("div", { class: "ashell" }, side, h("div", { class: "amain" }, ...Object.values(pages).map(([, el]) => el))));
  show(new URLSearchParams(location.search).get("p") || "today");
  $app().classList.add("wide");
  await drawTiles();
}

/** 3.6.5, P6: Send feedback to Sam. The page it came from rides along;
 *  Sam sees the name and can write back by mail, never the address. */
function feedbackPage() {
  const from = (new URLSearchParams(location.search).get("from") || "").replace(/[^A-Za-z0-9/_-]/g, "").slice(0, 80);
  const box = h("textarea", { rows: 7, maxlength: 2000, "aria-label": "Your feedback", placeholder: "What's working, what isn't, what you'd add…", style: "font-family:inherit;font-size:15px" });
  const status = h("p", { class: "status", role: "status" });
  const send = h("button", { onclick: async () => {
    const text = box.value.trim();
    if (!text) { status.className = "status bad"; status.textContent = "Write something first."; return; }
    send.disabled = true; status.className = "status"; status.textContent = "Sending…";
    try {
      await api("POST", "/feedback", { text, ver: `duecrew.com${from ? ` ${from}` : ""}` });
      box.value = ""; status.textContent = "Thanks! Sam reads every one.";
    } catch (err) {
      status.className = "status bad";
      status.textContent = err.status === 429 ? "That's five today. Send more tomorrow." : "That didn't send. Try again.";
    }
    send.disabled = false;
  } }, "Send");
  page(h("h1", {}, "Send feedback to Sam"),
    h("p", { class: "muted" }, "What's working, what isn't, what you'd add. Sam sees your name with it and can write back to your email. Nobody else sees it."),
    h("div", { class: "stack", style: "max-width:640px" }, box, h("div", { class: "row" }, send, h("span", { class: "muted small" }, from ? `Sent with the page you were on (${from}).` : "")), status));
  $app().classList.remove("wide");
  box.focus();
}

/** 3.6.5, P6: the admin's Feedback: newest first, Reply by mail from Due
 *  Crew (the address is never shown), Done, and the sender's account. */
function feedbackPanel(nav) {
  let state = "new";
  const list = h("div", { class: "fb" });
  const seg = h("span", { class: "seg" });
  const ago = (t) => new Date(t * 1000).toLocaleString(undefined, { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
  async function draw() {
    let r;
    try { r = await api("GET", `/admin/feedback?state=${state}`); } catch { list.replaceChildren(h("p", { class: "status bad" }, "Couldn't load feedback.")); return; }
    seg.replaceChildren(...[["new", `New · ${r.open}`], ["done", "Done"], ["all", "All"]].map(([k, t]) =>
      h("button", { class: state === k ? "on" : "", "aria-pressed": String(state === k), onclick: () => { state = k; draw(); } }, t)));
    if (!r.feedback.length) { list.replaceChildren(h("p", { class: "muted small" }, state === "new" ? "Nothing new." : "None.")); return; }
    list.replaceChildren(...r.feedback.map((f) => {
      const replyBox = h("div", { class: "stack", hidden: true });
      const ta = h("textarea", { rows: 3, maxlength: 2000, "aria-label": `Reply to ${f.name}` });
      const st = h("span", { class: "muted small", role: "status" });
      replyBox.append(ta, h("div", { class: "row" }, h("button", { onclick: async (e) => {
        if (!ta.value.trim()) return;
        e.target.disabled = true; st.textContent = "Sending…";
        try { await api("POST", `/admin/feedback/${f.id}/reply`, { text: ta.value }); st.textContent = "Sent."; setTimeout(draw, 800); }
        catch { st.textContent = "That didn't send."; e.target.disabled = false; }
      } }, "Send reply"), st), h("small", { class: "muted" }, "It goes from Due Crew to their email, with what they wrote quoted."));
      return h("div", { class: `item${f.done ? "" : " new"}` },
        h("span", { style: "white-space:pre-wrap" }, f.text),
        h("div", { class: "meta" }, h("span", {}, f.emoji ? `${f.emoji} ` : "", h("b", {}, f.name)), f.ver ? h("span", {}, f.ver) : null,
          h("span", {}, ago(f.at)), f.replied ? h("span", {}, "replied") : null),
        h("div", { class: "acts" },
          h("button", { class: "linkish", onclick: () => { replyBox.hidden = !replyBox.hidden; if (!replyBox.hidden) ta.focus(); } }, "Reply…"),
          h("button", { class: "linkish", onclick: async () => { await api("PATCH", `/admin/feedback/${f.id}`, { done: !f.done }).catch(() => null); draw(); } }, f.done ? "Mark new" : "Mark done"),
          h("button", { class: "linkish", onclick: () => nav.person(f.uid) }, "Account")),
        replyBox);
    }));
  }
  draw();
  return h("section", { class: "panel" }, h("h4", {}, "Feedback", seg), list);
}

async function route() {
  here = location.pathname + location.search;
  window.onbeforeunload = null;  // the builder sets it again when it opens
  const path = location.pathname.replace(/\/+$/, "") || "/";
  try {
    if (path === "/sign-in") return signIn();
    if (path === "/plans/new") return await newPlan();
    let m;
    if ((m = /^\/p\/([A-Za-z0-9]{1,16})$/.exec(path))) return await codePage(m[1].toUpperCase());
    if ((m = /^\/i\/([A-Za-z0-9]{1,12})$/.exec(path))) return await invitePage(m[1].toUpperCase());
    if (!me) return needSignIn();
    if (path === "/plans") return await plansList();
    if (path === "/library") return await libraryPage();
    if (path === "/home" || path === "/") return await home();
    if (path === "/log") return await logPage();
    if (path === "/admin") return await adminPage();
    if (path === "/account") return account();
    if (path === "/feedback") return feedbackPage();
    if ((m = /^\/plans\/([a-z0-9]{16})\/edit$/.exec(path))) return await builder(m[1]);
    if ((m = /^\/plans\/([a-z0-9]{16})$/.exec(path))) return await builder(m[1]);
    page(h("h1", {}, "Not here"), link("/plans", "Your plans"));
  } catch (err) {
    if (err.status === 401) { me = null; renderNav(); return needSignIn(); }
    page(h("h1", {}, err.status === 404 ? "Not found" : "Something went wrong"),
      h("p", { class: "muted" }, err.status === 404 ? "It may have been deleted, or it isn't yours to see." : "Try again in a moment."));
  }
}

/** A link from Anki carries a one-time sign-in token after the # (never
 *  sent to any server log): any page trades it for a session first, and
 *  it leaves the address bar at once. */
async function start() {
  const token = /^#([A-Za-z0-9_-]{43})$/.exec(location.hash);
  if (token) {
    history.replaceState(null, "", location.pathname + location.search);
    try { await api("POST", "/auth/link/redeem", { token: token[1] }); }
    catch { /* expired or used: a session already here carries on */ }
  }
  await whoami();
  await route();
}

start();
