"""2.12 study rooms: the glue. Main-thread rules as in __init__.

Where the room shows while reviewing, in this order (room_model.placement):
A, a chip in Anki's top bar; B, beside Edit in the bottom bar, for people
who hide the top bar while reviewing; C, a card in the left margin, when
both bars are hidden and the card leaves the margin free. Outside review
the chip is in the top bar. Nothing is ever drawn inside the card, except
the break, which takes the place of the next card after a round ends.

Rooms add no reads: the room rides my week doc, which friends already read
(one write to open, join or leave). The clocks tick in the page.

3.8.1, the Fifteen: ▶ Fifteen? in the top bar (or the nudge) starts fifteen
minutes, a room of mine alone, and Study today opens. When the fifteen ends,
once the card in front of me is answered, one question: take five, then
another fifteen; another now; or stop. Each yes adds one, up to eight. No
answer in five minutes and the session ends quietly. It isn't a room on my
week doc: my crew sees I'm studying now, nothing more (one write to start,
one per yes, one to stop). Sev, if on, keeps me company through it.
"""

import datetime
import html
import time
import traceback

from aqt import mw
from aqt.utils import tooltip

from . import app, board, room_model, sev
from .app import _state, cfg, client, save_cfg


def _closet(do):
    """3.8.2: tell Sev's closet (closet_flow); never in the way of a room."""
    try:
        from . import closet_flow
        do(closet_flow)
    except Exception:
        traceback.print_exc()


def _accent_pair():
    return board.accent_pair(cfg().get("accent"))


def my_room():
    """My room while it lasts. When it has just ended, the board gets a
    line for it, and the room leaves my week doc."""
    cl = client()
    room = room_model.clean_room(cl.session.get("room"))
    if room is None:
        return None
    if not room_model.is_over(room, _now()):
        return room
    if room_model.is_fifteen(room):
        _end_fifteen(room, walked=True)  # no answer to its question: the session ends quietly
        return None
    ms = room_model.members(_state["entries"], room)
    others = [m for m in ms if not m[2]]
    _closet(lambda cf: cf.note_room(bool(others)))  # 3.8.2: a room with my crew
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
    """For board.render(room=...). 3.8.1: a fifteen's question shows its
    cards; the session's line, when one ended today; with Sev on, a crew
    room's members as their Sevs, each in their accent."""
    room = my_room()
    out = room_model.board_view(room, _state["entries"], _state["room_dismissed"], _done(), now=_now(),
                                sev=sev_on(), accent_pair=_accent_pair(), look=my_look())
    mine = out.get("mine")
    if mine and mine.get("fifteen"):
        if mine["state"] == "ask":
            mine["cards"] = _cards_since(room_model.fifteen_round_start(room, room["rounds"]))
        pose = {"ask": "ring", "break": "stretch" if _brk_pose() == "stretch" else "rest"}.get(mine["state"], "focus")
        # its move takes turns a round at a time, as the widgets' do (room_model.FIFTEEN_VARY)
        turn = sev.nth(pose, int(mine.get("n") or 0) + room_model.vary_seed(room))
        mine["sev"] = _sev_markup(pose, rest=pose == "ring" and _state.get("sev_rang") == room["start"], move=turn)
        if pose == "ring":
            _state["sev_rang"] = room["start"]  # the clock rings once a fifteen
    fd = _fifteen_done()
    if fd:
        out["fifteen_done"] = dict(fd, sev=_sev_markup("stack", stack=fd["n"], rest=bool(fd.get("seen")), move=fd.get("move")))
        if not fd.get("seen"):
            fd["seen"] = True  # its stack plays once
    return out


def _set_room(room, msg):
    cl = client()
    if room:
        cl.session["room"] = room
    else:
        cl.session.pop("room", None)
    cl._save_session()
    for e in _state["entries"] or []:
        if e["you"]:
            e["room"] = None if room_model.is_fifteen(room) else room  # 3.8.1: a fifteen is studying now
            e["live_until"] = str(cl.session.get("live_until") or "")
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
    from .bingo_flow import bump
    bump("rm")  # 3.6
    _set_room(room, "Room open. Your crew sees it on their next refresh.")


def join(key):
    for e in _state["entries"] or []:
        r = e.get("room")
        if r and room_model.cmd_key(r) == key and not room_model.is_over(r, _now()):
            from .bingo_flow import bump
            bump("rm")  # 3.6
            _set_room(dict(r), f"You're in {html.escape(room_model.title(_state['entries'], r))}.")  # a crewmate's name
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
    emoji = cheer_allowed("\U0001F389")
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


def _data(room, side=None, **kw):
    c = cfg()
    return room_model.widget_data(room, _state["entries"], _accent_pair(),
                                  compact=bool(c.get("room_compact")),
                                  side=c.get("room_chip_side") if side is None else side,
                                  sev=sev_on(), brk_pose=_brk_pose(), look=my_look(), **kw)


def refresh_widgets():
    """Put the room where it belongs for the screen Anki is on, or take it
    down. Cheap: a few evals, no collection access, no network. 3.8.1: in
    no room, ▶ Fifteen? sits at the chip's end of the top bar."""
    top, main, bottom = _webs()
    signed = client().signed_in
    room = my_room() if signed else None
    if room is None:
        for web in (top, main, bottom):
            _eval(web, room_model.widget_js("off"))
        if signed and cfg().get("fifteen", True):
            c = cfg()
            _eval(top, room_model.widget_js("start", room_model.start_data(
                _accent_pair(), c.get("room_chip_side"), sev_on(), nap=not _studied_today(),
                compact=bool(c.get("room_compact")))))
        return
    data = _data(room)
    where = _where()
    _eval(top, room_model.widget_js("start", None))
    _eval(top, room_model.widget_js("chip", data if where == "chip" else None))
    _eval(bottom, room_model.widget_js("bottom", data if where == "bottom" else None))
    _eval(main, room_model.widget_js("gutter", data if where == "gutter" else None))
    if _state.get("room_card"):
        if _state["room_card"] == where:
            _card_still_out(where)
        else:
            _state["room_card"] = None  # it moved (a review began or ended): the card went with the page


def _where():
    """Which little one shows the room now: the top bar's chip, or while
    reviewing the bottom bar's or the margin's."""
    return (room_model.placement(_bar_hidden("top"), _bar_hidden("bottom"))
            if mw.state == "review" else "chip")


def _card_web():
    return mw.reviewer.web if mw.state == "review" else mw.web


def _little_shown(where, on):
    """3.8.1: the chip (or the bar's, or the margin's) hides while its card
    is out, and comes back when the card closes."""
    top, main, bottom = _webs()
    web = {"chip": top, "bottom": bottom, "gutter": main}.get(where)
    _eval(web, "(function(){var e=document.getElementById('dc-room-%s');if(e){e.style.visibility='%s';}})();"
          % (where, "" if on else "hidden"))


def show_card():
    room = my_room()
    if room is None:
        return
    c = cfg()
    where = _where()
    # 3.8.1: it opens at the chip's end (the left one too); the bars' and the margin's are the right's
    data = _data(room, side=c.get("room_chip_side") if where == "chip" else "right")
    _eval(_card_web(), room_model.widget_js("card", data))
    _state["room_card"] = where
    _little_shown(where, False)


def card_closed():
    """The card closed (×, a click outside, Tuck, Leave): its chip comes back."""
    where = _state.get("room_card")
    _state["room_card"] = None
    if where:
        _little_shown(where, True)


def _card_still_out(where):
    """After a redraw: the little one stays hidden while the card is out; a
    page that went away took the card with it, and the chip comes back."""
    _little_shown(where, False)

    def seen(there):
        if not there and _state.get("room_card") == where:
            card_closed()
    try:
        _card_web().evalWithCallback("!!document.getElementById('dc-room-card')", seen)
    except Exception:
        card_closed()


# ---- the break ----

def _break_due(room):
    p = room_model.phase(room, _now())
    return (p["state"] == "break"
            and _state["room_skip"] != (room_model.room_key(room), p["round"]))


def _show_break(room):
    data = _data(room)
    _eval(mw.reviewer.web, room_model.widget_js("ask", None))
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
    # Anki's Auto Advance answers on a timer, past the shortcuts: its
    # timers start after this hook, so they're stopped a moment later
    try:
        mw.progress.single_shot(50, _stop_auto_advance)
    except Exception:
        pass
    # one refresh per break: who's in the room now, for the chip. At most
    # one light fetch a round (a doc per friend), and only while reviewing.
    # 3.8.1: none for a fifteen: nobody else is in it
    mark = (room_model.room_key(room), room_model.phase(room, _now())["round"])
    if _state["room_refreshed"] != mark and not room_model.is_fifteen(room):
        _state["room_refreshed"] = mark
        app.sync(light=True, fetch=True)


def _remove_break():
    if not _state["room_break"]:
        return
    _state["room_break"] = False
    if mw.state != "review":
        return  # leaving review reset the screen and its shortcuts already
    _eval(mw.reviewer.web, room_model.widget_js("break", None))
    _eval(mw.reviewer.web, room_model.widget_js("ask", None))
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


def _stop_auto_advance():
    if _state["room_break"] and mw.state == "review":
        stop = getattr(mw.reviewer, "_clear_auto_advance_timers", None)
        if stop:
            try:
                stop()
            except Exception:
                pass


def will_answer(ease_tuple, reviewer, card):
    """reviewer_will_answer_card, a filter: ((proceed, ease), reviewer, card)
    in, (proceed, ease) out. No answer lands under the break, whatever sends
    it (Auto Advance, another add-on)."""
    if _state["room_break"]:
        return (False, ease_tuple[1])
    return ease_tuple


def swallow(message):
    """While the break is up, answering is off from every direction: the
    shortcuts are cleared, and this drops what a card's own page can still
    send (Enter in a type-in answer box sends "ans")."""
    return bool(_state["room_break"]) and (message == "ans" or message.startswith("ease"))


def on_close():
    """profile_will_close: closing Anki leaves the room. Anki's closing sync
    (or this push) takes it off my week doc; uploads still go while closing.
    3.8.1: a fifteen ends, and its line waits for the next open."""
    cl = client()
    room = room_model.clean_room(cl.session.get("room"))
    if cl.signed_in and room_model.is_fifteen(room):
        try:
            _end_fifteen(room, walked=False, closing=True)
        except Exception:
            traceback.print_exc()
        return
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
        _state["room_skip"] = (room_model.room_key(room), room_model.phase(room, _now())["round"])
    _remove_break()


def break_ended():
    """The break's clock ran out, or the question's: no answer, so the
    session ends here (my_room sees it's over)."""
    _remove_break()
    if my_room() is None:
        refresh_widgets()
        if mw.state == "deckBrowser":
            app.swap(cfg())


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
    elif room_model.is_fifteen(room) and room_model.phase(room, _now())["state"] == "ask":
        _show_ask(room)


def on_answer(card):
    if _state["room_break"]:
        _stop_auto_advance()  # Auto Advance's answer timer starts with the answer side
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
    elif cmd == "roomcardoff":
        card_closed()
    elif cmd == "roomtuck":
        tuck()
    elif cmd == "roomskip":
        skip_break()
    elif cmd == "roombreakend":
        break_ended()
    elif cmd == "room15":
        start_fifteen()  # 3.8.1: ▶ Fifteen? and the nudge's Start
    elif cmd in ("room15five", "room15now", "room15stop"):
        fifteen_answer(cmd[6:])
    elif cmd == "room15x":
        dismiss_fifteen_done()
    elif cmd == "roomtick":
        # a phase changed (the chip saw it): the Decks screen's lobby follows
        if mw.state == "deckBrowser":
            app.swap(cfg())
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


# ---- 3.8.1: the Fifteen ----

def sev_on():
    """Sev's switch in Settings, on this computer (on unless switched off)."""
    return bool(cfg().get("sev", True))


def _brk_pose():
    return "stretch" if cfg().get("sev_break") == "stretch" else "breathe"


def my_look():
    """3.8.2: what my Sev has on from the closet (closet_flow), or nothing."""
    try:
        from . import closet_flow
        return closet_flow.look(cfg())
    except Exception:
        traceback.print_exc()
        return []


def _sev_markup(pose, rest=False, stack=None, move=None):
    return sev.move(pose, move, rest=rest, stack=stack, look=my_look()) if sev_on() else None


def pick(place):
    """3.8.1 (Sam: "variety!"): a move for Sev at `place` (sev.MOVES), never
    the one it played there last time. Signed in, the last ones are kept
    with the session, so a restart doesn't repeat one either."""
    cl = client()
    kept = cl.session.get("sev_last") if cl.signed_in else _state.get("sev_last")
    last = {k: v for k, v in kept.items() if isinstance(v, str)} if isinstance(kept, dict) else {}
    m = last[place] = sev.pick(place, last.get(place))
    if cl.signed_in:
        cl.session["sev_last"] = last
        cl._save_session()
    else:
        _state["sev_last"] = last
    return m


def _cards_since(when):
    """Cards answered since `when` (UTC). Main thread."""
    try:
        ms = int(when.timestamp() * 1000)
        return int(mw.col.db.scalar("SELECT count() FROM revlog WHERE id >= ? AND ease > 0", ms) or 0)
    except Exception:
        return None


def _studied_today():
    """Any answer yet this Anki day (asked at every card for the top bar's
    Sev: once it's yes, the day remembers)."""
    try:
        cutoff = int(mw.col.sched.day_cutoff)
        if _state.get("fifteen_studied") == cutoff:
            return True
        yes = bool(mw.col.db.scalar("SELECT 1 FROM revlog WHERE id >= ? AND ease > 0 LIMIT 1", (cutoff - 86400) * 1000))
        if yes:
            _state["fifteen_studied"] = cutoff
        return yes
    except Exception:
        return True


def _now():
    # every "is it over yet" here asks this one clock (the suite sets it)
    return datetime.datetime.now(datetime.timezone.utc)


def _fifteen_live(room):
    """Studying now, for my crew, to the end of this fifteen's question (or
    longer, if I'd already said so)."""
    cl = client()
    until = room_model.iso(room_model.live_until(room))
    mine = str(cl.session.get("live_until") or "")
    if not board.live_now(mine) or mine == cl.session.get("fifteen_live") or mine < until:
        cl.session["live_until"] = until
    cl.session["fifteen_live"] = until


def start_fifteen():
    """▶ Fifteen? or the nudge's Start: fifteen minutes from now, and Study
    today opens (unless I'm reviewing already)."""
    cl = client()
    if not cl.signed_in:
        tooltip("Sign in to Due Crew first.")
        return
    if my_room():
        show_card()  # already in one: here it is
        return
    room = room_model.make_fifteen(cl.user_id, _now())
    cl.session["fifteen_began"] = room["start"]
    cl.session.pop("fifteen_done", None)
    _fifteen_live(room)
    _set_room(room, None)
    if mw.state != "review":
        from . import due_flow
        due_flow.study_today()


def _show_ask(room):
    """The question, in place of the next card (the break's way)."""
    began = room_model._parse(client().session.get("fifteen_began") or room["start"])
    data = _data(room, cards=_cards_since(room_model.fifteen_round_start(room, room["rounds"])),
                 total=_cards_since(began) if began else None)
    _eval(mw.reviewer.web, room_model.widget_js("ask", data))
    _eval(mw.reviewer.bottom.web,
          "var m=document.getElementById('middle');if(m){m.style.visibility='hidden';}")
    try:
        mw.clearStateShortcuts()
    except Exception:
        pass
    try:
        from aqt.sound import av_player
        av_player.stop_and_clear_queue()
    except Exception:
        pass
    _state["room_break"] = True
    try:
        mw.progress.single_shot(50, _stop_auto_advance)
    except Exception:
        pass


def fifteen_answer(how):
    """The question's answer (or the break's Start now): five, now, stop."""
    room = my_room()
    if not room_model.is_fifteen(room):
        _remove_break()
        return
    if how == "stop":
        _end_fifteen(room, walked=False)
        return
    nxt = room_model.fifteen_next(room, _now(), wait=(how == "five"))
    if nxt is None:
        return  # nothing to answer now, or the eighth is done (only Stop shows then)
    _fifteen_live(nxt)
    _set_room(nxt, None)
    if mw.state == "review":
        if how == "five":
            _show_break(nxt)  # the five minutes, in place of the next card
        else:
            _remove_break()  # the next fifteen is under way: the card's back
    elif how == "now":
        from . import due_flow
        due_flow.study_today()


def _end_fifteen(room, walked=False, closing=False):
    """The session's over: its line for the board (fifteens, minutes, cards),
    Sev stacks a square for each, and my crew stops seeing me studying."""
    cl = client()
    n, minutes = room_model.fifteen_spent(room, _now())
    began = room_model._parse(cl.session.get("fifteen_began") or room["start"])
    cards = _cards_since(began) if began else None
    cl.session.pop("room", None)
    cl.session.pop("fifteen_began", None)
    if cl.session.get("live_until") == cl.session.pop("fifteen_live", None):
        cl.session.pop("live_until", None)
    if n:
        _closet(lambda cf: cf.note_fifteens(n, began))  # 3.8.2: Sev's closet counts them
        cl.session["fifteen_done"] = {"n": n, "minutes": minutes, "cards": cards, "walked": bool(walked),
                                      "day": _state["labels"][0] if _state["labels"] else "", "move": pick("stack")}
    cl._save_session()
    for e in _state["entries"] or []:
        if e["you"]:
            e["room"] = None
            e["live_until"] = str(cl.session.get("live_until") or "")
    if closing:
        app.sync(light=True, fetch=False)
        return
    _remove_break()
    if walked:
        # found over while drawing: the redraw comes after this one
        from aqt.qt import QTimer
        QTimer.singleShot(0, lambda: (refresh_widgets(), mw.state == "deckBrowser" and app.swap(cfg())))
        return
    app.sync(light=True, fetch=False)  # my crew stops seeing "studying now"
    refresh_widgets()
    if mw.state == "review":
        mw.moveToState("deckBrowser")  # the session's line is there, with Sev
    else:
        app.swap(cfg())


def _fifteen_done():
    d = client().session.get("fifteen_done")
    if not isinstance(d, dict) or not d.get("n"):
        return None
    if _state["labels"] and d.get("day") and d["day"] != _state["labels"][0]:
        return None  # a day old: gone
    return d


def dismiss_fifteen_done():
    client().session.pop("fifteen_done", None)
    client()._save_session()
    app.swap(cfg())


# ---- 3.8.1: the nudge, and Sev by the logo ----

def _usual_start():
    """When I usually start, in seconds into my Anki day: the middle of my
    first answers on the days I studied in the last two weeks. Once a day."""
    try:
        cutoff = int(mw.col.sched.day_cutoff)
    except Exception:
        return None
    hit = _state.get("fifteen_usual")
    if hit and hit[0] == cutoff:
        return hit[1]
    usual = None
    try:
        first = cutoff - 15 * 86400
        rows = mw.col.db.all("SELECT min(id) FROM revlog WHERE id >= ? AND id < ? AND ease > 0 "
                             "GROUP BY (id / 1000 - ?) / 86400", first * 1000, (cutoff - 86400) * 1000, first)
        usual = room_model.usual_start([(int(r[0]) // 1000 - first) % 86400 for r in rows if r and r[0]])
    except Exception:
        traceback.print_exc()
    _state["fifteen_usual"] = (cutoff, usual)
    return usual


def nudge(c, v, dismissed=()):
    """Whether the You box asks "Fifteen?": once a day, only when nothing's
    studied yet, something's due, it's past my usual start, I'm not away,
    in no room, and I didn't say Not today."""
    try:
        if not c.get("fifteen", True) or not client().signed_in or not mw.col or "fifteen" in dismissed:
            return False
        if not v or v.get("done") or int(v.get("total_n") or 0) <= int(v.get("done_n") or 0) or _studied_today() or my_room():
            return False
        from .backend.shapes import away_range
        rng = away_range(c)
        today = datetime.date.today()
        if rng and rng[0] <= today <= rng[1]:
            return False
        usual = _usual_start()
        return usual is not None and time.time() - (mw.col.sched.day_cutoff - 86400) >= usual
    except Exception:
        traceback.print_exc()
        return False


def nudge_sev():
    """Sev peeking in at the nudge: it rises once a day, then stays put;
    each day a different way in (sev.MOVES["peek"], in turn)."""
    day = str(_state["labels"][0] if _state.get("labels") else "")
    rest = _state.get("sev_peeked") == day
    _state["sev_peeked"] = day
    return _sev_markup("peek", rest=rest, move=sev.nth("peek", datetime.date.today().toordinal()))


def milestone_sevs(milestones):
    """3.8.1 (Sam's pick): a crewmate's big-streak banner has Sev hopping in
    its emoji's place, a move from the day done's mix (never the last one),
    once a banner; drawn again, it rests there. {uid: markup}, or None."""
    if not sev_on() or not milestones:
        return None
    played = _state.setdefault("sev_banner", {})
    looks = {e.get("user_id"): e.get("look") for e in _state["entries"] or []}
    out = {}
    for uid, _who, days in milestones:
        key = (str(uid), int(days))
        rest = key in played
        if not rest:
            played[key] = pick("hop")
        out[uid] = sev.move("hop", played[key], rest=rest, label="Sev: a big streak", look=looks.get(uid))  # 3.8.2: in their look
    return out


def signed_out_sev():
    """3.8.1 (Sam's pick): Sev waving on the signed-out card until you
    start, a hello from its mix (never the last one) the first time it's
    drawn while Anki's open; after that it rests there, and blinks."""
    if not sev_on():
        return None
    turn = _state.get("sev_hello")
    if turn is None:
        _state["sev_hello"] = pick("hello")
        return sev.move("hello", _state["sev_hello"], look=my_look())
    return sev.move("hello", turn, rest=True, look=my_look())


def board_sev(c, v):
    """Sev beside the logo, for a moment (Sam): {svg, ago} when something
    just happened (sev.moment), the first time the board draws it; ago is
    how long it's been out, so a redraw in its few seconds keeps its place.
    None the rest of the time, and after."""
    if not sev_on():
        return None
    try:
        from .backend.shapes import away_range
        today = datetime.date.today()
        rng = away_range(c)
        cheer_at = float(_state.get("sev_cheer") or 0)
        pose = sev.moment(cheered=time.time() - cheer_at < 15 * 60,
                          back=bool(rng and rng[1] + datetime.timedelta(days=1) == today),
                          exam_eve=str(c.get("exam_date") or "") == (today + datetime.timedelta(days=1)).isoformat(),
                          day_done=bool(v and v.get("done")))
    except Exception:
        traceback.print_exc()
        return None
    if not pose:
        return None
    day = str(_state["labels"][0] if _state.get("labels") else "")
    key = (day, pose, int(cheer_at) if pose == "cheer" else 0)  # each cheer its own moment; the rest once a day
    shown = _state.setdefault("sev_shown", {})
    now = time.time()
    if key not in shown:
        shown[key] = (now, pick(pose))  # its move, picked once a moment (never the last one there)
    first, turn = shown[key]
    ago = now - first
    if ago >= sev.LOGO_SECONDS:
        return None
    return {"svg": sev.move(pose, turn, look=my_look()), "ago": round(ago, 2)}
