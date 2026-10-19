"""Labs, the picker (docs/planner.md): a deck's tags as the deck files them,
a tree read a level at a time (#-parts first, then ^, then the rest; a
bank's questions counted, not listed), with what each holds in this copy,
and a search over every tag's path; then its subdecks. Ticked ones go onto
a date, everything under each with it. Read on the main thread from the
DeckIndex; nothing is sent."""

from aqt.qt import (
    QDialog, QDialogButtonBox, QHeaderView, QLabel, QLineEdit, QPushButton, Qt, QTimer,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

from ..ui import attach_alive, esc, heading, note
from . import model as M

ROLE = Qt.ItemDataRole.UserRole
SHOWN = 200  # a search lists this many at most


def _plain(text="", muted=False):
    w = QLabel(str(text))
    w.setTextFormat(Qt.TextFormat.PlainText)
    w.setWordWrap(True)
    return note(w) if muted else w


class Picker(QDialog):
    def __init__(self, parent, idx, title, plan_deck=""):
        super().__init__(parent)
        self.idx, self.plan_deck = idx, plan_deck
        self.ticked = {}  # ("tag" | "deck", path) -> cards
        attach_alive(self)
        self.setWindowTitle(title)
        self.setMinimumSize(560, 520)
        root = QVBoxLayout(self)
        heading(self, root)
        root.addWidget(_plain(f"Counted in your {idx.name}. Tick a tag: everything under it comes with it.", muted=True))
        self.find = QLineEdit()
        self.find.setPlaceholderText("Find a tag: heart failure")
        self.find.setClearButtonEnabled(True)
        root.addWidget(self.find)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Tag", "Cards", "New"])
        h = self.tree.header()
        h.setStretchLastSection(False)
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.itemExpanded.connect(self._expand)
        self.tree.itemChanged.connect(self._tick)
        root.addWidget(self.tree, 1)
        self.hint = _plain(muted=True)
        root.addWidget(self.hint)
        self.said = _plain(muted=True)
        root.addWidget(self.said)
        buttons = QDialogButtonBox()
        buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole).clicked.connect(self.reject)
        self.go = QPushButton("Add")
        self.go.setDefault(True)
        self.go.clicked.connect(self.accept)
        buttons.addButton(self.go, QDialogButtonBox.ButtonRole.AcceptRole)
        root.addWidget(buttons)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._fill)
        self.find.textChanged.connect(lambda _t: self._timer.start())
        self._fill()

    # ---- rows ----

    def _row(self, kind, path, name, more=False):
        cards, new = M.tag_count(self.idx, path) if kind == "tag" else self._deck_count(path)
        item = QTreeWidgetItem([name, f"{cards:,}", f"{new:,}"])
        item.setData(0, ROLE, (kind, path, cards))
        item.setToolTip(0, esc(path))
        for i in (1, 2):
            item.setTextAlignment(i, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(0, Qt.CheckState.Checked if (kind, path) in self.ticked else Qt.CheckState.Unchecked)
        if more:
            item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
        return item

    def _deck_count(self, path):
        c = M.counts(self.idx, self.idx.deck_cards(path, self.idx.name))
        return c["cards"], c["new"]

    def _fill(self):
        self.tree.blockSignals(True)
        self.tree.clear()
        text = self.find.text().strip()
        if text:
            hits = M.find(self.idx, text, SHOWN)
            for path in hits:
                self.tree.addTopLevelItem(self._row("tag", path, M.label(path)))
            self.hint.setText(f"The first {SHOWN}: say more to narrow it." if len(hits) >= SHOWN
                              else "" if hits else "No tag here has those words.")
        else:
            self.hint.setText("")
            for path, name, more in M.children(self.idx, ""):
                self.tree.addTopLevelItem(self._row("tag", path, name, more))
            decks = sorted((self.idx.spelled[r] for r in self.idx.rel if r), key=str.lower)
            if decks:
                head = QTreeWidgetItem(["Subdecks", "", ""])
                head.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.tree.addTopLevelItem(head)
                for rel in decks:
                    head.addChild(self._row("deck", f"{self.idx.name}::{rel}", rel.replace("::", " › ")))
        self.hint.setVisible(bool(self.hint.text()))
        self.tree.blockSignals(False)
        self._said()

    def _expand(self, item):
        if item.childCount() or not item.data(0, ROLE):
            return
        kind, path, _n = item.data(0, ROLE)
        if kind != "tag":
            return
        self.tree.blockSignals(True)
        for p, name, more in M.children(self.idx, path):
            item.addChild(self._row("tag", p, name, more))
        q = M.questions(self.idx, path)
        if q:
            extra = QTreeWidgetItem([f"{q:,} question ID{'s' if q != 1 else ''}: Question IDs finds them by number", "", ""])
            extra.setFlags(Qt.ItemFlag.ItemIsEnabled)
            item.addChild(extra)
        if not item.childCount():
            item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicator)
        self.tree.blockSignals(False)

    def _tick(self, item, col):
        data = item.data(0, ROLE)
        if col != 0 or not data:
            return
        kind, path, cards = data
        if item.checkState(0) == Qt.CheckState.Checked:
            self.ticked[(kind, path)] = cards
        else:
            self.ticked.pop((kind, path), None)
        self._said()

    def _said(self):
        """"2 ticked · 140 cards", or that nothing is."""
        n = len(self.ticked)
        self.go.setEnabled(bool(n))
        if not n:
            self.said.setText("Nothing ticked yet.")
            return
        cards = sum(self.ticked.values())
        self.said.setText(f"{n:,} ticked · {cards:,} card{'s' if cards != 1 else ''}"
                          + (" (a card under two of them counts twice here)" if n > 1 else ""))

    def value(self):
        """(tags, decks) ticked, in the order ticked."""
        tags = [p for (k, p) in self.ticked if k == "tag"]
        decks = [p for (k, p) in self.ticked if k == "deck"]
        return tags, decks


def pick_sources(parent, idx, title, plan_deck=""):
    """(tags, decks) ticked, or None when cancelled or nothing was."""
    dlg = Picker(parent, idx, title, plan_deck)
    if not dlg.exec():
        return None
    tags, decks = dlg.value()
    return (tags, decks) if tags or decks else None
