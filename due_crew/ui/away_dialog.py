"""3.8.1, Welcome back: the morning would open a plan's dates from 3 or
more days on which I studied nothing in Anki. Asked before anything opens:
Open them · Push my dates back N days (my follow's shift, one request) ·
Not today (nothing opens; tomorrow morning asks again). Plan names are the
author's: plain text only. Sev waves from its corner (Sam's pick), still,
unless Settings › Sev is off."""

import datetime

from aqt.qt import QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPushButton, Qt, QVBoxLayout

from . import attach_alive, sev_label


def _day(iso):
    try:
        d = datetime.date.fromisoformat(str(iso))
    except ValueError:
        return str(iso)
    return f"{d:%a} {d.day} {d:%b}"


def days_words(days):
    """"3 days with no study in Anki: Mon 5 Oct, Tue 6 Oct and Wed 7 Oct.", or
    with more than four "… between Mon 5 Oct and Fri 16 Oct."."""
    days = [str(x) for x in days]
    n = len(days)
    head = f"{n} day{'s' if n != 1 else ''} with no study in Anki"
    if n > 4:
        return f"{head} between {_day(days[0])} and {_day(days[-1])}."
    if n == 1:
        return f"{head}: {_day(days[0])}."
    return f"{head}: " + ", ".join(_day(x) for x in days[:-1]) + f" and {_day(days[-1])}."


class AwayDialog(QDialog):
    """choice: "open", "push", or None (Not today, or closed: the same)."""

    def __init__(self, parent, name, days, n_dates, n_cards, sev=False):
        super().__init__(parent)
        attach_alive(self)
        self.choice = None
        n = len(days)
        self.setWindowTitle("Welcome back")
        self.setMinimumWidth(430)
        root = QVBoxLayout(self)
        words = QVBoxLayout()
        top = QHBoxLayout()
        self.sev = sev_label("hello", 64, "Sev, waving") if sev else None
        if self.sev is not None:
            top.addWidget(self.sev, 0, Qt.AlignmentFlag.AlignTop)
            top.addSpacing(8)
        top.addLayout(words, 1)
        root.addLayout(top)
        head = QLabel(f"Welcome back to {name}")
        head.setTextFormat(Qt.TextFormat.PlainText)
        head.setWordWrap(True)
        head.setStyleSheet("font-weight: 600;")
        words.addWidget(head)
        self.body = QLabel(f"{days_words(days)} "
                           f"{n_dates:,} date{'s' if n_dates != 1 else ''} would open now: "
                           f"{n_cards:,} new card{'s' if n_cards != 1 else ''}.")
        self.body.setTextFormat(Qt.TextFormat.PlainText)
        self.body.setWordWrap(True)
        words.addWidget(self.body)
        note = QLabel("Pushing moves only your dates; the plan and its events stay put. "
                      "Not today opens nothing and asks again tomorrow morning.")
        note.setTextFormat(Qt.TextFormat.PlainText)
        note.setWordWrap(True)
        note.setStyleSheet("color: palette(placeholder-text); font-size: 11.5px;")
        words.addWidget(note)
        buttons = QDialogButtonBox()
        buttons.addButton("Not today", QDialogButtonBox.ButtonRole.RejectRole).clicked.connect(self.reject)
        self.push_btn = QPushButton(f"Push my dates back {n} day{'s' if n != 1 else ''}")
        self.push_btn.clicked.connect(lambda: self._go("push"))
        buttons.addButton(self.push_btn, QDialogButtonBox.ButtonRole.ActionRole)
        self.open_btn = QPushButton("Open them")
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
