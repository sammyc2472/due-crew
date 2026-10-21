"""Round five's Plan tab (docs/planner.md): one screen to build a plan, or
to follow one. For its authors: the plan's shape in one line (Change…),
Today · Needs a look · Expand all / Collapse all, the weeks with what each asks (new
cards and reviews a day; amber, with its fixes, when a day is over the
pace), a line at today, each date with its cards as chips (no
suggestions of what goes on one: the author puts every card there, Sam's
call), the picked date or the deck beside them, a box to paste plan lines or a course calendar into, the
plan as text, a prompt for your own AI, and the changes waiting to be
sent. For a follower: today's date with Study now, what's behind, and the
same weeks to read. List or Month.

Every change is an op through the window (PlanWindow.change). Names are
the deck's and the authors': plain text everywhere, escaped in rich text."""

from aqt.qt import (
    QApplication, QDate, QFrame, QGridLayout, QHBoxLayout, QKeySequence, QLineEdit, QPlainTextEdit, QPushButton,
    QScrollArea, QShortcut, QSizePolicy, QSplitter, QStackedWidget, Qt, QTimer, QVBoxLayout, QWidget,
)

from ..ui import ask_text, confirm, esc, role, tone
from .. import plans as P
from . import build as B
from . import date_dialogs as DD
from . import edits as E
from . import model as M
from . import view as V
from .date_panel import DatePanel, EventPanel, ReviewPanel, chip_name
from .deck_panel import DeckPanel
from .widgets import DayCell, Elided, Row, flow_box, frame, keys, link, mark, menu_button, plain, segs, tip_keys, tool


def _scroll(widget):
    s = QScrollArea()
    s.setWidgetResizable(True)
    s.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    s.setFrameShape(QFrame.Shape.NoFrame)
    s.setWidget(widget)
    s.viewport().setAutoFillBackground(False)
    widget.setAutoFillBackground(False)
    return s


class PasteBox(QPlainTextEdit):
    """One line until something's pasted in; then tall enough to see it."""

    def __init__(self, on_change):
        super().__init__()
        self.setTabChangesFocus(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setPlaceholderText("Paste plan lines or a new course calendar")
        self.textChanged.connect(lambda: (self._size(), on_change()))
        self._size()

    def _size(self):
        lines = self.toPlainText().count("\n") + 1
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff if lines <= 1 else Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFixedHeight(36 if lines <= 1 else min(160, 24 + 18 * lines))


class PlanTab(QWidget):
    """One plan's Plan tab. win: the PlanWindow."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.picked = None          # ("date", id) | ("event", id) | ("review", day)
        self.open_weeks = set()     # weeks opened (or closed) by hand, by their Monday
        self.closed_weeks = set()
        self.all_open = None        # Expand all (True), Collapse all (False), or as it opens (None: past weeks collapsed)
        self.only_look = False
        self.mode = "list"
        self.desc = False           # List: latest date first
        self.month = None           # the month Month shows (its first day)
        self.look, self.asks, self.counts = {}, {}, {}
        self.rows = {}              # key -> Row, as drawn
        self.pid = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 8, 0, 0)
        root.setSpacing(8)

        # a follower's today, and what's behind: a line each, its button at the end
        self.today_box, tl = frame("line", horizontal=True, margins=(2, 0, 0, 0))
        self.today_head = plain("Today", dc="ok")
        self.today_head.setWordWrap(False)
        tl.addWidget(self.today_head)
        self.today_words = plain()
        tl.addWidget(self.today_words, 1)
        self.today_go = QPushButton("Study now")
        self.today_go.setProperty("dc", "go")
        self.today_go.setAutoDefault(False)
        self.today_go.clicked.connect(self._study_today)
        tl.addWidget(self.today_go)
        root.addWidget(self.today_box)
        self.behind_box, bl = frame("line", horizontal=True, margins=(2, 0, 0, 0))
        self.behind_head = plain("Behind", dc="warn")
        self.behind_head.setWordWrap(False)
        bl.addWidget(self.behind_head)
        self.behind_words = plain()
        bl.addWidget(self.behind_words, 1)
        self.behind_go = QPushButton("Study what's left")
        self.behind_go.setAutoDefault(False)
        self.behind_go.clicked.connect(self._study_behind)
        bl.addWidget(self.behind_go)
        root.addWidget(self.behind_box)

        # an author's shape: what it covers, by when, how fast, each its own label and value
        self.shape_box, sl = frame("line", horizontal=True, margins=(2, 0, 0, 0), spacing=12)
        self.shape_fields, self.shape_lay = flow_box(18, 2)
        sl.addWidget(self.shape_fields, 1, Qt.AlignmentFlag.AlignVCenter)
        self.shape_box.setToolTip("<span>Its dates and pace are in Settings</span>")
        root.addWidget(self.shape_box)

        # the toolbar, over the list it acts on: List or Month first, find, today, what needs a look, the weeks; Add
        bar = QHBoxLayout()
        bar.setSpacing(6)
        views = QHBoxLayout()
        views.setSpacing(0)
        self.list_btn = QPushButton("List")
        self.month_btn = QPushButton("Month")
        for b, m, seq in ((self.list_btn, "list", "Ctrl+1"), (self.month_btn, "month", "Ctrl+2")):
            b.setProperty("dc", "seg")
            b.setCheckable(True)
            b.setAutoDefault(False)
            b.setToolTip(tip_keys(m.capitalize(), seq))
            b.clicked.connect(lambda _=False, m=m: self._mode(m))
            views.addWidget(b)
        segs([self.list_btn, self.month_btn])
        bar.addLayout(views)
        self.sort_btn = tool("Earliest first", self._toggle_sort, tip="The list's order: earliest date first, or latest first")
        bar.addWidget(self.sort_btn)
        bar.addSpacing(6)
        self.find = QLineEdit()
        self.find.setPlaceholderText("Find a date or tag")
        self.find.setClearButtonEnabled(True)
        self.find.setToolTip(tip_keys("Only the dates whose name or cards have these words; Enter picks the first", "Ctrl+F"))
        self.find.setMaximumWidth(180)
        self.find.textChanged.connect(self._found)
        self.find.returnPressed.connect(self._find_first)
        QShortcut(QKeySequence("Escape"), self.find, context=Qt.ShortcutContext.WidgetShortcut,
                  activated=lambda: self.find.clear() if self.find.text() else self.views.currentWidget().setFocus())
        bar.addWidget(self.find)
        self.today_btn = tool("Today", self._go_today, tip="The date open today, or the next one", seq="Ctrl+T")
        self.look_btn = tool("Needs a look", self._toggle_look, checkable=True,
                             tip="Only the weeks with a date that has no cards here, or a day over the pace")
        self.all_btn = tool("Expand all", self._toggle_all, tip="Every week expanded, or every week collapsed")
        for w in (self.today_btn, self.look_btn, self.all_btn):
            bar.addWidget(w)
        self.add_btn, self.add_menu = menu_button("Add", small=True)
        for label, fn, seq in (("A date…", self.new_date, "Ctrl+N"), ("A quiz or exam…", lambda: self.new_event(), "Ctrl+E"),
                               ("A review day…", self.new_review, None)):
            a = self.add_menu.addAction(label + (f"\t{keys(seq)}" if seq else ""))
            a.triggered.connect(lambda _=False, fn=fn: fn())
        self.add_menu.addSeparator()
        self.lay_act = self.add_menu.addAction("Lay out from the deck…")  # ticks what the plan covers; laid out at its pace
        self.lay_act.triggered.connect(lambda: self.lay_out_view())
        bar.addWidget(self.add_btn)
        bar.addStretch(1)  # all of it over the list; the date beside it has its own
        root.addLayout(bar)

        # the plan, and beside it the picked date or the deck
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        left, ll = frame("card", margins=(4, 4, 4, 4))
        self.left = left
        self.views = QStackedWidget()
        self.list_body = QWidget()
        self.list_scroll = _scroll(self.list_body)
        self.views.addWidget(self.list_scroll)
        self.month_body = QWidget()
        self.month_page = _scroll(self.month_body)  # a month never makes the window taller than its screen
        self.views.addWidget(self.month_page)
        for v in (self.list_scroll, self.month_page):
            v.setFocusPolicy(Qt.FocusPolicy.StrongFocus)  # its keys: ↑ ↓, a day earlier or later, its name, delete
        ll.addWidget(self.views)
        split.addWidget(left)
        right, rl = frame("card", margins=(0, 0, 0, 0))
        self.side = QStackedWidget()  # the picked date (or quiz, or review day); the deck while cards go on from it
        self.panels = QStackedWidget()
        self.date_panel = DatePanel(win, self)
        self.event_panel = EventPanel(win, self)
        self.review_panel = ReviewPanel(win, self)
        self.none_panel = QWidget()
        nl = QVBoxLayout(self.none_panel)
        nl.setContentsMargins(12, 12, 12, 12)
        self.none_words = plain("Pick a date on the left to see its cards here.", muted=True)
        nl.addWidget(self.none_words)
        nl.addStretch(1)
        for p in (self.date_panel, self.event_panel, self.review_panel, self.none_panel):
            self.panels.addWidget(p)
        self.side_page = _scroll(self.panels)
        self.side.addWidget(self.side_page)
        self.deck = DeckPanel(win, self)
        self.side.addWidget(self.deck)
        rl.addWidget(self.side)
        split.addWidget(right)
        split.setStretchFactor(0, 5)
        split.setStretchFactor(1, 4)
        split.setSizes([540, 420])
        root.addWidget(split, 1)

        # paste, the plan as text, a prompt for your own AI
        self.paste_row = QWidget()
        pr = QHBoxLayout(self.paste_row)
        pr.setContentsMargins(0, 0, 0, 0)
        self.paste = PasteBox(self._paste_changed)
        pr.addWidget(self.paste, 1)
        self.paste_go = QPushButton("Show the changes")
        self.paste_go.setAutoDefault(False)
        self.paste_go.clicked.connect(self._show_changes)
        pr.addWidget(self.paste_go, 0, Qt.AlignmentFlag.AlignTop)
        self.text_btn = QPushButton("The plan as text")
        self.text_btn.setAutoDefault(False)
        self.text_btn.setToolTip("<span>Every date, quiz and tag as plan lines, to read or edit</span>")
        self.text_btn.clicked.connect(lambda: self.text(True))
        pr.addWidget(self.text_btn, 0, Qt.AlignmentFlag.AlignTop)
        self.ai_btn, self.ai_menu = menu_button("AI prompt", self._ai_entries,
                                                tip="Copied for you to paste in your own AI; it gets tag names and counts, never a card")
        pr.addWidget(self.ai_btn, 0, Qt.AlignmentFlag.AlignTop)
        root.addWidget(self.paste_row)

        # the changes waiting to be sent: the window's foot, each change a link to its date
        self.send_box, xl = frame("foot", horizontal=True, margins=(2, 8, 0, 0))
        self.send_words = plain()
        self.send_words.setTextFormat(Qt.TextFormat.RichText)  # names escaped; each change a link to its date
        self.send_words.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.send_words.linkActivated.connect(self._go_change)
        xl.addWidget(self.send_words, 1)
        xl.addWidget(tool("Discard", lambda: self.win.discard(), tip="Take every change not sent back; nobody saw them"))
        self.send_go = QPushButton("Review and send")
        self.send_go.setProperty("dc", "go")
        self.send_go.setAutoDefault(False)
        self.send_go.setToolTip(tip_keys("Every change waiting, and a line for followers", "Ctrl+Return"))
        self.send_go.clicked.connect(lambda: self.win.review_send())
        xl.addWidget(self.send_go)
        root.addWidget(self.send_box)
        self._keys()

    def _keys(self):
        """The Plan tab's keys: anywhere in it (Ctrl+…), and on the plan
        itself (the list or Month in focus: ↑ ↓, Alt+← →, Enter, Delete)."""
        here = Qt.ShortcutContext.WidgetWithChildrenShortcut

        def on(seq, fn, where=None):
            QShortcut(QKeySequence(seq), where or self, context=here, activated=fn)
        on("Ctrl+N", lambda: self._author() and self.new_date())
        on("Ctrl+E", lambda: self._author() and self.new_event())
        on("Ctrl+F", self._focus_find)
        on("Ctrl+T", self._go_today)
        on("Ctrl+1", lambda: self._mode("list"))
        on("Ctrl+2", lambda: self._mode("month"))
        on("Ctrl+D", self._deck_key)
        on("Ctrl+Return", lambda: self.win.review_send() if self.send_box.isVisible() and self.send_go.isEnabled() else None)
        on("Ctrl+Enter", lambda: self.win.review_send() if self.send_box.isVisible() and self.send_go.isEnabled() else None)
        on("Ctrl+Z", lambda: self.win.undo_key())
        for v in (self.list_scroll, self.month_page):
            on("Up", lambda: self.step(-1), v)
            on("Down", lambda: self.step(1), v)
            on("Alt+Left", lambda: self.nudge(-1), v)
            on("Alt+Right", lambda: self.nudge(1), v)
            on("Return", lambda: self.name_it(self.picked), v)
            on("Enter", lambda: self.name_it(self.picked), v)
            on("F2", lambda: self.name_it(self.picked), v)
            on("Delete", self.delete_picked, v)
            on("Backspace", self.delete_picked, v)

    def _author(self):
        return self.win.doc is not None and self.win.author() and not self.win.busy

    # ---- the window asks ----

    def shown(self, win):
        return True

    def plan_loaded(self, win):
        doc = win.doc
        if doc is None:
            for w in (self.today_box, self.behind_box, self.shape_box, self.paste_row, self.send_box):
                w.hide()
            self.picked = None
            self._draw_list([])
            self._show_side()
            return
        if (win.plan or {}).get("id") != self.pid:
            self.pid = (win.plan or {}).get("id")
            self.open_weeks, self.closed_weeks, self.all_open, self.only_look = set(), set(), None, False
            self.picked, self.month = None, None
            self.deck.target = None
            self.side.setCurrentWidget(self.side_page)
        self._work_out()
        self.date_panel.day_notes.plan_loaded(win.plan["id"], (win.raw or {}).get("library") is True)
        keep = win.keep
        win.keep = None
        if keep == ("gone",):
            self.picked = None
        elif keep is not None:
            self.picked = tuple(keep)
        if self.picked and not self._exists(self.picked):
            self.picked = None
        if (win.plan or {}).get("id") != getattr(self, "_found_for", None):
            self._found_for = (win.plan or {}).get("id")
            self.find.blockSignals(True)
            self.find.clear()
            self.find.blockSignals(False)
        if self.picked is None:
            u, _now = V.today_date(doc, win.ops.today())
            us = P.units(doc)
            u = u or (sorted(us, key=lambda x: str(x.get("opens")))[-1] if us else None)
            self.picked = ("date", u["id"]) if u else None
        self._strips()
        self._draw()
        self._show_side()
        self.deck.plan_loaded(win)
        self.busy_changed(win)

    def forget(self):
        self.date_panel.day_notes.forget()

    def busy_changed(self, win):
        idle = not win.busy
        self.send_go.setEnabled(idle)
        self._paste_changed()
        self.date_panel.busy_changed()
        self.event_panel.busy_changed()
        self.review_panel.busy_changed()
        self.deck.busy_changed(win)

    # ---- worked out once a draw ----

    def _work_out(self):
        win, doc = self.win, self.win.doc
        t = win.deck_tree()
        pace = V.pace_of(doc)
        self.asks = V.week_asks(doc, t, pace) if t is not None else {}
        self.counts = {u["id"]: len(win.idx.match(u, win.swap, doc)) for u in P.units(doc)} if win.idx is not None else {}
        self.look = V.needs_look(doc, self.counts, self.asks) if win.author() else {}
        self.heavy = None
        if win.author() and t is not None:
            placed = B.placed_keys(doc, t)
            hv = B.heavy(doc, t, pace, set(pace.get("cover") or []), B.plan_start(doc, win.ops.today()),
                         lambda u: B.unit_total(t, u, placed), win.ops.today())
            if hv:
                hv = dict(hv, big=B.biggest(t, hv["unit"], placed),
                          till=B.give_till(doc, pace.get("days") or [1] * 7, hv["unit"], hv["total"], hv["cap"]))
                self.heavy = hv

    def _exists(self, key):
        kind, k = key[0], key[1] if len(key) > 1 else None
        if kind == "date":
            return self.win.unit(k) is not None
        if kind == "event":
            return self._event(k) is not None
        if kind == "review":
            return self._review(k) is not None
        return False

    def _event(self, eid):
        return next((e for e in (self.win.doc or {}).get("events") or [] if isinstance(e, dict) and e.get("id") == eid), None)

    def _review(self, day):
        return next((r for r in (self.win.doc or {}).get("reviews") or [] if isinstance(r, dict) and r.get("day") == day), None)

    # ---- the strips on top ----

    def _strips(self):
        win, doc, today = self.win, self.win.doc, self.win.ops.today()
        author = win.author()
        self.shape_box.setVisible(author)
        if author:
            self.shape_lay.clear()
            for label, value in V.shape_line(doc, win.deck_tree(), V.pace_of(doc), self.asks):
                pair = QWidget()
                pl = QHBoxLayout(pair)
                pl.setContentsMargins(0, 0, 0, 0)
                pl.setSpacing(6)
                for w in (plain(label, muted=True), plain(value)):
                    w.setWordWrap(False)
                    pl.addWidget(w)
                self.shape_lay.addWidget(pair)
        self.paste_row.setVisible(author)
        self.add_btn.setVisible(author)
        n = len(win.draft) if win.draft else 0
        self.send_box.setVisible(author and n > 0)
        if n:
            said = []
            for c in win.draft.replay(win.ctx())[1][:3]:
                x = (c["entries"] or [{}])[0]
                what = x.get("what") or ""
                words = esc(f"{what.partition(' · ')[2] or what} {str(x.get('verb') or 'changed').lower()}")
                go = next((k for k in c["touched"] if win.unit(k) is not None or self._event(k) is not None), None)
                said.append(f'<a href="{esc(go)}" style="color: {tone("accent")}; text-decoration: none">{words}</a>' if go else words)
            more = n - len(said)
            self.send_words.setText(f"<b>{n:,} change{'s' if n != 1 else ''} not sent:</b> " + ", ".join(said)
                                    + (f", and {more:,} more" if more > 0 else ""))
        # today, for anyone who studies it here; what's behind, for a follower
        u, now = V.today_date(doc, today)
        studies = not author or win.own_steps()
        self.today_box.setVisible(studies and u is not None)
        self._today = u if now else None
        if u is not None and studies:
            name = str(u.get("name") or "?")
            if now and win.idx is not None:
                c = M.counts(win.idx, win.idx.match(u, win.swap, doc))
                self.today_head.setText("Today")
                self.today_words.setText(f"{name}, {c['new']:,} new of {c['cards']:,}")
            elif now:
                self.today_head.setText("Today")
                self.today_words.setText(name)
            else:
                self.today_head.setText("Next")
                self.today_words.setText(f"{P.fmt_day(u['opens'])}, {name}")
            self.today_go.setVisible(bool(now))
        behind = []
        if not author and win.idx is not None:
            for x in sorted(P.units(doc), key=lambda x: str(x.get("opens"))):
                if str(x.get("due") or x.get("opens")) < today:
                    c = M.counts(win.idx, win.idx.match(x, win.swap, doc))
                    if c["new"]:
                        behind.append((x, c["new"]))
        self._behind = behind
        self.behind_box.setVisible(bool(behind))
        if behind:
            left = sum(n for _x, n in behind)
            names = ", ".join(f"{M.day_words(x['opens'])} {x.get('name') or '?'}" for x, _n in behind[:2])
            more = f", and {len(behind) - 2:,} more" if len(behind) > 2 else ""
            self.behind_words.setText(f"{names}{more}: {left:,} card{'s' if left != 1 else ''} not seen yet")
            self.behind_go.setText(f"Study the {left:,}")

    def _go_change(self, key):
        """A change in the foot clicked: its date (or quiz), picked."""
        if self.win.unit(key) is not None:
            self.pick(("date", key))
        elif self._event(key) is not None:
            self.pick(("event", key))
        row = self.rows.get(self.picked) if self.picked else None
        if row is not None and self.mode == "list":
            self.list_scroll.ensureWidgetVisible(row, 0, 80)

    def _study_today(self):
        u = self._today
        if u is None:
            return
        if self.win.own_steps():
            self.win.study("date", u["id"])
        else:
            self.win.study("date", u["id"], self.win.idx.match(u, self.win.swap, self.win.doc) if self.win.idx else set(),
                           str(u.get("name") or "today"))

    def _study_behind(self):
        cids = set()
        for x, _n in self._behind:
            cids |= self.win.idx.match(x, self.win.swap, self.win.doc)
        self.win.study("behind", None, cids, "what's behind")

    # ---- the toolbar ----

    def _go_today(self):
        u, _now = V.today_date(self.win.doc or {}, self.win.ops.today())
        if self.mode == "month":
            t = QDate.fromString(str(self.win.ops.today()), "yyyy-MM-dd")
            self.month = QDate(t.year(), t.month(), 1)
            self._draw()
        if u is not None:
            self.open_weeks.add(V.monday(u["opens"]))
            self.pick(("date", u["id"]))
            row = self.rows.get(("date", u["id"]))
            if row is not None:
                self.list_scroll.ensureWidgetVisible(row, 0, 80)

    def _toggle_look(self):
        self.only_look = self.look_btn.isChecked()
        self._draw()

    def _all_expanded(self):
        return all(self._is_open(w) for w in M.weeks(self.win.doc or {}, self.win.ops.today()))

    def _toggle_all(self):
        """Expand all, or Collapse all once every week is expanded."""
        self.all_open = not self._all_expanded()
        self.open_weeks, self.closed_weeks = set(), set()
        self._draw()

    def _toggle_sort(self):
        self.desc = not self.desc
        self._draw()

    def _mode(self, m):
        self.mode = m
        self._draw()

    def _draw(self):
        self.list_btn.setChecked(self.mode == "list")
        self.month_btn.setChecked(self.mode == "month")
        n = len(self.look)
        self.look_btn.setVisible(self.win.author() and (bool(n) or self.only_look))
        self.look_btn.setText(f"Needs a look ({n:,})")
        mark(self.look_btn, "tone", "warm" if n and not self.only_look else "")
        self.look_btn.setChecked(self.only_look)
        self.all_btn.setText("Collapse all" if self._all_expanded() else "Expand all")
        self.all_btn.setVisible(self.mode == "list")
        self.sort_btn.setText("Latest first" if self.desc else "Earliest first")
        self.sort_btn.setVisible(self.mode == "list")
        if self.mode == "month":
            self._draw_month()
            self.views.setCurrentWidget(self.month_page)
        else:
            self._draw_list(M.weeks(self.win.doc or {}, self.win.ops.today()))
            self.views.setCurrentWidget(self.list_scroll)

    # ---- the list ----

    def _is_open(self, w):
        if w["start"] in self.open_weeks:
            return True
        if w["start"] in self.closed_weeks:
            return False
        if self.all_open is not None and not self.only_look:
            return self.all_open
        if self.only_look:
            return True
        return E._later(w["start"], 6) >= self.win.ops.today()  # as it opens: past weeks collapsed

    def _fold(self, key):
        start = key[1]
        w = next((w for w in M.weeks(self.win.doc, self.win.ops.today()) if w["start"] == start), None)
        if w is None:
            return
        if self._is_open(w):
            self.open_weeks.discard(start)
            self.closed_weeks.add(start)
        else:
            self.closed_weeks.discard(start)
            self.open_weeks.add(start)
        self._draw()

    def _draw_list(self, weeks):
        bar = self.list_scroll.verticalScrollBar()
        at = bar.value()
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(2)
        self.rows = {}
        win, today = self.win, self.win.ops.today()
        author = win.author()
        fresh = win.draft.touched(win.ctx()) if win.draft else set()
        taper = self._taper()
        found = self._matches()
        for w in (list(reversed(weeks)) if self.desc else weeks):
            items = ([(u.get("opens"), 0, u) for u in w["dates"]] + [(e.get("day"), 1, e) for e in w["events"]]
                     + [(r.get("day"), 2, r) for r in self.week_reviews(w["start"])])
            if taper and taper[0] <= E._later(w["start"], 6) and taper[1] >= w["start"]:
                items.append((max(taper[0], w["start"]), 3, None))
            if self.only_look and not any(k == 0 and x["id"] in self.look for _d, k, x in items):
                continue
            if found is not None:
                items = [t for t in items if t[1] in (0, 1) and t[2]["id"] in found]
                if not items:
                    continue
            lay.addWidget(self._week_head(w))
            if not self._is_open(w) and found is None:
                continue
            if self.heavy and V.monday(self.heavy["a"]) == w["start"] and author:
                lay.addWidget(self._heavy_box())
            ruled = w["start"] > today or E._later(w["start"], 6) < today
            for day, kind, x in sorted(items, key=lambda t: (str(t[0]), t[1]), reverse=self.desc):
                if not ruled and (str(day) <= today if self.desc else str(day) >= today):  # the line at today, either way
                    lay.addWidget(self._today_rule())
                    ruled = True
                if kind == 0:
                    lay.addWidget(self._date_row(x, fresh))
                elif kind == 1:
                    lay.addWidget(self._event_row(x))
                elif kind == 2:
                    lay.addWidget(self._review_row(x))
                else:
                    lay.addWidget(self._taper_row(taper))
            if not ruled:
                lay.addWidget(self._today_rule())
        if not weeks:
            lay.addWidget(plain("No dates yet. Paste the course's calendar below, tick what the plan covers in The deck, "
                                "or Add › A date." if author else "No dates on this plan yet.", muted=True))
        elif found is not None and not found:
            lay.addWidget(plain(f"No date or quiz has “{self.find.text().strip()}” in its name or its cards.", muted=True))
        lay.addStretch(1)
        self.list_body = body
        self.list_scroll.setWidget(body)
        body.setAutoFillBackground(False)
        QTimer.singleShot(0, lambda: bar.setValue(at))
        self._mark_picked()

    def _week_head(self, w):
        row = Row(("week", w["start"]), self._fold, margins=(6, 8, 6, 4))
        row.setToolTip("<span>Collapse</span>" if self._is_open(w) else "<span>Expand</span>")
        top = QHBoxLayout()
        top.setSpacing(6)
        opened = self._is_open(w)
        past = E._later(w["start"], 6) < self.win.ops.today()
        title = role(plain(f"{'▾' if opened else '▸'} {w['label']}" + (", this week" if w["now"] else "")), "head")
        top.addWidget(title, 1)
        words, warn = V.week_words(self.asks.get(w["start"]))
        if past and not opened:
            evs = ", ".join(e.get("name") or "?" for e in w["events"])
            words = f"{len(w['dates']):,} date{'s' if len(w['dates']) != 1 else ''}" + (f", {evs}" if evs else "")
            warn = False
        said = plain(words, dc="warn" if warn else None, muted=not warn)
        said.setWordWrap(False)
        top.addWidget(said)
        row.lay.addLayout(top)
        if past:
            mark(row, "past", "true")
        return row

    def _today_rule(self):
        f, lay = frame("rule", horizontal=True, margins=(6, 4, 6, 2))
        today = self.win.ops.today()
        lay.addWidget(plain(f"Today, {M.day_words(today)}", dc="ok"))
        lay.addStretch(1)
        return f

    def _date_row(self, u, fresh):
        win, author, today = self.win, self.win.author(), self.win.ops.today()
        row = Row(("date", u["id"]), self._clicked, on_double=self.name_it)
        top = QHBoxLayout()
        top.setSpacing(8)
        day = plain(M.day_words(u["opens"]), muted=True)
        day.setWordWrap(False)
        day.setFixedWidth(56)
        top.addWidget(day, 0, Qt.AlignmentFlag.AlignTop)
        name = role(plain(u.get("name") or "?"), "head")
        top.addWidget(name, 1)
        if author and u["id"] in fresh:
            ns = plain("not sent", dc="fresh")
            ns.setWordWrap(False)
            ns.setToolTip("<span>Changed: it waits with your other changes till you send them</span>")
            top.addWidget(ns, 0, Qt.AlignmentFlag.AlignTop)
        n = self.counts.get(u["id"])
        if author:
            right = plain(f"{n:,}" if n is not None else "", dc="n")
            right.setToolTip("<span>Its cards in your Anki</span>")
        else:
            due = str(u.get("due") or u.get("opens"))
            if str(u["opens"]) > today:
                right = plain(f"opens {M.day_words(u['opens'])}", dc="n")
            elif win.idx is not None:
                c = M.counts(win.idx, win.idx.match(u, win.swap, win.doc))
                right = plain("all seen" if not c["new"] else f"{c['new']:,} left" + ("" if due >= today else ", behind"),
                              dc="n" if due >= today or not c["new"] else "warn")
            else:
                right = plain("", dc="n")
        right.setWordWrap(False)
        top.addWidget(right, 0, Qt.AlignmentFlag.AlignTop)
        row.lay.addLayout(top)
        rows = win.rows(u)
        bits = [chip_name(r) + (f" ({len(r['cids']):,})" if win.idx is not None else "") for r in rows[:6]]
        if len(rows) > 6:
            bits.append(f"and {len(rows) - 6:,} more")
        if win.idx is None:
            bits += [M.label(t) for t in (list(u.get("tags") or []) + list(u.get("decks") or []))[:6]]
        under = None
        if bits:
            under = plain(", ".join(bits), muted=True)
        elif author and u["id"] in self.look:
            under = plain("No cards yet", dc="warn")
        if under is not None:
            ind = QHBoxLayout()
            ind.setContentsMargins(64, 0, 0, 0)
            ind.addWidget(under, 1)
            row.lay.addLayout(ind)
        if str(u.get("due") or u["opens"]) < today:
            mark(row, "past", "true")
        self.rows[("date", u["id"])] = row
        return row

    def _event_row(self, e):
        """A quiz or an exam: one line, its name in the plan's mark and what it tests at the end."""
        row = Row(("event", e["id"]), self._clicked, on_double=self.name_it)
        top = QHBoxLayout()
        top.setSpacing(8)
        day = plain(M.day_words(e.get("day")), muted=True)
        day.setFixedWidth(56)
        top.addWidget(day, 0, Qt.AlignmentFlag.AlignTop)
        top.addWidget(plain(e.get("name") or "?", dc="event"), 1)
        prep = self.prep(e)
        if prep:
            a, b = min(str(u["opens"]) for u in prep), max(str(u.get("due") or u["opens"]) for u in prep)
            words = f"tests {M.day_words(a)} – {M.day_words(b)}" if a != b else f"tests {M.day_words(a)}"
        else:
            words = "tests everything" if e is V.last_event(self.win.doc) else "tests no date yet"
        said = plain(words, dc="n")
        said.setWordWrap(False)
        top.addWidget(said, 0, Qt.AlignmentFlag.AlignTop)
        row.lay.addLayout(top)
        if prep and not self.win.author() and self.win.idx is not None:
            cids = set()
            for u in prep:
                cids |= self.win.idx.match(u, self.win.swap, self.win.doc)
            c = M.counts(self.win.idx, cids)
            ind = QHBoxLayout()
            ind.setContentsMargins(64, 0, 0, 0)
            ind.addWidget(plain(f"{c['cards']:,} cards, {c['cards'] - c['new']:,} seen", muted=True), 1)
            row.lay.addLayout(ind)
        self.rows[("event", e["id"])] = row
        return row

    def _review_row(self, r):
        row = Row(("review", r.get("day")), self._clicked)
        top = QHBoxLayout()
        top.setSpacing(8)
        day = plain(M.day_words(r.get("day")), muted=True)
        day.setFixedWidth(56)
        top.addWidget(day)
        us = self.review_units(r)
        span = (f"{M.day_words(us[0]['opens'])} – {M.day_words(us[-1]['opens'])}" if len(us) > 1
                else M.day_words(us[0]["opens"]) if us else "?")
        top.addWidget(plain(f"Review: {span}"), 1)
        row.lay.addLayout(top)
        self.rows[("review", r.get("day"))] = row
        return row

    def _taper(self):
        """(first, last) of the days at the end with no new cards, or None."""
        doc = self.win.doc or {}
        n = int((doc.get("phases") or {}).get("taper") or 0)
        _ev, end = V.ends_with(doc)
        if not n or not end:
            return None
        return E._later(end, -n), E._later(end, -1)

    def _taper_row(self, taper):
        f, lay = frame("row", horizontal=True, margins=(8, 6, 8, 6))
        day = plain(M.day_words(taper[0]), muted=True)
        day.setFixedWidth(56)
        lay.addWidget(day)
        lay.addWidget(plain(f"No new cards: {M.day_words(taper[0])} – {M.day_words(taper[1])}", muted=True), 1)
        return f

    def _heavy_box(self):
        hv, t = self.heavy, self.win.deck_tree()
        f, lay = frame("line", margins=(8, 6, 8, 8))
        name = hv["unit"].get("name") or "a date"
        when = M.day_words(hv["a"]) if hv["a"] == hv["b"] else f"{M.day_words(hv['a'])} – {M.day_words(hv['b'])}"
        top = QHBoxLayout()
        top.setSpacing(8)
        head = plain("Over the pace", dc="warn")
        head.setWordWrap(False)
        top.addWidget(head, 0, Qt.AlignmentFlag.AlignTop)
        top.addWidget(plain(f"{when}: {hv['top']:,} new a day, your pace is {hv['cap']:,}. "
                            f"{name} is {hv['total']:,} cards by {M.day_words(hv['last'])}."), 1)
        lay.addLayout(top)
        row = QHBoxLayout()
        row.setSpacing(6)
        if hv.get("big"):
            placed = B.placed_keys(self.win.doc, t)
            row.addWidget(tool(f"Split {B.label(t, hv['big'], placed)}…", self._split_heavy))
        if hv["till"] > hv["last"]:
            uid, till = hv["unit"]["id"], hv["till"]
            row.addWidget(tool(f"Let it finish by {P.fmt_day(hv['till'])}",
                               lambda: self.win.change({"op": "set_due", "date": uid, "due": till})))
        row.addStretch(1)
        row.insertSpacing(0, 64)
        lay.addLayout(row)
        return f

    def _split_heavy(self):
        hv = self.heavy
        if hv and hv.get("big"):
            self.pick(("date", hv["unit"]["id"]))
            self.date_panel.split((B.kind_of(hv["big"]), B.path_of(hv["big"])))

    # ---- the month ----

    def _draw_month(self):
        """Month: seven even columns, a day's dates and quizzes one line each
        (cut with … to fit, the whole name on hover), two a day and "+N
        more" (the list, at that date); today shaded, the picked one marked.
        An author drags a date or a quiz to another day to move it."""
        old = self.month_body.layout()
        if old is not None:
            QWidget().setLayout(old)  # the old layout and its widgets go with a throwaway parent
        doc, today = self.win.doc or {}, self.win.ops.today()
        if self.month is None:
            key = self.picked[1] if self.picked and self.picked[0] == "date" else None
            u = self.win.unit(key) if key else None
            d = QDate.fromString(str((u or {}).get("opens") or today), "yyyy-MM-dd")
            self.month = QDate(d.year(), d.month(), 1)
        self.rows = {}
        lay = QVBoxLayout(self.month_body)
        lay.setContentsMargins(8, 6, 8, 8)
        lay.setSpacing(8)
        nav = QHBoxLayout()
        nav.setSpacing(2)
        nav.setSpacing(6)
        nav.addWidget(tool("‹", lambda: self._month_step(-1), tip="The month before"))
        title = role(plain(self.month.toString("MMMM yyyy")), "head")
        title.setWordWrap(False)
        nav.addWidget(title)
        nav.addWidget(tool("›", lambda: self._month_step(1), tip="The month after"))
        nav.addStretch(1)
        lay.addLayout(nav)
        by_day = {}
        for u in sorted(P.units(doc), key=lambda u: str(u.get("name") or "")):
            by_day.setdefault(str(u.get("opens")), []).append(("date", u["id"], u.get("name") or "?"))
        for e in doc.get("events") or []:
            if isinstance(e, dict):
                by_day.setdefault(str(e.get("day")), []).insert(0, ("event", e.get("id"), str(e.get("name") or "?")))
        box = QFrame()
        box.setProperty("dc", "calgrid")
        grid = QGridLayout(box)
        grid.setContentsMargins(1, 1, 1, 1)
        grid.setSpacing(1)
        for i, d in enumerate(V.DAYS):
            head = QFrame()
            head.setProperty("dc", "calday")
            hl = QHBoxLayout(head)
            hl.setContentsMargins(6, 3, 6, 3)
            hl.addWidget(Elided(d, dc="calhead"))
            head.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            grid.addWidget(head, 0, i)
        first = self.month.addDays(-(self.month.dayOfWeek() - 1))
        rows = 0
        for k in range(42):
            d = first.addDays(k)
            if k >= 35 and d.month() != self.month.month():
                break
            rows = 1 + k // 7
            iso = d.toString("yyyy-MM-dd")
            cell = DayCell(iso, self._dropped if self.win.author() else None)
            if d.month() != self.month.month():
                cell.setProperty("out", "true")
            if iso == today:
                cell.setProperty("today", "true")
            cl = QVBoxLayout(cell)
            cl.setContentsMargins(4, 3, 4, 3)
            cl.setSpacing(1)
            num = Elided(str(d.day()), dc="calnum")
            if iso == today:
                num.setProperty("today", "true")
            cl.addWidget(num)
            here = by_day.get(iso, ())
            for kind, key, name in here[:2]:
                entry = Row((kind, key), self._clicked, margins=(4, 1, 4, 1), on_double=self.name_it, drag=self.win.author())
                entry.setProperty("dc", "calrow")  # picked: a solid pill in the day, not the list's left bar
                entry.lay.addWidget(Elided(name, dc="calev" if kind == "event" else "cal"))
                entry.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
                entry.set_on((kind, key) == self.picked)
                self.rows[(kind, key)] = entry
                cl.addWidget(entry)
            if len(here) > 2:
                more = link(f"+{len(here) - 2} more", lambda here=here: self._month_more(here[2]),
                            tip=", ".join(n for _k, _i, n in here[2:]))
                more.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
                cl.addWidget(more, 0, Qt.AlignmentFlag.AlignLeft)
            cl.addStretch(1)
            cell.setMinimumHeight(66)
            cell.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            grid.addWidget(cell, 1 + k // 7, k % 7)
        for i in range(7):
            grid.setColumnStretch(i, 1)
        for r in range(1, rows + 1):
            grid.setRowStretch(r, 1)
        lay.addWidget(box, 1)

    def _month_more(self, first):
        """+N more: the list, at the first one Month had no room for."""
        kind, key, _name = first
        self._mode("list")
        self.pick((kind, key))
        row = self.rows.get((kind, key))
        if row is not None:
            self.list_scroll.ensureWidgetVisible(row, 0, 80)

    def _month_step(self, k):
        self.month = self.month.addMonths(k)
        self._draw_month()

    def _dropped(self, kind, key, day):
        """Month: a date or a quiz dropped on another day moves there."""
        if self.win.busy or not self.win.author():
            return
        if kind == "date":
            u = self.win.unit(key)
            if u is not None and u["opens"] != day and self.day_taken(day, key):
                self.win.change({"op": "move", "date": key, "to": day}, keep=("date", key))
        elif kind == "event":
            e = self._event(key)
            if e is not None and e.get("day") != day:
                self.win.change({"op": "move_event", "event": key, "to": day}, keep=("event", key))

    # ---- picking, and the plan's keys ----

    def _clicked(self, key):
        """A row clicked: picked, and the plan in focus for its keys."""
        self.pick(key)
        self.views.currentWidget().setFocus(Qt.FocusReason.MouseFocusReason)

    def step(self, k):
        """↑ ↓: the date (or quiz, or review day) before or after the picked one, as drawn."""
        keys_ = [x for x in self.rows if x[0] in ("date", "event", "review")]
        if not keys_:
            return
        i = keys_.index(self.picked) if self.picked in keys_ else (-1 if k > 0 else len(keys_))
        i = max(0, min(len(keys_) - 1, i + k))
        self.pick(keys_[i])
        row = self.rows.get(keys_[i])
        if row is not None and self.mode == "list":
            self.list_scroll.ensureWidgetVisible(row, 0, 40)

    def nudge(self, k):
        """Alt+← →: the picked date or quiz a day earlier or later."""
        if not self._author() or not self.picked:
            return
        if self.picked[0] == "date":
            self.date_panel._nudge(k)
        elif self.picked[0] == "event":
            e = self._event(self.picked[1])
            if e is not None:
                self.win.change({"op": "move_event", "event": e["id"], "to": E._later(e["day"], k)}, keep=("event", e["id"]))

    def name_it(self, key):
        """Enter, F2 or a double-click: the picked one's name, to change."""
        if not key or not self._author():
            return
        if tuple(key) != self.picked:
            self.pick(key)
        self.back_from_deck()
        box = {"date": self.date_panel.name, "event": self.event_panel.name}.get(key[0])
        if box is not None and box.isVisible():
            box.setFocus(Qt.FocusReason.ShortcutFocusReason)
            box.selectAll()

    def delete_picked(self):
        """Delete: the picked date, quiz or review day off the plan (it asks first)."""
        if not self._author() or not self.picked:
            return
        {"date": self.date_panel._delete, "event": self.event_panel._take, "review": self.review_panel._off}[self.picked[0]]()

    def _deck_key(self):
        if self._has_deck():
            if self.picked and self.picked[0] == "date":
                self.tick_for(self.picked[1])
            else:
                self.lay_out_view()
            self.deck.find.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def _has_deck(self):
        return self.win.doc is not None and self.win.author() and self.win.deck_tree() is not None

    def _focus_find(self):
        self.find.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.find.selectAll()

    def _matches(self):
        """The ids of the dates and quizzes Find has (None: nothing typed)."""
        words = self.find.text().lower().split()
        if not words or self.win.doc is None:
            return None
        out = set()
        for u in P.units(self.win.doc):
            hay = " ".join([str(u.get("name") or "")] + [chip_name(r) for r in self.win.rows(u)]
                           + [str(t) for t in (u.get("tags") or []) + (u.get("decks") or [])]).lower()
            if all(w in hay for w in words):
                out.add(u["id"])
        for e in self.win.doc.get("events") or []:
            if isinstance(e, dict) and all(w in str(e.get("name") or "").lower() for w in words):
                out.add(e.get("id"))
        return out

    def _found(self, _text=""):
        if self.mode != "list" and self.find.text().strip():
            self.mode = "list"
        self._draw()

    def _find_first(self):
        first = next((k for k in self.rows if k[0] in ("date", "event")), None)
        if first is not None:
            self.pick(first)
            self.list_scroll.ensureWidgetVisible(self.rows[first], 0, 40)
            self.list_scroll.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def pick(self, key):
        self.picked = tuple(key) if key else None
        if self.picked and self.picked[0] == "date":
            u = self.win.unit(self.picked[1])
            if u is not None:
                self.open_weeks.add(V.monday(u["opens"]))
                self.closed_weeks.discard(V.monday(u["opens"]))
                if ("date", u["id"]) not in self.rows and self.mode == "list":
                    self._draw()
        self._mark_picked()
        self._show_side()
        if self.side.currentWidget() is self.deck and self.picked and self.picked[0] == "date":
            self.deck.set_target(self.picked[1])

    def show_key(self, key):
        """A date or a quiz picked from elsewhere (Insights): its week open, picked, in view."""
        if key and key[0] == "event":
            e = self._event(key[1])
            if e is not None:
                self.open_weeks.add(V.monday(e.get("day")))
                self.closed_weeks.discard(V.monday(e.get("day")))
                if tuple(key) not in self.rows and self.mode == "list":
                    self._draw()
        self.pick(key)

        def into_view():
            row = self.rows.get(self.picked) if self.picked else None
            if row is not None and self.mode == "list":
                self.list_scroll.ensureWidgetVisible(row, 0, 80)
        QTimer.singleShot(0, into_view)

    def _mark_picked(self):
        for key, row in self.rows.items():
            row.set_on(key == self.picked)

    def _show_side(self):
        win = self.win
        key = self.picked
        self.lay_act.setEnabled(self._has_deck())
        if self.side.currentWidget() is self.deck and not self._has_deck():
            self.side.setCurrentWidget(self.side_page)
        if not key or win.doc is None:
            self.panels.setCurrentWidget(self.none_panel)
            return
        kind = key[0]
        if kind == "date":
            self.date_panel.show_date(win.unit(key[1]))
            self.panels.setCurrentWidget(self.date_panel)
        elif kind == "event":
            self.event_panel.show_event(self._event(key[1]))
            self.panels.setCurrentWidget(self.event_panel)
        elif kind == "review":
            self.review_panel.show_review(self._review(key[1]))
            self.panels.setCurrentWidget(self.review_panel)
        if self.side.currentWidget() is self.deck and kind != "date" and self.deck.target:
            self.back_from_deck()

    def tick_for(self, uid):
        """Add from the deck: the date picked, the deck in its place, ticks adding to it (Done: the date again)."""
        if self.picked != ("date", uid):
            self.pick(("date", uid))
        self.side.setCurrentWidget(self.deck)
        self.deck.set_target(uid)

    def lay_out_view(self):
        """Add › Lay out from the deck…: the deck with no date picked to add to; ticks are what the plan
        covers, laid out on its study days at its pace."""
        if not self._has_deck():
            return
        self.side.setCurrentWidget(self.deck)
        self.deck.set_target(None)

    def back_from_deck(self):
        """Done: the picked date (or quiz) in the deck's place again."""
        self.deck.target = None
        self.side.setCurrentWidget(self.side_page)

    # ---- new dates, quizzes, review days ----

    def day_taken(self, day, uid=None):
        """True to go on: no other date that day, or I said so."""
        other = next((x for x in P.units(self.win.doc) if x.get("opens") == day and x.get("id") != uid), None)
        if other is None:
            return True
        return confirm(self, f"{P.fmt_day(day)} has {other.get('name') or 'a date'} already",
                       "Put this one on that day too? Followers see both.", "Put it on")

    def _after_picked(self):
        u = self.win.unit(self.picked[1]) if self.picked and self.picked[0] == "date" else None
        doc = self.win.doc or {}
        dd = B._Days(doc, V.pace_of(doc).get("days") or [1] * 7)
        if u is not None:
            return dd.next(u["opens"])
        ld = B.last_day(doc)
        return dd.first(E._later(ld, 1) if ld else self.win.ops.today())

    def new_date(self):
        from .window import ask_day
        name, ok = ask_text(self, "A new date", "Its name, as followers see it (the lecture, the chapter):", "")
        if not ok or not name.strip():
            return
        day = ask_day(self, f"{name.strip()}: its day", "The day its cards open for followers.", self._after_picked(), "Put it on")
        if day and self.day_taken(day):
            self.win.change({"op": "add_date", "day": day, "name": name.strip()}, keep="made")

    def new_event(self, for_uid=None):
        from .window import ask_day
        name, ok = ask_text(self, "A quiz or an exam", "Its name, as followers see it (Cardio quiz 1, Block 2 exam):", "")
        if not ok or not name.strip():
            return
        u = self.win.unit(for_uid) if for_uid else None
        start = E._later(u["opens"], 3) if u else self._after_picked()
        day = ask_day(self, f"{name.strip()}: its day", "Dates before it can be tested on it.", start, "Put it on")
        if not day:
            return
        ops = [{"op": "add_event", "day": day, "name": name.strip()}]
        if for_uid:
            ops.append({"op": "set_for", "date": for_uid, "event": f"{day} {name.strip()}"})
        self.win.changes(ops, keep=("date", for_uid) if for_uid else None)

    def week_reviews(self, start):
        end = E._later(start, 6)
        return [r for r in (self.win.doc or {}).get("reviews") or [] if isinstance(r, dict)
                and start <= str(r.get("day") or "") <= end]

    def review_units(self, r):
        a, b = self.win.unit(r.get("from")), self.win.unit(r.get("to"))
        if a is None or b is None:
            return []
        lo, hi = sorted((str(a["opens"]), str(b["opens"])))
        return [u for u in sorted(P.units(self.win.doc), key=lambda x: str(x.get("opens") or "")) if lo <= str(u["opens"]) <= hi]

    def review_label(self, r):
        a, b = self.win.unit(r.get("from")), self.win.unit(r.get("to"))
        names = (a or {}).get("name") or "?"
        if b is not None and b is not a:
            names += f" – {b.get('name') or '?'}"
        return f"{M.day_words(r.get('day'))} · Review · {names}"

    def review_day(self, day):
        """A review day on `day`: which dates it reviews, or none."""
        before = [u for u in sorted(P.units(self.win.doc), key=lambda x: str(x.get("opens") or "")) if str(u["opens"]) <= day]
        if not before:
            self.win.status.setText("A review day comes after the dates it reviews: none open by then.")
            return
        r = self._review(day)
        dlg = DD.ReviewDialog(self, f"Review day · {P.fmt_day(day)}", [(u["id"], M.date_label(u)) for u in before],
                              (r.get("from"), r.get("to")) if r else None)
        if not dlg.exec():
            return
        v = dlg.value()
        if v[0] == "off":
            self.win.change({"op": "take_review", "day": day}, keep=("gone",))
        else:
            self.win.change({"op": "set_review", "day": day, "from": v[1], "to": v[2]}, keep=("review", day))

    def new_review(self):
        from .window import ask_day
        day = ask_day(self, "A review day", "The morning followers get a deck of what they've seen so far.",
                      self._after_picked(), "Next")
        if day:
            self.review_day(day)

    def prep(self, e):
        return V.prep(self.win.doc, e)

    # ---- a tag's note, its extras, the plan's own ----

    def own_tag(self, path):
        return str(path).lower().startswith(P.tag_base(self.win.doc).lower() + "::")

    def remark(self, path):
        had = next((r for r in self.win.doc.get("remarks") or [] if isinstance(r, dict) and r.get("tag")
                    and str(r["tag"]).lower() == str(path).lower()), None)
        text, ok = ask_text(self, "A note for followers", f"On {M.label(path)}, shown in their Anki when it comes up "
                            "(one line; empty takes it off):", str((had or {}).get("text") or ""))
        if ok:
            self.win.change({"op": "set_tag_remark", "tag": path, "text": text})

    def extras(self, u, key):
        """(tag, without now, its extras' tags, its cards without them) for a
        chip that has extras (Extra, Bonus), or its search without them."""
        t = self.win.deck_tree()
        if not key or t is None or self.win.swap:
            return None
        if key[0] == "tag":
            path, without = key[1], False
        elif key[0] == "search":
            path, without = B.extras_of(t, key[1]), True
            if not path:
                return None
        else:
            return None
        kids = [B.path_of(k) for k in t.extra_kids(f"tag:{path}")]
        if not kids:
            return None
        main = max(0, t.n(f"tag:{path}") - sum(t.n(f"tag:{k}") for k in kids))
        return path, without, kids, main

    # ---- paste, text, prompts ----

    def _paste_changed(self):
        self.paste_go.setEnabled(bool(self.paste.toPlainText().strip()) and not self.win.busy)

    def _show_changes(self):
        """What's pasted: plan lines (the text's Add, shown before it goes on),
        or a course calendar (its sessions as dates, its quizzes as quizzes)."""
        from . import reading as R
        from . import text as T
        text = self.paste.toPlainText()
        if not text.strip():
            return
        win, doc = self.win, self.win.doc
        r = T.from_text(doc, win.deck_tree(), text, whole=False, start=B.plan_start(doc, B.next_monday(win.ops.today())),
                        plan_name=win.plan_name(), new_id=lambda: E.new_id(doc))
        if not r["errors"] and (r["units"] or r["events"] or r["tags"] or r["remarks"]):
            if self.text(False, text):
                self.paste.setPlainText("")
            return
        import datetime
        sessions = R.number_weeks(R.read_calendar(text, datetime.date.fromisoformat(str(win.ops.today()))))
        if not sessions:
            win.status.setText(" ".join(r["errors"][:2]) if r["errors"] else
                               "Nothing in that reads as plan lines or a calendar: each session needs a date (Mon 10/26, Oct 26).")
            return
        ops, n_dates, n_events = self.calendar_ops(sessions)
        if not ops:
            win.status.setText("Every session in that is on the plan already.")
            return
        if not confirm(self, f"{n_dates:,} date{'s' if n_dates != 1 else ''} and {n_events:,} quiz{'zes' if n_events != 1 else ''} or exams "
                       "from the calendar", "The dates come with their names and no cards: pick one, then Add from the deck."
                       + (" They wait with your other changes till you send them." if win.waiting() else ""), "Put them on"):
            return
        if win.changes(ops):
            self.paste.setPlainText("")

    def calendar_ops(self, sessions):
        """A calendar's sessions as ops: (ops, dates, quizzes), each date with
        its name and no cards (the author puts them on). A session the plan
        has (its day and name) is left out."""
        from . import reading as R
        doc = self.win.doc
        have = {(str(u.get("opens")), " ".join(str(u.get("name") or "").lower().split())) for u in P.units(doc)}
        have |= {(str(e.get("day")), " ".join(str(e.get("name") or "").lower().split()))
                 for e in doc.get("events") or [] if isinstance(e, dict)}
        ops, n_dates, n_events = [], 0, 0
        for s in sessions:
            title = " ".join(str(s["title"]).split())[:60]
            if (s["date"], title.lower()) in have:
                continue
            if s["kind"] in R.EVENT_KINDS:
                ops.append({"op": "add_event", "day": s["date"], "name": title})
                n_events += 1
                continue
            ops.append({"op": "add_date", "day": s["date"], "name": title, "tags": []})
            n_dates += 1
        return ops, n_dates, n_events

    def text(self, whole, pasted=""):
        """The plan as text (whole), or pasted plan lines to add: read, then
        shown before anything goes on. True when it went on."""
        from .text_tab import TextDialog
        dlg = TextDialog(self.win, whole, pasted)
        return bool(dlg.exec())

    def _ai_entries(self):
        self.ai_menu.clear()
        self.ai_menu.addAction("Plan the dates (a prompt to paste in your AI)").triggered.connect(lambda: self._prompt("plan"))
        self.ai_menu.addAction("Tag by objective (a prompt to paste in your AI)").triggered.connect(lambda: self._prompt("tags"))

    def _prompt(self, which):
        from . import prompts
        win, t = self.win, self.win.deck_tree()
        if t is None:
            win.status.setText("The plan's deck isn't in this Anki: a prompt needs its tags.")
            return
        if which == "plan":
            text = prompts.for_plan(win.doc, t, win.plan_name(), B.plan_start(win.doc, B.next_monday(win.ops.today())),
                                    self.deck.cover or None)
        else:
            text = prompts.for_tags(win.doc, t, win.plan_name())
        QApplication.clipboard().setText(text)
        win.status.setText("Copied. Paste it in your AI; paste what it answers in the box below, then Show the changes. "
                           "It has the deck's tag names and counts, never a card.")
