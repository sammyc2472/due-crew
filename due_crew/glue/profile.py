"""The glue: a profile opening and closing, the Tools menu, the keys."""

import sys
import time

from aqt import mw
from aqt.qt import QAction
from aqt.qt import QTimer
from aqt.utils import tooltip

from .. import account
from .. import app
from .. import board
from .. import due_flow
from .. import errs
from .. import errs_flow
from .. import gamenight_flow
from .. import magic_flow
from .. import rooms
from ..app import _reset_runtime
from ..app import _state
from ..app import cfg
from ..app import client
from ..app import save_cfg
from ..errs import oops
from ..squads import open_squads

from .render import _closet, _rerender
from .refresh import _current, _lock, _morning, _open_push_due, _run, refresh_board
from .sync import _on_sync_done
from .commands import _swap
from .windows import open_closet, open_friends, open_scrapbook
from .settings import open_feedback, open_settings


SHARE_KEYS = ("show_up", "share_reviews", "share_time", "share_retention", "share_streak",
              "share_heatmap", "paused", "exam_date", "show_studying",
              "away_from", "away_to")


def _on_signed_out():
    _closet(lambda cf: cf.clear_fridge())  # 3.9.1: the drawings were that account's
    _reset_runtime(keep_sync=True)
    with _lock:
        _run.fetching = False
    _run.pushed = None
    _rerender()


def _on_profile_open():
    if not _run.menu_done:
        _run.menu_done = True
        _tools_menu()
        mw.addonManager.setConfigAction(__name__, open_settings)
    _reset_runtime()          # profile switch: nothing carries over
    with _lock:
        _run.fetching = False     # the last profile's refresh can't commit here
    _run.closing = False
    _run.last_attempt = 0.0
    _run.pushed = None
    client()                  # rebind to this profile's session
    try:  # 3.9.12: switches that left Settings go back to their defaults, once
        from .. import settings_model
        back = settings_model.retire(cfg())
        if back:
            c = cfg()
            c.update(back)
            save_cfg(c)
    except Exception:
        oops()
    try:
        errs_flow.open_profile()  # 3.9.9: this profile's counts for Sam
        from .. import team_flow as _tf
        _tf.ASYNC = True  # 3.9.9: the board's Insights is worked out a part at a time (insights_soon)
        _tf.warm_soon()  # and ahead of its first ask, once the morning is through
    except Exception:
        oops()
    _closet(lambda cf: cf.hook())  # 3.8.2: cards I add count for Pip's closet
    if client().signed_in:
        account.ensure()      # 2.13: my settings, before anything uploads
    _settle_tabs()
    refresh_board()           # the board, right away
    # 3.1: a profile that syncs but didn't today still gets its morning
    gen = app.generation
    QTimer.singleShot(180000, lambda: _morning_fallback(gen))
    # ...and my own numbers a few seconds later, unless Anki's own sync got
    # there first (it pushes on finish, and it may have pulled phone reviews)
    QTimer.singleShot(8000, _push_on_open)


def _settle_tabs():
    """3.8.0: Plans left the board for the You bubble: a saved Plans tab
    opens there, with Crew's Today under it; a hidden Week (a tab once) goes."""
    c = cfg()
    changed = False
    if c.get("period") == "plans":
        c["period"], c["due_tab"] = "today", "plans"
        changed = True
    hidden = [k for k in (c.get("hidden_tabs") or []) if k in dict(board.HIDEABLE_TABS)]
    if hidden != list(c.get("hidden_tabs") or []):
        c["hidden_tabs"] = hidden
        changed = True
    if changed:
        save_cfg(c)


# 3.8.0: clear of Anki's own. On a Mac Qt's "Ctrl" is Command, and ⌘⇧Q is the
# system's Log Out: Ask the squad is the Control key there (Qt's "Meta"), ⌃⇧Q
STUDY_KEY, ASK_KEY = "Ctrl+Shift+S", ("Meta+Shift+Q" if sys.platform == "darwin" else "Ctrl+Shift+Q")
MAGIC_KEY = "Ctrl+F"  # 3.9.7: Magic search; 3.9.10: ⌘F on a Mac (was ⌘⇧F); Settings › Study takes it away


def _tools_menu():
    """Tools › Due Crew (3.1: a submenu, for plans). 3.8.0: Study what's
    next on top (Ctrl+Shift+S), Settings… opens the board's, and Show on
    the Decks screen is the way back when the board is off. 3.9.3: one
    Plans ▸ holds everything about plans (planner.plans_menu)."""
    from aqt.qt import QMenu, QShortcut, QKeySequence
    if getattr(mw, "_due_crew_menu", None) is not None:
        return  # a second profile open: the submenu is already there
    from .. import planner
    menu = QMenu("Due Crew", mw)
    for item in (("Study what’s next", due_flow.study_today),
                 ("Magic search…", open_magic), None,  # 3.9.7
                 ("Friends…", open_friends),
                 ("Squads…", open_squads),
                 ("Pip Party…", open_game_night),  # 3.9.5: the You bubble on it; shown when it is (gamenight_flow.shown)
                 "plans", None,  # 3.9.3: Plans ▸, the plan windows among its entries
                 ("Settings…", open_settings),
                 ("Pip’s closet…", lambda: open_closet()),
                 ("Scrapbook…", lambda: open_scrapbook()),
                 ("Show on the Decks screen", _toggle_board),
                 ("Send feedback…", open_feedback)):
        if item is None:
            menu.addSeparator()
            continue
        if item == "plans":
            menu.addMenu(planner.plans_menu(menu))
            continue
        label, fn = item
        action = QAction(label, mw)
        action.triggered.connect(lambda _=False, fn=fn: fn())
        menu.addAction(action)
        if fn is _toggle_board:
            action.setCheckable(True)
            menu.aboutToShow.connect(lambda a=action: a.setChecked(bool(cfg().get("show_leaderboard", True))))
        if fn is due_flow.study_today:
            mw._due_crew_study = action
        if fn is open_magic:
            mw._due_crew_magic = action
            menu.aboutToShow.connect(lambda a=action: a.setVisible(magic_flow.on()))
        if fn is open_game_night:
            menu.aboutToShow.connect(lambda a=action: a.setVisible(gamenight_flow.shown()))
    ask = QShortcut(QKeySequence(ASK_KEY), mw)
    ask.activated.connect(_ask_this_card)
    mw._due_crew_ask = ask
    mw.form.menuTools.addMenu(menu)
    mw._due_crew_menu = menu  # kept alive with the window
    _apply_keys()


def open_magic(text=""):
    """3.9.7: Magic search, unless Settings › Study has it off."""
    errs.used("magic")
    if not magic_flow.on():
        tooltip("Magic search is off: Settings › Study turns it on.")
        return
    magic_flow.open_search(text)


def open_game_night():
    """3.9.5: Tools › Due Crew › Pip Party: the You bubble open on it (gamenight_flow; game night until its last round)."""
    gamenight_flow.open_tab()


def _ask_this_card():
    from .. import team_flow
    team_flow.ask_this_card()


def _apply_keys():
    """Settings › Study › Shortcuts: both keys on, or both off (per computer)."""
    on = bool(cfg().get("shortcuts", True))
    try:
        from aqt.qt import QKeySequence
        study = getattr(mw, "_due_crew_study", None)
        if study is not None:
            study.setShortcut(QKeySequence(STUDY_KEY if on else ""))
        ask = getattr(mw, "_due_crew_ask", None)
        if ask is not None:
            ask.setEnabled(on)
        magic = getattr(mw, "_due_crew_magic", None)
        if magic is not None:  # 3.9.7: its key goes with the rest, and with Magic search off
            magic.setShortcut(QKeySequence(MAGIC_KEY if on and magic_flow.on() else ""))
    except Exception:
        oops()


def _toggle_board():
    """Tools › Due Crew › Show on the Decks screen."""
    c = cfg()
    c["show_leaderboard"] = not c.get("show_leaderboard", True)
    save_cfg(c)
    _state["settings_tab"] = None
    _rerender()


def _morning_fallback(gen=None):
    """Three minutes after opening: if no AnkiWeb sync has come (none set
    to run on open, or offline), the plans' morning runs anyway, unless a
    sync is still busy with the collection. Not for a profile, or a
    sign-in, that has gone since."""
    if gen is not None and not _current(gen):
        return
    try:
        if mw.progress.busy():
            QTimer.singleShot(60000, lambda: _morning_fallback(gen))
            return
    except Exception:
        pass
    _morning(False)
    if _state["board_shown"] and mw.state == "deckBrowser":
        _swap(cfg())


def _push_on_open():
    if not mw.col or not client().signed_in or client().session_dead:
        return
    if not _open_push_due(time.time(), _run.last_attempt):
        return
    _run.last_attempt = time.time()
    _on_sync_done(light=True, fetch=False)  # the open just drew the board


def _mark_anki_synced(*_args):
    _state["anki_synced"] = True


def _awaiting_phone():
    """This profile syncs with AnkiWeb and no sync has finished since it
    opened: reviews done on a phone may not have arrived yet (2.11.1)."""
    if _state["anki_synced"]:
        return False
    try:
        return bool(mw.pm.sync_auth())
    except Exception:
        return False


def _on_profile_close():
    _run.closing = True
    app.generation += 1  # nothing in flight lands after this
    try:
        rooms.on_close()  # 2.12: closing Anki leaves the room
    except Exception:
        oops()
    try:
        app.ai_app(on=False)  # Your AI app's local server goes with the profile
    except Exception:
        oops()
    try:
        magic_flow.close()  # 3.9.7: Magic search reads this profile's collection
    except Exception:
        oops()
    try:
        errs_flow.close_profile()  # 3.9.9: its counts on disk
    except Exception:
        oops()


# Names of the parts after this one. The package sets them as each of those parts loads
# (an import here would load a later part before the ones between).
_LATER = ("k",)
k = None
