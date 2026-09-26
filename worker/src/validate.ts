// Shapes. What firestore.rules checked field by field is checked here, and
// what the client used to coerce on read is coerced here on write, so the
// board only ever returns clean data.

import { HttpError } from "./util";

export type Json = null | boolean | number | string | Json[] | { [k: string]: Json };
type Obj = Record<string, unknown>;

export const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
export const NAME_MAX = 60;
export const NOTE_MAX = 80;
export const EMOJI_MAX = 16;      // UTF-16 units, as the rules' size() counted them
export const GUID_MAX = 40;
export const TRICKY_MAX = 3;
export const WEEK_DAYS_MAX = 9;   // eight days, and tomorrow for a friend ahead of me
export const DECKS_MAX = 200;
export const SIG_MAX = 20;
export const SQUAD_NAME_MAX = 24;
export const HOST_MAX = 128;

export const bad = (what: string) => new HttpError(400, "bad_" + what);

export const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
export const isInt = (v: unknown, lo = 0, hi = Number.MAX_SAFE_INTEGER): v is number =>
  typeof v === "number" && Number.isInteger(v) && v >= lo && v <= hi;
export const isStr = (v: unknown, max: number, min = 0): v is string =>
  typeof v === "string" && v.length >= min && v.length <= max;
export const isDate = (v: unknown): v is string => typeof v === "string" && DATE_RE.test(v) && !isNaN(Date.parse(v));
export const isIso = (v: unknown): v is string => isStr(v, 40, 10) && !isNaN(Date.parse(v as string));

/** Any one emoji: no letters, digits or spaces, at most 16 UTF-16 units
 *  (rules-v8). The client keeps exactly one cluster; this is the floor. */
export function isEmoji(v: unknown): v is string {
  return typeof v === "string" && v.length >= 1 && v.length <= EMOJI_MAX && /^[^A-Za-z0-9 ]+$/.test(v);
}

/** One printable line; what clean_note does in the client. */
export function oneLine(v: string, max: number): string {
  // eslint-disable-next-line no-control-regex
  return v.split(/\s+/).join(" ").trim().replace(/[\u0000-\u001f\u007f-\u009f]/g, "").slice(0, max);
}

export function displayName(v: unknown): string {
  if (!isStr(v, NAME_MAX, 1) || !v.trim()) throw bad("name");
  return oneLine(v, NAME_MAX);
}

/** The profile fields a sync carries. */
export function profile(v: unknown) {
  if (!isObj(v)) throw bad("profile");
  const out: { name?: string; emoji?: string | null; client_version?: string; tz?: number; rollover?: number } = {};
  if ("name" in v) out.name = displayName(v.name);
  if ("emoji" in v) {
    if (v.emoji !== null && v.emoji !== "" && !isEmoji(v.emoji)) throw bad("emoji");
    out.emoji = v.emoji ? (v.emoji as string) : null;
  }
  if ("clientVersion" in v) {
    if (!isStr(v.clientVersion, 20)) throw bad("client_version");
    out.client_version = v.clientVersion;
  }
  if ("tz" in v) {
    if (!isInt(v.tz, -900, 900)) throw bad("tz");
    out.tz = v.tz;
  }
  if ("rollover" in v) {
    if (!isInt(v.rollover, 0, 23)) throw bad("rollover");
    out.rollover = v.rollover;
  }
  return out;
}

function day(v: unknown): Obj {
  if (!isObj(v)) throw bad("week");
  const out: Obj = {};
  for (const k of Object.keys(v)) {
    const x = v[k];
    switch (k) {
      case "studied":
        if (typeof x !== "boolean") throw bad("week");
        out[k] = x;
        break;
      case "reviews": case "studyTimeMs": case "streak": case "newCards":
        if (!isInt(x)) throw bad("week");
        out[k] = x;
        break;
      case "accuracy":
        if (typeof x !== "number" || !(x >= 0 && x <= 100)) throw bad("week");
        out[k] = x;
        break;
      case "status":
        if (!isStr(x, NOTE_MAX)) throw bad("week");
        if (x) out[k] = oneLine(x, NOTE_MAX);
        break;
      default:
        throw bad("week");
    }
  }
  return out;
}

export function room(v: unknown): Obj {
  if (!isObj(v) || !isStr(v.host, HOST_MAX, 1) || !isIso(v.start)
      || !isInt(v.rounds, 1, 8) || !isInt(v.round, 5, 90) || !isInt(v.brk, 0, 30)) throw bad("room");
  return { host: v.host, start: v.start, rounds: v.rounds, round: v.round, brk: v.brk };
}

/** The week doc (2.9's shared/week): my last eight days in one document,
 *  plus what rides it. 3.0: a flagged card is its note guid, the deck's
 *  name and the day, never the card's text; crewmates read the text from
 *  their own copy of the note. */
export function week(v: unknown): Obj {
  if (!isObj(v)) throw bad("week");
  const out: Obj = { v: 1, days: {}, paused: false };
  for (const k of Object.keys(v)) {
    const x = v[k];
    switch (k) {
      case "v":
        break;
      case "days": {
        if (!isObj(x) || Object.keys(x).length > WEEK_DAYS_MAX) throw bad("week");
        const days: Obj = {};
        for (const [lb, d] of Object.entries(x)) {
          if (!isDate(lb)) throw bad("week");
          days[lb] = day(d);
        }
        out.days = days;
        break;
      }
      case "paused":
        if (typeof x !== "boolean") throw bad("week");
        out.paused = x;
        break;
      case "examDate": case "awayFrom": case "awayTo":
        if (!isDate(x)) throw bad("week");
        out[k] = x;
        break;
      case "liveUntil":
        if (!isIso(x)) throw bad("week");
        out[k] = x;
        break;
      case "tricky": {
        if (!Array.isArray(x) || x.length > TRICKY_MAX) throw bad("week");
        out[k] = x.map((t) => {
          if (!isObj(t) || !isStr(t.guid, GUID_MAX, 1) || !isDate(t.at)) throw bad("week");
          const deck = typeof t.deck === "string" ? oneLine(t.deck, 40) : "";
          return { guid: t.guid, deck, at: t.at };  // no `text`, ever
        });
        break;
      }
      case "room":
        out[k] = room(x);
        break;
      default:
        throw bad("week");
    }
  }
  if (("awayFrom" in out) !== ("awayTo" in out)) throw bad("week");
  return out;
}

/** Shared-deck progress, coerced as the client's _clean_decks did on read. */
export function decks(v: unknown): Obj[] {
  if (!Array.isArray(v) || v.length > DECKS_MAX) throw bad("decks");
  const out: Obj[] = [];
  for (const d of v) {
    if (!isObj(d) || !Array.isArray(d.sig) || !isInt(d.total, 1)) continue;
    const total = d.total;
    const seen = Math.min(isInt(d.seen) ? d.seen : 0, total);
    const e: Obj = {
      name: typeof d.name === "string" ? oneLine(d.name, 200) : "?",
      sig: d.sig.filter((g): g is string => isStr(g, GUID_MAX, 1)).slice(0, SIG_MAX),
      total, seen,
      mature: Math.min(isInt(d.mature) ? d.mature : 0, seen),
    };
    if (isInt(d.open)) e.open = Math.min(Math.max(d.open, seen), total);
    if (isInt(d.today) && isDate(d.day)) {
      e.today = d.today;
      e.day = d.day;
    }
    if (typeof d.ret === "number" && d.ret >= 0 && d.ret <= 100) e.ret = d.ret;
    out.push(e);
  }
  return out;
}

/** {day label: answers} for the profile heatmap; half a year at most. */
export function heatmap(v: unknown): Obj {
  if (!isObj(v) || !isObj(v.counts) || Object.keys(v.counts).length > 400) throw bad("heatmap");
  const counts: Obj = {};
  for (const [lb, n] of Object.entries(v.counts)) {
    if (!isDate(lb) || !isInt(n)) throw bad("heatmap");
    counts[lb] = n;
  }
  return { counts };
}

/** A squad member's row: memberShape, field for field. Absent fields are
 *  cleared (null), as the client's always-in-the-mask write did. */
export function memberRow(v: unknown) {
  if (!isObj(v)) throw bad("row");
  const allowed = new Set(["name", "day", "reviews", "studyTimeMs", "accuracy", "streak", "week", "emoji", "newCards"]);
  for (const k of Object.keys(v)) if (!allowed.has(k)) throw bad("row");
  const int = (k: string, hi = Number.MAX_SAFE_INTEGER) => {
    if (!(k in v) || v[k] === null) return null;
    if (!isInt(v[k], 0, hi)) throw bad("row");
    return v[k] as number;
  };
  if ("name" in v && !isStr(v.name, NAME_MAX)) throw bad("row");
  if ("day" in v && v.day !== null && !isDate(v.day)) throw bad("row");
  if ("emoji" in v && v.emoji !== null && !isStr(v.emoji, EMOJI_MAX)) throw bad("row");
  let accuracy: number | null = null;
  if ("accuracy" in v && v.accuracy !== null) {
    if (typeof v.accuracy !== "number" || !(v.accuracy >= 0 && v.accuracy <= 100)) throw bad("row");
    accuracy = v.accuracy;
  }
  return {
    name: typeof v.name === "string" ? v.name : null,
    day: (v.day as string | undefined) ?? null,
    reviews: int("reviews"),
    study_time_ms: int("studyTimeMs"),
    accuracy,
    streak: int("streak"),
    week: int("week", 7),
    emoji: (v.emoji as string | undefined) || null,
    new_cards: int("newCards"),
  };
}

export function squadName(v: unknown): string {
  if (typeof v !== "string") throw bad("name");
  const n = oneLine(v, 1000);
  if (!n || n.length > SQUAD_NAME_MAX) throw bad("name");
  return n;
}

/** A cheer: one emoji, a note of at most 80, `luck`, a card's guid. */
export function cheer(v: unknown) {
  if (!isObj(v)) throw bad("cheer");
  for (const k of Object.keys(v)) if (!["emoji", "note", "luck", "guid"].includes(k)) throw bad("cheer");
  if (!isEmoji(v.emoji)) throw bad("emoji");
  if ("note" in v && v.note !== null && !isStr(v.note, NOTE_MAX)) throw bad("note");
  if ("luck" in v && typeof v.luck !== "boolean") throw bad("luck");
  if ("guid" in v && v.guid !== null && !isStr(v.guid, GUID_MAX)) throw bad("guid");
  return {
    emoji: v.emoji,
    note: v.note ? oneLine(v.note as string, NOTE_MAX) || null : null,
    luck: v.luck === true ? 1 : null,
    guid: (v.guid as string | undefined) || null,
  };
}

export function settingsDoc(v: unknown) {
  if (!isObj(v) || !isInt(v.v, 0, 1000) || !isStr(v.at, 40, 1) || !isObj(v.settings)) throw bad("settings");
  for (const k of Object.keys(v)) if (!["v", "at", "settings"].includes(k)) throw bad("settings");
  const json = JSON.stringify(v.settings);
  if (json.length > 32 * 1024) throw bad("settings");
  return { v: v.v, at: v.at, json };
}
