"""Plans, the glue: today's set in the plan's deck (A) or a deck of its own (B), and the open itself."""

import html
import json

from aqt import mw
from aqt.utils import tooltip

from .. import app
from .. import plans as P
from .. import schedule as S
from ..app import _state
from ..app import cfg
from ..app import client
from ..app import save_cfg
from ..errs import oops

from .morning import NEW_ORDER, _after_change, _filtered, _note_built, _state_cfg
from .state import _deck_ok, _pcfg, _plan_doc, _psave, _swap, _today, followed, mine
from .cards import _index, _line_refresh, card_view, loads, offers_view, pick_names, progress, session_view, to_send


# ---- Today's lesson: in the plan's deck (A, the default), or a deck of its own (B) ----
# This computer's choice, per plan (plans.json `lesson_deck`; never sent). A
# opens a lesson's cards in the plan's deck, as ever. B opens them the same
# way, then each open lesson with cards to learn here is a filtered deck of
# its own, Due Crew::<plan>::<NN> <lesson>, in Anki's deck list; it goes with
# the morning's tidy once it's empty. A plan's state keeps `lesson_decks`
# {unit id: deck id}, `lesson_held` {unit id: cards another add-on's
# filtered deck holds} and `lesson_folder` (its folder's name, so a plan no
# longer followed here takes its decks along); `lesson_next` {plan id: true}
# is B chosen for a plan before it runs here.

LESSON_STEP = "Due Crew: sets' decks"
LESSON_OFF = "Due Crew: sets' decks off"


def lesson_deck_on(pid):
    """Today's lesson for this plan here: True, a deck of its own (B); False,
    in the plan's deck (A, the default). Main thread."""
    c = _pcfg()
    st = _state_cfg(c).get(pid)
    if st is not None:
        return bool(st.get("lesson_deck"))
    return bool((c.get("lesson_next") or {}).get(pid))


def set_lesson_deck(pid, on):
    """Today's lesson, chosen (Follow, Start it, Settings › Me on it). B builds
    the plan's open lessons' decks now; A empties and removes them (their
    cards go home, as they were); one undo step either way. A plan not
    running here yet keeps B for when it does (`lesson_next`). Main thread.
    True when the choice is kept."""
    if not mw.col:
        return False
    on = bool(on)
    c = _pcfg()
    state = _state_cfg(c)
    st = state.get(pid)
    if st is None:
        nxt = {k: v for k, v in (c.get("lesson_next") or {}).items() if k != pid}
        if on:
            nxt[pid] = True
        c["lesson_next"] = dict(list(nxt.items())[-50:])
        _psave(c)
        return True
    if on:
        st["lesson_deck"] = True
    else:
        st.pop("lesson_deck", None)
    c["plans"] = state
    _psave(c)
    changed = False
    try:
        if on:
            p = next((x for x in followed() if x["id"] == pid), None)
            changed = bool(p) and bool(_lesson_sync(mw.col, [p], state, _today()).get("work"))
        else:
            changed = bool(_lesson_drop(mw.col, st))
    except Exception:
        oops()
    c["plans"] = state
    _psave(c)
    if changed:
        _after_change()
    refresh_progress()
    app.swap(cfg())
    return True


def _take_next(c, pid, st):
    """B chosen for a plan before it ran here: its state takes it now."""
    nxt = c.get("lesson_next") or {}
    if st is not None and pid in nxt:
        if nxt.get(pid):
            st["lesson_deck"] = True
        c["lesson_next"] = {k: v for k, v in nxt.items() if k != pid}


def _dyn(col, did):
    """A filtered deck with this id is here."""
    try:
        d = col.decks.get(int(did), default=False) if did else None
    except Exception:
        return False
    return bool(d) and bool(d.get("dyn"))


def _open_lessons(p, st, today):
    """B: a plan's lessons open here, as I run it: opened here (not skipped),
    or, on a 3.2 schedule or even dates, opening in slices since their day;
    never one put off to a later morning (Not today, Welcome back's question)."""
    q = mine(p)
    applied, later = st.get("applied") or {}, st.get("later") or {}
    slices = bool(q.get("sched") or S.has_even(q["doc"])) and not P.own_pace(q)  # as run() opens them
    out = []
    for u in P.units(q["doc"]):
        if str(later.get(u["id"]) or "") > today:
            continue
        if P.opened_here(applied, u) or (slices and u["id"] not in applied and str(u.get("opens") or "9999") <= today):
            out.append(u)
    return out


def _fold_at(col, label):
    """The undo step to fold into: Anki's latest, while it's `label`'s."""
    try:
        st = col.undo_status()
        pos = getattr(st, "last_step", None)
        return pos if label and st.undo == label and pos is not None else None
    except Exception:
        return None


def _held_by(col, cids):
    """{card: the filtered deck holding it}, of these."""
    out = {}
    cl = sorted({int(c) for c in cids})
    for i in range(0, len(cl), 500):
        chunk = ",".join(str(c) for c in cl[i:i + 500])
        out.update({int(c): int(d) for c, d in col.db.all(f"SELECT id, did FROM cards WHERE odid != 0 AND id IN ({chunk})")})
    return out


def _lesson_sync(col, plan_list, state, today, fold=None):
    """B, main thread: each open lesson of these plans (the ones on B) with
    cards to learn here, a filtered deck of its own (P.lesson_deck): its open
    new cards and its learning ones due now (P.lesson_cards), as they come in
    the deck, Anki rescheduling them. Built when it has none, built again
    when it lacks some (an update added cards, a learning card came due),
    renamed when its name changed; one that holds them all is left as it is
    (a lesson behind keeps its deck till it's empty, then the morning's tidy
    takes it). A card another filtered deck holds stays there (Anki keeps a
    card in one); another add-on's are counted (`lesson_held`), for the
    plan's card. One undo step: `fold`'s (the open just made, so Not today
    and Undo take the decks too) while it's Anki's latest, else its own.
    Mutates `state`. {"work": decks built or renamed, "decks": {plan id:
    [unit ids with a deck]}}."""
    runs = [(p, state.get(p["id"])) for p in plan_list if p and (state.get(p["id"]) or {}).get("lesson_deck")]
    runs = [(p, st) for p, st in runs if _deck_ok(col, st.get("deck_id"))]
    if not runs:
        return {"work": 0, "decks": {}}
    names = {int(d.id): str(d.name) for d in col.decks.all_names_and_ids()}
    every = {pid: {int(d) for d in (st.get("lesson_decks") or {}).values()}
             for pid, st in state.items() if isinstance(st, dict)}
    jobs, out = [], {}
    for p, st in runs:
        q = mine(p)
        idx = P.DeckIndex(col, st["deck_id"])
        places = P.lesson_places(_plan_doc(p))
        folder = P.lesson_folder_free(p.get("name"), lambda n: bool(col.decks.id_for_name(n)) and _dyn(col, col.decks.id_for_name(n)))
        taken = set().union(*[v for k, v in every.items() if k != p["id"]])  # another plan's, by the same names
        mapped = {k: int(v) for k, v in (st.get("lesson_decks") or {}).items() if _dyn(col, v)}
        lessons = []
        for u in _open_lessons(p, st, today):
            name = P.lesson_deck(p.get("name"), places.get(u["id"], len(places) + 1), len(places), u.get("name"), folder=folder)
            did = mapped.get(u["id"])
            if did is None:  # a deck by its name (AnkiWeb brought it from another computer): its own
                by = col.decks.id_for_name(name)
                did = int(by) if by and _dyn(col, by) and int(by) not in taken else None
            lessons.append((u["id"], name, P.lesson_cards(idx, idx.match(u, _swap(st), q["doc"])), did))
        where = _held_by(col, {c for _u, _n, want, _d in lessons for c in want})
        held = {}
        for uid, name, want, did in lessons:
            have = set(col.db.list("SELECT id FROM cards WHERE did = ?", did)) if did else None
            other = {c for c in want if where.get(c) and where[c] != did}
            foreign = sum(1 for c in other if not P.ours(names.get(where[c], "")))
            if foreign:
                held[uid] = foreign
            kind = P.lesson_plan(want, have, other)
            if kind:
                jobs.append((p["id"], uid, name, [c for c in want if c not in other], did or 0))
            elif did and names.get(did) != name:
                jobs.append((p["id"], uid, name, None, did))  # renamed: the author's, or a lesson's place moved
            if did:
                mapped[uid] = did
        st["lesson_decks"], st["lesson_folder"] = mapped, folder
        if held:
            st["lesson_held"] = held
        else:
            st.pop("lesson_held", None)
    # one whose folder is a filtered deck can't be built (Anki nests nothing under one): left, so no empty undo step
    jobs = [j for j in jobs if not _dyn(col, col.decks.id_for_name(state[j[0]]["lesson_folder"]) or 0)]
    if jobs:
        pos = _fold_at(col, fold)
        if pos is None and hasattr(col, "add_custom_undo_entry"):
            try:
                pos = col.add_custom_undo_entry(LESSON_STEP)
            except Exception:
                pos = None
        try:
            for pid, uid, name, cids, did in jobs:
                st = state[pid]
                folder = st["lesson_folder"]
                had = col.decks.id_for_name(folder)
                try:
                    if cids is None:
                        col.decks.rename(did, name)
                        made = did
                    else:
                        made = _filtered(col, name, cids, order=NEW_ORDER, did=did)
                        made = col.decks.id_for_name(name) if made is True else made
                except Exception:
                    oops()
                    made = None
                if made:
                    st.setdefault("lesson_decks", {})[uid] = int(made)
                now = col.decks.id_for_name(folder)
                if now and not had and not _dyn(col, now):
                    _note_built(now)  # made with it, so the tidy may clear it
        finally:
            if pos is not None and hasattr(col, "merge_undo_entries"):
                try:
                    col.merge_undo_entries(pos)
                except Exception:
                    pass
    for p, st in runs:
        out[p["id"]] = [uid for uid, did in (st.get("lesson_decks") or {}).items() if _dyn(col, did)]
    return {"work": len(jobs), "decks": out}


def lesson_sync(plan_list, fold=None):
    """Main thread: _lesson_sync for these plans, saved; the screens redraw
    when a deck was built. Never raises."""
    if not mw.col or not plan_list:
        return {"work": 0, "decks": {}}
    c = _pcfg()
    state = _state_cfg(c)
    if not any((state.get(p["id"]) or {}).get("lesson_deck") for p in plan_list if p):
        return {"work": 0, "decks": {}}
    try:
        got = _lesson_sync(mw.col, plan_list, state, _today(), fold=fold)
    except Exception:
        oops()
        return {"work": 0, "decks": {}}
    c["plans"] = state
    _psave(c)
    if got["work"]:
        _after_change()
    return got


def _lesson_drop(col, st, uids=None, fold=None):
    """A plan's lesson decks (or just these lessons'), emptied and removed:
    their cards go home as they were. The ones it knows, and any filtered
    deck in its folder (AnkiWeb's, from another computer); then its folder
    once nothing's in it or under it. One undo step: fold's while it's
    Anki's latest (Put back's), else its own. Returns how many."""
    st = st or {}
    mapped = {k: int(v) for k, v in (st.get("lesson_decks") or {}).items()}
    ids = {d for k, d in mapped.items() if (uids is None or k in uids) and _dyn(col, d)}
    folder = st.get("lesson_folder")
    fid = col.decks.id_for_name(folder) if folder else None
    if uids is None and fid and not _dyn(col, fid):
        kids = [int(x) for x in col.decks.deck_and_child_ids(fid) if int(x) != int(fid)]
        # another plan's by the same name share the folder: theirs stay (3.9.6's review)
        theirs = {int(d) for s in _state_cfg().values() if isinstance(s, dict)
                  for d in (s.get("lesson_decks") or {}).values()} - set(mapped.values())
        ids |= {k for k in kids if _dyn(col, k) and k not in theirs}
        if set(kids) <= ids and int(fid) in (_pcfg().get("built") or []) \
                and not col.db.scalar("SELECT count() FROM cards WHERE did = ? OR odid = ?", int(fid), int(fid)):
            ids.add(int(fid))  # empty and ours: removing it can't take a card with it
    for k in [k for k, d in mapped.items() if d in ids or not _dyn(col, d)]:
        mapped.pop(k, None)
    st["lesson_decks"] = mapped
    if uids is None:
        st.pop("lesson_held", None)
    else:
        for k in uids:
            (st.get("lesson_held") or {}).pop(k, None)
    if not ids:
        return 0
    pos = _fold_at(col, fold)
    if pos is None and hasattr(col, "add_custom_undo_entry"):
        try:
            pos = col.add_custom_undo_entry(LESSON_OFF)
        except Exception:
            pos = None
    try:
        col.decks.remove(sorted(ids))
    finally:
        if pos is not None and hasattr(col, "merge_undo_entries"):
            try:
                col.merge_undo_entries(pos)
            except Exception:
                pass
    return len(ids)


def _lesson_prune(col, state):
    """Each plan's lesson decks, the ones still here (an undo took some away)."""
    for st in state.values():
        if isinstance(st, dict) and st.get("lesson_decks"):
            st["lesson_decks"] = {k: int(v) for k, v in st["lesson_decks"].items() if _dyn(col, v)}


def _lesson_did(pid, uid):
    """B: the deck a lesson is in now, with cards in it; None otherwise."""
    st = _state_cfg().get(pid) or {}
    did = (st.get("lesson_decks") or {}).get(uid)
    if not did or not mw.col or not _dyn(mw.col, did):
        return None
    return int(did) if mw.col.db.scalar("SELECT count() FROM cards WHERE did = ?", int(did)) else None


def _go_deck(did):
    """Anki's Study screen on a deck."""
    try:
        mw.col.decks.select(int(did))
        mw.moveToState("overview")
        return True
    except Exception:
        oops()
        return False


def lesson_view(plan, st, today):
    """B's part of the plan's card (None on A): today's lesson with a deck
    (its unit id; the first, if two open today), and the cards of open
    lessons another add-on's filtered deck holds, so the card can say so."""
    if not st or not st.get("lesson_deck"):
        return None
    decks = st.get("lesson_decks") or {}
    todays = [u["id"] for u in P.units(mine(plan)["doc"]) if str(u.get("opens") or "") == today]
    first = next((x for x in todays if x in decks), todays[0] if todays else None)
    return {"today": first, "held": sum(int(n) for n in (st.get("lesson_held") or {}).values())}


# 3.9.1: what refresh_progress leaves in _state; its last answer, and what it was read from
_WRITES = ("plan_progress", "plan_load", "plan_picks", "plan_reviews", "plan_session", "plan_parts", "plan_sibs",
           "plan_later", "plan_today")
_last = {"key": None, "got": None}


def _progress_key(col):
    """3.9.1: everything refresh_progress reads, as one value: the
    collection (every answer and op moves col.mod), the day, Due's day, the
    plans as the session has them, this profile's plan state, and the due
    now of each plan deck on my schedule (the clock moves a learning card's
    count, not a change). None when the collection can't say."""
    mod = getattr(col, "mod", None)
    if mod is None:
        return None
    try:
        plans = json.dumps(client().session.get("plans"))
        state = json.dumps(_state_cfg())
    except (TypeError, ValueError):
        return None
    due = tuple(_due_in(col, st["deck_id"]) for _p, st in _on_schedule(col, followed(), _state_cfg()))
    return (app.generation, id(col), mod, _today(), _state["labels"][0] if _state["labels"] else "", plans, state, due)


def refresh_progress():
    """Main thread: my numbers per unit, for the card and the next sync, and
    (3.2) today's session for the plans on my schedule. 3.9.1: asked again
    with nothing it reads changed (a sync and its commit ask one after the
    other), the last answer stands: the deck read again and the rest were
    about 280 ms on 35,000 cards."""
    if not mw.col:
        return {}
    key = _progress_key(mw.col)
    if key is not None and _last["key"] == key:
        _state.update({k: dict(v) if isinstance(v, dict) else v for k, v in _last["got"].items()})
        _note_recap(_state["plan_session"])
        return _state["plan_progress"]
    _last.update(key=None, got=None)
    idxs = {}  # each deck read once for both
    try:
        prog = progress(mw.col, followed(), _state_cfg(), idxs)
    except Exception:
        oops()
        return {}
    _state["plan_progress"] = prog
    _line_refresh(prog)  # 3.9.10: who waits in line, from these numbers
    whole = True  # kept for the next ask only when every part was read
    try:
        _state["plan_load"] = loads(mw.col, followed(), _state_cfg(), idxs)  # 3.7.81
    except Exception:
        whole = False
        oops()
    try:
        _state["plan_picks"] = pick_names(mw.col, followed(), _state_cfg(), idxs)  # 3.8.1
        if prog:
            _note_reviews(mw.col, _today())  # 3.8.1: my own load, beside what the plan opens
            _note_pace(mw.col, _today())  # 3.9.9: my pace, for the load across plans
    except Exception:
        whole = False
        oops()
    try:
        _state["plan_session"] = sessions(mw.col, followed(), _state_cfg(), _today(), idxs)
        _note_recap(_state["plan_session"])
    except Exception:
        whole = False
        oops()
    try:
        from .. import due_flow
        due_flow.parts(mw.col, idxs, _state["labels"][0] if _state["labels"] else _today())  # Due: each date's resources
    except Exception:
        whole = False
        oops()
    # a search about my own reviews (is:due, rated:…) is read at every refresh, as before
    if whole and key is not None and not any(idx._fresh for idx in idxs.values()):
        _last.update(key=key, got={k: dict(v) if isinstance(v, dict) else v for k, v in _state.items() if k in _WRITES})
    return prog


def _due_in(col, did):
    """Reviews (and learning cards) due now in a deck and its subdecks, when
    this Anki can say. 3.9.1: its node in the deck tree Due reads too, as
    Anki's deck_due_tree(did) finds it, not a whole tree of its own each time."""
    try:
        from .. import due_flow
        node = col.decks.find_deck_in_tree(due_flow.deck_tree(col), int(did))
        return int(node.review_count) + int(node.learn_count)
    except Exception:
        return None


def _answered(col, checks):
    """{cid: (ease, ms)}: each checkpoint card's first answer since its deck was built."""
    out = {}
    for c in checks.values():
        cids = [int(x) for x in (c.get("cids") or [])][:200]
        if not cids:
            continue
        rows = col.db.all(
            f"SELECT cid, ease, MIN(id) FROM revlog WHERE ease > 0 AND id >= ? AND cid IN ({','.join(map(str, cids))}) "
            "GROUP BY cid", int(c.get("at") or 0))
        out.update({int(cid): (int(e), int(t)) for cid, e, t in rows or []})
    return out


def new_limit(col, did):
    """3.3, C1: how many new cards Anki shows today in this deck: its own
    today-only or deck limit, else its options preset's. None if unknown."""
    try:
        deck = col.decks.get(int(did))
        today = int(col.sched.today)
        t = deck.get("newLimitToday") or {}
        if isinstance(t, dict) and t.get("today") == today and t.get("limit") is not None:
            return int(t["limit"])
        if deck.get("newLimit") is not None:
            return int(deck["newLimit"])
        return int(col.decks.config_dict_for_deck_id(int(did))["new"]["perDay"])
    except Exception:
        return None


def raise_limit(pid):
    """3.3, C1: Raise to today's plan, on this deck's own limit (Deck
    Options › This deck), so every other deck stays as it is. Anki's own
    undo step: Edit › Undo puts it back."""
    v = (_state.get("plan_session") or {}).get(pid) or {}
    st = _state_cfg().get(pid)
    want = int(v.get("target") or 0)
    if not st or not mw.col or not want:
        return
    col, did = mw.col, int(st["deck_id"])
    if _paused(col, did):
        tooltip("New cards are stopped in this deck. Turn them back on in Insights first.")
        return
    was = new_limit(col, did)
    pos = None
    try:
        pos = col.add_custom_undo_entry("Due Crew: new cards a day")
    except Exception:
        pos = None
    try:
        deck = col.decks.get(did)
        deck["newLimit"] = want
        deck.pop("newLimitToday", None)
        col.decks.save(deck)
    except Exception:
        oops()
        tooltip("Couldn't change it. Deck Options › New cards/day.")
        return
    if pos is not None:
        try:
            col.merge_undo_entries(pos)
        except Exception:
            pass
    _after_change()
    was_s = f" (was {was:,})" if was is not None else ""
    tooltip(f"New cards a day in {html.escape(col.decks.get(did)['name'])}: {want:,}{was_s}.")
    refresh_progress()
    app.swap(cfg())


def _on_schedule(col, plan_list, state):
    """[(plan, its state)] for the plans on my schedule here: not paused, not at my own pace."""
    todo = [(p, state.get(p["id"])) for p in plan_list if not p.get("paused") and not P.own_pace(p)]
    return [(p, st) for p, st in todo if st and _deck_ok(col, st.get("deck_id"))]


def sessions(col, plan_list, state, today, idxs=None):
    """{plan id: session_view} for the plans on my schedule, on this computer."""
    from ..stats.queries import StatsQueries
    q = StatsQueries(col)
    todo = _on_schedule(col, plan_list, state)
    if not todo:
        return {}
    first = q.first_seen(15)
    pace = q.pace()
    out = {}
    for p, st in todo:
        idx = _index(col, st, idxs)
        idx.fell_back = set()
        v = session_view(p, st, idx, first, today, pace, _due_in(col, st["deck_id"]),
                         _answered(col, st.get("checks") or {}))
        if v is not None:
            v["limit"] = new_limit(col, st["deck_id"])  # 3.3, C1
            v["paused_new"] = _paused(col, st["deck_id"])  # 3.9.2's audit: Stop new, not a low limit
            v["fell_back"] = len(idx.fell_back)          # 3.3, C5
        out[p["id"]] = v
    return out


def _note_recap(views):
    """On the first day of a plan week, the last one rides my week for the
    crew ("Week 3 done"): the first plan that has one."""
    cl = client()
    for pid, v in (views or {}).items():
        if v and v.get("recap"):
            p = next((x for x in followed() if x["id"] == pid), None)
            want = {"name": (p or {}).get("name") or "Plan", "n": v["recap"]["n"], "day": _today()}
            if cl.session.get("recap") != want:
                cl.session["recap"] = want
                cl._save_session()
            return


def for_sync():
    """Main thread, at every sync: progress on the plans I share it on.
    None when I follow nothing (and never did), so the sync is unchanged."""
    plan_list = followed()
    if not plan_list and not client().session.get("plans_hash"):
        return None
    return to_send(plan_list, refresh_progress())


def show_plans(c, swap=True):
    """3.8.0: the You bubble open on Plans (once the board's own tab), and
    Plans shown again if Settings had hidden it."""
    c["due_tab"] = "plans"
    c["due_fold"] = {"day": _today(), "folded": False}
    hidden = [k for k in (c.get("hidden_tabs") or []) if k != "plans"]
    if hidden != list(c.get("hidden_tabs") or []):
        c["hidden_tabs"] = hidden
    from .. import calm
    calm.release(c, ["plans"])
    calm.seen(c, "plans")
    save_cfg(c)
    if swap:
        app.swap(c)


def morning_opened():
    """3.8.0, Due's line under Today: {n} cards this morning opened, while
    Anki's latest step is still that one (Not today undoes it);
    None otherwise. Main thread."""
    pc = _pcfg()
    opened = pc.get("plans_opened") if isinstance(pc.get("plans_opened"), dict) else {}
    today = _today()
    if not today or opened.get("day") != today or not _undo_ok(opened.get("label")):
        return None
    n = sum(int(v[1] or 0) for v in (opened.get("per") or {}).values() if isinstance(v, (list, tuple)) and len(v) > 1)
    if not n:
        return None
    # Today's lesson, B: they're in decks of their own
    return dict({"n": n, "sync": _unsynced()}, **({"decks": True} if opened.get("decks") else {}))


OPENED_DATES = 60  # 3.8.1: the dates an open names, kept for its line


def opened_dates():
    """3.8.1: what the last open opened, by date: [[plan id, unit id, name,
    cards]], for the morning's line ("Renal physiology 80 · Antiarrhythmics
    40", each opening Browse on that date's new cards). Read only beside
    morning_opened(), which says whether the line shows at all."""
    pc = _pcfg()
    op = pc.get("plans_opened") if isinstance(pc.get("plans_opened"), dict) else {}
    return [[str(d[0]), str(d[1]), str(d[2]), int(d[3])] for d in op.get("dates") or []
            if isinstance(d, (list, tuple)) and len(d) >= 4 and int(d[3] or 0) > 0]


def opened_view():
    """morning_opened() with its dates (3.8.1), for Due's Today."""
    op = morning_opened()
    if op:
        op["dates"] = opened_dates()
    return op


def browse_opened(pid, uid):
    """3.8.1, a name on the morning's line: Anki's browser on that date's
    new cards that are open now (what the morning opened, and any new card
    of it open before)."""
    got = _plan_idx(pid)
    if not got:
        return
    _p, st, doc, idx = got
    u = next((x for x in P.units(doc) if x["id"] == uid), None)
    if u is None:
        return
    try:
        cids = {c for c in idx.match(u, _swap(st), doc) if idx.cards[c][1] == 0 and idx.cards[c][0] != -1}
    except Exception:
        oops()
        return
    _browse(cids, empty="None of its new cards are open now.")


def _unsynced():
    """3.8.0: this Anki signs in to AnkiWeb, and the collection changed
    since its last sync (both in ms): the morning's cards aren't on the
    phone yet."""
    try:
        return bool(mw.pm.sync_auth()) and int(mw.col.mod or 0) > int(mw.col.db.scalar("SELECT ls FROM col") or 0)
    except Exception:
        return False


def _undo_ok(label):
    try:
        return bool(label) and mw.col.undo_status().undo == label
    except Exception:
        return False


def board_view(c):
    """{cards, offers} for You › Plans, from cache. Main thread (no
    collection reads)."""
    plan_list = followed()
    pc = _pcfg()
    state = _state_cfg(pc)
    today = _state["labels"][0] if _state["labels"] else ""
    if not today:
        return {"cards": [], "offers": [], "invites": list(client().session.get("plan_invites") or [])}
    prog = _state.get("plan_progress") or {}
    here = lambda st: st if st and mw.col and _deck_ok(mw.col, st.get("deck_id")) else None
    sess = _state.get("plan_session") or {}
    cards = [card_view(p, here(state.get(p["id"])), prog.get(p["id"]), today, session=sess.get(p["id"]),
                       week_offset=(_state.get("plan_week") or {}).get(p["id"], 0))
             for p in plan_list]
    for card in cards:
        day = (_state.get("plan_focus") or {}).get(card["id"])
        if day:
            card["focus"] = day  # 3.8.0: Browse › Show on my plan
        try:
            joy(card, today)  # 3.9.6: what's happened to it since it was last looked at
        except Exception:
            oops()
    try:  # 3.9.9 (Sam's pick B): a plan's exam, asked once on its card
        ask = P.exam_offer(plan_list, (c or {}).get("exam_date"), today, (c or {}).get("exam_asked"),
                           (c or {}).get("exam_from"))
    except Exception:
        oops()
        ask = None
    for card in cards:
        if ask and str(card.get("id")) == ask["pid"]:
            card["exam_ask"] = ask
    from .. import team_flow
    for card in cards:
        try:
            card["tabs"] = team_flow.card_bits(card["id"])  # the squad line
        except Exception:
            oops()
    from ..squads import _my_squads
    names = {sq["id"]: sq.get("name") or "" for sq in _my_squads(c)}
    offers = offers_view(client().session.get("plan_offers"), names, {p["id"] for p in plan_list},
                         set(pc.get("plan_offers_dismissed") or []))
    # plans, end to end: the empty tab's line about my exam (Settings), while no plan I follow or
    # write ends by it; and whether I write any (its Your plans…)
    authored = client().session.get("plans_authored") or []
    ends = [P.last_day(p["doc"]) for p in plan_list] + [P.last_day(a.get("doc")) for a in authored]
    # 3.8.1: an invite to co-write a plan, or to keep one, from the day's first board; and
    # the morning's dates, for its line here when Due is off (__init__ hands over morning_opened())
    try:
        load = load_view(plan_list, state, today)  # 3.9.9: the week across plans
    except Exception:
        oops()
        load = None
    return {"cards": cards, "offers": offers, "load": load, "invites": list(client().session.get("plan_invites") or []),
            "opened_dates": opened_dates(), "exam": P.exam_way(str((c or {}).get("exam_date") or ""), today, ends),
            "writes": bool(authored)}


# Names of the parts after this one. The package sets them as each of those parts loads
# (an import here would load a later part before the ones between).
_LATER = ("_browse", "_note_pace", "_note_reviews", "_paused", "_plan_idx", "joy", "load_view")
_browse = _note_pace = _note_reviews = _paused = _plan_idx = joy = None
load_view = None
