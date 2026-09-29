"""3.6 squad bingo, the glue. Per profile, bingo.json keeps this week's
days this computer saw end due-zero or with its new cards done, and my
counts for the middle (cheers sent, rooms joined, the studying dot, asks,
tips); a new week starts them over. At each sync, `for_row` works out my
squares from my own reviews (main thread: collection access) and hands the
squad row its `play`; the board's view adds the squad's rows up.

Nothing here makes a request: the card comes with the day's first refresh
(or the squad, when the Squads tab opens) and play rides the sync."""

import datetime
import json
import os
import traceback

from aqt import mw

from . import bingo as B
from .app import _profile_files, _profile_key, _state, client

FILE = "bingo.json"
COUNT_KEYS = ("ch", "rm", "lv", "aq", "tp")
_mem = {"profile": None, "data": None}


def _path():
    return os.path.join(_profile_files(), FILE)


def _data():
    key = _profile_key()
    if _mem["profile"] != key:
        _mem["profile"] = key
        try:
            with open(_path()) as f:
                data = json.load(f)
            _mem["data"] = data if isinstance(data, dict) else {}
        except Exception:
            _mem["data"] = {}
    return _mem["data"]


def _save():
    path = _path()
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(_mem["data"], f)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _week(wk):
    """This week's record, started over when the week changed. `seen` (the
    week whose card I've looked at) and `lines` (per squad, the lines I've
    been told about) carry the week in their values."""
    d = _data()
    if d.get("wk") != wk:
        seen = d.get("seen")
        d.clear()
        d.update(wk=wk, zero=[], newdone=[], counts={}, lines={}, seen=seen if seen == wk else "")
    for k, default in (("zero", []), ("newdone", []), ("counts", {}), ("lines", {})):
        if not isinstance(d.get(k), type(default)):
            d[k] = default
    return d


def _today_wk():
    if _state["labels"]:
        return _state["labels"][0], B.week_key(_state["labels"][0])
    if mw.col:
        from .stats.queries import StatsQueries
        lb = StatsQueries(mw.col).day_label(0)
        return lb, B.week_key(lb)
    return None, None


def bump(key, by=1):
    """One more of something the middle can count. Main thread."""
    if key not in COUNT_KEYS:
        return
    try:
        _lb, wk = _today_wk()
        if not wk:
            return
        d = _week(wk)
        d["counts"][key] = int(d["counts"].get(key) or 0) + by
        _save()
    except Exception:
        traceback.print_exc()


def card():
    return client().session.get("bingo")


# ---- my week, from the collection (main thread) ----

def _observe(q, d, today):
    """Today, if the decks I studied have nothing left due, or none of the
    new cards they give: the days the "keeping up" and "new done" squares
    count. Seen when it's true at a sync; one deck tree and one query."""
    if today in d["zero"] and today in d["newdone"]:
        return  # both seen: the deck tree (slow in a big collection) can wait for tomorrow
    start, end = q.day_bounds_ms(0)
    rows = mw.col.db.all(
        "SELECT CASE WHEN c.odid THEN c.odid ELSE c.did END, MAX(CASE WHEN r.type = 0 THEN 1 ELSE 0 END) "
        "FROM revlog r JOIN cards c ON c.id = r.cid WHERE r.id >= ? AND r.id < ? AND r.ease > 0 GROUP BY 1",
        start, end)
    if not rows:
        return
    counts = {}

    def walk(node):
        counts[node.deck_id] = (node.review_count + node.learn_count, node.new_count)
        for child in node.children:
            walk(child)
    walk(mw.col.sched.deck_due_tree())
    studied = [(int(did), bool(new)) for did, new in rows if int(did) in counts]
    if not studied:
        return
    if all(counts[did][0] == 0 for did, _n in studied) and today not in d["zero"]:
        d["zero"].append(today)
    learned = [did for did, new in studied if new]
    if learned and all(counts[did][1] == 0 for did in learned) and today not in d["newdone"]:
        d["newdone"].append(today)


def _facts(q, d, today):
    week = B.week_labels(today)
    cutoff = int(mw.col.sched.day_cutoff)
    start_ms = (cutoff - 7 * 86400) * 1000
    times = {}
    for rid, in_day in mw.col.db.all(
            "SELECT id, CAST((? - id / 1000) / 86400 AS INTEGER) FROM revlog "
            "WHERE ease > 0 AND id >= ? AND id < ? ORDER BY id", cutoff - 1, start_ms, cutoff * 1000):
        lb = q.day_label(int(in_day))
        if lb in week:
            times.setdefault(lb, []).append(datetime.datetime.fromtimestamp(rid / 1000))
    daily = {lb: t[0] for lb, t in q.daily_totals(45).items()}
    new = q.new_cards_by_day(8)
    # the hour Anki's day rolls over, as _clock reads it: Anki keeps it in
    # its preferences, not the collection's config
    roll = datetime.datetime.fromtimestamp(cutoff).hour
    return B.facts(week, today, times, daily, new, d["zero"], d["newdone"], rollover=roll)


def for_row(c):
    """My squad row's play for this sync, or None (in no squad, or signed
    out). Keeps my progress on each square for the board. Main thread."""
    if not (c.get("squads") or []) or not mw.col or c.get("paused"):
        return None
    try:
        from .stats.queries import StatsQueries
        q = StatsQueries(mw.col)
        today = q.day_label(0)
        wk = B.week_key(today)
        d = _week(wk)
        try:
            _observe(q, d, today)
        except Exception:
            traceback.print_exc()
        f = _facts(q, d, today)
        cd = card()
        cd = cd if cd and cd.get("wk") == wk else None
        counts = dict(d["counts"])
        counts["dk"] = 1 if c.get("shared_decks") else 0
        counts["st"] = 1 if str(c.get("status") or "").strip() else 0
        play = B.play(cd, f, show_up=bool(c.get("show_up")), counts=counts, hide=B.withheld(c))
        _state["bingo_mine"] = {"wk": wk, "play": play, "ids": _ids(cd),
                                "progress": [B.progress(sq, f) if B.known(sq) else (False, "")
                                             for sq in cd["squares"]] if cd else None}
        _save()
        return play
    except Exception:
        traceback.print_exc()
        return None


def _ids(cd):
    return [q.get("id") for q in cd["squares"]] if cd else None


# ---- the board's view ----

def view(squad_view, c):
    """What board.bingo_* draw for the squad on screen, or None."""
    cd = card()
    rows = squad_view.get("rows") if squad_view.get("state") == "ok" else None
    lb, wk = _today_wk()
    if not cd or rows is None or cd.get("wk") != wk:
        return None
    me = client().user_id
    mine = _state.get("bingo_mine") or {}
    if mine.get("wk") == wk and mine.get("ids") != _ids(cd):
        # a new card since the sync (a redraw): my squares against this one,
        # now, not at the next sync (once: a failure leaves nothing of mine)
        _state["bingo_mine"] = dict(mine, ids=_ids(cd), play=None, progress=None)
        for_row(c)
        mine = _state.get("bingo_mine") or {}
    if mine.get("wk") == wk and mine.get("play"):
        # my own row as this computer worked it out at the sync, not as the
        # squad was last fetched (up to a few minutes old)
        rows = [dict(r, play=mine["play"]) if r["user_id"] == me else r for r in rows]
    ev = B.evaluate(cd, rows)
    progress = mine.get("progress") if mine.get("wk") == wk else None
    names = {r["user_id"]: (r.get("name") or "?", r.get("emoji") or "") for r in rows}
    d = _week(wk)
    return {"card": cd, "ev": ev, "progress": progress, "me": me, "names": names,
            "squad": squad_view.get("name") or "", "squad_id": squad_view.get("current") or "",
            "new": d.get("seen") != wk, "closest": B.closest(cd, ev),
            "withheld": sorted(B.withheld(c)), "today": lb}


def seen():
    """I've opened this week's card: the Monday banner goes."""
    _lb, wk = _today_wk()
    if wk:
        _week(wk)["seen"] = wk
        _save()


def new_lines(v):
    """The squad's lines since I was last told, once: for "BINGO!"."""
    if not v:
        return 0
    d = _week(v["card"]["wk"])
    sid = v["squad_id"]
    had = int(d["lines"].get(sid) or 0)
    now = v["ev"]["lines"]
    if now != had:
        d["lines"][sid] = now
        _save()
    return max(0, now - had)
