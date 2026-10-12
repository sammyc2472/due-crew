"""3.7.3 a plan's team and its Insights, the pure parts (team_flow.py is the
glue). Insights (3.7.9): the cards Anki won't show me before the plan's
next event that I'd recall under my target by then (FSRS), the topics not
sticking yet (a tag under its resource, read as words), my week in minutes
at my own pace, and Optimize FSRS when my newest cards fall short. Worked
out in my Anki from my own reviews; nothing about it leaves this computer."""

import datetime

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
                     "forgot": len(fg), "cids": sorted(st | fg)})
    rows.sort(key=lambda r: (-(r["stuck"] + r["forgot"]) / r["of"], -r["stuck"], r["name"].lower()))
    return rows[:ROWS]


MAP_MIN = 20     # 3.8.0, the topic map: started cards before a topic gets a tile...
MAP_TILES = 12   # ...and the biggest this many
MAP_WEAK = 200   # a tile's Browse: its weakest cards, at most this many


def topic_map(topics, cards_of, know):
    """3.8.0, the topic map: what I know now, by topic, biggest first.
    topics: as topic_list (or deck_topics) gives them; cards_of(tag): its
    cards; know: {cid: 0..1} for my started cards (FSRS's recall now, or 1
    when its last answer was right). [{key, name, n, know (0-100), cids}]:
    a topic with MAP_MIN started cards, its cids the weakest first. A card
    in two topics counts in both, as Not sticking yet counts it."""
    out = []
    for key, name, _res, tags, _uids in topics:
        cids = set()
        for t in tags:
            cids |= set(cards_of(t))
        mine = [c for c in cids if c in know]
        if len(mine) < MAP_MIN:
            continue
        mine.sort(key=lambda c: (know[c], c))
        avg = sum(know[c] for c in mine) / len(mine)
        out.append({"key": key, "name": name, "n": len(mine), "know": int(round(100 * avg)),
                    "cids": mine[:MAP_WEAK]})
    out.sort(key=lambda t: (-t["n"], t["name"].lower()))
    return out[:MAP_TILES]


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
