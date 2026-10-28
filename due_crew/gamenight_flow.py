"""Pip Party from Anki (3.9.5; game night until its last round, and still
gamenight in code): You › Pip Party on the board, or Tools › Due Crew ›
Pip Party….

The window (ui/game_night_window.py) picks tonight's cards: this week's
misses, a plan's week, a saved scope, or a custom one. This reads them
from the collection (main thread), and the cards around them for answer
choices (near), builds the pack (gamenight.py), opens a table on the API
(one request, on the click) and the TV (ui/game_night_tv.py): the table
page in a window of Anki's, handed the pack. Try it with bots needs no table. What reaches phones is the games'
business (gamenight.py). Saved scopes are this profile's,
user_files/<profile>/game_night.json; nothing about them is sent.

While Sam tests it, the menu shows for TESTERS alone, and the server opens
a table only for an admin (worker/src/table.ts's ADMINS_ONLY)."""

import datetime
import json
import os
import random
import time
import traceback

from aqt import mw
from aqt.utils import tooltip

from . import app
from . import gamenight as G
from .app import _bg, _profile_files, cfg, client, save_cfg

# the accounts the menu shows for while Sam tests it (wrangler.toml's ADMINS);
# None when it goes wider
TESTERS = ("FjrvFwUg6HNN3hy1YUmMp7ClR4v1",)
SAVED_MAX = 20
MISSED_DAYS = 7


def shown():
    """Pip Party is there (Tools › Due Crew, You › Pip Party): signed in, and (while testing)
    a tester, or this computer's labs switch on (the server still decides)."""
    try:
        from .planner import enabled as labs
        c = client()
        return bool(c.signed_in) and (TESTERS is None or c.user_id in TESTERS or labs())
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


def near(got, cids, cap=G.NEAR_MAX, rng=None):
    """Cards around tonight's, for answer choices and white cards (never
    asked): two thirds from under their tags' parents, the rest from their
    decks, and from anywhere when those run short, for the odd pairing.
    got: tonight's rows; cids: all of tonight's cards (left out)."""
    rng = rng or random
    mine = {int(c) for c in cids}
    ups = {}
    for r in got:
        t = G.deepest(r[4])
        if t:
            up = t.rsplit("::", 1)[0] if "::" in t else t
            ups[up] = ups.get(up, 0) + 1
    picked, seen = [], set(mine)

    def take(found, k):
        left = [c for c in dict.fromkeys(int(c) for c in found) if c not in seen]
        got = rng.sample(left, k) if len(left) > k else left
        picked.extend(got)
        seen.update(got)
    tops = sorted(ups, key=lambda t: -ups[t])[:8]
    if tops:
        take(find(" OR ".join(G.term("tag:" + t) for t in tops)), cap * 2 // 3)
    col = _col()
    try:
        q = ",".join(str(c) for c in list(mine)[:2000]) or "0"
        dids = [d for (d,) in col.db.all(f"SELECT DISTINCT did FROM cards WHERE id IN ({q})")]
        if dids:
            take(col.db.list(f"SELECT id FROM cards WHERE did IN ({','.join(str(int(d)) for d in dids)}) ORDER BY random() LIMIT {cap}"),
                 cap - len(picked))
        if len(picked) < cap:
            take(col.db.list(f"SELECT id FROM cards ORDER BY random() LIMIT {cap * 2}"), cap - len(picked))
    except Exception:
        pass
    return rows(picked, cap, rng)


def pack_for(key, scope=None, name=""):
    cids = cards_for(key, scope)
    got = rows(cids)
    return G.build(got, name, n=len(cids), near=near(got, cids))


def preview(scope):
    """For the custom scope: {n, search, fit, samples}. The search shown is
    without a plan's or Slow but right's cards (those go by card number)."""
    cids = cards_of(scope)
    rng = random.Random(1)
    got = rows(cids, 400, rng)
    pack = G.build(got, n=len(cids), seed=1, near=near(got, cids, 200, rng))
    have, _thin = G.fit(pack)
    return {"n": len(cids), "search": G.scope_search(dict(scope, plan=None, slow=False)), "fit": have, "samples": pack["qs"][:2]}


# ---- opening it ----

def open_window(custom=False):
    if not mw.col:
        return
    if not shown():
        tooltip("Sign in to Due Crew first.")
        return
    from .ui.game_night_window import GameNightWindow
    w = GameNightWindow(mw, Ops(), custom=custom)
    mw._due_crew_game_night = w
    w.finished.connect(lambda *_: _fresh())  # a scope saved there is on the tab's list
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
                done("Pip Party isn't open for this account yet.")
            elif status == 429:
                done("That's a lot of tables for one hour. Try again in a while.")
            else:
                done("Couldn't open a table. Check your connection.")
        _bg(lambda: client().open_table(), opened)


def _tv(payload):
    from . import plan_flow
    from .ui.game_night_tv import open_tv
    site = plan_flow.site_base()
    w = open_tv(mw, site, payload)
    # the tab says the TV's open (its code, where phones join) until it closes
    code = str(payload.get("code") or "")
    TAB["turn"] += 1
    turn = TAB["turn"]
    TAB["open"] = {"bots": payload.get("mode") == "bots", "code": code,
                   "url": f"{site}/t/{code}" if code else ""}
    TAB["burst"] = True
    try:
        w.destroyed.connect(lambda *_: _tv_closed(turn))
    except Exception:
        traceback.print_exc()
    _redraw()


def _tv_closed(turn):
    if TAB.get("turn") == turn:  # the TV the tab tells of, not an older one
        TAB["open"] = None
        _redraw()


# ---- You › Pip Party (3.9.5's last round): the bubble's tab ----
# The pick is this computer's (config), as the bubble's tab is. What's on the
# list, and how much of the six the pick fills, are worked out when the tab is
# on screen and kept a while (Custom…'s window, a Host or bots, a pick, a
# profile change: worked out again), never on every draw. Nothing is sent but
# Host's one request.

PICK = "party_pick"
SOURCES_FOR, FIT_FOR = 120, 600  # seconds a list and a fit hold
TAB = {"busy": False, "said": "", "open": None, "burst": False, "turn": 0, "list": None, "fits": {}, "pip": None}


def _redraw():
    try:
        if app.swap:
            app.swap(cfg())
    except Exception:
        traceback.print_exc()


def _fresh():
    """Work the list out again next time (a scope saved, a game started)."""
    TAB["list"] = None
    _redraw()


def _sources():
    now, got = time.time(), TAB.get("list")
    if not got or got[0] != app.generation or now - got[1] > SOURCES_FOR:
        got = TAB["list"] = (app.generation, now, sources())
    return got[2]


def _fit(key):
    """{n, have, thin} for a pick: its pack's fit, on a sample, kept a while."""
    now, got = time.time(), TAB["fits"].get(key)
    if not got or got[0] != app.generation or now - got[1] > FIT_FOR:
        rng = random.Random(1)
        cids = cards_for(key)
        rws = rows(cids, 300, rng)
        have, thin = G.fit(G.build(rws, n=len(cids), seed=1, near=near(rws, cids, 150, rng)))
        got = (app.generation, now, {"n": len(cids), "have": have, "thin": thin})
        TAB["fits"] = {k: v for k, v in TAB["fits"].items() if now - v[1] <= FIT_FOR}
        TAB["fits"][key] = got
    return got[2]


def _pip(place):
    """Pip at the tab's place (sev.GAME_PLACES), in my accent and look; its
    move picked once a place, never the last one there."""
    from . import rooms, sev
    if not rooms.sev_on():
        return ""
    if (TAB.get("pip") or ("",))[0] != place:
        last = TAB.setdefault("last", {})
        m = sev.pick(place, last=last.get(place)) if place in sev.MOVES else None
        last[place] = m
        TAB["pip"] = (place, m)
    return sev.slot(sev.move(place, TAB["pip"][1], look=rooms.my_look(), size=72), 72)


def tab_view(c):
    """You › Pip Party, for board.party_html: {sources, pick, fit, busy,
    said, open, burst, pip}. Only when the tab's on screen (the glue)."""
    srcs = _sources()
    keys = [x["key"] for x in srcs]
    pick = c.get(PICK) if c.get(PICK) in keys else next((x["key"] for x in srcs if x["n"]), None)
    n = next((x["n"] for x in srcs if x["key"] == pick), 0)
    fit = None
    if pick and n:
        try:
            fit = _fit(pick)
        except Exception:
            traceback.print_exc()
    burst, TAB["burst"] = TAB.get("burst"), False
    place = ("cheer" if TAB.get("open") and burst else "hop" if TAB.get("open") else "ready" if TAB.get("busy")
             else "again" if TAB.get("said") else "hello")
    return {"sources": srcs, "pick": pick, "fit": fit, "busy": bool(TAB.get("busy")), "said": TAB.get("said") or "",
            "open": TAB.get("open"), "burst": bool(burst), "pip": _pip(place)}




def on_message(parts):
    """The tab's clicks: party:pick:KEY, party:host, party:bots,
    party:custom, party:copy. Main thread."""
    what = parts[2] if len(parts) > 2 else ""
    c = cfg()
    if what == "pick" and len(parts) > 3:
        key = G.unpick(parts[3])
        if key is not None and key in [x["key"] for x in _sources()]:
            c[PICK] = key
            save_cfg(c)
            TAB["said"] = ""
        _redraw()
    elif what in ("host", "bots"):
        if TAB.get("busy") or TAB.get("open"):
            return  # one table at a time; the tab shows the open one
        view = tab_view(c)
        hit = next((x for x in view["sources"] if x["key"] == view["pick"]), None)
        if not hit:
            TAB["said"] = "Pick what to play from, or Custom…"
            _redraw()
            return
        TAB["busy"], TAB["said"] = what == "host", ("Opening a table…" if what == "host" else "")

        def done(err):
            TAB["busy"] = False
            TAB["said"] = err or ""
            TAB["list"] = None
            if err or not TAB.get("open"):
                _redraw()  # an open TV drew the tab already (its burst with it)
        _redraw()
        Ops.start(hit["key"], None, hit["label"], what == "bots", done)
    elif what == "custom":
        open_window(custom=True)
    elif what == "copy":
        url = (TAB.get("open") or {}).get("url")
        if url:
            _clip(url)
            tooltip("Copied. Send it to your crew.")


def _clip(text):
    from aqt.qt import QApplication
    QApplication.clipboard().setText(text)
