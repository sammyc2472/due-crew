"""3.7.3 a plan's team and its Insights, the pure parts (team_flow.py is the
glue). Insights (3.7.9): the cards Anki won't show me before the plan's
next event that I'd recall under my target by then (FSRS), the topics not
sticking yet (a tag under its resource, read as words), my week in minutes
at my own pace, and Optimize FSRS when my newest cards fall short. Worked
out in my Anki from my own reviews; nothing about it leaves this computer."""

import datetime
import math

from . import plans as P
from . import schedule as S

DAYS = 14          # the window; the trend compares it with the 14 before
ROWS = 6
NAME_MAX = 60


def topic_list(doc):
    """[(key, name, [resources], [plan tags], [unit ids])] for a plan's tags,
    one per topic: a tag's last part read as words, merged across resources
    ("Complement" from a video series and from a book is one topic)."""
    out = {}
    for u in P.units(doc):
        for t in u.get("tags") or []:
            segs = str(t).split(P._SEP)
            ri = next((i for i, x in enumerate(segs) if i > 0 and x[:1] in "#^"), -1)
            res = P._word(segs[ri]) if 0 <= ri < len(segs) - 1 else ""
            name = P._word(segs[-1])[:NAME_MAX]
            if not name:
                continue
            key = name.lower()
            k = out.setdefault(key, [key, name, [], [], []])
            if res and res not in k[2]:
                k[2].append(res)
            if t not in k[3]:
                k[3].append(t)
            if u["id"] not in k[4]:
                k[4].append(u["id"])
    return [tuple(v) for v in out.values()]


# ---- 3.7.9 Insights (mock "Insights", rounds 1-17, drawn on Sam's own
# collection): only what's counted, or Anki's own memory model, is said.

STUCK_MIN = 20     # a topic shows with this many cards reviewed in the window
FSRS_GAP = 3       # points under the target, on cards 1-3 days since their last review...
FSRS_MIN = 300     # ...with this many answers behind it
AIM_DAYS = 21      # the hero aims at the next event this close, else a week out
NEW_MIN = 50       # new cards measured over their first week before the week is in time
HIDE_DAYS = 30     # Optimize FSRS (or the Hard habit), dismissed, stays away this long
HARD_SHARE = 15    # % of review answers on Hard before Insights says so (3.8.0)...
HARD_MIN = 200     # ...with this many answers behind it


def recall(t, s, decay=0.5):
    """FSRS's forgetting curve: the chance of recall t days after the last
    review, at stability s (decay 0.5 is FSRS-4.5/5; FSRS-6 stores its own)."""
    decay = float(decay) if decay and float(decay) > 0 else 0.5
    factor = 0.9 ** (-1.0 / decay) - 1.0
    return (1.0 + factor * max(float(t), 0.0) / max(float(s), 0.1)) ** -decay


def aim(events, today):
    """(day, name, days to it, event id) the hero aims at: the plan's next
    event in AIM_DAYS, else (today + 7, "", 7, "")."""
    t = S.d(today)
    soon = sorted((str(e.get("day") or ""), str(e.get("name") or ""), str(e.get("id") or "")) for e in events or []
                  if isinstance(e, dict) and today < str(e.get("day") or "") <= S.iso(t + datetime.timedelta(days=AIM_DAYS)))
    if soon:
        return soon[0][0], soon[0][1], (S.d(soon[0][0]) - t).days, soon[0][2]
    return S.iso(t + datetime.timedelta(days=7)), "", 7, ""


def prep_units(units, eid):
    """The ids of the dates that prep for the event (a date's `for`); the
    hero counts only their cards when there are any."""
    return [u["id"] for u in units if eid and u.get("for") == eid]


def right_days(answers):
    """The header: {now: [right, n], before: [right, n], days: [% or None,
    oldest first]} over [(cid, days ago, ease)] review answers, the first
    answer of each card each day; now is the last DAYS days."""
    first = {}
    for cid, ago, ease in answers:
        ago = int(ago)
        if 0 <= ago < 2 * DAYS:
            first.setdefault((ago, int(cid)), int(ease) > 1)
    now, before, days = [0, 0], [0, 0], {}
    for (ago, _c), ok in first.items():
        w = now if ago < DAYS else before
        w[0] += ok
        w[1] += 1
        if ago < DAYS:
            dd = days.setdefault(ago, [0, 0])
            dd[0] += ok
            dd[1] += 1
    return {"now": now, "before": before,
            "days": [int(round(100.0 * days[a][0] / days[a][1])) if a in days else None for a in range(DAYS - 1, -1, -1)]}


def hero(cards, target):
    """The cards Anki won't show me before the aim that I'd recall below my
    target by then, least likely first. cards: {cid: (recall at the aim, shown before it)}."""
    out = [(r, c) for c, (r, shown) in cards.items() if not shown and r < target]
    return [c for _r, c in sorted(out)]


def source(tags):
    """A topic's source as its tags say: the resource and the part just above
    the topic ("Video Series › Autonomic System"), from the first tag. 3.8.0:
    with no resource in the tag, the part just above ("Path Book" over a
    subdeck's "Inflammation")."""
    for t in tags or []:
        segs = [x for x in str(t).split(P._SEP) if x]
        ri = next((i for i, x in enumerate(segs) if i > 0 and x[:1] in "#^"), -1)
        if ri < 0 or ri >= len(segs) - 1:
            continue
        parts = [P._word(segs[ri])]
        if len(segs) - 2 > ri:
            parts.append(P._word(segs[-2]))
        return " › ".join(p for p in parts if p)
    for t in tags or []:
        segs = [x for x in str(t).split(P._SEP) if x]
        if len(segs) > 1 and not any(x[:1] in "#^" for x in segs[1:]):
            return P._word(segs[-2])
    return ""


ANKI_TAGS = ("leech", "marked")  # Anki's own: never a topic


def deck_topics(tags_of, reviewed, min_n=None):
    """3.8.0, Insights with no plan on the deck: topics from the deck's own
    tags, as topic_list makes them from a plan's. Each reviewed card counts
    under its most specific tags (none of them a parent of another of its
    tags), rolled up the tag's own levels until one has min_n reviewed cards
    under it; never up to a hierarchy's root, nor to a level that names a
    resource ("#Path_Book"), nor from a question bank's ids (digits only).
    tags_of: {cid: [tags]} (a subdeck's path
    below the deck works the same). (topics, {level: {cids}}): the topics as
    topic_list gives them, the levels as their tags, for not_sticking."""
    min_n = STUCK_MIN if min_n is None else min_n
    leaves = {}
    for cid in reviewed:
        # 3.8.0: a question bank's id ("…::Step::104523") is never a topic
        tags = [str(t) for t in (tags_of.get(cid) or ()) if t and str(t).lower() not in ANKI_TAGS
                and not str(t).rsplit(P._SEP, 1)[-1].isdigit()]
        low = [t.lower() for t in tags]
        leaves[cid] = [t for t, lt in zip(tags, low) if not any(o.startswith(lt + P._SEP) for o in low)]
    under = {}
    for cid, ls in leaves.items():
        seen = set()
        for t in ls:
            segs = t.split(P._SEP)
            for i in range(1, len(segs) + 1):
                seen.add(P._SEP.join(segs[:i]).lower())
        for k in seen:
            under[k] = under.get(k, 0) + 1
    groups, first = {}, {}
    for cid in sorted(leaves):
        for t in leaves[cid]:
            segs = t.split(P._SEP)
            for i in range(len(segs), 0, -1):
                if (len(segs) > 1 and i == 1) or (i > 1 and segs[i - 1][:1] in "#^"):
                    break  # a hierarchy's root, or a resource: too broad to be a topic
                level = P._SEP.join(segs[:i])
                if under.get(level.lower(), 0) >= min_n:
                    level = first.setdefault(level.lower(), level)  # one spelling per level
                    groups.setdefault(level, set()).add(cid)
                    break
    out = {}
    for level in sorted(groups):
        name = P._word(level.split(P._SEP)[-1])[:NAME_MAX]
        if not name:
            continue
        k = out.setdefault(name.lower(), [name.lower(), name, [], [], []])
        k[3].append(level)
    return [tuple(v) for v in out.values()], groups


def not_sticking(topics, cards_of, reviewed, stuck, forgot):
    """Not sticking yet, worst first: [{key, name, src, of, stuck, forgot,
    cids}]. reviewed: my cards answered in review in the window; stuck: of
    those, never right in a review yet (as of now, so a row shrinks as cards
    stick); forgot: missed in the window after having been right. A topic
    shows with STUCK_MIN cards reviewed, and something to study."""
    rows = []
    for key, name, _res, tags, _uids in topics:
        cids = set()
        for t in tags:
            cids |= set(cards_of(t))
        rev = cids & reviewed
        if len(rev) < STUCK_MIN:
            continue
        st = rev & stuck
        fg = (rev & forgot) - st
        if not st and not fg:
            continue
        rows.append({"key": key, "name": name, "src": source(tags), "of": len(rev), "stuck": len(st),
                     "forgot": len(fg), "cids": sorted(st | fg), "tags": list(tags)})
    rows.sort(key=lambda r: (-(r["stuck"] + r["forgot"]) / r["of"], -r["stuck"], r["name"].lower()))
    return rows[:ROWS]


MAP_TILES = 12   # 3.8.0, the topic map: tiles on a level at most
MAP_FIT = 5      # a level reads best with this many tiles' worth of cards or more (top level)...
MAP_SUB_FIT = 3  # ...and inside a tile
MAP_DEEP = 4     # a tile opens this many levels down at most
MAP_SAMPLE = 3000  # a big deck's cut is chosen on an even sample of this many cards


def _min_n(n, top):
    """A tile's fewest cards: 1% of what's on the level (8 at least) at the
    top, 2% (5 at least) inside a tile."""
    return max(8, n // 100) if top else max(5, n // 50)


def _cut(per, depth, min_n):
    """per {cid: [(head, rest, rest lowered)]} cut at depth: [(key, cids,
    spell, depth)] of min_n cards or more, the biggest MAP_TILES, each card
    in its biggest subject; how many of their cards have one subject; and
    how many have a level below it (a topic opens into parts; a rating
    like "1-HighYield" doesn't)."""
    size, spell, keys_of, below = {}, {}, {}, set()
    for cid, lst in per.items():
        keys = set()
        for head, rest, low in lst:
            if len(low) > depth:
                below.add(cid)
            if len(low) >= depth:
                k = low[:depth]
                keys.add(k)
                if k not in spell:
                    spell[k] = (head, rest)
        if keys:
            keys_of[cid] = keys
            for k in keys:
                size[k] = size.get(k, 0) + 1
    groups = {}
    for cid, keys in keys_of.items():
        k = next(iter(keys)) if len(keys) == 1 else max(keys, key=lambda k: (size[k], k))
        groups.setdefault(k, []).append(cid)
    big = sorted(((k, v) for k, v in groups.items() if len(v) >= min_n), key=lambda kv: (-len(kv[1]), kv[0]))[:MAP_TILES]
    tiles = [(k, v, P._SEP.join(spell[k][0] + spell[k][1][:depth]), depth) for k, v in big]
    return (tiles, sum(1 for t in tiles for c in t[1] if len(keys_of[c]) == 1),
            sum(1 for t in tiles for c in t[1] if c in below))


def _score(tiles, clean, deep, n, fit):
    """How well a cut splits n cards: the share in its tiles, the share of
    those in one subject, how many tiles' worth it makes (the exponential
    of their sizes' entropy; fit or more is full marks), and topics over
    ratings: a cut whose cards have nothing below it scores half (a deck's
    yield tiers split it evenly and say nothing about what's in it). A
    cut too broad makes two big tiles; too fine, crumbs under min_n."""
    held = sum(len(t[1]) for t in tiles)
    if not n or not held or len(tiles) < 2:
        return 0.0
    eff = math.exp(-sum(len(t[1]) / held * math.log(len(t[1]) / held) for t in tiles))
    return (held / n) * (clean / held) * min(1.0, eff / fit) * (0.5 + 0.5 * deep / held)


def _family_cuts(fams, n, fit, top, min_n=None):
    """{family: (score, tiles)}: each family's best depth (the six that hold
    the most cards; shallower wins a tie), the ones that split at all."""
    out = {}
    min_n = _min_n(n, top) if min_n is None else min_n
    for fam in sorted(fams, key=lambda f: (-len(fams[f]), f))[:6]:
        best = (0.0, [])
        for depth in (1, 2, 3, 4):
            tiles, clean, deep = _cut(fams[fam], depth, min_n)
            if not tiles:
                break
            sc = _score(tiles, clean, deep, n, fit)
            if sc > best[0] + 1e-9:
                best = (sc, tiles)
        if best[0] > 0:
            out[fam] = best
    return out


def _best(fams, n, fit, top, min_n=None):
    """The best cut over every family and depth: (score, family, tiles);
    the family that holds more cards wins a tie."""
    cuts = _family_cuts(fams, n, fit, top, min_n)
    best = (0.0, None, [])
    for fam in sorted(cuts, key=lambda f: (-len(fams[f]), f)):
        if cuts[fam][0] > best[0] + 1e-9:
            best = (cuts[fam][0], fam, cuts[fam][1])
    return best


def _tiles(per, cut, know, decks, level):
    """A cut's tiles, biggest first. Each keeps what it needs to open
    later (expand): its level's cards and paths, privately (_-keys)."""
    out = []
    for key, cids, spell, depth in cut:
        name = P._word(spell.split(P._SEP)[-1])[:NAME_MAX]
        if not name:
            continue
        started = [know[c] for c in cids if c in know]
        out.append({"key": P._SEP.join(key), "name": name, "n": len(cids), "started": len(started),
                    "know": int(round(100 * sum(started) / len(started))) if started else None,
                    "find": {"decks" if decks else "tags": [spell]},
                    "_spell": spell, "_per": per, "_cids": cids, "_key": key, "_level": level})
    names = [t["name"].lower() for t in out]
    if len(set(names)) < len(names):  # two read the same: the level above names each ("Cardio · Physiology")
        for t in out:
            segs = t["_spell"].split(P._SEP)
            up = P._word(segs[-2]) if len(segs) > 1 else ""
            t["name"] = (f"{up} · {t['name']}" if up else t["name"])[:NAME_MAX]
    names = [t["name"].lower() for t in out]
    for t in out:  # still the same ("01_Chapter", "02_Chapter"): their numbers tell them apart
        if names.count(t["name"].lower()) > 1:
            seg = t["_spell"].split(P._SEP)[-1]
            t["name"] = (" ".join(seg.lstrip("#^$!").replace("_", " ").split()) or t["name"])[:NAME_MAX]
    out.sort(key=lambda t: (-t["n"], t["name"].lower()))
    return out


def expand(t, know):
    """A tile's smaller ones (two of real size or more), worked out once:
    t["kids"], [] when it doesn't split. Done for the level on screen, so
    its › marks are exact; deeper when a tile opens (map_level)."""
    if "kids" in t or "_per" not in t:
        return t.get("kids") or []
    t["kids"] = []
    if t["_level"] < MAP_DEEP:
        key, depth, per = t["_key"], len(t["_key"]), t["_per"]
        sub = {}
        for c in t["_cids"]:
            lst = [(head + rest[:depth], rest[depth:], low[depth:]) for head, rest, low in per[c]
                   if len(low) > depth and low[:depth] == key]
            if lst:
                sub[c] = lst
        sc, _f, kids = _best({(): sub}, len(t["_cids"]), MAP_SUB_FIT, False)
        if sc and len(kids) >= 2:
            t["kids"] = _tiles(sub, kids, know, "decks" in t["find"], t["_level"] + 1)
    return t["kids"]


def subjects(paths_of, know, active=None, decks=False):
    """The map's tiles, the best way (subjects_by without a pick)."""
    return subjects_by(paths_of, know, active, decks)[0]


def subjects_by(paths_of, know, active=None, decks=False, by=None):
    """3.8.0, the topic map's tiles: the cards in play (active: unsuspended,
    started or not; know's when not given) split the way that tells them
    apart best, not by the deck's top level. paths_of: {cid: [tags]}, or
    with decks {cid: [subdeck path below the deck]}; know: {cid: 0..1} for
    the started ones. A tag's family is what comes before its first level
    (under a resource's mark, "^Systems::Cardio" reads Cardio; else the
    tag's root). Every family's every depth is a cut; the best holds the
    most cards, each in one subject, in about MAP_FIT tiles or more of
    real size, with levels below them (_score). A card in two subjects
    goes to the bigger. A question bank's ids, Anki's own tags: never.
    (tiles, ways). tiles: [{key, name, n (cards in play), started, know
    (0-100 over the started, None with none), find, kids}] biggest first:
    find says how to Browse all of a tile's cards; kids, the same inside
    it. ways: the families that split, best first, [{key, name, score,
    on}], so a person can pick another (by: a way's key)."""
    active = set(know) if active is None else set(active)
    seen, names = {}, {}  # a tag read once; a family's name as spelled

    def read(t):
        if not t or t.lower() in ANKI_TAGS or t.rsplit(P._SEP, 1)[-1].isdigit():
            return None
        segs = [x for x in t.split(P._SEP) if x]
        ri = -1
        if not decks:
            for i in range(1, len(segs)):
                if segs[i][:1] in "#^$!":
                    ri = i
                    break
        if not segs[ri + 1:]:
            return None
        low = tuple(x.lower() for x in segs)
        return low[:ri + 1], segs[:ri + 1], segs[ri + 1:], low[ri + 1:]

    def gather(cids, only=None):
        out = {}
        for cid in cids:
            for t in paths_of.get(cid) or ():
                t = str(t)
                if t not in seen:
                    seen[t] = read(t)
                got = seen[t]
                if got and (only is None or got[0] == only):
                    out.setdefault(got[0], {}).setdefault(cid, []).append(got[1:])
                    names.setdefault(got[0], got[1])
        return out
    # the cut is chosen on an even sample (all of a smaller deck), then made of every card
    ids = sorted(active)
    pick = ids[::max(1, len(ids) // MAP_SAMPLE)]
    fams = gather(pick)
    n, m = len(ids), len(pick)
    cuts = _family_cuts(fams, m, MAP_FIT, True, max(2, _min_n(n, True) * m // max(1, n)))
    order = sorted(cuts, key=lambda f: (-cuts[f][0], -len(fams[f]), f))
    key = lambda f: P._SEP.join(f)  # noqa: E731
    fam = next((f for f in order if by is not None and key(f) == str(by)), order[0] if order else None)
    ways = [{"key": key(f), "score": round(cuts[f][0], 4), "on": f == fam,
             "name": ("Subdecks" if decks else P._word(names[f][-1]) if f else "Tags")[:NAME_MAX]} for f in order[:4]]
    if fam is None:
        return [], ways
    cut = cuts[fam][1]
    if m < n:
        fams = gather(ids, fam)
        cut, _clean, _deep = _cut(fams.get(fam) or {}, cut[0][3], _min_n(n, True))
    out = _tiles(fams[fam], cut, know, decks, 1) if cut else []
    while len(out) == 1 and expand(out[0], know):
        out = out[0]["kids"]  # every tag under one root ("Step1::…"): what's under it
    for t in out:
        expand(t, know)
    return out, ways


def map_level(tiles, at, know=None):
    """Where the map is: at, the keys of the tiles opened, in order. (trail
    of the opened tiles that still open, the tiles shown now). With know,
    what's on the way and on screen is worked out first (expand)."""
    trail, cur = [], tiles or []
    for k in at or ():
        t = next((x for x in cur if x["key"] == k), None)
        if t is not None and know is not None:
            expand(t, know)
        if t is None or not t.get("kids"):
            break
        trail.append(t)
        cur = t["kids"]
    if know is not None:
        for t in cur:
            expand(t, know)
    return trail, cur


def map_shade(know):
    """A tile's shade: 3 at 90% and up, 2 from 80, 1 from 70, 0 under."""
    return 3 if know >= 90 else 2 if know >= 80 else 1 if know >= 70 else 0


def week(past, ahead, secs_new, secs_answer):
    """Your week in minutes: past [(day, minutes)] as studied, ahead
    [(day, new cards, reviews due)] at my own measured pace (a new card's
    whole first week counted on the day it opens). None without a measured
    pace or with nothing ahead."""
    if not secs_new or not secs_answer or not any(n for _d, n, _r in ahead):
        return None
    fut = [(d, int(round((n * secs_new + r * secs_answer) / 60.0)), n, r) for d, n, r in ahead]
    days = [m for _d, m, _n, _r in fut]
    seen = [m for _d, m in past]
    return {"past": list(past), "ahead": fut, "avg": int(round(sum(days) / len(days))),
            "was": int(round(sum(seen) / len(seen))) if seen else 0}


def fsrs_gap(right, n, target):
    """{right, n, target} when my newest cards (1-3 days since their last
    review) come back FSRS_GAP points or more under my target, with
    FSRS_MIN answers behind it; else None."""
    if n < FSRS_MIN or right is None:
        return None
    pct, tgt = int(round(100.0 * right / n)), int(round(100 * target))
    return {"right": pct, "n": n, "target": tgt} if tgt - pct >= FSRS_GAP else None


def hard_habit(hard, n):
    """3.8.0: {pct, n} when Hard is HARD_SHARE% or more of my review answers
    (4 weeks), with HARD_MIN answers behind it; else None. Anki counts Hard
    as remembered, so a Hard that meant "forgot" schedules it as known.
    Said, never changed: my history stays as it is."""
    if n < HARD_MIN:
        return None
    pct = int(round(100.0 * hard / n))
    return {"pct": pct, "n": n} if pct >= HARD_SHARE else None


# ---- the team ----

def unread(summary, seen):
    """How many of the team's threads moved since I last looked."""
    return sum(1 for a in (summary or {}).get("act") or [] if int(a) > int(seen or 0))


CELLS = (0, 1, 2, 3, 5, 6, 7, 8)
LINES = ((0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6))


def bingo_line(ev):
    """"3 of 9 · one away from bingo", from the team card's counts."""
    def done(c):
        return ev["middle"]["done"] if c == 4 else ev["squares"][CELLS.index(c)]["done"]
    stamps = sum(1 for q in ev["squares"] if q["done"]) + (1 if ev["middle"]["done"] else 0)
    lines = int(ev.get("lines") or 0)
    if lines >= 8:
        state = "the whole card"
    elif lines:
        state = "BINGO" if lines == 1 else f"{lines} lines"
    else:
        left = min(sum(1 for c in line if not done(c)) for line in LINES)
        state = "one away from bingo" if left == 1 else f"{left} away from bingo"
    return f"{stamps} of 9 · {state}"


def closest(card, ev):
    """The names of the cells closest to a line (bingo.closest, on counts)."""
    def done(c):
        return ev["middle"]["done"] if c == 4 else ev["squares"][CELLS.index(c)]["done"]
    best = min(LINES, key=lambda line: sum(1 for c in line if not done(c)))
    return [card["middle"]["name"] if c == 4 else card["squares"][CELLS.index(c)]["title"] for c in best if not done(c)]
