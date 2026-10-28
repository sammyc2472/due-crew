"""3.9.5, Study where the cards are: a Study sits on the thing that names
the cards, no Study sheet. QBank QIDs' Their topics (planner/qids.py) and
the map's missed cards they count (team.py, team_flow.py), against a fake
collection (tests/fakes.py). The map's weakest part and its trail's Study
went before it shipped (Sam's picks on the 3.9.5 review page).
Standard library only.

Run: python3 tests/test_where.py
"""

import datetime
import os
import re
import sqlite3
import sys
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
from due_crew import plans as P                                # noqa: E402
from due_crew import team as T                                 # noqa: E402
from due_crew.planner import qids as Q                         # noqa: E402

CHECKS = []
TODAY = datetime.date(2026, 9, 1)
KK = board.BOARD_KEY


def check(name, cond, detail=""):
    CHECKS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond or detail == "" else f"\n     {detail}"))


def tile(key, name, cids, know, started=None, kids=None, tags=None):
    t = {"key": key, "name": name, "n": len(cids), "know": know, "started": len(cids) if started is None else started,
         "find": {"tags": tags or [f"Med::^Sys::{name}"]}, "_cids": list(cids)}
    if kids is not None:
        t["kids"] = kids
    return t


# ---- a part's missed cards ----

def test_missed():
    tiles = [tile("c", "Cardio", range(0, 40), 80), tile("r", "Renal", range(40, 70), 66), tile("p", "Pulm", range(70, 90), 66),
             tile("h", "Heme", range(90, 100), None, started=0), tile("e", "Endo", range(100, 110), None, started=4)]
    missed = set(range(40, 47)) | set(range(70, 79)) | set(range(0, 20)) | set(range(90, 100))
    check("missed in: a part's cards, a week's batch, the ones not started (their find)",
          T.missed_in(tiles[1], missed) == list(range(40, 47))
          and T.missed_in({"_batch": [1, 2, 3], "find": {"cids": [1, 2, 3]}}, {2, 3}) == [2, 3]
          and T.missed_in({"key": "new", "find": {"cids": [5, 6]}}, {6}) == [6]
          and T.missed_in({"find": {"tags": ["x"]}}, {1}) == [])
    pt = T.plan_tiles([("Renal", "DueCrew::P::Renal", {1, 2, 3})], {1: 1.0, 2: 0.0}, {1, 2})[0][0]
    check("plan tiles keep their cards in play, so their Study takes them",
          sorted(pt["_cids"]) == [1, 2] and T.missed_in(pt, {2, 3}) == [2], pt)
    check("study words: the number, one said as one", T.study_missed(41) == "Study the 41 you missed"
          and T.study_missed(1) == "Study the one you missed" and T.study_missed(1200) == "Study the 1,200 you missed")


def test_map_html():
    e = "<b>Renal & co"
    kids = [tile("a", "Acid–base", range(40, 55), 58), tile("t", "Tubules", range(55, 70), 74)]
    tiles = [tile("c", "Cardio", range(0, 40), 86), tile("r", e, range(40, 70), 66, kids=kids), tile("p", "Pulm", range(70, 90), 88)]
    mh = board._ins_map(10, tiles, "right", ())
    deep = board._ins_map(10, tiles, "right", ["r"])
    trail = re.search(r'<div class="tmt">.*?</div>', deep).group(0)
    check("map (Sam's picks): no weakest part named, and no Study on an open part's trail",
          "Weakest" not in mh and "insmapstudy" not in mh + deep and "you missed" not in mh + deep, mh[:1200])
    check("map: opened, the trail says the part, its cards and %, then Browse all, as before 3.9.5",
          ("<b>&lt;b&gt;Renal &amp; co</b> &middot; 30 cards, 66% &middot; <a href=\"#\" onclick=\"pycmd('duecrew:insmapall:10|"
           + KK) in trail, trail)
    view = {"map": tiles, "map_by": "right", "_map_missed": set(range(40, 81))}
    check("insights: the view's missed (QBank's topics count them) draw nothing on the map",
          "Weakest" not in board._insights_html(10, view) and "you missed" not in board._insights_html(10, view))


# ---- the glue, on a collection ----

def _collection():
    """Med (deck 30): Cardio (Valves 200-214, Rhythm 215-229), Renal (100-121,
    124), Pulm (300-314), all in play. Missed in the map's 4 weeks: Renal
    100-109, Cardio 200-205. Not missed: 120 (Again 30 days ago), 121 (Again
    learning it), 122 (suspended), 123 (another deck), 124 (Again only
    relearning). QBank's questions: 400-406 suspended, 100 in play."""
    conn = sqlite3.connect(":memory:")
    fakes.make_collection(conn)
    cut = fakes.day_cutoff_for(TODAY)
    at = lambda days: (cut - days * 86400 - 3600) * 1000  # noqa: E731
    add, rev = fakes.add_card, fakes.add_review
    for i in range(20):
        add(conn, 100 + i, 30, ctype=2, queue=2, ivl=5, tags="Med::^Sys::Renal" + (" Med::#Bank::10005" if i == 0 else ""))
        rev(conn, at(2), ease=1 if i < 10 else 3, cid=100 + i)
    add(conn, 120, 30, ctype=2, queue=2, ivl=5, tags="Med::^Sys::Renal")
    rev(conn, at(30), ease=1, cid=120)
    rev(conn, at(3), ease=3, cid=120)
    add(conn, 121, 30, ctype=0, queue=1, tags="Med::^Sys::Renal")
    rev(conn, at(1), ease=1, rtype=0, cid=121)
    add(conn, 122, 30, ctype=2, queue=-1, ivl=5, tags="Med::^Sys::Renal")
    rev(conn, at(2), ease=1, cid=122)
    add(conn, 123, 40, ctype=2, queue=2, ivl=5, tags="Med::^Sys::Renal")
    rev(conn, at(2), ease=1, cid=123)
    add(conn, 124, 30, ctype=2, queue=2, ivl=5, tags="Med::^Sys::Renal")
    rev(conn, at(5), ease=3, cid=124)
    rev(conn, at(4), ease=1, rtype=2, cid=124)
    for i in range(30):
        add(conn, 200 + i, 30, ctype=2, queue=2, ivl=5, tags="Med::^Sys::Cardio::" + ("Valves" if i < 15 else "Rhythm"))
        rev(conn, at(3), ease=1 if i < 6 else 3, cid=200 + i)
    for i in range(15):
        add(conn, 300 + i, 30, ctype=2, queue=2, ivl=5, tags="Med::^Sys::Pulm")
        rev(conn, at(3), ease=3, cid=300 + i)
    # a block's questions: 10001 two cards in Renal; 10002 one in Cardio, one in Pulm; 10003 Renal;
    # 10004 in no part; 10005 a card in play (100); 10006 a card tagged Renal and Pulm (the bigger: Renal)
    for cid, q, topic in ((400, 10001, "Med::^Sys::Renal"), (401, 10001, "Med::^Sys::Renal"),
                          (402, 10002, "Med::^Sys::Cardio::Valves"), (403, 10002, "Med::^Sys::Pulm"),
                          (404, 10003, "Med::^Sys::Renal"), (405, 10004, "Misc::Other"),
                          (406, 10006, "Med::^Sys::Pulm Med::^Sys::Renal")):
        add(conn, cid, 30, ctype=0, queue=-1, tags=f"Med::#Bank::{q} {topic}")
    col = fakes.FakeCol(conn, cut)
    col.decks = fakes.FakeDecks({30: "Med", 40: "Other"})
    return col


def test_glue():
    import due_crew as dc
    from aqt import mw
    from aqt.deckbrowser import DeckBrowser
    from due_crew import team_flow as TF, plan_flow as F
    from due_crew.app import _state
    from due_crew.planner import flow as PF
    if "aqt.reviewer" not in sys.modules:
        sys.modules["aqt.reviewer"] = types.SimpleNamespace(Reviewer=type("Reviewer", (), {}))
    col = _collection()
    cut = col.sched.day_cutoff
    deck = TF._deck_sql(col, 30)
    got = TF._missed(col, deck, cut)
    check("missed: Again in a review these 4 weeks, in the deck, not suspended (not before the window, "
          "not learning, not relearning, not another deck's)", got == set(range(100, 110)) | set(range(200, 206)), sorted(got))
    pc, conf, built, shown = {}, {}, [], []
    saved = (F._state_cfg, F.followed, F._today, F._pcfg, F._psave, F._filtered, F._browse, mw.col, TF.app.swap,
             TF.cfg, TF.save_cfg, dc.cfg, dc.save_cfg, _state.get("insights"), _state.get("map_at"))
    try:
        F._state_cfg = lambda c=None: {}
        F.followed = lambda: []
        F._today = lambda: TODAY.isoformat()
        F._pcfg = lambda: pc
        F._psave = lambda d: None
        F._filtered = lambda c, name, cids, **kw: built.append((name, sorted(cids))) or True
        F._browse = lambda cids, q=None, empty="": shown.append(sorted(cids) if cids else empty)
        TF.app.swap = lambda c=None: None
        TF.cfg = dc.cfg = lambda: conf
        TF.save_cfg = dc.save_cfg = lambda c, **k: None
        mw.col = col
        _state["insights"], _state["map_at"] = {}, {}
        alone = TF.deck_map(30)
        exam = (TODAY + datetime.timedelta(days=5)).isoformat()  # 3.9.5: a Study only before a date
        v = TF.insights(30, None, exam)
        tiles = v.get("map") or []
        check("glue: the map, by the deck's systems: Cardio (it opens), Renal, Pulm",
              [(t["name"], t["n"], bool(t.get("kids"))) for t in tiles] == [("Cardio", 30, True), ("Renal", 23, False), ("Pulm", 15, False)],
              [(t["name"], t["n"]) for t in tiles])
        check("glue: Insights keeps the map's missed with it (never drawn: a _-key)",
              v.get("_map_missed") == got and [t["know"] for t in tiles] == [80, 55, 100], [t["know"] for t in tiles])
        check("glue: QBank's map, worked out alone, is Insights' (the same split); fresh, Insights' own",
              [t["name"] for t in alone[0]] == [t["name"] for t in tiles] and alone[1] == got
              and TF.deck_map(30)[0] is tiles and TF.deck_map(99) == ([], set()))
        send = lambda m: dc._on_js(False, m + "|" + KK, DeckBrowser())  # noqa: E731
        send("duecrew:insmapstudy:30:1")
        check("insmapstudy (Sam's picks): gone, so the board's handler builds nothing", built == [], built)
        check("study: Insights' own Study still goes through the one helper",
              TF.study_deck("Renal", []) is False and TF.study_deck("Renal", [1]) is True and built[-1] == ("Due Crew::Renal", [1]))
        # ---- QBank QIDs' topics ----
        idx = P.DeckIndex(col, 30)
        found = Q.find(idx, "10001 10002 10003 10004 10005 10006 99999")
        rows = Q.topics(idx, found, tiles, got)
        check("qids: the questions found, their cards suspended but one",
              found["found"] == ["10001", "10002", "10003", "10004", "10005", "10006"] and len(found["cids"]) == 8, found)
        check("qids: their topics by the map's parts: a question once in each part its cards are in, the most first",
              [(r["name"], r["questions"]) for r in rows] == [("Renal", 4), ("Cardio", 1), ("Pulm", 1)], rows)
        check("qids: each topic's missed is the map's Study of it", rows[0]["missed"] == list(range(100, 110))
              and rows[1]["missed"] == list(range(200, 206)) and rows[2]["missed"] == [])
        check("qids: a card in two parts goes to the bigger, as the map has it (10006 in Renal, not Pulm)",
              Q.topics(idx, Q.find(idx, "10006"), tiles, got)[0]["name"] == "Renal" and len(Q.topics(idx, Q.find(idx, "10006"), tiles, got)) == 1)
        check("qids: a question in no part isn't said; nothing found, or a map of one tile, no topics",
              Q.topics(idx, Q.find(idx, "10004"), tiles, got) == [] and Q.topics(idx, Q.find(idx, "77777"), tiles, got) == []
              and Q.topics(idx, found, tiles[:1], got) == [])
        check("qids: the topics' lines, the first % says here", Q.topic_words(rows) == ["4 questions · 55% here", "1 question · 80%",
                                                                                       "1 question · 100%"], Q.topic_words(rows))
        ops = PF.QidOps()
        check("qids: the window's map is the deck's (QidOps.deck_map)",
              [t["name"] for t in ops.deck_map(30)[0]] == [t["name"] for t in tiles])
        built.clear()
        check("qids: a topic's Study, the same helper as the map's: Due Crew's deck named after it",
              ops.study_topic(rows[0]["name"], rows[0]["missed"]) is True and built == [("Due Crew::Renal", list(range(100, 110)))],
              built)
    finally:
        (F._state_cfg, F.followed, F._today, F._pcfg, F._psave, F._filtered, F._browse, mw.col, TF.app.swap,
         TF.cfg, TF.save_cfg, dc.cfg, dc.save_cfg, _state["insights"], _state["map_at"]) = saved


def test_qid_words():
    def row(name, q, know, started=1, i=0):
        return {"i": i, "name": name, "questions": q, "know": know, "started": started, "missed": []}
    rows = [row("Heme", 3, None, 0), row("Endo", 2, None, 5), row("Renal", 1, 66), row("Cardio", 1, 84)]
    check("qid words: new, too soon to say, then the first % says here, the rest the % alone",
          Q.topic_words(rows) == ["3 questions · new", "2 questions · too soon to say", "1 question · 66% here", "1 question · 84%"],
          Q.topic_words(rows))
    many = [row(f"Part {k}", 1, 70) for k in range(9)]
    check("qid words: past the rows shown, the rest named in a line", Q.TOPICS_SHOWN == 5
          and Q.more_topics(many) == "Also: Part 5, Part 6, Part 7 and 1 more"
          and Q.more_topics(many[:6]) == "Also: Part 5" and Q.more_topics(many[:5]) == "")
    check("qid words: a name stays as it is (the window shows it as plain text)",
          Q.topics(None, {"cids": {1}, "found": ["10"], "by": {"10": {1}}},
                   [tile("a", "<b>A", [1], 50), tile("b", "B", [2], 70)])[0]["name"] == "<b>A")


def test_commands():
    """Every duecrew: command the map emits has its handler (the suite's
    test_every_board_command_has_a_handler, for this front's)."""
    src = open(os.path.join(REPO, "due_crew", "board.py")).read()
    flow = open(os.path.join(REPO, "due_crew", "team_flow.py")).read()
    emitted = set(re.findall(r'_pycmd\(f"(insmap[a-z]*)', src))
    handled = set(re.findall(r'cmd == "([a-z0-9]+)"', flow))
    check("commands: the map's are handled; its Study is neither emitted nor handled (Sam's picks)",
          emitted <= handled and "insmapstudy" not in emitted | handled and not hasattr(T, "weakest"), (emitted, handled))


def main():
    for n in [n for n in list(globals()) if n.startswith("test_")]:
        globals()[n]()
    bad = [c for c in CHECKS if not c[1]]
    print(f"\n{len(CHECKS) - len(bad)}/{len(CHECKS)} checks passed")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
