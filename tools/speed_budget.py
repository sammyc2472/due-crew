"""The speed budget (3.9.9; the review's mock 4): what a person waits on,
timed on Anki's own engine with a big collection (tools/speed/make_big.py:
30,000 notes, a million answers), each against a budget. Over a budget
marked "fail" is exit 1, as a failing test is; one marked "warn" is said
and passes (a known wait not met yet, red once it is).

    pip install "anki==25.02.7"
    python3 tools/speed_budget.py [--keep DIR]

The first card after Study and CPU at rest are the robot click-test's
(tools/click_test.py): they need Anki's windows. Budgets leave room for a
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

    print(f"\nspeed budget · {col.db.scalar('SELECT count() FROM notes'):,} notes, "
          f"{col.db.scalar('SELECT count() FROM revlog'):,} answers\n")
    print(f"{'wait':<52}{'budget':>9}{'this run':>11}")
    failed = warned = 0
    for name, budget, kind in BUDGETS:
        ms = got[name]
        over = ms > budget
        failed += over and kind == "fail"
        warned += over and kind == "warn"
        print(f"{name:<52}{budget:>6} ms{ms:>8.0f} ms  {'ok' if not over else 'OVER' if kind == 'fail' else 'over (warn)'}")
    print(f"\n{failed} over budget, {warned} known and warned")
    return 1 if failed else 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)  # (Anki's backend threads: leave without waiting on them)
