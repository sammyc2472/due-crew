"""Streak = consecutive days with at least one answered card.

The backward base (through yesterday) is one bounded SQL pass over revlog,
cached per day; after that each call costs a single query to check whether today
counts yet. Not studying today never breaks the streak until rollover.

2.11.1: phone reviews arrive when Anki syncs, often after the day's first
count. Until then a day studied only on the phone looked like a day off, and
the short run was cached for the rest of the day. Now the cache watches the
gap (the day just before the run): once a sync fills it, the run is counted
again. And a run the tracker has seen is kept: yesterday's streak, today
included, is the floor for today's base, so a late or partial history can't
shorten what was already counted.
"""

import json
import os


class StreakTracker:
    def __init__(self, queries, user_files_dir):
        self.q = queries
        self.path = os.path.join(user_files_dir, "streak.json")

    def base(self):
        """Consecutive studied days ending yesterday; one bounded revlog pass
        per day, cached after that, and again whenever a sync fills the gap."""
        today = self.q.day_label(0)
        cached = self._load()
        kept = 0
        if cached.get("date") == today:
            kept = _int(cached.get("base"))
            # the day before the run: still empty means nothing that
            # arrived since can lengthen it (one day, one indexed count)
            if self.q.reviews_for_day(kept + 1) == 0:
                return kept
        seen = cached.get("seen") if isinstance(cached.get("seen"), dict) else {}
        if seen.get("day") == self.q.day_label(1):
            kept = max(kept, _int(seen.get("run")))  # what I counted yesterday stands
        base = max(self._base_through_yesterday(), kept)
        self._save(dict(cached, date=today, base=base))
        return base

    def current(self):
        base = self.base()
        if self.q.reviews_for_day(0) == 0:
            return base
        run = base + 1
        cached = self._load()
        if cached.get("seen") != {"day": self.q.day_label(0), "run": run}:
            self._save(dict(cached, seen={"day": self.q.day_label(0), "run": run}))
        return run

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


def _int(value):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0
