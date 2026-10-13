"""3.8.0: Share › As a picture, made here (it opened duecrew.com before):
my day, my week, my year or all time, drawn with QPainter from
sharecard.draw, in the site's picture-card look. A preview, a switch for
each number, Story or Link, Light or Dark, then Copy picture or Save….
Sev on my week (3.8.1) is sev.py's drawing, by QtSvg.
Main thread: no collection, no network (the glue counts cheers)."""

import os

from aqt.qt import (
    QApplication, QButtonGroup, QByteArray, QCheckBox, QColor, QComboBox, QDialog, QFileDialog, QFontMetricsF, QHBoxLayout,
    QImage, QLabel, QPainter, QPainterPath, QPen, QPixmap, QPointF, QPushButton, QRadioButton, QRectF, QVBoxLayout, Qt,
)

from . import _night, attach_alive
from .map_card_dialog import _font, _logo, _text
from .. import sharecard as S, sev

BOX_W, BOX_H = 380, 475  # the preview: a story fills it, a link sits in its middle


def measure(s, px, weight):
    return QFontMetricsF(_font(px, weight)).horizontalAdvance(s)


def paint(kind, size, data, on, look="light"):
    """The card as a QImage, at its full size."""
    W, H, ops = S.draw(kind, size, data, on, look, measure)
    pal = S.LOOKS[look]
    img = QImage(W, H, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(pal["bg"]))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    for op in ops:
        if op[0] == "text":
            _o, s, x, y, px, color, weight, align, track = op
            _text(p, s, x, y, px, color, weight, align, track)
        elif op[0] == "rect":
            _o, x, y, w, h, r, color = op
            if r:
                path = QPainterPath()
                path.addRoundedRect(QRectF(x, y, w, h), r, r)
                p.fillPath(path, QColor(color))
            else:
                p.fillRect(QRectF(x, y, w, h), QColor(color))
        elif op[0] == "ring":
            _o, x, y, w, h, r, color, width, dashed = op
            pen = QPen(QColor(color))
            pen.setWidthF(width)
            if dashed:
                pen.setDashPattern([4 / width, 3 / width])  # cards.js: setLineDash([4, 3]), in pixels
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(x, y, w, h), r, r)
        elif op[0] == "logo":
            _o, x, y, h = op
            mark = _logo(look, h)
            if mark is not None:
                p.drawImage(int(x), int(y), mark)
        elif op[0] == "dot":
            _o, x, y, r, color = op
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(color))
            p.drawEllipse(QPointF(x, y), r, r)
        elif op[0] == "sev":
            _o, pose, x, y, z, color = op
            _sev(p, pose, color, QRectF(x, y, z, z))
    p.end()
    return img


def _sev(p, pose, color, rect):
    """Sev, still, in the card's accent: sev.py's one drawing, by QtSvg
    (where this Qt can't read SVG the card goes without)."""
    try:
        from PyQt6.QtSvg import QSvgRenderer
    except Exception:
        return
    r = QSvgRenderer(QByteArray(sev.still(pose, color).encode("utf-8")))
    if r.isValid():
        r.render(p, rect)


class ShareCardDialog(QDialog):
    """The sheet. choose(key) -> {kind, title, data, sizes, file} for the
    picker's key (None without one); options: [(key, label)] for the
    picker (years and All time), value: the one it opens on. priv: where
    my day's and week's switches start (sharecard.privacy). cheers_say:
    what the cheers switch says while the count isn't here."""

    def __init__(self, parent, choose, options=None, value=None, priv=None, tooltip=None, cheers_say=""):
        super().__init__(parent)
        attach_alive(self)
        self._choose, self._priv, self._tip = choose, priv or {}, tooltip or (lambda msg: None)
        self._key, self._on, self._set = value, {}, set()  # set: switches a person has flipped
        self.cheers_say = cheers_say
        row = QHBoxLayout(self)
        self.preview = QLabel()
        self.preview.setFixedSize(BOX_W, BOX_H)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setAccessibleName("The card")
        row.addWidget(self.preview)
        side = QVBoxLayout()
        self.pick = None
        if options:
            self.pick = QComboBox()
            self.pick.setAccessibleName("Which")
            for key, label in options:
                self.pick.addItem(label, key)
            keys = [k for k, _l in options]
            self.pick.setCurrentIndex(keys.index(value) if value in keys else 0)
            self._key = self.pick.currentData()
            self.pick.currentIndexChanged.connect(self._picked)
            side.addWidget(self.pick)
        self.boxes = QVBoxLayout()
        self.boxes.setSpacing(2)
        side.addLayout(self.boxes)
        self.story, self.link = QRadioButton("Story"), QRadioButton("Link")
        self.story.setChecked(True)
        self.size_row = QHBoxLayout()
        self.size_label = QLabel("Size")
        for w in (self.size_label, self.story, self.link):
            self.size_row.addWidget(w)
        self.size_row.addStretch()
        side.addLayout(self.size_row)
        self.light, self.dark = QRadioButton("Light"), QRadioButton("Dark")
        (self.dark if _night() else self.light).setChecked(True)
        look = QHBoxLayout()
        look.addWidget(QLabel("Look"))
        look.addWidget(self.light)
        look.addWidget(self.dark)
        look.addStretch()
        side.addLayout(look)
        # Story/Link and Light/Dark: two choices, not one
        self._g1, self._g2 = QButtonGroup(self), QButtonGroup(self)
        for g, pair in ((self._g1, (self.story, self.link)), (self._g2, (self.light, self.dark))):
            for b in pair:
                g.addButton(b)
                b.toggled.connect(self._draw)
        self.copy = QPushButton("Copy picture")
        self.copy.setDefault(True)
        self.save = QPushButton("Save…")
        self.copy.clicked.connect(self._copy)
        self.save.clicked.connect(self._save)
        buttons = QHBoxLayout()
        buttons.addWidget(self.copy)
        buttons.addWidget(self.save)
        side.addSpacing(12)
        side.addLayout(buttons)
        note = QLabel("Made here, from your own Anki. Nothing is posted.")
        note.setStyleSheet("color: gray; font-size: 11px;")
        note.setWordWrap(True)
        side.addWidget(note)
        side.addStretch()
        row.addLayout(side)
        self.refresh()

    # the card on screen
    def card(self):
        return self._choose(self._key)

    def kind(self):
        return self.card()["kind"]

    def size(self):
        c = self.card()
        return "link" if self.link.isChecked() and "link" in c["sizes"] else c["sizes"][0]

    def look(self):
        return "dark" if self.dark.isChecked() else "light"

    def on(self):
        return dict(self._on)

    def image(self):
        c = self.card()
        return paint(c["kind"], self.size(), c["data"], self.on(), self.look())

    def refresh(self):
        """The switches for the card on screen (a person's flips kept), the
        title, the size row; then the picture."""
        c = self.card()
        self.setWindowTitle(c["title"])
        while self.boxes.count():
            w = self.boxes.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        self.switch = {}
        for key, label, note, start, enabled in S.switches(c["kind"], c["data"], self._priv, self.cheers_say):
            on = enabled and (self._on[key] if key in self._set else start)
            self._on[key] = on
            box = QCheckBox(f"{label} · {note}" if note else label)
            box.setChecked(on)
            box.setEnabled(enabled)
            box.toggled.connect(lambda v, k=key: self._flip(k, v))
            self.boxes.addWidget(box)
            self.switch[key] = box
        two = len(c["sizes"]) > 1
        for w in (self.size_label, self.story, self.link):
            w.setVisible(two)
        self._draw()

    def _flip(self, key, value):
        self._on[key] = value
        self._set.add(key)
        self._draw()

    def _picked(self, _i):
        self._key = self.pick.currentData()
        self.refresh()

    def _draw(self, *_):
        img = self.image()
        try:
            ratio = max(1.0, float(self.devicePixelRatioF()))
        except Exception:
            ratio = 1.0
        pix = QPixmap.fromImage(img.scaled(int(BOX_W * ratio), int(BOX_H * ratio), Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation))
        pix.setDevicePixelRatio(ratio)
        self.preview.setPixmap(pix)

    def _copy(self):
        QApplication.clipboard().setImage(self.image())
        self._tip("Copied. Paste it where your crew is.")

    def _save(self):
        name = f"{self.card()['file']}-{self.size()}.png"
        path, _f = QFileDialog.getSaveFileName(self, "Save the picture", os.path.join(os.path.expanduser("~"), name),
                                               "PNG (*.png)")
        if path:
            if not path.lower().endswith(".png"):
                path += ".png"
            if self.image().save(path, "PNG"):
                self._tip("Saved.")
