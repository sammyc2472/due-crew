"""The speed budget (3.9.9; the review's mock 4): what a person waits on,
timed on Anki's own engine with a big collection (tools/speed/make_big.py:
30,000 notes, a million answers), each against a budget. Over a budget
marked "fail" is exit 1, as a failing test is; one marked "warn" is said
and passes (a known wait not met yet, red once it is).

    pip install "anki==25.02.7"
    python3 tools/speed_budget.py [--keep DIR]

The first card after Study, the board's first draw and CPU at rest are the
robot click-test's (tools/click_test.py): they need Anki's windows. Budgets leave room for a
CI runner: about three times what a laptop measures."""
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tests"))

# (name, budget ms, "fail" or "warn")
BUDGETS = (
    ("a sync's gathering, the day's first", 800, "fail"),
    ("a sync's gathering, later the same day", 150, "fail"),
    ("Insights, first open of the day", 1500, "warn"),
    ("Insights, again within ten minutes", 20, "fail"),
    ("Insights, after ten minutes, nothing changed", 100, "fail"),
    ("Pip Party tab, first open (Tags)", 2500, "fail"),
    ("Pip Party tab, after ten minutes, nothing changed", 300, "fail"),
    ("Schedule ahead: which cards are open (2,000)", 150, "fail"),
    # 3.9.9, the waits nobody was timing
    ("Insights, the longest Anki is held while it's worked out", 2000, "fail"),
    ("Insights' deck picker, first read", 200, "fail"),
    ("a deck read for a plan or Magic search", 2000, "fail"),
    ("a plan's progress, read after a change (30 sets)", 800, "fail"),
    ("the morning: a plan's sets opened", 1200, "fail"),
    ("the week across plans, worked out", 50, "fail"),
    ("my pace, read once a day", 150, "fail"),
    ("reviews due by day, nine weeks", 150, "fail"),
)


def main():
    keep = sys.argv[sys.argv.index("--keep") + 1] if "--keep" in sys.argv else None
    work = keep or tempfile.mkdtemp(prefix="dc-speed-")
    os.makedirs(work, exist_ok=True)
    path = os.path.join(work, "big.anki2")
    if not os.path.exists(path):
        t = time.perf_counter()
        subprocess.run([sys.executable, os.path.join(HERE, "speed", "make_big.py"), path], check=True, stdout=subprocess.DEVNULL)
        print(f"big collection made in {time.perf_counter() - t:.0f} s")

    from anki.collection import Collection
    import fakes
    fakes.install_fake_requests(fakes.FakeWorker())
    aqt = fakes.install_fake_aqt()
    col = Collection(path)
    aqt.mw.col = col
    from due_crew import app, gamenight_flow as GF, magic_flow as MF, team_flow as TF
    from due_crew.app import _state
    from due_crew.stats import gather_stats, queries as Q
    app._bg = lambda job, done=None: None
    GF._bg = lambda job, done=None: None
    GF._soon = lambda fn, ms=40: fn()
    GF._redraw = lambda: None
    root = int(col.decks.id_for_name("Big Step 1"))
    got = {}

    def timed(name, fn):
        t = time.perf_counter()
        fn()
        got[name] = (time.perf_counter() - t) * 1000

    def age(sec=700):
        for d in (_state.get("insights") or {}).values():
            d["at"] -= sec
        if _state.get("you_decks"):
            _state["you_decks"]["at"] -= sec
        for k in ("corpus", "warmed"):
            v = GF.TAB.get(k)
            if v:
                GF.TAB[k] = tuple(x - sec if i == 1 else x for i, x in enumerate(v))

    files = tempfile.mkdtemp(prefix="dc-speed-files-")
    Q._FRESH.update(key=None, days=0, rows={})
    timed(BUDGETS[0][0], lambda: gather_stats(col, files))
    timed(BUDGETS[1][0], lambda: gather_stats(col, files))
    timed(BUDGETS[2][0], lambda: TF.insights(root))
    timed(BUDGETS[3][0], lambda: TF.insights(root))
    age()
    timed(BUDGETS[4][0], lambda: TF.insights(root))

    def party():
        if GF.tab_view({}).get("loading"):
            GF.tab_view({})
    GF._state()
    GF.TAB["by"] = "tag"
    timed(BUDGETS[5][0], party)
    age()
    timed(BUDGETS[6][0], party)
    cids = col.db.list("SELECT id FROM cards WHERE queue IN (0, 2) LIMIT 2000")
    timed(BUDGETS[7][0], lambda: MF.Ops().open_kinds(cids))

    def longest_hold():
        g, worst = TF._work_steps(root, None, ""), 0.0
        while True:
            t = time.perf_counter()
            try:
                next(g)
            except StopIteration:
                return max(worst, time.perf_counter() - t)
            worst = max(worst, time.perf_counter() - t)
    _state["insights"] = {}
    got[BUDGETS[8][0]] = longest_hold() * 1000
    _state.pop("you_decks", None)
    timed(BUDGETS[9][0], TF.you_decks)

    # a plan followed on the big deck: thirty sets by its own tags, a week of them due by today
    import datetime
    import types
    from due_crew import plans as P, plan_flow as F
    box = {}
    timed(BUDGETS[10][0], lambda: box.update(idx=P.DeckIndex(col, root), tree=None) or box.update(tree=box["idx"].tree()))
    idx, tags = box["idx"], box["tree"][0]
    picks = [t for t, n in sorted(tags, key=lambda x: -x[1]) if 40 <= n <= 400][:30]
    day = lambda n: str(datetime.date.today() + datetime.timedelta(days=n))  # noqa: E731
    units = [{"id": f"s{i}", "name": f"Set {i}", "opens": day(i - 7), "tags": [t], "decks": [], "cards": []}
             for i, t in enumerate(picks)]
    plan = {"id": "pS", "name": "Speed", "doc": {"deck": "Big Step 1", "units": units}}
    every = sorted(set().union(*(idx.match(u, None, "Big Step 1") for u in units)))
    col.sched.schedule_cards_as_new(every)
    col.sched.suspend_cards(every)
    pstore = {"plans": {"pS": F.new_state(col, plan, root)}, "plans_day": day(-1)}
    F._pcfg, F._psave = (lambda: pstore), (lambda d: None)
    F.followed = lambda: [F.mine(plan)]
    F.client = lambda: types.SimpleNamespace(signed_in=True, session={})
    F._today = lambda: day(0)
    F.tooltip = lambda *a, **k: None
    F.app.swap = lambda *a, **k: None
    F.mw.undo = col.undo
    F._last.update(key=None, got=None)
    timed(BUDGETS[11][0], F.refresh_progress)
    opened = {}
    timed(BUDGETS[12][0], lambda: opened.update(n=F.maybe_morning(False)))
    F._last.update(key=None, got=None)
    F.refresh_progress()
    timed(BUDGETS[13][0], lambda: F.load_view(F.followed(), F._state_cfg(), day(0)))
    timed(BUDGETS[14][0], lambda: MF.Ops().pace())
    timed(BUDGETS[15][0], lambda: F.reviews_by_day(col, day(0)))
    left = col.db.scalar(f"SELECT count() FROM cards WHERE queue = -1 AND id IN ({','.join(map(str, every))})")
    print(f"the plan: {len(units)} sets, {len(every):,} cards; the morning opened {len(every) - left:,}")
    if len(units) < 10 or left == len(every):
        print("the plan's setup opened nothing: its lines measured nothing")
        return 1

    print(f"\nspeed budget · {col.db.scalar('SELECT count() FROM notes'):,} notes, "
          f"{col.db.scalar('SELECT count() FROM revlog'):,} answers\n")
    print(f"{'wait':<58}{'budget':>9}{'this run':>11}")
    failed = warned = 0
    for name, budget, kind in BUDGETS:
        ms = got[name]
        over = ms > budget
        failed += over and kind == "fail"
        warned += over and kind == "warn"
        print(f"{name:<58}{budget:>6} ms{ms:>8.0f} ms  {'ok' if not over else 'OVER' if kind == 'fail' else 'over (warn)'}")
    print(f"\n{failed} over budget, {warned} known and warned")
    return 1 if failed else 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)  # (Anki's backend threads: leave without waiting on them)
