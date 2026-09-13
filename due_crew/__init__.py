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
import threading
import time
import traceback

from aqt import gui_hooks, mw
from aqt.deckbrowser import DeckBrowser
from aqt.qt import QAction
from aqt.utils import tooltip

from . import app, board
from .app import (CHEER_EMOJI, HEATMAP_DAYS, STREAK_MILESTONES, _migrate_server_json,
                  _pending_cheers, _profile_files, _reset_runtime, _state, cfg, client,
                  save_cfg)
from .backend.firebase import TransportError
from .shares import _share
from .social import (_cheer_menu, _edit_status, _fresh_cheers, _open_profile, _play_cheers,
                     _send_cheer)
from .squads import (_add_back, _copy_invite, _dismiss_knock, _drop_squad, _fetch_squad,
                     _kick_member, _leave_squad, _my_squads, _open_squad_card, _select_squad,
                     _send_knock, _squad_view, _toggle_squad_lock, _visible_knocks, open_squads)
from .stats import gather_stats, gather_week
from .stats.decks import gather_shared_decks
from .stats.queries import StatsQueries
from .ui import copy_text
from .wrap import (_deck_deltas, _exam_eve_info, _mute_knocker, _save_wrap, _update_returns,
                   _update_wrap, _wrap_data, _wrap_info)

_lock = threading.Lock()
_fetching = False
_menu_done = False

def _board_data():
    return {"entries": _state["entries"], "labels": _state["labels"],
            "tomorrow": _state["tomorrow"], "pending": _state["pending"]}


def refresh_board(upload_stats=None, backfill=None, shared_decks=None,
                  heatmap=None, squad_row=None, full=False):
    """Fetch (and optionally upload first) in the background. Main thread
    only. An upload is never dropped: only pure fetches dedup against an
    in-flight refresh. heatmap: dict to upload, "off" to retract, None to
    leave alone. backfill: last week's studied days, hash-guarded so the
    steady state stays one daily write per sync."""
    global _fetching
    if not mw.col or not client().signed_in:
        return
    uploading = (upload_stats is not None or shared_decks is not None
                 or backfill is not None)
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
        squads = [sq["id"] for sq in _my_squads()]
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
            if backfill is not None:
                cl.upload_backfill(uid, backfill, c)
            if shared_decks is not None and not c.get("paused"):
                cl.upload_shared(uid, shared_decks)
            if heatmap is not None:
                if isinstance(heatmap, dict) and not c.get("paused"):
                    cl.upload_heatmap(uid, heatmap)
                elif not cl.session.get("heatmap_deleted"):
                    cl.delete_heatmap(uid)  # share turned off, or paused
            gone = []
            if squad_row is not None and squads and not c.get("paused"):
                gone = cl.upload_squad_rows(uid, dict(squad_row, day=labels[0]),
                                            squads)
            cl.check_rules(labels[0])  # cached: one real request per day
            data = cl.fetch_board(uid, fetch_labels, tomorrow=tomorrow,
                                  include_shared=full)
            try:
                knocks = cl.list_knocks(uid)  # one list request
            except TransportError:
                knocks = None
            mw.taskman.run_on_main(
                lambda: _commit(data, c, labels, tomorrow, knocks, gone))
        except TransportError:
            # expected when offline or flaky — stderr raises Anki's error
            # dialog, so this stays off that channel; cache untouched and
            # the board footer already says how old it is
            print("due crew: refresh failed (network); keeping the cached board")
        except Exception:
            traceback.print_exc()  # cache stays untouched on failure
        finally:
            with _lock:
                _fetching = False

    threading.Thread(target=job, daemon=True).start()


def _commit(data, c, labels, tomorrow, knocks=None, gone=()):
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
    for e in data["entries"]:
        if e["you"]:
            continue
        doc = e["days"].get(tomorrow) or e["days"].get(today)
        streak_val = (doc or {}).get("streak")
        if isinstance(streak_val, int):
            old = _state["prev_streaks"].get(e["user_id"])
            if isinstance(old, int) and c.get("sync_notifications", True):
                for t in STREAK_MILESTONES:
                    if old < t <= streak_val:
                        toasts.append(f"{html.escape(e['name'])} hit a "
                                      f"{t}-day streak \U0001F525")
            _state["prev_streaks"][e["user_id"]] = streak_val

    _state["prev_label"] = today
    _state["prev_counts"] = counts

    cl = client()
    fresh, seen = _fresh_cheers(data.get("cheers", []), cl.session.get("cheers_seen"),
                                cl.session.get("cheers_seen_ts", ""))
    if seen != cl.session.get("cheers_seen"):
        cl.session["cheers_seen"] = seen
        cl.session.pop("cheers_seen_ts", None)
        cl._save_session()
    if fresh:
        _pending_cheers.extend(fresh)

    if knocks is not None:
        _state["knocks"] = [tuple(k) for k in knocks]
    for sid in gone or ():
        name = next((sq.get("name") for sq in _my_squads() if sq["id"] == sid), None)
        _drop_squad(sid, swap=False)
        tooltip(f"You're no longer in {html.escape(name or 'a squad')}.")

    _state.update(entries=data["entries"], labels=labels, tomorrow=tomorrow,
                  pending=data["pending"], ts=time.time(),
                  my_friends=list(data.get("my_friends") or []))
    toasts += _update_returns(data["entries"], labels, tomorrow, c)
    milestone = _update_wrap(data["entries"], labels)
    if milestone and c.get("sync_notifications", True):
        toasts.append(milestone)

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
            content.stats += board.render(_board_data(), c, _state["ts"],
                                          wrap=_wrap_info(), deltas=_deck_deltas(),
                                          exam_eve=_exam_eve_info(),
                                          rules_stale=client().rules_stale,
                                          squad_view=_squad_view(), knocks=_visible_knocks())
    except Exception:
        traceback.print_exc()


def _on_did_render(deck_browser):
    _play_cheers()


def _on_sync_done():
    if not mw.col or not client().signed_in:
        return
    c = cfg()
    # independent try blocks: one gatherer failing must not silently stop
    # the others from uploading (that failure mode is invisible in the UI)
    stats = week = decks = heat = None
    try:
        stats = gather_stats(mw.col, _profile_files())
    except Exception:
        traceback.print_exc()
    try:
        week = gather_week(mw.col, _profile_files())
    except Exception:
        traceback.print_exc()
    try:
        decks = gather_shared_decks(mw.col, c)
    except Exception:
        traceback.print_exc()
    try:
        heat = (StatsQueries(mw.col).heatmap_counts(HEATMAP_DAYS)
                if c.get("share_heatmap", True) else "off")
    except Exception:
        traceback.print_exc()
    row = None
    if stats is not None:
        row = {"name": client().display_name or "Me",
               "reviews": int(stats.reviews),
               "studyTimeMs": int(stats.time_ms),
               "streak": int(stats.streak)}
        if stats.accuracy is not None:
            row["accuracy"] = float(stats.accuracy)
    refresh_board(upload_stats=stats, backfill=week, shared_decks=decks,
                  heatmap=heat, squad_row=row)


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
        if parts[2] == "squads":
            _fetch_squad()
    elif cmd == "refresh":
        refresh_board(full=True)
        if c.get("period") == "squads":
            _fetch_squad(force=True)
    elif cmd == "friends":
        open_friends()
    elif cmd == "decks":
        open_decks()
    elif cmd == "setup":
        open_auth()
    elif cmd == "cheerpick" and len(parts) > 2:
        _cheer_menu(parts[2])
    elif cmd == "status":
        _edit_status()
    elif cmd == "profile" and len(parts) > 2:
        _open_profile(parts[2])
    elif cmd == "evedismiss":
        w = _wrap_data()
        w["eve_dismissed"] = _state["labels"][0] if _state["labels"] else ""
        _save_wrap()
        _swap(c)
    elif cmd == "wrapdismiss":
        w = _wrap_data()
        w["dismissed"] = w.get("week", "")
        _save_wrap()
        _swap(c)
    elif cmd in ("sharetoday", "shareweek", "sharecrewweek"):
        _share(cmd)
    elif cmd == "wrapcopy":
        b = _wrap_info() or {}
        if b.get("reviews"):
            text = (f"Last week, together: {b['reviews']:,} reviews "
                    f"· {board._fmt_time(b.get('time_ms') or 0)}")
            if (b.get("full_days") or 0) >= 3:
                text += f" · everyone showed up {b['full_days']} of 7 days"
            if b.get("milestone"):
                text += f" · just passed {b['milestone']} all-time"
            copy_text(text + " — Due Crew")
            tooltip("Copied.")
    elif cmd == "settings":
        open_settings()
    elif cmd == "ecard" and len(parts) > 2:
        _open_squad_card(parts[2])
    elif cmd == "squad" and len(parts) > 2:
        _select_squad(parts[2])
    elif cmd == "squadadd":
        open_squads()
    elif cmd == "squadinvite":
        _copy_invite()
    elif cmd == "squadlock":
        _toggle_squad_lock()
    elif cmd == "squadleave":
        _leave_squad()
    elif cmd == "squadkick" and len(parts) > 2:
        _kick_member(parts[2])
    elif cmd == "squaddrop" and len(parts) > 2:
        _drop_squad(parts[2])
    elif cmd == "addback" and len(parts) > 2:
        _add_back(parts[2])
    elif cmd == "knockmute" and len(parts) > 2:
        _dismiss_knock(parts[2])
    elif cmd == "knock" and len(parts) > 2:
        _send_knock(parts[2])
    elif cmd == "cheerback" and len(parts) > 3:
        uid, emoji = parts[2], parts[3]
        entry = next((e for e in (_state["entries"] or [])
                      if e["user_id"] == uid), None)
        if entry and emoji in CHEER_EMOJI:
            _send_cheer(uid, entry["name"], emoji)
    else:
        print(f"due crew: unknown command {message!r}")
    return (True, None)


def _swap(c):
    """Re-render the board in place from cache. No network, no page reload."""
    if _state["entries"] is None:
        _rerender()
        return
    html_out = board.render(_board_data(), c, _state["ts"],
                            wrap=_wrap_info(), deltas=_deck_deltas(),
                            exam_eve=_exam_eve_info(),
                            rules_stale=client().rules_stale,
                            squad_view=_squad_view(), knocks=_visible_knocks())
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
    dlg = FriendsDialog(mw, client(),
                        muted=list(_wrap_data().get("muted_knocks") or []),
                        on_mute=_mute_knocker)
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
                         open_auth, open_friends, _on_signed_out, open_decks,
                         open_squads)
    dlg.exec()


SHARE_KEYS = ("share_reviews", "share_time", "share_retention", "share_streak",
              "share_heatmap", "paused", "exam_date",
              "away_from", "away_to")


def _on_settings_saved(changed):
    """`changed` holds only the keys the dialog owns — never a stale
    snapshot of the whole config."""
    c = cfg()
    push = any(k in changed and changed[k] != c.get(k) for k in SHARE_KEYS)
    c.update(changed)
    save_cfg(c)
    _rerender()
    if push:
        # sharing choices apply now, not at whenever the next sync happens
        _on_sync_done()


def _on_signed_out():
    _reset_runtime()
    _rerender()


def _on_profile_open():
    global _menu_done
    if not _menu_done:
        _menu_done = True
        action = QAction("Due Crew…", mw)
        action.triggered.connect(open_settings)
        mw.form.menuTools.addAction(action)
        mw.addonManager.setConfigAction(__name__, open_settings)
    _reset_runtime()          # profile switch: nothing carries over
    client()                  # rebind to this profile's session
    _migrate_server_json()    # v1.x crew-server config, if any
    refresh_board()


gui_hooks.deck_browser_will_render_content.append(_on_render)


gui_hooks.deck_browser_did_render.append(_on_did_render)


gui_hooks.sync_did_finish.append(_on_sync_done)


gui_hooks.webview_did_receive_js_message.append(_on_js)


gui_hooks.profile_did_open.append(_on_profile_open)

# the modules that need a redraw or a refresh reach it through app
app.swap = _swap
app.rerender = _rerender
app.refresh = refresh_board
app.sync = _on_sync_done
