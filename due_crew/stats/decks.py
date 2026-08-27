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

SIG_SIZE = 20
MATCH_MIN = 8
MATURE_IVL = 21


def sig_match(a, b):
    if not a or not b:
        return False
    return len(set(a) & set(b)) >= MATCH_MIN


def all_deck_counts(col):
    """{did: [total, seen, mature]} over ALL cards, suspended included.
    Cards sitting in filtered decks are credited to their home deck (odid)."""
    counts = {}
    for did, total, seen, mature in col.db.all(
            "SELECT did, COUNT(*), COUNT(CASE WHEN type != 0 THEN 1 END), "
            "COUNT(CASE WHEN ivl >= %d THEN 1 END) FROM cards "
            "WHERE odid = 0 GROUP BY did" % MATURE_IVL):
        counts[int(did)] = [total, seen, mature]
    for odid, total, seen, mature in col.db.all(
            "SELECT odid, COUNT(*), COUNT(CASE WHEN type != 0 THEN 1 END), "
            "COUNT(CASE WHEN ivl >= %d THEN 1 END) FROM cards "
            "WHERE odid != 0 GROUP BY odid" % MATURE_IVL):
        base = counts.setdefault(int(odid), [0, 0, 0])
        base[0] += total
        base[1] += seen
        base[2] += mature
    return counts


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
    table = None
    for did in cfg.get("shared_decks") or []:
        try:
            if not col.decks.get(int(did), default=False):
                continue  # deck was deleted
            if table is None:
                table = all_deck_counts(col)
            name = col.decks.name(int(did))
            total, seen, mature = subtree_counts(col, did, table)
        except Exception:
            continue
        if not total:
            continue
        out.append({
            "name": name.split("::")[-1],
            "sig": deck_signature(col, did),
            "total": total,
            "seen": seen,
            "mature": mature,
        })
    return out
