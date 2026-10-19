"""Pip beside a line in Your plans (3.9.3): still (ui.sev_label), as
Settings › Pip says, at a moment worth one: a Fill that puts everything
ticked on the calendar, an update posted to followers, a plan with no
history yet. The words are the line's own; Pip goes when they change."""

from aqt.qt import QHBoxLayout, QLabel, Qt, QWidget

from ..ui import note, sev_label


class PipNote(QWidget):
    """A line of words (setText, text, as a label's), with Pip in a pose
    beside it while say() asks for one. pip_on: Settings › Pip, asked
    each time."""

    def __init__(self, pip_on, muted=False, size=40):
        super().__init__()
        self.pip_on, self.size, self.pose, self.pip = pip_on, size, None, None
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.words = QLabel()
        self.words.setTextFormat(Qt.TextFormat.PlainText)
        self.words.setWordWrap(True)
        if muted:
            note(self.words)
        row.addWidget(self.words, 1)

    def say(self, text, pose=None, name="Pip"):
        self.words.setText(str(text or ""))
        want = pose if pose and text and self.pip_on() else None
        if want == self.pose:
            return
        if self.pip is not None:
            self.layout().removeWidget(self.pip)
            self.pip.deleteLater()
        self.pip = sev_label(want, self.size, name) if want else None
        if self.pip is not None:
            self.layout().insertWidget(0, self.pip, 0, Qt.AlignmentFlag.AlignVCenter)
        self.pose = want if self.pip is not None else None

    def setText(self, text):  # noqa: N802 (a label's)
        self.say(text)

    def text(self):
        return self.words.text()
