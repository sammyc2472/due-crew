"""Follow a plan (3.1, mocks 2.2 and 2.3): a code (or a pasted link), a
look at the plan, the deck to run it on, how much of it this copy has,
what to do about units that have already opened, and whether the crew
sees my progress. The tag-swap question comes up once per deck, when my
tags start differently.

Decks are read on the main thread; the peek and the follow are one
request each, in the background. Every plan and unit name is the
author's: escaped wherever it's rich text."""

from aqt.qt import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QGridLayout, QLineEdit, QPushButton, QRadioButton, QVBoxLayout, QWidget, Qt,
)

from . import attach_alive, esc, run_bg, warn
from .. import plans as P

SHOWN_UNITS = 5


def late_counts(idx, doc, today, swap=None):
    """(units opened by date, cards they hold here)."""
    opened = P.opened_by_date(doc, today)
    cids = set()
    for u in opened:
        cids |= idx.match(u, swap, doc.get("deck", ""))
    return len(opened), len(cids)


def late_label(n_units, n_cards, while_paused=False):
    if while_paused:
        return f"{n_units} date{'s' if n_units != 1 else ''} opened while paused ({n_cards:,} cards)"
    return (f"{n_units} date{'s have' if n_units != 1 else ' has'} already opened "
            f"({n_cards:,} cards)")


class SwapDialog(QDialog):
    """Mock 2.3: "Your tags start differently"."""

    def __init__(self, parent, swap, matched):
        super().__init__(parent)
        theirs, mine = swap
        self.setWindowTitle("Your tags start differently")
        self.setMinimumWidth(400)
        root = QVBoxLayout(self)
        head = QLabel("<b>Your tags start differently</b>")
        root.addWidget(head)
        text = QLabel(f"The plan uses <code>{esc(theirs)}::</code>. Your copy uses "
                      f"<code>{esc(mine)}::</code>. With that swap, {matched:,} cards match.")
        text.setWordWrap(True)
        root.addWidget(text)
        buttons = QDialogButtonBox()
        no = buttons.addButton("No", QDialogButtonBox.ButtonRole.RejectRole)
        yes = buttons.addButton(f"Use {mine}::", QDialogButtonBox.ButtonRole.AcceptRole)
        yes.setDefault(True)
        no.clicked.connect(self.reject)
        yes.clicked.connect(self.accept)
        root.addWidget(buttons)


def ask_swap(parent, swap, matched):
    return bool(SwapDialog(parent, swap, matched).exec())


class CatchUpDialog(QDialog):
    """Resuming a paused plan asks what following asks: open what opened
    meanwhile, or start from the next unit."""

    def __init__(self, parent, n_units, n_cards, nxt):
        super().__init__(parent)
        self.choice = None
        self.setWindowTitle("Resume")
        self.setMinimumWidth(400)
        root = QVBoxLayout(self)
        root.addWidget(QLabel(late_label(n_units, n_cards, while_paused=True)))
        self.now = QRadioButton("Open them now")
        self.now.setChecked(True)
        self.next = QRadioButton(f"Start from the next date, {P.fmt_day(nxt['opens'])}" if nxt
                                 else "Start from the next date")
        self.next.setEnabled(bool(nxt))
        group = QButtonGroup(self)
        group.addButton(self.now)
        group.addButton(self.next)
        root.addWidget(self.now)
        root.addWidget(self.next)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._ok)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _ok(self):
        self.choice = "skip" if self.next.isChecked() else "open"
        self.accept()


def ask_catch_up(parent, n_units, n_cards, nxt):
    dlg = CatchUpDialog(parent, n_units, n_cards, nxt)
    return dlg.choice if dlg.exec() else None


class FollowDialog(QDialog):
    def __init__(self, parent, client, col, code="", today="", on_followed=None, swap_prompt=None):
        super().__init__(parent)
        self.client, self.col, self.today = client, col, today
        self.on_followed = on_followed      # main thread: (plan, deck_id, swap, "open" | "skip", hold)
        self.swap_prompt = swap_prompt or (lambda sw, n: ask_swap(self, sw, n))
        self.plan = None
        self.choices = P.deck_choices(col)
        self.best = None
        self.swaps = {}      # did -> the swap asked about, and the answer
        self.indexes = {}
        attach_alive(self)
        self.setWindowTitle("Follow a plan")
        self.setMinimumWidth(480)
        root = QVBoxLayout(self)

        row = QHBoxLayout()
        row.addWidget(QLabel("Plan code"))
        self.code_edit = QLineEdit()
        self.code_edit.setPlaceholderText("Code, or paste the link")
        self.code_edit.returnPressed.connect(self._look_up)
        self.code_edit.textChanged.connect(lambda *_: self._clear())
        self.look_btn = QPushButton("Look Up")
        self.look_btn.clicked.connect(self._look_up)
        row.addWidget(self.code_edit)
        row.addWidget(self.look_btn)
        root.addLayout(row)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        self.title = QLabel("")
        self.title.setStyleSheet("font-size: 14px; font-weight: 700;")
        root.addWidget(self.title)
        drow = QHBoxLayout()
        self.deck_label = QLabel("Run it on")
        drow.addWidget(self.deck_label)
        self.deck = QComboBox()
        for did, name in self.choices:
            self.deck.addItem(name, did)
        self.deck.currentIndexChanged.connect(self._deck_changed)
        drow.addWidget(self.deck, 1)
        self.best_hint = QLabel("best match of your decks")
        self.best_hint.setStyleSheet("font-size: 11px; color: palette(mid);")
        drow.addWidget(self.best_hint)
        root.addLayout(drow)
        self.match = QWidget()
        self.match_grid = QGridLayout(self.match)
        self.match_grid.setContentsMargins(0, 4, 0, 4)
        self.match_grid.setVerticalSpacing(4)
        self.match_grid.setColumnStretch(0, 1)
        root.addWidget(self.match)
        self.found = QLabel("")
        self.found.setWordWrap(True)
        root.addWidget(self.found)

        self.late_label = QLabel("")
        root.addWidget(self.late_label)
        lrow = QHBoxLayout()
        self.late_open = QRadioButton("Open them now")
        self.late_open.setChecked(True)
        self.late_skip = QRadioButton("Start from the next date")
        group = QButtonGroup(self)
        group.addButton(self.late_open)
        group.addButton(self.late_skip)
        lrow.addWidget(self.late_open)
        lrow.addWidget(self.late_skip)
        lrow.addStretch()
        root.addLayout(lrow)
        # 3.3: cards that are already active can't wait for their day unless held back
        self.hold = QCheckBox("")
        self.hold.setChecked(True)
        self.hold.setVisible(False)
        root.addWidget(self.hold)
        self.share = QCheckBox("Share my progress with the crew")
        self.share.setChecked(True)
        root.addWidget(self.share)
        self.about = QLabel("Each morning, that day's cards open.")
        self.about.setWordWrap(True)
        self.about.setStyleSheet("font-size: 12px;")
        root.addWidget(self.about)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                        | QDialogButtonBox.StandardButton.Cancel)
        self.follow_btn = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.follow_btn.setText("Follow")
        self.buttons.accepted.connect(self._follow)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)
        self._clear()
        if code:
            self.code_edit.setText(code)
            self._look_up()

    # ---- look up ----

    def _plan_parts(self):
        return (self.title, self.deck_label, self.deck, self.best_hint, self.match, self.found,
                self.late_label, self.late_open, self.late_skip, self.share, self.about)

    def _clear(self):
        self.plan = None
        self.status.setText("")
        for w in self._plan_parts():
            w.setVisible(False)
        self.follow_btn.setEnabled(False)
        self.adjustSize()

    def _look_up(self):
        code = P.code_from(self.code_edit.text())
        if len(code) != P.PLAN_CODE_LEN:
            self.status.setText(f"Plan codes are {P.PLAN_CODE_LEN} letters and numbers.")
            return
        self.look_btn.setEnabled(False)
        self.status.setText("Looking up…")
        cl = self.client
        self._code = code

        def done(result, err):
            self.look_btn.setEnabled(True)
            plan, status = result if result else (None, 0)
            if plan is None:
                self.status.setText("No plan with that code." if status == 404
                                    else "Couldn't look it up. Check your connection.")
                return
            self._peeked(plan)

        run_bg(self, lambda: cl.peek_plan(code), done)

    def _peeked(self, plan):
        self.plan = plan
        self.status.setText("You follow this plan. Following again keeps your progress."
                            if plan.get("following") else "")
        self.title.setText(P.plan_title(plan))  # a plain-text label
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        for w in self._plan_parts():
            w.setVisible(True)
        self.best, swap = P.best_deck(self.col, plan["doc"], self.choices)
        if self.best is not None:
            if swap:
                self.swaps[self.best] = swap  # asked about in _deck_changed
            at = self.deck.findData(self.best)
            self.deck.blockSignals(True)
            self.deck.setCurrentIndex(max(0, at))
            self.deck.blockSignals(False)
        self._deck_changed()

    def _index(self, did):
        if did not in self.indexes:
            self.indexes[did] = P.DeckIndex(self.col, did)
        return self.indexes[did]

    def _swap_for(self, did, idx):
        """The swap for this deck, asked about once."""
        if did in self.swaps and isinstance(self.swaps[did], dict):
            return self.swaps[did]["use"]
        swap = self.swaps.get(did) or P.detect_swap(idx, self.plan["doc"])
        if not swap:
            self.swaps[did] = {"use": None}
            return None
        yes = self.swap_prompt(swap, P.found_total(idx, self.plan["doc"], swap))
        self.swaps[did] = {"use": swap if yes else None}
        return self.swaps[did]["use"]

    def _rows(self, rows):
        """The match list: plain-text labels (names are the author's)."""
        while self.match_grid.count():
            w = self.match_grid.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        for i, (label, text, missing) in enumerate(rows):
            left = QLabel(label)
            left.setTextFormat(Qt.TextFormat.PlainText)
            right = QLabel(text)
            right.setTextFormat(Qt.TextFormat.PlainText)
            right.setAlignment(Qt.AlignmentFlag.AlignRight)
            right.setStyleSheet("font-weight: 700;" + (f" color: {warn()};" if missing else ""))
            self.match_grid.addWidget(left, i, 0)
            self.match_grid.addWidget(right, i, 1)
        self.adjustSize()

    def _deck_changed(self, *_):
        if not self.plan:
            return
        did = self.deck.currentData()
        self.best_hint.setVisible(did is not None and did == self.best)
        if did is None:
            self._rows([("You have no decks yet.", "", False)])
            self.follow_btn.setEnabled(False)
            return
        idx = self._index(did)
        doc = self.plan["doc"]
        swap = self._swap_for(did, idx)
        self._rows(P.match_rows(idx, doc, swap, SHOWN_UNITS))
        total = P.found_total(idx, doc, swap)
        us = P.units(doc)
        counted = all(isinstance(u.get("n"), int) or not (u.get("tags") or u.get("decks")) for u in us)
        if counted and us:
            # the author's counts (tags and subdecks) plus the picked single cards
            picked = sum((u.get("n") or 0) + len(u.get("cards") or []) for u in us)
            self.found.setText(f"<b>{total:,} of {picked:,}</b> cards found in your copy. "
                               "Missing ones are skipped.")
        else:
            self.found.setText(f"<b>{total:,}</b> cards found in your copy. Missing ones are skipped.")
        n_units, n_cards = late_counts(idx, doc, self.today, swap)
        late = n_units > 0 and not self.plan.get("following")
        for w in (self.late_label, self.late_open, self.late_skip):
            w.setVisible(late)
        if late:
            self.late_label.setText(late_label(n_units, n_cards))
            nxt = P.next_unit(doc, self.today)
            self.late_skip.setText(f"Start from the next date, {P.fmt_day(nxt['opens'])}" if nxt
                                   else "Start from the next date")
            self.late_skip.setEnabled(bool(nxt))
            if not nxt:
                self.late_open.setChecked(True)
        held = len(P.holdable(idx, doc, self.today, swap)) if not self.plan.get("following") else 0
        self.hold.setVisible(held > 0)
        if held:
            self.hold.setText(f"Hold back {held:,} card{'s' if held != 1 else ''} of later dates until their day")
        self.follow_btn.setEnabled(bool(total) or not P.units(doc))
        if not total and P.units(doc):
            self.found.setText("None of this plan's cards are in this deck. Pick another.")

    # ---- follow ----

    def _follow(self):
        plan = self.plan
        did = self.deck.currentData()
        if not plan or did is None:
            return
        swap = (self.swaps.get(did) or {}).get("use") if isinstance(self.swaps.get(did), dict) else None
        late = "skip" if (self.late_skip.isVisible() and self.late_skip.isChecked()) else "open"
        hold = self.hold.isVisible() and self.hold.isChecked()
        share = self.share.isChecked()
        code = self._code
        self.follow_btn.setEnabled(False)
        self.status.setText("Following…")
        cl = self.client

        def done(result, err):
            got, status = result if result else (None, 0)
            if got is None:
                self.follow_btn.setEnabled(True)
                self.status.setText("That plan is for a squad you're not in." if status == 404
                                    else "Couldn't follow. Check your connection.")
                return
            got = dict(got, share=share, paused=False, following=True)
            if self.on_followed:
                self.on_followed(got, did, swap, late, hold)
            self.accept()

        run_bg(self, lambda: cl.follow_plan(code, share), done)
