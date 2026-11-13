"""Plans, the glue on Anki: the morning's open, the sync's progress, a date's and a quiz's decks."""

import copy
import datetime
import hashlib
import html
import json
import re

from aqt import mw
from aqt.utils import tooltip

from .. import app
from .. import plans as P
from .. import schedule as S
from ..app import _bg
from ..app import _state
from ..app import cfg
from ..app import client
from ..errs import oops

from .cards import _aside, _opened_cids, ask_later, first_here, new_state, run
from .state import _deck_ok, _pcfg, _plan_doc, _psave, _swap, _today, followed, mine


# ---- the glue (aqt) ----

def _state_cfg(c=None):
    c = _pcfg() if c is None else c
    st = c.get("plans")
    return st if isinstance(st, dict) else {}


def _after_change():
    """What a CollectionOp does after an op: the Edit menu learns the new
    undo step, and the screens that show cards redraw."""
    try:
        mw.update_undo_actions()
    except Exception:
        pass
    try:
        from anki.collection import OpChanges
        from aqt import gui_hooks
        gui_hooks.operation_did_execute(OpChanges(card=True, browser_table=True, study_queues=True), None)
    except Exception:
        pass


def opened_line(res):
    """The toast: "Due Crew opened Renal physiology: 204 cards", escaped."""
    if not res or not res["n"]:
        return None
    what = res["names"][0] if len(res["names"]) == 1 else f"{len(res['names'])} sets"
    return f"Due Crew opened {html.escape(what)}: {res['n']:,} card{'s' if res['n'] != 1 else ''}"


def _open_now(plan_list, mode=None, everything=False, toast=True):
    """Main thread: run, remember, say so (or leave the line to the
    caller's toast), redraw."""
    if not mw.col:
        return None
    c = _pcfg()
    state = _state_cfg(c)
    today = _today()
    try:
        res = run(mw.col, plan_list, state, today, mode=mode, everything=everything)
    except Exception:
        oops()
        return None
    c["plans"] = state
    if res["n"]:
        c["plans_opened"] = {"day": today, "label": res["label"], "per": res["per"], "units": res.get("units") or {},
                             "spread": res.get("spread") or {}, "was": res.get("was") or {},
                             "dates": [d for d in res.get("dates") or [] if d[3]][:OPENED_DATES]}  # 3.8.1
    _psave(c)
    # Today's lesson, B: then each open lesson its own deck, in the open's undo step
    lessons = lesson_sync(plan_list, fold=res["label"] if res["n"] else None)
    if res["n"] and any(set(uids) & set(lessons["decks"].get(pid) or ())
                        for pid, uids in (res.get("units") or {}).items()):
        c["plans_opened"]["decks"] = True  # the morning's line: "in your decks"
        _psave(c)
    if res["n"]:
        _after_change()
        if toast:
            tooltip(opened_line(res), period=5000)
    refresh_progress()
    return res


def _tags_changed():
    """After plan tags change on notes: Browse's sidebar and table, the Edit
    menu's Undo."""
    try:
        mw.update_undo_actions()
    except Exception:
        pass
    try:
        from anki.collection import OpChanges
        from aqt import gui_hooks
        gui_hooks.operation_did_execute(OpChanges(note_text=True, tag=True, browser_table=True), None)
    except Exception:
        pass


def _deck_index(cache, did):
    """3.8.1 (the audit, #9): one read of a deck for every plan on it in one
    pass. The caller drops it once a plan's tags moved notes (a tag made from
    a tag reads them)."""
    if did not in cache:
        cache[did] = P.DeckIndex(mw.col, did)
    return cache[did]


def apply_tags(plan_list, toast=True):
    """3.8.0, main thread: the plans' own tags on this copy's notes, as soon as
    a plan's update is here. Its callers make that after the day's AnkiWeb
    sync and on the Decks screen (a tag on a stale note would win over an
    edit made on the phone), and before what opens (a date can use a tag).
    One undo step a plan; only DueCrew::<the plan> tags are ever touched.
    Returns the line to say, or None."""
    if not mw.col:
        return None
    c = _pcfg()
    state = _state_cfg(c)
    today = _today()
    said, changed, moved = [], False, False
    idxs = {}
    for p in plan_list:
        st = state.get(p["id"])
        doc = _plan_doc(p)
        if not st or not _deck_ok(mw.col, st.get("deck_id")) or not (P.plan_tags(doc) or st.get("tags")):
            continue
        # the deck is read (a second on a big one) when the plan's tags changed, and once
        # an Anki day for a tag made from a tag or a search (new notes that match)
        sig = P.tags_sig(doc)
        if st.get("tags_sig") == sig and st.get("tags_day") == today:
            continue
        try:
            applied, res = P.sync_tags(mw.col, _deck_index(idxs, st["deck_id"]), doc, st.get("tags"),
                                       f"Due Crew: {p.get('name') or 'plan'}'s tags", _swap(st))
        except Exception:
            oops()
            idxs.pop(st["deck_id"], None)
            continue
        if res["added"] or res["removed"]:
            idxs.pop(st["deck_id"], None)  # notes' tags moved: the next plan reads them fresh
        if res["added"] or res["removed"] or applied != (st.get("tags") or {}):
            moved = True
        if applied:
            st["tags"] = applied
        else:
            st.pop("tags", None)
        st["tags_sig"], st["tags_day"] = sig, today
        changed = True
        if res["new"]:
            st["tag_news"] = {"day": today, "names": res["new"][:6], "more": max(0, len(res["new"]) - 6),
                              "missing": int(sum(res["missing"].values()))}
            said.append(f"{html.escape(p.get('name') or 'A plan')}'s tags are in your Anki: "
                        + ", ".join(html.escape(x) for x in res["new"][:3]) + (" and more" if len(res["new"]) > 3 else "") + ".")
    if changed:
        c["plans"] = state
        _psave(c)
    if moved:
        _tags_changed()
    line = " ".join(said) or None
    if line and toast:
        tooltip(line, period=5000)
    return line


def apply_authored_tags(toast=True):
    """3.8.0, main thread: the plans I write or co-author and don't follow carry
    their own tags in my Anki too, so a tag made on duecrew.com counts in my
    builder and its dates' note ids reach followers on an older add-on. The
    same moment and rules as a follower's (after the day's AnkiWeb sync, on
    Decks; one undo step a plan; DueCrew::<the plan> only), on the deck named
    like the plan's. State: plans.json's `authored_tags` {plan id: {deck_id,
    tags, tags_sig, tags_day}}. A plan I no longer write takes its tags along;
    one I now follow hands them to my follow. Returns the line to say, or None."""
    auth = client().session.get("plans_authored")
    if auth is None or not mw.col:  # not heard yet: nothing is gone
        return None
    c = _pcfg()
    mine = dict(c.get("authored_tags") or {})
    followed = _state_cfg(c)
    today = _today()
    names = {n.lower(): d for d, n in P.deck_choices(mw.col)}
    said, changed, moved = [], False, False
    idxs = {}
    ids = {a["id"] for a in auth}
    for pid in [k for k in mine if k not in ids or k in followed]:
        st = mine.pop(pid)
        changed = True
        if pid in followed:
            if st.get("tags") and not followed[pid].get("tags"):
                followed[pid]["tags"] = st["tags"]  # my follow has them already: not new
        elif _drop_plan_tags(st, "a plan you wrote"):
            moved = True
    for a in auth:
        pid, doc = a["id"], a["doc"]
        st = mine.get(pid) or {}
        if pid in followed or not (P.plan_tags(doc) or st.get("tags")):
            continue
        did = names.get(str(doc.get("deck") or "").lower())
        sig = P.tags_sig(doc)
        if did is None or (st.get("tags_sig") == sig and st.get("tags_day") == today and st.get("deck_id") == did):
            continue
        try:
            applied, res = P.sync_tags(mw.col, _deck_index(idxs, did), doc, st.get("tags"),
                                       f"Due Crew: {a.get('name') or 'plan'}'s tags")
        except Exception:
            oops()
            idxs.pop(did, None)
            continue
        if res["added"] or res["removed"]:
            idxs.pop(did, None)
        if res["added"] or res["removed"] or applied != (st.get("tags") or {}):
            moved = True
        mine[pid] = {"deck_id": did, "tags_sig": sig, "tags_day": today, **({"tags": applied} if applied else {})}
        changed = True
        if res["new"]:
            said.append(f"{html.escape(a.get('name') or 'Your plan')}'s tags are in your Anki: "
                        + ", ".join(html.escape(x) for x in res["new"][:3]) + (" and more" if len(res["new"]) > 3 else "") + ".")
    if changed:
        c["authored_tags"], c["plans"] = mine, followed
        _psave(c)
    if moved:
        _tags_changed()
        send_ids()  # the dates' note ids and counts, now with the tags
    line = " ".join(said) or None
    if line and toast:
        tooltip(line, period=5000)
    return line


def _drop_plan_tags(st, name):
    """A plan I no longer follow takes its tags off my notes (one undo step)."""
    tags = (st or {}).get("tags") or {}
    path = next(iter(tags.values()), "")
    parts = str(path).split("::")
    if len(parts) < 3 or not mw.col:
        return 0
    try:
        n = P.drop_tags(mw.col, "::".join(parts[:2]), f"Due Crew: {name or 'plan'}'s tags off")
    except Exception:
        oops()
        return 0
    _tags_changed()
    return n


def maybe_morning(awaiting_sync, fresh=False, toast=True, update=False):
    """Main thread. Once per Anki day, for each followed, unpaused plan:
    open what's due. Waits for the day's AnkiWeb sync when this profile
    syncs (the phone's reviews, and the other computer's opened cards,
    come in with it). fresh: the plans just came with the day's refresh,
    so plans no longer followed are forgotten here, and what's due opens
    even when the morning already ran today (it may have run on
    yesterday's cached plans; what's applied doesn't open twice).
    toast=False returns the line for the caller's own toast (one tooltip
    replaces another)."""
    if not mw.col or not client().signed_in:
        return None
    try:
        c = _pcfg()
        state = _state_cfg(c)
        plan_list = followed()
        today = _today()
        # 3.8.0: never mid-review. What the morning unsuspends is an undo step,
        # and on the review screen it would land on top of the last answer
        # (Undo would suspend the cards again). Off the Decks screen, what
        # would unsuspend waits for it (`_state["plans_morning"]`), as midday does.
        here = getattr(mw, "state", "") == "deckBrowser"
        if fresh:
            ids = {p["id"] for p in plan_list}
            gone = [pid for pid in state if pid not in ids]
            waits = any(_shut_by_plan(state.get(pid)) or (state.get(pid) or {}).get("tags") for pid in gone)
            if not here and (waits or any((state.get(pid) or {}).get("lesson_decks") for pid in gone)):
                return _morning_waits(awaiting_sync, fresh)  # Today's lesson, B: its decks go on Decks too
            for pid in gone:
                was = state.pop(pid, None) or {}
                held = _shut_by_plan(was)
                if held and mw.col:
                    # taken down elsewhere (the author deleted it, or I stopped
                    # it on the site): what Hold back or Put back shut opens again, as Stop does
                    P.open_cards(mw.col, held, "Due Crew: a plan you followed ended")
                if was.get("tags"):
                    _drop_plan_tags(was, "a plan you followed")  # 3.8.0: and its tags come off
                if was.get("lesson_decks") and mw.col:
                    try:
                        if _lesson_drop(mw.col, was):  # Today's lesson, B: and its decks go
                            _after_change()
                    except Exception:
                        oops()
            changed = bool(gone)
            for p in plan_list:
                st = state.get(p["id"])
                if st and st.get("seen_version") != p.get("version") and st.get("snapshot") is not None \
                        and P.change_note(p.get("ownerName"), st["snapshot"], _plan_doc(p)) is None:
                    # a change with nothing to say (cards added, a name kept): noted quietly
                    st.update(seen_version=p.get("version"), snapshot=P.snapshot(_plan_doc(p)))
                    changed = True
            if changed:
                c["plans"] = state
                _psave(c)
            send_ids()  # 3.3, C5: the plans I write
            send_trees()  # 3.8.1: and their decks' tags, for the builder, when they changed
        if awaiting_sync or (c.get("plans_day") == today and not fresh):
            return None
        if c.get("plans_day") == today:
            # 3.7.3: plans that came again after today's morning (an author's
            # update, or Anki opened again): asked, not opened
            return midday(plan_list, toast=toast)
        if not here:
            return _morning_waits(awaiting_sync, fresh)
        _state["plans_morning"] = None
        _state["plan_updates"] = {}
        new_here = []
        for p in plan_list:
            if p["id"] not in state:
                st = new_state(mw.col, p)  # followed on another computer, or on the site
                if st:
                    state[p["id"]] = first_here(mw.col, st, p, today)
                    _take_next(c, p["id"], state[p["id"]])  # Today's lesson, if chosen before it ran here
                    new_here.append(p["id"])
        c["plans"] = state
        c["plans_day"] = today
        _psave(c)
        # 3.8.1: every other step the morning makes comes before what it opens, so
        # Anki's latest step is the open, and Not today can undo it
        if tidy_decks(mw.col):
            _after_change()
        tagged = " ".join(x for x in (apply_tags(plan_list, toast=False),  # 3.8.0: a date can use one of its plan's tags
                                      apply_authored_tags(toast=False)) if x) or None  # and the plans I write
        if hold_new([p for p in plan_list if not p.get("paused") and p["id"] not in new_here], _state_cfg(), today, morning=True):
            _after_change()  # 3.7.3: what an author added to later dates waits, for whoever chose Hold back
        apply_catch()  # G5
        try:
            from .. import ahead_flow
            if ahead_flow.apply_morning():  # 3.9.2: Stop new cards, after a catch-up's own limit
                _after_change()
        except Exception:
            oops()
        built = build_checks([p for p in plan_list if not p.get("paused")])  # 3.2
        # 3.8.1, Welcome back: a plan whose dates from 3+ days I studied nothing would open
        # keeps them shut till its question, asked below (Open them, Push my dates back, Not today)
        away = _put_away([p for p in plan_list if not p.get("paused") and p["id"] not in new_here], today)
        line = opened_line(_open_now([p for p in plan_list if not p.get("paused")], toast=toast))
        if tagged:
            line = f"{line} {tagged}" if line else tagged
            if toast and not _state.get("plans_opened_said"):
                tooltip(tagged, period=5000)
        backs = [p["id"] for p in plan_list if p.get("paused") and p.get("until") and str(p["until"]) < today]
        if backs:
            # G4: a pause whose last day has passed asks its question once, here
            from aqt.qt import QTimer
            for pid in backs:
                QTimer.singleShot(0, lambda pid=pid: back(pid))
        if built and toast:
            tooltip(f"Due Crew built {html.escape(built[0])}.", period=5000)
        if away:
            from aqt.qt import QTimer
            QTimer.singleShot(0, lambda: welcome_back(list(away)))
        if new_here:
            # a plan followed on the site asks Follow's question here, once
            from aqt.qt import QTimer
            QTimer.singleShot(0, lambda: offer_hold(new_here))
        return line
    except Exception:
        oops()
        return None


def _morning_waits(awaiting_sync, fresh):
    """3.8.0: the morning came off the Decks screen; it runs when Decks next
    draws (__init__._on_did_render), as this call would have."""
    was = _state.get("plans_morning") or {}
    _state["plans_morning"] = {"awaiting": bool(awaiting_sync) and was.get("awaiting", True),
                               "fresh": bool(fresh) or bool(was.get("fresh"))}
    return None


def midday(plan_list, toast=True):
    """3.7.3, main thread, an update later in the day. Only on the Decks screen
    (holding back is an undo step, and a change must never land mid-review):
    elsewhere it waits for the next time Decks draws. A plan new here opens
    as the morning would (following it was mine to do); a plan whose
    follower chose Hold back holds the new cards of its later dates too;
    what the update adds to today and earlier waits for my Open
    (`_state["plan_updates"]`: {plan id: {n, names, units}})."""
    if not mw.col:
        return None
    if getattr(mw, "state", "") != "deckBrowser":
        _state["plans_midday"] = True
        return None
    _state["plans_midday"] = False
    apply_tags(plan_list, toast=toast)  # 3.8.0: as soon as the update is here, before what it opens
    apply_authored_tags(toast=toast)
    c = _pcfg()
    state = _state_cfg(c)
    today = _today()
    live = [p for p in plan_list if not p.get("paused")]
    new_here = []
    for p in plan_list:
        if p["id"] not in state:
            st = new_state(mw.col, p)
            if st:
                state[p["id"]] = first_here(mw.col, st, p, today)
                _take_next(c, p["id"], state[p["id"]])
                new_here.append(p["id"])
    c["plans"] = state
    _psave(c)
    held = hold_new([p for p in live if p["id"] not in new_here], state, today)  # 3.8.1: before what opens
    line = None
    if new_here:
        line = opened_line(_open_now([p for p in live if p["id"] in new_here], toast=toast))
        from aqt.qt import QTimer
        QTimer.singleShot(0, lambda: offer_hold(new_here))
    try:
        dry = run(mw.col, [p for p in live if p["id"] not in new_here], copy.deepcopy(state), today, dry=True)
    except Exception:
        oops()
        dry = {"per": {}, "units": {}}
    _state["plan_updates"] = {pid: {"n": int(v[1]), "names": list(v[0]), "units": list(dry["units"].get(pid) or [])}
                              for pid, v in (dry.get("per") or {}).items() if v[1]}
    if held:
        _after_change()
    refresh_progress()
    app.swap(cfg())
    return line


def hold_new(plan_list, state, today, morning=False):
    """3.7.3: a follower who chose Hold back gets it for what an author adds to
    later dates too (that was their yes): those cards are suspended until
    their day, one undo step a plan. Never for anyone else. Returns how many.
    3.8.1: the yes is `hold_yes` (Put back's cards sit in `held` too, for Stop, but are never a yes);
    a card a date opened here is never held, nor one held or put back
    before and opened since by hand. morning: it runs before the morning's
    open, so what that opens (a date opening early, at my own pace the next
    date opening by itself) counts as open already."""
    n, changed = 0, False
    for p in plan_list:
        st = state.get(p["id"])
        if not st or not _deck_ok(mw.col, st.get("deck_id")):
            continue
        had = "hold_yes" in st
        yes = _hold_yes(p, st)
        changed = changed or (not had and "hold_yes" in st)
        if not yes:
            continue
        q = mine(p)
        own = P.own_pace(q)
        day = today if own or not morning else S.iso(S.d(today) + datetime.timedelta(days=int(p.get("early") or 0)))
        idx = P.DeckIndex(mw.col, st["deck_id"])
        kept = _opened_cids(idx, st, q["doc"])
        if own and morning and p.get("own") == "next":
            nxt = P.next_by_itself(q["doc"], st.get("applied"), st.get("own_opened"), P.progress(idx, q["doc"], _swap(st), _aside(idx, st, q["doc"])))
            if nxt and str((st.get("later") or {}).get(nxt["id"]) or "") <= today:
                kept |= idx.match(nxt, _swap(st), q["doc"])
        cids = P.holdable(idx, q["doc"], day, _swap(st), st.get("applied"), own=own, kept=kept)
        cids -= set(_shut_by_plan(st))
        if not cids:
            continue
        got = P.hold_cards(mw.col, cids, f"Due Crew: hold back {p.get('name') or 'plan'}")
        if got:
            st["held"] = sorted(set(st.get("held") or []) | {int(x) for x in cids})
            n += got
            changed = True
    if changed:
        c = _pcfg()
        c["plans"] = state
        _psave(c)
    return n


def _hold_yes(p, st):
    """3.8.1: whether I said yes to Hold back for this plan (at Follow, or
    asked on first sight or when I went to my own pace): `hold_yes`. Until
    3.8.1 any held card meant yes, and Put back kept its cards there too, so
    holding back turned on by itself. A state from then: a plan on its dates
    with held cards had said yes (Put back is only at my own pace); one at
    my own pace counts as no until asked again. Settled once, kept."""
    if "hold_yes" not in st:
        if not st.get("held"):
            return False
        st["hold_yes"] = not P.own_pace(p)
    return bool(st["hold_yes"])


def _shut_by_plan(st):
    """Every card this plan shut here when I asked (`held`: Hold back's and
    Put back's): Stop following, or the plan going, opens them again."""
    return sorted({int(x) for x in (st or {}).get("held") or []})


def update_open(pid):
    """3.7.3, Open on an update's line: what it adds opens now, in one undo step."""
    p = next((x for x in followed() if x["id"] == pid), None)
    (_state.get("plan_updates") or {}).pop(pid, None)
    if p and not p.get("paused"):
        _open_now([p])
    app.swap(cfg())


def update_later(pid):
    """3.7.3, Not today on an update's line: tomorrow's morning opens it."""
    upd = (_state.get("plan_updates") or {}).pop(pid, None) or {}
    c = _pcfg()
    state = _state_cfg(c)
    if pid in state and upd.get("units"):
        ask_later(state[pid], upd["units"], _today())
        c["plans"] = state
        _psave(c)
    app.swap(cfg())


def post_seen(pid):
    """3.7.3: the newest post on a plan is read here."""
    p = next((x for x in followed() if x["id"] == pid), None)
    c = _pcfg()
    seen = c.setdefault("posts_seen", {})
    top = max([int(x.get("id") or 0) for x in (p or {}).get("posts") or []] + [int(seen.get(pid) or 0)])
    seen[pid] = top
    _psave(c)
    app.swap(cfg())


def unread_posts(plan):
    """3.7.3: the plan's posts I haven't marked read, newest first; ones over
    a week old don't come up (a plan followed today shows its last week)."""
    seen = int(((_pcfg().get("posts_seen") or {}) if mw else {}).get(plan["id"]) or 0)
    import time as _time
    cut = int(_time.time()) - 7 * 86400
    return [x for x in plan.get("posts") or [] if int(x.get("id") or 0) > seen and int(x.get("at") or 0) > cut]


def offer_hold(pids, ask=None, words=None):
    """3.4 review, H1: a plan first seen on this computer (followed on the
    site, or elsewhere) asks what Follow asks: hold back its later dates'
    cards until their day (at my own pace, until I open them)? Only when
    there are some (a computer that held them already has them suspended,
    which AnkiWeb brought here). A yes is kept (`hold_yes`). 3.9.1: the
    question is a sheet (sheets.confirm), one plan at a time, the next
    asked once this one's answered. words(name, n, own): (title, text, yes)
    in place of _hold_words. ask(name, n): a test's answer, at once."""
    if not mw.col:
        return
    pids = list(pids)
    while pids:
        pid = pids.pop(0)
        got = _holdable(pid)
        if not got:
            continue
        p, cids, own = got
        name = p.get("name") or "The plan"
        if ask is not None:
            if ask(name, len(cids)):
                _hold(pid)
            continue
        from .. import sheets
        title, text, yes = (words or _hold_words)(name, len(cids), own)
        rest = list(pids)
        sheets.confirm(title, text, yes, lambda: (_hold(pid), offer_hold(rest, words=words)),
                       no=lambda: offer_hold(rest, words=words))
        return


def _holdable(pid):
    """(plan, the cards Hold back would keep, own pace), or None."""
    st = _state_cfg(_pcfg()).get(pid)
    p = next((x for x in followed() if x["id"] == pid), None)
    if not p or not st or not mw.col or not _deck_ok(mw.col, st.get("deck_id")):
        return None
    idx = P.DeckIndex(mw.col, st["deck_id"])
    own = P.own_pace(p)
    cids = P.holdable(idx, p["doc"], _today(), _swap(st), st.get("applied"), own=own, kept=_opened_cids(idx, st, p["doc"]))
    return (p, cids, own) if cids else None


def _hold(pid):
    """offer_hold's yes: what's holdable now, held, in one undo step."""
    got = _holdable(pid)
    if not got:
        return
    p, cids, _own = got
    c = _pcfg()
    state = _state_cfg(c)
    st = state[pid]
    st["hold_yes"] = True
    n = P.hold_cards(mw.col, cids, f"Due Crew: hold back {p.get('name') or 'plan'}")
    if n:
        st["held"] = sorted(set(st.get("held") or []) | {int(x) for x in cids})
    c["plans"] = state
    _psave(c)
    _after_change()
    refresh_progress()
    app.swap(cfg())


def _hold_words(name, n, own=False):
    """offer_hold's question (plain text: the plan's name is the author's)."""
    cards = f"{n:,} card{'s' if n != 1 else ''}"
    if own:
        text = (f"{name} is new on this computer. Hold back {cards} of its later sets until you open them?"
                "\n\nOne undo step; stopping the plan opens them again.")
    else:
        text = (f"{name} is new on this computer. Hold back {cards} of its later sets until their day?"
                "\n\nThey open on their day. One undo step; stopping the plan opens them again.")
    return "Hold back later cards", text, "Hold back"


def send_ids():
    """3.3, C5: main thread, on the day's first refresh. For each plan I
    write whose deck I have (by its name), the note ids behind each date's
    tags and subdecks go up, one request a plan, only when they changed:
    a follower whose copy of the deck renamed a tag still gets the date. 3.4, D1:
    with how many cards each of its searches finds here."""
    cl = client()
    auth = cl.session.get("plans_authored") or []
    if not auth or not mw.col:
        return
    sent = _pcfg().get("ids_sent") or {}
    names = {n.lower(): d for d, n in P.deck_choices(mw.col)}
    jobs = []
    try:
        for a in auth:
            did = names.get(str(a["doc"].get("deck") or "").lower())
            if did is None or not a["doc"].get("units"):
                continue
            idx = P.DeckIndex(mw.col, did)
            units = P.ids_snapshot(idx, a["doc"])
            counts = P.search_counts(idx, a["doc"])  # 3.4, D1: a pasted search's count
            for u in a["doc"]["units"]:  # 3.8.1: the deck tags a date's picked cards sit under here (#lbl, its `pl`)
                lbl = P.pick_labels(idx, idx.match(P.picks(u), None, a["doc"])) if P.picks(u) else []
                if lbl:
                    counts.setdefault(u["id"], {})["#lbl"] = lbl
            refs = P.id_refs(idx, mw.col, a["doc"])  # 3.6.5: pasted ids as cards anyone's copy can find
            # 3.8.1: with the picks the labels were read from: a site edit drops a date's `pl`, so new picks send them again
            picked = {u["id"]: P.picks(u) for u in a["doc"]["units"] if P.picks(u)}
            h = hashlib.sha1(json.dumps([units, counts, refs] + ([picked] if picked else []), sort_keys=True).encode()).hexdigest()[:16]
            if sent.get(a["id"]) != h:
                jobs.append((a["id"], units, counts, refs, h))
    except Exception:
        oops()
        return
    if not jobs:
        return

    def job():
        return [(pid, h) for pid, units, counts, refs, h in jobs if cl.put_ids(pid, units, counts, refs)]

    def done(ok):
        if ok:
            pc = _pcfg()
            pc.setdefault("ids_sent", {}).update(dict(ok))
            _psave(pc)

    _bg(job, done)


def send_trees():
    """3.8.1, main thread, at the same moment as send_ids: the tag and
    subdeck tree of each deck a plan I write runs on (the deck named like
    the plan's) goes up for the builder, so its tag list keeps up without
    Make a plan from a deck. Each deck is read once an Anki day; its tree
    goes (one request a deck, in the background) only when it differs from
    what this computer last sent (`trees_sent`). Nothing on a day nothing
    changed; a failed one is tried again at the next refresh."""
    cl = client()
    auth = cl.session.get("plans_authored") or []
    if not auth or not mw.col:
        return
    pc = _pcfg()
    today = _today()
    names = {n.lower(): d for d, n in P.deck_choices(mw.col)}
    want = {str(a["doc"].get("deck") or "").lower() for a in auth}
    sent = {k: v for k, v in (pc.get("trees_sent") or {}).items() if k in want and isinstance(v, dict)}
    jobs, seen, checked = [], set(), {}
    try:
        for a in auth:
            deck = str(a["doc"].get("deck") or "")
            key = deck.lower()
            did = names.get(key)
            if did is None or key in seen:
                continue
            seen.add(key)
            was = sent.get(key) or {}
            if was.get("day") == today:
                continue
            tags, decks = P.tree_rows(P.DeckIndex(mw.col, did))
            h = P.tree_hash(deck, tags, decks)
            if was.get("h") == h or not (tags or decks):
                checked[key] = dict(was, day=today)  # the same as sent, or nothing to send
            else:
                jobs.append((key, deck, tags, decks, h))
    except Exception:
        oops()
        return
    if checked or sent != (pc.get("trees_sent") or {}):
        pc["trees_sent"] = dict(sent, **checked)
        _psave(pc)
    if not jobs:
        return
    gen = app.generation

    def job():
        return [(key, h) for key, deck, tags, decks, h in jobs if cl.put_tree(deck, tags, decks)]

    def done(ok):
        if not ok or gen != app.generation:
            return  # nothing went, or another profile or account since: the next refresh asks again
        pc2 = _pcfg()
        pc2.setdefault("trees_sent", {}).update({key: {"h": h, "day": today} for key, h in ok})
        _psave(pc2)

    _bg(job, done)


CHECK_CARDS = 60
CHECK_DAYS = 3  # a checkpoint missed by more than this many mornings isn't built late


def checks_due(doc, st, sched, today):
    """Checkpoints and (3.3) review days that are today on my dates (or up
    to CHECK_DAYS ago) and not built here yet: [(key, name, [units], n)].
    3.9.5 (Sam's FSRS rule): a review day only before a quiz (an event
    within P.QUIZ_DAYS after it); otherwise it'd be reviews ahead of their
    date with no date to aim at, and FSRS has those."""
    day = S.d(today)
    shift = S.shift_days(doc, sched)
    done = st.get("checks") or {}
    us = P.units(doc)
    out = []
    due = lambda d: 0 <= (day - (S.d(d) + datetime.timedelta(days=shift))).days <= CHECK_DAYS
    for u in us:
        if u.get("check") and u["id"] not in done and due(u["check"]):
            out.append((u["id"], f"Checkpoint · {u.get('name') or 'unit'}", [u], CHECK_CARDS))
    by_id = {u["id"]: u for u in us}
    for r in doc.get("reviews") or []:
        key = f"r:{r['day']}:{r['from']}:{r['to']}"
        a, b = by_id.get(r["from"]), by_id.get(r["to"])
        if key in done or not a or not b or not due(r["day"]) or not quiz_after(doc, S.d(r["day"]) + datetime.timedelta(days=shift)):
            continue
        lo, hi = sorted([a["opens"], b["opens"]])
        span = [u for u in us if lo <= u["opens"] <= hi]
        name = f"Review · {a.get('name') or '?'}" + (f" – {b.get('name') or '?'}" if a is not b else "")
        out.append((key, name, span, REVIEW_CARDS))
    return out


REVIEW_CARDS = 200  # 3.3, C4: a review day's deck


def quiz_after(doc, day):
    """3.9.5: an event of the plan's within P.QUIZ_DAYS after `day` (a date;
    events never move)."""
    for e in doc.get("events") or []:
        try:
            gap = (datetime.date.fromisoformat(str((e or {}).get("day") or "")) - day).days
        except (TypeError, ValueError):
            continue
        if 0 <= gap <= P.QUIZ_DAYS:
            return True
    return False


STUDY_ORDER = 1  # Anki's filtered-deck order: random
NEW_ORDER = 6  # as they come in the deck: new cards by their place in it


def study_date(pid, uid):
    """3.3, C4: Study on a date (the plan's week, and a plan's date in Due):
    a Due Crew deck of the date's cards, Anki rescheduling them as it would
    (_filtered: one undo step of Anki's own), then Anki's Study screen on
    it. 3.9.5 (Sam's FSRS rule): its new cards and the ones due today
    (P.new_and_due), never reviews ahead of their date; a quiz's Study keeps
    those (study_quiz). A search run here; nothing is sent. Today's lesson,
    B: the lesson's own deck (built first if it needs it). A card another
    Due Crew deck holds (a lesson's, a topic's) comes out of it first, and
    that deck gets back the rest after (_free), as a topic's Study does."""
    got = _plan_idx(pid)
    if not got:
        return
    p, st, doc, idx = got
    u = next((x for x in P.units(doc) if x["id"] == uid), None)
    if not u:
        return
    if st.get("lesson_deck"):
        lesson_sync([p])
        did = _lesson_did(pid, uid)
        if did and _go_deck(did):
            return
        idx = P.DeckIndex(mw.col, st["deck_id"])
    cids = P.new_and_due(idx, idx.match(u, _swap(st), doc))
    if not cids:
        tooltip("Nothing new or due in it.")
        return
    name = _deck_name(u.get('name') or 'date')
    back = _free(mw.col, cids, name)
    ok = _filtered(mw.col, name, cids, order=NEW_ORDER)
    for bdid, keep in back:
        try:
            _refill(mw.col, bdid, keep)
        except Exception:
            oops()
    if ok or back:
        _after_change()
    if ok:
        did = mw.col.decks.id_for_name(name)
        if did:
            mw.col.decks.select(did)
            mw.moveToState("overview")


def study_day(pid, day):
    """3.9.6, a day's Study in You › Plans' week (Sam: "study all for the
    day and it pops out the filtered deck of just those new / review cards
    for the day ... not just for today for past days too ... when you've
    clicked on one of the days"): one Due Crew deck of what the day asks now
    (P.day_cards: its sets' new cards not seen yet and theirs due today;
    today, every set's due today too; never a review ahead of its date),
    "Due Crew::<plan> · Today" or "· Mon 2 Nov", emptied the morning after
    (`until`). A card another Due Crew deck holds (a set's own, Today's set
    B) comes out of it first and that deck gets back the rest (_free), as a
    date's Study does. Then Anki's Study screen on it. A search run here;
    nothing is sent."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(day or "")):
        return
    got = _plan_idx(pid)
    if not got:
        return
    p, st, doc, idx = got
    today = _today()
    if day > today:
        return
    when = "Today" if day == today else _day_words(day)
    cids, n_new, n_due = P.day_cards(idx, doc, day, today, st.get("applied"), _swap(st))
    if not cids:
        tooltip("Nothing new or due today in this plan." if day == today else f"Nothing new or due from {when}.")
        return
    name = _deck_name(f"{str(p.get('name') or 'Plan')} · {when}")
    back = _free(mw.col, cids, name)
    ok = _filtered(mw.col, name, cids, order=NEW_ORDER, until=today)
    for bdid, keep in back:
        try:
            _refill(mw.col, bdid, keep)
        except Exception:
            oops()
    if ok or back:
        _after_change()
    if ok:
        did = mw.col.decks.id_for_name(name)
        if did:
            mw.col.decks.select(did)
            mw.moveToState("overview")
            # what it holds, as Anki built it: a card another add-on's deck holds stays there
            inn = set(mw.col.db.list("SELECT id FROM cards WHERE did = ?", did))
            n_due = len(inn & set(idx.due_now))
            n_new = len(inn) - n_due
        bits = [f"{n_new:,} new"] if n_new else []
        bits += [f"{n_due:,} due"] if n_due else []
        if bits:
            tooltip(f"{'Today' + chr(8217) + 's' if day == today else when + ':'} {' and '.join(bits)}, in a filtered deck.")


def _day_words(day):
    """"Mon 2 Nov", a day of the week's in words."""
    d = datetime.date.fromisoformat(day)
    return f"{d:%a} {d.day} {d:%b}"


QUIZ_ORDER = 2  # Anki's filtered-deck order: smallest intervals first, the shakiest (and the unseen) first


def quiz_cards(pid, eid):
    """(cids, event) a quiz's Study takes: the open cards of the dates that
    prep for it (P.quiz: open by today, not one after it); ([], None)
    without the plan here or the event."""
    got = _plan_idx(pid)
    if not got:
        return [], None
    _p, st, doc, idx = got
    ev = next((e for e in doc.get("events") or [] if isinstance(e, dict) and e.get("id") == eid), None)
    if not ev:
        return [], None
    cids, today = set(), _today()
    for u in P.units(doc):  # the dates its line counts (P.quiz): prep dates open by today, not one after it
        if u.get("for") == eid and not P.reinforces(doc, u) and str(u.get("opens") or "9999") <= today:
            cids |= idx.match(u, _swap(st), doc)
    return P.study_cards(idx, cids), ev


def study_quiz(pid, eid):
    """3.8.1 (plans, rethought), Study for a quiz: one Due Crew deck of the
    open cards of every date that preps for the event (P.quiz: not a date
    after it), the shakiest first, Anki rescheduling them as it would; one
    undo step of Anki's own, then Anki's Study screen on it. A search run
    here; nothing is sent, and nobody else sees it."""
    cids, ev = quiz_cards(pid, eid)
    if ev is None:
        return
    if not cids:
        tooltip("None of its cards are open yet.")
        return
    name = _deck_name(f"Before {ev.get('name') or 'the quiz'}")  # 3.9.5: named for what it's before
    if _filtered(mw.col, name, cids, order=QUIZ_ORDER, until=str(ev.get("day") or "") or None):
        _after_change()
        did = mw.col.decks.id_for_name(name)
        if did:
            mw.col.decks.select(did)
            mw.moveToState("overview")


def _deck_name(name):
    """A filtered deck's name from a date's, under Due Crew's parent deck."""
    return P.our_deck(name)


def check_cards(col, idx, cids, n=CHECK_CARDS):
    """The unit's cards I've seen and that aren't suspended, most lapses first."""
    seen = [c for c in cids if idx.cards[c][1] != 0 and idx.cards[c][0] != -1]
    if not seen:
        return []
    out = []
    for i in range(0, len(seen), 500):
        chunk = ",".join(str(c) for c in seen[i:i + 500])
        out += col.db.all(f"SELECT id, lapses FROM cards WHERE id IN ({chunk})")
    out.sort(key=lambda r: (-int(r[1] or 0), int(r[0])))
    return [int(c) for c, _l in out[:n]]


def _filtered(col, name, cids, order=4, until=None, did=None):
    """Anki's own filtered deck over these cards, most lapses first (order 4;
    6, as they come in the deck, for new cards; 1, random, a date's Study);
    built (or rebuilt) under `name`. 3.9.5: until, the last day it's for (a
    quiz's, an exam's): the morning after, it's emptied (tidy_decks).
    did (Today's lesson, B): that deck, built again and named `name` (0: a
    new one), not the one named so. Returns the deck's id (true) when it
    took, else False."""
    try:
        did = (col.decks.id_for_name(name) or 0) if did is None else int(did)
        had = col.decks.id_for_name(P.PARENT)  # a "Due Crew" deck of the person's own isn't ours to tidy
        deck = col.sched.get_or_create_filtered_deck(deck_id=did)
        deck.name = name
        # 3.8.1: a new filtered deck comes with Anki's second filter (the current deck's new
        # cards, 20 of them), which slipped into every deck of ours: only our cards
        del deck.config.search_terms[1:]
        term = deck.config.search_terms[0]
        term.search = "cid:" + ",".join(str(c) for c in cids)
        term.limit = len(cids)
        term.order = order
        deck.config.reschedule = True
        got = col.sched.add_or_update_filtered_deck(deck)
        # Anki says which deck it built (a name taken by another deck gets a "+")
        made = int(getattr(got, "id", 0) or 0) or col.decks.id_for_name(name)
        _note_built(made, until)
        parent = col.decks.id_for_name(P.PARENT)
        if parent and (not had or int(parent) in (_pcfg().get("built") or [])):
            _note_built(parent)  # made with it (or before, by us), so the tidy may clear it
        return int(made) if made else True
    except Exception:
        oops()
        return False


BUILT_KEEP = 200  # filtered decks remembered for the morning's tidy


def _note_built(did, until=None):
    """3.8.0: a filtered deck Due Crew built, remembered (plans.json, this
    profile's) so the morning clears it once it's empty. 3.9.5: the last
    day it's for, when it has one (`until`: {did: day})."""
    if not did:
        return
    c = _pcfg()
    ids = [x for x in c.get("built") or [] if isinstance(x, int) and x != int(did)]
    c["built"] = (ids + [int(did)])[-BUILT_KEEP:]
    days = {k: v for k, v in (c.get("until") or {}).items() if str(k).isdigit() and int(k) in c["built"] and k != str(int(did))}
    if until:
        days[str(int(did))] = str(until)
    c["until"] = days
    c.pop("sd", None)  # 3.9.5's Super decks, gone before it shipped
    _psave(c)


def untils():
    """3.9.5: {did: the last day it's for}, of the decks built here with one."""
    return {int(k): str(v) for k, v in (_pcfg().get("until") or {}).items() if str(k).isdigit() and v}


RETIRED = ("Today's misses", "Slow but right")  # 3.9.5 (Sam's FSRS rule): decks Due Crew no longer makes


def tidy_decks(col):
    """3.8.0, the morning, before it unsuspends (its undo step stays the
    latest): the filtered decks Due Crew built that are empty now go, and
    the Due Crew parent deck once nothing's under it, in one step (Anki's
    Delete Deck). Returns how many. 3.9.5: a deck past its day (`until`:
    an exam or a quiz gone) and the decks Due Crew no longer makes
    (RETIRED) are emptied back into their decks first (Anki's Empty), so
    they go with the rest. Today's lesson, B: a plan's folder of lesson
    decks ("Due Crew::Path Book", made with its first) goes with its last."""
    try:
        normals = col.decks.all_names_and_ids(include_filtered=False)
        normal = {int(d.id) for d in normals}
        dyn = {int(d.id) for d in col.decks.all_names_and_ids(include_filtered=True)} - normal
        today = _today()
        old = [col.decks.id_for_name(P.our_deck(n)) for n in RETIRED]
        old += [did for did, day in untils().items() if day < today]
        for did in old:
            if did and int(did) in dyn:
                col.sched.empty_filtered_deck(int(did))
        rows = [(int(d.id), d.name, col.db.scalar("SELECT count() FROM cards WHERE did = ?", int(d.id)) or 0)
                for d in col.decks.all_names_and_ids(include_filtered=True) if int(d.id) not in normal]
        c = _pcfg()
        built = [x for x in c.get("built") or [] if isinstance(x, int)]
        pid = col.decks.id_for_name(P.PARENT)
        parent = None
        if pid and int(pid) in normal:
            parent = (int(pid), [int(x) for x in col.decks.deck_and_child_ids(pid) if int(x) != int(pid)],
                      col.db.scalar("SELECT count() FROM cards WHERE did = ? OR odid = ?", int(pid), int(pid)) or 0)
        folders = sorted(((str(d.name).count("::"), int(d.id)) for d in normals
                          if int(d.id) in built and str(d.name).startswith(P.PARENT + "::")), reverse=True)
        folders = [(f, [int(x) for x in col.decks.deck_and_child_ids(f) if int(x) != f],
                    col.db.scalar("SELECT count() FROM cards WHERE did = ? OR odid = ?", f, f) or 0) for _k, f in folders]
        gone = P.tidy(rows, built, parent, folders)
        keep = [x for x in built if (x in {r[0] for r in rows} or (parent and x == parent[0])
                                     or x in {f[0] for f in folders}) and x not in gone]
        if keep != built:
            c["built"] = keep
            _psave(c)
        if gone:
            col.decks.remove(gone)
        return len(gone)
    except Exception:
        oops()
        return 0


def build_checks(plan_list):
    """Main thread, in the morning: each checkpoint due today becomes a
    filtered deck, "Due Crew::Checkpoint · Cardio". Its score stays on this computer."""
    if not mw.col:
        return []
    import time as _time
    c = _pcfg()
    state = _state_cfg(c)
    today = _today()
    built = []
    for p in plan_list:
        st = state.get(p["id"])
        if not st or not _deck_ok(mw.col, st.get("deck_id")):
            continue
        due = checks_due(p["doc"], st, p.get("sched"), today)
        if not due:
            continue
        idx = P.DeckIndex(mw.col, st["deck_id"])
        for key, name, span, cap in due:
            pool = set()
            for u in span:
                pool |= idx.match(u, _swap(st), p["doc"])
            cids = check_cards(mw.col, idx, pool, cap)
            ok = bool(cids) and _filtered(mw.col, _deck_name(name), cids)
            st.setdefault("checks", {})[key] = {"day": today, "at": int(_time.time() * 1000), "name": name,
                                                "cids": cids if ok else []}
            if ok:
                built.append(name)
    c["plans"] = state
    _psave(c)
    if built:
        _after_change()
    return built


# Names of the parts after this one. The package sets them as each of those parts loads
# (an import here would load a later part before the ones between).
_LATER = ("OPENED_DATES", "_free", "_go_deck", "_lesson_did", "_lesson_drop", "_plan_idx", "_put_away",
          "_refill", "_take_next", "apply_catch", "back", "lesson_sync", "refresh_progress",
          "welcome_back")
OPENED_DATES = _free = _go_deck = _lesson_did = _lesson_drop = _plan_idx = None
_put_away = _refill = _take_next = apply_catch = back = lesson_sync = None
refresh_progress = welcome_back = None
