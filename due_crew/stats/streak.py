"""Streak = consecutive days with at least one answered card.

The backward base (through yesterday) is one SQL pass over revlog, cached
per day; after that each call costs a single query to check whether today
counts yet. Not studying today never breaks the streak until rollover.
"""

import json
import os


class StreakTracker:
    def __init__(self, queries, user_files_dir):
        self.q = queries
        self.path = os.path.join(user_files_dir, "streak.json")

    def current(self):
        today = self.q.day_label(0)
        cached = self._load()
        if cached.get("date") == today:
            base = cached.get("base", 0)
        else:
            base = self._base_through_yesterday()
            self._save({"date": today, "base": base})
        return base + (1 if self.q.reviews_for_day(0) > 0 else 0)

    def _base_through_yesterday(self):
        days = self.q.studied_days_ago()
        base = 0
        day = 1
        while day in days:
            base += 1
            day += 1
        return base

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
