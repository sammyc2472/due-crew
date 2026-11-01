"""Your plans (docs/planner.md; round five): the builder of duecrew.com,
in Anki, as one window, three tabs. An author's: Plan (the plan's shape
on top, its weeks and dates, the picked one beside them or the deck
while cards go on, a paste box, and the changes waiting to be sent),
Insights (what each week asks, how much of the deck it holds and of each
part, what each quiz tests, its biggest dates) and Settings (its name,
dates and pace, every-week lines; its code, who can follow, how many do
and the posts to them, co-authors, the library; Your AI app). A plan I
follow: Plan (today, what's behind, its dates), Insights (the same, on
my dates, with what I've seen) and Settings (my dates, skips, how its
cards open). Undo on top.

Every change is an op (ops.py). With anyone following, it waits under
the plan (draft.py, kept on this computer) until Review and send, one
save with one line to followers; with nobody following, it saves at once
(PUT /plans/{id}, the version it started from) and Undo takes it back.
Show in Browse, Open and Study are plan_flow's (through flow.Ops). Names
are the authors' and the deck's: plain text everywhere, escaped in a
tooltip."""

from aqt.qt import (
    QComboBox, QDate, QDateEdit, QDialog, QDialogButtonBox, QHBoxLayout, QPushButton, QTabWidget,
    QTimer, QVBoxLayout, QWidget,
)

from ..ui import attach_alive, heading, role
from .core import PlanCore, pick_label, whose
from .widgets import fit, menu_button, plain, tip_keys

TABS = {"dates": "plan", "layout": "plan", "text": "plan", "plan": "plan", "history": "plan",
        "insights": "insights", "workload": "insights", "progress": "sharing", "updates": "sharing", "followers": "sharing",
        "settings": "sharing", "sharing": "sharing", "mine": "mine"}


_whose, _pick_label = whose, pick_label  # (their old names)


class DayDialog(QDialog):
    """One day, picked on a calendar: a new date's day, a quiz's."""

    def __init__(self, parent, title, words, day, yes, clear=None):
        super().__init__(parent)
        attach_alive(self)
        self.cleared = False
        self.setWindowTitle(title)
        root = QVBoxLayout(self)
        heading(self, root)
        root.addWidget(plain(words, muted=True))
        self.day = QDateEdit()
        self.day.setCalendarPopup(True)
        self.day.setDisplayFormat("ddd d MMM yyyy")
        d = QDate.fromString(str(day), "yyyy-MM-dd")
        self.day.setDate(d if d.isValid() else QDate.currentDate())
        root.addWidget(self.day)
        buttons = QDialogButtonBox()
        buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole).clicked.connect(self.reject)
        if clear:
            b = QPushButton(clear)
            b.clicked.connect(self._clear)
            buttons.addButton(b, QDialogButtonBox.ButtonRole.ActionRole)
        go = QPushButton(yes)
        go.setDefault(True)
        go.clicked.connect(self.accept)
        buttons.addButton(go, QDialogButtonBox.ButtonRole.AcceptRole)
        root.addWidget(buttons)

    def _clear(self):
        self.cleared = True
        self.accept()

    def value(self):
        return None if self.cleared else self.day.date().toString("yyyy-MM-dd")


def ask_day(parent, title, words, day, yes, clear=None):
    """The day picked ("YYYY-MM-DD"), None for `clear`, False when cancelled."""
    dlg = DayDialog(parent, title, words, day, yes, clear)
    return dlg.value() if dlg.exec() else False


class PlanWindow(QDialog, PlanCore):
    """plans: remote.my_plans' (cleaned, each with its role). ops: flow.Ops,
    or a render's or test's own."""

    def __init__(self, parent, col, plans, ops, select=None, tab=None):
        super().__init__(parent)
        self.core_init(col, plans, ops)
        attach_alive(self)
        self.setWindowTitle("Your plans")
        self.setModal(False)
        self.setMinimumSize(900, 560)
        self.setProperty("dcOwnSize", True)  # it scrolls its own: ui._fit never grows it to its words
        fit(self, 1180, 780)  # its first size; less on a small screen
        root = QVBoxLayout(self)
        self.head = heading(self, root, "Your plans")

        top = QHBoxLayout()
        self.pick = QComboBox()
        for p in self.plans:
            self.pick.addItem(pick_label(p), p["id"])
        top.addWidget(self.pick, 1)
        self.undo_btn, self.undo_menu = menu_button("Undo", self._undo_entries)
        self.undo_btn.setToolTip(tip_keys("The last change not sent, your last save or send; History", "Ctrl+Z"))
        top.addWidget(self.undo_btn)
        self.new_btn = QPushButton("New plan…")
        self.new_btn.setAutoDefault(False)
        self.new_btn.clicked.connect(lambda: self.ops.new_plan())
        top.addWidget(self.new_btn)
        root.addLayout(top)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        root.addWidget(self.tabs, 1)
        self.welcome = self._welcome()  # no plans yet: in the tabs' place
        root.addWidget(self.welcome, 1)
        self.pages = {}
        from .plan_tab import PlanTab
        from .insights_tab import InsightsTab
        from .settings_tab import SettingsTab
        from .mine_tab import MineTab
        self._add_tab("plan", "Plan", PlanTab(self))
        self._add_tab("insights", "Insights", InsightsTab(self))  # what it asks a week, how much of the deck, what's in it
        self._add_tab("sharing", "Settings", SettingsTab(self))  # an author's: the plan's dates and pace, sharing it
        self._add_tab("mine", "Settings", MineTab(self))  # a follower's: my dates, skips, how its cards open
        self.want_tab = TABS.get(tab or "", tab)

        bottom = QHBoxLayout()
        self.status = plain(muted=True)
        bottom.addWidget(self.status, 1)
        close = QPushButton("Close")
        close.setAutoDefault(False)
        close.clicked.connect(self.reject)
        bottom.addWidget(close)
        root.addLayout(bottom)
        self.tabs.currentChanged.connect(self._tab_changed)

        if select and self.pick.findData(select) >= 0:
            self.pick.setCurrentIndex(self.pick.findData(select))  # before the signal: one load, of this one
        self.pick.currentIndexChanged.connect(self._load)
        # the same plan picked again after a load that failed: try it again
        self.pick.activated.connect(lambda _i: self._load() if self.plan is None and not self.busy else None)
        if self.plans:
            self._load()
        else:
            self._no_plans()

    def _welcome(self):
        """No plans yet: what a plan is, and the two ways to one."""
        page = QWidget()
        words = QVBoxLayout(page)
        words.setContentsMargins(0, 16, 0, 0)
        words.addWidget(role(plain("No plans yet"), "head"))
        words.addWidget(plain("A plan puts a block's lectures on dates, and opens each date's cards in Anki "
                              "as its day comes."))
        ways = QHBoxLayout()
        b = QPushButton("New plan…")
        b.setProperty("dc", "go")
        b.clicked.connect(lambda: self.ops.new_plan())
        ways.addWidget(b)
        f = QPushButton("Follow a plan…")
        f.clicked.connect(lambda: self.ops.follow_plan())
        ways.addWidget(f)
        ways.addStretch(1)
        words.addSpacing(8)
        words.addLayout(ways)
        words.addStretch(1)
        page.hide()
        return page

    def _no_plans(self):
        for w in (self.pick, self.undo_btn, self.new_btn, self.tabs):
            w.hide()
        self.welcome.show()
        self.setMinimumSize(640, 260)
        self.resize(720, 280)

    def go_to_plan(self, pid, tab=None):
        """The window, on this plan: True, or False when it doesn't list it."""
        i = self.pick.findData(pid)
        if i < 0:
            return False
        self.want_tab = TABS.get(tab or "", tab)
        if i != self.pick.currentIndex():
            self.pick.setCurrentIndex(i)
        else:
            self._show_tab(self.want_tab)
        return True

    # ---- the tabs ----

    def _add_tab(self, key, label, widget):
        self.pages[key] = widget
        self.tabs.addTab(widget, label)

    def _show_tab(self, key):
        page = self.pages.get(key or "")
        i = self.tabs.indexOf(page) if page is not None else -1
        if i >= 0 and self.tabs.isTabVisible(i):
            self.tabs.setCurrentIndex(i)

    def _role_tabs(self):
        """Plan and Insights always; Settings: an author's (SettingsTab) or a follower's (MineTab)."""
        for key, page in self.pages.items():
            shown = getattr(page, "shown", None)
            i = self.tabs.indexOf(page)
            self.tabs.setTabVisible(i, bool(shown(self)) if callable(shown) else True)
        for page in self.pages.values():
            fill = getattr(page, "plan_loaded", None)
            if callable(fill):
                fill(self)
        if self.want_tab:
            self._show_tab(self.want_tab)
            self.want_tab = None
        self._undo_button()

    def _tab_changed(self, _i):
        page = self.tabs.currentWidget()
        if getattr(page, "dirty", False):
            page.draw()  # Insights: worked out when it's looked at
        if not self.busy:
            self.status.setText("")

    # ---- the core's hooks (core.PlanCore) ----

    def current_pid(self):
        return self.pick.currentData()

    def say(self, text):
        self.status.setText(text)

    def busy_shown(self):
        self.pick.setEnabled(not self.busy)
        self.new_btn.setEnabled(not self.busy)
        for page in self.pages.values():
            if callable(getattr(page, "busy_changed", None)):
                page.busy_changed(self)

    def plan_shown(self):
        self._role_tabs()

    def doc_shown(self):
        for page in self.pages.values():
            fill = getattr(page, "plan_loaded", None)
            if callable(fill):
                fill(self)
        self._undo_button()

    def undo_shown(self):
        self._undo_button()

    def picked_key(self):
        return self.pages["plan"].picked

    def label_changed(self, pid, plan):
        i = self.pick.findData(pid)
        if i >= 0:
            self.pick.setItemText(i, pick_label(plan))

    def forget_notes(self):
        self.pages["plan"].forget()

    def ask_discard(self, n):
        from ..ui import confirm
        return confirm(self, f"Discard {n:,} change{'s' if n != 1 else ''}?", "They were never sent: nobody saw them.",
                       "Discard", danger=True)

    def later(self, fn):
        QTimer.singleShot(0, fn)

    # ---- this face's own ----

    def _load(self, *_):
        self.load()

    def _undo(self):
        self.undo()

    def review_send(self):
        """Review and send: each change in words with who it touches, a ✕
        each, the line to followers filled in; Send is one save."""
        if not self.draft or not len(self.draft) or self.busy:
            return
        from .send import SendDialog
        dlg = SendDialog(self)
        if dlg.exec():
            self.send(dlg.why())

    def _undo_button(self):
        self.undo_btn.setVisible(self.author())

    def _undo_entries(self):
        """Undo as it opens: the last change not sent, the last save or send of this window's, then History."""
        self.undo_menu.clear()
        for label, what, on in self.undo_entries():
            if what and what[0] == "history":
                self.undo_menu.addSeparator()
            a = self.undo_menu.addAction(label)
            a.setEnabled(bool(on and what))
            if what and what[0] == "take":
                a.triggered.connect(lambda _=False, i=what[1]: self.take_change(i))
            elif what and what[0] == "undo":
                a.triggered.connect(self._undo)
            elif what and what[0] == "history":
                a.triggered.connect(self._history)

    def undo_key(self):
        if not PlanCore.undo_key(self) and self.undo_btn.isVisible():
            self.undo_btn.showMenu()

    def _history(self):
        from .send import HistoryDialog
        HistoryDialog(self).exec()

    def study(self, kind, key, cids=None, name=""):
        if PlanCore.study(self, kind, key, cids, name):
            self.close()  # Anki's Study screen is on it; the window would sit over it
