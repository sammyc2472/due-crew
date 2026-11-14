"""Report a crewmate (3.0.1): a reason, an optional note, and Report. Pure
Qt; the caller sends it and mutes them. The name is the server's, so it
goes only where Qt shows plain text (the window title)."""

from aqt.qt import (
    QButtonGroup, QDialog, QDialogButtonBox, QLabel, QLineEdit, QRadioButton, Qt,
    QVBoxLayout,
)

from . import attach_alive, heading, note
from ..backend.shapes import REPORT_NOTE_MAX as NOTE_MAX, REPORT_REASONS as REASONS
from ..words import t as _t


class ReportDialog(QDialog):
    def __init__(self, parent, name):
        super().__init__(parent)
        self.reason = None
        self.note = ""
        attach_alive(self)
        self.setWindowTitle(_t("Report {name}", name=name))
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)
        heading(self, lay)
        self.group = QButtonGroup(self)
        self.choices = []
        for i, (_value, text) in enumerate(REASONS):
            radio = QRadioButton(_t(text))
            self.group.addButton(radio, i)
            self.choices.append(radio)
            lay.addWidget(radio)
        self.choices[0].setChecked(True)
        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText(_t("Add a note (optional)"))
        self.note_edit.setMaxLength(NOTE_MAX)
        lay.addWidget(self.note_edit)
        hint = QLabel(_t("Sends their name, emoji and last cheer to Due Crew. Reporting also mutes them."))
        hint.setTextFormat(Qt.TextFormat.PlainText)
        lay.addWidget(note(hint))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(_t("Report"))
        buttons.accepted.connect(self._report)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _report(self):
        self.reason = REASONS[max(0, self.group.checkedId())][0]
        self.note = " ".join(self.note_edit.text().split())[:NOTE_MAX]
        self.accept()
