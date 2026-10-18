"""3.8.0, "What I know" as a picture (and as text): the topic map drawn
here with QPainter, from mapcard.card, in the site's picture-card look.
A preview, Percentages and This week's change, Light or Dark, then Copy
picture, Save…, Copy as text. Made from my own Anki; nothing is sent
(Insights never are). Main thread: no collection, no network."""

import datetime
import os

from aqt.qt import (
    QApplication, QByteArray, QCheckBox, QColor, QDialog, QFileDialog, QFont, QFontMetricsF,
    QHBoxLayout, QImage, QLabel, QPainter, QPainterPath, QPixmap, QPointF, QPushButton, QRadioButton, QRectF,
    QVBoxLayout, Qt,
)

from . import attach_alive, copy_text, note, _night, title
from .. import mapcard as M


def _font(px, weight=400):
    f = QFont()
    f.setPixelSize(max(1, int(px)))
    f.setWeight(QFont.Weight.Bold if weight >= 700 else QFont.Weight.DemiBold if weight >= 600 else QFont.Weight.Normal)
    return f


def _fit(text, width, px, least, weight):
    """(text, size): the biggest size from px down to least that fits
    width, else least with an ellipsis."""
    z = px
    while z > least:
        if QFontMetricsF(_font(z, weight)).horizontalAdvance(text) <= width:
            return text, z
        z -= 2
    fm = QFontMetricsF(_font(least, weight))
    return fm.elidedText(text, Qt.TextElideMode.ElideRight, max(0.0, width)), least


def _wrap(text, width, px, least, weight):
    """([lines], size): the name on one line from px down to 24, else on
    two (broken at a word) from px down to least, else one line cut short."""
    z = px
    while z >= max(least, 24):
        if QFontMetricsF(_font(z, weight)).horizontalAdvance(text) <= width:
            return [text], z
        z -= 2
    words = text.split(" ")
    z = px
    while z >= least and len(words) > 1:
        fm = QFontMetricsF(_font(z, weight))
        for i in range(len(words) - 1, 0, -1):
            a, b = " ".join(words[:i]), " ".join(words[i:])
            if fm.horizontalAdvance(a) <= width and fm.horizontalAdvance(b) <= width:
                return [a, b], z
        z -= 2
    line, z = _fit(text, width, least, least, weight)
    return [line], z


def _logo(look, height):
    """The one-line logo in the card's green, or None where Qt can't read SVG."""
    from .. import logo
    try:
        from PyQt6.QtSvg import QSvgRenderer
    except Exception:
        return None
    src = logo.line_svg("dark" if look == "dark" else "light")
    r = QSvgRenderer(QByteArray(src.encode("utf-8")))
    if not r.isValid():
        return None
    size = r.defaultSize()
    w = int(round(height * size.width() / max(1, size.height())))
    img = QImage(w, int(height), QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r.render(p)
    p.end()
    return img


def _text(p, s, x, y, px, color, weight=400, align="left", track=0.0):
    f = _font(px, weight)
    if track:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, track)
    p.setFont(f)
    p.setPen(QColor(color))
    w = QFontMetricsF(f).horizontalAdvance(s)
    if align == "right":
        x -= w
    elif align == "center":
        x -= w / 2
    p.drawText(QPointF(x, y), s)  # y is the baseline
    return w


def paint(model, look="light"):
    """The card, SIZE x SIZE, as a QImage."""
    pal = M.LOOKS[look]
    W = M.SIZE
    img = QImage(W, W, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(pal["bg"]))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    P = M.PAD
    mark = _logo(look, 30)
    lw = mark.width() if mark is not None else 0
    if mark is not None:
        p.drawImage(int(W - P - lw), int(P), mark)
    brow, bz = _fit(model["eyebrow"], W - 2 * P - lw - 40, 28, 22, 700)
    _text(p, brow, P, P + 26, bz, pal["mut"], 700, track=bz * 0.12)
    title, tz = _fit(model["title"], W - 2 * P, 76, 48, 700)
    _text(p, title, P, P + 112, tz, pal["ink"], 700)
    for t in model["tiles"]:
        _tile(p, t, look, model["pct"])
    fy = W - P + 6
    if model["key"]:  # no numbers: the shades in words
        x = P + _text(p, "Less", P, fy, 32, pal["mut"]) + 16
        for s in range(4):
            path = QPainterPath()
            path.addRoundedRect(QRectF(x, fy - 26, 30, 30), 7, 7)
            p.fillPath(path, QColor(M.fill(look, s)))
            x += 38
        _text(p, "More", x + 8, fy, 32, pal["mut"])
    elif model["foot"]:
        _text(p, model["foot"], P, fy, 32, pal["mut"])
    _text(p, "duecrew.com", W - P, fy, 32, pal["mut"], align="right")
    p.end()
    return img


def _tile(p, t, look, pct):
    if t["w"] < 4 or t["h"] < 4:
        return
    pal = M.LOOKS[look]
    color = M.ink(look, t["shade"])
    path = QPainterPath()
    path.addRoundedRect(QRectF(t["x"], t["y"], t["w"], t["h"]), 22, 22)
    p.fillPath(path, QColor(M.fill(look, t["shade"])))
    pad = min(26.0, t["w"] * 0.12, t["h"] * 0.16)
    small = t["h"] < 150 or t["w"] < 190
    maxw = t["w"] - 2 * pad
    num = "new" if t["k"] is None else f"{t['k']}%"
    if not pct:
        lines, z = _wrap(t["name"], maxw, 34 if small else 44, 18, 650)
        for i, line in enumerate(lines):
            _text(p, line, t["x"] + pad, t["y"] + pad + z * 0.78 + i * z * 1.15, z, color, 650)
        return
    if t["h"] < 120:  # a short tile: the name, then the number, on one line
        mid = t["y"] + t["h"] / 2
        nw = QFontMetricsF(_font(40, 700)).horizontalAdvance(num)
        name, z = _fit(t["name"], maxw - nw - 14, 30, 16, 650)
        _text(p, name, t["x"] + pad, mid + z * 0.35, z, color, 650)
        _text(p, num, t["x"] + t["w"] - pad, mid + 14, 40, color, 700, align="right")
        return
    lines, z = _wrap(t["name"], maxw, 30 if small else 38, 18, 650)
    for i, line in enumerate(lines):
        _text(p, line, t["x"] + pad, t["y"] + pad + z * 0.78 + i * z * 1.15, z, color, 650)
    pz = 44 if small else 64
    if QFontMetricsF(_font(pz, 700)).horizontalAdvance(num) > maxw:
        pz = 30
    by = t["y"] + t["h"] - pad
    w = _text(p, num, t["x"] + pad, by, pz, color, 700)
    if t.get("d"):
        arrow = "↑" if t["d"] > 0 else "↓"
        s = f"{arrow}{abs(t['d'])}"
        bz = 26 if small else 32
        bw = QFontMetricsF(_font(bz, 700)).horizontalAdvance(s) + bz * 0.8
        bh = bz * 1.4
        bx = t["x"] + t["w"] - pad - bw if w + 12 + bw <= maxw else t["x"] + pad
        bt = by - bh + 2 if w + 12 + bw <= maxw else by - pz * 0.82 - 10 - bh
        pill = QPainterPath()
        pill.addRoundedRect(QRectF(bx, bt, bw, bh), bh / 2, bh / 2)
        p.fillPath(pill, QColor(pal["bg"]))
        _text(p, s, bx + bw / 2, bt + bh / 2 + bz * 0.36, bz, pal["g"] if t["d"] > 0 else pal["mut"], 700, align="center")


class MapCardDialog(QDialog):
    """The sheet: the card and its switches. tiles: the map's level on
    screen; prev/since: last week's map, or None (This week's change waits);
    part: a tile's parts are on screen (the change is kept for the top level)."""

    def __init__(self, parent, deck, day, tiles, by="fsrs", prev=None, since="", tooltip=None, part=False):
        super().__init__(parent)
        attach_alive(self)
        self.setWindowTitle(f"What I know · {deck}")
        self._args = (deck, day, tiles, by)
        self._prev, self._since = prev, since
        self._tip = tooltip or (lambda msg: None)
        row = QHBoxLayout(self)
        self.preview = QLabel()
        self.preview.setFixedSize(380, 380)
        self.preview.setAccessibleName("The card")
        row.addWidget(self.preview)
        side = QVBoxLayout()
        self.pct = QCheckBox("Percentages")
        self.pct.setChecked(True)
        self.pct.setToolTip("Off: the names and shades only")
        self.change = QCheckBox("This week's change")
        self.change.setEnabled(prev is not None)
        when = ""
        if prev is not None and since:
            d = datetime.date.fromisoformat(since)
            when = f"Since {d:%a} {d.day} {d:%b}"
        self.change_note = QLabel(when or ("For the whole deck's map, not its parts" if part
                                           else "From next week: it needs last week's map"))
        note(self.change_note).setContentsMargins(24, 0, 0, 0)  # under its box's words
        self.light = QRadioButton("Light")
        self.dark = QRadioButton("Dark")
        (self.dark if _night() else self.light).setChecked(True)
        look = QHBoxLayout()
        look.addWidget(QLabel("Look"))
        look.addWidget(self.light)
        look.addWidget(self.dark)
        look.addStretch()
        for w in (self.pct, self.change, self.light, self.dark):
            w.toggled.connect(self._draw)
        self.copy = QPushButton("Copy picture")
        self.copy.setDefault(True)
        self.save = QPushButton("Save…")
        self.as_text = QPushButton("Copy as text")
        self.copy.clicked.connect(self._copy)
        self.save.clicked.connect(self._save)
        self.as_text.clicked.connect(self._copy_text)
        buttons = QHBoxLayout()
        for b in (self.copy, self.save, self.as_text):
            buttons.addWidget(b)
        small = note(QLabel("Made here, from your own Anki. Nothing is sent."))
        side.addWidget(title(self.windowTitle()))  # the window says what it is (ui.heading)
        self.setWindowTitle("Due Crew")
        side.addSpacing(4)
        for w in (self.pct, self.change, self.change_note):
            side.addWidget(w)
        side.addLayout(look)
        side.addSpacing(12)
        side.addLayout(buttons)
        side.addWidget(small)
        side.addStretch()
        row.addLayout(side)
        self._draw()

    def model(self):
        deck, day, tiles, by = self._args
        on = self.change.isChecked() and self._prev is not None
        return M.card(deck, day, tiles, by, self.pct.isChecked(), self._prev if on else None, self._since if on else "")

    def look(self):
        return "dark" if self.dark.isChecked() else "light"

    def image(self):
        return paint(self.model(), self.look())

    def text(self):
        deck, day, tiles, by = self._args
        on = self.change.isChecked() and self._prev is not None
        return M.text(deck, day, tiles, by, self.pct.isChecked(), self._prev if on else None, self._since if on else "")

    def _draw(self, *_):
        img = self.image()
        try:
            ratio = max(1.0, float(self.devicePixelRatioF()))
        except Exception:
            ratio = 1.0
        side = int(380 * ratio)
        pix = QPixmap.fromImage(img.scaled(side, side, Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation))
        pix.setDevicePixelRatio(ratio)
        self.preview.setPixmap(pix)

    def _copy(self):
        QApplication.clipboard().setImage(self.image())
        self._tip("Copied. Paste it where your crew is.")

    def _copy_text(self):
        copy_text(self.text())
        self._tip("Copied as text.")

    def _save(self):
        deck, day, _t, _b = self._args
        name = f"due-crew-what-i-know-{day}.png"
        path, _f = QFileDialog.getSaveFileName(self, "Save the picture", os.path.join(os.path.expanduser("~"), name),
                                               "PNG (*.png)")
        if path:
            if not path.lower().endswith(".png"):
                path += ".png"
            if self.image().save(path, "PNG"):
                self._tip("Saved.")
