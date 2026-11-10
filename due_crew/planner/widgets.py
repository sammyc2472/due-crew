"""A window's first size (3.9.9: the Qt plan window's other small parts went
with it; the HTML plan window and Magic search size themselves here)."""


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
