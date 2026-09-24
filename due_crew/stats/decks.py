"""Shared-deck progress: counts and fingerprints. Local SQL only.

A deck's fingerprint is its 20 lexicographically smallest note GUIDs. GUIDs
survive deck sharing, so two people's copies of the same imported deck
(AnKing/AnkiHub included) produce overlapping fingerprints; independently
made decks don't — by design. Two decks match when fingerprints overlap on
at least MATCH_MIN entries, which tolerates version drift and partial copies.

Counting never runs per-deck queries with un-indexed OR shapes: use
all_deck_counts() (two grouped passes over cards, indexes used) and roll up
subtrees from it.
"""

from .queries import StatsQueries

SIG_SIZE = 20
MATCH_MIN = 8
MATURE_IVL = 21
RET_DAYS = 7


def sig_match(a, b):
    if not a or not b:
        return False
    return len(set(a) & set(b)) >= MATCH_MIN


def crew_matches(sig, entries):
    """Names of crewmates sharing a deck that matches this fingerprint. My
    own entry is skipped: it carries the decks I already share, so a deck I
    share used to read "matches <me>"."""
    names = []
    for e in entries or []:
        if e.get("you"):
            continue
        if any(sig_match(sig, d.get("sig")) for d in e.get("decks") or []):
            names.append(e["name"])
    return names


def all_deck_counts(col):
    """{did: [total, seen, mature, open]} over ALL cards, suspended included.
    `open` = unsuspended, or already seen: what this person has unlocked.
    People who work through a big shared deck by unsuspending it a topic at
    a time (the usual way with AnKing) read as "12% seen" forever without
    it; with it the bar says how much is in play and how much of THAT is
    done. Cards sitting in filtered decks are credited to their home deck."""
    cols = ("COUNT(*), COUNT(CASE WHEN type != 0 THEN 1 END), "
            "COUNT(CASE WHEN ivl >= %d THEN 1 END), "
            "COUNT(CASE WHEN queue != -1 OR type != 0 THEN 1 END)" % MATURE_IVL)
    counts = {}
    for did, total, seen, mature, opened in col.db.all(
            f"SELECT did, {cols} FROM cards WHERE odid = 0 GROUP BY did"):
        counts[int(did)] = [total, seen, mature, opened]
    for odid, total, seen, mature, opened in col.db.all(
            f"SELECT odid, {cols} FROM cards WHERE odid != 0 GROUP BY odid"):
        base = counts.setdefault(int(odid), [0, 0, 0, 0])
        for i, v in enumerate((total, seen, mature, opened)):
            base[i] += v
    return counts


def deck_activity(col, days=RET_DAYS):
    """{did: [answers_today, correct, graded]} — today's answers, and the
    last `days` days of graded answers (learn/review/relearn; Again = wrong,
    the board's own retention rule), credited to each card's home deck. One
    pass: revlog is range-scanned by id, cards joined by primary key."""
    cutoff = int(col.sched.day_cutoff)
    rows = col.db.all(
        "SELECT CASE WHEN c.odid != 0 THEN c.odid ELSE c.did END, "
        "COUNT(CASE WHEN r.id >= ? THEN 1 END), "
        "COUNT(CASE WHEN r.type IN (0, 1, 2) AND r.ease > 1 THEN 1 END), "
        "COUNT(CASE WHEN r.type IN (0, 1, 2) THEN 1 END) "
        "FROM revlog r JOIN cards c ON c.id = r.cid "
        "WHERE r.id >= ? AND r.id < ? AND r.ease > 0 GROUP BY 1",
        (cutoff - 86400) * 1000, (cutoff - days * 86400) * 1000, cutoff * 1000)
    return {int(did): [int(t or 0), int(c or 0), int(g or 0)] for did, t, c, g in rows or []}


def subtree_extra(col, did, table, activity):
    """(open, answers_today, correct, graded) summed over a deck's subtree."""
    opened = today = correct = graded = 0
    for deck_id in subtree_ids(col, did):
        row = table.get(deck_id)
        if row and len(row) > 3:
            opened += row[3]
        act = activity.get(deck_id)
        if act:
            today, correct, graded = today + act[0], correct + act[1], graded + act[2]
    return opened, today, correct, graded


def subtree_ids(col, did):
    return [int(did)] + [int(i) for i in col.decks.deck_and_child_ids(int(did))
                         if int(i) != int(did)]


def subtree_counts(col, did, table=None):
    """(total, seen, mature) for a deck and its children."""
    table = table if table is not None else all_deck_counts(col)
    total = seen = mature = 0
    for deck_id in subtree_ids(col, did):
        row = table.get(deck_id)
        if row:
            total += row[0]
            seen += row[1]
            mature += row[2]
    return total, seen, mature


def deck_signature(col, did):
    ids = ",".join(str(i) for i in subtree_ids(col, did))
    rows = col.db.all(
        "SELECT DISTINCT n.guid FROM notes n JOIN cards c ON c.nid = n.id "
        "WHERE c.did IN (%s) ORDER BY n.guid LIMIT %d" % (ids, SIG_SIZE))
    return [r[0] for r in rows]


# fingerprints for the day: (did, day label, card count) -> guids. The deck's
# 20 smallest note guids only change when its notes do, and a sort over a
# big deck's notes cost 31 ms of main thread per sync until 2.9.
_SIG_CACHE = {}


def deck_signature_cached(col, did, day, total):
    key = (int(did), str(day), int(total))
    if key not in _SIG_CACHE:
        if len(_SIG_CACHE) > 256:
            _SIG_CACHE.clear()
        _SIG_CACHE[key] = deck_signature(col, did)
    return _SIG_CACHE[key]


def clear_cache():
    """A profile switch: another collection, whose deck ids mean other decks."""
    _SIG_CACHE.clear()


def local_matches(col, crew, names):
    """{did: [crewmate names]}: which of my decks pair with a deck someone in
    my crew shares, by the board's own test (sig_match on fingerprints).
    `names`: {did: full deck name}. A deck can only pair with a crew deck
    if its subtree holds MATCH_MIN of that deck's fingerprint guids, so one
    query over every crew fingerprint finds the candidates, and only those
    are fingerprinted and tested. Until 2.9 the Shared Decks dialog
    fingerprinted every deck in the collection to find out."""
    wanted = []
    for e in crew or []:
        if e.get("you"):
            continue
        for d in e.get("decks") or []:
            sig = [g for g in d.get("sig") or [] if isinstance(g, str)]
            if sig:
                wanted.append((e["name"], sig))
    guids = sorted({g for _n, sig in wanted for g in sig})
    if not guids:
        return {}
    homes = {}
    for i in range(0, len(guids), 500):  # SQLite's parameter cap on old builds
        chunk = guids[i:i + 500]
        for guid, did in col.db.all(
                "SELECT DISTINCT n.guid, CASE WHEN c.odid != 0 THEN c.odid ELSE c.did END "
                "FROM notes n JOIN cards c ON c.nid = n.id "
                f"WHERE n.guid IN ({','.join('?' * len(chunk))})", *chunk):
            homes.setdefault(guid, set()).add(int(did))
    by_name = {name: did for did, name in names.items()}

    def up(did):
        """The deck and its ancestors, by name."""
        parts = str(names.get(did, "")).split("::")
        return {by_name[p] for p in ("::".join(parts[:k]) for k in range(1, len(parts) + 1))
                if p in by_name}

    reach = {g: set().union(*(up(d) for d in ds)) for g, ds in homes.items()}
    out = {}
    for who, sig in wanted:
        count = {}
        for g in sig:
            for did in reach.get(g, ()):
                count[did] = count.get(did, 0) + 1
        for did, n in count.items():
            if n >= MATCH_MIN and sig_match(deck_signature(col, did), sig):
                if who not in out.setdefault(did, []):
                    out[did].append(who)
    return out


def gather_shared_decks(col, cfg):
    """Upload payload: one entry per configured shared deck. Main thread."""
    out = []
    table = activity = None
    for did in cfg.get("shared_decks") or []:
        try:
            if not col.decks.get(int(did), default=False):
                continue  # deck was deleted
            if table is None:
                table = all_deck_counts(col)
                activity = deck_activity(col)
            name = col.decks.name(int(did))
            total, seen, mature = subtree_counts(col, did, table)
            opened, today, correct, graded = subtree_extra(col, did, table, activity)
        except Exception:
            continue
        if not total:
            continue
        today_label = StatsQueries(col).day_label(0)
        entry = {
            "name": name.split("::")[-1],
            "sig": deck_signature_cached(col, did, today_label, total),
            "total": total,
            "seen": seen,
            "mature": mature,
            "open": max(opened, seen),
            # `today` is only true on `day`; a reader on another day drops it
            "day": today_label,
        }
        # the same privacy switches as the board's columns
        if cfg.get("share_reviews", True):
            entry["today"] = today
        if cfg.get("share_retention", True) and graded:
            entry["ret"] = round(correct / graded * 100, 1)
        out.append(entry)
    return out
