"""Add cards to a plan (3.1, mock 1.3), from Anki's browser: the picked
cards onto a date of a plan I wrote, or onto a new date. Only those
cards, never their siblings, and only which cards they are ([note guid,
card number]), never their text. Two requests, both on a click: my plans
when the dialog opens, and the add."""

import datetime

from aqt.qt import (
    QButtonGroup, QComboBox, QDate, QDateEdit, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QLabel, QRadioButton, Qt, QVBoxLayout, QWidget,
)

from . import attach_alive, run_bg
from .. import plans as P


class AddCardsDialog(QDialog):
    def __init__(self, parent, client, refs, today, on_added=None, search="", search_n=0):
        super().__init__(parent)
        self.client, self.refs, self.today = client, list(refs), today
        self.on_added = on_added
        self.search, self.search_n = str(search or "").strip(), int(search_n or 0)
        self.plans = []
        attach_alive(self)
        self.setWindowTitle("Add to a plan")
        self.setMinimumWidth(440)
        root = QVBoxLayout(self)

        form = QFormLayout()
        self.plan = QComboBox()
        self.plan.currentIndexChanged.connect(self._plan_changed)
        form.addRow("Plan", self.plan)
        opens = QWidget()
        ol = QVBoxLayout(opens)
        ol.setContentsMargins(0, 0, 0, 0)
        wrow = QHBoxLayout()
        self.with_unit = QRadioButton("")
        self.unit = QComboBox()
        wrow.addWidget(self.with_unit)
        wrow.addWidget(self.unit, 1)
        ol.addLayout(wrow)
        orow = QHBoxLayout()
        self.own = QRadioButton("New date")
        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("ddd d MMM yyyy")
        try:
            t = datetime.date.fromisoformat(today) + datetime.timedelta(days=1)
        except ValueError:
            t = datetime.date.today() + datetime.timedelta(days=1)
        self.date.setDate(QDate(t.year, t.month, t.day))
        orow.addWidget(self.own)
        orow.addWidget(self.date)
        orow.addStretch()
        ol.addLayout(orow)
        group = QButtonGroup(self)
        group.addButton(self.with_unit)
        group.addButton(self.own)
        self.with_unit.setChecked(True)
        self.unit.currentIndexChanged.connect(lambda *_: self.with_unit.setChecked(True))
        self.date.dateChanged.connect(lambda *_: self.own.setChecked(True))
        form.addRow("Date", opens)
        root.addLayout(form)
        # 3.6.5: a follower's Anki opens a date once; what's added after comes the next morning
        self.opened = QLabel("This date has opened. Followers who opened it get these tomorrow morning.")
        self.opened.setWordWrap(True)
        self.opened.setStyleSheet("color: palette(placeholder-text); font-size: 11.5px;")
        self.opened.setVisible(False)
        root.addWidget(self.opened)
        self.unit.currentIndexChanged.connect(self._opened)
        self.date.dateChanged.connect(self._opened)
        self.with_unit.toggled.connect(self._opened)

        # 3.3, C3: the browser's search itself (it keeps up with cards added
        # later, and runs in each classmate's Anki), or exactly these cards
        n = len(self.refs)
        self.by_search = QRadioButton(f"This search · {self.search_n:,} card{'s' if self.search_n != 1 else ''} now, and cards added to it later")
        self.by_cards = QRadioButton(f"These {n:,} card{'s' if n != 1 else ''} · exactly these")
        what = QButtonGroup(self)
        what.addButton(self.by_search)
        what.addButton(self.by_cards)
        shown = QLabel(self.search)
        shown.setTextFormat(Qt.TextFormat.PlainText)  # the search as typed, never markup
        shown.setStyleSheet("font-family: monospace; font-size: 11.5px; margin-left: 22px;")
        shown.setWordWrap(True)
        for w in (self.by_search, shown, self.by_cards):
            root.addWidget(w)
        self.by_search.setVisible(bool(self.search))
        shown.setVisible(bool(self.search))
        self.by_cards.setVisible(bool(n))
        (self.by_cards if n else self.by_search).setChecked(True)  # what I picked, unless I picked nothing
        self.status = QLabel("Looking for your plans…")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                        | QDialogButtonBox.StandardButton.Cancel)
        self.add_btn = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.add_btn.setText("Add")
        self.add_btn.setEnabled(False)
        self.buttons.accepted.connect(self._add)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)

        me = client.user_id
        run_bg(self, client.my_plans, lambda plans, err: self._loaded(
            None if err else [p for p in plans or [] if p.get("owner") == me or p.get("role") == "editor"]))

    def _loaded(self, plans):
        if plans is None:
            self.status.setText("Couldn't reach Due Crew. Check your connection.")
            return
        self.plans = plans
        if not plans:
            self.status.setText("You haven't made a plan yet. Tools › Due Crew › Make a plan from a deck…")
            return
        self.status.setText("")
        for p in plans:
            self.plan.addItem(P.plan_title(p), p["id"])  # a combo shows plain text
        self._plan_changed()

    def _opened(self, *_):
        p = self._current() if self.plans else None
        if self.with_unit.isChecked():
            uid = self.unit.currentData()
            u = next((x for x in P.units(p["doc"]) if x["id"] == uid), None) if p else None
            day = u["opens"] if u else None
        else:
            d = self.date.date()
            day = f"{d.year():04d}-{d.month():02d}-{d.day():02d}"
        self.opened.setVisible(bool(day) and day <= self.today)

    def _current(self):
        pid = self.plan.currentData()
        return next((p for p in self.plans if p["id"] == pid), None)

    def _plan_changed(self, *_):
        p = self._current()
        self.unit.blockSignals(True)
        self.unit.clear()
        units = P.units(p["doc"]) if p else []
        for u in units:
            self.unit.addItem(f"{u.get('name') or '?'}, {P.fmt_day(u['opens'])}", u["id"])
        nxt = next((i for i, u in enumerate(units) if u["opens"] >= self.today), len(units) - 1)
        self.unit.setCurrentIndex(max(0, nxt))
        self.unit.blockSignals(False)
        self.with_unit.setEnabled(bool(units))
        self.unit.setEnabled(bool(units))
        (self.with_unit if units else self.own).setChecked(True)
        self.add_btn.setEnabled(bool(p) and (bool(self.refs) or bool(self.search)))
        self._opened()

    def _add(self):
        p = self._current()
        if not p:
            return
        unit = self.unit.currentData() if self.with_unit.isChecked() else None
        d = self.date.date()
        opens = f"{d.year():04d}-{d.month():02d}-{d.day():02d}"
        self.add_btn.setEnabled(False)
        self.status.setText("Adding…")
        cl, refs, pid = self.client, self.refs, p["id"]
        search = self.search if self.by_search.isChecked() and self.search else None
        n_added = self.search_n if search else len(refs)

        def done(result, err):
            got, status = result if result else (None, 0)
            if got is None:
                self.add_btn.setEnabled(True)
                self.status.setText({403: "Only the plan's author can add cards.",
                                     404: "That date is gone. Pick another.",
                                     400: "That's more single cards than a plan can hold."}.get(
                    status, "Couldn't add them. Check your connection."))
                return
            if self.on_added:
                self.on_added(got, n_added)
            self.accept()

        run_bg(self, lambda: cl.add_plan_cards(pid, refs, unit=unit, opens=None if unit else opens,
                                               search=search, n=self.search_n), done)
