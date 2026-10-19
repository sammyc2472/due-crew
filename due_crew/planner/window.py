"""Your plans (docs/planner.md; the plan window in labs, for everyone
since 3.9.3): the builder of duecrew.com, in Anki. Its Dates tab: a plan's
weeks and dates on the left (with its quizzes and exams and review days),
the picked one on the right, each source with what it holds in this copy
(cards, new, shut), grouped as the deck files them: by resource, by
system, other, the plan's own tags, subdecks, searches, picked cards.

Show in Browse, Open its cards and Study it are plan_flow's (through ops).
An author changes the plan here (Change ▾, New ▾): each change is one save
of the builder's (PUT /plans/{id}, the version it started from), and says
so; the builder's rules are build.py's and edits.py's. Names are the
authors' and the deck's: plain text everywhere, escaped in a tooltip."""

import json

from aqt.qt import (
    QAbstractItemView, QBrush, QColor, QComboBox, QDate, QDateEdit, QDialog, QDialogButtonBox,
    QFont, QHBoxLayout, QHeaderView, QLabel, QMenu, QPushButton, QSplitter, Qt, QTabWidget, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..ui import ask_text, attach_alive, confirm, esc, heading, note, role, tone
from .. import plans as P
from .. import schedule as S
from ..backend.shapes import clean_plan
from . import build as B
from . import date_dialogs as DD
from . import edits as E
from . import model as M

ROLE = Qt.ItemDataRole.UserRole


def _plain(text="", muted=False):
    w = QLabel(str(text))
    w.setTextFormat(Qt.TextFormat.PlainText)
    w.setWordWrap(True)
    return note(w) if muted else w


def _n(v):
    return f"{v:,}" if isinstance(v, int) else ""


def _whose(p):
    if p.get("role") in ("owner", "editor"):
        return "yours" if p.get("role") == "owner" else f"with {p.get('ownerName') or '?'}"
    return f"{p.get('ownerName') or '?'}’s"


class DayDialog(QDialog):
    """One day, picked on a calendar: Move, Due date, a new date's day."""

    def __init__(self, parent, title, words, day, yes, clear=None):
        super().__init__(parent)
        attach_alive(self)
        self.cleared = False
        self.setWindowTitle(title)
        root = QVBoxLayout(self)
        heading(self, root)
        root.addWidget(_plain(words, muted=True))
        self.day = QDateEdit()
        self.day.setCalendarPopup(True)
        self.day.setDisplayFormat("ddd d MMM yyyy")
        d = QDate.fromString(str(day), "yyyy-MM-dd")
        self.day.setDate(d if d.isValid() else QDate.currentDate())
        root.addWidget(self.day)
        buttons = QDialogButtonBox()
        buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole).clicked.connect(self.reject)
        if clear:
            b = QPushButton(clear)
            b.clicked.connect(self._clear)
            buttons.addButton(b, QDialogButtonBox.ButtonRole.ActionRole)
        go = QPushButton(yes)
        go.setDefault(True)
        go.clicked.connect(self.accept)
        buttons.addButton(go, QDialogButtonBox.ButtonRole.AcceptRole)
        root.addWidget(buttons)

    def _clear(self):
        self.cleared = True
        self.accept()

    def value(self):
        return None if self.cleared else self.day.date().toString("yyyy-MM-dd")


def ask_day(parent, title, words, day, yes, clear=None):
    """The day picked ("YYYY-MM-DD"), None for `clear`, False when cancelled."""
    dlg = DayDialog(parent, title, words, day, yes, clear)
    return dlg.value() if dlg.exec() else False


class PlanWindow(QDialog):
    """plans: remote.my_plans' (cleaned, each with its role). ops: flow.Ops,
    or a render's or test's own."""

    def __init__(self, parent, col, plans, ops, select=None, tab=None):
        super().__init__(parent)
        self.col, self.ops = col, ops
        self.plans = [p for p in plans or [] if isinstance(p, dict) and p.get("id")]
        self.plans.sort(key=lambda p: (p.get("role") not in ("owner", "editor"), str(p.get("name") or "").lower()))
        self.plan = self.raw = self.doc = self.idx = self.swap = None
        self.how = ""
        self.picked = None        # ("date", uid) | ("week", start) | ("event", id)
        self.busy = False
        self.undoable = None      # (plan id, version) a save of this window's made, while its Undo shows
        self._rows = {}           # uid -> model.sources, for this plan's index
        attach_alive(self)
        self.setWindowTitle("Your plans")
        self.setModal(False)
        self.setMinimumSize(900, 600)
        root = QVBoxLayout(self)
        self.head = heading(self, root, "Your plans")

        top = QHBoxLayout()
        self.pick = QComboBox()
        for p in self.plans:
            self.pick.addItem(f"{p.get('name') or 'Plan'} · {_whose(p)}", p["id"])
        top.addWidget(self.pick, 1)
        self.reload_btn = QPushButton("Reload")
        self.reload_btn.setFlat(True)
        self.reload_btn.setToolTip("The plan as it is on duecrew.com now")
        self.reload_btn.clicked.connect(self._load)
        top.addWidget(self.reload_btn)
        self.new_btn = QPushButton("New")
        self.new_menu = QMenu(self.new_btn)
        self.new_btn.setMenu(self.new_menu)
        top.addWidget(self.new_btn)
        root.addLayout(top)
        self.line = _plain(muted=True)
        root.addWidget(self.line)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        root.addWidget(self.tabs, 1)
        self.pages = {}

        split = QSplitter(Qt.Orientation.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Date", "Cards"])
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.itemSelectionChanged.connect(self._picked)
        split.addWidget(self.tree)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(12, 0, 0, 0)
        self.title = role(_plain(), "head")
        rl.addWidget(self.title)
        self.meta = _plain(muted=True)
        rl.addWidget(self.meta)
        self.todo = _plain(muted=True)
        rl.addWidget(self.todo)
        self.table = QTreeWidget()
        self.table.setHeaderLabels(["", "Cards", "New", "Shut"])
        self.table.setRootIsDecorated(False)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        h = self.table.header()
        h.setStretchLastSection(False)
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in (1, 2, 3):
            h.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemDoubleClicked.connect(lambda item, _c: self._browse_item(item))
        self.table.itemSelectionChanged.connect(self._buttons)
        rl.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.browse_btn = QPushButton("Show in Browse")
        self.browse_btn.clicked.connect(self._browse)
        self.open_btn = QPushButton("Open its cards")
        self.open_btn.clicked.connect(self._open)
        self.study_btn = QPushButton("Study it")
        self.study_btn.clicked.connect(self._study)
        self.change_btn = QPushButton("Change")
        self.menu = QMenu(self.change_btn)
        self.change_btn.setMenu(self.menu)
        for w in (self.browse_btn, self.open_btn, self.study_btn):
            row.addWidget(w)
        row.addStretch(1)
        row.addWidget(self.change_btn)
        rl.addLayout(row)
        split.addWidget(right)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 5)
        split.setSizes([300, 640])
        self._add_tab("dates", "Dates", split)
        self.want_tab = tab

        bottom = QHBoxLayout()
        self.status = _plain(muted=True)
        bottom.addWidget(self.status, 1)
        self.undo_btn = QPushButton("Undo")
        self.undo_btn.setFlat(True)
        self.undo_btn.setToolTip("Puts back what the last save changed, for everyone (as the builder's Undo)")
        self.undo_btn.clicked.connect(self._undo)
        self.undo_btn.setVisible(False)
        bottom.addWidget(self.undo_btn)
        root.addLayout(bottom)
        buttons = QDialogButtonBox()
        buttons.addButton("Close", QDialogButtonBox.ButtonRole.RejectRole).clicked.connect(self.reject)
        root.addWidget(buttons)

        if select and self.pick.findData(select) >= 0:
            self.pick.setCurrentIndex(self.pick.findData(select))  # before the signal: one load, of this one
        self.pick.currentIndexChanged.connect(self._load)
        # the same plan picked again after a load that failed: try it again
        self.pick.activated.connect(lambda _i: self._load() if self.plan is None and not self.busy else None)
        if self.plans:
            self._load()
        else:
            self._empty("No plans yet. Make one from a deck: Tools › Due Crew › Make a plan from a deck…")

    def go_to_plan(self, pid, tab=None):
        """The window, on this plan: True, or False when it doesn't list it."""
        i = self.pick.findData(pid)
        if i < 0:
            return False
        self.want_tab = tab
        if i != self.pick.currentIndex():
            self.pick.setCurrentIndex(i)
        else:
            self._show_tab(tab)
        return True

    # ---- the tabs ----

    def _add_tab(self, key, label, widget):
        self.pages[key] = widget
        self.tabs.addTab(widget, label)

    def _tab_shown(self, key, on):
        i = self.tabs.indexOf(self.pages[key]) if key in self.pages else -1
        if i >= 0:
            self.tabs.setTabVisible(i, bool(on))

    def _show_tab(self, key):
        page = self.pages.get(key or "")
        i = self.tabs.indexOf(page) if page is not None else -1
        if i >= 0 and self.tabs.isTabVisible(i):
            self.tabs.setCurrentIndex(i)

    def _role_tabs(self):
        """Which tabs this plan shows: Dates always; the builder's for its
        authors (the owner's Settings), what everyone in it sees for them."""
        for key, page in self.pages.items():
            shown = getattr(page, "shown", None)
            self._tab_shown(key, shown(self) if callable(shown) else True)
        for page in self.pages.values():
            fill = getattr(page, "plan_loaded", None)
            if callable(fill):
                fill(self)
        if self.want_tab:
            self._show_tab(self.want_tab)
            self.want_tab = None

    # ---- a plan ----

    def author(self):
        return bool(self.plan) and self.plan.get("role") in ("owner", "editor") and self.raw is not None

    def _empty(self, words):
        self.tree.clear()
        self.table.clear()
        self.title.setText("")
        self.meta.setText(words)
        self.todo.setText("")
        self.todo.setVisible(False)
        self.line.setText("")
        self._buttons()

    def _load(self, *_):
        pid = self.pick.currentData()
        if not pid:
            return
        self._can_undo(None)
        self._busy(True, "Loading the plan…")
        self.ops.load(self, pid, lambda got: self._loaded(pid, got))

    def _loaded(self, pid, got, keep=None):
        if pid != self.pick.currentData():
            return  # another plan was picked since
        self._busy(False, "")
        if not got:
            self.plan = self.raw = self.doc = self.idx = None
            self.picked = None
            self._empty("The plan didn't load: check your connection, then Reload.")
            return
        raw, plan = got
        self.plan = plan
        self.raw = raw if plan.get("role") in ("owner", "editor") else None
        # an author's view is the plan's own dates; a follower's, mine (as my follow moves them)
        self.doc = plan["doc"] if self.raw is not None else self.ops.my_doc(plan)
        self.idx, self.swap, self.how = self.ops.context(plan, self.doc)
        self._rows = {}
        self._tree = None
        self._line()
        self._fill(keep or self.picked)
        self._role_tabs()

    def _line(self):
        p = self.plan
        bits = [_whose(p).capitalize()]
        if p.get("role") in ("owner", "editor"):
            n = int(p.get("followers") or 0)
            bits.append(f"{n:,} following" if n else "nobody following yet")
        else:
            bits.append("your dates" + (" · at your own pace" if p.get("own") else ""))
        if self.idx is not None:
            bits.append(f"counted in your {self.idx.name}" + (" (its tags read as your copy names them)" if self.swap else ""))
        else:
            bits.append(f"its deck ({self.doc.get('deck') or '?'}) isn't in this Anki")
        self.line.setText(" · ".join(bits))

    def rows(self, u):
        if self.idx is None:
            return []
        if u["id"] not in self._rows:
            self._rows[u["id"]] = M.sources(self.idx, u, self.doc, self.swap)
        return self._rows[u["id"]]

    def _fill(self, keep=None):
        self.tree.blockSignals(True)
        self.tree.clear()
        ws = M.weeks(self.doc, self.ops.today())
        first = M.pick_week(ws, self.ops.today())
        target = default = None
        muted = QBrush(QColor(tone("muted")))
        for w in ws:
            top = QTreeWidgetItem([w["label"] + (" · this week" if w["now"] else ""), ""])
            top.setData(0, ROLE, ("week", w["start"]))
            if w["now"]:
                f = QFont(top.font(0))
                f.setBold(True)
                top.setFont(0, f)
            self.tree.addTopLevelItem(top)
            items = ([(u.get("opens"), 0, u) for u in w["dates"]] + [(e.get("day"), 1, e) for e in w["events"]]
                     + [(r.get("day"), 2, r) for r in self._week_reviews(w["start"])])
            for _day, is_event, x in sorted(items, key=lambda t: (str(t[0]), t[1])):
                if is_event:
                    review = is_event == 2
                    item = QTreeWidgetItem([self._review_label(x) if review else M.event_label(x), ""])
                    item.setData(0, ROLE, ("review", x.get("day")) if review else ("event", x.get("id")))
                    item.setToolTip(0, f"<span>{esc(item.text(0))}</span>")
                    item.setForeground(0, muted)
                    f = QFont(item.font(0))
                    f.setItalic(True)  # a named day (a quiz, the exam, a review day), not a date that opens cards
                    item.setFont(0, f)
                else:
                    n = len(self.idx.match(x, self.swap, self.doc)) if self.idx is not None else None
                    item = QTreeWidgetItem([M.date_label(x), _n(n)])
                    item.setData(0, ROLE, ("date", x["id"]))
                    item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                top.addChild(item)
                if keep and item.data(0, ROLE) == tuple(keep):
                    target = item
            if keep and top.data(0, ROLE) == tuple(keep):
                target = top
            if w is first:
                top.setExpanded(True)
                today = self.ops.today()
                kids = [top.child(i) for i in range(top.childCount())]
                dates = [k for k in kids if k.data(0, ROLE)[0] == "date"]
                default = next((k for k in dates if self._opens(k) >= today), dates[0] if dates else top)
        target = target or default
        self.tree.blockSignals(False)
        if not ws:
            self._empty("No dates on this plan yet." + (" New date… puts the first one on." if self.author() else ""))
            self._line()
            return
        if target is not None:
            p = target.parent()
            if p is not None:
                p.setExpanded(True)
            self.tree.setCurrentItem(target)
        self._picked()

    def _opens(self, item):
        kind, key = item.data(0, ROLE)
        u = self._unit(key) if kind == "date" else None
        return str((u or {}).get("opens") or "")

    def _unit(self, uid):
        return next((u for u in P.units(self.doc) if u["id"] == uid), None)

    def _week_reviews(self, start):
        """The plan's review days in the week from `start` (a Monday)."""
        end = E._later(start, 6)
        return [r for r in self.doc.get("reviews") or [] if isinstance(r, dict) and start <= str(r.get("day") or "") <= end]

    def _review(self, day):
        return next((r for r in self.doc.get("reviews") or [] if isinstance(r, dict) and r.get("day") == day), None)

    def _review_label(self, r):
        a, b = self._unit(r.get("from")), self._unit(r.get("to"))
        names = (a or {}).get("name") or "?"
        if b is not None and b is not a:
            names += f" – {b.get('name') or '?'}"
        return f"{M.day_words(r.get('day'))} · Review · {names}"

    def _event(self, eid):
        return next((e for e in self.doc.get("events") or [] if isinstance(e, dict) and e.get("id") == eid), None)

    # ---- the right side ----

    def _picked(self):
        item = self.tree.currentItem()
        self.picked = tuple(item.data(0, ROLE)) if item is not None and item.data(0, ROLE) else None
        self.table.clear()
        kind = self.picked[0] if self.picked else ""
        if kind == "date":
            self._show_date(self._unit(self.picked[1]))
        elif kind == "week":
            self._show_week(self.picked[1])
        elif kind == "event":
            self._show_event(self._event(self.picked[1]))
        elif kind == "review":
            self._show_review(self._review(self.picked[1]))
        else:
            self.title.setText("")
            self.meta.setText("")
            self.todo.setText("")
            self.todo.setVisible(False)
        self._buttons()

    def _show_date(self, u):
        if u is None:
            return
        self.title.setText(f"{P.fmt_day(u['opens'])} · {u.get('name') or '?'}")
        when = [f"Opens {P.fmt_day(u['opens'])}"]
        if u.get("due"):
            when.append(f"due {P.fmt_day(u['due'])}" + (", spread evenly" if u.get("even") else ""))
        if u.get("check"):
            when.append(f"checkpoint {P.fmt_day(u['check'])}")
        ev = P.for_words(self.doc, u) if u.get("for") else ""
        if ev:
            when.append(ev)
        lines = [" · ".join(when)]
        if self.idx is not None:
            cids = self.idx.match(u, self.swap, self.doc)
            c = M.counts(self.idx, cids)
            bits = [f"{c['cards']:,} card{'s' if c['cards'] != 1 else ''} in your {self.idx.name}", f"{c['new']:,} new"]
            if c["shut"] - c["leech"]:
                bits.append(f"{c['shut'] - c['leech']:,} still shut")
            if c["leech"]:
                bits.append(f"{c['leech']:,} leech{'es' if c['leech'] != 1 else ''} stay shut")
            pace = M.pace_words(self.doc, u, c["new"])
            if pace:
                bits.append(pace)
            lines.append(" · ".join(bits))
            if u["id"] in self.idx.fell_back:
                lines.append("Some of its tags are named differently in your copy: found by the notes behind them.")
        self.meta.setText("\n".join(lines))
        todo = [f"{str(x.get('k') or 'do').capitalize()}: {x.get('t') or ''}" for x in u.get("todo") or [] if isinstance(x, dict)]
        self.todo.setText(("To do: " + " · ".join(todo)) if todo else "")
        self.todo.setVisible(bool(todo))
        bold = None
        for group, rows in M.grouped(self.rows(u)):
            head = QTreeWidgetItem([group, "", "", ""])
            if bold is None:
                bold = QFont(head.font(0))
                bold.setBold(True)
            head.setFont(0, bold)
            head.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.addTopLevelItem(head)
            for r in rows:
                c = M.counts(self.idx, r["cids"])
                none = "finds nothing here" if r["kind"] == "search" else "not in your copy"
                item = QTreeWidgetItem(["    " + r["name"], _n(c["cards"]) if c["cards"] else none,
                                        _n(c["new"]) if c["cards"] else "", _n(c["shut"]) if c["cards"] else ""])
                item.setData(0, ROLE, r["key"])
                if r["raw"]:
                    item.setToolTip(0, f"<span>{esc(r['raw'])}</span>")  # rich text, so the escape reads as written
                for i in (1, 2, 3):
                    item.setTextAlignment(i, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.addTopLevelItem(item)
        if self.idx is None:
            for t in list(u.get("tags") or []) + list(u.get("decks") or []):
                item = QTreeWidgetItem([M.label(t), "", "", ""])
                item.setToolTip(0, f"<span>{esc(t)}</span>")
                self.table.addTopLevelItem(item)

    def _week_units(self, start):
        w = next((w for w in M.weeks(self.doc, self.ops.today()) if w["start"] == start), None)
        return w

    def _show_week(self, start):
        w = self._week_units(start)
        if w is None:
            return
        self.title.setText(w["label"])
        lines = [f"{len(w['dates']):,} date{'s' if len(w['dates']) != 1 else ''}"
                 + (f" · {', '.join(e.get('name') or '?' for e in w['events'])}" if w["events"] else "")]
        cids = set()
        for u in w["dates"]:
            mine = self.idx.match(u, self.swap, self.doc) if self.idx is not None else set()
            cids |= mine
            c = M.counts(self.idx, mine) if self.idx is not None else None
            item = QTreeWidgetItem([M.date_label(u), _n(c["cards"]) if c else "", _n(c["new"]) if c else "",
                                    _n(c["shut"]) if c else ""])
            item.setData(0, ROLE, ("date", u["id"]))
            for i in (1, 2, 3):
                item.setTextAlignment(i, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.addTopLevelItem(item)
        if self.idx is not None and cids:
            c = M.counts(self.idx, cids)
            lines.append(f"{c['cards']:,} cards in your {self.idx.name} · {c['new']:,} new")
        self.meta.setText("\n".join(lines))
        self.todo.setText("")
        self.todo.setVisible(False)

    def _prep(self, ev):
        return [u for u in P.units(self.doc) if u.get("for") == ev.get("id") and not P.reinforces(self.doc, u)]

    def _show_event(self, ev):
        if ev is None:
            return
        self.title.setText(f"{P.fmt_day(ev.get('day'))} · {ev.get('name') or '?'}")
        prep = self._prep(ev)
        self.meta.setText(f"{len(prep):,} date{'s' if len(prep) != 1 else ''} prep for it" if prep
                          else "No date preps for it.")
        self.todo.setText("")
        self.todo.setVisible(False)
        for u in prep:
            c = M.counts(self.idx, self.idx.match(u, self.swap, self.doc)) if self.idx is not None else None
            item = QTreeWidgetItem([M.date_label(u), _n(c["cards"]) if c else "", _n(c["new"]) if c else "",
                                    _n(c["shut"]) if c else ""])
            item.setData(0, ROLE, ("date", u["id"]))
            for i in (1, 2, 3):
                item.setTextAlignment(i, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.addTopLevelItem(item)

    def _review_units(self, r):
        """The dates a review day reviews: from its first to its last, in order."""
        a, b = self._unit(r.get("from")), self._unit(r.get("to"))
        if a is None or b is None:
            return []
        lo, hi = sorted((str(a["opens"]), str(b["opens"])))
        return [u for u in sorted(P.units(self.doc), key=lambda x: str(x.get("opens") or "")) if lo <= str(u["opens"]) <= hi]

    def _show_review(self, r):
        if r is None:
            return
        self.title.setText(self._review_label(r))
        us = self._review_units(r)
        self.meta.setText(f"That morning, followers get a Due Crew deck of what they've seen from these "
                          f"{len(us):,} date{'s' if len(us) != 1 else ''}, most missed first.")
        self.todo.setText("")
        self.todo.setVisible(False)
        for u in us:
            c = M.counts(self.idx, self.idx.match(u, self.swap, self.doc)) if self.idx is not None else None
            item = QTreeWidgetItem([M.date_label(u), _n(c["cards"]) if c else "", _n(c["new"]) if c else "",
                                    _n(c["shut"]) if c else ""])
            item.setData(0, ROLE, ("date", u["id"]))
            for i in (1, 2, 3):
                item.setTextAlignment(i, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.addTopLevelItem(item)

    # ---- what the buttons do ----

    def _cards(self):
        """(cards, name) the buttons act on: the picked source's, else the
        picked date's, week's or event's prep dates'."""
        if self.idx is None or not self.picked:
            return set(), ""
        kind, key = self.picked
        if kind == "date":
            u = self._unit(key)
            if u is None:
                return set(), ""
            item = self.table.currentItem()
            k = item.data(0, ROLE) if item is not None else None
            r = next((r for r in self.rows(u) if k is not None and r["key"] == tuple(k)), None)
            if r is not None:
                return set(r["cids"]), f"{u.get('name') or 'date'}: {r['name']}"
            return self.idx.match(u, self.swap, self.doc), str(u.get("name") or "date")
        if kind == "week":
            w = self._week_units(key)
            cids = set()
            for u in (w or {}).get("dates") or []:
                cids |= self.idx.match(u, self.swap, self.doc)
            return cids, (w or {}).get("label", "the week")
        if kind == "review":
            cids = set()
            for u in self._review_units(self._review(key) or {}):
                cids |= self.idx.match(u, self.swap, self.doc)
            return cids, "review"
        ev = self._event(key)
        cids = set()
        for u in self._prep(ev) if ev else ():
            cids |= self.idx.match(u, self.swap, self.doc)
        return cids, str((ev or {}).get("name") or "the quiz")

    def _buttons(self):
        kind = self.picked[0] if self.picked else ""
        have = self.idx is not None and bool(kind)
        if have and kind == "event":
            have = bool(self._prep(self._event(self.picked[1]) or {}))  # no date preps for it: nothing to show
        elif have and kind == "week":
            have = bool((self._week_units(self.picked[1]) or {}).get("dates"))
        elif have and kind == "review":
            have = bool(self._review_units(self._review(self.picked[1]) or {}))
        idle = not self.busy
        self.browse_btn.setEnabled(have)
        self.open_btn.setEnabled(have and idle and kind == "date")
        self.study_btn.setEnabled(have and idle and kind in ("date", "event", "review"))
        self.study_btn.setText("Study for it" if kind == "event" else "Study it")
        on_row = self._on_row()
        self.browse_btn.setText("Show these in Browse" if on_row else "Show in Browse")
        self.open_btn.setText("Open these" if on_row else "Open its cards")
        if kind != "event":
            self.study_btn.setText("Study these" if on_row else "Study it")
        self.reload_btn.setEnabled(idle and self.pick.count() > 0)
        author = self.author()
        self.change_btn.setVisible(author)
        self.change_btn.setEnabled(author and idle and kind in ("date", "event", "review"))
        self.new_btn.setEnabled(idle)
        self._new_menu(author and idle)
        self.menu.clear()
        if not author:
            return
        if kind == "date":
            self._date_menu(on_row)
        elif kind == "event":
            self._entries(self.menu, (("Rename…", self._rename_event, True), ("Move to another day…", self._move_event, True),
                                      (None, None, None), ("Take it off…", self._take_event, True)))
        elif kind == "review":
            self._entries(self.menu, (("Change its dates…", self._review_day, True), (None, None, None),
                                      ("No review day", self._no_review, True)))

    def _entries(self, menu, items):
        for label, fn, ok in items:
            if label is None:
                menu.addSeparator()
                continue
            a = menu.addAction(label)
            a.setEnabled(bool(ok))
            a.triggered.connect(lambda _=False, fn=fn: fn())

    def _new_menu(self, author):
        """New ▾: a date or a quiz or exam for an author; a plan, for anyone."""
        self.new_menu.clear()
        if self.plan is not None and self.author():
            self._entries(self.new_menu, (("New date…", self._new_date, author and self.idx is not None),
                                          ("New quiz or exam…", self._new_event, author),
                                          ("New review day…", self._new_review, author and bool(P.units(self.doc))),
                                          (None, None, None)))
        self._entries(self.new_menu, (("New plan from a calendar…", self.ops.new_from_calendar, True),
                                      ("New plan from a deck…", self.ops.new_from_deck, True)))

    def _date_menu(self, on_row):
        """Change ▾ on a date: the builder's day panel, as a menu."""
        u = self._date()
        item = self.table.currentItem()
        key = tuple(item.data(0, ROLE)) if on_row and item is not None and item.data(0, ROLE) else None
        here = self.idx is not None
        self._entries(self.menu, (("Add from the deck…", self._add, here), ("Add cards: a search or IDs…", self._add_cards, True)))
        sug = self._suggestions(u)
        if sug:
            sm = self.menu.addMenu("Suggested from its name")
            for path, n in sug:
                a = sm.addAction(f"{M.label(path)} · {n:,}")
                a.triggered.connect(lambda _=False, path=path: self._apply(lambda d: E.add_sources(d, u["id"], [path])[0], {u["id"]}))
        self._entries(self.menu, (("Take the picked one off", self._take, on_row and self._takeable(item)),
                                  ("Split the picked one…", self._split, bool(key) and key[0] in ("tag", "deck") and here)))
        if key and key[0] in ("tag", "cut") and P.plan_tags(self.doc) and not self._own_tag(key[1]):
            cm = self.menu.addMenu("Only what one of this plan's tags holds")
            now = key[2] if key[0] == "cut" else None
            for label, pid in [("All of it", None)] + [(f"Only {t.get('name') or '?'}", t.get("id")) for t in P.plan_tags(self.doc)]:
                a = cm.addAction(label)
                a.setCheckable(True)
                a.setChecked(pid == now)
                a.triggered.connect(lambda _=False, pid=pid, tag=key[1]: self._apply(lambda d: E.set_cut(d, u["id"], tag, pid), {u["id"]}))
        ex = self._extras(u, key)
        if ex:
            path, without, kids, main_n = ex
            a = self.menu.addAction("Without its extras" if not without else "With its extras")
            a.triggered.connect(lambda _=False: self._apply(
                lambda d: E.set_extras(d, u["id"], path, not without, kids, main_n), {u["id"]}))
        if key and key[0] in ("tag", "cut"):
            self._entries(self.menu, (("A note for followers on it…", lambda: self._remark(key[1]), True),))
        self.menu.addSeparator()
        prep = self.menu.addMenu("Prep for")
        evs = sorted((e for e in self.doc.get("events") or [] if isinstance(e, dict)), key=lambda e: str(e.get("day") or ""))
        for label, eid in [("Nothing", None)] + [(f"{e.get('name') or '?'} · {P.fmt_day(e.get('day'))}", e.get("id")) for e in evs]:
            a = prep.addAction(label + (" (after it)" if eid and str(next(e for e in evs if e["id"] == eid).get("day")) < str(u["opens"]) else ""))
            a.setCheckable(True)
            a.setChecked(u.get("for") == eid)
            a.triggered.connect(lambda _=False, eid=eid: self._apply(lambda d: E.set_for(d, u["id"], eid), {u["id"]}))
        prep.addSeparator()
        prep.addAction("New quiz or exam…").triggered.connect(lambda: self._new_event(for_uid=u["id"]))
        even = self.menu.addAction("Spread evenly to its due date")
        even.setCheckable(True)
        even.setChecked(bool(u.get("even")))
        even.setEnabled(bool(u.get("due") and u["due"] > u["opens"]))
        even.triggered.connect(lambda on: self._apply(lambda d: E.set_even(d, u["id"], on), {u["id"]}))
        self._entries(self.menu, (("To do…", self._todo, True), ("Make it a review day…", self._review_day, True),
                                  (None, None, None),
                                  ("Rename…", self._rename, True), ("Move to another day…", self._move, True),
                                  ("Due date…", self._due, True), (None, None, None),
                                  ("Delete this date…", self._delete, True)))

    def _on_row(self):
        """A source row of the picked date is picked: the buttons act on it."""
        item = self.table.currentItem()
        return (bool(self.picked) and self.picked[0] == "date" and item is not None
                and isinstance(item.data(0, ROLE), tuple) and item.data(0, ROLE)[:1] != ("date",))

    def _takeable(self, item):
        k = item.data(0, ROLE) if item is not None else None
        return bool(k) and k[0] in ("tag", "deck", "cut", "questions")

    def _browse_item(self, item):
        k = item.data(0, ROLE) if item is not None else None
        if k and tuple(k)[0] == "date":
            self._go_to(("date", k[1]))
            return
        self._browse()

    def _go_to(self, key):
        it = self._find(key)
        if it is not None:
            if it.parent() is not None:
                it.parent().setExpanded(True)
            self.tree.setCurrentItem(it)

    def _find(self, key):
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            if top.data(0, ROLE) == tuple(key):
                return top
            for j in range(top.childCount()):
                if top.child(j).data(0, ROLE) == tuple(key):
                    return top.child(j)
        return None

    def _browse(self):
        cids, _name = self._cards()
        self.ops.browse(cids)

    def _own_steps(self):
        """The plan's own open and study (its state kept: at my own pace, Up
        next's): when I follow it here, the board's copy is this version,
        and the whole date (not one of its rows) is what's picked."""
        return (not self._on_row()
                and self.ops.followed_here(self.plan["id"], self.plan.get("version")))

    def _open(self):
        if not self.picked or self.picked[0] != "date":
            return
        uid, pid = self.picked[1], self.plan["id"]
        if self._own_steps():
            self.ops.open_date(pid, uid)
        else:
            cids, name = self._cards()
            n = self.ops.open_cards(cids, name)
            if not n:
                self.status.setText("Nothing to open: its cards here are open already (leeches stay shut).")
        self._recount()

    def _study(self):
        kind, key = self.picked or ("", "")
        pid = self.plan["id"]
        if kind in ("date", "event") and self._own_steps():
            (self.ops.study_date if kind == "date" else self.ops.study_quiz)(pid, key)
            return
        cids, name = self._cards()
        if self.ops.study_cards(self.idx, cids, name):
            self.close()  # Anki's Study screen is on it; the window would sit over it

    def _recount(self):
        """After an open: the cards' states read again (the index re-reads
        them; what doesn't change with study is kept), the picked one kept."""
        if self.plan is None:
            return
        self.idx, self.swap, self.how = self.ops.context(self.plan, self.doc)
        self._rows = {}
        self._fill(self.picked)

    # ---- an author's changes ----

    def _busy(self, on, words=None):
        self.busy = on
        if words is not None:
            self.status.setText(words)
        self.pick.setEnabled(not on)
        self._buttons()

    def _apply(self, change, touched=(), keep=None):
        """One change to the plan, saved: change(doc) -> doc, on the doc as the
        server keeps it; the dates it touched (and any it made) counted again
        in this copy. keep: what to have picked once it's saved (a callable,
        asked after the change), else what's picked now."""
        if not self.author() or self.busy:
            return
        self._save(change, set(touched), keep, again=True)

    def _save(self, change, touched, keep, again):
        if not self.author():
            return
        before = self.raw["doc"]
        try:
            doc = change(before)
        except E.Refused as e:
            self.status.setText(str(e))
            return
        if json.dumps(E.lean(doc), sort_keys=True) == json.dumps(E.lean(before), sort_keys=True):
            self.status.setText("Nothing to change: the plan has that already.")
            return
        touched = set(touched) | {u["id"] for u in doc.get("units") or []
                                  if u.get("id") not in {x.get("id") for x in before.get("units") or []}}
        if self.idx is not None and touched:
            doc = E.recount(doc, self.idx, touched, self.swap)
        summary = E.what_changed(before, doc)
        pid, version = self.plan["id"], self.raw.get("version")
        keep_now = keep() if callable(keep) else (keep if keep is not None else self.picked)
        self._busy(True, "Saving…")
        self._can_undo(None)
        self.ops.save(self, pid, version, doc, summary,
                      lambda got: self._saved(pid, got, keep_now, (change, touched, keep) if again else None))

    def _saved(self, pid, got, keep, retry=None):
        self._busy(False, "")
        if pid != self.pick.currentData():
            return
        if not got:
            self.status.setText("That didn't save: check your connection, then try again.")
            return
        outcome, what = got
        if outcome == "refused":
            self.status.setText(str(what))
            return
        plan = clean_plan(what) or self.plan
        self._loaded(pid, (what, plan), keep=keep)
        if outcome == "stale" and retry:
            # someone (or my Anki's note ids) saved since it loaded: the same change, once, on theirs
            change, touched, keep_fn = retry
            self.status.setText("Someone saved this plan since it loaded: putting your change on theirs…")
            self._save(change, touched, keep_fn, again=False)
            return
        if outcome == "saved":
            self._can_undo((pid, plan.get("version")))
            self.status.setText("Saved for everyone following it. They get it at their next refresh.")
        else:
            self.status.setText("Someone saved this plan again since: it's up to date now. Make the change again.")

    def _can_undo(self, what):
        self.undoable = what
        self.undo_btn.setVisible(bool(what))

    def _undo(self):
        if not self.undoable or self.busy:
            return
        pid, version = self.undoable
        if pid != self.pick.currentData():
            self._can_undo(None)
            return
        self._busy(True, "Undoing…")
        self._can_undo(None)
        keep = self.picked

        def done(got):
            self._busy(False, "")
            if pid != self.pick.currentData():
                return
            if not got:
                self.status.setText("That didn't undo: check your connection, then try again.")
                return
            outcome, what = got
            if outcome == "refused":
                self.status.setText(str(what))
                return
            self._loaded(pid, (what, clean_plan(what) or self.plan), keep=keep)
            self.status.setText("Undone." if outcome == "saved"
                                else "Someone saved this plan since, so there's nothing of yours to undo now.")
        self.ops.undo(self, pid, version, done)

    def _date(self):
        return self._unit(self.picked[1]) if self.picked and self.picked[0] == "date" else None

    def _add(self):
        u = self._date()
        if u is None or self.idx is None:
            return
        from .picker import pick_sources
        got = pick_sources(self, self.idx, f"Add to {P.fmt_day(u['opens'])}", self.doc.get("deck") or "")
        if got:
            tags, decks = self._as_plan(got)
            self._apply(lambda d: E.add_sources(d, u["id"], tags, decks)[0], {u["id"]})

    def _as_plan(self, got):
        """(tags, decks) picked in this copy, as the plan names them: a copy
        whose top tag is named differently (self.swap: the plan's, mine)
        has its tags read back to the plan's."""
        tags, decks = got
        if self.swap:
            tags = [P.swapped(t, (self.swap[1], self.swap[0])) for t in tags]
        return tags, decks

    def _day_taken(self, day, uid=None):
        """True to go on: no other date that day, or I said so."""
        other = next((x for x in P.units(self.doc) if x.get("opens") == day and x.get("id") != uid), None)
        if other is None:
            return True
        return confirm(self, f"{P.fmt_day(day)} has {other.get('name') or 'a date'} already",
                       "Put this one on that day too? Followers see both.", "Put it on")

    def _take(self):
        u = self._date()
        item = self.table.currentItem()
        k = item.data(0, ROLE) if item is not None else None
        if u is None or not k:
            return
        self._apply(lambda d: E.take_source(d, u["id"], tuple(k)), {u["id"]})

    def _rename(self):
        u = self._date()
        if u is None:
            return
        name, ok = ask_text(self, "Rename the date", "Its name, as followers see it:", str(u.get("name") or ""))
        if ok and name.strip() and name.strip() != u.get("name"):
            self._apply(lambda d: E.rename(d, u["id"], name))

    def _move(self):
        u = self._date()
        if u is None:
            return
        day = ask_day(self, f"Move {P.fmt_day(u['opens'])}",
                      "Its due date and checkpoint move with it." if u.get("due") or u.get("check")
                      else "The day it opens for followers.", u["opens"], "Move it")
        if day and day != u["opens"] and self._day_taken(day, u["id"]):
            self._apply(lambda d: E.move(d, u["id"], day))

    def _due(self):
        u = self._date()
        if u is None:
            return
        day = ask_day(self, f"Due date for {P.fmt_day(u['opens'])}",
                      "By when followers should have its cards seen.", u.get("due") or u["opens"], "Set it",
                      clear="No due date" if u.get("due") else None)
        if day is not False and day != u.get("due"):
            self._apply(lambda d: E.set_due(d, u["id"], day))

    def _delete(self):
        u = self._date()
        if u is None:
            return
        if confirm(self, f"Delete {P.fmt_day(u['opens'])} · {u.get('name') or '?'}?",
                   "It comes off the plan for everyone following it. What opened stays open.", "Delete", danger=True):
            self._apply(lambda d: E.delete_date(d, u["id"]), keep=("gone",))  # saved, the window opens where it would

    def _new_date(self):
        if not self.author() or self.idx is None:
            return
        from .picker import pick_sources
        got = pick_sources(self, self.idx, "What the new date opens", self.doc.get("deck") or "")
        if not got:
            return
        tags, decks = self._as_plan(got)
        u = self._date()
        start = E._later(u["opens"], 1) if u and u.get("opens") else self.ops.today()  # the day after the picked one
        day = ask_day(self, "The new date's day", "The day it opens for followers.", start, "Put it on")
        if day and self._day_taken(day):
            made = {}

            def change(d):
                doc, uid = E.add_date(d, day, tags, decks)
                made["uid"] = uid
                return doc
            self._apply(change, keep=lambda: ("date", made["uid"]))

    # ---- 3.9.3: the builder's day panel, through Change ▾ and New ▾ ----

    def deck_tree(self):
        """The deck's tags and subdecks here as the builder reads them (build.Tree),
        read once a plan's load (a big deck's tree is a few seconds' work once)."""
        if self.idx is None:
            return None
        if getattr(self, "_tree", None) is None:
            tags, decks = self.idx.tree()
            self._tree = B.Tree(tags, decks)
        return self._tree

    def _named_by_hand(self, u):
        return bool(str(u.get("name") or "").strip()) and u.get("name") != E.auto_name(u.get("tags") or [], u.get("decks") or [])

    def _suggestions(self, u):
        """The deck's tags a date's name points at that no date has yet (Suggest.tags)."""
        if u is None or self.idx is None or self.swap or not self._named_by_hand(u):
            return []
        t = self.deck_tree()
        on, above = set(), set()
        for k in B.placed_keys(self.doc):
            if B.kind_of(k) != "tag":
                continue
            low = B.path_of(k).lower()
            on.add(low)
            segs = low.split("::")
            above.update("::".join(segs[:i]) for i in range(1, len(segs)))
        for x in P.units(self.doc):
            for c in x.get("cut") or []:
                on.add(str(c.get("tag") or "").lower())

        def skip(path):
            low = path.lower()
            segs = low.split("::")
            return low in on or low in above or any("::".join(segs[:i]) in on for i in range(1, len(segs)))
        rows = [(B.path_of(k), t.n(k)) for k in t.order if B.kind_of(k) == "tag"]
        return B.suggest(u.get("name"), rows, skip)

    def _own_tag(self, path):
        return str(path).lower().startswith(P.tag_base(self.doc).lower() + "::")

    def _extras(self, u, key):
        """(tag, without now, its extras' tags, its cards without them) for a
        picked tag that has extras (Extra, Bonus), or its search without them."""
        if not key or self.idx is None or self.swap:
            return None
        t = self.deck_tree()
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

    def _remark(self, path):
        had = next((r for r in self.doc.get("remarks") or [] if isinstance(r, dict) and r.get("tag")
                    and str(r["tag"]).lower() == str(path).lower()), None)
        text, ok = ask_text(self, "A note for followers", f"On {M.label(path)}, shown in their Anki when it comes up "
                            "(one line; empty takes it off):", str((had or {}).get("text") or ""))
        if ok:
            self._apply(lambda d: E.set_tag_remark(d, path, text))

    def _add_cards(self):
        u = self._date()
        if u is None:
            return
        idx = self.idx
        dlg = DD.AddCardsDialog(self, f"Add cards to {P.fmt_day(u['opens'])}",
                                lambda q: len(idx.search_cards(q)) if idx is not None else None)
        if not dlg.exec():
            return
        what = dlg.what()
        if not what:
            return
        kind, x = what
        if kind == "search":
            n = len(idx.search_cards(x)) if idx is not None else None
            self._apply(lambda d: E.add_search(d, u["id"], x, n), {u["id"]})
        elif kind in ("nids", "cids"):
            self._apply(lambda d: E.add_ids(d, u["id"], kind, x), {u["id"]})
        else:
            self._apply(lambda d: E.add_picks(d, u["id"], x["notes"], x["cards"]), {u["id"]})

    def _pace(self):
        """(cards a day, or 0 when each day is placed by hand; the plan's study days)."""
        pace = self.doc.get("pace") or {}
        cap = 0 if pace.get("mode") == "placed" else max(1, int(pace.get("daily") or 20))
        return cap, S.plan_days(self.doc)

    def _split(self):
        u = self._date()
        item = self.table.currentItem()
        key = tuple(item.data(0, ROLE)) if item is not None and item.data(0, ROLE) else None
        if u is None or not key or key[0] not in ("tag", "deck") or self.idx is None:
            return
        field, path = ("tags" if key[0] == "tag" else "decks"), key[1]
        t = self.deck_tree()
        tk = f"{key[0]}:{path}"
        placed = B.placed_keys(self.doc, t)
        others = placed - {tk}
        kids = [k for k in t.kids(tk) if not B.is_placed(k, others) and B.eff(t, k, others) > 0] if not self.swap else []
        total = B.eff(t, tk, others) or len(self.idx.match(u, self.swap, self.doc))
        cap, days = self._pace()
        rest = t.only(tk) if kids else 0
        parts = " · ".join(f"{B._tag_word(B.path_of(k).split('::')[-1])} {B.eff(t, k, others):,}" for k in kids[:6])
        if len(kids) > 6:
            parts += f" · {len(kids) - 6} more"
        if kids and rest > 0:
            parts += f" · the rest {rest:,}"
        dlg = DD.SplitDialog(self, B._tag_word(path.split("::")[-1]), total, parts, cap,
                             -(-total // cap) if cap else 3)
        if not dlg.exec():
            return
        how = dlg.value()
        made = {}
        if how[0] == "even":
            dd = B._Days(self.doc, days)
            ds, d = [], dd.first(u["opens"])
            while len(ds) < how[1]:
                ds.append(d)
                d = dd.next(d)

            def change(doc):
                out, nid = E.split_even(doc, u["id"], (field, path), ds)
                made["uid"] = nid
                return out
            self._apply(change, {u["id"]}, keep=lambda: ("date", made.get("uid", u["id"])))
            return
        items = [{"key": k, "n": B.eff(t, k, others)} for k in kids]
        if rest > 0:
            items.append({"key": tk, "n": rest, "rest": True, "even": bool(cap) and rest > cap})

        def change(doc):
            doc = E.take_off(doc, u["id"], field, path)
            before = E.copy.deepcopy(doc)
            got = B.fill(doc, items, u["opens"], None, cap, days, lambda: E.new_id(doc))
            if got["left"]:
                raise E.Refused(got["note"] or f"{sum(x['n'] for x in got['left']):,} didn't fit: {B.left_names(got['left'])}.")
            return E.name_dates(doc, got["touched"], before)
        self._apply(change, {u["id"]}, keep=lambda: ("date", u["id"]) if self._unit(u["id"]) else None)

    def _todo(self):
        u = self._date()
        if u is None:
            return
        dlg = DD.LinesDialog(self, f"To do on {P.fmt_day(u['opens'])}", u.get("todo") or [])
        if dlg.exec():
            lines = dlg.lines()
            self._apply(lambda d: E.set_todo(d, u["id"], lines), {u["id"]})

    def _review_day(self, day=None):
        """A review day on the picked date's day (or a review's, or `day`)."""
        kind, key = self.picked or ("", "")
        if day is None:
            day = key if kind == "review" else (self._date() or {}).get("opens")
        if not day:
            return
        before = [u for u in sorted(P.units(self.doc), key=lambda x: str(x.get("opens") or "")) if str(u["opens"]) <= day]
        if not before:
            self.status.setText("A review day comes after the dates it reviews: none open by then.")
            return
        r = self._review(day)
        dlg = DD.ReviewDialog(self, f"Review day · {P.fmt_day(day)}", [(u["id"], M.date_label(u)) for u in before],
                              (r.get("from"), r.get("to")) if r else None)
        if not dlg.exec():
            return
        v = dlg.value()
        if v[0] == "off":
            self._apply(lambda d: E.take_review(d, day), keep=("gone",))
        else:
            self._apply(lambda d: E.set_review(d, day, v[1], v[2]), keep=("review", day))

    def _no_review(self):
        kind, key = self.picked or ("", "")
        if kind == "review":
            self._apply(lambda d: E.take_review(d, key), keep=("gone",))

    def _new_review(self):
        day = ask_day(self, "A review day", "The morning followers get a deck of what they've seen so far.",
                      self.ops.today(), "Next")
        if day:
            self._review_day(day)

    def _new_event(self, for_uid=None):
        if not self.author():
            return
        name, ok = ask_text(self, "A quiz or an exam", "Its name, as followers see it (Micro quiz, Block 2 exam):", "")
        if not ok or not name.strip():
            return
        u = self._unit(for_uid) if for_uid else self._date()
        start = E._later(u["opens"], 3) if u and u.get("opens") else self.ops.today()
        day = ask_day(self, f"{name.strip()}: its day", "Dates before it can prep for it.", start, "Put it on")
        if not day:
            return
        made = {}

        def change(d):
            doc, eid = E.add_event(d, day, name)
            made["eid"] = eid
            return E.set_for(doc, for_uid, eid) if for_uid else doc
        self._apply(change, {for_uid} if for_uid else (), keep=lambda: ("date", for_uid) if for_uid else ("event", made["eid"]))

    def _picked_event(self):
        return self._event(self.picked[1]) if self.picked and self.picked[0] == "event" else None

    def _rename_event(self):
        e = self._picked_event()
        if e is None:
            return
        name, ok = ask_text(self, "Rename", "Its name, as followers see it:", str(e.get("name") or ""))
        if ok and name.strip() and name.strip() != e.get("name"):
            self._apply(lambda d: E.rename_event(d, e["id"], name))

    def _move_event(self):
        e = self._picked_event()
        if e is None:
            return
        day = ask_day(self, f"Move {e.get('name') or 'it'}", "The dates that prep for it keep prepping for it.",
                      e.get("day"), "Move it")
        if day and day != e.get("day"):
            self._apply(lambda d: E.move_event(d, e["id"], day))

    def _take_event(self):
        e = self._picked_event()
        if e is None:
            return
        n = len(self._prep(e))
        if confirm(self, f"Take {e.get('name') or 'it'} off?",
                   f"{n:,} date{'s' if n != 1 else ''} prep for it; they stay, prepping for nothing." if n
                   else "It comes off the plan for everyone following it.", "Take it off", danger=True):
            self._apply(lambda d: E.take_event(d, e["id"]), keep=("gone",))
