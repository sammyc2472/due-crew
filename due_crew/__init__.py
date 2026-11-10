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
"""

import datetime
import html
import re
import sys
import threading
import time

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

_lock = threading.Lock()
_fetching = False
_menu_done = False
_last_attempt = 0.0   # when a push was last STARTED, success or not
_closing = False      # profile_will_close: uploads still go, fetches don't
_pushed = None        # 3.9.1: (col.mod, my day, my config) as the last push gathered them

def _board_data():
    return {"entries": _state["entries"], "labels": _state["labels"],
            "tomorrow": _state["tomorrow"], "pending": _state["pending"],
            "my_code": _state["my_code"], "held": held_uids()}  # 3.9.9: cheers waiting to send


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
    rolls over (the phone check-in and the site will want it)."""
    try:
        roll = datetime.datetime.fromtimestamp(mw.col.sched.day_cutoff).hour
    except Exception:
        roll = 4
    tz = int(datetime.datetime.now().astimezone().utcoffset().total_seconds() // 60)
    return {"tz": tz, "rollover": roll}


def _current(gen):
    """Whether a background job started under `gen` may still commit: no
    profile switch, sign-in or sign-out since."""
    return gen == app.generation


def _morning(awaiting_sync, **kw):
    """3.1: the plans' morning, never while Anki is closing (the close's
    own AnkiWeb sync lands after profile_will_close)."""
    if _closing:
        return None
    return plan_flow.maybe_morning(awaiting_sync, **kw)


def _morning_now(waiting):
    """3.8.0, on the Decks screen: the morning that waited for it, then the
    board redrawn with what it opened."""
    if _state.get("plans_morning") is not waiting:
        return  # ran already, or a newer one is waiting
    _state["plans_morning"] = None
    _morning(bool(waiting.get("awaiting")) and _awaiting_phone(), fresh=bool(waiting.get("fresh")))
    if _state["board_shown"] and mw.state == "deckBrowser":
        _swap(cfg())


def _after_push(pushed, labels, gone=(), gen=None):
    """Main thread. An upload that skipped the fetch: my own row follows
    what was just written, and the footer learns whether it went."""
    if gen is not None and not _current(gen):
        return
    _state["sync_error"] = not pushed
    _state["offline"] = False  # 3.9.9: it got an answer, whatever the answer was
    if not _closing:
        send_held(labels[0])  # cheers that waited for Due Crew to be reachable
    cl = client()
    own = cl.my_days(cfg(), labels[0]).get(labels[0])
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
                  heatmap=None, squad_row=None, full=False, fetch=None, plans=None, extras=None):
    """Sync (optionally) and fetch, in the background: one request each.
    Main thread only. An upload is never dropped: only pure fetches dedup
    against an in-flight refresh. heatmap: dict to share, "off" to take it
    down, None to leave alone. backfill: last week's studied days. fetch:
    read the board after the upload (None: see _wants_fetch). plans (3.1):
    progress on the plans I share it on, sent when it changed. extras
    (3.2): {known, stuck, log} for the sync, as cards.for_sync gives them."""
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
        full = (full or _state["entries"] is None or not _state["labels"]
                or _state["labels"][0] != labels[0])
        squads = [sq["id"] for sq in _my_squads(c)]
        # shared decks ride the day's first fetch (the week's baseline, the
        # profile card, and the Shared Decks dialog read them); after that
        # the Decks tab fetches its own when someone actually looks
        with_decks = full and _state["decks_day"] != labels[0]
        fetch = _wants_fetch(uploading, _state["entries"] is not None,
                             time.time() - _state["ts"], _closing, fetch)
        clock = _clock()
        gen = app.generation
    except Exception:
        with _lock:
            _fetching = False
        oops()
        return
    if not uploading and not fetch:
        with _lock:
            _fetching = False
        return

    def job():
        global _fetching
        try:
            pushed, gone = True, []
            if uploading or heatmap is not None or squad_row is not None:
                row = None
                if squad_row is not None:
                    row = dict(squad_row)
                    row.setdefault("day", labels[0])
                    # a show-up row carries the day it last studied, or none
                    row = {k: v for k, v in row.items() if v is not None}
                pushed, gone = cl.push(labels, c, stats=upload_stats, backfill=backfill,
                                       shared_decks=shared_decks, heatmap=heatmap,
                                       squad_row=row, squads=squads,
                                       version=ADDON_VERSION, clock=clock, plans=plans,
                                       **(extras or {}))
            cl.check_version(labels[0], ADDON_VERSION)  # one real request a day
            if not fetch:
                mw.taskman.run_on_main(lambda: _after_push(pushed, labels, gone, gen=gen))
                return
            data = cl.fetch_board(labels, tomorrow=tomorrow, with_decks=with_decks)
            knocks = data["knocks"]
            failed = not pushed
            mw.taskman.run_on_main(
                lambda: _current(gen) and _commit(data, c, labels, tomorrow, knocks, gone, failed))
        except TransportError:
            # expected when offline or flaky — stderr raises Anki's error
            # dialog, so this stays off that channel; the cache is untouched
            # and the footer now SAYS the sync failed instead of just aging
            print("due crew: refresh failed (network); keeping the cached board")
            mw.taskman.run_on_main(lambda: _current(gen) and _sync_failed())
        except Exception:
            oops()  # cache stays untouched on failure
        finally:
            with _lock:
                if _current(gen):  # else the next profile's refresh owns the flag
                    _fetching = False

    threading.Thread(target=job, daemon=True).start()


def _sync_failed():
    """Main thread. Either the network is down (footer: Couldn't sync) or the
    server refused my sign-in for good (the card asks me back in)."""
    _state["sync_error"] = True
    _state["offline"] = not client().session_dead  # 3.9.9: the board says so on top (board.offline_html)
    _morning(_awaiting_phone())  # 3.1: offline, the morning runs from the cached plans
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
    few minutes. One request."""
    entries = _state["entries"]
    if not entries or not mw.col or not client().signed_in or client().session_dead:
        return
    if not force and time.time() - _state["decks_ts"] < SQUAD_CACHE_SECS:
        return
    _state["decks_ts"] = time.time()
    cl = client()

    def done(decks):
        if not decks:
            return
        for e in _state["entries"] or []:
            if e["user_id"] in decks:
                e["decks"] = decks[e["user_id"]]
                _state["decks"][e["user_id"]] = decks[e["user_id"]]
        if cfg().get("period") == "decks":
            _swap(cfg())

    _bg(cl.fetch_decks, done)


def _copy_friend_invite():
    """Copy invite (3.5.0): a one-time link, made now. Offline, the link
    carries my friend code instead (add, then Add back). An account without
    a code yet gets one made here too."""
    from .share import INVITE_COPIED, friend_invite
    cl = client()
    mine = _state["my_code"]

    def job():
        return cl.create_invite(), mine or cl.ensure_friend_code(None)

    def done(result):
        invite, code = result if result else (None, None)
        if not invite and not code:
            tooltip("Couldn't make your invite. Check your connection.")
            return
        copy_text(friend_invite(invite or code))
        tooltip(INVITE_COPIED if invite else "Invite copied.")
        if code and code != _state["my_code"]:
            _state["my_code"] = code
            _swap(cfg())

    _bg(job, done)


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
                        if t >= 100:
                            # 2.10: the big ones get a banner with a one-tap cheer
                            _state["milestones"] = [m for m in _state["milestones"]
                                                    if m[0] != e["user_id"]]
                            _state["milestones"].append((e["user_id"], e["name"], t))
            _state["prev_streaks"][e["user_id"]] = streak_val

    _state["prev_label"] = today
    _state["prev_counts"] = counts

    cl = client()
    # 3.0.1: someone I muted is dropped here, quietly; their tips don't
    # count either, so a flag they tipped comes back with my next sync
    cheers, kept_knocks = drop_muted(data.get("cheers", []),
                                     [tuple(k) for k in knocks or []], muted_uids(c))
    if knocks is not None:
        knocks = kept_knocks
    together.forget_tipped(cheers)  # a tipped flag stays down
    fresh, seen = _fresh_cheers(cheers, cl.session.get("cheers_seen"),
                                cl.session.get("cheers_seen_ts", ""))
    got = data.get("cheers_at") or 0  # 3.7.2: the next refresh says these arrived
    if seen != cl.session.get("cheers_seen") or got != (cl.session.get("cheers_got") or 0):
        cl.session["cheers_seen"] = seen
        cl.session["cheers_got"] = got
        cl.session.pop("cheers_seen_ts", None)
        cl._save_session()
    # 2.10: good-luck lines wait for my exam morning, tips for their card
    today_lb = labels[0]
    my_exam = str(c.get("exam_date") or "")
    fresh, luck, tips = together.route_cheers(fresh, my_exam, today_lb)
    toasts += together.keep(luck, tips, my_exam, today_lb)
    if fresh:
        _pending_cheers.extend(fresh)
        _state["sev_cheer"] = time.time()  # 3.8.1: Pip catches it by the logo, once
        _closet(lambda cf: cf.note_cheered())  # 3.8.2: a crewmate's cheer
        # 3.9.1: a drawing or a sign goes on the fridge, in its sender's colour from this refresh's crew
        # (the bug hunt: _state's is None at launch, and stale for someone just become mutual)
        _closet(lambda cf: cf.keep_doodles(fresh, data["entries"], client().user_id))

    if knocks is not None:
        _state["knocks"] = [tuple(k) for k in knocks]
    _state["notice"] = data.get("notice")  # 3.2.1
    account.saved_elsewhere(data.get("settings_at"))  # 3.7.1
    for sid in gone or ():
        name = next((sq.get("name") for sq in _my_squads() if sq["id"] == sid), None)
        _drop_squad(sid, swap=False)
        tooltip(f"You're no longer in {html.escape(name or 'a squad')}.")
    if data.get("squads") is not None:
        heal_squads(data["squads"], gone)  # 3.6: squads the server has and this config lost

    _state.update(entries=data["entries"], labels=labels, tomorrow=tomorrow,
                  pending=data["pending"], ts=time.time(), sync_error=bool(failed), offline=False,
                  my_code=str(data.get("my_code") or _state["my_code"]),
                  my_friends=list(data.get("my_friends") or []))
    # 3.1: plans ride the day's first refresh; the morning follows it
    opened = _morning(_awaiting_phone(), fresh=bool(data.get("plans_fresh")), toast=False,
                      update=bool(data.get("plans_update")))  # 3.7.3: later in the day, asked
    if opened:
        toasts.append(opened)
    elif data.get("plans"):
        plan_flow.refresh_progress()
    due_flow.after_refresh()  # Due: a fresh reviews count, and the morning's leeches when asked
    _closet(lambda cf: _closet_day(cf, labels[0], data["entries"]))  # 3.8.2: Pip's closet
    toasts += _update_returns(data["entries"], labels, tomorrow, c)
    milestone = _update_wrap(data["entries"], labels)
    if milestone and c.get("sync_notifications", True):
        toasts.append(milestone)

    if toasts:
        tooltip("<br>".join(toasts), period=5000)
    if _state["board_shown"] and mw.state == "deckBrowser":
        _swap(cfg())        # page not rebuilt: safe to play cheers directly
        _play_cheers()
        _joy_show()  # 3.9.6: after the cheers that came with it (it waits for their show)
        together.show_luck_card()  # 3.9.9: a line that came with this refresh, on my exam morning (only a draw showed it)
    elif _board_off(c) and mw.state == "deckBrowser":
        # 3.9.8 (the energy review): the board's off, so a refresh has nothing of ours to draw:
        # Anki's Decks screen isn't built again for it (it was, every refresh); its cheers play over it
        _play_cheers()
        _joy_show()
        together.show_luck_card()
    else:
        _rerender()         # deck_browser_did_render plays queued cheers
    rooms.refresh_widgets()  # 2.12: who's in the room, as of this fetch
    if not _closing:
        send_held(labels[0])  # 3.9.9: cheers that waited for Due Crew to be reachable go now


def _board_off(c):
    """The board turned off in Settings, and none of the screens that show in
    its place open (Settings, the closet, Wrapped)."""
    return (not c.get("show_leaderboard", True) and not _state.get("settings_tab")
            and not _state.get("closet_open") and not _state.get("wrapped_open"))


def _closet(do):
    """3.8.2: tell Pip's closet (closet_flow); never in the way of the board."""
    try:
        from . import closet_flow
        do(closet_flow)
    except Exception:
        oops()


def _closet_day(cf, today, entries):
    """At a refresh: the day's tallies, and anything newly earned."""
    rv = due_flow._reviews() or {}
    cf.note_day(today, entries, int(rv.get("done") or 0) > 0, rv.get("due"))
    cf.check(today)


def _rerender():
    if mw.state == "deckBrowser":
        mw.deckBrowser.refresh()


def _on_render(deck_browser, content):
    app.on_decks_render()
    content.stats += board.key_js()  # 3.9.1: the page's own scripts add the board's key to what they send
    try:
        c = cfg()
        if _state.get("settings_tab"):
            # 3.8.0: Settings shows whatever else is so (signed out, the board off)
            _state["board_shown"] = True
            content.stats += board.settings_html(_settings_view(), c)
            return
        if _state.get("closet_open"):
            _state["board_shown"] = True  # 3.8.2: Pip's closet, as Settings
            content.stats += board.closet_html(_closet_view(), c)
            return
        if _state.get("wrapped_open") and mw.col:
            _state["board_shown"] = True  # 3.9.0: your Wrapped, as the closet
            content.stats += board.wrapped_html(_wrapped_view(), c)
            return
        if not c.get("show_leaderboard", True):
            _state["board_shown"] = False
            return
        if not client().signed_in or client().session_dead:
            _state["board_shown"] = False
            content.stats += board.signed_out_card(c, expired=client().session_dead,
                                                   gone=client().deleted_quiet, sev=rooms.signed_out_sev())
        elif _state["entries"] is None:
            _state["board_shown"] = False
            content.stats += board.loading_card(c)
            refresh_board()
        else:
            _state["board_shown"] = True
            content.stats += _board_html(c)
            _push_if_stale()
    except Exception:
        oops()


def _bingo_view(c):
    sv = _squad_view(c)
    return bingo_flow.view(sv, c) if sv.get("state") == "ok" else None


def _squad_view_with_bingo(c):
    """The Squads tab's view, with this week's card when there is one (3.6).
    3.8.0: the plans' squads are pills too, and one of them may be picked."""
    from . import team_flow
    sv = _squad_view(c)
    if c.get("period") != "squads":
        return sv  # only the Squads tab draws it; a plan's squad reads my collection for its card questions
    ps = team_flow.plan_squads()
    pv = team_flow.squad_view(c, ps)
    if pv:
        return dict(pv, squads=sv.get("squads") or [], plan_squads=ps)
    sv = dict(sv, plan_squads=ps)
    if sv.get("state") == "ok":
        bv = bingo_flow.view(sv, c)
        if bv:
            sv = dict(sv, bingo=bv)
            squares = (bv.get("ev") or {}).get("squares") or []
            _closet(lambda cf: cf.note_bingo(int((bv.get("ev") or {}).get("lines") or 0),
                                             bool(squares) and all(q.get("done") for q in squares),
                                             f'{(bv.get("card") or {}).get("wk")}:{bv.get("squad_id")}'))
            if bingo_flow.new_lines(bv):
                tooltip("BINGO! Your squad just made a line.", period=4000)
    return sv


def _bingo_cmd(cmd):
    """3.6: open the card, go back, copy it for the group chat."""
    c = cfg()
    if cmd == "bingo":
        _state["bingo_open"] = True
        bingo_flow.seen()
        _swap(c)
        _fetch_squad()
    elif cmd == "bingoback":
        _state["bingo_open"] = False
        _swap(c)
    elif cmd == "bingocopy":
        bv = _bingo_view(c)
        if bv:
            from .bingo import share_text
            copy_text(share_text(bv["card"], bv["ev"], bv["squad"]))
            tooltip("Copied.")


def _board_html(c):
    """The board from cache: one call for the first render and every swap."""
    from . import closet_flow
    if _state.get("settings_tab"):
        return board.settings_html(_settings_view(), c)  # 3.5.0: Settings in its place
    if _state.get("closet_open"):
        return board.closet_html(_closet_view(), c)  # 3.8.2: Pip's closet in its place
    if _state.get("wrapped_open"):
        return board.wrapped_html(_wrapped_view(), c)  # 3.9.0: your Wrapped in its place
    if _state.get("team_bingo_open"):
        from . import team_flow  # 3.7.3: a plan team's card in its place
        pid = _state["team_bingo_open"]
        tv = (_state.get("team_view") or {}).get(pid) or {}
        return board.bingo_html(team_flow.bingo_view(pid), c, loading=tv.get("state") == "fetching", team=True)
    if _state.get("bingo_open"):
        return board.bingo_html(_bingo_view(c), c,  # 3.6: the squad's card in its place
                                loading=_squad_view(c).get("state") == "loading" and bool(bingo_flow.card()),
                                people={e.get("user_id"): e for e in _state["entries"] or []})  # 3.8.22: stamps as Pips
    show_up = bool(c.get("show_up"))
    notice = _state.get("notice")
    if notice and notice["id"] in (_wrap_data().get("notices_dismissed") or []):
        notice = None
    due = due_flow.view(c)  # Due: the day's to-do, on top
    plans = plan_flow.board_view(c)  # 3.3: the plans I follow (3.8.0: You › Plans; offers on Squads too)
    _state["dance_view"] = _dance_view(c)  # 3.9.6: song of the moment's dance floor (seen once it's on the page)
    return board.render(_board_data(), c, _state["ts"], notice=notice,
                        wrap=_wrap_info(), deltas=_deck_deltas(),
                        exam_eve=_exam_eve_info(),
                        rules_stale=client().rules_stale,
                        squad_view=_squad_view_with_bingo(c), knocks=_visible_knocks(c),
                        reviews=review_banners(), sync_error=_state["sync_error"], offline=bool(_state.get("offline")),
                        live=together.is_live(),
                        tricky=together.tricky_view() if c.get("period") == "decks" else None,
                        asks=together.my_asks_view() if c.get("period") == "decks" else None,
                        milestones=None if show_up else _state["milestones"],
                        milestone_sev=None if show_up else rooms.milestone_sevs(_state["milestones"][:2]),
                        room=rooms.board_view(), plans=plans,
                        due=due, you=_you(c, due, plans), sticking=_sticking(c),
                        sev=rooms.board_sev(c, due), closet=_state.get("closet_new"),
                        halloween=closet_flow.halloween_view(_state["labels"][0] if _state["labels"] else "",
                                                             _state["entries"], c),
                        wrapped=_wrapped_banner(c), ahead=ahead_flow.board_line(c),
                        fridge=closet_flow.fridge(client().user_id),
                        fridge_gone=closet_flow.gone(), dance=_state["dance_view"])


def _dance_view(c):
    """3.9.6: the dance floor's view (song_flow.floor_view), or None; never in the way of the board."""
    try:
        from . import song_flow
        return song_flow.floor_view(_state["entries"], c)
    except Exception:
        oops()
        return None


def _dance_seen():
    """3.9.6: the floor just drawn is on the page: what it showed is seen, so a new song hops in once."""
    view = _state.pop("dance_view", None)
    if view:
        try:
            from . import song_flow
            song_flow.mark_seen(view)
        except Exception:
            oops()


def _calm_check(c, plans):
    """3.9.9, the calm board: the parts that now have something to show are
    let out, with the board's line. From what's at hand; never raises."""
    from . import calm
    if not calm.on(c) or not calm.held(c):
        return
    try:
        entries = [e for e in (_state.get("entries") or []) if not e.get("me")]
        days = _state.get("calm_days")
        if (days is None or days[0] != errs.today()) and mw.col:
            first = mw.col.db.scalar("SELECT min(id) FROM revlog WHERE ease > 0")
            days = _state["calm_days"] = (errs.today(), None if not first else int((time.time() - int(first) / 1000) // 86400))
        facts = {"friends": len(entries), "squads": len(c.get("squads") or []),
                 "plans": len(plans or []) if isinstance(plans, (list, tuple)) else int(bool(plans)),
                 "days": days[1] if days else None}
        if calm.release(c, calm.ready(facts), news=True):
            save_cfg(c)
    except Exception:
        oops()


def _calm_cmd(c, parts):
    """The calm board's line and Show all."""
    from . import calm
    cmd, arg = parts[1], parts[2] if len(parts) > 2 else ""
    if cmd == "calmall":
        calm.show_all(c)
        save_cfg(c)
        _swap(c)
    elif cmd == "calmx":
        if calm.seen(c):
            save_cfg(c)
        _swap(c)
    elif cmd == "calmopen":
        calm.seen(c, arg)
        save_cfg(c)
        if arg in ("squads", "decks"):
            _cmd_period(c, ["duecrew", "period", arg])
        else:
            due_flow.on_message("duetab", ["duecrew", "duetab", arg])


def _you(c, due, plans):
    """3.8.0, the You bubble over the board: its tab, folded or not, and the
    Plans or Insights it draws. Only the one on screen is worked out."""
    from . import team_flow
    _calm_check(c, plans)
    hidden = board.hidden_tabs(c)
    you = {"tab": due_flow.you_tab(c), "folded": due_flow.folded(c, due), "plans": plans, "insights": None,
           "party_on": "party" not in hidden and gamenight_flow.shown()}  # 3.9.5: You › Pip Party, unless hidden in Settings
    if you["folded"]:
        return you
    keys = ((["today", "upcoming", "later"] if due else []) + [k for k, _l in board.YOU_MORE if k not in hidden]
            + ([board.PARTY_TAB[0]] if you["party_on"] else []))
    shown = you["tab"] if you["tab"] in keys else (keys[0] if keys else None)
    if shown:
        errs.used(shown if shown in ("plans", "insights", "party") else "due")  # 3.9.9: the tab on screen, once a day
    try:
        if shown == "plans":
            team_flow.plan_lines(plans.get("cards"))  # the next exam's cards at risk, a line a plan
            plan_flow.joy_claim(plans.get("cards"), c)  # 3.9.6: what's waiting to play on the plan shown plays now, once
            if not due and mw.col:
                you["opened"] = plan_flow.morning_opened()  # Due off: its Not today is here
        elif shown == "insights":
            you["insights"] = team_flow.you_view(c)
        elif shown == "party" and mw.col:
            you["party"] = gamenight_flow.tab_view(c)
    except Exception:
        oops()
    return you


def _sticking(c):
    """3.8.0, Crew › Decks: {name: deck id} of the decks I share, for their
    way to how they're sticking (You › Insights). Main thread."""
    if c.get("period") != "decks" or not mw.col:
        return None
    out = {}
    for did in c.get("shared_decks") or []:
        try:
            if mw.col.decks.get(int(did), default=False):
                out[str(mw.col.decks.name(int(did))).split("::")[-1]] = int(did)
        except Exception:
            continue
    return out


def _arrive_js():
    """3.8.0 (Board in Motion, 22): a friend arrives, said to the page once."""
    try:
        new = _arrivals(_state.get("entries"), client().user_id)
    except Exception:
        oops()
        return ""
    return "try{window.dcMotion&&dcMotion.arrive(%s);}catch(e){}" % board._json.dumps(new) if new else ""


# 3.9.1 (the efficiency run): the page the board's scripts last went to
# (app.pages). A page keeps them (motion.js, Due's add line, Find, the
# fridge's), and each loads once, so a swap on that page sends only what
# they do after a draw (it sent 77 KB of them at every click); a page drawn
# anew gets them all.
_SCRIPTS = {"page": None, "css": None}  # 3.9.7: and the board stylesheet that page holds (board.swap_js)


def _board_js(drawn=False):
    """(keep_me_in_view_js, fridge_js) for this draw: with the scripts when
    the page was just drawn (drawn) or is another since they went. 3.9.6:
    fridge_js brings the dance floor's (dance_js) with it."""
    whole = drawn or _SCRIPTS["page"] != app.pages[0]
    _SCRIPTS["page"] = app.pages[0]
    if whole:
        _SCRIPTS["css"] = None  # 3.9.7: a page drawn anew holds no board stylesheet of its own (#dc-css) yet
    return board.keep_me_in_view_js(scripts=whole), board.fridge_js(scripts=whole)


def _on_did_render(deck_browser):
    keep, fridge = _board_js(drawn=True)
    mw.web.eval("window.dcBK=%s;" % board._json.dumps(board.BOARD_KEY)  # 3.9.1: as the page's own script set it
                + keep + _arrive_js() + (board.wrapped_js() if _state.get("wrapped_open") else "")
                + fridge)  # 3.9.1: the doodles placed around the board, and draggable (3.9.6: and the dance floor)
    _dance_seen()
    _play_cheers()
    _joy_show()
    if _state.get("plans_midday") and not _closing:
        # 3.7.3: an update that came while reviewing waits for the Decks screen
        from aqt.qt import QTimer
        QTimer.singleShot(0, lambda: plan_flow.midday(plan_flow.followed()))
    waiting = _state.get("plans_morning")
    if waiting and not _closing:
        # 3.8.0: so does the morning (it came while reviewing, or before Decks first drew)
        from aqt.qt import QTimer
        QTimer.singleShot(0, lambda: _morning_now(waiting))
    together.show_luck_card()
    if not _closing:
        from aqt.qt import QTimer
        QTimer.singleShot(1500, ahead_flow.check)  # 3.9.2: once a day, the board's line when reviews climb
        from . import habits_flow
        QTimer.singleShot(2500, habits_flow.check)  # 3.9.5: once a day, How you study (and the Fifteen at 35)
    sheets.redraw()  # 3.9.1: a question that was open goes back up on the page drawn anew
    rooms.refresh_widgets()
    if not _closing and not _state.get("wrapped_open"):
        from aqt.qt import QTimer
        QTimer.singleShot(900, _magic_howto)  # 3.9.7, round 2: Magic search's how-to, once a person


def _magic_howto():
    try:
        if not _closing and app.board_up():
            errs_flow.use_ready()
            magic_flow.show_board_howto()
    except Exception:
        oops()


def _last_studied(q, stats):
    """The most recent day label with answers in the last week: today when
    today has any, else the newest such day, else None. Main thread."""
    if int(stats.reviews or 0) > 0:
        return q.day_label(0)
    try:
        studied = [lb for lb, t in q.daily_totals(7).items() if t and t[0]]
    except Exception:
        oops()
        return None
    return max(studied) if studied else None


def _on_sync_done(full=False, light=False, fetch=None):
    """Upload everything that changed, then fetch. Anki's sync hook and the
    board's Refresh both land here, so Refresh never leaves your own row
    behind; Refresh asks for the full week. light: the automatic pushes
    (on open, on a stale board) send today's numbers only — decks, heatmap,
    and backfill move slowly and cost main-thread SQL, so they wait for a
    real sync or a Refresh."""
    global _last_attempt, _pushed
    if not mw.col or not client().signed_in:
        return
    if not account.ready():
        # 2.13: my settings first, so a new computer never uploads defaults
        # over the account's (its shared decks, its privacy switches)
        account.ensure(lambda: _on_sync_done(full=full, light=light, fetch=fetch))
        return
    _last_attempt = time.time()
    # 3.1: the morning waits for the day's AnkiWeb sync; this may be it
    _morning(_awaiting_phone())
    c = cfg()
    # independent try blocks: one gatherer failing must not silently stop
    # the others from uploading (that failure mode is invisible in the UI)
    stats = week = decks = heat = None
    try:
        stats = gather_stats(mw.col, _profile_files())
        if _awaiting_phone():
            stats.streak = held_streak(stats.streak, client().sent_days(),
                                       StatsQueries(mw.col).day_label(0))
    except Exception:
        oops()
    if not light:
        try:
            week = gather_week(mw.col, _profile_files())
        except Exception:
            oops()
        try:
            # an install that has never had a deck list (and couldn't pull
            # one) doesn't upload an empty one over the account's
            if c.get("shared_decks") or c.get("shared_decks_set"):
                decks = gather_shared_decks(mw.col, c)
        except Exception:
            oops()
        try:
            heat = (cached_heatmap(StatsQueries(mw.col), _profile_files(), HEATMAP_DAYS)
                    if c.get("share_heatmap", True) else "off")
            if isinstance(heat, dict) and c.get("show_up"):
                heat = {lb: 1 for lb, n in heat.items() if n}  # just show up: which days, no counts
        except Exception:
            oops()
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
            if "reviews" in row:
                row["newCards"] = int(stats.new_cards)  # 2.13: under Reviews, never alone
        try:
            row["week"] = week_days(StatsQueries(mw.col))
        except Exception:
            oops()
        emoji = clean_emoji(c.get("emoji"))
        if emoji:
            row["emoji"] = emoji
        play = bingo_flow.for_row(c)  # 3.6: squad bingo, my week's facts
        if play:
            row["play"] = play
    plan_prog = None
    try:
        plan_prog = plan_flow.for_sync()
    except Exception:
        oops()
    extras = None
    try:
        extras = crew_cards.for_sync(c, light=light)  # 3.2: cards I know and I'm stuck on, my log
    except Exception:
        oops()
    try:
        from . import team_flow
        team = team_flow.for_sync(c)  # 3.7.3: showed up today, and my squares, per plan team
        if team:
            extras = dict(extras or {}, team=team)
    except Exception:
        oops()
    try:
        sending = errs_flow.for_sync(c)  # 3.9.9: the days that are over, what went wrong, by code (Privacy's switch)
        if sending:
            extras = dict(extras or {}, **sending)
    except Exception:
        oops()
    _pushed = _push_key() if stats is not None else None
    refresh_board(upload_stats=stats, backfill=week, shared_decks=decks,
                  heatmap=heat, squad_row=row, full=full, fetch=fetch, plans=plan_prog, extras=extras)


def _push_key():
    """What a push's numbers come from: the collection (Anki moves its mod
    with every change, a sync's too), my day and my config."""
    try:
        return (mw.col.mod, StatsQueries(mw.col).day_label(0), cfg())
    except Exception:
        return None


def _on_anki_sync(*_args):
    """Anki's own sync finished: everything that changed goes up
    (_on_sync_done). 3.9.1: the one Anki runs as it closes (after
    profile_will_close) sends today's numbers only, as the pushes on open
    do, and nothing when the collection, my day and my config are as the
    last push that went had them: Anki waits on this before it can quit,
    and the upload's thread may not outlive it. Leaving a room still goes
    (rooms.on_close pushes it itself)."""
    if not _closing:
        _on_sync_done()
    elif _pushed is None or _pushed != _push_key() or _state.get("sync_error"):
        _on_sync_done(light=True)


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
        from .room_model import trusted
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
    from . import native_emoji
    at = [int(v) for v in parts[2:6] if v.isdecimal() and len(v) < 6]
    x, y, w, h = at if len(at) == 4 else (0, 0, 64, 40)
    if not native_emoji.catch(x, y, w, h, lambda e: app.board_eval(native_emoji.picked_js(e)),
                              lambda: app.board_eval("window.dcCheerUnpick && window.dcCheerUnpick();")):
        app.board_eval("window.dcCheerNoNative && window.dcCheerNoNative();")


def _cmd_emoji_picker_off(c, parts):
    from .native_emoji import drop
    drop()  # 3.9.2: the Cheer window closed, or other's box put away there


def _cmd_cheer_send(c, parts):
    from .social import send_from_window
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
    from . import team_flow
    team_flow.on_message(cmd, parts)  # 3.8.0: You › Insights, a deck's


def _song(c, parts):
    from . import song_flow
    song_flow.on_message(parts[1], parts)  # 3.9.6: song of the moment, and its dance floor


def _settings_family(c, parts):
    _settings_cmd(parts[1], parts[2:])  # 3.5.0: Settings in the board; parts[2:] are its values


def _swapping(do):
    """A command that changes the board and draws it again."""
    def run(c, parts):
        do(c, parts)
        _swap(c)
    return run


# Settings' own (`_settings_cmd`)
SETTINGS_CMDS = ("settab", "setclose", "set", "settabs", "setlabel", "setprivacy", "setexam", "setscope",
                 "setaway", "setreset", "setname", "setemoji", "setstatus", "setsquads",
                 "setsignout", "setdelete", "setsignin", "setfeedback")

# families: a command by its first letters, its module knowing the rest
_FAMILIES = (
    ("plan", lambda c, p: plan_flow.on_message(p[1], p)),  # 3.1
    ("due", lambda c, p: due_flow.on_message(p[1], p)),  # Due
    ("ins", lambda c, p: _team(p[1], p)),
    ("closet", lambda c, p: _closet_cmd(p[1], p[2:])),  # 3.8.2: Pip's closet
    ("wrapped", lambda c, p: _wrapped_cmd(p[1], p[2:])),  # 3.9.0: your Wrapped
)

# a command: (how many values after its name, a check on them, what it does with (cfg, parts))
BOARD_CMDS = {
    "usetold": (0, None, lambda c, p: (errs_flow.told(), _swap(cfg()))),  # 3.9.9: the foot's note on what's counted, Got it
    "usesee": (0, None, lambda c, p: (errs_flow.told(), open_settings("privacy"))),  # and its way to the switch
    "calmall": (0, None, _calm_cmd), "calmx": (0, None, _calm_cmd),  # 3.9.9: the calm board (calm.py)
    "calmopen": (1, lambda p: p[2] in ("decks", "squads", "plans", "insights"), _calm_cmd),
    "party": (0, None, lambda c, p: gamenight_flow.on_message(p)),  # 3.9.5's last round: You › Pip Party
    "magic": (0, None, lambda c, p: open_magic()),  # 3.9.7: Magic search, from the You box's head (and Find a setting)
    "css": (0, None, _cmd_css),
    "magichow": (0, None, lambda c, p: magic_flow.howto_said(p)),  # 3.9.7, round 2: its how-to's buttons
    **{k: (0, None, _song) for k in ("songsearch", "songuse", "songclear", "songlisten", "songapp", "songapple",
                                     "dancehide", "danceshow", "dancemotion", "dancefold")},
    "youins": (0, None, lambda c, p: _team(p[1], p)),
    "sort": (1, lambda p: p[2] in board.SORT_KEYS, _cmd_sort),
    **{k: (0, None, lambda c, p: _bingo_cmd(p[1])) for k in ("bingo", "bingoback", "bingocopy")},
    "period": (1, lambda p: p[2] in board.PERIODS, _cmd_period),
    "refresh": (0, None, _cmd_refresh),
    "friends": (0, None, lambda c, p: open_friends()),
    "live": (0, None, lambda c, p: together.toggle_live()),
    "luckline": (1, None, lambda c, p: together.send_luck_line(p[2])),
    "luckthanks": (0, None, lambda c, p: together.luck_thanks()),
    "tricktip": (2, None, lambda c, p: together.send_tip(p[2], p[3])),
    "milestonecheer": (1, None, lambda c, p: together.milestone_cheer(p[2])),
    "milestonex": (1, None, lambda c, p: together.dismiss_milestone(p[2])),
    "unask": (1, lambda p: p[2].isdigit(), lambda c, p: together.unask(int(p[2]))),  # 3.5.0: Take back
    "copyinvite": (0, None, lambda c, p: _copy_friend_invite()),
    "addcode": (0, None, _cmd_addcode),
    "crewmenu": (0, None, lambda c, p: _crew_menu(c)),  # 3.4 review, H5
    "privacypage": (0, None, _cmd_privacy),
    "errsee": (0, None, lambda c, p: errs_flow.see_what_went()),  # 3.9.9: Privacy's See what went
    "sharemenu": (0, None, lambda c, p: _share_menu(c)),  # 3.7.1, H3
    "decks": (0, None, lambda c, p: open_decks()),
    "setup": (0, None, lambda c, p: open_auth()),
    "cheerpick": (1, None, lambda c, p: _cheer_menu(p[2])),
    # 3.9.1: the fridge: a Polaroid moved (no redraw), taken down (an Undo in its place for a few seconds), put back
    "fridgemove": (4, _fridge_spot,
                   lambda c, p: _closet(lambda cf: cf.move_fridge(p[2], p[3], int(p[4][:6]), int(p[5][:5])))),
    "fridgedown": (1, None, _swapping(lambda c, p: _closet(lambda cf: cf.take_down(p[2])))),
    "fridgeback": (1, None, _swapping(lambda c, p: _closet(lambda cf: cf.put_back(p[2])))),
    "emojipicker": (0, None, _cmd_emoji_picker),
    "emojipickeroff": (0, None, _cmd_emoji_picker_off),
    "cheersend": (1, None, _cmd_cheer_send),
    "sheet": (2, None, lambda c, p: sheets.answer(p[2], ":".join(p[3:]))),  # 3.9.1: a sheet's answer
    # 3.9.1: a window over the board; the bars dim with it
    "veil": (1, None, lambda c, p: app.veil(p[2] == "1" and app.board_up())),
    "rowmenu": (1, None, lambda c, p: row_menu(p[2])),  # 3.0.1: right-click a crewmate: mute, report
    "status": (0, None, lambda c, p: _edit_status()),
    "emoji": (0, None, lambda c, p: _edit_emoji()),
    "profile": (1, None, lambda c, p: _open_profile(p[2])),
    "evedismiss": (0, None, lambda c, p: _wrap_put(c, "eve_dismissed",
                                                   lambda w: _state["labels"][0] if _state["labels"] else "")),
    # 3.2.1: the admin's notice, dismissed for good on this profile
    "noticex": (1, lambda p: p[2].isdigit(), lambda c, p: _wrap_put(
        c, "notices_dismissed", lambda w: (list(w.get("notices_dismissed") or []) + [int(p[2])])[-50:])),
    "noticeopen": (0, None, _cmd_notice_open),
    "wrapdismiss": (0, None, lambda c, p: _wrap_put(c, "dismissed", lambda w: w.get("week", ""))),
    **{k: (0, None, lambda c, p: _share(p[1])) for k in ("sharetoday", "shareweek", "sharecrewweek", "sharemonth",
                                                         "shareyear", "monthcopy", "yearcopy")},
    **{k: (0, None, _swapping(lambda c, p: dismiss_review(p[1][:-7]))) for k in ("monthdismiss", "yeardismiss")},
    "wrapcopy": (0, None, _cmd_wrap_copy),
    "settings": (0, None, lambda c, p: open_settings(tab=p[2] if len(p) > 2 else None)),
    "heatday": (1, None, lambda c, p: _browse_day(p[2])),
    **{k: (0, None, _settings_family) for k in SETTINGS_CMDS},
    # 3.9.5: Insights' exam date and its scope, in a Qt calendar
    **{k: (0, None, lambda c, p: _pick_exam_day(p[1])) for k in ("exampick", "scopepick")},
    "ecard": (1, None, lambda c, p: _open_squad_card(p[2])),
    "squad": (1, None, lambda c, p: _select_squad(p[2])),
    "squadplan": (1, None, lambda c, p: _team_squad(p[2])),
    "squadadd": (0, None, lambda c, p: open_squads()),
    "squadinvite": (0, None, lambda c, p: _copy_invite()),
    "squadlock": (0, None, lambda c, p: _toggle_squad_lock()),
    "squadleave": (0, None, lambda c, p: _leave_squad()),
    "squadkick": (1, None, lambda c, p: _kick_member(p[2])),
    "squadblock": (1, None, lambda c, p: _block_member(p[2])),
    "squadfounder": (1, None, lambda c, p: _make_founder(p[2])),
    "squadshare": (0, None, lambda c, p: _share_squad()),
    "squaddrop": (1, None, lambda c, p: _drop_squad(p[2])),
    "addback": (1, None, lambda c, p: _add_back(p[2])),
    "knockmute": (1, None, lambda c, p: _dismiss_knock(p[2])),
    "knock": (1, None, lambda c, p: _send_knock(p[2])),
    "cheerback": (2, None, _cmd_cheer_back),
}


def _team_squad(team_id):
    from . import team_flow
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
    if _state.get("wrapped_open"):
        js += board.wrapped_js()  # 3.9.0: Wrapped's player, on the card just drawn
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


def open_auth():
    """One flow signs in and joins. A new account gets the welcome screen
    before its first upload, so what the crew will see is said before any
    of it is shared."""
    global _fetching
    from .ui.auth_dialog import AuthDialog
    dlg = AuthDialog(mw, client())
    if dlg.exec() and dlg.user:
        _uid, name = dlg.user
        _reset_runtime(keep_sync=True)
        with _lock:
            _fetching = False  # the last session's refresh can't commit now
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
    from .ui.welcome_dialog import WelcomeDialog
    dlg = WelcomeDialog(mw, client(), cfg(), open_squads)
    if dlg.exec() and dlg.offered:
        c = cfg()
        if bool(c.get("show_up")) != dlg.show_up:
            c["show_up"] = dlg.show_up
            save_cfg(c)


def _add_code(code):
    """The day-one card's Add: a friend's code, added now. One request."""
    from .backend.shapes import friend_code_from, invite_code_from, long_code_from
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


def _crew_menu(c):
    """The footer's Crew ▾ (3.4 review, H5): people."""
    from aqt.qt import QCursor, QMenu
    run = {"friends": lambda: open_friends(), "decks": lambda: open_decks(),
           "copyinvite": lambda: _copy_friend_invite()}
    menu = QMenu(mw)
    for label, key in board.crew_menu_items():
        menu.addAction(label).triggered.connect(lambda _=False, k=key: run[k]())
    menu.exec(QCursor.pos())


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
    from .ui.friends_dialog import FriendsDialog
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
    from .ui.decks_dialog import DecksDialog
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


def open_wrapped(year=None):
    """3.9.0: your Wrapped, in place of the board (as the closet is), from
    the board's December line or Tools › Due Crew › Your year…: the year's
    story, made here from your own reviews (wrapped_flow)."""
    if not mw.col:
        return
    from . import wrapped_flow
    try:
        v = wrapped_flow.view(year)
    except Exception:
        oops()
        tooltip("Couldn't read your year just now.")
        return
    _state["wrapped_open"] = {"year": v["year"], "view": v}
    _state["settings_tab"] = None
    _state["closet_open"] = None
    _close_addons_dialog()
    if mw.state != "deckBrowser":
        mw.moveToState("deckBrowser")
    elif _board_on_screen():
        _swap(cfg())
    else:
        _rerender()


def _wrapped_view():
    st = _state.get("wrapped_open") or {}
    return st.get("view") or {"year": st.get("year"), "slides": []}


def _wrapped_banner(c):
    from . import wrapped_flow
    try:
        return wrapped_flow.banner(_state["labels"][0] if _state["labels"] else "", c)
    except Exception:
        oops()
        return None


def _wrapped_cmd(cmd, parts):
    """3.9.0: Wrapped's clicks: open it (the line's Open), another year, the
    picture, the card I turned around on or off, back to the board, and the
    line's x (for the year, on every computer)."""
    arg = parts[0] if parts else ""
    year = int(arg) if arg.isdigit() and len(arg) == 4 else None
    if cmd in ("wrappedopen", "wrappedyear"):
        open_wrapped(year)
        return
    if cmd == "wrappedpic" and year:
        from .shares import picture
        picture("pictureyear", year=year)  # the year card, made here, with Pip on it
        return
    if cmd == "wrappedcard":
        from .wrapped_flow import CARD_KEY
        c = dict(cfg())
        c[CARD_KEY] = not c.get(CARD_KEY, True)
        save_cfg(c)
        st = _state.get("wrapped_open")
        if st:
            open_wrapped(st.get("year"))
        return
    if cmd == "wrappedclose":
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
    from . import closet_flow
    st = _state.get("closet_open") or {}
    c = cfg()
    rest, st["drawn"] = bool(st.get("drawn")), True  # Pip waves when it opens and at a change, then rests
    near, progress = closet_flow.standing(c)
    return {"tab": st.get("tab"), "have": closet_flow.have(c), "look": closet_flow.look(c),
            "near": near, "progress": progress, "new": st.get("new") or [], "msg": st.get("msg") or "", "rest": rest}


def _closet_cmd(cmd, parts):
    """3.8.2: the closet's clicks, and the board line's (Wear it, ×)."""
    from . import closet as cl, closet_flow
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


def _board_on_screen():
    c = cfg()
    return (mw.state == "deckBrowser" and c.get("show_leaderboard", True) and _state["board_shown"]
            and client().signed_in and not client().session_dead)


def _settings_view():
    """What the You tab shows. Main thread (deck names come from the collection)."""
    from .board import _ago
    c, cl = cfg(), client()
    if cl.session_dead:
        state = "Sign-in expired"
    else:
        ago, _tone = _ago(cl.session.get("last_ok", ""))
        state = f"Synced {ago}" if ago else "Not synced yet"
    sync = " · ".join(x for x in (cl.email, state, f"v{ADDON_VERSION}" if ADDON_VERSION else "") if x)
    decks = []
    for did in c.get("shared_decks") or []:
        try:
            decks.append(mw.col.decks.name(int(did)))
        except Exception:
            continue
    crew = sum(1 for e in (_state["entries"] or []) if not e.get("you"))
    return {"tab": _state.get("settings_tab"), "signed_in": cl.signed_in, "name": cl.display_name,
            "emoji": c.get("emoji"), "status": c.get("status"), "sync": sync, "crew": crew,
            "squads": [s.get("name") for s in (c.get("squads") or []) if isinstance(s, dict) and s.get("name")],
            "decks": decks,
            "fsrs": _fsrs_on(),  # 3.9.1: two buttons' note, with FSRS off
            "leech_reach": _leech_reach()}  # 3.9.3: Recover leeches' line, by this profile's answer


def _leech_reach():
    """This profile's answer to Recover's one question ("deck", "eight"), or None."""
    try:
        return plan_flow._pcfg().get("leech_reach") if mw.col else None
    except Exception:
        return None


def _fsrs_on():
    """Whether FSRS is on in this collection; None when there's none open."""
    if not mw.col:
        return None
    try:
        return bool(mw.col.get_config("fsrs", False))
    except Exception:
        return None


def _settings_cmd(cmd, parts):
    """One click in the board's Settings. Changes apply at once."""
    from .settings_model import TABS, change
    c = cfg()
    focus = ":".join([cmd] + parts)
    if cmd == "settab":
        if parts and parts[0] in TABS:
            _state["settings_tab"] = parts[0]
            _swap(c)
        return
    if cmd == "setclose":
        _state["settings_tab"] = None
        _swap(c)
        return
    if cmd == "setname":
        _rename()
    elif cmd == "setemoji":
        if _edit_emoji(mw) is not None:
            _swap(cfg(), focus)
    elif cmd == "setstatus":
        _edit_status(lambda _s: _swap(cfg(), focus))
    elif cmd == "setsquads":
        open_squads()
        _swap(cfg(), focus)
    elif cmd == "setsignin":
        _state["settings_tab"] = None
        open_auth()
    elif cmd == "setsignout":
        def out():
            _state["settings_tab"] = None
            client().sign_out()
            _on_signed_out()
        sheets.confirm("Sign out?", "Sign out on this device? Your account and stats stay.", "Sign Out", out)
    elif cmd == "setdelete":
        _delete_account()
    elif cmd == "setfeedback":
        open_feedback()  # 3.6.5, P6
    else:
        changed = change([cmd] + parts, c)
        if changed:
            _apply_settings(changed, focus="label" if cmd == "setlabel" else focus)


def _pick_exam_day(cmd):
    """3.9.5 (Sam: "removing an exam date and then clicking add exam date
    makes anki quit"): Insights' Add exam date (exampick) and its scope's
    Change (scopepick) pick the day in a Qt calendar, then change it as
    Settings does (setexam, setscope)."""
    from .settings_model import change
    from .ui import pick_date
    c = cfg()
    today = datetime.date.today()
    try:
        today = datetime.date.fromisoformat(plan_flow._today() or "")
    except ValueError:
        pass
    if cmd == "exampick":
        try:
            now = datetime.date.fromisoformat(str(c.get("exam_date") or ""))
        except ValueError:
            now = today + datetime.timedelta(days=7)
        day = pick_date(mw, "Exam date", max(now, today), lo=today, hi=today + datetime.timedelta(days=730))
        changed = change(["setexam", day], c, today=today) if day else None
    else:
        try:
            now = datetime.date.fromisoformat(str(c.get("exam_since") or ""))
        except ValueError:
            now = today - datetime.timedelta(days=14)
        day = pick_date(mw, "Count the cards started since", min(now, today), hi=today)
        changed = change(["setscope", day], c, today=today) if day else None
    if changed:
        _apply_settings(changed)


def _apply_settings(changed, focus=None):
    """Save what one change changed; the board redraws at once, and a
    sharing change goes out a moment later (one sync for a run of clicks)."""
    c = cfg()
    push = any(k in changed and changed[k] != c.get(k) for k in SHARE_KEYS)
    chip = any(k in changed and changed[k] != c.get(k, d) for k, d in
               (("room_chip_side", "right"), ("fifteen", True), ("sev", True), ("sev_break", "breathe")))  # 3.8.1
    leeches = changed.get("due_leeches") is True and not c.get("due_leeches")
    exam = "exam_date" in changed and str(changed["exam_date"] or "") != str(c.get("exam_date") or "")
    c.update(changed)
    save_cfg(c)
    if exam:
        ahead_flow.exam_moved()  # 3.9.2's QoL pass: a pause to it follows now, not tomorrow
    if changed.get("show_leaderboard") is False:
        _state["settings_tab"] = None
        _rerender()
        tooltip("Due Crew is off the Decks screen. Tools › Due Crew › Show on the Decks screen brings it back.")
    else:
        # the focus names the command sent; after a toggle it's the opposite one
        _swap(c, focus=_flip(focus))
    if chip:
        rooms.refresh_widgets()
    if "shortcuts" in changed or "magic_search" in changed:
        _apply_keys()
    if "send_errs" in changed:
        errs_flow.switched(changed["send_errs"])  # 3.9.9: off, what's kept goes too
    if leeches:
        due_flow.recover_now()  # 3.8.0: now, and said, not at the next refresh
    if push:
        _share_push["n"] += 1
        n = _share_push["n"]
        QTimer.singleShot(2500, lambda: n == _share_push["n"] and _on_sync_done())


def _flip(focus):
    """set:compact:1 was clicked; the redrawn switch sends set:compact:0."""
    if not focus:
        return focus
    for a, b in ((":1", ":0"), (":0", ":1"), (":on", ":off"), (":off", ":on")):
        if focus.endswith(a) and not focus.startswith(("set:theme", "set:accent", "set:room")):
            return focus[:-len(a)] + b
    return focus


def _rename():
    cl = client()
    current = cl.display_name

    def go(name):
        name = name.strip()
        if not name or name == current:
            return

        def done(result):
            if not result:
                tooltip("Couldn't save the name. Try again.")
                return
            tooltip("Name changed.")
            _swap(cfg())
        _bg(lambda: cl.set_display_name(name), done)
    sheets.ask_text("Display name", "New name.", go, value=current or "", most=60)


def _delete_account():
    def go():
        cl = client()

        def done(result):
            if not result:
                tooltip("Couldn't delete. Check your connection and try again.")
                return
            _state["settings_tab"] = None
            _on_signed_out()
            tooltip("Account deleted.")
        _bg(lambda: cl.delete_account() or True, done)
    sheets.confirm("Delete account?", "This deletes your stats, your code, and your account for good. No undo.",
                   "Delete Account", go, danger=True)


def open_feedback():
    """3.6.5, P6: Send feedback (Tools › Due Crew, and Settings)."""
    if not client().signed_in:
        tooltip("Sign in to send feedback.")
        return
    from .ui.feedback_dialog import FeedbackDialog
    FeedbackDialog(mw, client(), ADDON_VERSION, on_sent=lambda: tooltip("Sent. Thanks, every one is read.")).exec()


def open_settings(tab=None):
    """tab: "you", "board", or "privacy" (your card's Privacy… opens that
    one). 3.8.0, one Settings: the board's, on the Decks screen, from
    anywhere (Tools › Due Crew › Settings…, the add-on's Config button);
    signed out or with the board turned off it shows too, since Settings
    is how the board comes back."""
    from .settings_model import TABS
    _state["settings_tab"] = tab if tab in TABS else "you"
    _state["wrapped_open"] = None
    _close_addons_dialog()
    if mw.state != "deckBrowser":
        mw.moveToState("deckBrowser")  # its draw shows Settings
    elif _board_on_screen():
        _swap(cfg())
    else:
        _rerender()


def _browse_day(day):
    """3.8.0: a day on my own year (the profile card): the cards I answered
    that Anki day, in Browse."""
    try:
        d = datetime.date.fromisoformat(str(day))
        today = datetime.date.fromisoformat(due_flow._today())
    except (TypeError, ValueError):
        return
    ago = (today - d).days
    if ago < 0 or not mw.col:
        return
    end = (int(mw.col.sched.day_cutoff) - ago * 86400) * 1000
    cids = [int(x) for x in mw.col.db.list(
        "SELECT DISTINCT cid FROM revlog WHERE id >= ? AND id < ? AND ease > 0", end - 86400 * 1000, end)]
    plan_flow._browse(cids, empty="No reviews that day.")


def _close_addons_dialog():
    """The add-on's Config button opens Settings on the Decks screen: the
    Add-ons window in front of it closes."""
    try:
        import aqt
        inst = (getattr(aqt.dialogs, "_dialogs", {}).get("AddonsDialog") or [None, None])[1]
        if inst:
            inst.close()
    except Exception:
        pass


SHARE_KEYS = ("show_up", "share_reviews", "share_time", "share_retention", "share_streak",
              "share_heatmap", "paused", "exam_date",
              "away_from", "away_to")


def _on_signed_out():
    global _fetching, _pushed
    _closet(lambda cf: cf.clear_fridge())  # 3.9.1: the drawings were that account's
    _reset_runtime(keep_sync=True)
    with _lock:
        _fetching = False
    _pushed = None
    _rerender()


def _on_profile_open():
    global _menu_done, _closing, _last_attempt, _fetching, _pushed
    if not _menu_done:
        _menu_done = True
        _tools_menu()
        mw.addonManager.setConfigAction(__name__, open_settings)
    _reset_runtime()          # profile switch: nothing carries over
    with _lock:
        _fetching = False     # the last profile's refresh can't commit here
    _closing = False
    _last_attempt = 0.0
    _pushed = None
    client()                  # rebind to this profile's session
    try:
        errs_flow.open_profile()  # 3.9.9: this profile's counts for Sam
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
MAGIC_KEY = "Ctrl+Shift+F"  # 3.9.7: Magic search (⌘⇧F on a Mac); Settings › Board › Due takes it away


def _tools_menu():
    """Tools › Due Crew (3.1: a submenu, for plans). 3.8.0: Study what's
    next on top (Ctrl+Shift+S), Settings… opens the board's, and Show on
    the Decks screen is the way back when the board is off. 3.9.3: one
    Plans ▸ holds everything about plans (planner.plans_menu)."""
    from aqt.qt import QMenu, QShortcut, QKeySequence
    if getattr(mw, "_due_crew_menu", None) is not None:
        return  # a second profile open: the submenu is already there
    from . import planner
    menu = QMenu("Due Crew", mw)
    for item in (("Study what’s next", due_flow.study_today),
                 ("Magic search…", open_magic), None,  # 3.9.7
                 ("Friends…", open_friends),
                 ("Squads…", open_squads),
                 ("Pip Party…", open_game_night),  # 3.9.5: the You bubble on it; shown when it is (gamenight_flow.shown)
                 "plans", None,  # 3.9.3: Plans ▸, the plan windows among its entries
                 ("Settings…", open_settings),
                 ("Pip’s closet…", lambda: open_closet()),
                 ("Your year…", lambda: open_wrapped()),
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
    """3.9.7: Magic search, unless Settings › Board › Due has it off."""
    errs.used("magic")
    if not magic_flow.on():
        tooltip("Magic search is off: Settings › Board › Due turns it on.")
        return
    magic_flow.open_search(text)


def open_game_night():
    """3.9.5: Tools › Due Crew › Pip Party: the You bubble open on it (gamenight_flow; game night until its last round)."""
    gamenight_flow.open_tab()


def _ask_this_card():
    from . import team_flow
    team_flow.ask_this_card()


def _apply_keys():
    """Settings › Board › Shortcuts: both keys on, or both off (per computer)."""
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
    global _last_attempt
    if not mw.col or not client().signed_in or client().session_dead:
        return
    if not _open_push_due(time.time(), _last_attempt):
        return
    _last_attempt = time.time()
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
    global _closing
    _closing = True
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


gui_hooks.deck_browser_will_render_content.append(_on_render)


gui_hooks.deck_browser_did_render.append(_on_did_render)


# first: the upload that follows knows the phone's reviews are in
gui_hooks.sync_did_finish.append(_mark_anki_synced)


gui_hooks.sync_did_finish.append(_on_anki_sync)


gui_hooks.webview_did_receive_js_message.append(_on_js)


gui_hooks.profile_did_open.append(_on_profile_open)


gui_hooks.profile_will_close.append(_on_profile_close)


# 2.10: the flag on the reviewer's More menu. 3.2: a tip no longer goes
# under the answer; the chip beside Edit shows it, and who knows the card
# (nothing is drawn inside a card).
gui_hooks.reviewer_will_show_context_menu.append(together.reviewer_menu)
gui_hooks.reviewer_did_show_answer.append(crew_cards.on_answer)
gui_hooks.reviewer_did_show_question.append(crew_cards.on_question)


# 3.1: single cards onto a plan's date, from Anki's browser
gui_hooks.browser_will_show_context_menu.append(plan_flow.browser_menu)
if hasattr(gui_hooks, "browser_sidebar_will_show_context_menu"):  # 3.8.0: a tag's Due Crew: open its cards…
    gui_hooks.browser_sidebar_will_show_context_menu.append(plan_flow.sidebar_menu)
if hasattr(gui_hooks, "browser_did_fetch_row"):  # 3.9.5: Due says when a plan opens a suspended card
    gui_hooks.browser_did_fetch_row.append(plan_flow.browser_row)
if hasattr(gui_hooks, "browser_will_show"):
    gui_hooks.browser_will_show.append(lambda _browser: plan_flow.opens_reset())


# 2.12: study rooms. The room follows Anki from screen to screen; the break
# waits for the card on screen to be answered.
gui_hooks.reviewer_did_show_question.append(rooms.on_question)
gui_hooks.reviewer_did_show_answer.append(rooms.on_answer)
if hasattr(gui_hooks, "reviewer_will_answer_card"):
    gui_hooks.reviewer_will_answer_card.append(rooms.will_answer)  # none under a room's break
    gui_hooks.reviewer_will_answer_card.append(two_buttons.will_answer)  # 3.9.1: 2, 3 and 4 are Good
if hasattr(gui_hooks, "reviewer_will_init_answer_buttons"):
    gui_hooks.reviewer_will_init_answer_buttons.append(two_buttons.will_init_buttons)  # 3.9.1: Again and Good
gui_hooks.state_did_change.append(rooms.on_state)
gui_hooks.state_did_change.append(due_flow.on_state)  # 3.8.0: Study today's walk
gui_hooks.state_shortcuts_will_change.append(due_flow.walk_keys)  # and Escape stops it
if hasattr(gui_hooks, "top_toolbar_did_redraw"):  # Anki 2.1.54+
    gui_hooks.top_toolbar_did_redraw.append(rooms.on_toolbar)
# 3.9.1 (the efficiency run): a page sent once is sent again only on a new page
gui_hooks.webview_will_set_content.append(app.on_set_content)
gui_hooks.state_will_change.append(app.on_state_will_change)  # 3.9.1: the Decks page isn't up till it renders
gui_hooks.state_will_change.append(ahead_flow.on_state)  # 3.9.2's audit: Stop new is set before I study
if hasattr(gui_hooks, "theme_did_change"):
    gui_hooks.theme_did_change.append(rooms.on_theme)  # the widgets pick their colours as they're drawn

# the modules that need a redraw or a refresh reach it through app
app.swap = _swap
app.on_account_change = account.on_change
app.rerender = _rerender
app.refresh = refresh_board
app.sync = _on_sync_done
app.apply_settings = _apply_settings  # 3.9.7: Magic search's exam and away, as Settings saves them
