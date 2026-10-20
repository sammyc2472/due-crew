"""Round five's New plan (docs/planner.md): the one way to start a plan in
Anki, where New plan from a calendar and New plan from a deck were two
windows. Its name, the deck, what it ends with (the exam and its day,
so the plan knows its end from the first minute), and the course's
calendar if there is one: pasted in or its file dropped on the box, read
on this computer as it's typed. Make the plan puts it on duecrew.com as
mine (POST /plans, then the builder's save) and opens it in Your plans:
with a calendar, its sessions are its dates, named and with no cards (the
author puts every card on: nothing is picked for them), and its quizzes
its quizzes; without one, the deck beside an empty plan, to tick what the
exam covers. A friend's plan instead: its code, Follow.
Names are the calendar's and the deck's: plain text everywhere."""

import os

from aqt.qt import (
    QDate, QDateEdit, QDialog, QDialogButtonBox, QComboBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLineEdit,
    QPushButton, Qt, QTimer, QVBoxLayout,
)

from ..ui import attach_alive, confirm, heading, role
from .. import plans as P
from . import edits as E
from . import reading as R
from .start_window import EXAMPLE, FILES, DropBox, pdf_text
from .widgets import link, plain


def read_file(path):
    """(text, why): a calendar's file read on this computer (as the calendar window read it)."""
    name = os.path.basename(str(path))
    kind = R.kind_of_file(name)
    try:
        if os.path.getsize(path) > (R.BIG_MAX if kind in R.BIG else R.FILE_MAX):
            return "", "That file is too big to be a calendar."
        if kind == "pdf":
            text = pdf_text(path)
            if not text or not text.strip():
                return "", "That PDF's text couldn't be read here. Copy its text in instead."
            if R.scrambled(text):
                return "", "That PDF's text came out in pieces. Copy its text in instead."
            return text.replace("\r\n", "\n").replace("\r", "\n")[:R.TEXT_MAX], ""
        with open(path, "rb") as f:
            return R.from_file(name, f if kind in ("docx", "pptx") else f.read())
    except OSError:
        return "", "That file couldn't be opened."


class NewPlanWindow(QDialog):
    """decks: [(deck id, name, cards)], biggest first; ops: flow.NewOps, or a render's or test's own."""

    def __init__(self, parent, decks, ops, labs=False):
        super().__init__(parent)
        self.ops, self.labs = ops, bool(labs)
        self.decks = list(decks)
        self.sessions = []
        self.made = None       # a plan made whose dates didn't save: Make tries them again, on it
        self.file = ""
        self._named = ""       # the name a reading gave (a name typed in stays)
        self._ended = ("", "")  # the exam a reading gave (one typed in stays)
        attach_alive(self)
        self.setWindowTitle("New plan")
        self.setModal(False)
        self.setMinimumWidth(520)
        root = QVBoxLayout(self)
        heading(self, root)
        form = QFormLayout()
        self.name = QLineEdit()
        self.name.setMaxLength(60)
        self.name.setPlaceholderText("MS2 Block 2")
        form.addRow("Name", self.name)
        self.deck = QComboBox()
        for did, name, n in self.decks:
            self.deck.addItem(f"{name} · {n:,} cards", did)
        form.addRow("Deck", self.deck)
        ends = QHBoxLayout()
        self.end_name = QLineEdit()
        self.end_name.setMaxLength(60)
        self.end_name.setPlaceholderText("Block 2 exam (or leave it empty)")
        ends.addWidget(self.end_name, 1)
        self.end_day = QDateEdit()
        self.end_day.setCalendarPopup(True)
        self.end_day.setDisplayFormat("ddd d MMM yyyy")
        self.end_day.setDate(QDate.fromString(E._later(str(ops.today()), 28), "yyyy-MM-dd"))
        ends.addWidget(self.end_day)
        form.addRow("Ends with", ends)
        root.addLayout(form)
        row = QHBoxLayout()
        row.addWidget(role(plain("The course calendar"), "head"))
        row.addWidget(plain("optional", muted=True))
        row.addStretch(1)
        root.addLayout(row)
        self.text = DropBox(self._load_file)
        self.text.setPlaceholderText(EXAMPLE)
        self.text.setTabChangesFocus(True)
        self.text.setMinimumHeight(150)
        self._reading = QTimer(self)
        self._reading.setSingleShot(True)
        self._reading.setInterval(400)
        self._reading.timeout.connect(self._read)
        self.text.textChanged.connect(lambda: self._reading.start())
        root.addWidget(self.text)
        row = QHBoxLayout()
        self.said = plain("Read on this computer. Nothing is sent until you make the plan.", muted=True)
        row.addWidget(self.said, 1)
        row.addWidget(link("Choose a file…", self._choose))
        root.addLayout(row)
        if self.labs:
            root.addWidget(link("Session by session, with Claude's stand-in (labs)…", self._labs), 0, Qt.AlignmentFlag.AlignLeft)
        buttons = QDialogButtonBox()
        buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole).clicked.connect(self.reject)
        self.make_btn = QPushButton("Make the plan")
        self.make_btn.setDefault(True)
        self.make_btn.clicked.connect(self._make)
        buttons.addButton(self.make_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        root.addWidget(buttons)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        root.addWidget(line)
        root.addWidget(plain("Following a friend's plan instead?", muted=True))
        row = QHBoxLayout()
        self.code = QLineEdit()
        self.code.setMaxLength(40)
        self.code.setPlaceholderText("Their code")
        self.code.returnPressed.connect(self._follow)
        row.addWidget(self.code, 1)
        row.addWidget(link("Follow", self._follow))
        root.addLayout(row)
        self.name.textChanged.connect(lambda _t: self._buttons())
        self._buttons()

    def _buttons(self):
        self.make_btn.setEnabled(bool(self.name.text().strip()) and self.deck.count() > 0)

    # ---- the calendar ----

    def _choose(self):
        path, _f = QFileDialog.getOpenFileName(self, "A course's calendar", "", FILES)
        if path:
            self._load_file(path)

    def _load_file(self, path):
        text, why = read_file(path)
        if why:
            self.said.setText(why)
            return
        self.file = os.path.basename(str(path))
        self.text.setPlainText(text)
        self._read()

    def _read(self):
        text = self.text.toPlainText()
        self.sessions = R.number_weeks(R.read_calendar(text, self.ops.today())) if text.strip() else []
        if not text.strip():
            self.said.setText("Read on this computer. Nothing is sent until you make the plan.")
            return
        if not self.sessions:
            self.said.setText("No sessions found yet: each needs a date (Mon 10/26, Oct 26, 2026-10-26).")
            return
        n_ev = sum(1 for s in self.sessions if s["kind"] in R.EVENT_KINDS)
        n = len(self.sessions) - n_ev
        self.said.setText(f"Found {n:,} session{'s' if n != 1 else ''} and {n_ev:,} quiz{'zes' if n_ev != 1 else ''} or exam"
                          f"{'s' if n_ev != 1 else ''}.")
        if not self.name.text().strip() or self.name.text() == self._named:
            self._named = R.name_from(text) or R.file_name(self.file)
            self.name.setText(self._named)
        exams = [s for s in self.sessions if s["kind"] == "exam"]
        if exams and (not self.end_name.text().strip() or self.end_name.text() == self._ended[0]):
            last = exams[-1]
            self._ended = (" ".join(str(last["title"]).split())[:60], last["date"])
            self.end_name.setText(self._ended[0])
            self.end_day.setDate(QDate.fromString(last["date"], "yyyy-MM-dd"))

    # ---- making it ----

    def doc(self):
        """(doc, dates) as Make the plan would make it."""
        deck = next((name for did, name, _n in self.decks if did == self.deck.currentData()), "")
        end_name = self.end_name.text().strip()
        end_day = self.end_day.date().toString("yyyy-MM-dd") if end_name or not self.sessions else None
        doc, uids = E.new_plan_doc(deck, self.sessions, end_name, end_day)
        return doc, len(uids)

    def _make(self):
        name = self.name.text().strip()
        if not name:
            return
        try:
            doc, n = self.doc()
        except E.Refused as e:
            self.said.setText(str(e))
            return
        n_ev = len(doc.get("events") or [])
        if self.made is None and not confirm(
                self, f"Make {name}?",
                (f"{n:,} date{'s' if n != 1 else ''} and {n_ev:,} quiz{'zes' if n_ev != 1 else ''} or exams, "
                 "the dates with no cards yet. " if n else
                 "An empty plan that ends with " + (f"{doc['end'] and P.fmt_day(doc['end'])}. " if doc.get("end") else "nothing yet. "))
                + "It's yours: nobody follows it till you share its code.", "Make it"):
            return
        self.make_btn.setEnabled(False)
        self.said.setText("Making it…")
        self.ops.make(self, name, doc, self._made, pid=self.made)

    def _made(self, got):
        self._buttons()
        if not got:
            self.said.setText("That didn't make it: check your connection, then try again.")
            return
        if got[0] == "made":
            self.made = got[1]
            self.said.setText(f"The plan is on duecrew.com, but its dates didn't save. {got[2]} Make the plan tries them again, on it.")
            return
        outcome, what = got
        if outcome != "saved":
            self.said.setText(str(what))
            return
        self.made = None
        self.ops.open_plan(what.get("id"))
        self.accept()

    def _follow(self):
        code = self.code.text().strip()
        if code:
            self.ops.follow(code)
            self.accept()

    def _labs(self):
        self.ops.labs_window()
        self.accept()
