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
exam covers. 3.9.5: with no calendar, a Shape and From (a tag folder of
the deck; shapes.py): each tag in it a date, one a day, done by the exam
or a week each, the plan made filled; From left at None, it's as it was.
A friend's plan instead: its code, Follow.
Names are the calendar's and the deck's: plain text everywhere."""

import os

from aqt.qt import (
    QButtonGroup, QColor, QComboBox, QDate, QDateEdit, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame,
    QHBoxLayout, QLayout, QLineEdit, QPainter, QPushButton, QRectF, QSizePolicy, Qt, QTimer, QVBoxLayout, QWidget,
)

from ..ui import _mix, attach_alive, confirm, esc, heading, role, tone
from .. import plans as P
from . import edits as E
from . import reading as R
from . import shapes as SH
from .start_window import EXAMPLE, FILES, DropBox, pdf_text
from .widgets import mark, tool, plain

NO_FROM = "None (an empty plan)"
PICK_FROM = "Pick a folder of tags: each becomes a date."


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


class ShapePic(QFrame):
    """A shape's picture: three weeks of a calendar, each day a cell in the
    colour of what the shape makes of it (shapes.cell), in the board's."""

    CELL, GAP, ROWS = (13, 11), (3, 3), 3

    def __init__(self, shape):
        super().__init__()
        self.shape = shape
        (w, h), (gx, gy) = self.CELL, self.GAP
        self.setFixedSize(7 * w + 6 * gx, self.ROWS * h + (self.ROWS - 1) * gy)

    def paintEvent(self, _e):  # noqa: N802 (Qt's)
        accent, bg = tone("accent"), tone("bg")
        fill = {"on": accent, "off": tone("well"), "soft": _mix(accent, bg, .6), "free": _mix(accent, bg, .6),
                "exam": tone("hours")}
        (w, h), (gx, gy) = self.CELL, self.GAP
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        for r in range(self.ROWS):
            for c in range(7):
                p.setBrush(QColor(fill[SH.cell(self.shape, r, c)]))
                p.drawRoundedRect(QRectF(c * (w + gx), r * (h + gy), w, h), 2, 2)
        p.end()


class ShapeTile(QPushButton):
    """One of the shapes to pick: its name over its picture, ticked as the
    window's tool buttons are (the accent round it). Its parts let a click
    through to it."""

    def __init__(self, shape, text):
        super().__init__()
        self.shape = shape
        self.setProperty("dc", "tool")
        self.setCheckable(True)
        self.setAutoDefault(False)
        self.setAccessibleName(text)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(6)
        self.words = role(plain(text), "head")
        self.words.setWordWrap(False)
        self.pic = ShapePic(shape)
        for w in (self.words, self.pic):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            lay.addWidget(w)
        lay.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)  # as big as its parts, not a button's words
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


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
        self.shape = "day"
        self.tree = None       # the picked deck's tags (shapes.tree_of), read once a deck
        self._decks = {}       # deck id: (tree, its folders)
        self._kids = {}        # (deck id, folder): its tags and their cards
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
        self.tiles = QWidget()
        row = QHBoxLayout(self.tiles)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.shape_btns = {}
        group = QButtonGroup(self)
        for key, label in SH.SHAPES:
            b = ShapeTile(key, label)
            b.setChecked(key == self.shape)
            b.clicked.connect(lambda _=False, key=key: self._shape(key))
            group.addButton(b)
            row.addWidget(b, 1)
            self.shape_btns[key] = b
        form.addRow("Shape", self.tiles)
        self.frm = QComboBox()
        self.frm.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.frm.setMinimumContentsLength(24)  # a long folder's path ends in … rather than widening the window
        self.frm.setMaxVisibleItems(20)
        self.frm.currentIndexChanged.connect(lambda _i: self._from())
        form.addRow("From", self.frm)
        self.form = form
        root.addLayout(form)
        self.line = plain(PICK_FROM, muted=True)
        root.addWidget(self.line)
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
        row.addWidget(tool("Choose a file…", self._choose))
        root.addLayout(row)
        if self.labs:
            root.addWidget(tool("Session by session, with Claude's stand-in (labs)…", self._labs), 0, Qt.AlignmentFlag.AlignLeft)
        buttons = QDialogButtonBox()
        buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole).clicked.connect(self.reject)
        self.make_btn = QPushButton("Make the plan")
        self.make_btn.setDefault(True)
        self.make_btn.setProperty("dc", "go")  # 3.9.5: in the accent, as the mock had it (the Shape tiles kept ui._mark from it)
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
        row.addWidget(tool("Follow", self._follow))
        root.addLayout(row)
        self.name.textChanged.connect(lambda _t: self._buttons())
        self.deck.currentIndexChanged.connect(lambda _i: self._deck())
        self.end_name.textChanged.connect(lambda _t: self._line())
        self.end_day.dateChanged.connect(lambda _d: self._line())
        self._deck()

    def _buttons(self):
        laid = self._laid()
        self.make_btn.setEnabled(bool(self.name.text().strip()) and self.deck.count() > 0
                                 and not (laid and laid.get("why")))

    # ---- 3.9.5: a shape, from a tag folder ----

    def _deck(self):
        """The picked deck's tag folders in From (None first: as before shapes), read once a deck."""
        did = self.deck.currentData()
        if did is not None and did not in self._decks:
            tree = SH.tree_of(self.ops.index(did))
            self._decks[did] = (tree, SH.folders(tree))
        self.tree, folders = self._decks.get(did) or (None, [])
        self.frm.blockSignals(True)
        self.frm.clear()
        self.frm.addItem(NO_FROM, None)
        names = SH.labels(folders)
        for path in folders:
            self.frm.addItem(names[path], path)
            self.frm.setItemData(self.frm.count() - 1, f"<span>{esc(path)}</span>", Qt.ItemDataRole.ToolTipRole)
        self.frm.blockSignals(False)
        self._shown()

    def _shown(self):
        """Shape and From while there's a folder to fill from and no calendar (a calendar's sessions win)."""
        on = self.frm.count() > 1 and not self.sessions
        for w in (self.tiles, self.frm):
            w.setVisible(on)
            label = self.form.labelForField(w)
            if label is not None:
                label.setVisible(on)
        self.line.setVisible(on)
        self._line()

    def _shape(self, key):
        self.shape = key
        for k, b in self.shape_btns.items():
            b.setChecked(k == key)
        self._line()

    def _from(self):
        path = self.frm.currentData()
        if path and (not self.name.text().strip() or self.name.text() == self._named):
            self._named = SH.name_of(path)
            self.name.setText(self._named)
        self._line()

    def picked(self):
        """The folder From has picked, while Shape and From show; else None (as before shapes)."""
        return self.frm.currentData() if self.frm.count() > 1 and not self.sessions else None

    def _end(self):
        return self.end_day.date().toString("yyyy-MM-dd")

    def _laid(self):
        """shapes.lay's dates for the shape and the folder picked, or None (none picked)."""
        path = self.picked()
        if not path:
            return None
        key = (self.deck.currentData(), path)
        if key not in self._kids:
            self._kids[key] = SH.kids(self.tree, path)
        return SH.lay(self.shape, self._kids[key], self.ops.today(), self._end())

    def _line(self):
        laid = self._laid()
        if laid is None:
            words, late = PICK_FROM, False
        else:
            words, late = SH.line(laid, self._end(), self.end_name.text())
        self.line.setText(words)
        mark(self.line, "dc", "bad" if late else "note")  # in red on the plan window's band for a fill past the exam
        self.line.setContentsMargins(*((6, 3, 6, 3) if late else (0, 0, 0, 0)))
        self._buttons()

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
        self._shown()
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
        end_day = self._end() if end_name or not self.sessions else None
        doc, uids = SH.new_doc(deck, self.sessions, end_name, end_day, self._laid(), self.tree)
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
        laid = self._laid()
        if self.made is None and not confirm(
                self, f"Make {name}?",
                (f"{n:,} date{'s' if n != 1 else ''} from {SH.name_of(self.picked())}, done {P.fmt_day(laid['last'])}. "
                 if laid else
                 f"{n:,} date{'s' if n != 1 else ''} and {n_ev:,} quiz{'zes' if n_ev != 1 else ''} or exams, "
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
