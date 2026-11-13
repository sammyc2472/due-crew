"""The glue: what the pages say (duecrew: commands), the Decks screen's table of them."""

import re

from aqt.deckbrowser import DeckBrowser
from aqt.utils import tooltip

from .. import app
from .. import board
from .. import cards as crew_cards
from .. import errs
from .. import plan_flow
from .. import rooms
from ..app import _pending_cheers
from ..app import _state
from ..app import cfg
from ..app import save_cfg
from ..errs import oops
from ..social import _send_cheer
from ..social import cheer_allowed
from ..squads import _fetch_squad
from ..ui import copy_text
from ..wrap import _save_wrap
from ..wrap import _wrap_data
from ..wrap import _wrap_info

from .render import _SCRIPTS, _arrive_js, _board_html, _board_js, _dance_seen, _rerender
from .refresh import _fetch_decks
from .sync import _on_sync_done


def _our_page(context):
    """3.7.1 review: the pages Due Crew draws on, where a card's own script
    never runs: the Decks screen, the top bar and the reviewer's bottom bar.
    Everything else (the review screen, Overview with a deck's description,
    the browser's preview, Cards…, another add-on's page) gets the card
    page's rules: the widgets' keyed commands only."""
    ours = [DeckBrowser]
    # not Overview: it puts a deck's description in as it is, script and all.
    # 3.8.1: the top bar's messages come with a TopToolbar (a wrapper Anki's
    # Toolbar.draw makes), not the Toolbar: until then the top bar counted as
    # a card's page, and only the widgets' own commands got through
    # (▶ Fifteen? clicked to nothing)
    for mod, name in (("aqt.toolbar", "TopToolbar"), ("aqt.toolbar", "Toolbar"),
                      ("aqt.reviewer", "ReviewerBottomBar")):
        try:
            ours.append(getattr(__import__(mod, fromlist=[name]), name))
        except (ImportError, AttributeError):
            pass
    return isinstance(context, tuple(ours))


def _on_js(handled, message, context):
    if rooms.swallow(message):
        return (True, None)  # 2.12: no answering under the break
    card_page = False
    if message.startswith("duecrew:"):
        # the reviewer's page runs the card's own script too: from there only
        # the widgets' keyed buttons count, never a bare command. 3.9.1 (the
        # security review): the Decks screen's too, unless its page's own key
        # comes with it: on the way back to Decks, Anki sends the page
        # before's messages (a card's, a deck description's) as the Decks
        # screen's until the Decks page is built
        from ..room_model import trusted
        body, sep, key = message.rpartition("|")
        if isinstance(context, DeckBrowser) and sep and key == board.BOARD_KEY:
            message, card_page = body, False
        else:
            card_page = isinstance(context, DeckBrowser) or not _our_page(context)
            message, ok = trusted(message, card_page)
            if not ok:
                return (True, None)
    if message == "duecrew:veiltap":
        # 3.9.1: a tap on the top or bottom bar's shade (app.veil) is Esc on the board
        app.board_eval("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));")
        return (True, None)
    if message.startswith("duecrew:knows"):
        # 3.2: the chip in the reviewer's bottom bar, or its card above it
        try:
            parts = message.split(":")
            crew_cards.on_message(parts[1], parts, from_card_page=card_page)
        except Exception:
            oops()
        return (True, None)
    if message.startswith("duecrew:room"):
        # 2.12: study rooms answer from the top bar and the review screen too
        parts = message.split(":")
        try:
            errs.used("fifteen" if "fifteen" in parts[1] else "rooms")
            done = rooms.on_message(parts[1], parts)
        except Exception:
            oops()
            done = True
        if done:
            return (True, None)
    if not isinstance(context, DeckBrowser) or not message.startswith("duecrew:"):
        return handled
    parts = message.split(":")
    cmd = parts[1] if len(parts) > 1 else ""
    run = _board_cmd(cmd, parts)
    if run is None:
        print(f"due crew: unknown command {message!r}")
        # 3.9.9: for Sam, a name of the table's with values that didn't pass, or cmd:unknown (a
        # name it hasn't can come from a card's script: never said)
        errs.count(errs.cmd_code(cmd, BOARD_CMDS))
    else:
        run(cfg(), parts)
        errs.used(errs.use_of(cmd))  # 3.9.9: which part was opened today (once a day; Privacy's switch)
    return (True, None)


def _board_cmd(cmd, parts):
    """3.9.8 (the tidy-ups): what a Decks-screen command does, or None when
    it's none of ours or its values don't pass. A family by its first
    letters goes to its own module, which knows its names; any other is
    one line of BOARD_CMDS."""
    for start, run in _FAMILIES:
        if cmd.startswith(start):
            return run
    need, ok, run = BOARD_CMDS.get(cmd, (0, None, None))
    if run is None or len(parts) < 2 + need or (ok and not ok(parts)):
        return None
    return run


def _cmd_period(c, parts):
    _state["bingo_open"] = False
    _state["team_bingo_open"] = None
    c["period"] = parts[2]
    if parts[2] != "squads":
        c["crew_view"] = parts[2]  # 3.8.0: Today, Week or Decks: the Crew pill comes back to it
    save_cfg(c)
    _swap(c)
    if parts[2] == "squads":
        _fetch_squad()
    elif parts[2] == "decks":
        _fetch_decks()


def _cmd_refresh(c, parts):
    _on_sync_done(full=True, fetch=True)  # push my own numbers too, then fetch the week
    if c.get("period") == "squads":
        _fetch_squad(force=True)
    elif c.get("period") == "decks":
        _fetch_decks(force=True)


def _cmd_css(c, parts):
    _SCRIPTS["css"] = None  # 3.9.7: the page hasn't the board's stylesheet (board.swap_js): it goes with the next swap
    _swap(c)


def _cmd_sort(c, parts):
    c["sort"] = parts[2]
    save_cfg(c)
    _swap(c)


def _cmd_addcode(c, parts):
    if len(parts) > 2 and parts[2]:
        _add_code(parts[2])  # 3.4 review, C5: from the day-one card
    else:
        open_friends(focus_add=True)


def _cmd_privacy(c, parts):
    from aqt.utils import openLink  # 3.7.1, D3: signed out works; no token
    openLink(plan_flow.site_base() + "/privacy")


def _fridge_spot(parts):
    # 3.9.1: where I left it, beside the board (side, px from its edge, px down)
    return (parts[3] in ("l", "r") and (parts[4][1:] if parts[4][:1] == "-" else parts[4]).isdecimal()
            and parts[5].isdecimal())


def _cmd_emoji_picker(c, parts):
    # 3.9.1: the Cheer window's "other": the computer's own picker; when it has none, the window's drawer.
    # 3.9.2: into our own box over its "pick one" (x:y:w:h), since the page can't take the pick
    from .. import native_emoji
    at = [int(v) for v in parts[2:6] if v.isdecimal() and len(v) < 6]
    x, y, w, h = at if len(at) == 4 else (0, 0, 64, 40)
    if not native_emoji.catch(x, y, w, h, lambda e: app.board_eval(native_emoji.picked_js(e)),
                              lambda: app.board_eval("window.dcCheerUnpick && window.dcCheerUnpick();")):
        app.board_eval("window.dcCheerNoNative && window.dcCheerNoNative();")


def _cmd_emoji_picker_off(c, parts):
    from ..native_emoji import drop
    drop()  # 3.9.2: the Cheer window closed, or other's box put away there


def _cmd_cheer_send(c, parts):
    from ..social import send_from_window
    send_from_window(":".join(parts[2:]))  # 3.9.1: the Cheer window's Send


def _wrap_put(c, key, value):
    w = _wrap_data()
    w[key] = value(w)
    _save_wrap()
    _swap(c)


def _cmd_notice_open(c, parts):
    n = _state.get("notice")
    if n and n.get("link"):
        from aqt.utils import openLink
        openLink(n["link"])


def _cmd_wrap_copy(c, parts):
    b = _wrap_info() or {}
    if b.get("reviews"):
        text = (f"Last week, together: {b['reviews']:,} reviews "
                f"· {board._fmt_time(b.get('time_ms') or 0)}")
        if (b.get("full_days") or 0) >= 3:
            text += f" · everyone showed up {b['full_days']} of 7 days"
        if 0 < int(b.get("days_known") or 7) < 7:
            text += f" · from {int(b['days_known'])} of its 7 days"
        if b.get("milestone"):
            text += f" · just passed {b['milestone']} all-time"
        copy_text(text + " — Due Crew")
        tooltip("Copied.")


def _cmd_cheer_back(c, parts):
    uid, emoji = parts[2], parts[3]
    entry = next((e for e in (_state["entries"] or []) if e["user_id"] == uid), None)
    emoji = cheer_allowed(emoji)
    if entry and emoji:
        _send_cheer(uid, entry["name"], emoji)


def _team(cmd, parts):
    from .. import team_flow
    team_flow.on_message(cmd, parts)  # 3.8.0: You › Insights, a deck's


def _song(c, parts):
    from .. import song_flow
    song_flow.on_message(parts[1], parts)  # 3.9.6: song of the moment, and its dance floor


def _settings_family(c, parts):
    _settings_cmd(parts[1], parts[2:])  # 3.5.0: Settings in the board; parts[2:] are its values


def _swapping(do):
    """A command that changes the board and draws it again."""
    def run(c, parts):
        do(c, parts)
        _swap(c)
    return run


def _team_squad(team_id):
    from .. import team_flow
    team_flow.open_squad(team_id)  # 3.8.0: a plan's squad


def _swap(c, focus=None):
    """Re-render the board in place from cache. No network, no page reload.
    focus: the data-f of the control to give focus back to (Settings)."""
    if _state["entries"] is None:
        _rerender()
        return
    html_out = _board_html(c)
    have = _SCRIPTS.get("css") if _SCRIPTS["page"] == app.pages[0] else None  # 3.9.7: the stylesheet this page holds
    keep, fridge = _board_js()
    js = board.swap_js(html_out, have) + keep + _arrive_js() + fridge  # 3.8.0: no jumps under the pointer
    _SCRIPTS["css"] = board.css_key(html_out)
    if focus:
        js += ("(function(){var f=document.querySelector('#due-crew [data-f=\"%s\"]');"
               "if(f){f.focus({preventScroll:true});}})();" % re.sub(r"[^A-Za-z0-9:_-]", "", focus))
    app.board_eval(js)  # 3.9.1: never into the page before the Decks page (it'd carry the board's key)
    _dance_seen()
    if not _pending_cheers:  # cheers about to land play first; the finish follows them (_commit)
        _joy_show()


def _joy_show():
    """3.9.6: a plan just finished: its show over the Decks screen, once
    (plan_flow.joy_show); after a cheer's show, when one's playing."""
    try:
        plan_flow.joy_show()
    except Exception:
        oops()


# Names of the parts after this one. The package sets them as each of those parts loads
# (an import here would load a later part before the ones between).
_LATER = ("BOARD_CMDS", "_FAMILIES", "_add_code", "_settings_cmd", "open_friends")
BOARD_CMDS = _FAMILIES = _add_code = _settings_cmd = open_friends = None
