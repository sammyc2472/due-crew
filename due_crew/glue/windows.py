"""The glue: sign-in, welcome, codes, Friends, Decks, the closet, the scrapbook."""

import html

from aqt import mw
from aqt.qt import QTimer
from aqt.utils import tooltip

from .. import app
from .. import board
from .. import plan_flow
from ..app import _bg
from ..app import _reset_runtime
from ..app import _state
from ..app import cfg
from ..app import client
from ..app import save_cfg
from ..errs import oops
from ..shares import _share
from ..shares import picture as share_picture
from ..social import muted_uids
from ..squads import _share_squad
from ..squads import _squad_view
from ..squads import open_squads
from ..stats.decks import gather_shared_decks
from ..wrap import _mute_knocker
from ..wrap import _wrap_data

from .refresh import _lock, _run, refresh_board
from .sync import _on_sync_done
from .render import _rerender
from .commands import _swap


def open_auth():
    """One flow signs in and joins. A new account gets the welcome screen
    before its first upload, so what the crew will see is said before any
    of it is shared."""
    from ..ui.auth_dialog import AuthDialog
    dlg = AuthDialog(mw, client())
    if dlg.exec() and dlg.user:
        _uid, name = dlg.user
        _reset_runtime(keep_sync=True)
        with _lock:
            _run.fetching = False  # the last session's refresh can't commit now
        if dlg.joined:
            c = cfg()
            c["calm"], c["calm_open"], c["calm_news"] = True, [], []  # 3.9.9: a new person's board starts calm (calm.py)
            save_cfg(c)
            _welcome()
        else:
            tooltip(f"Welcome back, {html.escape(name)}.")
        _on_sync_done()
        _rerender()
        # 3.1: signed in on a profile that syncs but hasn't yet: the morning's fallback
        gen = app.generation
        QTimer.singleShot(180000, lambda: _morning_fallback(gen))


def _welcome():
    from ..ui.welcome_dialog import WelcomeDialog
    dlg = WelcomeDialog(mw, client(), cfg(), open_squads)
    if dlg.exec() and dlg.offered:
        c = cfg()
        if bool(c.get("show_up")) != dlg.show_up:
            c["show_up"] = dlg.show_up
            save_cfg(c)


def _add_code(code):
    """The day-one card's Add: a friend's code, added now. One request."""
    from ..backend.shapes import friend_code_from, invite_code_from, long_code_from
    typed = code
    invite = invite_code_from(typed)
    if invite:
        _redeem(invite)  # 3.5.0: a one-time invite makes us crew at once
        return
    code = friend_code_from(typed)
    if not code:
        # 3.5.0: a plan's code opens Follow, a squad's opens Squads
        longer = long_code_from(typed)
        if not longer:
            tooltip("That doesn't look like a code. Pasting the whole invite works too.")
            return
        _bg(lambda: client().peek_plan(longer),
            lambda r: plan_flow.open_follow(longer) if r and r[0] else open_squads(longer))
        return
    if code == _state["my_code"]:
        tooltip("That's your own code.")
        return
    cl = client()

    def done(result):
        friend, err = result if result else (None, None)
        if not friend:
            tooltip(html.escape(err or "Couldn't add. Check your connection."))
            return
        name = html.escape(str(friend.get("name") or "?"))
        tooltip(f"You and {name} are crew." if friend.get("mutual")
                else f"Added {name}. They'll see it on their board.")
        refresh_board(full=True)

    _bg(lambda: cl.add_friend(code), done)


def _redeem(invite):
    cl = client()

    def done(result):
        friend, err = result if result else (None, None)
        if not friend:
            tooltip(html.escape(err or "Couldn't add. Check your connection."))
            return
        name = html.escape(str(friend.get("name") or "?"))
        tooltip(f"You and {name} are crew." if friend.get("mutual")
                else f"Added {name}. They'll see it on their board." if friend.get("knocked")
                else f"{name} isn't in your crew now.")
        refresh_board(full=True)

    _bg(lambda: cl.redeem_invite(invite), done)


def _share_menu(c):
    """The footer's Share ▾ (3.7.1, H3): as text, then as a picture."""
    from aqt.qt import QCursor, QMenu
    run = {"squadshare": lambda: _share_squad(),
           "sharetoday": lambda: _share("sharetoday"), "sharecrewweek": lambda: _share("sharecrewweek"),
           # 3.8.0: the picture is made here (it opened duecrew.com before)
           "picturetoday": lambda: share_picture("picturetoday"),
           "pictureweek": lambda: share_picture("pictureweek"),
           "pictureyear": lambda: share_picture("pictureyear"),
           "picturealltime": lambda: share_picture("picturealltime")}
    menu = QMenu(mw)
    for label, key in board.share_menu_items(
            bool(c.get("show_up")), (_squad_view(c) or {}).get("state") == "ok"):
        if label is None:
            # a heading: macOS draws a QMenu section's title as a bare line,
            # so it's a greyed item that can't be clicked
            if menu.actions():
                menu.addSeparator()
            head = menu.addAction(key)
            head.setEnabled(False)
        else:
            menu.addAction(label).triggered.connect(lambda _=False, k=key: run[k]())
    menu.exec(QCursor.pos())


def open_friends(focus_add=False):
    if not client().signed_in:
        open_auth()
        return
    from ..ui.friends_dialog import FriendsDialog
    dlg = FriendsDialog(mw, client(),
                        muted=list(_wrap_data().get("muted_knocks") or [])
                        + sorted(muted_uids(cfg())),
                        on_mute=_mute_knocker, focus_add=focus_add)
    dlg.exec()
    if dlg.new_code:
        _state["my_code"] = dlg.new_code  # the solo board's Copy invite
    if dlg.changed:
        refresh_board(full=True)
    elif dlg.new_code:
        _swap(cfg())


def open_decks():
    if not client().signed_in:
        open_auth()
        return
    if not mw.col:
        return
    from ..ui.decks_dialog import DecksDialog
    dlg = DecksDialog(mw, cfg(), _state["entries"] or [], _on_decks_saved)
    dlg.exec()


def _on_decks_saved(changed):
    c = cfg()
    c.update(changed)
    c["shared_decks_set"] = True
    save_cfg(c)
    try:
        decks = gather_shared_decks(mw.col, c)
    except Exception:
        oops()
        decks = None
    refresh_board(shared_decks=decks)


_share_push = {"n": 0}


def open_closet(tab=None):
    """3.8.2: Pip's closet, in place of the board (as Settings is), from
    anywhere: what just came for Pip shows as new there, and the board's
    line for it is done."""
    news = list((_state.get("closet_new") or {}).get("keys") or [])
    _state["closet_open"] = {"tab": tab or board.CLOSET_TABS[0], "msg": "", "new": news, "drawn": False}
    _state["closet_new"] = None
    _state["wrapped_open"] = None
    _state["settings_tab"] = None
    _close_addons_dialog()
    if mw.state != "deckBrowser":
        mw.moveToState("deckBrowser")
    elif _board_on_screen():
        _swap(cfg())
    else:
        _rerender()


def _scrap(do):
    """A step of the scrapbook's (scrap_flow), never in a refresh's way."""
    try:
        from .. import scrap_flow
        return do(scrap_flow)
    except Exception:
        oops()
        return None


def open_scrapbook(year=None):
    """3.9.10: the scrapbook, in place of the board (as the closet is), from
    the foot's Scrapbook, the board's December line or Tools › Due Crew ›
    Scrapbook…: what my crew sent me and what I did, by month, under the
    year's page (Wrapped's, 3.9.0), read here from this computer alone."""
    if not mw.col:
        return
    if not _scrap_load(year):
        tooltip("Couldn't open your scrapbook just now.")
        return
    _state["settings_tab"] = None
    _state["closet_open"] = None
    _close_addons_dialog()
    if mw.state != "deckBrowser":
        mw.moveToState("deckBrowser")
    elif _board_on_screen():
        _swap(cfg())
    else:
        _rerender()


def _scrap_load(year=None):
    """The scrapbook's view, read again (opening it, another year, after a keepsake goes). True when it was."""
    from .. import scrap_flow
    try:
        v = scrap_flow.view(year)
    except Exception:
        oops()
        return False
    _state["wrapped_open"] = {"year": v["year"], "view": v}  # Wrapped's slot (3.9.0): one screen in the board's place
    return True


def _scrap_html(c):
    st = _state.get("wrapped_open") or {}
    view = st.get("view") or {"year": st.get("year"), "months": []}
    people = {e.get("user_id"): e for e in _state.get("entries") or [] if e.get("user_id") and not e.get("you")}
    from .. import closet_flow
    return board.scrapbook_html(view, c, people, closet_flow.look(c))


def _wrapped_banner(c):
    from .. import wrapped_flow
    try:
        return wrapped_flow.banner(_state["labels"][0] if _state["labels"] else "", c)
    except Exception:
        oops()
        return None


def _scrap_cmd(cmd, parts):
    """3.9.10: the scrapbook's clicks: open it (the foot's word, the
    December line's Open), another year, the year picture card, a polaroid
    back on the Decks screen, a keepsake or all of them gone (asked first),
    back to the board, and the line's x (for the year, on every computer)."""
    from .. import scrap_flow, sheets
    arg = parts[0] if parts else ""
    year = int(arg) if arg.isdigit() and len(arg) == 4 else None
    st = _state.get("wrapped_open") or {}

    def again():
        if _state.get("wrapped_open"):
            _scrap_load(st.get("year"))
        if _board_on_screen() or mw.state == "deckBrowser":
            _swap(cfg())

    if cmd in ("scrapbook", "scrapyear"):
        open_scrapbook(year)
        return
    if cmd == "scrapshare" and year:
        from ..shares import picture
        picture("pictureyear", year=year)  # the year card, made here, with Pip on it
        return
    if cmd == "scrappin" and st:
        item = scrap_flow.find(arg)
        if not item or item.get("k") != "pz":
            return
        from .. import closet_flow, scrapbook
        if closet_flow.pin_up(scrapbook.to_fridge(item), client().user_id):
            scrap_flow.forget(arg)
            tooltip("Pinned up on your Decks screen.")
        else:
            tooltip("It’s on your Decks screen already.")
            scrap_flow.forget(arg)
        again()
        return
    if cmd == "scrapdel" and st:
        if scrap_flow.find(arg):
            sheets.confirm("Delete this?", "It goes for good.", "Delete",
                           lambda: (scrap_flow.forget(arg), again()), danger=True)
        return
    if cmd == "scrapempty" and st:
        sheets.confirm("Empty the scrapbook?", "Every keepsake in it goes for good, from every year. "
                       "What’s pinned on your Decks screen stays.", "Empty it",
                       lambda: (scrap_flow.empty(), again()), danger=True)
        return
    if cmd == "scrapclose":
        _state["wrapped_open"] = None
    elif cmd == "wrappedx" and year:
        c = dict(cfg())
        c["wrapped_seen"] = str(year)
        save_cfg(c)
    else:
        return
    if _board_on_screen() or mw.state == "deckBrowser":
        _swap(cfg())


def _closet_view():
    from .. import closet_flow
    st = _state.get("closet_open") or {}
    c = cfg()
    rest, st["drawn"] = bool(st.get("drawn")), True  # Pip waves when it opens and at a change, then rests
    near, progress = closet_flow.standing(c)
    return {"tab": st.get("tab"), "have": closet_flow.have(c), "look": closet_flow.look(c),
            "near": near, "progress": progress, "new": st.get("new") or [], "msg": st.get("msg") or "", "rest": rest}


def _closet_cmd(cmd, parts):
    """3.8.2: the closet's clicks, and the board line's (Wear it, ×)."""
    from .. import closet as cl, closet_flow
    st = _state.get("closet_open")
    arg = parts[0] if parts else ""
    focus = None
    if cmd == "closet":
        open_closet()
        return
    if cmd == "closetnew":
        _state["closet_new"] = None  # the line, later: the things stay in the closet
    elif cmd == "closethw":
        closet_flow.hide_halloween(_state["labels"][0] if _state["labels"] else "")  # 3.8.22: till next year
    elif cmd == "closetclose":
        _state["closet_open"] = None
    elif cmd == "closetwear" and arg in cl.BY:
        if closet_flow.wear(arg):
            if st:
                st.update({"msg": "", "drawn": False})
                focus = "closetwear:" + arg
            else:
                _state["closet_new"] = None  # Wear it, on the board's line: on, and the line's done
    elif cmd == "closettab" and st is not None and arg.isdigit() and int(arg) < len(board.CLOSET_TABS):
        st.update({"tab": board.CLOSET_TABS[int(arg)], "msg": ""})
        focus = "closettab:" + arg
    elif cmd == "closetoff":
        c = cfg()
        if c.get(closet_flow.LOOK_KEY):
            c = dict(c)
            c[closet_flow.LOOK_KEY] = []
            save_cfg(c)
        if st:
            st.update({"msg": ""})
    else:
        return
    if _board_on_screen() or _state.get("closet_open"):
        _swap(cfg(), focus=focus)
    else:
        _rerender()


# Names of the parts after this one. The package sets them as each of those parts loads
# (an import here would load a later part before the ones between).
_LATER = ("_board_on_screen", "_close_addons_dialog", "_morning_fallback", "k")
_board_on_screen = _close_addons_dialog = _morning_fallback = k = None
