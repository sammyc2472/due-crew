"""Your plans' History and Updates tabs (3.9.3), the builder's, for a
plan's authors. History: every save, who and what, newest first; the
latest one undoes (the builder's Undo). Updates: what the authors said to
followers, newest first, and a post of one line to them (five a day a
plan), with how many followers' Anki has this version. Each is read when
its tab opens, one request; names and words are the authors': plain text."""

from aqt.qt import QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, Qt, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from ..ui import esc, note
from . import remote
from .model import ago
from .pip_note import PipNote

ROLE = Qt.ItemDataRole.UserRole


def _plain(text="", muted=False):
    w = QLabel(str(text))
    w.setTextFormat(Qt.TextFormat.PlainText)
    w.setWordWrap(True)
    return note(w) if muted else w


def _list():
    t = QTreeWidget()
    t.setHeaderHidden(True)
    t.setRootIsDecorated(False)
    t.setColumnCount(3)
    h = t.header()
    h.setStretchLastSection(False)
    h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
    h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
    h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
    return t


class _Lazy(QWidget):
    """A tab read when it opens (and again after a save), its plan's only."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.got = None       # (plan id, version) the list on show is of
        self.loading = False

    def shown(self, win):
        return win.author()

    def plan_loaded(self, win):
        if self.got != self._now():  # another plan, or a save: read again; a setting that kept the version, not
            self.got = None
            if self.isVisible() and not self.loading:
                self._read()

    def showEvent(self, e):
        super().showEvent(e)
        if self.win.author() and self.got != self._now() and not self.loading:
            self._read()

    def _now(self):
        return (self.win.plan.get("id"), self.win.raw.get("version")) if self.win.plan and self.win.raw else None


class HistoryTab(_Lazy):
    """Every save of the plan, newest first; Undo on the latest."""

    def __init__(self, win):
        super().__init__(win)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 8, 0, 0)
        self.said = PipNote(lambda: self.win.ops.pip(), muted=True, size=48)
        root.addWidget(self.said)
        self.list = _list()
        root.addWidget(self.list, 1)
        root.addStretch(0)  # with no list, the words stay at the top
        row = QHBoxLayout()
        row.addStretch(1)
        self.again_btn = QPushButton("Try again")
        self.again_btn.setFlat(True)
        self.again_btn.clicked.connect(self._read)
        row.addWidget(self.again_btn)
        self.undo_btn = QPushButton("Undo the latest")
        self.undo_btn.setToolTip("<span>Puts back what the latest save changed, for everyone (as the builder's Undo)</span>")
        self.undo_btn.clicked.connect(self._undo)
        row.addWidget(self.undo_btn)
        root.addLayout(row)
        self.rows = []
        self._show([], "")

    def _read(self):
        now = self._now()
        if now is None:
            return
        self.loading = True
        self._show([], "Loading…")
        pid = now[0]
        self.win.ops.ask(self.win, lambda cl: remote.log(cl, pid), lambda got: self._got(now, got))

    def _got(self, now, rows):
        self.loading = False
        if now != self._now():  # an answer for the last plan (or version): this one's, if it's on show
            if self.isVisible() and self.win.author():
                self._read()
            return
        if rows is None:
            self._show([], "Couldn't load the history.", again=True)
            return
        self.got = now
        # a new plan's: Pip peeking in, as Settings › Pip says
        self._show(rows, "" if rows else "No saves yet. Each one shows here, who made it and what it changed, "
                   "and the latest can be undone.", pose=None if rows else "peek")

    def _show(self, rows, said, again=False, pose=None):
        self.rows = rows
        self.list.clear()
        me = self.win.ops.me()
        for x in rows:
            who = "You" if me and x.get("uid") == me else str(x.get("name") or "?")
            it = QTreeWidgetItem([who, str(x.get("summary") or ""), ago(x.get("at"))])
            it.setToolTip(1, f"<span>{esc(x.get('summary') or '')}</span>")
            self.list.addTopLevelItem(it)
        self.list.setVisible(bool(rows))
        self.said.say(said, pose, "Pip, peeking in")
        self.said.setVisible(bool(said))
        self.again_btn.setVisible(again)
        self.undo_btn.setVisible(bool(rows) and bool(rows[0].get("undo")))
        self.undo_btn.setEnabled(not self.win.busy)

    def busy_changed(self, win):
        self.undo_btn.setEnabled(not win.busy)

    def _undo(self):
        if not self.rows or not self.rows[0].get("undo"):
            return
        self.win._can_undo((self.win.plan["id"], self.rows[0]["version"]))
        self.win._undo()


class UpdatesTab(_Lazy):
    """What the authors said to followers; a post of one line to them."""

    def __init__(self, win):
        super().__init__(win)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 8, 0, 0)
        row = QHBoxLayout()
        self.box = QLineEdit()
        self.box.setMaxLength(200)
        self.box.textChanged.connect(self._count)
        self.box.returnPressed.connect(self._post)
        row.addWidget(self.box, 1)
        self.count = _plain("0 / 200", muted=True)
        row.addWidget(self.count)
        self.post_btn = QPushButton("Post")
        self.post_btn.clicked.connect(self._post)
        row.addWidget(self.post_btn)
        root.addLayout(row)
        self.reached = _plain(muted=True)
        root.addWidget(self.reached)
        self.status = PipNote(lambda: self.win.ops.pip())
        root.addWidget(self.status)
        self.said = _plain(muted=True)
        root.addWidget(self.said)
        self.list = _list()
        self.list.itemSelectionChanged.connect(self._buttons)
        root.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.again_btn = QPushButton("Try again")
        self.again_btn.setFlat(True)
        self.again_btn.clicked.connect(self._read)
        row.addWidget(self.again_btn)
        self.remove_btn = QPushButton("Remove it")
        self.remove_btn.setFlat(True)
        self.remove_btn.clicked.connect(self._remove)
        row.addWidget(self.remove_btn)
        root.addLayout(row)
        self.rows = []
        self.posting = False
        self._show([], "")

    def plan_loaded(self, win):
        if (win.plan or {}).get("id") != getattr(self, "pid", None):
            self.pid = (win.plan or {}).get("id")
            self.status.setText("")  # the last plan's "Posted." isn't this one's
        if win.author():
            n = int((win.plan or {}).get("followers") or 0)
            self.box.setPlaceholderText(f"Post to the {n:,} following" if n else "Post to its followers (nobody follows it yet)")
            r = (win.raw or {}).get("reached") or [0, 0]
            self.reached.setText(f"This version is in {int(r[0]):,} of {int(r[1]):,} followers' Anki."
                                 if isinstance(r, list) and len(r) == 2 and r[1] else "")
            self.reached.setVisible(bool(self.reached.text()))
        super().plan_loaded(win)

    def _count(self, text):
        self.count.setText(f"{len(text.encode('utf-16-le')) // 2} / 200")  # as the box and the server count (an emoji is two)
        self._buttons()

    def _buttons(self):
        busy = self.win.busy or self.loading or getattr(self, "posting", False)
        self.post_btn.setEnabled(bool(self.box.text().strip()) and not busy)
        x = self._picked()
        self.remove_btn.setVisible(bool(x and x.get("remove")))
        self.remove_btn.setEnabled(not busy)

    def _picked(self):
        it = self.list.currentItem()
        i = it.data(0, ROLE) if it is not None else None
        return self.rows[i] if isinstance(i, int) and 0 <= i < len(self.rows) else None

    def busy_changed(self, win):
        self._buttons()

    def _read(self):
        now = self._now()
        if now is None:
            return
        self.loading = True
        self._show([], "Loading…")
        pid = now[0]
        self.win.ops.ask(self.win, lambda cl: remote.posts(cl, pid), lambda got: self._got(now, got))

    def _got(self, now, rows):
        self.loading = False
        if now != self._now():  # an answer for the last plan (or version): this one's, if it's on show
            if self.isVisible() and self.win.author():
                self._read()
            return
        if rows is None:
            self._show([], "Couldn't load the updates.", again=True)
            return
        self.got = now
        self._show(rows, "" if rows else "Nothing posted yet. Followers see a post in Anki and on their home page.")

    def _show(self, rows, said, again=False):
        self.rows = rows
        self.list.blockSignals(True)
        self.list.clear()
        me = self.win.ops.me()
        for i, x in enumerate(rows):
            who = "You" if me and x.get("uid") == me else str(x.get("name") or "?")
            if x.get("coauthor"):
                who += " (co-author)"
            it = QTreeWidgetItem([who, str(x.get("text") or "") + (" · with a save" if x.get("withSave") else ""), ago(x.get("at"))])
            it.setData(0, ROLE, i)
            it.setToolTip(1, f"<span>{esc(x.get('text') or '')}</span>")
            self.list.addTopLevelItem(it)
        self.list.blockSignals(False)
        self.list.setVisible(bool(rows))
        self.said.setText(said)
        self.said.setVisible(bool(said))
        self.again_btn.setVisible(again)
        self._buttons()

    def _post(self):
        text = " ".join(self.box.text().split())
        now = self._now()
        if not text or now is None or self.win.busy or self.posting:
            return  # (Enter again while it's on its way: one post)
        self.posting = True
        self.post_btn.setEnabled(False)
        self.status.setText("Posting…")

        def done(got):
            self.posting = False
            if now != self._now():
                return
            if not got:
                self.status.setText("That didn't post. Try again.")
                self._buttons()
                return
            outcome, what = got
            if outcome != "saved":
                self.status.setText(str(what))
                self._buttons()
                return
            self.box.clear()
            self.status.say("Posted. Followers see it in Anki and on their home page.", "hello", "Pip, waving")
            self._read()
        self.win.ops.ask(self.win, lambda cl: remote.post(cl, now[0], text), done)

    def _remove(self):
        x, now = self._picked(), self._now()
        if not x or now is None:
            return

        def done(ok):
            if now != self._now():
                return
            self.status.setText("" if ok else "That didn't work. Try again.")
            if ok:
                self._read()
        self.win.ops.ask(self.win, lambda cl: remote.unpost(cl, now[0], x["id"]), done)
