"""Labs, the plan window (docs/planner.md): a plan's weeks and dates on the
left, the picked one on the right, each source with what it holds in this
copy (cards, new, shut), grouped as the deck files them: by resource, by
system, other, the plan's own tags, subdecks, searches, picked cards.

Show in Browse, Open its cards and Study it are plan_flow's (through ops).
An author changes the plan here (Change ▾, New date…): each change is one
save of the builder's (PUT /plans/{id}, the version it started from), and
says so. Names are the authors' and the deck's: plain text everywhere,
escaped in a tooltip."""

import json

from aqt.qt import (
    QAbstractItemView, QBrush, QColor, QComboBox, QDate, QDateEdit, QDialog, QDialogButtonBox,
    QFont, QHBoxLayout, QHeaderView, QLabel, QMenu, QPushButton, QSplitter, Qt, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..ui import ask_text, attach_alive, confirm, esc, heading, note, role, tone
from .. import plans as P
from ..backend.shapes import clean_plan
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
        self.new_btn = QPushButton("New date…")
        self.new_btn.clicked.connect(self._new_date)
        top.addWidget(self.new_btn)
        root.addLayout(top)
        self.line = _plain(muted=True)
        root.addWidget(self.line)

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
        root.addWidget(split, 1)

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
        if i != self.pick.currentIndex():
            self.pick.setCurrentIndex(i)
        return True

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
        self._line()
        self._fill(keep or self.picked)

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
            items = [(u.get("opens"), 0, u) for u in w["dates"]] + [(e.get("day"), 1, e) for e in w["events"]]
            for _day, is_event, x in sorted(items, key=lambda t: (str(t[0]), t[1])):
                if is_event:
                    item = QTreeWidgetItem([M.event_label(x), ""])
                    item.setData(0, ROLE, ("event", x.get("id")))
                    item.setForeground(0, muted)
                    f = QFont(item.font(0))
                    f.setItalic(True)  # a named day (a quiz, the exam), not a date that opens cards
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
                item = QTreeWidgetItem(["    " + r["name"], _n(c["cards"]) if c["cards"] else "not in your copy",
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
        idle = not self.busy
        self.browse_btn.setEnabled(have)
        self.open_btn.setEnabled(have and idle and kind == "date")
        self.study_btn.setEnabled(have and idle and kind in ("date", "event"))
        self.study_btn.setText("Study for it" if kind == "event" else "Study it")
        on_row = self._on_row()
        self.browse_btn.setText("Show these in Browse" if on_row else "Show in Browse")
        self.open_btn.setText("Open these" if on_row else "Open its cards")
        if kind != "event":
            self.study_btn.setText("Study these" if on_row else "Study it")
        self.reload_btn.setEnabled(idle and self.pick.count() > 0)
        author = self.author()
        self.change_btn.setVisible(author)
        self.new_btn.setVisible(author)
        self.new_btn.setEnabled(author and idle and self.idx is not None)
        self.change_btn.setEnabled(author and idle and kind == "date")
        self.menu.clear()
        if author and kind == "date":
            for label, fn, ok in (("Add from the deck…", self._add, self.idx is not None),
                                  ("Take the picked one off", self._take, on_row and self._takeable(self.table.currentItem())),
                                  (None, None, None),
                                  ("Rename…", self._rename, True), ("Move to another day…", self._move, True),
                                  ("Due date…", self._due, True), (None, None, None),
                                  ("Delete this date…", self._delete, True)):
                if label is None:
                    self.menu.addSeparator()
                    continue
                a = self.menu.addAction(label)
                a.setEnabled(bool(ok))
                a.triggered.connect(lambda _=False, fn=fn: fn())

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
