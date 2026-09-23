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


def accent():
    """Board green, readable on both of Anki's themes. Dialogs rebuild on
    every open, so a theme change is picked up next time."""
    return "#7cc47f" if _night() else "#2e7d32"


def danger():
    return "#ef8383" if _night() else "#d32f2f"


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
