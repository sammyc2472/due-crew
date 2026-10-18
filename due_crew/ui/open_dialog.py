"""3.8.0, Browse › Due Crew: open its cards… (a tag in the sidebar, its
children too) or open these… (the picked cards): what opens, counted first.
Never suspends anything; a leech stays suspended, and the sheet says so.
First in Anki's line of new cards, ticked; Open and study opens them and
starts a Due Crew deck of the new ones. One undo step. Local: no request."""

from aqt.qt import QCheckBox, QDialog, QDialogButtonBox, QLabel, QPushButton, Qt, QVBoxLayout

from . import attach_alive, tone


class OpenDialog(QDialog):
    """counts: P.open_counts; where: a line under the title (a tag's path, the
    deck), plain text; plans: lines about plans I follow that hold them.
    on_open(first, study) runs when asked."""

    def __init__(self, parent, title, where, counts, plans=(), on_open=None):
        super().__init__(parent)
        attach_alive(self)
        self.on_open = on_open
        n, already, lee = int(counts.get("open") or 0), int(counts.get("already") or 0), int(counts.get("leech") or 0)
        self.setWindowTitle("Open cards")
        self.setMinimumWidth(400)
        root = QVBoxLayout(self)
        what = title or "the picked cards"
        head = QLabel((f"Open {n:,} card{'s' if n != 1 else ''} of {what}" if title else f"Open {n:,} of the picked cards")
                      if n else f"Nothing in {what} to open")
        head.setTextFormat(Qt.TextFormat.PlainText)
        head.setWordWrap(True)
        head.setStyleSheet("font-weight: 600;")
        root.addWidget(head)
        if where:
            w = QLabel(where)
            w.setTextFormat(Qt.TextFormat.PlainText)
            w.setWordWrap(True)
            w.setStyleSheet(f"color: {tone('muted')}; font-size: 11.5px;")
            root.addWidget(w)
        facts = []
        if already:
            facts.append(f"{already:,} {'is' if already == 1 else 'are'} open already")
        if lee:
            facts.append(f"{lee:,} {'is a leech' if lee == 1 else 'are leeches'} and stay{'s' if lee == 1 else ''} suspended")
        facts += list(plans)
        self.facts = QLabel("\n".join(f"• {x}" for x in facts))
        self.facts.setTextFormat(Qt.TextFormat.PlainText)  # plan and date names are their authors'
        self.facts.setWordWrap(True)
        self.facts.setVisible(bool(facts))
        root.addWidget(self.facts)
        self.first = QCheckBox("First in Anki's line of new cards")
        self.first.setChecked(True)
        self.first.setToolTip("Anki shows new cards in its own order; these go to the front, so they come next.")
        self.first.setVisible(bool(n))
        root.addWidget(self.first)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.study_btn = QPushButton("Open and study")
        self.study_btn.clicked.connect(lambda: self._go(study=True))
        self.open_btn = QPushButton(f"Open {n:,}")
        self.open_btn.setDefault(True)
        self.open_btn.clicked.connect(lambda: self._go(study=False))
        for b in (self.study_btn, self.open_btn):
            b.setVisible(bool(n))
            buttons.addButton(b, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _go(self, study):
        if self.on_open:
            self.on_open(self.first.isChecked(), study)
        self.accept()
