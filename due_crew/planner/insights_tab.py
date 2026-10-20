"""Round five's Insights tab (docs/planner.md), between Plan and Settings:
what the plan asks and holds, read here (insights.py works it out).
Workload: its weeks as bars, the new cards a study day and the reviews a
day they bring on one scale. How much of the deck: the plan's cards of
the deck's, and of each of its parts as the board's topic map splits it
(its By ▾ is the map's, one pick a deck), the part it's mostly in split
again. What's in it: each quiz or exam and
what it tests, the biggest dates (a click: that one on the Plan tab),
cards on two dates, leeches. A plan I follow: the same on my dates, with
what I've seen. Never sent. Drawn when it's looked at, not at every
change. Names are the deck's and the authors': plain text everywhere."""

from aqt.qt import QColor, QFrame, QGridLayout, QHBoxLayout, QPainter, QRectF, QScrollArea, QSizePolicy, Qt, QTimer, QVBoxLayout, QWidget

from ..ui import _mix, esc, role, tone
from . import insights as I
from . import model as M
from . import view as V
from .widgets import Elided, Row, menu_button, plain


class Bar(QWidget):
    """One of the tab's bars: parts [(value, colour key)] end to end, a 2px
    gap between them, on one scale (whole) with the bars beside it. track:
    a value drawn under them as the whole they're of (a part of the deck,
    the deck); line: a value marked across the row's height (the pace), so
    the rows' marks join into one line down a column."""

    def __init__(self, parts, whole, track=None, line=None, tip=None, width=None, height=14):
        super().__init__()
        self.parts, self.whole, self.track, self.line = parts, whole, track, line
        self.setFixedHeight(height)
        if width:
            self.setFixedWidth(width)
        else:
            self.setMinimumWidth(80)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        if tip:
            self.setToolTip(f"<span>{esc(tip)}</span>")

    def paintEvent(self, _e):  # noqa: N802 (Qt's)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        w, h = float(self.width()), 8.0
        y = (self.height() - h) / 2
        at = (lambda v: w * v / self.whole) if self.whole else (lambda v: 0.0)
        if self.track:
            p.setBrush(QColor(tone("line")))
            p.drawRoundedRect(QRectF(0, y, max(3.0, min(w, at(self.track))), h), 3, 3)
        x = 0.0
        for v, key in self.parts:
            if v <= 0 or not self.whole or x >= w:
                continue
            cw = min(max(3.0, at(v)), w - x)
            p.setBrush(QColor(colour(key)))
            p.drawRoundedRect(QRectF(x, y, cw, h), 3, 3)
            x += cw + 2
        if self.line and self.whole:
            p.setBrush(QColor(tone("muted")))
            p.drawRect(QRectF(min(w - 1, at(self.line)), 0, 1, self.height()))
        p.end()


def colour(key):
    """fill: the accent; soft: the accent toward the ground (a part still to
    come of the same thing); over: the amber of a week over the pace."""
    if key == "soft":
        return _mix(tone("accent"), tone("bg"), .5)
    if key == "over":
        return tone("hours")
    return tone("accent")


def _nowrap(w):
    w.setWordWrap(False)
    return w


class InsightsTab(QWidget):
    """One plan's Insights. win: the PlanWindow."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.dirty = True
        self._by = {}  # a way picked here when the window's ops keep none (a render's)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 8, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.viewport().setAutoFillBackground(False)
        outer.addWidget(self.scroll)
        self.body = None

    # ---- the window asks ----

    def shown(self, win):
        return win.doc is not None

    def plan_loaded(self, win):
        """Drawn now if it's the tab in view, else when it's next picked (PlanWindow._tab_changed)."""
        self.dirty = True
        if win.tabs.currentWidget() is self:
            self.draw()

    # ---- drawn ----

    def draw(self):
        self.dirty = False
        at = self.scroll.verticalScrollBar().value()
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 12, 12)
        lay.setSpacing(8)
        self.scroll.setWidget(body)  # the one before goes with it
        body.setAutoFillBackground(False)
        self.body = body
        win, doc = self.win, self.win.doc
        if doc is None:
            lay.addStretch(1)
            return
        if win.idx is None:
            lay.addWidget(plain("This plan's deck isn't in this Anki, so there's nothing here to count.", muted=True))
            lay.addStretch(1)
            return
        per, cards = I.held(win.idx, doc, win.swap)
        if not per:
            lay.addWidget(plain("Nothing to count yet: the plan has no dates.", muted=True))
            lay.addStretch(1)
            return
        self._workload(lay, doc)
        self._gap(lay)
        self._deck(lay, cards)
        self._gap(lay)
        self._contents(lay, doc, per, cards)
        lay.addStretch(1)
        QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(at))

    def _gap(self, lay):
        lay.addSpacing(10)

    def _head(self, lay, text):
        lay.addWidget(role(plain(text), "head"))

    def _workload(self, lay, doc):
        """Its weeks, a row each: new cards a study day against the pace (the
        line down its column) and reviews a day, each on its own scale, never
        added (a study day and a day aren't the same day); the week's quiz or
        exam beside it, for what a peak is before."""
        win = self.win
        t = win.deck_tree()
        pace = V.pace_of(doc)
        asks = V.week_asks(doc, t, pace) if t is not None else {}
        rows = I.workload(doc, asks, win.ops.today())
        self._head(lay, "Workload")
        if not rows:
            lay.addWidget(plain("No new cards on its dates yet.", muted=True))
            return
        words, over = I.workload_words(doc, rows, V.work(doc, t, pace))
        lay.addWidget(plain(words))
        if over:
            lay.addWidget(plain(over, dc="warn"))
        cap = max(w["cap"] for w in rows)
        new_top = max([w["new"] for w in rows] + [cap]) or 1
        rv_top = max(w["reviews"] for w in rows) or 1
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(0)  # the pace's marks meet: one line down the column
        grid.addWidget(_nowrap(plain("New a study day" + (f" · the line, your pace: {cap:,}" if cap else ""), muted=True)),
                       0, 3, 1, 2)
        grid.addWidget(_nowrap(plain("Reviews a day", muted=True)), 0, 5, 1, 2)
        for i, w in enumerate(rows, start=1):
            name = _nowrap(plain(f"Week {w['n']}" + (", this week" if w["now"] else ""), muted=w["past"]))
            if w["now"]:
                role(name, "head")
            grid.addWidget(name, i, 0)
            grid.addWidget(_nowrap(plain(w["span"], muted=True)), i, 1)
            grid.addWidget(_nowrap(plain(", ".join(w["events"]), dc="event")), i, 2)
            tip = I.week_words(w)
            grid.addWidget(Bar([(w["new"], "over" if w["over"] else "fill")], new_top, line=cap or None, tip=tip, height=24), i, 3)
            grid.addWidget(_nowrap(plain(I.new_words(w), dc="warn" if w["over"] else "n")), i, 4)
            grid.addWidget(Bar([(w["reviews"], "fill")], rv_top, tip=tip, height=24), i, 5)
            grid.addWidget(_nowrap(plain(I.reviews_words(w), dc="n")), i, 6)
        grid.setColumnStretch(3, 1)
        grid.setColumnStretch(5, 1)
        lay.addLayout(grid)

    def _deck(self, lay, cards):
        """The plan's cards of the deck's, a bar of the whole deck (a
        follower's: what I've seen, then what's to go); then each part's, on
        one scale, so a part's size reads with what the plan holds of it."""
        win = self.win
        idx = win.idx
        self._head(lay, "How much of the deck")
        total = len(idx.home)
        lay.addWidget(plain(I.deck_words(idx.name.split("::")[-1], len(cards), total)))
        if win.author():
            parts = [(len(cards), "fill")]
        else:
            c = M.counts(idx, cards)
            seen = c["cards"] - c["new"]
            parts = [(seen, "fill"), (c["new"], "soft")]
        meter = QHBoxLayout()
        bar = Bar(parts, total, track=total, tip=I.deck_words("", len(cards), total))
        bar.setMaximumWidth(560)
        meter.addWidget(bar, 1)
        meter.addStretch(0)
        lay.addLayout(meter)
        if not win.author():
            key = QHBoxLayout()
            key.setSpacing(6)
            key.addWidget(_nowrap(plain(f"You've seen {seen:,} of them; {c['new']:,} to go.", muted=True)))
            key.addSpacing(8)
            for label, k in (("Seen", "fill"), ("To go", "soft")):
                key.addWidget(Bar([(1, k)], 1, width=12))
                key.addWidget(_nowrap(plain(label, muted=True)))
                key.addSpacing(6)
            key.addStretch(1)
            lay.addLayout(key)
        tiles, ways = I.deck_split(idx, self._way(idx.did))
        rows, none, inside = I.topics(tiles, cards)
        if not rows:
            return
        lay.addSpacing(4)
        on = next((w for w in ways if w["on"]), None)
        if len(ways) > 1:
            btn, menu = menu_button(f"By {on['name']}" if on else "By", small=True,
                                    tip="How the deck is split: the same as its topic map on the board")
            for w in ways:
                act = menu.addAction(w["name"])
                act.setCheckable(True)
                act.setChecked(bool(w["on"]))
                act.triggered.connect(lambda _=False, k=w["key"]: self._pick(idx.did, k))
            line = QHBoxLayout()
            line.addWidget(btn)
            line.addStretch(1)
            lay.addLayout(line)
        elif on:
            lay.addWidget(_nowrap(plain(f"By {on['name']}", muted=True)))
        self._parts(lay, rows, none)
        if inside:
            name, krows, knone = inside
            lay.addSpacing(4)
            lay.addWidget(_nowrap(plain(f"Inside {name}", muted=True)))
            self._parts(lay, krows, knone)

    def _parts(self, lay, rows, none):
        """A part a row, the plan's share of it filled, every bar on one scale."""
        box = QWidget()
        box.setMaximumWidth(760)
        grid = QGridLayout(box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)
        shown = rows[:12]
        scale = max((r["total"] for r in shown), default=1)
        for i, r in enumerate(shown):
            grid.addWidget(Elided(r["name"]), i, 0)
            words = f"{r['held']:,} of {r['total']:,} · {I.pct(r['held'], r['total'])}"
            grid.addWidget(Bar([(r["held"], "fill")], scale, track=r["total"], tip=f"{r['name']}: {words}"), i, 1)
            grid.addWidget(_nowrap(plain(words, dc="n")), i, 2)
        grid.setColumnMinimumWidth(0, 150)  # an Elided name takes no room of its own
        grid.setColumnStretch(1, 1)
        lay.addWidget(box)
        if len(rows) > len(shown):
            lay.addWidget(plain(f"and {len(rows) - len(shown):,} smaller ones with some of their cards in it", muted=True))
        if none:
            lay.addWidget(plain(I.none_words(none), muted=True))

    def _way(self, did):
        """The deck's way: the topic map's pick for it on this computer (ops.map_by), else the best."""
        get = getattr(self.win.ops, "map_by", None)
        return get(did) if callable(get) else self._by.get(did)

    def _pick(self, did, key):
        """Another way, for the map too (one pick a deck)."""
        put = getattr(self.win.ops, "set_map_by", None)
        if callable(put):
            put(did, key)
        else:
            self._by[did] = key
        self.draw()

    def _contents(self, lay, doc, per, cards):
        win = self.win
        self._head(lay, "What's in it")
        xs = I.exams(doc, per, cards)
        if xs:
            lay.addWidget(_nowrap(plain("Quizzes and exams", muted=True)))
            for x in xs:
                lay.addWidget(self._row(("event", x["id"]), x["day"], x["name"], I.exam_words(x), "event"))
        big = I.biggest(doc, per)
        if big:
            lay.addWidget(_nowrap(plain("Its biggest dates", muted=True)))
            for u, n in big:
                lay.addWidget(self._row(("date", u["id"]), u.get("opens"), u.get("name") or "?", f"{n:,} cards", None))
        lines = []
        two = I.on_two(per)
        if two:
            lines.append(f"{two:,} card{'s are' if two != 1 else ' is'} on two dates or more; each opens with the first.")
        leech = M.counts(win.idx, cards)["leech"]
        if leech:
            lines.append(f"{leech:,} lee{'ches' if leech != 1 else 'ch'} on its dates stay{'' if leech != 1 else 's'} "
                         "shut: a plan never opens one.")
        for w in lines:
            lay.addWidget(plain(w, muted=True))

    def _row(self, key, day, name, words, dc):
        row = Row(key, self._go, margins=(6, 4, 6, 4))
        row.setToolTip("<span>Show it on the Plan tab</span>")
        line = QHBoxLayout()
        line.setSpacing(8)
        d = _nowrap(plain(M.day_words(day), muted=True))
        d.setFixedWidth(56)
        line.addWidget(d)
        line.addWidget(plain(name, dc=dc), 1)
        line.addWidget(_nowrap(plain(words, dc="n")))
        row.lay.addLayout(line)
        return row

    def _go(self, key):
        """A quiz or a date picked here: that one, on the Plan tab."""
        plan = self.win.pages.get("plan")
        if plan is None:
            return
        self.win._show_tab("plan")
        plan.show_key(key)
