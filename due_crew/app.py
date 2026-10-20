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
from .backend.shapes import TransportError


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
    the main thread. An exception delivers None, so a caller treating None
    as failure gets the failure. A TransportError (no network, the server
    busy, signed out) is one line on stdout: Anki shows anything on stderr
    in its error window, and being offline isn't an error (3.9.2: a settings
    pull that got no answer did). Anything else prints its traceback."""
    def worker():
        try:
            result = job()
        except TransportError as e:
            print(f"due crew: {e}")
            result = None
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
    "room_card": None,     # 3.8.1: the room's card is out, from the chip ("chip", "bottom", "gutter"), which hides
    "room_break": False,   # the break is on screen (review shortcuts are off)
    "room_refreshed": None,  # (room key, round): that break's one refresh
    "settings_ready": False,   # 2.13: my account settings were pulled (or can't be)
    "settings_pulling": False,
    "settings_failed_ts": 0.0,  # when a pull last failed for want of a network
    "plan_progress": {},   # 3.1: {plan id: {unit id: [opened, seen, total]}}, counted here
    "plan_load": {},       # 3.7.81: {plan id: {unit id: [seen, open, locked]}}, my days, counted here
    "plan_session": {},    # 3.2: {plan id: today's session}, for plans on my schedule
    "plan_updates": {},    # 3.7.3: {plan id: {n, names, units}}: an update's cards, waiting for Open
    "plans_midday": False, # 3.7.3: an update came while reviewing; it waits for the Decks screen
    "plans_morning": None, # 3.8.0: {awaiting, fresh}: the morning came off the Decks screen; it waits for it
    "notice": None,        # 3.2.1: the admin's notice, {id, text, link}
    "bingo_open": False,   # 3.6: the squad's bingo card is open in the board's place
    "bingo_mine": None,    # 3.6: {wk, play, progress}: my week as worked out at the sync (progress never sent)
    "squads_left": set(),  # 3.6: squads I left this session, which heal_squads never brings back
    "team_view": {},       # 3.7.3: {plan id: {at, data, state}}: the team as its tab last fetched it
    "team_draft": {},      # 3.7.3: {plan id: text}: Ask, filled in from Insights
    "team_bingo_open": None,  # 3.7.3: the plan whose team bingo card is open in the board's place
    "insights": {},        # 3.8.0: {deck id: {at, view, key}}: Insights, worked out here, never sent
    "you_decks": None,     # 3.8.0: {at, list}: Insights' decks, as its picker shows them
    "two_tried": False,    # 3.9.1: two buttons, just turned on from the Hard habit line (its Undo shows)
}


_pending_cheers = []


# disk (3.9.1): (path, text) of wrap.json as last read or written, so a save
# that would write the same text writes nothing
_wrap = {"profile": None, "data": {}, "disk": None}


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


# 3.9.1 (the efficiency run): Anki's getConfig reads config.json and
# meta.json from disk each time, and the review screen asks a few times a
# card. The merged doc is kept as text (each caller still gets its own copy
# to change) until save_cfg writes; Anki's own config editor isn't ours to
# worry about (setConfigAction opens Settings in its place).
_CFG = {"text": None}


def cfg():
    text = _CFG["text"]
    if text is None:
        text = _CFG["text"] = json.dumps(mw.addonManager.getConfig(__name__) or {})
    return json.loads(text)


# 3.9.1: one count of new pages in any of Anki's webviews
# (webview_will_set_content). What a page was sent once (rooms' widgets, a
# card's Pip sheet) is sent again once this moves.
pages = [0]


def on_set_content(_content=None, context=None, *_args):
    pages[0] += 1
    if not _a_bar(context):
        _drop_emoji_box()
    if _veiled[0] and not _a_bar(context):
        veil(False)  # the main view's new page has no window open over it


def _a_bar(context):
    """The top bar's or a bottom bar's page (Anki's TopToolbar, Toolbar,
    DeckBrowserBottomBar, OverviewBottomBar, ReviewerBottomBar)."""
    name = type(context).__name__
    return name in ("TopToolbar", "Toolbar") or name.endswith("BottomBar")


# 3.9.1 (Sam: "when cheering, the full background doesn't grey out"): while
# a window is open over the board (the Cheer window, a profile card, a
# sheet), the top bar and the bottom bar, pages of their own, wear the
# board's backdrop too, and a tap on either is Esc on the board, as a tap on
# the backdrop closes it. The board's page says when (board.VEIL_WATCH_JS);
# a new page in the main view or leaving the Decks screen takes it off.
VEIL_JS = """(function (on) {
  var v = document.getElementById('dc-veil');
  if (!v) {
    if (!on) { return; }
    var still = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    v = document.createElement('div');
    v.id = 'dc-veil';
    v.style.cssText = 'position:fixed;inset:0;z-index:2147483647;background:rgba(0,0,0,.35);opacity:0;' + (still ? '' : 'transition:opacity .22s;');
    v.addEventListener('click', function () { if (typeof pycmd !== 'undefined') { pycmd('duecrew:veiltap|%(key)s'); } });
    document.body.appendChild(v);
    v.getBoundingClientRect();
  }
  v.style.opacity = on ? '1' : '0';
  v.style.pointerEvents = on ? 'auto' : 'none';
})(%(on)s);"""
_veiled = [False]


def veil(on):
    from .room_model import CMD_KEY
    _veiled[0] = bool(on)
    js = VEIL_JS % {"key": CMD_KEY, "on": "true" if on else "false"}
    for web in (getattr(getattr(mw, "toolbar", None), "web", None), getattr(mw, "bottomWeb", None)):
        try:
            if web is not None:
                web.eval(js)
        except Exception:
            pass


# 3.9.1 (the security review): whether Anki's main view has the Decks page
# in it. Anki says "deckBrowser" from the moment it switches, but the page
# before (a card's, or Overview's with a deck's description, scripts and
# all) stays up until the Decks page is built; what we draw on the board
# (its commands carry board.BOARD_KEY) waits for that page.
_decks = [False]


def _drop_emoji_box():
    """3.9.2's audit: the Cheer window's box over "pick one" (native_emoji) goes
    with the page it sat on (a redraw, another screen, a profile switch)."""
    try:
        from .native_emoji import drop
        drop()
    except Exception:
        pass


def on_state_will_change(*_args):
    _drop_emoji_box()
    _decks[0] = False
    if _veiled[0]:
        veil(False)


def on_decks_render():
    _decks[0] = True  # deck_browser_will_render_content: the Decks page goes in now


def board_up():
    return mw.state == "deckBrowser" and _decks[0]


def board_eval(js):
    """mw.web.eval, for what draws on the board: only on the Decks page."""
    if board_up():
        mw.web.eval(js)


# 2.13: set by __init__ to account.on_change; a config write that changes a
# setting that follows the account also saves it there
on_account_change = None


def save_cfg(c, from_account=False):
    """from_account: the account's own settings arriving; no echo back."""
    before = cfg()
    _CFG["text"] = None
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
                  settings_failed_ts=0.0, plan_progress={}, plan_load={}, plan_session={}, notice=None,
                  plan_updates={}, plans_midday=False, plans_morning=None,
                  bingo_open=False, bingo_mine=None, squads_left=set(),
                  settings_tab=None, team_view={}, team_draft={},
                  team_bingo_open=None, insights={}, you_decks=None,
                  closet_open=None, closet_new=None,  # 3.8.2: Pip's closet, and what just came for it
                  wrapped_open=None,  # 3.9.0: your Wrapped, in the board's place
                  two_tried=False,  # 3.9.1
                  # 3.9.2's audit: keyed by deck id, and the Default deck is 1 in every collection
                  leech_view={}, leech_open={}, leech_line={}, map_at={}, ahead_day={}, ahead_line=None, ahead_asked=set())
    _pending_cheers.clear()
    try:  # 3.9.3: the plan windows were the last account's (its plans, its requests in flight)
        from .planner import flow as planner_flow
        planner_flow.close_all()
    except Exception:
        traceback.print_exc()
    try:  # Your AI app's local server: started again for this profile and account, or off
        ai_app()
    except Exception:
        traceback.print_exc()


def ai_app(on=True):
    """Your AI app's local server (planner/mcp_host.py): on as this
    computer's switch says, with a profile open and signed in (follow), or
    off (on=False: the profile closing). Loaded only once the switch is on."""
    import sys
    loaded = sys.modules.get(f"{__package__}.planner.mcp_host")
    if loaded is None:
        m = cfg().get("mcp")
        if not on or not (isinstance(m, dict) and m.get("on") is True):
            return
        from .planner import mcp_host as loaded
    if on:
        loaded.follow()
    else:
        loaded.stop()


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
