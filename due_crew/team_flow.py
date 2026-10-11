"""3.7.3 a plan's squad (its team, until 3.8.0) and Insights, the glue
(team.py is pure).

3.8.0: Insights is the You bubble's own tab, a deck's (see below), and
the plan's squad lives on the Squads tab, a pill beside my own squads
(`plan_squads`, picked as `cfg["squad"] = "plan:<id>"`), and the plan card
says how many showed up with a way there. It's opt-in per plan: joining
shares that I showed up today (answered one of the plan's cards), my
questions and answers, and my bingo squares (the same play as on my squad
rows: the week's one card); never a number. The board's refresh carries a few counts
(`session["teams"]`); the squad itself is one request when it opens, and
each click is one more. Showed-up days and squares ride the sync
(`for_sync`). The server still calls it a team (/plans/<id>/team).

Insights are mine alone (3.7.9): worked out here from my reviews of a
deck's cards and Anki's own memory model, never sent. Study builds Anki's
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
from .app import _bg, _state, cfg, client, save_cfg
from .backend.shapes import TransportError

FRESH = 60          # seconds a fetched team is shown before the tab asks again
INSIGHTS_FRESH = 600


def _plans_flow():
    from . import plan_flow
    return plan_flow


def teams():
    return client().session.get("teams") or {}


def _plan(pid):
    return next((p for p in _plans_flow().followed() if p.get("id") == pid), None)


PICK = "plan:"  # cfg["squad"] holds this and the plan's id when its squad is the one on screen


def plan_squads():
    """3.8.0: the squads of the plans I follow and am in, as the Squads
    tab's pills: [{id, pid, name, unread}]. A plan's squad is named for it."""
    on = teams()
    if not on:
        return []
    return [{"id": PICK + p["id"], "pid": p["id"], "name": str(p.get("name") or "Plan"),
             "unread": T.unread(on[p["id"]], _seen(p["id"]))}
            for p in _plans_flow().followed() if p.get("id") in on]


def picked(c, ps=None):
    """The plan squad the Squads tab shows, or None for one of my own: the
    one picked, or the first when I have no squad of my own."""
    ps = plan_squads() if ps is None else ps
    if not ps:
        return None
    sel = str(c.get("squad") or "")
    hit = next((q for q in ps if q["id"] == sel), None)
    if hit or any(isinstance(q, dict) and q.get("id") for q in c.get("squads") or []):
        return hit
    return ps[0]


def squad_view(c, ps=None):
    """What board._plan_squad_html draws when a plan's squad is picked, or None."""
    hit = picked(c, ps)
    if not hit:
        return None
    pid = hit["pid"]
    tv = (_state.get("team_view") or {}).get(pid) or {}
    return {"kind": "plan", "pid": pid, "name": hit["name"], "current": hit["id"],
            "team": tv.get("data"), "team_state": tv.get("state") or "loading",
            "draft": (_state.get("team_draft") or {}).get(pid) or "",
            "known": _known(tv.get("data")), "me": client().user_id}


def open_squad(pid):
    """The plan's squad on the Squads tab: its pill, and the plan card's Open."""
    if pid not in teams() or not _plan(pid):
        return
    c = cfg()
    from .board import hidden_tabs
    if "squads" in hidden_tabs(c):
        tooltip("The Squads tab is hidden. Settings brings it back.")
        return
    c["squad"], c["period"] = PICK + pid, "squads"
    save_cfg(c)
    _state["bingo_open"], _state["team_bingo_open"] = False, None
    app.swap(c)
    fetch(pid)


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
    """For the plan's card: the squad line's counts (3.8.0: the squad itself
    is on the Squads tab; Insights is the You bubble's own tab)."""
    summ = teams().get(pid)
    return {"on": summ is not None, "unread": T.unread(summ, _seen(pid)) if summ else 0, "summary": summ}


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
    """The plan's squad as the Squads tab shows it: one request, at most
    once a minute unless something changed it."""
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


JOIN_SAYS = ("The others in it see your name and the days you show up, and your questions and answers; "
             "your progress counts for the plan's authors. Never your numbers.")


def join(pid, ask=False):
    """ask: from the plan card's "Join its squad", which says what it shares
    first (the one-time ask and the Follow dialog already said it)."""
    if ask:
        from aqt.utils import askUser
        if not askUser("Join this plan's squad? " + JOIN_SAYS):
            return
    gen, cl, wk = app.generation, client(), _wk()

    def done(data):
        if gen != app.generation:
            return
        if not isinstance(data, dict):
            tooltip("This squad is full." if data == 409 else "Couldn't join just now.")
            return
        _state.setdefault("team_view", {})[pid] = {"at": time.time(), "data": data, "state": "ok"}
        if data.get("on") and pid not in teams():
            # its pill and the plan card's line now, not at the next refresh
            cl.session["teams"] = dict(cl.session.get("teams") or {}, **{pid: {
                "shown": int(data.get("shown") or 0), "of": int(data.get("count") or 1), "faces": [], "act": [], "last": None}})
        app.swap(cfg())
        if ask:
            tooltip("You're in. It's on the Squads tab.")
        app.sync(light=True)  # today's showed-up goes now, not at the next sync
    _bg(lambda: cl.team_join(pid, wk), done)


def leave(pid, ask=True):
    from aqt.utils import askUser
    if ask and not askUser("Leave this plan's squad? Your progress stops counting for its authors; "
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
        (cl.session.get("teams") or {}).pop(pid, None)  # its pill goes now
        c = cfg()
        if c.get("squad") == PICK + pid:
            c["squad"] = ""
            save_cfg(c)
        _state["team_bingo_open"] = None
        app.swap(c)
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
            tooltip("Join its squad first.")
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
    """The reviewer's "Ask the squad about this card…": a question with the
    card as its guid and number (never its text), in the squad of the plan
    whose deck the card is in."""
    pid = plan_for_card(card)
    if not pid:
        return
    from aqt.qt import QInputDialog, QLineEdit
    text, ok = QInputDialog.getText(mw, "Ask the squad", "Your question about this card:", QLineEdit.EchoMode.Normal, "")
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
    _bg(_send(lambda: cl.team_ask(pid, text, guid=guid, ord=ordn, topic=topic)), _after(pid, "Asked the squad."))


def plan_for_card(card):
    """The plan (whose squad I'm in) whose deck holds this card, or None."""
    if not card or not teams():
        return None
    did = int(card.odid or card.did)
    for pid in teams():
        if did in _deck_ids(pid):
            return pid
    return None


# ---- the plan squad's bingo ----

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


# ---- Insights (3.8.0: a deck's, for everyone, on the You bubble) ----
#
# A deck at a time (you_decks), picked as a squad is. A plan I follow that
# runs on the deck brings its exam (its next event, over its prep dates) and
# its topic names; without one the deck's own tags name the topics and my
# own exam date (Settings) aims the exam box. Mine alone: worked out here,
# never sent, at most every INSIGHTS_FRESH seconds a deck.

DECKS_MAX = 5


def _since(col, days):
    return (int(col.sched.day_cutoff) - days * 86400) * 1000


def you_decks():
    """[{did, name, full, pid}] as Insights' picker shows them: the decks of
    the plans I follow here first, then the deck I picked last (from Crew ›
    Decks, say), then the top-level decks I've reviewed most in two weeks;
    DECKS_MAX at most. Main thread."""
    have = _state.get("you_decks")
    if have and time.time() - have["at"] < INSIGHTS_FRESH:
        return have["list"]
    out = []
    if mw.col:
        try:
            out = _you_decks(mw.col, int(cfg().get("ins_deck") or 0))
        except Exception:
            traceback.print_exc()
    _state["you_decks"] = {"at": time.time(), "list": out}
    return out


def _you_decks(col, picked=0):
    pf = _plans_flow()
    state = pf._state_cfg()
    out, seen = [], set()

    def add(did, pid=None):
        did = int(did)
        if did in seen or len(out) >= DECKS_MAX or not col.decks.get(did, default=False):
            return
        full = str(col.decks.name(did) or "")
        seen.add(did)
        out.append({"did": did, "name": full.split("::")[-1] or full, "full": full, "pid": pid})
    for p in pf.followed():
        st = state.get(p["id"])
        if st and pf._deck_ok(col, st.get("deck_id")):
            add(st["deck_id"], p["id"])
    if picked:
        add(picked)
    roots = {}
    for did, n in col.db.all("SELECT CASE WHEN c.odid THEN c.odid ELSE c.did END, count() FROM revlog r "
                             "JOIN cards c ON c.id = r.cid WHERE r.id >= ? AND r.ease > 0 GROUP BY 1", _since(col, T.DAYS)):
        if not col.decks.get(int(did), default=False):
            continue
        root = str(col.decks.name(int(did)) or "").split("::")[0]
        if root:
            roots[root] = roots.get(root, 0) + int(n)
    for root, _n in sorted(roots.items(), key=lambda x: (-x[1], x[0].lower())):
        rid = col.decks.id_for_name(root)
        if rid:
            add(rid)
    return out


def you_view(c):
    """What You › Insights draws: {decks, did, plan, exam (my date, or ""), view}. The deck
    picked (cfg ins_deck, this computer's) or the first. Main thread."""
    decks = you_decks()
    if not decks:
        return {"decks": []}
    did = int(c.get("ins_deck") or 0)
    d = next((x for x in decks if x["did"] == did), decks[0])
    p = _plan(d["pid"]) if d.get("pid") else None
    exam = str(c.get("exam_date") or "")
    return {"decks": decks, "did": d["did"], "exam": exam,
            "plan": {"id": p["id"], "name": P.plan_title(p)} if p else None,
            "view": insights(d["did"], p["id"] if p else None, exam)}


def plan_lines(cards):
    """3.8.0, You › Plans: each plan's line from Insights (the next exam's
    cards at risk), card["ins"] = {n, did, name, day}. Main thread."""
    pf = _plans_flow()
    state = pf._state_cfg()
    for card in cards or []:
        st = state.get(card.get("id"))
        if card.get("paused") or not st or not mw.col or not pf._deck_ok(mw.col, st.get("deck_id")):
            continue
        did = int(st["deck_id"])
        v = insights(did, card["id"], "")
        aim = v.get("aim") or {}
        if v.get("hero"):
            card["ins"] = {"n": len(v["hero"]), "did": did, "day": aim.get("day"),
                           "name": aim.get("name") if aim.get("scoped") else ""}


def insights(did, pid=None, exam=""):
    """A deck's Insights, worked out at most every INSIGHTS_FRESH seconds
    (again when the plan or the exam date changes). Main thread."""
    key = f"{pid or ''}|{exam}"
    have = (_state.get("insights") or {}).get(did)
    if have and have.get("key") == key and time.time() - have["at"] < INSIGHTS_FRESH:
        return have["view"]
    view = {}
    try:
        view = _work_out(int(did), pid, exam)
    except Exception:
        traceback.print_exc()
    _state.setdefault("insights", {})[did] = {"at": time.time(), "view": view, "key": key}
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


def _new_per_day(col, did):
    try:
        return max(0, int(col.decks.config_dict_for_deck_id(did)["new"]["perDay"]))
    except Exception:
        return 0


def _work_out(did, pid=None, exam=""):
    col = mw.col
    if not col or not col.decks.get(did, default=False):
        return {}
    pf = _plans_flow()
    p = _plan(pid) if pid else None
    st = pf._state_cfg().get(pid) if p else None
    if p and not (st and pf._deck_ok(col, st.get("deck_id")) and int(st["deck_id"]) == did):
        p = st = None  # the plan moved to another deck: this deck's own Insights
    today = pf._today()
    cutoff = int(col.sched.day_cutoff)
    sday = int(getattr(col.sched, "today", 0) or 0)
    target = _target(col, did)
    if p:
        idx = P.DeckIndex(col, did)
        swap, doc = pf._swap(st), p["doc"]
        deck = _in(idx.cards)
    else:
        deck = _deck_sql(col, did)  # a big shared deck's 30,000 ids stay out of the SQL
    since = lambda days: (cutoff - days * 86400) * 1000  # noqa: E731
    out = {"target": int(round(100 * target)), "did": did}

    # the header: right on this deck's reviews, first answer of each card each day
    out["right"] = T.right_days(col.db.all(
        f"SELECT cid, CAST((? - id / 1000) / 86400 AS INTEGER), ease FROM revlog "
        f"WHERE id >= ? AND type = 1 AND ease > 0 AND cid IN ({deck}) ORDER BY id", cutoff - 1, since(2 * T.DAYS)))

    # the exam box: started cards Anki won't show me before the aim, under my target by then
    # (FSRS only). A plan aims at its next event (its prep dates' cards when it names them,
    # else all of the plan's), else a week out; with no plan, my own exam date when it's
    # within AIM_DAYS, over the whole deck, else a week out
    if p:
        ms = P.unit_matches(idx, doc, swap)
        plan = set()
        for v in ms.values():
            plan |= set(v)
        ld = P.load(idx, doc, swap)
        units = P.units(doc)
        day, name, k, eid = T.aim(doc.get("events"), today)
        prep = T.prep_units(units, eid)
        aimed = plan
        if prep:
            aimed = set()
            for uid in prep:
                aimed |= set(ms.get(uid) or ())
        out["aim"] = {"day": day, "name": name, "in": k, "scoped": bool(prep)}
        aimed = _in(aimed) if aimed else ""
    else:
        mine = [{"day": exam, "name": "Your exam", "id": "exam"}] if exam else []
        day, name, k, eid = T.aim(mine, today)
        aimed = deck
        out["aim"] = {"day": day, "name": name, "in": k, "scoped": False, "kind": "exam" if eid else ""}
    if _fsrs(col) and aimed and sday:
        last = dict(col.db.all(f"SELECT cid, max(id) FROM revlog WHERE cid IN ({aimed}) GROUP BY cid"))
        mem_of = {}
        for cid, ctype, queue, due, ivl, data in col.db.all(
                f"SELECT id, type, queue, due, ivl, data FROM cards WHERE id IN ({aimed}) AND type != 0 AND queue != -1"):
            if cid not in last:
                continue
            try:
                mem = json.loads(data or "{}")
            except ValueError:
                mem = {}
            s_ = float(mem.get("s") or max(int(ivl), 1))
            ago = (cutoff - int(last[cid]) // 1000) // 86400
            shown = queue in (1, 3, 4) or (queue == 2 and int(due) - sday < k)
            mem_of[cid] = (T.recall(ago + k, s_, mem.get("decay")), shown)
        out["hero"] = T.hero(mem_of, target)

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
    if p:
        out["rows"] = T.not_sticking(T.topic_list(doc), lambda t: idx.tag_cards(P.swapped(t, swap)), reviewed, stuck, forgot)
    else:
        out["rows"] = _deck_rows(col, did, reviewed, stuck, forgot)

    # behind on the plan (its Catch up; nothing while a catch-up runs)
    if p:
        catch = st.get("catch") if str((st.get("catch") or {}).get("until") or "") >= today else None
        out["behind"] = 0 if catch else sum(sum((ld.get(u["id"]) or [0, 0, 0])[1:]) for u in units
                                           if str(u.get("opens") or "") < today)
        out["pid"] = p["id"]

    # my week in minutes, at my own pace in this deck: ahead, what the plan
    # asks, or with no plan, what Anki has due (its new cards a day included)
    t = S.d(today)
    days = [S.iso(t + datetime.timedelta(days=i)) for i in range(7)]
    new = {d: 0 for d in days}
    if p:
        for u in units:
            o = str(u.get("opens") or "")
            if o in new:
                _sn, op, lk = ld.get(u["id"]) or [0, 0, 0]
                new[o] += (op + lk) if o == today else lk
    else:
        left = int(col.db.scalar(f"SELECT count() FROM cards WHERE id IN ({deck}) AND queue = 0") or 0)
        per = _new_per_day(col, did)
        for d in days:
            new[d] = min(per, left)
            left -= new[d]
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
        out["week"]["src"] = "plan" if p else "anki"

    # Optimize FSRS: my newest cards against my target (put away for 30 days)
    hide = float((pf._pcfg().get("ins_fsrs_hide") or 0))
    if _fsrs(col) and time.time() - hide > T.HIDE_DAYS * 86400:
        try:
            right, n = col.db.first(f"SELECT total(ease > 1), count() FROM revlog WHERE id >= ? AND type = 1 AND ease > 0 "
                                    f"AND lastIvl BETWEEN 1 AND 3 AND cid IN ({deck})", since(28)) or (0, 0)
            out["fsrs"] = T.fsrs_gap(int(right or 0), int(n or 0), target)
        except Exception:
            traceback.print_exc()

    # the Hard habit (3.8.0): Hard is a pass; put away for 30 days as Optimize is
    if time.time() - float(pf._pcfg().get("ins_hard_hide") or 0) > T.HIDE_DAYS * 86400:
        try:
            hard, n = col.db.first(f"SELECT total(ease = 2), count() FROM revlog WHERE id >= ? AND type = 1 AND ease > 0 "
                                   f"AND cid IN ({deck})", since(28)) or (0, 0)
            out["hard"] = T.hard_habit(int(hard or 0), int(n or 0))
        except Exception:
            traceback.print_exc()

    # the deck's leeches Anki suspended (from the plan card, 3.8.0)
    out["leeches"] = len(_leeches(col, deck))
    return out


def _deck_sql(col, did):
    """The deck's cards and its subdecks', as SQL to put in IN (...)."""
    dids = _in(col.decks.deck_and_child_ids(did))
    return f"SELECT id FROM cards WHERE did IN ({dids}) OR odid IN ({dids})"


def _leeches(col, deck):
    """The suspended cards tagged leech among `deck` (ids, or _deck_sql, for SQL)."""
    return col.db.list(f"SELECT c.id FROM cards c JOIN notes n ON n.id = c.nid WHERE c.id IN ({deck}) "
                       f"AND c.queue = -1 AND (' ' || lower(n.tags) || ' ') LIKE '% leech %'")


def _deck_rows(col, did, reviewed, stuck, forgot):
    """Not sticking yet with no plan: topics from the deck's tags (T.deck_topics),
    or its subdecks when its cards have no tags to say."""
    if not reviewed:
        return []
    ids = _in(reviewed)
    tags_of = {int(cid): str(tags or "").split() for cid, tags in
               col.db.all(f"SELECT c.id, n.tags FROM cards c JOIN notes n ON n.id = c.nid WHERE c.id IN ({ids})")}
    topics, groups = T.deck_topics(tags_of, reviewed)
    rows = T.not_sticking(topics, lambda t: groups.get(t, ()), reviewed, stuck, forgot)
    if rows:
        return rows
    root = str(col.decks.name(did) or "")
    paths = {}
    for cid, d in col.db.all(f"SELECT id, CASE WHEN odid THEN odid ELSE did END FROM cards WHERE id IN ({ids})"):
        name = str(col.decks.name(int(d)) or "")
        if name.startswith(root + "::"):
            paths[int(cid)] = [name[len(root) + 2:]]
    topics, groups = T.deck_topics(paths, reviewed)
    return T.not_sticking(topics, lambda t: groups.get(t, ()), reviewed, stuck, forgot)


def _pick(did, key):
    """(cids, title) of the exam box ("h") or a topic's row, as Insights shows them."""
    view = ((_state.get("insights") or {}).get(did) or {}).get("view") or {}
    if key == "h":
        cids, aim = view.get("hero") or [], view.get("aim") or {}
        if aim.get("name") and (aim.get("scoped") or aim.get("kind") == "exam"):
            title = f"Before {aim['name']}" if aim.get("scoped") else "Before your exam"
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
    return cids, title


def study(did, key):
    """Anki's filtered deck of the exam box's cards ("h") or a topic's, and into it."""
    cids, title = _pick(did, key)
    if not cids or not mw.col:
        return
    pf = _plans_flow()
    name = pf._deck_name(f"Due Crew · {title}")
    if pf._filtered(mw.col, name, cids):
        pf._after_change()
        fid = mw.col.decks.id_for_name(name)
        if fid:
            mw.col.decks.select(fid)
            mw.moveToState("overview")


def browse(did, key):
    """3.8.0: the same cards in Anki's browser, to look them over or fix them."""
    cids, _title = _pick(did, key)
    if mw.col:
        _plans_flow()._browse(cids, empty="Nothing to show.")


def browse_leeches(did):
    """The deck's suspended leeches in Anki's browser."""
    col = mw.col
    if not col or not col.decks.get(did, default=False):
        return
    _plans_flow()._browse(_leeches(col, _deck_sql(col, did)), empty="No suspended leeches here.")


def fsrs(did, open_it=True):
    """Optimize FSRS: the deck's options (Anki's own button is there), or the
    line put away for 30 days."""
    if not open_it:
        _put_away("ins_fsrs_hide")
        return
    if mw.col and mw.col.decks.get(did, default=False):
        try:
            from aqt.deckoptions import display_options_for_deck_id
            display_options_for_deck_id(int(did))
        except Exception:
            traceback.print_exc()


def pick_deck(did):
    """Insights' picker: a deck of mine, remembered on this computer."""
    if not any(d["did"] == did for d in you_decks()):
        return
    c = cfg()
    c["ins_deck"] = did
    save_cfg(c)
    app.swap(c)


def go_insights(did):
    """You › Insights on a deck (from a plan's line, or Crew › Decks): the
    bubble opened on it, the deck picked."""
    c = cfg()
    c["due_tab"] = "insights"
    c["due_fold"] = {"day": _today(), "folded": False}
    if "insights" in (c.get("hidden_tabs") or []):
        c["hidden_tabs"] = [k for k in c["hidden_tabs"] if k != "insights"]
    if mw.col and mw.col.decks.get(did, default=False):
        c["ins_deck"] = did
        if not any(d["did"] == did for d in you_decks()):
            _state["you_decks"] = None  # a deck the picker didn't list: it joins (you_decks keeps the one picked)
    save_cfg(c)
    app.swap(c)


def _today():
    return _state["labels"][0] if _state.get("labels") else ""


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


def _put_away(key):
    """An Insights line's Not now: gone for 30 days, on every deck."""
    pf = _plans_flow()
    pc = pf._pcfg()
    pc[key] = int(time.time())
    pf._psave(pc)
    _state["insights"] = {}
    app.swap(cfg())


# ---- the board's commands ----

def on_message(cmd, parts):
    """The plan squad's commands, and Insights' (3.8.0: ins*, a deck's id in
    each; youins opens the You bubble on Insights): True when handled."""
    arg = parts[2] if len(parts) > 2 else ""
    x = parts[3] if len(parts) > 3 else ""
    if cmd.startswith("ins") or cmd == "youins":
        if not arg.isdigit():
            return True  # a deck's id, nothing else
        did = int(arg)
        if cmd == "insdeck":
            pick_deck(did)
        elif cmd == "youins":
            go_insights(did)
        elif cmd == "insstudy" and (x.isdigit() or x == "h"):
            study(did, x)
        elif cmd == "insbrowse" and (x.isdigit() or x == "h"):
            browse(did, x)
        elif cmd == "insfsrs":
            fsrs(did)
        elif cmd == "insfsrsno":
            fsrs(did, open_it=False)
        elif cmd == "inshardno":
            _put_away("ins_hard_hide")
        elif cmd == "insleeches":
            browse_leeches(did)
        else:
            return False
        return True
    if cmd == "planteamjoin" and arg:
        join(arg, ask=x == "ask")
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
    else:
        return False
    return True
