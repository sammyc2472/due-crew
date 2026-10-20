"""Round five's Mine tab (docs/planner.md), for a plan I follow: everything
about my follow in one place, where the board's Plan ▾ had it. My dates
(as the plan, or some days later), the dates I skip, how its cards open
(each morning on their dates, or when I'm ready), what Hold back keeps,
its squad, Pause, Make my own copy (a library plan), Stop following; and
under More, Change deck, Open everything now, Open early. Each is
plan_flow's own step (through flow.Ops), one request on a click; the
window reads my follow again once it's taken."""

from aqt.qt import QFormLayout, QHBoxLayout, QPushButton, Qt, QTimer, QVBoxLayout, QWidget

from ..ui import role
from .. import plans as P
from .widgets import Source, link, menu_button, plain


class MineTab(QWidget):
    """My follow of the plan picked. win: the PlanWindow."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.p = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 12, 0, 0)
        root.setSpacing(10)
        self.head = role(plain(), "head")
        root.addWidget(self.head)
        form = QFormLayout()
        form.setVerticalSpacing(10)

        dates = QHBoxLayout()
        dates.setSpacing(0)
        self.as_plan = self._seg("As the plan", lambda: self._shift(False))
        self.later = self._seg("Some days later…", lambda: self._shift(True))
        dates.addWidget(self.as_plan)
        dates.addWidget(self.later)
        dates.addStretch(1)
        form.addRow("My dates", dates)

        skip = QVBoxLayout()
        skip.setSpacing(4)
        self.skips = QWidget()  # a date skipped a line: its day and name, ✕ to stop skipping it
        self.skips_lay = QVBoxLayout(self.skips)
        self.skips_lay.setContentsMargins(0, 0, 0, 0)
        self.skips_lay.setSpacing(0)
        self.skips.setMaximumWidth(420)  # its ✕ by the name, not across the window
        skip.addWidget(self.skips)
        self.skip_btn, self.skip_menu = menu_button("Skip a date", self._skip_entries, small=True)
        skip.addWidget(self.skip_btn, 0, Qt.AlignmentFlag.AlignLeft)
        form.addRow("Skipping", skip)

        opens = QHBoxLayout()
        opens.setSpacing(0)
        self.on_dates = self._seg("Each morning, on their dates", lambda: self._own(""))
        self.ready = self._seg("When I'm ready", lambda: self._own("ready"))
        self.ready.setToolTip("<span>Up next on the board opens the next date's cards when you say</span>")
        opens.addWidget(self.on_dates)
        opens.addWidget(self.ready)
        opens.addStretch(1)
        form.addRow("Cards open", opens)

        self.held = link("", lambda: self._do("show_held"))
        self.held_none = plain("Nothing held back.", muted=True)
        held = QHBoxLayout()
        held.addWidget(self.held)
        held.addWidget(self.held_none)
        held.addStretch(1)
        form.addRow("Held back", held)

        self.squad = plain(muted=True)
        form.addRow("Squad", self.squad)
        root.addLayout(form)

        row = QHBoxLayout()
        self.pause_btn = QPushButton("Pause until…")
        self.pause_btn.setAutoDefault(False)
        self.pause_btn.clicked.connect(self._pause)
        row.addWidget(self.pause_btn)
        self.copy_btn = QPushButton("Make my own copy")
        self.copy_btn.setAutoDefault(False)
        self.copy_btn.clicked.connect(self._copy)
        row.addWidget(self.copy_btn)
        self.more_btn, self.more_menu = menu_button("More", self._more)
        row.addWidget(self.more_btn)
        row.addStretch(1)
        row.addWidget(link("Stop following…", lambda: self._do("stop_following"), bad=True))
        root.addLayout(row)
        self.said = plain(muted=True)
        root.addWidget(self.said)
        root.addStretch(1)

    def _seg(self, label, fn):
        b = QPushButton(label)
        b.setProperty("dc", "seg")
        b.setCheckable(True)
        b.setAutoDefault(False)
        b.clicked.connect(lambda _=False: fn())
        return b

    # ---- the window asks ----

    def shown(self, win):
        return bool(win.plan) and not win.author()

    def plan_loaded(self, win):
        if not self.shown(win):
            return
        self.p = win.ops.follow_state(win.plan["id"])
        p = self.p or {}
        if not p:
            self.head.setText("You don't follow it on this account any more.")
            return
        self.head.setText(f"Following {p.get('name') or 'the plan'}" + (", paused" if p.get("paused") else ""))
        shift = int(p.get("shift") or 0)
        self.as_plan.setChecked(not shift)
        self.later.setChecked(bool(shift))
        self.later.setText(f"{shift:,} day{'s' if shift != 1 else ''} later" if shift else "Some days later…")
        while self.skips_lay.count():
            w = self.skips_lay.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.deleteLater()
        names = {u["id"]: u for u in P.units(win.plan.get("doc") or {})}
        for uid in p.get("skipped") or []:
            u = names.get(uid)
            self.skips_lay.addWidget(Source(f"{P.fmt_day(u['opens'])} · {u.get('name') or '?'}" if u else "a date taken off",
                                            on_take=lambda uid=uid: self._do("set_skip", uid, False)))
        self.skips.setVisible(self.skips_lay.count() > 0)
        own = p.get("own") or ""
        self.on_dates.setChecked(not own)
        self.ready.setChecked(bool(own))
        n = win.ops.held_count(win.plan["id"])
        self.held.setText(f"{n:,} card{'s' if n != 1 else ''} kept shut till their day…" if n else "")
        self.held.setVisible(bool(n))
        self.held_none.setVisible(not n)
        inside = win.ops.in_team(win.plan["id"])
        self.squad.setText("You're in it" if inside else "Not in it: join from the board's Squads tab")
        self.squad.setToolTip("<span>Its squad sees that you showed up, never your numbers</span>" if inside else "")
        self.pause_btn.setText("Resume" if p.get("paused") else "Pause until…")
        self.copy_btn.setVisible(bool(win.plan.get("listed")))

    # ---- what each does ----

    def _do(self, what, *args):
        pid = self.win.plan["id"]
        getattr(self.win.ops, what)(pid, *args)
        QTimer.singleShot(1800, self._again)

    def _again(self):
        """My follow read again once a step's request is likely back: the window loads it afresh when my dates moved."""
        if self.win.plan is None or self.win.author():
            return
        was = dict(self.p or {})
        self.plan_loaded(self.win)
        now = self.p or {}
        if any(was.get(k) != now.get(k) for k in ("shift", "skipped", "moved", "paused", "own")):
            self.win._load()

    def _shift(self, later):
        self.plan_loaded(self.win)  # the segment shows what's so until it's changed
        if later or int((self.p or {}).get("shift") or 0):
            self._do("set_shift")

    def _own(self, own):
        self.plan_loaded(self.win)
        if (self.p or {}).get("own", "") != own:
            self._do("set_own", own)

    def _skip_entries(self):
        self.skip_menu.clear()
        p = self.p or {}
        today = self.win.ops.today()
        have = set(p.get("skipped") or [])
        ahead = [u for u in sorted(P.units(self.win.plan.get("doc") or {}), key=lambda u: str(u.get("opens") or ""))
                 if str(u.get("opens") or "") >= today and u["id"] not in have][:20]
        for u in ahead:
            a = self.skip_menu.addAction(f"{P.fmt_day(u['opens'])} · {u.get('name') or '?'}")
            a.triggered.connect(lambda _=False, uid=u["id"]: self._do("set_skip", uid, True))
        if not ahead:
            self.skip_menu.addAction("No date ahead to skip").setEnabled(False)

    def _pause(self):
        self._do("resume" if (self.p or {}).get("paused") else "pause_until")

    def _copy(self):
        self.win.ops.copy_plan(self.win, self.win.plan["id"], lambda words: self.said.setText(words))

    def _more(self):
        m = self.more_menu
        m.clear()
        m.addAction("Change deck…").triggered.connect(lambda: self._do("change_deck"))
        m.addAction("Open everything now").triggered.connect(lambda: self._do("open_everything"))
        early = m.addMenu("Open early")
        now = int((self.p or {}).get("early") or 0)
        for n, label in ((0, "Off"), (1, "1 day"), (2, "2 days"), (3, "3 days"), (5, "5 days"), (7, "7 days")):
            a = early.addAction(label)
            a.setCheckable(True)
            a.setChecked(now == n)
            a.triggered.connect(lambda _=False, n=n: self._do("set_early", n))
        early.setEnabled(not (self.p or {}).get("own"))
