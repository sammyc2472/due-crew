"""Round five's Followers tab (docs/planner.md): how many follow the plan,
whose Anki has the last send, and the posts: what the authors said to
followers, and a line to them (the posts when shown). How far each
follower is isn't here (Sam's call: it added nothing); what followers do
together is the plan's squad, on the board's Squads tab."""

from aqt.qt import QScrollArea, Qt, QVBoxLayout, QWidget

from ..ui import role
from .history_tab import UpdatesTab
from .widgets import plain


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
                             "Share its code from Sharing." if not n else "")
        self.reached.setVisible(bool(self.reached.text()))
        self.posts.plan_loaded(win)

    def busy_changed(self, win):
        self.posts.busy_changed(win)
