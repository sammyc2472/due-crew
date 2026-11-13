"""Due Crew — your friends' studying next to yours, on the Decks screen.

Threading rules: collection access, config writes, and ALL cache commits
happen on the main thread; HTTP happens in background threads with timeouts.
Workers fetch and hand the result to _commit via run_on_main, so the main
thread is the only writer of shared state and renders never see torn data.

Anki profiles share the add-on folder, so session/streak files live under
user_files/<profile>/ and all runtime state resets on profile switch.

Request budget (3.0): a refresh is one request (GET /board: me, my crew
with their weeks, cheers, knocks), a sync is one (POST /sync), and the
server writes only what changed. The Decks tab, a profile's heatmap and a
squad board each fetch their own, when someone looks.

3.9.12 (the foundations, Stage B): the glue itself is glue/, a package by part (refresh, render,
sync, commands, windows, settings, profile, table, joined), one namespace as before: every name it
has, this package has, and setting one here (a test's stand-in) sets it in each part that has it.
The five flags the glue sets as it runs (_fetching, _menu_done, _last_attempt, _closing, _pushed)
live in one holder, glue.refresh._run; here they read and set it.
"""

import datetime
import html
import re
import sys
import threading
import types
import time

from urllib.parse import unquote as _unquote
from aqt import gui_hooks, mw
from aqt.deckbrowser import DeckBrowser
from aqt.qt import QAction, QTimer
from aqt.utils import tooltip

from . import app, board
from .app import (_bg, ADDON_VERSION, FRESH_SECS, HEATMAP_DAYS, SQUAD_CACHE_SECS,
                  STALE_SECS, STREAK_MILESTONES,
                  _pending_cheers, _profile_files, _reset_runtime, _state, cfg, client,
                  save_cfg)
from .backend.shapes import TransportError, _clean_day, clean_emoji, shared_numbers
from .shares import _share, dismiss_review, review_banners
from .shares import picture as share_picture
from .social import (_cheer_menu, _edit_emoji, _edit_status, _fresh_cheers, _open_profile,
                     _play_cheers, _send_cheer, cheer_allowed, drop_muted, held_uids, muted_uids, row_menu,
                     send_held)
from .squads import (_add_back, _block_member, _copy_invite, _dismiss_knock, _drop_squad,
                     _fetch_squad, _kick_member, _leave_squad, _make_founder, _my_squads,
                     _open_squad_card, _select_squad, _send_knock, _share_squad, _squad_view,
                     _toggle_squad_lock, _visible_knocks, heal_squads, open_squads)
from .stats import gather_stats, gather_week, held_streak, week_days
from .stats import heatmap as cached_heatmap
from .stats.decks import gather_shared_decks
from .stats.queries import StatsQueries
from .ui import copy_text
from . import account, ahead_flow, bingo_flow, due_flow, errs, errs_flow, gamenight_flow, magic_flow, plan_flow, rooms, sheets, together, two_buttons
from . import cards as crew_cards
from .wrap import (_arrivals, _deck_deltas, _exam_eve_info, _mute_knocker, _save_wrap, _update_returns,
                   _update_wrap, _wrap_data, _wrap_info)
from .errs import oops

# every name this file imported when it held the glue, kept in the package's namespace (pyflakes: read here)
_KEPT = (datetime, html, re, threading, time, _unquote, gui_hooks, mw, DeckBrowser, QAction, QTimer, tooltip,
         app, board, _bg, ADDON_VERSION, FRESH_SECS, HEATMAP_DAYS, SQUAD_CACHE_SECS, STALE_SECS,
         STREAK_MILESTONES, _pending_cheers, _profile_files, _reset_runtime, _state, cfg, client, save_cfg,
         TransportError, _clean_day, clean_emoji, shared_numbers, _share, dismiss_review, review_banners,
         share_picture, _cheer_menu, _edit_emoji, _edit_status, _fresh_cheers, _open_profile, _play_cheers,
         _send_cheer, cheer_allowed, drop_muted, held_uids, muted_uids, row_menu, send_held, _add_back,
         _block_member, _copy_invite, _dismiss_knock, _drop_squad, _fetch_squad, _kick_member, _leave_squad,
         _make_founder, _my_squads, _open_squad_card, _select_squad, _send_knock, _share_squad, _squad_view,
         _toggle_squad_lock, _visible_knocks, heal_squads, open_squads, gather_stats, gather_week,
         held_streak, week_days, cached_heatmap, gather_shared_decks, StatsQueries, copy_text, account,
         ahead_flow, bingo_flow, due_flow, errs, errs_flow, gamenight_flow, magic_flow, plan_flow, rooms,
         sheets, together, two_buttons, crew_cards, _arrivals, _deck_deltas, _exam_eve_info, _mute_knocker,
         _save_wrap, _update_returns, _update_wrap, _wrap_data, _wrap_info, oops)

from . import glue  # noqa: E402  (its parts load in order; the last one joins Anki's hooks)

globals().update({_k: _v for _k, _v in vars(glue).items() if not _k.startswith("__") and _k != "PARTS"})


def _flag(name):
    return property(lambda self: getattr(glue._run, name), lambda self, value: setattr(glue._run, name, value))


class _Glue(types.ModuleType):
    _fetching = _flag("fetching")
    _menu_done = _flag("menu_done")
    _last_attempt = _flag("last_attempt")
    _closing = _flag("closing")
    _pushed = _flag("pushed")

    def __setattr__(self, name, value):
        setattr(glue, name, value)  # each part that has the name
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _Glue
