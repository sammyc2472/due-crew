"""The course PoC's windows, built offscreen on real PyQt6 against Anki's
own engine (the test deck), driven through their buttons, and saved as
PNGs. Exits non-zero if a window fails to build or a click goes wrong.

    QT_QPA_PLATFORM=offscreen <venv with anki and PyQt6>/python poc/tests/render_course_mac.py OUT_DIR
"""
import concurrent.futures
import importlib
import os
import shutil
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
POC = os.path.dirname(HERE)
OUT = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp()
os.makedirs(OUT, exist_ok=True)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: E402

qapp = QtWidgets.QApplication([])

# ---- aqt on real Qt ----
qt = types.ModuleType("aqt.qt")
for mod in (QtCore, QtGui, QtWidgets):
    for name in dir(mod):
        if name.startswith("Q") or name == "Qt":
            setattr(qt, name, getattr(mod, name))
answers = {"question": QtWidgets.QMessageBox.StandardButton.Yes, "text": ("Block 2", True)}
qt.QMessageBox.question = staticmethod(lambda *a, **k: answers["question"])
qt.QInputDialog.getText = staticmethod(lambda *a, **k: answers["text"])

tips = []
browsed = []


class FakeBrowser:
    def search_for(self, q):
        browsed.append(q)


def run_in_background(fn, on_done=None, *a, **k):
    fut = concurrent.futures.Future()
    try:
        fut.set_result(fn())
    except Exception as e:  # noqa: BLE001
        fut.set_exception(e)
    if on_done:
        on_done(fut)


config = {}
mw = QtWidgets.QMainWindow()  # Anki's main window is a real one: menus and dialogs hang from it
mw.pm = types.SimpleNamespace(name="Test")
mw.col = None
mw.taskman = types.SimpleNamespace(run_in_background=run_in_background, run_on_main=lambda f: f())
mw.addonManager = types.SimpleNamespace(getConfig=lambda n: dict(config), writeConfig=lambda n, c: config.update(c))
mw.form = types.SimpleNamespace(menuTools=QtWidgets.QMenu())
mw.update_undo_actions = lambda: None
aqt = types.ModuleType("aqt")
aqt.mw = mw
aqt.dialogs = types.SimpleNamespace(open=lambda name, parent: FakeBrowser())
hooks = types.ModuleType("aqt.gui_hooks")
for h in ("profile_did_open", "profile_will_close", "browser_sidebar_will_show_context_menu"):
    setattr(hooks, h, [])
hooks.operation_did_execute = lambda *a: None
aqt.gui_hooks = hooks
utils = types.ModuleType("aqt.utils")
utils.tooltip = lambda msg, **k: tips.append(str(msg))
aqt.utils = utils
sys.modules.update({"aqt": aqt, "aqt.qt": qt, "aqt.gui_hooks": hooks, "aqt.utils": utils})

# ---- the add-on, as Anki loads it ----
addons = tempfile.mkdtemp()
shutil.copytree(os.path.join(POC, "course_mac"), os.path.join(addons, "course_mac_poc"),
                ignore=shutil.ignore_patterns("__pycache__", "user_files"))
sys.path.insert(0, addons)
sys.path.insert(0, HERE)
import course_mac_poc  # noqa: E402
from course_mac_poc import course as C, glue, ui  # noqa: E402

# the tests import the package as course_mac: one copy of each module, so their errors are the add-on's
sys.modules["course_mac"] = course_mac_poc
for _m in ("cal", "course", "engine", "find", "jobs", "model", "store"):
    sys.modules[f"course_mac.{_m}"] = importlib.import_module(f"course_mac_poc.{_m}")
import test_course_mac as T  # noqa: E402

assert hooks.profile_did_open and hooks.browser_sidebar_will_show_context_menu, "hooks not added"
assert any(a.text() == "Course on a Mac (PoC)" for a in mw.form.menuTools.actions()), "no menu"

t = T.EngineTests("test_index")
t.setUp()
mw.col = t.col
app = glue.app
app.load()
app.data = {"courses": [C.new_course("Block 2", t.did, "Big Step 1")], "current": 0}
app.runner = t.scripted()
fails = []


def check(cond, what):
    if not cond:
        fails.append(what)
        print("FAIL", what)


def shot(w, name, size=None):
    if size:
        w.resize(*size)
    w.show()
    qapp.processEvents()
    w.grab().save(os.path.join(OUT, name + ".png"))


# the course window, its calendar
win = ui.CourseWindow(app)
app.window = win
shot(win, "1-empty", (1180, 780))
cal_d = ui.CalendarDialog(app, win)
cal_d.text.setPlainText(T.CALENDAR)
cal_d.read(True)  # the scripted runner has no calendar job: it falls back to lines, piece by piece
check(len(cal_d.found) == 3, f"calendar sessions: {len(cal_d.found)} ({cal_d.state.text()})")
shot(cal_d, "2-calendar", (900, 680))
cal_d.take()
win_cal = cal_d.picked
c = app.course()
for s in win_cal:
    c["lectures"].append(C.new_lecture(s["date"], s["title"], s["kind"], s["objectives"]))
win.fill_list()
check(win.list.count() == 3, f"lectures listed: {win.list.count()}")

# read every lecture with the scripted model
win.read_all()
hf = next(l for l in c["lectures"] if l["title"] == "Heart failure")
check(hf["state"] == "done" and hf["rows"], "Heart failure read")
for i in range(win.list.count()):
    if win.list.item(i).data(ui.ROLE) == hf["id"]:
        win.list.setCurrentRow(i)
qapp.processEvents()
check(win.rows.topLevelItemCount() == len(hf["rows"]), "rows shown")
check(win.terms.text().startswith("heart failure"), f"the model's words shown: {win.terms.text()!r}")
check(hf["terms"] and not hf["terms_set"], "switching lectures keeps the model's words")
check([r["use"] for r in hf["rows"]][0] == "whole", "whole rows first")
check("to open" in win.checks.text(), f"checks: {win.checks.text()[:80]}")
shot(win, "3-lecture", (1180, 780))

# untick a row: the count follows
before = C.summary(c, hf, app.idx)["new"]
it = win.rows.topLevelItem(0)
it.setCheckState(0, QtCore.Qt.CheckState.Unchecked)
check(not hf["rows"][0]["on"], "unticked row saved")
check(C.summary(c, hf, app.idx)["new"] < before, "untick lowers the count")
it.setCheckState(0, QtCore.Qt.CheckState.Checked)

# open, tag, browse, plan text
n_sus = t.col.db.scalar("SELECT count() FROM cards WHERE queue = -1")
win.open_ticked()
check(t.col.db.scalar("SELECT count() FROM cards WHERE queue = -1") < n_sus, "Open ticked opened cards")
check(any("Opened" in x for x in tips), f"tooltip: {tips[-1:]}")
t.col.undo()
check(t.col.db.scalar("SELECT count() FROM cards WHERE queue = -1") == n_sus, "one undo puts them back")
app.states_at = 0  # a second later: the window reads what's open again
check(C.summary(c, hf, app.index())["new"] == before, "after the undo, the counts are back")
win.tag_cards()
check(any("Course::Block_2::2026-10-26_Heart_failure" in t.col.get_note(n).tags for n in app.idx.under(T.VA)),
      "tagged")
win.browse_btn.click()
check(browsed and browsed[-1].startswith("cid:"), "Show in Browse searched")
shown = []
ui.TextDialog.exec = lambda self: (shot(self, "4-plan-text", (820, 520)), shown.append(1))
win.plan_text()
check(shown and "| for Cardio quiz 1" in QtWidgets.QApplication.clipboard().text(), "plan text copied")

# settings, measuring, Browse's split
sd = ui.SettingsDialog(app, win)
shot(sd, "5-settings", (640, 640))
md = ui.MeasureDialog(app, win)
check(md.key.findText(T.KEY) >= 0, "the answer key is offered")
md.objs.setPlainText("SLG 5 | Name the drugs that lower mortality in heart failure\nSLG 9 | Not in the key")
md.run()
check(len(md.results) == 1 and md.results[0][1]["key"] == 3, f"measured: {md.results[:1]}")
shot(md, "6-measure", (980, 700))
sp = ui.SplitDialog(app, win, T.DI)
shot(sp, "7-split", (560, 380))
labels = [sp.grid.itemAt(i).widget().text() for i in range(sp.grid.count()) if sp.grid.itemAt(i).widget()]
check(any("Heart failure" in x for x in labels), f"split by lecture: {labels}")
check(any("Ask the Mac model" == x for x in labels), "ask button")
win.close()
app.reset_runner()
t.tearDown()
print(f"{len(fails)} problem{'s' if len(fails) != 1 else ''}; pictures in {OUT}")
sys.exit(1 if fails else 0)
