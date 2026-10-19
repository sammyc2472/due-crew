"""Missed questions (docs/planner.md; Question IDs in labs, for everyone
since 3.9.3): after a practice block, paste the IDs of the questions you
missed, any way the bank copies them. Due Crew
picks out the numbers, finds their cards by the deck's question tags, and
says what it found (and what isn't a question here), and what they have in
common: the threads, by the deck's own system and resource tags. Do it
opens the shut ones and, asked, brings the ones you've seen back over the
next 3 days, one undo step; Study them now is a deck of them (or of one
thread). What you act on is kept on this computer, numbers only, so All my
misses shows the threads across every block. Nothing is sent."""

from aqt.qt import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPlainTextEdit, QPushButton, QRadioButton, Qt, QTimer, QVBoxLayout,
)

from ..ui import attach_alive, confirm, heading, note, role
from . import actions as A
from . import qids as Q

ROLE = Qt.ItemDataRole.UserRole


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
        self.gone = None  # what Forget took out, while its Undo shows
        self.pasted = ""  # the paste, while All my misses shows the kept ones in its place
        self.threads = []
        self.picked = None  # the bank I picked, while it's this paste's and this deck's
        attach_alive(self)
        self.setWindowTitle("Missed questions")
        self.setModal(False)
        self.setMinimumWidth(560)
        root = QVBoxLayout(self)
        heading(self, root, "Paste the questions you missed")
        root.addWidget(_plain("From your question bank’s results, any way they copy: Due Crew picks out "
                              "the numbers and finds their cards by your deck’s question tags.", muted=True))
        form = QFormLayout()
        self.deck = QComboBox()
        for did, name in self.choices:
            self.deck.addItem(name, did)
        form.addRow("Deck", self.deck)
        self.bank = QComboBox()
        self.bank_label = QLabel("Bank")
        form.addRow(self.bank_label, self.bank)
        root.addLayout(form)
        scope = QHBoxLayout()
        self.paste = QRadioButton("This paste")
        self.all = QRadioButton("All my misses")
        self.paste.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self.paste)
        group.addButton(self.all)
        scope.addWidget(self.paste)
        scope.addWidget(self.all)
        scope.addStretch(1)
        self.forget_btn = QPushButton("Forget my misses")
        self.forget_btn.setFlat(True)
        self.forget_btn.clicked.connect(self._forget)
        scope.addWidget(self.forget_btn)
        self.undo_btn = QPushButton("Undo")
        self.undo_btn.setFlat(True)
        self.undo_btn.clicked.connect(self._unforget)
        scope.addWidget(self.undo_btn)
        root.addLayout(scope)
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("10234  10911  11002 …")
        self.text.setTabChangesFocus(True)
        self.text.setMinimumHeight(96)
        root.addWidget(self.text)
        self.lines = _plain()
        root.addWidget(self.lines)
        self.threads_head = role(QLabel("What they have in common"), "head")
        root.addWidget(self.threads_head)
        self.thread_list = QListWidget()
        self.thread_list.itemSelectionChanged.connect(self._show)
        self.thread_list.itemDoubleClicked.connect(lambda _i: self.ops.browse(self.cids()))
        root.addWidget(self.thread_list)
        self.back = QCheckBox("")  # and bring back the ones I've seen, over 3 days
        self.back.setChecked(True)
        root.addWidget(self.back)
        self.said = _plain(muted=True)
        root.addWidget(self.said)
        buttons = QDialogButtonBox()
        self.browse_btn = QPushButton("Show in Browse")
        self.browse_btn.clicked.connect(lambda: self.ops.browse(self.cids()))
        buttons.addButton(self.browse_btn, QDialogButtonBox.ButtonRole.ActionRole)
        self.study_btn = QPushButton("Study them now")
        self.study_btn.clicked.connect(self._study)
        buttons.addButton(self.study_btn, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton("Close", QDialogButtonBox.ButtonRole.RejectRole).clicked.connect(self.reject)
        self.go = QPushButton("Do it")
        self.go.setDefault(True)
        self.go.clicked.connect(self._do)
        buttons.addButton(self.go, QDialogButtonBox.ButtonRole.AcceptRole)
        root.addWidget(buttons)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._count)
        self.text.textChanged.connect(self._pasted)
        self.deck.currentIndexChanged.connect(self._deck)
        self.bank.activated.connect(self._pick_bank)  # a pick of mine, never one the count made
        self.back.toggled.connect(lambda _on: self._show())
        self.all.toggled.connect(lambda _on: self._scope())
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

    def thread(self):
        item = self.thread_list.currentItem()
        i = item.data(ROLE) if item is not None and item.isSelected() else None
        return self.threads[i] if isinstance(i, int) and i < len(self.threads) else None

    def cids(self):
        """The picked thread's cards, else every card the questions found."""
        t = self.thread()
        return set(t["cids"]) if t else set((self.found or {}).get("cids") or ())

    def _kept_bank(self):
        """All my misses reads one bank's: the one I picked, else the one
        most of them are from."""
        did = self.deck.currentData()
        if self.picked:
            return self.picked
        names = list(Q.banks(self.idx)) if self.idx is not None else []
        return max(names, key=lambda b: (len(self.ops.kept(did, b)[0]), b == names[0]), default=None)

    def _numbers(self):
        """The text the count reads: the paste, or the kept misses of one bank."""
        if self.all.isChecked():
            nums, _pastes, _since = self.ops.kept(self.deck.currentData(), self._kept_bank())
            return " ".join(nums)
        return self.text.toPlainText()

    def _pasted(self):
        if not self.text.isReadOnly():
            self.picked = None  # a new paste: the bank its numbers say
        self._timer.start()

    def _pick_bank(self, _i):
        self.picked = self.bank.currentText() or None
        if self.all.isChecked():
            self._scope()
        else:
            self._count()

    # ---- reading ----

    def _deck(self, *_):
        did = self.deck.currentData()
        self.picked = None
        self.idx = self.ops.index(did) if did is not None else None
        self._scope_words()
        self._count()

    def _scope_words(self):
        did = self.deck.currentData()
        nums, pastes, since = self.ops.kept(did) if did is not None else ([], 0, None)
        self.all.setText(f"All my misses ({len(nums):,} question{'s' if len(nums) != 1 else ''}, "
                         f"{pastes:,} paste{'s' if pastes != 1 else ''})" if nums else "All my misses")
        self.all.setEnabled(bool(nums))
        if not nums and self.all.isChecked():
            self.paste.setChecked(True)  # toggled: _scope puts the paste back
        self.forget_btn.setVisible(self.all.isChecked() and bool(nums) and self.gone is None)
        self.undo_btn.setVisible(self.gone is not None)

    def _scope(self):
        """All my misses: the kept numbers in the box, to read; This paste: the paste back."""
        every = self.all.isChecked()
        self.text.blockSignals(True)
        if every and not self.text.isReadOnly():
            self.pasted = self.text.toPlainText()
        if every:
            self.text.setPlainText("  ".join(self.ops.kept(self.deck.currentData(), self._kept_bank())[0]))
        elif self.text.isReadOnly():
            self.text.setPlainText(self.pasted)
        self.text.setReadOnly(every)
        self.text.blockSignals(False)
        self._scope_words()
        self._count()

    def _count(self):
        if self.idx is None:
            self.found, self.t, self.threads = None, None, []
            self.lines.setText("No deck to look in.")
            self._fill_threads()
            self._show()
            return
        asked = self.picked or (self._kept_bank() if self.all.isChecked() else None)
        self.found = Q.find(self.idx, self._numbers(), asked)
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
        self.threads = Q.threads(self.idx, self.found["by"]) if self.found["by"] else []
        dates = self.ops.plan_dates(self.deck.currentData(), self.idx, self.found["cids"]) if self.found["cids"] else []
        if not Q.banks(self.idx):
            self.lines.setText(f"{self.idx.name} has no question tags (a tag whose last part is the question's number).")
        else:
            self.lines.setText("\n".join(Q.words(self.found, self.t, dates)))
        self._fill_threads()
        self._show()

    def _fill_threads(self):
        """The threads listed again, the picked one kept while it's still one."""
        was = (self.thread_list.currentItem().data(ROLE + 1)
               if self.thread_list.currentItem() is not None and self.thread_list.currentItem().isSelected() else None)
        self.thread_list.blockSignals(True)
        self.thread_list.clear()
        for i, t in enumerate(self.threads):
            item = QListWidgetItem(Q.thread_words(t))
            item.setData(ROLE, i)
            item.setData(ROLE + 1, t["path"])
            self.thread_list.addItem(item)
            if was is not None and t["path"] == was:
                self.thread_list.setCurrentItem(item)
        self.thread_list.blockSignals(False)
        on = bool(self.threads)
        self.thread_list.setVisible(on)
        self.threads_head.setVisible(on)
        if on:  # as tall as its rows, up to six
            rows = sum(self.thread_list.sizeHintForRow(i) for i in range(self.thread_list.count()))
            self.thread_list.setFixedHeight(min(rows, 6 * max(1, self.thread_list.sizeHintForRow(0))) + 2 * self.thread_list.frameWidth() + 10)

    def _show(self):
        cids = self.cids()
        t = Q.tally(self.idx, cids) if self.idx is not None and cids else (self.t or {})
        shut = int(t.get("shut") or 0)
        later = self.ops.movable(cids) if cids else 0  # the seen ones Bring back would move (actions.reviews)
        self.back.setText(f"Bring back the {later:,} you’ve seen, over the next {A.BACK_DAYS} days")
        self.back.setVisible(bool(later))
        back = bool(later) and self.back.isChecked()
        go = ([f"Open {shut:,}"] if shut else []) + ([f"bring back {later:,}"] if back else [])
        self.go.setText(", ".join(go).capitalize() if go else "Nothing to do")
        self.go.setEnabled(bool(go))
        has = bool(cids)
        one = self.thread() is not None
        self.browse_btn.setText("Show this thread in Browse" if one else "Show in Browse")
        self.study_btn.setText("Study this thread" if one else "Study them now")
        self.browse_btn.setEnabled(has)
        self.study_btn.setEnabled(has and int(t.get("open") or 0) > 0)  # Study takes the open ones
        if not self.said.text():
            self.said.setText("Counted here; nothing is sent. What you act on is kept on this computer, numbers only.")

    # ---- doing ----

    def _keep(self):
        """A paste acted on joins my misses here (All my misses already is them)."""
        if self.paste.isChecked() and self.found and self.found["found"]:
            self.ops.keep(self.deck.currentData(), self.found["bank"], self.found["found"])
            self._scope_words()

    MANY = 200  # bringing back more than this asks first: it's days of reviews

    def _do(self):
        cids = self.cids()
        if not cids:
            return
        back = self.back.isChecked() and not self.back.isHidden()
        later = self.ops.movable(cids) if back else 0
        if later > self.MANY and not confirm(
                self, f"Bring back {later:,} cards?",
                f"About {-(-later // A.BACK_DAYS):,} a day on top of your reviews for the next {A.BACK_DAYS} days. "
                "Edit › Undo takes it back.", "Bring them back"):
            return
        got = self.ops.bring_back(cids, back=back)
        if not got:
            return
        self._keep()
        bits = []
        if got["opened"]:
            bits.append(f"Opened {got['opened']:,}, first in line")
        if got["due"]:
            bits.append(f"{got['due']:,} due over the next {A.BACK_DAYS} days")
        self.said.setText((" · ".join(bits) + ". Edit › Undo takes it back.") if bits else "Nothing needed doing.")
        self._deck()  # the deck read again: what's open now (the picked thread kept)

    def _study(self):
        t = self.thread()
        name = f"Missed · {t['label']}" if t else "Missed questions"
        if self.idx is not None and self.ops.study_cards(self.idx, self.cids(), name):
            self._keep()
            self.accept()

    def _forget(self):
        self.gone = self.ops.forget(self.deck.currentData())
        self.paste.setChecked(True)
        self.said.setText("Your misses for this deck are forgotten here.")
        self._scope()

    def _unforget(self):
        self.ops.unforget(self.gone)
        self.gone = None
        self.said.setText("Back.")
        self._scope()
