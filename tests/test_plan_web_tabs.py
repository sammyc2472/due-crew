"""Insights and Settings in the HTML plan window (due_crew/planner/webtabs.py,
page/tabs.js), against a fake collection and the fake Worker (tests/fakes.py):
each tab's view for an author and a follower, every click sent as the page
sends it ("dcplan:" + JSON, a tabcmd), the questions it asks first (sheets),
and what it saves. The page itself runs too: plan.js and tabs.js in node on a
small stand-in for the DOM, every view and sheet drawn, every control fired,
and each message it sent back through the window. Standard library and node
only; tools/plan_preview.py renders the same tabs for the eye.

Run: python3 tests/test_plan_web_tabs.py
"""

import datetime
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import traceback
import types

HARNESS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HARNESS)
sys.path.insert(0, HARNESS)

import fakes  # noqa: E402

STORE = fakes.FakeWorker()
fakes.install_fake_requests(STORE)
fakes.install_fake_aqt()
sys.path.insert(0, REPO)

from due_crew import plans as P                    # noqa: E402
from due_crew.backend import api                    # noqa: E402
from due_crew import planner as PL                  # noqa: E402
from due_crew.planner import remote as PR           # noqa: E402
from due_crew.planner import webtabs as WT          # noqa: E402
from due_crew.planner.draft import Draft            # noqa: E402
from due_crew.planner.webface import WebFace        # noqa: E402
from due_crew.planner.webpage import colors, page_html  # noqa: E402

CHECKS = []
TODAY = datetime.date.today()
MON = TODAY - datetime.timedelta(days=TODAY.weekday())
R = "#Big_Step_1::#Path_Book"
PAGE = os.path.join(REPO, "due_crew", "planner", "page")


def check(name, cond, detail=""):
    CHECKS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond or detail == "" else f"\n     {detail}"))


def day(n):
    return (MON + datetime.timedelta(days=n)).isoformat()


for uid, name in (("sam", "Sammy"), ("dre", "Dre"), ("maya", "Maya"), ("kai", "Kai")):
    STORE.add_user(uid, name, code=uid.upper()[:3] + "123")
for a, b in (("sam", "maya"), ("sam", "kai")):
    STORE.befriend(a, b)
    STORE.befriend(b, a)
STORE.squads["sq1"] = {"name": "Night owls", "founder": "sam", "open": False}
STORE.members[("sq1", "sam")] = {"name": "Sammy"}


# ---- the Qt dialogs these tabs open, stood in for (they're Qt's, not the page's) ----

class _Lines:
    made = []

    def __init__(self, parent, title, lines, every=False):
        _Lines.made.append((parent, title, list(lines), every))

    def exec(self):
        return True

    def lines(self):
        return [{"k": "read", "t": "Chapter 3", "r": "024"}]


_shown = []
_dd = types.ModuleType("due_crew.planner.date_dialogs")
_dd.LinesDialog = _Lines
_mcp = types.ModuleType("due_crew.planner.mcp_dialog")
_mcp.show = lambda parent=None, ops=None: _shown.append(parent)
for _name, _mod in (("date_dialogs", _dd), ("mcp_dialog", _mcp)):
    sys.modules["due_crew.planner." + _name] = _mod
    setattr(PL, _name, _mod)

_printed = []
_print_exc = traceback.print_exc
traceback.print_exc = lambda *a, **k: _printed.append(1) or _print_exc(*a, **k)  # a handler's TypeError, as _on_cmd reports it


def client(uid):
    c = api.ApiClient(os.path.join(os.environ.get("TMPDIR", "/tmp"), f"dc-test-plan-web-tabs-{uid}.json"))
    c.session = {"user_id": uid, "token": STORE.session_for(uid), "display_name": uid.title(),
                 "last_ok": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    return c


def collection():
    conn = sqlite3.connect(":memory:")
    fakes.make_collection(conn)
    cid = 0
    for ch, parts in (("01_Cell_injury", ["Adaptations", "Injury"]), ("02_Inflammation", ["Acute", "Chronic"]),
                      ("03_Neoplasia", ["Nomenclature", "Progression"]), ("04_Hemostasis", ["Platelets", "Coagulation"])):
        for part in parts:
            for i in range(6):
                cid += 1
                seen = ch == "01_Cell_injury" and i < 3
                system = "Heme" if ch in ("03_Neoplasia", "04_Hemostasis") else "Cardio" if i % 2 else "Renal"
                fakes.add_card(conn, cid, 1, ctype=2 if seen else 0, queue=2 if seen else -1, ivl=9 if seen else 0,
                               tags=f"{R}::{ch}::{part} #Big_Step_1::^Systems::{system}" + (" #Big_Step_1::^High_Yield" if i % 2 else ""))
    col = fakes.FakeCol(conn, fakes.day_cutoff_for(TODAY))
    col.decks = fakes.FakeDecks({1: "Big Step 1"})
    return col


COL = collection()


class Ops:
    """What the window asks of the add-on, at once, on this test's store; a follow's steps recorded."""

    def __init__(self, cl, deck=True):
        self.cl, self.deck = cl, deck
        self.drafts, self.calls, self.loads, self.reopened, self.pages = {}, [], 0, [], []
        self.by = {}
        self.follow = None
        self.lesson = None    # None: this Anki hasn't the choice

    def today(self):
        return TODAY.isoformat()

    def context(self, plan, doc):
        return (P.DeckIndex(COL, 1), None, "named") if self.deck else (None, None, "")

    def my_doc(self, plan):
        return plan["doc"]

    def followed_here(self, pid, version=None):
        return False

    def load(self, owner, pid, done):
        self.loads += 1
        done(PR.load(self.cl, pid))

    def save(self, owner, pid, version, doc, summary, done):
        done(PR.save(self.cl, pid, version, doc, summary))

    def send(self, owner, pid, version, doc, summary, post, done):
        done(PR.save(self.cl, pid, version, doc, summary, post))

    def undo(self, owner, pid, version, done):
        done(PR.undo(self.cl, pid, version))

    def ask(self, owner, fn, done):
        try:
            got = fn(self.cl)
        except Exception:  # noqa: BLE001
            got = None
        done(got)

    def draft(self, pid):
        return Draft.from_json(pid, self.drafts.get(str(pid)))

    def keep_draft(self, pid, d):
        if d is None or not len(d):
            self.drafts.pop(str(pid), None)
        else:
            self.drafts[str(pid)] = json.loads(json.dumps(d.to_json()))

    def now_words(self):
        return "Tue 2:14 pm"

    def me(self):
        return self.cl.user_id

    def my_squads(self):
        return [{"id": "sq1", "name": "Night owls"}]

    def site_url(self, path):
        return "https://duecrew.com" + path

    def open_page(self, path):
        self.pages.append(path)

    def reopen(self, pid):
        self.reopened.append(pid)

    def map_by(self, did):
        return self.by.get(did)

    def set_map_by(self, did, key):
        self.by[did] = key

    # a follow, as plan_flow keeps it; each step recorded, and some move it
    def follow_state(self, pid):
        return dict(self.follow) if self.follow else None

    def held_count(self, pid):
        return 7

    def in_team(self, pid):
        return False

    def can_reset(self, pid):
        return True

    def lesson_deck_on(self, pid):
        return self.lesson

    def follow_deck_name(self, pid):
        return "Big Step 1" if self.follow else ""

    def start_here(self, code):
        """Start it here… (the Follow window on its code): say it followed."""
        self.calls.append(("start_here", code))
        self.follow = {"id": self.cl.session.get("_pid_started"), "name": "mine", "shift": 0, "skipped": [], "own": "", "early": 0,
                       "paused": False}

    def set_lesson_deck(self, pid, on):
        self.calls.append(("set_lesson_deck", pid, on))
        self.lesson = bool(on)

    def copy_plan(self, owner, pid, said):
        self.calls.append(("copy_plan", pid))
        said("copied")

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def step(pid, *args):
            self.calls.append((name, pid) + args)
            if name == "set_shift" and self.follow is not None:
                self.follow["shift"] = 3  # (plan_flow asks how many; say three)
        return step


class Face(WebFace):
    def __init__(self, cl, select=None, tab=None, ops=None):
        self.js, self.copied, self.later_fns = [], None, []
        self.web_init(COL, PR.my_plans(cl), ops or Ops(cl), select, tab, {})
        self._ready = True
        if self.pid:
            self.load(self.pid)

    def eval_js(self, js):
        self.js.append(js)

    def close(self):
        self.closed = True

    def copy(self, text):
        self.copied = text

    def after(self, ms, fn):
        self.later_fns.append(ms)
        fn()

    def click(self, c, **a):
        self._on_cmd("dcplan:" + json.dumps({"c": c, "a": a}))

    def tab_click(self, _cmd, **args):
        """A click on Insights or Settings, as tabs.js sends it."""
        self.click("tabcmd", name=_cmd, args=args)

    def last(self, what="show"):
        for js in reversed(self.js):
            if js.startswith(f"dcPlan.{what}("):
                return json.loads(js[len(f"dcPlan.{what}("):-1])
        return None

    def sheet_yes(self, sh, **fields):
        """A sheet's yes, as plan.js sends it: its cmd, its args and its fields."""
        self.click(sh["cmd"], **dict(sh.get("args") or {}, **fields))


_codes = [0]


def plan(units, events=(), owner="sam", name="Path Book, high yield", daily=40):
    _codes[0] += 1  # its own code (the fake's own repeats once a plan is taken down)
    code = "".join(fakes.SQUAD_ALPHABET[(_codes[0] // 32 ** i) % 32] for i in range(7)) + "Z"
    pid, code = STORE.add_plan(owner, name, "Big Step 1", units, code=code)
    STORE.plans[pid]["doc"]["events"] = list(events)
    for u, had in zip(STORE.plans[pid]["doc"]["units"], units):  # (a lesson's quiz, once the quizzes are in)
        if had.get("for"):
            u["for"] = had["for"]
    STORE.plans[pid]["doc"]["pace"] = {"mode": "daily", "days": [1, 1, 1, 1, 1, 0, 0], "daily": daily}
    return pid, code


def units():
    return [{"id": "u1", "name": "Cell injury", "opens": day(-7), "tags": [f"{R}::01_Cell_injury"], "for": "e1"},
            {"id": "u2", "name": "Inflammation", "opens": day(-6), "tags": [f"{R}::02_Inflammation"], "for": "e1"},
            {"id": "u3", "name": "Neoplasia", "opens": day(1), "tags": [f"{R}::03_Neoplasia"]},
            {"id": "u4", "name": "Hemostasis", "opens": day(8), "tags": [f"{R}::04_Hemostasis::Platelets"]}]


EVENTS = [{"id": "e1", "day": day(-3), "name": "Heme quiz"}, {"id": "e2", "day": day(11), "name": "Exam"}]


# ---- Insights ----

def test_insights_an_authors():
    pid, _code = plan(units(), EVENTS)
    w = Face(client("sam"), select=pid, tab="insights")
    v = w.last()
    ins = v and v.get("insights")
    check("tabs: Insights opens on its tab, worked out (not the page's Loading…)", v["tab"] == "insights" and ins and "work" in ins, v and v.get("tab"))
    wk = ins["work"]
    check("tabs: workload a row a week from the plan's first to its end, this week said",
          [r["week"].split(",")[0] for r in wk["rows"]] == ["Week 1", "Week 2", "Week 3"] and any(", this week" in r["week"] for r in wk["rows"]),
          [r["week"] for r in wk["rows"]])
    check("tabs: the pace is the plan's own (40 a day), a line down the new cards' column: not the cleaned doc's",
          "your pace: 40" in wk["newHead"] and wk["line"] is not None, (wk["newHead"], wk["line"]))
    check("tabs: each week says what the Qt tab says (insights.py's words), the quiz beside its week",
          any(r["events"] == "Heme quiz" for r in wk["rows"]) and all(r["tip"].startswith("Week ") for r in wk["rows"])
          and wk["words"].endswith("a day.") and "new cards over 3 weeks" in wk["words"], wk["words"])
    dk = ins["deck"]
    check("tabs: how much of the deck: the plan's cards of the deck's, an author's bar one part",
          dk["words"].startswith("42 of Big Step 1's 48 cards") and len(dk["bar"]) == 1 and "key" not in dk, dk["words"])
    names = [r["name"] for r in dk["parts"]["rows"]]
    check("tabs: each part a row (the map's way), what it leaves out said",
          {"Cell injury", "Inflammation", "Neoplasia"} <= set(names) and dk["parts"]["rows"][0]["words"].endswith("all"), dk["parts"])
    has = ins["has"]
    check("tabs: what's in it: each quiz and exam with what it tests, in sets",
          [x["name"] for x in has["exams"]] == ["Heme quiz", "Exam"] and has["exams"][0]["words"] == "24 cards from 2 sets"
          and has["exams"][1]["words"].startswith("everything:"), has["exams"])
    check("tabs: its biggest lessons, most cards first", [x["name"] for x in has["big"]][:3] == ["Cell injury", "Inflammation", "Neoplasia"]
          and has["big"][0]["key"] == ["date", "u1"], has["big"])
    got = WT.insights(w)
    check("tabs: worked out once a change: the same answer while nothing changed", got is WT.insights(w))
    w.click("rename", uid="u3", name="Neoplasia and tumours")
    check("tabs: and again after a change", WT.insights(w) is not got and any(x["name"] == "Neoplasia and tumours" for x in WT.insights(w)["has"]["big"]))
    if dk.get("ways"):
        other = next(x for x in dk["ways"] if not x["on"])
        w.tab_click("map_by", key=other["key"])
        dk2 = w.last()["insights"]["deck"]
        check("tabs: By ▾ picks another way, kept for the board's map too (ops.set_map_by)",
              w.ops.by.get(1) == other["key"] and next(x for x in dk2["ways"] if x["on"])["key"] == other["key"], dk2.get("by"))
    else:
        check("tabs: the deck splits more than one way here", False, dk)
    w.tab_click("go", key=["event", "e1"])
    v = w.last()
    check("tabs: a quiz clicked: that one on the Plan tab", v["tab"] == "plan" and v["picked"] == ["event", "e1"], (v["tab"], v["picked"]))
    w.tab_click("go", key=["date", "nope"])
    w.tab_click("go", key="date")
    check("tabs: a lesson that isn't on the plan, or no key: nothing", w.last()["picked"] == ["event", "e1"])


def test_insights_nothing_to_count():
    pid, _code = plan([{"id": "z1", "name": "Later", "opens": day(3), "tags": []}], name="Empty")
    w = Face(client("sam"), select=pid, tab="insights", ops=Ops(client("sam"), deck=False))
    check("tabs: its deck not in this Anki: said, nothing counted", "deck isn't in this Anki" in w.last()["insights"]["none"])
    pid, _code = plan([], name="No lessons")
    w = Face(client("sam"), select=pid, tab="insights")
    check("tabs: no sets yet: said", w.last()["insights"]["none"] == "Nothing to count yet: the plan has no sets.", w.last()["insights"])


def test_insights_a_followers():
    pid, code = plan(units(), EVENTS, owner="dre", name="MS2 Block 2")
    sam = client("sam")
    sam.follow_plan(code)
    w = Face(sam, select=pid, tab="insights")
    dk = w.last()["insights"]["deck"]
    check("tabs: a follower's Insights: what I've seen, then what's to go", len(dk["bar"]) == 2 and dk["key"] == "You've seen 6 of them; 36 to go.",
          dk.get("key"))


# ---- Settings, an author's ----

def test_settings_the_plan():
    pid, code = plan(units(), EVENTS)
    STORE.plans[pid]["line"] = "One a week"
    w = Face(client("sam"), select=pid, tab="settings")
    s = w.last()["settings"]
    check("tabs: an author's Settings: its name, line, code, followers, AI app, as settings_tab says them",
          s["role"] == "author" and s["owner"] and s["name"] == "Path Book, high yield" and s["line"] == "One a week"
          and s["code"] == code and s["following"] == "Nobody follows it yet" and s["every"] == "None" and s["ai"] in ("On", "Off", ""), s)
    sh = s["shape"]
    check("tabs: its dates and pace are the plan's: starts on its first lesson, up to 40 a day, Mon–Fri",
          sh["start"] == day(-7) and sh["mode"] == "daily" and sh["daily"] == 40 and sh["days"] == [1, 1, 1, 1, 1, 0, 0]
          and sh["end"] == "none" and sh["preview"] is None and sh["go"] == "Save", sh)
    check("tabs: Ends with: each quiz or exam, a day, nothing yet", [x["v"] for x in sh["ends"]] == ["event:e1", "event:e2", "day", "none"], sh["ends"])
    w.tab_click("shape", key="day", value=5)
    sh = w.last()["settings"]["shape"]
    check("tabs: a study day ticked: said under the rows, nothing saved yet", sh["days"][5] == 1 and sh["preview"]
          and sh["preview"]["parts"] == [["", "No set moves."]] and STORE.plans[pid]["doc"]["pace"]["days"][5] == 0, sh["preview"])
    w.tab_click("shape_save")
    pace = STORE.plans[pid]["doc"]["pace"]
    check("tabs: Save: the plan's pace with Saturday, its mode and 40 a day kept (the full doc's, not the cleaned one's)",
          pace["days"] == [1, 1, 1, 1, 1, 1, 0] and pace["mode"] == "daily" and pace["daily"] == 40
          and w.last()["settings"]["shape"]["preview"] is None, pace)
    w.tab_click("shape", key="start", value=day(0))
    sh = w.last()["settings"]["shape"]
    words = "".join(x[1] for x in sh["preview"]["parts"])
    check("tabs: a new start: what it moves, said first (the sets and quizzes, the ones open already)",
          "Saving moves 4 sets and 2 quizzes or exams." in words and "of them opened already" in words, words)
    w.tab_click("shape_back")
    check("tabs: Put it back: the rows as the plan has them", w.last()["settings"]["shape"]["start"] == day(-7)
          and w.last()["settings"]["shape"]["preview"] is None)
    w.tab_click("shape", key="end", value="event:e2")
    w.tab_click("shape", key="taper", value=3)
    w.tab_click("shape", key="catchup", value=4)
    w.tab_click("shape", key="mode", value="end")
    sh = w.last()["settings"]["shape"]
    check("tabs: ends with the exam, 3 days of no new cards, every 4th week, fit to the end: said before it goes in",
          sh["end"] == "event:e2" and sh["taper"] == 3 and sh["catchup"] == 4 and sh["mode"] == "end"
          and "no new cards" in "".join(x[1] for x in sh["preview"]["parts"]), sh["preview"])
    w.tab_click("shape_save")
    doc = STORE.plans[pid]["doc"]
    check("tabs: and saved as one", doc.get("end") == day(11) and doc["phases"] == {"catchup": 4, "taper": 3} and doc["pace"]["mode"] == "end", doc.get("phases"))
    for k, val in (("start", "not a day"), ("end", "event:nope"), ("day", 9), ("mode", "fast"), ("daily", "lots")):
        w.tab_click("shape", key=k, value=val)
    check("tabs: what isn't a day, an event, a weekday, a mode or a number: nothing", w.last()["settings"]["shape"]["preview"] is None)
    w.tab_click("shape", key="day", value=0)
    for i in range(1, 6):
        w.tab_click("shape", key="day", value=i)
    check("tabs: the last study day stays (one at least)", any(w.last()["settings"]["shape"]["days"]), w.last()["settings"]["shape"]["days"])
    w.tab_click("shape_back")

    w.tab_click("meta", name="  Path Book,   the fast one ", line="Two a week")
    check("tabs: its name and one line saved (one request), the status says so",
          STORE.plans[pid]["name"] == "Path Book, the fast one" and STORE.plans[pid]["line"] == "Two a week"
          and w.last("status")["status"].startswith("Saved."), (STORE.plans[pid]["name"], w.last("status")))
    w.tab_click("meta", name="   ", line="x")
    check("tabs: no name: nothing saved", STORE.plans[pid]["name"] == "Path Book, the fast one")
    w.tab_click("deck_url", url=" https://example.org/deck ")
    check("tabs: where to get the deck: a change of the plan's", STORE.plans[pid]["doc"].get("deckUrl") == "https://example.org/deck")
    w.tab_click("every")
    check("tabs: Every week's Change…: its lines (a Qt dialog over the window), saved", _Lines.made and _Lines.made[-1][0] is w
          and _Lines.made[-1][3] is True and STORE.plans[pid]["doc"].get("every") == [{"k": "read", "t": "Chapter 3", "r": "024"}],
          STORE.plans[pid]["doc"].get("every"))
    check("tabs: and said in a line", w.last()["settings"]["every"] == "Read: Chapter 3, every Mon, Wed, Fri", w.last()["settings"]["every"])


def test_settings_sharing():
    pid, code = plan(units(), EVENTS)
    w = Face(client("sam"), select=pid, tab="settings")
    w.tab_click("copy_link")
    check("tabs: Copy link: its link, and the status says what it is", w.copied == f"https://duecrew.com/p/{code}"
          and "Copied: its link" in w.last("status")["status"], w.copied)
    w.tab_click("open_page")
    check("tabs: Open its page", w.ops.pages == [f"/p/{code}"], w.ops.pages)
    s = w.last()["settings"]
    check("tabs: my squads to offer it to, and who can follow", s["squads"] == [{"id": "sq1", "name": "Night owls"}]
          and s["audience"] == "code" and s["squad"] is None, s["squads"])
    w.tab_click("who", squad="sq1", audience="squad")
    check("tabs: only people in that squad: saved, said", STORE.plans[pid]["audience"] == "squad" and STORE.plans[pid]["squad"] == "sq1"
          and w.last("status")["status"] == "Only people in Night owls can follow it now.", w.last("status"))
    w.tab_click("who", squad="sq-not-mine", audience="squad")
    check("tabs: a squad that isn't mine: anyone with the code (none offered)", STORE.plans[pid]["audience"] == "code"
          and STORE.plans[pid]["squad"] is None, (STORE.plans[pid]["audience"], STORE.plans[pid]["squad"]))
    w.tab_click("listed", on=True)
    check("tabs: List it in the library", STORE.plans[pid].get("listed") == 1 and w.last("status")["status"] == "In the library.")
    w.tab_click("table")
    check("tabs: Copy as a table: a set a line, then the quizzes", w.copied.startswith("Day\tSet\tFinish by\tTested on\tCards\n")
          and f"{day(-7)}\tCell injury\t\tHeme quiz\t12" in w.copied and "(quiz or exam)" in w.copied, w.copied[:200])
    n = len(STORE.plans)
    w.tab_click("next_year")
    new = [p for p, x in STORE.plans.items() if x["owner"] == "sam" and x["name"].endswith("(next year)")]
    check("tabs: Copy it for next year: a copy, named for next year, the window on it", len(STORE.plans) == n + 1 and new
          and w.ops.reopened[-1] == new[-1], (len(STORE.plans), w.ops.reopened))
    w.tab_click("ai_app")
    check("tabs: Your AI app: its window over this one", _shown and _shown[-1] is w)
    w.tab_click("delete_plan")
    sh = w.last("sheet")
    check("tabs: Delete this plan… asks first, as danger", sh and sh["danger"] and sh["args"]["name"] == "delete_plan" and pid in STORE.plans, sh)
    w.sheet_yes(sh)
    check("tabs: its yes takes it down, the window on no plan", pid not in STORE.plans and w.ops.reopened[-1] is None, w.ops.reopened)


def test_posts_and_history():
    pid, code = plan(units(), EVENTS)
    client("maya").follow_plan(code)
    w = Face(client("sam"), select=pid, tab="settings")
    w.tab_click("posts")
    sh = w.last("sheet")
    check("tabs: Posts…: a sheet, nothing posted yet said, a box to post in", sh and sh["kind"] == "posts" and sh["rows"] == []
          and sh["words"].startswith("Nothing posted yet") and sh["fields"][0]["hint"] == "A line to the 1 following", sh)
    w.sheet_yes(sh, text="  Neoplasia moved:   the lecture did. ")
    sh = w.last("sheet")
    check("tabs: Post: one line to followers, the list read again with it", sh["rows"] and sh["rows"][0]["text"] == "Neoplasia moved: the lecture did."
          and sh["rows"][0]["who"] == "You" and sh["words"].startswith("Posted."), sh["rows"])
    w.sheet_yes(sh, text="   ")
    check("tabs: an empty post: nothing", len(w.last("sheet")["rows"]) == 1)
    w.tab_click("unpost", id=sh["rows"][0]["id"])
    check("tabs: Remove it: the post taken back", w.last("sheet")["rows"] == [], w.last("sheet")["rows"])
    w.tab_click("unpost", id=999)
    w.click("rename", uid="u3", name="Neoplasia II")
    w.click("send", why="Renamed")
    w.click("undo", what=["history"])
    sh = w.last("sheet")
    check("tabs: Undo › History: a sheet in the page, every save, the latest undoes", sh and sh["kind"] == "history" and sh["rows"]
          and sh["yes"] == "Undo the latest" and sh["args"]["name"] == "history_undo", sh)
    w.sheet_yes(sh)
    check("tabs: Undo the latest: the save taken back", next(u for u in STORE.plans[pid]["doc"]["units"] if u["id"] == "u3")["name"] == "Neoplasia",
          STORE.plans[pid]["doc"]["units"])
    pid2, _c = plan([], name="Brand new")
    w2 = Face(client("sam"), select=pid2, tab="settings")
    w2.click("undo", what=["history"])
    sh = w2.last("sheet")
    check("tabs: no saves yet: said, and no Undo", sh and sh["rows"] == [] and sh["yes"] is None and sh["words"].startswith("No saves yet"), sh)


def test_coauthors():
    pid, _code = plan(units(), EVENTS)
    w = Face(client("sam"), select=pid, tab="settings")
    w.tab_click("coauthor_ask")
    sh = w.last("sheet")
    check("tabs: Ask one of my crew…: my crew read, one to pick", sh and sh["kind"] == "pick" and {o["label"] for o in sh["options"]} == {"Kai", "Maya"}
          and sh["args"]["name"] == "coauthor_add", sh)
    maya = next(o["v"] for o in sh["options"] if o["label"] == "Maya")
    w.sheet_yes(dict(sh, args=dict(sh["args"], uid=maya)))
    s = w.last()["settings"]
    check("tabs: asked: invited, waiting for a yes, the status says so", [(c["name"], c["what"]) for c in s["coauthors"]] == [("Maya", "invited, waiting for a yes")]
          and s["coauthors"][0]["off"] == "Take back the invite" and not s["coauthors"][0]["hand"]
          and w.last("status")["status"].startswith("Asked Maya."), s["coauthors"])
    w.tab_click("coauthor_add", uid="dre")
    check("tabs: someone not offered in the pick: nothing", "dre" not in (STORE.plans[pid].get("invited") or {}))
    STORE.plans[pid]["invited"] = {}
    STORE.plans[pid]["editors"] = {"maya"}
    w.load()
    s = w.last()["settings"]
    check("tabs: a co-author who said yes can be handed it", s["coauthors"][0]["what"] == "co-author" and s["coauthors"][0]["hand"], s["coauthors"])
    w.tab_click("hand", uid="maya")
    s = w.last()["settings"]
    check("tabs: Hand it to them: offered, and Take the offer back", STORE.plans[pid].get("handover") == "maya"
          and s["coauthors"][0]["what"] == "offered the plan" and s["offered"], s)
    w.tab_click("unhand")
    check("tabs: Take the offer back", not STORE.plans[pid].get("handover") and w.last("status")["status"] == "Taken back.")
    w.tab_click("coauthor_off", uid="maya")
    check("tabs: Take them off", "maya" not in (STORE.plans[pid].get("editors") or ()) and w.last()["settings"]["coauthors"] == [],
          STORE.plans[pid].get("editors"))
    STORE.plans[pid]["editors"] = {"maya"}
    m = Face(client("maya"), select=pid, tab="settings")
    s = m.last()["settings"]
    check("tabs: a co-author's Settings: not the owner's (who can follow said, no library, no delete), Leave",
          s["role"] == "author" and not s["owner"] and s["ownerOnly"].startswith("Anyone with the code") and not s["library"]["shown"]
          and not s["delete"] and s["leave"] and not s["canAsk"], s)
    m.tab_click("who", squad=None, audience="code")
    m.tab_click("delete_plan", sure=True)
    m.tab_click("listed", on=True)
    check("tabs: the owner's clicks do nothing for a co-author", pid in STORE.plans and STORE.plans[pid].get("listed") != 1)
    m.tab_click("leave")
    sh = m.last("sheet")
    check("tabs: Leave asks first", sh and sh["args"]["name"] == "leave" and sh["args"]["sure"], sh)
    m.sheet_yes(sh)
    check("tabs: its yes: off the plan, the window on no plan", "maya" not in (STORE.plans[pid].get("editors") or ()) and m.ops.reopened == [None])


def test_changes_wait_with_followers():
    pid, code = plan(units(), EVENTS)
    client("maya").follow_plan(code)
    w = Face(client("sam"), select=pid, tab="settings")
    check("tabs: with someone following, the shape's button adds to the changes", w.last()["settings"]["shape"]["go"] == "Add to the changes")
    w.tab_click("shape", key="daily", value=25)
    w.tab_click("shape_save")
    v = w.last()
    check("tabs: and the change waits under the plan, not saved", w.draft and len(w.draft) == 1 and STORE.plans[pid]["doc"]["pace"]["daily"] == 40
          and v["settings"]["shape"]["daily"] == 25 and v["settings"]["shape"]["preview"] is None, STORE.plans[pid]["doc"]["pace"])
    # 3.9.6, after the last check: closing with a change waiting asks (web.py's closeEvent asks unsent_ask first)
    w.closed = False
    check("tabs: closing with a change waiting asks, and the close waits", w.unsent() == 1 and w.unsent_ask() is True)
    sh = w.last("sheet")
    check("tabs: its sheet: N not sent, who won't get it, Review and send or Close anyway",
          sh["title"] == "1 change not sent" and sh["words"].startswith("1 following it won't get it till you send.")
          and sh["yes"] == "Review and send" and sh["cmd"] == "review_send" and sh["no"] == "Close anyway"
          and sh["noCmd"] == "close" and sh["noArgs"] == {"sure": True}, sh)
    w.sheet_yes(sh)
    check("tabs: Review and send: the send sheet", (w.last("sheet") or {}).get("kind") == "send" and not w.closed, w.last("sheet"))
    w.click("close", sure=True)
    check("tabs: Close anyway: it closes, the change still waiting here", w.closed and len(w.draft) == 1
          and w.unsent_ask() is False, (w.closed, len(w.draft)))
    w2 = Face(client("sam"), select=pid, tab="settings")
    w2.closed = False
    w2.click("close")
    check("tabs: the window's own Close goes the same way (the frame's close asks; this one closes)", w2.closed)


# ---- Settings, a follower's ----

def test_settings_a_followers():
    us = units()
    us[2]["opens"] = (TODAY + datetime.timedelta(days=2)).isoformat()  # one ahead to skip, one skipped, whatever today is
    us[3]["opens"] = (TODAY + datetime.timedelta(days=9)).isoformat()
    pid, code = plan(us, EVENTS, owner="dre", name="MS2 Block 2")
    STORE.plans[pid]["listed"] = 1
    sam = client("sam")
    sam.follow_plan(code)
    ops = Ops(sam)
    ops.follow = {"id": pid, "name": "MS2 Block 2", "shift": 0, "skipped": ["u4"], "own": "", "early": 2, "paused": False}
    w = Face(sam, select=pid, tab="mine", ops=ops)
    s = w.last()["settings"]
    check("tabs: a follower's Settings: my follow, from the window's Mine tab", w.last()["tab"] == "settings" and s["role"] == "follower"
          and s["head"] == "Following MS2 Block 2" and s["later"] == "Some days later…" and s["held"] == "7 cards…"
          and s["squad"].startswith("Not in it") and s["reset"], s)
    check("tabs: Make my own copy for a plan in the library (the plan says so: clean_plan keeps `library`)",
          s["copy"] and w.plan.get("library") is True, (s.get("copy"), w.plan.get("library")))
    w.plan["library"] = True  # (what the server says a follower; the cleaned plan doesn't keep it yet)
    w.push()
    check("tabs: and shown when it says it's in the library", w.last()["settings"]["copy"])
    check("tabs: the lessons I skip, and the ones ahead to skip", [x["uid"] for x in s["skips"]] == ["u4"] and s["skips"][0]["label"].endswith("· Hemostasis")
          and [x["uid"] for x in s["ahead"]] == ["u3"], (s["skips"], s["ahead"]))
    check("tabs: Today's lesson hidden when this Anki hasn't the choice", s["lesson"] is None)
    check("tabs: Open early's days, its pick ticked", [x["n"] for x in s["early"] if x["on"]] == [2])
    w.tab_click("shift", later=False)
    check("tabs: As the plan when it is already: nothing", not ops.calls)
    loads = ops.loads
    w.tab_click("shift", later=True)
    check("tabs: Some days later…: plan_flow asks; my follow read again, the plan with it when my dates moved",
          ops.calls[-1] == ("set_shift", pid) and ops.loads == loads + 1 and w.last()["settings"]["later"] == "3 days later",
          (ops.calls, ops.loads, w.last()["settings"]["later"]))
    for name, args, want in (("skip", {"uid": "u3", "on": True}, ("set_skip", pid, "u3", True)),
                             ("skip", {"uid": "u4", "on": False}, ("set_skip", pid, "u4", False)),
                             ("own", {"own": "ready"}, ("set_own", pid, "ready")),
                             ("early", {"n": 3}, ("set_early", pid, 3)),
                             ("pause", {}, ("pause_until", pid)),
                             ("held", {}, ("show_held", pid)),
                             ("change_deck", {}, ("change_deck", pid)),
                             ("open_everything", {}, ("open_everything", pid)),
                             ("reset", {}, ("reset_days", pid)),
                             ("stop_following", {}, ("stop_following", pid))):
        n = len(ops.calls)
        w.tab_click(name, **args)
        check(f"tabs: {name} {args or ''}: plan_flow's own step", len(ops.calls) == n + 1 and ops.calls[-1] == want, ops.calls[n:])
    n = len(ops.calls)
    w.plan["library"] = False
    w.tab_click("copy_mine")
    w.plan["library"] = True
    w.tab_click("copy_mine")
    check("tabs: Make my own copy: only a plan in the library, and plan_flow makes it", ops.calls[n:] == [("copy_plan", pid)]
          and w.last("status")["status"] == "copied", ops.calls[n:])
    n = len(ops.calls)
    w.tab_click("skip", uid="nope", on=True)
    w.tab_click("own_next", on=True)
    w.tab_click("schedule")
    w.tab_click("early", n=4)
    w.tab_click("own", own="sometimes")
    check("tabs: a lesson not on the plan, the next-one rule at the plan's dates, no schedule, odd days, odd ways: nothing",
          len(ops.calls) == n, ops.calls[n:])
    ops.follow.update(own="ready", paused=True, sched={"days": [1] * 7})
    w.tab_click("own_next", on=True)
    w.tab_click("pause")
    w.tab_click("schedule")
    w.tab_click("early", n=1)
    check("tabs: at my own pace: the next-one rule; paused: Resume; a schedule: My schedule…; Open early: not at my own pace",
          ops.calls[n:] == [("set_own", pid, "next"), ("resume", pid), ("open_schedule", pid)], ops.calls[n:])
    ops.lesson = False
    w.load()  # (my follow is read once a change: a plan loaded again reads it)
    s = w.last()["settings"]
    check("tabs: Today's lesson when plan_flow has it: A, opens in my deck", s["lesson"] is False)
    w.tab_click("lesson_deck", on=True)
    check("tabs: B: also its own deck (plan_flow's set_lesson_deck)", ops.calls[-1] == ("set_lesson_deck", pid, True)
          and w.last()["settings"]["lesson"] is True, ops.calls[-1])
    for name in ("meta", "listed", "delete_plan", "posts", "coauthor_ask", "shape_save", "table", "next_year"):
        w.tab_click(name)
    check("tabs: an author's clicks do nothing for a follower", STORE.plans[pid]["name"] == "MS2 Block 2" and w.copied is None
          and not w.last("sheet"), w.last("sheet"))
    ops.follow = None
    w.load()
    check("tabs: not following it on this account any more: said", w.last()["settings"].get("gone"), w.last()["settings"])


def test_settings_an_author_who_follows_it():
    """3.9.6, after the last check: New plan's Start it follows my own plan,
    and Make it, start later doesn't. The author's Settings has my follow
    too: Start it here… (the Follow window on its code) till I follow it,
    then my follow's rows, each step plan_flow's as a follower's."""
    pid, code = plan(units(), EVENTS, owner="sam", name="Path Book, mine")
    sam = client("sam")
    ops = Ops(sam)
    w = Face(sam, select=pid, tab="settings", ops=ops)
    s = w.last()["settings"]
    check("tabs: an author not following it: Start it here…", s["role"] == "author" and s["mine"] == {"start": True, "pid": pid}, s.get("mine"))
    for name, args in (("shift", {"later": True}), ("pause", {}), ("stop_following", {}), ("lesson_deck", {"on": True}), ("team", {})):
        w.tab_click(name, **args)
    check("tabs: and my follow's steps do nothing till I follow it", not ops.calls, ops.calls)
    sam.session["_pid_started"] = pid
    w.tab_click("start_here")
    s = w.last()["settings"]
    check("tabs: Start it here…: the Follow window on its own code; then my follow's rows under the plan's",
          ops.calls == [("start_here", code)] and s["role"] == "author" and s["mine"]["role"] == "follower"
          and s["mine"]["head"] == "Your follow" and s["mine"]["deckName"] == "Big Step 1" and s["mine"]["team"] == "Join its squad",
          (ops.calls, s.get("mine")))
    w.tab_click("start_here")
    check("tabs: Start it here… once it's followed: nothing", ops.calls == [("start_here", code)], ops.calls)
    for name, args, want in (("shift", {"later": True}, ("set_shift", pid)),
                             ("skip", {"uid": "u3", "on": True}, ("set_skip", pid, "u3", True)),
                             ("own", {"own": "ready"}, ("set_own", pid, "ready")),
                             ("pause", {}, ("pause_until", pid)),
                             ("stop_following", {}, ("stop_following", pid))):
        n = len(ops.calls)
        w.tab_click(name, **args)
        check(f"tabs: an author's own follow, {name}: plan_flow's step", ops.calls[n:n + 1] == [want], ops.calls[n:])
    ops.lesson = False
    w.load()
    w.tab_click("lesson_deck", on=True)
    check("tabs: an author's own follow, Today's set: plan_flow's set_lesson_deck", ops.calls[-1] == ("set_lesson_deck", pid, True), ops.calls[-1])
    n = len(ops.calls)
    w.tab_click("team")
    sh = w.last("sheet")
    check("tabs: Join its squad asks in the window first, saying what it shares", sh and sh["title"] == "Join this plan's squad?"
          and sh["words"] == WT.TEAM_SAYS and len(ops.calls) == n, sh)
    w.sheet_yes(sh)
    check("tabs: and its yes is team_flow's join", ops.calls[n:] == [("team_join", pid)], ops.calls[n:])
    ops.follow["paused"] = True
    w.load()
    check("tabs: paused, said on its head", w.last()["settings"]["mine"]["head"] == "Your follow, paused")


def test_team_says_is_team_flows():
    src = open(os.path.join(REPO, "due_crew", "team_flow.py")).read()
    got = re.search(r"JOIN_SAYS = \(((?:\s*\"[^\"]*\")+)\)", src)
    words = "".join(re.findall(r'"([^"]*)"', got.group(1))) if got else ""
    check("tabs: Join its squad's words are team_flow.JOIN_SAYS word for word", words == WT.TEAM_SAYS, words)


def test_flow_ops_reach_plan_flow_by_name():
    """flow.Ops' Today's lesson: plan_flow's when it has it, else None (the row hidden), never a crash."""
    src = open(os.path.join(REPO, "due_crew", "planner", "flow.py")).read()
    body = src[src.index("    def lesson_deck_on"):src.index("    def copy_plan")]
    check("tabs: flow.Ops reaches lesson_deck_on and set_lesson_deck through getattr on plan_flow",
          'getattr(plan_flow, "lesson_deck_on", None)' in body and 'getattr(plan_flow, "set_lesson_deck", None)' in body
          and "return None" in body, body[:300])


# ---- the page ----

NODE = r"""
const fs = require("fs"), vm = require("vm");
const [planPath, tabsPath, statesPath] = process.argv.slice(2);
const src = fs.readFileSync(planPath, "utf8") + "\n" + fs.readFileSync(tabsPath, "utf8");
const states = JSON.parse(fs.readFileSync(statesPath, "utf8"));
function El(tag) { this.tagName = String(tag).toUpperCase(); this.children = []; this.parent = null; this.attrs = {};
  this.style = {}; this.className = ""; this._t = ""; this.ls = {}; this.value = ""; var self = this;
  this.classList = { add: function (c) { self.className += " " + c; }, remove: function () {}, toggle: function () {} }; }
Object.defineProperty(El.prototype, "textContent", { get: function () { return this._t + this.children.map(function (c) { return c.textContent || ""; }).join(""); },
  set: function (v) { this._t = String(v); this.children.forEach(function (c) { c.parent = null; }); this.children = []; } });
Object.defineProperty(El.prototype, "childNodes", { get: function () { return this.children; } });
El.prototype.appendChild = function (c) { if (c.parent) { c.remove(); } c.parent = this; this.children.push(c); return c; };
El.prototype.remove = function () { if (this.parent) { var i = this.parent.children.indexOf(this); if (i >= 0) { this.parent.children.splice(i, 1); } this.parent = null; } };
El.prototype.setAttribute = function (k, v) { this.attrs[k] = v; if (k === "disabled") { this.disabled = true; } if (k === "checked") { this.checked = true; } };
El.prototype.getAttribute = function (k) { return k in this.attrs ? this.attrs[k] : null; };
El.prototype.addEventListener = function (t, f) { (this.ls[t] = this.ls[t] || []).push(f); };
El.prototype.querySelector = function () { return null; };
El.prototype.querySelectorAll = function () { return []; };
El.prototype.getBoundingClientRect = function () { return { left: 0, top: 0, right: 10, bottom: 10, width: 10, height: 10 }; };
["focus", "blur", "select", "scrollIntoView", "setSelectionRange"].forEach(function (k) { El.prototype[k] = function () {}; });
function Text(t) { this.textContent = String(t); this.parent = null; }
Text.prototype.remove = El.prototype.remove;
function walk(el, fn) { fn(el); (el.children || []).forEach(function (c) { if (c instanceof El) { walk(c, fn); } }); }
function ev(el) { return { target: el, stopPropagation: function () {}, preventDefault: function () {}, key: "Enter" }; }
function fire(el, t) { (el.ls[t] || []).forEach(function (f) { f.call(el, ev(el)); }); }
function act(el) {
  if (el.tagName === "SELECT") { var o = el.children.filter(function (c) { return c.tagName === "OPTION"; }); el.value = o.length ? o[o.length - 1].attrs.value : ""; fire(el, "change"); return; }
  if (el.tagName === "INPUT") {
    var ty = el.attrs.type || "text";
    el.value = ty === "date" ? "2031-01-06" : ty === "number" ? "30" : "Typed here"; el.checked = !el.checked;
    fire(el, "input"); fire(el, "change"); fire(el, "keydown"); return;
  }
  fire(el, "click");
}
function setup(sent) {
  var root = new El("div");
  var ctx = { console: console, setTimeout: function (f) { try { f(); } catch (e) { /* a focus */ } }, clearTimeout: function () {}, JSON: JSON,
    document: { createElement: function (t) { return new El(t); }, createTextNode: function (t) { return new Text(t); },
      addEventListener: function () {}, getElementById: function () { return root; }, activeElement: null }, root: root };
  ctx.window = ctx; ctx.innerWidth = 1240; ctx.innerHeight = 820;
  ctx.pycmd = function (m) { sent.push(m); };
  vm.createContext(ctx);
  vm.runInContext(src, ctx);
  return ctx;
}
var out = {};
Object.keys(states).forEach(function (key) {
  var st = states[key], sent = [], errors = [], ctx = setup(sent);
  function draw() { ctx.dcPlan.show(st.view); if (st.sheet) { ctx.dcPlan.sheet(st.sheet); } }
  function controls() { var xs = []; walk(ctx.root, function (el) { if (el !== ctx.root && (el.ls.click || el.ls.change)) { xs.push(el); } }); return xs; }
  function menus() { return ctx.root.children.filter(function (c) { return / menu/.test(" " + c.className); }); }
  function items(m) { return m.children.filter(function (c) { return c.ls && c.ls.click; }); }
  try { ctx.dcPlan.start(st.view, true); if (st.sheet) { ctx.dcPlan.sheet(st.sheet); } } catch (e) { errors.push("draw: " + e.stack); }
  var text = ctx.root.textContent, n = controls().length;
  for (var i = 0; i < n; i++) {
    try {
      draw();
      var el = controls()[i];
      if (!el || el.disabled) { continue; }
      act(el);
      var opened = menus();
      if (opened.length) {
        var top = items(opened[0]);
        top.forEach(function (mi, j) {
          draw(); act(controls()[i]);
          var again = items(menus()[0])[j];
          if (!again) { return; }
          act(again);
          var subs = menus().slice(1);
          if (subs.length) { items(subs[0]).forEach(function (s) { act(s); }); }
        });
      }
    } catch (e) { errors.push("control " + i + ": " + e.stack); }
  }
  out[key] = { sent: sent, text: text, errors: errors, controls: n };
});
process.stdout.write(JSON.stringify(out));
"""


def _page_states():
    """Each view and sheet the tabs draw, from the window itself."""
    pid, code = plan(units(), EVENTS, name="Page, the author's")
    STORE.plans[pid]["editors"] = {"maya"}
    STORE.plans[pid]["invited"] = {"kai": 1}
    client("dre").follow_plan(code)
    a = Face(client("sam"), select=pid, tab="insights")
    states = {"author-insights": {"view": a.view()}}
    a.click("tab", tab="settings")
    a.tab_click("shape", key="start", value=day(0))
    states["author-settings"] = {"view": a.view()}
    a.tab_click("shape_back")
    PR.post(client("sam"), pid, "A line to them")
    a.tab_click("posts")
    states["posts"] = {"view": a.view(), "sheet": a.last("sheet")}
    a.click("rename", uid="u3", name="Neoplasia II")
    a.click("send", why="Renamed it")
    a.click("undo", what=["history"])
    states["history"] = {"view": a.view(), "sheet": a.last("sheet")}
    STORE.plans[pid]["invited"] = {}
    a.load()
    a.tab_click("coauthor_ask")
    states["pick"] = {"view": a.view(), "sheet": a.last("sheet")}
    m = Face(client("maya"), select=pid, tab="settings")
    states["coauthor-settings"] = {"view": m.view()}
    mine = Ops(client("sam"))
    mine.follow = {"id": pid, "name": "Page, the author's", "shift": 0, "skipped": [], "own": "", "early": 0, "paused": False}
    mine.lesson = False
    states["author-follows-settings"] = {"view": Face(client("sam"), select=pid, tab="settings", ops=mine).view()}
    us = units()
    us[2]["opens"] = (TODAY + datetime.timedelta(days=2)).isoformat()
    us[3]["opens"] = (TODAY + datetime.timedelta(days=9)).isoformat()
    fpid, fcode = plan(us, EVENTS, owner="dre", name="Page, a follower's")
    STORE.plans[fpid]["listed"] = 1
    sam = client("sam")
    sam.follow_plan(fcode)
    ops = Ops(sam)
    ops.follow = {"id": fpid, "name": "Page, a follower's", "shift": 2, "skipped": ["u4"], "own": "", "early": 0,
                  "paused": False, "sched": {"x": 1}}
    ops.lesson = True
    f = Face(sam, select=fpid, tab="insights", ops=ops)
    f.plan["library"] = True
    states["follower-insights"] = {"view": f.view()}
    f.click("tab", tab="settings")
    states["follower-settings"] = {"view": f.view()}
    ops.follow["own"] = "ready"  # at my own pace: the next-one rule, and Open early off
    f.load()
    states["follower-settings-ready"] = {"view": f.view()}
    return states, {"author": (pid, lambda: Face(client("sam"), select=pid, tab="settings")),
                    "follower": (fpid, lambda: Face(sam, select=fpid, tab="settings", ops=ops))}


def test_the_page_draws_and_every_click_has_its_handler():
    js = open(os.path.join(PAGE, "tabs.js")).read()
    css = open(os.path.join(PAGE, "tabs.css")).read()
    check("tabs: tabs.js sets names as text: no innerHTML", "innerHTML" not in js and "innerHTML" not in css)
    node = subprocess.run(["node", "--check", os.path.join(PAGE, "tabs.js")], capture_output=True, text=True)
    check("tabs: tabs.js parses", node.returncode == 0, node.stderr)
    named = set(re.findall(r'run\(\w+(?:\.\w+)?, "([a-z_]+)"', js)) | set(re.findall(r'item\("([a-z_]+)"', js))
    py = open(os.path.join(REPO, "due_crew", "planner", "webtabs.py")).read()
    named |= set(re.findall(r'_on\("([a-z_]+)"', py)) | set(re.findall(r'_ask\(w, "([a-z_]+)"', py)) | {"history"}
    missing = sorted(n for n in named if not callable(getattr(WT, "c_" + n, None)))
    check("tabs: every tabcmd the page or a sheet names has its c_ handler", named and not missing, missing)
    html = page_html({"head": {"plans": []}}, colors({}))
    check("tabs: the window's page inlines tabs.js and tabs.css", "P.tabs.insights = function" in html and ".dcp .tsec" in html)

    states, faces = _page_states()
    with tempfile.TemporaryDirectory() as tmp:
        sp, script = os.path.join(tmp, "states.json"), os.path.join(tmp, "draw.js")
        with open(sp, "w") as f:
            json.dump(states, f)
        with open(script, "w") as f:
            f.write(NODE)
        got = subprocess.run(["node", script, os.path.join(PAGE, "plan.js"), os.path.join(PAGE, "tabs.js"), sp],
                             capture_output=True, text=True, timeout=120)
    try:
        out = json.loads(got.stdout)
    except ValueError:
        check("tabs: the page ran in node", False, got.stderr[-2000:])
        return
    for key, o in out.items():
        check(f"tabs: page {key}: drawn and every control fired without an error ({o['controls']} controls)",
              not o["errors"] and o["controls"] > 0, o["errors"][:2])
    words = {
        "author-insights": ["Workload", "How much of the deck", "What's in it", "Quizzes and exams", "Its biggest sets", "Heme quiz"],
        "author-settings": ["The plan", "Sharing", "Your follow", "You don't follow it yet.", "Start it here…", "This computer",
                            "This plan", "Saving moves", "Put it back", "Copy link", "Posts…",
                            "Ask one of my crew…", "List it in the library", "Copy it for next year", "Delete this plan…", "Maya"],
        "author-follows-settings": ["Sharing", "Your follow", "My dates", "Today's set", "In Big Step 1", "Its own deck",
                                    "Join its squad", "Stop following…", "This plan", "Delete this plan…"],
        "coauthor-settings": ["Leave this plan", "Its owner sets that."],
        "posts": ["Posts to the 1 following", "A line to them", "Remove it"],
        "history": ["Undo the latest"],
        "pick": ["Ask a co-author", "Maya"],
        "follower-insights": ["You've seen", "To go"],
        "follower-settings": ["My dates", "2 days later", "Skip a set", "When I'm ready", "Today's set", "In Big Step 1",
                              "Its own deck", "Join its squad", "7 cards…", "Stop following…", "Make my own copy"],
    }
    for key, want in words.items():
        text = out.get(key, {}).get("text", "")
        gone = [x for x in want if x not in text]
        check(f"tabs: page {key} says what it should", not gone, gone)
    check("tabs: the coauthor's page has no owner's controls", "Delete this plan…" not in out["coauthor-settings"]["text"]
          and "Offer it to one of my squads" not in out["coauthor-settings"]["text"])

    sent = {}
    for key, o in out.items():
        for m in o["sent"]:
            data = json.loads(m[len("dcplan:"):])
            sent.setdefault(key, []).append(data)
    names = {d["a"].get("name") for ms in sent.values() for d in ms if d["c"] == "tabcmd"}
    expect = {"map_by", "go", "meta", "shape", "shape_back", "shape_save", "every", "copy_link", "open_page", "deck_url", "who",
              "posts", "post", "unpost", "history_undo", "coauthor_ask", "coauthor_add", "hand", "coauthor_off", "leave", "listed",
              "next_year", "table", "delete_plan", "ai_app", "shift", "skip", "own", "own_next", "early", "pause", "held",
              "change_deck", "open_everything", "schedule", "reset", "stop_following", "copy_mine", "lesson_deck"}
    check("tabs: the page sends every one of the tabs' clicks", expect <= names, sorted(expect - names))
    unknown = sorted({n for n in names if not callable(getattr(WT, "c_" + str(n), None))}
                     | {d["c"] for ms in sent.values() for d in ms if d["c"] != "tabcmd" and not hasattr(WebFace, "c_" + d["c"])})
    check("tabs: every message the page sent has its handler", not unknown, unknown)
    _printed.clear()
    for key, ms in sent.items():
        role = "follower" if key.startswith("follower") else "author"
        for d in ms:
            if d["c"] not in ("tabcmd", "tab", "pick", "undo"):
                continue
            w = faces[role][1]()
            w._on_cmd("dcplan:" + json.dumps(d))
    check("tabs: each message the page sent, sent back through the window: no handler took the wrong arguments", not _printed, len(_printed))


def main():
    for n in [n for n in list(globals()) if n.startswith("test_")]:
        globals()[n]()
    bad = [c for c in CHECKS if not c[1]]
    print(f"\n{len(CHECKS) - len(bad)}/{len(CHECKS)} checks passed")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
