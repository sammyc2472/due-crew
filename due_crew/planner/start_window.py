"""Labs, a plan from a block's calendar (docs/planner.md): paste the
calendar, Read it, and every session comes back with the deck tags its
words name, ticked where plain rules are sure; what plain rules leave,
Claude's stand-in fills when its box is ticked (claude.py), and each row
says who did it. Quizzes and exams become the plan's events; What's on
it… reads an exam's line ("Exam 1 covers weeks 1-3"). Make the plan puts
it on duecrew.com as mine (POST /plans, then the builder's save) and opens
it in the plan window. What Claude would get shows what the jobs the
stand-in did would send, before anything ever is: nothing is sent now.
Names are the calendar's and the deck's: plain text everywhere."""

import json

import os

from aqt.qt import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QPlainTextEdit, QPushButton, Qt, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

from ..ui import ask_text, attach_alive, confirm, esc, heading, note, role
from .. import plans as P
from . import claude as C
from . import edits as E
from . import model as M
from . import reading as R

ROLE = Qt.ItemDataRole.UserRole
EXAMPLE = ("Paste the block's calendar here, or drop its file on this box: " + R.KINDS_READ + ".\n\n"
           "BLOCK 2 · Cardiovascular\nWEEK 1\nMon 10/26  LEC  Heart failure\n"
           "    SLG 1  Define systolic and diastolic heart failure\n    Watch: heart failure 1-2\n"
           "Tue 10/27  LEC  Heart failure drugs\nFri 10/30  QUIZ  Cardio quiz 1")
FILES = "Calendars (*.ics *.pdf *.docx *.pptx *.csv *.tsv *.txt *.md);;Any file (*)"
SLIDES = "Slides (*.pptx *.pdf);;Any file (*)"


class DropBox(QPlainTextEdit):
    """The calendar's box: paste it in, or drop its file on it (one file, on
    this computer; on_file(path) reads it). While a file is over it, it
    says so in the accent."""

    def __init__(self, on_file):
        super().__init__()
        self.on_file = on_file
        self.setProperty("dc", "drop")
        self.setAcceptDrops(True)

    @staticmethod
    def path_of(mime):
        """The one local file a drag carries, else None (text drops as text)."""
        urls = [u for u in mime.urls() if u.isLocalFile()] if mime is not None and mime.hasUrls() else []
        return urls[0].toLocalFile() if len(urls) == 1 else None

    def _over(self, on):
        self.setProperty("over", bool(on))
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, e):
        if self.path_of(e.mimeData()):
            e.acceptProposedAction()
            self._over(True)
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if self.path_of(e.mimeData()):
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dragLeaveEvent(self, e):
        self._over(False)
        super().dragLeaveEvent(e)

    def dropEvent(self, e):
        path = self.path_of(e.mimeData())
        self._over(False)
        if path:
            e.acceptProposedAction()
            self.on_file(path)
        else:
            super().dropEvent(e)


def pdf_text(path, pages=False):
    """A PDF's text (Qt's own reader), up to R.PAGES_MAX pages: one string,
    or with pages a list, a page each; None when this Anki's Qt has no
    reader or the file won't open."""
    try:
        from PyQt6.QtPdf import QPdfDocument
    except ImportError:
        return None
    doc = QPdfDocument(None)
    try:
        if doc.load(path) != QPdfDocument.Error.None_:
            return None
        got = [doc.getAllText(n).text().replace("\r\n", "\n").replace("\r", "\n")
               for n in range(min(doc.pageCount(), R.PAGES_MAX))]
        return got if pages else "\n".join(got)
    finally:
        doc.close()


class DropTree(QTreeWidget):
    """The sessions: a lecture's slides (or its PDF) dropped on a session's
    row add to it (on_file(path, row)); the row a file is over is the one
    picked."""

    def __init__(self, on_file):
        super().__init__()
        self.on_file = on_file
        self.setAcceptDrops(True)

    def _row(self, e):
        item = self.itemAt(e.position().toPoint())
        while item is not None and item.parent() is not None:
            item = item.parent()
        data = item.data(0, ROLE) if item is not None else None
        return item if data and data[0] == "session" else None

    def dragEnterEvent(self, e):
        if DropBox.path_of(e.mimeData()):
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        path = DropBox.path_of(e.mimeData())
        if not path:
            super().dragMoveEvent(e)
            return
        row = self._row(e)
        if row is not None and R.kind_of_file(path) in ("pptx", "pdf"):
            self.setCurrentItem(row)
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e):
        path, row = DropBox.path_of(e.mimeData()), self._row(e)
        if path and row is not None:
            e.acceptProposedAction()
            self.on_file(path, row)
        else:
            super().dropEvent(e)


def _plain(text="", muted=False):
    w = QLabel(str(text))
    w.setTextFormat(Qt.TextFormat.PlainText)
    w.setWordWrap(True)
    return note(w) if muted else w


class StartWindow(QDialog):
    """decks: [(deck id, name, cards)], biggest first; ops: flow.StartOps,
    or a render's or test's own."""

    def __init__(self, parent, decks, ops, reader=None):
        super().__init__(parent)
        self.ops, self.reader = ops, reader or C.StandIn()
        self.decks = list(decks)
        self.idx = None
        self.sessions = []   # reading's sessions, numbered by week
        self.cands = {}      # session index -> candidates
        self.who = {}        # session index -> (who, why)
        self.scopes = {}     # event's session index -> ([covered index], [(said, who)])
        self.asked = []      # what the stand-in did: [(job, request kwargs)], for What Claude would get
        self.made = None     # a plan made whose dates didn't save: Make tries them again, on it
        self.file = ""       # the file the box's text came from, by name
        self._named = ""     # the name a reading gave (a name typed in stays)
        attach_alive(self)
        self.setWindowTitle("New plan from a calendar")
        self.setModal(False)
        self.setMinimumSize(760, 640)
        root = QVBoxLayout(self)
        heading(self, root, "A plan from a block's calendar")
        root.addWidget(_plain(self.reader.status(), muted=True))
        form = QFormLayout()
        self.name = QLineEdit()
        self.name.setMaxLength(60)
        self.name.setPlaceholderText("MS2 Block 2")
        form.addRow("Name", self.name)
        self.deck = QComboBox()
        for did, name, n in self.decks:
            self.deck.addItem(f"{name} · {n:,} cards", did)
        form.addRow("Deck", self.deck)
        root.addLayout(form)
        self.text = DropBox(self._load_file)
        self.text.setPlaceholderText(EXAMPLE)
        self.text.setTabChangesFocus(True)
        self.text.setMinimumHeight(130)
        root.addWidget(self.text)
        row = QHBoxLayout()
        self.stand_in = QCheckBox("Let Claude’s stand-in fill what plain rules leave")
        self.stand_in.setChecked(True)
        row.addWidget(self.stand_in)
        row.addStretch(1)
        self.file_btn = QPushButton("Choose a file…")
        self.file_btn.clicked.connect(self._choose)
        row.addWidget(self.file_btn)
        self.read_btn = QPushButton("Read it")
        self.read_btn.clicked.connect(self._read)
        row.addWidget(self.read_btn)
        root.addLayout(row)
        self.tree = DropTree(lambda path, row: self._add_slides(path, row.data(0, ROLE)[1]))
        self.tree.setHeaderLabels(["Session", "Cards", "Read by"])
        h = self.tree.header()
        h.setStretchLastSection(False)
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.itemChanged.connect(self._ticked)
        self.tree.itemSelectionChanged.connect(self._buttons)
        root.addWidget(self.tree, 1)
        self.head = role(_plain(), "head")
        root.addWidget(self.head)
        self.said = _plain(muted=True)
        root.addWidget(self.said)
        buttons = QDialogButtonBox()
        self.add_btn = QPushButton("Add tags…")
        self.add_btn.clicked.connect(self._add)
        buttons.addButton(self.add_btn, QDialogButtonBox.ButtonRole.ActionRole)
        self.slides_btn = QPushButton("Add its slides…")
        self.slides_btn.clicked.connect(self._choose_slides)
        buttons.addButton(self.slides_btn, QDialogButtonBox.ButtonRole.ActionRole)
        self.scope_btn = QPushButton("What's on it…")
        self.scope_btn.clicked.connect(self._scope)
        buttons.addButton(self.scope_btn, QDialogButtonBox.ButtonRole.ActionRole)
        self.would_btn = QPushButton("What Claude would get")
        self.would_btn.clicked.connect(self._would)
        buttons.addButton(self.would_btn, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton("Close", QDialogButtonBox.ButtonRole.RejectRole).clicked.connect(self.reject)
        self.make_btn = QPushButton("Make the plan")
        self.make_btn.setDefault(True)
        self.make_btn.clicked.connect(self._make)
        buttons.addButton(self.make_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        root.addWidget(buttons)
        self.deck.currentIndexChanged.connect(lambda _i: self._read() if self.sessions else None)
        self.name.textChanged.connect(lambda _t: self._buttons())
        self._buttons()

    # ---- a file ----

    def _choose(self):
        path, _f = QFileDialog.getOpenFileName(self, "A block's calendar", "", FILES)
        if path:
            self._load_file(path)

    def _load_file(self, path):
        """A calendar's file into the box, then read: on this computer only."""
        name = os.path.basename(str(path))
        kind = R.kind_of_file(name)
        try:
            if os.path.getsize(path) > (R.BIG_MAX if kind in R.BIG else R.FILE_MAX):
                text, why = "", "That file is too big to be a calendar."
            elif kind == "pdf":
                text = pdf_text(path)
                if not text or not text.strip():
                    text, why = "", "That PDF's text couldn't be read here. Copy its text in instead."
                elif R.scrambled(text):
                    text, why = "", "That PDF's text came out in pieces. Copy its text in instead."
                else:
                    text, why = text.replace("\r\n", "\n").replace("\r", "\n")[:R.TEXT_MAX], ""
            else:
                with open(path, "rb") as f:
                    text, why = R.from_file(name, f if kind in ("docx", "pptx") else f.read())
        except OSError:
            text, why = "", "That file couldn't be opened."
        if why:
            self.said.setText(why)
            return
        self.file = name
        self.text.setPlainText(text)
        self._read()

    # ---- a lecture's slides, onto its session ----

    def _choose_slides(self):
        p = self._picked()
        if not p or p[0] != "session":
            return
        path, _f = QFileDialog.getOpenFileName(self, "The lecture's slides", "", SLIDES)
        if path:
            self._add_slides(path, p[1])

    def _slide_pages(self, path):
        """([(title, [lines])], why not): a deck's slides, or a PDF's pages."""
        name = os.path.basename(str(path))
        kind = R.kind_of_file(name)
        try:
            if os.path.getsize(path) > R.BIG_MAX:
                return [], "That file is too big."
            if kind == "pptx":
                with open(path, "rb") as f:
                    return R.pptx_slides(f), ""
            if kind == "pdf":
                pages = pdf_text(path, pages=True)
                if not pages:
                    return [], "That PDF's text couldn't be read here."
                if R.scrambled("\n".join(pages)):
                    return [], "That PDF's text came out in pieces."
                return R.pdf_pages(pages), ""
        except OSError:
            return [], "That file couldn't be opened."
        except Exception:  # a broken deck: zipfile's and the XML's own errors
            return [], "Those slides couldn't be read."
        return [], "Slides are a PowerPoint (.pptx) or a PDF."

    def _add_slides(self, path, i):
        """A lecture's slides onto session i: its objectives slide's lines and
        its slides' titles, then its tags found again with them (by plain
        rules, then the stand-in). Read on this computer; never sent."""
        if self.idx is None or not (0 <= i < len(self.sessions)) or self.sessions[i]["kind"] in R.EVENT_KINDS:
            return
        pages, why = self._slide_pages(path)
        got = R.from_slides(pages) if pages else None
        if not got or not (got["objectives"] or got["slides"]):
            self.said.setText(why or "Nothing on those slides to go by.")
            return
        s = self.sessions[i]
        have = {o["text"].lower() for o in s.get("objectives") or []}
        s["objectives"] = list(s.get("objectives") or []) + [o for o in got["objectives"] if o["text"].lower() not in have]
        s["slides"] = list(dict.fromkeys(list(s.get("slides") or []) + got["slides"]))[:80]
        keep = {k: v for k, v in self.picks().items() if k != i}
        cands = R.candidates(self.idx, s)
        pick = R.pick(cands)
        who = ("plain rules", "with its slides")
        if not pick and self.stand_in.isChecked():
            near = R.nearby(self.idx, [t for v in keep.values() for t in v])
            self.asked.append(("pick", {"session": s, "cands": R.could_fit(self.idx, s, near)}))
            cands, pick, why2 = self.reader.pick(self.idx, s, cands)
            who = (self.reader.name, f"{why2}, with its slides") if pick else ("nothing fits", "")
        elif not pick:
            who = ("nothing fits", "")
        self.cands[i], self.who[i] = cands, who
        picks = {k: {n for n, c in enumerate(self.cands.get(k) or []) if c["tag"] in v} for k, v in keep.items()}
        picks[i] = set(pick)
        self._fill(picks)
        self._show_session(i)
        n_obj, n_sl = len(got["objectives"]), len(got["slides"])
        self.said.setText(f"{s['title']}: {n_sl:,} slide title{'s' if n_sl != 1 else ''}"
                          + (f" and {n_obj:,} objective{'s' if n_obj != 1 else ''}" if n_obj else "")
                          + f" from {os.path.basename(str(path))}.")

    # ---- reading ----

    def _read(self):
        did = self.deck.currentData()
        if did is None:
            self.said.setText("No deck here to match the sessions to.")
            return
        text = self.text.toPlainText()
        today = self.ops.today()
        self.idx = self.ops.index(did)
        self.asked, self.scopes, self.who, self.cands = [], {}, {}, {}
        sessions, by = R.read_calendar(text, today), "plain rules"
        if not sessions and text.strip() and self.stand_in.isChecked():
            sessions, by = self.reader.calendar(text, today), self.reader.name
            self.asked.append(("calendar", {"text": text, "today": today}))
        self.sessions = R.number_weeks(sessions)
        if self.sessions and (not self.name.text().strip() or self.name.text() == self._named):
            self._named = R.name_from(text) or R.file_name(self.file)
            self.name.setText(self._named)
        plain = {}
        for i, s in enumerate(self.sessions):
            if s["kind"] not in R.EVENT_KINDS:
                cands = R.candidates(self.idx, s)
                plain[i] = (cands, R.pick(cands))
        near = R.nearby(self.idx, [c[k]["tag"] for c, got in plain.values() for k in got])
        picks = {}
        for i, (cands, got) in plain.items():
            who = ("plain rules", "")
            if not got and self.stand_in.isChecked():
                s = self.sessions[i]
                self.asked.append(("pick", {"session": s, "cands": R.could_fit(self.idx, s, near)}))
                cands, got, why = self.reader.pick(self.idx, s, cands)
                who = (self.reader.name, why) if got else ("nothing fits", "")
            elif not got:
                who = ("nothing fits", "")
            self.cands[i], self.who[i] = cands, who
            picks[i] = set(got)
        self._fill(picks)
        self.head.setText(f"Calendar read by {by}" if self.sessions else "")
        if not self.sessions:
            self.said.setText("No sessions found: each needs a date (Mon 10/26, Oct 26, 2026-10-26)."
                              + ("" if self.stand_in.isChecked() else " Claude’s stand-in could look for dates anywhere in a line."))
        self._buttons()

    def _fill(self, picks):
        self.tree.blockSignals(True)
        self.tree.clear()
        for i, s in enumerate(self.sessions):
            label = f"{P.fmt_day(s['date'])} · {s['title']}"
            if s["kind"] in R.EVENT_KINDS:
                item = QTreeWidgetItem([f"{label} ({s['kind']})", "", ""])
                item.setData(0, ROLE, ("event", i))
                self.tree.addTopLevelItem(item)
                self._scope_rows(item, i)
                continue
            who, why = self.who.get(i, ("", ""))
            item = QTreeWidgetItem([label, "", who])
            item.setData(0, ROLE, ("session", i))
            if why:
                item.setToolTip(2, f"<span>{esc(why)}</span>")
            self.tree.addTopLevelItem(item)
            for k, c in enumerate(self.cands.get(i) or []):
                child = QTreeWidgetItem([c["label"], f"{c['cards']:,}", ""])
                child.setData(0, ROLE, ("tag", i, c["tag"]))
                child.setToolTip(0, f"<span>{esc(c['tag'])}</span>")
                child.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                child.setCheckState(0, Qt.CheckState.Checked if k in picks.get(i, ()) else Qt.CheckState.Unchecked)
                item.addChild(child)
            item.setExpanded(bool(picks.get(i)))
        self.tree.blockSignals(False)
        self._count()

    def _show_session(self, i):
        """After a redraw, session i stays picked, open and in view."""
        for n in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(n)
            if top.data(0, ROLE) == ("session", i):
                top.setExpanded(True)
                self.tree.setCurrentItem(top)
                self.tree.scrollToItem(top)
                return

    def _scope_rows(self, item, i):
        while item.childCount():
            item.removeChild(item.child(0))
        covered, said = self.scopes.get(i, ([], []))
        for text, who in said:
            item.addChild(QTreeWidgetItem([f"“{text}”", "", who]))
        if covered:
            item.addChild(QTreeWidgetItem([f"Covers {len(covered):,} session{'s' if len(covered) != 1 else ''}: "
                                           + ", ".join(self.sessions[k]["title"] for k in covered[:6])
                                           + (" …" if len(covered) > 6 else ""), "", ""]))
            item.setExpanded(True)

    def picks(self):
        """{session index: [tag]} as ticked now."""
        out = {}
        for n in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(n)
            kind, i = top.data(0, ROLE)
            if kind != "session":
                continue
            out[i] = [top.child(k).data(0, ROLE)[2] for k in range(top.childCount())
                      if top.child(k).checkState(0) == Qt.CheckState.Checked]
        return out

    def _ticked(self, item, col):
        data = item.data(0, ROLE)
        if col == 0 and data and data[0] == "tag":
            self._count()

    def _count(self):
        picks = self.picks()
        dates = sum(1 for v in picks.values() if v)
        events = sum(1 for s in self.sessions if s["kind"] in R.EVENT_KINDS)
        none = sum(1 for v in picks.values() if not v)
        cids = set()
        for tags in picks.values():
            for t in tags:
                cids |= self.idx.tag_cards(t) if self.idx is not None else set()
        for n in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(n)
            kind, i = top.data(0, ROLE)
            if kind == "session":
                mine = set()
                for t in picks.get(i) or []:
                    mine |= self.idx.tag_cards(t)
                top.setText(1, f"{len(mine):,}" if mine else "")
                top.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if self.sessions:
            bits = [f"{len(self.sessions):,} session{'s' if len(self.sessions) != 1 else ''}",
                    f"{dates:,} date{'s' if dates != 1 else ''} with cards ({len(cids):,} in your {self.idx.name})"]
            if events:
                bits.append(f"{events:,} quiz{'zes' if events != 1 else ''} and exams" if events != 1 else "1 quiz or exam")
            if none:
                bits.append(f"{none:,} with nothing ticked stay{'s' if none == 1 else ''} off")
            self.said.setText(" · ".join(bits))
        self._buttons()

    # ---- the buttons ----

    def _picked(self):
        item = self.tree.currentItem()
        while item is not None and item.parent() is not None:
            item = item.parent()
        return item.data(0, ROLE) if item is not None else None

    def _buttons(self):
        p = self._picked()
        self.add_btn.setEnabled(bool(p) and p[0] == "session" and self.idx is not None)
        self.slides_btn.setEnabled(bool(p) and p[0] == "session" and self.idx is not None)
        self.scope_btn.setEnabled(bool(p) and p[0] == "event")
        self.would_btn.setEnabled(bool(self.sessions))
        self.make_btn.setEnabled(any(self.picks().values()) and bool(self.name.text().strip()))

    def _add(self):
        p = self._picked()
        if not p or p[0] != "session":
            return
        from .picker import pick_sources
        s = self.sessions[p[1]]
        got = pick_sources(self, self.idx, f"Add to {P.fmt_day(s['date'])} · {s['title']}", self.idx.name)
        if not got:
            return
        tags, _decks = got
        have = {c["tag"] for c in self.cands.get(p[1]) or []}
        for t in tags:
            if t not in have:
                c = M.counts(self.idx, self.idx.tag_cards(t))
                self.cands.setdefault(p[1], []).append({"tag": t, "label": M.label(t), "kind": M.kind(t),
                                                        "group": M.split(t)[0], "score": 0, "title": False,
                                                        "cards": c["cards"], "new": c["new"]})
        picks = {i: {k for k, c in enumerate(self.cands.get(i) or []) if c["tag"] in v or (i == p[1] and c["tag"] in tags)}
                 for i, v in self.picks().items()}
        self.who[p[1]] = ("you", "")
        self._fill(picks)
        self._show_session(p[1])

    def _scope(self):
        p = self._picked()
        if not p or p[0] != "event":
            return
        s = self.sessions[p[1]]
        line, ok = ask_text(self, f"What's on {s['title']}", "What it covers, as the syllabus or an email says it:",
                            "")
        if not ok or not line.strip():
            return
        covered, left = R.scope(line, self.sessions, self.ops.today())
        said = [(line.strip(), "plain rules")] if covered else []
        if left and self.stand_in.isChecked():
            self.asked.append(("scope", {"phrases": left, "sessions": self.sessions, "tags": self.picks()}))
            more, still = self.reader.scope(left, self.sessions, self.picks())
            covered = sorted(set(covered) | set(more))
            said += [(x, self.reader.name) for x in left if x not in still]
            said += [(x, "couldn’t place it") for x in still]
        elif left:
            said += [(x, "couldn’t place it") for x in left]
        self.scopes[p[1]] = ([i for i in covered if self.sessions[i]["date"] <= s["date"]], said)
        item = self.tree.currentItem()
        while item.parent() is not None:
            item = item.parent()
        self.tree.blockSignals(True)
        self._scope_rows(item, p[1])
        self.tree.blockSignals(False)

    def would_get(self):
        """What a connected Claude would have been sent for this reading:
        [request], one a job the stand-in did."""
        return [C.request(job, **kw) for job, kw in self.asked]

    def _would(self):
        self.would_window().exec()

    def would_window(self):
        got = self.would_get()
        dlg = QDialog(self)
        attach_alive(dlg)
        dlg.setWindowTitle("What Claude would get")
        dlg.setMinimumSize(620, 480)
        lay = QVBoxLayout(dlg)
        heading(dlg, lay, "What Claude would get")
        lay.addWidget(_plain("Plain rules did everything here: nothing would go to Claude." if not got else
                             f"{len(got):,} job{'s' if len(got) != 1 else ''} the stand-in did. Claude would get "
                             "the calendar's words and the deck's tag names, never a card's text. Nothing is sent "
                             "while it's a stand-in.", muted=True))
        box = QPlainTextEdit()
        box.setReadOnly(True)
        box.setPlainText(json.dumps(got, indent=2, ensure_ascii=False) if got else "")
        box.setVisible(bool(got))
        lay.addWidget(box, 1)
        bb = QDialogButtonBox()
        bb.addButton("Close", QDialogButtonBox.ButtonRole.RejectRole).clicked.connect(dlg.reject)
        lay.addWidget(bb)
        return dlg

    def doc(self):
        """The plan's doc as this window would make it: (doc, dates, events)."""
        deck = self.idx.name if self.idx is not None else ""
        doc, units, events = E.from_sessions({"deck": deck, "units": []}, self.sessions, self.picks(),
                                             {i: v[0] for i, v in self.scopes.items()})
        if self.idx is not None and units:
            doc = E.recount(doc, self.idx, set(units.values()))
        return doc, units, events

    def _make(self):
        name = self.name.text().strip()
        if not name or not any(self.picks().values()):
            return
        try:
            doc, units, events = self.doc()
        except E.Refused as e:
            self.said.setText(str(e))
            return
        if self.made is None and not confirm(
                self, f"Make {name} on duecrew.com?",
                f"{len(units):,} date{'s' if len(units) != 1 else ''} and {len(events):,} quiz"
                f"{'zes' if len(events) != 1 else ''} or exams. It's yours: nobody follows it till you share "
                "its code, and you can change anything in the plan window or the builder.", "Make it"):
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
            self.said.setText(f"The plan is on duecrew.com, but its dates didn't save. {got[2]} "
                              "Make the plan tries them again, on it.")
            return
        outcome, what = got
        if outcome != "saved":
            self.said.setText(str(what))
            return
        self.made = None
        self.ops.open_plan(what.get("id"))
        self.accept()
