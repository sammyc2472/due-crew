"""3.8.2: Pip's closet, the glue. closet.py says what a thing needs; this
finds out what you've done:

- your reviews: the days and hours studied, read from the revlog in one
  grouped query a day (today's own hours read fresh, a small query), and
  the cards learned and leeches turned around (cards, one query each);
- the board: your crew, your squads and the plans you follow;
- a few tallies this computer keeps (wrap.json's "closet"): Fifteens,
  rooms with your crew, cheers you sent and got, a whole crew's day, days
  with nothing left due, cards you added, bingo lines.

What's earned goes to the account (sev_closet), and what Pip has on
(sev_look): both follow you to every computer, and the look rides with your
accent to mutual friends. Nothing new is asked of the server: a new thing
is a settings save, the same one any setting makes.

Main thread: collection and config. No network here.
"""

import datetime
import traceback

from aqt import mw

from . import closet
from .app import _state, cfg, save_cfg

LOOK_KEY, CLOSET_KEY = "sev_look", "sev_closet"
_TALLIES = ("fifteens", "fifteen_go", "fifteen_am", "rooms", "big_cheer", "cheered_by", "own_cards",
            "clear", "bingo_line", "bingo_card", "crew_day", "crew")
_LISTS = {"cheered": 40, "cheer_days": 40}
AM = 9  # a Fifteen begun before nine is a morning one


# ---- the tallies (wrap.json) ----

def clean_tallies(v):
    """wrap.json's "closet", as this add-on writes it, or less."""
    out = {}
    if not isinstance(v, dict):
        return out
    for k in _TALLIES:
        if isinstance(v.get(k), int) and not isinstance(v.get(k), bool) and 0 <= v[k] < 10 ** 7:
            out[k] = v[k]
    for k, n in _LISTS.items():
        if isinstance(v.get(k), list):
            out[k] = [x for x in v[k] if isinstance(x, str) and 0 < len(x) <= 128][-n:]
    for k in ("clear_last", "crew_day_last"):
        if isinstance(v.get(k), str) and len(v[k]) == 10:
            out[k] = v[k]
    if isinstance(v.get("clear_run"), int) and not isinstance(v.get("clear_run"), bool):
        out["clear_run"] = max(0, v["clear_run"])
    return out


def _tallies():
    from .wrap import _wrap_data
    w = _wrap_data()
    t = clean_tallies(w.get("closet"))
    w["closet"] = t
    return t


def _save():
    from .wrap import _save_wrap
    _save_wrap()


def _bump(key, by=1):
    t = _tallies()
    t[key] = t.get(key, 0) + by
    _save()


def _most(key, n):
    t = _tallies()
    if n > t.get(key, 0):
        t[key] = n
        _save()


def _add(key, item):
    t = _tallies()
    seen = t.setdefault(key, [])
    if item and item not in seen:
        seen.append(item)
        del seen[:-_LISTS[key]]
        _save()


def note_fifteens(n, began=None):
    """A session of fifteens ended: n of them; how many in one go; a morning's."""
    if n <= 0:
        return
    _bump("fifteens", n)
    _most("fifteen_go", n)
    if began is not None:
        try:
            if began.astimezone().hour < AM:
                _bump("fifteen_am", n)
        except Exception:
            pass


def note_room(with_crew):
    """A study room ended; with crewmates in it, it counts."""
    if with_crew:
        _bump("rooms")


def note_cheer(to_uid, day, big=False):
    """I cheered someone: a crewmate more, a day more; a big streak's."""
    _add("cheered", str(to_uid or ""))
    _add("cheer_days", str(day or ""))
    if big:
        _most("big_cheer", 1)


def note_cheered():
    """A crewmate's cheer landed."""
    _bump("cheered_by")


def note_card_added(*_args):
    """A note added in Anki's Add window: a card of my own."""
    try:
        _bump("own_cards")
    except Exception:
        traceback.print_exc()


def note_bingo(lines, full):
    """My squad's card: a line made, the whole card."""
    if lines > 0:
        _most("bingo_line", 1)
    if full:
        _most("bingo_card", 1)


def note_day(today, entries, studied, due_left):
    """At a refresh: a day with nothing left due (and studied), a run of
    them; a day my whole crew studied (a crewmate whose day is ahead of mine
    studied on their today, my tomorrow); the most crewmates I've had."""
    t = _tallies()
    changed = False
    others = [e for e in entries or [] if not e.get("you") and not e.get("paused")]
    if len([e for e in entries or [] if not e.get("you")]) > t.get("crew", 0):
        t["crew"] = len([e for e in entries or [] if not e.get("you")])
        changed = True
    if studied and due_left == 0 and t.get("clear_last") != today:
        try:
            yday = (datetime.date.fromisoformat(today) - datetime.timedelta(days=1)).isoformat()
        except ValueError:
            yday = ""
        t["clear_run"] = t.get("clear_run", 0) + 1 if t.get("clear_last") == yday else 1
        t["clear_last"] = today
        t["clear"] = max(t.get("clear", 0), t["clear_run"])
        changed = True
    try:
        soon = (today, (datetime.date.fromisoformat(today) + datetime.timedelta(days=1)).isoformat())
    except ValueError:
        soon = (today,)
    if (studied and others and t.get("crew_day_last") != today
            and all(any(_showed((e.get("days") or {}).get(lb)) for lb in soon) for e in others)):
        t["crew_day"] = t.get("crew_day", 0) + 1
        t["crew_day_last"] = today
        changed = True
    if changed:
        _save()


def _showed(day):
    from .board import _showed as showed
    try:
        return showed(day)
    except Exception:
        return False


# ---- the revlog: days and hours ----

_RF = {"key": None, "hours": {}, "facts": {}}


def _buckets(col, lo_ms, hi_ms):
    """{hours before the cutoff: answers} for answers in [lo, hi)."""
    cut = int(col.sched.day_cutoff)
    rows = col.db.all("SELECT CAST((? - id / 1000) / 3600 AS INTEGER), COUNT(*) FROM revlog "
                      "WHERE ease > 0 AND id >= ? AND id < ? GROUP BY 1", cut - 1, lo_ms, hi_ms)
    return {int(h): int(n) for h, n in rows or []}


def revlog_facts(col):
    """The facts the revlog gives: days, runs, comebacks, seasons, secrets,
    mornings and evenings, reviews, cards learned, leeches turned around.
    The days before today are read once a day; today's hours each time."""
    cut = int(col.sched.day_cutoff)
    today_ms = (cut - 86400) * 1000
    if _RF["key"] != cut:
        _RF["hours"] = _buckets(col, 0, today_ms)
        _RF["key"] = cut
    hours = dict(_RF["hours"])
    for h, n in _buckets(col, today_ms, cut * 1000).items():
        hours[h] = hours.get(h, 0) + n
    end = datetime.date.fromtimestamp(cut)
    labels = {(end - datetime.timedelta(days=h // 24 + 1)).isoformat() for h in hours}
    starts = [datetime.datetime.fromtimestamp(cut - (h + 1) * 3600) for h in hours]
    out = closet.from_days(labels)
    out.update(closet.from_hours(starts))
    out["reviews"] = sum(hours.values())
    out["learned"] = int(col.db.scalar("SELECT COUNT() FROM cards WHERE type IN (2, 3)") or 0)
    out["leeches"] = int(col.db.scalar("SELECT COUNT() FROM cards WHERE lapses >= 8 AND type = 2 "
                                       "AND ivl >= 21 AND queue >= 0") or 0)
    return out


# ---- the board ----

def board_facts(c, entries, me_uid, plans, progress, today, have):
    """What the board knows: squads (founded one?), plans followed and done,
    a year with my Pip. Pure over its arguments."""
    squads = [q for q in (c.get("squads") or []) if isinstance(q, dict)]
    out = {"squads": len(squads), "founder": int(any(me_uid and q.get("founder") == me_uid for q in squads)),
           "plans": len(plans or [])}
    done = exam = 0
    for p in plans or []:
        prog = (progress or {}).get(p.get("id")) or {}
        units = [u for u in (p.get("doc") or {}).get("units") or [] if isinstance(u, dict) and u.get("id")]
        if units and all(int((prog.get(u["id"]) or [0, 0, 0])[2]) and
                         int((prog.get(u["id"]) or [0, 0, 0])[1]) >= int((prog.get(u["id"]) or [0, 0, 0])[2]) for u in units):
            done += 1
            evs = [str(e.get("day")) for e in (p.get("doc") or {}).get("events") or [] if isinstance(e, dict) and e.get("day")]
            if evs and max(evs) < today:
                exam += 1
    out.update(plan_done=done, plan_exam=exam)
    first = min(closet.clean_closet(have).values() or [today])
    try:
        out["sev_days"] = (datetime.date.fromisoformat(today) - datetime.date.fromisoformat(first)).days
    except ValueError:
        out["sev_days"] = 0
    return out


def facts(c=None):
    """Everything the closet asks, from here. Main thread."""
    c = c or cfg()
    out = dict(_tallies())
    if mw.col:
        try:
            out.update(revlog_facts(mw.col))
        except Exception:
            traceback.print_exc()
    try:
        from . import plan_flow
        from .app import client
        today = _state["labels"][0] if _state["labels"] else datetime.date.today().isoformat()
        out.update(board_facts(c, _state["entries"], client().session.get("user_id"), plan_flow.followed(),
                               _state.get("plan_progress") or {}, today, c.get(CLOSET_KEY)))
    except Exception:
        traceback.print_exc()
    out["crew"] = max(out.get("crew", 0), len([e for e in _state["entries"] or [] if not e.get("you")]))
    for k in ("cheered", "cheer_days"):
        out[k] = len(out.get(k) or [])
    return out


# ---- what's earned, what's worn ----

def have(c=None):
    return closet.clean_closet((c or cfg()).get(CLOSET_KEY))


def look(c=None):
    """What my Pip has on: things I have, as the closet draws them."""
    c = c or cfg()
    mine = have(c)
    return [k for k in closet.clean(c.get(LOOK_KEY)) if k in mine]


def check(today):
    """At a refresh: anything newly earned goes in the closet (one settings
    save, only when there's something), the newest for the board to say.
    Once a day is enough for the revlog; the tallies count as they happen."""
    c = cfg()
    try:
        f = facts(c)
    except Exception:
        traceback.print_exc()
        return []
    got = closet.new(f, have(c), today)
    if not got:
        return []
    c = dict(c)
    c[CLOSET_KEY] = dict(have(c), **got)
    first = not have()
    save_cfg(c)
    # the day the closet comes, what you'd earned already arrives all at once: one line for it
    _state["closet_new"] = {"keys": list(got), "first": first, "day": today}
    return list(got)


def wear(k):
    """Put a thing on, or take it off. Only what's mine."""
    c = cfg()
    if k not in have(c):
        return False
    c = dict(c)
    c[LOOK_KEY] = closet.wear(look(c), k)
    save_cfg(c)
    return True


def near(c=None):
    return standing(c)[0]


def standing(c=None):
    """(near, progress) for the closet: the few I'm close to, and how far
    along every thing that counts up is. One read of the facts."""
    try:
        f, mine = facts(c), have(c)
        return closet.near(f, mine), closet.progress(f, mine)
    except Exception:
        traceback.print_exc()
        return [], {}


_HOOKED = {"done": False}


def hook():
    """Cards I add in Anki's Add window count as my own."""
    if _HOOKED["done"]:
        return
    _HOOKED["done"] = True
    try:
        from aqt import gui_hooks
        gui_hooks.add_cards_did_add_note.append(note_card_added)
    except Exception:
        traceback.print_exc()

