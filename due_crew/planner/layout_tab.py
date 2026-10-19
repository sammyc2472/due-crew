"""Your plans' Lay it out tab (3.9.3), the builder's side panel and pace
row in Anki, for a plan's authors: What to cover (the deck's tags and
subdecks, by resource, system or other, ticked), the pace (when it
starts, its study days, Finish by a date or an event, cards a day, or each
day placed by hand), Fill (and just next week), the plan's own tags
(renamed, deleted), its lines every week, its notes on cards, and what
the plan asks: a day over the pace, the reviews it brings.

What's ticked and the pace wait here until Fill or Save the pace, one
save, as the builder's do until Save. Names are the deck's and the
authors': plain text everywhere."""

from aqt.qt import (
    QAbstractItemView, QBrush, QColor, QComboBox, QDate, QDateEdit, QFont, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QPushButton, QScrollArea, QSpinBox, QSplitter, Qt, QTimer, QToolButton, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from ..ui import ask_text, confirm, esc, note, role, tone
from .. import plans as P
from . import build as B
from . import date_dialogs as DD
from . import edits as E
from .settings_tab import _WheelToPage

ROLE = Qt.ItemDataRole.UserRole
VIEWS = (("resource", "Resource"), ("system", "System"), ("other", "Other"))  # the builder's, those the tags have; then Deck
MODES = (("end", "Finish by"), ("daily", "Cards a day"), ("placed", "I'll place each day"))


def _plain(text="", muted=False):
    w = QLabel(str(text))
    w.setTextFormat(Qt.TextFormat.PlainText)
    w.setWordWrap(True)
    return note(w) if muted else w


class LayoutTab(QWidget):
    """One plan's Lay it out, for its authors. win: the PlanWindow."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.cover, self.pace, self.start, self.aim, self.pid = set(), {}, "", None, None
        self.dirty = False  # ticks or the pace changed here since the plan's last save
        self.heavy_now = None
        self.kinds = {}  # kindsBelow, worked out once a tree
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 8, 0, 0)
        split = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(split)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 8, 0)
        ll.addWidget(role(_plain("What to cover"), "head"))
        row = QHBoxLayout()
        self.view = QComboBox()
        self.view.setToolTip("<span>How the deck's tags are sorted: by resource (#), by system (^), the rest, or its subdecks</span>")
        self.view.currentIndexChanged.connect(lambda _i: None if self._loading else self._fill_tree())
        row.addWidget(self.view)
        self.find = QLineEdit()
        self.find.setPlaceholderText("Search tags and subdecks")
        self._typing = QTimer(self)  # a search waits for a pause in the typing: a big deck has 12,000 tags
        self._typing.setSingleShot(True)
        self._typing.setInterval(200)
        self._typing.timeout.connect(self._fill_tree)
        self.find.textChanged.connect(lambda _t: self._typing.start())
        self._hay = (None, [])  # (the tree, [(key, its path and readable name, lowercased)]): worded once a tree
        row.addWidget(self.find, 1)
        ll.addLayout(row)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["", "Cards"])
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        h = self.tree.header()
        h.setStretchLastSection(False)
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.itemChanged.connect(self._ticked)
        self.tree.itemExpanded.connect(self._expanded)
        ll.addWidget(self.tree, 1)
        self.tree.itemSelectionChanged.connect(self._put_button)
        self.ticked = _plain(muted=True)
        ll.addWidget(self.ticked)
        prow = QHBoxLayout()
        self.put_btn = QPushButton("Put it on the next free day")
        self.put_btn.setToolTip("<span>The picked tag or subdeck on the next study day after the last date. "
                                "To put it on a date of your choosing: the Dates tab's Change › Add from the deck…</span>")
        self.put_btn.clicked.connect(lambda: self._put(self._row_key()))
        prow.addWidget(self.put_btn)
        prow.addStretch(1)
        ll.addLayout(prow)
        split.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)
        rl.addWidget(role(_plain("The pace"), "head"))
        line = QHBoxLayout()
        line.addWidget(_plain("Starts"))
        self.start_in = QDateEdit()
        self.start_in.setCalendarPopup(True)
        self.start_in.setDisplayFormat("ddd d MMM yyyy")
        self.start_in.setKeyboardTracking(False)  # a typed date counts once it's typed, not at each digit
        self._starting = QTimer(self)  # and a click or arrow on it once it rests: the start can move every date
        self._starting.setSingleShot(True)
        self._starting.setInterval(600)
        self._starting.timeout.connect(self._start_changed)
        self.start_in.dateChanged.connect(lambda _d: None if self._loading else self._starting.start())
        line.addWidget(self.start_in)
        line.addSpacing(12)
        line.addWidget(_plain("Study days"))
        self.days = []
        for i, d in enumerate("MTWTFSS"):
            b = QToolButton()
            b.setText(d)
            b.setCheckable(True)
            b.setToolTip(("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")[i])
            b.toggled.connect(lambda _on, i=i: self._day(i))
            line.addWidget(b)
            self.days.append(b)
        line.addStretch(1)
        rl.addLayout(line)
        line = QHBoxLayout()
        self.mode = QComboBox()
        for k, label in MODES:
            self.mode.addItem(label, k)
        self.mode.currentIndexChanged.connect(lambda _i: self._mode())
        line.addWidget(self.mode)
        self.end_in = QDateEdit()
        self.end_in.setCalendarPopup(True)
        self.end_in.setDisplayFormat("ddd d MMM yyyy")
        self.end_in.dateChanged.connect(lambda _d: self._end())
        line.addWidget(self.end_in)
        self.aim_in = QComboBox()
        self.aim_in.currentIndexChanged.connect(lambda _i: self._aim())
        line.addWidget(self.aim_in)
        self.daily = QSpinBox()
        self.daily.setRange(1, 5000)
        self.daily.setSuffix(" a day")
        self.daily.valueChanged.connect(lambda _v: self._daily())
        line.addWidget(self.daily)
        self.how = _plain(muted=True)
        line.addWidget(self.how, 1)
        rl.addLayout(line)
        line = QHBoxLayout()
        self.fill_btn = QPushButton("Fill")
        self.fill_btn.setDefault(True)
        self.fill_btn.clicked.connect(lambda: self._fill(False))
        line.addWidget(self.fill_btn)
        self.week_btn = QPushButton("Just next week")
        self.week_btn.setFlat(True)
        self.week_btn.clicked.connect(lambda: self._fill(True))
        line.addWidget(self.week_btn)
        line.addStretch(1)
        self.save_btn = QPushButton("Save the pace")
        self.save_btn.clicked.connect(self._save_pace)
        line.addWidget(self.save_btn)
        rl.addLayout(line)
        self.said = _plain(muted=True)
        rl.addWidget(self.said)
        self.heavy = _plain()
        rl.addWidget(self.heavy)
        heavy_row = QHBoxLayout()
        self.split_btn = QPushButton("Split it")
        self.split_btn.setFlat(True)
        self.split_btn.clicked.connect(self._split_heavy)
        self.till_btn = QPushButton("Give it more days")
        self.till_btn.setFlat(True)
        self.till_btn.clicked.connect(self._give_days)
        heavy_row.addWidget(self.split_btn)
        heavy_row.addWidget(self.till_btn)
        heavy_row.addStretch(1)
        rl.addLayout(heavy_row)
        self.reviews = _plain(muted=True)
        rl.addWidget(self.reviews)

        rl.addWidget(role(_plain("This plan's tags"), "head"))
        self.ptags = QTreeWidget()
        self.ptags.setHeaderLabels(["Tag", "Cards here"])
        self.ptags.setRootIsDecorated(False)
        self.ptags.setMaximumHeight(140)
        ph = self.ptags.header()
        ph.setStretchLastSection(False)
        ph.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        ph.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.ptags.itemSelectionChanged.connect(self._tag_buttons)
        rl.addWidget(self.ptags)
        self.ptags_said = _plain(muted=True)
        rl.addWidget(self.ptags_said)
        trow = QHBoxLayout()
        self.rename_btn = QPushButton("Rename…")
        self.rename_btn.clicked.connect(self._rename_tag)
        self.delete_btn = QPushButton("Delete…")
        self.delete_btn.clicked.connect(self._delete_tag)
        self.put_tag_btn = QPushButton("Put it on a day")
        self.put_tag_btn.clicked.connect(lambda: self._put(self._picked_tag_key()))
        trow.addWidget(self.rename_btn)
        trow.addWidget(self.delete_btn)
        trow.addStretch(1)
        trow.addWidget(self.put_tag_btn)
        rl.addLayout(trow)

        erow = QHBoxLayout()
        erow.addWidget(role(_plain("Every week"), "head"))
        erow.addStretch(1)
        self.every_btn = QPushButton("Edit…")
        self.every_btn.setFlat(True)
        self.every_btn.clicked.connect(self._every)
        erow.addWidget(self.every_btn)
        rl.addLayout(erow)
        self.every = _plain(muted=True)
        rl.addWidget(self.every)
        crow = QHBoxLayout()
        crow.addWidget(role(_plain("Notes on cards"), "head"))
        crow.addStretch(1)
        rl.addLayout(crow)
        self.cnotes = QTreeWidget()
        self.cnotes.setHeaderLabels(["Card", "Note"])
        self.cnotes.setRootIsDecorated(False)
        self.cnotes.setMaximumHeight(110)
        rl.addWidget(self.cnotes)
        nrow = QHBoxLayout()
        self.cnote_said = _plain("Write them in Anki's Browse: right-click a card › Due Crew. Followers see each on its card.",
                                 muted=True)
        nrow.addWidget(self.cnote_said, 1)
        self.cnote_off = QPushButton("Take it off")
        self.cnote_off.setFlat(True)
        self.cnote_off.clicked.connect(self._take_cnote)
        nrow.addWidget(self.cnote_off)
        rl.addLayout(nrow)
        rl.addStretch(1)
        scroll = QScrollArea()  # the pace and what the plan asks scroll on a short screen; the tree has its own
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(right)
        scroll.viewport().setAutoFillBackground(False)  # the window's own ground behind it
        right.setAutoFillBackground(False)
        guard = _WheelToPage(scroll)  # a wheel scrolling the page doesn't move the start or the pace
        for w in (self.start_in, self.mode, self.end_in, self.aim_in, self.daily):
            w.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            w.installEventFilter(guard)
        self._asking = QTimer(self)  # what the plan asks (a day over the pace), once the pace rests
        self._asking.setSingleShot(True)
        self._asking.setInterval(300)
        self._asking.timeout.connect(self._asks)
        split.addWidget(scroll)
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 5)
        self._loading = False

    # ---- the window asks ----

    def shown(self, win):
        return win.author()

    def plan_loaded(self, win):
        """A plan (re)loaded: what's ticked and the pace as its doc keeps them."""
        if not win.author():
            return
        doc = win.raw["doc"]
        self.kinds = {}
        if win.plan.get("id") != self.pid:
            self.pid, self.start, self.aim, self.dirty = win.plan.get("id"), "", None, False
            self.said.setText("")
        if not self.dirty:  # what's ticked here and not saved yet stays through another change's save
            self.pace = dict({"mode": "placed" if P.units(doc) else "daily", "days": [1] * 7, "daily": 20}, **(doc.get("pace") or {}))
            if not doc.get("pace") and doc.get("end"):
                self.pace["mode"] = "end"  # fromDoc: a plan with an end and no pace yet finishes by it
            self.cover = set(self.pace.get("cover") or [])
        pace = self.pace
        self.start = B.plan_start(doc, self.start or B.next_monday(win.ops.today()))
        if self.aim and not any(e.get("id") == self.aim for e in doc.get("events") or [] if isinstance(e, dict)):
            self.aim = None
        self._loading = True
        try:
            d = QDate.fromString(self.start, "yyyy-MM-dd")
            self.start_in.setDate(d if d.isValid() else QDate.currentDate())
            for i, b in enumerate(self.days):
                b.setChecked(bool(pace["days"][i]))
            self.mode.setCurrentIndex(max(0, self.mode.findData(pace.get("mode"))))
            e = QDate.fromString(str(doc.get("end") or ""), "yyyy-MM-dd")
            self.end_in.setDate(e if e.isValid() else QDate.fromString(E._later(self.start, 55), "yyyy-MM-dd"))
            self.daily.setValue(int(pace.get("daily") or 20))
            self.aim_in.clear()
            self.aim_in.addItem("or a quiz or exam…", None)
            for ev in sorted((e for e in doc.get("events") or [] if isinstance(e, dict)), key=lambda e: str(e.get("day") or "")):
                self.aim_in.addItem(f"{ev.get('name') or '?'} · {P.fmt_day(ev.get('day'))}", ev.get("id"))
            self.aim_in.setCurrentIndex(max(0, self.aim_in.findData(self.aim)) if self.aim else 0)
            t, was = self._tree(), self.view.currentData()
            self.view.clear()
            if t is not None:
                for k, label in VIEWS:
                    if k in B.kinds_below(t, "root:tag", self.kinds):
                        self.view.addItem(label, k)
                if t.kids("root:deck"):
                    self.view.addItem("Deck", "deck")
            self.view.setCurrentIndex(max(0, self.view.findData(was)))
            self.view.setVisible(self.view.count() > 1)
        finally:
            self._loading = False
        self._fill_tree()
        self._side()
        self._show()

    def busy_changed(self, win):
        if win.author() and self.pace:
            self._show()
            self._tag_buttons()
            self._put_button()

    # ---- what to cover ----

    def _tree(self):
        return self.win.deck_tree()

    def _shown(self, key):
        t, view = self._tree(), self.view.currentData()
        if view == "deck":
            return B.kind_of(key) == "deck"
        return B.kind_of(key) == "tag" and view in B.kinds_below(t, key, self.kinds)

    def _item(self, key, full=False):
        t = self._tree()
        path = B.path_of(key)
        it = QTreeWidgetItem([B.tag_name(path) if full else B.tag_word(path.split("::")[-1]),
                              f"{t.n(key):,}"])
        it.setData(0, ROLE, key)
        it.setToolTip(0, f"<span>{esc(path)}</span>")
        it.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        if not full and [k for k in t.kids(key) if self._shown(k) and t.n(k)]:
            it.addChild(QTreeWidgetItem(["…", ""]))  # a stand-in: its children are read when it opens
        return it

    def _fill_tree(self):
        self.tree.blockSignals(True)
        self.tree.clear()
        t = self._tree()
        if t is None:
            self.tree.blockSignals(False)
            self.ticked.setText("This plan's deck isn't in this Anki, so there's nothing to tick here.")
            return
        term = self.find.text().strip().lower()
        if term:
            if self._hay[0] is not t:
                self._hay = (t, [(key, (B.path_of(key) + "\n" + B.tag_name(B.path_of(key))).lower())
                                 for key in t.order])
            n = 0
            for key, hay in self._hay[1]:
                if term in hay and t.n(key):
                    self.tree.addTopLevelItem(self._item(key, full=True))
                    n += 1
                    if n >= 200:
                        break
        else:
            root = "root:deck" if self.view.currentData() == "deck" else "root:tag"
            for key in t.kids(root):
                if self._shown(key) and t.n(key):
                    self.tree.addTopLevelItem(self._item(key))
            # one way down: opened to the first choice
            item = self.tree.topLevelItem(0) if self.tree.topLevelItemCount() == 1 else None
            while item is not None:
                item.setExpanded(True)
                self._expanded(item, marks=False)
                item = item.child(0) if item.childCount() == 1 else None
        self.tree.blockSignals(False)
        self._marks()

    def _expanded(self, item, marks=True):
        if item.childCount() == 1 and item.child(0).data(0, ROLE) is None:
            self.tree.blockSignals(True)
            item.takeChild(0)
            t = self._tree()
            for key in t.kids(item.data(0, ROLE)):
                if self._shown(key) and t.n(key):
                    item.addChild(self._item(key))
            self.tree.blockSignals(False)
            if marks:
                self._marks()

    def _items(self):
        out, stack = [], [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while stack:
            it = stack.pop()
            if it.data(0, ROLE):
                out.append(it)
            stack.extend(it.child(i) for i in range(it.childCount()))
        return out

    def _marks(self):
        """Each row's tick as what's ticked says, and the ones on the calendar muted."""
        doc = self.win.raw["doc"] if self.win.author() else {}
        placed = B.placed_keys(doc, self._tree())
        muted = QBrush(QColor(tone("muted")))
        t = self._tree()
        self.tree.blockSignals(True)
        for it in self._items():
            key = it.data(0, ROLE)
            on = B.ticked(self.cover, t, key, self.view.currentData(), self.kinds)
            it.setCheckState(0, Qt.CheckState.Checked if on else Qt.CheckState.PartiallyChecked
                             if B.partly(self.cover, key) else Qt.CheckState.Unchecked)
            # covered by the tag above it: that one's tick takes it off
            it.setDisabled(B.covered(self.cover, key) and key not in self.cover)
            if B.is_placed(key, placed):
                it.setForeground(0, muted)
                f = QFont(it.font(0))
                f.setItalic(True)
                it.setFont(0, f)
                it.setToolTip(0, f"<span>{esc(B.path_of(key))} · on the calendar</span>")
        self.tree.blockSignals(False)
        self._put_button()
        if t is not None:
            tot = sum(t.n(k) for k in B.cover_items(t, self.cover))
            left = B.cover_left(t, self.cover, placed)
            self.ticked.setText((f"{tot:,} cards ticked · {left:,} not on a day yet." if tot else "Tick what the plan covers.")
                                + (" Ticks aren't saved until you Fill or Save the pace." if self.dirty else ""))

    def _ticked(self, item, col):
        if col != 0 or not item.data(0, ROLE):
            return
        self.cover = B.toggle(self.cover, self._tree(), item.data(0, ROLE), self.view.currentData(), self.kinds)
        self.dirty = True
        self._marks()
        self._paced()

    # ---- the builder's +: one onto a day ----

    def _row_key(self):
        it = self.tree.currentItem()
        return it.data(0, ROLE) if it is not None else None

    def _put_day(self):
        """The next study day after the last date (or the start): the builder's + with no day picked."""
        doc = self.win.raw["doc"]
        ld = B.last_day(doc)
        return B._Days(doc, self.pace.get("days") or [1] * 7).first(E._later(ld, 1) if ld else self.start)

    def _put_button(self):
        if not self.win.author():
            return
        day = self._put_day()
        self.put_btn.setText(f"Put it on {P.fmt_day(day)}")
        self.put_btn.setEnabled(bool(self._row_key()) and not self.win.busy)
        self.put_tag_btn.setText(f"Put it on {P.fmt_day(day)}")

    def _put(self, key):
        if not key:
            return
        day, made = self._put_day(), {}

        def change(doc):
            out, touched = E.place(doc, [(day, "tags" if B.kind_of(key) == "tag" else "decks", B.path_of(key))])
            made["ids"] = touched
            return out
        self.win._apply(change, lambda: made.get("ids", ()))

    # ---- the pace ----

    def _day(self, i):
        if self._loading:
            return
        days = [1 if b.isChecked() else 0 for b in self.days]
        if not any(days):
            self._loading = True
            self.days[i].setChecked(True)
            self._loading = False
            return
        self.pace["days"] = days
        self._paced()

    def _mode(self):
        if self._loading:
            return
        self.pace["mode"] = self.mode.currentData()
        self._paced()

    def _daily(self):
        if not self._loading:
            self.pace["daily"] = int(self.daily.value())
            self._paced()

    def _end(self):
        if not self._loading:
            self.aim = None
            self._paced()

    def _aim(self):
        if self._loading:
            return
        eid = self.aim_in.currentData()
        ev = next((e for e in self.win.raw["doc"].get("events") or [] if e.get("id") == eid), None) if eid else None
        self.aim = eid if ev else None
        if ev:
            self._loading = True
            self.end_in.setDate(QDate.fromString(E._later(ev["day"], -1), "yyyy-MM-dd"))
            self._loading = False
        self._paced()

    def _start_changed(self):
        if self._loading or not self.win.author():
            return
        day = self.start_in.date().toString("yyyy-MM-dd")
        doc = self.win.raw["doc"]
        delta = (E._day(day) - E._day(self.start)).days
        if not delta:
            return
        moves = P.units(doc) or doc.get("events") or doc.get("reviews") or doc.get("end")
        if not moves:
            self.start = day  # nothing on the calendar yet: the start set here stays, as the builder's does
            self._paced()
            return
        what = ("Every date, quiz and exam, review day and the end date move" if P.units(doc)
                else "The quizzes and exams, review days and the end date move")
        if not self.win.busy and confirm(
                self, f"Move {'every date' if P.units(doc) else 'the calendar'} {abs(delta)} day{'s' if abs(delta) != 1 else ''} "
                f"{'later' if delta > 0 else 'earlier'}?", f"{what} with the start, for everyone following it.", "Move them"):
            was = self.start
            self.start = day  # with no dates the start is this tab's: it moves with them
            self.win._apply(lambda dd: E.shift_all(dd, delta), then=lambda saved: None if saved else self._start_back(was))
        else:
            self._start_back(self.start)

    def _start_back(self, day):
        self.start = day
        self._loading = True
        self.start_in.setDate(QDate.fromString(day, "yyyy-MM-dd"))
        self._loading = False
        self._show()

    def _doc_now(self):
        """The doc with this tab's end date (Finish by) in it, to count with
        (a shallow copy: it's never saved)."""
        doc = self.win.raw["doc"]
        if self.pace.get("mode") == "end":
            doc = dict(doc, end=self.end_in.date().toString("yyyy-MM-dd"))
        return doc

    def _show(self):
        if not self.win.author():
            return
        mode = self.pace.get("mode")
        self.end_in.setVisible(mode == "end")
        self.aim_in.setVisible(mode == "end" and self.aim_in.count() > 1)
        self.daily.setVisible(mode == "daily")
        self.fill_btn.setVisible(mode != "placed")
        self.week_btn.setVisible(mode != "placed")
        t, doc = self._tree(), self._doc_now()
        words = ""
        if t is not None and mode == "end":
            d1 = B.end_daily(doc, t, self.pace, self.cover, self.start)
            words = f"≈ {d1:,} new a day" if d1 else ""
            ev = self.aim_in.currentText() if self.aim else ""
            self.fill_btn.setText(f"Fill up to {ev.split(' · ')[0]}" if ev else f"Fill to {P.fmt_day(doc.get('end'))}")
        elif t is not None and mode == "daily":
            fin = B.finish_by(doc, t, self.pace, self.cover, self.start, int(self.pace.get("daily") or 20))
            words = f"done ≈ {P.fmt_day(fin)}" if fin else ""
            self.fill_btn.setText(f"Fill at {int(self.pace.get('daily') or 20):,} a day")
        else:
            words = "each day by hand: on the Dates tab, or with Put it on… under the list"
        self.how.setText(words)
        now = self._now()
        changed = self._pace_doc(doc, now) != (self.win.raw["doc"].get("pace") or {}) \
            or (mode == "end" and doc.get("end") != self.win.raw["doc"].get("end"))
        self.save_btn.setEnabled(changed and not self.win.busy)
        self.fill_btn.setEnabled(not self.win.busy and t is not None)
        self.week_btn.setEnabled(not self.win.busy and t is not None)

    def _paced(self):
        """The pace or the ticks changed here: words now, what the plan asks once it rests."""
        self.dirty = True
        self._show()
        self._asking.start()

    def _pace_doc(self, doc, now):
        """The pace as the builder saves it: cards a day only when it's
        asked for (Finish by keeps the pace it fills at, 5,000 at most), the
        ticks that aren't under another, in the deck's order, 500 at most."""
        pace, t = now["pace"], self._tree()
        out = {"mode": pace.get("mode") or "placed", "days": [1 if x else 0 for x in pace.get("days") or [1] * 7]}
        if out["mode"] == "daily":
            out["daily"] = max(1, min(5000, int(pace.get("daily") or 20)))
        elif out["mode"] == "end":
            d1 = (B.end_daily(doc, t, pace, now["cover"], now["start"]) if t is not None else 0) or int(pace.get("daily") or 0)
            if d1:
                out["daily"] = max(1, min(5000, d1))
        if now["cover"]:
            out["cover"] = (B.cover_items(t, now["cover"]) if t is not None else sorted(now["cover"]))[:500]
        return out

    def _now(self):
        """What's ticked and the pace, as they are this moment (a save tried
        again on someone else's runs with these, not with what loads)."""
        return {"pace": dict(self.pace), "cover": set(self.cover), "start": self.start, "aim": self.aim,
                "end": self.end_in.date().toString("yyyy-MM-dd") if self.pace.get("mode") == "end" else None}

    def _with_pace(self, doc, now):
        doc = E.set_end(doc, now["end"]) if now["end"] else doc
        p = self._pace_doc(doc, now)
        return E.set_pace(doc, p["mode"], p["days"], p.get("daily"), p.get("cover"))

    def _save_pace(self):
        now = self._now()
        self.win._apply(lambda d: self._with_pace(d, now), then=self._kept)

    def _kept(self, saved):
        """The ticks and the pace saved: nothing here waits any more (a save
        that didn't go keeps them waiting, as they were)."""
        if saved:
            self.dirty = False
            self._marks()

    def _fill(self, week_ahead):
        t = self._tree()
        if t is None:
            return
        if not B.cover_left(t, self.cover, B.placed_keys(self.win.raw["doc"], t)):
            self.said.setText("Everything ticked is on the calendar already." if self.cover else "Tick what to cover on the left first.")
            return
        got, now, today = {}, self._now(), self.win.ops.today()

        def change(doc):
            doc = self._with_pace(doc, now)  # a copy
            r = B.lay_out(doc, t, dict(now["pace"]), now["cover"], now["start"], today,
                          lambda: E.new_id(doc), week_ahead=week_ahead, aim=now["aim"])
            got.update(r)
            if not r["touched"]:
                raise E.Refused(r["note"] or "Nothing fit.")
            if r.get("daily"):
                doc["pace"]["daily"] = max(1, min(5000, int(r["daily"])))  # the server keeps 1 to 5,000
            return doc
        self.said.setText("")
        self.win._apply(change, lambda: got.get("touched", ()), then=self._kept)
        if got.get("note"):
            self.said.setText(got["note"])

    # ---- what the plan asks ----

    def _side(self):
        doc = self.win.raw["doc"]
        # the plan's own tags
        self.ptags.clear()
        for x in P.plan_tags(doc):
            n = len(self.win.idx.plan_tag_cards(doc, x, self.win.swap)) if self.win.idx is not None else None
            it = QTreeWidgetItem([str(x.get("name") or "?"), f"{n:,}" if n is not None else ""])
            it.setData(0, ROLE, x.get("id"))
            it.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.ptags.addTopLevelItem(it)
        self.ptags.setVisible(bool(P.plan_tags(doc)))
        self.ptags_said.setText(f"Everyone following gets them in Anki, under DueCrew › {doc.get('tagroot') or 'plan'}."
                                if P.plan_tags(doc) else "Tag cards for your class (SLG 12, or Unit 3): in Anki's Browse, "
                                "right-click › Due Crew: tag for a plan…")
        self._tag_buttons()
        lines = B.every_clean(doc.get("every") or [])
        self.every.setText("\n".join(f"{B.TODO_LABEL.get(x['k'], '')} · {x['t']} · {B.every_label(x['r'])}" for x in lines)
                           or "None. Lines followers tick in Due on their days, from the first date to the last.")
        self.cnotes.clear()
        for r in doc.get("remarks") or []:
            if isinstance(r, dict) and r.get("card"):
                it = QTreeWidgetItem([f"{r['card'][0]} · card {int(r['card'][1]) + 1}", str(r.get("text") or "")])
                it.setData(0, ROLE, r.get("id"))
                self.cnotes.addTopLevelItem(it)
        self.cnotes.setVisible(self.cnotes.topLevelItemCount() > 0)
        self.cnote_off.setVisible(self.cnotes.topLevelItemCount() > 0)
        self._asks()

    def _asks(self):
        """A day over the pace (the first that isn't past), and the reviews the dates bring."""
        if not self.win.author():
            return
        doc, t = self._doc_now(), self._tree()  # this tab's end date, as Finish by counts it
        self.heavy_now, self.reviews_tip = None, ""
        self.reviews.setText("")
        if t is not None:
            placed = B.placed_keys(doc, t)
            total = lambda u: B.unit_total(t, u, placed)  # noqa: E731
            hv = B.heavy(doc, t, self.pace or (doc.get("pace") or {}), self.cover, self.start, total, self.win.ops.today())
            if hv:
                hv = dict(hv, big=B.biggest(t, hv["unit"], placed),
                          till=B.give_till(doc, (self.pace or {}).get("days") or [1] * 7, hv["unit"], hv["total"], hv["cap"]))
                when = P.fmt_day(hv["a"]) if hv["a"] == hv["b"] else f"{P.fmt_day(hv['a'])} – {P.fmt_day(hv['b'])}"
                name = hv["unit"].get("name") or B.auto_name(doc, t, hv["unit"], placed)
                self.heavy.setText(f"{when} {'asks' if hv['a'] == hv['b'] else 'ask'} {hv['top']:,} new a day (pace {hv['cap']:,}): "
                                   f"{name}, {hv['total']:,} by {P.fmt_day(hv['last'])}.")
                if hv["big"]:
                    self.split_btn.setText(f"Split {B.label(t, hv['big'], placed)}…")
                self.till_btn.setText(f"Give it till {P.fmt_day(hv['till'])}")
            self.heavy_now = hv
            ws = B.review_weeks(B.work_map(doc, total, (self.pace or {}).get("days") or [1] * 7))
            head = ws[:16]  # the headline's week is one the list shows
            pk = B.review_peak(head)
            if pk and pk["n"] >= 5:
                self.reviews.setText(f"About {B.about(pk['n'])} reviews a day by week {pk['wk']}. Week by week: "
                                     + " · ".join(B.weekly(head)) + (" · …" if len(ws) > len(head) else ""))
                self.reviews.setToolTip("<span>A typical card's reviews over its first six weeks, new cards aside. "
                                        "A follower's own will differ.</span>")
        hv = self.heavy_now or {}
        self.heavy.setVisible(bool(hv))
        self.split_btn.setVisible(bool(hv.get("big")))
        self.till_btn.setVisible(bool(hv) and hv["till"] > hv["last"])
        self.reviews.setVisible(bool(self.reviews.text()))

    def _split_heavy(self):
        """Split its biggest tag: the date and that tag picked on the Dates tab, and its Split…"""
        hv, win = self.heavy_now, self.win
        if not hv or not hv.get("big"):
            return
        win._show_tab("dates")
        win._go_to(("date", hv["unit"]["id"]))
        want = (B.kind_of(hv["big"]), B.path_of(hv["big"]))
        for i in range(win.table.topLevelItemCount()):
            it = win.table.topLevelItem(i)
            got = it.data(0, ROLE)
            if got and tuple(got)[:2] == want:
                win.table.setCurrentItem(it)
                win._split()
                return

    def _give_days(self):
        """Give it till: the study days the pace needs from its day, as its due date."""
        hv = self.heavy_now
        if hv and hv["till"] > hv["last"]:
            uid, till = hv["unit"]["id"], hv["till"]
            self.win._apply(lambda d: E.set_due(d, uid, till), {uid})

    def _tag_buttons(self):
        on = self.ptags.currentItem() is not None and not self.win.busy
        shown = bool(P.plan_tags(self.win.raw["doc"])) if self.win.author() else False
        for b in (self.rename_btn, self.delete_btn, self.put_tag_btn):
            b.setVisible(shown)
            b.setEnabled(on)

    def _picked_tag(self):
        it = self.ptags.currentItem()
        tid = it.data(0, ROLE) if it is not None else None
        return next((x for x in P.plan_tags(self.win.raw["doc"]) if x.get("id") == tid), None)

    def _picked_tag_key(self):
        t = self._picked_tag()
        return f"tag:{P.tag_path(self.win.raw['doc'], t)}" if t is not None else None

    def _rename_tag(self):
        t = self._picked_tag()
        if t is None:
            return
        name, ok = ask_text(self, "Rename the tag", "Its name (40 characters); the dates, searches and notes using it change with it:",
                            str(t.get("name") or ""))
        if ok and name.strip() and name.strip() != t.get("name"):
            self.win._apply(lambda d: E.rename_plan_tag(d, t["id"], name))

    def _delete_tag(self):
        t = self._picked_tag()
        if t is None:
            return
        if confirm(self, f"Delete {t.get('name') or 'the tag'}?", E.drop_say(self.win.raw["doc"], t["id"])
                   + " Followers' Anki takes it off their notes.", "Delete it", danger=True):
            self.win._apply(lambda d: E.delete_plan_tag(d, t["id"]))

    def _every(self):
        dlg = DD.LinesDialog(self, "Every week", self.win.raw["doc"].get("every") or [], every=True)
        if dlg.exec():
            lines = dlg.lines()
            self.win._apply(lambda d: E.set_every(d, lines))

    def _take_cnote(self):
        it = self.cnotes.currentItem()
        rid = it.data(0, ROLE) if it is not None else None
        if rid:
            self.win._apply(lambda d: E.take_remark(d, rid))
