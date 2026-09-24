"""Shared decks dialog: pick which local decks to share with your crew.

A collapsed tree with a filter (2.9). Until then every deck and subdeck was
a checkbox in one long list, and a deep tree made a long one. Counts come
from ONE grouped pass over the cards table. Match labels ("matches igk")
come from local_matches: one query over the crew's fingerprint guids finds
the few decks that could pair, and only those are fingerprinted. Until 2.9
every deck was, one per timer tick. Collection access stays on the main
thread.
"""

from aqt import mw
from aqt.qt import (
    QDialog, QDialogButtonBox, QLabel, QLineEdit, QTimer, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, Qt,
)

from . import attach_alive
from ..stats.decks import all_deck_counts, local_matches, subtree_counts

DID = Qt.ItemDataRole.UserRole


class DecksDialog(QDialog):
    def __init__(self, parent, config, crew_entries, on_saved):
        super().__init__(parent)
        self.config = dict(config)
        self.crew = [e for e in crew_entries if not e.get("you")]
        self.on_saved = on_saved
        self.items = {}   # did -> QTreeWidgetItem
        self.names = {}   # did -> full deck name
        attach_alive(self)
        self._build()
        QTimer.singleShot(0, self._match)

    def _build(self):
        self.setWindowTitle("Shared Decks")
        self.setMinimumWidth(480)
        self.setMinimumHeight(400)
        root = QVBoxLayout(self)

        intro = QLabel("Share a deck and its progress shows on the Decks tab. Decks "
                       "you and your crew both study match automatically. A subdeck "
                       "can be shared on its own.")
        intro.setWordWrap(True)
        intro.setStyleSheet("font-size: 12px;")
        root.addWidget(intro)

        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter decks")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._filter)
        root.addWidget(self.filter)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Deck", "Cards", ""])
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        header = self.tree.header()
        header.setStretchLastSection(True)
        root.addWidget(self.tree)

        shared = set(int(d) for d in self.config.get("shared_decks") or [])
        col = mw.col
        table = all_deck_counts(col)
        rows = sorted(col.decks.all_names_and_ids(), key=lambda r: r.name.lower())
        by_name = {}  # full name -> item, for parents
        for row in rows:
            did = int(row.id)
            deck = col.decks.get(did, default=False)
            if not deck or deck.get("dyn"):
                continue  # skip filtered decks
            total, _seen, _mature = subtree_counts(col, did, table)
            if not total:
                continue
            self.names[did] = row.name
            parent_name = row.name.rsplit("::", 1)[0] if "::" in row.name else ""
            parent = by_name.get(parent_name) if parent_name else None
            # under its parent it goes by its own name; with no parent here, by the path
            label = row.name.split("::")[-1] if parent is not None else row.name
            item = QTreeWidgetItem([label, f"{total:,}", ""])
            item.setData(0, DID, did)
            item.setToolTip(0, row.name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked if did in shared
                               else Qt.CheckState.Unchecked)
            item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if parent is not None:
                parent.addChild(item)
            else:
                self.tree.addTopLevelItem(item)
            self.items[did] = item
            by_name[row.name] = item
        for did in shared:
            self._reveal(self.items.get(did))  # what you share is in view
        self.tree.resizeColumnToContents(0)
        self.tree.resizeColumnToContents(1)

        if not self.items:
            root.addWidget(QLabel("No decks with cards yet."))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @staticmethod
    def _reveal(item):
        while item is not None and item.parent() is not None:
            item.parent().setExpanded(True)
            item = item.parent()

    def _match(self):
        if not self._alive or not mw.col or not self.crew:
            return
        try:
            found = local_matches(mw.col, self.crew, self.names)
        except Exception:
            return
        for did, who in found.items():
            item = self.items.get(did)
            if item is not None:
                item.setText(2, "matches " + ", ".join(who))
                self._reveal(item)

    def _filter(self, text):
        needle = text.strip().lower()
        for did, item in self.items.items():
            item.setHidden(bool(needle))
        if not needle:
            return
        for did, item in self.items.items():
            if needle in self.names[did].lower():
                item.setHidden(False)
                parent = item.parent()
                while parent is not None:
                    parent.setHidden(False)
                    parent.setExpanded(True)
                    parent = parent.parent()

    def _save(self):
        self.on_saved({"shared_decks": [did for did, item in self.items.items()
                                        if item.checkState(0) == Qt.CheckState.Checked]})
        self.accept()
