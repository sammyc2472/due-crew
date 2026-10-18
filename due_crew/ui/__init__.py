"""Shared dialog plumbing.

attach_alive() must be called once per dialog: it sets dialog._alive and
clears it on the `finished` signal, which Qt emits for every way a dialog
ends (accept, reject, Esc, window close) — unlike closeEvent, which
accept()/reject() skip.

run_bg() runs a job off the main thread and delivers (result, error_code)
back on the main thread, only while the owner is still alive. error_code is
an AuthError code, "NETWORK" for transport failures, or None.
"""

import subprocess
import sys

from aqt import mw
from aqt.qt import QApplication

from ..backend.shapes import AuthError, TransportError


def copy_text(text):
    """Put text on the system clipboard (_clip), and say so on the board's
    link that asked for it (3.8.0, Board in Motion 32: Copied ✓ in place;
    the page knows which link was clicked, and a copy from a dialog finds
    none and shows nothing)."""
    ok = _clip(text)
    try:
        if mw.web:
            mw.web.eval("try{window.dcMotion&&dcMotion.copied();}catch(e){}")
    except Exception:
        pass
    return ok


def _clip(text):
    """Put text on the system clipboard, emoji and all.

    Qt's macOS pasteboard also offers a legacy "traditional Mac plain text"
    flavor, converted through Latin-1 with '?' for anything it can't encode
    — and some apps paste that one, turning every emoji and block glyph
    into '?' (and '·' into '∑'). pbcopy under a UTF-8 locale writes only
    the UTF-8 flavor, so it goes first on macOS; Qt with explicit UTF-8
    mime data is the fallback everywhere else."""
    text = str(text)
    if sys.platform == "darwin":
        try:
            subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True,
                           timeout=5, env={"LC_ALL": "en_US.UTF-8",
                                           "LANG": "en_US.UTF-8",
                                           "PATH": "/usr/bin:/bin"})
            return True
        except Exception:
            pass  # fall through to Qt
    clip = QApplication.clipboard()
    try:
        from aqt.qt import QMimeData
        mime = QMimeData()
        mime.setText(text)
        mime.setData("text/plain;charset=utf-8", text.encode("utf-8"))
        clip.setMimeData(mime)
    except Exception:
        clip.setText(text)
    return True


def open_emoji_picker(edit):
    """Open the system emoji palette over a text field: on macOS the one
    Ctrl-Cmd-Space opens, asked for through AppKit; on Windows the Win-period
    panel, by pressing the keys for the user. Both type the pick into the
    focused field. False where there is no palette (Linux), and the field
    takes a typed or pasted emoji instead. Never raises."""
    edit.setFocus()
    try:
        if sys.platform == "darwin":
            return _mac_character_palette()
        if sys.platform == "win32":
            return _win_emoji_panel()
    except Exception:
        pass
    return False


def _mac_character_palette():
    import ctypes
    objc = ctypes.cdll.LoadLibrary("/usr/lib/libobjc.dylib")
    ctypes.cdll.LoadLibrary("/System/Library/Frameworks/AppKit.framework/AppKit")
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    # objc_msgSend is variadic; a fixed prototype per arity is what makes the
    # arguments land on arm64 (a wrong one here is a crash, not an exception:
    # checked in a real Qt process on an Apple Silicon Mac, 2026-09-23)
    send0 = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(
        ("objc_msgSend", objc))
    send1 = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(
        ("objc_msgSend", objc))
    cls = objc.objc_getClass(b"NSApplication")
    nsapp = send0(cls, objc.sel_registerName(b"sharedApplication")) if cls else None
    if not nsapp:
        return False
    send1(nsapp, objc.sel_registerName(b"orderFrontCharacterPalette:"), None)
    return True


def _win_emoji_panel():
    import ctypes
    user32 = ctypes.windll.user32
    lwin, period, keyup = 0x5B, 0xBE, 0x0002
    for key, flags in ((lwin, 0), (period, 0), (period, keyup), (lwin, keyup)):
        user32.keybd_event(key, 0, flags, 0)
    return True


def _night():
    try:
        from aqt.theme import theme_manager
        return bool(theme_manager.night_mode)
    except Exception:
        return False


def _dark():
    """3.9.1: the board's theme (Settings › Theme), so a window wears what
    the board does; Match Anki follows Anki's night mode."""
    try:
        from ..app import cfg
        theme = cfg().get("theme", "auto")
    except Exception:
        theme = "auto"
    return theme == "dark" if theme in ("light", "dark") else _night()


def tokens():
    """The board's colours for its theme and accent (board.palette), and
    its red for a step that can't be taken back."""
    from ..board import palette
    t = dict(palette("dark" if _dark() else "light", _accent_name()))
    t.update({"bad": danger(), "bad-ink": "#2a1212" if _dark() else "#ffffff"})
    return t


def tone(key):
    """One of the board's colours (tokens) for a label's own style sheet:
    a window in the board's look ignores its palette, so palette(mid) and
    the like would come out Anki's, not the board's."""
    try:
        return tokens()[key]
    except Exception:
        return {"muted": "#7a7a72", "faded": "#aaaaa2", "line": "#e2e2da", "well": "#f2f2ec", "bg": "#ffffff"}.get(key, "#7a7a72")


# 3.9.1 (Sam: "make sure all modals are in our style"): a Qt window in the
# board's look, as its sheets and the Cheer window are: its colours, 8px
# corners, the main action (the window's default button, or a question's
# yes) in the accent, Cancel and the rest outlined; boxes on the board's
# well. The window's frame stays the computer's.
QSS = """
QDialog, QMessageBox, QInputDialog {{ background: {bg}; color: {ink}; }}
QLabel {{ color: {ink}; background: transparent; }}
QCheckBox, QRadioButton {{ color: {ink}; }}
QPushButton {{ background: {bg}; color: {ink}; border: 1px solid {line}; border-radius: 8px; padding: 5px 14px; min-height: 18px; }}
QPushButton:hover {{ background: {well}; }}
QPushButton:pressed {{ background: {you-bg}; }}
QPushButton:focus {{ border-color: {accent}; }}
QPushButton:disabled {{ color: {faded}; border-color: {line}; background: {bg}; }}
QPushButton[dc="go"] {{ background: {accent}; color: {accent-ink}; border-color: {accent}; font-weight: 600; }}
QPushButton[dc="bad"] {{ background: {bad}; color: {bad-ink}; border-color: {bad}; font-weight: 600; }}
QPushButton:checked {{ background: {you-bg}; border-color: {accent}; }}
QPushButton[dc="go"]:disabled, QPushButton[dc="bad"]:disabled {{ background: {well}; color: {faded}; border-color: {line}; }}
QLineEdit, QPlainTextEdit, QTextEdit, QDateEdit, QComboBox {{ background: {bg}; color: {ink}; border: 1px solid {line}; border-radius: 8px; padding: 4px 8px; selection-background-color: {accent}; selection-color: {accent-ink}; }}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QDateEdit:focus, QComboBox:focus {{ border-color: {accent}; }}
QComboBox QAbstractItemView {{ background: {bg}; color: {ink}; border: 1px solid {line}; selection-background-color: {you-bg}; selection-color: {ink}; }}
QListWidget, QListView, QTreeWidget, QTreeView, QTableWidget {{ background: {well}; color: {ink}; border: 1px solid {line}; border-radius: 10px; padding: 2px; }}
QListWidget::item:selected, QListView::item:selected, QTreeView::item:selected, QTableWidget::item:selected {{ background: {you-bg}; color: {ink}; }}
QGroupBox {{ border: 1px solid {line}; border-radius: 10px; margin-top: 14px; padding: 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {muted}; }}
QScrollArea {{ background: transparent; border: none; }}
QToolTip {{ background: {bg}; color: {ink}; border: 1px solid {line}; }}
QFrame[frameShape="4"] {{ border: none; border-top: 1px solid {line}; max-height: 1px; }}
QMessageBox QLabel#qt_msgbox_label {{ font-size: 15px; font-weight: 700; }}
"""


def styled(dialog):
    """The board's look on a Qt window (QSS, and its palette for what paints
    itself; a label's own style sheet takes tone(), as palette(...) there
    would be Anki's);
    as it shows, its default button is the accent, unless it says already
    which is which (confirm's yes). Ticks and radio dots and number boxes
    keep the system's own drawing (a styled one loses its frame or its
    arrows). Never raises: the suite's Qt has none of it."""
    try:
        from aqt.qt import QColor, QPalette
        t = tokens()
        pal = dialog.palette()
        R = QPalette.ColorRole
        for role, key in (("Window", "bg"), ("WindowText", "ink"), ("Base", "bg"), ("AlternateBase", "well"),
                          ("Text", "ink"), ("Button", "bg"), ("ButtonText", "ink"), ("PlaceholderText", "muted"),
                          ("Mid", "muted"), ("Highlight", "accent"), ("HighlightedText", "accent-ink"),
                          ("ToolTipBase", "bg"), ("ToolTipText", "ink")):
            pal.setColor(getattr(R, role), QColor(t[key]))
        dialog.setPalette(pal)  # for what paints itself from it (a chart); labels take tone()
        dialog.setStyleSheet(QSS.format(**t))
        dialog.installEventFilter(_marker(dialog))
    except Exception:
        pass
    return dialog


def _mark(dialog):
    """The default button in the accent (dc="go"), when no button is marked:
    the one the window chose (setDefault, or its button box's OK), never a
    link-like one (flat, or dressed by its own style sheet)."""
    try:
        from aqt.qt import QPushButton
        buttons = dialog.findChildren(QPushButton)
        if any(b.property("dc") for b in buttons):
            return
        for b in buttons:
            if b.isDefault() and not b.isFlat() and not b.styleSheet():
                b.setProperty("dc", "go")
                b.style().unpolish(b)
                b.style().polish(b)
    except Exception:
        pass


_MARKER = []


def _marker(dialog):
    """An event filter, the dialog's child, that marks its buttons as it
    shows: by then its own default is set (and its button box's), and focus
    hasn't yet moved one to whichever button it lands on."""
    if not _MARKER:
        from aqt.qt import QEvent, QObject

        class Marker(QObject):
            def eventFilter(self, obj, ev):
                if ev.type() == QEvent.Type.Show and obj is self.parent():
                    _mark(obj)
                return False
        _MARKER.append(Marker)
    return _MARKER[0](dialog)


def _accent_name():
    from ..board import DEFAULT_ACCENT
    try:
        return (mw.addonManager.getConfig(__name__) or {}).get("accent") or DEFAULT_ACCENT
    except Exception:
        return DEFAULT_ACCENT


def accent():
    """The board's accent (Settings → Accent) in the shade made for Anki's
    current theme. Until 2.9 dialogs were always green. Dialogs rebuild on
    every open, so a change is picked up next time."""
    shade = "dark" if _dark() else "light"
    try:
        from ..board import ACCENTS, DEFAULT_ACCENT
        return ACCENTS.get(_accent_name(), ACCENTS[DEFAULT_ACCENT])[shade][0]
    except Exception:
        return "#7cc47f" if shade == "dark" else "#2e7d32"


def _svg_by_renderer(data, w, h):
    """The image plugin's stand-in: QtSvg's renderer, where the build has
    it. None where it doesn't."""
    try:
        from PyQt6.QtCore import QByteArray, Qt
        from PyQt6.QtGui import QImage, QPainter
        from PyQt6.QtSvg import QSvgRenderer
    except Exception:
        return None
    renderer = QSvgRenderer(QByteArray(data))
    if not renderer.isValid():
        return None
    image = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    return image


def logo_label(width=150):
    """The stacked logo in the user's accent and Anki's theme (2.10), for
    the top of the sign-in and welcome screens, or None if this Qt can't
    draw SVG (then the screen goes without). Drawn at the screen's pixel
    ratio so it stays sharp; one square's width of clear space around it."""
    from aqt.qt import QLabel
    from ..logo import ASPECT, svg
    pixmap = _svg_pixmap(svg("dark" if _dark() else "light", _accent_name()), width, round(width * ASPECT))
    if pixmap is None:
        return None
    label = QLabel()
    label.setPixmap(pixmap)
    label.setAccessibleName("Due Crew")
    clear = round(width * 40 / 401)  # one square
    label.setContentsMargins(4, 4, 0, clear)  # the dialog's margin makes up the rest
    return label


def _svg_pixmap(markup, width, height):
    """An SVG drawn at the screen's pixel ratio, so it stays sharp; None if
    this Qt can't draw SVG."""
    from aqt.qt import QBuffer, QByteArray, QGuiApplication, QIODevice, QImageReader, QPixmap, QSize
    try:
        ratio = max(1.0, float(QGuiApplication.primaryScreen().devicePixelRatio()))
    except Exception:
        ratio = 1.0
    w, h = round(width * ratio), round(height * ratio)
    data = markup.encode("utf-8")
    buf = QBuffer()
    buf.setData(QByteArray(data))
    buf.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buf, QByteArray(b"svg"))
    reader.setScaledSize(QSize(w, h))
    image = reader.read()
    if image.isNull():
        image = _svg_by_renderer(data, w, h)
    if image is None or image.isNull():
        return None
    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


def sev_label(pose="hello", size=64, name="Pip"):
    """3.8.1: Pip in a dialog's corner (Welcome back), in the accent and
    Anki's theme: sev.py's one drawing, still (a Qt window can't play the
    board's motion; it's the frame Reduce motion shows). None if this Qt
    can't draw SVG: the dialog goes without."""
    from aqt.qt import QLabel, Qt
    from ..sev import still
    try:  # 3.8.2: in what it has on from the closet
        from ..closet_flow import look
        mine = look()
    except Exception:
        mine = None
    pixmap = _svg_pixmap(still(pose, accent(), look=mine), size, size)
    if pixmap is None:
        return None
    label = QLabel()
    label.setTextFormat(Qt.TextFormat.PlainText)  # a picture; never markup
    label.setPixmap(pixmap)
    label.setAccessibleName(name)
    return label


def danger():
    return "#ef8383" if _dark() else "#d32f2f"


def warn():
    """The board's warning colour (its "hours" token), for "not in your copy"."""
    return "#dda45c" if _dark() else "#b26a00"


def esc(text):
    """For rich-text labels: anything from the server or a deck goes through this."""
    import html
    return html.escape(str(text))


def confirm(parent, title, text, yes, danger=False):
    """The one way to ask before a step that can't be taken back: the button
    says what happens ("Remove", "Leave"), Cancel is the default, and the
    text is plain, because names in it come from the server. Until 2.9 there
    were three styles of this. 3.9.1: in the board's look, as its sheet
    (sheets.confirm, whose fallback this is): the title in bold over the
    words, no icon, the yes in the accent (danger: the board's red)."""
    box, go = _question(parent, title, text, yes, danger)
    box.exec()
    return box.clickedButton() is go


def confirm_check(parent, title, text, yes, check, checked=True, danger=False):
    """confirm, with one box to tick under the text (3.8.0: "Take its tags
    off my notes too"). Returns (yes, ticked)."""
    from aqt.qt import QCheckBox
    box, go = _question(parent, title, text, yes, danger)
    tick = QCheckBox(check)
    tick.setChecked(bool(checked))
    box.setCheckBox(tick)
    box.exec()
    return box.clickedButton() is go, tick.isChecked()


def _question(parent, title, text, yes, danger):
    from aqt.qt import QMessageBox, Qt
    box = QMessageBox(parent or mw)
    box.setIcon(QMessageBox.Icon.NoIcon)
    box.setWindowTitle(title)
    box.setTextFormat(Qt.TextFormat.PlainText)
    box.setText(title)
    if text:
        box.setInformativeText(text)  # plain too: the box's format holds for both
    go = box.addButton(yes, QMessageBox.ButtonRole.AcceptRole)
    cancel = box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(cancel)
    go.setProperty("dc", "bad" if danger else "go")
    cancel.setProperty("dc", "no")
    styled(box)
    return box, go


def _plain_input(parent, title, label):
    """A QInputDialog whose label is plain text: names in it come from the
    server, and Qt reads a label with a tag in it as rich text."""
    from aqt.qt import QInputDialog, QLabel, Qt
    dlg = QInputDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setLabelText(label)
    for lb in dlg.findChildren(QLabel):
        lb.setTextFormat(Qt.TextFormat.PlainText)
    return styled(dlg)


def ask_text(parent, title, label, text=""):
    """(text, ok), as QInputDialog.getText, with a plain-text label."""
    dlg = _plain_input(parent, title, label)
    dlg.setTextValue(text)
    ok = bool(dlg.exec())
    return dlg.textValue(), ok


def ask_item(parent, title, label, items, current=0):
    """(item, ok), as QInputDialog.getItem (not editable), with a plain-text label."""
    dlg = _plain_input(parent, title, label)
    dlg.setComboBoxItems(list(items))
    dlg.setComboBoxEditable(False)
    if items:
        dlg.setTextValue(items[max(0, min(current, len(items) - 1))])
    ok = bool(dlg.exec())
    return dlg.textValue(), ok


def shared_words(cfg):
    """The numbers the Privacy switches share, as words for a sentence:
    "reviews, time, retention, and streak". '' when none are."""
    words = [w for key, w in (("share_reviews", "reviews"), ("share_time", "time"),
                              ("share_retention", "retention"), ("share_streak", "streak"))
             if cfg.get(key, True)]
    if len(words) <= 2:
        return " and ".join(words)
    return ", ".join(words[:-1]) + f", and {words[-1]}"


def attach_alive(dialog):
    dialog._alive = True
    dialog.finished.connect(lambda _=0: setattr(dialog, "_alive", False))
    styled(dialog)  # 3.9.1: every window that comes here wears the board's look


def run_bg(owner, job, done):
    def worker():
        try:
            result, err = job(), None
        except AuthError as e:
            result, err = None, e.code
        except TransportError:
            result, err = None, "NETWORK"
        except Exception:
            result, err = None, "NETWORK"
        mw.taskman.run_on_main(
            lambda: getattr(owner, "_alive", False) and done(result, err))
    mw.taskman.run_in_background(worker)
