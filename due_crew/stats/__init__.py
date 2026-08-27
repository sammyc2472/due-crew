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
