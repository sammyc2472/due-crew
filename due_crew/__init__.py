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

import datetime
import html
import json
import os
import threading
import time
import traceback

from aqt import gui_hooks, mw
from aqt.deckbrowser import DeckBrowser
from aqt.qt import QAction, QApplication, QCursor, QMenu
from aqt.utils import tooltip

from . import board
from .backend.firebase import FirebaseClient, TransportError
from .stats import duet_runs, gather_stats, gather_week
from .stats.decks import gather_shared_decks
from .stats.queries import StatsQueries
from .ui import copy_text

CHEER_EMOJI = ("\U0001F389", "\U0001F4AA", "\U0001F525")  # party, muscle, fire
STREAK_MILESTONES = (7, 30, 100, 365)
CREW_REVIEW_MILESTONES = (100_000, 250_000, 500_000, 1_000_000)
CREW_HOUR_MILESTONE_MS = 1000 * 3600 * 1000  # 1,000 hours
RETURN_QUIET_DAYS = 7
HEATMAP_DAYS = 182

_client = None
_client_profile = None
_state = {
    "entries": None, "days": {}, "decks": {}, "labels": [], "tomorrow": "",
    "pending": [], "ts": 0.0, "prev_label": "", "prev_counts": {},
    "prev_streaks": {}, "board_shown": False,
    "my_friends": [], "server_rows": None, "server_ts": 0.0,
    "server_state": "loading",
}
_pending_cheers = []
_wrap = {"profile": None, "data": {}}
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


def _server_config():
    try:
        with open(os.path.join(_profile_files(), "server.json")) as f:
            conf = json.load(f)
        return conf if isinstance(conf, dict) else {}
    except Exception:
        return {}


def server_name():
    return str(_server_config().get("name", ""))


def client():
    global _client, _client_profile
    key = _profile_key()
    if _client is None or _client_profile != key:
        conf = _server_config()
        _client = FirebaseClient(os.path.join(_profile_files(), "session.json"),
                                 api_key=conf.get("apiKey"),
                                 project_id=conf.get("projectId"))
        _client_profile = key
    return _client


def _follow_rename_daily(cl, today):
    """Background thread. One directory read per day: if the founder renamed
    the crew (renamedTo on the old server_names doc), adopt the new name —
    the label, invites, and the server-board scope all follow it."""
    name = server_name()
    if not name or cl.session.get("rename_check") == today:
        return
    cl.session["rename_check"] = today
    cl._save_session()
    try:
        from .backend import directory
        current = name
        for _ in range(3):  # renames can chain; follow a few hops
            nxt = directory.follow_rename(current)
            if not nxt:
                break
            current = nxt
    except Exception:
        return  # the directory is a nicety; never fail a refresh over it
    if current != name:
        mw.taskman.run_on_main(lambda: _adopt_rename(current))


def _adopt_rename(new_name):
    """Main thread (config write). The join code belonged to the old name,
    so it's dropped — invites fall back to the short form until the founder
    shares the new code."""
    conf = _server_config()
    if not conf or conf.get("name") == new_name:
        return
    conf["name"] = new_name
    conf.pop("code", None)
    try:
        with open(os.path.join(_profile_files(), "server.json"), "w") as f:
            json.dump(conf, f)
    except OSError:
        return
    tooltip(f"Your crew server is now {html.escape(new_name)}.")
    _rerender()


def _switch_server(conf):
    """conf {} = back to the default server. Signs out locally, rebinds."""
    global _client
    if client().signed_in:
        client().sign_out()
    path = os.path.join(_profile_files(), "server.json")
    try:
        if conf:
            with open(path, "w") as f:
                json.dump(conf, f)
        elif os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
    _client = None
    _reset_runtime()
    _rerender()
    tooltip(f"Crew server: {html.escape(conf.get('name') or 'default')}. "
            f"Sign in to continue.")


def _reset_runtime():
    _state.update(entries=None, days={}, decks={}, labels=[], tomorrow="",
                  pending=[], ts=0.0, prev_label="", prev_counts={},
                  prev_streaks={}, board_shown=False,
                  my_friends=[], server_rows=None, server_ts=0.0,
                  server_state="loading")
    _pending_cheers.clear()


# ---- weekly wrap + deck baselines (local, per profile) ----

def _wrap_data():
    key = _profile_key()
    if _wrap["profile"] != key:
        _wrap["profile"] = key
        try:
            with open(os.path.join(_profile_files(), "wrap.json")) as f:
                _wrap["data"] = json.load(f)
        except Exception:
            _wrap["data"] = {}
    return _wrap["data"]


def _save_wrap():
    try:
        with open(os.path.join(_profile_files(), "wrap.json"), "w") as f:
            json.dump(_wrap["data"], f)
    except OSError:
        pass


def _week_key(label):
    year, week, _day = datetime.date.fromisoformat(label).isocalendar()
    return f"{year}-W{week:02d}"


def _update_wrap(entries, labels):
    """New-week bookkeeping. Returns a milestone toast string, or None."""
    w = _wrap_data()
    week = _week_key(labels[0])
    if w.get("week") == week:
        return None
    totals_r = totals_t = 0
    best = w.setdefault("best", {})
    best_name, best_gain = "", 0
    for e in entries:
        agg = board._week_row(e["days"], labels) or {}
        reviews = agg.get("reviews") or 0
        totals_r += reviews
        totals_t += agg.get("time_ms") or 0
        gain = reviews - best.get(e["user_id"], 0)
        if reviews > 0 and gain > best_gain:
            best_name, best_gain = e["name"], gain
        if reviews > best.get(e["user_id"], 0):
            best[e["user_id"]] = reviews
    w["banner"] = {"reviews": totals_r, "time_ms": totals_t,
                   "best_name": best_name,
                   "full_days": board._full_crew_days(entries, labels)}
    w["week"] = week
    w["dismissed"] = ""
    w["deck_base"] = {f"{e['user_id']}|{d.get('name', '')}": int(d.get("seen") or 0)
                      for e in entries for d in (e.get("decks") or [])}
    toast = _accrue_milestones(w, totals_r, totals_t, labels[0])
    _save_wrap()
    return toast


def _accrue_milestones(w, week_reviews, week_time_ms, today_label):
    """Lifetime crew totals, accrued weekly, celebrated at thresholds.
    Local arithmetic only; "since" is when accrual began, never an estimate."""
    life = w.setdefault("life", {"reviews": 0, "time_ms": 0,
                                 "since": today_label})
    life["reviews"] += int(week_reviews or 0)
    life["time_ms"] += int(week_time_ms or 0)
    done = w.setdefault("milestones_done", [])
    crossed = None
    for t in CREW_REVIEW_MILESTONES:
        if life["reviews"] >= t and f"r{t}" not in done:
            done.append(f"r{t}")
            crossed = f"{t:,} reviews"
    if life["time_ms"] >= CREW_HOUR_MILESTONE_MS and "h1000" not in done:
        done.append("h1000")
        crossed = crossed or "1,000 hours"
    if not crossed:
        return None
    try:
        since = datetime.date.fromisoformat(life["since"])
        today = datetime.date.fromisoformat(today_label)
        month = since.strftime("%B") if since.year == today.year \
            else since.strftime("%b %Y")
    except (TypeError, ValueError):
        month = ""
    w["banner"]["milestone"] = crossed
    tail = f" together since {month}" if month else " together"
    return f"\U0001F388 {crossed}{tail}"


def _update_returns(entries, labels, tomorrow, c):
    """The day a quiet friend's first sync lands, the board says so — once.
    Spoken to the crew, never at the returner. Local state only."""
    if not labels:
        return []
    w = _wrap_data()
    last = w.setdefault("last_studied", {})   # uid -> newest studied label
    rets = w.setdefault("returns", {})        # uid -> label of return day
    today = labels[0]
    toasts = []
    seen_uids = set()
    for e in entries:
        if e["you"] or e["paused"]:
            continue
        uid = e["user_id"]
        seen_uids.add(uid)
        days = e.get("days") or {}
        active = board._showed(days.get(tomorrow) or days.get(today))
        prior = [lb for lb in labels[1:] if board._showed(days.get(lb))]
        if active:
            known = last.get(uid)
            if known and not prior and rets.get(uid) != today:
                try:
                    gap = (datetime.date.fromisoformat(today)
                           - datetime.date.fromisoformat(known)).days
                except (TypeError, ValueError):
                    gap = 0
                if gap >= RETURN_QUIET_DAYS:
                    rets[uid] = today
                    if c.get("sync_notifications", True):
                        toasts.append(
                            f"\U0001F44B {html.escape(e['name'])} is back "
                            f"— first study in {gap} days")
        newest = today if active else (prior[0] if prior else None)
        if newest and newest > str(last.get(uid) or ""):
            last[uid] = newest
        e["back"] = rets.get(uid) == today
    for uid in [u for u in list(last) if u not in seen_uids]:
        last.pop(uid, None)
        rets.pop(uid, None)
    _save_wrap()
    return toasts


def _exam_eve_info():
    """People whose shared exam is tomorrow — one dismissible line's worth."""
    labels = _state["labels"]
    if not labels:
        return None
    today = labels[0]
    if _wrap_data().get("eve_dismissed") == today:
        return None
    people = [(e["user_id"], e["name"]) for e in _state["entries"] or []
              if not e["you"] and not e["paused"]
              and board._exam_text(e.get("exam_date"), today) == "exam tomorrow"]
    return {"people": people} if people else None


def _wrap_info():
    w = _wrap_data()
    if not _state["labels"] or w.get("week") != _week_key(_state["labels"][0]):
        return None
    if w.get("dismissed") == w.get("week"):
        return None
    banner = w.get("banner") or {}
    return banner if banner.get("reviews") else None


def _deck_deltas():
    base = _wrap_data().get("deck_base") or {}
    out = {}
    for e in _state["entries"] or []:
        for d in e.get("decks") or []:
            key = f"{e['user_id']}|{d.get('name', '')}"
            if key in base:
                delta = int(d.get("seen") or 0) - base[key]
                if delta > 0:
                    out[(e["user_id"], d.get("name", ""))] = delta
    return out


SERVER_CACHE_SECS = 300


def _server_key():
    return server_name() or "default"


def _server_view():
    """What board._server_html renders. Row decoration is cheap and local."""
    c = cfg()
    if not (c.get("server_board") and not c.get("paused")):
        return {"state": "optin", "server": _server_key()}
    rows = _state["server_rows"]
    if rows is None:
        return {"state": _state["server_state"], "server": _server_key()}
    me = client().user_id
    crew = {e["user_id"] for e in _state["entries"] or [] if not e["you"]}
    added = set(_state["my_friends"])
    keep_days = {_state["labels"][0] if _state["labels"] else "",
                 _state["tomorrow"]}
    out = []
    for r in rows:
        if r["day"] not in keep_days:
            continue  # only people who studied today are on the board
        out.append(dict(r, you=(r["user_id"] == me),
                        crew=(r["user_id"] in crew),
                        pending=(r["user_id"] in added
                                 and r["user_id"] not in crew)))
    return {"state": "ok", "rows": out, "server": _server_key()}


def _fetch_server_rows(force=False):
    """Lazy: one query when the view opens, cached a few minutes."""
    if _state["server_rows"] is not None and not force \
            and time.time() - _state["server_ts"] < SERVER_CACHE_SECS:
        return
    cl = client()
    key = _server_key()

    def job():
        try:
            rows = cl.fetch_server_board(key)
            state = "ok"
        except Exception:
            rows, state = None, "error"

        def commit():
            if rows is not None:
                _state["server_rows"] = rows
                _state["server_ts"] = time.time()
            _state["server_state"] = state
            _swap(cfg())

        mw.taskman.run_on_main(commit)

    threading.Thread(target=job, daemon=True).start()


def _board_data():
    return {"entries": _state["entries"], "labels": _state["labels"],
            "tomorrow": _state["tomorrow"], "pending": _state["pending"]}


# ---- refresh ----

def refresh_board(upload_stats=None, backfill=None, shared_decks=None,
                  heatmap=None, board_row=None, full=False):
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
            if board_row is not None:
                if isinstance(board_row, dict) and not c.get("paused"):
                    cl.upload_board_row(uid, board_row)
                elif not cl.session.get("board_row_deleted"):
                    cl.delete_board_row(uid)  # opted out, or paused
            cl.check_rules(labels[0])  # cached: one real request per day
            _follow_rename_daily(cl, labels[0])
            data = cl.fetch_board(uid, fetch_labels, tomorrow=tomorrow,
                                  include_shared=full)
            mw.taskman.run_on_main(lambda: _commit(data, c, labels, tomorrow))
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

    last_seen = client().session.get("cheers_seen_ts", "")
    fresh = [ch for ch in data.get("cheers", []) if ch["at"] > last_seen]
    if fresh:
        client().session["cheers_seen_ts"] = max(ch["at"] for ch in fresh)
        client()._save_session()
        _pending_cheers.extend(fresh)

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
    back = (cheers[0]["from"], cheers[0]["emoji"]) if len(cheers) == 1 else None
    mw.web.eval(board.flurry_js(emojis, text, back=back))


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
            content.stats += board.render(_board_data(), c, _state["ts"],
                                          wrap=_wrap_info(), deltas=_deck_deltas(),
                                          exam_eve=_exam_eve_info(),
                                          rules_stale=client().rules_stale,
                                          server_view=_server_view())
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
    row = "off"
    if c.get("server_board") and stats is not None:
        row = {"name": client().display_name or "Me",
               "server": _server_key(),
               "day": StatsQueries(mw.col).day_label(0),
               "reviews": int(stats.reviews),
               "studyTimeMs": int(stats.time_ms),
               "streak": int(stats.streak)}
    refresh_board(upload_stats=stats, backfill=week, shared_decks=decks,
                  heatmap=heat, board_row=row)


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
        if parts[2] == "server" and c.get("server_board") \
                and not c.get("paused"):
            _fetch_server_rows()
    elif cmd == "refresh":
        refresh_board(full=True)
        if c.get("period") == "server" and c.get("server_board"):
            _fetch_server_rows(force=True)
    elif cmd == "friends":
        open_friends()
    elif cmd == "decks":
        open_decks()
    elif cmd == "setup":
        open_welcome()
    elif cmd == "cheerpick" and len(parts) > 2:
        _cheer_menu(parts[2])
    elif cmd == "profile" and len(parts) > 2:
        _open_profile(parts[2])
    elif cmd == "evedismiss":
        w = _wrap_data()
        w["eve_dismissed"] = _state["labels"][0] if _state["labels"] else ""
        _save_wrap()
        _swap(c)
    elif cmd == "rules":
        open_rules()
    elif cmd == "wrapdismiss":
        w = _wrap_data()
        w["dismissed"] = w.get("week", "")
        _save_wrap()
        _swap(c)
    elif cmd in ("sharetoday", "sharetape", "sharecrew"):
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
    elif cmd == "scard" and len(parts) > 2:
        _open_server_card(parts[2])
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
                            server_view=_server_view())
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


# ---- shares (clipboard) ----

def _share(kind):
    """Main thread (collection access + clipboard). Builds one of the
    paste-ready shares from local stats and the cached board."""
    if not mw.col:
        return
    from . import share
    try:
        stats = gather_stats(mw.col, _profile_files())
    except Exception:
        traceback.print_exc()
        return
    if kind == "sharecrew":
        text = _crew_share_text(stats)
        if text is None:
            tooltip("No one's studied yet today.")
            return
    elif kind == "sharetape":
        text = share.my_today_tape(stats.reviews, stats.time_ms, stats.streak,
                                   stats.accuracy, stats.hourly)
    else:
        text = share.my_today_spark(stats.reviews, stats.time_ms, stats.streak,
                                    stats.accuracy, stats.hourly)
    copy_text(text)
    tooltip("Copied.")


def _crew_share_text(stats):
    """My row from local revlog (fresh); friends' rows from their uploaded
    hours. Only people who studied today become rows."""
    from . import share
    labels, tomorrow = _state["labels"], _state["tomorrow"]
    today = labels[0] if labels else ""
    rows, cards = [], 0
    for e in _state["entries"] or []:
        if e.get("paused"):
            continue
        if e["you"]:
            levels, n = share.hour_levels(stats.hourly), stats.reviews
        else:
            days = e.get("days") or {}
            doc = days.get(tomorrow) or days.get(today) or {}
            levels, n = share.levels_from_str(doc.get("hours")), doc.get("reviews")
        if levels and any(levels):
            rows.append((e["name"], levels))
            cards += int(n or 0)
    if not rows and stats.reviews:
        rows.append((client().display_name or "Me", share.hour_levels(stats.hourly)))
        cards = stats.reviews
    return share.crew_today(server_name() or "Crew", rows, cards)


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


# ---- server board: cards + knocks ----

def _open_server_card(uid):
    """Click a name on the server board. Crew and you get the full card;
    everyone else gets the spare stranger card — Add lives there."""
    if any(e["user_id"] == uid for e in _state["entries"] or []):
        _open_profile(uid)
        return
    row = next((r for r in _state["server_rows"] or []
                if r["user_id"] == uid), None)
    if row is None:
        return
    pending = uid in _state["my_friends"]
    mw.web.eval(board.stranger_card_js({
        "uid": uid, "name": row["name"], "reviews": row["reviews"],
        "time_ms": row["time_ms"], "streak": row["streak"],
        "pending": pending,
    }))


def _send_knock(to_uid):
    """Add from the board: they go in my list (my consent), and a knock
    tells them (their turn). Crew once they add back."""
    cl = client()
    me = cl.user_id
    if not to_uid or to_uid == me or to_uid in _state["my_friends"]:
        return
    friends = list(_state["my_friends"])
    my_name = cl.display_name or "A friend"

    def job():
        try:
            ok = cl.set_friends(me, friends + [to_uid])
            ok = cl.send_knock(to_uid, me, my_name) and ok
        except Exception:
            ok = False

        def done():
            if ok:
                _state["my_friends"] = friends + [to_uid]
                tooltip("Knocked — you're crew when they add back.")
                _swap(cfg())
            else:
                tooltip("Couldn't knock. Check your connection.")

        mw.taskman.run_on_main(done)

    threading.Thread(target=job, daemon=True).start()


def _mute_knocker(uid):
    w = _wrap_data()
    muted = w.setdefault("muted_knocks", [])
    if uid not in muted:
        muted.append(uid)
        _save_wrap()


# ---- friend profile card ----

def _open_profile(uid):
    entry = next((e for e in (_state["entries"] or [])
                  if e["user_id"] == uid), None)
    if entry is None or not mw.col:
        return
    you = bool(entry.get("you"))
    q = StatsQueries(mw.col)
    my_labels = [q.day_label(i) for i in range(HEATMAP_DAYS)]
    my_days = set() if you else set(q.heatmap_counts(HEATMAP_DAYS))
    tomorrow = _state["tomorrow"]
    labels = _state["labels"]
    days = entry["days"]
    doc = (days.get(tomorrow) or (days.get(labels[0]) if labels else None)
           or next((days.get(lb) for lb in labels[1:] if days.get(lb)), None))
    streak_val = (doc or {}).get("streak")
    groups, _extras = board.build_deck_groups(_state["entries"])
    decks_line = ", ".join(g["label"] for g in groups
                           if any(u == uid for _n, _m, _d, u in g["rows"]))
    exam = board._exam_text(entry.get("exam_date", ""),
                            labels[0] if labels else "")
    exam = exam[:1].upper() + exam[1:] if exam else ""
    cl = client()

    def job():
        try:
            # your own card fetches your own heatmap doc: the honest,
            # as-uploaded state, not a local recomputation
            counts = cl.fetch_heatmap(uid)
        except Exception:
            counts = None

        def show():
            if mw.state != "deckBrowser":
                return
            cells = same = duet = None
            if counts is not None:
                cells = [counts.get(lb, 0) for lb in reversed(my_labels)]
                if not you:
                    their_days = {lb for lb, n in counts.items() if n}
                    same = len(my_days & their_days)
                    run, best = duet_runs(my_days, their_days, my_labels[0])
                    mine_week = [lb in my_days for lb in reversed(labels)]
                    theirs_week = [
                        board._showed((days.get(tomorrow) or days.get(lb))
                                      if lb == labels[0] else days.get(lb))
                        for lb in reversed(labels)]
                    duet = {"run": run, "best": best,
                            "mine_week": mine_week, "theirs_week": theirs_week}
            mw.web.eval(board.profile_overlay_js({
                "name": entry["name"], "streak": streak_val,
                "last_active": entry["last_updated"], "cells": cells,
                "same_days": same, "decks_line": decks_line, "uid": uid,
                "you": you, "paused": bool(entry.get("paused")), "exam": exam,
                "duet": duet,
            }))

        mw.taskman.run_on_main(show)

    threading.Thread(target=job, daemon=True).start()


# ---- dialogs ----

def open_server_join():
    from .ui.server_dialog import JoinServerDialog
    dlg = JoinServerDialog(mw, server_name(), _switch_server,
                           open_server_register)
    dlg.exec()
    return dlg


def open_server_register():
    from .ui.server_dialog import RegisterServerDialog
    conf = _server_config()
    prefill = (conf.get("apiKey"), conf.get("projectId")) if conf else None
    dlg = RegisterServerDialog(mw, _switch_server, prefill=prefill)
    dlg.exec()
    return dlg


def open_welcome():
    from .ui.server_dialog import StartCrewDialog, WelcomeDialog
    dlg = WelcomeDialog(mw)
    if not dlg.exec() or not dlg.choice:
        return
    if dlg.choice == "join":
        joined = open_server_join()
        if getattr(joined, "joined", False) and not client().signed_in:
            open_auth()
    elif dlg.choice == "start":
        if StartCrewDialog(mw).exec():
            registered = open_server_register()
            if getattr(registered, "used", False) and not client().signed_in:
                open_auth()
    else:
        open_auth()


def open_auth():
    from .ui.auth_dialog import AuthDialog
    dlg = AuthDialog(mw, client(), server_name(), open_server_join)
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
    dlg = FriendsDialog(mw, client(), server=_server_config(),
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


def open_rules():
    from .ui.rules_dialog import RulesUpdateDialog
    RulesUpdateDialog(mw, server_name()).exec()


def open_settings():
    from .ui.settings_dialog import SettingsDialog
    dlg = SettingsDialog(mw, client(), cfg(), _on_settings_saved,
                         open_welcome, open_friends, _on_signed_out, open_decks,
                         server_name(), open_server_join, open_server_register)
    dlg.exec()


SHARE_KEYS = ("share_reviews", "share_time", "share_retention", "share_streak",
              "share_heatmap", "server_board", "paused", "exam_date")


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
