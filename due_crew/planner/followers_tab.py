"""Round five's Followers tab (docs/planner.md; Progress and Updates
before): how many follow the plan, whose Anki has the last send, how far
the class is on each date (its squad's counts, three sharing or more,
never a name), the dates most of them haven't finished with Push the
dates still to come a day later (a change, waiting with the others), and
the posts: what the authors said to followers, and a line to them. The
counts come with the plan's load (one request); the posts when shown."""

from aqt.qt import QHBoxLayout, QProgressBar, QScrollArea, Qt, QVBoxLayout, QWidget

from ..ui import confirm, role
from .. import plans as P
from .. import schedule as S
from . import edits as E
from .history_tab import UpdatesTab
from .widgets import frame, plain


class FollowersTab(QWidget):
    """One plan's followers, for its authors. win: the PlanWindow."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 8, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        scroll.viewport().setAutoFillBackground(False)
        body.setAutoFillBackground(False)
        root = QVBoxLayout(body)
        root.setContentsMargins(0, 0, 12, 0)
        root.setSpacing(8)
        self.head = role(plain(), "title")
        root.addWidget(self.head)
        self.reached = plain(muted=True)
        root.addWidget(self.reached)
        self.counts = QWidget()
        self.counts_lay = QVBoxLayout(self.counts)
        self.counts_lay.setContentsMargins(0, 0, 0, 0)
        self.counts_lay.setSpacing(4)
        root.addWidget(self.counts)
        self.said = plain(muted=True)
        root.addWidget(self.said)
        self.hints = QWidget()
        self.hints_lay = QVBoxLayout(self.hints)
        self.hints_lay.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.hints)
        root.addSpacing(8)
        root.addWidget(role(plain("Posts"), "head"))
        self.posts = UpdatesTab(win)
        root.addWidget(self.posts)
        root.addStretch(1)

    def shown(self, win):
        return win.author()

    def plan_loaded(self, win):
        if not win.author():
            return
        n = win.followers()
        self.head.setText(f"{n:,} following" if n else "Nobody follows it yet")
        r = (win.raw or {}).get("reached") or [0, 0]
        self.reached.setText(f"Your last save is in {int(r[0]):,} of {int(r[1]):,} followers' Anki."
                             if isinstance(r, list) and len(r) == 2 and r[1] else
                             "Share its code (Sharing) and each date's counts show here once three or more are in its squad."
                             if not n else "")
        self.reached.setVisible(bool(self.reached.text()))
        self.posts.plan_loaded(win)
        self.progress_in(win)

    def busy_changed(self, win):
        self.posts.busy_changed(win)

    def _clear(self, lay):
        while lay.count():
            it = lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.hide()
                w.deleteLater()
            elif it.layout() is not None:
                self._clear(it.layout())

    def progress_in(self, win):
        """The squad's counts a date, and the dates behind, as the plan's load read them."""
        self._clear(self.counts_lay)
        self._clear(self.hints_lay)
        pr, n = win.progress, win.followers()
        if not n:
            self.said.setText("")
            self.said.setVisible(False)
            return
        if pr is None:
            self.said.setText("Loading how far they are…")
            self.said.setVisible(True)
            return
        sharing = int(pr.get("sharing") or 0)
        self.said.setVisible(True)
        if sharing < 3:
            self.said.setText(f"{sharing:,} of them {'is' if sharing == 1 else 'are'} in its squad. "
                              "Each date's counts show once 3 or more are (never a name).")
            return
        self.said.setText(f"Counts from the {sharing:,} of the {n:,} in its squad, never a name.")
        doc, today = win.doc or {}, win.ops.today()
        for u in sorted(P.units(doc), key=lambda u: str(u.get("opens"))):
            if str(u.get("opens")) > today:
                continue
            c = (pr.get("units") or {}).get(u["id"]) or {}
            done = int(c.get("done") or 0)
            row = QHBoxLayout()
            name = plain(f"{P.fmt_day(u['opens'])} · {u.get('name') or '?'}")
            name.setFixedWidth(220)
            row.addWidget(name)
            bar = QProgressBar()
            bar.setRange(0, sharing)
            bar.setValue(min(done, sharing))
            bar.setTextVisible(False)
            bar.setFixedHeight(8)
            row.addWidget(bar, 1)
            n_done = plain(f"{done:,} of {sharing:,} done", muted=True)
            n_done.setWordWrap(False)
            row.addWidget(n_done)
            self.counts_lay.addLayout(row)
        later = [u for u in P.units(doc) if str(u.get("opens")) > today]
        for u, done, late in E.behind(doc, pr, today):
            f, lay = frame("warm")
            lay.addWidget(plain(f"{P.fmt_day(u['opens'])} · {u.get('name') or '?'}: {sharing - done:,} of {sharing:,} "
                                f"haven't finished it, {late:,} day{'s' if late != 1 else ''} on."))
            if later:
                from aqt.qt import QPushButton
                b = QPushButton("Push the dates still to come a day later…")
                b.setAutoDefault(False)
                b.clicked.connect(self._breather)
                lay.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)
            self.hints_lay.addWidget(f)

    def _breather(self):
        win = self.win
        if not confirm(self, "Push the dates still to come a day later?",
                       "Every date still to come moves one study day later; quizzes and exams stay on their days."
                       + (" It waits with your other changes till you send them." if win.waiting() else ""), "Push them"):
            return
        win.change({"op": "breather", "today": win.ops.today(), "days": S.plan_days(win.doc)})
