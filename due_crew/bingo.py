"""3.6 squad bingo, the pure part. The server draws the week's card (eight
squares around a middle) and keeps it; this works out, from my own
reviews, which squares I've passed and how close I am to the rest (that
stays on this computer), builds `play` (the facts my squad rows carry, the
same in every squad), and adds a squad's rows up. `evaluate` restates the
Worker's (worker/src/bingo.ts): change one, change both.

Squares count Anki's days (the rollover hour), my Monday to Sunday. Time of
day is the computer's clock; a review after midnight but before the
rollover belongs to the night before (hour 24 and on). Every mark is one you
pass on the way up: none rewards stopping."""

import datetime as _dt
import math
import re

FAMILIES = ("early", "spread", "focus", "volume", "fresh", "often", "clean", "wild")
FAMILY_NAMES = {"early": "Early", "spread": "Spread out", "focus": "Focus", "volume": "Bigger day",
                "fresh": "New cards", "often": "Showing up", "clean": "Keeping up", "wild": "Wildcard"}
DIFF_NAMES = {"e": "easy", "m": "medium", "h": "hard"}
SQUARE_TYPES = ("window", "minute", "sittings", "parts", "focus", "beat", "rel", "best",
                "newdays", "newdone", "days", "zero", "samehour")
MIDDLE_TYPES = ("people", "sum", "day", "emoji", "joined", "free")
# in show-up mode only squares that say which days go out, never when or how much
SHOW_UP_TYPES = ("newdays", "newdone", "days", "zero")
# and with a number's Privacy switch off, the squares built from it stay home
BY_SWITCH = {"share_reviews": ("beat", "rel", "best"), "share_time": ("focus",)}


def withheld(cfg):
    """The square types my Privacy switches keep off my squad rows."""
    if cfg.get("show_up"):
        return set(SQUARE_TYPES) - set(SHOW_UP_TYPES)
    return {t for k, types in BY_SWITCH.items() if not cfg.get(k, True) for t in types}
PLAY_KEYS = ("s", "d", "e8", "n10", "z", "ch", "rm", "lv", "aq", "tp", "dk", "st")
CELLS = (0, 1, 2, 3, 5, 6, 7, 8)   # the squares' places around the middle (4)
LINES = ((0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6))
# a team square's need, or a middle's goal, as a share of the squad (at
# least 2 of you, never more than there are): worker/src/bingo.ts SHARES
SHARES = {"half": 1 / 2, "third": 1 / 3, "quarter": 1 / 4}
SHARE_WORDS = {"half": "half of you", "third": "a third of you", "quarter": "a quarter of you"}
USUAL_DEFAULT = 50     # "your usual day" until there's a week of history
USUAL_MIN_DAYS = 7
_WK = re.compile(r"(\d{4})-W(\d{2})$")
_HM = re.compile(r"([01]\d|2[0-3]):[0-5]\d$")


# ---- weeks ----

def week_key(label):
    """The ISO week an Anki day is in, as "2026-W40"."""
    y, w, _d = _dt.date.fromisoformat(label).isocalendar()
    return f"{y}-W{w:02d}"


def wk_num(wk):
    return int(wk[:4]) * 100 + int(wk[6:])


def week_labels(label):
    """Monday to Sunday of the week `label` is in."""
    d = _dt.date.fromisoformat(label)
    monday = d - _dt.timedelta(days=d.weekday())
    return [(monday + _dt.timedelta(days=i)).isoformat() for i in range(7)]


# ---- the card, as the server sent it ----

def _text(v, limit):
    if not isinstance(v, str):
        return ""
    one = " ".join(v.split())
    return "".join(ch for ch in one if ch.isprintable())[:limit]


def _int(v, lo, hi):
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def _clean_params(p):
    """Numbers, short lists of numbers, "HH:MM" times, a play key. Anything
    else goes; a rule that then lacks what it needs is unknown."""
    if not isinstance(p, dict):
        return {}
    out = {}
    for k, v in list(p.items())[:8]:
        if not isinstance(k, str) or len(k) > 12:
            continue
        if k == "row" and isinstance(v, bool):
            out[k] = v
        elif _int(v, 0, 100000):
            out[k] = v
        elif isinstance(v, float) and 0 < v <= 10:
            out[k] = v
        elif k == "key" and v in PLAY_KEYS:
            out[k] = v
        elif k == "dow" and isinstance(v, list) and all(_int(x, 0, 6) for x in v[:7]):
            out[k] = list(v[:7])
        elif k == "hm" and isinstance(v, list) and all(isinstance(x, str) and _HM.match(x) for x in v[:4]):
            out[k] = list(v[:4])
        elif k == "parts" and isinstance(v, list) and all(
                isinstance(x, list) and len(x) == 2 and _int(x[0], 0, 23) and _int(x[1], 1, 24) and x[0] < x[1] for x in v[:3]):
            out[k] = [list(x) for x in v[:3]]
    return out


def clean_card(v):
    """The week's card, coerced, or None. Its words are shown escaped."""
    if not isinstance(v, dict) or not isinstance(v.get("wk"), str) or not _WK.match(v["wk"]):
        return None
    squares = v.get("squares")
    mid = v.get("middle")
    if not isinstance(squares, list) or len(squares) != 8 or not isinstance(mid, dict):
        return None
    out = []
    for s in squares:
        if not isinstance(s, dict):
            return None
        need = s.get("need")
        out.append({
            "id": _text(s.get("id"), 12), "fam": s.get("fam") if s.get("fam") in FAMILIES else "wild",
            "diff": s.get("diff") if s.get("diff") in DIFF_NAMES else "m",
            "icon": _text(s.get("icon"), 8), "title": _text(s.get("title"), 28), "rule": _text(s.get("rule"), 48),
            "detail": _text(s.get("detail"), 160), "type": _text(s.get("type"), 16),
            "params": _clean_params(s.get("params")),
            "need": need if need in SHARES or _int(need, 1, 3) else 1,
        })
    goal = mid.get("goal")
    middle = {
        "id": _text(mid.get("id"), 12), "group": _text(mid.get("group"), 8), "icon": _text(mid.get("icon"), 8),
        "name": _text(mid.get("name"), 28), "rule": _text(mid.get("rule"), 48), "detail": _text(mid.get("detail"), 160),
        "type": _text(mid.get("type"), 16), "params": _clean_params(mid.get("params")),
        "goal": goal if goal == "all" or goal in SHARES or _int(goal, 1, 500) else 1, "unit": _text(mid.get("unit"), 20),
    }
    return {"wk": v["wk"], "squares": out, "middle": middle}


def known(sq):
    """A square this version can play. A newer type shows "Update to play"."""
    return sq.get("type") in SQUARE_TYPES


# ---- my week: the facts, and each square from them ----

def _eff_hour(t, rollover):
    """The clock hour, with the hours after midnight (before the rollover)
    counted as the night before's 24, 25..."""
    return t.hour + 24 if t.hour < rollover else t.hour


def usual_day(daily, week):
    """My usual day: the average over the days I studied in the 30 before
    this Monday; USUAL_DEFAULT until there are USUAL_MIN_DAYS of them."""
    monday = _dt.date.fromisoformat(week[0])
    counts = [daily.get((monday - _dt.timedelta(days=i)).isoformat(), 0) for i in range(1, 31)]
    studied = [n for n in counts if n > 0]
    if len(studied) < USUAL_MIN_DAYS:
        return USUAL_DEFAULT
    return sum(studied) / len(studied)


def facts(week, today, times, daily, new, zero=(), newdone=(), rollover=4):
    """What the squares are worked out from. week: Monday to Sunday labels.
    times: {label: [datetime of each answer, sorted]} this week. daily:
    {label: answers} for this week and the 37 days before. new: {label: new
    cards}. zero, newdone: labels this computer saw end due-zero / with its
    new cards done."""
    return {"week": list(week), "today": today, "times": times, "daily": daily, "new": new,
            "zero": set(zero), "newdone": set(newdone), "rollover": rollover,
            "usual": usual_day(daily, week)}


def _days(f, dow=None):
    """This week's labels up to today, optionally only these weekdays."""
    return [lb for i, lb in enumerate(f["week"]) if lb <= f["today"] and (dow is None or i in dow)]


def _count(done, need, unit):
    have = min(done, need)
    return have >= need, f"{have} of {need} {unit}"


def _sessions(ts, gap):
    """How many sittings: a new one when the last answer was `gap` minutes or more before."""
    n, prev = 0, None
    for t in ts:
        if prev is None or (t - prev).total_seconds() >= gap * 60:
            n += 1
        prev = t
    return n


def _longest_run(ts, gap):
    """The longest stretch, in minutes, with no gap of `gap` minutes or more."""
    best, start, prev = 0.0, None, None
    for t in ts:
        if prev is None or (t - prev).total_seconds() >= gap * 60:
            start = t
        best = max(best, (t - start).total_seconds() / 60)
        prev = t
    return best


def _tally(f, test, p, unit="days"):
    """(done, words) for "that many days" (row: that many days in a row,
    this week so far). Days are Monday on; a gap day starts the run again."""
    need = int(p.get("days") or 1)
    days = _days(f, p.get("dow"))
    if p.get("row"):
        run = best = 0
        for lb in days:
            run = run + 1 if test(lb) else 0
            best = max(best, run)
        have = min(best, need)
        done = best >= need
        return done, "Done" if done else f"{have} of {need} days in a row"
    return _count(sum(1 for lb in days if test(lb)), need, unit if need > 1 else unit.rstrip("s"))


def progress(sq, f):
    """(done, words) for one square: how close I am. My own; never sent."""
    t, p = sq.get("type"), sq.get("params") or {}
    times, daily, roll = f["times"], f["daily"], f["rollover"]
    try:
        if t == "window":
            lo, hi = p["from"], p["to"]
            if hi == 24:
                hi = 24 + roll        # after midnight, before the rollover: still that night
            return _tally(f, lambda lb: any(lo <= _eff_hour(x, roll) < hi for x in times.get(lb, ())), p)
        if t == "minute":
            hit = any(x.strftime("%H:%M") in p["hm"] for lb in _days(f) for x in times.get(lb, ()))
            return hit, "Done" if hit else "Not yet"
        if t == "sittings":
            best = max([_sessions(times.get(lb, ()), p["gap"]) for lb in _days(f)] or [0])
            done = best >= p["n"]
            return done, "Done" if done else f"Best day: {best} of {p['n']} sittings"
        if t == "parts":
            parts = p["parts"]

            def covered(lb):
                hours = [_eff_hour(x, roll) for x in times.get(lb, ())]
                return sum(1 for a, b in parts if any(a <= h < (b + roll if b == 24 else b) for h in hours))
            done, words = _tally(f, lambda lb: covered(lb) == len(parts), p)
            if done or p.get("row"):
                return done, words
            return False, f"Today: {covered(f['today'])} of {len(parts)} parts"
        if t == "focus":
            if int(p.get("days") or 1) > 1:
                return _tally(f, lambda lb: _longest_run(times.get(lb, ()), p["gap"]) >= p["minutes"], p)
            best = max([_longest_run(times.get(lb, ()), p["gap"]) for lb in _days(f)] or [0])
            done = best >= p["minutes"]
            return done, "Done" if done else f"Longest: {int(best)} of {p['minutes']} min"
        if t == "beat":
            run = best = 0
            for lb in _days(f):
                prev = (_dt.date.fromisoformat(lb) - _dt.timedelta(days=1)).isoformat()
                run = run + 1 if daily.get(lb, 0) > daily.get(prev, 0) else 0
                best = max(best, run)
            if best >= p["run"]:
                return True, "Done"
            yday = (_dt.date.fromisoformat(f["today"]) - _dt.timedelta(days=1)).isoformat()
            to_go = daily.get(yday, 0) + 1 - daily.get(f["today"], 0)
            return False, f"{to_go} more today beats yesterday" if p["run"] == 1 else f"{best} of {p['run']} days running"
        if t == "rel":
            target = math.ceil(f["usual"] * p["x"])
            best = max([daily.get(lb, 0) for lb in _days(f)] or [0])
            if best >= target:
                return True, "Done"
            return False, f"{target - daily.get(f['today'], 0)} to go today ({target} is {p['x']}× your usual)"
        if t == "best":
            def beat_month(lb):
                d = _dt.date.fromisoformat(lb)
                before = [daily.get((d - _dt.timedelta(days=i)).isoformat(), 0) for i in range(1, p["days"] + 1)]
                return daily.get(lb, 0) > max(before), max(before)
            if any(daily.get(lb, 0) and beat_month(lb)[0] for lb in _days(f)):
                return True, "Done"
            top = beat_month(f["today"])[1]
            return False, f"{top + 1 - daily.get(f['today'], 0)} to go today (your best is {top})"
        if t == "newdays":
            return _tally(f, lambda lb: f["new"].get(lb, 0) > 0, p)
        if t == "newdone":
            return _tally(f, lambda lb: lb in f["newdone"], p)
        if t == "days":
            return _tally(f, lambda lb: daily.get(lb, 0) > 0, p)
        if t == "zero":
            return _tally(f, lambda lb: lb in f["zero"], p)
        if t == "samehour":
            run = best = 0
            last = None
            for lb in _days(f):
                ts = times.get(lb)
                h = _eff_hour(ts[0], roll) if ts else None
                run = run + 1 if h is not None and h == last else (1 if h is not None else 0)
                best = max(best, run)
                last = h
            return _count(best, p["run"], "days running")
    except (KeyError, TypeError, ValueError):
        pass
    return False, "Update Due Crew to play this one"


# ---- play: what my squad rows carry ----

def _bits(f, test):
    return sum(1 << i for i, lb in enumerate(f["week"]) if lb <= f["today"] and test(lb))


def play(card, f, show_up=False, counts=None, hide=()):
    """The facts about my week that a squad adds up, as {key: int}. Squares
    I've passed are bits of `s`. Show-up mode sends only which days, never
    when or how much; `hide` (withheld) are square types my switches keep
    home. counts: my week's cheers sent, rooms joined and so on (ch, rm,
    lv, aq, tp, dk, st)."""
    out = {"wk": wk_num(card["wk"]) if card else wk_num(week_key(f["today"]))}
    roll = f["rollover"]
    if card:
        s = 0
        for i, sq in enumerate(card["squares"]):
            if (known(sq) and (not show_up or sq["type"] in SHOW_UP_TYPES) and sq["type"] not in hide
                    and progress(sq, f)[0]):
                s |= 1 << i
        out["s"] = s
    out["d"] = _bits(f, lambda lb: f["daily"].get(lb, 0) > 0)
    out["z"] = _bits(f, lambda lb: lb in f["zero"])
    if not show_up:
        out["e8"] = _bits(f, lambda lb: any(_eff_hour(x, roll) < 8 for x in f["times"].get(lb, ())))
        out["n10"] = _bits(f, lambda lb: any(_eff_hour(x, roll) >= 22 for x in f["times"].get(lb, ())))
    for k, v in (counts or {}).items():
        if k in PLAY_KEYS and _int(v, 0, 10000):
            out[k] = v
    return {k: v for k, v in out.items() if v or k == "wk"}


# ---- a squad's card, from its rows (worker/src/bingo.ts: evaluate) ----

def how_many(need, count):
    """How many of you a need or a goal means, with this many active:
    worker/src/bingo.ts howMany. Numbers (cards before 3.6.1) as they are."""
    if need == "all":
        return count
    if need in SHARES:
        return 1 if count <= 1 else min(count, max(2, math.ceil(SHARES[need] * count)))
    return min(int(need), count)


def evaluate(card, rows):
    """rows: [{user_id, emoji, day, joined, play}]. Whose play counts this
    week, who's active, and where each square and the middle stand.
    Active: an add-on that plays (an older one never sends play, and
    can't be counted on), which played this week or studied since last
    week's Monday. `older` is those studying on an add-on that can't."""
    n = wk_num(card["wk"])
    monday = _dt.date.fromisoformat(week_labels_for(card["wk"])[0])
    since = (monday - _dt.timedelta(days=7)).isoformat()

    def mine(r):
        p = r.get("play")
        return p if isinstance(p, dict) and p.get("wk") == n else None
    active = [r for r in rows if mine(r) or (r.get("play") and (r.get("day") or "") >= since)]
    older = sum(1 for r in rows if not r.get("play") and (r.get("day") or "") >= since)
    count = max(1, len(active))

    def cap(need):
        return how_many(need, count)
    squares = []
    for i, sq in enumerate(card["squares"]):
        who = [r["user_id"] for r in rows if (int((mine(r) or {}).get("s") or 0) >> i) & 1]
        need = cap(sq.get("need") or 1)
        squares.append({"who": who, "need": need, "done": len(who) >= need})
    m = card["middle"]
    key = (m.get("params") or {}).get("key", "")

    def val(r):
        return int((mine(r) or {}).get(key) or 0)
    t = m.get("type")
    if t == "free":
        have = 1
    elif t == "people":
        have = sum(1 for r in rows if val(r) > 0)
    elif t == "sum":
        have = sum(val(r) for r in rows)
    elif t == "day":
        days = [m["params"]["day"]] if isinstance((m.get("params") or {}).get("day"), int) else range(7)
        have = max(sum(1 for r in rows if (val(r) >> d) & 1) for d in days)
    elif t == "emoji":
        have = sum(1 for r in active if r.get("emoji"))
    elif t == "joined":
        have = sum(1 for r in rows if (r.get("joined") or "") >= monday.isoformat())
    else:
        have = 0
    goal = 1 if t == "free" else (m["goal"] if t == "sum" and isinstance(m.get("goal"), int) else cap(m.get("goal") or 1))
    middle = {"have": min(have, goal), "goal": goal, "done": have >= goal, "known": t in MIDDLE_TYPES}

    def cell(c):
        return middle["done"] if c == 4 else squares[CELLS.index(c)]["done"]
    lines = [l for l in LINES if all(cell(c) for c in l)]
    return {"active": len(active), "players": sum(1 for r in rows if mine(r)), "older": older, "squares": squares,
            "middle": middle, "lines": len(lines), "cells": sorted({c for l in lines for c in l})}


def week_labels_for(wk):
    """Monday to Sunday of an ISO week."""
    y, w = int(wk[:4]), int(wk[6:])
    monday = _dt.date.fromisocalendar(y, w, 1)
    return [(monday + _dt.timedelta(days=i)).isoformat() for i in range(7)]


def closest(card, ev):
    """The fewest cells left for a line: their names, closest first."""
    def cell_done(c):
        return ev["middle"]["done"] if c == 4 else ev["squares"][CELLS.index(c)]["done"]
    best = min(LINES, key=lambda l: sum(1 for c in l if not cell_done(c)))
    return [card["middle"]["name"] if c == 4 else card["squares"][CELLS.index(c)]["title"]
            for c in best if not cell_done(c)]


def share_text(card, ev, squad_name):
    """For the group chat: the grid in emoji, never who stamped what."""
    rows = []
    for r in range(3):
        line = ""
        for c in range(3):
            cell = r * 3 + c
            if cell == 4:
                line += card["middle"]["icon"] if ev["middle"]["done"] else "🔒"
            else:
                line += "🟩" if ev["squares"][CELLS.index(cell)]["done"] else "⬜"
        rows.append(line)
    n = sum(1 for s in ev["squares"] if s["done"]) + (1 if ev["middle"]["done"] else 0)
    lines = ev["lines"]
    tail = "" if not lines else " · the whole card" if lines == len(LINES) else " · BINGO" if lines == 1 else f" · {lines} lines"
    name = _text(squad_name, 24)
    return (f"{name} · squad bingo {card['wk']}\n" + "\n".join(rows)
            + f"\n{n} of 9{tail}\n— Due Crew · Anki add-on 2035408484")
