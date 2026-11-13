"""3.9.11, a hook (hooks.py): my one line on the card up now, and whether my
crew reads it. Opened from the review screen's chip or More menu, where
there's no board for a sheet. Nothing is sent from here: the caller keeps
the line and sends it."""

from aqt.qt import QCheckBox, QDialog, QDialogButtonBox, QLineEdit, QPushButton, QVBoxLayout

from . import attach_alive, heading, note
from ..backend.shapes import NOTE_MAX

SHARE_WORDS = "Share with my crew"
SHARE_NOTE = "Crewmates see it when they miss this card. Never the card itself."


class HookDialog(QDialog):
    """words: the hook the card has ("" for none); shared: the tick as it
    starts; signed_in: whether there's a crew to share with. After exec():
    .result_words (None when cancelled; "" takes the hook off) and .result_shared."""

    def __init__(self, parent, words="", shared=True, signed_in=True):
        super().__init__(parent)
        attach_alive(self)
        self.result_words, self.result_shared = None, bool(shared)
        self.setWindowTitle("Your hook" if words else "Add a hook")
        self.setMinimumWidth(460)
        root = QVBoxLayout(self)
        heading(self, root)
        self.text = QLineEdit(words)
        self.text.setMaxLength(NOTE_MAX)
        self.text.setPlaceholderText("What makes this card stick? One line.")
        root.addWidget(self.text)
        self.share = QCheckBox(SHARE_WORDS)
        self.share.setChecked(bool(shared) and bool(signed_in))
        self.share.setEnabled(bool(signed_in))
        root.addWidget(self.share)
        from aqt.qt import QLabel
        why = QLabel(SHARE_NOTE if signed_in else "Kept on this computer. Sign in to share hooks with your crew.")
        why.setWordWrap(True)
        root.addWidget(note(why))
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.remove_btn = QPushButton("Take it off")
        self.remove_btn.clicked.connect(lambda: self._done(""))
        self.buttons.addButton(self.remove_btn, QDialogButtonBox.ButtonRole.ActionRole)
        self.remove_btn.setVisible(bool(words))  # after it's in the box, which shows what it's given
        self.save_btn = QPushButton("Save")
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(lambda: self._done(self.text.text()))
        self.buttons.addButton(self.save_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)
        self.text.textChanged.connect(lambda *_: self._ready())
        self._ready()

    def _ready(self):
        self.save_btn.setEnabled(bool(self.text.text().strip()))

    def _done(self, words):
        self.result_words, self.result_shared = str(words), self.share.isChecked()
        self.accept()
