"""Plans, the glue: at my own pace (3.8.0), and the plans' menus."""

import datetime
import html

from aqt import mw
from aqt.utils import tooltip

from .. import app
from .. import plans as P
from .. import schedule as S
from ..app import _bg
from ..app import _state
from ..app import cfg
from ..app import client
from ..errs import oops

from .morning import NEW_ORDER, _after_change, _deck_name, _filtered, _hold_yes, _open_now, _state_cfg, offer_hold
from .state import _deck_ok, _pcfg, _plan_doc, _psave, _swap, _today, followed, mine
from .lessons import _go_deck, _lesson_did, _lesson_drop, _lesson_prune, _undo_ok, lesson_deck_on, lesson_sync, refresh_progress
from .days import _raw
from .cards import open_one, waiting


# ---- 3.8.0: at my own pace ----

def _own_ctx(pid):
    p = next((x for x in followed() if x["id"] == pid), None)
    c = _pcfg()
    state = _state_cfg(c)
    st = state.get(pid)
    if p is None or not st or not mw.col or not _deck_ok(mw.col, st.get("deck_id")):
        return None
    return p, c, state, st


def _note_last(c, pid, u, kind, label, n, was):
    """What the plan card's line says (and its Undo undoes) while it's Anki's latest step."""
    c["own_last"] = {"pid": pid, "uid": u["id"], "name": str(u.get("name") or "?"), "kind": kind,
                     "label": label, "n": int(n), "day": _today(), "was": was}


def _was(st, uid):
    return {k: (st.get(k) or {}).get(uid) for k in ("applied", "src", "own_opened")}


def open_next(pid, study=False, uid=None):
    """You › Plans, Open: the next date at my own pace opens now, first in
    Anki's line of new cards, as one undo step. Open and study: then a Due
    Crew deck of its new cards, and into it. uid (3.8.1): that date
    instead (the week's Open now)."""
    got = _own_ctx(pid)
    if not got:
        return
    p, c, state, st = got
    today = _today()
    prog = (_state.get("plan_progress") or {}).get(pid) or {}
    left = ([x for x in P.units(p["doc"]) if x["id"] == uid] if uid
            else P.up_next(p["doc"], st.get("applied"), prog))
    if not left:
        if not uid:
            tooltip("Every set of this plan is open.")
        return
    u = left[0]
    # 3.8.1: a date further down Up next, opened first: the line says ahead of which
    nxt = [x["id"] for x in P.up_next(p["doc"], st.get("applied"), prog)] if uid else []
    ahead = next((x for x in P.units(p["doc"]) if x["id"] == nxt[0]), None) if u["id"] in nxt[1:] else None
    was = _was(st, u["id"])
    (st.get("applied") or {}).pop(u["id"], None)  # shut again since (Undo): it opens whole
    (st.get("src") or {}).pop(u["id"], None)
    try:
        res = open_one(mw.col, p, st, u["id"], today, first=True)
    except Exception:
        oops()
        return
    st.setdefault("own_opened", {})[u["id"]] = today
    c["plans"] = state
    if res["n"]:
        _note_last(c, pid, u, "open", res["label"], res["n"], was)
        if ahead:
            c["own_last"]["ahead"] = str(ahead.get("name") or "?")
    _psave(c)
    lesson_sync([p], fold=res["label"] if res["n"] else None)  # B: its deck, in the open's undo step (its Undo too)
    if res["n"]:
        _after_change()
    else:
        tooltip(f"Nothing in {html.escape(str(u.get('name') or 'it'))} to open: it's open already.")
    refresh_progress()
    if study and lesson_deck_on(pid):
        did = _lesson_did(pid, u["id"])  # B: Open and study goes to the lesson's own deck
        if did and _go_deck(did):
            return
    if study:
        idx = P.DeckIndex(mw.col, st["deck_id"])
        new = [c2 for c2 in idx.match(u, _swap(st), p["doc"]) if idx.cards[c2] == (0, 0)]
        name = _deck_name(u.get("name") or "date")
        if new and _filtered(mw.col, name, new, order=NEW_ORDER):
            _after_change()
            did = mw.col.decks.id_for_name(name)
            if did:
                mw.col.decks.select(did)
                mw.moveToState("overview")
                return
    app.swap(cfg())


def put_back_own(pid):
    """At my own pace, Put back: the last date I opened shuts again, only its
    cards I haven't seen (never a seen one, nor one another opened date
    has), as one undo step; it's Up next again. Stopping the plan opens them.
    3.8.1: they join `held` (what Stop opens), but Put back isn't a yes to
    Hold back: that's `hold_yes` now (before, any held card counted as one,
    and every later date's new cards were held each morning from then on)."""
    got = _own_ctx(pid)
    if not got:
        return
    p, c, state, st = got
    doc, applied = p["doc"], st.get("applied") or {}
    u = P.own_last(doc, st.get("own_opened"))
    if not u or not P.opened_here(applied, u):
        return
    idx = P.DeckIndex(mw.col, st["deck_id"])
    deck = doc
    others = set()
    for x in P.units(doc):
        if x["id"] != u["id"] and P.opened_here(applied, x):
            others |= idx.match(x, _swap(st), deck)
    cids = {c2 for c2 in idx.match(u, _swap(st), deck) - others if idx.cards[c2] == (0, 0)}
    label = f"Due Crew: put back {u.get('name') or 'a set'}"
    was = _was(st, u["id"])
    n = P.hold_cards(mw.col, cids, label) if cids else 0
    if n and st.get("lesson_deck"):
        try:
            _lesson_drop(mw.col, st, uids=[u["id"]], fold=label)  # B: Up next again, so its deck goes, in Put back's step
        except Exception:
            oops()
    for k in ("applied", "src", "own_opened"):
        (st.get(k) or {}).pop(u["id"], None)
    st["hold_yes"] = _hold_yes(p, st)  # settled before Put back adds to `held`, which isn't a yes
    if n:
        st["held"] = sorted(set(st.get("held") or []) | {int(x) for x in cids})
        _note_last(c, pid, u, "back", label, n, was)
    c["plans"] = state
    _psave(c)
    if n:
        _after_change()
    refresh_progress()
    app.swap(cfg())


def own_undo(pid):
    """The line's Undo after Open or Put back: Anki's own undo while it's its
    latest step, then the date is as it was."""
    last = _pcfg().get("own_last") or {}
    if last.get("pid") != pid or not _undo_ok(last.get("label")):
        tooltip("Anki has done something since. Use Edit › Undo.")
        app.swap(cfg())
        return

    def done(_out=None):
        pc = _pcfg()
        state = _state_cfg(pc)
        st = state.get(pid)
        if st is not None:
            for k, v in (last.get("was") or {}).items():
                if v is None:
                    (st.get(k) or {}).pop(last["uid"], None)
                else:
                    st.setdefault(k, {})[last["uid"]] = v
        if mw.col:
            _lesson_prune(mw.col, state)  # B: an Open's undo took its deck too
        pc["plans"] = state
        pc["own_last"] = {}
        _psave(pc)
        try:
            mw.update_undo_actions()
        except Exception:
            pass
        refresh_progress()
        app.swap(cfg())

    try:
        from aqt.operations import CollectionOp
    except ImportError:
        CollectionOp = None
    if CollectionOp is not None:
        CollectionOp(mw, lambda col: col.undo()).success(done).run_in_background()
        return
    try:
        mw.undo()
    except Exception:
        oops()
        return
    done()


def set_own(pid, own):
    """The plan's menu, How its cards open: mine, on the server (every
    computer and the site agree). Back on the plan's dates, what's opened by
    date since asks, as resuming does; at my own pace, a deck whose later
    cards are open is offered Hold back."""
    p = next((x for x in followed() if x["id"] == pid), None)
    if p is None or (p.get("own") or "") == (own or ""):
        return
    was, cl = p.get("own") or "", client()

    def done(res):
        if res is None:
            tooltip("Couldn't reach Due Crew. Check your connection.")
            return
        if was and not own:
            _resume(pid)
        elif own and not was:
            offer_hold([pid], words=lambda name, n, _own: (
                "Hold back the rest",
                f"{name}: {n:,} card{'s' if n != 1 else ''} of sets you haven't opened are open already. "
                "Hold them back until you open their set?\n\nOne undo step; stopping the plan opens them again.",
                "Hold back"))
            tooltip("Nothing opens by itself now. Open the next set from You › Plans.", period=5000)
        app.swap(cfg())

    _bg(lambda: cl.set_own(pid, own or None), done)


def own_view(plan, st, prog, today):
    """card_view's part at my own pace: Up next, then, where the plan's dates
    are, my pace (and the exam), the last step with its Undo, Put back."""
    doc = plan["doc"]
    st = st or {}
    applied, days, prog = st.get("applied") or {}, st.get("own_opened") or {}, prog or {}
    left = P.up_next(doc, applied, prog)

    def to_open(u):
        o, _s, t = (prog.get(u["id"]) or [0, 0, 0])[:3]
        return max(0, int(t) - int(o))
    last = None
    ol = (_pcfg().get("own_last") or {}) if mw else {}
    if ol.get("pid") == plan["id"] and ol.get("day") == today and mw and mw.col and _undo_ok(ol.get("label")):
        n = int(ol.get("n") or 0)
        ahead = f" (ahead of {ol['ahead']})" if ol.get("ahead") else ""  # 3.8.1: a later date, opened first
        last = (f"Opened {ol.get('name') or '?'}{ahead} · {n:,} card{'s' if n != 1 else ''}, first in line."
                if ol.get("kind") == "open" else f"Put back {ol.get('name') or '?'} · {n:,} card{'s' if n != 1 else ''}.")
    back = None
    lu = P.own_last(doc, days)
    if lu and not last and P.opened_here(applied, lu, prog):
        o, s2, _t = (prog.get(lu["id"]) or [0, 0, 0])[:3]
        if int(o) > int(s2):
            back = {"name": str(lu.get("name") or "?"), "n": int(o) - int(s2)}
    # 3.9.10 (Sam: the own-pace card "to match"): what I opened and haven't finished, a row each, Study or Ignore;
    # the lines measuring me against the author's dates (where the plan is, my pace, the finish) are gone
    opened = []
    for u in P.units(doc):
        o, s3, _t = (int(x or 0) for x in (list(prog.get(u["id"]) or []) + [0, 0, 0])[:3])
        if o > s3 and P.opened_here(applied, u, prog):
            opened.append({"uid": u["id"], "name": str(u.get("name") or "?"), "left": o - s3})
    return {"mode": plan.get("own"), "open": opened,
            "next": {"uid": left[0]["id"], "name": str(left[0].get("name") or "?"), "n": to_open(left[0])} if left else None,
            "then": [f"{u.get('name') or '?'} · {to_open(u):,}" for u in left[1:4]], "more": max(0, len(left) - 4),
            # 3.8.1: each a link, Open on that date (open_next(pid, uid))
            "then_items": [{"uid": u["id"], "name": str(u.get("name") or "?"), "n": to_open(u)} for u in left[1:4]],
            "last": last, "back": back}


def set_skip(pid, uid, on):
    """G3: skip a date (it never opens for me), or take the skip back
    (if its day has come, it opens now)."""
    p = _raw(pid)
    if p is None:
        return
    skipped = [u for u in p.get("skipped") or [] if u != uid] + ([uid] if on else [])
    cl = client()

    def done(got):
        if got is None:
            tooltip("Couldn't reach Due Crew. Check your connection.")
            return
        if not on and not got.get("paused"):
            _open_now([x for x in followed() if x["id"] == pid])
        app.swap(cfg())

    _bg(lambda: cl.set_days(pid, skipped=skipped), done)


def move_menu(pid, uid):
    """3.7.6: move one date later on my copy: the next seven days after it.
    A day on or after the event it preps for says so."""
    p = next((x for x in followed() if x["id"] == pid), None)
    u = next((x for x in P.units((p or {}).get("doc")) if x["id"] == uid), None)
    if p is None or u is None or not u.get("opens"):
        return
    raw = _raw(pid) or {}
    have = int((raw.get("moved") or {}).get(uid) or 0)
    ev = P.event_of(p["doc"], u)  # 3.8.1: by the event's id (its name never matched)
    from aqt.qt import QCursor, QMenu
    menu = QMenu(mw)
    head = menu.addAction(f"Move {u.get('name') or 'this set'} to")
    head.setEnabled(False)
    for k in range(1, 8):
        day = P._later(u["opens"], k)
        late = ev and str(ev.get("day") or "9999") <= day
        a = menu.addAction(f"{P.fmt_day(day)}" + (f" · after {ev.get('name')}" if late else ""))
        a.triggered.connect(lambda _=False, n=have + k: move_date(pid, uid, n))
    menu.exec(QCursor.pos())


def move_date(pid, uid, days):
    """Set how many days later this date runs for me (0: back on its day).
    Cards already open stay open; a date whose day has come opens."""
    raw = _raw(pid)
    if raw is None or not 0 <= int(days) <= 365:
        return
    moved = {k: int(v) for k, v in (raw.get("moved") or {}).items() if k != uid}
    if days:
        moved[uid] = int(days)
    cl = client()

    def done(got):
        if got is None:
            tooltip("Couldn't reach Due Crew. Check your connection.")
            return
        if not got.get("paused"):
            _open_now([x for x in followed() if x["id"] == pid], toast=False)
        u = next((x for x in P.units(raw.get("doc")) if x["id"] == uid), None)
        if u is not None and days:
            p = next((x for x in followed() if x["id"] == pid), None)
            mu = next((x for x in P.units((p or {}).get("doc")) if x["id"] == uid), None)
            if mu:
                tooltip(f"{html.escape(str(u.get('name') or 'It'))} moved to {P.fmt_day(mu['opens'])}.")
        app.swap(cfg())

    _bg(lambda: cl.set_days(pid, moved=moved), done)


def reset_lines(p):
    """3.7.6: what Reset to default puts back, as lines; [] when nothing."""
    out = []
    shift = int(p.get("shift") or 0)
    if shift:
        out.append(f"Your dates run {shift} day{'s' if shift != 1 else ''} later: back on time")
    names = {u["id"]: str(u.get("name") or "?") for u in P.units(p.get("doc"))}
    sk = [names.get(u, "?") for u in p.get("skipped") or [] if u in names]
    if sk:
        out.append(f"{len(sk)} skipped set{'s come' if len(sk) != 1 else ' comes'} back: " + ", ".join(sk[:3])
                   + (f" and {len(sk) - 3} more" if len(sk) > 3 else ""))
    mv = [names.get(u, "?") for u in (p.get("moved") or {}) if u in names]
    if mv:
        out.append(f"{len(mv)} moved set{'s go' if len(mv) != 1 else ' goes'} back: " + ", ".join(mv[:3])
                   + (f" and {len(mv) - 3} more" if len(mv) > 3 else ""))
    if p.get("paused") or p.get("until") or p.get("since"):
        out.append("Your pause ends")
    return out


def reset_days(pid):
    """3.7.6, Plan ▾ › Reset to default: my shift, skips, moved dates and
    pause back to the plan's, after saying exactly what. Cards already
    open stay open; dates that come back and have passed count as behind."""
    raw = _raw(pid)
    if raw is None:
        return
    lines = reset_lines(raw)
    if not lines:
        return
    from .. import sheets
    sheets.confirm("Reset to default?", "\n".join("\u2022 " + x for x in lines)
                   + "\n\nCards already open stay open. Sets that come back and have passed count as behind.",
                   "Reset", lambda: _reset_days(pid))


def _reset_days(pid):
    cl = client()

    def done(got):
        if got is None:
            tooltip("Couldn't reach Due Crew. Check your connection.")
            return
        _open_now([x for x in followed() if x["id"] == pid], toast=False)
        tooltip("Back to the plan's days.")
        app.swap(cfg())

    _bg(lambda: cl.set_days(pid, shift=0, skipped=[], moved={}, paused=False, until=None, since=None), done)


def pause_until(pid):
    """G4: pause until a day; my Away dates fill it in when they cover it."""
    p = _raw(pid)
    if p is None:
        return
    today = _today()
    c = cfg()
    away_to = str(c.get("away_to") or "")
    from_away = away_to >= today and str(c.get("away_from") or "") <= away_to
    until = away_to if from_away else S.iso(S.d(today) + datetime.timedelta(days=7))
    from ..ui.days_dialog import ask_pause
    got = ask_pause(mw, p.get("name") or "Plan", today, until, from_away)
    if not got:
        return
    cl = client()

    def done(res):
        if res is None:
            tooltip("Couldn't reach Due Crew. Check your connection.")
            return
        app.swap(cfg())

    _bg(lambda: cl.set_days(pid, paused=True, since=today, until=got), done)


def back(pid):
    """G4: back from a pause. Move my dates later by the days I was away,
    or open what opened meanwhile; either way, not paused any more."""
    p = _raw(pid)
    if p is None or not mw.col:
        return
    today = _today()
    st = _state_cfg().get(pid)
    # 3.8.1: at my own pace nothing opened by date while I was away: back without asking
    n_units, _n_cards = waiting(mw.col, mine(p), st, today) if st and not P.own_pace(p) else (0, 0)
    since = p.get("since") or today
    days = max(0, (S.d(today) - S.d(since)).days)
    choice = "open"
    if n_units and days:
        ev = P.prep_for(mine(p)["doc"], today)
        from ..ui.days_dialog import ask_back
        choice = ask_back(mw, n_units, days, (ev["name"], P.fmt_day(ev["day"])) if ev else None)
    shift = int(p.get("shift") or 0) + (days if choice == "push" else 0)
    cl = client()

    def done(res):
        if res is None:
            tooltip("Couldn't reach Due Crew. Check your connection.")
            return
        _open_now([x for x in followed() if x["id"] == pid])
        app.swap(cfg())

    _bg(lambda: cl.set_days(pid, paused=False, since=None, until=None, shift=min(365, shift)), done)


def set_shift(pid):
    """G7: Push my dates back…: how many days my dates run after the plan's."""
    p = _raw(pid)
    if p is None:
        return
    from ..ui.days_dialog import ask_shift
    n = ask_shift(mw, p.get("name") or "Plan", int(p.get("shift") or 0))
    if n is None or n == int(p.get("shift") or 0):
        return
    cl = client()

    def done(res):
        if res is None:
            tooltip("Couldn't reach Due Crew. Check your connection.")
            return
        if not res.get("paused"):
            _open_now([x for x in followed() if x["id"] == pid])  # fewer days may make a date due now
        app.swap(cfg())

    _bg(lambda: cl.set_days(pid, shift=n), done)


def _paused(col, did):
    """3.9.2's audit: the deck whose Stop new cards (Insights) runs today over
    this one, or None. Raise and Catch up stand aside for it: they'd undo it
    till the next morning set it again."""
    try:
        from .. import ahead_flow
        got = ahead_flow.paused(col, did)
    except Exception:
        oops()
        return None
    return got[0] if got else None


def _base_limit(col, did):
    """This deck's own new cards a day, not counting a today-only one."""
    try:
        deck = col.decks.get(int(did))
        if deck.get("newLimit") is not None:
            return int(deck["newLimit"])
        return int(col.decks.config_dict_for_deck_id(int(did))["new"]["perDay"])
    except Exception:
        return None


def apply_catch():
    """G5, each morning while a catch-up runs: Anki's today-only limit on the
    plan's deck, the deck's own plus the extra. It ends by itself at
    midnight, so there's nothing to put back afterwards."""
    if not mw.col:
        return
    col, today = mw.col, _today()
    for pid, st in _state_cfg().items():
        c = st.get("catch") or {}
        if not c or str(c.get("until") or "") < today or not _deck_ok(col, st.get("deck_id")):
            continue
        if _paused(col, st["deck_id"]):
            continue  # Stop new runs on it today
        base = _base_limit(col, st["deck_id"])
        if base is None:
            continue
        try:
            deck = col.decks.get(int(st["deck_id"]))
            want = {"limit": base + int(c.get("extra") or 0), "today": int(col.sched.today)}
            if deck.get("newLimitToday") == want:
                continue  # already so: no save, no undo step of its own (3.9.2's QoL pass)
            deck["newLimitToday"] = want
            col.decks.save(deck)
        except Exception:
            oops()


def catch_menu(pid):
    """G5: catch up over 3, 5 or 7 days; 3.8.0: or push my dates back, the
    other way to be on time again (Plan ▾ has it too)."""
    prog = (_state.get("plan_progress") or {}).get(pid) or {}
    p = next((x for x in followed() if x["id"] == pid), None)
    if p is None:
        return
    today = _today()
    n = P.waiting_new(p["doc"], prog, today)
    if not n:
        tooltip("Nothing's waiting from earlier sets now.")
        app.swap(cfg())
        return
    from aqt.qt import QCursor, QMenu
    menu = QMenu(mw)
    for days in (3, 5, 7):
        extra = -(-n // days)
        a = menu.addAction(f"Over {days} days (+{extra:,} new a day)")
        a.triggered.connect(lambda _=False, d=days, x=extra: start_catch(pid, d, x))
    menu.addSeparator()
    menu.addAction("Push my dates back…").triggered.connect(lambda: set_shift(pid))
    menu.exec(QCursor.pos())


def start_catch(pid, days, extra):
    c = _pcfg()
    state = _state_cfg(c)
    st = state.get(pid)
    if not st:
        return
    if mw.col and _paused(mw.col, st.get("deck_id")):
        tooltip("New cards are stopped in this deck. Turn them back on in Insights first.")
        return
    st["catch"] = {"until": S.iso(S.d(_today()) + datetime.timedelta(days=days - 1)), "extra": int(extra)}
    c["plans"] = state
    _psave(c)
    apply_catch()
    _after_change()
    tooltip(f"Anki shows {int(extra):,} more new cards a day in this deck for {days} days.")
    app.swap(cfg())


def stop_catch(pid):
    c = _pcfg()
    state = _state_cfg(c)
    st = state.get(pid)
    if not st:
        return
    st.pop("catch", None)
    c["plans"] = state
    _psave(c)
    if mw.col and _deck_ok(mw.col, st.get("deck_id")) and not _paused(mw.col, st.get("deck_id")):
        try:
            deck = mw.col.decks.get(int(st["deck_id"]))
            deck.pop("newLimitToday", None)
            mw.col.decks.save(deck)
        except Exception:
            oops()
    _after_change()
    app.swap(cfg())


def seen_change(pid):
    p = next((p for p in followed() if p["id"] == pid), None)
    c = _pcfg()
    state = _state_cfg(c)
    if p and pid in state:
        state[pid].update(seen_version=p.get("version"), snapshot=P.snapshot(_plan_doc(p)))
        c["plans"] = state
        _psave(c)
    app.swap(cfg())


def set_early(pid, days):
    """3.3, C2: open each date `days` early; what that opens, opens now."""
    cl = client()

    def done(ok):
        if not ok:
            tooltip("Couldn't reach Due Crew. Check your connection.")
            return
        p = next((x for x in followed() if x["id"] == pid), None)
        if p and not p.get("paused"):
            _open_now([p])
        app.swap(cfg())

    _bg(lambda: cl.set_early(pid, days), done)


def _planner_flow():
    from ..planner import flow
    return flow


def open_yours(pid=None):
    """3.9.3: Your plans (the plan window), on this plan when one's named."""
    _planner_flow().open_plans(select=pid)


def new_plan_menu():
    """3.9.3: You › Plans' New plan ▾ (round five: New plan, in Anki, the
    one way to start one; or on duecrew.com)."""
    from aqt.qt import QCursor, QMenu
    menu = QMenu(mw)
    menu.addAction("New plan…").triggered.connect(lambda: _planner_flow().open_new())
    menu.addAction("On duecrew.com ↗").triggered.connect(lambda: open_site("/plans"))
    menu.exec(QCursor.pos())


def plan_menu(pid):
    p = next((p for p in followed() if p["id"] == pid), None)
    if p is None:
        return
    from aqt.qt import QCursor, QMenu
    menu = QMenu(mw)
    menu.addAction("Open in Your plans").triggered.connect(lambda: open_yours(pid))  # 3.9.3
    menu.addSeparator()
    if p.get("sched"):  # 3.3: new follows do the plan's days; a 3.2 schedule can still change or go
        menu.addAction("My schedule…").triggered.connect(lambda: open_schedule(pid))
    how = menu.addMenu("How its cards open")  # 3.8.0: at my own pace
    for val, label in (("", "On the plan's dates"), ("ready", "When I'm ready"),
                       ("next", "When I'm ready, the next once I've seen most of the last")):
        a = how.addAction(label)
        a.setCheckable(True)
        a.setChecked((p.get("own") or "") == val)
        a.triggered.connect(lambda _=False, val=val: set_own(pid, val))
    menu.addAction("Open everything now").triggered.connect(lambda: open_everything(pid))
    n_held = held_count(pid)  # 3.8.1: what Hold back (or Put back) keeps shut, and why
    if n_held:
        menu.addAction(f"Held back: {n_held:,} card{'s' if n_held != 1 else ''}…").triggered.connect(lambda: show_held(pid))
    early = menu.addMenu("Open early")  # 3.3, C2: for studying on a phone
    early.setEnabled(not P.own_pace(p))
    for n, label in ((0, "Off"), (1, "1 day"), (2, "2 days"), (3, "3 days"), (5, "5 days"), (7, "7 days")):
        a = early.addAction(label)
        a.setCheckable(True)
        a.setChecked(int(p.get("early") or 0) == n)
        a.triggered.connect(lambda _=False, n=n: set_early(pid, n))
    # G3: skip a date I already know (the ones around now and ahead)
    skip = menu.addMenu("Skip a set")
    today = _today()
    week_ago = S.iso(S.d(today) - datetime.timedelta(days=7))
    ahead = [u for u in P.units(p["doc"]) if str(u.get("opens") or "") >= week_ago][:20]
    for u in ahead:
        a = skip.addAction(f"{u.get('name') or '?'} · {P.fmt_day(u['opens'])}")
        a.triggered.connect(lambda _=False, uid=u["id"]: set_skip(pid, uid, True))
    skip.setEnabled(bool(ahead))
    menu.addAction("Push my dates back…").triggered.connect(lambda: set_shift(pid))  # G4, G7
    menu.addAction("Change deck…").triggered.connect(lambda: change_deck(pid))
    if reset_lines(_raw(pid) or {}):  # 3.7.6: only once something's changed
        menu.addAction("Reset to default…").triggered.connect(lambda: reset_days(pid))
    menu.addSeparator()
    if p.get("paused"):
        menu.addAction("Resume").triggered.connect(lambda: back(pid) if p.get("since") else set_paused(pid, False))
    else:
        menu.addAction("Pause until…").triggered.connect(lambda: pause_until(pid))
    menu.addAction("Stop following").triggered.connect(lambda: stop_following(pid))
    menu.exec(QCursor.pos())


# Names of the parts after this one. The package sets them as each of those parts loads
# (an import here would load a later part before the ones between).
_LATER = ("_resume", "change_deck", "held_count", "open_everything", "open_schedule", "open_site",
          "set_paused", "show_held", "stop_following", "study")
_resume = change_deck = held_count = open_everything = open_schedule = open_site = None
set_paused = show_held = stop_following = study = None
