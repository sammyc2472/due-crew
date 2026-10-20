"""Round five's Change… (docs/planner.md): the plan's shape in one window,
where Lay it out and Settings had it in two. When it starts, what it
ends with (a quiz or exam of its own, a day, or nothing yet), its study
days, how many new cards a day (up to N, fit to the end, or each date
set by hand), no new cards in the last days before the end, catch-up
weeks. Before anything goes in, it says what moves: every date and quiz
moves with the start. Each part is an op (ops.py); Add to the changes
(or Save, nobody following) puts them in as one. Names: plain text."""

from aqt.qt import (
    QButtonGroup, QComboBox, QDate, QDateEdit, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QPushButton,
    QSpinBox, Qt, QVBoxLayout,
)

from ..ui import attach_alive, esc, heading
from .. import plans as P
from . import build as B
from . import edits as E
from . import ops as O
from . import view as V
from .widgets import frame, mark, plain

CATCHUP = ((0, "None"), (3, "Every 3rd week"), (4, "Every 4th week"))
MODES = (("daily", "Up to"), ("end", "Fit to the end"), ("placed", "I set each date"))


def _iso(qd):
    return qd.toString("yyyy-MM-dd")


class ShapeDialog(QDialog):
    """win: the PlanWindow (its doc, as it shows with the changes waiting)."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        attach_alive(self)
        self.setWindowTitle("The plan's shape")
        self.setMinimumWidth(480)
        doc = win.doc
        self.doc = doc
        self.pace = V.pace_of(doc)
        self.start0 = B.plan_start(doc, B.next_monday(win.ops.today()))
        self.ev0, self.end0 = V.ends_with(doc)
        ph = doc.get("phases") or {}
        self._loading = True
        root = QVBoxLayout(self)
        heading(self, root)
        form = QFormLayout()
        form.setVerticalSpacing(10)
        self.start = QDateEdit()
        self.start.setCalendarPopup(True)
        self.start.setDisplayFormat("ddd d MMM yyyy")
        self.start.setDate(QDate.fromString(self.start0, "yyyy-MM-dd"))
        self.start.dateChanged.connect(lambda _d: self._said())
        form.addRow("Starts", self.start)

        ends = QHBoxLayout()
        self.ends = QComboBox()
        evs = sorted((e for e in doc.get("events") or [] if isinstance(e, dict) and e.get("day")), key=lambda e: str(e["day"]))
        for e in evs:
            self.ends.addItem(f"{e.get('name') or '?'} · {P.fmt_day(e['day'])}", ("event", e["id"], e["day"]))
        self.ends.addItem("A day…", ("day", None, None))
        self.ends.addItem("Nothing yet", ("none", None, None))
        if self.ev0 is not None:
            self.ends.setCurrentIndex(self.ends.findData(("event", self.ev0["id"], self.ev0["day"])))
        elif self.end0:
            self.ends.setCurrentIndex(self.ends.count() - 2)
        else:
            self.ends.setCurrentIndex(self.ends.count() - 1)
        self.ends.currentIndexChanged.connect(lambda _i: self._said())
        ends.addWidget(self.ends, 1)
        self.end_day = QDateEdit()
        self.end_day.setCalendarPopup(True)
        self.end_day.setDisplayFormat("ddd d MMM yyyy")
        self.end_day.setDate(QDate.fromString(self.end0 or E._later(self.start0, 55), "yyyy-MM-dd"))
        self._end_touched = False
        self.end_day.dateChanged.connect(lambda _d: (setattr(self, "_end_touched", True), self._said()))
        ends.addWidget(self.end_day)
        form.addRow("Ends with", ends)

        days = QHBoxLayout()
        days.setSpacing(4)
        self.days = []
        for i, d in enumerate("MTWTFSS"):
            b = QPushButton(d)
            b.setProperty("dc", "seg")
            b.setCheckable(True)
            b.setAutoDefault(False)
            b.setChecked(bool((self.pace.get("days") or [1] * 7)[i]))
            b.setToolTip(("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")[i])
            b.toggled.connect(lambda _on, i=i: self._day(i))
            days.addWidget(b)
            self.days.append(b)
        days.addStretch(1)
        form.addRow("Study days", days)

        new = QHBoxLayout()
        new.setSpacing(0)
        self.mode = QButtonGroup(self)
        for i, (key, label) in enumerate(MODES):
            b = QPushButton(label)
            b.setProperty("dc", "seg")
            b.setCheckable(True)
            b.setAutoDefault(False)
            b.setChecked(self.pace.get("mode") == key)
            self.mode.addButton(b, i)
            new.addWidget(b)
        self.mode.idClicked.connect(lambda _i: self._said())
        new.addSpacing(8)
        self.daily = QSpinBox()
        self.daily.setRange(1, 5000)
        self.daily.setValue(int(self.pace.get("daily") or 20))
        self.daily.setSuffix(" a day")
        self.daily.valueChanged.connect(lambda _v: self._said())
        new.addWidget(self.daily)
        new.addStretch(1)
        form.addRow("New cards", new)

        self.taper = QSpinBox()
        self.taper.setRange(0, 60)
        self.taper.setSuffix(" days")
        self.taper.setValue(int(ph.get("taper") or 0))
        self.taper.valueChanged.connect(lambda _v: self._said())
        form.addRow("No new cards before the end", self.taper)
        self.catchup = QComboBox()
        for v, label in CATCHUP:
            self.catchup.addItem(label, v)
        c = int(ph.get("catchup") or 0)
        if self.catchup.findData(c) < 0:
            self.catchup.addItem(f"Every {c}th week", c)
        self.catchup.setCurrentIndex(self.catchup.findData(c))
        self.catchup.currentIndexChanged.connect(lambda _i: self._said())
        form.addRow("Catch-up weeks (nothing new)", self.catchup)
        root.addLayout(form)

        self.preview, pl = frame("warm")
        self.preview_words = plain()
        self.preview_words.setTextFormat(Qt.TextFormat.RichText)
        pl.addWidget(self.preview_words)
        root.addWidget(self.preview)
        buttons = QDialogButtonBox()
        buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole).clicked.connect(self.reject)
        self.go = QPushButton("Add to the changes" if win.waiting() else "Save")
        self.go.setDefault(True)
        self.go.clicked.connect(self.accept)
        buttons.addButton(self.go, QDialogButtonBox.ButtonRole.AcceptRole)
        root.addWidget(buttons)
        self._loading = False
        self._said()

    def _day(self, i):
        if self._loading:
            return
        if not any(b.isChecked() for b in self.days):
            self._loading = True
            self.days[i].setChecked(True)
            self._loading = False
        self._said()

    def _mode_key(self):
        return MODES[max(0, self.mode.checkedId())][0]

    def _end(self):
        kind, _eid, day = self.ends.currentData()
        if kind == "event":
            return day
        if kind == "day":
            return _iso(self.end_day.date())
        return None

    def ops(self):
        """The ops this window's choices make, only for what changed."""
        out = []
        start = _iso(self.start.date())
        delta = (E._day(start) - E._day(self.start0)).days
        if delta and (P.units(self.doc) or self.doc.get("events") or self.doc.get("reviews") or self.doc.get("end")):
            out.append({"op": "shift_all", "days": delta})
        shifted = bool(out)
        end, kind = self._end(), self.ends.currentData()[0]
        if end and shifted and not (kind == "day" and self._end_touched):
            end = E._later(end, delta)  # the exam (or the day it had) moves with the start
        end_now = E._later(self.doc["end"], delta) if shifted and self.doc.get("end") else self.doc.get("end")
        if (end or None) != (end_now or None):
            out.append({"op": "set_end", "end": end})
        days = [1 if b.isChecked() else 0 for b in self.days]
        mode, daily = self._mode_key(), int(self.daily.value())
        if (mode, days, daily) != (self.pace.get("mode"), list(self.pace.get("days") or [1] * 7), int(self.pace.get("daily") or 20)):
            out.append({"op": "set_pace", "mode": mode, "days": days, "daily": daily, "cover": list(self.pace.get("cover") or [])})
        ph = self.doc.get("phases") or {}
        c, t = int(self.catchup.currentData() or 0), int(self.taper.value()) if end else 0
        if (c, t) != (int(ph.get("catchup") or 0), int(ph.get("taper") or 0)):
            out.append({"op": "set_phases", "catchup": c, "taper": t})
        return out

    def _said(self):
        if self._loading:
            return
        self.end_day.setVisible(self.ends.currentData()[0] == "day")
        self.daily.setVisible(self._mode_key() == "daily")
        self.taper.setEnabled(bool(self._end()))
        ops = self.ops()
        self.go.setEnabled(bool(ops))
        mark(self.preview, "dc", "warm" if ops else "strip")
        if not ops:
            self.preview_words.setText(esc("Nothing changed yet."))
            return
        doc, ctx, said = self.doc, self.win.ctx(), []
        try:
            after = doc
            for o in ops:
                o = O.check(after, o)
                after, _e, _t = O.apply(after, o, ctx)
        except E.Refused as e:
            self.preview_words.setText(esc(str(e)))
            self.go.setEnabled(False)
            return
        before_days = {u["id"]: u.get("opens") for u in P.units(doc)}
        moved = sum(1 for u in P.units(after) if before_days.get(u["id"]) not in (None, u.get("opens")))
        evs0 = {e.get("id"): e.get("day") for e in doc.get("events") or [] if isinstance(e, dict)}
        ev_moved = sum(1 for e in after.get("events") or [] if isinstance(e, dict) and evs0.get(e.get("id")) not in (None, e.get("day")))
        today = self.win.ops.today()
        opened = sum(1 for u in P.units(doc) if str(u.get("opens")) <= today and before_days.get(u["id"]) and
                     any(x["id"] == u["id"] and x.get("opens") != u.get("opens") for x in P.units(after)))
        if moved or ev_moved:
            bits = [f"{moved:,} date{'s' if moved != 1 else ''}" if moved else "",
                    f"{ev_moved:,} quiz{'zes' if ev_moved != 1 else ''} or exam{'s' if ev_moved != 1 else ''}" if ev_moved else ""]
            said.append(f"Saving moves <b>{esc(' and '.join(b for b in bits if b))}</b>.")
            if opened:
                said.append(esc(f"{opened:,} of them opened already: followers who have their cards keep them."))
        else:
            said.append(esc("No date moves."))
        ph = after.get("phases") or {}
        if int(ph.get("taper") or 0) and after.get("end"):
            n = int(ph["taper"])
            said.append(esc(f"The last {n:,} day{'s' if n != 1 else ''} before {P.fmt_day(after['end'])} have no new cards."))
        if self.win.waiting():
            said.append(esc("It waits with your other changes till you send them."))
        self.preview_words.setText(" ".join(said))

