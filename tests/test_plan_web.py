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
TODAY = datetime.date.today()
MON = TODAY - datetime.timedelta(days=TODAY.weekday())
R = "#Big_Step_1::#Path_Book"


def check(name, cond, detail=""):
    CHECKS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond or detail == "" else f"\n     {detail}"))


def day(n):
    return (MON + datetime.timedelta(days=n)).isoformat()


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
            version = PR.load(self.cl, pid)[0].get("version") or 1
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


class Face(WebFace):
    def __init__(self, cl, select=None, tab=None):
        self.js, self.copied = [], None
        self.web_init(COL, PR.my_plans(cl), Ops(cl), select, tab, {})
        self._ready = True
        if self.pid:
            self.load(self.pid)

    def eval_js(self, js):
        self.js.append(js)

    def copy(self, text):
        self.copied = text

    def click(self, c, **a):
        self._on_cmd("dcplan:" + json.dumps({"c": c, "a": a}))

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
    w.click("send", why="Renamed it")
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
    w.click("undo", what=["undo"])


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
    hy = next((o for o in r["only"] if o["label"] == "High Yield"), None)
    check("web: Only: the tags some of it carries", hy and hy["n"] == 18, r["only"])
    w.click("new_set", key="only", value=hy["path"])
    r = w.view()["new"]["resource"]
    check("web: with Only, its count and its name", r["onlyCount"] == "18 of 36" and r["name"] == "Path Book, high yield", r)
    w.click("new_set", key="pace", value="by")
    w.click("new_set", key="by", value=day(30))
    w.click("new_set", key="end_name", value="Block exam")
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
    check("web: Add to my calendar: an .ics file named for the plan, saved where I pick", name == "Path Book high yield.ics"
          and text.startswith("BEGIN:VCALENDAR\r\nVERSION:2.0\r\n") and text.endswith("END:VCALENDAR\r\n")
          and "Saved." in w._status, (name, w._status))
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
    check("web: each part of the page is in it", all(f"dcPlan.{x}" in html for x in ("newPlan",)), "")
    check("web: the deck panel's views are the Qt panel's", [k for k, _ in WM.VIEWS] == ["resource", "system", "other", "deck", "plan"])


def main():
    for n in [n for n in list(globals()) if n.startswith("test_")]:
        globals()[n]()
    bad = [c for c in CHECKS if not c[1]]
    print(f"\n{len(CHECKS) - len(bad)}/{len(CHECKS)} checks passed")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
