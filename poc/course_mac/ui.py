"""The PoC's windows: the course (lectures, a lecture's rows to tick, what
opening would do), the calendar, settings (build and check the model),
measuring against an answer key's tags, and a tag's cards by lecture
(Browse). Plain Qt in Anki's own style. Names from a deck or a calendar
go into item texts (plain) or are escaped before a rich-text label."""

import datetime as dt
import html
import os
import shutil
import subprocess
import time

from aqt import mw
from aqt.qt import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit,
    QPushButton, QSpinBox, QSplitter, Qt, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)
from aqt.utils import tooltip

from . import cal
from . import course as C
from . import engine as E
from . import find as F
from . import jobs as J
from . import model as M
from .glue import FOLDER, run_steps

ROLE = Qt.ItemDataRole.UserRole
esc = html.escape


def _today():
    return dt.date.today()


def bg(fn, done, fail):
    """fn off the main thread; done(result) or fail(error) back on it."""
    def finished(fut):
        try:
            r = fut.result()
        except Exception as e:  # noqa: BLE001
            fail(e)
            return
        done(r)
    mw.taskman.run_in_background(fn, finished)


def deck_choices():
    out = []
    for r in mw.col.decks.all_names_and_ids():
        d = mw.col.decks.get(int(r.id), default=False)
        if d and not d.get("dyn"):
            out.append((int(r.id), str(r.name)))
    return sorted(out, key=lambda x: x[1].lower())


def browse(cids):
    if not cids:
        tooltip("No cards there.")
        return
    from aqt import dialogs
    b = dialogs.open("Browser", mw)
    q = "cid:" + ",".join(str(c) for c in list(cids)[:3000])
    if hasattr(b, "search_for"):
        b.search_for(q)
    else:
        b.form.searchEdit.lineEdit().setText(q)
        b.onSearchActivated()


def plain_label(text=""):
    """A label that shows its text as written (Qt would guess rich text)."""
    lab = QLabel(text)
    lab.setTextFormat(Qt.TextFormat.PlainText)
    return lab


def parse_objectives(text):
    """Lines as objectives: "SLG 5 | what it says", "SLG 5 What it says", or just the words."""
    out = []
    for line in str(text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if "|" in line:
            lab, _, words = line.partition("|")
            out.append({"label": lab.strip()[:20], "text": words.strip()[:300]})
            continue
        lab, words = cal.split_objective(line)
        out.append({"label": lab[:20], "text": (words or line)[:300]})
    return [o for o in out if o["text"]]


class TextDialog(QDialog):
    def __init__(self, parent, title, text, note=""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(820, 520)
        lay = QVBoxLayout(self)
        if note:
            n = QLabel(note)
            n.setWordWrap(True)
            lay.addWidget(n)
        box = QPlainTextEdit()
        box.setPlainText(text)
        box.setReadOnly(True)
        lay.addWidget(box, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


# ---- the course ----

class CourseWindow(QDialog):
    def __init__(self, app):
        super().__init__(mw)
        self.app = app
        self.cur = None
        self.loading = False
        self.setWindowTitle("Course on a Mac (PoC)")
        self.resize(1180, 780)
        root = QVBoxLayout(self)

        top = QHBoxLayout()
        self.courses = QComboBox()
        self.courses.setMinimumWidth(170)
        self.new_btn = QPushButton("New course…")
        self.rename_btn = QPushButton("Rename…")
        self.deck = QComboBox()
        self.deck.setMinimumWidth(220)
        self.model_lbl = plain_label()
        self.settings_btn = QPushButton("Settings…")
        for w in (QLabel("Course"), self.courses, self.new_btn, self.rename_btn):
            top.addWidget(w)
        top.addSpacing(12)
        top.addWidget(QLabel("Deck"))
        top.addWidget(self.deck, 1)
        top.addWidget(self.model_lbl)
        top.addWidget(self.settings_btn)
        root.addLayout(top)

        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        ll.addWidget(self.list, 1)
        r1 = QHBoxLayout()
        self.cal_btn = QPushButton("Calendar…")
        self.add_btn = QPushButton("Add")
        self.del_btn = QPushButton("Remove")
        for b in (self.cal_btn, self.add_btn, self.del_btn):
            r1.addWidget(b)
        ll.addLayout(r1)
        r2 = QHBoxLayout()
        self.all_btn = QPushButton("Read the unread lectures")
        self.stop_btn = QPushButton("Stop")
        r2.addWidget(self.all_btn, 1)
        r2.addWidget(self.stop_btn)
        ll.addLayout(r2)
        split.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(6, 0, 0, 0)
        head = QHBoxLayout()
        self.date = QLineEdit()
        self.date.setPlaceholderText("YYYY-MM-DD")
        self.date.setMaximumWidth(110)
        self.kind = QComboBox()
        self.kind.addItems(list(cal.KINDS))
        self.title = QLineEdit()
        self.title.setPlaceholderText("Title")
        head.addWidget(self.date)
        head.addWidget(self.kind)
        head.addWidget(self.title, 1)
        rl.addLayout(head)
        rl.addWidget(QLabel("Objectives, one a line (SLG 5 | what it says)"))
        self.objs = QPlainTextEdit()
        self.objs.setMaximumHeight(112)
        rl.addWidget(self.objs)
        wr = QHBoxLayout()
        wr.addWidget(QLabel("Search words"))
        self.terms = QLineEdit()
        self.terms.setPlaceholderText("The model's, or yours (commas between). Empty: the model picks them.")
        wr.addWidget(self.terms, 1)
        self.read_btn = QPushButton("Read this lecture")
        wr.addWidget(self.read_btn)
        rl.addLayout(wr)
        self.rows = QTreeWidget()
        self.rows.setHeaderLabels(["Source", "Use", "Cards", "To open", "Objectives", "Note"])
        self.rows.setRootIsDecorated(False)
        self.rows.setAlternatingRowColors(True)
        self.rows.setColumnWidth(0, 360)
        self.rows.setColumnWidth(1, 60)
        self.rows.setColumnWidth(2, 80)
        self.rows.setColumnWidth(3, 70)
        self.rows.setColumnWidth(4, 110)
        rl.addWidget(self.rows, 1)
        self.checks = QLabel("")
        self.checks.setWordWrap(True)
        self.checks.setTextFormat(Qt.TextFormat.RichText)
        rl.addWidget(self.checks)
        ar = QHBoxLayout()
        self.open_btn = QPushButton("Open ticked")
        self.open_row_btn = QPushButton("Open this row")
        self.tag_btn = QPushButton("Tag the cards…")
        self.browse_btn = QPushButton("Show in Browse")
        for b in (self.open_btn, self.open_row_btn, self.tag_btn, self.browse_btn):
            ar.addWidget(b)
        ar.addStretch(1)
        rl.addLayout(ar)
        split.addWidget(right)
        split.setSizes([320, 860])
        root.addWidget(split, 1)

        bottom = QHBoxLayout()
        self.plan_btn = QPushButton("Copy as plan text")
        self.auto = QCheckBox("Open each lecture's ticked cards on its day")
        self.status = plain_label()
        bottom.addWidget(self.plan_btn)
        bottom.addWidget(self.auto)
        bottom.addStretch(1)
        bottom.addWidget(self.status)
        root.addLayout(bottom)
        self.logbox = QPlainTextEdit()
        self.logbox.setReadOnly(True)
        self.logbox.setMaximumHeight(110)
        root.addWidget(self.logbox)

        self.courses.currentIndexChanged.connect(self.course_picked)
        self.new_btn.clicked.connect(self.new_course)
        self.rename_btn.clicked.connect(self.rename_course)
        self.deck.currentIndexChanged.connect(self.deck_picked)
        self.settings_btn.clicked.connect(self.settings)
        self.list.currentItemChanged.connect(lambda *_: self.lecture_picked())
        self.cal_btn.clicked.connect(self.calendar)
        self.add_btn.clicked.connect(self.add_lecture)
        self.del_btn.clicked.connect(self.remove_lecture)
        self.all_btn.clicked.connect(self.read_all)
        self.stop_btn.clicked.connect(self.stop)
        self.read_btn.clicked.connect(self.read_one)
        self.rows.itemChanged.connect(self.row_ticked)
        self.rows.itemDoubleClicked.connect(lambda it, _c: browse(self.row_cids(it)))
        self.open_btn.clicked.connect(self.open_ticked)
        self.open_row_btn.clicked.connect(self.open_row)
        self.tag_btn.clicked.connect(self.tag_cards)
        self.browse_btn.clicked.connect(lambda: browse(self.lec_cids()))
        self.plan_btn.clicked.connect(self.plan_text)
        self.auto.toggled.connect(self.auto_toggled)
        self.fill()
        self.show_log()
        self.model_status()

    # ---- state ----

    def course(self):
        return self.app.course()

    def lec(self):
        c = self.course()
        if not c or not self.cur:
            return None
        return next((l for l in c["lectures"] if l["id"] == self.cur), None)

    def idx(self):
        if not self.course():
            return None
        if self.app.idx is None or self.app.idx_did != self.course()["did"]:
            self.status.setText("Reading the deck…")
            QApplication.processEvents()
        i = self.app.index()
        self.status.setText("")
        return i

    def busy(self, on, text=""):
        for b in (self.read_btn, self.all_btn, self.cal_btn, self.add_btn, self.del_btn, self.new_btn,
                  self.courses, self.deck):
            b.setEnabled(not on)
        self.stop_btn.setEnabled(on)
        self.status.setText(text)

    def show_log(self):
        self.logbox.setPlainText("\n".join(self.app.lines[-200:]))
        sb = self.logbox.verticalScrollBar()
        sb.setValue(sb.maximum())

    def model_status(self):
        r = self.app.model()
        if r.name == "none":
            self.model_lbl.setText("No model: plain rules")
            return
        self.model_lbl.setText(f"{r.label}: checking…")
        bg(r.available, lambda got: self.model_lbl.setText(f"{r.label}: {'ready' if got[0] else 'not ready'}")
           or self.model_lbl.setToolTip(got[1]), lambda e: self.model_lbl.setText(f"{r.label}: {e}"))

    # ---- filling ----

    def fill(self):
        self.loading = True
        c = self.course()
        self.courses.clear()
        for x in self.app.data["courses"]:
            self.courses.addItem(x["name"])
        if c:
            self.courses.setCurrentIndex(self.app.data["courses"].index(c))
        self.deck.clear()
        if mw.col:
            for did, name in deck_choices():
                self.deck.addItem(name, did)
            if c and c.get("did"):
                i = self.deck.findData(c["did"])
                if i >= 0:
                    self.deck.setCurrentIndex(i)
        self.auto.setChecked(bool(c and c.get("auto_open")))
        for w in (self.rename_btn, self.cal_btn, self.add_btn, self.all_btn, self.plan_btn, self.auto):
            w.setEnabled(bool(c))
        self.loading = False
        self.fill_list()

    def item_text(self, lec, idx):
        t = f"{lec['date'][5:]}  {lec['title']}"
        if lec["kind"] in C.EVENT_KINDS or lec["kind"] == "lab":
            return f"{t}  · {lec['kind']}"
        st = lec.get("state")
        if st == "running":
            return f"{t}  · reading…"
        if st == "error":
            return f"{t}  · stopped"
        if st == "done" and idx is not None:
            s = C.summary(self.course(), lec, idx)
            extra = f"  · {len(s['missing'])} missing" if s["missing"] else ""
            return f"{t}  · {s['new']} to open{extra}"
        return f"{t}  · not read"

    def fill_list(self):
        self.loading = True
        keep = self.cur
        self.list.clear()
        c = self.course()
        idx = self.app.idx if c and self.app.idx_did == c.get("did") else None
        for lec in C.lectures(c) if c else []:
            it = QListWidgetItem(self.item_text(lec, idx))
            it.setData(ROLE, lec["id"])
            if lec["kind"] in C.EVENT_KINDS or lec["kind"] == "lab":
                f = it.font()
                f.setItalic(True)
                it.setFont(f)
            self.list.addItem(it)
            if lec["id"] == keep:
                self.list.setCurrentItem(it)
        self.loading = False
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self.lecture_picked(force=True)

    def lecture_picked(self, force=False):
        if self.loading and not force:
            return
        self.pull()
        it = self.list.currentItem()
        self.cur = it.data(ROLE) if it else None
        self.show_lecture()

    def show_lecture(self):
        self.loading = True
        lec = self.lec()
        on = lec is not None
        for w in (self.date, self.kind, self.title, self.objs, self.terms, self.read_btn, self.rows,
                  self.open_btn, self.open_row_btn, self.tag_btn, self.browse_btn, self.del_btn):
            w.setEnabled(on)
        self.date.setText(lec["date"] if on else "")
        self.kind.setCurrentText(lec["kind"] if on else "lecture")
        self.title.setText(lec["title"] if on else "")
        self.objs.setPlainText("\n".join(f"{o['label']} | {o['text']}" if o.get("label") else o["text"]
                                         for o in (lec.get("objectives") or [])) if on else "")
        self.terms.setText(", ".join(lec.get("terms") or []) if on else "")
        self.terms.setModified(False)
        self.objs.document().setModified(False)
        self.rows.clear()
        self.checks.setText("")
        if on and lec.get("rows"):
            idx = self.idx()
            objs = lec.get("objectives") or []
            for r in lec["rows"]:
                cids = C.row_cids(r, idx)
                to_open = len(E.openable(mw.col, cids)) if mw.col else 0
                if r["use"] == "whole":
                    cards = f"all {len(cids)}"
                elif r["kind"] == "found":
                    cards = f"{len(cids)} fit"
                elif r["use"] == "part":
                    cards = f"{len(cids)} of {len(idx.cids_of(idx.under(r['tag'])))}"
                else:
                    cards = str(len(idx.cids_of(idx.under(r["tag"])))) if r.get("tag") else ""
                os_ = sorted(set(r.get("objs") or []) | {v[1] for v in (r.get("fit") or {}).values() if v[0] and v[1]})
                labels = ", ".join(C.key_of(objs[o - 1], o) for o in os_ if 1 <= o <= len(objs))
                note = (f"{r['later']}" if r["use"] == "later" else
                        f"{len(r['unread'])} unread" if r.get("unread") else "")
                src = f"{r['res']} › {r['name']}" if r.get("res") else r["name"]
                it = QTreeWidgetItem([src, r["use"] if r["kind"] != "found" else "found", cards,
                                      str(to_open) if r.get("on") or r["use"] != "no" else "", labels, note])
                it.setToolTip(0, r.get("tag") or "Cards outside these tags whose text holds the search words")
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(0, Qt.CheckState.Checked if r.get("on") else Qt.CheckState.Unchecked)
                it.setData(0, ROLE, lec["rows"].index(r))
                self.rows.addTopLevelItem(it)
            self.show_checks()
        elif on and lec.get("state") == "running":
            self.checks.setText("Reading…")
        elif on and lec["kind"] not in C.EVENT_KINDS:
            self.checks.setText("Not read yet: Read this lecture.")
        self.loading = False

    def show_checks(self):
        lec, idx = self.lec(), self.app.idx
        if not lec or idx is None:
            return
        s = C.summary(self.course(), lec, idx)
        how = lec.get("how") or {}
        bits = [f"<b>{s['new']:,} to open</b>"]
        if s["open_already"]:
            bits.append(f"{s['open_already']:,} open already")
        if s["repeat"]:
            bits.append(f"{s['repeat']:,} on an earlier lecture")
        if s["leeches"]:
            bits.append(f"{s['leeches']:,} leech{'es' if s['leeches'] != 1 else ''} stay shut")
        line2 = []
        if s["covered"]:
            line2.append("Objectives with cards: " + ", ".join(esc(k) for k, _h in s["covered"]))
        if s["missing"]:
            line2.append("<b>Nothing fits:</b> " + ", ".join(esc(k) for k in s["missing"]))
        line3 = []
        if s["event"]:
            line3.append(f"For {esc(s['event'][0])}, {s['event'][1]} day{'s' if s['event'][1] != 1 else ''} ahead")
        line3.append(f"words: {esc(how.get('terms', ''))} · pick: {esc(how.get('pick', ''))} · "
                     f"read: {esc(how.get('read', ''))} · {lec.get('secs', 0)} s")
        if lec.get("opened"):
            line3.append(f"opened {esc(', '.join(lec['opened'][-3:]))}")
        self.checks.setText(" · ".join(bits) + "<br>" + " · ".join(line2) + "<br>"
                            + "<span style='color:gray'>" + " · ".join(line3) + "</span>")

    def pull(self):
        """The editor's fields into the lecture."""
        lec = self.lec()
        if not lec or self.loading:
            return
        try:
            lec["date"] = dt.date.fromisoformat(self.date.text().strip()).isoformat()
        except ValueError:
            pass
        lec["kind"] = self.kind.currentText()
        lec["title"] = self.title.text().strip()[:120] or lec["title"]
        if self.objs.document().isModified():
            lec["objectives"] = parse_objectives(self.objs.toPlainText())
            self.objs.document().setModified(False)
        if self.terms.isModified():  # only words you typed: a read fills the box itself
            typed = [t.strip() for t in self.terms.text().split(",") if t.strip()]
            lec["terms"], lec["terms_set"] = typed, bool(typed)
            self.terms.setModified(False)
        self.app.save()

    # ---- courses and decks ----

    def course_picked(self, i):
        if self.loading or i < 0:
            return
        self.pull()
        self.app.data["current"] = i
        self.cur = None
        self.app.save()
        self.fill()

    def new_course(self):
        name, ok = QInputDialog.getText(self, "New course", "Its name (MS2 Block 2):")
        if not ok or not name.strip():
            return
        self.pull()
        did = self.deck.currentData() or 0
        self.app.data["courses"].append(C.new_course(name.strip()[:60], did, self.deck.currentText()))
        self.app.data["current"] = len(self.app.data["courses"]) - 1
        self.cur = None
        self.app.save()
        self.fill()

    def rename_course(self):
        c = self.course()
        if not c:
            return
        name, ok = QInputDialog.getText(self, "Rename", "Its name:", text=c["name"])
        if ok and name.strip():
            c["name"] = name.strip()[:60]
            self.app.save()
            self.fill()

    def deck_picked(self, _i):
        c = self.course()
        if self.loading or not c:
            return
        c["did"], c["deck"] = int(self.deck.currentData() or 0), self.deck.currentText()
        self.app.idx = None
        self.app.save()
        self.fill_list()

    def settings(self):
        SettingsDialog(self.app, self).exec()
        self.model_status()

    def auto_toggled(self, on):
        c = self.course()
        if c and not self.loading:
            c["auto_open"] = bool(on)
            self.app.save()

    # ---- lectures ----

    def calendar(self):
        d = CalendarDialog(self.app, self)
        if d.exec() and d.picked:
            c = self.course()
            have = {(l["date"], l["title"].lower()) for l in c["lectures"]}
            added = 0
            for s in d.picked:
                if (s["date"], s["title"].lower()) in have:
                    continue
                c["lectures"].append(C.new_lecture(s["date"], s["title"], s["kind"], s.get("objectives") or []))
                added += 1
            self.app.save()
            self.fill_list()
            tooltip(f"Added {added} session{'s' if added != 1 else ''}.")

    def add_lecture(self):
        c = self.course()
        if not c:
            return
        self.pull()
        lec = C.new_lecture(_today().isoformat(), "New lecture")
        c["lectures"].append(lec)
        self.cur = lec["id"]
        self.app.save()
        self.fill_list()
        self.title.setFocus()
        self.title.selectAll()

    def remove_lecture(self):
        c, lec = self.course(), self.lec()
        if not lec:
            return
        if QMessageBox.question(self, "Remove", f"Remove {lec['title']} from the course? Its cards stay as they are.") \
                != QMessageBox.StandardButton.Yes:
            return
        c["lectures"] = [l for l in c["lectures"] if l["id"] != lec["id"]]
        self.cur = None
        self.app.save()
        self.fill_list()

    def read_one(self):
        self.pull()
        lec = self.lec()
        if not lec or not lec["title"].strip():
            return
        self.run([lec])

    def read_all(self):
        self.pull()
        c = self.course()
        todo = [l for l in C.lectures(c) if C.studied(l) and l.get("state") != "done"]
        if not todo:
            tooltip("Every lecture's read. Read one again with its own button.")
            return
        self.run(todo)

    def run(self, lecs):
        if self.idx() is None:
            return
        for l in lecs:
            l["state"] = "queued"
        self.busy(True, f"Reading {len(lecs)} lecture{'s' if len(lecs) != 1 else ''}…")
        t0 = time.time()
        left = [len(lecs)]

        def each(lec):
            left[0] -= 1
            self.status.setText(f"{left[0]} to go…" if left[0] else "")
            self.fill_list()

        def end():
            self.busy(False, f"Done in {time.time() - t0:.0f} s.")
            for l in lecs:
                if l.get("state") == "queued":
                    l["state"] = "new"
            self.app.save()
            self.fill_list()
        self.app.run_lectures(lecs, each, end)
        self.fill_list()

    def stop(self):
        self.app.cancel_flag = True
        self.status.setText("Stopping after this call…")

    # ---- rows ----

    def row_of(self, it):
        lec = self.lec()
        if not lec or it is None:
            return None
        i = it.data(0, ROLE)
        return lec["rows"][i] if i is not None and 0 <= i < len(lec["rows"]) else None

    def row_cids(self, it):
        r = self.row_of(it)
        return C.row_cids(r, self.idx()) if r else []

    def row_ticked(self, it, col):
        if self.loading or col != 0:
            return
        r = self.row_of(it)
        if r is None:
            return
        r["on"] = it.checkState(0) == Qt.CheckState.Checked
        self.app.save()
        self.show_checks()
        cur = self.list.currentItem()
        if cur:
            cur.setText(self.item_text(self.lec(), self.app.idx))

    def lec_cids(self):
        lec = self.lec()
        return C.lecture_cids(lec, self.idx()) if lec else []

    def opened(self, n, what):
        lec = self.lec()
        if n:
            lec.setdefault("opened", []).append(_today().isoformat())
            self.app.save()
        tooltip(f"Opened {n:,} card{'s' if n != 1 else ''} ({esc(what)}). Edit › Undo puts them back."
                if n else "Nothing to open: they're open already, or leeches.")
        self.show_lecture()

    def open_ticked(self):
        lec = self.lec()
        if lec:
            self.opened(self.app.open_cids(self.lec_cids(), f"Course: {lec['title']}"), lec["title"])

    def open_row(self):
        it = self.rows.currentItem()
        r = self.row_of(it)
        if r is None:
            tooltip("Click a row first.")
            return
        self.opened(self.app.open_cids(C.row_cids(r, self.idx()), f"Course: {r['name']}"), r["name"])

    def tag_cards(self):
        lec, idx = self.lec(), self.idx()
        if not lec or not mw.col:
            return
        tags = E.lecture_tags(self.course(), lec, idx)
        if not tags:
            tooltip("Nothing ticked to tag.")
            return
        lines = "\n".join(f"{t}  ({len(n):,} notes)" for t, n in tags.items())
        if QMessageBox.question(self, "Tag the cards", f"Add these tags? One undo step.\n\n{lines}") \
                != QMessageBox.StandardButton.Yes:
            return
        n = E.tag_notes(mw.col, tags, f"Course: tag {lec['title']}")
        self.app.after_change()
        tooltip(f"Tagged {n:,} notes.")

    def plan_text(self):
        self.pull()
        c, idx = self.course(), self.idx()
        if not c or idx is None:
            return
        text = C.plan_text(c, idx)
        QApplication.clipboard().setText(text)
        TextDialog(self, "Plan text", text,
                   "Copied. In the builder on duecrew.com: Text › Add dates, paste, Read it. It carries tag names, "
                   "note ids and searches, never a card's text.").exec()

    def closeEvent(self, ev):
        self.pull()
        self.app.cancel_flag = True
        self.app.window = None
        super().closeEvent(ev)


# ---- the calendar ----

class CalendarDialog(QDialog):
    def __init__(self, app, parent):
        super().__init__(parent)
        self.app = app
        self.picked = []
        self.found = []
        self.setWindowTitle("The block's calendar")
        self.resize(900, 680)
        lay = QVBoxLayout(self)
        n = QLabel("Paste the calendar (or Load a file: text, or a PDF on a Mac with the helper built). Each session "
                   "with a date, its title, and its objectives under it if you have them.")
        n.setWordWrap(True)
        lay.addWidget(n)
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("Mon 10/26  8:00  LEC  Heart failure\n    SLG 1  Define systolic and diastolic heart failure\n"
                                     "Fri 10/30  9:00  QUIZ  Cardio quiz 1")
        lay.addWidget(self.text, 2)
        r = QHBoxLayout()
        self.load_btn = QPushButton("Load a file…")
        self.model_btn = QPushButton("Read with the Mac model")
        self.lines_btn = QPushButton("Read as lines")
        self.state = plain_label()
        for w in (self.load_btn, self.model_btn, self.lines_btn):
            r.addWidget(w)
        r.addStretch(1)
        r.addWidget(self.state)
        lay.addLayout(r)
        self.table = QTreeWidget()
        self.table.setHeaderLabels(["Date", "Kind", "Title", "Objectives"])
        self.table.setRootIsDecorated(False)
        self.table.setColumnWidth(0, 120)
        self.table.setColumnWidth(1, 70)
        self.table.setColumnWidth(2, 420)
        lay.addWidget(self.table, 3)
        bb = QDialogButtonBox()
        self.add_btn = bb.addButton("Add the ticked ones", QDialogButtonBox.ButtonRole.AcceptRole)
        bb.addButton(QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.take)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.load_btn.clicked.connect(self.load)
        self.model_btn.clicked.connect(lambda: self.read(True))
        self.lines_btn.clicked.connect(lambda: self.read(False))
        self.model_btn.setEnabled(self.app.model().name != "none")

    def load(self):
        path, _ = QFileDialog.getOpenFileName(self, "A calendar", os.path.expanduser("~"),
                                              "Calendars (*.txt *.md *.csv *.tsv *.pdf);;All files (*)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    self.text.setPlainText(f.read())
            except OSError as e:
                self.state.setText(str(e))
            return
        self.state.setText("Reading the PDF…")
        runner = self.app.model()

        def work():
            helper = runner if isinstance(runner, M.HelperRunner) else M.HelperRunner(FOLDER)
            if helper.built():
                try:
                    return helper.pdf_text(path)
                finally:
                    if helper is not runner:
                        helper.close()
            exe = shutil.which("pdftotext")
            if exe:
                return subprocess.run([exe, "-layout", path, "-"], capture_output=True, text=True, timeout=60).stdout
            raise M.ModelError("Build the helper (Settings) to read PDFs, or copy the PDF's text and paste it here.")
        bg(work, lambda t: (self.text.setPlainText(t), self.state.setText("")), lambda e: self.state.setText(str(e)))

    def read(self, with_model):
        text = self.text.toPlainText()
        if not text.strip():
            return
        cfg = self.app.cfg()
        today, df = _today(), bool(cfg.get("day_first"))
        if not with_model:
            self.list_sessions(cal.read_lines(text, today, df), "as lines")
            return
        self.state.setText("The model's reading it…")
        self.model_btn.setEnabled(False)
        runner = self.app.model()
        t0 = time.time()
        bg(lambda: J.read_calendar(runner, text, today, self.app.log, int(cfg.get("calendar_chars") or 1800), df),
           lambda got: (self.model_btn.setEnabled(True), self.list_sessions(got[0], f"{got[1]}, {time.time() - t0:.0f} s")),
           lambda e: (self.model_btn.setEnabled(True), self.state.setText(f"Stopped: {e}")))

    def list_sessions(self, sessions, how=""):
        self.found = sessions
        self.table.clear()
        for i, s in enumerate(sessions):
            it = QTreeWidgetItem([s["date"], s["kind"], s["title"], str(len(s.get("objectives") or []))])
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(0, Qt.CheckState.Checked)
            it.setData(0, ROLE, i)
            it.setToolTip(2, "\n".join(f"{o['label']} {o['text']}".strip() for o in s.get("objectives") or []))
            self.table.addTopLevelItem(it)
        self.state.setText(f"{len(sessions)} session{'s' if len(sessions) != 1 else ''} ({how})")

    def take(self):
        self.picked = [self.found[self.table.topLevelItem(i).data(0, ROLE)] for i in range(self.table.topLevelItemCount())
                       if self.table.topLevelItem(i).checkState(0) == Qt.CheckState.Checked]
        self.accept()


# ---- settings ----

RUNNERS = [("auto", "Auto: the helper if built, else fm, else none"), ("helper", "The built helper (guided answers)"),
           ("fm", "The fm command (macOS 27)"), ("none", "No model: plain rules")]
NUMS = [("timeout", "Seconds a call may take", 10, 600), ("prompt_chars", "Characters a prompt may hold", 1500, 20000),
        ("read_batch", "Cards a reading call", 1, 30), ("groups_max", "Tag groups a lecture", 3, 30),
        ("tag_max_notes", "Notes a tag may hold to count", 20, 5000), ("part_max", "Cards read from a part", 5, 400),
        ("found_max", "Cards found by the words, at most", 0, 200), ("calendar_chars", "Calendar characters a call", 600, 8000)]
TICKS = [("first_in_line", "Opened cards go first in Anki's line of new cards"),
         ("day_first", "Dates are day first (26/10)"), ("verbose_log", "Log the model's answers too (this computer only)")]


class SettingsDialog(QDialog):
    def __init__(self, app, parent):
        super().__init__(parent)
        self.app = app
        self.setWindowTitle("Course on a Mac: settings")
        self.resize(640, 640)
        c = app.cfg()
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.runner = QComboBox()
        for k, t in RUNNERS:
            self.runner.addItem(t, k)
        self.runner.setCurrentIndex(max(0, self.runner.findData(c.get("runner", "auto"))))
        form.addRow("Model", self.runner)
        self.nums = {}
        for k, label, lo, hi in NUMS:
            s = QSpinBox()
            s.setRange(lo, hi)
            s.setValue(int(c.get(k) or E.DEFAULTS.get(k) or lo))
            self.nums[k] = s
            form.addRow(label, s)
        lay.addLayout(form)
        self.ticks = {}
        for k, label in TICKS:
            b = QCheckBox(label)
            b.setChecked(bool(c.get(k)))
            self.ticks[k] = b
            lay.addWidget(b)
        r = QHBoxLayout()
        self.build_btn = QPushButton("Build the helper")
        self.check_btn = QPushButton("Check the model")
        self.fm_btn = QPushButton("fm's help")
        self.log_btn = QPushButton("Open the log")
        for b in (self.build_btn, self.check_btn, self.fm_btn, self.log_btn):
            r.addWidget(b)
        lay.addLayout(r)
        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        helper = M.HelperRunner(FOLDER)
        self.out.setPlainText(
            f"Helper: {'built (' + (helper.guardrails() or '?') + ' guardrails)' if helper.built() else 'not built'}. "
            f"fm: {M.FmRunner().path or 'not found'}.\nOn-device only: nothing here uses Private Cloud Compute.")
        lay.addWidget(self.out, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.build_btn.clicked.connect(self.build)
        self.check_btn.clicked.connect(self.check)
        self.fm_btn.clicked.connect(lambda: self.out.setPlainText(M.FmRunner().help_text() if M.FmRunner().path
                                                                  else "No fm command on this Mac."))
        self.log_btn.clicked.connect(self.open_log)

    def collect(self):
        c = self.app.cfg()
        c["runner"] = self.runner.currentData()
        for k, s in self.nums.items():
            c[k] = s.value()
        for k, b in self.ticks.items():
            c[k] = b.isChecked()
        return c

    def save(self):
        self.app.save_cfg(self.collect())
        self.accept()

    def build(self):
        self.build_btn.setEnabled(False)
        self.out.setPlainText("Building the helper with swiftc (a minute or two)…")
        self.app.reset_runner()
        h = M.HelperRunner(FOLDER, self.app.log)
        bg(h.build, lambda got: (self.build_btn.setEnabled(True), self.out.setPlainText(got[1]), self.app.log(f"build: {got[1][:200]}")),
           lambda e: (self.build_btn.setEnabled(True), self.out.setPlainText(f"Didn't build: {e}")))

    def check(self):
        self.app.save_cfg(self.collect())
        r = self.app.model()
        self.check_btn.setEnabled(False)
        self.out.setPlainText(f"{r.label}: checking…")

        def work():
            ok, why = r.available()
            if not ok:
                return f"{r.label}: not ready. {why}"
            t0 = time.time()
            terms, how = J.terms_for(r, {"title": "Heart failure", "objectives": [
                {"label": "SLG 1", "text": "Name the drugs that lower mortality in heart failure"}]}, self.app.log)
            return (f"{r.label}: ready. {why}\nA test call ({how}) took {time.time() - t0:.1f} s and gave:\n"
                    + ", ".join(terms))
        bg(work, lambda t: (self.check_btn.setEnabled(True), self.out.setPlainText(t)),
           lambda e: (self.check_btn.setEnabled(True), self.out.setPlainText(f"Stopped: {e}")))

    def open_log(self):
        p = os.path.join(FOLDER, "log.txt")
        try:
            with open(p, encoding="utf-8") as f:
                text = f.read()[-60000:]
        except OSError:
            text = "No log yet."
        TextDialog(self, "Log", text, p).exec()


# ---- measuring against an answer key ----

class MeasureDialog(QDialog):
    def __init__(self, app, parent):
        super().__init__(parent)
        self.app = app
        self.results = []
        self.stop_flag = False
        self.setWindowTitle("Measure against my plan's tags")
        self.resize(980, 700)
        lay = QVBoxLayout(self)
        n = QLabel("A plan whose tags already pair your school's objectives with cards (Due Crew puts them on your notes "
                   "as DueCrew::<plan>::SLG_12) is an answer key. Paste some of its objectives; each runs as its own "
                   "lecture, and what it picks is scored against the key's cards. Nothing changes, nothing is sent.")
        n.setWordWrap(True)
        lay.addWidget(n)
        form = QFormLayout()
        self.key = QComboBox()
        self.key.setEditable(True)
        form.addRow("Answer key", self.key)
        self.howmany = QSpinBox()
        self.howmany.setRange(1, 40)
        self.howmany.setValue(5)
        form.addRow("How many objectives", self.howmany)
        lay.addLayout(form)
        lay.addWidget(QLabel("Objectives, one a line: SLG 12 | what it says (the label must match the key's tag)"))
        self.objs = QPlainTextEdit()
        self.objs.setMaximumHeight(140)
        lay.addWidget(self.objs)
        self.rules_too = QCheckBox("Also with no model (plain rules), to compare")
        self.rules_too.setChecked(True)
        lay.addWidget(self.rules_too)
        r = QHBoxLayout()
        self.run_btn = QPushButton("Run")
        self.stop_btn = QPushButton("Stop")
        self.copy_btn = QPushButton("Copy the results")
        self.state = plain_label()
        for w in (self.run_btn, self.stop_btn, self.copy_btn):
            r.addWidget(w)
        r.addStretch(1)
        r.addWidget(self.state)
        lay.addLayout(r)
        self.table = QTreeWidget()
        self.table.setHeaderLabels(["Objective", "Key's cards", "Model found", "Model right", "Seconds",
                                    "Rules found", "Rules right"])
        self.table.setRootIsDecorated(False)
        self.table.setColumnWidth(0, 300)
        lay.addWidget(self.table, 1)
        self.summary = plain_label()
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)
        self.run_btn.clicked.connect(self.run)
        self.stop_btn.clicked.connect(lambda: setattr(self, "stop_flag", True))
        self.copy_btn.clicked.connect(self.copy)
        idx = self.app.index()
        if idx is not None:
            roots = sorted({p for p in (v for k, v in idx.case.items() if k.startswith("duecrew::") and k.count("::") == 1)})
            self.key.addItems(roots)
        else:
            self.state.setText("Pick a course (with its deck) in the course window first.")
            self.run_btn.setEnabled(False)

    def run(self):
        idx = self.app.index()
        lines = parse_objectives(self.objs.toPlainText())
        root = self.key.currentText().strip()
        if idx is None or not root or not lines:
            return
        todo = []
        for o in lines:
            if not o["label"]:
                continue
            if idx.under(C.key_tag(root, o["label"])):
                todo.append(o)
            if len(todo) >= self.howmany.value():
                break
        if not todo:
            self.state.setText("None of those labels has a tag under that key in this deck.")
            return
        self.table.clear()
        self.results = []
        self.stop_flag = False
        self.run_btn.setEnabled(False)
        runner, cfg = self.app.model(), self.app.cfg()

        def one():
            if not todo or self.stop_flag:
                self.run_btn.setEnabled(True)
                self.done()
                return
            o = todo.pop(0)
            self.state.setText(f"{o['label']}… ({len(todo)} after it)")
            lec = C.new_lecture("2000-01-01", o["text"][:100], "lecture", [o])
            course = {**C.new_course("Measure"), "lectures": [lec]}
            run = E.LectureRun(course, lec, idx, runner, self.app.log, cfg, lambda: mw.col, lambda: self.stop_flag)
            t0 = time.time()

            def scored():
                secs = time.time() - t0
                pred = set().union(*[C.row_nids(r, idx) for r in lec["rows"] if r.get("on")]) if lec["rows"] else set()
                answer = idx.under(C.key_tag(root, o["label"]))
                m = C.score(pred, answer)
                rl = None
                if self.rules_too.isChecked():
                    rlec = C.new_lecture("2000-01-01", o["text"][:100], "lecture", [o])
                    E.LectureRun({**C.new_course("Measure"), "lectures": [rlec]}, rlec, idx, M.NoModel(), self.app.log,
                                 cfg, lambda: mw.col).run_all()
                    rp = set().union(*[C.row_nids(r, idx) for r in rlec["rows"] if r.get("on")]) if rlec["rows"] else set()
                    rl = C.score(rp, answer)
                self.results.append((o, m, secs, rl))
                pct = lambda x: f"{100 * x:.0f}%"  # noqa: E731
                self.table.addTopLevelItem(QTreeWidgetItem([
                    f"{o['label']}: {o['text'][:60]}", str(m["key"]), f"{pct(m['found'])} ({m['both']})",
                    f"{pct(m['right'])} of {m['chose']}", f"{secs:.0f}",
                    f"{pct(rl['found'])}" if rl else "", f"{pct(rl['right'])} of {rl['chose']}" if rl else ""]))
                one()

            def failed(e):
                self.app.log(f"measure {o['label']}: {e}")
                one()
            run_steps(run.steps(), scored, failed)
        one()

    def done(self):
        if not self.results:
            self.state.setText("")
            return
        n = len(self.results)
        avg = lambda xs: sum(xs) / len(xs) if xs else 0  # noqa: E731
        mf, mr = avg([m["found"] for _o, m, _s, _r in self.results]), avg([m["right"] for _o, m, _s, _r in self.results])
        secs = avg([s for _o, _m, s, _r in self.results])
        line = (f"{n} objective{'s' if n != 1 else ''}: the model found {100 * mf:.0f}% of the key's cards, and "
                f"{100 * mr:.0f}% of what it chose is in the key; {secs:.0f} s an objective ({self.app.model().label}).")
        rls = [r for _o, _m, _s, r in self.results if r]
        if rls:
            line += (f" Plain rules: found {100 * avg([r['found'] for r in rls]):.0f}%, "
                     f"right {100 * avg([r['right'] for r in rls]):.0f}%.")
        self.summary.setText(line)
        self.state.setText("Done.")

    def copy(self):
        rows = [self.summary.text(), ""]
        for o, m, s, r in self.results:
            rows.append(f"{o['label']}: key {m['key']}, model found {m['found']:.2f} ({m['both']}), right {m['right']:.2f} "
                        f"of {m['chose']}, {s:.0f} s" + (f"; rules found {r['found']:.2f}, right {r['right']:.2f} of {r['chose']}"
                                                         if r else ""))
        QApplication.clipboard().setText("\n".join(rows))
        tooltip("Copied: labels and numbers, no card text.")


# ---- a tag's cards by lecture (Browse) ----

class SplitDialog(QDialog):
    def __init__(self, app, parent, tag):
        super().__init__(parent)
        self.app, self.tag = app, tag
        res, name = F.resource_of(tag)
        self.setWindowTitle(f"{res} › {name}" if res else name)
        self.resize(560, 380)
        self.lay = QVBoxLayout(self)
        self.head = QLabel("")
        self.head.setWordWrap(True)
        self.lay.addWidget(self.head)
        self.grid = QGridLayout()
        self.lay.addLayout(self.grid)
        self.first = QCheckBox("First in Anki's line of new cards")
        self.first.setChecked(bool(app.cfg().get("first_in_line", True)))
        self.lay.addWidget(self.first)
        self.state = plain_label()
        self.lay.addWidget(self.state)
        self.lay.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        self.lay.addWidget(bb)
        self.refresh()

    def clear(self):
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w:
                w.deleteLater()

    def refresh(self):
        self.clear()
        c, idx = self.app.course(), self.app.index()
        if not c or idx is None:
            self.head.setText("Make a course first (Tools › Course on a Mac › Open).")
            return
        sp = E.split_tag(c, idx, self.tag)
        self.head.setText(f"<b>{sp['total']:,} cards</b> in {esc(c.get('deck') or '')}, for {esc(c['name'])}:")
        row = 0
        by_id = {l["id"]: l for l in c["lectures"]}
        for lid, cids in sorted(sp["by"].items(), key=lambda kv: by_id[kv[0]]["date"]):
            lec = by_id[lid]
            self.grid.addWidget(plain_label(f"{lec['date'][5:]} {lec['title']}: {len(cids):,} to open"), row, 0)
            b = QPushButton(f"Open {len(cids):,}")
            b.clicked.connect(lambda _=False, cids=cids, t=lec["title"]: self.open(cids, t))
            self.grid.addWidget(b, row, 1)
            row += 1
        if sp["open"]:
            self.grid.addWidget(plain_label(f"{len(sp['open']):,} open already"), row, 0)
            row += 1
        if sp["rest"]:
            self.grid.addWidget(plain_label(f"{len(sp['rest']):,} your course doesn't ask for (yet)"), row, 0)
            b = QPushButton("Ask the Mac model")
            b.setEnabled(self.app.model().name != "none" and not self.app.busy)
            b.clicked.connect(lambda _=False, n=sp["rest_nids"]: self.ask(n))
            self.grid.addWidget(b, row, 1)
            b2 = QPushButton(f"Open all {len(sp['rest']):,}")
            b2.clicked.connect(lambda _=False, cids=sp["rest"]: self.open(cids, self.windowTitle()))
            self.grid.addWidget(b2, row, 2)

    def open(self, cids, what):
        if not mw.col:
            return
        ids = E.openable(mw.col, cids)
        n = E.open_cards(mw.col, ids, f"Course: {what}", self.first.isChecked())
        self.app.mark_open(ids)
        self.app.after_change()
        tooltip(f"Opened {n:,} card{'s' if n != 1 else ''}. Edit › Undo puts them back.")
        self.refresh()
        if self.app.window:
            self.app.window.fill_list()

    def ask(self, nids):
        c, idx = self.app.course(), self.app.index()
        whole, owner = E.course_as_lecture(c, near=_today().isoformat())
        if not owner:
            self.state.setText("The course has no objectives to read them against.")
            return
        cfg, runner = self.app.cfg(), self.app.model()
        notes = E.note_rows(mw.col, nids[:120])
        self.state.setText(f"Reading {len(notes)} card{'s' if len(notes) != 1 else ''} against the course…")
        self.app.busy = True

        def done(got):
            self.app.busy = False
            fits, how, unread = got
            added = E.add_reads(c, self.tag, idx, None, fits, owner)
            self.app.save()
            self.state.setText(f"{sum(added.values())} fit a lecture ({how}).")
            self.refresh()
            if self.app.window:
                self.app.window.fill_list()

        def fail(e):
            self.app.busy = False
            self.state.setText(f"Stopped: {e}")
        bg(lambda: J.read(runner, whole, notes, [], self.app.log, int(cfg.get("read_batch") or 10),
                          int(cfg.get("prompt_chars") or 5200)), done, fail)
