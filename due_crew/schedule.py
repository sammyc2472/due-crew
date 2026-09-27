"""3.2 plans as training: a follower's own schedule over the author's dates.
Pure: dates, numbers and lists in, numbers out. No aqt, no collection, no
network. The glue is plan_flow.py; see docs/plans-design.md.

The author's plan says what opens and by when (a unit's window runs from
its `opens` to its `due`, or to the day before the next date opens). My
schedule (`sched`, on the server with my follow) says which days I study
and for how long: `days`, Monday first, 0 a rest day, 1 a study day, 2 a
double share; `minutes` a day; `start` when I begin later than the plan,
which moves every date of mine by the same number of days (the crew's
dates never move). A unit's cards spread over my study days in its window,
in the deck's own order. Catch-up weeks and the taper (the plan's
`phases`) open nothing new.

Everything here is cumulative and computed again each morning from the
dates, so a missed morning, another computer or a changed schedule can
never double-open: the morning opens up to today's quota and no further.
"""

import datetime
import math

REST, STUDY, DOUBLE = 0, 1, 2
CATCH_UP_DAYS = 4          # "spread them over the next 4 study days"
MISSED_SHARE = 0.25        # a study day under a quarter of its share is missed
# a new card's reviews over its first months, at typical settings: days after
# it's learned, and the chance of a lapse adding one more
CURVE = (1, 3, 7, 16, 35, 80)
LAPSE = 0.12


def d(iso):
    return datetime.date.fromisoformat(str(iso))


def iso(day):
    return day.isoformat()


def monday(day):
    return day - datetime.timedelta(days=day.weekday())


def units(doc):
    return [u for u in (doc or {}).get("units") or [] if isinstance(u, dict) and u.get("id") and u.get("opens")]


def plan_start(doc):
    us = units(doc)
    return d(min(u["opens"] for u in us)) if us else None


def shift_days(doc, sched):
    """How many days my dates run behind the plan's (0 without a later start)."""
    first = plan_start(doc)
    if not sched or not sched.get("start") or first is None:
        return 0
    return max(0, (d(sched["start"]) - first).days)


def phase(doc, day, shift=0):
    """"build", "catchup" or "taper" for my `day` (a date)."""
    ph = (doc or {}).get("phases") or {}
    first = plan_start(doc)
    plan_day = day - datetime.timedelta(days=shift)
    end = (doc or {}).get("end")
    taper = int(ph.get("taper") or 0)
    if end and taper and d(end) - datetime.timedelta(days=taper) < plan_day <= d(end):
        return "taper"
    every = int(ph.get("catchup") or 0)
    if every >= 2 and first is not None and plan_day >= first:
        week = (monday(plan_day) - monday(first)).days // 7 + 1
        if week % every == 0:
            return "catchup"
    return "build"


def weight(doc, sched, day, shift=0):
    """How much of a unit my `day` takes: 0 on a rest day, in a catch-up
    week or in the taper; 2 on a double day."""
    if phase(doc, day, shift) != "build":
        return 0
    days = (sched or {}).get("days") or [1] * 7
    return int(days[day.weekday()] or 0)


def window(doc, unit, shift=0):
    """(first, last) of a unit's window, my dates: its opens to its due, or
    to the day before the next date opens, or its opens alone."""
    start = d(unit["opens"])
    if unit.get("due"):
        last = d(unit["due"])
    else:
        later = sorted(d(u["opens"]) for u in units(doc) if d(u["opens"]) > start)
        last = later[0] - datetime.timedelta(days=1) if later else start
    delta = datetime.timedelta(days=shift)
    return start + delta, max(start, last) + delta


def _weights(doc, sched, first, last, shift):
    out, day = [], first
    while day <= last:
        out.append(weight(doc, sched, day, shift))
        day += datetime.timedelta(days=1)
    return out


def quota(doc, unit, sched, total, day, shift=None):
    """How many of the unit's `total` cards should be open (and seen) by
    the end of my `day`: cumulative, in whole cards. Without a schedule a
    unit opens whole on its first day, as in 3.1. A window with no study
    day in it opens whole on its first day too (nothing to spread over)."""
    if shift is None:
        shift = shift_days(doc, sched)
    first, last = window(doc, unit, shift)
    if day < first or total <= 0:
        return 0
    if not sched or day >= last:
        return total
    ws = _weights(doc, sched, first, last, shift)
    whole = sum(ws)
    if not whole:
        return total
    upto = sum(ws[:(day - first).days + 1])
    return min(total, math.ceil(total * upto / whole))


def share(doc, unit, sched, total, day, shift=None):
    """Today's new cards for one unit: today's quota less yesterday's."""
    return quota(doc, unit, sched, total, day, shift) - quota(doc, unit, sched, total, day - datetime.timedelta(days=1), shift)


def pick(order, open_now, want):
    """Which suspended cards to open so that `want` are open: the first
    ones in the deck's own order. `order` is [(cid, suspended)] sorted."""
    need = want - open_now
    if need <= 0:
        return []
    return [cid for cid, suspended in order if suspended][:need]


# ---- today's session, behind, the push back ----

def today_view(doc, sched, totals, seen_before, new_today, day, catch=None):
    """What the session card says for one plan. totals: {unit id: cards};
    seen_before: {unit id: seen by the start of today}; new_today: plan
    cards seen for the first time today. catch: "spread" or "leave" once
    I've answered the missed-days question. Returns {kind, target, done,
    behind, share}."""
    shift = shift_days(doc, sched)
    yesterday = day - datetime.timedelta(days=1)
    todays = behind = 0
    for u in units(doc):
        t = int(totals.get(u["id"]) or 0)
        if not t:
            continue
        todays += share(doc, u, sched, t, day, shift)
        behind += max(0, quota(doc, u, sched, t, yesterday, shift) - int(seen_before.get(u["id"]) or 0))
    extra = math.ceil(behind / CATCH_UP_DAYS) if behind and catch == "spread" else 0
    ph = phase(doc, day, shift)
    kind = ph if ph != "build" else ("rest" if weight(doc, sched, day, shift) == 0 and not todays else "study")
    return {"kind": kind, "target": todays + extra, "share": todays, "done": int(new_today),
            "behind": behind}


def missed_study_days(doc, sched, day, new_by_day, shares_by_day, back=7):
    """The study days before `day` (at most `back`, most recent first, stopping
    at the first one kept) where under a quarter of the day's share was seen.
    new_by_day and shares_by_day: {iso: n}."""
    out = []
    shift = shift_days(doc, sched)
    for i in range(1, back + 1):
        x = day - datetime.timedelta(days=i)
        want = int(shares_by_day.get(iso(x)) or 0)
        if not want or weight(doc, sched, x, shift) == 0:
            continue
        if int(new_by_day.get(iso(x)) or 0) < want * MISSED_SHARE:
            out.append(x)
        else:
            break
    return out


def pushed_start(doc, sched, days):
    """My schedule with every date `days` later, or None when that would
    run past the plan's end date."""
    first = plan_start(doc)
    if first is None or days <= 0:
        return None
    shift = shift_days(doc, sched) + days
    end = (doc or {}).get("end")
    last = max((window(doc, u, shift)[1] for u in units(doc)), default=None)
    if end and last and last > d(end):
        return None
    out = dict(sched or {"days": [1] * 7, "minutes": 60})
    out["start"] = iso(first + datetime.timedelta(days=shift))
    return out


# ---- load ahead ----

def new_per_day(doc, sched, totals, first_day, days):
    """[n] new cards the schedule opens on each of `days` days from `first_day`."""
    shift = shift_days(doc, sched)
    out = []
    for i in range(days):
        x = first_day + datetime.timedelta(days=i)
        out.append(sum(share(doc, u, sched, int(totals.get(u["id"]) or 0), x, shift)
                       for u in units(doc) if totals.get(u["id"])))
    return out


def load(new, base_due, curve=CURVE, lapse=LAPSE):
    """Expected reviews a day: what's already due (`base_due`, a list as
    long as `new` or shorter) plus the reviews the new cards bring."""
    n = len(new)
    out = [float(base_due[i]) if i < len(base_due) else 0.0 for i in range(n)]
    for day, k in enumerate(new):
        if not k:
            continue
        for gap in curve:
            if day + gap < n:
                out[day + gap] += k
        # a lapse or two along the way, spread over the first weeks
        for gap in (2, 8):
            if day + gap < n:
                out[day + gap] += k * lapse / 2
    return out


def by_week(daily, first_day):
    """[(monday iso, average a day)] over whole weeks from first_day."""
    weeks = {}
    for i, v in enumerate(daily):
        m = iso(monday(first_day + datetime.timedelta(days=i)))
        weeks.setdefault(m, []).append(v)
    return [(m, sum(vs) / len(vs)) for m, vs in sorted(weeks.items())]


def cap_reviews(minutes, secs_review, secs_new, new_a_day):
    """How many reviews a day fit in `minutes` beside the day's new cards."""
    left = minutes * 60 - new_a_day * secs_new
    return max(0, int(left / max(1.0, secs_review)))


def load_view(doc, sched, totals, today, base_due, secs_review, secs_new):
    """For the schedule dialog: {weeks: [(label, reviews a day, over)], cap,
    peak, over: [labels], new_a_day, minutes_peak}."""
    first = max(today, (plan_start(doc) or today) + datetime.timedelta(days=shift_days(doc, sched)))
    last = max((window(doc, u, shift_days(doc, sched))[1] for u in units(doc)), default=first)
    end = (doc or {}).get("end")
    if end:
        last = max(last, d(end))
    span = min(7 * 26, (last - first).days + 1 + 14)
    if span <= 0:
        return None
    new = new_per_day(doc, sched, totals, first, span)
    study = [x for x in new if x]
    new_a_day = round(sum(study) / len(study)) if study else 0
    daily = load(new, base_due[:span])
    minutes = int((sched or {}).get("minutes") or 60)
    cap = cap_reviews(minutes, secs_review, secs_new, new_a_day)
    weeks = []
    for i, (m, v) in enumerate(by_week(daily, first)):
        weeks.append((f"W{i + 1}", int(round(v)), v > cap))
    peak = max((v for _l, v, _o in weeks), default=0)
    mins_peak = int(round((peak * secs_review + new_a_day * secs_new) / 60))
    return {"weeks": weeks, "cap": cap, "peak": peak, "over": [l for l, _v, o in weeks if o],
            "new_a_day": new_a_day, "minutes_peak": mins_peak, "minutes": minutes}


# ---- the week recap ----

def plan_week(doc, day, shift=0):
    """My plan week for `day`: 1 the week my first date opens in; 0 before."""
    first = plan_start(doc)
    if first is None:
        return 0
    mine = first + datetime.timedelta(days=shift)
    if day < mine:
        return 0
    return (monday(day) - monday(mine)).days // 7 + 1
