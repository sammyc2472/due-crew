"""3.7.3 a plan's team and its Insights, the glue (team.py is pure).

The Plans tab's plan card has three tabs: Plan, Team and Insights
(`_state["plan_sub"]`, per session). Team is opt-in per plan: joining
shares that I showed up today (answered one of the plan's cards), my
questions and answers, and my bingo squares (the same play as on my squad
rows: the week's one card); never a number. The board's refresh carries a few counts
(`session["teams"]`); the tab itself is one request when it opens, and each
click is one more. Showed-up days and squares ride the sync (`for_sync`).

Insights are mine alone (3.7.9): worked out here from my reviews of the
plan's cards and Anki's own memory model, never sent. Study builds Anki's
filtered deck of the hero's cards or a topic's; Optimize FSRS opens the
deck's options; the line can be put away for 30 days."""

import datetime
import json
import time
import traceback
from urllib.parse import unquote

from aqt import mw
from aqt.utils import tooltip

from . import app
from . import plans as P
from . import schedule as S
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
    """What the Insights tab draws, worked out at most every ten minutes. Main thread."""
    have = (_state.get("insights") or {}).get(pid)
    if have and time.time() - have["at"] < INSIGHTS_FRESH:
        return have["view"]
    view = {}
    try:
        view = _work_out(pid)
    except Exception:
        traceback.print_exc()
    _state.setdefault("insights", {})[pid] = {"at": time.time(), "view": view}
    return view


def _in(ids):
    return ",".join(str(int(c)) for c in ids) or "0"


def _target(col, did):
    try:
        return float(col.decks.config_dict_for_deck_id(did).get("desiredRetention") or 0.9)
    except Exception:
        return 0.9


def _fsrs(col):
    try:
        return bool(col.get_config("fsrs", False))
    except Exception:
        return False


def _work_out(pid):
    p = _plan(pid)
    pf = _plans_flow()
    st = pf._state_cfg().get(pid)
    col = mw.col
    if not p or not st or not col or not pf._deck_ok(col, st.get("deck_id")):
        return {}
    did = int(st["deck_id"])
    idx = P.DeckIndex(col, did)
    swap = pf._swap(st)
    doc = p["doc"]
    today = pf._today()
    cutoff = int(col.sched.day_cutoff)
    sday = int(getattr(col.sched, "today", 0) or 0)
    target = _target(col, did)
    deck = _in(idx.cards)
    since = lambda days: (cutoff - days * 86400) * 1000  # noqa: E731
    out = {"target": int(round(100 * target))}

    # the header: right on this deck's reviews, first answer of each card each day
    out["right"] = T.right_days(col.db.all(
        f"SELECT cid, CAST((? - id / 1000) / 86400 AS INTEGER), ease FROM revlog "
        f"WHERE id >= ? AND type = 1 AND ease > 0 AND cid IN ({deck}) ORDER BY id", cutoff - 1, since(2 * T.DAYS)))

    # the plan's own cards, and what each date asks of me (plans.load)
    ms = P.unit_matches(idx, doc, swap)
    plan = set()
    for v in ms.values():
        plan |= set(v)
    ld = P.load(idx, doc, swap)
    units = P.units(doc)

    # the hero: started cards Anki won't show me before the aim, under my target by then (FSRS only).
    # The dates that prep for the event, when it has some (its name on the box); else the
    # whole plan, and the box goes by the day
    day, name, k, eid = T.aim(doc.get("events"), today)
    prep = T.prep_units(units, eid)
    aimed = plan
    if prep:
        aimed = set()
        for uid in prep:
            aimed |= set(ms.get(uid) or ())
    out["aim"] = {"day": day, "name": name, "in": k, "scoped": bool(prep)}
    if _fsrs(col) and aimed and sday:
        last = dict(col.db.all(f"SELECT cid, max(id) FROM revlog WHERE cid IN ({_in(aimed)}) GROUP BY cid"))
        cards = {}
        for cid, ctype, queue, due, ivl, data in col.db.all(
                f"SELECT id, type, queue, due, ivl, data FROM cards WHERE id IN ({_in(aimed)}) AND type != 0 AND queue != -1"):
            if cid not in last:
                continue
            try:
                mem = json.loads(data or "{}")
            except ValueError:
                mem = {}
            s = float(mem.get("s") or max(int(ivl), 1))
            ago = (cutoff - int(last[cid]) // 1000) // 86400
            shown = queue in (1, 3, 4) or (queue == 2 and int(due) - sday < k)
            cards[cid] = (T.recall(ago + k, s, mem.get("decay")), shown)
        out["hero"] = T.hero(cards, target)

    # not sticking yet: this window's reviews, never right yet, or forgotten after being right
    reviewed, miss_last = set(), {}
    for cid, rid, ease in col.db.all(f"SELECT cid, id, ease FROM revlog WHERE id >= ? AND type IN (1, 2) AND ease > 0 "
                                     f"AND cid IN ({deck})", since(T.DAYS)):
        reviewed.add(cid)
        if ease == 1:
            miss_last[cid] = max(miss_last.get(cid, 0), rid)
    first_right = dict(col.db.all(f"SELECT cid, min(id) FROM revlog WHERE type = 1 AND ease > 1 AND cid IN ({_in(reviewed)}) "
                                  f"GROUP BY cid")) if reviewed else {}
    stuck = reviewed - set(first_right)
    forgot = {c for c, m in miss_last.items() if c in first_right and first_right[c] < m}
    out["rows"] = T.not_sticking(T.topic_list(doc), lambda t: idx.tag_cards(P.swapped(t, swap)), reviewed, stuck, forgot)

    # behind on the plan (the Plan tab's Catch up; nothing while a catch-up runs)
    catch = st.get("catch") if str((st.get("catch") or {}).get("until") or "") >= today else None
    out["behind"] = 0 if catch else sum(sum((ld.get(u["id"]) or [0, 0, 0])[1:]) for u in units
                                       if str(u.get("opens") or "") < today)

    # my week in minutes, at my own pace in this deck
    t = S.d(today)
    days = [S.iso(t + datetime.timedelta(days=i)) for i in range(7)]
    new = {d: 0 for d in days}
    for u in units:
        o = str(u.get("opens") or "")
        if o in new:
            sn, op, lk = ld.get(u["id"]) or [0, 0, 0]
            new[o] += (op + lk) if o == today else lk
    due = {i: 0 for i in range(7)}
    if sday:
        for (dd,) in col.db.all(f"SELECT due FROM cards WHERE id IN ({deck}) AND queue = 2"):
            i = max(int(dd) - sday, 0)
            if i < 7:
                due[i] += 1
    n_ans, ms_ans = col.db.first(f"SELECT count(), total(time) FROM revlog WHERE id >= ? AND type IN (1, 2) AND ease > 0 "
                                 f"AND cid IN ({deck})", since(T.DAYS)) or (0, 0)
    firsts = dict(col.db.all(f"SELECT cid, min(id) FROM revlog WHERE cid IN ({deck}) GROUP BY cid "
                             f"HAVING min(id) >= ? AND min(id) < ?", since(28), since(7)))
    secs_new = None
    if len(firsts) >= T.NEW_MIN:
        spent = 0
        for cid, rid, ms_ in col.db.all(f"SELECT cid, id, time FROM revlog WHERE ease > 0 AND cid IN ({_in(firsts)})"):
            if 0 <= rid - firsts[cid] < 7 * 86400 * 1000:
                spent += ms_
        secs_new = spent / 1000.0 / len(firsts)
    past = col.db.all(f"SELECT CAST((? - id / 1000) / 86400 AS INTEGER), total(time) FROM revlog "
                      f"WHERE id >= ? AND ease > 0 AND cid IN ({deck}) GROUP BY 1", cutoff - 1, since(7))
    mins = {int(a): int(round(m / 60000.0)) for a, m in past}
    out["week"] = T.week([(S.iso(t - datetime.timedelta(days=a)), mins.get(a, 0)) for a in range(7, 0, -1)],
                         [(d, new[d], due[i]) for i, d in enumerate(days)],
                         secs_new, (ms_ans / 1000.0 / n_ans) if n_ans >= 200 else None)
    if out["week"]:
        out["week"]["today_done"] = mins.get(0, 0)

    # Optimize FSRS: my newest cards against my target (put away for 30 days)
    hide = float((pf._pcfg().get("ins_fsrs_hide") or 0))
    if _fsrs(col) and time.time() - hide > T.HIDE_DAYS * 86400:
        try:
            right, n = col.db.first(f"SELECT total(ease > 1), count() FROM revlog WHERE id >= ? AND type = 1 AND ease > 0 "
                                    f"AND lastIvl BETWEEN 1 AND 3 AND cid IN ({deck})", since(28)) or (0, 0)
            out["fsrs"] = T.fsrs_gap(int(right or 0), int(n or 0), target)
        except Exception:
            traceback.print_exc()
    return out


def study(pid, key):
    """Anki's filtered deck of the hero's cards ("h") or a topic's, and into it."""
    view = ((_state.get("insights") or {}).get(pid) or {}).get("view") or {}
    if key == "h":
        cids, aim = view.get("hero") or [], view.get("aim") or {}
        if aim.get("scoped") and aim.get("name"):
            title = f"Before {aim['name']}"
        else:
            try:
                d = datetime.date.fromisoformat(str(aim.get("day")))
                title = f"Before {d:%a} {d.day}"
            except ValueError:
                title = "This week"
    else:
        rows = view.get("rows") or []
        r = rows[int(key)] if str(key).isdigit() and int(key) < len(rows) else None
        cids, title = (r["cids"], r["name"]) if r else ([], "")
    if not cids or not mw.col:
        return
    pf = _plans_flow()
    name = pf._deck_name(f"Due Crew · {title}")
    if pf._filtered(mw.col, name, cids):
        pf._after_change()
        did = mw.col.decks.id_for_name(name)
        if did:
            mw.col.decks.select(did)
            mw.moveToState("overview")


def fsrs(pid, open_it=True):
    """Optimize FSRS: the plan deck's options (Anki's own button is there),
    or the line put away for 30 days."""
    pf = _plans_flow()
    if not open_it:
        pc = pf._pcfg()
        pc["ins_fsrs_hide"] = int(time.time())
        pf._psave(pc)
        _state.setdefault("insights", {}).pop(pid, None)
        app.swap(cfg())
        return
    st = pf._state_cfg().get(pid)
    if st and mw.col and pf._deck_ok(mw.col, st.get("deck_id")):
        try:
            from aqt.deckoptions import display_options_for_deck_id
            display_options_for_deck_id(int(st["deck_id"]))
        except Exception:
            traceback.print_exc()


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
    elif cmd == "planinsstudy" and arg and (x.isdigit() or x == "h"):
        study(arg, x)
    elif cmd == "planinsfsrs" and arg:
        fsrs(arg)
    elif cmd == "planinsfsrsno" and arg:
        fsrs(arg, open_it=False)
    else:
        return False
    return True
