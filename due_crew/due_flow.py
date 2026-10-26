"""Due, the glue: what the box above the board shows, from this computer,
and what its clicks do. Main thread: every collection read and the one
leech step happen here; the only requests are the account settings
pushes my own items ride (app.save_cfg), as any setting does.

Account keys (every computer, and the site): `due_items` (my own to-dos),
`due_ticks` (the author's lines I ticked), `due_show` (show it), and
`due_suggest` (suggestions from my own Anki). Per computer, in the config:
`due_tab`, `due_fold` (my Hide/Show for one day; else Due folds
itself once the day is done), and `due_leeches` (recover leeches: it changes this
collection, so it's this computer's to say). Per profile, beside the
plans (plans.json): the day's dismissed suggestions and what recovering
leeches did today.
"""

import datetime
import time
import traceback
from urllib.parse import unquote

from aqt import mw
from aqt.utils import tooltip

from . import app
from . import due as D
from . import plans as P
from .app import _state, cfg, save_cfg

AGAIN_MIN = 10  # today's misses before the box suggests going over them
MISSES = P.our_deck("Today's misses")  # their filtered deck, under Due Crew's parent
LEECH_MIN = 3  # new leeches this week before it suggests a look
RECOVER_MAX = 200  # leeches recovered in a morning, at most
REVIEWS_FRESH = 30.0  # seconds a reviews-due count is good for
# 3.9.5: Next up, once the day's reviews are through (Five mocks, reviewed)
NEXT_EXAM_DAYS, NEXT_EXAM_MIN = 7, 10  # an exam this close, with this many cards at risk
NEXT_TOPIC_MIN = 8   # a topic with this many missed in Insights' two weeks
NEXT_NEAR_MIN = 5    # cards one miss from a leech
NEXT_KEYS = ("next", "leeches")  # Not today on a Next up line: none steps in till tomorrow


def _pf():
    from . import plan_flow
    return plan_flow


def _today():
    return _state["labels"][0] if _state.get("labels") else ""


def on(c):
    return bool(c.get("due_show", True))


def _items(c):
    return D.clean_items(c.get("due_items"))


def _ticks(c):
    return D.clean_ticks(c.get("due_ticks"))


def _save(c, items=None, ticks=None):
    if items is not None:
        c["due_items"] = items
    if ticks is not None:
        c["due_ticks"] = ticks
    save_cfg(c)  # an account key: pushed, newest save wins


# ---- what the box shows ----

def plan_dates(today):
    """(dates, events, review days) from the plans I follow and run here, as
    due.view takes them: each date with my numbers and its parts."""
    pf = _pf()
    prog = _state.get("plan_progress") or {}
    parts = _state.get("plan_parts") or {}
    sibs = _state.get("plan_sibs") or {}
    later = _state.get("plan_later") or {}
    state = pf._state_cfg()
    end = D.iso(D.d(today) + datetime.timedelta(days=D.AHEAD))
    dates, events, reviews = [], [], []
    for p in pf.followed():
        st = state.get(p["id"])
        if p.get("paused") or not st or not mw.col or not pf._deck_ok(mw.col, st.get("deck_id")):
            continue
        doc, title = p["doc"], P.plan_title(p)
        named = {x["id"]: x for x in P.units(P.with_picks(doc, (_state.get("plan_picks") or {}).get(p["id"])))}  # 3.8.1
        evs = {e.get("id"): e for e in doc.get("events") or [] if isinstance(e, dict)}
        applied = st.get("applied") or {}
        crew, followers = p.get("crewDone") or {}, int(p.get("followers") or 0)
        upd = (_state.get("plan_updates") or {}).get(p["id"]) or {}
        own = P.own_pace(p)  # 3.8.0: the dates I opened are today's, till seen; nothing is behind or upcoming
        own_days = st.get("own_opened") or {}
        # round five: what a date's details say and offer, as the Plans tab's week had it
        moved, shut = p.get("moved") or {}, pf._shut_dates(p, st, prog.get(p["id"]))
        lee, miss = st.get("leeches") or {}, st.get("missing") or {}
        for u in P.units(doc):
            opens = str(u.get("opens") or "")
            a = applied.get(u["id"])
            pr = (prog.get(p["id"]) or {}).get(u["id"])
            o, s, t = pr or [0, 0, 0]
            if own:
                if not P.opened_here(applied, u, prog.get(p["id"]) or {}):
                    continue
                if int(t) and int(s) >= int(t) and own_days.get(u["id"]) != today:
                    continue
                opens = today
            if not opens or opens > end:
                continue
            # 3.7.2: an even date (or a 3.2 schedule) opens in slices and is
            # applied only when its window ends: while it runs, what's due is
            # what has opened so far
            running = not a and int(o) > 0 and bool(u.get("even") or p.get("sched"))
            if opens < today and (not (a or running) or str(a).startswith("skip:")):
                continue  # never opened here (followed after it): not mine to be behind on
            if not int(t) and opens < today and not u.get("todo"):
                continue  # nothing of it in my deck: nothing to be behind on
            ev = evs.get(u.get("for"))
            m = miss.get(u["id"]) if isinstance(miss.get(u["id"]), (list, tuple)) else None
            dates.append({"pid": p["id"], "uid": u["id"], "plan": title, "name": str(u.get("name") or "?"),
                          "opens": opens, "seen": int(s),
                          "later": int((later.get(p["id"]) or {}).get(u["id"]) or 0),  # 3.9.3: back later today
                          "total": int(o) if running else int(t) or (P.unit_total(u) if opens > today else 0),
                          # counted here and nothing of it in my deck: done once it's open (3.7.2)
                          "counted": pr is not None and opens <= today,
                          "parts": (parts.get(p["id"]) or {}).get(u["id"]) or [],
                          "sibs": (sibs.get(p["id"]) or {}).get(u["id"]),
                          "todo": [x for x in u.get("todo") or [] if isinstance(x, dict)],
                          "what": P.topics_line([u]), "topics": P.topic_view([named.get(u["id"], u)]),  # 3.8.0: each a link
                          "rm": P.topic_remarks(doc, [named.get(u["id"], u)]),  # 3.8.1: the authors' notes under its topics
                          "crew": [int(crew.get(u["id"]) or 0), followers] if followers > 1 else None,
                          "prep": str(ev.get("name") or "") if ev else None,
                          # 3.8.1: a date after its event reinforces it ("after Heme quiz"); Study
                          # on a date with cards open (a Due Crew deck of them); view() adds both to its row
                          "after": bool(ev) and P.reinforces(doc, u) is not None,
                          "study": opens <= today and int(o) > 0,
                          # 3.7.3: an author's update adds to it, waiting for Open (its count when it's
                          # the only date the update touches; -1: one of several)
                          "upd": (0 if u["id"] not in (upd.get("units") or []) else
                                  int(upd.get("n") or 0) if len(upd["units"]) == 1 else -1),
                          "own": own, "moved": bool(moved.get(u["id"])), "shut": opens <= today and u["id"] in shut,
                          # what it left shut when it opened: its leeches (Browse) and picks this copy hasn't
                          "why": {"lee": int(lee.get(u["id"]) or 0), "miss": int(m[0]) if m else 0} if a else None})
        for e in evs.values():
            if today <= str(e.get("day") or "") <= end:
                events.append({"day": e["day"], "name": str(e.get("name") or "?"), "plan": title})
        for r in doc.get("reviews") or []:
            if isinstance(r, dict) and today <= str(r.get("day") or "") <= end:
                reviews.append({"day": r["day"], "plan": title})
    return dates, events, reviews


def plan_every(today):
    """3.8.0: the weekly lines of the plans I follow and run here, as
    due.view takes them: {pid, plan, first, last, lines}, from my first date
    to my last (or the plan's last event or end date, if later)."""
    pf = _pf()
    state = pf._state_cfg()
    out = []
    for p in pf.followed():
        st = state.get(p["id"])
        doc = p["doc"]
        lines = [x for x in doc.get("every") or [] if isinstance(x, dict)]
        if not lines or p.get("paused") or not st or not mw.col or not pf._deck_ok(mw.col, st.get("deck_id")):
            continue
        days = [str(u.get("opens") or "") for u in P.units(doc) if u.get("opens")]
        if not days:
            continue
        ends = days + [str(e.get("day") or "") for e in doc.get("events") or [] if isinstance(e, dict)]
        ends += [str(doc["end"])] if doc.get("end") else []
        out.append({"pid": p["id"], "plan": P.plan_title(p), "first": min(days), "last": max(ends), "lines": lines})
    return out


def _every_line(key, today, any_day=False):
    """(plan, line) for a weekly line's key, on today (or any day), else (None, None)."""
    pid = key.split(":")[0]
    for p in plan_every(today):
        if p["pid"] == pid:
            keys = D.every_keys(pid, p["lines"])
            if key in keys and (any_day or D.every_on(p, p["lines"][keys.index(key)], today)):
                return p, p["lines"][keys.index(key)]
    return None, None


_QIDS = {"key": None, "has": False}


def has_qids():
    """3.9.3: a tag here ends in a question's number (3 to 9 digits, what
    QBank QIDs finds: planner.qids), so the box's head offers it. Anki's tag
    list, not the notes: read once a profile and day."""
    col = mw.col
    key = (app.generation, id(col), _today())
    if _QIDS["key"] != key:
        pats = " OR ".join(f"tag GLOB '*::{'[0-9]' * k}'" for k in range(3, 10))
        try:
            has = bool(col.db.scalar(f"SELECT 1 FROM tags WHERE {pats} LIMIT 1"))
        except Exception:
            traceback.print_exc()
            has = False
        _QIDS.update(key=key, has=has)
    return _QIDS["has"]


_TREE = {"key": None, "at": 0.0, "until": 0.0, "tree": None}


def deck_tree(col):
    """3.9.1: Anki's deck tree with its counts, read again only once it can
    have changed: the collection did (every answer and op moves col.mod),
    the day turned, or a learning card came inside Anki's learn-ahead (the
    clock moves that count, not a change). Due's reviews, a plan's due and
    the bingo's week share one read (each had its own: 8 to 17 ms on 35,000
    cards, again after every refresh)."""
    mod, now = getattr(col, "mod", None), time.time()
    key = (app.generation, id(col), mod)
    if mod is not None and _TREE["key"] == key and _TREE["at"] <= now < _TREE["until"]:
        return _TREE["tree"]
    tree = col.sched.deck_due_tree()
    try:
        # a learning card counts once it's due within the learn-ahead (preview cards too)
        ahead = int(col.get_config("collapseTime", 1200) or 0)
        nxt = col.db.scalar("SELECT min(due) FROM cards WHERE queue IN (1, 4) AND due >= ?", int(now) + ahead)
        until = min(float(col.sched.day_cutoff), float(nxt) - ahead if nxt else float("inf"))
    except Exception:
        until = 0.0  # can't say when it changes: read again next time
    _TREE.update(key=key, at=now, until=until, tree=tree)
    return tree


def _reviews():
    """{due, done}: what Anki shows now across my decks (Study today's
    walk), answers today; and 3.9.3's bars
    (bars()): the reviews' whole, through, later, left, back and at, and the
    new cards' (`new`, and `other`: started today outside today's plan
    dates). Cached a little: the board redraws often."""
    hit = _state.get("due_reviews")
    if hit and time.time() - hit[0] < REVIEWS_FRESH:
        return hit[1]
    out = None
    try:
        tree = deck_tree(mw.col)
        due = sum(int(n.review_count) + int(n.learn_count) for n in tree.children)
        start = (mw.col.sched.day_cutoff - 86400) * 1000
        done = int(mw.col.db.scalar("SELECT count() FROM revlog WHERE id >= ? AND ease > 0", start) or 0)
        now = int(time.time())
        ahead = int(mw.col.get_config("collapseTime", 1200) or 0)
        out = {"due": due, "done": done}
        try:
            got = bars(mw.col, tree, now, ahead, set(_state.get("plan_today") or ()))
        except Exception:
            traceback.print_exc()  # the count alone, as before 3.9.3
            got = {}
        when = got.pop("_first", 0)
        if got.pop("first", False):
            _flip_at(int(when) - ahead)
        out.update(got)
    except Exception:
        traceback.print_exc()
    _state["due_reviews"] = (time.time(), out)
    return out


def _misses(col):
    """3.9.5: today's misses: the reviews I answered Again today (a card
    once, first missed first), the reviews I answered today, and, once
    Study the N again has run today, how many of its cards I've answered
    since and how many right the first time. Main thread."""
    start = (int(col.sched.day_cutoff) - 86400) * 1000
    cids = [int(c) for c, _m in col.db.all("SELECT cid, min(id) FROM revlog WHERE id >= ? AND ease = 1 AND type = 1 "
                                           "GROUP BY cid ORDER BY 2", start)]
    out = {"n": len(cids), "cids": cids[:500],
           "reviews": int(col.db.scalar("SELECT count(DISTINCT cid) FROM revlog WHERE id >= ? AND ease > 0 AND type = 1",
                                        start) or 0)}
    out["topics"], out["elsewhere"] = _miss_topics(col, cids)
    built = _pf()._pcfg().get("misses_built")
    if isinstance(built, dict) and built.get("day") == _today() and built.get("cids"):
        mine = {int(c) for c in built["cids"]}
        seen = {}
        for cid, ease in col.db.all("SELECT cid, ease FROM revlog WHERE id >= ? AND ease > 0 ORDER BY id",
                                    int(float(built.get("at") or 0) * 1000)):
            if int(cid) in mine:
                seen.setdefault(int(cid), int(ease))
        out.update(of=len(mine), over=len(seen), right=sum(1 for x in seen.values() if x > 1))
    return out


def bars(col, tree, now, ahead, plan_cids=()):
    """3.9.3: the Today box's bars, from today's answers and today's learning
    cards. A card is through for today once it's answered and next due
    tomorrow or later; later: answered, back later today.

    Reviews are the cards due from before today: reviews, relearning, and
    learning carried over from an earlier day (whole: those I've answered
    today and the ones still due). New cards are the ones I started today
    (a first answer of a new card), and what Anki's limits still give;
    `other`, the ones I started today that none of today's plan dates holds
    (plan_cids). back/at: reviews back later today, past Anki's learn-ahead,
    and the first one's time. first/_first: any learning card back later
    today, for the box's one timer."""
    cut, day = int(col.sched.day_cutoff), int(col.sched.today)
    start = (cut - 86400) * 1000
    first = {}  # cid -> (its first answer today's type, last interval)
    for cid, kind, last in col.db.all("SELECT cid, type, lastIvl FROM revlog WHERE id >= ? AND ease > 0 ORDER BY id", start):
        first.setdefault(int(cid), (int(kind), int(last or 0)))
    fresh = {c for c, (kind, last) in first.items() if kind == 0 and last == 0}  # a new card's first answer
    tops = {}  # deck id -> its top deck's (id, name), from Anki's tree

    def walk(node, top):
        tops[int(node.deck_id)] = top
        for ch in node.children:
            walk(ch, top)
    for ch in tree.children:
        walk(ch, (int(ch.deck_id), str(getattr(ch, "name", "") or "")))
    rv = {"through": 0, "later": 0}
    nw, ot = {}, {}  # top deck id -> [through, later]
    if first:
        ids = ",".join(str(c) for c in first)
        for cid, queue, due, did in col.db.all(f"SELECT id, queue, due, did FROM cards WHERE id IN ({ids})"):
            queue, due = int(queue), int(due or 0)
            k = "later" if (queue == 1 and due < cut) or (queue in (2, 3) and due <= day) else "through"
            if int(cid) not in fresh:
                rv[k] += 1
                continue
            top = tops.get(int(did), (0, ""))
            for got, on in ((nw, True), (ot, int(cid) not in plan_cids)):
                if on:
                    got.setdefault(top, [0, 0])[k == "later"] += 1
    # what's still due today and not yet answered: reviews by Anki's limits,
    # and (re)learning cards, which no limit holds back
    todo_r = sum(int(n.review_count) for n in tree.children)
    left = todo_r
    back, at, any_at = 0, None, None
    for cid, queue, due in col.db.all("SELECT id, queue, due FROM cards WHERE (queue = 1 AND due < ?) OR (queue = 3 AND due <= ?)",
                                      cut, day):
        cid, queue, due = int(cid), int(queue), int(due or 0)
        if queue == 1 and due > now + ahead:
            any_at = due if any_at is None else min(any_at, due)
        if cid in fresh:
            continue
        if cid not in first:
            todo_r += 1
        if queue == 3 or due <= now + ahead:
            left += 1
        else:
            back += 1
            at = due if at is None else min(at, due)
    answered = rv["through"] + rv["later"]
    t = time.localtime(at) if at else None
    out = {"whole": answered + todo_r, "through": rv["through"], "later": rv["later"], "left": left, "back": back,
           "at": f"{t.tm_hour}:{t.tm_min:02d}" if t else "", "first": any_at is not None, "_first": any_at or 0}
    decks = []
    for ch in tree.children:
        top = (int(ch.deck_id), str(getattr(ch, "name", "") or ""))
        th, lt = nw.get(top, [0, 0])
        more = int(getattr(ch, "new_count", 0) or 0)
        if th + lt + more:
            decks.append([top[1], th, th + lt + more, lt])
    out["new"] = {"through": sum(d[1] for d in decks), "later": sum(d[3] for d in decks),
                  "whole": sum(d[2] for d in decks), "decks": decks}
    od = [[name, th, th + lt, lt] for (_d, name), (th, lt) in ot.items() if name]
    out["other"] = {"through": sum(d[1] for d in od), "later": sum(d[3] for d in od),
                    "whole": sum(d[2] for d in od), "decks": sorted(od, key=lambda d: -d[2])}
    return out


def _flip_at(when):
    """3.8.0: when the first learning card comes back (inside Anki's
    learn-ahead), Reviews says it's due: one timer, the earliest, redraws
    the box while the Decks screen shows it. Gone with the profile."""
    pending = _state.get("back_timer")
    if pending and pending[0] <= when and pending[1] == app.generation:
        return
    gen = app.generation
    _state["back_timer"] = (when, gen)
    delay = max(5, min(when - int(time.time()), 86400)) * 1000 + 2000

    def fire():
        if _state.get("back_timer") != (when, gen) or app.generation != gen:
            return
        _state["back_timer"] = None
        _state["due_reviews"] = None
        if getattr(mw, "state", "") == "deckBrowser":
            _swap(cfg())
    try:
        from aqt.qt import QTimer
        QTimer.singleShot(int(delay), fire)
    except Exception:
        traceback.print_exc()


def _day_state():
    pc = _pf()._pcfg()
    st = pc.get("due") if isinstance(pc.get("due"), dict) else {}
    if st.get("day") != _today():
        st = {"day": _today(), "dismissed": [], "recovered": []}
    return pc, st


def _put_day(pc, st):
    pc["due"] = st
    _pf()._psave(pc)


def suggestions(c, today):
    """At most two, from my own Anki. 3.9.5: once the day's reviews are
    through, Next up (_next_up); else new leeches, as before."""
    if not c.get("due_suggest", True) or not mw.col:
        return []
    _pc, st = _day_state()
    gone = set(st.get("dismissed") or [])
    r = _reviews() or {}
    through = r.get("whole") is not None and not int(r.get("left") or 0) and not int(r.get("back") or 0)
    # every render asks; the answer changes only when the collection does
    key = (getattr(mw.col, "mod", None), _today(), tuple(sorted(gone)), bool(c.get("due_leeches")), through)
    hit = _state.get("due_suggest")
    if key[0] is not None and hit and hit[0] == key:
        return list(hit[1])
    out = []
    try:
        nxt = _next_up(c, gone) if through and not gone & set(NEXT_KEYS) else None
        if nxt:
            out.append(nxt)
        # 3.8.0: today's misses are Study today's last step, not a suggestion of their own
        # (3.9.5: they're under the Reviews row once it's done)
        elif not c.get("due_leeches") and not gone & set(NEXT_KEYS):
            week = (mw.col.sched.day_cutoff - 8 * 86400) * 1000
            lee = int(mw.col.db.scalar(
                "SELECT count(DISTINCT c.nid) FROM cards c JOIN notes n ON n.id = c.nid "
                "WHERE (' ' || lower(n.tags) || ' ') LIKE '% leech %' "
                "AND c.id IN (SELECT cid FROM revlog WHERE id >= ? AND ease = 1)", week) or 0)
            if lee >= LEECH_MIN:
                out.append({"key": "leeches", "text": f"{lee:,} new leeches this week", "go": "See them",
                            "lead": "Next up:" if through else ""})
    except Exception:
        traceback.print_exc()
    _state["due_suggest"] = (key, out[:2])
    return out[:2]


MISS_TOPICS = 3  # today's misses named by part: the three with the most, the rest "elsewhere"


def _miss_topics(col, cids):
    """3.9.5: today's misses by the map's parts for the deck I reviewed most
    today (team_flow.deck_map, its top level): ([(part, [cid])] the
    MISS_TOPICS with the most, how many fall elsewhere), or ([], 0) when
    they don't split (one part, or no map). Worked out again only when the
    misses change. Main thread."""
    key = (_today(), tuple(cids))
    hit = _state.get("due_miss_topics")
    if hit and hit[0] == key:
        return hit[1]
    out = ([], 0)
    try:
        did = _today_deck(col) if cids else None
        if did:
            from . import team, team_flow
            tiles, _missed = team_flow.deck_map(did)
            left, groups = set(cids), []
            for t in tiles:
                got = [c for c in cids if c in left and c in set(team.tile_cards(t))]
                if got:
                    groups.append((str(t.get("name") or ""), got))
                    left -= set(got)
            groups.sort(key=lambda g: -len(g[1]))
            if len(groups) > 1:
                top = groups[:MISS_TOPICS]
                out = (top, len(cids) - sum(len(g) for _n, g in top))
    except Exception:
        traceback.print_exc()
    _state["due_miss_topics"] = (key, out)
    return out


def _today_deck(col):
    """The top deck I reviewed most today (a Due Crew deck's cards count for their home deck), or None."""
    start = (int(col.sched.day_cutoff) - 86400) * 1000
    roots = {}
    for did, n in col.db.all("SELECT CASE WHEN c.odid THEN c.odid ELSE c.did END, count() FROM revlog r "
                             "JOIN cards c ON c.id = r.cid WHERE r.id >= ? AND r.ease > 0 GROUP BY 1", start):
        root = str(col.decks.name(int(did)) or "").split("::")[0]
        if root:
            roots[root] = roots.get(root, 0) + int(n)
    for root, _n in sorted(roots.items(), key=lambda x: (-x[1], x[0].lower())):
        rid = col.decks.id_for_name(root)
        if rid:
            return int(rid)
    return None


def _next_up(c, gone):
    """3.9.5 (Five mocks, reviewed): one line once the day's reviews are
    through, the first that applies, from Insights' own numbers for the deck
    I reviewed most today: a topic not sticking, NEXT_TOPIC_MIN or more
    missed; NEXT_NEAR_MIN or more cards one miss from a leech. Its button
    is Insights' own. Not today puts it away, and none steps in till
    tomorrow. None when nothing applies. (Before my exam and Slow but right
    are Super decks, in their own rows: `supers`.)"""
    from . import team_flow
    did = _today_deck(mw.col)
    view = {}
    if did:
        d = next((x for x in team_flow.you_decks() if x["did"] == did), None)
        view = team_flow.insights(did, (d or {}).get("pid"), str(c.get("exam_date") or "")) or {}
    rows = view.get("rows") or []
    if rows and int(rows[0].get("stuck") or 0) + int(rows[0].get("forgot") or 0) >= NEXT_TOPIC_MIN:
        k = int(rows[0]["stuck"]) + int(rows[0]["forgot"])
        return {"key": "next", "lead": "Next up:", "cmd": f"insstudy:{did}:0", "go": f"Study {k:,}",
                "text": f'{rows[0]["name"]} isn\u2019t sticking: {k:,} of {int(rows[0].get("of") or k):,} missed in two weeks'}
    near = int(view.get("near") or 0)
    if did and near >= NEXT_NEAR_MIN:
        return {"key": "next", "lead": "Next up:", "cmd": "duego:near", "go": "See them",
                "text": f"{near:,} cards are one miss from a leech"}
    return None


def notes():
    _pc, st = _day_state()
    n = len(st.get("recovered") or [])
    # 3.9.3 (Sam): one card is "it": "Recovered 1 leech as a new card · See it"
    text = f"Recovered {n:,} leeches as new cards" if n != 1 else "Recovered 1 leech as a new card"
    return [{"key": "recovered", "text": text, "go": "See them" if n != 1 else "See it"}] \
        if n and "recovered" not in (st.get("dismissed") or []) else []


YOU_TABS = D.TABS + ("plans", "insights")  # 3.8.0: the You bubble's tabs, Due's lists first


def you_tab(c):
    """The You bubble's tab on this computer (`due_tab`), Today when unknown."""
    tab = c.get("due_tab")
    return tab if tab in YOU_TABS else "today"


def folded(c, v):
    """The bubble folded or open: Due's own rule with its lists on (v), else
    my Hide/Show for today."""
    if v:
        return bool(v.get("folded"))
    choice = c.get("due_fold")
    return isinstance(choice, dict) and choice.get("day") == _today() and bool(choice.get("folded"))


def view(c):
    """due.view for the board, or None when the box is off or there's no day yet."""
    today = _today()
    if not on(c) or not today:
        return None
    try:
        dates, events, revs = plan_dates(today)
        items = D.prune(_items(c), today)
        v = D.view(today, dates, items, _ticks(c), tab=c.get("due_tab", "today"), events=events,
                   review_days=revs, reviews=_reviews() if mw.col else None,
                   suggestions=suggestions(c, today), notes=notes(), every=plan_every(today))
        v["folded"] = D.fold_state(c.get("due_fold"), v, today)
        v["done"] = D.done_for_today(v)
        # 3.8.0: the morning's line, with Not today; 3.8.1: and what it opened, by date
        v["opened"] = _pf().opened_view() if mw.col else None
        more = {(x["pid"], x["uid"]): x for x in dates}
        for r in v.get("rows") or []:
            x = more.get((r.get("pid"), r.get("uid"))) if r.get("kind") == "plan" else None
            if x:  # 3.8.1: what due.view's rows don't carry: "after" its event, Study
                r["after"], r["study"] = bool(x.get("after")), bool(x.get("study"))
        v["qids"] = has_qids() if mw.col else False  # 3.9.3: QBank QIDs in the head
        # 3.9.5: today's misses (under a done Reviews row), a deck run out
        rv = next((r for r in v.get("rows") or [] if r.get("kind") == "reviews"), None)
        v["misses"] = _misses(mw.col) if mw.col and rv and rv.get("done") else None
        cl = _state.get("due_cleared")
        v["cleared"] = cl if isinstance(cl, dict) and cl.get("day") == today else None
        v["cleared_sev"] = _cleared_sev(v["cleared"]) if v["cleared"] else None
        # 3.9.5 (Sam: "where do I find superdecks?", "i don't see any super decks"): Today's Super decks,
        # the Due Crew decks with cards in them and the ones ready to make today
        v["supers"] = supers(c, v) if mw.col else []
        if v["misses"] and v["supers"]:
            v["misses"]["in_deck"] = True  # Today's misses is a super deck there; the line says where they were
        # 3.8.1: "Fifteen?", when the day hasn't started by my usual time
        from . import rooms
        v["nudge"] = rooms.nudge(c, v, _day_state()[1].get("dismissed") or ())
        v["nudge_sev"] = rooms.nudge_sev() if v["nudge"] else None
    except Exception:
        traceback.print_exc()
        return None
    v["toast"] = _toast()
    return v


def _toast():
    t = _state.get("due_toast")
    if t and time.time() - t[0] < 20:
        return t[1]
    _state["due_toast"] = None
    return None


# ---- the morning and the refresh ----

def parts(col, idxs, today):
    """Main thread, with the refresh's deck reads: each date's resources
    (P.parts) for the dates the box shows today and behind."""
    if not today:
        return
    pf = _pf()
    state = pf._state_cfg()
    out, sibs, later = {}, {}, {}  # sibs: {pid: {uid: [counted, buried today]}}; later: {pid: {uid: n}}
    on_today = set()  # 3.9.3: the cards of today's dates, so the box's Other new cards are the rest
    for p in pf.followed():
        st = state.get(p["id"])
        if p.get("paused") or not st or not pf._deck_ok(col, st.get("deck_id")):
            continue
        idx = pf._index(col, st, idxs)
        applied = st.get("applied") or {}
        doc = p["doc"]
        prog = (_state.get("plan_progress") or {}).get(p["id"]) or {}
        for u in P.units(doc):
            opens = str(u.get("opens") or "")
            a = applied.get(u["id"])
            running = (not a and int((prog.get(u["id"]) or [0])[0]) > 0
                       and bool(u.get("even") or p.get("sched")))  # an even date part open (3.7.2)
            if P.own_pace(p):  # 3.8.0: at my own pace, the dates I opened
                opens = today if P.opened_here(applied, u, prog) else "9999"
            if opens == today or (opens < today and (a or running) and not str(a).startswith("skip:")):
                got = P.parts(idx, u, pf._swap(st), doc)
                if got:
                    out.setdefault(p["id"], {})[u["id"]] = got
                cids = idx.match(u, pf._swap(st), doc)
                sib = idx.siblings(cids)
                if sib[0]:
                    sibs.setdefault(p["id"], {})[u["id"]] = list(sib)
                back = len(cids & idx.again)  # 3.9.3: seen, back later today: not through for today
                if back:
                    later.setdefault(p["id"], {})[u["id"]] = back
                if opens == today:
                    on_today |= cids
    _state["plan_parts"] = out
    _state["plan_sibs"] = sibs
    _state["plan_later"] = later
    _state["plan_today"] = sorted(on_today)


def leech_sets(rows, limits, out=()):
    """(deck, eight, extra): the leeches Recover takes, of rows [(card id,
    note id, lapses, queue, its home deck)] of notes tagged leech whose
    card lapsed. A suspended one always; one Anki kept in my reviews (Tag
    Only) at its deck's leech count (limits: {deck id: (leech count,
    action)}, leech_flow._limits; 3.9.3, Sam's pick A: one meaning of a
    leech, as Insights' Leeches counts them), or at 8 lapses (Recover's
    line until 3.9.3); extra: the ones only the deck's count takes. None I
    left out (Leeches' Leave it out). Pure."""
    deck, eight = [], []
    for cid, _nid, lapses, queue, did in rows:
        cid, lapses = int(cid), int(lapses or 0)
        if cid in out or lapses <= 0:
            continue
        if int(queue) == -1:
            deck.append(cid)
            eight.append(cid)
            continue
        if lapses >= int((limits.get(int(did)) or (8, 0))[0]):
            deck.append(cid)
        if lapses >= 8:
            eight.append(cid)
    has = set(eight)
    return deck, eight, [c for c in deck if c not in has]


def _leech_rows(col):
    return col.db.all(
        "SELECT c.id, c.nid, c.lapses, c.queue, CASE WHEN c.odid THEN c.odid ELSE c.did END FROM cards c "
        "JOIN notes n ON n.id = c.nid WHERE (' ' || lower(n.tags) || ' ') LIKE '% leech %' AND c.lapses > 0 "
        "ORDER BY c.id LIMIT 20000")


def leech_plan(col, out=()):
    """(deck, eight, extra, counts): leech_sets over this collection, and the
    leech counts of the decks the extra ones are in (for the question)."""
    from . import leech_flow
    rows = _leech_rows(col)
    limits = leech_flow._limits(col, {int(r[4]) for r in rows}, {})
    deck, eight, extra = leech_sets(rows, limits, out)
    of = {int(r[0]): int(r[4]) for r in rows}
    counts = sorted({int(limits[of[c]][0]) for c in extra if of.get(c) in limits})
    return deck, eight, extra, counts


def recover_leeches(col, label="Due Crew: recover leeches", cap=RECOVER_MAX, cids=None, reach="deck", out=()):
    """Leeches back as new cards: the leech tag off, unsuspended, and reset
    (Anki's own Forget, back to their place among the new cards), as one
    undo step. A leech: leech_sets' (by its deck's leech count; reach
    "eight", Recover's 8 lapses, for one who said Not these), or these
    cids. A note's other cards are left alone. Returns the card ids."""
    if cids is None:
        deck, eight, _extra, _n = leech_plan(col, out)
        cids = eight if reach == "eight" else deck
    cids = [int(c) for c in cids][:int(cap)]
    if not cids:
        return []
    nids = sorted({int(n) for n in col.db.list(f"SELECT nid FROM cards WHERE id IN ({','.join(map(str, cids))})")})
    pos = None
    if hasattr(col, "add_custom_undo_entry"):
        try:
            pos = col.add_custom_undo_entry(label)
        except Exception:
            pos = None
    col.tags.bulk_remove(nids, "leech")
    col.sched.unsuspend_cards(cids)
    col.sched.schedule_cards_as_new(cids, restore_position=True, reset_counts=True)
    if pos is not None and hasattr(col, "merge_undo_entries"):
        try:
            col.merge_undo_entries(pos)
        except Exception:
            pass
    return cids


def _left_out():
    try:
        from . import leech_flow
        return leech_flow._out()
    except Exception:
        return set()


def morning(c):
    """Once per Anki day, at the refresh: recover leeches when asked. Only on
    the Decks screen: mid-review its undo step would sit on my last answer
    (as the plans' morning waits for Decks). 3.9.3 (Sam's pick A): by each
    deck's own leech count. The first morning that would take leeches
    Recover's old line (8 lapses) left in my reviews, it takes what it
    always took and asks once about the rest (this profile's plans.json,
    `leech_reach`: "deck", or "eight" after Not these; switching Recover
    off and on asks again)."""
    if not c.get("due_leeches") or not mw.col or not _today() or getattr(mw, "state", "") != "deckBrowser":
        return
    pc, st = _day_state()
    if st.get("leeches_done"):
        return
    st["leeches_done"] = True
    ask = None
    try:
        reach = pc.get("leech_reach")
        deck, eight, extra, counts = leech_plan(mw.col, _left_out())
        if reach is None and not extra:
            reach = pc["leech_reach"] = "deck"  # nothing the old line left: the deck's count, no question
        if reach is None:
            ask = (len(extra), counts)
        st["recovered"] = recover_leeches(mw.col, cids=eight if reach != "deck" else deck)
    except Exception:
        traceback.print_exc()
        st["recovered"] = []
    _put_day(pc, st)
    if st["recovered"]:
        _pf()._after_change()
    if ask:
        from aqt.qt import QTimer
        QTimer.singleShot(0, lambda: ask_reach(*ask))


def ask_reach(n, counts):
    """The one question: the leeches only the deck's count takes, learned
    fresh too (one undo step), or Not these (Recover keeps to 8 lapses)."""
    from . import sheets
    gen = app.generation
    count = (f"your deck's leech count ({counts[0]} lapses)" if len(counts) == 1 else "your decks' leech counts")
    them = "them" if n != 1 else "it"
    sheets.confirm(f"Learn {n:,} more leech{'es' if n != 1 else ''} fresh?",
                   f"Anki tagged {them} at {count} and kept {them} in your reviews. Recover took only suspended "
                   f"leeches and ones at 8 lapses. Edit › Undo puts {them} back.",
                   "Learn them fresh" if n != 1 else "Learn it fresh",
                   lambda: gen == app.generation and set_reach(True),
                   no=lambda: gen == app.generation and set_reach(False), no_label="Not these")


def set_reach(wide):
    """The question's answer, for good (on this profile): the deck's count,
    and today's extra ones now; or Recover's 8 lapses."""
    pc = _pf()._pcfg()
    pc["leech_reach"] = "deck" if wide else "eight"
    _pf()._psave(pc)
    if not wide or not mw.col:
        return
    _deck, _eight, extra, _n = leech_plan(mw.col, _left_out())
    try:
        got = recover_leeches(mw.col, cids=extra)
    except Exception:
        traceback.print_exc()
        return
    pc, st = _day_state()
    st["recovered"] = list(st.get("recovered") or []) + got
    st["dismissed"] = [d for d in st.get("dismissed") or [] if d != "recovered"]
    _put_day(pc, st)
    if got:
        _pf()._after_change()
        tooltip(f"{len(got):,} leeches back as new cards. Edit › Undo puts them back." if len(got) != 1
                else "1 leech back as a new card. Edit › Undo puts it back.")


def recover_now():
    """3.8.0: Recover leeches switched on: today's go now, and it says what
    happened (it waited for the next refresh and said nothing). 3.9.3:
    switched on, its one question can come again."""
    c = cfg()
    if not c.get("due_leeches") or not mw.col or not _today():
        return
    pc, st = _day_state()
    st["leeches_done"] = False
    pc.pop("leech_reach", None)
    _put_day(pc, st)
    morning(c)
    _pc, st = _day_state()
    n = len(st.get("recovered") or [])
    tooltip((f"{n:,} leeches back as new cards. Edit › Undo puts them back." if n != 1
             else "1 leech back as a new card. Edit › Undo puts it back.")
            if n else "No leeches to recover now. Each morning looks again.")


def after_refresh():
    """Every refresh: a fresh reviews count, and the morning (once a day)."""
    _state["due_reviews"] = None
    try:
        exam_gone(cfg())
        morning(cfg())
    except Exception:
        traceback.print_exc()


def exam_gone(c):
    """3.9.5 (Sam: "when an exam date passes let's remove it"): the Anki day
    after my exam, its date comes off as × takes it (settings_model's
    setexam: kept as my last exam, so the next one's scope starts after
    it); the crew stops seeing it with the next sync. True when it went."""
    ex, today = str(c.get("exam_date") or ""), _today()
    if not ex or not today or ex >= today:
        return False
    from .settings_model import change
    try:
        changed = change(["setexam", "off"], c, today=datetime.date.fromisoformat(today))
    except ValueError:
        return False
    if not changed:
        return False
    c.update(changed)
    save_cfg(c)
    try:
        from . import ahead_flow
        ahead_flow.exam_moved()  # a pause to it ends with it
    except Exception:
        traceback.print_exc()
    return True


# ---- clicks ----

def _swap(c):
    if app.swap:
        app.swap(c)


def add(c, when, text, raw=False):
    """dueadd: `when` the add line's day button (today, later, a day), and
    a day said at the end of the text wins unless `raw`."""
    today = _today()
    if not today:
        return
    text = " ".join(unquote(text).split())
    day = today if when == "today" else "" if when == "later" else when
    rule = None
    if not raw:
        text, rule = D.parse_repeat(text)  # 3.8.0: "every mon" first
        if not rule:
            text, said = D.parse(text, today)
            if said is not None:
                day = said
    if not D.day_ok(day, today):
        day = today
    items = D.prune(_items(c), today)
    items, it = D.add(items, text, day, today, rule=rule)
    if not it:
        tooltip("That's 60 open. Tick or delete some first." if D.open_count(items) >= D.MAX_OPEN else "Nothing to add.")
        return
    _save(c, items=items)
    tab = c.get("due_tab", "today")
    if it.get("r"):
        shown = tab == "upcoming" or (tab == "today" and D.on_day(it, today))
        if not shown:
            _state["due_toast"] = (time.time(), {"text": "Added, " + D.repeat_label(it["r"]), "tab": "upcoming"})
    else:
        shown = (tab == "later" and not day) or (tab == "today" and day == today) or (
            tab == "upcoming" and day and day <= D.iso(D.d(today) + datetime.timedelta(days=D.AHEAD)))
    if not shown and not it.get("r"):
        _state["due_toast"] = (time.time(), {"text": "Added to " + (D.long_day(day, today) if day else "Later"),
                                             "tab": "later" if not day else "upcoming"})
    _swap(c)


def item_menu(c, ident):
    """⋯ on one of my items: its day, Edit…, Delete."""
    from aqt.qt import QMenu, QCursor
    today = _today()
    items = _items(c)
    it = next((x for x in items if x["id"] == ident), None)
    if not it or not today:
        return
    m = QMenu(mw)
    tomorrow = D.iso(D.d(today) + datetime.timedelta(days=1))
    if it.get("r"):
        # 3.8.0: a repeat has no day to move to; it stops instead
        m.addAction("Edit…").triggered.connect(lambda: _edit(ident))
        m.addAction("Stop repeating").triggered.connect(lambda: stop_repeat(cfg(), ident))
        m.addSeparator()
        m.addAction("Delete").triggered.connect(lambda: delete(cfg(), ident))
        m.exec(QCursor.pos())
        return

    def move(day):
        c2 = cfg()
        _save(c2, items=D.change(_items(c2), ident, today, d=day))
        _swap(c2)
    for label, day in (("Today", today), ("Tomorrow", tomorrow), ("Later", "")):
        a = m.addAction(label)
        a.setCheckable(True)
        a.setChecked(it["d"] == day)
        a.triggered.connect(lambda _=False, day=day: move(day))
    m.addAction("Pick a day…").triggered.connect(lambda: _pick_day(ident, it["d"] or tomorrow))
    m.addSeparator()
    m.addAction("Edit…").triggered.connect(lambda: _edit(ident))
    m.addAction("Delete").triggered.connect(lambda: delete(cfg(), ident))
    m.exec(QCursor.pos())


def _pick_day(ident, start):
    from aqt.qt import QDialog, QVBoxLayout, QCalendarWidget, QDate, QDialogButtonBox
    from .ui import heading, styled
    today = _today()
    dlg = styled(QDialog(mw))  # 3.9.1: the board's look, as every window
    dlg.setWindowTitle("Pick a day")
    lay = QVBoxLayout(dlg)
    heading(dlg, lay)
    cal = QCalendarWidget(dlg)
    t, s = D.d(today), D.d(start if start >= today else today)
    cal.setMinimumDate(QDate(t.year, t.month, t.day))
    mx = t + datetime.timedelta(days=D.MAX_AHEAD_DAYS)
    cal.setMaximumDate(QDate(mx.year, mx.month, mx.day))
    cal.setSelectedDate(QDate(s.year, s.month, s.day))
    lay.addWidget(cal)
    bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    lay.addWidget(bb)
    if dlg.exec():
        q = cal.selectedDate()
        day = datetime.date(q.year(), q.month(), q.day()).isoformat()
        c = cfg()
        _save(c, items=D.change(_items(c), ident, today, d=day))
        _swap(c)


def _edit(ident):
    from . import sheets
    c = cfg()
    it = next((x for x in _items(c) if x["id"] == ident), None)
    if not it:
        return

    def save(text):
        if " ".join(str(text).split()):
            c = cfg()
            _save(c, items=D.change(_items(c), ident, _today(), t=text))
            _swap(c)
    sheets.ask_text("Edit to-do", "", save, value=it["t"], most=D.MAX_TEXT)


def delete(c, ident):
    _save(c, items=D.remove(_items(c), ident))
    _swap(c)


def stop_repeat(c, ident):
    """3.8.0: a repeat becomes a one-off today."""
    _save(c, items=D.change(_items(c), ident, _today(), r=""))
    _swap(c)


def tick(c, ident):
    items = _items(c)
    it = next((x for x in items if x["id"] == ident), None)
    if it:
        today = _today()
        _save(c, items=D.change(items, ident, today, done=not D.done_on(it, today)))
        _swap(c)


def todo_tick(c, key):
    """An author's line, ticked by hand (only once its date has opened); a
    weekly one (3.8.0) for today, on its day."""
    today = _today()
    pid, uid, _h = (key.split(":") + ["", "", ""])[:3]
    if uid == "every":
        p, _ln = _every_line(key, today)
        if not p:
            return
        ticks = _ticks(c)
        if ticks.get(key) == today:
            ticks.pop(key, None)
        else:
            ticks[key] = today
        _save(c, ticks=D.clean_ticks(ticks))
        _swap(c)
        return
    dates, _e, _r = plan_dates(today)
    x = next((x for x in dates if x["pid"] == pid and x["uid"] == uid), None)
    keys = D.line_keys(pid, uid, (x or {}).get("todo"))
    if not x or key not in keys or x["opens"] > today:
        return
    n = keys.index(key)
    ticks = _ticks(c)
    if D.line_ticked(x, ticks)[n]:
        ticks.pop(key, None)
        ticks.pop(D.todo_key(pid, uid, n), None)  # one from before 3.7.2
    else:
        ticks[key] = today
    _save(c, ticks=D.clean_ticks(ticks))
    _swap(c)


def open_link(key):
    """An author's line's link, in the browser: only an https one on a date I follow."""
    pid, uid, _h = (key.split(":") + ["", "", ""])[:3]
    if uid == "every":
        _p, ln = _every_line(key, _today(), any_day=True)
        if ln and str(ln.get("url") or "").startswith("https://"):
            from aqt.utils import openLink
            openLink(ln["url"])
        return
    dates, _e, _r = plan_dates(_today())
    x = next((x for x in dates if x["pid"] == pid and x["uid"] == uid), None)
    todo = (x or {}).get("todo") or []
    keys = D.line_keys(pid, uid, todo)
    if key in keys and str(todo[keys.index(key)].get("url") or "").startswith("https://"):
        from aqt.utils import openLink
        openLink(todo[keys.index(key)]["url"])


def go(key):
    """A suggestion's or a note's button."""
    if not mw.col:
        return
    pf = _pf()
    if key == "again" or (key[:5] == "again" and key[5:].isdigit()):
        # 3.9.5: Study the N again, under the Reviews row once it's done: the reviews I missed today
        # (it had no way in since 3.8.1), or a part's alone (again0, again1, ...: its link on the line);
        # what's answered since is how the line says they've been gone over
        m = _misses(mw.col)
        cids = m["cids"]
        if key != "again":
            got = m["topics"][int(key[5:])] if int(key[5:]) < len(m["topics"]) else None
            cids = got[1] if got else []
        if cids and pf._filtered(mw.col, MISSES, cids):
            c = pf._pcfg()
            c["misses_day"] = pf._today()  # 3.8.1: the next morning empties it back if it's left
            c["misses_built"] = {"day": pf._today(), "at": time.time(), "cids": cids}
            pf._psave(c)
            pf._after_change()
            did = mw.col.decks.id_for_name(MISSES)
            if did:
                mw.col.decks.select(did)
                mw.moveToState("overview")
    elif key == "slow":
        from . import habits_flow  # 3.9.5: How you study's deck, from Next up
        habits_flow.study_slow()
    elif key == "near":
        did = _today_deck(mw.col)  # 3.9.5: Next up's cards one miss from a leech: Insights' leeches view
        if did:
            from . import leech_flow, team_flow
            team_flow.go_insights(did)
            leech_flow.open_view(did)
    elif key in ("leeches", "recovered"):
        import aqt
        browser = aqt.dialogs.open("Browser", mw)
        if key == "leeches":
            browser.search_for("tag:leech")
        else:
            _pc, st = _day_state()
            cids = st.get("recovered") or []
            if cids:
                browser.search_for("cid:" + ",".join(str(int(x)) for x in cids))


def dismiss(key):
    if key == "cleared":  # 3.9.5: Nice, on a deck that ran out
        _state["due_cleared"] = None
        _swap(cfg())
        return
    pc, st = _day_state()
    st["dismissed"] = list(dict.fromkeys(list(st.get("dismissed") or []) + [key]))[-20:]
    _put_day(pc, st)
    _swap(cfg())


def on_message(cmd, parts):
    """The board's Due commands (duetab, dueadd, …). True when handled."""
    c = cfg()
    arg = parts[2] if len(parts) > 2 else ""
    if cmd == "duetab" and arg in YOU_TABS:
        if arg in (c.get("hidden_tabs") or []):
            c["hidden_tabs"] = [k for k in c["hidden_tabs"] if k != arg]  # a link to it shows it again
        c["due_tab"] = arg
        c["due_fold"] = {"day": _today(), "folded": False}
        save_cfg(c)
        _state["due_toast"] = None
        _swap(c)
    elif cmd == "duefold":
        # Hide or Show by hand: it holds for today; tomorrow Due decides again
        c["due_fold"] = {"day": _today(), "folded": not folded(c, view(c))}
        save_cfg(c)
        _swap(c)
    elif cmd == "dueadd" and len(parts) > 4:
        # dueadd:WHEN:RAW:text (the text URI-encoded, so it may hold ":")
        add(c, arg, ":".join(parts[4:]), raw=parts[3] == "1")
    elif cmd == "duetick" and arg:
        tick(c, arg)
    elif cmd == "dueitem" and arg:
        item_menu(c, arg)
    elif cmd == "duedo" and arg:
        _save(c, items=D.change(_items(c), arg, _today(), d=_today()))
        _swap(c)
    elif cmd == "duetodo" and len(parts) > 4:
        todo_tick(c, ":".join(parts[2:5]))
    elif cmd == "duelink" and len(parts) > 4:
        open_link(":".join(parts[2:5]))
    elif cmd == "duego" and arg:
        go(arg)
    elif cmd == "duedeck" and arg.isdigit():
        study_ours(int(arg))  # 3.9.5: a Due Crew deck's row
    elif cmd == "duedeckx" and arg.isdigit():
        put_back(int(arg))
    elif cmd == "duestudy":
        study_today()  # 3.8.0
    elif cmd == "duex" and arg:
        dismiss(arg)
    elif cmd == "dueshow" and arg in D.TABS:
        c["due_tab"] = arg
        save_cfg(c)
        _state["due_toast"] = None
        _swap(c)
    else:
        return False
    return True


# ---- 3.8.0: Study today, one button through the day ----

def _plan_decks():
    """The decks of the plans I follow (not paused), in plan order."""
    pf = _pf()
    st = pf._state_cfg()
    out = []
    for p in pf.followed():
        did = (st.get(p["id"]) or {}).get("deck_id")
        if p.get("paused") or not did or not pf._deck_ok(mw.col, did) or int(did) in out:
            continue
        out.append(int(did))
    return out


def _due_now(col, dids, tree=None):
    """{deck id: cards Anki would show now} for these decks and every top
    deck, from Anki's deck tree (its limits, its subdecks)."""
    out = {}

    def walk(node, top):
        if top or int(node.deck_id) in dids:
            out[int(node.deck_id)] = int(node.review_count) + int(node.learn_count) + int(node.new_count)
        for ch in node.children:
            walk(ch, False)
    for ch in (tree or deck_tree(col)).children:
        walk(ch, True)
    return out


def study_today():
    """Study today › (the box, its folded line, Ctrl+Shift+S, a Fifteen):
    the walk starts. Plans' decks first, then the deck with the most due,
    each in Anki's own review; it goes on when a deck runs out and ends
    when I leave the review. It never builds a deck (3.8.1)."""
    if not mw.col:
        return
    _state["study_walk"] = {"steps": 0}
    study_step(first=True)


def study_step(first=False):
    w = _state.get("study_walk")
    if not w or not mw.col:
        return
    w["steps"] += 1
    step = None
    if w["steps"] <= D.STUDY_STEPS:
        try:
            plan = _plan_decks()
            step = D.study_next(plan, _due_now(mw.col, set(plan)))
        except Exception:
            traceback.print_exc()
    if step:
        return _study_deck(step[1], first)
    _state["study_walk"] = None
    r = _reviews() or {}
    back = int(r.get("back") or 0)
    tooltip(f"Done for now · {back:,} learning card{'s' if back != 1 else ''} back at {r.get('at')}"
            if back and r.get("at") else "Nothing due now." if first else "Done for today.")
    if not first and getattr(mw, "state", "") != "deckBrowser":
        mw.moveToState("deckBrowser")


def _study_deck(did, first, label=None):
    try:
        mw.col.decks.select(int(did))
        if not first:
            tooltip("Next: " + (label or mw.col.decks.name(int(did))), period=2500)
        _state["study_walk"]["deck"] = int(did)
        mw.moveToState("review")
    except Exception:
        traceback.print_exc()
        _state["study_walk"] = None


def walk_keys(state, shortcuts):
    """Escape while Study today walks the review: the walk stops there, the
    deck stays open (Anki's review has no Escape of its own)."""
    if state == "review" and _state.get("study_walk"):
        shortcuts.append(("Esc", stop_walk))


def stop_walk():
    if _state.get("study_walk"):
        _state["study_walk"] = None
        tooltip("Study today stopped. This deck stays open.")


def _ours(col, did):
    """A Due Crew deck's own name (the part after Due Crew's parent), when
    did is a filtered deck of ours; else None."""
    try:
        d = col.decks.get(int(did), default=False)
        name = str(col.decks.name(int(did)) or "")
    except Exception:
        return None
    if not d or not d.get("dyn") or not name.startswith(P.PARENT + "::"):
        return None
    return name.split("::")[-1]


def supers(c, v):
    """3.9.5: Today's Super decks, [{name, n, cmd, x?}]: every Due Crew deck
    with cards in it (its Study goes into it, × puts them back), then the
    ones ready to make today that aren't made: Today's misses (a review I
    missed today), Slow but right (How you study, when my log shows it),
    and, once the reviews are through, Before my exam (Insights' Study N
    early, an exam within NEXT_EXAM_DAYS with NEXT_EXAM_MIN at risk).
    Study on one of those makes it."""
    out = [dict(d, cmd=f"duedeck:{d['did']}", x=f"duedeckx:{d['did']}") for d in _our_decks(mw.col)]
    have = {d["name"] for d in out}
    try:
        n = len(_misses(mw.col)["cids"])
        if n and MISSES.split("::")[-1] not in have:
            out.append({"name": MISSES.split("::")[-1], "n": n, "cmd": "duego:again"})
        from . import habits_flow
        slow = habits_flow.next_up()
        if slow and habits_flow.DECK not in have:
            out.append({"name": habits_flow.DECK, "n": int(slow["n"]), "cmd": "duego:slow"})
        ex = _exam_ready(c, v)
        if ex and ex["name"] not in have:
            out.append(ex)
    except ImportError:
        pass
    except Exception:
        traceback.print_exc()
    return out


def _exam_ready(c, v):
    """Before my exam, as a super deck ready to make: only once the day's
    reviews are through (Insights is worked out for it then, as Next up's)."""
    rv = next((r for r in v.get("rows") or [] if r.get("kind") == "reviews"), None)
    if rv and not rv.get("done"):
        return None
    from . import team_flow
    did = _today_deck(mw.col)
    if not did:
        return None
    d = next((x for x in team_flow.you_decks() if x["did"] == did), None)
    view = team_flow.insights(did, (d or {}).get("pid"), str(c.get("exam_date") or "")) or {}
    aim, hero = view.get("aim") or {}, view.get("hero") or []
    if not (aim.get("name") and int(aim.get("in") or 99) <= NEXT_EXAM_DAYS and len(hero) >= NEXT_EXAM_MIN):
        return None
    _cids, title = team_flow._pick(did, "h")
    return {"name": title, "n": len(hero), "cmd": f"insstudy:{did}:h"}


def _our_decks(col):
    """3.9.5: [{did, name, n}] Due Crew's filtered decks (under its parent)
    with cards in them, as Anki's deck list has them. Main thread."""
    out = []
    try:
        for d in col.decks.all_names_and_ids(include_filtered=True):
            name = str(d.name or "")
            if not name.startswith(P.PARENT + "::") or not _ours(col, int(d.id)):
                continue
            n = int(col.db.scalar("SELECT count() FROM cards WHERE did = ?", int(d.id)) or 0)
            if n:
                out.append({"did": int(d.id), "name": name.split("::")[-1], "n": n})
    except Exception:
        traceback.print_exc()
    return out


def study_ours(did):
    """A Due Crew deck's row's Study: into it (Anki's overview), ours only."""
    if not mw.col or not _ours(mw.col, did):
        return
    mw.col.decks.select(int(did))
    mw.moveToState("overview")


def put_back(did):
    """A Due Crew deck's row's ×: its cards go back to their own decks
    (Anki's Empty, one undo step); the morning's tidy takes the empty deck."""
    if not mw.col or not _ours(mw.col, did):
        return
    try:
        mw.col.sched.empty_filtered_deck(int(did))
        _pf()._after_change()
    except Exception:
        traceback.print_exc()
    _swap(cfg())


def _cleared_sev(cl):
    """Pip hopping by a deck that ran out (a move from the hop's mix, never
    the last one); drawn again, it rests there. None with Pip off."""
    from . import rooms, sev
    if not rooms.sev_on():
        return None
    key = (cl.get("name"), cl.get("n"), cl.get("day"))
    have = _state.get("due_cleared_move")
    rest = isinstance(have, tuple) and have[0] == key
    if not rest:
        _state["due_cleared_move"] = (key, rooms.pick("hop"))
    return sev.slot(sev.move("hop", _state["due_cleared_move"][1], rest=rest, label="Pip: all cleared",
                             look=rooms.my_look()), 44)


def _watch_ours(new, old):
    """3.9.5: a Due Crew deck I studied that ran out says so on the board,
    with Pip (Nice puts it away). How many it held is counted as its review
    starts; it ran out when nothing's left in it as I leave the review."""
    col = mw.col
    if not col:
        return
    try:
        if new == "review":
            did = int(col.decks.get_current_id())
            name = _ours(col, did)
            had = _state.get("due_ours")
            if name and not (isinstance(had, dict) and had.get("did") == did):
                n = int(col.db.scalar("SELECT count() FROM cards WHERE did = ?", did) or 0)
                _state["due_ours"] = {"did": did, "name": name, "n": n}
            elif not name:
                _state["due_ours"] = None
            return
        had = _state.get("due_ours")
        if old != "review" or not isinstance(had, dict):
            return
        if not int(col.db.scalar("SELECT count() FROM cards WHERE did = ?", int(had["did"])) or 0) and int(had["n"]) > 0:
            _state["due_cleared"] = {"name": had["name"], "n": int(had["n"]), "day": _today()}
            _state["due_ours"] = None
    except Exception:
        traceback.print_exc()


def on_state(new, old):
    """Anki's screen changed: a walk goes on when its deck runs out (Anki's
    review hands over to the deck's overview with nothing left), and ends
    when I leave it any other way."""
    _watch_ours(new, old)
    if not _state.get("study_walk") or new == "review":
        return
    if new == "overview" and old == "review" and mw.col:
        try:
            left = sum(int(x) for x in mw.col.sched.counts())
        except Exception:
            left = 1
        if not left:
            from aqt.qt import QTimer
            QTimer.singleShot(0, study_step)
            return
    _state["study_walk"] = None
