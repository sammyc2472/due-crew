"""Plans, the glue in Anki's browser: Show on my plan, Due's opens, open from Browse."""

import html
import os

from aqt import mw
from aqt.utils import tooltip

from .. import app
from .. import plans as P
from .. import schedule as S
from ..app import _state
from ..app import cfg
from ..app import client
from ..errs import oops

from .morning import NEW_ORDER, _after_change, _deck_name, _filtered, _state_cfg, _tags_changed
from .cards import _claim
from .state import _deck_ok, _pcfg, _plan_doc, _psave, _swap, _today, followed
from .days import _plan_idx
from .following import _signed_in
from .lessons import lesson_sync, refresh_progress, show_plans


# ---- Anki's browser ----

def browser_menu(browser, menu):
    """gui_hooks.browser_will_show_context_menu: why a card isn't showing
    (3.8.0, signed in or not: it's Anki help); single cards onto a date.
    3.8.1: the ones for writing a plan only for someone who writes one."""
    menu.addSeparator()
    from .. import why_flow
    why = menu.addAction("Due Crew: why isn't it showing?")
    why.triggered.connect(lambda: why_flow.explain(browser))
    opn = menu.addAction("Due Crew: open these…")  # 3.8.0: never suspends; leeches stay
    opn.triggered.connect(lambda: open_these(browser))
    from .. import magic_flow
    if magic_flow.on():  # 3.9.7: the picked cards in Magic search: study them, keep them, put them on days
        mg = menu.addAction("Due Crew: put on a day…")
        mg.triggered.connect(lambda: magic_flow.from_browser(browser))
    if not client().signed_in:
        return
    if client().session.get("plans_authored"):  # the plans I write or co-author, from the day's refresh
        action = menu.addAction("Due Crew: add to a plan…")
        action.triggered.connect(lambda: add_to_plan(browser))
        tag = menu.addAction("Due Crew: tag for a plan…")  # 3.8.0: plan tags
        tag.triggered.connect(lambda: tag_for_plan(browser))
        if _one_card(browser):  # 3.8.1: a note on one card, for the plan's followers
            note = menu.addAction("Due Crew: note for the plan's followers…")
            note.triggered.connect(lambda: note_for_card(browser))
        copy = menu.addAction("Due Crew: copy as plan selector")
        copy.triggered.connect(lambda: copy_selector(browser))
        out = menu.addAction("Due Crew: export for my AI…")
        out.triggered.connect(lambda: export_selected(browser))
    if followed():
        where = menu.addAction("Due Crew: show on my plan")
        where.triggered.connect(lambda: show_on_plan(browser))


# ---- 3.9.5: Browse's Due column says when a plan opens a suspended card ----

OPENS_FOR = 60  # seconds the cards' days are kept while Browse is open (Browse opening again works them out again)
_OPENS = {"key": None, "at": 0.0, "cards": {}, "said": False}


def opens_reset():
    """Browse opening, or a morning's open: the cards' days are worked out again at the next row."""
    _OPENS["key"] = None


def opens_map():
    """{card: (day, plan's name)} for the cards the plans I follow open on a
    day ahead (plans.opens_ahead), the soonest plan's when two have it.
    Main thread (Browse asks for its rows there); the decks' index is
    the morning's own (DeckIndex, kept between reads). Nothing is sent."""
    import time
    today = _today()
    key = (app.generation, today)
    if _OPENS["key"] == key and time.time() - _OPENS["at"] < OPENS_FOR:
        return _OPENS["cards"]
    cards = {}
    state = _state_cfg()
    for p in followed():
        st = state.get(p["id"])
        if not st or not mw.col or not _deck_ok(mw.col, st.get("deck_id")):
            continue
        ahead = P.opens_ahead(P.units(p["doc"]), st.get("applied"), today, own=P.own_pace(p), paused=bool(p.get("paused")),
                              sched=bool(p.get("sched")))
        if not ahead:
            continue
        idx = P.DeckIndex(mw.col, st["deck_id"])
        name = str(p.get("name") or "Plan")
        for day, u in ahead:
            for cid in idx.match(u, _swap(st), p["doc"]):
                if cid not in cards or day < cards[cid][0]:
                    cards[cid] = (day, name)
    _OPENS.update(key=key, at=time.time(), cards=cards)
    return cards


def browser_row(item, is_note, row, columns):
    """gui_hooks.browser_did_fetch_row (Sam: "I want to be able to see if a
    card will be unsuspended by a plan in the due column"): a suspended card
    a plan opens on a day says the day and the plan in Due, "Thu 5 Nov ·
    Heme 2" (plans.opens_words). A leech never opens, so it keeps Anki's
    words; so does every other card, and Notes mode. Never raises: Anki
    drops a row hook that does."""
    try:
        if is_note or "cardDue" not in columns or not mw.col:
            return
        got = opens_map().get(int(item))
        if not got:
            return
        q = mw.col.db.first("SELECT c.queue, n.tags FROM cards c JOIN notes n ON n.id = c.nid WHERE c.id = ?", int(item))
        if not q or int(q[0]) != -1 or " leech " in f" {str(q[1] or '').lower()} ":
            return
        row.cells[list(columns).index("cardDue")].text = P.opens_words(got[0], got[1], _today())
    except Exception as e:
        if not _OPENS["said"]:  # once: stderr would be Anki's error window at every row
            _OPENS["said"] = True
            print(f"due crew: Browse's Due column: {e!r}")


# ---- 3.8.0: open from Browse (a tag in the sidebar, or the picked cards) ----

def sidebar_menu(sidebar, menu, item, index):
    """gui_hooks.browser_sidebar_will_show_context_menu: a tag's Due Crew: open its cards…"""
    try:
        from aqt.browser.sidebar.item import SidebarItemType
        if item is None or item.item_type != SidebarItemType.TAG:
            return
        tag = str(item.full_name or "")
    except Exception:
        return
    if not tag:
        return
    menu.addSeparator()
    parent = getattr(sidebar, "browser", None) or mw
    menu.addAction("Due Crew: open its cards…").triggered.connect(lambda: open_tag(parent, tag))


def _tag_words(tag):
    """"#Videos::Micro::12_Strep" -> ("12 Strep", "#Videos › Micro › 12 Strep")."""
    parts = [x.replace("_", " ").strip() or x for x in str(tag).split("::")]
    return parts[-1], " › ".join(parts)


def open_tag(parent, tag):
    """A tag's cards, its children's too."""
    if not mw.col:
        return
    try:
        cids = mw.col.find_cards(P.tag_search(tag) + '"')
    except Exception:
        oops()
        return
    title, where = _tag_words(tag)
    _open_sheet(parent, cids, title, where)


def open_these(browser):
    if not mw.col:
        return
    try:
        cids = browser.selected_cards() if hasattr(browser, "selected_cards") else browser.selectedCards()
    except Exception:
        oops()
        return
    if not cids:
        tooltip("Select some cards first.")
        return
    _open_sheet(browser, cids, None, "")


def _on_plans(cids):
    """Lines for the sheet: the plans I follow whose dates hold some of these."""
    out, want = [], {int(c) for c in cids}
    state = _state_cfg()
    for p in followed():
        st = state.get(p["id"])
        if not st or not _deck_ok(mw.col, st.get("deck_id")):
            continue
        idx = P.DeckIndex(mw.col, st["deck_id"])
        names = [str(u.get("name") or "?") for u in P.units(p["doc"])
                 if idx.match(u, _swap(st), p["doc"]) & want]
        if names:
            out.append(f"On {p.get('name') or 'a plan'}: {', '.join(names[:3])}"
                       + (f" and {len(names) - 3} more" if len(names) > 3 else "") + ", which count them")
        if len(out) == 2:
            break
    return out


def _open_sheet(parent, cids, title, where):
    counts = P.open_counts(mw.col, cids)
    try:
        plans = _on_plans(cids) if counts["open"] else []
    except Exception:
        oops()
        plans = []
    from ..ui.open_dialog import OpenDialog
    OpenDialog(parent, title, where, counts, plans,
               on_open=lambda first, study: open_cards_now(cids, title or "the picked cards", first, study)).exec()


def open_cards_now(cids, name, first=True, study=False):
    """Open them (never a leech, never suspends), first in line when asked, as
    one undo step; at my own pace, a date now all open counts as opened; with
    study, a Due Crew deck of the new ones, and into it."""
    if not mw.col:
        return 0
    shut = P.openable_ids(mw.col, cids)  # what this open unsuspends
    label = f"Due Crew: open {name}"
    n = P.open_cards(mw.col, cids, label, first=first)
    if n:
        _after_change()
    try:
        _claim_opened(shut if n else ())
    except Exception:
        oops()
    if n and not study:  # B: the lessons they're on, in decks of their own, in this undo step (Study makes its own)
        lesson_sync(followed(), fold=label)
    refresh_progress()
    if study:
        cl = sorted({int(c) for c in cids})
        new = []
        for i in range(0, len(cl), 500):
            chunk = ",".join(str(c) for c in cl[i:i + 500])
            new += mw.col.db.list(f"SELECT id FROM cards WHERE type = 0 AND queue = 0 AND id IN ({chunk})")
        deck = _deck_name(name)
        if new and _filtered(mw.col, deck, new, order=NEW_ORDER):
            _after_change()
            did = mw.col.decks.id_for_name(deck)
            if did:
                mw.col.decks.select(did)
                mw.moveToState("overview")
    if n:
        tooltip(f"Opened {n:,}{' · first in line' if first else ''}. Edit › Undo puts them back.", period=5000)
    app.swap(cfg())
    return n


def _claim_opened(touched):
    """At my own pace, a date whose cards are all open now because Browse
    opened some of them (`touched`, what that open unsuspended; leeches
    aside) counts as opened today, so Up next moves on. 3.8.1: only such a
    date; before, every date already all open counted too, so on a deck
    whose cards were all active one open from Browse opened the whole plan."""
    touched = {int(x) for x in touched or ()}
    if not touched:
        return False
    c = _pcfg()
    state = _state_cfg(c)
    today, changed = _today(), False
    for p in followed():
        st = state.get(p["id"])
        if not P.own_pace(p) or not st or not _deck_ok(mw.col, st.get("deck_id")):
            continue
        if _claim(P.DeckIndex(mw.col, st["deck_id"]), st, p["doc"], today, touched):
            changed = True
    if changed:
        c["plans"] = state
        _psave(c)
    return changed


def show_on_plan(browser):
    """3.8.0: the board on the plan date that has the card picked in the
    browser: You › Plans, that date's week, its details open. The first
    plan I follow that has it; within it, the date nearest today."""
    try:
        cids = [int(c) for c in (browser.selected_cards() if hasattr(browser, "selected_cards") else browser.selectedCards())]
    except Exception:
        cids = []
    if not cids or not mw.col:
        tooltip("Pick a card first.")
        return
    today = _today()
    for p in followed():
        got = _plan_idx(p["id"])
        if not got:
            continue
        _p, st, doc, idx = got
        try:
            us = P.dates_with(idx, doc, cids, _swap(st))
        except Exception:
            oops()
            continue
        if not us:
            continue
        u = min(us, key=lambda x: abs((S.d(str(x["opens"])) - S.d(today)).days))
        jump_to(p["id"], str(u["opens"]))
        tooltip(f"{html.escape(P.plan_title(p))}: {html.escape(str(u.get('name') or '?'))}, {P.fmt_day(u['opens'])}")
        return
    tooltip("It isn't on a plan you follow.")


def jump_to(pid, day):
    """You › Plans on `day`'s week of this plan, the day's details open."""
    today = _today()
    weeks = (S.d(P.week_start(day)) - S.d(P.week_start(today))).days // 7
    _state.setdefault("plan_week", {})[pid] = max(-26, min(26, weeks))
    _state["plan_focus"] = {pid: day}
    c = cfg()
    c["plan_pick"] = pid  # with two or more plans, this one stays shown once the day lets go
    show_plans(c, swap=False)
    if getattr(mw, "state", "") != "deckBrowser":
        mw.moveToState("deckBrowser")
    app.swap(c)
    try:
        mw.activateWindow()
        mw.raise_()
    except Exception:
        pass


def open_export():
    """3.6.5, P3: Tools › Due Crew › Export cards for my AI…"""
    if not mw.col:
        return
    from ..ui.export_dialog import ExportDialog
    cl = client()
    ExportDialog(mw, mw.col, cl if cl.signed_in else None, followed(), _state_cfg(), on_saved=_saved).exec()


def _saved(n, path):
    tooltip(f"Saved {n:,} note{'s' if n != 1 else ''} to {html.escape(os.path.basename(path))}. "
            "Attach it to your AI chat with the prompt.")


def export_selected(browser):
    """3.6.5, P3: the notes selected in the browser (their notes, in Cards
    mode), to a file for my AI."""
    if not mw.col:
        return
    try:
        nids = browser.selected_notes() if hasattr(browser, "selected_notes") else browser.selectedNotes()
    except Exception:
        oops()
        return
    if not nids:
        tooltip("Select some notes first.")
        return
    from aqt.qt import QFileDialog
    from ..ui.export_dialog import save
    desk = os.path.join(os.path.expanduser("~"), "Desktop")
    start = os.path.join(desk if os.path.isdir(desk) else os.path.expanduser("~"), "cards-for-my-ai.txt")
    path, _ = QFileDialog.getSaveFileName(browser, "Export for my AI", start, "Text (*.txt)")
    if path:
        save(mw.col, nids, path, True, _saved)


def copy_selector(browser):
    """3.6.5: the selected notes (Notes mode) or cards (Cards mode) as
    notes:… or cards:…, for a date in the builder's Text or Add cards box."""
    if not mw.col:
        return
    table = getattr(browser, "table", None)
    try:
        notes_mode = bool(table is not None and hasattr(table, "is_notes_mode") and table.is_notes_mode())
    except Exception:
        notes_mode = False
    try:
        if notes_mode:
            picked = browser.selected_notes() if hasattr(browser, "selected_notes") else browser.selectedNotes()
            text, n = P.selector(mw.col, nids=picked)
        else:
            picked = browser.selected_cards() if hasattr(browser, "selected_cards") else browser.selectedCards()
            text, n = P.selector(mw.col, cids=picked)
    except Exception:
        oops()
        return
    if not n:
        tooltip("Select some notes or cards first.")
        return
    from aqt.qt import QApplication
    QApplication.clipboard().setText(text)
    what = f"{n:,} note{'s' if n != 1 else ''}" if notes_mode else f"{n:,} card{'s' if n != 1 else ''}"
    tooltip(f"Copied {what}. Paste into a set on duecrew.com." + (" A set takes up to 5,000." if n > 5000 else ""))


def tag_for_plan(browser):
    """3.8.0, Browse › Due Crew: tag for a plan…: the picked notes onto one of
    a plan's own tags (or off it). The plan gets their guids; this Anki gets
    the tag at once, in one undo step; followers with the plan's update."""
    if not mw.col or not _signed_in():
        return
    try:
        nids = browser.selected_notes() if hasattr(browser, "selected_notes") else browser.selectedNotes()
    except Exception:
        oops()
        return
    nids = [int(n) for n in nids or []]
    if not nids:
        tooltip("Select some notes first.")
        return
    guid_of = {}
    for i in range(0, len(nids), 500):
        part = nids[i:i + 500]
        for nid, g in mw.col.db.all(f"SELECT id, guid FROM notes WHERE id IN ({','.join(str(n) for n in part)})"):
            guid_of[int(nid)] = str(g)
    from ..ui.tag_dialog import TagDialog

    def outside(p):
        """How many picked notes have no card in the plan's deck here: a follower's
        Anki tags inside the plan's deck only."""
        want = str(((p or {}).get("doc") or {}).get("deck") or "").lower()
        dids = [d for d, n in P.deck_choices(mw.col) if want and (n.lower() == want or n.lower().startswith(want + "::"))]
        if not dids:
            return 0
        ds = ",".join(str(d) for d in dids)
        inside = set()
        for i in range(0, len(nids), 500):
            part = ",".join(str(n) for n in nids[i:i + 500])
            inside |= {int(n) for n in mw.col.db.list(
                f"SELECT DISTINCT nid FROM cards WHERE nid IN ({part}) AND (did IN ({ds}) OR odid IN ({ds}))")}
        return len(set(nids) - inside)

    def done(plan, name, path, added, taken):
        by_guid = {g: n for n, g in guid_of.items()}
        mine = [by_guid[g] for g in (added or taken) if g in by_guid]
        if mine and path.lower().startswith(P.TAG_PARENT.lower() + "::"):
            pos = None
            try:
                pos = mw.col.add_custom_undo_entry(f"Due Crew: {'take off' if taken else 'tag'} {name}")
            except Exception:
                pos = None
            for i in range(0, len(mine), 5000):
                (mw.col.tags.bulk_remove if taken else mw.col.tags.bulk_add)(mine[i:i + 5000], path)
            if pos is not None:
                try:
                    mw.col.merge_undo_entries(pos)
                except Exception:
                    pass
            _tags_changed()
        # following my own plan: this copy has it already, so its update doesn't call it new
        c = _pcfg()
        st = _state_cfg(c).get(plan.get("id"))
        doc = _plan_doc(plan)
        t = next((x for x in P.plan_tags(doc) if P.tag_path(doc, x).lower() == path.lower()), None)
        if t and not taken:
            if st is not None:
                st.setdefault("tags", {})[str(t["id"])] = path
            else:  # a plan I write: its pass here doesn't call it new either
                c.setdefault("authored_tags", {}).setdefault(plan.get("id"), {}).setdefault("tags", {})[str(t["id"])] = path
            _psave(c)
        n = len(added or taken)
        tooltip((f"Took {n:,} note{'s' if n != 1 else ''} off {html.escape(name)}."
                 if taken else f"Tagged {n:,} note{'s' if n != 1 else ''} as {html.escape(name)}. ")
                + ("" if taken else f"{html.escape(plan.get('name') or 'The plan')}'s followers get it with its next update."),
                period=5000)

    TagDialog(browser, client(), [guid_of[n] for n in nids if n in guid_of], on_done=done, outside=outside).exec()


def _one_card(browser):
    """3.8.1: the browser has exactly one card picked (a note of one card, in Notes)."""
    try:
        return len(browser.selected_cards() if hasattr(browser, "selected_cards") else browser.selectedCards()) == 1
    except Exception:
        return False


def note_for_card(browser):
    """3.8.1, Browse › Due Crew: note for the plan's followers…: one line on
    one card, for everyone following a plan I write or co-author; it shows
    when that card comes up for them. The plan gets the card's guid and
    number and my words, never the card's text; one note a card a plan,
    edited or taken off here."""
    if not mw.col or not _signed_in():
        return
    try:
        cids = browser.selected_cards() if hasattr(browser, "selected_cards") else browser.selectedCards()
    except Exception:
        oops()
        return
    refs = P.card_refs(mw.col, cids) if len(cids or []) == 1 else []
    if not refs:
        tooltip("Select one card first.")
        return
    from ..ui.remark_dialog import RemarkDialog
    RemarkDialog(browser, client(), refs[0][0], refs[0][1], on_done=lambda text: tooltip(html.escape(text), period=5000)).exec()


def add_to_plan(browser):
    if not mw.col or not _signed_in():
        return
    table = getattr(browser, "table", None)
    try:
        notes_mode = bool(table is not None and hasattr(table, "is_notes_mode") and table.is_notes_mode())
    except Exception:
        notes_mode = False
    # 3.3, C3: the search in the browser's box, and how many cards it finds
    try:
        search = browser.form.searchEdit.lineEdit().text().strip()
    except Exception:
        search = ""
    if not P.shareable_search(search):
        search = ""  # Anki's own deck:current, or a search about my reviews: not for a plan
    try:
        search_n = len(mw.col.find_cards(search)) if search else 0
    except Exception:
        search, search_n = "", 0
    cids = []
    if not notes_mode:
        # a note's row is all its cards; exact cards come from Cards mode
        try:
            cids = browser.selected_cards()
        except AttributeError:
            cids = browser.selectedCards()
    if not cids and not search:
        tooltip("Switch the browser to Cards to add single cards to a plan." if notes_mode
                else "Search for the cards (a tag, say), or select them, first.")
        return
    refs = P.card_refs(mw.col, cids) if cids else []  # which cards, never their text
    from ..ui.add_cards_dialog import AddCardsDialog

    def added(plan, n):
        tooltip(f"Added {n:,} card{'s' if n != 1 else ''} to {html.escape(plan.get('name') or 'the plan')}.")

    AddCardsDialog(browser, client(), refs, _today(), on_added=added, search=search, search_n=search_n).exec()
