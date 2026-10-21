"""Round five's Plan tab, what it shows worked out (docs/planner.md): the
plan's shape in one line, what each week asks (new cards a day, the
reviews it brings), the dates that need a look, a follower's today. No
suggestions of what goes on a date: the author puts every card there
(Sam's call, round five). Pure: no Anki, no Qt."""

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


def prep(doc, e):
    """The dates that prep for a quiz or exam (their `for`), reinforcement after it aside."""
    return [u for u in P.units(doc) if u.get("for") == e.get("id") and not P.reinforces(doc, u)]


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
    """{a week's Monday: {new, reviews, new_week, reviews_week, top, over,
    cap}}: new cards a study day that week (its days' new over its study
    days), reviews a day (its seven days' over seven), the two for the whole
    week, its busiest day, and whether a day of it is over the pace by a
    quarter (Work.over)."""
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
        rw = sum(rv.get(x, 0) for x in ds)
        out[mon] = {"new": -(-new // study) if new else 0, "reviews": rw / 7, "new_week": new, "reviews_week": rw,
                    "top": top, "over": bool(cap) and top > cap * 1.25, "cap": cap}
    return out


def week_words(ask):
    """"9 new, 34 reviews a day", or the amber "41 new a day (over your 20), 52 reviews"."""
    if not ask:
        return "", False
    r = B.about(ask["reviews"])
    if ask["over"]:
        return f"{ask['top']:,} new a day (over your {ask['cap']:,}), {r} reviews", True
    if not ask["new"] and r == "0":
        return "", False
    return f"{ask['new']:,} new, {r} reviews a day", False


def peak(asks):
    """(week n from 1, reviews a day) of the busiest week, or None."""
    best = None
    for i, (_mon, a) in enumerate(sorted(asks.items())):
        if best is None or a["reviews"] > best[1]:
            best = (i + 1, a["reviews"])
    return best if best and best[1] >= 5 else None


def shape_line(doc, tree, pace, asks):
    """The plan's shape, label by label: [("Dates", "Mon 12 Oct – Block 2
    exam, Fri 13 Nov"), ("Study days", "Mon–Fri"), ("New a day", "20"),
    ("Reviews peak", "~115 a day, week 5"), ("Last days", "3 with no new
    cards"), ("Catch-up", "every 4th week")]."""
    parts = []
    start = B.plan_start(doc, "")
    ev, end = ends_with(doc)
    if start or end:
        a = P.fmt_day(start) if start else "Not started"
        last = B.last_day(doc)
        b = (f"{ev.get('name') or 'the exam'}, {P.fmt_day(end)}" if ev else P.fmt_day(end) if end
             else f"{P.fmt_day(last)}, no end set" if last else "no end set")
        parts.append(("Dates", f"{a} – {b}"))
    parts.append(("Study days", days_words(pace.get("days"))))
    cap = cap_of(doc, tree, pace)
    if pace.get("mode") != "placed" and cap:  # placed: each date's own cards, nothing to say
        parts.append(("New a day", f"{cap:,}" + (", to fit the end" if pace.get("mode") == "end" else "")))
    pk = peak(asks)
    if pk:
        parts.append(("Reviews peak", f"~{B.about(pk[1])} a day, week {pk[0]}"))
    ph = doc.get("phases") or {}
    if ph.get("taper"):
        n = int(ph["taper"])
        parts.append(("Last days", f"{n} with no new cards"))
    if ph.get("catchup"):
        n = int(ph["catchup"])
        parts.append(("Catch-up", f"every {n}{'st' if n == 1 else 'nd' if n == 2 else 'rd' if n == 3 else 'th'} week"))
    return parts


def needs_look(doc, counts, asks):
    """{date id: why}: a date with no cards here, one in a week over the pace."""
    out = {}
    for u in P.units(doc):
        uid = u["id"]
        if counts.get(uid) == 0:
            out[uid] = "no cards here yet"
        elif (asks.get(monday(u.get("opens"))) or {}).get("over"):
            out[uid] = "its week asks too much"
    return out


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
