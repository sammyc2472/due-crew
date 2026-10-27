"""3.9.5, How you study, the glue (habits.py is pure): Insights' line and
view, Slow but right's cards (for Before your exam), and the Fifteen at 35. Mine alone: worked out here from my own Anki log,
never sent (no request, no account key, nothing on the server).

The log is read once per Anki day (and again after an hour while Insights
is open): one query, the last 8 weeks of revlog over every deck, on the
main thread; worked out off it (a big log takes a second or two; a small
one, a few milliseconds, right there), and dropped if the profile or
account changed meanwhile (app.generation).

Slow but right: the cards whose latest review answer, in the last 7 days,
was right but took 1.5 to 3 times their usual; not suspended, buried or in
a filtered deck already. Since 3.9.5's FSRS rule, a finding with See them,
not a deck: with an exam set, the ones in its scope join Before your exam
(due_flow.supers). Never sent.

The Fifteen at 35: only for someone whose long-sittings finding passes.
While reviewing, at each card, the sitting going on (answers 10 minutes
apart at most) is read from the log since its last answer; past 35
minutes, with no Fifteen or room running and not waved off this sitting,
the top bar's ▶ Fifteen? says "35 min in · Take five" (rooms.take_five).
Main thread."""

import time
import traceback

from aqt import mw

from . import app
from . import habits as H
from .app import _state, cfg

STALE = 3600         # seconds: Insights open works it out again after an hour
LOOK_BACK_MS = 4 * 3600000  # the sitting going on, read from at most this far back
INLINE_ROWS = 2000   # a log this small is worked out right here (about 30 ms); a bigger one off the main thread


def _pf():
    from . import plan_flow
    return plan_flow


def _mine():
    """This profile's and account's runtime state (a new generation: none)."""
    m = _state.get("habits")
    if not isinstance(m, dict) or m.get("gen") != app.generation:
        m = _state["habits"] = {"gen": app.generation}
    return m


def _now_ms():
    return int(time.time() * 1000)


# ---- the log, once a day ----

def result():
    """The log as last worked out (any day), or None."""
    return _mine().get("res")


def check(insights=False):
    """Work it out once per Anki day; with Insights open, again once it's
    an hour old. The read is here, the sums off the main thread."""
    if not mw.col:
        return
    m = _mine()
    if m.get("busy"):
        return
    try:
        cutoff = int(mw.col.sched.day_cutoff)
    except Exception:
        return
    if m.get("day") == cutoff and not (insights and time.time() - float(m.get("at") or 0) > STALE):
        return
    m["day"], m["at"] = cutoff, time.time()
    try:
        rows = mw.col.db.all("SELECT id, cid, ease, ivl, lastIvl, time, type FROM revlog WHERE id >= ? ORDER BY id",
                             (cutoff - H.WEEKS * 7 * 86400) * 1000)
    except Exception:
        traceback.print_exc()
        return
    gen = app.generation

    def job():
        return H.work_out(rows, cutoff)

    def done(res, draw=True):
        if app.generation != gen:
            return  # another profile or account now
        m2 = _mine()
        m2["busy"] = False
        if not res:
            return
        was = m2.get("res")
        m2["res"], m2["live"] = res, None
        if draw and _seen(was) != _seen(res) and app.swap and app.board_up():
            app.swap(cfg())

    if len(rows) < INLINE_ROWS:
        try:
            done(job(), draw=False)  # a few weeks of a light log: milliseconds, and the board drawing now has it
        except Exception:
            traceback.print_exc()
        return
    m["busy"] = True
    app._bg(job, done)


def _seen(res):
    """What the board would show of it: a redraw only when that changed."""
    if not res:
        return None
    return (res.get("span", 0) >= H.VIEW_DAYS, res["matured"]["n"], (res.get("speed") or {}).get("pass"),
            (res.get("sit") or {}).get("pass"), len(res.get("slow") or []))


# ---- Slow but right ----

def slow_now():
    """The Slow but right cards as the collection is now: not suspended,
    buried or in a filtered deck; slowest first. [] while the finding
    doesn't pass. Kept till the collection changes."""
    res = result()
    if not res or not mw.col or not res.get("slow") or not (res.get("speed") or {}).get("pass"):
        return []
    try:
        mod = int(mw.col.mod)
    except Exception:
        mod = None
    m = _mine()
    live = m.get("live")
    if live and live[0] == mod:
        return list(live[1])
    cids = list(res["slow"])
    ok = set()
    try:
        for k in range(0, len(cids), 500):
            ids = ",".join(str(int(c)) for c in cids[k:k + 500])
            ok |= set(mw.col.db.list(f"SELECT id FROM cards WHERE id IN ({ids}) AND queue >= 0 AND odid = 0"))
    except Exception:
        traceback.print_exc()
        return []
    out = [c for c in cids if c in ok]
    m["live"] = (mod, out)
    return list(out)


def see_slow():
    """See them: Slow but right's cards, in Anki's browser."""
    _pf()._browse(slow_now(), empty="None right now.")


def see_matured():
    """See them: this week's matured cards, in Anki's browser."""
    res = result()
    _pf()._browse((res or {}).get("matured", {}).get("cids") or [], empty="None matured this week yet.")


# ---- the board ----

def board_view():
    """What Insights draws (board._habits_html, its line): habits.summary
    and whether the view is open; None under two weeks of log, or before
    it's worked out."""
    check(insights=True)
    res = result()
    if not res or int(res.get("span") or 0) < H.VIEW_DAYS:
        return None
    out = H.summary(res, len(slow_now()))
    out["open"] = bool(_mine().get("open"))
    return out


def open_view(on=True):
    _mine()["open"] = bool(on)
    if app.swap:
        app.swap(cfg())


def shut():
    """Insights itself (a deck picked, or Insights opened from elsewhere)."""
    _mine()["open"] = False


def on_message(act):
    """inshabits:<deck>:<act>: open, shut, see, slow (See them). True when handled."""
    if act == "open":
        open_view(True)
    elif act == "shut":
        open_view(False)
    elif act == "see":
        see_matured()
    elif act == "slow":
        see_slow()
    else:
        return False
    return True


# ---- the Fifteen at 35 ----

def _sitting():
    """[start, last] (ms) of the sitting going on, read from the log since
    its last answer (at most LOOK_BACK_MS back); None when none is."""
    now = _now_ms()
    m = _mine()
    s = m.get("sit")
    if not s or now - s[1] > LOOK_BACK_MS:
        s, since = None, now - LOOK_BACK_MS
    else:
        since = s[1]
    rows = mw.col.db.all("SELECT id, time FROM revlog WHERE id > ? AND ease > 0 ORDER BY id", since)
    s = H.fold_sitting(s, rows)
    m["sit"] = s
    return s


def sit_chip():
    """Whether the top bar says "35 min in · Take five" now: reviewing, my
    long-sittings finding passes, and the sitting going on is past 35
    minutes (since it began, or since the last Fifteen or room), not waved
    off. rooms.refresh_widgets asks only when no Fifteen or room runs."""
    try:
        if mw.state != "review" or not mw.col:
            return False
        res = result()
        if not res or not (res.get("sit") or {}).get("pass"):
            return False
        m = _mine()
        return H.sit_due(_sitting(), _now_ms(), m.get("floor") or 0, m.get("sit_x"))
    except Exception:
        traceback.print_exc()
        return False


def hold_sitting():
    """A Fifteen or a room is running: the 35 minutes count from its end."""
    _mine()["floor"] = _now_ms()


def dismiss_sit():
    """× on the chip: not again this sitting."""
    m = _mine()
    s = m.get("sit")
    m["sit_x"] = s[0] if s else None
