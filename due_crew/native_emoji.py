"""3.9.1: the computer's own emoji picker, for the Cheer window's "other"
(Sam: "the emoji drawer is missing tons that are natively supported. want
the other option to just open the native drawer?"). A page can't open it;
Python can ask the system: the Character Viewer on a Mac (what ⌃⌘Space
opens), Win + . on Windows. Linux has no one picker to ask for: there,
and whenever asking fails, the window opens its own drawer (emoji_drawer).

3.9.2 (Sam: "the custom picker doesn't accept the custom emoji choices"):
the Character Viewer can't type into Anki's web page (Qt's web view never
takes its insert), so a box of ours, a Qt one, sits exactly over the
window's "pick one" (catch), focused, and takes the pick there; the page
gets it (window.dcCheerPicked). Esc, the window's own Esc or close, or
two minutes put the box away. Main thread only (it's a click's command)."""

import ctypes
import ctypes.util
import json
import sys

WAIT_MS = 120000  # the box goes by itself after this long
_box = {"w": None}


def available(platform=None):
    """Whether this computer has a picker we can open."""
    return (platform or sys.platform) in ("darwin", "win32")


def open_picker(platform=None):
    """Open the system's emoji picker over the focused box; True when asked
    (the system takes it from there), False when there's none or it failed."""
    platform = platform or sys.platform
    try:
        if platform == "darwin":
            return _mac()
        if platform == "win32":
            return _windows()
    except Exception:
        return False
    return False


def _mac():
    # [NSApp orderFrontCharacterPalette:nil], through the Objective-C runtime;
    # objc_msgSend is called with its exact prototype each time (arm64 needs it)
    objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    send0 = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(("objc_msgSend", objc))
    send1 = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(("objc_msgSend", objc))
    app = send0(objc.objc_getClass(b"NSApplication"), objc.sel_registerName(b"sharedApplication"))
    if not app:
        return False
    send1(app, objc.sel_registerName(b"orderFrontCharacterPalette:"), None)
    return True


def _windows():
    # Win + . (the emoji panel), pressed and let go, for the focused box
    user32 = ctypes.windll.user32
    win, period, up = 0x5B, 0xBE, 0x0002
    user32.keybd_event(win, 0, 0, 0)
    user32.keybd_event(period, 0, 0, 0)
    user32.keybd_event(period, 0, up, 0)
    user32.keybd_event(win, 0, up, 0)
    return True


def first_emoji(text):
    """What's picked, when it reads as an emoji (not a letter, a digit or a
    space); the page cuts it to its first one. "" otherwise."""
    t = str(text or "").strip()
    if not t or t[0].isalnum() or ord(t[0]) < 0x2190:
        return ""
    return t[:16]


def catch(x, y, w, h, then, gone, platform=None):
    """Our box over the page's "pick one" (x, y, w, h: its place on the page,
    CSS pixels), focused, then the system's picker over it: then(text) with
    the pick, gone() when it's put away unpicked. False when there's no
    picker to ask (then nothing's shown)."""
    drop()
    if not available(platform):
        return False
    from aqt import mw
    from aqt.qt import QLineEdit, QRect, Qt, QTimer

    class Box(QLineEdit):
        def keyPressEvent(self, e):
            if e.key() == Qt.Key.Key_Escape:
                drop()
                gone()
                return
            super().keyPressEvent(e)

    from . import ui
    z = float(mw.web.zoomFactor() or 1.0)
    box = Box(mw.web)
    box.setObjectName("dcEmojiBox")
    box.setPlaceholderText("pick one")
    box.setMaxLength(16)
    box.setAlignment(Qt.AlignmentFlag.AlignCenter)
    box.setStyleSheet(f"QLineEdit#dcEmojiBox {{ border: 2px solid {ui.tone('accent')}; border-radius: {int(10 * z)}px;"
                      f" background: {ui.tone('you-bg')}; color: {ui.tone('ink')}; font-size: {int(18 * z)}px; }}")
    box.setGeometry(QRect(int(x * z), int(y * z), max(24, int(w * z)), max(24, int(h * z))))

    def got(text):
        e = first_emoji(text)
        if e:
            drop()
            then(e)
        elif text:
            box.clear()  # a letter typed: the box is for the picker's pick
    box.textChanged.connect(got)
    _box["w"] = box
    box.show()
    box.raise_()
    box.setFocus()
    QTimer.singleShot(WAIT_MS, lambda b=box: (drop(), gone()) if _box["w"] is b else None)
    if not open_picker(platform):
        drop()
        return False
    return True


def drop():
    """The box away, if it's up."""
    box, _box["w"] = _box["w"], None
    if box is not None:
        try:
            box.hide()
            box.deleteLater()
        except RuntimeError:
            pass


def picked_js(text):
    return "window.dcCheerPicked && window.dcCheerPicked(%s);" % json.dumps(str(text))
