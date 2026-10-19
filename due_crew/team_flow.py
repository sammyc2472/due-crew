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
        from . import sheets
        sheets.confirm("Join this plan's squad?", JOIN_SAYS, "Join", lambda: _join(pid, True))
        return
    _join(pid, False)


def _join(pid, ask):
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
                "shown": int(data.get("shown") or 0), "of": int(data.get("count") or 1), "faces": [], "who": [], "act": [], "last": None}})
        app.swap(cfg())
        if ask:
            tooltip("You're in. It's on the Squads tab.")
        app.sync(light=True)  # today's showed-up goes now, not at the next sync
    _bg(lambda: cl.team_join(pid, wk), done)


def leave(pid, ask=True):
    if ask:
        from . import sheets
        sheets.confirm("Leave this plan's squad?", "Your progress stops counting for its authors; "
                       "your questions and answers stay.", "Leave", lambda: leave(pid, False))
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
    from . import sheets

    def go(text):
        text = " ".join(str(text or "").split())[:280]
        if text:
            cl = client()
            _bg(_send(lambda: cl.team_ask(pid, text, parent=int(ask_id))), _after(pid))
    sheets.ask_text("Reply", "Your answer.", go, yes="Send")


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
    from . import sheets
    a, parent = _ask_by_id(pid, ask_id)
    if not a or not a.get("remove"):
        return
    cl = client()
    sheets.confirm("Remove this answer?" if parent else "Remove this question?",
                   "" if parent else "Its answers go with it.", "Remove",
                   lambda: _bg(_send(lambda: cl.team_remove(pid, a["id"])), _after(pid)), danger=True)


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
    from . import sheets
    sheets.ask_text("Ask the squad", "Your question about this card.",
                    lambda text: _ask_card(card, pid, text), yes="Ask")


def _ask_card(card, pid, text):
    text = " ".join(str(text or "").split())[:280]
    if not text:
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


def ask_this_card():
    """3.8.0, Ctrl+Shift+Q: the reviewer's Ask the squad, for the card on
    screen; said in a line when there's nothing to ask about."""
    card = getattr(getattr(mw, "reviewer", None), "card", None) if getattr(mw, "state", "") == "review" else None
    if not card:
        from .board import ASK_KBD
        tooltip(f"{ASK_KBD} asks your squad about the card you're reviewing.")
        return
    if not plan_for_card(card):
        tooltip("This card isn't on a plan whose squad you're in.")
        return
    ask_card(card)


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
    """[{did, name, full, pid}] as Insights' picker shows them, by deck: the
    top-level decks I've reviewed most in two weeks, then a plan's deck not
    among them, and the deck I picked last (from Crew › Decks, say) always;
    DECKS_MAX at most. pid: a plan I follow on that deck. Main thread."""
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
    out, seen = [], set()

    def add(did, pid=None):
        did = int(did)
        if did in seen or len(out) >= DECKS_MAX or not col.decks.get(did, default=False):
            return
        full = str(col.decks.name(did) or "")
        seen.add(did)
        out.append({"did": did, "name": full.split("::")[-1] or full, "full": full, "pid": pid})
    plans = _deck_plans(col)
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
            add(rid, plans.get(int(rid)))
    for did, pid in plans.items():
        add(did, pid)
    if picked and picked not in seen and col.decks.get(int(picked), default=False):  # a deck since deleted takes no place
        if len(out) >= DECKS_MAX:
            out.pop()
        add(picked, plans.get(int(picked)))
    return out


def _deck_plans(col):
    """{deck id: the plan that sharpens its Insights}: the first plan I follow
    on it. One view a deck (its cache, its Study and Browse), so a second plan
    on the same deck doesn't get its own."""
    pf = _plans_flow()
    state = pf._state_cfg()
    plans = {}
    for p in pf.followed():
        st = state.get(p["id"])
        if st and pf._deck_ok(col, st.get("deck_id")):
            plans.setdefault(int(st["deck_id"]), p["id"])
    return plans


def you_view(c):
    """What You › Insights draws: {decks, did, exam (my date, or ""), view}. The deck
    picked (cfg ins_deck, this computer's) or the first; a plan I follow on
    it sharpens it (its events, topic names, behind). Main thread."""
    decks = you_decks()
    if not decks:
        return {"decks": []}
    did = int(c.get("ins_deck") or 0)
    d = next((x for x in decks if x["did"] == did), decks[0])
    p = _plan(d["pid"]) if d.get("pid") else None
    exam = str(c.get("exam_date") or "")
    view = insights(d["did"], p["id"] if p else None, exam)
    at = (_state.get("map_at") or {}).get(d["did"]) or []
    if view.get("map"):
        T.map_level(view["map"], at, view.get("_map_know") or {})  # what's on screen worked out
    # 3.9.1: two buttons, for the Hard habit line: on, or just turned on from it (its Undo)
    two = ("tried" if _state.get("two_tried") else "on") if c.get("two_buttons") else ""
    out = {"decks": decks, "did": d["did"], "exam": exam, "view": dict(view, map_at=at, two=two)}
    from . import leech_flow
    if mw.col and "leeches" in view:
        # 3.9.2's QoL pass: the line's counts as the collection is now (the view it opens is), not as
        # Insights' ten minutes kept them; and the ones I left out, so their way back stays reachable
        try:
            out["view"].update(leech_flow.line_counts(mw.col, d["did"], _deck_sql(mw.col, d["did"])))
        except Exception:
            traceback.print_exc()
    if leech_flow.is_open(d["did"]) and mw.col:
        # 3.9.2: the leeches view; "on your exam" when the exam's scope is narrower than the deck
        since = (view.get("aim") or {}).get("since") if (view.get("aim") or {}).get("kind") == "exam" else ""
        ms = _since_ms(since, mw.col.sched.day_cutoff, _plans_flow()._today()) if since else None
        out["view"]["leech"] = leech_flow.current(mw.col, d["did"], _deck_sql(mw.col, d["did"]), ms)
    return out


def plan_lines(cards):
    """3.8.0, You › Plans: each plan's line from Insights (the next exam's
    cards at risk), card["ins"] = {n, did, name, day}. Main thread."""
    if not mw.col:
        return
    owner = _deck_plans(mw.col)
    for card in cards or []:
        did = next((d for d, pid in owner.items() if pid == card.get("id")), None)
        if card.get("paused") or did is None:
            continue  # a second plan on a deck: the deck's Insights are the first's
        v = insights(did, card["id"], str(cfg().get("exam_date") or ""))
        aim = v.get("aim") or {}
        if v.get("hero"):
            card["ins"] = {"n": len(v["hero"]), "did": did, "day": aim.get("day"),
                           "name": aim.get("name") if aim.get("scoped") else ""}


def insights(did, pid=None, exam=""):
    """A deck's Insights, worked out at most every INSIGHTS_FRESH seconds
    (again when the plan or the exam date changes). Main thread."""
    c = cfg()
    key = f"{pid or ''}|{exam}|{c.get('exam_last') or ''}|{c.get('exam_since') or ''}"  # 3.9.2: the scope too
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


MY_EXAM = "~exam"  # my own exam date, among a plan's events


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
    out = {"target": int(round(100 * target)), "did": did, "deck_name": str(col.decks.name(did) or "").split("::")[-1],
           "fsrs_on": bool(_fsrs(col))}  # 3.9.2's audit: Anki aims for a retention only with FSRS on

    # the header: right on this deck's reviews, first answer of each card each day
    # 3.9.2: split by the cards I started in these two weeks, when the mix shifted (T.right_split)
    young = col.db.list(f"SELECT cid FROM revlog WHERE ease > 0 AND cid IN ({deck}) GROUP BY cid HAVING min(id) >= ?",
                        since(T.DAYS))
    out["right"] = T.right_days(col.db.all(
        f"SELECT cid, CAST((? - id / 1000) / 86400 AS INTEGER), ease FROM revlog "
        f"WHERE id >= ? AND type = 1 AND ease > 0 AND cid IN ({deck}) ORDER BY id", cutoff - 1, since(2 * T.DAYS)), young)

    # the exam box: started cards Anki won't show me before the aim, under my target by then
    # (FSRS only). The deck's, plan or not: it aims at the next of my own exam date and
    # a plan's events within AIM_DAYS, else a week out. A plan's event counts its prep dates'
    # cards when it names them, else all of the plan's; anything else, the whole deck
    mine = [{"day": exam, "name": "Your exam", "id": MY_EXAM}] if exam else []
    if p:
        ms = P.unit_matches(idx, doc, swap)
        ld = P.load(idx, doc, swap)
        units = P.units(doc)
    day, name, k, eid = T.aim(list(doc.get("events") or []) + mine if p else mine, today)
    aimed, prep = deck, []
    if p and eid and eid != MY_EXAM:
        prep = T.prep_units(units, eid)
        got = set()
        for uid in prep or ms:
            got |= set(ms.get(uid) or ())
        aimed = _in(got) if got else ""
    out["aim"] = {"day": day, "name": name, "in": k, "scoped": bool(prep), "kind": "exam" if eid == MY_EXAM else ""}
    if eid == MY_EXAM:
        # 3.9.2 (Sam's pick C1-A): my exam covers the cards I started since my last exam (in the
        # last 10 weeks), or since a day I picked; else the whole deck. Said in the box, with Change
        c = cfg()
        first_day, why = T.scope(exam, c.get("exam_last"), c.get("exam_since"), today)
        out["aim"].update(since=first_day or "", since_why=why, since_pick=str(c.get("exam_since") or ""), today=str(today))
        if first_day:
            got = col.db.list(f"SELECT cid FROM revlog WHERE ease > 0 AND cid IN ({deck}) GROUP BY cid HAVING min(id) >= ?",
                              _since_ms(first_day, cutoff, today))
            aimed = _in(got)
            out["aim"]["since_n"] = len(got)
    if _fsrs(col) and aimed and sday:
        out["aim"]["checked"] = True
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
        for r in out["rows"]:
            r["find"] = {"tags": [P.swapped(t, swap) for t in r.get("tags") or []]}
    else:
        out["rows"] = _deck_rows(col, did, reviewed, stuck, forgot)

    # 3.8.0, the topic map: what I know now, by topic
    try:
        out["map"], out["map_by"], out["_map_know"], out["map_ways"] = _map(col, did, deck, cutoff)
        _map_week(out, did, today)
    except Exception:
        traceback.print_exc()

    # behind on the plan (its Catch up; nothing while a catch-up runs)
    if p:
        catch = st.get("catch") if str((st.get("catch") or {}).get("until") or "") >= today else None
        out["behind"] = 0 if catch else sum(sum((ld.get(u["id"]) or [0, 0, 0])[1:]) for u in units
                                           if str(u.get("opens") or "") < today)
        out["pid"] = p["id"]

    # 3.9.2, Reviews ahead (Your week until now): the next six weeks in cards a day,
    # counted from my own log; a plan's dates in it when I follow one (ahead_flow)
    try:
        from . import ahead_flow
        out["ahead"] = ahead_flow.deck_view(col, did, deck, exam,
                                            plan=ahead_flow.plan_days(units, ld, today) if p else None)
    except Exception:
        traceback.print_exc()

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

    # the deck's leeches Anki suspended (from the plan card, 3.8.0); 3.9.2: the ones a miss from it, and
    # the ones Anki tagged and kept showing (Tag Only)
    from . import leech_flow
    out["leeches"], out["near"], out["kept"] = leech_flow.counts(col, deck)
    return out


def _since_ms(day, cutoff, today):
    """A revlog id: the start of that Anki day."""
    back = (datetime.date.fromisoformat(str(today)) - datetime.date.fromisoformat(str(day))).days
    return (int(cutoff) - (back + 1) * 86400) * 1000


def _deck_sql(col, did):
    """The deck's cards and its subdecks', as SQL to put in IN (...)."""
    dids = _in(col.decks.deck_and_child_ids(did))
    return f"SELECT id FROM cards WHERE did IN ({dids}) OR odid IN ({dids})"


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
        for r in rows:
            r["find"] = {"tags": r.get("tags") or []}
        return rows
    root = str(col.decks.name(did) or "")
    paths, names = {}, {}
    for cid, d in col.db.all(f"SELECT id, CASE WHEN odid THEN odid ELSE did END FROM cards WHERE id IN ({ids})"):
        if int(d) not in names:
            names[int(d)] = str(col.decks.name(int(d)) or "")
        name = names[int(d)]
        if name.startswith(root + "::"):
            paths[int(cid)] = [name[len(root) + 2:]]
    topics, groups = T.deck_topics(paths, reviewed)
    rows = T.not_sticking(topics, lambda t: groups.get(t, ()), reviewed, stuck, forgot)
    for r in rows:
        r["find"] = {"decks": r.get("tags") or []}
    return rows


KNOW_DAYS = 28  # the map's window: a card's reviews these 4 weeks


def _know(col, deck, cutoff):
    """({cid: 0..1 or None}, "right"): each started card of the deck, the share of
    its reviews these KNOW_DAYS days it got right (each day's first); one
    not due in them, its last review; one never due yet, None (3.9.2's
    audit: its last answer is the pass that graduated it, so the newest
    cards read best known; the map says "too soon").
    3.9.2 (Sam's deck): FSRS's recall today read 93 to 96% on every tile
    while he passed 77% of his reviews (it says how lately a card was seen
    more than what's known), and the last answer read a relearning step
    after a miss as right. The last review alone saturates too: a missed
    card comes back the next day and passes; the weeks' share keeps it."""
    live = set(col.db.list(f"SELECT id FROM cards WHERE id IN ({deck}) AND type != 0 AND queue != -1"))
    if not live:
        return {}, ""
    win, seen = {}, set()
    for cid, day, ease in col.db.all(
            f"SELECT cid, CAST((? - id / 1000) / 86400 AS INTEGER), ease FROM revlog WHERE id >= ? AND type = 1 "
            f"AND ease > 0 AND cid IN ({deck}) ORDER BY id", int(cutoff) - 1, (int(cutoff) - KNOW_DAYS * 86400) * 1000):
        cid = int(cid)
        if cid not in live or (cid, day) in seen:
            continue
        seen.add((cid, day))
        w = win.setdefault(cid, [0, 0])
        w[0] += int(ease) > 1
        w[1] += 1
    out = {c: p / float(n) for c, (p, n) in win.items()}
    rest = [c for c in live if c not in out]
    if rest:
        out.update({c: None for c in rest})
        pick = [int(rev) for _cid, rev in col.db.all(
            f"SELECT cid, max(id) FROM revlog WHERE type = 1 AND ease > 0 AND cid IN ({_in(rest)}) GROUP BY cid")]
        if pick:
            out.update({int(c): 1.0 if int(e) > 1 else 0.0
                        for c, e in col.db.all(f"SELECT cid, ease FROM revlog WHERE id IN ({_in(pick)})")})
    return out, ("right" if out else "")


def _tag_plans(col, did):
    """3.8.1: [(plan id, name, doc, swap)] for the plans on this deck with
    their own tags: the ones I follow on it, then the ones I write on a deck
    of its name (my Anki carries their tags too)."""
    pf = _plans_flow()
    state = pf._state_cfg()
    out, seen = [], set()
    for p in pf.followed():
        st = state.get(p["id"])
        if st and int(st.get("deck_id") or 0) == int(did):
            doc = pf.mine(p)["doc"]
            if P.plan_tags(doc):
                out.append((p["id"], str(p.get("name") or "Plan"), doc, pf._swap(st)))
                seen.add(p["id"])
    name = str(col.decks.name(did) or "").lower()
    for a in client().session.get("plans_authored") or []:
        if a.get("id") not in seen and str((a.get("doc") or {}).get("deck") or "").lower() == name and P.plan_tags(a["doc"]):
            out.append((a["id"], str(a.get("name") or "Plan"), a["doc"], None))
    return out


def _plan_ways(col, did, active, know):
    """3.8.1: the map's ways by each plan's own tags, {key: (way, tiles)}."""
    out = {}
    plans = _tag_plans(col, did)
    if not plans:
        return out
    idx = P.DeckIndex(col, did)
    for pid, name, doc, swap in plans:
        held = [(t["name"], P.tag_path(doc, t), idx.plan_tag_cards(doc, t, swap)) for t in P.plan_tags(doc)]
        tiles, none = T.plan_tiles(held, know, active)
        key = f"~plan:{pid}"
        out[key] = ({"key": key, "name": f"{name}'s tags"[:T.NAME_MAX], "score": 0.0, "on": False, "none": none}, tiles)
    return out


def _map(col, did, deck, cutoff):
    """(tiles, by, know, ways) for the topic map: the deck's cards in play
    (unsuspended, started or not) split by its own tags or its subdecks,
    the way that tells them apart best (T.subjects_by), plan or not, or
    the way I picked (cfg ins_map_by, this computer's, per deck), or
    (3.8.1) by a plan's own tags when I pick that. Shaded by what I know
    now of the started ones."""
    know, by = _know(col, deck, cutoff)
    rows = col.db.all(f"SELECT c.id, n.tags, CASE WHEN c.odid THEN c.odid ELSE c.did END FROM cards c "
                      f"JOIN notes n ON n.id = c.nid WHERE c.id IN ({deck}) AND c.queue != -1")
    if not rows or not know:
        return [], by, know, []
    pick = str((cfg().get("ins_map_by") or {}).get(str(did)) or "") or None
    active = {int(cid) for cid, _t, _d in rows}
    tags_of = {int(cid): str(tags or "").split() for cid, tags, _d in rows}
    tiles, ways = T.subjects_by(tags_of, know, active, by=None if pick == DECKS_WAY else pick)
    root = str(col.decks.name(did) or "")
    names, paths = {}, {}
    for cid, _t, d in rows:
        if int(d) not in names:
            names[int(d)] = str(col.decks.name(int(d)) or "")
        name = names[int(d)]
        if name.startswith(root + "::"):
            paths[int(cid)] = [name[len(root) + 2:]]
    dtiles, dways = T.subjects_by(paths, know, active, decks=True) if paths else ([], [])
    best = ways[0]["score"] if ways else 0.0
    by_decks = bool(dtiles) and (pick == DECKS_WAY or (pick not in {w["key"] for w in ways} and dways[0]["score"] > best)
                                 or len(tiles) < 2)
    if dtiles:
        ways = [dict(w, on=not by_decks and w["on"]) for w in ways]
        ways.append({"key": DECKS_WAY, "name": "Subdecks", "score": dways[0]["score"], "on": by_decks})
        ways.sort(key=lambda w: -w["score"])
    shown = dtiles if by_decks else tiles
    # 3.9.2 (Sam's pick C2-A): by when I started them, a week a tile, named by what each week was;
    # worked out only when picked (its first answers are one more read of the deck's log)
    start = []
    if pick == T.START_WAY:
        first = {int(c): (cutoff - 1 - int(t) // 1000) // 86400 for c, t in col.db.all(
            f"SELECT cid, min(id) FROM revlog WHERE ease > 0 AND cid IN ({deck}) GROUP BY cid")}
        # named and opened by the map's own topics: its tag way that's on, else its best (3.9.2's audit:
        # plain tags are a way too; subdecks, a plan's tags and this one aren't tags of the deck's own)
        tag_ways = [w for w in ways if w["key"] == T.TAGS_WAY or not str(w["key"]).startswith("~")]
        own = next((w["key"] for w in tag_ways if w.get("on")), None) or (tag_ways[0]["key"] if tag_ways else None)
        start = T.started_tiles(first, tags_of, know, active, _plans_flow()._today(), own)
        if len(start) >= 2:
            ways = [dict(w, on=False) for w in ways]
            shown = start
    # 3.9.2 (Sam's pick): picked, but all I've started is from one week: said, not snapped back to topics
    ways.append({"key": T.START_WAY, "name": "When you started them", "score": 0.0, "on": len(start) >= 2,
                 "one": pick == T.START_WAY and len(start) == 1})
    plan_ways = _plan_ways(col, did, active, know) if active else {}
    if plan_ways:  # 3.8.1: a plan's own tags, only when picked, after the deck's own ways
        chosen = plan_ways.get(pick) if pick else None
        if chosen and len(chosen[1]) >= 2:
            ways = [dict(w, on=False) for w in ways]
            shown = chosen[1]
        ways += [dict(w, on=bool(chosen) and w["key"] == pick and len(t) >= 2) for w, t in plan_ways.values()]
    return shown, by, know, ways


DECKS_WAY = "~decks"  # the map by the deck's subdecks, among its ways


def _map_week(out, did, today):
    """3.8.0: the deck's map a week ago or more, for the card's change:
    kept in this profile's plans.json (never sent), today's added once a
    week at most (mapcard.keep)."""
    if not out.get("map"):
        return
    from . import mapcard as MC
    way = next((w["key"] for w in out.get("map_ways") or [] if w.get("on")), None)
    if way is None:
        return
    way = f"{way}|due"  # 3.9.2: shaded by the last review now; a week of the old shading isn't compared
    pf = _plans_flow()
    pc = pf._pcfg()
    snaps = pc.get("map_snaps") if isinstance(pc.get("map_snaps"), dict) else {}
    had = snaps.get(str(did)) if isinstance(snaps.get(str(did)), dict) else {}
    now = MC.keep_ways(had, way, today, out["map"])
    if now != had:
        pc["map_snaps"] = dict(snaps, **{str(did): now})
        pf._psave(pc)
    out["map_prev"], out["map_since"] = MC.week_ago(now.get(str(way)), today)


def share_map(did):
    """Share › on the map: the picture card (and its text) of the level on
    screen, made here; last week's change for the whole deck's level."""
    view = ((_state.get("insights") or {}).get(did) or {}).get("view") or {}
    trail, cur = _map_at(did)
    if len(cur) < 2 or not mw.col:
        return
    deck = str(mw.col.decks.name(did) or "").split("::")[-1] or "My deck"
    title = " \u00b7 ".join([deck] + [str(t["name"]) for t in trail])
    prev = None if trail else view.get("map_prev")
    from .ui.map_card_dialog import MapCardDialog
    dlg = MapCardDialog(mw, title, _plans_flow()._today(), cur, view.get("map_by") or "fsrs", prev,
                        (view.get("map_since") or "") if prev else "", tooltip=tooltip, part=bool(trail))
    _state["map_card"] = dlg  # kept while it's open
    dlg.show()


def pick_map(did, i):
    """The map's "by": another way to split it, remembered for this deck
    on this computer; the map starts again from the top."""
    view = ((_state.get("insights") or {}).get(did) or {}).get("view") or {}
    ways = view.get("map_ways") or []
    if not 0 <= i < len(ways):
        return
    c = cfg()
    c["ins_map_by"] = dict(c.get("ins_map_by") or {}, **{str(did): ways[i]["key"]})
    save_cfg(c)
    (_state.get("map_at") or {}).pop(did, None)
    (_state.get("insights") or {}).pop(did, None)
    app.swap(cfg())


def _find_cids(col, did, find):
    """3.8.0: every card of the deck under a topic's tags (and their
    children) or its subdecks: what a topic's name opens in Browse."""
    deck = _deck_sql(col, did)
    out = set()
    out |= {int(c) for c in (find or {}).get("cids") or ()}  # 3.9.2: a week I started them, its own cards
    want = [str(t).lower() for t in (find or {}).get("tags") or [] if str(t)]
    if want:
        # matched here, not in SQL: SQLite's lower() and LIKE fold ASCII only ("Анатомия", "Ökologie")
        for cid, tags in col.db.all(f"SELECT c.id, n.tags FROM cards c JOIN notes n ON n.id = c.nid WHERE c.id IN ({deck})"):
            mine = str(tags or "").lower().split()
            if any(x == lt or x.startswith(lt + "::") for lt in want for x in mine):
                out.add(int(cid))
    root = str(col.decks.name(did) or "")
    for path in (find or {}).get("decks") or []:
        sub = col.decks.id_for_name(f"{root}::{path}")
        if sub:
            dids = _in(col.decks.deck_and_child_ids(sub))
            out |= {int(c) for c in col.db.list(f"SELECT id FROM cards WHERE did IN ({dids}) OR odid IN ({dids})")}
    return sorted(out)


def _map_at(did):
    view = ((_state.get("insights") or {}).get(did) or {}).get("view") or {}
    return T.map_level(view.get("map"), (_state.get("map_at") or {}).get(did), view.get("_map_know") or {})


def open_map(did, i):
    """A topic map tile: one that splits again opens into its smaller
    tiles, with the trail back above them; one that doesn't, all of its
    cards in this deck, in Anki's browser."""
    trail, cur = _map_at(did)
    if not mw.col or not 0 <= i < len(cur):
        return
    t = cur[i]
    if t.get("kids"):
        _state.setdefault("map_at", {})[did] = [x["key"] for x in trail] + [t["key"]]
        app.swap(cfg())
    else:
        _plans_flow()._browse(_find_cids(mw.col, did, t.get("find")), empty="Nothing to show.")


def map_up(did, n):
    """The trail: back to its nth step (0, All)."""
    trail, _cur = _map_at(did)
    _state.setdefault("map_at", {})[did] = [x["key"] for x in trail[:n]]
    app.swap(cfg())


def browse_map(did):
    """The trail's Browse all: the open tile's cards in this deck."""
    trail, _cur = _map_at(did)
    if mw.col and trail:
        _plans_flow()._browse(_find_cids(mw.col, did, trail[-1].get("find")), empty="Nothing to show.")


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
    name = pf._deck_name(title)
    if pf._filtered(mw.col, name, cids):
        pf._after_change()
        fid = mw.col.decks.id_for_name(name)
        if fid:
            mw.col.decks.select(fid)
            mw.moveToState("overview")


def browse(did, key):
    """3.8.0: in Anki's browser. The exam box: its cards. A topic's name:
    all of its cards in the deck (Study is for the hard ones)."""
    cids, _title = _pick(did, key)
    if not mw.col:
        return
    if str(key).isdigit():
        rows = (((_state.get("insights") or {}).get(did) or {}).get("view") or {}).get("rows") or []
        r = rows[int(key)] if int(key) < len(rows) else None
        cids = (_find_cids(mw.col, did, r.get("find")) if r and r.get("find") else []) or cids
    _plans_flow()._browse(cids, empty="Nothing to show.")


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
    (_state.get("leech_open") or {}).pop(int(did), None)  # 3.9.2's QoL pass: Insights itself, not a leeches view left open
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


def try_two(on):
    """3.9.1: Try two buttons, from the Hard habit line: on (an account key,
    saved and synced as Settings saves it), and the line says so with Undo,
    which turns it off again and brings the line back."""
    c = dict(cfg())
    c["two_buttons"] = bool(on)
    _state["two_tried"] = bool(on)
    save_cfg(c)
    app.swap(cfg())


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
        elif cmd == "insmap" and x.isdigit():
            open_map(did, int(x))
        elif cmd == "insmapup" and x.isdigit():
            map_up(did, int(x))
        elif cmd == "insmapall":
            browse_map(did)
        elif cmd == "insmapby" and x.isdigit():
            pick_map(did, int(x))
        elif cmd == "insmapshare":
            share_map(did)
        elif cmd == "inshardno":
            _put_away("ins_hard_hide")
        elif cmd == "instwo":
            try_two(True)
        elif cmd == "instwono":
            try_two(False)
        elif cmd == "insleeches":
            from . import leech_flow
            leech_flow.open_view(did)  # 3.9.2: the leeches view in Insights' place (Browse is on it)
        elif cmd == "insleech":
            from . import leech_flow
            return leech_flow.on_message(did, x, parts[4] if len(parts) > 4 else "")
        elif cmd == "insaheadoff" and x in ("now", "week"):
            from . import ahead_flow
            ahead_flow.stop_new(did, x)
        elif cmd == "insaheadon":
            from . import ahead_flow
            ahead_flow.start_new(did)
        elif cmd == "insaheadx":
            from . import ahead_flow
            ahead_flow.hide_line(did)
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
