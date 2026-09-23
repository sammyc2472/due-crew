"""Cheer picker: a row of quick picks, an "other" box for any emoji, and an
optional one-line note. Pure Qt; the caller sends. Nothing here touches
the collection or the network.

The "other" box is a text field that acts like a button: a click opens
the system emoji palette (macOS, Windows), whose pick lands in the field
as typed text; where there is no palette a typed or pasted emoji does the
same. The box only ever holds one emoji: the first cluster of whatever
arrives is kept and anything else is cleared, so a second pick replaces
the first instead of joining it."""

from aqt.qt import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QVBoxLayout,
)

from . import accent, open_emoji_picker
from ..backend.firebase import clean_emoji

NOTE_MAX = 80


class _OtherBox(QLineEdit):
    def __init__(self):
        super().__init__()
        self.setPlaceholderText("other")
        self.setToolTip("Any emoji")
        self.setFixedWidth(66)
        self.setMaxLength(16)  # QString length is UTF-16 units: the rules' own cap

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self.selectAll()  # the next pick replaces what is here
        open_emoji_picker(self)


class CheerDialog(QDialog):
    def __init__(self, parent, name, emojis, any_emoji=True):
        super().__init__(parent)
        self.setWindowTitle(f"Cheer {name}")
        self.setMinimumWidth(360)
        self.emoji = None
        self.note = ""
        self._emojis = list(emojis)
        self._buttons = []
        self.other = None
        self._boxed = ""
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        for em in self._emojis:
            b = QPushButton(em)
            b.setCheckable(True)
            b.setMinimumSize(48, 40)
            b.setStyleSheet(
                "QPushButton { font-size: 22px; padding: 4px 8px; border-radius: 8px;"
                " border: 2px solid transparent; }"
                f"QPushButton:checked {{ border-color: {accent()}; }}")
            b.clicked.connect(lambda _=False, e=em: self._pick(e))
            row.addWidget(b)
            self._buttons.append(b)
        if any_emoji:
            self.other = _OtherBox()
            self.other.setStyleSheet(self._other_css(False))
            self.other.textChanged.connect(self._typed)
            row.addWidget(self.other)
        row.addStretch()
        lay.addLayout(row)
        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("Add a note (optional)")
        self.note_edit.setMaxLength(NOTE_MAX)
        lay.addWidget(self.note_edit)
        hint = QLabel("Lands after their next sync.")
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

    @staticmethod
    def _other_css(chosen):
        # a small "other" at rest; a chosen emoji at the quick picks' size
        border = f"2px solid {accent()}" if chosen else "1px solid palette(mid)"
        return (f"QLineEdit {{ font-size: {20 if chosen else 12}px; border: {border};"
                " border-radius: 8px; padding: 3px 6px; min-height: 30px; }")

    def _pick(self, emoji):
        self.emoji = emoji
        for b, em in zip(self._buttons, self._emojis):
            b.setChecked(em == emoji)
        if self.other is not None:
            self._set_other("")

    def _set_other(self, text):
        self._boxed = text
        self.other.blockSignals(True)
        self.other.setText(text)
        self.other.blockSignals(False)
        self.other.setStyleSheet(self._other_css(bool(text)))

    def _typed(self, text):
        prev = self._boxed
        if prev and text.startswith(prev) and len(text) > len(prev):
            text = text[len(prev):]  # a pick landed after the last one: keep the new one
        emoji = clean_emoji(text)
        if not emoji:
            if text:
                self._set_other("")  # letters, or a cluster that doesn't fit
            else:
                self._boxed = ""
                self.other.setStyleSheet(self._other_css(False))
            if prev:
                self._pick(self._emojis[0])
            return
        self._set_other(emoji)
        self.emoji = emoji
        for b in self._buttons:
            b.setChecked(False)

    def _send(self):
        self.note = " ".join(self.note_edit.text().split())[:NOTE_MAX]
        self.accept()
