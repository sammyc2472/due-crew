"""3.9.6, the plan joys (Sam's picks, the "Joy on the plan card" mock). A
set done pops on the path and Pip hops to it; halfway, three-quarters and
the last set are a line each with Share and ×; the finish line is a show
over the Decks screen (show.js's DCShow.finish), then a line with Share and
a story-size picture (sharecard.py's plan card, cards.js its twin); Behind
cleared says Caught up for the rest of the day; the first morning says Day
one and Pip says let's go; three new things for Pip's closet; New plan lays
the path out set by set. Each moment: when it shows, that it shows once,
its way back; each new duecrew: command through _on_js as the board sends
it; nothing new sent, no new request. Standard library; node for the
scripts, when it's there.

Run: python3 tests/test_plan_joy.py
"""

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import types

HARNESS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HARNESS)
sys.path.insert(0, HARNESS)

import test_plan_board as TB  # noqa: E402  (its plan world: a followed plan, its collection, the glue pointed at it)
import fakes  # noqa: E402

from due_crew import board  # noqa: E402
from due_crew import closet as C  # noqa: E402
from due_crew import closet_art as CA  # noqa: E402
from due_crew import closet_flow as CF  # noqa: E402
from due_crew import plans as P  # noqa: E402
from due_crew import sev  # noqa: E402
from due_crew import sharecard as S  # noqa: E402
from due_crew import shows  # noqa: E402

CHECKS = []
NODE = shutil.which("node")


def check(name, cond, detail=""):
    CHECKS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond or detail == "" else f"\n     {detail}"))


# the mock's plan: Path Book, 19 sets from Mon 2 Nov to Fri 11 Dec, 2,046 cards, its exam Fri 18 Dec
DAYS = ["2026-11-02", "2026-11-04", "2026-11-05", "2026-11-06", "2026-11-09", "2026-11-10", "2026-11-12", "2026-11-16",
        "2026-11-18", "2026-11-20", "2026-11-23", "2026-11-25", "2026-11-27", "2026-11-30", "2026-12-02", "2026-12-04",
        "2026-12-07", "2026-12-09", "2026-12-11"]
NAMES = ["Cell injury", "Inflammation", "Neoplasia", "Hemodynamics", "Immunology", "Genetics", "Environment", "Infectious",
         "Blood vessels", "Heart", "Hematopoietic", "Lung", "Head and neck", "GI tract", "Liver", "Pancreas", "Kidney",
         "Endocrine", "Skin <b>"]
N = [84, 101, 66, 118, 92, 125, 108, 96, 131, 112, 97, 140, 74, 128, 119, 103, 137, 88, 127]
DOC = {"units": [{"id": f"e{i}", "name": f"{i + 1} · {nm}", "opens": d, "n": N[i]} for i, (d, nm) in enumerate(zip(DAYS, NAMES))],
       "events": [{"id": "ex", "day": "2026-12-18", "name": "Exam"}]}


def path(today, prog, applied=None):
    return P.path(DOC, prog, today, applied=applied if applied is not None else {u["id"]: "s" for u in DOC["units"] if u["opens"] <= today})


def upto(k, **extra):
    out = {f"e{i}": [N[i], N[i], N[i]] for i in range(k)}
    out.update(extra)
    return out


def step(st, today, prog, now, shown=False, applied=None):
    p = path(today, prog, applied)
    return P.joy_step(st, p, P.behind_of(p, today), today, now, shown=shown, name="Path Book")


# ---- pure: plans.joy_step ----

def test_a_set_done():
    t = "2026-11-05"
    st, v = step(None, t, upto(2, e2=[66, 30, 66]), 100.0)
    check("pop: the first look is history: what's done already never pops", v["pop"] is None and st["done"] == ["e0", "e1"]
          and not st.get("pop"), st)
    st, v = step(st, t, upto(3), 101.0)
    check("pop: a set's cards all seen: its pop waits for the board (not drawn till it's on screen)",
          v["pop"] is None and st["pop"] == {"uid": "e2", "day": t, "at": 0}, (st.get("pop"), v["pop"]))
    st, v = step(st, t, upto(3), 102.0, shown=True)
    check("pop: on screen, it's claimed and plays from there", v["pop"] == {"uid": "e2", "ago": 0.0} and st["pop"]["at"] == 102.0, v["pop"])
    st2, v2 = step(st, t, upto(3), 104.5, shown=True)
    check("pop: a redraw in its seconds goes on from where it is (ago), never from the start", v2["pop"] == {"uid": "e2", "ago": 2.5}
          and st2["pop"]["at"] == 102.0, v2["pop"])
    st3, v3 = step(st2, t, upto(3), 102.0 + P.JOY_POP + 0.1, shown=True)
    check("pop: after its five seconds, gone: the segment is just filled", v3["pop"] is None and st3["pop"]["at"] == 102.0)
    st4, v4 = step(st3, "2026-11-06", upto(3), 99999.0, shown=True)
    check("pop: once a set: the next day it doesn't pop again", v4["pop"] is None and st4["done"] == ["e0", "e1", "e2"])
    late, _v = step(st, t, upto(3), 101.0)
    late["pop"]["at"] = 0
    gone, vg = step(late, "2026-11-06", upto(3), 200.0, shown=True)
    check("pop: one that waited past its day isn't played (the moment's gone)", vg["pop"] is None and not gone["pop"]["at"], gone["pop"])
    st5, _v = step(None, "2026-11-06", upto(3), 1.0)
    st5, v5 = step(st5, "2026-11-06", upto(5), 2.0, shown=True)
    check("pop: two sets done at once (a phone's sync): Pip hops to the last one; both are known", v5["pop"] == {"uid": "e4", "ago": 0.0}
          and st5["done"][-2:] == ["e3", "e4"], (v5["pop"], st5["done"]))
    empty = {"units": [{"id": "a", "name": "A", "opens": "2026-11-02"}, {"id": "b", "name": "B", "opens": "2026-11-04"}]
             + [{"id": x, "name": x, "opens": f"2026-11-{9 + i:02d}"} for i, x in enumerate("cdef")]}
    pe = P.path(empty, {"a": [5, 5, 5]}, "2026-11-05", applied={"a": "s", "b": "s"})
    s0, _v = P.joy_step(None, P.path(empty, {}, "2026-11-03", applied={"a": "s"}), None, "2026-11-03", 1.0)
    s1, ve = P.joy_step(s0, pe, None, "2026-11-05", 2.0, shown=True)
    check("pop: only a set whose cards are seen: one with none of its cards here, its day passed, doesn't pop",
          ve["pop"] == {"uid": "a", "ago": 0.0} and "b" not in s1["done"], (ve["pop"], s1["done"]))
    check("pop: nothing without a path (paused, my own pace, no deck: the card has none)", P.joy_step({"done": []}, None, None, t, 1.0)
          == ({"done": []}, None))


def test_milestones():
    st, _v = step(None, "2026-11-18", upto(8), 1.0)
    st, v = step(st, "2026-11-18", upto(9), 2.0)
    check("milestones: counted in sets: 9 of 19 isn't halfway (the 10th is)", v["line"] is None and P.joy_mark(19, 1, 2) == 10
          and P.joy_mark(19, 3, 4) == 15)
    st, v = step(st, "2026-11-20", upto(10), 3.0)
    check("halfway: the 10th set of 19 done: its line, today (pending till it's on screen), and no pop as well",
          v["line"] == {"key": "half", "n": 10, "of": 19, "name": "", "uid": "e9", "ago": None} and not st.get("pop")
          or v["line"]["key"] == "half" and v["line"]["n"] == 10 and st.get("pop", {}).get("uid") != "e9", (v["line"], st.get("pop")))
    st, v = step(st, "2026-11-20", upto(10), 4.0, shown=True)
    check("halfway: on screen, its line slides in and its set sparkles (ago)", v["line"]["ago"] == 0.0 and v["line"]["uid"] == "e9")
    st, v = step(st, "2026-11-20", upto(10), 4.0 + P.JOY_LINE + 1, shown=True)
    check("halfway: the line stays the day; its motion was once", v["line"]["key"] == "half" and v["line"]["ago"] is None)
    x = P.joy_dismiss(st, "half", "2026-11-20")
    _s, vx = step(x, "2026-11-20", upto(10), 9.0, shown=True)
    check("halfway: × takes it off for today", vx["line"] is None and x["miles"]["half"]["x"] is True
          and P.joy_dismiss(x, "half", "2026-11-20") is None and P.joy_dismiss(st, "half", "2026-11-21") is None
          and P.joy_dismiss(st, "fin", "2026-11-20") is None)
    _s, vt = step(st, "2026-11-21", upto(10), 99.0, shown=True)
    check("halfway: gone tomorrow either way; never again", vt["line"] is None)
    st, v = step(st, "2026-12-02", upto(15), 100.0)
    check("three-quarters: the 15th set of 19", v["line"]["key"] == "threeq" and v["line"]["n"] == 15 and v["line"]["of"] == 19, v["line"])
    st, v = step(st, "2026-12-09", upto(18, e18=[127, 0, 127]), 200.0)
    check("the last set: not before its morning", v["line"] is None)
    st, v = step(st, "2026-12-11", upto(18, e18=[127, 0, 127]), 300.0, shown=True)
    check("the last set: the morning it opens, its name", v["line"] == {"key": "last", "n": 19, "of": 19, "name": "19 · Skin <b>",
                                                                       "uid": "e18", "ago": 0.0}, v["line"])
    jump, _v = step(None, "2026-11-09", upto(4), 1.0)
    jump, vj = step(jump, "2026-12-02", upto(16), 2.0)
    check("milestones: past two at once, the bigger one's line; the other's passed, never shown",
          vj["line"]["key"] == "threeq" and jump["miles"]["half"] == {"day": ""}, (vj["line"], jump["miles"]))
    seeded, vs = step(None, "2026-12-02", upto(16), 1.0)
    check("milestones: the first look: what's passed is history, no line", vs["line"] is None and set(seeded["miles"]) == {"half", "threeq"})
    two = {"units": [{"id": "a", "name": "A", "opens": "2026-11-02"}, {"id": "b", "name": "B", "opens": "2026-11-04"}]}
    tp = lambda prog: P.path(two, prog, "2026-11-05", applied={"a": "s", "b": "s"})  # noqa: E731
    check("milestones: a plan of two: halfway is one set; never a three-quarters that's the finish",
          set(P._miles(tp({"a": [3, 3, 3], "b": [3, 0, 3]}), P.joy_numbers(tp({"a": [3, 3, 3], "b": [3, 0, 3]})))) == {"half"}
          and P._miles(P.path({"units": two["units"][:1]}, {"a": [3, 3, 3]}, "2026-11-05"), {"sets": 1, "done": 1}) == {})


def test_the_finish():
    st, _v = step(None, "2026-12-11", upto(18, e18=[127, 60, 127]), 1.0)
    st, v = step(st, "2026-12-11", upto(19), 2.0)
    check("finish: the last set's last card seen: its show waits for the next board draw; no pop, no line",
          v["show"] is True and v["pop"] is None and v["line"] is None and st["fin"]["at"] == 0 and st["fin"]["name"] == "Path Book"
          and (st["fin"]["sets"], st["fin"]["cards"], st["fin"]["weeks"]) == (19, 2046, 6), st["fin"])
    check("finish: the card keeps its line: 19 sets · 2,046 cards · 6 weeks",
          v["fin"] == {"sets": 19, "cards": 2046, "weeks": 6, "words": "19 sets · 2,046 cards · 6 weeks"}, v["fin"])
    st["fin"]["at"] = 5.0  # the show played (plan_flow.joy_show)
    st, v = step(st, "2026-12-11", upto(19), 9.0, shown=True)
    check("finish: once a plan: played, no show again; the line stays", v["show"] is False and v["fin"]["sets"] == 19)
    st, v = step(st, "2027-01-05", upto(19), 99.0, shown=True)
    check("finish: for as long as I follow it", v["fin"] and v["show"] is False)
    old, vo = step(None, "2026-12-14", upto(19), 1.0)
    check("finish: a plan finished before (history): the line, never its show", vo["fin"] and vo["show"] is False and old["fin"] == {"day": ""})
    num = P.joy_numbers(path("2026-12-11", upto(19)))
    check("finish: its numbers: sets (skipped ones aside), cards, weeks first day to last, as the builder's card counts them",
          num == {"sets": 19, "done": 19, "cards": 2046, "seen": 2046, "weeks": 6}
          and P.joy_numbers(P.path(DOC, upto(19), "2026-12-11", skipped=["e3"]))["sets"] == 18, num)
    check("finish: in words, and as text to paste (cards as Privacy's Reviews says)",
          P.joy_words(num) == "19 sets · 2,046 cards · 6 weeks" and P.joy_words(num, cards=False) == "19 sets · 6 weeks"
          and P.joy_text("fin", "Path Book", num) == "Finished Path Book: 19 sets, 2,046 cards, 6 weeks. duecrew.com"
          and P.joy_text("half", "Path Book", line={"n": 10, "of": 19}) == "Halfway through Path Book: 10 of 19 sets. duecrew.com"
          and P.joy_text("last", "Path Book", line={"name": "19 · Skin"}) == "The last set of Path Book: 19 · Skin, today. duecrew.com")
    un = P.path(DOC, upto(19), "2026-12-11", skipped=["e18"])
    check("finish: a skipped set doesn't hold it back", P.joy_finished(un) and not P.joy_finished(path("2026-12-11", upto(18))))


def test_caught_up():
    t = "2026-11-05"
    behind = upto(1, e1=[101, 70, 101], e2=[66, 0, 66])
    st, v = step(None, t, behind, 1.0)
    check("caught up: what's behind is kept, to know it when it clears", st["late"] == {"uids": ["e1"], "name": "2 · Inflammation", "more": 0}
          and v["caught"] is None)
    st, v = step(st, t, upto(2, e2=[66, 0, 66]), 2.0)
    check("caught up: Behind cleared by seeing it: its line for the rest of the day, its 🎉 waiting for the board; no pop as well",
          v["caught"] == {"name": "2 · Inflammation", "more": 0, "n": 101, "uids": ["e1"], "ago": None} and not st.get("pop")
          and "late" not in st, (v["caught"], st.get("pop")))
    st, v = step(st, t, upto(2, e2=[66, 0, 66]), 3.0, shown=True)
    st, v2 = step(st, t, upto(2, e2=[66, 0, 66]), 3.0 + P.JOY_TADA + 1, shown=True)
    check("caught up: the 🎉 pops once; the line stays the day", v["caught"]["ago"] == 0.0 and v2["caught"]["ago"] is None
          and v2["caught"]["n"] == 101)
    _s, v3 = step(st, "2026-11-06", upto(2, e2=[66, 0, 66]), 99.0, shown=True)
    check("caught up: gone tomorrow", v3["caught"] is None)
    again = step(st, "2026-11-06", upto(2, e2=[66, 10, 66]), 100.0)[0]
    check("caught up: behind again (the next set's day passed with cards left): the line goes, the new one's kept",
          again["late"]["uids"] == ["e2"] and "caught" not in again)
    again, va = step(again, "2026-11-06", upto(3), 101.0)
    check("caught up: every time it clears, the line again", va["caught"]["name"] == "3 · Neoplasia" and va["caught"]["n"] == 66)
    sl, _v = step(None, t, behind, 1.0)
    p2 = P.path(DOC, behind, t, applied={u["id"]: "s" for u in DOC["units"] if u["opens"] <= t}, shift=1)
    sl, vs = P.joy_step(sl, p2, P.behind_of(p2, t), t, 2.0, shown=True)
    check("caught up: Slide clears Behind its own way (its line, its Undo): no Caught up", vs["caught"] is None and "late" not in sl)
    two = upto(0, e0=[84, 30, 84], e1=[101, 70, 101], e2=[66, 0, 66])
    s2, _v = step(None, t, two, 1.0)
    s2, v2b = step(s2, t, upto(2, e2=[66, 0, 66]), 2.0)
    check("caught up: two sets behind: the first named, and one more; all their cards", v2b["caught"]["name"] == "1 · Cell injury"
          and v2b["caught"]["more"] == 1 and v2b["caught"]["n"] == 185, v2b["caught"])


def test_day_one():
    st, v = step(None, "2026-11-02", {"e0": [84, 0, 84]}, 10.0)
    check("day one: the first set opens today, even at the first look: Day one, its Pip waiting for the board",
          v["day1"] == {"ago": None} and st["day1"] == {"day": "2026-11-02", "at": 0})
    st, v = step(st, "2026-11-02", {"e0": [84, 0, 84]}, 11.0, shown=True)
    st, v2 = step(st, "2026-11-02", {"e0": [84, 30, 84]}, 11.0 + P.JOY_GO + 1, shown=True)
    check("day one: Pip's let's-go once, the words all day", v["day1"]["ago"] == 0.0 and v2["day1"] == {"ago": None})
    _s, v3 = step(st, "2026-11-04", {"e0": [84, 84, 84]}, 99.0, shown=True)
    check("day one: not the next morning", v3["day1"] is None)
    moved = P.path(DOC, {"e0": [84, 0, 84]}, "2026-11-03", applied={"e0": "s"}, shift=1)
    _s, vm = P.joy_step(st, moved, None, "2026-11-03", 120.0, shown=True)
    check("day one: once a plan: my dates moved, it says Day one again, but Pip doesn't play again",
          vm["day1"] == {"ago": None}, vm["day1"])


# ---- the board: what each moment draws ----

def _card(today, prog, joy=None, **kw):
    p = path(today, prog)
    late = P.behind_of(p, today)
    togo = sum(max(0, x["total"] - x["seen"]) for x in p["lessons"] if x["opens"] == today)
    return dict({"id": "p1", "title": "Path Book · Dre’s plan", "name": "Path <i>Book</i>", "sub": "set 3 of 19 · 6 following",
                 "rows": [], "lines": [], "change": None, "no_deck": False, "paused": False, "waiting": 0,
                 "aside": [0, 0, 0], "aside_ok": [0, 0], "week": P.week_view(DOC, prog, today, P.week_start(today)), "week_offset": 0,
                 "status": {"togo": togo, "behind": late["left"] if late else 0, "since": ""}, "path": p, "behind": late,
                 "tabs": {}, "joy": joy}, **kw)


def test_board():
    plain = board._plan_card_html(_card("2026-11-05", upto(3)))
    check("board: no joy, the card as it was (nothing new in it)", "data-joy" not in plain and "jpp" not in plain and "planjoy" not in plain
          and plain == board._plan_card_html(_card("2026-11-05", upto(3), joy={"pop": None, "line": None, "fin": None, "show": False,
                                                                               "caught": None, "day1": None})))
    pip = "<svg class=\"sv m-hop\"></svg>"
    h = board._plan_card_html(_card("2026-11-05", upto(3), joy={"pop": {"uid": "e2", "ago": 1.234, "pip": pip}}))
    seg = re.search(r'<i class="d t"[^>]*>.*?</i>', h).group(0)
    check("board: a set done: its segment plays the pop (motion.js), how long it's been out, Pip on it",
          'data-joy="pop" style="--ago:1.23s"' in seg and f'<span class="jpp" aria-hidden="true">{pip}</span>' in seg, seg)
    check("board: Pip off, the pop alone", '<span class="jpp"' not in board._plan_card_html(
        _card("2026-11-05", upto(3), joy={"pop": {"uid": "e2", "ago": 0.2}})))
    line = {"key": "half", "n": 10, "of": 19, "name": "", "uid": "e9", "ago": 0.0}
    h = board._plan_card_html(_card("2026-11-20", upto(10), joy={"line": line}))
    check("board: halfway: a line under the path, the plan's name escaped, Share and × (each the board's command, keyed)",
          '<b>Halfway through Path &lt;i&gt;Book&lt;/i&gt;</b> &middot; 10 of 19 sets' in h and "duecrew:planjoyshare:p1:half|" in h
          and "duecrew:planjoyx:p1:half|" in h and 'class="pst jml" data-joy="line"' in h
          and h.index('class="ppl"') < h.index("jml") < h.index('class="pwk"'), h[:2000])
    segs = re.findall(r"<i class=[^>]*>", h.split('<div class="ppath')[1].split("</div>")[0])
    check("board: …the set that made it sparkles", 'data-joy="spark"' in segs[9] and sum('data-joy' in x for x in segs) == 1, segs[8:11])
    last = board._plan_card_html(_card("2026-12-11", upto(18), joy={"line": {"key": "last", "n": 19, "of": 19, "name": "19 · Skin <b>",
                                                                             "uid": "e18", "ago": None}}))
    check("board: the last set: its name escaped, today; no motion once it's played",
          "<b>The last set of Path &lt;i&gt;Book&lt;/i&gt;</b> &middot; 19 · Skin &lt;b&gt;, today" in last
          and 'data-joy="line"' not in last and "spark" not in last)
    fin = board._plan_card_html(_card("2026-12-11", upto(19), joy={"fin": {"words": "19 sets · 2,046 cards · 6 weeks"}}))
    check("board: finished: the card keeps a line with Share, and no ×",
          '<div class="pst jfin"><span><b>Finished</b> &middot; 19 sets · 2,046 cards · 6 weeks</span>' in fin
          and "duecrew:planjoyshare:p1:fin|" in fin and "planjoyx" not in fin)
    caught = _card("2026-11-05", upto(2, e2=[66, 0, 66]), joy={"caught": {"name": "2 · Inflammation <i>", "more": 0, "n": 101,
                                                                         "uids": ["e1"], "ago": 0.1}})
    hc = board._plan_card_html(caught)
    check("board: caught up: the line where Behind was, the set's name escaped, a 🎉 that pops (motion.js), the late set turning",
          '<b>Caught up</b> &middot; 2 · Inflammation &lt;i&gt;, all 101 seen' in hc and 'data-joy="tada"' in hc and "&#127881;" in hc
          and 'data-joy="caught"' in hc and "planbehind" not in hc and hc.index("<b>66</b> to go today") < hc.index("Caught up"), hc[:2500])
    still = board._plan_card_html(dict(caught, joy={"caught": dict(caught["joy"]["caught"], ago=None)}))
    check("board: …after its moment, the line and its 🎉 stay the day, still", "Caught up" in still and "&#127881;" in still
          and "data-joy" not in still)
    one = board._plan_card_html(_card("2026-11-02", {"e0": [84, 0, 84]}, joy={"day1": {"ago": 0.5, "pip": pip}}))
    check("board: day one: Day one · 84 to go today, Pip just after the words for its let's-go",
          '<span><b class="jd1">Day one</b> &middot; <b>84</b> to go today</span><span class="jgo" data-joy="go" style="--ago:0.50s">' in one
          and f'<span class="jgp" aria-hidden="true">{pip}</span>' in one, one[:2500])
    one_later = board._plan_card_html(_card("2026-11-02", {"e0": [84, 0, 84]}, joy={"day1": {"ago": None}}))
    check("board: …all day the words, Pip once", "Day one" in one_later and "jgo" not in one_later)
    css = board._css({})
    check("board: still (Reduce motion), a Pip stands where it lands, then goes in its time; the joys' places are left-aligned board parts",
          "#due-crew .ppath i[data-joy] { position: relative; }" in css and "dcjoygo 0s linear calc(5s - var(--ago, 0s)) forwards" in css
          and "@keyframes dcjoygo { to { visibility: hidden; } }" in css)
    src = open(os.path.join(REPO, "due_crew", "plan_flow.py"), encoding="utf-8").read()
    handled = set(re.findall(r'cmd == "([a-z0-9]+)"', src))
    cmds = set(re.findall(r"duecrew:([a-z0-9]+)", fin + h + hc + board.finish_js({"pid": "p1", "name": "x", "sets": 2})))
    check("board: every joy command has its handler", {"planjoyshare", "planjoyx"} <= cmds and {"planjoyshare", "planjoyx"} <= handled, cmds)


# ---- the glue: a followed plan, its joys, the clicks ----

def _col8():
    """Eight sets: u1 seen, u2 behind (opened, its day passed, three new), u3 today's (one new), u4..u8 ahead."""
    conn = sqlite3.connect(":memory:")
    fakes.make_collection(conn)
    cards = [(1, "L1", True), (2, "L1", True), (3, "L2", False), (4, "L2", False), (5, "L2", False), (6, "L3", False)]
    cards += [(7 + i, f"L{4 + i}", False) for i in range(5)]
    for cid, tag, seen in cards:
        fakes.add_card(conn, cid, did=10, ctype=2 if seen else 0, queue=2 if seen else -1, tags=f"Step1::{tag}")
    col = fakes.FakeCol(conn, fakes.day_cutoff_for(TB.TODAY))
    col.decks = fakes.FakeDecks({10: "Step 1"})
    return col, conn


UNITS8 = ([{"id": "u1", "name": "1 · Cell injury", "opens": TB.day(-3), "tags": ["Step1::L1"]},
           {"id": "u2", "name": "2 · Inflammation", "opens": TB.day(-1), "tags": ["Step1::L2"]},
           {"id": "u3", "name": "3 · Neoplasia", "opens": TB.day(0), "tags": ["Step1::L3"]}]
          + [{"id": f"u{4 + i}", "name": f"{4 + i} · Set", "opens": TB.day(2 + i), "tags": [f"Step1::L{4 + i}"]} for i in range(5)])


def _seen(conn, *cids):
    conn.execute(f"UPDATE cards SET type = 2, queue = 2 WHERE id IN ({','.join(str(int(c)) for c in cids)})")


def test_glue():
    dc, DeckBrowser = TB._dc()
    from due_crew import app as A, rooms
    store, cl = TB._world()
    pid, code = store.add_plan("dre", "Path <b>Book", "Step 1", UNITS8)
    col, conn = _col8()
    m = A.mw
    saved = (getattr(m, "state", None), m.web, A._decks[0], rooms.cfg, A._state.get("board_shown"), CF.note_plan_done)
    sent, done_ids = [], []
    send = lambda msg: dc._on_js(False, TB.as_board("duecrew:" + msg), DeckBrowser())  # noqa: E731
    try:
        m.web = types.SimpleNamespace(eval=sent.append)
        m.state = "deckBrowser"
        A.on_decks_render()
        rooms.cfg = lambda: {}
        CF.note_plan_done = done_ids.append
        with TB.Glue(cl, col) as g:
            F = g.F
            g.follow(code)
            n = len(store.log)
            card = F.board_view(g.box["cfg"])["cards"][0]
            joys = F._pcfg().get("joy") or {}
            check("glue: the first look keeps what's so in plans.json's joy (this profile's), nothing plays",
                  joys.get(pid, {}).get("done") == ["u1"] and joys[pid]["late"]["uids"] == ["u2"] and card["joy"]["pop"] is None, joys)
            _seen(conn, 6)
            g.progress()
            card = F.board_view(g.box["cfg"])["cards"][0]
            check("glue: a set's cards all seen: its pop waits (the board's draw that isn't on screen claims nothing)",
                  card["joy"]["pop"] is None and F._pcfg()["joy"][pid]["pop"]["uid"] == "u3", F._pcfg()["joy"][pid].get("pop"))
            m.state = "review"
            F.joy_claim([card], g.box["cfg"])
            check("glue: …nor does You › Plans while the Decks screen isn't up", not F._pcfg()["joy"][pid]["pop"]["at"])
            m.state = "deckBrowser"
            F.joy_claim([card], g.box["cfg"])
            pop = card["joy"]["pop"] or {}
            move = re.search(r'class="sv m-([a-z]+)', pop.get("pip") or "")
            check("glue: You › Plans drawn with the board up claims it: it plays from now, Pip hopping (sev.py's, a move from the "
                  "day done's mix, no confetti)", pop.get("uid") == "u3" and pop.get("ago") == 0.0 and move and move.group(1) in sev.moves("hop")
                  and 'class="cf"' not in pop["pip"] and F._pcfg()["joy"][pid]["pop"]["at"] > 0, pop)
            same = F.board_view(g.box["cfg"])["cards"][0]
            F.joy_claim([same], g.box["cfg"])
            check("glue: …the same move through its redraws", move and f'class="sv m-{move.group(1)}' in (same["joy"]["pop"] or {}).get("pip", ""))
            rooms.cfg = lambda: {"sev": False}
            again = F.board_view(g.box["cfg"])["cards"][0]
            F.joy_claim([again], g.box["cfg"])
            check("glue: a redraw in its seconds goes on; with Pip off, no Pip", (again["joy"]["pop"] or {}).get("uid") == "u3"
                  and "pip" not in again["joy"]["pop"])
            rooms.cfg = lambda: {}
            st = F._pcfg()["joy"][pid]
            st["pop"]["at"] -= 60
            F._psave(F._pcfg())
            gone = F.board_view(g.box["cfg"])["cards"][0]
            F.joy_claim([gone], g.box["cfg"])
            check("glue: once: after its seconds, never again", gone["joy"]["pop"] is None)
            _seen(conn, 3, 4, 5)
            g.progress()
            card = F.board_view(g.box["cfg"])["cards"][0]
            F.joy_claim([card], g.box["cfg"])
            h = board._plan_card_html(card)
            check("glue: Behind cleared by seeing it: Caught up for the rest of the day, in Behind's place",
                  card["behind"] is None and card["joy"]["caught"]["name"] == "2 · Inflammation" and card["joy"]["caught"]["n"] == 3
                  and "Caught up" in h and "planbehind" not in h, card["joy"]["caught"])
            _seen(conn, 7)
            g.progress()
            card = F.board_view(g.box["cfg"])["cards"][0]
            F.joy_claim([card], g.box["cfg"])
            check("glue: halfway (the 4th of 8): its line", (card["joy"]["line"] or {}).get("key") == "half"
                  and card["joy"]["line"]["n"] == 4, card["joy"]["line"])
            menus = []
            saved_menu, saved_copy = F._joy_menu, sys.modules["due_crew.ui"].copy_text
            copied, made = [], []
            dlg = types.ModuleType("due_crew.ui.share_card_dialog")

            class Dlg:
                def __init__(self, parent, choose, priv=None, tooltip=None, **_kw):
                    made.append((choose(None), priv))

                def show(self):
                    pass
            dlg.ShareCardDialog = Dlg
            real_dlg = sys.modules.get("due_crew.ui.share_card_dialog")
            sys.modules["due_crew.ui.share_card_dialog"] = dlg
            F._joy_menu = menus.append
            sys.modules["due_crew.ui"].copy_text = copied.append
            try:
                send(f"planjoyshare:{pid}:half")
                items = menus[-1] if menus else []
                check("glue: Share on the line: the board's Share menu, as text or as a picture", [x[0] for x in items] == ["As text", "As a picture…"])
                items[0][1]()
                check("glue: as text: the line to paste, copied", copied == ["Halfway through Path <b>Book: 4 of 8 sets. duecrew.com"]
                      and g.toasts[-1] == "Copied.", copied)
                items[1][1]()
                pic, priv = made[-1] if made else ({}, None)
                d = pic.get("data") or {}
                check("glue: as a picture: the plan card, on its way (Halfway, the sets so far, the cards I've seen), story only",
                      pic.get("kind") == "plan" and pic.get("sizes") == ("story",) and d.get("brow") == "Halfway" and d.get("sets") == 8
                      and d.get("done") == 4 and d.get("cards") == 7 and d.get("cap") is False and priv == S.privacy(g.box["cfg"]), pic)
                k = len(menus)
                send(f"planjoyshare:{pid}:threeq")
                send(f"planjoyshare:{pid}:nope")
                check("glue: Share on a line that isn't there, or isn't one: nothing", len(menus) == k)
                swaps = len(g.swaps)
                dc._on_js(False, f"duecrew:planjoyx:{pid}:half", DeckBrowser())
                check("glue: × without the board's key (a page before's): nothing", len(g.swaps) == swaps
                      and not F._pcfg()["joy"][pid]["miles"]["half"].get("x"))
                send(f"planjoyx:{pid}:half")
                card = F.board_view(g.box["cfg"])["cards"][0]
                check("glue: × takes the line off for today, and the card's drawn again", card["joy"]["line"] is None and len(g.swaps) == swaps + 1)
                _seen(conn, 8, 9, 10, 11)
                g.progress()
                card = F.board_view(g.box["cfg"])["cards"][0]
                check("glue: every set done: the finish waits for its show; the card says it in its head and its line; the closet counts it",
                      card["joy"]["fin"]["sets"] == 8 and card["joy"]["show"] and card["sub"].startswith("all 8 sets done · ")
                      and done_ids == [pid], (card["joy"], card["sub"], done_ids))
                A._state["board_shown"] = True
                k = len(sent)
                played = F.joy_show()
                show = [s for s in sent[k:] if "DCShow.finish" in s]
                check("glue: the next board draw plays its show over the Decks screen (show.js), the plan's name as text",
                      played and len(show) == 1 and '"name": "Path <b>Book"' in show[0] and "textContent" not in show[0].split("var D = ")[1][:200]
                      and f"duecrew:planjoyshare:{pid}:fin" in show[0], sent[k:][:1])
                check("glue: once a plan: the next draw, no show", F.joy_show() is False and len([s for s in sent if "DCShow.finish" in s]) == 1)
                send(f"planjoyshare:{pid}:fin")
                menus[-1][1][1]()
                pic = made[-1][0]
                check("glue: the finish's Share: the picture, finished, Pip in its new grad cap",
                      pic["data"]["brow"] == "Finished" and pic["data"]["done"] == 8 and pic["data"]["cap"] is True, pic["data"])
                menus[-1][0][1]()
                check("glue: …or its words", copied[-1].startswith("Finished Path <b>Book: 8 sets, 11 cards, "), copied[-1])
            finally:
                F._joy_menu = saved_menu
                sys.modules["due_crew.ui"].copy_text = saved_copy
                if real_dlg is None:
                    sys.modules.pop("due_crew.ui.share_card_dialog", None)
                else:
                    sys.modules["due_crew.ui.share_card_dialog"] = real_dlg
            check("glue: none of it asked anything of the server (a refresh and a sync stay one request each)", len(store.log) == n,
                  store.log[n:])
            check("glue: and none of it is sent: the sync's plan progress is the same shape as ever",
                  "joy" not in json.dumps(F.to_send(F.followed(), A._state.get("plan_progress") or {})))
    finally:
        m.state, m.web, A._decks[0], rooms.cfg, A._state["board_shown"], CF.note_plan_done = saved


def test_finish_show():
    view = {"pid": "p1", "name": "Path </script> Book", "sets": 19, "cards": 2046, "weeks": 6, "a": ["#2e7d32", "#7cc47f"],
            "pip": {"hop": "<svg class=\"sv\"></svg>", "jump": "<svg class=\"sv\"></svg>", "still": "<svg></svg>", "cap": CA.ART["gradcap"][0]}}
    js = board.finish_js(view)
    check("show: started by board_eval, its script (show.js) with it; the name and line as data, </ escaped",
          board.SHOW_JS[:200] in js and "window.DCShow.finish(D)" in js and "</script>" not in js and '"sub": "19 sets \\u00b7 2,046 cards \\u00b7 6 weeks"' in js
          and '"ms": 7000' in js and '"linger": 3000' in js, js[:400])
    check("show: seven seconds, the banner three more (shows.py), the board's tokens read off the page, Reduce motion asked",
          (shows.FINISH_SECONDS, shows.BANNER_SECONDS) == (7, 3) and "getPropertyValue('--dc-' + name)" in js
          and "prefers-reduced-motion: reduce" in js)
    init = open(os.path.join(REPO, "due_crew", "__init__.py"), encoding="utf-8").read()
    did = init[init.index("def _on_did_render"):init.index("def _last_studied")]
    check("show: at a board draw, after any cheers landing with it: their show plays first, the finish waits for it to end",
          "document.getElementById('dc-show') && n < 40" in js and did.index("_play_cheers()") < did.index("_joy_show()")
          and "_play_cheers()\n        _joy_show()" in init and "if not _pending_cheers:  # cheers about to land play first" in init)
    off = board.finish_js(dict(view, pip=None))
    check("show: Pip off: no Pip, no motion sheet", '"pip": null' in off and "D.sevcss = null" in off)
    sj = board.SHOW_JS
    fin = sj[sj.index("  function finish(data)"):sj.index("  window.DCShow = {")]
    ban = sj[sj.index("  function banner(still)"):sj.index("  function finish(data)")]
    check("show: not one of the twelve (it's no cheer): its own DCShow.finish", "finish: finish," in sj
          and "finish" not in shows.SHOWS and "SHOW.finish" not in sj)
    check("show: a click anywhere (but its Share) or Esc ends it, as a cheer's; it ends on its own at ten seconds",
          'e.key === "Escape"' in fin and 'closest(".dcs-click")' in fin and "end(ms + linger)" in fin)
    check("show: Reduce motion: the banner alone, Pip still in its cap; no dim, no path", "if (D.rm) { banner(true); end(ms + linger); return true; }" in fin
          and fin.index("if (D.rm)") < fin.index("dim(0.55, ms)"))
    check("show: the name and its line go in as text; its Share sends with the board's key",
          'textContent = "Finished " + D.name' in ban and "s.textContent = D.sub" in ban and 'pycmd(D.share + "|" + window.dcBK)' in ban)
    if NODE:
        for name, code in (("show.js", sj), ("the finish's script", js)):
            r = subprocess.run([NODE, "--check", "-"], input=code, capture_output=True, text=True)
            check(f"show: {name} is valid JS", r.returncode == 0, r.stderr[:400])


def test_motion():
    js = open(os.path.join(REPO, "due_crew", "motion.js"), encoding="utf-8").read()
    check("motion: one file, the board's and the site's", js == open(os.path.join(REPO, "site", "public", "motion.js"), encoding="utf-8").read())
    joy = js[js.index("  var JOY = {"):js.index("  M.joy = function")]
    check("motion: each joy the board draws has its move (pop, caught, spark, line, tada, go)",
          all(f"    {k}: function (el, d)" in joy for k in ("pop", "caught", "spark", "line", "tada", "go")))
    mj = js[js.index("  M.joy = function"):js.index("  // 32: Copied")]
    check("motion: after every draw; once an element; from how long it's been out; nothing with Reduce motion or on a ghost",
          "    M.joy(root);\n  };" in js and "!M.ok()" in mj and "el.__dcJoy" in mj and 'getPropertyValue("--ago")' in mj
          and "-Math.round(ago * 1000)" in mj and '[data-dc-ghost]' in mj)
    check("motion: transforms and opacity, and what it adds goes at its end", not re.search(r"[{,] (?:height|width|left|top|margin\w*):", joy) and "c.remove()" in js
          and "p.remove()" in joy and "box.remove()" in js)
    if not NODE:
        print("SKIP motion in node: no node")
        return
    # M.joy on a small DOM: each data-joy element plays, from its --ago, once; Reduce motion, none
    dom = r"""
    function El(tag, attrs) { this.tagName = tag; this.kids = []; this.parentNode = null; this.attrs = attrs || {}; this.anims = [];
      var self = this; this.style = { cssText: "", getPropertyValue: function (k) { return (self.attrs.style || "").indexOf(k) >= 0 ? (self.attrs.style.split(k + ":")[1] || "").split(";")[0] : ""; } }; }
    El.prototype.getAttribute = function (k) { return this.attrs[k] === undefined ? null : this.attrs[k]; };
    El.prototype.setAttribute = function (k, v) { this.attrs[k] = String(v); };
    El.prototype.appendChild = function (c) { c.parentNode = this; this.kids.push(c); return c; };
    El.prototype.insertBefore = function (c) { return this.appendChild(c); };
    El.prototype.remove = function () { var p = this.parentNode; if (p) { p.kids = p.kids.filter(function (x) { return x !== this; }, this); } this.parentNode = null; };
    El.prototype.all = function () { var out = []; this.kids.forEach(function (k) { out.push(k); out = out.concat(k.all()); }); return out; };
    El.prototype.querySelectorAll = function (s) { return this.all().filter(function (e) { return s === "[data-joy]" ? e.attrs["data-joy"] : false; }); };
    El.prototype.querySelector = function (s) { var c = s.slice(1); return this.all().filter(function (e) { return (e.attrs["class"] || "") === c; })[0] || null; };
    El.prototype.closest = function () { return null; };
    El.prototype.getBoundingClientRect = function () { return { left: this.attrs.x ? +this.attrs.x : 0, top: 0, width: 30, height: 8 }; };
    Object.defineProperty(El.prototype, "previousElementSibling", { get: function () { var k = this.parentNode ? this.parentNode.kids : []; var i = k.indexOf(this); return i > 0 ? k[i - 1] : null; } });
    Object.defineProperty(El.prototype, "offsetHeight", { get: function () { return 10; } });
    El.prototype.animate = function (kf, o) { var a = { kf: kf, o: o, onfinish: null, oncancel: null }; this.anims.push(a); log.push([this.attrs["data-joy"] || this.attrs["class"] || this.tagName, o.delay || 0, o.duration]); return a; };
    var log = [], reduce = false;
    var document = { createElement: function (t) { return new El(t); }, addEventListener: function () {}, getElementById: function () { return null; },
                     querySelector: function () { return null; } };
    var window = { matchMedia: function () { return { matches: reduce }; } };
    var sessionStorage = { getItem: function () { return null; }, setItem: function () {} };
    function getComputedStyle() { return { opacity: "1", getPropertyValue: function () { return ""; } }; }
    var performance = { now: function () { return 0; } };
    function requestAnimationFrame() {}
    """
    run = r"""
    var root = new El("div", {}), path = root.appendChild(new El("div", { "class": "ppath" }));
    path.appendChild(new El("i", { "class": "d", x: "0" }));
    var seg = path.appendChild(new El("i", { "class": "d t", "data-joy": "pop", style: "--ago:1.25s", x: "34" }));
    seg.appendChild(new El("span", { "class": "jpp" }));
    var tada = root.appendChild(new El("span", { "class": "jta", "data-joy": "tada", style: "--ago:0.00s" }));
    window.dcMotion.joy(root);
    var first = log.slice(); log.length = 0;
    window.dcMotion.joy(root);
    var twice = log.slice(); log.length = 0;
    var r2 = new El("div", {}); r2.appendChild(new El("i", { "data-joy": "pop", style: "--ago:0s" }));
    reduce = true; window.dcMotion.joy(r2);
    console.log(JSON.stringify({ first: first, twice: twice, still: log }));
    """
    r = subprocess.run([NODE, "-e", dom + js + run], capture_output=True, text=True, timeout=60)
    try:
        got = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        got = None
    check("motion in node: it runs", got is not None, (r.stdout[-400:], r.stderr[-1200:]))
    if got is None:
        return
    check("motion in node: a set done: its fill, its squash, its seven squares, Pip's five seconds, each from its --ago",
          any(x[0] == "jpp" and x[1] == -1250 and x[2] == 5000 for x in got["first"])
          and len([x for x in got["first"] if x[0] == "b" and x[1] == -870 and x[2] == 1100]) == 7
          and any(x[0] == "b" and x[1] == -1250 and x[2] == 385 for x in got["first"]) and any(x[0] == "pop" and x[2] == 220 for x in got["first"]), got["first"])
    check("motion in node: caught up's 🎉 pops and its bits fly", any(x[0] == "tada" and x[2] == 500 for x in got["first"])
          and len([x for x in got["first"] if x[0] == "b" and x[1] == 500]) == 6, got["first"])
    check("motion in node: once an element (a second draw of the same page plays nothing); Reduce motion, nothing", got["twice"] == []
          and got["still"] == [], (got["twice"], got["still"]))


# ---- Pip's closet: three new things ----

def test_closet():
    ks = {t["k"]: t for t in C.THINGS}
    check("closet: the Finisher's ribbon (body), the Folded map and the Kite (hand), with the Plans",
          [ks[k]["slot"] for k in ("rosette", "map", "kite")] == ["body", "hand", "hand"]
          and all(ks[k]["group"] == "Plans" for k in ("rosette", "map", "kite", "gradcap", "backpack")))
    check("closet: their rules: three plans done; someone followed a plan you made; gave everyone a day on a plan you write",
          ks["rosette"]["need"] == ("plan_done", 3) and ks["rosette"]["rule"] == "3 plans, every set done"
          and ks["map"]["need"] == ("followed", 1) and ks["map"]["rule"] == "Someone followed a plan you made"
          and ks["kite"]["need"] == ("gave_day", 1) and ks["kite"]["rule"] == "Gave everyone a day on a plan you write")
    check("closet: the Grad cap stays the first finished plan's", ks["gradcap"]["need"] == ("plan_done", 1)
          and C.earned({"plan_done": 1}) == ["gradcap"] and set(C.earned({"plan_done": 3, "followed": 1, "gave_day": 1})) >= {"gradcap", "rosette", "map", "kite"})
    check("closet: two plans done, the ribbon's close (its bar)", ("rosette", 2, 3, "plans finished") in C.near({"plan_done": 2}, {})
          and C.progress({"plan_done": 2}, {})["rosette"] == (2, 3))
    kite = sev.svg("hello", look=["kite"])
    check("closet: drawn in its style: the kite in the hand, swaying as the balloon does; the map in the hand; the ribbon on the body",
          'class="cl-bal"' in CA.ART["kite"][0] and CA.ART["kite"][0][:60] in kite.split('class="sv-armR">', 1)[1]
          and CA.ART["map"][0][:60] in sev.svg("idle", look=["map"]) and CA.ART["rosette"][0][:60] in sev.svg("idle", look=["rosette"])
          and C.wear(["kite"], "map") == ["map"] and C.wear(["medal"], "rosette") == ["rosette"])
    check("closet: the site's kit has them (tools/gen_sev_js.py run)", all(f'"{k}"' in open(os.path.join(REPO, "site", "public", "sev.js"),
                                                                                         encoding="utf-8").read() for k in ("rosette", "map", "kite")))
    plans = [{"id": "p1", "owner": "me", "followers": 2, "doc": {"units": []}}, {"id": "p2", "owner": "dre", "followers": 9, "doc": {"units": []}}]
    bf = CF.board_facts({}, [], "me", plans, {}, "2026-11-05", {})
    check("closet: followed: a plan of mine I follow with someone besides me (its followers count me); another's doesn't",
          bf["followed"] == 1 and CF.board_facts({}, [], "me", plans[:1] and [dict(plans[0], followers=1)], {}, "2026-11-05", {})["followed"] == 0
          and CF.board_facts({}, [], "me", plans[1:], {}, "2026-11-05", {})["followed"] == 0, bf)
    fin = CF.board_facts({}, [], "me", [], {}, "2026-11-05", {}, finished=["a", "b", "a"], followed=1)
    check("closet: plans done counted from the tally too (a plan stopped once finished still counts), each once; the window's tally too",
          fin["plan_done"] == 2 and fin["followed"] == 1, fin)
    t = CF.clean_tallies({"plans_done": ["p1", 5, "p2"], "followed": 1, "gave_day": 3, "nope": 1})
    check("closet: the tallies (wrap.json, this computer's, never sent)", t == {"plans_done": ["p1", "p2"], "followed": 1, "gave_day": 3}, t)
    from due_crew.planner import flow as PF
    got = []
    saved = CF.note_followed
    CF.note_followed = lambda: got.append(1)
    try:
        PF.noted_followers([{"id": "a", "role": "owner", "followers": 1, "following": True}, {"id": "b", "role": "follower", "followers": 5}])
        quiet = len(got)
        PF.noted_followers([{"id": "a", "role": "owner", "followers": 2, "following": True}])
        PF.noted_followers([{"id": "c", "role": "owner", "followers": 1}])
    finally:
        CF.note_followed = saved
    check("closet: Your plans' list (the one request it makes anyway): a plan I made with someone following besides me, the map",
          quiet == 0 and len(got) == 2, got)


# ---- the picture: sharecard.py's plan card, cards.js its twin ----

def _measure(s, px, w):
    return len(s) * px * 0.55


def test_picture():
    d = S.plan("Path Book", 19, 19, 2046, 6, cap=True)
    W, H, ops = S.draw("plan", "story", d, {"cards": True}, "light", _measure)
    of = lambda kind: [o for o in ops if o[0] == kind]  # noqa: E731
    segs = [o for o in of("rect") if o[2] == S.PLAN_TOP]
    sv = of("sev")
    check("picture: story size; the path, a segment a set, all done in the card's green",
          (W, H) == (1080, 1350) and len(segs) == 19 and {o[6] for o in segs} == {S.LOOKS["light"]["g"]}, len(segs))
    check("picture: Pip hops each set and stands on the last, in its new grad cap",
          len(sv) == 1 and sv[0][1] == "hop" and sv[0][6] == ("gradcap",) and sv[0][4] == S.PLAN_SEV[0]
          and len(of("dot")) > 18 * 2 and abs(sv[0][3] + sv[0][4] * S.SEV_FEET - S.PLAN_TOP) < 1e-9, sv)
    words = [o[1] for o in of("text")]
    check("picture: FINISHED, the plan, 19 sets · 2,046 cards · 6 weeks, duecrew.com",
          words == ["FINISHED", "Path Book", "19 sets · 2,046 cards · 6 weeks", "duecrew.com"], words)
    off = [o[1] for o in S.draw("plan", "story", d, {"cards": False}, "light", _measure)[2] if o[0] == "text"]
    check("picture: its card count follows its switch (Privacy's Reviews to start)", "19 sets · 6 weeks" in off
          and S.switches("plan", d, {"reviews": False})[0][:4] == ("cards", "How many cards", "off in Privacy", False))
    half = S.draw("plan", "story", S.plan("Path Book", 19, 10, 1033, 6, brow="Halfway"), {"cards": True}, "dark", _measure)[2]
    hs = [o for o in half if o[0] == "sev"][0]
    check("picture: on its way (a milestone's Share): the path so far, Pip on the set I'm on, no cap; HALFWAY, 10 of 19 sets · 1,033 cards",
          len(hs) == 6 and hs[4] == S.PLAN_SEV[1] and [o[1] for o in half if o[0] == "text"][:3] == ["HALFWAY", "Path Book", "10 of 19 sets · 1,033 cards"]
          and len([o for o in half if o[0] == "rect" and o[6] == S.LOOKS["dark"]["g"]]) == 10)
    check("picture: the last set's morning says its name", S.plan_sub(S.plan("P", 19, 18, 1, 6, brow="The last set", last="19 · Skin"), {}) == "19 · Skin, today")
    off_pip = S.draw("plan", "story", S.plan("Path Book", 19, 19, 2046, 6, sev=False), {"cards": True}, "light", _measure)[2]
    check("picture: Pip off (Settings › Pip): the path, no Pip, no trail", not [o for o in off_pip if o[0] in ("sev", "dot")])
    long = S.draw("plan", "story", S.plan("x" * 90, 140, 140, 9000, 30, cap=True), {"cards": True}, "light", _measure)[2]
    check("picture: a long plan's sets close up, too close for a trail; its name fits or ends in …",
          len([o for o in long if o[0] == "rect" and o[2] == S.PLAN_TOP]) == 140 and not [o for o in long if o[0] == "dot"]
          and [o for o in long if o[0] == "text"][1][1].endswith("…"))
    sd = open(os.path.join(REPO, "due_crew", "ui", "share_card_dialog.py"), encoding="utf-8").read()
    check("picture: the add-on draws Pip with what the card puts on it, over my look (a costume off; tools/dialogs.py paints it)",
          "def _sev(p, pose, color, rect, wear=()):" in sd and "closet.COSTUME" in sd and "op[6] if len(op) > 6 else ()" in sd)
    js = open(os.path.join(REPO, "site", "public", "cards.js"), encoding="utf-8").read()
    cap = re.search(r"\n  const SEV_CAP = '([^']*)';\n", js)
    check("picture: cards.js draws sev.py's Pip in its cap: its copy is sev.still('hop', '%A%', look=['gradcap']) to the byte",
          cap is not None and cap.group(1) == sev.still("hop", "%A%", look=["gradcap"]))
    if not NODE:
        print("SKIP the plan card twin: no node")
        return
    expose = "return { open, short, SIZES, MONTHS };"
    cases = [S.plan("Path Book", 19, 19, 2046, 6, cap=True), S.plan("Path Book", 19, 10, 1033, 6, brow="Halfway"),
             S.plan("Path Book", 19, 18, 1919, 6, brow="The last set", last="19 · Skin"),
             S.plan("A plan with a name long enough to be cut short on the card", 140, 140, 9120, 31, cap=True),
             S.plan("One", 1, 1, 12, 1, cap=True), S.plan("Off", 19, 19, 2046, 6, sev=False, code="N4APULM2"),
             {"name": "Path Book", "cards": 2046, "weeks": 6, "code": "N4APULM2"}]  # duecrew.com's builder, as it calls it today
    draws = [[d, look, on] for d in cases for look in ("light", "dark") for on in ({"cards": True, "code": True}, {"cards": False})]
    prog = (
        "globalThis.Image = class { set src(v) { this.s = v; Promise.resolve().then(() => this.onload()); } };\n"
        + js.replace(expose, "return { open, short, SIZES, MONTHS, DRAW, LOOKS, planHops };") + "\n"
        "const fake = () => { const log = []; let font = '', at = null;\n"
        "  return { log, get font() { return font; }, set font(f) { font = f; },\n"
        "    measureText(s) { return { width: [...s].length * Number(/([0-9.]+)px/.exec(font)[1]) * 0.55 }; },\n"
        "    fillText(s, x, y) { log.push(['text', s, x, y]); }, fillRect() {},\n"
        "    arc(x, y, r) { log.push(['dot', x, y, r, this.fillStyle]); }, moveTo(x, y) { at = [x, y]; },\n"
        "    fill() { if (at) log.push(['rect', at[0], at[1], this.fillStyle]); at = null; },\n"
        "    drawImage(img, x, y, w, h) { log.push([img.s.startsWith('data:') ? 'sev' : 'logo', x, y, w, h, decodeURIComponent(img.s)]); },\n"
        "    beginPath() { at = null; }, arcTo() {}, closePath() {}, stroke() {}, setLineDash() {} }; };\n"
        "const { draws } = JSON.parse(require('fs').readFileSync(0, 'utf8'));\n"
        "(async () => { const out = [];\n"
        "  for (const [d, look, on] of draws) { const c = fake(); const [W, H] = Cards.SIZES.story;\n"
        "    await Cards.DRAW.plan(c, W, H, 'story', d, on, Cards.LOOKS[look], look); out.push(c.log); }\n"
        "  console.log(JSON.stringify(out)); })();")
    run = subprocess.run([NODE, "-e", prog], input=json.dumps({"draws": draws}), capture_output=True, text=True, timeout=60)
    try:
        got = json.loads(run.stdout)
    except ValueError:
        got = None
    check("picture twin: cards.js runs the plan card in node", got is not None, run.stdout[-300:] + run.stderr[-1500:])
    if got is None:
        return
    close = lambda a, b: len(a) == len(b) and all(abs(x - y) < 1e-6 for x, y in zip(a, b))  # noqa: E731
    bad = []
    for (d, look, on), log_ in zip(draws, got):
        ops = S.draw("plan", "story", d, on, look, _measure)[2]
        want = {"text": [(o[1], o[2], o[3]) for o in ops if o[0] == "text"],
                "rect": [(o[1] + o[5], o[2], o[6]) for o in ops if o[0] == "rect"],
                "dot": [(o[1], o[2], o[3], o[4]) for o in ops if o[0] == "dot"],
                "sev": [(o[2], o[3], o[4], o[4], "data:image/svg+xml;charset=utf-8," + sev.still(o[1], o[5], look=list(o[6]) if len(o) > 6 else None))
                        for o in ops if o[0] == "sev"]}
        have = {k: [tuple(x[1:]) for x in log_ if x[0] == k] for k in want}
        ok = (len(want["text"]) == len(have["text"]) and all(a[0] == b[0] and close(a[1:], b[1:]) for a, b in zip(want["text"], have["text"]))
              and len(want["rect"]) == len(have["rect"]) and all(close(a[:2], b[:2]) and a[2] == b[2] for a, b in zip(want["rect"], have["rect"]))
              and len(want["dot"]) == len(have["dot"]) and all(close(a[:3], b[:3]) and a[3] == b[3] for a, b in zip(want["dot"], have["dot"]))
              and len(want["sev"]) == len(have["sev"]) and all(close(a[:4], b[:4]) and a[4] == b[4] for a, b in zip(want["sev"], have["sev"])))
        if not ok:
            bad.append((d.get("name"), look, on, {k: (want[k][:3], have[k][:3]) for k in want if want[k] != have[k]}))
    check("picture twin: cards.js lays the plan card out as sharecard does: path, trail, Pip (and its cap), words, its switches",
          not bad and len(got) == len(draws), bad[:1])


# ---- New plan's preview: the path, set by set ----

def test_new_plan_path():
    from due_crew.planner.webnew import NewPlan
    pv = NewPlan._path_view({"units": [{"id": "a", "opens": "2026-11-02"}, {"id": "b", "opens": "2026-12-11"}],
                             "events": [{"id": "x", "day": "2026-12-18", "name": "Exam"}]},
                            [{"opens": "2026-11-02"}, {"opens": "2026-12-11"}])
    check("new plan: the path's view: sets, the first one's day, its exam", pv == {"n": 2, "first": "Mon 2 Nov", "event": True,
                                                                                    "end": "Exam · Fri 18 Dec"}, pv)
    if not NODE:
        print("SKIP New plan's path in node: no node")
        return
    page = os.path.join(REPO, "due_crew", "planner", "page")
    css = open(os.path.join(page, "new.css"), encoding="utf-8").read()
    check("new plan: its segments come in one after another, only without Reduce motion; no Pip in the plan window",
          "@media (prefers-reduced-motion: no-preference)" in css and ".npath.jin i { animation: dcp-seg" in css
          and "sv" not in re.findall(r"\.([a-z-]+)", css[css.index("3.9.6"):]))
    prog = r"""
    var dcPlan = {};
    function El(tag) { this.tag = tag; this.kids = []; this.cls = ""; this.text = ""; this.attrs = {}; }
    function h(sel, attrs, kids) {
      var p = sel.split("."), el = new El(p[0] || "div"); el.cls = p.slice(1).join(" ");
      Object.keys(attrs || {}).forEach(function (k) { if (k === "text") { el.text = String(attrs[k]); } else if (k.slice(0, 2) !== "on") { el.attrs[k] = attrs[k]; } });
      (kids || []).forEach(function (c) { if (c) { el.kids.push(c); } });
      el.appendChild = function (c) { this.kids.push(c); return c; };
      el.addEventListener = function () {};
      return el;
    }
    var k = { h: h, btn: function (l) { return h("button.b", { text: l }); }, send: function () {}, dateInput: function () { return h("input"); } };
    """ + open(os.path.join(page, "new.js"), encoding="utf-8").read() + r"""
    function find(el, c) { if ((" " + el.cls + " ").indexOf(" " + c + " ") >= 0) { return el; } for (var i = 0; i < (el.kids || []).length; i++) { var f = el.kids[i] && el.kids[i].kids ? find(el.kids[i], c) : null; if (f) { return f; } } return null; }
    var r = { parts: [{ path: "x", name: "Path Book", sub: "19 chapters", cards: 2046, on: true }], only: [], pace: "by", daily: 52, by: "2026-12-11",
              days: [1, 1, 1, 1, 1, 0, 0], starts: "2026-11-02", ok: true, summary: "19 sets", dates: [{ n: 1, name: "Cell injury", when: "Mon 2 Nov", cards: 84 }],
              more: 18, path: { n: 19, first: "Mon 2 Nov", end: "Exam · Fri 18 Dec", event: true } };
    var n = { step: "resource", resource: r, decks: [], name: "", today: "2026-11-01" };
    var a = find(dcPlan.newPlan(n, k), "npath"), b = find(dcPlan.newPlan(n, k), "npath");
    r.path = { n: 7, first: "Mon 2 Nov", end: "Ends Fri 11 Dec", event: false };
    var c = find(dcPlan.newPlan(n, k), "npath"), d = find(dcPlan.newPlan(n, k), "nppl");
    console.log(JSON.stringify({ a: [a.cls, a.kids.length, a.kids.filter(function (x) { return x.tag === "em"; }).length, a.attrs["aria-label"]],
                                 b: b.cls, c: [c.cls, c.kids.length], d: d.kids.map(function (x) { return x.text; }) }));
    """
    r = subprocess.run([NODE, "-e", prog], capture_output=True, text=True, timeout=60)
    try:
        got = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        got = None
    check("new plan in node: the preview lays the plan out, a segment a set and its exam a diamond, read out in words",
          got and got["a"] == ["npath jin", 20, 1, "19 sets, then Exam · Fri 18 Dec"], (got, r.stderr[-800:]))
    check("new plan in node: drawn again the same, it doesn't lay itself out again; a new shape does; its first day and end under it",
          got and got["b"] == "npath" and got["c"] == ["npath jin", 7] and got["d"] == ["Mon 2 Nov", "Ends Fri 11 Dec"], got)


def main():
    for n in [n for n in list(globals()) if n.startswith("test_")]:
        globals()[n]()
    bad = [c for c in CHECKS if not c[1]]
    print(f"\n{len(CHECKS) - len(bad)}/{len(CHECKS)} checks passed")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
