"""3.9.10, the scrapbook's glue (scrapbook.py is the pure part): its file,
what puts things in it, and the view the board draws.

scrapbook.json sits beside wrap.json in this Anki profile's files, never
sent. More than one account can sign in on a profile, so it keeps each
account's own ({"by": {uid: {"items": [...], "cheers": {"2026-11": n}}}})
and shows the signed-in one's; signing out leaves it (a keepsake isn't
lost by signing out, as a polaroid on the fridge was). Main thread."""

import datetime
import os

from aqt import mw

from . import scrapbook as S
from . import store, wrap
from .app import _state, cfg, client
from .errs import oops

_BOOK = {"path": None, "data": None, "disk": None}


def _path():
    return os.path.join(wrap._profile_files(), "scrapbook.json")  # where wrap.json is


def _data():
    return store.load(_BOOK, _path(), ok=lambda d: isinstance(d.get("by"), dict), empty=lambda: {"by": {}})


def _save():
    """Written whole, then swapped in, and only when it says something the file doesn't (store.py)."""
    store.save(_BOOK)


def _uid(uid=None):
    return str(uid or client().user_id or "")


def _mine(uid=None):
    """The signed-in account's part of the file (made when it isn't there), or None signed out."""
    u = _uid(uid)
    if not u:
        return None
    me = _data()["by"].setdefault(u, {})
    if not isinstance(me, dict):
        me = _data()["by"][u] = {}
    return me


def _read(uid=None):
    """The account's part as it is (never made by a look)."""
    me = _data()["by"].get(_uid(uid))
    return me if isinstance(me, dict) else {}


def items(uid=None):
    return S.clean(_read(uid).get("items"))


def keep(item, uid=None):
    """One more keepsake (once). True when it went in."""
    me = _mine(uid)
    if me is None or S.clean_one(item) is None:
        return False
    before = S.clean(me.get("items"))
    after = S.add(before, item)
    if len(after) == len(before) and {S.key(x) for x in after} == {S.key(x) for x in before}:
        return False
    me["items"] = after
    _save()
    return True


def forget(k, uid=None):
    """Delete one for good. True when it was there."""
    me = _mine(uid)
    if me is None:
        return False
    before = S.clean(me.get("items"))
    after = S.drop(before, k)
    if len(after) == len(before):
        return False
    me["items"] = after
    _save()
    return True


def empty(uid=None):
    """Empty the scrapbook: every keepsake and count of this account's."""
    u = _uid(uid)
    if u and _data()["by"].pop(u, None) is not None:
        _save()


def find(k, uid=None):
    return next((x for x in items(uid) if S.key(x) == k), None)


# ---- what puts things in it ----

def _today():
    try:
        return str(_state["labels"][0]) if _state.get("labels") else datetime.date.today().isoformat()
    except Exception:
        return datetime.date.today().isoformat()


def polaroid(item, uid=None):
    """A polaroid off the fridge: taken down, pushed out by a newer one, or the account signing out."""
    return keep(S.from_fridge(item), uid)


def polaroid_back(item, uid=None):
    """Undo of a take-down: it's on the fridge again, and out of here."""
    return forget(S.key(S.from_fridge(item)), uid)


def cheers_in(cheers, uid=None):
    """Cheers as they land: each is counted in its month; one that came with
    words (and no drawing: that's a polaroid) is kept as a slip."""
    me = _mine(uid)
    if me is None or not cheers:
        return
    tally = me.setdefault("cheers", {})
    if not isinstance(tally, dict):
        tally = me["cheers"] = {}
    changed = False
    for ch in cheers:
        at = str(ch.get("at") or "") or _today()
        ym = (at[:7] if len(at) >= 7 else _today()[:7])
        tally[ym] = int(tally.get(ym) or 0) + 1
        changed = True
        if ch.get("note") and not ch.get("doodle"):
            me["items"] = S.add(me.get("items"), {"k": "cheer", "from": ch.get("from"), "name": ch.get("name"), "at": at,
                                                  "n": ch.get("note"), "e": ch.get("emoji")})
    if changed:
        _save()


def luck_shown(lines, day=None, uid=None):
    """My exam morning's card has shown: each line my crew left is kept."""
    try:
        for x in lines or []:
            keep({"k": "luck", "from": x.get("from"), "name": x.get("name"), "at": day or _today(), "n": x.get("note")}, uid)
    except Exception:
        oops()


def tip_helped(guid, tip, uid=None):
    """This helped, on a tip: its words are kept, with the deck part its card is in (never the card)."""
    part = ""
    try:
        did = mw.col.db.scalar("SELECT c.did FROM cards c JOIN notes n ON n.id = c.nid WHERE n.guid = ? LIMIT 1", str(guid))
        if did:
            part = str(mw.col.decks.name(did) or "").split("::")[-1]
    except Exception:
        part = ""
    try:
        keep({"k": "tip", "from": tip.get("from"), "name": tip.get("name"), "at": str(tip.get("day") or "") or _today(),
              "n": tip.get("note"), "part": part}, uid)
    except Exception:
        oops()


def moment(what, head, sub="", pose="cheer", day=None, uid=None):
    """Something I did: a plan finished ("plan"), a bingo line ("bingo"), something Pip earned ("pip")."""
    try:
        return keep({"k": "mine", "w": what, "head": head, "sub": sub, "pose": pose, "at": day or _today()}, uid)
    except Exception:
        oops()
        return False


# ---- the view ----

def view(year=None):
    """The page's view (board.scrapbook_html): {year, years, so_far, yline,
    ystats, months: [{name, line, sub, items}], n}. The numbers are read
    from my own reviews, here (wrapped_flow's one query a year)."""
    from . import wrapped, wrapped_flow
    col = mw.col
    today = wrapped_flow._today_end(col)[0] if col else datetime.date.today()
    year = int(year or today.year)
    mine = items()
    me = _read()
    days, hours = wrapped_flow.year_rows(col, year) if col else ({}, {})
    f = wrapped.facts(year, today, days, hours, wrapped_flow.first_day(col) if col else None)
    per_month = {}
    for d, n in (f.get("per_day") or {}).items():
        m = int(d[5:7])
        got = per_month.setdefault(m, [0, 0])
        got[0] += 1
        got[1] += int(n)
    tally = me.get("cheers") if isinstance(me.get("cheers"), dict) else {}
    by_month = dict(S.months(mine, year))
    months = []
    for m in sorted(set(by_month) | set(per_month), reverse=True):
        its = by_month.get(m, [])
        dn, rv = per_month.get(m, (0, 0))
        months.append({"m": m, "name": S.MONTHS[m - 1], "line": S.month_line([x for x in its if x["k"] == "mine"], dn),
                       "sub": S.month_sub(dn, rv, int(tally.get(f"{year}-{m:02d}") or 0)),
                       "items": [dict(x, key=S.key(x)) for x in its]})
    c = S.counts(mine, year)
    in_year = [x for x in mine if x["at"][:4] == str(year)]
    cheers = sum(int(v or 0) for k, v in tally.items() if str(k)[:4] == str(year))
    ys = sorted(set(S.years(mine, today.year)) | set(wrapped_flow.years(col) if col else ()), reverse=True)
    return {"year": year, "years": ys, "so_far": year == today.year,
            "yline": S.year_line(year, f.get("days") or 0, f.get("reviews") or 0, year == today.year),
            "ystats": S.year_stats((f.get("run") or (0,))[0], sum(1 for x in in_year if x.get("w") == "plan"), c, cheers,
                                   sum(1 for x in in_year if x.get("w") == "pip")),
            "months": months, "n": len(in_year), "any": bool(mine or tally), "sev": bool(cfg().get("sev", True))}
