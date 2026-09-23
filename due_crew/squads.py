"""Squads: the private boards behind an invite code — the view, the lazy
fetch, the squadmate card, join/create/leave/lock/remove, and knocks (the
add-me flow between squadmates). Main-thread rules as in __init__."""

import html
import time

from aqt import mw
from aqt.utils import askUser, tooltip

from . import app, board
from .app import SQUAD_CACHE_SECS, _bg, _state, cfg, client, save_cfg
from .backend.firebase import TransportError
from .social import _open_profile
from .stats.queries import StatsQueries
from .ui import copy_text
from .wrap import _mute_knocker, _wrap_data

def _my_squads(c=None):
    """Squads from config: [{id, code, name, founder}]. Live config dicts.
    Pass `c` when you already hold the config: Anki's getConfig re-reads and
    re-parses two JSON files on every call."""
    c = cfg() if c is None else c
    return [sq for sq in (c.get("squads") or [])
            if isinstance(sq, dict) and sq.get("id")]


def _current_squad(c=None):
    c = cfg() if c is None else c
    squads = _my_squads(c)
    if not squads:
        return None
    sel = c.get("squad") or ""
    return next((sq for sq in squads if sq["id"] == sel), squads[0])


def _squad_view(c=None):
    """What board._squads_html renders. Decoration is cheap and local."""
    c = cfg() if c is None else c
    squads = _my_squads(c)
    cur = _current_squad(c)
    base = {"squads": [{"id": sq["id"], "name": sq.get("name") or "?"} for sq in squads],
            "current": cur["id"] if cur else ""}
    if cur is None:
        return dict(base, state="none")
    sq = _state["squad"]
    if sq["id"] != cur["id"] or sq["data"] is None:
        state = sq["state"] if sq["id"] == cur["id"] else "loading"
        return dict(base, state=state, name=cur.get("name") or "?")
    data = sq["data"]
    me = client().user_id
    crew = {e["user_id"] for e in _state["entries"] or [] if not e["you"]}
    added = set(_state["my_friends"])
    knocked_me = {k[0] for k in _state["knocks"]}
    rows = [dict(r, you=(r["user_id"] == me), crew=(r["user_id"] in crew),
                 pending=(r["user_id"] in added and r["user_id"] not in crew),
                 knocked_me=(r["user_id"] in knocked_me))
            for r in data["rows"]]
    labels = _state["labels"]
    day = sq["day"]
    live = [r for r in rows if r["day"] == day]
    return dict(base, state="ok", name=data["name"], open=data["open"],
                founder_me=(data["founder"] == me), rows=rows, day=day,
                yesterday=labels[1] if len(labels) > 1 else "",
                people=len(rows), studying=len(live),
                reviews=sum(int(r["reviews"] or 0) for r in live))


def _fetch_squad(force=False):
    """Lazy: when the view opens. One get plus one query (a read per
    member), cached a few minutes."""
    cur = _current_squad()
    sq = _state["squad"]
    if cur is None or not mw.col or not client().signed_in:
        return
    day = _state["labels"][0] if _state["labels"] else StatsQueries(mw.col).day_label(0)
    if (sq["id"] == cur["id"] and sq["data"] is not None and not force
            and sq["day"] == day and time.time() - sq["ts"] < SQUAD_CACHE_SECS):
        return
    if sq["id"] != cur["id"]:
        sq.update(id=cur["id"], data=None, state="loading")
    cl = client()
    sid = cur["id"]

    def job():
        try:
            data = cl.fetch_squad(sid)
            return data, ("ok" if data is not None else "gone")
        except TransportError as e:
            return None, ("gone" if e.status == 403 else "error")

    def commit(result):
        data, state = result or (None, "error")
        if sq["id"] != sid:
            return  # switched meanwhile
        if data is not None:
            sq.update(data=data, day=day, ts=time.time())
            c = cfg()
            for entry in c.get("squads") or []:
                if entry.get("id") == sid and entry.get("name") != data["name"]:
                    entry["name"] = data["name"]
                    save_cfg(c)
        sq["state"] = state
        app.swap(cfg())

    _bg(job, commit)


def _open_squad_card(uid):
    """Click a name on a squad board. Crew and you get the full card;
    everyone else gets the spare squadmate card — Add lives there."""
    if any(e["user_id"] == uid for e in _state["entries"] or []):
        _open_profile(uid)
        return
    view = _squad_view()
    rows = view.get("rows") or []
    row = next((r for r in rows if r["user_id"] == uid), None)
    if row is None:
        return
    field = board.SQUAD_FIELDS[board.sort_key(cfg())]  # the rank the board shows
    live = sorted([r for r in rows if r["day"] == view.get("day")],
                  key=lambda r: r[field] if r[field] is not None else -1, reverse=True)
    rank = next((i + 1 for i, r in enumerate(live) if r["user_id"] == uid), None)
    mw.web.eval(board.stranger_card_js({
        "uid": uid, "name": row["name"], "emoji": row.get("emoji") or "",
        "show_up": bool(cfg().get("show_up")), "week": row.get("week"),
        "reviews": row["reviews"],
        "time_ms": row["time_ms"], "retention": row["retention"],
        "streak": row["streak"], "rank": rank, "squad": view.get("name") or "",
        "today": row["day"] == view.get("day"), "pending": row["pending"],
        "knocked_me": row["knocked_me"], "founder_me": bool(view.get("founder_me")),
    }))


def _visible_knocks(c=None):
    """Knocks worth a banner: not muted, not already crew. Newest few."""
    muted = set(_wrap_data().get("muted_knocks") or [])
    crew = {e["user_id"] for e in _state["entries"] or []}
    names = {sq["id"]: sq.get("name") or "" for sq in _my_squads(c)}
    return [{"uid": u, "name": n, "squad": names.get(sid, "")}
            for u, n, sid in _state["knocks"] if u not in muted and u not in crew][:3]


def _add_back(uid):
    """They added me; my add makes it mutual. The knock is done either way."""
    cl = client()
    me = cl.user_id
    friends = list(_state["my_friends"])
    already = uid in friends

    def job():
        ok = already or cl.set_friends(me, friends + [uid])
        cl.delete_knock(me, uid)
        return ok

    def done(ok):
        _state["knocks"] = [k for k in _state["knocks"] if k[0] != uid]
        if ok:
            if not already:
                _state["my_friends"] = friends + [uid]
            tooltip("You're crew.")
            app.refresh(full=True)
        else:
            tooltip("Couldn't add them. Check your connection.")
            app.swap(cfg())

    _bg(job, done)


def _dismiss_knock(uid):
    _mute_knocker(uid)
    _state["knocks"] = [k for k in _state["knocks"] if k[0] != uid]
    cl = client()
    me = cl.user_id
    _bg(lambda: cl.delete_knock(me, uid))
    app.swap(cfg())


def _select_squad(sid):
    c = cfg()
    c["squad"] = sid
    save_cfg(c)
    app.swap(c)
    _fetch_squad()


def open_squads():
    from .ui.squad_dialog import SquadDialog
    dlg = SquadDialog(mw, client(), _on_squad_joined)
    dlg.exec()


def _on_squad_joined(squad):
    """Main thread. squad: {id, code, name, founder}."""
    c = cfg()
    squads = [sq for sq in (c.get("squads") or []) if sq.get("id") != squad["id"]]
    squads.append(dict(squad))
    c["squads"] = squads
    c["squad"] = squad["id"]
    c["period"] = "squads"
    save_cfg(c)
    _state["squad"].update(id=squad["id"], data=None, state="loading")
    app.swap(c)
    _fetch_squad(force=True)
    app.sync()  # my row lands now, not at the next sync


def _drop_squad(sid, swap=True):
    """Forget a squad locally (left, removed, or deleted)."""
    c = cfg()
    squads = [sq for sq in (c.get("squads") or []) if sq.get("id") != sid]
    c["squads"] = squads
    if c.get("squad") == sid:
        c["squad"] = squads[0]["id"] if squads else ""
    save_cfg(c)
    if _state["squad"]["id"] == sid:
        _state["squad"].update(id="", data=None, state="loading")
    if swap:
        app.swap(c)
        _fetch_squad()


def _copy_invite():
    cur = _current_squad()
    if cur is None:
        return
    from .ui.squad_dialog import invite_text
    code = str(cur.get("code") or "")
    if not code:
        tooltip("No code on this device.")
        return
    copy_text(invite_text(cur.get("name") or "my squad", code))
    tooltip("Copied.")


def _leave_squad():
    cur = _current_squad()
    if cur is None or not askUser(
            f"Leave {html.escape(cur.get('name') or 'this squad')}?"):
        return
    cl = client()
    me, sid = cl.user_id, cur["id"]
    _bg(lambda: cl.leave_squad(me, sid))
    _drop_squad(sid)


def _toggle_squad_lock():
    cur = _current_squad()
    sq = _state["squad"]
    if cur is None or sq["data"] is None or sq["id"] != cur["id"]:
        return
    new_open = not sq["data"]["open"]
    cl = client()

    def done(ok):
        if ok:
            sq["data"]["open"] = new_open
            tooltip("Open." if new_open else "Locked.")
            app.swap(cfg())
        else:
            tooltip("Couldn't change that.")

    _bg(lambda: cl.set_squad_open(cur["id"], new_open), done)


def _block_member(uid):
    """Founder: remove and keep them out, even with the code and an open
    door. The list rides the squad doc (rules-v7)."""
    cur = _current_squad()
    sq = _state["squad"]
    if cur is None or sq["data"] is None or sq["id"] != cur["id"]:
        return
    row = next((r for r in sq["data"]["rows"] if r["user_id"] == uid), None)
    if row is None or not askUser(
            f"Block {html.escape(row['name'])}? They leave "
            f"{html.escape(cur.get('name') or 'the squad')} and can't rejoin."):
        return
    cl = client()
    banned = list(sq["data"].get("banned") or [])

    def done(ok):
        if ok:
            sq["data"]["rows"] = [r for r in sq["data"]["rows"] if r["user_id"] != uid]
            sq["data"]["banned"] = sorted(set(banned) | {uid})
            tooltip("Blocked.")
            app.swap(cfg())
        else:
            tooltip("Couldn't block them.")

    _bg(lambda: cl.block_member(cur["id"], uid, banned), done)


def _make_founder(uid):
    """Founder: hand the squad to a member. Lock and remove move with it;
    you stay a member."""
    cur = _current_squad()
    sq = _state["squad"]
    if cur is None or sq["data"] is None or sq["id"] != cur["id"]:
        return
    row = next((r for r in sq["data"]["rows"] if r["user_id"] == uid), None)
    if row is None or not askUser(
            f"Make {html.escape(row['name'])} the founder of "
            f"{html.escape(cur.get('name') or 'the squad')}? You can't undo this."):
        return
    cl = client()

    def done(ok):
        if ok:
            sq["data"]["founder"] = uid
            c = cfg()
            for entry in c.get("squads") or []:
                if entry.get("id") == cur["id"]:
                    entry["founder"] = uid
            save_cfg(c)
            tooltip(f"{html.escape(row['name'])} is the founder now.")
            app.swap(cfg())
        else:
            tooltip("Couldn't hand it off.")

    _bg(lambda: cl.set_founder(cur["id"], uid), done)


def _share_squad():
    """Squad footer → Share: today's headline for the group chat, from the
    cached rows."""
    from . import share
    view = _squad_view()
    if view.get("state") != "ok":
        return
    live = sorted([r for r in view.get("rows") or [] if r.get("day") == view.get("day")],
                  key=lambda r: r.get("reviews") or 0, reverse=True)
    text = share.squad_today(view.get("name") or "Squad", view.get("day", ""),
                             [(r["name"], r.get("emoji") or "", r.get("reviews")) for r in live],
                             len(live), view.get("reviews") or 0)
    if text is None:
        tooltip("No one's studied yet today.")
        return
    copy_text(text)
    tooltip("Copied.")


def _kick_member(uid):
    cur = _current_squad()
    sq = _state["squad"]
    if cur is None or sq["data"] is None or sq["id"] != cur["id"]:
        return
    row = next((r for r in sq["data"]["rows"] if r["user_id"] == uid), None)
    if row is None or not askUser(
            f"Remove {html.escape(row['name'])} from "
            f"{html.escape(cur.get('name') or 'the squad')}?"):
        return
    cl = client()

    def done(ok):
        if ok:
            sq["data"]["rows"] = [r for r in sq["data"]["rows"]
                                  if r["user_id"] != uid]
            app.swap(cfg())
        else:
            tooltip("Couldn't remove them.")

    _bg(lambda: cl.remove_member(cur["id"], uid), done)


def _send_knock(to_uid):
    """Add from the board: they go in my list (my consent), and a knock
    tells them (their turn). Crew once they add back."""
    cl = client()
    me = cl.user_id
    if not to_uid or to_uid == me or to_uid in _state["my_friends"]:
        return
    cur = _current_squad()
    if cur is None:
        return
    sid = cur["id"]
    friends = list(_state["my_friends"])
    my_name = cl.display_name or "A friend"

    def job():
        ok = cl.set_friends(me, friends + [to_uid])
        return cl.send_knock(to_uid, me, my_name, sid) and ok

    def done(ok):
        if ok:
            _state["my_friends"] = friends + [to_uid]
            tooltip("Knocked — you're crew when they add back.")
            app.swap(cfg())
        else:
            tooltip("Couldn't knock. Check your connection.")

    _bg(job, done)
