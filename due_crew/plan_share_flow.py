"""3.10.2: plan_share.py's glue. Main thread (the config, plans.json, the collection)."""

from aqt import mw

from . import app, plan_share
from .app import cfg, save_cfg
from .errs import oops
from .words import t as _t

NOTE_KEY = "plan_share_note"   # this computer's: the decks a running plan just shared, till Got it


def _upload(c):
    """The decks I share, sent as Crew › Decks sends them."""
    try:
        from .stats.decks import gather_shared_decks
        from . import glue
        glue.refresh_board(shared_decks=gather_shared_decks(mw.col, c))
    except Exception:
        oops()


def _name(did):
    try:
        return str(mw.col.decks.name(int(did)))
    except Exception:
        return ""


def sync(new=None):
    """Share the deck of each plan not looked at yet. new: the plan just followed (the Follow window said so; no
    note for it). Returns the deck ids it shared."""
    if mw.col is None:
        return []
    try:
        from . import plan_flow as pf
        pc = pf._pcfg()
        state = pf._state_cfg(pc)
        c = cfg()
        add, mark = plan_share.due(state, c.get("shared_decks"), lambda d: pf._deck_ok(mw.col, d))
        if not add and not mark:
            return []
        for pid, how in mark:
            state[pid]["share"] = how
        for pid, _did in add:
            state[pid]["share"] = plan_share.ON
        pc["plans"] = state
        pf._psave(pc)
        if not add:
            return []
        c["shared_decks"] = list(c.get("shared_decks") or []) + [did for _pid, did in add]
        c["shared_decks_set"] = True
        told = [n for n in (_name(did) for pid, did in add if pid != new) if n]
        if told:
            c[NOTE_KEY] = list(dict.fromkeys(list(c.get(NOTE_KEY) or []) + told))[:6]
        save_cfg(c)
        _upload(c)
        return [did for _pid, did in add]
    except Exception:
        oops()
        return []


def told():
    c = cfg()
    if c.pop(NOTE_KEY, None) is not None:
        save_cfg(c)


def stopped(st):
    """A plan was stopped: if it shared its deck and it's still shared, ask once whether to keep sharing it."""
    try:
        c = cfg()
        if not plan_share.asks(st, c.get("shared_decks")):
            return
        did = int(st["deck_id"])
        name = _name(did) or _t("its deck")

        def stop():
            c2 = cfg()
            c2["shared_decks"] = plan_share.without(c2.get("shared_decks"), did)
            c2["shared_decks_set"] = True
            save_cfg(c2)
            _upload(c2)
            app.swap(cfg())

        from . import sheets
        sheets.confirm(_t("Keep sharing?"),
                       _t("{deck} is shared with your crew because of this plan: they see your progress on it and which cards you know. Keep sharing it?", deck=name),
                       _t("Keep sharing"), lambda: None, no=stop, no_label=_t("Stop sharing"))
    except Exception:
        oops()
