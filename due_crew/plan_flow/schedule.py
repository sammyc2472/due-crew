"""Plans, the glue: my schedule (3.2)."""

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

from .morning import _after_change, _drop_plan_tags, _open_now, _state_cfg
from .state import _deck_ok, _pcfg, _psave, _swap, _today, followed
from .lessons import _lesson_drop, refresh_progress
from .cards import new_state, waiting


# ---- 3.2: my schedule ----

def study(pid):
    """The session card's Study now: the plan's deck, in Anki's own review."""
    st = _state_cfg().get(pid)
    if not st or not mw.col or not _deck_ok(mw.col, st.get("deck_id")):
        return
    try:
        mw.col.decks.select(int(st["deck_id"]))
        mw.moveToState("review")
    except Exception:
        oops()


def set_catch(pid, mode):
    """The missed-days question answered: spread what's waiting over the
    next few study days, or leave it open with no target. Mine only."""
    c = _pcfg()
    state = _state_cfg(c)
    if pid not in state:
        return
    state[pid]["missed"] = {"mode": mode, "day": _today()}  # 3.8.1: its own key (`catch` is G5's catch-up)
    c["plans"] = state
    _psave(c)
    refresh_progress()
    app.swap(cfg())


def push_back(pid):
    """Every date of mine later by the study days I missed; the plan and the
    crew's dates stay put. One request."""
    p = next((p for p in followed() if p["id"] == pid), None)
    sess = (_state.get("plan_session") or {}).get(pid) or {}
    ask = sess.get("ask") or {}
    if p is None or not ask.get("push"):
        return
    new = S.pushed_start(p["doc"], p.get("sched"), int(ask["push"]))
    if new is None:
        return
    cl = client()

    def done(got):
        if got is False:
            tooltip("Couldn't reach Due Crew. Check your connection.")
            return
        c = _pcfg()
        state = _state_cfg(c)
        if pid in state:
            state[pid]["missed"] = {"mode": "leave", "day": _today()}
            c["plans"] = state
            _psave(c)
        refresh_progress()
        app.swap(cfg())
        tooltip(f"Your dates moved {ask['push']} day{'s' if ask['push'] != 1 else ''} later. The plan's stay put.")
    _bg(lambda: cl.set_schedule(pid, new), done)


def schedule_inputs(col, plan, st, today):
    """What the schedule dialog needs: cards per unit on my deck, the
    reviews already due by day, and my pace. Main thread."""
    from ..stats.queries import StatsQueries
    totals = {}
    if st and _deck_ok(col, st.get("deck_id")):
        idx = P.DeckIndex(col, st["deck_id"])
        totals = {uid: len(c) for uid, c in P.unit_matches(idx, plan["doc"], _swap(st)).items()}
    base = []
    try:
        now = int(col.sched.today)
        rows = dict(col.db.all(
            "SELECT due - ?, COUNT(*) FROM cards WHERE queue IN (2, 3) AND due >= ? AND due < ? GROUP BY due",
            now, now, now + 190))
        base = [int(rows.get(i, 0)) for i in range(190)]
        base[0] += int(col.db.scalar("SELECT COUNT(*) FROM cards WHERE queue IN (2, 3) AND due < ?", now) or 0)
    except Exception:
        base = []
    return totals, base, StatsQueries(col).pace()


def open_schedule(pid, then=None):
    """My schedule for a plan: start, days, time, and the load it makes."""
    p = next((p for p in followed() if p["id"] == pid), None)
    if p is None or not mw.col:
        return
    from ..ui.schedule_dialog import ScheduleDialog
    today = _today()
    totals, base, pace = schedule_inputs(mw.col, p, _state_cfg().get(pid), today)
    dlg = ScheduleDialog(mw, p, today, totals, base, pace)
    if not dlg.exec():
        if then:
            then()
        return
    want = dlg.value()
    cl = client()

    def done(got):
        if got is False:
            tooltip("Couldn't reach Due Crew. Check your connection.")
        elif then is None:
            fresh = next((x for x in followed() if x["id"] == pid), None)
            if fresh and not fresh.get("paused"):
                _open_now([fresh], toast=False)  # today's share, on the new schedule
            refresh_progress()
            app.swap(cfg())
            tooltip("Schedule saved." if want else "Schedule off: sets open whole, as the plan has them.")
        if then:
            then()
    _bg(lambda: cl.set_schedule(pid, want), done)


def open_everything(pid):
    p = next((p for p in followed() if p["id"] == pid), None)
    if p is None or not _ensure_deck(p):
        return
    res = _open_now([p], everything=True)
    if res is not None and not res["n"]:
        tooltip("Everything in this plan is already open.")
    app.swap(cfg())


def _ensure_deck(p):
    state = _state_cfg()
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
    from .. import sheets
    choices = P.deck_choices(mw.col)
    if not choices:
        return
    st = _state_cfg(_pcfg()).get(pid)
    best, _swap_guess = P.best_deck(mw.col, p["doc"], choices)
    current = st.get("deck_id") if st else best
    at = next((i for i, (d, _n) in enumerate(choices) if d == current), 0)
    # plain text: the plan's name is the author's
    sheets.ask_item("Change deck", f"Run {p.get('name') or 'the plan'} on", [n for _d, n in choices],
                    lambda i: _run_on(pid, choices[i][0]), at=at)


def _run_on(pid, did):
    """change_deck's pick."""
    p = next((p for p in followed() if p["id"] == pid), None)
    if p is None or not mw.col:
        return
    c = _pcfg()
    state = _state_cfg(c)
    st = state.get(pid)
    idx = P.DeckIndex(mw.col, did)
    swap = P.detect_swap(idx, p["doc"])
    if swap:
        from ..ui.follow_dialog import ask_swap
        if not ask_swap(mw, swap, P.found_total(idx, p["doc"], swap)):
            swap = None
    if st and st.get("lesson_decks") and int(st.get("deck_id") or 0) != int(did):
        try:
            _lesson_drop(mw.col, st)  # Today's lesson, B: the old deck's cards go home; the new deck's get decks
        except Exception:
            oops()
    if st:
        st.update(deck_id=did, swap=list(swap) if swap else None)
    else:
        state[pid] = new_state(mw.col, p, did, swap)
    c["plans"] = state
    _psave(c)
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
    if P.own_pace(p):
        # 3.8.1: at my own pace no date waited for its day: nothing to ask (its "start
        # from the next date" skipped every passed date out of Up next); what an author
        # added to dates I opened opens, as a morning would
        _open_now([p])
        return
    today = _today()
    n_units, n_cards = waiting(mw.col, p, _state_cfg().get(pid), today)
    if not n_units:
        return
    from ..ui.follow_dialog import ask_catch_up
    nxt = P.next_unit(p["doc"], today)
    choice = ask_catch_up(mw, n_units, n_cards, nxt)
    if choice is None:
        return
    _open_now([p], mode=choice)


def stop_following(pid):
    p = next((p for p in followed() if p["id"] == pid), None)
    if p is None:
        return
    from .. import sheets
    text = ("Cards already open stay open"
            + (", and the ones it held back open too" if (_state_cfg().get(pid) or {}).get("held") else "")
            + ". The crew stops seeing your progress on this plan.")
    title = f"Stop following {p.get('name') or 'this plan'}?"
    if (_state_cfg().get(pid) or {}).get("tags"):
        # 3.8.0: its tags stay only if I say so (they stop updating)
        sheets.confirm_check(title, text, "Stop", f"Take {p.get('name') or 'its'}'s tags off your notes too",
                             lambda untag: _stop(pid, untag))
    else:
        sheets.confirm(title, text, "Stop", lambda: _stop(pid, False))


def _stop(pid, untag):
    p = next((p for p in followed() if p["id"] == pid), None)
    if p is None:
        return
    cl = client()

    def done(ok):
        if not ok:
            tooltip("Couldn't reach Due Crew. Check your connection.")
            return
        pc = _pcfg()
        state = _state_cfg(pc)
        held = (state.get(pid) or {}).get("held") or []
        if held and mw.col:
            P.open_cards(mw.col, held, f"Due Crew: stop {p.get('name') or 'plan'}")
            _after_change()
        if mw.col and (state.get(pid) or {}).get("lesson_decks"):
            try:
                if _lesson_drop(mw.col, state.get(pid)):  # Today's lesson, B: its decks go with it
                    _after_change()
            except Exception:
                oops()
        if untag:
            _drop_plan_tags(state.get(pid), p.get("name"))
        state.pop(pid, None)
        pc["plans"] = state
        _psave(pc)
        _state.get("plan_progress", {}).pop(pid, None)
        app.swap(cfg())

    _bg(lambda: cl.unfollow_plan(pid), done)
