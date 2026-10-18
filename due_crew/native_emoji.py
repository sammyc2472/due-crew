"""3.9.1: the computer's own emoji picker, for the Cheer window's "other"
(Sam: "the emoji drawer is missing tons that are natively supported. want
the other option to just open the native drawer?"). A page can't open it;
Python can ask the system: the Character Viewer on a Mac (what ⌃⌘Space
opens), Win + . on Windows. The window has a box focused first, so what's
picked lands there and is picked. Linux has no one picker to ask for:
there, and whenever asking fails, the window opens its own drawer
(emoji_drawer). Main thread only (it's a click's command)."""

import ctypes
import ctypes.util
import sys


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
