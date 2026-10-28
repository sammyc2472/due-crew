// Plans (3.1): a list of dates for one shared deck, made by its author and
// followed by anyone with its code (or, for a squad plan, the squad). A
// follower's add-on unsuspends each date's cards on the morning it opens;
// the server only holds names, counts, note guids with card numbers, dates
// and progress counts. Never card text. See docs/plans-design.md.

import type { Session } from "./auth";
import { limitOrThrow } from "./limits";
import { SQUAD_ALPHABET, normalizeCode } from "./squads";
import * as V from "./validate";
import { Env, HttpError, clientIp, json, nowSec, readJson } from "./util";

export const PLAN_CODE_LEN = 8;
const UNITS_MAX = 200;
const EVENTS_MAX = 200;  // F1: named days (a lecture, a quiz, the exam) the dates prep for
const CARDS_MAX = 50000;  // 3.3: a class lead's own lecture tags, for a year
const IDS_MAX = 50000;    // 3.3, C5: note ids kept behind a plan's tags and subdecks
const SEARCH_MAX = 10;
const IDLIST_MAX = 5000;  // E1: note or card ids pasted onto one date
const IDR_MAX = 20000;   // 3.6.5: the cards those ids are, as note guid + card number, from the author's Anki
const SEARCH_LEN = 500;
const REVIEWS_MAX = 60;
const TODO_MAX = 8;  // Due: a date's lines to tick by hand
const EVERY_MAX = 6;  // 3.8.0: the plan's lines that come every week ("every Fri: practice questions")
export const PLAN_BODY_MAX = 1600 * 1024;
const SOURCES_MAX = 50;
const PATH_MAX = 200;
const COVER_MAX = 500;
const DOC_MAX = 1536 * 1024;  // 3.3: 50,000 cards; one D1 row holds 2 MB
const TREE_MAX = 5000;
const NEST_MAX = 100000;  // names in a nested tree; the body's size binds first
const TREE_BODY_MAX = 1536 * 1024;  // a big deck's tags, nested; one D1 row holds 2 MB
const NEST_DEPTH = 20;
const LINE_MAX = 120;
const SUMMARY_MAX = 120;
const LOG_KEEP = 30;
const EDITORS_MAX = 10;
const NOTES_MAX = 500;
const NOTES_PER_PERSON = 50;  // one follower's share of a plan's notes
const NOTE_TEXT_MAX = 280;
const POST_MAX = 200;        // 3.7.3: a post to followers, one line
const POSTS_PER_DAY = 5;     // a plan's posts in a day, all its authors together
const POSTS_KEEP = 50;       // a plan keeps its newest
const POSTS_ON_BOARD = 3;    // the newest per plan ride an add-on's board
export const FOLLOWS_MAX = 20;  // the plans I follow that I can see (FOLLOWED): what every board carries
// and the follows kept in all, a squad's plan I left (hidden, kept for when I'm back) among them
const FOLLOWS_KEPT = FOLLOWS_MAX * 5;
const TOTALS_EVERY = 3600;  // a plan's totals are worked out again when read older than this
const TREES_MAX = 20;
export const PLANS_MAX = 50;
// 3.7.2: what one account's plans keep in all (docs, library cards and the
// copy Undo puts back). A save that grows past it is refused; one that
// shrinks never is. With TREES_BYTES, one account can't fill the database.
export const PLAN_BYTES_MAX = 24 * 1024 * 1024;
const TREES_BYTES = 6 * 1024 * 1024;
const UNIT_ID = /^[a-z0-9]{1,12}$/;
// 3.8.0, plan tags: the plan's own tags (SLG 12), made in an author's Anki
// (exact notes, by guid) or from text (a tag's, a subdeck's or a search's
// cards, found in each follower's copy). Each follower's Anki puts them on
// its notes as DueCrew::{tagroot}::{the name}; a date uses one as any tag.
// Names and note guids only, never card text.
const TAGS_MAX = 100;
const TAG_NAME_MAX = 40;
const TAG_ROOT_MAX = 60;
// 3.8.1: where to get the deck (a link), and the authors' notes on a tag or
// a card (`remarks`), riding the doc: words and a link, never card text
const DECK_URL_MAX = 300;
// printable ASCII only (no space, quotes or <>): no control or direction-flipping character a link could hide behind
const DECK_URL = /^https:\/\/[\x21\x23-\x26\x28-\x2e\x30-\x3b\x3d\x3f-\x7e][\x21\x23-\x26\x28-\x3b\x3d\x3f-\x7e]*$/;
const REMARKS_MAX = 300;
const REMARK_TEXT_MAX = 280;
const LABELS_MAX = 3;  // 3.8.1: the deck tags a date's picked cards sit under (`pl`)
const INVITES_ON_BOARD = 10;  // 3.8.1: my pending co-author invites and hand-overs a board carries

type Obj = Record<string, unknown>;
export type Plan = { id: string; code: string; owner: string; name: string; line: string; audience: string;
  squad: string | null; doc: string; version: number; updated_at: number;
  listed?: number; listed_note?: string | null; lib?: string | null; based_on?: string | null; tagroot?: string | null;
  totals?: string | null; totals_at?: number | null; handover?: string | null; starter?: number };

export function draw(n: number): string {
  const bytes = crypto.getRandomValues(new Uint8Array(n));
  return [...bytes].map((b) => SQUAD_ALPHABET[b % 32]).join("");
}

const newUnitId = () => draw(8).toLowerCase().replace(/[^a-z0-9]/g, "x");

// ---- shapes ----

function path(v: unknown): string {
  if (!V.isStr(v, PATH_MAX, 1) || /[\u0000-\u001f]/.test(v)) throw V.bad("plan");
  return v;
}

/** A date's new cards as far as the server knows: its tags' and subdecks'
 *  count, single cards, what its searches and pasted ids found. */
export function unitCount(u: Obj): number {
  return ((u.n as number) || 0) + ((u.cards as unknown[]) || []).length
    + Object.values((u.sn as Record<string, number>) || {}).reduce((a, x) => a + x, 0)
    + ((u.idn as number | undefined) ?? (((u.nids as unknown[]) || []).length + ((u.cids as unknown[]) || []).length
      + ((u.notes as unknown[]) || []).length));
}

function cardRef(v: unknown): [string, number] {
  if (!Array.isArray(v) || v.length !== 2 || !V.isStr(v[0], V.GUID_MAX, 1) || !V.isInt(v[1], 0, 1000)) throw V.bad("plan");
  return [v[0], v[1]];
}

/** Due: a line to tick by hand, {k, t, url?}; `every` (3.8.0) adds `r`,
 *  its weekdays (Monday "0"), kept sorted. */
function todoLine(x: unknown, every = false): Obj {
  if (!V.isObj(x) || Object.keys(x).some((k) => !["k", "t", "url", ...(every ? ["r"] : [])].includes(k))) throw V.bad("plan");
  if (!["watch", "read", "do"].includes(x.k as string) || !V.isStr(x.t, 140, 1) || /[\u0000-\u001f]/.test(x.t as string)) throw V.bad("plan");
  const one: Obj = { k: x.k, t: (x.t as string).trim() };
  if (x.url !== undefined && x.url !== null && x.url !== "") {
    if (!V.isStr(x.url, 500, 1) || !/^https:\/\/[^\s"'<>]+$/.test(x.url as string)) throw V.bad("plan");
    one.url = x.url;
  }
  if (!one.t) throw V.bad("plan");
  if (every) {
    if (!V.isStr(x.r, 7, 1) || !/^[0-6]+$/.test(x.r as string)) throw V.bad("plan");
    one.r = [...new Set((x.r as string).split(""))].sort().join("");
  }
  return one;
}

function unit(v: unknown): Obj {
  if (!V.isObj(v)) throw V.bad("plan");
  for (const k of Object.keys(v)) if (!["id", "name", "opens", "due", "lead", "check", "tags", "decks", "cards", "n", "even", "search", "sn", "ids", "nids", "cids", "idn", "for", "notes", "idr", "pn", "todo", "cut", "pl"].includes(k)) throw V.bad("plan");
  // "every" is taken: a plan's weekly lines are ticked as pid:every:… (3.8.0)
  if (!V.isStr(v.id, 12) || !UNIT_ID.test(v.id) || v.id === "every") throw V.bad("plan");
  if (!V.isDate(v.opens)) throw V.bad("plan");
  const out: Obj = { id: v.id, name: V.displayName(v.name), opens: v.opens };
  if (v.due !== undefined && v.due !== null) {
    if (!V.isDate(v.due) || v.due < v.opens) throw V.bad("plan");
    out.due = v.due;
  }
  if (v.even !== undefined && v.even !== null && v.even !== false) {
    // 3.3: split evenly over its days, the same slices for everyone (needs a due date after it opens)
    if (v.even !== true || !out.due || out.due === out.opens) throw V.bad("plan");
    out.even = true;
  }
  if (v.check !== undefined && v.check !== null) {
    // 3.2: a checkpoint, the morning a filtered deck of this date's cards is built
    if (!V.isDate(v.check) || v.check < v.opens) throw V.bad("plan");
    out.check = v.check;
  }
  if (v.lead !== undefined && v.lead !== null) {  // 3.1 docs only; the builder no longer writes it
    if (!V.isStr(v.lead, 128, 1)) throw V.bad("plan");
    out.lead = v.lead;
  }
  if (v.n !== undefined && v.n !== null) {
    // how many cards the tags and subdecks hold in the author's copy, so a
    // follower sees "204 of 212"; a number, never which cards
    if (!V.isInt(v.n, 0, 1_000_000)) throw V.bad("plan");
    out.n = v.n;
  }
  for (const k of ["tags", "decks"] as const) {
    const x = v[k] ?? [];
    if (!Array.isArray(x) || x.length > SOURCES_MAX) throw V.bad("plan");
    out[k] = [...new Set(x.map(path))];
  }
  // 3.3, C3: Anki searches, run by each follower's Anki inside the plan's deck
  const search = v.search ?? [];
  if (!Array.isArray(search) || search.length > SEARCH_MAX
      || !search.every((q) => V.isStr(q, SEARCH_LEN, 1) && !/[\u0000-\u001f]/.test(q as string))) throw V.bad("plan");
  if (search.length) out.search = [...new Set(search as string[])];
  if (v.sn !== undefined && v.sn !== null) {
    // how many cards each search found in the author's Anki, when it was added there
    if (!V.isObj(v.sn) || Object.keys(v.sn).length > SEARCH_MAX
        || !Object.entries(v.sn).every(([q, n]) => (out.search as string[] | undefined)?.includes(q) && V.isInt(n, 0, 1_000_000))) throw V.bad("plan");
    if (Object.keys(v.sn).length) out.sn = v.sn;
  }
  if (v.cut !== undefined && v.cut !== null) {
    // 3.8.1: a tag kept to the cards of one of the plan's own tags ("Cephalosporins
    // in SLG 12"): {tag, in: that plan tag's id, q: the same as an Anki search,
    // which stays in `search` so an add-on before 3.8.1 opens the same cards}
    if (!Array.isArray(v.cut) || v.cut.length > SEARCH_MAX) throw V.bad("plan");
    const qs = (out.search as string[] | undefined) || [];
    const seen = new Set<string>();
    const cut = v.cut.map((c) => {
      if (!V.isObj(c) || Object.keys(c).some((k) => !["tag", "in", "q"].includes(k))) throw V.bad("plan");
      if (!V.isStr(c.in, 12) || !UNIT_ID.test(c.in as string) || !V.isStr(c.q, SEARCH_LEN, 1) || !qs.includes(c.q as string)) throw V.bad("plan");
      return { tag: path(c.tag), in: c.in as string, q: c.q as string };
    }).filter((c) => !seen.has(`${c.tag}\u0000${c.in}`) && seen.add(`${c.tag}\u0000${c.in}`));
    if (cut.length) out.cut = cut;
  }
  if (v.ids !== undefined && v.ids !== null) {
    // 3.3, C5: the note ids behind its tags and subdecks in the author's Anki
    if (!Array.isArray(v.ids) || v.ids.length > IDS_MAX || !v.ids.every((g) => V.isStr(g, V.GUID_MAX, 1))) throw V.bad("plan");
    if (v.ids.length) out.ids = [...new Set(v.ids as string[])];
  }
  if (v.todo !== undefined && v.todo !== null) {
    // Due: what a date asks that cards can't measure (a lecture to watch, a
    // chapter to read), each follower ticking it by hand; words and a link
    if (!Array.isArray(v.todo) || v.todo.length > TODO_MAX) throw V.bad("plan");
    const todo = v.todo.map((x) => todoLine(x));
    if (todo.length) out.todo = todo;
  }
  const cards = v.cards ?? [];
  if (!Array.isArray(cards)) throw V.bad("plan");
  const seen = new Set<string>();
  out.cards = cards.map(cardRef).filter(([g, o]) => !seen.has(`${g}:${o}`) && seen.add(`${g}:${o}`));
  // E1: note ids and card ids pasted onto the date, run in each follower's
  // Anki inside the plan's deck; numbers only, and `idn` how many cards they
  // found in the author's Anki
  for (const k of ["nids", "cids"]) {
    const a = v[k];
    if (a === undefined || a === null) continue;
    if (!Array.isArray(a) || a.length > IDLIST_MAX || !a.every((x) => Number.isSafeInteger(x) && (x as number) > 0)) throw V.bad("plan");
    if (a.length) out[k] = [...new Set(a as number[])];
  }
  // 3.6.5: notes by their guid (`notes:` in Text): every card of each, in
  // anyone's copy, where a note id is only the same in copies of one import
  if (v.notes !== undefined && v.notes !== null) {
    if (!Array.isArray(v.notes) || v.notes.length > IDLIST_MAX || !v.notes.every((g) => V.isStr(g, V.GUID_MAX, 1))) throw V.bad("plan");
    if (v.notes.length) out.notes = [...new Set(v.notes as string[])];
  }
  // 3.6.5: the cards the pasted ids are in the author's Anki, as guid + card
  // number (PUT /plans/{id}/ids), so a follower whose ids differ still gets them
  if (v.idr !== undefined && v.idr !== null) {
    if (!Array.isArray(v.idr) || v.idr.length > IDR_MAX) throw V.bad("plan");
    const refs = v.idr.map(cardRef);
    if (refs.length && (out.nids || out.cids)) out.idr = refs;
  }
  // F1: the event this date preps for, by its id
  if (v.for !== undefined && v.for !== null) {
    if (!V.isStr(v.for, 12) || !UNIT_ID.test(v.for)) throw V.bad("plan");
    out.for = v.for;
  }
  if (v.idn !== undefined && v.idn !== null) {
    if (!V.isInt(v.idn, 0, 1_000_000)) throw V.bad("plan");
    if (out.nids || out.cids || out.notes) out.idn = v.idn;
  }
  // 3.6.5, P1: [new, repeat, missing] as the author's Anki counted the date
  if (v.pn !== undefined && v.pn !== null) {
    if (!Array.isArray(v.pn) || v.pn.length !== 3 || !v.pn.every((n) => V.isInt(n, 0, 1_000_000))) throw V.bad("plan");
    out.pn = v.pn;
  }
  // 3.8.1: what its picked cards are: the deck tags they sit under in the
  // author's copy, with how many (PUT /plans/{id}/ids "#lbl"), while it has picks
  if (v.pl !== undefined && v.pl !== null) {
    const pl = labels(v.pl);
    if (!pl) throw V.bad("plan");
    if (pl.length && hasPicks(out)) out.pl = pl;
  }
  return out;
}

/** 3.8.1: `pl`, [[tag path, n]], at most LABELS_MAX; null when it isn't that. */
function labels(v: unknown): [string, number][] | null {
  if (!Array.isArray(v) || v.length > LABELS_MAX) return null;
  const ok = v.every((x) => Array.isArray(x) && x.length === 2 && V.isStr(x[0], PATH_MAX, 1) && !/[\u0000-\u001f]/.test(x[0])
    && V.isInt(x[1], 0, 1_000_000));
  return ok ? (v as [string, number][]).map(([t, n]) => [t, n]) : null;
}

/** A date's picked cards: single cards, notes, pasted ids. */
const hasPicks = (u: Obj) => !!(((u.cards as unknown[] | undefined) || []).length || u.notes || u.nids || u.cids);
const picksOf = (u: Obj) => [u.cards ?? [], u.notes ?? [], u.nids ?? [], u.cids ?? []];

/** 3.8.1: a remark, {id, tag | card, text}: an author's note on a deck tag
 *  (or a plan tag's DueCrew:: path) or on one card, for followers. One line. */
function remark(v: unknown): Obj {
  if (!V.isObj(v) || Object.keys(v).some((k) => !["id", "tag", "card", "text"].includes(k))) throw V.bad("plan");
  if (!V.isStr(v.id, 12) || !UNIT_ID.test(v.id)) throw V.bad("plan");
  const tag = v.tag !== undefined && v.tag !== null, card = v.card !== undefined && v.card !== null;
  if (tag === card) throw V.bad("plan");  // exactly one
  const out: Obj = { id: v.id, ...(tag ? { tag: path(v.tag) } : { card: cardRef(v.card) }) };
  if (!V.isStr(v.text, REMARK_TEXT_MAX, 1)) throw V.bad("plan");
  out.text = V.oneLine(v.text, REMARK_TEXT_MAX);
  if (!out.text) throw V.bad("plan");
  return out;
}

/** A name as one part of an Anki tag: spaces become _, the characters a tag
 *  or a search can't hold go, a : is a -. The twin of plans.py tag_part
 *  and Tags.part in builder.js: change one, change all three. */
const slug = (name: string) => String(name).replace(/\s+/gu, "_").replace(/["*\\%]/g, "").replace(/:/g, "-")
  .replace(/_+/g, "_").replace(/^[_-]+|[_-]+$/g, "");

export function tagPart(name: string): string {
  return slug(name) || "tag";
}

/** The plan's own part of its tags, from its name when the first is made
 *  (and then kept, whatever the plan is called later). The twin of
 *  plans.py tag_root and Tags.root in builder.js. */
export function tagRoot(planName: string): string {
  return slug(planName).slice(0, TAG_ROOT_MAX).replace(/[_-]+$/, "") || "plan";
}

const escRe = (x: string) => x.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** The doc with its plan tags moved from DueCrew::{from} to DueCrew::{to}:
 *  the root, and every date, plan tag and pace pick that names one, as a tag
 *  or inside a search (escaped as Tags.ankiSearch writes it, or not). */
export function reroot(doc: Obj, from: string, to: string): Obj {
  const plain = new RegExp(`(^|[\\s"(:-])DueCrew::${escRe(from)}(?=::|$|[\\s")])`, "gi");
  const esc = new RegExp(`DueCrew::${escRe(from.replace(/_/g, "\\_"))}(?=::|$|[\\s")])`, "gi");
  const tag = (t: string) => t.toLowerCase() === `duecrew::${from.toLowerCase()}` || t.toLowerCase().startsWith(`duecrew::${from.toLowerCase()}::`)
    ? `DueCrew::${to}${t.slice(`DueCrew::${from}`.length)}` : t;
  const q = (x: string) => x.replace(esc, `DueCrew::${to.replace(/_/g, "\\_")}`).replace(plain, (_m, pre) => `${pre}DueCrew::${to}`);
  const fix = (o: Obj) => {
    if (Array.isArray(o.tags)) o.tags = (o.tags as unknown[]).map((t) => typeof t === "string" ? tag(t) : t);
    if (Array.isArray(o.search)) o.search = (o.search as unknown[]).map((x) => typeof x === "string" ? q(x) : x);
    if (o.sn && typeof o.sn === "object") o.sn = Object.fromEntries(Object.entries(o.sn as Obj).map(([k, v]) => [q(k), v]));
    if (Array.isArray(o.cut)) o.cut = (o.cut as Obj[]).map((c) => ({ ...c, tag: tag(String(c.tag)), q: q(String(c.q)) }));
  };
  const out = JSON.parse(JSON.stringify(doc)) as Obj;
  for (const u of (out.units as Obj[] | undefined) || []) fix(u);
  for (const t of (out.tags as Obj[] | undefined) || []) fix(t);
  const pace = out.pace as Obj | undefined;
  if (pace && Array.isArray(pace.cover)) pace.cover = (pace.cover as unknown[]).map((c) => typeof c === "string" && c.startsWith("tag:") ? `tag:${tag(c.slice(4))}` : c);
  // 3.8.1: an author's note on a plan tag follows it
  for (const r of (out.remarks as Obj[] | undefined) || []) if (typeof r.tag === "string") r.tag = tag(r.tag);
  out.tagroot = to;
  return out;
}

/** The tag roots a plan may take, in order: the one asked for, then _2 to
 *  _50, then (a name fifty plans share) one ending in the plan's own id,
 *  which no other plan has, and the id alone. All fit TAG_ROOT_MAX. */
export function rootTries(want: string, id: string): string[] {
  const cut = (sfx: string) => `${want.slice(0, TAG_ROOT_MAX - sfx.length).replace(/[_-]+$/, "") || "plan"}${sfx}`;
  return [cut(""), ...Array.from({ length: 49 }, (_, i) => cut(`_${i + 2}`)), cut(`_${id}`), id];
}

/** The plan's tag root, its own: the one it holds (a save never moves it),
 *  or, with its first tag, the first of rootTries no other plan has (case
 *  aside). The doc comes back with its dates following. */
export async function rooted(env: Env, id: string, held: string | null | undefined, doc: Obj): Promise<{ doc: Obj; root: string | null }> {
  const want = doc.tagroot as string | undefined;
  if (!want) return { doc, root: held ?? null };
  if (held) return { doc: want === held ? doc : reroot(doc, want, held), root: held };
  const tries = rootTries(want, id);
  const taken = (r: string) => env.DB.prepare("SELECT 1 AS x FROM plans WHERE tagroot = ? COLLATE NOCASE AND id != ?").bind(r, id);
  const take = (r: string) => ({ doc: r === want ? doc : reroot(doc, want, r), root: r });
  // the one asked for is free nearly always: one read; else the rest in one batch, each by the index
  if (!(await taken(tries[0]).first("x"))) return take(tries[0]);
  const rows = await env.DB.batch(tries.slice(1).map(taken));
  const free = rows.findIndex((x) => !x.results.length);
  if (free < 0) throw new HttpError(503, "try_again");
  return take(tries[free + 1]);
}

/** Two saves took the same root at once: the second saves again (409), and gets _2. */
export function rootTaken(e: unknown): never {
  if (String((e as Error)?.message || e).includes("UNIQUE") && String((e as Error)?.message || e).includes("tagroot")) throw new HttpError(409, "stale");
  throw e;
}

/** A plan tag: {id, name, notes?, cards?, tags?, decks?, search?, n?}: what it
 *  holds is exact notes, or a tag's, a subdeck's or a search's cards in
 *  each follower's copy; `n` how many cards the author's Anki found. */
function planTag(v: unknown): Obj {
  if (!V.isObj(v)) throw V.bad("plan");
  for (const k of Object.keys(v)) if (!["id", "name", "notes", "cards", "tags", "decks", "search", "n"].includes(k)) throw V.bad("plan");
  if (!V.isStr(v.id, 12) || !UNIT_ID.test(v.id)) throw V.bad("plan");
  const name = V.displayName(v.name);
  if (name.length > TAG_NAME_MAX) throw V.bad("plan");
  const out: Obj = { id: v.id, name };
  for (const k of ["tags", "decks"] as const) {
    const x = v[k] ?? [];
    if (!Array.isArray(x) || x.length > SOURCES_MAX) throw V.bad("plan");
    if (x.length) out[k] = [...new Set(x.map(path))];
  }
  const search = v.search ?? [];
  if (!Array.isArray(search) || search.length > SEARCH_MAX
      || !search.every((q) => V.isStr(q, SEARCH_LEN, 1) && !/[\u0000-\u001f]/.test(q as string))) throw V.bad("plan");
  if (search.length) out.search = [...new Set(search as string[])];
  const notes = v.notes ?? [];
  if (!Array.isArray(notes) || notes.length > IDLIST_MAX || !notes.every((g) => V.isStr(g, V.GUID_MAX, 1))) throw V.bad("plan");
  if (notes.length) out.notes = [...new Set(notes as string[])];
  // 3.8.1: single cards, as a date's are (guid + card number): the tag goes on
  // their notes in Anki (Anki tags notes), and Due Crew uses just these cards
  const cards = v.cards ?? [];
  if (!Array.isArray(cards) || cards.length > IDLIST_MAX) throw V.bad("plan");
  const seenCard = new Set<string>();
  const refs = cards.map(cardRef).filter(([g, o]) => !seenCard.has(`${g}:${o}`) && seenCard.add(`${g}:${o}`));
  if (refs.length) out.cards = refs;
  if (!out.tags && !out.decks && !out.search && !out.notes && !out.cards) throw V.bad("plan");  // a tag holds something
  if (v.n !== undefined && v.n !== null) {
    if (!V.isInt(v.n, 0, 1_000_000)) throw V.bad("plan");
    out.n = v.n;
  }
  return out;
}

/** 3.2: the plan's shape over time. `catchup`: every nth week opens nothing
 *  new (0: none); `taper`: the last days before `end` open nothing new. */
function phases(v: unknown): Obj {
  if (!V.isObj(v)) throw V.bad("plan");
  for (const k of Object.keys(v)) if (!["catchup", "taper"].includes(k)) throw V.bad("plan");
  const catchup = v.catchup ?? 0;
  const taper = v.taper ?? 0;
  if (!V.isInt(catchup, 0, 8) || catchup === 1 || !V.isInt(taper, 0, 60)) throw V.bad("plan");
  return { catchup, taper };
}

/** 3.3: the builder's pace. `days`, Monday first: the plan's study days
 *  (1) and days off (0); `mode`: an end date, cards a day, or each day as
 *  placed; `daily`: cards a day; `cover`: what the plan means to cover
 *  ("tag:path" or "deck:path"), for laying it out. Only `days` reaches a
 *  follower: an even split spreads over them. */
function pace(v: unknown): Obj {
  if (!V.isObj(v)) throw V.bad("plan");
  for (const k of Object.keys(v)) if (!["mode", "days", "daily", "cover"].includes(k)) throw V.bad("plan");
  if (!["end", "daily", "placed"].includes(v.mode as string)) throw V.bad("plan");
  if (!Array.isArray(v.days) || v.days.length !== 7 || !v.days.every((d) => d === 0 || d === 1) || !v.days.some((d) => d === 1)) throw V.bad("plan");
  const out: Obj = { mode: v.mode, days: v.days };
  if (v.daily !== undefined && v.daily !== null) {
    if (!V.isInt(v.daily, 1, 5000)) throw V.bad("plan");
    out.daily = v.daily;
  }
  if (v.cover !== undefined && v.cover !== null) {
    if (!Array.isArray(v.cover) || v.cover.length > COVER_MAX) throw V.bad("plan");
    out.cover = [...new Set(v.cover.map((c) => {
      if (!V.isStr(c, PATH_MAX + 5, 5) || !/^(tag|deck):./.test(c)) throw V.bad("plan");
      path(c.slice(c.indexOf(":") + 1));
      return c;
    }))];
  }
  return out;
}

/** A plan's doc: {deck, exam?, end?, phases?, pace?, units}. Units sorted by when they open. */
export function planDoc(v: unknown): Obj {
  if (!V.isObj(v)) throw V.bad("plan");
  for (const k of Object.keys(v)) if (!["deck", "deckUrl", "exam", "end", "phases", "pace", "reviews", "units", "events", "every", "tags", "tagroot", "remarks"].includes(k)) throw V.bad("plan");
  const out: Obj = { deck: path(v.deck) };
  if (v.deckUrl !== undefined && v.deckUrl !== null && v.deckUrl !== "") {
    // 3.8.1: where to get the deck, for a follower whose Anki has none by its name
    if (!V.isStr(v.deckUrl, DECK_URL_MAX, 9) || !DECK_URL.test(v.deckUrl)) throw V.bad("plan");
    out.deckUrl = v.deckUrl;
  }
  if (v.pace !== undefined && v.pace !== null) out.pace = pace(v.pace);
  if (v.end !== undefined && v.end !== null) {
    if (!V.isDate(v.end)) throw V.bad("plan");
    out.end = v.end;
  }
  if (v.phases !== undefined && v.phases !== null) {
    const ph = phases(v.phases);
    if (ph.catchup || ph.taper) out.phases = ph;
    if (ph.taper && !out.end) throw V.bad("plan");  // a taper runs up to the end date
  }
  if (v.exam !== undefined && v.exam !== null) {
    const e = v.exam as Obj;
    if (!V.isObj(e) || !V.isDate(e.date) || !V.isInt(e.target, 50, 100)
        || (e.by !== undefined && !V.isDate(e.by))) throw V.bad("plan");
    out.exam = { date: e.date, target: e.target, ...(e.by ? { by: e.by } : {}) };
  }
  if (!Array.isArray(v.units) || v.units.length > UNITS_MAX) throw V.bad("plan");
  const units = v.units.map(unit);
  if (new Set(units.map((u) => u.id)).size !== units.length) throw V.bad("plan");
  const idLen = (u: Obj) => ((u.nids as unknown[] | undefined)?.length ?? 0) + ((u.cids as unknown[] | undefined)?.length ?? 0)
    + ((u.notes as unknown[] | undefined)?.length ?? 0);
  // 3.8.0: the plan's tags, under its own part of the tag (fixed when the first was made)
  let tagNotes = 0;
  if (v.tags !== undefined && v.tags !== null) {
    if (!Array.isArray(v.tags) || v.tags.length > TAGS_MAX) throw V.bad("plan");
    const tags = v.tags.map(planTag);
    const parts = new Set(tags.map((t) => tagPart(t.name as string).toLowerCase()));
    if (new Set(tags.map((t) => t.id)).size !== tags.length || parts.size !== tags.length) throw V.bad("plan");
    if (tags.length) {
      if (!V.isStr(v.tagroot, TAG_ROOT_MAX, 1) || tagPart(v.tagroot as string) !== v.tagroot) throw V.bad("plan");
      out.tagroot = v.tagroot;
      out.tags = tags;
      tagNotes = tags.reduce((n, t) => n + ((t.notes as unknown[] | undefined)?.length ?? 0) + ((t.cards as unknown[] | undefined)?.length ?? 0), 0);
    }
  }
  if (!out.tags && v.tagroot !== undefined && v.tagroot !== null) {
    // kept once made, so a tag made again lands where the old one was
    if (!V.isStr(v.tagroot, TAG_ROOT_MAX, 1) || tagPart(v.tagroot as string) !== v.tagroot) throw V.bad("plan");
    out.tagroot = v.tagroot;
  }
  if (units.reduce((n, u) => n + (u.cards as unknown[]).length + idLen(u), 0) + tagNotes > CARDS_MAX) throw V.bad("plan");
  if (units.reduce((n, u) => n + ((u.ids as unknown[] | undefined)?.length ?? 0), 0) > IDS_MAX) throw V.bad("plan");
  if (units.reduce((n, u) => n + ((u.idr as unknown[] | undefined)?.length ?? 0), 0) > IDS_MAX) throw V.bad("plan");
  if (v.reviews !== undefined && v.reviews !== null) {
    // 3.3, C4: a review day: that morning, a filtered deck of the dates from `from` to `to`
    const ids = new Set(units.map((u) => u.id));
    if (!Array.isArray(v.reviews) || v.reviews.length > REVIEWS_MAX) throw V.bad("plan");
    const rs = v.reviews.map((r) => {
      if (!V.isObj(r) || Object.keys(r).some((k) => !["day", "from", "to"].includes(k)) || !V.isDate(r.day)
          || !ids.has(r.from as string) || !ids.has(r.to as string)) throw V.bad("plan");
      return { day: r.day, from: r.from, to: r.to };
    });
    if (rs.length) out.reviews = rs.sort((a, b) => String(a.day).localeCompare(String(b.day)));
  }
  // F1: events: a name on a day; a date's `for` names one (a `for` whose
  // event went, in a merge, is dropped rather than refused)
  const evIds = new Set<string>();
  if (v.events !== undefined && v.events !== null) {
    if (!Array.isArray(v.events) || v.events.length > EVENTS_MAX) throw V.bad("plan");
    const evs = v.events.map((e) => {
      if (!V.isObj(e) || Object.keys(e).some((k) => !["id", "day", "name"].includes(k)) || !V.isStr(e.id, 12) || !UNIT_ID.test(e.id as string)
          || !V.isDate(e.day)) throw V.bad("plan");
      const name = V.displayName(e.name);
      if (!name) throw V.bad("plan");
      if (evIds.has(e.id as string)) throw V.bad("plan");
      evIds.add(e.id as string);
      return { id: e.id, day: e.day, name };
    });
    if (evs.length) out.events = evs.sort((a, b) => String(a.day).localeCompare(String(b.day)));
  }
  for (const u of units) if (u.for && !evIds.has(u.for as string)) delete u.for;
  if (v.every !== undefined && v.every !== null) {
    // 3.8.0: lines that come every week on their weekdays, from the plan's
    // first date to its last (Due, each follower ticking each day's by hand)
    if (!Array.isArray(v.every) || v.every.length > EVERY_MAX) throw V.bad("plan");
    const every = v.every.map((x) => todoLine(x, true));
    if (every.length) out.every = every;
  }
  if (v.remarks !== undefined && v.remarks !== null) {
    // 3.8.1: the authors' notes on a tag or a card, each follower's Anki
    // showing them where that tag or card comes up
    if (!Array.isArray(v.remarks) || v.remarks.length > REMARKS_MAX) throw V.bad("plan");
    const rs = v.remarks.map(remark);
    if (new Set(rs.map((r) => r.id)).size !== rs.length) throw V.bad("plan");
    if (rs.length) out.remarks = rs;
  }
  // 3.8.1: a cut whose plan tag went (in a merge, or its last note taken off
  // in Anki) is its whole tag again, and its search goes with it
  const tagIds = new Set(((out.tags as Obj[] | undefined) || []).map((t) => t.id as string));
  for (const u of units) {
    if (!u.cut) continue;
    const keep = (u.cut as Obj[]).filter((c) => tagIds.has(c.in as string));
    for (const c of (u.cut as Obj[]).filter((x) => !keep.includes(x))) {
      u.tags = [...new Set([...(u.tags as string[]), c.tag as string])];
      if (u.search) u.search = (u.search as string[]).filter((q) => q !== c.q);
      if (u.sn) delete (u.sn as Obj)[c.q as string];
    }
    if (keep.length) u.cut = keep; else delete u.cut;
    if (u.search && !(u.search as string[]).length) delete u.search;
    if (u.sn && !Object.keys(u.sn as Obj).length) delete u.sn;
  }
  units.sort((a, b) => String(a.opens).localeCompare(String(b.opens)));
  out.units = units;
  if (JSON.stringify(out).length > DOC_MAX) throw V.bad("plan");
  return out;
}

/** 3.5, B: what a library card shows, so the library never reads a doc:
 *  the deck, how many dates over how many days, about how many new cards a
 *  study day, review days, events, and whether dates hold pasted ids. */
export function libCard(doc: Obj): Obj {
  const units = (doc.units as Obj[]) || [];
  const from = units.length ? (units[0].opens as string) : null;  // sorted by when they open
  const to = units.reduce<string | null>((m, u) => { const e = (u.due as string) || (u.opens as string); return !m || e > m ? e : m; }, null);
  const days = from && to ? Math.round((Date.parse(to) - Date.parse(from)) / 86400000) + 1 : 0;
  const week = ((doc.pace as Obj | undefined)?.days as number[] | undefined) || [1, 1, 1, 1, 1, 1, 1];
  let study = 0;
  for (let i = 0; i < days; i++) if (week[(new Date(Date.parse(`${from}T00:00:00Z`) + i * 86400000).getUTCDay() + 6) % 7]) study++;
  const n = units.reduce((a, u) => a + unitCount(u), 0);
  return { deck: doc.deck, dates: units.length, daysOn: new Set(units.map((u) => u.opens)).size, from, to, days, n, perDay: study ? Math.round(n / study) : 0,
    reviews: ((doc.reviews as unknown[]) || []).length, events: ((doc.events as unknown[]) || []).length,
    ids: units.some((u) => u.nids || u.cids) ? 1 : 0 };
}

/** A save's library card: redone from the new doc while it's listed. */
export function keepLib(p: Plan, doc: string): string | null {
  return p.listed === 1 ? JSON.stringify(libCard(JSON.parse(doc))) : (p.lib ?? null);
}

/** 3.2: a follower's own schedule. `days`, Monday first: 0 rest, 1 study,
 *  2 a double share. `minutes` a day; `start` when later than the plan. */
export function schedule(v: unknown): Obj | null {
  if (v === null) return null;
  if (!V.isObj(v)) throw V.bad("sched");
  for (const k of Object.keys(v)) if (!["start", "days", "minutes"].includes(k)) throw V.bad("sched");
  if (!Array.isArray(v.days) || v.days.length !== 7 || !v.days.every((d) => V.isInt(d, 0, 2))
      || !v.days.some((d) => d > 0)) throw V.bad("sched");
  if (!V.isInt(v.minutes, 10, 600)) throw V.bad("sched");
  const out: Obj = { days: v.days, minutes: v.minutes };
  if (v.start !== undefined && v.start !== null) {
    if (!V.isDate(v.start)) throw V.bad("sched");
    out.start = v.start;
  }
  return out;
}

export function planLine(v: unknown): string {
  if (v === undefined || v === null || v === "") return "";
  if (!V.isStr(v, LINE_MAX * 2)) throw V.bad("line");
  return V.oneLine(v, LINE_MAX);
}

// ---- access ----

export async function getPlan(env: Env, id: string): Promise<Plan> {
  const p = await env.DB.prepare("SELECT * FROM plans WHERE id = ?").bind(id).first<Plan>();
  if (!p) throw new HttpError(404, "no_plan");
  return p;
}

async function isMember(env: Env, squad: string | null, uid: string): Promise<boolean> {
  return !!squad && !!(await env.DB.prepare("SELECT 1 FROM members WHERE squad = ? AND uid = ?").bind(squad, uid).first());
}

// a follow as a row: mine only (G3, G4: my shift, my pause's days, my skips)
const FOLLOW_COLS = "share, paused, sched, progress, early, shift, pause_until, pause_since, skipped, hist, team_ask, moved, own";
/** 3.8.0: how a plan's cards open for me: on its dates (null), when I open them, or the next once I've seen the last. */
export const OWN_PACE = ["ready", "next"];

/** 3.7.6: a plan's team and sharing my progress are one choice: on the
 *  team, my progress counts go to its authors; off it, they don't. */
export const TEAM_MAX = 500;        // members of one plan's team

/** A team row whose member may still see the plan: an author, or a
 *  follower (of a squad's plan, while in the squad). Losing that ends what
 *  the team shows of them and to them, without a write. `t` is plan_team.
 *  3.9.5 (the audit's S2): and whose progress counts (COUNTED), by the same rule. */
export const STILL_IN = `(EXISTS (SELECT 1 FROM plans o WHERE o.id = t.plan AND o.owner = t.uid)
  OR EXISTS (SELECT 1 FROM plan_editors e WHERE e.plan = t.plan AND e.uid = t.uid AND e.accepted_at IS NOT NULL)
  OR EXISTS (SELECT 1 FROM plan_follows f JOIN plans fp ON fp.id = f.plan WHERE f.plan = t.plan AND f.uid = t.uid
             AND (fp.audience != 'squad' OR fp.squad IN (SELECT squad FROM members WHERE uid = t.uid))))`;

/** 3.9.5 (the audit's S1, S2): whose progress the counts are made of, for
 *  the authors' Progress and the followers' crew counts alike: a follow
 *  sharing (on the team, 3.7.6) whose follower may still see the plan.
 *  `f` is plan_follows, LEFT JOINed to its team row `t` (WITH_TEAM). */
const WITH_TEAM = "plan_follows f LEFT JOIN plan_team t ON t.plan = f.plan AND t.uid = f.uid";
const COUNTED = `f.share = 1 AND t.uid IS NOT NULL AND ${STILL_IN}`;
/** A date's counts show from this many people counted, on the server too
 *  (the site's Progress has said so since 3.6): fewer, and a count is a person. */
export const COUNTS_MIN = 3;

/** Put me on a plan's team (sharing), or false when it's full. */
export async function joinTeam(env: Env, plan: string, uid: string): Promise<boolean> {
  const on = await env.DB.prepare("SELECT 1 FROM plan_team WHERE plan = ? AND uid = ?").bind(plan, uid).first();
  if (!on) {
    const n = await env.DB.prepare("SELECT COUNT(*) AS n FROM plan_team WHERE plan = ?").bind(plan).first<number>("n");
    if ((n ?? 0) >= TEAM_MAX) return false;
  }
  await env.DB.batch([
    env.DB.prepare("INSERT INTO plan_team (plan, uid, joined_at) VALUES (?, ?, ?) ON CONFLICT DO NOTHING").bind(plan, uid, nowSec()),
    env.DB.prepare("UPDATE plan_follows SET share = 1, team_ask = 0 WHERE plan = ? AND uid = ? AND (share != 1 OR team_ask != 0)").bind(plan, uid),
  ]);
  return true;
}

/** Off a plan's team: my progress stops counting for its authors (it stays
 *  mine, for my own views). Also "No thanks" to the one-time ask. */
export async function leaveTeam(env: Env, plan: string, uid: string): Promise<void> {
  await env.DB.batch([
    env.DB.prepare("DELETE FROM plan_team WHERE plan = ? AND uid = ?").bind(plan, uid),
    env.DB.prepare("UPDATE plan_follows SET share = 0, team_ask = 0 WHERE plan = ? AND uid = ? AND (share != 0 OR team_ask != 0)").bind(plan, uid),
    recount(env, plan),  // 3.9.5: out of the counts now, not in an hour
  ]);
}

async function following(env: Env, plan: string, uid: string) {
  return env.DB.prepare(`SELECT ${FOLLOW_COLS} FROM plan_follows WHERE plan = ? AND uid = ?`).bind(plan, uid).first<Follow>();
}

/** My follow's own days, as the add-on and the site read them. */
function followDays(f: { shift?: number | null; pause_until?: string | null; pause_since?: string | null; skipped?: string | null;
                         moved?: string | null; own?: string | null }) {
  return { shift: f.shift ?? 0, until: f.pause_until ?? null, since: f.pause_since ?? null,
    skipped: f.skipped ? JSON.parse(f.skipped) as string[] : [],
    moved: f.moved ? JSON.parse(f.moved) as Record<string, number> : {},  // 3.7.6: one date later, days
    ...(f.own && OWN_PACE.includes(f.own) ? { own: f.own } : {}) };  // 3.8.0: at my own pace
}

/** Who may see a plan: its author, its followers, and whoever may follow it. */
async function mayRead(env: Env, p: Plan, uid: string, code?: string): Promise<boolean> {
  // 3.8.1: someone asked to co-write it may look before saying yes
  if (p.owner === uid || (await env.DB.prepare("SELECT 1 FROM plan_editors WHERE plan = ? AND uid = ?").bind(p.id, uid).first())) return true;
  if (p.audience === "squad") return isMember(env, p.squad, uid);  // leaving the squad ends it, follow or not
  if (p.listed === 1) return true;  // 3.5, B: in the library, for anyone signed in
  if (await following(env, p.id, uid)) return true;
  return (!!code && normalizeCode(code) === p.code) || isMember(env, p.squad, uid);
}

/** 3.3: the owner and co-authors edit; the owner alone deletes, picks the
 *  audience and the co-authors. 3.8.1: a co-author is one who said yes
 *  (accepted_at); until then a plan_editors row is an invite, and nothing more. */
export async function isEditor(env: Env, plan: string, uid: string): Promise<boolean> {
  return !!(await env.DB.prepare("SELECT 1 FROM plan_editors WHERE plan = ? AND uid = ? AND accepted_at IS NOT NULL").bind(plan, uid).first());
}

/** The plans I co-author (said yes to), as SQL; ?1 is my uid. */
export const COAUTHORED = "SELECT plan FROM plan_editors WHERE uid = ?1 AND accepted_at IS NOT NULL";

async function authorOnly(env: Env, id: string, s: Session): Promise<Plan> {
  const p = await getPlan(env, id);
  if (p.owner !== s.uid && !(await isEditor(env, id, s.uid))) throw new HttpError(403, "not_author");
  return p;
}

export async function role(env: Env, p: Plan, uid: string): Promise<"owner" | "editor" | "follower" | "reader"> {
  if (p.owner === uid) return "owner";
  if (await isEditor(env, p.id, uid)) return "editor";
  // a squad plan's follower is a member still (mayRead): leaving ends it
  if (await following(env, p.id, uid) && (p.audience !== "squad" || await isMember(env, p.squad, uid))) return "follower";
  return "reader";
}

async function ownerOnly(env: Env, id: string, s: Session): Promise<Plan> {
  const p = await getPlan(env, id);
  if (p.owner !== s.uid) throw new HttpError(403, "not_author");
  return p;
}

type Follow = { share: number; paused: number; sched: string | null; progress: string | null; early: number;
  shift: number; pause_until: string | null; pause_since: string | null; skipped: string | null; hist?: string | null;
  moved?: string | null; own?: string | null;
  team_ask?: number };
type Editor = { uid: string; name: string; emoji: string; pending?: true };
type EditorRow = { plan: string; uid: string; name: string | null; emoji: string | null; accepted_at: number | null };
const editorOf = (e: EditorRow): Editor => ({ uid: e.uid, name: e.name || "?", emoji: e.emoji || "", ...(e.accepted_at === null ? { pending: true as const } : {}) });

/** A plan as its page shows it. What it needs about me comes in `ctx`, so
 *  a list of plans reads it in a few queries, not a few per plan. 3.8.1:
 *  `editors` holds the invites too (pending); only its authors see those,
 *  and who the owner offered it to (`handover`). */
function shape(p: Plan & { owner_name?: string | null }, uid: string, doc: unknown,
               ctx: { f: Follow | null; n: number; editors: Editor[]; mySquads: Set<string> }) {
  const { f } = ctx;
  const said = ctx.editors.filter((e) => !e.pending);
  const r = p.owner === uid ? "owner" : said.some((e) => e.uid === uid) ? "editor" : f ? "follower" : "reader";
  const authors = r === "owner" || r === "editor";
  return {
    role: r, editors: authors ? ctx.editors : said,
    ...(authors && p.handover ? { handover: p.handover } : {}),
    id: p.id, name: p.name, line: p.line, owner: p.owner, ownerName: p.owner_name || (p.owner ? "?" : "a former member"),
    audience: p.audience, version: p.version, doc, followers: ctx.n,
    // which squad it's offered to: only for the author and that squad's members (an id is not an invite)
    squad: p.owner === uid || (!!p.squad && ctx.mySquads.has(p.squad)) ? p.squad : null,
    ...(r === "owner" || r === "editor" || (r === "follower" && p.audience === "code") || p.listed === 1 ? { code: p.code } : {}),
    // 3.5, B: in the library (the code shows there); the authors also see if the admin took it out, and why
    library: p.listed === 1,
    ...(r === "owner" || r === "editor" ? { listed: p.listed ?? 0, ...(p.listed === -1 ? { listedNote: p.listed_note || "" } : {}) } : {}),
    ...(p.based_on ? { basedOn: JSON.parse(p.based_on) } : {}),
    // mine only: my schedule, and my own progress (3.2's on-track line on the site)
    ...(f ? { following: { share: f.share === 1, ...(f.team_ask === 1 ? { teamAsk: true } : {}), paused: f.paused === 1, sched: f.sched ? JSON.parse(f.sched) : null, early: f.early ?? 0,
                           progress: f.progress ? JSON.parse(f.progress) : null, ...followDays(f),
                           // 3.5, L: my own history on this plan, for my log
                           hist: f.hist ? JSON.parse(f.hist) : {} } } : {}),
  };
}

// D1 binds at most 100 parameters: ids go 90 at a time (one person can be
// in more than 100 plans: 50 owned, 20 followed, any number co-authored)
async function inChunks<T>(ids: string[], q: (part: string[]) => Promise<{ results: T[] }>): Promise<{ results: T[] }> {
  const results: T[] = [];
  for (let i = 0; i < ids.length; i += 90) results.push(...(await q(ids.slice(i, i + 90))).results);
  return { results };
}

const editorsOf = (env: Env, ids: string[]) => inChunks(ids, (part) => env.DB.prepare(
  `SELECT e.plan, e.uid, u.name, u.emoji, e.accepted_at FROM plan_editors e JOIN users u ON u.uid = e.uid
    WHERE e.plan IN (${part.map(() => "?").join(",")}) ORDER BY e.at`,
).bind(...part).all<EditorRow>());

/** A plan's totals (migration 0025), as its readers show them: `n` follow
 *  it, `m` of them not its owner, `r` of those have version `v` in their
 *  Anki (3.7.3), and `done` per date, how many on its team have every card
 *  of it seen. Counts, never who. */
export type Totals = { v: number; n: number; m: number; r: number; done: Record<string, number>; s: number };

/** 3.9.5 (the audit's S2): a plan's kept totals are counted again at the next
 *  read, when someone's place in its counts ended (left the team, unfollowed,
 *  a co-author removed). Squads (squads.ts, adminsquads.ts) and deleting an
 *  account (auth.ts) say it for the plans they touch. Writes only a row that holds totals. */
export const recount = (env: Env, plan: string) =>
  env.DB.prepare("UPDATE plans SET totals_at = NULL WHERE id = ? AND totals_at IS NOT NULL").bind(plan);
type Counted = { id: string; version: number; owner: string | null; totals?: string | null; totals_at?: number | null };

/** One total per plan, kept on its row: a board, a plan's page, my list of
 *  plans and the library read that row, not every follower's (a library
 *  plan's can be thousands). Under an hour old it's used as it is, so what
 *  it shows is up to an hour behind; older, it's worked out again from every
 *  follow of the stale plans (90 plans a query) and kept. Mine alone (my
 *  progress, my follow) is never from here, and stays live where it's shown.
 *  A save since the count moved the version: none have it yet, as at that save. */
export async function totals(env: Env, plans: Counted[]): Promise<Map<string, Totals>> {
  const now = nowSec();
  const out = new Map<string, Totals>();
  const stale: Counted[] = [];
  for (const p of plans) {
    let t: Totals | null = null;
    if (p.totals && (p.totals_at ?? 0) > now - TOTALS_EVERY) {
      try { t = JSON.parse(p.totals) as Totals; } catch { t = null; }
      if (t && typeof t.s !== "number") t = null;  // 3.9.5: kept before COUNTED; count again
    }
    if (t) out.set(p.id, t.v === p.version ? t : { ...t, v: p.version, r: 0 });
    else if (!out.has(p.id) && !stale.some((x) => x.id === p.id)) stale.push(p);
  }
  if (!stale.length) return out;
  const fresh = new Map<string, Totals>(stale.map((p) => [p.id, { v: p.version, n: 0, m: 0, r: 0, done: {}, s: 0 }]));
  const owners = new Map(stale.map((p) => [p.id, p.owner ?? ""]));
  // 3.9.5 (the audit's E2): progress only for the follows that count; nobody else's is read to be skipped
  const rows = await inChunks(stale.map((p) => p.id), (part) => env.DB.prepare(
    `SELECT f.plan, f.uid, f.seen_version, CASE WHEN ${COUNTED} THEN f.progress END AS progress
       FROM ${WITH_TEAM} WHERE f.plan IN (${part.map(() => "?").join(",")})`,
  ).bind(...part).all<{ plan: string; uid: string; progress: string | null; seen_version: number | null }>());
  for (const r of rows.results) {
    const t = fresh.get(r.plan)!;
    t.n++;
    if (r.uid !== owners.get(r.plan)) {
      t.m++;
      if (r.seen_version === t.v) t.r++;
    }
    if (r.progress) {
      t.s++;
      for (const [u, [, seen, total]] of Object.entries(JSON.parse(r.progress) as Record<string, number[]>)) {
        if (total > 0 && seen >= total) t.done[u] = (t.done[u] ?? 0) + 1;
      }
    }
  }
  for (const t of fresh.values()) if (t.s < COUNTS_MIN) t.done = {};  // 3.9.5 (S1): under three, no date's count
  // Kept with its time, once an hour at most per plan: the time has to move
  // even when the counts didn't, or every read would count again. Only the
  // stale row is written (two readers at once write it once), and a plan no
  // one follows, with nothing kept, isn't written at all (counting it reads nothing).
  const keep = stale.filter((p) => fresh.get(p.id)!.n || p.totals);
  if (keep.length) {
    await env.DB.batch(keep.map((p) => env.DB.prepare(
      "UPDATE plans SET totals = ?1, totals_at = ?2 WHERE id = ?3 AND (totals_at IS NULL OR totals_at <= ?4)",
    ).bind(JSON.stringify(fresh.get(p.id)), now, p.id, now - TOTALS_EVERY)));
  }
  for (const [id, t] of fresh) out.set(id, t);
  return out;
}

export async function view(env: Env, p: Plan, uid: string) {
  const [[f, eds, owner, member], tot] = await Promise.all([env.DB.batch<any>([
    env.DB.prepare(`SELECT ${FOLLOW_COLS} FROM plan_follows WHERE plan = ? AND uid = ?`).bind(p.id, uid),
    env.DB.prepare(`SELECT e.plan, e.uid, u.name, u.emoji, e.accepted_at FROM plan_editors e JOIN users u ON u.uid = e.uid WHERE e.plan = ? ORDER BY e.at`).bind(p.id),
    env.DB.prepare("SELECT name FROM users WHERE uid = ?").bind(p.owner),
    env.DB.prepare("SELECT squad FROM members WHERE squad = ? AND uid = ?").bind(p.squad ?? "", uid),
  ]), totals(env, [p])]);
  const t = tot.get(p.id)!;
  const out = shape({ ...p, owner_name: owner.results[0]?.name }, uid, JSON.parse(p.doc), {
    f: (f.results[0] as Follow) ?? null, n: t.n,
    editors: eds.results.map((e: any) => editorOf(e)),
    mySquads: new Set(member.results.map((m: any) => m.squad)),
  });
  // 3.7.3: the authors see "reached 18 of 23": followers whose Anki has this version (a count).
  // Counted live for them (only authors open this, now and then): the plan's totals are up to
  // an hour old, and after a save "reached" is what an author comes back to watch climb.
  if (out.role !== "owner" && out.role !== "editor") return out;
  const c = await env.DB.prepare(
    "SELECT COUNT(*) AS m, COALESCE(SUM(CASE WHEN seen_version = ?1 THEN 1 ELSE 0 END), 0) AS r FROM plan_follows WHERE plan = ?2 AND uid != ?3",
  ).bind(p.version, p.id, p.owner ?? "").first<{ m: number; r: number }>();
  return { ...out, reached: [c?.r ?? t.r, c?.m ?? t.m] };
}

// ---- the deck's tree, from the add-on ----

/** A tree as the add-on sends it since 3.3: nested, each name once,
 *  [name, n, [children]?]; paths (the names joined by ::) up to PATH_MAX. */
function nested(v: unknown, budget: { nodes: number }, prefix = 0, depth = 0): unknown[] {
  if (!Array.isArray(v) || depth > NEST_DEPTH) throw V.bad("tree");
  return v.map((x) => {
    if (!Array.isArray(x) || x.length < 2 || x.length > 3 || !V.isInt(x[1])) throw V.bad("tree");
    const name = x[0];
    if (!V.isStr(name, PATH_MAX, 1) || /[\u0000-\u001f]/.test(name) || name.includes("::")) throw V.bad("tree");
    const len = prefix + (prefix ? 2 : 0) + name.length;
    if (len > PATH_MAX || --budget.nodes < 0) throw V.bad("tree");
    return x.length === 3 ? [name, x[1], nested(x[2], budget, len, depth + 1)] : [name, x[1]];
  });
}

/** PUT /plans/trees {deck, tags, decks}: names and counts only. 3.3 sends
 *  them nested ({v: 2}); 3.1 and 3.2 send [[path, n]] lists. */
export async function putTree(req: Request, s: Session, env: Env): Promise<Response> {
  const body = await readJson(req, TREE_BODY_MAX);
  const deck = path(body.deck);
  const list = (v: unknown) => {
    if (!Array.isArray(v) || v.length > TREE_MAX) throw V.bad("tree");
    return v.map((x) => {
      if (!Array.isArray(x) || x.length !== 2 || !V.isInt(x[1])) throw V.bad("tree");
      return [path(x[0]), x[1]];
    });
  };
  let doc: string;
  if (body.v === 2) {
    const budget = { nodes: NEST_MAX };
    doc = JSON.stringify({ v: 2, tags: nested(body.tags ?? [], budget), decks: nested(body.decks ?? [], budget) });
  } else {
    doc = JSON.stringify({ tags: list(body.tags ?? []), decks: list(body.decks ?? []) });
  }
  await limitOrThrow(env, `tree:${s.uid}`, 30, 3600);
  // the oldest trees make room, by count and (3.7.2) by size: a tree is only
  // ever the latest upload, and the add-on sends it again when it's needed
  const others = (await env.DB.prepare("SELECT deck, LENGTH(doc) AS n FROM plan_trees WHERE uid = ? AND deck != ? ORDER BY at DESC")
    .bind(s.uid, deck).all<{ deck: string; n: number }>()).results;
  let kept = 0, bytes = doc.length;
  const drop: string[] = [];
  for (const t of others) {
    if (kept + 1 >= TREES_MAX || bytes + t.n > TREES_BYTES) drop.push(t.deck);
    else { kept++; bytes += t.n; }
  }
  if (drop.length) {
    await env.DB.batch(drop.map((d) => env.DB.prepare("DELETE FROM plan_trees WHERE uid = ? AND deck = ?").bind(s.uid, d)));
  }
  const now = nowSec();
  await env.DB.prepare(
    `INSERT INTO plan_trees (uid, deck, doc, at) VALUES (?, ?, ?, ?)
     ON CONFLICT(uid, deck) DO UPDATE SET doc = excluded.doc, at = excluded.at WHERE plan_trees.doc != excluded.doc`,
  ).bind(s.uid, deck, doc, now).run();
  return json({ ok: true });
}

/** GET /plans/trees?deck=: that deck's tree, for the builder; without a
 *  deck, which decks I have trees for (names and when, not the trees). */
export async function getTrees(req: Request, s: Session, env: Env): Promise<Response> {
  const deck = new URL(req.url).searchParams.get("deck");
  if (deck !== null) {
    const r = await env.DB.prepare("SELECT deck, doc, at FROM plan_trees WHERE uid = ? AND deck = ?").bind(s.uid, deck)
      .first<{ deck: string; doc: string; at: number }>();
    return json({ trees: r ? [{ deck: r.deck, at: r.at, ...JSON.parse(r.doc) }] : [] });
  }
  const rows = await env.DB.prepare("SELECT deck, at FROM plan_trees WHERE uid = ? ORDER BY at DESC").bind(s.uid)
    .all<{ deck: string; at: number }>();
  return json({ trees: rows.results });
}

// ---- authoring ----

/** POST /plans {name, deck, line?}: a new plan, no units yet; I'm its author. */
export async function create(req: Request, s: Session, env: Env): Promise<Response> {
  const body = await readJson(req);
  const name = V.displayName(body.name);
  const doc = JSON.stringify(planDoc({ deck: body.deck, units: [] }));
  const line = planLine(body.line);
  await limitOrThrow(env, `plannew:${s.uid}`, 20, 3600);
  const mine = await env.DB.prepare("SELECT COUNT(*) AS n FROM plans WHERE owner = ?").bind(s.uid).first<number>("n");
  if ((mine ?? 0) >= PLANS_MAX) throw new HttpError(409, "too_many_plans");
  const now = nowSec();
  for (let i = 0; i < 3; i++) {
    const id = draw(16).toLowerCase();
    const code = draw(PLAN_CODE_LEN);
    const r = await env.DB.prepare(
      `INSERT INTO plans (id, code, owner, name, line, doc, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING`,
    ).bind(id, code, s.uid, name, line, doc, now, now).run();
    if (r.meta.changes) return json(await view(env, await getPlan(env, id), s.uid));
  }
  throw new HttpError(503, "try_again");
}

/** GET /plans/{id}[?code=]: the plan, for whoever may see it. */
export async function get(req: Request, s: Session, env: Env, [id]: string[]): Promise<Response> {
  const p = await getPlan(env, id);
  if (!(await mayRead(env, p, s.uid, new URL(req.url).searchParams.get("code") || undefined))) throw new HttpError(404, "no_plan");
  return json(await view(env, p, s.uid));
}

/** GET /plans/peek?code=: the plan behind a code, before following. 60 an hour. */
export async function peek(req: Request, s: Session, env: Env): Promise<Response> {
  await limitOrThrow(env, `planpeek:${s.uid}`, 60, 3600);
  const code = normalizeCode(new URL(req.url).searchParams.get("code") || "");
  const p = code.length === PLAN_CODE_LEN
    ? await env.DB.prepare("SELECT * FROM plans WHERE code = ?").bind(code).first<Plan>() : null;
  if (!p || !(await mayRead(env, p, s.uid, code))) throw new HttpError(404, "no_plan");
  return json(await view(env, p, s.uid));
}

/** PUT /plans/{id} {version, name?, line?, audience?, squad?, doc?}: the
 *  author's save. A stale version is refused with the current one. */
/** 3.6.5: `idr` and `pn` come only from the author's Anki (PUT
 *  /plans/{id}/ids): a save keeps a date's as stored while what they were
 *  worked out from is unchanged, and drops them when it changes (the next
 *  morning works them out again). So do a date's `ids` (3.3, C5: the note
 *  ids behind its tags, subdecks and cuts in the author's Anki): kept as
 *  stored while those are, never as a save sends them, so a follower whose
 *  copy lacks a tag the date has now doesn't fall back to the notes of the
 *  one it had. The builder only ever sends them back as it got them. */
export function keepIdr(doc: Obj, was: string | null): Obj {
  const old = new Map(((was ? JSON.parse(was).units : []) as Obj[]).map((u) => [u.id, u]));
  const same = (a: unknown, b: unknown) => JSON.stringify(a ?? []) === JSON.stringify(b ?? []);
  const picks = (u: Obj) => [u.opens, u.tags, u.decks, u.search, u.nids, u.cids, u.notes];
  const from = (u: Obj) => [u.tags, u.decks, ((u.cut as Obj[] | undefined) || []).map((c) => [c.tag, c.in])];
  for (const u of doc.units as Obj[]) {
    const o = old.get(u.id);
    delete u.idr;
    delete u.pn;
    delete u.ids;
    delete u.pl;
    if (o?.idr && same(o.nids, u.nids) && same(o.cids, u.cids)) u.idr = o.idr;
    if (o?.pn && same(picks(o), picks(u))) u.pn = o.pn;
    if (o?.ids && same(from(o), from(u))) u.ids = o.ids;
    // 3.8.1: what its picked cards are, while they're the same cards
    if (o?.pl && same(picksOf(o), picksOf(u))) u.pl = o.pl;
  }
  return doc;
}

/** 3.8.1: a date whose picks changed (cards added in Anki) loses its `pl`;
 *  the author's Anki names them again. */
function stalePl(doc: Obj, was: string) {
  const old = new Map(((JSON.parse(was).units || []) as Obj[]).map((u) => [u.id, u]));
  for (const u of doc.units as Obj[]) {
    const o = old.get(u.id);
    if (u.pl && (!o || JSON.stringify(picksOf(o)) !== JSON.stringify(picksOf(u)))) delete u.pl;
  }
  return doc;
}

/** 3.7.2: room for a save Undo can take back: the new doc and library card
 *  less the old card and the copy Undo held before (it goes); the doc it
 *  replaces stays, as Undo's copy. */
async function roomForSave(env: Env, p: Plan, doc: string, lib: string | null) {
  const held = await env.DB.prepare("SELECT LENGTH(prev) AS n FROM plan_log WHERE plan = ? AND prev IS NOT NULL").bind(p.id).first<number>("n");
  await roomFor(env, p.owner, doc.length + (lib?.length ?? 0) - (p.lib?.length ?? 0) - (held ?? 0));
}

/** 3.7.3: a line to followers that came with a save. The save stands either
 *  way; a post past the day's ceiling is said, not lost silently. */
async function postWithSave(env: Env, p: Plan, uid: string, raw: unknown, version: number | null) {
  try { return await writePost(env, p, uid, raw, version); }
  catch (e) { if (e instanceof HttpError && e.status === 429) return { error: "too_many_posts" }; throw e; }
}

export async function put(req: Request, s: Session, env: Env, [id]: string[]): Promise<Response> {
  const p = await authorOnly(env, id, s);
  // 3.7.1 review: what one account can make the server keep has a ceiling
  await limitOrThrow(env, `planput:${s.uid}`, 500, 86400);
  const body = await readJson(req, PLAN_BODY_MAX);
  for (const k of Object.keys(body)) if (!["version", "name", "line", "audience", "squad", "doc", "summary", "post"].includes(k)) throw V.bad("plan");
  // 3.7.3: a line to followers with the save; checked before anything is written
  if (body.post !== undefined && (!V.isStr(body.post, POST_MAX * 4, 1) || !V.oneLine(body.post as string, POST_MAX))) throw V.bad("post");
  if (p.owner !== s.uid && ((body.audience !== undefined && body.audience !== p.audience)
      || (body.squad !== undefined && body.squad !== p.squad))) throw new HttpError(403, "not_owner");
  const summary = body.summary === undefined ? "" : V.oneLine(String(body.summary), SUMMARY_MAX);
  if (!V.isInt(body.version, 1)) throw V.bad("version");
  const next = {
    name: body.name !== undefined ? V.displayName(body.name) : p.name,
    line: body.line !== undefined ? planLine(body.line) : p.line,
    audience: p.audience,
    squad: p.squad,
    doc: p.doc,
    tagroot: p.tagroot ?? null,
  };
  if (body.doc !== undefined) {
    // 3.8.0: its tags' root is its own; then what only the author's Anki
    // sends is kept as stored, compared with the dates under that root
    const r = await rooted(env, id, p.tagroot, planDoc(body.doc));
    next.doc = JSON.stringify(keepIdr(r.doc, p.doc));
    next.tagroot = r.root;
  }
  if (body.audience !== undefined) {
    if (body.audience !== "code" && body.audience !== "squad") throw V.bad("audience");
    next.audience = body.audience;
  }
  if (body.squad !== undefined) {
    if (body.squad !== null && (!V.isStr(body.squad, 64, 1) || !(await isMember(env, body.squad, s.uid)))) throw V.bad("squad");
    next.squad = body.squad;
  }
  if (next.audience === "squad" && !next.squad) throw V.bad("squad");
  if (next.name === p.name && next.line === p.line && next.audience === p.audience
      && next.squad === p.squad && next.doc === p.doc) {
    // nothing changed: nothing written but its post, which goes all the same
    // (a post on its own: there's no new version for it to come with)
    const posted = body.post !== undefined ? await postWithSave(env, p, s.uid, body.post, null) : undefined;
    return json({ ...(await view(env, p, s.uid)), ...(posted ? { posted } : {}) });
  }
  // 3.5, B: a plan for one squad leaves the library; a listed plan's card follows its doc
  const listed = next.audience === "squad" && p.listed === 1 ? 0 : (p.listed ?? 0);
  const lib = listed === 1 && next.doc !== p.doc ? JSON.stringify(libCard(JSON.parse(next.doc))) : (p.lib ?? null);
  if (next.doc !== p.doc) await roomForSave(env, p, next.doc, lib);  // 3.7.2
  // 3.9.5: and out of the library, out of the starters (the admin's mark is kept while it's listed);
  // another audience or squad changes who may see it, so its kept totals are counted again (S2)
  const moved = next.audience !== p.audience || (next.squad ?? null) !== (p.squad ?? null) ? 1 : 0;
  const r = await env.DB.prepare(
    `UPDATE plans SET name = ?, line = ?, audience = ?, squad = ?, doc = ?, listed = ?, lib = ?, tagroot = ?, version = version + 1, updated_at = ?,
            starter = CASE WHEN ? = 1 THEN starter ELSE 0 END, totals_at = CASE WHEN ? = 1 THEN NULL ELSE totals_at END
     WHERE id = ? AND version = ?`,
  ).bind(next.name, next.line, next.audience, next.squad, next.doc, listed, lib, next.tagroot, nowSec(), listed, moved, id, body.version).run().catch(rootTaken);
  if (!r.meta.changes) throw new HttpError(409, "stale", { version: (await getPlan(env, id)).version });
  await logSave(env, id, (body.version as number) + 1, s.uid, summary || "changed the plan", next.doc !== p.doc ? p.doc : null);
  const posted = body.post !== undefined ? await postWithSave(env, p, s.uid, body.post, (body.version as number) + 1) : undefined;
  return json({ ...(await view(env, await getPlan(env, id), s.uid)), ...(posted ? { posted } : {}) });
}

/** One row of the plan's history: who saved, what they said it did, and
 *  the doc it replaced (for Undo). The last LOG_KEEP stay; only the latest
 *  keeps its doc, since Undo only ever puts back the latest save's (3.7.2). */
const PREV_KEEP = 1;

/** 3.7.2: the bytes an owner's plans keep (PLAN_BYTES_MAX). */
export async function ownerBytes(env: Env, owner: string): Promise<number> {
  const r = await env.DB.prepare(
    `SELECT COALESCE(SUM(LENGTH(doc) + COALESCE(LENGTH(lib), 0)), 0)
       + COALESCE((SELECT SUM(LENGTH(l.prev)) FROM plan_log l JOIN plans q ON q.id = l.plan
                   WHERE q.owner = ?1 AND l.prev IS NOT NULL), 0) AS n
     FROM plans WHERE owner = ?1`,
  ).bind(owner).first<number>("n");
  return r ?? 0;
}

export async function roomFor(env: Env, owner: string | null, grow: number) {
  if (!owner || grow <= 0) return;
  if ((await ownerBytes(env, owner)) + grow > PLAN_BYTES_MAX) throw new HttpError(409, "plans_full");
}

export async function logSave(env: Env, plan: string, version: number, uid: string, summary: string, prev: string | null) {
  await env.DB.batch([
    env.DB.prepare("INSERT OR REPLACE INTO plan_log (plan, version, uid, at, summary, prev) VALUES (?, ?, ?, ?, ?, ?)")
      .bind(plan, version, uid, nowSec(), summary, prev),
    env.DB.prepare("DELETE FROM plan_log WHERE plan = ? AND version <= ?").bind(plan, version - LOG_KEEP),
    // Undo only ever puts back the latest save's; the older rows keep who and
    // what, not a whole doc each (up to 1.5 MB), so a plan's history stays small
    env.DB.prepare("UPDATE plan_log SET prev = NULL WHERE plan = ? AND version <= ? AND prev IS NOT NULL").bind(plan, version - PREV_KEEP),
  ]);
}

/** PUT /plans/{id}/ids {units: {unitId: [tags, decks, [guid]]}}: 3.3, C5.
 *  An author's Anki keeps the note ids behind each date's tags and
 *  subdecks, so a follower whose copy of the deck renamed a tag still gets the date.
 *  A unit's ids are taken only while its tags and subdecks are still the
 *  ones they were read from. Never a history entry; a new version. */
export async function putIds(req: Request, s: Session, env: Env, [id]: string[]): Promise<Response> {
  const p = await authorOnly(env, id, s);
  // an author's Anki sends these by itself, at most once a day a plan (per
  // computer): a bucket of its own, far over that, so it never eats the
  // saves' (planput) nor they it
  await limitOrThrow(env, `planids:${s.uid}`, 500, 86400);
  const body = await readJson(req, PLAN_BODY_MAX);
  if (!V.isObj(body.units) || Object.keys(body).some((k) => !["units", "counts", "refs"].includes(k))) throw V.bad("ids");
  if (body.counts !== undefined && !V.isObj(body.counts)) throw V.bad("ids");
  if (body.refs !== undefined && !V.isObj(body.refs)) throw V.bad("ids");
  const doc = JSON.parse(p.doc) as Obj & { units: Obj[] };
  const same = (a: unknown, b: unknown) => JSON.stringify(a ?? []) === JSON.stringify(b ?? []);
  for (const [uid, v] of Object.entries(body.units)) {
    if (!Array.isArray(v) || (v.length !== 3 && v.length !== 4) || !Array.isArray(v[2])) throw V.bad("ids");
    const u = doc.units.find((x) => x.id === uid);
    if (!u || !same(u.tags, v[0]) || !same(u.decks, v[1])) continue;  // changed since: the next refresh sends it again
    // 3.8.1: and its cuts, [[tag, in]], from an add-on that knows them
    if (v.length === 4 && !same(((u.cut as Obj[] | undefined) || []).map((c) => [c.tag, c.in]), v[3])) continue;
    if (v[2].length) u.ids = v[2]; else delete u.ids;
  }
  // 3.6.5: the cards a date's pasted ids are here, as guid + card number,
  // kept only while its ids are still the ones they were worked out from
  for (const [uid, v] of Object.entries((body.refs as Obj) || {})) {
    if (!Array.isArray(v) || v.length !== 3 || !Array.isArray(v[2])) throw V.bad("ids");
    const u = doc.units.find((x) => x.id === uid);
    if (!u || !same(u.nids, v[0]) || !same(u.cids, v[1])) continue;
    if (v[2].length) u.idr = v[2]; else delete u.idr;
  }
  // 3.4, D1: how many cards each of a date's searches finds in my copy
  for (const [uid, v] of Object.entries((body.counts as Obj) || {})) {
    const u = doc.units.find((x) => x.id === uid);
    if (!u || !V.isObj(v)) continue;
    const qs = (u.search as string[]) || [];
    const sn: Obj = { ...((u.sn as Obj) || {}) };
    for (const [q, n] of Object.entries(v)) {
      // E1: "#ids" is how many cards the date's pasted ids found
      if (q === "#ids") { if ((u.nids || u.cids || u.notes) && V.isInt(n, 0, 1_000_000)) u.idn = n; continue; }
      // 3.6.5, P1: new to this date, already on an earlier one, picked notes not in the deck
      if (q === "#pn") { if (Array.isArray(n) && n.length === 3 && n.every((x) => V.isInt(x, 0, 1_000_000))) u.pn = n; continue; }
      // 3.8.1: the deck tags its picked cards sit under here, with how many;
      // kept as the date's `pl` while its picks are the same (keepIdr). Only
      // that shape is kept, and only on a date with picks; anything else is skipped
      if (q === "#lbl") {
        const pl = labels(n);
        if (pl && hasPicks(u)) { if (pl.length) u.pl = pl; else delete u.pl; }
        continue;
      }
      if (!qs.includes(q) || !V.isInt(n, 0, 1_000_000)) continue;  // a search taken off since: skipped
      sn[q] = n;
    }
    if (Object.keys(sn).length) u.sn = sn;
  }
  const clean = JSON.stringify(planDoc(doc));
  if (clean === p.doc) return json({ version: p.version });
  const lib = keepLib(p, clean);
  await roomFor(env, p.owner, clean.length - p.doc.length + (lib?.length ?? 0) - (p.lib?.length ?? 0));  // 3.7.2: no Undo copy
  const r = await env.DB.prepare("UPDATE plans SET doc = ?, lib = ?, version = version + 1, updated_at = ? WHERE id = ? AND version = ?")
    .bind(clean, lib, nowSec(), id, p.version).run();
  if (!r.meta.changes) throw new HttpError(409, "stale", { version: (await getPlan(env, id)).version });
  return json({ version: p.version + 1 });
}

/** GET /plans/{id}/log: the history, newest first, for the authors. Undo is
 *  on the newest row, while it holds the doc its save replaced. Not "the row
 *  of the plan's version": an upload from the author's Anki (PUT /ids) moves
 *  the version and writes no row (it's no one's save, nothing to undo), and
 *  it runs by itself each day, so Undo would go every time Anki opened.
 *  Every other change to a doc writes its row. */
export async function log(s: Session, env: Env, [id]: string[]): Promise<Response> {
  await authorOnly(env, id, s);
  const rows = await env.DB.prepare(
    `SELECT l.version, l.uid, l.at, l.summary, l.prev IS NOT NULL AS undoable, u.name FROM plan_log l
       LEFT JOIN users u ON u.uid = l.uid WHERE l.plan = ? ORDER BY l.version DESC LIMIT ?`,
  ).bind(id, LOG_KEEP).all<{ version: number; uid: string; at: number; summary: string; undoable: number; name: string | null }>();
  return json({ log: rows.results.map((r, i) => ({ version: r.version, uid: r.uid, name: r.name || "?", at: r.at, summary: r.summary,
    undo: i === 0 && r.undoable === 1 })) });
}

/** POST /plans/{id}/undo {version}: puts back what the latest save replaced
 *  (the newest row, as the log offers it), whatever ids the author's Anki
 *  sent since: they were worked out from the doc Undo replaces, and that
 *  Anki sends them again when the doc it reads changes. `version` is the
 *  plan's as I read it: another author's save since is refused (409). */
export async function undo(req: Request, s: Session, env: Env, [id]: string[]): Promise<Response> {
  const p = await authorOnly(env, id, s);
  await limitOrThrow(env, `planput:${s.uid}`, 500, 86400);  // a save, as far as the ceiling goes
  const body = await readJson(req);
  if (body.version !== p.version) throw new HttpError(409, "stale", { version: p.version });
  const row = await env.DB.prepare("SELECT summary, prev FROM plan_log WHERE plan = ? ORDER BY version DESC LIMIT 1").bind(id)
    .first<{ summary: string; prev: string | null }>();
  if (!row || !row.prev) throw new HttpError(404, "nothing_to_undo");
  const r = await env.DB.prepare("UPDATE plans SET doc = ?, lib = ?, version = version + 1, updated_at = ? WHERE id = ? AND version = ?")
    .bind(row.prev, keepLib(p, row.prev), nowSec(), id, p.version).run();
  if (!r.meta.changes) throw new HttpError(409, "stale", { version: (await getPlan(env, id)).version });
  await logSave(env, id, p.version + 1, s.uid, V.oneLine(`undid: ${row.summary}`, SUMMARY_MAX), p.doc);
  return json(await view(env, await getPlan(env, id), s.uid));
}

// ---- co-authors ----

/** POST /plans/{id}/editors {uid}: the owner asks someone from their crew
 *  (a mutual friend) to co-write it. 3.8.1: an invite (accepted_at NULL)
 *  until they say yes (POST /plans/{id}/invite); invites count toward the
 *  plan's EDITORS_MAX. Asking a co-author again changes nothing. */
export async function addEditor(req: Request, s: Session, env: Env, [id]: string[]): Promise<Response> {
  const p = await ownerOnly(env, id, s);
  // 3.8.1: an invite moves its invitee's stamp (their next refresh brings every plan again): a ceiling
  await limitOrThrow(env, `planinvite:${s.uid}`, 30, 86400);
  const body = await readJson(req);
  if (!V.isStr(body.uid, 128, 1) || body.uid === s.uid) throw V.bad("editor");
  const mutual = await env.DB.prepare(
    "SELECT 1 FROM friends a JOIN friends b ON b.owner = a.friend AND b.friend = a.owner WHERE a.owner = ? AND a.friend = ?",
  ).bind(s.uid, body.uid).first();
  if (!mutual) throw new HttpError(403, "not_crew");
  const n = await env.DB.prepare("SELECT COUNT(*) AS n FROM plan_editors WHERE plan = ?").bind(id).first<number>("n");
  if ((n ?? 0) >= EDITORS_MAX) throw new HttpError(409, "too_many_editors");
  await env.DB.prepare("INSERT INTO plan_editors (plan, uid, at) VALUES (?, ?, ?) ON CONFLICT DO NOTHING").bind(id, body.uid, nowSec()).run();
  return json(await view(env, p, s.uid));
}

/** DELETE /plans/{id}/editors/{uid}: the owner removes a co-author or takes
 *  back an invite, or anyone leaves (or says no). 3.8.1: the plan offered to
 *  them isn't any more. */
export async function removeEditor(s: Session, env: Env, [id, uid]: string[]): Promise<Response> {
  const p = await getPlan(env, id);
  if (p.owner !== s.uid && uid !== s.uid) throw new HttpError(403, "not_owner");
  await env.DB.batch([
    env.DB.prepare("DELETE FROM plan_editors WHERE plan = ? AND uid = ?").bind(id, uid),
    env.DB.prepare("UPDATE plans SET handover = NULL WHERE id = ? AND handover = ?").bind(id, uid),
    recount(env, id),  // 3.9.5: a squad's plan may be out of their sight now
  ]);
  return json({ ok: true });
}

/** POST /plans/{id}/owner {uid}: 3.8.1, the owner offers the plan to one of
 *  its co-authors (one who said yes); {uid: null} takes the offer back. It's
 *  theirs when they say yes (POST /plans/{id}/invite). */
export async function offerPlan(req: Request, s: Session, env: Env, [id]: string[]): Promise<Response> {
  const p = await ownerOnly(env, id, s);
  await limitOrThrow(env, `planinvite:${s.uid}`, 30, 86400);  // as an invite: it moves its co-author's stamp
  const body = await readJson(req);
  if (Object.keys(body).some((k) => k !== "uid") || !("uid" in body)) throw V.bad("owner");
  const to = body.uid;
  if (to !== null && !V.isStr(to, 128, 1)) throw V.bad("owner");
  if (to !== null && !(await isEditor(env, id, to as string))) throw new HttpError(400, "not_coauthor");
  if ((to ?? null) !== (p.handover ?? null)) {
    // still a co-author who said yes as it's written (one who left meanwhile is offered nothing)
    await env.DB.prepare(`UPDATE plans SET handover = ?1 WHERE id = ?2 AND owner = ?3
        AND (?1 IS NULL OR EXISTS (SELECT 1 FROM plan_editors WHERE plan = ?2 AND uid = ?1 AND accepted_at IS NOT NULL))`)
      .bind(to, id, s.uid).run();
  }
  return json(await view(env, await getPlan(env, id), s.uid));
}

export const LISTED_MAX = 20;  // plans one person keeps in the library (library.ts)

/** POST /plans/{id}/invite {yes, kind?}: 3.8.1, the invitee's answer (kind, as the board
 *  showed it: "coauthor" or "owner", so a stale answer never answers the other). To an invite
 *  to co-write it: yes makes me a co-author, no takes the invite away. To the
 *  plan offered to me (I co-write it): yes makes it mine, and its owner a
 *  co-author (its code, tag root and followers stay); no leaves it theirs.
 *  404 no_invite when there's neither. */
export async function answerInvite(req: Request, s: Session, env: Env, [id]: string[]): Promise<Response> {
  const body = await readJson(req);
  if (typeof body.yes !== "boolean" || Object.keys(body).some((k) => k !== "yes" && k !== "kind")) throw V.bad("invite");
  // which question this answers (as the board showed it): a stale "co-write?" Yes never takes the plan
  const kind = body.kind;
  if (kind !== undefined && kind !== "coauthor" && kind !== "owner") throw V.bad("invite");
  const p = await getPlan(env, id);
  const row = await env.DB.prepare("SELECT accepted_at FROM plan_editors WHERE plan = ? AND uid = ?").bind(id, s.uid)
    .first<{ accepted_at: number | null }>();
  const db = env.DB;
  const now = nowSec();
  if (kind !== "coauthor" && row && row.accepted_at !== null && p.handover === s.uid && p.owner) {
    if (body.yes) {
      // what an owner keeps has a ceiling (create, copy): a plan handed over counts too, its Undo copy and
      // its place in the library with it
      const mine = await db.prepare("SELECT COUNT(*) AS n FROM plans WHERE owner = ?").bind(s.uid).first<number>("n");
      if ((mine ?? 0) >= PLANS_MAX) throw new HttpError(409, "too_many_plans");
      const prev = await db.prepare("SELECT COALESCE(SUM(LENGTH(prev)), 0) AS n FROM plan_log WHERE plan = ? AND prev IS NOT NULL").bind(id).first<number>("n");
      await roomFor(env, s.uid, p.doc.length + (p.lib?.length ?? 0) + (prev ?? 0));
      if (p.listed === 1) {
        const listed = await db.prepare("SELECT COUNT(*) AS n FROM plans WHERE owner = ? AND listed = 1").bind(s.uid).first<number>("n");
        if ((listed ?? 0) >= LISTED_MAX) throw new HttpError(409, "too_many_listed");
      }
      // one transaction; each step only while the swap is the one asked for
      const [swap] = await db.batch([
        db.prepare("UPDATE plans SET owner = ?1, handover = NULL WHERE id = ?2 AND owner = ?3 AND handover = ?1").bind(s.uid, id, p.owner),
        db.prepare("DELETE FROM plan_editors WHERE plan = ?1 AND uid = ?2 AND EXISTS (SELECT 1 FROM plans WHERE id = ?1 AND owner = ?2)").bind(id, s.uid),
        db.prepare(
          `INSERT INTO plan_editors (plan, uid, at, accepted_at) SELECT ?1, ?2, ?3, ?3 WHERE EXISTS (SELECT 1 FROM plans WHERE id = ?1 AND owner = ?4)
           ON CONFLICT(plan, uid) DO UPDATE SET accepted_at = COALESCE(plan_editors.accepted_at, excluded.accepted_at)`,
        ).bind(id, p.owner, now, s.uid),
        // the invites the old owner sent go with them (only someone the new owner could add today is asked)
        db.prepare("DELETE FROM plan_editors WHERE plan = ?1 AND accepted_at IS NULL AND EXISTS (SELECT 1 FROM plans WHERE id = ?1 AND owner = ?2)")
          .bind(id, s.uid),
      ]);
      if (!swap.meta.changes) throw new HttpError(404, "no_invite");
    } else {
      await db.prepare("UPDATE plans SET handover = NULL WHERE id = ? AND handover = ?").bind(id, s.uid).run();
    }
  } else if (kind !== "owner" && row && row.accepted_at === null) {
    await (body.yes
      ? db.prepare("UPDATE plan_editors SET accepted_at = ? WHERE plan = ? AND uid = ? AND accepted_at IS NULL").bind(now, id, s.uid)
      : db.prepare("DELETE FROM plan_editors WHERE plan = ? AND uid = ? AND accepted_at IS NULL").bind(id, s.uid)).run();
  } else {
    throw new HttpError(404, "no_invite");
  }
  return json(await view(env, await getPlan(env, id), s.uid));
}

/** 3.8.1: my invites waiting for an answer, as the day's first board (and
 *  the site's home) carry them: to co-write a plan, or a plan offered to me.
 *  Who asked by name and emoji only. Offers first, then the newest invites. */
const INVITES_SQL = `SELECT p.id, p.name, 'owner' AS kind, u.name AS by_name, u.emoji AS by_emoji, 0 AS k, 0 AS at
     FROM plans p LEFT JOIN users u ON u.uid = p.owner
    WHERE p.handover = ?1 AND p.owner != ''
      AND EXISTS (SELECT 1 FROM plan_editors e WHERE e.plan = p.id AND e.uid = ?1 AND e.accepted_at IS NOT NULL)
   UNION ALL
   SELECT p.id, p.name, 'coauthor', u.name, u.emoji, 1, e.at
     FROM plan_editors e JOIN plans p ON p.id = e.plan LEFT JOIN users u ON u.uid = p.owner
    WHERE e.uid = ?1 AND e.accepted_at IS NULL AND p.owner != ''
   ORDER BY k, at DESC, id LIMIT ${INVITES_ON_BOARD}`;
type InviteRow = { id: string; name: string; kind: "owner" | "coauthor"; by_name: string | null; by_emoji: string | null };
const inviteOf = (r: InviteRow) => ({ id: r.id, name: r.name, kind: r.kind, by: { name: r.by_name || "?", emoji: r.by_emoji || "" } });

export async function planInvites(env: Env, uid: string) {
  return (await env.DB.prepare(INVITES_SQL).bind(uid).all<InviteRow>()).results.map(inviteOf);
}

/** POST /plans/{id}/remarks {add: {tag | card, text}} or {remove: id}: 3.8.1,
 *  an author's note for followers on a card (or a tag), from Anki's Browse.
 *  A save, as tagNotes is: a new version, a line in History, room for Undo's
 *  copy, the saves' daily ceiling. A note on a card or tag that has one
 *  already changes its text (one note there, edited). Never card text. */
export async function remarks(req: Request, s: Session, env: Env, [id]: string[]): Promise<Response> {
  const p = await authorOnly(env, id, s);
  await limitOrThrow(env, `planput:${s.uid}`, 500, 86400);
  const body = await readJson(req);
  const keys = Object.keys(body);
  if (keys.length !== 1 || !["add", "remove"].includes(keys[0])) throw V.bad("remark");
  const doc = JSON.parse(p.doc) as Obj;
  let list = ((doc.remarks as Obj[] | undefined) || []).map((r) => ({ ...r }));
  const target = (r: Obj) => (r.tag !== undefined ? `tag:${String(r.tag).toLowerCase()}` : `card:${JSON.stringify(r.card)}`);
  const where = (r: Obj) => (r.tag !== undefined ? String(r.tag).split("::").pop()!.replace(/_/g, " ") : "a card");
  let summary: string;
  if (body.add !== undefined) {
    if (!V.isObj(body.add) || "id" in body.add) throw V.bad("remark");
    const r = remark({ ...body.add, id: "new" });
    const had = list.find((x) => target(x) === target(r));
    if (had) {
      if (had.text === r.text) return json(await view(env, p, s.uid));
      had.text = r.text;
      summary = `changed a note on ${where(had)} in Anki`;
    } else {
      if (list.length >= REMARKS_MAX) throw new HttpError(409, "too_many_remarks");
      list.push({ ...r, id: newUnitId() });
      summary = `added a note on ${where(r)} in Anki`;
    }
  } else {
    if (!V.isStr(body.remove, 12) || !UNIT_ID.test(body.remove)) throw V.bad("remark");
    const r = list.find((x) => x.id === body.remove);
    if (!r) return json(await view(env, p, s.uid));  // gone already
    list = list.filter((x) => x !== r);
    summary = `took off a note on ${where(r)} in Anki`;
  }
  if (list.length) doc.remarks = list; else delete doc.remarks;
  const clean = JSON.stringify(planDoc(doc));
  if (clean === p.doc) return json(await view(env, p, s.uid));
  const lib = keepLib(p, clean);
  await roomForSave(env, p, clean, lib);  // 3.7.2: and the doc it replaces, kept for Undo
  const r = await env.DB.prepare("UPDATE plans SET doc = ?, lib = ?, version = version + 1, updated_at = ? WHERE id = ? AND version = ?")
    .bind(clean, lib, nowSec(), id, p.version).run();
  if (!r.meta.changes) throw new HttpError(409, "stale", { version: (await getPlan(env, id)).version });
  await logSave(env, id, p.version + 1, s.uid, V.oneLine(summary, SUMMARY_MAX), p.doc);
  return json(await view(env, await getPlan(env, id), s.uid));
}

// ---- notes on a day ----

/** Who may read and write a plan's notes: its authors and followers. */
async function inPlan(env: Env, id: string, uid: string): Promise<Plan> {
  const p = await getPlan(env, id);
  if ((await role(env, p, uid)) === "reader") throw new HttpError(404, "no_plan");
  return p;
}

/** GET /plans/{id}/notes: every note, oldest first. Names as on the board. */
export async function notes(s: Session, env: Env, [id]: string[]): Promise<Response> {
  const p = await inPlan(env, id, s.uid);
  const rows = await env.DB.prepare(
    `SELECT n.id, n.uid, n.day, n.text, n.at, u.name, u.emoji FROM plan_notes n LEFT JOIN users u ON u.uid = n.uid
      WHERE n.plan = ? ORDER BY n.id LIMIT ?`,
  ).bind(id, NOTES_MAX).all<{ id: number; uid: string; day: string; text: string; at: number; name: string | null; emoji: string | null }>();
  const author = p.owner === s.uid || (await isEditor(env, id, s.uid));
  // a plan in the library: its authors' notes (and my own, from before), never a stranger's
  const authors = p.listed === 1 ? await authorUids(env, p) : null;
  return json({ notes: rows.results.filter((r) => !authors || authors.has(r.uid) || r.uid === s.uid).map((r) => ({ id: r.id, uid: r.uid, name: r.name || "?", emoji: r.emoji || "", day: r.day,
    text: r.text, at: r.at, mine: r.uid === s.uid, remove: r.uid === s.uid || author })) });
}

/** The owner and co-authors. */
export async function authorUids(env: Env, p: Plan): Promise<Set<string>> {
  const eds = await env.DB.prepare("SELECT uid FROM plan_editors WHERE plan = ? AND accepted_at IS NOT NULL").bind(p.id).all<{ uid: string }>();
  return new Set([p.owner, ...eds.results.map((e) => e.uid)]);
}

/** POST /plans/{id}/notes {day, text}: a note on a day ("lab day, keep it light").
 *  On a plan in the library, where anyone can follow, only its authors write them. */
export async function addNote(req: Request, s: Session, env: Env, [id]: string[]): Promise<Response> {
  const p = await inPlan(env, id, s.uid);
  if (p.listed === 1 && !(await authorUids(env, p)).has(s.uid)) throw new HttpError(403, "authors_only");
  const body = await readJson(req);
  if (!V.isDate(body.day) || !V.isStr(body.text, NOTE_TEXT_MAX * 4, 1)) throw V.bad("note");
  const text = V.oneLine(body.text as string, NOTE_TEXT_MAX);
  if (!text) throw V.bad("note");
  await limitOrThrow(env, `plannote:${s.uid}`, 60, 3600);
  // the plan's ceiling, and one person's share of it: one follower can't
  // fill a plan's notes and leave its authors none (authors aren't capped)
  const c = await env.DB.prepare(
    "SELECT COUNT(*) AS n, SUM(CASE WHEN uid = ?2 THEN 1 ELSE 0 END) AS mine FROM plan_notes WHERE plan = ?1",
  ).bind(id, s.uid).first<{ n: number; mine: number | null }>();
  if ((c?.n ?? 0) >= NOTES_MAX) throw new HttpError(409, "too_many_notes");
  if ((c?.mine ?? 0) >= NOTES_PER_PERSON && !(await authorUids(env, p)).has(s.uid)) throw new HttpError(409, "too_many_notes");
  const r = await env.DB.prepare("INSERT INTO plan_notes (plan, uid, day, text, at) VALUES (?, ?, ?, ?, ?)")
    .bind(id, s.uid, body.day, text, nowSec()).run();
  return json({ id: r.meta.last_row_id, day: body.day, text });
}

/** DELETE /plans/{id}/notes/{nid}: its writer, or an author (done with it). */
export async function removeNote(s: Session, env: Env, [id, nid]: string[]): Promise<Response> {
  const p = await inPlan(env, id, s.uid);
  const author = p.owner === s.uid || (await isEditor(env, id, s.uid));
  await env.DB.prepare(`DELETE FROM plan_notes WHERE plan = ? AND id = ?${author ? "" : " AND uid = ?"}`)
    .bind(...(author ? [id, Number(nid)] : [id, Number(nid), s.uid])).run();
  return json({ ok: true });
}

// ---- 3.7.3: posts to followers ----

/** One post, written with a save or on its own: authors only, one line, a
 *  ceiling a day per plan, the newest POSTS_KEEP kept. */
async function writePost(env: Env, p: Plan, uid: string, raw: unknown, version: number | null) {
  if (!V.isStr(raw, POST_MAX * 4, 1)) throw V.bad("post");
  const text = V.oneLine(raw as string, POST_MAX);
  if (!text) throw V.bad("post");
  const since = nowSec() - 86400;
  const n = await env.DB.prepare("SELECT COUNT(*) AS n FROM plan_posts WHERE plan = ? AND at > ?").bind(p.id, since).first<number>("n");
  if ((n ?? 0) >= POSTS_PER_DAY) throw new HttpError(429, "too_many_posts");
  const r = await env.DB.prepare("INSERT INTO plan_posts (plan, uid, text, version, at) VALUES (?, ?, ?, ?, ?)")
    .bind(p.id, uid, text, version, nowSec()).run();
  await env.DB.prepare(
    "DELETE FROM plan_posts WHERE plan = ?1 AND id NOT IN (SELECT id FROM plan_posts WHERE plan = ?1 ORDER BY id DESC LIMIT ?2)",
  ).bind(p.id, POSTS_KEEP).run();
  return { id: r.meta.last_row_id as number, text };
}

/** GET /plans/{id}/posts: newest first, for anyone in the plan. */
export async function posts(s: Session, env: Env, [id]: string[]): Promise<Response> {
  const p = await inPlan(env, id, s.uid);
  const rows = await env.DB.prepare(
    `SELECT t.id, t.uid, t.text, t.version, t.at, u.name, u.emoji FROM plan_posts t LEFT JOIN users u ON u.uid = t.uid
      WHERE t.plan = ? ORDER BY t.id DESC LIMIT ?`,
  ).bind(id, POSTS_KEEP).all<{ id: number; uid: string; text: string; version: number | null; at: number; name: string | null; emoji: string | null }>();
  const authors = await authorUids(env, p);
  return json({ posts: rows.results.map((r) => ({ id: r.id, uid: r.uid, name: r.name || "?", emoji: r.emoji || "",
    text: r.text, withSave: r.version !== null, at: r.at, coauthor: r.uid !== p.owner && authors.has(r.uid),
    remove: r.uid === s.uid || p.owner === s.uid })) });
}

/** POST /plans/{id}/posts {text}: an author posts to the plan's followers. */
export async function addPost(req: Request, s: Session, env: Env, [id]: string[]): Promise<Response> {
  const p = await authorOnly(env, id, s);
  const body = await readJson(req);
  await limitOrThrow(env, `planpost:${s.uid}`, 30, 3600);
  return json(await writePost(env, p, s.uid, body.text, null));
}

/** DELETE /plans/{id}/posts/{pid}: its writer, or the owner. */
export async function removePost(s: Session, env: Env, [id, pid]: string[]): Promise<Response> {
  const p = await authorOnly(env, id, s);
  await env.DB.prepare(`DELETE FROM plan_posts WHERE plan = ? AND id = ?${p.owner === s.uid ? "" : " AND uid = ?"}`)
    .bind(...(p.owner === s.uid ? [id, Number(pid)] : [id, Number(pid), s.uid])).run();
  return json({ ok: true });
}

/** POST /plans/{id}/cards {cards, unit? | opens (+ name?)}: single cards
 *  picked in Anki's browser, added to a date that exists or a new one. */
export async function addCards(req: Request, s: Session, env: Env, [id]: string[]): Promise<Response> {
  const p = await authorOnly(env, id, s);
  await limitOrThrow(env, `planput:${s.uid}`, 500, 86400);  // a save, as the plan's PUT is
  const body = await readJson(req, PLAN_BODY_MAX);
  // 3.3, C3: or an Anki search, with how many it found here
  const search = body.search !== undefined ? body.search : null;
  if (search !== null && (!V.isStr(search, SEARCH_LEN, 1) || !V.isInt(body.n, 0, 1_000_000))) throw V.bad("cards");
  if (search === null && (!Array.isArray(body.cards) || !body.cards.length)) throw V.bad("cards");
  const cards = search === null ? (body.cards as unknown[]).map(cardRef) : [];
  const doc = JSON.parse(p.doc) as { units: Obj[] };
  let u: Obj | undefined;
  if (body.unit !== undefined) {
    u = doc.units.find((x) => x.id === body.unit);
    if (!u) throw new HttpError(404, "no_unit");
  } else {
    if (!V.isDate(body.opens)) throw V.bad("opens");
    u = { id: newUnitId(), name: body.name !== undefined ? V.displayName(body.name) : `Cards · ${body.opens}`,
          opens: body.opens, tags: [], decks: [], cards: [] };
    doc.units.push(u);
  }
  u.cards = [...(u.cards as [string, number][]), ...cards];
  if (search !== null) {
    u.search = [...new Set([...((u.search as string[]) || []), search as string])];
    u.sn = { ...((u.sn as Obj) || {}), [search as string]: body.n };
  }
  const clean = JSON.stringify(stalePl(planDoc(doc), p.doc));  // dedupes, re-sorts, enforces the caps
  if (clean === p.doc) return json(await view(env, p, s.uid));
  const lib = keepLib(p, clean);
  await roomForSave(env, p, clean, lib);  // 3.7.2, as a save's
  const r = await env.DB.prepare("UPDATE plans SET doc = ?, lib = ?, version = version + 1, updated_at = ? WHERE id = ? AND version = ?")
    .bind(clean, lib, nowSec(), id, p.version).run();
  if (!r.meta.changes) throw new HttpError(409, "stale", { version: (await getPlan(env, id)).version });
  await logSave(env, id, p.version + 1, s.uid, search !== null ? "added a search in Anki"
    : `added ${cards.length} single card${cards.length === 1 ? "" : "s"} in Anki`, p.doc);
  return json(await view(env, await getPlan(env, id), s.uid));
}

/** POST /plans/{id}/tags {name, add?, remove?, n?}: 3.8.0, notes picked in an
 *  author's Anki put on one of the plan's tags (made if it's new) or taken
 *  off it; a tag left with nothing goes. Note guids only. `n`: how many
 *  cards the tag holds in that Anki now. */
export async function tagNotes(req: Request, s: Session, env: Env, [id]: string[]): Promise<Response> {
  const p = await authorOnly(env, id, s);
  await limitOrThrow(env, `planput:${s.uid}`, 500, 86400);
  const body = await readJson(req, PLAN_BODY_MAX);
  for (const k of Object.keys(body)) if (!["name", "add", "remove", "n"].includes(k)) throw V.bad("tag");
  const name = V.displayName(body.name);
  if (name.length > TAG_NAME_MAX) throw V.bad("tag");
  const list = (x: unknown) => {
    if (x === undefined) return [];
    if (!Array.isArray(x) || x.length > IDLIST_MAX || !x.every((g) => V.isStr(g, V.GUID_MAX, 1))) throw V.bad("tag");
    return x as string[];
  };
  const add = list(body.add), remove = new Set(list(body.remove));
  if (!add.length && !remove.size) throw V.bad("tag");
  if (body.n !== undefined && !V.isInt(body.n, 0, 1_000_000)) throw V.bad("tag");
  const doc = JSON.parse(p.doc) as Obj & { tags?: Obj[] };
  const tags = doc.tags || [];
  const part = tagPart(name).toLowerCase();
  let t = tags.find((x) => tagPart(x.name as string).toLowerCase() === part);
  if (!t) {
    if (!add.length) throw new HttpError(404, "no_tag");
    t = { id: newUnitId(), name, notes: [] };
    tags.push(t);
  }
  const had = new Set((t.notes as string[] | undefined) || []);
  const notes = [...new Set([...had, ...add])].filter((g) => !remove.has(g));
  if (notes.length > IDLIST_MAX) throw new HttpError(400, "too_many");
  if (notes.length) t.notes = notes; else delete t.notes;
  if (t.cards) {  // 3.8.1: a note taken off takes its single cards with it
    const left = (t.cards as [string, number][]).filter(([g]) => !remove.has(g));
    if (left.length) t.cards = left; else delete t.cards;
  }
  if (body.n !== undefined) t.n = body.n;
  doc.tags = tags.filter((x) => x.notes || x.cards || x.tags || x.decks || x.search);
  if (!doc.tags.length) delete doc.tags;
  if (!doc.tagroot) doc.tagroot = p.tagroot || tagRoot(p.name);
  const r0 = await rooted(env, id, p.tagroot, planDoc(doc));
  const clean = JSON.stringify(r0.doc);
  if (clean === p.doc) return json(await view(env, p, s.uid));
  const lib = keepLib(p, clean);
  await roomForSave(env, p, clean, lib);  // 3.7.2: and the doc it replaces, kept for Undo
  const r = await env.DB.prepare("UPDATE plans SET doc = ?, lib = ?, tagroot = ?, version = version + 1, updated_at = ? WHERE id = ? AND version = ?")
    .bind(clean, lib, r0.root, nowSec(), id, p.version).run().catch(rootTaken);
  if (!r.meta.changes) throw new HttpError(409, "stale", { version: (await getPlan(env, id)).version });
  const added = notes.filter((g) => !had.has(g)).length, taken = [...had].filter((g) => remove.has(g)).length;
  await logSave(env, id, p.version + 1, s.uid, added
    ? `tagged ${added} note${added === 1 ? "" : "s"} as ${name} in Anki`
    : `took ${taken} note${taken === 1 ? "" : "s"} off ${name} in Anki`, p.doc);
  return json(await view(env, await getPlan(env, id), s.uid));
}

/** DELETE /plans/{id}: the author takes it down. Followers keep every card
 *  they have open; nothing is suspended anywhere. */
export async function remove(s: Session, env: Env, [id]: string[]): Promise<Response> {
  await ownerOnly(env, id, s);
  await env.DB.batch([
    env.DB.prepare("DELETE FROM plan_follows WHERE plan = ?").bind(id),
    env.DB.prepare("DELETE FROM plan_editors WHERE plan = ?").bind(id),
    env.DB.prepare("DELETE FROM plan_notes WHERE plan = ?").bind(id),
    env.DB.prepare("DELETE FROM plan_log WHERE plan = ?").bind(id),
    env.DB.prepare("DELETE FROM plan_posts WHERE plan = ?").bind(id),
    env.DB.prepare("DELETE FROM plan_team WHERE plan = ?").bind(id),  // 3.7.3
    env.DB.prepare("DELETE FROM plan_asks WHERE plan = ?").bind(id),
    env.DB.prepare("DELETE FROM plans WHERE id = ?").bind(id),
  ]);
  return json({ ok: true });
}

// ---- 3.4, D2: the plan as a calendar ----

const icsText = (t: string) => t.replace(/\\/g, "\\\\").replace(/;/g, "\\;").replace(/,/g, "\\,").replace(/\r?\n/g, "\\n");
const icsDate = (d: string) => d.replace(/-/g, "");
const dayAfter = (d: string) => new Date(Date.parse(`${d}T00:00:00Z`) + 86400000).toISOString().slice(0, 10);

/** RFC 5545: lines of at most 75 octets, continued with a space, never
 *  splitting a character. */
function fold(line: string): string {
  const enc = new TextEncoder();
  if (enc.encode(line).length <= 75) return line;
  const out: string[] = [];
  let cur = "";
  let n = 0;
  for (const ch of line) {
    const b = enc.encode(ch).length;
    if (n + b > (out.length ? 74 : 75)) { out.push(cur); cur = ""; n = 0; }
    cur += ch;
    n += b;
  }
  out.push(cur);
  return out.join("\r\n ");
}

/** GET /plans/ics?code=: the plan's dates as a calendar to subscribe to.
 *  No sign-in (a calendar app can't), like the shared link; the code opens
 *  it, and a plan for one squad has none. Names of people never appear. */
export async function ics(req: Request, env: Env): Promise<Response> {
  const code = normalizeCode(new URL(req.url).searchParams.get("code") || "");
  if (code.length !== PLAN_CODE_LEN) throw new HttpError(404, "no_plan");
  // by address, not by code: guessing codes stays slow, and nobody holding a
  // code can use up its calendar for everyone (Google polls from few addresses)
  await limitOrThrow(env, `ics:ip:${clientIp(req)}`, 1000, 3600);
  const p = await env.DB.prepare("SELECT * FROM plans WHERE code = ?").bind(code).first<Plan>();
  if (!p || p.audience === "squad") throw new HttpError(404, "no_plan");
  const doc = JSON.parse(p.doc) as { units: Obj[]; reviews?: { day: string; from: string; to: string }[]; events?: { id: string; day: string; name: string }[] };
  const stamp = new Date(p.updated_at * 1000).toISOString().replace(/[-:]/g, "").replace(/\.\d+Z$/, "Z");
  const link = `https://duecrew.com/p/${p.code}`;
  const lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Due Crew//Plans//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
    `X-WR-CALNAME:${icsText(p.name)}`, "REFRESH-INTERVAL;VALUE=DURATION:PT6H", "X-PUBLISHED-TTL:PT6H"];
  const event = (uid: string, start: string, end: string, summary: string) => lines.push("BEGIN:VEVENT",
    `UID:${uid}.${p.id}@duecrew.com`, `DTSTAMP:${stamp}`, `DTSTART;VALUE=DATE:${icsDate(start)}`, `DTEND;VALUE=DATE:${icsDate(end)}`,
    `SUMMARY:${icsText(summary)}`, `DESCRIPTION:${icsText(p.name)}`, `URL:${link}`, "TRANSP:TRANSPARENT", "END:VEVENT");
  const byId = new Map(doc.units.map((u) => [u.id as string, u]));
  for (const u of doc.units) {
    const n = unitCount(u);
    const last = u.even && u.due ? (u.due as string) : (u.opens as string);
    event(u.id as string, u.opens as string, dayAfter(last), `${u.name}${n ? ` · ${n.toLocaleString("en-US")} new` : ""}`);
  }
  // F1: an event is its own day, with how many days prep for it
  for (const ev of doc.events || []) {
    const prep = new Set(doc.units.filter((u) => u.for === ev.id).map((u) => u.opens)).size;  // days, not dates
    event(`e${ev.id}`, ev.day, dayAfter(ev.day), `${ev.name}${prep ? ` · ${prep} day${prep === 1 ? "" : "s"} of prep` : ""}`);
  }
  for (const r of doc.reviews || []) {
    const a = byId.get(r.from), b = byId.get(r.to);
    if (!a || !b) continue;
    event(`r${icsDate(r.day)}${r.from}${r.to}`, r.day, dayAfter(r.day), `Review · ${a.name}${a !== b ? ` – ${b.name}` : ""}`);
  }
  lines.push("END:VCALENDAR");
  return new Response(lines.map(fold).join("\r\n") + "\r\n", { headers: {
    "content-type": "text/calendar; charset=utf-8", "cache-control": "public, max-age=10800", "x-content-type-options": "nosniff",
    "content-disposition": `inline; filename="due-crew-${p.code}.ics"` } });
}

/** GET /plans/public?code=: what a plan's shared link shows before anyone
 *  signs in (3.4 review, C1): its name, whose, the one line, how many
 *  follow, and each date's name, day and card count. The calendar link
 *  already gives the dates to anyone with the code; a squad's plan has none. */
export async function publicPeek(req: Request, env: Env): Promise<Response> {
  const code = normalizeCode(new URL(req.url).searchParams.get("code") || "");
  if (code.length !== PLAN_CODE_LEN) throw new HttpError(404, "no_plan");
  await limitOrThrow(env, `pub:ip:${clientIp(req)}`, 300, 3600);  // guessing codes stays slow
  const p = await env.DB.prepare(
    `SELECT p.id, p.owner, p.name, p.line, p.audience, p.version, p.doc, p.totals, p.totals_at, u.name AS owner_name
       FROM plans p LEFT JOIN users u ON u.uid = p.owner WHERE p.code = ?`,
  ).bind(code).first<{ id: string; owner: string; name: string; line: string; audience: string; version: number; doc: string;
                       totals: string | null; totals_at: number | null; owner_name: string | null }>();
  if (!p || p.audience === "squad") throw new HttpError(404, "no_plan");
  const doc = JSON.parse(p.doc) as { deck: string; deckUrl?: string; units: Obj[]; events?: { day: string; name: string }[] };
  const n = unitCount;
  const followers = (await totals(env, [p])).get(p.id)!.n;  // its totals, up to an hour old
  return json({
    name: p.name, ownerName: p.owner_name || (p.owner ? "?" : "a former member"), line: p.line || "", deck: doc.deck, followers,
    // 3.5, A: the version keys the link's preview picture; events are in the calendar feed already
    v: p.version, events: (doc.events || []).map((e) => ({ day: e.day, name: e.name })),
    ...(doc.deckUrl ? { deckUrl: doc.deckUrl } : {}),  // 3.8.1: where to get the deck
    units: doc.units.map((u) => ({ name: u.name, opens: u.opens, ...(u.due ? { due: u.due } : {}), n: n(u) })),
  });
}

// ---- following ----

/** POST /plans/follow {code, team?, sched?}: follow the plan behind a code,
 *  on its team (sharing my progress) when `team` is true and it has room.
 *  3.7.6: `share` alone (older add-ons' box, ticked by default) no longer
 *  shares: being on a team is a choice made with this add-on or later. */
export async function follow(req: Request, s: Session, env: Env): Promise<Response> {
  const body = await readJson(req);
  if (typeof body.code !== "string") throw V.bad("code");
  const sched = body.sched !== undefined ? schedule(body.sched) : undefined;
  if (body.own !== undefined && body.own !== null && !OWN_PACE.includes(body.own as string)) throw V.bad("follow");
  const own = body.own === undefined ? undefined : (body.own as string | null);
  const code = normalizeCode(body.code);
  await limitOrThrow(env, `planpeek:${s.uid}`, 60, 3600);  // the same guesses as peek's
  const p = await env.DB.prepare("SELECT * FROM plans WHERE code = ?").bind(code).first<Plan>();
  if (!p || !(await mayRead(env, p, s.uid, code))) throw new HttpError(404, "no_plan");
  const was = await following(env, p.id, s.uid);
  if (!was) {
    // a bound on what every board carries (and on one query's parameters):
    // the plans I follow that I can see, as the board and my list show them.
    // A squad's plan I left is kept, hidden (back in the squad, it's back),
    // and counts only toward a looser ceiling on what I keep in all
    const c = await env.DB.prepare(
      `SELECT COUNT(*) AS n, COALESCE(SUM(${SEES("p")}), 0) AS shown FROM plan_follows f JOIN plans p ON p.id = f.plan WHERE f.uid = ?1`,
    ).bind(s.uid).first<{ n: number; shown: number }>();
    if ((c?.shown ?? 0) >= FOLLOWS_MAX || (c?.n ?? 0) >= FOLLOWS_KEPT) throw new HttpError(409, "too_many_plans");
  }
  const sj = sched === undefined ? null : sched === null ? null : JSON.stringify(sched);
  await env.DB.prepare(
    `INSERT INTO plan_follows (plan, uid, share, paused, sched, own, at) VALUES (?, ?, 0, 0, ?, ?, ?)
     ON CONFLICT(plan, uid) DO UPDATE SET paused = 0
       ${sched === undefined ? "" : ", sched = excluded.sched"}${own === undefined ? "" : ", own = excluded.own"}`,
  ).bind(p.id, s.uid, sj, own ?? null, nowSec()).run();
  const full = body.team === true && !(await joinTeam(env, p.id, s.uid));
  return json({ ...(await view(env, p, s.uid)), ...(full ? { teamFull: true } : {}) });
}

/** PATCH /plans/{id}/follow {share?, paused?, sched?, early?, shift?, until?, since?, skipped?, moved?, own?}.
 *  G3, G4: my own days: how many days my dates run later than the plan's
 *  (0-365), a pause's first and last day, the dates I skip (unit ids).
 *  3.7.6: `moved` {unit id: 1-365 days later}, one date at a time on top
 *  of the shift. Reset to default is one PATCH of all of them. */
export async function patchFollow(req: Request, s: Session, env: Env, [id]: string[]): Promise<Response> {
  const body = await readJson(req);
  for (const k of Object.keys(body)) if (!["share", "paused", "sched", "early", "shift", "until", "since", "skipped", "moved", "own"].includes(k)) throw V.bad("follow");
  if (body.own !== undefined && body.own !== null && !OWN_PACE.includes(body.own as string)) throw V.bad("follow");
  if (body.early !== undefined && !V.isInt(body.early, 0, 7)) throw V.bad("follow");
  if (body.shift !== undefined && !V.isInt(body.shift, 0, 365)) throw V.bad("follow");
  for (const k of ["until", "since"]) if (body[k] !== undefined && body[k] !== null && !V.isDate(body[k])) throw V.bad("follow");
  if (body.skipped !== undefined && (!Array.isArray(body.skipped) || body.skipped.length > UNITS_MAX
      || !body.skipped.every((u) => typeof u === "string" && UNIT_ID.test(u)))) throw V.bad("follow");
  if (body.moved !== undefined && (!body.moved || typeof body.moved !== "object" || Array.isArray(body.moved)
      || Object.keys(body.moved).length > UNITS_MAX
      || !Object.entries(body.moved).every(([u, n]) => UNIT_ID.test(u) && V.isInt(n, 1, 365)))) throw V.bad("follow");
  const f = await following(env, id, s.uid);
  if (!f) throw new HttpError(404, "not_following");
  // 3.7.6: share is the team: true joins it (or stays as is when it's full), false leaves it
  if (typeof body.share === "boolean" && body.share !== (f.share === 1)) {
    if (body.share) await joinTeam(env, id, s.uid);
    else await leaveTeam(env, id, s.uid);
  }
  const share = typeof body.share === "boolean" ? ((await following(env, id, s.uid))?.share ?? f.share) : f.share;
  const paused = typeof body.paused === "boolean" ? (body.paused ? 1 : 0) : f.paused;
  const sched = body.sched !== undefined ? schedule(body.sched) : undefined;
  const sj = sched === undefined ? f.sched : sched === null ? null : JSON.stringify(sched);
  const early = body.early !== undefined ? body.early as number : f.early ?? 0;
  const shift = body.shift !== undefined ? body.shift as number : f.shift ?? 0;
  const until = body.until !== undefined ? (body.until as string | null) : f.pause_until;
  const since = body.since !== undefined ? (body.since as string | null) : f.pause_since;
  const skipped = body.skipped !== undefined ? ((body.skipped as string[]).length ? JSON.stringify([...new Set(body.skipped as string[])]) : null) : f.skipped;
  const moved = body.moved !== undefined
    ? (Object.keys(body.moved as object).length ? JSON.stringify(Object.fromEntries(Object.entries(body.moved as Record<string, number>).sort())) : null)
    : f.moved ?? null;
  const own = body.own !== undefined ? (body.own as string | null) : f.own ?? null;
  if (paused !== f.paused || sj !== f.sched || early !== (f.early ?? 0) || shift !== (f.shift ?? 0)
      || until !== f.pause_until || since !== f.pause_since || skipped !== f.skipped || moved !== (f.moved ?? null)
      || own !== (f.own ?? null)) {
    await env.DB.prepare(
      `UPDATE plan_follows SET paused = ?, sched = ?, early = ?, shift = ?, pause_until = ?, pause_since = ?, skipped = ?, moved = ?, own = ?
        WHERE plan = ? AND uid = ?`,
    ).bind(paused, sj, early, shift, until, since, skipped, moved, own, id, s.uid).run();
  }
  return json({ share: share === 1, paused: paused === 1, sched: sj ? JSON.parse(sj) : null, early,
    ...followDays({ shift, pause_until: until, pause_since: since, skipped, moved, own }) });
}

/** DELETE /plans/{id}/follow: stop. My progress goes with it. */
export async function unfollow(s: Session, env: Env, [id]: string[]): Promise<Response> {
  await env.DB.batch([
    env.DB.prepare("DELETE FROM plan_follows WHERE plan = ? AND uid = ?").bind(id, s.uid),
    env.DB.prepare("DELETE FROM plan_team WHERE plan = ? AND uid = ?").bind(id, s.uid),  // 3.7.3: off its team too
    recount(env, id),  // 3.9.5
  ]);
  return json({ ok: true });
}

/** A plan I follow that I can see (`t` its plans row; ?1 my uid): any but a
 *  squad's, or one of a squad I'm in (mayRead: leaving ends it), or my own. */
const SEES = (t: string) => `(${t}.audience != 'squad' OR ${t}.owner = ?1
  OR EXISTS (SELECT 1 FROM members m WHERE m.squad = ${t}.squad AND m.uid = ?1))`;

/** The plans I follow that I may still read, as the board shows them. ?1 is my uid. */
export const FOLLOWED = `SELECT f.plan FROM plan_follows f JOIN plans fp ON fp.id = f.plan WHERE f.uid = ?1 AND ${SEES("fp")}`;

/** GET /plans/mine: plans I wrote and plans I follow. Each doc without its
 *  dates' single cards and note ids (`cards`, `ids`: a list never needs
 *  them; they're most of a big plan), and everything else in a few queries,
 *  however many plans. What a date's pasted ids are (`idr`), its notes and
 *  the plan tags' notes and cards stay: the add-on reads them from here for
 *  a plan it doesn't follow (Export cards for my AI's "what the dates open",
 *  the Browse tag dialog's notes on a tag), and the site counts a date's notes. */
export async function mine(s: Session, env: Env): Promise<Response> {
  const rows = await env.DB.prepare(
    `SELECT p.id, p.code, p.owner, p.name, p.line, p.audience, p.squad, p.version, p.updated_at, u.name AS owner_name,
            p.listed, p.listed_note, p.based_on, p.totals, p.totals_at, p.handover,
            json_remove(p.doc, '$.units') AS rest,
            (SELECT json_group_array(json_remove(x.value, '$.ids', '$.cards')) FROM json_each(p.doc, '$.units') x) AS units
       FROM plans p LEFT JOIN users u ON u.uid = p.owner
      WHERE p.id IN (SELECT id FROM plans WHERE owner = ?1 UNION ${FOLLOWED}
                     UNION ${COAUTHORED})
      ORDER BY p.updated_at DESC`,  // each part by index, not a scan of every plan
  ).bind(s.uid).all<Plan & { owner_name: string | null; rest: string; units: string }>();
  const ids = rows.results.map((p) => p.id);
  if (!ids.length) return json({ plans: [] });
  const [fs, tot, eds, sq] = await Promise.all([
    env.DB.prepare(`SELECT plan, ${FOLLOW_COLS} FROM plan_follows WHERE uid = ?`).bind(s.uid)
      .all<Follow & { plan: string }>(),
    totals(env, rows.results),  // how many follow each: its totals, up to an hour old
    editorsOf(env, ids),
    env.DB.prepare("SELECT squad FROM members WHERE uid = ?").bind(s.uid).all<{ squad: string }>(),
  ]);
  const follows = new Map(fs.results.map((f) => [f.plan, f]));
  const counts = new Map([...tot].map(([id, t]) => [id, t.n]));
  const editors = new Map<string, Editor[]>();
  for (const e of eds.results) editors.set(e.plan, [...(editors.get(e.plan) ?? []), editorOf(e)]);
  const mySquads = new Set(sq.results.map((m) => m.squad));
  return json({ plans: rows.results.map((p) => {
    const units = (JSON.parse(p.units) as Obj[]).sort((a, b) => String(a.opens).localeCompare(String(b.opens)));
    return shape(p, s.uid, { ...JSON.parse(p.rest), units },
      { f: follows.get(p.id) ?? null, n: counts.get(p.id) ?? 0, editors: editors.get(p.id) ?? [], mySquads });
  }) });
}

// ---- progress ----

/** Validates a sync's `plans` part: {planId: {unitId: [opened, seen, total]}}. */
export function progressPart(v: unknown): Record<string, Record<string, [number, number, number]>> {
  if (!V.isObj(v) || Object.keys(v).length > 50) throw V.bad("plans");
  const out: Record<string, Record<string, [number, number, number]>> = {};
  for (const [pid, units] of Object.entries(v)) {
    if (!/^[a-z0-9]{1,32}$/.test(pid) || !V.isObj(units) || Object.keys(units).length > UNITS_MAX) throw V.bad("plans");
    out[pid] = {};
    for (const [uid, t] of Object.entries(units)) {
      if (!UNIT_ID.test(uid) || !Array.isArray(t) || t.length !== 3 || !t.every((n) => V.isInt(n))) throw V.bad("plans");
      const [opened, seen, total] = t as number[];
      if (opened > total || seen > total) throw V.bad("plans");
      out[pid][uid] = [opened, seen, total];
    }
  }
  return out;
}

const HIST_DAYS = 120;

/** 3.5, L: today's point on my plan's history: cards opened and seen in all,
 *  the last HIST_DAYS days kept. */
export function histNext(have: string | null, units: Record<string, [number, number, number]>, day: string): string {
  const h = have ? (JSON.parse(have) as Record<string, [number, number]>) : {};
  h[day] = Object.values(units).reduce<[number, number]>((a, [o, s]) => [a[0] + o, a[1] + s], [0, 0]);
  const keep = Object.keys(h).sort().slice(-HIST_DAYS);
  return JSON.stringify(Object.fromEntries(keep.map((d) => [d, h[d]])));
}

/** The statements that store my progress: only for plans I follow with
 *  sharing on, and only where it changed; my history rides the same write. */
export async function progressWrites(env: Env, uid: string, part: ReturnType<typeof progressPart>,
                                     today = new Date().toISOString().slice(0, 10)) {
  const ids = Object.keys(part);
  if (!ids.length) return [];
  const rows = await env.DB.prepare(
    // 3.7.6: kept whether or not I share, for my own views (the site's home, my log);
    // only the team's progress reaches the authors' and the crew's counts.
    // 3.9.5 (the audit's S2): and only for a plan I may still see; a squad's, once I've left it, is skipped
    `SELECT f.plan, f.progress, f.hist FROM plan_follows f JOIN plans p ON p.id = f.plan
      WHERE f.uid = ?1 AND ${SEES("p")} AND f.plan IN (${ids.map(() => "?").join(",")})`,
  ).bind(uid, ...ids).all<{ plan: string; progress: string | null; hist: string | null }>();
  return rows.results
    .map((r) => ({ r, doc: JSON.stringify(part[r.plan]) }))
    .filter(({ r, doc }) => r.progress !== doc)
    .map(({ r, doc }) => env.DB.prepare("UPDATE plan_follows SET progress = ?, hist = ? WHERE plan = ? AND uid = ?")
      .bind(doc, histNext(r.hist, part[r.plan], today), r.plan, uid));
}

/** GET /plans/{id}/progress: for its authors, per unit, how many followers
 *  (among those sharing) have it opened and done. Counts, never names.
 *  3.9.5 (the audit's S1, S2): only the follows that count (COUNTED), and no
 *  date's counts under COUNTS_MIN of them: `sharing` says how many there are. */
export async function progress(s: Session, env: Env, [id]: string[]): Promise<Response> {
  const p = await authorOnly(env, id, s);
  const rows = await env.DB.prepare(`SELECT f.progress FROM ${WITH_TEAM} WHERE f.plan = ? AND f.progress IS NOT NULL AND ${COUNTED}`)
    .bind(id).all<{ progress: string }>();
  const units: Record<string, { opened: number; done: number }> = {};
  if (rows.results.length < COUNTS_MIN) {
    const followers = await env.DB.prepare("SELECT COUNT(*) AS n FROM plan_follows WHERE plan = ?").bind(id).first<number>("n");
    return json({ followers: followers ?? 0, sharing: rows.results.length, units });
  }
  for (const u of (JSON.parse(p.doc).units as Obj[])) units[u.id as string] = { opened: 0, done: 0 };
  for (const r of rows.results) {
    for (const [uid, [opened, seen, total]] of Object.entries(JSON.parse(r.progress) as Record<string, number[]>)) {
      if (!units[uid]) continue;
      if (opened > 0) units[uid].opened++;
      if (total > 0 && seen >= total) units[uid].done++;
    }
  }
  const followers = await env.DB.prepare("SELECT COUNT(*) AS n FROM plan_follows WHERE plan = ?").bind(id).first<number>("n");
  return json({ followers: followers ?? 0, sharing: rows.results.length, units });
}

// ---- the board ----

/** 3.7.3: what a refresh compares: everything forBoard sends as it stands,
 *  but counts. The plans I follow that I can see (their version, my follow's
 *  own days, their newest post), and since 3.8.1's review the plans I write
 *  or co-author (their version: an author's save reaches my Anki's tags) and
 *  the plans offered to my squads; so leaving a squad, or a plan offered to
 *  it, moves it too. Not my progress, which moves at every sync, nor the
 *  totals (the day's first refresh brings those). A short hash; one batch of reads. */
export async function planStamp(env: Env, uid: string): Promise<string> {
  const rows = await env.DB.batch([
    env.DB.prepare(
      `SELECT p.id, p.version, p.owner, f.share, f.team_ask, f.paused, f.sched, f.early, f.shift, f.pause_until, f.pause_since, f.skipped, f.moved, f.own,
              (SELECT MAX(t.id) FROM plan_posts t WHERE t.plan = p.id) AS post
         FROM plan_follows f JOIN plans p ON p.id = f.plan WHERE f.uid = ?1 AND ${SEES("p")} ORDER BY p.id`).bind(uid),
    env.DB.prepare(
      `SELECT p.id, p.version FROM plans p WHERE p.id IN (SELECT id FROM plans WHERE owner = ?1 UNION ${COAUTHORED})
        ORDER BY p.id`).bind(uid),
    env.DB.prepare(
      `SELECT p.id, p.version, p.squad, p.owner FROM plans p JOIN members m ON m.squad = p.squad AND m.uid = ?1
        WHERE p.owner != ?1 AND NOT EXISTS (SELECT 1 FROM plan_follows f WHERE f.plan = p.id AND f.uid = ?1) ORDER BY p.id`).bind(uid),
    // 3.8.1: my invites, as the board lists them (planInvites): one arriving or going moves it
    env.DB.prepare(INVITES_SQL).bind(uid),
  ]);
  // with none, the stamp is what it was before 3.8.1 (no refresh reloads its plans for them)
  const parts = rows[3].results.length ? rows : rows.slice(0, 3);
  const bytes = new TextEncoder().encode(JSON.stringify(parts.map((r) => r.results.map((x) => Object.values(x as Obj)))));
  const h = new Uint8Array(await crypto.subtle.digest("SHA-1", bytes));
  return Array.from(h.slice(0, 8), (b) => b.toString(16).padStart(2, "0")).join("");
}

/** What the day's first refresh carries (and, since 3.7.3, a refresh whose
 *  stamp moved): the plans I follow, and plans offered to my squads that I
 *  don't follow yet; with each plan its newest posts, and the version is
 *  noted as reached (seen_version, written only when it changed). */
export async function forBoard(env: Env, uid: string, same = false) {
  // 3.8.1: same: the add-on has every doc as it stands (its stamp matched), so
  // each plan comes without its doc, which isn't read here either
  const mineRows = await env.DB.prepare(
    `SELECT p.id, p.name, p.owner, p.version, ${same ? "NULL AS doc" : "p.doc"}, p.totals, p.totals_at, f.share, f.team_ask, f.paused, f.sched, f.early,
            f.shift, f.pause_until, f.pause_since, f.skipped, f.moved, f.own, u.name AS owner_name
       FROM plan_follows f JOIN plans p ON p.id = f.plan LEFT JOIN users u ON u.uid = p.owner
      WHERE f.uid = ?1 AND ${SEES("p")}`,
  ).bind(uid).all<any>();
  const offers = await env.DB.prepare(
    `SELECT p.id, p.name, p.code, p.squad, u.name AS owner_name FROM plans p
       JOIN members m ON m.squad = p.squad AND m.uid = ?1 LEFT JOIN users u ON u.uid = p.owner
      WHERE p.owner != ?1 AND NOT EXISTS (SELECT 1 FROM plan_follows f WHERE f.plan = p.id AND f.uid = ?1)`,
  ).bind(uid).all<any>();
  // per plan: how many follow, and per unit how many sharing followers have it
  // done. Counts only: each plan's totals, from its row, up to an hour old.
  const crew = await totals(env, mineRows.results);
  // 3.3, C5: the plans I write, so my Anki can keep the note ids behind their
  // tags. Only what that needs, cut in SQL: a plan's ids are most of its doc.
  const authored = await env.DB.prepare(
    `SELECT p.id, p.version, p.name, json_extract(p.doc, '$.deck') AS deck,
            json_extract(p.doc, '$.tagroot') AS tagroot, json_extract(p.doc, '$.tags') AS tags, json_extract(p.doc, '$.remarks') AS remarks,
            (SELECT json_group_array(json_object('id', json_extract(x.value, '$.id'), 'tags', json_extract(x.value, '$.tags'),
                      'decks', json_extract(x.value, '$.decks'), 'search', json_extract(x.value, '$.search'),
                      'nids', json_extract(x.value, '$.nids'), 'cids', json_extract(x.value, '$.cids'),
                      'notes', json_extract(x.value, '$.notes'), 'opens', json_extract(x.value, '$.opens'),
                      'cut', json_extract(x.value, '$.cut'), 'cards', json_extract(x.value, '$.cards')))
               FROM json_each(p.doc, '$.units') x
              WHERE json_array_length(x.value, '$.tags') + json_array_length(x.value, '$.decks')
                    + coalesce(json_array_length(x.value, '$.search'), 0) + coalesce(json_array_length(x.value, '$.nids'), 0)
                    + coalesce(json_array_length(x.value, '$.cids'), 0) + coalesce(json_array_length(x.value, '$.notes'), 0)
                    + coalesce(json_array_length(x.value, '$.cards'), 0) > 0) AS units
       FROM plans p WHERE p.id IN (SELECT id FROM plans WHERE owner = ?1 UNION ${COAUTHORED})`,
  ).bind(uid).all<{ id: string; version: number; name: string; deck: string; tagroot: string | null; tags: string | null; remarks: string | null; units: string }>();
  // 3.7.3: the newest posts per plan, and this version reached me
  const posts = new Map<string, Obj[]>();
  if (mineRows.results.length) {
    const ids = mineRows.results.map((r) => r.id as string);
    const rows = await inChunks(ids, (part) => env.DB.prepare(
      `SELECT t.id, t.plan, t.uid, t.text, t.version, t.at, u.name FROM plan_posts t LEFT JOIN users u ON u.uid = t.uid
        WHERE t.plan IN (${part.map(() => "?").join(",")})
          AND (SELECT COUNT(*) FROM plan_posts x WHERE x.plan = t.plan AND x.id > t.id) < ${POSTS_ON_BOARD}
        ORDER BY t.id DESC`,
    ).bind(...part).all<{ id: number; plan: string; uid: string; text: string; version: number | null; at: number; name: string | null }>());
    for (const r of rows.results) {
      const l = posts.get(r.plan) ?? [];
      l.push({ id: r.id, name: r.name || "?", text: r.text, withSave: r.version !== null, at: r.at });
      posts.set(r.plan, l);
    }
    await env.DB.batch(mineRows.results.map((r) => env.DB.prepare(
      "UPDATE plan_follows SET seen_version = ?1 WHERE plan = ?2 AND uid = ?3 AND seen_version IS NOT ?1",
    ).bind(r.version, r.id, uid)));
  }
  // 3.8.0: with the plan's own tags, so my Anki carries them too (counts, and older followers' note ids)
  // 3.8.1: and its notes on cards and tags, so my Anki's Browse can show and change them
  const lean = (r: { deck: string; units: string; tagroot: string | null; tags: string | null; remarks: string | null }) => ({ deck: r.deck, units: (JSON.parse(r.units) as Obj[])
    .map((u) => (u.search || u.nids || u.cids || u.notes || (u.cards as unknown[] | null)?.length ? Object.fromEntries(Object.entries(u).filter(([k, x]) => x !== null && !(k === "cards" && !(x as unknown[]).length))) : { id: u.id, tags: u.tags, decks: u.decks, opens: u.opens })),
    ...(r.tagroot ? { tagroot: r.tagroot } : {}), ...(r.tagroot && r.tags ? { tags: JSON.parse(r.tags) } : {}),
    ...(r.remarks ? { remarks: JSON.parse(r.remarks) } : {}) });
  return {
    authored: authored.results.map((r) => ({ id: r.id, version: r.version, name: r.name, doc: lean(r) })),
    plans: mineRows.results.map((r) => ({ id: r.id, name: r.name, owner: r.owner, ownerName: r.owner_name || (r.owner ? "?" : "a former member"),
      version: r.version, ...(same ? { same: true } : { doc: JSON.parse(r.doc) }), share: r.share === 1, ...(r.team_ask === 1 ? { teamAsk: true } : {}), paused: r.paused === 1,
      sched: r.sched ? JSON.parse(r.sched) : null, early: r.early ?? 0, ...followDays(r),
      // 3.9.5 (S1): a crew's counts only from COUNTS_MIN counted; under it, none at all (an older add-on reads 0)
      followers: crew.get(r.id)?.n ?? 0, ...((crew.get(r.id)?.s ?? 0) >= COUNTS_MIN ? { crewDone: crew.get(r.id)!.done } : {}),
      posts: posts.get(r.id) ?? [] })),
    planOffers: offers.results.map((r) => ({ id: r.id, name: r.name, code: r.code, squad: r.squad, ownerName: r.owner_name || (r.owner ? "?" : "a former member") })),
    planInvites: await planInvites(env, uid),  // 3.8.1
  };
}
