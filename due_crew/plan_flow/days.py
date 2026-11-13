"""Plans, the glue: a follower's own days (skips, moves, slides, catch-up)."""

import html

from aqt import mw
from aqt.utils import tooltip

from .. import app
from .. import plans as P
from ..app import _state
from ..app import cfg
from ..app import client
from ..errs import oops

from .morning import NEW_ORDER, _after_change, _deck_name, _filtered, _state_cfg, opened_line
from .cards import _aside, named, open_one
from .state import _deck_ok, _pcfg, _psave, _swap, _today, followed, mine
from .lessons import lesson_sync, refresh_progress


# ---- G1-G5: a follower's own days ----

def _raw(pid):
    """The plan as the session keeps it (not my view of it)."""
    return next((p for p in client().session.get("plans") or [] if p.get("id") == pid), None)


def browse_date(pid, uid):
    """3.6.5, P7: Anki's browser on one date's cards in this copy (a search
    run here; nothing is sent)."""
    p = next((x for x in followed() if x["id"] == pid), None)
    st = _state_cfg().get(pid)
    if p is None or not st or not mw.col or not _deck_ok(mw.col, st.get("deck_id")):
        return
    pm = mine(p)
    u = next((x for x in P.units(pm["doc"]) if x["id"] == uid), None)
    if u is None:
        return
    try:
        cids = P.DeckIndex(mw.col, st["deck_id"]).match(u, _swap(st), pm["doc"])
    except Exception:
        oops()
        return
    _browse(cids)


def _browse(cids, q=None, empty="None of its cards are in your deck."):
    """Anki's browser on these cards: `q` when given (a search that finds
    just them), else by id. A search run here; nothing is sent."""
    if not cids:
        tooltip(empty)
        return
    import aqt
    browser = aqt.dialogs.open("Browser", mw)
    browser.search_for(q or "cid:" + ",".join(str(int(c)) for c in sorted(cids)))


def browse_tags(pid):
    """3.8.0: Browse on the plan's tags here (DueCrew::<the plan>::*)."""
    st = _state_cfg().get(pid) or {}
    path = next(iter((st.get("tags") or {}).values()), "")
    parts = str(path).split("::")
    if len(parts) < 3:
        tooltip("Its tags aren't in your Anki yet.")
        return
    got = _plan_idx(pid)
    if got and any(t.get("cards") for t in P.plan_tags(got[2])):
        # 3.8.1: a tag with single cards: just those, where Anki's tag shows their whole notes
        _p, st2, doc, idx = got
        cids = set()
        for t in P.plan_tags(doc):
            cids |= idx.plan_tag_cards(doc, t, _swap(st2))
        _browse(cids)
    else:
        import aqt
        browser = aqt.dialogs.open("Browser", mw)
        browser.search_for(P.tag_search("::".join(parts[:2])) + "::*\"")
    tags_seen(pid, swap=False)


def tags_seen(pid, swap=True):
    c = _pcfg()
    st = _state_cfg(c).get(pid)
    if st and st.pop("tag_news", None) is not None:
        _psave(c)
    if swap:
        app.swap(cfg())


def _plan_idx(pid):
    """(plan, its state, my doc, DeckIndex) for a plan I follow whose deck is
    here, else None."""
    p = next((x for x in followed() if x["id"] == pid), None)
    st = _state_cfg().get(pid)
    if p is None or not st or not mw.col or not _deck_ok(mw.col, st.get("deck_id")):
        return None
    return p, st, mine(p)["doc"], P.DeckIndex(mw.col, st["deck_id"])


def browse_left(pid, uids=()):
    """3.8.0: Anki's browser on what's left to see: a day's dates' cards I
    haven't seen ("16 left"), or with no dates, the opened cards of every
    date before today I haven't seen ("16 new behind")."""
    got = _plan_idx(pid)
    if not got:
        return
    p, st, doc, idx = got
    today = _today()
    applied = st.get("applied") or {}

    def mine(u):  # as Due's Behind counts (due_flow.plan_dates): opened here, or opening in slices; not skipped
        a = applied.get(u["id"])
        return not str(a).startswith("skip:") if a else bool(u.get("even") or (p or {}).get("sched"))
    us = [u for u in P.units(doc) if (u["id"] in uids if uids else str(u.get("opens") or "") < today and mine(u))]
    try:
        cids = set()
        for u in us:
            cids |= idx.match(u, _swap(st), doc)
        left = idx.unseen(cids) - _aside(idx, st, doc)  # (not what I suspended myself)
        if not uids:
            left = {c for c in left if idx.cards[c][0] != -1}  # behind: opened, so waiting in my Anki now
    except Exception:
        oops()
        return
    _browse(left, empty="Nothing left to see.")


def browse_topic(pid, uids, i):
    """3.8.0: Anki's browser on one topic of a date, or of today's dates (i,
    its place in P.topic_items of those dates): its tag as the search when
    that finds just its cards here, else its cards by id. A search run
    here; nothing is sent."""
    p = next((x for x in followed() if x["id"] == pid), None)
    st = _state_cfg().get(pid)
    if p is None or not st or not mw.col or not _deck_ok(mw.col, st.get("deck_id")):
        return
    pm = mine(p)
    by_id = {u["id"]: u for u in P.units(named(pid, pm["doc"]))}  # 3.8.1: the picks named as the board drew them
    items = P.topic_items([by_id[x] for x in uids if x in by_id])
    if not 0 <= i < len(items):
        return
    src = items[i][2]
    try:
        cids = P.topic_cards(P.DeckIndex(mw.col, st["deck_id"]), src, _swap(st), pm["doc"])
    except Exception:
        oops()
        return
    _browse(cids, _tag_search(mw.col, st["deck_id"], src, _swap(st), cids) if cids else None)


def study_topic(pid, uids, i):
    """3.9.5 (Sam: "if one clicks on a tagged section on a plan (like a video
    tags) then it moves them into a filtered deck?"): a topic of a date on
    Today, as a deck named for it: its cards I haven't seen and the
    ones due today (P.new_and_due; never reviews ahead of their date), in
    the deck's order. A card another Due Crew deck holds comes out of it
    first (Anki keeps a card in one filtered deck), and that deck gets back
    the rest of what it held after. Nothing new or due: Browse, as before. A
    search run here; nothing is sent."""
    p = next((x for x in followed() if x["id"] == pid), None)
    st = _state_cfg().get(pid)
    if p is None or not st or not mw.col or not _deck_ok(mw.col, st.get("deck_id")):
        return
    pm = mine(p)
    by_id = {u["id"]: u for u in P.units(named(pid, pm["doc"]))}
    items = P.topic_items([by_id[x] for x in uids if x in by_id])
    if not 0 <= i < len(items):
        return
    group, title, src = items[i]
    try:
        idx = P.DeckIndex(mw.col, st["deck_id"])
        cids = P.new_and_due(idx, P.topic_cards(idx, src, _swap(st), pm["doc"]))
    except Exception:
        oops()
        return
    if not cids:
        browse_topic(pid, uids, i)
        return
    name = _deck_name(title)
    back = _free(mw.col, cids, name)
    ok = _filtered(mw.col, name, cids, order=NEW_ORDER)
    for did, keep in back:
        try:
            _refill(mw.col, did, keep)
        except Exception:
            oops()
    _after_change()
    did = mw.col.decks.id_for_name(name) if ok else None
    if did:
        mw.col.decks.select(did)
        mw.moveToState("overview")


def _free(col, cids, name):
    """The Due Crew decks (but `name`'s own) holding any of these cards,
    emptied so the cards can move: [(its id, the cards it held but these)],
    to fill again after with just those (_refill). Built again from its own
    search, it would take back the cards answered since, as reviews ahead."""
    own = col.decks.id_for_name(name)
    ids = ",".join(str(int(c)) for c in cids) or "0"
    moving = {int(c) for c in cids}
    out = []
    for did in col.db.list(f"SELECT DISTINCT did FROM cards WHERE odid != 0 AND id IN ({ids})"):
        did = int(did)
        if did != (int(own) if own else 0) and str(col.decks.name(did) or "").startswith(P.PARENT + "::"):
            held = [int(c) for c in col.db.list("SELECT id FROM cards WHERE did = ?", did)]
            col.sched.empty_filtered_deck(did)
            out.append((did, [c for c in held if c not in moving]))
    return out


def _refill(col, did, cids):
    """A Due Crew deck _free emptied, with these cards again (its order and
    rescheduling as they were); one with none left, or whose cards Anki
    won't take back (suspended since, or in another deck), stays empty, for
    the morning's tidy."""
    if not cids:
        return
    deck = col.sched.get_or_create_filtered_deck(deck_id=did)
    term = deck.config.search_terms[0]
    term.search = "cid:" + ",".join(str(int(c)) for c in cids)
    term.limit = len(cids)
    try:
        col.sched.add_or_update_filtered_deck(deck)
    except Exception as e:
        # 3.9.12 (Sam's report, a day's Study): the cards it would get back are suspended now, or another
        # add-on's deck took them, and Anki refuses a filtered deck that finds none ("No cards matched the
        # provided search"). That isn't an error of ours: the deck stays empty, for the morning's tidy.
        # Anything else is still said.
        if type(e).__name__ != "FilteredDeckError":
            raise


def _tag_search(col, deck_id, src, swap, cids):
    """A topic's tags as Anki's own search, kept to the plan's deck, when it
    finds exactly the cards the plan means (the search bar then reads as
    the tag); None otherwise."""
    if set(src) != {"tags"}:
        return None
    try:
        from anki.collection import SearchNode
        tags = col.group_searches(*[SearchNode(tag=P.swapped(t, swap)) for t in src["tags"]], joiner="OR")
        q = col.build_search_string(SearchNode(deck=col.decks.name(int(deck_id))), tags)
        return q if {int(c) for c in col.find_cards(q)} == set(cids) else None
    except Exception:
        return None


def open_date(pid, uid):
    """G1: one date, now. 3.8.1: at my own pace, one I haven't opened opens
    as Up next's Open does (whole, first in line, counted as opened today,
    with its Undo); one I opened opens what an author added since."""
    p = next((x for x in followed() if x["id"] == pid), None)
    c = _pcfg()
    state = _state_cfg(c)
    st = state.get(pid)
    if p is None or not st or not mw.col:
        return
    if P.own_pace(p):
        u = next((x for x in P.units(p["doc"]) if x["id"] == uid), None)
        prog = (_state.get("plan_progress") or {}).get(pid) or {}
        if u is not None and not P.opened_here(st.get("applied"), u, prog):
            open_next(pid, uid=uid)
            return
    try:
        res = open_one(mw.col, p, st, uid, _today())
    except Exception:
        oops()
        return
    c["plans"] = state
    _psave(c)
    lesson_sync([p], fold=res["label"] if res["n"] else None)  # B: its deck, in the open's undo step
    if res["n"]:
        _after_change()
        tooltip(opened_line(res), period=5000)
    else:
        tooltip(f"Nothing new to open in {html.escape(res['names'][0] if res['names'] else 'that set')}.")
    refresh_progress()
    app.swap(cfg())


def open_put_off(pid):
    """G2: what Not today put off, now after all."""
    st = _state_cfg().get(pid) or {}
    for uid in list((st.get("later") or {}).keys()):
        open_date(pid, uid)


# Names of the parts after this one. The package sets them as each of those parts loads
# (an import here would load a later part before the ones between).
_LATER = ("back", "open_next")
back = open_next = None
