"""Shared decks dialog: pick which local decks to share with your crew.

Counts come from ONE grouped pass over the cards table, so opening is fast
even on huge collections. Fingerprints (for the "matches Dre" labels) are
computed incrementally on timer ticks after the dialog shows — collection
access stays on the main thread, but never in one long freeze.
"""

from aqt import mw
from aqt.qt import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QTimer, QVBoxLayout, QWidget, Qt,
)

from . import attach_alive
from ..stats.decks import all_deck_counts, deck_signature, sig_match, subtree_counts


class DecksDialog(QDialog):
    def __init__(self, parent, config, crew_entries, on_saved):
        super().__init__(parent)
        self.config = dict(config)
        self.crew = [e for e in crew_entries if not e.get("you")]
        self.on_saved = on_saved
        self.rows = []  # [(deck_id, QCheckBox, QLabel)]
        attach_alive(self)
        self._build()
        QTimer.singleShot(0, self._next_match)

    def _crew_matches(self, sig):
        names = []
        for e in self.crew:
            for d in e.get("decks") or []:
                if sig_match(sig, d.get("sig")):
                    names.append(e["name"])
                    break
        return names

    def _build(self):
        self.setWindowTitle("Due Crew — Shared decks")
        self.setMinimumWidth(460)
        self.setMinimumHeight(380)
        root = QVBoxLayout(self)

        intro = QLabel("Share a deck and its progress shows on the Decks tab. "
                       "Decks you and your crew both study match automatically.")
        intro.setWordWrap(True)
        intro.setStyleSheet("font-size: 12px;")
        root.addWidget(intro)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        lay = QVBoxLayout(inner)

        shared = set(int(d) for d in self.config.get("shared_decks") or [])
        col = mw.col
        table = all_deck_counts(col)
        for row in col.decks.all_names_and_ids():
            deck = col.decks.get(int(row.id), default=False)
            if not deck or deck.get("dyn"):
                continue  # skip filtered decks
            total, _seen, _mature = subtree_counts(col, row.id, table)
            if not total:
                continue
            line = QHBoxLayout()
            box = QCheckBox(f"{row.name}  ({total:,} cards)")
            box.setChecked(int(row.id) in shared)
            line.addWidget(box)
            match = QLabel("checking…")
            # friend names land here and QLabel auto-detects rich text
            match.setTextFormat(Qt.TextFormat.PlainText)
            match.setStyleSheet("font-size: 11px;")
            line.addWidget(match)
            line.addStretch()
            lay.addLayout(line)
            self.rows.append((int(row.id), box, match))

        if not self.rows:
            lay.addWidget(QLabel("No decks with cards yet."))
        lay.addStretch()
        scroll.setWidget(inner)
        root.addWidget(scroll)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        save = QPushButton("Save")
        save.setDefault(True)
        save.clicked.connect(self._save)
        buttons.addWidget(save)
        root.addLayout(buttons)

        self._match_index = 0

    def _next_match(self):
        """One fingerprint per tick keeps the UI responsive on big collections."""
        if not self._alive or not mw.col or self._match_index >= len(self.rows):
            return
        did, _box, label = self.rows[self._match_index]
        self._match_index += 1
        try:
            names = self._crew_matches(deck_signature(mw.col, did))
            label.setText("matches " + ", ".join(names) if names
                          else "no matches in your crew yet")
        except Exception:
            label.setText("")
        QTimer.singleShot(0, self._next_match)

    def _save(self):
        self.on_saved({"shared_decks": [did for did, box, _ in self.rows
                                        if box.isChecked()]})
        self.accept()
