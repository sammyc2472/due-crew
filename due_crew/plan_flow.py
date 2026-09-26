"""3.1 plans, the glue: what this computer remembers about the plans I
follow, the morning, progress for the sync, the Decks tab's plan card,
and the menus. Main-thread rules as in __init__: every collection read and
the one unsuspend step happen here, on the main thread; plan_flow never
makes a request of its own except on a click (follow, pause, stop).

Per computer, in config `plans`: {plan id: {deck_id, swap, applied:
{unit id: sig | "skip:" + sig}, seen_version, snapshot}}. Follow, share
and pause live on the server; the board's plans are cached in the session
(api.fetch_board), so a light refresh and an offline morning have them.

The morning is once per Anki day (config `plans_day`): after the day's
AnkiWeb sync, or at the first refresh when this profile doesn't sync. It
never suspends anything: a unit removed, a date moved later, a plan
stopped all leave open cards open.
"""

import datetime
import html
import traceback

from aqt import mw
from aqt.utils import tooltip

from . import app
from . import plans as P
from .app import _bg, _state, cfg, client, save_cfg


def _today():
    from .stats.queries import StatsQueries
    return StatsQueries(mw.col).day_label(0)


def _deck_ok(col, did):
    try:
        d = col.decks.get(int(did), default=False)
    except Exception:
        return False
    return bool(d) and not d.get("dyn")


def _sig(st):
    return lambda u: P.unit_sig(u, st.get("deck_id"), st.get("swap"))


def _swap(st):
    s = st.get("swap")
    return tuple(s) if s else None


def followed():
    """The plans I follow, as the last day's-first refresh brought them."""
    return [p for p in client().session.get("plans") or [] if isinstance(p, dict) and p.get("id")]


# ---- pure over a collection: tested in tests/test_due_crew.py ----

def new_state(col, plan, deck_id=None, swap=None):
    """This computer's state for a plan: the deck it runs on (the best
    match unless given) and nothing applied yet. None when no deck here
    has any of it."""
    if deck_id is None:
        deck_id, swap = P.best_deck(col, plan["doc"])
    if deck_id is None:
        return None
    return {"deck_id": int(deck_id), "swap": list(swap) if swap else None, "applied": {},
            "seen_version": plan.get("version") or 0, "snapshot": P.snapshot(plan["doc"])}


def run(col, plan_list, state, today, mode=None, everything=False):
    """Open what's due (or, with `everything`, every unit) for these plans,
    in one undo step. mode "skip" marks due units applied without opening
    them (joining late, "Start from the next unit"); "open" is the default.
    A unit a late join skipped stays skipped unless `everything`. Mutates
    `state`. Returns {n, names, label, per: {plan id: [names, n]}}."""
    all_cids, names, per = set(), [], {}
    for p in plan_list:
        st = state.get(p["id"])
        if not st or not _deck_ok(col, st.get("deck_id")):
            continue
        doc = p["doc"]
        applied = st.setdefault("applied", {})
        sig = _sig(st)
        items = ([(u, "open") for u in P.units(doc)] if everything
                 else P.due_now(doc, applied, today, sig))
        if not items:
            continue
        idx = P.DeckIndex(col, st["deck_id"])
        pnames, pcids = [], set()
        for u, how in items:
            if how == "open" and mode != "skip":
                cids = idx.match(u, _swap(st), doc.get("deck", ""))
                applied[u["id"]] = sig(u)
                if idx.suspended(cids):
                    pnames.append(u.get("name") or "?")
                    pcids |= cids
            else:
                applied[u["id"]] = "skip:" + sig(u)
        if pnames:
            per[p["id"]] = [pnames, len(idx.suspended(pcids))]
            names += pnames
            all_cids |= pcids
    label = P.step_label(names) if names else ""
    n = P.open_cards(col, all_cids, label) if names else 0
    return {"n": n, "names": names, "label": label, "per": per}


def waiting(col, plan, st, today):
    """(units, cards) that have opened by date and aren't applied here:
    what a late join or a resume asks about."""
    if not st or not _deck_ok(col, st.get("deck_id")):
        return 0, 0
    due = [u for u, how in P.due_now(plan["doc"], st.get("applied") or {}, today, _sig(st)) if how == "open"]
    if not due:
        return 0, 0
    idx = P.DeckIndex(col, st["deck_id"])
    cids = set()
    for u in due:
        cids |= idx.match(u, _swap(st), plan["doc"].get("deck", ""))
    return len(due), len(cids)


def progress(col, plan_list, state):
    """{plan id: {unit id: [opened, seen, total]}} for the plans that run here."""
    out = {}
    for p in plan_list:
        st = state.get(p["id"])
        if not st or not _deck_ok(col, st.get("deck_id")):
            continue
        idx = P.DeckIndex(col, st["deck_id"])
        out[p["id"]] = P.progress(idx, p["doc"], _swap(st))
    return out


def to_send(plan_list, prog):
    """What the sync carries: progress on the plans I share it on, at most 50."""
    share = {p["id"] for p in plan_list if p.get("share")}
    return dict([(pid, units) for pid, units in sorted(prog.items()) if pid in share and units][:50])


def _short_day(iso, today):
    """"Mon" within the coming week, else "Mon 26 Oct"."""
    try:
        d, t = datetime.date.fromisoformat(iso), datetime.date.fromisoformat(today)
    except ValueError:
        return str(iso)
    return f"{d:%a}" if 0 <= (d - t).days < 7 else P.fmt_day(iso)


def card_view(plan, st, prog, today, opened=None, undo_ok=False):
    """What board._plans_html draws for one plan. Strings are raw here;
    the board escapes them."""
    doc = plan["doc"]
    week, weeks = P.span_weeks(doc, today)
    us = P.units(doc)
    if plan.get("paused"):
        sub = "paused"
    elif week == 0 and us:
        sub = f"starts {P.fmt_day(us[0]['opens'])}"
    else:
        sub = f"week {week} of {weeks}"
    sub += f" · {int(plan.get('followers') or 0):,} following"
    followers = int(plan.get("followers") or 0)
    crew = plan.get("crewDone") or {}
    rows = []
    open_units = P.opened_by_date(doc, today)
    current = [u for u in open_units if u.get("due") and u["due"] >= today]
    now_id = current[0]["id"] if current else (open_units[-1]["id"] if open_units else None)
    for u in open_units:
        o, s, t = (prog or {}).get(u["id"], [0, 0, 0])
        done = int(crew.get(u["id"]) or 0)
        n = f"{done:,} of {followers:,}"
        if u["id"] == now_id and u.get("due") and u["due"] >= today:
            n += f" · due {_short_day(u['due'], today)}"
        rows.append({"name": u.get("name") or "?", "state": "now" if u["id"] == now_id else "open",
                     "seen": [s, t], "crew": [done, followers], "n": n, "missing": not t})
    nxt = P.next_unit(doc, today)
    if nxt:
        rows.append({"name": nxt.get("name") or "?", "state": "later", "seen": None, "crew": None,
                     "n": f"opens {P.fmt_day(nxt['opens'])}", "missing": False})
    no_deck = not st
    change = None
    if st and st.get("snapshot") is not None and st.get("seen_version") != plan.get("version"):
        change = P.change_note(plan.get("ownerName"), st["snapshot"], doc)
    return {"id": plan["id"], "title": P.plan_title(plan), "sub": sub, "rows": rows,
            "opened": ({"names": opened[0], "n": opened[1], "undo": bool(undo_ok)}
                       if opened and opened[1] else None),
            "lines": [] if no_deck or plan.get("paused") else P.ahead_behind(doc, prog or {}, today),
            "change": change, "no_deck": no_deck, "paused": bool(plan.get("paused"))}


def offers_view(offers, squad_names, following_ids, dismissed):
    return [{"id": o["id"], "owner": o.get("ownerName") or "?", "name": o.get("name") or "Plan",
             "squad": squad_names.get(o.get("squad"), "your squad")}
            for o in offers or [] if o["id"] not in following_ids and o["id"] not in dismissed][:2]


# ---- the glue (aqt) ----

def _state_cfg(c=None):
    c = cfg() if c is None else c
    st = c.get("plans")
    return st if isinstance(st, dict) else {}


def _after_change():
    """What a CollectionOp does after an op: the Edit menu learns the new
    undo step, and the screens that show cards redraw."""
    try:
        mw.update_undo_actions()
    except Exception:
        pass
    try:
        from anki.collection import OpChanges
        from aqt import gui_hooks
        gui_hooks.operation_did_execute(OpChanges(card=True, browser_table=True, study_queues=True), None)
    except Exception:
        pass


def _toast_opened(res):
    if not res["n"]:
        return
    what = res["names"][0] if len(res["names"]) == 1 else f"{len(res['names'])} dates"
    tooltip(f"Due Crew opened {html.escape(what)}: {res['n']:,} card{'s' if res['n'] != 1 else ''}",
            period=5000)


def _open_now(plan_list, mode=None, everything=False):
    """Main thread: run, remember, say so, redraw."""
    if not mw.col:
        return None
    c = cfg()
    state = _state_cfg(c)
    today = _today()
    try:
        res = run(mw.col, plan_list, state, today, mode=mode, everything=everything)
    except Exception:
        traceback.print_exc()
        return None
    c["plans"] = state
    if res["n"]:
        c["plans_opened"] = {"day": today, "label": res["label"], "per": res["per"]}
    save_cfg(c)
    if res["n"]:
        _after_change()
        _toast_opened(res)
    refresh_progress()
    return res


def maybe_morning(awaiting_sync, fresh=False):
    """Main thread. Once per Anki day, for each followed, unpaused plan:
    open what's due. Waits for the day's AnkiWeb sync when this profile
    syncs (the phone's reviews, and the other computer's opened cards,
    come in with it). fresh: the plans just came with the day's refresh,
    so plans no longer followed are forgotten here."""
    if not mw.col or not client().signed_in:
        return
    try:
        c = cfg()
        state = _state_cfg(c)
        plan_list = followed()
        if fresh:
            ids = {p["id"] for p in plan_list}
            gone = [pid for pid in state if pid not in ids]
            for pid in gone:
                state.pop(pid, None)  # stopped, or taken down: nothing is suspended
            changed = bool(gone)
            for p in plan_list:
                st = state.get(p["id"])
                if st and st.get("seen_version") != p.get("version") and st.get("snapshot") is not None \
                        and P.change_note(p.get("ownerName"), st["snapshot"], p["doc"]) is None:
                    # a change with nothing to say (cards added, a name kept): noted quietly
                    st.update(seen_version=p.get("version"), snapshot=P.snapshot(p["doc"]))
                    changed = True
            if changed:
                c["plans"] = state
                save_cfg(c)
        today = _today()
        if awaiting_sync or c.get("plans_day") == today:
            return
        for p in plan_list:
            if p["id"] not in state:
                st = new_state(mw.col, p)  # followed on another computer
                if st:
                    state[p["id"]] = st
        c = cfg()
        c["plans"] = state
        c["plans_day"] = today
        save_cfg(c)
        _open_now([p for p in plan_list if not p.get("paused")])
    except Exception:
        traceback.print_exc()


def refresh_progress():
    """Main thread: my numbers per unit, for the card and the next sync."""
    if not mw.col:
        return {}
    try:
        prog = progress(mw.col, followed(), _state_cfg())
    except Exception:
        traceback.print_exc()
        return {}
    _state["plan_progress"] = prog
    return prog


def for_sync():
    """Main thread, at every sync: progress on the plans I share it on.
    None when I follow nothing (and never did), so the sync is unchanged."""
    plan_list = followed()
    if not plan_list and not client().session.get("plans_hash"):
        return None
    return to_send(plan_list, refresh_progress())


def _undo_ok(label):
    try:
        return bool(label) and mw.col.undo_status().undo == label
    except Exception:
        return False


def board_view(c):
    """{cards, offers} for the board, from cache. Main thread (one undo-queue
    look; no collection reads)."""
    plan_list = followed()
    state = _state_cfg(c)
    today = _state["labels"][0] if _state["labels"] else ""
    if not today:
        return {"cards": [], "offers": []}
    opened = c.get("plans_opened") if isinstance(c.get("plans_opened"), dict) else {}
    fresh_open = opened.get("day") == today
    undo = fresh_open and _undo_ok(opened.get("label"))
    prog = _state.get("plan_progress") or {}
    cards = [card_view(p, state.get(p["id"]), prog.get(p["id"]), today,
                       opened=(opened.get("per") or {}).get(p["id"]) if fresh_open else None,
                       undo_ok=undo)
             for p in plan_list]
    from .squads import _my_squads
    names = {sq["id"]: sq.get("name") or "" for sq in _my_squads(c)}
    offers = offers_view(client().session.get("plan_offers"), names, {p["id"] for p in plan_list},
                         set(c.get("plan_offers_dismissed") or []))
    return {"cards": cards, "offers": offers}


# ---- board commands ----

def on_message(cmd, parts):
    """duecrew:plan* from the board. True when handled."""
    arg = parts[2] if len(parts) > 2 else ""
    if cmd == "planundo":
        undo_morning()
    elif cmd == "planmenu" and arg:
        plan_menu(arg)
    elif cmd == "planok" and arg:
        seen_change(arg)
    elif cmd == "plandeck" and arg:
        change_deck(arg)
    elif cmd == "planlook" and arg:
        offer = next((o for o in client().session.get("plan_offers") or [] if o.get("id") == arg), None)
        if offer:
            open_follow(code=offer.get("code") or "")
    elif cmd == "planofferx" and arg:
        c = cfg()
        c["plan_offers_dismissed"] = (list(c.get("plan_offers_dismissed") or []) + [arg])[-50:]
        save_cfg(c)
        app.swap(c)
    else:
        return False
    return True


def undo_morning():
    """The board's Undo: Anki's own undo, only while the step is its latest."""
    c = cfg()
    opened = c.get("plans_opened") or {}
    if not _undo_ok(opened.get("label")):
        tooltip("Anki has done something since. Use Edit › Undo.")
        app.swap(c)
        return
    try:
        from aqt.operations.collection import undo
        undo(parent=mw)
    except Exception:
        try:
            mw.undo()
        except Exception:
            traceback.print_exc()
            return
    # the units stay marked as applied: the next morning won't open them again
    c["plans_opened"] = {}
    save_cfg(c)
    refresh_progress()
    app.swap(c)


def seen_change(pid):
    p = next((p for p in followed() if p["id"] == pid), None)
    c = cfg()
    state = _state_cfg(c)
    if p and pid in state:
        state[pid].update(seen_version=p.get("version"), snapshot=P.snapshot(p["doc"]))
        c["plans"] = state
        save_cfg(c)
    app.swap(c)


def plan_menu(pid):
    p = next((p for p in followed() if p["id"] == pid), None)
    if p is None:
        return
    from aqt.qt import QCursor, QMenu
    menu = QMenu(mw)
    menu.addAction("Open everything now").triggered.connect(lambda: open_everything(pid))
    menu.addAction("Change deck…").triggered.connect(lambda: change_deck(pid))
    menu.addSeparator()
    menu.addAction("Resume" if p.get("paused") else "Pause").triggered.connect(
        lambda: set_paused(pid, not p.get("paused")))
    menu.addAction("Stop following").triggered.connect(lambda: stop_following(pid))
    menu.exec(QCursor.pos())


def open_everything(pid):
    p = next((p for p in followed() if p["id"] == pid), None)
    if p is None or not _ensure_deck(p):
        return
    res = _open_now([p], everything=True)
    if res is not None and not res["n"]:
        tooltip("Everything in this plan is already open.")
    app.swap(cfg())


def _ensure_deck(p):
    c = cfg()
    state = _state_cfg(c)
    if state.get(p["id"]) and _deck_ok(mw.col, state[p["id"]].get("deck_id")):
        return True
    change_deck(p["id"])
    return bool(_state_cfg().get(p["id"]))


def change_deck(pid):
    """Pick the deck this plan runs on here. Units already opened open on
    the new deck too (their sig names the deck); skipped ones stay skipped."""
    p = next((p for p in followed() if p["id"] == pid), None)
    if p is None or not mw.col:
        return
    from aqt.qt import QInputDialog
    choices = P.deck_choices(mw.col)
    if not choices:
        return
    c = cfg()
    state = _state_cfg(c)
    st = state.get(pid)
    best, _swap_guess = P.best_deck(mw.col, p["doc"], choices)
    current = st.get("deck_id") if st else best
    names = [n for _d, n in choices]
    at = next((i for i, (d, _n) in enumerate(choices) if d == current), 0)
    name, ok = QInputDialog.getItem(mw, "Change deck", f"Run {p.get('name') or 'the plan'} on", names, at, False)
    if not ok:
        return
    did = next(d for d, n in choices if n == name)
    idx = P.DeckIndex(mw.col, did)
    swap = P.detect_swap(idx, p["doc"])
    if swap:
        from .ui.follow_dialog import ask_swap
        if not ask_swap(mw, swap, P.found_total(idx, p["doc"], swap)):
            swap = None
    if st:
        st.update(deck_id=did, swap=list(swap) if swap else None)
    else:
        state[pid] = new_state(mw.col, p, did, swap)
    c["plans"] = state
    save_cfg(c)
    if p.get("paused"):
        refresh_progress()
    else:
        _open_now([p])
    app.swap(cfg())


def set_paused(pid, paused):
    cl = client()

    def done(res):
        if res is None:
            tooltip("Couldn't reach Due Crew. Check your connection.")
            return
        if not paused:
            _resume(pid)
        app.swap(cfg())

    _bg(lambda: cl.set_follow(pid, paused=paused), done)


def _resume(pid):
    """Resuming asks the catch-up question, as following does."""
    p = next((p for p in followed() if p["id"] == pid), None)
    if p is None or not mw.col:
        return
    today = _today()
    n_units, n_cards = waiting(mw.col, p, _state_cfg().get(pid), today)
    if not n_units:
        return
    from .ui.follow_dialog import ask_catch_up
    nxt = P.next_unit(p["doc"], today)
    choice = ask_catch_up(mw, n_units, n_cards, nxt)
    if choice is None:
        return
    _open_now([p], mode=choice)


def stop_following(pid):
    p = next((p for p in followed() if p["id"] == pid), None)
    if p is None:
        return
    from .ui import confirm
    if not confirm(mw, "Stop following",
                   f"Stop following {p.get('name') or 'this plan'}?\n\n"
                   "Nothing gets suspended. Cards already open stay open, and the crew "
                   "stops seeing your progress on this plan.", "Stop"):
        return
    cl = client()

    def done(ok):
        if not ok:
            tooltip("Couldn't reach Due Crew. Check your connection.")
            return
        c = cfg()
        state = _state_cfg(c)
        state.pop(pid, None)
        c["plans"] = state
        save_cfg(c)
        _state.get("plan_progress", {}).pop(pid, None)
        app.swap(c)

    _bg(lambda: cl.unfollow_plan(pid), done)


# ---- following ----

def open_follow(code=""):
    if not client().signed_in:
        tooltip("Sign in to Due Crew first.")
        return
    if not mw.col:
        return
    from .ui.follow_dialog import FollowDialog
    dlg = FollowDialog(mw, client(), mw.col, code=code, today=_today(), on_followed=on_followed)
    dlg.exec()


def on_followed(plan, deck_id, swap, late):
    """Main thread, after POST /plans/follow: this computer runs it on
    `deck_id`; late is "open" (open what has opened) or "skip"."""
    cl = client()
    cl.remember_plan(plan)
    c = cfg()
    state = _state_cfg(c)
    state[plan["id"]] = new_state(mw.col, plan, deck_id, swap)
    c["plans"] = state
    save_cfg(c)
    res = _open_now([plan], mode=late)
    if res is not None and not res["n"]:
        tooltip(f"Following {html.escape(plan.get('name') or 'the plan')}.")
    app.swap(cfg())


def open_make():
    if not client().signed_in:
        tooltip("Sign in to Due Crew first.")
        return
    if not mw.col:
        return
    from .ui.plan_dialog import MakePlanDialog
    MakePlanDialog(mw, client(), mw.col, site_base()).exec()


def site_base():
    import os
    return (str(cfg().get("site_base") or "") or os.environ.get("DUE_CREW_SITE")
            or "https://duecrew.com").rstrip("/")


# ---- Anki's browser ----

def browser_menu(browser, menu):
    """gui_hooks.browser_will_show_context_menu: single cards onto a date."""
    if not client().signed_in:
        return
    menu.addSeparator()
    action = menu.addAction("Due Crew: add to a plan…")
    action.triggered.connect(lambda: add_to_plan(browser))


def add_to_plan(browser):
    try:
        cids = browser.selected_cards()
    except AttributeError:
        cids = browser.selectedCards()
    if not cids or not mw.col:
        return
    refs = P.card_refs(mw.col, cids)  # which cards, never their text
    from .ui.add_cards_dialog import AddCardsDialog
    AddCardsDialog(browser, client(), refs, _today()).exec()
