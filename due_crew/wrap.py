"""Local, per-profile bookkeeping that never touches the network: the
weekly wrap banner, lifetime crew milestones, "welcome back" detection, the
exam-eve line, deck deltas, and the muted-knocks list. All of it lives in
user_files/<profile>/wrap.json."""

import datetime
import html
import json
import os

from . import board
from .app import (CREW_HOUR_MILESTONE_MS, CREW_REVIEW_MILESTONES, RETURN_QUIET_DAYS,
                  _profile_files, _profile_key, _state, _wrap)

def _sane(data):
    """wrap.json as this add-on writes it, or less. It is read inside the
    deck browser's render hook, where a bad shape means Anki's error dialog
    on every redraw, over a file no user knows exists. A ledger that isn't
    ours is dropped and rebuilt from the board; _update_ledger's first-run
    rule then keeps the all-time totals from counting anything twice."""
    if not isinstance(data, dict):
        return {}
    ledger = data.get("ledger")
    if ledger is not None:
        def day_ok(d):
            return (isinstance(d, dict) and isinstance(d.get("r"), int)
                    and isinstance(d.get("t"), int) and isinstance(d.get("p", {}), dict)
                    and all(isinstance(n, int) for n in d.get("p", {}).values()))
        if not (isinstance(ledger, dict) and all(day_ok(d) for d in ledger.values())):
            data.pop("ledger")
    for key in ("best", "banner", "life"):
        if key in data and not isinstance(data[key], dict):
            data.pop(key)
    return data


def _wrap_data():
    key = _profile_key()
    if _wrap["profile"] != key:
        _wrap["profile"] = key
        try:
            with open(os.path.join(_profile_files(), "wrap.json")) as f:
                _wrap["data"] = _sane(json.load(f))
        except Exception:
            _wrap["data"] = {}
    return _wrap["data"]


def _save_wrap():
    """Written whole, then swapped in: a crash mid-write used to leave half a
    file, which loads as nothing and takes the all-time totals with it."""
    path = os.path.join(_profile_files(), "wrap.json")
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(_wrap["data"], f)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _week_key(label):
    year, week, _day = datetime.date.fromisoformat(label).isocalendar()
    return f"{year}-W{week:02d}"


LEDGER_DAYS = 21   # last week must stay summable all through this one


def _monday(day):
    return day - datetime.timedelta(days=day.weekday())


def _update_ledger(w, entries, labels):
    """Record what the board knows about each day in the window, and add a
    day to the all-time totals exactly once: when it leaves the window, by
    which time late syncs have landed. Returns (reviews, time_ms) folded in.

    Until 2.6 the accrual ran once per ISO week over "the last seven days as
    of whenever Anki was first opened that week". Open on a Monday one week
    and a Wednesday the next and two days were counted twice; skip a week
    and its days were never counted. The "Last week" banner was the same
    rolling sum, so it was only last week if you opened Anki on a Monday."""
    first_run = "ledger" not in w
    ledger = w.setdefault("ledger", {})
    active = [e for e in entries if not e.get("paused")]
    for lb in labels:
        reviews = time_ms = 0
        people = {}
        for e in entries:
            doc = (e.get("days") or {}).get(lb) or {}
            n = int(doc.get("reviews") or 0)
            reviews += n
            time_ms += int(doc.get("studyTimeMs") or 0)
            if n:
                people[e["user_id"]] = n
        everyone = len(active) >= 2 and all(
            board._showed((e.get("days") or {}).get(lb)) for e in active)
        ledger[lb] = {"r": reviews, "t": time_ms, "all": everyone, "p": people,
                      "folded": bool((ledger.get(lb) or {}).get("folded"))}
    today = datetime.date.fromisoformat(labels[0])
    if first_run:
        # the old weekly accrual already counted (roughly) everything before
        # this Monday; counting it again on the way out would double it
        monday = _monday(today).isoformat()
        for lb, day in ledger.items():
            if lb < monday:
                day["folded"] = True
    window = set(labels)
    folded_r = folded_t = 0
    for lb in sorted(ledger):
        day = ledger[lb]
        if lb not in window and not day.get("folded"):
            folded_r += day["r"]
            folded_t += day["t"]
            day["folded"] = True
    horizon = (today - datetime.timedelta(days=LEDGER_DAYS)).isoformat()
    for lb in [lb for lb in ledger if lb < horizon]:
        ledger.pop(lb)
    return folded_r, folded_t


def _week_totals(ledger, monday):
    """(days_known, reviews, time_ms, everyone_days, {uid: reviews}) for the
    calendar week starting `monday`, from whatever the ledger holds of it."""
    known = reviews = time_ms = everyone = 0
    people = {}
    for i in range(7):
        day = ledger.get((monday + datetime.timedelta(days=i)).isoformat())
        if not day:
            continue
        known += 1
        reviews += day["r"]
        time_ms += day["t"]
        everyone += 1 if day.get("all") else 0
        for uid, n in (day.get("p") or {}).items():
            people[uid] = people.get(uid, 0) + n
    return known, reviews, time_ms, everyone, people


def _update_wrap(entries, labels):
    """Per-commit bookkeeping. Returns a milestone toast string, or None."""
    w = _wrap_data()
    week = _week_key(labels[0])
    folded_r, folded_t = _update_ledger(w, entries, labels)
    toast = None
    if folded_r or folded_t:
        toast = _accrue_milestones(w, folded_r, folded_t, labels[0])
    if w.get("week") != week:
        # a new calendar week: the week BEFORE last is now settled, so it
        # joins each person's best; last week is judged against that
        this_monday = _monday(datetime.date.fromisoformat(labels[0]))
        best = w.setdefault("best", {})
        _k, _r, _t, _a, people = _week_totals(
            w.get("ledger") or {}, this_monday - datetime.timedelta(days=14))
        for uid, n in people.items():
            if n > best.get(uid, 0):
                best[uid] = n
        w["week"] = week
        w["deck_base"] = {f"{e['user_id']}|{d.get('name', '')}": int(d.get("seen") or 0)
                          for e in entries for d in (e.get("decks") or [])}
    _save_wrap()
    return toast


def _accrue_milestones(w, week_reviews, week_time_ms, today_label):
    """Lifetime crew totals, celebrated at thresholds. Fed by the ledger with
    days that have just left the window, each exactly once. Local arithmetic
    only; "since" is when accrual began. Totals from before 2.6 came from the
    drifting weekly sum and are carried forward as they stand."""
    life = w.setdefault("life", {"reviews": 0, "time_ms": 0,
                                 "since": today_label})
    life["reviews"] += int(week_reviews or 0)
    life["time_ms"] += int(week_time_ms or 0)
    done = w.setdefault("milestones_done", [])
    crossed = None
    for t in CREW_REVIEW_MILESTONES:
        if life["reviews"] >= t and f"r{t}" not in done:
            done.append(f"r{t}")
            crossed = f"{t:,} reviews"
    if life["time_ms"] >= CREW_HOUR_MILESTONE_MS and "h1000" not in done:
        done.append("h1000")
        crossed = crossed or "1,000 hours"
    if not crossed:
        return None
    try:
        since = datetime.date.fromisoformat(life["since"])
        today = datetime.date.fromisoformat(today_label)
        month = since.strftime("%B") if since.year == today.year \
            else since.strftime("%b %Y")
    except (TypeError, ValueError):
        month = ""
    w.setdefault("banner", {})["milestone"] = crossed
    w["milestone_week"] = _week_key(today_label)  # the banner shows it this week
    tail = f" together since {month}" if month else " together"
    return f"\U0001F388 {crossed}{tail}"


def _update_returns(entries, labels, tomorrow, c):
    """The day a quiet friend's first sync lands, the board says so — once.
    Spoken to the crew, never at the returner. Local state only."""
    if not labels:
        return []
    w = _wrap_data()
    last = w.setdefault("last_studied", {})   # uid -> newest studied label
    rets = w.setdefault("returns", {})        # uid -> label of return day
    today = labels[0]
    toasts = []
    seen_uids = set()
    for e in entries:
        if e["you"] or e["paused"]:
            continue
        uid = e["user_id"]
        seen_uids.add(uid)
        days = e.get("days") or {}
        active = board._showed(days.get(tomorrow) or days.get(today))
        prior = [lb for lb in labels[1:] if board._showed(days.get(lb))]
        if active:
            known = last.get(uid)
            if known and not prior and rets.get(uid) != today:
                try:
                    gap = (datetime.date.fromisoformat(today)
                           - datetime.date.fromisoformat(known)).days
                except (TypeError, ValueError):
                    gap = 0
                if gap >= RETURN_QUIET_DAYS:
                    rets[uid] = today
                    if c.get("sync_notifications", True):
                        toasts.append(
                            f"\U0001F44B {html.escape(e['name'])} is back "
                            f"— first study in {gap} days")
        newest = today if active else (prior[0] if prior else None)
        if newest and newest > str(last.get(uid) or ""):
            last[uid] = newest
        e["back"] = rets.get(uid) == today
    for uid in [u for u in list(last) if u not in seen_uids]:
        last.pop(uid, None)
        rets.pop(uid, None)
    _save_wrap()
    return toasts


def _exam_eve_info():
    """People whose shared exam is tomorrow — one dismissible line's worth."""
    labels = _state["labels"]
    if not labels:
        return None
    today = labels[0]
    if _wrap_data().get("eve_dismissed") == today:
        return None
    people = [(e["user_id"], e["name"]) for e in _state["entries"] or []
              if not e["you"] and not e["paused"]
              and board._exam_text(e.get("exam_date"), today) == "exam tomorrow"]
    return {"people": people} if people else None


def _wrap_info():
    """The "Last week, together" banner: last Monday to Sunday, summed from
    the ledger every time it is drawn, so a crewmate's late Sunday sync still
    lands in it. `days_known` < 7 means the board never saw some of those
    days (Anki wasn't opened while they were in view) and the banner says so
    instead of passing a partial week off as a whole one."""
    labels = _state["labels"]
    if not labels:
        return None
    w = _wrap_data()
    week = _week_key(labels[0])
    if w.get("dismissed") == week:
        return None
    this_monday = _monday(datetime.date.fromisoformat(labels[0]))
    known, reviews, time_ms, everyone, people = _week_totals(
        w.get("ledger") or {}, this_monday - datetime.timedelta(days=7))
    if not reviews:
        return None
    best = w.get("best") or {}
    names = {e["user_id"]: e["name"] for e in _state["entries"] or []}
    best_name, best_gain = "", 0
    for uid, n in people.items():
        gain = n - best.get(uid, 0)
        if uid in names and gain > best_gain:
            best_name, best_gain = names[uid], gain
    banner = {"reviews": reviews, "time_ms": time_ms, "full_days": everyone,
              "days_known": known, "best_name": best_name}
    if w.get("milestone_week") == week and (w.get("banner") or {}).get("milestone"):
        banner["milestone"] = w["banner"]["milestone"]
    return banner


def _deck_deltas():
    base = _wrap_data().get("deck_base") or {}
    out = {}
    for e in _state["entries"] or []:
        for d in e.get("decks") or []:
            key = f"{e['user_id']}|{d.get('name', '')}"
            if key in base:
                delta = int(d.get("seen") or 0) - base[key]
                if delta > 0:
                    out[(e["user_id"], d.get("name", ""))] = delta
    return out


def _mute_knocker(uid):
    w = _wrap_data()
    muted = w.setdefault("muted_knocks", [])
    if uid not in muted:
        muted.append(uid)
        _save_wrap()
