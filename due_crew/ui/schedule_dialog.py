"""3.2, my schedule for a plan: when I start, the days I study (a day
tapped again takes a double share, again is a rest day), my time a day,
and the load that makes: reviews a day, week by week, against my time.
Pure Qt over schedule.py; the caller saves it (one PATCH). The plan's name
is the author's, so it goes only where Qt shows plain text."""

import datetime

from aqt.qt import (
    QButtonGroup, QColor, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QPainter, QPushButton, QRadioButton, QSizePolicy, Qt, QVBoxLayout, QWidget,
)

from . import attach_alive
from .. import schedule as S

DAY_NAMES = ("M", "T", "W", "T", "F", "S", "S")
MINUTES = (30, 45, 60, 90, 120, 180)
DEFAULT = {"days": [1, 1, 1, 1, 1, 1, 0], "minutes": 60}


class LoadChart(QWidget):
    """Reviews a day, by week: bars, the ones over my time in amber, and my
    time as a dashed line. Labels every other week when crowded."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = None
        self.setMinimumHeight(130)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_view(self, view):
        self.view = view
        self.update()

    def paintEvent(self, _event):
        v = self.view
        if not v or not v.get("weeks"):
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = self.palette()
        ink = pal.color(pal.ColorRole.WindowText)
        muted = QColor(ink)
        muted.setAlpha(140)
        accent = QColor("#2e7d32") if pal.color(pal.ColorRole.Window).lightness() > 128 else QColor("#7cc47f")
        amber = QColor("#b26a00") if pal.color(pal.ColorRole.Window).lightness() > 128 else QColor("#dda45c")
        w, h = self.width(), self.height()
        left, bottom, top = 4, 18, 18
        weeks = v["weeks"]
        top_v = max(max(x for _l, x, _o in weeks), v["cap"], 1) * 1.1
        y = lambda val: top + (h - top - bottom) * (1 - val / top_v)
        slot = (w - left - 4) / len(weeks)
        bw = max(3.0, slot - 4)
        f = p.font()
        f.setPointSizeF(max(7.0, f.pointSizeF() - 2))
        p.setFont(f)
        for i, (label, val, over) in enumerate(weeks):
            x = left + i * slot + (slot - bw) / 2
            p.fillRect(int(x), int(y(val)), int(bw), int(y(0) - y(val)), amber if over else accent)
            if len(weeks) <= 16 or i % 2 == 0:
                p.setPen(muted)
                p.drawText(int(x - 4), h - 4, label)
        p.setPen(ink)
        cap_text = f"your {v.get('minutes', 60)} min ≈ {v['cap']:,}"
        tw = p.fontMetrics().horizontalAdvance(cap_text)
        p.drawText(w - 4 - tw, max(10, int(y(v["cap"])) - 4), cap_text)
        pen = p.pen()
        pen.setColor(ink)
        pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawLine(left, int(y(v["cap"])), w - 4, int(y(v["cap"])))
        p.end()


class ScheduleDialog(QDialog):
    def __init__(self, parent, plan, today, totals, base_due, pace):
        super().__init__(parent)
        attach_alive(self)
        self.plan, self.today = plan, S.d(today)
        self.totals, self.base, self.pace = totals, base_due, pace
        have = plan.get("sched") or DEFAULT
        self.days = list(have["days"])
        self.setWindowTitle(f"My schedule · {plan.get('name') or 'Plan'}")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)

        first = S.plan_start(plan["doc"]) or self.today
        lay.addWidget(self._label("Start"))
        self.with_plan = QRadioButton(f"With the plan, {first:%a} {first.day} {first:%b}")
        self.later = QRadioButton("Later:")
        grp = QButtonGroup(self)
        grp.addButton(self.with_plan)
        grp.addButton(self.later)
        self.start = QDateEdit()
        self.start.setCalendarPopup(True)
        self.start.setDisplayFormat("ddd d MMM yyyy")
        start = S.d(have["start"]) if have.get("start") else max(self.today, first)
        self.start.setDate(start)
        row = QHBoxLayout()
        row.addWidget(self.later)
        row.addWidget(self.start)
        row.addStretch(1)
        (self.later if have.get("start") else self.with_plan).setChecked(True)
        lay.addWidget(self.with_plan)
        lay.addLayout(row)

        lay.addWidget(self._label("Days I study"))
        days_row = QHBoxLayout()
        self.day_buttons = []
        for i, name in enumerate(DAY_NAMES):
            b = QPushButton(name)
            b.setFixedWidth(34)
            b.clicked.connect(lambda _c=False, i=i: self._tap(i))
            self.day_buttons.append(b)
            days_row.addWidget(b)
        days_row.addStretch(1)
        lay.addLayout(days_row)
        self.days_hint = QLabel()
        self.days_hint.setTextFormat(Qt.TextFormat.PlainText)
        self.days_hint.setStyleSheet("font-size: 11px;")
        lay.addWidget(self.days_hint)

        lay.addWidget(self._label("Time a day"))
        self.minutes = QComboBox()
        for m in MINUTES:
            self.minutes.addItem(f"{m} min" if m < 60 or m % 60 else f"{m // 60} h", m)
        at = min(range(len(MINUTES)), key=lambda i: abs(MINUTES[i] - int(have.get("minutes") or 60)))
        self.minutes.setCurrentIndex(at)
        lay.addWidget(self.minutes)

        self.chart = LoadChart()
        lay.addWidget(self.chart)
        self.summary = QLabel()
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)
        note = QLabel("The plan's dates are the window; your days decide how each one fills. "
                      "Rest days open no new cards. Anki's reviews still come due.")
        note.setTextFormat(Qt.TextFormat.PlainText)
        note.setWordWrap(True)
        note.setStyleSheet("font-size: 11px;")
        lay.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Save")
        self.off = None
        if plan.get("sched"):
            self.off = buttons.addButton("No schedule", QDialogButtonBox.ButtonRole.DestructiveRole)
            self.off.clicked.connect(self._no_schedule)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self._none = False

        for sig in (self.minutes.currentIndexChanged, self.start.dateChanged):
            sig.connect(lambda *_: self._update())
        self.with_plan.toggled.connect(lambda *_: self._update())
        self._update()

    @staticmethod
    def _label(text):
        lab = QLabel(text)
        lab.setStyleSheet("font-weight: 600; margin-top: 6px;")
        return lab

    def _tap(self, i):
        self.days[i] = (self.days[i] + 1) % 3
        if not any(self.days):
            self.days[i] = 1  # at least one study day
        self._update()

    def _no_schedule(self):
        self._none = True
        self.accept()

    def value(self):
        """The schedule to save, or None for none (dates open whole, as in 3.1)."""
        if self._none:
            return None
        out = {"days": list(self.days), "minutes": int(self.minutes.currentData())}
        if self.later.isChecked():
            d = self.start.date()
            start = datetime.date(d.year(), d.month(), d.day())
            first = S.plan_start(self.plan["doc"])
            if first and start > first:
                out["start"] = start.isoformat()
        return out

    def _update(self):
        for b, n in zip(self.day_buttons, self.days):
            b.setText(b.text()[0] + ("×2" if n == 2 else ""))
            b.setFixedWidth(46 if n == 2 else 34)
            b.setStyleSheet("" if n else "color: palette(mid);")
            b.setToolTip(("Rest day", "Study day", "Double share")[n] + ". Click to change.")
        rest = [DAY_NAMES[i] for i, n in enumerate(self.days) if n == 0]
        double = [DAY_NAMES[i] for i, n in enumerate(self.days) if n == 2]
        self.days_hint.setText(" ".join(filter(None, [
            f"{len(double)} day{'s' if len(double) != 1 else ''} take a double share." if double else "",
            f"{len(rest)} rest day{'s' if len(rest) != 1 else ''}." if rest else "",
            "Click a day to change it."])))
        sched = self.value() or DEFAULT
        secs_review, secs_new = self.pace
        view = S.load_view(self.plan["doc"], sched, self.totals, self.today, self.base, secs_review, secs_new)
        self.chart.set_view(view)
        if not view or not any(self.totals.values()):
            self.summary.setText("None of this plan's cards are in the deck it runs on here yet.")
            return
        text = (f"About {view['new_a_day']:,} new cards a study day. Reviews peak near "
                f"{view['peak']:,} a day.")
        if view["over"]:
            n = len(view["over"])
            fix = "add a study day, or give it more time" if any(k == 0 for k in self.days) else "give it more time a day"
            text += f" {n} week{'s' if n != 1 else ''} go past your {sched['minutes']} min: {fix}."
        self.summary.setText(text)
