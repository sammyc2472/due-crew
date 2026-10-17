"""Emoji pickers: the cheer dialog (quick picks, an "other" box, a note,
and since 3.9.1 a drawing or a sign: Draw · Sign) and, since 2.9, the crew-emoji dialog, which until then was a bare text box.
Both are built on EmojiPicker. Pure Qt; the caller sends or saves. Nothing
here touches the collection or the network.

The "other" box is a text field that acts like a button: a click opens
the system emoji palette (macOS, Windows), whose pick lands in the field
as typed text; where there is no palette a typed or pasted emoji does the
same. The box only ever holds one emoji: the first cluster of whatever
arrives is kept and anything else is cleared, so a second pick replaces
the first instead of joining it."""

from aqt.qt import (
    QButtonGroup, QColor, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit,
    QPainter, QPen, QPointF, QPushButton, QRectF, Qt, QTabWidget, QVBoxLayout, QWidget,
)

from . import accent, open_emoji_picker, paper_accent
from ..backend.shapes import (DOODLE_H, DOODLE_POINTS, DOODLE_STROKES, DOODLE_W, SIGN_MAX,
                              clean_doodle, clean_emoji)

NOTE_MAX = 80
# the crew-emoji dialog's quick row: faces for a name, not reactions
CREW_EMOJI = ("\U0001F98A", "\U0001F422", "\U0001F989", "\U0001F41D",   # fox, turtle, owl, bee
              "\U0001F335", "\U0001F30A")                               # cactus, wave


class _OtherBox(QLineEdit):
    def __init__(self):
        super().__init__()
        self.setPlaceholderText("other")
        self.setToolTip("Any emoji")
        self.setFixedWidth(66)
        self.setMaxLength(16)  # QString length is UTF-16 units: the rules' own cap

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self.selectAll()  # the next pick replaces what is here
        open_emoji_picker(self)


class EmojiPicker(QWidget):
    """A row of quick picks and, when `any_emoji`, the "other" box. `emoji`
    is the one chosen, or None. `initial`: preselect it (a quick pick, or
    into the box); None picks the first quick pick; "" picks nothing."""

    def __init__(self, emojis, any_emoji=True, initial=None):
        super().__init__()
        self.emoji = None
        self._emojis = list(emojis)
        self._buttons = []
        self.other = None
        self._boxed = ""
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        for em in self._emojis:
            b = QPushButton(em)
            b.setCheckable(True)
            b.setMinimumSize(48, 40)
            b.setStyleSheet(
                "QPushButton { font-size: 22px; padding: 4px 8px; border-radius: 8px;"
                " border: 2px solid transparent; }"
                f"QPushButton:checked {{ border-color: {accent()}; }}")
            b.clicked.connect(lambda _=False, e=em: self._pick(e))
            row.addWidget(b)
            self._buttons.append(b)
        if any_emoji:
            self.other = _OtherBox()
            self.other.setStyleSheet(self._other_css(False))
            self.other.textChanged.connect(self._typed)
            row.addWidget(self.other)
        row.addStretch()
        if initial is None:
            self._pick(self._emojis[0])
        elif initial in self._emojis:
            self._pick(initial)
        elif initial and self.other is not None:
            self._set_other(initial)
            self.emoji = initial

    @staticmethod
    def _other_css(chosen):
        # a small "other" at rest; a chosen emoji at the quick picks' size
        border = f"2px solid {accent()}" if chosen else "1px solid palette(mid)"
        return (f"QLineEdit {{ font-size: {20 if chosen else 12}px; border: {border};"
                " border-radius: 8px; padding: 3px 6px; min-height: 30px; }")

    def _pick(self, emoji):
        self.emoji = emoji
        for b, em in zip(self._buttons, self._emojis):
            b.setChecked(em == emoji)
        if self.other is not None:
            self._set_other("")

    def _set_other(self, text):
        self._boxed = text
        self.other.blockSignals(True)
        self.other.setText(text)
        self.other.blockSignals(False)
        self.other.setStyleSheet(self._other_css(bool(text)))

    def _typed(self, text):
        prev = self._boxed
        if prev and text.startswith(prev) and len(text) > len(prev):
            text = text[len(prev):]  # a pick landed after the last one: keep the new one
        emoji = clean_emoji(text)
        if not emoji:
            if text:
                self._set_other("")  # letters, or a cluster that doesn't fit
            else:
                self._boxed = ""
                self.other.setStyleSheet(self._other_css(False))
            if prev:
                self._pick(self._emojis[0])
            return
        self._set_other(emoji)
        self.emoji = emoji
        for b in self._buttons:
            b.setChecked(False)


# 3.9.1, doodle cheers: the pad is paper in either theme, like the card it lands on
PAPER, PAPER_LINE, INK = "#fffdf7", "#e6dfcc", "#2b2d29"
PAD_SCALE = 1.25  # the pad on screen, against its 300 x 170 points


class DoodlePad(QWidget):
    """A little pad to draw on with the mouse, a trackpad or a pen. It keeps
    strokes, not pixels: [pen, [(x, y), ...]] in whole points on the 300 x
    170 pad (shapes.clean_doodle), so what's sent is a few KB and drawn
    back on their side. pen: bit 0 thick, bit 1 ink, else my colour."""

    def __init__(self, colour):
        super().__init__()
        self.colour = colour
        self.strokes = []
        self.pen = 1  # my colour, thick
        self._live = None
        self.on_change = None
        self.setFixedSize(round(DOODLE_W * PAD_SCALE), round(DOODLE_H * PAD_SCALE))
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setToolTip("Draw here")

    def points(self):
        return sum(len(p) for _pen, p in self.strokes)

    def doodle(self):
        """What the pad holds, as it's sent, or None when it's blank."""
        if not self.strokes:
            return None
        return clean_doodle({"k": "draw", "s": [[pen] + [n for xy in pts for n in xy] for pen, pts in self.strokes]})

    def undo(self):
        if self.strokes:
            self.strokes.pop()
            self._changed()

    def clear(self):
        if self.strokes:
            self.strokes = []
            self._changed()

    def _changed(self):
        self.update()
        if self.on_change:
            self.on_change()

    def _at(self, event):
        pos = event.position() if hasattr(event, "position") else QPointF(event.pos())
        x = min(DOODLE_W, max(0, round(pos.x() * DOODLE_W / max(1, self.width()))))
        y = min(DOODLE_H, max(0, round(pos.y() * DOODLE_H / max(1, self.height()))))
        return x, y

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or len(self.strokes) >= DOODLE_STROKES or self.points() >= DOODLE_POINTS:
            return
        self._live = [self.pen, [self._at(event)]]
        self.strokes.append(self._live)
        self._changed()

    def mouseMoveEvent(self, event):
        if self._live is None or self.points() >= DOODLE_POINTS:
            return
        x, y = self._at(event)
        lx, ly = self._live[1][-1]
        if abs(x - lx) + abs(y - ly) >= 2:  # a point every couple of points keeps it small and smooth
            self._live[1].append((x, y))
            self._changed()

    def mouseReleaseEvent(self, event):
        self._live = None

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(PAPER_LINE), 1))
        p.setBrush(QColor(PAPER))
        p.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 8, 8)
        p.scale(self.width() / DOODLE_W, self.height() / DOODLE_H)
        for pen, pts in self.strokes:
            qp = QPen(QColor(INK if pen & 2 else self.colour), 6 if pen & 1 else 3)
            qp.setCapStyle(Qt.PenCapStyle.RoundCap)
            qp.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(qp)
            if len(pts) == 1:
                p.drawPoint(QPointF(*pts[0]))
            else:
                for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
                    p.drawLine(QPointF(x0, y0), QPointF(x1, y1))
        p.end()


class CheerDialog(QDialog):
    def __init__(self, parent, name, emojis, any_emoji=True, doodles=True):
        super().__init__(parent)
        self.setWindowTitle(f"Cheer {name}")
        self.setMinimumWidth(360)
        self.note = ""
        lay = QVBoxLayout(self)
        self.picker = EmojiPicker(emojis, any_emoji)
        self.other = self.picker.other  # tools/dialogs.py drops a pick in here
        lay.addWidget(self.picker)
        self.tabs = self.pad = self.sign_edit = None
        if doodles:  # 3.9.1: a drawing, or a sign their Pip holds up; both optional
            self.tabs = QTabWidget()
            self.tabs.setDocumentMode(True)
            self.pad = DoodlePad(paper_accent())
            draw = QWidget()
            dl = QVBoxLayout(draw)
            dl.setContentsMargins(0, 8, 0, 0)
            dl.addWidget(self.pad)
            dl.addLayout(self._tools())
            self.tabs.addTab(draw, "Draw")
            sign = QWidget()
            sl = QVBoxLayout(sign)
            sl.setContentsMargins(0, 8, 0, 0)
            self.sign_edit = QLineEdit()
            self.sign_edit.setPlaceholderText("you've got this")
            self.sign_edit.setMaxLength(SIGN_MAX)
            sl.addWidget(self.sign_edit)
            said = QLabel(f"A few words for your Pip to hold up when it lands. {SIGN_MAX} letters at most.")
            said.setWordWrap(True)
            said.setStyleSheet("font-size: 11px;")
            sl.addWidget(said)
            # the sign as it'll look, on the pad's paper
            self.sign_view = QLabel()
            self.sign_view.setFixedSize(self.pad.size())
            self.sign_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.sign_view.setWordWrap(True)
            self.sign_edit.textChanged.connect(self._sign_changed)
            self._sign_changed("")
            sl.addWidget(self.sign_view)
            sl.addStretch()
            self.tabs.addTab(sign, "Sign")
            lay.addWidget(self.tabs)
        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("Add a note (optional)")
        self.note_edit.setMaxLength(NOTE_MAX)
        lay.addWidget(self.note_edit)
        hint = QLabel("Lands after their next sync.")
        hint.setStyleSheet("font-size: 11px;")
        lay.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Send")
        buttons.accepted.connect(self._send)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.note_edit.setFocus()

    def _tools(self):
        """Two pens (my colour, ink), two widths, Undo, Clear."""
        row = QHBoxLayout()
        row.setSpacing(6)
        colours, widths = QButtonGroup(self), QButtonGroup(self)

        def pen(bit, on):
            self.pad.pen = (self.pad.pen & ~bit) | (bit if on else 0)

        for label, colour, ink in (("My colour", self.pad.colour, False), ("Black", INK, True)):
            b = QPushButton()
            b.setCheckable(True)
            b.setChecked(not ink)
            b.setToolTip(label)
            b.setAccessibleName(label)
            b.setFixedSize(26, 26)
            b.setStyleSheet(f"QPushButton {{ background: {colour}; border-radius: 13px; border: 2px solid palette(base); }}"
                            f"QPushButton:checked {{ border: 2px solid {accent()}; }}")
            b.clicked.connect(lambda _=False, ink=ink: pen(2, ink))
            colours.addButton(b)
            row.addWidget(b)
        for label, thick in (("Thin", False), ("Thick", True)):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setChecked(thick)
            b.clicked.connect(lambda _=False, thick=thick: pen(1, thick))
            widths.addButton(b)
            row.addWidget(b)
        row.addStretch()
        for label, go in (("Undo", self.pad.undo), ("Clear", self.pad.clear)):
            b = QPushButton(label)
            b.clicked.connect(go)
            row.addWidget(b)
        return row

    def _sign_changed(self, text):
        shown = " ".join(str(text).split())
        self.sign_view.setText(shown or "you've got this")
        self.sign_view.setStyleSheet(
            f"QLabel {{ background: {PAPER}; border: 1px solid {PAPER_LINE}; border-radius: 8px; padding: 12px;"
            f" color: {INK if shown else '#b7b1a2'}; font-size: 30px;"
            " font-family: 'Patrick Hand', 'Comic Sans MS', 'Chalkboard SE', 'Segoe Print', 'Bradley Hand', cursive; }")

    @property
    def emoji(self):
        return self.picker.emoji

    @property
    def doodle(self):
        """3.9.1: what the open tab holds, as it's sent, or None."""
        if self.tabs is None:
            return None
        if self.tabs.currentIndex() == 1:
            return clean_doodle({"k": "sign", "t": self.sign_edit.text()})
        return self.pad.doodle()

    def _send(self):
        self.note = " ".join(self.note_edit.text().split())[:NOTE_MAX]
        self.accept()


class EmojiDialog(QDialog):
    """Your crew emoji (2.9): the cheer picker, with faces for a quick row.
    `emoji` after accept: the one picked, or "" when Remove was pressed."""

    def __init__(self, parent, current=""):
        super().__init__(parent)
        self.setWindowTitle("Your Emoji")
        self.setMinimumWidth(380)
        self._removed = False
        lay = QVBoxLayout(self)
        note = QLabel("In front of your name, for your crew and squads.")
        note.setStyleSheet("font-size: 12px;")
        lay.addWidget(note)
        self.picker = EmojiPicker(CREW_EMOJI, True, initial=current or "")
        lay.addWidget(self.picker)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                   | QDialogButtonBox.StandardButton.Cancel)
        if current:
            remove = buttons.addButton("Remove", QDialogButtonBox.ButtonRole.DestructiveRole)
            remove.clicked.connect(self._remove)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    @property
    def emoji(self):
        return "" if self._removed else (self.picker.emoji or "")

    def _remove(self):
        self._removed = True
        self.accept()
