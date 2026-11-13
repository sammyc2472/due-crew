"""Plans, the glue: what this computer keeps (plans.json), and the small helpers every part leans on."""

import json
import os

from aqt import mw
from aqt.utils import tooltip

from .. import app
from .. import plans as P
from ..app import cfg
from ..app import client
from ..app import save_cfg


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
    from .. import store
    if not store.write_json(os.path.join(_files(), "plans.json"), data):
        # 3.9.9 (the plans review): this went by unsaid, and a plan's state that isn't kept is a morning
        # that opens again; counted for the field's sheet (a code, never the path)
        from .. import errs
        errs.count("file:plans")


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
    from ..stats.queries import StatsQueries
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
