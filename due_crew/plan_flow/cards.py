"""Plans, the glue: pure over a collection (the searches, a unit's cards, progress), tested in the suite."""

import datetime
import json

from aqt import mw

from .. import app
from .. import plans as P
from .. import schedule as S
from ..app import _state
from ..app import cfg
from ..errs import oops

from .state import _deck_ok, _pcfg, _plan_doc, _psave, _sig, _swap, _today, followed, mine


# ---- pure over a collection: tested in tests/test_due_crew.py ----

def new_state(col, plan, deck_id=None, swap=None):
    """This computer's state for a plan: the deck it runs on (the best
    match unless given) and nothing applied yet. None when no deck here
    has any of it."""
    if deck_id is None:
        deck_id, swap = P.best_deck(col, plan["doc"])
    if deck_id is None:
        return None
    return {"deck_id": int(deck_id), "swap": list(swap) if swap else None, "applied": {}, "src": {},
            "seen_version": plan.get("version") or 0, "snapshot": P.snapshot(_plan_doc(plan))}


def skip_past(st, plan, today):
    """A plan followed on another computer, first seen here: the units that
    opened before today opened there (and came with the AnkiWeb sync), or
    were skipped there on purpose. Only today's open here."""
    sig = _sig(st)
    applied = st.setdefault("applied", {})
    for u in P.units(plan["doc"]):
        if str(u.get("opens") or "9999") < today and u["id"] not in applied:
            applied[u["id"]] = "skip:" + sig(u)
    return st


def first_here(col, st, plan, today):
    """A plan first seen on this computer (followed on another one, or on
    the site). On the plan's dates, skip_past. At my own pace (3.8.1) no
    date has passed: a date whose cards are all open here (AnkiWeb brought
    what the other computer opened) counts as opened, on a day this
    computer doesn't know (`own_opened` "", so not in my pace); the rest
    stay Up next. Before, they were skipped, and left Up next for good."""
    if not P.own_pace(plan):
        return skip_past(st, plan, today)
    if _deck_ok(col, st.get("deck_id")):
        _claim(P.DeckIndex(col, st["deck_id"]), st, mine(plan)["doc"], "")
    return st


def _claim(idx, st, doc, day, touched=None):
    """At my own pace: the Up next dates whose cards are all open here now
    (leeches aside) count as opened on `day`. touched (3.8.1): only the
    dates with a card among these (what an open just unsuspended), so on a
    deck whose cards were all open already one open doesn't claim every
    date. Returns how many."""
    sig, n = _sig(st), 0
    for u in P.up_next(doc, st.get("applied")):
        cids = idx.match(u, _swap(st), doc)
        if not cids or (touched is not None and not cids & touched):
            continue
        if any(idx.cards[c][0] == -1 and c not in idx.leech for c in cids):
            continue
        st.setdefault("applied", {})[u["id"]] = sig(u)
        st.setdefault("src", {})[u["id"]] = _src(idx, st, u, doc)
        st.setdefault("own_opened", {})[u["id"]] = day
        n += 1
    return n


def _src(idx, st, u, doc):
    """P.unit_sources for a date opening now, with (3.8.1) the cards it has
    from the plan's own tags, so a change to them opens just what it adds."""
    return P.unit_sources(u, st.get("deck_id"), st.get("swap"), idx.plan_part(u, doc, _swap(st)))


def _unit_cids(idx, st, u, doc, whole=False):
    """The cards applying `u` opens: its match, or, when it was applied
    before on this deck and the author changed it since, only the cards the
    change adds (a card suspended since by hand, or by Anki, stays so)."""
    cids = idx.match(u, _swap(st), doc)
    have = (st.get("applied") or {}).get(u["id"])
    if whole or not isinstance(have, str) or have.startswith("skip:"):
        return cids
    old = _src_cids(idx, st, u["id"], doc)
    return cids if old is None else cids - old


def _opened_cids(idx, st, doc):
    """3.8.1: every card a date opened here matched when it opened (its
    `src`), read now: Hold back never shuts one, even after an author moves
    it to a later date."""
    out = set()
    for uid, have in (st.get("applied") or {}).items():
        if isinstance(have, str) and not have.startswith("skip:"):
            out |= _src_cids(idx, st, uid, doc) or set()
    return out


def _src_cids(idx, st, uid, doc):
    """The cards a date matched when it was applied here (its `src`, read on
    this deck now), or None: no src, or it opened on another deck (what had
    opened opens there too)."""
    was = (st.get("src") or {}).get(uid)
    if not was or len(was) < 5:
        return None
    did, swap, tags, decks, cards = was[:5]
    if did != st.get("deck_id") or list(swap or []) != list(st.get("swap") or []):
        return None
    before = {"tags": tags, "decks": decks, "cards": cards}
    # what came after the first five (P.unit_sources): a date's searches
    # (3.3, C3: a list of strings), its pasted ids (E1: [nids, cids]), its
    # notes and the refs behind its ids (3.6.5: a dict), C5's note ids (3.7.2: {"ids"})
    pt = None
    for extra in was[5:]:
        if isinstance(extra, dict):
            if "pt" in extra:
                pt = {int(c) for c in extra.get("pt") or []}  # 3.8.1: what the plan's own tags held then
            if "ids" in extra:
                before["ids"] = extra.get("ids") or []
            if "notes" in extra or "idr" in extra:
                before["notes"], before["idr"] = extra.get("notes") or [], extra.get("idr") or []
        elif extra and all(isinstance(x, str) for x in extra):
            before["search"] = extra
        elif isinstance(extra, list) and len(extra) == 2 and all(isinstance(x, list) for x in extra):
            before["nids"], before["cids"] = extra
    deck = str(doc.get("deck") or "") if isinstance(doc, dict) else doc
    if pt is not None:
        # the plan's own tags as they were when it opened, not as they read now
        before["tags"] = [t for t in before["tags"] if not str(t).lower().startswith(P.TAG_PARENT.lower() + "::")]
        return idx.match(before, _swap(st), deck) | pt
    return idx.match(before, _swap(st), deck)


def _tally(idx, st, u, deck):
    """3.6.5: what a date leaves shut here, for the plan card: leeches (Anki
    suspended them; a plan never opens one) and exact picks (single cards,
    notes) this copy doesn't have. Counted when the date opens."""
    cids = idx.match(u, _swap(st), deck)
    lee = sum(1 for c in cids if c in idx.leech and idx.cards[c][0] == -1)
    miss, of = idx.exact_missing(u)
    for key, val in (("leeches", lee), ("missing", [miss, of] if miss else None)):
        d = st.setdefault(key, {})
        if val:
            d[u["id"]] = val
        else:
            d.pop(u["id"], None)


def aside(plan, st):
    """3.6.5: [leeches, missing, of] over the plan's dates still on it."""
    ids = {u["id"] for u in P.units(plan.get("doc") or {})}
    lee = sum(int(n) for k, n in ((st or {}).get("leeches") or {}).items() if k in ids)
    ms = [v for k, v in ((st or {}).get("missing") or {}).items() if k in ids]
    return [lee, sum(int(m) for m, _o in ms), sum(int(o) for _m, o in ms)]


def run(col, plan_list, state, today, mode=None, everything=False, dry=False):
    """Open what's due (or, with `everything`, every unit) for these plans,
    in one undo step. mode "skip" marks due units applied without opening
    them (joining late, "Start from the next unit"); "open" is the default.
    A unit a late join skipped stays skipped unless `everything`. Mutates
    `state`. Returns {n, names, label, per: {plan id: [names, n]},
    units: {plan id: [unit ids opened]}}. G2: a unit put off to a later
    morning (`later` in the state) waits for it, unless `everything`.
    3.8.1: at my own pace too; `was` {plan id: {unit id: what it was}} is
    each own-pace date as it stood before, so Not today can put it back."""
    all_cids, names, per, opened_units, spread, before = set(), [], {}, {}, {}, {}
    dates = []  # 3.8.1: [plan id, unit id, name, cards it opened], the morning's line by date
    opens_reset()  # 3.9.5: what Browse's Due says of a date's cards changes with it
    for p in plan_list:
        p = mine(p)  # G3, G4: my shift, my skips
        st = state.get(p["id"])
        if not st or not _deck_ok(col, st.get("deck_id")):
            continue
        doc = p["doc"]
        applied = st.setdefault("applied", {})
        sig = _sig(st)
        src = st.setdefault("src", {})
        # 3.8.0, at my own pace: a morning opens only what an author adds to dates I opened,
        # and ("next") the next date once I've seen most of the last one I opened. 3.8.1:
        # whatever the mode (a resume's "start from the next date" once turned it off and
        # skipped every passed date out of Up next)
        own = P.own_pace(p) and not everything
        pmode = None if own else mode
        # 3.3, C2: a follower who studies on a phone opens days early
        when = S.iso(S.d(today) + datetime.timedelta(days=int(p.get("early") or 0))) if mode != "skip" else today
        if (p.get("sched") or S.has_even(doc)) and not everything and mode != "skip" and not own:
            cnt = {}
            pnames, pcids, puids = _spread(col, p, st, when, today, counts=cnt)
            if pnames:
                opened_units[p["id"]] = puids  # so Not today can put them off
                spread[p["id"]] = puids  # and Undo leaves them to their schedule (3.7.2)
                per[p["id"]] = [pnames, len(pcids)]
                by = {u["id"]: u for u in P.units(doc)}
                dates += [[p["id"], x, str((by.get(x) or {}).get("name") or "?"), int(cnt.get(x) or 0)] for x in puids]
                names += pnames
                all_cids |= pcids
            continue
        idx = None
        if own:
            # 3.8.1: a date put off (Not today) waits for its morning here too
            later = st.get("later") or {}
            items = [(u, how) for u, how in P.own_due(doc, applied, sig) if str(later.get(u["id"]) or "") <= today]
            was = before.setdefault(p["id"], {})
            for u, _how in items:
                was[u["id"]] = _was(st, u["id"])
            if p.get("own") == "next" and not dry:  # a morning's, never an update's line
                idx = P.DeckIndex(col, st["deck_id"])
                nxt = P.next_by_itself(doc, applied, st.get("own_opened"), P.progress(idx, doc, _swap(st), _aside(idx, st, doc)))
                if nxt and nxt["id"] not in {u["id"] for u, _h in items} and str(later.get(nxt["id"]) or "") <= today:
                    was[nxt["id"]] = _was(st, nxt["id"])
                    applied.pop(nxt["id"], None)  # shut again since (Undo): it opens whole
                    src.pop(nxt["id"], None)
                    items.append((nxt, "open"))
                    st.setdefault("own_opened", {})[nxt["id"]] = today
            for u, _how in items:
                later.pop(u["id"], None)
        else:
            items = ([(u, "open") for u in P.units(doc)] if everything
                     else P.due_now(doc, applied, when, sig))
            later = st.get("later") or {}
            if not everything:
                items = [(u, how) for u, how in items if str(later.get(u["id"]) or "") <= today]
            if st.get("line") and not everything and pmode != "skip" and _line_can(p, st):
                # 3.9.10, catching up: a day that never opened here waits in line (what an author adds to an open one still comes)
                items = [(u, how) for u, how in items if not (how == "open" and u["id"] not in applied)]
            for u, _how in items:
                later.pop(u["id"], None)
        if not items:
            continue
        idx = idx or P.DeckIndex(col, st["deck_id"])
        pnames, pcids = [], set()
        for u, how in items:
            if how == "open" and pmode != "skip":
                cids = idx.openable(_unit_cids(idx, st, u, doc, whole=everything))
                _tally(idx, st, u, doc)
                applied[u["id"]] = sig(u)
                src[u["id"]] = _src(idx, st, u, doc)
                if cids:
                    pnames.append(u.get("name") or "?")
                    dates.append([p["id"], u["id"], str(u.get("name") or "?"), len(cids - pcids)])  # 3.8.1
                    pcids |= cids
                    opened_units.setdefault(p["id"], []).append(u["id"])
            else:
                applied[u["id"]] = "skip:" + sig(u)
        if pnames:
            per[p["id"]] = [pnames, len(pcids)]
            names += pnames
            all_cids |= pcids
    label = P.step_label(names) if names else ""
    # dry (3.7.3): what it would open, for the update line; nothing is touched
    n = P.open_cards(col, all_cids, label, dry=dry) if names else 0
    was = {pid: {uid: v for uid, v in b.items() if uid in (opened_units.get(pid) or ())} for pid, b in before.items()}
    return {"n": n, "names": names, "label": label, "per": per, "units": opened_units, "spread": spread,
            "was": {pid: b for pid, b in was.items() if b}, "dates": dates}


def _line_can(p, st):
    """3.9.10: a plan that can wait in line: on its dates (not my own pace, not 3.2's schedule or even slices), running, not turned off."""
    return bool(st) and not (P.own_pace(p) or p.get("paused") or p.get("sched") or S.has_even(p["doc"]) or st.get("line_off"))


def _line_path(p, st, prog, today):
    return P.path(_plan_doc(p), prog or {}, today, applied=st.get("applied") or {}, shift=int(p.get("shift") or 0),
                  skipped=p.get("skipped") or (), moved=p.get("moved"), sched=False)


def line_sync(plan_list, state, prog, today):
    """3.9.10: which plans wait in line, from my numbers: one starts when
    it's far enough behind (P.line_starts) and ends when nothing's owed.
    Mutates `state`; (changed, [the plans whose line just ended])."""
    changed, ended = False, []
    for p in plan_list:
        st = state.get(p["id"])
        if not st:
            continue
        if not _line_can(p, st):
            changed = st.pop("line", None) is not None or changed
            continue
        path = _line_path(p, st, (prog or {}).get(p["id"]), today)
        if st.get("line"):
            if not P.line_view(path, P.line_waits(p["doc"], st.get("applied"), today), today)["rows"]:
                st.pop("line", None)
                changed = True
                ended.append(p)
        elif P.line_starts(path, today):
            st["line"] = {"since": today}
            changed = True
    return changed, ended


def _line_refresh(prog):
    """After my numbers are read: the lines kept in plans.json; a line that
    just ended opens what waited for today (on the Decks screen, its own undo step)."""
    try:
        c = _pcfg()
        state = _state_cfg(c)
        changed, ended = line_sync(followed(), state, prog, _today())
        if not changed:
            return
        c["plans"] = state
        _psave(c)
        if ended and getattr(mw, "state", "") == "deckBrowser":
            from aqt.qt import QTimer
            ids = [p["id"] for p in ended]
            QTimer.singleShot(0, lambda: _open_now([x for x in followed() if x["id"] in ids]))
    except Exception:
        oops()


def line_study(pid, uid):
    """Study on a row of the line: a date that waited opens first (its own
    undo step), then its deck as Study on any date (study_date)."""
    p = next((x for x in followed() if x["id"] == pid), None)
    c = _pcfg()
    state = _state_cfg(c)
    st = state.get(pid)
    if p is None or not st or not mw.col:
        return
    if uid not in (st.get("applied") or {}):
        try:
            res = open_one(mw.col, p, st, uid, _today())
        except Exception:
            oops()
            return
        c["plans"] = state
        _psave(c)
        if res["n"]:
            _after_change()
    study_date(pid, uid)
    refresh_progress()
    if getattr(mw, "state", "") == "deckBrowser":
        app.swap(cfg())


def line_off(pid):
    """Don't wait: this plan opens its days as they come again, here (plans.json's line_off), and what waited opens now."""
    c = _pcfg()
    state = _state_cfg(c)
    st = state.get(pid)
    if not st:
        return
    st.pop("line", None)
    st["line_off"] = True
    c["plans"] = state
    _psave(c)
    _open_now([x for x in followed() if x["id"] == pid])
    app.swap(cfg())


def open_one(col, plan, st, uid, today, first=False, whole=False):
    """G1: one date, now, in one undo step; the morning won't open it again.
    {n, names, label}. first (3.8.0): first in Anki's line of new cards.
    3.8.1: a date that opened here and has none of its cards open now (Edit
    › Undo closed it) opens whole, as `whole` does; else only what changed."""
    p = mine(plan)
    u = next((x for x in P.units(p["doc"]) if x["id"] == uid), None)
    if u is None or not st or not _deck_ok(col, st.get("deck_id")):
        return {"n": 0, "names": [], "label": ""}
    idx = P.DeckIndex(col, st["deck_id"])
    if not whole and P.opened_here(st.get("applied"), u):
        every = idx.match(u, _swap(st), p["doc"])
        whole = bool(every) and all(idx.cards[c][0] == -1 for c in every)
    cids = idx.openable(_unit_cids(idx, st, u, p["doc"], whole=whole))
    _tally(idx, st, u, p["doc"])
    st.setdefault("applied", {})[uid] = _sig(st)(u)
    st.setdefault("src", {})[uid] = _src(idx, st, u, p["doc"])
    (st.get("later") or {}).pop(uid, None)
    name = u.get("name") or "?"
    label = P.step_label([name])
    return {"n": P.open_cards(col, cids, label, first=first) if cids else 0, "names": [name], "label": label}


def put_off(st, uids, today, was=None):
    """G2, Not today: after Anki's undo closed this morning's cards again,
    these units open on tomorrow's morning (they're not applied any more).
    3.8.1, at my own pace (`was`: each date as it stood before the morning,
    run's `was`): a date I opened stays opened as it was, and what an author
    added to it waits for tomorrow's morning (as ask_later); the next date
    that opened by itself is Up next again till then."""
    tomorrow = S.iso(S.d(today) + datetime.timedelta(days=1))
    later = st.setdefault("later", {})
    for uid in uids:
        if was is not None and uid in was:
            for k, v in (was.get(uid) or {}).items():
                if v is None:
                    (st.get(k) or {}).pop(uid, None)
                else:
                    st.setdefault(k, {})[uid] = v
        else:
            (st.get("applied") or {}).pop(uid, None)
            (st.get("src") or {}).pop(uid, None)
        later[uid] = tomorrow
    return st


def ask_later(st, uids, today):
    """3.7.3, Not today on an update: those dates' changes open on tomorrow's
    morning. Unlike put_off nothing was opened, so they stay applied as
    they were: tomorrow opens only what the update adds."""
    tomorrow = S.iso(S.d(today) + datetime.timedelta(days=1))
    later = st.setdefault("later", {})
    for uid in uids:
        later[uid] = tomorrow
    return st


def _spread(col, p, st, today, now=None, counts=None):
    """3.2, a plan run on my schedule: each unit whose window has started
    opens up to today's quota, the first cards in the deck's order. A unit
    is marked applied once its window is over (all of it open), so from
    then on it behaves as in 3.1: an author's change opens only what it
    adds. Skipped units stay skipped. G2: a unit put off (`later`) waits
    for that morning (`now`, today's date when `today` looks ahead).
    Returns (names, cids to open, unit ids opened); counts (3.8.1), when
    given, gets {unit id: cards it opens} for the morning's line."""
    doc, sched = p["doc"], p.get("sched")
    later = st.get("later") or {}
    now = now or today
    applied, src, sig = st["applied"], st["src"], _sig(st)
    day = S.d(today)
    shift = S.shift_days(doc, sched)
    idx = P.DeckIndex(col, st["deck_id"])
    names, cids_out, uids = [], set(), []
    for u in P.units(doc):
        have, s = applied.get(u["id"]), sig(u)
        if isinstance(have, str) and (have == s or have.startswith("skip:")):
            continue
        if str(later.get(u["id"]) or "") > now:
            continue
        first, _last = S.window(doc, u, shift)
        if day < first:
            continue
        later.pop(u["id"], None)
        cids = _unit_cids(idx, st, u, doc)
        if have:  # applied whole before, and the author changed it: what's new opens
            chosen = idx.openable(cids)
            done = True
        else:
            order = [(c, sus) for c, sus in idx.in_order(cids) if not (sus and c in idx.leech)]
            open_now = sum(1 for _c, sus in idx.in_order(cids) if not sus)
            want = S.quota(doc, u, sched, len(cids), day, shift)
            chosen = set(S.pick(order, open_now, want))
            done = want >= len(cids)
        if done:
            applied[u["id"]] = s
            src[u["id"]] = _src(idx, st, u, doc)
            _tally(idx, st, u, doc)
        if chosen:
            names.append(u.get("name") or "?")
            if counts is not None:
                counts[u["id"]] = len(idx.openable(set(chosen)) - cids_out)
            cids_out |= set(chosen)
            uids.append(u["id"])
    return names, cids_out, uids


def waiting(col, plan, st, today):
    """(units, cards) that have opened by date and aren't applied here:
    what a late join or a resume asks about."""
    plan = mine(plan)
    if not st or not _deck_ok(col, st.get("deck_id")):
        return 0, 0
    due = [u for u, how in P.due_now(plan["doc"], st.get("applied") or {}, today, _sig(st)) if how == "open"]
    if not due:
        return 0, 0
    idx = P.DeckIndex(col, st["deck_id"])
    cids = set()
    for u in due:
        cids |= _unit_cids(idx, st, u, plan["doc"])
    return len(due), len(cids)


def _index(col, st, idxs):
    """One read of a deck per refresh: shared by progress and today's session."""
    did = int(st["deck_id"])
    if idxs is None:
        return P.DeckIndex(col, did)
    if did not in idxs:
        idxs[did] = P.DeckIndex(col, did)
    return idxs[did]


def progress(col, plan_list, state, idxs=None):
    """{plan id: {unit id: [opened, seen, total]}} for the plans that run here."""
    out = {}
    for p in plan_list:
        st = state.get(p["id"])
        if not st or not _deck_ok(col, st.get("deck_id")):
            continue
        idx = _index(col, st, idxs)
        out[p["id"]] = P.progress(idx, p["doc"], _swap(st), _aside(idx, st, p["doc"]))
    return out


def _aside(idx, st, doc):
    """3.9.6: the cards I suspended myself after their date opened here (P.set_aside)."""
    try:
        return P.set_aside(idx, doc, _swap(st), st.get("applied"), st.get("held"))
    except Exception:  # noqa: BLE001 (a count, never a crash: nothing set aside)
        oops()
        return frozenset()


_PICKS = {}  # 3.8.1: (deck id, a date's picks): (the deck's tag index they were named from, their labels)


def pick_names(col, plan_list, state, idxs=None):
    """3.8.1: {plan id: {unit id: [[tag path, n], ...]}}: each date's picked
    cards here, by the deck tags they sit under (P.pick_labels), then ["", n]
    for the ones under none; named again only when the deck's notes or the
    picks change. Main thread, with the refresh's deck reads."""
    out = {}
    for p in plan_list:
        st = state.get(p["id"])
        if not st or not _deck_ok(col, st.get("deck_id")):
            continue
        idx = None
        for u in P.units(p["doc"]):
            src = P.picks(u)
            if not src:
                continue
            idx = idx or _index(col, st, idxs)
            key = (int(st["deck_id"]), json.dumps([src, st.get("swap")], sort_keys=True))
            hit = _PICKS.get(key)
            if hit and hit[0] is idx.by_tag:
                got = hit[1]
            else:
                cids = idx.match(src, _swap(st), p["doc"])
                got = P.pick_labels(idx, cids)
                rest = len(cids) - sum(n for _p, n in got)
                got += [["", rest]] if got and rest > 0 else []
                for k in [k for k, v in _PICKS.items() if k[0] == key[0] and v[0] is not idx.by_tag]:
                    del _PICKS[k]  # read from the deck's notes as they were
                _PICKS[key] = (idx.by_tag, got)
            if got:
                out.setdefault(p["id"], {})[u["id"]] = got
    return out


def named(pid, doc):
    """3.8.1: the doc with each date's picked cards named as this copy has
    them (`_pl`, for P.topic_items), from the last refresh; a copy, so the
    session's plan stays as it came."""
    return P.with_picks(doc, (_state.get("plan_picks") or {}).get(pid))


def loads(col, plan_list, state, idxs=None):
    """3.7.81: {plan id: {unit id: [seen, open, locked]}} on my own days
    (plans.load), from the deck read the progress already made."""
    out = {}
    for p in plan_list:
        st = state.get(p["id"])
        if not st or not _deck_ok(col, st.get("deck_id")):
            continue
        idx = _index(col, st, idxs)
        out[p["id"]] = P.load(idx, mine(p)["doc"], _swap(st), _aside(idx, st, mine(p)["doc"]))
    return out


def session_view(plan, st, idx, first_seen, today, pace=(8.0, 30.0), due=None, answered=None):
    """3.2, what the plan card says about today for a plan on my schedule:
    {kind, target, done, share, behind, due, minutes, missed: [iso], ask
    (the missed-days question, or None), recap (last plan week, on the
    first day of a new one) or None, checks: [...]}. None without a
    schedule. first_seen: {cid: days ago} (0 today); due: reviews due in
    the plan's deck now, when known; answered: {cid: (first answer ease,
    ms)} since each checkpoint was built. Pure over the index."""
    sched = plan.get("sched")  # 3.3: without one, the plan's own days: each date on its day
    if not st:
        return None
    doc = plan["doc"]
    day = S.d(today)
    shift = S.shift_days(doc, sched)
    matches = P.unit_matches(idx, doc, _swap(st))
    totals, seen_before, seen_now, new_today = {}, {}, {}, 0
    new_by_day = {}
    note_ago = {}  # a note's first answer, days ago, from its cards' (Anki buries the rest)
    for c, ago in first_seen.items():
        nid = idx.nid_of.get(c)
        if nid is not None:
            note_ago[nid] = max(note_ago.get(nid, -1), int(ago))
    started = idx.started()

    def started_ago(c):
        queue, ctype = idx.cards[c]
        nid = idx.nid_of.get(c)
        return note_ago.get(nid) if ctype == 0 and queue != -1 and nid in started else None

    for uid, cids in matches.items():
        totals[uid] = len(cids)
        seen = seen_now[uid] = idx.counts(cids)[1]
        # a sibling Anki buried today counts as seen (plans.counts): done
        # today too, so the Today box reaches done when Due does; only for a
        # note started today (one started before was seen before today)
        today_n = sum(1 for c in cids if first_seen.get(c) == 0) + idx.buried_today(cids, first_seen)
        new_today += today_n
        seen_before[uid] = seen - today_n
        for c in cids:
            ago = first_seen.get(c)
            if ago is None:
                # a new sibling Anki buried or spaced out (counts calls it seen):
                # its note's first day, so a cloze-heavy day isn't a missed one
                ago = started_ago(c)
            if ago is not None:
                k = S.iso(day - datetime.timedelta(days=ago))
                new_by_day[k] = new_by_day.get(k, 0) + 1
    catch = _missed(st).get("mode")
    view = S.today_view(doc, sched, totals, seen_before, new_today, day, catch=catch, seen_now=seen_now)
    shares = {}
    for i in range(1, 15):
        x = day - datetime.timedelta(days=i)
        shares[S.iso(x)] = sum(S.share(doc, u, sched, totals.get(u["id"], 0), x, shift) for u in P.units(doc))
    missed = S.missed_study_days(doc, sched, day, new_by_day, shares)
    asked = _missed(st).get("day") or ""
    ask = None
    if sched and missed and view["behind"] and S.iso(missed[0]) > asked:
        waiting = view["behind"]
        push = S.pushed_start(doc, sched, len(missed))
        ask = {"days": [S.iso(x) for x in reversed(missed)], "waiting": waiting,
               "spread": -(-waiting // S.CATCH_UP_DAYS), "push": len(missed) if push else 0}
    secs_review, secs_new = pace
    left_new = max(0, view["target"] - view["done"])
    minutes = int(round(((due or 0) * secs_review + left_new * secs_new) / 60))
    recap = None
    week = S.plan_week(doc, day, shift)
    if day.weekday() == 0 and week > 1:
        days = [day - datetime.timedelta(days=i) for i in range(1, 8)]
        study = [x for x in days if shares.get(S.iso(x))]
        kept = [x for x in study if new_by_day.get(S.iso(x), 0) >= shares[S.iso(x)] * S.MISSED_SHARE]
        recap = {"n": week - 1, "sessions": [len(kept), len(study)],
                 "new": sum(new_by_day.get(S.iso(x), 0) for x in days), "on_track": not view["behind"]}
    checks = []
    for uid, c in sorted((st.get("checks") or {}).items()):
        unit = next((u for u in P.units(doc) if u["id"] == uid), None)
        if not isinstance(c, dict) or not (unit or c.get("name")):
            continue
        firsts = [(answered or {}).get(cid) for cid in c.get("cids") or []]
        done = [f for f in firsts if f]
        checks.append({"name": c.get("name") or (unit or {}).get("name") or "?", "n": len(c.get("cids") or []), "answered": len(done),
                       "right": sum(1 for e, _t in done if e > 1), "day": c.get("day") or ""})
    return dict(view, due=due, minutes=minutes, missed=[S.iso(x) for x in missed], ask=ask,
                recap=recap, checks=checks, phase=S.phase(doc, day, shift))


def _missed(st):
    """3.2's answer to the missed-days question, {mode, day} (`missed` since
    3.8.1; a state not upgraded yet still has it as `catch`)."""
    m = (st or {}).get("missed")
    if isinstance(m, dict):
        return m
    c = (st or {}).get("catch")
    return c if isinstance(c, dict) and "mode" in c and "until" not in c else {}


def to_send(plan_list, prog):
    """What the sync carries: progress on the plans I follow, at most 50.
    3.7.6: kept for my own views on the site; only a plan whose team I'm
    on (`share`) counts it for anyone else."""
    mine_ = {p["id"] for p in plan_list}
    return dict([(pid, units) for pid, units in sorted(prog.items()) if pid in mine_ and units][:50])


def _short_day(iso, today):
    """"Mon" within the coming week, else "Mon 26 Oct"."""
    try:
        d, t = datetime.date.fromisoformat(iso), datetime.date.fromisoformat(today)
    except ValueError:
        return str(iso)
    return f"{d:%a}" if 0 <= (d - t).days < 7 else P.fmt_day(iso)


def card_view(plan, st, prog, today, session=None, week_offset=0):
    """What board._plans_html draws for one plan. Strings are raw here;
    the board escapes them."""
    plan = mine(plan)  # G3, G4: my shift, my skips
    doc = plan["doc"]
    week, weeks = P.span_weeks(doc, today)
    us = P.units(doc)
    # plans, end to end: the whole plan as a path, its lessons on my days, and what's behind on it
    path = P.path(_plan_doc(plan), prog, today, applied=(st or {}).get("applied") if st else None,
                  shift=int(plan.get("shift") or 0), skipped=plan.get("skipped") or (), moved=plan.get("moved"),
                  sched=bool(plan.get("sched")))
    if plan.get("paused"):
        sub = f"paused until {P.fmt_day(plan['until'])}" if plan.get("until") else "paused"
    elif week == 0 and us:
        sub = f"starts {P.fmt_day(us[0]['opens'])}"
    elif st and P.joy_finished(path):  # 3.9.6: the finish line, kept on the card
        n = len(P.joy_sets(path))
        sub = f"all {n} set{'s' if n != 1 else ''} done"
    else:
        sub = f"set {path['at']} of {path['of']}" if path["at"] else f"week {week} of {weeks}"
    if int(plan.get("shift") or 0):
        sub += f" · your dates +{int(plan['shift'])} day{'s' if int(plan['shift']) != 1 else ''}"
    if int(plan.get("early") or 0) and not plan.get("paused"):
        n = int(plan["early"])  # 3.3, C2 (on the Today box until 3.8.0)
        sub += f" · opens {n} day{'s' if n != 1 else ''} early"
    sub += f" · {int(plan.get('followers') or 0):,} following"
    followers = int(plan.get("followers") or 0)
    crew = plan.get("crewDone")  # 3.9.5: only from three people counted; none, no crew count
    rows = []
    open_units = P.opened_by_date(doc, today)
    current = [u for u in open_units if u.get("due") and u["due"] >= today]
    now_id = current[0]["id"] if current else (open_units[-1]["id"] if open_units else None)
    for u in open_units:
        o, s, t = (prog or {}).get(u["id"], [0, 0, 0])
        done = int(crew.get(u["id"]) or 0) if isinstance(crew, dict) else None
        bits = [f"crew {done:,}/{followers:,}"] if done is not None else []
        if u["id"] == now_id and u.get("due") and u["due"] >= today:
            bits.append(f"due {_short_day(u['due'], today)}")
        rows.append({"name": u.get("name") or "?", "uid": u["id"], "state": "now" if u["id"] == now_id else "open",
                     "seen": [s, t], "crew": [done, followers] if done is not None else None, "n": " · ".join(bits),
                     "missing": not t})
    nxt = P.next_unit(doc, today)
    # G3: dates I skip, around now: crossed out, with Undo skip
    skipped = set(plan.get("skipped") or [])
    shift = int(plan.get("shift") or 0)
    horizon = nxt["opens"] if nxt else "9999"
    week_ago = S.iso(S.d(today) - datetime.timedelta(days=7))
    for u in P.units(_plan_doc(plan)):
        mine_opens = P._later(u.get("opens"), shift) if shift else u.get("opens")
        if u["id"] in skipped and week_ago <= str(mine_opens or "") <= horizon:
            rows.append({"name": u.get("name") or "?", "uid": u["id"], "state": "skip", "seen": None, "crew": None,
                         "n": "skipped", "missing": False})
    if nxt:
        rows.append({"name": nxt.get("name") or "?", "uid": nxt["id"], "state": "later", "seen": None, "crew": None,
                     "n": f"opens {P.fmt_day(nxt['opens'])}", "missing": False})
    # G2: what Not today put off to tomorrow
    later = {k: v for k, v in ((st or {}).get("later") or {}).items() if str(v) > today}
    by_id = {u["id"]: u for u in P.units(doc)}
    put_off = [by_id[k].get("name") or "?" for k in later if k in by_id]
    # G5: new cards from earlier dates I haven't seen, and a catch-up running
    catch = (st or {}).get("catch") if str(((st or {}).get("catch") or {}).get("until") or "") >= today else None
    waiting = 0 if plan.get("paused") or plan.get("sched") or not st else P.waiting_new(doc, prog or {}, today)
    no_deck = not st
    prep = None if plan.get("paused") else P.prep_for(doc, today)
    if prep:
        prep["when"] = _short_day(prep["day"], today)
    # 3.8.1 (plans, rethought): from three days out, Study for a quiz: its dates' open cards in one deck
    quiz = None if plan.get("paused") or not st else P.quiz(doc, today, prog)
    if quiz:
        quiz["when"], quiz["today"] = _short_day(quiz["day"], today), quiz["day"] == today
    # 3.5.0: a week of the calendar (today's dates are Due's Today since 3.8.0)
    moved = plan.get("moved") or {}
    skipped_units = [dict(u, opens=P._later(u["opens"], shift + int(moved.get(u["id"]) or 0)))
                     if shift or moved.get(u["id"]) else u
                     for u in P.units(_plan_doc(plan)) if u["id"] in skipped]
    week = P.week_view(named(plan["id"], doc), prog, today, P.week_start(today, week_offset), skipped=skipped_units,
                       ld=(_state.get("plan_load") or {}).get(plan["id"]), shut=_shut_dates(plan, st, prog))
    _week_more(week, st, prog, today)  # 3.8.1: what stayed shut, Study, my own load
    change = None
    if st and st.get("snapshot") is not None and st.get("seen_version") != plan.get("version"):
        change = P.change_note(plan.get("ownerName"), st["snapshot"], _plan_doc(plan))
    own = P.own_pace(plan) and not plan.get("paused") and not no_deck
    # round five: the card's line about the plan's day (Due's Today and Upcoming have each date):
    # what today's dates have left; plans, end to end: what's behind is the path's (a lesson whose
    # last day passed with cards left, opened here), its own line with Behind…
    status = behind = line = None
    if st and st.get("line") and not no_deck and _line_can(plan, st):  # 3.9.10: catching up: the line, in Behind's place
        line = P.line_view(path, P.line_waits(doc, st.get("applied"), today), today)
        line = line if line["rows"] else None
        for r in (line or {}).get("rows") or []:
            d = S.d(r["day"])
            r["when"] = f"{d:%a} {d.day}"
    if not (no_deck or plan.get("paused") or own):
        left = lambda u: max(0, int(_t3(prog, u)[2]) - int(_t3(prog, u)[1]))
        behind = P.behind_of(path, today)
        status = {"togo": sum(left(u) for u in us if str(u.get("opens") or "") == today),
                  "behind": behind["left"] if behind else 0,
                  "since": P.weekday_or_day(behind["since"], today) if behind else ""}
    if own:  # 3.8.0: no Behind at my own pace; what's next, and where the plan is
        sub = f"at your pace · {followers:,} following"
        waiting, catch, session = 0, None, None
    return {"id": plan["id"], "title": P.plan_title(plan), "name": str(plan.get("name") or "Plan"), "sub": sub, "rows": rows,
            "own": own_view(plan, st, prog, today) if own else None,
            "lines": [] if no_deck or plan.get("paused") or own else P.ahead_behind(doc, prog or {}, today),
            "change": change, "no_deck": no_deck, "paused": bool(plan.get("paused")),
            # 3.8.0: the plan's tags that came today, once (OK, or Browse them)
            "tag_news": (st or {}).get("tag_news") if str(((st or {}).get("tag_news") or {}).get("day") or "") == today else None,
            # 3.7.3: what an author's update adds to today and earlier, waiting for Open; their posts
            "update": (_state.get("plan_updates") or {}).get(plan["id"]) if mw else None,
            "posts": unread_posts(plan) if mw else [],
            "team_ask": bool(plan.get("teamAsk")),  # 3.7.6: shared before the merge: asked once
            "owner_name": str(plan.get("ownerName") or ""),
            "session": None if no_deck or plan.get("paused") else session,
            "prep": prep, "quiz": quiz,
            "fallback_ok": bool(((_pcfg().get("fallback_ok") or {}) if mw else {}).get(plan["id"])),
            "aside": aside(plan, st), "aside_ok": list(((_pcfg().get("aside_ok") or {}) if mw else {}).get(plan["id"]) or [0, 0]),
            "put_off": put_off, "waiting": waiting,
            # 3.8.1: put off by Welcome back's Not today: tomorrow morning asks again
            "put_off_ask": bool(put_off) and str(((st or {}).get("away") or {}).get("day") or "") == today,
            "week": week, "week_offset": int(week_offset), "status": status,
            "path": path if status is not None else None, "behind": None if line else behind,  # plans, end to end
            "line": line,
            "lesson_deck": None if no_deck or plan.get("paused") else lesson_view(plan, st, today),  # Today's lesson, B
            # Slide on Behind…, today: the card's Undo (plan_board.unslide)
            "slid": int(((st or {}).get("slid") or {}).get("days") or 0) if ((st or {}).get("slid") or {}).get("day") == today else 0,
            "catch": {"extra": int(catch.get("extra") or 0), "until": _short_day(catch["until"], today)} if catch else None}


def _t3(prog, u):
    """A date's [opened, seen, total] here."""
    return (list((prog or {}).get(u["id"]) or []) + [0, 0, 0])[:3]


def _shut_dates(plan, st, prog):
    """3.8.1: the dates the week offers Open now on although their day has
    come: ones that opened here and have none of their cards open now
    (Edit › Undo closed them), and at my own pace, ones I haven't opened."""
    if not st or plan.get("paused"):
        return set()
    applied, own, out = st.get("applied") or {}, P.own_pace(plan), set()
    for u in P.units(plan["doc"]):
        o, _s, t = ((prog or {}).get(u["id"]) or [0, 0, 0])[:3]
        have = applied.get(u["id"])
        skip = isinstance(have, str) and have.startswith("skip:")
        if int(t) and not int(o) and not skip and (own or isinstance(have, str)):
            out.add(u["id"])
    return out


def offers_view(offers, squad_names, following_ids, dismissed):
    return [{"id": o["id"], "owner": o.get("ownerName") or "?", "name": o.get("name") or "Plan",
             "squad": squad_names.get(o.get("squad"), "your squad")}
            for o in offers or [] if o["id"] not in following_ids and o["id"] not in dismissed][:2]


# Names of the parts after this one. The package sets them as each of those parts loads
# (an import here would load a later part before the ones between).
_LATER = ("_after_change", "_open_now", "_state_cfg", "_was", "_week_more", "lesson_view", "opens_reset",
          "own_view", "refresh_progress", "study", "study_date", "unread_posts")
_after_change = _open_now = _state_cfg = _was = _week_more = lesson_view = None
opens_reset = own_view = refresh_progress = study = study_date = unread_posts = None
