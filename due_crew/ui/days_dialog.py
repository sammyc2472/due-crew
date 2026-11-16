"""A follower's own days (G4, G7): pause a plan until a day, the question
on coming back, and how many days my dates run after the plan's. Only
this follower's copy changes; the plan never does. Plan and date names are
the author's: plain text, never markup (3.9.1: they were escaped into
rich text, and a lone "&" then showed as "&amp;")."""

import datetime

from aqt.qt import (
    QButtonGroup, QDate, QDateEdit, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QRadioButton,
    QSpinBox, QVBoxLayout, Qt,
)

from . import heading, laid, note, styled
from ..words import t as _t, tn as _tn


def _qdate(iso):
    d = datetime.date.fromisoformat(iso)
    return QDate(d.year, d.month, d.day)


def _iso(qd):
    return datetime.date(qd.year(), qd.month(), qd.day()).isoformat()


def _note(text):
    """The small print under a choice, as plain text: an event's name is its author's."""
    label = QLabel(str(text))
    label.setTextFormat(Qt.TextFormat.PlainText)
    return note(label)


class PauseDialog(QDialog):
    """Pause until a day. `until` comes from my Away dates when they're set."""

    def __init__(self, parent, name, today, until, from_away=False):
        super().__init__(parent)
        styled(self)  # 3.9.1: the board's look
        self.until = None
        self.setWindowTitle(_t("Pause"))
        self.setMinimumWidth(380)
        root = QVBoxLayout(self)
        heading(self, root, _t("Pause {name}", name=name))
        row = QHBoxLayout()
        row.addWidget(QLabel(_t("Until")))
        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("ddd d MMM yyyy")
        self.date.setMinimumDate(_qdate(today))
        self.date.setDate(_qdate(until))
        row.addWidget(self.date)
        row.addStretch()
        root.addLayout(row)
        root.addWidget(_note((_t("From your Away dates.") + " " if from_away else "")
                             + _t("Nothing opens while it's paused. On the day after, it asks what to do with what you missed.")))
        buttons = QDialogButtonBox()
        buttons.addButton(_t("Cancel"), QDialogButtonBox.ButtonRole.RejectRole).clicked.connect(self.reject)
        ok = buttons.addButton(_t("Pause"), QDialogButtonBox.ButtonRole.AcceptRole)
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
        styled(self)  # 3.9.1: the board's look
        self.choice = None
        self.setWindowTitle(_t("Welcome back"))
        self.setMinimumWidth(420)
        root = QVBoxLayout(self)
        heading(self, root, _tn("Welcome back. {n} set opened while you were away.", "Welcome back. {n} sets opened while you were away.", n_units))
        self.push = QRadioButton(_tn("Push my dates back {n} day", "Push my dates back {n} days", days))
        self.push.setChecked(True)
        self.open = QRadioButton(_tn("Open the {n} set now", "Open the {n} sets now", n_units))
        group = QButtonGroup(self)
        group.addButton(self.push)
        group.addButton(self.open)
        root.addWidget(self.push)
        root.addWidget(self.open)
        root.addWidget(_note(_t("Only your copy changes. The plan stays the same for everyone else, and {event} is still {day}.", event=event[0], day=event[1])
                             if event else _t("Only your copy changes. The plan stays the same for everyone else.")))
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
        styled(self)  # 3.9.1: the board's look
        self.days = None
        self.setWindowTitle(_t("Push my dates back"))
        self.setMinimumWidth(380)
        root = QVBoxLayout(self)
        heading(self, root, str(name))
        row = QHBoxLayout()
        self.spin = QSpinBox()
        self.spin.setRange(0, 365)
        self.spin.setValue(int(current or 0))
        laid(row, _t("My dates run {n} days after the plan's"), n=self.spin)  # one phrase around the box
        row.addStretch()
        root.addLayout(row)
        root.addWidget(_note(_t("Only your copy moves; events stay on their days. 0 puts you back on the plan's dates. "
                                "Sets already open stay open.")))
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
