"""Round five's Plan tab, what it shows worked out (docs/planner.md): the
plan's shape in one line, what each week asks (new cards a day, the
reviews it brings), the dates that need a look, and the deck's tags a
date's name points at (Suggest.tags, build.suggest, read through an index
so a plan of a hundred dates doesn't read a big deck's 12,000 tags a
hundred times). Pure: no Anki, no Qt."""

import datetime

from .. import plans as P
from .. import schedule as S
from . import build as B

DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _d(iso):
    try:
        return datetime.date.fromisoformat(str(iso)[:10])
    except ValueError:
        return None


def monday(iso):
    d = _d(iso)
    return (d - datetime.timedelta(days=d.weekday())).isoformat() if d else ""


def pace_of(doc):
    """The plan's pace as the builder reads it (fromDoc): one with an end and no pace finishes by it."""
    pace = dict({"mode": "placed" if P.units(doc) else "daily", "days": [1] * 7, "daily": 20}, **(doc.get("pace") or {}))
    if not doc.get("pace") and doc.get("end"):
        pace["mode"] = "end"
    return pace


def cap_of(doc, tree, pace):
    """New cards a day the plan asks for at most (0: each date placed by hand)."""
    if pace.get("mode") == "placed":
        return 0
    if pace.get("mode") == "end" and tree is not None:
        start = B.plan_start(doc, "")
        return int(B.end_daily(doc, tree, pace, set(pace.get("cover") or []), start) or pace.get("daily") or 0)
    return int(pace.get("daily") or 0)


def days_words(days):
    """"Mon–Fri", "Mon, Wed, Fri", "every day"."""
    on = [i for i, x in enumerate(days or [1] * 7) if x]
    if len(on) == 7:
        return "every day"
    if on and on == list(range(on[0], on[-1] + 1)) and len(on) > 2:
        return f"{DAYS[on[0]]}–{DAYS[on[-1]]}"
    return ", ".join(DAYS[i] for i in on) or "no days"


def last_event(doc):
    evs = sorted((e for e in doc.get("events") or [] if isinstance(e, dict) and e.get("day")), key=lambda e: str(e["day"]))
    return evs[-1] if evs else None


def ends_with(doc):
    """(the quiz or exam the plan ends with, or None; its end day, or ""):
    its end date, and the event on that day when it has one."""
    end = str(doc.get("end") or "")
    if not end:
        return None, ""
    ev = next((e for e in doc.get("events") or [] if isinstance(e, dict) and str(e.get("day")) == end), None)
    return ev, end


# ---- what each week asks ----

def work(doc, tree, pace):
    """{iso: new cards that day} (Work.map, as the builder counts a date)."""
    if tree is None:
        return {}
    placed = B.placed_keys(doc, tree)
    m = B.work_map(doc, lambda u: B.unit_total(tree, u, placed), pace.get("days") or [1] * 7)
    return {d: e["n"] for d, e in m.items()}


def reviews_by_day(per_new):
    """{iso: reviews that day} a typical card's curve brings from the new cards."""
    cv = B.curve()
    out = {}
    for day, n in per_new.items():
        d = _d(day)
        for k in range(1, len(cv)):
            x = (d + datetime.timedelta(days=k)).isoformat()
            out[x] = out.get(x, 0) + n * cv[k]
    return out


def week_asks(doc, tree, pace):
    """{a week's Monday: {new, reviews, top, over, cap}}: new cards a study
    day that week (its days' new over its study days), reviews a day (its
    seven days' over seven), its busiest day, and whether a day of it is over
    the pace by a quarter (Work.over)."""
    per = work(doc, tree, pace)
    if not per:
        return {}
    rv = reviews_by_day(per)
    cap = cap_of(doc, tree, pace)
    days = pace.get("days") or [1] * 7
    out = {}
    for mon in sorted({monday(d) for d in list(per) + list(rv)}):
        m = _d(mon)
        ds = [(m + datetime.timedelta(days=i)).isoformat() for i in range(7)]
        study = sum(1 for i in range(7) if days[i]) or 7
        new = sum(per.get(x, 0) for x in ds)
        top = max(per.get(x, 0) for x in ds)
        out[mon] = {"new": -(-new // study) if new else 0, "reviews": sum(rv.get(x, 0) for x in ds) / 7,
                    "top": top, "over": bool(cap) and top > cap * 1.25, "cap": cap}
    return out


def week_words(ask):
    """"9 new · 34 reviews a day", or the amber "41 new a day, over your 20 · 52 reviews"."""
    if not ask:
        return "", False
    r = B.about(ask["reviews"])
    if ask["over"]:
        return f"{ask['top']:,} new a day, over your {ask['cap']:,} · {r} reviews", True
    if not ask["new"] and r == "0":
        return "", False
    return f"{ask['new']:,} new · {r} reviews a day", False


def peak(asks):
    """(week n from 1, reviews a day) of the busiest week, or None."""
    best = None
    for i, (_mon, a) in enumerate(sorted(asks.items())):
        if best is None or a["reviews"] > best[1]:
            best = (i + 1, a["reviews"])
    return best if best and best[1] >= 5 else None


def shape_line(doc, tree, pace, asks):
    """The plan's shape, one line: "Mon 12 Oct → Block 2 exam Fri 13 Nov · Mon–Fri
    · 20 new cards a day · reviews peak ~115 a day (week 5) · no new cards the
    last 3 days". [(words, bold)] parts."""
    parts = []
    start = B.plan_start(doc, "")
    ev, end = ends_with(doc)
    if start or end:
        a = P.fmt_day(start) if start else "Not started"
        last = B.last_day(doc)
        b = (f"{ev.get('name') or 'the exam'} {P.fmt_day(end)}" if ev else P.fmt_day(end) if end
             else f"{P.fmt_day(last)}, no end set" if last else "no end set")
        parts.append((f"{a} → {b}", False))
    parts.append((days_words(pace.get("days")), False))
    cap = cap_of(doc, tree, pace)
    if pace.get("mode") == "placed":
        parts.append(("each date's cards set by hand", False))
    elif cap:
        parts.append((f"{cap:,} new cards a day" + (" to fit the end" if pace.get("mode") == "end" else ""), True))
    pk = peak(asks)
    if pk:
        parts.append((f"reviews peak ~{B.about(pk[1])} a day (week {pk[0]})", False))
    ph = doc.get("phases") or {}
    if ph.get("taper"):
        n = int(ph["taper"])
        parts.append((f"no new cards the last {n} day{'s' if n != 1 else ''}", False))
    if ph.get("catchup"):
        parts.append((f"a catch-up week every {int(ph['catchup'])}", False))
    return parts


# ---- suggestions (Suggest.tags), read through an index ----

class SuggestIndex:
    """The deck's tags by the first three letters of their last part's
    words: build.suggest needs one of a name's words in a tag's last part,
    and its same_word needs their first three letters alike, so the tags it
    reads for a name are these and no others (the answer is the same)."""

    def __init__(self, tree):
        self.tree = tree
        self.by = {}
        self.rows = []
        if tree is None:
            return
        for k in tree.order:
            if B.kind_of(k) != "tag":
                continue
            i = len(self.rows)
            path = B.path_of(k)
            self.rows.append((path, tree.n(k)))
            for w in B.words(path.split("::")[-1]):
                self.by.setdefault(w[:3], []).append(i)

    def rows_for(self, name):
        hit = set()
        for w in B.words(name):
            hit.update(self.by.get(w[:3], ()))
        return [self.rows[i] for i in sorted(hit)]

    def suggest(self, name, skip):
        return B.suggest(name, self.rows_for(name), skip)


def placed_skip(doc):
    """Suggest's skip: a tag on a date already, above one, or under one (a cut's too)."""
    on, above = set(), set()
    for k in B.placed_keys(doc):
        if B.kind_of(k) != "tag":
            continue
        low = B.path_of(k).lower()
        on.add(low)
        segs = low.split("::")
        above.update("::".join(segs[:i]) for i in range(1, len(segs)))
    for u in P.units(doc):
        for c in u.get("cut") or []:
            on.add(str(c.get("tag") or "").lower())

    def skip(path):
        low = str(path).lower()
        segs = low.split("::")
        return low in on or low in above or any("::".join(segs[:i]) in on for i in range(1, len(segs)))
    return skip


def by_hand(doc, tree, u, placed=None):
    """A date named by its author, not for what's on it (autoName)."""
    placed = B.placed_keys(doc, tree) if placed is None else placed
    return bool(str(u.get("name") or "").strip()) and u.get("name") != B.auto_name(doc, tree, u, placed)


def suggestions(doc, tree, index, turned_down=()):
    """{date id: [(path, n, sure)]}: for each date named by hand, the deck's
    tags its name points at that no date has; sure: the date has nothing on
    it yet and its name points at one tag alone (Add the sure ones adds
    those). A suggestion turned down here (✕) isn't made again."""
    if tree is None or index is None:
        return {}
    skip_placed = placed_skip(doc)
    no = {(str(a), str(b).lower()) for a, b in turned_down}
    placed = B.placed_keys(doc, tree)
    out = {}
    for u in P.units(doc):
        if not by_hand(doc, tree, u, placed):
            continue
        got = index.suggest(u.get("name"), lambda p, uid=u["id"]: skip_placed(p) or (uid, str(p).lower()) in no)
        if got:
            empty = not B.srcs(u) and not B.unit_total(tree, u, placed)
            out[u["id"]] = [(p, n, empty and len(got) == 1) for p, n in got]
    return out


def needs_look(doc, tree, counts, sugg, asks):
    """{date id: why}: a date with no cards here, one a maybe points at, one
    in a week over the pace."""
    out = {}
    for u in P.units(doc):
        uid = u["id"]
        if counts.get(uid) == 0:
            out[uid] = "no cards here yet"
        elif any(not sure for _p, _n, sure in sugg.get(uid, ())):
            out[uid] = "a maybe to look at"
        elif (asks.get(monday(u.get("opens"))) or {}).get("over"):
            out[uid] = "its week asks too much"
    return out


def sure_ones(sugg):
    """[(date id, tag path)] for Add the sure ones."""
    return [(uid, x[0]) for uid, xs in sugg.items() for x in xs if x[2]]


# ---- a follower's today ----

def today_date(doc, today):
    """The date whose window has today in it (opens ≤ today ≤ due), else the next one ahead, else None."""
    us = sorted(P.units(doc), key=lambda u: str(u.get("opens") or ""))
    now = [u for u in us if str(u.get("opens")) <= today <= str(u.get("due") or u.get("opens"))]
    if now:
        return now[-1], True
    nxt = next((u for u in us if str(u.get("opens")) > today), None)
    return nxt, False


def study_days(doc):
    return S.plan_days(doc)
