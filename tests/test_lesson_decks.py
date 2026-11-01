"""Today's lesson, A or B (the plans redesign): per plan, chosen when it
starts on this computer. A, the default: the morning opens a lesson's cards
in the plan's deck, as ever. B: the same opening, then each open lesson with
cards to learn is a filtered deck of its own, Due Crew::<plan>::<NN> <lesson>,
in Anki's deck list: its new cards and the learning ones due now, never a
review (Sam's FSRS rule); one undo step with the open, so the board's Not
today takes the decks too; tidied once empty. plans.json only, never sent.

Against a fake collection with Anki's filtered decks and undo (below; the
real engine is tools/real_anki.py). Standard library only.

Run: python3 tests/test_lesson_decks.py
"""

import copy
import datetime
import os
import re
import sqlite3
import sys
import tempfile
import time
import types

HARNESS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HARNESS)
sys.path.insert(0, HARNESS)

import fakes  # noqa: E402

STORE = fakes.FakeWorker()
fakes.install_fake_requests(STORE)
fakes.install_fake_aqt()
sys.path.insert(0, REPO)

from due_crew import board                                     # noqa: E402
from due_crew import plan_flow as F                            # noqa: E402
from due_crew import plans as P                                # noqa: E402
from due_crew.app import _state                                # noqa: E402
from due_crew.backend import api                               # noqa: E402

CHECKS = []
TODAY = datetime.date.today()


def check(name, cond, detail=""):
    CHECKS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond or detail == "" else f"\n     {detail}"))


def day(n):
    return (TODAY + datetime.timedelta(days=n)).isoformat()


# ---- a collection with Anki's filtered decks and undo ----

class Sched(fakes.FakeSched):
    """FakeSched's ops as undo steps of the collection's, and Anki's filtered
    decks: built over a cid: search (suspended, buried and cards in another
    filtered deck left out; none left, Anki's error and nothing changes),
    rebuilt (emptied first), emptied (cards home, their due back)."""

    def unsuspend_cards(self, ids):
        self.col.op("Unsuspend")
        return super().unsuspend_cards(ids)

    def suspend_cards(self, ids):
        self.col.op("Suspend")
        return super().suspend_cards(ids)

    def reposition_new_cards(self, card_ids, **kw):
        self.col.op("Reposition")
        return super().reposition_new_cards(card_ids, **kw)

    def get_or_create_filtered_deck(self, deck_id=0):
        d = self.col.decks.d.get(int(deck_id)) if deck_id else None
        if d and d["dyn"]:
            return types.SimpleNamespace(id=int(deck_id), name=d["name"], config=types.SimpleNamespace(
                search_terms=[types.SimpleNamespace(**t) for t in d["terms"]], reschedule=d["resched"]))
        return types.SimpleNamespace(id=0, name="Filtered Deck 1", config=types.SimpleNamespace(
            search_terms=[types.SimpleNamespace(search="", limit=100, order=0),
                          types.SimpleNamespace(search="is:new", limit=20, order=5)], reschedule=True))

    def home(self, did):
        self.col.db.conn.execute("UPDATE cards SET did = odid, odid = 0, due = CASE WHEN odue != 0 THEN odue ELSE due END, "
                                 "odue = 0 WHERE did = ? AND odid != 0", (int(did),))

    def add_or_update_filtered_deck(self, deck):
        col = self.col
        col.op("Build Deck")
        before = col.steps[-1][2]
        try:
            did = col.decks.put_filtered(deck)
            self.home(did)
            term = deck.config.search_terms[0]
            ids = [int(x) for x in re.findall(r"\d+", term.search)]
            take = col.db.list(f"SELECT id FROM cards WHERE id IN ({','.join(map(str, ids)) or '0'}) "
                               "AND queue >= 0 AND odid = 0 ORDER BY due, id")[:int(term.limit)]
            if not take:
                raise RuntimeError("No cards matched the provided search.")
            for i, c in enumerate(take):
                col.db.conn.execute("UPDATE cards SET odid = did, did = ?, odue = due, due = ? WHERE id = ?", (did, -100000 + i, c))
        except Exception:
            col.restore(before)
            col.steps.pop()
            raise
        return types.SimpleNamespace(id=did)

    def empty_filtered_deck(self, did):
        self.col.op("Empty")
        self.home(did)


class Decks:
    """{did: {name, dyn, terms, resched}}; parents made as Anki makes them;
    a filtered deck can't have a child; removing a filtered deck sends its
    cards home, removing a normal one would delete its cards (counted)."""

    def __init__(self, col, names):
        self.col = col
        self.d = {int(k): {"name": v, "dyn": 0} for k, v in names.items()}
        self.cur = None
        self.lost = 0

    def get(self, did, default=True):
        d = self.d.get(int(did))
        return dict(d, id=int(did)) if d else None

    def name(self, did):
        return (self.d.get(int(did)) or {}).get("name", "")

    def id_for_name(self, name):
        return next((k for k, v in self.d.items() if v["name"] == name), None)

    def deck_and_child_ids(self, did):
        top = self.d[int(did)]["name"]
        return [int(did)] + [k for k, v in self.d.items() if v["name"].startswith(top + "::")]

    def all_names_and_ids(self, skip_empty_default=False, include_filtered=True):
        return [types.SimpleNamespace(id=k, name=v["name"]) for k, v in sorted(self.d.items(), key=lambda kv: kv[1]["name"])
                if include_filtered or not v["dyn"]]

    def _new(self, name, dyn):
        while self.id_for_name(name) is not None:
            name += "+"
        did = max(self.d) + 1
        self.d[did] = {"name": name, "dyn": dyn}
        return did

    def put_filtered(self, deck):
        parts = deck.name.split("::")
        for i in range(1, len(parts)):
            up = "::".join(parts[:i])
            have = self.id_for_name(up)
            if have is not None and self.d[have]["dyn"]:
                raise RuntimeError("Filtered decks can not have child decks.")
            if have is None:
                self._new(up, 0)
        if deck.id:
            did = int(deck.id)
            if self.d[did]["name"] != deck.name:
                self.d[did]["name"] = deck.name
        else:
            did = self._new(deck.name, 1)
        self.d[did].update(dyn=1, terms=[dict(vars(t)) for t in deck.config.search_terms], resched=deck.config.reschedule)
        return did

    def remove(self, ids):
        self.col.op("Delete Deck")
        for did in list(ids):
            if int(did) not in self.d:
                continue
            for k in self.deck_and_child_ids(did):
                if self.d[k]["dyn"]:
                    self.col.sched.home(k)
                else:
                    self.lost += self.col.db.scalar("SELECT count() FROM cards WHERE did = ? OR odid = ?", k, k) or 0
                    self.col.db.conn.execute("DELETE FROM cards WHERE did = ?", (k,))
                self.d.pop(k, None)

    def rename(self, did, name):
        self.col.op("Rename Deck")
        self.d[int(did)]["name"] = name

    def select(self, did):
        self.cur = int(did)

    def selected(self):
        return self.cur


class Col(fakes.FakeCol):
    """Anki's undo, as Due Crew uses it: each step remembers the collection as
    it was before it; a custom step's merge folds every later one into it
    (its name stays); undo puts the collection back as the step found it."""

    def __init__(self, conn, names):
        super().__init__(conn, fakes.day_cutoff_for(TODAY))
        self.sched = Sched(fakes.day_cutoff_for(TODAY), self.db)
        self.sched.col = self
        self.decks = Decks(self, names)
        self.steps, self.n = [], 0

    def snap(self):
        return (self.db.conn.execute("SELECT id, did, odid, type, queue, due, odue FROM cards").fetchall(),
                copy.deepcopy(self.decks.d))

    def restore(self, snap):
        rows, d = snap
        for r in rows:
            self.db.conn.execute("UPDATE cards SET did=?, odid=?, type=?, queue=?, due=?, odue=? WHERE id=?", (*r[1:], r[0]))
        self.decks.d = d

    def op(self, name):
        self.n += 1
        self.steps.append([self.n, name, self.snap()])
        return self.n

    def add_custom_undo_entry(self, name):
        return self.op(name)

    def merge_undo_entries(self, pos):
        at = next(i for i, s in enumerate(self.steps) if s[0] == pos)
        del self.steps[at + 1:]
        return types.SimpleNamespace(card=True)

    def undo_status(self):
        return types.SimpleNamespace(undo=self.steps[-1][1] if self.steps else "",
                                     last_step=self.steps[-1][0] if self.steps else 0)

    def undo(self):
        _n, _name, snap = self.steps.pop()
        self.restore(snap)


BIG, CRAM = 10, 50  # Big Step 1; My cram, another add-on's filtered deck
NOW = int(time.time())


def make_col():
    """Big Step 1 (10). Cell injury: 1-3 new, shut; 4 a review not due.
    Inflammation: 5, 6 new, shut; 7 learning, back in ten minutes; 8
    learning, back tomorrow; 9 new, in My cram (another add-on's deck).
    Neoplasia: 11, 12 new, shut. Healing: 13, new, shut."""
    conn = sqlite3.connect(":memory:")
    fakes.make_collection(conn)
    add = fakes.add_card
    for cid in (1, 2, 3):
        add(conn, cid, did=BIG, queue=-1, tags="Path::Cell_injury", due=cid)
    add(conn, 4, did=BIG, ctype=2, queue=2, ivl=9, tags="Path::Cell_injury", due=1000 + 5)
    add(conn, 5, did=BIG, queue=-1, tags="Path::Inflammation", due=5)
    add(conn, 6, did=BIG, queue=-1, tags="Path::Inflammation", due=6)
    add(conn, 7, did=BIG, ctype=1, queue=1, tags="Path::Inflammation", due=NOW + 600)
    add(conn, 8, did=BIG, ctype=1, queue=3, tags="Path::Inflammation", due=1001)
    add(conn, 9, did=CRAM, odid=BIG, tags="Path::Inflammation", due=-100000)
    conn.execute("UPDATE cards SET odue = 9 WHERE id = 9")
    for cid in (11, 12):
        add(conn, cid, did=BIG, queue=-1, tags="Path::Neoplasia", due=cid)
    add(conn, 13, did=BIG, queue=-1, tags="Path::Healing", due=13)
    col = Col(conn, {BIG: "Big Step 1"})
    col.decks.d[CRAM] = {"name": "My cram", "dyn": 1, "terms": [], "resched": True}
    return col


UNITS = [
    {"id": "l1", "name": "Cell injury", "opens": day(-2), "due": day(-1), "tags": ["Path::Cell_injury"]},
    {"id": "l2", "name": "Inflammation", "opens": day(0), "due": day(1), "tags": ["Path::Inflammation"]},
    {"id": "l3", "name": "Neoplasia", "opens": day(3), "due": day(4), "tags": ["Path::Neoplasia"]},
    {"id": "l4", "name": "Healing", "opens": day(5), "tags": ["Path::Healing"]},
]


class World:
    """plan_flow pointed at a fake world: a signed-in follower with the Worker
    fake, this profile's plans.json in a folder of its own, a collection."""

    def __init__(self, units=None, name="Path Book"):
        self.store = fakes.FakeWorker()
        sys.modules["requests"].Session = lambda: fakes.FakeSession(self.store)
        for uid, nm in (("dre", "Dre"), ("maya", "Maya")):
            self.store.add_user(uid, nm)
        self.pid, self.code = self.store.add_plan("dre", name, "Big Step 1", copy.deepcopy(units or UNITS))
        self.cl = api.ApiClient(os.path.join(tempfile.mkdtemp(), "session.json"))
        self.cl.session = {"user_id": "maya", "token": self.store.session_for("maya"),
                           "email": "maya@example.com", "display_name": "Maya"}
        self.col = make_col()
        self.dir = tempfile.mkdtemp()
        self.today = {"d": day(0)}
        self.toasts = []

    def __enter__(self):
        names = ("cfg", "save_cfg", "_files", "client", "_today", "tooltip", "_bg")
        self.saved = {k: getattr(F, k) for k in names}
        self.saved_mw = (F.mw.col, F.app.swap, getattr(F.mw, "moveToState", None), getattr(F.mw, "undo", None))
        self.glob = {}
        F.cfg = lambda: self.glob
        F.save_cfg = lambda c: None
        F._files = lambda: self.dir
        F.client = lambda: self.cl
        F._today = lambda: self.today["d"]
        F.tooltip = lambda text, **kw: self.toasts.append(text)
        F._bg = lambda job, done=None: done(job()) if done else job()
        F.app.swap = lambda c: None
        F.mw.col = self.col
        self.moved = []
        F.mw.moveToState = self.moved.append
        F.mw.undo = self.col.undo
        F._store.update(profile=None, data=None)
        return self

    def __exit__(self, *exc):
        for k, v in self.saved.items():
            setattr(F, k, v)
        F.mw.col, F.app.swap = self.saved_mw[:2]
        for k, v in (("moveToState", self.saved_mw[2]), ("undo", self.saved_mw[3])):
            if v is None:
                F.mw.__dict__.pop(k, None)
            else:
                setattr(F.mw, k, v)
        F._store.update(profile=None, data=None)
        _state["labels"], _state["plan_progress"] = [], {}
        return False

    def follow(self, lesson=None):
        plan, _ = self.cl.follow_plan(self.code)
        F.on_followed(plan, BIG, None, "open", lesson=lesson)
        return plan

    def st(self):
        return F._state_cfg().get(self.pid) or {}

    def deck(self, name):
        return self.col.decks.id_for_name(name)

    def cards_in(self, name):
        did = self.deck(name)
        return sorted(self.col.db.list("SELECT id FROM cards WHERE did = ?", did)) if did else None

    def queue(self, cid):
        return self.col.db.scalar("SELECT queue FROM cards WHERE id = ?", cid)

    def filtered(self):
        return sorted(v["name"] for v in self.col.decks.d.values() if v["dyn"] and v["name"] != "My cram")


L1, L2, L3 = "Due Crew::Path Book::01 Cell injury", "Due Crew::Path Book::02 Inflammation", "Due Crew::Path Book::03 Neoplasia"


# ---- pure ----

def test_pure():
    doc = {"units": [{"id": "b", "opens": "2026-11-03"}, {"id": "a", "opens": "2026-11-02"},
                     {"id": "c", "opens": "2026-11-03"}, {"id": "x"}]}
    check("places: by opening day, the plan's order for a day with two, a date without a day last",
          P.lesson_places(doc) == {"a": 1, "b": 2, "c": 3, "x": 4}, P.lesson_places(doc))
    check("names: Due Crew::<plan>::<NN> <lesson>, two digits so Anki lists them in order",
          P.lesson_deck("Path Book", 3, 19, "Neoplasia") == "Due Crew::Path Book::03 Neoplasia")
    check("names: \"::\" in a name can't make another level, and spaces fold",
          P.lesson_deck("MS2::Block  2", 1, 9, "Heme::Onc  1") == "Due Crew::MS2: Block 2::01 Heme: Onc 1")
    check("names: three digits from a 100th lesson on; an unnamed one is a Lesson",
          P.lesson_deck("P", 7, 120, "") == "Due Crew::P::007 Lesson" and P.lesson_folder("") == "Due Crew::Plan")
    idx = types.SimpleNamespace(cards={1: (0, 0), 2: (-1, 0), 3: (2, 2), 4: (1, 1), 5: (3, 1), 6: (3, 3), 7: (-2, 0), 8: (0, 0)},
                                due_now={4, 6, 3}, order={1: (True, 9, 1), 8: (True, 2, 8), 4: (False, 0, 4)})
    check("cards: open new ones and learning ones due now, learning first then new by place; never a review, "
          "a shut or buried card, a learning one due later, or relearning",
          P.lesson_cards(idx, {1, 2, 3, 4, 5, 6, 7, 8, 99}) == [4, 8, 1], P.lesson_cards(idx, {1, 2, 3, 4, 5, 6, 7, 8, 99}))
    check("plan: none yet and cards to take, build; it lacks some, build again; it has them all, or nothing to "
          "take, leave it (the tidy takes an empty one)",
          P.lesson_plan([1, 2], None, ()) == "build" and P.lesson_plan([1, 2], {1}, ()) == "rebuild"
          and P.lesson_plan([1, 2], {1, 2, 3}, ()) is None and P.lesson_plan([], {1}, ()) is None
          and P.lesson_plan([1], None, {1}) is None and P.lesson_plan([1, 2], {1}, {2}) is None)
    rows = [(1, "Due Crew::Path Book::01 Cell injury", 0), (2, "Due Crew::Path Book::02 Inflammation", 4)]
    check("tidy: a plan's folder goes with its last lesson deck, if Due Crew made it, and empty",
          P.tidy(rows, [7], folders=[(7, [1, 2], 0)]) == [1]
          and P.tidy(rows[:1], [7, 8], (8, [7, 1], 0), [(7, [1], 0)]) == [1, 7, 8]
          and P.tidy(rows[:1], [], folders=[(7, [1], 0)]) == [1]
          and P.tidy(rows[:1], [7], folders=[(7, [1], 3)]) == [1])


# ---- A, the default ----

def test_default_is_a():
    with World() as w:
        w.follow()
        check("A: the default; nothing new in plans.json but what was there", F.lesson_deck_on(w.pid) is False
              and not {"lesson_deck", "lesson_decks", "lesson_held"} & set(w.st()), sorted(w.st()))
        check("A: the lessons open in the plan's deck, as ever; no deck of Due Crew's",
              all(w.queue(c) == 0 for c in (1, 2, 3, 5, 6)) and w.filtered() == [], w.filtered())
        check("A: one undo step, the open's", [s[1] for s in w.col.steps] == ["Due Crew: open 2 dates"], w.col.steps)
        card = F.card_view(F.followed()[0], w.st(), {}, day(0))
        check("A: the card has no lesson deck", card.get("lesson_deck") is None)


# ---- B ----

def test_follow_b():
    with World() as w:
        sent = len(w.store.log)
        w.follow(lesson=True)
        check("B at Follow: kept for this plan here", F.lesson_deck_on(w.pid) is True and w.st().get("lesson_deck") is True)
        check("B: each open lesson a deck of its own, named and numbered by the plan's order",
              w.filtered() == [L1, L2], w.filtered())
        check("B: its open new cards and the learning one due now; the review stays home (FSRS's dates), the learning "
              "one due tomorrow too, and another add-on's deck keeps its card",
              w.cards_in(L1) == [1, 2, 3] and w.cards_in(L2) == [5, 6, 7] and w.col.db.scalar("SELECT did FROM cards WHERE id = 4") == BIG
              and w.col.db.scalar("SELECT did FROM cards WHERE id = 8") == BIG and w.col.db.scalar("SELECT did FROM cards WHERE id = 9") == CRAM,
              (w.cards_in(L1), w.cards_in(L2)))
        d1 = w.col.decks.d[w.deck(L1)]
        check("B: Anki's filtered deck, as they come in the deck (Due Crew's new order), rescheduling, no small limit",
              d1["dyn"] and len(d1["terms"]) == 1 and d1["terms"][0]["order"] == F.NEW_ORDER and d1["resched"]
              and d1["terms"][0]["limit"] >= 3, d1)
        check("B: the open and its decks are one undo step, the open's",
              [s[1] for s in w.col.steps] == ["Due Crew: open 2 dates"], [s[1] for s in w.col.steps])
        st = w.st()
        check("B: what it knows here: the decks, the folder, what another add-on's deck holds",
              st.get("lesson_decks") == {"l1": w.deck(L1), "l2": w.deck(L2)} and st.get("lesson_folder") == "Due Crew::Path Book"
              and st.get("lesson_held") == {"l2": 1}, st)
        built = F._pcfg().get("built") or []
        check("B: the folder and Due Crew's parent remembered as made here, so the tidy may take them",
              w.deck("Due Crew::Path Book") in built and w.deck("Due Crew") in built and w.deck(L1) in built, built)
        check("B: nothing sent for it", not any("lesson" in str(x).lower() for x in w.store.log[sent:]), w.store.log[sent:])
        card = F.card_view(F.followed()[0], st, {}, day(0))
        check("B: the card's view: today's lesson, and the card another add-on's deck holds",
              card["lesson_deck"] == {"today": "l2", "held": 1}, card["lesson_deck"])
        op = F.morning_opened()
        check("B: the opened line knows they're in decks", op and op.get("decks") is True, op)
        w.col.undo()
        check("B: one Edit › Undo takes the open and every deck it made, the folder and parent too",
              all(w.queue(c) == -1 for c in (1, 2, 3, 5, 6)) and w.filtered() == [] and not w.deck("Due Crew"), w.col.decks.d)


def test_switch():
    with World() as w:
        w.follow()
        before = len(w.col.steps)
        sent = len(w.store.log)
        F.set_lesson_deck(w.pid, True)
        check("switch to B: the open lessons' decks now, one undo step of their own",
              w.filtered() == [L1, L2] and [s[1] for s in w.col.steps[before:]] == [F.LESSON_STEP], [s[1] for s in w.col.steps])
        F.set_lesson_deck(w.pid, True)
        check("switch to B again: nothing to do, no undo step", len(w.col.steps) == before + 1)
        F.set_lesson_deck(w.pid, False)
        check("switch to A: the decks emptied and gone, the folder too; the cards home as they were, one undo step",
              w.filtered() == [] and not w.deck("Due Crew::Path Book") and w.col.decks.lost == 0
              and all(w.col.db.scalar("SELECT did FROM cards WHERE id = ?", c) == BIG for c in (1, 2, 3, 5, 6, 7))
              and [w.queue(c) for c in (1, 2, 3, 5, 6, 7)] == [0, 0, 0, 0, 0, 1]
              and w.col.db.list("SELECT due FROM cards WHERE id IN (1, 2, 3) ORDER BY id") == [1, 2, 3]
              and w.col.steps[-1][1] == F.LESSON_OFF and F.lesson_deck_on(w.pid) is False
              and not w.st().get("lesson_decks"), (w.filtered(), w.col.steps[-1][1], w.st()))
        w.col.undo()
        check("switch to A: Edit › Undo brings the decks back", w.filtered() == [L1, L2])
        check("switch: nothing sent", w.store.log[sent:] == [], w.store.log[sent:])
        F.set_lesson_deck("not-here-yet", True)
        check("a plan not here yet keeps B for when it starts", F.lesson_deck_on("not-here-yet") is True
              and F._pcfg().get("lesson_next") == {"not-here-yet": True})


def test_chosen_before():
    with World() as w:
        F.set_lesson_deck(w.pid, True)  # Start it, before the follow's state is here
        w.follow()
        check("B chosen before the plan ran here: the follow takes it, and builds",
              F.lesson_deck_on(w.pid) is True and w.filtered() == [L1, L2] and not F._pcfg().get("lesson_next"), w.filtered())
    with World() as w:
        w.follow(lesson=True)
        w.follow(lesson=False)
        check("Follow again with A: its decks go", w.filtered() == [] and F.lesson_deck_on(w.pid) is False, w.filtered())


def test_morning_and_not_today():
    with World() as w:
        w.follow(lesson=True)
        F._pcfg()["plans_day"] = day(0)
        w.today["d"] = day(3)
        w.cl.fetch_board([day(3)], with_decks=True)
        F.maybe_morning(False)
        op = F._pcfg().get("plans_opened") or {}
        check("morning: Neoplasia opens, and its deck with it", w.filtered() == [L1, L2, L3] and w.cards_in(L3) == [11, 12], w.filtered())
        check("morning: the open and its deck one undo step, still Anki's latest (Not today undoes both)",
              op.get("label") == "Due Crew: open Neoplasia" and w.col.undo_status().undo == op["label"]
              and F.morning_opened().get("decks") is True, (op, [s[1] for s in w.col.steps]))
        html = board._opened_line(F.opened_view())
        check("morning: its line says they're in your decks", "Neoplasia</a> 2, in your decks" in html and "plannottoday" in html, html)
        F.undo_morning(put_off_too=True)
        check("Not today: the cards shut again and the deck gone; the decks from before stay as they were",
              w.queue(11) == -1 and w.filtered() == [L1, L2] and w.cards_in(L1) == [1, 2, 3]
              and "l3" not in (w.st().get("lesson_decks") or {}) and (w.st().get("later") or {}).get("l3") == day(4),
              (w.filtered(), w.st().get("lesson_decks")))
        w.today["d"] = day(4)
        F.maybe_morning(False)
        check("the next morning: it opens, with its deck", w.cards_in(L3) == [11, 12], w.filtered())


def test_open_paths():
    with World() as w:
        w.follow(lesson=True)
        F.open_date(w.pid, "l3")
        check("Open now: the lesson's deck, in the open's undo step",
              w.cards_in(L3) == [11, 12] and w.col.steps[-1][1] == "Due Crew: open Neoplasia", w.col.steps[-1][1])
        w.col.undo()
        check("…one Edit › Undo takes both", w.queue(11) == -1 and w.deck(L3) is None)
        # an author's update adds a tag to a lesson that opened: what it adds opens, and the deck takes it
        F.open_date(w.pid, "l3")
        sess = [p for p in w.cl.session["plans"] if p["id"] == w.pid][0]
        doc = copy.deepcopy(sess["doc"])
        doc["units"][0]["tags"] = ["Path::Cell_injury", "Path::Healing"]
        sess["doc"] = doc
        F.update_open(w.pid)
        check("an update that adds cards to an open lesson: they open, and its deck holds them too, same deck",
              w.queue(13) == 0 and w.cards_in(L1) == [1, 2, 3, 13] and w.st()["lesson_decks"]["l1"] == w.deck(L1), w.cards_in(L1))
        # renamed: the plan's decks follow its name, the same decks
        ids = dict(w.st()["lesson_decks"])
        sess["name"] = "Path Book 2"
        F.lesson_sync(F.followed())
        names = sorted(w.col.decks.d[d]["name"] for d in w.st()["lesson_decks"].values())
        check("a plan renamed: its decks renamed, the same decks", w.st()["lesson_decks"] == ids
              and names == ["Due Crew::Path Book 2::01 Cell injury", "Due Crew::Path Book 2::02 Inflammation",
                            "Due Crew::Path Book 2::03 Neoplasia"], names)
        n = F.tidy_decks(w.col)
        check("…and the old folder, empty, goes with the tidy", n == 1 and not w.deck("Due Crew::Path Book"), n)


def test_learning_and_behind():
    with World() as w:
        w.follow(lesson=True)
        w.col.db.conn.execute("UPDATE cards SET queue = 1, due = ? WHERE id = 8", (NOW + 60,))  # its day came
        F.lesson_sync(F.followed())
        check("a learning card come due: the lesson's deck is built again with it",
              w.cards_in(L2) == [5, 6, 7, 8], w.cards_in(L2))
        steps = len(w.col.steps)
        F.lesson_sync(F.followed())
        check("a deck that has all its cards is left as it is, no undo step", len(w.col.steps) == steps)
        w.col.db.conn.execute("UPDATE cards SET did = odid, odid = 0, type = 2, queue = 2, due = 1010 WHERE id IN (1, 2, 3)")
        n = F.tidy_decks(w.col)
        check("a lesson behind keeps its deck till it's empty; studied through, the tidy takes it, the folder stays",
              n == 1 and w.filtered() == [L2] and w.deck("Due Crew::Path Book"), w.filtered())
        F.lesson_sync(F.followed())
        check("…and it isn't made again: nothing left to learn", w.filtered() == [L2])
        w.col.db.conn.execute("UPDATE cards SET did = odid, odid = 0, type = 2, queue = 2, due = 1010 WHERE did = ?", (w.deck(L2),))
        n = F.tidy_decks(w.col)
        check("the last one studied: it goes, with the folder and Due Crew's parent", n == 3 and w.filtered() == []
              and not w.deck("Due Crew::Path Book") and not w.deck("Due Crew") and w.col.decks.lost == 0, (n, w.col.decks.d))


def test_study():
    with World() as w:
        w.follow(lesson=True)
        F.study_date(w.pid, "l2")
        check("Study on B: the lesson's own deck, Anki's Study screen on it; no other deck made",
              w.col.decks.cur == w.deck(L2) and w.moved == ["overview"] and w.filtered() == [L1, L2], (w.col.decks.cur, w.moved))
        # a topic's Study takes its cards out of the lesson's deck (Anki keeps a card in one); the lesson keeps the rest
        F.study_topic(w.pid, ["l2"], 0)
        check("a topic's Study with lesson decks: its cards come out of the lesson's deck, which keeps what's left",
              w.cards_in("Due Crew::Inflammation") == [5, 6, 7] and w.cards_in(L2) is not None, w.filtered())
        F.set_lesson_deck(w.pid, False)
        F.study_date(w.pid, "l1")
        check("Study on A: a deck of the date's own, as before", w.cards_in("Due Crew::Cell injury") == [1, 2, 3], w.filtered())
        F.set_lesson_deck(w.pid, True)
        check("B again: a card another Due Crew deck holds stays there", w.cards_in(L1) is None, w.filtered())
        F.study_date(w.pid, "l1")
        check("…and Study on it goes to that one's deck as before",
              w.col.decks.cur == w.deck("Due Crew::Cell injury"), w.col.decks.cur)


def test_not_followed():
    with World() as w:
        w.follow(lesson=True)
        F._stop(w.pid, False)
        check("Stop following: its decks go, the cards home", w.filtered() == [] and w.col.decks.lost == 0
              and all(w.col.db.scalar("SELECT did FROM cards WHERE id = ?", c) == BIG for c in (1, 2, 3, 5, 6, 7)), w.filtered())
    with World() as w:
        w.follow(lesson=True)
        w.store.follows.pop((w.pid, "maya"), None)  # stopped on the site
        w.cl.fetch_board([day(1)], with_decks=True)
        w.today["d"] = day(1)
        F.maybe_morning(False, fresh=True)
        check("a plan no longer followed (the site, the author): its decks go at the day's first refresh",
              w.pid not in F._state_cfg() and w.filtered() == [], (list(F._state_cfg()), w.filtered()))


def test_own_pace():
    with World() as w:
        plan, _ = w.cl.follow_plan(w.code, own="ready")
        F.on_followed(plan, BIG, None, "open", lesson=True)
        check("own pace: nothing opens by itself, no deck", w.filtered() == [], w.filtered())
        F.open_next(w.pid)
        check("own pace, Open: the lesson's deck in Open's undo step (its Undo takes both)",
              w.filtered() == [L1] and w.col.steps[-1][1] == "Due Crew: open Cell injury", w.filtered())
        F._state["plan_progress"] = F.progress(w.col, F.followed(), F._state_cfg())
        F.put_back_own(w.pid)
        check("own pace, Put back: its cards shut, its deck gone, in Put back's one step; the cards home, shut",
              w.filtered() == [] and all(w.queue(c) == -1 and w.col.db.scalar("SELECT did FROM cards WHERE id = ?", c) == BIG
                                         for c in (1, 2, 3)) and w.col.steps[-1][1] == "Due Crew: put back Cell injury",
              (w.filtered(), [s[1] for s in w.col.steps[-2:]]))
        F.own_undo(w.pid)
        check("…its Undo puts the deck back as it was", w.cards_in(L1) == [1, 2, 3], w.filtered())
        F.open_next(w.pid, study=True)
        check("own pace, Open and study on B: into the lesson's own deck", w.moved[-1] == "overview"
              and w.col.decks.cur == w.deck(L2) and "Due Crew::Inflammation" not in w.filtered(), (w.moved, w.filtered()))


def test_deck_read_cached():
    """A card going into a filtered deck, or home again, isn't a change to the
    deck's read (its tags, notes, home decks): studying a lesson's deck
    doesn't read 35,000 notes again at the next refresh."""
    col = make_col()
    reads, real = [], P.DeckIndex._read_static
    P.DeckIndex._read_static = lambda self, *a: reads.append(1) or real(self, *a)
    try:
        P.DeckIndex(col, BIG)
        base = len(reads)
        col.db.conn.execute("UPDATE cards SET odid = did, did = 60, queue = 0 WHERE id = 3")  # into a lesson's deck
        idx = P.DeckIndex(col, BIG)
        into = len(reads) == base and 3 in idx.home
        col.db.conn.execute("UPDATE cards SET did = odid, odid = 0 WHERE id = 3")  # studied, home again
        P.DeckIndex(col, BIG)
        back = len(reads) == base
        col.db.conn.execute("UPDATE cards SET did = 20 WHERE id = 4")  # moved to another deck: a change
        idx = P.DeckIndex(col, BIG)
        moved = len(reads) == base + 1 and 4 not in idx.home
    finally:
        P.DeckIndex._read_static = real
    check("the deck's read: a card into a filtered deck and home again reads nothing again; one leaving the deck does",
          into and back and moved, (into, back, moved, len(reads)))


def test_board():
    pid = "p1"
    card = {"id": pid, "title": "Path Book", "status": {"togo": 84, "behind": 0}}
    a = board._plan_card_html(card)
    b = board._plan_card_html(dict(card, lesson_deck={"today": "l2", "held": 0}))
    check("card, A: as before", "<b>84</b> to go today</span>" in a and "planstudydate" not in a, a)
    check("card, B: today's lesson is in your decks, and Study goes to its deck",
          "<b>84</b> to go today, in your decks" in b and "planstudydate:p1:l2" in b, b)
    late = board._plan_card_html(dict(card, status={"togo": 84, "behind": 31, "since": "Wed"}, lesson_deck={"today": "l2", "held": 0}))
    check("card, B, behind too: Study, then Catch up…", late.index("planstudydate") < late.index("plancatch")
          and "in your decks, and <span" in late, late)
    line = board._opened_line({"n": 78, "dates": [["p1", "l1", "Cell injury", 78]], "decks": True})
    check("the morning's line, B", "Cell injury</a> 78, in your decks</span>" in line, line)
    check("the morning's line, B, without its dates", "opened 78 new cards, in your decks.</span>"
          in board._opened_line({"n": 78, "decks": True}))
    check("the morning's line, A: as before", "Cell injury</a> 78</span>" in board._opened_line(
        {"n": 78, "dates": [["p1", "l1", "Cell injury", 78]]}))
    src = open(os.path.join(REPO, "due_crew", "board.py")).read()
    flow = open(os.path.join(REPO, "due_crew", "plan_flow.py")).read()
    check("the card's Study is planstudydate, which plan_flow handles", 'cmd == "planstudydate"' in flow and "planstudydate" in src)


def main():
    for n in [n for n in list(globals()) if n.startswith("test_")]:
        globals()[n]()
    bad = [c for c in CHECKS if not c[1]]
    print(f"\n{len(CHECKS) - len(bad)}/{len(CHECKS)} checks passed")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
