"""QBank QIDs' two collection steps (docs/planner.md), on the main thread:
Unsuspend, and Study now's deck. Opening a date's or a pick's cards is
plan_flow's (the same step Browse's open takes).

Never suspends, never opens a leech Anki suspended, never moves a due date
(3.9.3, Sam: a card I know comes back when Study now asks it, and my answer
there reschedules it: Again is a lapse, Good an early review). Each is one
undo step, named."""

from .. import plans as P

DECK = "QBank cards"  # Study now's deck, under Due Crew: each paste adds to it


def unsuspend(col, cids, label):
    """The suspended ones among `cids`, never a leech, unsuspended and the
    new ones first in Anki's line, as one undo step `label`: how many (0:
    none were, and no undo step)."""
    return P.open_cards(col, cids, label, first=True)


def in_deck(col, name):
    """The cards in the deck `name` now: Study now's keeps what's not done."""
    did = col.decks.id_for_name(name)
    return [int(c) for c in col.db.list("SELECT id FROM cards WHERE did = ?", int(did))] if did else []


def _studyable(col, cids):
    """The ones among `cids` a filtered deck can take: not suspended, not
    buried, not in another filtered deck."""
    out = []
    cl = sorted({int(c) for c in cids})
    for i in range(0, len(cl), 500):
        chunk = ",".join(str(c) for c in cl[i:i + 500])
        out += col.db.list(f"SELECT id FROM cards WHERE queue >= 0 AND odid = 0 AND id IN ({chunk})")
    return [int(c) for c in out]


def study(col, cids, label, name, build):
    """Study now: the suspended ones among `cids` unsuspended (never a
    leech), new ones first in line, and the deck `name` built over what's in
    it already and these, by build(card ids) (plan_flow._filtered: Anki's
    filtered deck, rescheduling by my answers), as one undo step `label`.
    (how many unsuspended, how many in the deck now); (0, 0) and no undo
    step when none of them can go in, or is in it already."""
    shut = P.openable_ids(col, cids)
    if not shut and not _studyable(col, cids) and not {int(c) for c in cids} & set(in_deck(col, name)):
        return 0, 0
    pos = None
    if hasattr(col, "add_custom_undo_entry"):
        try:
            pos = col.add_custom_undo_entry(label)
        except Exception:
            pos = None
    try:
        if shut:
            col.sched.unsuspend_cards(shut)
            P.first_in_line(col, shut)
        want = sorted(set(in_deck(col, name)) | set(_studyable(col, cids)))
        took = bool(want) and build(want)
    finally:
        if pos is not None and hasattr(col, "merge_undo_entries"):
            try:
                col.merge_undo_entries(pos)
            except Exception:
                pass
    return len(shut), (len(in_deck(col, name)) if took else 0)
