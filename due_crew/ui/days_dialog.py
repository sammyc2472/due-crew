"""A follower's own days (G4, G7): pause a plan until a day, the question
on coming back, and how many days my dates run after the plan's. Only
this follower's copy changes; the plan never does. Plan and date names are
the author's: escaped wherever it's rich text."""

import datetime

from aqt.qt import (
    QButtonGroup, QDate, QDateEdit, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QRadioButton,
    QSpinBox, QVBoxLayout,
)

from . import esc


def _qdate(iso):
    d = datetime.date.fromisoformat(iso)
    return QDate(d.year, d.month, d.day)


def _iso(qd):
    return datetime.date(qd.year(), qd.month(), qd.day()).isoformat()


class PauseDialog(QDialog):
    """Pause until a day. `until` comes from my Away dates when they're set."""

    def __init__(self, parent, name, today, until, from_away=False):
        super().__init__(parent)
        self.until = None
        self.setWindowTitle("Pause")
        self.setMinimumWidth(380)
        root = QVBoxLayout(self)
        root.addWidget(QLabel(f"<b>Pause {esc(name)}</b>"))
        row = QHBoxLayout()
        row.addWidget(QLabel("Until"))
        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("ddd d MMM yyyy")
        self.date.setMinimumDate(_qdate(today))
        self.date.setDate(_qdate(until))
        row.addWidget(self.date)
        row.addStretch()
        root.addLayout(row)
        note = QLabel(("From your Away dates. " if from_away else "")
                      + "Nothing opens while it's paused. On the day after, it asks what to do with what you missed.")
        note.setWordWrap(True)
        root.addWidget(note)
        buttons = QDialogButtonBox()
        buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole).clicked.connect(self.reject)
        ok = buttons.addButton("Pause", QDialogButtonBox.ButtonRole.AcceptRole)
        ok.setDefault(True)
        ok.clicked.connect(self._ok)
        root.addWidget(buttons)

    def _ok(self):
        self.until = _iso(self.date.date())
        self.accept()


def ask_pause(parent, name, today, until, from_away=False):
    dlg = PauseDialog(parent, name, today, until, from_away)
    return dlg.until if dlg.exec() else None


class BackDialog(QDialog):
    """Back from a pause: move my dates later by the days I was away, or
    open what opened meanwhile."""

    def __init__(self, parent, n_units, days, event=None):
        super().__init__(parent)
        self.choice = None
        self.setWindowTitle("Welcome back")
        self.setMinimumWidth(420)
        root = QVBoxLayout(self)
        root.addWidget(QLabel(f"<b>Welcome back. {n_units} date{'s' if n_units != 1 else ''} "
                              f"opened while you were away.</b>"))
        self.push = QRadioButton(f"Pick up where I left off: my dates move {days} day{'s' if days != 1 else ''} later")
        self.push.setChecked(True)
        self.open = QRadioButton(f"Open the {n_units} date{'s' if n_units != 1 else ''} now")
        group = QButtonGroup(self)
        group.addButton(self.push)
        group.addButton(self.open)
        root.addWidget(self.push)
        root.addWidget(self.open)
        note = QLabel("Only your copy changes. The plan stays the same for everyone else"
                      + (f", and {esc(event[0])} is still {esc(event[1])}." if event else "."))
        note.setWordWrap(True)
        root.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self._ok)
        root.addWidget(buttons)

    def _ok(self):
        self.choice = "push" if self.push.isChecked() else "open"
        self.accept()


def ask_back(parent, n_units, days, event=None):
    dlg = BackDialog(parent, n_units, days, event)
    return dlg.choice if dlg.exec() else "open"


class ShiftDialog(QDialog):
    """Push my dates back: how many days my dates run after the plan's."""

    def __init__(self, parent, name, current):
        super().__init__(parent)
        self.days = None
        self.setWindowTitle("Push my dates back")
        self.setMinimumWidth(380)
        root = QVBoxLayout(self)
        root.addWidget(QLabel(f"<b>{esc(name)}</b>"))
        row = QHBoxLayout()
        row.addWidget(QLabel("My dates run"))
        self.spin = QSpinBox()
        self.spin.setRange(0, 365)
        self.spin.setValue(int(current or 0))
        row.addWidget(self.spin)
        row.addWidget(QLabel("days after the plan's"))
        row.addStretch()
        root.addLayout(row)
        note = QLabel("Only your copy moves; events stay on their days. 0 puts you back on the plan's dates. "
                      "Dates already open stay open.")
        note.setWordWrap(True)
        root.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._ok)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _ok(self):
        self.days = int(self.spin.value())
        self.accept()


def ask_shift(parent, name, current):
    dlg = ShiftDialog(parent, name, current)
    return dlg.days if dlg.exec() else None
