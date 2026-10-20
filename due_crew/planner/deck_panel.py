"""Round five's deck beside the plan (docs/planner.md; Lay it out's tree
before): the deck's tags and subdecks, by resource, by system, or more
(the rest, its subdecks, the plan's own tags), each with its cards and
the date it's on. With a date picked to add to (Add from the deck), its
line says so and a tick puts that tag on it (or takes it off); with
none, ticks are what the plan covers, and the bar under them lays them
out on its study days at its pace (or fits them before the exam, saying
first by how much they'd run past it). Every change is an op through the
window. Names are the deck's: plain text everywhere, escaped in a tip."""

from aqt.qt import (
    QAbstractItemView, QBrush, QColor, QFont, QHBoxLayout, QHeaderView, QLineEdit, QMenu, QPushButton, Qt, QTimer,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..ui import ask_text, confirm, esc, role, tone
from .. import plans as P
from . import build as B
from . import edits as E
from . import model as M
from . import view as V
from .widgets import fit_parts, frame, mark, plain, segs, tool

ROLE = Qt.ItemDataRole.UserRole
PARTS = Qt.ItemDataRole.UserRole + 1  # a search's row of a few parts: its words, fitted to the width
VIEWS = (("resource", "By resource"), ("system", "By system"), ("other", "Other"), ("deck", "Subdecks"), ("plan", "The plan's own tags"))


class DeckPanel(QWidget):
    """The deck, beside the plan. win: the PlanWindow; tab: the PlanTab."""

    def __init__(self, win, tab):
        super().__init__()
        self.win, self.tab = win, tab
        self.target = None      # a date's id: ticks add to it
        self.cover = set()      # what's ticked as the plan's cover, waiting till laid out or kept
        self.dirty = False
        self.pid = None
        self.kinds = {}
        self.view = "resource"
        self._hay = (None, [], {}, {})
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        self.bar, bl = frame("line", horizontal=True, margins=(0, 0, 0, 0), spacing=8)
        said = plain("Ticks add to", muted=True)
        said.setWordWrap(False)
        bl.addWidget(said)
        self.bar_words = role(plain(), "head")
        bl.addWidget(self.bar_words, 1)
        bl.addWidget(tool("Done", self._back, tip="Back to the date"))
        root.addWidget(self.bar)
        row = QHBoxLayout()
        self.head = role(plain("Tick what the plan covers"), "head")
        row.addWidget(self.head)
        row.addStretch(1)
        row.addWidget(tool("Done", self._back, tip="Back to the plan's dates"))
        self.head_row = QWidget()
        self.head_row.setLayout(row)
        root.addWidget(self.head_row)

        views = QHBoxLayout()
        views.setSpacing(0)
        self.view_btns = {}
        for key, label in VIEWS[:2]:
            b = QPushButton(label)
            b.setProperty("dc", "seg")
            b.setCheckable(True)
            b.setAutoDefault(False)
            b.clicked.connect(lambda _=False, key=key: self._view(key))
            views.addWidget(b)
            self.view_btns[key] = b
        self.more_btn = QPushButton("More")
        self.more_btn.setProperty("dc", "seg")
        self.more_btn.setProperty("menu", "true")
        self.more_btn.setCheckable(True)
        self.more_btn.setAutoDefault(False)
        self.more_menu = QMenu(self.more_btn)
        self.more_btn.setMenu(self.more_menu)
        self.more_menu.aboutToShow.connect(self._more)
        # a click opens the menu and would tick the button too: ticked only while its view shows
        self.more_btn.toggled.connect(lambda _on: self.more_btn.setChecked(self.view not in self.view_btns))
        views.addWidget(self.more_btn)
        views.addStretch(1)
        segs(list(self.view_btns.values()) + [self.more_btn])
        root.addLayout(views)
        self.find = QLineEdit()
        self.find.setPlaceholderText("Find a tag or subdeck")
        self._typing = QTimer(self)  # a search waits for a pause: a big deck has 12,000 tags
        self._typing.setSingleShot(True)
        self._typing.setInterval(200)
        self._typing.timeout.connect(self.fill_tree)
        self.find.textChanged.connect(lambda _t: self._typing.start())
        root.addWidget(self.find)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(3)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setTextElideMode(Qt.TextElideMode.ElideMiddle)  # what fit_parts can't fit keeps its end
        h = self.tree.header()
        h.setStretchLastSection(False)
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        h.sectionResized.connect(lambda i, _old, new: i == 0 and self._fit(new))
        self.tree.itemChanged.connect(self._ticked)
        self.tree.itemExpanded.connect(self._expanded)
        self.tree.itemClicked.connect(self._clicked)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._row_menu)
        root.addWidget(self.tree, 1)

        self.fill, fl = frame("foot", margins=(0, 8, 0, 0))
        self.fill_words = plain()
        self.fill_words.setTextFormat(Qt.TextFormat.RichText)
        fl.addWidget(self.fill_words)
        row = QHBoxLayout()
        self.go = QPushButton("Lay them out")
        self.go.setProperty("dc", "go")
        self.go.setAutoDefault(False)
        self.go.clicked.connect(lambda: self._lay(self._go_how))
        row.addWidget(self.go)
        row.addStretch(1)
        fl.addLayout(row)
        links = QHBoxLayout()
        self.alt = tool("Lay them out anyway", lambda: self._lay(self._alt_how))
        self.week = tool("Next week only", lambda: self._lay(("daily", True, None)), tip="Lay out only what fits next week")
        self.keep_btn = tool("Save the ticks only", self._keep, tip="Saves the ticks as what the plan covers, without laying them out")
        for w in (self.alt, self.week, self.keep_btn):
            links.addWidget(w)
        links.addStretch(1)
        fl.addLayout(links)
        root.addWidget(self.fill)
        self.notes_btn = tool("Notes on cards…", self._notes, tip="Notes followers see on a card, written in Browse")
        root.addWidget(self.notes_btn, 0, Qt.AlignmentFlag.AlignLeft)
        self._go_how = self._alt_how = None

    # ---- the window asks ----

    def plan_loaded(self, win):
        doc = win.doc or {}
        if (win.plan or {}).get("id") != self.pid:
            self.pid, self.dirty, self.target = (win.plan or {}).get("id"), False, None
            self.find.setText("")
        if not self.dirty:
            self.cover = set(V.pace_of(doc).get("cover") or [])
        self.kinds = {}
        t = win.deck_tree()
        have = set(B.kinds_below(t, "root:tag", self.kinds)) if t is not None else set()
        for key, b in self.view_btns.items():
            b.setVisible(key in have)
        segs(list(self.view_btns.values()) + [self.more_btn])  # the ends rounded, whichever show
        if self.view in ("resource", "system") and self.view not in have:
            self.view = next((k for k, _l in VIEWS[:2] if k in have), "other" if "other" in have else "deck")
        if self.target and win.unit(self.target) is None:
            self.target = None
        self.fill_tree()
        self._said()

    def set_target(self, uid):
        """Add from the deck: ticks add to this date (None: back to what the plan covers)."""
        self.target = uid
        self.fill_tree()
        self._said()

    def _back(self):
        uid = self.target
        self.tab.back_from_deck()
        if uid:
            self.tab.pick(("date", uid))

    def busy_changed(self, win):
        idle = not win.busy
        self.tree.setEnabled(idle)
        for w in (self.go, self.alt, self.week, self.keep_btn):
            w.setEnabled(idle)

    # ---- views and rows ----

    def _view(self, key):
        self.view = key
        self.fill_tree()

    def _more(self):
        self.more_menu.clear()
        t = self.win.deck_tree()
        have = set(B.kinds_below(t, "root:tag", self.kinds)) if t is not None else set()
        for key, label in VIEWS[2:]:
            if (key == "other" and "other" not in have) or (key == "deck" and (t is None or not t.kids("root:deck"))) \
                    or (key == "plan" and not P.plan_tags(self.win.doc or {})):
                continue
            a = self.more_menu.addAction(label)
            a.setCheckable(True)
            a.setChecked(self.view == key)
            a.triggered.connect(lambda _=False, key=key: self._view(key))

    def _shown(self, key, view=None):
        t, view = self.win.deck_tree(), view or self.view
        if view == "deck":
            return B.kind_of(key) == "deck"
        return B.kind_of(key) == "tag" and view in B.kinds_below(t, key, self.kinds)

    def _where(self, key):
        """("on this date" | "on Thu 22" | "", the date's id) for a row."""
        doc, path = self.win.doc or {}, B.path_of(key)
        field = "tags" if B.kind_of(key) == "tag" else "decks"
        for u in sorted(P.units(doc), key=lambda u: str(u.get("opens") or "")):
            if any(str(x).lower() == path.lower() for x in u.get(field) or []):
                return ("on this date" if u["id"] == self.target else f"on {M.day_words(u['opens'])}"), u["id"]
        return "", None

    def _item(self, key, name=None, kids=True):
        t = self.win.deck_tree()
        path = B.path_of(key)
        where, _uid = self._where(key)
        it = QTreeWidgetItem([name or B.tag_word(path.split("::")[-1]), where, f"{t.n(key):,}"])
        it.setData(0, ROLE, key)
        it.setToolTip(0, f"<span>{esc(path)}</span>")
        it.setTextAlignment(2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        it.setForeground(1, QBrush(QColor(tone("muted"))))
        it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        if kids and [k for k in t.kids(key) if self._shown(k) and t.n(k)]:
            it.addChild(QTreeWidgetItem(["…", "", ""]))  # a stand-in: its children are read when it opens
        return it

    def fill_tree(self):
        self.tree.blockSignals(True)
        self.tree.clear()
        t = self.win.deck_tree()
        if t is None:
            self.tree.blockSignals(False)
            self.fill_words.setText(esc("This plan's deck isn't in this Anki, so there's nothing to tick here."))
            return
        for key, b in self.view_btns.items():
            b.setChecked(self.view == key)
        self.more_btn.setChecked(self.view not in self.view_btns)
        self.more_btn.setText(dict(VIEWS).get(self.view, "More") if self.view not in self.view_btns else "More")
        if self.view == "plan":
            self._plan_rows()
            self.tree.blockSignals(False)
            return
        term = self.find.text().strip().lower()
        if term:
            self._found(t, term)
        else:
            root = "root:deck" if self.view == "deck" else "root:tag"
            for key in t.kids(root):
                if self._shown(key) and t.n(key):
                    self.tree.addTopLevelItem(self._item(key))
            item = self.tree.topLevelItem(0) if self.tree.topLevelItemCount() == 1 else None
            while item is not None:  # one way down: opened to the first choice
                item.setExpanded(True)
                self._expanded(item, marks=False)
                item = item.child(0) if item.childCount() == 1 else None
        self.tree.blockSignals(False)
        self._marks()

    # ---- a search ----

    FOUND_MAX = 200

    def _hay_of(self, t):
        """(tree, [(key, its own name's words, its path's)], {key: the one above}, {key: its path's words}), once a tree."""
        if self._hay[0] is not t:
            up = {k: p for p, ks in t.kids_of.items() for k in ks}
            rows, whole = [], {}
            for key in t.order:
                path = B.path_of(key)
                seg = path.split("::")[-1]
                whole[key] = (path + "\n" + B.tag_name(path)).lower()
                rows.append((key, (seg + "\n" + B.tag_word(seg)).lower(), whole[key]))
            self._hay = (t, rows, up, whole)
        return self._hay

    def _finds(self, t, term, view=None, most=None):
        """The rows with the term in their own name, as written or as it
        reads (or across parts of their path, from where it starts), in the
        deck's order: a tag below one that has it is found only for its own name."""
        _t, rows, up, whole = self._hay_of(t)
        out = []
        for key, own, path in rows:
            if (term in own or (term in path and term not in whole.get(up.get(key), ""))) \
                    and self._shown(key, view) and t.n(key):
                out.append(key)
                if most and len(out) >= most:
                    break
        return out

    def _found(self, t, term):
        """A search, the deck's structure kept (Sam: tags nested in each
        other stay nested): each find under the tags above it, a line of
        them with one way down read as one row (its path, the end kept as
        it narrows); a find with finds below it shows those, one without
        opens onto its own parts. Nothing in this view: the views that have it."""
        found = self._finds(t, term, most=self.FOUND_MAX + 1)
        more = len(found) > self.FOUND_MAX
        found = found[:self.FOUND_MAX]
        if not found:
            self._none_here(t, term)
            return
        _t, _rows, up, _whole = self._hay_of(t)
        hit, show = set(found), set(found)
        for k in found:
            p = up.get(k)
            while p and p in t.order and p not in show:
                show.add(p)
                p = up.get(p)
        below = {}
        for k in sorted(show, key=t.order.get):
            below.setdefault(up.get(k), []).append(k)

        def place(k, above):
            while k not in hit and len(below.get(k) or []) == 1:
                k = below[k][0]
            path = B.path_of(k)
            parts = [B.tag_word(x) for x in (path[len(B.path_of(above)) + 2:] if above else path).split("::")]
            it = self._item(k, name=" \u203a ".join(parts), kids=k in hit and not below.get(k))
            if len(parts) > 2:
                it.setData(0, PARTS, parts)
            for c in below.get(k) or []:
                it.addChild(place(c, k))
            return it
        for k in below.get("root:deck" if self.view == "deck" else "root:tag") or []:
            self.tree.addTopLevelItem(place(k, None))
        for it in self._items():
            if it.childCount() and it.child(0).data(0, ROLE):
                it.setExpanded(True)
        if more:
            self._note(f"The first {self.FOUND_MAX:,}: type more of a name to narrow them.")
        self._fit()

    def _fit(self, w=None):
        """Each long row's path to its width (column 0's, w as it changes): B&B › … › 5 · Parasites and helminths."""
        fm, w, ind = self.tree.fontMetrics(), w or self.tree.columnWidth(0), self.tree.indentation()
        was = self.tree.blockSignals(True)  # a row's words changing isn't a tick
        for it in self._items():
            parts = it.data(0, PARTS)
            if parts:
                depth, p = 1, it.parent()
                while p is not None:
                    depth, p = depth + 1, p.parent()
                it.setText(0, fit_parts(list(parts), w - ind * depth - 32, fm))
        self.tree.blockSignals(was)

    def _note(self, words, view=None):
        it = QTreeWidgetItem([words, "", ""])
        it.setFlags(Qt.ItemFlag.ItemIsEnabled)
        it.setForeground(0, QBrush(QColor(tone("accent" if view else "muted"))))
        if view:
            it.setData(1, ROLE, view)  # a click shows that view's
        self.tree.addTopLevelItem(it)

    def _none_here(self, t, term):
        """Nothing in this view: what the others have ("By system has 4", a click away)."""
        have = [(v, label, len(self._finds(t, term, v, most=self.FOUND_MAX))) for v, label in VIEWS[:4] if v != self.view]
        have = [x for x in have if x[2]]
        self._note(f"Nothing here has \u201c{self.find.text().strip()}\u201d." if have
                   else f"Nothing in this deck has \u201c{self.find.text().strip()}\u201d.")
        for v, label, n in have:
            self._note(f"{label} has {n:,}{'+' if n >= self.FOUND_MAX else ''}", v)

    def _clicked(self, item, _col):
        v = item.data(1, ROLE) if item.data(0, ROLE) is None else None
        if v in dict(VIEWS):
            self._view(v)

    def _plan_rows(self):
        doc = self.win.doc or {}
        for x in P.plan_tags(doc):
            n = len(self.win.idx.plan_tag_cards(doc, x, self.win.swap)) if self.win.idx is not None else 0
            key = f"tag:{P.tag_path(doc, x)}"
            where, _uid = self._where(key)
            it = QTreeWidgetItem([str(x.get("name") or "?"), where, f"{n:,}"])
            it.setData(0, ROLE, key)
            it.setData(1, ROLE, x.get("id"))
            it.setTextAlignment(2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            it.setForeground(1, QBrush(QColor(tone("muted"))))
            if self.target:
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(0, Qt.CheckState.Checked if where == "on this date" else Qt.CheckState.Unchecked)
            self.tree.addTopLevelItem(it)

    def _expanded(self, item, marks=True):
        if item.childCount() == 1 and item.child(0).data(0, ROLE) is None:
            self.tree.blockSignals(True)
            item.takeChild(0)
            t = self.win.deck_tree()
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
        """Each row's tick: on the date picked to add to, or in what the plan covers."""
        t, doc = self.win.deck_tree(), self.win.doc or {}
        placed = B.placed_keys(doc, t)
        muted = QBrush(QColor(tone("muted")))
        u = self.win.unit(self.target) if self.target else None
        on_date = set(B.srcs(u)) if u else set()
        self.tree.blockSignals(True)
        for it in self._items():
            key = it.data(0, ROLE)
            if u is not None:
                on = key in on_date
                it.setCheckState(0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
                it.setDisabled(not on and any(B.under(k, key) for k in on_date))
            else:
                on = B.ticked(self.cover, t, key, self.view, self.kinds)
                it.setCheckState(0, Qt.CheckState.Checked if on else Qt.CheckState.PartiallyChecked
                                 if B.partly(self.cover, key) else Qt.CheckState.Unchecked)
                it.setDisabled(B.covered(self.cover, key) and key not in self.cover)
            if B.is_placed(key, placed) and key not in on_date:
                it.setForeground(0, muted)
                f = QFont(it.font(0))
                f.setItalic(True)
                it.setFont(0, f)
        self.tree.blockSignals(False)
        self._said()

    def _ticked(self, item, col):
        key = item.data(0, ROLE)
        if col != 0 or not key or self.win.busy:
            return
        if self.target:
            u = self.win.unit(self.target)
            if u is None:
                return
            kind, path = B.kind_of(key), B.path_of(key)
            if item.checkState(0) == Qt.CheckState.Checked:
                tags, decks = ([path], []) if kind == "tag" else ([], [path])
                if self.win.swap:
                    tags = [P.swapped(x, (self.win.swap[1], self.win.swap[0])) for x in tags]
                self.win.change({"op": "add_cards", "date": u["id"], "tags": tags, "decks": decks}, keep=("date", u["id"]))
            else:
                self.win.change({"op": "take_cards", "date": u["id"], "key": [kind, path]}, keep=("date", u["id"]))
            return
        self.cover = B.toggle(self.cover, self.win.deck_tree(), key, self.view, self.kinds)
        self.dirty = True
        self._marks()

    # ---- what's ticked, laid out ----

    def _said(self):
        t, doc, win = self.win.deck_tree(), self.win.doc or {}, self.win
        u = win.unit(self.target) if self.target else None
        self.bar.setVisible(u is not None)
        self.head_row.setVisible(u is None)
        if u is not None:
            self.bar_words.setText(M.date_label(u))
        self.fill.setVisible(u is None and win.author())
        self.notes_btn.setVisible(u is None and win.author() and any(
            isinstance(r, dict) and r.get("card") for r in doc.get("remarks") or []))
        if u is not None or t is None:
            return
        pace = V.pace_of(doc)
        placed = B.placed_keys(doc, t)
        left = B.cover_left(t, self.cover, placed)
        daily = int(pace.get("daily") or 20)
        start = B.plan_start(doc, B.next_monday(win.ops.today()))
        ev, end = V.ends_with(doc)
        who = (ev or {}).get("name") or "the end"
        self._go_how = self._alt_how = None
        self.alt.setVisible(False)
        self.week.setVisible(False)
        self.keep_btn.setVisible(self.dirty)
        mark(self.fill, "dc", "foot")
        if not self.cover:
            self.fill_words.setText(esc("Tick what the plan covers; then lay it out on its study days."))
            self.go.setVisible(False)
            return
        if not left:
            self.fill_words.setText(esc("Everything ticked is on a date."))
            self.go.setVisible(False)
            return
        fin = B.finish_by(doc, t, pace, self.cover, start, daily)
        self.go.setVisible(True)
        self.week.setVisible(True)
        b = f"<b>{left:,} ticked, not on a date.</b> "
        if end and fin and fin >= end:
            fit_end = E._later(end, -1) if ev else end
            d1 = B.end_daily(dict(doc, end=fit_end), t, pace, self.cover, start) or daily
            late = (E._day(fin) - E._day(end)).days
            mark(self.fill, "dc", "bad")
            self.fill_words.setText(b + esc(f"At {daily:,} a day they'd end {P.fmt_day(fin)}, ")
                                    + f"<b>{late:,} day{'s' if late != 1 else ''} after {esc(who)}</b>.")
            self.go.setText(f"Fit them before {who}: {d1:,} a day")
            self._go_how = ("end", False, (fit_end, (ev or {}).get("id")))
            self.alt.setText(f"Lay them out at {daily:,} anyway")
            self.alt.setVisible(True)
            self._alt_how = ("daily", False, None)
        elif end and fin:
            self.fill_words.setText(b + esc(f"At {daily:,} a day they end {P.fmt_day(fin)}, before {who}."))
            self.go.setText(f"Lay them out at {daily:,} a day")
            self._go_how = ("daily", False, None)
        else:
            self.fill_words.setText(b + esc(f"At {daily:,} a day they end {P.fmt_day(fin)}." if fin else ""))
            self.go.setText(f"Lay them out at {daily:,} a day")
            self._go_how = ("daily", False, None)

    def _lay(self, how):
        if not how or self.win.busy:
            return
        mode, week_ahead, fit = how
        doc = self.win.doc or {}
        pace = V.pace_of(doc)
        o = {"op": "lay_out", "pace": {"mode": mode, "days": pace.get("days") or [1] * 7, "daily": int(pace.get("daily") or 20)},
             "cover": sorted(self.cover), "start": B.plan_start(doc, B.next_monday(self.win.ops.today())),
             "week_ahead": bool(week_ahead)}
        if fit:
            o["end"], o["aim"] = fit[0], fit[1]

        def done(ok):
            if ok:
                self.dirty = False
        self.win.change(o, then=done)

    def _keep(self):
        doc = self.win.doc or {}
        pace = V.pace_of(doc)
        t = self.win.deck_tree()

        def done(ok):
            if ok:
                self.dirty = False
                self._said()
        self.win.change({"op": "set_pace", "mode": pace.get("mode") or "daily", "days": pace.get("days") or [1] * 7,
                         "daily": pace.get("daily"), "cover": B.cover_items(t, self.cover) if t is not None else sorted(self.cover)},
                        then=done)

    # ---- a row's menu: the plan's own tags, a note on a tag ----

    def _row_menu(self, pos):
        it = self.tree.itemAt(pos)
        if it is None or not it.data(0, ROLE) or not self.win.author():
            return
        key = it.data(0, ROLE)
        menu = QMenu(self)
        where, uid = self._where(key)
        if uid:
            menu.addAction(f"Go to its date ({where.replace('on ', '')})").triggered.connect(lambda: self.tab.pick(("date", uid)))
        if B.kind_of(key) == "tag":
            menu.addAction("A note for followers on it…").triggered.connect(lambda: self.tab.remark(B.path_of(key)))
        tid = it.data(1, ROLE)
        if tid:
            t = next((x for x in P.plan_tags(self.win.doc) if x.get("id") == tid), None)
            if t is not None:
                menu.addSeparator()
                menu.addAction("Rename the tag…").triggered.connect(lambda: self._rename_tag(t))
                menu.addAction("Delete the tag…").triggered.connect(lambda: self._delete_tag(t))
        if menu.actions():
            menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _rename_tag(self, t):
        name, ok = ask_text(self, "Rename the tag", "Its name (40 characters); the dates, searches and notes using it change with it:",
                            str(t.get("name") or ""))
        if ok and name.strip() and name.strip() != t.get("name"):
            self.win.change({"op": "rename_plan_tag", "tag": t["id"], "name": name.strip()})

    def _delete_tag(self, t):
        if confirm(self, f"Delete {t.get('name') or 'the tag'}?", E.drop_say(self.win.doc, t["id"])
                   + " Followers' Anki takes it off their notes.", "Delete it", danger=True):
            self.win.change({"op": "delete_plan_tag", "tag": t["id"]})

    def _notes(self):
        menu = QMenu(self)
        for r in self.win.doc.get("remarks") or []:
            if isinstance(r, dict) and r.get("card") and r.get("id"):
                sub = menu.addMenu(f"{r['card'][0]} · card {int(r['card'][1]) + 1}: {str(r.get('text') or '')[:40]}")
                sub.addAction("Take it off").triggered.connect(
                    lambda _=False, rid=r["id"]: self.win.change({"op": "take_remark", "id": rid}))
        menu.exec(self.notes_btn.mapToGlobal(self.notes_btn.rect().bottomLeft()))
