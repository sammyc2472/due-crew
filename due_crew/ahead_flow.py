"""3.9.2, Reviews ahead, the glue (ahead.py is pure): Insights' chart of
the next six weeks of a deck, its choices about new cards, the pause one
of them asks for, the board's line when reviews climb, and the track
record (the forecast against my own past). Mine alone, never sent.

Queries: once per Anki day a deck, its log (LOOK days, today left out)
and each card's first answer: the habits, the curve and my pace come from
them and keep all day. Each time Insights is worked out, the cards as
they are now (their next due day) and today's counts. The track record
reads further back (BACK) once a week, worked out off the main thread.

The pause ("Stop new cards", Do it): this profile's plans.json
(`new_off`, {deck id: {kind, at, exam}}), never the deck's options; each
morning (and at Do it) sets Anki's today-only new limit to 0 on the deck
and its subdecks while it runs, as a catch-up sets its own; Turn back on
takes today's off again. Main thread, but for the track record's sums."""

import datetime
import traceback

from aqt import mw
from aqt.utils import tooltip

from . import ahead as A
from . import app
from .app import _bg, _state, cfg

FRESH = 600         # seconds a deck's view keeps (Insights' own)
TRUST_DAYS = 7      # the track record is worked out again after a week
LINE_HIDE = 7       # the board's line, put away, stays away a week (a deck)
MIN_STARTED = 100   # started cards before a deck has a forecast
SUBDECKS_MAX = 300  # the decks a pause sets, at most


def _pf():
    from . import plan_flow
    return plan_flow


def _today():
    return _pf()._today()


def _in(ids):
    return ",".join(str(int(c)) for c in ids) or "0"


def _wd(iso):
    try:
        return datetime.date.fromisoformat(str(iso)).weekday()
    except ValueError:
        return 0


def _days_to(iso, today):
    try:
        return (datetime.date.fromisoformat(str(iso)) - datetime.date.fromisoformat(str(today))).days
    except ValueError:
        return None


def _iso(today, k):
    return (datetime.date.fromisoformat(str(today)) + datetime.timedelta(days=int(k))).isoformat()


# ---- the log's part, once a day ----

def _day_part(col, did, deck, today):
    """{hab, extra, cv, own, rate, past, n}: what the log says, worked out
    once per Anki day per deck (today's answers aren't in it)."""
    have = (_state.get("ahead_day") or {}).get(did)
    if have and have.get("day") == today:
        return have
    cutoff = int(col.sched.day_cutoff)
    start = (cutoff - 86400) * 1000
    since = (cutoff - (A.LOOK + 1) * 86400) * 1000
    first = {int(c): -int((cutoff - 1 - int(t) // 1000) // 86400)
             for c, t in col.db.all(f"SELECT cid, min(id) FROM revlog WHERE ease > 0 AND cid IN ({deck}) GROUP BY cid")}
    first = {c: d for c, d in first.items() if d < 0}  # started today: today's count, not the log's
    log = [(-int(a), int(c), int(e), int(i), int(li), int(t)) for a, c, e, i, li, t in col.db.all(
        f"SELECT CAST((? - id / 1000) / 86400 AS INTEGER), cid, ease, ivl, lastIvl, type FROM revlog "
        f"WHERE id >= ? AND id < ? AND cid IN ({deck})", cutoff - 1, since, start)]
    hab, extra = A.habits(log)
    cv = A.curve(log, first)
    past = [set() for _ in range(7)]
    for day, cid, ease, *_ in log:
        if ease > 0 and -7 <= day < 0:
            past[day + 7].add(cid)
    n_ans, ms = col.db.first(f"SELECT count(), total(time) FROM revlog WHERE id >= ? AND id < ? AND ease > 0 "
                             f"AND cid IN ({deck})", (cutoff - 15 * 86400) * 1000, start) or (0, 0)
    part = {"day": today, "hab": hab, "extra": extra, "cv": cv or A.GENERIC, "own": cv is not None,
            "rate": A.pace(first, _wd(today)), "past": [len(s) for s in past], "n": len(first),
            "secs": (float(ms) / 1000.0 / int(n_ans)) if int(n_ans or 0) >= 200 else None}
    _state.setdefault("ahead_day", {})[did] = part
    return part


# ---- the cards now ----

def _state_now(col, deck, sday):
    """[(due day, interval)] of the deck's started cards, unsuspended, from
    today: a card in a filtered deck by its own due (odue), one in its
    learning steps today, a buried one tomorrow at the soonest."""
    out = []
    for ctype, queue, due, ivl in col.db.all(
            f"SELECT type, queue, CASE WHEN odid THEN odue ELSE due END, ivl FROM cards "
            f"WHERE id IN ({deck}) AND type != 0 AND queue != -1"):
        if queue in (1, 4):
            out.append((0, max(1, int(ivl or 0))))
        elif queue in (-2, -3):
            out.append((max(1, int(due) - sday) if ctype == 2 else 1, max(1, int(ivl or 0))))
        else:
            out.append((int(due) - sday, max(1, int(ivl or 0))))
    return out


def plan_days(units, ld, today):
    """{day from today: cards} a plan opens on its dates the next six weeks
    (what's still locked then), from P.load's counts."""
    out = {}
    for u in units:
        k = _days_to(u.get("opens"), today)
        if k is not None and 0 <= k < A.H:
            out[k] = out.get(k, 0) + int((ld.get(u["id"]) or [0, 0, 0])[2])
    return out


def deck_view(col, did, deck, exam="", plan=None):
    """Reviews ahead for a deck, as the board draws it, or None (too few
    cards started): ahead.view's, with the days it names, my seconds an
    answer, the pause and the track record. plan: plan_days()' for a plan
    I follow on it. Main thread."""
    today = _today()
    sday = int(getattr(col.sched, "today", 0) or 0)
    if not today or not sday:
        return None
    part = _day_part(col, did, deck, today)
    if part["n"] < MIN_STARTED:
        return None
    cutoff = int(col.sched.day_cutoff)
    start = (cutoff - 86400) * 1000
    left, unlocked = col.db.first(f"SELECT total(type = 0), total(queue = 0) FROM cards WHERE id IN ({deck})") or (0, 0)
    done, new_today = col.db.first(
        f"SELECT count(DISTINCT cid), count(DISTINCT CASE WHEN type = 0 AND lastIvl = 0 THEN cid END) FROM revlog "
        f"WHERE id >= ? AND ease > 0 AND cid IN ({deck})", start) or (0, 0)
    exam_in = _days_to(exam, today) if exam else None
    off = A.stop_of(_off().get(str(did)), exam_in, today)
    started = A.existing(_state_now(col, deck, sday), part["hab"], part["extra"])
    v = A.view(started, part["cv"], part["rate"], _wd(today), int(left or 0), int(unlocked or 0), part["past"],
               exam_in=exam_in, off=off, new_today=int(new_today or 0),
               plan=plan, pool=int(unlocked or 0) if plan is not None else None)
    v.update(did=did, today=today, days=[_iso(today, k) for k in range(-7, A.H)], exam=exam_in,
             done=int(done or 0), own=part["own"], secs=part["secs"], rate=sum(part["rate"]),
             unlocked=int(unlocked or 0), left=int(left or 0), off=bool(off),
             trust=_trust(col, did, deck, today))
    return v


# ---- the pause ----

def _off():
    pc = _pf()._pcfg()
    return pc.get("new_off") if isinstance(pc.get("new_off"), dict) else {}


def _decks(col, did):
    try:
        ids = [int(x) for x in col.decks.deck_and_child_ids(int(did))][:SUBDECKS_MAX]
    except Exception:
        return []
    return [d for d in ids if _pf()._deck_ok(col, d)]


def _set_zero(col, did, on):
    """Today's new cards to 0 on the deck and its subdecks (on), or today's
    0 taken off again: Anki's today-only limit, the deck's options as they
    were. True when a deck changed."""
    today, changed = int(col.sched.today), False
    for d in _decks(col, did):
        deck = col.decks.get(d)
        t = deck.get("newLimitToday") if isinstance(deck.get("newLimitToday"), dict) else {}
        mine = t.get("today") == today and t.get("limit") == 0
        if on and not mine:
            deck["newLimitToday"] = {"limit": 0, "today": today}
        elif not on and mine:
            deck.pop("newLimitToday", None)
        else:
            continue
        col.decks.save(deck)
        changed = True
    return changed


def apply_morning():
    """Each morning (after a catch-up's own limit): the pauses that run
    today set today's new cards to 0; one that's over is forgotten. Main
    thread."""
    col = mw.col
    if not col:
        return False
    today, exam = _today(), str(cfg().get("exam_date") or "")
    pc = _pf()._pcfg()
    offs, keep, changed = _off(), {}, False
    for key, off in offs.items():
        if not col.decks.get(int(key), default=False):
            continue
        stop = A.stop_of(off, _days_to(exam, today) if exam else None, today)
        if stop is None:
            continue  # over: forgotten
        keep[key] = off
        if stop[0] <= 0 <= stop[1]:
            try:
                changed = _set_zero(col, int(key), True) or changed
            except Exception:
                traceback.print_exc()
    if keep != offs:
        pc["new_off"] = keep
        _pf()._psave(pc)
    return changed


def stop_new(did, kind):
    """Do it: no new cards in this deck "now" (to my exam, or till I turn
    them back on) or the "week" before my exam. Main thread."""
    col = mw.col
    if not col or kind not in ("now", "week") or not col.decks.get(int(did), default=False):
        return
    today, exam = _today(), str(cfg().get("exam_date") or "")
    exam_in = _days_to(exam, today) if exam else None
    has_exam = exam_in is not None and exam_in >= 1
    if kind == "week" and not has_exam:
        return
    pc = _pf()._pcfg()
    pc["new_off"] = dict(_off(), **{str(int(did)): {"kind": kind, "at": today, "exam": has_exam}})
    _pf()._psave(pc)
    stop = A.stop_of(pc["new_off"][str(int(did))], exam_in, today)
    if stop and stop[0] <= 0:
        try:
            _set_zero(col, int(did), True)
            _pf()._after_change()
        except Exception:
            traceback.print_exc()
    name = str(col.decks.name(int(did)) or "").split("::")[-1]
    try:
        x = datetime.date.fromisoformat(exam) if has_exam else None
    except ValueError:
        x = None
    if kind == "week" and x:
        w = x - datetime.timedelta(days=A.STOP_BEFORE)
        tooltip(f"No new cards in {name} from {w:%a} {w.day} {w:%b} to your exam.")
    elif x:
        tooltip(f"No new cards in {name} till your exam, {x:%a} {x.day} {x:%b}.")
    else:
        tooltip(f"No new cards in {name} till you turn them back on.")
    _forget(did)


def start_new(did):
    """Turn back on: the pause gone, today's 0 off (a catch-up's limit
    back). Main thread."""
    col = mw.col
    pc = _pf()._pcfg()
    offs = dict(_off())
    offs.pop(str(int(did)), None)
    pc["new_off"] = offs
    _pf()._psave(pc)
    if col and col.decks.get(int(did), default=False):
        try:
            if _set_zero(col, int(did), False):
                _pf().apply_catch()
                _pf()._after_change()
        except Exception:
            traceback.print_exc()
    _forget(did)


def _forget(did):
    (_state.get("insights") or {}).pop(int(did), None)
    _state["ahead_line"] = None  # the line again, with the pause in it
    app.swap(cfg())


# ---- the track record ----

def _trust(col, did, deck, today):
    """(mean error, [by week]) as plans.json last kept it, or None. Older
    than a week (or never), it's worked out again off the main thread,
    once a session a deck, for the next draw."""
    pc = _pf()._pcfg()
    book = pc.get("ahead_trust") if isinstance(pc.get("ahead_trust"), dict) else {}
    have = book.get(str(did)) if isinstance(book.get(str(did)), dict) else {}
    age = _days_to(have.get("day"), today) if have else None
    asked = _state.setdefault("ahead_asked", set())
    if (age is None or age <= -TRUST_DAYS) and did not in asked:
        asked.add(did)
        try:
            _start_trust(col, did, deck, today)
        except Exception:
            traceback.print_exc()
    if have.get("by"):
        return (float(have.get("err") or 0), [float(x) for x in have["by"]])
    return None


def _start_trust(col, did, deck, today):
    cutoff = int(col.sched.day_cutoff)
    sday = int(col.sched.today)
    back = max(A.BACK) + A.LOOK + 1
    first = {int(c): -int((cutoff - 1 - int(t) // 1000) // 86400)
             for c, t in col.db.all(f"SELECT cid, min(id) FROM revlog WHERE ease > 0 AND cid IN ({deck}) GROUP BY cid")}
    log = [(-int(a), int(c), int(e), int(i), int(li), int(t)) for a, c, e, i, li, t in col.db.all(
        f"SELECT CAST((? - id / 1000) / 86400 AS INTEGER), cid, ease, ivl, lastIvl, type FROM revlog "
        f"WHERE id >= ? AND cid IN ({deck})", cutoff - 1, (cutoff - back * 86400) * 1000)]
    now = {int(c): (int(d) - sday, max(1, int(i or 0))) for c, d, i in col.db.all(
        f"SELECT id, CASE WHEN odid THEN odue ELSE due END, ivl FROM cards WHERE id IN ({deck}) AND type = 2 AND queue != -1")}
    gone = set(col.db.list(f"SELECT id FROM cards WHERE id IN ({deck}) AND queue = -1"))
    gen = app.generation

    def job():
        return A.trust(A.backtest(log, first, now, gone))

    def done(res):
        if app.generation != gen or not mw.col:
            return
        pc = _pf()._pcfg()
        book = dict(pc.get("ahead_trust") or {}) if isinstance(pc.get("ahead_trust"), dict) else {}
        book[str(did)] = {"day": today, "err": round(res[0], 4), "by": [round(x, 4) for x in res[1]]} if res else {"day": today}
        pc["ahead_trust"] = book
        _pf()._psave(pc)
        v = ((_state.get("insights") or {}).get(did) or {}).get("view") or {}
        if v.get("ahead") and res:
            v["ahead"]["trust"] = res
            app.swap(cfg())

    _bg(job, done)


# ---- the board's line ----

def board_line(c):
    """The board's line when reviews climb (ahead.climb) in my most
    reviewed deck: {did, name, day, n, week}, from today's view of it, or
    None. Worked out only by check() (after the board draws)."""
    have = _state.get("ahead_line")
    today = _today() if mw.col else ""
    if not have or have.get("day") != today or not have.get("line"):
        return None
    ln = have["line"]
    hid = _pf()._pcfg().get("ahead_line_x") or {}
    x = hid.get(str(ln["did"])) if isinstance(hid, dict) else None
    if x and (_days_to(x, today) or 0) > -LINE_HIDE:
        return None
    return ln


def check():
    """Once per Anki day, after the board draws: my most reviewed deck's
    forecast, for the board's line (a plan on it: Insights' own, its
    dates in it); a redraw only when there's a line."""
    if not mw.col:
        return
    today = _today()
    if not today or (_state.get("ahead_line") or {}).get("day") == today:
        return
    _state["ahead_line"] = {"day": today, "line": None}
    from . import team_flow
    exam = str(cfg().get("exam_date") or "")
    try:
        decks = team_flow.you_decks()
        if not decks:
            return
        d = decks[0]
        if d.get("pid"):
            v = team_flow.insights(d["did"], d["pid"], exam).get("ahead")
        else:
            v = deck_view(mw.col, d["did"], team_flow._deck_sql(mw.col, d["did"]), exam)
    except Exception:
        traceback.print_exc()
        return
    if not v or not v.get("climb"):
        return
    day, n = v["climb"]
    _state["ahead_line"]["line"] = {"did": d["did"], "name": d["name"], "day": v["days"][7 + int(day)],
                                    "n": A.r(n), "week": A.r(sum(v["past"]) / 7.0)}
    app.swap(cfg())


def hide_line(did):
    pc = _pf()._pcfg()
    pc["ahead_line_x"] = dict(pc.get("ahead_line_x") or {}, **{str(int(did)): _today()})
    _pf()._psave(pc)
    app.swap(cfg())
