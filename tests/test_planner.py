"""Labs, the plan window (due_crew/planner, docs/planner.md), against a fake
collection and the fake Worker (tests/fakes.py). Standard library only.

Run: python3 tests/test_planner.py
"""

import ast
import datetime
import glob
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
    from due_crew import app
    saved = app.cfg
    menu = types.SimpleNamespace(addSeparator=lambda: None, addAction=lambda a: added.append(a))
    added = []
    try:
        app.cfg = lambda: {}
        check("gate: labs off, Tools › Due Crew gets nothing", planner.install(menu) is False and not added)
    finally:
        app.cfg = saved
    init = open(os.path.join(REPO, "due_crew", "__init__.py")).read()
    check("gate: the menu asks the labs package itself, after its own entries; nothing else imports it",
          "planner.install(menu)" in init and "from . import planner" in init
          and not [f for f in glob.glob(os.path.join(REPO, "due_crew", "*.py"))
                   if "planner" in open(f).read() and not f.endswith("__init__.py")])
    cfgj = open(os.path.join(REPO, "due_crew", "config.json")).read()
    check("gate: no default config turns it on (a key nothing writes)", '"labs"' not in cfgj)


def test_admin_only():
    store = world({"sam": "Sammy", "dre": "Dre"})
    store.admins.add("sam")
    sam, dre = new_client(store, "sam"), new_client(store, "dre")
    check("admin: the server says the admin's account is one, and no one else's",
          R.is_admin(sam) is True and R.is_admin(dre) is False)
    from due_crew.planner import flow
    shown, tips = [], []
    saved = (flow.enabled, flow.client, flow._bg, flow.show_plans, flow.tooltip, flow.mw.col, flow.plan_flow._signed_in)
    try:
        flow.enabled = lambda: True
        flow._bg = lambda job, done: done(job())
        flow.show_plans = lambda plans, select=None: shown.append(plans)
        flow.tooltip = lambda text, **k: tips.append(text)
        flow.plan_flow._signed_in = lambda: True
        flow.mw.col = object()
        flow._admin.clear()
        flow.client = lambda: dre
        flow.open_plans()
        n = len(store.log)
        flow.open_plans()
        check("admin: anyone else is told it's the admin's, and asked once a session",
              not shown and len(tips) == 2 and "admin" in tips[0] and len(store.log) == n
              and not any(p.startswith("/plans") for _m, p, _s in store.log), (tips, store.log))
        pid, _code = store.add_plan("sam", "MS2 Block 2", "Big Step 1",
                                    [{"id": "u1", "name": "Heart failure", "opens": "2026-11-09", "tags": [VID]}])
        flow.client = lambda: sam
        flow.open_plans()
        check("admin: the admin's account gets the window, with its plans (two requests, on the click)",
              len(shown) == 1 and [p["id"] for p in shown[0]] == [pid]
              and [p for _m, p, _s in store.log][-2:] == ["/auth/me", "/plans/mine"], store.log[-3:])
        flow.enabled = lambda: False
        flow.open_plans()
        check("admin: labs off, nothing at all", len(shown) == 1)
    finally:
        flow.enabled, flow.client, flow._bg, flow.show_plans, flow.tooltip, flow.mw.col, flow.plan_flow._signed_in = saved


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
                    ("deck", "Subdecks", "Cardio"), ("search", "Searches", "deck:current"),
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
    g = Q.find(idx, "10234 10911", bank="Other Bank")
    check("qids: another bank, when asked", g["bank"] == "Other Bank" and g["cids"] == {10} and g["missing"] == ["10911"])
    t = Q.tally(idx, f["cids"] | {12})
    check("qids: what they are here: open, shut (would open), a leech (stays shut), seen before",
          t == {"cards": 4, "open": 1, "shut": 2, "leech": 1, "new_shut": 1, "review": 2}, t)
    words = Q.words(f, Q.tally(idx, f["cids"]), [("MS2 Block 2", ["Mon 9 Nov", "Tue 10 Nov"])])
    check("qids: its lines, plainly",
          words == ["3 questions · 3 cards here", "1 open already, 2 still shut",
                    "2 numbers aren’t questions here: 2026, 99999", "On MS2 Block 2: Mon 9 Nov, Tue 10 Nov"], words)
    check("qids: nothing pasted, or nothing a question",
          Q.words(Q.find(idx, ""), Q.tally(idx, set())) == ["Paste the IDs: Due Crew picks out the numbers."]
          and Q.words(Q.find(idx, "55555"), Q.tally(idx, set())) == ["None of these are questions in this deck."])
    cold = collection()
    cold.db.conn.execute("UPDATE notes SET tags = ' x '")
    check("qids: a deck with no question tags has no banks", Q.banks(P.DeckIndex(cold, 1)) == {}
          and Q.find(P.DeckIndex(cold, 1), "10234")["bank"] is None)


def test_threads():
    """Sam: "take ... mistakes from qbanks ... and develop insights into common
    threads": what the missed questions share, by the deck's own tags."""
    conn = sqlite3.connect(":memory:")
    fakes.make_collection(conn)
    cardio, renal = f"{ROOT}::^Systems::Cardio", f"{ROOT}::^Systems::Renal"
    hf = f"{ROOT}::#Videos::Cardio::Heart_Failure"
    rows = [(1, f"{ROOT}::#Bank::101 {cardio}::Heart_Failure {hf}"), (2, f"{ROOT}::#Bank::102 {cardio}::Heart_Failure {hf}"),
            (3, f"{ROOT}::#Bank::103 {cardio}::Shock"), (4, f"{ROOT}::#Bank::103 {cardio}::Shock leech"),
            (5, f"{ROOT}::#Bank::104 {renal}::AKI"), (6, f"{ROOT}::#Bank::105 {renal}::AKI"), (7, f"{ROOT}::#Bank::106 Misc")]
    for cid, tags in rows:
        fakes.add_card(conn, cid, 1, tags=tags)
    col = fakes.FakeCol(conn, fakes.day_cutoff_for(datetime.date(2026, 11, 9)))
    col.decks = fakes.FakeDecks({1: "Big Step 1"})
    idx = P.DeckIndex(col, 1)
    f = Q.find(idx, "101 102 103 104 105 106")
    ts = Q.threads(idx, f["by"])
    got = [(t["label"], t["n"], t["of"]) for t in ts]
    check("threads: the tags most of the questions share, a question once however many cards, most first",
          got == [("Systems › Cardio", 3, 6), ("Videos › Cardio › Heart Failure", 2, 6), ("Systems › Renal › AKI", 2, 6)], got)
    check("threads: each line of tags named once, at its deepest with them all; one question is no thread",
          not any("Heart Failure" in t["label"] and t["label"].startswith("Systems") for t in ts)
          and not any("Misc" in t["label"] or "Shock" in t["label"] for t in ts))
    check("threads: a thread's cards are its questions' cards on it; its questions by number",
          ts[0]["cids"] == {1, 2, 3, 4} and ts[0]["qids"] == ["101", "102", "103"] and ts[2]["cids"] == {5, 6} and ts[1]["cids"] == {1, 2})
    check("threads: in words", Q.thread_words(ts[0]) == "Systems › Cardio · 3 of 6 questions")
    check("threads: the plans' own tags, a leech's and the question's never are one",
          Q._topic_paths("DueCrew::MS2::SLG_1") == [] and Q._topic_paths("leech") == [] and Q._topic_paths(f"{ROOT}::#Bank::101") == []
          and Q._topic_paths("Pharm::Antibiotics") == ["Pharm", "Pharm::Antibiotics"]
          and Q._topic_paths(cardio) == [cardio])
    check("threads: none without questions", Q.threads(idx, {}) == [])


def test_kept_misses():
    log = Q.keep([], "2026-11-09", 1, "Bank", ["101", "102", "x"])
    log = Q.keep(log, "2026-11-09", 1, "Bank", ["102", "103"])
    log = Q.keep(log, "2026-11-10", 1, "Bank", ["101", "104"])
    log = Q.keep(log, "2026-11-10", 2, "Bank", ["900"])
    check("kept: one entry a day, deck and bank, each number once in it",
          [(e["day"], e["deck"], e["n"]) for e in log]
          == [("2026-11-09", 1, ["101", "102", "103"]), ("2026-11-10", 1, ["101", "104"]), ("2026-11-10", 2, ["900"])], log)
    check("kept: a deck's questions once each, the newest paste's first, with its pastes and first day",
          Q.kept(log, 1) == (["101", "104", "102", "103"], 2, "2026-11-09") and Q.kept(log, 3) == ([], 0, None))
    rest, gone = Q.forget(log, 1)
    check("kept: forget takes a deck's out and says which", [e["deck"] for e in rest] == [2] and len(gone) == 2)
    big = []
    for i in range(Q.KEEP_PASTES + 5):
        big = Q.keep(big, f"d{i:04d}", 1, "Bank", [str(1000 + i)])
    check("kept: the newest 200 pastes", len(big) == Q.KEEP_PASTES and big[0]["day"] == "d0005")
    check("kept: nothing kept for no numbers", Q.keep([], "d", 1, "Bank", []) == [])
    from due_crew.planner import flow
    from due_crew import app
    tmp = tempfile.mkdtemp()
    saved = (app._profile_files, flow.plan_flow._today)
    try:
        app._profile_files = lambda: tmp
        flow.plan_flow._today = lambda: "2026-11-09"
        ops = flow.QidOps()
        ops.keep(1, "Bank", ["101", "102"])
        check("kept: on this computer, in the profile's qids.json, numbers only",
              ops.kept(1) == (["101", "102"], 1, "2026-11-09") and os.listdir(tmp) == ["qids.json"]
              and open(os.path.join(tmp, "qids.json")).read() == '{"v": 1, "misses": [{"day": "2026-11-09", "deck": 1, "bank": "Bank", "n": ["101", "102"]}]}')
        gone = ops.forget(1)
        check("kept: Forget, then Undo, the same screen", ops.kept(1)[0] == [] and (ops.unforget(gone) or True)
              and ops.kept(1) == (["101", "102"], 1, "2026-11-09"))
        with open(os.path.join(tmp, "qids.json"), "w") as f:
            f.write("{not json")
        check("kept: a file that won't read is none kept, never an error", flow.misses_log() == [])
    finally:
        app._profile_files, flow.plan_flow._today = saved


def test_bring_back():
    col = collection()
    before = state(col)
    cids = {7, 8, 9, 12, 15, 3}
    got = A.bring_back(col, cids, "Due Crew: bring back 6 cards")
    after = state(col)
    check("bring back: the shut ones open (never the leech), one undo step under its name",
          after[7][0] == 0 and after[8][0] == 2 and after[12][0] == -1 and len(col.undo_steps) == 1
          and col.undo_steps[0][0] == "Due Crew: bring back 6 cards", (after, col.undo_steps))
    check("bring back: the review ones (open, or just opened) come due over the next 3 days, in their own deck only",
          got == {"opened": 2, "due": 3} and {after[c][2] for c in (3, 8, 9)} <= {1000, 1001, 1002}
          and after[15] == before[15] and after[7][1] == 0, (got, after))
    check("bring back: a new one opened goes first in Anki's line", after[7][2] == 0 and before[7][2] == 0
          and any(n == "Reposition" or 7 in ids for n, ids in col.undo_steps), col.undo_steps)
    col3 = collection()
    col3.db.conn.execute("UPDATE cards SET due = 990 WHERE id = 3")   # overdue
    col3.db.conn.execute("UPDATE cards SET due = 1001 WHERE id = 9")  # due tomorrow, inside the 3 days
    moves = A.reviews(col3, {3, 9, 8}, {8})  # what the window's count says first
    got3 = A.bring_back(col3, {3, 9, 8}, "Due Crew: bring back 3 cards")
    after3 = state(col3)
    check("bring back: never puts a card later: one overdue or due inside the 3 days stays as it is",
          moves == [8] and got3 == {"opened": 1, "due": 1} and after3[3][2] == 990 and after3[9][2] == 1001
          and after3[8][2] in (1000, 1001, 1002), (moves, got3, after3))
    col2 = collection()
    got2 = A.bring_back(col2, {7, 8, 9}, "Due Crew: open 3", back=False)
    after2 = state(col2)
    check("bring back: Just open opens the shut ones, moves nothing",
          got2 == {"opened": 2, "due": 0} and after2[9] == state(collection())[9] and after2[8][0] == 2 and len(col2.undo_steps) == 1)
    col3 = collection()
    col3.db.conn.execute("UPDATE cards SET queue = -1 WHERE id = 9")
    col3.db.conn.execute("UPDATE notes SET tags = tags || ' leech ' WHERE id = 9")
    check("bring back: nothing to do, no undo step", A.bring_back(col3, {12, 15, 9}, "x") == {"opened": 0, "due": 0}
          and not col3.undo_steps)
    check("bring back: one day is today", A.BACK_DAYS == 3 and "\"0\" if int(days) <= 1" in open(A.__file__).read())


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
    try:
        E.take_source(d, "u2", ("search", "q2"))
        site = None
    except E.Refused as e:
        site = str(e)
    check("edits: a search is changed on duecrew.com", site == "That one is changed on duecrew.com.", site)
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
             flow.cfg)
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
        got = qo.bring_back({7, 8, 9}, back=True)
        check("glue: Do it is one undo step, then what an open does (Edit's undo, my pace, the board)",
              got == {"opened": 2, "due": 2} and calls == ["undo", ("claim", [7, 8]), "progress", "swap"]
              and col.undo_steps[-1][0] == "Due Crew: bring back 3 cards", (got, calls))
    finally:
        (F._state_cfg, flow.mw.col, F.followed, F._after_change, F._claim_opened, F.refresh_progress, flow.app.swap,
         flow.cfg) = saved


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
        flow._admin.clear()
        flow.client = lambda: dre
        flow.open_start()
        check("calendar glue: the admin's account only, as the plan window", not shown and tips and "admin" in tips[0])
        flow.client = lambda: sam
        flow.open_start()
        n = len(store.log)
        flow._open.clear()
        flow.open_start()
        check("calendar glue: the admin gets it, asked once a session", shown == [True, True] and len(store.log) == n)
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
    check("road: four windows, each wearing the board's look and saying what it is",
          sorted(windows) == ["picker.py", "qid_window.py", "start_window.py", "window.py"]
          and all(t.count("(QDialog)") == t.count("attach_alive(self)") == len(re.findall(r"\bheading\(self", t))
                  for t in windows.values()), sorted(windows))
    check("road: no window sets its own type or margins in a style sheet, nor reads Anki's palette",
          not [f for f, t in windows.items() if "setStyleSheet" in t or "palette(" in t or "font-size" in t])
    check("road: every label is plain text (names are the authors' and the deck's); tooltips escaped",
          all("setTextFormat(Qt.TextFormat.PlainText)" in t for t in windows.values())
          and not [f for f, t in windows.items() if re.search(r'setToolTip\(0, (?!f"<span>\{esc\()', t)])
    pure = ("model.py", "qids.py", "edits.py", "actions.py", "remote.py", "reading.py", "claude.py")
    check("road: the pure parts and the requests import no aqt",
          not [f for f in pure if re.search(r"^\s*(from aqt|import aqt)", src[f], re.M)])
    calls = set()
    for f in ("flow.py", "window.py", "qid_window.py", "picker.py", "start_window.py"):
        for node in ast.walk(ast.parse(src[f])):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "remote":
                calls.add(node.attr)
    check("road: requests only on a click, through remote (who I am, my plans, one plan, a save)",
          calls <= {"is_admin", "my_plans", "load", "save", "undo", "create"} and "_call" not in src["flow.py"], calls)
    routes = set(re.findall(r'_call\((?:client, )?"(GET|PUT|POST|PATCH|DELETE)", f?"([^"]+)"', src["remote.py"]))
    check("road: nothing new on the server: routes the builder and the site use already",
          routes == {("GET", "/auth/me"), ("GET", "/plans/{pid}"), ("PUT", "/plans/{pid}"), ("POST", "/plans/{pid}/undo"),
                     ("POST", "/plans")}, routes)
    check("road: Claude isn't connected: the stand-in sends nothing, and nothing reads a card's text for it",
          not re.search(r"^\s*(?:from|import)\s+(?:requests|urllib|http|socket|anthropic)\b", src["claude.py"] + src["reading.py"], re.M)
          and not re.search(r"\bflds\b|\.note\(|\bnote\[", src["claude.py"] + src["reading.py"] + src["start_window.py"]))
    words = " ".join(src.values()).lower()
    banned = [w for w in ("anking", "uworld", "amboss", "boards and beyond", "sketchy", "pathoma", "first aid", "bootcamp")
              if w in words]
    check("road: no third-party deck, bank or video series named", not banned, banned)
    check("road: never suspends: the one step it adds unsuspends and moves due dates",
          "suspend_cards" not in src["actions.py"].replace("unsuspend_cards", ""))


def main():
    names = [n for n in list(globals()) if n.startswith("test_")]
    for n in names:
        globals()[n]()
    bad = [c for c in CHECKS if not c[1]]
    print(f"\n{len(CHECKS) - len(bad)}/{len(CHECKS)} checks passed")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
