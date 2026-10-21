"""The AI hooks (round five, docs/planner.md): the jobs an AI can do for a
plan's author, what each would be sent, and its answer checked into ops
(ops.py) before anything changes. Plain rules go first in every job
(reading.py, build.py's Suggest); an AI is asked only for what they leave.

A request carries the plan's names, days and counts, its own date and
event ids, the deck's tag and subdeck paths with their card counts, and
the author's own words. Never a card's text, a person's name or email, or
a note's or card's id: request() refuses a key it doesn't know, and says
so for one shaped like card text.

An answer is ops ({"ops": [...], "say": "..."}), plan lines (plan, tag), a
calendar's sessions, or lines worth a look (check). answer_ops keeps only
ops the registry knows, with only their own fields, each checked and tried
on the plan as the ones before it leave it; one that won't go on is said,
never applied.

Runners: Off; the stand-in (labs: claude.py's, by rules, and says so);
your own AI (a prompt to copy, its answer pasted back: OwnAI.read); Claude,
later, through the Worker (not connected yet: nothing new on the server).

Pure: no Anki, no network."""

import copy
import datetime
import json
import re

from .. import plans as P
from . import build as B
from . import claude as C
from . import edits as E
from . import ops as O
from . import prompts as PR
from . import reading as R

V = 1  # a request's shape


class NotSent(ValueError):
    """What a request never carries: card text, an id, anyone."""


# ---- the ops, as an AI is told them (vocabulary) ----

DATE = 'the date: its id, its day (YYYY-MM-DD), its name, or "YYYY-MM-DD name"'
EVENT = "the quiz or exam: its id, its day, its name, or both"
DAY = "YYYY-MM-DD"
TAGS = "[full tag paths, copied exactly]"
DECKS = "[full subdeck paths, copied exactly]"
WEEK = "[seven 1s and 0s, Monday first: the study days]"

# op -> (what it does, {field: what goes in it}, an example); `made`: worked out by Your plans, never written by an AI
VOCAB = {
    "add_cards": ("Puts every card under tags or subdecks on a date.",
                  {"date": DATE, "tags": TAGS, "decks": DECKS + " (optional)"},
                  {"date": "2026-10-22 Shock", "tags": ["Pharm::Pressors"]}),
    "take_cards": ("Takes one of a date's sources off it.",
                   {"date": DATE, "key": '["tag", path], ["deck", path], ["cut", tag path], ["search", the search], '
                                         '["questions", [question tags]] or ["picks"]'},
                   {"date": "2026-10-22 Shock", "key": ["tag", "Cardio::Shock"]}),
    "add_search": ("Puts what an Anki search finds on a date (never one about one person's own Anki: is:due, rated:, flag:).",
                   {"date": DATE, "q": "the search, 500 characters at most", "n": "its cards, if known (optional)"},
                   {"date": "2026-10-22 Shock", "q": "tag:Cardio::Shock -tag:Cardio::Shock::Extra"}),
    "add_ids": ("Puts notes or cards on a date by their numeric IDs (they work in my own Anki only).",
                {"date": DATE, "kind": '"nids" or "cids"', "ids": "[numbers]"},
                {"date": "2026-10-22 Shock", "kind": "nids", "ids": [1712345678901]}),
    "add_picks": ("Puts notes (every card of each) or single cards on a date by note ID, for everyone following.",
                  {"date": DATE, "notes": "[note IDs, as an export's #guid column has them]",
                   "cards": "[[note ID, the card's number, 0 the first]]"},
                  {"date": "2026-10-22 Shock", "notes": ["Ab3$kL9qZ1"]}),
    "rename": ("Names a date.", {"date": DATE, "name": "60 characters at most"},
               {"date": "2026-10-22", "name": "Shock and sepsis"}),
    "move": ("Moves one date to another day.", {"date": DATE, "to": DAY},
             {"date": "2026-10-22 Shock", "to": "2026-10-23"}),
    "move_from": ("Moves a date and every date after it some days later (or earlier); quizzes and exams stay.",
                  {"date": DATE, "days": "1 to 120 later, or -1 to -120 earlier"},
                  {"date": "2026-10-22 Shock", "days": 1}),
    "set_due": ("Gives a date a finish-by day, or none.", {"date": DATE, "due": DAY + ", or null"},
                {"date": "2026-10-22 Shock", "due": "2026-10-25"}),
    "set_for": ("Says which quiz or exam a date preps for, or none.", {"date": DATE, "event": EVENT + ", or null"},
                {"date": "2026-10-22 Shock", "event": "Cardio quiz"}),
    "set_even": ("Spreads a date's cards evenly to its finish-by day, or not.", {"date": DATE, "on": "true or false"},
                 {"date": "2026-10-22 Shock", "on": True}),
    "add_date": ("A new date on a day: a name, cards, or both.",
                 {"day": DAY, "name": "60 characters at most (optional with cards)", "tags": TAGS + " (optional)",
                  "decks": DECKS + " (optional)"},
                 {"day": "2026-10-27", "name": "Valve disease", "tags": ["Cardio::Valves"]}),
    "delete_date": ("Takes a date off the plan.", {"date": DATE}, {"date": "2026-10-22 Shock"}),
    "add_event": ("A quiz or exam on a day (no cards; dates prep for it).", {"day": DAY, "name": "60 characters at most"},
                  {"day": "2026-10-30", "name": "Cardio quiz"}),
    "rename_event": ("Names a quiz or exam.", {"event": EVENT, "name": "60 characters at most"},
                     {"event": "Cardio quiz", "name": "Cardio quiz 1"}),
    "move_event": ("Moves a quiz or exam to another day.", {"event": EVENT, "to": DAY},
                   {"event": "Cardio quiz", "to": "2026-10-31"}),
    "take_event": ("Takes a quiz or exam off; the dates for it stay.", {"event": EVENT}, {"event": "Cardio quiz"}),
    "set_todo": ("A date's to-dos, ticked by hand (8 at most): the whole list.",
                 {"date": DATE, "lines": '[{"k": "watch", "read" or "do", "t": "140 characters at most", '
                                         '"url": "https://… (optional)"}]'},
                 {"date": "2026-10-22 Shock", "lines": [{"k": "watch", "t": "Lecture 14"}]}),
    "set_every": ("The plan's lines every week (6 at most): the whole list.",
                  {"lines": '[{"r": its weekdays as digits, Monday 0 ("01234" is weekdays), "k": "watch", "read" or "do", '
                            '"t": 140 characters at most}]'},
                  {"lines": [{"r": "01234", "k": "do", "t": "20 practice questions"}]}),
    "set_review": ("A review day: on its day, the dates from one to another come up again.",
                   {"day": DAY, "from": DATE, "to": DATE},
                   {"day": "2026-10-29", "from": "2026-10-22 Shock", "to": "2026-10-26 Heart failure"}),
    "take_review": ("Takes a review day off.", {"day": DAY}, {"day": "2026-10-29"}),
    "set_cut": ("Keeps a tag on a date to what one of the plan's own tags holds, or all of it again.",
                {"date": DATE, "tag": "the deck tag on the date", "ptag": "the plan tag's id, or null"},
                {"date": "2026-10-22 Shock", "tag": "Cardio::Shock", "ptag": "t1"}),
    "set_extras": ("A tag on a date with its extras (Extra, Bonus tags under it), or without them.",
                   {"date": DATE, "path": "the tag on the date", "without": "true or false",
                    "kids": "[the extra tags under it]"},
                   {"date": "2026-10-22 Shock", "path": "Cardio::Shock", "without": True, "kids": ["Cardio::Shock::Extra"]}),
    "set_tag_remark": ("A note for followers on a tag, shown when its cards come up; empty takes it off.",
                       {"tag": "a full tag path", "text": "one line, 280 characters at most, in your own words; never card text"},
                       {"tag": "Cardio::Shock", "text": "Lecture 9's slides cover this better than the book."}),
    "take_remark": ("Takes a note for followers off.", {"id": "the note's id"}, {"id": "r7Kd2pQa"}),
    "split_even": ("Spreads one of a date's tags or subdecks evenly over study days, a date of its own.",
                   {"date": DATE, "source": '["tags" or "decks", path]',
                    "days": "[the study days, YYYY-MM-DD, 2 or more, the date's own first]"},
                   {"date": "2026-10-22 Shock", "source": ["tags", "Cardio::Shock"],
                    "days": ["2026-10-22", "2026-10-23", "2026-10-26"]}),
    "split_tags": ("Your plans' Split by its tags (its parts worked out there, from the deck).",
                   {"date": DATE, "field": '"tags" or "decks"', "path": "the tag on the date",
                    "items": "[the parts, as Your plans works them out]", "cap": "cards a day", "days": WEEK},
                   {"date": "2026-10-22 Shock", "field": "tags", "path": "Cardio", "items": [], "cap": 40,
                    "days": [1, 1, 1, 1, 1, 0, 0]}),
    "place": ("Puts tags or subdecks on days, each onto that day's date (a new one when the day has none).",
              {"items": '[[YYYY-MM-DD, "tags" or "decks", path]]', "n": "their cards, if known (optional)"},
              {"items": [["2026-10-27", "tags", "Cardio::Valves"]]}),
    "lay_out": ("Lays out what the plan covers and no date has yet, at its pace, on its study days after its last date.",
                {"pace": '{"mode": "end", "daily" or "placed", "days": ' + WEEK + ', "daily": cards a day}',
                 "cover": '["tag:PATH" or "deck:PATH": what the plan covers]', "start": DAY + " (optional)",
                 "end": DAY + " (optional)", "aim": EVENT + " the new dates prep for (optional)",
                 "week_ahead": "true: just next week (optional)"},
                {"pace": {"mode": "daily", "days": [1, 1, 1, 1, 1, 0, 0], "daily": 40}, "cover": ["tag:Cardio"]}),
    "set_pace": ("The plan's pace: up to a number of new cards a day, fit to the end, or each date set by hand.",
                 {"mode": '"daily", "end" or "placed"', "days": WEEK, "daily": "cards a day (optional)",
                  "cover": '["tag:PATH" or "deck:PATH"] (optional)'},
                 {"mode": "daily", "days": [1, 1, 1, 1, 1, 0, 0], "daily": 40}),
    "set_end": ("The plan's end date, or none.", {"end": DAY + ", or null"}, {"end": "2026-12-18"}),
    "set_phases": ("A catch-up week every so many weeks, and no new cards the last days before the end.",
                   {"catchup": "every this many weeks, 2 to 8, or null", "taper": "days, 1 to 60, or null"},
                   {"catchup": 4, "taper": 7}),
    "shift_all": ("Moves every date, quiz and review day some days later (or earlier).",
                  {"days": "days later, or earlier when negative"}, {"days": 7}),
    "breather": ("Every date still to come a study day later; quizzes stay (Give the class a day).",
                 {"today": DAY, "days": WEEK}, {"today": "2026-10-20", "days": [1, 1, 1, 1, 1, 0, 0]}),
    "rename_plan_tag": ("Renames one of the plan's own tags (SLG 12).", {"tag": "its id or name", "name": "40 characters at most"},
                        {"tag": "SLG 12", "name": "SLG 12a"}),
    "delete_plan_tag": ("Takes one of the plan's own tags off.", {"tag": "its id or name"}, {"tag": "SLG 12"}),
    "set_deck_url": ("Where to get the plan's deck: a link, or none.", {"url": "https://…, or null"},
                     {"url": "https://example.com/deck"}),
    "text": ("Plan lines in the plan's text format (https://duecrew.com/plan-text): added to the plan, or the whole plan in its place.",
             {"mode": '"add" or "replace"', "text": "the lines", "take_tags": "replace: tags the text leaves out come off the dates too"},
             {"mode": "add", "text": "2026-10-27 | Valve disease | tag:Cardio::Valves | for Cardio quiz"}),
}
MADE = {"split_tags"}  # worked out by Your plans from the deck, never an AI's to write


def vocabulary(for_ai=False):
    """[{op, does, fields, example}]: every change a plan takes (ops.REG), as
    docs, prompts and the AI app are told it. for_ai: the ones an AI writes."""
    return [{"op": name, "does": does, "fields": dict(fields), "example": dict({"op": name}, **ex)}
            for name, (does, fields, ex) in VOCAB.items() if name in O.REG and not (for_ai and name in MADE)]


def clean_op(o):
    """(op with only its own fields, "") or (None, why): an op the registry
    doesn't know, or that isn't an object, is never tried."""
    if not isinstance(o, dict):
        return None, "A change is an object with its op."
    name = o.get("op")
    if not isinstance(name, str) or name not in O.REG:
        return None, f"There's no change called {name}." if name else "That change has no op."
    fields = VOCAB.get(name, ("", {}, {}))[1]
    return {k: copy.deepcopy(v) for k, v in o.items() if k == "op" or k in fields}, ""


def _same(a, b):
    return json.dumps(E.lean(a), sort_keys=True) == json.dumps(E.lean(b), sort_keys=True)


def try_ops(ops_list, doc, ctx, most=O.OPS_MAX):
    """Each op checked and tried in order, on the doc the ones before it
    leave: ([(op as checked, entries with who)], [(op, words)], doc after).
    The doc itself never changes."""
    kept, refused, cur = [], [], doc
    for i, raw in enumerate(ops_list if isinstance(ops_list, list) else []):
        if i >= most:
            refused.append((raw, f"More than {most:,} changes at once: this one wasn't tried."))
            continue
        o, why = clean_op(raw)
        if o is None:
            refused.append((raw, why))
            continue
        try:
            c = O.check(cur, o)
            after, entries, _touched = O.apply(cur, c, ctx)
        except E.Refused as e:
            refused.append((o, str(e)))
            continue
        except Exception:  # an op whose fields aren't what its kind takes: said, never applied
            refused.append((o, "That change doesn't fit this plan."))
            continue
        if _same(after, cur):
            refused.append((o, "Nothing to change: the plan has that already."))
            continue
        for x in entries:
            x["who"] = O.who(x, ctx.today)
        kept.append((c, entries))
        cur = after
    return kept, refused, cur


# ---- the jobs ----

OPS_SHAPE = {"type": "object", "required": ["ops"], "properties": {
    "ops": {"type": "array", "items": {"type": "object", "required": ["op"]}, "maxItems": O.OPS_MAX},
    "say": {"type": "string", "description": "one line on what changed"}}}
TEXT_SHAPE = {"type": "object", "required": ["text"], "properties": {
    "text": {"type": "string", "description": "plan lines, in the plan's text format"}, "say": {"type": "string"}}}
NOTES_SHAPE = {"type": "object", "required": ["notes"], "properties": {
    "notes": {"type": "array", "items": {"type": "string"}, "maxItems": 40}}}
PICK_SHAPE = {"type": "object", "required": ["tags"], "properties": {
    "tags": {"type": "array", "items": {"type": "string", "description": "a path from the list, as given"}, "maxItems": 6},
    "say": {"type": "string"}}}
SCOPE_SHAPE = {"type": "object", "required": ["dates"], "properties": {
    "dates": {"type": "array", "items": {"type": "string", "description": "a date's id from the list"}},
    "say": {"type": "string"}}}


class Job:
    """One thing an AI does: its name, title, what it's told (does), the
    input it may be sent, how it answers (ops, text, sessions, notes) and
    the answer's shape."""

    def __init__(self, name, title, does, inputs, answer, shape):
        self.name, self.title, self.does = name, title, does
        self.inputs, self.answer, self.shape = tuple(inputs), answer, shape


JOBS = {j.name: j for j in (
    Job("calendar", "Read a block's calendar",
        "Each session in this calendar: its date, what kind it is, its title, its objectives and the resources it "
        "lists. Leave out breaks and holidays.", ("today", "text", "day_first"), "sessions", C.CALENDAR_SHAPE),
    Job("pick", "Cards for a date",
        "Which of these tags or subdecks fit this date, by its name and words. Answer with paths from the list only.",
        ("date", "tags"), "ops", PICK_SHAPE),
    Job("scope", "What an exam covers",
        "Which of these dates the line says the exam covers.", ("event", "said", "dates"), "ops", SCOPE_SHAPE),
    Job("words", "A change in my words",
        "The changes to this plan these words ask for, as ops.", ("today", "said", "plan"), "ops", OPS_SHAPE),
    Job("tag", "Tag by objective",
        "A plan tag line for each objective, from the deck's tags.", ("said", "plan", "tags"), "text", TEXT_SHAPE),
    Job("check", "Check the plan",
        "What in this plan is worth a second look, one line each. Change nothing.", ("today", "plan", "tags"),
        "notes", NOTES_SHAPE),
    Job("plan", "Plan the dates",
        "Dates for this plan, in the plan's text format.", ("today", "said", "plan", "tags", "whole"), "text",
        TEXT_SHAPE),
)}

# a request's keys, anywhere in it; and the ones that would be card text, an id or a person
KEYS = {"today", "text", "day_first", "date", "dates", "tags", "event", "events", "said", "plan", "whole",
        "id", "day", "name", "n", "sources", "due", "even", "for", "week", "title", "kind", "objectives", "listed",
        "slides", "label", "how", "path", "deck", "start", "end", "pace", "mode", "daily", "days", "phases",
        "catchup", "taper", "reviews", "from", "to", "size", "root", "more", "todo", "words", "cover"}
NEVER = {"fields", "flds", "sfld", "field", "question", "questions", "answer", "answers", "front", "back", "html",
         "card", "cards", "card_text", "note", "notes", "note_text", "extra", "guid", "guids", "nid", "nids", "cid",
         "cids", "ids", "picks", "email", "emails", "uid", "uids", "user", "users", "owner", "ownername", "editors",
         "followers", "people", "token"}
STR_MAX = {"text": 12000, "said": 4000}
LIST_MAX = 600
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def _clean(v, key="", depth=0):
    if depth > 6:
        raise NotSent("That's nested deeper than a request goes.")
    if isinstance(v, dict):
        out = {}
        for k, x in v.items():
            k = str(k)
            if k.lower() in NEVER:
                raise NotSent(f"A request never carries {k}: card text, ids and people stay on this computer.")
            if k not in KEYS:
                raise NotSent(f"A request doesn't carry {k}.")
            if x is not None:
                out[k] = _clean(x, k, depth + 1)
        return out
    if isinstance(v, (list, tuple)):
        return [_clean(x, key, depth + 1) for x in list(v)[:LIST_MAX]]
    if v is None or isinstance(v, (bool, int)):
        return v
    if isinstance(v, float):
        return v if v == v and abs(v) != float("inf") else None
    if isinstance(v, str):
        return _EMAIL.sub("[email]", v)[:STR_MAX.get(key, 600)]
    raise NotSent(f"A request carries words and numbers, not {type(v).__name__}.")


def request(job, **inputs):
    """What would be sent for one job: {job, v, input}. Only the job's own
    inputs, only keys it knows; an email in the words becomes [email].
    NotSent for anything else (card text above all)."""
    j = JOBS.get(job)
    if j is None:
        raise NotSent(f"There's no job called {job}.")
    bad = sorted(k for k in inputs if k not in j.inputs)
    if bad:
        raise NotSent(f"{j.title} isn't sent {', '.join(bad)}.")
    return {"job": job, "v": V, "input": _clean({k: v for k, v in inputs.items() if v is not None})}


# ---- what a request says of the plan: names, days and counts ----

def _day(v):
    if isinstance(v, datetime.date):
        return v
    try:
        return datetime.date.fromisoformat(str(v)[:10])
    except ValueError:
        return datetime.date.today()


def sources(u, doc=None):
    """What's on a date, as a request says it: tag:, deck: and search: as
    written, a cut by its plan tag's name, picked notes and IDs by count."""
    tags = {t.get("id"): t for t in P.plan_tags(doc or {})}
    out = [f"tag:{t}" for t in u.get("tags") or []]
    out += [f"tag:{c.get('tag')} in {(tags.get(c.get('in')) or {}).get('name') or '?'}" for c in u.get("cut") or []
            if isinstance(c, dict)]
    out += [f"deck:{d}" for d in u.get("decks") or []]
    cut_q = {c.get("q") for c in u.get("cut") or [] if isinstance(c, dict)}
    out += [f"search:{q}" for q in u.get("search") or [] if q not in cut_q]
    for n, one, many in ((len(u.get("notes") or []), "picked note", "picked notes"),
                         (len(u.get("cards") or []), "single card", "single cards"),
                         (len(u.get("nids") or []) + len(u.get("cids") or []), "card by ID", "cards by ID")):
        if n:
            out.append(f"{n:,} {one if n == 1 else many}")
    return out


def _events(doc):
    return [e for e in (doc or {}).get("events") or [] if isinstance(e, dict) and e.get("id")]


def date_cards(u, tree=None, placed=None):
    """A date's cards: as this deck counts it (the builder's unitTotal), else the author's count."""
    if tree is not None:
        return B.unit_total(tree, u, placed if placed is not None else B.Placed())
    n = u.get("n")
    return n if isinstance(n, int) and not isinstance(n, bool) else None


def plan_summary(doc, tree=None, name=""):
    """The plan as a request says it: its name, deck, pace and end, each
    date (its id, day, name, what's on it, cards, finish-by day, the quiz it
    preps for), its quizzes and exams, review days and own tags."""
    doc = doc or {}
    placed = B.placed_keys(doc, tree) if tree is not None else None
    evs = {e["id"]: e for e in _events(doc)}
    dates = []
    for u in sorted(P.units(doc), key=lambda u: str(u.get("opens") or "")):
        x = {"id": u["id"], "day": u.get("opens"), "name": u.get("name") or "", "sources": sources(u, doc),
             "n": date_cards(u, tree, placed), "due": u.get("due") or None, "even": True if u.get("even") else None,
             "for": (evs.get(u.get("for")) or {}).get("name"),
             "todo": [str(t.get("t") or "") for t in u.get("todo") or [] if isinstance(t, dict)] or None}
        dates.append({k: v for k, v in x.items() if v is not None})
    pace = doc.get("pace") if isinstance(doc.get("pace"), dict) else {}
    out = {"name": name or "", "deck": doc.get("deck") or "", "end": doc.get("end") or None,
           "pace": {k: pace[k] for k in ("mode", "days", "daily") if k in pace} or None,
           "phases": doc.get("phases") or None, "dates": dates,
           "events": [{"id": e["id"], "day": e.get("day"), "name": e.get("name") or ""} for e in _events(doc)],
           "reviews": [{"day": r.get("day"), "from": r.get("from"), "to": r.get("to")}
                       for r in doc.get("reviews") or [] if isinstance(r, dict)] or None,
           "tags": [{"name": t.get("name") or "", "size": PR.ptag_size(doc, tree, t) if tree is not None else None}
                    for t in P.plan_tags(doc)] or None}
    return {k: v for k, v in out.items() if v is not None}


def deck_rows(tree):
    """[(key, cards)]: the deck's tags then its subdecks, in its order, Due Crew's own tags left out."""
    if tree is None:
        return []
    return [(k, tree.n(k)) for k in sorted(tree.order, key=tree.order.get)
            if not B.path_of(k).lower().startswith("duecrew::")]


def candidates(tree, name, words=(), skip=lambda key: False, most=40):
    """The tags and subdecks a date's words could mean: Suggest's first
    (every word of the name in the path), then any whose last part has one
    of its words. [{path: "tag:…", n}], names and counts only."""
    rows = deck_rows(tree)
    tag_rows = [(B.path_of(k), n) for k, n in rows if B.kind_of(k) == "tag"]
    out = [f"tag:{p}" for p, _n in B.suggest(name, tag_rows, skip=lambda p: skip(f"tag:{p}"), most=12)]
    want = set(B.words(" ".join([str(name or "")] + [str(w) for w in words])))
    loose = []
    for k, n in rows:
        if not n or k in out or skip(k):
            continue
        leaf = B.words(B.path_of(k).split("::")[-1])
        hit = sum(1 for w in want if any(B.same_word(w, x) for x in leaf))
        if hit:
            loose.append((-hit, -B.path_of(k).count("::"), n, k))
    out += [k for *_r, k in sorted(loose)]
    counts = dict(rows)
    return [{"path": k, "n": counts.get(k, 0)} for k in out[:most]]


def pick_input(doc, tree, ref):
    """pick's input: the date (its id, day, name, to-dos, what's on it) and the tags it could take."""
    uid = O.find_date(doc, ref)
    u = next(x for x in P.units(doc) if x["id"] == uid)
    todo = [str(t.get("t") or "") for t in u.get("todo") or [] if isinstance(t, dict)]
    placed = B.placed_keys(doc, tree) if tree is not None else B.Placed()
    cands = candidates(tree, u.get("name") or "", todo, skip=lambda k: B.is_placed(k, placed)) if tree is not None else []
    return {"date": {"id": uid, "day": u.get("opens"), "name": u.get("name") or "", "todo": todo or None,
                     "sources": sources(u, doc)}, "tags": cands}


def plain_pick(doc, tree, ref):
    """Plain rules for a date's cards (the builder's Suggest): [add_cards op],
    or [] when its name names none of the deck's tags (the AI's, then)."""
    if tree is None:
        return []
    uid = O.find_date(doc, ref)
    u = next(x for x in P.units(doc) if x["id"] == uid)
    placed = B.placed_keys(doc, tree)
    rows = [(B.path_of(k), n) for k, n in deck_rows(tree) if B.kind_of(k) == "tag"]
    got = B.suggest(u.get("name") or "", rows, skip=lambda p: B.is_placed(f"tag:{p}", placed))
    return [{"op": "add_cards", "date": uid, "tags": [p for p, _n in got]}] if got else []


def _scope_dates(doc, eid):
    """The dates up to an event, as reading.py's sessions (weeks numbered from the first)."""
    e = next(x for x in _events(doc) if x["id"] == eid)
    us = [u for u in sorted(P.units(doc), key=lambda u: str(u.get("opens") or ""))
          if str(u.get("opens") or "") <= str(e.get("day") or "")]
    sessions = R.number_weeks([R.session(u["opens"], u.get("name") or "?") for u in us])
    return e, us, sessions


def plain_scope(doc, ref, said, today):
    """Plain rules for what an exam covers ("weeks 1-3", "Oct 26 to Nov 13"):
    ([set_for op], [the words they couldn't place]: the AI's, then)."""
    eid = O.find_event(doc, ref)
    _e, us, sessions = _scope_dates(doc, eid)
    got, left = R.scope(said, sessions, _day(today))
    return [{"op": "set_for", "date": us[i]["id"], "event": eid} for i in got], left


def scope_input(doc, ref, said):
    """scope's input: the event, the words, and the dates up to it (id, day, name, week, what's on them)."""
    eid = O.find_event(doc, ref)
    e, us, sessions = _scope_dates(doc, eid)
    return {"event": {"id": eid, "day": e.get("day"), "name": e.get("name") or ""},
            "said": [str(s) for s in (said if isinstance(said, (list, tuple)) else [said]) if str(s or "").strip()],
            "dates": [{"id": u["id"], "day": u.get("opens"), "name": u.get("name") or "", "week": s.get("week"),
                       "tags": [x for x in sources(u, doc) if x.startswith(("tag:", "deck:"))][:12]}
                      for u, s in zip(us, sessions)][:200]}


def plain_calendar(text, today, day_first=False):
    """Plain rules for a calendar (reading.read_calendar): [session], [] when they find none (the AI's, then)."""
    return R.read_calendar(text, _day(today), day_first)


def own_tags(doc, tree, name):
    """tag's plan: its name, its tags' root, and its own tags (name, what's on each, how big)."""
    return {"name": name or "", "root": doc.get("tagroot") or P.tag_root(name or "plan"),
            "tags": [{"name": t.get("name") or "", "sources": sources(t, doc),
                      "size": PR.ptag_size(doc, tree, t) if tree is not None else None} for t in P.plan_tags(doc)]}


def request_for(job, doc=None, tree=None, name="", today="", said="", ref=None, cover=None, whole=False,
                text="", day_first=False):
    """request(), its input gathered from the plan here (plan_summary, the
    deck's paths and counts, the author's words). ref: the date (pick) or
    the quiz (scope) it's about."""
    doc = doc or {}
    lines = (lambda: PR.tag_lines(tree, cover)[0] if tree is not None else [])  # noqa: E731
    if job == "calendar":
        inp = {"today": str(today), "text": str(text or ""), "day_first": bool(day_first)}
    elif job == "pick":
        inp = pick_input(doc, tree, ref)
    elif job == "scope":
        inp = scope_input(doc, ref, said)
    elif job == "words":
        inp = {"today": str(today), "said": str(said or ""), "plan": plan_summary(doc, tree, name)}
    elif job == "tag":
        inp = {"said": str(said or ""), "plan": own_tags(doc, tree, name), "tags": PR.tag_list(tree) if tree is not None else []}
    elif job == "check":
        inp = {"today": str(today), "plan": plan_summary(doc, tree, name), "tags": lines()}
    elif job == "plan":
        inp = {"today": str(today), "said": str(said or ""), "plan": plan_summary(doc, tree, name), "tags": lines(),
               "whole": bool(whole)}
    else:
        raise NotSent(f"There's no job called {job}.")
    return request(job, **inp)


# ---- answers ----

def say_of(answer):
    """The answer's own line on what it did, one line, or ''."""
    s = answer.get("say") if isinstance(answer, dict) else ""
    return " ".join(str(s or "").split())[:O.WHY_MAX]


def answer_sessions(answer):
    """A calendar answer as reading.py's sessions, by date: a real day, a
    kind it knows (else read from the title), a title; breaks left out."""
    items = answer.get("sessions") if isinstance(answer, dict) else answer
    out = []
    for s in items[:400] if isinstance(items, list) else []:
        if not isinstance(s, dict):
            continue
        try:
            d = datetime.date.fromisoformat(str(s.get("date") or ""))
        except ValueError:
            continue
        title = " ".join(str(s.get("title") or "").split())[:R.TITLE_MAX]
        if not title or R._SKIP.search(title):
            continue
        kind = s.get("kind") if s.get("kind") in R.KINDS else R.kind_of(title)
        x = R.session(d, title, kind)
        for key, field in (("objectives", "label"), ("listed", "how")):
            for item in (s.get(key) or [])[:30] if isinstance(s.get(key), list) else []:
                words = item.get("text") if isinstance(item, dict) else item
                words = " ".join(str(words or "").split())[:300]
                if words:
                    x[key].append({field: "", "text": words})
        out.append(x)
    return R.merge(out)


def _calendar_ops(answer):
    """Sessions as ops on a plan: a quiz or exam its event, any other session a date named for it (no cards yet)."""
    return [{"op": "add_event" if s["kind"] in R.EVENT_KINDS else "add_date", "day": s["date"], "name": s["title"]}
            for s in answer_sessions(answer)]


def _paths(xs):
    return [str(x.get("path") if isinstance(x, dict) else x) for x in xs or []]


def _pick_ops(answer, inp):
    """pick's answer ({"tags": [...]}, or the ops themselves) as add_cards on the date it was asked about;
    a path it wasn't given is refused."""
    date = (inp.get("date") or {}).get("id")
    given = set(_paths(inp.get("tags"))) if inp.get("tags") is not None else None
    if isinstance(answer, dict) and isinstance(answer.get("ops"), list):
        raw = answer["ops"]
    else:
        picked = _paths(answer.get("tags") if isinstance(answer, dict) else answer)
        tags = [p[4:] for p in picked if p.startswith("tag:")] + [p for p in picked if ":" not in p.split("::")[0]]
        decks = [p[5:] for p in picked if p.startswith("deck:")]
        raw = [{"op": "add_cards", "date": date, "tags": tags, "decks": decks}] if date and (tags or decks) else []
    ok, refused = [], []
    for o in raw:
        if isinstance(o, dict) and o.get("op") == "add_cards":
            if date and o.get("date") not in (None, date):
                refused.append((o, "That's not the date it was asked about."))
                continue
            o = dict(o, date=date or o.get("date"))
            if given is not None:
                ts, ds = [str(t) for t in o.get("tags") or []], [str(d) for d in o.get("decks") or []]
                off = [f"tag:{t}" for t in ts if f"tag:{t}" not in given] + [f"deck:{d}" for d in ds if f"deck:{d}" not in given]
                if off:
                    refused.append(({"op": "add_cards", "date": o["date"], "tags": off}, f"Not one of the tags it was given: {', '.join(off)}."))
                    o = dict(o, tags=[t for t in ts if f"tag:{t}" in given], decks=[d for d in ds if f"deck:{d}" in given])
                    if not (o["tags"] or o["decks"]):
                        continue
        elif isinstance(o, dict):
            refused.append((o, "A date's cards are all pick changes."))
            continue
        ok.append(o)
    return ok, refused


def _scope_ops(answer, inp):
    """scope's answer ({"dates": [ids]}, or the ops) as set_for on the event it was asked about."""
    eid = (inp.get("event") or {}).get("id")
    given = {d.get("id") for d in inp.get("dates") or [] if isinstance(d, dict)} if inp.get("dates") is not None else None
    if isinstance(answer, dict) and isinstance(answer.get("ops"), list):
        raw = answer["ops"]
    else:
        ids = answer.get("dates") if isinstance(answer, dict) else answer
        raw = [{"op": "set_for", "date": str(d), "event": eid} for d in ids or [] if isinstance(d, (str, int))]
    ok, refused = [], []
    for o in raw:
        if not isinstance(o, dict) or o.get("op") != "set_for":
            refused.append((o, "What an exam covers is all set_for changes."))
            continue
        if eid and o.get("event") not in (None, eid):
            refused.append((o, "That's not the quiz or exam it was asked about."))
            continue
        if given is not None and o.get("date") not in given:
            refused.append((o, f"Not one of the dates it was given: {o.get('date')}."))
            continue
        ok.append(dict(o, event=eid or o.get("event")))
    return ok, refused


def answer_ops(job, answer, doc, ctx, request=None):
    """(ops, [(op, words)] refused): an answer as the changes it makes, each
    checked and tried in order on a copy (the ones before it applied), only
    ops the registry knows, with only their own fields, OPS_MAX at most.
    answer: the dict an AI returned (or text for plan and tag, or a pasted
    answer); request: what was asked, so a pick or a scope keeps to what it
    was given. check makes none."""
    j = JOBS.get(job)
    if j is None:
        raise ValueError(job)
    inp = (request or {}).get("input") or {}
    if isinstance(answer, str):
        answer = OwnAI.read(answer, job)
    if j.answer == "notes":
        return [], []
    pre = []
    if isinstance(answer, dict) and isinstance(answer.get("ops"), list) and job not in ("pick", "scope"):
        raw = answer["ops"]
    elif isinstance(answer, list) and job not in ("pick", "scope", "calendar"):
        raw = answer
    elif j.answer == "text":
        text = _unfence(str((answer.get("text") if isinstance(answer, dict) else "") or ""))
        if not text.strip():
            return [], [(answer, "No plan lines in that answer.")]
        raw = [{"op": "text", "mode": "replace" if job == "plan" and inp.get("whole") else "add", "text": text}]
    elif job == "calendar":
        raw = _calendar_ops(answer)
    elif job == "pick":
        raw, pre = _pick_ops(answer, inp)
    elif job == "scope":
        raw, pre = _scope_ops(answer, inp)
    else:
        raw = None
    if not raw:
        return [], pre or [(answer, "That answer has no changes in it.")]
    kept, refused, _after = try_ops(raw, doc, ctx)
    return [o for o, _e in kept], pre + refused


def check_notes(answer):
    """check's answer as lines worth a look: {"notes": [...]}, or the # lines
    of a pasted answer (all its lines when none start with #). 40 at most."""
    if isinstance(answer, dict):
        items = answer.get("notes") if isinstance(answer.get("notes"), list) else [answer.get("say") or ""]
    else:
        lines = [x.strip() for x in _unfence(str(answer or "")).splitlines() if x.strip()]
        marked = [x for x in lines if x.startswith("#")]
        items = [x.lstrip("#").strip() for x in marked] if marked else lines
    out = [" ".join(str(x or "").split())[:300] for x in items]
    return [x for x in out if x][:40]


# ---- runners: who does a job ----

class Runner:
    """Who answers a job. available() -> (bool, words); run(request, done):
    done(answer or None, words), on the caller's thread for these (Claude's,
    later, in the background)."""

    name = ""
    key = ""

    def available(self):
        return False, ""

    def run(self, req, done):
        done(None, self.available()[1])


class Off(Runner):
    name = "Off"
    key = "off"

    def available(self):
        return False, "No AI helps with this. Plain rules alone."


class StandIn(Runner):
    """Labs: claude.py's stand-in, by rules, here; every answer says it's the stand-in's."""

    name = C.StandIn.name
    key = "standin"

    def __init__(self):
        self.rules = C.StandIn()

    def available(self):
        return True, self.rules.status()

    def run(self, req, done):
        job, inp = req.get("job"), req.get("input") or {}
        say = "Claude’s stand-in: its rules, not Claude."
        if job == "calendar":
            got = self.rules.calendar(inp.get("text") or "", _day(inp.get("today")), bool(inp.get("day_first")))
            done({"sessions": [{"date": s["date"], "kind": s["kind"], "title": s["title"]} for s in got], "say": say},
                 say if got else "The stand-in found no dates in that.")
        elif job == "pick":
            got = self._pick(inp)
            done({"tags": got, "say": say}, say if got else "The stand-in found nothing that fits.")
        elif job == "scope":
            dates = inp.get("dates") or []
            sessions = [{"date": d.get("day"), "kind": "lecture", "title": d.get("name") or "", "week": d.get("week")}
                        for d in dates]
            tags = {i: [str(t).split(":", 1)[-1] for t in d.get("tags") or []] for i, d in enumerate(dates)}
            idx, left = self.rules.scope(inp.get("said") or [], sessions, tags)
            done({"dates": [dates[i]["id"] for i in idx], "say": say},
                 say + (f" It couldn't place: {'; '.join(left)}." if left else ""))
        else:
            done(None, "The stand-in reads calendars, picks a date's tags and finds what an exam covers; "
                       "for this one, copy the prompt to your own AI.")

    def _pick(self, inp):
        """The stand-in's pick: the given paths whose last part has the date's
        words, or its abbreviations read as a reader would (claude.SAYS); two at most."""
        d = inp.get("date") or {}
        ws = B.words(" ".join([str(d.get("name") or "")] + [str(t) for t in d.get("todo") or []]))
        want = set(ws) | {w for x in ws for w in C.SAYS.get(x, ())}
        scored = []
        for i, t in enumerate(inp.get("tags") or []):
            path = str(t.get("path") or "")
            leaf = B.words(path.split("::")[-1])
            hit = sum(1 for w in want if any(B.same_word(w, x) for x in leaf))
            if hit:
                scored.append((-hit, i, path))
        return [p for _h, _i, p in sorted(scored)[:2]]


class OwnAI(Runner):
    """Your own AI: the prompt to copy into any AI chat, and its answer pasted back (read)."""

    name = "Your own AI"
    key = "own"
    WORDS = "Copy the prompt into your own AI, then paste its answer back here."

    def available(self):
        return True, self.WORDS

    def run(self, req, done):
        done(None, self.WORDS)

    def prompt(self, job, doc=None, tree=None, name="", today="", said="", cover=None, req=None):
        """The prompt to copy: Plan the dates' and Tag by objective's own
        (prompts.py), the plan with the ops for words, the job's ask and its
        answer's shape for the rest."""
        doc = doc or {}
        if job == "plan":
            return _with_said(PR.for_plan(doc, tree, name, B.plan_start(doc, str(today)), cover), said)
        if job == "check":
            return _with_said(PR.for_plan(doc, tree, name, B.plan_start(doc, str(today)), cover),
                              said or "Only check the plan: answer with # lines only.")
        if job == "tag":
            return _with_said(PR.for_tags(doc, tree, name), said)
        if job == "words":
            return words_prompt(doc, tree, name, today, said)
        req = req or request_for(job, doc, tree, name, today, said)
        j = JOBS[req["job"]]
        return "\n".join([j.does, "", "Answer with JSON only, in one code block, in this shape:",
                          json.dumps(j.shape, indent=1), "", "What it's about:",
                          json.dumps(req["input"], ensure_ascii=False, indent=1)])

    @staticmethod
    def read(pasted, job=None):
        """A pasted answer: the JSON in it (code fences, words around it and
        all; a bare list is its ops), or for plan and tag its plan lines. None
        when there's nothing in it."""
        s = str(pasted or "").strip()[:400_000]
        if not s:
            return None
        j = JOBS.get(job)
        if j is not None and j.answer in ("text", "notes"):
            inner = _unfence(s)
            got = _json_in(inner) if inner.startswith("{") else None
            if isinstance(got, dict) and (got.get("ops") or got.get("text") or got.get("notes")):
                return got
            return {"text": inner} if j.answer == "text" else {"notes": check_notes(s)}
        for cand in [b for _lang, b in _FENCE.findall(s)] + [s]:
            got = _json_in(cand)
            if got is not None:
                return {"ops": got} if isinstance(got, list) else got
        return None


class Claude(Runner):
    """Claude, through the Worker: later. Nothing new on the server yet."""

    name = "Claude"
    key = "claude"

    def available(self):
        return False, "Claude isn't connected yet."


RUNNERS = {"off": Off, "standin": StandIn, "own": OwnAI, "claude": Claude}


def runner_for(labs, choice):
    """The runner for a choice ("off", "standin", "own", "claude"): the
    stand-in only with labs on; anything else is Off."""
    if choice == "standin" and not labs:
        return Off()
    return RUNNERS.get(choice, Off)()


# ---- the prompts' plumbing ----

_FENCE = re.compile(r"```[ \t]*([A-Za-z0-9_+-]*)[ \t]*\r?\n(.*?)```", re.S)


def _unfence(s):
    """What's inside a pasted answer's code blocks, or all of it."""
    blocks = [b.strip("\n") for _lang, b in _FENCE.findall(str(s or ""))]
    return "\n".join(blocks).strip() if blocks else str(s or "").strip()


def _json_in(s, tries=200):
    """The first JSON object or list in the text, or None."""
    dec = json.JSONDecoder()
    for n, m in enumerate(re.finditer(r"[\[{]", s)):
        if n >= tries:
            break
        try:
            v, _end = dec.raw_decode(s, m.start())
        except ValueError:
            continue
        if isinstance(v, (dict, list)):
            return v
    return None


def _with_said(prompt, said):
    """The author's words in the prompt's "(edit this part):" space."""
    said = str(said or "").strip()
    if not said:
        return prompt
    return prompt.replace("(edit this part):\n\n", f"(edit this part):\n{said}\n", 1)


def date_line(u, doc, tree=None, placed=None):
    """One date as the words prompt and the AI app list it: id | day | name | what's on it."""
    evs = {e["id"]: e for e in _events(doc)}
    n = date_cards(u, tree, placed)
    bits = [u["id"], str(u.get("opens") or ""), u.get("name") or "?", ", ".join(sources(u, doc)) or "no cards yet"]
    if n is not None:
        bits.append(f"{n:,} cards")
    if u.get("due"):
        bits.append(f"due {u['due']}" + (" even" if u.get("even") else ""))
    if u.get("for") in evs:
        bits.append(f"for {evs[u['for']].get('name')}")
    return " | ".join(bits)


def words_prompt(doc, tree, name, today, said=""):
    """The prompt for a change in my own words: the ops an answer may hold
    (vocabulary), the plan by date id, the deck's tags; JSON back."""
    placed = B.placed_keys(doc, tree) if tree is not None else None
    ops = [f"- {v['op']}: {v['does']} Fields: " + "; ".join(f"{k}: {d}" for k, d in v["fields"].items())
           + f". Example: {json.dumps(v['example'], ensure_ascii=False)}" for v in vocabulary(for_ai=True)]
    out = [f"I'm changing my study plan \"{name}\" in Anki (Due Crew) on the deck \"{doc.get('deck') or ''}\". "
           "Answer with JSON only, in one code block:",
           '{"ops": [ ... ], "say": "one line on what changed"}',
           "",
           "Each op is one change, done in order on the plan as the ones before it leave it. Name a date by its id "
           "(the first part of its line below). Copy tags exactly from the plan or the deck's tags below; never "
           "invent one. Never put card text in a plan.",
           "",
           "The changes:", *ops, "",
           f"Today is {today}.", "",
           "The plan's dates (id | day | name | what's on it):",
           *[date_line(u, doc, tree, placed) for u in sorted(P.units(doc), key=lambda u: str(u.get("opens") or ""))],
           "", "Its quizzes and exams (id | day | name):",
           *[f"{e['id']} | {e.get('day')} | {e.get('name')}" for e in _events(doc)],
           "", "What I want (edit this part):", str(said or "").strip(), ""]
    if tree is not None:
        lines, more = PR.tag_lines(tree)
        out += ["The deck's tags (tag or subdeck, card count, readable name)"
                + (f"; {more:,} more aren't listed" if more > 0 else "") + ":", *lines]
    return "\n".join(out)
