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

from ..backend.firebase import AuthError, TransportError


def copy_text(text):
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
    shade = "dark" if _night() else "light"
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
    from aqt.qt import (QBuffer, QByteArray, QGuiApplication, QIODevice, QImageReader,
                        QLabel, QPixmap, QSize)
    from ..logo import ASPECT, svg
    try:
        ratio = max(1.0, float(QGuiApplication.primaryScreen().devicePixelRatio()))
    except Exception:
        ratio = 1.0
    height = round(width * ASPECT)
    buf = QBuffer()
    data = svg("dark" if _night() else "light", _accent_name()).encode("utf-8")
    buf.setData(QByteArray(data))
    buf.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buf, QByteArray(b"svg"))
    reader.setScaledSize(QSize(round(width * ratio), round(height * ratio)))
    image = reader.read()
    if image.isNull():
        image = _svg_by_renderer(data, round(width * ratio), round(height * ratio))
    if image is None or image.isNull():
        return None
    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(ratio)
    label = QLabel()
    label.setPixmap(pixmap)
    label.setAccessibleName("Due Crew")
    clear = round(width * 40 / 401)  # one square
    label.setContentsMargins(4, 4, 0, clear)  # the dialog's margin makes up the rest
    return label


def danger():
    return "#ef8383" if _night() else "#d32f2f"


def confirm(parent, title, text, yes):
    """The one way to ask before a step that can't be taken back: the button
    says what happens ("Remove", "Leave"), Cancel is the default, and the
    text is plain, because names in it come from the server. Until 2.9 there
    were three styles of this."""
    from aqt.qt import QMessageBox, Qt
    box = QMessageBox(parent or mw)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle(title)
    box.setTextFormat(Qt.TextFormat.PlainText)
    box.setText(text)
    go = box.addButton(yes, QMessageBox.ButtonRole.AcceptRole)
    cancel = box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(cancel)
    box.exec()
    return box.clickedButton() is go


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
