"""Open a Study Room (2.12): rounds, their length, the breaks, and now or
at a time. A later start makes it a study date: the crew sees it coming."""

import datetime

from aqt.qt import (
    QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QRadioButton, QSpinBox, QTime, QTimeEdit, QVBoxLayout,
)

from . import attach_alive
from ..room_model import BREAK_CHOICES, MAX_ROUNDS, ROUND_CHOICES, duration_text


class RoomDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.result_room = None  # (start UTC, rounds, round min, break min)
        attach_alive(self)
        self.setWindowTitle("Open a Study Room")
        self.setMinimumWidth(420)
        root = QVBoxLayout(self)

        row = QHBoxLayout()
        row.addWidget(QLabel("Rounds"))
        self.rounds = QSpinBox()
        self.rounds.setRange(1, MAX_ROUNDS)
        self.rounds.setValue(4)
        row.addWidget(self.rounds)
        row.addWidget(QLabel("of"))
        self.length = QComboBox()
        for m in ROUND_CHOICES:
            self.length.addItem(f"{m} min", m)
        self.length.setCurrentIndex(ROUND_CHOICES.index(25))
        row.addWidget(self.length)
        row.addWidget(QLabel("with"))
        self.brk = QComboBox()
        for m in BREAK_CHOICES:
            self.brk.addItem(f"{m} min", m)
        row.addWidget(self.brk)
        row.addWidget(QLabel("breaks"))
        row.addStretch()
        root.addLayout(row)

        when = QHBoxLayout()
        when.addWidget(QLabel("Starts"))
        self.now = QRadioButton("Now")
        self.now.setChecked(True)
        self.later = QRadioButton("At")
        group = QButtonGroup(self)
        group.addButton(self.now)
        group.addButton(self.later)
        self.time = QTimeEdit()
        self.time.setDisplayFormat("HH:mm")
        soon = datetime.datetime.now() + datetime.timedelta(minutes=35)
        soon = soon.replace(minute=0 if soon.minute < 30 else 30)
        self.time.setTime(QTime(soon.hour, soon.minute))
        self.time.setEnabled(False)
        self.later.toggled.connect(self.time.setEnabled)
        when.addWidget(self.now)
        when.addWidget(self.later)
        when.addWidget(self.time)
        when.addStretch()
        root.addLayout(when)

        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setStyleSheet("font-size: 12px;")
        root.addWidget(self.note)
        for w in (self.rounds.valueChanged, self.length.currentIndexChanged, self.brk.currentIndexChanged):
            w.connect(self._update_note)
        self._update_note()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Open Room")
        buttons.accepted.connect(self._open)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _choice(self):
        return self.rounds.value(), int(self.length.currentData()), int(self.brk.currentData())

    def _update_note(self, *_):
        rounds, length, brk = self._choice()
        self.note.setText(f"About {duration_text(rounds * length + (rounds - 1) * brk)}. "
                          "Your crew sees it on their board and can join any time. "
                          "A break waits until you finish the card you're on.")

    def _open(self):
        from ..rooms import start_at
        rounds, length, brk = self._choice()
        if self.later.isChecked():
            t = self.time.time()
            start = start_at(datetime.time(t.hour(), t.minute()))
        else:
            start = datetime.datetime.now(datetime.timezone.utc)
        self.result_room = (start, rounds, length, brk)
        self.accept()
