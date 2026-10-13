"""Clipboard shares built from local stats and the cached board: my day,
my week, the crew's week. Text comes from share.py; this module gathers."""

import datetime
import traceback

from aqt import mw
from aqt.utils import tooltip

from . import app, board
from .app import _bg, _profile_files, _state, cfg, client
from .backend.shapes import away_on
from .stats import gather_stats, period_review
from .stats.queries import StatsQueries
from .ui import copy_text
from .wrap import _wrap_data

def _share(kind):
    """Main thread (collection access + clipboard). Builds one of the
    paste-ready shares from local stats and the cached board."""
    if not mw.col:
        return
    from . import share
    q = StatsQueries(mw.col)
    try:
        stats = gather_stats(mw.col, _profile_files())
    except Exception:
        traceback.print_exc()
        return
    labels = list(_state["labels"]) or [q.day_label(i) for i in range(7)]
    if kind == "sharetoday":
        text = share.my_today(labels[0], stats.reviews, stats.time_ms,
                              stats.accuracy, stats.streak, stats.new_cards)
    elif kind == "shareweek":
        text = _my_week_text(q, stats, labels)
    elif kind in ("sharemonth", "monthcopy"):
        text = _month_text(q, last=(kind == "monthcopy"))
        if text is None:
            tooltip("No reviews that month.")
            return
    elif kind in ("shareyear", "yearcopy"):
        text = _year_text(q, complete=(kind == "yearcopy"))
        if text is None:
            tooltip("No reviews that year.")
            return
    else:
        text = _crew_week_text(q, stats, labels)
        if text is None:
            tooltip("No one in the crew has studied this week yet.")
            return
    copy_text(text)
    tooltip("Copied.")


def _my_week(q, labels):
    """(flags Monday->today, reviews, time_ms) for THIS calendar week, from
    the local revlog — always fresh, never waiting on a sync. Only days that
    have happened get a square, so an unfinished week never shows tomorrow as
    missed. A day inside my away spell that I didn't study reads "away"."""
    c = cfg()
    days = len(board.week_labels(labels)) or 1      # Monday..today
    studied = q.studied_days_ago(7)
    totals = q.daily_totals(days)                    # one pass
    flags = []
    for ago in range(days - 1, -1, -1):
        lb = labels[ago] if ago < len(labels) else q.day_label(ago)
        flags.append(True if ago in studied
                     else ("away" if away_on(lb, c) else False))
    reviews = sum(v[0] for v in totals.values())
    time_ms = sum(v[1] for v in totals.values())
    return flags, reviews, time_ms


def _my_week_text(q, stats, labels):
    from . import share
    flags, reviews, time_ms = _my_week(q, labels)
    week = board.week_labels(labels)
    try:
        new_cards = sum(q.new_cards_by_day(len(week) or 1).values())
    except Exception:
        new_cards = None
    return share.my_week(list(reversed(week)), flags, reviews,
                         time_ms, stats.streak, new_cards)


def _day_flag(doc):
    """True (studied), "away" (flagged, no answers), or False."""
    if board._showed(doc):
        return True
    return "away" if (doc or {}).get("away") else False


def _as_of(last_updated, labels):
    """'Tue' when a friend's last sync is older than yesterday — their later
    squares are unknown, not empty. '' otherwise."""
    try:
        dt = datetime.datetime.fromisoformat(str(last_updated).replace("Z", "+00:00"))
        day = dt.astimezone().date().isoformat()
    except Exception:
        return ""
    if len(labels) > 1 and day < labels[1]:
        return datetime.date.fromisoformat(day).strftime("%a")
    return ""


def _crew_week_text(q, stats, labels):
    """My row from local revlog (fresh); friends' rows from their uploaded
    days. Absence is silent: no row without at least one studied day."""
    from . import share
    this_week = board.week_labels(labels)
    week = list(reversed(this_week))  # Monday -> today
    rows, reviews, time_ms = [], 0, 0
    for e in _state["entries"] or []:
        if e.get("paused"):
            continue
        if e["you"]:
            flags, r, t = _my_week(q, labels)
            rows.append((e["name"], flags, "", e.get("emoji") or ""))
            reviews += r
            time_ms += t
            continue
        days = e.get("days") or {}
        flags = [_day_flag(days.get(lb)) for lb in week]
        agg = board._week_row(days, this_week) or {}
        reviews += int(agg.get("reviews") or 0)
        time_ms += int(agg.get("time_ms") or 0)
        rows.append((e["name"], flags, _as_of(e.get("last_updated"), labels),
                     e.get("emoji") or ""))
    if not rows:
        flags, r, t = _my_week(q, labels)
        rows.append((client().display_name or "Me", flags, ""))
        reviews, time_ms = r, t
    label = str(cfg().get("crew_label") or "Crew").strip() or "Crew"
    if cfg().get("show_up"):
        reviews = time_ms = None  # squares only
    return share.crew_week(label, week, rows, reviews, time_ms)


# ---- personal month and year reviews (revlog only, nothing shared) ----

def _month_bounds(today, last=False):
    """(first, last, name) for this month, or the previous one."""
    first = today.replace(day=1)
    if last:
        end = first - datetime.timedelta(days=1)
        first = end.replace(day=1)
    else:
        nxt = (first + datetime.timedelta(days=32)).replace(day=1)
        end = nxt - datetime.timedelta(days=1)
    return first, end, first.strftime("%B")


def _month_text(q, last=False):
    from . import share
    today = datetime.date.fromisoformat(q.day_label(0))
    first, end, name = _month_bounds(today, last)
    review = period_review(q, first, end)
    return share.my_month(review, name, so_far=(not last and today < end))


def _year_text(q, complete=False):
    from . import share
    today = datetime.date.fromisoformat(q.day_label(0))
    year = today.year - 1 if (complete and today.month == 1) else today.year
    review = period_review(q, datetime.date(year, 1, 1), datetime.date(year, 12, 31))
    so_far = not complete and today < datetime.date(year, 12, 31)
    return share.my_year(review, year, so_far=so_far)


_review_cache = {"label": None, "banners": {}}


def review_banners():
    """Banners for the board, from the local revlog: last month's review
    during the first week of a month, the year's from Dec 20 to Jan 7.
    Each is dismissable (wrap.json) and computed once per day."""
    if not mw.col:
        return {}
    q = StatsQueries(mw.col)
    label = q.day_label(0)
    w = _wrap_data()
    if _review_cache["label"] != label:
        today = datetime.date.fromisoformat(label)
        banners = {}
        if today.day <= 7:
            first, end, name = _month_bounds(today, last=True)
            review = period_review(q, first, end)
            if review and review["reviews"]:
                banners["month"] = {"key": first.strftime("%Y-%m"), "name": name,
                                    "review": review}
        if (today.month == 12 and today.day >= 20) or (today.month == 1 and today.day <= 7):
            year = today.year if today.month == 12 else today.year - 1
            review = period_review(q, datetime.date(year, 1, 1), datetime.date(year, 12, 31))
            if review and review["reviews"]:
                banners["year"] = {"key": str(year), "review": review}
        _review_cache.update(label=label, banners=banners)
    out = {}
    for kind, info in _review_cache["banners"].items():
        if w.get(f"{kind}_dismissed") != info["key"]:
            out[kind] = info
    return out


def dismiss_review(kind):
    info = _review_cache["banners"].get(kind)
    if info:
        _wrap_data()[f"{kind}_dismissed"] = info["key"]
        from .wrap import _save_wrap
        _save_wrap()


# ---- 3.8.0: Share › As a picture, made here (sharecard.py) ----

LATE_DAYS = 31  # a phone's reviews can arrive this late: read again each time


def _log_days(q):
    """{day: (reviews, time_ms)} for every day I answered a card: the
    whole revlog the first time a session asks (the one big read; about
    a second for millions of reviews), then the last month again, which
    a phone's late sync can still change. Main thread."""
    cache = _state.get("pic_log") or {}
    if cache.get("gen") == app.generation and cache.get("days") is not None:
        recent = q.daily_totals(LATE_DAYS)
        cut = q.day_label(LATE_DAYS - 1)
        days = {lb: v for lb, v in cache["days"].items() if lb < cut}
    else:
        first = mw.col.db.scalar("SELECT MIN(id) FROM revlog WHERE ease > 0")
        if not first:
            return {}
        span = max(1, (q._cutoff_s() - int(first) // 1000) // 86400 + 1)
        try:
            from aqt.qt import QApplication, Qt
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            wait = QApplication
        except ImportError:  # the suite's Qt has no cursor
            wait = None
        try:
            recent = q.daily_totals(span)
        finally:
            if wait is not None:
                wait.restoreOverrideCursor()
        days = {}
    days.update({lb: (n, t) for lb, (n, t, _c, _g) in recent.items() if n})
    _state["pic_log"] = {"gen": app.generation, "days": days}
    return days


def _crew_with_me(span):
    """How many of my crew studied on any of these days (never who)."""
    return sum(1 for e in _state["entries"] or [] if not e.get("you")
               and any(board._showed((e.get("days") or {}).get(lb)) for lb in span))


def picture(kind):
    """The footer's Share › As a picture: the card made here (it opened
    duecrew.com before). My day and week start from my Privacy switches;
    my year and all time count my crew's cheers with one request."""
    if not mw.col:
        return
    from . import sharecard as S
    from .ui.share_card_dialog import ShareCardDialog
    q = StatsQueries(mw.col)
    try:
        days = _log_days(q)
        today = q.day_label(0)
    except Exception:
        traceback.print_exc()
        return
    c = cfg()
    if kind in ("picturetoday", "pictureweek"):
        one = kind == "picturetoday"
        try:
            stats = gather_stats(mw.col, _profile_files())
            fresh = q.new_cards_by_day(7)
        except Exception:
            traceback.print_exc()
            return
        span = [today] if one else list(reversed(board.week_labels(list(_state["labels"]) or [q.day_label(i) for i in range(7)])))
        from .rooms import sev_on  # 3.8.1: Sev hops across it, as Settings › Sev says
        d = S.week(days, today, one, fresh, stats.streak, _crew_with_me(span), sev_on())
        mon = (datetime.date.fromisoformat(today) - datetime.timedelta(days=datetime.date.fromisoformat(today).weekday())).isoformat()
        card = {"kind": "today" if one else "week", "title": "Share today" if one else "Share my week",
                "sizes": ("story", "link"), "file": f"due-crew-{today}" if one else f"due-crew-week-{mon}", "data": d}
        dlg = ShareCardDialog(mw, lambda _k: card, priv=S.privacy(c), tooltip=tooltip)
    else:
        cheers = {"by": None}  # {year: n} once counted
        signed = client().signed_in

        def choose(k):
            by = cheers["by"]
            if k == "all":
                total = sum(by.values()) if by is not None else None
                return {"kind": "alltime", "title": "Share my Anki, all time", "sizes": ("story", "link"),
                        "file": "due-crew-all-time", "data": S.alltime(days, today, total)}
            return {"kind": "year", "title": "Share my year", "sizes": ("story",), "file": f"due-crew-{k}",
                    "data": S.year(days, k, today, (by or {}).get(str(k), 0) if by is not None else None)}
        if not days:
            tooltip("No reviews yet.")
            return
        dlg = ShareCardDialog(mw, choose, S.year_options(days, today), "all" if kind == "picturealltime" else today[:4],
                              tooltip=tooltip, cheers_say="counting…" if signed else "sign in to count")
        if signed:
            gen, cl = app.generation, client()

            def done(by):
                if gen != app.generation or _state.get("share_card") is not dlg:
                    return
                dlg.cheers_say = "couldn't count"
                if by is not None:
                    cheers["by"] = by
                dlg.refresh()
            _bg(cl.cheer_counts, done)
    _state["share_card"] = dlg  # kept while it's open
    dlg.show()
