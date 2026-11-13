"""Plans, the glue: following a plan, and stopping."""

import html
import os

from aqt import mw
from aqt.utils import tooltip

from .. import app
from .. import plans as P
from ..app import _bg
from ..app import cfg
from ..app import client
from ..errs import oops

from .morning import _after_change, _open_now, _state_cfg, apply_tags
from .lessons import _lesson_drop, _take_next, lesson_deck_on, show_plans
from .cards import _opened_cids, new_state, skip_past
from .state import _pcfg, _psave, _today, followed
from .pace import start_catch


# ---- following ----

def _signed_in():
    """3.3: a plan needs an account; not signed in, the sign-in opens here
    and the plan carries on after it."""
    if client().signed_in:
        return True
    from .. import open_auth
    open_auth()
    return client().signed_in


def open_follow(code=""):
    if not _signed_in():
        return
    if not mw.col:
        return
    from ..ui.follow_dialog import FollowDialog
    dlg = FollowDialog(mw, client(), mw.col, code=code, today=_today(), on_followed=on_followed,
                       lesson_on=lesson_deck_on)
    dlg.exec()


def on_followed(plan, deck_id, swap, late, hold=False, lesson=None):
    """Main thread, after POST /plans/follow: this computer runs it on
    `deck_id`; late is "open" (open what has opened) or "skip". 3.7.6:
    "skip:a,b" starts where everyone is (the passed dates skipped on my
    follow, so they're behind nowhere), "catch:W:N" opens them and catches
    up N cards over W weeks (G5's today-only limit), "begin:D" runs my
    dates D days later so the first is today. Following
    again keeps what this computer already applied: only the deck changes.
    hold (3.3, asked for at Follow): later dates' active, never-studied
    cards are suspended now, one undo step, and remembered so stopping
    opens them again. lesson: Today's lesson, True its own deck (B), False
    in the plan's deck (A), None as it was (or as chosen before, `lesson_next`)."""
    cl = client()
    cl.remember_plan(plan)
    c = _pcfg()
    state = _state_cfg(c)
    st = state.get(plan["id"])
    if st and st.get("lesson_decks") and int(st.get("deck_id") or 0) != int(deck_id) and mw.col:
        try:
            _lesson_drop(mw.col, st)  # Today's lesson, B: on another deck now, the old one's cards go home
        except Exception:
            oops()
    if st:
        st.update(deck_id=int(deck_id), swap=list(swap) if swap else None)
    else:
        state[plan["id"]] = new_state(mw.col, plan, deck_id, swap)
    st = state[plan["id"]]
    _take_next(c, plan["id"], st)
    if lesson is not None and st is not None:
        was = bool(st.get("lesson_deck"))
        if lesson:
            st["lesson_deck"] = True
        else:
            st.pop("lesson_deck", None)
            if was and mw.col:
                try:
                    if _lesson_drop(mw.col, st):  # back to A: its decks go
                        _after_change()
                except Exception:
                    oops()
    kind, _, rest = str(late).partition(":")
    if hold and mw.col:
        state[plan["id"]]["hold_yes"] = True  # 3.8.1: my yes, kept (hold_new holds what authors add later)
        idx = P.DeckIndex(mw.col, deck_id)
        # 3.7.6: from the beginning, "later dates" are my shifted ones
        hdoc = P.my_doc(plan["doc"], int(rest)) if kind == "begin" and rest.isdigit() else plan["doc"]
        cids = P.holdable(idx, hdoc, _today(), swap, state[plan["id"]].get("applied"), own=P.own_pace(plan),
                          kept=_opened_cids(idx, state[plan["id"]], hdoc))
        n = P.hold_cards(mw.col, cids, f"Due Crew: hold back {plan.get('name') or 'plan'}")
        if n:
            state[plan["id"]]["held"] = sorted(set(state[plan["id"]].get("held") or []) | set(int(c) for c in cids))
            _after_change()
    c["plans"] = state
    _psave(c)

    pid = plan["id"]
    saved = kind not in ("skip", "begin") or not rest  # what needs a request has it yet?

    def finish(got=None):
        show_plans(cfg(), swap=False)  # 3.3: where it lives now (3.8.0: You › Plans)
        fresh = next((x for x in followed() if x["id"] == pid), plan)
        ok = saved or got is not None
        if not ok:
            # a choice that didn't reach the server never opens what has passed:
            # the passed dates are skipped here only, and today's opens as usual
            c3 = _pcfg()
            st3 = _state_cfg(c3).get(pid)
            if st3 is not None:
                skip_past(st3, plan, _today())
                c3["plans"] = _state_cfg(c3)
                _psave(c3)
        apply_tags([fresh])  # 3.8.0: its tags, before its dates open
        # "skip:" saved the passed dates as skipped on my follow, so today's opens as usual
        res = _open_now([fresh], mode="skip" if kind == "skip" and not rest else "open")
        if not ok:
            tooltip("Following. Couldn't save how you start, so the earlier sets wait here; "
                    "Plan \u25be \u203a Push my dates back… or Open now on each.", period=7000)
            app.swap(cfg())
            return
        if kind == "catch":
            weeks, _, cards = rest.partition(":")
            days = 7 * max(1, min(3, int(weeks or 2)))
            if int(cards or 0):
                start_catch(pid, days, -(-int(cards) // days))
        elif res is not None and not res["n"]:
            tooltip(f"Following {html.escape(plan.get('name') or 'the plan')}.")
        app.swap(cfg())

    cl = client()
    if kind == "skip" and rest:
        _bg(lambda: cl.set_days(pid, skipped=[u for u in rest.split(",") if u]), finish)
    elif kind == "begin" and rest.isdigit() and int(rest):
        _bg(lambda: cl.set_days(pid, shift=min(365, int(rest))), finish)
    else:
        finish()  # 3.3: the plan's days are the schedule; nothing to ask


def open_site(path):
    """3.5.0: a page of duecrew.com in the browser, signed in when the link
    can be made (a one-time token in the fragment, never logged)."""
    cl, site = client(), site_base()

    def done(token):
        from aqt.utils import openLink
        openLink(f"{site}{path}" + (f"#{token}" if token else ""))
    _bg(lambda: cl.site_link() if cl.signed_in else None, done)


def site_base():
    return (str(cfg().get("site_base") or "") or os.environ.get("DUE_CREW_SITE")
            or "https://duecrew.com").rstrip("/")
