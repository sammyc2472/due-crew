"""Your plans' notes on a day (3.9.3), the builder's: anyone in the plan
writes one ("lab day, keep it light"); on a plan in the library, only its
authors. Read once when a plan is picked or read again (one request, on
that click; a save doesn't read them again), shown under the Dates tab's
picked date, quiz or review day, and by day under a week. A note's writer
takes it off, or an author. Names and words are the plan's people's:
plain text, escaped in a tooltip."""

from aqt.qt import QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, Qt, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from ..ui import esc, note
from .. import plans as P
from . import remote

ROLE = Qt.ItemDataRole.UserRole


def _plain(text="", muted=False):
    w = QLabel(str(text))
    w.setTextFormat(Qt.TextFormat.PlainText)
    w.setWordWrap(True)
    return note(w) if muted else w


class DayNotes(QWidget):
    """The picked day's notes, and a new one on it."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.notes, self.of = [], None   # the plan's notes, and the plan id they're of (None: not read yet)
        self.library = False
        self.days, self.day, self.dated = set(), None, False
        self.shown = []                  # the notes on the list, in its order
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 4, 0, 0)
        self.list = QTreeWidget()
        self.list.setHeaderHidden(True)
        self.list.setRootIsDecorated(False)
        self.list.setColumnCount(2)
        h = self.list.header()
        h.setStretchLastSection(False)
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.list.itemSelectionChanged.connect(self._buttons)
        root.addWidget(self.list)
        row = QHBoxLayout()
        self.box = QLineEdit()
        self.box.setMaxLength(280)
        self.box.textChanged.connect(lambda _t: self._buttons())
        self.box.returnPressed.connect(self._add)
        row.addWidget(self.box, 1)
        self.add_btn = QPushButton("Add the note")
        self.add_btn.clicked.connect(self._add)
        row.addWidget(self.add_btn)
        self.rm_btn = QPushButton("Take it off")
        self.rm_btn.clicked.connect(self._remove)
        row.addWidget(self.rm_btn)
        root.addLayout(row)
        self.said = _plain(muted=True)
        root.addWidget(self.said)
        self.sending = False
        self._draw()

    # ---- the window asks ----

    def forget(self):
        """Reload: the notes are read again with the plan."""
        self.of = None

    def plan_loaded(self, pid, library):
        """A plan in the window: its notes, read once (a save keeps them)."""
        self.library = library
        if self.of == pid:
            self._draw()
            return
        if self.of is not None:
            self.box.clear()  # what I was typing was a note for the last plan
        self.notes, self.of = [], None
        self.said.setText("")
        self._draw()

        def done(got):
            if (self.win.plan or {}).get("id") != pid:
                return  # another plan since
            if got is None:
                self.said.setText("Its notes didn't load. Reload to try again.")
            else:
                self.notes, self.of = got, pid
            self._draw()
        self.win.ops.ask(self.win, lambda cl: remote.notes(cl, pid), done)

    def show_for(self, days, day=None, dated=False):
        """The notes on `days`; a new one goes on `day` (None: none here, as
        a week's). dated: each line says its day."""
        self.days, self.day, self.dated = set(days), day, dated
        if self.of is not None:
            self.said.setText("")
        self._draw()

    # ---- drawn ----

    def _writes(self):
        return self.of is not None and bool(self.day) and not (self.library and not self.win.author())

    def _draw(self):
        self.shown = sorted((x for x in self.notes if x.get("day") in self.days), key=lambda x: (str(x["day"]), x["id"]))
        self.list.blockSignals(True)
        self.list.clear()
        for i, x in enumerate(self.shown):
            who = "You" if x.get("mine") else str(x.get("name") or "?")
            if self.dated:
                who = f"{P.fmt_day(x['day'])} · {who}"
            it = QTreeWidgetItem([who, str(x.get("text") or "")])
            it.setData(0, ROLE, i)
            it.setToolTip(1, f"<span>{esc(x.get('text') or '')}</span>")
            self.list.addTopLevelItem(it)
        self.list.blockSignals(False)
        if self.shown:  # as tall as its notes, up to four; more scroll
            pad = self.list.height() - self.list.viewport().height() if self.list.isVisible() else 2 * self.list.frameWidth() + 12
            self.list.setFixedHeight(self.list.sizeHintForRow(0) * min(len(self.shown), 4) + max(pad, 2 * self.list.frameWidth()))
        self.list.setVisible(bool(self.shown))
        writes = self._writes()
        self.box.setVisible(writes)
        self.add_btn.setVisible(writes)
        if writes:
            self.box.setPlaceholderText(f"A note on {P.fmt_day(self.day)}, for everyone in the plan")
        self.said.setVisible(bool(self.said.text()))
        self.setVisible(bool(self.shown) or writes or bool(self.said.text()))
        self._buttons()

    def _picked(self):
        it = self.list.currentItem()
        i = it.data(0, ROLE) if it is not None else None
        return self.shown[i] if isinstance(i, int) and 0 <= i < len(self.shown) else None

    def _buttons(self):
        x = self._picked()
        self.add_btn.setEnabled(bool(self.box.text().strip()) and not self.sending)
        self.rm_btn.setVisible(bool(x and x.get("remove")))
        self.rm_btn.setEnabled(not self.sending)

    def _say(self, text):
        self.said.setText(text)
        self._draw()

    # ---- what the buttons do ----

    def _add(self):
        text, day, pid = " ".join(self.box.text().split()), self.day, self.of
        if not text or not self._writes() or self.sending:
            return
        self.sending = True
        self._buttons()

        def done(got):
            self.sending = False
            if pid != self.of:
                self._buttons()
                return
            if not got:
                self._say("That note didn't post. Try again.")
            elif got[0] != "saved":
                self._say(str(got[1]))
            else:
                self.notes.append({"id": got[1]["id"], "day": day, "text": str(got[1].get("text") or text),
                                   "name": "You", "mine": True, "remove": True})
                self.box.clear()
                self._say("")
        self.win.ops.ask(self.win, lambda cl: remote.add_note(cl, pid, day, text), done)

    def _remove(self):
        x, pid = self._picked(), self.of
        if not x or not x.get("remove") or self.sending:
            return
        self.sending = True
        self._buttons()

        def done(ok):
            self.sending = False
            if pid != self.of:
                self._buttons()
                return
            if ok:
                self.notes = [y for y in self.notes if y is not x]
            self._say("" if ok else "That note didn't go. Try again.")
        self.win.ops.ask(self.win, lambda cl: remote.remove_note(cl, pid, x["id"]), done)
