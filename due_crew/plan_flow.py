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
import html
import json
import os
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


def followed():
    """The plans I follow, as the last day's-first refresh brought them."""
    return [p for p in client().session.get("plans") or [] if isinstance(p, dict) and p.get("id")]


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
            "seen_version": plan.get("version") or 0, "snapshot": P.snapshot(plan["doc"])}


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
    did, swap, tags, decks, cards = was
    if did != st.get("deck_id") or list(swap or []) != list(st.get("swap") or []):
        return cids  # another deck now: what had opened opens there too
    old = idx.match({"tags": tags, "decks": decks, "cards": cards}, _swap(st), deck)
    return cids - old


def run(col, plan_list, state, today, mode=None, everything=False):
    """Open what's due (or, with `everything`, every unit) for these plans,
    in one undo step. mode "skip" marks due units applied without opening
    them (joining late, "Start from the next unit"); "open" is the default.
    A unit a late join skipped stays skipped unless `everything`. Mutates
    `state`. Returns {n, names, label, per: {plan id: [names, n]}}."""
    all_cids, names, per = set(), [], {}
    for p in plan_list:
        st = state.get(p["id"])
        if not st or not _deck_ok(col, st.get("deck_id")):
            continue
        doc = p["doc"]
        applied = st.setdefault("applied", {})
        sig = _sig(st)
        src = st.setdefault("src", {})
        if p.get("sched") and not everything and mode != "skip":
            pnames, pcids = _spread(col, p, st, today)
            if pnames:
                per[p["id"]] = [pnames, len(pcids)]
                names += pnames
                all_cids |= pcids
            continue
        items = ([(u, "open") for u in P.units(doc)] if everything
                 else P.due_now(doc, applied, today, sig))
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
            else:
                applied[u["id"]] = "skip:" + sig(u)
        if pnames:
            per[p["id"]] = [pnames, len(pcids)]
            names += pnames
            all_cids |= pcids
    label = P.step_label(names) if names else ""
    n = P.open_cards(col, all_cids, label) if names else 0
    return {"n": n, "names": names, "label": label, "per": per}


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


def progress(col, plan_list, state):
    """{plan id: {unit id: [opened, seen, total]}} for the plans that run here."""
    out = {}
    for p in plan_list:
        st = state.get(p["id"])
        if not st or not _deck_ok(col, st.get("deck_id")):
            continue
        idx = P.DeckIndex(col, st["deck_id"])
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
    sched = plan.get("sched")
    if not sched or not st:
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
    if missed and view["behind"] and S.iso(missed[0]) > asked:
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
        if not unit or not isinstance(c, dict):
            continue
        firsts = [(answered or {}).get(cid) for cid in c.get("cids") or []]
        done = [f for f in firsts if f]
        checks.append({"name": unit.get("name") or "?", "n": len(c.get("cids") or []), "answered": len(done),
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


def card_view(plan, st, prog, today, opened=None, undo_ok=False, session=None):
    """What board._plans_html draws for one plan. Strings are raw here;
    the board escapes them."""
    doc = plan["doc"]
    week, weeks = P.span_weeks(doc, today)
    us = P.units(doc)
    if plan.get("paused"):
        sub = "paused"
    elif week == 0 and us:
        sub = f"starts {P.fmt_day(us[0]['opens'])}"
    else:
        sub = f"week {week} of {weeks}"
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
        n = f"{done:,} of {followers:,}"
        if u["id"] == now_id and u.get("due") and u["due"] >= today:
            n += f" · due {_short_day(u['due'], today)}"
        rows.append({"name": u.get("name") or "?", "state": "now" if u["id"] == now_id else "open",
                     "seen": [s, t], "crew": [done, followers], "n": n, "missing": not t})
    nxt = P.next_unit(doc, today)
    if nxt:
        rows.append({"name": nxt.get("name") or "?", "state": "later", "seen": None, "crew": None,
                     "n": f"opens {P.fmt_day(nxt['opens'])}", "missing": False})
    no_deck = not st
    change = None
    if st and st.get("snapshot") is not None and st.get("seen_version") != plan.get("version"):
        change = P.change_note(plan.get("ownerName"), st["snapshot"], doc)
    return {"id": plan["id"], "title": P.plan_title(plan), "sub": sub, "rows": rows,
            "opened": ({"names": opened[0], "n": opened[1], "undo": bool(undo_ok)}
                       if opened and opened[1] else None),
            "lines": [] if no_deck or plan.get("paused") else P.ahead_behind(doc, prog or {}, today),
            "change": change, "no_deck": no_deck, "paused": bool(plan.get("paused")),
            "session": None if no_deck or plan.get("paused") else session,
            "today": P.fmt_day(today), "sched": bool(plan.get("sched"))}


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
        c["plans_opened"] = {"day": today, "label": res["label"], "per": res["per"]}
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
                        and P.change_note(p.get("ownerName"), st["snapshot"], p["doc"]) is None:
                    # a change with nothing to say (cards added, a name kept): noted quietly
                    st.update(seen_version=p.get("version"), snapshot=P.snapshot(p["doc"]))
                    changed = True
            if changed:
                c["plans"] = state
                _psave(c)
        today = _today()
        if awaiting_sync or (c.get("plans_day") == today and not fresh):
            return None
        for p in plan_list:
            if p["id"] not in state:
                st = new_state(mw.col, p)  # followed on another computer
                if st:
                    state[p["id"]] = skip_past(st, p, today)
        c["plans"] = state
        c["plans_day"] = today
        _psave(c)
        line = opened_line(_open_now([p for p in plan_list if not p.get("paused")], toast=toast))
        built = build_checks([p for p in plan_list if not p.get("paused")])  # 3.2
        if built and toast:
            tooltip(f"Due Crew built {html.escape(built[0])}.", period=5000)
        return line
    except Exception:
        traceback.print_exc()
        return None


CHECK_CARDS = 60
CHECK_DAYS = 3  # a checkpoint missed by more than this many mornings isn't built late


def checks_due(doc, st, sched, today):
    """Units whose checkpoint is today on my dates (or up to CHECK_DAYS ago)
    and not built here yet."""
    day = S.d(today)
    shift = S.shift_days(doc, sched)
    done = st.get("checks") or {}
    out = []
    for u in P.units(doc):
        if not u.get("check") or u["id"] in done:
            continue
        when = S.d(u["check"]) + datetime.timedelta(days=shift)
        if 0 <= (day - when).days <= CHECK_DAYS:
            out.append(u)
    return out


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
        for u in due:
            cids = check_cards(mw.col, idx, idx.match(u, _swap(st), p["doc"].get("deck", "")))
            name = f"Checkpoint · {u.get('name') or 'unit'}"
            ok = bool(cids) and _filtered(mw.col, name, cids)
            st.setdefault("checks", {})[u["id"]] = {"day": today, "at": int(_time.time() * 1000),
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
    try:
        prog = progress(mw.col, followed(), _state_cfg())
    except Exception:
        traceback.print_exc()
        return {}
    _state["plan_progress"] = prog
    try:
        _state["plan_session"] = sessions(mw.col, followed(), _state_cfg(), _today())
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


def sessions(col, plan_list, state, today):
    """{plan id: session_view} for the plans on my schedule, on this computer."""
    from .stats.queries import StatsQueries
    q = StatsQueries(col)
    todo = [(p, state.get(p["id"])) for p in plan_list if p.get("sched") and not p.get("paused")]
    todo = [(p, st) for p, st in todo if st and _deck_ok(col, st.get("deck_id"))]
    if not todo:
        return {}
    first = q.first_seen(15)
    pace = q.pace()
    out = {}
    for p, st in todo:
        idx = P.DeckIndex(col, st["deck_id"])
        out[p["id"]] = session_view(p, st, idx, first, today, pace, _due_in(col, st["deck_id"]),
                                    _answered(col, st.get("checks") or {}))
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
                       undo_ok=undo, session=sess.get(p["id"]))
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


def undo_morning():
    """The board's Undo: Anki's own undo, only while the step is its latest.
    The card and the numbers follow once the undo has happened, and only
    if it did."""
    opened = _pcfg().get("plans_opened") or {}
    if not _undo_ok(opened.get("label")):
        tooltip("Anki has done something since. Use Edit › Undo.")
        app.swap(cfg())
        return

    def done(_out=None):
        # the units stay marked as applied: the next morning won't open them again
        pc = _pcfg()
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


def seen_change(pid):
    p = next((p for p in followed() if p["id"] == pid), None)
    c = _pcfg()
    state = _state_cfg(c)
    if p and pid in state:
        state[pid].update(seen_version=p.get("version"), snapshot=P.snapshot(p["doc"]))
        c["plans"] = state
        _psave(c)
    app.swap(cfg())


def plan_menu(pid):
    p = next((p for p in followed() if p["id"] == pid), None)
    if p is None:
        return
    from aqt.qt import QCursor, QMenu
    menu = QMenu(mw)
    menu.addAction("My schedule…").triggered.connect(lambda: open_schedule(pid))
    menu.addAction("Open everything now").triggered.connect(lambda: open_everything(pid))
    menu.addAction("Change deck…").triggered.connect(lambda: change_deck(pid))
    menu.addSeparator()
    menu.addAction("Resume" if p.get("paused") else "Pause").triggered.connect(
        lambda: set_paused(pid, not p.get("paused")))
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
                   "Nothing gets suspended. Cards already open stay open, and the crew "
                   "stops seeing your progress on this plan.", "Stop"):
        return
    cl = client()

    def done(ok):
        if not ok:
            tooltip("Couldn't reach Due Crew. Check your connection.")
            return
        pc = _pcfg()
        state = _state_cfg(pc)
        state.pop(pid, None)
        pc["plans"] = state
        _psave(pc)
        _state.get("plan_progress", {}).pop(pid, None)
        app.swap(cfg())

    _bg(lambda: cl.unfollow_plan(pid), done)


# ---- following ----

def open_follow(code=""):
    if not client().signed_in:
        tooltip("Sign in to Due Crew first.")
        return
    if not mw.col:
        return
    from .ui.follow_dialog import FollowDialog
    dlg = FollowDialog(mw, client(), mw.col, code=code, today=_today(), on_followed=on_followed)
    dlg.exec()


def on_followed(plan, deck_id, swap, late):
    """Main thread, after POST /plans/follow: this computer runs it on
    `deck_id`; late is "open" (open what has opened) or "skip". Following
    again keeps what this computer already applied: only the deck changes."""
    cl = client()
    cl.remember_plan(plan)
    c = _pcfg()
    state = _state_cfg(c)
    st = state.get(plan["id"])
    if st:
        st.update(deck_id=int(deck_id), swap=list(swap) if swap else None)
    else:
        state[plan["id"]] = new_state(mw.col, plan, deck_id, swap)
    c["plans"] = state
    _psave(c)

    def finish():
        fresh = next((x for x in followed() if x["id"] == plan["id"]), plan)
        res = _open_now([fresh], mode=late)
        if res is not None and not res["n"]:
            tooltip(f"Following {html.escape(plan.get('name') or 'the plan')}.")
        app.swap(cfg())
    if plan.get("sched") or late == "skip":
        finish()
    else:
        open_schedule(plan["id"], then=finish)  # 3.2: my days and time, before anything opens


def open_make():
    if not client().signed_in:
        tooltip("Sign in to Due Crew first.")
        return
    if not mw.col:
        return
    from .ui.plan_dialog import MakePlanDialog
    MakePlanDialog(mw, client(), mw.col, site_base()).exec()


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
    table = getattr(browser, "table", None)
    try:
        notes_mode = bool(table is not None and hasattr(table, "is_notes_mode") and table.is_notes_mode())
    except Exception:
        notes_mode = False
    if notes_mode:
        # a note's row is all its cards; a plan takes the exact cards picked
        tooltip("Switch the browser to Cards to add single cards to a plan.")
        return
    try:
        cids = browser.selected_cards()
    except AttributeError:
        cids = browser.selectedCards()
    if not cids or not mw.col:
        return
    refs = P.card_refs(mw.col, cids)  # which cards, never their text
    from .ui.add_cards_dialog import AddCardsDialog
    def added(plan, n):
        tooltip(f"Added {n:,} card{'s' if n != 1 else ''} to {html.escape(plan.get('name') or 'the plan')}.")

    AddCardsDialog(browser, client(), refs, _today(), on_added=added).exec()
