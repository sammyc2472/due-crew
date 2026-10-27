"""3.1 plans, the glue: what this computer remembers about the plans I
follow, the morning, progress for the sync, the Decks tab's plan card,
and the menus. Main-thread rules as in __init__: every collection read and
the one unsuspend step happen here, on the main thread; plan_flow makes a
request of its own only on a click (follow, pause, stop) and, for a plan
I write, at the day's first refresh (send_ids, send_trees: in the
background, only when what they send changed).

Per profile and computer, in user_files/<profile>/plans.json (deck ids
belong to one collection, so not in the add-on's config, which every
profile shares); never sent. Follow, share, pause, my days and my pace
live on the server; the board's plans are cached in the session
(api.fetch_board), so a light refresh and an offline morning have them.

plans.json, per profile:
  plans                  {plan id: the plan's state here, below}
  plans_day              the Anki day the morning last ran
  plans_opened           the last open's {day, label, per, units, spread, was, dates}: its undo line (3.8.1: by date)
  plan_offers_dismissed  squad offers waved off (the last 50)
  own_last               at my own pace, the last Open or Put back {pid, uid, name, kind, label, n, day, was}
  built                  filtered decks Due Crew built here (the last 200), for the morning's tidy
  authored_tags          plans I write, not follow: {plan id: {deck_id, tags, tags_sig, tags_day}}
  ids_sent               {plan id: hash of the note ids, counts and refs last sent} (send_ids)
  trees_sent             3.8.1: {deck name, lowercased: {h, day}}, its tree last sent, the day last read (send_trees)
  posts_seen             {plan id: the newest post read}
  aside_ok               {plan id: [leeches, missing]} as last OK'd
  fallback_ok            {plan id: true}: its renamed-tags note OK'd
  due, team_seen, map_snaps, ins_fsrs_hide, ins_hard_hide: due_flow's and team_flow's

plans[plan id], one plan on this computer:
  deck_id, swap          the deck it runs on here, and the tag swap ([theirs, mine]) or None
  applied                {unit id: sig | "skip:" + sig}: dates opened here, or skipped
  src                    {unit id: what it matched when applied}: a change opens only what it adds
  sig2                   1 once applied sigs carry C5's ids (3.7.2)
  seen_version, snapshot the plan as last seen, for the change note
  later                  {unit id: day}: put off (Not today) to that morning
  held                   cards the plan shut when I asked (Hold back, Put back): Stop opens them
  hold_yes               3.8.1: I said yes to Hold back; hold_new holds what authors add later
  catch                  G5's catch-up {until, extra}: Anki's today-only limit each morning
  missed                 3.8.1: the missed-days answer {mode, day} (3.2; was `catch` before)
  own_opened             at my own pace {unit id: the day I opened it, "" when opened elsewhere}
  checks                 checkpoints and review days built {key: {day, at, name, cids}}
  leeches, missing       {unit id: n}, {unit id: [missing, of]}: what a date left shut, when it opened
  tags, tags_sig, tags_day  the plan's own tags on my notes {tag id: path}, its sig, the day read
  tag_news               {day, names, more, missing}: tags that came today, said once
  away                   3.8.1, Welcome back's question {day, days, units, n}: dates from days I studied
                         nothing, kept back (in `later`) till it's answered; asked again each morning

3.8.1, read as today's (_upgrade, _hold_yes): an old `catch` {mode, day}
moves to `missed`; `held` without `hold_yes` was a yes on the plan's dates
and isn't one at my own pace (Put back put its cards there too).

The morning is once per Anki day (`plans_day`): after the day's AnkiWeb
sync, or at the first refresh when this profile doesn't sync; the day's
fresh plans get one more look. It never suspends anything on its own: a
unit removed, a date moved later, a plan stopped all leave open cards
open; only a yes to Hold back holds what authors add to later dates. A
unit the author changes opens only the cards the change adds, and a leech
never opens. Its other steps (tidy, tags, hold, catch-up, checkpoints)
come before what it opens, so the open is Anki's latest step and Not
today can undo it. 3.8.1: a plan whose morning would open dates from 3
or more days on which I studied nothing keeps them back and asks first
(Welcome back: Open them, Push my dates back, Not today).
"""

import copy
import datetime
import hashlib
import html
import json
import os
import re
import traceback

from aqt import mw
from aqt.utils import tooltip

from . import app
from . import plans as P
from . import schedule as S
from .app import _bg, _state, cfg, client, save_cfg

PLAN_KEYS = ("plans", "plans_day", "plans_opened", "plan_offers_dismissed")

_store = {"profile": None, "data": None}


def _files():
    return app._profile_files()


def _pcfg():
    """This profile's plan state (plans.json), loaded once per profile.
    Main thread. The first load after 3.1.1 takes the plans in the old
    shared config whose decks are in this collection."""
    key = app._profile_key()
    if _store["profile"] == key and _store["data"] is not None:
        return _store["data"]
    path = os.path.join(_files(), "plans.json")
    try:
        with open(path) as f:
            data = json.load(f)
        data = data if isinstance(data, dict) else {}
        if _upgrade(data):
            _store.update(profile=key, data=data)
            _psave(data)
    except FileNotFoundError:
        if not mw.col:
            return {}  # nothing to claim with yet; asked again once it's open
        data = _migrate()
        _upgrade(data)
        _store.update(profile=key, data=data)
        _psave(data)
    except Exception:
        data = {}
        _set_aside(path)
    _store.update(profile=key, data=data)
    return data


def _upgrade(data):
    """3.8.1: an older plans.json, read as today's. A plan's `catch` held two
    shapes: G5's catch-up {until, extra} and 3.2's missed-days answer {mode,
    day}; the answer moves to `missed`. (Hold back's yes, `hold_yes`, needs
    the plan, so _hold_yes settles it.) True when something changed."""
    plans = data.get("plans") if isinstance(data.get("plans"), dict) else {}
    changed = False
    for st in plans.values():
        c = st.get("catch") if isinstance(st, dict) else None
        if isinstance(c, dict) and "mode" in c and "until" not in c:
            st["missed"] = {"mode": str(c.get("mode") or ""), "day": str(c.get("day") or "")}
            st.pop("catch")
            changed = True
    return changed


def _set_aside(path):
    """3.8.0: a plans.json that won't read is moved aside, not written
    over: it lists the cards a plan held back, which nothing else does.
    Said once, when it happens."""
    bad = path + ".bad"
    n = 2
    while os.path.exists(bad):
        bad, n = f"{path}.bad{n}", n + 1
    try:
        os.replace(path, bad)
    except OSError:
        return
    tooltip(f"Due Crew couldn't read this profile's plan file, so it's kept as {os.path.basename(bad)}.",
            period=8000)


def _psave(data):
    """Written whole, then swapped in (as wrap.json)."""
    _store.update(profile=app._profile_key(), data=data)
    path = os.path.join(_files(), "plans.json")
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _migrate():
    """Until 3.1.1 plan state lived in the config every profile shares. Each
    profile takes the plans that run on its decks, with the day's morning
    and Undo if it takes any; the rest wait for their own profile. The
    config keys go once nothing is left in them."""
    c = cfg()
    if not any(k in c for k in PLAN_KEYS):
        return {}
    old = c.get("plans") if isinstance(c.get("plans"), dict) else {}
    mine = {pid: st for pid, st in old.items()
            if isinstance(st, dict) and _deck_ok(mw.col, st.get("deck_id"))}
    rest = {pid: st for pid, st in old.items() if pid not in mine}
    data = {"plans": mine,
            "plan_offers_dismissed": list(c.get("plan_offers_dismissed") or [])}
    if mine:
        for k in ("plans_day", "plans_opened"):
            if k in c:
                data[k] = c[k]
    if rest:
        c["plans"] = rest
        if mine:
            c.pop("plans_day", None)
            c.pop("plans_opened", None)
    else:
        for k in PLAN_KEYS:
            c.pop(k, None)
    save_cfg(c)
    return data


def _today():
    from .stats.queries import StatsQueries
    return StatsQueries(mw.col).day_label(0)


def _deck_ok(col, did):
    try:
        d = col.decks.get(int(did), default=False)
    except Exception:
        return False
    return bool(d) and not d.get("dyn")


def _sig(st):
    deck_id, swap = st.get("deck_id"), st.get("swap")
    # 3.7.2: the sig takes C5's ids now. The first pass over a plan applied
    # before carries its dates over as they stand (what opened then stays as
    # it is); from then on, ids that arrive or change open what they add
    legacy = not st.get("sig2")
    st["sig2"] = 1

    def sig(u):
        s = P.unit_sig(u, deck_id, swap)
        if legacy and u.get("ids"):
            have, old = (st.get("applied") or {}).get(u["id"]), P.unit_sig_v1(u, deck_id, swap)
            src = (st.get("src") or {}).get(u["id"])
            if have in (old, "skip:" + old) and not any(isinstance(x, dict) and "ids" in x for x in src or []):
                st["applied"][u["id"]] = ("skip:" if have.startswith("skip:") else "") + s
                if isinstance(src, list):
                    src.append({"ids": list(u["ids"])})
        return s
    return sig


def _swap(st):
    s = st.get("swap")
    return tuple(s) if s else None


def mine(p):
    """G3, G4: a followed plan as I run it: my dates `shift` days later, the
    ones I skip left out (P.my_doc). Marked, so it's never shifted twice;
    `plan_doc` is the plan itself (what the author's changes compare to)."""
    if p.get("_mine"):
        return p
    return dict(p, doc=P.my_doc(p["doc"], int(p.get("shift") or 0), p.get("skipped") or (), p.get("moved")),
                plan_doc=p["doc"], _mine=True)


def _plan_doc(p):
    return p.get("plan_doc") or p["doc"]


def followed():
    """The plans I follow, as the last day's-first refresh brought them, as I run them."""
    return [mine(p) for p in client().session.get("plans") or [] if isinstance(p, dict) and p.get("id")]


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
                nxt = P.next_by_itself(doc, applied, st.get("own_opened"), P.progress(idx, doc, _swap(st)))
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
        out[p["id"]] = P.progress(idx, p["doc"], _swap(st))
    return out


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
        out[p["id"]] = P.load(_index(col, st, idxs), mine(p)["doc"], _swap(st))
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
    if plan.get("paused"):
        sub = f"paused until {P.fmt_day(plan['until'])}" if plan.get("until") else "paused"
    elif week == 0 and us:
        sub = f"starts {P.fmt_day(us[0]['opens'])}"
    else:
        sub = f"week {week} of {weeks}"
    if int(plan.get("shift") or 0):
        sub += f" · your dates +{int(plan['shift'])} day{'s' if int(plan['shift']) != 1 else ''}"
    if int(plan.get("early") or 0) and not plan.get("paused"):
        n = int(plan["early"])  # 3.3, C2 (on the Today box until 3.8.0)
        sub += f" · opens {n} day{'s' if n != 1 else ''} early"
    sub += f" · {int(plan.get('followers') or 0):,} following"
    followers = int(plan.get("followers") or 0)
    crew = plan.get("crewDone") or {}
    rows = []
    open_units = P.opened_by_date(doc, today)
    current = [u for u in open_units if u.get("due") and u["due"] >= today]
    now_id = current[0]["id"] if current else (open_units[-1]["id"] if open_units else None)
    for u in open_units:
        o, s, t = (prog or {}).get(u["id"], [0, 0, 0])
        done = int(crew.get(u["id"]) or 0)
        n = f"crew {done:,}/{followers:,}"
        if u["id"] == now_id and u.get("due") and u["due"] >= today:
            n += f" · due {_short_day(u['due'], today)}"
        rows.append({"name": u.get("name") or "?", "uid": u["id"], "state": "now" if u["id"] == now_id else "open",
                     "seen": [s, t], "crew": [done, followers], "n": n, "missing": not t})
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
    # what today's dates have left, and what's behind (past its day, not seen) and since when
    status = None
    if not (no_deck or plan.get("paused") or own):
        left = lambda u: max(0, int(_t3(prog, u)[2]) - int(_t3(prog, u)[1]))
        late = sorted(str(u["due"]) for u in us if u.get("due") and str(u["due"]) < today and left(u))
        status = {"togo": sum(left(u) for u in us if str(u.get("opens") or "") == today),
                  "behind": sum(left(u) for u in us if u.get("due") and str(u["due"]) < today),
                  "since": P.weekday_or_day(late[0], today) if late else ""}
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
    what = res["names"][0] if len(res["names"]) == 1 else f"{len(res['names'])} dates"
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
        traceback.print_exc()
        return None
    c["plans"] = state
    if res["n"]:
        c["plans_opened"] = {"day": today, "label": res["label"], "per": res["per"], "units": res.get("units") or {},
                             "spread": res.get("spread") or {}, "was": res.get("was") or {},
                             "dates": [d for d in res.get("dates") or [] if d[3]][:OPENED_DATES]}  # 3.8.1
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
            traceback.print_exc()
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
            traceback.print_exc()
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
        traceback.print_exc()
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
            if not here and any(_shut_by_plan(state.get(pid)) or (state.get(pid) or {}).get("tags") for pid in gone):
                return _morning_waits(awaiting_sync, fresh)
            for pid in gone:
                was = state.pop(pid, None) or {}
                held = _shut_by_plan(was)
                if held and mw.col:
                    # taken down elsewhere (the author deleted it, or I stopped
                    # it on the site): what Hold back or Put back shut opens again, as Stop does
                    P.open_cards(mw.col, held, "Due Crew: a plan you followed ended")
                if was.get("tags"):
                    _drop_plan_tags(was, "a plan you followed")  # 3.8.0: and its tags come off
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
            from . import ahead_flow
            if ahead_flow.apply_morning():  # 3.9.2: Stop new cards, after a catch-up's own limit
                _after_change()
        except Exception:
            traceback.print_exc()
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
        traceback.print_exc()
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
        traceback.print_exc()
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
            nxt = P.next_by_itself(q["doc"], st.get("applied"), st.get("own_opened"), P.progress(idx, q["doc"], _swap(st)))
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
        from . import sheets
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
        text = (f"{name} is new on this computer. Hold back {cards} of its later dates until you open them?"
                "\n\nOne undo step; stopping the plan opens them again.")
    else:
        text = (f"{name} is new on this computer. Hold back {cards} of its later dates until their day?"
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
        traceback.print_exc()
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
        traceback.print_exc()
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


def note_tree(deck, tags, decks):
    """Make a plan from a deck just sent this deck's tree: noted as sent
    today, so the next refresh doesn't send it again."""
    try:
        pc = _pcfg()
        pc.setdefault("trees_sent", {})[str(deck).lower()] = {"h": P.tree_hash(deck, tags, decks), "day": _today()}
        _psave(pc)
    except Exception:
        traceback.print_exc()


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
    those (study_quiz). A search run here; nothing is sent."""
    got = _plan_idx(pid)
    if not got:
        return
    _p, st, doc, idx = got
    u = next((x for x in P.units(doc) if x["id"] == uid), None)
    if not u:
        return
    cids = P.new_and_due(idx, idx.match(u, _swap(st), doc))
    if not cids:
        tooltip("Nothing new or due in it.")
        return
    name = _deck_name(u.get('name') or 'date')
    if _filtered(mw.col, name, cids, order=NEW_ORDER):
        _after_change()
        did = mw.col.decks.id_for_name(name)
        if did:
            mw.col.decks.select(did)
            mw.moveToState("overview")


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


def _filtered(col, name, cids, order=4, until=None):
    """Anki's own filtered deck over these cards, most lapses first (order 4;
    6, as they come in the deck, for new cards; 1, random, a date's Study);
    built (or rebuilt) under `name`. 3.9.5: until, the last day it's for (a
    quiz's, an exam's): the morning after, it's emptied (tidy_decks).
    Returns True when it took."""
    try:
        did = col.decks.id_for_name(name) or 0
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
        col.sched.add_or_update_filtered_deck(deck)
        _note_built(col.decks.id_for_name(name), until)
        parent = col.decks.id_for_name(P.PARENT)
        if parent and (not had or int(parent) in (_pcfg().get("built") or [])):
            _note_built(parent)  # made with it (or before, by us), so the tidy may clear it
        return True
    except Exception:
        traceback.print_exc()
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
    they go with the rest."""
    try:
        normal = {int(d.id) for d in col.decks.all_names_and_ids(include_filtered=False)}
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
        gone = P.tidy(rows, built, parent)
        keep = [x for x in built if (x in {r[0] for r in rows} or (parent and x == parent[0])) and x not in gone]
        if keep != built:
            c["built"] = keep
            _psave(c)
        if gone:
            col.decks.remove(gone)
        return len(gone)
    except Exception:
        traceback.print_exc()
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
        traceback.print_exc()
        return {}
    _state["plan_progress"] = prog
    whole = True  # kept for the next ask only when every part was read
    try:
        _state["plan_load"] = loads(mw.col, followed(), _state_cfg(), idxs)  # 3.7.81
    except Exception:
        whole = False
        traceback.print_exc()
    try:
        _state["plan_picks"] = pick_names(mw.col, followed(), _state_cfg(), idxs)  # 3.8.1
        if prog:
            _note_reviews(mw.col, _today())  # 3.8.1: my own load, beside what the plan opens
    except Exception:
        whole = False
        traceback.print_exc()
    try:
        _state["plan_session"] = sessions(mw.col, followed(), _state_cfg(), _today(), idxs)
        _note_recap(_state["plan_session"])
    except Exception:
        whole = False
        traceback.print_exc()
    try:
        from . import due_flow
        due_flow.parts(mw.col, idxs, _state["labels"][0] if _state["labels"] else _today())  # Due: each date's resources
    except Exception:
        whole = False
        traceback.print_exc()
    # a search about my own reviews (is:due, rated:…) is read at every refresh, as before
    if whole and key is not None and not any(idx._fresh for idx in idxs.values()):
        _last.update(key=key, got={k: dict(v) if isinstance(v, dict) else v for k, v in _state.items() if k in _WRITES})
    return prog


def _due_in(col, did):
    """Reviews (and learning cards) due now in a deck and its subdecks, when
    this Anki can say. 3.9.1: its node in the deck tree Due reads too, as
    Anki's deck_due_tree(did) finds it, not a whole tree of its own each time."""
    try:
        from . import due_flow
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
        traceback.print_exc()
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
    from .stats.queries import StatsQueries
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
    return {"n": n, "sync": _unsynced()} if n else None


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
        traceback.print_exc()
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
    # 3.9.5: following and owning none, the starters the day's first board brought
    starters = list(client().session.get("plan_starters") or [])
    if not today:
        return {"cards": [], "offers": [], "invites": list(client().session.get("plan_invites") or []), "starters": starters}
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
    from . import team_flow
    for card in cards:
        try:
            card["tabs"] = team_flow.card_bits(card["id"])  # the squad line
        except Exception:
            traceback.print_exc()
    from .squads import _my_squads
    names = {sq["id"]: sq.get("name") or "" for sq in _my_squads(c)}
    offers = offers_view(client().session.get("plan_offers"), names, {p["id"] for p in plan_list},
                         set(pc.get("plan_offers_dismissed") or []))
    # 3.8.1: an invite to co-write a plan, or to keep one, from the day's first board; and
    # the morning's dates, for its line here when Due is off (__init__ hands over morning_opened())
    return {"cards": cards, "offers": offers, "invites": list(client().session.get("plan_invites") or []),
            "opened_dates": opened_dates(), "starters": starters}


# ---- board commands ----

def on_message(cmd, parts):
    """duecrew:plan* from the board. True when handled."""
    if cmd.startswith("planteam"):
        from . import team_flow  # 3.7.3: the plan's squad
        return team_flow.on_message(cmd, parts)
    arg = parts[2] if len(parts) > 2 else ""
    if cmd == "planundo":
        undo_morning()
    elif cmd == "plannottoday":
        undo_morning(put_off_too=True)
    elif cmd == "plansync":
        try:
            mw.on_sync_button_clicked()  # Anki's own Sync, as its top bar's button
        except Exception:
            traceback.print_exc()
    elif cmd == "plannow" and arg and len(parts) > 3:
        open_date(arg, parts[3])
    elif cmd == "planbrowse" and arg and len(parts) > 3:
        browse_date(arg, parts[3])
    elif cmd == "planleft" and arg:
        browse_left(arg, [x for x in (parts[3] if len(parts) > 3 else "").split("-") if x])
    elif cmd == "plantopic" and arg and len(parts) > 4:
        browse_topic(arg, [x for x in parts[3].split("-") if x], int(parts[4]) if parts[4].isdigit() else -1)
    elif cmd == "plantopicstudy" and arg and len(parts) > 4:  # 3.9.5: a topic on Today, as a deck of its own
        study_topic(arg, [x for x in parts[3].split("-") if x], int(parts[4]) if parts[4].isdigit() else -1)
    elif cmd == "planputback" and arg:
        open_put_off(arg)
    elif cmd == "planmove" and arg and len(parts) > 3:
        move_menu(arg, parts[3])
    elif cmd == "planmoveback" and arg and len(parts) > 3:
        move_date(arg, parts[3], 0)
    elif cmd == "planreset" and arg:
        reset_days(arg)
    elif cmd == "planskip" and arg and len(parts) > 3:
        set_skip(arg, parts[3], True)
    elif cmd == "planunskip" and arg and len(parts) > 3:
        set_skip(arg, parts[3], False)
    elif cmd == "plancatch" and arg:
        catch_menu(arg)
    elif cmd == "plancatchstop" and arg:
        stop_catch(arg)
    elif cmd == "planweek" and arg and len(parts) > 3:
        # 3.5.0: the Plans tab's week, back and on (0: this week again); not saved
        weeks = _state.setdefault("plan_week", {})
        _state.pop("plan_focus", None)  # moving on lets go of a jumped-to day
        step = parts[3]
        weeks[arg] = 0 if step == "0" else max(-26, min(26, int(weeks.get(arg, 0)) + (1 if step == "next" else -1)))
        app.swap(cfg())
    elif cmd == "planpick" and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", arg or ""):
        # round five, pick 3: the plan You › Plans shows, with two or more (this computer's)
        c = cfg()
        c["plan_pick"] = arg
        _state.pop("plan_focus", None)  # another plan lets go of a jumped-to day
        save_cfg(c)
        app.swap(c)
    elif cmd == "planshift" and arg:
        set_shift(arg)
    elif cmd == "plansite" and arg and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", arg):
        open_site(f"/plans/{arg}")  # an id, nothing else: the link carries a sign-in token
    elif cmd == "planlibrary":
        open_site("/library")
    elif cmd == "planstarter" and re.fullmatch(r"[a-z0-9]{1,32}", arg or ""):
        _planner_flow().use_starter(arg)  # 3.9.5: Use it, on a starter in the empty Plans tab
    elif cmd == "planmake":
        _planner_flow().open_new()  # round five: one New plan
    elif cmd == "planyours":  # 3.9.3: Your plans, on a plan when the click names one
        open_yours(arg if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", arg or "") else None)
    elif cmd == "plannew":  # 3.9.3: You › Plans' New plan ▾
        new_plan_menu()
    elif cmd == "planstart":  # 3.9.3: New plan from a calendar (round five: the one New plan)
        _planner_flow().open_new()
    elif cmd == "planmissed":  # 3.9.3: QBank QIDs, from Due's head or on Insights' deck
        _planner_flow().open_qids(int(arg) if arg.isdigit() else None)
    elif cmd == "planresume" and arg:
        p = next((x for x in followed() if x["id"] == arg), None)
        if p:
            back(arg) if p.get("since") else set_paused(arg, False)
    elif cmd == "planmenu" and arg:
        plan_menu(arg)
    elif cmd == "planpaceopen" and arg:  # 3.8.0, at my own pace: Open, Open and study, Undo, Put back
        if len(parts) > 3 and parts[3]:
            open_next(arg, uid=parts[3])  # 3.8.1: a date after "Then", opened ahead of the rest
        else:
            open_next(arg)
    elif cmd == "planopened" and arg and len(parts) > 3:  # 3.8.1: a date on the morning's line
        browse_opened(arg, parts[3])
    elif cmd == "planleech" and arg and len(parts) > 3:  # 3.8.1: a date's leeches, which stay shut
        browse_leeches(arg, parts[3])
    elif cmd == "planpacestudy" and arg:
        open_next(arg, study=True)
    elif cmd == "planpaceundo" and arg:
        own_undo(arg)
    elif cmd == "planpaceback" and arg:
        put_back_own(arg)
    elif cmd == "plantags" and arg:  # 3.8.0: the plan's tags, in Browse
        browse_tags(arg)
    elif cmd == "plantagsok" and arg:
        tags_seen(arg)
    elif cmd == "planok" and arg:
        seen_change(arg)
    elif cmd == "planupdopen" and arg:   # 3.7.3: an update's Open
        update_open(arg)
    elif cmd == "planupdlater" and arg:  # 3.7.3: an update's Not today
        update_later(arg)
    elif cmd == "planpostok" and arg:    # 3.7.3: the authors' post, read
        post_seen(arg)
    elif cmd == "plandeck" and arg:
        change_deck(arg)
    elif cmd == "planlook" and arg:
        offer = next((o for o in client().session.get("plan_offers") or [] if o.get("id") == arg), None)
        if offer:
            open_follow(code=offer.get("code") or "")
    elif cmd == "planstudy" and arg:
        study(arg)
    elif cmd == "plansched" and arg:
        open_schedule(arg)
    elif cmd == "planlimit" and arg:
        raise_limit(arg)
    elif cmd == "planstudydate" and arg and len(parts) > 3:
        study_date(arg, parts[3])
    elif cmd == "planquiz" and arg and len(parts) > 3:  # 3.8.1: Study for a quiz
        study_quiz(arg, parts[3])
    elif cmd == "planasideok" and arg:
        st = _state_cfg().get(arg)
        p = next((x for x in followed() if x.get("id") == arg), None)
        if st and p:
            pc = _pcfg()
            pc.setdefault("aside_ok", {})[arg] = aside(p, st)[:2]
            _psave(pc)
            app.swap(cfg())
    elif cmd == "planidsok" and arg:
        pc = _pcfg()
        pc.setdefault("fallback_ok", {})[arg] = True
        _psave(pc)
        app.swap(cfg())
    elif cmd == "planspread" and arg:
        set_catch(arg, "spread")
    elif cmd == "planleave" and arg:
        set_catch(arg, "leave")
    elif cmd == "planpush" and arg:
        push_back(arg)
    elif cmd == "planofferx" and arg:
        pc = _pcfg()
        pc["plan_offers_dismissed"] = (list(pc.get("plan_offers_dismissed") or []) + [arg])[-50:]
        _psave(pc)
        app.swap(cfg())
    elif cmd == "planinvite" and arg and len(parts) > 3 and parts[3] in ("yes", "no"):
        answer_invite(arg, parts[3] == "yes")  # 3.8.1: co-write it, or keep it
    else:
        return False
    return True


def answer_invite(pid, yes):
    """3.8.1: Yes or No to an invite on the board (to co-write a plan, or to
    keep one its owner hands me): one request, on the click. A yes makes me
    one of its authors: Browse's items at once, its tags on my notes when the
    plan next arrives (the refresh's stamp moved with the answer)."""
    cl = client()
    inv = next((x for x in cl.session.get("plan_invites") or [] if x.get("id") == pid), None)
    if inv is None or not cl.signed_in:
        return
    gen = app.generation

    def done(res):
        if gen != app.generation:
            return  # another profile or account since
        _got, status = res if res else (None, 0)
        name = html.escape(inv.get("name") or "the plan")
        if status == 404:
            tooltip(f"That invite to {name} was taken back.")
        elif status != 200:
            tooltip("Couldn't reach Due Crew. Check your connection." if not status else "That didn't go through. Try again later.")
        elif yes:
            tooltip(f"{name} is yours now." if inv.get("kind") == "owner" else f"You co-write {name} now.")
        app.swap(cfg())

    _bg(lambda: cl.answer_plan_invite(pid, yes), done)


def undo_morning(put_off_too=False):
    """The board's Undo: Anki's own undo, only while the step is its latest.
    The card and the numbers follow once the undo has happened, and only
    if it did. G2, Not today (put_off_too): the dates it opened open again
    on tomorrow's morning."""
    opened = _pcfg().get("plans_opened") or {}
    if not _undo_ok(opened.get("label")):
        tooltip("Anki has done something since. Use Edit › Undo.")
        app.swap(cfg())
        return

    def done(_out=None):
        # Undo: the units stay marked as applied, the next morning won't open them again;
        # Not today: they open on tomorrow's. A date opened in slices (an even
        # date, a 3.2 schedule) has no "won't open again": its next morning
        # opens what its schedule says is due, so plain Undo leaves it to that
        # (3.7.2; before, a window's last day stayed applied and its cards shut)
        pc = _pcfg()
        state = _state_cfg(pc)
        if put_off_too:
            for pid, uids in (opened.get("units") or {}).items():
                if pid in state:
                    # 3.8.1: at my own pace, each date back as it was (`was`)
                    put_off(state[pid], uids, _today(), was=(opened.get("was") or {}).get(pid))
        else:
            for pid, uids in (opened.get("spread") or {}).items():
                for uid in uids if pid in state else ():
                    (state[pid].get("applied") or {}).pop(uid, None)
                    (state[pid].get("src") or {}).pop(uid, None)
        pc["plans"] = state
        pc["plans_opened"] = {}
        _psave(pc)
        try:
            mw.update_undo_actions()
        except Exception:
            pass
        refresh_progress()
        app.swap(cfg())

    try:
        from aqt.operations import CollectionOp
    except ImportError:
        CollectionOp = None
    if CollectionOp is not None:
        CollectionOp(mw, lambda col: col.undo()).success(done).run_in_background()
        return
    try:
        mw.undo()  # an Anki without CollectionOp: undo runs here, now
    except Exception:
        traceback.print_exc()
        return
    done()


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
        traceback.print_exc()
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
        left = idx.unseen(cids)
        if not uids:
            left = {c for c in left if idx.cards[c][0] != -1}  # behind: opened, so waiting in my Anki now
    except Exception:
        traceback.print_exc()
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
        traceback.print_exc()
        return
    _browse(cids, _tag_search(mw.col, st["deck_id"], src, _swap(st), cids) if cids else None)


def study_topic(pid, uids, i):
    """3.9.5 (Sam: "if one clicks on a tagged section on a plan (like a video
    tags) then it moves them into a filtered deck?"): a topic of a date on
    Today, as a deck named for it: its cards I haven't seen and the
    ones due today (P.new_and_due; never reviews ahead of their date), in
    the deck's order. A card another Due Crew deck holds comes out of it
    first (Anki keeps a card in one filtered deck), and that deck is built
    again after. Nothing new or due: Browse, as before. A search run here;
    nothing is sent."""
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
        traceback.print_exc()
        return
    if not cids:
        browse_topic(pid, uids, i)
        return
    name = _deck_name(title)
    back = _free(mw.col, cids, name)
    ok = _filtered(mw.col, name, cids, order=NEW_ORDER)
    for did in back:
        try:
            mw.col.sched.rebuild_filtered_deck(did)
        except Exception:
            traceback.print_exc()
    _after_change()
    did = mw.col.decks.id_for_name(name) if ok else None
    if did:
        mw.col.decks.select(did)
        mw.moveToState("overview")


def _free(col, cids, name):
    """The Due Crew decks (but `name`'s own) holding any of these cards,
    emptied so the cards can move; their ids, to build again after."""
    own = col.decks.id_for_name(name)
    ids = ",".join(str(int(c)) for c in cids) or "0"
    out = []
    for did in col.db.list(f"SELECT DISTINCT did FROM cards WHERE odid != 0 AND id IN ({ids})"):
        if int(did) != (int(own) if own else 0) and str(col.decks.name(int(did)) or "").startswith(P.PARENT + "::"):
            col.sched.empty_filtered_deck(int(did))
            out.append(int(did))
    return out


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
        traceback.print_exc()
        return
    c["plans"] = state
    _psave(c)
    if res["n"]:
        _after_change()
        tooltip(opened_line(res), period=5000)
    else:
        tooltip(f"Nothing new to open in {html.escape(res['names'][0] if res['names'] else 'that date')}.")
    refresh_progress()
    app.swap(cfg())


def open_put_off(pid):
    """G2: what Not today put off, now after all."""
    st = _state_cfg().get(pid) or {}
    for uid in list((st.get("later") or {}).keys()):
        open_date(pid, uid)


# ---- 3.8.0: at my own pace ----

def _own_ctx(pid):
    p = next((x for x in followed() if x["id"] == pid), None)
    c = _pcfg()
    state = _state_cfg(c)
    st = state.get(pid)
    if p is None or not st or not mw.col or not _deck_ok(mw.col, st.get("deck_id")):
        return None
    return p, c, state, st


def _note_last(c, pid, u, kind, label, n, was):
    """What the plan card's line says (and its Undo undoes) while it's Anki's latest step."""
    c["own_last"] = {"pid": pid, "uid": u["id"], "name": str(u.get("name") or "?"), "kind": kind,
                     "label": label, "n": int(n), "day": _today(), "was": was}


def _was(st, uid):
    return {k: (st.get(k) or {}).get(uid) for k in ("applied", "src", "own_opened")}


def open_next(pid, study=False, uid=None):
    """You › Plans, Open: the next date at my own pace opens now, first in
    Anki's line of new cards, as one undo step. Open and study: then a Due
    Crew deck of its new cards, and into it. uid (3.8.1): that date
    instead (the week's Open now)."""
    got = _own_ctx(pid)
    if not got:
        return
    p, c, state, st = got
    today = _today()
    prog = (_state.get("plan_progress") or {}).get(pid) or {}
    left = ([x for x in P.units(p["doc"]) if x["id"] == uid] if uid
            else P.up_next(p["doc"], st.get("applied"), prog))
    if not left:
        if not uid:
            tooltip("Every date of this plan is open.")
        return
    u = left[0]
    # 3.8.1: a date further down Up next, opened first: the line says ahead of which
    nxt = [x["id"] for x in P.up_next(p["doc"], st.get("applied"), prog)] if uid else []
    ahead = next((x for x in P.units(p["doc"]) if x["id"] == nxt[0]), None) if u["id"] in nxt[1:] else None
    was = _was(st, u["id"])
    (st.get("applied") or {}).pop(u["id"], None)  # shut again since (Undo): it opens whole
    (st.get("src") or {}).pop(u["id"], None)
    try:
        res = open_one(mw.col, p, st, u["id"], today, first=True)
    except Exception:
        traceback.print_exc()
        return
    st.setdefault("own_opened", {})[u["id"]] = today
    c["plans"] = state
    if res["n"]:
        _note_last(c, pid, u, "open", res["label"], res["n"], was)
        if ahead:
            c["own_last"]["ahead"] = str(ahead.get("name") or "?")
    _psave(c)
    if res["n"]:
        _after_change()
    else:
        tooltip(f"Nothing in {html.escape(str(u.get('name') or 'it'))} to open: it's open already.")
    refresh_progress()
    if study:
        idx = P.DeckIndex(mw.col, st["deck_id"])
        new = [c2 for c2 in idx.match(u, _swap(st), p["doc"]) if idx.cards[c2] == (0, 0)]
        name = _deck_name(u.get("name") or "date")
        if new and _filtered(mw.col, name, new, order=NEW_ORDER):
            _after_change()
            did = mw.col.decks.id_for_name(name)
            if did:
                mw.col.decks.select(did)
                mw.moveToState("overview")
                return
    app.swap(cfg())


def put_back_own(pid):
    """At my own pace, Put back: the last date I opened shuts again, only its
    cards I haven't seen (never a seen one, nor one another opened date
    has), as one undo step; it's Up next again. Stopping the plan opens them.
    3.8.1: they join `held` (what Stop opens), but Put back isn't a yes to
    Hold back: that's `hold_yes` now (before, any held card counted as one,
    and every later date's new cards were held each morning from then on)."""
    got = _own_ctx(pid)
    if not got:
        return
    p, c, state, st = got
    doc, applied = p["doc"], st.get("applied") or {}
    u = P.own_last(doc, st.get("own_opened"))
    if not u or not P.opened_here(applied, u):
        return
    idx = P.DeckIndex(mw.col, st["deck_id"])
    deck = doc
    others = set()
    for x in P.units(doc):
        if x["id"] != u["id"] and P.opened_here(applied, x):
            others |= idx.match(x, _swap(st), deck)
    cids = {c2 for c2 in idx.match(u, _swap(st), deck) - others if idx.cards[c2] == (0, 0)}
    label = f"Due Crew: put back {u.get('name') or 'a date'}"
    was = _was(st, u["id"])
    n = P.hold_cards(mw.col, cids, label) if cids else 0
    for k in ("applied", "src", "own_opened"):
        (st.get(k) or {}).pop(u["id"], None)
    st["hold_yes"] = _hold_yes(p, st)  # settled before Put back adds to `held`, which isn't a yes
    if n:
        st["held"] = sorted(set(st.get("held") or []) | {int(x) for x in cids})
        _note_last(c, pid, u, "back", label, n, was)
    c["plans"] = state
    _psave(c)
    if n:
        _after_change()
    refresh_progress()
    app.swap(cfg())


def own_undo(pid):
    """The line's Undo after Open or Put back: Anki's own undo while it's its
    latest step, then the date is as it was."""
    last = _pcfg().get("own_last") or {}
    if last.get("pid") != pid or not _undo_ok(last.get("label")):
        tooltip("Anki has done something since. Use Edit › Undo.")
        app.swap(cfg())
        return

    def done(_out=None):
        pc = _pcfg()
        state = _state_cfg(pc)
        st = state.get(pid)
        if st is not None:
            for k, v in (last.get("was") or {}).items():
                if v is None:
                    (st.get(k) or {}).pop(last["uid"], None)
                else:
                    st.setdefault(k, {})[last["uid"]] = v
        pc["plans"] = state
        pc["own_last"] = {}
        _psave(pc)
        try:
            mw.update_undo_actions()
        except Exception:
            pass
        refresh_progress()
        app.swap(cfg())

    try:
        from aqt.operations import CollectionOp
    except ImportError:
        CollectionOp = None
    if CollectionOp is not None:
        CollectionOp(mw, lambda col: col.undo()).success(done).run_in_background()
        return
    try:
        mw.undo()
    except Exception:
        traceback.print_exc()
        return
    done()


def set_own(pid, own):
    """The plan's menu, How its cards open: mine, on the server (every
    computer and the site agree). Back on the plan's dates, what's opened by
    date since asks, as resuming does; at my own pace, a deck whose later
    cards are open is offered Hold back."""
    p = next((x for x in followed() if x["id"] == pid), None)
    if p is None or (p.get("own") or "") == (own or ""):
        return
    was, cl = p.get("own") or "", client()

    def done(res):
        if res is None:
            tooltip("Couldn't reach Due Crew. Check your connection.")
            return
        if was and not own:
            _resume(pid)
        elif own and not was:
            offer_hold([pid], words=lambda name, n, _own: (
                "Hold back the rest",
                f"{name}: {n:,} card{'s' if n != 1 else ''} of dates you haven't opened are open already. "
                "Hold them back until you open their date?\n\nOne undo step; stopping the plan opens them again.",
                "Hold back"))
            tooltip("Nothing opens by itself now. Open the next date from You › Plans.", period=5000)
        app.swap(cfg())

    _bg(lambda: cl.set_own(pid, own or None), done)


def own_view(plan, st, prog, today):
    """card_view's part at my own pace: Up next, then, where the plan's dates
    are, my pace (and the exam), the last step with its Undo, Put back."""
    doc, real = plan["doc"], _plan_doc(plan)
    st = st or {}
    applied, days, prog = st.get("applied") or {}, st.get("own_opened") or {}, prog or {}
    left = P.up_next(doc, applied, prog)

    def to_open(u):
        o, _s, t = (prog.get(u["id"]) or [0, 0, 0])[:3]
        return max(0, int(t) - int(o))
    recent = P.recent_opens(days, today)
    last = None
    ol = (_pcfg().get("own_last") or {}) if mw else {}
    if ol.get("pid") == plan["id"] and ol.get("day") == today and mw and mw.col and _undo_ok(ol.get("label")):
        n = int(ol.get("n") or 0)
        ahead = f" (ahead of {ol['ahead']})" if ol.get("ahead") else ""  # 3.8.1: a later date, opened first
        last = (f"Opened {ol.get('name') or '?'}{ahead} · {n:,} card{'s' if n != 1 else ''}, first in line."
                if ol.get("kind") == "open" else f"Put back {ol.get('name') or '?'} · {n:,} card{'s' if n != 1 else ''}.")
    back = None
    lu = P.own_last(doc, days)
    if lu and not last and P.opened_here(applied, lu, prog):
        o, s2, _t = (prog.get(lu["id"]) or [0, 0, 0])[:3]
        if int(o) > int(s2):
            back = {"name": str(lu.get("name") or "?"), "n": int(o) - int(s2)}
    return {"mode": plan.get("own"),
            "next": {"uid": left[0]["id"], "name": str(left[0].get("name") or "?"), "n": to_open(left[0])} if left else None,
            "then": [f"{u.get('name') or '?'} · {to_open(u):,}" for u in left[1:4]], "more": max(0, len(left) - 4),
            # 3.8.1: each a link, Open on that date (open_next(pid, uid))
            "then_items": [{"uid": u["id"], "name": str(u.get("name") or "?"), "n": to_open(u)} for u in left[1:4]],
            "at": P.plan_at(real, today),
            "pace": f"You opened {recent} date{'s' if recent != 1 else ''} in the last two weeks." if recent else None,
            "finish": P.finish_check(real, len(left), recent, today), "last": last, "back": back}


def set_skip(pid, uid, on):
    """G3: skip a date (it never opens for me), or take the skip back
    (if its day has come, it opens now)."""
    p = _raw(pid)
    if p is None:
        return
    skipped = [u for u in p.get("skipped") or [] if u != uid] + ([uid] if on else [])
    cl = client()

    def done(got):
        if got is None:
            tooltip("Couldn't reach Due Crew. Check your connection.")
            return
        if not on and not got.get("paused"):
            _open_now([x for x in followed() if x["id"] == pid])
        app.swap(cfg())

    _bg(lambda: cl.set_days(pid, skipped=skipped), done)


def move_menu(pid, uid):
    """3.7.6: move one date later on my copy: the next seven days after it.
    A day on or after the event it preps for says so."""
    p = next((x for x in followed() if x["id"] == pid), None)
    u = next((x for x in P.units((p or {}).get("doc")) if x["id"] == uid), None)
    if p is None or u is None or not u.get("opens"):
        return
    raw = _raw(pid) or {}
    have = int((raw.get("moved") or {}).get(uid) or 0)
    ev = P.event_of(p["doc"], u)  # 3.8.1: by the event's id (its name never matched)
    from aqt.qt import QCursor, QMenu
    menu = QMenu(mw)
    head = menu.addAction(f"Move {u.get('name') or 'this date'} to")
    head.setEnabled(False)
    for k in range(1, 8):
        day = P._later(u["opens"], k)
        late = ev and str(ev.get("day") or "9999") <= day
        a = menu.addAction(f"{P.fmt_day(day)}" + (f" · after {ev.get('name')}" if late else ""))
        a.triggered.connect(lambda _=False, n=have + k: move_date(pid, uid, n))
    menu.exec(QCursor.pos())


def move_date(pid, uid, days):
    """Set how many days later this date runs for me (0: back on its day).
    Cards already open stay open; a date whose day has come opens."""
    raw = _raw(pid)
    if raw is None or not 0 <= int(days) <= 365:
        return
    moved = {k: int(v) for k, v in (raw.get("moved") or {}).items() if k != uid}
    if days:
        moved[uid] = int(days)
    cl = client()

    def done(got):
        if got is None:
            tooltip("Couldn't reach Due Crew. Check your connection.")
            return
        if not got.get("paused"):
            _open_now([x for x in followed() if x["id"] == pid], toast=False)
        u = next((x for x in P.units(raw.get("doc")) if x["id"] == uid), None)
        if u is not None and days:
            p = next((x for x in followed() if x["id"] == pid), None)
            mu = next((x for x in P.units((p or {}).get("doc")) if x["id"] == uid), None)
            if mu:
                tooltip(f"{html.escape(str(u.get('name') or 'It'))} moved to {P.fmt_day(mu['opens'])}.")
        app.swap(cfg())

    _bg(lambda: cl.set_days(pid, moved=moved), done)


def reset_lines(p):
    """3.7.6: what Reset to default puts back, as lines; [] when nothing."""
    out = []
    shift = int(p.get("shift") or 0)
    if shift:
        out.append(f"Your dates run {shift} day{'s' if shift != 1 else ''} later: back on time")
    names = {u["id"]: str(u.get("name") or "?") for u in P.units(p.get("doc"))}
    sk = [names.get(u, "?") for u in p.get("skipped") or [] if u in names]
    if sk:
        out.append(f"{len(sk)} skipped date{'s come' if len(sk) != 1 else ' comes'} back: " + ", ".join(sk[:3])
                   + (f" and {len(sk) - 3} more" if len(sk) > 3 else ""))
    mv = [names.get(u, "?") for u in (p.get("moved") or {}) if u in names]
    if mv:
        out.append(f"{len(mv)} moved date{'s go' if len(mv) != 1 else ' goes'} back: " + ", ".join(mv[:3])
                   + (f" and {len(mv) - 3} more" if len(mv) > 3 else ""))
    if p.get("paused") or p.get("until") or p.get("since"):
        out.append("Your pause ends")
    return out


def reset_days(pid):
    """3.7.6, Plan ▾ › Reset to default: my shift, skips, moved dates and
    pause back to the plan's, after saying exactly what. Cards already
    open stay open; dates that come back and have passed count as behind."""
    raw = _raw(pid)
    if raw is None:
        return
    lines = reset_lines(raw)
    if not lines:
        return
    from . import sheets
    sheets.confirm("Reset to default?", "\n".join("\u2022 " + x for x in lines)
                   + "\n\nCards already open stay open. Dates that come back and have passed count as behind.",
                   "Reset", lambda: _reset_days(pid))


def _reset_days(pid):
    cl = client()

    def done(got):
        if got is None:
            tooltip("Couldn't reach Due Crew. Check your connection.")
            return
        _open_now([x for x in followed() if x["id"] == pid], toast=False)
        tooltip("Back to the plan's days.")
        app.swap(cfg())

    _bg(lambda: cl.set_days(pid, shift=0, skipped=[], moved={}, paused=False, until=None, since=None), done)


def pause_until(pid):
    """G4: pause until a day; my Away dates fill it in when they cover it."""
    p = _raw(pid)
    if p is None:
        return
    today = _today()
    c = cfg()
    away_to = str(c.get("away_to") or "")
    from_away = away_to >= today and str(c.get("away_from") or "") <= away_to
    until = away_to if from_away else S.iso(S.d(today) + datetime.timedelta(days=7))
    from .ui.days_dialog import ask_pause
    got = ask_pause(mw, p.get("name") or "Plan", today, until, from_away)
    if not got:
        return
    cl = client()

    def done(res):
        if res is None:
            tooltip("Couldn't reach Due Crew. Check your connection.")
            return
        app.swap(cfg())

    _bg(lambda: cl.set_days(pid, paused=True, since=today, until=got), done)


def back(pid):
    """G4: back from a pause. Move my dates later by the days I was away,
    or open what opened meanwhile; either way, not paused any more."""
    p = _raw(pid)
    if p is None or not mw.col:
        return
    today = _today()
    st = _state_cfg().get(pid)
    # 3.8.1: at my own pace nothing opened by date while I was away: back without asking
    n_units, _n_cards = waiting(mw.col, mine(p), st, today) if st and not P.own_pace(p) else (0, 0)
    since = p.get("since") or today
    days = max(0, (S.d(today) - S.d(since)).days)
    choice = "open"
    if n_units and days:
        ev = P.prep_for(mine(p)["doc"], today)
        from .ui.days_dialog import ask_back
        choice = ask_back(mw, n_units, days, (ev["name"], P.fmt_day(ev["day"])) if ev else None)
    shift = int(p.get("shift") or 0) + (days if choice == "push" else 0)
    cl = client()

    def done(res):
        if res is None:
            tooltip("Couldn't reach Due Crew. Check your connection.")
            return
        _open_now([x for x in followed() if x["id"] == pid])
        app.swap(cfg())

    _bg(lambda: cl.set_days(pid, paused=False, since=None, until=None, shift=min(365, shift)), done)


def set_shift(pid):
    """G7: Push my dates back…: how many days my dates run after the plan's."""
    p = _raw(pid)
    if p is None:
        return
    from .ui.days_dialog import ask_shift
    n = ask_shift(mw, p.get("name") or "Plan", int(p.get("shift") or 0))
    if n is None or n == int(p.get("shift") or 0):
        return
    cl = client()

    def done(res):
        if res is None:
            tooltip("Couldn't reach Due Crew. Check your connection.")
            return
        if not res.get("paused"):
            _open_now([x for x in followed() if x["id"] == pid])  # fewer days may make a date due now
        app.swap(cfg())

    _bg(lambda: cl.set_days(pid, shift=n), done)


def _paused(col, did):
    """3.9.2's audit: the deck whose Stop new cards (Insights) runs today over
    this one, or None. Raise and Catch up stand aside for it: they'd undo it
    till the next morning set it again."""
    try:
        from . import ahead_flow
        got = ahead_flow.paused(col, did)
    except Exception:
        traceback.print_exc()
        return None
    return got[0] if got else None


def _base_limit(col, did):
    """This deck's own new cards a day, not counting a today-only one."""
    try:
        deck = col.decks.get(int(did))
        if deck.get("newLimit") is not None:
            return int(deck["newLimit"])
        return int(col.decks.config_dict_for_deck_id(int(did))["new"]["perDay"])
    except Exception:
        return None


def apply_catch():
    """G5, each morning while a catch-up runs: Anki's today-only limit on the
    plan's deck, the deck's own plus the extra. It ends by itself at
    midnight, so there's nothing to put back afterwards."""
    if not mw.col:
        return
    col, today = mw.col, _today()
    for pid, st in _state_cfg().items():
        c = st.get("catch") or {}
        if not c or str(c.get("until") or "") < today or not _deck_ok(col, st.get("deck_id")):
            continue
        if _paused(col, st["deck_id"]):
            continue  # Stop new runs on it today
        base = _base_limit(col, st["deck_id"])
        if base is None:
            continue
        try:
            deck = col.decks.get(int(st["deck_id"]))
            want = {"limit": base + int(c.get("extra") or 0), "today": int(col.sched.today)}
            if deck.get("newLimitToday") == want:
                continue  # already so: no save, no undo step of its own (3.9.2's QoL pass)
            deck["newLimitToday"] = want
            col.decks.save(deck)
        except Exception:
            traceback.print_exc()


def catch_menu(pid):
    """G5: catch up over 3, 5 or 7 days; 3.8.0: or push my dates back, the
    other way to be on time again (Plan ▾ has it too)."""
    prog = (_state.get("plan_progress") or {}).get(pid) or {}
    p = next((x for x in followed() if x["id"] == pid), None)
    if p is None:
        return
    today = _today()
    n = P.waiting_new(p["doc"], prog, today)
    if not n:
        return
    from aqt.qt import QCursor, QMenu
    menu = QMenu(mw)
    for days in (3, 5, 7):
        extra = -(-n // days)
        a = menu.addAction(f"Over {days} days (+{extra:,} new a day)")
        a.triggered.connect(lambda _=False, d=days, x=extra: start_catch(pid, d, x))
    menu.addSeparator()
    menu.addAction("Push my dates back…").triggered.connect(lambda: set_shift(pid))
    menu.exec(QCursor.pos())


def start_catch(pid, days, extra):
    c = _pcfg()
    state = _state_cfg(c)
    st = state.get(pid)
    if not st:
        return
    if mw.col and _paused(mw.col, st.get("deck_id")):
        tooltip("New cards are stopped in this deck. Turn them back on in Insights first.")
        return
    st["catch"] = {"until": S.iso(S.d(_today()) + datetime.timedelta(days=days - 1)), "extra": int(extra)}
    c["plans"] = state
    _psave(c)
    apply_catch()
    _after_change()
    tooltip(f"Anki shows {int(extra):,} more new cards a day in this deck for {days} days.")
    app.swap(cfg())


def stop_catch(pid):
    c = _pcfg()
    state = _state_cfg(c)
    st = state.get(pid)
    if not st:
        return
    st.pop("catch", None)
    c["plans"] = state
    _psave(c)
    if mw.col and _deck_ok(mw.col, st.get("deck_id")) and not _paused(mw.col, st.get("deck_id")):
        try:
            deck = mw.col.decks.get(int(st["deck_id"]))
            deck.pop("newLimitToday", None)
            mw.col.decks.save(deck)
        except Exception:
            traceback.print_exc()
    _after_change()
    app.swap(cfg())


def seen_change(pid):
    p = next((p for p in followed() if p["id"] == pid), None)
    c = _pcfg()
    state = _state_cfg(c)
    if p and pid in state:
        state[pid].update(seen_version=p.get("version"), snapshot=P.snapshot(_plan_doc(p)))
        c["plans"] = state
        _psave(c)
    app.swap(cfg())


def set_early(pid, days):
    """3.3, C2: open each date `days` early; what that opens, opens now."""
    cl = client()

    def done(ok):
        if not ok:
            tooltip("Couldn't reach Due Crew. Check your connection.")
            return
        p = next((x for x in followed() if x["id"] == pid), None)
        if p and not p.get("paused"):
            _open_now([p])
        app.swap(cfg())

    _bg(lambda: cl.set_early(pid, days), done)


def _planner_flow():
    from .planner import flow
    return flow


def open_yours(pid=None):
    """3.9.3: Your plans (the plan window), on this plan when one's named."""
    _planner_flow().open_plans(select=pid)


def new_plan_menu():
    """3.9.3: You › Plans' New plan ▾ (round five: New plan, in Anki, the
    one way to start one; or on duecrew.com)."""
    from aqt.qt import QCursor, QMenu
    menu = QMenu(mw)
    menu.addAction("New plan…").triggered.connect(lambda: _planner_flow().open_new())
    menu.addAction("On duecrew.com ↗").triggered.connect(lambda: open_site("/plans"))
    menu.exec(QCursor.pos())


def plan_menu(pid):
    p = next((p for p in followed() if p["id"] == pid), None)
    if p is None:
        return
    from aqt.qt import QCursor, QMenu
    menu = QMenu(mw)
    menu.addAction("Open in Your plans").triggered.connect(lambda: open_yours(pid))  # 3.9.3
    menu.addSeparator()
    if p.get("sched"):  # 3.3: new follows do the plan's days; a 3.2 schedule can still change or go
        menu.addAction("My schedule…").triggered.connect(lambda: open_schedule(pid))
    how = menu.addMenu("How its cards open")  # 3.8.0: at my own pace
    for val, label in (("", "On the plan's dates"), ("ready", "When I'm ready"),
                       ("next", "When I'm ready, the next once I've seen most of the last")):
        a = how.addAction(label)
        a.setCheckable(True)
        a.setChecked((p.get("own") or "") == val)
        a.triggered.connect(lambda _=False, val=val: set_own(pid, val))
    menu.addAction("Open everything now").triggered.connect(lambda: open_everything(pid))
    n_held = held_count(pid)  # 3.8.1: what Hold back (or Put back) keeps shut, and why
    if n_held:
        menu.addAction(f"Held back: {n_held:,} card{'s' if n_held != 1 else ''}…").triggered.connect(lambda: show_held(pid))
    early = menu.addMenu("Open early")  # 3.3, C2: for studying on a phone
    early.setEnabled(not P.own_pace(p))
    for n, label in ((0, "Off"), (1, "1 day"), (2, "2 days"), (3, "3 days"), (5, "5 days"), (7, "7 days")):
        a = early.addAction(label)
        a.setCheckable(True)
        a.setChecked(int(p.get("early") or 0) == n)
        a.triggered.connect(lambda _=False, n=n: set_early(pid, n))
    # G3: skip a date I already know (the ones around now and ahead)
    skip = menu.addMenu("Skip a date")
    today = _today()
    week_ago = S.iso(S.d(today) - datetime.timedelta(days=7))
    ahead = [u for u in P.units(p["doc"]) if str(u.get("opens") or "") >= week_ago][:20]
    for u in ahead:
        a = skip.addAction(f"{u.get('name') or '?'} · {P.fmt_day(u['opens'])}")
        a.triggered.connect(lambda _=False, uid=u["id"]: set_skip(pid, uid, True))
    skip.setEnabled(bool(ahead))
    menu.addAction("Push my dates back…").triggered.connect(lambda: set_shift(pid))  # G4, G7
    menu.addAction("Change deck…").triggered.connect(lambda: change_deck(pid))
    if reset_lines(_raw(pid) or {}):  # 3.7.6: only once something's changed
        menu.addAction("Reset to default…").triggered.connect(lambda: reset_days(pid))
    menu.addSeparator()
    if p.get("paused"):
        menu.addAction("Resume").triggered.connect(lambda: back(pid) if p.get("since") else set_paused(pid, False))
    else:
        menu.addAction("Pause until…").triggered.connect(lambda: pause_until(pid))
    menu.addAction("Stop following").triggered.connect(lambda: stop_following(pid))
    menu.exec(QCursor.pos())


# ---- 3.2: my schedule ----

def study(pid):
    """The session card's Study now: the plan's deck, in Anki's own review."""
    st = _state_cfg().get(pid)
    if not st or not mw.col or not _deck_ok(mw.col, st.get("deck_id")):
        return
    try:
        mw.col.decks.select(int(st["deck_id"]))
        mw.moveToState("review")
    except Exception:
        traceback.print_exc()


def set_catch(pid, mode):
    """The missed-days question answered: spread what's waiting over the
    next few study days, or leave it open with no target. Mine only."""
    c = _pcfg()
    state = _state_cfg(c)
    if pid not in state:
        return
    state[pid]["missed"] = {"mode": mode, "day": _today()}  # 3.8.1: its own key (`catch` is G5's catch-up)
    c["plans"] = state
    _psave(c)
    refresh_progress()
    app.swap(cfg())


def push_back(pid):
    """Every date of mine later by the study days I missed; the plan and the
    crew's dates stay put. One request."""
    p = next((p for p in followed() if p["id"] == pid), None)
    sess = (_state.get("plan_session") or {}).get(pid) or {}
    ask = sess.get("ask") or {}
    if p is None or not ask.get("push"):
        return
    new = S.pushed_start(p["doc"], p.get("sched"), int(ask["push"]))
    if new is None:
        return
    cl = client()

    def done(got):
        if got is False:
            tooltip("Couldn't reach Due Crew. Check your connection.")
            return
        c = _pcfg()
        state = _state_cfg(c)
        if pid in state:
            state[pid]["missed"] = {"mode": "leave", "day": _today()}
            c["plans"] = state
            _psave(c)
        refresh_progress()
        app.swap(cfg())
        tooltip(f"Your dates moved {ask['push']} day{'s' if ask['push'] != 1 else ''} later. The crew's stay put.")
    _bg(lambda: cl.set_schedule(pid, new), done)


def schedule_inputs(col, plan, st, today):
    """What the schedule dialog needs: cards per unit on my deck, the
    reviews already due by day, and my pace. Main thread."""
    from .stats.queries import StatsQueries
    totals = {}
    if st and _deck_ok(col, st.get("deck_id")):
        idx = P.DeckIndex(col, st["deck_id"])
        totals = {uid: len(c) for uid, c in P.unit_matches(idx, plan["doc"], _swap(st)).items()}
    base = []
    try:
        now = int(col.sched.today)
        rows = dict(col.db.all(
            "SELECT due - ?, COUNT(*) FROM cards WHERE queue IN (2, 3) AND due >= ? AND due < ? GROUP BY due",
            now, now, now + 190))
        base = [int(rows.get(i, 0)) for i in range(190)]
        base[0] += int(col.db.scalar("SELECT COUNT(*) FROM cards WHERE queue IN (2, 3) AND due < ?", now) or 0)
    except Exception:
        base = []
    return totals, base, StatsQueries(col).pace()


def open_schedule(pid, then=None):
    """My schedule for a plan: start, days, time, and the load it makes."""
    p = next((p for p in followed() if p["id"] == pid), None)
    if p is None or not mw.col:
        return
    from .ui.schedule_dialog import ScheduleDialog
    today = _today()
    totals, base, pace = schedule_inputs(mw.col, p, _state_cfg().get(pid), today)
    dlg = ScheduleDialog(mw, p, today, totals, base, pace)
    if not dlg.exec():
        if then:
            then()
        return
    want = dlg.value()
    cl = client()

    def done(got):
        if got is False:
            tooltip("Couldn't reach Due Crew. Check your connection.")
        elif then is None:
            fresh = next((x for x in followed() if x["id"] == pid), None)
            if fresh and not fresh.get("paused"):
                _open_now([fresh], toast=False)  # today's share, on the new schedule
            refresh_progress()
            app.swap(cfg())
            tooltip("Schedule saved." if want else "Schedule off: dates open whole, as the plan has them.")
        if then:
            then()
    _bg(lambda: cl.set_schedule(pid, want), done)


def open_everything(pid):
    p = next((p for p in followed() if p["id"] == pid), None)
    if p is None or not _ensure_deck(p):
        return
    res = _open_now([p], everything=True)
    if res is not None and not res["n"]:
        tooltip("Everything in this plan is already open.")
    app.swap(cfg())


def _ensure_deck(p):
    state = _state_cfg()
    if state.get(p["id"]) and _deck_ok(mw.col, state[p["id"]].get("deck_id")):
        return True
    change_deck(p["id"])
    return bool(_state_cfg().get(p["id"]))


def change_deck(pid):
    """Pick the deck this plan runs on here. Units already opened open on
    the new deck too (their sig names the deck); skipped ones stay skipped."""
    p = next((p for p in followed() if p["id"] == pid), None)
    if p is None or not mw.col:
        return
    from . import sheets
    choices = P.deck_choices(mw.col)
    if not choices:
        return
    st = _state_cfg(_pcfg()).get(pid)
    best, _swap_guess = P.best_deck(mw.col, p["doc"], choices)
    current = st.get("deck_id") if st else best
    at = next((i for i, (d, _n) in enumerate(choices) if d == current), 0)
    # plain text: the plan's name is the author's
    sheets.ask_item("Change deck", f"Run {p.get('name') or 'the plan'} on", [n for _d, n in choices],
                    lambda i: _run_on(pid, choices[i][0]), at=at)


def _run_on(pid, did):
    """change_deck's pick."""
    p = next((p for p in followed() if p["id"] == pid), None)
    if p is None or not mw.col:
        return
    c = _pcfg()
    state = _state_cfg(c)
    st = state.get(pid)
    idx = P.DeckIndex(mw.col, did)
    swap = P.detect_swap(idx, p["doc"])
    if swap:
        from .ui.follow_dialog import ask_swap
        if not ask_swap(mw, swap, P.found_total(idx, p["doc"], swap)):
            swap = None
    if st:
        st.update(deck_id=did, swap=list(swap) if swap else None)
    else:
        state[pid] = new_state(mw.col, p, did, swap)
    c["plans"] = state
    _psave(c)
    if p.get("paused"):
        refresh_progress()
    else:
        _open_now([p])
    app.swap(cfg())


def set_paused(pid, paused):
    cl = client()

    def done(res):
        if res is None:
            tooltip("Couldn't reach Due Crew. Check your connection.")
            return
        if not paused:
            _resume(pid)
        app.swap(cfg())

    _bg(lambda: cl.set_follow(pid, paused=paused), done)


def _resume(pid):
    """Resuming asks the catch-up question, as following does."""
    p = next((p for p in followed() if p["id"] == pid), None)
    if p is None or not mw.col:
        return
    if P.own_pace(p):
        # 3.8.1: at my own pace no date waited for its day: nothing to ask (its "start
        # from the next date" skipped every passed date out of Up next); what an author
        # added to dates I opened opens, as a morning would
        _open_now([p])
        return
    today = _today()
    n_units, n_cards = waiting(mw.col, p, _state_cfg().get(pid), today)
    if not n_units:
        return
    from .ui.follow_dialog import ask_catch_up
    nxt = P.next_unit(p["doc"], today)
    choice = ask_catch_up(mw, n_units, n_cards, nxt)
    if choice is None:
        return
    _open_now([p], mode=choice)


def stop_following(pid):
    p = next((p for p in followed() if p["id"] == pid), None)
    if p is None:
        return
    from . import sheets
    text = ("Cards already open stay open"
            + (", and the ones it held back open too" if (_state_cfg().get(pid) or {}).get("held") else "")
            + ". The crew stops seeing your progress on this plan.")
    title = f"Stop following {p.get('name') or 'this plan'}?"
    if (_state_cfg().get(pid) or {}).get("tags"):
        # 3.8.0: its tags stay only if I say so (they stop updating)
        sheets.confirm_check(title, text, "Stop", f"Take {p.get('name') or 'its'}'s tags off your notes too",
                             lambda untag: _stop(pid, untag))
    else:
        sheets.confirm(title, text, "Stop", lambda: _stop(pid, False))


def _stop(pid, untag):
    p = next((p for p in followed() if p["id"] == pid), None)
    if p is None:
        return
    cl = client()

    def done(ok):
        if not ok:
            tooltip("Couldn't reach Due Crew. Check your connection.")
            return
        pc = _pcfg()
        state = _state_cfg(pc)
        held = (state.get(pid) or {}).get("held") or []
        if held and mw.col:
            P.open_cards(mw.col, held, f"Due Crew: stop {p.get('name') or 'plan'}")
            _after_change()
        if untag:
            _drop_plan_tags(state.get(pid), p.get("name"))
        state.pop(pid, None)
        pc["plans"] = state
        _psave(pc)
        _state.get("plan_progress", {}).pop(pid, None)
        app.swap(cfg())

    _bg(lambda: cl.unfollow_plan(pid), done)


# ---- 3.8.1: a follower's day (plans, round three) ----
# Welcome back, the morning's dates, what Hold back keeps, why a date left
# cards shut, Study on a date, my own load beside the plan's. All local but
# Push my dates back (one PATCH, on its click).

REVIEWS_AHEAD = 63  # days of my own reviews due the week can show (nine weeks)


def reviews_by_day(col, today, days=REVIEWS_AHEAD):
    """My own load beside what the plan opens: {iso day: reviews due} in my
    whole Anki, today (overdue too) and the days ahead, by Anki's due day.
    One query; a card in a filtered deck isn't counted."""
    now, base, out = int(col.sched.today), S.d(today), {}
    for k, n in col.db.all("SELECT due - ?, count() FROM cards WHERE queue IN (2, 3) AND odid = 0 AND due < ? "
                           "GROUP BY due", now, now + int(days)) or []:
        day = S.iso(base + datetime.timedelta(days=max(0, int(k))))
        out[day] = out.get(day, 0) + int(n)
    return out


def _note_reviews(col, today):
    """refresh_progress: reviews_by_day, read again only when the collection
    or the day changed (`_state["plan_reviews"]`: ((mod, day), {day: n}))."""
    key = (getattr(col, "mod", None), today)
    hit = _state.get("plan_reviews")
    if hit and key[0] is not None and hit[0] == key:
        return
    _state["plan_reviews"] = (key, reviews_by_day(col, today))


def _day_due(today):
    """{iso day: reviews due} for the week's day lines; today's is Due's own
    count (Anki's limits, learning too) when Due has read it."""
    got = _state.get("plan_reviews")
    out = dict(got[1]) if got and got[0][1] == today else {}
    hit = _state.get("due_reviews")
    if hit and hit[1] and today:
        out[today] = int(hit[1].get("due") or 0)
    return out


def _week_more(week, st, prog, today):
    """card_view's week with what only this computer knows: what a date left
    shut when it opened (leeches, picks this copy doesn't have: _tally's
    counts), Study on a date with cards open, and each day's own load
    (reviews due) beside what the plan opens. A key only where there's
    something to say."""
    lee, miss = (st or {}).get("leeches") or {}, (st or {}).get("missing") or {}
    mine = _day_due(today) if st else {}
    for d in week:
        n = int(mine.get(d["day"]) or 0)
        if n and d["day"] >= today:
            d["mine"] = n
        for r in d["units"]:
            if r["state"] not in ("open", "done"):
                continue
            if st and int(((prog or {}).get(r["uid"]) or [0])[0]):
                r["study"] = True
            m = miss.get(r["uid"])
            why = {"lee": int(lee.get(r["uid"]) or 0), "miss": int(m[0]) if isinstance(m, (list, tuple)) and m else 0}
            if why["lee"] or why["miss"]:
                r["why"] = why


def browse_leeches(pid, uid):
    """Why didn't it open: Anki's browser on a date's leeches, which a plan
    never opens."""
    got = _plan_idx(pid)
    if not got:
        return
    _p, st, doc, idx = got
    u = next((x for x in P.units(doc) if x["id"] == uid), None)
    if u is None:
        return
    try:
        cids = {c for c in idx.match(u, _swap(st), doc) if c in idx.leech and idx.cards[c][0] == -1}
    except Exception:
        traceback.print_exc()
        return
    _browse(cids, empty="No leeches in it now.")


# -- what Hold back keeps --

HELD_LINES = 8  # dates the Held back sheet names


def held_count(pid):
    """How many cards this plan holds shut here now that Open them would open
    (Hold back's, Put back's; a leech never opens): the plan's ··· menu says
    it, the same number as its sheet."""
    v = held_view(pid) if mw.col else None
    return int(v["n"]) if v else 0


def _held_now(st, doc, idx):
    """3.8.1: the cards the plan holds shut here now: in `held`, suspended, and
    on no date that opened here (a card I suspended myself after its date
    opened isn't the plan's to show or open)."""
    shut = {c for c in _shut_by_plan(st) if c in idx.cards and idx.cards[c][0] == -1}
    opened = {k for k, v in (st.get("applied") or {}).items() if not str(v).startswith("skip:")} | set(st.get("own_opened") or {})
    for u in P.units(doc):
        if u["id"] in opened and shut:
            shut -= idx.match(u, _swap(st), doc)
    return shut


def held_view(pid):
    """What the Held back sheet says: {name, n, lines, more, why, leeches,
    holding}: n and lines are what Open them opens, by date; leeches, the
    held ones that stay shut. Raw strings (the sheet shows them as plain
    text); None when the plan doesn't run here."""
    got = _plan_idx(pid)
    if not got:
        return None
    p, st, doc, idx = got
    shut = _held_now(st, doc, idx)
    held = shut - idx.leech
    own, holding = P.own_pace(p), _hold_yes(p, st)
    lines = []
    for name, opens, n in P.held_rows(idx, doc, held, _swap(st)):
        if name is None:
            lines.append(f"On no date now · {n:,}")
        else:
            lines.append(f"{name} · {n:,}" if own or not opens else f"{name} · {P.fmt_day(opens)} · {n:,}")
    if holding:
        why = ("You said yes to Hold back: the new cards of dates you haven't opened wait, suspended, till you open them."
               if own else "You said yes to Hold back: the new cards of dates still to come wait, suspended, till their day.")
    elif own:
        why = "You put these back. They open when you open their date again."
    else:
        why = "Hold back is off; these stayed shut."
    return {"name": str(p.get("name") or "The plan"), "n": len(held), "lines": lines[:HELD_LINES],
            "more": max(0, len(lines) - HELD_LINES), "why": why, "holding": holding, "leeches": len(shut & idx.leech)}


def show_held(pid, ask=None):
    """The plan's ··· menu, Held back: N cards…: what it holds and why; Open
    them · Stop holding back · Close."""
    v = held_view(pid)
    if not v or not v["n"]:
        tooltip("Nothing held back now.")
        return
    if ask is None:
        from .ui.held_dialog import ask_held
        ask = lambda view: ask_held(mw, view)  # noqa: E731
    choice = ask(v)
    if choice in ("open", "stop"):
        open_held(pid, stop=choice == "stop")


def open_held(pid, stop=False):
    """Open what the plan holds shut here, as one undo step (a leech stays
    shut). Hold back stays on for what an author adds later (the opened
    cards stay in `held`, so it never shuts them again); stop: and it's off
    (`hold_yes`)."""
    got = _plan_idx(pid)
    if not got:
        return
    p, st, doc, idx = got
    held = sorted(_held_now(st, doc, idx))
    name = p.get("name") or "plan"
    n = P.open_cards(mw.col, held, f"Due Crew: open what {name} held back") if held else 0
    if stop:
        _hold_yes(p, st)
        st["hold_yes"] = False
    pc = _pcfg()
    pc["plans"] = _state_cfg(pc)
    _psave(pc)
    if n:
        _after_change()
    refresh_progress()
    said = f"Opened {n:,} card{'s' if n != 1 else ''}. Edit › Undo shuts them again." if n else "Nothing to open."
    tooltip(said + (" Nothing more is held back." if stop else ""), period=5000)
    app.swap(cfg())


# -- Welcome back --

def _away(col, plan_list, state, today):
    """{plan id: {days, units, n}}: each plan on its dates (not at my own pace,
    not paused, not on a 3.2 schedule or even dates, which open in slices)
    whose morning would open dates from AWAY_DAYS or more days on which I
    studied nothing in Anki (no answer at all, any deck: the revlog after
    the day's sync, phone included). days: those days; units: every date
    the morning would open for it; n: their cards. Cheap when there's
    nothing to ask: the revlog (one query) and the deck are read only for
    a plan with that many days' dates waiting."""
    from .stats.queries import StatsQueries
    out, studied = {}, None
    since = S.iso(S.d(today) - datetime.timedelta(days=P.AWAY_LOOK))
    for p in plan_list:
        q = mine(p)
        st = state.get(p["id"])
        if (p.get("paused") or P.own_pace(p) or p.get("sched") or not st or S.has_even(q["doc"])
                or not _deck_ok(col, st.get("deck_id"))):
            continue
        applied, later = st.get("applied") or {}, st.get("later") or {}
        waiting = {str(u.get("opens")) for u in P.units(q["doc"])
                   if since <= str(u.get("opens") or "") < today and applied.get(u["id"]) is None
                   and str(later.get(u["id"]) or "") <= today}
        if len(waiting) < P.AWAY_DAYS:
            continue
        if studied is None:
            sq = StatsQueries(col)
            studied = {sq.day_label(int(a)) for a in sq.studied_days_ago(P.AWAY_LOOK + 1)}
        if len(waiting - studied) < P.AWAY_DAYS:
            continue
        dry = run(col, [p], copy.deepcopy(state), today, dry=True)
        uids = list(dry["units"].get(p["id"]) or [])
        by = {u["id"]: u for u in P.units(q["doc"])}
        days = P.away_days([by[x] for x in uids if x in by], applied, today, studied, since)
        if len(days) >= P.AWAY_DAYS:
            out[p["id"]] = {"days": days, "units": uids, "n": int((dry["per"].get(p["id"]) or [[], 0])[1])}
    return out


def _put_away(plan_list, today):
    """The morning, before it opens: a plan Welcome back will ask about keeps
    what it would open shut till then (`later`, as Not today does), so it's
    never opened before the question; its question waits in `away`."""
    if not mw.col:
        return {}
    c = _pcfg()
    state = _state_cfg(c)
    try:
        away = _away(mw.col, plan_list, state, today)
    except Exception:
        traceback.print_exc()
        return {}
    for pid, info in away.items():
        ask_later(state[pid], info["units"], today)
        state[pid]["away"] = dict(info, day=today)
    if away:
        c["plans"] = state
        _psave(c)
    return away


def _release_away(st, today):
    """The question answered with Open or Push: its dates aren't kept back any more."""
    info = (st or {}).pop("away", None) or {}
    tomorrow = S.iso(S.d(today) + datetime.timedelta(days=1))
    later = (st or {}).get("later") or {}
    for uid in info.get("units") or []:
        if later.get(uid) == tomorrow:
            later.pop(uid)


def welcome_back(pids, ask=None):
    """Main thread, after the morning (on Decks): each plan _put_away kept
    back asks Welcome back: Open them · Push my dates back N days (N: the
    days I studied nothing; the follow's shift, one PATCH) · Not today
    (nothing opens; tomorrow morning asks again)."""
    for pid in pids:
        try:
            _welcome_one(pid, ask)
        except Exception:
            traceback.print_exc()


def _welcome_one(pid, ask=None):
    p = next((x for x in followed() if x["id"] == pid), None)
    c = _pcfg()
    state = _state_cfg(c)
    st = state.get(pid)
    info = (st or {}).get("away") or {}
    today = _today()
    if p is None or p.get("paused") or not mw.col or info.get("day") != today:
        return
    days = [str(x) for x in info.get("days") or []]
    choice = (ask or _ask_away)(str(p.get("name") or "The plan"), days, len(info.get("units") or []), int(info.get("n") or 0))
    if choice == "open":
        _release_away(st, today)
        c["plans"] = state
        _psave(c)
        _open_now([p])
        app.swap(cfg())
    elif choice == "push":
        n = len(days)
        shift = min(365, int((_raw(pid) or {}).get("shift") or 0) + n)
        cl, gen = client(), app.generation

        def done(res):
            if gen != app.generation:
                return
            if res is None:
                tooltip("Couldn't reach Due Crew. Check your connection. Tomorrow morning asks again.")
                app.swap(cfg())
                return
            pc = _pcfg()
            st2 = _state_cfg(pc).get(pid)
            if st2 is not None:
                _release_away(st2, today)
                _psave(pc)
            if not res.get("paused"):
                _open_now([x for x in followed() if x["id"] == pid], toast=False)  # what's due on my new days
            tooltip(f"Your dates moved {n} day{'s' if n != 1 else ''} later. The plan's stay put.", period=5000)
            app.swap(cfg())
        _bg(lambda: cl.set_days(pid, shift=shift), done)
    else:
        app.swap(cfg())  # Not today, or closed: nothing opens; tomorrow morning asks again


def _ask_away(name, days, n_dates, n_cards):
    from .rooms import sev_on  # 3.8.1: Pip waves from its corner, as Settings › Pip says
    from .ui.away_dialog import ask_away
    return ask_away(mw, name, days, n_dates, n_cards, sev=sev_on())


# ---- following ----

def _signed_in():
    """3.3: a plan needs an account; not signed in, the sign-in opens here
    and the plan carries on after it."""
    if client().signed_in:
        return True
    from . import open_auth
    open_auth()
    return client().signed_in


def open_follow(code=""):
    if not _signed_in():
        return
    if not mw.col:
        return
    from .ui.follow_dialog import FollowDialog
    dlg = FollowDialog(mw, client(), mw.col, code=code, today=_today(), on_followed=on_followed)
    dlg.exec()


def on_followed(plan, deck_id, swap, late, hold=False):
    """Main thread, after POST /plans/follow: this computer runs it on
    `deck_id`; late is "open" (open what has opened) or "skip". 3.7.6:
    "skip:a,b" starts where everyone is (the passed dates skipped on my
    follow, so they're behind nowhere), "catch:W:N" opens them and catches
    up N cards over W weeks (G5's today-only limit), "begin:D" runs my
    dates D days later so the first is today. Following
    again keeps what this computer already applied: only the deck changes.
    hold (3.3, asked for at Follow): later dates' active, never-studied
    cards are suspended now, one undo step, and remembered so stopping
    opens them again."""
    cl = client()
    cl.remember_plan(plan)
    c = _pcfg()
    state = _state_cfg(c)
    st = state.get(plan["id"])
    if st:
        st.update(deck_id=int(deck_id), swap=list(swap) if swap else None)
    else:
        state[plan["id"]] = new_state(mw.col, plan, deck_id, swap)
    kind, _, rest = str(late).partition(":")
    if hold and mw.col:
        state[plan["id"]]["hold_yes"] = True  # 3.8.1: my yes, kept (hold_new holds what authors add later)
        idx = P.DeckIndex(mw.col, deck_id)
        # 3.7.6: from the beginning, "later dates" are my shifted ones
        hdoc = P.my_doc(plan["doc"], int(rest)) if kind == "begin" and rest.isdigit() else plan["doc"]
        cids = P.holdable(idx, hdoc, _today(), swap, state[plan["id"]].get("applied"), own=P.own_pace(plan),
                          kept=_opened_cids(idx, state[plan["id"]], hdoc))
        n = P.hold_cards(mw.col, cids, f"Due Crew: hold back {plan.get('name') or 'plan'}")
        if n:
            state[plan["id"]]["held"] = sorted(set(state[plan["id"]].get("held") or []) | set(int(c) for c in cids))
            _after_change()
    c["plans"] = state
    _psave(c)

    pid = plan["id"]
    saved = kind not in ("skip", "begin") or not rest  # what needs a request has it yet?

    def finish(got=None):
        show_plans(cfg(), swap=False)  # 3.3: where it lives now (3.8.0: You › Plans)
        fresh = next((x for x in followed() if x["id"] == pid), plan)
        ok = saved or got is not None
        if not ok:
            # a choice that didn't reach the server never opens what has passed:
            # the passed dates are skipped here only, and today's opens as usual
            c3 = _pcfg()
            st3 = _state_cfg(c3).get(pid)
            if st3 is not None:
                skip_past(st3, plan, _today())
                c3["plans"] = _state_cfg(c3)
                _psave(c3)
        apply_tags([fresh])  # 3.8.0: its tags, before its dates open
        # "skip:" saved the passed dates as skipped on my follow, so today's opens as usual
        res = _open_now([fresh], mode="skip" if kind == "skip" and not rest else "open")
        if not ok:
            tooltip("Following. Couldn't save how you start, so the earlier dates wait here; "
                    "Plan \u25be \u203a Push my dates back… or Open now on each.", period=7000)
            app.swap(cfg())
            return
        if kind == "catch":
            weeks, _, cards = rest.partition(":")
            days = 7 * max(1, min(3, int(weeks or 2)))
            if int(cards or 0):
                start_catch(pid, days, -(-int(cards) // days))
        elif res is not None and not res["n"]:
            tooltip(f"Following {html.escape(plan.get('name') or 'the plan')}.")
        app.swap(cfg())

    cl = client()
    if kind == "skip" and rest:
        _bg(lambda: cl.set_days(pid, skipped=[u for u in rest.split(",") if u]), finish)
    elif kind == "begin" and rest.isdigit() and int(rest):
        _bg(lambda: cl.set_days(pid, shift=min(365, int(rest))), finish)
    else:
        finish()  # 3.3: the plan's days are the schedule; nothing to ask


def open_make():
    if not _signed_in():
        return
    if not mw.col:
        return
    from .ui.plan_dialog import MakePlanDialog
    from .planner import flow as planner_flow
    make, made = planner_flow.make_here(client())
    MakePlanDialog(mw, client(), mw.col, site_base(), on_sent=note_tree, make=make, on_made=made).exec()


def open_site(path):
    """3.5.0: a page of duecrew.com in the browser, signed in when the link
    can be made (a one-time token in the fragment, never logged)."""
    cl, site = client(), site_base()

    def done(token):
        from aqt.utils import openLink
        openLink(f"{site}{path}" + (f"#{token}" if token else ""))
    _bg(lambda: cl.site_link() if cl.signed_in else None, done)


def site_base():
    return (str(cfg().get("site_base") or "") or os.environ.get("DUE_CREW_SITE")
            or "https://duecrew.com").rstrip("/")


# ---- Anki's browser ----

def browser_menu(browser, menu):
    """gui_hooks.browser_will_show_context_menu: why a card isn't showing
    (3.8.0, signed in or not: it's Anki help); single cards onto a date.
    3.8.1: the ones for writing a plan only for someone who writes one."""
    menu.addSeparator()
    from . import why_flow
    why = menu.addAction("Due Crew: why isn't it showing?")
    why.triggered.connect(lambda: why_flow.explain(browser))
    opn = menu.addAction("Due Crew: open these…")  # 3.8.0: never suspends; leeches stay
    opn.triggered.connect(lambda: open_these(browser))
    if not client().signed_in:
        return
    if client().session.get("plans_authored"):  # the plans I write or co-author, from the day's refresh
        action = menu.addAction("Due Crew: add to a plan…")
        action.triggered.connect(lambda: add_to_plan(browser))
        tag = menu.addAction("Due Crew: tag for a plan…")  # 3.8.0: plan tags
        tag.triggered.connect(lambda: tag_for_plan(browser))
        if _one_card(browser):  # 3.8.1: a note on one card, for the plan's followers
            note = menu.addAction("Due Crew: note for the plan's followers…")
            note.triggered.connect(lambda: note_for_card(browser))
        copy = menu.addAction("Due Crew: copy as plan selector")
        copy.triggered.connect(lambda: copy_selector(browser))
        out = menu.addAction("Due Crew: export for my AI…")
        out.triggered.connect(lambda: export_selected(browser))
    if followed():
        where = menu.addAction("Due Crew: show on my plan")
        where.triggered.connect(lambda: show_on_plan(browser))


# ---- 3.8.0: open from Browse (a tag in the sidebar, or the picked cards) ----

def sidebar_menu(sidebar, menu, item, index):
    """gui_hooks.browser_sidebar_will_show_context_menu: a tag's Due Crew: open its cards…"""
    try:
        from aqt.browser.sidebar.item import SidebarItemType
        if item is None or item.item_type != SidebarItemType.TAG:
            return
        tag = str(item.full_name or "")
    except Exception:
        return
    if not tag:
        return
    menu.addSeparator()
    parent = getattr(sidebar, "browser", None) or mw
    menu.addAction("Due Crew: open its cards…").triggered.connect(lambda: open_tag(parent, tag))


def _tag_words(tag):
    """"#Videos::Micro::12_Strep" -> ("12 Strep", "#Videos › Micro › 12 Strep")."""
    parts = [x.replace("_", " ").strip() or x for x in str(tag).split("::")]
    return parts[-1], " › ".join(parts)


def open_tag(parent, tag):
    """A tag's cards, its children's too."""
    if not mw.col:
        return
    try:
        cids = mw.col.find_cards(P.tag_search(tag) + '"')
    except Exception:
        traceback.print_exc()
        return
    title, where = _tag_words(tag)
    _open_sheet(parent, cids, title, where)


def open_these(browser):
    if not mw.col:
        return
    try:
        cids = browser.selected_cards() if hasattr(browser, "selected_cards") else browser.selectedCards()
    except Exception:
        traceback.print_exc()
        return
    if not cids:
        tooltip("Select some cards first.")
        return
    _open_sheet(browser, cids, None, "")


def _on_plans(cids):
    """Lines for the sheet: the plans I follow whose dates hold some of these."""
    out, want = [], {int(c) for c in cids}
    state = _state_cfg()
    for p in followed():
        st = state.get(p["id"])
        if not st or not _deck_ok(mw.col, st.get("deck_id")):
            continue
        idx = P.DeckIndex(mw.col, st["deck_id"])
        names = [str(u.get("name") or "?") for u in P.units(p["doc"])
                 if idx.match(u, _swap(st), p["doc"]) & want]
        if names:
            out.append(f"On {p.get('name') or 'a plan'}: {', '.join(names[:3])}"
                       + (f" and {len(names) - 3} more" if len(names) > 3 else "") + ", which count them")
        if len(out) == 2:
            break
    return out


def _open_sheet(parent, cids, title, where):
    counts = P.open_counts(mw.col, cids)
    try:
        plans = _on_plans(cids) if counts["open"] else []
    except Exception:
        traceback.print_exc()
        plans = []
    from .ui.open_dialog import OpenDialog
    OpenDialog(parent, title, where, counts, plans,
               on_open=lambda first, study: open_cards_now(cids, title or "the picked cards", first, study)).exec()


def open_cards_now(cids, name, first=True, study=False):
    """Open them (never a leech, never suspends), first in line when asked, as
    one undo step; at my own pace, a date now all open counts as opened; with
    study, a Due Crew deck of the new ones, and into it."""
    if not mw.col:
        return 0
    shut = P.openable_ids(mw.col, cids)  # what this open unsuspends
    n = P.open_cards(mw.col, cids, f"Due Crew: open {name}", first=first)
    if n:
        _after_change()
    try:
        _claim_opened(shut if n else ())
    except Exception:
        traceback.print_exc()
    refresh_progress()
    if study:
        cl = sorted({int(c) for c in cids})
        new = []
        for i in range(0, len(cl), 500):
            chunk = ",".join(str(c) for c in cl[i:i + 500])
            new += mw.col.db.list(f"SELECT id FROM cards WHERE type = 0 AND queue = 0 AND id IN ({chunk})")
        deck = _deck_name(name)
        if new and _filtered(mw.col, deck, new, order=NEW_ORDER):
            _after_change()
            did = mw.col.decks.id_for_name(deck)
            if did:
                mw.col.decks.select(did)
                mw.moveToState("overview")
    if n:
        tooltip(f"Opened {n:,}{' · first in line' if first else ''}. Edit › Undo puts them back.", period=5000)
    app.swap(cfg())
    return n


def _claim_opened(touched):
    """At my own pace, a date whose cards are all open now because Browse
    opened some of them (`touched`, what that open unsuspended; leeches
    aside) counts as opened today, so Up next moves on. 3.8.1: only such a
    date; before, every date already all open counted too, so on a deck
    whose cards were all active one open from Browse opened the whole plan."""
    touched = {int(x) for x in touched or ()}
    if not touched:
        return False
    c = _pcfg()
    state = _state_cfg(c)
    today, changed = _today(), False
    for p in followed():
        st = state.get(p["id"])
        if not P.own_pace(p) or not st or not _deck_ok(mw.col, st.get("deck_id")):
            continue
        if _claim(P.DeckIndex(mw.col, st["deck_id"]), st, p["doc"], today, touched):
            changed = True
    if changed:
        c["plans"] = state
        _psave(c)
    return changed


def show_on_plan(browser):
    """3.8.0: the board on the plan date that has the card picked in the
    browser: You › Plans, that date's week, its details open. The first
    plan I follow that has it; within it, the date nearest today."""
    try:
        cids = [int(c) for c in (browser.selected_cards() if hasattr(browser, "selected_cards") else browser.selectedCards())]
    except Exception:
        cids = []
    if not cids or not mw.col:
        tooltip("Pick a card first.")
        return
    today = _today()
    for p in followed():
        got = _plan_idx(p["id"])
        if not got:
            continue
        _p, st, doc, idx = got
        try:
            us = P.dates_with(idx, doc, cids, _swap(st))
        except Exception:
            traceback.print_exc()
            continue
        if not us:
            continue
        u = min(us, key=lambda x: abs((S.d(str(x["opens"])) - S.d(today)).days))
        jump_to(p["id"], str(u["opens"]))
        tooltip(f"{html.escape(P.plan_title(p))}: {html.escape(str(u.get('name') or '?'))}, {P.fmt_day(u['opens'])}")
        return
    tooltip("It isn't on a plan you follow.")


def jump_to(pid, day):
    """You › Plans on `day`'s week of this plan, the day's details open."""
    today = _today()
    weeks = (S.d(P.week_start(day)) - S.d(P.week_start(today))).days // 7
    _state.setdefault("plan_week", {})[pid] = max(-26, min(26, weeks))
    _state["plan_focus"] = {pid: day}
    c = cfg()
    c["plan_pick"] = pid  # with two or more plans, this one stays shown once the day lets go
    show_plans(c, swap=False)
    if getattr(mw, "state", "") != "deckBrowser":
        mw.moveToState("deckBrowser")
    app.swap(c)
    try:
        mw.activateWindow()
        mw.raise_()
    except Exception:
        pass


def open_export():
    """3.6.5, P3: Tools › Due Crew › Export cards for my AI…"""
    if not mw.col:
        return
    from .ui.export_dialog import ExportDialog
    cl = client()
    ExportDialog(mw, mw.col, cl if cl.signed_in else None, followed(), _state_cfg(), on_saved=_saved).exec()


def _saved(n, path):
    tooltip(f"Saved {n:,} note{'s' if n != 1 else ''} to {html.escape(os.path.basename(path))}. "
            "Attach it to your AI chat with the prompt.")


def export_selected(browser):
    """3.6.5, P3: the notes selected in the browser (their notes, in Cards
    mode), to a file for my AI."""
    if not mw.col:
        return
    try:
        nids = browser.selected_notes() if hasattr(browser, "selected_notes") else browser.selectedNotes()
    except Exception:
        traceback.print_exc()
        return
    if not nids:
        tooltip("Select some notes first.")
        return
    from aqt.qt import QFileDialog
    from .ui.export_dialog import save
    desk = os.path.join(os.path.expanduser("~"), "Desktop")
    start = os.path.join(desk if os.path.isdir(desk) else os.path.expanduser("~"), "cards-for-my-ai.txt")
    path, _ = QFileDialog.getSaveFileName(browser, "Export for my AI", start, "Text (*.txt)")
    if path:
        save(mw.col, nids, path, True, _saved)


def copy_selector(browser):
    """3.6.5: the selected notes (Notes mode) or cards (Cards mode) as
    notes:… or cards:…, for a date in the builder's Text or Add cards box."""
    if not mw.col:
        return
    table = getattr(browser, "table", None)
    try:
        notes_mode = bool(table is not None and hasattr(table, "is_notes_mode") and table.is_notes_mode())
    except Exception:
        notes_mode = False
    try:
        if notes_mode:
            picked = browser.selected_notes() if hasattr(browser, "selected_notes") else browser.selectedNotes()
            text, n = P.selector(mw.col, nids=picked)
        else:
            picked = browser.selected_cards() if hasattr(browser, "selected_cards") else browser.selectedCards()
            text, n = P.selector(mw.col, cids=picked)
    except Exception:
        traceback.print_exc()
        return
    if not n:
        tooltip("Select some notes or cards first.")
        return
    from aqt.qt import QApplication
    QApplication.clipboard().setText(text)
    what = f"{n:,} note{'s' if n != 1 else ''}" if notes_mode else f"{n:,} card{'s' if n != 1 else ''}"
    tooltip(f"Copied {what}. Paste into a date on duecrew.com." + (" A date takes up to 5,000." if n > 5000 else ""))


def tag_for_plan(browser):
    """3.8.0, Browse › Due Crew: tag for a plan…: the picked notes onto one of
    a plan's own tags (or off it). The plan gets their guids; this Anki gets
    the tag at once, in one undo step; followers with the plan's update."""
    if not mw.col or not _signed_in():
        return
    try:
        nids = browser.selected_notes() if hasattr(browser, "selected_notes") else browser.selectedNotes()
    except Exception:
        traceback.print_exc()
        return
    nids = [int(n) for n in nids or []]
    if not nids:
        tooltip("Select some notes first.")
        return
    guid_of = {}
    for i in range(0, len(nids), 500):
        part = nids[i:i + 500]
        for nid, g in mw.col.db.all(f"SELECT id, guid FROM notes WHERE id IN ({','.join(str(n) for n in part)})"):
            guid_of[int(nid)] = str(g)
    from .ui.tag_dialog import TagDialog

    def outside(p):
        """How many picked notes have no card in the plan's deck here: a follower's
        Anki tags inside the plan's deck only."""
        want = str(((p or {}).get("doc") or {}).get("deck") or "").lower()
        dids = [d for d, n in P.deck_choices(mw.col) if want and (n.lower() == want or n.lower().startswith(want + "::"))]
        if not dids:
            return 0
        ds = ",".join(str(d) for d in dids)
        inside = set()
        for i in range(0, len(nids), 500):
            part = ",".join(str(n) for n in nids[i:i + 500])
            inside |= {int(n) for n in mw.col.db.list(
                f"SELECT DISTINCT nid FROM cards WHERE nid IN ({part}) AND (did IN ({ds}) OR odid IN ({ds}))")}
        return len(set(nids) - inside)

    def done(plan, name, path, added, taken):
        by_guid = {g: n for n, g in guid_of.items()}
        mine = [by_guid[g] for g in (added or taken) if g in by_guid]
        if mine and path.lower().startswith(P.TAG_PARENT.lower() + "::"):
            pos = None
            try:
                pos = mw.col.add_custom_undo_entry(f"Due Crew: {'take off' if taken else 'tag'} {name}")
            except Exception:
                pos = None
            for i in range(0, len(mine), 5000):
                (mw.col.tags.bulk_remove if taken else mw.col.tags.bulk_add)(mine[i:i + 5000], path)
            if pos is not None:
                try:
                    mw.col.merge_undo_entries(pos)
                except Exception:
                    pass
            _tags_changed()
        # following my own plan: this copy has it already, so its update doesn't call it new
        c = _pcfg()
        st = _state_cfg(c).get(plan.get("id"))
        doc = _plan_doc(plan)
        t = next((x for x in P.plan_tags(doc) if P.tag_path(doc, x).lower() == path.lower()), None)
        if t and not taken:
            if st is not None:
                st.setdefault("tags", {})[str(t["id"])] = path
            else:  # a plan I write: its pass here doesn't call it new either
                c.setdefault("authored_tags", {}).setdefault(plan.get("id"), {}).setdefault("tags", {})[str(t["id"])] = path
            _psave(c)
        n = len(added or taken)
        tooltip((f"Took {n:,} note{'s' if n != 1 else ''} off {html.escape(name)}."
                 if taken else f"Tagged {n:,} note{'s' if n != 1 else ''} as {html.escape(name)}. ")
                + ("" if taken else f"{html.escape(plan.get('name') or 'The plan')}'s followers get it with its next update."),
                period=5000)

    TagDialog(browser, client(), [guid_of[n] for n in nids if n in guid_of], on_done=done, outside=outside).exec()


def _one_card(browser):
    """3.8.1: the browser has exactly one card picked (a note of one card, in Notes)."""
    try:
        return len(browser.selected_cards() if hasattr(browser, "selected_cards") else browser.selectedCards()) == 1
    except Exception:
        return False


def note_for_card(browser):
    """3.8.1, Browse › Due Crew: note for the plan's followers…: one line on
    one card, for everyone following a plan I write or co-author; it shows
    when that card comes up for them. The plan gets the card's guid and
    number and my words, never the card's text; one note a card a plan,
    edited or taken off here."""
    if not mw.col or not _signed_in():
        return
    try:
        cids = browser.selected_cards() if hasattr(browser, "selected_cards") else browser.selectedCards()
    except Exception:
        traceback.print_exc()
        return
    refs = P.card_refs(mw.col, cids) if len(cids or []) == 1 else []
    if not refs:
        tooltip("Select one card first.")
        return
    from .ui.remark_dialog import RemarkDialog
    RemarkDialog(browser, client(), refs[0][0], refs[0][1], on_done=lambda text: tooltip(html.escape(text), period=5000)).exec()


def add_to_plan(browser):
    if not mw.col or not _signed_in():
        return
    table = getattr(browser, "table", None)
    try:
        notes_mode = bool(table is not None and hasattr(table, "is_notes_mode") and table.is_notes_mode())
    except Exception:
        notes_mode = False
    # 3.3, C3: the search in the browser's box, and how many cards it finds
    try:
        search = browser.form.searchEdit.lineEdit().text().strip()
    except Exception:
        search = ""
    if not P.shareable_search(search):
        search = ""  # Anki's own deck:current, or a search about my reviews: not for a plan
    try:
        search_n = len(mw.col.find_cards(search)) if search else 0
    except Exception:
        search, search_n = "", 0
    cids = []
    if not notes_mode:
        # a note's row is all its cards; exact cards come from Cards mode
        try:
            cids = browser.selected_cards()
        except AttributeError:
            cids = browser.selectedCards()
    if not cids and not search:
        tooltip("Switch the browser to Cards to add single cards to a plan." if notes_mode
                else "Search for the cards (a tag, say), or select them, first.")
        return
    refs = P.card_refs(mw.col, cids) if cids else []  # which cards, never their text
    from .ui.add_cards_dialog import AddCardsDialog

    def added(plan, n):
        tooltip(f"Added {n:,} card{'s' if n != 1 else ''} to {html.escape(plan.get('name') or 'the plan')}.")

    AddCardsDialog(browser, client(), refs, _today(), on_added=added, search=search, search_n=search_n).exec()
