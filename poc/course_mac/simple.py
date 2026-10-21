"""The window everyone sees first (0.2.0). Paste a calendar and press Make my
course: the deck is picked, the calendar read, every lecture read (the Mac's
model if it's on, plain matching if not), and each lecture's cards opened on
its day. Then a list: each lecture, its cards, one Open. Everything else
(rows, objectives, search words, settings, the log) is in All the details
(ui.CourseWindow), one click away under More. Plain Qt, as ui.py; names
from a deck or a calendar go into plain-text labels and item texts."""

import datetime as dt
import time

from aqt import mw
from aqt.qt import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QMenu,
    QMessageBox, QPlainTextEdit, QPushButton, QStackedWidget, Qt, QToolButton, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)
from aqt.utils import tooltip

from . import cal
from . import course as C
from . import jobs as J
from . import model as M

EXAMPLE = ("For example:\n\nBLOCK 2 · WEEK 1\nMon 10/26  LEC  Heart failure\n"
           "    SLG 1  Define systolic and diastolic heart failure\n"
           "Tue 10/27  LEC  Pressure-volume loops\nFri 10/30  QUIZ  Cardio quiz 1")


def _today():
    return dt.date.today()


def _bold(text, scale=1.0):
    lab = QLabel(text)
    lab.setTextFormat(Qt.TextFormat.PlainText)
    f = lab.font()
    f.setBold(True)
    if scale != 1.0:
        f.setPointSizeF(f.pointSizeF() * scale)
    lab.setFont(f)
    return lab


def _note(text=""):
    lab = QLabel(text)
    lab.setTextFormat(Qt.TextFormat.PlainText)
    lab.setWordWrap(True)
    return lab


def top_decks():
    """[(did, name, cards)] for the collection's top-level decks (not
    filtered ones): the biggest is where a new course starts."""
    out = []
    for r in mw.col.decks.all_names_and_ids():
        name = str(r.name)
        if "::" in name:
            continue
        d = mw.col.decks.get(int(r.id), default=False)
        if not d or d.get("dyn"):
            continue
        try:
            n = int(mw.col.decks.card_count(int(r.id), include_subdecks=True))
        except Exception:  # noqa: BLE001
            n = 0
        out.append((int(r.id), name, n))
    return sorted(out, key=lambda x: x[1].lower())


class SimpleWindow(QDialog):
    def __init__(self, app):
        super().__init__(mw)
        self.app = app
        self.loading = False
        self.adding = False  # the start page adds sessions to this course rather than making one
        self.checked = None  # (runner name, ok, words) once the model's been asked if it's ready
        self.setWindowTitle("Course on a Mac")
        self.resize(720, 640)
        root = QVBoxLayout(self)
        self.pages = QStackedWidget()
        root.addWidget(self.pages, 1)
        self.pages.addWidget(self._start_page())
        self.pages.addWidget(self._course_page())
        self.show_page()

    # ---- the start: paste, Make my course ----

    def _start_page(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.start_head = _bold("Make a course from your calendar", 1.3)
        lay.addWidget(self.start_head)
        lay.addWidget(_note("Paste your block's calendar: each session's date and title, and its objectives "
                            "under it if you have them."))
        self.cal_text = QPlainTextEdit()
        self.cal_text.setPlaceholderText(EXAMPLE)
        lay.addWidget(self.cal_text, 1)
        r = QHBoxLayout()
        self.load_btn = QPushButton("Load a file…")
        r.addWidget(self.load_btn)
        r.addStretch(1)
        lay.addLayout(r)
        self.deck_row = QWidget()
        dr = QHBoxLayout(self.deck_row)
        dr.setContentsMargins(0, 0, 0, 0)
        dr.addWidget(QLabel("Your deck"))
        self.deck = QComboBox()
        dr.addWidget(self.deck, 1)
        lay.addWidget(self.deck_row)
        self.auto_new = QCheckBox("Open each lecture's cards on its day")
        self.auto_new.setChecked(True)
        lay.addWidget(self.auto_new)
        self.start_state = _note()
        lay.addWidget(self.start_state)
        br = QHBoxLayout()
        br.addWidget(_note("Your Mac reads it with its own model when Apple Intelligence is on, and by plain "
                           "matching when it isn't. Nothing leaves this Mac."), 1)
        self.cancel_btn = QPushButton("Cancel")
        self.make_btn = QPushButton("Make my course")
        self.make_btn.setDefault(True)
        br.addWidget(self.cancel_btn)
        br.addWidget(self.make_btn)
        lay.addLayout(br)
        self.load_btn.clicked.connect(self.load_file)
        self.cancel_btn.clicked.connect(lambda: self.show_page())
        self.make_btn.clicked.connect(self.make)
        return w

    def start(self, adding=False):
        self.adding = adding
        c = self.app.course()
        self.start_head.setText(f"Add to {c['name']}" if adding and c else "Make a course from your calendar")
        self.make_btn.setText("Add these sessions" if adding else "Make my course")
        self.deck_row.setVisible(not adding)
        self.auto_new.setVisible(not adding)
        self.cancel_btn.setVisible(bool(self.app.data["courses"]))
        self.start_state.setText("")
        if not adding and mw.col:
            decks = top_decks()
            self.deck.clear()
            for did, name, n in decks:
                self.deck.addItem(f"{name} ({n:,} cards)", did)
            i = self.deck.findData(C.biggest_deck(decks))
            self.deck.setCurrentIndex(max(0, i))
        self.pages.setCurrentIndex(0)
        self.cal_text.setFocus()

    def load_file(self):
        path, _f = QFileDialog.getOpenFileName(self, "A calendar", "", "Text or PDF (*.txt *.csv *.md *.pdf);;Any (*)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    self.cal_text.setPlainText(f.read())
            except OSError as e:
                self.start_state.setText(str(e))
            return
        helper = M.HelperRunner(self.app_folder())
        if not helper.built():
            self.start_state.setText("Open the PDF, select its text, copy it, and paste it here.")
            return
        self.start_state.setText("Reading the PDF…")

        def work():
            try:
                return helper.pdf_text(path)
            finally:
                helper.close()
        self._bg(work, lambda t: (self.cal_text.setPlainText(t), self.start_state.setText("")),
                 lambda e: self.start_state.setText("Couldn't read that PDF. Copy its text and paste it here."))

    @staticmethod
    def app_folder():
        from .glue import FOLDER
        return FOLDER

    @staticmethod
    def _bg(fn, done, fail):
        from .ui import bg
        bg(fn, done, fail)

    def make(self):
        text = self.cal_text.toPlainText()
        if not text.strip():
            self.start_state.setText("Paste the calendar first.")
            return
        if not self.adding and not self.deck.currentData():
            self.start_state.setText("Pick the deck your cards are in.")
            return
        self.make_btn.setEnabled(False)
        self.start_state.setText("Reading the calendar…")
        cfg, today = self.app.cfg(), _today()
        df = bool(cfg.get("day_first"))

        def read():
            runner = self.ready_runner()
            return J.read_calendar(runner, text, today, self.app.log, int(cfg.get("calendar_chars") or 1800), df)[0]
        self._bg(read, lambda sessions: self.made(sessions, text),
                 lambda e: self.made(cal.read_lines(text, today, df), text))

    def made(self, sessions, text):
        self.make_btn.setEnabled(True)
        if not sessions:
            self.start_state.setText("No dated sessions in that. Each session needs a date at the start of its "
                                     "line, like 10/26 or Mon 26 Oct.")
            return
        today = _today().isoformat()
        if self.adding:
            c = self.app.course()
        else:
            deck = str(self.deck.currentText()).rsplit(" (", 1)[0]
            c = C.new_course(C.course_name(text, deck), int(self.deck.currentData()), deck)
            c["auto_open"] = self.auto_new.isChecked()
        have = {(l["date"], l["title"].lower()) for l in c["lectures"]}
        added = []
        for s in sessions:
            if (s["date"], s["title"].lower()) in have:
                continue
            lec = C.new_lecture(s["date"], s["title"], s["kind"], s.get("objectives") or [])
            c["lectures"].append(lec)
            added.append(lec)
        if not self.adding:
            C.wait_for_open(c, today)
            self.app.data["courses"].append(c)
            self.app.data["current"] = len(self.app.data["courses"]) - 1
            self.app.idx = None
        else:
            for lec in added:
                if lec["date"] < today:
                    lec["auto_done"] = "before"
        self.app.save()
        self.cal_text.clear()
        self.show_page()
        self.read_unread()

    # ---- the course: each lecture, its cards, Open ----

    def _course_page(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        top = QHBoxLayout()
        self.name_lbl = _bold("", 1.3)
        self.switch = QComboBox()
        self.more = QToolButton()
        self.more.setText("More")
        self.more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        m = QMenu(self.more)
        for text, fn in (("All the details…", lambda: self.details(None)),
                         ("Add more of the calendar…", lambda: self.start(adding=True)),
                         ("Copy as plan text", self.plan_text),
                         (None, None),
                         ("New course…", lambda: self.start()),
                         ("Rename this course…", self.rename),
                         ("Delete this course…", self.delete),
                         (None, None),
                         ("Settings…", self.settings),
                         ("Show the log", self.show_log)):
            if text is None:
                m.addSeparator()
            else:
                m.addAction(text).triggered.connect(fn)
        self.more.setMenu(m)
        top.addWidget(self.name_lbl)
        top.addWidget(self.switch)
        top.addStretch(1)
        top.addWidget(self.more)
        lay.addLayout(top)
        self.sub = _note()
        lay.addWidget(self.sub)

        self.next_row = QWidget()
        nr = QHBoxLayout(self.next_row)
        nr.setContentsMargins(0, 6, 0, 6)
        self.next_lbl = _note()
        self.next_btn = QPushButton("Open them now")
        nr.addWidget(self.next_lbl, 1)
        nr.addWidget(self.next_btn)
        lay.addWidget(self.next_row)

        self.list = QTreeWidget()
        self.list.setHeaderLabels(["Date", "Lecture", "Cards", ""])
        self.list.setRootIsDecorated(False)
        self.list.setUniformRowHeights(False)
        h = self.list.header()
        h.setStretchLastSection(False)
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        lay.addWidget(self.list, 1)
        lay.addWidget(_note("Double-click a lecture to see what's in it."))

        bottom = QHBoxLayout()
        self.auto = QCheckBox("Open each lecture's cards on its day")
        self.state = _note()
        self.stop_btn = QPushButton("Stop")
        bottom.addWidget(self.auto)
        bottom.addWidget(self.state, 1)
        bottom.addWidget(self.stop_btn)
        lay.addLayout(bottom)

        self.switch.currentIndexChanged.connect(self.switched)
        self.next_btn.clicked.connect(lambda: self.open_lecture(self.next_lec))
        self.list.itemDoubleClicked.connect(lambda it, _c: self.details(it.data(0, Qt.ItemDataRole.UserRole)))
        self.auto.toggled.connect(self.auto_toggled)
        self.stop_btn.clicked.connect(self.stop)
        self.next_lec = None
        return w

    def show_page(self):
        if not self.app.data["courses"]:
            self.start()
            return
        self.pages.setCurrentIndex(1)
        self.fill()

    def idx(self):
        c = self.app.course()
        if not c or not mw.col:
            return None
        if self.app.idx is None or self.app.idx_did != c["did"]:
            self.state.setText("Reading your deck…")
            QApplication.processEvents()
        i = self.app.index()
        if not self.app.busy:
            self.state.setText("")
        return i

    def fill(self):
        c = self.app.course()
        if not c:
            return
        self.loading = True
        self.name_lbl.setText(c["name"])
        self.switch.clear()
        for x in self.app.data["courses"]:
            self.switch.addItem(x["name"])
        self.switch.setCurrentIndex(self.app.data["courses"].index(c))
        self.switch.setVisible(len(self.app.data["courses"]) > 1)
        self.name_lbl.setVisible(len(self.app.data["courses"]) <= 1)
        self.auto.setChecked(bool(c.get("auto_open")))
        self.stop_btn.setVisible(self.app.busy)
        self.loading = False
        self.fill_sub()
        self.fill_list()

    def fill_sub(self):
        c = self.app.course()
        how = C.read_by(c)
        words = {"model": "read by your Mac's model", "rules": "read by plain matching"}.get(how, "")
        if self.checked and not self.checked[1] and self.checked[2]:
            words = f"read by plain matching: {self.checked[2]}"
        elif how == "rules" and self.checked and self.checked[0] != "none":
            words = "read by plain matching: your Mac's model didn't answer (More › Show the log)"
        self.sub.setText(" · ".join(x for x in (c.get("deck") or "", words) if x))

    def fill_list(self):
        c, idx = self.app.course(), self.idx()
        self.list.clear()
        today = _today().isoformat()
        for lec in C.lectures(c):
            words, can = C.lecture_status(c, lec, idx)
            it = QTreeWidgetItem([C.day_label(lec["date"]), lec["title"], words, ""])
            it.setData(0, Qt.ItemDataRole.UserRole, lec["id"])
            if lec["date"] < today:
                for col in range(3):
                    it.setForeground(col, self.palette().placeholderText())
            self.list.addTopLevelItem(it)
            if can:
                b = QPushButton("Open")
                b.clicked.connect(lambda _=False, l=lec: self.open_lecture(l))
                self.list.setItemWidget(it, 3, b)
        nxt = C.next_up(c, idx, today)
        self.next_lec = nxt
        if nxt is None:
            self.next_row.setVisible(False)
            return
        self.next_row.setVisible(True)
        words, can = C.lecture_status(c, nxt, idx)
        when = "today" if nxt["date"] == today else C.day_label(nxt["date"])
        line = f"Next: {nxt['title']}, {when}. {words[:1].upper() + words[1:]}."
        if can and c.get("auto_open") and nxt["date"] > today:
            line += " They open on the day, or now if you like."
        self.next_lbl.setText(line)
        self.next_btn.setVisible(can)

    def switched(self, i):
        if self.loading or i < 0:
            return
        self.app.data["current"] = i
        self.app.save()
        self.fill()

    def auto_toggled(self, on):
        c = self.app.course()
        if c and not self.loading:
            c["auto_open"] = bool(on)
            self.app.save()
            self.fill_list()

    # ---- reading ----

    def ready_runner(self):
        """The model to read with: Auto's pick if it says it's ready, else
        plain matching, so nothing waits on a model that won't answer. Off
        the main thread (asking can take a moment)."""
        r = self.app.model()
        if r.name == "none":
            if not self.checked:  # a model found not ready a moment ago keeps its reason
                self.checked = ("none", True, "")
            return r
        try:
            ok, why = r.available()
        except Exception as e:  # noqa: BLE001
            ok, why = False, str(e)
        self.checked = (r.name, ok, M.plain_why(why) if not ok else "")
        if not ok:
            self.app.log(f"model not ready ({r.name}): {str(why)[:200]}")
            self.app.runner = M.NoModel()
            return self.app.runner
        return r

    def read_unread(self):
        c = self.app.course()
        if not c or self.app.busy:
            return
        todo = C.reading_order(c, _today().isoformat())
        if not todo or self.idx() is None:
            self.fill()
            return
        for l in todo:
            l["state"] = "queued"
        self.app.busy = True  # held while the model's readiness is asked
        self.stop_btn.setVisible(True)
        self.state.setText("Getting ready…")
        self.fill_list()
        self._bg(self.ready_runner, lambda _r: self.read_now(todo), lambda _e: self.read_now(todo))

    def read_now(self, todo):
        self.app.busy = False
        self.fill_sub()
        t0, left = time.time(), [len(todo)]

        def each(lec):
            left[0] -= 1
            self.state.setText(f"Reading the lectures… {left[0]} to go" if left[0] else "")
            self.fill_list()

        def end():
            for l in todo:
                if l.get("state") == "queued":
                    l["state"] = "new"
            self.app.save()
            self.stop_btn.setVisible(False)
            self.state.setText(f"Read in {time.time() - t0:.0f} s." if not self.app.cancel_flag else "Stopped.")
            self.fill_sub()
            self.fill_list()
        self.state.setText(f"Reading the lectures… {len(todo)} to go. You can close this window.")
        self.app.run_lectures(todo, each, end)

    def stop(self):
        self.app.cancel_flag = True
        self.state.setText("Stopping after this lecture…")

    # ---- opening ----

    def open_lecture(self, lec):
        if not lec:
            return
        idx = self.idx()
        if idx is None:
            return
        n = self.app.open_cids(C.lecture_cids(lec, idx), f"Course: {lec['title']}")
        if n:
            lec.setdefault("opened", []).append(_today().isoformat())
            self.app.save()
        tooltip(f"Opened {n:,} card{'s' if n != 1 else ''} for {lec['title']}. Edit › Undo puts them back."
                if n else "Nothing to open: they're open already.")
        self.fill_list()

    # ---- More ----

    def details(self, lec_id):
        from . import ui
        if self.app.window is None:
            self.app.window = ui.CourseWindow(self.app)
        w = self.app.window
        if lec_id:
            w.cur = lec_id
        w.fill()
        w.show()
        w.raise_()
        w.activateWindow()

    def plan_text(self):
        c, idx = self.app.course(), self.idx()
        if not c or idx is None:
            return
        QApplication.clipboard().setText(C.plan_text(c, idx))
        tooltip("Copied. In the builder on duecrew.com: Text › Add dates, paste, Read it.")

    def rename(self):
        c = self.app.course()
        name, ok = QInputDialog.getText(self, "Rename", "The course's name:", text=c["name"])
        if ok and name.strip():
            c["name"] = name.strip()[:60]
            self.app.save()
            self.fill()

    def delete(self):
        c = self.app.course()
        if QMessageBox.question(self, "Delete", f"Delete {c['name']}? Its cards stay as they are.") \
                != QMessageBox.StandardButton.Yes:
            return
        self.app.data["courses"].remove(c)
        self.app.data["current"] = 0
        self.app.idx = None
        self.app.save()
        self.show_page()

    def settings(self):
        from . import ui
        ui.SettingsDialog(self.app, self).exec()
        self.checked = None
        self.fill_sub()

    def show_log(self):
        from . import ui
        ui.TextDialog(self, "The log", "\n".join(self.app.lines[-300:]) or "Nothing yet.").exec()
