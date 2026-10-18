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
    lay = dlg.layout()
    if lay is not None:
        least = lay.totalMinimumSize()
        if dlg.width() < least.width() or dlg.height() < least.height():
            bad.append(f"window {dlg.width()}x{dlg.height()} under its rows' {least.width()}x{least.height()}")
        elif lay.hasHeightForWidth() and dlg.height() < lay.totalHeightForWidth(dlg.width()):
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
        want = ["Study what’s next", "—", "Friends…", "Squads…", "—", "Make a plan from a deck…",
                "Follow a plan…", "Export cards for my AI…", "—", "Settings…", "Pip’s closet…", "Your year…", "Show on the Decks screen",
                "Send feedback…"]
        if items != want:
            raise RuntimeError(f"tools menu: {items}")
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

    for label, build in (("kitchen", kitchen), ("questions", questions), ("tools menu", tools_menu), ("friends", friends), ("decks", decks),
                         ("squads", squads), ("auth", auth),
                         ("welcome", welcome), ("logo", logo), ("room", room), ("emoji", emoji),
                         ("report", report), ("plans", plans), ("schedule", schedule), ("map card", map_card),
                         ("share card", share_card), ("why", why), ("plan tags", plan_tags), ("open cards", open_cards),
                         ("remark", remark), ("held back", held), ("welcome back", away)):
        attempt(label, build)
    if failures:
        print("FAILED:", *failures, sep="\n  ")
        return 1
    print("all dialogs built")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "dialog-shots"))
