"""Paste-ready shares for the group chat. Pure text: no network, no
collection access — callers hand in numbers and 24 hourly review counts.

Grammar (decided with Sam, 2026-09-02): emoji tapes where people are the
point, block sparklines for shape, `░` always means an idle hour. Effort
stats sit above the visual, identity stats (🔥 streak, 🎯 retention)
below, and every share signs off with the add-on code. Names go on the
clipboard as plain text — still sanitized to one bounded line.
"""

from .board import _fmt_time

FOOTER = "— Due Crew · Anki add-on 2035408484"
SQUARES = ("⬜", "🟨", "🟩")
BARS = "▁▂▃▄▅▆▇█"
SOLID_HOUR = 15   # cards in one hour that read as a real block (🟩)
NAME_MAX = 24


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


def tape_rows(levels):
    """Personal tape: two rows of 12 hourly squares (🌅 0–11, 🌙 12–23)."""
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


def _stat_lines(cards, time_ms, streak, retention):
    top = f"Today 📚 {int(cards):,} cards · {_fmt_time(int(time_ms or 0))}"
    bottom = f"🔥{int(streak or 0)}"
    if retention is not None:
        bottom += f" · 🎯 {float(retention):.1f}%"
    return top, bottom


def my_today_tape(cards, time_ms, streak, retention, hourly):
    top, bottom = _stat_lines(cards, time_ms, streak, retention)
    am, pm = tape_rows(hour_levels(hourly))
    return "\n".join([top, f"🌅 {am}", f"🌙 {pm}", bottom, FOOTER])


def my_today_spark(cards, time_ms, streak, retention, hourly):
    top, bottom = _stat_lines(cards, time_ms, streak, retention)
    return "\n".join([top, f"🕐 {sparkline(hourly)}", bottom, FOOTER])


def crew_today(server, rows, cards):
    """rows: [(name, levels24)] for everyone who studied today (absence is
    silent). Ordered by who started first — the day as a story. Returns
    None when nobody has a row yet."""
    active = [(n, lv) for n, lv in rows if lv and any(lv)]
    if not active:
        return None
    active.sort(key=lambda r: (next(i for i, l in enumerate(r[1]) if l),
                               clean_name(r[0]).lower()))
    covered = sum(1 for h in range(24) if any(lv[h] for _n, lv in active))
    lines = [f"{server} today 🕐"]
    lines += [f"{crew_row(lv)} {clean_name(n)}" for n, lv in active]
    unit = "hour" if covered == 1 else "hours"
    lines.append(f"we covered {covered} {unit} · {int(cards):,} cards")
    lines.append(FOOTER)
    return "\n".join(lines)
