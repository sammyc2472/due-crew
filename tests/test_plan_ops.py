"""Round five's plan changes (due_crew/planner: ops.py, draft.py, view.py,
edits.new_plan_doc; docs/planner.md): every change an op, said in words,
waiting under the plan till it's sent, replayed on a co-author's save; the
Plan tab's arithmetic (each week's asks, the shape line, suggestions read
through an index); a send's line kept by the fake Worker as the Worker
keeps it. Standard library only.

Run: python3 tests/test_plan_ops.py
"""

import copy
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
    for ref, words in (("Renal", "No date on the plan is Renal."), ("", "Which date?")):
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
        check("ops: the last thing on a date doesn't come off", False)
    except E.Refused as e:
        check("ops: the last thing on a date doesn't come off (delete the date instead)", "delete the date" in str(e), str(e))
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
    check("ops: lay_out said: Laid out, how many new dates", entries[0]["verb"] == "Laid out", entries)
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


def main():
    names = [n for n in list(globals()) if n.startswith("test_")]
    for n in names:
        globals()[n]()
    bad = [c for c in CHECKS if not c[1]]
    print(f"\n{len(CHECKS) - len(bad)}/{len(CHECKS)} checks passed")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()

