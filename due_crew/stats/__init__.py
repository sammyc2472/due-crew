import datetime as _dt
from dataclasses import dataclass
from typing import Optional

from .queries import StatsQueries
from .streak import StreakTracker


@dataclass
class UserStats:
    reviews: int
    time_ms: int
    accuracy: Optional[float]  # None until the first answer of the day
    streak: int


def gather_stats(col, user_files_dir):
    """Runs on the main thread (collection access); cheap, local SQL only."""
    q = StatsQueries(col)
    correct, total = q.accuracy_today()
    return UserStats(
        reviews=q.reviews_for_day(0),
        time_ms=q.study_time_ms_today(),
        accuracy=(correct / total * 100) if total else None,
        streak=StreakTracker(q, user_files_dir).current(),
    )


def duet_runs(my_days, their_days, today_label):
    """(current, best) runs of consecutive days BOTH studied, from two sets
    of ISO day labels. Like a streak, today still counting is a bonus, not a
    requirement: a current run measured through yesterday hasn't broken."""
    both = my_days & their_days
    if not both:
        return 0, 0
    try:
        day = _dt.date.fromisoformat(today_label)
    except (TypeError, ValueError):
        return 0, 0
    if today_label not in both:
        day -= _dt.timedelta(days=1)
    current = 0
    while day.isoformat() in both:
        current += 1
        day -= _dt.timedelta(days=1)
    best = run = 0
    prev = None
    for lb in sorted(both):
        d = _dt.date.fromisoformat(lb)
        run = run + 1 if prev is not None and (d - prev).days == 1 else 1
        best = max(best, run)
        prev = d
    return current, best


def week_days(q):
    """How many of the last 7 days (today included) had at least one answer.
    The squad board's "Week" column: one honest int, no per-day docs."""
    return len({d for d in q.studied_days_ago(7) if 0 <= d <= 6})


def period_review(q, start, end):
    """Everything a personal month or year review says, from one revlog pass
    over the days `start`..`end` (dates, inclusive; the end is clamped to
    today). None when the range is empty. Numbers are the person's own,
    exact even for months before the add-on was installed."""
    today = _dt.date.fromisoformat(q.day_label(0))
    end = min(end, today)
    if end < start:
        return None
    totals = q.daily_totals((today - start).days + 1)
    lo, hi = start.isoformat(), end.isoformat()
    per_day = {lb: v for lb, v in totals.items() if lo <= lb <= hi and v[0]}
    reviews = sum(v[0] for v in per_day.values())
    graded = sum(v[3] for v in per_day.values())
    correct = sum(v[2] for v in per_day.values())
    months = {}
    for lb, v in per_day.items():
        months[lb[:7]] = months.get(lb[:7], 0) + v[0]
    run = best_run = 0
    prev = None
    for lb in sorted(per_day):
        d = _dt.date.fromisoformat(lb)
        run = run + 1 if prev is not None and (d - prev).days == 1 else 1
        best_run = max(best_run, run)
        prev = d
    # ties go to the earliest day/month: max() keeps the first of equals
    best_day = max(sorted(per_day.items()), key=lambda kv: kv[1][0], default=None)
    best_month = max(sorted(months.items()), key=lambda kv: kv[1], default=None)
    return {"start": start, "end": end,
            "reviews": reviews,
            "time_ms": sum(v[1] for v in per_day.values()),
            "days": len(per_day),
            "span": (end - start).days + 1,
            "best_day": (best_day[0], best_day[1][0]) if best_day else None,
            "best_month": best_month,
            "longest_run": best_run,
            "retention": (correct / graded * 100) if graded else None}


WEEK_WINDOW = 60  # bounds the per-sync scan; runs older than this are rare


def gather_week(col, user_files_dir, days=7):
    """Per-day payloads for days 1..days-1 ago (today rides upload_today),
    studied days only — the server's week must not depend on which days a
    sync happened to run. Main thread; the scan is bounded, so this stays
    cheap per sync even on huge collections. Streaks that reach back through
    yesterday splice onto the tracker's cached full-history base."""
    q = StatsQueries(col)
    studied = q.studied_days_ago(WEEK_WINDOW)
    base = StreakTracker(q, user_files_dir).base()
    out = []
    for ago in range(1, days):
        if ago not in studied:
            continue  # nothing to say: absence of a doc reads as "no answers"
        if ago <= base:
            streak = base - ago + 1  # inside the unbroken run to yesterday
        else:
            streak = 0
            day = ago
            while day in studied:  # a short, already-broken run
                streak += 1
                day += 1
        correct, total = q.accuracy_for_day(ago)
        out.append({
            "label": q.day_label(ago),
            "reviews": q.reviews_for_day(ago),
            "time_ms": q.study_time_ms_for_day(ago),
            "accuracy": (correct / total * 100) if total else None,
            "streak": streak,
        })
    return out
