"""Render the HTML plan window (due_crew/planner/web.py) as standalone pages,
from the real view code (webface, webmodel, webpage) on a sample deck and
plan held by the fake Worker: an author's plan, a follower's, the deck
beside the plan, Week and Month, a sheet open. No Anki, no Qt.

    python3 tools/plan_preview.py OUT_DIR

writes OUT_DIR/<name>.html for each; tools/plan_preview.js screenshots them
(light, dark, narrow). Clicks print the "dcplan:" message they'd send."""

import datetime
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import fakes  # noqa: E402

STORE = fakes.FakeWorker()
fakes.install_fake_requests(STORE)
fakes.install_fake_aqt()

from due_crew.backend import api  # noqa: E402
from due_crew import plans as P  # noqa: E402
from due_crew.planner import remote as PR  # noqa: E402
from due_crew.planner.draft import Draft  # noqa: E402
from due_crew.planner.webface import WebFace  # noqa: E402
from due_crew.planner.webpage import colors, page_html  # noqa: E402

TODAY = datetime.date.today()
MON = TODAY - datetime.timedelta(days=TODAY.weekday())


def day(n):
    return (MON + datetime.timedelta(days=n)).isoformat()


for uid, name in (("sam", "Sammy"), ("maya", "Maya"), ("dre", "Dre")):
    STORE.add_user(uid, name, code=uid.upper()[:3] + "123")
STORE.befriend("sam", "maya")
STORE.befriend("maya", "sam")


def client(uid):
    c = api.ApiClient(os.path.join(os.environ.get("TMPDIR", "/tmp"), f"dc-plan-preview-{uid}.json"))
    c.session = {"user_id": uid, "token": STORE.session_for(uid), "display_name": uid.title(),
                 "last_ok": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    return c


def collection():
    """A big shared deck's shape, small: a resource's numbered chapters with their parts, a video series, a bank, high-yield tags."""
    import sqlite3
    conn = sqlite3.connect(":memory:")
    fakes.make_collection(conn)
    root = "#Big_Step_1"
    chapters = [("01_Cell_injury", ["Adaptations", "Injury", "Cell_death"]), ("02_Inflammation", ["Acute", "Chronic", "Mediators"]),
                ("03_Neoplasia", ["Nomenclature", "Progression", "Carcinogenesis"]), ("04_Hemostasis", ["Platelets", "Coagulation"]),
                ("05_Red_cell_disorders", ["Microcytic", "Hemolytic", "Macrocytic"]), ("06_White_cell_disorders", ["Leukemias", "Lymphomas"])]
    cid = 0
    for ci, (ch, parts) in enumerate(chapters):
        for pi, part in enumerate(parts):
            for i in range(9 + 3 * pi + ci):
                cid += 1
                seen = ci < 2 and i % 2 == 0
                tags = f"{root}::#Path_Book::{ch}::{part}" + (f" {root}::^High_Yield" if i % 3 != 2 else "")
                fakes.add_card(conn, cid, 1, ctype=2 if seen else 0, queue=2 if seen else -1, ivl=9 if seen else 0, tags=tags)
        for i in range(2):
            cid += 1
            fakes.add_card(conn, cid, 1, queue=-1, tags=f"{root}::#Path_Book::{ch}")  # the chapter's own: its "the rest"
    for sys_, n in (("Heme::Anemia", 18), ("Heme::Coagulation", 12), ("Cardio::Heart_Failure", 14)):
        for i in range(n):
            cid += 1
            fakes.add_card(conn, cid, 1, queue=-1, tags=f"{root}::#Video_Series::{sys_} {root}::^Systems::{sys_.split('::')[0]}")
    for q in range(10230, 10250):
        cid += 1
        fakes.add_card(conn, cid, 1, queue=-1, tags=f"{root}::#Bank::{q} {root}::^Systems::Heme")
    col = fakes.FakeCol(conn, fakes.day_cutoff_for(TODAY))
    col.decks = fakes.FakeDecks({1: "Big Step 1"})
    return col


COL = collection()
R = "#Big_Step_1::#Path_Book"
UNITS = [
    {"id": "u1", "name": "Cell injury", "opens": day(-7), "tags": [f"{R}::01_Cell_injury"]},
    {"id": "u2", "name": "Inflammation", "opens": day(-6), "due": day(-5), "even": True, "tags": [f"{R}::02_Inflammation"],
     "todo": [{"k": "read", "t": "Chapter 2"}]},
    {"id": "u3", "name": "Neoplasia", "opens": day(0), "tags": [f"{R}::03_Neoplasia"], "for": "e1"},
    {"id": "u4", "name": "Hemostasis", "opens": day(1), "due": day(2), "even": True, "tags": [f"{R}::04_Hemostasis",
                                                                                              "#Big_Step_1::#Video_Series::Heme::Coagulation"]},
    {"id": "u5", "name": "Red cell disorders", "opens": day(3), "tags": [f"{R}::05_Red_cell_disorders", "#Big_Step_1::#Bank::10234"]},
    {"id": "u6", "name": "White cell disorders", "opens": day(7), "due": day(8), "tags": []},
]
PID, CODE = STORE.add_plan("sam", "Path Book, high yield", "Big Step 1", UNITS)
STORE.plans[PID]["doc"]["events"] = [{"id": "e1", "day": day(4), "name": "Heme quiz"}, {"id": "e2", "day": day(11), "name": "Exam"}]
STORE.plans[PID]["doc"]["pace"] = {"mode": "daily", "days": [1, 1, 1, 1, 1, 0, 0], "daily": 40}
next(u for u in STORE.plans[PID]["doc"]["units"] if u["id"] == "u3")["for"] = "e1"
STORE.plans[PID]["doc"]["remarks"] = [{"id": "r1", "tag": f"{R}::05_Red_cell_disorders::Hemolytic", "text": "Start from the smear."}]
# a class plan Sam follows
PID2, CODE2 = STORE.add_plan("dre", "MS2 Block 2", "Big Step 1", [
    {"id": "c1", "name": "Anemias I", "opens": day(-3), "tags": ["#Big_Step_1::#Video_Series::Heme::Anemia"]},
    {"id": "c2", "name": "Hemolysis", "opens": day(0), "tags": [f"{R}::05_Red_cell_disorders::Hemolytic"],
     "todo": [{"k": "watch", "t": "Lecture 16"}]},
    {"id": "c3", "name": "Leukemias", "opens": day(4), "tags": [f"{R}::06_White_cell_disorders::Leukemias"]}])
STORE.plans[PID2]["doc"]["events"] = [{"id": "q1", "day": day(5), "name": "Heme quiz"}]
SAM = client("sam")
SAM.follow_plan(CODE2)


class Ops:
    """What the window asks of the add-on, on this preview's collection and client, at once."""
    drafts = {}

    def __init__(self, cl):
        self.cl = cl

    def today(self):
        return TODAY.isoformat()

    def context(self, plan, doc):
        return P.DeckIndex(COL, 1), None, "named"

    def my_doc(self, plan):
        return plan["doc"]

    def followed_here(self, pid, version=None):
        return False

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

    def me(self):
        return self.cl.user_id

    def my_squads(self):
        return []

    def site_url(self, path):
        return "https://duecrew.com" + path

    def top_decks(self):
        return [(1, "Big Step 1", COL.db.scalar("SELECT count() FROM cards")), (2, "Spanish", 1840)]

    def index(self, did):
        return P.DeckIndex(COL, did) if did == 1 else None

    def __getattr__(self, name):
        return lambda *a, **k: None


class Face(WebFace):
    """The window's face with no window: what it would run on the page, kept."""

    def __init__(self, plans, cl, select=None, tab=None):
        self.sent_js = []
        self.web_init(COL, plans, Ops(cl), select, tab, {"theme": "auto", "accent": "green"})
        self._ready = True
        if self.pid:
            self.load(self.pid)

    def eval_js(self, js):
        self.sent_js.append(js)

    def copy(self, text):
        self.copied = text


def page(face, name, out, js=""):
    html = page_html(face.view(), colors(face.cfg), preview=True)
    head = ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>{name}</title>")
    with open(os.path.join(out, name + ".html"), "w", encoding="utf-8") as f:
        f.write(head + html + (f"<script>{js}</script>" if js else ""))


def main(out):
    os.makedirs(out, exist_ok=True)
    mine = PR.my_plans(SAM)
    author = Face(mine, SAM, select=PID)
    page(author, "author-list", out)
    page(author, "author-week", out, "dcPlan.set({mode:'week'})")
    page(author, "author-month", out, "dcPlan.set({mode:'month'})")
    author._on_cmd("dcplan:" + json.dumps({"c": "deck", "a": {"uid": "u5"}}))
    page(author, "author-deck", out)
    author._on_cmd("dcplan:" + json.dumps({"c": "deck_done", "a": {}}))
    author._on_cmd("dcplan:" + json.dumps({"c": "deck", "a": {}}))
    page(author, "author-layout", out)
    author._on_cmd("dcplan:" + json.dumps({"c": "deck_done", "a": {}}))
    author._on_cmd("dcplan:" + json.dumps({"c": "pick", "a": {"key": ["event", "e1"]}}))
    page(author, "author-event", out)
    author._on_cmd("dcplan:" + json.dumps({"c": "new_date_form", "a": {}}))
    page(author, "author-sheet", out, "dcPlan.sheet(" + author.sent_js[-1][len("dcPlan.sheet("):-1] + ")")
    follower = Face(mine, SAM, select=PID2)
    page(follower, "follower", out)
    page(follower, "follower-month", out, "dcPlan.set({mode:'month'})")
    fresh = Face(mine, SAM, select=PID)
    fresh._on_cmd("dcplan:" + json.dumps({"c": "new_plan", "a": {}}))
    page(fresh, "new-pick", out)
    for step in ("empty", "someone", "resource"):
        fresh._on_cmd("dcplan:" + json.dumps({"c": "new_step", "a": {"step": step}}))
        page(fresh, "new-" + step, out)
    fresh._on_cmd("dcplan:" + json.dumps({"c": "new_set", "a": {"key": "pace", "value": "by"}}))
    page(fresh, "new-resource-by", out)
    print("wrote", out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "tools", "plan_preview"))
