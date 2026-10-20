"""Round five's small parts of the plan windows (docs/planner.md): words,
links, chips that wrap, rows that pick, bars. Each wears the board's look
through the window's style sheet (ui.QSS: QFrame[dc=chip], [dc=row],
QPushButton[dc=link] and the like); none sets a colour, a size or a
margin in a style sheet of its own. Names are the deck's and the
authors': plain text everywhere."""

from aqt.qt import QFrame, QHBoxLayout, QLabel, QLayout, QPoint, QPushButton, QRect, QSize, QSizePolicy, Qt

from ..ui import esc, note


def plain(text="", muted=False, dc=None):
    w = QLabel(str(text))
    w.setTextFormat(Qt.TextFormat.PlainText)
    w.setWordWrap(True)
    if muted:
        note(w)
    if dc:
        w.setProperty("dc", dc)
    return w


def repolish(w):
    """A property the style sheet reads changed: drawn again by it."""
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


def mark(w, key, value):
    """w's style-sheet property `key` set (only when it changes)."""
    if w.property(key) != value:
        w.setProperty(key, value)
        repolish(w)
        for kid in w.findChildren(QLabel):
            repolish(kid)


def link(text, fn=None, bad=False, tip=None):
    """A green link (a flat button in the accent), in the line of words."""
    b = QPushButton(str(text))
    b.setProperty("dc", "link")
    if bad:
        b.setProperty("tone", "bad")
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setAutoDefault(False)
    if tip:
        b.setToolTip(f"<span>{esc(tip)}</span>")
    if fn is not None:
        b.clicked.connect(lambda _=False: fn())
    return b


def pill(text, fn=None, checkable=False, tip=None):
    b = QPushButton(str(text))
    b.setProperty("dc", "pill")
    b.setCheckable(checkable)
    b.setAutoDefault(False)
    if tip:
        b.setToolTip(f"<span>{esc(tip)}</span>")
    if fn is not None:
        b.clicked.connect(lambda _=False: fn())
    return b


def small(text, fn, tip):
    """A chip's ✕ or ✓: small, its tip saying what it does."""
    b = QPushButton(text)
    b.setProperty("dc", "x")
    b.setAutoDefault(False)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setToolTip(f"<span>{esc(tip)}</span>")
    b.clicked.connect(lambda _=False: fn())
    return b


def frame(dc, horizontal=False, margins=(10, 8, 10, 8), spacing=6):
    """A box of the window's (a bar, a strip, a card) and its layout."""
    from aqt.qt import QVBoxLayout
    f = QFrame()
    f.setProperty("dc", dc)
    lay = QHBoxLayout(f) if horizontal else QVBoxLayout(f)
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    return f, lay


class FlowLayout(QLayout):
    """Chips in rows that wrap at the panel's width (Qt has no such layout)."""

    def __init__(self, parent=None, hspace=6, vspace=6):
        super().__init__(parent)
        self._items, self._h, self._v = [], hspace, vspace
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):  # noqa: N802 (Qt's)
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):  # noqa: N802
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):  # noqa: N802
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self):  # noqa: N802
        return True

    def heightForWidth(self, width):  # noqa: N802
        return self._lay(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):  # noqa: N802
        super().setGeometry(rect)
        self._lay(rect, False)

    def sizeHint(self):  # noqa: N802
        return self.minimumSize()

    def minimumSize(self):  # noqa: N802
        size = QSize()
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def clear(self):
        while self._items:
            it = self._items.pop()
            w = it.widget()
            if w is not None:
                w.hide()
                w.deleteLater()

    def _lay(self, rect, test):
        m = self.contentsMargins()
        x, y = rect.x() + m.left(), rect.y() + m.top()
        right, line = rect.right() - m.right(), 0
        for it in self._items:
            w = it.widget()
            if w is not None and w.isHidden():
                continue
            hint = it.sizeHint()
            if x + hint.width() > right + 1 and line > 0:
                x, y, line = rect.x() + m.left(), y + line + self._v, 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._h
            line = max(line, hint.height())
        return y + line - rect.y() + m.bottom()


def flow_box():
    """(a widget whose chips wrap, its FlowLayout)."""
    from aqt.qt import QWidget
    w = QWidget()
    lay = FlowLayout(w)
    sp = w.sizePolicy()
    sp.setHeightForWidth(True)
    sp.setHorizontalPolicy(QSizePolicy.Policy.Preferred)
    w.setSizePolicy(sp)
    return w, lay


class Chip(QFrame):
    """One of a date's sources (or a suggestion): its name, its count, and
    small buttons (✕ takes it off, ✓ / + Add takes a suggestion, ✕ turns it
    down). kind: None, "sug" (dashed), "maybe" (amber), "fresh" (a change
    not sent yet). on_click: the chip itself picked (its menu)."""

    def __init__(self, text, n=None, kind=None, tip=None, on_click=None):
        super().__init__()
        self.setProperty("dc", "chip")
        if kind:
            self.setProperty("kind", kind)
        self.on_click = on_click
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 2, 4 if on_click is None else 6, 2)
        row.setSpacing(4)
        self.words = QLabel(str(text))
        self.words.setTextFormat(Qt.TextFormat.PlainText)
        row.addWidget(self.words)
        if n is not None:
            k = QLabel(f"{n:,}" if isinstance(n, int) else str(n))
            k.setTextFormat(Qt.TextFormat.PlainText)
            k.setProperty("dc", "n")
            row.addWidget(k)
        self.row = row
        if tip:
            self.setToolTip(f"<span>{esc(tip)}</span>")
        if on_click is not None:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    def add(self, w):
        self.row.addWidget(w)
        return w

    def mousePressEvent(self, e):  # noqa: N802 (Qt's)
        if self.on_click is not None and e.button() == Qt.MouseButton.LeftButton:
            self.on_click(self.mapToGlobal(QPoint(0, self.height())))
            return
        super().mousePressEvent(e)


class Row(QFrame):
    """A row of the plan's list (a date, a quiz, a review day, a week's
    head): picked on a click, as the window's own (on: the picked one)."""

    def __init__(self, key, on_pick, margins=(8, 6, 8, 6)):
        super().__init__()
        self.setProperty("dc", "row")
        self.key, self.on_pick = key, on_pick
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        from aqt.qt import QVBoxLayout
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(*margins)
        self.lay.setSpacing(4)

    def mousePressEvent(self, e):  # noqa: N802 (Qt's)
        if e.button() == Qt.MouseButton.LeftButton and self.on_pick is not None:
            self.on_pick(self.key)
            return
        super().mousePressEvent(e)

    def set_on(self, on):
        mark(self, "on", "true" if on else "false")
