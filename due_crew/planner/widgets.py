"""Round five's small parts of the plan windows (docs/planner.md): words,
links, small buttons and menu buttons, a date's sources, rows that pick
(and Month's that drag to another day), bars. Each wears the board's look
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


def keys(seq):
    """A key sequence as this computer writes it ("Ctrl+N", "⌘N")."""
    from aqt.qt import QKeySequence
    return QKeySequence(seq).toString(QKeySequence.SequenceFormat.NativeText)


def tip_keys(tip, seq=None):
    """A tooltip, its key after it."""
    return f"<span>{esc(tip)}" + (f" <b>{esc(keys(seq))}</b>" if seq else "") + "</span>"


def tool(text, fn=None, checkable=False, tip=None, seq=None, bad=False):
    """An action's button, the window's one kind (the boxes' corners and
    height); bad: one that takes something away, in red words."""
    b = QPushButton(str(text))
    b.setProperty("dc", "tool")
    if bad:
        b.setProperty("tone", "bad")
    b.setCheckable(checkable)
    b.setAutoDefault(False)
    if tip or seq:
        b.setToolTip(tip_keys(tip or text, seq))
    if fn is not None:
        b.clicked.connect(lambda _=False: fn())
    return b


def segs(buttons):
    """Buttons side by side as one control: the ends rounded as the boxes,
    the joins square (QSS [pos]); only the ones shown count."""
    shown = [b for b in buttons if not b.isHidden()] or list(buttons)
    for i, b in enumerate(shown):
        mark(b, "pos", "only" if len(shown) == 1 else "first" if i == 0 else "last" if i == len(shown) - 1 else "mid")
    return buttons


def menu_button(text, on_show=None, small=False, tip=None):
    """A button that opens its menu (a chevron at its end, as a box's):
    (button, menu); on_show fills the menu as it opens."""
    from aqt.qt import QMenu
    b = QPushButton(str(text))
    b.setProperty("dc", "menu")
    if small:
        b.setProperty("small", "true")
    b.setAutoDefault(False)
    if tip:
        b.setToolTip(f"<span>{esc(tip)}</span>")
    m = QMenu(b)
    if on_show is not None:
        m.aboutToShow.connect(on_show)
    b.setMenu(m)
    return b, m


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


def flow_box(hspace=6, vspace=6):
    """(a widget whose parts wrap, its FlowLayout)."""
    from aqt.qt import QWidget
    w = QWidget()
    lay = FlowLayout(w, hspace, vspace)
    sp = w.sizePolicy()
    sp.setHeightForWidth(True)
    sp.setHorizontalPolicy(QSizePolicy.Policy.Preferred)
    w.setSizePolicy(sp)
    return w, lay


class Source(QFrame):
    """One of a date's sources, a line of the panel's list: its name (the
    whole of it on hover), its count, and an ✕ for an author. A click
    anywhere on it: its menu (on_click(pos))."""

    def __init__(self, text, n=None, tip=None, on_click=None, on_take=None):
        super().__init__()
        self.setProperty("dc", "src")
        self.on_click = on_click
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 3, 2, 3)
        row.setSpacing(8)
        self.words = Elided(str(text))
        if tip:
            self.words.setToolTip(f"<span>{esc(tip)}</span>")
        row.addWidget(self.words, 1)
        if n is not None:
            k = QLabel(f"{n:,}" if isinstance(n, int) else str(n))
            k.setTextFormat(Qt.TextFormat.PlainText)
            k.setProperty("dc", "n")
            row.addWidget(k)
        if on_take is not None:
            row.addWidget(small("✕", on_take, "Take it off this date"))
        if on_click is not None:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def mousePressEvent(self, e):  # noqa: N802 (Qt's)
        if self.on_click is not None and e.button() == Qt.MouseButton.LeftButton:
            self.on_click(self.mapToGlobal(QPoint(0, self.height())))
            return
        super().mousePressEvent(e)


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


DRAG = "application/x-duecrew-plan-item"  # Month: a date or a quiz dragged to another day


class Row(QFrame):
    """A row of the plan's list (a date, a quiz, a review day, a week's
    head): picked on a click, as the window's own (on: the picked one).
    on_double: a double-click (its name, to change). drag: Month's entries
    carry their key to another day."""

    def __init__(self, key, on_pick, margins=(8, 6, 8, 6), on_double=None, drag=False):
        super().__init__()
        self.setProperty("dc", "row")
        self.key, self.on_pick, self.on_double, self.drag = key, on_pick, on_double, drag
        self._press = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        from aqt.qt import QVBoxLayout
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(*margins)
        self.lay.setSpacing(4)

    def mousePressEvent(self, e):  # noqa: N802 (Qt's)
        if e.button() == Qt.MouseButton.LeftButton and self.on_pick is not None:
            self._press = e.position().toPoint() if hasattr(e, "position") else e.pos()
            self.on_pick(self.key)
            return
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):  # noqa: N802 (Qt's)
        if e.button() == Qt.MouseButton.LeftButton and self.on_double is not None:
            self.on_double(self.key)
            return
        super().mouseDoubleClickEvent(e)

    def mouseMoveEvent(self, e):  # noqa: N802 (Qt's)
        from aqt.qt import QApplication, QDrag, QMimeData
        if not self.drag or self._press is None or not (e.buttons() & Qt.MouseButton.LeftButton):
            return super().mouseMoveEvent(e)
        at = e.position().toPoint() if hasattr(e, "position") else e.pos()
        if (at - self._press).manhattanLength() < QApplication.startDragDistance():
            return
        self._press = None
        data = QMimeData()
        data.setData(DRAG, f"{self.key[0]}|{self.key[1]}".encode("utf-8"))
        d = QDrag(self)
        d.setMimeData(data)
        d.setPixmap(self.grab())
        d.exec(Qt.DropAction.MoveAction)

    def mouseReleaseEvent(self, e):  # noqa: N802 (Qt's)
        self._press = None
        super().mouseReleaseEvent(e)

    def set_on(self, on):
        mark(self, "on", "true" if on else "false")


class DayCell(QFrame):
    """A day of Month's: a date or a quiz dragged onto it moves there
    (on_drop(kind, key, day)); lit while one is over it."""

    def __init__(self, day, on_drop):
        super().__init__()
        self.setProperty("dc", "calday")
        self.day, self.on_drop = day, on_drop
        self.setAcceptDrops(on_drop is not None)

    def _key(self, e):
        md = e.mimeData()
        if not md.hasFormat(DRAG):
            return None
        kind, _, key = bytes(md.data(DRAG)).decode("utf-8", "replace").partition("|")
        return (kind, key) if kind in ("date", "event") and key else None

    def dragEnterEvent(self, e):  # noqa: N802 (Qt's)
        if self._key(e):
            mark(self, "over", "true")
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):  # noqa: N802 (Qt's)
        mark(self, "over", "false")

    def dropEvent(self, e):  # noqa: N802 (Qt's)
        mark(self, "over", "false")
        key = self._key(e)
        if key:
            e.acceptProposedAction()
            self.on_drop(key[0], key[1], self.day)


class Elided(QLabel):
    """One line that ends in … when its column is narrower than it, the
    whole of it in its tooltip: never widens what it's in (Month's days)."""

    def __init__(self, text, dc=None):
        super().__init__()
        self.full = str(text)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(1)
        if dc:
            self.setProperty("dc", dc)
        self.setToolTip(f"<span>{esc(self.full)}</span>")
        self.setText(self.full)

    def resizeEvent(self, e):  # noqa: N802 (Qt's)
        super().resizeEvent(e)
        self.setText(self.fontMetrics().elidedText(self.full, Qt.TextElideMode.ElideRight, max(0, self.width())))


def fit(win, w, h):
    """A window's first size: w x h, or less on a small screen (never past
    what the screen has room for, so nothing opens bigger than the screen)."""
    from aqt.qt import QGuiApplication
    scr = win.screen() if hasattr(win, "screen") and win.screen() is not None else QGuiApplication.primaryScreen()
    if scr is None:
        win.resize(w, h)
        return
    room = scr.availableGeometry()
    win.resize(min(w, int(room.width() * 0.94)), min(h, int(room.height() * 0.9)))
