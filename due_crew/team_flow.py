"""3.7.3 a plan's team and its Insights, the glue (team.py is pure).

The Plans tab's plan card has three tabs: Plan, Team and Insights
(`_state["plan_sub"]`, per session). Team is opt-in per plan: joining
shares that I showed up today (answered one of the plan's cards), my
questions and answers, and my bingo squares (the same play as on my squad
rows: the week's one card); never a number. The board's refresh carries a few counts
(`session["teams"]`); the tab itself is one request when it opens, and each
click is one more. Showed-up days and squares ride the sync (`for_sync`).

Insights are mine alone: worked out here from my reviews of the plan's
cards (team.insights), never sent. Study builds Anki's filtered deck of the
cards I missed in a topic; Re-watch opens the author's watch link; Ask goes
to Team with the topic filled in."""

import time
import traceback
from urllib.parse import unquote

from aqt import mw
from aqt.utils import tooltip

from . import app
from . import plans as P
from . import team as T
from .app import _bg, _state, cfg, client
from .backend.shapes import TransportError

FRESH = 60          # seconds a fetched team is shown before the tab asks again
INSIGHTS_FRESH = 600


def _plans_flow():
    from . import plan_flow
    return plan_flow


def teams():
    return client().session.get("teams") or {}


def on_team(pid):
    return pid in teams()


def _plan(pid):
    return next((p for p in _plans_flow().followed() if p.get("id") == pid), None)


def _deck_ids(pid):
    """This computer's deck for the plan, and its subdecks, or []."""
    pf = _plans_flow()
    st = pf._state_cfg().get(pid)
    if not st or not mw.col or not pf._deck_ok(mw.col, st.get("deck_id")):
        return []
    return [int(d) for d in mw.col.decks.deck_and_child_ids(int(st["deck_id"]))]


def _wk():
    from . import bingo as B
    lb = _state["labels"][0] if _state["labels"] else ""
    return B.week_key(lb) if lb else ""


# ---- what the board shows ----

def _seen(pid):
    return int(((_plans_flow()._pcfg().get("team_seen") or {}).get(pid)) or 0)


def card_bits(pid):
    """For the plan's card: its tab, the badge, the Plan tab's team line,
    and the open tab's view (Team: as last fetched; Insights: worked out)."""
    sub = (_state.get("plan_sub") or {}).get(pid) or "plan"
    summ = teams().get(pid)
    out = {"sub": sub, "on": summ is not None, "unread": T.unread(summ, _seen(pid)) if summ else 0, "summary": summ}
    if sub == "team":
        tv = (_state.get("team_view") or {}).get(pid) or {}
        out["team"] = tv.get("data")
        out["team_state"] = tv.get("state") or "loading"
        out["draft"] = (_state.get("team_draft") or {}).get(pid) or ""
        out["known"] = _known(tv.get("data"))
        out["me"] = client().user_id
    elif sub == "ins":
        out["insights"] = insights(pid)
    return out


def _known(view):
    """The card questions' guids that I have down, and those I have at all."""
    asks = [a for a in ((view or {}).get("asks") or []) if a.get("guid")]
    if not asks or not mw.col:
        return {"down": [], "have": []}
    try:
        from .cards import i_know
        from .together import notes_by_guid
        guids = [a["guid"] for a in asks]
        return {"down": sorted(i_know(mw.col, guids)), "have": sorted(notes_by_guid(mw.col, guids))}
    except Exception:
        traceback.print_exc()
        return {"down": [], "have": []}


# ---- the team: fetch, join, leave ----

def fetch(pid, force=False):
    """The team as its tab shows it: one request, at most once a minute
    unless something changed it."""
    views = _state.setdefault("team_view", {})
    have = views.get(pid) or {}
    if not force and have.get("data") is not None and time.time() - float(have.get("at") or 0) < FRESH:
        return
    if have.get("busy"):
        if force:
            views[pid] = dict(have, again=True)  # one more when this one lands: it may predate the change
        return
    views[pid] = dict(have, busy=True, state="fetching" if have.get("data") is None else have.get("state") or "ok")
    gen, cl, wk = app.generation, client(), _wk()

    def job():
        try:
            return cl.team(pid, wk)
        except TransportError:
            return False

    def done(data):
        if gen != app.generation:
            return
        again = (views.get(pid) or {}).get("again")
        if data is None or data is False:
            views[pid] = dict(views.get(pid) or {}, busy=False, again=False,
                              state="failed" if (views.get(pid) or {}).get("data") is None else "ok")
        else:
            views[pid] = {"at": time.time(), "data": data, "state": "ok"}
            if data.get("on"):
                _mark_seen(pid, data)
                _seed_card(data)
            else:
                (client().session.get("teams") or {}).pop(pid, None)
        app.swap(cfg())
        if again:
            fetch(pid, force=True)
    _bg(job, done)


def _seed_card(data):
    """The week's squares, from the team's card, for someone in no squad who
    joined since the day's first refresh: their squares count from the next
    sync, not tomorrow's. A squad's own card is never replaced (its middle
    is the squad's)."""
    b = data.get("bingo")
    cl = client()
    if b and not cl.session.get("bingo"):
        cl.session["bingo"] = dict(b["card"], middle=dict(b["card"]["middle"]))


def _mark_seen(pid, data):
    newest = max([int(a.get("act") or 0) for a in data.get("asks") or []] + [0])
    if newest > _seen(pid):
        pf = _plans_flow()
        pc = pf._pcfg()
        pc.setdefault("team_seen", {})[pid] = newest
        pf._psave(pc)


def show(pid, sub):
    """Plan, Team or Insights on the plan's card."""
    if sub not in ("plan", "team", "ins") or not _plan(pid):
        return
    _state.setdefault("plan_sub", {})[pid] = sub
    if sub == "ins":
        _state.setdefault("insights", {}).pop(pid, None)  # worked out again when opened
    app.swap(cfg())
    if sub == "team":
        fetch(pid)


def join(pid):
    gen, cl, wk = app.generation, client(), _wk()

    def done(data):
        if gen != app.generation:
            return
        if not isinstance(data, dict):
            tooltip("This team is full." if data == 409 else "Couldn't join just now.")
            return
        _state.setdefault("team_view", {})[pid] = {"at": time.time(), "data": data, "state": "ok"}
        app.swap(cfg())
        app.sync(light=True)  # today's showed-up goes now, not at the next sync
    _bg(lambda: cl.team_join(pid, wk), done)


def leave(pid, ask=True):
    from aqt.utils import askUser
    if ask and not askUser("Leave the team? Your progress stops counting for the plan's authors; "
                           "your questions and answers stay."):
        return
    gen, cl = app.generation, client()

    def done(ok):
        if gen != app.generation:
            return
        if not ok:
            tooltip("Couldn't leave just now.")
            return
        _state.setdefault("team_view", {})[pid] = {"at": time.time(), "data": {"on": False, "count": 0}, "state": "ok"}
        if ask:
            fetch(pid, force=True)
        else:
            app.swap(cfg())  # No thanks: the ask goes, nothing to fetch
    _bg(lambda: cl.team_leave(pid), done)


# ---- asking and answering ----

def _after(pid, msg_ok=None):
    gen = app.generation

    def done(status):
        if gen != app.generation:
            return
        if status == 200 or status is True:
            if msg_ok:
                tooltip(msg_ok)
            _state.setdefault("team_draft", {}).pop(pid, None)
            fetch(pid, force=True)
        elif status == 429:
            tooltip("That's a lot of questions today. Try again tomorrow.")
        elif status == 403:
            tooltip("Join the team first.")
        else:
            tooltip("Couldn't send it just now.")
    return done


def _send(job):
    def run():
        try:
            return job()
        except TransportError as e:
            return getattr(e, "status", None) or 0
    return run


def ask(pid, raw):
    text = " ".join(unquote(raw or "").split())[:280]
    if not text:
        return
    cl = client()
    _bg(_send(lambda: cl.team_ask(pid, text)), _after(pid))


def reply(pid, ask_id):
    from aqt.qt import QInputDialog, QLineEdit
    text, ok = QInputDialog.getText(mw, "Reply", "Your answer:", QLineEdit.EchoMode.Normal, "")
    text = " ".join(str(text or "").split())[:280]
    if not ok or not text:
        return
    cl = client()
    _bg(_send(lambda: cl.team_ask(pid, text, parent=int(ask_id))), _after(pid))


def _ask_by_id(pid, ask_id):
    data = ((_state.get("team_view") or {}).get(pid) or {}).get("data") or {}
    for a in data.get("asks") or []:
        if a["id"] == int(ask_id):
            return a, None
        for r in a.get("replies") or []:
            if r["id"] == int(ask_id):
                return r, a
    return None, None


def helped(pid, ask_id):
    r, parent = _ask_by_id(pid, ask_id)
    if not r or not parent or not parent.get("mine"):
        return
    cl, on = client(), not r.get("helped")
    _bg(_send(lambda: cl.team_helped(pid, r["id"], on)), _after(pid))


def remove(pid, ask_id):
    from aqt.utils import askUser
    a, parent = _ask_by_id(pid, ask_id)
    if not a or not a.get("remove"):
        return
    if not askUser("Remove this answer?" if parent else "Remove this question, and its answers?"):
        return
    cl = client()
    _bg(_send(lambda: cl.team_remove(pid, a["id"])), _after(pid))


def report(pid, ask_id):
    a, _parent = _ask_by_id(pid, ask_id)
    if not a or a.get("mine") or not a.get("uid"):
        return
    from .social import _report
    _report(a["uid"], a.get("name") or "?")  # mutes them too: their words go from my view


def see_card(pid, ask_id):
    """Anki's browser on the card a question is about, in my copy."""
    a, _parent = _ask_by_id(pid, ask_id)
    if not a or not a.get("guid") or not mw.col:
        return
    nid = mw.col.db.scalar("SELECT id FROM notes WHERE guid = ?", a["guid"])
    if not nid:
        tooltip("That card isn't in your collection.")
        return
    cid = mw.col.db.scalar("SELECT id FROM cards WHERE nid = ? AND ord = ?", nid, int(a.get("ord") or 0)) or 0
    import aqt
    browser = aqt.dialogs.open("Browser", mw)
    browser.search_for(f"cid:{cid}" if cid else f"nid:{nid}")


def ask_card(card):
    """The reviewer's "Ask the team about this card…": a question with the
    card as its guid and number (never its text), on the team of the plan
    whose deck the card is in."""
    pid = plan_for_card(card)
    if not pid:
        return
    from aqt.qt import QInputDialog, QLineEdit
    text, ok = QInputDialog.getText(mw, "Ask the team", "Your question about this card:", QLineEdit.EchoMode.Normal, "")
    text = " ".join(str(text or "").split())[:280]
    if not ok or not text:
        return
    note = card.note()
    topic = ""
    p = _plan(pid)
    if p:
        tags = {t.lower() for t in note.tags}
        for _key, name, _res, ptags, _uids in T.topic_list(p["doc"]):
            if any(t.lower() in tags or any(x.startswith(t.lower() + "::") for x in tags) for t in ptags):
                topic = name
                break
    cl, guid, ordn = client(), note.guid, int(card.ord)
    _bg(_send(lambda: cl.team_ask(pid, text, guid=guid, ord=ordn, topic=topic)), _after(pid, "Asked the team."))


def plan_for_card(card):
    """The plan (on whose team I am) whose deck holds this card, or None."""
    if not card or not teams():
        return None
    did = int(card.odid or card.did)
    for pid in teams():
        if did in _deck_ids(pid):
            return pid
    return None


# ---- team bingo ----

def bingo_view(pid):
    """What board.bingo_html draws for the plan's team card, or None."""
    data = ((_state.get("team_view") or {}).get(pid) or {}).get("data") or {}
    b = data.get("bingo")
    if not b:
        return None
    mine = _state.get("bingo_mine") or {}  # my squares, as the sync worked them out
    p = _plan(pid)
    return {"card": b["card"], "ev": b["ev"], "progress": mine.get("progress") if mine.get("wk") == b["card"]["wk"] else None,
            "me": client().user_id, "names": {}, "squad": (p or {}).get("name") or "", "team": True,
            "closest": T.closest(b["card"], b["ev"]), "withheld": [], "today": _state["labels"][0] if _state["labels"] else ""}


def open_bingo(pid, on=True):
    _state["team_bingo_open"] = pid if on else None
    app.swap(cfg())
    if on:
        fetch(pid, force=True)


# ---- Insights ----

def insights(pid):
    """The table, worked out at most every ten minutes. Main thread."""
    have = (_state.get("insights") or {}).get(pid)
    if have and time.time() - have["at"] < INSIGHTS_FRESH:
        return have["rows"]
    rows = []
    try:
        rows = _work_out(pid)
    except Exception:
        traceback.print_exc()
    _state.setdefault("insights", {})[pid] = {"at": time.time(), "rows": rows}
    return rows


def _work_out(pid):
    p = _plan(pid)
    pf = _plans_flow()
    st = pf._state_cfg().get(pid)
    if not p or not st or not mw.col or not pf._deck_ok(mw.col, st.get("deck_id")):
        return []
    idx = P.DeckIndex(mw.col, st["deck_id"])
    swap = pf._swap(st)
    topics = T.topic_list(p["doc"])
    if not topics:
        return []
    dids = ",".join(str(d) for d in _deck_ids(pid)) or "0"
    cutoff = int(mw.col.sched.day_cutoff)
    # review and relearning answers (learning steps aren't a slip), 28 days
    answers = mw.col.db.all(
        f"SELECT r.cid, CAST((? - r.id / 1000) / 86400 AS INTEGER), r.ease FROM revlog r "
        f"WHERE r.id >= ? AND r.ease > 0 AND r.type IN (1, 2) "
        f"AND r.cid IN (SELECT id FROM cards WHERE did IN ({dids}) OR odid IN ({dids}))",
        cutoff - 1, (cutoff - 2 * T.DAYS * 86400) * 1000)
    units = {u["id"]: u for u in P.units(p["doc"])}
    return T.insights(topics, lambda t: idx.tag_cards(P.swapped(t, swap)), answers,
                      todo_of=lambda uid: (units.get(uid) or {}).get("todo"))


def _row(pid, i):
    """A row of the table on screen, by its place."""
    rows = ((_state.get("insights") or {}).get(pid) or {}).get("rows") or []
    return rows[int(i)] if str(i).isdigit() and int(i) < len(rows) else None


def study(pid, key):
    """Anki's filtered deck of the cards I missed in that topic, and into it."""
    r = _row(pid, key)
    if not r or not r["cids"] or not mw.col:
        return
    pf = _plans_flow()
    name = pf._deck_name(f"Due Crew · {r['name']}")
    if pf._filtered(mw.col, name, r["cids"]):
        pf._after_change()
        did = mw.col.decks.id_for_name(name)
        if did:
            mw.col.decks.select(did)
            mw.moveToState("overview")


def rewatch(pid, key):
    r = _row(pid, key)
    if r and r["url"].startswith("https://"):
        from aqt.utils import openLink
        openLink(r["url"])


def ask_about(pid, key):
    """Insights' Ask: Team, with the topic in the box."""
    r = _row(pid, key)
    if not r:
        return
    _state.setdefault("team_draft", {})[pid] = f"{r['name']}: "
    show(pid, "team")


# ---- the sync ----

def for_sync(c):
    """{plan id: {days?, play?}} for the teams I'm on: the days of the last
    eight I answered one of the plan's cards (reviews from a phone arrive
    here only with the AnkiWeb sync, so a day can come late), and my week's
    play, the same as on my squad rows. None when I'm on no team (or paused). Main thread."""
    if not teams() or not mw.col or c.get("paused"):
        return None
    from . import bingo_flow
    from .stats.queries import StatsQueries
    q = StatsQueries(mw.col)
    cutoff = int(mw.col.sched.day_cutoff)
    out = {}
    play = bingo_flow.my_play(c)  # the same play as my squad rows: one square, stamped everywhere
    for pid in list(teams())[:20]:
        dids = _deck_ids(pid)
        if not dids:
            continue
        ids = ",".join(str(d) for d in dids)
        part = {}
        agos = mw.col.db.list(
            f"SELECT DISTINCT CAST((? - id / 1000) / 86400 AS INTEGER) FROM revlog WHERE id >= ? AND id < ? AND ease > 0 "
            f"AND cid IN (SELECT id FROM cards WHERE did IN ({ids}) OR odid IN ({ids}))",
            cutoff - 1, (cutoff - 8 * 86400) * 1000, cutoff * 1000)
        if agos:
            part["days"] = sorted(q.day_label(int(a)) for a in agos)
        if play:
            part["play"] = play
        if part:
            out[pid] = part
    return out or None


# ---- the board's commands ----

def on_message(cmd, parts):
    """The plan tabs' commands (plansub, the team's and Insights'): True when handled."""
    arg = parts[2] if len(parts) > 2 else ""
    x = parts[3] if len(parts) > 3 else ""
    if cmd == "plansub" and arg and x:
        show(arg, x)
    elif cmd == "planteamjoin" and arg:
        join(arg)
    elif cmd == "planteamleave" and arg:
        leave(arg)
    elif cmd == "planteamno" and arg:
        leave(arg, ask=False)  # 3.7.6: No thanks to the one-time ask
    elif cmd == "planteamask" and arg:
        ask(arg, ":".join(parts[3:]))
    elif cmd == "planteamreply" and arg and x.isdigit():
        reply(arg, x)
    elif cmd == "planteamhelped" and arg and x.isdigit():
        helped(arg, x)
    elif cmd == "planteamremove" and arg and x.isdigit():
        remove(arg, x)
    elif cmd == "planteamreport" and arg and x.isdigit():
        report(arg, x)
    elif cmd == "planteamcard" and arg and x.isdigit():
        see_card(arg, x)
    elif cmd == "planteamretry" and arg:
        fetch(arg, force=True)
    elif cmd == "planteambingo" and arg:
        open_bingo(arg)
    elif cmd == "planteambingoback":
        open_bingo(None, on=False)
    elif cmd == "planinsstudy" and arg and x.isdigit():
        study(arg, x)
    elif cmd == "planinswatch" and arg and x.isdigit():
        rewatch(arg, x)
    elif cmd == "planinsask" and arg and x.isdigit():
        ask_about(arg, x)
    else:
        return False
    return True
