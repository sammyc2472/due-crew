"""Pip Party from Anki (3.9.5; game night until its last round, and still
gamenight in code): You › Pip Party on the board, which Tools › Due Crew ›
Pip Party opens.

Round three (Sam's): the games up top, the one the TV opens on picked;
under them, what to play on. The map is Insights' own (a deck's Systems),
or the tag tree, or the decks; a tap picks a tile, › opens it, a find
names one; which of their cards; the picks at the foot, each one left out
or dropped there. The tab is the one way in (Sam: no Party from Today or
elsewhere). Nothing picked, the tiles on the map are the night, and the table
votes among them. Host reads the cards here (main thread) and the cards
around them (near), builds the pack off the main thread (gamenight.py,
each question marked with its pick for the vote), opens a table on the API
(one request, on the click) and the TV (ui/game_night_tv.py). What reaches
phones is the games' business (gamenight.py). Kept picks are this
profile's, user_files/<profile>/game_night.json; nothing about them is sent.

While Sam tests it, the tab shows for TESTERS alone, and the server opens
a table only for an admin (worker/src/table.ts's ADMINS_ONLY)."""

import functools
import json
import os
import random
import re
import time
import traceback
import urllib.parse

from aqt import mw
from aqt.utils import tooltip

from . import app
from . import gamenight as G
from .app import _bg, _profile_files, cfg, client, save_cfg

# the accounts the tab shows for while Sam tests it (wrangler.toml's ADMINS);
# None when it goes wider
TESTERS = ("FjrvFwUg6HNN3hy1YUmMp7ClR4v1",)
KEPT_MAX = 20
SHOW_MAX = 12      # a level's tiles on the map; the rest are a find away
IDS_MIN = 10       # question-number tags at a level, folded into one tile
FIND_MAX = 8
HOST_MAX = 2400    # cards Host reads at most, each pick's share among them
CORPUS_FOR, FIT_FOR = 600, 600  # seconds the tag and deck counts, and a pick's fit, hold
PARTY = "party"    # this computer's config: {by, did, game, of, picks} (a question-number tile's cards aren't kept)
GAME_IDS = [g for g, _l in G.GAMES]
# which of their cards: (key, words, the search, or None for slow but right)
OF = (("all", "all", ""), ("seen", "seen before", "-is:new"), ("missed", "missed in the last 7 days", "rated:7:1"),
      ("often", "missed 3 times or more", "prop:lapses>=3"), ("due", "due in the next 3 days", "prop:due<=3"),
      ("flagged", "flagged", "-flag:0"), ("slow", "slow but right", None))


def shown():
    """Pip Party is there (You › Pip Party, Tools › Due Crew): signed in, and
    (while testing) a tester, or this computer's labs switch on (the server
    still decides)."""
    try:
        from .planner import enabled as labs
        c = client()
        return bool(c.signed_in) and (TESTERS is None or c.user_id in TESTERS or labs())
    except Exception:
        return False


# ---- what's in the collection ----

def _col():
    return mw.col


def find(search):
    try:
        return [int(c) for c in _col().find_cards(search)]
    except Exception:
        return []


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


def near(got, cids, cap=G.NEAR_MAX, rng=None, slots=False):
    """Cards around tonight's, for answer choices and white cards (never
    asked): two thirds from under their topics' parent tags, the rest from
    their decks, and from anywhere when those run short, for the odd
    pairing. slots (Host's pack): also cards whose blank sits before the
    same word as tonight's ("{{c1::…}} receptor") or has the same hint
    ("{{c1::…::class}}"), the best wrong answers.
    got: tonight's rows; cids: all of tonight's cards (left out)."""
    rng = rng or random
    mine = {int(c) for c in cids}
    ups = {}
    for r in got:
        t = G.topic_of(r[4])[0]
        if t:
            up = t.rsplit("::", 1)[0] if "::" in t else t
            ups[up] = ups.get(up, 0) + 1
    picked, seen = [], set(mine)

    def take(found, k):
        left = [c for c in dict.fromkeys(int(c) for c in found) if c not in seen]
        got_ = rng.sample(left, k) if len(left) > k else left
        picked.extend(got_)
        seen.update(got_)
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
        its = [x for x in (G.item(r) for r in got) if x] if slots else []
        # one pass over the notes: a blank before the same word, or with the same hint ("::class}}");
        # each is letters, digits and spaces alone
        like = [f"%}}}} {w}%" for w in G.slots(its)] + [f"%::{h}}}}}%" for h in G.hints(its)]
        if like:
            take(col.db.list(f"SELECT c.id FROM cards c JOIN notes n ON n.id = c.nid WHERE {' OR '.join('n.flds LIKE ?' for _ in like)} LIMIT 3000",
                             *like), SLOT_MAX)
    except Exception:
        traceback.print_exc()
    return rows(picked, cap + SLOT_MAX, rng)


SLOT_MAX = 300  # of Host's pack's cards found by their blank

# ---- kept picks ----

def _file():
    return os.path.join(_profile_files(), "game_night.json")


def kept():
    """[{name, picks, of}]: the picks kept to play again. Round one's saved
    scopes (decks and tags in or out, which cards) read as picks."""
    try:
        with open(_file(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    data = data if isinstance(data, dict) else {}
    out = []
    for k in data.get("kept") or []:
        if isinstance(k, dict) and isinstance(k.get("name"), str) and isinstance(k.get("picks"), list):
            out.append({"name": k["name"][:40], "picks": [_clean_pick(x) for x in k["picks"] if _clean_pick(x)], "of": _of_key(k.get("of"))})
    for sc in data.get("scopes") or []:
        if isinstance(sc, dict) and isinstance(sc.get("name"), str) and isinstance(sc.get("scope"), dict) \
                and not any(x["name"].lower() == sc["name"].lower() for x in out):
            out.append(_from_scope(sc["name"][:40], sc["scope"]))
    return [k for k in out if k["picks"]][:KEPT_MAX]


def _from_scope(name, sc):
    picks = []
    for key, out in [(k, False) for k in sc.get("in") or []] + [(k, True) for k in sc.get("out") or []]:
        kind, _, path = str(key).partition(":")
        if kind in ("tag", "deck") and path:
            picks.append({"by": kind, "path": path, "out": out})
    if str(sc.get("search") or "").strip():
        picks = [{"by": "search", "text": str(sc["search"]).strip()[:400]}]
    of = "slow" if sc.get("slow") else "missed" if sc.get("missed") else "due" if sc.get("due") else (
        "often" if sc.get("lapses") else "flagged" if sc.get("flags") else "seen" if sc.get("seen") else "all")
    return {"name": name, "picks": picks, "of": of}


def _write(kept_list):
    try:
        with open(_file(), "w", encoding="utf-8") as f:
            json.dump({"kept": kept_list[:KEPT_MAX]}, f)
        return True
    except OSError:
        return False


def _clean_pick(p):
    """A pick as kept: {by, …, out}; None when it isn't one."""
    if not isinstance(p, dict):
        return None
    by, out = p.get("by"), bool(p.get("out"))
    if by in ("tag", "deck") and isinstance(p.get("path"), str) and p["path"]:
        return {"by": by, "path": p["path"][:200], "out": out}
    if by == "sys" and str(p.get("did") or "").isdigit() and isinstance(p.get("keys"), list):
        return {"by": "sys", "did": int(p["did"]), "keys": [str(k)[:120] for k in p["keys"]][:8], "name": str(p.get("name") or "")[:60],
                "deck": str(p.get("deck") or "")[:60], "out": out}
    if by == "ids" and isinstance(p.get("cids"), list):
        cids = [int(c) for c in p["cids"] if str(c).isdigit()][:20000]
        return {"by": by, "cids": cids, "name": str(p.get("name") or "")[:60], "path": str(p.get("path") or "")[:200], "out": out} if cids else None
    if by == "search" and str(p.get("text") or "").strip():
        return {"by": "search", "text": str(p["text"]).strip()[:400], "out": False}
    return None


# ---- the tab's state: what's picked, where the map is ----

TAB = {"busy": False, "said": "", "open": None, "burst": False, "turn": 0, "gen": None, "indexing": False,
       "by": "sys", "did": 0, "at": [], "game": GAME_IDS[0], "of": "all", "picks": [], "find": "", "hits": [],
       "shown": [], "level": None, "corpus": None, "levels": {}, "fits": {}, "fitting": None, "counts": {}}


def _redraw():
    try:
        if app.swap:
            app.swap(cfg())
    except Exception:
        traceback.print_exc()


def _state():
    """The tab's state, read from this computer's config once a profile."""
    if TAB.get("gen") != app.generation:
        st = cfg().get(PARTY) or {}
        TAB.update(gen=app.generation, by=st.get("by") if st.get("by") in ("sys", "tag", "deck") else "sys",
                   did=int(st.get("did") or 0) if str(st.get("did") or "").isdigit() else 0, at=[],
                   game=st.get("game") if st.get("game") in GAME_IDS else GAME_IDS[0], of=_of_key(st.get("of")),
                   picks=[x for x in (_clean_pick(p) for p in st.get("picks") or []) if x], find="", hits=[],
                   corpus=None, levels={}, fits={}, counts={}, said="")
    return TAB


def _keep_state():
    c = cfg()
    c[PARTY] = {"by": TAB["by"], "did": TAB["did"], "game": TAB["game"], "of": TAB["of"],
                "picks": [p for p in TAB["picks"] if p["by"] in ("tag", "deck", "sys", "search")]}
    save_cfg(c)


def _of_key(k):
    return k if k in [o[0] for o in OF] else "all"


def _pick_key(p):
    return "|".join(str(x) for x in (p["by"], p.get("did", ""), "::".join(p.get("keys") or []), p.get("path", ""), p.get("name", ""), p.get("text", "")))


def pick_name(p):
    """A pick in words, as its chip and the TV's vote say it."""
    if p["by"] == "sys":
        return p.get("name") or "?"
    if p["by"] in ("tag", "deck"):
        return _named(p["path"])
    if p["by"] == "search":
        return "Your search"
    return p.get("name") or "?"


def _leaf(path):
    return _show(str(path).split("::")[-1])


def _named(path):
    """A tag or deck pick as its chip and the vote say it: its parent and
    itself, their running numbers off ("14_Renal::03_Physiology" is "Renal ›
    Physiology"; Physiology alone could be any resource's)."""
    bare = lambda x: re.sub(r"^\d+[\s.)-]+(?=\S)", "", _show(x)) or _show(x)
    parts = str(path).split("::")
    return " › ".join(bare(x) for x in parts[-2:]) if len(parts) > 1 else bare(parts[0])


@functools.lru_cache(maxsize=200000)
def _show(seg):
    """A tag's part as the map names it: "#AK_Step1_v12" is "AK Step1 v12"."""
    return " ".join(re.sub(r"^[#!^$*@]+", "", str(seg)).replace("_", " ").split()) or str(seg)


# ---- the map: Systems (Insights'), tags, decks ----

def _corpus():
    """Every card in play (not suspended): (cid, deck id), what I know
    of each (team_flow._know: these four weeks' reviews), the decks' names,
    and each tag's cards (full: a big shared deck has 18 times fewer tags
    than a card's tags all told, so the map and Find walk these); read once
    and kept CORPUS_FOR seconds."""
    got = TAB.get("corpus")
    if got and got[0] == app.generation and time.time() - got[1] <= CORPUS_FOR:
        return got[2]
    from . import team_flow
    col = _col()
    rows_, full = [], {}
    for c, tags, d in col.db.all("SELECT c.id, n.tags, CASE WHEN c.odid THEN c.odid ELSE c.did END FROM cards c "
                                 "JOIN notes n ON n.id = c.nid WHERE c.queue != -1"):
        c = int(c)
        rows_.append((c, int(d)))
        for t in str(tags or "").split():  # one pass, no tuple a card: a big shared deck's tags are 50 MB of text
            got = full.get(t)
            if got is None:
                full[t] = [c]
            else:
                got.append(c)
    try:
        know = team_flow._know(col, "SELECT id FROM cards WHERE queue != -1", col.sched.day_cutoff)[0]
    except Exception:
        traceback.print_exc()
        know = {}
    try:
        decks = {int(d.id): str(d.name) for d in col.decks.all_names_and_ids()}
    except Exception:
        decks = {}
    data = {"rows": rows_, "know": know, "decks": decks, "full": full}
    TAB["corpus"] = (app.generation, time.time(), data)
    TAB["levels"] = {}
    return data


@functools.lru_cache(maxsize=200000)
def _idlike(seg):
    s = re.sub(r"^[#!^$*@]+", "", str(seg))
    return bool(re.fullmatch(r"\d+[A-Za-z]?", s) or (re.fullmatch(r"[A-Za-z0-9]{5,10}", s) and re.search(r"\d", s) and re.search(r"[A-Za-z]", s)
                                                       and not re.search(r"[aeiou]{2}", s.lower()) and G._part(s)[0] == "id"))


def _tile(key, name, cids, know, kids=False):
    got = [know[c] for c in cids if know.get(c) is not None]
    return {"key": key, "name": name, "n": len(cids), "know": int(round(100 * sum(got) / len(got))) if got else None,
            "started": len(got), "kids": bool(kids), "cids": cids}


def _tag_level(path):
    """The tag tree a level down from path ("" the top): its tiles, the most
    carded first, and its question-number tags folded into one ({n, cids})
    when there are IDS_MIN of them."""
    hit = TAB["levels"].get(("tag", path))
    if hit is not None:
        return hit
    data = _corpus()
    pre = (path + "::").lower() if path else ""
    by, deeper, names, ids = {}, set(), {}, {}
    for t, cs in data["full"].items():
        if pre and not t.lower().startswith(pre):
            continue
        seg, _, more = t[len(pre):].partition("::")
        if not seg:
            continue
        k = seg.lower()
        names.setdefault(k, seg)
        if more:
            deeper.add(k)
        (ids if _idlike(seg) else by).setdefault(k, set()).update(cs)
    if len(ids) < IDS_MIN:  # a few numbers are tiles like any other
        for k, cs in ids.items():
            by.setdefault(k, set()).update(cs)
        ids = {}
    know = data["know"]
    tiles = sorted((_tile(names[k], _show(names[k]), sorted(cs), know, k in deeper) for k, cs in by.items()), key=lambda t: (-t["n"], t["name"].lower()))
    folded = sorted(set().union(*ids.values())) if ids else []
    out = {"tiles": tiles, "ids": {"n": len(folded), "tags": len(ids), "cids": folded} if folded else None}
    TAB["levels"][("tag", path)] = out
    return out


def _deck_level(path):
    """The decks a level down from path: each with its subdecks' cards."""
    hit = TAB["levels"].get(("deck", path))
    if hit is not None:
        return hit
    data = _corpus()
    pre = (path + "::") if path else ""
    by, deeper = {}, set()
    names = data["decks"]
    for cid, did in data["rows"]:
        name = names.get(did, "")
        if pre and not name.startswith(pre):
            continue
        seg, _, more = name[len(pre):].partition("::")
        if not seg:
            continue
        by.setdefault(seg, []).append(cid)
        if more:
            deeper.add(seg)
    tiles = sorted((_tile(seg, seg, cs, data["know"], seg in deeper) for seg, cs in by.items()), key=lambda t: (-t["n"], t["name"].lower()))
    out = {"tiles": tiles, "ids": None}
    TAB["levels"][("deck", path)] = out
    return out


def _sys_decks():
    from . import team_flow
    try:
        return team_flow.you_decks()
    except Exception:
        traceback.print_exc()
        return []


def _sys_level(did, at):
    """Insights' map of a deck (team_flow.insights), where the tab has it
    open: (trail names, tiles)."""
    from . import team, team_flow
    d = next((x for x in _sys_decks() if x["did"] == did), None)
    if d is None:
        return [], []
    view = team_flow.insights(d["did"], d.get("pid"), str(cfg().get("exam_date") or ""))
    tiles, know = view.get("map") or [], view.get("_map_know") or {}
    if len(tiles) < 2:
        return [], []
    trail, cur = team.map_level(tiles, at, know)
    out = [{"key": t["key"], "name": str(t.get("name") or "?"), "n": int(t.get("n") or 0), "know": t.get("know"),
            "started": int(t.get("started") or 0), "kids": bool(t.get("kids")), "cids": list(team.tile_cards(t))} for t in cur]
    return [str(t.get("name") or "?") for t in trail], out


def level():
    """The map as the tab shows it now: {by, did, decks, trail, tiles (all
    of the level's), ids, where, plain}."""
    st = TAB
    out = {"by": st["by"], "did": st["did"], "decks": [], "trail": [], "tiles": [], "ids": None, "where": ""}
    if st["by"] == "sys":
        decks = _sys_decks()
        out["decks"] = [{"did": d["did"], "name": d["name"]} for d in decks]
        if decks and not any(d["did"] == st["did"] for d in decks):
            st["did"], st["at"] = decks[0]["did"], []
        trail, tiles = _sys_level(st["did"], st["at"]) if decks else ([], [])
        if len(trail) < len(st["at"]):
            st["at"] = st["at"][:len(trail)]
        out.update(trail=trail, tiles=tiles, where=next((d["name"] for d in decks if d["did"] == st["did"]), ""))
    else:
        path = "::".join(st["at"])
        lv = (_tag_level if st["by"] == "tag" else _deck_level)(path)
        if path and not lv["tiles"] and not lv["ids"]:
            st["at"], path = [], ""
            lv = (_tag_level if st["by"] == "tag" else _deck_level)("")
        out.update(trail=[_show(x) for x in st["at"]], tiles=lv["tiles"], ids=lv["ids"],
                   where=_show(st["at"][-1]) if st["at"] else ("your tags" if st["by"] == "tag" else "your decks"))
    return out


def _pick_of_tile(lv, t):
    if lv["by"] == "sys":
        return {"by": "sys", "did": lv["did"], "keys": TAB["at"] + [t["key"]], "name": t["name"], "deck": lv["where"], "out": False}
    return {"by": lv["by"], "path": "::".join(TAB["at"] + [t["key"]]), "out": False}


# ---- find ----

@functools.lru_cache(maxsize=200000)
def _words(seg):
    """A tag's or deck's part as words, lower case, each after a space
    (" 03 physiology"), so a word typed is the start of one when " " + it
    is in them ("phys" of "physiology"; "renal" not of "adrenal")."""
    return "".join(" " + w for w in re.findall(r"[a-z0-9]+", _show(seg).lower()))


def _find_ix(data):
    """Find's index, built once a corpus: every tag and parent tag (a node)
    with its own words and its path's, and where its cards lie in the tags
    sorted (a node's tags are a run of them: the tag itself and those under
    it), with a running count, so a keystroke is string checks and a
    count only for the few shown."""
    ix = data.get("find_ix")
    if ix is not None:
        return ix
    tags = sorted(data["full"], key=str.lower)
    low = [t.lower() for t in tags]
    acc = [0]
    for t in tags:
        acc.append(acc[-1] + len(data["full"][t]))
    nodes, seen = [], set()
    for t in tags:
        parts = t.split("::")
        said = ""
        for i, seg in enumerate(parts):
            own = _words(seg)
            said += own
            path = "::".join(parts[:i + 1])
            k = path.lower()
            if k in seen or _idlike(seg):
                continue  # a question number is never a match
            seen.add(k)
            nodes.append((path, k, own, said, _show(seg).lower(), " ".join(_show(x) for x in parts[max(0, i - 1):i + 1]).lower()))
    ix = data["find_ix"] = {"tags": tags, "low": low, "acc": acc, "nodes": nodes}
    return ix


def _runs(ix, k):
    """The tags under node k (lower case): the tag itself and those after "k::", as runs of the sorted tags."""
    import bisect
    low = ix["low"]
    a = bisect.bisect_left(low, k)
    b = a + 1 if a < len(low) and low[a] == k else a
    c = bisect.bisect_left(low, k + "::")
    d = bisect.bisect_left(low, k + "::\uffff")
    return [(a, b), (c, d)]


def hits(text):
    """Up to FIND_MAX tags and decks with every word typed the start of one
    on their way down, one of them in their own name: first those that have
    what's typed as it is when it's more than words ("B&B"), then those whose words are all in their
    name or their parent's ("Renal › Physiology" for "renal phys"), then the
    most carded: [{by, path, name, where, n, know, kids}]."""
    lit = " ".join(str(text or "").lower().split())
    words = re.findall(r"[a-z0-9]+", lit)
    if not re.search(r"[^a-z0-9\s]", lit):
        lit = ""  # what's typed as it is counts only when its words alone lose something ("b&b" is more than "b b")
    if not words:
        return []
    data = _corpus()
    know, full = data["know"], data["full"]
    ix = _find_ix(data)
    ws = [" " + w for w in words]
    near_of = lambda own, said2: all(w in said2 for w in ws)
    found = []
    for path, k, own, said, leaf, near in ix["nodes"]:
        if all(w in said for w in ws) and any(w in own for w in ws):
            runs = _runs(ix, k)
            n = sum(ix["acc"][y] - ix["acc"][x] for x, y in runs)  # cards counted once a tag: for the order only
            near_w = "".join(" " + w for w in re.findall(r"[a-z0-9]+", near))
            found.append(((bool(lit) and lit not in near, not near_of(own, near_w), -n, not leaf.startswith(words[0]), k), "tag", path, runs))
    for did, name in data["decks"].items():
        segs = name.split("::")
        said, own = "".join(_words(x) for x in segs), _words(segs[-1])
        if all(w in said for w in ws) and any(w in own for w in ws):
            near = " ".join(_show(x) for x in segs[-2:]).lower()
            found.append(((bool(lit) and lit not in near, not near_of(own, "".join(_words(x) for x in segs[-2:])), 0, False, name.lower()), "deck", name, None))
    found.sort(key=lambda f: f[0])
    out = []
    by_deck = None
    for key, kind, path, runs in found[:FIND_MAX * 3]:  # the exact cards, for the few that may show
        if kind == "tag":
            cs = set()
            for x, y in runs:
                for j in range(x, y):
                    cs.update(full[ix["tags"][j]])
        else:
            if by_deck is None:
                by_deck = {}
                for cid, did in data["rows"]:
                    by_deck.setdefault(data["decks"].get(did, ""), []).append(cid)
            cs = {c for dn, l in by_deck.items() if dn == path or dn.startswith(path + "::") for c in l}
        if cs:
            out.append(((key[0], key[1], -len(cs)) + key[3:], kind, path, cs))
    out.sort(key=lambda f: f[0])
    tiles = []
    for _key, kind, path, cs in out[:FIND_MAX]:
        parts = path.split("::")
        t = _tile(path, _show(parts[-1]), sorted(cs), know)
        t.update(by=kind, path=path, where=("Deck" if kind == "deck" else "Tag") + (" · " + " › ".join(_show(x) for x in parts[:-1]) if len(parts) > 1 else ""))
        tiles.append(t)
    return tiles


# ---- the picks' cards, the count, the fit ----

def _cids_of(p):
    by = p["by"]
    if by == "sys":
        from . import team, team_flow
        d = next((x for x in _sys_decks() if x["did"] == p["did"]), None)
        if d is None:
            return set()
        view = team_flow.insights(d["did"], d.get("pid"), str(cfg().get("exam_date") or ""))
        trail, cur = team.map_level(view.get("map") or [], p["keys"][:-1], view.get("_map_know") or {})
        t = next((x for x in cur if x["key"] == p["keys"][-1]), None) if len(trail) == len(p["keys"]) - 1 else None
        return set(team.tile_cards(t)) if t else set()  # a tile that's gone since (tags changed): nothing
    if by in ("tag", "deck"):
        return set(find(G.term(f"{by}:{p['path']}")))
    if by == "search":
        return set(find(p["text"]))
    return set(p.get("cids") or ())


def scope():
    """(cards, {card: its pick's name}, words): what Host plays on. Nothing
    picked, the tiles on the map, each its own; then the picks left out
    come off, and which of their cards narrows it."""
    ins = [p for p in TAB["picks"] if not p.get("out")]
    subs = {}
    if ins:
        # a card in two picks is the narrower one's (Pharm inside Step1 is Pharm's)
        got = sorted(((pick_name(p), _cids_of(p)) for p in ins), key=lambda x: -len(x[1]))
        for name, cs in got:
            for c in cs:
                subs[c] = name
    else:
        lv = level()
        for t in lv["tiles"]:
            for c in t["cids"]:
                subs.setdefault(c, t["name"])
        if lv["ids"]:
            for c in lv["ids"]["cids"]:
                subs.setdefault(c, "Question numbers")
    out = set()
    for p in TAB["picks"]:
        if p.get("out"):
            out |= _cids_of(p)
    cards = set(subs) - out
    of = next(o for o in OF if o[0] == TAB["of"])
    if of[0] == "slow":
        from . import habits_flow
        cards &= set(habits_flow.slow_now())
    elif of[2]:
        cards &= set(find(of[2]))
    return sorted(cards), {c: subs[c] for c in cards}, _sum_words(ins)


def _sum_words(ins):
    if ins:
        return ""
    lv = TAB.get("level") or {}
    return f"All of {lv.get('where') or 'it'}"


def _state_key():
    return json.dumps([TAB["by"], TAB["did"], TAB["at"] if not TAB["picks"] else [], TAB["of"], [_pick_key(p) + str(p.get("out")) for p in TAB["picks"]]])


def _count():
    """The cards the picks come to, kept until they change."""
    k = _state_key()
    got = TAB["counts"].get(k)
    if got is None:
        cards, _subs, _w = scope()
        got = TAB["counts"][k] = len(cards)
        if len(TAB["counts"]) > 40:
            TAB["counts"] = {k: got}
    return got


def _fit():
    """{game: how many} for the picks, from a pack built on a sample off the
    main thread and kept a while; None while it's worked out."""
    k, now, gen = _state_key(), time.time(), app.generation
    got = TAB["fits"].get(k)
    if got and got[0] == gen and now - got[1] <= FIT_FOR:
        return got[2]
    if TAB.get("fitting") == (gen, k):
        return None
    TAB["fitting"] = (gen, k)
    cards, subs, _w = scope()
    rng = random.Random(1)
    rws = rows(cards, 300, rng)
    nr = near(rws, cards, 150, rng)

    def done(have):
        if TAB.get("fitting") == (gen, k):
            TAB["fitting"] = None
        if app.generation != gen or have is None:
            return
        TAB["fits"] = {x: v for x, v in TAB["fits"].items() if now - v[1] <= FIT_FOR}
        TAB["fits"][k] = (gen, now, have)
        _redraw()
    _bg(lambda: G.fit(G.build(rws, n=len(cards), seed=1, near=nr, subs=subs))[0] if cards else {g: 0 for g in G.NEEDS}, done)
    got = TAB["fits"].get(k)  # there already when the job ran here
    return got[2] if got and got[0] == gen else None


def first_game(have):
    """The game the TV opens on: the one picked, or (it won't run on these)
    the next one that will; None when none will."""
    if have is None:
        return TAB["game"]
    fits = [g for g in GAME_IDS if have.get(g, 0) >= G.NEEDS[g][1]]
    return TAB["game"] if TAB["game"] in fits else (fits[0] if fits else None)


def search_text():
    """The picks as one Anki search, as the tab shows it (card numbers for
    a Systems tile or a question-number tile)."""
    def term(p):
        if p["by"] in ("tag", "deck"):
            return G.term(f"{p['by']}:{p['path']}")
        if p["by"] == "search":
            return f"({p['text']})"
        if p["by"] == "sys":
            return f"cid:… ({p.get('name')}, {p.get('deck')})"
        return f"cid:… ({p.get('name')})"
    ins = [term(p) for p in TAB["picks"] if not p.get("out")]
    outs = ["-" + term(p) for p in TAB["picks"] if p.get("out")]
    of = next(o for o in OF if o[0] == TAB["of"])
    parts = ([ins[0] if len(ins) == 1 else "(" + " OR ".join(ins) + ")"] if ins else []) + outs
    parts += [of[2]] if of[2] else (["(slow but right)"] if of[0] == "slow" else [])
    return " ".join(parts) or "deck:*"


# ---- the tab ----

def tab_view(c):
    """You › Pip Party, for board.party_html. Only when the tab's on screen
    (the glue); while the TV's open, the tab shows it alone."""
    _state()
    burst, TAB["burst"] = TAB.get("burst"), False
    if TAB.get("open"):
        return {"open": TAB["open"], "burst": bool(burst)}
    lv = TAB["level"] = level()
    TAB["shown"] = lv["tiles"][:SHOW_MAX]
    keys = {_pick_key(p): p for p in TAB["picks"]}
    data = (TAB.get("corpus") or (0, 0, {}))[2]
    if data and "find_ix" not in data and not TAB.get("indexing"):  # Find's index, made off the main thread before the first keystroke
        TAB["indexing"] = True
        _bg(lambda: _find_ix(data), lambda _ix: TAB.update(indexing=False))

    def marked(t, by=None, path=None):
        p = dict(by=by, path=path) if by else _pick_of_tile(lv, t)
        hit = keys.get(_pick_key(dict(p, out=False)))
        return "out" if hit and hit.get("out") else "in" if hit else ""
    tiles = [dict({k: v for k, v in t.items() if k != "cids"}, pick=marked(t)) for t in TAB["shown"]]
    ids = None
    if lv["ids"]:
        ip = _ids_pick(lv)
        hit = next((p for p in TAB["picks"] if p["by"] == "ids" and p.get("path") == ip["path"]), None)
        ids = {"n": lv["ids"]["n"], "tags": lv["ids"]["tags"], "pick": ("out" if hit and hit.get("out") else "in" if hit else "")}
    found = []
    if TAB["find"]:
        TAB["hits"] = hits(TAB["find"])
        found = [dict({k: v for k, v in t.items() if k != "cids"}, pick=marked(t, t["by"], t["path"])) for t in TAB["hits"]]
    n = _count()
    have = _fit() if n else {g: 0 for g in G.NEEDS}
    first = first_game(have)
    ins = [p for p in TAB["picks"] if not p.get("out")]
    return {"open": None, "burst": bool(burst), "busy": bool(TAB.get("busy")), "said": TAB.get("said") or "",
            "games": [{"id": g, "label": lbl, "n": None if have is None else have.get(g, 0), "need": G.NEEDS[g][1], "first": g == first}
                      for g, lbl in G.GAMES],
            "first": first, "kept": [k["name"] for k in kept()],
            "by": lv["by"], "decks": lv["decks"], "did": lv["did"], "trail": lv["trail"], "tiles": tiles, "ids": ids,
            "more": max(0, len(lv["tiles"]) - SHOW_MAX), "where": lv["where"], "find": TAB["find"], "hits": found,
            "of": TAB["of"], "ofs": [(k, w) for k, w, _s in OF], "search": search_text(),
            "picks": [{"name": pick_name(p), "deck": p.get("deck") or "", "kind": p["by"], "out": bool(p.get("out"))} for p in TAB["picks"]],
            "n": n, "all": "" if ins else _sum_words(ins)}


def _ids_pick(lv):
    path = "::".join(TAB["at"])
    return {"by": "ids", "path": path, "name": f"{lv['ids']['n']:,} cards by question number", "cids": lv["ids"]["cids"], "out": False}


def _toggle(p):
    k = _pick_key(dict(p, out=False))
    i = next((i for i, x in enumerate(TAB["picks"]) if _pick_key(dict(x, out=False)) == k), None)
    if i is None:
        TAB["picks"] = [x for x in TAB["picks"] if x["by"] != "search"] + [p]
    else:
        TAB["picks"].pop(i)


def open_tab():
    """The You bubble open on Pip Party, on the Decks screen, Anki in front."""
    if not mw.col or not shown():
        tooltip("Sign in to Due Crew first.")
        return
    c = cfg()
    c["due_tab"] = "party"
    from . import team_flow
    c["due_fold"] = {"day": team_flow._today(), "folded": False}
    save_cfg(c)
    try:
        if mw.state != "deckBrowser":
            mw.moveToState("deckBrowser")
        mw.activateWindow()
        mw.raise_()
    except Exception:
        traceback.print_exc()
    app.swap(c)


def _text(parts, start=3, top=400):
    return urllib.parse.unquote(":".join(parts[start:]))[:top]


def _find_draw():
    """The find's matches in the map's place, without drawing the board
    again (the box keeps its focus and what's typed)."""
    from . import board
    view = tab_view(cfg())
    try:
        app.board_eval("(function(){var m=document.getElementById('pp-map');if(m){m.outerHTML=%s;}})();"
                       % json.dumps(board.party_map_html(view)))
    except Exception:
        traceback.print_exc()


def on_message(parts):
    """The tab's clicks (party:…). Main thread."""
    what = parts[2] if len(parts) > 2 else ""
    arg = parts[3] if len(parts) > 3 else ""
    _state()
    if TAB.get("open") and what != "copy":
        return
    lv = TAB.get("level") or level()
    redraw, keep = True, True
    if what == "game" and arg in GAME_IDS:
        TAB["game"] = arg
    elif what == "by" and arg in ("sys", "tag", "deck"):
        TAB["by"], TAB["at"] = arg, []
    elif what == "deck" and arg.isdigit():
        TAB["did"], TAB["at"] = int(arg), []
    elif what in ("open", "pick") and arg.isdigit() and int(arg) < len(TAB["shown"]):
        t = TAB["shown"][int(arg)]
        if what == "open" and t.get("kids"):
            TAB["at"] = TAB["at"] + [t["key"]]
        elif what == "pick":
            _toggle(_pick_of_tile(lv, t))
    elif what == "up" and arg.isdigit():
        TAB["at"] = TAB["at"][:int(arg)]
    elif what == "ids" and lv.get("ids"):
        _toggle(_ids_pick(lv))
    elif what == "hit" and arg.isdigit() and int(arg) < len(TAB["hits"]):
        h = TAB["hits"][int(arg)]
        _toggle({"by": h["by"], "path": h["path"], "out": False})
    elif what == "find":
        TAB["find"] = " ".join(_text(parts, top=60).split())
        _find_draw()
        return
    elif what in ("out", "drop") and arg.isdigit() and int(arg) < len(TAB["picks"]):
        if what == "out":
            p = TAB["picks"][int(arg)]
            if p["by"] != "search":
                p["out"] = not p.get("out")
        else:
            TAB["picks"].pop(int(arg))
    elif what == "clear":
        TAB["picks"], TAB["find"] = [], ""
    elif what == "of" and arg in [o[0] for o in OF]:
        TAB["of"] = arg
    elif what == "search":
        text = " ".join(_text(parts).split())
        if text and text != search_text():
            TAB["picks"] = [{"by": "search", "text": text, "out": False}]
    elif what == "keep":
        ins = [p for p in TAB["picks"] if not p.get("out")]
        if TAB["picks"]:
            names = [pick_name(p) for p in ins] or ["Everything but"]
            name = (" and ".join(names[:2]) + (f" and {len(names) - 2} more" if len(names) > 2 else ""))[:40]
            rest = [k for k in kept() if k["name"].lower() != name.lower()]
            if _write([{"name": name, "picks": [dict(p) for p in TAB["picks"]], "of": TAB["of"]}] + rest):
                tooltip("Kept.")
        keep = False
    elif what == "kept" and arg.isdigit():
        ks = kept()
        if int(arg) < len(ks):
            TAB["picks"], TAB["of"], TAB["find"] = [dict(p) for p in ks[int(arg)]["picks"]], ks[int(arg)]["of"], ""
    elif what == "forget" and arg.isdigit():
        ks = kept()
        if int(arg) < len(ks):
            _write(ks[:int(arg)] + ks[int(arg) + 1:])
        keep = False
    elif what == "host":
        host()
        return
    elif what == "copy":
        url = (TAB.get("open") or {}).get("url")
        if url:
            _clip(url)
            tooltip("Copied. Send it to your crew.")
        return
    else:
        redraw = False
    if keep:
        _keep_state()
    if redraw:
        TAB["said"] = "" if what != "host" else TAB["said"]
        _redraw()


def _clip(text):
    from aqt.qt import QApplication
    QApplication.clipboard().setText(text)


# ---- Host ----

def host():
    """Host: tonight's cards and the ones around them read here, the pack
    built off the main thread, then a table (one request) and the TV."""
    if TAB.get("busy") or TAB.get("open"):
        return  # one table at a time; the tab shows the open one
    view = tab_view(cfg())
    first = view.get("first")
    if not first or not view.get("n"):
        TAB["said"] = "Too few cards for any game here."
        _redraw()
        return
    TAB["busy"], TAB["said"] = True, "Opening a table…"

    def done(err):
        TAB["busy"] = False
        TAB["said"] = err or ""
        if err or not TAB.get("open"):
            _redraw()  # an open TV drew the tab already (its burst with it)
    _redraw()
    Ops.start(first, done)


def _pack_rows():
    """Host's reading of the collection (main thread): (rows, near=…, n=…,
    subs=…) as G.build takes them; the build itself can run anywhere. Each
    pick (or tile) keeps a share of its own, so the vote has enough of any."""
    cards, subs, _w = scope()
    by = {}
    for c in cards:
        by.setdefault(subs.get(c, ""), []).append(c)
    rng = random.Random()
    take = []
    for sub, cs in by.items():
        k = max(80, round(G.READ_MAX * len(cs) / max(1, len(cards))))
        take += rng.sample(cs, k) if len(cs) > k else cs
    if len(take) > HOST_MAX:  # many small picks: their shares, together, kept to what a build takes in time
        take = rng.sample(take, HOST_MAX)
    got = rows(take, len(take))
    return (got,), {"near": near(got, cards, slots=True), "n": len(cards), "subs": subs}


class Ops:
    @staticmethod
    def start(first, done):
        """Build tonight's pack, open a table, then the TV on the first game.
        done(error) on the main thread: None, or what to say. A profile
        changed or signed out meanwhile opens nothing."""
        gen = app.generation
        args, kw = _pack_rows()
        _bg(lambda: G.build(*args, name="Pip Party", **kw), lambda pack: built(pack))

        def built(pack):
            if app.generation != gen:
                done(None)
                return
            if not pack:
                done("Couldn't read tonight's cards.")
                return
            _have, thin = G.fit(pack)
            if len(thin) == len(G.GAMES):
                done("Too few cards for any game here.")
                return
            _bg(lambda: client().open_table(), lambda got: opened(got, pack))

        def opened(got, pack):
            status, data = got if isinstance(got, tuple) else (0, {})
            if app.generation != gen:
                done(None)
            elif status == 200 and data.get("code") and data.get("key"):
                _tv({"mode": "tv", "code": data["code"], "key": data["key"], "pack": pack, "first": first})
                done(None)
            elif status == 404:
                done("Pip Party isn't open for this account yet.")
            elif status == 429:
                done("That's a lot of tables for one hour. Try again in a while.")
            else:
                done("Couldn't open a table. Check your connection.")


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
