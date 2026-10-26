"""3.9.5: Shapes in New plan (docs/planner.md; Sam's pick on the "Five
mocks, reviewed" page: people got most of the way to a plan and stalled,
one asked for "one chapter's cards being due daily"). A tag folder of
the deck (From) and a shape, and the plan comes out filled: each tag in
the folder a date, in the deck's order, named as the builder names one
(autoName), its tag and nothing else on it.

- One a day: a tag each study day, from today.
- Done by the exam: spread as evenly as the study days allow from today
  to the exam, the last week before it left free (the last fifth when the
  span is short); tags share a date when they must.
- A week each: a tag a week, on the week's first study day.

Pure: tag names and counts, no Anki, no Qt (new_plan.py is the window).
Not shape.py, the plan's dates and pace in Settings."""

import copy
import datetime
import math
import random

from .. import plans as P
from . import build as B
from . import edits as E
from . import model as M

SEP = "::"
SHAPES = (("day", "One a day"), ("exam", "Done by the exam"), ("week", "A week each"))
WEEKDAYS = (1, 1, 1, 1, 1, 0, 0)   # New plan's study days (edits.new_plan_doc's pace)
FREE = 7                           # Done by the exam: the days before it left free, at most


def _d(x):
    return x if isinstance(x, datetime.date) else datetime.date.fromisoformat(str(x)[:10])


def _study(days, d):
    return bool(days[d.weekday()])


def _first(days, d):
    """The first study day on or after d (None: no study days)."""
    for i in range(7):
        x = d + datetime.timedelta(days=i)
        if _study(days, x):
            return x
    return None


# ---- the deck's folders ----

def tree_of(idx):
    """The deck's tags as the builder reads them (build.Tree, every path
    above a tag too), from a DeckIndex's tags as written; a tag's cards
    counted only when asked (a big deck's 30,000 aren't all counted to find
    its folders)."""
    rows = {}
    for t in idx.tag_names.values():
        parts = str(t).split(SEP)
        for i in range(1, len(parts) + 1):
            p = SEP.join(parts[:i])
            rows.setdefault(p.lower(), p)
    return B.Tree([(p, None) for p in rows.values()], count=lambda _kind, path: len(idx.tag_cards(path)))


def _ok(path):
    """A tag a date can hold (plans.ts PATH_MAX, one printable line), not a bank's question id."""
    return 0 < len(path) <= E.PATH_MAX and path.isprintable() and not M.is_question(path)


def _kid_keys(tree, key):
    return [k for k in tree.kids(key) if B.kind_of(k) == "tag" and _ok(B.path_of(k))]


def kids(tree, path):
    """[(tag, cards)]: a folder's tags, in natural order as the planner
    sorts tag names ("Chapter 2" before "Chapter 10"); a bank's question
    ids, and a tag with no cards here, left out."""
    ks = sorted(_kid_keys(tree, f"tag:{path}"), key=lambda k: B.natural(B.path_of(k)))
    return [(B.path_of(k), n) for k, n in ((k, tree.n(k)) for k in ks) if n > 0]


def folders(tree):
    """The deck's tag folders a shape fills a plan from: each tag holding two
    or more tags (a bank's question ids aside), in the deck's order."""
    return [B.path_of(k) for k in tree.order if B.kind_of(k) == "tag" and len(_kid_keys(tree, k)) >= 2]


def labels(paths):
    """{folder: how From reads it}: its path read ("Pharm › Antibiotics");
    when every folder is under one root (a big shared deck's), the root
    left off ("› Resources › Pathology videos"), the root itself by name."""
    paths = list(paths)
    common = len(paths) > 1 and len({p.split(SEP)[0].lower() for p in paths}) == 1
    out = {}
    for p in paths:
        parts = p.split(SEP)
        out[p] = ("› " + " › ".join(B.tag_word(x) for x in parts[1:])) if common and len(parts) > 1 \
            else B.tag_name(p)
    return out


def name_of(path):
    """A plan's first name from its folder: "Pathology videos"."""
    return E._cut(B.tag_word(str(path).split(SEP)[-1]), E.NAME_MAX).strip()


# ---- the dates ----

def lay(shape, tags, today, end=None, days=WEEKDAYS):
    """The dates a shape makes of a folder's tags ([(tag, cards)], in
    order): {dates: [{opens, tags, n, due?}], cards, study (the study days
    they span), last (the day the last is done), why (a reason there are
    none, else "")}. end: the exam's day. The last date of A week each and
    Done by the exam is due at the end of its stretch, so it spreads over
    its days as the ones before it do (each runs to the next)."""
    days, today = list(days), _d(today)
    out = {"dates": [], "cards": sum(n for _p, n in tags), "study": 0, "last": None, "why": ""}
    if not any(days):
        out["why"] = "Pick a study day."
        return out
    if not tags:
        out["why"] = "No tags in it to put on a date."
        return out
    dates = out["dates"]
    if shape == "day":
        d = _first(days, today)
        for p, n in tags:
            dates.append({"opens": d.isoformat(), "tags": [p], "n": n})
            d = _first(days, d + datetime.timedelta(days=1))
        out["study"] = len(dates)
    elif shape == "week":
        mon = today - datetime.timedelta(days=today.weekday())
        on = [i for i in range(7) if days[i]]
        d = mon + datetime.timedelta(days=on[0])
        if d < today:
            d += datetime.timedelta(days=7)
        for p, n in tags:
            dates.append({"opens": d.isoformat(), "tags": [p], "n": n})
            d += datetime.timedelta(days=7)
        if on[-1] > on[0]:
            dates[-1]["due"] = (_d(dates[-1]["opens"]) + datetime.timedelta(days=on[-1] - on[0])).isoformat()
        out["study"] = len(dates) * len(on)
    elif shape == "exam":
        if end is None:
            out["why"] = "Pick the exam's day."
            return out
        end = _d(end)
        span = (end - today).days
        stop = end - datetime.timedelta(days=min(FREE, max(0, span) // 5) + 1)
        study = []
        d = today
        while d <= stop:
            if _study(days, d):
                study.append(d)
            d += datetime.timedelta(days=1)
        if not study:
            out["why"] = "No study days before the exam."
            return out
        m, k = len(study), len(tags)
        at = {}
        for i, (p, n) in enumerate(tags):
            j = i * m // k
            if j not in at:
                at[j] = {"opens": study[j].isoformat(), "tags": [], "n": 0}
                dates.append(at[j])
            at[j]["tags"].append(p)
            at[j]["n"] += n
        if study[-1].isoformat() > dates[-1]["opens"]:
            dates[-1]["due"] = study[-1].isoformat()
        out["study"] = m
    else:
        out["why"] = "That isn't a shape."
        return out
    out["last"] = dates[-1].get("due") or dates[-1]["opens"]
    if len(dates) > E.UNITS_MAX:
        out["why"] = f"A plan holds up to {E.UNITS_MAX} dates."
    elif any(len(x["tags"]) > E.SOURCES_MAX for x in dates):
        out["why"] = f"A date holds up to {E.SOURCES_MAX} tags."
    return out


def daily(laid):
    """New cards a study day the dates ask, about (the plan's pace)."""
    return max(1, math.ceil(laid["cards"] / laid["study"])) if laid.get("study") else 1


def line(laid, end=None, exam=""):
    """(words, late): what the shape makes, "34 dates · ~40 new a study day
    · done Mon 30 Nov"; late when it isn't done before the exam (or there
    are no dates: why)."""
    if laid.get("why"):
        return laid["why"], True
    n = len(laid["dates"])
    words = (f"{n:,} date{'s' if n != 1 else ''} · ~{B.about(max(1, laid['cards'] / laid['study']))} new a study day"
             f" · done {P.fmt_day(laid['last'])}")
    if end is None or laid["last"] < _d(end).isoformat():
        return words, False
    who = " ".join(str(exam or "").split()) or "the exam"
    late = (_d(laid["last"]) - _d(end)).days
    return words + (f", the day of {who}" if not late else f", {late:,} day{'s' if late != 1 else ''} after {who}"), True


# ---- New plan's doc ----

def new_doc(deck, sessions, end_name, end_day, laid=None, tree=None, days=WEEKDAYS, rng=random):
    """(doc, [date ids]) as New plan makes it. A calendar's sessions win (and
    with no shape laid it's edits.new_plan_doc's, as before shapes): the
    plan's exam, end and pace, with the shape's dates on it, each its tags
    and nothing else, named as the builder names a date (name_dates), the
    pace the cards a study day they ask, each date tested on the exam."""
    if sessions or not laid:
        return E.new_plan_doc(deck, sessions, end_name, end_day)
    if laid.get("why"):
        raise E.Refused(laid["why"])
    doc, _u = E.new_plan_doc(deck, [], end_name, end_day)
    before, uids = copy.deepcopy(doc), []
    for x in laid["dates"]:
        doc, uid = E.add_date(doc, x["opens"], x["tags"], rng=rng)
        if x.get("due"):
            doc = E.set_due(doc, uid, x["due"])
        uids.append(uid)
    doc = E.name_dates(doc, before, tree)
    doc = E.set_pace(doc, (doc.get("pace") or {}).get("mode") or "daily", days, daily(laid))
    if doc.get("events"):
        doc = E.prep_for(doc, {})
    return doc, uids


# ---- the picture on each shape ----

def cell(shape, row, col):
    """A cell of the shape's picture, three weeks of a calendar: "on" a
    date's day, "off" a day off, "free" the week left free before the
    exam, "exam" its day, "soft" every other week of A week each."""
    if shape == "week":
        return "on" if row % 2 == 0 else "soft"
    if shape == "exam" and row == 2:
        return "exam" if col == 6 else "free"
    return "on" if col < 5 else "off"
