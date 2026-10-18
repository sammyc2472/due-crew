"""3.9.1 (Sam: "the modal for status update is still native, make sure all
modals are in our style"): the board's own sheets. A question before a step
(confirm), one line (ask_text) or one of a few (ask_item), drawn on the
Decks screen in the Cheer window's look (board.sheet_js) when the board is
up; off it (the review screen, Browse, a menu while studying) the Qt ones in
ui, in the board's colours. Either way the answer goes to then(...), and
only a yes does: Cancel, Esc and the backdrop do nothing, as a Qt No did
(but for a confirm's no(), when one question leads to another).

One sheet at a time: a new one drops the one before (its then never runs).
Its id is new each time and the page's answer must name it, so a page can't
answer a question it wasn't asked; the answer comes with the Decks page's
key too (__init__._on_js). A Decks page drawn anew while one is open draws
it again (redraw, at did_render). Main thread."""

import json
import secrets
import traceback
from urllib.parse import unquote

from aqt import mw

from . import app, board

_open = {}  # id -> {"view": ..., "then": ..., "gen": app.generation}


def confirm(title, text, yes, then, danger=False, no=None):
    """then() after a yes. danger: a step that can't be taken back (the
    button in the board's red; Cancel has the focus). no(): after Cancel,
    Esc or the backdrop, for a question that leads to another."""
    if _board(dict(title=title, text=text, yes=yes, danger=danger), lambda a: then(), no):
        return
    from .ui import confirm as qt_confirm
    if qt_confirm(mw, title, text, yes, **({"danger": True} if danger else {})):
        then()
    elif no is not None:
        no()


def confirm_check(title, text, yes, check, then, checked=True, danger=False):
    """confirm, with one box to tick under the words: then(ticked)."""
    if _board(dict(title=title, text=text, yes=yes, danger=danger, check={"label": check, "on": checked}),
              lambda a: then(bool(a.get("check")))):
        return
    from .ui import confirm_check as qt_check
    ok, ticked = qt_check(mw, title, text, yes, check, checked, **({"danger": True} if danger else {}))
    if ok:
        then(ticked)


def ask_text(title, text, then, value="", most=280, hint="", yes="Save"):
    """One line: then(words), as typed (the caller cleans them). The board's
    box takes at most `most`."""
    if _board(dict(title=title, text=text, yes=yes, field={"kind": "text", "value": value, "max": most, "hint": hint}),
              lambda a: then(str(a.get("text") or "")[:most])):
        return
    from .ui import ask_text as qt_text
    words, ok = qt_text(mw, title, text, value)
    if ok:
        then(str(words or "")[:most])


def ask_item(title, text, items, then, at=0, yes="OK"):
    """One of items: then(index)."""
    items = [str(x) for x in items]
    if not items:
        return
    if _board(dict(title=title, text=text, yes=yes, field={"kind": "pick", "items": items, "at": at}),
              lambda a: then(a["at"]) if isinstance(a.get("at"), int) and 0 <= a["at"] < len(items) else None):
        return
    from .ui import ask_item as qt_item
    name, ok = qt_item(mw, title, text, items, at)
    if ok and name in items:
        then(items.index(name))


def _board(view, then, no=None):
    """Draw the sheet on the board, when it's up and in front. False when it
    isn't: Qt asks instead."""
    if not app.board_up() or not _in_front():
        return False
    sid = secrets.token_hex(8)
    _open.clear()
    _open[sid] = {"view": dict(view, id=sid), "then": then, "no": no, "gen": app.generation}
    app.board_eval(board.sheet_js(_open[sid]["view"]))
    return True


def _in_front():
    """Not behind a window of its own: a Qt dialog open over the main window
    (the Friends window's Remove, a plan's Follow), or another window in
    front (Browse's right-click), asks in Qt, over it; the board's sheet
    would sit behind, out of reach."""
    try:
        from aqt.qt import QApplication
        if QApplication.activeModalWidget() is not None:
            return False
        front = QApplication.activeWindow()
        return front is None or front is mw
    except Exception:
        return True


def answer(sid, raw):
    """The page's duecrew:sheet:<id>:<payload>. Anything but the open
    sheet's id, from this profile, does nothing; so does anything but {ok:
    true}."""
    s = _open.get(str(sid))
    if s is None:
        return
    _open.clear()
    if s["gen"] != app.generation:
        return
    try:
        a = json.loads(unquote(str(raw or "")))
    except ValueError:
        return
    if not isinstance(a, dict):
        return
    go = s["then"] if a.get("ok") is True else (lambda _a: s["no"]()) if s["no"] is not None else None
    if go is None:
        return
    try:
        go(a)
    except Exception:
        traceback.print_exc()


def redraw():
    """The Decks page was drawn anew: the sheet that was open goes back up."""
    for s in list(_open.values()):
        if s["gen"] == app.generation:
            app.board_eval(board.sheet_js(s["view"]))
        else:
            _open.clear()
