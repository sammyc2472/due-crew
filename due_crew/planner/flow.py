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
from ..app import _bg, _state, cfg, client, save_cfg
from ..backend.shapes import TransportError
from . import actions, enabled, remote

_open = {}       # "plans", "start", "qids" -> the window, while it's open
_asking = []     # my plans on their way for Your plans (one ask at a time)


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
    if not plan_flow._signed_in() or _asking:
        return  # (a second click while my plans are on their way: the one window)
    cl, gen = client(), app.generation
    _asking.append(True)

    def done(plans):
        _asking.clear()
        if gen != app.generation or not mw.col:
            return
        if plans is None:
            tooltip("Due Crew couldn't be reached. Try again in a minute.")
            return
        w = _open.get("plans")
        if w is not None and getattr(w, "_alive", False):
            w.close()  # one opened meanwhile (a plan made): this one, with every plan, in its place
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

    def map_by(self, did):
        """How Insights splits a deck: the topic map's pick for it on this
        computer (cfg ins_map_by), or None for the best."""
        return str((cfg().get("ins_map_by") or {}).get(str(did)) or "") or None

    def set_map_by(self, did, key):
        """Another way, the map's too: the board's map starts again from the top."""
        c = cfg()
        c["ins_map_by"] = dict(c.get("ins_map_by") or {}, **{str(did): str(key)})
        save_cfg(c)
        for k in ("map_at", "insights"):
            (_state.get(k) or {}).pop(did, None)

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

    def send(self, owner, pid, version, doc, summary, post, done):
        """Round five's Send: the waiting changes as one save, with its line
        to followers. done((outcome, what) or None): remote.save's answer."""
        cl, gen = client(), app.generation
        _bg(lambda: remote.save(cl, pid, version, doc, summary, post),
            lambda got: getattr(owner, "_alive", False) and gen == app.generation and done(got))

    def draft(self, pid):
        """The changes waiting on this plan here (draft.Draft), or None."""
        from .draft import Draft
        return Draft.from_json(pid, (_drafts().get("drafts") or {}).get(str(pid)))

    def keep_draft(self, pid, draft):
        """The waiting changes kept on this computer (None, or none waiting: gone)."""
        data = _drafts()
        ds = data.setdefault("drafts", {})
        if draft is None or not len(draft):
            ds.pop(str(pid), None)
        else:
            ds[str(pid)] = draft.to_json()
        _save_drafts(data)

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
        open_new()

    def new_from_deck(self):
        open_new()

    def new_plan(self):
        """Round five: the one New plan window."""
        open_new()

    def now_words(self):
        """"Tue 2:14 pm", for Undo ▾'s line about a send."""
        import datetime
        t = datetime.datetime.now()
        return f"{t:%a} {t.hour % 12 or 12}:{t:%M} {'am' if t.hour < 12 else 'pm'}"

    def site_url(self, path):
        return f"{plan_flow.site_base()}{path}"

    # ---- round five's Mine: my follow, plan_flow's own steps ----

    def follow_state(self, pid):
        return next((p for p in plan_flow.followed() if p.get("id") == pid), None)

    def held_count(self, pid):
        try:
            return int(plan_flow.held_count(pid) or 0)
        except Exception:
            return 0

    def in_team(self, pid):
        from .. import team_flow
        return pid in (team_flow.teams() or {})

    def set_shift(self, pid):
        plan_flow.set_shift(pid)

    def set_skip(self, pid, uid, on):
        plan_flow.set_skip(pid, uid, on)

    def set_own(self, pid, own):
        plan_flow.set_own(pid, own)

    def set_early(self, pid, n):
        plan_flow.set_early(pid, n)

    def pause_until(self, pid):
        plan_flow.pause_until(pid)

    def resume(self, pid):
        p = self.follow_state(pid) or {}
        if p.get("since"):
            plan_flow.back(pid)
        else:
            plan_flow.set_paused(pid, False)

    def show_held(self, pid):
        plan_flow.show_held(pid)

    def change_deck(self, pid):
        plan_flow.change_deck(pid)

    def open_everything(self, pid):
        plan_flow.open_everything(pid)

    def stop_following(self, pid):
        plan_flow.stop_following(pid)

    def open_schedule(self, pid):
        plan_flow.open_schedule(pid)

    def can_reset(self, pid):
        """Reset to default has something to put back (my shift, skips, moves, pause)."""
        try:
            return bool(plan_flow.reset_lines(plan_flow._raw(pid) or {}))
        except Exception:
            return False

    def reset_days(self, pid):
        plan_flow.reset_days(pid)

    def copy_plan(self, owner, pid, said):
        """Make my own copy (a library plan): the same dates, mine to change; then Your plans on it."""
        p = self.follow_state(pid) or {}
        start = min((str(u.get("opens")) for u in P.units(p.get("doc") or {})), default=self.today())
        cl, gen = client(), app.generation

        def done(got):
            if not getattr(owner, "_alive", False) or gen != app.generation:
                return
            if not got or got[0] != "saved":
                said("That didn't copy: " + (str(got[1]) if got else "check your connection, then try again."))
                return
            self.reopen(got[1].get("id"))
        _bg(lambda: remote.copy(cl, pid, start), done)

    def open_page(self, path):
        """A page of duecrew.com (the Text tab's format), in the browser."""
        from aqt.utils import openLink
        openLink(f"{plan_flow.site_base()}{path}")


# ---- round five: changes waiting to be sent, kept per profile ----

_drafts_store = {"profile": None, "data": None}


def _drafts_path():
    return os.path.join(plan_flow._files(), "plan_drafts.json")


def _drafts():
    """This profile's waiting changes (plan_drafts.json): {drafts: {plan
    id: draft}}. Never sent; read once a profile. Main thread."""
    key = app._profile_key()
    if _drafts_store["profile"] == key and _drafts_store["data"] is not None:
        return _drafts_store["data"]
    try:
        with open(_drafts_path()) as f:
            data = json.load(f)
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        data = {}
    _drafts_store.update(profile=key, data=data)
    return data


def _save_drafts(data):
    path = _drafts_path()
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except OSError:
        pass  # a full disk: the changes stay in the window till it closes


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


# ---- round five: New plan, the one way to start ----

def open_new():
    """New plan: signed in (it makes a plan on the server), a collection open."""
    if not mw.col or _raise("new"):
        return
    if not plan_flow._signed_in():
        return
    from .new_plan import NewPlanWindow
    w = NewPlanWindow(mw, top_decks(mw.col), NewOps(), labs=enabled())
    _gone_on_close(w)
    _open["new"] = w
    w.show()
    return w


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


class NewOps(StartOps):
    """What New plan asks of the add-on: StartOps', a friend's code, the labs window."""

    def follow(self, code):
        plan_flow.open_follow(code)

    def labs_window(self):
        open_start()


# ---- question IDs ----

def open_qids(did=None):
    """QBank QIDs (3.9.3, for everyone; Question IDs in labs): this
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


class QidOps:
    def index(self, did):
        return P.DeckIndex(mw.col, did)

    def default_deck(self, choices):
        """The deck my plan runs on here (its top deck: question tags are
        deck-wide, and the window lists top decks): the plan You › Plans
        shows first, else the one most of my plans run on, else Anki's
        current deck's top."""
        state = plan_flow._state_cfg()
        top = lambda st: _top_deck(mw.col, st["deck_id"]) if isinstance(st, dict) and st.get("deck_id") else None  # noqa: E731
        shown = top(state.get(cfg().get("plan_pick")))
        ids = [d for d in map(top, state.values()) if d]
        have = {d for d, _n in choices}
        for did in ([shown] if shown else []) + sorted(set(ids), key=ids.count, reverse=True):
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

    def unsuspend(self, cids):
        """Unsuspend: actions.unsuspend, then what plan_flow does after an
        open (Edit's undo, at my own pace a date now all open)."""
        if not mw.col or not cids:
            return 0
        shut = P.openable_ids(mw.col, cids)
        n = actions.unsuspend(mw.col, cids, f"Due Crew: unsuspend {len(shut):,} card{'s' if len(shut) != 1 else ''}")
        if n:
            plan_flow._after_change()
            plan_flow._claim_opened(shut)
            plan_flow.refresh_progress()
            app.swap(cfg())
        return n

    def study(self, cids):
        """Study now: actions.study into Due Crew › QBank cards (each
        paste adds to it; a card goes back to its own deck once done), then
        Anki's Study screen on it. False when none of them can go in."""
        if not mw.col or not cids:
            return False
        name = P.our_deck(actions.DECK)
        shut = P.openable_ids(mw.col, cids)
        n = len({int(c) for c in cids})
        opened, had = actions.study(mw.col, cids, f"Due Crew: study {n:,} QBank card{'s' if n != 1 else ''}", name,
                                    lambda want: plan_flow._filtered(mw.col, name, want, order=plan_flow.STUDY_ORDER))
        if opened:
            plan_flow._claim_opened(shut)
            plan_flow.refresh_progress()
        if opened or had:
            plan_flow._after_change()
        if not had:
            tooltip("None of them can be studied now (buried, or in another filtered deck).")
            return False
        did = mw.col.decks.id_for_name(name)
        if did:
            mw.col.decks.select(did)
            mw.moveToState("overview")
        return True

    def browse(self, cids):
        plan_flow._browse(cids, empty="None of them are in this deck.")
