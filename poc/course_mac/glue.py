"""The add-on in Anki: its state, the menus, the Browse hook, the daily
open, and run_steps (the collection read and changed on the main thread
only; the model called off it, through mw.taskman, with timeouts)."""

import datetime as dt
import os
import time
import traceback

from aqt import gui_hooks, mw
from aqt.qt import QAction, QMenu, QTimer
from aqt.utils import tooltip

from . import course as C
from . import engine as E
from . import model as M
from . import store

ADDON = __name__.rsplit(".", 1)[0]
FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "user_files")


def run_steps(steps, on_done, on_error):
    """[(where, fn)]: "main" runs here (the main thread), "bg" in Anki's
    background pool; each starts when the one before has finished."""
    it = iter(steps)

    def step():
        while True:
            try:
                where, fn = next(it)
            except StopIteration:
                on_done()
                return
            if where == "main":
                try:
                    fn()
                except Exception as e:  # noqa: BLE001
                    on_error(e)
                    return
                continue

            def done(fut, fn=fn):
                try:
                    fut.result()
                except Exception as e:  # noqa: BLE001
                    on_error(e)
                    return
                step()
            mw.taskman.run_in_background(fn, done)
            return
    step()


class App:
    """The add-on's state: the profile's courses, the deck index, the model."""

    def __init__(self):
        self.data = {"courses": [], "current": 0}
        self.profile = None
        self.idx, self.idx_did = None, None
        self.states_at = 0.0
        self.lines = []
        self.runner = None
        self.busy = False
        self.cancel_flag = False
        self.window = None  # All the details (ui.CourseWindow)
        self.simple = None  # the window everyone sees first (simple.SimpleWindow)

    # ---- config, log, model ----

    def cfg(self):
        c = dict(E.DEFAULTS)
        c.update({"runner": "auto", "timeout": 90, "verbose_log": False, "fm_schema_flag": False})
        try:
            c.update(mw.addonManager.getConfig(ADDON) or {})
        except Exception:  # noqa: BLE001
            pass
        return c

    def save_cfg(self, c):
        mw.addonManager.writeConfig(ADDON, c)
        self.reset_runner()

    def log(self, line, detail=None):
        os.makedirs(FOLDER, exist_ok=True)
        M.Log(os.path.join(FOLDER, "log.txt"), self.cfg().get("verbose_log"), self.lines)(line, detail)
        if self.window:
            mw.taskman.run_on_main(self.window.show_log)

    def model(self):
        if self.runner is None:
            c = self.cfg()
            self.runner = M.pick_runner(c.get("runner", "auto"), FOLDER, self.log, float(c.get("timeout") or 90),
                                        bool(c.get("fm_schema_flag")))
        return self.runner

    def reset_runner(self):
        if self.runner:
            self.runner.close()
        self.runner = None

    # ---- courses ----

    def load(self):
        prof = getattr(mw.pm, "name", None) if mw.pm else None
        if prof != self.profile:
            self.profile = prof
            self.data = store.load(FOLDER, prof)
            self.idx = self.idx_did = None

    def save(self):
        if self.profile is not None:
            store.save(FOLDER, self.profile, self.data)

    def course(self):
        cs = self.data["courses"]
        if not cs:
            return None
        i = min(max(0, int(self.data.get("current") or 0)), len(cs) - 1)
        return cs[i]

    def index(self, fresh=False):
        """The current course's deck, read (main thread)."""
        c = self.course()
        if not c or not mw.col:
            return None
        if fresh or self.idx is None or self.idx_did != c["did"]:
            t0 = dt.datetime.now()
            self.idx = E.build_index(mw.col, c["did"])
            self.idx_did = c["did"]
            self.states_at = time.time()
            self.log(f"read the deck: {len(self.idx.guid):,} notes, {len(self.idx.card):,} cards "
                     f"in {(dt.datetime.now() - t0).total_seconds():.1f} s")
        elif time.time() - self.states_at > 1:
            # an undo, a review, another add-on: what's open now
            E.refresh_states(mw.col, self.idx, c["did"])
            self.states_at = time.time()
        return self.idx

    def mark_open(self, ids):
        """Opened cards are open in the index too, without reading it all again."""
        if self.idx:
            for c in ids:
                if c in self.idx.card:
                    n, o, _q, t = self.idx.card[c]
                    self.idx.card[c] = (n, o, 0, t)

    # ---- running lectures ----

    def run_lectures(self, lecs, on_each, on_end):
        """One lecture after another; on_each(lec) as each finishes."""
        c, idx = self.course(), self.index()
        if not c or idx is None or self.busy:
            on_end()
            return
        self.busy, self.cancel_flag = True, False
        runner, cfg = self.model(), self.cfg()
        todo = list(lecs)

        def next_one():
            if not todo or self.cancel_flag:
                self.busy = False
                self.save()
                on_end()
                return
            lec = todo.pop(0)
            run = E.LectureRun(c, lec, idx, runner, self.log, cfg, lambda: mw.col, lambda: self.cancel_flag)

            def done():
                self.save()
                on_each(lec)
                next_one()

            def failed(e):
                lec["state"] = "error"
                self.log(f"{lec['title']}: stopped: {e}", traceback.format_exc())
                self.save()
                on_each(lec)
                next_one()
            run_steps(run.steps(), done, failed)
        next_one()

    # ---- what a click changes ----

    def after_change(self):
        try:
            mw.update_undo_actions()
        except Exception:  # noqa: BLE001
            pass
        try:
            from anki.collection import OpChanges
            gui_hooks.operation_did_execute(OpChanges(card=True, note_text=True, tag=True, browser_table=True,
                                                      study_queues=True), None)
        except Exception:  # noqa: BLE001
            pass

    def open_cids(self, cids, label):
        if not mw.col:
            return 0
        ids = E.openable(mw.col, cids)
        n = E.open_cards(mw.col, ids, label, bool(self.cfg().get("first_in_line", True)))
        self.mark_open(ids)
        self.after_change()
        return n

    def auto_open(self):
        """The day's lectures, for a course set to open on its own: once a
        day, what's ticked on lectures whose date has come."""
        self.load()
        if not mw.col:
            return
        today = dt.date.today().isoformat()
        said = []
        was = self.data.get("current", 0)
        try:
            for i, c in enumerate(self.data["courses"]):
                if not c.get("auto_open"):
                    continue
                self.data["current"] = i
                idx = self.index()
                for lec in C.lectures(c):
                    if not C.studied(lec) or lec.get("state") != "done" or lec["date"] > today or lec.get("auto_done"):
                        continue
                    n = self.open_cids(C.lecture_cids(lec, idx), f"Course: {lec['title']}")
                    lec["auto_done"] = today
                    lec.setdefault("opened", []).append(today)
                    if n:
                        said.append(f"{lec['title']}: {n}")
        finally:
            self.data["current"] = was
        self.save()
        if said:
            tooltip("Course opened " + "; ".join(said[:3]) + (" …" if len(said) > 3 else ""), period=6000)


app = App()


def open_window():
    from . import simple
    app.load()
    if app.simple is None:
        app.simple = simple.SimpleWindow(app)
    else:
        app.simple.show_page()
    app.simple.show()
    app.simple.raise_()
    app.simple.activateWindow()


def open_measure():
    from . import ui
    app.load()
    ui.MeasureDialog(app, mw).show()


def open_settings():
    from . import ui
    ui.SettingsDialog(app, mw).exec()


def _sidebar_menu(sidebar, menu, item, index):
    try:
        from aqt.browser.sidebar.item import SidebarItemType
        if item is None or item.item_type != SidebarItemType.TAG:
            return
        tag = str(item.full_name or "")
    except Exception:  # noqa: BLE001
        return
    if not tag:
        return
    from . import ui
    parent = getattr(sidebar, "browser", None) or mw
    menu.addSeparator()
    menu.addAction("Course: what my course asks of this tag…").triggered.connect(
        lambda: (app.load(), ui.SplitDialog(app, parent, tag).show()))


def _setup_menu():
    m = QMenu("Course on a Mac (PoC)", mw)
    for text, fn in (("Open…", open_window), ("Measure against my plan's tags…", open_measure),
                     ("Settings…", open_settings)):
        a = QAction(text, mw)
        a.triggered.connect(fn)
        m.addAction(a)
    mw.form.menuTools.addMenu(m)


def _profile_open():
    app.profile = None
    app.load()
    QTimer.singleShot(15000, lambda: app.auto_open() if mw.col else None)


def _profile_close():
    app.cancel_flag = True
    app.reset_runner()
    for w in (app.window, app.simple):
        if w:
            w.close()
    app.window = app.simple = None
    app.profile = None


_setup_menu()
gui_hooks.profile_did_open.append(_profile_open)
gui_hooks.profile_will_close.append(_profile_close)
if hasattr(gui_hooks, "browser_sidebar_will_show_context_menu"):
    gui_hooks.browser_sidebar_will_show_context_menu.append(_sidebar_menu)
