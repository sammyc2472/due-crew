"""Paste-ready shares for the group chat. Pure text: no network, no
collection access — callers hand in numbers and hourly review counts.

Grammar (decided with Sam, 2026-09-02): emoji tapes where people are the
point, block sparklines for shape, `░` always means an idle hour. Effort
stats sit above the visual, identity stats (🔥 streak, 🎯 retention)
below, and every share signs off with the add-on code. Names go on the
clipboard as plain text — still sanitized to one bounded line.

Truthfulness rules (v1.10):
- Counts are REVIEWS (answer events; a card answered twice counts twice),
  never "cards".
- A day is the Anki day: 24 hourly slots starting at the rollover hour
  (4 AM by default), so a 1 AM session belongs to the day it ended.
- The crew tape is one shared timeline: every friend's hours are placed by
  absolute time onto the viewer's day, so "we covered N hours" counts
  distinct clock hours, not a merge of different local clocks.
- Missing is never zero: friends who don't share hours are counted, not
  drawn; a total that excludes hidden counts says "(partial)".
"""

from .board import _fmt_time

FOOTER = "— Due Crew · Anki add-on 2035408484"
SQUARES = ("⬜", "🟨", "🟩")
BARS = "▁▂▃▄▅▆▇█"
SOLID_HOUR = 15   # reviews in one hour that read as a real block (🟩)
NAME_MAX = 24
HOUR = 3600


def hour_levels(hourly):
    """24 hourly counts -> 24 intensity levels (0 idle, 1 a few, 2 solid)."""
    out = []
    for n in (hourly or [0] * 24)[:24]:
        n = int(n or 0)
        out.append(0 if n <= 0 else 2 if n >= SOLID_HOUR else 1)
    return (out + [0] * 24)[:24]


def levels_str(levels):
    return "".join(str(int(l)) for l in levels)


def levels_from_str(s):
    """A friend's uploaded hours string -> levels, or None if malformed."""
    if not isinstance(s, str) or len(s) != 24 or any(c not in "012" for c in s):
        return None
    return [int(c) for c in s]


def project_levels(levels, their_start, my_start):
    """Place a friend's day (24 levels from THEIR day start, epoch seconds)
    onto MY day window. Slots outside my window are dropped — they belong
    to a different day of mine. Both starts are absolute, so time zones
    and rollover settings fall out naturally."""
    out = [0] * 24
    if levels is None or their_start is None or my_start is None:
        return out
    offset = (int(their_start) - int(my_start)) // HOUR
    for i, level in enumerate(levels[:24]):
        j = i + offset
        if 0 <= j < 24 and level:
            out[j] = max(out[j], int(level))
    return out


def tape_rows(levels):
    """Personal tape: two rows of 12 hourly squares — the first and second
    half of the Anki day (🌅 rollover..+11h, 🌙 +12h..+23h)."""
    sq = [SQUARES[l] for l in levels]
    return "".join(sq[:12]), "".join(sq[12:])


def crew_row(levels):
    """Crew tape: 12 two-hour slots, each the brighter of its hour pair."""
    return "".join(SQUARES[max(levels[i], levels[i + 1])]
                   for i in range(0, 24, 2))


def sparkline(hourly):
    """24 hourly counts as one skyline: ░ idle, ▁..█ scaled to the day's peak."""
    counts = [max(0, int(n or 0)) for n in (hourly or [])][:24]
    counts += [0] * (24 - len(counts))
    peak = max(counts) or 1
    return "".join("░" if n == 0 else BARS[min(7, round(7 * n / peak))]
                   for n in counts)


def clean_name(name):
    one_line = " ".join(str(name).split())
    text = "".join(ch for ch in one_line if ch.isprintable())
    return (text[:NAME_MAX - 1] + "…") if len(text) > NAME_MAX else text or "?"


def _stat_lines(reviews, time_ms, streak, retention):
    top = f"Today 📚 {int(reviews):,} reviews · {_fmt_time(int(time_ms or 0))}"
    bottom = f"🔥{int(streak or 0)}"
    if retention is not None:
        bottom += f" · 🎯 {float(retention):.1f}%"
    return top, bottom


def my_today_tape(reviews, time_ms, streak, retention, hourly):
    top, bottom = _stat_lines(reviews, time_ms, streak, retention)
    am, pm = tape_rows(hour_levels(hourly))
    return "\n".join([top, f"🌅 {am}", f"🌙 {pm}", bottom, FOOTER])


def my_today_spark(reviews, time_ms, streak, retention, hourly):
    top, bottom = _stat_lines(reviews, time_ms, streak, retention)
    return "\n".join([top, f"🕐 {sparkline(hourly)}", bottom, FOOTER])


def crew_today(server, rows, reviews, partial=False, unshared=0):
    """rows: [(name, levels24)] ALREADY projected onto the viewer's day, for
    everyone whose hours are known. Ordered by who started first — the day
    as a story. `unshared` = people who studied today but don't share
    hours (they are counted, never drawn as idle); `partial` = the review
    total excludes someone's hidden count. None when nobody has a row."""
    active = [(n, lv) for n, lv in rows if lv and any(lv)]
    if not active:
        return None
    active.sort(key=lambda r: (next(i for i, l in enumerate(r[1]) if l),
                               clean_name(r[0]).lower()))
    covered = sum(1 for h in range(24) if any(lv[h] for _n, lv in active))
    lines = [f"{server} today 🕐"]
    lines += [f"{crew_row(lv)} {clean_name(n)}" for n, lv in active]
    unit = "hour" if covered == 1 else "hours"
    total = f"{int(reviews):,} reviews" + (" (partial)" if partial else "")
    tail = f"we covered {covered} {unit} · {total}"
    if unshared:
        tail += f" · {unshared} not sharing hours"
    lines.append(tail)
    lines.append(FOOTER)
    return "\n".join(lines)
