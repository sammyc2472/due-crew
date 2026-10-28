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
if os.environ["QT_QPA_PLATFORM"] == "offscreen":
    # a laptop's screen, not offscreen's 800x600: a window takes at most two
    # thirds of its screen, and a narrow one would squeeze rows a Mac doesn't
    import json
    import tempfile
    _screen = os.path.join(tempfile.gettempdir(), "dc-dialogs-screen.json")
    with open(_screen, "w") as _f:
        json.dump({"screens": [{"name": "laptop", "x": 0, "y": 0, "width": 1440, "height": 900,
                                "logicalDpi": 96, "logicalBaseDpi": 96, "dpr": 1}]}, _f)
    os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _screen

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
# a Mac's system font, near enough (13 px; Arial's metrics stand in for the
# system face), so a render here clips or wraps where a Mac would
_font = QtGui.QFont("Liberation Sans")
_font.setPixelSize(13)
app.setFont(_font)
if os.environ.get("DC_APP_QSS"):  # an app-wide style sheet under ours, as Anki's own widget style sets one
    app.setStyle(QtWidgets.QStyleFactory.create("Fusion"))
    with open(os.environ["DC_APP_QSS"], encoding="utf-8") as _f:
        app.setStyleSheet(_f.read())

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
if os.environ.get("DC_THEME") in ("light", "dark"):  # DC_THEME=dark: every window in the board's dark look
    CONFIG["theme"] = os.environ["DC_THEME"]
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


def heading_of(dlg):
    """3.9.1: a window's title is its heading (ui.heading), in plain text: a
    name in it is someone's. None if it has none, or one in rich text."""
    for label in dlg.findChildren(QtWidgets.QLabel):
        if label.property("dc") == "title":
            return label.text() if label.textFormat() == QtCore.Qt.TextFormat.PlainText else None
    return None


def fits(dlg):
    """3.9.1: what a person would see as broken, measured: a button, tick or
    choice narrower than its words; a box narrower than its words (up to the
    240px ui._tidy keeps); two of a row's buttons or boxes on top of each
    other; a window shorter or narrower than its rows need. [] when none."""
    W = QtWidgets
    bad = []
    sheet = bool(dlg.property("every_control"))  # the kitchen: every control at once, not a window anyone opens
    if not sheet and (dlg.width() > 1280 or dlg.height() > 800):  # round five: a window, as it is now, fits a laptop's screen
        bad.append(f"window {dlg.width()}x{dlg.height()}: bigger than a 1280x800 screen")
    lay = dlg.layout()
    if lay is not None:
        least = lay.totalMinimumSize()
        if not sheet and (least.width() > 1240 or least.height() > 740):
            bad.append(f"its rows need {least.width()}x{least.height()}: more than a 1280x800 screen has")
        if dlg.width() < least.width() or dlg.height() < least.height():
            bad.append(f"window {dlg.width()}x{dlg.height()} under its rows' {least.width()}x{least.height()}")
        elif lay.hasHeightForWidth() and not dlg.property("dcOwnSize") and dlg.height() < lay.totalHeightForWidth(dlg.width()):
            bad.append(f"window {dlg.height()} tall, its words need {lay.totalHeightForWidth(dlg.width())}")
    shown = [w for w in dlg.findChildren(W.QWidget) if w.isVisibleTo(dlg) and w.window() is dlg]
    for w in shown:
        if isinstance(w, (W.QPushButton, W.QCheckBox, W.QRadioButton)) and w.text():
            if w.width() < w.sizeHint().width() - 1:
                bad.append(f"{type(w).__name__} {w.text()!r} {w.width()} < {w.sizeHint().width()}")
        elif isinstance(w, W.QComboBox) and w.count():
            if w.width() < min(w.sizeHint().width(), 240) - 1:
                bad.append(f"box {w.currentText()!r} {w.width()} < {w.sizeHint().width()}")
    controls = [w for w in shown if isinstance(w, (W.QPushButton, W.QComboBox, W.QLineEdit, W.QAbstractSpinBox))]
    for i, a in enumerate(controls):
        for b in controls[i + 1:]:
            if a.parentWidget() is b.parentWidget() and a.geometry().intersects(b.geometry()):
                bad.append(f"{type(a).__name__} over {type(b).__name__}: {a.geometry()} {b.geometry()}")
    return bad


def shoot(dlg, path):
    dlg.show()
    settle()
    broken = fits(dlg)
    if broken:
        raise RuntimeError(f"{os.path.basename(path)}: " + "; ".join(broken))
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

    def friends():
        from due_crew.ui.friends_dialog import FriendsDialog
        STORE.users["igk"]["emoji"] = "\U0001F422"  # 3.8.22: names alone in the list, never an emoji
        dlg = FriendsDialog(None, CLIENT, muted=[], on_mute=noop)
        shoot(dlg, os.path.join(out, "friends.png"))
        rows = [dlg.list.item(i).text() for i in range(dlg.list.count())]
        if not any("igk" in r for r in rows) or any("\U0001F422" in r for r in rows):
            raise RuntimeError(f"friends: the list shows emojis, or not the crew: {rows}")

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
        # 3.9.5: in 20 squads already, a join and a new squad are refused and said so
        full = SquadDialog(None, CLIENT, noop)
        full.code_edit.setText(SQUAD["code"])
        full._look_up()
        app.processEvents()
        full._joined(full.peek or {}, 409)
        app.processEvents()
        shoot(full, os.path.join(out, "squads-join-full.png"))
        full._joined(full.peek or {}, 429)  # 3.9.5: a join's budget, 30 tries an hour
        app.processEvents()
        shoot(full, os.path.join(out, "squads-join-tries.png"))
        made = SquadDialog(None, CLIENT, noop)
        made.name_edit.setText("Anatomy")
        made._created({"error": "too_many_squads"})
        app.processEvents()
        shoot(made, os.path.join(out, "squads-create-full.png"))

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

    def kitchen():
        """3.9.1: every kind of box, button, tick and list a window uses, in the
        board's look (ui.styled), with a box's list open and a calendar: the
        one picture that shows the whole look, light or dark (DC_THEME)."""
        from due_crew import ui
        W = QtWidgets
        dlg = W.QDialog()
        ui.attach_alive(dlg)
        dlg.setWindowTitle("Due Crew")
        root = W.QVBoxLayout(dlg)
        root.addWidget(ui.role(W.QLabel("Open a study room"), "title"))
        root.addWidget(ui.role(W.QLabel("Your crew sees it on their board and can join any time."), "note"))
        row = W.QHBoxLayout()
        row.addWidget(W.QLabel("Rounds"))
        spin = W.QSpinBox()
        spin.setRange(1, 8)
        spin.setValue(4)
        row.addWidget(spin)
        row.addWidget(W.QLabel("of"))
        box = W.QComboBox()
        for m in (15, 25, 30, 45, 50):
            box.addItem(f"{m} min")
        box.setCurrentIndex(1)
        row.addWidget(box)
        row.addWidget(W.QLabel("with"))
        brk = W.QComboBox()
        brk.addItems(["5 min", "10 min"])
        brk.setEnabled(False)
        row.addWidget(brk)
        row.addStretch()
        root.addLayout(row)
        when = W.QHBoxLayout()
        when.addWidget(W.QLabel("Starts"))
        now, later = W.QRadioButton("Now"), W.QRadioButton("At a time")
        now.setChecked(True)
        when.addWidget(now)
        when.addWidget(later)
        t = W.QTimeEdit()
        t.setDisplayFormat("HH:mm")
        when.addWidget(t)
        date = W.QDateEdit(QtCore.QDate(2026, 10, 24))
        date.setCalendarPopup(True)
        date.setDisplayFormat("ddd d MMM yyyy")
        when.addWidget(date)
        when.addStretch()
        root.addLayout(when)
        root.addWidget(ui.role(W.QLabel("How its cards open"), "head"))
        a, b = W.QCheckBox("Hold back 2 cards of later dates until their day"), W.QCheckBox("Join this plan's squad")
        a.setChecked(True)
        root.addWidget(a)
        root.addWidget(b)
        off = W.QCheckBox("Can't be changed")
        off.setEnabled(False)
        root.addWidget(off)
        edit = W.QLineEdit()
        edit.setPlaceholderText("Their code, or paste their invite")
        root.addWidget(edit)
        typed = W.QLineEdit("DLT29GPW")
        root.addWidget(typed)
        lst = W.QListWidget()
        lst.addItems(["Adina", "Ameya", "Chidemma \u2014 waiting", "igk"])
        lst.setCurrentRow(1)
        lst.setFixedHeight(96)
        root.addWidget(lst)
        tree = W.QTreeWidget()
        tree.setHeaderLabels(["Deck", "Cards"])
        top = W.QTreeWidgetItem(["Big Step 1", "13"])
        top.setCheckState(0, QtCore.Qt.CheckState.Checked)
        kid = W.QTreeWidgetItem(["Cardio", "4"])
        kid.setCheckState(0, QtCore.Qt.CheckState.Unchecked)
        top.addChild(kid)
        tree.addTopLevelItem(top)
        other = W.QTreeWidgetItem(["Pharm::Antibiotics", "5"])
        other.setCheckState(0, QtCore.Qt.CheckState.Unchecked)
        tree.addTopLevelItem(other)
        tree.expandAll()
        tree.setFixedHeight(110)
        root.addWidget(tree)
        cal = W.QCalendarWidget()
        cal.setSelectedDate(QtCore.QDate(2026, 10, 24))
        cal.setCurrentPage(2026, 10)
        root.addWidget(cal)
        bb = W.QDialogButtonBox(W.QDialogButtonBox.StandardButton.Ok | W.QDialogButtonBox.StandardButton.Cancel)
        bb.button(W.QDialogButtonBox.StandardButton.Ok).setText("Open Room")
        extra = bb.addButton("Not today", W.QDialogButtonBox.ButtonRole.ActionRole)
        extra.setEnabled(False)
        root.addWidget(bb)
        dlg.resize(560, 10)
        dlg.setProperty("every_control", True)
        shoot(dlg, os.path.join(out, "kitchen.png"))
        dlg.show()
        settle(100)
        box.showPopup()
        settle(200)
        pop = box.view().window()
        pix = QtGui.QPixmap(dlg.width(), dlg.height())
        dlg.render(pix)
        p = QtGui.QPainter(pix)
        at = pop.mapToGlobal(QtCore.QPoint(0, 0)) - dlg.mapToGlobal(QtCore.QPoint(0, 0))
        p.drawPixmap(at, pop.grab())
        p.end()
        pix.save(os.path.join(out, "kitchen-popup.png"))
        box.hidePopup()
        dlg.close()

    def questions():
        """3.9.1: the board's questions off the board (sheets' Qt fallback),
        and Due's Pick a day: every window in the look."""
        from due_crew import ui, due_flow
        holder = QtWidgets.QWidget()  # the main window's stand-in
        box, _go = ui._question(holder, "Remove igk?", "They come off your crew, and you off theirs.", "Remove", True)
        shoot(box, os.path.join(out, "q-confirm.png"))
        box, _go = ui._question(holder, "Unfollow Step 1?", "Its dates stop opening. What opened stays open.", "Unfollow", False)
        tick = QtWidgets.QCheckBox("Take its tags off my notes too")
        tick.setChecked(True)
        box.setCheckBox(tick)
        shoot(box, os.path.join(out, "q-confirm-check.png"))
        dlg = ui._plain_input(None, "Your status", "What are you up to? Your crew sees it today.")
        dlg.setTextValue("coffee, then 400 cards")
        shoot(dlg, os.path.join(out, "q-text.png"))
        dlg = ui._plain_input(None, "Move it", "Which day?")
        dlg.setComboBoxItems(["Today", "Tomorrow", "Mon 26 Oct"])
        dlg.setComboBoxEditable(False)
        shoot(dlg, os.path.join(out, "q-item.png"))
        was = QtWidgets.QDialog.exec
        QtWidgets.QDialog.exec = lambda self: (shoot(self, os.path.join(out, "pick-a-day.png")), 0)[1]
        due_flow._state["labels"] = [TODAY]
        main, due_flow.mw = due_flow.mw, holder  # its parent, Anki's window
        try:
            due_flow._pick_day("x", TODAY)
        finally:
            QtWidgets.QDialog.exec = was
            due_flow.mw = main
        # 3.9.5: Insights' exam date in a Qt calendar (the page's own picker went down with a redraw)
        t = datetime.date.fromisoformat(TODAY)
        dlg, cal = ui.date_dialog(holder, "Exam date", t + datetime.timedelta(days=7), lo=t, hi=t + datetime.timedelta(days=730))
        if cal.selectedDate().toString("yyyy-MM-dd") != (t + datetime.timedelta(days=7)).isoformat() or dlg.windowTitle() != "Due Crew":
            raise RuntimeError("exam date: a week out, picked; the frame says Due Crew")
        shoot(dlg, os.path.join(out, "exam-date.png"))

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
        if heading_of(dlg) != "Report Ameya <b>" or dlg.windowTitle() != "Due Crew":
            raise RuntimeError(f"report: title {heading_of(dlg)!r} on {dlg.windowTitle()!r}")
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
        # 3.9.3: made in Anki: named, POST /plans, and Your plans opens on it
        from due_crew.planner import remote as PR
        made = []
        dlg = MakePlanDialog(None, CLIENT, aqt.mw.col, "https://duecrew.com", open_link=opened.append,
                             make=lambda name, deck: PR.create(CLIENT, name, deck), on_made=made.append)
        if dlg.go.text() != "Make the plan" or dlg.site_btn is None or dlg.name.placeholderText() != "Big Step 1":
            raise RuntimeError(f"make here: {dlg.go.text()!r}, {dlg.name.placeholderText()!r}")
        dlg.name.setText("MS2 <b>Block</b> 3")
        shoot(dlg, os.path.join(out, "plan-make-here.png"))
        dlg = MakePlanDialog(None, CLIENT, aqt.mw.col, "https://duecrew.com", open_link=opened.append,
                             make=lambda name, deck: PR.create(CLIENT, name, deck), on_made=made.append)
        dlg.show()
        dlg.name.setText("  MS2   Block 3 ")
        dlg._make()
        settle()
        if len(made) != 1 or STORE.plans.get(made[0].get("id"), {}).get("name") != "MS2 Block 3":
            raise RuntimeError(f"make here: {made!r} {dlg.status.text()!r}")
        STORE.plans.pop(made[0]["id"])  # the renders after this one count Sam's plans

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
        # 3.8.0: at my own pace: the late-start question goes, the box under it shows, the line says so
        dlg = FollowDialog(None, CLIENT, aqt.mw.col, code=code, today=today.isoformat(), swap_prompt=lambda sw, n: True)
        settle()
        dlg.how_ready.setChecked(True)
        settle(100)
        if dlg.own() != "next" or dlg.how_next.isHidden() or dlg.late_skip.isVisible() or "Nothing opens" not in dlg.about.text():
            raise RuntimeError(f"follow at my pace: {dlg.own()!r} {dlg.about.text()!r}")
        dlg.how_next.setChecked(False)
        if dlg.own() != "ready":
            raise RuntimeError("follow at my pace: the box under it")
        shoot(dlg, os.path.join(out, "plan-follow-own-pace.png"))
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
        # 3.8.1: with a plan picked, the plan itself at the file's top, ticked by default; none for a whole deck
        lines = dlg.plan_lines()
        if dlg.with_plan.isHidden() or not dlg.with_plan.isChecked() or not lines or not all(x.startswith("# ") for x in lines):
            raise RuntimeError(f"export with the plan: {lines!r}")
        shoot(dlg, os.path.join(out, "export-for-ai.png"))
        dlg.plan.setCurrentIndex(dlg.plan.count() - 1)
        if not dlg.with_plan.isHidden() or dlg.plan_lines() is not None:
            raise RuntimeError("export: a whole deck has no plan's lines")
        dlg.close()
        # 3.8.1: Follow, when no deck here has the plan's deck's name and the plan says where to get it
        got_pid, got_code = STORE.add_plan("igk", "Elsewhere", "A deck not here", units[:1])
        STORE.plans[got_pid]["doc"]["deckUrl"] = "https://example.com/get-the-deck"
        links = []
        utils.openLink = links.append
        dlg = FollowDialog(None, CLIENT, aqt.mw.col, code=got_code, today=today.isoformat(), swap_prompt=lambda sw, n: False)
        settle()
        if dlg.get_deck.isHidden() or "Where to get it" not in dlg.get_deck.text() or "A deck not here" not in dlg.get_deck.text():
            raise RuntimeError(f"follow: the deck's link {dlg.get_deck.text()!r}")
        dlg.get_deck.linkActivated.emit("x")
        if links != ["https://example.com/get-the-deck"]:
            raise RuntimeError(f"follow: opened {links!r}")
        shoot(dlg, os.path.join(out, "plan-follow-get-deck.png"))
        dlg = FollowDialog(None, CLIENT, aqt.mw.col, code=code, today=today.isoformat(), swap_prompt=lambda sw, n: True)
        settle()
        if not dlg.get_deck.isHidden():
            raise RuntimeError("follow: a plan with no link, or a deck here, says nothing of it")
        dlg.close()
        # 3.6.5, P6: Send feedback to Sam
        from due_crew.ui.feedback_dialog import FeedbackDialog
        dlg = FeedbackDialog(None, CLIENT, "3.6.5")
        dlg.box.setPlainText("The Plans tab is great but I wish I could see next week without the arrows.")
        settle()
        if not dlg.send_btn.isEnabled():
            raise RuntimeError("feedback: Send stays off with text in the box")
        shoot(dlg, os.path.join(out, "feedback.png"))
        dlg = AddCardsDialog(None, CLIENT, P.card_refs(aqt.mw.col, [4, 5, 6]), today.isoformat(),
                             search="tag:*Cardio* tag:*#V&B* -tag:*Pharm*", search_n=212)
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
        if heading_of(dlg) != "My schedule · Step 1 <b>":
            raise RuntimeError(f"schedule: title {heading_of(dlg)!r}")
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
        want = ["Study what’s next", "—", "Friends…", "Squads…", "Game night…", "Plans", "—", "Settings…", "Pip’s closet…", "Your year…",
                "Show on the Decks screen", "Send feedback…"]
        if items != want:
            raise RuntimeError(f"tools menu: {items}")
        # 3.9.5: Game night… shows for its testers alone, as the menu opens
        acts = {a.text(): a for a in subs[0].actions()}
        subs[0].aboutToShow.emit()
        if acts["Game night…"].isVisible():
            raise RuntimeError("tools menu: Game night… shows for someone who isn't a tester")
        # ...and does show for one (signed_in and user_id are the client's properties)
        from due_crew import gamenight_flow as GF
        was = GF.client
        try:
            for uid, want_shown in ((GF.TESTERS[0], True), ("someone-else", False)):
                GF.client = lambda uid=uid: types.SimpleNamespace(signed_in=True, user_id=uid)
                subs[0].aboutToShow.emit()
                if acts["Game night…"].isVisible() != want_shown:
                    raise RuntimeError(f"tools menu: Game night… for {uid}: shown {not want_shown}")
        finally:
            GF.client = was
        # 3.9.3: Plans ▸, everything about plans, the plan windows among it
        plans = [a.menu() for a in subs[0].actions() if a.menu()]
        got = [a.text() or "—" for a in plans[0].actions()] if len(plans) == 1 else []
        if got != ["Your plans…", "New plan…", "Follow a plan…", "—",
                   "QBank QIDs…", "Export cards for my AI…"]:
            raise RuntimeError(f"tools menu: Plans {got}")
        # 3.8.0: Study what's next carries Ctrl+Shift+S; Show on the Decks screen is a check
        acts = {a.text(): a for a in subs[0].actions()}
        if acts["Study what’s next"].shortcut().toString() != "Ctrl+Shift+S":
            raise RuntimeError("tools menu: Study what's next has no Ctrl+Shift+S")
        if not acts["Show on the Decks screen"].isCheckable():
            raise RuntimeError("tools menu: Show on the Decks screen isn't a check")

    def map_card():
        # 3.8.0: "What I know" as a picture: the sheet, and the card itself in each look
        from due_crew.ui.map_card_dialog import MapCardDialog, paint
        from due_crew import mapcard as M
        tiles = [{"key": k.lower(), "name": k, "n": n, "know": kn, "started": n if kn is not None else 0}
                 for k, n, kn in (("Cardio · Physiology", 412, 86), ("Cardio · Pathology", 318, 77), ("Cardio · Pharm", 260, 84),
                                  ("Renal · Physiology", 190, 66), ("Pulm · Pathology", 150, 88), ("Heme", 120, None),
                                  ("Endo", 96, 71), ("MSK", 64, 94))]
        prev = {"cardio · physiology": 82, "cardio · pathology": 79, "renal · physiology": 60}
        dlg = MapCardDialog(None, "Big Step 1", "2026-10-12", tiles, "fsrs", prev, "2026-10-05")
        shoot(dlg, os.path.join(out, "map-card-sheet.png"))
        for name, look, pct, ch in (("light", "light", True, False), ("dark", "dark", True, False),
                                    ("shape", "light", False, False), ("change", "light", True, True)):
            img = paint(M.card("Big Step 1", "2026-10-12", tiles, "fsrs", pct, prev if ch else None,
                               "2026-10-05" if ch else ""), look)
            if img.isNull() or img.width() != M.SIZE:
                raise RuntimeError("map card: no picture")
            img.save(os.path.join(out, f"map-card-{name}.png"))
        if "🟩 Cardio · Physiology 86%" not in dlg.text():
            raise RuntimeError(f"map card: text {dlg.text()!r}")
        dlg.pct.setChecked(False)
        if "%" in dlg.text():
            raise RuntimeError("map card: Percentages off still has numbers")
        none = MapCardDialog(None, "Big Step 1", "2026-10-12", tiles)
        if none.change.isEnabled():
            raise RuntimeError("map card: This week's change on with no week to compare")
        none.close()
        part = MapCardDialog(None, "Big Step 1 · Cardio", "2026-10-12", tiles, part=True)
        if part.change.isEnabled() or "whole deck" not in part.change_note.text():
            raise RuntimeError("map card: a tile's parts should say the change is the deck's")
        part.close()

    def share_card():
        # 3.8.0: Share › As a picture, made in Anki: the sheet, and each card in each size and look
        from due_crew.ui.share_card_dialog import ShareCardDialog, paint
        from due_crew import sharecard as S
        today = "2026-10-14"  # a Wednesday
        start = datetime.date(2024, 3, 4)
        days = {}
        for i in range((datetime.date.fromisoformat(today) - start).days + 1):
            d = start + datetime.timedelta(days=i)
            if (i * 7) % 11 not in (3, 8):  # most days, not all
                days[d.isoformat()] = (40 + (i * 37) % 260, (12 + (i * 13) % 70) * 60000)
        wk = S.week(days, today, False, {today: 14, "2026-10-12": 20}, 23, 4)
        one = S.week(days, today, True, {today: 14}, 23, 2)
        cheers = {"2026": 31, "2025": 12}
        pick = lambda k: ({"kind": "alltime", "title": "Share my Anki, all time", "sizes": ("story", "link"), "file": "due-crew-all-time",
                           "data": S.alltime(days, today, sum(cheers.values()))} if k == "all" else
                          {"kind": "year", "title": "Share my year", "sizes": ("story",), "file": f"due-crew-{k}",
                           "data": S.year(days, k, today, cheers.get(k, 0))})  # noqa: E731
        dlg = ShareCardDialog(None, pick, S.year_options(days, today), "2026")
        shoot(dlg, os.path.join(out, "share-card-year-sheet.png"))
        if dlg.link.isVisible() or not dlg.switch["cheers"].isChecked():
            raise RuntimeError("share card: a year is story only, and its cheers start on")
        dlg.pick.setCurrentIndex(dlg.pick.count() - 1)
        if dlg.kind() != "alltime" or not dlg.switch["best"].isEnabled():
            raise RuntimeError("share card: All time didn't take over the sheet")
        dlg.close()
        priv = S.privacy({"share_time": False})
        wdlg = ShareCardDialog(None, lambda _k: {"kind": "week", "title": "Share my week", "sizes": ("story", "link"),
                                                 "file": "due-crew-week-2026-10-12", "data": dict(wk, sev=True)}, priv=priv)
        shoot(wdlg, os.path.join(out, "share-card-week-sheet.png"))
        if wdlg.switch["time"].isChecked() or "Privacy" not in wdlg.switch["time"].text():
            raise RuntimeError("share card: Time studied should start off when Privacy keeps it home")
        wdlg.close()
        for kind, data, sizes in (("week", wk, ("story", "link")), ("today", one, ("story", "link")),
                                  ("year", pick("2026")["data"], ("story",)), ("year", pick("2025")["data"], ("story",)),
                                  ("alltime", pick("all")["data"], ("story", "link"))):
            on = {k: True for k in ("time", "reviews", "streak", "crew", "best", "cheers")}
            for size in sizes:
                for look in ("light", "dark"):
                    img = paint(kind, size, data, on, look)
                    if img.isNull() or (img.width(), img.height()) != S.SIZES[size]:
                        raise RuntimeError(f"share card: no {kind} {size} picture")
                    tag = data.get("year") if kind == "year" else ""
                    img.save(os.path.join(out, f"share-card-{kind}{tag}-{size}-{look}.png"))
        # 3.8.1: Pip hops across the week (Settings › Pip on): the sample week, one with two days off (the
        # mock's), today's card; Pip drawn by QtSvg in the card's accent, on the last day studied
        mon = datetime.date(2026, 10, 12)
        two_off = {(mon + datetime.timedelta(days=i)).isoformat(): (60 + 23 * i, (14 + 6 * i) * 60000)
                   for i, x in enumerate((1, 1, 0, 1, 1, 0, 1)) if x}
        on = {k: True for k in ("time", "reviews", "streak", "crew")}
        for name, kind, data in (("week", "week", S.week(days, today, False, {today: 14, "2026-10-12": 20}, 23, 4, True)),
                                 ("week-two-off", "week", S.week(two_off, "2026-10-18", False, {"2026-10-18": 9}, 23, 4, True)),
                                 ("today", "today", S.week(days, today, True, {today: 14}, 23, 2, True))):
            for size in ("story", "link"):
                for look in ("light", "dark"):
                    img = paint(kind, size, data, on, look)
                    ops = S.draw(kind, size, data, on, look, lambda s, px, w: 0)[2]
                    sev = [o for o in ops if o[0] == "sev"]
                    if len(sev) != 1:
                        raise RuntimeError(f"share card: Pip isn't on the {name} card")
                    _o, _pose, x, y, z, color = sev[0]
                    if img.pixelColor(int(x + z / 2), int(y + z * 38 / 80)).name() != color:  # its forehead, in the accent
                        raise RuntimeError(f"share card: Pip not drawn on the {name} card ({size}, {look})")
                    img.save(os.path.join(out, f"share-card-{name}-sev-{size}-{look}.png"))

    def game_night():
        # 3.9.5: Tools › Due Crew › Game night…: Play from, then Custom's scope builder
        from due_crew.ui.game_night_window import GameNightWindow
        asked, started = [], []

        class Ops:
            sources = staticmethod(lambda: [{"key": "misses", "label": "This week's misses", "n": 86},
                                            {"key": "plan:p1", "label": "Block 2, this week", "n": 212},
                                            {"key": "saved:Renal misses", "label": "Renal misses", "n": 41}])
            tree = staticmethod(lambda: [("deck:Big Step 1", "Big Step 1", 0), ("deck:Big Step 1::Cardio", "Cardio", 1),
                                         ("tag:Step1", "Step1", 0), ("tag:Step1::Renal", "Renal", 1), ("tag:Step1::Renal::Pharm", "Pharm", 2),
                                         ("tag:Step1::Renal::Heart_failure", "Heart_failure", 2)])
            plans = staticmethod(lambda: [("p1", "Block 2")])
            saved = staticmethod(lambda: [])

            @staticmethod
            def preview(scope):
                asked.append(scope)
                return {"n": 64, "search": '"tag:Step1::Renal" -is:new rated:7:1', "fit": {"trivia": 52, "rounds": 40, "links": 31, "imposter": 3, "draw": 31, "between": 31},
                        "samples": [{"q": "Loop diuretics block the ____ cotransporter", "opts": ["Na-Cl", "Na-K-2Cl", "ENaC", "Na-H"], "ans": 1}]}

            @staticmethod
            def save(name, scope):
                return name or "My scope"

            @staticmethod
            def start(key, scope, label, bots, done):
                started.append((key, label, bots))
                done("Game night isn't open for this account yet." if not bots else None)

        dlg = GameNightWindow(None, Ops())
        if heading_of(dlg) != "Game night" or not dlg.radios[0].isChecked() or dlg.custom.isVisible():
            raise RuntimeError("game night: opens on the first with cards, Custom folded")
        shoot(dlg, os.path.join(out, "game-night.png"))
        dlg = GameNightWindow(None, Ops())
        dlg.custom_r.setChecked(True)
        top = dlg.tree.topLevelItem(1).child(0).child(0)  # Tags › Step1 › Renal
        dlg.tree.itemClicked.emit(top, 0)
        dlg.tree.itemClicked.emit(top.child(0), 0)
        dlg.tree.itemClicked.emit(top.child(0), 0)
        dlg.missed.setChecked(True)
        dlg.refresh()
        sc = dlg.scope()
        if sc["in"] != ["tag:Step1::Renal"] or sc["out"] != ["tag:Step1::Renal::Pharm"] or sc["missed"] != 7 or not sc["seen"]:
            raise RuntimeError(f"game night: the scope {sc}")
        if "64 cards" not in dlg.count.text() or "Trivia: 52" not in dlg.fit.text() or "→ Na-K-2Cl" not in dlg.samples.text():
            raise RuntimeError("game night: the count, the fit, a sample")
        if dlg.samples.textFormat() != QtCore.Qt.TextFormat.PlainText:
            raise RuntimeError("game night: a card's words are plain text")
        shoot(dlg, os.path.join(out, "game-night-custom.png"))
        dlg = GameNightWindow(None, Ops())
        dlg.show()
        dlg.tv_btn.click()
        if started[-1] != ("misses", "This week's misses", False) or "isn't open" not in dlg.said.text() or not dlg.tv_btn.isEnabled():
            raise RuntimeError(f"game night: a refusal is said, and it can try again {started}")
        dlg.bots_btn.click()
        if started[-1][2] is not True or dlg.isVisible():
            raise RuntimeError("game night: bots open and the window goes")

    def why():
        # 3.8.0, pick 9: Browse › why isn't it showing?, a few reasons and their fixes
        from due_crew.ui.why_dialog import WhyDialog
        gs = [{"say": "3 suspended, 1 of them as leeches.", "fix": ("unsuspend",), "label": "Unsuspend them", "n": 3},
              {"say": "New: today's 20 new cards in Anatomy are done.", "fix": ("more_new", 1, 43), "label": "43 more new today", "n": 1},
              {"say": "Not due till Fri 16 Oct, by FSRS.", "fix": ("due_now",), "label": "Study it now", "n": 1},
              {"say": "Learning: back at 15:40. Nothing to do: it comes back on its own.", "fix": None, "label": "", "n": 1},
              {"say": "In <b>Custom</b> Study Session, a filtered deck, not in Anatomy: it shows when you study it.",
               "fix": ("empty", 9), "label": "Empty Custom Study Session", "n": 1}]
        fixed = []
        dlg = WhyDialog(None, gs, fixed.append)
        shoot(dlg, os.path.join(out, "why.png"))
        if len([b for _s, b in dlg.rows if b]) != 4 or "Undo" not in dlg.note.text():
            raise RuntimeError("why: a fix a reason, the undo note")
        if dlg.rows[4][0].textFormat() != QtCore.Qt.TextFormat.PlainText:
            raise RuntimeError("why: a deck's name must be plain text")
        dlg.rows[0][1].click()
        if fixed[-1]["label"] != "Unsuspend them" or dlg.rows[0][1].isEnabled():
            raise RuntimeError("why: the fix runs once")
        dlg.show_groups(gs[3:4])
        if len(dlg.rows) != 1 or dlg.note.isVisible():
            raise RuntimeError("why: read again after a fix")
        dlg.close()

    def held():
        # 3.8.1: the plan's ··· menu › Held back: N cards…: what it holds, by date, and why; Open them,
        # Stop holding back (only with a yes to Hold back), Close. The plan's and dates' names stay text
        from due_crew.ui.held_dialog import HeldDialog
        view = {"name": "MS2 <b>Block</b> 1", "n": 1240, "more": 9, "holding": True, "leeches": 2,
                "lines": ["Renal physiology <i> · Mon 19 Oct · 120", "Antiarrhythmics · Tue 20 Oct · 80",
                          "Heart failure · Wed 21 Oct · 96", "On no date now · 4"],
                "why": "You said yes to Hold back: the new cards of dates still to come wait, suspended, till their day."}
        dlg = HeldDialog(None, view)
        settle()
        labels = dlg.findChildren(QtWidgets.QLabel)
        if any(w.textFormat() != QtCore.Qt.TextFormat.PlainText for w in labels):
            raise RuntimeError("held: a plan's or date's name went in as markup")
        if not any("MS2 <b>Block</b> 1 holds back 1,240 cards" == w.text() for w in labels) or "and 9 more dates" not in dlg.list.text():
            raise RuntimeError(f"held: {[w.text() for w in labels]!r}")
        if "2 more are leeches and stay shut" not in dlg.note.text() or dlg.stop_btn.isHidden():
            raise RuntimeError(f"held: {dlg.note.text()!r}")
        shoot(dlg, os.path.join(out, "plan-held.png"))
        dlg = HeldDialog(None, dict(view, holding=False, leeches=0, more=0, lines=view["lines"][:1],
                                    why="You put these back. They open when you open their date again."))
        dlg.show()
        if dlg.stop_btn.isVisible() or "leech" in dlg.note.text():
            raise RuntimeError("held: no yes, no Stop holding back")
        dlg.open_btn.click()
        if dlg.choice != "open":
            raise RuntimeError(f"held: {dlg.choice!r}")
        shoot(HeldDialog(None, dict(view, holding=False, leeches=0, more=0, lines=view["lines"][:1],
                                    why="You put these back. They open when you open their date again.")),
              os.path.join(out, "plan-held-put-back.png"))

    def away():
        # 3.8.1: Welcome back, before the morning opens dates from days with nothing studied
        from due_crew.ui.away_dialog import AwayDialog, days_words
        dlg = AwayDialog(None, "MS2 <i>Block</i> 1", ["2026-10-05", "2026-10-06", "2026-10-07"], 4, 240, sev=True)
        settle()
        # 3.8.1: Pip waves from its corner (still), in the accent: its forehead's pixel says QtSvg drew it
        from due_crew.ui import accent
        if dlg.sev is None:
            raise RuntimeError("away: no Pip with Pip on")
        img = dlg.sev.pixmap().toImage()
        k = img.width() / 64
        if img.pixelColor(int(32 * k), int(30 * k)).name() != accent():
            raise RuntimeError(f"away: Pip isn't in the accent: {img.pixelColor(int(32 * k), int(30 * k)).name()}")
        labels = dlg.findChildren(QtWidgets.QLabel)
        if any(w.textFormat() != QtCore.Qt.TextFormat.PlainText for w in labels):
            raise RuntimeError("away: the plan's name went in as markup")
        if (dlg.push_btn.text() != "Push my dates back 3 days"
                or "3 days with no study in Anki: Mon 5 Oct, Tue 6 Oct and Wed 7 Oct." not in dlg.body.text()
                or "4 dates would open now: 240 new cards." not in dlg.body.text()):
            raise RuntimeError(f"away: {dlg.push_btn.text()!r} {dlg.body.text()!r}")
        shoot(dlg, os.path.join(out, "plan-welcome-back.png"))
        plain = AwayDialog(None, "MS2 <i>Block</i> 1", ["2026-10-05", "2026-10-06", "2026-10-07"], 4, 240)
        if plain.sev is not None:
            raise RuntimeError("away: Pip with Pip off")
        shoot(plain, os.path.join(out, "plan-welcome-back-plain.png"))
        dlg = AwayDialog(None, "Cardio", [f"2026-10-{d:02d}" for d in range(5, 15)], 9, 610)
        dlg.show()
        dlg.push_btn.click()
        if dlg.choice != "push" or "between Mon 5 Oct and Wed 14 Oct" not in days_words([f"2026-10-{d:02d}" for d in range(5, 15)]):
            raise RuntimeError(f"away: {dlg.choice!r}")

    def open_cards():
        # 3.8.0: Browse › Due Crew: open its cards…: counted first, leeches stay, first in line ticked
        from due_crew.ui.open_dialog import OpenDialog
        asked = []
        dlg = OpenDialog(None, "12 Strep <b>", "#Videos › Micro › 12 Strep", {"open": 46, "already": 2, "leech": 2},
                         ["On Step 1: SLG 15, which count them"], on_open=lambda first, study: asked.append((first, study)))
        settle()
        if dlg.facts.textFormat() != QtCore.Qt.TextFormat.PlainText or "2 are leeches and stay suspended" not in dlg.facts.text():
            raise RuntimeError(f"open: {dlg.facts.text()!r}")
        shoot(dlg, os.path.join(out, "open-cards.png"))
        dlg = OpenDialog(None, None, "", {"open": 3, "already": 0, "leech": 0}, on_open=lambda first, study: asked.append((first, study)))
        dlg.show()
        dlg.first.setChecked(False)
        dlg.study_btn.click()
        if asked != [(False, True)]:
            raise RuntimeError(f"open: asked {asked!r}")
        none = OpenDialog(None, "Renal", "", {"open": 0, "already": 5, "leech": 0})
        if none.open_btn.isVisible() or none.first.isVisible():
            raise RuntimeError("open: nothing to open shows no Open")
        none.close()

    def plan_tags():
        # 3.8.0: Browse › tag for a plan: only plans I write; a tag's name from the
        # server stays text; the notes already on it can come off; it goes on a click
        from due_crew.ui.tag_dialog import TagDialog
        pid, _code = STORE.add_plan("sam", "MS2 Block 1", "Big Step 1", [
            {"id": "u1", "name": "Cardio", "opens": TODAY, "tags": ["Step1::Cardio"]}])
        STORE.plans[pid]["doc"]["tagroot"] = "MS2_Block_1"
        STORE.plans[pid]["doc"]["tags"] = [{"id": "t1", "name": "SLG 12 <b>", "notes": ["guid000001", "guid000002"]}]
        STORE.add_plan("igk", "Not mine", "Big Step 1", [{"id": "u1", "name": "Cardio", "opens": TODAY, "tags": ["Step1::Cardio"]}])
        got = []
        dlg = TagDialog(None, CLIENT, ["guid000001", "guid000003", "guid000004"], lambda *a: got.append(a), outside=lambda p: 2)
        settle()
        names = [dlg.plan.itemText(i) for i in range(dlg.plan.count())]
        if not any("MS2 Block 1" in n for n in names) or any("Not mine" in n for n in names):
            raise RuntimeError(f"tag: plans listed {names!r}")
        dlg.plan.setCurrentIndex(next(i for i, n in enumerate(names) if "MS2 Block 1" in n))
        dlg.tag.setEditText("SLG 12 <b>")
        settle(100)
        if dlg.where.textFormat() != QtCore.Qt.TextFormat.PlainText or "DueCrew::MS2_Block_1::SLG_12_<b>" not in dlg.where.text():
            raise RuntimeError(f"tag: where {dlg.where.text()!r}")
        if "2 of them aren't in Big Step 1" not in dlg.where.text():
            raise RuntimeError(f"tag: outside the deck {dlg.where.text()!r}")
        if dlg.take_btn.isHidden() or "1" not in dlg.take_btn.text():
            raise RuntimeError(f"tag: take off {dlg.take_btn.text()!r}")
        shoot(dlg, os.path.join(out, "plan-tag.png"))
        dlg = TagDialog(None, CLIENT, ["guid000005"], lambda *a: got.append(a))
        settle()
        dlg.plan.setCurrentIndex(next(i for i in range(dlg.plan.count()) if "MS2 Block 1" in dlg.plan.itemText(i)))
        dlg.tag.setEditText("SLG 14")
        dlg.show()
        dlg.add_btn.click()
        settle()
        if not got or got[-1][1] != "SLG 14" or got[-1][3] != ["guid000005"]:
            raise RuntimeError(f"tag: sent {got!r} {dlg.status.text()!r}")
        if not any(t["name"] == "SLG 14" for t in STORE.plans[pid]["doc"]["tags"]):
            raise RuntimeError("tag: the plan didn't get it")
        dlg.close()

    def remark():
        # 3.8.1: Browse › note for the plan's followers: only plans I write; the note on this
        # card there is filled in and edited (it stays one note) or taken off; names stay text
        from due_crew.ui.remark_dialog import RemarkDialog
        pid, _code = STORE.add_plan("sam", "MS2 <Block> 2", "Big Step 1", [
            {"id": "u1", "name": "Cardio", "opens": TODAY, "tags": ["Step1::Cardio"]}])
        CLIENT.plan_remark(pid, add={"card": ["guid000004", 0], "text": "The second half of the lecture"})
        done = []
        dlg = RemarkDialog(None, CLIENT, "guid000004", 0, on_done=done.append)
        settle()
        names = [dlg.plan.itemText(i) for i in range(dlg.plan.count())]
        if any("Not mine" in n for n in names) or "MS2 <Block> 2" not in dlg.plan.currentText():
            raise RuntimeError(f"remark: plans {names!r}, picked {dlg.plan.currentText()!r}")
        if dlg.text.text() != "The second half of the lecture" or dlg.remove_btn.isHidden() or dlg.save_btn.isEnabled():
            raise RuntimeError(f"remark: the note there {dlg.text.text()!r}")
        if dlg.where.textFormat() != QtCore.Qt.TextFormat.PlainText or "MS2 <Block> 2" not in dlg.where.text():
            raise RuntimeError(f"remark: where {dlg.where.text()!r}")
        shoot(dlg, os.path.join(out, "plan-remark.png"))
        dlg = RemarkDialog(None, CLIENT, "guid000004", 0, on_done=done.append)
        settle()
        dlg.text.setText("Watch the second half first")
        dlg.show()
        dlg.save_btn.click()
        settle()
        rs = STORE.plans[pid]["doc"].get("remarks") or []
        if [r["text"] for r in rs] != ["Watch the second half first"] or not done:
            raise RuntimeError(f"remark: edited {rs!r} {dlg.status.text()!r}")
        dlg = RemarkDialog(None, CLIENT, "guid000004", 0, on_done=done.append)
        settle()
        dlg.show()
        dlg.remove_btn.click()
        settle()
        if STORE.plans[pid]["doc"].get("remarks"):
            raise RuntimeError("remark: not taken off")
        dlg = RemarkDialog(None, CLIENT, "guid000003", 0)
        settle()
        if dlg.text.text() or not dlg.remove_btn.isHidden() or dlg.save_btn.isEnabled():
            raise RuntimeError("remark: a card with none starts empty, Save off")
        shoot(dlg, os.path.join(out, "plan-remark-new.png"))

    def ai_app():
        """Your AI app (planner/mcp_dialog.py): the local MCP server's switch, off;
        then on, its address, the token hidden, and the setup to copy (the shim's,
        the token in its environment; the address with the bearer header)."""
        import json as _json
        from due_crew.planner import mcp as MCP
        from due_crew.planner.mcp_dialog import AiAppDialog, SWITCH

        class AiOps:
            s = {"on": False, "running": False, "port": 0, "url": "", "token": "", "said": ""}

            def state(self):
                return dict(self.s)

            def set_on(self, on):
                self.s = (dict(self.s, on=True, running=True, port=48123, url="http://127.0.0.1:48123/mcp",
                               token=self.s["token"] or "tok-" + "x" * 28) if on
                          else dict(self.s, on=False, running=False, url=""))
                return self.state()

            def new_token(self):
                self.s = dict(self.s, token="tok-" + "y" * 28)
                return self.state()

            def setup(self, http=False):
                return MCP.setup(self.s["port"], self.s["token"], "/Users/sam/Library/Application Support/Anki2/addons21/2035408484/planner/mcp_shim.py", http=http)

        ops = AiOps()
        dlg = AiAppDialog(None, ops)
        if heading_of(dlg) != "Your AI app" or dlg.switch.text() != SWITCH or dlg.switch.isChecked() or not dlg.on_box.isHidden():
            raise RuntimeError(f"ai app: off {heading_of(dlg)!r}, {dlg.switch.isChecked()}")
        shoot(dlg, os.path.join(out, "planner-ai-app-off.png"))
        dlg = AiAppDialog(None, ops)
        dlg.show()
        dlg.switch.setChecked(True)  # as a click: set_on, then its address and token
        settle(100)
        if (dlg.on_box.isHidden() or dlg.address.text() != "http://127.0.0.1:48123/mcp"
                or dlg.token.echoMode() != QtWidgets.QLineEdit.EchoMode.Password or not dlg.setup_btn.isEnabled()):
            raise RuntimeError(f"ai app: on {dlg.address.text()!r}, {dlg.setup_btn.isEnabled()}")
        stdio = _json.loads(ops.setup())["mcpServers"]["due-crew"]
        http = _json.loads(ops.setup(http=True))["mcpServers"]["due-crew"]
        if ("--port" not in stdio["args"] or "48123" not in stdio["args"] or any(ops.s["token"] in a for a in stdio["args"])
                or stdio["env"]["DUE_CREW_MCP_TOKEN"] != ops.s["token"] or http["headers"]["Authorization"] != "Bearer " + ops.s["token"]):
            raise RuntimeError(f"ai app: the setup {stdio} {http}")
        dlg.setup_btn.click()
        if dlg.said.text() != "Setup copied." or dlg.said.textFormat() != QtCore.Qt.TextFormat.PlainText:
            raise RuntimeError(f"ai app: Copy setup said {dlg.said.text()!r}")
        shoot(dlg, os.path.join(out, "planner-ai-app-on.png"))

    def _col_texts(tree, col):
        """Every row's text in one column of a tree, its children too."""
        out = []
        for i in range(tree.topLevelItemCount()):
            top = tree.topLevelItem(i)
            out.append(top.text(col))
            out.extend(top.child(j).text(col) for j in range(top.childCount()))
        return out

    def start_window(STORE, PF, PR, P):
        """New plan from a calendar (start_window.py): empty; for everyone (labs off); a
        calendar read (plain rules' ticks, the stand-in's where they found
        nothing, a quiz and an exam); an exam's line read; What Claude would
        get; Make the plan end to end (POST /plans, then its save); prose,
        which only the stand-in reads, and with it off."""
        import sqlite3
        from due_crew.planner import reading as R
        from due_crew.planner import start_window as SW
        ROLE_ = SW.ROLE
        conn = sqlite3.connect(":memory:")
        fakes.make_collection(conn)
        root = "#Big_Step1_v3"
        cid = 0
        for tag, n in ((f"{root}::#Videos::Cardio::Heart_Failure {root}::^Systems::Cardio::Heart_Failure", 14),
                       (f"{root}::#Book::Cardio::Heart_Failure", 6), (f"{root}::#Videos::Cardio::Systolic_Dysfunction", 5),
                       (f"{root}::#Videos::Pharm::Antiarrhythmics", 8), (f"{root}::#Book::Renal::Diuretics", 6),
                       (f"{root}::#Videos::Renal::Acid_Base", 7), (f"{root}::#Bank::10234", 3)):
            for i in range(n):
                cid += 1
                fakes.add_card(conn, cid, 1, tags=tag)
        col = fakes.FakeCol(conn, fakes.day_cutoff_for(datetime.date.today()))
        col.decks = fakes.FakeDecks({1: "Big Step 1", 2: "Mine"})
        monday = datetime.date.today() + datetime.timedelta(days=7 - datetime.date.today().weekday())
        d = lambda n: (lambda x: f"{x:%a} {x.month}/{x.day}")(monday + datetime.timedelta(days=n))
        cal = (f"BLOCK 2 · Cardiovascular\nWEEK 1\n{d(0)}  LEC  Heart failure\n"
               "    SLG 1  Define systolic and diastolic heart failure\n    Watch: heart failure 1-2\n"
               f"{d(1)}  LEC  HFrEF\n{d(2)}  Holiday, no class\n{d(3)}  LEC  Antiarrhythmic drugs\n"
               f"{d(4)}  QUIZ  Cardio quiz 1\nWEEK 2\n{d(7)}  LEC  Diuretics\n{d(8)}  LEC  Acid-base\n"
               f"{d(11)}  EXAM  Exam 1\n")
        opened = []

        class SOps(PF.StartOps):
            def today(self):
                return datetime.date.today()

            def index(self, did):
                return P.DeckIndex(col, did)

            def make(self, owner, name, doc, done, pid=None):
                outcome, raw = PR.create(CLIENT, name, doc.get("deck") or "")
                done(PR.save(CLIENT, raw["id"], raw["version"], doc, "made in Anki from a calendar")
                     if outcome == "saved" else (outcome, raw))

            def open_plan(self, pid):
                opened.append(pid)

        decks = [(1, "Big Step 1", cid), (2, "Mine", 0)]
        w = SW.StartWindow(None, decks, SOps())
        if w.make_btn.isEnabled() or w.would_btn.isEnabled():
            raise RuntimeError("start: nothing read, nothing to make")
        shoot(w, os.path.join(out, "planner-start-empty.png"))
        # 3.9.3: for everyone, labs off: plain rules alone, no stand-in, no What Claude would get
        w = SW.StartWindow(None, decks, SOps(), labs=False)
        w.resize(820, 720)
        w.text.setPlainText(cal)
        w._read()
        if (w.stand_in.isVisible() or w.stand_in.isChecked() or w.would_btn.isVisible()
                or any(r in ("Claude’s stand-in",) for r in _col_texts(w.tree, 2))):
            raise RuntimeError("start: labs off shows Claude's stand-in")
        if not w.make_btn.isEnabled():
            raise RuntimeError("start: labs off, plain rules' reading can't be made")
        shoot(w, os.path.join(out, "planner-start-release.png"))

        def read(text, stand_in=True):
            w = SW.StartWindow(None, decks, SOps())
            w.resize(820, 720)
            w.text.setPlainText(text)
            w.stand_in.setChecked(stand_in)
            w._read()
            return w
        w = read(cal)
        rows = {w.tree.topLevelItem(i).text(0).split(" · ", 1)[1]: w.tree.topLevelItem(i)
                for i in range(w.tree.topLevelItemCount())}
        picks = {w.sessions[i]["title"]: v for i, v in w.picks().items()}
        if (w.name.text() != "BLOCK 2 · Cardiovascular" or len(w.sessions) != 7
                or picks["Heart failure"] != [f"{root}::#Book::Cardio::Heart_Failure", f"{root}::#Videos::Cardio::Heart_Failure"]
                or picks["HFrEF"] != [f"{root}::#Videos::Cardio::Systolic_Dysfunction"]
                or picks["Antiarrhythmic drugs"] != [f"{root}::#Videos::Pharm::Antiarrhythmics"]
                or rows["HFrEF"].text(2) != "Claude’s stand-in" or rows["Heart failure"].text(2) != "plain rules"
                or "Cardio quiz 1 (quiz)" not in rows or "Exam 1 (exam)" not in rows or not w.make_btn.isEnabled()):
            raise RuntimeError(f"start: read {w.name.text()!r} {picks} {sorted(rows)}")
        shoot(w, os.path.join(out, "planner-start-read.png"))
        w = read(cal)
        exam = next(w.tree.topLevelItem(i) for i in range(w.tree.topLevelItemCount())
                    if w.tree.topLevelItem(i).text(0).endswith("(exam)"))
        w.tree.setCurrentItem(exam)
        saved = SW.ask_text
        SW.ask_text = lambda *a, **k: ("Exam 1 covers week 1 and week 2's renal lectures", True)
        try:
            w._scope()
        finally:
            SW.ask_text = saved
        covered = sorted(w.sessions[i]["title"] for i in next(iter(w.scopes.values()))[0])
        said = [exam.child(i).text(2) for i in range(exam.childCount())]
        if covered != ["Acid-base", "Antiarrhythmic drugs", "Diuretics", "HFrEF", "Heart failure"] or said[:2] != [
                "plain rules", "Claude’s stand-in"]:
            raise RuntimeError(f"start: the exam's line {covered} {said}")
        shoot(w, os.path.join(out, "planner-start-scope.png"))
        jobs = [r["job"] for r in w.would_get()]
        tags = [[t["tag"] for t in r["input"]["tags"]] for r in w.would_get()[:2]]
        if (jobs != ["Match a session to the deck's tags"] * 2 + ["What an exam covers"]
                or f"{root}::#Videos::Cardio::Systolic_Dysfunction" not in tags[0]
                or f"{root}::#Videos::Pharm::Antiarrhythmics" not in tags[1]):
            raise RuntimeError(f"start: what Claude would get {jobs} {tags}")
        dlg = w.would_window()
        dlg.resize(680, 560)
        shoot(dlg, os.path.join(out, "planner-start-would.png"))
        saved = SW.confirm
        SW.confirm = lambda *a, **k: True
        try:
            w.show()
            w._make()
        finally:
            SW.confirm = saved
        plan = STORE.plans.get(opened[-1]) if opened else None
        if (not plan or plan["name"] != "BLOCK 2 · Cardiovascular" or len(plan["doc"]["units"]) != 5
                or [e["name"] for e in plan["doc"]["events"]] != ["Cardio quiz 1", "Exam 1"]
                or {u["name"]: u.get("for") for u in plan["doc"]["units"]}["Diuretics"] != plan["doc"]["events"][1]["id"]):
            raise RuntimeError(f"start: Make the plan {plan and plan['doc']}")
        w.close()
        prose = (f"We meet on {(monday):%b} {monday.day} for heart failure.\n"
                 f"The cardio quiz is on {(monday + datetime.timedelta(days=4)):%b} {(monday + datetime.timedelta(days=4)).day}.")
        w = read(prose)
        if w.name.text() or [x["title"] for x in w.sessions] != ["Heart failure", "Cardio quiz"] or w.head.text() != "Calendar read by Claude’s stand-in":
            raise RuntimeError(f"start: prose {w.sessions} {w.head.text()!r}")
        shoot(w, os.path.join(out, "planner-start-prose.png"))
        w = read(prose, stand_in=False)
        if w.sessions or w.name.text() or "stand-in could" not in w.said.text():
            raise RuntimeError(f"start: prose, stand-in off: {w.said.text()!r}")
        shoot(w, os.path.join(out, "planner-start-none.png"))
        # a calendar's file dragged over the box, then dropped: a PDF, made here as a school's would be
        pdf = os.path.join(tempfile.mkdtemp(), "MS2_Block_2 calendar.pdf")
        writer = QtGui.QPdfWriter(pdf)
        writer.setResolution(96)
        painter = QtGui.QPainter(writer)
        painter.setFont(QtGui.QFont("DejaVu Sans", 11))
        rows = [("Week 1", "", ""), (d(0), "Heart failure", "Room B2"), (d(1), "HFrEF", "Room B2"),
                (d(3), "Antiarrhythmic drugs", "Room B4"), (d(4), "Cardio quiz 1", "Hall A"), ("Week 2", "", ""),
                (d(7), "Diuretics", "Room B2"), (d(11), "Exam 1", "Hall A")]
        # a row a line: three cells each drawn alone came out of Qt's reader a letter a line in 41 weeks
        # of a year (the scrambled case, which the window rightly turns down), so this passed by the date
        for n, row in enumerate(rows):
            painter.drawText(40, 60 + 24 * n, "    ".join(t for t in row if t))
        painter.end()
        w = SW.StartWindow(None, decks, SOps())
        w.resize(820, 720)
        mime = QtCore.QMimeData()
        mime.setUrls([QtCore.QUrl.fromLocalFile(pdf)])
        if SW.DropBox.path_of(mime) != pdf:
            raise RuntimeError("start: a dragged file's path")
        two = QtCore.QMimeData()
        two.setUrls([QtCore.QUrl.fromLocalFile(pdf), QtCore.QUrl.fromLocalFile(pdf + "2")])
        if SW.DropBox.path_of(two) is not None:
            raise RuntimeError("start: two files at once are dropped as nothing")
        enter = QtGui.QDragEnterEvent(QtCore.QPoint(20, 20), QtCore.Qt.DropAction.CopyAction, mime,
                                      QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.KeyboardModifier.NoModifier)
        w.text.dragEnterEvent(enter)
        if not enter.isAccepted() or w.text.property("over") is not True:
            raise RuntimeError("start: a file over the box")
        w.show()
        settle()
        w.grab().save(os.path.join(out, "planner-start-drag.png"))
        drop = QtGui.QDropEvent(QtCore.QPointF(20, 20), QtCore.Qt.DropAction.CopyAction, mime,
                                QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.KeyboardModifier.NoModifier)
        w.text.dropEvent(drop)
        titles = [x["title"] for x in w.sessions]
        if (w.text.property("over") is not False or w.file != os.path.basename(pdf) or w.name.text() != "MS2 Block 2 calendar"
                or titles != ["Heart failure", "HFrEF", "Antiarrhythmic drugs", "Cardio quiz 1", "Diuretics", "Exam 1"]
                or [x["week"] for x in w.sessions] != [1, 1, 1, 1, 2, 2]):
            raise RuntimeError(f"start: the PDF dropped {w.name.text()!r} {titles} {w.text.toPlainText()!r}")
        shoot(w, os.path.join(out, "planner-start-dropped.png"))
        bits = os.path.join(tempfile.mkdtemp(), "bits.pdf")
        writer = QtGui.QPdfWriter(bits)
        writer.setResolution(96)
        painter = QtGui.QPainter(writer)
        painter.drawText(40, 60, "Mon 10/26 Heart failure")  # no font: Qt reads it back a letter a line
        painter.end()
        w = SW.StartWindow(None, decks, SOps())
        w._load_file(bits)
        if SW.pdf_text(bits) and not R.scrambled(SW.pdf_text(bits)):
            pass  # this Qt reads it whole: nothing to say
        elif w.sessions or "pieces" not in w.said.text():
            raise RuntimeError(f"start: a PDF read in pieces: {w.said.text()!r}")
        # a lecture's slides dropped on its session's row: its objectives and its slides' titles find its tags
        import zipfile
        from xml.sax.saxutils import escape
        deck = os.path.join(tempfile.mkdtemp(), "Renal 4 - Diuretics.pptx")
        ns = ('xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
              'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
              'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')
        slides = [("Diuretics", []), ("Learning objectives", ["Describe the site of action of loop diuretics",
                                                              "Explain the acid-base effects of thiazides"]),
                  ("Loop diuretics", ["Furosemide"]), ("Acid-base effects", []), ("Questions?", [])]
        with zipfile.ZipFile(deck, "w") as z:
            for n, (title, body) in enumerate(slides, 1):
                sp = (f'<p:sp><p:nvSpPr><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr><p:txBody><a:p><a:r><a:t>{escape(title)}'
                      '</a:t></a:r></a:p></p:txBody></p:sp>')
                sp += "<p:sp><p:nvSpPr><p:nvPr/></p:nvSpPr><p:txBody>" + "".join(
                    f"<a:p><a:r><a:t>{escape(t)}</a:t></a:r></a:p>" for t in body) + "</p:txBody></p:sp>"
                z.writestr(f"ppt/slides/slide{n}.xml", f'<p:sld {ns}><p:cSld><p:spTree>{sp}</p:spTree></p:cSld></p:sld>')
            z.writestr("ppt/presentation.xml", f'<p:presentation {ns}><p:sldIdLst>' + "".join(
                f'<p:sldId id="{256 + n}" r:id="rId{n}"/>' for n in range(1, len(slides) + 1)) + "</p:sldIdLst></p:presentation>")
            z.writestr("ppt/_rels/presentation.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
                       '2006/relationships">' + "".join(f'<Relationship Id="rId{n}" Target="slides/slide{n}.xml"/>'
                                                       for n in range(1, len(slides) + 1)) + "</Relationships>")
        w = read(cal)
        row = next(w.tree.topLevelItem(i) for i in range(w.tree.topLevelItemCount())
                   if w.tree.topLevelItem(i).text(0).endswith("Diuretics"))
        di = row.data(0, ROLE_)[1]
        w.show()
        settle()
        w.tree.scrollToItem(row)
        at = QtCore.QPointF(w.tree.visualItemRect(row).center())
        dmime = QtCore.QMimeData()
        dmime.setUrls([QtCore.QUrl.fromLocalFile(deck)])
        move = QtGui.QDragMoveEvent(at.toPoint(), QtCore.Qt.DropAction.CopyAction, dmime,
                                    QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.KeyboardModifier.NoModifier)
        w.tree.dragMoveEvent(move)
        if not move.isAccepted() or w.tree.currentItem() is not row:
            raise RuntimeError("start: a deck over a session's row")
        w.tree.dropEvent(QtGui.QDropEvent(at, QtCore.Qt.DropAction.CopyAction, dmime,
                                          QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.KeyboardModifier.NoModifier))
        s_ = w.sessions[di]
        tags_ = [c["tag"] for c in w.cands[di]]
        if (s_.get("slides") != ["Loop diuretics", "Acid-base effects"] or len(s_["objectives"]) != 2
                or f"{root}::#Videos::Renal::Acid_Base" not in tags_ or "with its slides" not in w.who[di][1]
                or "2 slide titles and 2 objectives" not in w.said.text()
                or w.tree.currentItem() is None or w.tree.currentItem().data(0, ROLE_) != ("session", di)
                or not w.slides_btn.isEnabled()):
            raise RuntimeError(f"start: slides onto a session {s_} {tags_} {w.who[di]} {w.said.text()!r}")
        shoot(w, os.path.join(out, "planner-start-slides.png"))
        w = SW.StartWindow(None, decks, SOps())
        sheet = os.path.join(tempfile.mkdtemp(), "block.xlsx")
        with open(sheet, "wb") as f:
            f.write(b"PK")
        w._load_file(sheet)
        if "CSV" not in w.said.text() or w.text.toPlainText():
            raise RuntimeError(f"start: a sheet: {w.said.text()!r}")

    def planner():
        """Labs (due_crew/planner, docs/planner.md): the plan window an author
        sees (a date's sources by resource, system and other, with what each
        holds here; a week; an event; Change ▾), a change saved end to end,
        the picker (the deck's tree, then a search), and QBank QIDs (a paste
        found across two banks, Study now, then Unsuspend: one undo step).
        Names are the author's: plain text."""
        import sqlite3
        from due_crew import plans as P
        from due_crew.planner import actions as PA, flow as PF, remote as PR
        from due_crew.planner.picker import Picker
        from due_crew.planner.qid_window import QidWindow
        from due_crew.planner.window import PlanWindow
        conn = sqlite3.connect(":memory:")
        fakes.make_collection(conn)
        root = "#Big_Step1_v3"
        tags = [(f"{root}::#Videos::Cardio::Heart_Failure {root}::^Systems::Cardio::Heart_Failure", 14),
                (f"{root}::#Book::Cardio::Heart_Failure", 6), (f"{root}::#Videos::Pharm::HF_Drugs", 9),
                (f"{root}::#Sketches::Pharm::HF_Drugs", 4), (f"{root}::#Videos::Cardio::Shock", 7),
                ("Pharm::Antibiotics", 3)]
        cid = 0
        for tag, n in tags:
            for i in range(n):
                cid += 1
                fakes.add_card(conn, cid, 1, ctype=2 if i % 3 == 0 else 0, queue=-1 if i % 4 == 1 else (2 if i % 3 == 0 else 0),
                               ivl=9, tags=tag)
        for q, n, on in ((10234, 2, "^Systems::Cardio::Heart_Failure"), (10911, 1, "^Systems::Cardio::Shock"),
                         (11002, 1, "^Systems::Renal::AKI"), (12118, 2, "^Systems::Cardio::Heart_Failure")):
            for i in range(n):
                cid += 1
                fakes.add_card(conn, cid, 1, ctype=2 if i else 0, queue=-1, ivl=6,
                               tags=f"{root}::#Bank::{q} {root}::{on} {root}::#Videos::Cardio::Heart_Failure" if "Heart" in on
                               else f"{root}::#Bank::{q} {root}::{on}")
        cid += 1
        fakes.add_card(conn, cid, 1, tags=f"{root}::#Other_Bank::10234")
        col = fakes.FakeCol(conn, fakes.day_cutoff_for(datetime.date.today()))
        col.decks = fakes.FakeDecks({1: "Big Step 1", 3: "Big Step 1::Cardio"})
        monday = datetime.date.today() - datetime.timedelta(days=datetime.date.today().weekday())
        day = lambda n: (monday + datetime.timedelta(days=n)).isoformat()
        units = [{"id": "u1", "name": "Heart failure", "opens": day(0), "due": day(2),
                  "tags": [f"{root}::#Videos::Cardio::Heart_Failure", f"{root}::^Systems::Cardio::Heart_Failure",
                           f"{root}::#Bank::10234", f"{root}::#Bank::10911"],
                  "todo": [{"k": "watch", "t": "Heart failure 1–2"}, {"k": "read", "t": "pp. 290–295"}], "for": "e1"},
                 {"id": "u2", "name": "HF drugs <b>", "opens": day(1), "tags": [f"{root}::#Videos::Pharm::HF_Drugs"]},
                 {"id": "u3", "name": "Shock", "opens": day(3), "tags": [f"{root}::#Videos::Cardio::Shock"]},
                 {"id": "u4", "name": "Antibiotics", "opens": day(-7), "tags": ["Pharm::Antibiotics"]}]
        pid, _code = STORE.add_plan("sam", "MS2 Block 2", "Big Step 1", units)
        STORE.plans[pid]["doc"]["events"] = [{"id": "e1", "day": day(4), "name": "Heme quiz"}]
        next(u for u in STORE.plans[pid]["doc"]["units"] if u["id"] == "u1")["for"] = "e1"  # add_plan drops a `for` with no event yet

        class Ops(PF.Ops):
            """The window's asks, on this render's collection and client, at once."""
            def today(self):
                return TODAY

            def context(self, plan, doc):
                return P.DeckIndex(col, 1), None, "named"

            def followed_here(self, pid, version=None):
                return False

            def load(self, owner, pid, done):
                done(PR.load(CLIENT, pid))

            def save(self, owner, pid, version, doc, summary, done):
                done(PR.save(CLIENT, pid, version, doc, summary))

            def undo(self, owner, pid, version, done):
                done(PR.undo(CLIENT, pid, version))

            def open_page(self, path):
                pass

            def me(self):
                return CLIENT.user_id

            def ask(self, owner, fn, done):
                try:
                    got = fn(CLIENT)
                except Exception:  # noqa: BLE001 (the real one's _bg says None)
                    got = None
                done(got)

            def my_squads(self):
                return [{"id": "sq1", "name": "Study buddies"}]

            drafts = {}   # this render's plan_drafts.json

            def draft(self, pid):
                from due_crew.planner.draft import Draft
                return Draft.from_json(pid, self.drafts.get(str(pid)))

            def keep_draft(self, pid, d):
                if d is None or not len(d):
                    self.drafts.pop(str(pid), None)
                else:
                    self.drafts[str(pid)] = json.loads(json.dumps(d.to_json()))

            def send(self, owner, pid, version, doc, summary, post, done):
                done(PR.save(CLIENT, pid, version, doc, summary, post))

            def now_words(self):
                return "Tue 2:14 pm"

            def site_url(self, path):
                return "https://duecrew.com" + path

            def my_doc(self, plan):
                return plan["doc"]

            def follow_plan(self):
                reopened.append("follow")

            def new_plan(self):
                reopened.append("new")

            def reopen(self, pid):
                reopened.append(pid)

        import json
        from due_crew.planner import plan_tab as PTB, send as PS, shape as PSH, text_tab as PT, widgets as PW, model as M_
        from due_crew.planner import ops as PO
        reopened = []
        mine = PR.my_plans(CLIENT)

        def PlanWindow_(plans=mine):
            w = PlanWindow(None, col, plans, Ops())
            if plans:
                w.pick.setCurrentIndex(w.pick.findData(pid))  # earlier renders left plans of Sam's in the store
            return w

        def unit(uid):
            return next(u for u in STORE.plans[pid]["doc"]["units"] if u["id"] == uid)

        yes = lambda *a, **k: True  # noqa: E731 (a confirm said yes to)
        dlg = PlanWindow_()
        tab = dlg.pages["plan"]
        shown = [dlg.tabs.tabText(i) for i in range(dlg.tabs.count()) if dlg.tabs.isTabVisible(i)]
        if not dlg.pick.currentText().startswith("MS2 Block 2") or not dlg.author() or shown != ["Plan", "Insights", "Settings"]:
            raise RuntimeError(f"planner: an author's tabs {shown}, {dlg.pick.currentText()!r}")
        dlg.resize(1180, 760)
        tab.pick(("date", "u1"))
        dp = tab.date_panel
        chips = [c.words.full for c in dp.chips.findChildren(PW.Source)]
        if "Videos › Cardio › Heart Failure" not in chips or not any(c.startswith("Systems") for c in chips) \
                or not any(c.startswith("Bank") for c in chips) or dp.name.text() != "Heart failure":
            raise RuntimeError(f"planner: the date's chips {chips}, {dp.name.text()!r}")
        shape = [w.text() for w in tab.shape_fields.findChildren(QtWidgets.QLabel)]
        if tab.shape_box.isHidden() or "Dates" not in shape or "Study days" not in shape or not tab.send_box.isHidden():
            raise RuntimeError(f"planner: the shape line {shape}")
        if [w for w in dlg.findChildren(QtWidgets.QLabel) if w.pixmap() is not None and not w.pixmap().isNull()]:
            raise RuntimeError("planner: Pip in the plan window (round five: none)")
        shoot(dlg, os.path.join(out, "planner-date.png"))
        # Insights, between Plan and Settings: what each week asks, how much of the deck, what's in it
        dlg._show_tab("insights")
        it = dlg.pages["insights"]
        said = [w.text() for w in it.findChildren(QtWidgets.QLabel) if w.isVisibleTo(it)]
        if "Workload" not in said or "How much of the deck" not in said or "What's in it" not in said \
                or not any(" cards (" in t for t in said) or not any(t.startswith("Week 1") for t in said) \
                or any(t.startswith("You've seen") for t in said) or not any(t.startswith("By ") for t in said) \
                or "Inside Cardio" not in said:
            raise RuntimeError(f"planner: Insights {said}")
        shoot(dlg, os.path.join(out, "planner-insights.png"))
        it.body.grab().save(os.path.join(out, "planner-insights-all.png"))  # the whole of it, to look at
        kept_doc = dlg.doc  # a pace of 5 a day, weekdays: the pace's line down the column, a week over it
        dlg.doc = dict(kept_doc, pace={"mode": "daily", "days": [1, 1, 1, 1, 1, 0, 0], "daily": 5})
        it.draw()
        said = [w.text() for w in it.findChildren(QtWidgets.QLabel) if w.isVisibleTo(it)]
        if not any(t.startswith("Over the pace") for t in said) or not any("your pace: 5" in t for t in said) \
                or not any("busiest day" in t for t in said):
            raise RuntimeError(f"planner: Insights with a pace {said}")
        it.body.grab().save(os.path.join(out, "planner-insights-pace.png"))
        dlg.doc = kept_doc
        it.draw()
        picks = [r for r in it.findChildren(PW.Row) if r.key[0] == "date"]
        picks[0].on_pick(picks[0].key)
        if dlg.tabs.currentWidget() is not tab or tab.picked != picks[0].key:
            raise RuntimeError(f"planner: a date picked in Insights, on the Plan tab: {tab.picked}")
        tab.pick(("date", "u2"))
        if dp.name.text() != "HF drugs <b>" or tab.rows[("date", "u2")].findChildren(QtWidgets.QLabel)[1].textFormat() \
                != QtCore.Qt.TextFormat.PlainText:
            raise RuntimeError("planner: a date's name went in as markup")
        # nobody follows it: a change saves at once, and Undo ▾ takes it back
        dlg.change({"op": "add_cards", "date": "u2", "tags": [f"{root}::#Sketches::Pharm::HF_Drugs"]})
        u2 = unit("u2")
        if (STORE.plans[pid]["version"] != 2 or u2["tags"][-1] != f"{root}::#Sketches::Pharm::HF_Drugs" or u2.get("n") != 13
                or not dlg.status.text().startswith("Saved") or tab.picked != ("date", "u2") or dlg.draft is not None):
            raise RuntimeError(f"planner: a change saved: v{STORE.plans[pid]['version']}, {u2}, {dlg.status.text()!r}")
        shoot(dlg, os.path.join(out, "planner-saved.png"))
        dlg.change({"op": "add_cards", "date": "u2", "tags": [f"{root}::#Sketches::Pharm::HF_Drugs"]})
        if STORE.plans[pid]["version"] != 2 or "has those already" not in dlg.status.text():
            raise RuntimeError(f"planner: the same change again saves nothing: {dlg.status.text()!r}")
        dlg._undo_entries()
        if not [a for a in dlg.undo_menu.actions() if a.text() == "Undo your last save"]:
            raise RuntimeError(f"planner: Undo ▾ {[a.text() for a in dlg.undo_menu.actions()]}")
        dlg._undo()
        if STORE.plans[pid]["version"] != 3 or f"{root}::#Sketches::Pharm::HF_Drugs" in unit("u2")["tags"] or dlg.status.text() != "Undone.":
            raise RuntimeError(f"planner: Undo: v{STORE.plans[pid]['version']}, {dlg.status.text()!r}")
        STORE.plans[pid]["version"] += 1  # someone saves on the site meanwhile: the window's next change goes on theirs
        dlg.change({"op": "rename", "date": "u2", "name": "HF drugs"})
        if unit("u2")["name"] != "HF drugs" or not dlg.status.text().startswith("Saved"):
            raise RuntimeError(f"planner: a stale save, put on theirs: {dlg.status.text()!r}")
        # a new date named for a deck tag: nothing suggested (Sam's call); no cards till the author puts them on
        dlg.change({"op": "add_date", "day": day(5), "name": "Heart failure book"}, keep="made")
        made = next(u for u in STORE.plans[pid]["doc"]["units"] if u.get("name") == "Heart failure book")
        said = [w.text() for w in tab.findChildren(QtWidgets.QLabel) if w.isVisibleTo(tab)]
        if tab.picked != ("date", made["id"]) or any(t.startswith("Maybe") for t in said) or hasattr(tab, "sure_box") \
                or "No cards yet" not in said:
            raise RuntimeError(f"planner: a new date, nothing suggested: picked {tab.picked}, {said}")
        shoot(dlg, os.path.join(out, "planner-date-new.png"))
        dlg.change({"op": "add_cards", "date": made["id"], "tags": [f"{root}::#Book::Cardio::Heart_Failure"]}, keep=("date", made["id"]))
        if unit(made["id"]).get("tags") != [f"{root}::#Book::Cardio::Heart_Failure"]:
            raise RuntimeError(f"planner: cards put on a new date: {unit(made['id'])}")
        # the plan's dates and pace: rows of Settings (round five: no Change… window); the Plan tab's line only reads
        if hasattr(tab, "shape_btn") or hasattr(PSH, "ShapeDialog"):
            raise RuntimeError("planner: the shape is Settings' (no Change…)")
        dlg._show_tab("sharing")
        sh = dlg.pages["sharing"].shape
        if not sh.preview.isHidden():
            raise RuntimeError("planner: Settings' shape, nothing changed: nothing to save")
        sh.mode.button(0).click()  # Up to N a day
        sh.daily.setValue(25)
        sh.ends.setCurrentIndex(sh.ends.findText("A day…"))
        sh.end_day.setDate(QtCore.QDate.fromString(day(30), "yyyy-MM-dd"))
        sh.taper.setValue(2)
        ops_ = sh.ops()
        if [o["op"] for o in ops_] != ["set_end", "set_pace", "set_phases"] or sh.go.text() != "Save" \
                or "no new cards" not in sh.preview_words.text():
            raise RuntimeError(f"planner: Settings' shape {ops_}, {sh.go.text()!r}")
        shoot(dlg, os.path.join(out, "planner-settings-shape.png"))
        sh.start.setDate(sh.start.date().addDays(7))
        if not sh.ops() or sh.ops()[0] != {"op": "shift_all", "days": 7} or "Saving moves" not in sh.preview_words.text():
            raise RuntimeError(f"planner: Settings' shape, the start: {sh.ops()}, {sh.preview_words.text()!r}")
        sh.load()  # Put it back
        if sh.ops() or not sh.preview.isHidden():
            raise RuntimeError("planner: Settings' shape, Put it back")
        dlg._show_tab("plan")
        # no deck tab: Add from the deck puts the deck in the date's place, ticks adding to it; Done, the date again
        if tab.side.count() != 2 or isinstance(tab.side, QtWidgets.QTabWidget):
            raise RuntimeError("planner: the side is the date, or the deck while cards go on (no tabs)")
        tab.tick_for("u3")
        if tab.deck.bar.isHidden() or "Shock" not in tab.deck.bar_words.text() or tab.side.currentWidget() is not tab.deck:
            raise RuntimeError("planner: Add from the deck")
        shoot(dlg, os.path.join(out, "planner-deck-date.png"))
        tab.deck._back()
        if tab.side.currentWidget() is not tab.side_page or tab.picked != ("date", "u3"):
            raise RuntimeError("planner: the deck's Done: the date again")
        tab.lay_out_view()  # Add › Lay out from the deck…
        if tab.side.currentWidget() is not tab.deck or tab.deck.target is not None:
            raise RuntimeError("planner: Lay out from the deck")
        # a search keeps the tags' structure: what's found under the tags above it, a line of one-way tags one row
        deck = tab.deck
        deck.find.setText("heart failure")
        deck._typing.stop()
        deck.fill_tree()
        top = deck.tree.topLevelItem(0)
        kids = [top.child(i).text(0) for i in range(top.childCount())] if top else []
        if deck.tree.topLevelItemCount() != 1 or top.text(0) != "Big Step 1" or not top.isExpanded() \
                or kids != ["Book › Cardio › Heart Failure", "Videos › Cardio › Heart Failure"] or deck.cover:
            raise RuntimeError(f"planner: the deck's search, kept as a tree: {top and top.text(0)!r} {kids}, {deck.cover}")
        shoot(dlg, os.path.join(out, "planner-deck-search.png"))
        deck.view_btns["system"].click()  # a view button narrows the search to its tags
        top = deck.tree.topLevelItem(0)
        if deck.tree.topLevelItemCount() != 1 or top.text(0) != "Big Step 1 › Systems › Cardio › Heart Failure":
            raise RuntimeError(f"planner: the search by system: {top and top.text(0)!r}")
        deck.find.setText("sketches")
        deck._typing.stop()
        deck.fill_tree()
        rows = [deck.tree.topLevelItem(i).text(0) for i in range(deck.tree.topLevelItemCount())]
        if rows != ["Nothing here has \u201csketches\u201d.", "By resource has 1"]:
            raise RuntimeError(f"planner: nothing by system: {rows}")
        deck.more_btn.setChecked(True)  # a click opens More's menu and ticks it: only its own views tick it
        if deck.more_btn.isChecked() or not deck.view_btns["system"].isChecked():
            raise RuntimeError("planner: More ticked while By system shows")
        deck._clicked(deck.tree.topLevelItem(1), 0)
        if deck.view != "resource" or deck.tree.topLevelItem(0).text(0) != "Big Step 1 › Sketches":
            raise RuntimeError(f"planner: By resource has 1: {deck.view}")
        tab.deck.find.setText("#sketches")
        tab.deck._typing.stop()
        tab.deck.fill_tree()
        it = tab.deck.tree.topLevelItem(0)
        it.setCheckState(0, QtCore.Qt.CheckState.Checked)
        if tab.deck.cover != {f"tag:{root}::#Sketches"} or tab.deck.go.isHidden() or "ticked, not on a date" not in tab.deck.fill_words.text():
            raise RuntimeError(f"planner: the deck's ticks {tab.deck.cover}, {tab.deck.fill_words.text()!r}")
        shoot(dlg, os.path.join(out, "planner-deck-fill.png"))
        tab.deck._lay(tab.deck._go_how)
        if not any(u.get("tags") == [f"{root}::#Sketches"] for u in STORE.plans[pid]["doc"]["units"]):
            raise RuntimeError(f"planner: Lay them out: {dlg.status.text()!r}")
        tab.back_from_deck()
        # the text: plan lines pasted in, read, then added; the whole plan as text
        td = PT.TextDialog(dlg, False, f"{day(6)} | Shock again | tag:{root}::#Videos::Cardio::Shock | read: chapter 9\n"
                                      f"{day(4)} | event | Shock quiz")
        if td.tab.go_btn.isHidden() or td.tab.go_btn.text() != "Add to the plan" or "1 date, 1 quiz or exam." not in td.tab.status.text():
            raise RuntimeError(f"planner: plan lines read: {td.tab.status.text()!r}")
        shoot(td, os.path.join(out, "planner-text-add.png"))
        td.tab._go()
        if not any(u.get("name") == "Shock again" for u in STORE.plans[pid]["doc"]["units"]) or td.result() != 1:
            raise RuntimeError(f"planner: plan lines added: {td.tab.status.text()!r}")
        td = PT.TextDialog(dlg, True)
        if not any("| Shock again |" in x for x in td.tab.box.toPlainText().split("\n")):
            raise RuntimeError("planner: the whole plan as text")
        shoot(td, os.path.join(out, "planner-text-whole.png"))
        # a course calendar pasted in: its sessions as dates, its quiz as a quiz
        tab.paste.setPlainText(f"WEEK 3\n{P.fmt_day(day(8))}  LEC  Arrhythmias\n{P.fmt_day(day(9))}  QUIZ  Cardio quiz 2")
        was = PTB.confirm
        PTB.confirm = yes
        try:
            tab._show_changes()
        finally:
            PTB.confirm = was
        doc = STORE.plans[pid]["doc"]
        if not any(u.get("name") == "Arrhythmias" for u in doc["units"]) or not any(e.get("name") == "Cardio quiz 2" for e in doc["events"]) \
                or tab.paste.toPlainText():
            raise RuntimeError(f"planner: a calendar pasted: {dlg.status.text()!r}")
        # with people following: changes wait under the plan, Review and send is one save with its line
        for who, prog in (("kai", {"u4": [1, 1, 1], "u1": [1, 1, 2]}), ("dre", {"u4": [1, 0, 3]}), ("lee", {"u4": [1, 0, 3], "u1": [1, 0, 2]})):
            STORE.follows[(pid, who)] = {"share": True, "paused": False, "sched": None, "progress": json.dumps(prog)}
        STORE.follows[(pid, "mo")] = {"share": False, "paused": False, "sched": None, "progress": None}
        dlg._load()
        v = STORE.plans[pid]["version"]
        tab.pick(("date", "u3"))
        dp._nudge(1)
        dlg.change({"op": "set_todo", "date": "u3", "lines": [{"k": "watch", "t": "Shock, part 2"}]})
        if STORE.plans[pid]["version"] != v or not dlg.draft or len(dlg.draft) != 2 or tab.send_box.isHidden() \
                or "2 changes not sent" not in tab.send_words.text() or 'href="u3"' not in tab.send_words.text() \
                or unit("u3")["opens"] != day(3):
            raise RuntimeError(f"planner: changes wait: {tab.send_words.text()!r}, v{STORE.plans[pid]['version']}")
        shoot(dlg, os.path.join(out, "planner-waiting.png"))
        sd = PS.SendDialog(dlg)
        if not sd.why().startswith("Shock moved") or sd.go.text() != "Send to 4" or "Not open for anyone yet" not in \
                " ".join(w.text() for w in sd.findChildren(QtWidgets.QLabel)):
            raise RuntimeError(f"planner: Review and send: {sd.why()!r}, {sd.go.text()!r}")
        shoot(sd, os.path.join(out, "planner-send.png"))
        dlg.send(sd.why() + " The school moved the lecture.")
        if STORE.plans[pid]["version"] != v + 1 or unit("u3")["opens"] != day(4) or dlg.draft is not None \
                or not dlg.status.text().startswith("Sent to 4") or not STORE.plan_posts.get(pid):
            raise RuntimeError(f"planner: Send: v{STORE.plans[pid]['version']} (was {v}), u3 {unit('u3')['opens']} vs {day(4)}, "
                               f"draft {dlg.draft}, posts {STORE.plan_posts.get(pid)}, {dlg.status.text()!r}")
        dlg._undo_entries()
        if not [a for a in dlg.undo_menu.actions() if a.text().startswith("Undo your send of Tue 2:14 pm (2 changes)")]:
            raise RuntimeError(f"planner: Undo ▾ after a send {[a.text() for a in dlg.undo_menu.actions()]}")
        shoot(dlg, os.path.join(out, "planner-sent.png"))
        # a co-author saves while changes wait: they go on theirs when it loads
        dlg.change({"op": "rename", "date": "u3", "name": "Shock and sepsis"})
        STORE.plans[pid]["version"] += 1
        dlg._load()
        if not dlg.draft or dlg.draft.version != STORE.plans[pid]["version"] or dlg.unit("u3")["name"] != "Shock and sepsis":
            raise RuntimeError("planner: waiting changes, replayed on a co-author's save")
        dlg.take_change(0)
        if dlg.draft is not None or not tab.send_box.isHidden():
            raise RuntimeError("planner: a waiting change taken out")
        # an AI app's change (what the local MCP server adds): marked in Review and send, its reason the line
        dlg.change({"op": "rename", "date": "u3", "name": "Shock and sepsis", "by": "ai", "why": "Named as the course names it."})
        sd = PS.SendDialog(dlg)
        if sd.why() != "Named as the course names it." or "From your AI app" not in \
                [w.text() for w in sd.findChildren(QtWidgets.QLabel)]:
            raise RuntimeError(f"planner: an AI app's change in Review and send: {sd.why()!r}")
        shoot(sd, os.path.join(out, "planner-send-ai.png"))
        sd.reject()
        dlg.take_change(0)
        # no Followers tab (Sam's call): how many follow is a line in Sharing, and Posts… what they were told;
        # nothing says how far they are or whose Anki has the last send (the plan's squad is where followers meet)
        if "followers" in dlg.pages:
            raise RuntimeError("planner: a Followers tab")
        st = dlg.pages["sharing"]
        if st.following.text() != "4 following" or st.posts_btn.isHidden():
            raise RuntimeError(f"planner: Sharing's Followers line {st.following.text()!r}")
        pd = PS.PostsDialog(dlg)
        pd.tab.box.setText("Week 3 moved: Shock is Thursday now.")
        pd.tab._post()
        labels = [w.text() for w in pd.findChildren(QtWidgets.QLabel)]
        if not pd.tab.status.text().startswith("Posted") or any("followers' Anki" in t or " done" in t for t in labels) \
                or pd.findChildren(QtWidgets.QProgressBar):
            raise RuntimeError(f"planner: Posts {pd.tab.status.text()!r}, {labels}")
        pd.tab._read()
        shoot(pd, os.path.join(out, "planner-posts.png"))
        pd.reject()
        if dlg.draft:
            dlg.draft.clear()
        dlg.ops.keep_draft(pid, None)
        dlg._load()
        # Sharing: its code and link first; the name and line; the deck's link (a change)
        st = dlg.pages["sharing"]
        dlg._show_tab("sharing")
        if st.code.text() != STORE.plans[pid]["code"] or st.squad.count() != 2 or st.delete_btn.isHidden():
            raise RuntimeError(f"planner: Sharing: {st.code.text()!r}")
        st.line.setText("Organ systems, one a week.")
        st._save_meta()
        if STORE.plans[pid].get("line") != "Organ systems, one a week." or not st.said.text().startswith("Saved"):
            raise RuntimeError(f"planner: Sharing, the line: {st.said.text()!r}")
        shoot(dlg, os.path.join(out, "planner-sharing.png"))
        # History: every save, the latest undone
        hd = PS.HistoryDialog(dlg)
        hd.tab._read()
        if hd.tab.list.topLevelItemCount() < 5 or hd.tab.undo_btn.isHidden():
            raise RuntimeError("planner: History")
        shoot(hd, os.path.join(out, "planner-history.png"))
        # notes on a day, on the picked date
        heart = unit("u1")
        STORE.follows[(pid, "ameya")] = {"share": False, "paused": False, "sched": None, "progress": None}
        STORE._note_n = 1
        STORE.plan_notes.append({"id": 1, "plan": pid, "uid": "ameya", "day": heart["opens"], "text": "Lecture's in room 4B today", "at": 0})
        dlg._show_tab("plan")
        dlg._load()
        tab.pick(("date", "u1"))
        dn = dp.day_notes
        dn.box.setText("Lab day, keep it light")
        dn._add()
        rows = [(dn.list.topLevelItem(i).text(0), dn.list.topLevelItem(i).text(1)) for i in range(dn.list.topLevelItemCount())]
        if rows != [("Ameya", "Lecture's in room 4B today"), ("You", "Lab day, keep it light")]:
            raise RuntimeError(f"planner: notes on a day: {rows}")
        tab._mode("month")
        shoot(dlg, os.path.join(out, "planner-month.png"))
        # Month: a date dragged onto another day moves there (with people following, it waits); Ctrl+Z takes it back
        cells = {c.day: c for c in tab.month_body.findChildren(PW.DayCell)}
        to = QtCore.QDate.fromString(unit("u1")["opens"], "yyyy-MM-dd").addDays(2).toString("yyyy-MM-dd")
        drags = [r for r in tab.month_body.findChildren(PW.Row) if r.drag]
        if to not in cells or not cells[to].acceptDrops() or not drags:
            raise RuntimeError(f"planner: Month takes a dragged date ({to} in {sorted(cells)[:3]}…)")
        was = PTB.confirm
        PTB.confirm = yes
        try:
            cells[to].on_drop("date", "u1", to)
        finally:
            PTB.confirm = was
        if not dlg.draft or dlg.draft.ops[-1].get("op") != "move" or dlg.unit("u1")["opens"] != to:
            raise RuntimeError(f"planner: a date dropped on another day: {dlg.draft and dlg.draft.ops}")
        dlg.undo_key()
        if dlg.draft is not None:
            raise RuntimeError("planner: Ctrl+Z takes back the last change not sent")
        tab._mode("list")
        # the Plan tab's keys, and Find
        seqs = {x.key().toString() for x in tab.findChildren(QtGui.QShortcut)}
        want = {"Ctrl+N", "Ctrl+E", "Ctrl+F", "Ctrl+T", "Ctrl+1", "Ctrl+2", "Ctrl+D", "Ctrl+Z", "Ctrl+Return",
                "Up", "Down", "Alt+Left", "Alt+Right", "Return", "F2", "Del"}
        if not want <= seqs:
            raise RuntimeError(f"planner: the Plan tab's keys, missing {sorted(want - seqs)}")
        tab.pick(("date", "u1"))
        tab.step(1)
        order = [k for k in tab.rows if k[0] in ("date", "event", "review")]
        if tab.picked != order[order.index(("date", "u1")) + 1]:
            raise RuntimeError(f"planner: ↓ picks the next one: {tab.picked}")
        tab._toggle_all()
        if tab.all_btn.text() != "Collapse all" or not all(tab._is_open(w) for w in M_.weeks(dlg.doc, TODAY)):
            raise RuntimeError(f"planner: Expand all ({tab.all_btn.text()!r})")
        tab._toggle_all()
        if tab.all_btn.text() != "Expand all" or [k for k in tab.rows if k[0] == "date"]:
            raise RuntimeError(f"planner: Collapse all ({tab.all_btn.text()!r}, {list(tab.rows)[:3]})")
        tab.all_open = None
        tab._toggle_sort()  # Latest first: the list the other way up, the line at today still between past and to come
        order = [k for k in tab.rows if k[0] == "date"]
        days = [dlg.unit(k[1])["opens"] for k in order]
        if tab.sort_btn.text() != "Latest first" or days != sorted(days, reverse=True):
            raise RuntimeError(f"planner: Latest first {days}")
        tab._toggle_sort()
        days = [dlg.unit(k[1])["opens"] for k in tab.rows if k[0] == "date"]
        if tab.sort_btn.text() != "Earliest first" or days != sorted(days):
            raise RuntimeError(f"planner: Earliest first {days}")
        tab.find.setText("heart")
        found = [k for k in tab.rows if k[0] == "date"]
        if not found or any("heart" not in (dlg.unit(k[1]).get("name") or "").lower()
                            and not any("heart" in str(t).lower() for t in dlg.unit(k[1]).get("tags") or []) for k in found):
            raise RuntimeError(f"planner: Find keeps the dates with its words: {found}")
        tab._find_first()
        if tab.picked != found[0]:
            raise RuntimeError("planner: Find's Enter picks the first")
        tab.find.clear()
        tab._go_change("u3")
        if tab.picked != ("date", "u3"):
            raise RuntimeError("planner: a change in the foot, clicked, picks its date")
        # a plan I follow: Plan (today, behind, its dates to read) and Mine
        pid2, _code2 = STORE.add_plan("kai", "Kai's Renal", "Big Step 1", [
            {"id": "k1", "name": "Heart failure", "opens": day(-6), "tags": [f"{root}::#Videos::Cardio::Heart_Failure"]},
            {"id": "k2", "name": "Shock", "opens": TODAY, "tags": [f"{root}::#Videos::Cardio::Shock"]}])
        STORE.follows[(pid2, "sam")] = {"share": True, "paused": False, "sched": None, "progress": None}

        class FOps(Ops):
            def follow_state(self, pid_):
                return {"id": pid_, "name": "Kai's Renal", "shift": 2, "skipped": ["k1"], "own": ""}

            def held_count(self, pid_):
                return 3

            def in_team(self, pid_):
                return True

            def can_reset(self, pid_):
                return True

        fw = PlanWindow(None, col, PR.my_plans(CLIENT), FOps(), select=pid2)
        fw.resize(1180, 760)
        shown = [fw.tabs.tabText(i) for i in range(fw.tabs.count()) if fw.tabs.isTabVisible(i)]
        ft = fw.pages["plan"]
        if shown != ["Plan", "Insights", "Settings"] or fw.author() or ft.today_box.isHidden() or ft.behind_box.isHidden() \
                or not ft.paste_row.isHidden() or not ft.shape_box.isHidden() or not fw.undo_btn.isHidden():
            raise RuntimeError(f"planner: a follower's tabs {shown}")
        shoot(fw, os.path.join(out, "planner-follower.png"))
        fw._show_tab("insights")
        fi = fw.pages["insights"]
        said = [w.text() for w in fi.findChildren(QtWidgets.QLabel) if w.isVisibleTo(fi)]
        if not any(t.startswith("You've seen") for t in said) or "Workload" not in said:
            raise RuntimeError(f"planner: a follower's Insights {said}")
        shoot(fw, os.path.join(out, "planner-insights-follower.png"))
        fi.body.grab().save(os.path.join(out, "planner-insights-follower-all.png"))
        fw._show_tab("mine")
        mt = fw.pages["mine"]
        if mt.later.text() != "2 days later" or mt.held.isHidden():
            raise RuntimeError(f"planner: Mine {mt.later.text()!r}")
        mt._more()  # round five: what the board's Plan ▾ held besides is under More
        more = [a.text() for a in mt.more_menu.actions()]
        nxt = next((a for a in mt.more_menu.actions() if a.text().startswith("When I'm ready, the next")), None)
        if not {"Change deck…", "Open everything now", "Open early", "Reset to default…"} <= set(more) \
                or nxt is None or nxt.isEnabled() or "My schedule…" in more:
            raise RuntimeError(f"planner: Settings' More (a follower's) {more}")
        shoot(fw, os.path.join(out, "planner-mine.png"))
        # a picked date whose plan lost its dates, then a load that fails: no crash, no stale pick
        crash = PlanWindow_()
        crash.pages["plan"].pick(("date", "u1"))
        raw0, plan0 = PR.load(CLIENT, pid)
        bare = dict(raw0, doc=dict(raw0["doc"], units=[], reviews=[], events=[]))
        crash._loaded(pid, (bare, dict(plan0, doc=dict(plan0["doc"], units=[], events=[]))))
        if crash.pages["plan"].picked is not None:
            raise RuntimeError("planner: a picked date outlived its plan's dates")
        crash._loaded(pid, None)
        if crash.pages["plan"].picked is not None or "didn't load" not in crash.status.text():
            raise RuntimeError(f"planner: a load that failed: {crash.status.text()!r}")
        crash._load()
        if crash.busy or crash.plan is None:
            raise RuntimeError("planner: picked again after a load that failed")
        empty = PlanWindow_([])
        if not empty.tabs.isHidden() or empty.welcome.isHidden() or not empty.pick.isHidden():
            raise RuntimeError("planner: no plans yet: the welcome, no tabs")
        [b for b in empty.welcome.findChildren(QtWidgets.QPushButton) if b.text() == "Follow a plan…"][0].click()
        if reopened[-1:] != ["follow"]:
            raise RuntimeError("planner: no plans yet: Follow a plan…")
        shoot(empty, os.path.join(out, "planner-empty.png"))
        # New plan: the one way to start, a calendar pasted
        from due_crew.planner.new_plan import NewPlanWindow

        class NOps:
            def today(self):
                return datetime.date.fromisoformat(TODAY)

            def index(self, did):
                return P.DeckIndex(col, did)

            def make(self, owner, name, doc, done, pid=None):
                outcome, raw = PR.create(CLIENT, name, doc.get("deck") or "")
                done(PR.save(CLIENT, raw["id"], raw.get("version") or 1, doc, "made"))

            def open_plan(self, pid_):
                reopened.append(("new", pid_))

            def follow(self, code):
                reopened.append(("follow", code))

            def labs_window(self):
                pass

        nw = NewPlanWindow(None, [(1, "Big Step 1", 60)], NOps())
        nw.text.setPlainText(f"BLOCK 2 · Cardiovascular\nWEEK 1\n{P.fmt_day(day(7))}  LEC  Heart failure\n"
                             f"{P.fmt_day(day(8))}  LEC  Something new\n{P.fmt_day(day(11))}  EXAM  Block 2 exam")
        nw._read()
        doc_, n_ = nw.doc()
        if nw.name.text() != "BLOCK 2 · Cardiovascular" or nw.end_name.text() != "Block 2 exam" or n_ != 2 \
                or any(u.get("tags") or u.get("decks") for u in doc_["units"]) or doc_.get("deck") != "Big Step 1" \
                or doc_.get("end") != day(11) or len(doc_.get("events") or []) != 1:
            raise RuntimeError(f"new plan: {nw.name.text()!r}, {nw.end_name.text()!r}, {n_}, {doc_}")
        shoot(nw, os.path.join(out, "planner-new.png"))
        was = __import__("due_crew.planner.new_plan", fromlist=["confirm"]).confirm
        import due_crew.planner.new_plan as PNP
        PNP.confirm = yes
        try:
            nw._make()
        finally:
            PNP.confirm = was
        if not reopened or reopened[-1][0] != "new":
            raise RuntimeError(f"new plan: made {nw.said.text()!r}")
        STORE.plans.pop(reopened[-1][1], None)
        STORE.plans.pop(pid2, None)
        if PO.why_line([]) != "":
            raise RuntimeError("planner: an empty why")
        idx = P.DeckIndex(col, 1)
        pick = Picker(None, idx, "Add to Tue " + day(1)[-2:], "Big Step 1")
        top = pick.tree.topLevelItem(0)
        pick.tree.expandItem(top)
        settle(50)
        for i in range(top.childCount()):
            if top.child(i).text(0) == "Videos":
                pick.tree.expandItem(top.child(i))
        shoot(pick, os.path.join(out, "planner-picker.png"))
        pick = Picker(None, idx, "Add to Tue", "Big Step 1")
        pick.find.setText("heart failure")
        pick._fill()
        pick.tree.topLevelItem(0).setCheckState(0, QtCore.Qt.CheckState.Checked)
        if pick.value() != ([f"{root}::#Book::Cardio::Heart_Failure"], []) or not pick.go.isEnabled():
            raise RuntimeError(f"picker: ticked {pick.value()}")
        shoot(pick, os.path.join(out, "planner-picker-find.png"))

        # QBank QIDs on its own copy of the deck: its Unsuspend changes nothing the windows after it read
        qconn = sqlite3.connect(":memory:")
        conn.commit()  # a backup waits forever on a source with a write still open
        conn.backup(qconn)
        qcol = fakes.FakeCol(qconn, fakes.day_cutoff_for(datetime.date.today()))
        qcol.decks = fakes.FakeDecks({1: "Big Step 1", 3: "Big Step 1::Cardio", 5: "Due Crew::QBank cards"})

        class QOps(PF.QidOps):
            def index(self, did):
                return P.DeckIndex(qcol, did)

            def default_deck(self, choices):
                return 1

            def plan_dates(self, did, idx, cids):
                return [("MS2 Block 2", [P.fmt_day(day(0))])]

            def unsuspend(self, cids):
                return PA.unsuspend(qcol, cids, "Due Crew: unsuspend")

            def study(self, cids):
                QOps.studied = sorted(cids)
                return True

            def browse(self, cids):
                QOps.browsed = sorted(cids)

            # 3.9.5, Their topics: the deck's map as Insights would draw it, a part a system; the questions' cards
            # are all suspended, so each falls in its part by its tag (qids.topics), as they do in a real deck
            long_name = ""

            def deck_map(self, did):
                qidx = P.DeckIndex(qcol, did)
                play = lambda tag: sorted(c for c in qidx.tag_cards(f"{root}::{tag}") if qidx.cards[c][0] != -1)  # noqa: E731
                hf, shock, drugs = (play("^Systems::Cardio::Heart_Failure"), play("#Videos::Cardio::Shock"),
                                    play("#Videos::Pharm::HF_Drugs"))
                part = lambda name, tag, cids, know, n=None: {  # noqa: E731
                    "key": tag.lower(), "name": name, "n": n or len(cids), "started": len(cids) if know is not None else 0,
                    "know": know, "find": {"tags": [f"{root}::{tag}"]}, "_cids": cids}
                tiles = [part(QOps.long_name or "Cardio · Heart Failure", "^Systems::Cardio::Heart_Failure", hf, 66),
                         part("Pharm · HF Drugs", "#Videos::Pharm::HF_Drugs", drugs, 81),
                         part("Cardio · Shock", "^Systems::Cardio::Shock", shock, 84),
                         part("Renal · AKI", "^Systems::Renal::AKI", [], None, n=12)]
                return tiles, set(hf[:5]) | set(shock[:2]) | set(drugs)

            def study_topic(self, name, cids):
                QOps.topic = (name, sorted(cids))
                return True

        q = QidWindow(None, qcol, [(1, "Big Step 1")], QOps())
        if q.study_btn.isEnabled() or q.unsuspend_btn.isEnabled() or q.lines.text() or not q.browse_btn.isHidden():
            raise RuntimeError("qids: nothing pasted, nothing to do")
        if q.study_btn.property("dc") != "go" or q.text.placeholderText() != "Paste QBank QIDs here":
            raise RuntimeError("qids: Study now in the accent, and the box asks for QIDs (3.9.4, Sam)")
        shoot(q, os.path.join(out, "planner-qids-empty.png"))
        q = QidWindow(None, qcol, [(1, "Big Step 1")], QOps())
        q.text.setPlainText("Block 3 · 12 Oct 2026\nMissed: 10234, 10911, 11002, 12118 · 65%")
        q._count()
        if (q.found["found"] != ["10234", "10911", "11002", "12118"] or not q.bank.isHidden() or not q.study_btn.isEnabled()
                or q.unsuspend_btn.text() != "Unsuspend 6" or q.lines.text() != "4 questions · 6 cards · 6 suspended"):
            raise RuntimeError(f"qids: {q.found}, {q.unsuspend_btn.text()!r}, {q.lines.text()!r}")
        # 3.9.5: Their topics, a question once in each part its cards are in; the map's % there; Study when I missed some
        said = [lab.text() for lab in q.topics.findChildren(QtWidgets.QLabel) if lab.isVisibleTo(q)]
        studies = [b for b in q.topics.findChildren(QtWidgets.QPushButton) if b.isVisibleTo(q)]
        if (q.topics.isHidden() or [(r["name"], r["questions"]) for r in q.topic_rows]
                != [("Cardio · Heart Failure", 2), ("Cardio · Shock", 1), ("Renal · AKI", 1)]
                or said != ["Their topics", "Cardio · Heart Failure", "2 questions · 66% here", "Cardio · Shock", "1 question · 84%",
                            "Renal · AKI", "1 question · new"]
                or [b.text() for b in studies] != ["Study", "Study"] or "Study the 5 you missed" not in studies[0].toolTip()
                or any(lab.textFormat() != QtCore.Qt.TextFormat.PlainText for lab in q.topics.findChildren(QtWidgets.QLabel))):
            raise RuntimeError(f"qids: their topics {q.topic_rows}, {said}, {[b.toolTip() for b in studies]} (names in plain text)")
        shoot(q, os.path.join(out, "planner-qids.png"))
        q.show()
        settle(50)  # the paste's own count came in the shot: its rows drawn again
        [b for b in q.topics.findChildren(QtWidgets.QPushButton) if b.isVisibleTo(q)][1].click()
        if QOps.topic[0] != "Cardio · Shock" or len(QOps.topic[1]) != 2 or q.isVisible():
            raise RuntimeError(f"qids: a topic's Study took {QOps.topic}, the window still open: {q.isVisible()}")
        q = QidWindow(None, qcol, [(1, "Big Step 1")], QOps())
        q.text.setPlainText("10234 10911 11002 12118")
        q._count()
        q.study_btn.click()
        if QOps.studied != sorted(q.cids()) or len(QOps.studied) != 6:
            raise RuntimeError(f"qids: Study took {QOps.studied}")
        QOps.long_name = "Cardiovascular Physiology and Pathology · Heart Failure Treatment"[:60]  # team.NAME_MAX
        q = QidWindow(None, qcol, [(1, "Big Step 1")], QOps())
        q.text.setPlainText("10234 10911 11002 12118")
        q._count()
        shoot(q, os.path.join(out, "planner-qids-topics-long.png"))
        QOps.long_name = ""
        q = QidWindow(None, qcol, [(1, "Big Step 1")], QOps())
        q.text.setPlainText("10234")
        q._count()
        if q.bank.isHidden() or q.bank_label.text() != "Question bank" or q.bank.count() != 2:
            raise RuntimeError("qids: a number in two banks asks which")
        shoot(q, os.path.join(out, "planner-qids-bank.png"))
        q = QidWindow(None, qcol, [(1, "Big Step 1")], QOps())
        q.text.setPlainText("10234 10911 11002 12118")
        q._count()
        q._unsuspend()
        if not q.said.text().startswith("Unsuspended 6") or len(qcol.undo_steps) != 1 or q.unsuspend_btn.isEnabled():
            raise RuntimeError(f"qids: Unsuspend said {q.said.text()!r}, {qcol.undo_steps}")
        shoot(q, os.path.join(out, "planner-qids-done.png"))
        start_window(STORE, PF, PR, P)

    for label, build in (("kitchen", kitchen), ("questions", questions), ("tools menu", tools_menu), ("friends", friends), ("decks", decks),
                         ("squads", squads), ("auth", auth),
                         ("welcome", welcome), ("logo", logo), ("room", room), ("emoji", emoji),
                         ("report", report), ("plans", plans), ("schedule", schedule), ("map card", map_card),
                         ("share card", share_card), ("why", why), ("game night", game_night), ("plan tags", plan_tags), ("open cards", open_cards),
                         ("remark", remark), ("held back", held), ("welcome back", away), ("planner", planner),
                         ("ai app", ai_app)):
        if os.environ.get("DC_ONLY") and label not in os.environ["DC_ONLY"].split(","):
            continue  # DC_ONLY=planner,plans: just those (while working on them)
        attempt(label, build)
    if failures:
        print("FAILED:", *failures, sep="\n  ")
        return 1
    print("all dialogs built")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "dialog-shots"))
