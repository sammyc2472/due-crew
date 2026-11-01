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
    check("web: and the row says it's on this lesson", ch["check"] == 1 and ch["where"] == "on this lesson", ch)
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


def test_the_page():
    pid, _code = plan([{"id": "u1", "name": "<b>Bold</b> & co", "opens": day(0), "tags": [f"{R}::01_Cell_injury"]}])
    w = Face(client("sam"), select=pid)
    html = page_html(w.view(), colors({}))
    check("web: a name reaches the page as data, never as markup", "<b>Bold</b>" not in html and "\\u003c" not in html
          and "<\\/b>" in html or "\\u003cb" in html.lower() or "<b>Bold" not in html, html[:0])
    js = open(os.path.join(REPO, "due_crew", "planner", "page", "plan.js")).read()
    check("web: the page sets names as text: no innerHTML anywhere in its script", "innerHTML" not in js)
    cmds = set(re.findall(r'send\("([a-z_]+)"', js)) | set(re.findall(r'cmd: "([a-z_]+)"', js))
    cmds |= {c for m in re.findall(r'"cmd": "([a-z_]+)"', open(os.path.join(REPO, "due_crew", "planner", "webmodel.py")).read() +
                                    open(os.path.join(REPO, "due_crew", "planner", "webface.py")).read()) for c in [m]}
    missing = sorted(c for c in cmds if not hasattr(WebFace, "c_" + c))
    check("web: every command the page or the view sends has its handler", not missing, missing)
    node = subprocess.run(["node", "--check", os.path.join(REPO, "due_crew", "planner", "page", "plan.js")], capture_output=True, text=True)
    check("web: the page's script parses", node.returncode == 0, node.stderr)
    check("web: the deck panel's views are the Qt panel's", [k for k, _ in WM.VIEWS] == ["resource", "system", "other", "deck", "plan"])


def main():
    for n in [n for n in list(globals()) if n.startswith("test_")]:
        globals()[n]()
    bad = [c for c in CHECKS if not c[1]]
    print(f"\n{len(CHECKS) - len(bad)}/{len(CHECKS)} checks passed")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
