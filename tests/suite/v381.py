"""The suite: 3.8.1: plans round three, why isn't it showing, the Fifteen, Pip."""

from due_crew import board
from due_crew.backend import api
from due_crew.backend import shapes
from due_crew.stats.queries import StatsQueries
import datetime
import fakes
import json
import os
import re
import sqlite3
import srcs
import sys
import tempfile
import types

from .base import KK, REPO, SUITE_FILE, TODAY, as_board, check, make_user_col, new_client, world
from .plans import _PlanGlue
from .board import _day, _open, _plan_col, _plan_units
from .v380 import _tag_col, _tags_of, dc_mw


def test_morning_keeps_unchanged_plan_docs_v381():
    """3.8.1 (plans, rethought): the day's first refresh asks with same=1; when
    the plans' stamp hasn't moved, each followed plan comes without its doc and
    the add-on keeps the one it has. A doc it doesn't have leaves its plans as
    they are, and the next refresh brings them all again."""
    store = world({"dre": "Dre", "maya": "Maya"})
    pid, code = store.add_plan("dre", "Step 1", "Step 1", _plan_units())
    maya = new_client(store, "maya", "Maya")
    labels = [_day(-i) for i in range(7)]
    maya.follow_plan(code)
    saw = []
    real = store._plans_for_board
    store._plans_for_board = lambda me, same=False: (saw.append(same), real(me, same))[1]
    first = maya.fetch_board(labels, with_decks=True)
    kept = json.loads(json.dumps(maya.session.get("plans")))
    check("lean plans: the first morning brings each doc", first["plans_fresh"] and saw[-1] is False
          and kept and kept[0]["doc"]["units"])
    again = maya.fetch_board(labels, with_decks=True)
    check("lean plans: nothing moved: no doc comes, the plans stay whole", again["plans_fresh"] and saw[-1] is True
          and maya.session.get("plans") == kept, str(saw))
    store.add_post(pid, "dre", "Read chapter 6 first.")
    moved = maya.fetch_board(labels, with_decks=True)
    check("lean plans: the stamp moved: the docs come again, with the post", moved["plans_fresh"] and saw[-1] is False
          and maya.session["plans"][0]["posts"][0]["text"] == "Read chapter 6 first.")
    # an older add-on's docs (its cleaner left out what it didn't know) are never kept: the first morning brings them whole
    maya.session["plans_by"] = "3.7.9"
    maya.session["plans"] = [dict(p, doc=dict(p["doc"], units=p["doc"]["units"][:1])) for p in maya.session["plans"]]
    up = maya.fetch_board(labels, with_decks=True)
    check("lean plans: after an upgrade, the docs come whole once, and are kept from then on",
          up["plans_fresh"] and saw[-1] is False and len(maya.session["plans"][0]["doc"]["units"]) == len(_plan_units())
          and maya.session.get("plans_by") == api._KEPT_BY and api._KEPT_BY == json.load(open(os.path.join(REPO, "due_crew", "manifest.json")))["version"])
    maya.fetch_board(labels, with_decks=True)
    check("lean plans: the next morning asks with same=1 again", saw[-1] is True)
    maya.session["plans"] = []  # a session that lost its plans but kept its stamp
    lost = maya.fetch_board(labels, with_decks=True)
    check("lean plans: a doc I don't have: nothing of them is used, the stamp is let go",
          not lost["plans_fresh"] and maya.session["plans"] == [] and maya.session.get("plans_pv") == "")
    back = maya.fetch_board(labels)
    check("lean plans: the next refresh brings them all", back["plans_fresh"] and maya.session["plans"]
          and maya.session["plans"][0]["doc"]["units"] and maya.session.get("plans_pv"))
    # a kept doc goes through clean_plan again: cleaning must change nothing, or the morning would read an update
    q = '"tag:#V::Ceph" "tag:DueCrew::MS2::SLG_12"'
    rich = {"deck": "Big Step 1", "deckUrl": "https://example.com/deck", "tagroot": "MS2", "end": "2026-12-01",
            "phases": {"catchup": 3, "taper": 7}, "pace": {"mode": "daily", "daily": 20, "days": [1, 1, 1, 1, 1, 0, 0]},
            "reviews": [{"day": "2026-10-20", "from": "u1", "to": "u2"}], "events": [{"id": "q", "name": "Heme <quiz>", "day": "2026-10-16"}],
            "every": [{"k": "do", "t": "Practice questions", "r": "4"}],
            "tags": [{"id": "t12", "name": "SLG 12", "notes": ["guid000002"], "cards": [["guid000001", 1]], "tags": ["#V::Pharm"]}],
            "remarks": [{"id": "r1", "tag": "#V::Pharm", "text": "Read chapter 6 first"}, {"id": "r2", "card": ["guid000005", 1], "text": "Two"}],
            "units": [{"id": "u1", "name": "Ceph", "opens": "2026-10-08", "due": "2026-10-12", "even": True, "tags": [], "decks": [],
                       "cards": [["guid000009", 0]], "search": [q], "sn": {q: 12}, "cut": [{"tag": "#V::Ceph", "in": "t12", "q": q}], "for": "q",
                       "todo": [{"k": "read", "t": "Chapter 6"}], "notes": ["Ab3$kL9qZ1"], "nids": [1690000000000], "idr": [["Ab3$kL9qZ1", 0]],
                       "ids": ["guid000002"], "pl": [["#V::Pharm::Ceph", 12]]},
                      {"id": "u2", "name": "SLG 12", "opens": "2026-10-09", "tags": ["DueCrew::MS2::SLG_12"], "decks": ["Big Step 1::Extras"]}]}
    once = shapes.clean_plan({"id": "abcdefgh12", "version": 3, "doc": rich, "share": True})
    check("lean plans: a kept doc cleaned again is the same doc (every part of a rich plan)",
          once == shapes.clean_plan({"id": "abcdefgh12", "version": 3, "doc": once["doc"], "share": True}))
    old = store.handle("GET", f"{api.API_BASE}/board?decks=1&wk=&got=0&pv={maya.session['plans_pv']}",
                       {"Authorization": f"Bearer {store.session_for('maya')}"})
    body = old.json()
    check("lean plans: an older add-on (no same=1) still gets every doc", old.status_code == 200 and body.get("plans")
          and all("doc" in p and not p.get("same") for p in body["plans"]), str(body)[:200])


def test_builder_work_and_suggestions_v381():
    """3.8.1 (plans, rethought): the builder warns about the work a day asks
    (each date spread to its due date over the plan's days), not about what
    opens on it; and a date's name points at the deck's tags. Needs node."""
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        print("SKIP builder work: no node")
        return
    app = open(os.path.join(REPO, "site", "public", "app.js")).read()
    b = open(os.path.join(REPO, "site", "public", "builder.js")).read()
    head = app[app.index("const MONTHS"):app.index("const today =")]
    sched_js = app[app.index("const Sched = (() => {"):app.index("// ---- 3.2: home")]
    work_js = b[b.index("const Work = (() => {"):b.index("/** 3.8.0: a plan's squad")]
    doc = {"deck": "x", "units": [
        {"id": "rp", "name": "Renal physiology", "opens": "2026-10-12"},           # to the day before the next
        {"id": "rx", "name": "Renal pharm", "opens": "2026-10-19", "due": "2026-10-20"},
        {"id": "pu", "name": "Pulm", "opens": "2026-10-26", "due": "2026-10-30", "even": True}]}
    tree = [["#Videos::Renal", 900], ["#Videos::Renal::Physiology", 212], ["#Videos::Renal::Pharm", 190],
            ["#Videos::Cardio::Physiology", 300], ["#Videos::Cardio::Arrhythmias", 61], ["#Book::Pharm::Ch07_Diuretics", 64],
            ["Step1::Pulm", 288], ["#Videos::Heme::Herpes_Viruses", 88]]
    prog = head + "\n" + sched_js + "\n" + work_js + (
        f"const doc = {json.dumps(doc)}; const tree = {json.dumps(tree)};\n"
        "const all = [1, 1, 1, 1, 1, 1, 1], wk = [1, 1, 1, 1, 1, 0, 0];\n"
        "const tot = { rp: 212, rx: 190, pu: 288 };\n"
        "const w = Work.map(doc, (u) => tot[u.id], all);\n"
        "const w5 = Work.map(doc, (u) => tot[u.id], wk);\n"
        "const sum = (m) => [...m.values()].reduce((a, x) => a + x.n, 0);\n"
        "console.log(JSON.stringify({"
        " rp: Work.spread(doc, doc.units[0], 212, all), mon: w.get('2026-10-12').n, sum: sum(w), sum5: sum(w5),"
        " sat: w5.get('2026-10-17') || null, rx: Work.spread(doc, doc.units[1], 190, all),"
        " over: Work.over(w, 20), none: Work.over(w, 0), rv: Reviews.weeks(w), pk: Reviews.peak(Reviews.weeks(w)),"
        " ab: [7.4, 42, 187, 1234].map(Reviews.about), curve: Reviews.CURVE,"
        " s1: Suggest.tags('Renal physiology', tree), s2: Suggest.tags('Cardiac physiology', tree),"
        " s3: Suggest.tags('Lecture 14: Herpes viruses', tree), s4: Suggest.tags('Read: Chapter 3', tree),"
        " s5: Suggest.tags('Arrhythmia', tree, (p) => p.includes('Cardio')), s6: Suggest.tags('Diuretics', tree),"
        " s7: Suggest.tags('Cardio arrhythmia', tree), s8: Suggest.tags('Renal and cardio physiology', tree),"
        " n1: Suggest.tags('SLG 12', [['DueCrew::B1::SLG_3', 9], ['DueCrew::B1::SLG_12', 40], ['DueCrew::B1::SLG_1', 5]]),"
        " n2: Suggest.tags('Block 2 cardiology', [['Block_3::Cardiology', 9], ['Block_2::Cardiology', 30]]),"
        " n3: Suggest.tags('Hemolytic anemia', [['#Path::03_Hemolytic_Anemia', 20]]),"
        " n4: Suggest.tags('Lecture 14: Herpes viruses', [['#Videos::05_Herpes_Viruses', 88]]) }));")
    out = subprocess.run([node, "-e", prog], capture_output=True, text=True, timeout=60)
    try:
        r = json.loads(out.stdout)
    except ValueError:
        check("builder work: runs", False, out.stdout + out.stderr)
        return
    check("work: a week's date is its daily share, every day of its week, all of it",
          len(r["rp"]) == 7 and sum(n for _d, n in r["rp"]) == 212 and r["mon"] == 31 and max(n for _d, n in r["rp"]) == 31, str(r["rp"]))
    check("work: a due date makes the window; every card counted once", [d for d, _n in r["rx"]] == ["2026-10-19", "2026-10-20"]
          and r["sum"] == 212 + 190 + 288 and r["sum5"] == 212 + 190 + 288, str(r["rx"]))
    check("work: a day off asks nothing", r["sat"] is None)
    from due_crew import ahead as AH
    check("3.9.2 reviews by week: the builder's curve is the add-on's typical one (the twins)",
          r["curve"] == list(AH.GENERIC[0]), r["curve"][:5])
    rv = r["rv"]
    check("3.9.2 reviews by week: from the first date, four weeks past the last; the busiest named, as the add-on rounds",
          rv[0]["a"] == "2026-10-12" and rv[-1]["a"] >= "2026-11-23" and r["pk"]["n"] == max(x["n"] for x in rv)
          and 0 < r["pk"]["n"] < 212 + 190 + 288 and r["ab"] == ["7", "40", "185", "1,230"], str(rv[:3]) + str(r["pk"]))
    check("work: days over the pace come as runs, with their most", r["over"][0]["a"] == "2026-10-12"
          and r["over"][0]["b"] >= "2026-10-18" and r["over"][0]["top"] >= 31 and r["none"] == [], str(r["over"]))
    check("suggest: every word of the name, one in the tag's last part",
          r["s1"] == [["#Videos::Renal::Physiology", 212]] and r["s2"] == [["#Videos::Cardio::Physiology", 300]], str(r["s1"]) + str(r["s2"]))
    check("suggest: lecture words and numbers aside; nothing for a chapter", r["s3"] == [["#Videos::Heme::Herpes_Viruses", 88]]
          and r["s4"] == [], str(r["s3"]))
    check("suggest: what's placed is left out; a word inside a part", r["s5"] == [] and r["s6"] == [["#Book::Pharm::Ch07_Diuretics", 64]])
    check("suggest: a name's number picks its own tag (SLG 12, never SLG 3 or 1); a deck's 03_ order is no number",
          r["n1"] == [["DueCrew::B1::SLG_12", 40]] and r["n2"] == [["Block_2::Cardiology", 30]]
          and r["n3"] == [["#Path::03_Hemolytic_Anemia", 20]] and r["n4"] == [["#Videos::05_Herpes_Viruses", 88]], str([r["n1"], r["n2"], r["n3"], r["n4"]]))
    check("builder: a renamed tag is followed string by string (never inside a number), a kept-without-extras tag is placed",
          "const follow = (u) => (ren.length ? walk(u, \"\") : u);" in b and "JSON.parse(x)" not in b
          and "const p = extrasOf(q); return p ? `tag:${p}` : null;" in b
          and b.index("const extrasOf = (q) =>") < b.index("const placedKeys = () =>"))
    check("suggest: half a name is noise; all but one of three words will do",
          r["s7"] == [["#Videos::Cardio::Arrhythmias", 61]] and r["s8"] and all(p.endswith("Physiology") for p, _n in r["s8"]), str(r["s7"]) + str(r["s8"]))
    check("builder: the heavy note and the Text preview read the day's work",
          "const run = Work.over(work, cap)" in b and "Work.over(workMap({ ...doc, units: after }, placed), cap)" in b
          and "e.load > cap * 1.25" not in b)
    check("builder: a named date shows its name on the calendar; a doubled last word its parent",
          'h("span", { class: "dname", title: u.name }, u.name)' in b and "const chipLabel = (key, placed)" in b)
    check("builder: a named date's suggestions add a tag in one click", "Suggest.tags(u.name, tree.tags, skip)" in b
          and "u.tags = [...(u.tags || []), p]; mark(); draw();" in b)


def test_study_for_a_quiz_v381():
    """3.8.1 (plans, rethought): from three days out, the plan's box offers
    Study for a quiz: one Due Crew deck of the open cards of every date that
    preps for it (not one after it), the shakiest first, Anki's own step."""
    import due_crew as dc
    from due_crew import plans as P, board
    from aqt.deckbrowser import DeckBrowser
    t = _day(0)
    doc = {"units": [{"id": "a", "name": "A", "opens": _day(-2), "for": "q"}, {"id": "b", "name": "B", "opens": _day(-1), "for": "q"},
                     {"id": "c", "name": "C", "opens": _day(4), "for": "q"},          # after the quiz: reinforcement
                     {"id": "d", "name": "D", "opens": _day(1), "for": "q"}],         # not open yet
           "events": [{"id": "q", "name": "Heme <quiz>", "day": _day(3)}, {"id": "z", "name": "Later", "day": _day(9)}]}
    prog = {"a": [40, 10, 40], "b": [30, 0, 30], "c": [5, 0, 5]}
    qz = P.quiz(doc, t, prog)
    check("quiz: its dates open by today and before it; their opened cards counted",
          qz == {"id": "q", "name": "Heme <quiz>", "day": _day(3), "units": ["a", "b"], "open": 70}, qz)
    check("quiz: not four days out, not with nothing open, not after it",
          P.quiz(doc, _day(-1), prog) is None and P.quiz(doc, t, {}) is None and P.quiz(doc, _day(4), prog) is None)
    html = board._plan_card_html(dict({"id": "p1", "title": "Plan"}, prep={"name": "Heme <quiz>", "day": _day(3), "when": "Thu", "left": 1, "today": False},
                                      quiz=dict(qz, when="Thu")))
    check("quiz: one line for the event, its prep days and its cards, Study for it; its name escaped",
          "duecrew:planquiz:p1:q" in html and "Heme &lt;quiz&gt;" in html and "Heme <quiz>" not in html
          and html.count("Heme &lt;quiz&gt;") == 1 and "1 more day of prep &middot; 70 cards open from its sets" in html, html[-1200:])
    html2 = board._plan_card_html(dict({"id": "p1", "title": "Plan"}, prep={"name": "Other", "day": _day(1), "when": "Tue", "left": 0},
                                       quiz=dict(qz, when="Thu", today=False)))
    check("quiz: beside the prep line when that names another event", "70 cards open from its sets" in html2
          and "planquiz:p1:q" in html2 and "<b>Other</b>" in html2)
    units = [dict(u, **{"for": "q"}) if u["id"] in ("hf", "ar") else u for u in _plan_units()]
    store, pid, code, maya = _v381_world(units, [{"id": "q", "name": "Cardio quiz", "day": _day(2)}])
    col = _plan_col()
    with _PlanGlue({"A": maya}, {"A": col}) as g:
        F = g.F
        plan, _ = maya.follow_plan(code)
        F.on_followed(plan, 10, None, "open")
        built, sel, moved = [], [], []

        def fake_filtered(c, name, cids, order=4, **kw):
            built.append((name, sorted(cids), order))
            col.decks.names[98] = name
            return True
        saved = (F._filtered, getattr(F.mw, "moveToState", None))
        F._filtered = fake_filtered
        col.decks.select = sel.append
        F.mw.moveToState = moved.append
        try:
            dc._on_js(False, as_board(f"duecrew:planquiz:{pid}:q"), DeckBrowser())
            dc._on_js(False, as_board(f"duecrew:planquiz:{pid}:nope"), DeckBrowser())
        finally:
            F._filtered = saved[0]
            if saved[1] is None:
                F.mw.__dict__.pop("moveToState", None)
            else:
                F.mw.moveToState = saved[1]
        check("quiz: one Due Crew deck of its dates' open cards, the shakiest first, and Anki's Study screen on it",
              built == [("Due Crew::Before Cardio quiz", [1, 2, 3], 2)] and sel == [98] and moved == ["overview"], (built, sel, moved))
        F._state["plan_progress"] = F.progress(col, F.followed(), F._state_cfg())
        p = next(x for x in F.followed() if x["id"] == pid)
        v = F.card_view(p, F._state_cfg()[pid], F._state["plan_progress"][pid], _day(0))
        check("quiz: the plan's box carries it from three days out", (v.get("quiz") or {}).get("id") == "q"
              and f"duecrew:planquiz:{pid}:q" in board._plan_card_html(v), v.get("quiz"))


def test_plan_tags_round_two_v381():
    """3.8.1, plan tags round two (Sam's picks on the mock): a date can keep a
    video's tag to the cards one of the plan's own tags holds (a cut, named
    for both, in the video's row); a plan tag can name single cards (Anki's
    tag goes on their notes; Due Crew reads just those cards); an SLG that
    changes reaches dates that opened, opening just what it adds."""
    from due_crew import plans as P, plan_flow as F
    from due_crew.backend import shapes
    video = "Step1_v12::#Videos::Pharm::Cephalosporins"
    conn = sqlite3.connect(":memory:")
    fakes.make_collection(conn)
    for cid, nid, ord_, tags in ((1, 1, 0, video), (11, 1, 1, video), (12, 1, 2, video), (2, 2, 0, video), (3, 3, 0, video),
                                 (4, 4, 0, "#Book::Ch07"), (5, 5, 0, "#Book::Ch07"), (6, 6, 0, "")):
        fakes.add_card(conn, cid, did=10, tags=tags, nid=nid, ord_=ord_)
    col = fakes.FakeCol(conn, fakes.day_cutoff_for(TODAY))
    col.decks = fakes.FakeDecks({10: "Step 1"})
    q = '"tag:DueCrew::MS2\\_Block\\_1::SLG\\_12" "tag:Step1\\_v*::#Videos::Pharm::Cephalosporins"'
    raw = {"deck": "Step 1", "tagroot": "MS2_Block_1",
           "tags": [{"id": "t12", "name": "SLG 12", "notes": ["guid000002", "guid000004"], "cards": [["guid000001", 1], ["gone", 0]]},
                    {"id": "t13", "name": "SLG 13", "cards": [["guid000005", 0]]}],
           "units": [{"id": "u1", "name": "Cephalosporins", "opens": "2026-10-08", "tags": [], "decks": [], "cards": [],
                      "search": [q, "tag:Other"], "cut": [{"tag": video, "in": "t12", "q": q}, {"tag": video, "in": "nope", "q": "tag:Other"}]},
                     {"id": "u2", "name": "SLG 12", "opens": "2026-10-09", "tags": ["DueCrew::MS2_Block_1::SLG_12"], "decks": [], "cards": []},
                     {"id": "u3", "name": "Book", "opens": "2026-10-10", "tags": ["#Book::Ch07"], "decks": [], "cards": []}]}
    doc = shapes.clean_plan_doc(raw)
    u1, u2, u3 = doc["units"]
    check("r2: a cut is kept with its tag's name; one whose tag is gone is left to its search",
          u1.get("cut") == [{"tag": video, "in": "t12", "q": q, "nm": "SLG 12"}], str(u1.get("cut")))
    check("r2: a tag of single cards alone is a tag; its cards are kept", doc["tags"][1].get("cards") == [["guid000005", 0]], str(doc["tags"]))
    check("r2: a date using the plan's tags carries what they hold (ptv); one that doesn't, nothing",
          bool(u1.get("ptv")) and bool(u2.get("ptv")) and "ptv" not in u3)
    idx = P.DeckIndex(col, 10)
    check("r2: a cut is the video's cards the SLG holds: a whole note's, and just the single cloze named",
          idx.match(u1, None, doc) == {2, 11}, str(idx.match(u1, None, doc)))
    check("r2: a date naming the plan's tag reads what it holds: the single card, never its siblings",
          idx.match(u2, None, doc) == {2, 4, 11}, str(idx.match(u2, None, doc)))
    check("r2: without the doc, the Anki tag and the search are read, as an older add-on does",
          idx.match(u2, None, "Step 1") == set())  # the tag isn't on any note yet
    items = P.topic_items([u1])
    check("r2: a cut is named for both, in its video's group; its search isn't listed again",
          [(g, x) for g, x, _s in items] == [("Videos", "Cephalosporins \u00b7 SLG 12"), ("Search", "tag:Other")], str(items))
    check("r2: a cut's topic finds its cards, as the date does", idx.match(items[0][2], None, doc) == {2, 11})
    got = P.parts(idx, dict(u1, tags=["#Book::Ch07"]), None, doc)
    check("r2: a cut counts in its video's row of Due's progress",
          sorted(g for g, _s, _t, _b in got) == ["Other", "Videos"] and dict((g, t) for g, _s, t, _b in got)["Videos"] == 2, str(got))
    applied, res = P.sync_tags(col, idx, doc, {}, "Due Crew: tags")
    check("r2: the tag goes on the notes of its single cards (Anki tags notes); missing ones are counted",
          "DueCrew::MS2_Block_1::SLG_12" in _tags_of(col, 1) and "DueCrew::MS2_Block_1::SLG_12" in _tags_of(col, 2)
          and "DueCrew::MS2_Block_1::SLG_13" in _tags_of(col, 5) and res["missing"] == {"SLG 12": 1}, str(res))
    check("r2: with the tag on, a date naming it still reads just the single card", P.DeckIndex(col, 10).match(u2, None, doc) == {2, 4, 11})
    idx = P.DeckIndex(col, 10)
    pt = idx.plan_part(u1, doc)
    src = P.unit_sources(u1, 10, None, pt)
    check("r2: an opened date keeps what the plan's tags held then; a cut's search is the cut's",
          pt == {2, 11} and src[5] == ["tag:Other"] and src[-1] == {"pt": [2, 11]} and idx.plan_part(u3, doc) is None, str(src))
    # the SLG grows by a note: the date reads as changed, and opening it opens just the new card
    raw2 = json.loads(json.dumps(raw))
    raw2["tags"][0]["notes"].append("guid000003")
    doc2 = shapes.clean_plan_doc(raw2)
    v1, v2 = doc2["units"][0], doc["units"][0]
    check("r2: an SLG that changes makes the dates using it read as changed", P.unit_sig(v1, 10) != P.unit_sig(v2, 10)
          and P.unit_sig(doc2["units"][2], 10) == P.unit_sig(u3, 10))
    st = {"deck_id": 10, "applied": {"u1": P.unit_sig(u1, 10)}, "src": {"u1": src}}
    check("r2: opening the changed date opens just what the SLG added", F._unit_cids(P.DeckIndex(col, 10), st, v1, doc2) == {3},
          str(F._unit_cids(P.DeckIndex(col, 10), st, v1, doc2)))
    lean = shapes.clean_authored({"id": "p" + "0" * 15, "version": 1, "name": "MS2 Block 1", "doc": raw})
    snap = P.ids_snapshot(P.DeckIndex(col, 10), shapes.clean_plan_doc(dict(raw, units=lean["doc"]["units"])))
    check("r2: the author's note ids for a cut date go up with its cuts, so the Worker keeps them only while they're these",
          snap["u1"][3] == [[video, "t12"]] and "guid000001" in snap["u1"][2] and "guid000002" in snap["u1"][2], str(snap.get("u1")))


# ---------------------------------------------------------------- 3.8.1: the follower side of plans

def _v381_world(units=None, events=None):
    """A plan by Dre (_plan_units unless given) and Maya, who'll follow it."""
    store = world({"dre": "Dre", "maya": "Maya"})
    pid, code = store.add_plan("dre", "Step 1", "Step 1", units or _plan_units())
    if events:  # saved with the dates, so a date's `for` names one
        store.plans[pid]["doc"] = store._plan_doc({"deck": "Step 1", "units": units or _plan_units(), "events": events})
    return store, pid, code, new_client(store, "maya", "Maya")


class _SyncBg:
    """plan_flow's background jobs run at once, their done after them."""

    def __init__(self, F):
        self.F = F

    def __enter__(self):
        self.saved = self.F._bg
        self.F._bg = lambda job, done=None: done(job()) if done else job()
        return self

    def __exit__(self, *exc):
        self.F._bg = self.saved
        return False


def _undo_here(F, col, fn):
    """fn() with Anki's undo run on the spot (an Anki without CollectionOp)."""
    sys.modules["aqt.operations"] = None
    was = getattr(F.mw, "undo", None)
    F.mw.undo = col.undo
    try:
        fn()
    finally:
        sys.modules.pop("aqt.operations", None)
        if was is None:
            del F.mw.undo
        else:
            F.mw.undo = was


def test_put_back_is_not_hold_back_v381():
    """3.8.1: Put back (at my own pace) kept its cards in `held`, and the
    morning read any held card as a yes to Hold back: from then on each date
    not opened yet had its new cards suspended. The yes is its own flag now
    (`hold_yes`: Follow's Hold back, or the question on first sight or on
    going to my own pace); a state from before reads as a yes on the plan's
    dates only. And a card a date opened here is never held, even when the
    author moves it to a later date."""
    from due_crew import plans as P
    from due_crew import plan_flow as F
    store, pid, code, maya = _v381_world()
    col = _plan_col()
    col.db.conn.execute("UPDATE cards SET queue = 0 WHERE id IN (4, 6)")  # later dates' new cards, active
    with _PlanGlue({"A": maya}, {"A": col}) as g:
        plan, _ = maya.follow_plan(code, own="ready")
        F.on_followed(plan, 10, None, "open")
        F.open_next(pid)  # Heart failure
        F._state["plan_progress"] = F.progress(col, F.followed(), F._state_cfg())
        F.put_back_own(pid)
        st = F._state_cfg()[pid]
        check("put back: its cards shut and kept for Stop, and that's no yes to Hold back",
              not ({1, 2} & _open(col)) and {1, 2} <= set(st.get("held") or []) and st.get("hold_yes") is False, str(st))
        n = F.hold_new(F.followed(), F._state_cfg(), _day(0), morning=True)
        pc = g.state()
        pc["plans_day"] = _day(-1)
        F._psave(pc)
        F.maybe_morning(False)
        check("put back: no morning holds a later date's cards after it", n == 0 and {4, 6} <= _open(col)
              and g.state()["plans_day"] == _day(0), sorted(_open(col)))
        asked = []
        F.offer_hold([pid], ask=lambda name, k: asked.append(k) or True)
        st = F._state_cfg()[pid]
        check("hold back asked, yes: the later dates' new cards held, and the yes kept",
              asked == [2] and not ({4, 6} & _open(col)) and st["hold_yes"] is True, (asked, st.get("hold_yes")))
        units = _plan_units()
        units[4] = dict(units[4], tags=["Step1::Renal", "Step1::Cardiology"])  # card 9 onto a later date
        store.edit_plan(pid, units)
        col.db.conn.execute("UPDATE cards SET queue = 0 WHERE id = 9")
        maya.fetch_board([_day(0)], with_decks=True)
        F.hold_new(F.followed(), F._state_cfg(), _day(0))
        check("hold back, yes: what an author adds to a later date is held too",
              9 not in _open(col) and 9 in F._state_cfg()[pid]["held"])
    a, b, c = {"held": [1]}, {"held": [1]}, {}
    ya, yb, yc = F._hold_yes({"own": ""}, a), F._hold_yes({"own": "ready"}, b), F._hold_yes({"own": ""}, c)
    check("before 3.8.1: held cards on the plan's dates were a yes; at my own pace a no until asked; settled once",
          ya is True and a["hold_yes"] is True and yb is False and b["hold_yes"] is False
          and yc is False and "hold_yes" not in c and F._hold_yes({"own": ""}, b) is False, (a, b, c))

    store2, pid2, code2, kai = _v381_world()
    col2 = _plan_col()
    col2.db.conn.execute("UPDATE cards SET queue = 0 WHERE id = 4")
    with _PlanGlue({"B": kai}, {"B": col2}):
        plan, _ = kai.follow_plan(code2)
        F.on_followed(plan, 10, None, "open", hold=True)
        st = F._state_cfg()[pid2]
        check("follow with Hold back: today's dates open, a later date's card held, the yes kept",
              {1, 2, 3} <= _open(col2) and 4 not in _open(col2) and st["hold_yes"] is True and st["held"] == [4], str(st))
        units = _plan_units()
        units[1] = dict(units[1], tags=["Step1::Cardiology"])                          # Arrhythmia's card...
        units[4] = dict(units[4], tags=["Step1::Renal", "Step1::Cardio::Arrhythmia"])  # ...moved to a later date
        store2.edit_plan(pid2, units)
        kai.fetch_board([_day(0)], with_decks=True)
        p = F.followed()[0]
        bare = P.holdable(P.DeckIndex(col2, 10), p["doc"], _day(0), None, st["applied"])
        F.hold_new(F.followed(), F._state_cfg(), _day(0))
        check("moved later by the author: a card a date opened here is never held again",
              3 in bare and 3 in _open(col2) and 3 not in F._state_cfg()[pid2]["held"], (sorted(bare), sorted(_open(col2))))


def test_own_pace_first_seen_v381():
    """3.8.1: a plan at my own pace, first seen on this computer (followed on
    the site, or on another computer). The morning skipped every date before
    today, so each left Up next for good. At my own pace no date has passed:
    one whose cards are all open here counts as opened (of a day this
    computer doesn't know, so not in my pace), the rest stay Up next, and
    the hold-back question counts only those."""
    from due_crew import plans as P
    store, pid, code, maya = _v381_world()
    col = _plan_col()
    # Extras opened on the other computer (AnkiWeb brought it); one of Heart failure's cards is active
    col.db.conn.execute("UPDATE cards SET queue = 0 WHERE id IN (1, 4)")
    with _PlanGlue({"A": maya}, {"A": col}) as g:
        F = g.F
        maya.follow_plan(code, own="ready")  # on the site
        maya.fetch_board([_day(0)], with_decks=True)
        F.maybe_morning(False, fresh=True)
        st = g.state()["plans"][pid]
        p = next(x for x in F.followed() if x["id"] == pid)
        check("first seen at my own pace: nothing skipped; a date all open here counts as opened, of no day here",
              sorted(st["applied"]) == ["ex", "rn"] and not any(v.startswith("skip:") for v in st["applied"].values())
              and st["own_opened"] == {"ex": "", "rn": ""}, str(st))
        check("first seen at my own pace: the earlier dates are still Up next",
              [u["id"] for u in P.up_next(p["doc"], st["applied"])] == ["hf", "ar", "cz"])
        v = F.card_view(p, st, F.progress(col, [p], F._state_cfg())[pid], _day(0))
        check("first seen: not in my pace; Up next starts at the first date",
              "pace" not in v["own"] and v["own"]["next"]["uid"] == "hf", str(v["own"]))
        asked = []
        F.offer_hold([pid], ask=lambda name, n: asked.append(n) or False)
        check("first seen: the hold-back question counts the dates I haven't opened, not one opened elsewhere",
              asked == [1], asked)


def test_browse_open_claims_only_what_it_opened_v381():
    """3.8.1: at my own pace, an open from Browse counted every Up next date
    whose cards were all open as opened today, so on a deck whose cards are
    all active one open emptied Up next. Now only a date the open touched,
    with a card shut before it, counts."""
    from due_crew import plans as P
    store, pid, code, maya = _v381_world()
    col = _plan_col()
    col.db.conn.execute("UPDATE cards SET queue = 0 WHERE queue = -1")  # a deck imported all active
    with _PlanGlue({"A": maya}, {"A": col}) as g:
        F = g.F
        plan, _ = maya.follow_plan(code, own="ready")
        F.on_followed(plan, 10, None, "open")
        n = F.open_cards_now([4], "Extras", first=False)
        check("browse, a deck all active: nothing opens, and no date counts as opened",
              n == 0 and not F._state_cfg()[pid].get("applied"), str(F._state_cfg()[pid].get("applied")))
        col.db.conn.execute("UPDATE cards SET queue = -1 WHERE id IN (2, 3)")
        n = F.open_cards_now([3], "Arrhythmia", first=False)
        st = F._state_cfg()[pid]
        p = next(x for x in F.followed() if x["id"] == pid)
        check("browse: the date it opened counts as opened today; one still shut, or one it didn't touch, doesn't",
              n == 1 and list(st["applied"]) == ["ar"] and st["own_opened"] == {"ar": _day(0)}
              and [u["id"] for u in P.up_next(p["doc"], st["applied"])] == ["hf", "ex", "cz", "rn"], str(st))


def test_not_today_at_own_pace_v381():
    """3.8.1: at my own pace, Not today after a morning took the date I had
    opened out of `applied` (Up next again) and lost what the author had
    added (the own-pace morning ignored `later`). Now the date stays opened
    as it was and the addition opens tomorrow morning; a next date that
    opened by itself is Up next again till then."""
    from due_crew import plans as P
    store, pid, code, maya = _v381_world()
    col = _plan_col()
    with _PlanGlue({"A": maya}, {"A": col}):
        from due_crew import plan_flow as F
        plan, _ = maya.follow_plan(code, own="ready")
        F.on_followed(plan, 10, None, "open")
        F.open_next(pid)  # Heart failure: 1, 2
        was_sig = F._state_cfg()[pid]["applied"]["hf"]
        units = _plan_units()
        units[0] = dict(units[0], tags=units[0]["tags"] + ["Step1::Cardiology"])  # the author adds card 9 to it
        store.edit_plan(pid, units)
        maya.fetch_board([_day(0)], with_decks=True)
        res = F._open_now(F.followed())
        check("own pace: the morning opens what an author added to a date I opened, with Not today",
              res["n"] == 1 and 9 in _open(col) and (F.morning_opened() or {}).get("n") == 1, str(res))
        _undo_here(F, col, lambda: F.undo_morning(put_off_too=True))
        st = F._state_cfg()[pid]
        p = next(x for x in F.followed() if x["id"] == pid)
        check("not today: the date stays opened as it was, the addition waits for tomorrow",
              9 not in _open(col) and {1, 2} <= _open(col) and st["applied"]["hf"] == was_sig
              and st["later"] == {"hf": _day(1)} and "hf" not in [u["id"] for u in P.up_next(p["doc"], st["applied"])], str(st))
        state = F._state_cfg()
        again = F.run(col, F.followed(), state, _day(0))
        check("not today: not again today", again["n"] == 0 and 9 not in _open(col), str(again))
        tomorrow = F.run(col, F.followed(), state, _day(1))
        check("not today: tomorrow's morning opens it", tomorrow["n"] == 1 and 9 in _open(col)
              and not state[pid].get("later"), str(tomorrow))

    store2, pid2, code2, kai = _v381_world()
    col2 = _plan_col()
    with _PlanGlue({"B": kai}, {"B": col2}):
        plan, _ = kai.follow_plan(code2, own="next")
        F.on_followed(plan, 10, None, "open")
        F.open_next(pid2)
        col2.db.conn.execute("UPDATE cards SET type = 2, queue = 2 WHERE id IN (1, 2)")  # seen
        pc = F._pcfg()
        pc["plans"][pid2]["own_opened"]["hf"] = _day(-1)
        F._psave(pc)
        res = F._open_now(F.followed())
        check("next: seen the last one, the morning opens the next by itself", res["names"] == ["Arrhythmia"] and 3 in _open(col2), str(res))
        _undo_here(F, col2, lambda: F.undo_morning(put_off_too=True))
        st = F._state_cfg()[pid2]
        p = next(x for x in F.followed() if x["id"] == pid2)
        check("next, not today: Up next again, opening tomorrow morning",
              3 not in _open(col2) and "ar" not in st["applied"] and "ar" not in (st.get("own_opened") or {})
              and P.up_next(p["doc"], st["applied"])[0]["id"] == "ar" and st["later"] == {"ar": _day(1)}, str(st))
        state = F._state_cfg()
        check("next, not today: not again today", F.run(col2, F.followed(), state, _day(0))["n"] == 0 and 3 not in _open(col2))
        check("next, not today: tomorrow's morning opens it",
              F.run(col2, F.followed(), state, _day(1))["names"] == ["Arrhythmia"] and 3 in _open(col2))


def test_open_now_on_a_closed_date_v381():
    """3.8.1: a date closed again with Edit › Undo stayed shut: Open now was
    only on dates still to come, and opening a date that had opened opened
    only what the author had changed since. Now the week offers Open now on
    a date that opened here and has none of its cards open, and it opens
    whole."""
    import due_crew as dc
    from aqt.deckbrowser import DeckBrowser
    store, pid, code, maya = _v381_world()
    col = _plan_col()
    with _PlanGlue({"A": maya}, {"A": col}):
        from due_crew import plan_flow as F
        plan, _ = maya.follow_plan(code)
        F.on_followed(plan, 10, None, "open")
        opened = {1, 2, 3} <= _open(col)
        col.undo()  # Edit › Undo
        p = next(x for x in F.followed() if x["id"] == pid)
        view = lambda: board._plan_card_html(dict(F.card_view(p, F._state_cfg()[pid], F.progress(col, [p], F._state_cfg())[pid],
                                                              _day(0)), id=pid))
        html = view()
        check("closed by Undo: still opened here, and today's date offers Open now",
              opened and not ({1, 2, 3} & _open(col)) and "ar" in F._state_cfg()[pid]["applied"]
              and f"duecrew:plannow:{pid}:ar" in html, html[:300])
        dc._on_js(False, as_board(f"duecrew:plannow:{pid}:ar"), DeckBrowser())
        check("Open now (sent as the board does): the date opens whole, in one step; then no Open now",
              3 in _open(col) and col.undo_status().undo == "Due Crew: open Arrhythmia"
              and f"duecrew:plannow:{pid}:ar" not in view(), col.undo_status().undo)


def test_morning_open_is_the_last_step_v381():
    """3.8.1: the morning held back, set the catch-up's limit and built the
    day's checkpoints after it opened, so the open wasn't Anki's latest
    step and Not today went missing. They come before it now."""
    store, pid, code, maya = _v381_world()
    col = _plan_col()
    col.db.conn.execute("UPDATE cards SET queue = 0 WHERE id = 4")
    with _PlanGlue({"A": maya}, {"A": col}) as g:
        F = g.F
        plan, _ = maya.follow_plan(code)
        F.on_followed(plan, 10, None, "open", hold=True)  # Extras' card held till its day
        units = _plan_units()
        units[4] = dict(units[4], tags=["Step1::Renal", "Step1::Cardiology"])  # a later date gains card 9
        store.edit_plan(pid, units)
        col.db.conn.execute("UPDATE cards SET queue = 0 WHERE id = 9")
        g.today["d"] = _day(3)  # Extras' morning
        maya.fetch_board([_day(3)], with_decks=True)
        pc = g.state()
        pc["plans_day"] = _day(2)
        F._psave(pc)
        F.maybe_morning(False, fresh=True)
        steps = [s[0] for s in col.undo_steps]
        check("morning: it holds back what the author added, then opens; the open is Anki's latest step, so Not today shows",
              9 not in _open(col) and 4 in _open(col)
              and steps[-2:] == ["Due Crew: hold back Step 1", "Due Crew: open Extras"]
              and F.morning_opened() == {"n": 1, "sync": False}, steps)
    src = srcs.flow_src()
    morning = src[src.index("def maybe_morning"):src.index("def _morning_waits")]
    mid = src[src.index("def midday"):src.index("def hold_new")]
    check("morning: hold back, the catch-up's limit and the checkpoints come before the open; midday holds before it opens",
          morning.index("hold_new(") < morning.index("apply_catch()") < morning.index("build_checks(")
          < morning.index('_open_now([p for p in plan_list if not p.get("paused")]')
          and mid.index("hold_new(") < mid.index("_open_now("))


def test_resume_at_own_pace_v381():
    """3.8.1: ending a pause at my own pace asked about the plan's dates, and
    "Start from the next date" turned my own pace off inside run and
    skipped every passed date out of Up next. At my own pace it resumes
    without asking."""
    from due_crew import plans as P
    store, pid, code, maya = _v381_world()
    col = _plan_col()
    asked = []
    fakes_ui = {"due_crew.ui.days_dialog": types.SimpleNamespace(ask_back=lambda *a, **k: asked.append("back") or "push",
                                                                 ask_pause=lambda *a, **k: None),
                "due_crew.ui.follow_dialog": types.SimpleNamespace(ask_catch_up=lambda *a, **k: asked.append("catch") or "skip")}
    saved = {k: sys.modules.get(k) for k in fakes_ui}
    sys.modules.update(fakes_ui)
    skipped = lambda st: [k for k, v in (st.get("applied") or {}).items() if str(v).startswith("skip:")]
    try:
        with _PlanGlue({"A": maya}, {"A": col}) as g, _SyncBg(g.F):
            F = g.F
            plan, _ = maya.follow_plan(code, own="ready")
            F.on_followed(plan, 10, None, "open")
            maya.set_days(pid, paused=True, since=_day(-5), until=_day(-1))
            F.back(pid)
            st = F._state_cfg()[pid]
            f = store.follows[(pid, "maya")]
            p = next(x for x in F.followed() if x["id"] == pid)
            check("back from a pause at my own pace: nothing asked, my dates not moved, nothing skipped",
                  asked == [] and not f.get("paused") and not f.get("shift") and not p.get("paused")
                  and not skipped(st) and len(P.up_next(p["doc"], st.get("applied"))) == 5, (asked, f, st.get("applied")))
            maya.set_follow(pid, paused=True)
            F.set_paused(pid, False)
            st = F._state_cfg()[pid]
            check("resume at my own pace: nothing asked, nothing skipped", asked == [] and not skipped(st), (asked, st.get("applied")))
            res = F.run(col, F.followed(), F._state_cfg(), _day(0), mode="skip")
            check("and a run asked to skip leaves a plan at my own pace as it is",
                  res["n"] == 0 and not skipped(F._state_cfg()[pid]), str(F._state_cfg()[pid].get("applied")))
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def test_move_menu_names_the_event_v381():
    """3.8.1: Move…'s days compared an event's name with a date's `for` (the
    event's id), so "after Cardio quiz" never showed."""
    from due_crew import plans as P
    units = _plan_units()
    units[1] = dict(units[1], **{"for": "q1"})
    store, pid, code, maya = _v381_world(units=units, events=[{"id": "q1", "day": _day(2), "name": "Cardio quiz"}])
    doc = store.plans[pid]["doc"]
    check("event_of: by the event's id", P.event_of(doc, doc["units"][1])["name"] == "Cardio quiz"
          and P.event_of(doc, doc["units"][0]) is None)
    labels = []

    class Menu:
        def __init__(self, *a):
            pass

        def addAction(self, text):
            labels.append(text)
            return types.SimpleNamespace(setEnabled=lambda on: None, triggered=types.SimpleNamespace(connect=lambda f: None))

        def exec(self, *a):
            pass
    qt = sys.modules["aqt.qt"]
    saved = (qt.QMenu, qt.QCursor)
    qt.QMenu, qt.QCursor = Menu, types.SimpleNamespace(pos=lambda: None)
    try:
        with _PlanGlue({"A": maya}, {"A": _plan_col()}) as g:
            maya.follow_plan(code)
            maya.fetch_board([_day(0)], with_decks=True)
            g.F.move_menu(pid, "ar")
    finally:
        qt.QMenu, qt.QCursor = saved
    check("move: from the event's day on, a day says it's after it",
          labels[1] == P.fmt_day(_day(1)) and labels[2] == f"{P.fmt_day(_day(2))} · after Cardio quiz", labels)


def test_catch_has_one_shape_v381():
    """3.8.1: a plan's `catch` was G5's catch-up {until, extra} and 3.2's
    missed-days answer {mode, day} both, so answering the question ended a
    running catch-up. The answer is `missed`; an old plans.json moves it."""
    from due_crew import plan_flow as F
    store, pid, code, maya = _v381_world()
    with _PlanGlue({"A": maya}, {"A": _plan_col()}) as g:
        path = os.path.join(g.dirs["A"], "plans.json")
        with open(path, "w") as f:
            json.dump({"plans": {"p1": {"deck_id": 10, "catch": {"mode": "spread", "day": _day(-1)}},
                                 "p2": {"deck_id": 10, "catch": {"until": _day(3), "extra": 4}}}}, f)
        g.forget()
        pc = F._pcfg()
        with open(path) as f:
            disk = json.load(f)
        check("upgrade: the missed-days answer moves to `missed`, a catch-up stays `catch`, written back",
              pc["plans"]["p1"] == {"deck_id": 10, "missed": {"mode": "spread", "day": _day(-1)}}
              and pc["plans"]["p2"]["catch"] == {"until": _day(3), "extra": 4} and disk["plans"]["p1"].get("missed"), str(pc))
        F.set_catch("p2", "leave")
        st = F._state_cfg()["p2"]
        check("the missed-days answer leaves a running catch-up be",
              st["catch"] == {"until": _day(3), "extra": 4} and st["missed"] == {"mode": "leave", "day": _day(0)}, str(st))
    check("session: the answer read from either shape, never from a catch-up",
          F._missed({"missed": {"mode": "spread"}}) == {"mode": "spread"}
          and F._missed({"catch": {"mode": "leave", "day": "x"}})["mode"] == "leave"
          and F._missed({"catch": {"until": "x", "extra": 1}}) == {})


def test_week_open_now_at_own_pace_v381():
    """3.8.1: at my own pace the week's Open now opened a date without
    counting it as opened (not in my pace, not first in line, no Undo line),
    unlike Up next's Open. It's the same Open; a date I haven't opened
    whose day has passed offers it too, and one I opened opens what an
    author added since."""
    import due_crew as dc
    from aqt.deckbrowser import DeckBrowser
    store, pid, code, maya = _v381_world()
    col = _plan_col()
    for cid, due in ((1, 50), (2, 51), (3, 52), (4, 53), (5, 54), (6, 55), (9, 56)):
        col.db.conn.execute("UPDATE cards SET due = ? WHERE id = ?", (due, cid))
    with _PlanGlue({"A": maya}, {"A": col}):
        from due_crew import plan_flow as F
        plan, _ = maya.follow_plan(code, own="ready")
        F.on_followed(plan, 10, None, "open")
        F._state["plan_progress"] = F.progress(col, F.followed(), F._state_cfg())
        p = next(x for x in F.followed() if x["id"] == pid)
        last_week = F.card_view(p, F._state_cfg()[pid], F._state["plan_progress"][pid], _day(0), week_offset=-1)
        check("own pace: a date I haven't opened whose day has passed offers Open now",
              f"duecrew:plannow:{pid}:hf" in board._plan_card_html(dict(last_week, id=pid)))
        dc._on_js(False, as_board(f"duecrew:plannow:{pid}:ex"), DeckBrowser())
        st = F._state_cfg()[pid]
        due4 = col.db.scalar("SELECT due FROM cards WHERE id = 4")
        last = F._pcfg().get("own_last") or {}
        check("own pace, the week's Open now is Up next's Open: opened today, first in line, its Undo line",
              4 in _open(col) and st["own_opened"] == {"ex": _day(0)} and due4 == 0 and last.get("uid") == "ex"
              and last.get("kind") == "open" and col.undo_status().undo == "Due Crew: open Extras", (st.get("own_opened"), last, due4))
        units = _plan_units()
        units[2] = dict(units[2], tags=["Step1::Cardiology"])  # the author adds card 9 to Extras
        store.edit_plan(pid, units)
        maya.fetch_board([_day(0)], with_decks=True)
        F._state["plan_progress"] = F.progress(col, F.followed(), F._state_cfg())
        dc._on_js(False, as_board(f"duecrew:plannow:{pid}:ex"), DeckBrowser())
        check("own pace: Open now on a date I opened opens what the author added, and it stays opened as it was",
              9 in _open(col) and F._state_cfg()[pid]["own_opened"] == {"ex": _day(0)})


def test_plan_words_v381():
    """3.8.1, one name per idea: Not today (the morning's line and an
    update's), Push my dates back (the missed-days line, Welcome back), "once
    I've seen most of the last" (90% of its open cards opens the next), Hold
    back's question at my own pace; Browse's items for writing a plan only
    for someone who writes one."""
    from due_crew import plan_flow as F
    line = board._opened_line({"n": 3})
    check("words: the morning's line says Not today, and when they open",
          "Not today</a>" in line and 'title="They open tomorrow morning"' in line and "Put off" not in line, line)
    notes = "".join(board._plan_notes({"update": {"n": 1, "names": ["A"]},
                                       "session": {"ask": {"days": [_day(-2), _day(-1)], "waiting": 4, "spread": 2, "push": 2}}}, "p1"))
    check("words: an update's Not today says when; the missed days' push is Push my dates back",
          notes.count('title="They open tomorrow morning"') == 1 and "Push my dates back 2 days</a>" in notes
          and "Move my days" not in notes, notes)
    src = {n: srcs.due_src(n) for n in ("plan_flow.py", "ui/follow_dialog.py", "ui/days_dialog.py")}
    check("words: the next opens once I've seen most of the last, at Follow and in the plan's menu",
          "Open the next one by itself once I've seen most of the last" in src["ui/follow_dialog.py"]
          and "When I'm ready, the next once I've seen most of the last" in src["plan_flow.py"]
          and "seen the last\"" not in src["ui/follow_dialog.py"] + src["plan_flow.py"])
    check("words: Welcome back's choice is Push my dates back",
          'f"Push my dates back {days} day' in src["ui/days_dialog.py"] and "Pick up where" not in src["ui/days_dialog.py"])
    said = [F._hold_words("Step 1", 3, own=True)[1], F._hold_words("Step 1", 1)[1]]
    check("words: Hold back's question at my own pace: until you open them",
          "3 cards of its later sets until you open them?" in said[0] and "their day" not in said[0]
          and "1 card of its later sets until their day?" in said[1], said)
    acts = []

    class Menu:
        def addSeparator(self):
            pass

        def addAction(self, label):
            acts.append(label)
            return types.SimpleNamespace(triggered=types.SimpleNamespace(connect=lambda f: None))
    saved_client = F.client
    try:
        F.client = lambda: types.SimpleNamespace(signed_in=True, session={"plans_authored": [], "plans": []})
        F.browser_menu(types.SimpleNamespace(), Menu())
        reader = list(acts)
        del acts[:]
        F.client = lambda: types.SimpleNamespace(signed_in=True, session={"plans_authored": [{"id": "p1", "doc": {}}], "plans": []})
        F.browser_menu(types.SimpleNamespace(), Menu())
        writer = list(acts)
    finally:
        F.client = saved_client
    check("browse: someone who writes no plan gets why, open these and put on a day (3.9.7); an author the writing ones too",
          reader == ["Due Crew: why isn't it showing?", "Due Crew: open these…", "Due Crew: put on a day…"]
          and writer == reader + ["Due Crew: add to a plan…", "Due Crew: tag for a plan…",
                                  "Due Crew: copy as plan selector", "Due Crew: export for my AI…"], (reader, writer))


def test_builder_tags_keep_up_v381():
    """3.8.1, Sam's pick "Keep the builder's tag list current": a deck's tag
    tree reached duecrew.com's builder only through Make a plan from a deck.
    Now, at the day's first refresh, each deck a plan I write runs on is
    read (once an Anki day) and its tree goes up only when it differs from
    what this computer last sent. One that didn't go is tried again; one
    that lands after a profile switch isn't kept; Make a plan's counts."""
    from due_crew import plans as P
    from due_crew import app as appmod
    store = world({"dre": "Dre"})
    store.add_plan("dre", "Step 1", "Step 1", _plan_units())
    dre = new_client(store, "dre", "Dre")
    dre.fetch_board([_day(0)], with_decks=True)
    col = _plan_col()
    puts = lambda: sum(1 for m, path, _s in store.log if m == "PUT" and path == "/plans/trees")
    reads = []
    real_rows = P.tree_rows
    with _PlanGlue({"A": dre}, {"A": col}) as g, _SyncBg(g.F):
        F = g.F
        P.tree_rows = lambda idx: reads.append(idx.did) or real_rows(idx)
        real_put = dre.put_tree
        try:
            F.send_trees()
            sent = g.state()["trees_sent"]["step 1"]
            check("trees: the first refresh sends the deck's tree, noted as sent today",
                  puts() == 1 and sent["day"] == _day(0) and sent["h"]
                  and "Arrhythmia" in json.dumps(store.plan_trees[("dre", "Step 1")]), sent)
            F.send_trees()
            check("trees: the same day again: not read, not sent", puts() == 1 and reads == [10], reads)
            g.today["d"] = _day(1)
            F.send_trees()
            check("trees: the next day it's read; nothing changed, nothing sent",
                  puts() == 1 and len(reads) == 2 and g.state()["trees_sent"]["step 1"]["day"] == _day(1))
            col.db.conn.execute("UPDATE notes SET tags = ' Step1::Cardio::Arrhythmia Step1::Cardio::Long_QT ' WHERE id = 3")
            g.today["d"] = _day(2)
            F.send_trees()
            check("trees: on a day its tags changed, one request", puts() == 2
                  and "Long_QT" in json.dumps(store.plan_trees[("dre", "Step 1")]))
            col.db.conn.execute("UPDATE notes SET tags = ' Step1::Cardio::Arrhythmia ' WHERE id = 3")
            g.today["d"] = _day(3)
            dre.put_tree = lambda *a: False
            F.send_trees()
            check("trees: one that didn't go isn't noted as sent", g.state()["trees_sent"]["step 1"]["day"] == _day(2))

            def switched(*a):
                appmod.generation += 1  # a profile switch while it was out
                return real_put(*a)
            dre.put_tree = switched
            F.send_trees()
            check("trees: tried again at the next refresh; a reply after a profile switch isn't kept",
                  puts() == 3 and g.state()["trees_sent"]["step 1"]["day"] == _day(2))
            dre.put_tree = real_put
            F.send_trees()
            check("trees: so the next refresh sends it", puts() == 4 and g.state()["trees_sent"]["step 1"]["day"] == _day(3))
        finally:
            P.tree_rows, dre.put_tree = real_rows, real_put
        maya = new_client(store, "maya", "Maya")
        F.client = lambda: maya
        F.send_trees()
        check("trees: someone who writes no plan sends nothing", puts() == 4)
    check("tree hash: the same tree, the same hash; a count, a name or the deck changes it",
          P.tree_hash("Step 1", [["a", 1]], []) == P.tree_hash("Step 1", [["a", 1]], [])
          and len({P.tree_hash("Step 1", [["a", 1]], []), P.tree_hash("Step 1", [["a", 2]], []),
                   P.tree_hash("Step 1", [["b", 1]], []), P.tree_hash("Step 2", [["a", 1]], [])}) == 4)
    fakes.add_card(col.db.conn, 40, did=10, queue=-1, tags="Step1::" + "x" * 200)
    tags, _decks = P.tree_rows(P.DeckIndex(col, 10))
    check("tree: a path the server won't take stays here", not any(len(t[0]) > 200 for t in tags)
          and any(t[0] == "Step1::Cardio" for t in tags), [t[0] for t in tags][:6])


def _labels_col():
    """3.8.1, round three: a deck in a big shared deck's shapes. 1-5 Herpes
    (1 with a child tag), each with a question id and a Systems tag; 6-8
    Influenza; 9 a leech with a plan's own tag only; 10 a tag with no
    resource part. SECRET in every field: never in what a plan sends."""
    conn = sqlite3.connect(":memory:")
    fakes.make_collection(conn)
    R = "#Big_Step1_v12"
    for cid in range(1, 6):
        fakes.add_card(conn, cid, did=10, queue=-1, tags=f"{R}::#Video_Series::05_Micro::Viruses::Herpes_Viruses"
                       f"{'::HSV1' if cid == 1 else ''} {R}::#QBank::Step::{1000 + cid} {R}::^Systems::Micro")
    for cid in range(6, 9):
        fakes.add_card(conn, cid, did=10, queue=-1, tags=f"{R}::#Video_Series::05_Micro::Viruses::Influenza {R}::#QBank::Step::{2000 + cid}")
    fakes.add_card(conn, 9, did=10, queue=-1, tags="leech DueCrew::Block::SLG_1")
    fakes.add_card(conn, 10, did=10, queue=-1, tags="Step1::Renal")
    conn.execute("UPDATE notes SET flds = 'SECRET front' || char(31) || 'SECRET back'")
    col = fakes.FakeCol(conn, fakes.day_cutoff_for(TODAY))
    col.decks = fakes.FakeDecks({10: "Big Step 1"})
    return col


def test_pick_labels_v381():
    """3.8.1, plans round three (4): a date's picked cards keep their
    resource's name. plans.pick_labels reads the deck tags they sit under
    (the deepest covering the most, read from a #/^ resource part down; then
    the next for what's left; up to 3); the author's Anki sends them with the
    date's counts (#lbl, again only when they or the picks change); a
    follower's Anki names the picks with its own in You › Plans and Due, and
    a name's click opens just those cards."""
    from due_crew import plans as P, plan_flow as F
    from due_crew.app import _state
    R = "#Big_Step1_v12"
    herpes, viruses = f"{R}::#Video_Series::05_Micro::Viruses::Herpes_Viruses", f"{R}::#Video_Series::05_Micro::Viruses"
    col = _labels_col()
    idx = P.DeckIndex(col, 10)
    check("labels: the deepest tag covering them all names them; a series' root, a question's id and Systems don't",
          P.pick_labels(idx, [1, 2, 3, 4, 5]) == [[herpes, 5]], P.pick_labels(idx, [1, 2, 3, 4, 5]))
    got = P.pick_labels(idx, range(1, 11))
    check("labels: what covers the most first, then the next for what's left; a leech's and a plan's own tags name nothing",
          got == [[viruses, 8], ["Step1::Renal", 1]], got)
    check("labels: up to `most`, and none for no cards",
          P.pick_labels(idx, [1, 6, 10], most=1) == [[viruses, 2]] and P.pick_labels(idx, []) == [], P.pick_labels(idx, [1, 6, 10], most=1))
    # topics: without labels as before; with them, by the resource, then the rest
    u = {"id": "u1", "name": "Viruses", "opens": _day(0), "tags": [], "decks": [],
         "cards": [["guid000001", 0], ["guid000006", 0], ["guid000009", 0]], "notes": ["guid000010"]}
    doc = {"deck": "Big Step 1", "units": [u]}
    check("topics: picks with no labels read as before",
          ["Picked by ID", ["1 note"]] in P.topics(u) and ["Picked", ["3 single cards"]] in P.topics(u), P.topics(u))
    names = F.pick_names(col, [{"id": "p1", "doc": doc}], {"p1": {"deck_id": 10}})
    check("labels here: each date's picks by this copy's tags, the rest counted",
          names == {"p1": {"u1": [[viruses, 2], ["Step1::Renal", 1], ["", 1]]}}, names)
    nu = P.units(P.with_picks(doc, names["p1"]))[0]
    check("labels here: a copy of the doc carries them; the plan stays as it came",
          nu.get("_pl") and "_pl" not in u and P.with_picks(doc, None) is doc)
    check("topics: \"Viruses · 2 picked\" in its series, then the rest under it",
          P.topics(nu) == [["Video Series", ["Viruses · 2 picked"]], ["", ["Renal · 1 picked", "1 more picked"]]], P.topics(nu))
    items = P.topic_items([nu])
    check("topics: each name opens just its picks here; the rest, the picks under none",
          [P.topic_cards(idx, s, None, doc) for _g, _x, s in items] == [{1, 6}, {10}, {9}], items)
    wk = P.week_view(P.with_picks(doc, names["p1"]), {}, _day(0), P.week_start(_day(0)))
    row = next(r for d in wk for r in d["units"])
    html = board._week_html({"week": wk, "week_offset": 0}, "p1")
    check("week: the date's picks read by their resource, each a link to its cards",
          "Viruses · 2 picked</a>" in html and "duecrew:plantopic:p1:u1:0" in html and "Picked" not in html, row["what"])
    shown, saved = [], (F.followed, F._state_cfg, F._browse, F.mw.col)
    try:
        F.followed = lambda: [{"id": "p1", "doc": doc}]
        F._state_cfg = lambda c=None: {"p1": {"deck_id": 10}}
        F._browse = lambda cids, q=None, empty="": shown.append(sorted(cids))
        F.mw.col = col
        _state["plan_picks"] = names
        F.browse_topic("p1", ["u1"], 0)
        F.browse_topic("p1", ["u1"], 2)
    finally:
        (F.followed, F._state_cfg, F._browse, F.mw.col) = saved
        _state.pop("plan_picks", None)
    check("browse: the board's click on a named pick opens those cards, as the board drew them", shown == [[1, 6], [9]], shown)
    # the author's Anki: the labels ride the day's ids request, once a change
    store = world({"dre": "Dre"})
    pid, _code = store.add_plan("dre", "Micro", "Big Step 1", [
        {"id": "u1", "name": "Viruses", "opens": _day(0), "tags": [], "decks": [], "notes": ["guid000001", "guid000006"]},
        {"id": "u2", "name": "Renal", "opens": _day(1), "tags": ["Step1::Renal"], "decks": []}])
    dre = new_client(store, "dre", "Dre")
    dre.fetch_board([_day(0)], with_decks=True)
    puts = lambda: [b for m, p, b in store.bodies if m == "PUT" and p == f"/plans/{pid}/ids"]
    with _PlanGlue({"A": dre}, {"A": col}) as g, _SyncBg(g.F):
        g.F.send_ids()
        first = puts()
        g.F.send_ids()
        same = puts()
        col.db.conn.execute("UPDATE notes SET tags = ' Step1::Renal ' WHERE id = 6")
        g.F.send_ids()
        moved = puts()
    check("#lbl: the deck tags a date's picks sit under go with its counts; a date of tags alone has none",
          len(first) == 1 and first[0]["counts"]["u1"]["#lbl"] == [[viruses, 2]] and "#lbl" not in first[0]["counts"].get("u2", {}),
          first)
    check("#lbl: nothing changed, nothing sent; a tag that moved sends them again",
          len(same) == 1 and len(moved) == 2 and moved[-1]["counts"]["u1"]["#lbl"] == [[herpes + "::HSV1", 1], ["Step1::Renal", 1]],
          moved[-1:])
    check("#lbl: never a card's text", "SECRET" not in json.dumps(first + moved))


def test_plan_remarks_and_deck_link_v381():
    """3.8.1, plans round three (2, 3): the plan doc keeps where to get its
    deck (an https link) and its authors' notes (`remarks`, on a tag or one
    card). A tag's note shows under the topic row that names that tag (or one
    under it) in You › Plans and Due; a card's on the review screen when that
    card comes up for someone following the plan, with no request of its own.
    Authors write them from Browse, one note a card (one request on a click)."""
    from due_crew import plans as P, plan_flow as F, cards as C, due as DUE
    clean = shapes.clean_plan_doc
    url = lambda v: clean({"deck": "D", "units": [], "deckUrl": v}).get("deckUrl")
    check("deckUrl: an https link of up to 300, no spaces, is kept; anything else isn't",
          url("https://example.com/deck?x=1") == "https://example.com/deck?x=1" and url("https://" + "a" * 292)
          and not url("https://" + "a" * 293) and not url("http://example.com") and not url("javascript:alert(1)")
          and not url("https://example.com/a b") and not url('https://x.com/"><b>') and not url(5))
    rs = clean({"deck": "D", "units": [], "remarks": [
        {"id": "r1", "tag": "#Deck::#Path_Book::02_Inflammation", "text": "Watch <this>\nfirst"},
        {"id": "r2", "card": ["guid000005", 1], "text": "The second cloze is the one"},
        {"id": "r3", "tag": "x", "card": ["g", 0], "text": "both"}, {"id": "r4", "text": "neither"},
        {"id": "R5", "tag": "x", "text": "a bad id"}, {"id": "r6", "tag": "x", "text": "  "},
        {"id": "r7", "card": ["g", -1], "text": "no such card"}, {"id": "r1", "tag": "y", "text": "the same id"},
        {"id": "r8", "tag": "y" * 201, "text": "too long a tag"}, {"id": "r9", "tag": "z", "text": "w" * 300}]}).get("remarks")
    check("remarks: one of a tag or a card, one line, 280 at most; ids unique; the rest dropped",
          [r["id"] for r in rs] == ["r1", "r2", "r9"] and rs[0]["text"] == "Watch <this> first" and rs[1]["card"] == ["guid000005", 1]
          and len(rs[2]["text"]) == 280, rs)
    check("remarks: at most 300 a plan", len(clean({"deck": "D", "units": [], "remarks": [
        {"id": f"r{i}", "tag": "t", "text": "x"} for i in range(400)]})["remarks"]) == 300)
    # under the topics that name the tag (or one under it), in the week and in Due
    doc = clean({"deck": "Deck", "tagroot": "Block_1", "units": [
        {"id": "a", "name": "Inflammation", "opens": _day(0), "tags": ["#Deck::#Path_Book::02_Inflammation::Acute", "Step1::Renal"],
         "search": ['"tag:DueCrew::Block_1::SLG_12" "tag:#Deck::#Videos::Pharm::Cephalosporins"'],
         "cut": [{"tag": "#Deck::#Videos::Pharm::Cephalosporins", "in": "t1",
                  "q": '"tag:DueCrew::Block_1::SLG_12" "tag:#Deck::#Videos::Pharm::Cephalosporins"'}]}],
        "tags": [{"id": "t1", "name": "SLG 12", "notes": ["g1"]}],
        "remarks": [{"id": "r1", "tag": "#Deck::#Path_Book::02_Inflammation", "text": "Watch <this> first"},
                    {"id": "r2", "tag": "#deck::#path_book::02_inflammation::acute::deeper", "text": "under a topic, not over it"},
                    {"id": "r3", "tag": "DueCrew::Block_1::SLG_12", "text": "SLG 12 is on the quiz"},
                    {"id": "r4", "card": ["guid000005", 1], "text": "a card's, not a topic's"}]})
    u = P.units(doc)[0]
    names = [x for _g, x, _s in P.topic_items([u])]
    rm = P.topic_remarks(doc, [u])
    check("remarks: a tag's note goes with the topic that names it or a tag under it, a plan tag's with its cut; never a card's",
          rm == [[names.index("Acute"), "Watch <this> first"], [names.index("Cephalosporins · SLG 12"), "SLG 12 is on the quiz"]],
          (names, rm))
    wk = P.week_view(doc, {}, _day(0), P.week_start(_day(0)))
    row = next(r for d in wk for r in d["units"])
    html = board._week_html({"week": wk, "week_offset": 0}, "p1")
    check("week: under its topic's row, escaped, once",
          row.get("rm") == rm and html.count("Watch &lt;this&gt; first") == 1 and "<this>" not in html
          and '<span class="rm">&#9432; Watch &lt;this&gt; first</span>' in html, html[-900:])
    check("week: a date with no notes has no rm (as before)", "rm" not in next(
        r for d in P.week_view(dict(doc, remarks=[]), {}, _day(0), P.week_start(_day(0))) for r in d["units"]))
    due_row = DUE._date_row({"pid": "p1", "uid": "a", "plan": "Block 1", "name": "Inflammation", "opens": _day(0), "seen": 0,
                             "total": 4, "topics": P.topic_view([u]), "rm": rm}, {}, _day(0))
    dh = board._due_plan(due_row)
    check("Due: the same notes under the same topics, escaped", due_row["rm"] == rm and dh.count('class="du-rm"') == 2
          and "Watch &lt;this&gt; first" in dh and "<this>" not in dh, dh)
    # the review screen: a card's note, for the plans I follow, that card only, no request
    plans = [{"id": "p1", "name": "Block <1>", "doc": doc}]
    view = C.remark_view(plans, "guid000005", 1)
    check("review: a card's note shows with the plan's name, for that card alone",
          view and view["kind"] == "remark" and view["text"] == "\U0001F4CC Block <1>: a card's, not a topic's" and "cmd" not in view
          and C.remark_view(plans, "guid000005", 0) is None and C.remark_view([], "guid000005", 1) is None, view)
    js = C.chip_js(dict(view, accent="#2e7d32")) + C.float_js(dict(view, accent=["#2e7d32", "#7cc47f"]))
    check("review: drawn as text, never markup; with no click of its own",
          "t.textContent = folded ? D.fold : D.text" in js and "e.textContent = text" in js and "if (D.cmd)" in js
          and json.dumps(view["text"]) in js, js[:200])
    shown, saved = [], (C._bottom, C._review_web, C._show, C.client)
    store = world({"dre": "Dre", "sam": "Sam"})
    pid, code = store.add_plan("dre", "Block 1", "Deck", [{"id": "a", "name": "Inflammation", "opens": _day(0), "tags": ["x"], "decks": []}])
    dre, sam = new_client(store, "dre", "Dre"), new_client(store, "sam", "Sam")
    sam.follow_plan(code)
    n = len(store.log)
    got, status = dre.plan_remark(pid, add={"card": ["guid000005", 1], "text": "The second cloze"})
    rid = (got or {}).get("doc", {}).get("remarks", [{}])[0].get("id")
    check("remarks: an author's note on a card is one request on a click, and comes back with the plan",
          status == 200 and len(store.log) == n + 1 and got["doc"]["remarks"][0]["card"] == ["guid000005", 1] and rid, got)
    sam.fetch_board([_day(0)], with_decks=True)
    check("remarks: they ride the plan to its followers (no request of their own)",
          sam.session["plans"][0]["doc"]["remarks"][0]["text"] == "The second cloze")
    _status, data = sam._call("POST", f"/plans/{pid}/remarks", {"add": {"tag": "x", "text": "mine"}})
    check("remarks: a follower can't write one", _status == 403, data)
    card = types.SimpleNamespace(note=lambda: types.SimpleNamespace(guid="guid000005"), ord=1)
    try:
        C._bottom, C._review_web = (lambda: object()), (lambda: None)
        C._show = lambda v: shown.append(v)
        C.client = lambda: sam
        n = len(store.log)
        C.on_answer(card)
        C.on_answer(types.SimpleNamespace(note=lambda: types.SimpleNamespace(guid="guid000005"), ord=0))
        sam.session["cards"] = {"guid000005": {"tips": [{"from": "dre", "text": "think of it as two"}]}}
        _state_entries = C._state["entries"]
        C._state["entries"] = [{"user_id": "dre", "name": "Dre", "you": False}]
        C.on_answer(card)
        C._state["entries"] = _state_entries
        sam.session.pop("cards", None)
    finally:
        (C._bottom, C._review_web, C._show, C.client) = saved
    check("review: the card's note when it comes up, another card nothing, a crewmate's tip first; no request",
          shown[0] and shown[0]["kind"] == "remark" and "Block 1: The second cloze" in shown[0]["text"] and shown[1] is None
          and shown[2]["kind"] == "tip" and len(store.log) == n, shown)
    got, status = dre.plan_remark(pid, add={"card": ["guid000005", 1], "text": "The second cloze, the bigger one"})
    rs = got["doc"]["remarks"]
    dlg = open(os.path.join(REPO, "due_crew", "ui", "remark_dialog.py")).read()
    check("remarks: a card's note changed in place keeps its id, and Save leaves it there (only old words go)",
          status == 200 and len(rs) == 1 and rs[0]["id"] == rid and rs[0]["text"] == "The second cloze, the bigger one"
          and 'if got is not None and old is not None and old.get("text") != words:' in dlg, rs)
    got, status = dre.plan_remark(pid, remove=rid)
    check("remarks: taken off by its id", status == 200 and not got["doc"].get("remarks"), got)
    # Browse: for authors, on one card
    acts, said = [], []

    class Menu:
        def addSeparator(self):
            pass

        def addAction(self, label):
            acts.append(label)
            return types.SimpleNamespace(triggered=types.SimpleNamespace(connect=lambda f: None))
    saved = (F.client, F.tooltip, F.mw.col)
    try:
        F.client = lambda: types.SimpleNamespace(signed_in=True, session={"plans_authored": [{"id": "p1", "doc": {}}], "plans": []})
        F.browser_menu(types.SimpleNamespace(selected_cards=lambda: [5]), Menu())
        one = list(acts)
        del acts[:]
        F.browser_menu(types.SimpleNamespace(selected_cards=lambda: [5, 6]), Menu())
        two = list(acts)
        F.tooltip = lambda msg, **k: said.append(msg)
        F.mw.col = _plan_col()
        F.note_for_card(types.SimpleNamespace(selected_cards=lambda: [5, 6]))
    finally:
        (F.client, F.tooltip, F.mw.col) = saved
    check("browse: an author's note for one card; not for two",
          "Due Crew: note for the plan's followers…" in one and "Due Crew: note for the plan's followers…" not in two
          and said == ["Select one card first."], (one, two, said))
    src = open(os.path.join(REPO, "due_crew", "ui", "follow_dialog.py"), encoding="utf-8").read()
    check("follow: no deck named like the plan's, and a link: \"Where to get it ›\", opened in the browser from the plan's own link",
          "Your Anki has no deck called <b>{esc(deck)}</b>. " in src and "Where to get it &rsaquo;" in src
          and "openLink(url)" in src and "setOpenExternalLinks(False)" in src)


def test_plan_invites_v381():
    """3.8.1, plans round three (1): an invite to co-write a plan, or to keep
    one its owner hands over, rides the day's first board (planInvites; no
    request of its own) and shows as a line above the plans with Yes and No
    (duecrew:planinvite:<pid>:yes|no), one request on the click."""
    from due_crew import plan_flow as F
    import due_crew as dc
    from aqt.deckbrowser import DeckBrowser
    store = world({"dre": "Dre <b>", "sam": "Sam"}, {"dre": ["sam"], "sam": ["dre"]})  # an invite goes to a mutual friend
    pid, _code = store.add_plan("dre", "Block <1>", "Deck", [{"id": "a", "name": "A", "opens": _day(0), "tags": ["x"], "decks": []}])
    dre, sam = new_client(store, "dre", "Dre"), new_client(store, "sam", "Sam")
    st, _d = dre._call("POST", f"/plans/{pid}/editors", {"uid": "sam"})
    n = len(store.log)
    data = sam.fetch_board([_day(0)], with_decks=True)
    inv = sam.session.get("plan_invites")
    check("invites: they ride the day's first board, one request",
          st == 200 and len(store.log) == n + 1 and data["plan_invites"] == inv
          and inv == [{"id": pid, "name": "Block <1>", "kind": "coauthor", "by": {"name": "Dre <b>", "emoji": ""}}], inv)
    check("invites: cleaned (an id, a kind, ten at most)", shapes.clean_plan_invites(
        [{"id": "BAD!", "kind": "coauthor"}, {"id": "p1", "kind": "boss"}] + [{"id": f"p{i}", "kind": "owner"} for i in range(12)])
        == [{"id": f"p{i}", "name": "Plan", "kind": "owner", "by": {"name": "?", "emoji": ""}} for i in range(10)])
    html = board._you_plans({"cards": [], "offers": [], "invites": inv})
    check("invites: a line above the plans, names escaped, Yes and No",
          "<b>Dre &lt;b&gt;</b> asked you to co-write <b>Block &lt;1&gt;</b>. Its tags would go on your notes in Anki." in html
          and f"duecrew:planinvite:{pid}:yes" in html and f"duecrew:planinvite:{pid}:no" in html
          and html.index("planinvite") < html.index("dc-plancode"), html[:600])
    col = _plan_col()
    with _PlanGlue({"A": sam}, {"A": col}) as g, _SyncBg(g.F):
        check("invites: the board's view has them", F.board_view({})["invites"] == inv)
        n = len(store.log)
        dc._on_js(False, as_board(f"duecrew:planinvite:{pid}:yes"), DeckBrowser())
        sent = [b for m, p, b in store.bodies if p == f"/plans/{pid}/invite"]
        check("invites: Yes is one request; I co-write it now (Browse's items, its tags), and the line goes",
              len(store.log) == n + 1 and sent == [{"yes": True, "kind": "coauthor"}] and "sam" in store.plans[pid].get("editors", [])
              and not sam.session["plan_invites"] and any(a["id"] == pid for a in sam.session["plans_authored"])
              and g.toasts[-1] == "You co-write Block &lt;1&gt; now.", g.toasts)
        st, _d = dre._call("POST", f"/plans/{pid}/owner", {"uid": "sam"})
        sam.fetch_board([_day(0)])  # a later refresh: the stamp moved
        inv2 = sam.session.get("plan_invites")
        html = board._you_plans({"cards": [], "offers": [], "invites": inv2})
        check("hand-over: the owner offers the plan; it comes with the next refresh, its own words",
              st == 200 and inv2 and inv2[0]["kind"] == "owner"
              and "<b>Dre &lt;b&gt;</b> offered you <b>Block &lt;1&gt;</b> to keep." in html, (inv2, html[:300]))
        dc._on_js(False, as_board(f"duecrew:planinvite:{pid}:no"), DeckBrowser())
        check("hand-over: No keeps it where it was; the line goes",
              store.plans[pid]["owner"] == "dre" and not sam.session["plan_invites"]
              and [b for m, p, b in store.bodies if p == f"/plans/{pid}/invite"][-1] == {"yes": False, "kind": "owner"})
        sam.session["plan_invites"] = inv2  # as if the board still showed it: the owner took it back meanwhile
        dc._on_js(False, as_board(f"duecrew:planinvite:{pid}:yes"), DeckBrowser())
        check("invites: one taken back meanwhile says so, and goes", not sam.session["plan_invites"]
              and "taken back" in g.toasts[-1] and store.plans[pid]["owner"] == "dre", g.toasts[-1:])
        n = len(store.log)
        dc._on_js(False, as_board(f"duecrew:planinvite:{pid}:maybe"), DeckBrowser())
        dc._on_js(False, as_board("duecrew:planinvite:nothere:yes"), DeckBrowser())
        check("invites: anything but yes or no, or an invite I don't have, sends nothing", len(store.log) == n)


def test_change_note_round_three_v381():
    """3.8.1, plans round three (7): revisions read as revisions. The
    snapshot keeps the plan's tags {id: name}; a date whose only change is
    its name is said by its day ("updated Fri 16 Oct"); the tags by count
    ("renamed 10 tags", "added 2 tags", "took off 1 tag"). A snapshot from
    before has no tags: nothing is said about them then."""
    from due_crew import plans as P
    tag = lambda i, name=None: {"id": f"t{i}", "name": name or f"SLG {i}", "notes": [f"g{i}"]}
    doc = {"deck": "D", "tagroot": "MS2", "units": [{"id": "a", "name": "Friday's date", "opens": "2026-10-16", "tags": ["x"]},
                                                    {"id": "b", "name": "Renal", "opens": "2026-10-17", "tags": ["y"]}],
           "tags": [tag(i) for i in range(1, 13)]}
    old = P.snapshot(doc)
    check("snapshot: the plan's tags, {id: name}, beside the dates", old[P.SNAP_TAGS] == {f"t{i}": f"SLG {i}" for i in range(1, 13)}
          and json.loads(json.dumps(old)) == old)
    seg = lambda o, d: "".join(t for t, _b in P.change_note("Dre", o, d) or [])
    renamed = dict(doc, units=[dict(doc["units"][0], name="SLG 4-6 · Acid-base"), doc["units"][1]])
    check("change: a date renamed, nothing else, is said by its day", seg(old, renamed) == "Dre updated Fri 16 Oct."
          and ("Fri 16 Oct", True) in P.change_note("Dre", old, renamed), P.change_note("Dre", old, renamed))
    both = dict(doc, units=[dict(doc["units"][0], name="SLG 4-6", tags=["x", "z"]), doc["units"][1]])
    check("change: renamed and its cards changed: by its new name, as before", seg(old, both) == "Dre updated SLG 4-6.")
    tags = dict(doc, tags=[tag(i, f"SLG {i} renal") for i in range(1, 11)] + [tag(13), tag(14)])
    check("change: the tags by count", seg(old, tags) == "Dre renamed 10 tags, added 2 tags and took off 2 tags.", seg(old, tags))
    check("change: a date and a tag", seg(old, dict(renamed, tags=doc["tags"][1:])) == "Dre updated Fri 16 Oct and took off 1 tag.")
    before = {k: v for k, v in old.items() if k != P.SNAP_TAGS}
    check("change: a snapshot from before has no tags: nothing said of them; its dates still are",
          P.change_note("Dre", before, tags) is None and seg(before, renamed) == "Dre updated Fri 16 Oct.")
    check("change: nothing changed, no note", P.change_note("Dre", old, doc) is None
          and P.change_note("Dre", {"a": ["Friday's date", "2026-10-16"], "b": ["Renal", "2026-10-17"]}, doc) is None)


def test_export_with_the_plan_v381():
    """3.8.1, plans round three (8): Export cards for my AI, with a plan
    picked, starts with the plan as comment lines after Anki's header lines:
    each date as the plan's text writes it, with its cards here and how many
    of them another date has too; its events; its tags (name, full path,
    cards here); its notes. Names, tags, ids, counts and the authors' own
    words: never a card's text."""
    from due_crew import plans as P
    col = _labels_col()
    R = "#Big_Step1_v12"
    doc = shapes.clean_plan_doc({"deck": "Big Step 1", "tagroot": "Block_1", "units": [
        {"id": "a", "name": "Viruses", "opens": "2026-10-05", "due": "2026-10-09", "tags": [f"{R}::#Video_Series::05_Micro::Viruses"],
         "decks": [], "for": "q", "todo": [{"k": "watch", "t": "lecture 14", "url": "https://example.com/l14"}]},
        {"id": "b", "name": "Herpes again", "opens": "2026-10-06", "tags": [], "decks": [], "cards": [["guid000001", 0], ["guid000002", 0]],
         "notes": ["guid000010"], "search": ['"tag:DueCrew::Block_1::SLG_12" "tag:Step1::Renal"'],
         "cut": [{"tag": "Step1::Renal", "in": "t1", "q": '"tag:DueCrew::Block_1::SLG_12" "tag:Step1::Renal"'}]}],
        "events": [{"id": "q", "day": "2026-10-09", "name": "Micro quiz"}],
        "tags": [{"id": "t1", "name": "SLG 12", "notes": ["guid000010", "guid000003"]}],
        "remarks": [{"id": "r1", "tag": f"{R}::#Video_Series", "text": "Watch at 1.5x"},
                    {"id": "r2", "card": ["guid000005", 1], "text": "The second cloze"}]})
    lines = P.export_plan_lines(P.DeckIndex(col, 10), doc, "Block 1")
    check("export: the plan's lines, each a comment", lines and all(x.startswith("# ") for x in lines), lines)
    check("export: a set as its text writes it, with its cards here and what another set has too",
          f"# 2026-10-05 | Viruses | tag:{R}::#Video_Series::05_Micro::Viruses | due 2026-10-09 | for Micro quiz | "
          "watch: lecture 14 https://example.com/l14 | 8 cards here, 2 also on another set" in lines, lines)
    check("export: picks as the text writes them (cards numbered from 1), a cut by its tag's name",
          "# 2026-10-06 | Herpes again | tag:Step1::Renal in SLG 12 | notes:guid000010 | cards:guid000001:1 guid000002:1 | "
          "3 cards here, 2 also on another set" in lines, lines)
    check("export: events, the plan's tags with their path and cards here, the authors' notes",
          "# 2026-10-09 | event | Micro quiz" in lines and "# tag | SLG 12 | DueCrew::Block_1::SLG_12 | 2 cards here" in lines
          and f"# note | tag:{R}::#Video_Series | Watch at 1.5x" in lines and "# note | card:guid000005:2 | The second cloze" in lines,
          lines)
    check("export: never a card's text in the plan's lines", "SECRET" not in "\n".join(lines))
    text, n = P.export_notes(col, {1, 6}, plan_lines=lines)
    rows = text.split("\n")
    check("export: the lines come after Anki's header lines, then the cards by #guid and #cards",
          rows[:7] == ["#separator:tab", "#html:false", "#guid column:1", "#notetype column:2", "#deck column:3", "#tags column:4",
                       "#cards column:5"] and rows[7:7 + len(lines)] == lines and n == 2 and rows[7 + len(lines)].startswith("guid000001\t"),
          rows[:12])
    check("export: without the plan, as before", P.export_notes(col, {1, 6})[0].split("\n")[7].startswith("guid000001\t"))
    src = open(os.path.join(REPO, "due_crew", "ui", "export_dialog.py"), encoding="utf-8").read()
    check("export: the box, on by default, only with a plan picked; the plan itself, not my days",
          'QCheckBox("With the plan (its sets, tags, notes and what overlaps)")' in src and "self.with_plan.setChecked(True)" in src
          and "self.with_plan.setVisible(bool(p))" in src and 'p.get("plan_doc") or p["doc"]' in src)


def test_export_reads_an_authored_plan_whole_v381():
    """3.8.1 (found in the plans review): /plans/mine leaves a date's single
    cards and note ids out, so Export cards for my AI, for a plan I write but
    don't follow, asks for that plan whole (one request, on picking it)."""
    store = world({"dre": "Dre"})
    pid, _code = store.add_plan("dre", "Block 1", "Step 1", [
        {"id": "hf", "name": "Heart failure", "opens": "2026-09-01", "tags": ["Step1::Cardio"], "decks": [],
         "cards": [["guid000001", 0]]}])
    dre = new_client(store, "dre", "Dre")
    lean = dre.my_plans()[0]["doc"]["units"][0]
    whole = dre.plan(pid)["doc"]["units"][0]
    check("export: the plan list is lean (no single cards), as plans.ts mine; the plan itself is whole",
          "cards" not in lean or not lean["cards"], lean)
    check("export: ...and one GET /plans/{id} has them", whole.get("cards") == [["guid000001", 0]]
          and store.log[-1] == ("GET", f"/plans/{pid}", 200), whole)
    src = open(os.path.join(REPO, "due_crew", "ui", "export_dialog.py"), encoding="utf-8").read()
    check("export: a plan from the list is fetched whole once, when picked",
          'dict(p, _lean=True)' in src and 'self.client.plan(pid)' in src and 'p["_lean"] = False' in src)


def _away_units():
    """Five dates a day apart up to today, and one ahead (see _plan_col)."""
    return [
        {"id": "hf", "name": "Heart failure", "opens": _day(-4), "tags": ["Step1::Cardio::Heart_failure"]},
        {"id": "ar", "name": "Arrhythmia", "opens": _day(-3), "tags": ["Step1::Cardio::Arrhythmia"]},
        {"id": "ex", "name": "Extras", "opens": _day(-2), "decks": ["Step 1::Extras"]},
        {"id": "cz", "name": "Cloze two", "opens": _day(-1), "cards": [["guid000050", 1]]},
        {"id": "cg", "name": "Cardiology", "opens": _day(0), "tags": ["Step1::Cardiology"]},
        {"id": "lt", "name": "Later", "opens": _day(5), "cards": [["guid000050", 0]]},
    ]


def _studied(col, *days):
    """An answer on each of those Anki days (days ago, 0 today)."""
    cut = col.sched.day_cutoff
    for n in days:
        fakes.add_review(col.db.conn, (cut - (n + 1) * 86400 + 3600) * 1000)


def _away_world():
    """Maya follows the plan (_away_units) on _plan_col's deck."""
    store, pid, code, maya = _v381_world(_away_units())
    col = _plan_col()
    return store, pid, code, maya, col


def _away_start(g, F, maya, code, pid, col, own=None):
    """This computer last ran its morning five days ago, and nothing of the
    plan has opened since: its dates are waiting."""
    plan, _ = maya.follow_plan(code, own=own)
    maya.fetch_board([_day(0)], with_decks=True)
    p = next(x for x in F.followed() if x["id"] == pid)
    pc = g.state()
    pc["plans"] = {pid: F.new_state(col, p, 10)}
    pc["plans_day"] = _day(-5)
    F._psave(pc)
    return p


def test_welcome_back_v381():
    """3.8.1, plans round three, Welcome back: on the plan's dates, when the
    morning would open dates from 3 or more days on which I studied nothing
    in Anki (no answer at all that day, read from the revlog in one query),
    it asks before opening: Open them, Push my dates back N days (the
    follow's shift, one PATCH on the click), or Not today (nothing opens,
    asked again tomorrow). Never at my own pace, never for a paused plan."""
    from due_crew import plans as P, board
    us = _away_units()
    check("away: the days with a waiting date and nothing studied, oldest first",
          P.away_days(us, {}, _day(0), {_day(-4)}) == [_day(-3), _day(-2), _day(-1)]
          and P.away_days(us, {"ar": "sig"}, _day(0), set()) == [_day(-4), _day(-2), _day(-1)]
          and P.away_days(us, {}, _day(0), set(), since=_day(-2)) == [_day(-2), _day(-1)])

    store, pid, code, maya, col = _away_world()
    _studied(col, 4)  # studied on Heart failure's day only
    with _PlanGlue({"A": maya}, {"A": col}) as g:
        F = g.F
        _away_start(g, F, maya, code, pid, col)
        F.maybe_morning(False)
        st = F._state_cfg()[pid]
        away = st.get("away") or {}
        check("welcome back: three days with nothing studied: the morning opens nothing of it and asks",
              not ({1, 2, 3, 4, 6, 9} & _open(col)) and away.get("days") == [_day(-3), _day(-2), _day(-1)]
              and sorted(away.get("units") or []) == ["ar", "cg", "cz", "ex", "hf"] and away.get("n") == 6
              and away.get("day") == _day(0) and g.state()["plans_day"] == _day(0), str(away))
        check("welcome back: till it's answered, its dates wait (as Not today keeps them), so nothing else opens them",
              all(st["later"].get(u) == _day(1) for u in ("hf", "ar", "ex", "cz", "cg"))
              and F.run(col, F.followed(), json.loads(json.dumps(F._state_cfg())), _day(0), dry=True)["n"] == 0)
        asked = []
        F.welcome_back([pid], ask=lambda *a: asked.append(a) or "open")
        st = F._state_cfg()[pid]
        check("welcome back, Open them: everything waiting opens, in one undo step, and nothing waits",
              asked == [("Step 1", [_day(-3), _day(-2), _day(-1)], 5, 6)] and {1, 2, 3, 4, 6, 9} <= _open(col)
              and 5 not in _open(col) and col.undo_status().undo == "Due Crew: open 5 sets"
              and not st.get("later") and "away" not in st and (F.morning_opened() or {}).get("n") == 6, str(asked))
        F.welcome_back([pid], ask=lambda *a: asked.append(a) or "open")
        check("welcome back: asked once", len(asked) == 1)

    # Push my dates back: one PATCH, my dates N days later, what's due on them opens
    store, pid, code, maya, col = _away_world()
    _studied(col, 4)
    with _PlanGlue({"A": maya}, {"A": col}) as g, _SyncBg(g.F):
        F = g.F
        _away_start(g, F, maya, code, pid, col)
        F.maybe_morning(False)
        before = len(store.log)
        F.welcome_back([pid], ask=lambda *a: "push")
        sent = store.log[before:]
        st = F._state_cfg()[pid]
        check("welcome back, Push my dates back 3 days: one PATCH of my follow's shift, nothing else",
              [(m, s) for m, _p, s in sent] == [("PATCH", 200)] and store.follows[(pid, "maya")].get("shift") == 3, sent)
        check("pushed: what's due on my new days opens (Heart failure and Arrhythmia), the rest waits for its day",
              {1, 2, 3} <= _open(col) and not ({4, 6, 9} & _open(col)) and "away" not in st
              and not (st.get("later") or {}), sorted(_open(col)))

    # Not today: nothing opens, it says they wait, and tomorrow morning asks again
    store, pid, code, maya, col = _away_world()
    _studied(col, 4)
    with _PlanGlue({"A": maya}, {"A": col}) as g:
        F = g.F
        _away_start(g, F, maya, code, pid, col)
        F.maybe_morning(False)
        F.welcome_back([pid], ask=lambda *a: "later")
        st = F._state_cfg()[pid]
        p = next(x for x in F.followed() if x["id"] == pid)
        v = F.card_view(p, st, F.progress(col, [p], F._state_cfg())[pid], _day(0))
        h = board._plan_card_html(v)
        check("welcome back, Not today: nothing opens; the card says they wait for tomorrow morning, with Open now",
              not ({1, 2, 3, 4, 6, 9} & _open(col)) and v["put_off_ask"] and "5 sets</b> wait for tomorrow morning" in h
              and f"duecrew:planputback:{pid}" in h, h[-900:])
        g.today["d"] = _day(1)
        col.sched.day_cutoff += 86400
        F.maybe_morning(False)
        st = F._state_cfg()[pid]
        check("not today: the next morning asks again (the day I was away too), and still opens nothing",
              (st.get("away") or {}).get("day") == _day(1)
              and st["away"]["days"] == [_day(-3), _day(-2), _day(-1), _day(0)]
              and not ({1, 2, 3, 4, 6, 9} & _open(col)), str(st.get("away")))

    # it doesn't ask: studied on those days (the phone's reviews come with the sync), two days only, my own pace, paused
    for what, setup in (("studied every day", lambda col: _studied(col, 1, 2, 3, 4)),
                        ("two days with nothing", lambda col: _studied(col, 2, 4))):
        store, pid, code, maya, col = _away_world()
        setup(col)
        with _PlanGlue({"A": maya}, {"A": col}) as g:
            F = g.F
            _away_start(g, F, maya, code, pid, col)
            F.maybe_morning(False)
            st = F._state_cfg()[pid]
            check(f"welcome back: {what}, the morning opens as ever, no question",
                  "away" not in st and {1, 2, 3, 4, 6, 9} <= _open(col), sorted(_open(col)))
    store, pid, code, maya, col = _away_world()
    with _PlanGlue({"A": maya}, {"A": col}) as g:
        F = g.F
        _away_start(g, F, maya, code, pid, col, own="ready")
        F.maybe_morning(False)
        check("welcome back: never at my own pace", "away" not in F._state_cfg()[pid] and not ({1, 2, 3, 4, 6, 9} & _open(col)))
    store, pid, code, maya, col = _away_world()
    with _PlanGlue({"A": maya}, {"A": col}) as g:
        F = g.F
        _away_start(g, F, maya, code, pid, col)
        maya.set_days(pid, paused=True, since=_day(-5), until=_day(9))
        F.maybe_morning(False)
        check("welcome back: never for a paused plan", "away" not in F._state_cfg()[pid] and not ({1, 2, 3} & _open(col)))
    src = srcs.flow_src()
    morning = src[src.index("def maybe_morning"):src.index("def _morning_waits")]
    check("welcome back: decided after the morning's other steps and before its open; asked after it",
          morning.index("build_checks(") < morning.index("_put_away(") < morning.index("_open_now([p for p")
          < morning.index("welcome_back("))


def test_morning_opened_by_date_v381():
    """3.8.1: the morning's line says what it opened by date ("This morning
    opened 3 new cards: Heart failure 2 · Arrhythmia 1"), each name opening
    Browse on that date's new cards; four or more, the first two "and 2
    more". Under Today, and on Plans when Due is off. Not today as ever."""
    import due_crew as dc
    from due_crew import board, due_flow
    from due_crew.app import _state
    from aqt.deckbrowser import DeckBrowser
    store, pid, code, maya = _v381_world()
    col = _plan_col()
    with _PlanGlue({"A": maya}, {"A": col}) as g:
        F = g.F
        plan, _ = maya.follow_plan(code)
        F.on_followed(plan, 10, None, "open")
        check("morning by date: what each date opened, a card on two dates counted once",
              F.opened_dates() == [[pid, "hf", "Heart failure", 2], [pid, "ar", "Arrhythmia", 1]]
              and F.morning_opened() == {"n": 3, "sync": False}, F.opened_dates())
        op = F.opened_view()
        h = board._opened_line(op)
        check("morning by date: the line names them with their cards, each a way to Browse; Not today stays",
              "This morning opened 3 new cards: <a class=\"tp\"" in h and f"duecrew:planopened:{pid}:hf" in h
              and "Heart failure</a> 2 &middot; " in h and "Arrhythmia</a> 1</span>" in h and "duecrew:plannottoday" in h, h)
        many = dict(op, dates=[[pid, f"u{i}", f"Date <{i}>", 10] for i in range(5)])
        hm = board._opened_line(many)
        check("morning by date: three named; four or more, two and how many more; names escaped",
              "Date &lt;0&gt;</a> 10 &middot; " in hm and "Date &lt;1&gt;</a> 10 and 3 more</span>" in hm
              and "Date &lt;2&gt;" not in hm and "<0>" not in hm
              and board._opened_line(dict(op, dates=many["dates"][:3])).count("planopened:") == 3, hm)
        _state["labels"] = [_day(0)]
        try:
            v = due_flow.view({"due_show": True})
            plans = F.board_view({})
        finally:
            _state["labels"], _state["due_reviews"] = [], None
        check("morning by date: Due's Today has them", (v or {}).get("opened", {}).get("dates") == F.opened_dates(), str(v and v.get("opened")))
        ph = board.you_html({}, None, {"tab": "plans", "plans": plans, "opened": F.morning_opened()})
        check("morning by date: with Due off, on Plans too", f"duecrew:planopened:{pid}:ar" in ph, ph[-1500:])
        got = []
        saved = F._browse
        F._browse = lambda cids, q=None, empty="": got.append(sorted(cids))
        try:
            dc._on_js(False, as_board(f"duecrew:planopened:{pid}:hf"), DeckBrowser())
        finally:
            F._browse = saved
        check("morning by date: a name (sent as the board does) opens Browse on that date's new cards", got == [[1, 2]], got)


def _menu_recorder(acts):
    """A QMenu stand-in for plan_menu: every action's text, and its trigger."""
    class Action:
        def __init__(self, text):
            self.text, self.fn = text, None
            self.triggered = types.SimpleNamespace(connect=lambda f: setattr(self, "fn", f))

        def setCheckable(self, on): pass

        def setChecked(self, on): pass

        def setEnabled(self, on): pass

    class Menu:
        def __init__(self, *a):
            pass

        def addAction(self, text):
            a = Action(text)
            acts.append(a)
            return a

        def addMenu(self, text):
            return Menu()

        def addSeparator(self):
            pass

        def setEnabled(self, on):
            pass

        def exec(self, *a):
            pass
    return Menu


def test_held_back_sheet_v381():
    """3.8.1: what Hold back keeps. The plan's ··· menu says "Held back: N
    cards…" and opens a sheet: what it holds, by date, and why; Open them
    (one undo step, a leech stays shut, Hold back stays on for what an author
    adds later) or Stop holding back (opens them and turns it off)."""
    store, pid, code, maya = _v381_world()
    col = _plan_col()
    col.db.conn.execute("UPDATE cards SET queue = 0 WHERE id IN (4, 6)")  # later dates' new cards, active
    with _PlanGlue({"A": maya}, {"A": col}) as g:
        F = g.F
        plan, _ = maya.follow_plan(code)
        F.on_followed(plan, 10, None, "open", hold=True)
        acts = []
        qt = sys.modules["aqt.qt"]
        saved_qt = (qt.QMenu, qt.QCursor)
        qt.QMenu, qt.QCursor = _menu_recorder(acts), types.SimpleNamespace(pos=lambda: None)
        shown = []
        saved_show = F.show_held
        F.show_held = lambda p2, ask=None: shown.append(p2)
        try:
            F.plan_menu(pid)
            item = next((a for a in acts if a.text.startswith("Held back")), None)
            if item:
                item.fn()
        finally:
            qt.QMenu, qt.QCursor = saved_qt
            F.show_held = saved_show
        check("held back: the plan's menu says how many, and opens the sheet",
              item is not None and item.text == "Held back: 2 cards…" and shown == [pid], [a.text for a in acts])
        col.db.conn.execute("UPDATE notes SET tags = ' leech ' WHERE id = 4")  # Extras' card became a leech since
        v = F.held_view(pid)
        check("held back: by date, with its day, and why; a leech stays shut, said apart",
              v["n"] == 1 and v["lines"] == [f"Cloze two · {P_fmt(_day(7))} · 1"]
              and v["holding"] and "till their day" in v["why"] and v["leeches"] == 1 and F.held_count(pid) == 1, str(v))
        st = F._state_cfg()[pid]
        st["applied"]["cz"] = "opened-here"  # as if Cloze two's date had opened and I suspended its card myself
        check("held back: a card on a date that opened here isn't the plan's to show or open (the review)",
              F.held_view(pid)["n"] == 0 and F.held_count(pid) == 0)
        del st["applied"]["cz"]
        F.show_held(pid, ask=lambda view: "open")
        st = F._state_cfg()[pid]
        check("held back, Open them: one undo step; the leech stays shut; Hold back stays on",
              6 in _open(col) and 4 not in _open(col) and col.undo_status().undo == "Due Crew: open what Step 1 held back"
              and st["hold_yes"] is True and F.held_count(pid) == 0, str(st))
        F.hold_new(F.followed(), F._state_cfg(), _day(0), morning=True)
        check("held back: what it opened is never held again", 6 in _open(col))
        units = _plan_units()
        units[4] = dict(units[4], tags=["Step1::Renal", "Step1::Cardiology"])  # the author adds card 9 to a later date
        store.edit_plan(pid, units)
        col.db.conn.execute("UPDATE cards SET queue = 0 WHERE id = 9")
        maya.fetch_board([_day(0)], with_decks=True)
        F.hold_new(F.followed(), F._state_cfg(), _day(0))
        check("held back: and what an author adds later is still held", 9 not in _open(col))
        F.show_held(pid, ask=lambda view: "stop")
        st = F._state_cfg()[pid]
        col.db.conn.execute("UPDATE cards SET queue = 0 WHERE id = 5")
        units[4] = dict(units[4], cards=[["guid000050", 0]])  # and card 5, after the stop
        store.edit_plan(pid, units)
        maya.fetch_board([_day(0)], with_decks=True)
        F.hold_new(F.followed(), F._state_cfg(), _day(0))
        check("held back, Stop holding back: opens them and holds nothing more",
              9 in _open(col) and 5 in _open(col) and 4 not in _open(col) and st["hold_yes"] is False, sorted(_open(col)))
        left = F.held_view(pid)
        check("held back: only the leech is left, and no yes: nothing to open, so no menu line",
              left["n"] == 0 and left["leeches"] == 1 and not left["holding"] and "Hold back is off" in left["why"]
              and F.held_count(pid) == 0, str(left))
        said = len(g.toasts)
        F.show_held(pid, ask=lambda view: "open")
        check("held back: nothing to open, nothing to show", len(g.toasts) == said + 1 and "Nothing held back" in g.toasts[-1])


def P_fmt(iso):
    from due_crew import plans as P
    return P.fmt_day(iso)


def test_why_didnt_it_open_v381():
    """3.8.1: under a date in the plan's week, a quiet line when it left cards
    shut: "1 leech stays shut" (Browse them) · "1 pick isn't in your copy",
    from what the date counted when it opened (_tally)."""
    import due_crew as dc
    from due_crew import board
    from aqt.deckbrowser import DeckBrowser
    units = _plan_units()
    units[1] = dict(units[1], cards=[["guid000003", 0], ["guidnothere", 0]])
    store, pid, code, maya = _v381_world(units)
    col = _plan_col()
    col.db.conn.execute("UPDATE notes SET tags = tags || ' leech' WHERE id = 3")
    with _PlanGlue({"A": maya}, {"A": col}):
        from due_crew import plan_flow as F
        plan, _ = maya.follow_plan(code)
        F.on_followed(plan, 10, None, "open")
        st = F._state_cfg()[pid]
        p = next(x for x in F.followed() if x["id"] == pid)
        v = F.card_view(p, st, F.progress(col, [p], F._state_cfg())[pid], _day(0))
        row = next(r for d in v["week"] for r in d["units"] if r["uid"] == "ar")
        check("why: the date's row says what stayed shut", 3 not in _open(col) and row.get("why") == {"lee": 1, "miss": 1}, str(row))
        h = board._plan_card_html(dict(v, week=[dict(d, units=[dict(r, name="Arr <i>") for r in d["units"]]) for d in v["week"]]))
        check("why: a quiet line under it, the leech a way to Browse, names escaped",
              f'duecrew:planleech:{pid}:ar' in h and "1 leech</a> stays suspended &middot; 1 pick isn&rsquo;t in your copy" in h
              and "Arr &lt;i&gt;" in h and "<i>" not in h.replace("<i class", "").replace("<i style", ""), h[-2500:])
        two = board._why_shut("p", "u", {"lee": 2, "miss": 3})
        check("why: in the plural", "2 leeches</a> stay suspended &middot; 3 picks aren&rsquo;t in your copy" in two
              and board._why_shut("p", "u", {}) == "", two)
        check("why: a date that left nothing shut says nothing",
              [r["uid"] for d in v["week"] for r in d["units"] if r.get("why")] == ["ar"])
        got = []
        saved = F._browse
        F._browse = lambda cids, q=None, empty="": got.append(sorted(cids))
        try:
            dc._on_js(False, as_board(f"duecrew:planleech:{pid}:ar"), DeckBrowser())
        finally:
            F._browse = saved
        check("why: its leeches open in Browse (sent as the board does)", got == [[3]], got)


def test_up_next_any_date_v381():
    """3.8.1, at my own pace: the names after "Then" are links, each opening
    that date ahead of the rest (first in line, one undo step), and the line
    after says "Opened Extras (ahead of Heart failure)" with its Undo."""
    import due_crew as dc
    from due_crew import plans as P, board
    from aqt.deckbrowser import DeckBrowser
    store, pid, code, maya = _v381_world()
    col = _plan_col()
    with _PlanGlue({"A": maya}, {"A": col}):
        from due_crew import plan_flow as F
        plan, _ = maya.follow_plan(code, own="ready")
        F.on_followed(plan, 10, None, "open")
        p = next(x for x in F.followed() if x["id"] == pid)
        F._state["plan_progress"] = F.progress(col, F.followed(), F._state_cfg())
        v = F.card_view(p, F._state_cfg()[pid], F._state["plan_progress"][pid], _day(0))
        items = v["own"]["then_items"]
        check("then: each date after Up next, with its id", [x["uid"] for x in items] == ["ar", "ex", "cz"], str(items))
        h = board._plan_card_html(dict(v, own=dict(v["own"], then_items=[dict(items[0], name="Arr <b>")] + items[1:])))
        check("then: each name a link that opens it, escaped", f"duecrew:planpaceopen:{pid}:ex" in h
              and "Arr &lt;b&gt;</a> 1 &middot; " in h and "Arr <b>" not in h, h[:1500])
        dc._on_js(False, as_board(f"duecrew:planpaceopen:{pid}:ex"), DeckBrowser())
        st = F._state_cfg()[pid]
        F._state["plan_progress"] = F.progress(col, F.followed(), F._state_cfg())
        p = next(x for x in F.followed() if x["id"] == pid)
        v = F.card_view(p, st, F._state["plan_progress"][pid], _day(0))
        check("then: Extras opens now (sent as the board does), first in line, one undo step; Heart failure is still up next",
              4 in _open(col) and not ({1, 2} & _open(col)) and col.undo_status().undo == "Due Crew: open Extras"
              and st["own_opened"] == {"ex": _day(0)} and v["own"]["next"]["uid"] == "hf"
              and P.up_next(p["doc"], st["applied"])[0]["id"] == "hf", str(st.get("own_opened")))
        check("then: the line says it went ahead of which, with its Undo",
              v["own"]["last"] == "Opened Extras (ahead of Heart failure) · 1 card, first in line."
              and f"duecrew:planpaceundo:{pid}" in board._plan_card_html(v), v["own"]["last"])
        _undo_here(F, col, lambda: F.own_undo(pid))
        st = F._state_cfg()[pid]
        check("then: Undo shuts it again, Up next as it was", 4 not in _open(col) and "ex" not in (st.get("own_opened") or {}))
        F.open_next(pid)
        check("then: the next one, in order, says nothing of ahead",
              (F._pcfg().get("own_last") or {}).get("ahead") is None and {1, 2} <= _open(col))


def test_study_this_date_v381():
    """3.8.1, Study on a date (the plan's week, and a plan date in Due): a Due
    Crew deck of the date's open cards, new and review, due or not (a cram
    before a quiz), random order, Anki's own one step; Anki's Study screen
    on it. A date with nothing open builds nothing."""
    import due_crew as dc
    from due_crew import plans as P, board, due_flow, due as DUE
    from aqt.deckbrowser import DeckBrowser
    col = _plan_col()
    col.db.conn.execute("UPDATE cards SET queue = 0 WHERE id = 1")
    col.db.conn.execute("UPDATE cards SET queue = -3 WHERE id = 2")  # buried
    idx = P.DeckIndex(col, 10)
    check("study: a date's open cards, new and review, due or not; never a suspended or buried one",
          P.study_cards(idx, {1, 2, 3, 8, 99}) == [1, 8])
    check("study: 3.9.5 (Sam's FSRS rule), its new cards and the ones due today, seen ones first",
          P.new_and_due(idx, {1, 2, 3, 8, 99}) == [8, 1])
    col.db.conn.execute("UPDATE cards SET due = ? WHERE id = 8", (col.sched.today + 5,))
    check("…never a review ahead of its date", P.new_and_due(P.DeckIndex(col, 10), {1, 2, 3, 8, 99}) == [1])
    store, pid, code, maya = _v381_world()
    col = _plan_col()
    with _PlanGlue({"A": maya}, {"A": col}) as g:
        F = g.F
        plan, _ = maya.follow_plan(code)
        F.on_followed(plan, 10, None, "open")
        built, sel, moved = [], [], []

        def fake_filtered(c, name, cids, order=4, **kw):
            built.append((name, sorted(cids), order))
            col.decks.names[99] = name
            return True
        saved = (F._filtered, getattr(F.mw, "moveToState", None))
        F._filtered = fake_filtered
        col.decks.select = sel.append
        F.mw.moveToState = moved.append
        try:
            dc._on_js(False, as_board(f"duecrew:planstudydate:{pid}:hf"), DeckBrowser())
            dc._on_js(False, as_board(f"duecrew:planstudydate:{pid}:ex"), DeckBrowser())  # nothing of it open yet
        finally:
            F._filtered = saved[0]
            if saved[1] is None:
                F.mw.__dict__.pop("moveToState", None)
            else:
                F.mw.moveToState = saved[1]
        check("study: 3.9.5, a Due Crew deck of the date's new cards and the ones due today, as they come in the deck, "
              "and Anki's Study screen on it", built == [("Due Crew::Heart failure", [1, 2], 6)] and sel == [99] and moved == ["overview"], (built, sel, moved))
        check("study: a date with nothing new or due builds nothing, and says so", len(built) == 1 and "Nothing new or due in it." in g.toasts[-1])
        # 3.9.5 (Sam's): a topic of a date on Today, as a super deck of its own
        F._filtered, browsed = fake_filtered, []
        saved_b = F._browse
        F._browse = lambda cids, q=None, empty="": browsed.append(sorted(cids))
        F.mw.moveToState = moved.append
        try:
            dc._on_js(False, as_board(f"duecrew:plantopicstudy:{pid}:hf:0"), DeckBrowser())
            check("topic: its new cards and the ones due today, as they come in the deck, a super deck named for it, and into it",
                  built[-1] == ("Due Crew::Heart failure", [1, 2], 6) and moved[-1] == "overview", (built, moved))
            n = len(built)
            dc._on_js(False, as_board(f"duecrew:plantopicstudy:{pid}:ex:0"), DeckBrowser())  # Extras: nothing open yet
            dc._on_js(False, as_board(f"duecrew:plantopicstudy:{pid}:hf:9"), DeckBrowser())  # no such topic
            check("topic: nothing new or due in it, Browse as before; no such topic, nothing", len(built) == n and len(browsed) == 1, browsed)
        finally:
            F._filtered, F._browse = saved[0], saved_b
            if saved[1] is None:
                F.mw.__dict__.pop("moveToState", None)
            else:
                F.mw.moveToState = saved[1]
        emptied = []
        col.decks.names[98], col.decks.names[97] = "Due Crew::MS2 \u00b7 Today", "Mine::Cram"
        col.sched.empty_filtered_deck = emptied.append
        col.db.conn.execute("UPDATE cards SET odid = did, did = 98 WHERE id = 1")
        col.db.conn.execute("UPDATE cards SET odid = did, did = 97 WHERE id = 2")
        col.db.conn.execute("UPDATE cards SET odid = did, did = 98 WHERE id = 8")
        freed = F._free(col, [1, 2, 3], "Due Crew::Heart failure")
        check("topic: a card another Due Crew deck holds comes out of it first, with what else it held (to go back); "
              "a deck of mine is left alone", freed == [(98, [8])] and emptied == [98], (freed, emptied))
        check("topic: the deck being built isn't emptied", F._free(col, [1], "Due Crew::MS2 \u00b7 Today") == [])
        made, term = [], types.SimpleNamespace(search="cid:1,5,8", limit=3, order=1)
        col.sched.get_or_create_filtered_deck = lambda deck_id: made.append(("get", deck_id)) or types.SimpleNamespace(
            config=types.SimpleNamespace(search_terms=[term]))
        col.sched.add_or_update_filtered_deck = lambda d: made.append(("put", term.search, term.limit, term.order))
        F._refill(col, 98, [8])
        F._refill(col, 97, [])
        check("topic (the second review): the deck it came out of gets back the rest of what it held, its order kept; "
              "not its first search, which would take back the cards answered since as reviews ahead",
              made == [("get", 98), ("put", "cid:8", 1, 1)], made)
        F._state["plan_progress"] = F.progress(col, F.followed(), F._state_cfg())
        p = next(x for x in F.followed() if x["id"] == pid)
        v = F.card_view(p, F._state_cfg()[pid], F._state["plan_progress"][pid], _day(0))
        ar = next(r for d in v["week"] for r in d["units"] if r["uid"] == "ar")
        h = board._plan_card_html(v)
        ar_day = next(d["day"] for d in v["week"] for r in d["units"] if r["uid"] == "ar")
        check("study: the week offers it on a date with cards open, though none is seen yet (3.9.6: its day's Study)",
              ar.get("study") and int(ar["seen"]) == 0 and f"duecrew:planstudyday:{pid}:{ar_day}" in h, str(ar))
        dates, _e, _r = due_flow.plan_dates(_day(0))
        mine = {d["uid"]: d for d in dates if d["pid"] == pid}
        check("study: Due's plan dates say which have cards open", mine["ar"]["study"] and not mine.get("ex", {}).get("study"), str(mine.keys()))
        rows = DUE.view(_day(0), [dict(mine["ar"], name="Arr <b>")], [], {})
        r = next(x for x in rows["rows"] if x["kind"] == "plan")
        dh = board._due_html(dict(rows, rows=[dict(r, study=True)]))
        check("study: a plan date in Due has its Study too, its name escaped",
              f"duecrew:planstudydate:{pid}:ar" in dh and "Arr &lt;b&gt;" in dh and "Arr <b>" not in dh, dh[-1500:])
        check("study: not on a row Due Crew didn't mark", "planstudydate" not in board._due_html(rows))
    # Anki's new filtered deck comes with a second filter (the current deck's new cards, 20): ours keep only theirs
    made = []
    term = lambda: types.SimpleNamespace(search="", limit=0, order=0)  # noqa: E731
    deck = types.SimpleNamespace(name="", config=types.SimpleNamespace(search_terms=[term(), term()], reschedule=False))
    fcol = types.SimpleNamespace(decks=types.SimpleNamespace(id_for_name=lambda n: None),
                                 sched=types.SimpleNamespace(get_or_create_filtered_deck=lambda deck_id=0: deck,
                                                             add_or_update_filtered_deck=made.append))
    from due_crew import plan_flow as F
    saved = (F._pcfg, F._psave)
    F._pcfg, F._psave = (lambda: {}), (lambda c: None)
    try:
        F._filtered(fcol, "Due Crew::Renal", [3, 1], order=1)
    finally:
        F._pcfg, F._psave = saved
    t = deck.config.search_terms
    check("study: the deck holds just its cards, random, rescheduling (Anki's second filter dropped)",
          made == [deck] and len(t) == 1 and t[0].search == "cid:3,1" and t[0].limit == 2 and t[0].order == 1
          and deck.config.reschedule, [(x.search, x.limit) for x in t])


def test_shared_and_mine_v381():
    """3.8.1: the week's day line separates what the plan opens that day
    ("opens 1 new") from my own load ("you: 3 reviews due"), today and
    ahead; today's is Due's own count once Due has read it."""
    from due_crew import board
    from due_crew.app import _state
    store, pid, code, maya = _v381_world()
    col = _plan_col()
    fakes.add_card(col.db.conn, 20, did=20, ctype=2, queue=2, due=1000)   # today
    fakes.add_card(col.db.conn, 21, did=20, ctype=2, queue=2, due=995)    # overdue: today's too
    fakes.add_card(col.db.conn, 22, did=20, ctype=2, queue=3, due=1002)   # in two days
    fakes.add_card(col.db.conn, 23, did=20, ctype=2, queue=2, due=1001, odid=20)  # in a filtered deck
    _state["due_reviews"] = None  # Due's count, from another test
    with _PlanGlue({"A": maya}, {"A": col}):
        from due_crew import plan_flow as F
        got = F.reviews_by_day(col, _day(0))
        check("mine: reviews due by day, my whole Anki, overdue on today", got == {_day(0): 3, _day(2): 1}, got)
        plan, _ = maya.follow_plan(code)
        F.on_followed(plan, 10, None, "open")
        F.refresh_progress()
        p = next(x for x in F.followed() if x["id"] == pid)
        v = F.card_view(p, F._state_cfg()[pid], F._state["plan_progress"][pid], _day(0))
        by = {d["day"]: d for d in v["week"]}
        h = board._plan_card_html(v)
        check("mine: today and the days ahead carry my reviews due, past days don't",
              by[_day(0)].get("mine") == 3 and by.get(_day(2), {}).get("mine", 1) == 1
              and all("mine" not in d for d in v["week"] if d["day"] < _day(0)), str([(d["day"], d.get("mine")) for d in v["week"]]))
        check("mine: the day line, the plan's then mine (cards: every card its dates match)", "opens 1 card &middot; you: 3 reviews due" in h, h[-3000:])
        _state["due_reviews"] = (0, {"due": 7})
        try:
            v = F.card_view(p, F._state_cfg()[pid], F._state["plan_progress"][pid], _day(0))
        finally:
            _state["due_reviews"] = None
        check("mine: today's is Due's own count when Due has it", next(d for d in v["week"] if d["today"]).get("mine") == 7)
        check("mine: a past day has no line, a day with nothing says nothing",
              board._day_line({"past": True, "new": 5, "mine": 9}) == "" and board._day_line({"new": 0}) == ""
              and board._day_line({"new": 0, "mine": 1}) == '<span class="pdl">you: 1 review due</span>')


def test_reinforcement_v381():
    """3.8.1, plans round three §5: a date for an event that opens after the
    event's day is reinforcement: Anki's week view and Due say "after Heme
    quiz" in place of "for Heme quiz", it isn't a prep day, and the plan
    card's "For … · N more days of prep" doesn't count it."""
    from due_crew import plans as P, board, due as DUE, due_flow
    doc = {"deck": "Step 1", "events": [{"id": "q", "day": "2026-10-09", "name": "Heme <quiz>"}],
           "units": [{"id": "a", "name": "Anemia", "opens": "2026-10-07", "for": "q"},
                     {"id": "b", "name": "Anemia again", "opens": "2026-10-12", "for": "q"},
                     {"id": "c", "name": "Plain", "opens": "2026-10-08"}]}
    a, b, c = doc["units"]
    check("after: a date after its event reinforces it; one before preps for it; none, neither",
          P.reinforces(doc, b)["id"] == "q" and P.reinforces(doc, a) is None and P.reinforces(doc, c) is None
          and P.for_words(doc, a) == "for Heme <quiz>" and P.for_words(doc, b) == "after Heme <quiz>" and P.for_words(doc, c) == "")
    w = P.week_view(doc, {}, "2026-10-07", P.week_start("2026-10-12"))
    rb = next(r for d in w for r in d["units"] if r["uid"] == "b")
    check("after: in the week it says so, and isn't prep", rb["ev"] == "after Heme <quiz>" and rb["prep"] is False
          and not next(d for d in w if d["day"] == "2026-10-12")["prep"], str(rb))
    w0 = P.week_view(doc, {}, "2026-10-07", P.week_start("2026-10-07"))
    ra = next(r for d in w0 for r in d["units"] if r["uid"] == "a")
    rc = next(r for d in w0 for r in d["units"] if r["uid"] == "c")
    check("after: a prep date says for, a plain one nothing", ra["ev"] == "for Heme <quiz>" and ra["prep"] and "ev" not in rc)
    card = {"id": "p1", "title": "Plan", "week": w, "rows": [], "lines": []}
    h = board._week_html(card, "p1")
    check("after: the day's details say it, escaped", "&middot; after Heme &lt;quiz&gt;</span>" in h and "<quiz>" not in h, h[-1500:])
    check("after: the card's prep line doesn't count a date after the event",
          P.prep_for(dict(doc, units=[b]), "2026-10-05") is None
          and P.prep_for(doc, "2026-10-05")["name"] == "Heme <quiz>")
    x = {"pid": "p", "uid": "b", "plan": "Plan", "name": "Anemia again", "opens": "2026-10-12", "seen": 0, "total": 4,
         "prep": "Heme <quiz>"}
    r = DUE.view("2026-10-12", [x], [], {})["rows"][0]
    check("after: Due says after for it, for otherwise, escaped",
          "after Heme &lt;quiz&gt;" in board._due_plan(dict(r, after=True))
          and "for Heme &lt;quiz&gt;" in board._due_plan(r))
    store, pid, code, maya = _v381_world(
        [dict(u, **{"for": "e1"}) if u["id"] in ("hf", "ar") else u for u in _plan_units()],
        events=[{"id": "e1", "day": _day(-3), "name": "Cardio quiz"}])
    col = _plan_col()
    with _PlanGlue({"A": maya}, {"A": col}):
        from due_crew import plan_flow as F
        plan, _ = maya.follow_plan(code)
        F.on_followed(plan, 10, None, "open")
        F.refresh_progress()
        dates, _e, _r = due_flow.plan_dates(_day(0))
        mine = {d["uid"]: d for d in dates if d["pid"] == pid}
        check("after: Due's plan dates mark a date after its event (my days), not one before it",
              mine["ar"]["after"] and not mine["hf"]["after"] and mine["ar"]["prep"] == "Cardio quiz", str(mine))


def test_plan_tags_builder_v381():
    """3.8.1 on duecrew.com: the builder names a cut as the add-on does,
    writes and reads it as text, makes one from Overlap's "and", lets a tag
    line hold single cards, and the whole plan's text names the dates still
    using a tag it takes off."""
    builder = open(os.path.join(REPO, "site", "public", "builder.js"), encoding="utf-8").read()
    plans_src = open(os.path.join(REPO, "due_crew", "plans.py"), encoding="utf-8").read()
    check("r2 site: a cut is named for its tag's last part and the plan tag, as plans.topic_items names it (the twins)",
          'return `${Tags.word(c.tag.split("::").pop())}${t ? ` · ${t.name}` : ""}`' in builder
          and 'f"{_word(segs[-1])} \\u00b7 {c[\'nm\']}"' in plans_src)
    check("r2 site: the text writes a cut as tag:PATH in NAME and reads it back, its search not again",
          "`tag:${c.tag} in ${" in builder and "/^(\\S+)\\s+in\\s+(\\S.*)$/i" in builder
          and ".filter((q) => !cutOf(u, q)).map((q) => `search:${q}`)" in builder)
    check("r2 site: a cut keeps its Anki search in the date's searches, for an add-on before 3.8.1",
          "const cutQ = (tagPath, t) => `${Tags.ankiSearch(\"tag\", ptagPath(t))} ${Tags.ankiSearch(\"tag\", tagPath)}`" in builder
          and builder.count("syncCuts();") >= 3)
    check("r2 site: Overlap's and with a deck tag is a cut; a tag line takes cards:",
          'if (ovl.op === "and" && !pt)' in builder and "const cs = picks ? picks.cards : [];" in builder
          and "(t.cards || []).length ? Picks.cardsText(t.cards)" in builder)
    check("r2 site: the whole plan's text names the dates a removed tag is still on, and offers both ways",
          '"Take them off those sets too"' in builder and '"Keep the tags"' in builder and '"Replace anyway"' in builder
          and "What these sets already opened stays open." in builder)
    check("r2 site: the tagging prompt gives the root, the tags as they stand and the #cards rule",
          "In Anki each one becomes the tag DueCrew::${a.root}::NAME" in builder and "root: tagRootNow()" in builder
          and "This plan's tags now, as they stand" in builder and "#cards column" in builder
          and "if (ids + m <= 2000)" in builder)
    check("r2 site: a plan tag's tag inside a search is matched whole (renaming SLG 1 leaves SLG 12), as plans.ts reroot bounds it",
          '(?=::|$|[\\\\s")])`, flags);' in builder and "if (!tagRe(oldPath).test(q)) continue;" in builder
          and "q.replace(tagRe(oldPath, \"gi\"), () => nq)" in builder and "q.includes(oq)" not in builder)
    check("r2 site: a tag line writes each search as its own part, so Edit the whole plan reads it back the same",
          "...(t.search || []).map((x) => `search:${x}`)].filter(Boolean);" in builder and '"tag", t.name, ...tagSrcs(t)' in builder)
    check("r2 site: a cut chip dragged to another day moves as a cut; a cut's search is never trimmed away",
          "else if (c.cut) {" in builder and "takeCut(c.u, x);" in builder and ".slice(-10)" not in builder
          and 'note = "A set holds up to 10 searches and cuts."' in builder)
    check("r2 site: a heavy day's Split takes a whole tag or subdeck only; a redraw keeps the page where it was",
          "const big = u.even ? null : srcs(u).filter((k) => !uncounted(k) && eff(k) > 0)" in builder  # 3.8.1: srcs are tags and subdecks
          and "const y = window.scrollY;\n    drawNow();\n    if (y) window.scrollTo(0, y);" in builder)


def test_builder_review_bugs_v381():
    """The plan builder's review (Sam's picks): Fill to a date stops there and
    says what didn't fit; /plans/new draws before it can fail and says why;
    a replaced doc brings its pace; Edit the whole plan keeps a renamed or
    moved date's id and reads a name as a name; a plan tag's x names its
    dates first; the server's ceilings are said where they're hit, each
    refusal in its own words; Starts and Move this day move everything."""
    import re
    site = os.path.join(REPO, "site", "public")
    builder = open(os.path.join(site, "builder.js"), encoding="utf-8").read()
    app = open(os.path.join(site, "app.js"), encoding="utf-8").read()
    plans_ts = open(os.path.join(REPO, "worker", "src", "plans.ts"), encoding="utf-8").read()
    # 1: Fill to <date>
    check("review: Fill to a date never runs past it; an even piece there takes fewer days",
          "let until = end;" in builder and "if (end && studyDays(d, end) < k) { k = studyDays(d, end); clipped = true; }" in builder
          and "if (pace.mode === \"end\") pace.daily = endDaily();" not in builder)
    check("review: whole chapters leave gaps, so the pace rises a little (8 tries) before anything is left off",
          "cap = Math.min(5000, Math.ceil(cap * 1.1));" in builder and "tries >= 7" in builder)
    check("review: what didn't fit is said, by name; an end before the dates places nothing (no 1-a-day pace)",
          "didn't fit${end && !full ? ` by ${pretty(end)}` : \"\"}: ${leftNames(r.left)}." in builder
          and "`Nothing fits by ${pretty(end)}: " in builder and "if (d1) pace.daily = d1;" in builder)
    # 2: /plans/new
    new_plan = app[app.index("async function newPlan()"):app.index("// ---- the builder: builder.js ----")]
    check("review: a new plan is named for the deck's last part, 60 characters at most",
          'const name = (deck.split("::").pop().trim() || deck.trim()).slice(0, 60).trim() || "My plan";' in new_plan
          and 'api("POST", "/plans", { name, deck })' in new_plan and "{ name: deck, deck }" not in new_plan)
    check("review: /plans/new draws its page before any request, so a failure shows; each reason its own",
          new_plan.index("page(h(\"h1\"") < new_plan.index('api("GET", "/plans/mine")')
          and all(k in new_plan for k in ('"too_many_plans"', '"plans_full"', '"bad_plan"', "err.status === 429")))
    # 3: the doc replaced, the pace follows
    check("review: History's Undo and a (merged) save reload the pace, what to cover and the start with the doc",
          "function reload(d) {" in builder and builder.count("reload(plan.doc)") == 2 and "fromDoc(); study.days = pace.days;" in builder
          and "doc = structuredClone(plan.doc); base = structuredClone(plan.doc);" not in builder)
    check("review: a save to an end date keeps the pace it was filled at (5,000 at most, as the server takes)",
          "p.daily = Math.max(1, Math.min(5000, endDaily() || pace.daily));" in builder)
    # 4: Edit the whole plan
    check("review: the whole plan's text keeps a moved date (its name, another day) or a renamed one (its day and cards)",
          "fromText(ta.value, !adding)" in builder and "function fromText(text, whole = false)" in builder
          and "oldSig(u) === sigOf(e)" in builder and "loose.filter((x) => x.key === e.key).length === 1" in builder
          and "claimed.has(u.id)" in builder)
    check("review: the part after the date is a name (Read: Chapter 3, For the midterm, Evenly), keywords only after it",
          "const namePart = !opens || k === at + 1;" in builder and "!namePart && /^even(ly)?$/i.test(part)" in builder
          and "!namePart && (m = /^for\\s+(.+)$/i.exec(part))" in builder and "!namePart && (m = /^(watch|read|do):" in builder)
    check("review: the preview says a date moved or was renamed", "` · moved from ${pretty(was.opens)}`" in builder and "` · was ${was.name}`" in builder)
    # 5: a plan tag's x
    check("review: a plan tag's x names the dates it's on, and which go, before Delete it",
          "function dropSay(t)" in builder and "nothing else, so ${gone.length === 1 ? \"it goes\" : \"they go\"}, to-dos too." in builder
          and 'tagDrop === t.id ? h("div", { class: "ptdrop small"' in builder)
    # 6: the server's ceilings, where they're hit
    want = {k: re.search(rf"const {k} = (\d+);", plans_ts).group(1) for k in ("UNITS_MAX", "EVENTS_MAX", "REVIEWS_MAX", "SOURCES_MAX", "SEARCH_MAX")}
    named = {"UNITS_MAX": "sets", "EVENTS_MAX": "events", "REVIEWS_MAX": "reviews"}  # 3.9.9: Ceilings.MAX, the site's one table
    check("review: the builder's ceilings are the Worker's", all(
        (f"{named[k]}: {v}," in builder and f"{k} = Ceilings.MAX.{named[k]}" in builder) if k in named else f"{k} = {v}" in builder
        for k, v in want.items()), str(want))
    check("review: a date made past 200, a search past 10 (search box, Overlap, a moved chip), a review day past 60 are refused, said",
          "if (doc.units.length >= UNITS_MAX) { note = FULL; return null; }" in builder
          and "if (!addSearch(u, q)) { why.textContent = note;" in builder and ".slice(0, 10)" not in builder
          and "if (!addSearch(t, c.search)) { cleanup(); draw(); return; }" in builder
          and "(doc.reviews || []).length >= REVIEWS_MAX" in builder)
    check("review: a cleared date name is the date's own again; a cleared event name keeps the one it had",
          "const nameIt = (u, v) =>" in builder and 'x.name = was.trim() ? was : "Event";' in builder
          and "for (const u of doc.units) if (!String(u.name || \"\").trim()) { auto.add(u.id); u.name = autoName(u); }" in builder)
    codes = ("plans_full", "bad_plan", "bad_name", "bad_line", "bad_post", "bad_squad", "not_owner", "not_author", "no_plan", "too_big", "slow_down")
    check("review: each refusal of a save has its own words; the old catch-all about due dates is gone",
          all(f"    {c}: " in builder for c in codes) and "A date isn't valid: a due date can't be before it opens" not in builder
          and "const over = overLimit()" in builder)
    worker_src = "".join(open(os.path.join(REPO, "worker", "src", f), encoding="utf-8").read() for f in ("plans.ts", "util.ts", "limits.ts", "validate.ts"))
    check("review: those codes are the Worker's", all(f'"{c}"' in worker_src or f'bad("{c[4:]}")' in worker_src for c in codes)
          and 'bad = (what: string) => new HttpError(400, "bad_" + what)' in worker_src)
    # 7: Starts, Move this day, failures said, Split
    check("review: Starts moves the review days, the events and the end with the dates",
          "for (const r of doc.reviews || []) r.day = addDays(r.day, delta);" in builder and "for (const x of events()) x.day = addDays(x.day, delta);" in builder
          and "if (doc.end) doc.end = addDays(doc.end, delta);" in builder)
    check("review: Move this day onto a date merges its to-dos, its for and its cuts too",
          "function mergeInto(into, u)" in builder and "if (u.for && !into.for) into.for = u.for;" in builder
          and "into.cut = [...(into.cut || []), c]" in builder and "into.todo = all.slice(0, Todo.MAX);" in builder
          and "const r = mergeInto(other, u);" in builder)
    check("review: a note, a co-author, a follower's pace, History and Updates say when they fail",
          '"That note didn\'t post. Try again."' in builder and '"Couldn\'t load your crew. Try again."' in builder
          and "That didn't change. Try again.\"" in builder and "That didn't reset. Try again.\"" in builder and '"Couldn\'t load the history. "' in builder
          and '"Couldn\'t load the updates. "' in builder and "catch { return; }" not in builder
          and "/* stays as it was */" not in builder and "history = []; draw();" not in builder)
    check("review: Split has no choice its button ignores; picking in Anki is a line",
          'opt("anki"' not in builder and '"Or pick cards in Anki: "' in builder and "} else return;" not in builder)


def test_builder_review_wording_v381():
    """The builder's words (Sam's picks): followers are asked at their next
    refresh; Fill, not Lay it out; the Text tab's line is true; my squads
    vs the plan's squad; a neutral example beside the med one; the review
    day says what it makes; the empty tree names the deck; most of the
    last; per-date counts from 3 in the squad; the whole format's page."""
    site = os.path.join(REPO, "site", "public")
    builder = open(os.path.join(site, "builder.js"), encoding="utf-8").read()
    classes = open(os.path.join(site, "classes.html"), encoding="utf-8").read()
    check("words: an opened date's followers are asked at their next refresh",
          "Followers who opened it are asked at their next refresh" in builder and "tomorrow morning" not in builder)
    check("words: the empty List says Fill", "Tick what to cover and Fill, or drag" in builder and "Lay it out, or drag" not in builder)
    check("words: Edit the whole plan says nothing changes before Replace and Save",
          "Nothing does until you Replace the plan's sets, and Save." in builder and "Saving replaces the plan's dates with this text." not in builder)
    check("words: Settings offers it to one of my squads, not the plan's squad",
          '"Offer it to one of my squads"' in builder and '"Only people in that squad of mine"' in builder and '"Offer it to a squad"' not in builder)
    check("words: each example has a neutral one beside the med one",
          "(SLG 12, or Unit 3)" in builder and "2026-10-20 | Chapter 4 | deck:Chemistry::Unit 3::Chapter 4" in builder
          and "2026-10-12 | Chapter 4 | tag:Chemistry::Unit_3::Chapter_4" in builder and '"tag | Unit 3 | tag:Chemistry::Unit_3"' in builder
          and "Heart failure | tag:Step1::Cardio::Heart_failure" in builder)
    check("words: Make it a review day says followers get a Due Crew deck of what they've seen, that morning",
          "That morning, followers get a Due Crew deck of what they've seen from these sets" in builder)
    check("words: the empty tree names the plan's deck, and Anki's deck needs that name",
          "the deck there needs the name ${doc.deck}." in builder and "Make a plan from a deck" not in builder)  # 3.9.12: that menu item went in 3.9.3
    check("words: at my own pace, the next once I've seen most of the last",
          "when I'm ready, the next once I've seen most of the last" in builder and "the next once I've seen the last\"" not in builder)
    check("words: Progress shows per-date counts only from 3 in the squad (3.9.5: an author on the team among them) "
          "and 2 sharing besides me, as the class hint",
          "const inSquad = pr.inSquad ?? pr.sharing;" in builder and "if (inSquad < 3) {" in builder
          and "const others = pr.others ?? pr.sharing;" in builder and "if (others < 2) {" in builder
          and "if ((pr.inSquad ?? pr.sharing) < 3 || (pr.others ?? pr.sharing) < 2 || !pr.sharing) return null;" in builder
          and "Each set's counts show once 3 or more are in it." in builder
          and "Each set's counts show once 2 or more besides you do." in builder)
    check("words: For classes says the plan's squad", "among those in the plan&rsquo;s squad" in classes and "among those who share it" not in classes)
    check("words: the Format box links the whole format; both prompts name it",
          'h("a", { class: "small", href: "/plan-text"' in builder and "The whole format ›" in builder
          and builder.count('"The whole format: https://duecrew.com/plan-text",') == 2)


def test_builder_undo_follow_asof_v381():
    """Sam's picks: Undo in the builder, a step at a time, never across a
    save or a reload; Follow on a plan's link page, one request; "Tags as
    of" the day the author's Anki sent them."""
    site = os.path.join(REPO, "site", "public")
    builder = open(os.path.join(site, "builder.js"), encoding="utf-8").read()
    app = open(os.path.join(site, "app.js"), encoding="utf-8").read()
    css = open(os.path.join(site, "app.css"), encoding="utf-8").read()
    plans_ts = open(os.path.join(REPO, "worker", "src", "plans.ts"), encoding="utf-8").read()
    check("undo: each change keeps the state before it (doc, pace, what to cover, the start), 20 at most",
          "const UNDO_MAX = 20;" in builder and "const snap = () => JSON.stringify({ doc, pace, cover: [...cover], start, meta, auto: [...auto] });" in builder
          and "if (undos.length > UNDO_MAX) { undos.shift(); undoLost = true; }" in builder)
    check("undo: typing in one box is one step", "mark(`name:${u.id}`)" in builder and 'mark("title")' in builder and "!(key && key === undoKey)" in builder)
    check("undo: a save or a reload starts over; back to the saved plan is clean",
          "settled();" in builder and "  settled();  // Undo starts from the plan as it loaded\n  draw();" in builder
          and "if (!undos.length && !undoLost) { dirty = false;" in builder)
    check("undo: the button beside Save, and Ctrl/Cmd+Z when no text box has the focus",
          "undoBtn, saveBtn) : null);" in builder and '.savebar button.undo' in css
          and 'e.key.toLowerCase() === "z" && document.contains(saveBtn)' in builder and "&& undos.length && !typing(e.target)) { e.preventDefault(); undo(); }" in builder)
    fb = app[app.index("function followBox(p, code, followed) {"):app.index("/** /p/CODE: what a shared link shows. */")]
    check("follow: signed in, a plan's link page follows on one request, then says where its cards go",
          fb.count("api(") == 1 and 'api("POST", "/plans/follow", { code })' in fb and "picks it up at its next refresh" in fb
          and '"You follow 20 plans. Stop one first."' in fb and "me ? followBox(p, code, followed) : null" in app)
    check("follow: its authors and followers get the way to it instead",
          '"It\'s your plan. "' in fb and '"You follow it. "' in fb and "following: !!peek.following" in app)
    check("as of: the tree's day, from GET /plans/trees' at, under its heading",
          "at: r.at, ...JSON.parse(r.doc)" in plans_ts and "const treeAt = raw.at ?" in builder and "`Tags as of ${pretty(treeAt)}`" in builder)


def test_plans_round_three_site_v381():
    """Plans, round three, on duecrew.com (Sam signed off): co-authors say yes
    first and a plan can be handed over (Settings, and Home's invite lines);
    where to get the deck; notes for followers on a tag or a card (Note, the
    ⓘ, Notes on cards, note | lines in the text, both prompts); a date's
    picked cards read by the deck tags they sit under (`pl`)."""
    site = os.path.join(REPO, "site", "public")
    builder = open(os.path.join(site, "builder.js"), encoding="utf-8").read()
    app = open(os.path.join(site, "app.js"), encoding="utf-8").read()
    css = open(os.path.join(site, "app.css"), encoding="utf-8").read()
    text_page = open(os.path.join(site, "plan-text.html"), encoding="utf-8").read()
    # 1: co-authors who said yes, and handing a plan over
    co = builder[builder.index("function coauthorsBox() {"):builder.index("/** 3.5, B: list the plan in the library")]
    check("r3 site: Settings lists co-authors: an invite waits (Take back), one who said yes can be handed it or taken off",
          '"Invited, waiting for "' in co and '"Take back"' in co and "`Hand it to ${e.name}`" in co and '"Remove"' in co
          and 'h("label", {}, "Co-authors"), coauthorsBox(),' in builder)
    check("r3 site: an offer is said with Take back, and stands alone (no second Hand it to)",
          '"Offered to "' in co and "offered ? null : h(\"button\"" in co and "offer(null, ev.currentTarget)" in co)
    check("r3 site: each is one request on its click: POST /owner {uid}, DELETE /editors/{uid}, POST /editors {uid}",
          'api("POST", `/plans/${id}/owner`, { uid })' in co and 'api("DELETE", `/plans/${id}/editors/${e.uid}`)' in co
          and 'api("POST", `/plans/${id}/editors`, { uid: who.uid })' in co and co.count("api(") == 4)
    check("r3 site: an invite isn't a co-author yet: not in the plan's line, shown as invited in Share",
          "x.uid !== me.uid && !x.pending" in builder and "`${x.name}, invited`" in builder and '"Co-authors…"' in builder)
    inv = app[app.index("function planInvites() {"):app.index("// board.py's footer")]
    check("r3 site: Home's invite lines, as the add-on's board says them, above the plans",
          '" asked you to co-write "' in inv and '". Its tags would go on your notes in Anki."' in inv and '" offered you "' in inv
          and '" to keep."' in inv and "b.planInvites" in inv and app.count("planInvites(),") == 2)
    check("r3 site: Yes and No are one request each, POST /plans/{id}/invite {yes, kind}",
          inv.count("api(") == 1 and 'api("POST", `/plans/${x.id}/invite`, { yes, ...(x.kind === "coauthor" || x.kind === "owner" ? { kind: x.kind } : {}) })' in inv
          and '"Yes"' in inv and '"No"' in inv and "Open it ›" in inv)
    # 2: where to get the deck
    deck_link = re.search(r"const deckLink = \(u\) => typeof u === \"string\" && u.length <= 300 && /(.*?)/\.test\(u\);", app)
    ok_link = lambda u: len(u) <= 300 and bool(re.match(deck_link.group(1).replace("\\/", "/"), u))  # noqa: E731
    check("r3 site: a deck link is https://, no spaces or quotes, 300 at most, or never a link (plans.ts DECK_URL)",
          bool(deck_link) and ok_link("https://example.com/deck?v=12") and not any(ok_link(x) for x in (
              "http://example.com", "javascript:alert(1)", "https://a b", 'https://x"y', "https:///x", "https://" + "a" * 293))
          and all(f"deckLink({x})" in app + builder for x in ("v", "url", "doc.deckUrl")))
    check("r3 site: Settings' field; the link page and the poster say Where to get it ›",
          '"Where to get the deck (a link, optional)"' in builder and app.count('"Where to get it ›"') == 1
          and builder.count('"Where to get it ›"') == 1 and "deckUrl: peek.doc.deckUrl" in app
          and "steps(p.deck, true, p.deckUrl)" in app and "steps(p.deck, false, p.deckUrl)" in app)
    check("r3 site: a save says where to get the deck changed; a merge keeps it",
          '["deckUrl", "where to get the deck"]' in builder and '"every", "deckUrl"]) {' in builder)
    # 3: notes for followers on a tag or a card
    check("r3 site: notes ride the doc: 300 a plan, one line of 280, one a tag or a card",
          "const MAX = 300, TEXT = 280;" in builder and "function setTagRemark(path, text)" in builder
          and "const same = (a, b) => (a.card ?" in builder)
    check("r3 site: Note on a deck tag's or a cut's chip in the day; the ⓘ on the calendar and in the day",
          "const noteTag = (c) => (c.cut ? c.cut.tag : c.key && !c.picks && kindOf(c.key) === \"tag\" ? pathOf(c.key) : null);" in builder
          and '}, "Note") : null,' in builder and 'h("i", { class: "ri", "aria-label": `Note: ${rmk.text}` }, "ⓘ ")' in builder
          and "return [chip, nt ? remarkBox(nt) : null];" in builder and ".flatMap((c) => chipEl(u, c))" in builder)
    check("r3 site: a row shows its tag's note or the nearest tag above it's, as in Anki",
          "p.startsWith(`${r.tag.toLowerCase()}::`)" in builder and ".sort((a, b) => b.tag.length - a.tag.length)[0]" in builder)
    check("r3 site: Notes on cards: which card by ID and number, never its text, the authors take one off",
          '"Notes on cards"' in builder and "`${r.card[0]} · card ${r.card[1] + 1}`" in builder
          and "putRemarks(remarks().filter((x) => x !== r)); mark(); draw();" in builder)
    check("r3 site: a renamed or deleted plan tag's note follows it or goes",
          "putRemarks(newPath ? remarks().map((r) => (r.tag && r.tag.toLowerCase() === low ? { ...r, tag: newPath } : r))" in builder)
    check("r3 site: the text writes note lines after the dates and reads them (Add dates adds, the whole plan replaces)",
          "...remarks().map(Remarks.line)].join(\"\\n\"); };" in builder
          and "const line = (r) => (r.card ? `note | card:${r.card[0]}:${r.card[1] + 1} | ${r.text}` : `note | tag:${r.tag} | ${r.text}`);" in builder
          and "if (replace) putRemarks(r.remarks.map(keepId));" in builder and "Takes off ${goneRmk.length} note" in builder)
    # the reading regexes, run here on lines a guid with | and : can make
    take_card = re.search(r"let m = /(\^card:.*?\$)/i\.exec\(rest\);", builder).group(1).replace("\\/", "/")
    take_tag = re.search(r"m = /(\^tag:.*?\$)/i\.exec\(rest\);", builder).group(1)
    note_line = re.search(r"const nl = /(\^note.*?\$)/i\.exec\(line\);", builder).group(1)
    m = re.match(note_line, "note | card:Zq|7!m:N2:3 | On the quiz | Friday.", re.I)
    c = m and re.match(take_card, m.group(1), re.I)
    check("r3 site: note | card:GUID:N reads a guid holding | and :, N from 1, the rest the note",
          bool(c) and c.group(1) == "Zq|7!m:N2" and c.group(2) == "3" and c.group(3) == "On the quiz | Friday.", str(c and c.groups()))
    t = re.match(take_tag, "tag:SLG 12 | Slides first.", re.I)
    check("r3 site: note | tag: takes a plan tag's name with its space", bool(t) and t.group(1) == "SLG 12" and t.group(2) == "Slides first.")
    check("r3 site: both AI prompts mention note lines; the format's page documents them",
          "note | tag:FULL::TAG::PATH | Skip the last two minutes, or note | card:ID:N |" in builder
          and "note | tag:NAME | your words, or note | card:ID:N | your words." in builder
          and 'id="remarks"' in text_page and "note | card:Zq7!mN2pLk:2 |" in text_page and "Up to 300 a plan." in text_page)
    # 4: a date's picked cards by their resource's name
    check("r3 site: a picked chip reads by its first label (88 picked until the author's Anki says)",
          "`${plWord(pl[0][0])} · ${pl[0][1].toLocaleString()} picked` : `${picksN(u).toLocaleString()} picked`" in builder
          and "picks: true, text: picksText(u), raw: picksList(u)" in builder and "cards: true, text:" not in builder)
    check("r3 site: pl counts only while the date's picks are as they loaded, and goes back as it came",
          "was && picksSig(was) === picksSig(u) ? u.pl : null" in builder and "pl && was.get(u.id) === picksSig(u) ? { ...u, pl } : u" in builder
          and "lean(merge(doc, base, theirs.doc), theirs.doc.units || [])" in builder
          and "if (old?.pl && picksSig(old) === picksSig(u)) u.pl = old.pl;" in builder)
    check("r3 site: the new parts are styled", all(x in css for x in (".firststeps", ".chips2 .rmk", ".cnote", ".coa", ".pinv", ".pdeck", ".ch2 .xtra")))


def test_plans_round_three_builder_v381():
    """Plans, round three, in the builder (Sam signed off): a date after its
    event is reinforcement ("after Heme quiz"); a tag's extras split, with
    them or without; Edit the whole plan keeps a renamed tag (its dates
    follow) and the save says what changed as revisions; first steps on an
    empty plan."""
    site = os.path.join(REPO, "site", "public")
    builder = open(os.path.join(site, "builder.js"), encoding="utf-8").read()
    text_page = open(os.path.join(site, "plan-text.html"), encoding="utf-8").read()
    # 5: reinforcement, the same rule as the add-on's
    check("r3 builder: a date after its event's day is reinforcement",
          "const afterEv = (u) => { const ev = u.for && evById(u.for); return !!ev && ev.day < u.opens; };" in builder
          and "doc.units.filter((u) => u.for === id && !afterEv(u))" in builder)
    check("r3 builder: the calendar, the day panel and the printout say after",
          'evById(id).day < d ? "after " : "for "' in builder and 'after ? "After " : "For "' in builder
          and "${forWord(u)} ${fx.name}, ${pretty(fx.day)}" in builder and 'h("optgroup", { label: "After" }' in builder
          and "evById(u.for) && !afterEv(u)) ? \"lead\"" in builder)
    check("r3 builder: the format's page and the prompt say it", "&ldquo;after Heme quiz&rdquo;" in text_page
          and 'it reads \\"after Micro quiz\\", review after it.' in builder)
    # 6: extras
    ex = re.search(r"const EXTRA = /(.*?)/i;", builder).group(1)
    is_extra = lambda seg: bool(re.match(ex, re.sub(r"[_#]", "", seg), re.I))  # noqa: E731
    check("r3 builder: a child named Extra, Extras, Bonus or Supplement (any case, _ and # aside) is a tag's extras",
          all(is_extra(x) for x in ("Extra", "#Extras", "BONUS", "_Supplement_", "extra_")) and not any(is_extra(x) for x in ("Extraction", "Supplements2", "Bonuses")))
    check("r3 builder: the split, and Without as a search less each extra, named X but not Extra",
          "`${main.toLocaleString()} + ${ex.toLocaleString()} extra`" in builder and '[[false, "With extras"], [true, "Without"]]' in builder
          and '[Tags.ankiSearch("tag", path), ...extraKids(`tag:${path}`).map((k) => `-${Tags.ankiSearch("tag", pathOf(k))}`)].join(" ")' in builder
          and "`${ws[0][1]} but not ${ws.slice(1).map(([, w]) => w).join(\", \")}`" in builder)
    # 7: revisions
    check("r3 builder: the whole plan's text keeps a renamed tag (same contents, a new name) and its dates follow",
          "renamed.push({ id: was[0].id, from: ptagPath(was[0]), was: was[0].name });" in builder
          and "if (t) retag(x.from, ptagPath(t)); }" in builder and "` · was ${was.name}`" in builder
          and builder.index("const renamed = [];") < builder.index("for (const c of pendingCuts) {"))
    check("r3 builder: a save's summary: updated Fri 16 Oct, renamed / added / took off N tags, the notes",
          "out.push(`updated ${pretty(updated[0].opens)}`)" in builder and "out.push(`renamed ${nTags(ren.length)}`)" in builder
          and "out.push(`added ${nTags(tAdded)}`)" in builder and "out.push(`took off ${nTags(tGone)}`)" in builder
          and "out.push(`added ${nNotes2(rAdded)}`)" in builder)
    check("r3 builder: a date that only followed a renamed tag hasn't changed; dates compare in any key order",
          "!same(follow(b.get(u.id)), u)" in builder and "Object.keys(v).sort()" in builder)
    # Sam's pick: first steps on an empty plan
    fs = builder[builder.index("// 3.8.1 (Sam's pick): first steps"):builder.index("const main = h(\"div\", { class: \"main2\" },")]
    check("r3 builder: first steps while the plan as saved has no dates, gone once it's saved with them",
          "author && view !== \"print\" && !(plan.doc.units || []).length" in fs and "firstSteps, paceBox," in builder)
    check("r3 builder: Tick what to cover · Fill to <end> · Save · Share the code, the step now bold, done ones ticked",
          all(x in fs for x in ('"Tick what to cover"', "fillLabel", '"Save"', '"Share the code"', 'done ? "✓"', 'i === now ? h("b", {}, t) : t', '"aria-current"')))


def test_plan_tags_insights_v381():
    """3.8.1 (Sam's pick): a plan's own tags stay out of Insights' own
    choices (its topics, the map's first pick); the map's "by" gets one
    named way a plan, each SLG a tile, with the ones no card carries."""
    from due_crew import team as T, board
    sys_tags = ["Step1::^Systems::Cardio::Heart", "Step1::^Systems::Renal::Kidney", "Step1::^Systems::Pulm::Lung"]
    tags_of = {i: [sys_tags[i % 3], f"DueCrew::MS2_Block_1::SLG_{i % 5}"] for i in range(90)}
    know = {i: (0.95 if i % 2 else 0.6) for i in range(90)}
    topics, _groups = T.deck_topics(tags_of, set(tags_of))
    check("r2 insights: a plan's own tags are never a topic of Not sticking yet",
          not any("SLG" in t[1] for t in topics) and topics, str([t[1] for t in topics]))
    tiles, ways = T.subjects_by(tags_of, know, set(tags_of))
    check("r2 insights: nor the map's own pick, nor one of its ways",
          not any("duecrew" in w["key"].lower() or "MS2" in w["name"] for w in ways) and {t["name"] for t in tiles} == {"Cardio", "Renal", "Pulm"},
          str((ways, [t["name"] for t in tiles])))
    held = [("SLG 1", "DueCrew::MS2_Block_1::SLG_1", set(range(0, 40))), ("SLG 2", "DueCrew::MS2_Block_1::SLG_2", set(range(40, 50))),
            ("SLG 19", "DueCrew::MS2_Block_1::SLG_19", set()), ("SLG 3", "DueCrew::MS2_Block_1::SLG_3", {200})]
    pt, none = T.plan_tiles(held, know, set(range(90)))
    check("r2 insights: by a plan's tags: a tile a tag, biggest first, shaded by what I know; Browse by its tag",
          [t["name"] for t in pt] == ["SLG 1", "SLG 2"] and pt[0]["n"] == 40 and pt[0]["know"] == round(100 * (20 * 0.95 + 20 * 0.6) / 40)
          and pt[0]["find"] == {"tags": ["DueCrew::MS2_Block_1::SLG_1"]}, str(pt))
    check("r2 insights: the ones no card here carries are named (one with cards, none in play, isn't)", none == ["SLG 19"], str(none))
    way = {"key": "~plan:p1", "name": "MS2 Block 1's tags", "on": True, "none": ["SLG 19", "SLG <22>"]}
    html = board._ins_map(10, pt, "fsrs", (), [{"key": "x", "name": "Systems", "on": False}, way])
    check("r2 insights: picked, the way reads by the plan's name, and the gap is said, escaped",
          "MS2 Block 1&#x27;s tags" in html and "No card in this deck carries SLG 19, SLG &lt;22&gt;." in html, html[-400:])
    html2 = board._ins_map(10, pt, "fsrs", (), [dict(way, on=False), {"key": "x", "name": "Systems", "on": True}])
    check("r2 insights: another way picked, no gap line", "No card in this deck" not in html2)
    from due_crew import team_flow as TF
    from due_crew.backend import shapes
    col = _tag_col()
    doc = shapes.clean_plan_doc({"deck": "Step 1", "units": [], "tagroot": "MS2_Block_1", "tags": [
        {"id": "t1", "name": "SLG 1", "notes": ["guid000001", "guid000002"]}, {"id": "t2", "name": "SLG 2", "tags": ["#Video::Auto"]},
        {"id": "t3", "name": "SLG 9", "notes": ["elsewhere"]}]})
    saved = TF._tag_plans
    try:
        TF._tag_plans = lambda c, did: [("p1", "MS2 Block 1", doc, None)]
        got = TF._plan_ways(col, 10, {1, 2, 4, 5, 6}, {1: 0.9, 4: 0.5})
    finally:
        TF._tag_plans = saved
    way, tiles = got["~plan:p1"]
    check("r2 insights: the plan's way reads what its tags hold in this deck, cards in play only",
          way["name"] == "MS2 Block 1's tags" and way["none"] == ["SLG 9"]
          and [(t["name"], t["n"]) for t in tiles] == [("SLG 2", 3), ("SLG 1", 2)], str((way, tiles)))


def test_tag_pass_reads_a_deck_once_v381():
    """3.8.1, the audit (#9): plans that share a deck read it once a tag pass,
    and a plan whose tags moved notes makes the next plan read it fresh."""
    from due_crew import plan_flow as F, plans as P
    reads, moves = [], {}
    pc = {"plans": {"a": {"deck_id": 10}, "b": {"deck_id": 10}, "c": {"deck_id": 20}}}
    plan_list = [{"id": k, "name": k, "doc": {"tags": [{"id": "t1", "name": "SLG 1", "notes": ["g1"]}]}} for k in ("a", "b", "c")]
    names = ("_pcfg", "_psave", "_today", "tooltip", "_deck_ok", "_tags_changed")
    saved = {n: getattr(F, n) for n in names}
    real = (P.DeckIndex, P.sync_tags, dc_mw().col)
    try:
        F._pcfg, F._psave, F.tooltip = (lambda: pc), (lambda c: None), (lambda *a, **k: None)
        F._deck_ok, F._tags_changed = (lambda col, did: True), (lambda: None)
        dc_mw().col = object()
        P.DeckIndex = lambda col, did: reads.append(did) or ("idx", did)
        P.sync_tags = lambda col, idx, doc, applied, label, swap=None: (
            {"t1": "DueCrew::x::SLG_1"}, {"added": moves.get(label, 0), "removed": 0, "new": [], "missing": {}})
        F._today = lambda: "2026-10-13"
        F.apply_tags(plan_list, toast=False)
        check("tag pass: two plans on one deck read it once", reads == [10, 20], str(reads))
        reads.clear()
        moves["Due Crew: a's tags"] = 3
        F._today = lambda: "2026-10-14"
        F.apply_tags(plan_list, toast=False)
        check("tag pass: a plan whose tags moved notes makes the next one read fresh", reads == [10, 10, 20], str(reads))
    finally:
        for n, v in saved.items():
            setattr(F, n, v)
        P.DeckIndex, P.sync_tags, dc_mw().col = real


def test_sign_in_says_what_went_wrong_v381():
    """3.8.1, the audit (#5): asking for a code blames the address only when
    the server says the address is bad; the mail being down says so."""
    cl = api.ApiClient(os.path.join(tempfile.mkdtemp(), "session.json"))
    said = []
    for status in (502, 503, 429):
        def boom(*a, _s=status, **k):
            raise shapes.TransportError("x", status=_s)
        cl._call = boom
        try:
            cl.request_code("dre@example.com")
        except api.AuthError as e:
            said.append(str(e))
    cl._call = lambda *a, **k: (400, {"error": "bad_email"})
    try:
        cl.request_code("nope")
    except api.AuthError as e:
        said.append(str(e))
    check("sign-in: mail trouble isn't the address; too many is too many; a bad address is",
          said == ["mail_failed", "mail_failed", "slow_down", "bad_email"], str(said))


def test_plan_tags_glue_v380():
    """3.8.0, plan tags in the add-on: Browse sends the picked notes' guids
    to the plan (owner or co-author) and tags them here; a follower's Anki
    takes them as soon as the plan's update is here (the morning, a mid-day
    update, a new follow), before what opens; the plan card says so once;
    Stop asks before taking them off; a plan gone takes them along."""
    import due_crew as dc
    from due_crew import plan_flow as F, plans as P, board
    from aqt.deckbrowser import DeckBrowser
    w = world({"dre": "Dre", "maya": "Maya", "kai": "Kai"})
    pid, _code = w.add_plan("dre", "MS2 Block 1", "Step 1", [])
    w.plans[pid]["editors"] = {"maya"}
    dre = new_client(w, "dre", "Dre")
    got, status = dre.tag_plan_notes(pid, "SLG 12", add=["guid000001", "guid000002"])
    check("tags: Browse's notes reach the plan by guid, the plan's part made from its name",
          status == 200 and got["doc"]["tagroot"] == "MS2_Block_1"
          and got["doc"]["tags"][0]["name"] == "SLG 12" and got["doc"]["tags"][0]["notes"] == ["guid000001", "guid000002"], str(got and got["doc"]))
    maya = new_client(w, "maya", "Maya")
    check("tags: a co-author tags too", maya.tag_plan_notes(pid, "SLG 13", add=["guid000003"])[1] == 200)
    kai = new_client(w, "kai", "Kai")
    check("tags: anyone else can't", kai.tag_plan_notes(pid, "SLG 12", add=["guid000009"])[1] == 403)
    kpid, _kc = w.add_plan("kai", "ms2 block 1", "Step 1", [])
    check("tags: another plan of the same name (any case) gets a root of its own",
          kai.tag_plan_notes(kpid, "SLG 1", add=["guid000009"])[0]["doc"]["tagroot"] == "ms2_block_1_2")
    del w.plans[kpid]
    check("tags: taken off, the last one takes the tag", maya.tag_plan_notes(pid, "slg 13", remove=["guid000003"])[0]["doc"]["tags"][0]["name"] == "SLG 12")
    # a follower's Anki: the morning, an update, a new follow
    col = _tag_col()
    plan = dict(w._plan_view(pid, "kai"), deck_id=10)
    from due_crew.backend import shapes
    plan = dict(shapes.clean_plan(plan), id=pid)
    pc = {"plans": {pid: {"deck_id": 10, "applied": {}}}}
    saved = (F._pcfg, F._psave, dc_mw().col, F._today, F.tooltip)
    said = []
    try:
        F._pcfg, F._psave = (lambda: pc), (lambda c: None)
        dc_mw().col = col
        F._today = lambda: TODAY.isoformat()
        F.tooltip = lambda msg, **k: said.append(msg)
        line = F.apply_tags([plan])
        st = pc["plans"][pid]
        check("tags: a follower's notes carry the plan's tag, remembered by its id, said once",
              st["tags"] == {plan["doc"]["tags"][0]["id"]: "DueCrew::MS2_Block_1::SLG_12"}
              and "DueCrew::MS2_Block_1::SLG_12" in _tags_of(col, 1) and line and "SLG 12" in line
              and st["tag_news"]["names"] == ["SLG 12"], str((st, line)))
        reads = []
        real_idx = P.DeckIndex
        P.DeckIndex = lambda *a, **k: reads.append(1) or real_idx(*a, **k)
        try:
            again = F.apply_tags([plan])
            edited = dict(plan, doc=dict(plan["doc"], tags=[dict(plan["doc"]["tags"][0], notes=["guid000001"])]))
            F.apply_tags([edited])
            F._today = lambda: (TODAY + datetime.timedelta(days=1)).isoformat()
            F.apply_tags([edited])
        finally:
            P.DeckIndex = real_idx
            F._today = lambda: TODAY.isoformat()
        check("tags: the deck is read again only when the plan's tags change, or the next Anki day",
              again is None and len(reads) == 2 and "DueCrew::MS2_Block_1::SLG_12" not in _tags_of(col, 2), str(reads))
        F.apply_tags([plan])
        view = F.card_view(plan, st, {}, TODAY.isoformat())
        html = board._plan_card_html(dict(view, tag_news=dict(view["tag_news"], names=["<SLG 12>"]), id=pid))
        check("tags: the plan card says it the day it happens, escaped, with Browse them and OK",
              "New tags: <b>&lt;SLG 12&gt;</b>" in html and f"duecrew:plantags:{pid}" in html and f"duecrew:plantagsok:{pid}" in html, html[:300])
        opened = []
        before = F.tags_seen
        F.tags_seen = lambda p, swap=True: opened.append(("seen", p))
        try:
            dc._on_js(False, as_board(f"duecrew:plantagsok:{pid}"), DeckBrowser())
        finally:
            F.tags_seen = before
        check("tags: the card's OK reaches its handler", opened == [("seen", pid)], str(opened))
        F.tags_seen(pid, swap=False)
        check("tags: OK clears the line", "tag_news" not in pc["plans"][pid])
        src = srcs.flow_src()
        morning = src[src.index("def maybe_morning"):src.index("def _morning_waits")]
        check("tags: the morning tags before what opens, after the sync and on Decks",
              morning.index("apply_tags(plan_list, toast=False)") < morning.index("_open_now([p for p in plan_list if not p.get(\"paused\")]")
              and morning.index("if awaiting_sync or") < morning.index("apply_tags(plan_list") and morning.index("if not here:") < morning.index("apply_tags(plan_list"))
        mid = src[src.index("def midday"):src.index("def hold_new")]
        check("tags: an update later in the day tags at once (on Decks), before what it opens",
              mid.index('if getattr(mw, "state", "") != "deckBrowser"') < mid.index("apply_tags(plan_list") < mid.index("dry = run("))
        fol = src[src.index("def on_followed"):src.index("def open_site")]
        check("tags: a new follow tags before its first dates open", fol.index("apply_tags([fresh])") < fol.index("res = _open_now([fresh]"))
        check("tags: a plan gone takes its tags off (and waits for Decks to)",
              '_drop_plan_tags(was, "a plan you followed")' in morning and '.get("tags") for pid in gone)' in morning)
        stop = src[src.index("def stop_following"):src.index("# ---- following ----")]
        check("tags: Stop asks with a box to tick before taking them off", "confirm_check(" in stop and "if untag:" in stop)
        n = F._drop_plan_tags(pc["plans"][pid], "MS2 Block 1")
        check("tags: taking them off on Stop", n == 2 and not any(t.startswith("DueCrew") for t in _tags_of(col, 1)))
        # Browse › tag for a plan: the sheet sends the guids; this Anki tags them at once, and a plan
        # I follow myself doesn't call the tag new when its update comes
        import types
        caught = {}

        class Sheet:
            def __init__(self, parent, cl, guids, on_done=None, outside=None):
                caught.update(guids=guids, done=on_done, outside=outside)

            def exec(self):
                return 0
        was_mod, was_in = sys.modules.get("due_crew.ui.tag_dialog"), F._signed_in
        sys.modules["due_crew.ui.tag_dialog"] = types.SimpleNamespace(TagDialog=Sheet)
        F._signed_in = lambda: True
        try:
            class Browser:
                def selected_notes(self):
                    return [4, 5]
            F.tag_for_plan(Browser())
            g45 = caught["guids"]
            col.decks = fakes.FakeDecks({10: "Step 1", 11: "Other"})
            col.db.conn.execute("UPDATE cards SET did = 11 WHERE nid = 5")
            n_out = caught["outside"]({"doc": {"deck": "step 1"}})
            col.db.conn.execute("UPDATE cards SET did = 10 WHERE nid = 5")
            check("tags: the sheet counts the picked notes outside the plan's deck (followers tag inside it only)",
                  n_out == 1 and caught["outside"]({"doc": {"deck": "Step 1"}}) == 0 and caught["outside"]({"doc": {"deck": "Gone"}}) == 0, str(n_out))
            mine_plan, _st = dre.tag_plan_notes(pid, "SLG 15", add=g45)
            caught["done"](dict(mine_plan, id=pid), "SLG 15", "DueCrew::MS2_Block_1::SLG_15", g45, [])
            fresh = dict(shapes.clean_plan(dict(w._plan_view(pid, "kai"), deck_id=10)), id=pid)
            pc["plans"][pid].pop("tag_news", None)
            F.apply_tags([fresh])
            news = (pc["plans"][pid].get("tag_news") or {}).get("names") or []
            check("tags: Browse's notes carry the tag here at once, and my own update doesn't call it new",
                  len(g45) == 2 and all("DueCrew::MS2_Block_1::SLG_15" in _tags_of(col, n) for n in (4, 5))
                  and "SLG 15" not in news and any("as SLG 15" in x for x in said), str((news, said[-1:])))
        finally:
            F._signed_in = was_in
            if was_mod is None:
                sys.modules.pop("due_crew.ui.tag_dialog", None)
            else:
                sys.modules["due_crew.ui.tag_dialog"] = was_mod
        # the plans I write and don't follow carry their tags in my Anki too (counts, older followers' ids)
        col2 = _tag_col()
        dc_mw().col = col2
        pc2 = {"plans": {}}
        F._pcfg = lambda: pc2
        dre.fetch_board([TODAY.isoformat()], with_decks=True)
        lean = next(a for a in dre.session["plans_authored"] if a["id"] == pid)
        sent, reads = [], []
        was_cl, was_ids, real_idx = F.client, F.send_ids, P.DeckIndex
        F.client, F.send_ids = (lambda: dre), (lambda: sent.append(1))
        P.DeckIndex = lambda *a, **k: reads.append(1) or real_idx(*a, **k)
        try:
            line = F.apply_authored_tags(toast=False)
            mine = pc2.get("authored_tags", {}).get(pid) or {}
            check("authored tags: the plan's tags come with its name; my notes carry them, my ids go again, said once",
                  lean["name"] == "MS2 Block 1" and lean["doc"]["tagroot"] == "MS2_Block_1" and len(lean["doc"]["tags"]) == 2
                  and "DueCrew::MS2_Block_1::SLG_12" in _tags_of(col2, 1) and "DueCrew::MS2_Block_1::SLG_15" in _tags_of(col2, 4)
                  and len(mine.get("tags") or {}) == 2 and sent == [1] and line and "MS2 Block 1" in line, str((line, mine, sent)))
            reads.clear()
            check("authored tags: the same day, nothing new: the deck isn't read", F.apply_authored_tags(toast=False) is None and not reads and sent == [1])
            pc2["plans"][pid] = {"deck_id": 10}
            F.apply_authored_tags(toast=False)
            check("authored tags: following my own plan hands them to the follow (not new there)",
                  pid not in pc2["authored_tags"] and len(pc2["plans"][pid].get("tags") or {}) == 2)
            pc2["authored_tags"] = {pid: {"deck_id": 10, "tags": pc2["plans"].pop(pid)["tags"]}}
            dre.session["plans_authored"] = []
            F.apply_authored_tags(toast=False)
            check("authored tags: a plan I no longer write takes them off my notes",
                  pid not in pc2["authored_tags"] and not any(t.startswith("DueCrew") for n in (1, 2, 4, 5) for t in _tags_of(col2, n)))
        finally:
            F.client, F.send_ids, P.DeckIndex = was_cl, was_ids, real_idx
    finally:
        F._pcfg, F._psave, dc_mw().col, F._today, F.tooltip = saved
    menu = srcs.flow_src()
    check("tags: Browse's menu has it, signed in", 'menu.addAction("Due Crew: tag for a plan…")' in menu
          and menu.index('if not client().signed_in') < menu.index('"Due Crew: tag for a plan…"'))


def test_own_pace_v380():
    """3.8.0, at my own pace (Sam's picks on the Your Own Pace mock): a follow
    says how its cards open: on the plan's dates (as before), when I'm ready
    (nothing opens by itself; You › Plans' Open opens the next date, first in
    Anki's line, one undo step), or the next once I've seen the last. No
    Behind; a quiet line says where the plan's dates are, my pace, the exam.
    Put back shuts the last date's unseen cards again. Browse opens a tag's
    cards or the picked ones: never suspends, leeches stay, first in line."""
    import due_crew as dc
    from due_crew import plans as P, board, due_flow
    from aqt.deckbrowser import DeckBrowser
    doc = {"deck": "Step 1", "units": [dict(u) for u in _plan_units()],
           "events": [{"id": "ex1", "day": _day(20), "name": "Block exam"}]}
    us = P.units(doc)
    sig = P.unit_sig
    check("own: up next is every date in the plan's order, none opened", [u["id"] for u in P.up_next(doc, {})] == [u["id"] for u in us])
    applied = {"hf": sig(us[0]), "ar": "skip:" + sig(us[1])}
    check("own: an opened date and a skipped one aren't up next", [u["id"] for u in P.up_next(doc, applied)] == ["ex", "cz", "rn"])
    check("own: an opened date shut again since (Undo) is up next again",
          P.up_next(doc, applied, {"hf": [0, 0, 2]})[0]["id"] == "hf")
    check("own: a morning opens only what an author adds to dates I opened",
          P.own_due(doc, {"hf": "old"}, sig) == [(us[0], "open")] and P.own_due(doc, applied, sig) == [])
    days = {"hf": _day(-1)}
    check("own, next: nothing before I open one, nor till I've seen most of the last",
          P.next_by_itself(doc, applied, {}, {}) is None
          and P.next_by_itself(doc, applied, days, {"hf": [2, 1, 2]}) is None
          and P.next_by_itself(doc, applied, days, {"hf": [10, 9, 10]})["id"] == "ex")
    check("own: where the plan's dates are", P.plan_at(doc, _day(4)) == "The plan's dates are at Extras today."
          and P.plan_at(doc, _day(-30)).startswith("The plan's dates start "))
    recent = P.recent_opens({"a": _day(-20), "b": _day(-13), "c": _day(0)}, _day(0))
    check("own: my pace is the dates I opened in the last two weeks", recent == 2, recent)
    late = P.finish_check(doc, 4, 2, _day(0))
    check("own: the exam check names the plan's exam and the day my pace gets there",
          late == f"At that pace you open the last set on {P.fmt_day(_day(28))}, 8 days after Block exam.", late)
    check("own: in time says so; no pace, no exam: no line",
          "in time for Block exam" in P.finish_check(doc, 1, 7, _day(0))
          and P.finish_check(doc, 4, 0, _day(0)) is None and P.finish_check(dict(doc, events=[]), 4, 2, _day(0)) is None)
    idx = P.DeckIndex(_plan_col(), 10)
    check("own: Hold back holds every date I haven't opened, whatever its day",
          P.holdable(idx, doc, _day(0)) == set() and P.holdable(idx, doc, _day(0), own=True) == set())

    store = world({"dre": "Dre", "maya": "Maya"})
    pid, code = store.add_plan("dre", "Step 1", "Step 1", _plan_units())
    store.plans[pid]["doc"]["events"] = [{"id": "ex1", "day": _day(20), "name": "Block exam"}]
    maya = new_client(store, "maya", "Maya")
    plan, _ = maya.follow_plan(code, own="ready")
    check("own: chosen at Follow, on my follow", plan["own"] == "ready" and store.follows[(pid, "maya")]["own"] == "ready")
    col = _plan_col()
    fakes.add_card(col.db.conn, 30, did=10, queue=-1, tags="Step1::Cardio::Heart_failure leech")
    for cid, due in ((1, 50), (2, 51), (3, 52), (4, 53), (5, 54), (6, 55), (9, 56), (30, 57)):
        col.db.conn.execute("UPDATE cards SET due = ? WHERE id = ?", (due, cid))
    with _PlanGlue({"A": maya}, {"A": col}) as g:
        F = g.F
        F.on_followed(plan, 10, None, "open")
        check("own: following at my own pace opens nothing by itself", _open(col) == {8}, sorted(_open(col)))
        p = next(x for x in F.followed() if x["id"] == pid)
        st = F._state_cfg()[pid]
        prog = F.progress(col, [p], F._state_cfg())[pid]
        v = F.card_view(p, st, prog, _day(0))
        check("own: the card says at your pace, Up next with what opens, and no Behind",
              v["sub"].startswith("at your pace") and v["own"]["next"]["name"] == "Heart failure" and v["own"]["next"]["n"] == 3  # not open yet, its leech too
              and v["lines"] == [] and not {"at", "pace", "finish"} & set(v["own"]) and "open" in v["own"], str(v["own"]))  # 3.9.10: no line against the plan's dates
        F.open_next(pid)
        st = F._state_cfg()[pid]
        dues = dict(col.db.all("SELECT id, due FROM cards"))
        check("own: Open opens the next date (never the leech), first in Anki's line, as one undo step",
              {1, 2} <= _open(col) and 30 not in _open(col) and dues[1] == 0 and dues[2] == 1 and dues[3] > 1
              and col.undo_status().undo == "Due Crew: open Heart failure" and st["own_opened"] == {"hf": _day(0)}, str(dues))
        F._state["plan_progress"] = F.progress(col, F.followed(), F._state_cfg())
        v = F.card_view(next(x for x in F.followed() if x["id"] == pid), st, F._state["plan_progress"][pid], _day(0))
        html = board._plan_card_html(dict(v, own=dict(v["own"], next=dict(v["own"]["next"], name="<Arr>"))))
        check("own: the card moves on, says what it did with Undo, names escaped",
              v["own"]["next"]["name"] == "Arrhythmia" and v["own"]["last"] == "Opened Heart failure · 2 cards, first in line."
              and "&lt;Arr&gt;" in html and f"duecrew:planpaceopen:{pid}" in html and f"duecrew:planpacestudy:{pid}" in html
              and f"duecrew:planpaceundo:{pid}" in html and "Up next" in html and "Behind" not in html, html[:400])
        dates, _e, _r = due_flow.plan_dates(_day(0))
        check("own: Due shows the date I opened as today's, and no date I haven't",
              [(d["uid"], d["opens"]) for d in dates if d["pid"] == pid] == [("hf", _day(0))], str([(d["uid"], d["opens"]) for d in dates]))
        sys.modules["aqt.operations"] = None  # an Anki without CollectionOp: undo runs here
        was_undo = getattr(F.mw, "undo", None)
        F.mw.undo = col.undo
        try:
            F.own_undo(pid)
        finally:
            sys.modules.pop("aqt.operations", None)
            if was_undo is None:
                del F.mw.undo
            else:
                F.mw.undo = was_undo
        st = F._state_cfg()[pid]
        check("own: Undo shuts them again and Heart failure is up next again",
              not ({1, 2} & _open(col)) and "hf" not in (st.get("applied") or {}) and not st.get("own_opened")
              and not F._pcfg().get("own_last"), str(st))
        F.open_next(pid)
        # "next": once I've seen most of the last date, the morning opens the one after
        maya.set_own(pid, "next")
        check("own: changed later with one request, kept on my follow",
              store.follows[(pid, "maya")]["own"] == "next" and next(x for x in F.followed() if x["id"] == pid)["own"] == "next")
        col.db.conn.execute("UPDATE cards SET type = 2, queue = 2 WHERE id IN (1, 2)")
        state = F._state_cfg()
        state[pid]["own_opened"]["hf"] = _day(-1)
        dry = F.run(col, F.followed(), json.loads(json.dumps(state)), _day(0), dry=True)
        check("own, next: a mid-day update's line never offers the next by itself", dry["names"] == [], str(dry))
        res = F.run(col, F.followed(), state, _day(0))
        check("own, next: seen the last one, the next opens by itself, and only that",
              res["names"] == ["Arrhythmia"] and 3 in _open(col) and 4 not in _open(col)
              and state[pid]["own_opened"].get("ar") == _day(0), str(res))
        res = F.run(col, F.followed(), state, _day(0))
        check("own, next: not another till I've seen this one", res["names"] == [], str(res))
        c = F._pcfg()
        c["plans"] = state
        F._psave(c)
        F._state["plan_progress"] = F.progress(col, F.followed(), F._state_cfg())
        v = F.card_view(next(x for x in F.followed() if x["id"] == pid), F._state_cfg()[pid], F._state["plan_progress"][pid], _day(0))
        check("own: Put back offers the last date's unseen cards", v["own"]["back"] == {"name": "Arrhythmia", "n": 1}, str(v["own"]))
        F.put_back_own(pid)
        st = F._state_cfg()[pid]
        check("own: Put back shuts only its unseen cards, one undo step; it's up next again, and Stop opens them",
              3 not in _open(col) and {1, 2} <= _open(col) and "ar" not in st["applied"] and 3 in st.get("held", [])
              and col.undo_status().undo == "Due Crew: put back Arrhythmia"
              and P.up_next(next(x for x in F.followed() if x["id"] == pid)["doc"], st["applied"])[0]["id"] == "ar")
        # Browse: open what I picked, or a tag's cards
        counts = P.open_counts(col, [3, 4, 8, 30])
        check("browse: the sheet counts what opens, what's open, the leeches", counts == {"open": 2, "already": 1, "leech": 1}, str(counts))
        n = F.open_cards_now([3, 4, 30], "Extras", first=True)
        st = F._state_cfg()[pid]
        dues = dict(col.db.all("SELECT id, due FROM cards"))
        check("browse: opened (never the leech), first in line, said with its Undo",
              n == 2 and {3, 4} <= _open(col) and 30 not in _open(col) and {dues[3], dues[4]} == {0, 1}
              and any("Opened 2 · first in line" in t for t in g.toasts))
        check("browse: at my own pace, dates now all open count as opened",
              "ex" in st["applied"] and "ar" in st["applied"] and st["own_opened"].get("ex") == _day(0))
        check("browse: a tag's words", F._tag_words("#Videos::Micro::12_Strep") == ("12 Strep", "#Videos › Micro › 12 Strep"))
        acts = []
        menu = types.SimpleNamespace(addSeparator=lambda: None,
                                     addAction=lambda t: acts.append(t) or types.SimpleNamespace(triggered=types.SimpleNamespace(connect=lambda f: None)))
        item_mod = types.ModuleType("aqt.browser.sidebar.item")
        item_mod.SidebarItemType = types.SimpleNamespace(TAG="tag", DECK="deck")
        saved_mod = sys.modules.get("aqt.browser.sidebar.item")
        sys.modules["aqt.browser.sidebar.item"] = item_mod
        try:
            F.sidebar_menu(types.SimpleNamespace(browser=None), menu, types.SimpleNamespace(item_type="tag", full_name="#Videos::Micro"), None)
            F.sidebar_menu(types.SimpleNamespace(browser=None), menu, types.SimpleNamespace(item_type="deck", full_name="Step 1"), None)
        finally:
            if saved_mod is None:
                sys.modules.pop("aqt.browser.sidebar.item", None)
            else:
                sys.modules["aqt.browser.sidebar.item"] = saved_mod
        check("browse: a tag in the sidebar has Due Crew: open its cards…, a deck doesn't", acts == ["Due Crew: open its cards…"], acts)
        # the card's commands reach their handlers, through the board's own path
        got = []
        saved = {k: getattr(F, k) for k in ("open_next", "own_undo", "put_back_own")}
        F.open_next = lambda p2, study=False: got.append(("open", p2, study))
        F.own_undo = lambda p2: got.append(("undo", p2))
        F.put_back_own = lambda p2: got.append(("back", p2))
        try:
            for cmd in ("planpaceopen", "planpacestudy", "planpaceundo", "planpaceback"):
                dc._on_js(False, as_board(f"duecrew:{cmd}:{pid}"), DeckBrowser())
        finally:
            for k, val in saved.items():
                setattr(F, k, val)
        check("own: Open, Open and study, Undo and Put back reach their handlers",
              got == [("open", pid, False), ("open", pid, True), ("undo", pid), ("back", pid)], str(got))
    check("own: back to the plan's dates with one request", maya.set_own(pid, None)["own"] == ""
          and "own" not in store.follows[(pid, "maya")] or store.follows[(pid, "maya")].get("own") is None)


def test_why_not_showing_v380():
    """3.8.0, pick 9: Browse › why isn't it showing? (why, pure): one plain
    sentence a card, in Anki's words, and Anki's own fix beside it;
    alike cards together."""
    from due_crew import why as W
    rooms = {1: {"new": 0, "rev": 30, "new_limit": 20, "rev_limit": 200},
             2: {"new": 5, "rev": 0, "new_limit": 20, "rev_limit": 100},
             3: {"new": 0, "rev": 0, "new_limit": 0, "rev_limit": 0}}
    names = {1: "Anatomy", 2: "Pharm", 3: "Archive", 9: "Custom Study Session"}
    ranks = {}
    ctx = {"today": 500, "now": 1_000_000, "ahead": 1200, "deck": lambda d: names.get(d, "?"),
           "left": lambda d: rooms.get(d, {}), "rank": lambda c: ranks.get(c["id"], 1),
           "size": lambda d: 12, "day": lambda n: f"day {n}", "clock": lambda t: "15:40", "fsrs": True}
    card = lambda i, **kw: dict({"id": i, "did": 1, "odid": 0, "queue": 0, "due": 0, "lapses": 0, "leech": False}, **kw)  # noqa: E731
    r = lambda c: W.reason(c, ctx)  # noqa: E731
    check("why: suspended, and a leech says how often it was forgotten; both unsuspend",
          r(card(1, queue=-1))["say"] == "Suspended, so Anki never shows it." and r(card(1, queue=-1))["fix"] == ("unsuspend",)
          and r(card(2, queue=-1, leech=True, lapses=8))["say"] == "Suspended as a leech: forgotten 8 times.")
    check("why: buried by a sibling or by me, both shown today with Anki's unbury",
          "another card from its note" in r(card(1, queue=-2))["say"] and r(card(1, queue=-3))["say"] == "Buried by you till tomorrow."
          and r(card(1, queue=-3))["fix"] == ("unbury",))
    f = r(card(1, did=9, odid=1, queue=2, due=400))
    check("why: in a filtered deck, named, with how many go home if it's emptied",
          f["say"] == "In Custom Study Session, a filtered deck, not in Anatomy: it shows when you study Custom Study Session. "
          "Emptying it sends its 12 cards home." and f["fix"] == ("empty", 9), f)
    ranks[5] = 43
    n1 = r(card(5))
    check("why: new, past today's limit: the limit's done, and enough more to reach it",
          n1["say"] == "New: today's 20 new cards in Anatomy are done." and n1["fix"] == ("more_new", 1, 43), n1)
    ranks[6] = 9
    n2 = r(card(6, did=2))
    check("why: new, further in line than what's left: how far, and the difference",
          n2["say"] == "New: about 8 new cards come before it, and Pharm has 5 left today." and n2["fix"] == ("more_new", 2, 4), n2)
    ranks[7] = 3
    check("why: new and within today's: study the deck",
          r(card(7, did=2))["fix"] == ("study", 2) and "in today's new cards" in r(card(7, did=2))["say"])
    check("why: a deck that takes no new cards says so", r(card(8, did=3))["say"] == "New, and Archive takes no new cards a day.")
    check("why: learning, back at a time; nothing to do",
          r(card(1, queue=1, due=1_000_000 + 3600))["say"].startswith("Learning: back at 15:40.")
          and r(card(1, queue=1, due=1_000_000 + 3600))["fix"] is None
          and r(card(1, queue=1, due=1_000_000 + 600))["fix"] == ("study", 1))
    nd = r(card(1, queue=2, due=505))
    check("why: a review not due yet, by FSRS; Study it now sets its due date to today",
          nd["say"] == "Not due till day 505, by FSRS." and nd["fix"] == ("due_now",)
          and W.label(nd["fix"], 1, ctx) == "Study it now" and W.label(nd["fix"], 3, ctx) == "Study them now")
    rd = r(card(1, did=2, queue=2, due=499))
    check("why: due, but the day's reviews are done: more reviews today",
          rd["say"] == "Due, but today's 100 reviews in Pharm are done." and rd["fix"] == ("more_rev", 2, W.REV_MORE))
    check("why: due and within today's: study the deck", r(card(1, queue=2, due=500))["fix"] == ("study", 1))
    ranks.update({11: 30, 12: 50})
    gs = W.groups([card(10, queue=-1), card(11), card(12), card(13, queue=-1, leech=True), card(14, queue=-1),
                   card(15, queue=2, due=510), card(16, queue=2, due=503)], ctx)
    by = {g["group"]: g for g in gs}
    check("why: alike cards together, the most first, said by how many",
          gs[0]["group"] == "suspended" and by["suspended"]["say"] == "3 suspended, 1 of them as leeches."
          and by["suspended"]["label"] == "Unsuspend them" and by["suspended"]["cids"] == [10, 13, 14]
          and by["not_due"]["say"] == "2 not due yet, the soonest day 503.", [(g["group"], g["say"]) for g in gs])
    check("why: new cards past the limit get enough for the furthest in line",
          by["new:1"]["fix"] == ("more_new", 1, 50) and by["new:1"]["label"] == "50 more new today"
          and by["new:1"]["say"] == "2 new, past today's 20 new cards in Anatomy.", by["new:1"])
    one = W.groups([card(1, did=9, odid=1, queue=2)], ctx)
    check("why: one card says its own sentence; Empty names the deck", one[0]["say"].startswith("In Custom Study Session")
          and one[0]["label"] == "Empty Custom Study Session")


def test_why_not_showing_glue_v380():
    """3.8.0, pick 9: the glue reads the picked cards (a leech by its tag,
    the order kept), asks Anki's deck tree for each deck's room, and runs
    each fix as Anki's own operation, then reads again; Browse's menu has
    it signed in or not."""
    from due_crew import why_flow as WF, plan_flow as PF
    col = make_user_col([TODAY])
    conn = col.db.conn
    for cid, nid, q, due, tags in ((1, 1, -1, 0, " leech marked "), (2, 2, 0, 7, ""), (3, 3, 0, 3, ""), (4, 4, 2, 9999, "")):
        conn.execute("INSERT INTO notes (id, guid, tags) VALUES (?, ?, ?)", (nid, f"g{nid}", tags))
        conn.execute("INSERT INTO cards (id, nid, did, queue, due, lapses) VALUES (?, ?, 1, ?, ?, 4)", (cid, nid, q, due))
    got = WF.facts(col, [4, 1, 99, 2])
    check("glue: the picked cards in order, a leech by its tag, one not there left out",
          [c["id"] for c in got] == [4, 1, 2] and got[1]["leech"] and not got[0]["leech"] and got[1]["lapses"] == 4, got)
    node = types.SimpleNamespace(new_count=1, review_count=0)
    col.decks = types.SimpleNamespace(name=lambda d: "Big Step 1::Anatomy", find_deck_in_tree=lambda tree, d: node,
                                      config_dict_for_deck_id=lambda d: {"new": {"perDay": 20}, "rev": {"perDay": 200}},
                                      deck_and_child_ids=lambda d: [1])
    col.sched.deck_due_tree = lambda: "tree"
    ctx = WF.context(col)
    check("glue: a deck by its own name, its room today from Anki's tree, a new card's place in line",
          ctx["deck"](1) == "Anatomy" and ctx["left"](1) == {"new": 1, "rev": 0, "new_limit": 20, "rev_limit": 200}
          and ctx["rank"]({"id": 2, "did": 1, "due": 7}) == 2 and ctx["rank"]({"id": 3, "did": 1, "due": 3}) == 1)
    gs = WF.W.groups(WF.facts(col, [1, 2, 3]), ctx)
    check("glue: the leech, the new card past what's left, the one in today's",
          [g["group"] for g in gs] == ["new:1", "study:1", "suspended"] and gs[2]["say"] == "Suspended as a leech: forgotten 4 times.",
          [(g["group"], g["say"]) for g in gs])
    ran, shown = [], []
    saved = sys.modules.get("aqt.operations")

    class Op:
        def __init__(self, parent=None, op=None):
            self.op = op

        def success(self, f):
            self.f = f
            return self

        def run_in_background(self):
            ran.append(self.op(types.SimpleNamespace(sched=types.SimpleNamespace(
                unsuspend_cards=lambda ids: ("unsuspend", ids), unbury_cards=lambda ids: ("unbury", ids),
                set_due_date=lambda ids, d: ("due", ids, d), empty_filtered_deck=lambda d: ("empty", d),
                custom_study=lambda req: ("custom", req)))))
            self.f(None)
    sys.modules["aqt.operations"] = types.SimpleNamespace(CollectionOp=Op)
    sys.modules["anki.scheduler.base"] = types.SimpleNamespace(CustomStudyRequest=lambda **kw: kw)
    dlg = types.SimpleNamespace(show_groups=lambda gs: shown.append([g["group"] for g in gs]))
    saved_col = sys.modules["aqt"].mw.col
    sys.modules["aqt"].mw.col = col
    try:
        WF.fix({"fix": ("unsuspend",), "cids": [1]}, dlg, [1, 2])
        WF.fix({"fix": ("due_now",), "cids": [4]}, dlg, [4])
        WF.fix({"fix": ("more_new", 1, 6), "cids": [2]}, dlg, [2])
        WF.fix({"fix": ("more_rev", 1, 50), "cids": [4]}, dlg, [4])
        WF.fix({"fix": ("empty", 9), "cids": [4]}, dlg, [4])
        WF.fix({"fix": ("unbury",), "cids": [3]}, dlg, [3])
        check("glue: each fix is Anki's own (unsuspend, due today, more new or reviews today, empty, unbury), then a fresh read",
              ran == [("unsuspend", [1]), ("due", [4], "0"), ("custom", {"deck_id": 1, "new_limit_delta": 6}),
                      ("custom", {"deck_id": 1, "review_limit_delta": 50}), ("empty", 9), ("unbury", [3])] and len(shown) == 6, ran)
    finally:
        sys.modules["aqt"].mw.col = saved_col
        if saved is None:
            sys.modules.pop("aqt.operations", None)
        else:
            sys.modules["aqt.operations"] = saved
        sys.modules.pop("anki.scheduler.base", None)
    acts = []

    class Menu:
        def addSeparator(self):
            pass

        def addAction(self, label):
            acts.append(label)
            return types.SimpleNamespace(triggered=types.SimpleNamespace(connect=lambda f: None))
    saved_client = PF.client
    PF.client = lambda: types.SimpleNamespace(signed_in=False)
    try:
        PF.browser_menu(types.SimpleNamespace(), Menu())
    finally:
        PF.client = saved_client
    check("glue: Browse's right-click asks why, opens the picked cards and puts them on a day, signed out too (Anki help, not the account)",
          acts == ["Due Crew: why isn't it showing?", "Due Crew: open these…", "Due Crew: put on a day…"], acts)


def test_card_set_links_one_look_v380():
    """3.8.0 (Sam: "the linked card sets appear differently on plan vs
    today/upcoming... pick one style and stick with it"): a link that
    opens a set of cards (a.tp) is the board's green everywhere, with no
    per-screen look of its own; Today writes a group as Plans does."""
    rules = re.findall(r"#due-crew[^{}]*a\.tp[^{}]*\{[^}]*\}", board._css({}))
    check("card-set links: one rule sets their colour, the green; none grey or dotted",
          rules and all("dotted" not in r and "inherit;" not in r.split("color:")[1][:12] for r in rules if "color:" in r)
          and sum(1 for r in rules if "color:" in r) == 1 and "var(--dc-accent)" in [r for r in rules if "color:" in r][0], rules)


def test_share_pictures_v380():
    """3.8.0: Share › As a picture, made in Anki (sharecard, pure): the
    site's cards (cards.js) from my own reviews: my week's squares and
    numbers, my year's calendar and best day, all time's bar a year; the
    switches, starting from my Privacy switches; what each card draws."""
    from due_crew import sharecard as S
    measure = lambda s, px, w: len(s) * px * 0.55  # noqa: E731
    texts = lambda ops: [o[1] for o in ops if o[0] == "text"]  # noqa: E731
    today = "2026-10-14"  # a Wednesday
    days = {"2026-10-12": (100, 30 * 60000), "2026-10-13": (40, 5 * 60000), "2026-10-14": (60, 20 * 60000),
            "2026-10-09": (10, 60000), "2025-03-03": (5, 60000), "2025-03-04": (7, 60000), "2025-03-05": (300, 90 * 60000),
            "2024-12-31": (2, 60000)}
    wk = S.week(days, today, False, {"2026-10-12": 3, "2026-10-14": 9, "2026-10-09": 50}, 4, 2)
    check("week: Monday to Sunday, the days so far studied, today ringed, tomorrow on",
          [c["label"] for c in wk["days"]] == list("MTWTFSS") and [c["studied"] for c in wk["days"]][:3] == [True] * 3
          and wk["days"][2]["today"] and [c["future"] for c in wk["days"]] == [False] * 3 + [True] * 4
          and wk["studied"] == 3 and wk["elapsed"] == 3, wk["days"])
    check("week: the numbers this week only, new cards too (last Friday's aren't in it)",
          wk["reviews"] == 200 and wk["time"] == 55 * 60000 and wk["newCards"] == 12 and wk["range"] == "12 Oct – 18 Oct"
          and wk["streak"] == 4 and wk["crew"] == 2, wk)
    one = S.week(days, today, True, {"2026-10-14": 9}, 4, 1)
    check("today: today's numbers, its day in the eyebrow",
          one["reviews"] == 60 and one["newCards"] == 9 and one["range"] == "Wed 14 Oct" and one["studied"] == 1, one)
    on = {k: True for k in ("time", "reviews", "streak", "crew", "best", "cheers")}
    W, H, ops = S.draw("week", "story", wk, on, "light", measure)
    t = texts(ops)
    check("week card: a story, the logo, time studied the big number, the reviews, new cards and streak under it",
          (W, H) == (1080, 1350) and ops[0] == ("logo", 78, 78, 40) and "MY WEEK · 12 OCT – 18 OCT" in t and "55m" in t
          and "200" in t and "12" in t and "🔥 4" in t and "with 2 crew this week" in t and "duecrew.com" in t
          and "studied, 3 of 3 days so far" in t, t)
    _w, _h, ops = S.draw("week", "story", wk, dict(on, time=False, streak=False, crew=False), "light", measure)
    t = texts(ops)
    check("week card: a switch off takes its number off the card",
          "55m" not in t and "200 reviews" in t and not any("🔥" in x for x in t) and not any(x.startswith("with ") for x in t), t)
    _w, _h, ops = S.draw("week", "story", wk, {}, "dark", measure)
    t = texts(ops)
    check("week card: every number off, the days studied are left", "3 days" in t and not any(x.isdigit() and x != "3" for x in t)
          and not any("reviews" in x or "new" in x for x in t), t)
    W, H, ops = S.draw("today", "link", one, on, "light", measure)
    t = texts(ops)
    check("today, a link: wide, the numbers on one line", (W, H) == (1200, 630) and "TODAY · WED 14 OCT" in t
          and "20m" in t and "60 reviews · 9 new · 🔥 4" in t and "with 1 crew today · duecrew.com" in t, t)
    big = S._Ops(measure, S.LOOKS["light"]).fit("123,456 reviews", 300, 150, 90, 700)
    check("a big number too wide shrinks, then ends in …", big[1] == 90 and big[0].endswith("…") and len(big[0]) < 15, big)

    yr = S.year(days, "2025", today, 7)
    first = S.year(days, "2024", today)
    check("year: the calendar year in Monday-first columns, days before my first review dashed",
          yr["cols"] == 53 and len(yr["cells"]) == 53 * 7 and yr["cells"][:2] == [{"out": True}] * 2
          and yr["cells"][2] == {"lvl": 0} and yr["since"] == "" and yr["studied"] == 3
          and first["cells"][0] == {"pre": True} and first["since"] == "31 Dec" and first["studied"] == 1,
          (yr["cells"][:3], first["cells"][:2], first["since"]))
    check("year: its streak, best day, reviews and cheers",
          yr["streak"] == 3 and yr["best"] == {"n": 300, "day": "5 Mar"} and yr["reviews"] == 312 and yr["cheers"] == 7, yr)
    now = S.year(days, "2026", today)
    check("year: this year's days to come are drawn faint; its first day isn't 'since'",
          now["cells"][-1] == {"out": True} and {"fut": True} in now["cells"] and now["since"] == "" and now["cheers"] is None)
    _w, _h, ops = S.draw("year", "link", yr, on, "light", measure)
    t = texts(ops)
    check("year card: story only, its eyebrow, days, the four numbers, my crew's cheers",
          (_w, _h) == (1080, 1350) and "MY YEAR IN ANKI · 2025" in t and "3 days" in t and "studied in 2025" in t
          and "312" in t and "2h" in t and "300" in t and "biggest day · 5 Mar" in t and "🎉 Cheered on 7 times by my crew" in t, t)
    al = S.alltime(days, today, 12)
    check("all time: a bar a year, the longest streak and its year, the best year",
          [r["days"] for r in al["years"]] == [1, 3, 4] and al["since"] == "Dec 2024" and al["streak"] == 3
          and al["streakYear"] == 2025 and al["bestYear"]["year"] == 2026 and al["days"] == 8 and al["cheers"] == 12, al)
    _w, _h, ops = S.draw("alltime", "story", al, dict(on, best=False), "dark", measure)
    t = texts(ops)
    check("all-time card: reviews big, a bar a year labelled, best year off",
          "524" in t and "’24" in t and "’26" in t and "longest streak · 2025" in t and not any("best year" in x for x in t), t)
    check("all time: nothing before my first review", S.alltime({}, today) is None)
    check("picker: the years I studied in and this one, newest first, then All time",
          S.year_options(days, today) == [("2026", "2026"), ("2025", "2025"), ("2024", "2024"), ("all", "All time")]
          and S.year_options({}, today) == [("2026", "2026"), ("all", "All time")])

    sw = {k: (note, start, en) for k, _l, note, start, en in S.switches("week", wk, S.privacy({"share_time": False}))}
    check("switches: a number my Privacy keeps home starts off, and says so; I can still turn it on",
          sw["time"] == ("off in Privacy", False, True) and sw["reviews"] == ("", True, True) and sw["crew"][1:] == (True, True), sw)
    sw = {k: (note, start, en) for k, _l, note, start, en in S.switches("today", dict(one, streak=0, crew=0), S.privacy({"show_up": True}))}
    check("switches: Just show up starts every number off; no streak or crew can't be on",
          not sw["time"][1] and not sw["reviews"][1] and sw["streak"] == ("none yet", False, False)
          and sw["crew"] == ("none yet today", False, False), sw)
    sw = {k: (note, start, en) for k, _l, note, start, en in S.switches("year", dict(yr, cheers=None), {}, "counting…")}
    check("switches: cheers wait for their count, then none yet or on",
          sw["cheers"] == ("counting…", False, False)
          and {k: v for k, _l, v, _s, _e in S.switches("year", dict(yr, cheers=0))}["cheers"] == "none yet"
          and [x for x in S.switches("year", yr) if x[0] == "cheers"][0][3:] == (True, True), sw)
    check("switches: all time over one year has no best year",
          [x for x in S.switches("alltime", dict(al, bestYear=None)) if x[0] == "best"][0][2:] == ("one year so far", False, False))


def test_share_pictures_glue_v380():
    """3.8.0: Share › As a picture opens the card made in Anki, not the
    website: my week from my reviews and my crew's days; my year with
    my crew's cheers counted with one request, after it opens."""
    from due_crew import shares as SH
    from due_crew.app import _state
    text = srcs.glue_src()
    check("menu: every picture is made here, none opens the site",
          "/home?card=" not in text and all(f'share_picture("{k}")' in text
                                            for k in ("picturetoday", "pictureweek", "pictureyear", "picturealltime")))
    store = world({"sam": "Sam", "dre": "Dre"}, {"sam": ["dre"], "dre": ["sam"]})
    cl = new_client(store, "sam")
    d0 = datetime.date.today()
    col = make_user_col([d0 - datetime.timedelta(days=k) for k in (0, 1, 400)], today=d0)
    made, bg = [], []

    class Dlg:
        def __init__(self, parent, choose, options=None, value=None, priv=None, tooltip=None, cheers_say=""):
            self.choose, self.options, self.value, self.priv, self.cheers_say = choose, options, value, priv, cheers_say
            self.refreshed = 0
            made.append(self)

        def refresh(self):
            self.refreshed += 1

        def show(self):
            self.shown = True
    saved = (SH.client, SH._bg, SH.cfg, SH._profile_files, sys.modules["aqt"].mw.col, _state.get("entries"), _state.get("labels"))
    files = tempfile.mkdtemp()
    sys.modules["due_crew.ui.share_card_dialog"] = types.SimpleNamespace(ShareCardDialog=Dlg)
    try:
        SH.client, SH._bg, SH.cfg, SH._profile_files = (lambda: cl), (lambda job, done: bg.append((job, done))), \
            (lambda: {"share_reviews": False}), (lambda: files)
        sys.modules["aqt"].mw.col = col
        q = StatsQueries(col)
        labels = [q.day_label(i) for i in range(7)]
        _state["labels"] = labels
        _state["entries"] = [{"you": True, "days": {}}, {"you": False, "days": {labels[0]: {"studied": True}}},
                             {"you": False, "days": {labels[0]: {"studied": False}}}]
        _state.pop("pic_log", None)
        SH.picture("picturetoday")
        dlg = made[-1]
        card = dlg.choose(None)
        check("my day: today's card, my reviews, one of my crew studied too, Reviews starting off as Privacy keeps it",
              card["kind"] == "today" and card["data"]["reviews"] == 3 and card["data"]["crew"] == 1
              and dlg.priv == {"time": True, "reviews": False, "streak": True} and dlg.shown and not bg
              and _state["share_card"] is dlg, (card["data"], dlg.priv))
        SH.picture("pictureyear")
        dlg = made[-1]
        check("my year: this year first, the years I studied in, All time; cheers being counted",
              dlg.value == labels[0][:4] and dlg.options[-1] == ("all", "All time") and len(dlg.options) >= 2
              and dlg.cheers_say == "counting…" and dlg.choose(dlg.value)["data"]["cheers"] is None and len(bg) == 1)
        check("my year: the whole log was read once, the year before last's day in it",
              (d0 - datetime.timedelta(days=400)).isoformat() in _state["pic_log"]["days"])
        dre = new_client(store, "dre")
        dre.send_cheer("sam", "🎉")
        job, done = bg[-1]
        got = job()
        check("cheers: one read, mine by year", got == {str(datetime.date.today().year): 1}
              and store.requests("GET", "/log") and len(store.requests("GET", "/log")) == 1, got)
        done(got)
        check("cheers: in the card once counted, the sheet redrawn",
              dlg.refreshed == 1 and dlg.choose(str(datetime.date.today().year))["data"]["cheers"] == 1
              and dlg.choose("all")["data"]["cheers"] == 1)
        SH.picture("picturealltime")
        dlg2 = made[-1]
        bg[-1][1](None)
        check("all time: opens on All time; a count that failed says so", dlg2.value == "all"
              and dlg2.cheers_say == "couldn't count" and dlg2.choose("all")["data"]["cheers"] is None)
        app_gen = SH.app.generation
        SH.picture("pictureyear")
        SH.app.generation += 1
        bg[-1][1]({"2026": 5})
        check("cheers: a profile closed while counting draws nothing", made[-1].refreshed == 0)
        SH.app.generation = app_gen
        signed_out = types.SimpleNamespace(signed_in=False)
        SH.client = lambda: signed_out
        n = len(bg)
        SH.picture("pictureyear")
        check("signed out: no request, the switch says why", len(bg) == n and made[-1].cheers_say == "sign in to count")
    finally:
        (SH.client, SH._bg, SH.cfg, SH._profile_files, sys.modules["aqt"].mw.col, _state["entries"], _state["labels"]) = saved
        sys.modules.pop("due_crew.ui.share_card_dialog", None)
        _state.pop("share_card", None)
        _state.pop("pic_log", None)


def test_map_card_v380():
    """3.8.0: "What I know" as a picture card and as text (mapcard, pure):
    tiles laid out to fill the card, the board's shades, the foot; the
    text's squares; last week's map kept once a week, for the change."""
    from due_crew import mapcard as M
    rects = M.squarify([50, 30, 20], 0, 0, 100, 100)
    check("card: the tiles fill the space, sized by cards", abs(sum(w * h for _x, _y, w, h in rects) - 10000) < 1e-6
          and abs(rects[0][2] * rects[0][3] - 5000) < 1e-6 and all(0 <= x and 0 <= y and x + w <= 100.0001 and y + h <= 100.0001
                                                                   for x, y, w, h in rects), rects)
    tiles = [{"key": "cardio", "name": "Cardio", "n": 412, "know": 86, "started": 400},
             {"key": "renal", "name": "Renal", "n": 318, "know": 77, "started": 300},
             {"key": "neuro", "name": "Neuro", "n": 190, "know": 66, "started": 190},
             {"key": "msk", "name": "MSK", "n": 64, "know": 94, "started": 64},
             {"key": "heme", "name": "Heme", "n": 120, "know": None, "started": 0}]
    c = M.card("Big Step 1", "2026-10-12", tiles)
    check("card: the eyebrow, the deck, biggest first, shades as the board's, nothing started has no number",
          c["eyebrow"] == "WHAT I KNOW · 12 OCT" and c["title"] == "Big Step 1"
          and [(t["name"], t["k"], t["shade"]) for t in c["tiles"]] == [("Cardio", 86, 2), ("Renal", 77, 1), ("Neuro", 66, 0),
                                                                         ("Heme", None, None), ("MSK", 94, 3)], c["tiles"])
    check("card: inside the card, room left at the foot", all(M.PAD - 1 <= t["x"] and t["x"] + t["w"] <= M.SIZE - M.PAD + 1
                                                             and M.TOP - 1 <= t["y"] and t["y"] + t["h"] <= M.SIZE - M.FOOT + 1
                                                             for t in c["tiles"]), c["tiles"])
    check("card: the foot, over the started cards", c["foot"] == "80% I’d remember now · 1,104 cards", c["foot"])
    check("card: without FSRS it says so", "right in their reviews these 4 weeks" in M.card("D", "2026-10-12", tiles, by="right")["foot"])
    shape = M.card("Big Step 1", "2026-10-12", tiles, pct=False)
    check("card: Percentages off, no numbers anywhere, the shades in words", shape["foot"] == "" and shape["key"] is True)
    prev = {"cardio": 82, "renal": 79, "gone": 50}
    ch = M.card("Big Step 1", "2026-10-12", tiles, prev=prev, since="2026-10-05")
    check("card: this week's change on the tiles that were there, and at the foot",
          [(t["name"], t["d"]) for t in ch["tiles"]][:3] == [("Cardio", 4), ("Renal", -2), ("Neuro", None)]
          and ch["foot"] == "80% now · up 1 since 5 Oct", ch["foot"])
    tx = M.text("Big Step 1", "2026-10-12", tiles)
    check("card as text: a square and a line a subject, the foot, the add-on",
          tx.splitlines()[:6] == ["What I know · Big Step 1 · 12 Oct", "🟩 Cardio 86%", "🟨 Renal 77%", "🟧 Neuro 66%",
                                  "⬜ Heme new", "🟩 MSK 94%"] and "80% I’d remember now · 1,104 cards" in tx
          and tx.endswith("Anki add-on 2035408484"), tx)
    check("card as text: no numbers when they're off; the change when it's on",
          "🟩 Cardio\n" in M.text("D", "2026-10-12", tiles, pct=False) and "%" not in M.text("D", "2026-10-12", tiles, pct=False)
          and "🟩 Cardio 86% ↑4" in M.text("D", "2026-10-12", tiles, prev=prev, since="2026-10-05"))
    s1 = M.keep([], "2026-10-01", tiles)
    check("week: the first map kept", [x["day"] for x in s1] == ["2026-10-01"] and s1[0]["k"]["cardio"] == 86 and "heme" not in s1[0]["k"])
    check("week: not again inside the week", M.keep(s1, "2026-10-06", tiles) == s1)
    s2 = M.keep(s1, "2026-10-08", tiles)
    s3 = M.keep(M.keep(s2, "2026-10-15", tiles), "2026-10-22", tiles)
    check("week: a week on, another; three kept", [x["day"] for x in s2] == ["2026-10-01", "2026-10-08"]
          and [x["day"] for x in s3] == ["2026-10-08", "2026-10-15", "2026-10-22"], s3)
    w1 = M.keep_ways({}, "sys", "2026-10-01", tiles)
    w2 = M.keep_ways(M.keep_ways(w1, "yield", "2026-10-03", tiles), "sys", "2026-10-03", tiles)
    check("week: by way, so switching ways never pushes out a week", w2["sys"] == w1["sys"] and list(w2) == ["sys", "yield"], w2)
    many = {f"w{i}": [{"day": f"2026-09-0{i}", "k": {"a": 1}}] for i in range(1, 6)}
    check("week: four ways at most, the longest unseen go", sorted(M.keep_ways(many, "w1", "2026-10-03", tiles)) == ["w1", "w3", "w4", "w5"])
    check("week: the map a week ago or more, for the change", M.week_ago(s2, "2026-10-12") == (s2[0]["k"], "2026-10-01")
          and M.week_ago(s2, "2026-10-15")[1] == "2026-10-08" and M.week_ago(s2, "2026-10-05") == (None, "")
          and M.week_ago(None, "2026-10-15") == (None, ""))


def test_learning_back_flip_v380():
    """3.8.0: the box flips "4 back at 9:42" to due when they come back:
    one timer, the earliest, a redraw on the Decks screen; none after the
    profile closed."""
    import time as _t
    from due_crew import due_flow as F, app as A
    from due_crew.app import _state
    import aqt.qt as Q
    timers, swaps = [], []
    saved = (Q.QTimer, F._swap, F.mw.state, _state.get("back_timer"))
    Q.QTimer = type("QTimer", (), {"singleShot": staticmethod(lambda ms, fn: timers.append((ms, fn)))})
    F._swap = lambda c: swaps.append(1)
    try:
        _state["back_timer"] = None
        now = int(_t.time())
        F._flip_at(now + 600)
        F._flip_at(now + 900)
        check("flip: one timer, at the first card's time", len(timers) == 1 and 600000 <= timers[0][0] <= 604000, timers)
        F._flip_at(now + 300)
        check("flip: an earlier card moves it up", len(timers) == 2)
        _state["due_reviews"] = (now, {"due": 0})
        F.mw.state = "deckBrowser"
        timers[0][1]()
        check("flip: the old timer does nothing", swaps == [] and _state["due_reviews"] is not None)
        timers[1][1]()
        check("flip: the box counts again and redraws", swaps == [1] and _state["due_reviews"] is None and _state["back_timer"] is None)
        F._flip_at(now + 60)
        A.generation += 1
        timers[-1][1]()
        check("flip: not after the profile changed", swaps == [1])
    finally:
        Q.QTimer, F._swap, F.mw.state, _state["back_timer"] = saved


def test_heatmap_day_v380():
    """3.8.0: on my own card, a day I studied opens its cards in Browse;
    a friend's card has no clicks."""
    import due_crew as dc
    from due_crew import plan_flow as F
    from due_crew.app import _state
    from aqt.deckbrowser import DeckBrowser
    prof = {"name": "Sam", "you": True, "cells": [0, 3, 12], "start": "2026-09-28", "streak": 2, "last_active": ""}
    js = board.profile_overlay_js(prof)
    check("heat: my studied days open Browse; a day with none doesn't", "duecrew:heatday:2026-09-29" in js
          and "duecrew:heatday:2026-09-30" in js and "duecrew:heatday:2026-09-28" not in js and "12 reviews" in js)
    check("heat: a friend's card has no clicks", "heatday" not in board.profile_overlay_js(dict(prof, you=False)))
    conn = sqlite3.connect(":memory:")
    fakes.make_collection(conn)
    cut = fakes.day_cutoff_for(TODAY)
    for i, ago in enumerate((0, 1, 1, 2)):
        fakes.add_card(conn, 900 + i, did=10)
        fakes.add_review(conn, (cut - ago * 86400 - 3600) * 1000, ease=3, cid=900 + i)
    shown = []
    saved = (F._browse, dc.mw.col, _state.get("labels"))
    try:
        F._browse = lambda cids, q=None, empty="": shown.append(sorted(cids) if cids else empty)
        dc.mw.col = fakes.FakeCol(conn, cut)
        _state["labels"] = [TODAY.isoformat()]
        y = (TODAY - datetime.timedelta(days=1)).isoformat()
        dc._on_js(False, as_board("duecrew:heatday:" + y), DeckBrowser())
        check("heat: that Anki day's answered cards, in Browse", shown == [[901, 902]], shown)
        dc._on_js(False, as_board("duecrew:heatday:nope"), DeckBrowser())
        dc._on_js(False, as_board("duecrew:heatday:" + (TODAY + datetime.timedelta(days=3)).isoformat()), DeckBrowser())
        check("heat: not a day, or a day ahead: nothing", shown == [[901, 902]])
    finally:
        F._browse, dc.mw.col, _state["labels"] = saved


def test_fifteen_model_v381():
    """3.8.1, the Fifteen: fifteen minutes, then a question for five; each
    yes adds one (after a five-minute break, or now), up to eight; no
    answer and it's over. Mine alone: never a room on my week doc."""
    from due_crew import room_model as rm
    utc = datetime.timezone.utc
    t0 = datetime.datetime(2026, 10, 13, 18, 0, tzinfo=utc)
    at = lambda m: t0 + datetime.timedelta(minutes=m)
    f = rm.make_fifteen("me", t0)
    check("fifteen: one fifteen of 15 with a 5-min break, kind kept by clean_room",
          f == {"host": "me", "start": "2026-10-13T18:00:00Z", "rounds": 1, "round": 15, "brk": 5, "kind": "fifteen"}
          and rm.clean_room(dict(f)) == f and rm.is_fifteen(f) and not rm.is_fifteen(rm.make_room("x", t0)))
    check("fifteen: a friend's doc can't make a room a fifteen with junk",
          "kind" not in rm.clean_room(dict(f, kind="party")))
    got = [(m, rm.phase(f, at(m))["state"]) for m in (0, 14.9, 15, 19.9, 20)]
    check("fifteen: the question for five minutes after the fifteen, then done",
          got == [(0, "round"), (14.9, "round"), (15, "ask"), (19.9, "ask"), (20, "done")], got)
    five = rm.fifteen_next(f, at(16))
    check("take five: one more after a five-minute break from the fifteen's end; the start holds",
          five["rounds"] == 2 and five["start"] == f["start"] and rm.phase(five, at(16))["state"] == "break"
          and rm.phase(five, at(20))["state"] == "round" and rm.phase(five, at(35))["state"] == "ask")
    now = rm.fifteen_next(f, at(16), wait=False)
    p = rm.phase(now, at(16))
    check("another now: the next fifteen starts this minute, all fifteen of it",
          now["rounds"] == 2 and p["state"] == "round" and p["round"] == 2 and p["left"] == 900)
    early = rm.fifteen_next(five, at(17), wait=False)
    check("Start now on the break: the same, the round it was waiting for",
          early["rounds"] == 2 and rm.phase(early, at(17))["state"] == "round" and rm.phase(early, at(17))["left"] == 900)
    check("nothing to answer in a fifteen, or a room's break",
          rm.fifteen_next(f, at(5)) is None and rm.fifteen_next(rm.make_room("x", t0, 4, 25, 5), at(27)) is None)
    eight = dict(f, rounds=8)
    check("eight is the most: no ninth", rm.fifteen_next(eight, at(8 * 15 + 7 * 5 + 1)) is None
          and rm.phase(eight, at(8 * 15 + 7 * 5 + 1))["state"] == "ask")
    check("what's spent: fifteens begun and their minutes",
          rm.fifteen_spent(f, at(7.5)) == (1, 7) and rm.fifteen_spent(f, at(16)) == (1, 15)
          and rm.fifteen_spent(now, at(23)) == (2, 22) and rm.fifteen_spent(f, at(0.2)) == (0, 0))
    check("studying now lasts to the end of the question", rm.live_until(five) == at(40))
    check("usual start: the middle of the last days' first answers; none from under three days",
          rm.usual_start([3600 * 18, 3600 * 19, 3600 * 20]) == 3600 * 19 and rm.usual_start([10, 20]) is None
          and rm.usual_start([100, 300, 200, 400]) == 250)
    v = rm.board_view(now, [], now=at(16))["mine"]
    check("on the Decks screen: the fifteen, its ring, minutes left",
          v["fifteen"] and v["state"] == "round" and v["title"] == "Fifteen 2" and v["label"] == "15")
    q = rm.board_view(f, [], now=at(16))["mine"]
    check("…and its question there too", q["state"] == "ask" and q["label"] == "✓" and "another fifteen?" in q["sub"])
    check("a capped one says so", "two hours" in rm.board_view(eight, [], now=at(8 * 15 + 7 * 5 + 1))["mine"]["sub"])

    # the week doc: a fifteen isn't a room to join; it's studying now
    from due_crew.backend import shapes as S
    live = datetime.datetime.now(utc)  # both under way: a row's room is one not over yet, by the clock
    check("fifteen: never on a row as a room", S._live_room(rm.make_fifteen("me", live)) is None
          and S._live_room(rm.make_room("x", live)) is not None)
    cl = api.ApiClient(os.path.join(tempfile.mkdtemp(), "session.json"))
    cl.session = {"room": rm.make_fifteen("me", datetime.datetime.now(utc)), "live_until": "2099-01-01T00:00:00Z"}
    doc = cl.week_doc([TODAY.isoformat()], {})
    check("fifteen: my week doc has studying now and no room", "room" not in doc and doc.get("liveUntil"), doc)
    cl.session["room"] = rm.make_room("me", datetime.datetime.now(utc), 2, 25, 5)
    check("…a room with my crew still rides it", "room" in cl.week_doc([TODAY.isoformat()], {}))


def test_fifteen_js_phase_matches_v381():
    """The widgets' clock is room_model.phase restated (a twin): a fifteen's
    question and its end, on both sides. Needs node; skipped without it."""
    import shutil
    import subprocess
    from due_crew import room_model as rm
    node = shutil.which("node")
    if not node:
        print("SKIP fifteen phase parity: no node")
        return
    src = rm._RUNTIME
    fn = src[src.index("  function phase(now) {"):src.index("  function hm(ms)")]
    t0 = datetime.datetime(2026, 10, 13, 18, 0, tzinfo=datetime.timezone.utc)
    cases, datas = [], []
    for i, room in enumerate((rm.make_fifteen("me", t0), dict(rm.make_fifteen("me", t0), rounds=3), rm.make_room("x", t0, 2, 25, 5))):
        d = rm.widget_data(room, [], ("#000", "#fff"), sev=False)
        datas.append({k: d[k] for k in ("start", "rounds", "round", "brk", "kind", "ask")})
        for m in range(-3, 140, 1):
            when = t0 + datetime.timedelta(minutes=m, seconds=7)
            p = rm.phase(room, when)
            cases.append([i, int(when.timestamp() * 1000), p["state"], p["round"], round(p["left"])])
    prog = ("var D;" + fn + f"var datas = {json.dumps(datas)}, cases = {json.dumps(cases)}, bad = 0;"
            "cases.forEach(function (c) { D = datas[c[0]]; var p = phase(c[1]);"
            " if (p.state !== c[2] || p.round !== c[3] || Math.round(p.left / 1000) !== c[4]) { bad++; } });"
            "console.log(bad + '/' + cases.length);")
    out = subprocess.run([node], input=prog, capture_output=True, text=True, timeout=60)
    check("fifteen: the widgets' clock is the model's, question and all", out.stdout.strip() == f"0/{len(cases)}", out.stdout + out.stderr)


def test_fifteen_widgets_v381():
    """▶ Fifteen? in the top bar; the question and its break on the review
    screen, keyed (a card's own script can't answer it); Pip in them."""
    from due_crew import room_model as rm
    t0 = datetime.datetime.now(datetime.timezone.utc)
    start = rm.widget_js("start", rm.start_data(("#2e7d32", "#7cc47f"), "left", True, nap=True))
    check("Fifteen? (with its question mark) at the chip's end, napping Pip, starts one",
          "'Fifteen?'" in start and "position:fixed;left:10px" in start and "send('room15')" in start
          and "m-nap" in start and "dc-sev-css" in start)
    plain = rm.widget_js("start", rm.start_data(("#2e7d32", "#7cc47f"), "right", False))
    check("…and with Pip off, no Pip", "sv m-" not in plain and '"sev": null' in plain)
    f = rm.make_fifteen("me", t0)
    ask = rm.widget_js("ask", rm.widget_data(f, [], ("#2e7d32", "#7cc47f"), cards=38, total=61))
    check("the question: three answers, keyed, Pip with the clock",
          all(f"'{c}'" in ask for c in ("room15five", "room15now", "room15stop")) and "That’s fifteen." in ask
          and "m-ring" in ask and '"cards": 38' in ask and "No answer" not in ask)
    brk = rm.widget_js("break", rm.widget_data(dict(f, rounds=2), [], ("#2e7d32", "#7cc47f"), brk_pose="stretch"))
    check("a fifteen's break: Start now and Stop here, Pip stretching (Settings), no cheer for nobody",
          "'room15now'" in brk and "'room15stop'" in brk and '"brk_pose": "stretch"' in brk and "Cheer the room" in brk
          and "FIF ?" in brk)
    room = rm.widget_js("break", rm.widget_data(rm.make_room("dre", t0, 2, 25, 5), [], ("#2e7d32", "#7cc47f")))
    check("a room with my crew keeps its break as it was (no Pip yet)", '"sev": null' in room and '"kind": "room"' in room)
    check("the answers are the widget's own commands", {"room15five", "room15now", "room15stop"} <= set(rm.CARD_PAGE_CMDS))
    msg, ok = rm.trusted("duecrew:room15now", True)
    msg2, ok2 = rm.trusted(f"duecrew:room15now|{rm.CMD_KEY}", True)
    check("from the review page only with the key", not ok and ok2 and msg2 == "duecrew:room15now")


def test_fifteen_flow_v381():
    """Start, the question, its answers, the end: through _on_js, as the
    top bar, the board and the review screen send them."""
    import due_crew as dc
    from aqt.deckbrowser import DeckBrowser
    from due_crew import rooms as R, room_model as rm, app as appmod, due_flow, sev
    from due_crew.app import _state
    utc = datetime.timezone.utc
    t0 = datetime.datetime(2026, 10, 13, 18, 0, tzinfo=utc)
    clock = {"now": t0}
    cl = types.SimpleNamespace(signed_in=True, user_id="me", session={}, _save_session=lambda: None)
    syncs, swaps, evals, walked = [], [], [], []
    col = types.SimpleNamespace(db=types.SimpleNamespace(scalar=lambda *a: 7), sched=types.SimpleNamespace(day_cutoff=10 ** 10))
    saved = (R.client, R._now, R._eval, R._webs, appmod.sync, appmod.swap, due_flow.study_today, R.mw.state, R.mw.col,
             dict(_state), R.cfg)
    try:
        R.client = lambda: cl
        R._now = lambda: clock["now"]
        R._eval = lambda web, js: evals.append(js)
        R._webs = lambda: (None, None, None)
        R.cfg = lambda: {}
        appmod.sync = lambda **k: syncs.append(k)
        appmod.swap = lambda c, **k: swaps.append(1)
        due_flow.study_today = lambda: walked.append(1)
        R.mw.state, R.mw.col = "deckBrowser", col
        _state["entries"] = [{"user_id": "me", "you": True, "room": None, "live_until": ""}]
        _state["labels"] = ["2026-10-13"]
        dc._on_js(False, as_board("duecrew:room15"), DeckBrowser())
        room = cl.session.get("room")
        check("start: a fifteen of mine, my crew sees studying now (one light sync), Study today opens",
              rm.is_fifteen(room) and room["rounds"] == 1 and cl.session.get("live_until") == "2026-10-13T18:20:00Z"
              and syncs == [{"light": True, "fetch": False}] and walked == [1]
              and _state["entries"][0]["room"] is None and _state["entries"][0]["live_until"] == "2026-10-13T18:20:00Z")
        clock["now"] = t0 + datetime.timedelta(minutes=16)
        R.rm_real = rm.phase
        dc._on_js(False, as_board("duecrew:room15five"), DeckBrowser())
        check("take five: one more, studying now to the end of its question",
              cl.session["room"]["rounds"] == 2 and cl.session["live_until"] == "2026-10-13T18:40:00Z" and len(syncs) == 2)
        clock["now"] = t0 + datetime.timedelta(minutes=17)
        walked.clear()
        dc._on_js(False, as_board("duecrew:room15now"), DeckBrowser())
        check("Start now on its break: the second starts this minute; from Decks, Study today opens",
              rm.phase(cl.session["room"], clock["now"])["left"] == 900 and walked == [1])
        clock["now"] = t0 + datetime.timedelta(minutes=22)
        dc._on_js(False, as_board("duecrew:room15stop"), DeckBrowser())
        done = cl.session.get("fifteen_done")
        check("stop: the session's line (fifteens begun, minutes, cards), nothing left of it, crew told",
              "room" not in cl.session and "live_until" not in cl.session and done
              and (done["n"], done["minutes"], done["cards"], done["walked"]) == (2, 20, 7, False) and len(syncs) == 4,
              str((done, len(syncs), sorted(cl.session))))
        check("…Pip's move for it picked as it ended (one of the stack's), kept with the session as its last there",
              done.get("move") in sev.moves("stack") and cl.session.get("sev_last") == {"stack": done["move"]})
        view = R.board_view()
        check("…on the board, with Pip stacking (once)", view.get("fifteen_done", {}).get("n") == 2
              and "stk" in (view["fifteen_done"].get("sev") or "") and " rest" not in view["fifteen_done"]["sev"].split('"')[1])
        check("…and drawn again it rests", " rest" in R.board_view()["fifteen_done"]["sev"].split('"')[1])
        dc._on_js(False, as_board("duecrew:room15x"), DeckBrowser())
        check("× takes the line away", "fifteen_done" not in cl.session)
        # walked away: no answer, so it ends quietly, with no sync of its own
        clock["now"] = t0
        dc._on_js(False, as_board("duecrew:room15"), DeckBrowser())
        n = len(syncs)
        clock["now"] = t0 + datetime.timedelta(minutes=21)
        real_phase = rm.phase
        R.room_model.is_over = lambda r, now=None: rm.phase(r, clock["now"])["state"] == "done"
        try:
            gone = R.my_room()
        finally:
            R.room_model.is_over = lambda r, now=None: r is None or real_phase(r, now)["state"] == "done"
        d = cl.session.get("fifteen_done") or {}
        check("no answer: over, quietly (no request), and its line is there", gone is None and d.get("walked") is True
              and d.get("n") == 1 and len(syncs) == n and "live_until" not in cl.session, str((d, len(syncs), n, sorted(cl.session))))
    finally:
        (R.client, R._now, R._eval, R._webs, appmod.sync, appmod.swap, due_flow.study_today, R.mw.state, R.mw.col,
         st, R.cfg) = saved
        _state.clear()
        _state.update(st)
        R.room_model.is_over = rm.__dict__["is_over"]


def test_sev_by_the_logo_is_a_moment_v381():
    """Sam: Pip isn't always by the logo. It comes when something just
    happened, the first time the board draws it, and goes after a few
    seconds; a redraw meanwhile keeps its place; then the logo's alone."""
    from due_crew import rooms as R, sev
    from due_crew.app import _state
    saved = (R.cfg, dict(_state), R.time.time)
    clock = {"t": 1000.0}
    try:
        R.cfg = lambda: {}
        R.time.time = lambda: clock["t"]
        _state["labels"] = ["2026-10-13"]
        _state.pop("sev_shown", None)
        _state["sev_cheer"] = 0
        check("nothing happening: no Pip by the logo", R.board_sev({}, {"done": False}) is None)
        first = R.board_sev({}, {"done": True})
        clock["t"] += 2
        again = R.board_sev({}, {"done": True})
        clock["t"] += 4
        later = R.board_sev({}, {"done": True})
        mv = lambda h: re.search(r'class="sv m-([a-z]+)', h).group(1)  # noqa: E731
        check("the day done: a hop (one of its moves), kept through a redraw, gone after its few seconds, not back that day",
              first and mv(first["svg"]) in sev.moves("hop") and mv(again["svg"]) == mv(first["svg"])
              and first["ago"] == 0 and again["ago"] == 2 and later is None)
        _state["sev_cheer"] = clock["t"] - 1
        cheer = R.board_sev({}, {"done": True})
        check("a cheer is its own moment, the same day", cheer and mv(cheer["svg"]) in sev.moves("cheer"))
        _state["sev_cheer"] = 0
        seen = [mv(first["svg"])]
        import random as _random
        _random.seed(26)  # the picks are random: seeded, so twelve days always meet every move (it missed one ~1 run in 50)
        for d in range(14, 26):
            _state["labels"] = [f"2026-10-{d}"]
            clock["t"] += 100
            seen.append(mv(R.board_sev({}, {"done": True})["svg"]))
        check("Sam, variety: each day done a move from the mix, never the same twice in a row",
              all(a != b for a, b in zip(seen, seen[1:])) and set(seen) == set(sev.moves("hop")), seen)
        R.cfg = lambda: {"sev": False}
        _state.pop("sev_shown", None)
        check("Pip off: never", R.board_sev({}, {"done": True}) is None)
    finally:
        R.cfg, st, R.time.time = saved
        _state.clear()
        _state.update(st)


def test_top_bar_is_our_page_v381():
    """Sam: clicking ▶ Fifteen? did nothing. Anki tags the top bar's
    messages with a TopToolbar (Toolbar.draw's wrapper), and only Toolbar
    counted as ours: the top bar got a card page's rules, and room15 (not
    one of the widgets' own) was dropped. The chip's phase tick too."""
    import due_crew as dc
    from due_crew import rooms as R, room_model as rm
    saved_mod, saved_on = sys.modules.get("aqt.toolbar"), R.on_message
    tb = types.ModuleType("aqt.toolbar")
    tb.TopToolbar = type("TopToolbar", (), {"__init__": lambda self, toolbar=None: None})
    tb.Toolbar = type("Toolbar", (), {})
    sys.modules["aqt.toolbar"] = tb
    got = []
    R.on_message = lambda cmd, parts: (got.append(cmd), True)[1]
    try:
        check("the top bar (as Anki tags it) is one of our pages", dc._our_page(tb.TopToolbar()))
        dc._on_js(False, f"duecrew:room15|{rm.CMD_KEY}", tb.TopToolbar())  # as the chip sends it, keyed
        dc._on_js(False, "duecrew:roomtick", tb.TopToolbar())
        dc._on_js(False, "duecrew:room15", type("Previewer", (), {})())  # a card's page: still not
    finally:
        R.on_message = saved_on
        if saved_mod is None:
            sys.modules.pop("aqt.toolbar", None)
        else:
            sys.modules["aqt.toolbar"] = saved_mod
    check("▶ Fifteen? and the chip's tick reach the glue from the top bar; a card's page can't start one",
          got == ["room15", "roomtick"], got)


def test_crew_room_sevs_wear_their_accents_v381():
    """3.8.1 (Sam's pick): in a crew room each member is their Pip, in their
    own accent, and they started at different moments, so the blinks never
    line up: the room's card and the Decks screen's lobby. Pip off, or a
    fifteen: the initials, as before. The accent rides GET /board, a mutual
    friend's only, and only one of the add-on's own reaches a page."""
    from due_crew import room_model as rm, rooms as R, sev
    from due_crew.app import _state
    utc = datetime.timezone.utc
    store = world({"sam": "Sammy", "dre": "Dre <K>", "ana": "Ana", "nia": "Nia", "kai": "Kai"},
                  {"sam": ["dre", "ana", "nia"], "dre": ["sam"], "ana": ["sam"], "kai": ["sam"]})
    for uid, accent in (("sam", "amber"), ("dre", "blue"), ("ana", "teal"), ("nia", "rose"), ("kai", "purple")):
        new_client(store, uid).put_settings("2026-10-13T10:00:00Z", {"accent": accent})
    raw = {f["uid"]: f for f in store._board("sam", False)["friends"]}
    check("server: a mutual friend's accent comes with their week; someone I added who hasn't added me back: name and emoji only",
          raw["dre"].get("accent") == "blue" and raw["nia"] == {"uid": "nia", "name": "Nia", "emoji": "", "mutual": False}
          and "kai" not in raw)
    check("…and the other way: someone who added me, and I haven't added back, never gets mine",
          {f["uid"]: f for f in store._board("kai", False)["friends"]}["sam"] == {"uid": "sam", "name": "Sammy", "emoji": "", "mutual": False})
    real_board = store._board

    def junk_board(me, *a, **k):  # a server that sends junk for ana's (the Worker never would)
        out = real_board(me, *a, **k)
        for f in out["friends"]:
            if f["uid"] == "ana":
                f["accent"] = "red;}</style><b>x"
        return out
    store._board = junk_board
    labels = [(TODAY - datetime.timedelta(days=i)).isoformat() for i in range(7)]
    sam = new_client(store, "sam", "Sammy")
    n = len(store.log)
    entries = sam.fetch_board(labels)["entries"]
    acc = {e["user_id"]: e["accent"] for e in entries}
    check("client: the accent rides the refresh (still one request); junk is no accent; mine is this computer's, not the server's",
          len(store.log) - n == 1 and acc == {"sam": "", "dre": "blue", "ana": ""}, acc)
    check("client: only one of the add-on's accents is kept",
          [shapes.clean_accent(x) for x in ("rose", "Rose", " rose", "</style>", "red;x", ["rose"], {"a": 1}, None, 7, "__proto__")]
          == ["rose"] + [""] * 9)

    room = rm.make_room("dre", datetime.datetime.now(utc) - datetime.timedelta(minutes=5))
    ents = [dict(e, room=room) for e in entries]
    mine = board.accent_pair("amber")
    on = rm.widget_data(room, ents, mine)
    seats = {s["n"]: s for s in on["seats"]}
    check("card, Pip on: each member is their Pip in their accent (mine is mine; junk wears the default), host first",
          [s["n"] for s in on["seats"]] == ["Dre <K>", "Ana", "You"] and seats["Dre <K>"]["a"] == list(board.accent_pair("blue"))
          and seats["Ana"]["a"] == list(board.accent_pair("green")) and seats["You"]["a"] == list(mine)
          and on["sev"] == dict({"idle": sev.svg("idle")}, **{f"idle.{m}": sev.svg("idle", m) for m in sev.SEAT_MOVES[1:]})
          and "sv-blink" in on["sevcss"], on["seats"])
    check("…each started at its own moment: the blinks never line up (a delay in the blink, each different)",
          [(s["b"], s["d"]) for s in on["seats"]] == [sev.blink(i) for i in range(3)]
          and "sv-blink var(--sv-b, 4.6s) var(--sv-d, 0s)" in sev.CSS and sev.BLINK == 4.6)
    clocks = [sev.blink(i) for i in range(8)]
    check("…each on its own clock (3.9.0, Sam: in turn \"still looks kinda creepy\"): cycles of 3.4 to 6.4 s, no two alike, "
          "places in them apart; the same every time it's drawn",
          all(3.4 <= c <= 6.4 and -c <= d <= 0 for c, d in clocks) and len({c for c, _d in clocks}) == 8
          and all(abs(a[0] - b[0]) >= 0.3 for a, b in zip(clocks, clocks[1:])) and clocks == [sev.blink(i) for i in range(8)]
          and sev.blink_css(1) == f"--sv-b:{clocks[1][0]}s;--sv-d:{clocks[1][1]}s", clocks)
    js = rm.widget_js("card", on)
    check("…drawn from sev.py's markup (24 px seats, the faces' size), coloured by day or night, the name only a label set as text",
          "who.appendChild(people(c, 24));" in js and "Math.round(size / (D.slot || [0.6])[0]), f = seats(s, most)" in js
          and "n ? s.a[1] : s.a[0]" in js and "w.title = s.n;" in js
          and "v.setAttribute('aria-label', s.n)" in js and round(40 * sev.SLOT[0]) == 24)
    off = rm.widget_data(room, ents, mine, sev=False)
    fif = rm.widget_data(rm.make_fifteen("sam", datetime.datetime.now(utc)), ents, mine)
    check("card, Pip off: the initials as before; a fifteen has no members (and its own Pips)",
          off["seats"] == [] and off["sev"] is None and off["initials"] == ["D", "A", "S"]
          and fif["seats"] == [] and fif["initials"] == [] and "focus" in fif["sev"])

    now = datetime.datetime.now(utc)
    lobby = board.room_html(rm.board_view(room, ents, now=now, sev=True, accent_pair=mine))
    blue, amber = board.accent_pair("blue"), mine
    check("lobby, Pip on: each member is their Pip, in their accent by day and by night, blinking at its own moment",
          lobby.count('class="seat"') == 3 and "<i>D</i>" not in lobby and "sv-seats" in lobby
          and [lobby.count(f"sv m-{m}") for m in ("idle", "sread", "snod")] == [1, 1, 1]
          and all(f"--sv-b:{c:.2f}s;--sv-d:{d:.2f}s" in lobby for c, d in (sev.blink(i) for i in range(3)))
          and f'--sa-l:{blue[0]};--sa-d:{blue[1]};--sv-b:' in lobby and f'--sa-l:{amber[0]};--sa-d:{amber[1]};--sv-b:' in lobby)
    check("…the name only as its label, escaped",
          'title="Dre &lt;K&gt;"' in lobby and 'aria-label="Dre &lt;K&gt;"' in lobby and "Dre <K>" not in lobby
          and 'aria-label="You"' in lobby)
    plain = board.room_html(rm.board_view(room, ents, now=now))
    check("lobby, Pip off: the initials as before", "<i>D</i><i>A</i><i>S</i>" in plain and "sv-slot" not in plain)
    bad = board._seat_html({"n": '"><b>x', "a": ["red;}</style>", "#2e7d3"], "d": "soon", "b": "1;}</style>"})
    check("lobby: a seat's colours are colours, or the default's; nothing else reaches its style",
          f'--sa-l:{board.accent_pair(None)[0]};--sa-d:{board.accent_pair(None)[1]};--sv-b:4.60s;--sv-d:0.00s' in bad
          and "</style>" not in bad and "<b>" not in bad)
    cfg_sheet = lambda theme: board.render({"entries": [], "labels": labels, "tomorrow": "", "pending": []}, {"theme": theme}, 0)
    dark, light, auto = cfg_sheet("dark"), cfg_sheet("light"), cfg_sheet("auto")
    check("the board picks a seat's colour as it does its own: Settings › Theme, or Anki's night mode",
          "#due-crew .dc-room .seat { --sv-a: var(--sa-d); }" in dark and "#due-crew .dc-room .seat { --sv-a: var(--sa-l); }" in light
          and "--sa-d" not in light and "body.nightMode #due-crew .dc-room .seat" in auto
          and "@media (prefers-color-scheme: dark) { #due-crew .dc-room .seat { --sv-a: var(--sa-d); } }" in auto)

    # the glue: Settings › Pip decides, my accent is mine
    saved = (R.cfg, R.my_room, R._done, R._fifteen_done, dict(_state))
    try:
        R.my_room, R._done, R._fifteen_done = (lambda: room), (lambda: None), (lambda: None)
        _state.update(entries=ents, room_dismissed=set(), labels=labels)
        R.cfg = lambda: {"accent": "amber"}
        glue_on, data_on = R.board_view()["mine"], R._data(room)
        R.cfg = lambda: {"accent": "amber", "sev": False}
        glue_off, data_off = R.board_view()["mine"], R._data(room)
    finally:
        R.cfg, R.my_room, R._done, R._fifteen_done, st = saved
        _state.clear()
        _state.update(st)
    check("glue: Pip on, the lobby's and the card's seats, me in my accent; Pip off, none",
          [s["a"] for s in glue_on["seats"]] == [list(blue), list(board.accent_pair("green")), list(amber)]
          and data_on["seats"] == glue_on["seats"] and glue_off["seats"] == [] and data_off["seats"] == []
          and data_off["initials"] == ["D", "A", "S"])


def test_fifteen_board_v381():
    """The board: the lobby's question, the session's line, the nudge, Pip
    beside the logo, and the Settings that turn it all off."""
    from due_crew import room_model as rm, sev, settings_model as SM
    t0 = datetime.datetime(2026, 10, 13, 18, 0, tzinfo=datetime.timezone.utc)
    f = rm.make_fifteen("me", t0)
    ask = dict(rm.fifteen_view(f, t0 + datetime.timedelta(minutes=16)), cards=38, sev=sev.svg("ring"))
    h = board.room_html({"mine": ask})
    check("lobby, the question: cards, three answers, Pip with its clock",
          "38 cards." in h and all(f"duecrew:{c}" in h for c in ("room15five", "room15now", "room15stop")) and "m-ring" in h)
    cap = board.room_html({"mine": rm.fifteen_view(dict(f, rounds=8), t0 + datetime.timedelta(minutes=8 * 15 + 7 * 5 + 1))})
    check("…capped: Stop here only", "room15five" not in cap and "room15now" not in cap and "room15stop" in cap)
    rnd = board.room_html({"mine": rm.fifteen_view(f, t0 + datetime.timedelta(minutes=3))})
    check("…in a fifteen: Study and Stop here", "duecrew:duestudy" in rnd and "room15stop" in rnd and "12 min left" in rnd)
    line = board.room_html({"fifteen_done": {"n": 3, "minutes": 45, "cards": 1212, "walked": True, "sev": sev.svg("stack", stack=3)}})
    check("the session's line: fifteens, minutes, cards, the same however it ended",
          "3 fifteens &middot; 45 m &middot; 1,212 cards.</span>" in line and "counts" not in line and "room15x" in line)
    one = board.room_html({"fifteen_done": {"n": 1, "minutes": 11, "cards": 56, "sev": sev.svg("stack", stack=1)}})
    check("Sam: its box fits what Pip stacks (room for one square, or three), its words left, no fixed gap above",
          [sev.stack_reach(n, 44) for n in (1, 2, 3, 8)] == [(7, 3), (13, 3), (19, 3), (19, 3)]
          and 'style="padding:7px 0 3px"' in one and 'style="padding:19px 0 3px"' in line
          and "dc-sess" in one and "padding-top: 26px" not in board.SEV_CSS and ".dc-sess { text-align: left; }" in board.SEV_CSS)
    check("…and the sparks that twinkle as it lands are gone once it rests, or when nothing moves",
          all(f".sv.m-{m} .spark" in sev.CSS.split("@media")[0].split("{ opacity: 0; }")[0]
              for m in ("stack", "cheer", "hug", "giftspin", "wobble", "catch"))
          and ".sv.rest .spark" in sev.CSS)
    v = {"today": "2026-10-13", "name": "Due", "done_n": 0, "total_n": 2, "behind_n": 0, "folded": False, "tab": "today",
         "rows": [], "suggestions": [], "notes": [], "later": [], "later_n": 0, "nudge": True, "nudge_sev": sev.svg("peek")}
    try:
        nud = board._due_html(v)
    except Exception as ex:  # the view's other keys: from a real one
        nud = str(ex)
    check("the nudge: Not started yet today. Fifteen? Start, and Not today",
          "Not started yet today." in nud and "duecrew:room15" in nud and "duecrew:duex:fifteen" in nud and "m-peek" in nud, nud[:300])
    head = board._head("today", sev={"svg": sev.svg("hop"), "ago": 1.5})
    check("Pip beside the logo, never on it, for a moment (it goes; a redraw keeps its place)",
          'class="dc-sev once"' in head and head.index("dc-mark") < head.index("dc-sev") and "--ago:1.50s" in head
          and board._head("today") .count("dc-sev") == 0)
    check("by the logo only when something happens: a cheer, back from away, exam eve, the day done; else nothing",
          [sev.moment(cheered=True, back=True), sev.moment(back=True, exam_eve=True), sev.moment(exam_eve=True, day_done=True),
           sev.moment(day_done=True), sev.moment()] == ["cheer", "hello", "exam", "hop", None])
    check("Pip: every pose draws; the cheer blushes and nothing else does; a stack of one",
          all(sev.svg(k).startswith('<svg class="sv m-') for k in sev.POSES) and "sv-cheek" in sev.svg("cheer")
          and "sv-cheek" not in sev.svg("idle") and sev.svg("stack", stack=1).count('class="stk') == 1)
    check("Pip: still unless the computer allows motion; what happens once rests when drawn again",
          sev.CSS.index("@media (prefers-reduced-motion: no-preference)") < sev.CSS.index("@keyframes")
          and "animation" not in sev.CSS[:sev.CSS.index("@media")] and ' rest"' in sev.svg("hop", rest=True)
          and " rest" not in sev.svg("nap", rest=True))
    st = board.settings_html({"tab": "board"}, {})
    sy = board.settings_html({"tab": "study"}, {})
    check("Settings: Pip on Board; Fifteen? in the top bar and the break's Breathe or Stretch on Study",
          "set:sev:0" in st and "set:fifteen:0" in sy and "set:sev_break:stretch" in sy and "duecrew:set:fifteen" not in st)
    ix = board.settings_index({"tab": "board"}, {})
    hit = lambda word: {r["f"] for r in ix if word in r["k"].split()}
    check("Find a setting: timer or pomodoro finds Fifteen?, mascot finds Pip, stretch finds the break",
          "set:fifteen:" in hit("timer") and "set:fifteen:" in hit("pomodoro") and "set:sev:" in hit("mascot")
          and "set:sev_break:" in hit("stretch"), (hit("timer"), hit("mascot"), hit("stretch")))
    check("…and what a click there saves", SM.change(["set", "sev", "0"], {}) == {"sev": False}
          and SM.change(["set", "sev_break", "stretch"], {}) == {"sev_break": "stretch"}
          and SM.change(["set", "sev_break", "dance"], {}) is None and SM.change(["set", "fifteen", "0"], {}) == {"fifteen": False})
    off = board.render({"entries": [], "labels": ["2026-10-13"], "tomorrow": "", "pending": []}, {"sev": False}, 0)
    on = board.render({"entries": [], "labels": ["2026-10-13"], "tomorrow": "", "pending": []}, {}, 0,
                      sev={"svg": sev.svg("hop"), "ago": 0})
    check("Pip off: no motion sheet on the board; on, the sheet and Pip by the logo",
          "sv-blink" not in off and "dc-sev" not in off.split("</style>")[-1] and "sv-blink" in on and 'class="dc-sev once"' in on)


def test_week_card_sev_v381():
    """3.8.1, the week card (Sam's pick, "Pip hops across the week"): a
    dotted arc from each day studied to the next, a long one over days
    off, none over days to come, and Pip standing on the last day studied
    in the card's accent; no Pip with nothing studied or Pip off, and on
    today's card only on today. sev.still is the one drawing: cards.js
    keeps a copy, and lays the card out the same (that part needs node)."""
    import shutil
    import subprocess
    from due_crew import rooms as R, sev, shares as SH, sharecard as S
    from due_crew.app import _state
    measure = lambda s, px, w: len(s) * px * 0.55  # noqa: E731
    mon = datetime.date(2026, 10, 12)
    log = lambda days: {(mon + datetime.timedelta(days=i)).isoformat(): (30 + 7 * i, (10 + 3 * i) * 60000)  # noqa: E731
                        for i, x in enumerate(days) if x}
    on = {k: True for k in ("time", "reviews", "streak", "crew")}
    of = lambda ops, kind: [o for o in ops if o[0] == kind]  # noqa: E731
    P, s = 78, (1080 - 2 * 78 - 6 * 20) / 7
    mid = lambda i, x0=P, side=s, gap=20: x0 + i * (side + gap) + side / 2  # noqa: E731

    wk = S.week(log([1, 1, 0, 1, 1, 0, 1]), "2026-10-18", False, {"2026-10-18": 9}, 4, 2, sev=True)  # the mock's: two days off
    W, H, ops = S.draw("week", "story", wk, on, "light", measure)
    hp = S.hops(wk, P, 560 + S.ROOM, s, 20, 8)
    over = lambda a, b: [y - hp["r"] for x, y in hp["dots"] if mid(a) < x < mid(b)]  # noqa: E731
    check("hops: an arc from each day studied to the next, a long one over each day off",
          hp["arcs"] == [(0, 1), (1, 3), (3, 4), (4, 6)] and min(over(1, 3)) < min(over(0, 1)) and min(over(4, 6)) < min(over(3, 4))
          and all(min(over(a, b)) < 560 + S.ROOM for a, b in hp["arcs"]), hp["arcs"])
    sv = of(ops, "sev")
    check("Pip on the last day studied, standing on today's ring, in the card's accent; the trail drawn in it too",
          len(sv) == 1 and sv[0][1] == "hop" and abs(sv[0][2] + sv[0][4] / 2 - mid(6)) < 1e-9
          and abs(sv[0][3] + sv[0][4] * S.SEV_FEET - (560 + S.ROOM - 8 * 1.375)) < 1e-9 and sv[0][5] == "#2e7d32"
          and [o[1:3] for o in of(ops, "dot")] == hp["dots"] and {o[4] for o in of(ops, "dot")} == {"#2e7d32"}
          and of(S.draw("week", "story", wk, on, "dark", measure)[2], "sev")[0][5] == S.LOOKS["dark"]["g"], sv)
    texts = {o[1]: o[3] for o in of(ops, "text")}
    body_top = sv[0][3] + sv[0][4] * 27 / 80  # sev.py: the body's top
    check("room for it: the squares and the numbers under them move down; every word and number kept, nothing crowded",
          texts["S"] == 560 + S.ROOM + s + 54 and texts["day streak"] == 962 + S.ROOM and texts["duecrew.com"] == H - P
          and body_top - 462 >= 50 and min(y - hp["r"] for _x, y in hp["dots"]) - 462 >= 50
          and texts["day streak"] + 100 < H - P and [o[1] for o in of(ops, "text")]
          == [o[1] for o in of(S.draw("week", "story", dict(wk, sev=False), on, "light", measure)[2], "text")], (body_top, texts))
    six = S.week(log([1, 0, 0, 0, 0, 0, 1]), "2026-10-18", sev=True)
    tall = S.hops(six, P, 560 + S.ROOM, s, 20, 8)
    check("…the longest hop (Monday to Sunday) clears the words above it too",
          tall["arcs"] == [(0, 6)] and min(y - tall["r"] for _x, y in tall["dots"]) - 462 >= 50)
    wed = S.week(dict(log([1, 0, 1, 1, 1, 0, 0])), "2026-10-14", sev=True)
    hw = S.hops(wed, P, 560 + S.ROOM, s, 20, 8)
    check("nothing over the days to come: Pip on today, the last day so far",
          hw["arcs"] == [(0, 2)] and max(x for x, _y in hw["dots"]) < mid(2) and abs(hw["sev"][0] + hw["sev"][2] / 2 - mid(2)) < 1e-9)
    hg = S.hops(S.week(log([1, 1, 0, 0, 0, 0, 0]), "2026-10-14", sev=True), P, 660, s, 20, 8)
    check("today not studied yet: Pip on the last day that was, standing on its square (no ring there)",
          hg["arcs"] == [(0, 1)] and abs(hg["sev"][0] + hg["sev"][2] / 2 - mid(1)) < 1e-9
          and abs(hg["sev"][1] + hg["sev"][2] * S.SEV_FEET - 660) < 1e-9, hg["sev"])
    plain = S.draw("week", "story", S.week(log([1, 1, 0, 1, 1, 0, 1]), "2026-10-18"), on, "light", measure)
    none = S.week({}, "2026-10-14", sev=True)
    check("no Pip with nothing studied this week, or with Pip off: today's card as it was (squares at 560)",
          not S.landings(none) and not of(S.draw("week", "story", none, on, "light", measure)[2], "sev")
          and S.draw("week", "story", none, on, "light", measure) == S.draw("week", "story", dict(none, sev=False), on, "light", measure)
          and not of(plain[2], "sev") and not of(plain[2], "dot")
          and {o[1]: o[3] for o in of(plain[2], "text")}["S"] == 560 + s + 54)
    one = S.week(log([1, 1, 1, 0, 0, 0, 0]), "2026-10-14", True, sev=True)
    one_ops = S.draw("today", "story", one, on, "light", measure)[2]
    not_yet = S.week(log([1, 1, 0, 0, 0, 0, 0]), "2026-10-14", True, sev=True)
    check("today's card: Pip on today's square when today was studied, no arcs; not yet today, no Pip",
          S.landings(one) == [2] and len(of(one_ops, "sev")) == 1 and not of(one_ops, "dot")
          and abs(of(one_ops, "sev")[0][2] + of(one_ops, "sev")[0][4] / 2 - mid(2)) < 1e-9
          and not S.landings(not_yet) and not of(S.draw("today", "story", not_yet, on, "light", measure)[2], "sev"))
    lk = S.draw("week", "link", wk, on, "light", measure)[2]
    ls = (1200 - 64 - 720 - 6 * 12) / 7
    lsev = of(lk, "sev")[0]
    check("a link: Pip and its trail in the room above the squares, under the logo's row, the squares where they were",
          {o[1]: o[3] for o in of(lk, "text")}["M"] == 230 + ls + 38 and lsev[3] + lsev[4] * 27 / 80 > 64 + 34 + 20
          and min(o[2] - o[3] for o in of(lk, "dot")) > 64 + 34 + 20
          and min(o[1] for o in of(lk, "dot")) > 720 and abs(lsev[2] + lsev[4] / 2 - mid(6, 720, ls, 12)) < 1e-9)

    art = sev.still("hop", "#123456")
    check("sev.still: one drawing, standing still for a picture: its own svg, the colour given, no CSS, no classes, no effects",
          art.startswith('<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80" viewBox="0 0 80 80">')
          and "fill:#123456" in art and "var(" not in art and "class=" not in art
          and art.count("<rect") == sev.svg("hop").count("<rect") - 7 and "<ellipse" not in art  # no confetti, no shadow
          and "#1f2a1f" in art and sev.still("idle").count("#2e7d32") > 3)
    js = open(os.path.join(REPO, "site", "public", "cards.js"), encoding="utf-8").read()
    const = re.search(r"\n  const SEV = '([^']*)';\n", js)
    check("cards.js draws sev.py's Pip: its copy is sev.still('hop', '%A%') to the byte",
          const is not None and const.group(1) == sev.still("hop", "%A%"))
    app_js = open(os.path.join(REPO, "site", "public", "app.js"), encoding="utf-8").read()
    check("the site has no Pip switch: its week card always asks for Pip", "crew: withMe, sev: true }" in app_js)

    # in Anki the card follows Settings › Pip
    store = world({"sam": "Sam"})
    cl = new_client(store, "sam")
    d0 = datetime.date.today()
    col = make_user_col([d0], today=d0)
    made = []

    class Dlg:
        def __init__(self, parent, choose, **_kw):
            self.choose = choose
            made.append(self)

        def show(self):
            pass
    saved = (SH.client, SH.cfg, SH._profile_files, sys.modules["aqt"].mw.col, _state.get("entries"), _state.get("labels"), R.cfg)
    real_dlg = sys.modules.get("due_crew.ui.share_card_dialog")
    sys.modules["due_crew.ui.share_card_dialog"] = types.SimpleNamespace(ShareCardDialog=Dlg)
    files = tempfile.mkdtemp()
    try:
        SH.client, SH.cfg, SH._profile_files = (lambda: cl), (lambda: {}), (lambda: files)
        sys.modules["aqt"].mw.col = col
        q = StatsQueries(col)
        _state["labels"] = [q.day_label(i) for i in range(7)]
        _state["entries"] = [{"you": True, "days": {}}]
        _state.pop("pic_log", None)
        got = []
        for c in ({}, {"sev": False}):
            R.cfg = lambda c=c: c
            for kind in ("pictureweek", "picturetoday"):
                SH.picture(kind)
                got.append(made[-1].choose(None)["data"]["sev"])
        check("in Anki: the week and today cards have Pip as Settings › Pip says (on unless switched off)",
              got == [True, True, False, False], got)
    finally:
        (SH.client, SH.cfg, SH._profile_files, sys.modules["aqt"].mw.col, _state["entries"], _state["labels"], R.cfg) = saved
        if real_dlg is None:
            sys.modules.pop("due_crew.ui.share_card_dialog", None)
        else:
            sys.modules["due_crew.ui.share_card_dialog"] = real_dlg
        _state.pop("share_card", None)
        _state.pop("pic_log", None)

    node = shutil.which("node")
    if not node:
        print("SKIP week card Pip twin: no node")
        return
    expose = "return { open, short, SIZES, MONTHS };"
    check("cards.js: the card's twin is reachable for the check", expose in js)
    cases = [(S.week(log(p), t, one_, {t: 9}, 4, 2, sv_), one_) for p, t, one_, sv_ in (
        ([1, 1, 0, 1, 1, 0, 1], "2026-10-18", False, True), ([1, 0, 0, 0, 0, 0, 1], "2026-10-18", False, True),
        ([1, 0, 1, 1, 1, 0, 0], "2026-10-14", False, True), ([1, 1, 0, 0, 0, 0, 0], "2026-10-14", False, True),
        ([0] * 7, "2026-10-14", False, True), ([1, 1, 1, 0, 0, 0, 0], "2026-10-14", True, True),
        ([1, 1, 0, 0, 0, 0, 0], "2026-10-14", True, True), ([1, 1, 0, 1, 1, 0, 1], "2026-10-18", False, False))]
    draws = [[kind, size, look, d] for d, one_ in cases for kind in (["today"] if one_ else ["week"])
             for size in ("story", "link") for look in ("light", "dark")]
    grid = [[S.week(log([(m >> i) & 1 for i in range(7)]), t, one_, sev=True), x0, top, side, g, ring]
            for m in range(128) for t in ("2026-10-12", "2026-10-15", "2026-10-18") for one_ in (False, True)
            for x0, top, side, g, ring in ((P, 660, s, 20, 8), (720, 230, ls, 12, 4))]
    prog = (
        "globalThis.Image = class { set src(v) { this.s = v; Promise.resolve().then(() => this.onload()); } };\n"
        + js.replace(expose, "return { open, short, SIZES, MONTHS, DRAW, LOOKS, hops };") + "\n"
        "const fake = () => { const log = []; let font = '';\n"
        "  return { log, get font() { return font; }, set font(f) { font = f; },\n"
        "    measureText(s) { return { width: [...s].length * Number(/([0-9.]+)px/.exec(font)[1]) * 0.55 }; },\n"
        "    fillText(s, x, y) { log.push(['text', s, x, y]); }, fillRect(x, y, w, h) { log.push(['rule', x, y, w, h]); },\n"
        "    arc(x, y, r) { log.push(['dot', x, y, r, this.fillStyle]); },\n"
        "    drawImage(img, x, y, w, h) { log.push([img.s.startsWith('data:') ? 'sev' : 'logo', x, y, w, h, decodeURIComponent(img.s)]); },\n"
        "    beginPath() {}, moveTo() {}, arcTo() {}, closePath() {}, fill() {}, stroke() {}, setLineDash() {} }; };\n"
        "const { draws, grid, on } = JSON.parse(require('fs').readFileSync(0, 'utf8'));\n"
        "(async () => { const out = [];\n"
        "  for (const [kind, size, look, d] of draws) { const c = fake(); const [W, H] = Cards.SIZES[size];\n"
        "    await Cards.DRAW[kind](c, W, H, size, d, on, Cards.LOOKS[look], look); out.push(c.log); }\n"
        "  console.log(JSON.stringify({ draws: out, grid: grid.map((g) => Cards.hops(...g)) })); })();")
    run = subprocess.run([node, "-e", prog], input=json.dumps({"draws": draws, "grid": grid, "on": on}),  # too big for an argument
                         capture_output=True, text=True, timeout=60)
    try:
        got = json.loads(run.stdout)
    except ValueError:
        got = None
    check("cards.js runs the week card in node", got is not None, run.stdout[-500:] + run.stderr[-2000:])
    if got is None:
        return
    close = lambda a, b: len(a) == len(b) and all(abs(x - y) < 1e-6 for x, y in zip(a, b))  # noqa: E731
    bad = []
    for g, h in zip(grid, got["grid"]):
        mine = S.hops(*g)
        if ([list(a) for a in mine["arcs"]] != h["arcs"] or abs(mine["r"] - h["r"]) > 1e-9 or len(mine["dots"]) != len(h["dots"])
                or not all(close(a, b) for a, b in zip(mine["dots"], h["dots"]))
                or (mine["sev"] is None) != (h["sev"] is None) or (mine["sev"] and not close(mine["sev"], h["sev"]))):
            bad.append((g[0]["days"], g[1:], mine, h))
    check("cards.js hops() is sharecard.hops: the same arcs, dots and Pip on every week (all 128, three todays, both cards, both sizes)",
          not bad and len(got["grid"]) == len(grid) == 128 * 3 * 2 * 2, bad[:1])
    bad = []
    for (kind, size, look, d), log_ in zip(draws, got["draws"]):
        ops = S.draw(kind, size, d, on, look, measure)[2]
        want = {"text": [(o[1], o[2], o[3]) for o in of(ops, "text")],
                "rule": [o[1:5] for o in of(ops, "rect") if o[4] == 3],
                "dot": [(o[1], o[2], o[3], o[4]) for o in of(ops, "dot")],
                "sev": [(o[2], o[3], o[4], o[4], "data:image/svg+xml;charset=utf-8," + sev.still(o[1], o[5])) for o in of(ops, "sev")]}
        have = {k: [tuple(x[1:]) for x in log_ if x[0] == k] for k in want}
        ok = (len(want["text"]) == len(have["text"]) and all(a[0] == b[0] and close(a[1:], b[1:]) for a, b in zip(want["text"], have["text"]))
              and all(close(a, b) for a, b in zip(want["rule"], have["rule"])) and len(want["rule"]) == len(have["rule"])
              and len(want["dot"]) == len(have["dot"]) and all(close(a[:3], b[:3]) and a[3] == b[3] for a, b in zip(want["dot"], have["dot"]))
              and len(want["sev"]) == len(have["sev"]) and all(close(a[:4], b[:4]) and a[4] == b[4] for a, b in zip(want["sev"], have["sev"])))
        if not ok:
            bad.append((kind, size, look, [c["studied"] for c in d["days"]], want, have))
    check("cards.js lays the week and today cards out as sharecard does: words, rule, trail, and Pip (sev.still, in the accent)",
          not bad and len(got["draws"]) == len(draws) == 32, bad[:1])


def test_welcome_back_sev_v381():
    """Sam liked Welcome back with Pip: Pip waves from the window's corner
    (still: a Qt window can't play the board's motion), unless Settings ›
    Pip is off. tools/dialogs.py draws it and checks the pixel; here, the
    switch reaches the window, and the drawing is sev.py's still one."""
    from due_crew import plan_flow, rooms as R, sev, room_model as rm
    got = []
    fake = types.ModuleType("due_crew.ui.away_dialog")
    fake.ask_away = lambda parent, name, days, n_dates, n_cards, sev=False: (got.append(sev), "later")[1]
    saved = (sys.modules.get("due_crew.ui.away_dialog"), R.cfg)
    sys.modules["due_crew.ui.away_dialog"] = fake
    try:
        R.cfg = lambda: {}
        plan_flow._ask_away("Big Step 1", ["2026-10-05"], 1, 20)
        R.cfg = lambda: {"sev": False}
        plan_flow._ask_away("Big Step 1", ["2026-10-05"], 1, 20)
    finally:
        R.cfg = saved[1]
        if saved[0] is None:
            sys.modules.pop("due_crew.ui.away_dialog", None)
        else:
            sys.modules["due_crew.ui.away_dialog"] = saved[0]
    check("Welcome back: Pip on, the window waves; Settings › Pip off, it's as before", got == [True, False], got)
    art = sev.still("hello", "#6b3fb5")
    check("…its Pip is the still drawing, waving, in the accent", art.startswith('<svg xmlns="http://www.w3.org/2000/svg"')
          and "#6b3fb5" in art and "var(" not in art and "class=" not in art)
    ask = next(ln for ln in rm._RUNTIME.splitlines() if "squares(c, 110)" in ln and "qb." in ln)
    check("the fifteen's question with Pip off shows the logo's squares (the else was inside a comment)",
          "//" not in ask.split("squares(c, 110)")[0], ask.strip())


def test_sev_moves_v381():
    """Sam's picks (Pip's Places): every move in the mix at every place Pip
    already is, a different one each time (never the same twice in a row);
    where it stays a while, one small thing now and then. And two new
    places: the signed-out card, and a crewmate's big streak."""
    import random
    from due_crew import room_model as rm, rooms as R, sev
    from due_crew.app import _state
    still, motion = sev.CSS.split("@media", 1)
    mom = lambda h: re.search(r'class="sv m-([a-z]+)', h).group(1)  # noqa: E731
    rests = lambda h: " rest" in h.split('"')[1]  # noqa: E731
    check("Sam's picks, all in the mix, each place's own move first (the one it played before)",
          {k: sev.moves(k) for k in sev.MOVES} == {
              "hop": ("hop", "twirl", "shuffle", "jump"), "cheer": ("cheer", "hug", "giftspin"),
              "hello": ("in", "walkin", "popup"), "exam": ("exam", "pep"), "focus": ("focus", "nod", "think", "tap"),
              "stretch": ("stretch", "shake", "march", "look"), "ring": ("ring", "point", "bigring"),
              "stack": ("stack", "wobble", "catch"), "peek": ("peek", "knock", "bounce")}
          and all(sev.MOVES[k][0] == (k, sev.MOMENT[k]) for k in sev.MOVES)
          and sev.SEAT_MOVES == ("idle", "sread", "snod", "sreach", "slook"))
    every = {m for k in sev.MOVES for m in sev.moves(k)} | set(sev.SEAT_MOVES)
    check("every move moves, under Reduce motion's query", all(f".sv.m-{m} " in motion for m in every - {"idle"}),
          sorted(m for m in every - {"idle"} if f".sv.m-{m} " not in motion))
    props = set(re.findall(r"[{;]\s*([a-z-]+)\s*:", motion))
    check("transforms and opacity only (the drawing never changes, it moves)",
          props <= {"animation", "animation-delay", "animation-duration", "animation-direction", "transform", "transform-origin",
                    "opacity", "visibility"}, props)
    check("the ones that happen once rest when drawn again; the ones that stay a while loop",
          {"twirl", "shuffle", "jump", "hug", "giftspin", "walkin", "popup", "point", "bigring", "wobble", "catch", "knock",
           "bounce"} <= sev.ONCE and not ({"pep", "nod", "think", "tap", "shake", "march", "look"} | set(sev.SEAT_MOVES)) & sev.ONCE
          and all(rests(sev.move(k, m, rest=True)) for k in sev.MOVES for m in sev.moves(k) if m in sev.ONCE))
    check("still, each is the frame that says it: peeking low, the day done in the air (and at rest it's landed)",
          ".sv.m-peek .sv-body, .sv.m-knock .sv-body, .sv.m-bounce .sv-body { transform: translateY(10px); }" in still
          and ".sv.m-hop .sv-body, .sv.m-twirl .sv-body, .sv.m-shuffle .sv-body, .sv.m-jump .sv-body" in still
          and ".sv.rest.m-knock .sv-body, .sv.rest.m-bounce .sv-body { transform: translateY(10px); }" in motion
          and ".sv.rest .sv-footL, .sv.rest .sv-footR" in motion)
    after = sev.CSS.rsplit("\n}\n", 1)[1]
    check("drawn again it rests with Reduce motion on too: landed, what flew gone (a banner isn't left mid-hop)",
          ".sv.rest .cf, .sv.rest .spark, .sv.rest .sv-ring { opacity: 0; }" in after
          and ".sv.rest .sv-footL, .sv.rest .sv-footR { transform: none; }" in after and "animation" not in after
          and "translateY(10px)" in after)
    check("a body moves in the drawing's own units, never a share of its box, which what Pip has on makes taller "
          "(3.9.0, Sam: a pumpkin and an umbrella sank the peek)",
          not re.search(r"translateY\(-?[0-9.]+%\)", sev.CSS), re.findall(r"translateY\(-?[0-9.]+%\)", sev.CSS))

    rnd = random.Random(7)
    never = all(sev.pick(k, last, rnd) != last for k in sev.MOVES for last in sev.moves(k) for _ in range(20))
    seq, last = [], None
    for _ in range(40):
        last = sev.pick("hop", last, rnd)
        seq.append(last)
    check("pick: from the mix at random, never the one it played last", never and set(seq) == set(sev.moves("hop"))
          and all(a != b for a, b in zip(seq, seq[1:])))
    check("nth: in turn, one after another never the same",
          all(sev.nth(k, i) != sev.nth(k, i + 1) for k in sev.MOVES for i in range(-3, 9)))
    check("a place with one move keeps it (Breathe stays); a move that isn't the place's plays its own",
          sev.moves("breathe") == ("breathe",) and sev.pick("rest") == "breathe" and mom(sev.move("hop", "knock")) == "hop"
          and mom(sev.move("focus")) == "focus" and mom(sev.move("hello")) == "in")
    check("a move keeps its place's words (marching is the break's stretch)",
          'class="sv m-march"' in sev.move("stretch", "march") and 'aria-label="Pip, stretching"' in sev.move("stretch", "march"))

    # a fifteen's widgets: the moves take turns, a round each
    utc = datetime.timezone.utc
    t0 = datetime.datetime(2026, 10, 13, 18, 0, tzinfo=utc)
    f = dict(rm.make_fifteen("sam", t0), rounds=3)
    d = rm.widget_data(f, [], ("#2e7d32", "#7cc47f"), brk_pose="stretch")
    check("a fifteen's widgets get each move's markup and their turns, its own first",
          d["vary"] == {"focus": ["focus", "focus.nod", "focus.think", "focus.tap"], "ring": ["ring", "ring.point", "ring.bigring"],
                        "stretch": ["stretch", "stretch.shake", "stretch.march", "stretch.look"]}
          and all(k in d["sev"] for v in d["vary"].values() for k in v) and mom(d["sev"]["focus.tap"]) == "tap"
          and d["vseed"] == rm.vary_seed(f) and 0 <= d["vseed"] < 12, d["vary"])
    check("…heads down, the break's stretch and the clock each take theirs; Breathe stays itself",
          "return vk('focus', p.round);" in rm._RUNTIME and "D.brk_pose === 'stretch' ? vk('stretch', p.round) : 'rest'" in rm._RUNTIME
          and "return vk('ring', p.round);" in rm._RUNTIME and "sev(vk('stretch', phase(Date.now()).round), 170)" in rm._RUNTIME
          and "sev(vk('ring', D.rounds), 170)" in rm._RUNTIME and "sev('breathe', 180, true)" in rm._RUNTIME
          and "function vk(k, n)" in rm.widget_js("card", d))
    off = rm.widget_data(f, [], ("#2e7d32", "#7cc47f"), sev=False)
    check("Pip off: no moves either", off["sev"] is None and off["vary"] is None and off["vseed"] == 0)
    check("the board's line takes the widgets' turn (sev.nth, the same seed)",
          all(d["vary"][k][(r + d["vseed"]) % len(d["vary"][k])].split(".")[-1] == sev.nth(k, r + rm.vary_seed(f))
              for k in d["vary"] for r in range(1, 9)))
    saved = (R.cfg, R.my_room, R._done, R._fifteen_done, R._now, R.datetime, dict(_state))
    try:
        R.cfg = lambda: {"sev_break": "stretch"}
        R.my_room, R._done, R._fifteen_done = (lambda: f), (lambda: None), (lambda: None)
        _state.update(entries=[], room_dismissed=set(), labels=["2026-10-13"])
        got = []
        for minutes in (3, 23, 43, 17):  # rounds 1, 2 and 3, and the break after the first
            R._now = lambda m=minutes: t0 + datetime.timedelta(minutes=m)
            got.append(mom(R.board_view()["mine"]["sev"]))
        seed = rm.vary_seed(f)
        check("on the board: a round each, never the same move twice running; the break's stretch takes its turn too",
              got == [sev.nth("focus", r + seed) for r in (1, 2, 3)] + [sev.nth("stretch", 1 + seed)]
              and got[0] != got[1] != got[2], got)

        # the nudge: a different way in each day
        real = datetime
        ways = []
        for day in (13, 14, 15, 16):
            _state["labels"] = [f"2026-10-{day}"]
            R.datetime = types.SimpleNamespace(date=types.SimpleNamespace(today=lambda d=day: real.date(2026, 10, d)))
            ways.append(R.nudge_sev())
        again = R.nudge_sev()
        check("the nudge: a different way in each day (in turn), and drawn again the same day it stays put",
              all(mom(w) in sev.moves("peek") for w in ways) and all(mom(a) != mom(b) for a, b in zip(ways, ways[1:]))
              and not rests(ways[-1]) and rests(again) and mom(again) == mom(ways[-1]))
        R.datetime = real

        # a room's seats
        ms = [(u, u.upper(), u == "me") for u in ("a", "b", "c", "d", "e", "me")]
        check("a room's seats: each its own small thing now and then, side by side never the same",
              [x["m"] for x in rm.seats(ms, [], ("#2e7d32", "#7cc47f"))] == ["idle", "sread", "snod", "sreach", "slook", "idle"]
              and "'idle.' + s.m" in rm._RUNTIME)
        check("…the board draws the seat's move, and only a seat's",
              mom(board._seat_html({"n": "A", "m": "snod"})) == "snod" and mom(board._seat_html({"n": "A", "m": "hop"})) == "idle"
              and mom(board._seat_html({"n": "A"})) == "idle")

        # new: signed out
        R.cfg = lambda: {}
        _state.pop("sev_hello", None)
        a, b = R.signed_out_sev(), R.signed_out_sev()
        card = board.signed_out_card({}, sev=a)
        check("signed out (Sam's pick): Pip waves, a hello from its mix, once; drawn again it rests there",
              mom(a) in sev.moves("hello") and not rests(a) and mom(b) == mom(a) and rests(b))
        check("…beside the words on the card, with its colours and motion sheet",
              card.index('class="dc-hi"') < card.index("Your friends’") and "sv-blink" in card
              and "--sv-a: var(--dc-accent)" in card and "duecrew:setup" in card)
        check("…only on the way in: an expired sign-in or a deleted account says just what happened",
              "dc-hi" not in board.signed_out_card({}, expired=True, sev=a) and "dc-hi" not in board.signed_out_card({}, gone=True, sev=a))
        R.cfg = lambda: {"sev": False}
        check("…Settings › Pip off: the card as it was", R.signed_out_sev() is None
              and 'class="sv' not in board.signed_out_card({}, sev=None) and "sv-blink" not in board.signed_out_card({}, sev=None)
              and "Start with your email" in board.signed_out_card({}))

        # new: a crewmate's big streak
        R.cfg = lambda: {}
        _state.pop("sev_banner", None)
        big = [("dre", "Dre <b>", 100), ("ana", "Ana", 365)]
        one, two = R.milestone_sevs(big), R.milestone_sevs(big)
        check("a crewmate's big streak (Sam's pick): Pip hops in the emoji's place, from the day done's mix, once a banner",
              set(one) == {"dre", "ana"} and all(mom(one[u]) in sev.moves("hop") for u in one) and mom(one["dre"]) != mom(one["ana"])
              and not any(rests(x) for x in one.values()) and all(rests(two[u]) and mom(two[u]) == mom(one[u]) for u in two)
              and 'aria-label="Pip: a big streak"' in one["dre"] and "Dre" not in one["dre"])
        data = {"entries": [], "labels": ["2026-10-13"], "tomorrow": "", "pending": []}
        ban = board.render(data, {}, 0, milestones=big, milestone_sev=one)
        plain = board.render(data, {}, 0, milestones=big)
        check("…on the banner; Send stays as it was, the name escaped",
              ban.count('<span class="dc-fig">') == 2 and "Send &#128175;" in ban and "Send &#127881;" in ban
              and "Dre &lt;b&gt;" in ban and "<span>&#128175;</span>" not in ban)
        R.cfg = lambda: {"sev": False}
        check("…Pip off: the emoji, as before", R.milestone_sevs(big) is None and "<span>&#128175;</span>" in plain
              and "<span>&#127881;</span>" in plain and '<span class="dc-fig">' not in plain)
    finally:
        R.cfg, R.my_room, R._done, R._fifteen_done, R._now, R.datetime, st = saved
        _state.clear()
        _state.update(st)


def test_closet_core_v382():
    """3.8.2, Pip's closet: one thing in each place, a costume the whole look
    (one at a time, the look waiting under it), things earned from facts,
    the next in each line when it's close, and Pip wearing it all (what it
    holds in its right hand, where the hand goes)."""
    from due_crew import closet as C, closet_art as CA, sev
    ks = [t["k"] for t in C.THINGS]
    check("every thing has its drawing, and every drawing a thing", set(ks) == set(CA.ART) and len(ks) == len(set(ks)) == 64,
          (len(ks), set(ks) ^ set(CA.ART)))
    check("each thing has a place, a group and a rule; seasons say when",
          all(t["slot"] in C.SLOTS + (C.COSTUME,) and t["group"] in C.GROUPS and t["rule"] and t["name"] for t in C.THINGS)
          and all(t.get("when") for t in C.THINGS if t["group"] == "Seasons"))
    check("one in each place: a hat replaces the hat",
          C.wear(["beanie", "glasses"], "cap") == ["glasses", "cap"] and C.wear(["cap"], "cap") == [])
    check("a costume over the look, one at a time: the second replaces the first, the look waits under them",
          C.wear(["headphones", "glasses"], "dino") == ["headphones", "glasses", "dino"]
          and C.wear(["headphones", "glasses", "dino"], "ghost") == ["headphones", "glasses", "ghost"]
          and C.shown(["headphones", "glasses", "ghost"]) == ["ghost"] and C.costume(["headphones", "ghost"]) == "ghost")
    check("taking the costume off brings the look back; putting a thing on takes the costume off",
          C.wear(["headphones", "dino"], "dino") == ["headphones"]
          and C.wear(["headphones", "dino"], "glasses") == ["headphones", "glasses"])
    check("a thing that reaches into another place takes it too (winter's scarf)",
          C.wear(["scarf", "headphones"], "winter") == ["winter"] and C.wear(["winter"], "medal") == ["medal"]
          and C.places("winter") == {"head", "body"})
    check("any look anyone sends is made one the closet can draw: unknown things out, clashes settled as worn, no repeats",
          C.clean(["beanie", "nope", 7, "cap", "cap", "dino", "ghost", "glasses"]) == ["cap", "ghost", "glasses"]
          and C.clean("beanie") == [] and C.clean(None) == [] and len(C.clean(ks)) <= C.LOOK_MAX)
    f = {"days": 120, "run": 12, "reviews": 26000, "fifteens": 1, "crew": 2, "halloween": 3, "leeches": 6, "own_cards": 10}
    got = C.earned(f)
    check("earned from facts: each thing's need met",
          {"sprout", "beanie", "glasses", "stetho", "mustache", "headphones", "bowtie", "pumpkin", "witch", "batwings"} == set(got)
          and "cap" not in got and "ghost" not in got)
    check("what's new is only what wasn't there, on today",
          C.new(f, {"sprout": "2026-01-02", "beanie": "2026-02-01"}, "2026-10-14") == {k: "2026-10-14" for k in got if k not in ("sprout", "beanie")})
    near = C.near(f, {})
    check("almost there: the next in each line, at least half there, closest first; never seasons or secrets",
          [n[0] for n in near] == ["cap", "magnifier", "tophat"] and near[0] == ("cap", 12, 14, "days in a row"))
    check("a closet from the server: known things with a date", C.clean_closet({"cap": "2026-01-01", "x": "2026-01-01", "beanie": "soon", "sprout": 3}) == {"cap": "2026-01-01"})
    check("two computers' closets: everything either earned, on its first day",
          C.merge_closets({"cap": "2026-03-01"}, {"cap": "2026-02-01", "beanie": "2026-01-01"}) == {"cap": "2026-02-01", "beanie": "2026-01-01"})
    days = ["2025-10-24", "2025-10-25", "2025-10-29", "2026-02-13", "2026-02-14", "2026-03-20", "2024-02-29",
            "2025-12-31", "2026-01-01", "2026-01-02", "2026-01-03"] + [f"2026-04-{d:02d}" for d in range(1, 21)]
    fd = C.from_days(days)
    check("the days give: how many, the longest run, the comebacks, the seasons and the secrets",
          fd["days"] == len(days) and fd["run"] == 20 and fd["back7"] >= 3 and fd["back30"] >= 2 and fd["halloween"] == 3
          and fd["winter"] == 4 and fd["newyear"] == 1 and fd["friends"] == 1 and fd["spring"] == 1 and fd["fri13"] == 1
          and fd["leap"] == 1 and fd["pi"] == 0 and fd["summer"] == 0, fd)
    dt = datetime.datetime
    fh = C.from_hours([dt(2026, 5, 1, 6), dt(2026, 5, 1, 7), dt(2026, 5, 2, 3), dt(2026, 5, 2, 22), dt(2026, 5, 3, 1),
                       dt(2025, 12, 31, 23)])
    check("the hours give: mornings before 8 (not the small hours), evenings after 9 (by the evening), the year turning",
          fh == {"mornings": 1, "evenings": 2, "yearturn": 1}, fh)
    plain = sev.svg("idle", rest=True)
    check("no look: Pip is drawn as it always was", sev.svg("idle", rest=True, look=[]) == plain
          and sev.still("idle", "#2e7d32") == sev.still("idle", "#2e7d32", look=None))
    dressed = sev.svg("hello", look=["headphones", "mug", "cape"])
    arm = dressed.split('class="sv-armR">', 1)[1]
    check("a look goes on: behind, over, and what it holds in the right arm, upright",
          CA.ART["cape"][1][:40] in dressed.split("sv-armL")[0] and CA.ART["headphones"][0][:40] in dressed
          and CA.ART["mug"][0][:30] in arm.split("</g></g></g>")[0] and "rotate(150)" in arm)
    busy = sev.svg("focus", look=["mug"])
    check("a busy pose's hands hold their own thing; the closet's is set down beside it, never gone (Sam: a fifteen took the mug)",
          CA.ART["mug"][0][:30] in busy.split('class="sv-armL"')[0] and 'class="cl-down" transform="translate(4 12)"' in busy
          and CA.ART["mug"][0][:30] not in busy.split('class="sv-armR">', 1)[1].split("</g></g>")[0]
          and 'cl-down' in sev.svg("away", look=["umbrella"]) and 'cl-down' not in sev.svg("idle", look=["mug"])
          and 'cl-down' not in sev.svg("focus", look=["cap"])
          and sev.busy("focus") and sev.busy("exam") and not sev.busy("hop"))
    from due_crew import room_model as RM2
    fif, _css, _t = RM2._sevs(RM2.FIFTEEN_SEV, True, RM2.FIFTEEN_VARY, look=["mug"])
    check("…so a fifteen's every moment still has it, held or beside", all(CA.ART["mug"][0][:30] in v for v in fif.values()))
    check("a costume shows alone", CA.ART["headphones"][0][:40] not in sev.svg("idle", look=["headphones", "dino"])
          and CA.ART["dino"][0][:40] in sev.svg("idle", look=["headphones", "dino"]))
    check("a still Pip wears it too, colours its own", CA.ART["cap"][0][:30] in sev.still("idle", "#2e7d32", look=["cap"]))
    still, motion = sev.CSS.split("@media", 1)
    check("an arm turns at its shoulder whatever it holds; the closet's things move only under no-preference",
          ".sv .sv-armL, .sv .sv-armR { transform-box: view-box; transform-origin: 0 0; }" in still
          and all(f".sv .cl-{c} {{ animation" in motion for c in ("prop", "steam", "flame", "flick", "bal", "flag", "blink", "glow", "wl", "wr"))
          and "animation" not in still.split("3.8.2: the closet's things that move")[1])


def test_closet_board_v382():
    """3.8.2, Pip's closet on the board: in place of the board (as Settings
    is), its clicks reaching it through the add-on's own handler, the
    board's line when something comes, and each crew row's Pip in the
    emoji's place, wearing its person's colour and look."""
    import due_crew as dc
    from due_crew import closet as C, closet_art as CA
    from aqt.deckbrowser import DeckBrowser
    have = {"sprout": "2026-01-01", "beanie": "2026-01-08", "headphones": "2026-02-01", "dino": "2026-08-01", "bowtie": "2026-03-01"}
    view = {"tab": "Yours", "have": have, "look": ["bowtie", "glasses", "headphones"],
            "near": [("cap", 11, 14, "days in a row")], "progress": {"cap": (11, 14), "beanie": (3, 7)}, "new": ["dino"], "msg": ""}
    page = board.closet_html(view, {"theme": "light"})
    fig = page.split('class="cl-fig"')[1].split("</div>")[0]
    check("the closet: its own page, a way back, how many of how many; Yours and To earn, each with its count",
          "dc-closet" in page and "duecrew:closetclose" in page and f"5 of {len(C.THINGS)}" in page
          and "Yours <small>5</small>" in page and f"To earn <small>{len(C.THINGS) - 5}</small>" in page
          and "duecrew:closettab:1" in page and "never bought" not in page)
    check("Yours: only my things, each a button, by place (head to back, then costumes); nothing greyed, nothing to try",
          page.count('<button class="cl-t') == len(have) and 'class="cl-t lk' not in page and "closettry" not in page
          and "duecrew:closetwear:cap" not in page and "duecrew:closetwear:beanie" in page
          and page.index(">Head") < page.index(">Body") < page.index(">Costumes")
          and "Yours since 8 Jan" in page
          and "<b>Beanie</b><small>7 days in a row</small>" in page)  # what earned it, under its name
    check("what's on says so: the accent, filled, a tick; a look naming what I haven't earned drops it",
          page.count('<span class="cl-badge">&#10003; On</span>') == 2 and page.count('class="cl-t on') == 2
          and 'aria-label="Headphones, on"' in page and 'aria-label="Beanie, not on"' in page
          and CA.ART["glasses"][0][:30] not in fig and CA.ART["headphones"][0][:30] in fig)
    check("what's on, place by place, each taking it off; a place with nothing yet says what's next",
          page.count('title="Take it off"') == 2 and '<span>Face</span><i>&ndash;</i>' in page
          and "Next: <b>Round glasses</b>, 100 days studied" in page and "Take it all off" in page)
    check("what just came is marked New", page.count('class="cl-badge n"') == 1 and " new\"" in page.split("closetwear:dino")[0][-400:])
    dressed = board.closet_html(dict(view, look=["bowtie", "headphones", "dino"]), {"theme": "dark"})
    check("a costume on: it's the one On, the costume's row first; the things under it say Under, and come back when it's off",
          dressed.count("&#10003; On") == 1 and dressed.count('<span class="cl-badge u">Under</span>') == 2
          and 'cl-ons covered' in dressed and '<div class="cl-o cos"><span>Costume</span>' in dressed
          and 'aria-label="Bow tie, under the costume"' in dressed)
    earn = board.closet_html(dict(view, tab="To earn"), {"theme": "light"})
    secrets = [t for t in C.THINGS if t["group"] == "Secret"]
    check("To earn: every thing I haven't got, shown but never a button, by how it's earned; how far along",
          earn.count('<div class="cl-t lk') == len(C.THINGS) - len(have) and '<button class="cl-t' not in earn
          and "duecrew:closetwear:cap" not in earn and "Almost there" in earn and "11 of 14 days in a row" in earn
          and "<small>11 of 14</small>" in earn and "<small>3 of 7</small>" not in earn  # beanie is mine
          and "Showing up <small>" in earn)
    check("a secret you haven't found shows nothing of it", earn.count("<b>A secret</b>") == len(secrets)
          and "Pi day" not in earn and CA.ART["catears"][0][:40] not in earn)
    off = board.closet_html(view, {"sev": False})
    check("with Pip off, the closet says nobody sees it for now", "nobody sees it" in off)
    line = board.closet_line(["cap"], ["beanie"])
    check("the board's line: Pip in the new thing, its name and why, Wear it, the closet, later",
          "New for your Pip: Cap." in line and "14 days in a row" in line and "duecrew:closetwear:cap" in line
          and ("duecrew:closet|" + KK + "'") in line and "duecrew:closetnew" in line and CA.ART["cap"][0][:40] in line
          and "Be one" in board.closet_line(["dino"], []))
    check("the day it opens, one line for everything your days earned",
          "earned it 9 things" in board.closet_line(list(C.BY)[:9], [], first=True))
    # rows: Pip in the emoji's place
    labels = [(TODAY - datetime.timedelta(days=i)).isoformat() for i in range(7)]
    ents = [{"user_id": "me", "name": "Sammy", "emoji": "🦊", "you": True, "paused": False, "last_updated": "", "exam_date": "",
             "days": {labels[0]: {"studied": True, "reviews": 30}}, "decks": []},
            {"user_id": "dre", "name": "Dre <i>", "emoji": "🐢", "you": False, "paused": False, "last_updated": "", "exam_date": "",
             "accent": "blue", "look": ["dino"], "days": {labels[0]: {"studied": True, "reviews": 20}}, "decks": []}]
    data = {"entries": ents, "labels": labels, "tomorrow": "", "pending": []}
    conf = {"accent": "rose", "sev_look": ["cap", "glasses"], "sev_closet": {"cap": "2026-01-01"}}
    crew = board.render(data, conf, 0)
    rows = crew.split("<table")[1]
    check("crew rows: each person's Pip where the emoji was, in their colour",
          "🦊" not in rows and "🐢" not in rows and rows.count('class="dc-rsev"') == 2
          and "--rs-l:#1e5fb4" in rows and "--rs-l:#b03052" in rows and "--sv-a: var(--rs-l);" in crew)
    check("their look on their Pip; mine only what I've earned; my Pip opens the closet",
          CA.ART["dino"][0][:40] in rows and CA.ART["cap"][0][:40] in rows and CA.ART["glasses"][0][:40] not in rows
          and 'title="Pip&rsquo;s closet"' in rows and "Dre &lt;i&gt;" in rows and "Dre <i>’s Pip" not in rows)
    plain = board.render(data, dict(conf, sev=False), 0).split("<table")[1]
    check("Pip off: the emoji as before", "🦊 Sammy" in plain and "dc-rsev" not in plain)
    squares = board.render(data, dict(conf, show_up=True), 0)
    check("the days view's rows too", squares.count('class="dc-rsev"') >= 2)
    dre_row = rows.split('>Dre &lt;i&gt;</a>')[0].rsplit("<tr", 1)[1]
    check("a row with Pip: room above it for a hat (the whole row, so name and numbers share a line); "
          "their Pip beside the name's underline, opening their profile too",
          'class="sv"' in dre_row and 'tr.sv > td { padding-top: 12px; }' in crew
          and ('class="dc-rsevl" href="#" tabindex="-1" aria-hidden="true" onclick="pycmd(\'duecrew:profile:dre|' + KK + '\')') in dre_row
          and dre_row.index('class="dc-rsev"') < dre_row.index('class="dc-pl"')
          and 'tr.sv' not in board.render(data, dict(conf, sev=False), 0))
    # profile cards (3.8.2): their Pip where the emoji was, as on their row; mine opens the closet
    card = board.profile_overlay_js({"name": "Dre", "uid": "dre", "cells": None, "emoji": "🐢",
                                     "sev": board.card_sev(ents[1], conf)})
    mine_card = board.profile_overlay_js({"name": "Sammy", "you": True, "cells": None, "emoji": "🦊",
                                          "sev": board.card_sev(ents[0], conf)})
    turtle, fox = json.dumps("🐢")[1:-1], json.dumps("🦊")[1:-1]  # as the card's script carries them
    check("profile cards: Pip in the emoji's place, in their colour and look; mine links to the closet",
          turtle not in card and "dc-psev" in card and json.dumps(CA.ART["dino"][0])[1:30] in card and "--sv-a: #1e5fb4" in card
          and fox not in mine_card and json.dumps(CA.ART["cap"][0])[1:30] in mine_card
          and ("remove();pycmd('duecrew:closet|" + KK + "')") in mine_card
          and "Change emoji" in mine_card and board.card_sev(ents[1], dict(conf, sev=False)) is None
          and turtle in board.profile_overlay_js({"name": "Dre", "uid": "dre", "cells": None, "emoji": "🐢"}))
    from due_crew import room_model as RM
    chip = RM.start_data(("#2e7d32", "#7cc47f"), "right", True, look=["cap"])
    check("▶ Fifteen? in the top bar wears my look (it was plain)", CA.ART["cap"][0][:30] in chip["sev"]["idle"]
          and CA.ART["cap"][0][:30] not in RM.start_data(("#2e7d32", "#7cc47f"), "right", True)["sev"]["idle"])
    check("Settings › Fifteen and Pip: the closet, a click away", ("duecrew:closet|" + KK + "'") in board._settings_board({}))
    col_page = board.closet_html({"tab": "Yours", "have": {}, "look": []}, {"accent": "blue"})
    check("3.9.0 (Sam): the closet has the colour too, every accent, the one on pressed, as Settings' Board tab has it",
          all(f"duecrew:set:accent:{k}" in col_page for k in board.ACCENTS) and 'aria-label="Blue" aria-pressed="true"' in col_page
          and "Pip and your board" in col_page and board._accent_swatches({"accent": "blue"}) in board._settings_board({"accent": "blue"}))
    # the clicks, as the board sends them
    if "aqt.reviewer" not in sys.modules:
        sys.modules["aqt.reviewer"] = types.SimpleNamespace(Reviewer=type("Reviewer", (), {}))
    mine = {"sev_closet": dict(have), "sev_look": ["beanie"]}
    saved = (dc._swap, dc.cfg, dc.save_cfg, dc._board_on_screen)
    swaps = []
    from due_crew import closet_flow as cf
    saved_flow = (cf.cfg, cf.save_cfg, cf.facts)
    dc._swap = lambda c, focus=None: swaps.append(focus)
    dc.cfg = cf.cfg = lambda: mine
    dc.save_cfg = cf.save_cfg = lambda c, **k: mine.update(c)
    cf.facts = lambda c=None: {"run": 11}
    dc._board_on_screen = lambda: True
    send = lambda m: dc._on_js(False, as_board("duecrew:" + m), DeckBrowser())
    try:
        dc._state["closet_new"] = {"keys": ["dino"], "first": False}
        send("closet")
        st = dict(dc._state["closet_open"])
        send("closettab:1")
        tab9 = dc._state["closet_open"]["tab"]
        send("closettry:cap")  # an older page's try-on: nothing, and nothing worn
        tried = "try" in dc._state["closet_open"] or "cap" in mine["sev_look"]
        send("closetwear:headphones")
        send("closetwear:cap")  # not mine: nothing
        send("closetwear:dino")
        worn = list(mine["sev_look"])
        send("closetwear:dino")
        back = list(mine["sev_look"])
        send("set:accent:purple")  # 3.9.0 (Sam): the colour, from the closet
        coloured = (mine.get("accent"), dc._state["closet_open"] is not None)
        send("closettab:99")
        send("closetoff")
        offed = list(mine["sev_look"])
        v = dc._closet_view()
        send("closetclose")
        check("the closet opens in the board's place; what just came is new there, and the line is done",
              st["tab"] == "Yours" and st["new"] == ["dino"] and dc._state["closet_new"] is None and tab9 == "To earn")
        check("its clicks: put mine on (a hat replaces the hat; a costume over the look, off again: the look's back), never one I haven't",
              not tried and worn == ["headphones", "dino"] and back == ["headphones"], (worn, back))
        check("the closet's colour: Pip's and the board's, saved as Settings saves it, and the closet stays open",
              coloured == ("purple", True), coloured)
        check("take it all off; its view holds what's mine and what's near; back to the board",
              offed == [] and v["have"] == have and v["near"] and v["near"][0][0] == "cap" and v["progress"]["cap"] == (11, 14)
              and dc._state["closet_open"] is None and len(swaps) >= 8)
        dc._state["closet_new"] = {"keys": ["sprout"], "first": False}
        send("closetwear:sprout")
        check("Wear it, on the board's line: on, and the line's done",
              "sprout" in mine["sev_look"] and dc._state["closet_new"] is None)
    finally:
        dc._swap, dc.cfg, dc.save_cfg, dc._board_on_screen = saved
        cf.cfg, cf.save_cfg, cf.facts = saved_flow
        dc._state["closet_open"] = dc._state["closet_new"] = None


def test_squad_pips_v3821():
    """3.8.21 (Sam: "squads page still has the old emojis and not the new
    pips"): the Squads tab's people are Pips, as Crew's are: mine in my colour
    and look, a crewmate's in theirs (a mutual friend's, which only the crew
    brings), anyone else plain in the default colour, since a squadmate
    shares a name and an emoji, nothing more. A plan's squad too, its faces
    and its threads. With Pip off, the emojis. And the site's twin."""
    from due_crew import closet_art as CA
    lb = [(TODAY - datetime.timedelta(days=i)).isoformat() for i in range(2)]
    rows = [{"user_id": "me", "name": "Sammy", "emoji": "🦊", "day": lb[0], "reviews": 50, "time_ms": 60000, "you": True},
            {"user_id": "dre", "name": "Dre", "emoji": "🐢", "day": lb[0], "reviews": 40, "time_ms": 60000, "crew": True},
            {"user_id": "zed", "name": "Zed <b>", "emoji": "🐸", "day": lb[0], "reviews": 30, "time_ms": 60000}]
    view = {"state": "ok", "squads": [{"id": "s", "name": "S"}], "current": "s", "name": "S", "open": True,
            "rows": rows, "day": lb[0], "yesterday": lb[1], "people": 3, "reviews": 120}
    conf = {"accent": "rose", "sev_look": ["cap"], "sev_closet": {"cap": "2026-01-01"}}
    crew = {"dre": {"user_id": "dre", "accent": "blue", "look": ["dino"]}}
    html = board._squads_html(view, conf, crew)

    def row(name):
        i = html.index(name)
        return html[html.rfind("<tr", 0, i):html.index("</tr>", i)]
    me, dre, zed = row(">Sammy<"), row(">Dre<"), row(">Zed &lt;b&gt;<")
    green = board.accent_pair(None)[0]
    check("squads: a Pip where each emoji was, room above it for a hat",
          not any(x in html for x in ("🦊", "🐢", "🐸")) and all('class="sv"' in r or ' sv"' in r for r in (me, dre, zed)))
    check("…mine in my colour and look, opening the closet; a crewmate's in theirs",
          CA.ART["cap"][0][:30] in me and "--rs-l:#b03052" in me and ("duecrew:closet|" + KK + "'") in me
          and CA.ART["dino"][0][:30] in dre and "--rs-l:#1e5fb4" in dre)
    check("…anyone else plain, in the default colour (nothing of theirs but a name), the name still text",
          f"--rs-l:{green}" in zed and "cl-" not in zed.split("dc-pl")[0] and "Zed <b>" not in zed
          and "Zed &lt;b&gt;’s Pip" in zed)
    plain = board._squads_html(view, dict(conf, sev=False), crew)
    check("…Pip off: the emojis as before", "🦊 Sammy" in plain and "🐢 Dre" in plain and "dc-rsev" not in plain)
    team = {"on": True, "count": 3, "shown": 2,
            "faces": [{"uid": "me", "name": "Sammy", "emoji": "🦊", "shown": True},
                      {"uid": "dre", "name": "Dre", "emoji": "🐢", "shown": True},
                      {"uid": "zed", "name": "Zed", "emoji": "🐸", "shown": False}],
            "asks": [{"id": 1, "uid": "dre", "name": "Dre", "emoji": "🐢", "text": "why?", "replies": [], "mine": False}]}
    ps = board._plan_squad_html("p1", {"team": team, "me": "me"}, crew, conf)
    faces = ps.split('class="faces"')[1].split('<div class="tg">')[0]
    check("a plan's squad: its faces are Pips, a size up (mine, my crewmate's in their look, the rest plain)",
          not any(x in ps for x in ("🦊", "🐢", "🐸")) and faces.count('class="dc-rsev') == 3
          and "width:24px" in faces and CA.ART["dino"][0][:30] in faces and CA.ART["cap"][0][:30] in faces)
    check("…and so is who asked", CA.ART["dino"][0][:30] in ps.split('class="tqa"')[1]
          and "🐢" in board._plan_squad_html("p1", {"team": team, "me": "me"}, crew, dict(conf, sev=False))
          and "🐢" in board._plan_squad_html("p1", {"team": team, "me": "me"}))
    page = board.render({"entries": [{"user_id": "me", "name": "Sammy", "you": True, "days": {}},
                                     dict(crew["dre"], name="Dre", days={})], "labels": lb, "tomorrow": "", "pending": []},
                        dict(conf, period="squads"), 0, squad_view=view)
    check("…the board hands the squads its crew", CA.ART["dino"][0][:30] in page.split(">Dre<")[0].rsplit("<tr", 1)[1])
    root = os.path.dirname(os.path.dirname(os.path.abspath(SUITE_FILE)))
    app_js = open(os.path.join(root, "site", "public", "app.js"), encoding="utf-8").read()
    builder_js = open(os.path.join(root, "site", "public", "builder.js"), encoding="utf-8").read()
    check("the site's twin: squad rows, a plan squad's faces and threads, by the same rule",
          "function squadPip(x, pips)" in app_js and "accentPair(you ? p.accent || worn : p.accent)" in app_js
          and 'squadPip(r, pips) || (r.emoji ? r.emoji + " " : ""), r.name)' in app_js
          and "pip: (x) => squadPip(x, pips)" in app_js and "new Map(people.map((p) => [p.uid, p]))" in app_js
          and "pipOf(f) || face(f.emoji, f.name)" in builder_js and "[pipOf(x) || (x.emoji" in builder_js)


# Names of the parts after this one. The package sets them as each of those parts loads
# (an import here would load a later part before the ones between).
_LATER = ("n", "t", "tag")
n = t = tag = None
