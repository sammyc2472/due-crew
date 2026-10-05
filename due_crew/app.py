"""Shared runtime: config, the API client for the open profile, the
board cache, and the one background helper. Everything the other modules
need and nothing that renders. The four late-bound hooks at the bottom are
set by __init__ so squads/social/shares can trigger a redraw or a refresh
without importing the package root."""

import json
import os
import threading
import traceback

from aqt import mw

from .backend.api import ApiClient


def _read_version():
    try:
        with open(os.path.join(os.path.dirname(__file__), "manifest.json")) as f:
            return str(json.load(f).get("version") or "")
    except Exception:
        return ""


ADDON_VERSION = _read_version()   # sent with my profile, and checked against /version
STALE_SECS = 900                  # a board older than this refreshes itself

# the cheer picker's quick row
CHEER_QUICK = ("\U0001F389", "\U0001F4AA", "\U0001F525",   # party, muscle, fire
               "\U0001F44F", "\U0001F680", "\u2615")       # clap, rocket, coffee


STREAK_MILESTONES = (7, 30, 100, 365)


CREW_REVIEW_MILESTONES = (100_000, 250_000, 500_000, 1_000_000)


CREW_HOUR_MILESTONE_MS = 1000 * 3600 * 1000  # 1,000 hours


RETURN_QUIET_DAYS = 7


HEATMAP_DAYS = 182


SQUAD_CACHE_SECS = 300


# after an upload, the board is read again only if it is older than this
FRESH_SECS = 120


_client = None


# bumped at profile open and close, sign-in and sign-out: a background job
# captures it, and drops what it brings back when it has changed (an old
# profile's board must not land in the next one's)
generation = 0


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
    "knocks": [],          # [(sender_uid, name, squad_id)] awaiting my add
    "sync_error": False,   # the last upload/fetch failed; the footer says so
    "decks_day": "",       # the day shared-deck docs last rode a board fetch
    "decks_ts": 0.0,       # when the Decks tab last fetched them itself
    "my_code": "",         # my friend code, for Copy invite on a solo board
    "milestones": [],      # [(uid, name, days)]: a crewmate's 100/365-day streak, today
    "anki_synced": False,  # an AnkiWeb sync finished since the profile opened
    "settings_tab": None,  # 3.5.0: Settings open in the board, on this tab
    "room_dismissed": set(),  # study-room invites waved off this session
    "room_skip": None,     # (room key, round): the break I skipped
    "room_break": False,   # the break is on screen (review shortcuts are off)
    "room_refreshed": None,  # (room key, round): that break's one refresh
    "settings_ready": False,   # 2.13: my account settings were pulled (or can't be)
    "settings_pulling": False,
    "settings_failed_ts": 0.0,  # when a pull last failed for want of a network
    "plan_progress": {},   # 3.1: {plan id: {unit id: [opened, seen, total]}}, counted here
    "plan_session": {},    # 3.2: {plan id: today's session}, for plans on my schedule
    "plan_updates": {},    # 3.8: {plan id: {n, names, units}}: an update's cards, waiting for Open
    "plans_midday": False, # 3.8: an update came while reviewing; it waits for the Decks screen
    "notice": None,        # 3.2.1: the admin's notice, {id, text, link}
    "bingo_open": False,   # 3.6: the squad's bingo card is open in the board's place
    "bingo_mine": None,    # 3.6: {wk, play, progress}: my week as worked out at the sync (progress never sent)
    "squads_left": set(),  # 3.6: squads I left this session, which heal_squads never brings back
    "plan_sub": {},        # 3.9: {plan id: "team" | "ins"}: the plan's tab on screen (Plan when absent)
    "team_view": {},       # 3.9: {plan id: {at, data, state}}: the team as its tab last fetched it
    "team_draft": {},      # 3.9: {plan id: text}: Ask, filled in from Insights
    "team_bingo_open": None,  # 3.9: the plan whose team bingo card is open in the board's place
    "team_bingo_mine": {},  # 3.9: {plan id: {wk, progress}}: my squares on the plan's cards (never sent)
    "insights": {},        # 3.9: {plan id: {at, rows}}: worked out here, never sent
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


# 2.13: set by __init__ to account.on_change; a config write that changes a
# setting that follows the account also saves it there
on_account_change = None


def save_cfg(c, from_account=False):
    """from_account: the account's own settings arriving; no echo back."""
    before = mw.addonManager.getConfig(__name__) or {}
    mw.addonManager.writeConfig(__name__, c)
    if not from_account and on_account_change is not None:
        from .account import ACCOUNT_KEYS
        if any(before.get(k) != c.get(k) for k in ACCOUNT_KEYS):
            on_account_change(c)


def client():
    global _client, _client_profile
    key = _profile_key()
    if _client is None or _client_profile != key:
        # api_base: an unlisted config key for trying a client against the
        # dev Worker (api-dev.duecrew.com) before the crew gets it
        _client = ApiClient(os.path.join(_profile_files(), "session.json"),
                            base=str(cfg().get("api_base") or "") or None)
        _client_profile = key
    return _client


def _reset_runtime(keep_sync=False):
    """keep_sync: signing in or out mid-session; whether AnkiWeb has synced
    is about the collection, which hasn't changed."""
    global generation
    generation += 1
    synced = _state["anki_synced"] if keep_sync else False
    from .stats.decks import clear_cache
    clear_cache()  # fingerprints belong to the last profile's collection
    _state.update(entries=None, days={}, decks={}, labels=[], tomorrow="",
                  pending=[], ts=0.0, prev_label="", prev_counts={},
                  prev_streaks={}, board_shown=False,
                  my_friends=[],
                  squad={"id": "", "data": None, "day": "", "ts": 0.0,
                         "state": "loading"},
                  knocks=[], sync_error=False, decks_day="", decks_ts=0.0, my_code="",
                  milestones=[], anki_synced=synced,
                  room_dismissed=set(), room_skip=None, room_break=False,
                  room_refreshed=None, settings_ready=False, settings_pulling=False,
                  settings_failed_ts=0.0, plan_progress={}, plan_session={}, notice=None,
                  plan_updates={}, plans_midday=False,
                  bingo_open=False, bingo_mine=None, squads_left=set(),
                  settings_tab=None, plan_sub={}, team_view={}, team_draft={},
                  team_bingo_open=None, team_bingo_mine={}, insights={})
    _pending_cheers.clear()


# ---- late-bound hooks, set by __init__ (which owns rendering + refresh) ----

swap = None       # swap(cfg): re-render the board in place from cache
rerender = None   # rerender(): rebuild the deck screen
refresh = None    # refresh(**kw): refresh_board
sync = None       # sync(**kw): _on_sync_done (upload + fetch)


def feedback_versions(addon_version=None):
    """3.6.5, P6: 'add-on 3.6.5 · Anki 24.11 · Mac', what the admin sees beside
    feedback when the box is ticked."""
    import platform
    try:
        from anki.buildinfo import version as anki_version
    except Exception:
        anki_version = "?"
    osname = {"Darwin": "Mac", "Windows": "Windows", "Linux": "Linux"}.get(platform.system(), platform.system() or "?")
    return f"add-on {addon_version or ADDON_VERSION} · Anki {anki_version} · {osname}"
