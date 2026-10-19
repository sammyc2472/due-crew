"""3.9.2, Leeches (Sam's picks, S1-A, S2-A): the cards Anki stopped showing
me (a leech, suspended) and the ones one miss from it, in a deck, as a view
in Insights' place. One button a card, sorted by danger: a crewmate's tip
when someone has it down (else Ask them), else Bring back; Learn it fresh,
Edit and Leave it out sit behind its ⋯. Bring all back and Browse at the top.

Bring back is Anki's unsuspend with the leech tag off: the card keeps its
schedule and is due again (before an exam, that's what saves it). Learn it
fresh is Anki's Reset: a new card again, in its place among them. Either
is one undo step (Edit › Undo). Leave it out keeps it suspended and out of
the count, in this profile's plans.json (`leech_out`). And the leeches
Anki tagged and kept showing me (Tag Only, its default since 23.10: none of
them suspended), still in my reviews.

Mine alone: worked out here, never sent. A card's front shows here only,
from my own copy (escaped by the board). Who has it down and their tips
come back with each sync already (cards.py's stuck list), no new request.
Main thread."""

import html
import re
import traceback

from aqt import mw
from aqt.utils import tooltip

from . import app
from .app import _state, cfg

OUT_MAX = 5000   # cards left out, at most
SLOW_SECS = 30   # a card's answers this slow on average say so
FRONT_MAX = 90
FRONTS = 12      # the cards a group lists (board.LEECH_SHOW), drawn from their own question


def _mine(key):
    """This profile's {deck id: ...} for key (app._reset_runtime empties it)."""
    if not isinstance(_state.get(key), dict):
        _state[key] = {}
    return _state[key]


def _pf():
    from . import plan_flow
    return plan_flow


# ---- pure ----

def next_is_leech(lapses, fails, every=None):
    """Whether one more miss makes this card a leech (again): Anki marks one
    at `fails` lapses, then every half of it after, rounded up (at 5: 5, 8,
    11; 3.9.2's audit, on Anki's engine)."""
    fails = max(1, int(fails))
    every = max(1, -(-fails // 2)) if every is None else max(1, int(every))
    n = int(lapses) + 1
    return n >= fails and (n - fails) % every == 0


_CLOZE = re.compile(r"\{\{c\d+::(.*?)(?:::(.*?))?\}\}", re.S)


def front(sfld):
    """A card's sort field as one plain line: tags and sounds out, a cloze's
    answer hidden ([…], or its hint), at most FRONT_MAX."""
    t = _CLOZE.sub(lambda m: f"[{m.group(2)}]" if m.group(2) else "[…]", str(sfld or ""))
    t = re.sub(r"\[sound:[^\]]*\]|\[\[type:[^\]]*\]\]", " ", t)
    t = re.sub(r"<[^>]*>", " ", t)
    t = " ".join(html.unescape(t).split())
    return t if len(t) <= FRONT_MAX else t[:FRONT_MAX - 1].rstrip() + "…"


def topic(tags):
    """The last part of a card's longest tag (not Anki's own), readable."""
    best = ""
    for t in str(tags or "").split():
        if t.lower() in ("leech", "marked") or t.count("::") < best.count("::"):
            continue
        if t.count("::") > best.count("::") or not best:
            best = t
    part = best.split("::")[-1].lstrip("#^$!").replace("_", " ").strip()
    return part[:40]


def order(gone, near):
    """Danger first. Gone (suspended): on my exam first, then the most
    missed, then the latest; near: the one due soonest, then the most missed."""
    gone = sorted(gone, key=lambda c: (not c.get("exam"), -c["lapses"], -c.get("at", 0)))
    near = sorted(near, key=lambda c: (c.get("due", 0), -c["lapses"]))
    return gone, near


# ---- the view ----

def _out():
    pc = _pf()._pcfg()
    return set(int(x) for x in pc.get("leech_out") or [] if str(x).isdigit())


def _limits(col, dids, cache):
    for d in dids:
        if d not in cache:
            try:
                lapse = col.decks.config_dict_for_deck_id(int(d))["lapse"]
                cache[d] = (int(lapse.get("leechFails") or 8), int(lapse.get("leechAction") or 0))
            except Exception:
                cache[d] = (8, 0)
    return cache


def counts(col, deck):
    """(gone, near, kept) for Insights' line: suspended leeches, cards one
    miss from Anki suspending them, and leeches Anki tagged and kept in my
    reviews; none I left out. A leech lapsed: Anki tags the note, so a
    sibling a big shared deck ships suspended, never answered, carries the
    tag without being one (Sam's deck, 3.9.2)."""
    out = _out()
    gone = [c for c in col.db.list(
        f"SELECT c.id FROM cards c JOIN notes n ON n.id = c.nid WHERE c.id IN ({deck}) "
        f"AND c.queue = -1 AND c.lapses > 0 AND (' ' || lower(n.tags) || ' ') LIKE '% leech %'") if c not in out]
    return len(gone), len(_near(col, deck, out)), len(_kept(col, deck, out))


def _near(col, deck, out=()):
    rows = col.db.all(f"SELECT id, lapses, CASE WHEN odid THEN odid ELSE did END FROM cards WHERE id IN ({deck}) "
                      f"AND queue = 2 AND type = 2 AND lapses >= 1")
    lim = _limits(col, {int(d) for _c, _l, d in rows}, {})
    return [int(c) for c, lap, d in rows if int(c) not in out and lim[int(d)][1] == 0 and next_is_leech(lap, lim[int(d)][0])]


def _kept(col, deck, out=()):
    """3.9.2 (Sam's pick): the leeches Anki tagged and kept showing me, in a
    deck whose leech action is Tag Only (Anki's default since 23.10), at
    its leech count or past it (so a tag a shared deck shipped isn't one)."""
    rows = col.db.all(f"SELECT c.id, c.lapses, CASE WHEN c.odid THEN c.odid ELSE c.did END FROM cards c "
                      f"JOIN notes n ON n.id = c.nid WHERE c.id IN ({deck}) AND c.queue != -1 AND c.lapses > 0 "
                      f"AND (' ' || lower(n.tags) || ' ') LIKE '% leech %'")
    lim = _limits(col, {int(d) for _c, _l, d in rows}, {})
    return [int(c) for c, lap, d in rows if int(c) not in out and lim[int(d)][1] == 1 and int(lap) >= lim[int(d)][0]]


def view(col, did, deck, since=None):
    """{gone, near, kept, n_gone, n_near, n_kept}: each card {cid, front,
    topic, lapses, at (its last answer, ms), due (days from today, near and
    kept), secs, exam, tip [{name, text}], knows [names], susp, kept}.
    since: an exam's scope (a started-since day, ms), for "on your exam"."""
    out = _out()
    sday = int(getattr(col.sched, "today", 0) or 0)
    gone_ids = [int(c) for c in col.db.list(
        f"SELECT c.id FROM cards c JOIN notes n ON n.id = c.nid WHERE c.id IN ({deck}) "
        f"AND c.queue = -1 AND c.lapses > 0 AND (' ' || lower(n.tags) || ' ') LIKE '% leech %'") if int(c) not in out]
    near_ids = _near(col, deck, out)
    kept_ids = set(_kept(col, deck, out))
    ids = gone_ids + near_ids + sorted(kept_ids)
    if not ids:
        return _empty()
    q = ",".join(str(c) for c in ids)
    stats = {int(c): (int(t or 0), int(m or 0), int(n or 0), int(f or 0)) for c, t, m, n, f in col.db.all(
        f"SELECT cid, max(id), total(time), count(), min(id) FROM revlog WHERE ease > 0 AND cid IN ({q}) GROUP BY cid")}
    from .cards import names_by_uid, tip_list
    from .together import local_tips
    names = names_by_uid()
    session = app.client().session.get("cards") or {}
    gone, near, kept = [], [], []
    for cid, lapses, queue, due, odid, sfld, tags, guid in col.db.all(
            f"SELECT c.id, c.lapses, c.queue, CASE WHEN c.odid THEN c.odue ELSE c.due END, c.odid, n.sfld, n.tags, n.guid "
            f"FROM cards c JOIN notes n ON n.id = c.nid WHERE c.id IN ({q})"):
        last, ms, n, first = stats.get(int(cid), (0, 0, 0, 0))
        info = session.get(str(guid)) or {}
        tips = [{"name": t["name"].split(" ")[0], "text": t["text"]} for t in tip_list(info, local_tips(str(guid)), names)
                if str(t.get("text") or "").strip()]
        knows = [names[u][0].split(" ")[0] for u in info.get("knows") or [] if u in names]
        c = {"cid": int(cid), "front": front(sfld), "topic": topic(tags), "lapses": int(lapses), "at": last,
             "secs": int(round(ms / 1000.0 / n)) if n else 0, "tip": tips[:3], "knows": knows[:3],
             "exam": bool(since and first >= since), "susp": int(queue) == -1, "kept": int(cid) in kept_ids}
        if c["susp"]:
            gone.append(c)
            continue
        # a buried card's back tomorrow; a relearning one (its due a time) is due today
        c["due"] = 1 if int(queue) in (-2, -3) else max(0, int(due) - sday) if int(queue) in (2, 3) else 0
        (kept if c["kept"] else near).append(c)
    gone, near = order(gone, near)
    kept = order([], kept)[1]
    for c in gone[:FRONTS] + near[:FRONTS] + kept[:FRONTS]:
        c["front"] = question(col, c["cid"], c["front"])
    return {"gone": gone, "near": near, "kept": kept, "n_gone": len(gone), "n_near": len(near), "n_kept": len(kept)}


def _empty():
    return {"gone": [], "near": [], "kept": [], "n_gone": 0, "n_near": 0, "n_kept": 0}


def question(col, cid, fallback=""):
    """3.9.2's audit: a card's question as Anki shows it, as one plain line
    (front()'s rules): a reversed card's own front, a cloze's asked part
    hidden. fallback (the sort field's) when the card can't be drawn."""
    try:
        q = col.get_card(int(cid)).render_output(reload=True, browser=True).question_text
    except Exception:
        return fallback
    q = re.sub(r"<(script|style)\b.*?</\1\s*>", " ", str(q or ""), flags=re.S | re.I)
    return front(q) or fallback


# ---- the commands ----

def _undo_step(col, label):
    try:
        return col.add_custom_undo_entry(label)
    except Exception:
        return None


def _merge(col, pos):
    if pos is not None:
        try:
            col.merge_undo_entries(pos)
        except Exception:
            pass


def _untag(col, cids):
    """The notes whose leech tag comes off with these cards: not one with
    another card still a leech, suspended or kept in my reviews (3.9.2's
    audit: a reversed note's other card stayed suspended and fell out of
    every count)."""
    q = ",".join(str(int(c)) for c in cids)
    nids = {int(n) for n in col.db.list(f"SELECT nid FROM cards WHERE id IN ({q})")}
    if not nids:
        return []
    rows = col.db.all(f"SELECT nid, queue, lapses, CASE WHEN odid THEN odid ELSE did END FROM cards "
                      f"WHERE nid IN ({','.join(map(str, nids))}) AND id NOT IN ({q}) AND lapses > 0")
    lim = _limits(col, {int(d) for _n, _q, _l, d in rows}, {})
    # a leech Anki kept showing (Tag Only) keeps the tag too
    keep = {int(n) for n, qu, lap, d in rows if int(qu) == -1 or (lim[int(d)][1] == 1 and int(lap) >= lim[int(d)][0])}
    return sorted(nids - keep)


def bring_back(did, cids):
    """Unsuspended, the leech tag off, schedule kept: due again. One undo."""
    col = mw.col
    if not col or not cids:
        return
    cids = [int(c) for c in cids]
    cids = [int(c) for c in col.db.list(f"SELECT id FROM cards WHERE id IN ({','.join(map(str, cids))})")]
    if not cids:
        _done(did, None)  # gone since the view was drawn
        return
    nids = _untag(col, cids)
    pos = _undo_step(col, "Due Crew: bring back")
    try:
        if nids:
            col.tags.bulk_remove(nids, "leech")
        col.sched.unsuspend_cards(cids)
    except Exception:
        traceback.print_exc()
        tooltip("Couldn't bring them back. Browse › Toggle Suspend.")
        return
    _merge(col, pos)
    _done(did, f"{len(cids):,} back in your reviews." if len(cids) > 1 else "Back in your reviews.")


def fresh(did, cid):
    """Learn it fresh: Anki's Reset, a new card again in its place among
    them (lapses and reps from zero), unsuspended, the leech tag off. One undo."""
    col = mw.col
    if not col:
        return
    nid = col.db.scalar("SELECT nid FROM cards WHERE id = ?", int(cid))
    if nid is None:
        _done(did, None)
        return
    nids = _untag(col, [int(cid)])
    pos = _undo_step(col, "Due Crew: learn it fresh")
    try:
        if nids:
            col.tags.bulk_remove(nids, "leech")
        col.sched.unsuspend_cards([int(cid)])
        col.sched.schedule_cards_as_new([int(cid)], restore_position=True, reset_counts=True)
    except Exception:
        traceback.print_exc()
        tooltip("Couldn't reset it. Browse › Cards › Reset.")
        return
    _merge(col, pos)
    _done(did, "A new card again.")


def leave_out(did, cid):
    pc = _pf()._pcfg()
    have = [int(x) for x in pc.get("leech_out") or [] if str(x).isdigit()]
    if int(cid) not in have:
        have = (have + [int(cid)])[-OUT_MAX:]
    pc["leech_out"] = have
    _pf()._psave(pc)
    _done(did, "Left out. Put it back from the foot of this list.")


def put_back_out(did, deck):
    """Leave it out's way back: this deck's cards left out, back in the list."""
    col = mw.col
    pc = _pf()._pcfg()
    have = [int(x) for x in pc.get("leech_out") or [] if str(x).isdigit()]
    here = set(int(c) for c in col.db.list(f"SELECT id FROM cards WHERE id IN ({deck})")) if col else set()
    pc["leech_out"] = [c for c in have if c not in here]
    _pf()._psave(pc)
    _done(did, None)


def n_out(col, deck):
    have = _out()
    if not have:
        return 0
    return len(set(int(c) for c in col.db.list(f"SELECT id FROM cards WHERE id IN ({deck})")) & have)


def _done(did, said):
    _pf()._after_change()
    (_state.get("insights") or {}).pop(int(did), None)
    _mine("leech_view")[int(did)] = None  # worked out again
    if said:
        tooltip(said)
    app.swap(cfg())


def _card_of(did, cid):
    v = (_state.get("leech_view") or {}).get(int(did)) or {}
    return next((c for c in _listed(v) if c["cid"] == int(cid)), None)


def _listed(v):
    return (v.get("gone") or []) + (v.get("near") or []) + (v.get("kept") or [])


def show_tip(did, cid):
    """A crewmate's tip on it, in a sheet: Bring back from there when it's
    suspended."""
    c = _card_of(did, cid)
    if not c or not c.get("tip"):
        return
    from . import sheets
    words = "\n\n".join(f"{t['name']}: {t['text']}" for t in c["tip"])
    head = f"{c['tip'][0]['name']}'s tip" if len(c["tip"]) == 1 else "Tips from your crew"
    if c["susp"]:
        sheets.confirm(head, words, "Bring it back", lambda: bring_back(did, [c["cid"]]))
    else:
        sheets.confirm(head, words, "OK", lambda: None)


def ask(did, cid):
    """Ask the ones who have it down (the crew with the card): one line,
    optional, flagged as a card ask from the reviewer is."""
    col = mw.col
    c = _card_of(did, cid)
    if not col or not c:
        return
    from . import sheets
    from .cards import clean_note, flag
    who = c["knows"]
    lead = (", ".join(who[:-1]) + " and " + who[-1]) if len(who) > 1 else (who[0] if who else "")
    try:
        card = col.get_card(int(cid))
    except Exception:
        _done(did, None)
        return
    sheets.ask_text("Ask your crew about this card",
                    f"Goes to everyone in your crew who has it.{' ' + lead + (' has' if len(who) == 1 else ' have') + ' it down.' if who else ''}",
                    lambda line: flag(card, clean_note(line) or ""), yes="Ask")


def browse(did):
    v = (_state.get("leech_view") or {}).get(int(did)) or {}
    _pf()._browse([c["cid"] for c in _listed(v)], empty="No leeches here.")


def open_view(did, on=True):
    _mine("leech_open")[int(did)] = bool(on)
    _mine("leech_view")[int(did)] = None
    app.swap(cfg())


def is_open(did):
    return bool((_state.get("leech_open") or {}).get(int(did)))


def current(col, did, deck, since=None):
    """The open view, worked out again when the collection changed since
    (a review, Browse, an undo, a card deleted: 3.9.2's audit) or my exam's
    scope did; a command's own change too."""
    have = (_state.get("leech_view") or {}).get(int(did))
    try:
        mod = int(col.mod)
    except Exception:
        mod = None
    if have is None or have.get("mod") != mod or have.get("since") != since:
        try:
            have = view(col, did, deck, since)
            have["out"] = n_out(col, deck)
        except Exception:
            traceback.print_exc()
            have = _empty()
        have.update(mod=mod, since=since)
        _mine("leech_view")[int(did)] = have
    return have


def on_message(did, act, arg):
    """insleech:<deck>:<act>:<card id or all>. True when handled. A card
    acted on must be one the view lists (worked out again after a change)."""
    v = {}
    if mw.col and act not in ("open", "shut") and mw.col.decks.get(int(did), default=False):
        from .team_flow import _deck_sql
        have = (_state.get("leech_view") or {}).get(int(did)) or {}
        v = current(mw.col, did, _deck_sql(mw.col, int(did)), have.get("since"))
    if act == "open":
        open_view(did)
    elif act == "shut":
        open_view(did, False)
    elif act == "browse":
        browse(did)
    elif act == "unout" and mw.col:
        from .team_flow import _deck_sql
        put_back_out(did, _deck_sql(mw.col, int(did)))
    elif act == "back" and arg == "all":
        bring_back(did, [c["cid"] for c in v.get("gone") or []])
    elif act in ("back", "fresh", "edit", "out", "tip", "ask") and arg.isdigit() and _card_of(did, arg):
        cid = int(arg)
        if act == "back":
            bring_back(did, [cid])
        elif act == "fresh":
            fresh(did, cid)
        elif act == "edit":
            _pf()._browse([cid])
        elif act == "out":
            leave_out(did, cid)
        elif act == "tip":
            show_tip(did, cid)
        else:
            ask(did, cid)
    else:
        return False
    return True

