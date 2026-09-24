"""2.12 study rooms: the glue. Main-thread rules as in __init__.

Where the room shows while reviewing, in this order (room_model.placement):
A, a chip in Anki's top bar; B, beside Edit in the bottom bar, for people
who hide the top bar while reviewing; C, a card in the left margin, when
both bars are hidden and the card leaves the margin free. Outside review
the chip is in the top bar. Nothing is ever drawn inside the card, except
the break, which takes the place of the next card after a round ends.

Rooms add no reads: the room rides my week doc, which friends already read
(one write to open, join or leave). The clocks tick in the page.
"""

import datetime

from aqt import mw
from aqt.utils import tooltip

from . import app, board, room_model
from .app import _state, cfg, client, save_cfg


def _accent_pair():
    name = cfg().get("accent") or board.DEFAULT_ACCENT
    shades = board.ACCENTS.get(name, board.ACCENTS[board.DEFAULT_ACCENT])
    return shades["light"][0], shades["dark"][0]


def my_room():
    """My room while it lasts. When it has just ended, the board gets a
    line for it, and the room leaves my week doc."""
    cl = client()
    room = room_model.clean_room(cl.session.get("room"))
    if room is None:
        return None
    if not room_model.is_over(room):
        return room
    ms = room_model.members(_state["entries"], room)
    others = [m for m in ms if not m[2]]
    cl.session.pop("room", None)
    cl.session["room_done"] = {"rounds": room["rounds"], "minutes": room_model.room_minutes(room),
                               "with": room_model.names_line(others),
                               "uids": [(u, n) for u, n, _y in others],
                               "day": _state["labels"][0] if _state["labels"] else ""}
    cl._save_session()
    # after this render: take the room off my week doc
    from aqt.qt import QTimer
    QTimer.singleShot(0, lambda: app.sync(light=True, fetch=False))
    return None


def _done():
    d = client().session.get("room_done")
    if not isinstance(d, dict):
        return None
    if _state["labels"] and d.get("day") and d["day"] != _state["labels"][0]:
        return None  # a day old: gone
    return d


def board_view():
    """For board.render(room=...)."""
    return room_model.board_view(my_room(), _state["entries"],
                                 _state["room_dismissed"], _done())


def _set_room(room, msg):
    cl = client()
    if room:
        cl.session["room"] = room
    else:
        cl.session.pop("room", None)
    cl._save_session()
    for e in _state["entries"] or []:
        if e["you"]:
            e["room"] = room
    app.swap(cfg())
    app.sync(light=True, fetch=False)
    refresh_widgets()
    if msg:
        tooltip(msg)


def open_room():
    from .ui.room_dialog import RoomDialog
    dlg = RoomDialog(mw)
    if not dlg.exec() or not dlg.result_room:
        return
    start, rounds, round_min, brk_min = dlg.result_room
    room = room_model.make_room(client().user_id, start, rounds, round_min, brk_min)
    _set_room(room, "Room open. Your crew sees it on their next refresh.")


def join(key):
    for e in _state["entries"] or []:
        r = e.get("room")
        if r and room_model.cmd_key(r) == key and not room_model.is_over(r):
            _set_room(dict(r), f"You're in {room_model.title(_state['entries'], r)}.")
            return
    tooltip("That room has ended.")


def leave():
    _remove_break()
    _set_room(None, "You left the room.")


def dismiss(key):
    _state["room_dismissed"].add(str(key))
    app.swap(cfg())


def cheer_room():
    from .social import _send_cheer, cheer_allowed
    room = my_room()
    if room:
        crew = [(u, n) for u, n, you in room_model.members(_state["entries"], room) if not you]
    else:
        crew = [tuple(x) for x in (_done() or {}).get("uids") or []]
    emoji = cheer_allowed("\U0001F389", client().rules_stale)
    if not crew or not emoji:
        tooltip("Nobody else in the room yet.")
        return
    for uid, name in crew:
        _send_cheer(uid, name, emoji)


def share_done():
    from .ui import copy_text
    d = _done()
    if d:
        copy_text(room_model.done_share(d))
        tooltip("Copied for the chat.")


def dismiss_done():
    client().session.pop("room_done", None)
    client()._save_session()
    app.swap(cfg())


def study():
    mw.moveToState("overview")


def tuck():
    c = cfg()
    c["room_compact"] = not c.get("room_compact")
    save_cfg(c)
    refresh_widgets()


# ---- the widgets ----

def _bar_hidden(which):
    """Whether Anki hides its top or bottom bar while reviewing (23.10+:
    Preferences), now. Older Ankis have no such setting."""
    pm = mw.pm
    try:
        if not getattr(pm, f"hide_{which}_bar")():
            return False
    except Exception:
        return False
    try:
        mode = getattr(pm, f"{which}_bar_hide_mode")()
        if str(getattr(mode, "name", mode)).upper().endswith("FULLSCREEN"):
            return bool(mw.isFullScreen())
    except Exception:
        pass
    return True


def _eval(web, js):
    try:
        if web is not None:
            web.eval(js)
    except Exception:
        pass


def _webs():
    rv = getattr(mw, "reviewer", None)
    return (getattr(getattr(mw, "toolbar", None), "web", None),
            getattr(rv, "web", None) if mw.state == "review" else None,
            getattr(getattr(rv, "bottom", None), "web", None) if mw.state == "review" else None)


def refresh_widgets():
    """Put the room where it belongs for the screen Anki is on, or take it
    down. Cheap: a few evals, no collection access, no network."""
    top, main, bottom = _webs()
    room = my_room() if client().signed_in else None
    if room is None:
        for web in (top, main, bottom):
            _eval(web, room_model.widget_js("off"))
        return
    data = room_model.widget_data(room, _state["entries"], _accent_pair(),
                                  compact=bool(cfg().get("room_compact")))
    where = (room_model.placement(_bar_hidden("top"), _bar_hidden("bottom"))
             if mw.state == "review" else "chip")
    _eval(top, room_model.widget_js("chip", data if where == "chip" else None))
    _eval(bottom, room_model.widget_js("bottom", data if where == "bottom" else None))
    _eval(main, room_model.widget_js("gutter", data if where == "gutter" else None))


def show_card():
    room = my_room()
    if room is None:
        return
    data = room_model.widget_data(room, _state["entries"], _accent_pair(),
                                  compact=bool(cfg().get("room_compact")))
    web = mw.reviewer.web if mw.state == "review" else mw.web
    _eval(web, room_model.widget_js("card", data))


# ---- the break ----

def _break_due(room):
    p = room_model.phase(room)
    return (p["state"] == "break"
            and _state["room_skip"] != (room_model.room_key(room), p["round"]))


def _show_break(room):
    data = room_model.widget_data(room, _state["entries"], _accent_pair())
    _eval(mw.reviewer.web, room_model.widget_js("break", data))
    _eval(mw.reviewer.bottom.web,
          "var m=document.getElementById('middle');if(m){m.style.visibility='hidden';}")
    try:
        mw.clearStateShortcuts()  # no answering a card nobody can see
    except Exception:
        pass
    try:
        from aqt.sound import av_player
        av_player.stop_and_clear_queue()  # the card under the break keeps quiet
    except Exception:
        pass
    _state["room_break"] = True
    # one refresh per break: who's in the room now, for the chip. At most
    # one light fetch a round (a doc per friend), and only while reviewing.
    mark = (room_model.room_key(room), room_model.phase(room)["round"])
    if _state["room_refreshed"] != mark:
        _state["room_refreshed"] = mark
        app.sync(light=True, fetch=True)


def _remove_break():
    if not _state["room_break"]:
        return
    _state["room_break"] = False
    if mw.state != "review":
        return  # leaving review reset the screen and its shortcuts already
    _eval(mw.reviewer.web, room_model.widget_js("break", None))
    _eval(mw.reviewer.bottom.web,
          "var m=document.getElementById('middle');if(m){m.style.visibility='';}")
    try:
        mw.setStateShortcuts(mw.reviewer._shortcutKeys())
    except Exception:
        pass
    # the card under the break starts now: its timer (Anki's answer time,
    # and Due Crew's study time) and its audio
    card = getattr(mw.reviewer, "card", None)
    try:
        if card is not None:
            if hasattr(card, "start_timer"):
                card.start_timer()
            else:
                import time
                card.timerStarted = time.time()
    except Exception:
        pass
    try:
        mw.reviewer.replayAudio()
    except Exception:
        pass


def swallow(message):
    """While the break is up, answering is off from every direction: the
    shortcuts are cleared, and this drops what a card's own page can still
    send (Enter in a type-in answer box sends "ans")."""
    return bool(_state["room_break"]) and (message == "ans" or message.startswith("ease"))


def on_close():
    """profile_will_close: closing Anki leaves the room. Anki's closing sync
    (or this push) takes it off my week doc; uploads still go while closing."""
    cl = client()
    if cl.signed_in and cl.session.get("room"):
        cl.session.pop("room", None)
        cl._save_session()
        try:
            app.sync(light=True, fetch=False)
        except Exception:
            pass


def skip_break():
    room = my_room()
    if room:
        _state["room_skip"] = (room_model.room_key(room), room_model.phase(room)["round"])
    _remove_break()


def break_ended():
    _remove_break()


# ---- hooks ----

def on_question(card):
    """reviewer_did_show_question: the widgets for the new page, then the
    break if a round ended while the last card was up."""
    if not client().signed_in:
        return
    refresh_widgets()
    room = my_room()
    if room and _break_due(room):
        _show_break(room)


def on_answer(card):
    _eval(getattr(getattr(mw, "reviewer", None), "web", None),
          "window.dcRoomFit && window.dcRoomFit();")


def on_state(new_state, old_state):
    if old_state == "review":
        _state["room_break"] = False  # the review screen and its keys are gone
    if client().signed_in:
        refresh_widgets()


def on_toolbar(*_args):
    if client().signed_in:
        refresh_widgets()


def on_message(cmd, parts):
    """duecrew:room* from any of Anki's webviews. True when handled."""
    arg = parts[2] if len(parts) > 2 else ""
    if cmd == "roomopen":
        open_room()
    elif cmd == "roomjoin" and arg:
        join(":".join(parts[2:]))
    elif cmd == "roomx" and arg:
        dismiss(":".join(parts[2:]))
    elif cmd == "roomleave":
        leave()
    elif cmd == "roomstudy":
        study()
    elif cmd == "roomcheer":
        cheer_room()
    elif cmd == "roomshare":
        share_done()
    elif cmd == "roomdonex":
        dismiss_done()
    elif cmd == "roomcard":
        show_card()
    elif cmd == "roomtuck":
        tuck()
    elif cmd == "roomskip":
        skip_break()
    elif cmd == "roombreakend":
        break_ended()
    else:
        return False
    return True


def start_at(when_local_time, now=None):
    """The next time the clock shows `when_local_time` (a datetime.time):
    today if it's still ahead, else tomorrow. UTC."""
    now = (now or datetime.datetime.now()).astimezone()
    start = now.replace(hour=when_local_time.hour, minute=when_local_time.minute,
                        second=0, microsecond=0)
    if start <= now:
        start += datetime.timedelta(days=1)
    return start.astimezone(datetime.timezone.utc)
