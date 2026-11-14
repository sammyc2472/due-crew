"""3.8.0, Browse › Due Crew: open its cards… (a tag in the sidebar, its
children too) or open these… (the picked cards): what opens, counted first.
Never suspends anything; a leech stays suspended, and the sheet says so.
First in Anki's line of new cards, ticked; Open and study opens them and
starts a Due Crew deck of the new ones. One undo step. Local: no request."""

from aqt.qt import QCheckBox, QDialog, QDialogButtonBox, QLabel, QPushButton, Qt, QVBoxLayout

from . import attach_alive, heading, note
from ..words import later as _later, t as _t


class OpenDialog(QDialog):
    """counts: P.open_counts; where: a line under the title (a tag's path, the
    deck), plain text; plans: lines about plans I follow that hold them.
    on_open(first, study) runs when asked."""

    def __init__(self, parent, title, where, counts, plans=(), on_open=None):
        super().__init__(parent)
        attach_alive(self)
        self.on_open = on_open
        n, already, lee = int(counts.get("open") or 0), int(counts.get("already") or 0), int(counts.get("leech") or 0)
        self.setWindowTitle(_t("Open cards"))
        self.setMinimumWidth(400)
        root = QVBoxLayout(self)
        heading(self, root, (_t(_later("Open {n} card of {what}") if n == 1 else _later("Open {n} cards of {what}"), n=f"{n:,}", what=title)
                             if title else _t("Open {n} of the picked cards", n=f"{n:,}"))
                if n else _t("Nothing in {what} to open", what=title) if title else _t("Nothing in the picked cards to open"))
        if where:
            w = QLabel(where)
            w.setTextFormat(Qt.TextFormat.PlainText)
            root.addWidget(note(w))
        facts = []
        if already:
            facts.append(_t(_later("{n} is open already") if already == 1 else _later("{n} are open already"), n=f"{already:,}"))
        if lee:
            facts.append(_t(_later("{n} is a leech and stays suspended") if lee == 1 else _later("{n} are leeches and stay suspended"), n=f"{lee:,}"))
        facts += list(plans)
        self.facts = QLabel("\n".join(f"• {x}" for x in facts))
        self.facts.setTextFormat(Qt.TextFormat.PlainText)  # plan and date names are their authors'
        self.facts.setWordWrap(True)
        self.facts.setVisible(bool(facts))
        root.addWidget(self.facts)
        self.first = QCheckBox(_t("First in Anki's line of new cards"))
        self.first.setChecked(True)
        self.first.setToolTip(_t("Anki shows new cards in its own order; these go to the front, so they come next."))
        self.first.setVisible(bool(n))
        root.addWidget(self.first)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.study_btn = QPushButton(_t("Open and study"))
        self.study_btn.clicked.connect(lambda: self._go(study=True))
        self.open_btn = QPushButton(_t("Open {n}", n=f"{n:,}"))
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
