"""3.9.0: your Wrapped, the glue (wrapped.py is the story; board.wrapped_html
draws it in the board's place). One grouped query over the year's reviews
(an hour a row, so a busy year is a few thousand rows), the counts this
computer keeps for the year (closet_flow.year_counts), the closet, and the
card I turned around, its front read here and never sent or put on the
picture. Nothing in it is sent.

Main thread: the collection and the config. No network.
"""

import datetime
import html
import re
import traceback

from aqt import mw

from . import closet, closet_flow, wrapped
from .app import _state, cfg

CARD_KEY = "wrapped_card"  # per computer: the card I turned around, on its slide (on unless turned off there)


def _today_end(col):
    """(the Anki day today, the day after it: the cutoff's date)."""
    cut = int(col.sched.day_cutoff)
    end = datetime.date.fromtimestamp(cut)
    return end - datetime.timedelta(days=1), end, cut


def year_rows(col, year):
    """({Anki day: (reviews, new cards met, ms)}, {hour: reviews}) for a
    year, read in one query grouped by the hour before the day's cutoff (as
    the closet reads its days). A new card met is its first answer (a learn
    with no interval before it)."""
    today, end, cut = _today_end(col)
    y0, y1 = datetime.date(int(year), 1, 1), datetime.date(int(year), 12, 31)
    if y0 > today:
        return {}, {}
    lo = cut - 86400 * ((today - y0).days + 1)
    hi = cut - 86400 * max(0, (today - y1).days)
    rows = col.db.all("SELECT CAST((? - id / 1000) / 3600 AS INTEGER), COUNT(*), "
                      "SUM(CASE WHEN type = 0 AND lastIvl = 0 THEN 1 ELSE 0 END), SUM(time) FROM revlog "
                      "WHERE ease > 0 AND id >= ? AND id < ? GROUP BY 1", cut - 1, lo * 1000, hi * 1000)
    days, hours = {}, {}
    for h, k, new, ms in rows or []:
        h = int(h)
        d = (end - datetime.timedelta(days=h // 24 + 1)).isoformat()
        r = days.setdefault(d, [0, 0, 0])
        r[0] += int(k or 0)
        r[1] += int(new or 0)
        r[2] += int(ms or 0)
        hr = datetime.datetime.fromtimestamp(cut - (h + 1) * 3600).hour
        hours[hr] = hours.get(hr, 0) + int(k or 0)
    return {d: tuple(v) for d, v in days.items()}, hours


def first_day(col):
    """The Anki day of my first review ever, or None."""
    first = col.db.scalar("SELECT MIN(id) FROM revlog WHERE ease > 0")
    if not first:
        return None
    _today, end, cut = _today_end(col)
    h = max(0, (cut - 1 - int(first) // 1000) // 3600)
    return (end - datetime.timedelta(days=h // 24 + 1)).isoformat()


def years(col):
    """The years with reviews in them, newest first (Anki's history can go
    back years before Due Crew)."""
    lo, hi = col.db.first("SELECT MIN(id), MAX(id) FROM revlog WHERE ease > 0") or (None, None)
    if not lo:
        return []
    a = datetime.date.fromtimestamp(int(lo) / 1000).year
    b = max(datetime.date.fromtimestamp(int(hi) / 1000).year, a)
    return list(range(b, a - 1, -1))[:12]


def _plain(text):
    """A card's side as one plain line: no markup, no media, no styling."""
    text = re.sub(r"(?is)<(style|script)\b.*?</\1>", " ", text or "")
    text = re.sub(r"\[sound:[^\]]*\]", " ", text)
    text = re.sub(r"(?i)<br\s*/?>|</(div|p|li)>", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def turned(col):
    """(how many leeches are turned around, the one turned furthest: {front,
    lapses, ivl} or None). Its front is read from my own collection, here."""
    where = f"lapses >= {wrapped.TURNED_LAPSES} AND type = 2 AND ivl >= {wrapped.TURNED_IVL} AND queue >= 0"
    count = int(col.db.scalar(f"SELECT COUNT() FROM cards WHERE {where}") or 0)
    if not count:
        return 0, None
    row = col.db.first(f"SELECT id, lapses, ivl FROM cards WHERE {where} ORDER BY lapses DESC, ivl DESC LIMIT 1")
    try:
        front = _plain(col.get_card(int(row[0])).question())
    except Exception:
        traceback.print_exc()
        front = ""
    return count, ({"front": front[:wrapped.FRONT_MAX], "lapses": int(row[1]), "ivl": int(row[2])} if front else None)


def view(year=None):
    """Wrapped's view for the board (board.wrapped_html): {year, years,
    slides, heat, look}. Main thread."""
    col = mw.col
    c = cfg()
    today, _end, _cut = _today_end(col)
    year = int(year or wrapped.default_year(today))
    days, hours = year_rows(col, year)
    f = wrapped.facts(year, today, days, hours, first_day(col))
    n_turned, card = turned(col) if f["days"] else (0, None)
    look = closet_flow.look(c)
    names = {k: t["name"] for k, t in closet.BY.items()}
    try:
        rollover = int(col.get_config("rollover", 4) or 0)
    except Exception:
        rollover = 4
    crew = len([e for e in _state.get("entries") or [] if not e.get("you")])
    slides = wrapped.slides(f, closet_flow.year_counts(year), closet_flow.have(c) if c.get("sev", True) else {},
                            [names[k] for k in closet.shown(look)], crew,
                            card if c.get(CARD_KEY, True) else None, n_turned, rollover, names)
    return {"year": year, "years": years(col), "slides": slides, "heat": wrapped.heat(f), "look": look,
            "card": bool(card), "card_on": bool(c.get(CARD_KEY, True))}


def banner(today, c=None):
    """The board's line, 1 December to 15 January, until the x (for the
    year, on every computer: the account's wrapped_seen): {year, so_far,
    look} or None."""
    c = c or cfg()
    y = wrapped.banner_year(today)
    if not y or str(c.get("wrapped_seen") or "") == str(y):
        return None
    return {"year": y, "so_far": str(today) <= f"{y}-12-31", "look": closet_flow.look(c) if c.get("sev", True) else []}
