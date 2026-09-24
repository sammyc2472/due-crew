"""Render every Due Crew dialog offscreen with real PyQt6 against the fake
Firestore, and save a PNG of each. The one way to see the Qt side without
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

STORE = fakes.FakeFirestore()
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
    col.decks = fakes.FakeDecks({1: "AnKing Step 1", 3: "AnKing Step 1::Cardio",
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

from due_crew.backend import firebase  # noqa: E402

# ---- a signed-in Sam with a crew, a knock, and two squads ----
TODAY = datetime.date.today().isoformat()


def fv(v):
    if isinstance(v, bool):
        return {"booleanValue": v}
    if isinstance(v, int):
        return {"integerValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    if isinstance(v, list):
        return {"arrayValue": {"values": [fv(x) for x in v]}}
    return {"stringValue": str(v)}


for uid, name, friends in (("sam", "Sammy", ["igk", "ameya", "adina", "chi"]),
                           ("igk", "igk", ["sam"]), ("ameya", "Ameya", ["sam"]),
                           ("adina", "Adina", ["sam"]), ("chi", "Chidemma", []),
                           ("priya", "Priya", ["sam"])):
    STORE.docs[f"users/{uid}"] = {"displayName": fv(name), "friends": fv(friends),
                                  "friendCode": fv(uid.upper()[:3] + "123")}
STORE.docs["friend_codes/SAM123"] = {"userId": fv("sam")}
STORE.auth_uid = "sam"
CLIENT = firebase.FirebaseClient(os.path.join(os.environ.get("TMPDIR", "/tmp"), "dc-dialogs-session.json"))
CLIENT.session = {"user_id": "sam", "id_token": "t-sam", "refresh_token": "r",
                  "display_name": "Sammy", "email": "sam@example.com",
                  "last_ok": (datetime.datetime.now(datetime.timezone.utc)
                              - datetime.timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%SZ")}
SQUAD = CLIENT.create_squad("sam", "busm", "Sammy")
STORE.docs[f"squads/{SQUAD['id']}/members/priya"] = {"name": fv("Priya"), "joinedAt": fv("t")}
STORE.auth_uid = "priya"
firebase.FirebaseClient(os.path.join(os.environ.get("TMPDIR", "/tmp"), "dc-dialogs-priya.json"))
STORE.docs["users/sam/knocks/priya"] = {"name": fv("Priya"), "at": fv("t"), "squad": fv(SQUAD["id"])}
STORE.auth_uid = "sam"

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
# fingerprints are note guids; these overlap the AnKing subtree built in
# _collection(), so the Shared Decks dialog has a real match to show
_SIG = [f"guid{n:06d}" for n in range(1, 13)]
CREW = [{"user_id": "sam", "name": "Sammy", "you": True, "decks": [{"name": "AnKing Step 1", "sig": _SIG}]},
        {"user_id": "igk", "name": "igk", "you": False, "decks": [{"name": "AnKing Step 1", "sig": _SIG[:10]}]}]


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
        dlg = SquadDialog(None, CLIENT, noop)
        dlg.code_edit.setText(SQUAD["code"])
        dlg._look_up()
        app.processEvents()
        shoot(dlg, os.path.join(out, "squads.png"))

    def cheer():
        from due_crew.ui.cheer_dialog import CheerDialog
        from due_crew.app import CHEER_CLASSIC, CHEER_QUICK
        dlg = CheerDialog(None, "Ameya", CHEER_QUICK)
        dlg.other.setText("\U0001F973")  # a palette pick landing in the box
        shoot(dlg, os.path.join(out, "cheer.png"))
        dlg = CheerDialog(None, "Ameya", CHEER_CLASSIC, any_emoji=False)  # server on old rules
        shoot(dlg, os.path.join(out, "cheer-old-rules.png"))

    def auth():
        from due_crew.ui.auth_dialog import AuthDialog
        dlg = AuthDialog(None, CLIENT)
        shoot(dlg, os.path.join(out, "auth.png"))
        dlg = AuthDialog(None, CLIENT, join=True)  # a new install opens on Join
        shoot(dlg, os.path.join(out, "auth-join.png"))

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

    def emoji():
        from due_crew.ui.cheer_dialog import EmojiDialog
        shoot(EmojiDialog(None, "\U0001F98A"), os.path.join(out, "emoji.png"))
        shoot(EmojiDialog(None, "\U0001F985"), os.path.join(out, "emoji-other.png"))

    for label, build in (("settings", settings), ("friends", friends), ("decks", decks),
                         ("squads", squads), ("cheer", cheer), ("auth", auth),
                         ("welcome", welcome), ("logo", logo), ("emoji", emoji)):
        attempt(label, build)
    if failures:
        print("FAILED:", *failures, sep="\n  ")
        return 1
    print("all dialogs built")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "dialog-shots"))
