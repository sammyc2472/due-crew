"""Paste-ready shares for the group chat. Pure text: no network, no
collection access — callers hand in day flags and numbers.

Grammar (v2.1, simplified with Sam): the unit is a DAY. A week is seven
squares (🟩 studied, ⬜ not), one row per person; today is one honest
line of numbers. Effort first, identity (🔥 streak, 🎯 retention) last,
and every share signs off with the add-on code. Names go on the clipboard
as plain text — still sanitized to one bounded line.

Truthfulness: counts are REVIEWS (answer events); a crewmate who hasn't
synced since mid-week is marked "as of <day>" rather than drawn absent;
nobody gets a row of empty squares (absence is silent).
"""

import datetime as _dt

from .board import _fmt_time

FOOTER = "— Due Crew · Anki add-on 2035408484"
ON, OFF, AWAY = "🟩", "⬜", "✈️"
NAME_MAX = 24


def clean_name(name):
    one_line = " ".join(str(name).split())
    text = "".join(ch for ch in one_line if ch.isprintable())
    return (text[:NAME_MAX - 1] + "…") if len(text) > NAME_MAX else text or "?"


def _date(label):
    try:
        return _dt.date.fromisoformat(str(label))
    except (TypeError, ValueError):
        return None


def day_text(label):
    """'Sep 9' from an ISO label; '' when unparsable."""
    d = _date(label)
    return f"{d:%b} {d.day}" if d else ""


def date_range(labels_oldest_first):
    """'Sep 1–7' or 'Aug 30 – Sep 5' from the first and last ISO labels."""
    if not labels_oldest_first:
        return ""
    a, b = _date(labels_oldest_first[0]), _date(labels_oldest_first[-1])
    if not a or not b:
        return ""
    if a.month == b.month:
        return f"{a:%b} {a.day}–{b.day}"
    return f"{a:%b} {a.day} – {b:%b} {b.day}"


def week_squares(flags):
    """flags: True (studied), "away", or anything else (nothing)."""
    return "".join(ON if f is True else AWAY if f == "away" else OFF
                   for f in flags)


def _studied(flags):
    return sum(1 for f in flags if f is True)


def my_today(label, reviews, time_ms, retention, streak):
    head = "Today" + (f" · {day_text(label)}" if day_text(label) else "")
    stats = f"📚 {int(reviews):,} reviews · ⏱ {_fmt_time(int(time_ms or 0))}"
    if retention is not None:
        stats += f" · 🎯 {float(retention):.1f}%"
    stats += f" · 🔥 {int(streak or 0)}"
    return "\n".join([head, stats, FOOTER])


def my_week(labels_oldest_first, flags, reviews, time_ms, streak):
    n = _studied(flags)
    head = "This week" + (f" · {date_range(labels_oldest_first)}"
                         if date_range(labels_oldest_first) else "")
    return "\n".join([
        head,
        f"{week_squares(flags)} {n} of {len(flags)} days",
        f"{int(reviews):,} reviews · {_fmt_time(int(time_ms or 0))} · 🔥 {int(streak or 0)}",
        FOOTER])


def crew_week(label, labels_oldest_first, rows, reviews, time_ms):
    """rows: [(name, flags7, as_of)] — flags are True / "away" / False;
    as_of is '' or a weekday ('Tue') meaning the person's last sync was
    that day, so later squares are unknown, not empty. Only people with
    at least one studied day get a row, most days first, then by name.
    None when nobody has a row."""
    active = [r for r in rows if _studied(r[1])]
    if not active:
        return None
    active.sort(key=lambda r: (-_studied(r[1]), clean_name(r[0]).lower()))
    head = str(label or "Crew") + (f" · {date_range(labels_oldest_first)}"
                                   if date_range(labels_oldest_first) else "")
    lines = [head]
    for row in active:
        name, flags, as_of = row[0], row[1], row[2]
        emoji = row[3] if len(row) > 3 and row[3] else ""
        line = f"{week_squares(flags)} {emoji + ' ' if emoji else ''}{clean_name(name)}"
        if as_of:
            line += f" · as of {as_of}"
        lines.append(line)
    lines.append(f"{int(reviews):,} reviews · {_fmt_time(int(time_ms or 0))} together")
    lines.append(FOOTER)
    return "\n".join(lines)


def squad_today(name, label, rows, studying, reviews):
    """rows: [(name, emoji, reviews)] for people who studied today, best
    first; the top three are named. None when nobody has."""
    if not rows:
        return None
    head = clean_name(name) + (f" · {day_text(label)}" if day_text(label) else "")
    who = " · ".join(f"{(e + ' ') if e else ''}{clean_name(n)} {int(r or 0):,}"
                     for n, e, r in rows[:3])
    return "\n".join([
        head,
        f"{int(studying):,} studying · {int(reviews):,} reviews together",
        f"🟩 {who}",
        FOOTER])


MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")


def month_name(key):
    """'September' from '2026-09'."""
    try:
        return MONTHS[int(str(key)[5:7]) - 1]
    except (ValueError, IndexError):
        return str(key)


def _ret(review):
    r = review.get("retention")
    return f" · 🎯 {float(r):.1f}%" if r is not None else ""


def my_month(review, name, so_far=False):
    """Personal. review: period_review(); name: 'September'. None when the
    month has no reviews."""
    if not review or not review.get("reviews"):
        return None
    best = review.get("best_day")
    lines = [f"My {name}" + (" so far" if so_far else ""),
             f"{int(review['reviews']):,} reviews · {_fmt_time(int(review['time_ms'] or 0))}"
             f" · {int(review['days'])} of {int(review['span'])} days"]
    if best:
        lines.append(f"best day {day_text(best[0])} ({int(best[1]):,})" + _ret(review))
    elif _ret(review):
        lines.append(_ret(review)[3:])
    lines.append(FOOTER)
    return "\n".join(lines)


def my_year(review, year, so_far=False):
    """Personal. Exact from the revlog, so even months before the add-on
    count. None when the year has no reviews."""
    if not review or not review.get("reviews"):
        return None
    lines = [f"My {year}" + (" so far" if so_far else ""),
             f"{int(review['reviews']):,} reviews · {_fmt_time(int(review['time_ms'] or 0))}"
             f" · {int(review['days'])} of {int(review['span'])} days"]
    bm, bd = review.get("best_month"), review.get("best_day")
    bits = []
    if bm:
        bits.append(f"best month {month_name(bm[0])} ({int(bm[1]):,})")
    if bd:
        bits.append(f"best day {day_text(bd[0])} ({int(bd[1]):,})")
    if bits:
        lines.append(" · ".join(bits))
    run = int(review.get("longest_run") or 0)
    tail = (f"🔥 longest run {run} days" if run > 1 else "") + _ret(review)
    if tail.startswith(" · "):
        tail = tail[3:]
    if tail:
        lines.append(tail)
    lines.append(FOOTER)
    return "\n".join(lines)
