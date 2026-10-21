"""QBank QIDs (docs/planner.md; Question IDs in labs, for everyone since
3.9.3): after a practice block, paste the IDs of the questions you missed,
any way the bank copies them. Due Crew picks out the numbers, finds their
cards by the deck's question tags, and says what it found (and what isn't
a question here). This paste only (3.9.3, Sam): nothing is kept and
nothing is sent; what's not sticking is Insights' to say.

Two things to do with them (3.9.3, Sam: no moving due dates): Unsuspend,
the new ones first in line; or Study now, a deck of them (Due Crew ›
QBank cards, each paste adding to it) that reschedules by my answers,
each card going back to its own deck once done. Browse shows them."""

from aqt.qt import QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, Qt, QTimer, QVBoxLayout

from ..ui import attach_alive, heading, note
from . import qids as Q
from .widgets import link

def _plain(text="", muted=False):
    w = QLabel(str(text))
    w.setTextFormat(Qt.TextFormat.PlainText)
    w.setWordWrap(True)
    return note(w) if muted else w


class QidWindow(QDialog):
    """choices: [(deck id, name)]; ops: flow.QidOps, or a render's own; did:
    the deck to start on (Insights' line), else the one my plans run on."""

    def __init__(self, parent, col, choices, ops, did=None):
        super().__init__(parent)
        self.col, self.ops, self.choices = col, ops, list(choices)
        self.idx = self.found = self.t = None
        self.picked = None  # the bank I picked, while it's this paste's and this deck's
        attach_alive(self)
        self.setWindowTitle("QBank QIDs")
        self.setModal(False)
        self.setMinimumWidth(560)
        root = QVBoxLayout(self)
        heading(self, root, "QBank QIDs")
        form = QFormLayout()
        self.deck = QComboBox()
        for did_, name in self.choices:
            self.deck.addItem(name, did_)
        form.addRow("Deck", self.deck)
        self.bank = QComboBox()
        self.bank_label = QLabel("Bank")
        form.addRow(self.bank_label, self.bank)
        root.addLayout(form)
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("Paste the IDs of the questions you missed")
        self.text.setTabChangesFocus(True)
        self.text.setMinimumHeight(96)
        root.addWidget(self.text)
        counts = QHBoxLayout()
        self.lines = _plain()  # "5 questions · 14 cards · 10 suspended"
        counts.addWidget(self.lines)
        self.browse_btn = link("Browse", lambda: self.ops.browse(self.cids()))
        counts.addWidget(self.browse_btn)
        counts.addStretch(1)
        root.addLayout(counts)
        self.more = _plain(muted=True)  # what isn't a question here; my plan's dates
        root.addWidget(self.more)
        self.said = _plain(muted=True)
        root.addWidget(self.said)
        buttons = QHBoxLayout()
        self.unsuspend_btn = QPushButton("Unsuspend")
        self.unsuspend_btn.setAutoDefault(False)
        self.unsuspend_btn.clicked.connect(self._unsuspend)
        buttons.addWidget(self.unsuspend_btn)
        buttons.addStretch(1)
        close = QPushButton("Close")
        close.setAutoDefault(False)
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        self.study_btn = QPushButton("Study now")
        self.study_btn.setDefault(True)
        self.study_btn.clicked.connect(self._study)
        buttons.addWidget(self.study_btn)
        root.addLayout(buttons)
        self.where = _plain("Study now adds them to Due Crew › QBank cards. "
                            "Each card goes back to its own deck once you’ve done it.", muted=True)
        root.addWidget(self.where)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._count)
        self.text.textChanged.connect(self._pasted)
        self.deck.currentIndexChanged.connect(self._deck)
        self.bank.activated.connect(self._pick_bank)  # a pick of mine, never one the count made
        start = did if any(d == did for d, _n in self.choices) else self.ops.default_deck(self.choices)
        at = next((i for i, (d, _n) in enumerate(self.choices) if d == start), 0)
        if self.choices:
            self.deck.setCurrentIndex(at)
        self._deck()

    def pick_deck(self, did):
        """The window, on this deck (Insights' line, the window open already)."""
        i = self.deck.findData(did)
        if i >= 0 and i != self.deck.currentIndex():
            self.deck.setCurrentIndex(i)

    # ---- what it acts on ----

    def cids(self):
        """Every card the questions found."""
        return set((self.found or {}).get("cids") or ())

    def _pasted(self):
        self.picked = None  # a new paste: the bank its numbers say
        self.said.setText("")
        self._timer.start()

    def _pick_bank(self, _i):
        self.picked = self.bank.currentText() or None
        self._count()

    # ---- reading ----

    def _deck(self, *_):
        did = self.deck.currentData()
        self.picked = None
        self.idx = self.ops.index(did) if did is not None else None
        self._count()

    def _count(self):
        if self.idx is None:
            self.found, self.t = None, None
            self.lines.setText("No deck to look in.")
            self.more.setText("")
            self._show()
            return
        self.found = Q.find(self.idx, self.text.toPlainText(), self.picked)
        self.t = Q.tally(self.idx, self.found["cids"])
        banks = self.found["banks"]
        names = [b for b, _n in banks]
        self.bank.blockSignals(True)
        if [self.bank.itemText(i) for i in range(self.bank.count())] != names:
            self.bank.clear()
            for b in names:
                self.bank.addItem(b)
        if self.found["bank"] in names:
            self.bank.setCurrentIndex(names.index(self.found["bank"]))
        self.bank.blockSignals(False)
        many = len(banks) > 1
        self.bank.setVisible(many)
        self.bank_label.setVisible(many)
        dates = self.ops.plan_dates(self.deck.currentData(), self.idx, self.found["cids"]) if self.found["cids"] else []
        if not Q.banks(self.idx):
            lines = [f"{self.idx.name} has no question IDs in its tags."]
        else:
            lines = Q.words(self.found, self.t, dates)
        self.lines.setText(lines[0] if lines else "")
        self.more.setText("\n".join(lines[1:]))
        self.more.setVisible(len(lines) > 1)
        self._show()

    def _show(self):
        cids = self.cids()
        t = Q.tally(self.idx, cids) if self.idx is not None and cids else {}
        shut = int(t.get("shut") or 0)
        self.unsuspend_btn.setText(f"Unsuspend {shut:,}" if shut else "Unsuspend")
        self.unsuspend_btn.setEnabled(bool(shut))
        self.browse_btn.setVisible(bool(cids))
        self.study_btn.setEnabled(bool(cids) and int(t.get("cards") or 0) > int(t.get("leech") or 0))
        self.where.setVisible(bool(cids))

    # ---- doing ----

    def _unsuspend(self):
        n = self.ops.unsuspend(self.cids())
        self.said.setText(f"Unsuspended {n:,}, first in line." if n else "None needed unsuspending.")
        self._deck()  # the deck read again: what's suspended now

    def _study(self):
        if self.ops.study(self.cids()):
            self.accept()
