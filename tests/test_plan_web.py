"""The HTML plan window (due_crew/planner/web.py; its face webface.py, its
view webmodel.py, its page page/plan.*), against a fake collection and the
fake Worker (tests/fakes.py): every click sent as the page sends it
("dcplan:" + JSON), what the window draws, and what it saves. Standard
library only; tools/plan_preview.py renders the same face for the eye.

Run: python3 tests/test_plan_web.py
"""

import datetime
import json
import os
import re
import sqlite3
import subprocess
import sys

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
from due_crew.planner import remote as PR           # noqa: E402
from due_crew.planner import webmodel as WM         # noqa: E402
from due_crew.planner.draft import Draft            # noqa: E402
from due_crew.planner.webface import WebFace        # noqa: E402
from due_crew.planner.webpage import colors, page_html  # noqa: E402

CHECKS = []
DEAD_SHEETS = []  # sheets drawn with a yes and no cmd: pressed, they'd send nothing
DEAD_CLICKS = []  # anything a view or a sheet draws to be clicked whose cmd has no handler, or a menu item with nothing to do
TODAY = datetime.date.today()
MON = TODAY - datetime.timedelta(days=TODAY.weekday())
R = "#Big_Step_1::#Path_Book"


def check(name, cond, detail=""):
    CHECKS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond or detail == "" else f"\n     {detail}"))


def day(n):
    return (MON + datetime.timedelta(days=n)).isoformat()


def rel(n):
    """A day n days from today (day(n) is from this week's Monday)."""
    return (TODAY + datetime.timedelta(days=n)).isoformat()


for uid, name in (("sam", "Sammy"), ("dre", "Dre"), ("maya", "Maya")):
    STORE.add_user(uid, name, code=uid.upper()[:3] + "123")


def client(uid):
    c = api.ApiClient(os.path.join(os.environ.get("TMPDIR", "/tmp"), f"dc-test-plan-web-{uid}.json"))
    c.session = {"user_id": uid, "token": STORE.session_for(uid), "display_name": uid.title(),
                 "last_ok": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    return c


def collection():
    conn = sqlite3.connect(":memory:")
    fakes.make_collection(conn)
    cid = 0
    for ch, parts in (("01_Cell_injury", ["Adaptations", "Injury"]), ("02_Inflammation", ["Acute", "Chronic"]),
                      ("03_Neoplasia", ["Nomenclature", "Progression"])):
        for part in parts:
            for i in range(6):
                cid += 1
                fakes.add_card(conn, cid, 1, queue=-1, tags=f"{R}::{ch}::{part}" + (" #Big_Step_1::^High_Yield" if i % 2 else ""))
    col = fakes.FakeCol(conn, fakes.day_cutoff_for(TODAY))
    col.decks = fakes.FakeDecks({1: "Big Step 1"})
    return col


COL = collection()


class Ops:
    def __init__(self, cl):
        self.cl, self.drafts, self.browsed, self.opened, self.studied = cl, {}, [], [], []
        self.started, self.followed, self.pages = [], [], []
        self.follow = False
        self.gave = 0

    def gave_day(self):
        self.gave += 1  # 3.9.6: Give everyone a day saved, for Pip's Kite

    def today(self):
        return TODAY.isoformat()

    def context(self, plan, doc):
        return P.DeckIndex(COL, 1), None, "named"

    def my_doc(self, plan):
        return plan["doc"]

    def followed_here(self, pid, version=None):
        return self.follow

    def load(self, owner, pid, done):
        done(PR.load(self.cl, pid))

    def save(self, owner, pid, version, doc, summary, done):
        done(PR.save(self.cl, pid, version, doc, summary))

    def send(self, owner, pid, version, doc, summary, post, done):
        done(PR.save(self.cl, pid, version, doc, summary, post, waits=True))  # flow.send's: its changes wait if it's refused

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

    def browse(self, cids):
        self.browsed.append(set(cids))

    def open_cards(self, cids, name):
        self.opened.append((set(cids), name))
        return True

    def study_cards(self, idx, cids, name):
        self.studied.append((set(cids), name))
        return True

    def top_decks(self):
        return [(1, "Big Step 1", 36)]

    def index(self, did):
        return P.DeckIndex(COL, did)

    def make(self, owner, name, doc, done, pid=None):
        if pid is None:
            outcome, raw = PR.create(self.cl, name, doc.get("deck") or "")
            if outcome != "saved":
                done((outcome, raw))
                return
            pid, version = raw["id"], raw.get("version") or 1
        else:
            have = PR.load(self.cl, pid)[0]
            version = have.get("version") or 1
            if name and str(have.get("name") or "") != name:  # flow.StartOps.make's: its name fixed since
                outcome, raw = PR.save_meta(self.cl, pid, version, {"name": name}, f"named {name}"[:120])
                if outcome == "saved":
                    version = raw.get("version") or version
        if self.fail_save:
            self.fail_save = False
            done(("made", pid, "Check your connection."))
            return
        outcome, raw = PR.save(self.cl, pid, version, doc, f"made in Anki: {name}")
        done(("saved", dict(raw, id=raw.get("id") or pid)) if outcome == "saved" else ("made", pid, "It changed since."))

    fail_save = False

    def start_own(self, owner, raw, did, own, lesson_deck, done):
        got, _status = self.cl.follow_plan(raw["code"], False, own=own)
        self.started.append((raw["id"], did, own, lesson_deck, got is not None))
        done(got is not None)

    def follow_code(self, code):
        self.followed.append(code)

    def open_page(self, path):
        self.pages.append(path)

    def __getattr__(self, name):
        return lambda *a, **k: None


def dead_clicks(x, where):
    """What a view or a sheet draws to be clicked that would reach nothing: a
    cmd (or a sheet's noCmd) with no c_ handler, a tabcmd with no webtabs one,
    and a menu item (a set's More, a source's menu and their subs: plan.js
    menu()) with no cmd, no sub and not off, which closes and sends nothing."""
    from due_crew.planner import webtabs as WT
    out = []

    def handled(cmd, args):
        if cmd == "tabcmd":
            return callable(getattr(WT, "c_" + str((args or {}).get("name")), None))
        return hasattr(WebFace, "c_" + str(cmd))

    def walk(v, at):
        if isinstance(v, list):
            for i, y in enumerate(v):
                walk(y, f"{at}[{i}]")
        elif isinstance(v, dict):
            for k in ("cmd", "noCmd"):
                if isinstance(v.get(k), str) and not handled(v[k], v.get("args" if k == "cmd" else "noArgs")):
                    out.append((where, at, v[k]))
            for k, y in v.items():
                walk(y, f"{at}.{k}")

    def items(menu, at):
        for i, it in enumerate(menu or []):
            if isinstance(it, dict) and not it.get("sep") and not it.get("off"):
                if it.get("sub"):
                    items(it["sub"], f"{at}[{i}].sub")
                elif not it.get("cmd"):
                    out.append((where, f"{at}[{i}]", it.get("label")))
    walk(x, "")
    pn = x.get("panel") if isinstance(x, dict) else None
    if isinstance(pn, dict):
        items(pn.get("more"), "panel.more")
        for i, s in enumerate(pn.get("sources") or []):
            items((s or {}).get("menu"), f"panel.sources[{i}].menu")
    return out


class Face(WebFace):
    def __init__(self, cl, select=None, tab=None):
        self.js, self.copied = [], None
        self.web_init(COL, PR.my_plans(cl), Ops(cl), select, tab, {})
        self._ready = True
        if self.pid:
            self.load(self.pid)

    def eval_js(self, js):
        self.js.append(js)
        if js.startswith("dcPlan.sheet("):
            sh = json.loads(js[len("dcPlan.sheet("):-1])
            if sh.get("yes") is not None and not sh.get("cmd"):
                DEAD_SHEETS.append(sh.get("title"))  # its yes would close it and send nothing (page/plan.js submit)
            DEAD_CLICKS.extend(dead_clicks(sh, "sheet " + str(sh.get("title"))))
        elif js.startswith("dcPlan.show("):
            DEAD_CLICKS.extend(dead_clicks(json.loads(js[len("dcPlan.show("):-1]), "view"))

    def copy(self, text):
        self.copied = text

    def click(self, c, **a):
        self._on_cmd("dcplan:" + json.dumps({"c": c, "a": a}))

    def press(self, sheet, **fields):
        """A sheet's yes, as the page sends it (page/plan.js submit): its cmd with its args and the
        fields filled in; a send sheet's, its line to followers alone; no cmd, nothing."""
        args = dict(sheet.get("args") or {}, **fields)
        if sheet.get("kind") == "send":
            args = {"why": fields.get("why", sheet.get("why") or "")}
        if sheet.get("cmd"):
            self.click(sheet["cmd"], **args)

    def last(self, what="show"):
        for js in reversed(self.js):
            if js.startswith(f"dcPlan.{what}("):
                return json.loads(js[len(f"dcPlan.{what}("):-1])
        return None


def plan(units, events=(), owner="sam", name="Path Book, high yield"):
    pid, code = STORE.add_plan(owner, name, "Big Step 1", units)
    STORE.plans[pid]["doc"]["events"] = list(events)
    STORE.plans[pid]["doc"]["pace"] = {"mode": "daily", "days": [1, 1, 1, 1, 1, 0, 0], "daily": 20}
    return pid, code


def test_an_authors_window():
    pid, _code = plan([{"id": "u1", "name": "Cell injury", "opens": day(0), "tags": [f"{R}::01_Cell_injury"]},
                       {"id": "u2", "name": "Inflammation", "opens": day(1), "tags": [f"{R}::02_Inflammation"]}],
                      [{"id": "e1", "day": day(4), "name": "Heme quiz"}])
    w = Face(client("sam"), select=pid)
    v = w.last()
    check("web: an author's plan loads, its head says whose and that nobody follows",
          v and v["head"]["author"] and any(p["id"] == pid and "nobody following yet" in p["label"] for p in v["head"]["plans"]), v and v["head"])
    items = [it for wk in v["plan"]["weeks"] for it in wk["items"]]
    check("web: the lessons and the quiz by week, each with its cards here", [it["name"] for it in items if it["kind"] == "date"] ==
          ["Cell injury", "Inflammation"] and any(it["kind"] == "event" and it["name"] == "Heme quiz" for it in items)
          and next(it for it in items if it["name"] == "Cell injury")["right"] == "12", items)
    check("web: the shape on one line, and the cover's bar", v["plan"]["shape"] and v["plan"]["cover"]["cards"] == 24, v["plan"].get("cover"))
    w.click("pick", key=["date", "u2"])
    v = w.last()
    check("web: a lesson picked: its panel, its sources a line each with a menu", v["picked"] == ["date", "u2"]
          and v["panel"]["kind"] == "date" and v["panel"]["sources"] and v["panel"]["sources"][0]["menu"], v["panel"])
    w.click("rename", uid="u2", name="  Inflammation   and repair ")
    check("web: a rename saves at once with nobody following", next(u for u in STORE.plans[pid]["doc"]["units"] if u["id"] == "u2")["name"]
          == "Inflammation and repair", STORE.plans[pid]["doc"]["units"])
    w.click("move", uid="u2", to=day(0))
    sh = w.last("sheet")
    check("web: a move onto a taken day asks first (a sheet), and nothing moves yet",
          sh and "already" in sh["title"] and sh["cmd"] == "move" and sh["args"]["sure"] is True
          and next(u for u in STORE.plans[pid]["doc"]["units"] if u["id"] == "u2")["opens"] == day(1), sh)
    w.click("move", **sh["args"])
    check("web: and the sheet's yes moves it", next(u for u in STORE.plans[pid]["doc"]["units"] if u["id"] == "u2")["opens"] == day(0))
    v = w.last()
    check("web: Undo has the save of this window's", any(u["what"] == ["undo"] for u in v["head"]["undo"]), v["head"]["undo"])
    w.click("undo", what=["undo"])
    check("web: Undo takes it back", next(u for u in STORE.plans[pid]["doc"]["units"] if u["id"] == "u2")["opens"] == day(1))
    w.click("new_date_form")
    sh = w.last("sheet")
    check("web: Add › A lesson is a form in the page: a name and its day", sh and [f["name"] for f in sh["fields"]] == ["name", "day"], sh)
    w.click("new_date", name="Neoplasia", day=day(2))
    v = w.last()
    new = [u for u in STORE.plans[pid]["doc"]["units"] if u["name"] == "Neoplasia"]
    check("web: a new lesson goes on, and is the one picked", new and v["picked"] == ["date", new[0]["id"]], v["picked"])
    w.click("browse", key=["date", "u1"])
    check("web: Show in Browse sends the lesson's cards", w.ops.browsed and len(w.ops.browsed[-1]) == 12, w.ops.browsed)
    w.click("pick", key=["date", "u1"])
    w.click("copy_source", i=0)
    check("web: a source's own search, copied", "tag:" in str(w.copied) and "01\\_Cell\\_injury" in str(w.copied), w.copied)
    w.click("delete")
    sh = w.last("sheet")
    check("web: Delete asks first, in the page, as danger", sh and sh["danger"] and sh["cmd"] == "delete", sh)
    w.click("delete", sure=True)
    check("web: and its yes takes the lesson off", not any(u["id"] == "u1" for u in STORE.plans[pid]["doc"]["units"]))
    w.click("nope_not_a_command")
    w._on_cmd("duecrew:something")
    w._on_cmd("dcplan:{not json")
    check("web: what isn't a command of the window's does nothing", True)



def test_after_the_last_check_v396():
    """3.9.6, after the last check: a quiz's panel picks its sets (a tick each,
    one click for the ones since the last quiz); the week a set runs in today
    stays open; a follower's week says the plan's pace; a quiz added after
    every set ends a plan with no end; New plan's preview numbers a set once."""
    us = [{"id": "u1", "name": "Cell injury", "opens": day(-9), "tags": [f"{R}::01_Cell_injury"]},
          {"id": "u2", "name": "Inflammation", "opens": day(-8), "tags": [f"{R}::02_Inflammation"], "for": "e1"},
          # running today whatever day of the week the suite runs on (it said so only on a Monday or a Tuesday)
          {"id": "u3", "name": "Neoplasia", "opens": rel(-1), "due": rel(1), "tags": [f"{R}::03_Neoplasia"]},
          {"id": "u4", "name": "Hemostasis", "opens": rel(2), "tags": [f"{R}::04_Hemostasis::Platelets"]}]
    pid, _code = plan(us, [{"id": "e0", "day": day(-7), "name": "Cell quiz"}, {"id": "e1", "day": rel(4), "name": "Heme quiz"}])
    next(u for u in STORE.plans[pid]["doc"]["units"] if u["id"] == "u2")["for"] = "e1"  # (plan() keeps no `for`)
    w = Face(client("sam"), select=pid)
    w.click("pick", key=["event", "e1"])
    pn = w.last()["panel"]
    check("web: a quiz's panel, an author's: every set by its day, ticked when it leads up to it",
          [(x["uid"], x["on"]) for x in pn["picks"]] == [("u1", False), ("u2", True), ("u3", False), ("u4", False)], pn.get("picks"))
    check("web: …and one click for the ones since the quiz before it, not ticked yet", pn["since"] == ["u3", "u4"]
          and pn["sinceWords"] == "Tick the 2 since Cell quiz", (pn.get("since"), pn.get("sinceWords")))
    w.click("event_sets", eid="e1", uids=["u1"], on=True)
    doc = STORE.plans[pid]["doc"]
    check("web: a tick: that set leads up to it (set_for), saved at once with nobody following",
          next(u for u in doc["units"] if u["id"] == "u1").get("for") == "e1")
    w.click("event_sets", eid="e1", uids=["u2"], on=False)
    check("web: untick: it leads up to nothing", "for" not in next(u for u in STORE.plans[pid]["doc"]["units"] if u["id"] == "u2"))
    w.click("event_sets", eid="e1", uids=w.last()["panel"]["since"], on=True)
    doc = STORE.plans[pid]["doc"]
    check("web: the ones since: all of them, one save", all(next(u for u in doc["units"] if u["id"] == x).get("for") == "e1" for x in ("u3", "u4")))
    w.click("event_sets", eid="nope", uids=["u1"], on=False)
    w.click("event_sets", eid="e1", uids="u1", on=False)
    check("web: a quiz that isn't one, or uids that aren't a list: nothing", next(u for u in STORE.plans[pid]["doc"]["units"] if u["id"] == "u1").get("for") == "e1")
    weeks = w.last()["plan"]["weeks"]
    held = [wk for wk in weeks if any(it.get("key") == ["date", "u3"] for it in wk["items"])]
    check("web: the week a set opened in that still runs today says so (it stays open)", held and held[0]["running"]
          and not any(wk["running"] for wk in weeks if wk is not held[0]), [(wk["label"], wk["running"]) for wk in weeks])
    check("web: a week's name is its Monday to Sunday", all(" · " in wk["label"] and "–" in wk["label"] for wk in weeks), [wk["label"] for wk in weeks])
    v = __import__("due_crew.planner.view", fromlist=["x"])
    ask = {"over": True, "top": 70, "cap": 40, "new": 50, "reviews": 30}
    check("web: a week over the pace: the author's 'your 40', a follower's 'the plan's 40'",
          v.week_words(ask)[0].startswith("70 new a day (over your 40)") and v.week_words(ask, mine=False)[0].startswith("70 new a day (over the plan's 40)"))
    STORE.plans[pid]["doc"].pop("end", None)
    w.load()
    w.click("new_event", name="Path exam", day=day(9))
    check("web: a quiz or exam after every set ends a plan that has no end", STORE.plans[pid]["doc"].get("end") == day(9), STORE.plans[pid]["doc"].get("end"))
    w.click("new_event", name="Later still", day=day(12))
    check("web: …once: with an end, another after it changes nothing of the end", STORE.plans[pid]["doc"].get("end") == day(9))
    w.click("new_event", name="Midterm", day=day(0))
    check("web: and one before the last set never does", STORE.plans[pid]["doc"].get("end") == day(9))
    # 3.9.9 (Sam's pick B): This is the exam, on the event's panel; a follower's board asks once
    eid = next(e["id"] for e in STORE.plans[pid]["doc"]["events"] if e["name"] == "Path exam")
    w.click("pick", key=["event", eid])
    check("web: an event's panel says whether it's the exam (not yet)", w.last()["panel"]["exam"] is False, w.last()["panel"].get("exam"))
    w.click("event_kind", eid=eid, exam=True)
    ev = next(e for e in STORE.plans[pid]["doc"]["events"] if e["id"] == eid)
    check("web: This is the exam marks it on the plan; the panel says so", ev.get("kind") == "exam" and w.last()["panel"]["exam"] is True, ev)
    other = next(e for e in STORE.plans[pid]["doc"]["events"] if e["name"] == "Midterm")
    check("web: …and only that one", "kind" not in other, other)
    w.click("event_kind", eid=eid, exam=False)
    check("web: unticked, a named day again", "kind" not in next(e for e in STORE.plans[pid]["doc"]["events"] if e["id"] == eid))
    w.click("event_kind", eid="nope", exam=True)
    check("web: an event that isn't one: nothing", not any(e.get("kind") for e in STORE.plans[pid]["doc"]["events"]))
    from due_crew.planner import edits as E, text as T
    doc = {"deck": "d", "units": [], "events": [{"id": "x1", "day": day(5), "name": "Block exam", "kind": "exam"},
                                                {"id": "q1", "day": day(2), "name": "Quiz"}]}
    txt = T.to_text(doc)
    back = T.from_text(doc, None, txt, whole=True)
    check("web: the text says exam on an exam's line and event on a plain one, and reads it back so (builder.js's twin)",
          f"{day(5)} | exam | Block exam" in txt and f"{day(2)} | event | Quiz" in txt
          and [(e["name"], e.get("kind")) for e in back["events"]] == [("Quiz", None), ("Block exam", "exam")]
          or [(e["name"], e.get("kind")) for e in sorted(back["events"], key=lambda e: e["day"])] == [("Quiz", None), ("Block exam", "exam")],
          (txt, back["events"]))
    made, _u = E.new_plan_doc("d", [{"date": day(3), "kind": "quiz", "title": "Quiz 1"}, {"date": day(4), "kind": "exam", "title": "Midterm"}],
                              "Block exam", day(20))
    kinds = {e["name"]: e.get("kind") for e in made["events"]}
    check("web: New plan: the exam it ends with is the exam, and so is a calendar's exam; a quiz stays a quiz",
          kinds == {"Quiz 1": None, "Midterm": "exam", "Block exam": "exam"}, kinds)

def test_the_deck_beside_the_plan():
    pid, _code = plan([{"id": "u1", "name": "Cell injury", "opens": day(0), "tags": []}])
    w = Face(client("sam"), select=pid)
    w.click("deck", uid="u1")
    v = w.last()
    dk = v["deck"]
    check("web: Add from the deck: the deck in the lesson's place, saying which lesson ticks add to",
          v["side"] == "deck" and dk["target"] == "u1" and "Cell injury" in dk["targetLabel"] and dk["nodes"], dk.get("targetLabel"))

    def find(nodes, name):
        for n in nodes:
            if n["name"] == name or n["name"].endswith(" · " + name):
                return n
            got = find(n["children"], name)
            if got:
                return got
        return None
    pb = find(dk["nodes"], "Path Book")
    check("web: the tree opened one way down to its first choice", pb is not None, [n["name"] for n in dk["nodes"]])
    check("web: an open row shows its chapters, numbered", pb["open"] and [c["name"] for c in pb["children"]][:2] ==
          ["1 · Cell injury", "2 · Inflammation"], [c["name"] for c in pb["children"]])
    ch = find(pb["children"], "Inflammation")
    w.click("deck_open", key=ch["key"], on=True)
    check("web: a row opened shows its parts", [c["name"] for c in find(w.last()["deck"]["nodes"], "Inflammation")["children"]]
          == ["Acute", "Chronic"], find(w.last()["deck"]["nodes"], "Inflammation"))
    w.click("deck_open", key=ch["key"], on=False)
    w.click("deck_tick", key=ch["key"], on=True)
    u = next(u for u in STORE.plans[pid]["doc"]["units"] if u["id"] == "u1")
    check("web: a tick puts the tag on the lesson", f"{R}::02_Inflammation" in (u.get("tags") or []), u)
    ch = find(w.last()["deck"]["nodes"], "Inflammation")
    check("web: and the row says it's on this set", ch["check"] == 1 and ch["where"] == "on this set", ch)
    w.click("deck_find", text="neopl")
    v = w.last()
    check("web: Find keeps the deck's structure: the find under the tags above it", find(v["deck"]["nodes"], "Neoplasia") is not None
          or any("Neoplasia" in n["name"] for n in v["deck"]["nodes"]), [n["name"] for n in v["deck"]["nodes"]])
    w.click("deck_done")
    check("web: Done: the lesson again", w.last()["side"] == "panel" and w.last()["picked"] == ["date", "u1"])


def test_changes_wait_when_someone_follows():
    pid, code = plan([{"id": "u1", "name": "Cell injury", "opens": day(3), "tags": [f"{R}::01_Cell_injury"]}])
    client("maya").follow_plan(code)
    w = Face(client("sam"), select=pid)
    w.click("rename", uid="u1", name="Cell injury and death")
    v = w.last()
    check("web: with someone following, a change waits under the plan, not saved",
          v["plan"]["sending"] and v["plan"]["sending"]["n"] == 1
          and next(u for u in STORE.plans[pid]["doc"]["units"] if u["id"] == "u1")["name"] == "Cell injury", v["plan"]["sending"])
    w.click("review_send")
    sh = w.last("sheet")
    check("web: Review and send: each change in words, a line for followers filled in", sh and sh["kind"] == "send" and sh["rows"]
          and sh["why"] and sh["yes"] == "Send to 1", sh)
    w.press(sh, why="Renamed it")  # the sheet's own Send, as the page sends it (Sam, 7 Nov: it sent nothing)
    check("web: Send saves it, with the line as a post", next(u for u in STORE.plans[pid]["doc"]["units"] if u["id"] == "u1")["name"]
          == "Cell injury and death" and not w.draft, STORE.plans[pid]["doc"]["units"])
    w.click("rename", uid="u1", name="Cells")
    w.click("discard")
    sh = w.last("sheet")
    check("web: Discard asks first", sh and sh["cmd"] == "discard" and sh["danger"], sh)
    w.click("discard", sure=True)
    check("web: and its yes takes every waiting change back", not w.draft and not w.last()["plan"]["sending"])


def test_a_followers_window():
    pid, code = plan([{"id": "c1", "name": "Anemias", "opens": day(-7), "tags": [f"{R}::03_Neoplasia"]},
                      {"id": "c2", "name": "Hemolysis", "opens": TODAY.isoformat(), "tags": [f"{R}::01_Cell_injury"]}],
                     owner="dre", name="MS2 Block 2")
    sam = client("sam")
    sam.follow_plan(code)
    w = Face(sam, select=pid)
    v = w.last()
    check("web: a follower's window: not an author, no shape, today and behind on top",
          not v["head"]["author"] and "shape" not in v["plan"] and v["plan"]["now"] and v["plan"]["behind"], v["plan"].get("behind"))
    w.click("rename", uid="c1", name="Mine now")
    check("web: a follower's click on an author's change does nothing", next(u for u in STORE.plans[pid]["doc"]["units"]
                                                                             if u["id"] == "c1")["name"] == "Anemias")
    w.notes, w.notes_of = [{"id": "n1", "day": TODAY.isoformat(), "text": "Bring the smear atlas", "name": "Dre"}], pid
    w.plan = dict(w.plan, doc=dict(w.plan["doc"]))
    w.doc = P.my_doc(w.plan["doc"], shift=2)
    w.click("pick", key=["date", "c2"])
    nv = w.last()["panel"]["notes"]
    check("web: a follower whose days run later sees a set's notes on the plan's day for it (where everyone posts them)",
          [r["text"] for r in nv["rows"]] == ["Bring the smear atlas"] and nv["day"] == TODAY.isoformat()
          and nv["dayw"] == P.fmt_day((TODAY + datetime.timedelta(days=2)).isoformat()), nv)
    w.click("study", kind="behind", key=v["plan"]["behind"]["uids"])
    check("web: Study the N: what's behind, studied", w.ops.studied and w.ops.studied[-1][1] == "what's behind", w.ops.studied)


def test_new_plan():
    STORE.add_user("nia", "Nia", code="NIA123")
    w = Face(client("nia"))
    v = w.last() or w.view()
    v = w.view()
    check("web: with no plans, the window opens on New plan's first screen", v["new"] and v["new"]["step"] == "pick"
          and not v.get("welcome"), v.get("new"))
    w.click("new_step", step="nope")
    check("web: a step that isn't one does nothing", w.view()["new"]["step"] == "pick")
    w.click("new_step", step="someone")
    w.click("new_follow", code="  ABC  123 ")
    check("web: Someone's plan: Follow… with its code (the Follow window's)", w.ops.followed == ["ABC 123"], w.ops.followed)
    w.click("new_library")
    check("web: and the library, on duecrew.com", w.ops.pages == ["/library"])
    w.click("new_step", step="empty")
    w.click("new_set", key="end_day", value="1999-01-01")
    check("web: a day already gone isn't taken", w.view()["new"]["endDay"] > TODAY.isoformat())
    w.click("new_set", key="name", value="  Heme   block ")
    w.click("new_set", key="end_name", value="Heme exam")
    w.click("new_set", key="end_day", value=day(20))
    w.click("new_set", key="lesson", value="sideways")
    nv = w.view()["new"]
    check("web: Start empty: a name, the deck, the exam it ends with; today's lesson in the deck by default",
          nv["name"] == "Heme block" and nv["endName"] == "Heme exam" and nv["endDay"] == day(20) and nv["lesson"] == "deck"
          and nv["canMake"] and nv["deckName"] == "Big Step 1", nv)
    w.click("new_make", start=False)
    sh = w.last("sheet")
    check("web: Make asks first, saying what it makes", sh and sh["title"] == "Make Heme block?" and "Heme exam" in sh["words"]
          and sh["yes"] == "Make it" and sh["args"] == {"start": False, "sure": True}, sh)
    before = len(STORE.plans)
    w.ops.fail_save = True
    w.click("new_make", **sh["args"])
    nv = w.view()["new"]
    check("web: made but its lessons not saved: it says so, and Make tries them again on the same plan",
          nv and "didn't save" in nv["said"] and len(STORE.plans) == before + 1, nv and nv["said"])
    w.click("new_make", start=False)
    v = w.view()
    pid = w.pid
    check("web: then it's made once, mine, and open in the window on the deck, to lay it out",
          len(STORE.plans) == before + 1 and v.get("new") is None and STORE.plans[pid]["owner"] == "nia"
          and STORE.plans[pid]["doc"].get("end") == day(20) and v["side"] == "deck" and v["head"]["author"]
          and any(p["id"] == pid for p in v["head"]["plans"]), (v.get("side"), STORE.plans.get(pid, {}).get("doc")))
    check("web: nobody started it here (Make it, start later)", w.ops.started == [])
    w.click("new_plan")
    w.click("new_step", step="empty")
    w.click("new_set", key="name", value="Mine to study")
    w.click("new_set", key="lesson", value="own")
    w.click("new_make", start=True, sure=True)
    started = w.ops.started[-1] if w.ops.started else None
    check("web: Start it follows my own plan here, today's lesson as its own deck as asked",
          started and started[1] == 1 and started[3] is True and started[4], w.ops.started)
    v = w.view()
    check("web: and my own follow isn't someone my changes wait for", w.plan and w.plan.get("following")
          and w.followers() == 0 and not w.waiting() and "nobody following yet" in next(p["label"] for p in v["head"]["plans"]
                                                                                    if p["id"] == w.pid), w.plan and w.plan.get("followers"))
    w.click("new_plan")
    check("web: New plan… from a plan: the new screen in the tabs' place", w.view()["new"]["step"] == "pick")
    w.click("new_cancel")
    check("web: Cancel: back to the plan", w.view().get("new") is None and w.view()["plan"] is not None)
    w.click("new_plan", finish_by=day(30), exam="Block exam")
    nv = w.view()["new"]
    check("web: from the board's exam line, New plan knows the exam: Finish by its day", nv["endDay"] == day(30)
          and nv["endName"] == "Block exam" and w.new["pace"] == "by" and w.new["by"] == day(30), (nv, w.new["pace"]))
    w.click("pick_plan", pid=w.pid)
    check("web: picking a plan leaves New plan", w.view().get("new") is None)


def test_the_builders_tools_in_the_window():
    pid, _code = plan([{"id": "u1", "name": "Cell injury", "opens": day(7), "tags": [f"{R}::01_Cell_injury"]},
                       {"id": "u2", "name": "Inflammation", "opens": day(8), "tags": [f"{R}::02_Inflammation"]}],
                      [{"id": "e1", "day": day(12), "name": "Heme quiz"}])
    w = Face(client("sam"), select=pid)
    w.click("pick", key=["date", "u1"])
    src = w.last()["panel"]["sources"][0]
    menu = {m.get("label"): m for m in src["menu"]}
    leave = menu.get("Leave out cards also tagged")
    hy = next((x for x in (leave or {}).get("sub") or [] if x["label"].startswith("High Yield")), None)
    check("web: a source's menu: Leave out cards also tagged, the tags some of its cards carry, with how many",
          hy and hy["label"] == "High Yield (6)", leave and [x["label"] for x in leave["sub"]])
    w.click("op", **hy["args"])
    u1 = next(u for u in STORE.plans[pid]["doc"]["units"] if u["id"] == "u1")
    check("web: and its click puts the builder's \"but not\" search in the tag's place",
          not u1.get("tags") and any("-" in q and "High\\_Yield" in q for q in u1.get("search") or []), u1)
    w.click("undo", what=["undo"])
    moves = {m["label"].split(" · ")[0]: m for m in menu["Move to"]["sub"] if m.get("label")}
    check("web: Move to: the nearest lessons, and another day", "Inflammation" in moves and "Another day…" in moves, list(moves))
    w.click("op", **moves["Inflammation"]["args"])
    doc = STORE.plans[pid]["doc"]
    check("web: a source moved to another lesson; the lesson it left, empty, goes", [u["id"] for u in doc["units"]] == ["u2"]
          and f"{R}::01_Cell_injury" in doc["units"][0]["tags"], doc["units"])
    w.click("undo", what=["undo"])
    w.click("pick", key=["date", "u1"])
    w.click("move_source_form", i=0)
    sh = w.last("sheet")
    check("web: Move to › Another day… asks for the day in the page", sh and sh["cmd"] == "move_source_form"
          and sh["fields"][0]["type"] == "date", sh)
    w.click("move_source_form", i=0, day=day(10))
    doc = STORE.plans[pid]["doc"]
    check("web: and the day gets it, a lesson of its own there", any(u["opens"] == day(10) and f"{R}::01_Cell_injury" in (u.get("tags") or [])
                                                                  for u in doc["units"]), doc["units"])
    w.click("undo", what=["undo"])
    w.click("deck")
    w.click("deck_tick", key=f"tag:{R}::03_Neoplasia", on=True)
    f = w.last()["deck"]["fill"]
    check("web: the deck's lay out: before any quiz or exam", f and [x["eid"] for x in f.get("upto") or []] == ["e1"], f)
    w.click("deck_lay", how=["end", False, None], upto="e1")
    doc = STORE.plans[pid]["doc"]
    neo = [u for u in doc["units"] if any(t.startswith(f"{R}::03_Neoplasia") for t in u.get("tags") or [])]
    check("web: …laid out before it, for it", neo and all(u["opens"] < day(12) and u.get("for") == "e1" for u in neo), neo)
    w.click("undo", what=["undo"])
    w.click("deck_done")
    w.click("lesson_from", key=f"tag:{R}::03_Neoplasia", day="next")
    doc = STORE.plans[pid]["doc"]
    new = [u for u in doc["units"] if f"{R}::03_Neoplasia" in (u.get("tags") or [])]
    check("web: a deck row's A lesson of its own: on the next free study day, after the plan's last",
          new and new[0]["opens"] > day(8), doc["units"])
    w.click("lesson_from", key=f"tag:{R}::03_Neoplasia", day=None)
    check("web: …or on a day asked for", (w.last("sheet") or {}).get("cmd") == "lesson_from")
    w.click("breather")
    sh = w.last("sheet")
    check("web: Give everyone a day asks first, saying how many move", sh and sh["cmd"] == "breather" and "3 sets" in sh["words"], sh)
    before = {u["id"]: u["opens"] for u in STORE.plans[pid]["doc"]["units"]}
    w.click("breather", sure=True)
    after = {u["id"]: u["opens"] for u in STORE.plans[pid]["doc"]["units"]}
    check("web: and its yes moves each a study day later; the quiz stays", all(after[k] > before[k] for k in before)
          and STORE.plans[pid]["doc"]["events"][0]["day"] == day(12), (before, after))
    check("3.9.6: Give everyone a day, saved (nobody follows: at once), counts once for Pip's Kite", w.ops.gave == 1, w.ops.gave)
    w.click("undo", what=["undo"])
    check("3.9.6: …and Undo doesn't count it again", w.ops.gave == 1, w.ops.gave)


def test_give_everyone_a_day_with_followers_v396():
    """3.9.6, the Kite: with someone following, Give everyone a day waits
    under the plan like any change; it counts when it's sent, not before,
    and a send without it doesn't."""
    pid, code = plan([{"id": "u1", "name": "Cell injury", "opens": day(7), "tags": [f"{R}::01_Cell_injury"]},
                      {"id": "u2", "name": "Inflammation", "opens": day(8), "tags": [f"{R}::02_Inflammation"]}])
    client("maya").follow_plan(code)
    w = Face(client("sam"), select=pid)
    w.click("rename", uid="u1", name="Cells")
    w.click("send", why="Renamed it")
    check("kite: a send without it doesn't count", w.ops.gave == 0, w.ops.gave)
    w.click("breather", sure=True)
    check("kite: waiting under the plan, not yet", w.ops.gave == 0 and w.draft and len(w.draft) == 1, w.ops.gave)
    w.click("send", why="A day for everyone")
    check("kite: sent to the one following, it counts once", w.ops.gave == 1 and not w.draft, w.ops.gave)


def test_new_plan_fills_in_what_it_knows():
    STORE.add_user("lee", "Lee", code="LEE123")
    cl = client("lee")
    face = Face.__new__(Face)
    face.js, face.copied = [], None
    ops = Ops(cl)
    ops.top_decks = lambda: [(1, "Big Step 1", 36), (2, "Spanish", 900)]
    ops.new_defaults = lambda: {"deck": 1, "days": [1, 1, 0, 1, 1, 1, 0], "exam": day(40)}
    face.web_init(COL, PR.my_plans(cl), ops, None, None, {})
    face._ready = True
    nv = face.view()["new"]
    check("web: New plan fills in the deck I study most, the days I study and my exam (Settings) as Finish by",
          nv["deck"] == 1 and face.new["days"] == [1, 1, 0, 1, 1, 1, 0] and face.new["pace"] == "by" and face.new["by"] == day(40)
          and nv["endDay"] == day(40) and nv["endName"] == "Exam", (nv, face.new["days"], face.new["pace"]))
    ops.new_defaults = lambda: {"deck": 99, "days": [0] * 7, "exam": "1999-01-01"}
    face.new_open()
    check("web: …and with nothing to go on, the plain ones (the biggest deck, weekdays, 20 a day)",
          face.new["deck"] == 1 and face.new["days"] == [1, 1, 1, 1, 1, 0, 0] and face.new["pace"] == "daily", face.new)
    ops.new_defaults = lambda: {"deck": 2, "days": None, "exam": day(40)}
    face.new_open(finish_by=day(40))
    check("web: from the board's Plan the way there, my exam keeps its name", face.new["end_name"] == "Exam" and face.new["deck"] == 2)


def test_a_resource_at_my_pace():
    STORE.add_user("rae", "Rae", code="RAE123")
    w = Face(client("rae"))
    w.click("new_step", step="resource")
    r = w.view()["new"]["resource"]
    pb = next((p for p in r["parts"] if p["name"].endswith("Path Book")), None)
    check("web: A resource: the deck's resources, each with its chapters and cards", pb and pb["on"] and pb["sub"] == "3 chapters"
          and pb["cards"] == 36, r["parts"])
    check("web: its sets a chapter each, on my days from tomorrow, at about 20 new a day", r["ok"] and r["dates"][0]["name"].endswith("Cell injury")
          and r["summary"].startswith("3 sets, 36 new") and w.view()["new"]["name"] == "Path Book", (r.get("summary"), r.get("dates")))
    check("web: the preview numbers a set once (its name says 1 · Cell injury already)",
          all(x["n"] == "" for x in r["dates"] if x["name"].startswith(f"{r['dates'].index(x) + 1} · ")) and r["dates"][0]["name"].startswith("1 · "),
          r.get("dates"))
    hy = next((o for o in r["only"] if o["label"] == "High Yield"), None)
    check("web: Only: the tags some of it carries", hy and hy["n"] == 18, r["only"])
    w.click("new_set", key="only", value=hy["path"])
    r = w.view()["new"]["resource"]
    check("web: with Only, its count and its name", r["onlyCount"] == "18 of 36" and r["name"] == "Path Book, high yield", r)
    check("3.9.6, day one: the preview lays the path out set by set, from the first set's day to its end",
          r["path"] and r["path"]["n"] == len(r["dates"]) + r["more"] and r["path"]["first"] == r["dates"][0]["when"].split(" – ")[0]
          and r["path"]["end"].startswith("Ends ") and r["path"]["event"] is False, r.get("path"))
    w.click("new_set", key="pace", value="by")
    w.click("new_set", key="by", value=day(30))
    w.click("new_set", key="end_name", value="Block exam")
    r = w.view()["new"]["resource"]
    check("3.9.6, day one: finishing by an exam, the path ends with it", r["path"]["event"] is True
          and r["path"]["end"] == f"Block exam · {P.fmt_day(day(30))}", r.get("path"))
    w.click("new_set", key="day", value=5)
    w.click("new_set", key="pace", value="ready")
    w.click("new_set", key="daily", value="5")
    r = w.view()["new"]["resource"]
    check("web: When I'm ready lays it out at the pace given, Saturdays in", r["pace"] == "ready" and r["daily"] == 5 and r["days"][5] == 1, r)
    w.click("new_make", start=True, sure=True)
    started = w.ops.started[-1] if w.ops.started else None
    doc = STORE.plans[w.pid]["doc"] if w.pid in STORE.plans else {}
    check("web: Start it: the plan made with a lesson a chapter, and followed here at my own pace",
          started and started[2] == "ready" and len(doc.get("units") or []) >= 3 and w.view().get("new") is None
          and w.view()["side"] == "panel", (started, len(doc.get("units") or [])))


def test_add_to_my_calendar():
    from due_crew.planner import ics
    pid, code = plan([{"id": "u1", "name": "Cell injury, part 1", "opens": day(7), "due": day(9), "even": True,
                       "tags": [f"{R}::01_Cell_injury"]},
                      {"id": "u2", "name": "Inflammation", "opens": day(10), "tags": [f"{R}::02_Inflammation"]}],
                     [{"id": "e1", "day": day(12), "name": "Heme quiz"}], name="Path Book; high yield")
    w = Face(client("sam"), select=pid)
    w.click("calendar")
    name, text = w._saved_file
    ymd = lambda n: day(n).replace("-", "")  # noqa: E731
    check("web: Add to my calendar: an .ics file named for the plan, straight to the calendar app (Sam's pick, no save window)",
          name == "Path Book high yield.ics"
          and text.startswith("BEGIN:VCALENDAR\r\nVERSION:2.0\r\n") and text.endswith("END:VCALENDAR\r\n")
          and "Opened in your calendar app" in w._status, (name, w._status))
    web = open(os.path.join(REPO, "due_crew", "planner", "web.py"), encoding="utf-8").read()
    check("web: the shell writes it to Downloads and opens it with the calendar app; no save dialog",
          "QDesktopServices.openUrl(QUrl.fromLocalFile(path))" in web and "QFileDialog" not in web)
    check("web: each set an all-day event over its days (a spread one to its finish-by day), each quiz too",
          text.count("BEGIN:VEVENT") == 3 and f"DTSTART;VALUE=DATE:{ymd(7)}\r\nDTEND;VALUE=DATE:{ymd(10)}" in text
          and f"DTSTART;VALUE=DATE:{ymd(12)}\r\nDTEND;VALUE=DATE:{ymd(13)}" in text, text)
    check("web: its words escaped as the format asks, with each set's cards here",
          "SUMMARY:Cell injury\\, part 1 · Path Book\\; high yield" in text and "12 cards" in text, text[:600])
    check("web: long lines folded under 76 octets", all(len(x.encode()) <= 75 for x in text.split("\r\n")))
    sam = client("maya")
    sam.follow_plan(code)
    STORE.follows[(pid, "maya")]["skipped"] = ["u2"]
    f = Face(sam, select=pid)
    f.plan["skipped"] = ["u2"]
    f.click("calendar")
    _n, text = f._saved_file
    check("web: a follower's file: my days, without the sets I skip", text.count("BEGIN:VEVENT") == 2 and "Inflammation" not in text)
    check("ics: a name with nothing safe in it", ics.file_name("///") == "Plan.ics")


def test_the_page():
    pid, _code = plan([{"id": "u1", "name": "<b>Bold</b> & co", "opens": day(0), "tags": [f"{R}::01_Cell_injury"]}])
    w = Face(client("sam"), select=pid)
    html = page_html(w.view(), colors({}))
    check("web: a name reaches the page as data, never as markup", "<b>Bold" not in html and "\\u003cb>Bold" in html)
    import glob
    js = "\n".join(open(f).read() for f in sorted(glob.glob(os.path.join(REPO, "due_crew", "planner", "page", "*.js"))))
    check("web: the page sets names as text: no innerHTML anywhere in its scripts", "innerHTML" not in js and "insertAdjacentHTML" not in js)
    cmds = set(re.findall(r'send\("([a-z_]+)"', js)) | set(re.findall(r'cmd: "([a-z_]+)"', js))
    cmds |= {c for m in re.findall(r'"cmd": "([a-z_]+)"', open(os.path.join(REPO, "due_crew", "planner", "webmodel.py")).read() +
                                    open(os.path.join(REPO, "due_crew", "planner", "webface.py")).read()) for c in [m]}
    missing = sorted(c for c in cmds if not hasattr(WebFace, "c_" + c))
    check("web: every command the page or the view sends has its handler", not missing, missing)
    bad = []
    for f in sorted(glob.glob(os.path.join(REPO, "due_crew", "planner", "page", "*.js"))):
        node = subprocess.run(["node", "--check", f], capture_output=True, text=True)
        if node.returncode:
            bad.append(node.stderr)
    check("web: the page's scripts parse", not bad, bad)
    css = open(os.path.join(REPO, "due_crew", "planner", "page", "plan.css")).read()
    check("web: every control is ours on macOS too: appearance none, outranking Anki's button rules, a focus ring outline:none can't take",
          "body .dcp button, body .dcp select, body .dcp input, body .dcp textarea {\n  appearance: none; -webkit-appearance: none;" in css
          and "box-shadow: 0 0 0 2px var(--dc-bg), 0 0 0 4px var(--dc-accent) !important" in css and "body .dcp .b:disabled:hover" in css)
    check("web: each part of the page is in it", all(f"dcPlan.{x}" in html for x in ("newPlan",)), "")
    check("web: the deck panel's views are the Qt panel's", [k for k, _ in WM.VIEWS] == ["resource", "system", "other", "deck", "plan"])


class AsyncOps(Ops):
    """Ops whose requests wait till run() (the real ones answer later)."""
    def __init__(self, cl):
        super().__init__(cl)
        self.queue = []

    def load(self, owner, pid, done):
        self.queue.append(("load", lambda: done(PR.load(self.cl, pid))))

    def save(self, owner, pid, version, doc, summary, done):
        self.queue.append(("save", lambda: done(PR.save(self.cl, pid, version, doc, summary))))

    def send(self, owner, pid, version, doc, summary, post, done):
        self.queue.append(("send", lambda: done(PR.save(self.cl, pid, version, doc, summary, post, waits=True))))

    def make(self, owner, name, doc, done, pid=None):
        self.queue.append(("make", lambda: Ops.make(self, owner, name, doc, done, pid)))

    def run(self, kind=None):
        while self.queue:
            i = next((j for j, q in enumerate(self.queue) if kind is None or q[0] == kind), None)
            if i is None:
                return
            fn = self.queue.pop(i)[1]
            fn()
            if kind is not None:
                return


class AFace(Face):
    def __init__(self, cl, select=None, ops=None):
        self.js, self.copied = [], None
        self.web_init(COL, PR.my_plans(cl), ops or AsyncOps(cl), select, None, {})
        self._ready = True
        if self.pid:
            self.load(self.pid)


KEYS_JS = r"""
const fs = require("fs"), vm = require("vm");
const [PAGE, VIEW] = process.argv.slice(1);
const src = ["plan.js", "tabs.js", "new.js"].map((f) => fs.readFileSync(PAGE + "/" + f, "utf8")).join("\n");
function El(tag) { this.tagName = String(tag).toUpperCase(); this.children = []; this.attrs = {}; this.style = {}; this.className = ""; this._t = "";
  this.ls = {}; this.value = ""; this.classList = { add() {}, remove() {}, toggle() {} }; }
Object.defineProperty(El.prototype, "textContent", { get() { return this._t + this.children.map((c) => c.textContent || "").join(""); },
  set(v) { this._t = String(v); this.children = []; } });
Object.defineProperty(El.prototype, "childNodes", { get() { return this.children; } });
El.prototype.appendChild = function (c) { this.children.push(c); return c; };
El.prototype.remove = function () {};
El.prototype.setAttribute = function (k, v) { this.attrs[k] = v; };
El.prototype.getAttribute = function (k) { return k in this.attrs ? this.attrs[k] : null; };
El.prototype.addEventListener = function (t, f) { (this.ls[t] = this.ls[t] || []).push(f); };
El.prototype.querySelector = function () { return null; };
El.prototype.querySelectorAll = function () { return []; };
El.prototype.getBoundingClientRect = function () { return { left: 0, top: 0, right: 10, bottom: 10, width: 10, height: 10 }; };
["focus", "blur", "select", "scrollIntoView", "setSelectionRange"].forEach((k) => { El.prototype[k] = function () {}; });
function Text(t) { this.textContent = String(t); }
const root = new El("div"), docLs = {}, sent = [];
const ctx = { console, setTimeout: (f) => { try { f(); } catch (e) {} }, clearTimeout() {}, JSON,
  document: { createElement: (t) => new El(t), createTextNode: (t) => new Text(t), getElementById: () => root, activeElement: new El("div"),
    addEventListener: (t, f) => { (docLs[t] = docLs[t] || []).push(f); } } };
ctx.window = ctx; ctx.innerWidth = 1240; ctx.innerHeight = 820; ctx.pycmd = (m) => sent.push(m);
vm.createContext(ctx); vm.runInContext(src, ctx);
ctx.dcPlan.start(JSON.parse(fs.readFileSync(VIEW, "utf8")), true);
const key = (k, mods) => (docLs.keydown || []).forEach((f) => f(Object.assign({ key: k, ctrlKey: false, metaKey: false, altKey: false, preventDefault() {} }, mods || {})));
key("ArrowLeft", { altKey: true }); key("z", { ctrlKey: true }); key("Backspace"); key("n", { ctrlKey: true }); key("e", { ctrlKey: true }); key("Enter");
console.log(JSON.stringify({ sent, text: root.textContent }));
"""


def test_the_review_round_v396():
    """3.9.6's review of the window, each finding as it was found:
    keys and clicks under New plan reach the plan behind it no more; an
    edit made while a save is out saves after it; a failed load says so
    with Try again; take back and Discard wait while changes send; an AI
    app's changes made during a send stay waiting; Make again renames the
    half-made plan, and New plan doesn't start over under a Make; the board
    opening the picked plan takes New plan away; a library plan's follower
    gets no note box."""
    import shutil
    import tempfile
    from due_crew.planner import webface as WF

    # 1: under New plan, the plan behind it takes nothing
    pid, _c = plan([{"id": "u1", "name": "Cell injury", "opens": day(7), "tags": [f"{R}::01_Cell_injury"]},
                    {"id": "u2", "name": "Inflammation", "opens": day(8), "tags": [f"{R}::02_Inflammation"]}])
    w = Face(client("sam"), select=pid)
    w.click("pick", key=["date", "u1"])
    w.click("new_plan")
    before = json.dumps(STORE.plans[pid]["doc"], sort_keys=True)
    n_js = len(w.js)
    for c, a in (("nudge", {"k": -1}), ("undo_key", {}), ("delete", {}), ("new_date_form", {}), ("deck", {"uid": "u1"})):
        w.click(c, **a)
    check("review: under New plan, the keys' and clicks' commands reach nothing behind it (the plan as it was, no sheet)",
          json.dumps(STORE.plans[pid]["doc"], sort_keys=True) == before and not any(j.startswith("dcPlan.sheet(") for j in w.js[n_js:])
          and w.new is not None and "new_make" in WF.NEW_CMDS and "new_date_form" not in WF.NEW_CMDS)
    v = w.view()
    if shutil.which("node"):
        f = os.path.join(tempfile.mkdtemp(), "view.json")
        with open(f, "w", encoding="utf-8") as fh:
            json.dump(v, fh)
        r = subprocess.run(["node", "-e", KEYS_JS, os.path.join(REPO, "due_crew", "planner", "page"), f], capture_output=True, text=True, timeout=60)
        got = json.loads(r.stdout or "{}")
        check("review: the page sends no key's command while New plan is up", r.returncode == 0 and got.get("sent") == [], (got.get("sent"), r.stderr[-300:]))
    # 7: the board opening the plan already picked: New plan goes
    check("review: the board opening the picked plan takes New plan away", w.go_to_plan(pid, "settings") and w.new is None and w.view()["tab"] == "settings")

    # 2: an edit made while a save is out saves after it
    pid, _c = plan([{"id": "u1", "name": "Cell injury", "opens": day(7), "tags": [f"{R}::01_Cell_injury"]}])
    w = AFace(client("sam"), select=pid)
    w.ops.run()
    w.click("pick", key=["date", "u1"])
    w.click("rename", uid="u1", name="Cell injury and death")
    w.click("set_due", uid="u1", due=day(9))
    queued = [k for k, _f in w.ops.queue]
    w.ops.run()
    u = next(x for x in STORE.plans[pid]["doc"]["units"] if x["id"] == "u1")
    check("review: an edit made while a save is out saves after it, never dropped",
          queued == ["save"] and u["name"] == "Cell injury and death" and u.get("due") == day(9) and w._status == "Saved."
          and w.last()["panel"]["due"] == day(9), (queued, u, w._status))

    # 3: a load that failed says so, and the page can try again
    pid, _c = plan([{"id": "u1", "name": "Cell injury", "opens": day(3), "tags": [f"{R}::01_Cell_injury"]}], owner="dre", name="Only plan")
    cl = client("dre")
    w = AFace(cl, select=pid)
    w.ops.queue.pop(0)
    w._loaded(pid, None)
    w.click("pick_plan", pid=pid)
    check("review: a failed load, then Try again (the same plan picked again) loads it", [k for k, _f in w.ops.queue] == ["load"])
    w.ops.run()
    js = open(os.path.join(REPO, "due_crew", "planner", "page", "plan.js"), encoding="utf-8").read()
    check("review: ...and once it loads, the plan's there; the page's empty state has Try again", w.plan is not None
          and 'btn("Try again", function () { send("pick_plan", { pid: S.head.pid }); }' in js and "The plan didn't load." in js)

    # 4: take back and Discard wait while the changes send
    pid, code = plan([{"id": "u1", "name": "Cell injury", "opens": day(3), "tags": [f"{R}::01_Cell_injury"]},
                      {"id": "u2", "name": "Inflammation", "opens": day(4), "tags": [f"{R}::02_Inflammation"]}])
    client("maya").follow_plan(code)
    w = AFace(client("sam"), select=pid)
    w.ops.run()
    w.click("rename", uid="u1", name="A")
    w.click("rename", uid="u2", name="B")
    w.click("send", why="two renames")
    undo = w.last()["head"]["undo"]
    take = next(x for x in undo if x["what"] and x["what"][0] == "take")
    w.click("undo", what=take["what"])
    w.click("discard", sure=True)
    check("review: while changes send, Take back is off and does nothing; Discard waits too",
          take["on"] is False and len(w.draft) == 2 and 'send("discard"); }, "t", { disabled: busy(),' in js)
    w.ops.run()
    check("review: ...and both went, as they were shown", [x["name"] for x in STORE.plans[pid]["doc"]["units"]] == ["A", "B"] and w.draft is None)

    # 5: Your AI app's change made while a send was out stays waiting
    w.click("rename", uid="u1", name="A2")
    w.click("send", why="a rename")
    d = w.ops.draft(pid)
    d.add({"op": "rename", "date": "u2", "name": "B from my AI"}, w.ctx())
    w.ops.keep_draft(pid, d)
    w.draft_changed(pid)
    w.ops.run()
    kept = w.ops.draft(pid)
    check("review: a change Your AI app put under the plan during a send stays waiting, on the plan as sent",
          kept is not None and len(kept) == 1 and kept.ops[0].get("name") == "B from my AI" and w.draft is not None and len(w.draft) == 1
          and [x["name"] for x in w.doc["units"]] == ["A2", "B from my AI"] and "from your AI app is waiting" in w._status,
          (kept and kept.ops, w._status))

    # 6: Make again renames the half-made plan; New plan doesn't start over under a Make
    STORE.add_user("zed", "Zed", code="ZED123")
    w = AFace(client("zed"))
    w.click("new_step", step="empty")
    w.click("new_set", key="name", value="Heme blok")
    w.ops.fail_save = True
    w.click("new_make", start=False, sure=True)
    w.new_open(finish_by=day(30), exam="Block exam")
    still = w.new["step"] == "empty" and w.new["busy"]
    w.ops.run("make")
    made = w.new["made"]
    w.click("new_set", key="name", value="Heme block")
    w.click("new_make", start=False)
    w.ops.run("make")
    w.ops.run()
    zed = [p for p in STORE.plans.values() if p["owner"] == "zed"]
    check("review: New plan doesn't start over while a Make is out; Make again renames the half-made plan, one plan",
          still and made and len(zed) == 1 and zed[0]["name"] == "Heme block", (still, made, [p["name"] for p in zed]))

    # 8: a library plan's follower gets no note box
    pid, code = plan([{"id": "c1", "name": "Anemias", "opens": TODAY.isoformat(), "tags": [f"{R}::03_Neoplasia"]}], owner="dre", name="Library plan")
    STORE.plans[pid]["listed"] = 1
    sam = client("sam")
    sam.follow_plan(code)
    w = Face(sam, select=pid)
    w.notes, w.notes_of = [], pid
    w.click("pick", key=["date", "c1"])
    check("review: a library plan's follower gets no note box (it's the plan's authors' alone)",
          w.plan.get("library") is True and w.raw is None and w.last()["panel"]["notes"]["writes"] is False)


def test_the_page_draws_its_own_days_v396():
    """3.9.6 (Sam's click test: Anki quit as a set was put on just after a
    day was picked): no date box in the window is the computer's own (on a
    Mac its popup is native, inside Anki's process, and Liquid Glass); every
    day is picked on the page's calendar, which opens over a sheet."""
    page = os.path.join(REPO, "due_crew", "planner", "page")
    js = {f: open(os.path.join(page, f), encoding="utf-8").read() for f in ("plan.js", "tabs.js", "new.js")}
    css = open(os.path.join(page, "plan.css"), encoding="utf-8").read()
    check("page: no native date box anywhere in the window's scripts",
          not any(re.search(r'type:\s*"date"|type=\\?"date|\.type\s*=\s*"date"', t) for t in js.values()), "")
    check("page: the day boxes are the page's (plan.js dateInput, calPop); Settings' use it too; a sheet's date field too",
          "function calPop(" in js["plan.js"] and 'h("button.in.date"' in js["plan.js"] and "c.dateInput(" in js["tabs.js"]
          and 'f.type === "date" ? dateInput(' in js["plan.js"])
    z = lambda sel: int(re.search(re.escape(sel) + r" \{[^}]*z-index: (\d+)", css).group(1))  # noqa: E731
    check("page: the calendar opens over a sheet's veil", z(".dcp .calp") > z(".dcp .veil"), (z(".dcp .calp"), z(".dcp .veil")))


# The page pressed (test_every_control_pressed): each state's view drawn in node, every control fired (its
# menus and their sub-menus, a day picked in each calendar, the keys), a sheet's own yes with its boxes filled
# in as a person fills them, and its no; each message kept by what sent it. The page's ui (List, Find, folds)
# goes back to how it opens before each control, so one control's state never hides the next.
PRESS_JS = r"""
const fs = require("fs"), vm = require("vm");
const [PAGE, STATES] = process.argv.slice(1);
const src = ["plan.js", "tabs.js", "new.js"].map((f) => fs.readFileSync(PAGE + "/" + f, "utf8")).join("\n");
const states = JSON.parse(fs.readFileSync(STATES, "utf8"));
function El(tag) {
  this.tagName = String(tag).toUpperCase(); this.children = []; this.parent = null; this.attrs = {}; this.style = {};
  this.className = ""; this._t = ""; this.ls = {}; this.value = ""; const self = this;
  this.classList = { add(c) { self.className += " " + c; }, remove() {}, toggle() {}, contains(c) { return (" " + self.className + " ").indexOf(" " + c + " ") >= 0; } };
}
Object.defineProperty(El.prototype, "textContent", { get() { return this._t + this.children.map((c) => c.textContent || "").join(""); },
  set(v) { this._t = String(v); this.children.forEach((c) => { c.parent = null; }); this.children = []; } });
Object.defineProperty(El.prototype, "childNodes", { get() { return this.children; } });
Object.defineProperty(El.prototype, "parentNode", { get() { return this.parent; } });
El.prototype.appendChild = function (c) { if (c.parent) { c.remove(); } c.parent = this; this.children.push(c); return c; };
El.prototype.remove = function () { if (this.parent) { const i = this.parent.children.indexOf(this); if (i >= 0) { this.parent.children.splice(i, 1); } this.parent = null; } };
El.prototype.setAttribute = function (k, v) { this.attrs[k] = v; if (k === "disabled") { this.disabled = true; } if (k === "checked") { this.checked = true; } };
El.prototype.getAttribute = function (k) { return k in this.attrs ? this.attrs[k] : null; };
El.prototype.addEventListener = function (t, f) { (this.ls[t] = this.ls[t] || []).push(f); };
function matches(el, sel) {  /* the selectors the page asks for: .a.b, #id, [attr], [attr=v], a tag; the last part of a descendant one */
  const last = sel.trim().split(/\s+/).pop();
  if (last[0] === ".") { return last.slice(1).split(".").every((c) => (" " + el.className + " ").indexOf(" " + c + " ") >= 0); }
  if (last[0] === "#") { return el.attrs.id === last.slice(1); }
  const m = /^\[([\w-]+)(?:=(.*))?\]$/.exec(last);
  if (m) { return m[1] in el.attrs && (m[2] === undefined || String(el.attrs[m[1]]) === m[2].replace(/^"|"$/g, "")); }
  return el.tagName === last.toUpperCase();
}
function all(el) { const out = []; (function walk(n) { (n.children || []).forEach((c) => { if (c instanceof El) { out.push(c); walk(c); } }); })(el); return out; }
El.prototype.querySelector = function (sel) { return all(this).find((c) => matches(c, sel)) || null; };
El.prototype.querySelectorAll = function (sel) { return all(this).filter((c) => matches(c, sel)); };
El.prototype.click = function () { fire(this, "click"); };
El.prototype.getBoundingClientRect = function () { return { left: 0, top: 0, right: 10, bottom: 10, width: 10, height: 10 }; };
["focus", "blur", "select", "scrollIntoView", "setSelectionRange"].forEach((k) => { El.prototype[k] = function () {}; });
function Text(t) { this.textContent = String(t); this.parent = null; }
Text.prototype.remove = El.prototype.remove;
function ev(el, key) { return { target: el, currentTarget: el, stopPropagation() {}, preventDefault() {}, key: key || "Enter" }; }
function fire(el, t, key) { (el.ls[t] || []).slice().forEach((f) => f.call(el, ev(el, key))); }
function act(el) {
  if (el.tagName === "SELECT") {  /* another option than the one shown, as a person picks */
    const o = el.children.filter((c) => c.tagName === "OPTION"), x = o.find((y) => !y.selected && (y.value || y.attrs.value)) || o[o.length - 1];
    el.value = x ? (x.value || x.attrs.value || "") : ""; fire(el, "change"); return;
  }
  if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") {
    el.value = (el.attrs.type || "text") === "number" ? "30" : "Typed here"; el.checked = !el.checked;
    fire(el, "input"); fire(el, "change"); fire(el, "keydown"); return;
  }
  if (el.ls.click) { fire(el, "click"); } else if (el.ls.dblclick) { fire(el, "dblclick"); } else { fire(el, "keydown", "Enter"); }
}
function label(el) { return (el.attrs["aria-label"] || el.attrs.title || el.textContent || el.tagName).slice(0, 60); }
const UI = { find: "", look: false, opened: {}, closed: {}, all: null, month: null, week: null, paste: "", deckFind: null, tb: {}, sheet: null };
const out = {};
Object.keys(states).forEach((key) => {
  const st = states[key], errors = [], presses = [];
  let sent = [];
  const root = new El("div"), docLs = {};
  const ctx = { console, setTimeout: (f) => { try { f(); } catch (e) { /* a focus */ } }, clearTimeout() {}, JSON,
    document: { createElement: (t) => new El(t), createTextNode: (t) => new Text(t), getElementById: (id) => (id === "dcp" ? root : root.querySelector("#" + id)),
      activeElement: null, addEventListener: (t, f) => { (docLs[t] = docLs[t] || []).push(f); } } };
  ctx.window = ctx; ctx.innerWidth = 1240; ctx.innerHeight = 820; ctx.pycmd = (m) => sent.push(m);
  vm.createContext(ctx);
  vm.runInContext(src, ctx);
  const P = ctx.dcPlan;
  function draw() {
    (docLs.click || []).forEach((f) => f(ev(root)));  /* a menu open from before, closed */
    P.show(st.view); P.set(Object.assign({}, UI, { mode: st.mode || "list", opened: {}, closed: {}, tb: {} }));
    if (st.sheet) { P.sheet(st.sheet); }
  }
  function controls() {  /* with a sheet up, only what's on it (its veil covers the page); its yes and no are pressed below */
    const veil = st.sheet ? root.querySelector(".veil") : null, acts = veil && veil.querySelector(".acts");
    return all(veil || root).filter((el) => (el.ls.click || el.ls.change || el.ls.dblclick || el.ls.input || (box(el) && el.ls.keydown))
      && !(acts && el.parent === acts) && !hidden(el));
  }
  function box(el) { return el.tagName === "TEXTAREA" || (el.tagName === "INPUT" && (el.attrs.type || "text") === "text"); }
  function shape() { return JSON.stringify(all(root).map((e) => [e.tagName, e.className, e._t, e.style.display || "", e.value || ""])); }
  function hidden(el) { for (let x = el; x; x = x.parent) { if (x.style.display === "none" || "hidden" in x.attrs) { return true; } } return false; }  /* nobody presses what isn't shown (a Save till something's typed) */
  function menus() { return root.children.filter((c) => / menu /.test(" " + c.className + " ")); }
  function items(m) { return (m ? m.children : []).filter((c) => c.ls && c.ls.click && !/ off /.test(" " + c.className + " ")); }  /* an off item is shown off */
  /* may do nothing: the choice already on (List in List), or a button whose box beside it is empty (pressed typed below) */
  function quiet(el) {
    return / on /.test(" " + el.className + " ") || el.attrs["aria-pressed"] === "true"
      || (el.parent ? el.parent.children : []).some((b) => b !== el && box(b) && !String(b.value || "").trim());
  }
  let quietly = null;
  function press(what, fn) {
    sent = [];
    const was = shape();
    try { fn(); } catch (e) { errors.push(what + ": " + e.stack.split("\n").slice(0, 3).join(" ")); }
    presses.push({ what, sent: sent.slice(), page: shape() !== was, quiet: !!(quietly && quietly()) });  /* page: it changed something here (a fold, the month, a menu) */
  }
  try { P.start(st.view, true); draw(); } catch (e) { errors.push("draw: " + e.stack); }
  const text = root.textContent;
  if (st.sheet) {  /* its yes, filled in as a person does: a line in each box, the day after the one shown; then its no */
    ["yes", "no"].forEach((which) => {
      draw();
      const veil = root.querySelector(".veil"), acts = veil && veil.querySelector(".acts"), b = acts && acts.children[which === "yes" ? 1 : 0];
      if (!b) { presses.push({ what: "sheet " + which, sent: [], none: true }); return; }
      veil.querySelectorAll("input").concat(veil.querySelectorAll("textarea")).forEach((i) => { if (!i.attrs.type || i.attrs.type === "text") { i.value = "Typed here"; } });
      veil.querySelectorAll(".date").forEach((d) => { if (/^\d{4}-\d\d-\d\d$/.test(d.value)) { const x = new Date(d.value + "T12:00:00"); x.setDate(x.getDate() + 1); d.value = x.toISOString().slice(0, 10); } });
      press("sheet " + which + " (" + label(b) + ")", () => { if (b.disabled) { throw new Error("its " + which + " is off"); } fire(b, "click"); });
    });
  }
  draw();
  const n = controls().length;
  for (let i = 0; i < n; i++) {
    draw();
    const el = controls()[i];
    if (!el || el.disabled) { continue; }
    const name = label(el);
    quietly = () => quiet(el);
    press(name, () => act(el));
    quietly = null;
    if (box(el)) {  /* typed in, then each button beside it (a note's Add, Show the changes, a Save): as a person types first */
      const beside = (el.parent ? el.parent.children : []).filter((b) => b !== el && b.tagName === "BUTTON");
      beside.forEach((_b, k) => {
        draw();
        const again = controls()[i];
        if (!again) { return; }
        again.value = "Typed here"; fire(again, "input");
        const b = (again.parent ? again.parent.children : []).filter((x) => x !== again && x.tagName === "BUTTON")[k];
        if (b && !b.disabled && !hidden(b)) { press(name + " typed › " + label(b), () => fire(b, "click")); }
      });
    }
    const opened = menus();
    if (!opened.length) { continue; }
    if (/ calp /.test(" " + opened[0].className + " ")) {  /* the page's calendar: a day in it, picked */
      draw(); act(controls()[i]);
      const cells = menus()[0] ? menus()[0].querySelectorAll(".cd") : [];
      if (cells.length) { press(name + " › a day", () => fire(cells[cells.length - 1], "click")); }
      continue;
    }
    items(opened[0]).forEach((_mi, j) => {
      draw(); act(controls()[i]);
      const again = items(menus()[0])[j];
      if (!again) { return; }
      const mname = name + " › " + label(again);
      press(mname, () => act(again));
      items(menus()[1]).forEach((_s, k) => {
        draw(); act(controls()[i]);
        const a2 = items(menus()[0])[j];
        if (!a2) { return; }
        act(a2);
        const s2 = items(menus()[1])[k];
        if (s2) { press(mname + " › " + label(s2), () => act(s2)); }
      });
    });
  }
  [["ArrowLeft", { altKey: true }], ["z", { ctrlKey: true }], ["Delete"], ["n", { ctrlKey: true }], ["e", { ctrlKey: true }],
    ["d", { ctrlKey: true }], ["Enter", { ctrlKey: true }], ["ArrowDown"]].forEach(([k, mods]) => {
    draw();
    press("key " + k, () => (docLs.keydown || []).forEach((f) => f(Object.assign({ key: k, ctrlKey: false, metaKey: false, altKey: false, preventDefault() {} }, mods || {}))));
  });
  out[key] = { presses, errors, text, controls: n };
});
process.stdout.write(JSON.stringify(out));
"""


def test_every_control_pressed():
    """Sam, 7 Nov: Review and send's Send closed its sheet and sent nothing
    (the sheet had a yes and no cmd); the test had called "send" itself. So
    the page is pressed here as a person presses it: every state the window
    draws (an author's plan, a set, a quiz, a review day, the deck beside it,
    changes waiting, a follower's, New plan's screens, Insights, Settings,
    and every sheet it asks with), each in node, every control fired; then
    each message the page sent goes back through a fresh window in that
    state. Each reaches its handler (none dropped, none under New plan that
    New plan doesn't take, no wrong arguments), each click does something,
    and a sheet's yes sends its own cmd, does something, and never draws the
    same sheet again. Every sheet webface and webnew can draw is pressed."""
    import shutil
    import tempfile
    import traceback
    import types
    from due_crew import planner as PL
    from due_crew.planner import webface as WF, webtabs as WT
    if not shutil.which("node"):
        print("SKIP the page pressed: no node")
        return
    opened, printed = [], []

    class Dlg:  # the Qt windows a click opens (date_dialogs' and the rest), stood in for: opened, then Cancel
        def __init__(self, *a, **k):
            opened.append(type(self).__name__)

        def exec(self):
            return False
    stand = {"date_dialogs": ("SplitDialog", "AddCardsDialog", "LinesDialog", "ReviewDialog", "MoveFromDialog"),
             "text_tab": ("TextDialog",), "mcp_dialog": ()}
    was_mods = {n: sys.modules.get("due_crew.planner." + n) for n in stand}
    was_attrs = {n: getattr(PL, n, None) for n in stand}
    for name, classes in stand.items():
        m = types.ModuleType("due_crew.planner." + name)
        for c in classes:
            setattr(m, c, type(c, (Dlg,), {}))
        m.show = lambda parent=None, ops=None: opened.append("mcp")
        sys.modules["due_crew.planner." + name] = m
        setattr(PL, name, m)
    print_exc = traceback.print_exc
    traceback.print_exc = lambda *a, **k: printed.append(1) or print_exc(*a, **k)  # a handler's TypeError, as _on_cmd says it

    class PFace(Face):
        def close(self):  # as web.py's closeEvent: changes waiting ask first
            if not self.unsent_ask():
                self._closed = True

    made = [0]

    def fresh(name):
        made[0] += 1
        uid = f"press{made[0]}"
        STORE.add_user(uid, name)  # a person of each state's own: one's follows and plans never reach another's ceilings
        return uid

    def a_plan(owner, followed=False):
        """Sets behind, today and ahead, a finish-by day, a quiz, a review day, a plan tag, a note on a card,
        to-dos; a pace a set's cards can't keep (a heavy week); a code of its own (the fake's repeat every 32 plans)"""
        made[0] += 1
        code = "PR" + "".join("ABCDEFGHJKLMNPQRSTUVWXYZ23456789"[(made[0] >> (5 * i)) % 32] for i in range(6))
        units = [{"id": "u0", "name": "Neoplasia", "opens": rel(-6), "tags": [f"{R}::03_Neoplasia"]},
                 {"id": "u1", "name": "Cell injury", "opens": rel(0), "tags": [f"{R}::01_Cell_injury"]},
                 {"id": "u2", "name": "Inflammation", "opens": rel(1), "due": rel(3), "tags": [f"{R}::02_Inflammation"]}]
        pid, code = STORE.add_plan(owner, "Path Book, high yield", "Big Step 1", units, code=code)
        doc = STORE.plans[pid]["doc"]
        doc["events"] = [{"id": "e1", "day": rel(5), "name": "Heme quiz"}]
        doc["pace"] = {"mode": "daily", "days": [1] * 7, "daily": 3}
        doc["reviews"] = [{"day": rel(4), "from": "u0", "to": "u2"}]
        doc["tagroot"], doc["tags"] = "PB", [{"id": "t1", "name": "SLG 5", "notes": []}]
        doc["remarks"] = [{"id": "r1", "card": ["g1", 0], "text": "on the quiz"}]
        next(u for u in doc["units"] if u["id"] == "u1")["todo"] = [{"k": "read", "t": "Chapter 3"}]
        if followed:
            client(fresh("Fen")).follow_plan(code)
        return pid

    def noted(w):
        w.notes, w.notes_of = [{"id": 1, "day": rel(0), "text": "Bring the atlas", "name": "You", "mine": True, "remove": True}], w.pid  # the Worker's ids are numbers
        w.push()

    def author(*clicks, followed=False):
        def make():
            me = fresh("Sam")
            a_plan(me)  # another of mine, to pick in the head
            w = PFace(client(me), select=a_plan(me, followed))
            noted(w)
            for c, a in clicks:
                w.click(c, **a)
            return w
        return make

    def follower(*clicks):
        def make():
            me = fresh("Sam")
            a_plan(me)
            pid = a_plan(fresh("Dre"))
            cl = client(me)
            cl.follow_plan(STORE.plans[pid]["code"])
            w = PFace(cl, select=pid)
            for c, a in clicks:
                w.click(c, **a)
            return w
        return make

    def nobody(*clicks):
        def make():
            w = PFace(client(fresh("Zed")))
            for c, a in clicks:
                w.click(c, **a)
            return w
        return make

    cells = f"tag:{R}::01_Cell_injury"
    rename, pick1, picke = ("rename", {"uid": "u1", "name": "Cells"}), ("pick", {"key": ["date", "u1"]}), ("pick", {"key": ["event", "e1"]})
    states = {
        "author": author(), "author week": author(), "author month": author(),
        "a set": author(pick1), "a set behind": author(("pick", {"key": ["date", "u0"]})), "a quiz": author(picke),
        "a review day": author(("pick", {"key": ["review", rel(4)]})),
        "the deck, adding to a set": author(("deck", {"uid": "u1"})), "the deck, laying out": author(("deck", {}), ("deck_tick", {"key": f"tag:{R}::03_Neoplasia", "on": True})),
        "the deck, the plan's tags": author(("deck", {"uid": "u1"}), ("deck_view", {"view": "plan"})),
        "the deck, found": author(("deck", {"uid": "u1"}), ("deck_find", {"text": "inflam"})),
        "changes waiting": author(rename, followed=True), "insights": author(("tab", {"tab": "insights"})),
        "settings": author(("tab", {"tab": "settings"})), "settings, changes waiting": author(rename, ("tab", {"tab": "settings"}), followed=True),
        "a follower": follower(), "a follower week": follower(), "a follower's set": follower(pick1), "a follower's insights": follower(("tab", {"tab": "insights"})),
        "new plan": nobody(), "new plan, a resource": nobody(("new_step", {"step": "resource"})),
        "new plan, empty": nobody(("new_step", {"step": "empty"}), ("new_set", {"key": "name", "value": "Heme"})),
        "new plan, someone's": nobody(("new_step", {"step": "someone"})),
    }
    sheets = {  # every sheet webface and webnew draw: the clicks that draw it
        "discard": author(rename, ("discard", {}), followed=True), "send": author(rename, ("review_send", {}), followed=True),
        "close with changes waiting": author(rename, ("close", {}), followed=True), "move onto a taken day": author(("move", {"uid": "u2", "to": rel(0)})),
        "a note for followers": author(pick1, ("remark", {"path": f"{R}::01_Cell_injury"})),
        "move a source to a day": author(pick1, ("move_source_form", {"i": 0})), "delete a set": author(pick1, ("delete", {})),
        "take a quiz off": author(picke, ("delete", {})), "a new set": author(("new_date_form", {})),
        "a new set on a taken day": author(("new_date", {"name": "Again", "day": rel(0)})), "a quiz": author(("new_event_form", {})),
        "a review day": author(("new_review_form", {})), "a set of its own": author(("lesson_from", {"key": cells, "day": None})),
        "give everyone a day": author(("breather", {})), "rename a tag": author(("ptag_rename", {"ptag": "t1"})),
        "delete a tag": author(("ptag_delete", {"ptag": "t1"})), "the prompt": author(("see_prompt", {"which": "plan"})),
        "make a plan": nobody(("new_step", {"step": "empty"}), ("new_set", {"key": "name", "value": "Heme"}), ("new_make", {"start": False})),
    }
    views, pids, drew = {}, {}, {}
    for key, make in list(states.items()) + [("sheet " + k, v) for k, v in sheets.items()]:
        w = make()
        views[key] = {"view": w.view(), "mode": "week" if key.endswith(" week") else "month" if key.endswith(" month") else None}
        pids[key] = [p["id"] for p in w.plans]
        if key.startswith("sheet "):
            drew[key] = w.last("sheet")
            views[key]["sheet"] = drew[key]
    makers = dict(states, **{"sheet " + k: v for k, v in sheets.items()})
    try:
        with tempfile.TemporaryDirectory() as tmp:
            sp = os.path.join(tmp, "states.json")
            with open(sp, "w", encoding="utf-8") as f:
                json.dump(views, f)
            got = subprocess.run(["node", "-e", PRESS_JS, os.path.join(REPO, "due_crew", "planner", "page"), sp],
                                 capture_output=True, text=True, timeout=300)
        try:
            out = json.loads(got.stdout)
        except ValueError:
            check("press: the page ran in node", False, got.stderr[-2000:])
            return
        errors = {k: o["errors"][:2] for k, o in out.items() if o["errors"]}
        check(f"press: the page drew all {len(out)} states and fired every control without an error ({sum(len(o['presses']) for o in out.values())} presses)",
              not errors and all(o["controls"] or k.startswith("sheet ") for k, o in out.items()), errors)
        dropped, wrong, idle, loops, mute = [], [], [], [], []
        dead = [(k, p["what"]) for k, o in out.items() for p in o["presses"]
                if not p["sent"] and not p.get("page") and not p.get("none") and not p.get("quiet") and not p["what"].startswith("key ")]
        check("press: every control sends something or changes something on the page", not dead, dead[:8])
        reached = {json.loads(m[len(WF.PREFIX):])["c"] for o in out.values() for p in o["presses"] for m in p["sent"]}
        expect = {"add_search", "breather", "browse", "calendar", "card_note_off", "close", "copy_search", "copy_source", "deck", "deck_done",
                  "deck_find", "deck_keep", "deck_open", "deck_tick", "deck_view", "delete", "discard", "event_kind", "event_sets", "keep_only", "lesson_from",
                  "move", "move_event", "move_from", "move_source_form", "new_cancel", "new_date", "new_date_form", "new_event", "new_event_form",
                  "new_follow", "new_library", "new_make", "new_plan", "new_review_form", "new_set", "new_step", "note_add", "note_off", "nudge",
                  "op", "open_now", "paste", "pick", "pick_plan", "prompt", "ptag_delete", "ptag_rename", "remark", "rename", "rename_event",
                  "review_day", "review_send", "see_prompt", "send", "set_cut", "set_due", "set_for", "spread", "spread_heavy", "study", "tab",
                  "tabcmd", "take_change", "text", "todo", "todo_off", "undo", "undo_key"}
        check("press: the walk reaches every one of the window's own clicks (Insights' and Settings' are test_plan_web_tabs')",
              expect <= reached, sorted(expect - reached))

        def mark(w):
            o = w.ops
            return json.dumps([len(w.js), sum(int(p.get("version") or 0) for p in STORE.plans.values()), len(STORE.plans),
                               len(o.browsed), len(o.opened), len(o.studied), len(o.started), len(o.followed), len(o.pages),
                               o.drafts, w.copied, getattr(w, "_closed", False), len(opened), getattr(w, "_saved_file", None)],
                              sort_keys=True, default=str)
        for key, o in out.items():
            seen = set()
            for p in o["presses"]:
                if key.startswith("sheet ") and p["what"].startswith("sheet yes"):
                    sh = drew[key]
                    if not p["sent"] or json.loads(p["sent"][0][len(WF.PREFIX):])["c"] != sh.get("cmd"):
                        mute.append((key, sh.get("title"), p["sent"]))
                for m in p["sent"]:
                    if m in seen and not p["what"].startswith("sheet "):
                        continue
                    seen.add(m)
                    w = makers[key]()
                    for old, new in zip(pids[key], [x["id"] for x in w.plans]):
                        m = m.replace(f'"{old}"', f'"{new}"')  # the page's plan ids, this window's
                    d = json.loads(m[len(WF.PREFIX):])
                    c, a = d["c"], d["a"]
                    if not (hasattr(w, "c_" + c) and (w.new is None or c in WF.NEW_CMDS)
                            and (c != "tabcmd" or callable(getattr(WT, "c_" + str(a.get("name")), None)))):
                        dropped.append((key, p["what"], m))
                        continue
                    before, n_sheets = mark(w), sum(1 for j in w.js if j.startswith("dcPlan.sheet("))
                    printed.clear()
                    w._on_cmd(m)
                    if printed:
                        wrong.append((key, p["what"], m))
                    if mark(w) == before and not p["what"].startswith("key "):
                        idle.append((key, p["what"], m))
                    after = [json.loads(j[len("dcPlan.sheet("):-1]) for j in w.js if j.startswith("dcPlan.sheet(")]
                    if p["what"].startswith("sheet yes") and len(after) > n_sheets and after[-1] == drew[key]:
                        loops.append((key, p["what"], m))
        check("press: every message the page sent reaches its handler in that state (none dropped, none New plan doesn't take)", not dropped, dropped[:5])
        check("press: no handler took the wrong arguments", not wrong, wrong[:5])
        check("press: every click did something (a key may not, where it isn't for that state)", not idle, idle[:8])
        check("press: every sheet's yes sends the sheet's own cmd (Sam, 7 Nov: Send to N sent nothing)", not mute and len(drew) == len(sheets), mute[:5])
        check("press: a sheet's yes never draws the same sheet again (duecrew.com's Add to the plan did, every press)", not loops, loops[:5])
        import ast
        can = set()  # every sheet the two can draw, by its cmd: an ask(…, cmd), or a dict with a yes and a cmd
        for f in ("webface.py", "webnew.py"):
            for node in ast.walk(ast.parse(open(os.path.join(REPO, "due_crew", "planner", f), encoding="utf-8").read())):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "ask" and len(node.args) > 3 \
                        and isinstance(node.args[3], ast.Constant):
                    can.add(node.args[3].value)
                elif isinstance(node, ast.Dict):
                    keys = {k.value: v for k, v in zip(node.keys, node.values) if isinstance(k, ast.Constant)}
                    if "yes" in keys and isinstance(keys.get("cmd"), ast.Constant):
                        can.add(keys["cmd"].value)
        pressed = {sh.get("cmd") for sh in drew.values() if sh}
        check("press: every sheet webface and webnew can draw is pressed above", len(can) >= 15 and can <= pressed, sorted(can - pressed))
    finally:
        traceback.print_exc = print_exc
        for name in stand:
            if was_mods[name] is None:
                sys.modules.pop("due_crew.planner." + name, None)
            else:
                sys.modules["due_crew.planner." + name] = was_mods[name]
            if was_attrs[name] is None:
                if hasattr(PL, name):
                    delattr(PL, name)
            else:
                setattr(PL, name, was_attrs[name])



def _own_code():
    """A plan code no other plan in the fake has (its own repeat every 32 plans)."""
    a, n = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789", len(STORE.plans)
    return "NQ" + "".join(a[(n >> (5 * i)) % 32] for i in range(6))


def _near_plan(me, sets=185, cards=0, tags_each=0):
    """3.9.9: a plan of `me`'s near its ceilings, someone following it: (pid, the window on it)."""
    STORE.add_user(me, me.title())
    left, units = cards, []
    for i in range(sets):
        u = {"id": f"s{i}", "name": f"Set {i}", "opens": rel(i - 60), "tags": [f"{R}::01_Cell_injury"] if i == 0 else []}
        if left > 0:
            n = min(left, 20000)
            u["cards"], left = [[f"g{i}x{j}", 0] for j in range(n)], left - n
        if tags_each:
            u["tags"] = [f"{R}::{'x' * 150}::{i}_{j}" for j in range(tags_each)]
        units.append(u)
    pid, code = STORE.add_plan(me, "Path Book, all of it", "Big Step 1", units, code=_own_code())
    STORE.add_user(me + "f", "Fen")
    client(me + "f").follow_plan(code)
    return pid, Face(client(me), select=pid)


def test_review_and_send_says_a_ceiling_near_v399():
    """3.9.9 (Sam's sign-off): Review and send says each ceiling the plan as it
    would be sent is past 90% of, a line each in the sheet's amber, before the
    Worker would refuse it: "Picked cards and IDs: 47,900 of 50,000.", "Size:
    1.4 of 1.5 MB."; nothing at 90% or under. The page draws them, and the
    sheet's buttons do what they did (pressed in node: its Send sends)."""
    import shutil
    import tempfile
    from due_crew.planner import build as B
    from due_crew.planner import edits as E
    from due_crew.planner import webface as WF
    pid, w = _near_plan("nearly", sets=185, cards=47_900)
    w.click("rename", uid="s1", name="Cells")
    w.click("review_send")
    sh = w.last("sheet")
    check("near: Review and send says the ceilings the plan is past 90% of, a line each",
          sh and sh["kind"] == "send" and sh["warns"] == ["Sets: 185 of 200.", "Picked cards and IDs: 47,900 of 50,000."], sh and sh.get("warns"))
    check("near: the lines are remote.near's on the doc a send sends (edits.lean), Ceilings.near's twin",
          sh["warns"] == PR.near(E.lean(w.draft.doc(w.ctx()))), "")
    _pid2, w2 = _near_plan("roomy", sets=180, cards=45_000)
    w2.click("rename", uid="s1", name="Cells")
    w2.click("review_send")
    check("near: at 90% or under, no line", w2.last("sheet")["warns"] == [], w2.last("sheet").get("warns"))
    _pid3, w3 = _near_plan("wordy", sets=180, tags_each=45)
    w3.click("rename", uid="s1", name="Cells")
    w3.click("review_send")
    size = B.ceiling_counts(E.lean(w3.draft.doc(w3.ctx())))["size"]
    check("near: the plan's size as the Worker measures the doc a save sends, in MB rounded down under the ceiling",
          w3.last("sheet")["warns"] == ["Size: 1.4 of 1.5 MB."] and 1.4 * 1048576 <= size < 1536 * 1024, (w3.last("sheet").get("warns"), size))
    if not shutil.which("node"):
        print("SKIP near: the page in node: no node")
        return
    with tempfile.TemporaryDirectory() as tmp:
        sp = os.path.join(tmp, "states.json")
        with open(sp, "w", encoding="utf-8") as f:
            json.dump({"send near": {"view": w.view(), "sheet": sh}}, f)
        got = subprocess.run(["node", "-e", PRESS_JS, os.path.join(REPO, "due_crew", "planner", "page"), sp], capture_output=True, text=True, timeout=300)
    try:
        out = json.loads(got.stdout)["send near"]
    except ValueError:
        check("near: the page ran in node", False, got.stderr[-2000:])
        return
    yes = next((p for p in out["presses"] if p["what"].startswith("sheet yes")), None)
    check("near: the page draws each line in the sheet; its controls and buttons pressed without an error",
          not out["errors"] and all(t in out["text"] for t in sh["warns"]) and yes and yes["sent"], (out["errors"], yes))
    v0 = STORE.plans[pid]["version"]
    w._on_cmd(yes["sent"][0])
    check("near: the sheet's Send still sends: one save, nothing waiting",
          json.loads(yes["sent"][0][len(WF.PREFIX):])["c"] == "send" and STORE.plans[pid]["version"] == v0 + 1 and not w.draft, w._status)


def test_a_refused_send_keeps_its_changes_v399():
    """3.9.9: a send refused at a ceiling says which, with the server's
    numbers; past the day's saves it says the changes wait, and they do:
    under the plan, kept on this computer (draft.py), till the next send
    (tomorrow's) takes them. One saved at once (nobody following) is said as
    before: nothing waits there."""
    from due_crew.planner.draft import Draft
    STORE.add_user("busy", "Busy")
    pid, code = STORE.add_plan("busy", "Path Book", "Big Step 1", [{"id": "u1", "name": "Cell injury", "opens": day(3), "tags": [f"{R}::01_Cell_injury"]}],
                               code=_own_code())
    STORE.add_user("busyf", "Fen")
    client("busyf").follow_plan(code)
    w = Face(client("busy"), select=pid)
    w.click("rename", uid="u1", name="Cells")
    today = datetime.date.today().isoformat()
    STORE.plan_saves[("busy", today)] = STORE.PLAN_SAVES_A_DAY
    v0 = STORE.plans[pid]["version"]
    w.click("review_send")
    w.press(w.last("sheet"), why="Renamed it")
    kept = w.ops.drafts.get(str(pid))
    check("refused: past the day's saves, a send says so, and that its changes wait",
          w._status == "500 saves a day. Your changes wait here and send tomorrow." == PR.SLOW_WAITS, w._status)
    again = Draft.from_json(pid, kept) if kept else None
    check("refused: …and they do: still under the plan, kept on this computer as they were, nothing sent",
          w.draft and len(w.draft) == 1 and again and len(again) == 1 and STORE.plans[pid]["version"] == v0
          and w.last()["plan"]["sending"]["n"] == 1, (kept, w.last()["plan"].get("sending")))
    STORE.plan_saves.pop(("busy", today))  # tomorrow
    w.click("review_send")
    w.press(w.last("sheet"), why="Renamed it")
    check("refused: the next day's send takes them", STORE.plans[pid]["version"] == v0 + 1 and not w.draft
          and next(u for u in STORE.plans[pid]["doc"]["units"] if u["id"] == "u1")["name"] == "Cells", w._status)
    # a ceiling: the account's plans full; said with what they hold now, the changes still waiting
    STORE.plans["pfillbusy0000000"] = {"code": "FILLBUSY", "owner": "busy", "name": "F", "line": "", "audience": "code", "squad": None,
                                       "version": 1, "doc": {"deck": "F", "units": [], "pad": "x" * (24 * 1048576 - 5_000)}}
    w.click("op", op={"op": "add_date", "day": day(9), "name": "Big", "tags": [f"{R}::{'z' * 150}::{i}" for i in range(50)]})
    w.click("rename", uid="u1", name="Cell injury and death")
    held = STORE._plan_bytes("busy")
    w.click("review_send")
    w.press(w.last("sheet"), why="More")
    check("refused: a ceiling says which, the numbers the server's (the account's plans together, what they hold now)",
          w._status == PR.LIMIT_WORDS["total"].format(max="24", have=PR.mb(held, 24 * 1048576)) and w._status.startswith(
              "Your plans can be up to 24 MB together. They're at 23.9 MB.") and w.draft and len(w.draft) == 2, (w._status, held))
    del STORE.plans["pfillbusy0000000"]
    # nobody following: a change saves at once, and a refusal says what it said
    STORE.add_user("solo", "Solo")
    pid2, _c = STORE.add_plan("solo", "Mine", "Big Step 1", [{"id": "u1", "name": "Cell injury", "opens": day(3), "tags": [f"{R}::01_Cell_injury"]}])
    w3 = Face(client("solo"), select=pid2)
    STORE.plan_saves[("solo", today)] = STORE.PLAN_SAVES_A_DAY
    w3.click("rename", uid="u1", name="Cells")
    check("refused: saved at once (nobody following), the day's saves say what they said: nothing waits there",
          w3._status == "That's a lot of saves today. Try again tomorrow." and not w3.draft, w3._status)
    STORE.plan_saves.pop(("solo", today))


def test_share_hint_v399():
    """3.9.9, plans as the way in: my plan with dates on it and nobody
    following says where its link is, once a window; never a plan someone
    follows, one for a squad alone, a co-author's, or one just begun."""
    from due_crew.planner import core as C

    class W(C.PlanCore):
        def __init__(self, plan, raw, units):
            self.plan, self.raw, self.doc = plan, raw, {"units": [{"id": f"u{i}"} for i in range(units)]}
    mine = {"id": "p1", "role": "owner", "followers": 1, "following": True}
    w = W(mine, {"code": "HEME2BLK", "audience": "code"}, 6)
    first, again = w.share_hint("p1"), w.share_hint("p1")
    check("share: a plan of mine with dates and nobody else following: where its link is, once",
          "Copy link" in first and "your class" in first and again == "", (first, again))
    quiet = [W(dict(mine, followers=4), {"code": "X"}, 6).share_hint("p1"),
             W(dict(mine, role="editor"), {"code": "X"}, 6).share_hint("p1"),
             W(mine, {"code": "X", "audience": "squad"}, 6).share_hint("p1"),
             W(mine, {"code": "X"}, C.SHARE_FROM - 1).share_hint("p1"),
             W(mine, {}, 6).share_hint("p1")]
    check("share: not when someone follows, for a co-author, a squad's plan, a plan just begun, or one with no code", quiet == [""] * 5, quiet)


def main():
    for n in [n for n in list(globals()) if n.startswith("test_")]:
        globals()[n]()
    check("web: every sheet with a yes sends a cmd when it's pressed (the page sends nothing without one)", not DEAD_SHEETS, DEAD_SHEETS)
    check("web: everything a view or a sheet drew to be clicked has its handler; no menu item with nothing to do", not DEAD_CLICKS,
          sorted(set(map(str, DEAD_CLICKS)))[:8])
    bad = [c for c in CHECKS if not c[1]]
    print(f"\n{len(CHECKS) - len(bad)}/{len(CHECKS)} checks passed")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
