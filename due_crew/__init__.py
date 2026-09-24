"""Due Crew — your friends' studying next to yours, on the Decks screen.

Threading rules: collection access, config writes, and ALL cache commits
happen on the main thread; HTTP happens in background threads with timeouts.
Workers fetch and hand the result to _commit via run_on_main, so the main
thread is the only writer of shared state and renders never see torn data.

Anki profiles share the add-on folder, so session/streak files live under
user_files/<profile>/ and all runtime state resets on profile switch.

Document-read budget: a friend on 2.9+ is one read per refresh (their week
doc); an older client's week is read once per day and on Refresh, and only
the doc they are writing now otherwise. Profiles ride the day's first fetch,
knocks that or an hourly one.
"""

import datetime
import html
import json
import threading
import time
import traceback

from aqt import gui_hooks, mw
from aqt.deckbrowser import DeckBrowser
from aqt.qt import QAction, QTimer
from aqt.utils import tooltip

from . import app, board
from .app import (_bg, ADDON_VERSION, FRESH_SECS, HEATMAP_DAYS, KNOCK_SECS, SQUAD_CACHE_SECS,
                  STALE_SECS, STREAK_MILESTONES,
                  _migrate_server_json,
                  _pending_cheers, _profile_files, _reset_runtime, _state, cfg, client,
                  save_cfg)
from .backend.firebase import TransportError
from .shares import _share, dismiss_review, review_banners
from .backend.firebase import _clean_day, clean_emoji, shared_numbers
from .social import (_cheer_menu, _edit_emoji, _edit_status, _fresh_cheers, _open_profile,
                     _play_cheers, _send_cheer, cheer_allowed)
from .squads import (_add_back, _block_member, _copy_invite, _dismiss_knock, _drop_squad,
                     _fetch_squad, _kick_member, _leave_squad, _make_founder, _my_squads,
                     _open_squad_card, _select_squad, _send_knock, _share_squad, _squad_view,
                     _toggle_squad_lock, _visible_knocks, open_squads)
from .stats import gather_stats, gather_week, week_days
from .stats import heatmap as cached_heatmap
from .stats.decks import gather_shared_decks
from .stats.queries import StatsQueries
from .ui import copy_text
from .wrap import (_deck_deltas, _exam_eve_info, _mute_knocker, _save_wrap, _update_returns,
                   _update_wrap, _wrap_data, _wrap_info)

_lock = threading.Lock()
_fetching = False
_menu_done = False
_last_attempt = 0.0   # when a push was last STARTED, success or not
_closing = False      # profile_will_close: uploads still go, fetches don't

def _board_data():
    return {"entries": _state["entries"], "labels": _state["labels"],
            "tomorrow": _state["tomorrow"], "pending": _state["pending"],
            "my_code": _state["my_code"]}


def _wants_fetch(uploading, have_board, age, closing, fetch=None):
    """Whether a refresh reads the board after its uploads. A pure fetch
    always does. After an upload the board is read again only when it is
    older than FRESH_SECS: opening Anki used to read it three times inside a
    minute (the open, the push, Anki's own sync). Never while Anki is
    closing — the upload matters, a board nobody will see doesn't."""
    if closing:
        return False
    if fetch is not None:
        return fetch
    return (not uploading) or (not have_board) or age > FRESH_SECS


def _open_push_due(now, last_attempt):
    """The push a few seconds after opening goes unless something already
    pushed. In 2.5.1 it asked whether the BOARD was stale, and the open's own
    fetch had just made it fresh, so online it never went at all."""
    return now - last_attempt > STALE_SECS


def _clock():
    """My clock, for the profile: minutes east of UTC and the hour the day
    rolls over. A friend's client uses it to tell which day label I'm on
    and skip reading the docs I can't have written yet."""
    try:
        roll = datetime.datetime.fromtimestamp(mw.col.sched.day_cutoff).hour
    except Exception:
        roll = 4
    tz = int(datetime.datetime.now().astimezone().utcoffset().total_seconds() // 60)
    return {"tz": tz, "rollover": roll}


def _after_push(pushed, labels, gone=()):
    """Main thread. An upload that skipped the fetch: my own row follows
    what was just written, and the footer learns whether it went."""
    _state["sync_error"] = not pushed
    cl = client()
    own = (cl.session.get("own_days") or {}).get(labels[0])
    if own and _state["entries"]:
        days = _state["days"].setdefault(cl.user_id, {})
        days[labels[0]] = _clean_day(own)
        for e in _state["entries"]:
            if e["user_id"] == cl.user_id:
                e["days"] = days
    for sid in gone or ():
        name = next((sq.get("name") for sq in _my_squads() if sq["id"] == sid), None)
        _drop_squad(sid, swap=False)
        tooltip(f"You're no longer in {html.escape(name or 'a squad')}.")
    if _state["board_shown"] and mw.state == "deckBrowser":
        _swap(cfg())


def refresh_board(upload_stats=None, backfill=None, shared_decks=None,
                  heatmap=None, squad_row=None, full=False, fetch=None):
    """Fetch (and optionally upload first) in the background. Main thread
    only. An upload is never dropped: only pure fetches dedup against an
    in-flight refresh. heatmap: dict to upload, "off" to retract, None to
    leave alone. backfill: last week's studied days, hash-guarded so the
    steady state stays one daily write per sync. fetch: read the board
    after the uploads (None: see _wants_fetch)."""
    global _fetching
    if not mw.col or not client().signed_in or client().session_dead:
        return  # a refused token can't be retried into working
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
        squads = [sq["id"] for sq in _my_squads(c)]
        # shared-deck docs ride along once a day (the week's baseline, the
        # profile card, and the Shared Decks dialog read them); after that
        # the Decks tab fetches its own when someone actually looks. They
        # used to ride EVERY full fetch, a read per person per Refresh.
        with_decks = full and _state["decks_day"] != labels[0]
        # knocks are rare: the day's first fetch and Refresh read them, and
        # otherwise an hourly one does. They were a read on every refresh.
        with_knocks = full or time.time() - _state["knocks_ts"] > KNOCK_SECS
        fetch = _wants_fetch(uploading, _state["entries"] is not None,
                             time.time() - _state["ts"], _closing, fetch)
        clock = _clock()
        own_days = None if c.get("paused") else dict(cl.session.get("own_days") or {})
    except Exception:
        with _lock:
            _fetching = False
        traceback.print_exc()
        return
    if not uploading and not fetch:
        with _lock:
            _fetching = False
        return

    def job():
        global _fetching
        try:
            pushed = True
            if upload_stats is not None:
                pushed = cl.upload_today(uid, name, labels[0], upload_stats, c,
                                         version=ADDON_VERSION, clock=clock)
            if backfill is not None:
                cl.upload_backfill(uid, backfill, c, labels=labels)
            if upload_stats is not None or backfill is not None:
                # 2.9: my week in one doc, from what was just uploaded
                pushed = cl.upload_week(uid, labels, c) and pushed
            if shared_decks is not None and not c.get("paused"):
                cl.upload_shared(uid, shared_decks)
            if heatmap is not None:
                if isinstance(heatmap, dict) and not c.get("paused"):
                    cl.upload_heatmap(uid, heatmap)
                elif not cl.session.get("heatmap_deleted"):
                    cl.delete_heatmap(uid)  # share turned off, or paused
            gone = []
            if squad_row is not None and squads and not c.get("paused"):
                srow = dict(squad_row)
                srow.setdefault("day", labels[0])
                # a show-up row carries the day it last studied, or none
                srow = {k: v for k, v in srow.items() if v is not None}
                gone = cl.upload_squad_rows(uid, srow, squads)
            cl.check_rules(labels[0])  # cached: one real request per day
            if not fetch:
                mw.taskman.run_on_main(lambda: _after_push(pushed, labels, gone))
                return
            # knocks don't depend on the board, so they go alongside it
            box = {}

            def _knocks():
                try:
                    box["knocks"] = cl.list_knocks(uid)  # one list request
                except Exception:
                    box["knocks"] = None

            side = threading.Thread(target=_knocks, daemon=True)
            if with_knocks:
                side.start()
            data = cl.fetch_board(uid, labels, tomorrow=tomorrow,
                                  include_shared=with_decks, check_edges=full,
                                  light=not full, own_days=own_days,
                                  cached_people=not full)
            if with_knocks:
                side.join(25)
            knocks = box.get("knocks")
            failed = not pushed
            mw.taskman.run_on_main(
                lambda: _commit(data, c, labels, tomorrow, knocks, gone, failed))
        except TransportError:
            # expected when offline or flaky — stderr raises Anki's error
            # dialog, so this stays off that channel; the cache is untouched
            # and the footer now SAYS the sync failed instead of just aging
            print("due crew: refresh failed (network); keeping the cached board")
            mw.taskman.run_on_main(_sync_failed)
        except Exception:
            traceback.print_exc()  # cache stays untouched on failure
        finally:
            with _lock:
                _fetching = False

    threading.Thread(target=job, daemon=True).start()


def _sync_failed():
    """Main thread. Either the network is down (footer: Couldn't sync) or the
    server refused my sign-in for good (the card asks me back in)."""
    _state["sync_error"] = True
    if client().session_dead:
        _state["board_shown"] = False
        _rerender()
    elif _state["board_shown"] and mw.state == "deckBrowser":
        _swap(cfg())


def _is_stale(now, fetched_at, last_attempt, limit=STALE_SECS):
    """Refresh when the board is old AND we haven't just tried. The second
    half matters offline: without it every redraw would fire a request."""
    return now - fetched_at > limit and now - last_attempt > limit


def _push_if_stale():
    """Uploads used to ride Anki's sync hook alone, so anyone who studied and
    closed Anki without syncing shared nothing. Now opening Anki, and coming
    back to a stale deck screen, push too. Hash guards keep an unchanged day
    at zero writes; the fetch is capped by STALE_SECS."""
    global _last_attempt
    if not mw.col or not client().signed_in or client().session_dead:
        return
    now = time.time()
    if not _is_stale(now, _state["ts"], _last_attempt):
        return
    _last_attempt = now  # claim it now: a second redraw must not double up
    QTimer.singleShot(0, lambda: _on_sync_done(light=True))  # after this paint


def _fetch_decks(force=False):
    """The Decks tab's own fetch: fresh numbers when someone looks, cached a
    few minutes. One batchGet, a read per person."""
    entries = _state["entries"]
    if not entries or not mw.col or not client().signed_in or client().session_dead:
        return
    if not force and time.time() - _state["decks_ts"] < SQUAD_CACHE_SECS:
        return
    _state["decks_ts"] = time.time()
    cl = client()
    uids = [e["user_id"] for e in entries]

    def done(decks):
        if not decks:
            return
        for e in _state["entries"] or []:
            if e["user_id"] in decks:
                e["decks"] = decks[e["user_id"]]
                _state["decks"][e["user_id"]] = decks[e["user_id"]]
        if cfg().get("period") == "decks":
            _swap(cfg())

    _bg(lambda: cl.fetch_decks(uids), done)


def _copy_friend_invite():
    """The solo board's Copy invite. Accounts made since 2.9 have a code from
    sign-up; an older one that never opened Friends gets one made here, and
    the invite is copied when it lands (until 2.9 this opened Friends)."""
    from .share import friend_invite
    if _state["my_code"]:
        copy_text(friend_invite(_state["my_code"]))
        tooltip("Invite copied.")
        return
    cl = client()
    uid = cl.user_id

    def done(code):
        if not code:
            tooltip("Couldn't make your code. Check your connection.")
            return
        _state["my_code"] = code
        copy_text(friend_invite(code))
        tooltip("Invite copied.")
        _swap(cfg())

    _bg(lambda: cl.ensure_friend_code(uid, (cl.get_doc(f"users/{uid}")[0] or {}).get("friendCode")),
        done)


def _commit(data, c, labels, tomorrow, knocks=None, gone=(), failed=False):
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
            _state["decks_day"] = labels[0]
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
                toasts.append(f"{html.escape(e['name'])} just studied" + (
                    "" if c.get("show_up") else f" — {counts[e['user_id']]:,} reviews today"))
    for e in data["entries"]:
        if e["you"]:
            continue
        doc = e["days"].get(tomorrow) or e["days"].get(today)
        streak_val = (doc or {}).get("streak")
        if isinstance(streak_val, int):
            old = _state["prev_streaks"].get(e["user_id"])
            if isinstance(old, int) and c.get("sync_notifications", True) and not c.get("show_up"):
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
        _state["knocks_ts"] = time.time()
    for sid in gone or ():
        name = next((sq.get("name") for sq in _my_squads() if sq["id"] == sid), None)
        _drop_squad(sid, swap=False)
        tooltip(f"You're no longer in {html.escape(name or 'a squad')}.")

    _state.update(entries=data["entries"], labels=labels, tomorrow=tomorrow,
                  pending=data["pending"], ts=time.time(), sync_error=bool(failed),
                  my_code=str(data.get("my_code") or _state["my_code"]),
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
        if not client().signed_in or client().session_dead:
            _state["board_shown"] = False
            content.stats += board.signed_out_card(c, expired=client().session_dead)
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
                                          squad_view=_squad_view(c), knocks=_visible_knocks(c),
                                          reviews=review_banners(),
                                          sync_error=_state["sync_error"])
            _push_if_stale()
    except Exception:
        traceback.print_exc()


def _on_did_render(deck_browser):
    mw.web.eval(board.keep_me_in_view_js())
    _play_cheers()


def _last_studied(q, stats):
    """The most recent day label with answers in the last week: today when
    today has any, else the newest such day, else None. Main thread."""
    if int(stats.reviews or 0) > 0:
        return q.day_label(0)
    try:
        studied = [lb for lb, t in q.daily_totals(7).items() if t and t[0]]
    except Exception:
        traceback.print_exc()
        return None
    return max(studied) if studied else None


def _on_sync_done(full=False, light=False, fetch=None):
    """Upload everything that changed, then fetch. Anki's sync hook and the
    board's Refresh both land here, so Refresh never leaves your own row
    behind; Refresh asks for the full week. light: the automatic pushes
    (on open, on a stale board) send today's numbers only — decks, heatmap,
    and backfill move slowly and cost main-thread SQL, so they wait for a
    real sync or a Refresh."""
    global _last_attempt
    if not mw.col or not client().signed_in:
        return
    _last_attempt = time.time()
    c = cfg()
    # independent try blocks: one gatherer failing must not silently stop
    # the others from uploading (that failure mode is invisible in the UI)
    stats = week = decks = heat = None
    try:
        stats = gather_stats(mw.col, _profile_files())
    except Exception:
        traceback.print_exc()
    if not light:
        try:
            week = gather_week(mw.col, _profile_files())
        except Exception:
            traceback.print_exc()
        try:
            decks = gather_shared_decks(mw.col, c)
        except Exception:
            traceback.print_exc()
        try:
            heat = (cached_heatmap(StatsQueries(mw.col), _profile_files(), HEATMAP_DAYS)
                    if c.get("share_heatmap", True) else "off")
        except Exception:
            traceback.print_exc()
    row = None
    if stats is not None:
        row = {"name": client().display_name or "Me"}
        if c.get("show_up"):
            # just show up: no numbers, and the row is dated by the last day I
            # studied, so "today" on a squad board means I studied today
            row["day"] = _last_studied(StatsQueries(mw.col), stats)
        else:
            # the Privacy switches, as on the day docs: until 2.9 a squad got
            # all four numbers whatever the switches said
            row.update(shared_numbers({
                "reviews": int(stats.reviews), "studyTimeMs": int(stats.time_ms),
                "streak": int(stats.streak),
                "accuracy": None if stats.accuracy is None else float(stats.accuracy)}, c))
        try:
            row["week"] = week_days(StatsQueries(mw.col))
        except Exception:
            traceback.print_exc()
        emoji = clean_emoji(c.get("emoji"))
        if emoji:
            row["emoji"] = emoji
    refresh_board(upload_stats=stats, backfill=week, shared_decks=decks,
                  heatmap=heat, squad_row=row, full=full, fetch=fetch)


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
        elif parts[2] == "decks":
            _fetch_decks()
    elif cmd == "refresh":
        _on_sync_done(full=True, fetch=True)  # push my own numbers too, then fetch the week
        if c.get("period") == "squads":
            _fetch_squad(force=True)
        elif c.get("period") == "decks":
            _fetch_decks(force=True)
    elif cmd == "friends":
        open_friends()
    elif cmd == "copyinvite":
        _copy_friend_invite()
    elif cmd == "addcode":
        open_friends(focus_add=True)
    elif cmd == "decks":
        open_decks()
    elif cmd == "setup":
        open_auth(join=(parts[2] == "join") if len(parts) > 2 else None)
    elif cmd == "cheerpick" and len(parts) > 2:
        _cheer_menu(parts[2])
    elif cmd == "status":
        _edit_status()
    elif cmd == "emoji":
        _edit_emoji()
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
    elif cmd in ("sharetoday", "shareweek", "sharecrewweek", "sharemonth", "shareyear",
                 "monthcopy", "yearcopy"):
        _share(cmd)
    elif cmd in ("monthdismiss", "yeardismiss"):
        dismiss_review(cmd[:-7])
        _swap(c)
    elif cmd == "wrapcopy":
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
    elif cmd == "settings":
        open_settings(tab=parts[2] if len(parts) > 2 else None)
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
    elif cmd == "squadblock" and len(parts) > 2:
        _block_member(parts[2])
    elif cmd == "squadfounder" and len(parts) > 2:
        _make_founder(parts[2])
    elif cmd == "squadshare":
        _share_squad()
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
        emoji = cheer_allowed(emoji, client().rules_stale)
        if entry and emoji:
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
                            squad_view=_squad_view(c), knocks=_visible_knocks(c),
                            reviews=review_banners(), sync_error=_state["sync_error"])
    js = """
    (function() {
        var el = document.getElementById('due-crew');
        if (!el) { return; }
        var tmp = document.createElement('div');
        tmp.innerHTML = %s;
        el.parentNode.replaceChild(tmp.firstElementChild, el);
    })();
    """ % json.dumps(html_out) + board.keep_me_in_view_js()
    mw.web.eval(js)


def open_auth(join=None):
    """join: open the dialog on Join (True) or Sign In (False); None lets it
    choose. A new account gets the welcome screen before its first upload,
    so what the crew will see is said before any of it is shared."""
    from .ui.auth_dialog import AuthDialog
    dlg = AuthDialog(mw, client(), join=join)
    if dlg.exec() and dlg.user:
        _uid, name = dlg.user
        _reset_runtime()
        if dlg.joined:
            _welcome()
        else:
            tooltip(f"Welcome back, {html.escape(name)}.")
        _on_sync_done()
        _rerender()


def _welcome():
    from .ui.welcome_dialog import WelcomeDialog
    dlg = WelcomeDialog(mw, client(), cfg(), open_squads)
    if dlg.exec() and dlg.offered:
        c = cfg()
        if bool(c.get("show_up")) != dlg.show_up:
            c["show_up"] = dlg.show_up
            save_cfg(c)


def open_friends(focus_add=False):
    if not client().signed_in:
        open_auth()
        return
    from .ui.friends_dialog import FriendsDialog
    dlg = FriendsDialog(mw, client(),
                        muted=list(_wrap_data().get("muted_knocks") or []),
                        on_mute=_mute_knocker, focus_add=focus_add)
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


def open_settings(tab=None):
    """tab: "you", "board", or "privacy" (your card's Privacy… opens that
    one; until 2.9 it landed on Account)."""
    from .ui.settings_dialog import SettingsDialog
    dlg = SettingsDialog(mw, client(), cfg(), _on_settings_saved,
                         open_auth, open_friends, _on_signed_out, open_decks,
                         open_squads, edit_emoji=_edit_emoji, edit_status=_edit_status,
                         tab=tab)
    dlg.exec()


SHARE_KEYS = ("show_up", "share_reviews", "share_time", "share_retention", "share_streak",
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
    global _menu_done, _closing, _last_attempt
    if not _menu_done:
        _menu_done = True
        action = QAction("Due Crew…", mw)
        action.triggered.connect(open_settings)
        mw.form.menuTools.addAction(action)
        mw.addonManager.setConfigAction(__name__, open_settings)
    _reset_runtime()          # profile switch: nothing carries over
    _closing = False
    _last_attempt = 0.0
    client()                  # rebind to this profile's session
    _migrate_server_json()    # v1.x crew-server config, if any
    refresh_board()           # the board, right away
    # ...and my own numbers a few seconds later, unless Anki's own sync got
    # there first (it pushes on finish, and it may have pulled phone reviews)
    QTimer.singleShot(8000, _push_on_open)


def _push_on_open():
    global _last_attempt
    if not mw.col or not client().signed_in or client().session_dead:
        return
    if not _open_push_due(time.time(), _last_attempt):
        return
    _last_attempt = time.time()
    _on_sync_done(light=True, fetch=False)  # the open just drew the board


def _on_profile_close():
    global _closing
    _closing = True


gui_hooks.deck_browser_will_render_content.append(_on_render)


gui_hooks.deck_browser_did_render.append(_on_did_render)


gui_hooks.sync_did_finish.append(_on_sync_done)


gui_hooks.webview_did_receive_js_message.append(_on_js)


gui_hooks.profile_did_open.append(_on_profile_open)


gui_hooks.profile_will_close.append(_on_profile_close)

# the modules that need a redraw or a refresh reach it through app
app.swap = _swap
app.rerender = _rerender
app.refresh = refresh_board
app.sync = _on_sync_done
