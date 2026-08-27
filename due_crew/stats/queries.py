"""Revlog queries. Day bounds follow Anki's rollover hour (default 4 AM),
and only actual answers count (ease > 0) — manual scheduling operations like
Set Due Date write ease-0 revlog rows and must not inflate reviews or
streaks."""

import datetime


class StatsQueries:
    def __init__(self, col):
        self.col = col

    def _cutoff_s(self):
        return int(self.col.sched.day_cutoff)

    def day_bounds_ms(self, days_ago=0):
        end = (self._cutoff_s() - days_ago * 86400) * 1000
        return end - 86400000, end

    def day_label(self, days_ago=0):
        start, _ = self.day_bounds_ms(days_ago)
        return datetime.date.fromtimestamp(start / 1000).isoformat()

    def reviews_for_day(self, days_ago=0):
        start, end = self.day_bounds_ms(days_ago)
        return self.col.db.scalar(
            "SELECT COUNT(*) FROM revlog WHERE id >= ? AND id < ? AND ease > 0",
            start, end) or 0

    def study_time_ms_today(self):
        start, end = self.day_bounds_ms(0)
        return self.col.db.scalar(
            "SELECT SUM(time) FROM revlog WHERE id >= ? AND id < ? AND ease > 0",
            start, end) or 0

    def accuracy_today(self):
        """(correct, total) over learn/review/relearn answers; Again = incorrect."""
        start, end = self.day_bounds_ms(0)
        row = self.col.db.first(
            "SELECT COUNT(CASE WHEN ease > 1 THEN 1 END), COUNT(*) FROM revlog "
            "WHERE id >= ? AND id < ? AND ease > 0 AND type IN (0, 1, 2)",
            start, end)
        if not row:
            return 0, 0
        return row[0] or 0, row[1] or 0

    def studied_days_ago(self):
        """Set of days-ago ints (0 = today) that have at least one answer.
        One query, however long the history."""
        cutoff = self._cutoff_s()
        rows = self.col.db.list(
            "SELECT DISTINCT CAST((? - id / 1000) / 86400 AS INTEGER) "
            "FROM revlog WHERE ease > 0 AND id < ?",
            cutoff - 1, cutoff * 1000)
        return set(rows or [])
