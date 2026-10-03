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
        """The Anki day `days_ago` before today, as a date: the day before
        the cutoff's date. Counted in dates, not 86400s, so a 23- or 25-hour
        day (DST) with rollover at midnight still names the right day."""
        cutoff = datetime.date.fromtimestamp(self._cutoff_s())
        return (cutoff - datetime.timedelta(days=days_ago + 1)).isoformat()

    def reviews_for_day(self, days_ago=0):
        start, end = self.day_bounds_ms(days_ago)
        return self.col.db.scalar(
            "SELECT COUNT(*) FROM revlog WHERE id >= ? AND id < ? AND ease > 0",
            start, end) or 0

    def study_time_ms_for_day(self, days_ago=0):
        start, end = self.day_bounds_ms(days_ago)
        return self.col.db.scalar(
            "SELECT SUM(time) FROM revlog WHERE id >= ? AND id < ? AND ease > 0",
            start, end) or 0

    def study_time_ms_today(self):
        return self.study_time_ms_for_day(0)

    def accuracy_for_day(self, days_ago=0):
        """(correct, total) over learn/review/relearn answers; Again = incorrect."""
        start, end = self.day_bounds_ms(days_ago)
        row = self.col.db.first(
            "SELECT COUNT(CASE WHEN ease > 1 THEN 1 END), COUNT(*) FROM revlog "
            "WHERE id >= ? AND id < ? AND ease > 0 AND type IN (0, 1, 2)",
            start, end)
        if not row:
            return 0, 0
        return row[0] or 0, row[1] or 0

    def accuracy_today(self):
        return self.accuracy_for_day(0)

    def studied_days_ago(self, max_days=None):
        """Set of days-ago ints (0 = today) that have at least one answer.
        One query; `max_days` bounds it to an index range scan so per-sync
        callers stay cheap on huge collections."""
        cutoff = self._cutoff_s()
        start_ms = 0 if max_days is None else (cutoff - max_days * 86400) * 1000
        rows = self.col.db.list(
            "SELECT DISTINCT CAST((? - id / 1000) / 86400 AS INTEGER) "
            "FROM revlog WHERE ease > 0 AND id >= ? AND id < ?",
            cutoff - 1, start_ms, cutoff * 1000)
        return set(rows or [])

    def daily_totals(self, days, skip=0):
        """{day_label: (answers, time_ms, correct, graded)} for the last
        `days` days (the `skip` newest left out: the history import reads a
        year further back each time). One query; graded = learn/review/
        relearn answers, the ones retention is measured on."""
        cutoff = self._cutoff_s()
        start_ms = (cutoff - (days + skip) * 86400) * 1000
        rows = self.col.db.all(
            "SELECT CAST((? - id / 1000) / 86400 AS INTEGER), COUNT(*), SUM(time), "
            "COUNT(CASE WHEN ease > 1 AND type IN (0, 1, 2) THEN 1 END), "
            "COUNT(CASE WHEN type IN (0, 1, 2) THEN 1 END) "
            "FROM revlog WHERE ease > 0 AND id >= ? AND id < ? GROUP BY 1",
            cutoff - 1, start_ms, (cutoff - skip * 86400) * 1000)
        return {self.day_label(int(ago)): (int(n), int(t or 0), int(c or 0), int(g or 0))
                for ago, n, t, c, g in rows or []}

    def new_cards_by_day(self, days, skip=0):
        """{day_label: n} for the last `days` days: cards whose first answer
        ever fell on that day. Each card counts once, on its first day; a
        card seen before is a review, even relearned. One pass over the
        window's answers, each checking revlog's card index for an earlier
        one (2.13)."""
        cutoff = self._cutoff_s()
        start_ms = (cutoff - (days + skip) * 86400) * 1000
        rows = self.col.db.all(
            "SELECT CAST((? - r.id / 1000) / 86400 AS INTEGER), COUNT(DISTINCT r.cid) "
            "FROM revlog r WHERE r.ease > 0 AND r.id >= ? AND r.id < ? AND NOT EXISTS "
            "(SELECT 1 FROM revlog p WHERE p.cid = r.cid AND p.ease > 0 AND p.id < r.id) "
            "GROUP BY 1", cutoff - 1, start_ms, (cutoff - skip * 86400) * 1000)
        return {self.day_label(int(ago)): int(n) for ago, n in rows or []}

    def first_seen(self, days):
        """{cid: days ago} for cards whose first answer ever fell in the last
        `days` days (0 = today). 3.2's plan card counts a plan's new cards
        by day from it."""
        cutoff = self._cutoff_s()
        start_ms = (cutoff - days * 86400) * 1000
        rows = self.col.db.all(
            "SELECT r.cid, CAST((? - MIN(r.id) / 1000) / 86400 AS INTEGER) FROM revlog r "
            "WHERE r.ease > 0 AND r.id >= ? AND r.id < ? AND NOT EXISTS "
            "(SELECT 1 FROM revlog p WHERE p.cid = r.cid AND p.ease > 0 AND p.id < ?) GROUP BY r.cid",
            cutoff - 1, start_ms, cutoff * 1000, start_ms)
        return {int(c): int(a) for c, a in rows or []}

    def pace(self, days=30):
        """(seconds a review, seconds a new card on its first day) over the
        last `days`: what turns cards into minutes. Typical values until
        there's enough to go on."""
        cutoff = self._cutoff_s()
        start_ms = (cutoff - days * 86400) * 1000
        rev = self.col.db.first(
            "SELECT SUM(time), COUNT(*) FROM revlog WHERE ease > 0 AND type IN (1, 2) AND id >= ?", start_ms)
        learn = self.col.db.first(
            "SELECT SUM(time), COUNT(DISTINCT cid) FROM revlog WHERE ease > 0 AND type = 0 AND id >= ?", start_ms)
        secs_review = (rev[0] / rev[1] / 1000) if rev and rev[1] and rev[1] >= 50 else 8.0
        secs_new = (learn[0] / learn[1] / 1000) if learn and learn[1] and learn[1] >= 20 else 30.0
        return max(2.0, min(60.0, secs_review)), max(5.0, min(300.0, secs_new))

    def answers_in_days(self, first, last):
        """Answers on the days `first` to `last - 1` ago, the span
        heatmap_counts(last) keeps once `first` days have settled: one count
        over an id range, to check a cache still holds."""
        cutoff = self._cutoff_s()
        return self.col.db.scalar(
            "SELECT COUNT(*) FROM revlog WHERE ease > 0 AND id >= ? AND id < ?",
            (cutoff - last * 86400) * 1000, (cutoff - first * 86400) * 1000) or 0

    def heatmap_counts(self, days=182):
        """{day_label: answer_count} for the last `days` days. One query."""
        cutoff = self._cutoff_s()
        start_ms = (cutoff - days * 86400) * 1000
        rows = self.col.db.all(
            "SELECT CAST((? - id / 1000) / 86400 AS INTEGER), COUNT(*) "
            "FROM revlog WHERE ease > 0 AND id >= ? AND id < ? "
            "GROUP BY 1", cutoff - 1, start_ms, cutoff * 1000)
        return {self.day_label(int(ago)): int(n) for ago, n in rows or []}
