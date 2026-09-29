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
import json
import re
import threading
import time
import traceback

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
from .social import (_cheer_menu, _edit_emoji, _edit_status, _fresh_cheers, _open_profile,
                     _play_cheers, _send_cheer, cheer_allowed, drop_muted, muted_uids, row_menu)
from .squads import (_add_back, _block_member, _copy_invite, _dismiss_knock, _drop_squad,
                     _fetch_squad, _kick_member, _leave_squad, _make_founder, _my_squads,
                     _open_squad_card, _select_squad, _send_knock, _share_squad, _squad_view,
                     _toggle_squad_lock, _visible_knocks, open_squads)
from .stats import gather_stats, gather_week, held_streak, week_days
from .stats import heatmap as cached_heatmap
from .stats.decks import gather_shared_decks
from .stats.queries import StatsQueries
from .ui import copy_text
from . import account, bingo_flow, plan_flow, rooms, together
from . import cards as crew_cards
from .wrap import (_deck_deltas, _exam_eve_info, _mute_knocker, _save_wrap, _update_returns,
                   _streak_info, _update_wrap, _wrap_data, _wrap_info)

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


def _after_push(pushed, labels, gone=(), gen=None):
    """Main thread. An upload that skipped the fetch: my own row follows
    what was just written, and the footer learns whether it went."""
    if gen is not None and not _current(gen):
        return
    _state["sync_error"] = not pushed
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
        traceback.print_exc()
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
            traceback.print_exc()  # cache stays untouched on failure
        finally:
            with _lock:
                if _current(gen):  # else the next profile's refresh owns the flag
                    _fetching = False

    threading.Thread(target=job, daemon=True).start()


def _sync_failed():
    """Main thread. Either the network is down (footer: Couldn't sync) or the
    server refused my sign-in for good (the card asks me back in)."""
    _state["sync_error"] = True
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
    if seen != cl.session.get("cheers_seen"):
        cl.session["cheers_seen"] = seen
        cl.session.pop("cheers_seen_ts", None)
        cl._save_session()
    # 2.10: good-luck lines wait for my exam morning, tips for their card
    today_lb = labels[0]
    my_exam = str(c.get("exam_date") or "")
    fresh, luck, tips = together.route_cheers(fresh, my_exam, today_lb)
    toasts += together.keep(luck, tips, my_exam, today_lb)
    if fresh:
        _pending_cheers.extend(fresh)

    if knocks is not None:
        _state["knocks"] = [tuple(k) for k in knocks]
    _state["notice"] = data.get("notice")  # 3.2.1
    for sid in gone or ():
        name = next((sq.get("name") for sq in _my_squads() if sq["id"] == sid), None)
        _drop_squad(sid, swap=False)
        tooltip(f"You're no longer in {html.escape(name or 'a squad')}.")

    _state.update(entries=data["entries"], labels=labels, tomorrow=tomorrow,
                  pending=data["pending"], ts=time.time(), sync_error=bool(failed),
                  my_code=str(data.get("my_code") or _state["my_code"]),
                  my_friends=list(data.get("my_friends") or []))
    # 3.1: plans ride the day's first refresh; the morning follows it
    opened = _morning(_awaiting_phone(), fresh=bool(data.get("plans_fresh")), toast=False)
    if opened:
        toasts.append(opened)
    elif data.get("plans"):
        plan_flow.refresh_progress()
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
    rooms.refresh_widgets()  # 2.12: who's in the room, as of this fetch


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
            content.stats += board.signed_out_card(c, expired=client().session_dead,
                                                   moved=client().was_on_2x)
        elif _state["entries"] is None:
            _state["board_shown"] = False
            content.stats += board.loading_card(c)
            refresh_board()
        else:
            _state["board_shown"] = True
            content.stats += _board_html(c)
            _push_if_stale()
    except Exception:
        traceback.print_exc()


def _bingo_view(c):
    sv = _squad_view(c)
    return bingo_flow.view(sv, c) if sv.get("state") == "ok" else None


def _squad_view_with_bingo(c):
    """The Squads tab's view, with this week's card when there is one (3.6)."""
    sv = _squad_view(c)
    if c.get("period") == "squads" and sv.get("state") == "ok":
        bv = bingo_flow.view(sv, c)
        if bv:
            sv = dict(sv, bingo=bv)
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
    if _state.get("settings_tab"):
        return board.settings_html(_settings_view(), c)  # 3.5.0: Settings in its place
    if _state.get("bingo_open"):
        return board.bingo_html(_bingo_view(c), c,  # 3.6: the squad's card in its place
                                loading=_squad_view(c).get("state") == "loading" and bool(bingo_flow.card()))
    show_up = bool(c.get("show_up"))
    notice = _state.get("notice")
    if notice and notice["id"] in (_wrap_data().get("notices_dismissed") or []):
        notice = None
    return board.render(_board_data(), c, _state["ts"], notice=notice,
                        wrap=_wrap_info(), deltas=_deck_deltas(), streak=_streak_info(),
                        exam_eve=_exam_eve_info(),
                        rules_stale=client().rules_stale,
                        squad_view=_squad_view_with_bingo(c), knocks=_visible_knocks(c),
                        reviews=review_banners(), sync_error=_state["sync_error"],
                        live=together.is_live(),
                        tricky=together.tricky_view() if c.get("period") == "decks" else None,
                        asks=together.my_asks_view() if c.get("period") == "decks" else None,
                        milestones=None if show_up else _state["milestones"],
                        room=rooms.board_view(),
                        plans=plan_flow.board_view(c))  # 3.3: the Plans tab shows while I follow one


def _on_did_render(deck_browser):
    mw.web.eval(board.keep_me_in_view_js())
    _play_cheers()
    together.show_luck_card()
    rooms.refresh_widgets()


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
        traceback.print_exc()
    if not light:
        try:
            week = gather_week(mw.col, _profile_files())
        except Exception:
            traceback.print_exc()
        try:
            # an install that has never had a deck list (and couldn't pull
            # one) doesn't upload an empty one over the account's
            if c.get("shared_decks") or c.get("shared_decks_set"):
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
            if "reviews" in row:
                row["newCards"] = int(stats.new_cards)  # 2.13: under Reviews, never alone
        try:
            row["week"] = week_days(StatsQueries(mw.col))
        except Exception:
            traceback.print_exc()
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
        traceback.print_exc()
    extras = None
    try:
        extras = crew_cards.for_sync(c, light=light)  # 3.2: cards I know and I'm stuck on, my log
    except Exception:
        traceback.print_exc()
    refresh_board(upload_stats=stats, backfill=week, shared_decks=decks,
                  heatmap=heat, squad_row=row, full=full, fetch=fetch, plans=plan_prog, extras=extras)


def _on_js(handled, message, context):
    if rooms.swallow(message):
        return (True, None)  # 2.12: no answering under the break
    if message.startswith("duecrew:"):
        # the reviewer's page runs the card's own script too: from there only
        # the room widget's keyed buttons count, never a bare command
        from aqt.reviewer import Reviewer
        from .room_model import trusted
        message, ok = trusted(message, isinstance(context, Reviewer))
        if not ok:
            return (True, None)
    if message.startswith("duecrew:knows"):
        # 3.2: the chip in the reviewer's bottom bar
        try:
            parts = message.split(":")
            crew_cards.on_message(parts[1], parts)
        except Exception:
            traceback.print_exc()
        return (True, None)
    if message.startswith("duecrew:room"):
        # 2.12: study rooms answer from the top bar and the review screen too
        parts = message.split(":")
        try:
            done = rooms.on_message(parts[1], parts)
        except Exception:
            traceback.print_exc()
            done = True
        if done:
            return (True, None)
    if not isinstance(context, DeckBrowser) or not message.startswith("duecrew:"):
        return handled
    parts = message.split(":")
    cmd = parts[1] if len(parts) > 1 else ""
    c = cfg()
    if cmd.startswith("plan"):
        plan_flow.on_message(cmd, parts)  # 3.1
    elif cmd == "sort" and len(parts) > 2 and parts[2] in board.SORT_KEYS:
        c["sort"] = parts[2]
        save_cfg(c)
        _swap(c)
    elif cmd in ("bingo", "bingoback", "bingocopy"):
        _bingo_cmd(cmd)
    elif cmd == "period" and len(parts) > 2 and parts[2] in board.PERIODS:
        _state["bingo_open"] = False
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
    elif cmd == "live":
        together.toggle_live()
    elif cmd == "luckline" and len(parts) > 2:
        together.send_luck_line(parts[2])
    elif cmd == "luckthanks":
        together.luck_thanks()
    elif cmd == "tricktip" and len(parts) > 3:
        together.send_tip(parts[2], parts[3])
    elif cmd == "milestonecheer" and len(parts) > 2:
        together.milestone_cheer(parts[2])
    elif cmd == "milestonex" and len(parts) > 2:
        together.dismiss_milestone(parts[2])
    elif cmd == "unask" and len(parts) > 2 and parts[2].isdigit():
        together.unask(int(parts[2]))  # 3.5.0: Take back, on the Decks tab
    elif cmd == "copyinvite":
        _copy_friend_invite()
    elif cmd == "addcode":
        if len(parts) > 2 and parts[2]:
            _add_code(parts[2])  # 3.4 review, C5: from the day-one card
        else:
            open_friends(focus_add=True)
    elif cmd == "crewmenu":
        _crew_menu(c)  # 3.4 review, H5
    elif cmd == "decks":
        open_decks()
    elif cmd == "setup":
        open_auth(join=(parts[2] == "join") if len(parts) > 2 else None)
    elif cmd == "cheerpick" and len(parts) > 2:
        _cheer_menu(parts[2])
    elif cmd == "rowmenu" and len(parts) > 2:
        row_menu(parts[2])  # 3.0.1: right-click a crewmate: mute, report
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
    elif cmd == "noticex" and len(parts) > 2 and parts[2].isdigit():
        # 3.2.1: the admin's notice, dismissed for good on this profile
        w = _wrap_data()
        w["notices_dismissed"] = (list(w.get("notices_dismissed") or []) + [int(parts[2])])[-50:]
        _save_wrap()
        _swap(c)
    elif cmd == "noticeopen":
        n = _state.get("notice")
        if n and n.get("link"):
            from aqt.utils import openLink
            openLink(n["link"])
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
    elif cmd in SETTINGS_CMDS:
        _settings_cmd(cmd, parts[2:])  # 3.5.0: Settings in the board; parts[2:] are its values
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
        emoji = cheer_allowed(emoji)
        if entry and emoji:
            _send_cheer(uid, entry["name"], emoji)
    else:
        print(f"due crew: unknown command {message!r}")
    return (True, None)


def _swap(c, focus=None):
    """Re-render the board in place from cache. No network, no page reload.
    focus: the data-f of the control to give focus back to (Settings)."""
    if _state["entries"] is None:
        _rerender()
        return
    html_out = _board_html(c)
    js = """
    (function() {
        var el = document.getElementById('due-crew');
        if (!el) { return; }
        var tmp = document.createElement('div');
        tmp.innerHTML = %s;
        el.parentNode.replaceChild(tmp.firstElementChild, el);
    })();
    """ % json.dumps(html_out) + board.keep_me_in_view_js()
    if focus:
        js += ("(function(){var f=document.querySelector('#due-crew [data-f=\"%s\"]');"
               "if(f){f.focus({preventScroll:true});}})();" % re.sub(r"[^A-Za-z0-9:_-]", "", focus))
    mw.web.eval(js)


def open_auth(join=None):
    """join: open the dialog on Join (True) or Sign In (False); None lets it
    choose. A new account gets the welcome screen before its first upload,
    so what the crew will see is said before any of it is shared."""
    global _fetching
    from .ui.auth_dialog import AuthDialog
    dlg = AuthDialog(mw, client(), join=join)
    if dlg.exec() and dlg.user:
        _uid, name = dlg.user
        _reset_runtime(keep_sync=True)
        with _lock:
            _fetching = False  # the last session's refresh can't commit now
        if dlg.joined:
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
    """The footer's Crew ▾ (3.4 review, H5), as fits the tab on screen."""
    from aqt.qt import QCursor, QMenu
    run = {"friends": lambda: open_friends(), "decks": lambda: open_decks(),
           "squadshare": lambda: _share_squad(),
           "sharetoday": lambda: _share("sharetoday"), "sharecrewweek": lambda: _share("sharecrewweek")}
    menu = QMenu(mw)
    for i, (label, key) in enumerate(board.crew_menu_items(
            c.get("period", "today"), bool(c.get("show_up")),
            (_squad_view(c) or {}).get("state") == "ok")):
        if i == 1:
            menu.addSeparator()
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
        traceback.print_exc()
        decks = None
    refresh_board(shared_decks=decks)


SETTINGS_CMDS = ("settab", "setclose", "set", "settabs", "setlabel", "setprivacy", "setexam",
                 "setaway", "setreset", "setname", "setemoji", "setstatus", "setsquads",
                 "setsignout", "setdelete", "setsignin")
_share_push = {"n": 0}


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
            "decks": decks}


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
        if _edit_status(mw) is not None:
            _swap(cfg(), focus)
    elif cmd == "setsquads":
        open_squads()
        _swap(cfg(), focus)
    elif cmd == "setsignin":
        _state["settings_tab"] = None
        open_auth()
    elif cmd == "setsignout":
        from .ui import confirm
        if confirm(mw, "Sign out?", "Sign out on this device? Your account and stats stay.", "Sign Out"):
            _state["settings_tab"] = None
            client().sign_out()
            _on_signed_out()
    elif cmd == "setdelete":
        _delete_account()
    else:
        changed = change([cmd] + parts, c)
        if changed:
            _apply_settings(changed, focus="label" if cmd == "setlabel" else focus)


def _apply_settings(changed, focus=None):
    """Save what one change changed; the board redraws at once, and a
    sharing change goes out a moment later (one sync for a run of clicks)."""
    c = cfg()
    push = any(k in changed and changed[k] != c.get(k) for k in SHARE_KEYS)
    chip = "room_chip_side" in changed and changed["room_chip_side"] != c.get("room_chip_side")
    c.update(changed)
    save_cfg(c)
    if changed.get("show_leaderboard") is False:
        _state["settings_tab"] = None
        _rerender()
        tooltip("Due Crew is off the Decks screen. Tools › Due Crew › Settings brings it back.")
    else:
        # the focus names the command sent; after a toggle it's the opposite one
        _swap(c, focus=_flip(focus))
    if chip:
        rooms.refresh_widgets()
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
    from aqt.qt import QInputDialog, QLineEdit
    cl = client()
    current = cl.display_name
    name, ok = QInputDialog.getText(mw, "Display name", "New name:", QLineEdit.EchoMode.Normal, current)
    name = name.strip()
    if not ok or not name or name == current:
        return

    def done(result):
        if not result:
            tooltip("Couldn't save the name. Try again.")
            return
        tooltip("Name changed.")
        _swap(cfg())
    _bg(lambda: cl.set_display_name(name), done)


def _delete_account():
    from .ui import confirm
    if not confirm(mw, "Delete account?", "This deletes your stats, your code, and "
                   "your account for good. No undo.", "Delete Account"):
        return
    cl = client()

    def done(result):
        if not result:
            tooltip("Couldn't delete. Check your connection and try again.")
            return
        _state["settings_tab"] = None
        _on_signed_out()
        tooltip("Account deleted.")
    _bg(lambda: cl.delete_account() or True, done)


def open_settings(tab=None):
    """tab: "you", "board", or "privacy" (your card's Privacy… opens that
    one; until 2.9 it landed on Account). 3.5.0: in the board when it's on
    screen; the dialog otherwise (the board turned off, signed out, or
    another screen)."""
    if _board_on_screen():
        from .settings_model import TABS
        _state["settings_tab"] = tab if tab in TABS else "you"
        _swap(cfg())
        return
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
    chip = "room_chip_side" in changed and changed["room_chip_side"] != c.get("room_chip_side")
    c.update(changed)
    save_cfg(c)
    _rerender()
    if chip:
        rooms.refresh_widgets()  # 3.0.1: the room chip moves now
    if push:
        # sharing choices apply now, not at whenever the next sync happens
        _on_sync_done()


def _on_signed_out():
    global _fetching
    _reset_runtime(keep_sync=True)
    with _lock:
        _fetching = False
    _rerender()


def _on_profile_open():
    global _menu_done, _closing, _last_attempt, _fetching
    if not _menu_done:
        _menu_done = True
        _tools_menu()
        mw.addonManager.setConfigAction(__name__, open_settings)
    _reset_runtime()          # profile switch: nothing carries over
    with _lock:
        _fetching = False     # the last profile's refresh can't commit here
    _closing = False
    _last_attempt = 0.0
    client()                  # rebind to this profile's session
    if client().signed_in:
        account.ensure()      # 2.13: my settings, before anything uploads
    refresh_board()           # the board, right away
    # 3.1: a profile that syncs but didn't today still gets its morning
    gen = app.generation
    QTimer.singleShot(180000, lambda: _morning_fallback(gen))
    # ...and my own numbers a few seconds later, unless Anki's own sync got
    # there first (it pushes on finish, and it may have pulled phone reviews)
    QTimer.singleShot(8000, _push_on_open)


def _tools_menu():
    """Tools › Due Crew (3.1: a submenu, for plans)."""
    from aqt.qt import QMenu
    if getattr(mw, "_due_crew_menu", None) is not None:
        return  # a second profile open: the submenu is already there
    menu = QMenu("Due Crew", mw)
    for item in (("Friends…", open_friends),
                 ("Squads…", open_squads), None,
                 ("Make a plan from a deck…", plan_flow.open_make),
                 ("Follow a plan…", plan_flow.open_follow), None,
                 ("Settings…", open_settings)):
        if item is None:
            menu.addSeparator()
            continue
        label, fn = item
        action = QAction(label, mw)
        action.triggered.connect(lambda _=False, fn=fn: fn())
        menu.addAction(action)
    mw.form.menuTools.addMenu(menu)
    mw._due_crew_menu = menu  # kept alive with the window


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
        traceback.print_exc()


gui_hooks.deck_browser_will_render_content.append(_on_render)


gui_hooks.deck_browser_did_render.append(_on_did_render)


# first: the upload that follows knows the phone's reviews are in
gui_hooks.sync_did_finish.append(_mark_anki_synced)


gui_hooks.sync_did_finish.append(_on_sync_done)


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


# 2.12: study rooms. The room follows Anki from screen to screen; the break
# waits for the card on screen to be answered.
gui_hooks.reviewer_did_show_question.append(rooms.on_question)
gui_hooks.reviewer_did_show_answer.append(rooms.on_answer)
gui_hooks.state_did_change.append(rooms.on_state)
if hasattr(gui_hooks, "top_toolbar_did_redraw"):  # Anki 2.1.54+
    gui_hooks.top_toolbar_did_redraw.append(rooms.on_toolbar)

# the modules that need a redraw or a refresh reach it through app
app.swap = _swap
app.on_account_change = account.on_change
app.rerender = _rerender
app.refresh = refresh_board
app.sync = _on_sync_done
