"""Your plans' small windows (3.9.3, the builder's day panel in Anki): add
cards to a date (an Anki search, note or card IDs, notes: and cards:), a
date's lines to tick or the plan's lines every week, a review day, and
Split. Each wears the board's look; names are the authors' and the
deck's, plain text everywhere."""

from aqt.qt import (
    QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QRadioButton, QSpinBox, Qt, QTimer, QToolButton, QVBoxLayout, QWidget,
)

from ..ui import attach_alive, heading, note
from . import build as B


def _plain(text="", muted=False):
    w = QLabel(str(text))
    w.setTextFormat(Qt.TextFormat.PlainText)
    w.setWordWrap(True)
    return note(w) if muted else w


def _buttons(dialog, yes, extra=None):
    """Cancel, an extra (label, fn) when there's one, and the dialog's yes."""
    box = QDialogButtonBox()
    box.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole).clicked.connect(dialog.reject)
    if extra:
        b = QPushButton(extra[0])
        b.clicked.connect(extra[1])
        box.addButton(b, QDialogButtonBox.ButtonRole.ActionRole)
    go = QPushButton(yes)
    go.setDefault(True)
    go.clicked.connect(dialog.accept)
    box.addButton(go, QDialogButtonBox.ButtonRole.AcceptRole)
    return box, go


def paste_kind(text):
    """What a paste into Add cards is (the builder's searchBox): ("picks",
    {notes, cards}) for notes:/cards:, ("ids", [n]) for numbers, ("search",
    q) for anything else, ("bad", words) for a picks line it can't read,
    or None for nothing."""
    t = " ".join(str(text or "").split())
    if not t:
        return None
    if t[:6].lower() in ("notes:", "cards:"):
        r = B.picks_take(t)
        if r["bad"] or not (r["notes"] or r["cards"]):
            return ("bad", f"\"{(r['bad'] or [t])[0][:30]}\" isn't a note's ID from Anki (cards: takes ID:N, N the card's "
                           "number from 1).")
        return ("picks", {"notes": r["notes"], "cards": r["cards"]})
    if all(ch.isdigit() or ch in " ,;" for ch in t):
        got = list(dict.fromkeys(int(x) for x in t.replace(",", " ").replace(";", " ").split() if int(x) > 0))
        return ("ids", got) if got else None
    return ("search", t)


class AddCardsDialog(QDialog):
    """Add cards to a date: an Anki search, note or card IDs, or notes: and
    cards: as Browse copies them. count(q) -> the cards a search finds in
    this deck, or None when there's no deck here."""

    def __init__(self, parent, title, count):
        super().__init__(parent)
        attach_alive(self)
        self.count = count
        self.setWindowTitle("Add cards")
        self.setMinimumWidth(520)
        root = QVBoxLayout(self)
        heading(self, root, title)
        root.addWidget(_plain("An Anki search (each follower's Anki runs it in the plan's deck), note IDs or card IDs "
                              "(a spreadsheet's column), or notes: and cards: as Browse's Due Crew menu copies them.",
                              muted=True))
        self.box = QPlainTextEdit()
        self.box.setPlaceholderText('tag:#Videos::Cardio::Heart_Failure -tag:*Extra*   or   1688392011234, 1688392011235')
        self.box.setTabChangesFocus(True)
        self.box.setMinimumHeight(80)
        root.addWidget(self.box)
        row = QHBoxLayout()
        self.nids = QRadioButton("Note IDs (all their cards)")
        self.cids = QRadioButton("Card IDs (just those cards)")
        self.nids.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self.nids)
        group.addButton(self.cids)
        row.addWidget(self.nids)
        row.addWidget(self.cids)
        row.addStretch(1)
        self.kinds = QWidget()
        self.kinds.setLayout(row)
        row.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.kinds)
        self.said = _plain(muted=True)
        root.addWidget(self.said)
        box, self.go = _buttons(self, "Add")
        root.addWidget(box)
        self._typing = QTimer(self)  # a search runs in the collection: once the typing pauses
        self._typing.setSingleShot(True)
        self._typing.setInterval(300)
        self._typing.timeout.connect(self._said)
        self.box.textChanged.connect(self._typed)
        self._said()

    def _typed(self):
        self.go.setEnabled(False)
        self._typing.start()

    def what(self):
        """("search", q) | ("nids"|"cids", [n]) | ("picks", {notes, cards}) | None."""
        k = paste_kind(self.box.toPlainText())
        if not k or k[0] == "bad":
            return None
        if k[0] == "ids":
            return ("cids" if self.cids.isChecked() else "nids", k[1])
        return k

    def _said(self):
        k = paste_kind(self.box.toPlainText())
        self.kinds.setVisible(bool(k) and k[0] == "ids")
        ok, words = False, ""
        if k is None:
            words = ""
        elif k[0] == "bad":
            words = k[1]
        elif k[0] == "ids":
            n = len(k[1])
            ok = n <= B.IDS_MAX
            words = (f"{n:,} ID{'s' if n != 1 else ''}. Your Anki turns them into notes everyone's copy has after you save."
                     if ok else f"A date takes up to {B.IDS_MAX:,}. Split the list over two dates.")
        elif k[0] == "picks":
            n, m = len(k[1]["notes"]), len(k[1]["cards"])
            ok = n <= B.IDS_MAX
            words = " · ".join(x for x in (f"{n:,} note{'s' if n != 1 else ''}, all their cards" if n else "",
                                           f"{m:,} single card{'s' if m != 1 else ''}" if m else "") if x)
        else:
            q = k[1]
            from .. import plans as P
            if len(q) > B.SEARCH_LEN:
                words = f"A search is at most {B.SEARCH_LEN} characters."
            elif not P.shareable_search(q):
                words = "That finds different cards in each person's Anki. Use tags or decks."
            else:
                ok = True
                n = self.count(q)
                name = B.search_name(q)
                words = ((name if name.startswith("Search") else f"Search: {name}")
                         + (f" · finds {n:,} card{'s' if n != 1 else ''} here" if n is not None else "")
                         + (". Check it: it finds nothing here." if n == 0 else ""))
        self.said.setText(words)
        self.go.setEnabled(ok)


class LinesDialog(QDialog):
    """A date's lines to tick by hand (watch, read, do; a link may follow),
    or with `every`, the plan's lines every week, each on its weekdays."""

    def __init__(self, parent, title, lines, every=False):
        super().__init__(parent)
        attach_alive(self)
        self.every = every
        self.most = B.EVERY_MAX if every else B.TODO_MAX
        self.setWindowTitle("Every week" if every else "To do")
        self.setMinimumWidth(620)
        root = QVBoxLayout(self)
        heading(self, root, title)
        root.addWidget(_plain("Lines followers tick in Due on those days, from the plan's first date to its last."
                              if every else "What the date asks that cards can't measure: a lecture to watch, a chapter "
                              "to read. Each follower ticks it in Due.", muted=True))
        self.grid = QGridLayout()
        root.addLayout(self.grid)
        self.rows = []
        self.more = QPushButton("Add a line")
        self.more.setAutoDefault(False)
        self.more.clicked.connect(lambda: self._row({"k": "do" if every else "watch", "t": "", "r": "4"}))
        for x in lines or []:
            self._row(x)
        if not self.rows:
            self._row({"k": "do" if every else "watch", "t": "", "r": "4"})
        root.addWidget(self.more, 0, Qt.AlignmentFlag.AlignLeft)
        box, _go = _buttons(self, "Save")
        root.addWidget(box)

    def _row(self, x):
        if self._live() >= self.most:
            return
        i = len(self.rows)
        kind = QComboBox()
        for k, label in B.TODO_LABEL.items():
            kind.addItem(label, k)
        kind.setCurrentIndex(max(0, kind.findData(x.get("k"))))
        text = QLineEdit(str(x.get("t") or ""))
        text.setMaxLength(B.TODO_TEXT)
        text.setPlaceholderText("Practice questions" if self.every else "Lecture 14, renal clearance")
        link = QLineEdit(str(x.get("url") or ""))
        link.setMaxLength(500)
        link.setPlaceholderText("https:// (optional)")
        link.setMinimumWidth(170)
        gone = QToolButton()
        gone.setText("×")
        gone.setToolTip("Take this line off")
        row = {"kind": kind, "text": text, "link": link, "gone": gone, "days": []}
        self.grid.addWidget(kind, i, 0)
        self.grid.addWidget(text, i, 1)
        col = 2
        if self.every:
            days = QWidget()
            dl = QHBoxLayout(days)
            dl.setContentsMargins(0, 0, 0, 0)
            dl.setSpacing(2)
            for k, d in enumerate("MTWTFSS"):
                b = QToolButton()
                b.setText(d)
                b.setCheckable(True)
                b.setToolTip(B.DAYS[k])
                b.setChecked(str(k) in str(x.get("r") or ""))
                dl.addWidget(b)
                row["days"].append(b)
            self.grid.addWidget(days, i, col)
            col += 1
        self.grid.addWidget(link, i, col)
        self.grid.addWidget(gone, i, col + 1)
        self.grid.setColumnStretch(1, 3)
        self.grid.setColumnStretch(col, 2)
        gone.clicked.connect(lambda: self._drop(row))
        self.rows.append(row)
        self.more.setEnabled(self._live() < self.most)

    def _live(self):
        return sum(1 for r in self.rows if not r.get("gone_now"))

    def _drop(self, row):
        row["gone_now"] = True
        for k in ("kind", "text", "link", "gone"):
            row[k].hide()
        for b in row["days"]:
            b.hide()
        self.more.setEnabled(self._live() < self.most)

    def lines(self):
        out = []
        for r in self.rows:
            if r.get("gone_now"):
                continue
            x = {"k": r["kind"].currentData(), "t": r["text"].text().strip()}
            url = r["link"].text().strip()
            if url and B.ok_url(url):
                x["url"] = url
            if self.every:
                x["r"] = "".join(str(k) for k, b in enumerate(r["days"]) if b.isChecked())
            out.append(x)
        return out


class ReviewDialog(QDialog):
    """A review day: that morning, followers get a Due Crew deck of what
    they've seen of these dates, most missed first. dates: [(id, label)],
    the ones opening by then; now: (from, to) or None."""

    def __init__(self, parent, title, dates, now=None):
        super().__init__(parent)
        attach_alive(self)
        self.off = False
        self.setWindowTitle("Review day")
        self.setMinimumWidth(460)
        root = QVBoxLayout(self)
        heading(self, root, title)
        root.addWidget(_plain("That morning, followers get a Due Crew deck of what they've seen from these dates, "
                              "most missed first.", muted=True))
        grid = QGridLayout()
        self.frm, self.to = QComboBox(), QComboBox()
        for uid, label in dates:
            self.frm.addItem(label, uid)
            self.to.addItem(label, uid)
        a, b = now or (dates[max(0, len(dates) - 5)][0], dates[-1][0])
        self.frm.setCurrentIndex(max(0, self.frm.findData(a)))
        self.to.setCurrentIndex(max(0, self.to.findData(b)))
        grid.addWidget(_plain("From"), 0, 0)
        grid.addWidget(self.frm, 0, 1)
        grid.addWidget(_plain("To"), 1, 0)
        grid.addWidget(self.to, 1, 1)
        grid.setColumnStretch(1, 1)
        root.addLayout(grid)
        box, _go = _buttons(self, "Make it a review day" if now is None else "Save",
                            None if now is None else ("No review day", self._off))
        root.addWidget(box)

    def _off(self):
        self.off = True
        self.accept()

    def value(self):
        return ("off",) if self.off else ("set", self.frm.currentData(), self.to.currentData())


class SplitDialog(QDialog):
    """Split a date's tag: by its own tags (laid out as Fill does, at the
    plan's pace), or evenly over some study days."""

    def __init__(self, parent, name, total, parts, cap, days):
        super().__init__(parent)
        attach_alive(self)
        self.total = total
        self.setWindowTitle("Split")
        self.setMinimumWidth(480)
        root = QVBoxLayout(self)
        heading(self, root, f"Split {name} · {total:,} cards")
        self.tags = QRadioButton("By its tags")
        self.even = QRadioButton("Evenly over")
        group = QButtonGroup(self)
        group.addButton(self.tags)
        group.addButton(self.even)
        root.addWidget(self.tags)
        root.addWidget(_plain((f"{parts}, {f'at {cap:,} a day' if cap else 'one a study day'}" if parts
                               else "Nothing below this tag."), muted=True))
        row = QHBoxLayout()
        row.addWidget(self.even)
        self.days = QSpinBox()
        self.days.setRange(2, 60)
        self.days.setValue(max(2, min(60, days)))
        row.addWidget(self.days)
        row.addWidget(_plain("study days"))
        self.per = _plain(muted=True)
        row.addWidget(self.per)
        row.addStretch(1)
        root.addLayout(row)
        self.tags.setEnabled(bool(parts))
        (self.tags if parts else self.even).setChecked(True)
        self.days.valueChanged.connect(self._per)
        self._per()
        box, _go = _buttons(self, "Split")
        root.addWidget(box)

    def _per(self):
        self.per.setText(f"≈ {-(-self.total // max(2, self.days.value())):,} a day")

    def value(self):
        return ("tags",) if self.tags.isChecked() else ("even", int(self.days.value()))
