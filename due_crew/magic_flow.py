"""Magic search's glue (3.9.7; magic.py the rules, ui/magic_window.py the
window). Main-thread rules as in __init__: every collection read and step
here, on the main thread; each request in the background, on a click, its
answer dropped when the profile or the account changed since
(app.generation). Nothing typed is sent or kept but the last few finds,
on this computer (cfg "magic_recent").

What it does with the cards, Due Crew's own steps (Sam's picks):
- Study now: a Due Crew filtered deck of them (New and due, or All of
  them), suspended ones opened first (never a leech), one undo step; it
  stays till it's studied through (a card goes home once done) and an
  empty one is tidied the next morning, as QBank cards' is.
- Keep as a filtered deck: one named by me, holding the search itself, so
  Anki's Rebuild fills it again; never tidied.
- Add to a filtered deck: one I have (a QBank misses deck): these cards
  join its search and it's rebuilt, one undo step.
- Unsuspend: as QBank QIDs' (the new ones first in line).
- Put on days: each picked day a date of My plan (the first one starts
  it: only me, on this deck) or of a plan I write (with followers, it
  waits in Review and send). The cards split over the days, in the deck's
  order. Anki is never asked to move a due date.
- What's coming up: a quiz (a date on a plan), my exam and my away spell
  (Settings' own), my plan pushed back or paused (my follow)."""

import datetime
import json
import re

from aqt import mw
from aqt.utils import tooltip

from . import app, board, magic as M, plan_flow
from . import plans as P
from .app import _bg, cfg, client, save_cfg
from .backend.shapes import TransportError
from .errs import oops

RECENT = 5           # finds kept for the empty box, on this computer
DAYS = 14            # the day picker: two weeks from today
FILL_SPAN = 90       # the fill-in: how far out it reaches, in days
FILL_MAX = 60        # and how many study days (a set a day on the plan)
BEFORE_MAX = 5       # a quiz's topics: on at most this many days before it
MY_PLAN = "My plan"
ALSO_MAX = 8         # a topic's near names under it
KEEP_LIMIT = 9999    # a kept deck's limit: what Anki's own box goes to

_win = None


# ---- the way in ----

def on():
    """Settings › Board › Due › Magic search (an account key, on by default)."""
    return cfg().get("magic_search", True) is not False


def open_search(text="", cids=None):
    """The window, raised if it's open (with `text` typed into it), else
    made. cids: Browse's picked cards, to study or put on days."""
    global _win
    if not mw.col:
        return None
    if _win is not None and getattr(_win, "_alive", False):
        if text or cids:
            _win.face.prefill(text, cids)
        _win.raise_()
        _win.activateWindow()
        return _win
    from .ui.magic_window import MagicWindow
    face = Search(Ops())
    face.prefill(text, cids)
    _win = MagicWindow(mw, face)
    _win.show()
    _win.raise_()  # from Browse: in front of it
    _win.activateWindow()
    return _win


def close():
    """profile_will_close: the window goes with the collection."""
    global _win
    w, _win = _win, None
    if w is not None and getattr(w, "_alive", False):
        try:
            w.close()
        except RuntimeError:
            pass


# ---- the how-to on the Decks screen, once (round 2) ----

_TRIES = {}  # this session's resource try, from the collection's tags: read once, the first time the card's due


def board_howto():
    """The Decks screen's first-time card, its words (magic.howto), or None:
    Magic search off, or the card was seen (the account's magic_seen: once a
    person, wherever they are). Its resource try is the collection's own
    (a fifth of a second on a big shared deck, once)."""
    if not mw.col or not on() or cfg().get("magic_seen"):
        return None
    if "res" not in _TRIES:
        try:
            _TRIES["res"] = M.examples(mw.col.tags.all())
        except Exception:
            oops()
            _TRIES["res"] = {}
    return M.howto(board.MAGIC_KBD, _TRIES["res"])


def show_board_howto():
    """On the Decks screen just drawn: the card, when it's due (it waits on the page for the board to be clear)."""
    view = board_howto()
    if view is not None:
        app.board_eval(board.magic_howto_js(view))


def howto_said(parts):
    """The card's buttons (duecrew:magichow:how:text): Got it, Open Magic search,
    or a try, the window opened with it. Each is the card seen."""
    how = parts[2] if len(parts) > 2 else ""
    try:
        from urllib.parse import unquote
        text = unquote(":".join(parts[3:]))[:500] if len(parts) > 3 else ""
    except Exception:
        text = ""
    Ops().saw_intro()
    if how == "open":
        open_search()
    elif how == "try" and text.strip():
        open_search(text)


def from_browser(browser):
    """Browse's right-click › Due Crew: put on a day…: the picked cards."""
    try:
        cids = browser.selected_cards() if hasattr(browser, "selected_cards") else browser.selectedCards()
    except Exception:
        oops()
        return
    cids = [int(c) for c in cids or []]
    if not cids:
        tooltip("Select some cards first.")
        return
    open_search(cids=cids)


# ---- what the window asks of Anki and the server ----

class Ops:
    """The collection and the requests, one object so a test hands the
    window its own."""

    def today(self):
        return datetime.date.fromisoformat(plan_flow._today())

    def decks(self):
        """[(did, name)]: the top-level normal decks with cards, biggest first (a deck's tags are deck-wide)."""
        from .planner.flow import top_decks
        return [(d, n) for d, n, k in top_decks(mw.col) if k]

    def all_decks(self):
        return P.deck_choices(mw.col)

    def deck_name(self, did):
        try:
            return str(mw.col.decks.name(int(did)))
        except Exception:
            return ""

    def deck_cards(self, did, idx):
        """The cards of a deck and its subdecks, as idx has them by home deck."""
        out = set()
        try:
            for d in mw.col.decks.deck_and_child_ids(int(did)):
                out.update(idx.by_deck.get(int(d), ()))
        except Exception:
            pass
        return out

    def home_deck(self, cid):
        """A card's own deck (its home, when a filtered deck holds it)."""
        try:
            return mw.col.db.scalar("SELECT CASE WHEN odid THEN odid ELSE did END FROM cards WHERE id = ?", int(cid))
        except Exception:
            return None

    def filtered_decks(self):
        """[(did, name)]: the filtered decks here, mine and Due Crew's (two reads, as the morning's tidy does)."""
        normal = {int(r.id) for r in mw.col.decks.all_names_and_ids(include_filtered=False)}
        return sorted(((int(r.id), str(r.name)) for r in mw.col.decks.all_names_and_ids(include_filtered=True)
                       if int(r.id) not in normal), key=lambda x: x[1].lower())

    def default_deck(self, choices):
        """The deck my plans run on (its top deck: a deck's tags are deck-wide):
        the plan You › Plans shows first, else the one most of my plans run on
        (QBank QIDs' rule, 3.9.3), else the one I've studied most these 30
        days, else the biggest."""
        from .planner.flow import StartOps
        have = {d for d, _n in choices}
        state = plan_flow._state_cfg()
        top = lambda st: self.top_of(st["deck_id"]) if isinstance(st, dict) and st.get("deck_id") else None  # noqa: E731
        shown = top(state.get(cfg().get("plan_pick")))
        ids = [d for d in map(top, state.values()) if d]
        for did in ([shown] if shown else []) + sorted(set(ids), key=lambda d: (-ids.count(d), ids.index(d))):
            if did in have:
                return did
        try:
            most = StartOps().new_defaults().get("deck")
        except Exception:
            most = None
        if most in have:
            return most
        return choices[0][0] if choices else None

    def index(self, did):
        return P.DeckIndex(mw.col, did)

    def top_of(self, did):
        from .planner.flow import _top_deck
        return _top_deck(mw.col, did)

    def find(self, q):
        try:
            return {int(c) for c in mw.col.find_cards(q)}
        except Exception:
            return None  # Anki can't read it

    def followed(self):
        """[(plan, state, my doc)] I follow, as I run them."""
        state = plan_flow._state_cfg()
        out = []
        for p in plan_flow.followed():
            st = state.get(p.get("id"))
            if st:
                out.append((p, st, plan_flow.mine(p)["doc"]))
        return out

    def plan_idx(self, pid):
        return plan_flow._plan_idx(pid)

    def day_loads(self, idx, today, days=DAYS):
        """[n]: reviews due on each of the next `days` days in this deck (today's: due by today)."""
        try:
            day = int(mw.col.sched.today)
        except Exception:
            return [0] * days
        ids = ",".join(str(int(c)) for c in idx.home) or "0"
        rows = dict(mw.col.db.all(f"SELECT max(due - {day}, 0), count() FROM cards WHERE id IN ({ids}) "
                                  f"AND queue IN (2, 3) AND due <= {day + days - 1} GROUP BY 1"))
        return [int(rows.get(i, 0) or 0) for i in range(days)]

    def signed_in(self):
        return bool(client().signed_in)

    def my_plans(self, done):
        """The plans I write or follow (GET /plans/mine), done(list or None) on the main thread."""
        cl, gen = client(), app.generation

        def job():
            from .planner import remote
            try:
                return remote.my_plans(cl)
            except Exception:  # noqa: BLE001 (offline: My plan alone)
                return None
        _bg(job, lambda got: gen == app.generation and done(got))

    def write_plan(self, pid, ops, idx, done, name=None, deck=None):
        """The ops on a plan of mine: saved now when nobody else follows it,
        else added to its waiting changes (Review and send). pid None: My
        plan, made first (name, deck) and followed here on idx's deck.
        done((how, pid, version or None, words)) on the main thread: how is
        "saved", "waiting", or "failed"."""
        cl, gen = client(), app.generation
        from .planner import remote
        from .planner import ops as O
        from .planner import build as B
        from .planner import edits as E
        from .planner.core import others
        tree = B.Tree(*idx.tree())
        today = plan_flow._today()

        def job():
            made = None
            try:
                code = ""
                if pid is None:
                    outcome, raw = remote.create(cl, name or MY_PLAN, deck or idx.name)
                    if outcome != "saved":
                        return "failed", None, None, str(raw or "Couldn't start My plan.")
                    made, plan, code = raw["id"], None, str(raw.get("code") or "")
                else:
                    raw, plan = remote.load(cl, pid)
                ctx = O.Ctx(tree, today, str(raw.get("name") or name or MY_PLAN))
                if plan is not None and others(plan) > 0:
                    return "waiting", pid, raw, ops
                doc, touched = raw["doc"], set()
                for o in ops:
                    o = O.check(doc, o)
                    doc, _entries, t = O.apply(doc, o, ctx)
                    touched |= t
                summary = E.what_changed(raw["doc"], doc) or "added in Magic search"
                outcome, got = remote.save(cl, made or pid, raw.get("version") or 1, doc, summary[:120])
                if outcome != "saved":
                    return "failed", made or pid, None, "It changed since: try again." if outcome == "stale" else str(got)
                return "saved", made or pid, got, (code or "-") if made else ""
            except E.Refused as e:
                return "failed", made or pid, None, str(e)
            except TransportError:  # offline, or the plan gone: said in the window, never Anki's error box
                return "failed", made or pid, None, "Couldn't reach Due Crew. Check your connection."
            except Exception:  # noqa: BLE001
                oops()
                return "failed", made or pid, None, "That didn't save. Try again."

        def back(got):
            if gen != app.generation or not mw.col:
                return
            how, got_pid, raw, more = got
            if how == "waiting":
                return done(self._wait(got_pid, raw, more, tree, today))
            if how != "saved":
                return done(("failed", got_pid, None, more))
            if more:  # My plan, just made: followed here, on this deck
                return self._follow_new(raw, idx.did, done, "" if more == "-" else more)
            self._note_saved(raw)
            done(("saved", got_pid, raw.get("version"), ""))
        _bg(job, back)

    def _wait(self, pid, raw, ops, tree, today):
        from .planner import ops as O
        from .planner.draft import Draft
        from .planner.flow import Ops as PlanOps
        from .planner import edits as E
        po = PlanOps()
        d = po.draft(pid) or Draft(pid, raw["doc"], raw.get("version"))
        ctx = O.Ctx(tree, today, str(raw.get("name") or ""))
        n0 = len(d)
        try:
            for o in ops:
                d.add(o, ctx)
        except E.Refused as e:
            del d.ops[n0:]
            d._cache = None
            return "failed", pid, None, str(e)
        po.keep_draft(pid, d)
        return "waiting", pid, None, len(d) - n0

    def _follow_new(self, raw, did, done, code=""):
        """My plan, made: followed here on `did` (POST /plans/follow), as New plan's Start it."""
        cl, gen = client(), app.generation
        code = code or str(raw.get("code") or "")
        c = plan_flow._pcfg()
        c["magic_plans"] = dict(c.get("magic_plans") or {}, **{str(did): raw["id"]})
        plan_flow._psave(c)
        if not code:
            done(("saved", raw["id"], raw.get("version"), "made"))
            return

        def followed(res):
            got = res[0] if isinstance(res, tuple) else None
            if gen != app.generation or not mw.col:
                return
            if got is not None:
                plan_flow.on_followed(dict(got, paused=False, following=True), did, None, "open", False)
            done(("saved", raw["id"], raw.get("version"), "made"))
        _bg(lambda: cl.follow_plan(code, False), followed)

    def _note_saved(self, raw):
        """A plan I follow, saved here: the board's copy is this one, and what's due today opens now."""
        from .backend.shapes import clean_plan
        cl = client()
        fresh = clean_plan(raw) if isinstance(raw, dict) else None
        had = next((p for p in cl.session.get("plans") or [] if p.get("id") == (fresh or {}).get("id")), None)
        if fresh is None or had is None:
            return
        cl.remember_plan(dict(had, doc=fresh["doc"], version=fresh.get("version") or had.get("version")))
        plan_flow._open_now([x for x in plan_flow.followed() if x["id"] == fresh["id"]], toast=False)
        app.swap(cfg())

    def undo_save(self, pid, version, done):
        """The builder's Undo on a save of mine."""
        from .planner import remote
        cl, gen = client(), app.generation

        def job():
            try:
                return remote.undo(cl, pid, version)
            except Exception:  # noqa: BLE001
                return None

        def back(got):
            if gen != app.generation:
                return
            if isinstance(got, tuple) and got[0] == "saved":
                self._note_saved(got[1])
                return done(True)
            done(False)
        _bg(job, back)

    def undo_draft(self, pid, n):
        """The last n changes waiting on a plan, taken back."""
        from .planner.flow import Ops as PlanOps
        po = PlanOps()
        d = po.draft(pid)
        if d is None:
            return False
        del d.ops[max(0, len(d) - n):]
        d._cache = None
        po.keep_draft(pid, d)
        return True

    def settings(self, parts):
        """A change as Settings makes it (setexam, setaway): {key: old value} to put back, or None."""
        from .settings_model import change
        c = cfg()
        got = change(parts, c, today=self.today())
        if not got or app.apply_settings is None:
            return None
        old = {k: c.get(k, "") for k in got}
        app.apply_settings(got)
        return old

    def put_back(self, old):
        if app.apply_settings is not None and old:
            app.apply_settings(dict(old))

    def set_days(self, pid, done, **fields):
        cl, gen = client(), app.generation
        _bg(lambda: cl.set_days(pid, **fields), lambda got: gen == app.generation and done(got))

    # ---- Anki's steps ----

    def unsuspend(self, cids):
        """Unsuspend: actions.unsuspend (the new ones first in line, one undo
        step), then what plan_flow does after an open (at my own pace, a date
        now all open). How many."""
        from .planner import actions
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

    def study(self, cids, name, order=None):
        """Study now: actions.study into Due Crew › name, rescheduled by my
        answers, each card back to its own deck once done (QBank cards'
        way: each paste adds to it), then Anki's Study screen. order: Anki's
        (the deck's own, else QIDs' random)."""
        from .planner import actions
        deck = P.our_deck(name)
        shut = P.openable_ids(mw.col, cids)
        n = len({int(c) for c in cids})
        how = plan_flow.NEW_ORDER if order is None else int(order)
        opened, had = actions.study(mw.col, cids, f"Due Crew: study {n:,} card{'s' if n != 1 else ''}", deck,
                                    lambda want: plan_flow._filtered(mw.col, deck, want, order=how))
        if opened:
            plan_flow._claim_opened(shut)
            plan_flow.refresh_progress()
        if opened or had:
            plan_flow._after_change()
        if not had:
            tooltip("None of them can be studied now (buried, or in another filtered deck).")
            return False
        did = mw.col.decks.id_for_name(deck)
        if did:
            mw.col.decks.select(did)
            mw.moveToState("overview")
        return True

    def keep(self, name, q, cids, limit, order):
        """Keep as a filtered deck: one named `name` holding the search `q`
        (Rebuild fills it again), its suspended cards opened first, one undo
        step. Its id, or None."""
        col = mw.col
        label = f"Due Crew: {name}"
        had = col.decks.id_for_name(name)
        if had and not (col.decks.get(had, default=False) or {}).get("dyn"):
            return None  # a deck of mine has the name
        shut = P.openable_ids(col, cids)
        pos = _undo_start(col, label)
        try:
            if shut:
                col.sched.unsuspend_cards(shut)
                P.first_in_line(col, shut)
            deck = col.sched.get_or_create_filtered_deck(deck_id=had or 0)
            deck.name = name
            del deck.config.search_terms[1:]
            term = deck.config.search_terms[0]
            term.search, term.limit, term.order = q, int(limit or KEEP_LIMIT), int(order)
            deck.config.reschedule = True
            got = col.sched.add_or_update_filtered_deck(deck)
            did = int(getattr(got, "id", 0) or 0) or col.decks.id_for_name(name)
        except Exception:
            oops()
            did = None
        finally:
            _undo_end(col, pos)
        if shut:
            plan_flow._claim_opened(shut)
        plan_flow._after_change()
        return did

    def add_to(self, did, cids):
        """Add to a filtered deck I have: these cards join its first search
        ("(its search) OR cid:…", the ones added before kept together) and its
        limit, and it's rebuilt; suspended ones opened first. One undo step.
        How many it holds now, or None."""
        col = mw.col
        name = col.decks.name(int(did))
        shut = P.openable_ids(col, cids)
        pos = _undo_start(col, f"Due Crew: add to {name}")
        try:
            if shut:
                col.sched.unsuspend_cards(shut)
                P.first_in_line(col, shut)
            deck = col.sched.get_or_create_filtered_deck(deck_id=int(did))
            term = deck.config.search_terms[0]
            term.search = add_cids(term.search, cids)
            term.limit = min(KEEP_LIMIT * 10, int(term.limit or 0) + len(set(cids)))
            col.sched.add_or_update_filtered_deck(deck)
            n = int(col.db.scalar("SELECT count() FROM cards WHERE did = ?", int(did)) or 0)
        except Exception:
            oops()
            n = None
        finally:
            _undo_end(col, pos)
        if shut:
            plan_flow._claim_opened(shut)
        plan_flow._after_change()
        return n

    def pace(self):
        """My pace from my answer log these 4 weeks (one read, when the window
        first needs it): a new card's first-day seconds, a review's, my
        usual day's minutes (magic.pace_from)."""
        col = mw.col
        cut = int(col.sched.day_cutoff)
        since = (cut - 28 * 86400) * 1000
        new_ms, new_cards = col.db.first("SELECT total(time), count(DISTINCT cid) FROM revlog WHERE id > ? AND type = 0", since) or (0, 0)
        rev_ms, rev_n = col.db.first("SELECT total(time), count() FROM revlog WHERE id > ? AND type = 1", since) or (0, 0)
        days = [int(ms or 0) / 60000 for _d, ms in col.db.all(
            "SELECT (id / 1000 - ?) / 86400, total(time) FROM revlog WHERE id > ? GROUP BY 1", cut, since)]
        return M.pace_from(float(new_ms or 0), int(new_cards or 0), float(rev_ms or 0), int(rev_n or 0), days)

    def in_filtered(self, cids):
        """[(deck, n)]: these cards sitting in a filtered deck now (another one
        can't take them), the most first."""
        ids = ",".join(str(int(c)) for c in cids) or "0"
        rows = mw.col.db.all(f"SELECT did, count() FROM cards WHERE odid != 0 AND id IN ({ids}) GROUP BY did")
        return sorted(((self.deck_name(d) or "a filtered deck", int(k)) for d, k in rows), key=lambda x: -x[1])

    def plan_dates(self, did, idx, cids):
        """[(plan name, [date label])]: the dates of the plans I follow on this
        deck that hold any of these cards (my dates). QBank QIDs' line."""
        out = []
        state = plan_flow._state_cfg()
        for p in plan_flow.followed():
            st = state.get(p["id"]) or {}
            if not st.get("deck_id") or self.top_of(st["deck_id"]) != did:
                continue
            dates = P.dates_with(idx, p["doc"], cids, plan_flow._swap(st))
            if dates:
                out.append((str(p.get("name") or "Plan"), [P.fmt_day(u.get("opens")) for u in dates]))
        return out

    def deck_map(self, did):
        """3.9.5, Their topics: the deck's topic map as Insights draws it, its
        top level, and the cards I missed these 4 weeks: (tiles, missed)."""
        from . import team_flow
        return team_flow.deck_map(did)

    def study_topic(self, name, cids):
        """3.9.5: a topic's Study, the map's deck of what I missed there. True when it took."""
        from . import team_flow
        return team_flow.study_deck(name, cids)

    def open_kinds(self, cids):
        """3.9.9: which of these a plan's date can't hold till its day, being open
        already: {cid: "new"} (not started, not suspended) and {cid: "rev"} (a
        review due today or before); in their own decks (a filtered deck's stay)."""
        if not mw.col or not cids:
            return {}
        today, out = int(mw.col.sched.today), {}
        ids = ",".join(str(int(c)) for c in cids)
        for cid, ctype, queue, due in mw.col.db.all(
                f"SELECT id, type, queue, due FROM cards WHERE id IN ({ids}) AND odid = 0 AND queue IN (0, 1, 2, 3)"):
            if queue in (1, 3):
                out[int(cid)] = "learn"  # in its steps: never moved (a move would start them again), only said
            elif ctype == 0 and queue == 0:
                out[int(cid)] = "new"
            elif ctype == 2 and queue == 2 and int(due) <= today:
                out[int(cid)] = "rev"
        return out

    def spread(self, shares):
        """Schedule ahead on cards that are open already (Sam, 10 Nov: unsuspended
        cards due on one day, put on the next few, stayed where they were: a date
        only opens what's suspended). shares: [(days from today, [new], [rev])].
        A later day's new cards are held back (suspended: its date opens them that
        morning) and its due reviews get that day as their due date (Anki's Set
        due date: the interval stays). One undo step. (held, moved, its label)."""
        col = mw.col
        held = [c for n, new, _rev in shares if n > 0 for c in new]
        moved = sum(len(rev) for n, _new, rev in shares if n > 0)
        if not col or not (held or moved):
            return 0, 0, ""
        label = f"Due Crew: spread {len(held) + moved:,} card{'s' if len(held) + moved != 1 else ''} over days"
        pos = _undo_start(col, label)
        try:
            if held:
                col.sched.suspend_cards(held)
            for n, _new, rev in shares:
                if n > 0 and rev:
                    col.sched.set_due_date(rev, str(int(n)))
        except Exception:
            oops()
        _undo_end(col, pos)
        plan_flow._after_change()
        app.swap(cfg())
        return len(held), moved, label

    def exam_day(self):
        """My exam's day (Settings › Privacy › Exam), or ""."""
        return str(cfg().get("exam_date") or "")

    def undo_anki(self, label):
        """Edit › Undo, when the last step is still ours."""
        if plan_flow._undo_ok(label):
            try:
                mw.undo()
                return True
            except Exception:
                oops()
        return False

    def browse(self, cids, q=None):
        plan_flow._browse(cids, q=q, empty="None of them are in this deck.")

    def refs(self, cids):
        return P.card_refs(mw.col, cids)

    def open_plans(self, pid):
        from .planner import flow
        flow.open_plans(select=pid)

    def seen_intro(self):
        return bool(cfg().get("magic_seen"))

    def saw_intro(self):
        c = cfg()
        if not c.get("magic_seen"):
            if app.apply_settings is not None:
                app.apply_settings({"magic_seen": True})
            else:
                c["magic_seen"] = True
                save_cfg(c)

    def recent(self):
        return [str(x) for x in cfg().get("magic_recent") or [] if isinstance(x, str)][:RECENT]

    def note_recent(self, text):
        t = " ".join(str(text or "").split())[:200]
        if not t or "\n" in str(text):
            return
        c = cfg()
        c["magic_recent"] = ([t] + [x for x in c.get("magic_recent") or [] if x != t])[:RECENT]
        save_cfg(c)


def _undo_start(col, label):
    try:
        return col.add_custom_undo_entry(label)
    except Exception:
        return None


def _undo_end(col, pos):
    if pos is not None:
        try:
            col.merge_undo_entries(pos)
        except Exception:
            pass


def add_cids(search, cids):
    """A filtered deck's search with these cards added: "(it) OR cid:…", the
    cards added before and these as one list."""
    s = str(search or "").strip()
    m = re.fullmatch(r"\((.*)\) OR cid:([0-9,]+)", s, re.S)
    base, had = (m.group(1), [int(x) for x in m.group(2).split(",") if x]) if m else (s, [])
    ids = sorted(set(had) | {int(c) for c in cids})
    if not base:
        return "cid:" + ",".join(map(str, ids))
    return f"({base}) OR cid:" + ",".join(map(str, ids))


# ---- the window's logic: what it shows, what a click does ----

class Search:
    """The box, its reading, the picks on it and what it can do. Qt-free:
    the window hands it the page's clicks (on) and draws its view."""

    def __init__(self, ops):
        self.ops = ops
        self.push = lambda: None   # the window: draw the view again
        self.close_win = lambda: None
        self.text, self.cids_in = "", None
        self.idx, self.tree, self.did = None, None, None
        self._idx = {}
        self.r = M.read("", None, ops.today())
        self.flip, self.tag_off = set(), set()
        self.open_segs, self.seg_off = set(), set()  # round 3: a typed topic's tree open; a topic left out whole
        self.filters, self.filters_set = [], False
        self.how = "nd"
        self.picked, self.day_name = [], ""
        self.dest, self.dests = "mine", None
        self.said, self.undo = None, None
        self.intro = False         # the how-to: the Decks screen shows it once (board_howto), ? here any time
        self._tries = {}           # a deck's how-to tries, read against its tags: did -> {part: [tries]}
        self.busy = False
        self.mode = ""             # "days": the day picker open
        self.fill = None           # {from, to, skip}: a stretch longer than the picker, filled in (3.9.9)
        self._cards, self._q = None, ""
        choices = ops.decks()
        self.decks = choices
        self.every = ops.all_decks()      # read once a window: a deck said by its name
        self.filtered = ops.filtered_decks()
        self._loads, self._btree = {}, {}
        self.bank_pick, self._qf, self._maps, self._topics = None, None, {}, []  # QBank QIDs: the bank I picked, the find, decks' maps, Their topics
        self._pace, self._found = None, None  # round 3: my pace (read once a window), what was found (once a reading)
        self.pick_deck(ops.default_deck(choices) if choices else None)

    # -- state --

    def prefill(self, text="", cids=None):
        if cids:
            self.cids_in = [int(c) for c in cids]
            top = self.ops.top_of(self.ops.home_deck(self.cids_in[0]))
            if top:
                self.pick_deck(top)
            self.text = ""
            self.mode = "days"
        if text:
            self.cids_in = None
            self.text = str(text)
        self.reread()

    def pick_deck(self, did):
        if did is None:
            return
        self.did = int(did)
        if self.did not in self._idx:
            idx = self.ops.index(self.did)
            self._idx[self.did] = (idx, tree_of(idx))
        self.idx, self.tree = self._idx[self.did]

    def plans_for_words(self):
        out = []
        for p, _st, doc in self.ops.followed():
            out.append({"id": p["id"], "name": p.get("name") or "Plan",
                        "units": [{"id": u.get("id"), "name": u.get("name"), "opens": u.get("opens"), "for": u.get("for")}
                                  for u in P.units(doc)],
                        "events": [e for e in doc.get("events") or [] if isinstance(e, dict)]})
        return out

    def reread(self):
        plans = self.plans_for_words()
        self.r = M.read(self.text, self.tree, self.ops.today(), self.every, plans)
        if self.r.get("deck"):
            top = self.ops.top_of(self.r["deck"])
            if top and top != self.did:
                self.pick_deck(top)
                self.r = M.read(self.text, self.tree, self.ops.today(), self.every, plans)
        self.flip, self.tag_off, self.seg_off = set(), set(), set()
        self.filters, self.filters_set = [dict(f) for f in self.r["filters"]], False
        # Sam: "seeing the tag tree is really important": the first topic's tree open, the rest a tap away
        first = next((g["seg"] for g in self.r["groups"] if g["on"]), None)
        self.open_segs = {first} if first is not None else set()
        self.how = "all" if (self.r["kind"] in ("ids", "search") or self.filters or self.cids_in) else "nd"
        self._cards = None
        if any(a["k"] == "before" for a in self.r["acts"]):
            ev = next(a for a in self.r["acts"] if a["k"] == "before")
            self.picked = self.days_before(ev["day"])
        elif not self.cids_in:
            self.picked = []
        self.fill = None
        self.day_name = ""
        self.spread()

    def spread(self):
        """3.9.9: the days the words asked for ("over the next 5 days", "by
        Friday", "20 a day", or only "spread …"), picked in Schedule ahead:
        the picker's two weeks of them, said when the words asked for more."""
        sp = self.r.get("span")
        if not sp:
            if getattr(self, "_spread_on", False):  # the words no longer ask: the picker they opened shuts
                self._spread_on, self.mode = False, ""
            return
        today = self.ops.today()
        last = (today + datetime.timedelta(days=DAYS - 1)).isoformat()
        days = [d for d in sp["days"] if today.isoformat() <= d <= last]
        more = len(days) < len(sp["days"])
        if more and not sp.get("per"):  # longer than the picker shows: the fill-in's stretch (Sam: "add the fill in option")
            self.c_fill(to=sp["days"][-1], first=sp["days"][0])
            self.mode, self._spread_on = "days", True
            return
        if sp.get("per"):
            n = len(self.cards()[0])
            need = max(1, -(-n // int(sp["per"])))
            if not days:
                more = need > DAYS - 1
                days = [(today + datetime.timedelta(days=k)).isoformat() for k in range(1, min(need, DAYS - 1) + 1)]
            elif need < len(days):
                days = days[:need]
        if not days and not sp["days"]:
            self.picked = []
            self.c_days(True)  # "spread cardio": the days it takes at my pace
        else:
            self.picked = days
            self.mode = "days"
        self._spread_on = True
        if more and self.picked:
            self.said = {"text": f"{M.words_span(self.picked[0], self.picked[-1])} picked. Go longer below for more days."}

    def days_before(self, day):
        today = self.ops.today()
        end = datetime.date.fromisoformat(day)
        n = (end - today).days - 1
        if n < 1:
            return [today.isoformat()] if end > today else []
        first = max(1, n - BEFORE_MAX + 1)
        return [(today + datetime.timedelta(days=k)).isoformat() for k in range(first, n + 1)]

    # -- what's found --

    def offs(self):
        """The chips toggled from the reading's own: my taps (flip), and a topic
        I left out whole (seg_off) takes its ticked ones out with it."""
        out = set(self.flip)
        for i, g in enumerate(self.r["groups"]):
            if g.get("seg") in self.seg_off and (bool(g["on"]) != (i in self.flip)):
                out ^= {i}
        return out

    def ticked(self):
        return M.ticked_tags(self.r, self.offs(), self.tag_off)

    def joined_cards(self, deck_q):
        """Sam: "AND statements and OR statements on tags": each term's topics'
        cards in all of them ("both heart failure and pharm"), the terms'
        together ("…, or renal"). A topic no tag says is its words in the
        cards' text; one whose chips are all off, none (nothing is in both)."""
        r, idx = self.r, self.idx
        by_seg = M.ticked_by_seg(r, self.offs(), self.tag_off)
        has = {g["seg"] for g in r["groups"]}
        words = r.get("seg_words") or []
        out = set()
        for term in r.get("terms") or ():
            got = None
            for sg in term:
                if sg in by_seg:
                    cs = set()
                    for t in by_seg[sg]:
                        cs |= idx.tag_cards(t)
                elif sg not in has and sg < len(words) and words[sg]:
                    cs = self.ops.find(f"{deck_q} {M.text_q(words[sg])}") or set()
                else:
                    cs = set()
                got = cs if got is None else got & cs
            out |= got or set()
        return out

    def reading(self):
        return dict(self.r, filters=self.filters)

    def cards(self):
        """(cids in the deck's order, the search they're kept by) for what's
        ticked and typed now. A topic's cards come from the deck's own index
        (a tag in Anki's search costs a fifth of a second on a big shared
        deck's 45,000 tags); Anki's search runs only the filters, the cards'
        text, a pasted search and IDs."""
        if self._cards is not None:
            return self._cards
        r, idx = self.reading(), self.idx
        if idx is None:
            self._cards = ([], "")
            return self._cards
        fq = M.filters_q(self.filters)
        deck_q = M.deck_q(self.ops.deck_name(r["deck"]) if r.get("deck") else idx.name)
        base = None  # the cards it's about, before the filters; None: the whole deck
        if self.cids_in is not None:
            base = set(self.cids_in) & set(idx.home)
        elif r["kind"] in ("do", "plantext"):
            base = set()
        elif r["kind"] == "empty":
            base = None if self.filters else set()
        elif r["kind"] == "ids":
            base = set(self.qfind()["cids"]) if r["qids"] else set()
            if r["ids"]:
                # a note's id first; a card's only when no note has it (both come from the clock, and can meet)
                by_note = self.ops.find("nid:" + ",".join(r["ids"])) or set()
                notes = {str(idx.nid_of.get(c)) for c in by_note}
                rest = [i for i in r["ids"] if i not in notes]
                base |= by_note | ((self.ops.find("cid:" + ",".join(rest)) or set()) if rest else set())
        elif r["kind"] == "search":
            base = self.ops.find(f"{deck_q} ({r['search']})") or set()
        else:
            tags = self.ticked()
            if M.joined(r):
                base = self.joined_cards(deck_q)  # "both A and B", A AND B, A with B
            elif tags or r.get("plan"):
                base = set()
                for t in tags:
                    base |= idx.tag_cards(t)
            elif r["text"]:
                base = self.ops.find(f"{deck_q} {M.text_q(r['text'])}") or set()
            elif not (self.filters or r.get("deck")):
                base = set()
            if r.get("plan"):
                base = set(base or ())
                hit = r["plan"]
                got_p = self.ops.plan_idx(hit["pid"])
                if got_p:
                    _p, st, doc, pidx = got_p
                    for u in P.units(doc):
                        if u.get("id") in hit["uids"]:
                            base |= pidx.match(u, plan_flow._swap(st), doc)
        for g in r.get("neg") or ():
            for t in g.get("tags") or ():
                if base is None:
                    base = set(idx.home)
                base -= idx.tag_cards(t)
        if r.get("deck") and base is not None:
            base &= self.ops.deck_cards(r["deck"], idx)
        if base is not None and not base:
            got = set()
        elif fq or base is None:
            got = self.ops.find(f"{deck_q} {fq}".strip()) or set()
            if base is not None:
                got &= base
        else:
            got = base
        cids = sorted((c for c in got if c in idx.cards), key=lambda c: idx.order.get(c, (True, 0, c)))
        if r.get("limit"):
            cids = cids[:r["limit"]]
        # what a kept deck holds: the exact cards when it's "10 of them", else the deck's filters live
        # over the cards it's about (Rebuild runs the filters again: this week's misses are this week's)
        if not cids:
            q = ""
        elif r.get("limit"):
            q = "cid:" + ",".join(str(c) for c in sorted(cids))
        elif base is None:
            q = f"{deck_q} {fq}".strip()
        else:
            q = ("cid:" + ",".join(str(c) for c in sorted(base)) + (" " + fq if fq else ""))
        self._cards = (cids, q)
        return self._cards

    def qfind(self):
        """QBank QIDs' own find (planner/qids.py): in the bank I picked, else
        the one the words named ("qbank 2345 …"), else the one with most.
        Once a reading."""
        from .planner import qids as Q
        key = (self.did, tuple(self.r["qids"]), self.r.get("bank"), self.bank_pick)
        if self._qf is None or self._qf[0] != key:
            have = Q.banks(self.idx)
            bank = self.bank_pick if self.bank_pick in have else None
            if bank is None and self.r.get("bank"):
                want = re.sub(r"[^a-z0-9]", "", self.r["bank"])
                bank = next((b for b in have if re.sub(r"[^a-z0-9]", "", b.lower()) == want), None)
            self._qf = (key, Q.find(self.idx, " ".join(self.r["qids"]), bank=bank))
        return self._qf[1]

    def qids_view(self):
        """What the QBank QIDs window said (3.9.3 to 3.9.6; Magic search has it
        since 3.9.7, round 2, Sam: "this is replacing QBank QID search"): how
        many are questions, the bank when two are close (or I picked one), and
        Their topics (3.9.5): the map's parts they're in, each with a Study of
        what I missed there. None unless it's QIDs."""
        from .planner import qids as Q
        r = self.r
        if r["kind"] != "ids" or not r["qids"] or self.idx is None or not Q.banks(self.idx):
            return None
        f = self.qfind()
        out = {"q": len(f["found"]), "banks": [b for b, _n in f["banks"]], "bank": f["bank"],
               "ask": Q.close(f) or self.bank_pick is not None, "topics": [], "more": ""}
        if f["cids"]:
            if self.did not in self._maps:
                self._maps[self.did] = self.ops.deck_map(self.did)
            tiles, missed = self._maps[self.did]
            rows = Q.topics(self.idx, f, tiles, missed)
            self._topics = rows
            out["topics"] = [{"i": i, "name": x["name"], "line": line, "missed": len(x["missed"])}
                             for i, (x, line) in enumerate(list(zip(rows, Q.topic_words(rows)))[:Q.TOPICS_SHOWN])]
            out["more"] = Q.more_topics(rows)
        return out

    def tally(self, cids):
        idx = self.idx
        t = {"n": 0, "new": 0, "seen": 0, "susp": 0, "due": 0, "leech": 0, "nd": 0, "all": 0}
        for c in cids:
            queue, ctype = idx.cards.get(c, (0, 0))
            t["n"] += 1
            t["new" if ctype == 0 else "seen"] += 1
            t["susp"] += queue == -1
            t["due"] += c in idx.due_now
            leech = c in idx.leech
            t["leech"] += leech
            if not leech:
                t["all"] += 1
                t["nd"] += ctype == 0 or c in idx.due_now
        return t

    def study_ids(self, cids):
        idx = self.idx
        if self.how == "all":
            return [c for c in cids if c not in idx.leech]
        return [c for c in cids if c not in idx.leech and (idx.cards.get(c, (0, 0))[1] == 0 or c in idx.due_now)]

    def name(self):
        """What the cards are, in a few words: the topics, a plan's set, the QIDs, the text."""
        r = self.r
        if self.cids_in is not None:
            return f"{len(self.cids_in):,} picked"
        if r.get("plan"):
            return r["plan"]["name"]
        offs = self.offs()
        said = M.topics_said([dict(g, on=(g["on"] if i not in offs else not g["on"])) for i, g in enumerate(r["groups"])],
                             r.get("terms"))
        if said:
            return said
        if r["kind"] == "ids":
            from .planner import actions
            return actions.DECK if r["qids"] else "These IDs"  # QBank QIDs' Study now: each paste adds to its deck
        if r["text"]:
            return r["text"].capitalize()
        if self.filters:
            return " · ".join(M.filter_label(f) for f in self.filters)
        return "Cards"

    # -- the view --

    def view(self):
        r = self.r
        cids, q = self.cards()
        t = self.tally(cids) if cids or q or r["kind"] not in ("empty", "do", "plantext") else None
        have = {f["k"]: f for f in self.filters}
        row = [{"k": k, "label": M.filter_label({"k": k}), "on": k in have} for k in M.ROW]
        row = [{"k": f["k"], "label": M.filter_label(f), "on": True, "n": f.get("n")} for f in self.filters
               if f["k"] not in M.ROW] + row
        f = self.found()
        v = {"intro": self.intro, "howto": self.howto() if self.intro else None, "text": self.text, "decks": [{"did": d, "name": n} for d, n in self.decks],
             "did": self.did, "kind": r["kind"], "topics": self.topics_view(), "neg": [g["name"] for g in r["neg"]],
             "filters": row, "limit": r.get("limit"), "count": t, "q": q, "how": self.how,
             "rows": self.rows(), "said": self.said, "busy": self.busy, "mode": self.mode,
             "recent": self.ops.recent() if r["kind"] == "empty" else [],
             "picked": self.cids_in is not None, "name": self.name(), "signed_in": self.ops.signed_in(),
             "lines": self.lines(cids, t), "qids": self.qids_view(), "terms": r.get("terms") or [],
             "found": f, "tiles": self.tiles_view(f)}
        if self.mode == "days" or self.picked:
            v["days"] = self.days_view(cids)
        v["dests"] = self.dests_view()
        v["dest"] = self.dest
        v["filtered"] = [{"did": d, "name": n} for d, n in self.filtered]
        if r["kind"] == "plantext":
            v["plantext"] = self.plantext_view()
        return v

    # -- round 3 (Sam: "giving the user enough information about what has been found so that they can take the
    # appropriate action"): one row a typed topic and its tree, what was found, four tiles --

    def topics_view(self):
        """One row a typed topic: its ticked names as one (Sam: "combine things
        with similar names so long as the tag goes all the way to the end"),
        their cards, the near names as Also under it, and its tree when open:
        each tag to its last part, under where it's from, a resource's cards
        once each. [{seg, name, on, can, n, ntags, open, join, also, tree}]."""
        r, idx = self.r, self.idx
        if idx is None or not r["groups"]:
            return []
        flipped = lambda i, g: bool(g["on"]) != (i in self.flip)  # noqa: E731 (what my taps left ticked, a topic left out aside)
        term = {sg: ti for ti, t in enumerate(r.get("terms") or []) for sg in t}
        sizes = {ti: len(t) for ti, t in enumerate(r.get("terms") or [])}
        words = r.get("seg_words") or []
        found = set(self.cards()[0])  # what it found: a filter, a but not or a number narrows a topic's cards
        out, prev = [], None
        for sg in sorted({g["seg"] for g in r["groups"]}):
            gs = [(i, g) for i, g in enumerate(r["groups"]) if g["seg"] == sg]
            named = [(i, g) for i, g in gs if flipped(i, g)]
            on = named if sg not in self.seg_off else []
            tags = list(dict.fromkeys(x for _i, g in on for x in g["tags"]))
            cards = set()
            for x in tags:
                if x not in self.tag_off:
                    cards |= idx.tag_cards(x)
            joined = sizes.get(term.get(sg), 1) > 1
            kept = len(cards & found)
            row = {"seg": sg, "name": (named or gs)[0][1]["name"] if named else (words[sg] if sg < len(words) else gs[0][1]["name"]),
                   "on": bool(on), "can": bool(named), "n": len(cards), "ntags": len(tags),
                   "in": kept if on and kept != len(cards) and not joined else None,  # "13 of 798": the ones it found
                   "open": sg in self.open_segs and bool(tags),
                   "join": "with" if prev is not None and term.get(sg) == term.get(prev) and joined else "",
                   "also": [{"i": i, "name": g["name"], "n": g["cards"]} for i, g in gs if not flipped(i, g)][:ALSO_MAX]}
            if row["open"]:
                roots = len({str(x).split("::")[0].lower() for x in tags}) > 1
                row["tree"] = M.tag_list([dict(M.tag_row(x, roots=roots), t=x, on=x not in self.tag_off, n=len(idx.tag_cards(x)))
                                          for x in tags], idx.tag_cards)
            out.append(row)
            prev = sg
        return out

    def pace(self):
        if self._pace is None:
            try:
                self._pace = self.ops.pace()
            except Exception:
                oops()
                self._pace = dict(M.PACE)
        return self._pace

    def found(self):
        """What it found, each card once by what Study now would do with it:
        due now, new (and how many of those are suspended), seen and not due
        yet; leeches left out; how long Study now's set is at my pace, beside
        my usual day; any sitting in another filtered deck. None for nothing."""
        cids, _q = self.cards()
        if self._found is not None and self._found[0] is self._cards:
            return self._found[1]
        f = None
        if cids and self.idx is not None:
            idx = self.idx
            f = {"n": len(cids), "due": 0, "new": 0, "susp_new": 0, "notdue": 0, "leech": 0, "susp": 0}
            for c in cids:
                queue, ctype = idx.cards.get(c, (0, 0))
                if c in idx.leech:
                    f["leech"] += 1
                    continue
                f["susp"] += queue == -1
                if c in idx.due_now:
                    f["due"] += 1
                elif ctype == 0:
                    f["new"] += 1
                    f["susp_new"] += queue == -1
                else:
                    f["notdue"] += 1
            pace = self.pace()
            f["all"] = self.how == "all"
            rev = f["due"] + (f["notdue"] if f["all"] else 0)
            f["study"] = f["new"] + rev
            sec = M.took(f["new"], rev, pace)
            f["time"] = M.says_time(sec) if f["study"] else ""
            f["usual"] = M.says_time(pace["day_min"] * 60).replace("about ", "") if pace["known"] else ""
            f["big"] = bool(f["study"]) and sec > pace["day_min"] * 60
            f["days"] = M.days_for(sec, pace) if f["big"] else 0
            own = P.our_deck(self.name())
            f["infilt"] = [[name, k] for name, k in self.ops.in_filtered(cids) if name != own]
        self._found = (self._cards, f)
        return f

    def tiles_view(self, f):
        """Study now, Schedule ahead, Make a new filtered deck, Unsuspend (Sam's
        four), the one that fits filled: Schedule ahead when it's more than my
        usual day, else Study now (Unsuspend when only that's left to do)."""
        if not f:
            return None
        rec = "days" if f["big"] else ("study" if f["study"] else ("uns" if f["susp"] else ""))
        every = f["new"] + f["due"] + f["notdue"]
        return {"study": f["study"], "all": every if not f["all"] and f["notdue"] else 0, "days": f["days"],
                "keep": self.name(), "uns": f["susp"], "rec": rec,
                "deck": P.our_deck(self.name()).replace("::", " \u203a ")}

    def howto(self):
        """The how-to's words, its tries this deck's: the resource one from its
        own tags, and each try that needs a tag kept only when reading it here
        ticks something (no "heart failure" to tap in a deck that hasn't it)."""
        if self.did not in self._tries and self.idx is not None:
            have = dict(M.examples(self.idx.tag_names.values()))
            today, kept = self.ops.today(), {}
            for x in M.HOWTO["parts"]:
                if x["k"] not in M.TRIED:
                    continue
                kept[x["k"]] = [t for t in have.get(x["k"], x.get("try") or []) if _ticks(M.read(t, self.tree, today), x["k"], self.tree)]
            self._tries[self.did] = kept
        return M.howto(board.MAGIC_KBD, self._tries.get(self.did))

    def lines(self, cids, t):
        r = self.r
        out = []
        if r["kind"] == "ids" and r["qids"] and self.idx is not None:
            from .planner import qids as Q
            found = self.qfind()
            if not Q.banks(self.idx):
                out.append(f"{self.idx.name} has no question IDs in its tags.")
            elif not found["found"]:
                if not r["ids"]:
                    out.append(f"None of these are questions in {self.idx.name}.")
            else:
                dates = self.ops.plan_dates(self.did, self.idx, found["cids"])
                said = Q.words(found, Q.tally(self.idx, found["cids"]), dates)[1:]
                out += [x for x in said if not r["ids"] or not x[:1].isdigit()]  # with note ids pasted, a short number may be neither
        if r["kind"] == "words" and r["text"] and not self.ticked():
            out.append(f"No tag says “{r['text']}”; these cards do." if cids
                       else f"No tag or card says “{r['text']}” in {self.idx.name if self.idx else 'this deck'}.")
        if M.joined(r) and not cids and r["groups"]:
            out.append("No card here is in both." if all(len(x) <= 2 for x in r["terms"]) else "No card here is in all of them.")
        return out

    def rows(self):
        """What's coming up, a row each: {i, k, icon, words, verb, choose, done}."""
        out = []
        today = self.ops.today()
        names = self.name()
        for i, a in enumerate(self.r["acts"]):
            k, row = a["k"], {"i": i, "k": a["k"]}
            if k == "event":
                n = (datetime.date.fromisoformat(a["day"]) - today).days
                row.update(icon="📝", words=[("Add ", ""), (f"{a['name']} · {P.fmt_day(a['day'])}", "b")],
                           note=f"in {n} day{'s' if n != 1 else ''}" if n > 1 else ("tomorrow" if n == 1 else "today"),
                           verb="Add", choose=True)
            elif k == "before":
                days = self.days_before(a["day"])
                cids, _q = self.cards()
                row.update(icon="🗓", words=[("Put ", ""), (names, "b"),
                                             (f" on {M.words_span(days[0], days[-1])}" if days else " before it", ""),
                                             (f" · {len(cids):,} cards" if cids else "", "")],
                           verb="Pick days…", choose=False)
            elif k == "exam":
                n = (datetime.date.fromisoformat(a["day"]) - today).days
                row.update(icon="🎓", words=[("Set your exam: ", ""), (P.fmt_day(a["day"]), "b")], note=f"in {n} days", verb="Set")
            elif k == "away":
                row.update(icon="🧳", words=[("Away ", ""), (M.words_span(a["from"], a["to"]), "b")],
                           note="your crew sees it; plans wait", verb="Set")
            elif k in ("slide", "pause"):
                p = self.my_plan_followed()
                if p is None:
                    continue
                if k == "slide":
                    row.update(icon="↪", words=[("Push ", ""), (p.get("name") or "my plan", "b"),
                                                (f" back {a['days']} day{'s' if a['days'] != 1 else ''}", "")], verb="Push")
                else:
                    until = (today + datetime.timedelta(days=7)).isoformat()
                    row.update(icon="⏸", words=[("Pause ", ""), (p.get("name") or "my plan", "b"), (f" till {P.fmt_day(until)}", "")],
                               verb="Pause")
            else:
                continue
            row["done"] = self.undo is not None and self.undo.get("row") == i
            out.append(row)
        return out

    def my_plan_followed(self):
        """The plan my push and pause are for: the one You › Plans shows, else the first I follow."""
        fs = self.ops.followed()
        if not fs:
            return None
        pick = cfg().get("plan_pick")
        return next((p for p, _s, _d in fs if p.get("id") == pick), fs[0][0])

    def days_view(self, cids):
        today = self.ops.today()
        key = (self.did, today)
        if key not in self._loads:  # once a deck a window: a click on a day doesn't read the deck again
            self._loads[key] = self.ops.day_loads(self.idx, today) if self.idx is not None else [0] * DAYS
        loads = self._loads[key]
        light = sorted(range(1, DAYS), key=lambda i: (loads[i], i))[:3]
        days = []
        for i in range(DAYS):
            d = today + datetime.timedelta(days=i)
            days.append({"iso": d.isoformat(), "dow": f"{d:%a}", "d": d.day, "mon": f"{d:%b}", "load": loads[i],
                         "light": i in light and loads[i] < max(loads[1:] or [0]), "today": i == 0,
                         "on": d.isoformat() in self.picked})
        split = M.split(cids, self.picked) if self.picked else []
        each = [{"iso": d, "n": len(c)} for d, c in split]
        sh = self.shares(cids, self.picked) if self.picked else []
        held = sum(len(new) for n, new, _r in sh if n > 0)
        moved = sum(len(rev) for n, _n, rev in sh if n > 0)
        kinds = self.kinds(cids) if self.picked else {}
        learn = sum(1 for d, part in split if d > today.isoformat() for c in part if kinds.get(c) == "learn")
        exam = str(self.ops.exam_day() or "")
        eve = (datetime.date.fromisoformat(exam) - datetime.timedelta(days=1)).isoformat() if exam > (today + datetime.timedelta(days=2)).isoformat() else ""
        f = self.fill
        fill = {"on": bool(f), "eve": eve, "eve_label": P.fmt_day(eve) if eve else "",
                "n": (datetime.date.fromisoformat(f["to"]) - datetime.date.fromisoformat(f["from"])).days + 1 if f else 0,
                "to_label": P.fmt_day(f["to"]) if f else "", "skip": list(f.get("skip") or []) if f else [],
                "study": len(each), "per": -(-len(cids) // len(each)) if each else 0, "max": FILL_SPAN}
        note = " ".join(x for x in (
            f"{held:,} {'is' if held == 1 else 'are'} new and open now: held back till {'its' if held == 1 else 'their'} day." if held else "",
            f"{moved:,} review{' is' if moved == 1 else 's are'} due now: {'its due date moves' if moved == 1 else 'their due dates move'} "
            f"to {'its' if moved == 1 else 'their'} day." if moved else "",
            f"{learn:,} {'is' if learn == 1 else 'are'} mid-learning and stay{'s' if learn == 1 else ''} with today." if learn else "") if x)
        return {"list": days, "each": each, "name": self.day_name or self.name(), "note": note, "fill": fill}

    def dests_view(self):
        """Where a date or a quiz goes: My plan, and the plans I write on this deck."""
        mine = self.my_plan_id()
        out = [{"key": "mine", "name": MY_PLAN, "note": "" if mine else "starts it"}]
        for p in self.dests or ():
            if p.get("role") in ("owner", "editor") and p.get("id") != mine and self.idx is not None and \
                    str((p.get("doc") or {}).get("deck") or "").split("::")[0].lower() == self.idx.name.lower():
                from .planner.core import others
                n = others(p)
                out.append({"key": p["id"], "name": p.get("name") or "Plan",
                            "note": f"waits in Review and send · {n:,} following" if n else ""})
        return out

    def my_plan_id(self):
        pid = (plan_flow._pcfg().get("magic_plans") or {}).get(str(self.did))
        if pid and (self.dests is None or any(p.get("id") == pid for p in self.dests)):
            return pid
        return None

    def plantext_view(self):
        from .planner import text as T
        from .planner import build as B
        doc = {"deck": self.idx.name if self.idx else "", "units": []}
        if self.did not in self._btree:  # the builder's tree of the deck, once a deck a window
            self._btree[self.did] = B.Tree(*self.idx.tree())
        try:
            r = T.from_text(doc, self._btree[self.did], self.text, whole=False, start=self.ops.today().isoformat())
        except Exception:
            oops()
            return {"dates": [], "events": [], "errors": ["Those lines couldn't be read."]}
        dates = []
        total = set()
        for u in r["units"]:
            got = self.idx.match(u, None, doc) if self.idx else set()
            total |= got
            dates.append({"day": u.get("opens"), "label": P.fmt_day(u.get("opens")), "name": u.get("name") or "",
                          "n": len(got), "due": P.fmt_day(u["due"]) if u.get("due") else ""})
        evs = [{"day": e["day"], "label": P.fmt_day(e["day"]), "name": e["name"]} for e in r["events"]]
        days = sorted([d["day"] for d in dates] + [e["day"] for e in evs])
        return {"dates": dates, "events": evs, "n": len(total), "errors": r["errors"][:3],
                "span": M.words_span(days[0], days[-1]) if days else "",
                "none": sum(1 for d in dates if not d["n"])}

    # -- the page's clicks --

    def on(self, cmd, a):
        a = a or {}
        fn = getattr(self, "c_" + str(cmd), None)
        if fn is None:
            return
        try:
            fn(**{k: v for k, v in a.items() if k != "cmd"})
        except TypeError:
            oops()  # a click with the wrong arguments: nothing
            return
        except Exception:  # noqa: BLE001 (said in the window, never Anki's error box)
            oops()
            self.busy = False
            self.said = {"text": "That didn't work. Try again."}
        self.push()

    def c_ready(self):
        if self.dests is None and self.ops.signed_in():
            def got(plans):
                self.dests = [p for p in plans or [] if isinstance(p, dict)]
                self.push()
            self.ops.my_plans(got)

    def c_type(self, text=""):
        self.text = str(text)[:20000]
        self.bank_pick = None  # a new paste: the bank its numbers say
        self.cids_in = None if self.text.strip() else self.cids_in
        self.said, self.undo = None, None
        self.reread()

    def c_deck(self, did=None):
        try:
            self.pick_deck(int(did))
        except (TypeError, ValueError):
            return
        self.bank_pick = None
        self.reread()

    def c_chip(self, i=None):
        """An Also: a near name taken in (its topic back in too, if I'd left it out)."""
        i = int(i)
        self.flip ^= {i}
        if 0 <= i < len(self.r["groups"]):
            self.seg_off.discard(self.r["groups"][i]["seg"])
        self._cards = None

    def c_open(self, seg=None):
        """A topic's tree, open or closed."""
        self.open_segs ^= {int(seg)}

    def c_seg(self, seg=None):
        """A typed topic's tick: all of it left out, or back in."""
        self.seg_off ^= {int(seg)}
        self._cards = None

    def c_tag(self, t=""):
        self.tag_off ^= {str(t)}
        self._cards = None

    def c_tags(self, ts=(), on=True):
        """A resource's tick in a chip's list: all its tags in, or all out."""
        ts = {str(x) for x in ts or ()}
        self.tag_off = (self.tag_off - ts) if on else (self.tag_off | ts)
        self._cards = None

    def c_filter(self, k=""):
        if any(f["k"] == k for f in self.filters):
            self.filters = [f for f in self.filters if f["k"] != k]
        elif k in M.ROW:
            self.filters.append({"k": k})
            if k == "due":
                self.filters = [f for f in self.filters if f["k"] not in ("tom", "dN")]
            if k in ("tom", "dN"):
                self.filters = [f for f in self.filters if f["k"] != "due"]
            if k in ("new", "seen"):
                self.filters = [f for f in self.filters if f["k"] != ("seen" if k == "new" else "new")]
        self._cards = None

    def c_study(self, all=False):
        """Study now: the new and due (all of them for a filter or QIDs); all=True, every one but a leech."""
        if all:
            self.how = "all"
            self._found = None
        cids = self.study_ids(self.cards()[0])
        if not cids:
            self.said = {"text": "Nothing here to study now."}
            return
        self.ops.note_recent(self.text)
        qids = self.r["kind"] == "ids" and bool(self.r["qids"])
        if self.ops.study(cids, self.name(), order=plan_flow.STUDY_ORDER if qids else None):  # a block's questions: mixed, as the bank had them
            self.close_win()

    def c_bank(self, name=""):
        """QBank QIDs: which bank, when two have these numbers (kept while it's this paste and this deck)."""
        self.bank_pick = str(name) or None
        self._cards = None

    def c_topic(self, i=None):
        """Their topics' Study: the map's deck of what I missed there."""
        try:
            row = self._topics[int(i)]
        except (TypeError, ValueError, IndexError):
            return
        if row["missed"] and self.ops.study_topic(row["name"], row["missed"]):
            self.close_win()

    def c_keep(self, name=""):
        name = " ".join(str(name or self.name()).replace("::", ": ").split())[:80] or "Cards"
        cids, q = self.cards()
        if not cids or not q:
            return
        if self.how == "nd":
            q = f"({q}) (is:new OR is:due)"
        did = self.ops.keep(name, q, cids, self.r.get("limit"), plan_flow.NEW_ORDER)
        if not did:
            self.said = {"text": f"Couldn't make “{name}”: a deck has that name."}
            return
        self.ops.note_recent(self.text)
        label = f"Due Crew: {name}"
        self.said = {"text": f"“{name}” is in your decks.", "undo": "anki"}
        self.undo = {"kind": "anki", "label": label}

    def c_addto(self, did=None):
        cids = self.study_ids(self.cards()[0])
        if not cids or did is None:
            return
        n = self.ops.add_to(int(did), cids)
        name = self.ops.deck_name(did) or "the deck"
        if n is None:
            self.said = {"text": f"Couldn't add them to {name}."}
            return
        self.ops.note_recent(self.text)
        self.said = {"text": f"Added to {name}: it holds {n:,} card{'s' if n != 1 else ''} now.", "undo": "anki"}
        self.undo = {"kind": "anki", "label": f"Due Crew: add to {name}"}

    def c_uns(self):
        cids = self.cards()[0]
        n = self.ops.unsuspend(cids)
        self.ops.note_recent(self.text)
        self._cards = None
        self.idx = None
        self._idx.pop(self.did, None)
        self.pick_deck(self.did)
        self.said = {"text": f"Unsuspended {n:,} card{'s' if n != 1 else ''}." if n else "None were suspended."}
        if n:
            self.said["undo"] = "anki"
            self.undo = {"kind": "anki", "label": f"Due Crew: unsuspend {n:,} card{'s' if n != 1 else ''}"}

    def c_browse(self):
        cids, _q = self.cards()
        self.ops.browse(cids)

    def c_days(self, show=True):
        """Schedule ahead: the day picker, the days it takes at my pace picked
        from tomorrow when nothing is yet (the days before a quiz are)."""
        self.mode = "days" if show else ""
        f = self.found() if show and not self.picked else None
        if f and f["days"]:
            today = self.ops.today()
            self.picked = [(today + datetime.timedelta(days=k)).isoformat() for k in range(1, min(f["days"], DAYS - 1) + 1)]

    # -- the fill-in: a stretch longer than the picker's two weeks (3.9.9) --

    def fill_days(self):
        f = self.fill or {}
        try:
            a, b = datetime.date.fromisoformat(f["from"]), datetime.date.fromisoformat(f["to"])
        except (KeyError, ValueError):
            return []
        skip, out = set(f.get("skip") or []), []
        while a <= b and len(out) < FILL_MAX:
            if a.weekday() not in skip:
                out.append(a.isoformat())
            a += datetime.timedelta(days=1)
        return out

    def c_fill(self, n=None, to=None, off=False, first=None):
        """Go longer: every day from tomorrow (or `first`) for n days, or to a
        day (my exam's eve), FILL_MAX study days at most; off: back to tapping."""
        today = self.ops.today()
        if off:
            self.fill = None
            self.picked = [d for d in self.picked if d <= (today + datetime.timedelta(days=DAYS - 1)).isoformat()]
            return
        start = first or (today + datetime.timedelta(days=1)).isoformat()
        try:
            end = (datetime.date.fromisoformat(str(to)) if to
                   else datetime.date.fromisoformat(start) + datetime.timedelta(days=max(1, min(FILL_SPAN, int(n))) - 1))
        except (TypeError, ValueError):
            return
        end = min(end, today + datetime.timedelta(days=FILL_SPAN))
        if end.isoformat() < start:
            return
        self.fill = {"from": start, "to": end.isoformat(), "skip": list((self.fill or {}).get("skip") or [])}
        self.picked = self.fill_days()

    def c_fillskip(self, dow=0):
        if not self.fill:
            return
        d = int(dow)
        if 0 <= d <= 6:
            skip = set(self.fill.get("skip") or [])
            skip ^= {d}
            if len(skip) < 7:
                self.fill["skip"] = sorted(skip)
                self.picked = self.fill_days()

    def c_day(self, iso=""):
        self.fill = None  # a tap is my own choice of days again
        if iso in self.picked:
            self.picked = [d for d in self.picked if d != iso]
        else:
            self.picked = sorted(self.picked + [str(iso)])

    def c_dayname(self, name=""):
        self.day_name = " ".join(str(name).split())[:60]

    def c_dest(self, key="mine"):
        self.dest = str(key)

    def c_put(self):
        cids = self.cards()[0]
        if not cids or not self.picked:
            return
        if not self.ops.signed_in():
            self.said = {"text": "Sign in to put cards on a plan."}
            return
        name = self.day_name or self.name()
        ops = self.day_ops(cids, self.picked, name)
        what = f"{name} on {M.words_span(self.picked[0], self.picked[-1])}"
        shares, many = self.shares(cids, self.picked), len(self.picked) > 1

        def landed(how):
            """Once the dates are on the plan (the review of 10 Nov: held before
            the save, a save that failed left them suspended with no date to open
            them): the open cards, which a date alone leaves where they are. Not
            while the dates wait in Review and send: nothing would open them yet."""
            if how != "saved":
                open_n = sum(len(n) + len(r) for d, n, r in shares if d > 0)
                return (f" {open_n:,} of them {'is' if open_n == 1 else 'are'} open already and stay"
                        f"{'s' if open_n == 1 else ''} where Anki has {'it' if open_n == 1 else 'them'} till it's sent."
                        if how == "waiting" and open_n else ""), ""
            held, moved, label = self.ops.spread(shares)
            self._kinds = None
            words = " and ".join(x for x in (
                f"{held:,} new held back till their day" if held else "",
                f"{moved:,} review{'s' if moved != 1 else ''} moved to {'their days' if many else 'that day'}" if moved else "") if x)
            return (f" {words[0].upper()}{words[1:]}." if words else ""), label
        self.write(ops, what, after=landed)
        self.ops.note_recent(self.text)

    def kinds(self, cids):
        key = (len(cids), cids[0] if cids else 0, cids[-1] if cids else 0)
        got = getattr(self, "_kinds", None)
        if not got or got[0] != key:
            try:
                got = self._kinds = (key, self.ops.open_kinds(cids))
            except Exception:
                oops()
                got = self._kinds = (key, {})
        return got[1]

    def shares(self, cids, days):
        """[(days from today, its open new cards, its due reviews)] a picked day."""
        kinds, today, out = self.kinds(cids), self.ops.today(), []
        for day, part in M.split(cids, days):
            n = (datetime.date.fromisoformat(day) - today).days
            out.append((n, [c for c in part if kinds.get(c) == "new"], [c for c in part if kinds.get(c) == "rev"]))
        return out

    def day_ops(self, cids, days, name):
        """A date a day: the ticked tags when it's one day of whole topics,
        else each day's share of the cards, by which cards they are."""
        tags = self.ticked()
        r = self.reading()
        whole = (len(days) == 1 and tags and not self.filters and not r.get("limit") and not r["neg"]
                 and self.cids_in is None and not r.get("plan"))
        if whole:
            return [{"op": "add_date", "day": days[0], "name": name, "tags": tags}]
        out = []
        parts = M.split(cids, days)
        for i, (day, part) in enumerate(parts):
            if not part:
                continue
            nm = M.day_name(name, i, len(parts))
            out.append({"op": "add_date", "day": day, "name": nm})
            out.append({"op": "add_picks", "date": f"{day} {nm}", "cards": self.ops.refs(part)})
        return out

    def c_act(self, i=None):
        i = int(i)
        if i >= len(self.r["acts"]):
            return
        a = self.r["acts"][i]
        k = a["k"]
        if k == "event":
            self.write([{"op": "add_event", "day": a["day"], "name": a["name"]}], f"{a['name']} on {P.fmt_day(a['day'])}", row=i)
        elif k == "before":
            self.picked = self.days_before(a["day"])
            self.mode = "days"
        elif k == "exam":
            old = self.ops.settings(["setexam", a["day"]])
            if old is not None:
                self.said = {"text": f"Your exam: {P.fmt_day(a['day'])}.", "undo": "settings"}
                self.undo = {"kind": "settings", "old": old, "row": i}
        elif k == "away":
            old = self.ops.settings(["setaway", a["from"], a["to"]])
            if old is not None:
                self.said = {"text": f"Away {M.words_span(a['from'], a['to'])}.",
                             "undo": "settings"}
                self.undo = {"kind": "settings", "old": old, "row": i}
        elif k in ("slide", "pause"):
            p = self.my_plan_followed()
            if p is None:
                return
            pid, name = p["id"], p.get("name") or "My plan"
            if k == "slide":
                was = int(p.get("shift") or 0)
                fields = {"shift": min(365, was + int(a["days"]))}
                back = {"shift": was}
                words = f"{name}'s dates are {a['days']} day{'s' if a['days'] != 1 else ''} later."
            else:
                today = self.ops.today()
                fields = {"paused": True, "since": today.isoformat(),
                          "until": (today + datetime.timedelta(days=7)).isoformat()}
                back = {"paused": False, "since": None, "until": None}
                words = f"{name} is paused till {P.fmt_day(fields['until'])}."
            self.busy = True

            def done(got):
                self.busy = False
                if got is None:
                    self.said = {"text": "Couldn't reach Due Crew. Check your connection."}
                else:
                    self.said = {"text": words, "undo": "days"}
                    self.undo = {"kind": "days", "pid": pid, "fields": back, "row": i}
                    app.swap(cfg())
                self.push()
            self.ops.set_days(pid, done, **fields)

    def c_plantext(self):
        if not self.ops.signed_in():
            self.said = {"text": "Sign in to put dates on a plan."}
            return
        pt = self.plantext_view()
        if pt.get("errors"):
            self.said = {"text": pt["errors"][0]}
            return
        n = len(pt["dates"])
        self.write([{"op": "text", "mode": "add", "text": self.text}],
                   f"{n:,} date{'s' if n != 1 else ''}" + (f" and {len(pt['events']):,} event{'s' if len(pt['events']) != 1 else ''}" if pt["events"] else ""))

    def write(self, ops, what, row=None, after=None):
        """The ops onto the plan picked (My plan unless another), said when it lands."""
        key = self.dest if any(d["key"] == self.dest for d in self.dests_view()) else "mine"
        pid = self.my_plan_id() if key == "mine" else key
        plan_name = MY_PLAN if key == "mine" else next((d["name"] for d in self.dests_view() if d["key"] == key), "the plan")
        self.busy = True
        self.said = {"text": "Saving…"}

        def done(got):
            how, got_pid, version, more = got
            self.busy = False
            extra, also = after(how) if after else ("", "")
            if how == "failed":
                self.said = {"text": more or "Couldn't save it."}
            elif how == "waiting":
                self.said = {"text": f"Waiting in {plan_name}'s Review and send.{extra}",
                             "undo": "draft", "open": got_pid}
                self.undo = {"kind": "draft", "pid": got_pid, "n": int(more or len(ops)), "row": row, "anki": also}
            else:
                if more == "made":  # My plan, just made: the next Put goes onto it, never a second one
                    self.dests = [p for p in self.dests or [] if p.get("id") != got_pid] + [
                        {"id": got_pid, "name": MY_PLAN, "role": "owner", "followers": 1, "following": True,
                         "doc": {"deck": self.idx.name if self.idx else ""}}]
                self.said = {"text": f"{'Made' if more == 'made' else 'On'} {plan_name}: {what}.{extra}", "undo": "save", "open": got_pid}
                self.undo = {"kind": "save", "pid": got_pid, "version": version, "row": row, "anki": also}
                self.picked = [] if row is None else self.picked
                self.mode = "" if row is None else self.mode
            self.push()
        self.ops.write_plan(pid, ops, self.idx, done, name=MY_PLAN, deck=self.idx.name if self.idx else None)

    def c_undo(self):
        u, self.undo = self.undo, None
        if not u:
            return
        k = u["kind"]
        if u.get("anki") and k in ("save", "draft"):  # Schedule ahead's own step in Anki goes back with its dates
            self.ops.undo_anki(u["anki"])
            self._kinds = None
        if k == "anki":
            ok = self.ops.undo_anki(u["label"])
            self.said = {"text": "Undone." if ok else "Undo it with Edit › Undo."}
            self._idx.pop(self.did, None)
            self.pick_deck(self.did)
            self._cards = None
        elif k == "settings":
            self.ops.put_back(u["old"])
            self.said = {"text": "Undone."}
        elif k == "draft":
            self.ops.undo_draft(u["pid"], u["n"])
            self.said = {"text": "Taken back."}
        elif k == "save":
            self.busy = True

            def done(ok):
                self.busy = False
                self.said = {"text": "Undone." if ok else "Couldn't undo it: open the plan to change it."}
                self.push()
            self.ops.undo_save(u["pid"], u["version"], done)
        elif k == "days":
            self.busy = True

            def back(got):
                self.busy = False
                self.said = {"text": "Undone." if got is not None else "Couldn't reach Due Crew. Check your connection."}
                app.swap(cfg())
                self.push()
            self.ops.set_days(u["pid"], back, **u["fields"])

    def c_open_plan(self, pid=""):
        if pid:
            self.ops.open_plans(str(pid))

    def c_intro(self, show=True):
        self.intro = bool(show)
        if not show:
            self.ops.saw_intro()

    def c_try(self, text=""):
        self.intro = False
        self.ops.saw_intro()
        self.c_type(text)

    def c_close(self):
        self.close_win()


_TREES = {}  # deck id -> (its tags as the index read them, Tree): a deck's tags change only when its notes do


def tree_of(idx):
    """The deck's tag tree, made again only when the deck's tags were read
    again (DeckIndex keeps them while its notes are unchanged): on a big
    shared deck, two seconds once, then nothing."""
    kept = _TREES.get(idx.did)
    if kept is not None and kept[0] is idx.tag_names:
        return kept[1]
    tree = M.Tree(list(idx.tag_names.values()), idx.tag_cards)
    _TREES.clear()  # one deck's tree at a time: it's the size of its tags
    _TREES[idx.did] = (idx.tag_names, tree)
    return tree


def _ticks(r, k, tree=None):
    """A how-to try reads as something here: a topic it ticks (a resource's,
    for the resource part); for the QIDs part, the deck's questions."""
    if k == "ids":
        return r["kind"] == "ids" and bool(set(r["qids"]) & (tree.qnums if tree is not None else set()))
    return any(g["on"] for g in r["groups"]) and (k != "res" or bool(r.get("res")))


def dumps(v):
    return json.dumps(v, ensure_ascii=True).replace("<", "\\u003c")

