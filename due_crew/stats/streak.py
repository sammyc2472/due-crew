"""Streak = consecutive days with at least one answered card.

The backward base (through yesterday) is one bounded SQL pass over revlog,
cached per day; after that each call costs a single query to check whether today
counts yet. Not studying today never breaks the streak until rollover.
"""

import json
import os


class StreakTracker:
    def __init__(self, queries, user_files_dir):
        self.q = queries
        self.path = os.path.join(user_files_dir, "streak.json")

    def base(self):
        """Consecutive studied days ending yesterday; one full revlog pass
        per day, cached after that."""
        today = self.q.day_label(0)
        cached = self._load()
        if cached.get("date") == today:
            return cached.get("base", 0)
        base = self._base_through_yesterday()
        self._save({"date": today, "base": base})
        return base

    def current(self):
        return self.base() + (1 if self.q.reviews_for_day(0) > 0 else 0)

    def _base_through_yesterday(self):
        """The run back from yesterday, scanned over a window that widens only
        while the run reaches its edge. Until 2.9 this read the whole history
        every day: 210 ms on the main thread at 1.1 million reviews."""
        window = 64
        while True:
            days = self.q.studied_days_ago(None if window > 40000 else window)
            base = 0
            day = 1
            while day in days:
                base += 1
                day += 1
            if day < window or window > 40000:
                return base  # the run ended inside the window: exact
            window *= 4

    def _load(self):
        try:
            with open(self.path) as f:
                return json.load(f)
        except Exception:
            return {}

    def _save(self, data):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w") as f:
                json.dump(data, f)
        except OSError:
            pass
