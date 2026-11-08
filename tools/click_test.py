#!/usr/bin/env python3
"""The robot click-test: real Anki, headless, with Due Crew from this repo,
signed in to the suite's fake server (tests/fakes.FakeWorker, in this
process). It goes through the add-on the way the manual click-test does
(docs/manual-anki-checklist.md): every view and tab, every window over the
board, every control on screen pressed with a real DOM click, a deck
studied, a plan made and sent, then a minute at rest on the Decks screen.

It fails when a control's press reaches no handler, anything raises, the
first card takes too long to show, or the board burns CPU at rest.

    QT_QPA_PLATFORM=offscreen QTWEBENGINE_DISABLE_SANDBOX=1 \\
    QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox --disable-gpu" \\
        <python with aqt 25.02.7> tools/click_test.py [--out click-test] [--quick]

It writes OUT/report.json, OUT/summary.txt and OUT/shots/*.png. Exit 0
when every check passed, 1 when one failed, 2 when the robot itself broke.
Nothing reaches the network: the add-on's requests go to the fake, and any
other connection is refused (and listed in the report)."""

import argparse
import os
import shutil
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from click_test.probe import Probe  # noqa: E402
from click_test.world import World  # noqa: E402

PROFILE = "User 1"


def make_base(base):
    """A fresh Anki folder: the profile's collection (made here) and the add-on, copied from due_crew/."""
    from click_test import collection
    prof = os.path.join(base, PROFILE)
    os.makedirs(prof, exist_ok=True)
    info = collection.build(os.path.join(prof, "collection.anki2"))
    dest = os.path.join(base, "addons21", "due_crew")
    if os.path.exists(dest):
        shutil.rmtree(dest)
    shutil.copytree(os.path.join(REPO, "due_crew"), dest,
                    ignore=shutil.ignore_patterns("user_files", "__pycache__", "*.pyc", ".DS_Store"))
    return info


def parse():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default="click-test", help="where the report and screenshots go")
    ap.add_argument("--base", help="the Anki folder to use (default: a new temporary one)")
    ap.add_argument("--quick", action="store_true", help="a few presses a view and 30 s at rest (a dry run)")
    ap.add_argument("--rest", type=float, default=None, help="seconds to measure CPU at rest (default 60)")
    ap.add_argument("--only", default="", help="comma-separated parts to run after boot "
                                               "(plans,due,windows,views,bars,study,energy)")
    ap.add_argument("--views", default="", help="comma-separated words: only the views whose names hold one")
    ap.add_argument("--limit", type=float, default=540, help="give up after this many seconds")
    return ap.parse_args()


def main():
    args = parse()
    out = os.path.abspath(args.out)
    os.makedirs(os.path.join(out, "shots"), exist_ok=True)
    base = os.path.abspath(args.base) if args.base else tempfile.mkdtemp(prefix="dc-click-")
    t0 = time.time()
    built = make_base(base)
    probe = Probe()
    probe.guard_network()
    world = World(REPO)
    import aqt
    import aqt.profiles
    from aqt import gui_hooks
    from aqt.qt import QTimer
    probe.patch_anki()
    # the first run's language window: English, asked of nobody
    aqt.profiles.ProfileManager.setDefaultLang = lambda pm, idx: pm.setLang("en_US")

    from click_test import report, steps
    run = steps.Run(probe, world, out, args, built)
    code = {"exit": 2}

    def finished(result):
        code["exit"] = report.write(out, run, probe, world, result, time.time() - t0)

        def stuck():
            time.sleep(60)
            os._exit(code["exit"])  # Anki didn't close in a minute: the report is written, the verdict stands
        threading.Thread(target=stuck, daemon=True).start()
        aqt.mw.unloadProfileAndExit()

    def watchdog():
        time.sleep(args.limit)
        try:
            report.write(out, run, probe, world, {"crash": f"gave up after {args.limit:g} s at: {probe.step}"},
                         time.time() - t0)
        finally:
            os._exit(2)
    threading.Thread(target=watchdog, daemon=True).start()

    def on_init():
        import due_crew
        from anki.buildinfo import version as anki_version
        from aqt.qt import PYQT_VERSION_STR, qVersion
        built["versions"] = {"anki": anki_version, "qt": qVersion(), "pyqt": PYQT_VERSION_STR,
                             "python": sys.version.split()[0], "due_crew": due_crew.app.ADDON_VERSION}
        probe.watch_addon(due_crew)
        probe.watch_plan_window()
        aqt.mw.resize(1280, 900)
        QTimer.singleShot(0, lambda: run.start(finished))

    def on_profile():
        import due_crew
        world.sign_in(due_crew)
        world.songs_offline(due_crew)
        from click_test.world import anki_days
        world.seed(anki_days(aqt.mw.col))

    gui_hooks.profile_did_open.append(on_profile)  # before the add-on's own (it loads later): it reads the session
    gui_hooks.main_window_did_init.append(on_init)
    sys.argv = ["anki", "-b", base, "-p", PROFILE]
    try:
        aqt.run()
    finally:
        sys.stdout.flush()
        if not args.base:
            shutil.rmtree(base, ignore_errors=True)
        os._exit(code["exit"])


if __name__ == "__main__":
    main()
