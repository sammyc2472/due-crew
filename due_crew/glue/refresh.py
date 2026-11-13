"""The glue: one refresh (the board's request), one sync, and what a fetched board commits."""

import datetime
import html
import threading
import time
import types

from aqt import mw
from aqt.qt import QTimer
from aqt.utils import tooltip

from .. import account
from .. import app
from .. import due_flow
from .. import plan_flow
from .. import rooms
from .. import together
from ..app import ADDON_VERSION
from ..app import FRESH_SECS
from ..app import SQUAD_CACHE_SECS
from ..app import STALE_SECS
from ..app import STREAK_MILESTONES
from ..app import _bg
from ..app import _pending_cheers
from ..app import _state
from ..app import cfg
from ..app import client
from ..backend.shapes import TransportError
from ..backend.shapes import _clean_day
from ..errs import oops
from ..social import _fresh_cheers
from ..social import _play_cheers
from ..social import drop_muted
from ..social import held_uids
from ..social import muted_uids
from ..social import send_held
from ..squads import _drop_squad
from ..squads import _my_squads
from ..squads import heal_squads
from ..stats.queries import StatsQueries
from ..ui import copy_text
from ..wrap import _update_returns
from ..wrap import _update_wrap


_lock = threading.Lock()
# 3.9.12: the flags the glue sets as it runs, in one holder every part shares (due_crew._pushed and
# the rest read and set it: the package's properties)
_run = types.SimpleNamespace(
    fetching=False,
    menu_done=False,
    last_attempt=0.0,   # when a push was last STARTED, success or not
    closing=False,      # profile_will_close: uploads still go, fetches don't
    pushed=None,        # 3.9.1: (col.mod, my day, my config) as the last push gathered them
)

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
    if _run.closing:
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
        _swap(cfg(), quiet=True)


def _after_push(pushed, labels, gone=(), gen=None):
    """Main thread. An upload that skipped the fetch: my own row follows
    what was just written, and the footer learns whether it went."""
    if gen is not None and not _current(gen):
        return
    _state["sync_error"] = not pushed
    _state["offline"] = False  # 3.9.9: it got an answer, whatever the answer was
    if not _run.closing:
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
        _swap(cfg(), quiet=True)


def refresh_board(upload_stats=None, backfill=None, shared_decks=None,
                  heatmap=None, squad_row=None, full=False, fetch=None, plans=None, extras=None):
    """Sync (optionally) and fetch, in the background: one request each.
    Main thread only. An upload is never dropped: only pure fetches dedup
    against an in-flight refresh. heatmap: dict to share, "off" to take it
    down, None to leave alone. backfill: last week's studied days. fetch:
    read the board after the upload (None: see _wants_fetch). plans (3.1):
    progress on the plans I share it on, sent when it changed. extras
    (3.2): {known, stuck, log} for the sync, as cards.for_sync gives them."""
    if not mw.col or not client().signed_in or client().session_dead:
        return  # a refused token can't be retried into working
    uploading = (upload_stats is not None or shared_decks is not None
                 or backfill is not None)
    with _lock:
        if _run.fetching and not uploading:
            return
        _run.fetching = True
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
                             time.time() - _state["ts"], _run.closing, fetch)
        clock = _clock()
        gen = app.generation
        if upload_stats is not None:
            together.auto_live(c, q.last_review_ms(), labels[0])  # 3.9.10: the studying dot, by itself
    except Exception:
        with _lock:
            _run.fetching = False
        oops()
        return
    if not uploading and not fetch:
        with _lock:
            _run.fetching = False
        return

    def job():
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
                    _run.fetching = False

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
        _swap(cfg(), quiet=True)


def _is_stale(now, fetched_at, last_attempt, limit=STALE_SECS):
    """Refresh when the board is old AND we haven't just tried. The second
    half matters offline: without it every redraw would fire a request."""
    return now - fetched_at > limit and now - last_attempt > limit


def _push_if_stale():
    """Uploads used to ride Anki's sync hook alone, so anyone who studied and
    closed Anki without syncing shared nothing. Now opening Anki, and coming
    back to a stale deck screen, push too. Hash guards keep an unchanged day
    at zero writes; the fetch is capped by STALE_SECS."""
    if not mw.col or not client().signed_in or client().session_dead:
        return
    now = time.time()
    if not _is_stale(now, _state["ts"], _run.last_attempt):
        return
    _run.last_attempt = now  # claim it now: a second redraw must not double up
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
    from ..share import INVITE_COPIED, friend_invite
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
        _scrap(lambda sf: sf.cheers_in(fresh))  # 3.9.10: counted by month; one with words is kept
    # 3.9.11, hooks: who mine helped (said once), and any of mine still owed to the server
    from .. import cards as _crew_cards
    _crew_cards.hook_thanks(data.get("thanks"))
    _crew_cards.flush_hooks()

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
        _swap(cfg(), quiet=True)        # page not rebuilt: safe to play cheers directly
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
    if not _run.closing:
        send_held(labels[0])  # 3.9.9: cheers that waited for Due Crew to be reachable go now


# Names of the parts after this one. The package sets them as each of those parts loads
# (an import here would load a later part before the ones between).
_LATER = ("_awaiting_phone", "_board_off", "_closet", "_closet_day", "_joy_show", "_on_sync_done",
          "_rerender", "_scrap", "_swap", "k")
_awaiting_phone = _board_off = _closet = _closet_day = _joy_show = _on_sync_done = None
_rerender = _scrap = _swap = k = None
