"""3.9.9, Know when it breaks: errs.py's glue. The open profile's counts
(user_files/<profile>/errs.json, beside wrap.json), Privacy's switch ("Send
Sam what went wrong", the account's send_errs), the sync's part, and See
what went (a sheet: exactly what the next sync sends).

Main thread, but for what a count sets off (errs.after: a save, a few
seconds on, on the main thread) and errs_sent, from the push's thread."""

import os
import time

from aqt import mw

from . import app, errs
from .errs import wanted as on
from .words import later

FILE = "errs.json"
SAVE_MS = 10000   # a count is on disk this long after, at most
FLY_SECS = 90     # a push has a day's counts this long before another sync may take them
_save = {"due": False}
_flying = {}      # day -> when a push took its counts (two syncs at once never both send it)


def open_profile():
    """profile_did_open: this profile's file; what was counted before it
    opened joins it (with the switch on)."""
    before = errs.current()
    before.save()
    t = errs.Tally(os.path.join(app._profile_files(), FILE))
    yes = on(app.cfg())
    if yes and before.path is None:
        t.merge(before)
    _flying.clear()
    errs.use(t, on=yes)
    use_ready()
    errs.after(_soon)
    t.save()


def close_profile():
    """profile_will_close: on disk; what comes after counts for the next one."""
    errs.current().save()
    _flying.clear()
    errs.use(errs.Tally(), on=on(app.cfg()))


def switched(yes):
    """The switch, turned (Settings › Privacy): off, what's kept goes too."""
    errs.switch(yes)
    errs.current().save()


def _soon():
    """After a count, from any thread: saved a few seconds on, on the main thread."""
    if _save["due"]:
        return
    _save["due"] = True

    def arm():
        from aqt.qt import QTimer
        QTimer.singleShot(SAVE_MS, flush)
    try:
        mw.taskman.run_on_main(arm)
    except Exception:
        _save["due"] = False


def flush():
    _save["due"] = False
    errs.current().save()


def _today():
    """Today, as Anki counts it; told to errs, so a count from any thread
    lands on the right day."""
    try:
        from .stats.queries import StatsQueries
        errs.set_day(mw.col.sched.day_cutoff, StatsQueries(mw.col).day_label(0))
    except Exception:
        pass
    return errs.today()


def _sending(c):
    """(errs part or None, why none goes): what the next sync would carry."""
    if not on(c):
        return None, "Nothing goes: Send what went wrong, and what gets used is off."
    cl = app.client()
    if not cl.signed_in:
        return None, "Nothing goes while you're signed out."
    if cl.session.get("errs_ok") is not True:
        return None, "Nothing yet: Due Crew's server doesn't take them yet."
    return errs.part(errs.current(), _today(), app.ADDON_VERSION), ""


def for_sync(c):
    """At each sync: {errs, errs_sent} for the push, or {}. The days that
    are over, once; off, nothing (and nothing kept)."""
    errs.switch(on(c))
    part, _why = _sending(c)
    t = errs.current()
    t.save()
    now = time.time()
    if part:
        part["days"] = {d: v for d, v in part["days"].items() if now - _flying.get(d, 0) > FLY_SECS}
    if not part or not part["days"]:
        return {}
    days = list(part["days"])
    for d in days:
        _flying[d] = now

    def sent():
        t.drop(days)
        for d in days:
            _flying.pop(d, None)
        _soon()
    return {"errs": part, "errs_sent": sent}


def see_what_went():
    """Settings › Privacy's See what went: a sheet with what the next sync
    sends, exactly (or why nothing goes)."""
    from . import sheets
    c = app.cfg()
    errs.switch(on(c))
    part, why = _sending(c)
    sheets.confirm(errs.SHEET_TITLE, errs.sheet_text(part, why), "OK", lambda: None)


# ---- 3.9.9: what gets used, said once ----
# A line at the board's foot (board.draw._use_line; Sam, of the sheet it was first: "a bit dramatic a
# pop-up... a little note somewhere"), there until Got it or its Privacy link is pressed. Nothing is
# counted before that.

TOLD = "use_told"
NOTE = later("New: Due Crew counts which of its parts get opened, as totals with no account on them.")  # said with t() where it's drawn


def use_ready(c=None):
    """Tell errs whether uses count: the switch on and the person told."""
    c = app.cfg() if c is None else c
    errs.use_ok(on(c) and bool(c.get(TOLD)))


def note_due(c):
    """The board's line is still to be put away."""
    return bool(on(c) and not c.get(TOLD))


def told():
    """Got it, or the line's way to Privacy: said, so uses count from here."""
    c = app.cfg()
    if not c.get(TOLD):
        c[TOLD] = True
        app.save_cfg(c)
        try:
            from . import account
            account.push(c)
        except Exception:
            pass
    use_ready(c)
