"""Render every Due Crew dialog offscreen with real PyQt6 against the fake
Worker (tests/fakes.py), and save a PNG of each. The one way to see the Qt side without
launching Anki; the two crashes of 2026-09-10 would both have shown here.

    QT_QPA_PLATFORM=offscreen <python-with-PyQt6> tools/dialogs.py OUT_DIR

Also usable as a smoke test: exits non-zero if any dialog fails to build."""

import os
import sys
import types
import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fakes  # noqa: E402

STORE = fakes.FakeWorker()
fakes.install_fake_requests(STORE)
aqt = fakes.install_fake_aqt()  # hooks, deckbrowser: enough for the package import

# ---- aqt shim on real Qt ----
from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: E402

qt = types.ModuleType("aqt.qt")
for mod in (QtCore, QtGui, QtWidgets):
    for name in dir(mod):
        if name.startswith("Q") or name == "pyqtSignal":
            setattr(qt, name, getattr(mod, name))
qt.Qt = QtCore.Qt
qt.QMimeData = QtCore.QMimeData

app = QtWidgets.QApplication(sys.argv[:1])

PENDING = []


class _MainHop(QtCore.QObject):
    """Dialogs hand callbacks to mw.taskman.run_on_main from worker threads;
    a queued signal delivers them on the GUI thread, like Anki does."""
    hop = QtCore.pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.hop.connect(lambda f: f(), QtCore.Qt.ConnectionType.QueuedConnection)


HOP = _MainHop()


class _Taskman:
    def run_on_main(self, f):
        HOP.hop.emit(f)

    def run_in_background(self, f):
        f()  # synchronous: the fake store answers instantly


def _collection():
    """A real in-memory collection, from the builders the suite uses. The
    stub this replaces answered every query with nothing, so Shared Decks
    only ever rendered "No decks with cards yet" — and the populated state,
    with its counts and match labels, is where a crash would be. sqlite's
    same-thread check is left on: a dialog touching the collection off the
    main thread raises here, as the main-thread rule says it should."""
    import sqlite3
    conn = sqlite3.connect(":memory:")
    fakes.make_collection(conn)
    cid = 0
    for did, cards, seen in ((1, 9, 6), (3, 4, 2), (2, 5, 0)):
        for i in range(cards):
            cid += 1
            fakes.add_card(conn, cid, did=did, ctype=2 if i < seen else 0,
                           queue=2 if i < seen else 0, ivl=30 if i % 2 == 0 else 3)
    col = fakes.FakeCol(conn, fakes.day_cutoff_for(datetime.date.today()))
    col.decks = fakes.FakeDecks({1: "Big Step 1", 3: "Big Step 1::Cardio",
                                 2: "Pharm::Antibiotics"})
    return col


aqt.mw.col = _collection()
aqt.mw.taskman = _Taskman()
utils = types.ModuleType("aqt.utils")
utils.tooltip = lambda *a, **k: None
utils.askUser = lambda *a, **k: True
utils.showInfo = lambda *a, **k: None
theme = types.ModuleType("aqt.theme")
theme.theme_manager = types.SimpleNamespace(night_mode=False)
for name, mod in (("aqt.qt", qt), ("aqt.utils", utils), ("aqt.theme", theme)):
    sys.modules[name] = mod
aqt.qt, aqt.utils, aqt.theme = qt, utils, theme

from due_crew.backend import api  # noqa: E402

# ---- a signed-in Sam with a crew, a knock, and two squads ----
TODAY = datetime.date.today().isoformat()

for uid, name in (("sam", "Sammy"), ("igk", "igk"), ("ameya", "Ameya"), ("adina", "Adina"),
                  ("chi", "Chidemma"), ("priya", "Priya")):
    STORE.add_user(uid, name, code=uid.upper()[:3] + "123")
for uid in ("igk", "ameya", "adina", "chi"):
    STORE.befriend("sam", uid)
for uid in ("igk", "ameya", "adina", "priya"):
    STORE.befriend(uid, "sam")
CLIENT = api.ApiClient(os.path.join(os.environ.get("TMPDIR", "/tmp"), "dc-dialogs-session.json"))
CLIENT.session = {"user_id": "sam", "token": STORE.session_for("sam"),
                  "display_name": "Sammy", "email": "sam@example.com",
                  "last_ok": (datetime.datetime.now(datetime.timezone.utc)
                              - datetime.timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%SZ")}
SQUAD = CLIENT.create_squad("busm")
STORE._join(SQUAD["id"], "priya")
STORE.knocks[("sam", "priya")] = {"squad": SQUAD["id"], "at": "t"}

CONFIG = {
    "show_leaderboard": True, "period": "today", "sort": "reviews", "show_stale": True,
    "sync_notifications": True, "theme": "auto", "accent": "green", "compact": False,
    "show_last_active": True, "highlight_me": True, "share_reviews": True,
    "share_time": True, "share_retention": True, "share_streak": True,
    "share_heatmap": True, "show_up": False, "paused": False, "exam_date": "2026-09-20",
    "crew_label": "busm", "away_from": "", "away_to": "", "status": "coffee, then 400 cards",
    "shared_decks": [1], "squads": [SQUAD, {"id": "b" * 24, "code": "MS2XXXXX", "name": "MS2", "founder": "x"}],
    "squad": SQUAD["id"],
}
aqt.mw.addonManager.getConfig = lambda name: CONFIG  # the accent reaches dialogs
# fingerprints are note guids; these overlap the Step 1 subtree built in
# _collection(), so the Shared Decks dialog has a real match to show
_SIG = [f"guid{n:06d}" for n in range(1, 13)]
CREW = [{"user_id": "sam", "name": "Sammy", "you": True, "decks": [{"name": "Big Step 1", "sig": _SIG}]},
        {"user_id": "igk", "name": "igk", "you": False, "decks": [{"name": "Big Step 1", "sig": _SIG[:10]}]}]


def settle(ms=400):
    """Let worker threads finish and their queued callbacks land."""
    end = QtCore.QDeadlineTimer(ms)
    while not end.hasExpired():
        app.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents, 50)
        QtCore.QThread.msleep(10)


def shoot(dlg, path):
    dlg.show()
    settle()
    pix = dlg.grab()
    pix.save(path)
    print(f"{os.path.basename(path)}: {pix.width()}x{pix.height()}")
    dlg.close()


def main(out):
    os.makedirs(out, exist_ok=True)
    for old in os.listdir(out):  # this run's renders only: none left from dialogs that changed or went
        if old.endswith(".png"):
            os.remove(os.path.join(out, old))
    failures = []
    noop = lambda *a, **k: None

    def attempt(label, build):
        try:
            build()
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            failures.append(f"{label}: {e}")

    def settings():
        from due_crew.ui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(None, CLIENT, dict(CONFIG, emoji="\U0001F98A"), noop, noop, noop,
                             noop, noop, noop, edit_emoji=noop, edit_status=noop)
        tabs = dlg.findChild(QtWidgets.QTabWidget)
        for i in range(tabs.count()):
            tabs.setCurrentIndex(i)
            shoot(dlg, os.path.join(out, f"settings-{i}-{tabs.tabText(i).lower()}.png"))
        # Just show up chosen: the numbers stay set underneath, greyed out
        dlg = SettingsDialog(None, CLIENT, dict(CONFIG, show_up=True), noop, noop, noop,
                             noop, noop, noop, tab="privacy")
        shoot(dlg, os.path.join(out, "settings-privacy-showup.png"))

    def friends():
        from due_crew.ui.friends_dialog import FriendsDialog
        dlg = FriendsDialog(None, CLIENT, muted=[], on_mute=noop)
        shoot(dlg, os.path.join(out, "friends.png"))

    def decks():
        from due_crew.ui.decks_dialog import DecksDialog
        dlg = DecksDialog(None, CONFIG, CREW, noop)
        app.processEvents()
        shoot(dlg, os.path.join(out, "decks.png"))

    def squads():
        from due_crew.ui.squad_dialog import SquadDialog
        empty = SquadDialog(None, CLIENT, noop)
        app.processEvents()
        shoot(empty, os.path.join(out, "squads-empty.png"))
        dlg = SquadDialog(None, CLIENT, noop)
        dlg.code_edit.setText(SQUAD["code"])
        dlg._look_up()
        app.processEvents()
        shoot(dlg, os.path.join(out, "squads.png"))

    def cheer():
        from due_crew.ui.cheer_dialog import CheerDialog
        from due_crew.app import CHEER_QUICK
        dlg = CheerDialog(None, "Ameya", CHEER_QUICK)
        dlg.other.setText("\U0001F973")  # a palette pick landing in the box
        shoot(dlg, os.path.join(out, "cheer.png"))

    def auth():
        from due_crew.ui.auth_dialog import AuthDialog
        dlg = AuthDialog(None, CLIENT)
        shoot(dlg, os.path.join(out, "auth.png"))              # 1: the email
        dlg.sent_to.setText("We sent a code to sam@example.com. It works for 10 minutes.")
        dlg._show(1)
        shoot(dlg, os.path.join(out, "auth-code.png"))         # 2: the code
        dlg._show(2)
        shoot(dlg, os.path.join(out, "auth-name.png"))         # 3: a new account's name

    def welcome():
        from due_crew.ui.welcome_dialog import WelcomeDialog
        dlg = WelcomeDialog(None, CLIENT, CONFIG, noop)
        dlg.code_input.setText("Study with me on Due Crew · my code IGK123")
        shoot(dlg, os.path.join(out, "welcome.png"))

    def logo():
        """2.10: the logo takes the accent and the theme. The sign-in and
        welcome screens drop it quietly if Qt can't draw SVG; here that's a
        failure, so CI proves it draws."""
        from due_crew import ui
        was = CONFIG["accent"]
        try:
            for accent, night in (("green", False), ("rose", False), ("purple", True), ("amber", True)):
                CONFIG["accent"] = accent
                theme.theme_manager.night_mode = night
                label = ui.logo_label()
                if label is None:
                    raise RuntimeError("logo_label: Qt could not draw the SVG")
                label.setStyleSheet(f"background: {'#1c1c1c' if night else '#ffffff'}; padding: 16px;")
                label.adjustSize()
                label.grab().save(os.path.join(out, f"logo-{accent}{'-dark' if night else ''}.png"))
            CONFIG["accent"] = "rose"
            theme.theme_manager.night_mode = False
            from due_crew.ui.welcome_dialog import WelcomeDialog
            shoot(WelcomeDialog(None, CLIENT, CONFIG, noop), os.path.join(out, "welcome-rose.png"))
        finally:
            CONFIG["accent"] = was
            theme.theme_manager.night_mode = False

    def room():
        from due_crew.ui.room_dialog import RoomDialog
        dlg = RoomDialog(None)
        shoot(dlg, os.path.join(out, "room.png"))
        dlg.later.setChecked(True)
        shoot(dlg, os.path.join(out, "room-later.png"))

    def emoji():
        from due_crew.ui.cheer_dialog import EmojiDialog
        shoot(EmojiDialog(None, "\U0001F98A"), os.path.join(out, "emoji.png"))
        shoot(EmojiDialog(None, "\U0001F985"), os.path.join(out, "emoji-other.png"))

    def report():
        """3.0.1: right-click a crewmate → Report…. The name is the server's:
        it goes in the title only, as plain text."""
        from due_crew.ui.report_dialog import ReportDialog
        dlg = ReportDialog(None, "Ameya <b>")
        if dlg.windowTitle() != "Report Ameya <b>":
            raise RuntimeError(f"report: title {dlg.windowTitle()!r}")
        shoot(dlg, os.path.join(out, "report.png"))
        dlg = ReportDialog(None, "Ameya")
        dlg.choices[2].setChecked(True)
        dlg.note_edit.setText("  keeps   knocking ")
        dlg._report()
        if (dlg.reason, dlg.note) != ("other", "keeps knocking"):
            raise RuntimeError(f"report: {dlg.reason!r} {dlg.note!r}")

    def plans():
        """3.1: Make a plan, Follow a plan (with the tag swap and the late
        join), Resume's catch-up, and Add to a plan from the browser. Names
        come from the author: one carries markup, which must stay text."""
        from due_crew import plans as P
        from due_crew.ui.plan_dialog import MakePlanDialog
        from due_crew.ui.follow_dialog import CatchUpDialog, FollowDialog, SwapDialog
        from due_crew.ui.add_cards_dialog import AddCardsDialog
        conn = aqt.mw.col.db.conn
        tags = {1: "Step1_v11::Cardio::Heart_failure", 2: "Step1_v11::Cardio::Heart_failure",
                3: "Step1_v11::Cardio::Arrhythmia", 4: "Step1_v11::Renal::Physiology",
                5: "Step1_v11::Renal::Physiology", 6: "Step1_v11::Renal::Pharm"}
        for nid, tag in tags.items():
            conn.execute("UPDATE notes SET tags = ? WHERE id = ?", (f" {tag} ", nid))
        opened = []

        dlg = MakePlanDialog(None, CLIENT, aqt.mw.col, "https://duecrew.com", open_link=opened.append)
        shoot(dlg, os.path.join(out, "plan-make.png"))
        dlg = MakePlanDialog(None, CLIENT, aqt.mw.col, "https://duecrew.com", open_link=opened.append)
        dlg.show()
        dlg._open()
        settle()
        if not opened or "#" not in opened[0] or "/plans/new?deck=Big%20Step%201" not in opened[0]:
            raise RuntimeError(f"make: opened {opened!r} {dlg.status.text()!r} {STORE.log[-3:]}")
        if ("sam", "Big Step 1") not in STORE.plan_trees:
            raise RuntimeError("make: the tree didn't go")

        today = datetime.date.today()
        day = lambda n: (today + datetime.timedelta(days=n)).isoformat()
        units = [
            {"id": "hf", "name": "Heart failure", "opens": day(-14), "due": day(-7),
             "tags": ["Step1::Cardio::Heart_failure"]},
            {"id": "ar", "name": "Arrhythmia <b>", "opens": day(-7), "due": day(0),
             "tags": ["Step1::Cardio::Arrhythmia"]},
            {"id": "rp", "name": "Renal physiology", "opens": day(-1), "due": day(6),
             "tags": ["Step1::Renal::Physiology"], "cards": [["guid000004", 0], ["guidnothere", 0]]},
            {"id": "pa", "name": "Pulm · Asthma", "opens": day(3), "tags": ["Step1::Pulm::Asthma"]},
            {"id": "ph", "name": "Renal pharm", "opens": day(6), "tags": ["Step1::Renal::Pharm"]},
            {"id": "x1", "name": "Extras", "opens": day(13), "decks": ["Step 1::Cardio"]},
            {"id": "x2", "name": "Review", "opens": day(20), "tags": ["Step1::Cardio"]},
        ]
        _pid, code = STORE.add_plan("igk", "Step 1", "Step 1", units)
        STORE.add_plan("sam", "My plan", "Big Step 1", units[:3])
        asked = []
        dlg = FollowDialog(None, CLIENT, aqt.mw.col, code=code, today=today.isoformat(),
                           swap_prompt=lambda sw, n: asked.append((sw, n)) or True)
        settle()
        if not dlg.plan or not asked or asked[0][0] != ("Step1", "Step1_v11"):
            raise RuntimeError(f"follow: plan {bool(dlg.plan)}, swap asked {asked!r}")
        names = [w for w in dlg.match.findChildren(QtWidgets.QLabel) if w.text() == "Arrhythmia <b>"]
        if not names or names[0].textFormat() != QtCore.Qt.TextFormat.PlainText:
            raise RuntimeError("follow: a unit's name went in as markup")
        shoot(dlg, os.path.join(out, "plan-follow.png"))
        shoot(SwapDialog(None, ("Step1", "Step1_v11"), 1944), os.path.join(out, "plan-swap.png"))
        shoot(CatchUpDialog(None, 2, 61, {"opens": day(6)}), os.path.join(out, "plan-resume.png"))
        # G4, G7: a follower's own days
        from due_crew.ui.days_dialog import BackDialog, PauseDialog, ShiftDialog
        shoot(PauseDialog(None, "MS2 <Micro> block", day(0), day(6), from_away=True), os.path.join(out, "plan-pause.png"))
        shoot(BackDialog(None, 4, 5, ("Micro quiz", "Thu 15 Oct")), os.path.join(out, "plan-back.png"))
        shoot(ShiftDialog(None, "MS2 Micro block", 3), os.path.join(out, "plan-shift.png"))
        dlg = AddCardsDialog(None, CLIENT, P.card_refs(aqt.mw.col, [4, 5, 6]), today.isoformat())
        settle()
        if dlg.plan.count() != 1:
            raise RuntimeError(f"add: {dlg.plan.count()} plans of mine listed")
        shoot(dlg, os.path.join(out, "plan-add-cards.png"))
        # 3.6.5: a date that has opened says when followers get what's added
        dlg = AddCardsDialog(None, CLIENT, P.card_refs(aqt.mw.col, [4, 5, 6]), today.isoformat())
        settle()
        dlg.date.setDate(QtCore.QDate(today.year, today.month, today.day))
        if dlg.opened.isHidden():
            raise RuntimeError("add: an opened date doesn't say so")
        shoot(dlg, os.path.join(out, "plan-add-opened.png"))
        # 3.6.5, P3: Export cards for my AI, a followed plan picked
        from due_crew.ui.export_dialog import ExportDialog
        fplan = {"id": "p1abcdefghij", "name": "Cardio block", "ownerName": "Dre", "doc": {"deck": "Big Step 1", "units": [
            {"id": "u1", "name": "Cardio", "opens": today.isoformat(), "tags": [], "decks": ["Big Step 1::Cardio"], "cards": []}]}}
        dlg = ExportDialog(None, aqt.mw.col, None, [fplan], {})
        settle()
        if "notes" not in dlg.size.text() or dlg.scope.count() != 2:
            raise RuntimeError(f"export: {dlg.size.text()!r} {dlg.scope.count()}")
        shoot(dlg, os.path.join(out, "export-for-ai.png"))
        dlg = AddCardsDialog(None, CLIENT, P.card_refs(aqt.mw.col, [4, 5, 6]), today.isoformat(),
                             search="tag:*Cardio* tag:*#B&B* -tag:*Pharm*", search_n=212)
        settle()
        shoot(dlg, os.path.join(out, "plan-add-search.png"))
        # Change deck's question carries the plan's name: plain text, as the tip prompts
        from due_crew.ui import _plain_input
        dlg = _plain_input(None, "Change deck", "Run Arrhythmia <b> on")
        dlg.setComboBoxItems(["Big Step 1", "Other"])
        dlg.setComboBoxEditable(False)
        labels = [w for w in dlg.findChildren(QtWidgets.QLabel) if "Arrhythmia" in w.text()]
        if not labels or labels[0].textFormat() != QtCore.Qt.TextFormat.PlainText:
            raise RuntimeError("change deck: the plan's name went in as markup")
        shoot(dlg, os.path.join(out, "plan-change-deck.png"))

    def schedule():
        """3.2: my schedule for a plan: start, days, time, and the load chart.
        The plan's name is the author's: plain text in the title only."""
        from due_crew.ui.schedule_dialog import ScheduleDialog
        units = [{"id": "c", "name": "Cardio", "opens": "2026-10-05", "due": "2026-10-18"},
                 {"id": "r", "name": "Renal", "opens": "2026-10-19", "due": "2026-11-08"},
                 {"id": "p", "name": "Pulm", "opens": "2026-11-09", "due": "2026-11-29"}]
        plan = {"id": "p1", "name": "Step 1 <b>", "doc": {"deck": "Step 1", "end": "2026-12-12",
                "phases": {"catchup": 4, "taper": 10}, "units": units}}
        totals = {"c": 420, "r": 610, "p": 560}
        dlg = ScheduleDialog(None, plan, "2026-10-01", totals, [120] * 190, (9.0, 35.0))
        if dlg.windowTitle() != "My schedule · Step 1 <b>":
            raise RuntimeError(f"schedule: title {dlg.windowTitle()!r}")
        shoot(dlg, os.path.join(out, "plan-schedule.png"))
        dlg._tap(6)
        dlg._tap(5)
        if dlg.value()["days"] != [1, 1, 1, 1, 1, 2, 1]:
            raise RuntimeError(f"schedule: days {dlg.value()}")
        dlg.later.setChecked(True)
        dlg.start.setDate(QtCore.QDate(2026, 10, 12))
        if dlg.value().get("start") != "2026-10-12":
            raise RuntimeError(f"schedule: start {dlg.value()}")
        dlg = ScheduleDialog(None, dict(plan, sched={"days": [1] * 7, "minutes": 30}), "2026-10-01",
                             totals, [300] * 190, (9.0, 35.0))
        shoot(dlg, os.path.join(out, "plan-schedule-over.png"))
        if "go past" not in dlg.summary.text():
            raise RuntimeError(f"schedule: no warning in {dlg.summary.text()!r}")
        dlg._no_schedule()
        if dlg.value() is not None:
            raise RuntimeError("schedule: No schedule didn't clear it")

    def tools_menu():
        """Tools › Due Crew as profile open builds it, on a real QMenu (3.1:
        a separator entry once crashed every start, and no test loaded it)."""
        import due_crew
        tools = QtWidgets.QMenu("Tools")
        win = QtWidgets.QMainWindow()  # the real parent Anki's main window is
        win.form = types.SimpleNamespace(menuTools=tools)
        win._due_crew_menu = None
        saved = due_crew.mw
        due_crew.mw = win
        try:
            due_crew._tools_menu()
            due_crew._tools_menu()  # a second profile open adds nothing
        finally:
            due_crew.mw = saved
        subs = [a.menu() for a in tools.actions() if a.menu()]
        if len(subs) != 1:
            raise RuntimeError(f"tools menu: {len(subs)} Due Crew submenus")
        items = [a.text() or "—" for a in subs[0].actions()]
        want = ["Friends…", "Squads…", "—", "Make a plan from a deck…",
                "Follow a plan…", "Export cards for my AI…", "—", "Settings…"]
        if items != want:
            raise RuntimeError(f"tools menu: {items}")

    for label, build in (("tools menu", tools_menu), ("settings", settings), ("friends", friends), ("decks", decks),
                         ("squads", squads), ("cheer", cheer), ("auth", auth),
                         ("welcome", welcome), ("logo", logo), ("room", room), ("emoji", emoji),
                         ("report", report), ("plans", plans), ("schedule", schedule)):
        attempt(label, build)
    if failures:
        print("FAILED:", *failures, sep="\n  ")
        return 1
    print("all dialogs built")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "dialog-shots"))
