"""Plans, end to end: the board's You › Plans tab. The whole plan as a path
above the week (plans.path, path_end, board._plan_path), what's behind as
one line with Behind… (plans.behind_of, behind_sheet, board._plan_behind,
plan_board.behind and its three ways: Slide, Fit it in, Skip what's
left), the head's "lesson N of M", and the empty tab (a plan's code or
link with Follow, my exam with Plan the way there, Make a plan; plans.
exam_way, link_code). Each new duecrew: command goes through _on_js as
the board sends it. Standard library only; node for the sheet, when it's
there.

Run: python3 tests/test_plan_board.py
"""

import datetime
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import types
from urllib.parse import quote

HARNESS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HARNESS)
sys.path.insert(0, HARNESS)

import fakes  # noqa: E402

fakes.install_fake_requests(fakes.FakeWorker())
fakes.install_fake_aqt()
sys.path.insert(0, REPO)

from due_crew import board  # noqa: E402
from due_crew import plans as P  # noqa: E402
from due_crew.backend import api  # noqa: E402

CHECKS = []
TODAY = datetime.date(2026, 11, 5)  # a Thursday, as the design's frame 16


def check(name, cond, detail=""):
    CHECKS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond or detail == "" else f"\n     {detail}"))


def day(n):
    return (TODAY + datetime.timedelta(days=n)).isoformat()


def as_board(message):
    """A message as the Decks page sends it: with the board's key."""
    return message + "|" + board.BOARD_KEY


def _view(js):
    """The sheet's words, as sheet_js put them in its script."""
    return json.loads(re.search(r"var V = (\{.*?\});\n", js).group(1).replace("<\\/", "</"))


# a plan as frame 16 has it: lesson 1 done, 2 behind, 3 today, more ahead, the exam at its end
DOC = {"units": [{"id": "l1", "name": "1 · Cell injury", "opens": day(-3)},
                 {"id": "l2", "name": "2 · Inflammation <b>", "opens": day(-1)},
                 {"id": "l3", "name": "3 · Neoplasia", "opens": day(0)},
                 {"id": "l4", "name": "4 · Heme", "opens": day(1), "due": day(2)},
                 {"id": "l5", "name": "5 · Renal", "opens": day(4)}],
       "events": [{"id": "q", "day": day(2), "name": "Heme quiz"}, {"id": "x", "day": day(43), "name": "Exam"}]}
PROG = {"l1": [40, 40, 40], "l2": [53, 22, 53], "l3": [84, 0, 84]}
APPLIED = {"l1": "s", "l2": "s", "l3": "s"}


# ---- pure: the path ----

def test_path():
    p = P.path(DOC, PROG, day(0), applied=APPLIED)
    states = [x["state"] for x in p["lessons"]]
    check("path: a lesson each, in the plan's order: done, behind, today, ahead",
          states == ["done", "behind", "now", "ahead", "ahead"] and [x["uid"] for x in p["lessons"]] == ["l1", "l2", "l3", "l4", "l5"], states)
    check("path: set 3 of 5; its first day and its end, the last exam (events never move)",
          p["at"] == 3 and p["of"] == 5 and p["first"] == day(-3)
          and p["end"] == {"name": "Exam", "day": day(43), "event": True}, (p["at"], p["of"], p["first"], p["end"]))
    l2 = p["lessons"][1]
    check("path: a lesson behind has what's left of it; today's is marked today", l2["left"] == 31 and p["lessons"][2]["today"]
          and not l2["today"] and l2["name"] == "2 · Inflammation <b>", l2)
    slid = P.path(DOC, PROG, day(0), applied=APPLIED, shift=1)
    check("path: on my days: a day later, set 2 is today's, nothing behind, set 2 of 5",
          [x["state"] for x in slid["lessons"]][:3] == ["done", "now", "ahead"] and slid["at"] == 2
          and slid["first"] == day(-2) and slid["end"]["day"] == day(43) and P.behind_of(slid, day(0)) is None, slid["lessons"][:3])
    skip = P.path(DOC, PROG, day(0), applied=APPLIED, skipped=["l2"])
    check("path: a skipped set stays in its place, skipped, and isn't behind; still set 3 of 5",
          skip["lessons"][1]["state"] == "skip" and skip["at"] == 3 and skip["of"] == 5 and P.behind_of(skip, day(0)) is None)
    late = P.path(DOC, PROG, day(0), applied={"l1": "s", "l3": "s"})
    gone = P.path(DOC, PROG, day(0), applied={"l1": "s", "l2": "skip:s", "l3": "s"})
    check("path: passed before it opened here (followed after it, or skipped at the join): not mine to be behind on, as Due's Behind",
          late["lessons"][1]["state"] == "skip" and gone["lessons"][1]["state"] == "skip")
    check("path: without what opened here, every passed lesson counts as opened",
          P.path(DOC, PROG, day(0))["lessons"][1]["state"] == "behind")
    empty = P.path(DOC, {"l2": [53, 22, 53]}, day(0), applied=APPLIED)
    check("path: nothing of a lesson here, done once its day passed; today's and ahead by their days",
          [x["state"] for x in empty["lessons"]] == ["done", "behind", "now", "ahead", "ahead"])
    moved = P.path(DOC, PROG, day(0), applied=APPLIED, moved={"l3": 2})
    check("path: a lesson I moved is on its own day; with none today, the last that opened is where I am",
          moved["lessons"][2]["state"] == "ahead" and moved["lessons"][2]["opens"] == day(2) and moved["at"] == 2)
    check("path: before the first lesson, lesson 0 (the head says when it starts)",
          P.path(DOC, {}, day(-5))["at"] == 0)
    even = {"units": [{"id": "e", "name": "Even", "opens": day(-5), "due": day(-1), "even": True},
                      {"id": "w", "name": "Window", "opens": day(-2), "due": day(2)}]}
    ep = P.path(even, {"e": [10, 4, 20], "w": [5, 1, 9]}, day(0), applied={})
    check("path: a lesson in slices, its days over and cards left, is behind though not applied; one in its days is today's",
          [x["state"] for x in ep["lessons"]] == ["behind", "now"] and ep["at"] == 2, ep["lessons"])
    check("path: its end is its quiz or exam; else 3.2's exam; else its end or last lesson's day, no diamond",
          P.path_end({"units": DOC["units"], "exam": {"date": day(50), "target": 90}}) == {"name": "Exam", "day": day(50), "event": True}
          and P.path_end({"units": DOC["units"]}) == {"name": "", "day": day(4), "event": False}
          and P.path_end({"units": DOC["units"], "end": day(9)})["day"] == day(9) and P.path_end({"units": []}) is None)
    check("last day: lessons, events and its end; a lean doc (a plan I write) by its lessons' days",
          P.last_day(DOC) == day(43) and P.last_day({"units": [{"id": "a", "opens": day(10)}]}) == day(10) and P.last_day({}) == "")


def test_behind():
    p = P.path(DOC, PROG, day(0), applied=APPLIED)
    b = P.behind_of(p, day(0))
    check("behind: the lesson, what's left, a day behind",
          b == {"uid": "l2", "name": "2 · Inflammation <b>", "more": 0, "left": 31, "uids": ["l2"], "since": day(-1), "days": 1}, b)
    two = P.behind_of(P.path(DOC, dict(PROG, l1=[40, 30, 40]), day(0), applied=APPLIED), day(0))
    check("behind: two lessons: the first named, one more, all they have left, since the earliest's day",
          two["name"] == "1 · Cell injury" and two["more"] == 1 and two["left"] == 41 and two["uids"] == ["l1", "l2"]
          and two["days"] == 3, two)
    s = P.behind_sheet("Path Book", b, p, 31)
    keys = [(w["key"], w["label"], w["yes"]) for w in s["ways"]]
    check("sheet: titled a day behind on the plan; what's left and what today opened",
          s["title"] == "A day behind on Path Book" and s["text"] == "2 · Inflammation <b> has 31 left; today 3 · Neoplasia opened 84.", s)
    check("sheet: Slide a day, Fit it in… (over the days I pick), Skip what's left; each button its own word",
          keys == [("slide", "Slide a day", "Slide a day"), ("fit", "Fit it in…", "Fit it in…"),
                   ("skip", "Skip what's left", "Skip it")], keys)
    notes = [w["note"] for w in s["ways"]]
    check("sheet: each way says what it does, in a line",
          notes == ["Everything still to come, a day later. Ends Tue 10 Nov.",
                    "Over the days you pick: about 11 more new cards a day for three days.", "The 31 left stay open in your deck, no longer behind."], notes)
    check("sheet: Slide is the days behind, Fit it in what's waiting, Skip the lessons behind",
          s["ways"][0]["days"] == 1 and (s["ways"][1]["waiting"], s["ways"][1]["extra"]) == (31, 11) and s["ways"][2]["uids"] == ["l2"])
    check("sheet: nothing opened and unseen, no Fit it in", [w["key"] for w in P.behind_sheet("X", b, p, 0)["ways"]] == ["slide", "skip"])
    check("Fit it in…'s box: the days typed, 2 to 14; not a number, none",
          [P.fit_days(x) for x in ("5", " 10 days", "1", "40", "", "soon")] == [5, 10, 2, 14, None, None]
          and P.fit_extra(31, 5) == 7)
    pt = P.path(DOC, dict(PROG, l1=[40, 30, 40]), day(0), applied=APPLIED)
    s3 = P.behind_sheet("Path Book", two, pt, 41, shift=363)
    check("sheet: three days behind, two lessons; a slide keeps my dates within 365 days of the plan's",
          s3["title"] == "3 days behind on Path Book" and s3["text"].startswith("1 · Cell injury and 1 more have 41 left")
          and s3["ways"][0]["label"] == "Slide 2 days" and s3["ways"][-1]["yes"] == "Skip them"
          and "slide" not in [w["key"] for w in P.behind_sheet("X", two, pt, 41, shift=365)["ways"]], s3)
    close = dict(DOC, events=[{"id": "x", "day": day(4), "name": "Block exam"}])
    pc = P.path(close, PROG, day(0), applied=APPLIED)
    check("sheet: a slide that ends after the exam says so",
          P.behind_sheet("X", P.behind_of(pc, day(0)), pc, 31)["ways"][0]["note"].endswith("Ends Tue 10 Nov, after Block exam."))
    p0 = P.path(DOC, dict(PROG, l3=[0, 0, 84]), day(0), applied={"l1": "s", "l2": "s"})
    check("sheet: today's lesson not opened yet says what it opens",
          P.behind_sheet("X", P.behind_of(p0, day(0)), p0, 31)["text"].endswith("today 3 · Neoplasia opens 84."))


def test_exam_and_code():
    check("exam: ahead, with how many days", P.exam_way(day(43), day(0)) == {"day": day(43), "days": 43})
    check("exam: today, passed, none or junk: no line",
          all(P.exam_way(x, day(0)) is None for x in (day(0), day(-3), "", "soon", None)))
    check("exam: a plan I follow or write that ends by it (from today to the exam): no line",
          P.exam_way(day(43), day(0), [day(43)]) is None and P.exam_way(day(43), day(0), [day(10)]) is None)
    check("exam: one that ends after it, or ended already, doesn't count",
          P.exam_way(day(43), day(0), [day(50), day(-5), ""]) == {"day": day(43), "days": 43})
    codes = [P.link_code(x) for x in ("N4AP ULM2", "n4ap-ulm2", "https://duecrew.com/p/N4APULM2", "duecrew.com/p/n4apulm2/",
                                      "https://duecrew.com/p/N4APULM2?ref=crew#top", "", "   ", "/", None)]
    check("code: typed or spaced, or a link's last part (a query and a fragment aside); nothing, ''",
          codes == ["N4APULM2"] * 5 + [""] * 4, codes)


# ---- the board ----

def _card(**kw):
    p = P.path(DOC, PROG, day(0), applied=APPLIED)
    wk = P.week_view({"units": DOC["units"], "events": DOC["events"]}, PROG, day(0), P.week_start(day(0)))
    return dict({"id": "p1", "title": "Path Book <i> · Dre’s plan", "name": "Path Book", "sub": "set 3 of 5 · 6 following",
                 "rows": [], "lines": [], "change": None, "no_deck": False, "paused": False, "waiting": 31,
                 "aside": [0, 0, 0], "aside_ok": [0, 0], "week": wk, "week_offset": 0,
                 "status": {"togo": 84, "behind": 31, "since": "Wednesday"}, "path": p, "behind": P.behind_of(p, day(0)),
                 "tabs": {}}, **kw)


def test_card():
    h = board._plan_card_html(_card())
    path = h.split('<div class="ppath')[1].split("</div>")[0]
    check("card: the head says set 3 of 5", "set 3 of 5 · 6 following" in h)
    check("card: the path, a segment a lesson: done, behind, today, ahead; the exam a diamond at its end",
          re.findall(r'<i class="([a-z ]+)"', path) == ["d", "b", "t", "a", "a"] and path.count("<em ") == 1
          and path.index("<em ") > path.rindex("<i "), path)
    check("card: under it the first lesson's day, and the exam by name and day",
          '<div class="ppl"><span>Mon 2 Nov</span><span>Exam &middot; Fri 18 Dec</span></div>' in h)
    check("card: each segment says its set on a hover, the names escaped; the path read out in words",
          'title="2 · Inflammation &lt;b&gt; &middot; 31 left"' in path and 'title="3 · Neoplasia &middot; today &middot; 84 to go"' in path
          # 3.9.9: a group of buttons to the keyboard (one Tab stop, the arrows walk it), each set named for a screen reader
          and 'role="group" aria-label="Sets: 1 done, 1 behind, 1 today, 2 to come, then Exam on Fri 18 Dec. Arrow keys move along them."' in h
          and 'aria-label="3 · Neoplasia, today, 84 to go"' in path and path.count(' tabindex="0" data-rove="1"') == 1
          and "<b>" not in path, path)
    jumps = re.findall(r"duecrew:planjump:p1:(\d{4}-\d{2}-\d{2})\|", path)
    check("card: each segment's click opens the day it opens in the week below (3.9.6, after the last check)",
          len(jumps) == path.count("<i ") and jumps == sorted(jumps) and jumps, jumps)
    order = [h.index(x) for x in ('class="pk"', 'class="ppath', 'class="ppl"', '<b>84</b> to go today', 'class="pst pbh"', 'class="pwk"')]
    check("card: the path above the day's line, then Behind, then the week (round five's, kept)", order == sorted(order), order)
    check("card: behind is one line, with Behind… (not Catch up…); the waiting note goes",
          '<span class="late">Behind &middot; 2 · Inflammation &lt;b&gt;, 31 left</span>' in h and h.count("duecrew:planbehind:p1|") == 1
          and "plancatch" not in h and "new from earlier days waiting" not in h, h[:1500])
    check("card: no raw markup from the author's names",
          "Inflammation <b>" not in h and "Path Book <i>" not in h and "Inflammation &lt;b&gt;" in h)
    caught = board._plan_card_html(_card(catch={"extra": 11, "until": "Sun"}))
    check("card: a catch-up running: no Behind line, and the path calls it catching up, not behind",
          "planbehind" not in caught and '<i class="c" title="2 · Inflammation &lt;b&gt; &middot; catching up &middot; 31 left"' in caught
          and "1 catching up" in caught and "behind" not in caught.split('class="ppath')[1].split("</div>")[0])
    asked = board._plan_card_html(_card(session={"kind": "study", "ask": {"days": [day(-1)], "waiting": 31, "spread": 11, "push": 1}}))
    check("card: 3.2's missed-days question up (its own three ways): no Behind line as well",
          "planbehind" not in asked and "planspread:p1" in asked)
    done = board._plan_card_html(_card(path=P.path(DOC, dict(PROG, l2=[53, 53, 53], l3=[84, 84, 84]), day(0), applied=APPLIED),
                                       behind=None, status={"togo": 0, "behind": 0}))
    check("card: today's lesson done is filled and still marked; nothing behind, no line",
          '<i class="d t"' in done and "planbehind" not in done and 'class="pst' not in done)
    check("card: no path without one (paused, at my own pace, no deck: plan_flow leaves it out)",
          'class="ppath' not in board._plan_card_html(_card(path=None, behind=None)))
    big = [{"uid": f"u{i}", "name": f"L{i}", "opens": day(i), "day": day(i), "state": "ahead", "left": 0, "today": False}
           for i in range(150)]
    long = board._plan_card_html(_card(path={"lessons": big, "first": day(0), "end": {"name": "", "day": day(149), "event": False}}))
    mid = board._plan_card_html(_card(path={"lessons": big[:45], "first": day(0), "end": None}))
    check("card: a long plan folds what's far ahead (3.9.6, Sam's pick A); with no quiz or exam, no diamond and its last day",
          'class="ppath fold"' in long and "<span>145 to come</span>" in long and "<span>40 to come</span>" in mid
          and "<em " not in long and f"<span>Ends {board._ins_dname(day(149), long=True)}</span>" in long, long[:600])
    two = board._plans_html({"cards": [_card(), _card(id="p2", name="Micro", title="Micro · Kim’s plan", behind=None,
                                                    status={"togo": 3, "behind": 0})]}, None, {})
    check("card: two plans, the switch's dot on the one behind (its Behind line's count)",
          two.count('class="dot"') == 1 and 'title="31 behind"' in two)



def test_long_path_folds_v396():
    """3.9.6 (Sam: "if a plan is long, then this kinda seems overwhelming";
    his pick A, past 16 sets): a long path shows one by one what needs me
    (every set behind, the two before today's, today's, the next four, and a
    set a joy plays on) and folds each run of the rest, done, to come or
    skipped, into one piece with its count under it; a click on a fold opens
    its nearest set's day. 16 sets or fewer: a segment a set, as ever."""
    def lessons(states):
        return [{"uid": f"u{i}", "name": f"{i + 1} · Set", "opens": day(i - 38), "state": st, "left": 3 if st == "behind" else 0,
                 "today": st == "now"} for i, st in enumerate(states)]
    states = ["done"] * 22 + ["behind"] * 7 + ["done"] * 5 + ["behind"] * 3 + ["done", "now", "ahead"]
    card = _card(path={"lessons": lessons(states), "at": 39, "of": 40, "first": day(-38), "end": {}}, behind=None)
    h = board._plan_card_html(card)
    path = h.split('<div class="ppath')[1].split("</div>")[0]
    pieces = re.findall(r'<i class="([a-z ]+)"', path)
    check("long: 40 sets, one piece each for what needs me; the runs done fold, their counts under them",
          pieces == ["run d"] + ["b"] * 7 + ["run d"] + ["b"] * 3 + ["d", "t", "a"]
          and "<span>22 done</span>" in path and "<span>5 done</span>" in path and 'class="ppath fold' in h, pieces)
    check("long: a fold says its first and last set, and its click opens the last done set's day",
          'title="1 · Set to 22 · Set &middot; 22 done"' in path and f"planjump:p1:{day(-38 + 21)}|" in path, path[:400])
    check("long: the path still reads out every set's state", "Sets: 28 done, 10 behind, 1 today, 1 to come" in h, h[:200])
    far = ["done"] * 3 + ["now"] + ["ahead"] * 30
    path = board._plan_card_html(_card(path={"lessons": lessons(far), "at": 4, "of": 34, "first": day(-38), "end": {}},
                                       behind=None)).split('<div class="ppath')[1].split("</div>")[0]
    pieces = re.findall(r'<i class="([a-z ]+)"', path)
    check("long: early on, the sets far ahead fold into what's to come, at the end, its count under its right edge",
          pieces == ["d"] * 3 + ["t"] + ["a"] * 4 + ["run a rl"] and "<span>26 to come</span>" in path, pieces)
    joy = {"pop": {"uid": "u5", "ago": 0.5}}
    pieces = re.findall(r'<i class="([a-z ]+)"', board._plan_card_html(_card(
        path={"lessons": lessons(states), "at": 39, "of": 40, "first": day(-38), "end": {}}, behind=None, joy=joy)).split('<div class="ppath')[1].split("</div>")[0])
    check("long: a set a joy plays on stays its own (Pip hops onto it from the fold before)",
          pieces[:3] == ["run d", "d", "run d"], pieces[:4])
    short = board._plan_card_html(_card(path={"lessons": lessons(["done"] * 15 + ["now"]), "at": 16, "of": 16, "first": day(-38),
                                              "end": {}}, behind=None))
    check("long: 16 sets or fewer, a segment a set", "run" not in short.split('<div class="ppath')[1].split("</div>")[0]
          and 'class="ppath fold' not in short)

def test_empty_tab():
    none = board._plans_empty_html({"cards": []})
    check("empty: a box for a plan's code or link, with Follow; what's typed goes encoded with the board's key",
          'id="dc-plancode" placeholder="A plan&rsquo;s code or link"' in none and ">Follow</a>" in none
          and "pycmd('duecrew:planfollowcode:'+encodeURIComponent(v)+'|'+window.dcBK)" in none
          and "if(event.key==='Enter')" in none and "addcode" not in none, none)
    check("empty: Make a plan and the library; no exam line without one; Your plans… only for someone who writes one",
          "duecrew:planopennew|" in none and "Make a plan</a>" in none and "duecrew:planlibrary|" in none
          and "Your exam" not in none and "planyours" not in none
          and "duecrew:planyours|" in board._plans_empty_html({"cards": [], "writes": True}))
    ex = board._plans_empty_html({"cards": [], "exam": {"day": "2026-12-18", "days": 43}})
    check("empty: my exam ahead, in days, with Plan the way there (a new plan finishing by it)",
          "Your exam: <b>Fri 18 Dec</b>, in 43 days" in ex and "duecrew:planopennew:2026-12-18|" in ex
          and ex.index("Your exam") < ex.index("Make a plan"), ex)
    check("empty: tomorrow's says tomorrow",
          "Your exam: <b>Fri 6 Nov</b>, tomorrow" in board._plans_empty_html({"cards": [], "exam": {"day": day(1), "days": 1}}))
    page = board.render({"entries": [], "labels": [day(0)], "tomorrow": "", "pending": []}, {"period": "today"}, 0,
                        plans={"cards": []}, you={"tab": "plans", "plans": {"cards": [], "exam": {"day": day(43), "days": 43}}})
    check("empty: on the board's You › Plans, in the board's own look (left-aligned, the tokens)",
          "Your exam: <b>Fri 18 Dec</b>" in page and "#due-crew .dc-pc, #due-crew .dc-pways { text-align: left; }" in page
          and "#due-crew .dc-pways .pwl {" in page and "#due-crew .ppath {" in page)


def test_sheet_board():
    view = {"id": "s1", "title": "A day behind on Path <Book>", "text": "x", "yes": "Slide a day", "no": "Not now",
            "field": {"kind": "pick", "items": ["Slide a day", "Fit it in", "Skip what's left"], "at": 0,
                      "notes": ["Everything still to come.", "About 11 more."], "go": ["Slide a day", "Fit it in", "Skip it"]}}
    v = _view(board.sheet_js(view))
    check("sheet: a pick's quiet lines and its button's words go with it, one each (missing ones empty)",
          v["field"]["notes"] == ["Everything still to come.", "About 11 more.", ""] and v["field"]["go"] == ["Slide a day", "Fit it in", "Skip it"]
          and v["no"] == "Not now" and v["title"] == "A day behind on Path <Book>")
    plain = _view(board.sheet_js({"id": "s2", "title": "t", "field": {"kind": "pick", "items": ["a", "b"]}}))
    check("sheet: a pick without them is as it was", plain["field"] == {"kind": "pick", "items": ["a", "b"], "at": 0})
    node = shutil.which("node")
    if not node:
        print("SKIP the sheet in node: no node")
        return
    dom = r"""
    function El(tag) { this.tagName = tag; this.style = {}; this.kids = []; this.l = {}; this.attrs = {}; this.value = '';
                       this.offsetTop = 0; this.offsetHeight = 10; this.scrollTop = 0; this.clientHeight = 100; }
    El.prototype.appendChild = function (k) { this.kids.push(k); k.parentNode = this; return k; };
    El.prototype.addEventListener = function (t, f) { this.l[t] = f; };
    El.prototype.setAttribute = function (a, v) { this.attrs[a] = String(v); };
    El.prototype.removeAttribute = function (a) { delete this.attrs[a]; };
    El.prototype.focus = function () {};
    El.prototype.remove = function () {};
    var sent = [], body = new El('body');
    function find(n, id) { if (n.id === id) return n; for (var k of n.kids) { var f = find(k, id); if (f) return f; } return null; }
    function all(n, out) { out = out || []; out.push(n); n.kids.forEach((k) => all(k, out)); return out; }
    var document = { body: body, createElement: (t) => new El(t), getElementById: (id) => find(body, id),
                     addEventListener: () => {}, removeEventListener: () => {} };
    var window = { dcBK: 'KEY', matchMedia: () => ({ matches: true }) };
    function getComputedStyle() { return null; }
    function pycmd(c) { sent.push(decodeURIComponent(c)); }
    var opts = () => all(body).filter((e) => e.attrs.role === 'option');
    var go = () => all(body).find((e) => e.tagName === 'button' && e.className === 'go');
    """
    then = r"""
    var rows = opts(), first = go().textContent;
    var shape = rows.map((b) => b.kids.map((k) => k.className + ':' + k.textContent).join('|'));
    var cls = all(body).find((e) => e.attrs.role === 'listbox').className;
    rows[2].l.click();
    var after = go().textContent;
    go().l.click();
    console.log(JSON.stringify([first, after, shape, cls, sent]));
    """
    r = subprocess.run([node, "-e", dom + board.sheet_js(view) + "\n" + then], capture_output=True, text=True, timeout=60)
    try:
        got = json.loads(r.stdout)
    except ValueError:
        got = r.stdout + r.stderr[-1500:]
    check("sheet in node: each way its name and its quiet line; the button says the pick; the answer is the pick",
          isinstance(got, list) and got[0] == "Slide a day" and got[1] == "Skip it"
          and got[2] == ["nm:Slide a day|nt:Everything still to come.", "nm:Fit it in|nt:About 11 more.", "nm:Skip what's left"]
          and got[3] == "ls nts" and got[4] == ['duecrew:sheet:s1:{"ok":true,"at":2}|KEY'], got)


# ---- the glue: a plan followed, its card, and the clicks ----

def _col():
    """Step 1 (10): lesson 1's two cards seen, lesson 2's three new, lesson 3's one; all opened by the plan."""
    conn = sqlite3.connect(":memory:")
    fakes.make_collection(conn)
    for cid, tag, seen in ((1, "L1", True), (2, "L1", True), (3, "L2", False), (4, "L2", False), (5, "L2", False),
                           (6, "L3", False), (7, "L4", False)):
        fakes.add_card(conn, cid, did=10, ctype=2 if seen else 0, queue=2 if seen else -1, tags=f"Step1::{tag}")
    col = fakes.FakeCol(conn, fakes.day_cutoff_for(TODAY))
    col.decks = fakes.FakeDecks({10: "Step 1"})
    return col


UNITS = [{"id": "l1", "name": "1 · Cell injury", "opens": day(-3), "tags": ["Step1::L1"]},
         {"id": "l2", "name": "2 · Inflammation", "opens": day(-1), "tags": ["Step1::L2"]},
         {"id": "l3", "name": "3 · Neoplasia", "opens": day(0), "tags": ["Step1::L3"]},
         {"id": "l4", "name": "4 · Heme", "opens": day(3), "tags": ["Step1::L4"]}]


class Glue:
    """plan_flow pointed at a test world (as test_due_crew's _PlanGlue):
    one profile, its folder, a client and a collection; background jobs
    run at once. Restores everything on exit."""

    def __init__(self, cl, col, cfg=None):
        from due_crew import plan_flow as F
        self.F, self.cl, self.col = F, cl, col
        self.box = {"cfg": dict(cfg or {})}
        self.dir = tempfile.mkdtemp()
        self.toasts, self.swaps = [], []

    def __enter__(self):
        F = self.F
        self.saved = {k: getattr(F, k) for k in ("cfg", "save_cfg", "_files", "client", "_today", "tooltip", "_bg")}
        self.saved_mw = (F.mw.col, F.app.swap)
        F.cfg = lambda: self.box["cfg"]
        F.save_cfg = lambda c: self.box.update(cfg=c)
        F._files = lambda: self.dir
        F.client = lambda: self.cl
        F._today = lambda: day(0)
        F.tooltip = lambda text, **kw: self.toasts.append(text)
        F._bg = lambda job, done=None: done(job()) if done else job()
        F.app.swap = lambda c: self.swaps.append(1)
        F.mw.col = self.col
        F._store.update(profile=None, data=None)
        return self

    def __exit__(self, *exc):
        F = self.F
        for k, v in self.saved.items():
            setattr(F, k, v)
        F.mw.col, F.app.swap = self.saved_mw
        F._store.update(profile=None, data=None)
        from due_crew.app import _state
        _state["labels"], _state["plan_progress"] = [], {}
        return False

    def follow(self, code):
        F = self.F
        plan, _ = self.cl.follow_plan(code)
        F.on_followed(plan, 10, None, "open")
        self.progress()
        return plan

    def progress(self):
        from due_crew.app import _state
        _state["labels"] = [day(-i) for i in range(7)]
        _state["plan_progress"] = self.F.progress(self.col, self.F.followed(), self.F._state_cfg())


def _world():
    store = fakes.FakeWorker()
    sys.modules["requests"].Session = lambda: fakes.FakeSession(store)
    for uid, name in (("dre", "Dre"), ("maya", "Maya")):
        store.add_user(uid, name)
    cl = api.ApiClient(os.path.join(tempfile.mkdtemp(), "session.json"))
    cl.session = {"user_id": "maya", "token": store.session_for("maya"), "email": "maya@example.com", "display_name": "Maya"}
    return store, cl


def test_card_view():
    store, cl = _world()
    pid, code = store.add_plan("dre", "Path Book", "Step 1",
                               UNITS + [], code=None)
    store.plans[pid]["doc"]["events"] = [{"id": "x", "day": day(43), "name": "Exam"}]
    with Glue(cl, _col()) as g:
        g.follow(code)
        F = g.F
        card = F.card_view(F.followed()[0], F._state_cfg()[pid], F._state["plan_progress"][pid], day(0))
        states = [x["state"] for x in card["path"]["lessons"]]
        check("card view: the path from what's here: lesson 1 seen, 2 behind (opened, its day passed), 3 today, 4 ahead",
              states == ["done", "behind", "now", "ahead"], states)
        check("card view: the head's set 3 of 4; what's behind, its line's words; status's behind is the same count",
              card["sub"].startswith("set 3 of 4 · ") and card["behind"]["name"] == "2 · Inflammation"
              and card["behind"]["left"] == 3 and card["status"]["behind"] == 3 and card["status"]["togo"] == 1, (card["sub"], card["behind"]))
        check("card view: its end, the exam", card["path"]["end"] == {"name": "Exam", "day": day(43), "event": True})
        n = len(store.log)
        view = F.board_view(g.box["cfg"])
        check("board view: no request of its own (the refresh stays one); no exam line while I follow a plan",
              len(store.log) == n and view["exam"] is None and view["cards"][0]["path"]["of"] == 4)
        raw = next(p for p in cl.session["plans"] if p["id"] == pid)
        paused = F.card_view(dict(raw, paused=True), F._state_cfg()[pid], F._state["plan_progress"][pid], day(0))
        own = F.card_view(dict(raw, own="ready"), F._state_cfg()[pid], F._state["plan_progress"][pid], day(0))
        check("card view: paused, or at my own pace (nothing's behind there): no path, no Behind",
              paused["path"] is None and paused["behind"] is None and own["path"] is None and own["behind"] is None)


def test_board_view_exam():
    store, cl = _world()
    with Glue(cl, _col(), cfg={"exam_date": day(43)}) as g:
        F = g.F
        cl.session["plans"] = []
        g.progress()
        view = F.board_view(g.box["cfg"])
        check("board view: following none, my exam ahead: its day and how far", view["exam"] == {"day": day(43), "days": 43}
              and view["writes"] is False, view)
        cl.session["plans_authored"] = [{"id": "a1", "version": 1, "name": "Mine", "doc": {"deck": "Step 1", "units": [
            {"id": "u1", "tags": [], "decks": [], "search": [], "opens": day(40)}]}}]
        view = F.board_view(g.box["cfg"])
        check("board view: a plan I write ends by it: no exam line; and I write one (Your plans…)",
              view["exam"] is None and view["writes"] is True)
        cl.session["plans_authored"][0]["doc"]["units"][0]["opens"] = day(60)
        check("board view: one that ends after it doesn't count", F.board_view(g.box["cfg"])["exam"] == {"day": day(43), "days": 43})
        g.box["cfg"]["exam_date"] = day(0)
        check("board view: an exam today, no line", F.board_view(g.box["cfg"])["exam"] is None)


def _dc():
    import due_crew as dc
    from aqt.deckbrowser import DeckBrowser
    if "aqt.reviewer" not in sys.modules:
        sys.modules["aqt.reviewer"] = types.SimpleNamespace(Reviewer=type("Reviewer", (), {}))
    return dc, DeckBrowser


def test_behind_sheet_glue():
    """Behind… through _on_js as the board sends it: the board's sheet; each
    way does its one thing; Not now nothing."""
    dc, DeckBrowser = _dc()
    from due_crew import app as A, sheets
    store, cl = _world()
    pid, code = store.add_plan("dre", "Path Book", "Step 1", UNITS)
    m = A.mw
    saved = (getattr(m, "state", None), m.web, A._decks[0])
    sent = []
    send = lambda msg: dc._on_js(False, as_board("duecrew:" + msg), DeckBrowser())  # noqa: E731
    try:
        m.web = types.SimpleNamespace(eval=sent.append)
        m.state = "deckBrowser"
        A.on_decks_render()
        with Glue(cl, _col()) as g:
            g.follow(code)
            F = g.F
            n = len(store.log)
            send("planbehind:" + pid)
            js = [s for s in sent if "dc-sheet" in s]
            v = _view(js[-1]) if js else {}
            items = (v.get("field") or {}).get("items")
            check("Behind…: the board's sheet, a day behind on the plan; no request to open it",
                  len(js) == 1 and v["title"] == "A day behind on Path Book" and len(store.log) == n
                  and v["text"] == "2 · Inflammation has 3 left; today 3 · Neoplasia opened 1." and v["no"] == "Not now", v)
            check("Behind…: Slide a day, Fit it in…, Skip what's left",
                  items == ["Slide a day", "Fit it in…", "Skip what's left"] and v["field"]["go"] == ["Slide a day", "Fit it in…", "Skip it"]
                  and v["field"]["notes"][1] == "Over the days you pick: about 1 more new card a day for three days.", v.get("field"))
            answer = lambda at, ok=True: dc._on_js(  # noqa: E731
                False, f"duecrew:sheet:{v['id']}:{quote(json.dumps({'ok': ok, 'at': at}))}|{board.BOARD_KEY}", DeckBrowser())
            answer(0, ok=False)
            check("Behind…: Not now does nothing (no request, nothing kept)",
                  len(store.log) == n and not store.follows[(pid, "maya")].get("shift") and sheets._open == {})
            send("planbehind:" + pid)
            v = _view(sent[-1])
            answer(0)
            check("Slide a day: my follow's shift, one request; the crew's dates stay put",
                  store.follows[(pid, "maya")].get("shift") == 1 and [x[:2] for x in store.log[n:]] == [("PATCH", f"/plans/{pid}/follow")]
                  and any("1 day later" in t for t in g.toasts), (store.log[n:], g.toasts))
            card = F.card_view(F.followed()[0], F._state_cfg()[pid], F._state["plan_progress"][pid], day(0))
            check("Slide a day: then nothing's behind; lesson 2 is today's, and the head says my dates +1 day",
                  card["behind"] is None and card["path"]["at"] == 2 and "your dates +1 day" in card["sub"], card["sub"])
            n0 = len(sent)
            send("planbehind:" + pid)
            check("Behind…: nothing behind any more: no sheet, the card's drawn again", len(sent) == n0 and g.swaps)
            h = board._plan_card_html(card)
            check("Slide: its way back on the same screen, today: \"Your dates moved 1 day later\" with Undo",
                  card["slid"] == 1 and "Your dates moved 1 day later" in h and f"planunslide:{pid}|" in h, card.get("slid"))
            k = len(store.log)
            send("planunslide:" + pid)
            card = F.card_view(F.followed()[0], F._state_cfg()[pid], F._state["plan_progress"][pid], day(0))
            check("Undo: my dates back as they were, one request; the line goes",
                  not store.follows[(pid, "maya")].get("shift") and len(store.log) == k + 1 and card["slid"] == 0
                  and "Your dates moved" not in board._plan_card_html(card), (store.follows[(pid, "maya")], card.get("slid")))
            send("planunslide:" + pid)
            check("…and a second Undo does nothing", len(store.log) == k + 1)
            n = len(store.log) - 1  # the checks below count from the slide's one request
            store.follows[(pid, "maya")]["shift"] = 0
            next(p for p in cl.session["plans"] if p["id"] == pid)["shift"] = 0
            send("planbehind:" + pid)
            v = _view(sent[-1])
            answer(1)
            v = _view(sent[-1])
            check("Fit it in…: then how many days, three to start, 2 to 14", v["title"] == "Fit it in over how many days?"
                  and (v.get("field") or {}).get("value") == "3" and v["yes"] == "Fit it in", v)
            dc._on_js(False, f"duecrew:sheet:{v['id']}:{quote(json.dumps({'ok': True, 'text': '5'}))}|{board.BOARD_KEY}", DeckBrowser())
            st = F._state_cfg()[pid]
            check("Fit it in over 5 days: catch-up's extra a day for those days (G5, Anki's today-only limit each morning); no request",
                  st.get("catch") == {"until": day(4), "extra": 1} and [x[:2] for x in store.log[n + 1:]] == [], (st.get("catch"), store.log[n:]))
            pc = F._pcfg()
            pc["plans"][pid].pop("catch", None)  # as Stop does (the fake decks keep no today-only limit to take off)
            F._psave(pc)
            send("planbehind:" + pid)
            v = _view(sent[-1])
            k = len(store.log)
            answer(2)
            check("Skip what's left: the lesson behind skipped on my follow, one request",
                  store.follows[(pid, "maya")].get("skipped") == ["l2"] and len(store.log) == k + 1)
            check("Skip what's left: says so, and where its way back is (3.9.6, after the last check)",
                  any(t.startswith("Skipped. Its cards stay open in your deck; the week has Undo skip.") for t in g.toasts), g.toasts[-3:])
            card = F.card_view(F.followed()[0], F._state_cfg()[pid], F._state["plan_progress"][pid], day(0))
            check("Skip what's left: off what's behind, in its place on the path, skipped; its cards as they were",
                  card["behind"] is None and card["path"]["lessons"][1]["state"] == "skip"
                  and {3, 4, 5} <= {c for c, q in g.col.db.all("SELECT id, queue FROM cards") if q != -1})
            h = board._plan_card_html(card)
            check("Skip what's left: its way back on the same screen, Undo skip in the week",
                  f"planunskip:{pid}:l2" in h and '<i class="s" title="2 · Inflammation &middot; skipped"' in h)
            k, ks = len(store.log), len(sent)
            next(p for p in cl.session["plans"] if p["id"] == pid)["skipped"] = []  # behind again, here
            dc._on_js(False, "duecrew:planbehind:" + pid, DeckBrowser())  # no board key: a page before's, not the board's
            dc._on_js(False, as_board("duecrew:planbehind:nope"), DeckBrowser())
            check("Behind…: without the board's key, or for a plan I don't follow: nothing",
                  len(store.log) == k and len(sent) == ks, sent[ks:])
            send("planbehind:" + pid)
            check("…and with it, the sheet again (the test above was of something)", len(sent) == ks + 1)
            F._state.pop("plan_focus", None)
            send(f"planjump:{pid}:{day(1)}")
            send(f"planjump:nope:{day(1)}")
            send(f"planjump:{pid}:soon")
            check("a segment's click: its day's details, in its week (jump_to); a plan I don't follow, or no day: nothing",
                  F._state.get("plan_focus") == {pid: day(1)}, F._state.get("plan_focus"))
            # 3.9.6, after the last check: Due's Catch up… is Behind's sheet too, one way to each thing
            sheets._open.clear()
            ks = len(sent)
            send("plancatch:" + pid)
            v = _view(sent[-1]) if len(sent) > ks else {}
            check("Catch up… (Due's, Insights'): Behind's own sheet, not a menu of its own",
                  len(sent) == ks + 1 and v.get("title") == "A day behind on Path Book"
                  and (v.get("field") or {}).get("items") == ["Slide a day", "Fit it in…", "Skip what's left"], v)
    finally:
        m.state, m.web, A._decks[0] = saved
        sheets._open.clear()



def test_cards_i_suspend_are_set_aside_v396():
    """3.9.6 (Sam: "if i've chosen to suspend something after the plan opens
    it, don't want it to make me behind"): a new card I suspend on a date that
    opened here is set aside: not left, not behind, in none of its numbers,
    nor in the day's Left. One the plan holds (Hold back) still counts; a
    date all suspended again (Edit › Undo) is closed, not set aside; a date
    that hasn't opened keeps its suspended cards to come."""
    from due_crew import plans as P
    store, cl = _world()
    pid, code = store.add_plan("dre", "Path Book", "Step 1", UNITS)
    with Glue(cl, _col()) as g:
        g.follow(code)
        F = g.F
        prog = F._state["plan_progress"][pid]
        check("suspend: before, lesson 2's three new cards are left on it (opened by the plan)",
              prog["l2"] == [3, 0, 3], prog.get("l2"))
        g.col.db.conn.execute("UPDATE cards SET queue = -1 WHERE id = 4")  # I suspend one of them in Anki
        g.progress()
        prog = F._state["plan_progress"][pid]
        st = F._state_cfg()[pid]
        check("suspend: the one I suspended is set aside: lesson 2 has two, both left",
              prog["l2"] == [2, 0, 2] and P.set_aside(P.DeckIndex(g.col, 10), F.followed()[0]["doc"], None,
                                                      st.get("applied"), st.get("held")) == {4}, prog.get("l2"))
        card = F.card_view(F.followed()[0], st, prog, day(0))
        b = card["behind"]
        check("suspend: behind counts the two I didn't set aside, not three", b and b["left"] == 2, b)
        g.col.db.conn.execute("UPDATE cards SET queue = 2, type = 2 WHERE id IN (3, 5)")  # and I see the other two
        g.progress()
        prog = F._state["plan_progress"][pid]
        card = F.card_view(F.followed()[0], st, prog, day(0))
        check("suspend: the rest seen, lesson 2 is done, and nothing's behind",
              prog["l2"] == [2, 2, 2] and card["behind"] is None
              and next(x for x in card["path"]["lessons"] if x["uid"] == "l2")["state"] == "done", (prog.get("l2"), card.get("behind")))
        c = F._pcfg()
        c["plans"][pid]["held"] = [4]  # the plan holds it (Hold back), not me
        F._psave(c)
        g.progress()
        check("suspend: one the plan holds still counts (left till it opens)", F._state["plan_progress"][pid]["l2"] == [2, 2, 3])
        c["plans"][pid]["held"] = []
        F._psave(c)
        g.col.db.conn.execute("UPDATE cards SET queue = -1 WHERE id IN (6)")  # lesson 3, opened today: its one card suspended again
        g.progress()
        check("suspend: a date with none of its cards open (Edit › Undo) is closed, not set aside",
              F._state["plan_progress"][pid]["l3"] == [0, 0, 1])
        check("suspend: a date that hasn't opened keeps its suspended cards to come",
              F._state["plan_progress"][pid]["l4"] == [0, 0, 1])

def test_qt_sheet():
    """Off the board (a window in front, the review screen), Qt's list: each way with its line."""
    from due_crew import app as A, sheets, ui
    m = A.mw
    saved = (getattr(m, "state", None), ui.ask_item)
    seen, got = [], []
    try:
        m.state = "review"
        ui.ask_item = lambda parent, title, label, items, current=0: seen.append((title, list(items))) or (items[1], True)
        sheets.ask_item("A day behind on X", "x", ["Slide a day", "Fit it in"], got.append,
                        notes=["Everything still to come.", ""], yes_each=["Slide a day", "Fit it in"], no_label="Not now")
        check("off the board: Qt's list, each way with its line; the pick reaches then",
              seen == [("A day behind on X", ["Slide a day: Everything still to come.", "Fit it in"])] and got == [1], (seen, got))
    finally:
        m.state, ui.ask_item = saved


def test_follow_and_new_commands():
    """The empty tab's clicks, through _on_js as the board sends them."""
    dc, DeckBrowser = _dc()
    from due_crew import plan_flow as F
    from due_crew import planner
    from due_crew.planner import flow as pflow
    got = []
    saved = (F.open_follow, pflow.open_new, sys.modules.get("due_crew.planner.web"), getattr(planner, "web", None), dc._add_code)
    send = lambda msg: dc._on_js(False, as_board("duecrew:" + msg), DeckBrowser())  # noqa: E731
    try:
        F.open_follow = lambda code="": got.append(("follow", code))
        dc._add_code = lambda code: got.append(("code", code))
        pflow.open_new = lambda: got.append(("new",))
        for typed in ("https://duecrew.com/p/N4APULM2?ref=crew", "n4ap ulm2", ""):
            send("planfollowcode:" + quote(typed, safe=""))
        dc._on_js(False, "duecrew:planfollowcode:N4APULM2", DeckBrowser())  # no board key
        check("Follow: a link's code into Follow; a code as typed the way the box's codes always went (a plan's, a friend's, "
              "a squad's, an invite); nothing typed, Follow to type one; no key, nothing",
              got == [("follow", "N4APULM2"), ("code", "N4AP ULM2"), ("follow", "")], got)
        got.clear()
        sys.modules["due_crew.planner.web"] = None  # this build has no new plan window
        if hasattr(planner, "web"):
            delattr(planner, "web")
        send("planopennew")
        send("planopennew:2026-12-18")
        check("Make a plan, Plan the way there: without the new plan window, planner's New plan", got == [("new",), ("new",)], got)
        got.clear()
        web = types.ModuleType("due_crew.planner.web")
        web.open_new = lambda start=None, finish_by=None: got.append(("web", start, finish_by))
        sys.modules["due_crew.planner.web"] = web
        send("planopennew")
        send("planopennew:2026-12-18")
        send("planopennew:soon")
        check("…with it, the new plan window: Plan the way there finishing by my exam's day; anything but a day, none",
              got == [("web", None, None), ("web", None, "2026-12-18"), ("web", None, None)], got)
    finally:
        F.open_follow, pflow.open_new, dc._add_code = saved[0], saved[1], saved[4]
        if saved[2] is None:
            sys.modules.pop("due_crew.planner.web", None)
        else:
            sys.modules["due_crew.planner.web"] = saved[2]
        if saved[3] is not None:
            planner.web = saved[3]
        elif hasattr(planner, "web"):
            delattr(planner, "web")


def test_commands_have_handlers():
    """Every duecrew: command this tab puts on the board has its handler in plan_flow."""
    html = (board._plan_card_html(_card()) + board._plans_empty_html({"cards": [], "exam": {"day": day(43), "days": 43}, "writes": True}))
    cmds = set(re.findall(r"duecrew:([a-z0-9]+)", html))
    src = "".join(open(os.path.join(REPO, "due_crew", f)).read() for f in ("plan_flow.py", "__init__.py", "team_flow.py"))
    handled = set(re.findall(r'cmd == "([a-z0-9]+)"', src))
    new = {"planbehind", "planfollowcode", "planopennew"}
    check("commands: the new ones are on the tab, and every command on it has a handler",
          new <= cmds and not (cmds - handled - {"plan"}), sorted(cmds - handled))


def main():
    names = [n for n in list(globals()) if n.startswith("test_")]
    for n in names:
        globals()[n]()
    bad = [c for c in CHECKS if not c[1]]
    print(f"\n{len(CHECKS) - len(bad)}/{len(CHECKS)} checks passed")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
