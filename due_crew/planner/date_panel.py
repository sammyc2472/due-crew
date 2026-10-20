"""Round five's picked date, changed where it's shown (docs/planner.md):
its name, when its cards open and by when they're done, the quiz it's
tested on, a day earlier or later (or it and every date after), its cards
as chips (✕ takes one off; a chip's own menu splits it, keeps it to one
of the plan's tags, leaves out its extras, puts a note on it), the deck's
tags its name points at (+ Add, ✕ not this), its to-dos and a note on its
day. The rest of what the builder's day panel did is under ⋯, each entry
saying what it does to the cards. A follower sees the same date to read:
what's open and left, Study, Show in Browse, the to-dos and the notes.

A quiz or exam and a review day get panels of their own here too. Every
change is an op (ops.py) through the window: waiting to be sent, or
saved. Names are the deck's and the authors': plain text everywhere."""

from aqt.qt import (
    QApplication, QComboBox, QDate, QDateEdit, QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout, QLineEdit,
    QMenu, QPushButton, QSpinBox, QTimer, QVBoxLayout, QWidget,
)

from ..ui import attach_alive, confirm, heading, role
from .. import plans as P
from . import build as B
from . import date_dialogs as DD
from . import edits as E
from . import model as M
from .day_notes import DayNotes
from .widgets import Chip, flow_box, link, plain, small


def _every_on(doc, x, day):
    """A plan's every-week line falls on this date's day (due.every_on, from the plan's first date to its last)."""
    from .. import due
    try:
        return bool(due.every_on({"first": B.plan_start(doc, ""), "last": B.last_day(doc)}, x, str(day)))
    except Exception:
        return False


def chip_name(r):
    g, n = str(r.get("group") or ""), str(r.get("name") or "")
    if r.get("kind") in ("search", "picks", "plan", "deck") or not g or g == "?" or g.lower() in n.lower():
        return n
    return f"{g} › {n}"


def _iso(qd):
    return qd.toString("yyyy-MM-dd")


def _qd(iso):
    d = QDate.fromString(str(iso or ""), "yyyy-MM-dd")
    return d if d.isValid() else QDate.currentDate()


class MoveFromDialog(QDialog):
    """This and every date after: how many days, later or earlier."""

    def __init__(self, parent, name, after):
        super().__init__(parent)
        attach_alive(self)
        self.setWindowTitle(f"Move {name} and every date after it")
        root = QVBoxLayout(self)
        heading(self, root)
        root.addWidget(plain(f"{after:,} date{'s' if after != 1 else ''} after it move with it, and the review days "
                             "among them. Quizzes and exams stay on their days.", muted=True))
        row = QHBoxLayout()
        self.n = QSpinBox()
        self.n.setRange(1, 60)
        self.n.setValue(1)
        self.n.setSuffix(" day")
        self.n.valueChanged.connect(lambda v: self.n.setSuffix(" day" if v == 1 else " days"))
        row.addWidget(self.n)
        self.way = QComboBox()
        self.way.addItem("later", 1)
        self.way.addItem("earlier", -1)
        row.addWidget(self.way)
        row.addStretch(1)
        root.addLayout(row)
        buttons = QDialogButtonBox()
        buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole).clicked.connect(self.reject)
        go = QPushButton("Move them")
        go.setDefault(True)
        go.clicked.connect(self.accept)
        buttons.addButton(go, QDialogButtonBox.ButtonRole.AcceptRole)
        root.addWidget(buttons)

    def days(self):
        return int(self.n.value()) * int(self.way.currentData())


class DatePanel(QWidget):
    """The picked date. win: the PlanWindow; tab: the PlanTab (its deck panel)."""

    def __init__(self, win, tab):
        super().__init__()
        self.win, self.tab = win, tab
        self.u = None
        self._loading = False
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)
        self.root = root

        # ---- an author's fields ----
        self.fields = QWidget()
        fl = QVBoxLayout(self.fields)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(8)
        row = QHBoxLayout()
        self.name = QLineEdit()
        self.name.setMaxLength(60)
        self.name.editingFinished.connect(self._rename)
        row.addWidget(self.name, 1)
        self.more = QPushButton("⋯")
        self.more.setProperty("dc", "more")
        self.more.setAutoDefault(False)
        self.more.setToolTip("<span>More for this date: split, a review day, keep only some of its cards, spread, copy its search, delete</span>")
        self.more_menu = QMenu(self.more)
        self.more_menu.aboutToShow.connect(self._more)
        self.more.setMenu(self.more_menu)
        row.addWidget(self.more)
        fl.addLayout(row)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        grid.addWidget(plain("Cards open", muted=True), 0, 0)
        grid.addWidget(plain("Finish by", muted=True), 1, 0)
        self.opens = QDateEdit()
        self.opens.setCalendarPopup(True)
        self.opens.setDisplayFormat("ddd d MMM")
        self.opens.setKeyboardTracking(False)
        self.due = QDateEdit()
        self.due.setCalendarPopup(True)
        self.due.setDisplayFormat("ddd d MMM")
        self.due.setKeyboardTracking(False)
        self.due.setSpecialValueText("no day")
        self._resting = QTimer(self)  # a click or an arrow on a day counts once it rests
        self._resting.setSingleShot(True)
        self._resting.setInterval(700)
        self._resting.timeout.connect(self._days_changed)
        self.opens.dateChanged.connect(lambda _d: None if self._loading else self._resting.start())
        self.due.dateChanged.connect(lambda _d: None if self._loading else self._resting.start())
        for r, w in ((0, self.opens), (1, self.due)):
            box = QHBoxLayout()
            box.addWidget(w)
            box.addStretch(1)
            grid.addLayout(box, r, 1)
        grid.addWidget(plain("Tested on", muted=True), 2, 0)
        self.event = QComboBox()
        self.event.activated.connect(self._tested_on)
        grid.addWidget(self.event, 2, 1)
        grid.addWidget(plain("Move", muted=True), 3, 0)
        moves = QHBoxLayout()
        moves.setSpacing(6)
        self.earlier = QPushButton("−1 day")
        self.earlier.setAutoDefault(False)
        self.earlier.clicked.connect(lambda: self._nudge(-1))
        self.later = QPushButton("+1 day")
        self.later.setAutoDefault(False)
        self.later.clicked.connect(lambda: self._nudge(1))
        moves.addWidget(self.earlier)
        moves.addWidget(self.later)
        moves.addWidget(link("This and later dates…", self._move_from, tip="Move this date and every one after it"))
        moves.addStretch(1)
        grid.addLayout(moves, 3, 1)
        grid.setColumnStretch(1, 1)
        fl.addLayout(grid)
        root.addWidget(self.fields)

        # ---- a follower's line ----
        self.meta = plain(muted=True)
        root.addWidget(self.meta)

        # ---- its cards ----
        heads = QVBoxLayout()
        heads.setSpacing(1)
        self.cards_head = role(plain(), "head")
        self.cards_head.setWordWrap(False)
        heads.addWidget(self.cards_head)
        self.cards_said = plain(muted=True)
        heads.addWidget(self.cards_said)
        root.addLayout(heads)
        self.chips, self.chips_lay = flow_box()
        root.addWidget(self.chips)
        self.adds = QWidget()
        al = QHBoxLayout(self.adds)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(2)
        al.addWidget(link("+ From the deck", lambda: self.tab.tick_for(self.u["id"]) if self.u else None,
                          tip="Tick the deck's tags for this date, beside the plan"))
        al.addWidget(link("+ A search or IDs", self._add_cards))
        al.addStretch(1)
        root.addWidget(self.adds)
        row = QHBoxLayout()
        self.browse_btn = QPushButton("Show in Browse")
        self.browse_btn.setAutoDefault(False)
        self.browse_btn.clicked.connect(lambda: self.win.ops.browse(self._cids()))
        self.study_btn = QPushButton("Study them")
        self.study_btn.setAutoDefault(False)
        self.study_btn.clicked.connect(self._study)
        row.addWidget(self.browse_btn)
        row.addWidget(self.study_btn)
        row.addStretch(1)
        root.addLayout(row)

        # ---- to do ----
        self.todo_head = role(plain("To do"), "head")
        root.addWidget(self.todo_head)
        self.todo_box = QWidget()
        self.todo_lay = QVBoxLayout(self.todo_box)
        self.todo_lay.setContentsMargins(0, 0, 0, 0)
        self.todo_lay.setSpacing(2)
        root.addWidget(self.todo_box)
        self.todo_links = QWidget()
        tl = QHBoxLayout(self.todo_links)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(2)
        tl.addWidget(link("+ A line", self._todo, tip="Watch, read or do: a line followers tick in Due on this date"))
        tl.addWidget(link("+ Every week…", self._every, tip="Lines on the same weekday every week of the plan"))
        tl.addStretch(1)
        root.addWidget(self.todo_links)

        # ---- notes on its day ----
        root.addWidget(role(plain("Notes on its day"), "head"))
        self.day_notes = DayNotes(win)
        root.addWidget(self.day_notes)
        root.addStretch(1)

    # ---- shown ----

    def show_date(self, u):
        self.u = u
        win, author = self.win, self.win.author()
        self.fields.setVisible(author)
        self.adds.setVisible(author and win.idx is not None)
        self.todo_links.setVisible(author)
        self._loading = True
        try:
            if author:
                self.name.setText(str(u.get("name") or ""))
                self.opens.setDate(_qd(u["opens"]))
                self.due.setMinimumDate(_qd(u["opens"]).addDays(-1))
                self.due.setDate(_qd(u["due"]) if u.get("due") else self.due.minimumDate())
                self.event.clear()
                self.event.addItem("Nothing", None)
                evs = sorted((e for e in win.doc.get("events") or [] if isinstance(e, dict)), key=lambda e: str(e.get("day") or ""))
                for e in evs:
                    after = " (after it)" if str(e.get("day")) < str(u["opens"]) else ""
                    self.event.addItem(f"{e.get('name') or '?'} · {P.fmt_day(e.get('day'))}{after}", e.get("id"))
                self.event.addItem("New quiz or exam…", "new")
                self.event.setCurrentIndex(max(0, self.event.findData(u.get("for"))))
        finally:
            self._loading = False
        self.meta.setVisible(not author)
        if not author:
            when = [f"Opens {P.fmt_day(u['opens'])}" if str(u["opens"]) > win.ops.today() else f"Opened {P.fmt_day(u['opens'])}"]
            if u.get("due"):
                when.append(f"finish by {P.fmt_day(u['due'])}")
            ev = P.for_words(win.doc, u) if u.get("for") else ""
            if ev:
                when.append(ev)
            self.meta.setText(" · ".join(when))
        self._cards()
        self._todos()
        self.day_notes.show_for({u["opens"]}, u["opens"])  # the day it's on here, sent or not
        self.busy_changed()

    def _cids(self):
        if self.u is None or self.win.idx is None:
            return set()
        return self.win.idx.match(self.u, self.win.swap, self.win.doc)

    def _cards(self):
        win, u, author = self.win, self.u, self.win.author()
        self.chips_lay.clear()
        rows = win.rows(u)
        fresh = win.draft.touched(win.ctx()) if win.draft else set()
        for r in rows:
            c = Chip(chip_name(r), len(r["cids"]) if win.idx is not None else None,
                     kind="fresh" if u["id"] in fresh else None, tip=r.get("raw") or None,
                     on_click=(lambda pos, r=r: self._chip_menu(r, pos)))
            if author:
                c.add(small("✕", lambda r=r: self.win.change({"op": "take_cards", "date": u["id"], "key": list(r["key"])}),
                            "Take it off this date"))
            self.chips_lay.addWidget(c)
        if win.idx is None:
            for t in list(u.get("tags") or []) + list(u.get("decks") or []):
                self.chips_lay.addWidget(Chip(M.label(t), tip=t))
        self.chips.setVisible(self.chips_lay.count() > 0)
        cids = self._cids()
        n = len(cids)
        self.cards_head.setText(f"Its cards · {n:,}" if win.idx is not None else "Its cards")
        bits = []
        if win.idx is not None and cids:
            c = M.counts(win.idx, cids)
            if author:
                bits.append(f"{c['new']:,} new")
                if c["leech"]:
                    bits.append(f"{c['leech']:,} leech{'es' if c['leech'] != 1 else ''} stay shut")
            else:
                left = c["shut"] - c["leech"]
                bits.append(f"{c['open']:,} open · {left:,} still shut" if left else f"all {c['open']:,} open")
            pace = M.pace_words(win.doc, u, c["new"]) if author else ""
            if pace:
                bits.append(pace)
        if win.idx is None:
            bits.append(f"its deck ({win.doc.get('deck') or '?'}) isn't in this Anki")
        self.cards_said.setText(" · ".join(bits))
        self.browse_btn.setText(f"Show the {n:,} in Browse" if n else "Show in Browse")

    def _todos(self):
        while self.todo_lay.count():
            w = self.todo_lay.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.deleteLater()
        u, author = self.u, self.win.author()
        lines = [x for x in u.get("todo") or [] if isinstance(x, dict)]
        for i, x in enumerate(lines):
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.addWidget(plain(f"{B.TODO_LABEL.get(x.get('k'), 'Do')}: {x.get('t') or ''}"), 1)
            if author:
                rest = [y for j, y in enumerate(lines) if j != i]
                rl.addWidget(small("✕", lambda rest=rest: self.win.change({"op": "set_todo", "date": u["id"], "lines": rest}),
                                   "Take this line off"))
            self.todo_lay.addWidget(row)
        every = [x for x in B.every_clean(self.win.doc.get("every") or []) if _every_on(self.win.doc, x, u.get("opens"))]
        for x in every:
            self.todo_lay.addWidget(plain(f"{B.TODO_LABEL.get(x.get('k'), 'Do')}: {x.get('t') or ''} · every week", muted=True))
        self.todo_box.setVisible(bool(lines or every))
        self.todo_head.setVisible(author or bool(lines or every))

    def busy_changed(self):
        idle = not self.win.busy
        for w in (self.fields, self.adds, self.todo_links):
            w.setEnabled(idle)
        has = bool(self._cids())
        self.browse_btn.setVisible(has)
        self.study_btn.setVisible(has)
        self.study_btn.setEnabled(idle)

    # ---- an author's changes ----

    def _rename(self):
        if self._loading or self.u is None:
            return
        name = " ".join(self.name.text().split())
        if name and name != self.u.get("name"):
            self.win.change({"op": "rename", "date": self.u["id"], "name": name})

    def _days_changed(self):
        u = self.u
        if u is None or not self.win.author():
            return
        opens = _iso(self.opens.date())
        due = None if self.due.date() == self.due.minimumDate() else _iso(self.due.date())
        if opens != u["opens"]:
            if self.tab.day_taken(opens, u["id"]):
                self.win.change({"op": "move", "date": u["id"], "to": opens})
            else:
                self.show_date(u)
            return
        if due != (u.get("due") or None):
            if due and due < opens:
                due = None
            self.win.change({"op": "set_due", "date": u["id"], "due": due})

    def _nudge(self, k):
        u = self.u
        if u is not None:
            day = E._later(u["opens"], k)
            if self.tab.day_taken(day, u["id"]):
                self.win.change({"op": "move", "date": u["id"], "to": day})

    def _move_from(self):
        u = self.u
        if u is None:
            return
        after = sum(1 for x in P.units(self.win.doc) if str(x.get("opens")) > str(u["opens"]))
        dlg = MoveFromDialog(self, u.get("name") or "this date", after)
        if dlg.exec():
            self.win.change({"op": "move_from", "date": u["id"], "days": dlg.days()})

    def _tested_on(self, _i):
        if self._loading or self.u is None:
            return
        eid, u = self.event.currentData(), self.u
        if eid == "new":
            self.tab.new_event(for_uid=u["id"])
            self.show_date(u)
            return
        if eid != u.get("for"):
            self.win.change({"op": "set_for", "date": u["id"], "event": eid})

    def _add_cards(self):
        u, idx = self.u, self.win.idx
        if u is None:
            return

        def peek(q):
            if idx is None:
                return None
            try:
                return sum(1 for c in idx.col.find_cards(str(q)) if int(c) in idx.cards)
            except Exception:
                return 0  # one this Anki can't read finds nothing
        dlg = DD.AddCardsDialog(self, f"Add cards to {P.fmt_day(u['opens'])}", peek)
        if not dlg.exec():
            return
        what = dlg.what()
        if not what:
            return
        kind, x = what
        if kind == "search":
            n = len(idx.search_cards(x)) if idx is not None else None
            self.win.change({"op": "add_search", "date": u["id"], "q": x, "n": n})
        elif kind in ("nids", "cids"):
            self.win.change({"op": "add_ids", "date": u["id"], "kind": kind, "ids": list(x)})
        else:
            self.win.change({"op": "add_picks", "date": u["id"], "notes": list(x["notes"]),
                             "cards": [list(c) for c in x["cards"]]})

    def _biggest(self):
        t = self.win.deck_tree()
        if t is None or self.u is None or self.win.swap:
            return None
        return B.biggest(t, self.u, B.placed_keys(self.win.doc, t))

    def _split_biggest(self):
        k = self._biggest()
        if k:
            self.split((B.kind_of(k), B.path_of(k)))

    def split(self, key):
        """Split… on a tag or a subdeck of the date: evenly over N study days, or into its own tags."""
        u, win = self.u, self.win
        t = win.deck_tree()
        if u is None or t is None or key[0] not in ("tag", "deck"):
            return
        field, path = ("tags" if key[0] == "tag" else "decks"), key[1]
        tk = f"{key[0]}:{path}"
        placed = B.placed_keys(win.doc, t)
        others = placed - {tk}
        kids = [k for k in t.kids(tk) if not B.is_placed(k, others) and B.eff(t, k, others) > 0] if not win.swap else []
        total = B.eff(t, tk, others) or len(self._cids())
        pace = (win.doc.get("pace") or {})
        cap = 0 if pace.get("mode") == "placed" else max(1, int(pace.get("daily") or 20))
        days = pace.get("days") or [1] * 7
        rest = t.only(tk) if kids else 0
        parts = " · ".join(f"{B.tag_word(B.path_of(k).split('::')[-1])} {B.eff(t, k, others):,}" for k in kids[:6])
        if len(kids) > 6:
            parts += f" · {len(kids) - 6} more"
        if kids and rest > 0:
            parts += f" · the rest {rest:,}"
        dlg = DD.SplitDialog(self, B.tag_word(path.split("::")[-1]), total, parts, cap, -(-total // cap) if cap else 3)
        if not dlg.exec():
            return
        how = dlg.value()
        if how[0] == "even":
            dd = B._Days(win.doc, days)
            ds, d = [], dd.first(u["opens"])
            while len(ds) < how[1]:
                ds.append(d)
                d = dd.next(d)
            win.change({"op": "split_even", "date": u["id"], "source": [key[0], path], "days": ds})
            return
        items = [{"key": k, "n": B.eff(t, k, others)} for k in kids]
        if rest > 0:
            items.append({"key": tk, "n": rest, "rest": True, "even": bool(cap) and rest > cap})
        win.change({"op": "split_tags", "date": u["id"], "field": field, "path": path, "items": items,
                    "cap": cap, "days": days})

    def _review_day(self):
        if self.u is not None:
            self.tab.review_day(self.u["opens"])

    def _todo(self):
        u = self.u
        if u is None:
            return
        dlg = DD.LinesDialog(self, f"To do on {P.fmt_day(u['opens'])}", u.get("todo") or [])
        if dlg.exec():
            self.win.change({"op": "set_todo", "date": u["id"], "lines": dlg.lines()})

    def _every(self):
        dlg = DD.LinesDialog(self, "Every week", self.win.doc.get("every") or [], every=True)
        if dlg.exec():
            self.win.change({"op": "set_every", "lines": dlg.lines()})

    def _study(self):
        u = self.u
        if u is None:
            return
        if self.win.own_steps():
            self.win.study("date", u["id"])
        else:
            self.win.study("date", u["id"], self._cids(), str(u.get("name") or "date"))

    # ---- a chip's menu, and ⋯ ----

    def _chip_menu(self, r, pos):
        win, u = self.win, self.u
        menu = QMenu(self)
        cids, name = set(r["cids"]), f"{u.get('name') or 'date'}: {chip_name(r)}"
        menu.addAction(f"Show these {len(cids):,} in Browse").triggered.connect(lambda: win.ops.browse(cids))
        a = menu.addAction("Study these")
        a.setEnabled(bool(cids) and not win.busy)
        a.triggered.connect(lambda: win.study("date", u["id"], cids, name))
        if win.author():
            a = menu.addAction("Open these in my Anki now")
            a.setEnabled(bool(cids) and not win.busy)
            a.triggered.connect(lambda: win.open_date(u["id"], cids, name))
            key = r["key"]
            menu.addSeparator()
            if key[0] in ("tag", "deck") and win.idx is not None:
                menu.addAction("Split it…").triggered.connect(lambda: self.split((key[0], key[1])))
            if key[0] in ("tag", "cut") and P.plan_tags(win.doc) and not self.tab.own_tag(key[1]):
                cm = menu.addMenu("Keep only cards also tagged")
                now = key[2] if key[0] == "cut" else None
                for label, pid in [("All of it", None)] + [(t.get("name") or "?", t.get("id")) for t in P.plan_tags(win.doc)]:
                    act = cm.addAction(label)
                    act.setCheckable(True)
                    act.setChecked(pid == now)
                    act.triggered.connect(lambda _=False, pid=pid, tag=key[1]: win.change(
                        {"op": "set_cut", "date": u["id"], "tag": tag, "ptag": pid}))
            ex = self.tab.extras(u, key)
            if ex:
                path, without, kids, main_n = ex
                n_ex = max(0, (len(cids) - main_n)) if not without else 0
                label = (f"Leave out its extras ({n_ex:,} cards)" if not without and n_ex else
                         "Leave out its extras" if not without else "Put its extras back")
                menu.addAction(label).triggered.connect(lambda: win.change(
                    {"op": "set_extras", "date": u["id"], "path": path, "without": not without, "kids": kids, "main_n": main_n}))
            if key[0] in ("tag", "cut"):
                menu.addAction("A note for followers on it…").triggered.connect(lambda: self.tab.remark(key[1]))
            menu.addSeparator()
            menu.addAction("Take it off this date").triggered.connect(
                lambda: win.change({"op": "take_cards", "date": u["id"], "key": list(key)}))
        menu.exec(pos)

    def _more(self):
        """⋯, as it opens: each entry says what it does to the date's cards."""
        menu, win, u = self.more_menu, self.win, self.u
        menu.clear()
        if u is None or not win.author():
            return
        if self._biggest() is not None:
            menu.addAction("Split its biggest tag…").triggered.connect(self._split_biggest)
        a = menu.addAction("Make it a review day")
        a.setToolTip("That morning followers get a deck of what they've seen so far")
        a.triggered.connect(self._review_day)
        menu.addSeparator()
        tags = [t for t in P.plan_tags(win.doc)]
        if tags and any(r["key"][0] == "tag" for r in win.rows(u)):
            keep = menu.addMenu("Keep only cards also tagged…")
            for t in tags:
                keep.addAction(str(t.get("name") or "?")).triggered.connect(lambda _=False, t=t: self._keep_only(t))
        for r in win.rows(u):
            ex = self.tab.extras(u, r["key"])
            if ex and not ex[1]:
                n_ex = max(0, len(r["cids"]) - ex[3])
                menu.addAction(f"Leave out {chip_name(r)}'s extras" + (f" ({n_ex:,} cards)" if n_ex else "")).triggered.connect(
                    lambda _=False, ex=ex: win.change({"op": "set_extras", "date": u["id"], "path": ex[0], "without": True,
                                                       "kids": ex[2], "main_n": ex[3]}))
        if u.get("due") and u["due"] > u["opens"]:
            a = menu.addAction(f"Spread its cards evenly to {P.fmt_day(u['due'])}")
            a.setCheckable(True)
            a.setChecked(bool(u.get("even")))
            a.triggered.connect(lambda on: win.change({"op": "set_even", "date": u["id"], "on": bool(on)}))
        else:
            a = menu.addAction("Spread its cards evenly (give it a finish-by day first)")
            a.setEnabled(False)
        menu.addSeparator()
        menu.addAction("Copy its search for Anki").triggered.connect(self._copy_search)
        a = menu.addAction("Open its cards in my Anki now")
        a.setEnabled(bool(self._cids()) and not win.busy)
        a.triggered.connect(lambda: win.open_date(u["id"], None if win.own_steps() else self._cids(), str(u.get("name") or "")))
        menu.addSeparator()
        a = menu.addAction("Delete this date…")
        a.triggered.connect(self._delete)

    def _keep_only(self, t):
        u, win = self.u, self.win
        for r in win.rows(u):
            if r["key"][0] == "tag" and not self.tab.own_tag(r["key"][1]):
                win.change({"op": "set_cut", "date": u["id"], "tag": r["key"][1], "ptag": t.get("id")})

    def _copy_search(self):
        u = self.u
        parts = [B.anki_search("tag", t) for t in u.get("tags") or []] + [B.anki_search("deck", d) for d in u.get("decks") or []]
        parts += [f"({q})" for q in u.get("search") or []]
        if not parts:
            self.win.status.setText("Its cards are picked one by one: Show in Browse finds them.")
            return
        QApplication.clipboard().setText(" OR ".join(parts) if len(parts) > 1 else parts[0])
        self.win.status.setText("Copied: its search, for Anki's Browse.")

    def _delete(self):
        u = self.u
        if u is None:
            return
        opened = str(u["opens"]) <= self.win.ops.today()
        if confirm(self, f"Delete {P.fmt_day(u['opens'])} · {u.get('name') or '?'}?",
                   ("It comes off the plan. What opened stays open." if opened else "It comes off the plan.")
                   + (" With people following, it waits with your other changes till you send them." if self.win.waiting() else ""),
                   "Delete", danger=True):
            self.win.change({"op": "delete_date", "date": u["id"]}, keep=("gone",))


class EventPanel(QWidget):
    """A quiz or an exam: its name and day, the dates it tests, and taking it off."""

    def __init__(self, win, tab):
        super().__init__()
        self.win, self.tab, self.e = win, tab, None
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)
        self.name = QLineEdit()
        self.name.setMaxLength(60)
        self.name.editingFinished.connect(self._rename)
        root.addWidget(self.name)
        row = QHBoxLayout()
        row.addWidget(plain("On", muted=True))
        self.day = QDateEdit()
        self.day.setCalendarPopup(True)
        self.day.setDisplayFormat("ddd d MMM yyyy")
        self.day.setKeyboardTracking(False)
        self._loading = False
        self._resting = QTimer(self)
        self._resting.setSingleShot(True)
        self._resting.setInterval(700)
        self._resting.timeout.connect(self._moved)
        self.day.dateChanged.connect(lambda _d: None if self._loading else self._resting.start())
        row.addWidget(self.day)
        row.addStretch(1)
        self.day_row = QWidget()
        self.day_row.setLayout(row)
        root.addWidget(self.day_row)
        self.title = role(plain(), "head")
        root.addWidget(self.title)
        self.said = plain(muted=True)
        root.addWidget(self.said)
        self.list = QWidget()
        self.list_lay = QVBoxLayout(self.list)
        self.list_lay.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.list)
        row = QHBoxLayout()
        self.study_btn = QPushButton("Study for it")
        self.study_btn.setAutoDefault(False)
        self.study_btn.clicked.connect(self._study)
        row.addWidget(self.study_btn)
        row.addStretch(1)
        self.take_btn = link("Take it off…", self._take, bad=True)
        row.addWidget(self.take_btn)
        root.addLayout(row)
        root.addStretch(1)

    def show_event(self, e):
        self.e = e
        author = self.win.author()
        self._loading = True
        self.name.setText(str(e.get("name") or ""))
        self.day.setDate(_qd(e.get("day")))
        self._loading = False
        for w in (self.name, self.day_row, self.take_btn):
            w.setVisible(author)
        self.title.setVisible(not author)
        self.title.setText(f"{P.fmt_day(e.get('day'))} · {e.get('name') or '?'}")
        prep = self.tab.prep(e)
        while self.list_lay.count():
            w = self.list_lay.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.deleteLater()
        cids = set()
        for u in prep:
            mine = self.win.idx.match(u, self.win.swap, self.win.doc) if self.win.idx is not None else set()
            cids |= mine
            self.list_lay.addWidget(link(f"{M.date_label(u)}" + (f" · {len(mine):,}" if self.win.idx is not None else ""),
                                         lambda uid=u["id"]: self.tab.pick(("date", uid))))
        self.cids = cids
        if prep:
            c = M.counts(self.win.idx, cids) if self.win.idx is not None and cids else None
            self.said.setText(f"Tests {len(prep):,} date{'s' if len(prep) != 1 else ''}"
                              + (f" · {c['cards']:,} cards, {c['cards'] - c['new']:,} seen" if c else ""))
        else:
            self.said.setText("No date is tested on it yet: pick it as a date's Tested on.")
        self.study_btn.setEnabled(bool(cids) and not self.win.busy)

    def busy_changed(self):
        idle = not self.win.busy
        for w in (self.name, self.day, self.take_btn):
            w.setEnabled(idle)

    def _rename(self):
        if self._loading or self.e is None:
            return
        name = " ".join(self.name.text().split())
        if name and name != self.e.get("name"):
            self.win.change({"op": "rename_event", "event": self.e["id"], "name": name})

    def _moved(self):
        if self.e is None:
            return
        day = _iso(self.day.date())
        if day != self.e.get("day"):
            self.win.change({"op": "move_event", "event": self.e["id"], "to": day})

    def _study(self):
        e = self.e
        if e is None:
            return
        if self.win.own_steps():
            self.win.study("event", e["id"])
        else:
            self.win.study("event", e["id"], self.cids, str(e.get("name") or "the quiz"))

    def _take(self):
        e = self.e
        if e is None:
            return
        n = len(self.tab.prep(e))
        if confirm(self, f"Take {e.get('name') or 'it'} off?",
                   f"{n:,} date{'s' if n != 1 else ''} are tested on it; they stay, tested on nothing." if n
                   else "It comes off the plan.", "Take it off", danger=True):
            self.win.change({"op": "take_event", "event": e["id"]}, keep=("gone",))


class ReviewPanel(QWidget):
    """A review day: the dates it reviews, changed or taken off."""

    def __init__(self, win, tab):
        super().__init__()
        self.win, self.tab, self.r = win, tab, None
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)
        self.title = role(plain(), "head")
        root.addWidget(self.title)
        self.said = plain(muted=True)
        root.addWidget(self.said)
        row = QHBoxLayout()
        self.change_btn = link("Change its dates…", lambda: self.tab.review_day(self.r.get("day")) if self.r else None)
        self.off_btn = link("No review day", self._off, bad=True)
        row.addWidget(self.change_btn)
        row.addWidget(self.off_btn)
        row.addStretch(1)
        root.addLayout(row)
        root.addStretch(1)

    def show_review(self, r):
        self.r = r
        us = self.tab.review_units(r)
        self.title.setText(self.tab.review_label(r))
        self.said.setText(f"That morning, followers get a Due Crew deck of what they've seen from these "
                          f"{len(us):,} date{'s' if len(us) != 1 else ''}, most missed first.")
        for w in (self.change_btn, self.off_btn):
            w.setVisible(self.win.author())

    def busy_changed(self):
        for w in (self.change_btn, self.off_btn):
            w.setEnabled(not self.win.busy)

    def _off(self):
        if self.r:
            self.win.change({"op": "take_review", "day": self.r.get("day")}, keep=("gone",))
