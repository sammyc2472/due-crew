"""Round five's Review and send, and History (docs/planner.md). Review:
each change waiting under the plan in words, who it touches (a date that
opened: anyone who has its cards keeps them; one still to come: not open
for anyone yet), a ✕ each to take one out, and the line followers get
with it, filled in from the changes for the author to say better. Send is
one save (PUT /plans/{id} with its post). History: every save of the
plan, and Undo the latest. Names and words: plain text."""

from aqt.qt import QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QPlainTextEdit, QPushButton, QScrollArea, Qt, QVBoxLayout, QWidget

from ..ui import attach_alive, heading, role
from . import ops as O
from .history_tab import HistoryTab
from .widgets import frame, plain, small


class SendDialog(QDialog):
    """Send N changes to N following. win: the PlanWindow (its draft)."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        attach_alive(self)
        n = win.followers()
        self.setWindowTitle(f"Send {len(win.draft):,} change{'s' if len(win.draft) != 1 else ''} to {n:,} following"
                            if n else "Save your changes")
        self.setMinimumWidth(560)
        root = QVBoxLayout(self)
        self.head = heading(self, root)
        self.list_box, self.list_lay = frame("card", margins=(10, 6, 10, 6), spacing=0)
        scroll = QScrollArea()  # forty changes scroll here; the window stays its size
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self.list_box)
        scroll.viewport().setAutoFillBackground(False)
        scroll.setMaximumHeight(320)
        self.list_scroll = scroll
        root.addWidget(scroll)
        root.addWidget(plain("Tell them why", muted=True))
        self.why_box = QPlainTextEdit()
        self.why_box.setTabChangesFocus(True)
        self.why_box.setFixedHeight(72)
        self.why_box.textChanged.connect(self._count)
        root.addWidget(self.why_box)
        self.why_box.setToolTip("<span>Followers see it with the change, on the plan and on their board</span>")
        self.count = plain(muted=True)
        root.addWidget(self.count, 0, Qt.AlignmentFlag.AlignRight)
        buttons = QDialogButtonBox()
        buttons.addButton("Back", QDialogButtonBox.ButtonRole.RejectRole).clicked.connect(self.reject)
        self.go = QPushButton(f"Send to {n:,}" if n else "Save")
        self.go.setProperty("dc", "go")
        self.go.setDefault(True)
        self.go.clicked.connect(self.accept)
        buttons.addButton(self.go, QDialogButtonBox.ButtonRole.AcceptRole)
        root.addWidget(buttons)
        self._typed = False
        self._fill()

    def _fill(self):
        win = self.win
        while self.list_lay.count():
            w = self.list_lay.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.deleteLater()
        _doc, changes, _dropped = win.draft.replay(win.ctx())
        for i, c in enumerate(changes):
            for j, x in enumerate(c["entries"]):
                row = QWidget()
                rl = QHBoxLayout(row)
                rl.setContentsMargins(0, 6, 0, 6)
                verb = plain(str(x["verb"]).capitalize(), muted=True)
                verb.setFixedWidth(72)
                rl.addWidget(verb, 0, Qt.AlignmentFlag.AlignTop)
                words = QVBoxLayout()
                words.setSpacing(2)
                words.addWidget(role(plain(x["what"]), "head"))
                if x.get("detail"):
                    words.addWidget(plain(x["detail"], muted=True))
                if x.get("who"):
                    words.addWidget(plain(x["who"], dc="warn" if x["who"].startswith("Open since") else None, muted=True))
                if j == 0 and c["op"].get("by") == "ai":
                    words.addWidget(plain("From your AI app", muted=True))
                rl.addLayout(words, 1)
                if j == 0:
                    rl.addWidget(small("✕", lambda i=i: self._take(i), "Take this change out (it's never sent)"),
                                 0, Qt.AlignmentFlag.AlignTop)
                self.list_lay.addWidget(row)
        n = len(win.draft)
        self.setWindowTitle("Due Crew")
        self.head.setText(f"Send {n:,} change{'s' if n != 1 else ''} to {win.followers():,} following"
                          if win.followers() else f"Save {n:,} change{'s' if n != 1 else ''}")
        if not self._typed:
            self.why_box.blockSignals(True)
            self.why_box.setPlainText(O.send_line(changes))
            self.why_box.blockSignals(False)
        self._count()

    def _take(self, i):
        self.win.take_change(i)
        if not self.win.draft or not len(self.win.draft):
            self.reject()
            return
        self._fill()

    def _count(self):
        text = self.why_box.toPlainText()
        if self.why_box.hasFocus():
            self._typed = True
        n = len(" ".join(text.split()).encode("utf-16-le")) // 2
        self.count.setText(f"{n} / {O.WHY_MAX}")
        self.go.setEnabled(n <= O.WHY_MAX)

    def why(self):
        return " ".join(self.why_box.toPlainText().split())


class HistoryDialog(QDialog):
    """Every save of the plan, newest first; Undo the latest."""

    def __init__(self, win):
        super().__init__(win)
        attach_alive(self)
        self.setWindowTitle("History")
        self.setMinimumSize(640, 420)
        root = QVBoxLayout(self)
        heading(self, root, f"History · {win.plan_name() or 'the plan'}")
        self.tab = HistoryTab(win)
        self.tab.on_undo = self.accept
        root.addWidget(self.tab, 1)
        close = QPushButton("Close")  # beside Undo the latest: one row of buttons
        close.setAutoDefault(False)
        close.clicked.connect(self.reject)
        self.tab.button_row.addWidget(close)
