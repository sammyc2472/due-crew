"""The year's facts (3.9.0, your Wrapped; since 3.9.10 the scrapbook's year
page reads them, and the slide story is gone). Pure: no aqt.

My own year from Anki's review history: days, reviews, the longest run,
the times away and back. Nothing is sent. Days are Anki days (after the
rollover hour), as everywhere.
"""

import datetime as _dt

BANNER = ((12, 1), (1, 15))  # the board's line for it: 1 December to 15 January


def _date(v):
    if isinstance(v, _dt.date):
        return v
    try:
        return _dt.date.fromisoformat(str(v))
    except ValueError:
        return None


def banner_year(today):
    """The year the board's line is for, 1 December to 15 January; None the rest of the year."""
    t = _date(today)
    if t is None:
        return None
    if (t.month, t.day) >= BANNER[0]:
        return t.year
    if (t.month, t.day) <= BANNER[1]:
        return t.year - 1
    return None


# ---- the year's facts ----

def facts(year, today, days, hours=None, first_ever=None):
    """What a year of reviews says. days: {ISO day: (reviews, new cards met,
    ms)} (other years' are ignored); hours: {hour 0-23: reviews} for the
    year; first_ever: the first day of any review at all."""
    y0, y1, t = _date(f"{int(year)}-01-01"), _date(f"{int(year)}-12-31"), _date(today)
    end = min(t, y1)
    rows = {d: v for d, v in ((_date(k), v) for k, v in (days or {}).items())
            if d and y0 <= d <= end and v and int(v[0] or 0) > 0}
    studied = sorted(rows)
    first = _date(first_ever) if first_ever else None
    out = {"year": int(year), "today": t, "end": end, "so_far": t <= y1, "days": len(studied),
           "reviews": sum(int(v[0]) for v in rows.values()), "new": sum(int(v[1] or 0) for v in rows.values()),
           "ms": sum(int(v[2] or 0) for v in rows.values()), "met": first if first and y0 <= first <= y1 else None,
           "studied": [d.isoformat() for d in studied], "per_day": {d.isoformat(): int(rows[d][0]) for d in studied}, "hours": {int(h): int(c) for h, c in (hours or {}).items() if int(c) > 0}}
    start = max(y0, out["met"] or y0)
    out["elapsed"] = max(0, (end - start).days + 1)
    # the steadiest month: the most days, the earlier on a tie
    months = {}
    for d in studied:
        months[d.month] = months.get(d.month, 0) + 1
    out["months"] = months
    if len(months) >= 3:
        m = max(sorted(months), key=lambda k: months[k])
        last = (_dt.date(int(year) + (m == 12), m % 12 + 1, 1) - _dt.timedelta(days=1))
        out["steadiest"] = (m, months[m], last.day if end >= last else 0)
    # runs: the longest, and the one going now (today not yet studied keeps yesterday's alive)
    best, run, prev, run_from = (0, None, None), 0, None, None
    for d in studied:
        if prev and (d - prev).days == 1:
            run += 1
        else:
            run, run_from = 1, d
        if run > best[0]:
            best = (run, run_from, d)
        prev = d
    out["run"] = best
    alive = studied and (end - studied[-1]).days <= (1 if end == t else 0)
    out["now"] = run if alive else 0
    # coming back: 7 days or more away, then a day studied
    backs = []
    for a, b in zip(studied, studied[1:]):
        gap = (b - a).days - 1
        if gap >= 7:
            after = sum(1 for d in studied if d >= b)
            backs.append({"gap": gap, "day": b, "after": after, "span": (end - b).days + 1})
    out["backs"] = backs
    return out
