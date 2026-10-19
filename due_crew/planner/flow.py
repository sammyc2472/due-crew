"""The plan windows' glue (docs/planner.md). Main-thread rules as in __init__: every
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
from ..backend.shapes import TransportError
from . import actions, enabled, qids, remote

_open = {}       # "plans", "start", "qids" -> the window, while it's open


def close_all():
    """profile_will_close: the plan windows go with the profile (their cards
    and decks are its collection's)."""
    for key, w in list(_open.items()):
        _open.pop(key, None)
        if w is not None and getattr(w, "_alive", False):
            try:
                w.close()
            except RuntimeError:
                pass  # Qt has it gone already


def _raise(key):
    w = _open.get(key)
    if w is not None and getattr(w, "_alive", False):
        w.raise_()
        w.activateWindow()
        return True
    return False


# ---- the plan window ----

def open_plans(select=None, tab=None):
    """Your plans (3.9.3, for everyone; labs before): signed in, a
    collection open. One request on the click: my plans. select: a plan's
    id to start on; tab: the tab to start on ("dates", "layout"...)."""
    if not mw.col:
        return
    w = _open.get("plans")
    if w is not None and getattr(w, "_alive", False):
        if not select or w.go_to_plan(select, tab):
            w.raise_()
            w.activateWindow()
            return
        w.close()  # a plan it doesn't list (one just made): my plans asked again
    if not plan_flow._signed_in():
        return
    cl, gen = client(), app.generation

    def done(plans):
        if gen != app.generation or not mw.col:
            return
        if plans is None:
            tooltip("Due Crew couldn't be reached. Try again in a minute.")
            return
        show_plans(plans, select, tab)
    _bg(lambda: remote.my_plans(cl), done)


def make_here(cl):
    """3.9.3, Make a plan from a deck made in Anki: (make, made) for its
    dialog. make, in the background: the plan (POST /plans); made, on the
    main thread: Your plans opens on it, at Lay it out."""
    gen = app.generation

    def made(raw):
        if gen == app.generation and mw.col and raw.get("id"):
            open_plans(select=raw["id"], tab="layout")
    return (lambda name, deck: remote.create(cl, name, deck)), made


def show_plans(plans, select=None, tab=None):
    from .window import PlanWindow
    w = PlanWindow(mw, mw.col, plans, Ops(), select=select, tab=tab)
    _gone_on_close(w)
    _open["plans"] = w
    w.show()
    return w


def _gone_on_close(w):
    """A plan window lets go of its deck read when it closes."""
    from aqt.qt import Qt
    w.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)


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

    def followed_here(self, pid, version=None):
        """True when I follow it, it runs on a deck here (open and study go
        through the plan's own state), and (with `version`) the board's copy
        of it is that version: one the window saved since the last refresh
        isn't the board's yet, so the window opens its own cards."""
        if plan_flow._plan_idx(pid) is None:
            return False
        if version is None:
            return True
        p = next((p for p in client().session.get("plans") or [] if isinstance(p, dict) and p.get("id") == pid), None)
        return p is not None and int(p.get("version") or 0) == int(version)

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

    def undo(self, owner, pid, version, done):
        """done((outcome, what) or None): remote.undo's (the builder's Undo)."""
        cl, gen = client(), app.generation
        _bg(lambda: remote.undo(cl, pid, version),
            lambda got: getattr(owner, "_alive", False) and gen == app.generation and done(got))

    def my_squads(self):
        """The squads I'm in, [{id, name}] (the board's), for a plan offered to one."""
        from .. import squads
        return [{"id": q["id"], "name": q.get("name") or "?"} for q in squads._my_squads(cfg())]

    def reopen(self, pid):
        """Your plans again, on `pid` (a copy just made), or on none (one taken down or left)."""
        w = _open.pop("plans", None)
        if w is not None and getattr(w, "_alive", False):
            w.close()
        open_plans(select=pid)

    def pip(self):
        """Pip in the window's corner, as Settings › Pip says."""
        from ..rooms import sev_on
        return sev_on()

    def follow_plan(self):
        """Follow a plan (its code), then Your plans again, with it in."""
        plan_flow.open_follow()
        self.reopen(None)

    def me(self):
        """My account's id (a row of mine says You)."""
        return client().user_id

    def ask(self, owner, fn, done):
        """One of the plan's other requests (its history, posts, settings):
        fn(client) in the background, done(answer or None) on the main thread
        while `owner` is open and nothing changed under it."""
        cl, gen = client(), app.generation
        _bg(lambda: fn(cl), lambda got: getattr(owner, "_alive", False) and gen == app.generation and done(got))

    def browse(self, cids):
        plan_flow._browse(cids)

    def open_cards(self, cids, name):
        """How many opened (Browse's open: one undo step, never a leech)."""
        return plan_flow.open_cards_now(cids, name, first=True)

    def open_date(self, pid, uid):
        plan_flow.open_date(pid, uid)

    def study_date(self, pid, uid):
        plan_flow.study_date(pid, uid)

    def study_quiz(self, pid, eid):
        plan_flow.study_quiz(pid, eid)

    def study_cards(self, idx, cids, name):
        return study_cards(idx, cids, name)

    def new_from_calendar(self):
        open_start()

    def new_from_deck(self):
        plan_flow.open_make()

    def open_page(self, path):
        """A page of duecrew.com (the Text tab's format), in the browser."""
        from aqt.utils import openLink
        openLink(f"{plan_flow.site_base()}{path}")


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


# ---- a plan from a block's calendar (claude.py's jobs, a stand-in for now) ----

def open_start():
    """New plan from a calendar (3.9.3, for everyone): signed in (it makes
    a plan on the server), a collection open. Claude's stand-in and What
    Claude would get stay behind the labs switch."""
    if not mw.col or _raise("start"):
        return
    if not plan_flow._signed_in():
        return
    show_start()


def top_decks(col):
    """[(deck id, name, cards)]: the top-level normal decks, biggest first
    (a new plan starts on the biggest)."""
    out = []
    for did, name in P.deck_choices(col):
        if "::" in name:
            continue
        ids = ",".join(str(int(d)) for d in col.decks.deck_and_child_ids(did)) or "0"
        n = int(col.db.scalar(f"SELECT count() FROM cards WHERE did IN ({ids}) OR odid IN ({ids})") or 0)
        out.append((did, name, n))
    return sorted(out, key=lambda x: (-x[2], x[1].lower()))


def show_start():
    from .start_window import StartWindow
    w = StartWindow(mw, top_decks(mw.col), StartOps(), labs=enabled())
    _gone_on_close(w)
    _open["start"] = w
    w.show()
    return w


class StartOps:
    """What the calendar window asks of the add-on."""

    def today(self):
        import datetime
        return datetime.date.fromisoformat(plan_flow._today())

    def index(self, did):
        return P.DeckIndex(mw.col, did)

    def make(self, owner, name, doc, done, pid=None):
        """The plan made (POST /plans) and its dates saved (the builder's
        PUT), one click. done(("saved", raw) | ("made", pid, why): made,
        its dates not saved | ("refused", words) | None). pid: one made
        already, whose dates are tried again (never a second plan)."""
        cl, gen = client(), app.generation

        def job():
            got = pid
            if got is None:
                outcome, raw = remote.create(cl, name, doc.get("deck") or "")
                if outcome != "saved":
                    return outcome, raw
                got, version = raw["id"], raw.get("version") or 1
            else:
                version = remote.load(cl, got)[0].get("version") or 1
            try:
                outcome, raw = remote.save(cl, got, version, doc, f"made in Anki from a calendar: {name}")
            except TransportError:
                return "made", got, "Check your connection."
            if outcome == "saved":
                return "saved", dict(raw, id=raw.get("id") or got)
            return "made", got, (str(raw) if outcome == "refused" else "It changed since.")
        _bg(job, lambda got: getattr(owner, "_alive", False) and gen == app.generation and done(got))

    def open_plan(self, pid):
        """The plan window, on the plan just made."""
        w = _open.get("plans")
        if w is not None and getattr(w, "_alive", False):
            w.close()
        open_plans(select=pid)


# ---- question IDs ----

def open_qids(did=None):
    """Missed questions (3.9.3, for everyone; Question IDs in labs): this
    collection only, nothing sent. did: the deck to start on (Insights')."""
    if not mw.col:
        return
    did = _top_deck(mw.col, did) if did else None
    w = _open.get("qids")
    if w is not None and getattr(w, "_alive", False):
        if did:
            w.pick_deck(did)
        w.raise_()
        w.activateWindow()
        return
    from .qid_window import QidWindow
    every = P.deck_choices(mw.col)
    tops = [(d, n) for d, n in every if "::" not in str(n)]  # question tags are deck-wide: a top deck is enough
    w = QidWindow(mw, mw.col, tops or every, QidOps(), did=did)
    _gone_on_close(w)
    _open["qids"] = w
    w.show()
    return w


def _top_deck(col, did):
    """A deck's top-level deck (question tags are deck-wide), or None."""
    try:
        top = str(col.decks.name(int(did)) or "").split("::")[0]
        return col.decks.id_for_name(top) if top else None
    except Exception:
        return None


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

    def movable(self, cids):
        """How many of these Bring back would move: the seen ones due after
        its days (actions.reviews), with the shut ones it opens."""
        if not mw.col or not cids:
            return 0
        return len(actions.reviews(mw.col, cids, P.openable_ids(mw.col, cids)))

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
