"""Labs, the plan window (due_crew/planner, docs/planner.md), against a fake
collection and the fake Worker (tests/fakes.py). Standard library only.

Run: python3 tests/test_planner.py
"""

import ast
import datetime
import glob
import json
import os
import random
import re
import sqlite3
import sys
import tempfile
import types

HARNESS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HARNESS)
sys.path.insert(0, HARNESS)

import fakes  # noqa: E402

STORE = fakes.FakeWorker()
fakes.install_fake_requests(STORE)
fakes.install_fake_aqt()
sys.path.insert(0, REPO)

from due_crew import plans as P                               # noqa: E402
from due_crew import planner                                   # noqa: E402
from due_crew.backend import api                               # noqa: E402
from due_crew.planner import actions as A                      # noqa: E402
from due_crew.planner import edits as E                        # noqa: E402
from due_crew.planner import model as M                        # noqa: E402
from due_crew.planner import qids as Q                         # noqa: E402
from due_crew.planner import remote as R                       # noqa: E402

CHECKS = []
ROOT = "#Big_Step1_v3"
VID = f"{ROOT}::#Videos::Cardio::Heart_Failure"
SYS = f"{ROOT}::^Systems::Cardio::Heart_Failure"
BOOK = f"{ROOT}::#Book::Cardio::Heart_Failure"
DRUGS = f"{ROOT}::#Videos::Pharm::HF_Drugs"
OTHER = "Pharm::Antibiotics"


def check(name, cond, detail=""):
    CHECKS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond or detail == "" else f"\n     {detail}"))


def world(users):
    store = fakes.FakeWorker()
    sys.modules["requests"].Session = lambda: fakes.FakeSession(store)
    for uid, name in users.items():
        store.add_user(uid, name)
    return store


def new_client(store, uid):
    cl = api.ApiClient(os.path.join(tempfile.mkdtemp(), "session.json"))
    cl.session = {"user_id": uid, "token": store.session_for(uid), "email": f"{uid}@example.com", "display_name": uid}
    return cl


def collection():
    """Big Step 1 (deck 1) and its Cardio subdeck (2), and a deck of its own (3).
    Cards by note: 1-4 a video and a system (1-2 new, 3 a review, 4 shut and new),
    5-6 the book (5 shut review, 6 new), 7-9 the bank's questions (7 shut new, 8
    shut review, 9 review), 10 the other bank's, 11 another root's tag, 12 a
    leech (shut), 13-14 in the subdeck, untagged, 15 a drug video, in a filtered deck."""
    conn = sqlite3.connect(":memory:")
    fakes.make_collection(conn)
    add = fakes.add_card
    add(conn, 1, 1, tags=f"{VID} {SYS}")
    add(conn, 2, 1, tags=f"{VID} {SYS}")
    add(conn, 3, 1, ctype=2, queue=2, ivl=10, tags=f"{VID} {SYS}")
    add(conn, 4, 1, queue=-1, tags=f"{VID} {SYS}")
    add(conn, 5, 1, ctype=2, queue=-1, ivl=8, tags=BOOK)
    add(conn, 6, 1, tags=BOOK)
    add(conn, 7, 1, queue=-1, tags=f"{ROOT}::#Bank::10234")
    add(conn, 8, 1, ctype=2, queue=-1, ivl=5, tags=f"{ROOT}::#Bank::10911")
    add(conn, 9, 1, ctype=2, queue=2, ivl=5, tags=f"{ROOT}::#Bank::011002")
    add(conn, 10, 1, tags=f"{ROOT}::#Other_Bank::10234")
    add(conn, 11, 1, tags=OTHER)
    add(conn, 12, 1, queue=-1, tags=f"{VID} leech")
    add(conn, 13, 2)
    add(conn, 14, 2, ctype=2, queue=2, ivl=3)
    add(conn, 15, 4, odid=1, ctype=2, queue=2, ivl=4, tags=DRUGS)
    col = fakes.FakeCol(conn, fakes.day_cutoff_for(datetime.date(2026, 11, 9)))
    col.decks = fakes.FakeDecks({1: "Big Step 1", 2: "Big Step 1::Cardio", 3: "Mine", 4: "Due Crew::Cram"})
    # the review cards come due a month out (Anki's day 1000 is today), so Bring back has something to move
    conn.execute("UPDATE cards SET due = 1030 WHERE type = 2")
    return col


def state(col):
    return {int(c): (int(q), int(t), int(d)) for c, q, t, d in col.db.all("SELECT id, queue, type, due FROM cards")}


# ---- the gate ----

def test_gate():
    check("gate: labs is on only for a config whose labs is true",
          planner.enabled({"labs": True}) and not planner.enabled({}) and not planner.enabled({"labs": "true"})
          and not planner.enabled({"labs": 1}))
    # 3.9.3: the windows are everyone's, in Tools › Due Crew › Plans
    from aqt import qt

    class Menu:
        def __init__(self, title="", parent=None):
            self.title, self.items = title, []

        def addAction(self, label):
            self.items.append(label)
            return types.SimpleNamespace(triggered=types.SimpleNamespace(connect=lambda f: None))

        def addSeparator(self):
            self.items.append("—")
    saved = qt.QMenu
    qt.QMenu = Menu
    try:
        m = planner.plans_menu(None)
    finally:
        qt.QMenu = saved
    check("gate: Tools › Due Crew › Plans holds everything about plans, the three windows among it, for everyone",
          m.title == "Plans" and m.items == ["Your plans…", "New plan…",
                                             "Follow a plan…", "—", "QBank QIDs…", "Export cards for my AI…"], m.items)
    init = open(os.path.join(REPO, "due_crew", "__init__.py")).read()
    check("gate: Tools › Due Crew puts the Plans submenu in, and the old plan entries at its root are gone",
          "planner.plans_menu(menu)" in init and "Make a plan from a deck…" not in init and "(labs)" not in init)
    cfgj = open(os.path.join(REPO, "due_crew", "config.json")).read()
    check("gate: no default config turns labs on (a key nothing writes)", '"labs"' not in cfgj)


def test_for_everyone():
    """3.9.3: Your plans opens for anyone signed in (the admin's alone in
    labs): one request on the click, my plans; labs on or off."""
    store = world({"sam": "Sammy", "dre": "Dre"})
    store.admins.add("sam")
    dre = new_client(store, "dre")  # not the admin: the window is everyone's
    from due_crew.planner import flow
    shown, tips = [], []
    saved = (flow.enabled, flow.client, flow._bg, flow.show_plans, flow.tooltip, flow.mw.col, flow.plan_flow._signed_in)
    try:
        flow.enabled = lambda: False
        flow._bg = lambda job, done: done(job())
        flow.show_plans = lambda plans, select=None, tab=None: shown.append((plans, select, tab))
        flow.tooltip = lambda text, **k: tips.append(text)
        flow.plan_flow._signed_in = lambda: True
        flow.mw.col = object()
        flow._open.clear()
        pid, _code = store.add_plan("dre", "MS2 Block 2", "Big Step 1",
                                    [{"id": "u1", "name": "Heart failure", "opens": "2026-11-09", "tags": [VID]}])
        flow.client = lambda: dre
        n = len(store.log)
        flow.open_plans(select=pid, tab="layout")
        check("everyone: anyone's account gets the window, on the plan and tab asked for, labs off",
              len(shown) == 1 and [p["id"] for p in shown[0][0]] == [pid] and shown[0][1:] == (pid, "layout") and not tips,
              (shown, tips))
        check("everyone: one request on the click, my plans (no asking who I am)",
              [p for _m, p, _s in store.log[n:]] == ["/plans/mine"], store.log[n:])
        flow.plan_flow._signed_in = lambda: False
        flow.open_plans()
        check("everyone: signed out, nothing (the sign-in asks)", len(shown) == 1)
    finally:
        flow.enabled, flow.client, flow._bg, flow.show_plans, flow.tooltip, flow.mw.col, flow.plan_flow._signed_in = saved
        flow._open.clear()


# ---- a deck tag ----

def test_tags():
    check("tags: a #part is a resource, ^ a system, none other, a digit leaf a question",
          [M.kind(t) for t in (VID, SYS, OTHER, f"{ROOT}::#Bank::10234", f"{ROOT}::Cardio")]
          == ["resource", "system", "other", "question", "other"])
    check("tags: named as the deck files them",
          M.split(VID) == ("Videos", "Cardio › Heart Failure") and M.split(SYS) == ("Systems", "Cardio › Heart Failure")
          and M.split(OTHER) == ("", "Pharm › Antibiotics") and M.split(f"{ROOT}::Cardio") == ("", "Cardio")
          and M.split(f"{ROOT}::#Videos") == ("Videos", ""), [M.split(t) for t in (VID, OTHER)])
    check("tags: a question's bank is its #part; one line names a tag",
          M.bank(f"{ROOT}::#Other_Bank::10234") == "Other Bank" and M.label(VID) == "Videos › Cardio › Heart Failure")


def test_sources():
    col = collection()
    idx = P.DeckIndex(col, 1)
    doc = {"deck": "Big Step 1", "tagroot": "MS2", "tags": [{"id": "t1", "name": "SLG 5", "notes": ["guid000001"]}],
           "units": [{"id": "u1", "name": "Heart failure", "opens": "2026-11-09",
                      "tags": [VID, SYS, f"{ROOT}::#Bank::10234", f"{ROOT}::#Bank::10911", OTHER, "DueCrew::MS2::SLG_5"],
                      "cut": [{"tag": BOOK, "in": "t1", "q": "x"}], "search": ["x", "deck:current"],
                      "decks": ["Big Step 1::Cardio"], "cards": [["guid000006", 0]]}]}
    rows = M.sources(idx, doc["units"][0], doc)
    kinds = [(r["kind"], r["group"], r["name"]) for r in rows]
    check("sources: one row each, in the window's order: resources, systems, other, questions, plan tags, subdecks, searches, picks",
          kinds == [("resource", "Videos", "Cardio › Heart Failure"), ("resource", "Book", "Cardio › Heart Failure · SLG 5"),
                    ("system", "Systems", "Cardio › Heart Failure"), ("other", "Other tags", "Pharm › Antibiotics"),
                    ("question", "Bank", "2 questions"), ("plan", "This plan’s tags", "SLG 5"),
                    ("deck", "Subdecks", "Cardio"), ("search", "Searches", "Search"),
                    ("picks", "Picked cards", "1 single card")], kinds)
    by = {(r["kind"], r["name"]): r for r in rows}
    by.update({r["name"]: r for r in rows if r["kind"] not in ("resource", "system")})
    check("sources: each holds what it finds in this copy (a cut its tag kept to the plan tag's)",
          by[("resource", "Cardio › Heart Failure")]["cids"] == {1, 2, 3, 4, 12}
          and by[("system", "Cardio › Heart Failure")]["cids"] == {1, 2, 3, 4}
          and by[("resource", "Cardio › Heart Failure · SLG 5")]["cids"] == set()
          and by["2 questions"]["cids"] == {7, 8} and by["SLG 5"]["cids"] == {1} and by["Cardio"]["cids"] == {13, 14}
          and by["1 single card"]["cids"] == {6}, {k: v["cids"] for k, v in by.items()})
    check("sources: a key says which part of the date each is",
          by["2 questions"]["key"] == ("questions", (f"{ROOT}::#Bank::10234", f"{ROOT}::#Bank::10911"))
          and by[("resource", "Cardio › Heart Failure · SLG 5")]["key"] == ("cut", BOOK, "t1") and by["Cardio"]["key"] == ("deck", "Big Step 1::Cardio")
          and by["1 single card"]["key"] == ("picks",))
    groups = [g for g, _rows in M.grouped(rows)]
    check("sources: grouped for the window, a resource's rows under its name",
          groups == ["Videos", "Book", "Systems", "Other tags", "Bank", "This plan’s tags", "Subdecks", "Searches", "Picked cards"], groups)
    c = M.counts(idx, {1, 2, 3, 4, 12})
    check("counts: new as plans count it, shut, and the leech that stays shut",
          c == {"cards": 5, "new": 4, "open": 3, "shut": 2, "leech": 1}, c)


def test_weeks():
    doc = {"deck": "x", "units": [{"id": "a", "name": "Heart failure", "opens": "2026-11-09"},
                                  {"id": "b", "name": "HF drugs", "opens": "2026-11-10", "due": "2026-11-12"},
                                  {"id": "c", "name": "Shock", "opens": "2026-10-28"},
                                  {"id": "d", "name": "Block review", "opens": "2026-12-03"}],
           "events": [{"id": "e1", "day": "2026-11-13", "name": "Heme quiz"}, {"id": "e2", "day": "2026-11-30", "name": "Exam"}]}
    ws = M.weeks(doc, "2026-11-11")
    check("weeks: numbered from the plan's first, only weeks with something on, the days on them",
          [(w["n"], w["label"], w["now"]) for w in ws]
          == [(1, "Week 1 · Wed 28 Oct", False), (3, "Week 3 · 9–13 Nov", True), (6, "Week 6 · 30 Nov–3 Dec", False)],
          [(w["n"], w["label"]) for w in ws])
    check("weeks: dates and events each under their week",
          [u["id"] for u in ws[1]["dates"]] == ["a", "b"] and [e["id"] for e in ws[1]["events"]] == ["e1"]
          and [u["id"] for u in ws[2]["dates"]] == ["d"])
    check("weeks: open on this one, else the next ahead, else the last",
          M.pick_week(ws, "2026-11-11")["n"] == 3 and M.pick_week(M.weeks(doc, "2026-11-20"), "2026-11-20")["n"] == 6
          and M.pick_week(M.weeks(doc, "2026-10-01"), "2026-10-01")["n"] == 1
          and M.pick_week(M.weeks(doc, "2027-01-01"), "2027-01-01")["n"] == 6 and M.pick_week([], "x") is None)
    check("weeks: a date's and an event's line", M.date_label(doc["units"][0]) == "Mon 9 · Heart failure"
          and M.event_label(doc["events"][0]) == "Fri 13 · Heme quiz")
    paced = dict(doc, pace={"days": [1, 1, 1, 1, 1, 0, 0]})
    check("pace: a date's window counts the plan's study days",
          M.study_days(paced, doc["units"][1])[2] == 3 and M.pace_words(paced, doc["units"][1], 100) == "over 3 study days, about 34 a day"
          and M.pace_words(paced, doc["units"][0], 50) == "" and M.pace_words(paced, doc["units"][1], 0) == "")
    check("weeks: none for an empty plan", M.weeks({"units": []}, "2026-11-11") == [])


def test_picker_model():
    col = collection()
    idx = P.DeckIndex(col, 1)
    top = M.children(idx, "")
    check("picker: the top of the deck's tags, #-parts first, as written", [p for p, _n, _m in top] == [ROOT, "leech", "Pharm"], top)
    under = M.children(idx, ROOT)
    check("picker: one level at a time: resources, then systems, with whether there's more",
          [(p.rsplit("::", 1)[-1], more) for p, _n, more in under]
          == [("#Bank", True), ("#Book", True), ("#Other_Bank", True), ("#Videos", True), ("^Systems", True)], under)
    check("picker: a bank's questions aren't listed, they're counted",
          M.children(idx, f"{ROOT}::#Bank") == [] and M.questions(idx, f"{ROOT}::#Bank") == 3)
    check("picker: a search finds every path holding all its words, shallow first",
          M.find(idx, "heart failure") == [BOOK, VID, SYS] and M.find(idx, "cardio") [:3] == [f"{ROOT}::#Book::Cardio", f"{ROOT}::#Videos::Cardio", f"{ROOT}::^Systems::Cardio"]
          and M.find(idx, "") == [] and M.find(idx, "10234") == [], M.find(idx, "cardio"))
    check("picker: a tag's cards and new ones here", M.tag_count(idx, VID) == (5, 4) and M.tag_count(idx, "nope") == (0, 0))
    hits = M.find(idx, "pharm")
    check("picker: a path above a tag is found too", "Pharm" in hits and OTHER in hits, hits)


# ---- question IDs ----

def test_qids():
    check("qids: every run of 3 to 9 digits, once each, leading zeros off, in order",
          Q.numbers("10234, 10911\n011002 · 10234 · 65% 12 1234567890 Q 777") == ["10234", "10911", "11002", "777"])
    col = collection()
    idx = P.DeckIndex(col, 1)
    banks = Q.banks(idx)
    check("qids: the deck's question tags by bank",
          set(banks) == {"Bank", "Other Bank"} and banks["Bank"] == {"10234": {7}, "10911": {8}, "11002": {9}}
          and banks["Other Bank"] == {"10234": {10}}, banks)
    f = Q.find(idx, "Missed: 10234 10911 11002 2026 99999")
    check("qids: a paste reads the bank with the most of its numbers; what isn't a question is said",
          f["bank"] == "Bank" and f["found"] == ["10234", "10911", "11002"] and f["missing"] == ["2026", "99999"]
          and f["cids"] == {7, 8, 9} and f["banks"] == [("Bank", 3), ("Other Bank", 1)], f)
    check("qids: which bank is asked only when it's close (the runner-up has half as many or more); one stray number isn't",
          not Q.close(f) and Q.close(Q.find(idx, "10234")) and not Q.close(Q.find(idx, "10911"))
          and Q.close({"banks": [("A", 4), ("B", 2)]}) and not Q.close({"banks": [("A", 5), ("B", 2)]})
          and not Q.close({"banks": [("A", 0)]}))
    g = Q.find(idx, "10234 10911", bank="Other Bank")
    check("qids: another bank, when asked", g["bank"] == "Other Bank" and g["cids"] == {10} and g["missing"] == ["10911"])
    t = Q.tally(idx, f["cids"] | {12})
    check("qids: what they are here: open, shut (would open), a leech (stays shut), seen before",
          t == {"cards": 4, "open": 1, "shut": 2, "leech": 1, "new_shut": 1, "review": 2}, t)
    words = Q.words(f, Q.tally(idx, f["cids"]), [("MS2 Block 2", ["Mon 9 Nov", "Tue 10 Nov"])])
    check("qids: its lines, plainly, the counts first in Anki's words (3.9.3)",
          words == ["3 questions · 3 cards · 2 suspended",
                    "2 numbers aren’t questions here: 2026, 99999", "On MS2 Block 2: Mon 9 Nov, Tue 10 Nov"], words)
    lw = Q.words(Q.find(idx, "10234 10911"), Q.tally(idx, {7, 8, 12}))
    check("qids: a leech is said, and stays suspended", lw[0] == "2 questions · 3 cards · 2 suspended · 1 leech left suspended", lw)
    check("qids: nothing pasted says nothing (the box says what to paste); nothing a question says so",
          Q.words(Q.find(idx, ""), Q.tally(idx, set())) == []
          and Q.words(Q.find(idx, "55555"), Q.tally(idx, set())) == ["None of these are questions in this deck."])
    cold = collection()
    cold.db.conn.execute("UPDATE notes SET tags = ' x '")
    check("qids: a deck with no question tags has no banks", Q.banks(P.DeckIndex(cold, 1)) == {}
          and Q.find(P.DeckIndex(cold, 1), "10234")["bank"] is None)


def test_nothing_kept():
    """3.9.3 (Sam): the window reads the paste in it, nothing more: no
    misses kept on this computer, no All my misses, no In common (what's not
    sticking is Insights')."""
    from due_crew.planner import flow
    check("kept: no misses kept, no qids.json", not hasattr(flow, "misses_log") and not hasattr(Q, "keep")
          and "qids.json" not in open(flow.__file__, encoding="utf-8").read())
    check("kept: no threads", not hasattr(Q, "threads") and "In common" not in open(Q.__file__.replace("qids.py", "qid_window.py"), encoding="utf-8").read())


def test_unsuspend_and_study():
    col = collection()
    before = state(col)
    n = A.unsuspend(col, {7, 8, 9, 12, 15, 3}, "Due Crew: unsuspend 2 cards")
    after = state(col)
    check("unsuspend: the suspended ones (never the leech), one undo step under its name",
          n == 2 and after[7][0] == 0 and after[8][0] == 2 and after[12][0] == -1 and len(col.undo_steps) == 1
          and col.undo_steps[0][0] == "Due Crew: unsuspend 2 cards", (n, after, col.undo_steps))
    check("unsuspend: no due date moves (3.9.3: nothing comes back over 3 days)",
          all(after[c][2] == before[c][2] for c in (3, 8, 9, 15)) and "set_due_date" not in open(A.__file__).read(), after)
    check("unsuspend: a new one goes first in Anki's line", after[7][2] == 0
          and any(n == "Reposition" or 7 in ids for n, ids in col.undo_steps), col.undo_steps)
    check("unsuspend: nothing suspended, nothing done, no undo step",
          A.unsuspend(col, {7, 8, 9}, "x") == 0 and len(col.undo_steps) == 1)
    col = collection()
    col.decks = fakes.FakeDecks({1: "Big Step 1", 2: "Big Step 1::Cardio", 3: "Mine", 4: "Due Crew::Cram",
                                 5: "Due Crew::QBank cards"})
    col.db.conn.execute("UPDATE cards SET odid = did, did = 5 WHERE id = 14")  # an earlier paste's, not done yet
    before = state(col)
    built = []

    def build(want):
        built.append(list(want))
        col.db.conn.execute(f"UPDATE cards SET odid = did, did = 5 WHERE odid = 0 AND id IN ({','.join(map(str, want))})")
        return True
    got = A.study(col, {7, 8, 9, 12, 15}, "Due Crew: study 5 QBank cards", "Due Crew::QBank cards", build)
    after = state(col)
    check("study: the suspended ones unsuspended (never the leech), then the deck over what's in it and these",
          got == (2, 4) and built == [[7, 8, 9, 14]] and after[12][0] == -1 and after[7][0] == 0 and after[8][0] == 2, (got, built))
    check("study: one undo step under its name; no due date moves",
          len(col.undo_steps) == 1 and col.undo_steps[0][0] == "Due Crew: study 5 QBank cards"
          and all(after[c][2] == before[c][2] for c in (8, 9)), (col.undo_steps, after))
    check("study: a card in another filtered deck stays where it is", 15 not in built[0] and after[15] == before[15])
    built.clear()
    check("study: the same paste again opens the deck (they're in it), nothing new to build in",
          A.study(col, {7, 8}, "y", "Due Crew::QBank cards", build) == (0, 4) and built == [[7, 8, 9, 14]])
    built.clear()
    steps = len(col.undo_steps)
    check("study: none that can go in (a leech), nothing done, no undo step",
          A.study(col, {12}, "z", "Due Crew::QBank cards", build) == (0, 0) and built == [] and len(col.undo_steps) == steps)


# ---- an author's edits ----

def _doc():
    return {"deck": "Big Step 1",
            "units": [{"id": "u1", "name": "Heart failure", "opens": "2026-11-09", "due": "2026-11-11", "check": "2026-11-12",
                       "even": True, "tags": [VID], "decks": [], "cards": [], "ids": ["g1"], "idr": [["g", 0]], "pn": [1, 0, 0]},
                      {"id": "u2", "name": "HF drugs", "opens": "2026-11-10", "tags": [DRUGS], "decks": [], "cards": [],
                       "cut": [{"tag": BOOK, "in": "t1", "q": "q1"}], "search": ["q1", "q2"], "sn": {"q1": 3, "q2": 4}}],
            "reviews": [{"day": "2026-11-14", "from": "u1", "to": "u2"}]}


def test_edits():
    d = _doc()
    d2, n = E.add_sources(d, "u1", [BOOK, VID.upper(), BOOK], ["Big Step 1::Cardio"])
    check("edits: sources onto a date, each once (any case), the doc never changed in place",
          n == 2 and d2["units"][0]["tags"] == [VID, BOOK] and d2["units"][0]["decks"] == ["Big Step 1::Cardio"]
          and d["units"][0]["tags"] == [VID], d2["units"][0])
    full = _doc()
    full["units"][0]["tags"] = [f"t{i}" for i in range(50)]
    try:
        E.add_sources(full, "u1", ["one more"])
        refused = None
    except E.Refused as e:
        refused = str(e)
    check("edits: a date holds 50 tags, as the server does", refused == "A date holds up to 50 tags.", refused)
    d3 = E.take_source(d, "u2", ("cut", BOOK, "t1"))
    u = d3["units"][1]
    check("edits: a cut comes off with its search and its count; the rest stays",
          "cut" not in u and u["search"] == ["q2"] and u["sn"] == {"q2": 4} and u["tags"] == [DRUGS], u)
    try:
        E.take_source(d, "u1", ("tag", VID))
        last = None
    except E.Refused as e:
        last = str(e)
    check("edits: not the last thing on a date", last and "delete the date" in last, last)
    u = next(x for x in E.take_source(d, "u2", ("search", "q2"))["units"] if x["id"] == "u2")
    check("edits: a search comes off here too (3.9.3), its count with it", "q2" not in (u.get("search") or [])
          and "q2" not in (u.get("sn") or {}), u)
    m = E.move(d, "u1", "2026-11-16")
    u1 = next(x for x in m["units"] if x["id"] == "u1")
    check("edits: a move takes its due date and checkpoint the same days, and the dates stay in order",
          (u1["opens"], u1["due"], u1["check"]) == ("2026-11-16", "2026-11-18", "2026-11-19")
          and [x["id"] for x in m["units"]] == ["u2", "u1"])
    s = E.set_due(d, "u1", None)
    check("edits: no due date, no even split", "due" not in s["units"][0] and "even" not in s["units"][0])
    try:
        E.set_due(d, "u1", "2026-11-01")
        early = None
    except E.Refused as e:
        early = str(e)
    check("edits: a due date before it opens is refused", early == "The due date is before the date opens.")
    check("edits: a name as the server keeps one", E.rename(d, "u1", "  Heart\n failure,  part 2 ")["units"][0]["name"]
          == "Heart failure, part 2")
    try:
        E.rename(d, "u1", "   ")
        blank = None
    except E.Refused as e:
        blank = str(e)
    check("edits: a date needs a name", blank == "A date needs a name.")
    a, uid = E.add_date(d, "2026-11-11", [SYS, BOOK], rng=random.Random(7))
    new = next(x for x in a["units"] if x["id"] == uid)
    check("edits: a new date, its id as the builder makes one, named for what's on it, in order",
          re.fullmatch(r"[a-km-np-z2-9]{8}", uid) and new["name"] == "Heart Failure + 1 more" and new["tags"] == [SYS, BOOK]
          and new["cards"] == [] and [x["id"] for x in a["units"]] == ["u1", "u2", uid], new)
    try:
        E.add_date(d, "2026-11-11")
        empty = None
    except E.Refused as e:
        empty = str(e)
    check("edits: a new date needs something on it", empty == "Pick something for the date first.")
    gone = E.delete_date(d, "u2")
    check("edits: a date deleted takes the review days that name it", [x["id"] for x in gone["units"]] == ["u1"]
          and "reviews" not in gone)
    col = collection()
    idx = P.DeckIndex(col, 1)
    rc = E.recount(d2, idx, {"u1"})
    check("edits: a changed date counted in this copy (its tags' and subdecks' cards, as the tree counts them)",
          rc["units"][0]["n"] == 5 + 2 + 2 and "n" not in rc["units"][1], rc["units"][0].get("n"))
    lean = E.lean(d)
    check("edits: a save leaves what only the author's Anki sends with the server",
          not any(k in lean["units"][0] for k in ("ids", "idr", "pn", "pl")) and "ids" in d["units"][0])
    line = E.what_changed(d, E.add_sources(E.rename(d, "u2", "Drugs"), "u1", [BOOK])[0])
    check("edits: one line for the plan's history, said to be from Anki",
          line == "Mon 9 Nov: added 1 tag; renamed Tue 10 Nov (in Anki)" or line == "renamed Tue 10 Nov; Mon 9 Nov: added 1 tag (in Anki)", line)
    check("edits: a long history line fits the server's 120", len(E.what_changed({"units": []}, a)) <= 120
          and len(E.what_changed({"units": []}, {"units": [{"id": f"x{i}", "opens": "2026-11-09"} for i in range(40)]})) <= 120)


def test_saves():
    store = world({"sam": "Sammy", "dre": "Dre"})
    sam, dre = new_client(store, "sam"), new_client(store, "dre")
    pid, _code = store.add_plan("sam", "MS2 Block 2", "Big Step 1", _doc()["units"])
    store.plans[pid]["doc"]["units"][1]["ids"] = ["kept"]
    raw, plan = R.load(sam, pid)
    check("saves: a plan as the server keeps it, and cleaned to read", plan["role"] == "owner" and raw["version"] == 1
          and raw["doc"]["units"][0].get("ids") == ["g1"])
    doc, _n = E.add_sources(raw["doc"], "u1", [BOOK])
    got = R.save(sam, pid, raw["version"], doc, E.what_changed(raw["doc"], doc))
    u = {x["id"]: x for x in store.plans[pid]["doc"]["units"]}
    check("saves: the builder's save: one PUT from its version, the plan a version on, its line in the history",
          got[0] == "saved" and store.plans[pid]["version"] == 2 and u["u1"]["tags"] == [VID, BOOK]
          and store.plan_log[-1][3] == "Mon 9 Nov: added 1 tag (in Anki)"
          and [m for m, p, _s in store.log if p == f"/plans/{pid}"][-1] == "PUT", (got[0], store.plan_log))
    sent = [b for m, p, b in store.bodies if m == "PUT" and p == f"/plans/{pid}"][-1]
    check("saves: what only the author's Anki sends isn't sent; the server kept its own where nothing changed",
          not any(k in x for x in sent["doc"]["units"] for k in ("ids", "idr", "pn"))
          and "ids" not in u["u1"] and u["u2"]["ids"] == ["kept"] and set(sent) == {"version", "doc", "summary"}, u)
    store.edit_plan(pid, [dict(x, name=x["name"] + "!") if x["id"] == "u2" else x for x in store.plans[pid]["doc"]["units"]])
    late = E.rename(raw["doc"], "u1", "Heart failure 1")
    got = R.save(sam, pid, raw["version"], late, "renamed")
    check("saves: one from an older version is stale, and comes back with the plan as it is",
          got[0] == "stale" and got[1]["version"] == 3 and store.plans[pid]["doc"]["units"][0]["name"] == "Heart failure", got[0])
    got = R.save(dre, pid, 3, late, "x")
    check("saves: someone not an author is refused, in words", got == ("refused", "You're not one of this plan's authors any more."), got)
    bad = dict(late, units=[dict(late["units"][0], opens="soon")] + late["units"][1:])
    got = R.save(sam, pid, 3, bad, "x")
    check("saves: one the plan can't take, in words", got == ("refused", "The plan didn't take that change."), got)
    same = R.save(sam, pid, 1, store.plans[pid]["doc"], "again")
    check("saves: the same doc again changes nothing (the server writes nothing)", same[0] == "saved" and store.plans[pid]["version"] == 3)

    class Lost:
        """A save whose answer was lost: the server has it, the retry is stale."""
        def __init__(self, now):
            self.now = now

        def _call(self, method, path, body=None):
            if method == "PUT":
                return 409, {"error": "stale", "version": 9}
            return 200, {"id": pid, "version": 9, "role": "owner", "name": "x", "doc": self.now}
    mine = _doc()
    landed = dict(E.lean(mine), units=[dict(u, n=4, ids=["x"]) for u in E.lean(mine)["units"]][::-1])
    check("saves: a stale answer to a save that landed (the plan is what it sent) is saved",
          R.save(Lost(landed), pid, 1, mine, "x")[0] == "saved"
          and R.save(Lost(E.rename(landed, "u1", "Other")), pid, 1, mine, "x")[0] == "stale")


# ---- the glue ----

def test_flow():
    from due_crew.planner import flow
    from due_crew import plan_flow as F
    col = collection()
    saved = (F._state_cfg, flow.mw.col, F.followed, F._after_change, F._claim_opened, F.refresh_progress, flow.app.swap,
             flow.cfg, F._filtered, getattr(flow.mw, "moveToState", None))
    calls = []
    try:
        flow.mw.col = col
        F._state_cfg = lambda c=None: {"p1": {"deck_id": 1, "swap": None, "applied": {}}}
        ops = flow.Ops()
        plan = {"id": "p1", "doc": {"deck": "Elsewhere", "units": []}}
        idx, swap, how = ops.context(plan, plan["doc"])
        check("glue: a plan I follow here reads the deck it runs on here", how == "followed" and idx.did == 1 and swap is None)
        idx, swap, how = ops.context({"id": "p2"}, {"deck": "Big Step 1", "units": []})
        check("glue: one I write, the deck named like its own", how == "named" and idx.did == 1)
        idx, swap, how = ops.context({"id": "p3"}, {"deck": "Not here", "units": [{"id": "a", "opens": "2026-11-09", "tags": ["Elsewhere::Not::Here"]}]})
        check("glue: none here, none", idx is None and how == "")
        qo = flow.QidOps()
        choices = P.deck_choices(col)
        check("glue: question IDs start on the deck my plans run on", qo.default_deck(choices) == 1)
        conf = {}
        flow.cfg = lambda: conf
        F._state_cfg = lambda c=None: {"p1": {"deck_id": 2}}
        check("glue: a plan on a subdeck starts them on its top deck (question tags are deck-wide)", qo.default_deck(choices) == 1)
        F._state_cfg = lambda c=None: {"p1": {"deck_id": 3}, "p2": {"deck_id": 1}, "p3": {"deck_id": 2}}
        check("glue: the deck most of my plans run on", qo.default_deck(choices) == 1)
        conf["plan_pick"] = "p1"
        check("glue: with two or more, the plan You › Plans shows first", qo.default_deck(choices) == 3)
        conf["plan_pick"] = "gone"
        check("glue: a pick no longer followed: the most", qo.default_deck(choices) == 1)
        F._state_cfg = lambda c=None: {"p1": {"deck_id": 1, "swap": None, "applied": {}}}
        F.followed = lambda: [{"id": "p1", "name": "MS2 Block 2",
                               "doc": {"deck": "Big Step 1", "units": [{"id": "a", "name": "HF", "opens": "2026-11-09", "tags": [f"{ROOT}::#Bank"]},
                                                                       {"id": "b", "name": "Shock", "opens": "2026-11-12", "tags": [VID]}]}}]
        idx = qo.index(1)
        check("glue: the dates of my plans that hold them, by name and day",
              qo.plan_dates(1, idx, {7, 8}) == [("MS2 Block 2", ["Mon 9 Nov"])] and qo.plan_dates(3, idx, {7}) == [])
        F._after_change = lambda: calls.append("undo")
        F._claim_opened = lambda shut: calls.append(("claim", sorted(shut)))
        F.refresh_progress = lambda: calls.append("progress")
        flow.app.swap = lambda c: calls.append("swap")
        flow.cfg = lambda: {}
        got = qo.unsuspend({7, 8, 9})
        check("glue: Unsuspend is one undo step, then what an open does (Edit's undo, my pace, the board)",
              got == 2 and calls == ["undo", ("claim", [7, 8]), "progress", "swap"]
              and col.undo_steps[-1][0] == "Due Crew: unsuspend 2 cards", (got, calls))
        calls.clear()
        col.decks = fakes.FakeDecks({1: "Big Step 1", 2: "Big Step 1::Cardio", 3: "Mine", 4: "Due Crew::Cram",
                                     5: "Due Crew::QBank cards"})
        col.decks.select = lambda d: calls.append(("select", d))
        flow.mw.moveToState = lambda s: calls.append(s)

        def filtered(c, name, cids, order=4, **kw):
            calls.append(("build", name, list(cids), order))
            c.db.conn.execute(f"UPDATE cards SET odid = did, did = 5 WHERE odid = 0 AND id IN ({','.join(map(str, cids))})")
            return True
        F._filtered = filtered
        check("glue: Study now builds Due Crew › QBank cards (in random order), one undo step, and opens it",
              qo.study({7, 8, 9}) is True and calls == [("build", "Due Crew::QBank cards", [7, 8, 9], F.STUDY_ORDER), "undo",
                                                        ("select", 5), "overview"]
              and col.undo_steps[-1][0] == "Due Crew: study 3 QBank cards", (calls, col.undo_steps[-1:]))
    finally:
        (F._state_cfg, flow.mw.col, F.followed, F._after_change, F._claim_opened, F.refresh_progress, flow.app.swap,
         flow.cfg, F._filtered, flow.mw.moveToState) = saved


# ---- a plan from a block's calendar (reading.py, claude.py's stand-in) ----

CAL = """BLOCK 2 · Cardiovascular
WEEK 1
Mon 10/26  LEC  Heart failure
    SLG 1  Define systolic and diastolic heart failure
    Watch: heart failure 1-2
Tue 10/27  LEC  HFrEF
Wed 10/28  Thanksgiving break
Thu 10/29  LEC  Antiarrhythmic drugs
Fri 10/30  QUIZ  Cardio quiz 1
WEEK 2
Mon 11/2  LEC  Diuretics
Tue 11/3  LEC  Acid-base
Fri 11/6  EXAM  Exam 1
"""
CAL_TODAY = datetime.date(2026, 10, 19)
HF_V, HF_S, HF_B = (f"{ROOT}::#Videos::Cardio::Heart_Failure", f"{ROOT}::^Systems::Cardio::Heart_Failure",
                    f"{ROOT}::#Book::Cardio::Heart_Failure")
SYSTOLIC, ANTI = f"{ROOT}::#Videos::Cardio::Systolic_Dysfunction", f"{ROOT}::#Videos::Pharm::Antiarrhythmics"
DIURETICS, ACID = f"{ROOT}::#Book::Renal::Diuretics", f"{ROOT}::#Videos::Renal::Acid_Base"


def cal_collection():
    """A block's deck: heart failure in a video and a system (the same notes)
    and the book; systolic dysfunction, antiarrhythmics, diuretics, acid-base,
    a question number."""
    conn = sqlite3.connect(":memory:")
    fakes.make_collection(conn)
    for cid, tags in ((1, f"{HF_V} {HF_S}"), (2, f"{HF_V} {HF_S}"), (3, HF_B), (4, SYSTOLIC), (5, ANTI), (6, DIURETICS),
                      (7, f"{ROOT}::#Bank::10234"), (8, ACID)):
        fakes.add_card(conn, cid, 1, tags=tags)
    col = fakes.FakeCol(conn, fakes.day_cutoff_for(CAL_TODAY))
    col.decks = fakes.FakeDecks({1: "Big Step 1"})
    return col


def test_reading():
    from due_crew.planner import reading as RD
    ss = RD.number_weeks(RD.read_calendar(CAL, CAL_TODAY))
    check("reading: each dated line a session, by date, in its week; a break left out",
          [(x["date"], x["kind"], x["title"], x["week"]) for x in ss]
          == [("2026-10-26", "lecture", "Heart failure", 1), ("2026-10-27", "lecture", "HFrEF", 1),
              ("2026-10-29", "lecture", "Antiarrhythmic drugs", 1), ("2026-10-30", "quiz", "Cardio quiz 1", 1),
              ("2026-11-02", "lecture", "Diuretics", 2), ("2026-11-03", "lecture", "Acid-base", 2),
              ("2026-11-06", "exam", "Exam 1", 2)], ss)
    check("reading: the lines under a session, its objectives and what it lists",
          ss[0]["objectives"] == [{"label": "SLG 1", "text": "Define systolic and diastolic heart failure"}]
          and ss[0]["listed"] == [{"how": "watch", "text": "heart failure 1-2"}] and not ss[1]["objectives"])
    check("reading: the plan's name is the calendar's first line that names something, never one with a date",
          RD.name_from(CAL) == "BLOCK 2 · Cardiovascular" and RD.name_from("Mon 10/26 Heart failure") == ""
          and RD.name_from("We meet on Oct 26 for heart failure.\nCardio block") == "Cardio block"
          and RD.name_from("Mon 10/26  Heart failure\n    SLG 1  Define systolic and diastolic heart failure") == "")
    table = "Heart failure | Mon 10/26 | Room B2 | Dr. Lee\nAcid-base\t11/3\tB2\n"
    check("reading: a table's rows, the cell that names something (not the room, not who)",
          [(x["date"], x["title"]) for x in RD.read_calendar(table, CAL_TODAY)]
          == [("2026-10-26", "Heart failure"), ("2026-11-03", "Acid-base")])
    got = [RD.parse_date(t, CAL_TODAY)[0] for t in ("Mon 10/26", "Oct 26", "26 October 2026", "2026-10-26",
                                                    "Monday, October 26th", "10/26/26")]
    check("reading: the ways a calendar writes a date, the year that's coming when none is written",
          got == [datetime.date(2026, 10, 26)] * 6 and RD.parse_date("3/1", datetime.date(2026, 11, 20))[0]
          == datetime.date(2027, 3, 1) and RD.parse_date("26/10", CAL_TODAY, day_first=True)[0]
          == datetime.date(2026, 10, 26), got)
    weeks = RD.number_weeks(RD.read_calendar("Mon 10/26 Heart failure\nMon 11/2 Diuretics", CAL_TODAY))
    check("reading: a calendar with no weeks written gets them from the first session's Monday",
          [x["week"] for x in weeks] == [1, 2])
    check("reading: prose with no line starting with a date is plain rules' none (the stand-in's job)",
          RD.read_calendar("We meet on Oct 26 for heart failure.\nThe cardio quiz is on Oct 30.", CAL_TODAY) == [])
    sc = lambda t: RD.scope(t, ss, CAL_TODAY)
    check("reading: an exam's line by plain rules: weeks, numbered lectures, dates, up to a date",
          sc("Exam 1 covers weeks 1-2") == ([0, 1, 2, 4, 5], []) and sc("lectures 1-3") == ([0, 1, 2], [])
          and sc("Oct 26 - Oct 29") == ([0, 1, 2], []) and sc("everything through 10/29") == ([0, 1, 2], [])
          and sc("weeks 1-2 lectures") == ([0, 1, 2, 4, 5], []), [sc("weeks 1-2 lectures"), sc("everything through 10/29")])
    check("reading: what plain rules can't place is left, word for word (some of a week)",
          sc("Exam 1 covers week 1 and week 2's renal lectures") == ([0, 1, 2], ["week 2's renal lectures"]),
          sc("Exam 1 covers week 1 and week 2's renal lectures"))


def _docx_bytes(paragraphs, rows, listed=()):
    """A Word file as Word writes one, the parts the reader reads: paragraphs
    (a list item numbered), then a table."""
    import io
    import zipfile
    from xml.sax.saxutils import escape
    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    para = lambda t, li=False: ("<w:p>" + ("<w:pPr><w:numPr><w:ilvl w:val=\"0\"/></w:numPr></w:pPr>" if li else "")
                                + f"<w:r><w:t>{escape(t)}</w:t></w:r></w:p>")
    body = "".join(para(t, t in listed) for t in paragraphs)
    body += "<w:tbl>" + "".join("<w:tr>" + "".join(f"<w:tc>{para(c)}</w:tc>" for c in row) + "</w:tr>" for row in rows) + "</w:tbl>"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", f'<?xml version="1.0"?><w:document {w}><w:body>{body}</w:body></w:document>')
    return buf.getvalue()


def test_calendar_files():
    from due_crew.planner import reading as RD
    ics = ("BEGIN:VCALENDAR\r\nX-WR-CALNAME:MS2 Block 2\r\nBEGIN:VEVENT\r\nDTSTART;TZID=America/New_York:20261027T090000\r\n"
           "SUMMARY:LEC: HFrEF\r\nEND:VEVENT\r\nBEGIN:VEVENT\r\nDTSTART;VALUE=DATE:20261026\r\nSUMMARY:Heart failure\\, "
           "part 1\r\nDESCRIPTION:SLG 1 Define systolic and diastolic heart failure\\nWatch: heart fa\r\n ilure 1-2\r\n"
           "END:VEVENT\r\nBEGIN:VEVENT\r\nDTSTART:20261030T130000Z\r\nSUMMARY:Cardio quiz 1\r\nEND:VEVENT\r\n"
           "BEGIN:VEVENT\r\nDTSTART;VALUE=DATE:20261028\r\nSUMMARY:Fall break\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    text, why = RD.from_file("block2.ics", ics.encode())
    ss = RD.read_calendar(text, CAL_TODAY)
    check("files: a calendar export's events, by date, its name first, a description's lines under its event",
          not why and RD.name_from(text) == "MS2 Block 2"
          and [(x["date"], x["kind"], x["title"]) for x in ss] == [("2026-10-26", "lecture", "Heart failure, part 1"),
                                                                    ("2026-10-27", "lecture", "HFrEF"),
                                                                    ("2026-10-30", "quiz", "Cardio quiz 1")]
          and ss[0]["objectives"][0]["label"] == "SLG 1" and ss[0]["listed"] == [{"how": "watch", "text": "heart failure 1-2"}],
          (text, ss))
    doc = _docx_bytes(["MS2 Block 2 · Cardiovascular", "Mon 10/26 LEC Heart failure",
                       "Define systolic and diastolic heart failure"],
                      [["Date", "Session", "Room"], ["Tue 10/27", "HFrEF", "Room B2"], ["Fri 10/30", "Cardio quiz 1", "B2"]],
                      listed=("Define systolic and diastolic heart failure",))
    text, why = RD.from_file("Block 2.docx", doc)
    ss = RD.read_calendar(text, CAL_TODAY)
    check("files: a Word file's paragraphs and its table's rows (a list item an objective, not a room)",
          not why and [(x["date"], x["title"]) for x in ss] == [("2026-10-26", "Heart failure"), ("2026-10-27", "HFrEF"),
                                                                 ("2026-10-30", "Cardio quiz 1")]
          and ss[0]["objectives"] == [{"label": "", "text": "Define systolic and diastolic heart failure"}], (text, ss))
    text, why = RD.from_file("block.csv", b'Date,Session,Where\n"Monday, October 26, 2026",Heart failure,Room B2\n'
                                          b'10/27/2026,HFrEF,B2\n')
    check("files: a sheet saved as CSV, its rows a table",
          not why and [(x["date"], x["title"]) for x in RD.read_calendar(text, CAL_TODAY)]
          == [("2026-10-26", "Heart failure"), ("2026-10-27", "HFrEF")], text)
    text, why = RD.from_file("notes.txt", "Mon 10/26  Heart failure\r\nTue 10/27  HFrEF".encode("cp1252"))
    check("files: text as it is, any line ending", not why and text == "Mon 10/26  Heart failure\nTue 10/27  HFrEF")
    said = {n: RD.from_file(n, b"x")[1] for n in ("block.xlsx", "block.pages", "photo.png")}
    check("files: what it can't read says what to do instead",
          "CSV" in said["block.xlsx"] and ".docx" in said["block.pages"] and ".ics" in said["photo.png"], said)
    check("files: a broken Word file, an empty one, one too big, each said",
          "couldn't be read" in RD.from_file("x.docx", b"not a zip")[1] and "no text" in RD.from_file("x.txt", b"  \n")[1]
          and "too big" in RD.from_file("x.txt", b"a" * (RD.FILE_MAX + 1))[1])
    check("files: the file's name names a plan whose calendar names none",
          RD.file_name("/Users/sam/Downloads/MS2_Block_2 calendar.pdf") == "MS2 Block 2 calendar"
          and RD.file_name("C:\\x\\Block 3.ics") == "Block 3")
    check("files: a PDF's table, its cells run together, keeps the room out of the title",
          [x["title"] for x in RD.read_calendar("Mon 11/2 Diuretics Room B2\nFri 11/6 Exam 1 Hall A", CAL_TODAY)]
          == ["Diuretics", "Exam 1"])
    check("reading: a kind column comes off a title, a title that starts with its kind keeps it",
          [RD.clean_title(t) for t in ("LEC  Heart failure", "Lecture: Heart failure", "Exam 1", "Lab safety", "QUIZ Cardio quiz 1")]
          == ["Heart failure", "Heart failure", "Exam 1", "Lab safety", "Cardio quiz 1"])


def _pptx_bytes(slides, order=None):
    """A deck as PowerPoint writes one, the parts the reader reads: slides
    [(title, [(level, text)], [[cell]])], listed in `order` (indexes; a
    deck's order isn't its files' names)."""
    import io
    import zipfile
    from xml.sax.saxutils import escape
    P_ = 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" ' \
         'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" ' \
         'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        rels, ids = [], []
        for n, (title, body, table) in enumerate(slides, 1):
            sp = (f'<p:sp><p:nvSpPr><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr><p:txBody><a:p><a:r><a:t>{escape(title)}'
                  '</a:t></a:r></a:p></p:txBody></p:sp>') if title else ""
            if body:
                sp += "<p:sp><p:nvSpPr><p:nvPr/></p:nvSpPr><p:txBody>" + "".join(
                    f'<a:p><a:pPr lvl="{lvl}"/><a:r><a:t>{escape(t)}</a:t></a:r></a:p>' for lvl, t in body) + "</p:txBody></p:sp>"
            if table:
                sp += "<p:graphicFrame><a:graphic><a:graphicData><a:tbl>" + "".join(
                    "<a:tr>" + "".join(f"<a:tc><a:txBody><a:p><a:r><a:t>{escape(c)}</a:t></a:r></a:p></a:txBody></a:tc>" for c in row)
                    + "</a:tr>" for row in table) + "</a:tbl></a:graphicData></a:graphic></p:graphicFrame>"
            z.writestr(f"ppt/slides/slide{n}.xml", f'<?xml version="1.0"?><p:sld {P_}><p:cSld><p:spTree>{sp}</p:spTree></p:cSld></p:sld>')
            z.writestr(f"ppt/media/image{n}.png", b"\x89PNG" + b"0" * 50)  # a picture: never read
            rels.append(f'<Relationship Id="rId{n + 1}" Type="slide" Target="slides/slide{n}.xml"/>')
        for k in (order or range(len(slides))):
            ids.append(f'<p:sldId id="{256 + k}" r:id="rId{k + 2}"/>')
        z.writestr("ppt/presentation.xml", f'<?xml version="1.0"?><p:presentation {P_}><p:sldIdLst>{"".join(ids)}'
                                           '</p:sldIdLst></p:presentation>')
        z.writestr("ppt/_rels/presentation.xml.rels", '<?xml version="1.0"?><Relationships '
                   'xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + "".join(rels) + "</Relationships>")
    return buf.getvalue()


def test_slides():
    import io
    from due_crew.planner import reading as RD
    deck = _pptx_bytes([("Diuretics", [], []),
                        ("Learning objectives", [(0, "Describe the loop diuretics' site of action"),
                                                 (0, "Compare thiazides with loop diuretics")], []),
                        ("Loop diuretics", [(0, "Furosemide"), (1, "Ototoxicity")], []),
                        ("Acid-base effects", [], []),
                        ("Questions?", [], []),
                        ("", [(0, "Block schedule")], [["Mon 11/2", "Diuretics", "Room B2"], ["Tue 11/3", "Acid-base", "B2"]])],
                       order=[0, 1, 3, 2, 4, 5])
    slides = RD.pptx_slides(io.BytesIO(deck))
    check("slides: a deck's slides in its own order, titles, levels, a table's rows; pictures never read",
          [t for t, _l in slides] == ["Diuretics", "Learning objectives", "Acid-base effects", "Loop diuretics", "Questions?",
                                      "Block schedule"]
          and slides[3][1] == ["    Furosemide", "        Ototoxicity"] and slides[5][1] == ["Mon 11/2\tDiuretics\tRoom B2",
                                                                                         "Tue 11/3\tAcid-base\tB2"], slides)
    text, why = RD.from_file("Renal 4.pptx", io.BytesIO(deck))
    check("slides: a deck dropped on the box reads as text, a schedule on a slide as a table",
          not why and [(x["date"], x["title"]) for x in RD.read_calendar(text, CAL_TODAY)]
          == [("2026-11-02", "Diuretics"), ("2026-11-03", "Acid-base")], (text, why))
    got = RD.from_slides(slides)
    check("slides: what a lecture's slides add: its objectives slide's lines, the topics its slides name",
          got["title"] == "Diuretics" and [o["text"] for o in got["objectives"]]
          == ["Describe the loop diuretics' site of action", "Compare thiazides with loop diuretics"]
          and got["slides"] == ["Acid-base effects", "Loop diuretics", "Block schedule"], got)
    labelled = RD.from_slides([("Cardio", []), ("Heart failure", ["SLG 3  Define systolic and diastolic dysfunction"])])
    check("slides: a line labelled like an objective is one, wherever it is",
          labelled["objectives"] == [{"label": "SLG 3", "text": "Define systolic and diastolic dysfunction"}])
    pages = RD.pdf_pages(["Diuretics\nDr. Lee", "Objectives\nDescribe the loop diuretics' site of action", "Loop diuretics\nFurosemide", ""])
    check("slides: a deck saved as a PDF, each page's first line its title",
          RD.from_slides(pages)["slides"] == ["Loop diuretics"] and len(RD.from_slides(pages)["objectives"]) == 1)
    check("slides: an old .ppt or a Keynote file says what to do",
          ".pptx" in RD.from_file("a.ppt", b"x")[1] and ".pptx" in RD.from_file("a.key", b"x")[1]
          and "couldn't be read" in RD.from_file("a.pptx", b"not a zip")[1])
    big = b"Mon 10/26 Heart failure\n" + b" " * (RD.FILE_MAX + 10)
    check("slides: a PDF, Word file or deck may be big (their pictures weigh), a text file not",
          "too big" in RD.from_file("a.txt", big)[1] and RD.from_file("a.docx", big)[1] != "That file is too big to be a calendar.")
    col = cal_collection()
    idx = P.DeckIndex(col, 1)
    s = RD.session(CAL_TODAY, "Renal pharm")
    before = [c["tag"] for c in RD.candidates(idx, s)]
    s["slides"] = got["slides"]
    s["objectives"] = got["objectives"]
    after = RD.candidates(idx, s)
    check("slides: a session its title can't place finds its tags by its slides' titles and objectives",
          DIURETICS not in before and {DIURETICS, ACID} <= {c["tag"] for c in after}, (before, [c["tag"] for c in after]))
    from due_crew.planner import claude as C
    req = C.request("pick", session=s, cands=RD.could_fit(idx, s))
    check("Claude would get: a session's slides' titles too, never a slide's words beyond its objectives",
          req["input"]["session"]["slides"] == got["slides"] and "Furosemide" not in str(req))


def test_matching():
    from due_crew.planner import reading as RD
    col = cal_collection()
    idx = P.DeckIndex(col, 1)
    ss = RD.number_weeks(RD.read_calendar(CAL, CAL_TODAY))
    cands = RD.candidates(idx, ss[0])
    tags = [c["tag"] for c in cands]
    check("matching: a session's title names its tags, the same cards once (a system with its video's notes)",
          tags[:2] == [HF_B, HF_V] and HF_S not in tags and all(c["title"] for c in cands[:2]), tags)
    check("matching: plain rules tick what the title names, one a resource",
          RD.pick(cands) == [0, 1] and cands[0]["cards"] == 1 and cands[1]["cards"] == 2)
    check("matching: question numbers are never a session's", not [t for t in tags if "#Bank" in t])
    check("matching: words it can't read match nothing (HFrEF, antiarrhythmic drugs)",
          RD.pick(RD.candidates(idx, ss[1])) == [] and RD.pick(RD.candidates(idx, ss[2])) == [])
    check("matching: one word is one", RD.pick(RD.candidates(idx, ss[4])) == [0]
          and RD.candidates(idx, ss[4])[0]["tag"] == DIURETICS)


def test_stand_in():
    from due_crew.planner import claude as C
    from due_crew.planner import reading as RD
    col = cal_collection()
    idx = P.DeckIndex(col, 1)
    ss = RD.number_weeks(RD.read_calendar(CAL, CAL_TODAY))
    si = C.StandIn()
    check("stand-in: it says it's a stand-in and that nothing is sent", si.fake and "stand-in" in si.status()
          and "Nothing is sent" in si.status())
    cands, got, why = si.pick(idx, ss[1])
    check("stand-in: reads an abbreviation as a reader would (HFrEF, systolic)",
          [cands[i]["tag"] for i in got] == [SYSTOLIC] and why == "read HFrEF as systolic or reduced", (got, why))
    cands, got, why = si.pick(idx, ss[2])
    check("stand-in: takes a title's words one at a time before reading them",
          [cands[i]["tag"] for i in got] == [ANTI] and why == "matched its words one at a time", [c["tag"] for c in cands])
    cands, got, why = si.pick(idx, RD.session(CAL_TODAY, "Ethics"))
    check("stand-in: says so when nothing fits", got == [] and why == "found nothing that fits")
    prose = "We meet on Oct 26 for heart failure.\nThe cardio quiz is on Oct 30.\nNo class Oct 28 (holiday)."
    check("stand-in: finds a date anywhere in a line (prose), breaks still left out",
          [(x["date"], x["kind"], x["title"]) for x in si.calendar(prose, CAL_TODAY)]
          == [("2026-10-26", "lecture", "Heart failure"), ("2026-10-30", "quiz", "Cardio quiz")],
          si.calendar(prose, CAL_TODAY))
    ticked = {4: [DIURETICS], 5: [ACID]}
    check("stand-in: some of a week, by the titles and the tags ticked for them (diuretics are renal)",
          si.scope(["week 2's renal lectures"], ss, ticked) == ([4, 5], [])
          and si.scope(["week 2's renal lectures"], ss) == ([], ["week 2's renal lectures"])
          and si.scope(["week 1's drugs lectures"], ss) == ([2], []), si.scope(["week 1's drugs lectures"], ss))


def test_from_sessions():
    from due_crew.planner import reading as RD
    ss = RD.number_weeks(RD.read_calendar(CAL, CAL_TODAY))
    rng = random.Random(4)
    doc, units, events = E.from_sessions({"deck": "Big Step 1", "units": []}, ss,
                                         {0: [HF_B, HF_V], 1: [SYSTOLIC], 2: [], 4: [DIURETICS], 5: [ACID]}, rng=rng)
    by = {u["id"]: u for u in doc["units"]}
    ev = {e["id"]: e for e in doc["events"]}
    check("calendar plan: a quiz and an exam are events, a session with tags a date named as it is, on its day",
          sorted(units) == [0, 1, 4, 5] and sorted(events) == [3, 6]
          and [(e["day"], e["name"]) for e in doc["events"]] == [("2026-10-30", "Cardio quiz 1"), ("2026-11-06", "Exam 1")]
          and [(u["opens"], u["name"], u["tags"]) for u in doc["units"]][:2]
          == [("2026-10-26", "Heart failure", [HF_B, HF_V]), ("2026-10-27", "HFrEF", [SYSTOLIC])], doc)
    check("calendar plan: nothing ticked, not on the plan", 2 not in units)
    check("calendar plan: each date preps for the next quiz or exam",
          [ev[by[units[i]]["for"]]["name"] for i in (0, 1, 4, 5)] == ["Cardio quiz 1"] * 2 + ["Exam 1"] * 2)
    doc2, units2, events2 = E.from_sessions({"deck": "Big Step 1", "units": []}, ss,
                                            {0: [HF_V], 4: [DIURETICS]}, {6: [0, 4]}, rng=random.Random(4))
    by2 = {u["id"]: u for u in doc2["units"]}
    check("calendar plan: what an exam's line covers preps for it, though a quiz comes first",
          by2[units2[0]]["for"] == events2[6] and by2[units2[4]]["for"] == events2[6])
    store = world({"sam": "Sammy"})
    pid, _code = store.add_plan("sam", "MS2 Block 2", "Big Step 1", [])
    sam = new_client(store, "sam")
    outcome, raw = R.save(sam, pid, store.plans[pid]["version"], doc, "made in Anki from a calendar")
    check("calendar plan: the server takes it, events and all", outcome == "saved"
          and len(raw["doc"]["events"]) == 2 and all(u.get("for") for u in raw["doc"]["units"]), raw)
    try:
        E.from_sessions({"deck": "x", "units": [], "events": [{"id": f"e{n:07d}", "day": "2026-11-01", "name": "x"}
                                                              for n in range(E.EVENTS_MAX)]}, ss, {})
        refused = False
    except E.Refused as e:
        refused = "200" in str(e)
    check("calendar plan: the ceiling on quizzes and exams is the server's, said first", refused)


def test_what_claude_would_get():
    import json as J
    from due_crew.planner import claude as C
    from due_crew.planner import reading as RD
    col = cal_collection()
    idx = P.DeckIndex(col, 1)
    ss = RD.number_weeks(RD.read_calendar(CAL, CAL_TODAY))
    near = RD.nearby(idx, [HF_B, HF_V, DIURETICS, ACID])
    check("Claude would get: beside what the block has ticked, the deck's other tags there",
          near == [SYSTOLIC], near)
    fits = {i: [c["tag"] for c in RD.could_fit(idx, ss[i], near)] for i in (0, 1, 2)}
    check("Claude would get: a session nothing matched still has tags to choose among (its words' stems, what's beside)",
          fits[1] == [SYSTOLIC] and fits[2][0] == ANTI and fits[0][:2] == [HF_B, HF_V], fits)
    cands = RD.could_fit(idx, ss[0], near)
    asked = [C.request("calendar", text=CAL, today=CAL_TODAY), C.request("pick", session=ss[0], cands=cands),
             C.request("scope", phrases=["week 2's renal lectures"], sessions=ss, tags={4: [DIURETICS]})]
    text = J.dumps(asked)
    check("Claude would get: each job its words and what to answer in (by number, never a name it makes up)",
          [a["job"] for a in asked] == ["Read a block's calendar", "Match a session to the deck's tags", "What an exam covers"]
          and all(set(a) == {"job", "instructions", "input", "answer"} and a["answer"]["type"] == "object" for a in asked)
          and asked[1]["answer"]["properties"]["picks"]["items"]["properties"]["n"]["type"] == "integer")
    check("Claude would get: the calendar's words and tag names with their counts; no card, note or id",
          "_cids" not in text and "guid" not in text
          and [set(t) for t in asked[1]["input"]["tags"]] == [{"n", "tag", "cards"}] * len(cands)
          and asked[2]["input"]["sessions"][3]["tags"] == [DIURETICS]
          and not [x for x in asked[2]["input"]["sessions"] if x["title"] in ("Cardio quiz 1", "Exam 1")], text[:300])
    try:
        C.request("anything")
        unknown = False
    except ValueError:
        unknown = True
    check("Claude would get: only the three jobs", unknown)


def test_start_flow():
    from due_crew.planner import flow
    store = world({"sam": "Sammy", "dre": "Dre"})
    store.admins.add("sam")
    sam, dre = new_client(store, "sam"), new_client(store, "dre")
    col = collection()
    shown, tips = [], []
    saved = (flow.enabled, flow.client, flow._bg, flow.show_start, flow.tooltip, flow.mw.col, flow.plan_flow._signed_in,
             flow.remote.save, flow.open_plans)
    try:
        flow.mw.col = col
        check("calendar glue: the top-level decks, biggest first (its subdecks' and filtered cards counted)",
              flow.top_decks(col) == [(1, "Big Step 1", 15), (3, "Mine", 0)], flow.top_decks(col))
        flow.enabled = lambda: True
        flow._bg = lambda job, done: done(job())
        flow.show_start = lambda: shown.append(True)
        flow.tooltip = lambda text, **k: tips.append(text)
        flow.plan_flow._signed_in = lambda: True
        flow.client = lambda: dre
        n = len(store.log)
        flow.open_start()
        check("calendar glue: anyone signed in gets it (3.9.3), nothing asked of the server to open it",
              shown == [True] and not tips and len(store.log) == n, (shown, tips))
        flow.client = lambda: sam
        ops = flow.StartOps()
        owner = types.SimpleNamespace(_alive=True)
        doc, _u, _e = E.from_sessions({"deck": "Big Step 1", "units": []},
                                      [{"date": "2026-11-09", "kind": "lecture", "title": "Heart failure"},
                                       {"date": "2026-11-13", "kind": "quiz", "title": "Cardio quiz"}], {0: [VID]})
        got = []
        ops.make(owner, "MS2 Block 2", doc, got.append)
        mine = [q for q in store.plans.values() if q["owner"] == "sam"]
        check("calendar glue: Make is the builder's New plan, then its save (mine, its dates and quiz on it)",
              len(mine) == 1 and got[0][0] == "saved" and got[0][1]["id"] in store.plans
              and [u["name"] for u in mine[0]["doc"]["units"]] == ["Heart failure"]
              and [e["name"] for e in mine[0]["doc"]["events"]] == ["Cardio quiz"], (got, mine))

        def lost(*a, **k):
            raise api.TransportError("network")
        flow.remote.save = lost
        got = []
        ops.make(owner, "MS2 Block 3", doc, got.append)
        made = got[0]
        check("calendar glue: made but its dates lost on the way says so, with the plan it made",
              made[0] == "made" and made[1] in store.plans and "connection" in made[2], got)
        flow.remote.save = saved[7]
        got = []
        ops.make(owner, "MS2 Block 3", doc, got.append, pid=made[1])
        check("calendar glue: Make again puts the dates on that plan, never a second one",
              got[0][0] == "saved" and got[0][1]["id"] == made[1]
              and sum(1 for q in store.plans.values() if q["name"] == "MS2 Block 3") == 1
              and store.plans[made[1]]["doc"]["units"], got)
        opened = []
        flow.open_plans = lambda select=None: opened.append(select)
        ops.open_plan(made[1])
        check("calendar glue: then the plan window, on it", opened == [made[1]])
        owner._alive = False
        got = []
        ops.make(owner, "MS2 Block 4", doc, got.append)
        check("calendar glue: a window closed meanwhile is told nothing", got == [])
    finally:
        (flow.enabled, flow.client, flow._bg, flow.show_start, flow.tooltip, flow.mw.col, flow.plan_flow._signed_in,
         flow.remote.save, flow.open_plans) = saved
        flow._open.clear()


def test_rules_of_the_road():
    src = {os.path.basename(p): open(p).read() for p in glob.glob(os.path.join(REPO, "due_crew", "planner", "*.py"))}
    windows = {f: t for f, t in src.items() if "(QDialog)" in t}
    check("road: the windows, each wearing the board's look and saying what it is",
          sorted(windows) == ["date_dialogs.py", "date_panel.py", "mcp_dialog.py", "new_plan.py", "picker.py", "qid_window.py",
                              "send.py", "start_window.py", "text_tab.py", "window.py"]
          and all(t.count("(QDialog)") == t.count("attach_alive(self)") == len(re.findall(r"\bheading\(self", t))
                  for t in windows.values()), sorted(windows))
    tabs = {f: t for f, t in src.items() if "(QWidget)" in t}  # round five: Your plans' tabs and panels
    check("road: the tabs and panels (Plan with its date and deck panels, Insights, Settings, Mine, the text, History and Posts, "
          "a date's notes), and no Pip in them",
          sorted(tabs) == ["date_panel.py", "day_notes.py", "deck_panel.py", "history_tab.py", "insights_tab.py", "mine_tab.py",
                           "plan_tab.py", "settings_tab.py", "text_tab.py"]
          and not [f for f, t in dict(windows, **tabs).items() if re.search(r"\bsev\b|pip_note", t)], sorted(tabs))
    windows_tabs = dict(windows, **tabs, **{"widgets.py": src["widgets.py"]})
    check("road: no window sets its own type or margins in a style sheet, nor reads Anki's palette",
          not [f for f, t in windows_tabs.items() if "setStyleSheet" in t or "palette(" in t or "font-size" in t])
    labels = {f: t.count("QLabel(") for f, t in windows_tabs.items()}
    check("road: every label is plain text (names are the authors' and the deck's), its own or widgets.plain's; tooltips escaped",
          all("setTextFormat(Qt.TextFormat.PlainText)" in t or (not labels[f] and "plain(" in t) for f, t in windows_tabs.items())
          and not [f for f, t in windows_tabs.items() if re.search(r'setToolTip\(0, (?!f"<span>\{esc\()', t)])
    pure = ("model.py", "qids.py", "edits.py", "actions.py", "remote.py", "reading.py", "claude.py", "build.py", "text.py",
            "ops.py", "draft.py", "view.py", "prompts.py", "ai.py", "mcp.py", "mcp_shim.py", "insights.py")
    check("road: the pure parts and the requests import no aqt",
          not [f for f in pure if re.search(r"^\s*(from aqt|import aqt)", src[f], re.M)])
    calls = set()
    for f in ("flow.py", "window.py", "plan_tab.py", "date_panel.py", "deck_panel.py", "shape.py", "send.py",
              "mine_tab.py", "new_plan.py", "text_tab.py", "history_tab.py", "settings_tab.py", "day_notes.py", "qid_window.py",
              "picker.py", "start_window.py", "mcp_host.py", "mcp_dialog.py"):
        for node in ast.walk(ast.parse(src[f])):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "remote":
                calls.add(node.attr)
    check("road: requests only on a click, through remote (who I am, my plans, one plan, a save, its history and posts)",
          calls <= {"is_admin", "my_plans", "load", "save", "undo", "create", "log", "posts", "post", "unpost", "save_meta",
                    "set_listed", "copy", "delete", "crew", "add_editor", "remove_editor", "offer", "notes", "add_note",
                    "remove_note"}
          and "_call" not in src["flow.py"], calls)
    routes = set(re.findall(r'_call\((?:client, )?"(GET|PUT|POST|PATCH|DELETE)", f?"([^"]+)"', src["remote.py"]))
    builder = open(os.path.join(REPO, "site", "public", "builder.js")).read()
    check("road: nothing new on the server: routes the builder and the site use already",
          routes == {("GET", "/plans/{pid}"), ("PUT", "/plans/{pid}"), ("POST", "/plans/{pid}/undo"),
                     ("POST", "/plans"), ("GET", "/plans/{pid}/log"), ("GET", "/plans/{pid}/posts"), ("POST", "/plans/{pid}/posts"),
                     ("DELETE", "/plans/{pid}/posts/{int(post_id)}"), ("PUT", "/plans/{pid}/listed"),
                     ("POST", "/plans/{pid}/copy"), ("DELETE", "/plans/{pid}"), ("GET", "/friends"), ("POST", "/plans/{pid}/editors"),
                     ("DELETE", "/plans/{pid}/editors/{uid}"), ("POST", "/plans/{pid}/owner"), ("GET", "/plans/{pid}/notes"),
                     ("POST", "/plans/{pid}/notes"), ("DELETE", "/plans/{pid}/notes/{int(note_id)}")}
          and all(f'api("{m}", `/plans/${{{v}}}{x}' in builder
                  for m, v, x in (("GET", "id", "/log"), ("GET", "id", "/posts"), ("POST", "id", "/posts"), ("DELETE", "id", "/posts/"),
                                  ("PUT", "id", "/listed"), ("POST", "plan.id", "/copy"), ("DELETE", "id", "`"),
                                  ("POST", "id", "/editors"), ("DELETE", "id", "/editors/"), ("POST", "id", "/owner"),
                                  ("GET", "id", "/notes"), ("POST", "id", "/notes"), ("DELETE", "id", "/notes/")))
          and 'api("GET", "/friends")' in builder, routes)
    check("road: Claude isn't connected: the stand-in sends nothing, and nothing reads a card's text for it",
          not re.search(r"^\s*(?:from|import)\s+(?:requests|urllib|http|socket|anthropic)\b", src["claude.py"] + src["reading.py"], re.M)
          and not re.search(r"\bflds\b|\.note\(|\bnote\[", src["claude.py"] + src["reading.py"] + src["start_window.py"]))
    ui_files = {f: t for f, t in windows_tabs.items() if f not in ("widgets.py",)}
    hallmarks = [(f, m) for f, t in ui_files.items()
                 for m in re.findall(r'(?:link|tool|plain|QPushButton|menu_button|addAction)\(\s*f?"(\+ [^"]*|[^"]*[◆▾↗][^"]*)"', t)]
    hallmarks = [(f, m) for f, m in hallmarks if not m.startswith("{'▾' if")]  # a week's fold, as a tree's
    check("road: no AI look in the plan windows (Sam, after the site mock): no '+ A …' links, no ◆, no ▾ or ↗ in words, "
          "no tinted banners or accent stripes, no capitals for a change's kind",
          not hallmarks and not re.search(r'frame\("(?:strip|warm|today|bar|go-bar)"', src["plan_tab.py"] + src["deck_panel.py"]
                                           + src["settings_tab.py"] + src["shape.py"])
          and ".upper()" not in src["send.py"], hallmarks)
    check("road: one way to each thing (Sam, after the site mock): no Study in the plan window (the board studies), no deck tab "
          "(Add from the deck puts the deck in the date's place), no Followers tab, no −1/+1 day (the date's field, Alt+← →, "
          "Month's drag), the plan's dates and pace in Settings (no Change… window)",
          not re.search(r'"Study (them|these|for it)"', src["date_panel.py"]) and "QTabWidget" not in src["plan_tab.py"]
          and "followers_tab.py" not in src and '"−1 day"' not in src["date_panel.py"] and "ShapeDialog" not in src["shape.py"]
          and "Shape(win, form)" in src["settings_tab.py"] and '"Settings"' in src["window.py"] and '"Sharing"' not in src["window.py"])
    order = re.findall(r'self\._add_tab\("(\w+)", "([^"]+)"', src["window.py"])
    check("road: Plan · Insights · Settings, whoever I am (Sam, before the click-test); Insights asks the server nothing",
          [x[1] for x in order] == ["Plan", "Insights", "Settings", "Settings"]
          and not re.search(r"\bremote\b|_call\(", src["insights_tab.py"] + src["insights.py"]), order)
    keys_ = set(re.findall(r'on\("([^"]+)"', src["plan_tab.py"]))
    check("road: the Plan tab's keys (each in its button's tip)",
          {"Ctrl+N", "Ctrl+E", "Ctrl+F", "Ctrl+T", "Ctrl+1", "Ctrl+2", "Ctrl+D", "Ctrl+Z", "Ctrl+Return", "Up", "Down",
           "Alt+Left", "Alt+Right", "Return", "F2", "Delete"} <= keys_, sorted(keys_))
    words = " ".join(src.values()).lower()
    banned = [w for w in ("anking", "uworld", "amboss", "boards and beyond", "sketchy", "pathoma", "first aid", "bootcamp")
              if w in words]
    check("road: no third-party deck, bank or video series named", not banned, banned)
    check("road: never suspends: the one step it adds unsuspends and moves due dates",
          "suspend_cards" not in src["actions.py"].replace("unsuspend_cards", ""))


# ---- 3.9.3: the builder's rules, restated (build.py) ----

def _builder_js():
    """The top of builder.js (its rules, before the plan's page) with what it
    needs of app.js (the dates, Sched), for node."""
    app = open(os.path.join(REPO, "site", "public", "app.js")).read()
    bj = open(os.path.join(REPO, "site", "public", "builder.js")).read()
    head = app[app.index("const MONTHS"):app.index("const today =")]
    sched = app[app.index("const Sched = (() => {"):app.index("// ---- 3.2: home")]
    rules = bj[bj.index("const Tags = (() => {"):bj.index("/** 3.8.0: a plan's squad")]
    return head + "\n" + sched + "\n" + rules


def test_builder_twins_v393():
    """3.9.3: build.py restates builder.js's rules (Todo, Every, Remarks,
    Picks, Suggest, Work, Reviews, Tags.ankiSearch): the same answers on
    the same cases, the site's run in node. Skipped without node."""
    import json
    import shutil
    import subprocess
    from due_crew.planner import build as B
    node = shutil.which("node")
    if not node:
        print("SKIP builder twins: no node")
        return
    todo = [{"k": "watch", "t": "  Lecture 14  ", "url": "https://x.org/l14"}, {"k": "read", "t": ""},
            {"k": "do", "t": "Block 3", "url": "http://not-https"}, {"k": "bad", "t": "x"}] + [{"k": "do", "t": f"n{i}"} for i in range(9)]
    every = [{"k": "do", "t": "Practice", "r": "44"}, {"k": "watch", "t": "x", "r": "7"}, {"k": "read", "t": "Ch", "r": "0123456"}]
    remarks = ["card:abc:3 | on the quiz", "tag:#V::Cardio | skip the end", "card:x:0 | n", "tag:A  two spaces", "nothing"]
    picks = ["2026-10-05 | HF | notes:g1 g2 g1 | cards:g3:2 g3:2 g4:x | tag:A", "cards:a|b:1 c:1002", "notes:  "]
    rows = [[f"{ROOT}::#Videos::Pharm::Antiarrhythmics", 8], [f"{ROOT}::#Videos::Cardio::Heart_Failure", 14],
            [f"{ROOT}::#Videos::Cardio::Arrhythmias", 6], ["DueCrew::MS2::SLG_12", 4], ["DueCrew::MS2::SLG_3", 5],
            [f"{ROOT}::#Book::03_Renal::Physiology", 9], [f"{ROOT}::#Videos::Renal::Physiology", 7], ["Pharm::Cardiac", 2]]
    names = ["Antiarrhythmic", "Heart failure", "SLG 12", "Renal physiology", "cardio arrhythmia week", "Lecture 3", "Cárdiac"]
    docs = [{"deck": "x", "pace": {"mode": "daily", "days": [1, 1, 1, 1, 1, 0, 0], "daily": 20},
             "units": [{"id": "a", "name": "A", "opens": "2026-10-05", "due": "2026-10-09"},
                       {"id": "b", "name": "B", "opens": "2026-10-10"},
                       {"id": "c", "name": "C", "opens": "2026-10-12", "due": "2026-10-30", "even": True}]},
            {"deck": "x", "phases": {"catchup": 3}, "units": [{"id": "a", "name": "A", "opens": "2026-10-03"},
                                                            {"id": "b", "name": "B", "opens": "2026-10-04", "due": "2026-10-20"}]}]
    totals = {"a": 97, "b": 0, "c": 401}
    days = [[1, 1, 1, 1, 1, 0, 0], [1, 0, 1, 0, 1, 0, 0]]
    paths = [["tag", f"{ROOT}::#Videos::Cardio::Heart_Failure"], ["tag", "a_b*c\\d"], ["deck", 'Big "Step"::1_x']]
    segs = ["05_Renal", "#AK_Step1_v12", "^Systems", "!FLAG", "Heart_Failure", "003. Intro", "12) Strep", "a1b2", "Step10_v3",
            "  __  ", "007", "Lecture 3a", "Ébola_2", "x_V12"]
    sortme = ["#Videos", "^Systems", "01_Cardio", "1_Cardio", "02_Renal", "10_GI", "2_Heme", "Ébola", "Ebola", "Árboles", "Animales",
              "Heart_Failure", "Heart Failure", "x 2", "x2", "x_2", "Step1", "Step10", "Step2", "Zeta", "zeta", "!FLAG", "$Junk",
              "straße", "strasse", "Œuvre", "Ølsen", "Pharm (Cardiac)", "Pharm-Cardiac", "Pharm::Cardiac", "Lecture 03", "Lecture 3 a", "日本"]
    prog = _builder_js() + f"""
const out = {{}};
out.todo = Todo.clean({json.dumps(todo)});
out.parse = [Todo.parse("Watch", "lecture 14 https://x.org/a b"), Todo.parse("read", "chapter 6   https://x.org/c")];
out.every = Every.clean({json.dumps(every)});
out.labels = ["0123456", "01234", "14"].map(Every.label);
out.remarks = {json.dumps(remarks)}.map(Remarks.take);
out.rclean = Remarks.clean("one\\n two\\t  three\\u0001");
out.rline = [Remarks.line({{card: ["g", 2], text: "t"}}), Remarks.line({{tag: "A::B", text: "u"}})];
out.picks = {json.dumps(picks)}.map(Picks.take);
out.suggest = {json.dumps(names)}.map((n) => Suggest.tags(n, {json.dumps(rows)}));
out.search = {json.dumps(paths)}.map(([k, p]) => Tags.ankiSearch(k, p));
out.word = {json.dumps(segs)}.map(Tags.word);
out.name = Tags.name({json.dumps("::".join(segs[:4]))});
out.sorted = {json.dumps(sortme)}.slice().sort(Tags.natural);
const docs = {json.dumps(docs)}, totals = {json.dumps(totals)}, days = {json.dumps(days)};
out.spread = []; out.over = []; out.weeks = []; out.peak = []; out.about = [];
for (const doc of docs) for (const d of days) {{
  for (const u of doc.units) out.spread.push(Work.spread(doc, u, totals[u.id], d));
  const w = Work.map(doc, (u) => totals[u.id], d);
  out.over.push(Work.over(w, 15));
  const ws = Reviews.weeks(w);
  out.weeks.push(ws.map((x) => [x.a, Math.round(x.n * 1e6) / 1e6]));
  out.peak.push(Reviews.peak(ws));
}}
out.about = [0, 2.5, 29.4, 31, 147.5, 199, 204, 1234.5].map(Reviews.about);
console.log(JSON.stringify(out));
"""
    got = subprocess.run([node, "-e", prog], capture_output=True, text=True, timeout=60)
    if got.returncode:
        check("builder twins: builder.js runs in node", False, got.stderr[-800:])
        return
    js = json.loads(got.stdout)
    check("builder twins: Todo.clean and Todo.parse", js["todo"] == B.todo_clean(todo)
          and js["parse"] == [B.todo_parse("Watch", "lecture 14 https://x.org/a b"), B.todo_parse("read", "chapter 6   https://x.org/c")],
          (js["todo"], B.todo_clean(todo)))
    check("builder twins: Every.clean and Every.label", js["every"] == B.every_clean(every)
          and js["labels"] == [B.every_label(r) for r in ("0123456", "01234", "14")], (js["every"], B.every_clean(every)))
    check("builder twins: Remarks.take, clean, line", js["remarks"] == [B.remark_take(r) for r in remarks]
          and js["rclean"] == B.remark_clean("one\n two\t  three\u0001")
          and js["rline"] == [B.remark_line({"card": ["g", 2], "text": "t"}), B.remark_line({"tag": "A::B", "text": "u"})],
          (js["remarks"], [B.remark_take(r) for r in remarks]))
    check("builder twins: Picks.take", js["picks"] == [B.picks_take(x) for x in picks], (js["picks"], [B.picks_take(x) for x in picks]))
    mine = [[list(x) for x in B.suggest(n, rows)] for n in names]
    check("builder twins: Suggest.tags (Antiarrhythmic finds Antiarrhythmics; SLG 12 is never SLG 3)",
          js["suggest"] == mine and mine[0] and mine[0][0][0].endswith("Antiarrhythmics") and mine[2] == [["DueCrew::MS2::SLG_12", 4]],
          (js["suggest"], mine))
    check("builder twins: Tags.ankiSearch", js["search"] == [B.anki_search(k, p) for k, p in paths], (js["search"], paths))
    check("builder twins: Tags.word and Tags.name (5 · Renal, Step 1)", js["word"] == [B.tag_word(x) for x in segs]
          and js["name"] == B.tag_name("::".join(segs[:4])) and B.tag_word("05_Renal") == "5 · Renal",
          (js["word"], [B.tag_word(x) for x in segs]))
    check("builder twins: Tags.natural (punctuation, then numbers by value, then letters; accents and case aside)",
          js["sorted"] == sorted(sortme, key=B.natural), (js["sorted"], sorted(sortme, key=B.natural)))
    spread, over, weeks, peak = [], [], [], []
    for doc in docs:
        for d in days:
            for u in doc["units"]:
                spread.append([list(x) for x in B.spread(doc, u, totals[u["id"]], d)])
            w = B.work_map(doc, lambda u: totals[u["id"]], d)
            over.append(B.over(w, 15))
            ws = B.review_weeks(w)
            weeks.append([[x["a"], round(x["n"] * 1e6) / 1e6] for x in ws])
            peak.append(B.review_peak(ws))
    check("builder twins: Work.spread, map and over", js["spread"] == spread and js["over"] == over, (js["spread"], spread))
    check("builder twins: Reviews.weeks, peak and about", js["weeks"] == weeks and js["peak"] == peak
          and js["about"] == [B.about(x) for x in (0, 2.5, 29.4, 31, 147.5, 199, 204, 1234.5)], (js["about"], js["peak"], peak))


def test_build_fill_v393():
    """3.9.3: the builder's Fill and Split, restated: pieces of what to cover
    (a chapter whole while it fits the pace, a bigger one by its own tags,
    the rest of it last, one with nothing below it spread evenly), on study
    days from a day, a pace a day."""
    from due_crew.planner import build as B
    t = B.Tree([("A", 60), ("A::One", 20), ("A::Two", 25), ("B", 50), ("C", 9)], [("Big Step 1", 119)])
    placed = set()
    check("fill: a chapter that fits is one piece; a bigger one goes by its tags, its rest last",
          B.pieces(t, "tag:C", 30, placed) == [{"key": "tag:C", "n": 9}]
          and B.pieces(t, "tag:A", 30, placed) == [{"key": "tag:A::One", "n": 20}, {"key": "tag:A::Two", "n": 25},
                                                  {"key": "tag:A", "n": 15, "rest": True, "even": False}]
          and B.pieces(t, "tag:B", 30, placed) == [{"key": "tag:B", "n": 50, "even": True}], B.pieces(t, "tag:A", 30, placed))
    doc = {"deck": "Big Step 1", "units": [], "pace": {"mode": "daily", "days": [1, 1, 1, 1, 1, 0, 0], "daily": 30}}
    items = B.pieces(t, "tag:A", 30, placed) + B.pieces(t, "tag:B", 30, placed)
    n = iter(f"u{i}" for i in range(99))
    got = B.fill(doc, items, "2026-11-06", None, 30, [1, 1, 1, 1, 1, 0, 0], lambda: next(n))
    us = [(u["opens"], u.get("due"), u["tags"], bool(u.get("even"))) for u in doc["units"]]
    check("fill: each piece on the next study day with room, weekends off; a big one evenly over its days",
          us == [("2026-11-06", None, ["A::One"], False), ("2026-11-09", None, ["A::Two"], False),
                 ("2026-11-10", None, ["A"], False), ("2026-11-11", "2026-11-12", ["B"], True)]
          and got["placed"] == 110 and got["last"] == "2026-11-12" and not got["left"], (us, got))
    doc2 = {"deck": "x", "units": [{"id": "x", "name": "X", "opens": "2026-11-06", "tags": ["Z"], "decks": [], "cards": []}]}
    got2 = B.fill(doc2, [{"key": "tag:C", "n": 9}, {"key": "tag:B", "n": 10}], "2026-11-06", "2026-11-06", 30,
                  [1] * 7, lambda: next(n))
    check("fill: onto a day with a date, it joins it; nothing starts past `until`",
          [u["tags"] for u in doc2["units"]] == [["Z", "C", "B"]] and got2["touched"] == {"x"} and not got2["left"], doc2)
    got3 = B.fill({"deck": "x", "units": []}, [{"key": "tag:C", "n": 9}] * 3, "2026-11-06", "2026-11-06", 0, [1] * 7, lambda: next(n))
    check("fill: with no pace, a piece a day, and what didn't fit by `until` is said",
          len(got3["left"]) == 2 and B.left_names(got3["left"]) == "C, C", got3)
    check("fill: a search's name, as the builder's",
          B.search_name(B.cut_q("#V::Pharm::Ceph", "DueCrew::MS2::SLG_12")) == "SLG 12 and Ceph"
          and B.search_name('"tag:A::Cardio" -"tag:A::Cardio::Extra" -"tag:A::Cardio::Bonus"') == "Cardio but not Extra, Bonus"
          and B.search_name("deck:current") == "Search" and B.search_name('("tag:A" OR "tag:B")') == "A or B")


def test_date_edits_v393():
    """3.9.3: the builder's day panel in Your plans: events, what a date
    preps for, its lines to tick, a review day, a search and IDs, a tag
    kept to a plan tag or without its extras, a note on a tag, Split."""
    doc = {"deck": "Big Step 1", "tagroot": "MS2", "tags": [{"id": "t1", "name": "SLG 12", "notes": ["g1"]}],
           "units": [{"id": "u1", "name": "Heart failure", "opens": "2026-11-09", "tags": [VID], "decks": [], "cards": []},
                     {"id": "u2", "name": "HF drugs", "opens": "2026-11-10", "tags": [DRUGS], "decks": [], "cards": []}]}
    rng = random.Random(4)
    d, eid = E.add_event(doc, "2026-11-13", "Cardio quiz", rng)
    d = E.set_for(d, "u1", eid)
    d = E.rename_event(d, eid, "Cardio quiz 1")
    d = E.move_event(d, eid, "2026-11-12")
    check("dates: an event made, renamed, moved, and a date preps for it",
          d["events"] == [{"id": eid, "day": "2026-11-12", "name": "Cardio quiz 1"}] and d["units"][0]["for"] == eid)
    gone = E.take_event(d, eid)
    check("dates: an event taken off takes every date's for with it", "events" not in gone and "for" not in gone["units"][0])
    t = E.set_todo(d, "u1", [{"k": "watch", "t": "Lecture 14", "url": "https://x.org"}, {"k": "read", "t": "  "}])
    check("dates: lines to tick, the empty ones dropped", t["units"][0]["todo"] == [{"k": "watch", "t": "Lecture 14", "url": "https://x.org"}])
    try:
        E.set_todo(d, "u1", [{"k": "do", "t": f"x{i}"} for i in range(9)])
        many = None
    except E.Refused as e:
        many = str(e)
    check("dates: a date keeps 8 lines to tick", many and "8" in many, many)
    ev = E.set_every(d, [{"k": "do", "t": "Practice questions", "r": "4"}])
    check("dates: a line every Friday", ev["every"] == [{"k": "do", "t": "Practice questions", "r": "4"}])
    r = E.set_review(d, "2026-11-14", "u2", "u1")
    check("dates: a review day of two dates, from the earlier", r["reviews"] == [{"day": "2026-11-14", "from": "u1", "to": "u2"}])
    try:
        E.set_review(d, "2026-11-09", "u1", "u2")
        early = None
    except E.Refused as e:
        early = str(e)
    check("dates: a review day comes after the dates it reviews", early and "after" in early, early)
    check("dates: no review day", "reviews" not in E.take_review(r, "2026-11-14"))
    s = E.add_search(d, "u1", 'tag:#Videos::Cardio  -tag:*Extra*', 12)
    check("dates: a search on a date with what it finds here, one line", s["units"][0]["search"] == ["tag:#Videos::Cardio -tag:*Extra*"]
          and s["units"][0]["sn"] == {"tag:#Videos::Cardio -tag:*Extra*": 12})
    words = []
    for q in ("is:due tag:x", "x" * 501, ""):
        try:
            E.add_search(d, "u1", q)
        except E.Refused as e:
            words.append(str(e))
    check("dates: no search about one person's Anki, none past 500, none empty", len(words) == 3 and "each person" in words[0], words)
    i = E.add_ids(d, "u1", "nids", [5, 5, 6])
    p = E.add_picks(d, "u1", ["g1", "g1"], [["g2", 0], ["g2", 0]])
    check("dates: note IDs and picked notes and cards, each once",
          i["units"][0]["nids"] == [5, 6] and p["units"][0]["notes"] == ["g1"] and p["units"][0]["cards"] == [["g2", 0]])
    off = E.take_source(p, "u1", ("picks",))
    check("dates: picked cards off together", off["units"][0]["cards"] == [] and "notes" not in off["units"][0])
    c = E.set_cut(d, "u1", VID, "t1")
    q = c["units"][0]["cut"][0]["q"]
    check("dates: a tag kept to what one of the plan's tags holds (a cut, its search beside it)",
          c["units"][0]["tags"] == [] and c["units"][0]["cut"] == [{"tag": VID, "in": "t1", "q": q}] and c["units"][0]["search"] == [q]
          and q == '"tag:DueCrew::MS2::SLG\\_12" "tag:#Big\\_Step1\\_v*::#Videos::Cardio::Heart\\_Failure"', q)
    back = E.set_cut(c, "u1", VID, None)
    check("dates: all of it again", back["units"][0]["tags"] == [VID] and "cut" not in back["units"][0] and "search" not in back["units"][0])
    x = E.set_extras(d, "u1", VID, True, [VID + "::Extra"], 9)
    check("dates: a tag without its extras is its search, counted",
          x["units"][0]["tags"] == [] and x["units"][0]["sn"] == {x["units"][0]["search"][0]: 9}
          and E.set_extras(x, "u1", VID, False, [VID + "::Extra"])["units"][0]["tags"] == [VID])
    n = E.set_tag_remark(d, VID, "Skip the\nlast two minutes", rng)
    check("dates: a note for followers on a tag, one line; empty takes it off",
          n["remarks"][0]["text"] == "Skip the last two minutes" and n["remarks"][0]["tag"] == VID
          and "remarks" not in E.set_tag_remark(n, VID.lower(), " ", rng))
    sp, nid = E.split_even(d, "u2", ("tags", DRUGS), ["2026-11-10", "2026-11-11", "2026-11-12"], rng)
    us = {u["id"]: u for u in sp["units"]}
    check("dates: Split evenly: its own date over the study days, due on the last; the date it left goes when empty",
          "u2" not in us and us[nid]["even"] is True and us[nid]["due"] == "2026-11-12" and us[nid]["tags"] == [DRUGS], sp["units"])
    placed, touched = E.place(d, [("2026-11-09", "tags", BOOK), ("2026-11-16", "tags", OTHER)], rng)
    named = E.name_dates(placed, d)
    check("dates: Fill's places join a day's date or make one, named for what's on it (a hand name kept)",
          [u["tags"] for u in named["units"]] == [[VID, BOOK], [DRUGS], [OTHER]]
          and named["units"][0]["name"] == "Heart failure" and named["units"][2]["name"] == "Antibiotics", named["units"])
    one = E.what_changed(d, E.add_search(d, "u1", "tag:Misc", 3))
    check("dates: one search added reads as one", one == "Mon 9 Nov: added 1 search (in Anki)", one)
    line = E.what_changed(d, E.set_for(E.set_todo(d, "u1", [{"k": "do", "t": "x"}]), "u1", None))
    check("dates: a save's history line says what changed", "to-dos" in line and "for nothing" in line and line.endswith("(in Anki)"), line)


def test_lay_out_v393():
    """3.9.3: Lay it out, the builder's: what to cover in a view (a tag that
    holds resources and systems covers what the view shows of it), the
    pace (cards a day, or a finish date it reaches a little more a day),
    just next week, a date aimed at a quiz, and a day over the pace."""
    from due_crew.planner import build as B
    t = B.Tree([("#Big", 250), ("#Big::#Book", 50), ("#Big::#Videos", 100), ("#Big::#Videos::Cardio", 60),
                ("#Big::#Videos::Pulm", 40), ("#Big::^Systems", 100), ("#Big::^Systems::Heart", 100), ("Misc", 10)],
               [("Big Step 1", 260)])
    check("lay out: a tag's views, itself and below",
          B.kinds_below(t, "tag:#Big") == {"resource", "system"} and B.kinds_below(t, "root:tag") == {"resource", "system", "other"}
          and B.tag_kind("#Big::^Systems::Heart") == "system" and B.tag_kind("Misc") == "other")
    check("lay out: a tag holding more than one view covers what this view shows of it",
          B.in_view(t, "tag:#Big", "resource") == ["tag:#Big::#Book", "tag:#Big::#Videos"]
          and B.in_view(t, "tag:#Big", "system") == ["tag:#Big::^Systems"] and B.in_view(t, "tag:#Big", "deck") == ["tag:#Big"],
          B.in_view(t, "tag:#Big", "resource"))
    c = B.toggle(set(), t, "tag:#Big", "resource")
    check("lay out: ticking it ticks those, and shows it ticked; again, they're off",
          c == {"tag:#Big::#Book", "tag:#Big::#Videos"} and B.ticked(c, t, "tag:#Big", "resource")
          and B.toggle(c, t, "tag:#Big", "resource") == set(), c)
    c2 = B.toggle({"tag:#Big::#Videos::Cardio"}, t, "tag:#Big::#Videos", "resource")
    check("lay out: a tag ticked takes the ones below it off; one below a ticked one stays as it is; a tick off",
          c2 == {"tag:#Big::#Videos"} and B.toggle(c2, t, "tag:#Big::#Videos::Pulm", "resource") == c2
          and B.toggle(c2, t, "tag:#Big::#Videos", "resource") == set()
          and B.partly(c2, "tag:#Big") and B.covered(c2, "tag:#Big::#Videos::Pulm"), c2)
    cover = {"tag:#Big::#Book", "tag:#Big::#Videos", "tag:#Big::#Videos::Cardio"}
    check("lay out: what's ticked, none under another, in the tree's order; what's ticked and on no date",
          B.cover_items(t, cover) == ["tag:#Big::#Book", "tag:#Big::#Videos"] and B.cover_left(t, cover, set()) == 150
          and B.cover_left(t, cover, {"tag:#Big::#Videos::Cardio"}) == 90)
    week = [1, 1, 1, 1, 1, 0, 0]
    start = "2026-11-09"  # a Monday
    ids = iter(f"n{i}" for i in range(999))
    doc = {"deck": "Big Step 1", "units": []}
    pace = {"mode": "daily", "days": week, "daily": 30}
    check("lay out: done by, at 30 a day; the cards a day that finish by an end",
          B.finish_by(doc, t, pace, cover, start, 30) == "2026-11-13"
          and B.end_daily(dict(doc, end="2026-11-13"), t, dict(pace, mode="end"), cover, start) == 30
          and B.next_monday("2026-11-04") == start and B.plan_start(doc, start) == start)
    r = B.lay_out(doc, t, pace, cover, start, "2026-11-04", lambda: next(ids))
    us = [(u["opens"], u.get("due"), u["tags"]) for u in doc["units"]]
    check("lay out: Fill at 30 a day: a chapter bigger than the pace spread evenly, weekends off",
          us == [("2026-11-09", "2026-11-10", ["#Big::#Book"]), ("2026-11-11", "2026-11-12", ["#Big::#Videos::Cardio"]),
                 ("2026-11-13", "2026-11-16", ["#Big::#Videos::Pulm"])]
          and r["note"] == "Put 150 cards from Mon 9 Nov to Mon 16 Nov." and len(r["touched"]) == 3 and r["daily"] is None, (us, r))
    doc = {"deck": "Big Step 1", "units": [], "end": "2026-11-13",
           "events": [{"id": "e1", "day": "2026-11-14", "name": "Cardio quiz"}]}
    r = B.lay_out(doc, t, {"mode": "end", "days": week, "daily": 20}, cover, start, "2026-11-04", lambda: next(ids), aim="e1")
    us = [(u["opens"], u.get("due"), u["tags"], u.get("for")) for u in doc["units"]]
    check("lay out: Fill to an end: a little more a day until it all fits by then (30, 33, 37, 41); aimed at a quiz, the dates prep for it",
          r["daily"] == 41 and us == [("2026-11-09", "2026-11-10", ["#Big::#Book"], "e1"),
                                      ("2026-11-11", "2026-11-12", ["#Big::#Videos::Cardio"], "e1"),
                                      ("2026-11-13", None, ["#Big::#Videos::Pulm"], "e1")]
          and r["note"] == "Put 150 cards from Mon 9 Nov to Fri 13 Nov.", (us, r))
    late = {"deck": "Big Step 1", "units": [], "end": "2026-11-08"}
    r = B.lay_out(late, t, {"mode": "end", "days": week, "daily": 20}, cover, start, "2026-11-04", lambda: next(ids))
    check("lay out: an end before the start: nothing, and why",
          not late["units"] and r["note"] == "Nothing fits by Sun 8 Nov: the plan starts Mon 9 Nov. Move the finish date.", r)
    doc = {"deck": "Big Step 1", "units": []}
    r = B.lay_out(doc, t, pace, cover | {"tag:Misc"}, start, "2026-11-04", lambda: next(ids), week_ahead=True)
    check("lay out: just next week: from its Monday, nothing starting after its Sunday, what's left unsaid",
          [u["opens"] for u in doc["units"]] == ["2026-11-09", "2026-11-11", "2026-11-13"]
          and r["note"] == "Put 150 cards from Mon 9 Nov to Mon 16 Nov.", (doc["units"], r))
    r2 = B.lay_out(doc, t, pace, cover | {"tag:Misc"}, start, "2026-11-04", lambda: next(ids))
    check("lay out: Fill again goes on after the last date, with only what's left",
          [(u["opens"], u["tags"]) for u in doc["units"]][-1] == ("2026-11-17", ["Misc"])
          and r2["note"] == "Put 10 cards on Tue 17 Nov.", (doc["units"], r2))
    hd = {"deck": "Big Step 1", "units": [{"id": "u1", "name": "Videos", "opens": start, "tags": ["#Big::#Videos", "Misc"],
                                           "decks": [], "cards": []}]}
    placed = B.placed_keys(hd, t)
    hv = B.heavy(hd, t, pace, set(), start, lambda u: B.unit_total(t, u, placed))
    check("lay out: a day over the pace says so: the date, what it asks, the pace",
          hv and hv["unit"]["id"] == "u1" and hv["cap"] == 30 and hv["top"] > 37.5 and hv["a"] == start, hv)
    check("lay out: what fixes it: Split its biggest tag, or Give it till the study days the pace needs",
          B.biggest(t, hd["units"][0], placed) == "tag:#Big::#Videos"
          and B.give_till(hd, week, hd["units"][0], 110, 30) == "2026-11-12"
          and B.biggest(t, dict(hd["units"][0], even=True), placed) is None)
    check("lay out: no pace, no day over it", B.heavy(hd, t, {"mode": "placed", "days": week}, set(), start, lambda u: 110) is None)


def test_plan_edits_v393():
    """3.9.3: the pace saved, the start moved, the end and its phases, and
    the plan's own tags renamed or deleted (the dates using them follow)."""
    from due_crew.planner import build as B
    p = E.set_pace({"units": []}, "end", [1, 1, 1, 1, 1, 0, 0], 25, ["tag:B", "tag:A", "tag:A"])
    check("plan: the pace, its study days, cards a day, what it covers",
          p["pace"] == {"mode": "end", "days": [1, 1, 1, 1, 1, 0, 0], "daily": 25, "cover": ["tag:B", "tag:A"]}
          and len(E.set_pace({}, "daily", [1] * 7, 20, [f"tag:T{i}" for i in range(600)])["pace"]["cover"]) == 500, p)
    words = []
    for args in (("x", [1] * 7), ("daily", [0] * 7), ("daily", [1] * 6)):
        try:
            E.set_pace({}, *args)
        except E.Refused as e:
            words.append(str(e))
    check("plan: no pace that isn't one, none without a study day", len(words) == 3, words)
    doc = {"units": [{"id": "u1", "opens": "2026-11-09", "due": "2026-11-11", "check": "2026-11-12"}],
           "reviews": [{"day": "2026-11-14", "from": "u1", "to": "u1"}], "events": [{"id": "e1", "day": "2026-11-15"}],
           "end": "2026-12-01", "phases": {"catchup": 0, "taper": 5}}
    s = E.shift_all(doc, 7)
    check("plan: the start moved a week: every date, review day, event and the end with it",
          s["units"][0] == {"id": "u1", "opens": "2026-11-16", "due": "2026-11-18", "check": "2026-11-19"}
          and s["reviews"][0]["day"] == "2026-11-21" and s["events"][0]["day"] == "2026-11-22" and s["end"] == "2026-12-08", s)
    check("plan: no end: its review-only days go with it; catch-up weeks stay",
          "end" not in E.set_end(doc, None) and "phases" not in E.set_end(doc, None)
          and E.set_end(dict(doc, phases={"catchup": 3, "taper": 5}), None)["phases"] == {"catchup": 3, "taper": 0})
    words = []
    for kw in ({"catchup": 1}, {"taper": 61}):
        try:
            E.set_phases(doc, **kw)
        except E.Refused as e:
            words.append(str(e))
    try:
        E.set_phases({"units": []}, taper=5)
    except E.Refused as e:
        words.append(str(e))
    check("plan: catch-up every 2nd to 8th week, 0 to 60 review-only days, and those only with an end",
          len(words) == 3 and E.set_phases(doc, catchup=3)["phases"] == {"catchup": 3, "taper": 5}
          and "phases" not in E.set_phases(doc, taper=0), words)
    root = {"tagroot": "MS2", "tags": [{"id": "t1", "name": "SLG 12"}, {"id": "t2", "name": "SLG 13"}]}
    old = P.tag_path(root, root["tags"][0])
    q = B.cut_q(VID, old)
    own = B.anki_search("tag", old)
    doc = dict(root, deck="Big Step 1",
               units=[{"id": "u1", "name": E.auto_name([old]), "opens": "2026-11-09", "tags": [old], "decks": [], "cards": []},
                      {"id": "u2", "name": "Heart failure", "opens": "2026-11-10", "tags": [], "decks": [], "cards": [],
                       "cut": [{"tag": VID, "in": "t1", "q": q}], "search": [q], "sn": {q: 4}},
                      {"id": "u3", "name": "Antibiotics", "opens": "2026-11-11", "tags": [OTHER], "decks": [], "cards": [],
                       "search": [f"{own} -is:suspended"]}],
               reviews=[{"day": "2026-11-12", "from": "u1", "to": "u2"}],
               remarks=[{"id": "r1", "tag": old, "text": "Skip the last two minutes"}])
    r = E.rename_plan_tag(doc, "t1", "SLG 12b")
    new = P.tag_path(r, r["tags"][0])
    us = {u["id"]: u for u in r["units"]}
    check("plan: a tag renamed: the dates on it, a cut kept to it, a search using it and its note follow; a date named for it too",
          new == "DueCrew::MS2::SLG_12b" and us["u1"]["tags"] == [new] and us["u1"]["name"] == "SLG 12b"
          and us["u2"]["cut"][0]["q"] == B.cut_q(VID, new) and us["u2"]["search"] == [B.cut_q(VID, new)]
          and us["u2"]["sn"] == {B.cut_q(VID, new): 4} and us["u2"]["name"] == "Heart failure"
          and us["u3"]["search"] == [f"{B.anki_search('tag', new)} -is:suspended"] and r["remarks"][0]["tag"] == new, r)
    try:
        E.rename_plan_tag(doc, "t1", " slg  13 ")
        clash = None
    except E.Refused as e:
        clash = str(e)
    check("plan: no two of the plan's tags named alike", clash == "There's a tag called SLG 13 already.", clash)
    say = E.drop_say(doc, "t1")
    check("plan: what deleting a tag does, said first",
          say == "SLG 12 is on 3 dates: Mon 9 Nov, Tue 10 Nov, Wed 11 Nov. Mon 9 Nov has nothing else, so it goes, to-dos too."
          " A tag kept to it there is all of that tag again.", say)
    d = E.delete_plan_tag(doc, "t1")
    us = {u["id"]: u for u in d["units"]}
    check("plan: a tag deleted: a date with nothing else goes (its review day too), a cut is all its tag again, searches and its note go",
          set(us) == {"u2", "u3"} and us["u2"]["tags"] == [VID] and "cut" not in us["u2"] and "search" not in us["u2"]
          and "search" not in us["u3"] and "reviews" not in d and "remarks" not in d and d["tags"] == [root["tags"][1]], d)


def test_plan_text_v393():
    """3.9.3: the builder's Text in Your plans: the plan as text, read back
    the same; Add dates (a new date, a line adding to its own date, an
    event, a cut on one of the plan's tags); Edit the whole plan (a date
    moved or renamed keeps its id, one left out goes, a tag renamed keeps
    its id and its dates follow); what it can't read, a line each."""
    from due_crew.planner import build as B
    from due_crew.planner import text as T
    t = B.Tree([("#Big", 250), ("#Big::#Book", 50), ("#Big::#Videos", 100), ("#Big::#Videos::Cardio", 60),
                ("#Big::#Videos::Pulm", 40), ("Misc", 10)], [("Big Step 1", 260)])
    ids = iter(f"x{i}" for i in range(999))
    doc = {"deck": "Big Step 1", "tagroot": "MS2", "tags": [{"id": "t1", "name": "SLG 12", "notes": ["g1", "g2"]}],
           "events": [{"id": "e1", "day": "2026-11-13", "name": "Cardio quiz"}],
           "units": [{"id": "u1", "name": "Cardio", "opens": "2026-11-09", "due": "2026-11-11", "even": True,
                      "tags": ["#Big::#Videos::Cardio"], "decks": [], "cards": [], "for": "e1",
                      "todo": [{"k": "watch", "t": "Lecture 14"}]},
                     {"id": "u2", "name": "Book", "opens": "2026-11-12", "tags": ["#Big::#Book"], "decks": [], "cards": [["g9", 1]],
                      "search": ["tag:Misc -tag:Misc::x"]}],
           "remarks": [{"id": "r1", "tag": "#Big::#Book", "text": "Read the summary first"}]}
    txt = T.to_text(doc)
    check("text: the plan as text, the builder's: tags, then dates and events by day, then notes",
          txt.split("\n") == ["tag | SLG 12 | notes:g1 g2",
                              "2026-11-09 | Cardio | tag:#Big::#Videos::Cardio | due 2026-11-11 | even | for Cardio quiz | watch: Lecture 14",
                              "2026-11-12 | Book | tag:#Big::#Book | search:tag:Misc -tag:Misc::x | cards:g9:2",
                              "2026-11-13 | event | Cardio quiz",
                              "note | tag:#Big::#Book | Read the summary first"], txt)
    r = T.from_text(doc, t, txt, whole=True, start="2026-11-09", new_id=lambda: next(ids))
    back = T.apply(doc, r, True)
    check("text: read back whole, nothing changes",
          not r["errors"] and E.lean(back) == E.lean(doc) and [u["id"] for u in r["units"]] == ["u1", "u2"], (r["errors"], back))
    add = ("2026-11-16 | Pulm | tag:#big::#videos::pulm | for Cardio quiz\n"
           "2026-11-09 | Cardio | tag:Misc | read: chapter 4\n"
           "week 2 | Cuts | tag:#Big::#Videos::Cardio in SLG 12\n"
           "2026-11-20 | event | Pulm quiz\n"
           "# Pick in Anki: the iron cards\n"
           "# I chose the video over the book")
    r = T.from_text(doc, t, add, start="2026-11-09", new_id=lambda: next(ids))
    us = {u["name"]: u for u in r["units"]}
    check("text: Add dates: a new date (a tag in any case), one adding to its own day and name, an event; picks and notes said",
          not r["errors"] and us["Pulm"]["tags"] == ["#Big::#Videos::Pulm"] and us["Pulm"]["for"] == "e1"
          and us["Cardio"]["id"] == "u1" and us["Cardio"]["tags"] == ["Misc"] and len(r["events"]) == 1
          and r["notes"] == ["Pick in Anki: the iron cards"] and r["why"] == ["I chose the video over the book"], r)
    cut = next(u for u in r["units"] if u.get("cut"))
    check("text: week 2 is the plan's second Monday; a date named by its cut alone reads as it and its plan tag",
          cut["opens"] == "2026-11-16" and cut["name"] == "Cuts" and cut["cut"][0]["in"] == "t1"
          and T.from_text(doc, t, "week 2 | tag:#Big::#Videos::Cardio in SLG 12", start="2026-11-09")["units"][0]["name"]
          == "Cardio · SLG 12", cut)
    added = T.apply(doc, r, False)
    au = {u["id"]: u for u in added["units"]}
    check("text: Add to the plan: a date it names gets its tag and to-do, new ones go on, the cut's search is made",
          au["u1"]["tags"] == ["#Big::#Videos::Cardio", "Misc"] and au["u1"]["todo"][-1] == {"k": "read", "t": "chapter 4"}
          and len(added["units"]) == 4 and [e["name"] for e in added["events"]] == ["Cardio quiz", "Pulm quiz"]
          and B.cut_q("#Big::#Videos::Cardio", "DueCrew::MS2::SLG_12") in au[cut["id"]]["search"], added["units"])
    whole = ("tag | SLG 12b | notes:g1 g2\n"
             "2026-11-10 | Cardio | tag:#Big::#Videos::Cardio | due 2026-11-11 | even | for Cardio quiz\n"
             "2026-11-13 | event | Cardio quiz\n"
             "2026-11-16 | Pulm | tag:#Big::#Videos::Pulm | tag:SLG 12b")
    r = T.from_text(doc, t, whole, whole=True, start="2026-11-09", new_id=lambda: next(ids))
    gu, gt, gr = T.gone(doc, r, True)
    check("text: the whole plan: a date moved keeps its id, one left out goes, a tag with a new name and the same notes is it renamed",
          not r["errors"] and r["units"][0]["id"] == "u1" and [u["id"] for u in gu] == ["u2"] and not gt
          and r["renamed"] == [{"id": "t1", "from": "DueCrew::MS2::SLG_12", "was": "SLG 12"}] and [x["id"] for x in gr] == ["r1"]
          and r["units"][1]["tags"] == ["#Big::#Videos::Pulm", "DueCrew::MS2::SLG_12b"], r)
    rep = T.apply(doc, r, True)
    check("text: Replace the plan's dates: the plan as the text says, the tag renamed",
          [u["id"] for u in rep["units"]] == ["u1", r["units"][1]["id"]] and rep["tags"][0] == {"id": "t1", "name": "SLG 12b", "notes": ["g1", "g2"]}
          and "remarks" not in rep and rep["units"][0]["opens"] == "2026-11-10", rep)
    ren = T.from_text(doc, t, "2026-11-12 | Chapter 5 | tag:#Big::#Book | search:tag:Misc -tag:Misc::x | cards:g9:2", whole=True,
                      start="2026-11-09", new_id=lambda: next(ids))
    check("text: the whole plan: a date with its cards under another name is it renamed",
          ren["units"][0]["id"] == "u2" and ren["units"][0]["name"] == "Chapter 5", ren["units"])
    drop = T.from_text(doc, t, "2026-11-09 | Cardio | tag:#Big::#Videos::Cardio\n2026-11-16 | Own | tag:SLG 12", whole=True,
                       start="2026-11-09", new_id=lambda: next(ids))
    uses = T.using(doc, drop, True)
    check("text: a tag the whole plan leaves out, while a date in it still uses it, says so first",
          [u["name"] for u, _w in uses] == ["Own"] and "nothing else on it" in uses[0][1], uses)
    said = T.take_all(doc, drop, t)
    back, kept = T.keep_tags(doc, "2026-11-16 | Own | tag:SLG 12", T.from_text(doc, t, "2026-11-16 | Own | tag:SLG 12", whole=True,
                                                                               start="2026-11-09"))
    check("text: Take them off those dates too (a date with nothing left goes), or Keep the tags (their lines back in the text)",
          [u["name"] for u in drop["units"]] == ["Cardio"] and said == ["Mon 16 Nov · Own: nothing left on it, so it goes"]
          and back.startswith("tag | SLG 12 | notes:g1 g2\n") and kept == ["SLG 12"], (said, back))
    bad = T.from_text(doc, t, "\n".join(["Cardio | tag:Misc", "2026-11-09 | x | search:is:due tag:Misc",
                                         "2026-11-12 | y | tag:Misc | due 2026-11-10", "2026-11-12 | z | tag:Misc | even",
                                         "2026-11-12 | w | tag:Misc | for Nothing", "2026-11-12 | v | notes:" + "x" * 41,
                                         "2026-11-12 | nothing on it", "note | bad", "tag | SLG 13"]), start="2026-11-09")
    check("text: what it can't read, a line each, in the builder's words",
          [e.split(":")[0] for e in bad["errors"]] == ["Line 1", "Line 2", "Line 3", "Line 4", "Line 6", "Line 7", "Line 8",
                                                      "Line 9", '"for Nothing"']
          and "each person's Anki" in bad["errors"][1] and "before it opens" in bad["errors"][2], bad["errors"])
    miss = T.from_text(doc, t, "2026-11-12 | q | tag:Nope::Here | tag:DueCrew::MS2::New", start="2026-11-09")
    check("text: a tag the deck doesn't have is said (the plan's own aren't till they're made)",
          miss["missing"] == ["tag:Nope::Here"], miss["missing"])


def test_history_and_posts_v393():
    """3.9.3: Your plans' History (every save, the latest one undoable) and
    Updates (a post to followers, five a day; its writer or the owner takes
    it back), against the fake Worker's plans.ts log and posts."""
    store = world({"sam": "Sammy", "dre": "Dre", "kai": "Kai"})
    sam, dre, kai = new_client(store, "sam"), new_client(store, "dre"), new_client(store, "kai")
    pid, _code = store.add_plan("sam", "MS2 Block 2", "Big Step 1", _doc()["units"])
    raw, _plan = R.load(sam, pid)
    R.save(sam, pid, raw["version"], E.rename(raw["doc"], "u1", "HF"), "renamed Mon 9 Nov")
    log = R.log(sam, pid)
    check("history: every save, newest first, the latest one undoable; only an author reads it",
          [x["summary"] for x in log] == ["renamed Mon 9 Nov"] and log[0]["undo"] is True and log[0]["name"] == "Sammy"
          and log[0]["version"] == 2, log)
    try:
        R.log(dre, pid)
        stranger = None
    except Exception as e:  # noqa: BLE001
        stranger = getattr(e, "status", None)
    check("history: not a stranger's", stranger == 403, stranger)
    got = R.post(sam, pid, "  Week 3\nmoved:  Shock is Thursday  ")
    posts = R.posts(sam, pid)
    check("updates: a post, one line, newest first, the owner's to take back",
          got[0] == "saved" and [x["text"] for x in posts] == ["Week 3 moved: Shock is Thursday"] and posts[0]["remove"] is True
          and posts[0]["uid"] == "sam", (got, posts))
    store.follows[(pid, "kai")] = {"share": False, "paused": False, "progress": None, "sched": None}
    check("updates: a follower reads them, can't post or take one back",
          R.posts(kai, pid)[0]["remove"] is False and R.post(kai, pid, "hi")[0] == "refused")
    for i in range(4):
        R.post(sam, pid, f"note {i}")
    over = R.post(sam, pid, "one too many")
    check("updates: five posts a day a plan", over == ("refused", "Five posts a day per plan. Try tomorrow."), over)
    check("updates: taken back", R.unpost(sam, pid, posts[0]["id"]) and len(R.posts(sam, pid)) == 4)
    check("updates: the time a line says, as the builder's",
          M.ago(1000, now=1010) == "just now" and M.ago(1000, now=1000 + 300) == "5 min ago"
          and M.ago(1000, now=1000 + 3 * 3600) == "3 h ago")


def test_settings_edits_v393():
    """3.9.3: the builder's Settings and Progress in Your plans: where to get
    the deck, next year's name and first day, a class's dates behind, and
    Give the class a day."""
    check("settings: a deck link is https, printable, no space or quote, 300 at most",
          E.deck_link("https://example.org/deck?x=1") and not E.deck_link("http://x.org") and not E.deck_link("https://a b")
          and not E.deck_link('https://a"b') and not E.deck_link("https://" + "x" * 293))
    d = E.set_deck_url({"units": []}, " https://example.org/deck ")
    try:
        E.set_deck_url(d, "example.org")
        bad = None
    except E.Refused as e:
        bad = str(e)
    check("settings: the deck link set, refused when it isn't one, taken off empty",
          d["deckUrl"] == "https://example.org/deck" and "https://" in bad and "deckUrl" not in E.set_deck_url(d, ""), bad)
    check("settings: next year's name, as the builder's",
          E.next_year_name("MS2 Block 2") == "MS2 Block 2 (next year)" and E.next_year_name("MS2 Block 2 (copy)") == "MS2 Block 2 (next year)"
          and E.next_year_name("MS2 Block 2 (next year)") == "MS2 Block 2 (next year)"
          and E.next_year_name("A very long plan name that goes on and on past the limit") == "A very long plan name that goes on and on past (next year)"
          and E.first_day({"units": [{"opens": "2026-11-10"}], "events": [{"day": "2026-11-09"}]}) == "2026-11-09")
    doc = {"units": [{"id": "a", "name": "A", "opens": "2026-11-09", "due": "2026-11-10"},
                     {"id": "b", "name": "B", "opens": "2026-11-12", "due": "2026-11-13", "check": "2026-11-14"},
                     {"id": "c", "name": "C", "opens": "2026-11-13"}],
           "reviews": [{"day": "2026-11-14", "from": "a", "to": "b"}], "events": [{"id": "e", "day": "2026-11-15", "name": "Quiz"}]}
    week = [1, 1, 1, 1, 1, 0, 0]
    moved, n = E.breather(doc, "2026-11-11", week)
    us = {u["id"]: u for u in moved["units"]}
    check("progress: Give the class a day: every date still to come one study day later, events where they were",
          n == 2 and us["a"]["opens"] == "2026-11-09" and (us["b"]["opens"], us["b"]["due"], us["b"]["check"]) == ("2026-11-13", "2026-11-14", "2026-11-15")
          and us["c"]["opens"] == "2026-11-16" and moved["reviews"][0]["day"] == "2026-11-16" and moved["events"][0]["day"] == "2026-11-15", moved)
    prog = {"sharing": 4, "units": {"a": {"opened": 4, "done": 1}, "b": {"opened": 4, "done": 3}, "c": {"opened": 0, "done": 0}}}
    late = E.behind(doc, prog, "2026-11-16")
    check("progress: a date most of the class hasn't finished two days after it; fewer than 3 sharing, none",
          [(u["id"], done, days) for u, done, days in late] == [("c", 0, 3), ("a", 1, 6)] and E.behind(doc, dict(prog, sharing=2), "2026-11-16") == [], late)
    two = dict(prog, sharing=2, inSquad=3, units={"a": {"opened": 2, "done": 1}, "c": {"opened": 0, "done": 0}})
    check("progress (3.9.5): an author on the team makes the three; half is of the followers sharing",
          [(u["id"], done) for u, done, _d in E.behind(doc, two, "2026-11-16")] == [("b", 0), ("c", 0)]
          and E.behind(doc, dict(two, sharing=0), "2026-11-16") == [], E.behind(doc, two, "2026-11-16"))
    check("progress (3.9.5, Sam): and two sharing besides me; one besides me, none",
          E.behind(doc, dict(two, others=1), "2026-11-16") == [] and len(E.behind(doc, dict(two, others=2), "2026-11-16")) == 2)


def test_settings_remote_v393():
    """3.9.3: Your plans' Settings and Progress against the fake Worker: the
    name and line, who can follow, co-authors (asked, handed it, taken
    off), the library, a copy for next year, the plan taken down, and its
    squad's counts."""
    store = world({"sam": "Sammy", "dre": "Dre", "kai": "Kai"})
    sam, dre = new_client(store, "sam"), new_client(store, "dre")
    pid, _code = store.add_plan("sam", "MS2 Block 2", "Big Step 1", _doc()["units"])
    raw, _p = R.load(sam, pid)
    got = R.save_meta(sam, pid, raw["version"], {"name": " MS2  Block 2b ", "line": "One a week", "doc": "ignored"}, "renamed it")
    check("settings: the name and line saved, nothing but them",
          got[0] == "saved" and store.plans[pid]["name"] == "MS2 Block 2b" and store.plans[pid]["line"] == "One a week"
          and set([b for m, p, b in store.bodies if m == "PUT" and p == f"/plans/{pid}"][-1]) == {"name", "line", "version", "summary"}, got)
    store.squads["s1"] = {"name": "Study crew", "founder": "sam", "open": False}
    store.members[("s1", "sam")] = {"name": "Sammy", "joined": 1}
    got = R.save_meta(sam, pid, got[1]["version"], {"audience": "squad", "squad": "s1"}, "for one squad")
    check("settings: for one of my squads", got[0] == "saved" and (store.plans[pid]["audience"], store.plans[pid]["squad"]) == ("squad", "s1"), got)
    check("settings: not a squad of mine", R.save_meta(sam, pid, got[1]["version"], {"squad": "nope"}, "x") == ("refused", "That squad isn't one of yours."))
    check("settings: a plan for one squad stays out of the library",
          R.set_listed(sam, pid, True) == ("refused", "Only a plan anyone with the code can follow goes in the library."))
    got = R.save_meta(sam, pid, got[1]["version"], {"audience": "code", "squad": None}, "anyone")
    listed = R.set_listed(sam, pid, True)
    check("settings: in the library, and out", listed[0] == "saved" and listed[1]["listed"] == 1
          and R.set_listed(sam, pid, False)[1]["listed"] == 0)
    store.befriend("sam", "dre")
    store.befriend("dre", "sam")
    store.befriend("sam", "kai")
    check("settings: co-authors come from my crew (mutual)", R.crew(sam) == [("dre", "Dre")], R.crew(sam))
    asked = R.add_editor(sam, pid, "dre")
    check("settings: a co-author asked waits for a yes", asked[0] == "saved" and asked[1]["editors"][0]["pending"] is True, asked)
    check("settings: not one of my crew", R.add_editor(sam, pid, "kai") == ("refused", "Co-authors come from your crew: you add each other."))
    check("settings: only a co-author who said yes can be handed it",
          R.offer(sam, pid, "dre") == ("refused", "Only a co-author who said yes can be handed it."))
    store.plans[pid]["invited"].pop("dre")
    store.plans[pid]["editors"] = {"dre"}
    handed = R.offer(sam, pid, "dre")
    check("settings: handed to a co-author, and taken back", handed[0] == "saved" and handed[1].get("handover") == "dre"
          and "handover" not in R.offer(sam, pid, None)[1])
    check("settings: a co-author leaves", R.remove_editor(dre, pid, "dre") and "dre" not in store.plans[pid]["editors"])
    raw, _p = R.load(sam, pid)
    first = E.first_day(raw["doc"])
    copied = R.copy(sam, pid, E._later(first, 364))
    new = copied[1]
    named = R.save_meta(sam, new["id"], new["version"], {"name": E.next_year_name(raw["name"])}, "named for next year")
    check("settings: Copy for next year: every date 52 weeks on, named for next year",
          copied[0] == "saved" and E.first_day(new["doc"]) == E._later(first, 364) and named[1]["name"] == "MS2 Block 2b (next year)"
          and [u["opens"] for u in new["doc"]["units"]] == [E._later(u["opens"], 364) for u in raw["doc"]["units"]], new["doc"]["units"])
    check("followers' progress isn't read in Anki (round five, Sam's call: their squad is where followers meet)",
          not hasattr(R, "progress"))
    check("settings: only its owner takes it down; then it's gone", not R.delete(dre, pid) and R.delete(sam, pid) and pid not in store.plans)


def test_split_keeps_the_date_v393():
    """3.9.3 review: Split by its tags (takeOut, fill, cleanup) keeps the
    date when the split tag was all on it: its id (followers' progress is
    by it), name, due date, prep, to-dos and review day; its first part
    fills onto it and the rest goes on new dates."""
    from due_crew.planner import build as B
    from due_crew.planner import edits as E
    doc = {"deck": "Big Step 1", "events": [{"id": "e1", "day": "2026-11-13", "name": "Heart quiz"}],
           "reviews": [{"day": "2026-11-12", "from": "h", "to": "h"}],
           "units": [{"id": "h", "name": "Heart week", "opens": "2026-11-06", "due": "2026-11-10", "for": "e1",
                      "todo": [{"k": "read", "t": "Ch 4"}], "tags": ["A"], "decks": []}]}
    items = [{"key": "tag:A::One", "n": 20}, {"key": "tag:A::Two", "n": 25}]
    n = iter(f"n{i}" for i in range(9))
    before = doc
    out = E.take_off(doc, "h", "tags", "A", keep=True)
    B.fill(out, items, "2026-11-06", None, 30, [1, 1, 1, 1, 1, 0, 0], lambda: next(n))
    out = E.name_dates(E.cleanup(out), before)
    h = next((u for u in out["units"] if u["id"] == "h"), None)
    check("split: the date stays, its first part on it, the rest on a new date",
          h is not None and h["tags"] == ["A::One"] and h["name"] == "Heart week" and h["due"] == "2026-11-10"
          and h["for"] == "e1" and h["todo"] == [{"k": "read", "t": "Ch 4"}] and out.get("reviews") == doc["reviews"]
          and [u["tags"] for u in out["units"] if u["id"] != "h"] == [["A::Two"]], out["units"])
    gone = E.cleanup(E.take_off(doc, "h", "tags", "A", keep=True))
    check("split: a date nothing filled goes after all, with its review day", gone["units"] == [] and "reviews" not in gone)


def test_text_review_fixes_v393():
    """3.9.3 review: Text reads a day that isn't one as a line's error (not a
    crash later), cuts names as the Worker counts them (UTF-16: an emoji is
    two), and an old checkpoint is a review day as the builder loads it."""
    from due_crew.planner import edits as E
    from due_crew.planner import text as T
    import itertools
    ids = itertools.count()
    doc = {"deck": "Big Step 1", "units": []}
    got = T.from_text(doc, None, "2026-02-31 | Heart | tag:A\n2026-11-02 | Lungs | tag:B | due 2026-11-31\n"
                                 "2026-02-30 | event | Quiz", whole=False, start="2026-11-02", new_id=lambda: f"n{next(ids)}")
    check("text: a day that isn't one is a line's error",
          [e for e in got["errors"] if "isn't a day on the calendar" in e] == [
              "Line 1: 2026-02-31 isn't a day on the calendar.", "Line 2: 2026-11-31 isn't a day on the calendar.",
              "Line 3: 2026-02-30 isn't a day on the calendar."] and not got["units"] and not got["events"], got["errors"])
    emoji = "\U0001F600" * 35
    got = T.from_text(doc, None, f"2026-11-02 | event | {emoji}\n2026-11-03 | {emoji} | tag:A", whole=False,
                      start="2026-11-02", new_id=lambda: f"n{next(ids)}")
    ev, un = (got["events"] or [{}])[0], (got["units"] or [{}])[0]
    check("text: names cut to 60 as the Worker counts, an emoji whole",
          len(ev.get("name", "")) == 30 and T._u16(ev["name"]) == 60 and T._u16(un.get("name") or un.get("key") or "") <= 60
          and any("cut to 60" in w for w in got["warns"]), (len(ev.get("name", "")), got["warns"]))
    old = {"units": [{"id": "a", "opens": "2026-11-02", "check": "2026-11-06", "tags": ["A"]}], "reviews": [{"day": "2026-11-09", "from": "a", "to": "a"}]}
    mig = E.migrate_checks(old)
    check("text: an old checkpoint is a review day (builder.js on load), the doc left as it was",
          "check" not in mig["units"][0] and mig["reviews"][-1] == {"day": "2026-11-06", "from": "a", "to": "a"}
          and old["units"][0]["check"] == "2026-11-06" and E.migrate_checks(mig) is mig)


def test_pick_note_twin_v393():
    """3.9.3: Read it's "To pick in Anki:" line says "Pick in Anki" once, its
    date kept: text.pick_note and builder.js's pickNote, the same."""
    import shutil
    import subprocess
    from due_crew.planner.text import pick_note
    cases = ["Pick in Anki: the two shock cases", "pick in anki for 2026-10-06: the iron cards", "the iron cards",
             "Pick in Ankifoo", "Pick in Anki", "  PICK IN ANKI  for 2026-01-02 : x"]
    want = ["the two shock cases", "2026-10-06: the iron cards", "the iron cards", "Pick in Ankifoo", "Pick in Anki", "2026-01-02 : x"]
    check("pick note: the words once, its date kept", [pick_note(c) for c in cases] == want, [pick_note(c) for c in cases])
    node = shutil.which("node")
    line = re.search(r"^\s*const pickNote = .*;$", open(os.path.join(REPO, "site", "public", "builder.js")).read(), re.M)
    if not node or not line:
        check("pick note: builder.js has pickNote", bool(line))
        return
    got = subprocess.run([node, "-e", line.group(0) + f"\nconsole.log(JSON.stringify({json.dumps(cases)}.map(pickNote)))"],
                         capture_output=True, text=True, timeout=30)
    check("pick note: builder.js's pickNote says the same", got.returncode == 0 and json.loads(got.stdout) == want, got.stdout + got.stderr)


def test_day_notes_v393():
    """3.9.3: notes on a day in Your plans against the fake Worker (plans.ts
    notes): anyone in the plan writes one, a stranger gets nothing, its
    writer or an author takes it off, and on a plan in the library only its
    authors write (and a stranger's older note isn't shown)."""
    store = world({"sam": "Sammy", "dre": "Dre", "kai": "Kai", "lee": "Lee"})
    sam, kai, lee = new_client(store, "sam"), new_client(store, "kai"), new_client(store, "lee")
    pid, _code = store.add_plan("sam", "MS2 Block 2", "Big Step 1", _doc()["units"])
    store.follows[(pid, "kai")] = {"share": False, "paused": False, "sched": None, "progress": None}
    mine = R.add_note(sam, pid, "2026-10-20", "  Lab day,  keep it light ")
    theirs = R.add_note(kai, pid, "2026-10-20", "Room 4B?")
    check("notes: an author's and a follower's, one line each",
          mine[0] == "saved" and mine[1]["text"] == "Lab day, keep it light" and theirs[0] == "saved"
          and [(x["name"], x["text"], x["mine"], x["remove"]) for x in R.notes(kai, pid)]
          == [("Sammy", "Lab day, keep it light", False, False), ("Kai", "Room 4B?", True, True)])
    check("notes: an author takes any off", [x["remove"] for x in R.notes(sam, pid)] == [True, True])
    try:
        R.notes(lee, pid)
        stranger = False
    except Exception:  # noqa: BLE001 (a 404, as no plan)
        stranger = True
    check("notes: a stranger reads none and writes none",
          stranger and R.add_note(lee, pid, "2026-10-20", "hi")[0] == "refused")
    check("notes: a follower can't take an author's off", R.remove_note(kai, pid, mine[1]["id"])
          and len(R.notes(sam, pid)) == 2)
    check("notes: its writer takes it off", R.remove_note(kai, pid, theirs[1]["id"]) and len(R.notes(sam, pid)) == 1)
    check("notes: one line, 280 at most", R.add_note(sam, pid, "2026-10-21", "   ") == ("refused", "A note is one line, 280 characters at most.")
          and R.add_note(sam, pid, "Tuesday", "x")[0] == "refused")
    R.add_note(kai, pid, "2026-10-21", "Before it was listed")
    store.plans[pid]["listed"] = 1
    check("notes: in the library, only its authors write, and a follower's own still shows to them",
          R.add_note(kai, pid, "2026-10-22", "x") == ("refused", "On a plan in the library, only its authors write notes.")
          and R.add_note(sam, pid, "2026-10-22", "Quiz moved")[0] == "saved"
          and [x["text"] for x in R.notes(kai, pid)] == ["Lab day, keep it light", "Before it was listed", "Quiz moved"])
    store.follows[(pid, "lee")] = {"share": False, "paused": False, "sched": None, "progress": None}
    check("notes: in the library, a stranger's note isn't shown to anyone else",
          [x["text"] for x in R.notes(lee, pid)] == ["Lab day, keep it light", "Quiz moved"])
    check("notes: they go with the plan", R.delete(sam, pid) and not store.plan_notes)


def test_lay_out_review_fixes_v393():
    """3.9.3's review of Lay it out: one autoName and renameAll (a cut's
    name follows its plan tag, a tag with a date below it reads "· the
    rest", a name typed stays); placed keys looked up, not scanned; the
    pace the server keeps (5,000 a day, 500 ticks); a day over the pace
    that isn't past; "²" is no card number; a cut's search once; Fill's
    words."""
    import itertools
    from due_crew.planner import build as B
    root = {"tagroot": "MS2", "tags": [{"id": "t1", "name": "SLG 12"}]}
    ptag = P.tag_path(root, root["tags"][0])
    q = B.cut_q(VID, ptag)
    t = B.Tree([(VID, 9), (VID + "::Extra", 2), (BOOK, 5), ("A", 10), ("A::One", 4)], [])
    doc = dict(root, deck="Big Step 1", units=[
        {"id": "u1", "name": "Heart Failure · SLG 12", "opens": "2026-11-09", "tags": [], "decks": [], "cards": [],
         "cut": [{"tag": VID, "in": "t1", "q": q}], "search": [q]},
        {"id": "u2", "name": "A", "opens": "2026-11-10", "tags": ["A"], "decks": [], "cards": []},
        {"id": "u3", "name": "My own name", "opens": "2026-11-11", "tags": [BOOK], "decks": [], "cards": []}])
    placed = B.placed_keys(doc, t)
    check("names: autoName with a cut is the cut's (Heart Failure · SLG 12), a date's first tag read as the site reads it",
          B.auto_name(doc, t, doc["units"][0], placed) == "Heart Failure · SLG 12"
          and B.auto_name(doc, t, doc["units"][1], placed) == "A" and B.tag_word("Heart_Failure") == "Heart Failure")
    r = E.rename_plan_tag(doc, "t1", "Unit 12")
    check("names: a plan tag renamed, the date named for its cut follows it; one named by hand doesn't",
          r["units"][0]["name"] == "Heart Failure · Unit 12" and r["units"][2]["name"] == "My own name", r["units"])
    more = E.name_dates(dict(doc, units=doc["units"] + [{"id": "u4", "name": "One", "opens": "2026-11-12", "tags": ["A::One"],
                                                         "decks": [], "cards": []}]), doc, t)
    check("names: a tag with a date below it reads \"· the rest\" (renameAll, every date named for what's on it)",
          [u["name"] for u in more["units"]] == ["Heart Failure · SLG 12", "A · the rest", "My own name", "One"], more["units"])
    typed = E.name_dates(E.rename(doc, "u2", "Week one"), doc, t)
    check("names: a name this change typed stays (nameIt), and one left blank is named again",
          typed["units"][1]["name"] == "Week one"
          and E.name_dates(dict(doc, units=[dict(doc["units"][1], name="")]), doc, t)["units"][0]["name"] == "A", typed["units"])
    rng = random.Random(7)
    paths = ["A", "A::B", "A::B::C", "a::b::d", "X", "X::Y", "A:", "A:::B", "Q::R::S::T"]
    keys = [f"{k}:{p}" for k in ("tag", "deck") for p in paths]
    same = True
    for _ in range(300):
        pl = set(rng.sample(keys, rng.randint(0, 6)))
        fast = B.Placed(pl)
        for key in keys:
            slow_is = key in pl or any(B.under(p, key) for p in pl)
            below = [p for p in pl if B.under(key, p)]
            slow_below = sorted(p for p in below if not any(x != p and B.under(x, p) for x in below))
            same = same and B.is_placed(key, fast) == slow_is == B.is_placed(key, pl) \
                and sorted(B.placed_below(key, fast)) == slow_below == sorted(B.placed_below(key, pl))
    check("placed: looked up by what's above and below, the same as scanning every placed key", same)
    check("placed: a tag kept without its extras is on the calendar (the tree's map, worked out once)",
          "tag:" + VID in B.placed_keys({"units": [{"id": "x", "opens": "2026-11-09", "search": [B.without_q(VID, [VID + "::Extra"])]}]}, t)
          and t.extras() is t.extras())
    big = B.Tree([("Big", 30000)], [])
    lay = {"units": [], "end": "2026-11-13"}
    ids = itertools.count()
    r = B.lay_out(lay, big, {"mode": "end", "days": [1] * 7}, {"tag:Big"}, "2026-11-09", "2026-11-01", lambda: f"n{next(ids)}")
    check("pace: 30,000 cards in 5 days fills at more than the server keeps; the pace saved is 5,000 at most",
          r["daily"] > 5000 and E.set_pace({}, "end", [1] * 7, r["daily"])["pace"]["daily"] == 5000, r)
    hv_doc = {"units": [{"id": "a", "name": "A", "opens": "2026-09-07"}, {"id": "m", "name": "M", "opens": "2026-09-08"},
                        {"id": "b", "name": "B", "opens": "2026-11-09"}]}
    tot = {"a": 400, "m": 0, "b": 300}
    past = B.heavy(hv_doc, big, {"mode": "daily", "days": [1] * 7, "daily": 20}, set(), "2026-09-07", lambda u: tot[u["id"]])
    now = B.heavy(hv_doc, big, {"mode": "daily", "days": [1] * 7, "daily": 20}, set(), "2026-09-07", lambda u: tot[u["id"]], "2026-10-19")
    check("heavy: the first day over the pace that isn't past (a plan that's been running doesn't say September)",
          past["a"] == "2026-09-07" and now["a"] == "2026-11-09" and now["unit"]["id"] == "b", (past, now))
    check("picks: \"²\" is a digit but no card number: a bad token, not a crash",
          B.picks_take("cards:g1:² g2:3")["cards"] == [["g2", 2]] and B.picks_take("cards:g1:²")["bad"] == ["g1:²"])
    once = E.set_cut(dict(doc, units=[dict(doc["units"][1], tags=[VID], search=[q])]), "u2", VID, "t1")
    check("cut: a date that has the cut's search already keeps it once (addSearch)",
          once["units"][0]["search"] == [q] and once["units"][0]["cut"][0]["q"] == q, once["units"])
    check("fill: its words, one day or from one to another, a card or cards",
          B.put_words(1, "Mon 9 Nov", "Mon 9 Nov") == "Put 1 card on Mon 9 Nov."
          and B.put_words(1500, "Mon 9 Nov", "Fri 13 Nov") == "Put 1,500 cards from Mon 9 Nov to Fri 13 Nov.")
    import json
    import shutil
    import subprocess
    node = shutil.which("node")
    line = re.search(r"^\s*const putWords = .*;$", open(os.path.join(REPO, "site", "public", "builder.js")).read(), re.M)
    cases = [[1, "Mon 9 Nov", "Mon 9 Nov"], [2, "Mon 9 Nov", "Mon 9 Nov"], [1500, "Mon 9 Nov", "Fri 13 Nov"], [0, "a", "b"]]
    if not node or not line:
        check("fill: builder.js has putWords", bool(line))
        return
    got = subprocess.run([node, "-e", line.group(0) + f"\nconsole.log(JSON.stringify({json.dumps(cases)}.map((c) => putWords(...c))))"],
                         capture_output=True, text=True, timeout=30)
    check("fill: builder.js's putWords says the same (put_words)",
          got.returncode == 0 and json.loads(got.stdout) == [B.put_words(*c) for c in cases], got.stdout + got.stderr)


# ---- round five: the AI hooks (ai.py) and Your AI app (mcp.py, the shim) ----

def _ai_plan():
    """A plan, its deck's tree and its ctx: three dates (one with picked notes), a quiz, nothing sent."""
    from due_crew.planner import build as B
    from due_crew.planner import ops as O
    doc = {"deck": "Big Step 1", "units": [
        {"id": "u1", "name": "Shock", "opens": "2026-10-21", "tags": ["Cardio::Shock"], "decks": [], "cards": []},
        {"id": "u2", "name": "Valve disease", "opens": "2026-10-22", "tags": [], "decks": [], "cards": [],
         "notes": ["Gq7#mN2pLx", "Zr4!tW8bYc"]},
        {"id": "u3", "name": "Heart failure", "opens": "2026-10-26", "tags": ["Cardio::HF"], "decks": [], "cards": [],
         "for": "e1"}],
        "events": [{"id": "e1", "day": "2026-10-28", "name": "Cardio quiz"}]}
    tree = B.Tree([("Cardio", 30), ("Cardio::Shock", 10), ("Cardio::Valves", 8), ("Cardio::Valves::Valve_disease", 8),
                   ("Cardio::HF", 12), ("Renal", 5)], [("Big Step 1", 35)])
    return doc, tree, O.Ctx(tree, "2026-10-20", "MS2 Block 2")


def _keys(v, out=None):
    """Every key anywhere in a request."""
    out = set() if out is None else out
    if isinstance(v, dict):
        for k, x in v.items():
            out.add(k)
            _keys(x, out)
    elif isinstance(v, list):
        for x in v:
            _keys(x, out)
    return out


def test_ai_jobs():
    from due_crew.planner import ai, claude
    from due_crew.planner import ops as O
    from due_crew.planner import prompts as PR
    doc, tree, _ctx = _ai_plan()
    vocab = ai.vocabulary()
    check("ai: every op the registry has is in the vocabulary, and nothing else, each with what it does, its fields and an example",
          sorted(v["op"] for v in vocab) == sorted(O.REG) == sorted(ai.VOCAB)
          and all(v["does"] and v["example"]["op"] == v["op"] for v in vocab)
          and all(set(v["example"]) - {"op"} <= set(v["fields"]) for v in vocab),
          sorted(set(O.REG) ^ set(ai.VOCAB)))
    from due_crew.planner import build as B
    ex_doc = {"deck": "Big Step 1", "tagroot": "MS2", "end": "2026-12-18", "units": [
        {"id": "u1", "name": "Shock", "opens": "2026-10-22", "tags": ["Cardio::Shock", "Cardio::Valves"], "decks": [], "cards": [],
         "due": "2026-10-24"},
        {"id": "u2", "name": "Heart failure", "opens": "2026-10-26", "tags": ["Cardio::HF"], "decks": [], "cards": []}],
        "events": [{"id": "e1", "day": "2026-10-30", "name": "Cardio quiz"}], "tags": [{"id": "t1", "name": "SLG 12", "notes": ["g1"]}],
        "remarks": [{"id": "r7Kd2pQa", "tag": "Cardio::Shock", "text": "Watch the second half"}]}
    ex_tree = B.Tree([("Cardio", 40), ("Cardio::Shock", 10), ("Cardio::Shock::Extra", 2), ("Cardio::HF", 12), ("Cardio::Valves", 8),
                      ("Pharm::Pressors", 4)],
                     [("Big Step 1", 44)])
    wrong = []
    for v in vocab:
        try:
            O.apply(ex_doc, O.check(ex_doc, v["example"]), O.Ctx(ex_tree, "2026-10-20", "MS2", [1, 1, 1, 1, 1, 0, 0]))
        except Exception as e:
            wrong.append((v["op"], str(e)))
    check("ai: every op's example goes on a plan it reads as (an AI copies them)", not wrong, wrong)
    check("ai: what Your plans works out from the deck (Split by its tags) isn't offered to an AI",
          "split_tags" not in [v["op"] for v in ai.vocabulary(for_ai=True)] and len(ai.vocabulary(for_ai=True)) == len(vocab) - 1)
    reqs = {}
    for job in ai.JOBS:
        reqs[job] = ai.request_for(job, doc, tree, "MS2 Block 2", "2026-10-20", said="push everything after the quiz a day",
                                   ref={"pick": "u2", "scope": "Cardio quiz"}.get(job), text="Oct 26 heart failure")
    check("ai: a request is its job, its shape's version and its input; each job's own inputs, only keys it knows",
          all(set(r) == {"job", "v", "input"} and r["v"] == ai.V and set(r["input"]) <= set(ai.JOBS[j].inputs)
              and _keys(r["input"]) <= ai.KEYS and not {k.lower() for k in _keys(r["input"])} & ai.NEVER
              for j, r in reqs.items()), {j: sorted(_keys(r["input"]) - ai.KEYS) for j, r in reqs.items()})
    blob = json.dumps(reqs)
    check("ai: a date's picked notes go as a count, never their IDs; no person, no email",
          "Gq7#mN2pLx" not in blob and "2 picked notes" in blob and "@" not in blob)
    refused = []
    for key in ("fields", "question", "answer", "Front", "notes", "cids", "email"):
        try:
            ai.request("pick", date={"id": "u1", "name": "Shock", key: "the card's text"}, tags=[])
        except ai.NotSent as e:
            refused.append(str(e))
    try:
        ai.request("words", said="x", cards=[[1, 2]])
    except ai.NotSent as e:
        refused.append(str(e))
    try:
        ai.request("check", plan={"name": "x", "dates": [{"id": "u1", "html": "<b>x</b>"}]})
    except ai.NotSent as e:
        refused.append(str(e))
    check("ai: a request refuses anything shaped like card text, an id or a person, anywhere in it, and an input its job isn't sent",
          len(refused) == 9 and all(r for r in refused) and "card text" in refused[0], refused)
    said = ai.request("calendar", today="2026-10-20", text="Questions to dr.lee@school.edu\nOct 26 shock")["input"]["text"]
    check("ai: an email in the author's words goes as [email]", "school.edu" not in said and "[email]" in said, said)
    check("ai: plain rules first: Suggest puts the tag a date's name names, the exam's weeks and the calendar's lines are read",
          ai.plain_pick(doc, tree, "u2") == [{"op": "add_cards", "date": "u2", "tags": ["Cardio::Valves::Valve_disease"]}]
          and ai.plain_scope(doc, "Cardio quiz", "weeks 1", "2026-10-20")[0] == [
              {"op": "set_for", "date": "u1", "event": "e1"}, {"op": "set_for", "date": "u2", "event": "e1"}]
          and [s["title"] for s in ai.plain_calendar("Mon 10/26 Heart failure\nTue 10/27 Valves", "2026-10-20")] == ["Heart failure", "Valves"])
    check("ai: pick is sent the date and the deck's paths it could take, with their counts (names and counts only)",
          reqs["pick"]["input"]["date"]["id"] == "u2" and {"path": "tag:Cardio::Valves::Valve_disease", "n": 8} in reqs["pick"]["input"]["tags"]
          and all(set(t) == {"path", "n"} for t in reqs["pick"]["input"]["tags"]), reqs["pick"]["input"])
    check("ai: runners: the stand-in only with labs on, Claude not connected yet, your own AI always, Off otherwise",
          isinstance(ai.runner_for(False, "standin"), ai.Off) and isinstance(ai.runner_for(True, "standin"), ai.StandIn)
          and ai.Claude().available() == (False, "Claude isn't connected yet.") and ai.OwnAI().available()[0]
          and isinstance(ai.runner_for(True, None), ai.Off) and ai.StandIn().available() == (True, claude.StandIn().status()))
    told = []
    ai.Claude().run(reqs["words"], lambda a, w: told.append((a, w)))
    ai.StandIn().run(reqs["words"], lambda a, w: told.append((a, w)))
    check("ai: Claude answers nothing yet; the stand-in says which jobs it does", told[0] == (None, "Claude isn't connected yet.")
          and told[1][0] is None and "your own AI" in told[1][1], told)
    own = ai.OwnAI()
    words = own.prompt("words", doc, tree, "MS2 Block 2", "2026-10-20", "push everything after the quiz a day")
    check("ai: your own AI's prompt for my words lists every op an AI writes, the plan by date id, my words, and asks for JSON",
          all(f"- {v['op']}:" in words for v in ai.vocabulary(for_ai=True)) and "- split_tags:" not in words
          and "u3 | 2026-10-26 | Heart failure | tag:Cardio::HF | 12 cards | for Cardio quiz" in words
          and "push everything after the quiz a day" in words and '{"ops": [' in words and "Gq7#mN2pLx" not in words, words[:400])
    planned = own.prompt("plan", doc, tree, "MS2 Block 2", "2026-10-20", "My syllabus: week 1 is shock.")
    check("ai: Plan the dates' prompt is prompts.py's, my words in its edit space",
          planned == PR.for_plan(doc, tree, "MS2 Block 2", "2026-10-21").replace(
              "(edit this part):\n\n", "(edit this part):\nMy syllabus: week 1 is shock.\n", 1) and "My syllabus" in planned)
    src = {f: open(os.path.join(REPO, "due_crew", "planner", f)).read() for f in ("ai.py", "mcp.py", "mcp_shim.py")}
    check("ai: the AI hooks and the AI app's server import no aqt, and the hooks send nothing",
          not [f for f, t in src.items() if re.search(r"^\s*(from aqt|import aqt)", t, re.M)]
          and not re.search(r"^\s*(?:from|import)\s+(?:requests|urllib|http|socket|anthropic)\b", src["ai.py"], re.M))


def test_ai_answers():
    from due_crew.planner import ai
    from due_crew.planner import ops as O
    doc, tree, ctx = _ai_plan()
    before = json.dumps(doc, sort_keys=True)
    answer = {"ops": [{"op": "move", "date": "u1", "to": "2026-10-23", "bogus": 1, "seed": 7},
                      {"op": "fly", "date": "u1"},
                      {"op": "move", "date": "Nope", "to": "2026-10-23"},
                      {"op": "move_from", "date": "2026-10-26 Heart failure", "days": 1},
                      {"op": "set_for", "date": "u3", "event": "Cardio quiz"}],
              "say": "Shock a day later"}
    ops, refused = ai.answer_ops("words", answer, doc, ctx)
    check("ai: an answer's good ops kept in order, checked (refs made ids), unknown fields stripped",
          [(o["op"], o["date"]) for o in ops] == [("move", "u1"), ("move_from", "u3")]
          and "bogus" not in ops[0] and ops[0]["seed"] != 7, ops)
    check("ai: an op nobody knows, one naming a date that isn't there and one that changes nothing are each said, never applied",
          [w for _o, w in refused] == ["There's no change called fly.", "No date on the plan is Nope.",
                                      "Nothing to change: the plan has that already."]
          and json.dumps(doc, sort_keys=True) == before, refused)
    many = [{"op": "rename", "date": "u1", "name": f"Shock {i}"} for i in range(O.OPS_MAX + 5)]
    ops, refused = ai.answer_ops("words", {"ops": many}, doc, ctx)
    check("ai: OPS_MAX changes at most; the rest said, not tried",
          len(ops) == O.OPS_MAX and len(refused) == 5 and all("wasn't tried" in w for _o, w in refused), (len(ops), refused[:1]))
    pasted = ("Here's the change:\n```json\n{\"ops\": [{\"op\": \"move\", \"date\": \"u1\", \"to\": \"2026-10-23\"}], "
              "\"say\": \"Shock a day later\"}\n```\nAnything else?")
    read = ai.OwnAI.read(pasted)
    check("ai: a pasted answer's JSON is read out of its code fence and the words around it; a bare list is its ops; none is None",
          read == {"ops": [{"op": "move", "date": "u1", "to": "2026-10-23"}], "say": "Shock a day later"}
          and ai.OwnAI.read('[{"op": "move", "date": "u1", "to": "2026-10-23"}]') == {"ops": [{"op": "move", "date": "u1", "to": "2026-10-23"}]}
          and ai.OwnAI.read("Sorry, I can't help with that.") is None and ai.say_of(read) == "Shock a day later")
    ops, refused = ai.answer_ops("words", pasted, doc, ctx)
    check("ai: a pasted answer goes through the same checks", [o["op"] for o in ops] == ["move"] and not refused)
    req = ai.request_for("pick", doc, tree, ref="u2")
    ops, refused = ai.answer_ops("pick", {"tags": ["tag:Cardio::Valves::Valve_disease", "tag:Renal::Made_up"]}, doc, ctx, req)
    check("ai: a pick keeps to the paths it was given: an invented one is said, the rest go on the date it was asked about",
          [(o["op"], o["date"], o["tags"]) for o in ops] == [("add_cards", "u2", ["Cardio::Valves::Valve_disease"])]
          and refused and "Renal::Made_up" in refused[0][1], (ops, refused))
    ops, refused = ai.answer_ops("pick", {"ops": [{"op": "add_cards", "date": "u1", "tags": ["Cardio::Valves"]}]}, doc, ctx, req)
    check("ai: a pick for another date is refused", not ops and refused[0][1] == "That's not the date it was asked about.")
    sreq = ai.request_for("scope", doc, tree, ref="Cardio quiz", said="the shock lecture")
    got = []
    ai.StandIn().run(sreq, lambda a, w: got.append(a))
    ops, refused = ai.answer_ops("scope", got[0], doc, ctx, sreq)
    check("ai: the stand-in's scope (its rules, said as its) becomes set_for on the quiz it was asked about",
          [(o["op"], o["date"], o["event"]) for o in ops] == [("set_for", "u1", "e1")] and "stand-in" in got[0]["say"], (got, ops))
    ops, refused = ai.answer_ops("scope", {"dates": ["u1", "zz"]}, doc, ctx, sreq)
    check("ai: a scope's date it wasn't given is refused", len(ops) == 1 and "zz" in refused[0][1], refused)
    ops, refused = ai.answer_ops("plan", "```\n2026-10-30 | Renal | tag:Renal\n# Renal's whole tag fits.\n```", doc, ctx)
    check("ai: Plan the dates' answer is plan lines: one text op, added (the whole plan only when asked)",
          [(o["op"], o["mode"]) for o in ops] == [("text", "add")] and not refused, (ops, refused))
    whole = ai.request_for("plan", doc, tree, whole=True)
    ops, refused = ai.answer_ops("plan", {"text": "2026-10-30 | Renal | tag:Renal"}, doc, ctx, whole)
    check("ai: ...and in the whole plan's place when the request said so", [o["mode"] for o in ops] == ["replace"], (ops, refused))
    ops, refused = ai.answer_ops("calendar", {"sessions": [
        {"date": "2026-10-29", "kind": "lecture", "title": "Arrhythmias"}, {"date": "2026-11-02", "kind": "exam", "title": "Cardio exam"},
        {"date": "not a day", "title": "x"}, {"date": "2026-10-30", "title": "Fall break"}]}, doc, ctx)
    check("ai: a calendar's sessions on a plan: a date for a lecture, an event for an exam; a bad day and a break left out",
          [(o["op"], o["day"], o["name"]) for o in ops] == [("add_date", "2026-10-29", "Arrhythmias"),
                                                           ("add_event", "2026-11-02", "Cardio exam")], ops)
    check("ai: check makes no changes; its lines are the # lines, or the notes",
          ai.answer_ops("check", {"notes": ["x"]}, doc, ctx) == ([], [])
          and ai.check_notes("# Problem: Shock opens after the quiz\n# Tradeoff: two videos on one day\nfine") ==
          ["Problem: Shock opens after the quiz", "Tradeoff: two videos on one day"]
          and ai.check_notes({"notes": ["  one  ", ""]}) == ["one"])
    check("ai: an answer with nothing in it is said", ai.answer_ops("words", {"say": "done"}, doc, ctx)[1][0][1]
          == "That answer has no changes in it.")


class _FakeMcpHost:
    """mcp.Server's host, as mcp_host.Host is in Anki: my plans, a plan,
    the deck's tree, today, the drafts kept as their JSON (a fresh Draft each
    read, as plan_drafts.json gives one), and who heard of a change."""

    def __init__(self, plans, raws, tree, today):
        self._plans, self.raws, self._tree, self._today = plans, raws, tree, today
        self.drafts, self.heard, self.calls, self.refuse_keeps, self.gone = {}, [], [], 0, False

    def live(self):
        if self.gone:
            from due_crew.planner import mcp
            raise mcp.Unavailable("Anki changed profile or account. Try again.")

    def plans(self):
        self.calls.append("plans")
        return json.loads(json.dumps(self._plans))

    def plan(self, pid):
        self.calls.append(("plan", pid))
        return json.loads(json.dumps(self.raws[pid]))

    def tree(self, pid):
        return self._tree

    def today(self):
        return self._today

    def draft(self, pid):
        from due_crew.planner.draft import Draft
        data = self.drafts.get(pid)
        return Draft.from_json(pid, json.loads(data)) if data else None

    def keep_draft(self, pid, d):
        if self.refuse_keeps:
            self.refuse_keeps -= 1
            return False  # Your plans changed it meanwhile
        self.drafts[pid] = json.dumps(d.to_json()) if d is not None and len(d) else None
        return True

    def changed(self, pid):
        self.heard.append(pid)


def _mcp_post(port, body, token="t0k3n-for-tests", host=None, origin=None, raw=None, path="/mcp", method="POST"):
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if host is not None:
        headers["Host"] = host
    if origin is not None:
        headers["Origin"] = origin
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    conn.request(method, path, body=data, headers=headers)
    r = conn.getresponse()
    text = r.read()
    conn.close()
    return r.status, (json.loads(text) if text else None)


def _mcp_big(port, n):
    """A POST that says it's n bytes: the status, its body never sent."""
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    conn.putrequest("POST", "/mcp")
    for k, v in (("Content-Type", "application/json"), ("Authorization", "Bearer t0k3n-for-tests"), ("Content-Length", str(n))):
        conn.putheader(k, v)
    conn.endheaders()
    status = conn.getresponse().status
    conn.close()
    return status


def _mcp_world():
    from due_crew.planner import mcp
    doc, tree, _ctx = _ai_plan()
    plans = [{"id": "p1", "name": "MS2 Block 2", "role": "owner", "followers": 14, "ownerName": "Sammy"},
             {"id": "p2", "name": "Dre's renal", "role": "follower", "followers": 3, "ownerName": "Dre"}]
    raws = {"p1": {"id": "p1", "name": "MS2 Block 2", "role": "owner", "version": 4, "doc": doc},
            "p2": {"id": "p2", "name": "Dre's renal", "role": "follower", "version": 9, "doc": dict(doc)}}
    host = _FakeMcpHost(plans, raws, tree, "2026-10-20")
    return host, mcp.Server(host, "t0k3n-for-tests", 0, cache_secs=0).start()


def _tool(port, name, args, mid=1):
    status, got = _mcp_post(port, {"jsonrpc": "2.0", "id": mid, "method": "tools/call", "params": {"name": name, "arguments": args}})
    res = (got or {}).get("result") or {}
    return status, res, res.get("structuredContent")


def test_mcp_server():
    import contextlib
    import io
    from due_crew.planner import mcp
    host, srv = _mcp_world()
    port = srv.port
    said = io.StringIO()

    class Tee:  # what the server prints, kept; the checks' own lines still shown
        def __init__(self, real):
            self.real = real

        def write(self, x):
            said.write(x)
            return self.real.write(x)

        def flush(self):
            self.real.flush()
    try:
        with contextlib.redirect_stdout(Tee(sys.stdout)), contextlib.redirect_stderr(Tee(sys.stderr)):
            status, got = _mcp_post(port, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}})
            res = got["result"]
            check("mcp: initialize echoes a version it speaks, names itself with the add-on's version, offers tools",
                  status == 200 and res["protocolVersion"] == "2025-03-26" and res["serverInfo"] == {"name": "due-crew", "version": mcp.version()}
                  and res["capabilities"] == {"tools": {}} and "Nothing is sent from here" in res["instructions"] and mcp.version(), got)
            got = _mcp_post(port, {"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}})[1]
            check("mcp: ...and its newest for one it doesn't", got["result"]["protocolVersion"] == mcp.PROTOCOLS[0])
            status, got = _mcp_post(port, {"jsonrpc": "2.0", "method": "notifications/initialized"})
            check("mcp: a notification gets 202 and no body", status == 202 and got is None, (status, got))
            status, got = _mcp_post(port, {"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
            tools = {t["name"]: t for t in got["result"]["tools"]}
            check("mcp: tools/list: the six tools, each with its input's JSON Schema and words",
                  sorted(tools) == ["add_to_changes", "deck_tags", "list_plans", "ops_vocabulary", "preview_changes", "read_plan"]
                  and all(t["inputSchema"]["type"] == "object" and t["description"] for t in tools.values()), sorted(tools))
            _s, res, data = _tool(port, "list_plans", {})
            check("mcp: list_plans: mine with my role and how many follow, the ones I follow by id and name; no one's name",
                  data == {"authored": [{"id": "p1", "name": "MS2 Block 2", "role": "owner", "followers": 14}],
                           "following": [{"id": "p2", "name": "Dre's renal"}]} and "Sammy" not in json.dumps(res), data)
            _s, res, data = _tool(port, "read_plan", {"plan": "ms2 block 2"})
            check("mcp: read_plan (by name too): its text, its dates by id with cards, sources and the quiz each preps for",
                  data["id"] == "p1" and "2026-10-26 | Heart failure | tag:Cardio::HF | for Cardio quiz" in data["text"]
                  and data["dates"][2] == {"id": "u3", "day": "2026-10-26", "name": "Heart failure", "cards": 12,
                                           "sources": ["tag:Cardio::HF"], "tested_on": {"id": "e1", "day": "2026-10-28", "name": "Cardio quiz"}}
                  and data["dates"][1]["sources"] == ["2 picked notes"] and data["events"][0]["id"] == "e1"
                  and data["waiting"] == [] and json.loads(res["content"][0]["text"]) == data, data)
            _s, res, data = _tool(port, "deck_tags", {"plan": "p1", "under": "Cardio::Valves"})
            check("mcp: deck_tags: paths under a tag with their card counts",
                  data["tags"] == [{"path": "tag:Cardio::Valves::Valve_disease", "cards": 8, "name": "Cardio › Valves › Valve disease"}]
                  and data["more"] == 0, data)
            data = _tool(port, "deck_tags", {"plan": "p1", "find": "shock", "limit": 1})[2]
            check("mcp: deck_tags: words to find, a limit", [t["path"] for t in data["tags"]] == ["tag:Cardio::Shock"], data)
            data = _tool(port, "ops_vocabulary", {})[2]
            check("mcp: ops_vocabulary is ai.vocabulary's, for an AI", data["ops"] == __import__("due_crew.planner.ai", fromlist=["x"]).vocabulary(for_ai=True))
            ops = [{"op": "move", "date": "u1", "to": "2026-10-23"}, {"op": "move", "date": "Nope", "to": "2026-10-23"}]
            _s, res, data = _tool(port, "preview_changes", {"plan": "p1", "ops": ops})
            check("mcp: preview_changes: each change in words with who it touches, one that won't go on with why; nothing kept",
                  [e["verb"] for c in data["changes"] for e in c["entries"]] == ["Moved"]
                  and data["changes"][0]["entries"][0]["who"] == "Not open for anyone yet"
                  and data["refused"] == [{"op": ops[1], "why": "No date on the plan is Nope."}]
                  and not any(host.drafts.values()) and not host.heard and not res["isError"], data)
            _s, res, data = _tool(port, "add_to_changes", {"plan": "p1", "ops": ops, "why": "Shock a day later"})
            kept = json.loads(host.drafts["p1"])
            check("mcp: add_to_changes: under the plan as changes waiting (its version, who asked, the line), an open Your plans told",
                  len(data["added"]) == 1 and len(data["refused"]) == 1 and data["waiting"] == 1
                  and kept["version"] == 4 and [(o["op"], o["by"], o["why"]) for o in kept["ops"]] == [("move", "ai", "Shock a day later")]
                  and host.heard == ["p1"] and mcp.SEND in data["note"], (data, kept))
            data = _tool(port, "read_plan", {"plan": "p1"})[2]
            check("mcp: read_plan shows the plan with its changes waiting, and says them",
                  data["waiting"][0]["verb"] == "Moved" and next(d["day"] for d in data["dates"] if d["id"] == "u1") == "2026-10-23"
                  and data["note"].startswith("The plan with the 1 change waiting under it, not sent."), data)
            data = _tool(port, "preview_changes", {"plan": "p1", "ops": [{"op": "move", "date": "u1", "to": "2026-10-23"}]})[2]
            check("mcp: a preview is tried on the plan as the changes waiting leave it",
                  data["refused"][0]["why"] == "Nothing to change: the plan has that already.", data)
            host.refuse_keeps = 1
            data = _tool(port, "add_to_changes", {"plan": "p1", "ops": [{"op": "move", "date": "u2", "to": "2026-10-24"}]})[2]
            check("mcp: a draft that changed in Anki meanwhile is read again and the change kept over it",
                  data["waiting"] == 2 and len(json.loads(host.drafts["p1"])["ops"]) == 2 and host.heard == ["p1", "p1"], data)
            host.raws["p1"]["version"] = 5  # a co-author's save
            data = _tool(port, "add_to_changes", {"plan": "p1", "ops": [{"op": "rename", "date": "u3", "name": "HF"}]})[2]
            check("mcp: a co-author's save since: the changes waiting are put on the plan as it is now",
                  json.loads(host.drafts["p1"])["version"] == 5 and data["waiting"] == 3, data)
            before = dict(host.drafts)
            _s, res, data = _tool(port, "add_to_changes", {"plan": "p2", "ops": ops})
            check("mcp: a plan I follow takes no changes: an error result in words, nothing kept",
                  res["isError"] and "only its authors" in res["content"][0]["text"] and host.drafts == before, res)
            _s, res, _d = _tool(port, "read_plan", {"plan": "nope"})
            check("mcp: a plan I don't have is an error result, never a crash", res["isError"] and "list_plans" in res["content"][0]["text"])
            _s, res, _d = _tool(port, "add_to_changes", {"plan": "p1", "ops": "not a list"})
            check("mcp: ops that aren't a list are an error result", res["isError"], res)
            status, got = _mcp_post(port, {"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "send_plan"}})
            check("mcp: an unknown tool is invalid params; an unknown method isn't found",
                  got["error"]["code"] == -32602 and _mcp_post(port, {"jsonrpc": "2.0", "id": 10, "method": "resources/list"})[1]["error"]["code"] == -32601)
            status, got = _mcp_post(port, [{"jsonrpc": "2.0", "id": 11, "method": "ping"},
                                           {"jsonrpc": "2.0", "method": "notifications/initialized"},
                                           {"jsonrpc": "2.0", "id": 12, "method": "tools/list"}])
            check("mcp: a batch: an answer for each request, none for its notification",
                  status == 200 and [a["id"] for a in got] == [11, 12] and got[0]["result"] == {}, got)
            status, got = _mcp_post(port, [{"jsonrpc": "2.0", "method": "notifications/initialized"}])
            check("mcp: a batch of notifications alone gets 202", status == 202 and got is None)
            check("mcp: no token, or the wrong one, is 401",
                  _mcp_post(port, {"jsonrpc": "2.0", "id": 1, "method": "ping"}, token=None)[0] == 401
                  and _mcp_post(port, {"jsonrpc": "2.0", "id": 1, "method": "ping"}, token="t0k3n-for-test")[0] == 401)
            check("mcp: a Host that isn't this computer's address is 403 (DNS rebinding); localhost is fine",
                  _mcp_post(port, {"jsonrpc": "2.0", "id": 1, "method": "ping"}, host=f"evil.example:{port}")[0] == 403
                  and _mcp_post(port, {"jsonrpc": "2.0", "id": 1, "method": "ping"}, host="127.0.0.1:1")[0] == 403
                  and _mcp_post(port, {"jsonrpc": "2.0", "id": 1, "method": "ping"}, host=f"localhost:{port}")[0] == 200)
            check("mcp: an Origin that isn't this computer's is 403; none, null or a local page's is fine",
                  _mcp_post(port, {"jsonrpc": "2.0", "id": 1, "method": "ping"}, origin="https://evil.example")[0] == 403
                  and _mcp_post(port, {"jsonrpc": "2.0", "id": 1, "method": "ping"}, origin="http://localhost.evil.example")[0] == 403
                  and _mcp_post(port, {"jsonrpc": "2.0", "id": 1, "method": "ping"}, origin="null")[0] == 200
                  and _mcp_post(port, {"jsonrpc": "2.0", "id": 1, "method": "ping"}, origin="http://localhost:6274")[0] == 200)
            check("mcp: GET is 405 (no stream), another path 404",
                  _mcp_post(port, None, method="GET")[0] == 405 and _mcp_post(port, {"jsonrpc": "2.0", "id": 1, "method": "ping"}, path="/x")[0] == 404)
            status, got = _mcp_post(port, None, raw=b"{not json")
            check("mcp: a body that isn't JSON is a parse error", status == 400 and got["error"]["code"] == -32700, got)
            check("mcp: more than 1 MB is turned away before it's read", _mcp_big(port, mcp.BODY_MAX + 1) == 413)
            check("mcp: setup to copy: the shim with the port, the token in its environment (never its command line); or the address and header",
                  json.loads(mcp.setup(4242, "tok", "/x/mcp_shim.py", python="python3")) == {"mcpServers": {"due-crew": {
                      "command": "python3", "args": ["-I", "/x/mcp_shim.py", "--port", "4242"], "env": {"DUE_CREW_MCP_TOKEN": "tok"}}}}
                  and json.loads(mcp.setup(4242, "tok", "", http=True))["mcpServers"]["due-crew"] == {
                      "type": "http", "url": "http://127.0.0.1:4242/mcp", "headers": {"Authorization": "Bearer tok"}})
            host.gone = True  # signed out, or another profile: nothing kept is shown past it
            _s, res, _d = _tool(port, "list_plans", {})
            check("mcp: once its profile or account is gone, a tool says so", res["isError"]
                  and res["content"][0]["text"] == "Anki changed profile or account. Try again.", res)
    finally:
        srv.stop()
    printed = "\n".join(x for x in said.getvalue().splitlines() if not x.startswith(("PASS ", "FAIL ", "     ")))
    check("mcp: nothing it was sent is logged, the token least of all", "t0k3n" not in printed and "Shock" not in printed, printed[:300])
    import socket
    try:
        socket.create_connection(("127.0.0.1", port), timeout=2).close()
        gone = False
    except OSError:
        gone = True
    check("mcp: stopped, it's gone (and only ever on 127.0.0.1)", gone and srv.port is None and srv.url == "")


def test_mcp_shim():
    import subprocess
    shim = os.path.join(REPO, "tools", "due_crew_mcp.py")
    check("mcp shim: the add-on's copy is tools/due_crew_mcp.py, byte for byte",
          open(shim, "rb").read() == open(os.path.join(REPO, "due_crew", "planner", "mcp_shim.py"), "rb").read())
    host, srv = _mcp_world()
    try:
        env = dict(os.environ, DUE_CREW_MCP_TOKEN="t0k3n-for-tests")
        lines = (json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}) + "\n"
                 + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
                 + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "list_plans", "arguments": {}}}) + "\n")
        got = subprocess.run([sys.executable, "-I", shim, "--port", str(srv.port)], input=lines, capture_output=True, text=True,
                             timeout=60, env=env)
        out = [json.loads(x) for x in got.stdout.splitlines() if x.strip()]
        check("mcp shim: each line on stdin to the server, each answer a line on stdout, none for the notification",
              got.returncode == 0 and [a["id"] for a in out] == [1, 2] and out[0]["result"]["serverInfo"]["name"] == "due-crew"
              and out[1]["result"]["structuredContent"]["authored"][0]["id"] == "p1", got.stdout + got.stderr)
        bad = subprocess.run([sys.executable, "-I", shim, "--port", str(srv.port), "--token", "wrong"], input=lines,
                             capture_output=True, text=True, timeout=60)
        check("mcp shim: a wrong token is said on stderr, and an error answers each request",
              [a["id"] for a in map(json.loads, bad.stdout.splitlines())] == [1, 2] and "token doesn't match" in bad.stderr
              and "wrong" not in bad.stderr, bad.stdout + bad.stderr)
    finally:
        srv.stop()
    dead = subprocess.run([sys.executable, "-I", shim, "--port", str(srv_port_free())], input=lines, capture_output=True,
                          text=True, timeout=60, env=env)
    answers = [json.loads(x) for x in dead.stdout.splitlines() if x.strip()]
    check("mcp shim: Anki not running is said on stderr (never the token), each request answered with an error",
          dead.returncode == 0 and "Anki isn't running" in dead.stderr and "t0k3n" not in dead.stderr
          and [a["id"] for a in answers] == [1, 2] and all("error" in a for a in answers), dead.stdout + dead.stderr)
    none = subprocess.run([sys.executable, "-I", shim], input="", capture_output=True, text=True, timeout=60,
                          env={k: v for k, v in os.environ.items() if not k.startswith("DUE_CREW_MCP")})
    check("mcp shim: no port or token: says what it needs", none.returncode == 2 and "--port" in none.stderr, none.stderr)


def srv_port_free():
    """A port nothing listens on (bound, then let go)."""
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ---- round five: the Insights tab (insights.py) ----

def test_insights_tab():
    """Round five (Sam, before the click-test): Insights between Plan and
    Settings: what each week asks, how much of the deck the plan holds and
    of each of its parts, what each quiz or exam tests, its biggest dates,
    cards on two dates, leeches."""
    from due_crew.planner import build as B
    from due_crew.planner import insights as I
    from due_crew.planner import view as V
    check("insights: a share in words", (I.pct(0, 10), I.pct(10, 10), I.pct(1, 1000), I.pct(1, 3), I.pct(995, 1000), I.pct(3, 0))
          == ("none", "all", "<1%", "33%", "99%", "none"))
    col = collection()
    idx = P.DeckIndex(col, 1)
    doc = {"deck": "Big Step 1", "end": "2026-11-27", "units": [
        {"id": "u1", "name": "Heart failure", "opens": "2026-11-09", "tags": [VID]},
        {"id": "u2", "name": "HF drugs", "opens": "2026-11-10", "tags": [DRUGS, VID]},
        {"id": "u3", "name": "The book", "opens": "2026-11-17", "tags": [BOOK], "for": "e1"}],
        "events": [{"id": "e2", "day": "2026-11-27", "name": "Block exam"}, {"id": "e1", "day": "2026-11-20", "name": "Cardio quiz"}]}
    per, cards = I.held(idx, doc)
    check("insights: the plan's cards here, date by date and all of them (a card on two dates once)",
          per == {"u1": {1, 2, 3, 4, 12}, "u2": {1, 2, 3, 4, 12, 15}, "u3": {5, 6}} and cards == {1, 2, 3, 4, 5, 6, 12, 15}
          and I.on_two(per) == 5, per)
    check("insights: how much of the deck, in words (a filtered deck's card counts in its home deck)",
          I.deck_words("Big Step 1", len(cards), len(idx.home)) == "8 of Big Step 1's 15 cards (53%)"
          and I.deck_words("", 0, 4) == "0 of the deck's 4 cards (none)", len(idx.home))
    check("insights: what's not in it, named", I.none_words([{"name": c, "total": 1} for c in "ABCDEF"])
          == "Not in it: A, B, C, D and 2 more" and I.none_words([]) == "")
    tiles, ways = I.deck_split(idx)
    check("insights: the fake deck's own split, kept with its searches (a big deck's is a second or two once)",
          I.deck_split(idx) is I.deck_split(idx) and isinstance(ways, list), ways)
    xs = I.exams(doc, per, cards)
    check("insights: each quiz or exam by its day, what its dates hold; the last with no date for it tests everything",
          [(x["name"], I.exam_words(x)) for x in xs] == [("Cardio quiz", "2 cards from 1 date"), ("Block exam", "everything: 8 cards")]
          and I.exam_words({"all": False, "dates": 0, "cards": 0}) == "no date for it yet", xs)
    check("insights: the biggest dates, most first", [(u["id"], n) for u, n in I.biggest(doc, per)] == [("u2", 6), ("u1", 5), ("u3", 2)])
    check("insights: the leech on its dates is counted (a plan never opens one)", M.counts(idx, cards)["leech"] == 1)
    tags, decks = idx.tree()
    t = B.Tree(tags, decks)
    pace = V.pace_of(doc)
    asks = V.week_asks(doc, t, pace)
    rows = I.workload(doc, asks, "2026-11-11")
    check("insights: the workload week by week, the first to the one it ends in, a week with nothing new too",
          [(w["n"], w["start"], w["span"], w["now"]) for w in rows]
          == [(1, "2026-11-09", "9–15 Nov", True), (2, "2026-11-16", "16–22 Nov", False), (3, "2026-11-23", "23–29 Nov", False)]
          and rows[0]["new"] > 0 and rows[2]["new"] == 0 and rows[2]["reviews"] > 0, rows)
    words, over = I.workload_words(doc, rows, V.work(doc, t, pace))
    b = I.busiest(rows)
    check("insights: the workload in a line: the new cards, the weeks, the busiest",
          words.startswith(f"{sum(V.work(doc, t, pace).values()):,} new cards over 3 weeks. Busiest: week {b['n']}, ") and over == "",
          words)
    check("insights: each week's quizzes and exams; its whole (new and reviews) finds the busiest",
          [w["events"] for w in rows] == [[], ["Cardio quiz"], ["Block exam"]]
          and b["cards"] == max(w["cards"] for w in rows) and all(w["cards"] >= w["new"] for w in rows), rows)
    w = {"n": 3, "span": "26 Oct–1 Nov", "events": [], "new": 20, "reviews": 34.2, "cards": 300, "over": False, "top": 22, "cap": 20}
    check("insights: a week's two measures, never added; one over the pace says its busiest day",
          (I.new_words(w), I.reviews_words(w), I.reviews_words(dict(w, reviews=0.2))) == ("20", "~35", "0")
          and I.new_words(dict(w, new=18, over=True, top=41)) == "18 · busiest day 41"
          and I.week_words(w) == "Week 3, 26 Oct–1 Nov: 20 new a study day, ~35 reviews a day"
          and I.week_words(dict(w, over=True, top=41, events=["Cardio quiz"]))
          == "Week 3, 26 Oct–1 Nov: 20 new a study day (41 on its busiest day, over the pace of 20), ~35 reviews a day; Cardio quiz"
          and I.workload_words(doc, [dict(w, over=True), dict(w, n=5, over=True)], {})[1]
          == "Over the pace: weeks 3 and 5" and I.workload(doc, {}, "2026-11-11") == []
          and I.busiest([dict(w, cards=0)]) is None and I.busiest([w, dict(w, n=4, cards=300)])["n"] == 3)
    # Sam: "the same organization problem we had for the bento": the deck split as the topic map splits it
    # (team.subjects_by), not by its #/^ parts. A big shared deck: systems under ^, the same topics under
    # each # resource, a yield rating on every card, a bank's question ids, Anki's own tags.
    tags_of, cid = {}, 0
    for system, parts in (("Cardio", (("Physiology", 60), ("Pathology", 60), ("Pharm", 30))),
                          ("Renal", (("Physiology", 60), ("Pathology", 60))), ("Pulm", (("Physiology", 45), ("Pathology", 45)))):
        for part, n in parts:
            for _ in range(n):
                cid += 1
                tags_of[cid] = [f"#Big::^Systems::{system}::{part}", f"#Big::#Videos::{system}::{part}",
                                f"#Big::#Yield::{1 + cid % 3}-Tier", f"#Big::#Bank::Step::{100000 + cid}"] + (["leech"] if cid % 7 == 0 else [])
    home = set(tags_of)
    plan = set(range(1, 61)) | set(range(61, 91)) | set(range(151, 161))  # Cardio's physiology, half its pathology, a little Renal
    tiles, ways = I.split(tags_of, home)
    rows, none, inside = I.topics(tiles, plan)
    check("insights: the deck by its systems, not its ratings or a bank's ids; the plan's parts most held first",
          [(r["name"], r["held"], r["total"]) for r in rows] == [("Cardio", 90, 150), ("Renal", 10, 120)]
          and [(r["name"], r["total"]) for r in none] == [("Pulm", 90)]
          and not any("Tier" in w["name"] or "Bank" in w["name"] for w in ways if w["on"]), (rows, none, ways))
    check("insights: the part the plan is mostly in, split again: which of its parts it leaves out",
          inside is not None and inside[0] == "Cardio"
          and [(r["name"], r["held"], r["total"]) for r in inside[1]] == [("Physiology", 60, 60), ("Pathology", 30, 60)]
          and [(r["name"], r["total"]) for r in inside[2]] == [("Pharm", 30)], inside)
    spread = set(range(1, 31)) | set(range(151, 181)) | set(range(271, 301))
    check("insights: a plan spread over the deck isn't split again", I.topics(tiles, spread)[2] is None)
    rating = next((w["key"] for w in ways if "yield" in w["key"]), None)
    rtiles, rways = I.split(tags_of, home, by=rating)
    check("insights: another way, picked (the map's By ▾): the deck by it; a pick not among them, the best",
          rating is not None and sorted(t["name"] for t in rtiles) == ["1-Tier", "2-Tier", "3-Tier"]
          and next(w for w in rways if w["on"])["key"] == rating
          and [t["name"] for t in I.split(tags_of, home, by="#gone::^way")[0]] == [t["name"] for t in tiles], rways)
    # a deck of my own: its subdecks when its tags don't split it (team_flow._map's rule); the way named Subdecks
    mine = {c: [] for c in range(1, 301)}
    paths = {c: [f"Week {1 + (c - 1) // 100}"] for c in range(1, 301)}
    dtiles, dways = I.split(mine, set(mine), paths=paths)
    check("insights: a deck of my own: by its subdecks, the way Subdecks",
          sorted((t["name"], t["n"]) for t in dtiles) == [("Week 1", 100), ("Week 2", 100), ("Week 3", 100)]
          and [w["name"] for w in dways if w["on"]] == ["Subdecks"]
          and f'DECKS_WAY = "{I.DECKS_WAY}"' in open(os.path.join(REPO, "due_crew", "team_flow.py")).read(), dways)
    col2 = collection()
    idx2 = P.DeckIndex(col2, 1)
    sp = I.tags_spelled(idx2)
    check("insights: each card's tags as written; each subdeck card's path below the deck",
          VID in sp[1] and SYS in sp[1] and I.deck_paths(idx2) == {13: ["Cardio"], 14: ["Cardio"]}, (sp.get(1), I.deck_paths(idx2)))

def main():
    names = [n for n in list(globals()) if n.startswith("test_")]
    for n in names:
        globals()[n]()
    bad = [c for c in CHECKS if not c[1]]
    print(f"\n{len(CHECKS) - len(bad)}/{len(CHECKS)} checks passed")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
