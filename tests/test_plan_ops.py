"""Round five's plan changes (due_crew/planner: ops.py, draft.py, view.py,
edits.new_plan_doc; docs/planner.md): every change an op, said in words,
waiting under the plan till it's sent, replayed on a co-author's save; the
Plan tab's arithmetic (each week's asks, the shape line, suggestions read
through an index); a send's line kept by the fake Worker as the Worker
keeps it. Standard library only.

Run: python3 tests/test_plan_ops.py
"""

import copy
import datetime
import json
import os
import sys

HARNESS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HARNESS)
sys.path.insert(0, HARNESS)

import fakes  # noqa: E402

STORE = fakes.FakeWorker()
fakes.install_fake_requests(STORE)
fakes.install_fake_aqt()
sys.path.insert(0, REPO)

from due_crew.planner import build as B        # noqa: E402
from due_crew.planner import draft as D        # noqa: E402
from due_crew.planner import edits as E        # noqa: E402
from due_crew.planner import ops as O          # noqa: E402
from due_crew.planner import view as V         # noqa: E402

CHECKS = []
ROOT = "#Big_Step1_v3"
VID = f"{ROOT}::#Videos::Cardio::Heart_Failure"
SHOCK = f"{ROOT}::#Videos::Cardio::Shock"
BOOK = f"{ROOT}::#Book::Cardio::Heart_Failure"
DRUGS = f"{ROOT}::#Videos::Pharm::HF_Drugs"
TODAY = "2026-10-20"


def check(name, cond, detail=""):
    CHECKS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond or detail == "" else f"\n     {detail}"))


def tree():
    return B.Tree([(VID, 18), (SHOCK, 7), (BOOK, 6), (DRUGS, 9), (f"{ROOT}::#Videos::Cardio::Arrhythmias", 48)], [])


def doc():
    return {"deck": "Big Step 1", "units": [
        {"id": "u1", "name": "Heart failure", "opens": "2026-10-19", "due": "2026-10-21", "tags": [VID], "for": "e1"},
        {"id": "u2", "name": "HF drugs", "opens": "2026-10-20", "tags": [DRUGS]},
        {"id": "u3", "name": "Shock", "opens": "2026-10-22", "tags": [SHOCK]},
    ], "events": [{"id": "e1", "day": "2026-10-23", "name": "Cardio quiz 1"}],
        "pace": {"mode": "daily", "days": [1, 1, 1, 1, 1, 0, 0], "daily": 20}}


def ctx():
    return O.Ctx(tree(), TODAY, "MS2 Block 2", [1, 1, 1, 1, 1, 0, 0])


def test_ops_by_name():
    d = doc()
    for ref, want in (("u3", "u3"), ("2026-10-22", "u3"), ("Shock", "u3"), ("2026-10-22 Shock", "u3"), ("shock", "u3")):
        check(f"ops: a date named by {ref!r}", O.find_date(d, ref) == want)
    for ref, words in (("Renal", "No set on the plan is Renal."), ("", "Which set?")):
        try:
            O.find_date(d, ref)
            check(f"ops: {ref!r} is refused", False)
        except E.Refused as e:
            check(f"ops: {ref!r} is refused, said", str(e).startswith(words), str(e))
    try:
        O.check(d, {"op": "teleport"})
        check("ops: an op that isn't one is refused", False)
    except E.Refused as e:
        check("ops: an op that isn't one is refused, said", "no change called teleport" in str(e), str(e))


def test_ops_apply_and_words():
    d, c = doc(), ctx()
    o = O.check(d, {"op": "move", "date": "Shock", "to": "2026-10-23"})
    after, entries, touched = O.apply(d, o, c)
    u3 = next(u for u in after["units"] if u["id"] == "u3")
    check("ops: move puts the date on its day", u3["opens"] == "2026-10-23" and touched == {"u3"})
    check("ops: move said: Moved, the date, from its old day, on its old day",
          entries[0]["verb"] == "Moved" and entries[0]["detail"].startswith("from ") and entries[0]["day"] == "2026-10-22", entries)
    check("ops: who a change to a date still to come touches", O.who(entries[0], TODAY) == "Not open for anyone yet")
    check("ops: who a change to an opened date touches",
          O.who({"day": "2026-10-19"}, TODAY).startswith("Open since") and "keeps them" in O.who({"day": "2026-10-19"}, TODAY))
    check("ops: the line to followers, filled in from the changes", O.why_line(entries).startswith("Shock moved from"), O.why_line(entries))
    check("ops: the line to followers stays one line of 200 at most",
          len(O.why_line([dict(entries[0], what=f"Fri 23 · {'x' * 80} {i}") for i in range(10)])) <= O.WHY_MAX)
    o = O.check(d, {"op": "add_date", "day": "2026-10-26", "name": "Arrhythmias"})
    a1, _e, t1 = O.apply(d, o, c)
    a2, _e, t2 = O.apply(d, o, c)
    check("ops: a new date's id comes from the op's seed: the same op makes the same id", t1 == t2 and len(t1) == 1)
    new = next(u for u in a1["units"] if u["id"] in t1)
    check("ops: a date with no cards yet (round five: a calendar's session)", new["name"] == "Arrhythmias" and not B.srcs(new))
    o = O.check(d, {"op": "add_cards", "date": "Shock", "tags": [BOOK]})
    a3, e3, _t = O.apply(d, o, c)
    check("ops: add_cards puts the tag on and says what it holds",
          BOOK in next(u for u in a3["units"] if u["id"] == "u3")["tags"] and "6 cards" in e3[0]["detail"], e3)
    try:
        O.apply(d, O.check(d, {"op": "take_cards", "date": "u3", "key": ["tag", SHOCK]}), c)
        check("ops: the last thing on a set doesn't come off", False)
    except E.Refused as e:
        check("ops: the last thing on a set doesn't come off (delete the set instead)", "delete the set" in str(e), str(e))
    o = O.check(d, {"op": "set_phases", "catchup": 0, "taper": None})
    check("ops: catch-up weeks can be turned off (0 is a value)", o["catchup"] == 0)


def test_lay_out_op():
    d, c = doc(), ctx()
    o = O.check(d, {"op": "lay_out", "pace": {"mode": "daily", "days": [1, 1, 1, 1, 1, 0, 0], "daily": 20},
                    "cover": [f"tag:{ROOT}::#Videos::Cardio::Arrhythmias"], "start": "2026-10-19"})
    after, entries, touched = O.apply(d, o, c)
    new = [u for u in after["units"] if u["id"] in touched]
    check("ops: lay_out puts what's ticked on study days after the last date, at the pace",
          new and all(u["opens"] > "2026-10-22" for u in new) and sum(len(u.get("tags") or []) for u in new) >= 1
          and after["pace"]["cover"] == [f"tag:{ROOT}::#Videos::Cardio::Arrhythmias"], new)
    check("ops: lay_out said: Laid out, how many new sets", entries[0]["verb"] == "Laid out", entries)
    try:
        O.apply(d, O.check(d, dict(o, cover=[f"tag:{VID}"])), c)
        check("ops: nothing to lay out is said", False)
    except E.Refused as e:
        check("ops: what's ticked and on a date already: nothing to lay out, said", bool(str(e)), str(e))
    try:
        O.apply(d, o, O.Ctx(None, TODAY))
        check("ops: lay_out with no deck here", False)
    except E.Refused as e:
        check("ops: lay_out with no deck here is refused, said", "isn't in this Anki" in str(e))


def test_draft():
    base, c = doc(), ctx()
    dr = D.Draft("p1", base, 3)
    dr.add({"op": "move", "date": "Shock", "to": "2026-10-23"}, c)
    dr.add({"op": "rename", "date": "u2", "name": "Heart failure drugs"}, c)
    d2, changes, dropped = dr.replay(c)
    check("draft: the changes on the plan as the server has it",
          [u["opens"] for u in d2["units"] if u["id"] == "u3"] == ["2026-10-23"] and len(changes) == 2 and not dropped)
    check("draft: the base is never changed", base == doc())
    try:
        dr.add({"op": "rename", "date": "u2", "name": "Heart failure drugs"}, c)
        check("draft: a change the plan has already", False)
    except E.Refused as e:
        check("draft: a change the plan has already is refused, said", "Nothing to change" in str(e))
    back = D.Draft.from_json("p1", json.loads(json.dumps(dr.to_json())))
    check("draft: kept on this computer and read back, the same plan", back.doc(c) == dr.doc(c) and back.version == 3)
    # a co-author takes Shock off meanwhile: its move no longer fits, dropped and said; the rename stays
    theirs = copy.deepcopy(base)
    theirs["units"] = [u for u in theirs["units"] if u["id"] != "u3"]
    dr.rebase(theirs, 4)
    d3, changes, dropped = dr.replay(c)
    check("draft: on a co-author's save, what still fits stays and what doesn't is dropped, said",
          len(changes) == 1 and len(dropped) == 1 and "isn't on the plan any more" in dropped[0][1]
          and next(u for u in d3["units"] if u["id"] == "u2")["name"] == "Heart failure drugs" and len(dr) == 1, dropped)
    doc_, summary, why = dr.payload(c)
    check("draft: one send: the doc, its history line, its line to followers",
          doc_["units"] and summary and why.startswith("Heart failure drugs renamed"), (summary, why))
    ai_ = D.Draft("p1", base, 3)
    ai_.add({"op": "move", "date": "Shock", "to": "2026-10-23", "by": "ai", "why": "Shock  moved to after the quiz."}, c)
    _d, ai_changes, _x = ai_.replay(c)
    check("draft: an AI app's change keeps who asked and its reason (never in the doc that's sent)",
          ai_changes[0]["op"].get("by") == "ai" and O.send_line(ai_changes) == "Shock moved to after the quiz."
          and "by" not in json.dumps(ai_.payload(c)[0]), O.send_line(ai_changes))
    ai_.add({"op": "rename", "date": "u2", "name": "Heart drugs"}, c)
    check("draft: with a change of my own beside it, the send's line is the changes in words",
          O.send_line(ai_.replay(c)[1]).startswith("Shock moved"), O.send_line(ai_.replay(c)[1]))
    dr.take(0)
    check("draft: a change taken out", len(dr) == 0 and dr.doc(c) == theirs)
    full = D.Draft("p1", base, 1, [O.check(base, {"op": "set_even", "date": "u1", "on": i % 2 == 0}) for i in range(O.OPS_MAX)])
    try:
        full.add({"op": "rename", "date": "u1", "name": "HF"}, c)
        check("draft: at most OPS_MAX waiting", False)
    except E.Refused as e:
        check("draft: at most OPS_MAX changes wait (send them first)", "send them first" in str(e))


def test_view():
    d, t = doc(), tree()
    pace = V.pace_of(d)
    asks = V.week_asks(d, t, pace)
    wk = asks.get("2026-10-19")
    check("view: a week's new cards a study day and reviews a day", wk and wk["new"] > 0 and wk["reviews"] >= 0, asks)
    words, warn = V.week_words(wk)
    check("view: a week's words", "new, " in words and "reviews a day" in words and not warn, words)
    heavy = dict(d, pace=dict(pace, daily=5))
    hw, hwarn = V.week_words(V.week_asks(heavy, t, V.pace_of(heavy)).get("2026-10-19"))
    check("view: a week over the pace says by how much, in amber", hwarn and "over your 5" in hw, hw)
    line = dict(V.shape_line(d, t, pace, asks))
    check("view: the shape, label by label; no end set said so", line.get("Dates") == "Mon 19 Oct – Thu 22 Oct, no end set"
          and line.get("Study days") == "Mon–Fri" and line.get("New a day") == "20", line)
    ended = dict(d, end="2026-10-23", phases={"taper": 3, "catchup": 4})
    line = dict(V.shape_line(ended, t, V.pace_of(ended), asks))
    check("view: the shape ends with the exam on its end day", line.get("Dates") == "Mon 19 Oct – Cardio quiz 1, Fri 23 Oct"
          and line.get("Last days") == "3 with no new cards" and line.get("Catch-up") == "every 4th week", line)
    check("view: study days in words", V.days_words([1, 1, 1, 1, 1, 0, 0]) == "Mon–Fri" and V.days_words([1] * 7) == "every day"
          and V.days_words([1, 0, 1, 0, 1, 0, 0]) == "Mon, Wed, Fri")
    u, now = V.today_date(d, TODAY)
    check("view: today's date (its window has today in it)", u["id"] == "u2" and now)


def test_no_suggestions():
    """Sam's call (round five): nothing suggests what goes on a date; the
    author puts every card there. Needs a look is no cards, or a week over."""
    d = doc()
    d["units"].append({"id": "u4", "name": "Heart failure book", "opens": "2026-10-24"})
    check("view: no suggestion helpers left", not any(hasattr(V, n) for n in ("SuggestIndex", "suggestions", "sure_ones")))
    look = V.needs_look(d, {"u1": 18, "u2": 9, "u3": 7, "u4": 0}, {})
    check("view: a date with no cards here needs a look; nothing else does here", look == {"u4": "no cards here yet"}, look)


def test_new_plan_doc():
    sessions = [{"date": "2026-10-26", "kind": "lecture", "title": "Heart failure"},
                {"date": "2026-10-27", "kind": "lecture", "title": "Something new"},
                {"date": "2026-10-30", "kind": "quiz", "title": "Cardio quiz 1"}]
    d, uids = E.new_plan_doc("Big Step 1", sessions, "Block 2 exam", "2026-11-13")
    names = {u["name"]: u for u in d["units"]}
    check("new plan: every session a date on its day, named as it is, with no cards (nothing picked for the author)",
          len(uids) == 2 and set(names) == {"Heart failure", "Something new"} and not any(B.srcs(u) for u in d["units"]))
    check("new plan: its quizzes and the exam it ends with are events; the end is the exam's day",
          sorted(e["name"] for e in d["events"]) == ["Block 2 exam", "Cardio quiz 1"] and d["end"] == "2026-11-13")
    check("new plan: each date tested on the next quiz after it", all(u.get("for") for u in d["units"]))
    check("new plan: it fits what's ticked to the end", d["pace"]["mode"] == "end" and d["pace"]["days"] == [1, 1, 1, 1, 1, 0, 0])
    d2, _u = E.new_plan_doc("Big Step 1", [], "", None)
    check("new plan: no calendar and no exam: an empty plan at 20 a day", not d2["units"] and d2["pace"]["mode"] == "daily")


def test_fake_keeps_a_sends_line():
    store = fakes.FakeWorker()
    sys.modules["requests"].Session = lambda: fakes.FakeSession(store)
    store.add_user("sam", "Sam")
    pid, _code = store.add_plan("sam", "MS2 Block 2", "Big Step 1", doc()["units"])
    from due_crew.backend import api
    from due_crew.planner import remote as R
    cl = api.ApiClient(os.path.join(os.environ.get("TMPDIR", "/tmp"), "dc-ops-session.json"))
    cl.session = {"user_id": "sam", "token": store.session_for("sam"), "name": "Sam"}
    raw, _plan = R.load(cl, pid)
    d = dict(raw["doc"], units=[dict(u, name="Shock!") if u["id"] == "u3" else u for u in raw["doc"]["units"]])
    outcome, got = R.save(cl, pid, raw["version"], d, "renamed Shock", "Shock is Thursday now.")
    posts = store.plan_posts.get(pid) or []
    check("fake: a save's line goes to followers as a post with the save (plans.ts postWithSave)",
          outcome == "saved" and posts and posts[0]["text"] == "Shock is Thursday now." and posts[0]["withSave"], (outcome, posts))
    for i in range(6):
        d = dict(d, units=[dict(u, name=f"Shock {i}") if u["id"] == "u3" else u for u in d["units"]])
        outcome, got = R.save(cl, pid, got["version"], d, "renamed", f"Line {i}")
    check("fake: past five lines a day the save still goes, the line doesn't",
          outcome == "saved" and len(store.plan_posts[pid]) == 5, len(store.plan_posts[pid]))


# ---- plans end to end: the builder's site-only editing, as ops ----

PEDS = f"{SHOCK}::Peds"
EXTRA = f"{SHOCK}::Extra"


def _u(d, uid):
    return next((u for u in d["units"] if u["id"] == uid), None)


def _refused(o, d, c, words):
    try:
        O.apply(d, O.check(d, o), c)
        return False
    except E.Refused as e:
        return words in str(e)


def _raises(fn, words):
    try:
        fn()
        return False
    except E.Refused as e:
        return words in str(e)


def test_leave_out_is_the_builders_but_not():
    """Leave out cards also tagged: the builder's Overlap "but not", the
    search it writes ("tag:A" -"tag:B", both as Tags.ankiSearch writes a
    tag), in the source's place; the date keeps its name."""
    d, c = doc(), ctx()
    o = O.check(d, {"op": "leave_out", "date": "Shock", "key": ["tag", SHOCK], "tag": PEDS, "n": 5})
    after, entries, touched = O.apply(d, o, c)
    u = _u(after, "u3")
    q = f"{B.anki_search('tag', SHOCK)} -{B.anki_search('tag', PEDS)}"
    check("leave out: the tag comes off and the builder's but-not search goes on in its place, with its count",
          u["tags"] == [] and u["search"] == [q] and u["sn"] == {q: 5} and touched == {"u3"}, u)
    check("leave out: read as the builder reads it (searchName), the date's name kept, said",
          B.search_name(q) == "Shock but not Peds" and u["name"] == "Shock"
          and entries[0]["detail"] == "Shock but not Peds" and entries[0]["verb"] == "Changed", (u["name"], entries))
    pt = dict(d, tagroot="MS2", tags=[{"id": "t1", "name": "SLG 12", "notes": ["g1"]}])
    pt["units"] = [dict(x) for x in pt["units"]]
    pt["units"][2] = dict(pt["units"][2], tags=["DueCrew::MS2::SLG_12"])
    a2, _e, _t = O.apply(pt, O.check(pt, {"op": "leave_out", "date": "u3", "key": ["tag", "DueCrew::MS2::SLG_12"], "tag": DRUGS}), c)
    check("leave out: on one of the plan's own tags it is exactly the builder's Overlap (its plan tag, but not the other)",
          _u(a2, "u3")["search"] == [f"{B.anki_search('tag', 'DueCrew::MS2::SLG_12')} -{B.anki_search('tag', DRUGS)}"], _u(a2, "u3"))
    a3, _e, _t = O.apply(pt, O.check(pt, {"op": "leave_out", "date": "u2", "key": ["tag", DRUGS], "ptag": "SLG 12"}), c)
    check("leave out: one of the plan's own tags left out, named by its name",
          _u(a3, "u2")["search"] == [f"{B.anki_search('tag', DRUGS)} -{B.anki_search('tag', 'DueCrew::MS2::SLG_12')}"], _u(a3, "u2"))
    wo = B.without_q(SHOCK, [EXTRA])
    d4 = dict(d, units=[dict(x) for x in d["units"]])
    d4["units"][2] = dict(d4["units"][2], tags=[], search=[wo], sn={wo: 6})
    a4, e4, _t = O.apply(d4, O.check(d4, {"op": "leave_out", "date": "u3", "key": ["search", wo], "tag": PEDS}), c)
    check("leave out: a search (a tag without its extras) gets the -tag in its place; its old count goes",
          _u(a4, "u3")["search"] == [f"{wo} -{B.anki_search('tag', PEDS)}"] and "sn" not in _u(a4, "u3")
          and e4[0]["detail"] == "Shock but not Extra, Peds", (_u(a4, "u3"), e4))
    cq = B.cut_q(SHOCK, "DueCrew::MS2::SLG_12")
    d5 = dict(pt, units=[dict(x) for x in pt["units"]])
    d5["units"][2] = dict(d5["units"][2], tags=[], cut=[{"tag": SHOCK, "in": "t1", "q": cq}], search=[cq], sn={cq: 3})
    a5, e5, _t = O.apply(d5, O.check(d5, {"op": "leave_out", "date": "u3", "key": ["cut", SHOCK, "t1"], "tag": PEDS}), c)
    check("leave out: a cut (a whole tag kept to a plan tag) becomes its search with the -tag; the cut goes",
          "cut" not in _u(a5, "u3") and _u(a5, "u3")["search"] == [f"{cq} -{B.anki_search('tag', PEDS)}"]
          and e5[0]["detail"] == "Shock · SLG 12 but not Peds", (_u(a5, "u3"), e5))
    a5b, _e, _t = O.apply(d5, O.check(d5, {"op": "leave_out", "date": "u3", "key": ["search", cq], "tag": PEDS}), c)
    check("leave out: a cut named by its search is the cut (the Worker keeps no cut whose search went)",
          a5b["units"] == a5["units"], _u(a5b, "u3"))
    check("leave out: the tag itself (or one above it) would leave nothing: refused, said",
          _refused({"op": "leave_out", "date": "u3", "key": ["tag", SHOCK], "tag": f"{ROOT}::#Videos::Cardio"}, d, c, "take it off instead"))
    check("leave out: the Worker takes what it writes", all(bool(STORE._plan_doc(x)) for x in (after, a2, a3, a4, a5)))
    check("leave out: picked cards are picked one by one",
          _refused({"op": "leave_out", "date": "u3", "key": ["picks"], "tag": PEDS}, d, c, "Leave them out of which"))
    check("leave out: twice is refused, said",
          _refused({"op": "leave_out", "date": "u3", "key": ["search", q], "tag": PEDS}, after, c, "already"))
    check("leave out: a tag the set doesn't have is refused, said",
          _refused({"op": "leave_out", "date": "u2", "key": ["tag", SHOCK], "tag": PEDS}, d, c, "not on this set"))
    dk = dict(d, units=[dict(x) for x in d["units"]])
    dk["units"][1] = dict(dk["units"][1], decks=["Big Step 1::Cardio Videos"])
    check("leave out: never a subdeck (3.9.6's review): it's read in each follower's own deck, a search as typed",
          _refused({"op": "leave_out", "date": "u2", "key": ["deck", "Big Step 1::Cardio Videos"], "tag": PEDS}, dk, c, "Leave them out of which")
          and _raises(lambda: E.leave_out(dk, "u2", ["deck", "Big Step 1::Cardio Videos"], PEDS), "add its tag instead"))
    orq = f"{B.anki_search('tag', SHOCK)} OR {B.anki_search('tag', DRUGS)}"
    d7 = dict(d, units=[dict(x) for x in d["units"]])
    d7["units"][2] = dict(d7["units"][2], tags=[], search=[orq])
    a7, _e, _t = O.apply(d7, O.check(d7, {"op": "leave_out", "date": "u3", "key": ["search", orq], "tag": PEDS}), c)
    inq = f'{B.anki_search("tag", SHOCK)} "deck:a or b"'
    check("leave out: a search with an OR at its top in brackets, so the -tag holds for all of it (Anki reads A OR B -C as A OR (B -C)); "
          "an OR in quotes or brackets is no top",
          _u(a7, "u3")["search"] == [f"({orq}) -{B.anki_search('tag', PEDS)}"] and E._bracket(inq) == inq
          and E._bracket(f"({orq}) -x") == f"({orq}) -x", _u(a7, "u3"))


def test_move_source_is_the_builders_move_chip():
    """One source from one date to another (moveChip): one op; onto a day
    it finds that day's date or makes one; the one it left goes when
    nothing's left on it, its review days with it."""
    c = ctx()
    d = doc()
    d["units"][1] = dict(d["units"][1], tags=[DRUGS, BOOK])
    d["reviews"] = [{"day": "2026-10-30", "from": "u2", "to": "u3"}]
    a, e, t = O.apply(d, O.check(d, {"op": "move_source", "date": "HF drugs", "key": ["tag", BOOK], "to": "Shock"}), c)
    check("move: a tag goes onto the other date and off this one, both named for what's on them again (renameAll)",
          _u(a, "u2")["tags"] == [DRUGS] and _u(a, "u3")["tags"] == [SHOCK, BOOK] and t == {"u2", "u3"}
          and _u(a, "u3")["name"] == "Shock + 1 more" and _u(a, "u2")["name"] == "HF drugs", (a["units"], t))
    check("move: said, with the line followers get",
          e[0]["verb"] == "Moved" and "to Thu 22 · Shock + 1 more" in e[0]["detail"] and O.why_line(e) == "Book › Cardio › Heart Failure moved to Shock + 1 more.",
          (e, O.why_line(e)))
    a2, e2, t2 = O.apply(d, O.check(d, {"op": "move_source", "date": "u2", "key": ["tag", BOOK], "day": "2026-10-26"}), c)
    new = [u for u in a2["units"] if u["id"] not in {"u1", "u2", "u3"}]
    check("move: onto a day with no date, a date of its own, named as the builder names one",
          len(new) == 1 and new[0]["opens"] == "2026-10-26" and new[0]["tags"] == [BOOK] and new[0]["name"] == "Heart Failure"
          and new[0]["id"] in t2, new)
    a3, _e, _t = O.apply(d, O.check(d, {"op": "move_source", "date": "u2", "key": ["tag", BOOK], "day": "2026-10-22"}), c)
    check("move: onto a day with a date, onto that date (unitOn)", _u(a3, "u3")["tags"] == [SHOCK, BOOK] and len(a3["units"]) == 3)
    a4, e4, _t = O.apply(d, O.check(d, {"op": "move_source", "date": "u3", "key": ["tag", SHOCK], "to": "u2"}), c)
    check("move: the date left with nothing goes (the builder's cleanup), and the review day naming it",
          _u(a4, "u3") is None and "reviews" not in a4 and "so it went" in e4[0]["detail"], (a4.get("reviews"), e4))
    s = dict(d, units=[dict(x) for x in d["units"]])
    s["units"][0] = dict(s["units"][0], search=["tag:X -tag:Y"], sn={"tag:X -tag:Y": 4}, cards=[["g1", 0]], notes=["g2"])
    a5, _e, _t = O.apply(s, O.check(s, {"op": "move_source", "date": "u1", "key": ["search", "tag:X -tag:Y"], "to": "u3"}), c)
    check("move: a search goes with its count", _u(a5, "u3")["search"] == ["tag:X -tag:Y"] and _u(a5, "u3")["sn"] == {"tag:X -tag:Y": 4}
          and "search" not in _u(a5, "u1"), (_u(a5, "u1"), _u(a5, "u3")))
    a6, _e, _t = O.apply(s, O.check(s, {"op": "move_source", "date": "u1", "key": ["picks"], "to": "u3"}), c)
    check("move: picked cards all go together, single cards and notes", _u(a6, "u3")["cards"] == [["g1", 0]]
          and _u(a6, "u3")["notes"] == ["g2"] and not _u(a6, "u1").get("cards") and "notes" not in _u(a6, "u1"), _u(a6, "u3"))
    pt = dict(d, tagroot="MS2", tags=[{"id": "t1", "name": "SLG 12", "notes": ["g1"]}], units=[dict(x) for x in d["units"]])
    cq = B.cut_q(VID, "DueCrew::MS2::SLG_12")
    pt["units"][0] = dict(pt["units"][0], tags=[DRUGS], cut=[{"tag": VID, "in": "t1", "q": cq}], search=[cq], sn={cq: 7})
    a7, _e, _t = O.apply(pt, O.check(pt, {"op": "move_source", "date": "u1", "key": ["cut", VID, "t1"], "to": "u3"}), c)
    check("move: a cut goes with its search and count", _u(a7, "u3")["cut"] == [{"tag": VID, "in": "t1", "q": cq}]
          and _u(a7, "u3")["search"] == [cq] and _u(a7, "u3")["sn"] == {cq: 7}
          and "cut" not in _u(a7, "u1") and "search" not in _u(a7, "u1"), (_u(a7, "u1"), _u(a7, "u3")))
    a7b, _e, _t = O.apply(pt, O.check(pt, {"op": "move_source", "date": "u1", "key": ["search", cq], "to": "u3"}), c)
    check("move: a cut named by its search moves as the cut", a7b["units"] == a7["units"], _u(a7b, "u3"))
    check("move: the Worker takes what a move leaves", bool(STORE._plan_doc(a7)) and bool(STORE._plan_doc(a4)) and bool(STORE._plan_doc(a6)))
    pt["units"][2] = dict(pt["units"][2], tags=[SHOCK, VID])
    a8, _e, _t = O.apply(pt, O.check(pt, {"op": "move_source", "date": "u1", "key": ["cut", VID, "t1"], "to": "u3"}), c)
    check("move: a cut onto a date with all of its tag just goes (moveChip's has)", "cut" not in _u(a8, "u3")
          and "search" not in _u(a8, "u3") and "cut" not in _u(a8, "u1"), _u(a8, "u3"))
    check("move: onto its own set or day is refused, said",
          _refused({"op": "move_source", "date": "u3", "key": ["tag", SHOCK], "day": "2026-10-22"}, d, c, "on that day already")
          and _refused({"op": "move_source", "date": "u3", "key": ["tag", SHOCK], "to": "u3"}, d, c, "on that set already"))
    check("move: somewhere is needed", _refused({"op": "move_source", "date": "u3", "key": ["tag", SHOCK]}, d, c, "Move them where"))
    dr = D.Draft("p1", d, 1)
    dr.add({"op": "move_source", "date": "u2", "key": ["tag", BOOK], "day": "2026-10-26"}, c)
    check("move: in a draft, the new date's id replays the same", dr.doc(c) == D.Draft.from_json("p1", json.loads(json.dumps(dr.to_json()))).doc(c))


def test_a_lesson_straight_from_a_tag():
    """A lesson from a tag on a day or the next free study day (the
    builder's + on a tag: after the plan's last day), named as the builder
    names it; of its own, or onto the day's date (unitOn)."""
    d, c = doc(), ctx()
    o = O.check(d, {"op": "add_date", "day": "next", "tags": [BOOK], "today": TODAY})
    check("lesson from a tag: next is the first study day after the plan's last day, worked out once",
          o["day"] == "2026-10-23", o)
    d2 = dict(d, units=[dict(x) for x in d["units"]])
    d2["units"][2] = dict(d2["units"][2], due="2026-10-30", even=True)
    check("lesson from a tag: after an even date's due date, on a study day (the weekend skipped)",
          O.check(d2, {"op": "add_date", "day": "next", "tags": [BOOK], "today": TODAY})["day"] == "2026-11-02")
    check("lesson from a tag: a plan with no dates starts on its start (next Monday)",
          O.check({"deck": "x", "units": []}, {"op": "add_date", "day": "next", "tags": [BOOK], "today": TODAY})["day"] == "2026-10-26")
    a, e, t = O.apply(d, o, c)
    new = [u for u in a["units"] if u["id"] in t]
    check("lesson from a tag: a date of its own, named as the builder names it", len(new) == 1 and new[0]["name"] == "Heart Failure"
          and new[0]["tags"] == [BOOK], new)
    t2 = B.Tree([(f"{ROOT}::#Book::Cardio", 20), (BOOK, 6)], [])
    dd = dict(d, units=d["units"] + [{"id": "u9", "name": "HF book", "opens": "2026-10-26", "tags": [BOOK]}])
    a2, _e, t3 = O.apply(dd, O.check(dd, {"op": "add_date", "day": "2026-10-27", "tags": [f"{ROOT}::#Book::Cardio"]}),
                         O.Ctx(t2, TODAY, "MS2", [1] * 7))
    check("lesson from a tag: a tag with a part on another date is named for the rest of it (label's · the rest)",
          [u["name"] for u in a2["units"] if u["id"] in t3] == ["Cardio · the rest"], [u["name"] for u in a2["units"] if u["id"] in t3])
    a3, _e, t4 = O.apply(d, O.check(d, {"op": "add_date", "day": "2026-10-22", "tags": [BOOK], "join": True}), c)
    check("lesson from a tag: join puts it on that day's date (the builder's drop on a day)",
          t4 == {"u3"} and _u(a3, "u3")["tags"] == [SHOCK, BOOK] and len(a3["units"]) == 3, a3["units"])
    a4, _e, _t = O.apply(d, O.check(d, {"op": "add_date", "day": "2026-10-22", "tags": [BOOK]}), c)
    check("lesson from a tag: without join, two dates on one day (Anki keeps both)", sum(u["opens"] == "2026-10-22" for u in a4["units"]) == 2)


def test_events_are_one_kind():
    """A quiz or exam and "Make it an event" (a lecture, any named day) are
    the same in the doc: {id, day, name}. The Worker takes nothing more."""
    d = doc()
    a, _e, _t = O.apply(d, O.check(d, {"op": "add_event", "day": "2026-10-27", "name": "Lecture 12"}), ctx())
    ev = next(e for e in a["events"] if e["name"] == "Lecture 12")
    check("events: any named day is an event as the builder's addEvent makes it", set(ev) == {"id", "day", "name"}, ev)
    try:
        STORE._plan_doc(dict(a, events=[dict(ev, kind="day")]))
        check("events: the Worker refuses a kind on an event", False)
    except Exception:
        check("events: the Worker refuses a kind on an event (so there's none to keep)", True)


def test_lay_out_up_to_any_event():
    """The builder's pace "or an event…" › Fill up to it: what's ticked fits
    by the day before that event, the new dates prep for it; the plan's
    own end stays."""
    d, c = doc(), ctx()
    d["events"].append({"id": "e2", "day": "2026-11-06", "name": "Cardio quiz 2"})
    d["end"] = "2026-12-18"
    cover = [f"tag:{ROOT}::#Videos::Cardio::Arrhythmias"]
    o = O.check(d, {"op": "lay_out", "pace": {"mode": "end", "days": [1, 1, 1, 1, 1, 0, 0], "daily": 20},
                    "cover": cover, "upto": "Cardio quiz 2", "start": "2026-10-19"})
    a, e, t = O.apply(d, o, c)
    new = [u for u in a["units"] if u["id"] in t]
    check("lay out up to an event: before it, and every new date for it",
          new and all(str(u.get("due") or u["opens"]) <= "2026-11-05" for u in new) and all(u.get("for") == "e2" for u in new), new)
    check("lay out up to an event: the plan's end stays the exam it ends with", a["end"] == "2026-12-18" and a["pace"]["mode"] == "end")
    want = copy.deepcopy(d)
    want["end"] = "2026-11-05"
    r = B.lay_out(want, c.tree, {"mode": "end", "days": [1, 1, 1, 1, 1, 0, 0], "daily": 20}, set(cover), "2026-10-19", TODAY,
                  iter(f"x{i}" for i in range(99)).__next__, aim="e2")
    site = [(u["opens"], u.get("due"), u.get("tags"), u.get("for")) for u in want["units"] if u["id"] in r["touched"]]
    check("lay out up to an event: the same dates as the builder's Fill with its end the day before",
          [(u["opens"], u.get("due"), u.get("tags"), u.get("for")) for u in new] == site, (new, site))
    try:
        O.apply(d, O.check(d, dict(o, upto="Cardio quiz 1")), c)
        check("lay out up to an event already passed by the dates", False)
    except E.Refused as x:
        check("lay out up to an event the dates run past: nothing fits, said", "before a later quiz or exam" in str(x), str(x))


def test_give_the_class_a_day():
    """classHints' Give the class a day, as one click: every date still to
    come a study day later (the plan's own study days), the review days
    after today too; quizzes stay."""
    d, c = doc(), ctx()
    d["reviews"] = [{"day": "2026-10-23", "from": "u1", "to": "u3"}, {"day": "2026-10-19", "from": "u1", "to": "u1"}]
    d["units"][2] = dict(d["units"][2], due="2026-10-23")
    o = O.check(d, {"op": "breather"})
    check("breather: one click, today and the plan's own study days kept with it",
          o["today"] == datetime.date.today().isoformat() and o["days"] == [1, 1, 1, 1, 1, 0, 0], o)
    a, e, _t = O.apply(d, dict(o, today=TODAY), c)
    check("breather: the dates still to come a study day later, their finish-by days with them",
          _u(a, "u3")["opens"] == "2026-10-23" and _u(a, "u3")["due"] == "2026-10-24"
          and _u(a, "u2")["opens"] == "2026-10-20" and _u(a, "u1")["opens"] == "2026-10-19", a["units"])
    check("breather: review days after today move a study day too (Fri to Mon); earlier ones and quizzes stay",
          sorted(r["day"] for r in a["reviews"]) == ["2026-10-19", "2026-10-26"] and a["events"] == d["events"], (a["reviews"], a["events"]))
    week = dict(d, pace=dict(d["pace"], days=[1] * 7))
    check("breather: on a plan studied every day, a day later is the next day",
          O.check(week, {"op": "breather"})["days"] == [1] * 7)
    check("breather: said", e[0]["verb"] == "Moved" and "a study day later" in e[0]["detail"], e)


def main():
    names = [n for n in list(globals()) if n.startswith("test_")]
    for n in names:
        globals()[n]()
    bad = [c for c in CHECKS if not c[1]]
    print(f"\n{len(CHECKS) - len(bad)}/{len(CHECKS)} checks passed")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()

