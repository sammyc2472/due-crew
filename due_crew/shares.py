"""Clipboard shares built from local stats and the cached board: my day,
my week, the crew's week. Text comes from share.py; this module gathers."""

import datetime
import traceback

from aqt import mw
from aqt.utils import tooltip

from . import board
from .app import _profile_files, _state, cfg, client
from .backend.firebase import away_on
from .stats import gather_stats
from .stats.queries import StatsQueries
from .ui import copy_text

def _share(kind):
    """Main thread (collection access + clipboard). Builds one of the
    paste-ready shares from local stats and the cached board."""
    if not mw.col:
        return
    from . import share
    q = StatsQueries(mw.col)
    try:
        stats = gather_stats(mw.col, _profile_files())
    except Exception:
        traceback.print_exc()
        return
    labels = list(_state["labels"]) or [q.day_label(i) for i in range(7)]
    if kind == "sharetoday":
        text = share.my_today(labels[0], stats.reviews, stats.time_ms,
                              stats.accuracy, stats.streak)
    elif kind == "shareweek":
        text = _my_week_text(q, stats, labels)
    else:
        text = _crew_week_text(q, stats, labels)
        if text is None:
            tooltip("No one in the crew has studied this week yet.")
            return
    copy_text(text)
    tooltip("Copied.")


def _my_week(q, labels):
    """(flags oldest->today, reviews, time_ms) for the last 7 days, from
    the local revlog — always fresh, never waiting on a sync. A day inside
    my away spell that I didn't study reads "away", not missed."""
    c = cfg()
    studied = q.studied_days_ago(7)
    flags = []
    for ago in range(6, -1, -1):
        lb = labels[ago] if ago < len(labels) else q.day_label(ago)
        flags.append(True if ago in studied
                     else ("away" if away_on(lb, c) else False))
    reviews = sum(q.reviews_for_day(i) for i in range(7))
    time_ms = sum(q.study_time_ms_for_day(i) for i in range(7))
    return flags, reviews, time_ms


def _my_week_text(q, stats, labels):
    from . import share
    flags, reviews, time_ms = _my_week(q, labels)
    return share.my_week(list(reversed(labels[:7])), flags, reviews, time_ms,
                         stats.streak)


def _day_flag(doc):
    """True (studied), "away" (flagged, no answers), or False."""
    if board._showed(doc):
        return True
    return "away" if (doc or {}).get("away") else False


def _as_of(last_updated, labels):
    """'Tue' when a friend's last sync is older than yesterday — their later
    squares are unknown, not empty. '' otherwise."""
    try:
        dt = datetime.datetime.fromisoformat(str(last_updated).replace("Z", "+00:00"))
        day = dt.astimezone().date().isoformat()
    except Exception:
        return ""
    if len(labels) > 1 and day < labels[1]:
        return datetime.date.fromisoformat(day).strftime("%a")
    return ""


def _crew_week_text(q, stats, labels):
    """My row from local revlog (fresh); friends' rows from their uploaded
    days. Absence is silent: no row without at least one studied day."""
    from . import share
    week = list(reversed(labels[:7]))  # oldest -> today
    rows, reviews, time_ms = [], 0, 0
    for e in _state["entries"] or []:
        if e.get("paused"):
            continue
        if e["you"]:
            flags, r, t = _my_week(q, labels)
            rows.append((e["name"], flags, "", e.get("emoji") or ""))
            reviews += r
            time_ms += t
            continue
        days = e.get("days") or {}
        flags = [_day_flag(days.get(lb)) for lb in week]
        agg = board._week_row(days, labels) or {}
        reviews += int(agg.get("reviews") or 0)
        time_ms += int(agg.get("time_ms") or 0)
        rows.append((e["name"], flags, _as_of(e.get("last_updated"), labels),
                     e.get("emoji") or ""))
    if not rows:
        flags, r, t = _my_week(q, labels)
        rows.append((client().display_name or "Me", flags, ""))
        reviews, time_ms = r, t
    label = str(cfg().get("crew_label") or "Crew").strip() or "Crew"
    return share.crew_week(label, week, rows, reviews, time_ms)
