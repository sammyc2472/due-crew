"""Labs, Question IDs (docs/planner.md): after a practice block, paste the
IDs of the questions you missed, any way the bank copies them. Due Crew
picks out the numbers, finds their cards by the deck's question tags, and
says what it found (and what isn't a question here), and what they have in
common: the threads, by the deck's own system and resource tags. Do it
opens the shut ones and, asked, brings the ones you've seen back over the
next 3 days, one undo step; Study them now is a deck of them (or of one
thread). What you act on is kept on this computer, numbers only, so All my
misses shows the threads across every block. Nothing is sent."""

from aqt.qt import (
    QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPlainTextEdit, QPushButton, QRadioButton, Qt, QTimer, QVBoxLayout,
)

from ..ui import attach_alive, heading, note, role
from . import actions as A
from . import qids as Q

ROLE = Qt.ItemDataRole.UserRole


def _plain(text="", muted=False):
    w = QLabel(str(text))
    w.setTextFormat(Qt.TextFormat.PlainText)
    w.setWordWrap(True)
    return note(w) if muted else w


class QidWindow(QDialog):
    """choices: [(deck id, name)]; ops: flow.QidOps, or a render's own."""

    def __init__(self, parent, col, choices, ops):
        super().__init__(parent)
        self.col, self.ops, self.choices = col, ops, list(choices)
        self.idx = self.found = self.t = None
        self.gone = None  # what Forget took out, while its Undo shows
        self.pasted = ""  # the paste, while All my misses shows the kept ones in its place
        self.threads = []
        attach_alive(self)
        self.setWindowTitle("Question IDs")
        self.setModal(False)
        self.setMinimumWidth(560)
        root = QVBoxLayout(self)
        heading(self, root, "Paste the question IDs you missed")
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
        self.both = QRadioButton("")
        self.just = QRadioButton("")
        self.both.setChecked(True)
        how = QButtonGroup(self)
        how.addButton(self.both)
        how.addButton(self.just)
        root.addWidget(self.both)
        root.addWidget(self.just)
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
        self.text.textChanged.connect(self._timer.start)
        self.deck.currentIndexChanged.connect(self._deck)
        self.bank.currentIndexChanged.connect(lambda _i: self._count())
        self.both.toggled.connect(lambda _on: self._show())
        self.all.toggled.connect(lambda _on: self._scope())
        start = self.ops.default_deck(self.choices)
        at = next((i for i, (d, _n) in enumerate(self.choices) if d == start), 0)
        if self.choices:
            self.deck.setCurrentIndex(at)
        self._deck()

    # ---- what it acts on ----

    def thread(self):
        item = self.thread_list.currentItem()
        i = item.data(ROLE) if item is not None and item.isSelected() else None
        return self.threads[i] if isinstance(i, int) and i < len(self.threads) else None

    def cids(self):
        """The picked thread's cards, else every card the questions found."""
        t = self.thread()
        return set(t["cids"]) if t else set((self.found or {}).get("cids") or ())

    def _numbers(self):
        """The text the count reads: the paste, or every kept miss."""
        if self.all.isChecked():
            nums, _pastes, _since = self.ops.kept(self.deck.currentData())
            return " ".join(nums)
        return self.text.toPlainText()

    # ---- reading ----

    def _deck(self, *_):
        did = self.deck.currentData()
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
            self.text.setPlainText("  ".join(self.ops.kept(self.deck.currentData())[0]))
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
        asked = self.bank.currentText() if self.bank.count() > 1 else None
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
        t = Q.tally(self.idx, self.cids()) if self.idx is not None and self.cids() else (self.t or {})
        shut, review = int(t.get("shut") or 0), int(t.get("review") or 0)
        days = A.BACK_DAYS
        self.both.setText(f"Open the {shut:,} shut, and bring the {review:,} you’ve seen back over {days} days"
                          if shut else f"Bring the {review:,} you’ve seen back over {days} days")
        self.just.setText(f"Just open the {shut:,} shut" if shut else "Nothing to open")
        has = bool(self.cids())
        self.both.setEnabled(has and bool(shut or review))
        self.just.setEnabled(has and bool(shut))
        if not self.just.isEnabled() and self.just.isChecked():
            self.both.setChecked(True)
        self.go.setEnabled(has and bool(shut or (review and self.both.isChecked())))
        one = self.thread() is not None
        self.browse_btn.setText("Show this thread in Browse" if one else "Show in Browse")
        self.study_btn.setText("Study this thread" if one else "Study them now")
        self.browse_btn.setEnabled(has)
        self.study_btn.setEnabled(has and int(t.get("open") or 0) + shut > 0)
        if not self.said.text():
            self.said.setText("Counted here; nothing is sent. What you act on is kept on this computer, numbers only.")

    # ---- doing ----

    def _keep(self):
        """A paste acted on joins my misses here (All my misses already is them)."""
        if self.paste.isChecked() and self.found and self.found["found"]:
            self.ops.keep(self.deck.currentData(), self.found["bank"], self.found["found"])
            self._scope_words()

    def _do(self):
        cids = self.cids()
        if not cids:
            return
        got = self.ops.bring_back(cids, back=self.both.isChecked())
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
