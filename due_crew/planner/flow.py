"""Labs, the glue (docs/planner.md). Main-thread rules as in __init__: every
collection read and step here, on the main thread; each request in the
background, on a click, its answer dropped when the profile or the account
changed since (app.generation). What opens, studies and shows in Browse is
plan_flow's own (Browse's open, a date's Study), so the morning, Not today
and at-my-own-pace keep counting what the window does.
"""

import json
import os

from aqt import mw
from aqt.utils import tooltip

from .. import app, plan_flow
from .. import plans as P
from ..app import _bg, cfg, client
from . import actions, enabled, qids, remote

_admin = {}      # uid -> the server's answer, asked once an Anki session
_open = {}       # "plans", "qids" -> the window, while it's open


def _raise(key):
    w = _open.get(key)
    if w is not None and getattr(w, "_alive", False):
        w.raise_()
        w.activateWindow()
        return True
    return False


# ---- the plan window ----

def open_plans():
    """Tools › Due Crew › Plan window (labs): the admin's account only (the
    server says), signed in, a collection open. Two requests on the click:
    who I am (once a session) and my plans."""
    if not enabled() or not mw.col or _raise("plans"):
        return
    if not plan_flow._signed_in():
        return
    cl, gen = client(), app.generation
    uid = cl.user_id

    def job():
        ok = _admin.get(uid)
        if ok is None:
            ok = remote.is_admin(cl)
        return ok, (remote.my_plans(cl) if ok else [])

    def done(got):
        if gen != app.generation or not mw.col:
            return
        if got is None:
            tooltip("Due Crew couldn't be reached. Try again in a minute.")
            return
        ok, plans = got
        _admin[uid] = ok
        if not ok:
            tooltip("The plan window is for the admin’s account while it’s in labs.")
            return
        show_plans(plans)
    _bg(job, done)


def show_plans(plans):
    from .window import PlanWindow
    w = PlanWindow(mw, mw.col, plans, Ops())
    _open["plans"] = w
    w.show()
    return w


class Ops:
    """What the plan window asks of the add-on: a plan's deck here, its
    requests, and plan_flow's steps. One object, so a render or a test can
    hand the window its own."""

    def today(self):
        return plan_flow._today()

    def context(self, plan, doc):
        """(DeckIndex or None, swap, how) for a plan here: the deck it runs on
        on this computer when I follow it here, else the deck named like its
        own (P.best_deck). how: "followed" or "named" or "" (none here)."""
        col = mw.col
        st = plan_flow._state_cfg().get(plan.get("id")) or {}
        if st and plan_flow._deck_ok(col, st.get("deck_id")):
            return P.DeckIndex(col, st["deck_id"]), plan_flow._swap(st), "followed"
        did, swap = P.best_deck(col, doc)
        if did is None:
            return None, None, ""
        return P.DeckIndex(col, did), (tuple(swap) if swap else None), "named"

    def my_doc(self, plan):
        """A plan I follow as I run it: my dates (plan_flow.mine)."""
        return plan_flow.mine(plan)["doc"]

    def followed_here(self, pid):
        """True when I follow it and it runs on a deck here (open and study go
        through the plan's own state)."""
        return plan_flow._plan_idx(pid) is not None

    def generation(self):
        return app.generation

    def load(self, owner, pid, done):
        """done((raw, plan) or None) on the main thread, while `owner` is open
        and nothing changed under it."""
        cl, gen = client(), app.generation
        _bg(lambda: remote.load(cl, pid),
            lambda got: getattr(owner, "_alive", False) and gen == app.generation and done(got))

    def save(self, owner, pid, version, doc, summary, done):
        """done((outcome, what) or None): remote.save's answer."""
        cl, gen = client(), app.generation
        _bg(lambda: remote.save(cl, pid, version, doc, summary),
            lambda got: getattr(owner, "_alive", False) and gen == app.generation and done(got))

    def browse(self, cids):
        plan_flow._browse(cids)

    def open_cards(self, cids, name):
        return plan_flow.open_cards_now(cids, name, first=True)

    def open_date(self, pid, uid):
        plan_flow.open_date(pid, uid)

    def study_date(self, pid, uid):
        plan_flow.study_date(pid, uid)

    def study_quiz(self, pid, eid):
        plan_flow.study_quiz(pid, eid)

    def study_cards(self, idx, cids, name):
        return study_cards(idx, cids, name)


def study_cards(idx, cids, name):
    """A Due Crew deck of these cards' open ones, random (a date's Study), and
    Anki's Study screen on it. False when none of them is open."""
    cids = P.study_cards(idx, cids)
    if not cids:
        tooltip("None of them are open yet.")
        return False
    deck = P.our_deck(name)
    if not plan_flow._filtered(mw.col, deck, cids, order=plan_flow.STUDY_ORDER):
        return False
    plan_flow._after_change()
    did = mw.col.decks.id_for_name(deck)
    if did:
        mw.col.decks.select(did)
        mw.moveToState("overview")
    return True


# ---- question IDs ----

def open_qids():
    """Tools › Due Crew › Question IDs (labs): this collection only, nothing
    sent, so labs alone opens it."""
    if not enabled() or not mw.col or _raise("qids"):
        return
    from .qid_window import QidWindow
    w = QidWindow(mw, mw.col, P.deck_choices(mw.col), QidOps())
    _open["qids"] = w
    w.show()
    return w


MISSES = "qids.json"  # this profile's kept misses: question numbers by day, deck and bank; never sent


def _misses_path():
    return os.path.join(app._profile_files(), MISSES)


def misses_log():
    """[{day, deck, bank, n}], oldest first; [] when there's none or it won't read."""
    try:
        with open(_misses_path(), encoding="utf-8") as f:
            data = json.load(f)
        log = data.get("misses") if isinstance(data, dict) else None
        return [e for e in log if isinstance(e, dict)] if isinstance(log, list) else []
    except (OSError, ValueError):
        return []


def _save_misses(log):
    try:
        os.makedirs(app._profile_files(), exist_ok=True)
        tmp = _misses_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"v": 1, "misses": log}, f)
        os.replace(tmp, _misses_path())
        return True
    except OSError:
        return False


class QidOps:
    def index(self, did):
        return P.DeckIndex(mw.col, did)

    def kept(self, did, bank=None):
        """(numbers, pastes, since) this computer kept for a deck (qids.kept)."""
        return qids.kept(misses_log(), did, bank)

    def keep(self, did, bank, numbers):
        """A paste's questions into the kept misses (main thread), once each a day."""
        return _save_misses(qids.keep(misses_log(), plan_flow._today(), did, bank, numbers))

    def forget(self, did):
        """This deck's kept misses gone; the ones taken out, for Undo."""
        log, gone = qids.forget(misses_log(), did)
        _save_misses(log)
        return gone

    def unforget(self, gone):
        """Undo: the pastes forget took out, back."""
        _save_misses(sorted(misses_log() + list(gone or []), key=lambda e: str(e.get("day") or "")))

    def default_deck(self, choices):
        """The deck most of my plans run on here, else Anki's current deck's top."""
        state = plan_flow._state_cfg()
        ids = [st.get("deck_id") for st in state.values() if isinstance(st, dict)]
        have = {d for d, _n in choices}
        for did in sorted(set(ids), key=ids.count, reverse=True):
            if did in have:
                return did
        try:
            cur = mw.col.decks.current()["name"].split("::")[0]
        except Exception:
            cur = ""
        return next((d for d, n in choices if n == cur), choices[0][0] if choices else None)

    def plan_dates(self, did, idx, cids):
        """[(plan name, [date label])]: the dates of the plans I follow on this
        deck that hold any of these cards (my dates)."""
        out = []
        state = plan_flow._state_cfg()
        for p in plan_flow.followed():
            st = state.get(p["id"]) or {}
            if st.get("deck_id") != did:
                continue
            dates = P.dates_with(idx, p["doc"], cids, plan_flow._swap(st))
            if dates:
                out.append((str(p.get("name") or "Plan"), [P.fmt_day(u.get("opens")) for u in dates]))
        return out

    def bring_back(self, cids, back):
        """The window's Do it: actions.bring_back, then what plan_flow does
        after an open (Edit's undo, at my own pace a date now all open)."""
        if not mw.col:
            return None
        shut = P.openable_ids(mw.col, cids)
        n = len({int(c) for c in cids})
        got = actions.bring_back(mw.col, cids, f"Due Crew: bring back {n:,} card{'s' if n != 1 else ''}", back=back)
        if got["opened"] or got["due"]:
            plan_flow._after_change()
            plan_flow._claim_opened(shut if got["opened"] else ())
            plan_flow.refresh_progress()
            app.swap(cfg())
        return got

    def browse(self, cids):
        plan_flow._browse(cids, empty="None of them are in this deck.")

    def study_cards(self, idx, cids, name):
        return study_cards(idx, cids, name)
