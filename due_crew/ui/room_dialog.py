"""Open a Study Room (2.12): rounds, their length, the breaks, and now or
at a time. A later start makes it a study date: the crew sees it coming."""

import datetime

from aqt.qt import (
    QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QRadioButton, QSpinBox, QTime, QTimeEdit, QVBoxLayout,
)

from . import attach_alive, heading, laid, note
from ..room_model import BREAK_CHOICES, MAX_ROUNDS, ROUND_CHOICES, duration_text
from ..words import t as _t


class RoomDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.result_room = None  # (start UTC, rounds, round min, break min)
        attach_alive(self)
        self.setWindowTitle(_t("Open a study room"))
        self.setMinimumWidth(420)
        root = QVBoxLayout(self)
        heading(self, root)

        row = QHBoxLayout()
        self.rounds = QSpinBox()
        self.rounds.setRange(1, MAX_ROUNDS)
        self.rounds.setValue(4)
        self.length = QComboBox()
        for m in ROUND_CHOICES:
            self.length.addItem(_t("{n} min", n=m), m)
        self.length.setCurrentIndex(ROUND_CHOICES.index(25))
        self.brk = QComboBox()
        for m in BREAK_CHOICES:
            self.brk.addItem(_t("{n} min", n=m), m)
        # one phrase around the three boxes
        laid(row, _t("Rounds {n} of {length} with {pause} breaks"), n=self.rounds, length=self.length, pause=self.brk)
        row.addStretch()
        root.addLayout(row)

        when = QHBoxLayout()
        when.addWidget(QLabel(_t("Starts")))
        self.now = QRadioButton(_t("Now"))
        self.now.setChecked(True)
        self.later = QRadioButton(_t("At a time"))
        group = QButtonGroup(self)
        group.addButton(self.now)
        group.addButton(self.later)
        self.time = QTimeEdit()
        self.time.setDisplayFormat("HH:mm")
        soon = datetime.datetime.now() + datetime.timedelta(minutes=35)
        soon = soon.replace(minute=0 if soon.minute < 30 else 30)
        self.time.setTime(QTime(soon.hour, soon.minute))
        # 3.4 review, N11: the time appears when "At a time" is picked
        self.time.setVisible(False)
        self.later.toggled.connect(self.time.setVisible)
        when.addWidget(self.now)
        when.addWidget(self.later)
        when.addWidget(self.time)
        when.addStretch()
        root.addLayout(when)

        self.note = note(QLabel(""))
        root.addWidget(self.note)
        for w in (self.rounds.valueChanged, self.length.currentIndexChanged, self.brk.currentIndexChanged):
            w.connect(self._update_note)
        self._update_note()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(_t("Open room"))
        buttons.accepted.connect(self._open)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _choice(self):
        return self.rounds.value(), int(self.length.currentData()), int(self.brk.currentData())

    def _update_note(self, *_):
        rounds, length, brk = self._choice()
        self.note.setText(_t("About {time}. "
                             "Your crew sees it on their board and can join any time. "
                             "A break waits until you finish the card you're on.", time=duration_text(rounds * length + (rounds - 1) * brk)))

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
