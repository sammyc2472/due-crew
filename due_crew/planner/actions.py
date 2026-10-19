"""Labs (docs/planner.md): the one collection step the planner adds, on the
main thread. Opening a date's or a pick's cards is plan_flow's (the same
step Browse's open takes); this is question IDs' Bring back.

Never suspends, never opens a leech Anki suspended, and changes nothing
it doesn't say: shut cards open (new ones first in line), and the ones seen
before come due over the next few days (Anki's Set due date, keeping their
intervals). One undo step, named."""

from .. import plans as P

BACK_DAYS = 3  # "bring them back over 3 days": due today, tomorrow or the day after


def _rows(col, sql, cids):
    out = []
    cl = sorted({int(c) for c in cids})
    for i in range(0, len(cl), 500):
        chunk = ",".join(str(c) for c in cl[i:i + 500])
        out += col.db.all(sql.format(chunk))
    return out


def reviews(col, cids, opening=()):
    """The review cards among these that Set due date would move: Anki's
    review cards in their own deck (a filtered deck's are being studied
    there), open, or shut and among `opening` (what this step opens)."""
    opening = {int(c) for c in opening}
    rows = _rows(col, "SELECT id, queue FROM cards WHERE type = 2 AND queue IN (2, -1) AND odid = 0 AND id IN ({})", cids)
    return sorted(int(c) for c, q in rows if int(q) == 2 or int(c) in opening)


def bring_back(col, cids, label, days=BACK_DAYS, back=True):
    """Open the shut ones among `cids` (never a leech), new ones first in
    Anki's line, and with `back` the review ones due over the next `days`
    days, as one undo step `label`. {"opened": n, "due": n}; nothing done
    (and no undo step) when there's nothing to do."""
    if not back:
        return {"opened": P.open_cards(col, cids, label, first=True), "due": 0}
    shut = P.openable_ids(col, cids)
    due = reviews(col, cids, shut)
    if not shut and not due:
        return {"opened": 0, "due": 0}
    pos = None
    if hasattr(col, "add_custom_undo_entry"):
        try:
            pos = col.add_custom_undo_entry(label)
        except Exception:
            pos = None
    if shut:
        col.sched.unsuspend_cards(shut)
        P.first_in_line(col, shut)
    if due:
        col.sched.set_due_date(due, "0" if int(days) <= 1 else f"0-{int(days) - 1}")
    if pos is not None and hasattr(col, "merge_undo_entries"):
        try:
            col.merge_undo_entries(pos)
        except Exception:
            pass
    return {"opened": len(shut), "due": len(due)}
