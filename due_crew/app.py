"""Shared runtime: config, the Firebase client for the open profile, the
board cache, and the one background helper. Everything the other modules
need and nothing that renders. The four late-bound hooks at the bottom are
set by __init__ so squads/social/shares can trigger a redraw or a refresh
without importing the package root."""

import json
import os
import threading
import traceback

from aqt import mw
from aqt.utils import tooltip

from .backend.firebase import FirebaseClient


def _read_version():
    try:
        with open(os.path.join(os.path.dirname(__file__), "manifest.json")) as f:
            return str(json.load(f).get("version") or "")
    except Exception:
        return ""


ADDON_VERSION = _read_version()   # written to my profile so a stuck build shows
STALE_SECS = 900                  # a board older than this refreshes itself

# the cheer picker's quick row. The first three are all that rules before v8
# accept, and all a client offers while the server is still on them.
CHEER_QUICK = ("\U0001F389", "\U0001F4AA", "\U0001F525",   # party, muscle, fire
               "\U0001F44F", "\U0001F680", "\u2615")       # clap, rocket, coffee
CHEER_CLASSIC = CHEER_QUICK[:3]


STREAK_MILESTONES = (7, 30, 100, 365)


CREW_REVIEW_MILESTONES = (100_000, 250_000, 500_000, 1_000_000)


CREW_HOUR_MILESTONE_MS = 1000 * 3600 * 1000  # 1,000 hours


RETURN_QUIET_DAYS = 7


HEATMAP_DAYS = 182


SQUAD_CACHE_SECS = 300


_client = None


_client_profile = None


def _bg(job, done=None):
    """Run job() off the main thread; deliver its result to done(result) on
    the main thread. An exception prints its traceback and delivers None,
    so a caller treating None as failure gets both the failure and a log."""
    def worker():
        try:
            result = job()
        except Exception:
            traceback.print_exc()
            result = None
        if done is not None:
            mw.taskman.run_on_main(lambda: done(result))
    threading.Thread(target=worker, daemon=True).start()


_state = {
    "entries": None, "days": {}, "decks": {}, "labels": [], "tomorrow": "",
    "pending": [], "ts": 0.0, "prev_label": "", "prev_counts": {},
    "prev_streaks": {}, "board_shown": False,
    "my_friends": [],
    "squad": {"id": "", "data": None, "day": "", "ts": 0.0, "state": "loading"},
    "knocks": [],
    "sync_error": False,   # the last upload/fetch failed; the footer says so
    "decks_day": "",       # the day shared-deck docs last rode a board fetch
    "decks_ts": 0.0,       # when the Decks tab last fetched them itself
    "my_code": "",         # my friend code, for Copy invite on a solo board   # [(sender_uid, name, squad_id)] awaiting my add
}


_pending_cheers = []


_wrap = {"profile": None, "data": {}}


def _profile_key():
    name = str(getattr(mw.pm, "name", "") or "default")
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name) or "default"


def _profile_files():
    root = os.path.join(os.path.dirname(__file__), "user_files")
    d = os.path.join(root, _profile_key())
    os.makedirs(d, exist_ok=True)
    # one-time migration from the pre-1.2.4 shared location
    for name in ("session.json", "streak.json"):
        old, new = os.path.join(root, name), os.path.join(d, name)
        if os.path.exists(old) and not os.path.exists(new):
            try:
                os.replace(old, new)
            except OSError:
                pass
    return d


def cfg():
    return mw.addonManager.getConfig(__name__) or {}


def save_cfg(c):
    mw.addonManager.writeConfig(__name__, c)


def client():
    global _client, _client_profile
    key = _profile_key()
    if _client is None or _client_profile != key:
        _client = FirebaseClient(os.path.join(_profile_files(), "session.json"))
        _client_profile = key
    return _client


def _migrate_server_json():
    """v1.4–v1.9 kept a per-profile server.json (crew servers). v2.0 runs on
    one hosted backend. A file pointing at the default project is simply
    retired; one pointing elsewhere means this account lived on a custom
    project that the add-on no longer talks to — sign out locally so the
    board offers a fresh sign-in instead of failing quietly."""
    path = os.path.join(_profile_files(), "server.json")
    if not os.path.exists(path):
        return
    try:
        with open(path) as f:
            conf = json.load(f)
    except Exception:
        conf = {}
    try:
        os.remove(path)
    except OSError:
        pass
    project = str((conf or {}).get("projectId") or "")
    if project and project != client().project_id:
        client().sign_out()
        tooltip("Due Crew now runs on one server. Sign in again to continue.")


def _reset_runtime():
    _state.update(entries=None, days={}, decks={}, labels=[], tomorrow="",
                  pending=[], ts=0.0, prev_label="", prev_counts={},
                  prev_streaks={}, board_shown=False,
                  my_friends=[],
                  squad={"id": "", "data": None, "day": "", "ts": 0.0,
                         "state": "loading"},
                  knocks=[], sync_error=False, decks_day="", decks_ts=0.0, my_code="")
    _pending_cheers.clear()


# ---- late-bound hooks, set by __init__ (which owns rendering + refresh) ----

swap = None       # swap(cfg): re-render the board in place from cache
rerender = None   # rerender(): rebuild the deck screen
refresh = None    # refresh(**kw): refresh_board
sync = None       # sync(**kw): _on_sync_done (upload + fetch)
