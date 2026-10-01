"""3.1 plans, the glue: what this computer remembers about the plans I
follow, the morning, progress for the sync, the Decks tab's plan card,
and the menus. Main-thread rules as in __init__: every collection read and
the one unsuspend step happen here, on the main thread; plan_flow never
makes a request of its own except on a click (follow, pause, stop).

Per profile and computer, in user_files/<profile>/plans.json (deck ids
belong to one collection, so not in the add-on's config, which every
profile shares): `plans`: {plan id: {deck_id, swap, applied: {unit id: sig
| "skip:" + sig}, src: {unit id: what it matched with when applied},
seen_version, snapshot}}, `plans_day`, `plans_opened` and
`plan_offers_dismissed`. Follow, share and pause live on the server; the
board's plans are cached in the session (api.fetch_board), so a light
refresh and an offline morning have them.

The morning is once per Anki day (`plans_day`): after the day's AnkiWeb
sync, or at the first refresh when this profile doesn't sync; the day's
fresh plans get one more look. It never suspends anything: a unit
removed, a date moved later, a plan stopped all leave open cards open. A
unit the author changes opens only the cards the change adds, and a leech
never opens.
"""

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
    except FileNotFoundError:
        if not mw.col:
            return {}  # nothing to claim with yet; asked again once it's open
        data = _migrate()
        _store.update(profile=key, data=data)
        _psave(data)
    except Exception:
        data = {}
    _store.update(profile=key, data=data)
    return data


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
    return lambda u: P.unit_sig(u, st.get("deck_id"), st.get("swap"))


def _swap(st):
    s = st.get("swap")
    return tuple(s) if s else None


def mine(p):
    """G3, G4: a followed plan as I run it: my dates `shift` days later, the
    ones I skip left out (P.my_doc). Marked, so it's never shifted twice;
    `plan_doc` is the plan itself (what the author's changes compare to)."""
    if p.get("_mine"):
        return p
    return dict(p, doc=P.my_doc(p["doc"], int(p.get("shift") or 0), p.get("skipped") or ()),
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


def _unit_cids(idx, st, u, deck, whole=False):
    """The cards applying `u` opens: its match, or, when it was applied
    before on this deck and the author changed it since, only the cards the
    change adds (a card suspended since by hand, or by Anki, stays so)."""
    cids = idx.match(u, _swap(st), deck)
    was = (st.get("src") or {}).get(u["id"])
    have = (st.get("applied") or {}).get(u["id"])
    if whole or not was or not isinstance(have, str) or have.startswith("skip:"):
        return cids
    did, swap, tags, decks, cards = was[:5]
    if did != st.get("deck_id") or list(swap or []) != list(st.get("swap") or []):
        return cids  # another deck now: what had opened opens there too
    before = {"tags": tags, "decks": decks, "cards": cards}
    # what came after the first five (P.unit_sources): a date's searches
    # (3.3, C3: a list of strings), its pasted ids (E1: [nids, cids]), its
    # notes and the refs behind its ids (3.6.5: a dict)
    for extra in was[5:]:
        if isinstance(extra, dict):
            before["notes"], before["idr"] = extra.get("notes") or [], extra.get("idr") or []
        elif extra and all(isinstance(x, str) for x in extra):
            before["search"] = extra
        elif isinstance(extra, list) and len(extra) == 2 and all(isinstance(x, list) for x in extra):
            before["nids"], before["cids"] = extra
    old = idx.match(before, _swap(st), deck)
    return cids - old


def run(col, plan_list, state, today, mode=None, everything=False):
    """Open what's due (or, with `everything`, every unit) for these plans,
    in one undo step. mode "skip" marks due units applied without opening
    them (joining late, "Start from the next unit"); "open" is the default.
    A unit a late join skipped stays skipped unless `everything`. Mutates
    `state`. Returns {n, names, label, per: {plan id: [names, n]},
    units: {plan id: [unit ids opened]}}. G2: a unit put off to a later
    morning (`later` in the state) waits for it, unless `everything`."""
    all_cids, names, per, opened_units = set(), [], {}, {}
    for p in plan_list:
        p = mine(p)  # G3, G4: my shift, my skips
        st = state.get(p["id"])
        if not st or not _deck_ok(col, st.get("deck_id")):
            continue
        doc = p["doc"]
        applied = st.setdefault("applied", {})
        sig = _sig(st)
        src = st.setdefault("src", {})
        # 3.3, C2: a follower who studies on a phone opens days early
        when = S.iso(S.d(today) + datetime.timedelta(days=int(p.get("early") or 0))) if mode != "skip" else today
        if (p.get("sched") or S.has_even(doc)) and not everything and mode != "skip":
            pnames, pcids = _spread(col, p, st, when)
            if pnames:
                per[p["id"]] = [pnames, len(pcids)]
                names += pnames
                all_cids |= pcids
            continue
        items = ([(u, "open") for u in P.units(doc)] if everything
                 else P.due_now(doc, applied, when, sig))
        later = st.get("later") or {}
        if not everything:
            items = [(u, how) for u, how in items if str(later.get(u["id"]) or "") <= today]
        for u, _how in items:
            later.pop(u["id"], None)
        if not items:
            continue
        idx = P.DeckIndex(col, st["deck_id"])
        pnames, pcids = [], set()
        for u, how in items:
            if how == "open" and mode != "skip":
                cids = idx.openable(_unit_cids(idx, st, u, doc.get("deck", ""), whole=everything))
                applied[u["id"]] = sig(u)
                src[u["id"]] = P.unit_sources(u, st.get("deck_id"), st.get("swap"))
                if cids:
                    pnames.append(u.get("name") or "?")
                    pcids |= cids
                    opened_units.setdefault(p["id"], []).append(u["id"])
            else:
                applied[u["id"]] = "skip:" + sig(u)
        if pnames:
            per[p["id"]] = [pnames, len(pcids)]
            names += pnames
            all_cids |= pcids
    label = P.step_label(names) if names else ""
    n = P.open_cards(col, all_cids, label) if names else 0
    return {"n": n, "names": names, "label": label, "per": per, "units": opened_units}


def open_one(col, plan, st, uid, today):
    """G1: one date, now, in one undo step; the morning won't open it again.
    {n, names, label}."""
    p = mine(plan)
    u = next((x for x in P.units(p["doc"]) if x["id"] == uid), None)
    if u is None or not st or not _deck_ok(col, st.get("deck_id")):
        return {"n": 0, "names": [], "label": ""}
    idx = P.DeckIndex(col, st["deck_id"])
    cids = idx.openable(_unit_cids(idx, st, u, p["doc"].get("deck", "")))
    st.setdefault("applied", {})[uid] = _sig(st)(u)
    st.setdefault("src", {})[uid] = P.unit_sources(u, st.get("deck_id"), st.get("swap"))
    (st.get("later") or {}).pop(uid, None)
    name = u.get("name") or "?"
    label = P.step_label([name])
    return {"n": P.open_cards(col, cids, label) if cids else 0, "names": [name], "label": label}


def put_off(st, uids, today):
    """G2, Not today: after Anki's undo closed this morning's cards again,
    these units open on tomorrow's morning (they're not applied any more)."""
    tomorrow = S.iso(S.d(today) + datetime.timedelta(days=1))
    later = st.setdefault("later", {})
    for uid in uids:
        (st.get("applied") or {}).pop(uid, None)
        (st.get("src") or {}).pop(uid, None)
        later[uid] = tomorrow
    return st


def _spread(col, p, st, today):
    """3.2, a plan run on my schedule: each unit whose window has started
    opens up to today's quota, the first cards in the deck's order. A unit
    is marked applied once its window is over (all of it open), so from
    then on it behaves as in 3.1: an author's change opens only what it
    adds. Skipped units stay skipped. Returns (names, cids) to open."""
    doc, sched = p["doc"], p.get("sched")
    applied, src, sig = st["applied"], st["src"], _sig(st)
    day = S.d(today)
    shift = S.shift_days(doc, sched)
    idx = P.DeckIndex(col, st["deck_id"])
    names, cids_out = [], set()
    for u in P.units(doc):
        have, s = applied.get(u["id"]), sig(u)
        if isinstance(have, str) and (have == s or have.startswith("skip:")):
            continue
        first, _last = S.window(doc, u, shift)
        if day < first:
            continue
        cids = _unit_cids(idx, st, u, doc.get("deck", ""))
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
            src[u["id"]] = P.unit_sources(u, st.get("deck_id"), st.get("swap"))
        if chosen:
            names.append(u.get("name") or "?")
            cids_out |= set(chosen)
    return names, cids_out


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
        cids |= _unit_cids(idx, st, u, plan["doc"].get("deck", ""))
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
    totals, seen_before, new_today = {}, {}, 0
    new_by_day = {}
    for uid, cids in matches.items():
        totals[uid] = len(cids)
        seen = idx.counts(cids)[1]
        today_n = sum(1 for c in cids if first_seen.get(c) == 0)
        new_today += today_n
        seen_before[uid] = seen - today_n
        for c in cids:
            ago = first_seen.get(c)
            if ago is not None:
                k = S.iso(day - datetime.timedelta(days=ago))
                new_by_day[k] = new_by_day.get(k, 0) + 1
    catch = (st.get("catch") or {}).get("mode")
    view = S.today_view(doc, sched, totals, seen_before, new_today, day, catch=catch)
    shares = {}
    for i in range(1, 15):
        x = day - datetime.timedelta(days=i)
        shares[S.iso(x)] = sum(S.share(doc, u, sched, totals.get(u["id"], 0), x, shift) for u in P.units(doc))
    missed = S.missed_study_days(doc, sched, day, new_by_day, shares)
    asked = (st.get("catch") or {}).get("day") or ""
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


def to_send(plan_list, prog):
    """What the sync carries: progress on the plans I share it on, at most 50."""
    share = {p["id"] for p in plan_list if p.get("share")}
    return dict([(pid, units) for pid, units in sorted(prog.items()) if pid in share and units][:50])


def _short_day(iso, today):
    """"Mon" within the coming week, else "Mon 26 Oct"."""
    try:
        d, t = datetime.date.fromisoformat(iso), datetime.date.fromisoformat(today)
    except ValueError:
        return str(iso)
    return f"{d:%a}" if 0 <= (d - t).days < 7 else P.fmt_day(iso)


def card_view(plan, st, prog, today, opened=None, undo_ok=False, session=None, week_offset=0):
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
    # 3.5.0, the Plans tab: today's topics, the next one, and a week of the calendar
    today_names = [str(u.get("name") or "?") for u in P.units(doc) if u.get("opens") == today]
    if not today_names and now_id and any(u["id"] == now_id and u.get("due") and u["due"] >= today for u in open_units):
        today_names = [str(u.get("name") or "?") for u in open_units if u["id"] == now_id]
    skipped_units = [dict(u, opens=P._later(u["opens"], shift)) if shift else u
                     for u in P.units(_plan_doc(plan)) if u["id"] in skipped]
    week = P.week_view(doc, prog, today, P.week_start(today, week_offset), skipped=skipped_units)
    nxt_view = ({"name": str(nxt.get("name") or "?"), "uid": nxt["id"], "day": P.weekday_or_day(nxt["opens"], today),
                 "n": P.unit_total(nxt)} if nxt else None)
    change = None
    if st and st.get("snapshot") is not None and st.get("seen_version") != plan.get("version"):
        change = P.change_note(plan.get("ownerName"), st["snapshot"], _plan_doc(plan))
    return {"id": plan["id"], "title": P.plan_title(plan), "sub": sub, "rows": rows,
            "opened": ({"names": opened[0], "n": opened[1], "undo": bool(undo_ok)}
                       if opened and opened[1] else None),
            "lines": [] if no_deck or plan.get("paused") else P.ahead_behind(doc, prog or {}, today),
            "change": change, "no_deck": no_deck, "paused": bool(plan.get("paused")),
            "session": None if no_deck or plan.get("paused") else session,
            "today": P.fmt_day(today), "sched": bool(plan.get("sched")),
            "early": int(plan.get("early") or 0),
            "prep": prep,
            "fallback_ok": bool(((_pcfg().get("fallback_ok") or {}) if mw else {}).get(plan["id"])),
            "put_off": put_off, "waiting": waiting,
            "today_names": today_names, "next": nxt_view, "week": week, "week_offset": int(week_offset),
            "catch": {"extra": int(catch.get("extra") or 0), "until": _short_day(catch["until"], today)} if catch else None}


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
        c["plans_opened"] = {"day": today, "label": res["label"], "per": res["per"], "units": res.get("units") or {}}
    _psave(c)
    if res["n"]:
        _after_change()
        if toast:
            tooltip(opened_line(res), period=5000)
    refresh_progress()
    return res


def maybe_morning(awaiting_sync, fresh=False, toast=True):
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
        if fresh:
            ids = {p["id"] for p in plan_list}
            gone = [pid for pid in state if pid not in ids]
            for pid in gone:
                state.pop(pid, None)  # stopped, or taken down: nothing is suspended
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
        today = _today()
        if awaiting_sync or (c.get("plans_day") == today and not fresh):
            return None
        new_here = []
        for p in plan_list:
            if p["id"] not in state:
                st = new_state(mw.col, p)  # followed on another computer, or on the site
                if st:
                    state[p["id"]] = skip_past(st, p, today)
                    new_here.append(p["id"])
        c["plans"] = state
        c["plans_day"] = today
        _psave(c)
        line = opened_line(_open_now([p for p in plan_list if not p.get("paused")], toast=toast))
        apply_catch()  # G5
        backs = [p["id"] for p in plan_list if p.get("paused") and p.get("until") and str(p["until"]) < today]
        if backs:
            # G4: a pause whose last day has passed asks its question once, here
            from aqt.qt import QTimer
            for pid in backs:
                QTimer.singleShot(0, lambda pid=pid: back(pid))
        built = build_checks([p for p in plan_list if not p.get("paused")])  # 3.2
        if built and toast:
            tooltip(f"Due Crew built {html.escape(built[0])}.", period=5000)
        if new_here:
            # a plan followed on the site asks Follow's question here, once
            from aqt.qt import QTimer
            QTimer.singleShot(0, lambda: offer_hold(new_here))
        return line
    except Exception:
        traceback.print_exc()
        return None


def offer_hold(pids, ask=None):
    """3.4 review, H1: a plan first seen on this computer (followed on the
    site, or elsewhere) asks what Follow asks: hold back its later dates'
    cards until their day? Only when there are some (a computer that held
    them already has them suspended, which AnkiWeb brought here)."""
    if not mw.col:
        return
    if ask is None:
        from .ui import confirm

        def ask(name, n):
            return confirm(mw, "Hold back later cards",
                           f"{name} is new on this computer. Hold back {n:,} card{'s' if n != 1 else ''} "
                           "of its later dates until their day?\n\nThey open on their day. "
                           "One undo step; stopping the plan opens them again.", "Hold back")
    c = _pcfg()
    state = _state_cfg(c)
    changed = False
    for pid in pids:
        p = next((x for x in followed() if x["id"] == pid), None)
        st = state.get(pid)
        if not p or not st or not _deck_ok(mw.col, st.get("deck_id")):
            continue
        cids = P.holdable(P.DeckIndex(mw.col, st["deck_id"]), p["doc"], _today(), _swap(st))
        if not cids or not ask(p.get("name") or "The plan", len(cids)):
            continue
        n = P.hold_cards(mw.col, cids, f"Due Crew: hold back {p.get('name') or 'plan'}")
        if n:
            st["held"] = sorted(set(st.get("held") or []) | {int(x) for x in cids})
            changed = True
    if changed:
        c["plans"] = state
        _psave(c)
        _after_change()
        refresh_progress()
        app.swap(cfg())


def send_ids():
    """3.3, C5: main thread, on the day's first refresh. For each plan I
    write whose deck I have (by its name), the note ids behind each date's
    tags and subdecks go up, one request a plan, only when they changed:
    a follower whose AnKing renamed a tag still gets the date. 3.4, D1:
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
            refs = P.id_refs(idx, mw.col, a["doc"])  # 3.6.5: pasted ids as cards anyone's copy can find
            h = hashlib.sha1(json.dumps([units, counts, refs], sort_keys=True).encode()).hexdigest()[:16]
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


CHECK_CARDS = 60
CHECK_DAYS = 3  # a checkpoint missed by more than this many mornings isn't built late


def checks_due(doc, st, sched, today):
    """Checkpoints and (3.3) review days that are today on my dates (or up
    to CHECK_DAYS ago) and not built here yet: [(key, name, [units], n)]."""
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
        if key in done or not a or not b or not due(r["day"]):
            continue
        lo, hi = sorted([a["opens"], b["opens"]])
        span = [u for u in us if lo <= u["opens"] <= hi]
        name = f"Review · {a.get('name') or '?'}" + (f" – {b.get('name') or '?'}" if a is not b else "")
        out.append((key, name, span, REVIEW_CARDS))
    return out


REVIEW_CARDS = 200  # 3.3, C4: a review day's deck


def study_date(pid, uid):
    """3.3, C4: Study on a date's row: Anki's filtered deck of that date's
    cards I've seen, most-missed first, and straight into it."""
    p = next((x for x in followed() if x["id"] == pid), None)
    st = _state_cfg().get(pid)
    if not p or not st or not mw.col or not _deck_ok(mw.col, st.get("deck_id")):
        return
    u = next((x for x in P.units(p["doc"]) if x["id"] == uid), None)
    if not u:
        return
    idx = P.DeckIndex(mw.col, st["deck_id"])
    cids = check_cards(mw.col, idx, idx.match(u, _swap(st), p["doc"].get("deck", "")), 9999)
    if not cids:
        tooltip("Nothing from this date studied yet.")
        return
    name = _deck_name(f"Due Crew · {u.get('name') or 'date'}")
    if _filtered(mw.col, name, cids):
        _after_change()
        did = mw.col.decks.id_for_name(name)
        if did:
            mw.col.decks.select(did)
            mw.moveToState("overview")


def _deck_name(name):
    """A filtered deck's name from a date's: "::" in it would make a parent deck."""
    return " ".join(str(name).replace("::", ": ").split())[:120]


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


def _filtered(col, name, cids):
    """Anki's own filtered deck over these cards, most lapses first; built
    (or rebuilt) under `name`. Returns True when it took."""
    try:
        did = col.decks.id_for_name(name) or 0
        deck = col.sched.get_or_create_filtered_deck(deck_id=did)
        deck.name = name
        term = deck.config.search_terms[0]
        term.search = "cid:" + ",".join(str(c) for c in cids)
        term.limit = len(cids)
        term.order = 4  # most lapses
        deck.config.reschedule = True
        col.sched.add_or_update_filtered_deck(deck)
        return True
    except Exception:
        traceback.print_exc()
        return False


def build_checks(plan_list):
    """Main thread, in the morning: each checkpoint due today becomes a
    filtered deck, "Checkpoint · Cardio". Its score stays on this computer."""
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
                pool |= idx.match(u, _swap(st), p["doc"].get("deck", ""))
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


def refresh_progress():
    """Main thread: my numbers per unit, for the card and the next sync, and
    (3.2) today's session for the plans on my schedule."""
    if not mw.col:
        return {}
    idxs = {}  # each deck read once for both
    try:
        prog = progress(mw.col, followed(), _state_cfg(), idxs)
    except Exception:
        traceback.print_exc()
        return {}
    _state["plan_progress"] = prog
    try:
        _state["plan_session"] = sessions(mw.col, followed(), _state_cfg(), _today(), idxs)
        _note_recap(_state["plan_session"])
    except Exception:
        traceback.print_exc()
    return prog


def _due_in(col, did):
    """Reviews (and learning cards) due now in a deck and its subdecks, when this Anki can say."""
    try:
        node = col.sched.deck_due_tree(int(did))
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


def sessions(col, plan_list, state, today, idxs=None):
    """{plan id: session_view} for the plans on my schedule, on this computer."""
    from .stats.queries import StatsQueries
    q = StatsQueries(col)
    todo = [(p, state.get(p["id"])) for p in plan_list if not p.get("paused")]
    todo = [(p, st) for p, st in todo if st and _deck_ok(col, st.get("deck_id"))]
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


def _undo_ok(label):
    try:
        return bool(label) and mw.col.undo_status().undo == label
    except Exception:
        return False


def board_view(c):
    """{cards, offers} for the board, from cache. Main thread (one undo-queue
    look; no collection reads)."""
    plan_list = followed()
    pc = _pcfg()
    state = _state_cfg(pc)
    today = _state["labels"][0] if _state["labels"] else ""
    if not today:
        return {"cards": [], "offers": []}
    opened = pc.get("plans_opened") if isinstance(pc.get("plans_opened"), dict) else {}
    fresh_open = opened.get("day") == today
    undo = fresh_open and _undo_ok(opened.get("label"))
    prog = _state.get("plan_progress") or {}
    here = lambda st: st if st and mw.col and _deck_ok(mw.col, st.get("deck_id")) else None
    sess = _state.get("plan_session") or {}
    cards = [card_view(p, here(state.get(p["id"])), prog.get(p["id"]), today,
                       opened=(opened.get("per") or {}).get(p["id"]) if fresh_open else None,
                       undo_ok=undo, session=sess.get(p["id"]),
                       week_offset=(_state.get("plan_week") or {}).get(p["id"], 0))
             for p in plan_list]
    from .squads import _my_squads
    names = {sq["id"]: sq.get("name") or "" for sq in _my_squads(c)}
    offers = offers_view(client().session.get("plan_offers"), names, {p["id"] for p in plan_list},
                         set(pc.get("plan_offers_dismissed") or []))
    return {"cards": cards, "offers": offers}


# ---- board commands ----

def on_message(cmd, parts):
    """duecrew:plan* from the board. True when handled."""
    arg = parts[2] if len(parts) > 2 else ""
    if cmd == "planundo":
        undo_morning()
    elif cmd == "plannottoday":
        undo_morning(put_off_too=True)
    elif cmd == "plannow" and arg and len(parts) > 3:
        open_date(arg, parts[3])
    elif cmd == "planputback" and arg:
        open_put_off(arg)
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
        step = parts[3]
        weeks[arg] = 0 if step == "0" else max(-26, min(26, int(weeks.get(arg, 0)) + (1 if step == "next" else -1)))
        app.swap(cfg())
    elif cmd == "planshift" and arg:
        set_shift(arg)
    elif cmd == "plansite" and arg and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", arg):
        open_site(f"/plans/{arg}")  # an id, nothing else: the link carries a sign-in token
    elif cmd == "planlibrary":
        open_site("/library")
    elif cmd == "planmake":
        open_make()
    elif cmd == "planresume" and arg:
        p = next((x for x in followed() if x["id"] == arg), None)
        if p:
            back(arg) if p.get("since") else set_paused(arg, False)
    elif cmd == "planmenu" and arg:
        plan_menu(arg)
    elif cmd == "planok" and arg:
        seen_change(arg)
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
    else:
        return False
    return True


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
        # Not today: they open on tomorrow's
        pc = _pcfg()
        if put_off_too:
            state = _state_cfg(pc)
            for pid, uids in (opened.get("units") or {}).items():
                if pid in state:
                    put_off(state[pid], uids, _today())
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


def open_date(pid, uid):
    """G1: one date, now."""
    p = next((x for x in followed() if x["id"] == pid), None)
    c = _pcfg()
    state = _state_cfg(c)
    st = state.get(pid)
    if p is None or not st or not mw.col:
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
    n_units, _n_cards = waiting(mw.col, mine(p), st, today) if st else (0, 0)
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
        base = _base_limit(col, st["deck_id"])
        if base is None:
            continue
        try:
            deck = col.decks.get(int(st["deck_id"]))
            deck["newLimitToday"] = {"limit": base + int(c.get("extra") or 0), "today": int(col.sched.today)}
            col.decks.save(deck)
        except Exception:
            traceback.print_exc()


def catch_menu(pid):
    """G5: catch up over 3, 5 or 7 days."""
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
    menu.exec(QCursor.pos())


def start_catch(pid, days, extra):
    c = _pcfg()
    state = _state_cfg(c)
    st = state.get(pid)
    if not st:
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
    if mw.col and _deck_ok(mw.col, st.get("deck_id")):
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


def plan_menu(pid):
    p = next((p for p in followed() if p["id"] == pid), None)
    if p is None:
        return
    from aqt.qt import QCursor, QMenu
    menu = QMenu(mw)
    if p.get("sched"):  # 3.3: new follows do the plan's days; a 3.2 schedule can still change or go
        menu.addAction("My schedule…").triggered.connect(lambda: open_schedule(pid))
    menu.addAction("Open everything now").triggered.connect(lambda: open_everything(pid))
    early = menu.addMenu("Open early")  # 3.3, C2: for studying on a phone
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
    state[pid]["catch"] = {"mode": mode, "day": _today()}
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
            state[pid]["catch"] = {"mode": "leave", "day": _today()}
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
    from .ui import ask_item
    choices = P.deck_choices(mw.col)
    if not choices:
        return
    c = _pcfg()
    state = _state_cfg(c)
    st = state.get(pid)
    best, _swap_guess = P.best_deck(mw.col, p["doc"], choices)
    current = st.get("deck_id") if st else best
    names = [n for _d, n in choices]
    at = next((i for i, (d, _n) in enumerate(choices) if d == current), 0)
    # plain text: the plan's name is the author's
    name, ok = ask_item(mw, "Change deck", f"Run {p.get('name') or 'the plan'} on", names, at)
    if not ok:
        return
    did = next(d for d, n in choices if n == name)
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
    from .ui import confirm
    if not confirm(mw, "Stop following",
                   f"Stop following {p.get('name') or 'this plan'}?\n\n"
                   "Cards already open stay open"
                   + (", and the ones it held back open too" if (_state_cfg().get(pid) or {}).get("held") else "")
                   + ". The crew stops seeing your progress on this plan.", "Stop"):
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
        state.pop(pid, None)
        pc["plans"] = state
        _psave(pc)
        _state.get("plan_progress", {}).pop(pid, None)
        app.swap(cfg())

    _bg(lambda: cl.unfollow_plan(pid), done)


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
    `deck_id`; late is "open" (open what has opened) or "skip". Following
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
    if hold and mw.col:
        idx = P.DeckIndex(mw.col, deck_id)
        cids = P.holdable(idx, plan["doc"], _today(), swap)
        n = P.hold_cards(mw.col, cids, f"Due Crew: hold back {plan.get('name') or 'plan'}")
        if n:
            state[plan["id"]]["held"] = sorted(set(state[plan["id"]].get("held") or []) | set(int(c) for c in cids))
            _after_change()
    c["plans"] = state
    _psave(c)

    def finish():
        c2 = cfg()
        c2["period"] = "plans"  # 3.3: where it lives now
        save_cfg(c2)
        fresh = next((x for x in followed() if x["id"] == plan["id"]), plan)
        res = _open_now([fresh], mode=late)
        if res is not None and not res["n"]:
            tooltip(f"Following {html.escape(plan.get('name') or 'the plan')}.")
        app.swap(cfg())
    finish()  # 3.3: the plan's days are the schedule; nothing to ask


def open_make():
    if not _signed_in():
        return
    if not mw.col:
        return
    from .ui.plan_dialog import MakePlanDialog
    MakePlanDialog(mw, client(), mw.col, site_base()).exec()


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
    """gui_hooks.browser_will_show_context_menu: single cards onto a date."""
    if not client().signed_in:
        return
    menu.addSeparator()
    action = menu.addAction("Due Crew: add to a plan…")
    action.triggered.connect(lambda: add_to_plan(browser))


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
