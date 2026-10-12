"""3.8.0: Browse › right-click › "Due Crew: why isn't it showing?", the
glue for why.py: the picked cards' facts and their decks' room today,
read here, the sheet (ui/why_dialog.py), and the fixes, each Anki's own
operation as one undoable step. Main thread; nothing is sent."""

import datetime
import time
import traceback

from aqt import mw
from aqt.utils import tooltip

from . import why as W
from .stats.queries import StatsQueries

_open = {}  # the sheet, kept while it's open


def _ids(browser):
    try:
        got = browser.selected_cards() if hasattr(browser, "selected_cards") else browser.selectedCards()
        return [int(c) for c in got]
    except Exception:
        return []


def _short(col, did):
    try:
        return str(col.decks.name(did) or "").split("::")[-1] or "that deck"
    except Exception:
        return "that deck"


def context(col):
    """What why.reason needs to know about today, read from this
    collection once; each deck's room asked of Anki's own deck tree."""
    today = int(col.sched.today)
    label = datetime.date.fromisoformat(StatsQueries(col).day_label(0))
    tree, left, names = None, {}, {}

    def deck(did):
        if did not in names:
            names[did] = _short(col, did)
        return names[did]

    def room(did):
        nonlocal tree
        if did not in left:
            out = {}
            try:
                if tree is None:
                    tree = col.sched.deck_due_tree()
                node = col.decks.find_deck_in_tree(tree, did)
                conf = col.decks.config_dict_for_deck_id(did)
                out = {"new": int(node.new_count) if node else 0, "rev": int(node.review_count) if node else 0,
                       "new_limit": int(conf["new"]["perDay"]), "rev_limit": int(conf["rev"]["perDay"])}
            except Exception:
                traceback.print_exc()
            left[did] = out
        return left[did]

    def rank(c):
        try:
            kids = ",".join(str(int(d)) for d in col.decks.deck_and_child_ids(int(c["did"])))
            return 1 + int(col.db.scalar(
                f"SELECT count() FROM cards WHERE did IN ({kids}) AND queue = 0 AND (due < ? OR (due = ? AND id < ?))",
                int(c["due"]), int(c["due"]), int(c["id"])) or 0)
        except Exception:
            return 1

    def day(n):
        d = label + datetime.timedelta(days=int(n) - today)
        return f"{d:%a} {d.day} {d:%b}"

    def clock(secs):
        t = time.localtime(int(secs))
        return f"{t.tm_hour}:{t.tm_min:02d}"

    try:
        ahead = int(col.get_config("collapseTime", 1200) or 0)
    except Exception:
        ahead = 1200
    try:
        fsrs = bool(col.get_config("fsrs", False))
    except Exception:
        fsrs = False
    return {"today": today, "now": int(time.time()), "ahead": ahead, "deck": deck, "left": room, "rank": rank,
            "size": lambda did: int(col.db.scalar("SELECT count() FROM cards WHERE did = ?", int(did)) or 0),
            "day": day, "clock": clock, "fsrs": fsrs}


def facts(col, cids):
    """The cards as why.reason reads them, in the order picked."""
    cids = [int(c) for c in cids][:W.MOST]
    if not cids:
        return []
    rows = col.db.all(
        f"SELECT c.id, c.did, c.odid, c.queue, c.due, c.lapses, n.tags FROM cards c JOIN notes n ON n.id = c.nid "
        f"WHERE c.id IN ({','.join(str(c) for c in cids)})")
    got = {int(r[0]): {"id": int(r[0]), "did": int(r[1]), "odid": int(r[2] or 0), "queue": int(r[3]), "due": int(r[4]),
                       "lapses": int(r[5] or 0), "leech": " leech " in f" {str(r[6] or '').lower()} "} for r in rows}
    return [got[c] for c in cids if c in got]


def read(cids):
    """[group] for these cards now (why.groups)."""
    col = mw.col
    return W.groups(facts(col, cids), context(col))


def explain(browser):
    """The menu item: the sheet for the picked cards."""
    cids = _ids(browser)
    if not cids or not mw.col:
        tooltip("Pick a card first.")
        return
    try:
        got = read(cids)
    except Exception:
        traceback.print_exc()
        tooltip("Couldn't read those cards.")
        return
    from .ui.why_dialog import WhyDialog
    dlg = WhyDialog(browser, got, lambda g: fix(g, dlg, cids), len(cids) > W.MOST)
    _open["dlg"] = dlg
    dlg.show()


def fix(g, dlg, cids):
    """A group's fix, as Anki would do it (one undo step), then the sheet
    reads the cards again."""
    act, ids = g["fix"][0], list(g["cids"])

    def again(_=None):
        try:
            dlg.show_groups(read(cids))
        except Exception:
            traceback.print_exc()
    if act == "study":
        mw.col.decks.select(int(g["fix"][1]))
        mw.moveToState("overview")
        mw.activateWindow()
        return
    from aqt.operations import CollectionOp
    if act == "unsuspend":
        run = lambda col: col.sched.unsuspend_cards(ids)  # noqa: E731
    elif act == "unbury":
        run = lambda col: col.sched.unbury_cards(ids)  # noqa: E731
    elif act == "due_now":
        run = lambda col: col.sched.set_due_date(ids, "0")  # noqa: E731
    elif act == "empty":
        run = lambda col: col.sched.empty_filtered_deck(int(g["fix"][1]))  # noqa: E731
    elif act in ("more_new", "more_rev"):
        from anki.scheduler.base import CustomStudyRequest
        did, n = int(g["fix"][1]), int(g["fix"][2])
        req = (CustomStudyRequest(deck_id=did, new_limit_delta=n) if act == "more_new"
               else CustomStudyRequest(deck_id=did, review_limit_delta=n))
        run = lambda col: col.sched.custom_study(req)  # noqa: E731
    else:
        return
    CollectionOp(parent=dlg, op=run).success(again).run_in_background()
