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
ON, OFF = "🟩", "⬜"
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
    return "".join(ON if f else OFF for f in flags)


def my_today(label, reviews, time_ms, retention, streak):
    head = "Today" + (f" · {day_text(label)}" if day_text(label) else "")
    stats = f"📚 {int(reviews):,} reviews · ⏱ {_fmt_time(int(time_ms or 0))}"
    if retention is not None:
        stats += f" · 🎯 {float(retention):.1f}%"
    stats += f" · 🔥 {int(streak or 0)}"
    return "\n".join([head, stats, FOOTER])


def my_week(labels_oldest_first, flags, reviews, time_ms, streak):
    n = sum(1 for f in flags if f)
    head = "This week" + (f" · {date_range(labels_oldest_first)}"
                         if date_range(labels_oldest_first) else "")
    return "\n".join([
        head,
        f"{week_squares(flags)} {n} of {len(flags)} days",
        f"{int(reviews):,} reviews · {_fmt_time(int(time_ms or 0))} · 🔥 {int(streak or 0)}",
        FOOTER])


def crew_week(label, labels_oldest_first, rows, reviews, time_ms):
    """rows: [(name, flags7, as_of)] — as_of is '' or a weekday ('Tue')
    meaning the person's last sync was that day, so later squares are
    unknown, not empty. Only people with at least one day get a row,
    most days first, then by name. None when nobody has a row."""
    active = [(n, f, a) for n, f, a in rows if any(f)]
    if not active:
        return None
    active.sort(key=lambda r: (-sum(1 for f in r[1] if f), clean_name(r[0]).lower()))
    head = str(label or "Crew") + (f" · {date_range(labels_oldest_first)}"
                                   if date_range(labels_oldest_first) else "")
    lines = [head]
    for name, flags, as_of in active:
        line = f"{week_squares(flags)} {clean_name(name)}"
        if as_of:
            line += f" · as of {as_of}"
        lines.append(line)
    lines.append(f"{int(reviews):,} reviews · {_fmt_time(int(time_ms or 0))} together")
    lines.append(FOOTER)
    return "\n".join(lines)
