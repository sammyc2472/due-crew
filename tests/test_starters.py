"""3.9.5, starter plans: the few plans the admin marks in the library, offered
on the board's Plans tab to someone who owns and follows no plan, each with
Use it (a copy of my own, starting today, in Your plans). Against the fake
Worker (tests/fakes.py) and fake aqt; standard library only.

Run: python3 tests/test_starters.py
"""

import datetime
import json
import os
import re
import sys
import tempfile

HARNESS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HARNESS)
sys.path.insert(0, HARNESS)

import fakes  # noqa: E402

STORE = fakes.FakeWorker()
fakes.install_fake_requests(STORE)
fakes.install_fake_aqt()
sys.path.insert(0, REPO)

from due_crew import app, board, plan_flow                  # noqa: E402
from due_crew.backend import api, shapes                      # noqa: E402

CHECKS = []
TODAY = datetime.date(2026, 10, 26)
LABELS = [(TODAY - datetime.timedelta(days=i)).isoformat() for i in range(7)]
TOMORROW = (TODAY + datetime.timedelta(days=1)).isoformat()
UNITS = [{"id": "hf", "name": "Heart failure", "opens": "2026-10-05", "due": "2026-10-07", "tags": ["Step1::Cardio::HF"], "decks": [], "n": 120},
         {"id": "arr", "name": "Arrhythmia", "opens": "2026-10-26", "tags": ["Step1::Cardio::Arr"], "decks": [], "n": 80}]


def check(name, cond, detail=""):
    CHECKS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond or detail == "" else f"\n     {detail}"))


def world(users):
    store = fakes.FakeWorker()
    sys.modules["requests"].Session = lambda: fakes.FakeSession(store)
    for uid, name in users.items():
        store.add_user(uid, name)
    return store


def new_client(store, uid):
    cl = api.ApiClient(os.path.join(tempfile.mkdtemp(), "session.json"))
    cl.session = {"user_id": uid, "token": store.session_for(uid), "email": f"{uid}@example.com", "display_name": uid}
    return cl


def as_board(message):
    """A message as the Decks page sends it (3.9.1): with the board's key."""
    return message + "|" + board.BOARD_KEY


def starters_world(n=5):
    """Sam (the admin) lists n plans and marks each a starter, newest last;
    Maya has no plan. (store, sam, maya, [plan ids])."""
    store = world({"sam": "Sam Caplan", "maya": "Maya", "kai": "Kai", "dre": "Dre"})
    store.admins.add("sam")
    sam, maya = new_client(store, "sam"), new_client(store, "maya")
    pids = []
    for i in range(1, n + 1):
        pid, _code = store.add_plan("sam", f"Starter {i}", "Big Step 1", json.loads(json.dumps(UNITS)))
        store.plans[pid]["line"] = "the videos, a chapter a day" if i == 1 else ""
        status, _ = sam._call("PUT", f"/plans/{pid}/listed", {"listed": True})
        status2, _ = sam._call("POST", f"/admin/library/{pid}/starter", {"on": True})
        assert status == 200 and status2 == 200, (status, status2)
        pids.append(pid)
    return store, sam, maya, pids


# ---- the payload: on the day's first board, only with no plans ----

def test_payload_rides_the_board_only_with_no_plans():
    store, sam, maya, pids = starters_world(5)
    n = len(store.log)
    maya.fetch_board(LABELS, TOMORROW, with_decks=True)
    got = maya.session.get("plan_starters")
    check("payload: the day's first refresh is still one request", len(store.log) - n == 1, store.log[n:])
    check("payload: four starters at most, newest listed first, as the board needs them",
          [s["name"] for s in got] == ["Starter 5", "Starter 4", "Starter 3", "Starter 2"]
          and got[3] == {"id": pids[1], "name": "Starter 2", "deck": "Big Step 1", "days": 22, "perDay": 9, "line": ""}, got)
    check("payload: kept in the session, for the Plans tab (no request to show them)",
          json.load(open(maya.session_file)).get("plan_starters") == got)
    body = maya.fetch_board(LABELS, TOMORROW)
    check("payload: a later refresh carries none and leaves the kept ones alone",
          maya.session.get("plan_starters") == got and "plan_starters" not in body
          and store.log[-1] == ("GET", "/board", 200), store.log[-1])
    # following a plan: none
    kai = new_client(store, "kai")
    kai._call("POST", "/plans/follow", {"code": store.plans[pids[0]]["code"]})
    kai.session["plan_starters"] = [{"id": "old"}]
    kai.fetch_board(LABELS, TOMORROW, with_decks=True)
    check("payload: following a plan, none (and the kept ones go)", kai.session.get("plan_starters") == [], kai.session.get("plan_starters"))
    # owning one: none
    store.add_plan("dre", "Dre's", "Big Step 1", json.loads(json.dumps(UNITS)))
    dre = new_client(store, "dre")
    dre.fetch_board(LABELS, TOMORROW, with_decks=True)
    check("payload: owning a plan, none", not dre.session.get("plan_starters"), dre.session.get("plan_starters"))
    sam.fetch_board(LABELS, TOMORROW, with_decks=True)
    check("payload: the admin who wrote them owns plans: none", not sam.session.get("plan_starters"))


def test_clean_starters():
    raw = [{"id": "abc123", "name": "A <b>chapter</b>\na day", "deck": "Big Step 1", "days": 42, "perDay": 40, "line": "x" * 300, "code": "SECRET1"},
           {"id": "abc123", "name": "again"},                      # the same one twice
           {"id": "Bad Id!", "name": "x"}, {"id": 7, "name": "x"}, "nope", None,
           {"id": "d2", "name": "", "deck": None, "days": -3, "perDay": "9", "line": 5},
           {"id": "d3"}, {"id": "d4"}, {"id": "d5"}]
    got = shapes.clean_starters(raw)
    check("clean: good ids only, once each, four at most",
          [s["id"] for s in got] == ["abc123", "d2", "d3", "d4"], got)
    check("clean: one line each, clipped; numbers whole and not below 0; nothing else kept",
          got[0] == {"id": "abc123", "name": "A <b>chapter</b> a day", "deck": "Big Step 1", "days": 42, "perDay": 40, "line": "x" * 120}
          and got[1] == {"id": "d2", "name": "Plan", "deck": "", "days": 0, "perDay": 0, "line": ""}, got[:2])
    check("clean: anything not a list is none", shapes.clean_starters(None) == [] and shapes.clean_starters({"id": "a"}) == [])


# ---- the fake's mirror of the Worker (worker/test/starters.test.ts) ----

def test_fake_mirrors_the_worker():
    store, sam, maya, pids = starters_world(3)
    dre = new_client(store, "dre")
    plain, _ = store.add_plan("dre", "Dre's own block", "Big Step 1", json.loads(json.dumps(UNITS)))
    dre._call("PUT", f"/plans/{plain}/listed", {"listed": True})
    status, body = dre._call("POST", f"/admin/library/{plain}/starter", {"on": True})
    check("fake: only the admin marks one (as if there were no route)", (status, body.get("error")) == (404, "not_found"))
    quiet, _ = store.add_plan("dre", "Not listed", "Big Step 1", json.loads(json.dumps(UNITS)))
    status, body = sam._call("POST", f"/admin/library/{quiet}/starter", {"on": True})
    check("fake: only a listed plan", (status, body.get("error")) == (409, "not_listed"))
    check("fake: a plain body", sam._call("POST", f"/admin/library/{plain}/starter", {"on": "yes"})[0] == 400)
    status, lib = maya._call("GET", "/library")
    check("fake: the library's starters apart, newest first, under Due Crew; the grid leaves them out",
          [(s["name"], s["ownerName"], s.get("starter")) for s in lib["starters"]]
          == [("Starter 3", "Due Crew", True), ("Starter 2", "Due Crew", True), ("Starter 1", "Due Crew", True)]
          and [p["name"] for p in lib["plans"]] == ["Dre's own block"] and "starter" not in lib["plans"][0], lib)
    _s, deck = maya._call("GET", "/library?deck=Big%20Step%201")
    check("fake: a filter shows them in the grid, as starters; no row apart", "starters" not in deck
          and sorted(p["name"] for p in deck["plans"] if p.get("starter")) == ["Starter 1", "Starter 2", "Starter 3"], deck)
    check("fake: a later page has no row apart", "starters" not in maya._call("GET", "/library?page=1")[1])
    sam._call("PUT", f"/plans/{pids[0]}/listed", {"listed": False})
    sam._call("POST", f"/admin/library/{pids[1]}", {"note": "Not a study plan"})
    status, body = sam._call("POST", f"/admin/library/{pids[2]}/starter", {"on": False})
    check("fake: leaving the library ends it (the owner's switch, the admin's Take out); the admin unmarks one",
          not store.plans[pids[0]].get("starter") and not store.plans[pids[1]].get("starter") and not store.plans[pids[2]].get("starter")
          and (status, body) == (200, {"ok": True, "starter": False}) and maya._call("GET", "/library")[1]["starters"] == []
          and [a for a, _d in store.admin_log] == ["made a starter"] * 3 + ["took a starter off"])
    _s, cp = maya._call("POST", f"/plans/{pids[2]}/copy", {"start": "2027-01-04"})
    check("fake: a copy of what was a starter credits its owner again", cp.get("basedOn", {}).get("owner") == "Sam Caplan", cp.get("basedOn"))


# ---- the board: the empty Plans tab draws them, escaped ----

def test_empty_plans_tab_draws_them_escaped():
    starters = [{"id": "abc123", "name": "A <b>chapter</b> a day", "deck": "Big <Step> 1", "days": 42, "perDay": 40, "line": 'videos "first"'},
                {"id": "def456", "name": "Rapid review", "deck": "Big Step 1", "days": 30, "perDay": 220, "line": ""},
                {"id": "ghi789", "name": "One block", "deck": "", "days": 3, "perDay": 1, "line": ""},
                {"id": "Bad Id!", "name": "Skipped", "deck": "D", "days": 7}]
    html = board._plans_html({"cards": [], "offers": [], "starters": starters})
    check("tab: Follow a plan and its ways, then Or start from one under them",
          "Follow a plan" in html and "planlibrary" in html and html.index("Your plans&hellip;") < html.index("Or start from one"), html)
    check("tab: a row each, its name in bold, escaped; deck · N weeks under it, escaped",
          "<b title=\"videos &quot;first&quot;\">A &lt;b&gt;chapter&lt;/b&gt; a day</b><small>Big &lt;Step&gt; 1 &middot; 6 weeks</small>" in html
          and "<b>Rapid review</b><small>Big Step 1 &middot; 4 weeks</small>" in html
          and "<b>One block</b><small>1 week</small>" in html and "<b>A <b>" not in html, html)
    check("tab: Use it sends planstarter with the plan's id and the board's key; a bad id is no row",
          html.count(">Use it</a>") == 3 and f"duecrew:planstarter:abc123|{board.BOARD_KEY}" in html and "Skipped" not in html, html)
    check("tab: with none, the ways alone", "Or start from one" not in board._plans_html({"cards": [], "starters": []})
          and "Or start from one" not in board._plans_html({"cards": []}) and "Follow a plan" in board._plans_html({"cards": []}))
    card = {"id": "p1", "title": "Plan", "sub": "", "rows": [], "lines": [], "change": None, "no_deck": False, "paused": False,
            "week": [], "week_offset": 0, "session": {}}
    check("tab: following a plan, its card and no starters",
          "Or start from one" not in board._plans_html({"cards": [card], "starters": starters}))
    css = board._css({})
    check("tab: the new part reads left to right on the centred Decks screen",
          re.search(r"#due-crew \.dc-exs \{[^}]*text-align: left", css) is not None)
    you = board.you_html({}, None, {"tab": "plans", "plans": {"cards": [], "offers": [], "starters": starters}})
    check("tab: in the You bubble's Plans", "Or start from one" in you and "planstarter:def456" in you)


def test_board_view_hands_over_the_kept_starters():
    store, _sam, maya, pids = starters_world(2)
    maya.fetch_board(LABELS, TOMORROW, with_decks=True)
    saved = {k: getattr(plan_flow, k) for k in ("client", "cfg", "save_cfg", "_files", "_today")}
    files = tempfile.mkdtemp()
    plan_flow.client, plan_flow.cfg, plan_flow.save_cfg = (lambda: maya), (lambda: {}), (lambda c: None)
    plan_flow._files, plan_flow._today = (lambda: files), (lambda: TODAY.isoformat())
    try:
        app._state["labels"] = []
        early = plan_flow.board_view({})
        app._state["labels"] = list(LABELS)
        view = plan_flow.board_view({})
        html = board._plans_html(view)
    finally:
        for k, v in saved.items():
            setattr(plan_flow, k, v)
        app._state["labels"] = []
        if hasattr(plan_flow, "_store"):
            plan_flow._store.update(profile=None, data=None)
    check("view: the Plans tab's view carries the starters the board kept",
          [s["id"] for s in view["starters"]] == [pids[1], pids[0]] and early["starters"] == view["starters"] and view["cards"] == [], view)
    check("view: drawn from it, with no request", "Starter 2" in html and "Starter 1" in html
          and store.log[-1] == ("GET", "/board", 200), store.log[-1])


# ---- Use it: a copy of my own, starting today, then Your plans on it ----

class _Glue:
    """planner.flow's and plan_flow's glue pointed at a client, with the
    background run at once and what it opens and says recorded."""

    def __init__(self, cl):
        from due_crew.planner import flow
        self.flow, self.cl = flow, cl
        self.opened, self.toasts, self.swaps, self.refreshes = [], [], [], []

    def __enter__(self):
        f = self.flow
        self.saved = ({k: getattr(f, k) for k in ("client", "_bg", "tooltip", "open_plans", "cfg")},
                      {k: getattr(plan_flow, k) for k in ("_today", "open_follow")}, (app.swap, app.refresh, f.mw.col))
        self.follows = []
        plan_flow.open_follow = lambda code="": self.follows.append(code)
        f.client, f.cfg = (lambda: self.cl), (lambda: {})
        f._bg = lambda job, done=None: done(self._run(job))
        f.tooltip = lambda text, **kw: self.toasts.append(text)
        f.open_plans = lambda select=None, tab=None: self.opened.append(select)
        plan_flow._today = lambda: TODAY.isoformat()
        app.swap, app.refresh = (lambda c: self.swaps.append(True)), (lambda **kw: self.refreshes.append(kw))
        f.mw.col = object()
        return self

    @staticmethod
    def _run(job):
        """app._bg's rule: a failed request delivers None."""
        try:
            return job()
        except Exception:
            return None

    def __exit__(self, *exc):
        f = self.flow
        for k, v in self.saved[0].items():
            setattr(f, k, v)
        for k, v in self.saved[1].items():
            setattr(plan_flow, k, v)
        app.swap, app.refresh, f.mw.col = self.saved[2]
        return False


def _send(message):
    import due_crew as dc
    from aqt.deckbrowser import DeckBrowser
    return dc._on_js(False, as_board(message), DeckBrowser())


def test_use_it_copies_today_and_follows_it():
    store, _sam, maya, pids = starters_world(3)
    maya.fetch_board(LABELS, TOMORROW, with_decks=True)
    pid = pids[2]
    with _Glue(maya) as g:
        n = len(store.log)
        _send(f"duecrew:planstarter:{pid}")
        sent = store.log[n:]
        mine = [(i, p) for i, p in store.plans.items() if p["owner"] == "maya"]
    check("use it: through the board's _on_js, one request: the library's Copy",
          sent == [("POST", f"/plans/{pid}/copy", 200)], sent)
    body = next(b for m, r, b in reversed(store.bodies) if r == f"/plans/{pid}/copy")
    check("use it: its first date today's Anki day", body == {"start": TODAY.isoformat()}, body)
    check("use it: a plan of my own, its dates from today, crediting Due Crew",
          len(mine) == 1 and [u["opens"] for u in mine[0][1]["doc"]["units"]] == ["2026-10-26", "2026-11-16"]
          and mine[0][1]["basedOn"] == {"id": pid, "name": "Starter 3", "owner": "Due Crew"}, mine)
    check("use it: then Follow on my copy (its code, as the box opens one), the board drawn again and refreshed",
          g.follows == [mine[0][1]["code"]] and g.opened == [] and g.swaps and len(g.refreshes) == 1 and not g.toasts,
          (g.follows, g.opened, g.swaps, g.refreshes, g.toasts))
    check("use it: the starters go from the board (I own a plan now), kept so",
          maya.session.get("plan_starters") == [] and json.load(open(maya.session_file)).get("plan_starters") == [])
    maya.fetch_board(LABELS, TOMORROW, with_decks=True)
    check("use it: and the next day's first board agrees", maya.session.get("plan_starters") == [])


def test_use_it_failing_says_so():
    store, sam, maya, pids = starters_world(2)
    maya.fetch_board(LABELS, TOMORROW, with_decks=True)
    sam._call("POST", f"/admin/library/{pids[0]}", {"note": "Not a study plan"})  # taken out since this morning
    with _Glue(maya) as g:
        _send(f"duecrew:planstarter:{pids[0]}")
        refused = list(g.toasts)
        store.down = True
        _send(f"duecrew:planstarter:{pids[1]}")
        store.down = False
        offline = g.toasts[len(refused):]
        n = len(store.log)
        _send("duecrew:planstarter:notastarter")  # an id the board didn't offer
        _send("duecrew:planstarter:BAD")          # not an id
        quiet = store.log[n:]
        opened = list(g.opened)
    check("use it: refused, the board says so in its words, nothing opens",
          refused == ["That didn't copy. This plan was deleted."] and not opened and not g.follows, refused)
    check("use it: no answer, it says so", offline == ["Couldn't reach Due Crew. Check your connection."], offline)
    check("use it: only a starter the board offered; nothing sent otherwise", quiet == [], quiet)
    check("use it: a failure keeps the starters", [s["id"] for s in maya.session.get("plan_starters")] == [pids[1], pids[0]])
    # the answer comes after a sign-out or a profile switch: dropped
    with _Glue(maya) as g:
        g.flow._bg = lambda job, done=None: (job(), setattr(app, "generation", app.generation + 1), done(("saved", {"id": "x1"})))
        _send(f"duecrew:planstarter:{pids[1]}")
        check("use it: an answer for another profile or account is dropped",
              g.opened == [] and g.follows == [] and not g.refreshes, (g.opened, g.follows))


def test_the_command_has_a_handler():
    """As test_due_crew's test_every_board_command_has_a_handler scans it:
    the board emits planstarter, and plan_flow handles the name itself."""
    src = open(os.path.join(REPO, "due_crew", "board.py")).read()
    handled = open(os.path.join(REPO, "due_crew", "plan_flow.py")).read()
    check("command: the board emits planstarter, plan_flow handles it",
          "planstarter" in re.findall(r'_pycmd\(\s*f?["\']([a-z]+)', src) and 'cmd == "planstarter"' in handled)
    seen = []
    from due_crew.planner import flow
    saved = flow.use_starter
    flow.use_starter = lambda pid: seen.append(pid)
    try:
        _send("duecrew:planstarter:abc123")
        _send("duecrew:planstarter:")
    finally:
        flow.use_starter = saved
    check("command: through _on_js it reaches Use it with the id; none, nothing", seen == ["abc123"], seen)


def test_request_budget():
    """Showing starters costs nothing; the day's first refresh is still one
    request, a later one is one, and Use it is one on the click."""
    store, _sam, maya, pids = starters_world(4)
    count = lambda fn: (lambda n: (fn(), len(store.log) - n)[1])(len(store.log))
    check("budget: a refresh with starters is one request, without them one",
          count(lambda: maya.fetch_board(LABELS, TOMORROW, with_decks=True)) == 1
          and count(lambda: maya.fetch_board(LABELS, TOMORROW)) == 1)
    check("budget: drawing them is none",
          count(lambda: board._plans_html({"cards": [], "starters": maya.session["plan_starters"]})) == 0)
    with _Glue(maya):
        check("budget: Use it is one", count(lambda: _send(f"duecrew:planstarter:{pids[0]}")) == 1)


def main():
    names = [n for n in list(globals()) if n.startswith("test_")]
    for n in names:
        globals()[n]()
    bad = [c for c in CHECKS if not c[1]]
    print(f"\n{len(CHECKS) - len(bad)}/{len(CHECKS)} checks passed")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
