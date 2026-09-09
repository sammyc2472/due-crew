"""Cheer picker: one of the three emoji plus an optional one-line note.
Pure Qt; the caller sends. Nothing here touches the collection or the
network."""

from aqt.qt import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QVBoxLayout,
)

NOTE_MAX = 80


class CheerDialog(QDialog):
    def __init__(self, parent, name, emojis):
        super().__init__(parent)
        self.setWindowTitle(f"Cheer {name}")
        self.emoji = None
        self.note = ""
        self._emojis = list(emojis)
        self._buttons = []
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        for em in self._emojis:
            b = QPushButton(em)
            b.setCheckable(True)
            b.setStyleSheet("font-size: 20px; padding: 6px 14px;")
            b.clicked.connect(lambda _=False, e=em: self._pick(e))
            row.addWidget(b)
            self._buttons.append(b)
        row.addStretch()
        lay.addLayout(row)
        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("Add a note (optional)")
        self.note_edit.setMaxLength(NOTE_MAX)
        lay.addWidget(self.note_edit)
        hint = QLabel(f"They see it after their next sync. Up to {NOTE_MAX} characters.")
        hint.setStyleSheet("font-size: 11px;")
        lay.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Send")
        buttons.accepted.connect(self._send)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self._pick(self._emojis[0])
        self.note_edit.setFocus()

    def _pick(self, emoji):
        self.emoji = emoji
        for b, em in zip(self._buttons, self._emojis):
            b.setChecked(em == emoji)

    def _send(self):
        self.note = " ".join(self.note_edit.text().split())[:NOTE_MAX]
        self.accept()
