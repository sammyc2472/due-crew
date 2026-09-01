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
