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

def _wrap_data():
    key = _profile_key()
    if _wrap["profile"] != key:
        _wrap["profile"] = key
        try:
            with open(os.path.join(_profile_files(), "wrap.json")) as f:
                _wrap["data"] = json.load(f)
        except Exception:
            _wrap["data"] = {}
    return _wrap["data"]


def _save_wrap():
    try:
        with open(os.path.join(_profile_files(), "wrap.json"), "w") as f:
            json.dump(_wrap["data"], f)
    except OSError:
        pass


def _week_key(label):
    year, week, _day = datetime.date.fromisoformat(label).isocalendar()
    return f"{year}-W{week:02d}"


def _update_wrap(entries, labels):
    """New-week bookkeeping. Returns a milestone toast string, or None."""
    w = _wrap_data()
    week = _week_key(labels[0])
    if w.get("week") == week:
        return None
    totals_r = totals_t = 0
    best = w.setdefault("best", {})
    best_name, best_gain = "", 0
    for e in entries:
        agg = board._week_row(e["days"], labels) or {}
        reviews = agg.get("reviews") or 0
        totals_r += reviews
        totals_t += agg.get("time_ms") or 0
        gain = reviews - best.get(e["user_id"], 0)
        if reviews > 0 and gain > best_gain:
            best_name, best_gain = e["name"], gain
        if reviews > best.get(e["user_id"], 0):
            best[e["user_id"]] = reviews
    w["banner"] = {"reviews": totals_r, "time_ms": totals_t,
                   "best_name": best_name,
                   "full_days": board._full_crew_days(entries, labels)}
    w["week"] = week
    w["dismissed"] = ""
    w["deck_base"] = {f"{e['user_id']}|{d.get('name', '')}": int(d.get("seen") or 0)
                      for e in entries for d in (e.get("decks") or [])}
    toast = _accrue_milestones(w, totals_r, totals_t, labels[0])
    _save_wrap()
    return toast


def _accrue_milestones(w, week_reviews, week_time_ms, today_label):
    """Lifetime crew totals, accrued weekly, celebrated at thresholds.
    Local arithmetic only; "since" is when accrual began, never an estimate."""
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
    w["banner"]["milestone"] = crossed
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
    w = _wrap_data()
    if not _state["labels"] or w.get("week") != _week_key(_state["labels"][0]):
        return None
    if w.get("dismissed") == w.get("week"):
        return None
    banner = w.get("banner") or {}
    return banner if banner.get("reviews") else None


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
