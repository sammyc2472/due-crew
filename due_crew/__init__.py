"""Due Crew — your friends' studying next to yours, on the Decks screen.

Threading rules: collection access, config writes, and ALL cache commits
happen on the main thread; HTTP happens in background threads with timeouts.
Workers fetch and hand the result to _commit via run_on_main, so the main
thread is the only writer of shared state and renders never see torn data.

Anki profiles share the add-on folder, so session/streak files live under
user_files/<profile>/ and all runtime state resets on profile switch.

Document-read budget: full 7-day history once per day and on manual Refresh;
other refreshes fetch only today (plus my next label, so friends whose day
already rolled over ahead of my timezone stay live).
"""

import html
import json
import os
import threading
import time
import traceback

from aqt import gui_hooks, mw
from aqt.deckbrowser import DeckBrowser
from aqt.qt import QAction, QCursor, QMenu
from aqt.utils import tooltip

from . import board
from .backend.firebase import FirebaseClient
from .stats import gather_stats
from .stats.decks import gather_shared_decks
from .stats.queries import StatsQueries

CHEER_EMOJI = ("\U0001F389", "\U0001F4AA", "\U0001F525")  # party, muscle, fire

_client = None
_client_profile = None
_state = {
    "entries": None, "days": {}, "decks": {}, "labels": [], "tomorrow": "",
    "pending": [], "ts": 0.0, "prev_label": "", "prev_counts": {},
    "board_shown": False,
}
_pending_cheers = []
_lock = threading.Lock()
_fetching = False
_menu_done = False


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


def _reset_runtime():
    _state.update(entries=None, days={}, decks={}, labels=[], tomorrow="",
                  pending=[], ts=0.0, prev_label="", prev_counts={},
                  board_shown=False)
    _pending_cheers.clear()


def _board_data():
    return {"entries": _state["entries"], "labels": _state["labels"],
            "tomorrow": _state["tomorrow"], "pending": _state["pending"]}


# ---- refresh ----

def refresh_board(upload_stats=None, shared_decks=None, full=False):
    """Fetch (and optionally upload first) in the background. Main thread
    only. An upload is never dropped: only pure fetches dedup against an
    in-flight refresh."""
    global _fetching
    if not mw.col or not client().signed_in:
        return
    uploading = upload_stats is not None or shared_decks is not None
    with _lock:
        if _fetching and not uploading:
            return
        _fetching = True
    try:
        c = cfg()
        q = StatsQueries(mw.col)
        labels = [q.day_label(i) for i in range(7)]
        tomorrow = q.day_label(-1)
        cl = client()
        uid = cl.user_id
        name = cl.display_name or "Me"
        full = (full or _state["entries"] is None or not _state["labels"]
                or _state["labels"][0] != labels[0])
    except Exception:
        with _lock:
            _fetching = False
        traceback.print_exc()
        return
    fetch_labels = labels if full else labels[:1]

    def job():
        global _fetching
        try:
            if upload_stats is not None:
                cl.upload_today(uid, name, labels[0], upload_stats, c)
            if shared_decks is not None and not c.get("paused"):
                cl.upload_shared(uid, shared_decks)
            data = cl.fetch_board(uid, fetch_labels, tomorrow=tomorrow,
                                  include_shared=full)
            mw.taskman.run_on_main(lambda: _commit(data, c, labels, tomorrow))
        except Exception:
            traceback.print_exc()  # cache stays untouched on failure
        finally:
            with _lock:
                _fetching = False

    threading.Thread(target=job, daemon=True).start()


def _commit(data, c, labels, tomorrow):
    """Main thread. The only writer of _state and _pending_cheers."""
    keep = set(labels) | {tomorrow}
    day_store = _state["days"]
    seen = set()
    for e in data["entries"]:
        uid = e["user_id"]
        seen.add(uid)
        merged = {lb: d for lb, d in day_store.get(uid, {}).items() if lb in keep}
        merged.update(e["days"])
        day_store[uid] = merged
        e["days"] = merged
        if e["decks"] is None:  # not fetched this time — keep what we had
            e["decks"] = _state["decks"].get(uid, [])
        else:
            _state["decks"][uid] = e["decks"]
    for uid in list(day_store):
        if uid not in seen:
            day_store.pop(uid, None)
            _state["decks"].pop(uid, None)

    # day-keyed toast baseline: first sync of a friend's day toasts too
    today = labels[0]
    toasts = []
    counts = {}
    baseline_valid = _state["prev_label"] == today
    for e in data["entries"]:
        if e["you"]:
            continue
        doc = e["days"].get(tomorrow) or e["days"].get(today)
        reviews = (doc or {}).get("reviews")
        counts[e["user_id"]] = reviews if isinstance(reviews, int) else 0
        if baseline_valid and c.get("sync_notifications", True):
            old = _state["prev_counts"].get(e["user_id"])
            if old is not None and counts[e["user_id"]] > old:
                toasts.append(f"{html.escape(e['name'])} just studied — "
                              f"{counts[e['user_id']]:,} reviews today")
    _state["prev_label"] = today
    _state["prev_counts"] = counts

    last_seen = client().session.get("cheers_seen_ts", "")
    fresh = [ch for ch in data.get("cheers", []) if ch["at"] > last_seen]
    if fresh:
        client().session["cheers_seen_ts"] = max(ch["at"] for ch in fresh)
        client()._save_session()
        _pending_cheers.extend(fresh)

    _state.update(entries=data["entries"], labels=labels, tomorrow=tomorrow,
                  pending=data["pending"], ts=time.time())

    if toasts:
        tooltip("<br>".join(toasts), period=5000)
    if _state["board_shown"] and mw.state == "deckBrowser":
        _swap(cfg())        # page not rebuilt: safe to play cheers directly
        _play_cheers()
    else:
        _rerender()         # deck_browser_did_render plays queued cheers


def _rerender():
    if mw.state == "deckBrowser":
        mw.deckBrowser.refresh()


def _play_cheers():
    if not _pending_cheers or mw.state != "deckBrowser":
        return
    cheers = list(_pending_cheers)
    _pending_cheers.clear()
    names = sorted({ch["name"] for ch in cheers})
    emojis = [ch["emoji"] for ch in cheers]
    if len(names) == 1:
        text = f"{emojis[0]} {names[0]} sent cheers"
    else:
        text = f"{' '.join(dict.fromkeys(emojis))} {' and '.join(names)} sent cheers"
    mw.web.eval(board.flurry_js(emojis, text))


# ---- hooks ----

def _on_render(deck_browser, content):
    try:
        c = cfg()
        if not c.get("show_leaderboard", True):
            _state["board_shown"] = False
            return
        if not client().signed_in:
            _state["board_shown"] = False
            content.stats += board.signed_out_card(c)
        elif _state["entries"] is None:
            _state["board_shown"] = False
            content.stats += board.loading_card(c)
            refresh_board()
        else:
            _state["board_shown"] = True
            content.stats += board.render(_board_data(), c, _state["ts"])
    except Exception:
        traceback.print_exc()


def _on_did_render(deck_browser):
    _play_cheers()


def _on_sync_done():
    if not mw.col or not client().signed_in:
        return
    c = cfg()
    try:
        stats = gather_stats(mw.col, _profile_files())
        decks = gather_shared_decks(mw.col, c)
    except Exception:
        traceback.print_exc()
        stats, decks = None, None
    refresh_board(upload_stats=stats, shared_decks=decks)


def _on_js(handled, message, context):
    if not isinstance(context, DeckBrowser) or not message.startswith("duecrew:"):
        return handled
    parts = message.split(":")
    cmd = parts[1] if len(parts) > 1 else ""
    c = cfg()
    if cmd == "sort" and len(parts) > 2 and parts[2] in board.SORT_KEYS:
        c["sort"] = parts[2]
        save_cfg(c)
        _swap(c)
    elif cmd == "period" and len(parts) > 2 and parts[2] in board.PERIODS:
        c["period"] = parts[2]
        save_cfg(c)
        _swap(c)
    elif cmd == "refresh":
        refresh_board(full=True)
    elif cmd == "friends":
        open_friends()
    elif cmd == "decks":
        open_decks()
    elif cmd == "setup":
        open_auth()
    elif cmd == "cheerpick" and len(parts) > 2:
        _cheer_menu(parts[2])
    else:
        print(f"due crew: unknown command {message!r}")
    return (True, None)


def _swap(c):
    """Re-render the board in place from cache. No network, no page reload."""
    if _state["entries"] is None:
        _rerender()
        return
    html_out = board.render(_board_data(), c, _state["ts"])
    js = """
    (function() {
        var el = document.getElementById('due-crew');
        if (!el) { return; }
        var tmp = document.createElement('div');
        tmp.innerHTML = %s;
        el.parentNode.replaceChild(tmp.firstElementChild, el);
    })();
    """ % json.dumps(html_out)
    mw.web.eval(js)


# ---- cheers ----

def _cheer_menu(to_uid):
    entry = next((e for e in (_state["entries"] or [])
                  if e["user_id"] == to_uid), None)
    if entry is None:
        return
    menu = QMenu(mw)
    for emoji in CHEER_EMOJI:
        action = menu.addAction(f"{emoji}  Cheer {entry['name']}")
        action.triggered.connect(
            lambda _=False, em=emoji: _send_cheer(to_uid, entry["name"], em))
    menu.exec(QCursor.pos())


def _send_cheer(to_uid, to_name, emoji):
    cl = client()
    uid = cl.user_id
    my_name = cl.display_name or "A friend"

    def job():
        try:
            ok = cl.send_cheer(to_uid, uid, my_name, emoji)
        except Exception:
            ok = False
        msg = (f"Sent {emoji} to {html.escape(to_name)}." if ok
               else "Couldn't send. Check your connection.")
        mw.taskman.run_on_main(lambda: tooltip(msg))

    threading.Thread(target=job, daemon=True).start()


# ---- dialogs ----

def open_auth():
    from .ui.auth_dialog import AuthDialog
    dlg = AuthDialog(mw, client())
    if dlg.exec() and dlg.user:
        _uid, name = dlg.user
        _reset_runtime()
        _on_sync_done()
        _rerender()
        tooltip(f"Welcome, {html.escape(name)}.")


def open_friends():
    if not client().signed_in:
        open_auth()
        return
    from .ui.friends_dialog import FriendsDialog
    dlg = FriendsDialog(mw, client())
    dlg.exec()
    if dlg.changed:
        refresh_board(full=True)


def open_decks():
    if not client().signed_in:
        open_auth()
        return
    if not mw.col:
        return
    from .ui.decks_dialog import DecksDialog
    dlg = DecksDialog(mw, cfg(), _state["entries"] or [], _on_decks_saved)
    dlg.exec()


def _on_decks_saved(changed):
    c = cfg()
    c.update(changed)
    save_cfg(c)
    try:
        decks = gather_shared_decks(mw.col, c)
    except Exception:
        traceback.print_exc()
        decks = None
    refresh_board(shared_decks=decks)


def open_settings():
    from .ui.settings_dialog import SettingsDialog
    dlg = SettingsDialog(mw, client(), cfg(), _on_settings_saved,
                         open_auth, open_friends, _on_signed_out, open_decks)
    dlg.exec()


def _on_settings_saved(changed):
    """`changed` holds only the keys the dialog owns — never a stale
    snapshot of the whole config."""
    c = cfg()
    c.update(changed)
    save_cfg(c)
    _rerender()


def _on_signed_out():
    _reset_runtime()
    _rerender()


# ---- startup ----

def _on_profile_open():
    global _menu_done
    if not _menu_done:
        _menu_done = True
        action = QAction("Due Crew", mw)
        action.triggered.connect(open_settings)
        mw.form.menuTools.addAction(action)
        mw.addonManager.setConfigAction(__name__, open_settings)
    _reset_runtime()          # profile switch: nothing carries over
    client()                  # rebind to this profile's session
    refresh_board()


gui_hooks.deck_browser_will_render_content.append(_on_render)
gui_hooks.deck_browser_did_render.append(_on_did_render)
gui_hooks.sync_did_finish.append(_on_sync_done)
gui_hooks.webview_did_receive_js_message.append(_on_js)
gui_hooks.profile_did_open.append(_on_profile_open)
