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
  /** 3.8.0: a tag or subdeck as a search to paste into Anki's Browse. A
   *  versioned root (…_v12) matches any version: copies of a deck differ. */
  const ankiSearch = (kind, path) => {
    const esc = (x) => x.replace(/[\\"*_]/g, (c) => `\\${c}`);
    if (kind === "deck") return `"deck:${esc(path)}"`;
    const segs = path.split("::");
    return `"tag:${[esc(segs[0]).replace(/\\_v\d+$/i, "\\_v*"), ...segs.slice(1).map(esc)].join("::")}"`;
  };
  /** 3.8.0: a name as one part of an Anki tag (a plan's own tag, SLG 12):
   *  plans.ts tagPart, plans.py tag_part; change all three. */
  const slug = (s) => String(s).replace(/\s+/gu, "_").replace(/["*\\%]/g, "").replace(/:/g, "-")
    .replace(/_+/g, "_").replace(/^[_-]+|[_-]+$/g, "");
  const part = (name) => slug(name) || "tag";
  /** the plan's own part, from its name when its first tag is made (tagRoot, tag_root) */
  const root = (planName) => slug(planName).slice(0, 60).replace(/[_-]+$/, "") || "plan";
  return { word, name, kind, natural, ankiSearch, part, root };
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

/** 3.8.0: the plan's lines every week ({k, t, url, r}: r its weekdays,
 *  Monday "0"), as the Worker keeps them (plans.ts, EVERY_MAX). */
const Every = (() => {
  const MAX = 6;
  const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  /** what a save sends: lines with words and days, at most MAX */
  const clean = (lines) => (lines || []).filter((x) => x && /^[0-6]{1,7}$/.test(x.r || "") && Todo.LABEL[x.k] && String(x.t || "").trim())
    .slice(0, MAX).map((x) => ({ ...Todo.clean([x])[0], r: [...new Set(x.r)].sort().join("") }));
  const label = (r) => (r === "0123456" ? "every day" : r === "01234" ? "weekdays" : "every " + [...r].map((k) => DAYS[Number(k)]).join(", "));
  return { MAX, DAYS, clean, label };
})();

/** 3.8.1: notes for followers on a tag (a video, a chapter) or on one card
 *  (`remarks`: {id, tag | card, text}), as the Worker keeps them (plans.ts):
 *  one line, 280 characters, 300 a plan. Each follower's Anki shows them;
 *  never card text. In text: note | tag:PATH | … and note | card:GUID:N | …
 *  (N from 1, as cards: writes it). */
const Remarks = (() => {
  const MAX = 300, TEXT = 280;
  const clean = (s) => String(s || "").replace(/[\r\n\t]+/g, " ").replace(/[\u0000-\u001f]/g, "").replace(/\s+/g, " ").trim();
  const line = (r) => (r.card ? `note | card:${r.card[0]}:${r.card[1] + 1} | ${r.text}` : `note | tag:${r.tag} | ${r.text}`);
  /** the part after "note |": {card: [guid, ord], text} or {tag, text}, or null */
  function take(rest) {
    let m = /^card:(\S+?):(\d+)(?:\s+\|\s*|\s{2,})(.*)$/i.exec(rest);
    if (m) { const n = Number(m[2]); return m[1].length <= 40 && n >= 1 && n <= 1001 ? { card: [m[1], n - 1], text: m[3] } : { bad: true }; }
    m = /^tag:(.+?)(?:\s*\|\s*|\s{2,})(.*)$/i.exec(rest);
    return m ? { tag: m[1].trim(), text: m[2] } : null;
  }
  /** the same tag (any case) or the same card */
  const same = (a, b) => (a.card ? !!b.card && a.card[0] === b.card[0] && a.card[1] === b.card[1] : !!b.tag && a.tag.toLowerCase() === b.tag.toLowerCase());
  return { MAX, TEXT, clean, line, take, same };
})();

/** 3.8.1 (plans, round three): a deck tag's extras, a child named Extra,
 *  Extras, Bonus or Supplement (any case, _ and # aside). */
const EXTRA = /^(extras?|bonus|supplement)$/i;
const isExtra = (seg) => EXTRA.test(String(seg).replace(/[_#]/g, ""));

/** Searches about one person's own Anki (due_crew/plans.py, _PERSONAL). */
const PERSONAL =/(?:^|[\s("-])(?:deck:current|is:(?:due|new|learn|review|suspended|buried|susp)|rated:|prop:|introduced:|added:|edited:|resched:|flag:|nid:|cid:)/i;

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

/** 3.8.1 (plans, rethought): a date's work, not its delivery. The cards a
 *  date opens, over the study days until it's due (or until the next date
 *  opens), as the plan's own days weigh them (Sched): what keeping up takes
 *  each day. [[day, n]]; all on the next study day when its window has none. */
const Work = (() => {
  function spread(doc, u, total, days) {
    if (!(total > 0) || !u?.opens) return [];
    const sch = { days };
    const [a, b] = Sched.win(doc, u, 0);
    const ws = []; let whole = 0;
    for (let x = a; x <= b; x = addDays(x, 1)) { const w = Number(Sched.weight(doc, sch, x, 0)) || 0; ws.push([x, w]); whole += w; }
    if (!whole) {
      for (let i = 1; i <= 60; i++) { const x = addDays(b, i); if (Number(Sched.weight(doc, sch, x, 0))) return [[x, total]]; }
      return [[a, total]];
    }
    const out = []; let upto = 0, prev = 0;
    for (const [x, w] of ws) { upto += w; const q = Math.min(total, Math.ceil((total * upto) / whole)); if (q > prev) out.push([x, q - prev]); prev = q; }
    return out;
  }
  /** every day's work, {n, by: [[unit, n]]}, for each date of the plan */
  function map(doc, totalOf, days) {
    const out = new Map();
    for (const u of doc.units || []) {
      for (const [d, k] of spread(doc, u, totalOf(u), days)) {
        if (!out.has(d)) out.set(d, { n: 0, by: [] });
        const e = out.get(d); e.n += k; e.by.push([u, k]);
      }
    }
    return out;
  }
  /** runs of days over the pace (a quarter over it): [{a, b, top}] */
  function over(work, cap) {
    const runs = [];
    if (!cap) return runs;
    for (const d of [...work.keys()].sort()) {
      const v = work.get(d).n;
      if (v <= cap * 1.25) continue;
      const r = runs[runs.length - 1];
      if (r && addDays(r.b, 1) === d) { r.b = d; r.top = Math.max(r.top, v); } else runs.push({ a: d, b: d, top: v });
    }
    return runs;
  }
  return { spread, map, over };
})();

/** 3.9.2 (Sam's pick R3-A): the reviews a plan's dates bring, a day, by
 *  week: each day's new cards (Work's, the work a day asks) on a typical
 *  card's next six weeks (the share of cards seen k days after they start:
 *  simulated learners on FSRS's defaults at 90%, ahead.GENERIC's cards; the
 *  suite checks the two are the same). The new cards themselves aside.
 *  Cards, never minutes: the builder has no one's log. */
const Reviews = (() => {
  const CURVE = [1.0, 0.336, 0.15, 0.338, 0.446, 0.27, 0.1, 0.062, 0.104, 0.173, 0.133, 0.066, 0.054, 0.058, 0.058, 0.049, 0.046, 0.077, 0.174, 0.22, 0.134, 0.07, 0.065, 0.065, 0.083, 0.08, 0.049, 0.036, 0.04, 0.044, 0.047, 0.045, 0.04, 0.039, 0.038, 0.033, 0.029, 0.029, 0.032, 0.032, 0.034, 0.037];
  /** [{a: the week's first day, n: reviews a day}], from the first date to four weeks past the last */
  function weeks(work) {
    const ds = [...work.keys()].sort();
    if (!ds.length) return [];
    const per = new Map();
    for (const [d, e] of work) {
      for (let k = 1; k < CURVE.length; k++) { const x = addDays(d, k); per.set(x, (per.get(x) || 0) + e.n * CURVE[k]); }
    }
    const out = [], end = addDays(ds[ds.length - 1], 28);
    for (let a = ds[0]; a <= end; a = addDays(a, 7)) {
      let n = 0;
      for (let i = 0; i < 7; i++) n += per.get(addDays(a, i)) || 0;
      out.push({ a, n: n / 7 });
    }
    return out;
  }
  /** the busiest week, {wk: from 1, n}, or null */
  function peak(ws) {
    let best = null;
    ws.forEach((w, i) => { if (!best || w.n > best.n) best = { wk: i + 1, n: w.n }; });
    return best;
  }
  /** a number as the add-on's chart says it (ahead.r): never more exact than it is */
  const about = (x) => (x < 30 ? Math.round(x) : x < 200 ? Math.round(x / 5) * 5 : Math.round(x / 10) * 10).toLocaleString();
  return { CURVE, weeks, peak, about };
})();

/** 3.8.1 (plans, rethought): the deck's tags a date's name points at. "Renal
 *  physiology" finds #Videos::Renal::Physiology: every word of the name in
 *  the tag's path, one of them in its last part. Words, not card text: the
 *  tag tree is all the builder has. [[path, n]] best first, at most `max`. */
const Suggest = (() => {
  const STOP = new Set(["and", "the", "for", "with", "part", "lecture", "lec", "week", "day", "read", "watch", "chapter", "unit",
    "video", "videos", "intro", "introduction", "review", "notes", "extra", "extras", "session", "class"]);
  const words = (s) => String(s || "").toLowerCase().normalize("NFKD").replace(/[\u0300-\u036f]/g, "")
    .split(/[^a-z0-9]+/).filter((w) => w.length >= 3 && !STOP.has(w) && !/^\d+$/.test(w));
  // a name's numbers ("SLG 12", "Block 2"), and a tag part's own ones: a leading "03_" is the deck's order, not a number
  const nums = (s) => (String(s || "").match(/\d+/g) || []).map(Number);
  const partNums = (seg) => nums(String(seg).replace(/^[#^]?\d+[_ .-]+/, ""));
  // "arrhythmia" and "arrhythmias", "cardiac" and "cardio": the same word here
  const same = (a, b) => {
    const [s, l] = a.length <= b.length ? [a, b] : [b, a];
    if (s === l || (s.length >= 4 && l.startsWith(s))) return true;
    let k = 0; while (k < s.length && s[k] === l[k]) k++;
    return k >= 5 && k >= 0.8 * s.length;
  };
  function tags(name, rows, skip = () => false, max = 3) {
    const want = [...new Set(words(name))];
    if (!want.length) return [];
    const have = new Set(nums(name));
    const out = [];
    for (const [path, n] of rows) {
      if (!n) continue;
      const segs = String(path).split("::");
      const leaf = words(segs[segs.length - 1]);
      const all = words(segs.join(" "));
      const hit = want.filter((w) => all.some((x) => same(w, x))).length;
      if (!hit || !want.some((w) => leaf.some((x) => same(w, x)))) continue;
      // "SLG 12" is never SLG 3: a part a word matched that carries its own number must carry one of the name's
      if (have.size && segs.some((g) => want.some((w) => words(g).some((x) => same(w, x)))
          && partNums(g).length && !partNums(g).some((k) => have.has(k)))) continue;
      if (skip(path)) continue;
      out.push([path, n, hit / want.length, segs.length]);
    }
    out.sort((x, y) => y[2] - x[2] || y[3] - x[3] || x[1] - y[1]);
    // every word of the name, or all but one of three or more when nothing has them all: half a name is noise
    const need = out[0]?.[2] >= 1 || want.length <= 2 ? 1 : (want.length - 1) / want.length;
    return out.filter((x) => x[2] >= need - 1e-9).slice(0, max).map(([p, n]) => [p, n]);
  }
  return { words, tags };
})();

/** Round five: the prompts for your own AI (Text, and Anki's Your plans),
 *  as data in, words out, so the add-on says the very same (planner/prompts.py,
 *  its twin; the suite runs both). plan(): the plan so far, the format and
 *  the deck's tags, for planning dates; tags(): Tag by objective. Names and
 *  counts only, never a card. */
const Prompts = (() => {
  const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const pathOf = (key) => key.slice(key.indexOf(":") + 1);
  const kindOf = (key) => key.slice(0, key.indexOf(":"));
  const segs = (k) => pathOf(k).split("::");
  // 3.6.5: a tag whose last part has no readable name (a number, a hash) isn't listed
  const unreadable = (k) => { const w = segs(k).pop().replace(/^[#^$!]+/, ""); return /^\d+$/.test(w) || /^[0-9a-f-]{12,}$/i.test(w) || (/^[A-Za-z0-9_-]{24,}$/.test(w) && /\d/.test(w)); };
  const inRes = (k) => segs(k).slice(1).some((x) => x.startsWith("#"));
  const rank = (k) => { const last = segs(k).pop(); return last.startsWith("#") ? 0 : last.startsWith("^") ? 1 : 2; };
  const order = (ks) => ks.slice().sort((a, b) => rank(a) - rank(b));
  /** the deck's tags for the plan's prompt: what's ticked (cover, in the
   *  deck's order), whole; else the top levels, and resources (a # part)
   *  five levels down; a branch of mostly numbered tags is one line; 600
   *  lines at most. t: {kids(key), n(key), size}. {lines, more} */
  function tagLines(t, cover) {
    const keys = [];
    const collapsed = new Map();  // key -> how many unreadable tags it stands for
    const walk2 = (k, depth) => {
      if (keys.length >= 600 || unreadable(k)) return;
      keys.push(k);
      const ks = t.kids(k);
      const odd = ks.filter(unreadable).length;
      if (ks.length >= 10 && odd >= ks.length * 0.8) { collapsed.set(k, odd); return; }
      if (cover || depth < 2 || (inRes(k) && depth < 5)) for (const c of order(ks)) walk2(c, depth + 1);
    };
    for (const k of order(cover || t.kids("root:tag").concat(t.kids("root:deck")))) walk2(k, 0);
    const lines = keys.map((k) => `${kindOf(k)}:${pathOf(k)}  (${t.n(k).toLocaleString("en-US")} cards) ${Tags.name(pathOf(k))}`
      + (collapsed.has(k) ? ` [${collapsed.get(k).toLocaleString("en-US")} numbered tags under it, not listed]` : ""));
    return { lines, more: t.size - keys.length };
  }
  /** a: {name, deck, start, end, days, mode, daily, phases, units, lines,
   *  more, cover, ptags: [{name, path, size}], planned, pn: [line]} */
  function plan(a) {
    const dayNames = DAYS.filter((_, i) => a.days[i]).join(", ");
    const ph = a.phases || {};
    return [
      `I'm planning what to study in Anki, day by day, for "${a.name}" on the deck "${a.deck}". Due Crew opens each day's cards (unsuspends them) on the morning of that day, for me and everyone following the plan.`,
      "",
      "The plan so far:",
      `- Starts ${a.start}${a.end ? `, ends ${a.end}` : ", no end date yet"}.`,
      `- Study days: ${dayNames}.`,
      a.mode === "daily" && a.daily ? `- About ${a.daily} new cards a study day.` : a.mode === "end" && a.end ? "- Finish everything by the end date, at an even pace." : "- Each date's cards are for that date; nothing spreads over days unless its line says even.",
      ph.catchup ? `- Every ${ph.catchup}th week is a catch-up week: nothing new opens.` : null,
      ph.taper ? `- The last ${ph.taper} days before the end open nothing new.` : null,
      a.units ? `- ${a.units} dates are already planned (as text below the tags); keep or change them.` : null,
      "",
      "Write the plan in exactly this format, one line per date, and nothing else (no table; anything you want to explain goes on a line starting with #):",
      "",
      "YYYY-MM-DD | a short name (60 characters at most) | tag:FULL::TAG::PATH, tag:ANOTHER::PATH | due YYYY-MM-DD | even | for EVENT NAME",
      "YYYY-MM-DD | a short name (60 characters at most) | notes:ID ID ID | cards:ID:2 ID:1",
      "",
      "The whole format: https://duecrew.com/plan-text",
      "",
      "Rules:",
      "- The first part is the date those cards open: YYYY-MM-DD, or \"week 3\" for the Monday of the plan's third week. The part after it is the date's name, as it reads (\"Read: Chapter 3\" is a name there).",
      "- A tag brings every card under it. A whole chapter is its tag; a smaller part is a deeper tag (a section, a lecture). Copy tags exactly from the list below, the part before the two spaces; never invent one.",
      "- A subdeck works the same way: deck:FULL::DECK::PATH.",
      a.ptags.length ? "- This plan's own tags (my course's, like SLG 12) are listed below too; a date uses one by its name: tag:SLG 12. A resource kept to what one of them holds is the resource's tag, then in and the name: tag:#Videos::Pharm::Cephalosporins in SLG 12." : null,
      "- When a lecture is only part of a tag (two tags at once, or one without another), use an Anki search instead: search:tag:A tag:B -tag:C.",
      "- Several tags can open the same day: separate them with commas on one line.",
      "- Exact notes: notes:ID ID ID brings every card of those notes (every cloze), the IDs separated by spaces. Exact cards: cards:ID:N ID:N brings card N of each note (1 is the first). These IDs can hold any character but a space; copy each exactly. For a plan others follow, use notes: and cards:; numeric nids: and cids: only work in my own Anki. Use only IDs I give you below; never invent, guess or round one. At most 5,000 on a line; split a longer list over dates.",
      "- An Anki search never uses deck:current, is:due, is:new, is:learn, is:review, is:suspended, is:buried, rated:, prop:, introduced:, added:, edited:, resched:, flag:, nid: or cid: (they find different cards for each person), and stays under 500 characters.",
      "- Events are named days with no cards (a lecture, a quiz, an exam): YYYY-MM-DD | event | Micro quiz, or YYYY-MM-DD | event | Unit 3 test. A date that preps for one ends with | for Micro quiz, the name exactly as on its event line. A date after its event can name it too: it reads \"after Micro quiz\", review after it.",
      "- A date can ask for things cards can't measure, ticked by hand (up to 8): | watch: Lecture 14, renal clearance | read: chapter 6 | do: practice block 3. A link may follow the words: | watch: Lecture 14 https://example.com/l14",
      "- A note for followers on a video's or a chapter's tag, or on one card, shows in their Anki when it comes up: note | tag:FULL::TAG::PATH | Skip the last two minutes, or note | card:ID:N | This one's on the quiz. One line in your own words, 280 characters at most, one a tag or a card; never card text.",
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
      "- A date that preps for an event opens before that event, with time to study it.",
      "- Name each problem on its own line: # Problem: (something that's wrong), # Tradeoff: (a choice I might make differently), # Question: (something you can't tell from what I gave). Name the date. Skip what's fine.",
      "- If I only ask you to check the plan, answer with # lines only.",
      a.units ? "- Write only new dates, or what to add to a date already planned: a line with the same date and name as one below adds to it. Dates below stay as they are unless I ask to change them; then give the whole plan." : null,
      a.units ? "- Keep every notes:, cards:, nids: and cids: in the plan below on its line, exactly as written, unless I ask to move or drop it. Keep its note lines too." : null,
      "",
      "Example:",
      "2026-10-05 | Microcytic anemias | tag:Heme::Red_cells::Microcytic",
      "2026-10-06 | Hemolysis | tag:Heme::Red_cells::Hemolytic | due 2026-10-08 | even | for Heme quiz",
      "2026-10-07 | Lecture 12 cards | notes:Ab3$kL9qZ1 p&x8Hk!eQ2 | for Heme quiz",
      "2026-10-09 | event | Heme quiz",
      "2026-10-12 | Chapter 4 | tag:Chemistry::Unit_3::Chapter_4 | read: Chapter 4, sections 1 to 3 | for Unit 3 test",
      "2026-10-16 | event | Unit 3 test",
      "note | tag:Heme::Red_cells::Hemolytic | Lecture 9's slides cover this better than the book.",
      "",
      "My syllabus, learning objectives and exam dates, or what I want (edit this part):",
      "",
      "",
      "Note IDs or card IDs I have, and what each list is for (in Anki's browser: select them, right-click, Due Crew: copy as plan selector; paste here, or leave this empty):",
      "",
      "",
      a.ptags.length ? ["This plan's own tags (its name, its full tag in Anki, how big):",
        ...a.ptags.map((t) => `${t.name}  tag:${t.path}  (${t.size})`), ""] : [],
      `The deck's tags${a.cover ? " for what the plan covers" : ""} (tag or subdeck, card count, readable name)${a.more > 0 ? `; ${a.more.toLocaleString("en-US")} more aren't listed, ask me for a branch` : ""}:`,
      ...a.lines,
      a.planned ? ["", "Already planned:", a.planned] : [],
      a.pn.length ? ["", "What each planned date opens, as my Anki counted it (new to that date, already on an earlier date, picked notes not in my deck):", ...a.pn] : [],
    ].flat().filter((x) => x !== null).join("\n");
  }
  /** Tag by objective's standing tags: each [its line, its IDs, its short
   *  line]; past 2,000 IDs in all, a tag's lists are a count. {lines, cut} */
  function standing(items) {
    const out = { lines: [], cut: false };
    let ids = 0;
    for (const [line, m, short] of items) {
      if (ids + m <= 2000) { ids += m; out.lines.push(line); continue; }
      out.cut = true;
      out.lines.push(short);
    }
    return out;
  }
  /** Tag by objective, the deck's tags for whole-tag answers: 300 at most,
   *  in the deck's order, never Due Crew's own. t: {keys, order(key), n(key)} */
  const tagList = (t) => t.keys.filter((k) => kindOf(k) === "tag" && !pathOf(k).startsWith("DueCrew::"))
    .sort((a, b) => t.order(a) - t.order(b)).slice(0, 300)
    .map((k) => `tag:${pathOf(k)}  (${t.n(k).toLocaleString("en-US")} cards)`);
  /** a: {name, deck, root, has: plan tags?, standing: {lines, cut}, list} */
  function tags(a) {
    return [
      `I'm tagging my Anki cards for "${a.name}" on the deck "${a.deck}" by my course's own objectives. Due Crew puts each tag on the cards of everyone following the plan, in their own Anki.`,
      "",
      "For each objective I give, write one line, and nothing else (anything you want to explain goes on a line starting with #):",
      "",
      "tag | NAME | notes:ID ID ID",
      "tag | NAME | cards:ID:2 ID:1",
      "",
      `In Anki each one becomes the tag DueCrew::${a.root}::NAME (spaces as _).`,
      "",
      "The whole format: https://duecrew.com/plan-text",
      "",
      "Rules:",
      "- NAME is the objective's short name as my course writes it (SLG 12, Week 3, Lecture 14), 40 characters at most.",
      "- The IDs are from the #guid column of the text file I attached (my cards, exported from Anki), copied exactly; they can hold any character but a space. Use only IDs from that file; never invent, guess or round one.",
      "- notes:ID brings every card of the note. When only some of a note's cards fit (one cloze of three), use cards:ID:N instead, N a card's number from the #cards column (1 is the first).",
      "- Read each card's text to judge whether it serves the objective. A card can be on more than one objective; leave out a card that only touches one in passing.",
      "- When every card under one of my deck's tags fits an objective, write the tag instead of the IDs: tag | NAME | tag:FULL::TAG::PATH, copied exactly from the list below or the #tags column.",
      "- At most 5,000 notes and 5,000 cards on a line; a bigger objective is two names (SLG 12a, SLG 12b).",
      "- Never quote or copy card text into your answer.",
      "- After each tag line, one # line: what you took, what you left out, and why.",
      "- If an objective has no cards in the file, say so on a # line; don't invent any.",
      a.has ? "- This plan's tags as they stand are below. A line with the same name adds to that tag; to change one, say so on a # line." : null,
      "- A note for followers on one of the tags, or on one card, shows in their Anki: note | tag:NAME | your words, or note | card:ID:N | your words. One line, 280 characters at most; never card text.",
      "",
      "Example:",
      "tag | SLG 12 | notes:Ab3$kL9qZ1 p&x8Hk!eQ2",
      "# SLG 12: the receptor-and-effect cards from the video and chapter 5; left out 9 on toxicity (SLG 15).",
      "tag | SLG 14 | tag:#Book::Pharm::Ch07",
      "# SLG 14: the whole chapter fits.",
      "tag | Unit 3 | tag:Chemistry::Unit_3",
      "# Unit 3: every card under the unit's tag fits.",
      "",
      "My objectives (edit this part):",
      "",
      "",
      a.has ? ["This plan's tags now, as they stand (a line with the same name adds to one):", ...a.standing.lines,
        a.standing.cut ? "A tag above with a count in brackets has more IDs than fit here; the whole lists are in Text › Edit the whole plan." : null, ""] : [],
      "Tags in my deck, for whole-tag answers (tag, card count):",
      ...a.list,
    ].flat().filter((x) => x !== null).join("\n");
  }
  return { tagLines, plan, standing, tagList, tags };
})();

/** 3.8.0: a plan's squad (its team until then), as the board's Squads tab
 *  draws it (board.py _plan_squad_html: change one, change both): who
 *  showed up today (answered one of the plan's cards), its bingo, then Ask
 *  the squad and its threads. Opt-in; never anyone's numbers. Each click is
 *  one request. The server still calls it a team (/plans/{id}/team). */
const PlanSquad = (() => {
  const LINES = [[0, 1, 2], [3, 4, 5], [6, 7, 8], [0, 3, 6], [1, 4, 7], [2, 5, 8], [0, 4, 8], [2, 4, 6]];
  const CELLS = [0, 1, 2, 3, 5, 6, 7, 8];
  const wkOf = (d) => {
    const x = parseIso(d); const dow = (x.getUTCDay() + 6) % 7; x.setUTCDate(x.getUTCDate() - dow + 3);
    const y = x.getUTCFullYear(); const first = new Date(Date.UTC(y, 0, 4));
    return `${y}-W${String(1 + Math.round(((x - first) / 86400000 - 3 + ((first.getUTCDay() + 6) % 7)) / 7)).padStart(2, "0")}`;
  };
  const ago = (t) => { const m = Math.round((Date.now() / 1000 - t) / 60); return m < 1 ? "now" : m < 60 ? `${m}m` : m < 1440 ? `${Math.round(m / 60)}h` : m < 2880 ? "yesterday" : `${Math.round(m / 1440)}d`; };
  /** "3 of 9 · one away from bingo" (team.py bingo_line: change one, change both). */
  function bingoLine(ev) {
    const done = (c) => (c === 4 ? ev.middle.done : ev.squares[CELLS.indexOf(c)].done);
    const stamps = ev.squares.filter((q) => q.done).length + (ev.middle.done ? 1 : 0);
    const left = Math.min(...LINES.map((l) => l.filter((c) => !done(c)).length));
    const state = ev.lines >= 8 ? "the whole card" : ev.lines ? (ev.lines === 1 ? "BINGO" : `${ev.lines} lines`)
      : left === 1 ? "one away from bingo" : `${left} away from bingo`;
    return `${stamps} of 9 · ${state}`;
  }
  const got = {};  // plan id: {team, busy, replyTo, bingoOpen}, kept while the page lives
  /** One plan's squad. redraw: the board's; on.left / on.joined: after a
   *  leave or a join here, so the board's pills follow. */
  function view(id, redraw, on = {}) {
    const s = got[id] || (got[id] = { team: null, busy: false, replyTo: null, bingoOpen: false });
    if (!s.team) {
      if (!s.busy) {
        s.busy = true;
        api("GET", `/plans/${id}/team?wk=${wkOf(today())}`).then((r) => { s.team = r; }).catch(() => { s.team = { failed: true }; })
          .finally(() => { s.busy = false; redraw(); });
      }
      return h("p", { class: "muted small" }, "Loading…");
    }
    const team = s.team;
    const st = h("span", { class: "status", role: "status" });
    const again = (p, bad = "That didn't work. Try again.") => p.then(() => { s.team = null; redraw(); }).catch((err) => {
      st.className = "status bad"; st.textContent = err.status === 429 ? "That's a lot of questions today. Try tomorrow."
        : err.body?.error === "team_full" ? "This squad is full." : bad; });
    if (team.failed) return h("p", { class: "muted small" }, "Couldn't load the squad. ", h("button", { class: "linkish", onclick: () => { s.team = null; redraw(); } }, "Try again"));
    if (!team.on) {
      return h("div", { class: "panel", style: "max-width:560px;margin:0 auto;text-align:left" },
        h("h4", {}, h("span", {}, team.count ? `${team.count.toLocaleString()} in its squad` : "No one in its squad yet")),
        h("p", { class: "muted small", style: "margin:0" }, "The squad sees that you showed up today, and your questions and answers; your progress counts for the plan’s authors. Never your numbers."),
        h("div", { class: "row" }, h("button", { onclick: (e) => { e.target.disabled = true; again(api("POST", `/plans/${id}/team`).then((r) => { on.joined?.(); return r; })); } }, "Join its squad"), st));
    }
    const ask = h("input", { placeholder: "Ask anything…", maxlength: 280, "aria-label": "Ask the squad" });
    const send = () => { const text = ask.value.trim(); if (text) again(api("POST", `/plans/${id}/asks`, { text })); };
    ask.addEventListener("keydown", (e) => { if (e.key === "Enter") send(); });
    // 3.8.21: a person's Pip where the emoji was (on.pip, from the board's Squads: board._plan_squad_html's who_face)
    const pipOf = (x) => (on.pip ? on.pip(x) : null);
    const who = (x) => (x.mine ? "You" : [pipOf(x) || (x.emoji ? `${x.emoji} ` : ""), h("b", {}, x.name)]);
    const thread = (a) => {
      const reps = a.replies.map((r) => h("div", { class: "rep" }, h("b", {}, r.mine ? "You" : r.name), r.author ? " (author)" : "", `: ${r.text}`,
        a.mine && !r.mine ? h("button", { class: "linkish", onclick: () => again(api("POST", `/plans/${id}/asks/${r.id}/helped`, { on: !r.helped })) }, r.helped ? "Helped ✓" : "That helped")
          : r.helped ? h("span", { class: "ok" }, " ✓ helped") : null,
        r.remove ? h("button", { class: "linkish", onclick: () => again(api("DELETE", `/plans/${id}/asks/${r.id}`)) }, "Remove") : null));
      const bits = [a.topic, a.replies.length ? `${a.replies.length} repl${a.replies.length === 1 ? "y" : "ies"}` : ""].filter(Boolean).join(" · ");
      let box = null;
      if (s.replyTo === a.id) {
        const r = h("input", { placeholder: "Your answer…", maxlength: 280, "aria-label": "Your answer" });
        const go = () => { const text = r.value.trim(); if (text) { s.replyTo = null; again(api("POST", `/plans/${id}/asks`, { text, parent: a.id })); } };
        r.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
        requestAnimationFrame(() => r.focus());
        box = h("div", { class: "ask3" }, r, h("button", { onclick: go }, "Reply"));
      }
      return h("div", { class: "tq" },
        h("div", { class: "t" }, a.guid ? h("span", {}, who(a), " on a card") : h("span", {}, who(a), `: ${a.text}`), h("span", { class: "m" }, ago(a.act || a.at))),
        a.guid ? h("div", {}, `“${a.text}”`) : null, ...reps, box,
        h("div", { class: "t" }, h("span", { class: "card" }, bits), h("span", { class: "m" },
          h("button", { class: "linkish", onclick: () => { s.replyTo = s.replyTo === a.id ? null : a.id; redraw(); } }, a.guid ? "Answer" : "Reply"),
          a.remove ? h("button", { class: "linkish quiet2", onclick: () => again(api("DELETE", `/plans/${id}/asks/${a.id}`)) }, "Remove") : null)));
    };
    const faces = h("div", { class: "faces" }, team.faces.map((f) => h("div", { class: `face${f.shown ? "" : " away"}` },
      h("span", { class: "e" }, pipOf(f) || face(f.emoji, f.name)), h("b", {}, f.uid === me.uid ? "You" : f.name))),
      team.more ? h("div", { class: "face away" }, h("span", { class: "e" }, "+"), h("b", {}, `${team.more} more`)) : null);
    const b = team.bingo;
    let bingo = null;
    if (b) {
      const cell = (c) => (c === 4 ? b.ev.middle.done : b.ev.squares[CELLS.indexOf(c)].done);
      const sq = (c) => (c === 4 ? b.card.middle : b.card.squares[CELLS.indexOf(c)]);
      bingo = h("div", { class: "panel" }, h("h4", {}, h("span", {}, "Squad bingo"), h("span", { class: "muted small", style: "font-weight:500" }, bingoLine(b.ev).split(" · ")[0])),
        h("div", { class: "bgrow" }, h("span", { class: "bgmini" }, [0, 1, 2, 3, 4, 5, 6, 7, 8].map((c) => h("i", { class: cell(c) ? "on" : "" }))),
          h("span", { class: "small" }, bingoLine(b.ev).split(" · ")[1]), h("span", { style: "flex:1" }),
          h("button", { class: "linkish", onclick: () => { s.bingoOpen = !s.bingoOpen; redraw(); } }, s.bingoOpen ? "Close" : "Open")),
        s.bingoOpen ? h("div", { class: "bggrid" }, [0, 1, 2, 3, 4, 5, 6, 7, 8].map((c) => h("div", { class: cell(c) ? "on" : "" },
          h("span", {}, sq(c).icon || ""), h("b", {}, c === 4 ? sq(c).name : sq(c).title),
          h("small", {}, c === 4 ? `${b.ev.middle.have} of ${b.ev.middle.goal}` : sq(c).rule || "")))) : null);
    }
    const leave = h("button", { class: "linkish", onclick: (e) => {
      if (e.target.dataset.sure !== "1") { e.target.dataset.sure = "1"; e.target.textContent = "Leave? Your questions and answers stay. Click again"; return; }
      e.target.disabled = true;
      api("DELETE", `/plans/${id}/team`).then(() => { delete got[id]; on.left?.(); }).catch(() => { e.target.disabled = false; e.target.textContent = "Couldn’t leave. Try again."; });
    } }, "Leave");
    return h("div", { class: "psq" },
      h("div", { class: "panel" }, h("h4", {}, h("span", {}, "Showed up today"),
        h("span", { class: "muted small", style: "font-weight:500" }, `${team.shown} of ${team.count}${team.streak > 1 ? ` · ${team.streak} days running` : ""}`)), faces),
      bingo,
      h("div", { class: "panel" }, h("h4", {}, h("span", {}, "Ask the squad")),
        h("div", { class: "ask3" }, ask, h("button", { onclick: send }, "Ask")), st,
        team.asks.length ? team.asks.map(thread) : h("p", { class: "muted small", style: "margin:0" }, "No questions yet.")),
      h("div", { class: "sqline" }, h("button", { class: "linkish", onclick: () => go(`/plans/${id}`) }, "Open the plan"), " · ", leave));
  }
  const forget = (id) => { delete got[id]; };
  return { view, forget, bingoLine };
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
  // when the author's Anki sent it (GET /plans/trees' `at`, seconds), as a day here
  const treeAt = raw.at ? iso(new Date(raw.at * 1000 - new Date().getTimezoneOffset() * 60000)) : null;

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
  // ---- 3.8.1: a deck tag's extras (Extra, Bonus): with them, or without ----
  const extraKids = (key) => (kindOf(key) === "tag" ? kidsOf(key).filter((k) => isExtra(pathOf(k).split("::").pop())) : []);
  /** the tag less its extras, as an Anki search: "tag:X" -"tag:X::Extra" */
  const withoutQ = (path) => [Tags.ankiSearch("tag", path), ...extraKids(`tag:${path}`).map((k) => `-${Tags.ankiSearch("tag", pathOf(k))}`)].join(" ");
  let extraMap = null;  // each without-extras search: its tag, worked out once
  const extrasOf = (q) => {
    if (!extraMap) { extraMap = new Map(); for (const k of count.keys()) if (extraKids(k).length) extraMap.set(withoutQ(pathOf(k)), pathOf(k)); }
    return extraMap.get(q) || null;
  };
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
  let pace, cover, start;
  /** the pace, what to cover and the start, as the doc says: when the page
   *  opens, and whenever the doc is replaced (History › Undo, a save) */
  function fromDoc() {
    // a new plan starts at Anki's own 20 new cards a day
    pace = { mode: doc.units.length ? "placed" : "daily", days: [1, 1, 1, 1, 1, 1, 1], daily: 20, ...(doc.pace || {}) };
    if (!doc.pace && doc.end) pace.mode = "end";
    cover = new Set(pace.cover || []);
    start = Sched.start(doc) || start || nextMonday();  // no dates yet: the start set here stays
  }
  fromDoc();
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
  // Undo, a step at a time, of what isn't saved: each change keeps the state
  // before it (the doc, the pace, what to cover, the start, the name). Typing
  // in one box is one step. A save or a reload starts over: Undo never crosses one.
  const UNDO_MAX = 20;
  const undos = [];
  let undoLost = false;  // older steps fell off: undoing all of them isn't the saved plan
  let undoKey = null;    // the box being typed in
  let now0 = null;       // the state after the last change
  const snap = () => JSON.stringify({ doc, pace, cover: [...cover], start, meta, auto: [...auto] });
  const undoBtn = h("button", { class: "quiet undo", hidden: true, title: `Undo the last change (${/Mac|iP/.test(navigator.platform) ? "⌘Z" : "Ctrl+Z"})`, onclick: () => undo() }, "Undo");
  const mark = (key) => {
    const was = now0;
    now0 = snap();
    if (was !== null && was !== now0 && !(key && key === undoKey)) {
      undos.push(was);
      if (undos.length > UNDO_MAX) { undos.shift(); undoLost = true; }
    }
    undoKey = key || null;
    undoBtn.hidden = !undos.length;
    dirty = true; status.className = "status"; status.textContent = "Unsaved changes";
    document.querySelector(".savebar")?.classList.remove("clean");  // C6: on a phone, Save shows now
  };
  /** the page's state is what it loaded or saved: nothing to undo */
  const settled = () => { undos.length = 0; undoLost = false; undoKey = null; now0 = snap(); undoBtn.hidden = true; };
  function undo() {
    const s = undos.pop();
    if (!s) return;
    const st = JSON.parse(s);
    doc = st.doc; pace = st.pace; study.days = pace.days; cover = new Set(st.cover); start = st.start; meta = st.meta;
    auto.clear(); for (const x of st.auto) auto.add(x);
    splitting = null; moving = null; tagEdit = null; tagDrop = null; newEv = null; movingEv = null; rmkEdit = null; note = "";
    now0 = s; undoKey = null; undoBtn.hidden = !undos.length;
    if (!undos.length && !undoLost) { dirty = false; status.className = "status"; status.textContent = ""; }
    else { status.className = "status"; status.textContent = "Unsaved changes"; }
    draw();
  }
  /** the doc replaced from the server (History › Undo, a save): the pace and the rest follow it */
  function reload(d) {
    doc = structuredClone(d);
    for (const u of doc.units) if (u.check) { (doc.reviews ||= []).push({ day: u.check, from: u.id, to: u.id }); delete u.check; }
    base = structuredClone(doc);
    fromDoc(); study.days = pace.days;
    auto.clear(); for (const u of doc.units) if (!u.name || u.name === autoName(u)) auto.add(u.id);
    splitting = null; moving = null; tagEdit = null; tagDrop = null;
    dirty = false;
    settled();
  }
  const narrow = () => matchMedia("(max-width: 700px)").matches;
  let coverOpen = null;   // H3: What to cover, open or not, across redraws (a phone opens it while there are no dates)
  let paceOpen = false;   // C6: the pace, folded to one line on a phone
  window.onbeforeunload = () => (dirty ? true : undefined);
  // B8: ⌘S / Ctrl+S saves (only while this page is the one showing); ⌘Z / Ctrl+Z
  // undoes the last change, unless a text box has the focus (its own undo, then)
  const typing = (t) => !!t && (t.isContentEditable || t.tagName === "TEXTAREA"
    || (t.tagName === "INPUT" && !/^(checkbox|radio|button|submit|reset|range|color|file)$/i.test(t.type)));
  document.onkeydown = (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s" && document.contains(saveBtn)) { e.preventDefault(); if (dirty) save(); }
    if ((e.metaKey || e.ctrlKey) && !e.shiftKey && !e.altKey && e.key.toLowerCase() === "z" && document.contains(saveBtn)
        && undos.length && !typing(e.target)) { e.preventDefault(); undo(); }
  };

  // ---- units and sources ----
  const srcs = (u) => [...(u.tags || []).map((t) => `tag:${t}`), ...(u.decks || []).map((d) => `deck:${d}`)];
  // 3.8.1: a tag kept without its extras (its "Without" search) is on the calendar too
  const placedKeys = () => new Set(doc.units.flatMap((u) => [...srcs(u), ...(u.search || []).map((q) => { const p = extrasOf(q); return p ? `tag:${p}` : null; }).filter(Boolean)]));
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
  // 3.8.1 (plans, rethought): on the calendar, a last word the deck has in two
  // places takes its parent's ("Renal › Physiology", not "Physiology")
  const leafSeen = new Map();
  for (const k of count.keys()) { const w = `${kindOf(k)}:${pathOf(k).split("::").pop().toLowerCase()}`; leafSeen.set(w, (leafSeen.get(w) || 0) + 1); }
  const chipLabel = (key, placed) => {
    const segs = pathOf(key).split("::");
    const twice = segs.length > 1 && (leafSeen.get(`${kindOf(key)}:${segs[segs.length - 1].toLowerCase()}`) || 0) > 1;
    return twice ? `${Tags.word(segs[segs.length - 2])} › ${label(key, placed)}` : label(key, placed);
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
  // 3.8.1: a date's picked cards (single cards and IDs) are one chip, read by
  // the deck tags they sit under in the author's Anki (`pl`, [[path, n]]):
  // "Herpes Viruses · 88 picked"; "88 picked" until that Anki has said
  const picksN = (u) => (u.cards || []).length + idsN(u);
  const picksSig = (x) => JSON.stringify([x.cards || [], x.notes || [], x.nids || [], x.cids || []]);
  /** `pl` while the date's picks are as they loaded (the server keeps it so, as `idn`) */
  const plOf = (u) => {
    const was = (base.units || []).find((x) => x.id === u.id);
    return Array.isArray(u.pl) && u.pl.length && was && picksSig(was) === picksSig(u) ? u.pl : null;
  };
  const plWord = (p) => Tags.word(String(p).split("::").pop()).replace(/^\d+ · /, "");  // a video's name, not its number
  const picksText = (u) => { const pl = plOf(u); return pl ? `${plWord(pl[0][0])} · ${pl[0][1].toLocaleString()} picked` : `${picksN(u).toLocaleString()} picked`; };
  /** every label, and what no label covers: "Herpes Viruses 88 · Hepatitis 12 · 3 more" */
  const picksList = (u) => {
    const pl = plOf(u);
    if (!pl) return null;
    const rest = picksN(u) - pl.reduce((a, [, k]) => a + k, 0);
    return [...pl.map(([p, k]) => `${plWord(p)} ${k.toLocaleString()}`), rest > 0 ? `${rest.toLocaleString()} more` : null].filter(Boolean).join(" · ");
  };
  // 3.8.1: a cut, "Cephalosporins · SLG 12": a tag kept to the cards one of the plan's own tags holds
  const cutName = (c) => { const t = (doc.tags || []).find((x) => x.id === c.in); return `${Tags.word(c.tag.split("::").pop())}${t ? ` · ${t.name}` : ""}`; };
  const autoName = (u) => {
    const ks = srcs(u);
    if (!ks.length && (u.cut || []).length) return `${cutName(u.cut[0])}${u.cut.length > 1 ? ` + ${u.cut.length - 1} more` : ""}`.slice(0, 60);
    const wo = (u.search || []).map(extrasOf).find(Boolean);  // 3.8.1: a tag without its extras is still that tag
    if (!ks.length && wo) return label(`tag:${wo}`).slice(0, 60);
    if (!ks.length) return (u.search || []).length ? "Search" : hasIds(u) ? idsText(u) : (u.cards || []).length ? `${u.cards.length} single card${u.cards.length === 1 ? "" : "s"}` : "?";
    return `${label(ks[0])}${ks.length > 1 ? ` + ${ks.length - 1} more` : ""}`.slice(0, 60);
  };
  const auto = new Set(doc.units.filter((u) => !u.name || u.name === autoName(u)).map((u) => u.id));
  const renameAll = () => { for (const u of doc.units) if (auto.has(u.id)) u.name = autoName(u); };
  /** a date named by hand; cleared, it's named for what's on it again (the server refuses no name) */
  const nameIt = (u, v) => {
    if (String(v).trim()) { u.name = v; auto.delete(u.id); } else { auto.add(u.id); u.name = autoName(u); }
    mark(`name:${u.id}`);
  };
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
    doc.units = doc.units.filter((u) => srcs(u).length || (u.cards || []).length || (u.search || []).length || (u.cut || []).length || hasIds(u));
    const ids = new Set(doc.units.map((u) => u.id));
    if (doc.reviews) { doc.reviews = doc.reviews.filter((r) => ids.has(r.from) && ids.has(r.to)); if (!doc.reviews.length) delete doc.reviews; }
  };
  function takeIds(u) { delete u.nids; delete u.cids; delete u.notes; delete u.idn; delete u.idr; }
  // 3.8.0: the plan's own tags (SLG 12): made in an author's Anki (Browse ›
  // Due Crew: tag for a plan…, exact notes) or here (Text, the AI: a tag's,
  // a subdeck's or a search's cards). Each follower's Anki puts them on its
  // notes as DueCrew::<tagroot>::<name>, so a date uses one as any tag.
  const ptags = () => doc.tags || [];
  const tagRootNow = () => doc.tagroot || Tags.root(meta.name || plan.name);
  const ptagPath = (t) => `DueCrew::${tagRootNow()}::${Tags.part(t.name)}`;
  const ptagByName = (name) => { const want = Tags.part(name).toLowerCase(); return ptags().find((t) => Tags.part(t.name).toLowerCase() === want); };
  const ptagFrom = (t) => [...(t.tags || []).map((x) => `tag:${x}`), ...(t.decks || []).map((x) => `deck:${x}`), ...(t.search || []).map((x) => `search:${x}`)];
  /** how big: its cards in an author's Anki once it's there (the tree), else its notes */
  const ptagSize = (t) => {
    const k = `tag:${ptagPath(t)}`, m = (t.notes || []).length, c = (t.cards || []).length;
    if (count.has(k) && !c) return `${n(k).toLocaleString()} cards`;  // Anki's count is of whole notes: not with single cards
    const parts = [m ? `${m.toLocaleString()} note${m === 1 ? "" : "s"}` : "", c ? `${c.toLocaleString()} single card${c === 1 ? "" : "s"}` : ""].filter(Boolean);
    return parts.length ? parts.join(", ") : count.has(k) ? `${n(k).toLocaleString()} cards` : "counted in your Anki soon";
  };
  /** a plan tag the author's Anki hasn't counted yet: no number, rather than 0 */
  const uncounted = (k) => !count.has(k) && ptags().some((t) => `tag:${ptagPath(t)}` === k);
  function putTags(list) { if (list.length) { doc.tagroot = tagRootNow(); doc.tags = list; } else delete doc.tags; }
  // 3.8.1: notes for followers on a tag or a card (Remarks), with the plan
  const remarks = () => doc.remarks || [];
  function putRemarks(list) { if (list.length) doc.remarks = list; else delete doc.remarks; }
  const tagRemark = (path) => remarks().find((r) => r.tag && r.tag.toLowerCase() === String(path).toLowerCase());
  /** the note a row of this tag shows: its own, or the nearest tag above it's (as in Anki) */
  const remarkOn = (path) => {
    if (!path) return null;
    const p = String(path).toLowerCase();
    return remarks().filter((r) => r.tag && (p === r.tag.toLowerCase() || p.startsWith(`${r.tag.toLowerCase()}::`)))
      .sort((a, b) => b.tag.length - a.tag.length)[0] || null;
  };
  /** a tag's note written, changed, or (empty) taken off */
  function setTagRemark(path, text) {
    const t = Remarks.clean(text).slice(0, Remarks.TEXT);
    const r = tagRemark(path);
    if (!t) { if (r) { putRemarks(remarks().filter((x) => x !== r)); mark(); } return; }
    if (r) { if (r.text !== t) { r.text = t; mark(); } return; }
    if (remarks().length >= Remarks.MAX) { note = `A plan holds up to ${Remarks.MAX} notes on tags and cards.`; return; }
    putRemarks([...remarks(), { id: uid8(), tag: path, text: t }]);
    mark();
  }
  // 3.8.1: a cut's search, q, is the same as the cut and stays among the
  // date's searches, so an add-on before 3.8.1 opens the same cards
  const cutQ = (tagPath, t) => `${Tags.ankiSearch("tag", ptagPath(t))} ${Tags.ankiSearch("tag", tagPath)}`;
  const cutOf = (u, q) => (u.cut || []).find((c) => c.q === q);
  /** 3.8.1: a tag where it sits in a search, whole (SLG_1 isn't in SLG_12), as Tags.ankiSearch
   *  writes it or plain (an AI's search:tag:DueCrew::…); the bound is plans.ts reroot's */
  const tagRe = (path, flags = "i") => {
    const e = (x) => x.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return new RegExp(`(${e(Tags.ankiSearch("tag", path).slice(1, -1))}|${e(`tag:${path}`)})(?=::|$|[\\s")])`, flags);
  };
  /** a search onto a date, if it has room (a date holds 10; a cut's search must stay) */
  const addSearch = (u, q) => {
    if ((u.search || []).includes(q)) return true;
    if ((u.search || []).length >= 10) { note = "A date holds up to 10 searches and cuts."; return false; }
    u.search = [...(u.search || []), q];
    return true;
  };
  const isOwnTag = (path) => path.toLowerCase().startsWith(`duecrew::${tagRootNow().toLowerCase()}::`);
  /** each date's cuts as the plan's tags are now: one whose tag went is its
   *  whole tag again; a renamed tag's cut searches by its new name */
  function syncCuts() {
    for (const u of doc.units) {
      if (!(u.cut || []).length) { delete u.cut; continue; }
      const keep = [];
      for (const c of u.cut) {
        const t = ptags().find((x) => x.id === c.in);
        if (!t) { takeSearch(u, c.q); u.tags = [...new Set([...(u.tags || []), c.tag])]; continue; }
        const q = cutQ(c.tag, t);
        if (q !== c.q) { const was = u.sn?.[c.q]; takeSearch(u, c.q); if (was != null) u.sn = { ...(u.sn || {}), [q]: was }; c.q = q; }
        if (!(u.search || []).includes(q)) u.search = [...(u.search || []), q];  // in place of its old one
        keep.push(c);
      }
      if (keep.length) u.cut = keep; else delete u.cut;
    }
  }
  /** a tag on a date kept to one of the plan's tags (its id), or all of it again (null) */
  function setCut(u, tagPath, inId) {
    const had = (u.cut || []).find((c) => c.tag === tagPath);
    if (had) { takeSearch(u, had.q); u.cut = u.cut.filter((c) => c !== had); if (!u.cut.length) delete u.cut; }
    u.tags = (u.tags || []).filter((t) => t !== tagPath);
    const t = inId && ptags().find((x) => x.id === inId);
    if (!t) { u.tags.push(tagPath); return; }
    const q = cutQ(tagPath, t);
    if (!addSearch(u, q)) { u.tags.push(tagPath); return; }
    u.cut = [...(u.cut || []), { tag: tagPath, in: t.id, q }];
  }
  function takeCut(u, c) {
    takeSearch(u, c.q);
    u.cut = (u.cut || []).filter((x) => x !== c);
    if (!u.cut.length) delete u.cut;
  }
  /** a tag renamed (or gone, newPath null): the dates using it follow, as a tag and in their searches */
  function retag(oldPath, newPath) {
    const low = oldPath.toLowerCase();
    const nq = newPath ? Tags.ankiSearch("tag", newPath).slice(1, -1) : null;
    for (const u of doc.units) {
      if ((u.tags || []).some((t) => t.toLowerCase() === low)) {
        u.tags = newPath ? u.tags.map((t) => (t.toLowerCase() === low ? newPath : t)) : u.tags.filter((t) => t.toLowerCase() !== low);
      }
      for (const q of [...(u.search || [])]) {
        if (!tagRe(oldPath).test(q)) continue;
        if (!nq) { takeSearch(u, q); continue; }
        const q2 = q.replace(tagRe(oldPath, "gi"), () => nq);
        u.search = u.search.map((x) => (x === q ? q2 : x));
        if (u.sn?.[q] != null) { u.sn[q2] = u.sn[q]; delete u.sn[q]; }
      }
    }
    // 3.8.1: a note on the tag follows it, or goes with it
    if (remarks().some((r) => r.tag && r.tag.toLowerCase() === low)) {
      putRemarks(newPath ? remarks().map((r) => (r.tag && r.tag.toLowerCase() === low ? { ...r, tag: newPath } : r))
        : remarks().filter((r) => !(r.tag && r.tag.toLowerCase() === low)));
    }
    syncCuts();
    cleanup();
    renameAll();  // a date named for the tag (Cardio · SLG 12) follows it
  }
  let tagEdit = null;  // the tag being renamed
  let tagDrop = null;  // the tag whose × asked first
  /** a date using one of the plan's tags: as a tag, a cut kept to it, or in a search */
  const usesPtag = (u, t) => (u.tags || []).some((x) => x.toLowerCase() === ptagPath(t).toLowerCase())
    || (u.cut || []).some((c) => c.in === t.id) || (u.search || []).some((q) => tagRe(ptagPath(t)).test(q));
  /** with the tag gone, nothing would be left on the date (a cut is its whole tag again, so it stays) */
  const bareWithout = (u, t) => !(srcs(u).some((k) => k.toLowerCase() !== `tag:${ptagPath(t)}`.toLowerCase())
    || (u.cards || []).length || hasIds(u) || (u.cut || []).length
    || (u.search || []).some((q) => !tagRe(ptagPath(t)).test(q)));
  /** what deleting a tag does to the dates, said before it's done (as Edit the whole plan's preview does) */
  function dropSay(t) {
    const us = doc.units.filter((u) => usesPtag(u, t)).sort((a, b) => a.opens.localeCompare(b.opens));
    if (!us.length) return `${t.name} is on no dates.`;
    const list = (xs) => `${xs.slice(0, 4).map((u) => pretty(u.opens)).join(", ")}${xs.length > 4 ? ` and ${xs.length - 4} more` : ""}`;
    const gone = us.filter((u) => bareWithout(u, t));
    const cuts = us.some((u) => (u.cut || []).some((c) => c.in === t.id));
    return `${t.name} is on ${us.length} date${us.length === 1 ? "" : "s"}: ${list(us)}.`
      + (gone.length ? ` ${gone.length === us.length ? (us.length === 1 ? "It has" : "They have") : `${list(gone)} ha${gone.length === 1 ? "s" : "ve"}`} nothing else, so ${gone.length === 1 ? "it goes" : "they go"}, to-dos too.` : "")
      + (cuts ? " A tag kept to it there is all of that tag again." : "");
  }
  function ptagsPanel() {
    if (!author) return null;
    const list = ptags();
    const rows = list.map((t) => {
      const path = ptagPath(t);
      const from = ptagFrom(t);
      let nameEl = h("b", {}, t.name);
      if (tagEdit === t.id) {
        nameEl = h("input", { class: "ptname", value: t.name, maxlength: 40, "aria-label": "The tag's name" });
        let gone = false;
        const done = (ok) => {
          if (gone) return;
          gone = true; tagEdit = null;
          const v = nameEl.value.trim().slice(0, 40);
          if (ok && v && v !== t.name) {
            const clash = ptagByName(v);
            if (clash && clash !== t) note = `There's a tag called ${clash.name} already.`;
            else { t.name = v; retag(path, ptagPath(t)); mark(); }
          }
          draw();
        };
        nameEl.addEventListener("keydown", (e) => { if (e.key === "Enter") done(true); if (e.key === "Escape") done(false); });
        nameEl.addEventListener("blur", () => done(true));
        requestAnimationFrame(() => { nameEl.focus(); nameEl.select(); });
      }
      return h("div", { class: "ptag" },
        h("div", { class: "pt1" }, nameEl, h("small", { class: "muted" }, ptagSize(t)), h("span", { class: "sp" }),
          h("button", { class: "add", title: picked ? `Put it on ${pretty(picked)}` : "Put it on the next free day", "aria-label": `Put ${t.name} on ${picked ? pretty(picked) : "the next free day"}`,
            onclick: () => { const d = picked || firstStudy(lastDay() ? addDays(lastDay(), 1) : start); dropped(d, { key: `tag:${path}` }); } }, "+"),
          h("button", { class: "linkish", onclick: () => { tagEdit = t.id; tagDrop = null; draw(); } }, "Rename"),
          h("button", { class: "linkish", title: "Delete it (and from the dates that use it)", "aria-label": `Delete ${t.name}`, "aria-expanded": String(tagDrop === t.id),
            onclick: () => { tagDrop = tagDrop === t.id ? null : t.id; draw(); } }, "\u00d7")),
        from.length ? h("div", { class: "muted small pfrom" }, `From ${from.join(", ")}`) : null,
        // the dates it's on, before it goes: a date with nothing else goes with it
        tagDrop === t.id ? h("div", { class: "ptdrop small", role: "status" }, h("span", {}, dropSay(t)),
          h("span", { class: "row" },
            h("button", { class: "linkish danger", onclick: () => { tagDrop = null; putTags(list.filter((x) => x !== t)); retag(path, null); mark(); draw(); } }, "Delete it"),
            h("button", { class: "linkish", onclick: () => { tagDrop = null; draw(); } }, "Cancel"))) : null);
    });
    return h("div", { class: "ptags" },
      h("div", { class: "thead" }, h("b", {}, "This plan's tags")),
      list.length ? h("small", { class: "muted psub" }, `Everyone following gets them in Anki, under DueCrew › ${tagRootNow()}`) : null,
      // a long list scrolls in its own box, so the deck's tags below it stay in reach
      list.length ? h("div", { class: "ptlist" }, rows) : h("p", { class: "muted small" }, "Tag cards for your class (SLG 12, or Unit 3): in Anki's browser, right-click › Due Crew: tag for a plan…, or with your AI in Text › Tag by objective."));
  }
  // overlap: a plan tag and another tag, as an Anki search on the picked day
  let ovl = { a: "", op: "and", b: "" };
  function overlapBox(d) {
    if (!author || !ptags().length) return null;
    const listId = "ovl-tags";
    const others = [...ptags().map(ptagPath), ...[...count.keys()].filter((k) => kindOf(k) === "tag").slice(0, 3000).map(pathOf)];
    const dl = h("datalist", { id: listId }, others.map((p) => h("option", { value: p })));
    const a = h("select", { "aria-label": "The plan's tag", onchange: () => { ovl.a = a.value; } },
      ptags().map((t) => h("option", { value: t.id, selected: ovl.a === t.id }, t.name)));
    const b = h("input", { list: listId, value: ovl.b, placeholder: "another tag", "aria-label": "Another tag", oninput: () => { ovl.b = b.value; } });
    const ops = h("span", { class: "seg", role: "group", "aria-label": "How they meet" }, [["and", "and"], ["not", "but not"], ["or", "or"]].map(([k, t]) =>
      h("button", { class: ovl.op === k ? "on" : "", "aria-pressed": String(ovl.op === k), onclick: () => { ovl = { a: a.value, op: k, b: b.value }; draw(); } }, t)));
    const add = h("button", { onclick: () => {
      const t = ptags().find((x) => x.id === a.value) || ptags()[0];
      const other = b.value.trim();
      if (!t || !other) return;
      const pt = ptagByName(other);
      const otherPath = pt ? ptagPath(pt) : pathOf(findKey("tag", other.replace(/^tag:/i, "")));
      const A = Tags.ankiSearch("tag", ptagPath(t)), B = Tags.ankiSearch("tag", otherPath);
      const fresh = !doc.units.some((x) => x.opens === d && !x.even);
      const u = unitOn(d);
      if (!u) { draw(); return; }
      if (ovl.op === "and" && !pt) {
        // 3.8.1: the deck's tag kept to what this plan tag holds: a cut, in the tag's row in Anki
        const q = cutQ(otherPath, t);
        if (!addSearch(u, q)) { cleanup(); draw(); return; }
        u.cut = [...(u.cut || []).filter((c) => !(c.tag === otherPath && c.in === t.id)), { tag: otherPath, in: t.id, q }];
        if (fresh) { u.name = `${Tags.word(otherPath.split("::").pop())} · ${t.name}`.slice(0, 60); auto.delete(u.id); }
      } else {
        const q = ovl.op === "and" ? `${A} ${B}` : ovl.op === "not" ? `${A} -${B}` : `(${A} OR ${B})`;
        if (!addSearch(u, q)) { cleanup(); draw(); return; }
        if (fresh) { u.name = `${t.name} ${ovl.op === "not" ? "but not" : ovl.op} ${Tags.word(otherPath.split("::").pop())}`.slice(0, 60); auto.delete(u.id); }
      }
      ovl = { a: t.id, op: ovl.op, b: "" };
      renameAll(); mark(); draw();
    } }, "Add");
    return h("div", { class: "ovl" }, h("span", { class: "lbl" }, "Overlap"),
      h("div", { class: "row" }, a, ops, b, dl, add),
      h("small", { class: "muted" }, "and: in both. but not: the first without the second. or: either one. Counted in your Anki."));
  }
  // F1: events: named days (a lecture, a quiz, the exam) that dates prep for
  const events = () => doc.events || [];
  const evById = (id) => events().find((x) => x.id === id);
  const evOn = (d) => events().filter((x) => x.day === d);
  /** 3.8.1: a date after the event it names is reinforcement: "after Heme quiz",
   *  not "for" (the add-on's week view and Due say the same) */
  const afterEv = (u) => { const ev = u.for && evById(u.for); return !!ev && ev.day < u.opens; };
  const forWord = (u) => (afterEv(u) ? "after" : "for");
  const prepOf = (id) => doc.units.filter((u) => u.for === id && !afterEv(u));
  /** the days (not dates: a day can hold several) that prep for an event */
  const prepDays = (id) => [...new Set(prepOf(id).map((u) => u.opens))].sort();
  function addEvent(day, name) {
    if (events().length >= EVENTS_MAX) { note = `A plan holds up to ${EVENTS_MAX} events.`; return null; }
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
  /** a search's name from its tags; two of them, as Overlap writes them, read "SLG 12 but not Pharm" */
  const searchName = (q) => {
    const ws = [...q.matchAll(/(-?)"?tag:"?((?:\\.|[^\s"])+)/gi)].map((m) => [m[1],
      Tags.word(m[2].replace(/\\(.)/g, "$1").split("::").filter((x) => x.replace(/\*/g, "")).pop() || "").replace(/\*/g, "")]).filter(([, w]) => w);
    if (ws.length === 2 && !ws[0][0]) return `${ws[0][1]} ${ws[1][0] ? "but not" : /\sOR\s/.test(q) ? "or" : "and"} ${ws[1][1]}`;
    // 3.8.1: a tag without its extras (Extra and Bonus): "Cardio but not Extra, Bonus"
    if (ws.length > 2 && !ws[0][0] && ws.slice(1).every(([neg]) => neg)) return `${ws[0][1]} but not ${ws.slice(1).map(([, w]) => w).join(", ")}`;
    const w = ws.find(([neg]) => !neg);
    return w ? `Search: ${w[1]}` : "Search";
  };

  // the server's ceilings (worker/src/plans.ts), said where they're hit, not at Save
  const UNITS_MAX = 200, EVENTS_MAX = 200, REVIEWS_MAX = 60, SOURCES_MAX = 50, SEARCH_MAX = 10;
  const FULL = `A plan holds up to ${UNITS_MAX} dates.`;
  const srcFull = (f) => `A date holds up to ${SOURCES_MAX} ${f === "tags" ? "tags" : "subdecks"}.`;
  /** the day's date, made if it has none; null when the plan holds all it can (note says so) */
  function unitOn(d) {
    let u = doc.units.find((x) => x.opens === d && !x.even);
    if (!u) {
      if (doc.units.length >= UNITS_MAX) { note = FULL; return null; }
      u = { id: uid8(), name: "", opens: d, tags: [], decks: [], cards: [] }; doc.units.push(u); auto.add(u.id); byOpens();
    }
    return u;
  }
  /** a tag or subdeck onto a day; null when it can't take it (note says why) */
  function addTo(d, key) {
    const f = kindOf(key) === "tag" ? "tags" : "decks";
    const had = doc.units.find((x) => x.opens === d && !x.even);
    if (had && !(had[f] || []).includes(pathOf(key)) && (had[f] || []).length >= SOURCES_MAX) { note = srcFull(f); return null; }
    const u = unitOn(d);
    if (!u) return null;
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
    if (doc.units.length >= UNITS_MAX) { note = FULL; return null; }
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
  /** "Move this day…" onto a day with a date: all of `u` joins `into` (its
   *  tags, cards, IDs, searches and cuts, to-dos, what it's for, its review
   *  days), or, past what a date holds, nothing does and it says why. */
  function mergeInto(into, u) {
    const union = (k) => [...new Set([...(into[k] || []), ...(u[k] || [])])];
    const no = (why) => ({ ok: false, why: `${pretty(into.opens)} can't take it: ${why}` });
    if (union("search").length > SEARCH_MAX) return no(`a date holds up to ${SEARCH_MAX} searches and cuts.`);
    for (const f of ["tags", "decks"]) if (union(f).length > SOURCES_MAX) return no(srcFull(f).toLowerCase());
    for (const k of ["nids", "cids", "notes"]) if (union(k).length > 5000) return no("a date takes up to 5,000 IDs of each kind.");
    for (const f of ["tags", "decks"]) into[f] = union(f);
    const have = new Set((into.cards || []).map(([g, o]) => `${g}:${o}`));
    into.cards = [...(into.cards || []), ...(u.cards || []).filter(([g, o]) => !have.has(`${g}:${o}`))];
    for (const k of ["nids", "cids", "notes"]) if ((u[k] || []).length) { into[k] = union(k); delete into.idn; delete into.idr; }
    for (const q of u.search || []) { if (!(into.search || []).includes(q)) into.search = [...(into.search || []), q]; if (u.sn?.[q] != null) into.sn = { ...(into.sn || {}), [q]: u.sn[q] }; }
    for (const c of u.cut || []) if (!(into.cut || []).some((x) => x.tag === c.tag && x.in === c.in)) into.cut = [...(into.cut || []), c];
    let lost = 0;
    if ((u.todo || []).length) {
      const had = new Set((into.todo || []).map((x) => `${x.k}:${x.t.trim().toLowerCase()}`));
      const all = [...(into.todo || []), ...u.todo.filter((x) => !had.has(`${x.k}:${x.t.trim().toLowerCase()}`))];
      lost = Math.max(0, all.length - Todo.MAX);
      into.todo = all.slice(0, Todo.MAX);
    }
    if (u.for && !into.for) into.for = u.for;
    for (const r of doc.reviews || []) { if (r.from === u.id) r.from = into.id; if (r.to === u.id) r.to = into.id; }
    doc.units = doc.units.filter((x) => x !== u);
    return { ok: true, why: lost ? `A date keeps ${Todo.MAX} lines to tick: ${lost} didn't fit.` : "" };
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
  /** Puts `items` on study days from `from` (starting none after `until`), `cap`
   *  a day, chapters whole; nothing runs past `end` (an even piece there takes
   *  fewer days: `clipped`). `left`: what didn't go on, in order. */
  function fill(items, from, until, cap, end = null) {
    let d = firstStudy(from);
    let room = cap || Infinity;
    let used = 0;
    let placedN = 0;
    let lastD = null;
    let clipped = false;  // an even piece on fewer days than the pace asks: the end came first
    const next = () => { d = nextStudy(d); room = cap || Infinity; used = 0; };
    // a day holding all the tags (or subdecks) a date can: the next one
    const roomFor = (it) => {
      const f = kindOf(it.key) === "tag" ? "tags" : "decks", u = doc.units.find((x) => x.opens === d && !x.even);
      return !u || (u[f] || []).includes(pathOf(it.key)) || (u[f] || []).length < SOURCES_MAX;
    };
    let i = 0;
    for (; i < items.length; i++) {
      const it = items[i];
      if (until && d > until) break;
      if (it.even) {
        if (used) { next(); if (until && d > until) break; }
        let k = Math.max(2, Math.ceil(it.n / cap));
        if (end && studyDays(d, end) < k) { k = studyDays(d, end); clipped = true; }  // never past the end: more a day instead
        const u = evenUnit(d, it.key, k);
        if (!u) break;
        placedN += it.n; lastD = u.due || d;
        d = nextStudy(u.due || d); room = cap; used = 0;
        continue;
      }
      if (!cap) { if (used) next(); }
      else if (it.n > room && used) next();
      if (until && d > until) break;
      if (!roomFor(it)) { next(); if (until && d > until) break; }
      if (!addTo(d, it.key)) break;
      room -= it.n; used++; placedN += it.n; lastD = d;
    }
    return { placedN, lastD, left: items.slice(i), clipped };
  }
  /** what a fill left off, by name: "Renal, Pulm · the rest and 2 more" */
  /** 3.9.3: what a Fill put where, "Put 150 cards from Mon 9 Nov to Fri 13 Nov." (build.put_words) */
  const putWords = (n, a, b) => `Put ${n.toLocaleString()} card${n === 1 ? "" : "s"} ${a === b ? `on ${a}` : `from ${a} to ${b}`}.`;
  const leftNames = (xs) => `${xs.slice(0, 3).map((x) => `${Tags.word(pathOf(x.key).split("::").pop())}${x.rest ? " · the rest" : ""}`).join(", ")}${xs.length > 3 ? ` and ${xs.length - 3} more` : ""}`;
  function layOut(weekAhead) {
    // Fill to <date> stops there; just next week stops at its Sunday (or the end, if sooner)
    const end = pace.mode === "end" && doc.end ? doc.end : null;
    const after = lastDay() ? addDays(lastDay(), 1) : start;
    let from = after > start ? after : start;
    let until = end;
    if (weekAhead) {
      const nm = nextMonday();
      if (from < nm) from = nm;
      const mon = Sched.monday(from);
      from = from < mon ? mon : from;
      until = end && end < addDays(mon, 6) ? end : addDays(mon, 6);
      anchor = mon; view = "week";
    }
    if (until && firstStudy(from) > until) {
      note = end && until === end ? `Nothing fits by ${pretty(end)}: ${lastDay() ? `the dates already run to ${pretty(lastDay())}` : `the plan starts ${pretty(start)}`}. Move the finish date.`
        : "No study days left in that week.";
      return draw();
    }
    if (pace.mode === "end") { const d1 = endDaily(); if (d1) pace.daily = d1; }
    let cap = paceDaily();
    const placed = placedKeys();
    if (!coverItems().flatMap((k) => pieces(k, cap, placed)).length) return draw();
    const before = new Set(doc.units.map((u) => u.id));
    // to an end date, whole chapters leave room unused on a day: a little more a day (up to
    // about twice the pace) until it all fits by then; past that, it stops there and says what's left
    const was = JSON.stringify(doc.units), wasAuto = [...auto];
    let r;
    for (let tries = 0; ; tries++) {
      note = "";
      r = fill(coverItems().flatMap((k) => pieces(k, cap, placed)), from, until, cap, end);
      if (!end || weekAhead || !(r.left.length || r.clipped) || note || tries >= 7) break;  // note: a ceiling (200 dates) stopped it
      doc.units = JSON.parse(was); auto.clear(); for (const x of wasAuto) auto.add(x);
      cap = Math.min(5000, Math.ceil(cap * 1.1));
    }
    if (pace.mode === "end") pace.daily = cap;  // the pace it was filled at: a day over it says so
    const full = note;  // a plan's 200 dates, when that's what stopped it
    // F1: aimed at an event, the new dates before it prep for it
    const ev = pace.mode === "end" && aimFor && evById(aimFor);
    if (ev) for (const u of doc.units) if (!before.has(u.id) && u.opens < ev.day && !u.for) u.for = ev.id;
    renameAll(); byOpens(); mark();
    const leftN = r.left.reduce((a, x) => a + x.n, 0);
    // 3.9.3: what to do about what didn't fit, said (planner/build.py says the same)
    const tip = end && !full ? " Move the finish date." : full && pace.mode === "daily" ? " Raise the cards a day for fewer, bigger dates." : "";
    note = [r.placedN ? putWords(r.placedN, pretty(firstStudy(from)), pretty(r.lastD))
      : weekAhead ? "No study days left in that week." : "Nothing fit.",
    leftN && (full || !weekAhead) ? `${full ? `${full} ` : ""}${leftN.toLocaleString()} didn't fit${end && !full ? ` by ${pretty(end)}` : ""}: ${leftNames(r.left)}.${tip}` : ""]
      .filter(Boolean).join(" ");
    if (!weekAhead && r.lastD) anchor = firstStudy(from);
    if (r.lastD) requestAnimationFrame(() => document.querySelector(".cal2")?.scrollIntoView({ block: "nearest", behavior: "smooth" }));
    draw();
  }
  /** 3.4 review, H2: Fill with nothing to place says why, and the panel on the left flashes. */
  function fillOrSay(weekAhead) {
    if (coverLeft()) return layOut(weekAhead);
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
        const days = Work.spread(doc, u, total, pace.days);  // 3.8.1: as its bars spread it, the days as set now
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
        for (const k of srcs(u)) e.chips.push({ u, key: k, text: chipLabel(k, placed), short: label(k, placed), n: null, raw: pathOf(k) });
        e.load += u.n || 0;
      } else for (const k of srcs(u)) { const c = uncounted(k) ? null : eff(k, placed); e.chips.push({ u, key: k, text: chipLabel(k, placed), short: label(k, placed), n: c, raw: pathOf(k) }); e.load += c || 0; }
      for (const c of u.cut || []) {  // 3.8.1: counted by its search in an author's Anki, of its whole tag's
        const v = u.sn?.[c.q] ?? null, k = `tag:${c.tag}`;
        e.chips.push({ u, cut: c, key: k, text: cutName(c), raw: c.tag, n: v, of: count.size && count.has(k) ? n(k) : null });
        e.load += v || 0;
      }
      for (const q of u.search || []) { if (cutOf(u, q)) continue; const c = u.sn?.[q] ?? null; e.chips.push({ u, search: q, text: searchName(q), raw: q, n: c }); e.load += c || 0; }
      // 3.8.1: its picked cards, single cards and IDs, as one chip (picksText)
      if ((u.cards || []).length || hasIds(u)) {
        e.chips.push({ u, picks: true, text: picksText(u), raw: picksList(u), n: hasIds(u) && u.idn == null ? null : picksN(u) });
        e.load += picksN(u);
      }
    }
    const byId = new Map(doc.units.map((u) => [u.id, u]));
    for (const r of doc.reviews || []) {
      if (r.day < from || r.day > to) continue;
      const a = byId.get(r.from), b = byId.get(r.to);
      if (a && b) at(r.day).chips.push({ review: r, text: `Review · ${a.name}${a !== b ? ` – ${b.name}` : ""}`, n: null });
    }
    return out;
  }
  // 3.8.1 (plans, rethought): each day's work, every date spread over its window (Work)
  const workMap = (d0 = doc, placed = placedKeys()) => Work.map(d0, (u) => unitTotal(u, placed), pace.days);
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
    if (!c.even && c.u.opens === d) return;
    // onto a day with no date, when the plan holds all it can: nothing moves (the note says why)
    const t = c.even ? null : unitOn(d);
    if (!c.even && !t) { draw(); return; }
    if (c.even) { shiftUnit(c.u, Sched.diff(d, c.u.opens)); }
    else if (c.picks) {
      // 3.8.1: its picks move together, IDs and single cards
      const all = (k) => [...new Set([...(t[k] || []), ...(c.u[k] || [])])];
      if (["nids", "cids", "notes"].some((k) => all(k).length > 5000)) { note = "A date takes up to 5,000 IDs of each kind."; cleanup(); draw(); return; }
      if (hasIds(c.u)) { for (const k of ["nids", "cids", "notes"]) { t[k] = all(k); if (!t[k].length) delete t[k]; } delete t.idn; delete t.idr; takeIds(c.u); }
      const have = new Set((t.cards || []).map(([g, o]) => `${g}:${o}`));
      t.cards = [...(t.cards || []), ...(c.u.cards || []).filter(([g, o]) => !have.has(`${g}:${o}`))]; c.u.cards = [];
    }
    else if (c.search) { if (!addSearch(t, c.search)) { cleanup(); draw(); return; } if (c.u.sn?.[c.search] != null) t.sn = { ...(t.sn || {}), [c.search]: c.u.sn[c.search] }; takeSearch(c.u, c.search); }
    else if (c.cut) {
      // 3.8.1: the cut moves as it is; onto a day with all of that tag already, it just goes
      const n0 = c.u.sn?.[c.cut.q], x = c.cut;
      const has = (t.tags || []).includes(x.tag) || (t.cut || []).some((y) => y.tag === x.tag && y.in === x.in);
      if (!has && !addSearch(t, x.q)) { cleanup(); draw(); return; }
      takeCut(c.u, x);
      if (!has) { t.cut = [...(t.cut || []), x]; if (n0 != null) t.sn = { ...(t.sn || {}), [x.q]: n0 }; }
    }
    else { if (!addTo(d, c.key)) { cleanup(); draw(); return; } takeOut(c.u, c.key); }
    cleanup(); renameAll(); byOpens(); mark(); draw();
  }
  function dropped(d, what) {
    if (what.key) { if (addTo(d, what.key)) { renameAll(); mark(); picked = d; } draw(); }
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
      if (!out.length) out.push(h("p", { class: "muted small" }, count.size ? "Nothing matches."
        : `No tags yet. In Anki: Tools › Due Crew › Make a plan from a deck, and pick ${doc.deck}: the deck in Anki needs that name.`));
      list.replaceChildren(...out);
    }
    q.addEventListener("input", fillList);
    fillList();
    const seg = views.length > 1 ? h("div", { class: "seg", role: "tablist" }, views.map(([k, t]) =>
      h("button", { role: "tab", "aria-selected": String(treeView === k), class: treeView === k ? "on" : "", onclick: () => { treeView = k; draw(); } }, t))) : null;
    const tot = coverTotal();
    return h("div", { class: "tree2" },
      ptagsPanel(),
      h("div", { class: "thead" }, h("small", { class: "muted" }, tot ? `${tot.toLocaleString()} cards ticked` : "Tick what the plan covers.")),
      // the tree is the copy the author's Anki last sent (it sends it again when the deck's tags change)
      treeAt ? h("small", { class: "muted asof", title: "As your Anki last sent them" }, `Tags as of ${pretty(treeAt)}`) : null,
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
        // every date moves with the start, and the review days, the events and the end with them
        for (const u of doc.units) shiftUnit(u, delta);
        for (const r of doc.reviews || []) r.day = addDays(r.day, delta);
        for (const x of events()) x.day = addDays(x.day, delta);
        if (doc.end) doc.end = addDays(doc.end, delta);
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

  /** 3.8.0: lines that come every week ("every Fri: practice questions"),
   *  from the plan's first date to its last; each follower ticks each
   *  day's in Due. Authors edit them here; followers see them. */
  function everyBox() {
    const lines = doc.every || [];
    if (!author) {
      return lines.length ? h("div", { class: "every2" }, h("b", {}, "Every week"),
        lines.map((x) => h("span", { class: "small" }, h("b", {}, Todo.LABEL[x.k]), ` · ${x.t} · ${Every.label(x.r || "")}`,
          x.url && Todo.okUrl(x.url) ? [" ", h("a", { href: x.url, target: "_blank", rel: "noopener" }, "link")] : null))) : null;
    }
    const set = (key) => { if (lines.length) doc.every = lines; else delete doc.every; mark(key); };
    const rows = lines.map((x, i) => h("div", { class: "todo" },
      h("select", { "aria-label": "Kind", onchange: (e) => { x.k = e.target.value; set(); } },
        Object.entries(Todo.LABEL).map(([k, lb]) => h("option", { value: k, selected: x.k === k }, lb))),
      h("input", { value: x.t, maxlength: 140, placeholder: "Practice questions", "aria-label": "What to do",
        oninput: (e) => { x.t = e.target.value; set(`every:${i}`); } }),
      h("span", { class: "wdays", role: "group", "aria-label": "Days" }, ["M", "T", "W", "T", "F", "S", "S"].map((l, k) =>
        h("button", { class: (x.r || "").includes(String(k)) ? "on" : "", "aria-pressed": String((x.r || "").includes(String(k))), title: Every.DAYS[k],
          onclick: () => { const r = new Set((x.r || "").split("")); if (r.has(String(k))) r.delete(String(k)); else r.add(String(k));
            if (r.size) { x.r = [...r].sort().join(""); set(); draw(); } } }, l))),
      h("input", { value: x.url || "", maxlength: 500, placeholder: "https:// (optional)", "aria-label": "A link",
        onchange: (e) => { const v = e.target.value.trim(); if (!v) delete x.url; else if (Todo.okUrl(v)) x.url = v; else { e.target.value = x.url || ""; e.target.placeholder = "A link starts with https://"; } set(); } }),
      h("button", { class: "x", "aria-label": "Take this line off", onclick: () => { lines.splice(i, 1); set(); draw(); } }, "×")));
    return h("div", { class: "every2" },
      h("span", { class: "pi" }, h("b", {}, "Every week"), h("small", { class: "muted" }, " lines followers tick in Due on those days, from the first date to the last")),
      rows,
      lines.length < Every.MAX ? h("button", { class: "linkish", onclick: () => {
        doc.every = [...lines, { k: "do", t: "", r: "4" }]; mark(); draw(); } }, "+ Add a line") : null);
  }

  /** 3.8.1: the plan's notes on single cards (written in Anki's Browse): which card, by its
   *  note's ID and number, and the note; never the card's text. The authors take one off here. */
  let cnOpen = false;  // the list open, across redraws
  function cardNotes() {
    const list = remarks().filter((r) => r.card);
    if (!author || !list.length) return null;
    return h("details", { class: "every2 cnotes", open: cnOpen, ontoggle: (e) => { cnOpen = e.target.open; } },
      h("summary", {}, h("b", {}, "Notes on cards"), h("span", { class: "muted small" }, ` ${list.length} · followers see each on its card in Anki; write them in Anki's Browse`)),
      list.map((r) => h("div", { class: "cnote" }, h("span", { class: "mono small" }, `${r.card[0]} · card ${r.card[1] + 1}`), h("span", { class: "small" }, r.text),
        h("button", { class: "x", "aria-label": `Take off the note on ${r.card[0]}, card ${r.card[1] + 1}`, onclick: () => { putRemarks(remarks().filter((x) => x !== r)); mark(); draw(); } }, "×"))));
  }

  /** 3.8.0: a follower sees the plan's own tags: their names, where they sit in
   *  Anki (each follower's Anki adds them with the plan's updates), and a search
   *  to paste into Browse. */
  function followTags() {
    const list = ptags();
    if (author || !list.length) return null;
    return h("div", { class: "every2 ptagsf" },
      h("span", { class: "pi" }, h("b", {}, "This plan's tags"),
        h("small", { class: "muted" }, ` in your Anki under DueCrew › ${tagRootNow()}, with the plan's updates`)),
      h("div", { class: "ptf" }, list.map((t) => h("span", { class: "ptf1" }, h("b", {}, t.name),
        h("button", { class: "linkish cps", title: "Copy a search to paste into Anki's Browse", "aria-label": `Copy a search for ${t.name}`,
          onclick: (e) => copy(Tags.ankiSearch("tag", ptagPath(t)), e.currentTarget) }, "Copy search")))));
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
    slid = k;
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
    // 3.8.1: a day is heavy for the work it asks (its share of each date), not for what opens on it
    const work = workMap();
    const wOn = (d) => work.get(d)?.n || 0;
    const maxWork = Math.max(1, ...[...work.entries()].filter(([d]) => d >= a && d <= b).map(([, x]) => x.n));
    const cells = [];
    for (let d = a; d <= b; d = addDays(d, 1)) {
      const e = days.get(d) || { chips: [], load: 0 };
      const ph = Sched.phase(doc, d, 0);
      const off = !pace.days[(parseIso(d).getUTCDay() + 6) % 7];
      const w = wOn(d);
      const heavy = cap && w > cap * 1.25;
      const cls = ["d", off ? "off" : "", ph !== "build" ? ph : "", d === t ? "today" : "", d === picked ? "picked" : "", heavy ? "heavy" : "",
        doc.units.some((u) => u.opens === d && u.for && evById(u.for) && !afterEv(u)) ? "lead" : ""].filter(Boolean).join(" ");
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
      // 3.8.1 (plans, rethought): a date the author named shows its name above its chips,
      // unless its one chip already says it
      const said = new Set(), headed = new Set();
      const dname = (c) => {
        const u = c.u;
        if (!u || c.even || c.review || said.has(u) || auto.has(u.id) || !String(u.name || "").trim()) return null;
        said.add(u);
        const nm = u.name.trim().toLowerCase();
        if (e.chips.some((x) => x.u === u && [x.text, x.short].some((t) => String(t || "").toLowerCase() === nm))) return null;
        headed.add(u);
        return h("span", { class: "dname", title: u.name }, u.name);
      };
      const chip = (c) => {
        // 3.8.1: a note for followers on its tag (or a tag above it): a small ⓘ, the note in its title
        const rmk = c.cut ? remarkOn(c.cut.tag) : c.key && kindOf(c.key) === "tag" ? remarkOn(pathOf(c.key)) : null;
        const el = h("button", { class: `ch ${c.review ? "rv" : c.picks ? "single" : c.search && c.n === 0 ? "warn" : c.search ? "c2" : hue(c.key)}${c.even ? " ev" : ""}`, draggable: author && !c.review ? "true" : null,
          "data-k": c.u ? `${c.u.id}:${c.key || c.search || (c.picks ? "picks" : "")}` : null,
          title: `${c.raw || c.text}${c.n != null && !c.picks ? ` · ${c.n.toLocaleString()} cards` : ""}${rmk ? `\nⓘ ${rmk.text}` : ""}`,
          onclick: (ev) => { ev.stopPropagation(); picked = d; splitting = null; moving = null; sideTab = "day"; draw(); } },
          h("span", {}, rmk ? h("i", { class: "ri", "aria-label": `Note: ${rmk.text}` }, "ⓘ ") : null, headed.has(c.u) && c.short ? c.short : c.text), c.n != null && !c.picks ? h("small", {}, c.n.toLocaleString()) : null);
        if (author) el.addEventListener("dragstart", (ev) => { dragging = { chip: c }; ev.dataTransfer.setData("text/plain", c.text); ev.stopPropagation(); });
        return el;
      };
      const chips = e.chips.flatMap((c) => [dname(c), chip(c)]).filter(Boolean);
      const bar = w ? h("div", { class: `load${heavy ? " hi" : ""}`, title: `About ${w.toLocaleString()} new to learn this day` },
        h("i", { style: `width:${Math.min(100, Math.round((100 * w) / (cap || maxWork)))}%` })) : null;
      const cell = h("div", { class: cls, role: "gridcell", tabindex: "0", "aria-label": `${pretty(d)}${off ? ", a day off" : ""}${ph !== "build" ? `, ${ph === "catchup" ? "catch-up week" : "review-only days"}` : ""}: ${e.load ? `${e.load.toLocaleString()} cards` : "nothing new"}${w ? `, about ${w.toLocaleString()} to learn` : ""}`,
        onclick: () => { picked = picked === d ? null : d; splitting = null; moving = null; sideTab = picked ? "day" : "cover"; draw(); },
        onkeydown: (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); picked = picked === d ? null : d; moving = null; sideTab = picked ? "day" : "cover"; draw(); } } },
        h("div", { class: "dn2" }, h("span", {}, num), nNotes(d) ? h("span", { class: "nb", title: "Notes" }, `💬 ${nNotes(d)}`) : null, e.load ? h("b", {}, e.load.toLocaleString()) : null), ...evs, ...chips,
        fors.map((id) => h("span", { class: "for" }, evById(id).day < d ? "after " : "for ", h("b", {}, evById(id).name))), bar,
        you ? h("span", { class: "you" }, you) : null);
      const preps = [...new Set(doc.units.filter((u) => u.opens === d && u.for && evById(u.for) && !afterEv(u)).map((u) => u.for))];
      if (preps.length) cell.dataset.for = preps.join(" ");  // 3.8.1: a date after its event isn't its prep
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
    // 3.8.1 (plans, rethought): the work a day asks, each date spread to its due date;
    // a week's date due a week later is its daily share, never "212 new on Monday"
    const work = workMap();
    const run = Work.over(work, cap).find((r) => r.b >= a && r.a <= b);
    if (!run) return null;
    const [u] = work.get(run.a).by.slice().sort((x, y) => y[1] - x[1])[0];
    const total = unitTotal(u), last = Sched.win(doc, u, 0)[1];
    // what fixes it: split its biggest tag, or give it the study days the pace needs
    const big = u.even ? null : srcs(u).filter((k) => !uncounted(k) && eff(k) > 0).sort((x, y) => eff(y) - eff(x))[0];
    const need = Math.ceil(total / cap);
    let till = u.opens, k = isStudy(u.opens) ? 1 : 0;
    while (k < need && till < addDays(u.opens, 366)) { till = addDays(till, 1); if (isStudy(till)) k++; }
    const when = run.a === run.b ? pretty(run.a) : `${pretty(run.a)} – ${pretty(run.b)}`;
    return h("div", { class: "hnote" },
      h("span", {}, h("b", {}, when), ` ${run.a === run.b ? "asks" : "ask"} ${run.top.toLocaleString()} new a day (pace ${cap.toLocaleString()}): `,
        h("b", {}, u.name || autoName(u)), `, ${total.toLocaleString()} by ${pretty(last)}.`),
      h("span", { class: "row" },
        big ? h("button", { class: "ghost", onclick: () => { picked = u.opens; splitting = { u, key: big }; sideTab = "day"; draw(); } }, `Split ${chipLabel(big)}`) : null,
        till > last ? h("button", { class: "ghost", onclick: () => { u.due = till; mark(); draw(); } }, `Give it till ${pretty(till)}`) : null));
  }

  /** 3.9.2 (Sam's pick R3-A): what following the plan asks later, in reviews:
   *  its busiest week, then each week's, a typical card's (Reviews). */
  function reviewsNote() {
    const all = Reviews.weeks(workMap());
    const ws = all.slice(0, 16);  // 3.9.2's audit: the headline's week is one the list shows
    const p = Reviews.peak(ws);
    if (!p || p.n < 5) return null;
    return h("div", { class: "rnote", title: "A typical card's reviews over its first six weeks, new cards aside. A follower's own will differ." },
      h("span", {}, "About ", h("b", {}, Reviews.about(p.n)), ` reviews a day by week ${p.wk}`),
      h("span", { class: "muted" }, "Week by week: " + weekly(ws).join(" · ") + (all.length > ws.length ? " · …" : "")));
  }

  /** 3.9.2's QoL pass: a break between a plan's parts says so ("0 for 24 weeks"), not a row of zeros; its tail's zeros go */
  function weekly(ws) {
    const parts = [];
    let z = 0;
    for (const w of ws) {
      const s = Reviews.about(w.n);
      if (s === "0") { z++; continue; }
      if (z) parts.push(z > 1 ? `0 for ${z} weeks` : "0");
      z = 0;
      parts.push(s);
    }
    return parts;
  }

  /** 3.8.1 (plans, rethought): a named date's suggestions: the deck's tags its
   *  name points at that no date has yet, each added in one click. */
  function sugRows(u) {
    if (!author || !count.size || auto.has(u.id) || !String(u.name || "").trim()) return [];
    // what any date has (a tag, a subdeck, a cut, a tag without its extras): the tag itself, a tag under it, a tag above it
    const on = new Set(), above = new Set();
    const put = (k) => { const p = pathOf(k).toLowerCase(); on.add(p); const segs = p.split("::"); for (let i = 1; i < segs.length; i++) above.add(segs.slice(0, i).join("::")); };
    for (const k of placedKeys()) if (kindOf(k) === "tag") put(k);
    for (const x of doc.units) for (const c of x.cut || []) put(`tag:${c.tag}`);
    const skip = (p) => {
      const l = p.toLowerCase(), segs = l.split("::");
      if (on.has(l) || above.has(l)) return true;
      for (let i = 1; i < segs.length; i++) if (on.has(segs.slice(0, i).join("::"))) return true;
      return false;
    };
    const found = Suggest.tags(u.name, tree.tags, skip);
    if (!found.length) return [];
    return [h("span", { class: "muted small" }, "In your deck:"), ...found.map(([p, k]) => h("button", { class: `ch2 sug1 ${hue(`tag:${p}`)}`, title: `Add ${Tags.name(p)}`,
      onclick: () => {
        if ((u.tags || []).length >= SOURCES_MAX) { note = srcFull("tags"); draw(); return; }
        u.tags = [...(u.tags || []), p]; mark(); draw();
      } }, h("span", {}, `+ ${chipLabel(`tag:${p}`)}`), h("small", {}, k.toLocaleString())))];
  }

  // ---- 3.8.1: a deck tag's extras: extraKids, withoutQ, extrasOf (up with the tree: placedKeys and autoName read them) ----
  /** "64 + 22 extra", and With extras / Without: a tag's chip, or the search that is it without */
  function extrasPick(u, c) {
    const path = c.search ? extrasOf(c.search) : c.key && !c.cut && !c.picks && extraKids(c.key).length ? pathOf(c.key) : null;
    if (!path) return null;
    const ex = extraKids(`tag:${path}`).reduce((a, k) => a + n(k), 0), main = Math.max(0, n(`tag:${path}`) - ex);
    const without = !!c.search;
    const set = (want) => {
      if (want === without) return;
      // without: counted from the deck's tags until the author's Anki counts the search itself
      if (want) { const q = withoutQ(path); if (!addSearch(u, q)) { draw(); return; } takeOut(u, `tag:${path}`); u.sn = { ...(u.sn || {}), [q]: main }; }
      else { takeSearch(u, c.search); u.tags = [...new Set([...(u.tags || []), path])]; }
      cleanup(); renameAll(); mark(); draw();
    };
    return h("span", { class: "xtra" }, h("small", {}, `${main.toLocaleString()} + ${ex.toLocaleString()} extra`),
      author ? h("span", { class: "seg", role: "group", "aria-label": "Its extras" }, [[false, "With extras"], [true, "Without"]].map(([v, t]) =>
        h("button", { class: without === v ? "on" : "", "aria-pressed": String(without === v), onclick: () => set(v) }, t))) : null);
  }

  /** 3.8.1: under a tag's chip, its note for followers (ⓘ), or the box to write one */
  let rmkEdit = null;  // the tag whose note is being written
  function remarkBox(path) {
    const own = tagRemark(path);
    if (!author || rmkEdit !== path) {
      const r = own || remarkOn(path);
      return r ? h("div", { class: "rmk small" }, h("span", { class: "ri", "aria-hidden": "true" }, "ⓘ"), h("span", {}, r.text)) : null;
    }
    const box = h("input", { value: own?.text || "", maxlength: Remarks.TEXT, placeholder: "A note for followers, shown in their Anki",
      "aria-label": `A note for followers on ${Tags.word(path.split("::").pop())}` });
    let gone = false;
    const done = (keep) => { if (gone) return; gone = true; rmkEdit = null; if (keep) setTagRemark(path, box.value); draw(); };
    box.addEventListener("keydown", (e) => { if (e.key === "Enter") done(true); if (e.key === "Escape") done(false); });
    box.addEventListener("blur", () => done(true));
    requestAnimationFrame(() => box.focus());
    return h("div", { class: "rmk edit" }, box,
      own ? h("button", { class: "linkish", onmousedown: (e) => e.preventDefault(), onclick: () => { box.value = ""; done(true); } }, "Remove") : null);
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
    // 3.8.1: a picked chip says its number in its name ("88 picked")
    const count = (c) => (c.picks ? (c.n === 0 ? h("small", { class: "w" }, "finds nothing") : null)
      : c.search && c.n == null ? null  // the line under the date says when it's counted
      : c.search && c.n === 0 ? h("small", { class: "w" }, "finds nothing") : c.n != null ? h("small", {}, c.n.toLocaleString()) : null);
    // 3.8.0: a tag, subdeck or search, copied as a search for Anki's Browse
    const copySearch = (q) => h("button", { class: "linkish cps", title: `Copy ${q} to paste into Anki's Browse`, onclick: async (ev) => {
      const b = ev.currentTarget;
      try {
        await navigator.clipboard.writeText(q);
        if (window.dcMotion) return dcMotion.copied(b);  // 3.8.0: Copied ✓ in place, then back
        b.textContent = "Copied";
      } catch { b.textContent = q; }
      setTimeout(() => { b.textContent = "Copy search"; }, 2000);
    } }, "Copy search");
    // 3.8.1: a tag kept to what one of the plan's own tags holds, or all of it
    const onlyPick = (u, c) => {
      const tagPath = c.cut ? c.cut.tag : pathOf(c.key);
      const sel = h("select", { class: "inpick", title: "Only the cards one of this plan's tags holds", "aria-label": `Only what one of the plan's tags holds, of ${Tags.word(tagPath.split("::").pop())}`,
        onchange: () => { setCut(u, tagPath, sel.value || null); cleanup(); renameAll(); mark(); draw(); } },
        h("option", { value: "" }, "All of it"), ptags().map((t) => h("option", { value: t.id, selected: c.cut?.in === t.id }, `Only ${t.name}`)));
      return sel;
    };
    const canCut = (c) => author && ptags().length && (c.cut || (c.key && !c.picks && !c.search && kindOf(c.key) === "tag" && !isOwnTag(pathOf(c.key))));
    const cutCount = (c) => (c.n == null ? null : c.n === 0 ? h("small", { class: "w" }, "finds nothing")
      : h("small", {}, c.of ? `${c.n.toLocaleString()} of ${c.of.toLocaleString()}` : c.n.toLocaleString()));
    // 3.8.1: the tag a note for followers goes on: a deck tag's (or a plan tag's), a cut's own tag
    const noteTag = (c) => (c.cut ? c.cut.tag : c.key && !c.picks && kindOf(c.key) === "tag" ? pathOf(c.key) : null);
    /** a chip, and under it its tag's note (or the box to write one) */
    const chipEl = (u, c) => {
      const nt = noteTag(c);
      const chip = h("span", { class: `ch2 ${c.picks ? "single" : c.search && c.n === 0 ? "warn" : c.search ? "c2" : hue(c.key)}`, title: c.raw || "" },
        h("span", {}, c.short || c.text, c.raw && (c.search || c.cut || c.picks || Tags.name(c.raw) !== c.raw) ? h("span", { class: "raw" }, c.raw) : null), c.cut ? cutCount(c) : count(c),
        extrasPick(u, c),
        c.cut ? copySearch(c.cut.q) : c.search ? copySearch(c.search) : c.key && !c.picks ? copySearch(Tags.ankiSearch(kindOf(c.key), pathOf(c.key))) : null,
        canCut(c) ? onlyPick(u, c) : null,
        author && !c.picks && !c.search && !c.cut ? h("button", { class: "linkish", onclick: () => { splitting = { u, key: c.key }; draw(); } }, "Split") : null,
        author && nt ? h("button", { class: "linkish", title: "A note for followers on this, in their Anki", "aria-expanded": String(rmkEdit === nt),
          onclick: () => { rmkEdit = rmkEdit === nt ? null : nt; draw(); } }, "Note") : null,
        author ? h("button", { class: "x", "aria-label": `Take ${c.text} off`, onclick: () => {
          if (c.picks) { u.cards = []; takeIds(u); } else if (c.cut) takeCut(u, c.cut); else if (c.search) takeSearch(u, c.search); else takeOut(u, c.key);
          cleanup(); renameAll(); mark(); draw(); } }, "×") : null);
      return [chip, nt ? remarkBox(nt) : null];
    };
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
      const chips = e.chips.filter((c) => c.u === u).flatMap((c) => chipEl(u, c));
      if (!author) { rows.push(h("div", { class: "du" }, h("b", {}, u.name), h("div", { class: "chips2" }, chips), opensLine(u))); continue; }
      // 3.8.1 (plans, rethought): the deck's tags its name points at, as it's typed
      const sugBox = h("div", { class: "sug" });
      const fillSug = () => sugBox.replaceChildren(...sugRows(u));
      const name = h("input", { class: "uname", value: u.name, maxlength: 60, placeholder: autoName(u), "aria-label": "Name this day",
        oninput: (ev) => { nameIt(u, ev.target.value); fillSug(); }, onchange: (ev) => { if (!ev.target.value.trim()) { nameIt(u, ""); draw(); } } });
      fillSug();
      rows.push(h("div", { class: "du" }, h("label", { class: "dl" }, h("span", { class: "lbl" }, "Name"), name), sugBox, h("div", { class: "chips2" }, chips), opensLine(u)));
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
      // onto a day with a date, all of this one joins it (its to-dos, what it's for and its cuts too)
      const why = [];
      for (const u of own) {
        const other = doc.units.find((x) => x.opens === to && !x.even && x !== u);
        if (!other) { shiftUnit(u, Sched.diff(to, u.opens)); continue; }
        const r = mergeInto(other, u);
        if (r.why) why.push(r.why);
      }
      note = why.join(" ");
      picked = doc.units.some((u) => u.opens === d && !u.even) ? d : to;
      moving = null; renameAll(); byOpens(); mark(); draw(); } }) : null;
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
        d <= today() && rows.length ? h("small", { class: "muted" }, "This date has opened. Followers who opened it are asked at their next refresh to open what you add.") : null) : null,
      overlapBox(d),
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
    const set = (key) => { if (lines.length) u.todo = lines; else delete u.todo; mark(key); };
    const rows = lines.map((x, i) => h("div", { class: "todo" },
      h("select", { "aria-label": "Kind", onchange: (e) => { x.k = e.target.value; set(); } },
        Object.entries(Todo.LABEL).map(([k, lb]) => h("option", { value: k, selected: x.k === k }, lb))),
      h("input", { value: x.t, maxlength: 140, placeholder: "Lecture 14, renal clearance", "aria-label": "What to do",
        oninput: (e) => { x.t = e.target.value; set(`todo:${u.id}:${i}`); } }),
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
    // 3.8.1: an event before this day makes it reinforcement: "after Heme quiz"
    const after = !!cur && cur.day < d;
    if (!author) return cur ? h("p", { class: "muted small" }, after ? "After " : "For ", h("b", {}, cur.name), ` on ${pretty(cur.day)}`) : null;
    const later = events().filter((x) => x.day >= d), before = events().filter((x) => x.day < d);
    const opt = (x) => h("option", { value: x.id, selected: cur && cur.id === x.id }, `${x.name} · ${pretty(x.day)}`);
    const sel = h("select", { "aria-label": after ? "After" : "Prep for", onchange: (e) => {
      if (e.target.value === "+") { newEv = { day: addDays(d, 3), forDay: d }; draw(); return; }
      for (const u of own) { if (e.target.value) u.for = e.target.value; else delete u.for; }
      mark(); draw(); } },
      h("option", { value: "" }, "Nothing"),
      later.map(opt),
      before.length ? h("optgroup", { label: "After" }, before.map(opt)) : null,
      h("option", { value: "+" }, "+ New event…"));
    return h("div", { class: "addc" }, h("span", { class: "lbl" }, after ? "After" : "Prep for"), sel, newEv && newEv.forDay === d ? newEventForm(d, own) : null);
  }
  function newEventForm(d, own) {
    const name = h("input", { placeholder: "Lecture 12, Micro quiz, Block 2 exam", maxlength: 60, "aria-label": "The event's name" });
    const day = h("input", { type: "date", value: newEv.day, min: d, "aria-label": "Its day" });
    const make = () => {
      if (!name.value.trim() || !day.value) { name.focus(); return; }
      const ev = addEvent(day.value, name.value);
      if (!ev) { newEv = null; draw(); return; }  // a plan's 200 events: the note says so
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
    // an event needs a name (the server refuses none): cleared, it keeps the one it had
    const was = x.name;
    const name = h("input", { value: x.name, maxlength: 60, "aria-label": "The event's name", oninput: (e) => { x.name = e.target.value.slice(0, 60); mark(`ev:${x.id}`); },
      onchange: (e) => { if (!e.target.value.trim()) { x.name = was.trim() ? was : "Event"; mark(`ev:${x.id}`); draw(); } } });
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
      if (!u) { why.textContent = FULL; return; }
      const notes = [...new Set([...(u.notes || []), ...r.notes])];
      if (notes.length > 5000) { why.textContent = "A date takes up to 5,000 notes."; cleanup(); return; }
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
      if (!u) { why.textContent = FULL; return; }
      const all = [...new Set([...(u[kind] || []), ...ids])];
      if (all.length > 5000) { why.textContent = "A date takes up to 5,000 IDs of each kind."; cleanup(); return; }
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
      if (!u) { why.textContent = FULL; return; }
      // a date holds 10 searches and cuts (the server's SEARCH_MAX)
      if (!addSearch(u, q)) { why.textContent = note; note = ""; cleanup(); return; }
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
    if (!r && (doc.reviews || []).length >= REVIEWS_MAX) return h("small", { class: "muted" }, `A plan holds up to ${REVIEWS_MAX} review days.`);
    if (!r) return h("button", { class: "linkish", title: "That morning, followers get a Due Crew deck of what they've seen from these dates, most missed first.", onclick: () => {
      (doc.reviews ||= []).push({ day: d, from: before[Math.max(0, before.length - 5)].id, to: before[before.length - 1].id }); mark(); draw(); } }, "Make it a review day");
    const pick = (k) => h("select", { "aria-label": k === "from" ? "Review from" : "Review to", onchange: (e) => { r[k] = e.target.value; mark(); draw(); } },
      us.map((u) => h("option", { value: u.id, selected: r[k] === u.id }, `${u.name} · ${pretty(u.opens)}`)));
    return h("div", { class: "rvbox" }, h("b", { title: "That morning, followers get a Due Crew deck of what they've seen from these dates, most missed first." }, "Review day"),
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
    const st = h("small", { class: "status", role: "status" });
    const failed = (text) => { st.className = "status bad"; st.textContent = text; };
    const add = async () => {
      const text = input.value.trim(); if (!text) return;
      input.disabled = true; st.textContent = "";
      try {
        const r = await api("POST", `/plans/${id}/notes`, { day: d, text });
        notes.push({ id: r.id, uid: me.uid, name: me.name || "You", emoji: "", day: d, text: r.text, at: Date.now() / 1000, mine: true, remove: true });
        draw();
      } catch (err) {
        input.disabled = false; input.value = text;
        failed(err.body?.error === "too_many_notes" ? "That's as many notes as this plan holds from you. Remove one first."
          : err.body?.error === "authors_only" ? "On a plan in the library, only its authors write notes."
            : err.status === 429 ? "That's a lot of notes. Try again in an hour." : "That note didn't post. Try again.");
      }
    };
    input.addEventListener("keydown", (ev) => { if (ev.key === "Enter") add(); });
    return h("div", { class: "notes" },
      list.map((x) => h("div", { class: "note" }, h("b", {}, x.mine ? "You" : x.name), " ", h("span", {}, x.text),
        x.remove ? h("button", { class: "x", "aria-label": "Remove this note", onclick: async () => {
          try { await api("DELETE", `/plans/${id}/notes/${x.id}`); } catch { failed("That note didn't go. Try again."); return; }
          notes = notes.filter((y) => y !== x); draw(); } }, "×") : null)),
      input, st);
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
    const search = Tags.ankiSearch(kindOf(key), pathOf(key));
    const rest = only(key);
    const go2 = () => {
      if (doc.units.length >= UNITS_MAX) { note = FULL; draw(); return; }
      if (how === "tags") {
        takeOut(u, key);
        const items = ks.map((k) => ({ key: k, n: eff(k, placed) }));
        if (rest > 0) items.push({ key, n: rest, rest: true, even: !!cap && rest > cap });
        note = "";
        const r = fill(items, u.opens, null, cap);
        const leftN = r.left.reduce((a, x) => a + x.n, 0);
        note = `Split over ${pretty(firstStudy(u.opens))} to ${pretty(r.lastD || u.opens)}.${leftN ? ` ${note} ${leftN.toLocaleString()} didn't fit: ${leftNames(r.left)}.` : ""}`;
      } else {
        takeOut(u, key);
        const e = evenUnit(u.opens, key, Math.max(2, Math.min(60, Math.round(Number(days.value) || 2))));
        note = `Split evenly over ${pretty(e.opens)} to ${pretty(e.due || e.opens)}.`;
      }
      splitting = null; cleanup(); renameAll(); byOpens(); mark(); draw();
    };
    return h("div", { class: "splitp" },
      h("b", {}, `Split “${label(key, placed)}” · ${total.toLocaleString()} cards`),
      opt("tags", h("span", {}, h("b", {}, "By its tags"), " ", h("span", { class: "muted small" },
        ks.length ? `${ks.slice(0, 6).map((k) => `${Tags.word(pathOf(k).split("::").pop())} ${eff(k, placed)}`).join(" · ")}${ks.length > 6 ? ` · ${ks.length - 6} more` : ""}${rest > 0 ? ` · the rest ${rest}` : ""}, ${cap ? `at ${cap} a day` : "one a study day"}` : "nothing below this tag")), !ks.length),
      opt("even", h("span", {}, h("b", {}, "Evenly over "), days, " study days ", per)),
      // not a way Split works: picking is in Anki, so it's a line, not a choice
      h("p", { class: "muted small", style: "margin:0" }, "Or pick cards in Anki: ", h("code", {}, search), " ",
        h("button", { class: "quiet", onclick: (ev) => { ev.preventDefault(); copy(search, ev.target); } }, "Copy"),
        " · in Browse, select them, then Due Crew: add to a plan…"),
      h("div", { class: "row", style: "justify-content:flex-end" }, h("button", { class: "quiet", onclick: () => { splitting = null; draw(); } }, "Cancel"), h("button", { onclick: go2 }, "Split")));
  }

  // ---- the list: every date, with its dates to type ----
  function listView() {
    byOpens();
    if (!doc.units.length) return h("p", { class: "muted" }, "No dates yet. Tick what to cover and Fill, or drag a tag onto the calendar.");
    const placed = placedKeys();
    return h("div", { class: "units" }, doc.units.map((u) => {
      const name = h("input", { class: "uname", value: u.name, maxlength: 60, placeholder: autoName(u), "aria-label": "Date name",
        oninput: (e) => { nameIt(u, e.target.value); }, onchange: (e) => { if (!e.target.value.trim()) { nameIt(u, ""); draw(); } } });
      const opens = h("input", { type: "date", value: u.opens, "aria-label": "Opens", onchange: (e) => { if (e.target.value) { const k = Sched.diff(e.target.value, u.opens); shiftUnit(u, k); if (u.check && u.check < u.opens) delete u.check; byOpens(); mark(); draw(); } } });
      const due = h("input", { type: "date", value: u.due || "", min: u.opens, "aria-label": "Due", onchange: (e) => { u.due = e.target.value && e.target.value >= u.opens ? e.target.value : undefined; if (!u.due || u.due === u.opens) delete u.even; mark(); draw(); } });
      const even = h("input", { type: "checkbox", checked: !!u.even, disabled: !u.due || u.due === u.opens, onchange: (e) => { if (e.target.checked) u.even = true; else delete u.even; mark(); draw(); } });
      const chips = h("div", { class: "chips2" }, srcs(u).map((k) => h("span", { class: `ch2 ${hue(k)}`, title: pathOf(k) }, h("span", {}, label(k, placed), h("span", { class: "raw" }, pathOf(k))), h("small", {}, eff(k, placed).toLocaleString()),
        h("button", { class: "x", "aria-label": `Remove ${pathOf(k)}`, onclick: () => { takeOut(u, k); cleanup(); renameAll(); mark(); draw(); } }, "×"))),
        (u.cut || []).map((c) => h("span", { class: `ch2 ${hue(`tag:${c.tag}`)}`, title: c.tag }, h("span", {}, cutName(c), h("span", { class: "raw" }, c.tag)),
          u.sn?.[c.q] != null ? h("small", {}, u.sn[c.q].toLocaleString()) : null,
          h("button", { class: "x", "aria-label": `Remove ${cutName(c)}`, onclick: () => { takeCut(u, c); cleanup(); renameAll(); mark(); draw(); } }, "×"))),
        (u.search || []).filter((q) => !cutOf(u, q)).map((q) => h("span", { class: `ch2 ${u.sn?.[q] === 0 ? "warn" : "c2"}`, title: q }, h("span", {}, searchName(q), h("span", { class: "raw" }, q)),
          u.sn?.[q] != null ? h("small", {}, u.sn[q].toLocaleString()) : null,
          h("button", { class: "x", "aria-label": `Remove the search ${q}`, onclick: () => { takeSearch(u, q); cleanup(); renameAll(); mark(); draw(); } }, "×"))),
        // 3.8.1: its picked cards, single cards and IDs, as one chip read by its first label
        (u.cards || []).length || hasIds(u) ? h("span", { class: "ch2 single", title: picksList(u) || "" }, picksText(u),
          h("button", { class: "x", "aria-label": `Take ${picksText(u)} off`, onclick: () => { u.cards = []; takeIds(u); cleanup(); renameAll(); mark(); draw(); } }, "×")) : null);
      return h("div", { class: "unit" }, h("span"), h("div", {}, name, chips),
        h("div", { class: "dates" }, h("span", {}, "Opens ", opens), h("span", {}, "Due ", due), h("label", { class: "inline" }, even, " evenly over its days"),
          h("button", { class: "del", "aria-label": `Delete ${u.name}`, onclick: () => { doc.units = doc.units.filter((x) => x !== u); mark(); draw(); } }, "×")));
    }));
  }

  // ---- as text ----
  const CARDS_TEXT = 500;
  // 3.8.0: a plan tag as a line: tag | SLG 12 | tag:…, search:… | notes:…
  const tagSrcs = (t) => [[...(t.tags || []).map((x) => `tag:${x}`), ...(t.decks || []).map((x) => `deck:${x}`)].join(", "),
    ...(t.search || []).map((x) => `search:${x}`)].filter(Boolean);
  const tagLine = (t) => ["tag", t.name, ...tagSrcs(t), (t.notes || []).length ? Picks.notesText(t.notes) : "",
    (t.cards || []).length ? Picks.cardsText(t.cards) : ""].filter(Boolean).join(" | ");
  const toText = () => { byOpens(); return [...ptags().map(tagLine), ...[...events().map((x) => `${x.day} | event | ${x.name}`), ...doc.units.map((u) => [u.opens, u.name,
    [...(u.tags || []).map((t) => `tag:${t}`), ...(u.cut || []).map((c) => `tag:${c.tag} in ${(ptags().find((x) => x.id === c.in) || {}).name || "?"}`),
      ...(u.decks || []).map((d) => `deck:${d}`)].join(", "),
    ...(u.search || []).filter((q) => !cutOf(u, q)).map((q) => `search:${q}`),
    (u.nids || []).length ? `nids:${u.nids.join(",")}` : "", (u.cids || []).length ? `cids:${u.cids.join(",")}` : "",
    (u.notes || []).length ? Picks.notesText(u.notes) : "",
    u.due ? `due ${u.due}` : "", u.even ? "even" : "",
    // 3.6.5: single cards as cards: (a long list stays a count, kept as it is)
    (u.cards || []).length > CARDS_TEXT ? `${u.cards.length} single cards` : (u.cards || []).length ? Picks.cardsText(u.cards) : "",
    u.for && evById(u.for) ? `for ${evById(u.for).name}` : "",
    // Due: the author's lines, each one part ("watch: lecture 14 https://…")
    ...(u.todo || []).map((x) => `${x.k}: ${x.t}${x.url ? ` ${x.url}` : ""}`)].filter(Boolean).join(" | "))].sort(),
    // 3.8.1: notes for followers on a tag or a card, after the dates
    ...remarks().map(Remarks.line)].join("\n"); };

  // what an AI (or a person) might write for a tag: the exact path, any
  // case, or its readable name
  const byLower = new Map([...count.keys()].map((k) => [k.toLowerCase(), k]));
  const byName = new Map([...count.keys()].map((k) => [`${kindOf(k)}:${Tags.name(pathOf(k)).toLowerCase()}`, k]));
  const findKey = (kind, p) => byLower.get(`${kind}:${p.toLowerCase()}`) || byName.get(`${kind}:${p.toLowerCase()}`) || `${kind}:${p}`;
  // 3.9.3: a "# Pick in Anki for 2026-10-06: the iron cards" line after "To pick in Anki:", the words once (text.pick_note)
  const pickNote = (n) => n.replace(/^\s*pick in anki\b\s*(?:for\s+)?/i, "").replace(/^:\s*/, "") || n;

  function fromText(text, whole = false) {
    const errors = [];
    const units = [];
    const tagsIn = [];   // 3.8.0: "tag | SLG 12 | notes:… | tag:…"
    // the names of the tags this text makes, for a date's tag:SLG 12 before the line that makes it
    const named = new Set(text.split("\n").map((l) => /^\s*(?:[-*•]\s+)?`?tag\s*\|\s*([^|]+?)\s*(?:\||$)/i.exec(l)).filter(Boolean)
      .map((m) => Tags.part(m[1].slice(0, 40)).toLowerCase()));
    const planTagKey = (raw) => {
      if (raw.includes("::")) return null;
      const t = ptagByName(raw);
      if (t) return `tag:${ptagPath(t)}`;
      return named.has(Tags.part(raw).toLowerCase()) ? `tag:DueCrew::${tagRootNow()}::${Tags.part(raw)}` : null;
    };
    const notes = [];
    const evs = [];     // F1: "2026-10-15 | event | Micro quiz"
    const forName = new Map();  // unit id -> the event name it's for
    const warns = [];
    let localIds = 0;  // dates with pasted numbers not yet turned into note IDs by the author's Anki
    const why = [];  // 3.6.5: the AI's own notes (which video, and why), shown, never imported
    const pendingCuts = [];  // 3.8.1: tag:PATH in NAME, NAME a tag of this plan (here or already)
    const lines = [];  // the date lines, read; which date each one is comes after (all of them are needed)
    const remarksIn = [];  // 3.8.1: note | tag:PATH | … and note | card:GUID:N | …
    text.split("\n").forEach((raw, i) => {
      let line = raw.trim().replace(/^[-*•]\s+/, "").replace(/^`([^`].*)`$/, "$1");
      if (!line || /^```/.test(raw.trim())) return;
      // 3.8.1: a note for followers, read before notes: and cards: (a guid can hold | and :)
      const nl = /^note(?:\s*\|\s*|\s{2,})(.*)$/i.exec(line);
      if (nl) {
        const r = Remarks.take(nl[1]);
        if (!r || r.bad) { errors.push(`Line ${i + 1}: a note is note | tag:PATH | your words, or note | card:ID:N | your words (N the card's number from 1).`); return; }
        const words = Remarks.clean(r.text);
        if (!words) { errors.push(`Line ${i + 1}: the note has no words.`); return; }
        if (words.length > Remarks.TEXT) warns.push(`Line ${i + 1}: a note is cut to ${Remarks.TEXT} characters.`);
        const x = r.card ? { card: r.card } : { tag: pathOf(planTagKey(r.tag) || findKey("tag", r.tag)) };
        if (x.tag !== undefined && (!x.tag || x.tag.length > 200)) { errors.push(`Line ${i + 1}: a note's tag is up to 200 characters.`); return; }
        x.text = words.slice(0, Remarks.TEXT);
        const had = remarksIn.findIndex((y) => Remarks.same(x, y));  // one note a tag or a card: the last line's
        if (had >= 0) remarksIn[had] = x; else remarksIn.push(x);
        return;
      }
      // 3.6.5: notes: and cards: first; a guid can hold | and `
      const picks = line.startsWith("#") ? null : Picks.take(line);
      if (picks) line = picks.line;
      line = line.replace(/`/g, "");
      if (line.startsWith("#")) { (/\bpick\b|\bsingle\b/i.test(line) ? notes : why).push(line.replace(/^#+\s*/, "")); return; }
      const parts = line.split(/\s*\|\s*|\s{2,}/).filter(Boolean);
      if (parts.length >= 2 && /^tag$/i.test(parts[0])) {
        const full = parts[1].trim();
        const tname = full.slice(0, 40).trim();
        if (full.length > 40) warns.push(`Line ${i + 1}: a tag's name is cut to 40 characters.`);
        const tg = [], dk = [], sq = [];
        for (const part of parts.slice(2)) {
          if (/^search:/i.test(part)) sq.push(part.slice(7).trim());
          else if (/^(tag|deck):/i.test(part)) {
            for (const x of part.split(/\s*[,;]\s*(?=(?:tag|deck):)/i)) {
              const kind = x.slice(0, 4).toLowerCase() === "deck" ? "deck" : "tag";
              (kind === "tag" ? tg : dk).push(pathOf(findKey(kind, x.slice(x.indexOf(":") + 1).trim())));
            }
          } else { errors.push(`Line ${i + 1}: a tag line is tag | its name | notes:…, tag:…, deck:… or search:…`); return; }
        }
        if (picks && picks.bad.length) { errors.push(`Line ${i + 1}: "${picks.bad[0].slice(0, 30)}" isn't a note's ID from Anki (cards: takes ID:N, N the card's number from 1).`); return; }
        if (sq.some((q) => PERSONAL.test(q))) { errors.push(`Line ${i + 1}: that search finds different cards in each person's Anki; use tags.`); return; }
        const gs = picks ? picks.notes : [];
        const cs = picks ? picks.cards : [];  // 3.8.1: single cards (Anki's tag goes on their notes)
        if (!tname || (!gs.length && !cs.length && !tg.length && !dk.length && !sq.length)) { errors.push(`Line ${i + 1}: a tag needs a name, and notes:, cards:, a tag:, a deck: or a search:.`); return; }
        if (gs.length > 5000 || cs.length > 5000) { errors.push(`Line ${i + 1}: a tag holds up to 5,000 notes and 5,000 single cards.`); return; }
        const want = Tags.part(tname).toLowerCase();
        const t = tagsIn.find((x) => Tags.part(x.name).toLowerCase() === want)
          || (tagsIn[tagsIn.push({ id: ptagByName(tname)?.id || uid8(), name: tname }) - 1]);
        for (const [k, v] of [["notes", gs], ["tags", tg], ["decks", dk], ["search", sq]]) if (v.length) t[k] = [...new Set([...(t[k] || []), ...v])];
        if (cs.length) { const have = new Set((t.cards || []).map(([g, o]) => `${g}:${o}`)); t.cards = [...(t.cards || []), ...cs.filter(([g, o]) => !have.has(`${g}:${o}`))]; }
        return;
      }
      if (parts.length >= 3 && /^\d{4}-\d{2}-\d{2}$/.test(parts[0]) && /^event$/i.test(parts[1])) {
        const full = parts.slice(2).join(" ");
        const name = full.slice(0, 60);
        if (full.length > 60) warns.push(`Line ${i + 1}: the event's name is cut to 60 characters.`);
        const old = events().find((x) => x.name.toLowerCase() === name.toLowerCase());
        evs.push({ id: old?.id || uid8(), day: parts[0], name });
        return;
      }
      let forN = null; let keepCards = false; let keepN = 0;
      let opens = null; let at = -1; let due; let even = false; let name = ""; const tags = []; const decks = []; const searches = []; const ids = { nids: [], cids: [] };
      const cutsHere = [];  // 3.8.1: tag:PATH in SLG 12
      const todo = [];  // Due: "watch: lecture 14 https://…", "read: …", "do: …"
      parts.forEach((part, k) => {
        let m;
        // the part after the date is its name, whatever it says ("Read: Chapter 3", "For the
        // midterm", "Evenly"): there only tag:, deck:, search:, IDs and due DATE are read as such
        const namePart = !opens || k === at + 1;
        if (!opens && (m = /^(\d{4}-\d{2}-\d{2})$/.exec(part))) { opens = m[1]; at = k; }
        else if (!opens && (m = /^week\s+(\d+)$/i.exec(part))) { opens = addDays(start, (Number(m[1]) - 1) * 7); at = k; }
        else if ((m = /^due\s+(\d{4}-\d{2}-\d{2})$/i.exec(part))) due = m[1];
        else if (!namePart && /^even(ly)?$/i.test(part)) even = true;
        else if (!namePart && (m = /^for\s+(.+)$/i.exec(part))) forN = m[1].trim();
        else if (!namePart && (m = /^(\d+) single cards?$/.exec(part))) { keepCards = true; keepN = Number(m[1]); }
        else if (/^search:/i.test(part)) searches.push(part.slice(7).trim());
        else if (!namePart && (m = /^(watch|read|do):\s*(.+)$/i.exec(part))) todo.push(Todo.parse(m[1], m[2]));
        else if ((m = /^(nids|cids|ids):\s*([\d\s,;]+)$/i.exec(part))) ids[m[1].toLowerCase() === "cids" ? "cids" : "nids"].push(...m[2].split(/[\s,;]+/).filter(Boolean).map(Number).filter((x) => Number.isSafeInteger(x) && x > 0));
        else if (/^(tag|deck):/i.test(part)) {
          for (const x of part.split(/\s*[,;]\s*(?=(?:tag|deck):)/i)) {
            const kind = x.slice(0, 4).toLowerCase() === "deck" ? "deck" : "tag";
            const raw = x.slice(x.indexOf(":") + 1).trim();
            const cm = kind === "tag" && /^(\S+)\s+in\s+(\S.*)$/i.exec(raw);
            if (cm) { cutsHere.push({ tag: pathOf(findKey("tag", cm[1])), inName: cm[2].trim(), line: i + 1 }); continue; }
            const key = (kind === "tag" && planTagKey(raw)) || findKey(kind, raw);  // 3.8.0: tag:SLG 12, the plan's own
            (kind === "tag" ? tags : decks).push(pathOf(key));
          }
        } else name = name ? `${name} ${part}` : part;
      });
      if (!opens) { errors.push(`Line ${i + 1}: starts with a date (2026-10-05) or "week 3".`); return; }
      if (searches.some((q) => PERSONAL.test(q))) { errors.push(`Line ${i + 1}: that search finds different cards in each person's Anki; use tags.`); return; }
      if (picks.bad.length) { errors.push(`Line ${i + 1}: "${picks.bad[0].slice(0, 30)}" isn't a note's ID from Anki (cards: takes ID:N, N the card's number from 1).`); return; }
      if (!tags.length && !cutsHere.length && !decks.length && !searches.length && !ids.nids.length && !ids.cids.length && !picks.notes.length && !picks.cards.length && !keepCards) { errors.push(`Line ${i + 1}: needs a tag:, a deck:, a search: or notes:.`); return; }
      if (ids.nids.length > 5000 || ids.cids.length > 5000 || picks.notes.length > 5000) { errors.push(`Line ${i + 1}: a date takes up to 5,000 IDs.`); return; }
      if (due && due < opens) { errors.push(`Line ${i + 1}: due is before it opens.`); return; }
      if (even && !(due && due > opens)) { errors.push(`Line ${i + 1}: "even" needs a due date after it opens.`); return; }
      // the server's ceilings for one date (worker/src/plans.ts)
      if (new Set(searches).size + cutsHere.length > SEARCH_MAX) { errors.push(`Line ${i + 1}: a date holds up to ${SEARCH_MAX} searches and cuts.`); return; }
      if (new Set(tags).size > SOURCES_MAX || new Set(decks).size > SOURCES_MAX) { errors.push(`Line ${i + 1}: a date holds up to ${SOURCES_MAX} tags and ${SOURCES_MAX} subdecks.`); return; }
      if (name.length > 60) warns.push(`Line ${i + 1}: the name is cut to 60 characters.`);
      // 3.6.5: names compared as they're kept (60 at most, trimmed), so a long one still finds its date
      const key = (name || leaf(tags[0] || decks[0] || cutsHere[0]?.tag) || "").slice(0, 60).trim();
      lines.push({ i, opens, due, even, name, key, tags, decks, searches, ids, picks, keepCards, keepN, cutsHere, todo, forN });
    });
    // 3.8.1: the whole plan: a tag line with a new name that holds just what one of the plan's
    // tags holds is that tag renamed; it keeps its id, and the dates using it follow (retag)
    const renamed = [];
    if (whole) {
      const srt = (xs) => [...new Set(xs || [])].map(String).sort();
      const tsig = (t) => JSON.stringify([srt(t.notes), srt((t.cards || []).map(([g, o]) => `${g}:${o}`)), srt(t.tags), srt(t.decks), srt(t.search)]);
      const had = new Set(ptags().map((t) => t.id));
      const fresh = tagsIn.filter((t) => !had.has(t.id));
      const free = ptags().filter((t) => !tagsIn.some((x) => x.id === t.id));
      for (const t of fresh) {
        const was = free.filter((x) => tsig(x) === tsig(t));
        if (was.length !== 1 || fresh.filter((y) => tsig(y) === tsig(t)).length !== 1) continue;
        renamed.push({ id: was[0].id, from: ptagPath(was[0]), was: was[0].name });
        t.id = was[0].id;
        free.splice(free.indexOf(was[0]), 1);
      }
    }
    // Which date each line is (its id keeps followers' skips, moves and progress): the same day
    // and name. In the whole plan, a line with no such date is the one date with its name on
    // another day (moved), or the one on its day with the same cards under another name (renamed).
    const claimed = new Set();
    for (const e of lines) {
      e.old = doc.units.find((u) => u.opens === e.opens && String(u.name || "").trim() === e.key && !(whole && claimed.has(u.id)));
      if (e.old && whole) claimed.add(e.old.id);
    }
    if (whole) {
      const sorted = (xs) => [...new Set(xs || [])].map(String).sort();
      const cardsSig = (cs) => cs.map(([g, o]) => `${g}:${o}`).sort();
      const sigOf = (e) => JSON.stringify([sorted(e.tags), sorted(e.decks), sorted(e.searches), e.cutsHere.map((c) => `${c.tag} in ${Tags.part(c.inName).toLowerCase()}`).sort(),
        sorted(e.ids.nids), sorted(e.ids.cids), sorted(e.picks.notes), e.picks.cards.length ? cardsSig(e.picks.cards) : e.keepN ? `#${e.keepN}` : []]);
      const oldSig = (u) => JSON.stringify([sorted(u.tags), sorted(u.decks), sorted((u.search || []).filter((q) => !cutOf(u, q))),
        (u.cut || []).map((c) => `${c.tag} in ${Tags.part((ptags().find((t) => t.id === c.in) || {}).name || "?").toLowerCase()}`).sort(),
        sorted(u.nids), sorted(u.cids), sorted(u.notes), (u.cards || []).length > CARDS_TEXT ? `#${u.cards.length}` : cardsSig(u.cards || [])]);
      const loose = lines.filter((e) => !e.old);
      const one = (xs) => (xs.length === 1 ? xs[0] : null);
      for (const e of loose) {
        const free = doc.units.filter((u) => !claimed.has(u.id));
        const moved = one(free.filter((u) => String(u.name || "").trim() === e.key));
        const renamed = one(free.filter((u) => u.opens === e.opens && oldSig(u) === sigOf(e)));
        e.old = moved && loose.filter((x) => x.key === e.key).length === 1 ? moved
          : renamed && loose.filter((x) => x.opens === e.opens && sigOf(x) === sigOf(e)).length === 1 ? renamed : undefined;
        if (e.old) claimed.add(e.old.id);
      }
    }
    for (const { i, opens, due, even, name, tags, decks, searches, ids, picks, keepCards, cutsHere, todo, forN, old } of lines) {
      // single cards: as written (cards:), plus the ones a count stands for; neither keeps what it had
      const had = picks.cards.length && !keepCards ? [] : old?.cards || [];
      const seen = new Set(had.map(([g, o]) => `${g}:${o}`));
      const cards = [...had, ...picks.cards.filter(([g, o]) => !seen.has(`${g}:${o}`))];
      if (!tags.length && !cutsHere.length && !decks.length && !searches.length && !ids.nids.length && !ids.cids.length && !picks.notes.length && !cards.length) { errors.push(`Line ${i + 1}: needs a tag:, a deck:, a search: or notes:.`); continue; }
      const u = { id: old?.id || uid8(), name: (name || "").slice(0, 60), opens, due, tags: [...new Set(tags)], decks: [...new Set(decks)], cards };
      for (const c of cutsHere) pendingCuts.push({ u, ...c });
      if (even) u.even = true;
      if (searches.length) {
        u.search = [...new Set(searches)];
        const sn = Object.fromEntries(u.search.filter((q) => old?.sn?.[q] != null).map((q) => [q, old.sn[q]]));
        if (Object.keys(sn).length) u.sn = sn;  // a search kept as it was keeps its count
      }
      for (const k of ["nids", "cids"]) if (ids[k].length) u[k] = [...new Set(ids[k])];
      if (picks.notes.length) u.notes = picks.notes;
      if (hasIds(u) && old && JSON.stringify([old.nids, old.cids, old.notes]) === JSON.stringify([u.nids, u.cids, u.notes]) && old.idn != null) u.idn = old.idn;
      if (old?.pl && picksSig(old) === picksSig(u)) u.pl = old.pl;  // 3.8.1: what its picks are, while they're the same
      if ((u.nids || u.cids) && !(old?.idr && JSON.stringify([old.nids, old.cids]) === JSON.stringify([u.nids, u.cids]))) localIds++;
      if (todo.length > Todo.MAX) warns.push(`Line ${i + 1}: a date keeps ${Todo.MAX} lines to tick; the rest are left off.`);
      if (todo.length) u.todo = todo.slice(0, Todo.MAX);
      if (forN) forName.set(u.id, forN);
      if (!u.due) delete u.due;
      if (!u.name) { u.name = autoName(u); auto.add(u.id); }
      units.push(u);
    }
    // 3.8.1: a cut's tag is one of the plan's own, made on a tag line here or already the plan's
    for (const c of pendingCuts) {
      const want = Tags.part(c.inName).toLowerCase();
      const t = tagsIn.find((x) => Tags.part(x.name).toLowerCase() === want) || ptagByName(c.inName);
      if (!t) { errors.push(`Line ${c.line}: no tag of this plan is called ${c.inName}. Make it with a tag | ${c.inName} | … line.`); continue; }
      if (!(c.u.cut || []).some((x) => x.tag === c.tag && x.in === t.id)) c.u.cut = [...(c.u.cut || []), { tag: c.tag, in: t.id, q: "" }];
      // a date named by nothing but its cuts: by the first, the plan tag's name from here or the plan
      if (auto.has(c.u.id) && !srcs(c.u).length && c.u.cut[0].tag === c.tag) {
        c.u.name = `${Tags.word(c.tag.split("::").pop())} · ${t.name}${c.u.cut.length > 1 ? ` + ${c.u.cut.length - 1} more` : ""}`.slice(0, 60);
      } else if (auto.has(c.u.id) && !srcs(c.u).length) c.u.name = c.u.name.replace(/( \+ \d+ more)?$/, ` + ${c.u.cut.length - 1} more`).slice(0, 60);
    }
    const ours = `tag:DueCrew::${tagRootNow()}::`.toLowerCase();  // the plan's own tags aren't in the deck until they're made
    const missing = [...new Set([...units.flatMap((u) => [...u.tags.map((t) => `tag:${t}`), ...(u.cut || []).map((c) => `tag:${c.tag}`), ...u.decks.map((d) => `deck:${d}`)]),
      ...remarksIn.filter((x) => x.tag).map((x) => `tag:${x.tag}`)])]
      .filter((k) => count.size && !count.has(k) && !k.toLowerCase().startsWith(ours));
    for (const u of units) {
      const n = forName.get(u.id); if (!n) continue;
      const ev = [...evs, ...events()].find((x) => x.name.toLowerCase() === n.toLowerCase());
      if (ev) u.for = ev.id; else errors.push(`"for ${n}": no event by that name. Add a line like 2026-10-15 | event | ${n}`);
    }
    // 3.6.5: pasted ids are this Anki's own numbers until the author's Anki sends what they are
    if (localIds) warns.push(`${localIds} date${localIds === 1 ? " uses" : "s use"} nids: or cids:, your Anki's own numbers. Open Anki after you save, and they'll work in everyone's copy.`);
    if (tagsIn.length + ptags().filter((t) => !tagsIn.some((x) => x.id === t.id)).length > 100) errors.push("A plan holds up to 100 tags.");
    const rmN = whole ? remarksIn.length : remarks().filter((y) => !remarksIn.some((x) => Remarks.same(x, y))).length + remarksIn.length;
    if (rmN > Remarks.MAX) errors.push(`A plan holds up to ${Remarks.MAX} notes on tags and cards; this would make ${rmN}.`);
    // the plan's ceilings, as it would be after this text (the whole plan, or added to it)
    const joins = (u) => doc.units.find((x) => x.id === u.id);
    const dates = whole ? units.length : doc.units.length + units.filter((u) => !joins(u)).length;
    if (dates > UNITS_MAX) errors.push(`A plan holds up to ${UNITS_MAX} dates; this would make ${dates}.`);
    const evN = whole ? evs.length : events().filter((x) => !evs.some((y) => y.id === x.id)).length + evs.length;
    if (evN > EVENTS_MAX) errors.push(`A plan holds up to ${EVENTS_MAX} events; this would make ${evN}.`);
    if (!whole) {
      for (const u of units) {
        const x = joins(u);
        if (x && new Set([...(x.search || []), ...(u.search || [])]).size + (u.cut || []).filter((c) => !(x.cut || []).some((y) => y.tag === c.tag && y.in === c.in)).length > SEARCH_MAX) {
          errors.push(`${pretty(x.opens)}, ${x.name}: a date holds up to ${SEARCH_MAX} searches and cuts.`);
        }
      }
    }
    return { units, errors, missing, notes, events: evs, warns, why: why.filter(Boolean).slice(0, 60), tags: tagsIn, renamed, remarks: remarksIn };
  }

  /** The prompt for your own AI: the plan so far, the format, the deck's
   *  tags (round five: Prompts.plan, the add-on's twin). */
  function aiPrompt() {
    const { lines, more } = Prompts.tagLines({ kids: kidsOf, n, size: count.size }, cover.size ? coverItems() : null);
    return Prompts.plan({
      name: meta.name || plan.name, deck: doc.deck, start, end: doc.end || "", days: pace.days, mode: pace.mode, daily: pace.daily,
      phases: doc.phases || {}, units: doc.units.length, lines, more, cover: cover.size > 0,
      ptags: ptags().map((t) => ({ name: t.name, path: ptagPath(t), size: ptagSize(t) })),
      planned: doc.units.length ? toText() : "",
      // 3.6.5, P1: what each planned date opens, as the author's Anki counted it
      pn: doc.units.filter((u) => u.pn).map((u) => `${u.opens} ${u.name}: ${u.pn[0] + (u.cards || []).length} new, ${u.pn[1]} repeat, ${u.pn[2]} not in my deck`),
    });
  }

  /** 3.8.0: Tag by objective: the person's objectives and their own export
   *  in, the plan's tags out (tag | NAME | notes:…). Names and counts only. */
  function tagPrompt() {
    // the plan's tags as Edit the whole plan writes them; past 2,000 IDs in all, a tag's lists are a count
    const standing = Prompts.standing(ptags().map((t) => [tagLine(t), (t.notes || []).length + (t.cards || []).length,
      `${["tag", t.name, ...tagSrcs(t)].join(" | ")} (${ptagSize(t)})`]));
    return Prompts.tags({ name: meta.name || plan.name, deck: doc.deck, root: tagRootNow(), has: ptags().length > 0, standing,
      list: Prompts.tagList({ keys: [...count.keys()], order: (k) => order.get(k) ?? 0, n }) });
  }

  // 3.6.5: Text opens on Add dates (pasting can't take anything off); Edit
  // the whole plan is the box with every date in it
  let textMode = "add";
  function textTab() {
    const adding = textMode === "add";
    const ta = h("textarea", { rows: adding ? 8 : Math.max(10, doc.units.length + 3), "aria-label": adding ? "New dates as text" : "The plan as text",
      placeholder: adding ? "Paste new lines here: an AI's answer, or your own.\n2026-10-07 | Adrenergics | tag:… | for Quiz 2\n2026-10-08 | Chapter 4 | tag:… | read: Chapter 4" : "" });
    ta.value = adding ? "" : toText();
    const out = h("div", { class: "status", role: "status" });
    const preview = h("div");
    let kept = [];  // 3.8.1: tags Keep the tags put back in the text, said once
    const read = () => {
      const r = fromText(ta.value, !adding);
      const keptNow = kept; kept = [];
      let taken = null;  // 3.8.1: what Take them off those dates too did, date by date
      preview.replaceChildren();
      if (r.errors.length) { out.className = "status bad"; out.textContent = r.errors.slice(0, 6).join(" "); return; }
      if (!r.units.length && !r.events.length && !r.why.length && !r.notes.length && !r.tags.length && !r.remarks.length) { out.className = "status"; out.textContent = "Nothing to read yet."; return; }
      const render = () => {
      preview.replaceChildren();
      out.className = r.missing.length ? "status bad" : "status";
      out.textContent = `${r.units.length} date${r.units.length === 1 ? "" : "s"}${r.events.length ? `, ${r.events.length} event${r.events.length === 1 ? "" : "s"}` : ""}${r.tags.length ? `, ${r.tags.length} tag${r.tags.length === 1 ? "" : "s"}` : ""}${r.remarks.length ? `, ${r.remarks.length} note${r.remarks.length === 1 ? "" : "s"}` : ""}.${r.missing.length ? ` Not in your deck (they'd find nothing): ${r.missing.slice(0, 5).map((k) => pathOf(k)).join(", ")}${r.missing.length > 5 ? "…" : ""}` : ""}`;
      const placed = new Set(r.units.flatMap(srcs));
      const joins = (u) => adding && doc.units.some((x) => x.id === u.id);
      // P1: a date as it was keeps its count from the author's Anki
      const counted = (u) => {
        const was = doc.units.find((x) => x.id === u.id);
        if (!was?.pn || adding || JSON.stringify([srcs(was), was.search, was.nids, was.cids, was.notes, was.opens]) !== JSON.stringify([srcs(u), u.search, u.nids, u.cids, u.notes, u.opens])) return "";
        return `${(was.pn[0] + (u.cards || []).length).toLocaleString()} new · ${was.pn[1].toLocaleString()} repeat · ${was.pn[2].toLocaleString()} not in your deck`;
      };
      // 3.8.1: a date with a plan tag or a cut is counted in the author's Anki after Save, not here
      const uncounted = (u) => (u.cut || []).length || srcs(u).some((k) => k.toLowerCase().startsWith(`tag:duecrew::${tagRootNow().toLowerCase()}::`));
      const cardsLine = (u) => { const t = unitTotal(u, placed); return !t && uncounted(u) ? "counted in your Anki after you save" : `${t.toLocaleString()}${uncounted(u) ? "+" : ""} cards`; };
      // 3.8.1: a cut by its tag and the plan tag it's kept to, from the text or the plan
      const inName = (c) => (r.tags.find((t) => t.id === c.in) || ptags().find((t) => t.id === c.in) || {}).name;
      const cutText = (c) => `${Tags.word(c.tag.split("::").pop())}${inName(c) ? ` · ${inName(c)}` : ""}`;
      // the whole plan: a date kept by its name on another day, or by its cards under another name
      const keptAs = (u) => { const was = !adding && doc.units.find((x) => x.id === u.id);
        return !was ? null : was.opens !== u.opens ? ` · moved from ${pretty(was.opens)}` : String(was.name).trim() !== String(u.name).trim() ? ` · was ${was.name}` : null; };
      const rows = r.units.slice().sort((a, b) => a.opens.localeCompare(b.opens)).map((u) => h("div", { class: "pvrow" },
        h("span", {}, pretty(u.opens)), h("span", {}, h("b", {}, u.name), joins(u) ? h("span", { class: "muted small" }, " · adds to this date") : null,
          keptAs(u) ? h("span", { class: "muted small" }, keptAs(u)) : null, " ",
          h("span", { class: "muted small" }, [...srcs(u).map((k) => (count.has(k) || k.toLowerCase().startsWith(`tag:duecrew::${tagRootNow().toLowerCase()}::`) ? label(k, placed) : `${pathOf(k)} (not found)`)),
            ...(u.cut || []).map(cutText)].join(", "))),
        h("span", { class: "muted small" }, `${u.due ? `to ${pretty(u.due)}${u.even ? ", evenly" : ""} · ` : ""}${counted(u) || cardsLine(u)}`)));
      // Add: new dates go on; a line with a date's own day and name adds its picks to it
      const merge = (into, u) => {
        for (const c of u.cut || []) if (!(into.cut || []).some((x) => x.tag === c.tag && x.in === c.in)) into.cut = [...(into.cut || []), c];
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
        // 3.8.0: the plan's tags: the whole plan's text says them all; Add dates adds to them
        // 3.8.1: notes for followers the same way (a note on a tag or card already there is rewritten)
        const keepId = (x) => ({ id: (remarks().find((y) => Remarks.same(x, y)) || {}).id || uid8(), ...x });
        if (replace) putRemarks(r.remarks.map(keepId));
        else if (r.remarks.length) {
          const list = remarks().map((y) => ({ ...y }));
          for (const x of r.remarks) { const y = list.find((z) => Remarks.same(x, z)); if (y) y.text = x.text; else list.push(keepId(x)); }
          putRemarks(list);
        }
        if (replace) {
          putTags(r.tags);
          // 3.8.1: a tag renamed in the text: the dates (and notes) using its old name follow it
          for (const x of r.renamed) { const t = ptags().find((y) => y.id === x.id); if (t) retag(x.from, ptagPath(t)); }
        }
        else if (r.tags.length) {
          const list = ptags().map((t) => structuredClone(t));
          for (const t of r.tags) {
            const x = list.find((y) => y.id === t.id);
            if (!x) { list.push(t); continue; }
            for (const k of ["notes", "tags", "decks", "search"]) if ((t[k] || []).length) x[k] = [...new Set([...(x[k] || []), ...t[k]])];
            if ((t.cards || []).length) { const have = new Set((x.cards || []).map(([g, o]) => `${g}:${o}`)); x.cards = [...(x.cards || []), ...t.cards.filter(([g, o]) => !have.has(`${g}:${o}`))]; }
          }
          putTags(list);
        }
        syncCuts();  // 3.8.1: each cut's search, for an add-on before 3.8.1
        byOpens(); mark(); preview.replaceChildren(); out.className = "status";
        out.textContent = replace ? `Now ${doc.units.length} dates. Save to keep them.` : `Added. Now ${doc.units.length} dates. Save to keep them.`;
        ta.value = replace ? toText() : "";
      };
      const gone = adding ? [] : doc.units.filter((x) => !r.units.some((u) => u.id === x.id));
      const goneTags = adding ? [] : ptags().filter((t) => !r.tags.some((x) => x.id === t.id));
      // 3.8.1: the dates in the text that still use a tag it takes off
      const usesOf = (u) => goneTags.filter((t) => (u.tags || []).some((x) => x.toLowerCase() === ptagPath(t).toLowerCase())
        || (u.cut || []).some((c) => c.in === t.id) || (u.search || []).some((q) => tagRe(ptagPath(t)).test(q)));
      const using = taken ? [] : r.units.filter((u) => usesOf(u).length).sort((a, b) => a.opens.localeCompare(b.opens));
      const bare = (u) => !(srcs(u).length || (u.cards || []).length || (u.search || []).length || (u.cut || []).length || hasIds(u));
      const usingWhy = (u) => {
        const ts = usesOf(u);
        const only = (u.cut || []).filter((c) => ts.some((t) => t.id === c.in)).map((c) => `only what's in ${inName(c)}`);
        const names = ts.filter((t) => !(u.cut || []).some((c) => c.in === t.id)).map((t) => t.name);
        const left = structuredClone(u); takeOff(left, ts);
        return `${[...names, ...only].join(", ")}${bare(left) ? ", nothing else on it: it would find nothing" : ""}`;
      };
      /** the tags off one date: a plan tag and its searches go, a cut is its whole tag again */
      function takeOff(u, ts) {
        for (const t of ts) {
          u.tags = (u.tags || []).filter((x) => x.toLowerCase() !== ptagPath(t).toLowerCase());
          for (const c of (u.cut || []).filter((x) => x.in === t.id)) { takeCut(u, c); u.tags = [...new Set([...u.tags, c.tag])]; }
          for (const q of [...(u.search || [])]) if (tagRe(ptagPath(t)).test(q)) takeSearch(u, q);
        }
      }
      const takeAll = () => {
        taken = using.map((u) => {
          const ts = usesOf(u), cuts = (u.cut || []).filter((c) => ts.some((t) => t.id === c.in));
          const was = u.name;
          takeOff(u, ts);
          if (auto.has(u.id) && !bare(u)) u.name = autoName(u);
          const what = bare(u) ? "nothing left on it, so it goes"
            : [ts.filter((t) => !cuts.some((c) => c.in === t.id)).map((t) => `${t.name} off it`).join(", "),
              cuts.map((c) => `back to all of ${Tags.word(c.tag.split("::").pop())}`).join(", ")].filter(Boolean).join("; ");
          return `${pretty(u.opens)} · ${was}: ${what}`;
        });
        r.units = r.units.filter((u) => !bare(u));
        render();
      };
      const keepTags = () => {
        kept = goneTags.map((t) => t.name);
        ta.value = [...goneTags.map(tagLine), ta.value].join("\n");
        read();
      };
      const tagRows = r.tags.map((t) => {
        const was = ptags().find((x) => x.id === t.id);
        const what = [(t.notes || []).length ? `${t.notes.length.toLocaleString()} notes` : "", (t.cards || []).length ? `${t.cards.length.toLocaleString()} single card${t.cards.length === 1 ? "" : "s"}` : "",
          ptagFrom(t).length ? `from ${ptagFrom(t).join(", ")}` : ""].filter(Boolean).join(", ");
        return h("div", { class: "pvrow" }, h("span", {}, was ? "Tag" : "New tag"), h("span", {}, h("b", {}, t.name), adding && was ? h("span", { class: "muted small" }, " · adds to it") : null,
          was && was.name !== t.name ? h("span", { class: "muted small" }, ` · was ${was.name}`) : null),
          h("span", { class: "muted small" }, what));
      });
      // 3.8.1: notes for followers, by what they're on (a card by its ID and number, never its text)
      const rmkOn = (x) => (x.card ? `${x.card[0]} · card ${x.card[1] + 1}`
        : ([...r.tags, ...ptags()].find((t) => ptagPath(t).toLowerCase() === x.tag.toLowerCase()) || {}).name || Tags.name(x.tag));
      const rmkRows = r.remarks.map((x) => h("div", { class: "pvrow" }, h("span", {}, remarks().some((y) => Remarks.same(x, y)) ? "Note" : "New note"),
        h("span", {}, h("b", { class: x.card ? "mono" : "" }, rmkOn(x))), h("span", { class: "muted small" }, x.text)));
      const goneRmk = adding ? [] : remarks().filter((y) => !r.remarks.some((x) => Remarks.same(x, y)));
      // 3.6.5: a day over the pace, as it would be after this
      const cap = pace.mode === "end" ? endDaily() || pace.daily : pace.mode === "daily" ? pace.daily : 0;
      const after = adding ? [...doc.units.filter((x) => !r.units.some((u) => u.id === x.id)), ...r.units] : r.units;
      // 3.8.1: the work each day would ask, each date spread to its due date (Work)
      const heavy = Work.over(workMap({ ...doc, units: after }, placed), cap);
      const goneText = gone.slice(0, 6).map((u) => `${pretty(u.opens)}, ${u.name}`).join(" · ") + (gone.length > 6 ? ` and ${gone.length - 6} more` : "");
      preview.append(h("div", { class: "pv" }, tagRows, rows, rmkRows,
        gone.length ? h("p", { class: "warn small" }, h("b", {}, `Takes off ${gone.length} date${gone.length === 1 ? "" : "s"}: `), goneText) : null,
        goneRmk.length ? h("p", { class: "warn small" }, h("b", {}, `Takes off ${goneRmk.length} note${goneRmk.length === 1 ? "" : "s"}: `),
          goneRmk.slice(0, 4).map(rmkOn).join(" · ") + (goneRmk.length > 4 ? ` and ${goneRmk.length - 4} more` : "")) : null,
        keptNow.length ? h("div", { class: "pvrow" }, h("span", {}, "Tags"), h("span", {}, `${keptNow.join(", ")} stay${keptNow.length === 1 ? "s" : ""}: ${keptNow.length === 1 ? "its line is" : "their lines are"} back in the text.`)) : null,
        goneTags.length && using.length ? h("div", { class: "warnbox small" },
          h("b", {}, `Takes off ${goneTags.length} tag${goneTags.length === 1 ? "" : "s"}: ${goneTags.map((t) => t.name).join(", ")}.`),
          ` ${using.length} date${using.length === 1 ? " still uses" : "s still use"} ${goneTags.length === 1 ? "it" : "them"}:`,
          h("ul", {}, using.slice(0, 8).map((u) => h("li", {}, `${pretty(u.opens)} · ${u.name} (${usingWhy(u)})`)),
            using.length > 8 ? h("li", {}, `and ${using.length - 8} more`) : null),
          h("div", { class: "muted" }, "What these dates already opened stays open."))
          : goneTags.length ? h("p", { class: "warn small" }, h("b", {}, `Takes off ${goneTags.length} tag${goneTags.length === 1 ? "" : "s"}: `), goneTags.map((t) => t.name).join(", "),
            taken?.length ? h("ul", { style: "margin:4px 0 0;padding-left:20px;text-align:left" }, taken.slice(0, 8).map((x) => h("li", {}, x)), taken.length > 8 ? h("li", {}, `and ${taken.length - 8} more`) : null) : null) : null,
        heavy.length ? h("p", { class: "warn small" }, h("b", {}, "Over your pace: "), heavy.slice(0, 6).map((x) => `${x.a === x.b ? pretty(x.a) : `${pretty(x.a)} – ${pretty(x.b)}`}, ${x.top.toLocaleString()} new a day`).join(" · "),
          ` (pace ${cap.toLocaleString()} a day)`) : null,
        r.warns.length ? h("p", { class: "warn small" }, r.warns.slice(0, 4).join(" ")) : null,
        r.notes.length ? h("div", { class: "hnote" }, h("span", {}, h("b", {}, "To pick in Anki: "), r.notes.map(pickNote).join(" · "))) : null,
        r.why.length ? h("details", { class: "small", open: !r.units.length }, h("summary", {}, `The AI's notes (${r.why.length})`),
          h("ul", { class: "muted", style: "margin:4px 0 0;padding-left:20px;text-align:left" }, r.why.map((x) => h("li", {}, x.slice(0, 300))))) : null,
        h("div", { class: "row" },
          using.length ? h("button", { onclick: takeAll }, "Take them off those dates too") : null,
          using.length ? h("button", { onclick: keepTags }, "Keep the tags") : null,
          adding ? (r.units.length || r.events.length || r.tags.length || r.remarks.length ? h("button", { onclick: () => use(false) }, "Add to the plan") : null)
            : h("button", { class: gone.length || goneTags.length || goneRmk.length ? "danger" : "", onclick: () => use(true) }, using.length ? "Replace anyway" : "Replace the plan's dates"),
          h("button", { class: "quiet", onclick: () => { preview.replaceChildren(); out.textContent = ""; } }, "Cancel"))));
      };
      render();
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
        h("details", {}, h("summary", { class: "small" }, "See it"), h("pre", { class: "mono small muted aipre" }, aiPrompt()))),
      // 3.8.0: tag by objective: the plan's own tags, made by the AI from your export
      h("div", { class: "aitag" },
        h("b", {}, "Tag by objective"),
        h("p", { class: "muted small" }, "Your course's objectives in, the plan's tags out (SLG 12), on everyone's cards who follows it. The AI reads your cards from your own export; Due Crew never sees them."),
        h("ol", { class: "muted small", style: "margin:4px 0;padding-left:20px;text-align:left" },
          h("li", {}, "In Anki: Tools › Due Crew › Export cards for my AI."),
          h("li", {}, "Copy this prompt, add your objectives where it says, and attach the export."),
          h("li", {}, "Paste the answer into Add dates. The new tags show before anything changes.")),
        h("div", { class: "row" }, h("button", { class: "ghost", onclick: (e) => copy(tagPrompt(), e.target) }, "Copy the tagging prompt"),
          h("details", {}, h("summary", { class: "small" }, "See it"), h("pre", { class: "mono small muted aipre" }, tagPrompt())))));
    return h("div", { class: "stack" },
      aiBox,
      h("details", { class: "fmt" }, h("summary", { class: "small" }, "Format"),
        h("p", { class: "muted small" }, "One line per date: when it opens, a name, the tags and subdecks (or notes: with note IDs: in Anki's browser, Due Crew › Copy as plan selector), and an optional due date, separated by |. Add even to split a date evenly up to its due date. A note line puts your words on a tag or a card, in followers' Anki. For example:"),
        h("pre", { class: "mono small muted", style: "margin:0;white-space:pre-wrap" }, "2026-10-05 | Heart failure | tag:Step1::Cardio::Heart_failure | due 2026-10-09 | even\nweek 2 | Arrhythmia | tag:Step1::Cardio::Arrhythmia\n2026-10-19 | Lecture 12 | notes:Ab3$kL9qZ1 p&x8Hk!eQ2\n2026-10-20 | Chapter 4 | deck:Chemistry::Unit 3::Chapter 4 | read: Chapter 4, sections 1 to 3\nnote | tag:Step1::Cardio::Arrhythmia | Lecture 9's slides cover this better than the book."),
        h("a", { class: "small", href: "/plan-text", target: "_blank", rel: "noopener" }, "The whole format ›")),
      h("div", { class: "row" }, modes, h("span", { class: "muted small" }, adding
        ? `Adds to the plan's ${doc.units.length} date${doc.units.length === 1 ? "" : "s"}. A line with a date's own day and name adds to that date.`
        : "Read it shows what would change. Nothing does until you Replace the plan's dates, and Save.")),
      ta, h("div", { class: "row" }, readBtn), out, preview);
  }


  // ---- settings ----
  function settingsTab() {
    const name = h("input", { id: "sname", maxlength: 60, value: meta.name, style: "width:100%", oninput: (e) => { meta.name = e.target.value; mark("sname"); } });
    const line = h("input", { id: "sline", maxlength: 120, value: meta.line, style: "width:100%", placeholder: "Organ systems, one a week, done by January.", oninput: (e) => { meta.line = e.target.value; mark("sline"); } });
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
    // 3.8.1: where to get the deck, for a follower whose Anki has none by its name (the link page, the poster, Anki)
    const urlSay = h("small", { class: "muted" }, `On its link page and poster, and in Anki for anyone with no deck called ${doc.deck}.`);
    const deckUrl = h("input", { id: "sdeckurl", type: "url", maxlength: 300, value: doc.deckUrl || "", placeholder: "https://…", style: "width:100%", spellcheck: "false",
      onchange: (e) => {
        const v = e.target.value.trim();
        if (!v) { if (doc.deckUrl) { delete doc.deckUrl; mark(); } return; }
        if (deckLink(v)) { if (v !== doc.deckUrl) { doc.deckUrl = v; mark(); } return; }
        e.target.value = doc.deckUrl || "";
        urlSay.className = "warn"; urlSay.textContent = "A link starts with https://, has no spaces or quotes, and is 300 characters at most.";
      } });
    return h("div", { class: "stack", style: "max-width:560px" },
      h("label", { for: "sname" }, "Name"), name,
      h("label", { for: "sline" }, "One line"), line,
      h("label", { for: "sdeckurl" }, "Where to get the deck (a link, optional)"), deckUrl, urlSay,
      h("label", { for: "ssquad" }, "Offer it to one of my squads"), sq,
      h("label", {}, "Who can follow"), aud("code", "Anyone with the code"), aud("squad", meta.squad ? "Only people in that squad of mine" : "Only people in one of my squads (choose one above)"),
      h("label", {}, "Co-authors"), coauthorsBox(),
      h("label", { for: "pend" }, "Ends (optional)"), h("div", { class: "row" }, endIn, h("span", { class: "muted small" }, "the exam, or the course's last day")),
      h("label", { for: "pcatch" }, "Catch-up weeks (nothing new)"), catchup,
      h("label", { for: "ptaper" }, "Review-only days at the end"), h("div", { class: "row" }, taper, h("span", { class: "muted small" }, "before the end date: no new cards")),
      h("label", {}, "Library"), libraryBox(),
      h("div", { style: "margin-top:18px" }, del));
  }

  /** 3.8.1: the plan's co-authors (Settings, the owner's). Each says yes first: an invited one
   *  waits (Take back); one who said yes can be handed the plan, which they say yes to as well
   *  (offered, Take back), or taken off. At once, not with Save: each click is one request. */
  let coaSaid = "";  // what the last click did, said under the list
  function coauthorsBox() {
    const eds = plan.editors || [];
    const st = h("span", { class: "status small", role: "status" }, coaSaid);
    coaSaid = "";
    const failed = (text) => { st.className = "status bad small"; st.textContent = text; };
    const offered = plan.handover ? eds.find((e) => e.uid === plan.handover) || { uid: plan.handover, name: "?" } : null;
    const remove = async (e, btn) => {
      btn.disabled = true;
      try { await api("DELETE", `/plans/${id}/editors/${e.uid}`); }
      catch { btn.disabled = false; failed(e.pending ? `${e.name} is still asked. Try again.` : `${e.name} is still a co-author. Try again.`); return; }
      plan = { ...plan, editors: eds.filter((x) => x.uid !== e.uid), handover: plan.handover === e.uid ? null : plan.handover };
      draw();
    };
    const offer = async (uid, btn) => {
      btn.disabled = true;
      let r;
      try { r = await api("POST", `/plans/${id}/owner`, { uid }); }
      catch (err) { btn.disabled = false; failed(err.body?.error === "not_coauthor" ? "Only a co-author who said yes can be handed it." : "That didn't work. Try again."); return; }
      plan = { ...plan, editors: r?.editors || plan.editors, handover: r && "handover" in r ? r.handover : uid };
      if (uid) coaSaid = "They'll see it on their home page and in Anki. It's theirs once they say yes.";
      draw();
    };
    const rows = eds.map((e) => h("div", { class: "coa" },
      e.pending ? h("span", {}, "Invited, waiting for ", h("b", {}, e.name)) : h("b", {}, e.name),
      h("span", { class: "sp" }),
      e.pending ? h("button", { class: "linkish", onclick: (ev) => remove(e, ev.currentTarget) }, "Take back")
        : [offered ? null : h("button", { class: "linkish", onclick: (ev) => offer(e.uid, ev.currentTarget) }, `Hand it to ${e.name}`),
          h("button", { class: "linkish", onclick: (ev) => remove(e, ev.currentTarget) }, "Remove")]));
    const pick = h("span");
    const add = eds.length >= 10 ? h("span", { class: "muted small" }, "A plan has up to 10 co-authors.") : h("button", { class: "linkish", onclick: async () => {
      let b;
      try { b = await api("GET", "/friends"); } catch { failed("Couldn't load your crew. Try again."); return; }
      const have = new Set([plan.owner, ...eds.map((x) => x.uid)]);
      const crew = (b.friends || []).filter((f) => f.mutual && !have.has(f.uid));
      pick.replaceChildren(crew.length
        ? h("select", { "aria-label": "Ask a co-author", onchange: async (e) => {
          const who = crew.find((f) => f.uid === e.target.value);
          if (!who) return;
          e.target.disabled = true;
          try { plan = { ...plan, editors: (await api("POST", `/plans/${id}/editors`, { uid: who.uid })).editors }; }
          catch (err) {
            e.target.disabled = false; e.target.value = "";
            failed(err.body?.error === "too_many_editors" ? "A plan has up to 10 co-authors."
              : err.body?.error === "not_crew" ? "Co-authors come from your crew: you add each other." : "That didn't work. Try again.");
            return;
          }
          coaSaid = `Asked ${who.name}. They'll see it on their home page and in Anki.`;
          draw(); } },
          h("option", { value: "" }, "Pick from your crew"), crew.map((f) => h("option", { value: f.uid }, f.name)))
        : h("span", { class: "muted small" }, "Co-authors come from your crew."));
    } }, "+ Co-author");
    return h("div", { class: "coas" },
      h("small", { class: "muted" }, "They edit it with you, and its tags go on their notes in Anki. Each one says yes first."),
      offered ? h("div", { class: "coa offer" }, h("span", {}, "Offered to ", h("b", {}, offered.name)), " · ",
        h("button", { class: "linkish", onclick: (ev) => offer(null, ev.currentTarget) }, "Take back")) : null,
      rows, h("div", { class: "row" }, add, pick), st);
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
    const eds = (plan.editors || []).filter((x) => x.uid !== me.uid && !x.pending).map((x) => x.name);  // 3.8.1: an invite isn't one yet
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
    const st = h("span", { class: "status", role: "status" });
    return h("span", { class: "resetask" }, h("br"), `Reset to default? ${what}. Cards already open stay open. `,
      h("button", { class: "linkish", onclick: async () => {
        try {
          await api("PATCH", `/plans/${id}/follow`, { shift: 0, skipped: [], moved: {}, paused: false, until: null, since: null });
          plan = await api("GET", `/plans/${id}`);
        } catch (e) { if (!e.status) console.error(e); st.className = "status bad"; st.textContent = " That didn't reset. Try again."; return; }
        resetAsk = false; draw();
      } }, "Reset"), " · ",
      h("button", { class: "linkish", onclick: () => { resetAsk = false; draw(); } }, "Cancel"), st);
  }

  /** 3.8.0: a follower's "how its cards open": on the plan's dates, or at my own
   *  pace (my Anki opens the next date when I ask, or once I've seen the last).
   *  Mine only; the plan never changes. Next is the first date not all open yet,
   *  by the progress my Anki syncs. */
  function paceBox() {
    const f = !author && plan.following;
    if (!f) return null;
    const own = f.own || "";
    const prog = f.progress || {};
    const skipped = new Set(f.skipped || []);
    const next = own ? [...(doc.units || [])].filter((u) => !skipped.has(u.id)).sort((a, b) => (a.opens < b.opens ? -1 : a.opens > b.opens ? 1 : 0))
      .find((u) => { const c = prog[u.id]; return !c || (c[2] > 0 && c[0] < c[2]); }) : null;  // not counted yet: not open yet
    const st = h("span", { class: "status", role: "status" });
    const sel = h("select", { "aria-label": "How its cards open", onchange: async (e) => {
      sel.disabled = true;
      try {
        await api("PATCH", `/plans/${id}/follow`, { own: e.target.value || null });
        plan = await api("GET", `/plans/${id}`);
      } catch (err) {
        if (!err.status) console.error(err);
        sel.disabled = false; sel.value = own; st.className = "status bad"; st.textContent = " That didn't change. Try again.";
        return;
      }
      draw();
    } }, [["", "on the plan's dates"], ["ready", "when I'm ready"], ["next", "when I'm ready, the next once I've seen most of the last"]]
      .map(([v, t]) => h("option", { value: v, selected: own === v }, t)));
    return h("div", { class: "pacebox small" },
      own ? h("div", {}, h("b", {}, "At your pace"), next ? ` · next: ${next.name || "?"}` : " · every date is open",
        h("span", { class: "muted" }, next ? ". Your Anki opens it from You › Plans." : ".")) : null,
      h("label", { class: "muted" }, "Cards open ", sel), st);
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
        nextYear(),
        h("span", { class: "lbl" }, "Planning it with"),
        people()));
  }

  /** 3.9.2 (Sam's pick C3-A): next year's class gets this plan: a copy of
   *  my own with every date 52 weeks on, so each keeps its weekday, named
   *  "… (next year)" (Sam's pick), not "(copy)". */
  function nextYear() {
    const firstOf = (d) => [...(d.units || []).map((u) => u.opens), ...(d.events || []).map((e) => e.day)].filter(Boolean).sort()[0];
    // "… (next year)" within a plan name's 60: an earlier "(next year)" or "(copy)" off, cut at a word (3.9.2's QoL pass)
    function named(n) {
      let b = String(n || "").replace(/\s*\((?:next year|copy)\)\s*$/i, "").trim();
      if (b.length > 48) { b = b.slice(0, 48); const sp = b.lastIndexOf(" "); if (sp > 24) b = b.slice(0, sp); }
      return `${b.trimEnd()} (next year)`;
    }
    const first = firstOf(doc);
    if (!first) return null;
    const st = h("span", { class: "status small", role: "status" });
    const b = h("button", { class: "linkish", title: `Its first date on ${pretty(addDays(first, 364))}, every date 52 weeks on`, onclick: async () => {
      // 3.9.2's audit: the copy is made of the plan as saved, so it waits for a save, and its first
      // date comes from the saved plan as it is now (a co-author's save since), 364 days on: weekdays kept
      if (dirty) { st.className = "status small bad"; st.textContent = "Save your changes first, so they're in the copy."; return; }
      b.disabled = true; st.className = "status small"; st.textContent = "Copying…";
      try {
        const got = await api("GET", `/plans/${plan.id}`);
        const saved = firstOf(got.doc || {});
        if (!saved) throw new Error("no dates");
        let mine = await api("POST", `/plans/${plan.id}/copy`, { start: addDays(saved, 364) });
        try {
          mine = await api("PUT", `/plans/${mine.id}`, { version: mine.version, name: named(got.name || plan.name), summary: "named for next year" });
        } catch (_) { /* the copy stands, named "(copy)"; Settings renames it */ }
        go(`/plans/${mine.id}`);
      } catch (err) {
        b.disabled = false; st.className = "status small bad";
        const code = err.body?.error;
        st.textContent = err.message === "no dates" ? "The saved plan has no dates to copy."
          : code === "too_many_plans" ? "You have 50 plans. Delete one first."
          : code === "plans_full" ? "Your plans hold as much as one account can. Delete one first."
          : err.status === 429 ? "That's a lot of new plans. Try again in an hour."
          : !err.status ? "That didn't copy: check your connection, then try again." : "That didn't work. Try again.";
      }
    } }, "Copy for next year");
    return h("div", { class: "row" }, b, st);
  }

  /** The people who write the plan. 3.8.1: the owner asks co-authors in Settings, where each one
   *  says yes first; an invited one shows here as invited. A co-author leaves with their ×. */
  function people() {
    const eds = plan.editors || [];
    const all = [{ uid: plan.owner, name: plan.ownerName }, ...eds.filter((x) => !x.pending)];
    const st = h("span", { class: "status small", role: "status" });
    const chips = all.map((p) => h("span", { class: "who2", title: p.uid === plan.owner ? "Made it" : "Co-author" },
      p.uid === me.uid ? "You" : p.name,
      plan.role === "editor" && p.uid === me.uid
        ? h("button", { class: "x", "aria-label": "Leave", onclick: async () => {
          try { await api("DELETE", `/plans/${id}/editors/${p.uid}`); } catch { st.className = "status bad small"; st.textContent = "That didn't work. Try again."; return; }
          go("/plans"); } }, "×") : null));
    const asked = eds.filter((x) => x.pending).map((x) => h("span", { class: "who2 wait", title: "Asked; hasn't said yes yet" }, `${x.name}, invited`));
    const more = owner ? h("button", { class: "linkish", onclick: () => { tab = "settings"; shareOpen = false; draw(); } }, "Co-authors…") : null;
    return h("div", { class: "people2" }, chips, asked, more, st);
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
    // 3.8.1 (Sam's pick): first steps, while the plan as saved has no dates: the step to do now bold, done ones ticked
    const firstSteps = author && view !== "print" && !(plan.doc.units || []).length ? (() => {
      const steps = [["Tick what to cover", cover.size > 0 || doc.units.length > 0],
        [pace.mode === "placed" ? "Drag tags onto days" : fillLabel, doc.units.length > 0],
        ["Save", false], [meta.audience === "squad" ? "Your squad finds it in Anki" : "Share the code", false]];
      const now = steps.findIndex(([, done]) => !done);
      return h("ol", { class: "firststeps", "aria-label": "First steps" }, steps.map(([t, done], i) =>
        h("li", { class: done ? "done" : i === now ? "now" : "", "aria-current": i === now ? "step" : null },
          h("span", { class: "n", "aria-hidden": "true" }, done ? "✓" : String(i + 1)), i === now ? h("b", {}, t) : t)));
    })() : null;
    const main = h("div", { class: "main2" },
      firstSteps, paceBox, view === "print" ? null : everyBox(), view === "print" ? null : followTags(),
      h("div", { class: "calcard" }, nav, fillRow, view === "text" || view === "print" ? null : heavyNote(), inner,
        view === "text" || view === "print" ? null : reviewsNote()),
      view === "print" ? null : cardNotes());
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
    for (const c of u.cut || []) {  // 3.8.1: in its tag's group, named for both (plans.py topic_items)
      const segs = c.tag.split("::");
      const ri = segs.findIndex((x, i) => i > 0 && /^[#^]/.test(x));
      put(ri >= 0 && ri < segs.length - 1 ? Tags.word(segs[ri]) : "", cutName(c));
    }
    for (const q of u.search || []) if (!cutOf(u, q)) put("Search", searchName(q).replace(/^Search:\s*/, ""));
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
      // 3.8.1: where to get the deck; on paper, its address shows
      deckLink(doc.deckUrl) ? h("p", { class: "pdeck" }, h("a", { href: doc.deckUrl, target: "_blank", rel: "noopener" }, "Where to get it ›"), " ",
        h("span", { class: "purl" }, doc.deckUrl.replace(/^https:\/\//, ""))) : null,
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
        cells.push(h("span", { class: "t" }, `${u.name}${part}`, fx ? h("span", { class: "fx" }, ` · ${forWord(u)} ${fx.name}, ${pretty(fx.day)}`) : null),
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
    if (pr.sharing < 3) {
      return h("div", {}, h("p", { class: "muted small" }, `${pr.sharing} of ${pr.followers} ${pr.sharing === 1 ? "is" : "are"} in its squad. Each date's counts show once 3 or more are in it.`));
    }
    return h("div", {},
      classHints(pr),
      h("p", { class: "muted small" }, `${pr.sharing} of ${pr.followers} are in its squad; these counts are theirs.`),
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
      history = "loading";
      api("GET", `/plans/${id}/log`).then((r) => { history = r.log; draw(); }).catch(() => { history = "failed"; draw(); });
      return h("p", { class: "muted" }, "Loading…");
    }
    if (history === "loading") return h("p", { class: "muted" }, "Loading…");
    if (history === "failed") return h("p", { class: "muted" }, "Couldn't load the history. ", h("button", { class: "linkish", onclick: () => { history = null; draw(); } }, "Try again"));
    if (!history.length) return h("p", { class: "muted" }, "Nothing yet. Each save shows here.");
    const ago2 = (t) => { const m = Math.round((Date.now() / 1000 - t) / 60); return m < 1 ? "just now" : m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : pretty(iso(new Date(t * 1000))); };
    return h("div", { class: "hist" }, history.map((l) => h("div", { class: "hrow" },
      h("span", {}, h("b", {}, l.uid === me.uid ? "You" : l.name), ` ${l.summary}`), h("small", { class: "muted" }, ago2(l.at)),
      l.undo ? h("button", { class: "linkish", onclick: async () => {
        if (dirty && !confirm("Undo drops your unsaved changes here too.")) return;
        try {
          plan = await api("POST", `/plans/${id}/undo`, { version: l.version });
          reload(plan.doc); history = null;  // the pace, what to cover and the start come with it
          status.className = "status"; status.textContent = "Undone";
        } catch { status.className = "status bad"; status.textContent = "That changed since. Reload."; }
        draw(); } }, "Undo") : h("span"))));
  }

  /** 3.7.3: what the authors said to followers, newest first; the authors post
   *  here any time (a save's "Tell followers" lands here too). Anki shows
   *  the newest unread on the plan, the site's home lists them. */
  function updatesTab() {
    if (!posts) {
      posts = "loading";
      api("GET", `/plans/${id}/posts`).then((r) => { posts = r.posts; draw(); }).catch(() => { posts = "failed"; draw(); });
      return h("p", { class: "muted" }, "Loading…");
    }
    if (posts === "loading") return h("p", { class: "muted" }, "Loading…");
    if (posts === "failed") return h("p", { class: "muted" }, "Couldn't load the updates. ", h("button", { class: "linkish", onclick: () => { posts = null; draw(); } }, "Try again"));
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

  const ago = (t) => { const m = Math.round((Date.now() / 1000 - t) / 60); return m < 1 ? "now" : m < 60 ? `${m}m` : m < 1440 ? `${Math.round(m / 60)}h` : m < 2880 ? "yesterday" : `${Math.round(m / 1440)}d`; };

  /** 3.8.0: the plan's squad lives on the board's Squads tab. In it: the
   *  way there. Following, not in it: what it shares, and the way in. */
  function squadLine() {
    if (!plan.following) return null;
    const open = () => { Board.store("dc-tab", "squads"); Board.store("dc-squad", `plan:${id}`); go("/"); };
    if (plan.following.share && !plan.following.teamAsk) {
      return h("p", { class: "small", style: "margin:4px 0 10px" }, "You’re in its squad. ", h("button", { class: "linkish", onclick: open }, "Open it ›"));
    }
    const st = h("span", { class: "status", role: "status" });
    const join = h("button", { class: "linkish", onclick: async () => {
      join.disabled = true;
      try { await api("POST", `/plans/${id}/team`); PlanSquad.forget(id); open(); }
      catch (err) { join.disabled = false; st.className = "status bad"; st.textContent = err.body?.error === "team_full" ? "This squad is full." : "That didn't work. Try again."; }
    } }, "Join its squad");
    return h("p", { class: "small muted", style: "margin:4px 0 10px" }, "Its squad sees that you showed up today, and your questions and answers; your progress counts for the plan’s authors. Never your numbers. ", join, " ", st);
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

  // 3.8.0 (Board in Motion, 34): ‹ › slide the calendar; a date moved to another day settles there
  let slid = 0;
  function draw() {
    const M = window.dcMotion, at = `${view}|${anchor}`, was = M ? M.places(".cal2 .ch[data-k]", "data-k", ".d") : null;
    // the side's lists keep their place through a redraw (a click on a tag low in a list)
    const kept = [".ptags .ptlist", ".tree2 .tlist"].map((q) => [q, document.querySelector(q)?.scrollTop || 0]);
    const y = window.scrollY;
    drawNow();
    if (y) window.scrollTo(0, y);
    for (const [q, y] of kept) { const el = y && document.querySelector(q); if (el) el.scrollTop = y; }
    // the same days on screen: a date moved to another settles; ‹ › slide; another view just draws
    try { if (M && (slid || at === `${view}|${anchor}`)) M.moved(".cal2 .ch[data-k]", "data-k", was, slid, ".cal2", ".d"); } catch { /* drawn either way */ }
    slid = 0;
  }
  function drawNow() {
    const tabBtn = (k, t) => h("button", { role: "tab", "aria-selected": String(tab === k), onclick: () => { tab = k; draw(); } }, t);
    // the plan's name, edited in place: it wraps and grows, so a long name is never cut off
    function titleBox() {
      const t = h("textarea", { class: "tname", rows: 1, maxlength: 60, "aria-label": "The plan's name", spellcheck: "false" });
      t.value = meta.name;
      const fit = () => { t.style.height = "auto"; t.style.height = `${t.scrollHeight}px`; };
      t.addEventListener("input", () => { t.value = t.value.replace(/[\r\n]+/g, " "); meta.name = t.value; mark("title"); fit(); });
      t.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); t.blur(); } });
      requestAnimationFrame(fit);
      // and again whenever its width changes (a window resized, the page laid out late)
      if (window.ResizeObserver) { let w = 0; new ResizeObserver(() => { if (t.clientWidth !== w) { w = t.clientWidth; fit(); } }).observe(t); }
      return t;
    }
    // 3.7.3: followers see the calendar (the authors' posts show above it); authors keep Updates.
    // 3.8.0: the plan's squad lives on the board's Squads tab; squadLine() goes there
    const tabs = author ? [["calendar", "Calendar"], ["updates", "Updates"], ["progress", "Progress"], ["history", "History"], owner ? ["settings", "Settings"] : null].filter(Boolean) : [];
    if (!tabs.some(([k]) => k === tab)) tab = "calendar";
    const body = tab === "settings" ? settingsTab() : tab === "progress" ? progressTab() : tab === "history" ? historyTab()
      : tab === "updates" ? updatesTab() : calendarTab();
    page(
      h("div", { class: "bhead" },
        h("div", { class: "btitle" }, owner ? titleBox() : h("h1", {}, meta.name || "Untitled"),
          h("p", { class: "muted small bsub" }, subline(), resetBtn())),
        author ? share() : plan.code && plan.audience !== "squad" ? calMenu(plan.code) : null),
      !author && plan.following && !plan.following.own ? onTrack(plan, false) : null,  // 3.8.0: at my own pace, no Behind
      paceBox(),
      !author && plan.following ? finished() : null,
      !author && !plan.following ? readerActions() : null,
      postLine(),
      squadLine(),
      tabs.length ? h("div", { class: "tabs", role: "tablist" }, tabs.map(([k, t]) => tabBtn(k, t))) : null,
      body,
      author ? h("div", { class: `savebar${dirty || status.classList.contains("bad") || flash ? "" : " clean"}` }, status,
        plan.followers > (plan.following ? 1 : 0) ? tell : null, undoBtn, saveBtn) : null);
    $app().classList.add("wide");
  }

  // a date the same but for its refreshed card count hasn't changed
  // 3.8.1: in any key order (a date read from text has its keys in another order than the server's)
  const canon = (v) => (Array.isArray(v) ? v.map(canon) : v && typeof v === "object"
    ? Object.fromEntries(Object.keys(v).sort().filter((k) => v[k] !== undefined).map((k) => [k, canon(v[k])])) : v);
  const same = (x, y) => JSON.stringify(canon({ ...x, n: 0 })) === JSON.stringify(canon({ ...y, n: 0 }));

  /** What a save did, in a few words, for the history. */
  function describe(before, after) {
    const b = new Map((before.units || []).map((u) => [u.id, u]));
    const a = new Map((after.units || []).map((u) => [u.id, u]));
    const out = [];
    // 3.8.1: the plan's tags, by id: a new name is a rename, and a date that only followed it
    // (its tag, its searches, a name made from it) hasn't changed
    const bt = new Map((before.tags || []).map((t) => [t.id, t])), at = new Map((after.tags || []).map((t) => [t.id, t]));
    const ren = [...at.values()].filter((t) => bt.has(t.id) && bt.get(t.id).name !== t.name).map((t) => [bt.get(t.id), t]);
    const pathIn = (d, t) => `DueCrew::${d.tagroot || tagRootNow()}::${Tags.part(t.name)}`;
    // each string on its own (never the JSON text, where a name could land inside a number): a whole
    // tag path, the tag inside a search, and the old name inside the date's own name, word for word
    const subst = (v, key) => {
      for (const [o, t] of ren) {
        const p0 = pathIn(before, o), p1 = pathIn(after, t);
        if (v === p0) { v = p1; continue; }
        v = v.split(Tags.ankiSearch("tag", p0)).join(Tags.ankiSearch("tag", p1));
        if (key === "name") v = v.replace(new RegExp(`(?<![\\p{L}\\p{N}])${o.name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?![\\p{L}\\p{N}])`, "gu"), () => t.name);
      }
      return v;
    };
    const walk = (v, key) => (typeof v === "string" ? subst(v, key) : Array.isArray(v) ? v.map((x) => walk(x, key))
      : v && typeof v === "object" ? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, walk(x, k)])) : v);
    const follow = (u) => (ren.length ? walk(u, "") : u);
    const added = [...a.values()].filter((u) => !b.has(u.id));
    const gone = [...b.values()].filter((u) => !a.has(u.id));
    const moved = [...a.values()].filter((u) => b.has(u.id) && b.get(u.id).opens !== u.opens);
    const changed = [...a.values()].filter((u) => b.has(u.id) && b.get(u.id).opens === u.opens && !same(follow(b.get(u.id)), u));
    // a date whose only change is its name: "updated Fri 16 Oct" (its new name is no help in the history)
    const nameOnly = (u) => same({ ...follow(b.get(u.id)), name: "" }, { ...u, name: "" });
    const updated = changed.filter(nameOnly), other = changed.filter((u) => !nameOnly(u));
    if (moved.length === 1) out.push(`moved ${moved[0].name} to ${pretty(moved[0].opens)}`); else if (moved.length) out.push(`moved ${moved.length} dates`);
    if (added.length === 1) out.push(`added ${added[0].name} on ${pretty(added[0].opens)}`); else if (added.length) out.push(`added ${added.length} dates`);
    if (gone.length === 1) out.push(`took off ${gone[0].name}`); else if (gone.length) out.push(`took off ${gone.length} dates`);
    if (other.length === 1) out.push(`changed ${other[0].name}`); else if (other.length) out.push(`changed ${other.length} dates`);
    if (updated.length === 1) out.push(`updated ${pretty(updated[0].opens)}`); else if (updated.length) out.push(`updated ${updated.length} dates`);
    const nTags = (k) => `${k} tag${k === 1 ? "" : "s"}`, nNotes2 = (k) => `${k} note${k === 1 ? "" : "s"}`;
    const tAdded = [...at.keys()].filter((id) => !bt.has(id)).length, tGone = [...bt.keys()].filter((id) => !at.has(id)).length;
    const tChanged = [...at.values()].filter((t) => bt.has(t.id) && !same({ ...bt.get(t.id), name: "" }, { ...t, name: "" })).length;
    if (ren.length) out.push(`renamed ${nTags(ren.length)}`);
    if (tAdded) out.push(`added ${nTags(tAdded)}`);
    if (tGone) out.push(`took off ${nTags(tGone)}`);
    if (tChanged) out.push(`changed ${nTags(tChanged)}`);
    // 3.8.1: notes for followers on a tag or a card
    const br = new Map((before.remarks || []).map((x) => [x.id, x])), ar = new Map((after.remarks || []).map((x) => [x.id, x]));
    const rAdded = [...ar.keys()].filter((id) => !br.has(id)).length, rGone = [...br.keys()].filter((id) => !ar.has(id)).length;
    const rChanged = [...ar.values()].filter((x) => br.has(x.id) && !same(follow(br.get(x.id)), x)).length;
    if (rAdded) out.push(`added ${nNotes2(rAdded)}`);
    if (rGone) out.push(`took off ${nNotes2(rGone)}`);
    if (rChanged) out.push(`changed ${nNotes2(rChanged)}`);
    for (const [k, w] of [["pace", "the pace"], ["end", "the end date"], ["phases", "catch-up weeks"], ["reviews", "the review days"], ["events", "the events"], ["every", "the weekly lines"],
      ["deckUrl", "where to get the deck"]]) {
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
    // 3.8.0: the plan's tags, by id, as the dates are (Anki's browser may have tagged meanwhile)
    const bt = new Map((mineBase.tags || []).map((t) => [t.id, t]));
    const mt = new Map((mine.tags || []).map((t) => [t.id, t]));
    let tags = out.tags || [];
    for (const [tid] of bt) if (!mt.has(tid)) tags = tags.filter((t) => t.id !== tid);
    for (const [tid, t] of mt) {
      if (bt.has(tid) && same(bt.get(tid), t)) continue;
      tags = tags.filter((x) => x.id !== tid).concat([structuredClone(t)]);
    }
    if (tags.length) { out.tags = tags; out.tagroot = out.tagroot || mine.tagroot; } else delete out.tags;
    // 3.8.1: notes for followers, by id, the same way (Anki's Browse may have written one meanwhile)
    const br = new Map((mineBase.remarks || []).map((x) => [x.id, x]));
    const mr = new Map((mine.remarks || []).map((x) => [x.id, x]));
    let rms = out.remarks || [];
    for (const [rid] of br) if (!mr.has(rid)) rms = rms.filter((x) => x.id !== rid);
    for (const [rid, x] of mr) {
      if (br.has(rid) && same(br.get(rid), x)) continue;
      rms = rms.filter((y) => y.id !== rid && !Remarks.same(x, y)).concat([structuredClone(x)]);
    }
    if (rms.length) out.remarks = rms; else delete out.remarks;
    for (const k of ["pace", "end", "phases", "reviews", "events", "every", "deckUrl"]) {
      if (JSON.stringify(mine[k] ?? null) !== JSON.stringify(mineBase[k] ?? null)) { if (mine[k] === undefined) delete out[k]; else out[k] = structuredClone(mine[k]); }
    }
    // a review day of a date one of us took off goes with it
    const ids = new Set(out.units.map((u) => u.id));
    if (out.reviews) { out.reviews = out.reviews.filter((r) => ids.has(r.from) && ids.has(r.to)); if (!out.reviews.length) delete out.reviews; }
    return out;
  }

  /** The server's ceilings (worker/src/plans.ts planDoc), checked before a save: what's over, by name. */
  function overLimit() {
    if (doc.units.length > UNITS_MAX) return `A plan holds up to ${UNITS_MAX} dates; this one has ${doc.units.length}. Take some off.`;
    for (const u of doc.units) {
      const at = `${pretty(u.opens)}, ${u.name}`;
      if ((u.search || []).length > SEARCH_MAX) return `${at}: a date holds up to ${SEARCH_MAX} searches and cuts.`;
      if ((u.tags || []).length > SOURCES_MAX || (u.decks || []).length > SOURCES_MAX) return `${at}: a date holds up to ${SOURCES_MAX} tags and ${SOURCES_MAX} subdecks.`;
      if (["nids", "cids", "notes"].some((k) => (u[k] || []).length > 5000)) return `${at}: a date takes up to 5,000 IDs of each kind.`;
      if (u.due && u.due < u.opens) return `${at} is due before it opens.`;
    }
    if (events().length > EVENTS_MAX) return `A plan holds up to ${EVENTS_MAX} events.`;
    if ((doc.reviews || []).length > REVIEWS_MAX) return `A plan holds up to ${REVIEWS_MAX} review days.`;
    if (ptags().length > 100) return "A plan holds up to 100 tags.";
    const picks = doc.units.reduce((a, u) => a + (u.cards || []).length + idsLen(u), 0) + ptags().reduce((a, t) => a + (t.notes || []).length + (t.cards || []).length, 0);
    if (picks > 50000) return `A plan holds up to 50,000 picked cards and IDs in all; this one has ${picks.toLocaleString()}.`;
    return null;
  }
  /** what each refusal of a save means (PUT /plans/{id}), in a few words */
  const SAVE_ERRORS = {
    plans_full: "Your plans hold as much as one account can. Make this one smaller, or delete a plan.",
    bad_plan: "Something in the plan isn't valid. Undo your last change, or reload the page.",
    bad_name: "A date or an event has no name. Name it, then save.",
    bad_line: "The plan's one line is too long.",
    bad_post: "The line to followers is too long: 200 characters at most.",
    bad_squad: "You're not in that squad any more. Pick another in Settings.",
    bad_audience: "Pick who can follow it in Settings.",
    not_owner: "Only the plan's owner changes who can follow it.",
    not_author: "You're not one of this plan's authors any more.",
    no_plan: "This plan was deleted.",
    too_big: "The plan is too big to save. Take some IDs or dates off.",
    slow_down: "That's a lot of saves today. Try again tomorrow.",
  };
  async function save() {
    saveBtn.disabled = true;
    status.className = "status"; status.textContent = "Saving…";
    try {
      syncCuts(); cleanup(); byOpens();
      // the server refuses a date or an event with no name: a date is named for what's on it again
      for (const u of doc.units) if (!String(u.name || "").trim()) { auto.add(u.id); u.name = autoName(u); }
      for (const x of events()) if (!String(x.name || "").trim()) x.name = "Event";
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
      // to an end date: the pace it was filled at, kept once everything is on a day (5,000 at most, as the server takes)
      if (pace.mode === "end" && (endDaily() || pace.daily)) p.daily = Math.max(1, Math.min(5000, endDaily() || pace.daily));
      if (cover.size) p.cover = coverItems().slice(0, 500);
      doc.pace = p;
      if (doc.phases && doc.phases.taper && !doc.end) doc.phases.taper = 0;
      if (doc.phases && !doc.phases.taper && !doc.phases.catchup) delete doc.phases;
      const summary = describe(base, doc);
      // 3.6.5: `idr` is the server's (from the author's Anki) and kept there; sending it back only costs size
      // 3.8.1: a date's `pl` (what its picks are, from the author's Anki) goes back as it came, while its picks are as they were
      const lean = ({ every, ...d }, ref = base.units || []) => {
        const was = new Map(ref.map((x) => [x.id, picksSig(x)]));
        return { ...d, units: (d.units || []).map(({ idr: _idr, pn: _pn, pl, todo, ...u }) => {
          const t = Todo.clean(todo);  // Due: a line with no words yet isn't sent
          const v = pl && was.get(u.id) === picksSig(u) ? { ...u, pl } : u;
          return t.length ? { ...v, todo: t } : v;
        }), ...(Every.clean(every).length ? { every: Every.clean(every) } : {}) };
      };
      const body = { version: plan.version, name: meta.name.trim() || plan.name, line: meta.line, doc: lean(doc), summary };
      if (tell.value.trim()) body.post = tell.value.trim();  // 3.7.3
      if (owner && meta.squad !== (plan.squad || "")) body.squad = meta.squad || null;
      if (owner && meta.audience !== plan.audience) body.audience = meta.audience;
      const over = overLimit() || (JSON.stringify(body.doc).length > 1536 * 1024 ? SAVE_ERRORS.too_big : null);
      if (over) { status.className = "status bad"; status.textContent = over; return; }
      let merged = false;
      try {
        plan = await api("PUT", `/plans/${id}`, body);
      } catch (err) {
        if (err.status !== 409) throw err;
        // someone else saved first: theirs, with mine on top
        const theirs = await api("GET", `/plans/${id}`);
        body.version = theirs.version;
        body.doc = lean(merge(doc, base, theirs.doc), theirs.doc.units || []);
        plan = await api("PUT", `/plans/${id}`, body);
        merged = true;
      }
      reload(plan.doc);  // the pace, what to cover and the start as saved (a merge may keep another's); Undo starts over
      history = null; progressData = null; posts = null;
      const postFailed = plan.posted && plan.posted.error;
      if (!postFailed) tell.value = "";
      status.textContent = postFailed ? "Saved. Five posts a day per plan: your line didn't go."
        : merged ? "Saved, with the other changes kept" : "Saved";
      flash = true; draw();
      setTimeout(() => { flash = false; if (!dirty) document.querySelector(".savebar")?.classList.add("clean"); }, merged ? 5000 : 2200);
    } catch (err) {
      status.className = "status bad";
      const code = err.body?.error;
      status.textContent = code === "bad_plan" ? overLimit() || SAVE_ERRORS.bad_plan
        : SAVE_ERRORS[code] || (err.status === 409 ? "It changed again while saving. Save once more."
          : !err.status ? "That didn't save: check your connection, then try again." : "That didn't save. Try again.");
    } finally { saveBtn.disabled = false; }
  }

  settled();  // Undo starts from the plan as it loaded
  draw();
}
