"""3.8.1, Welcome back: the morning would open a plan's dates from 3 or
more days on which I studied nothing in Anki. Asked before anything opens:
Open them · Push my dates back N days (my follow's shift, one request) ·
Not today (nothing opens; tomorrow morning asks again). Plan names are the
author's: plain text only. Pip waves from its corner (Sam's pick), still,
unless Settings › Pip is off."""

import datetime

from aqt.qt import QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPushButton, Qt, QVBoxLayout

from . import attach_alive, sev_label, title
from . import note as ui_note
from ..words import month as _month, t as _t, tn as _tn, weekday as _weekday


def _day(iso):
    try:
        d = datetime.date.fromisoformat(str(iso))
    except ValueError:
        return str(iso)
    return f"{_weekday(d.weekday())} {d.day} {_month(d.month)}"


def days_words(days):
    """"3 days with no study in Anki: Mon 5 Oct, Tue 6 Oct and Wed 7 Oct.", or
    with more than four "… between Mon 5 Oct and Fri 16 Oct."."""
    days = [str(x) for x in days]
    n = len(days)
    if n > 4:
        return _t("{n} days with no study in Anki between {first} and {last}.", n=n, first=_day(days[0]), last=_day(days[-1]))
    if n == 1:
        return _t("1 day with no study in Anki: {day}.", day=_day(days[0]))
    return _t("{n} days with no study in Anki: {days} and {last}.", n=n, days=", ".join(_day(x) for x in days[:-1]), last=_day(days[-1]))


class AwayDialog(QDialog):
    """choice: "open", "push", or None (Not today, or closed: the same)."""

    def __init__(self, parent, name, days, n_dates, n_cards, sev=False):
        super().__init__(parent)
        attach_alive(self)
        self.choice = None
        n = len(days)
        self.setWindowTitle(_t("Welcome back"))
        self.setMinimumWidth(430)
        root = QVBoxLayout(self)
        words = QVBoxLayout()
        top = QHBoxLayout()
        self.sev = sev_label("hello", 64, _t("Pip, waving")) if sev else None
        if self.sev is not None:
            top.addWidget(self.sev, 0, Qt.AlignmentFlag.AlignTop)
            top.addSpacing(8)
        top.addLayout(words, 1)
        root.addLayout(top)
        words.addWidget(title(_t("Welcome back to {name}", name=name)))
        self.setWindowTitle("Due Crew")  # the window says what it is (ui.heading)
        cards = _t("{n} new card", n=1) if n_cards == 1 else _t("{n} new cards", n=f"{n_cards:,}")
        self.body = QLabel(days_words(days) + " " + (_t("{n} set would open now: {cards}.", n=1, cards=cards) if n_dates == 1
                                                     else _t("{n} sets would open now: {cards}.", n=f"{n_dates:,}", cards=cards)))
        self.body.setTextFormat(Qt.TextFormat.PlainText)
        self.body.setWordWrap(True)
        words.addWidget(self.body)
        note = QLabel(_t("Pushing moves only your dates; the plan and its events stay put. "
                         "Not today opens nothing and asks again tomorrow morning."))
        note.setTextFormat(Qt.TextFormat.PlainText)
        words.addWidget(ui_note(note))
        buttons = QDialogButtonBox()
        buttons.addButton(_t("Not today"), QDialogButtonBox.ButtonRole.RejectRole).clicked.connect(self.reject)
        self.push_btn = QPushButton(_tn("Push my dates back {n} day", "Push my dates back {n} days", n))
        self.push_btn.clicked.connect(lambda: self._go("push"))
        buttons.addButton(self.push_btn, QDialogButtonBox.ButtonRole.ActionRole)
        self.open_btn = QPushButton(_t("Open them"))
        self.open_btn.setDefault(True)
        self.open_btn.clicked.connect(lambda: self._go("open"))
        buttons.addButton(self.open_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        root.addWidget(buttons)

    def _go(self, choice):
        self.choice = choice
        self.accept()


def ask_away(parent, name, days, n_dates, n_cards, sev=False):
    """"open", "push", or "later" (Not today, or the window closed)."""
    dlg = AwayDialog(parent, name, days, n_dates, n_cards, sev)
    return (dlg.choice if dlg.exec() else None) or "later"
