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
        entry = {
            "name": name.split("::")[-1],
            "sig": deck_signature(col, did),
            "total": total,
            "seen": seen,
            "mature": mature,
            "open": max(opened, seen),
            # `today` is only true on `day`; a reader on another day drops it
            "day": StatsQueries(col).day_label(0),
        }
        # the same privacy switches as the board's columns
        if cfg.get("share_reviews", True):
            entry["today"] = today
        if cfg.get("share_retention", True) and graded:
            entry["ret"] = round(correct / graded * 100, 1)
        out.append(entry)
    return out
