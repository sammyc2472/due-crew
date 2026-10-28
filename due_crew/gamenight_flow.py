"""Game night from Anki (3.9.5): Tools › Due Crew › Game night….

The window (ui/game_night_window.py) picks tonight's cards: this week's
misses, a plan's week, a saved scope, or a custom one. This reads them
from the collection (main thread), builds the pack (gamenight.py), opens a
table on the API (one request, on the click) and the TV
(ui/game_night_tv.py): the table page in a window of Anki's, handed the
pack. Try it with bots needs no table. What reaches phones is the games'
business (gamenight.py). Saved scopes are this profile's,
user_files/<profile>/game_night.json; nothing about them is sent.

While Sam tests it, the menu shows for TESTERS alone, and the server opens
a table only for an admin (worker/src/table.ts's ADMINS_ONLY)."""

import datetime
import json
import os
import random

from aqt import mw
from aqt.utils import tooltip

from . import gamenight as G
from .app import _bg, _profile_files, client

# the accounts the menu shows for while Sam tests it (wrangler.toml's ADMINS);
# None when it goes wider
TESTERS = ("FjrvFwUg6HNN3hy1YUmMp7ClR4v1",)
SAVED_MAX = 20
MISSED_DAYS = 7


def shown():
    """Tools › Due Crew › Game night… is there: signed in, and (while testing)
    a tester, or this computer's labs switch on (the server still decides)."""
    try:
        from .planner import enabled as labs
        c = client()
        return bool(c.signed_in()) and (TESTERS is None or c.user_id() in TESTERS or labs())
    except Exception:
        return False


# ---- saved scopes ----

def _file():
    return os.path.join(_profile_files(), "game_night.json")


def saved():
    try:
        with open(_file(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    out = []
    for s in data.get("scopes") or [] if isinstance(data, dict) else []:
        if isinstance(s, dict) and isinstance(s.get("name"), str) and isinstance(s.get("scope"), dict):
            out.append({"name": s["name"][:40], "scope": s["scope"]})
    return out[:SAVED_MAX]


def save(name, scope):
    name = " ".join(str(name or "").split())[:40] or "My scope"
    keep = [s for s in saved() if s["name"].lower() != name.lower()]
    keep.insert(0, {"name": name, "scope": scope})
    try:
        with open(_file(), "w", encoding="utf-8") as f:
            json.dump({"scopes": keep[:SAVED_MAX]}, f)
    except OSError:
        return None
    return name


# ---- what's in the collection ----

def _col():
    return mw.col


def find(search):
    try:
        return [int(c) for c in _col().find_cards(search)]
    except Exception:
        return []


def plan_week(pid):
    """The cards of a followed plan's dates that open this week (Monday to
    Sunday), as it runs here; [] without it."""
    from . import plan_flow as PF
    from . import plans as P
    got = PF._plan_idx(pid)
    if not got:
        return []
    _p, st, doc, idx = got
    today = datetime.date.today()
    mon = today - datetime.timedelta(days=today.weekday())
    lo, hi = mon.isoformat(), (mon + datetime.timedelta(days=6)).isoformat()
    out = set()
    for u in P.units(doc):
        if lo <= str(u.get("opens") or "") <= hi:
            out |= idx.match(u, PF._swap(st), doc)
    return sorted(out)


def _plans():
    from . import plan_flow as PF
    try:
        return [p for p in PF.followed() if p.get("id")]
    except Exception:
        return []


def sources():
    """Play from: [{key, label, n}]: this week's misses, each plan's week,
    the saved scopes."""
    out = [{"key": "misses", "label": "This week's misses", "n": len(find(f"rated:{MISSED_DAYS}:1"))}]
    for p in _plans():
        n = len(plan_week(p["id"]))
        if n:
            out.append({"key": f"plan:{p['id']}", "label": f"{p.get('name') or 'A plan'}, this week", "n": n})
    for s in saved():
        out.append({"key": "saved:" + s["name"], "label": s["name"], "n": len(cards_of(s["scope"]))})
    return out


def plans_for_scope():
    return [(p["id"], p.get("name") or "A plan") for p in _plans()]


def tree():
    """Decks and tags for the custom scope: [(key, label, depth)], decks first."""
    col, out = _col(), []
    try:
        decks = sorted(d.name for d in col.decks.all_names_and_ids())
    except Exception:
        decks = []
    for name in decks:
        out.append(("deck:" + name, name.split("::")[-1], name.count("::")))
    try:
        tags = sorted(col.tags.all(), key=str.lower)
    except Exception:
        tags = []
    for t in tags:
        out.append(("tag:" + t, t.split("::")[-1], t.count("::")))
    return out


def cards_of(scope):
    """The cards a custom scope comes to."""
    extra = None
    if scope.get("plan"):
        extra = plan_week(scope["plan"]) if not scope.get("search") else None
    if scope.get("slow") and not scope.get("search"):
        from . import habits_flow
        slow = habits_flow.slow_now()
        extra = slow if extra is None else sorted(set(extra) & set(slow))
    return find(G.scope_search(scope, extra))


def cards_for(key, scope=None):
    if key == "misses":
        return find(f"rated:{MISSED_DAYS}:1")
    if key.startswith("plan:"):
        return plan_week(key[5:])
    if key.startswith("saved:"):
        hit = next((s for s in saved() if s["name"] == key[6:]), None)
        return cards_of(hit["scope"]) if hit else []
    return cards_of(scope or {})


def rows(cids, cap=G.READ_MAX, rng=None):
    """item()'s rows for these cards, at most `cap` of them (a sample)."""
    cids = list(cids)
    if len(cids) > cap:
        cids = (rng or random).sample(cids, cap)
    if not cids:
        return []
    col, out, kinds = _col(), [], {}
    q = ",".join(str(int(c)) for c in cids)
    for cid, ord_, mid, flds, tags in col.db.all(
            f"SELECT c.id, c.ord, n.mid, n.flds, n.tags FROM cards c JOIN notes n ON n.id = c.nid WHERE c.id IN ({q})"):
        if mid not in kinds:
            try:
                kinds[mid] = (col.models.get(mid) or {}).get("type") == 1
            except Exception:
                kinds[mid] = False
        out.append((cid, ord_, kinds[mid], str(flds or "").split("\x1f"), str(tags or "").split()))
    return out


def pack_for(key, scope=None, name=""):
    cids = cards_for(key, scope)
    return G.build(rows(cids), name, n=len(cids))


def preview(scope):
    """For the custom scope: {n, search, fit, samples}. The search shown is
    without a plan's or Slow but right's cards (those go by card number)."""
    cids = cards_of(scope)
    pack = G.build(rows(cids, 400, random.Random(1)), n=len(cids), seed=1)
    have, _thin = G.fit(pack)
    return {"n": len(cids), "search": G.scope_search(dict(scope, plan=None, slow=False)), "fit": have, "samples": pack["qs"][:2]}


# ---- opening it ----

def open_window():
    if not mw.col:
        return
    if not shown():
        tooltip("Sign in to Due Crew first.")
        return
    from .ui.game_night_window import GameNightWindow
    w = GameNightWindow(mw, Ops())
    mw._due_crew_game_night = w
    w.show()


class Ops:
    """What the window asks of the add-on."""

    sources = staticmethod(sources)
    tree = staticmethod(tree)
    plans = staticmethod(plans_for_scope)
    preview = staticmethod(preview)
    saved = staticmethod(saved)

    @staticmethod
    def save(name, scope):
        return save(name, scope)

    @staticmethod
    def start(key, scope, label, bots, done):
        """Build tonight's pack, open a table (unless bots), then the TV.
        done(error) on the main thread: None, or what to say."""
        pack = pack_for(key, scope, label)
        _have, thin = G.fit(pack)
        if len(thin) == len(G.NEEDS):
            done("Not enough cards with short answers in that. Pick more.")
            return
        if bots:
            _tv({"mode": "bots", "pack": pack})
            done(None)
            return

        def opened(got):
            status, data = got if isinstance(got, tuple) else (0, {})
            if status == 200 and data.get("code") and data.get("key"):
                _tv({"mode": "tv", "code": data["code"], "key": data["key"], "pack": pack})
                done(None)
            elif status == 404:
                done("Game night isn't open for this account yet.")
            elif status == 429:
                done("That's a lot of tables for one hour. Try again in a while.")
            else:
                done("Couldn't open a table. Check your connection.")
        _bg(lambda: client().open_table(), opened)


def _tv(payload):
    from . import plan_flow
    from .ui.game_night_tv import open_tv
    open_tv(mw, plan_flow.site_base(), payload)
