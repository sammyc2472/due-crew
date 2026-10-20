"""A plan's changes as data (round five, docs/planner.md): every change an
author makes in Your plans, a pasted calendar makes, or an AI proposes is
one op, a small JSON object ({"op": "move", "date": "…", "to": "…"}),
checked here, applied by edits.py (the builder's own edits), and said in
words for the changes waiting to be sent (draft.py).

An op names a date by its id, or as an author or an AI would: its day
("2026-10-22"), its name ("Shock"), or both ("2026-10-22 Shock"); check()
turns that into the id, once, and says so when it can't. A new date or
event's id comes from the op's own seed, so the same ops on the same plan
make the same ids (a draft is replayed on the plan as the server has it
whenever it loads or a send comes back stale).

Pure: no Anki, no server. ctx is what the deck says (the builder's tree,
for naming dates as the builder names them, and for counts), and today."""

import copy
import datetime
import random
import re

from .. import plans as P
from . import build as B
from . import edits as E
from . import model as M

Refused = E.Refused
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
OPS_MAX = 200          # a draft's changes, at most (each is a save's worth of work)
WHY_MAX = 200          # plans.ts POST_MAX: the line followers get with a send


class Ctx:
    """What applying an op may read: the deck's tree here (build.Tree, or
    None when the deck isn't in this Anki), today (iso), the plan's name (its
    own tags' root), and its study days (for the shape's ops)."""

    def __init__(self, tree=None, today=None, plan_name="", days=None):
        self.tree = tree
        self.today = today or datetime.date.today().isoformat()
        self.plan_name = plan_name
        self.days = days


def seed():
    return random.randrange(1, 2 ** 31)


def _rng(o):
    return random.Random(int(o.get("seed") or 1))


# ---- naming dates and events ----

def _units(doc):
    return [u for u in doc.get("units") or [] if isinstance(u, dict) and u.get("id")]


def _events(doc):
    return [e for e in doc.get("events") or [] if isinstance(e, dict) and e.get("id")]


def _norm(s):
    return " ".join(str(s or "").lower().split())


def find_date(doc, ref):
    """A date's id from how an op names it: its id, its day, its name, or
    "YYYY-MM-DD name". Refused when nothing or more than one matches."""
    ref = str(ref or "").strip()
    us = _units(doc)
    if not ref:
        raise Refused("Which date? Name it by its day or its name.")
    by_id = [u for u in us if u["id"] == ref]
    if by_id:
        return ref
    day, name = (ref[:10], ref[10:].strip(" ·|-")) if ISO.match(ref[:10]) else (None, ref)
    hits = [u for u in us if (day is None or u.get("opens") == day) and (not name or _norm(u.get("name")) == _norm(name))]
    if not hits and name:
        hits = [u for u in us if (day is None or u.get("opens") == day) and _norm(name) in _norm(u.get("name"))]
    if len(hits) == 1:
        return hits[0]["id"]
    if not hits:
        raise Refused(f"No date on the plan is {ref}.")
    raise Refused(f"{len(hits)} dates are {ref}: say its day too.")


def find_event(doc, ref):
    ref = str(ref or "").strip()
    es = _events(doc)
    if any(e["id"] == ref for e in es):
        return ref
    day, name = (ref[:10], ref[10:].strip(" ·|-")) if ISO.match(ref[:10]) else (None, ref)
    hits = [e for e in es if (day is None or e.get("day") == day) and (not name or _norm(e.get("name")) == _norm(name))]
    if len(hits) == 1:
        return hits[0]["id"]
    if not hits:
        raise Refused(f"No quiz or exam on the plan is {ref}.")
    raise Refused(f"{len(hits)} quizzes or exams are {ref}: say its day too.")


def _iso(v, what="day"):
    v = str(v or "").strip()
    if not ISO.match(v):
        raise Refused(f"That {what} isn't a date (YYYY-MM-DD).")
    E._day(v)
    return v


def _list(v, what):
    if v is None:
        return []
    if not isinstance(v, (list, tuple)):
        raise Refused(f"{what} is a list.")
    return list(v)


def _str(v, what, most=600):
    v = str(v if v is not None else "").strip()
    if not v or len(v) > most:
        raise Refused(f"{what} is missing or too long.")
    return v


# ---- the ops: each check()s its args and apply()s itself ----

class Op:
    """One kind of op: check(doc, o) -> o with its refs as ids; run(doc, o,
    ctx) -> (doc, {made ids}); words(o, before, after, ctx) -> entries."""

    rename = True   # the dates named for what's on them named again after it (renameAll)

    def check(self, doc, o):
        return o

    def run(self, doc, o, ctx):
        raise NotImplementedError

    def words(self, o, before, after, ctx):
        return diff_words(before, after)


REG = {}


def op(name):
    def reg(cls):
        REG[name] = cls()
        return cls
    return reg


def _date_ref(doc, o, key="date"):
    o = dict(o)
    o[key] = find_date(doc, o.get(key))
    return o


def _label(doc, uid):
    u = next((x for x in _units(doc) if x["id"] == uid), None)
    return M.date_label(u) if u else "a date"


def _src_words(tags=(), decks=(), tree=None):
    out = []
    for kind, items in (("tag", tags), ("deck", decks)):
        for p in items:
            n = tree.n(f"{kind}:{p}") if tree is not None else None
            out.append(f"{M.label(p)}" + (f", {n:,} cards" if n else ""))
    return "; ".join(out)


def _entry(verb, what, detail="", uid=None, day=None):
    return {"verb": verb, "what": what, "detail": detail, "uid": uid, "day": day}


@op("add_cards")
class AddCards(Op):
    def check(self, doc, o):
        o = _date_ref(doc, o)
        o["tags"] = [E._path(p) for p in _list(o.get("tags"), "tags")]
        o["decks"] = [E._path(p) for p in _list(o.get("decks"), "decks")]
        if not (o["tags"] or o["decks"]):
            raise Refused("Add what? Name a tag or a subdeck.")
        return o

    def run(self, doc, o, ctx):
        doc, took = E.add_sources(doc, o["date"], o["tags"], o["decks"])
        if not took:
            raise Refused("That date has those already.")
        return doc, set()

    def words(self, o, before, after, ctx):
        return [_entry("Added", _label(after, o["date"]), _src_words(o["tags"], o["decks"], ctx.tree), o["date"])]


@op("take_cards")
class TakeCards(Op):
    def check(self, doc, o):
        o = _date_ref(doc, o)
        k = _list(o.get("key"), "key")
        if not k or k[0] not in ("tag", "deck", "cut", "questions", "search", "picks"):
            raise Refused("Take off which of its cards?")
        if k[0] == "questions":
            k = ["questions", list(k[1] if len(k) > 1 else [])]
        o["key"] = k
        return o

    def run(self, doc, o, ctx):
        k = o["key"]
        key = ("questions", tuple(k[1])) if k[0] == "questions" else tuple(k)
        return E.take_source(doc, o["date"], key), set()

    def words(self, o, before, after, ctx):
        k = o["key"]
        what = {"tag": lambda: M.label(k[1]), "deck": lambda: M.label(k[1]), "cut": lambda: M.label(k[1]),
                "questions": lambda: f"{len(k[1]):,} questions", "search": lambda: B.search_name(k[1]),
                "picks": lambda: "its picked cards"}[k[0]]()
        return [_entry("Took off", _label(before, o["date"]), what, o["date"])]


@op("add_search")
class AddSearch(Op):
    def check(self, doc, o):
        o = _date_ref(doc, o)
        o["q"] = _str(o.get("q"), "The search", 500)
        return o

    def run(self, doc, o, ctx):
        return E.add_search(doc, o["date"], o["q"], o.get("n")), set()

    def words(self, o, before, after, ctx):
        n = o.get("n")
        return [_entry("Added", _label(after, o["date"]), f"a search: {B.search_name(o['q'])}" + (f", {n:,} cards" if n else ""), o["date"])]


@op("add_ids")
class AddIds(Op):
    def check(self, doc, o):
        o = _date_ref(doc, o)
        if o.get("kind") not in ("nids", "cids"):
            raise Refused("Note IDs or card IDs?")
        o["ids"] = [int(x) for x in _list(o.get("ids"), "ids") if str(x).isdigit()]
        if not o["ids"]:
            raise Refused("No IDs to add.")
        return o

    def run(self, doc, o, ctx):
        return E.add_ids(doc, o["date"], o["kind"], o["ids"]), set()

    def words(self, o, before, after, ctx):
        n = len(o["ids"])
        return [_entry("Added", _label(after, o["date"]), f"{n:,} {'note' if o['kind'] == 'nids' else 'card'} ID{'s' if n != 1 else ''}", o["date"])]


@op("add_picks")
class AddPicks(Op):
    def check(self, doc, o):
        o = _date_ref(doc, o)
        o["notes"] = [str(g) for g in _list(o.get("notes"), "notes")]
        o["cards"] = [[str(c[0]), int(c[1])] for c in _list(o.get("cards"), "cards") if isinstance(c, (list, tuple)) and len(c) == 2]
        if not (o["notes"] or o["cards"]):
            raise Refused("No notes or cards to add.")
        return o

    def run(self, doc, o, ctx):
        return E.add_picks(doc, o["date"], o["notes"], [tuple(c) for c in o["cards"]]), set()

    def words(self, o, before, after, ctx):
        bits = [f"{len(o['notes']):,} notes" if o["notes"] else "", f"{len(o['cards']):,} single cards" if o["cards"] else ""]
        return [_entry("Added", _label(after, o["date"]), ", ".join(b for b in bits if b), o["date"])]


@op("rename")
class Rename(Op):
    def check(self, doc, o):
        o = _date_ref(doc, o)
        o["name"] = E._name(o.get("name"))
        return o

    def run(self, doc, o, ctx):
        return E.rename(doc, o["date"], o["name"]), set()

    def words(self, o, before, after, ctx):
        old = next((u.get("name") for u in _units(before) if u["id"] == o["date"]), "")
        return [_entry("Renamed", _label(after, o["date"]), f"was {old}", o["date"])]


@op("move")
class Move(Op):
    def check(self, doc, o):
        o = _date_ref(doc, o)
        o["to"] = _iso(o.get("to"))
        return o

    def run(self, doc, o, ctx):
        return E.move(doc, o["date"], o["to"]), set()

    def words(self, o, before, after, ctx):
        old = next((u.get("opens") for u in _units(before) if u["id"] == o["date"]), None)
        return [_entry("Moved", _label(after, o["date"]), f"from {P.fmt_day(old)}" if old else "", o["date"], old)]


@op("move_from")
class MoveFrom(Op):
    """This date and every date after it, `days` days later (or earlier):
    their finish-by days and review days with them; quizzes stay."""

    def check(self, doc, o):
        o = _date_ref(doc, o)
        try:
            o["days"] = int(o.get("days"))
        except (TypeError, ValueError):
            raise Refused("How many days?") from None
        if not o["days"] or abs(o["days"]) > 120:
            raise Refused("Move them 1 to 120 days.")
        return o

    def run(self, doc, o, ctx):
        return E.shift_from(doc, o["date"], o["days"]), set()

    def words(self, o, before, after, ctx):
        day = next((u.get("opens") for u in _units(before) if u["id"] == o["date"]), "")
        n = sum(1 for u in _units(before) if str(u.get("opens") or "") >= day) - 1
        d = abs(o["days"])
        return [_entry("Moved", _label(after, o["date"]) + (f" and the {n:,} date{'s' if n != 1 else ''} after it" if n else ""),
                       f"{d} day{'s' if d != 1 else ''} {'later' if o['days'] > 0 else 'earlier'}", o["date"], day)]


@op("set_due")
class SetDue(Op):
    def check(self, doc, o):
        o = _date_ref(doc, o)
        o["due"] = _iso(o["due"]) if o.get("due") else None
        return o

    def run(self, doc, o, ctx):
        return E.set_due(doc, o["date"], o["due"]), set()

    def words(self, o, before, after, ctx):
        return [_entry("Changed", _label(after, o["date"]), f"finish by {P.fmt_day(o['due'])}" if o["due"] else "no finish-by day", o["date"])]


@op("set_for")
class SetFor(Op):
    def check(self, doc, o):
        o = _date_ref(doc, o)
        o["event"] = find_event(doc, o["event"]) if o.get("event") else None
        return o

    def run(self, doc, o, ctx):
        return E.set_for(doc, o["date"], o["event"]), set()

    def words(self, o, before, after, ctx):
        ev = next((e for e in _events(after) if e["id"] == o["event"]), None)
        return [_entry("Tested on", _label(after, o["date"]), (ev or {}).get("name") or "nothing", o["date"])]


@op("set_even")
class SetEven(Op):
    def check(self, doc, o):
        o = _date_ref(doc, o)
        o["on"] = bool(o.get("on"))
        return o

    def run(self, doc, o, ctx):
        return E.set_even(doc, o["date"], o["on"]), set()

    def words(self, o, before, after, ctx):
        return [_entry("Changed", _label(after, o["date"]), "spread evenly to its finish-by day" if o["on"] else "not spread", o["date"])]


@op("add_date")
class AddDate(Op):
    def check(self, doc, o):
        o = dict(o)
        o["day"] = _iso(o.get("day"))
        o["tags"] = [E._path(p) for p in _list(o.get("tags"), "tags")]
        o["decks"] = [E._path(p) for p in _list(o.get("decks"), "decks")]
        o["name"] = E._name(o["name"]) if o.get("name") else None
        if not (o["tags"] or o["decks"]) and not o["name"]:
            raise Refused("A new date needs a name or something on it.")
        return o

    def run(self, doc, o, ctx):
        if o["tags"] or o["decks"]:
            doc, uid = E.add_date(doc, o["day"], o["tags"], o["decks"], o["name"], _rng(o))
        else:
            doc, uid = E.add_empty_date(doc, o["day"], o["name"], _rng(o))
        return doc, {uid}

    def words(self, o, before, after, ctx):
        made = [u for u in _units(after) if u["id"] not in {x["id"] for x in _units(before)}]
        uid = made[0]["id"] if made else None
        what = _src_words(o["tags"], o["decks"], ctx.tree) or "no cards yet"
        return [_entry("Added", _label(after, uid) if uid else P.fmt_day(o["day"]), what, uid, o["day"])]


@op("delete_date")
class DeleteDate(Op):
    def check(self, doc, o):
        return _date_ref(doc, o)

    def run(self, doc, o, ctx):
        return E.delete_date(doc, o["date"]), set()

    def words(self, o, before, after, ctx):
        day = next((u.get("opens") for u in _units(before) if u["id"] == o["date"]), None)
        return [_entry("Gone", _label(before, o["date"]), "", o["date"], day)]


@op("add_event")
class AddEvent(Op):
    def check(self, doc, o):
        o = dict(o)
        o["day"] = _iso(o.get("day"))
        o["name"] = E._name(o.get("name"))
        return o

    def run(self, doc, o, ctx):
        doc, eid = E.add_event(doc, o["day"], o["name"], _rng(o))
        return doc, {eid}

    def words(self, o, before, after, ctx):
        return [_entry("Added", f"{P.fmt_day(o['day'])} · {o['name']}", "a quiz or exam", None, o["day"])]


class _EventOp(Op):
    def check(self, doc, o):
        o = dict(o)
        o["event"] = find_event(doc, o.get("event"))
        return o

    def _label(self, doc, eid):
        e = next((x for x in _events(doc) if x["id"] == eid), None)
        return M.event_label(e).lstrip("◆ ") if e else "a quiz or exam"


@op("rename_event")
class RenameEvent(_EventOp):
    def check(self, doc, o):
        o = super().check(doc, o)
        o["name"] = E._name(o.get("name"))
        return o

    def run(self, doc, o, ctx):
        return E.rename_event(doc, o["event"], o["name"]), set()

    def words(self, o, before, after, ctx):
        old = next((e.get("name") for e in _events(before) if e["id"] == o["event"]), "")
        return [_entry("Renamed", self._label(after, o["event"]), f"was {old}")]


@op("move_event")
class MoveEvent(_EventOp):
    def check(self, doc, o):
        o = super().check(doc, o)
        o["to"] = _iso(o.get("to"))
        return o

    def run(self, doc, o, ctx):
        return E.move_event(doc, o["event"], o["to"]), set()

    def words(self, o, before, after, ctx):
        old = next((e.get("day") for e in _events(before) if e["id"] == o["event"]), None)
        out = [_entry("Moved", self._label(after, o["event"]), f"from {P.fmt_day(old)}" if old else "", None, old)]
        late = [u for u in _units(after) if u.get("for") == o["event"] and str(u.get("due") or u.get("opens") or "") >= o["to"]]
        if late:
            out[0]["detail"] += f" · {len(late):,} date{'s' if len(late) != 1 else ''} now finish on it or after"
        return out


@op("take_event")
class TakeEvent(_EventOp):
    def run(self, doc, o, ctx):
        return E.take_event(doc, o["event"]), set()

    def words(self, o, before, after, ctx):
        return [_entry("Gone", self._label(before, o["event"]), "the dates for it stay")]


@op("set_todo")
class SetTodo(Op):
    rename = False

    def check(self, doc, o):
        o = _date_ref(doc, o)
        o["lines"] = B.todo_clean(_list(o.get("lines"), "lines"))
        return o

    def run(self, doc, o, ctx):
        return E.set_todo(doc, o["date"], o["lines"]), set()

    def words(self, o, before, after, ctx):
        n = len(o["lines"])
        return [_entry("Changed", _label(after, o["date"]), f"its to-dos ({n:,})" if n else "no to-dos", o["date"])]


@op("set_every")
class SetEvery(Op):
    rename = False

    def check(self, doc, o):
        o = dict(o)
        o["lines"] = B.every_clean(_list(o.get("lines"), "lines"))
        return o

    def run(self, doc, o, ctx):
        return E.set_every(doc, o["lines"]), set()

    def words(self, o, before, after, ctx):
        return [_entry("Changed", "Every week", "; ".join(f"{B.every_label(x.get('r'))}: {x.get('t')}" for x in o["lines"][:3]) or "none")]


@op("set_review")
class SetReview(Op):
    rename = False

    def check(self, doc, o):
        o = dict(o)
        o["day"] = _iso(o.get("day"))
        o["from"], o["to"] = find_date(doc, o.get("from")), find_date(doc, o.get("to"))
        return o

    def run(self, doc, o, ctx):
        return E.set_review(doc, o["day"], o["from"], o["to"]), set()

    def words(self, o, before, after, ctx):
        a, b = _label(after, o["from"]), _label(after, o["to"])
        had = any(r.get("day") == o["day"] for r in before.get("reviews") or [] if isinstance(r, dict))
        return [_entry("Changed" if had else "Added", f"{P.fmt_day(o['day'])} · Review", f"reviews {a} – {b}" if a != b else f"reviews {a}", None, o["day"])]


@op("take_review")
class TakeReview(Op):
    rename = False

    def check(self, doc, o):
        o = dict(o)
        o["day"] = _iso(o.get("day"))
        return o

    def run(self, doc, o, ctx):
        return E.take_review(doc, o["day"]), set()

    def words(self, o, before, after, ctx):
        return [_entry("Gone", f"{P.fmt_day(o['day'])} · Review", "", None, o["day"])]


@op("set_cut")
class SetCut(Op):
    def check(self, doc, o):
        o = _date_ref(doc, o)
        o["tag"] = E._path(o.get("tag"))
        o["ptag"] = str(o["ptag"]) if o.get("ptag") else None
        return o

    def run(self, doc, o, ctx):
        return E.set_cut(doc, o["date"], o["tag"], o["ptag"]), set()

    def words(self, o, before, after, ctx):
        t = next((x for x in P.plan_tags(after) if x.get("id") == o["ptag"]), None)
        return [_entry("Changed", _label(after, o["date"]), f"{M.label(o['tag'])}: only what {t.get('name')} holds" if t
                       else f"{M.label(o['tag'])}: all of it", o["date"])]


@op("set_extras")
class SetExtras(Op):
    def check(self, doc, o):
        o = _date_ref(doc, o)
        o["path"] = E._path(o.get("path"))
        o["without"] = bool(o.get("without"))
        o["kids"] = [E._path(p) for p in _list(o.get("kids"), "kids")]
        return o

    def run(self, doc, o, ctx):
        return E.set_extras(doc, o["date"], o["path"], o["without"], o["kids"], o.get("main_n")), set()

    def words(self, o, before, after, ctx):
        return [_entry("Changed", _label(after, o["date"]), f"{M.label(o['path'])}: {'without' if o['without'] else 'with'} its extras", o["date"])]


@op("set_tag_remark")
class SetTagRemark(Op):
    rename = False

    def check(self, doc, o):
        o = dict(o)
        o["tag"] = E._path(o.get("tag"))
        o["text"] = str(o.get("text") or "")
        return o

    def run(self, doc, o, ctx):
        return E.set_tag_remark(doc, o["tag"], o["text"], _rng(o)), set()

    def words(self, o, before, after, ctx):
        return [_entry("Note", M.label(o["tag"]), o["text"].strip() or "taken off")]


@op("take_remark")
class TakeRemark(Op):
    rename = False

    def check(self, doc, o):
        o = dict(o)
        o["id"] = _str(o.get("id"), "Which note")
        return o

    def run(self, doc, o, ctx):
        return E.take_remark(doc, o["id"]), set()

    def words(self, o, before, after, ctx):
        return [_entry("Gone", "A note for followers", "")]


@op("split_even")
class SplitEven(Op):
    def check(self, doc, o):
        o = _date_ref(doc, o)
        src = _list(o.get("source"), "source")
        if len(src) != 2 or src[0] not in ("tags", "decks"):
            raise Refused("Split which of its cards?")
        o["source"] = [src[0], E._path(src[1])]
        o["days"] = [_iso(d) for d in _list(o.get("days"), "days")]
        return o

    def run(self, doc, o, ctx):
        doc, nid = E.split_even(doc, o["date"], tuple(o["source"]), o["days"], _rng(o))
        return doc, {nid}

    def words(self, o, before, after, ctx):
        return [_entry("Split", _label(before, o["date"]), f"{M.label(o['source'][1])} evenly over {len(o['days']):,} study days", o["date"])]


@op("split_tags")
class SplitTags(Op):
    """Split by its tags: a tag off its date, its parts filled onto the
    study days from that date as the builder's Fill puts them (items and
    cap worked out when it was asked, so it replays the same)."""

    def check(self, doc, o):
        o = _date_ref(doc, o)
        if o.get("field") not in ("tags", "decks"):
            raise Refused("Split which of its cards?")
        o["path"] = E._path(o.get("path"))
        o["items"] = [dict(x) for x in _list(o.get("items"), "items") if isinstance(x, dict) and x.get("key")]
        o["cap"] = int(o.get("cap") or 0)
        o["days"] = [1 if x else 0 for x in _list(o.get("days"), "days")][:7] or [1, 1, 1, 1, 1, 0, 0]
        return o

    def run(self, doc, o, ctx):
        start = next(u["opens"] for u in _units(doc) if u["id"] == o["date"])
        doc = E.take_off(doc, o["date"], o["field"], o["path"], keep=True)
        rng = _rng(o)
        got = B.fill(doc, o["items"], start, None, o["cap"], o["days"], lambda: E.new_id(doc, rng))
        if got["left"]:
            raise Refused(got["note"] or f"{sum(x['n'] for x in got['left']):,} didn't fit: {B.left_names(got['left'])}.")
        return E.drop_if_empty(doc, o["date"]), set()

    def words(self, o, before, after, ctx):
        n = len(_units(after)) - len(_units(before)) + 1
        return [_entry("Split", _label(before, o["date"]), f"{M.label(o['path'])} by its tags, over {max(1, n):,} dates", o["date"])]


@op("place")
class Place(Op):
    """Lay them out: the ticked parts onto the days the builder's Fill chose
    ([[iso, field, path], ...], worked out when it was asked)."""

    def check(self, doc, o):
        o = dict(o)
        items = []
        for x in _list(o.get("items"), "items"):
            if not isinstance(x, (list, tuple)) or len(x) != 3 or x[1] not in ("tags", "decks"):
                raise Refused("A laid-out part is [day, tags or decks, path].")
            items.append([_iso(x[0]), x[1], E._path(x[2])])
        if not items:
            raise Refused("Nothing to lay out.")
        o["items"] = items
        return o

    def run(self, doc, o, ctx):
        doc, touched = E.place(doc, [tuple(x) for x in o["items"]], _rng(o))
        return doc, set(touched)

    def words(self, o, before, after, ctx):
        days = sorted({x[0] for x in o["items"]})
        n = o.get("n")
        what = f"{n:,} cards" if n else f"{len(o['items']):,} parts"
        span = P.fmt_day(days[0]) + (f" – {P.fmt_day(days[-1])}" if len(days) > 1 else "")
        return [_entry("Laid out", what, f"on {len(days):,} day{'s' if len(days) != 1 else ''}, {span}", None, days[0])]


@op("set_pace")
class SetPace(Op):
    rename = False

    def check(self, doc, o):
        o = dict(o)
        if o.get("mode") not in ("end", "daily", "placed"):
            raise Refused("Up to a number a day, fit to the end, or each date set by hand?")
        o["days"] = [1 if x else 0 for x in _list(o.get("days"), "days")][:7]
        if len(o["days"]) != 7 or not any(o["days"]):
            raise Refused("Pick a study day or more.")
        o["daily"] = int(o["daily"]) if o.get("daily") else None
        o["cover"] = [str(x) for x in _list(o.get("cover"), "cover")] if o.get("cover") is not None else None
        return o

    def run(self, doc, o, ctx):
        return E.set_pace(doc, o["mode"], o["days"], o["daily"], o["cover"]), set()

    def words(self, o, before, after, ctx):
        names = "".join("MTWTFSS"[i] for i, on in enumerate(o["days"]) if on)
        how = {"daily": f"up to {o['daily'] or 20} new cards a day", "end": "fit to the end", "placed": "each date set by hand"}[o["mode"]]
        return [_entry("Changed", "The plan’s shape", f"{how}, study days {names}")]


@op("set_end")
class SetEnd(Op):
    rename = False

    def check(self, doc, o):
        o = dict(o)
        o["end"] = _iso(o["end"]) if o.get("end") else None
        return o

    def run(self, doc, o, ctx):
        return E.set_end(doc, o["end"]), set()

    def words(self, o, before, after, ctx):
        return [_entry("Changed", "The plan’s shape", f"ends {P.fmt_day(o['end'])}" if o["end"] else "no end date")]


@op("set_phases")
class SetPhases(Op):
    rename = False

    def check(self, doc, o):
        o = dict(o)
        o["catchup"] = int(o["catchup"]) if o.get("catchup") is not None else None
        o["taper"] = int(o["taper"]) if o.get("taper") is not None else None
        return o

    def run(self, doc, o, ctx):
        return E.set_phases(doc, o["catchup"], o["taper"]), set()

    def words(self, o, before, after, ctx):
        ph = after.get("phases") or {}
        c, t = int(ph.get("catchup") or 0), int(ph.get("taper") or 0)
        bits = [f"a catch-up week every {c}" if c else "no catch-up weeks",
                f"no new cards the last {t} days" if t else "new cards to the end"]
        return [_entry("Changed", "The plan’s shape", ", ".join(bits))]


@op("shift_all")
class ShiftAll(Op):
    rename = False

    def check(self, doc, o):
        o = dict(o)
        o["days"] = int(o.get("days") or 0)
        if not o["days"]:
            raise Refused("Move it by how many days?")
        return o

    def run(self, doc, o, ctx):
        return E.shift_all(doc, o["days"]), set()

    def words(self, o, before, after, ctx):
        d = abs(o["days"])
        return [_entry("Moved", "Every date, quiz and review day", f"{d} day{'s' if d != 1 else ''} {'later' if o['days'] > 0 else 'earlier'}")]


@op("lay_out")
class LayOut(Op):
    """Lay them out (the deck panel's, the builder's Fill): what's ticked
    and on no date yet, on the plan's study days after its last date, at
    its pace; the pace and the ticks kept with it. week_ahead: just next
    week. aim: an event the new dates prep for (Fit them before the exam)."""

    def check(self, doc, o):
        o = dict(o)
        p = o.get("pace") if isinstance(o.get("pace"), dict) else {}
        if p.get("mode") not in ("end", "daily", "placed"):
            raise Refused("Lay them out how? (end, daily or placed)")
        days = [1 if x else 0 for x in _list(p.get("days"), "days")][:7] or [1, 1, 1, 1, 1, 0, 0]
        if len(days) != 7 or not any(days):
            raise Refused("Its study days are seven 1s and 0s, one at least.")
        o["pace"] = {"mode": p["mode"], "days": days, "daily": max(1, min(5000, int(p.get("daily") or 20)))}
        o["cover"] = [str(x) for x in _list(o.get("cover"), "cover")][:500]
        if not o["cover"]:
            raise Refused("Tick what the plan covers first.")
        o["start"] = _iso(o.get("start") or B.plan_start(doc, B.next_monday(datetime.date.today().isoformat())))
        o["end"] = _iso(o["end"]) if o.get("end") else None
        o["aim"] = find_event(doc, o["aim"]) if o.get("aim") else None
        o["week_ahead"] = bool(o.get("week_ahead"))
        return o

    def run(self, doc, o, ctx):
        if ctx.tree is None:
            raise Refused("The plan's deck isn't in this Anki, so there's nothing to lay out.")
        rng = _rng(o)
        doc = E.set_end(doc, o["end"]) if o["end"] else copy.deepcopy(doc)
        pace = dict(o["pace"])
        cover = set(o["cover"])
        if pace["mode"] == "end":
            d1 = B.end_daily(doc, ctx.tree, pace, cover, o["start"]) or pace["daily"]
            pace["daily"] = max(1, min(5000, int(d1)))
        doc = E.set_pace(doc, pace["mode"], pace["days"], pace.get("daily"), B.cover_items(ctx.tree, cover)[:500])
        r = B.lay_out(doc, ctx.tree, dict(pace), cover, o["start"], ctx.today, lambda: E.new_id(doc, rng),
                      week_ahead=o["week_ahead"], aim=o["aim"])
        if not r["touched"]:
            raise Refused(r["note"] or "Nothing fit.")
        if r.get("daily"):
            doc["pace"]["daily"] = max(1, min(5000, int(r["daily"])))
        return doc, set(r["touched"])

    def words(self, o, before, after, ctx):
        new = [u for u in _units(after) if u["id"] not in {x["id"] for x in _units(before)}]
        if not new:
            return diff_words(before, after)
        days = sorted(str(u.get("opens")) for u in new)
        return [_entry("Laid out", f"{len(new):,} new date{'s' if len(new) != 1 else ''}",
                       f"{P.fmt_day(days[0])} – {P.fmt_day(days[-1])}" if len(days) > 1 else P.fmt_day(days[0]),
                       None, days[0])]


@op("breather")
class Breather(Op):
    rename = False

    def check(self, doc, o):
        o = dict(o)
        o["today"] = _iso(o.get("today"))
        o["days"] = [1 if x else 0 for x in _list(o.get("days"), "days")][:7] or [1, 1, 1, 1, 1, 0, 0]
        return o

    def run(self, doc, o, ctx):
        doc, _n = E.breather(doc, o["today"], o["days"])
        return doc, set()

    def words(self, o, before, after, ctx):
        n = sum(1 for u in _units(before) if str(u.get("opens") or "") > o["today"])
        return [_entry("Moved", f"The {n:,} date{'s' if n != 1 else ''} still to come", "a study day later; quizzes stay")]


@op("rename_plan_tag")
class RenamePlanTag(Op):
    def check(self, doc, o):
        o = dict(o)
        t = next((x for x in P.plan_tags(doc) if x.get("id") == o.get("tag") or _norm(x.get("name")) == _norm(o.get("tag"))), None)
        if t is None:
            raise Refused(f"The plan has no tag {o.get('tag')}.")
        o["tag"] = t["id"]
        o["name"] = _str(o.get("name"), "Its name", 40)
        return o

    def run(self, doc, o, ctx):
        return E.rename_plan_tag(doc, o["tag"], o["name"]), set()

    def words(self, o, before, after, ctx):
        old = next((x.get("name") for x in P.plan_tags(before) if x.get("id") == o["tag"]), "")
        return [_entry("Renamed", f"The plan’s tag {old}", f"now {o['name']}")]


@op("delete_plan_tag")
class DeletePlanTag(RenamePlanTag):
    def check(self, doc, o):
        o = dict(o, name=o.get("name") or "x")
        o = super().check(doc, o)
        o.pop("name", None)
        return o

    def run(self, doc, o, ctx):
        return E.delete_plan_tag(doc, o["tag"]), set()

    def words(self, o, before, after, ctx):
        old = next((x.get("name") for x in P.plan_tags(before) if x.get("id") == o["tag"]), "")
        return [_entry("Gone", f"The plan’s tag {old}", E.drop_say(before, o["tag"]) or "")]


@op("set_deck_url")
class SetDeckUrl(Op):
    rename = False

    def check(self, doc, o):
        o = dict(o)
        o["url"] = str(o.get("url") or "").strip() or None
        return o

    def run(self, doc, o, ctx):
        return E.set_deck_url(doc, o["url"]), set()

    def words(self, o, before, after, ctx):
        return [_entry("Changed", "Where to get the deck", o["url"] or "no link")]


@op("text")
class Text(Op):
    """Plan lines (Add) or the whole plan as text (Replace): text.py's read
    and use, as the Text tab does; take_tags: a tag the text leaves out
    that a date still uses comes off those dates too (Replace)."""

    rename = False

    def check(self, doc, o):
        o = dict(o)
        o["mode"] = "replace" if o.get("mode") == "replace" else "add"
        o["text"] = _str(o.get("text"), "The text", 400_000)
        o["take_tags"] = bool(o.get("take_tags"))
        return o

    def run(self, doc, o, ctx):
        from . import text as T
        rng = _rng(o)

        def uid8():
            return "".join(rng.choice(E._ALPHABET) for _ in range(8))
        whole = o["mode"] == "replace"
        start = B.plan_start(doc, B.next_monday(ctx.today))  # the Text tab's start
        r = T.from_text(doc, ctx.tree, o["text"], whole=whole, start=start, plan_name=ctx.plan_name, new_id=uid8)
        if r["errors"]:
            raise Refused(r["errors"][0])
        if not (r["units"] or r["events"] or r["tags"] or r["remarks"]) and not whole:
            raise Refused("No plan lines in that.")
        if whole and o["take_tags"] and T.using(doc, r, whole, ctx.plan_name):
            doc = T.take_all(doc, r, ctx.tree, ctx.plan_name)
        return T.apply(doc, r, whole, ctx.plan_name, new_id=uid8), set()


# ---- applying ----

def check(doc, o):
    """o, its refs made ids: Refused (with the words) when it isn't one."""
    if not isinstance(o, dict) or o.get("op") not in REG:
        raise Refused(f"There's no change called {o.get('op') if isinstance(o, dict) else o}.")
    o = REG[o["op"]].check(doc, dict(o))
    o.setdefault("seed", seed())
    return o


def apply(doc, o, ctx):
    """(doc after, entries, touched ids): one checked op on the doc, the
    dates named for what's on them named again (as every save of the
    builder's does), said in words for the changes."""
    kind = REG[o["op"]]
    after, made = kind.run(doc, o, ctx)
    if kind.rename:
        after = E.name_dates(after, doc, ctx.tree)
    entries = kind.words(o, doc, after, ctx)
    days = {u["id"]: u.get("opens") for u in _units(after)}
    days.update({u["id"]: u.get("opens") for u in _units(doc)})
    for x in entries:
        if not x.get("day") and x.get("uid") in days:
            x["day"] = days[x["uid"]]
    touched = set(made) | {o[k] for k in ("date", "from", "to") if isinstance(o.get(k), str) and o[k] in {u["id"] for u in _units(after)}}
    return after, entries, touched


def diff_words(before, after):
    """Entries for a change no op words itself (the text's): each date
    added, gone, moved or changed."""
    a = {u["id"]: u for u in _units(before)}
    b = {u["id"]: u for u in _units(after)}
    out = []
    for uid in sorted(b.keys() - a.keys(), key=lambda i: str(b[i].get("opens"))):
        out.append(_entry("Added", M.date_label(b[uid]), "", uid, b[uid].get("opens")))
    for uid in sorted(a.keys() - b.keys(), key=lambda i: str(a[i].get("opens"))):
        out.append(_entry("Gone", M.date_label(a[uid]), "", uid, a[uid].get("opens")))
    for uid in sorted(a.keys() & b.keys(), key=lambda i: str(b[i].get("opens"))):
        x, y = a[uid], b[uid]
        if x.get("opens") != y.get("opens"):
            out.append(_entry("Moved", M.date_label(y), f"from {P.fmt_day(x['opens'])}", uid, x.get("opens")))
        elif {k: v for k, v in x.items() if k not in ("n", "pn", "idn", "idr", "pl")} != {k: v for k, v in y.items() if k not in ("n", "pn", "idn", "idr", "pl")}:
            out.append(_entry("Changed", M.date_label(y), "", uid, y.get("opens")))
    ea = {e["id"]: e for e in _events(before)}
    eb = {e["id"]: e for e in _events(after)}
    for eid in eb.keys() - ea.keys():
        out.append(_entry("Added", M.event_label(eb[eid]).lstrip("◆ "), "a quiz or exam", None, eb[eid].get("day")))
    for eid in ea.keys() - eb.keys():
        out.append(_entry("Gone", M.event_label(ea[eid]).lstrip("◆ "), "", None, ea[eid].get("day")))
    for eid in ea.keys() & eb.keys():
        if ea[eid].get("day") != eb[eid].get("day"):
            out.append(_entry("Moved", M.event_label(eb[eid]).lstrip("◆ "), f"from {P.fmt_day(ea[eid].get('day'))}", None, ea[eid].get("day")))
    if not out:
        for key, word in (("reviews", "Review days"), ("every", "Every week"), ("remarks", "Notes for followers"),
                          ("tags", "The plan’s tags"), ("pace", "The plan’s shape"), ("end", "The plan’s shape")):
            if (before.get(key) or None) != (after.get(key) or None):
                out.append(_entry("Changed", word, ""))
                break
    return out or [_entry("Changed", "The plan", "")]


def who(entry, today):
    """Who a change touches, said: a date that opened already keeps its
    cards for anyone who has them; one still to come isn't open for anyone."""
    day = entry.get("day")
    if not day:
        return ""
    if str(day) <= str(today):
        return f"Open since {P.fmt_day(day)}: anyone who has its cards keeps them"
    return "Not open for anyone yet"


def why_line(entries):
    """A send's line to followers, filled in from its changes (one line,
    WHY_MAX): "Shock moved from Wed 21 to Thu 22; Valve disease added.\""""
    bits = []
    for x in entries:
        day, _sep, name = x["what"].partition(" · ")
        name = name or x["what"]
        verb, detail = x["verb"], x.get("detail") or ""
        if verb == "Moved" and detail.startswith("from ") and _sep:
            bits.append(f"{name} moved {detail} to {day}")
        elif verb == "Moved":
            bits.append(f"{x['what']} moved {detail}".strip())
        elif verb == "Laid out":
            bits.append(f"{x['what']} laid out {detail}".strip())
        elif verb == "Gone":
            bits.append(f"{name} taken off")
        elif verb == "Tested on":
            bits.append(f"{name} now for {detail}" if detail != "nothing" else f"{name} for no quiz now")
        elif verb in ("Added", "Split", "Renamed"):
            bits.append(f"{name} {verb.lower()}")
        else:
            bits.append(f"{name} changed")
    out = ""
    for b in dict.fromkeys(bits):
        nxt = (out + "; " if out else "") + b
        if len(nxt) + 1 > WHY_MAX:
            break
        out = nxt
    return (out[:1].upper() + out[1:] + ".") if out else ""


def send_line(changes):
    """The line a send starts from ([{op, entries}] waiting): an AI app's
    own reason when every change waiting is its and it gave one, else the
    changes in words (why_line). The person can always write over it."""
    whys = {" ".join(str(c["op"].get("why") or "").split()) for c in changes}
    if changes and all(c["op"].get("by") == "ai" for c in changes) and len(whys) == 1 and "" not in whys:
        return whys.pop()[:WHY_MAX]
    return why_line([x for c in changes for x in c["entries"]])


def copy_ops(ops):
    return [copy.deepcopy(o) for o in ops]
