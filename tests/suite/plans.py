"""The suite: plans (3.1, 3.2): the morning, a follower's days, schedules, who knows this."""

from due_crew import board
from due_crew.stats.queries import StatsQueries
import datetime
import fakes
import json
import os
import re
import sqlite3
import srcs
import sys
import tempfile
import types

from .base import KK, REPO, TODAY, acked, as_board, check, make_user_col, new_client, world
from .board import _day, _open, _plan_col, _plan_units, _queues


def test_plans_events_f1():
    """F1: events are named days the dates prep for; the plan card says
    what today's studying leads up to, and how many prep days are left."""
    from due_crew import plans as P, board
    from due_crew.backend import shapes
    doc = shapes.clean_plan_doc({"deck": "Step 1",
        "events": [{"id": "q1", "day": "2026-10-15", "name": "Micro <quiz>"}, {"id": "x", "day": "soon", "name": "bad"}],
        "units": [{"id": "a", "name": "Staph", "opens": "2026-10-12", "for": "q1"},
                  {"id": "b", "name": "Strep", "opens": "2026-10-13", "for": "q1"},
                  {"id": "c", "name": "Entero", "opens": "2026-10-14", "for": "q1"},
                  {"id": "d", "name": "Clostridium", "opens": "2026-10-16"}]})
    check("events: cleaned on arrival, a bad day dropped", [e["id"] for e in doc.get("events", [])] == ["q1"], str(doc.get("events")))
    pf = P.prep_for(doc, "2026-10-12")
    check("events: today preps for the quiz, two more days to go", pf == {"name": "Micro <quiz>", "day": "2026-10-15", "left": 2, "today": False}, str(pf))
    check("events: on its day it says so", P.prep_for(doc, "2026-10-15")["today"] is True)
    check("events: nothing once it's past", P.prep_for(doc, "2026-10-16") is None)
    html = board._plan_card_html({"id": "p", "title": "Plan", "prep": dict(pf, when="Thu")})
    check("events: the card line, the name escaped",
          "For <b>Micro &lt;quiz&gt;</b> on Thu &middot; 2 more days of prep" in html, html)


def test_deck_counts_v395():
    """3.9.5 (the audit's E1): a plan deck's subdecks counted in one pass up
    each path, the same as every deck against every deck was: nested, empty
    parents, the deck itself, a name with ":::" in it; and fast at 4,000."""
    import random
    import time as _t
    from due_crew import plans as P

    def brute(rel, by_deck):
        return {k: sum(len(by_deck.get(dd, ())) for r, dd in rel.items() if not k or r == k or r.startswith(k + "::"))
                for k in rel}
    rel = {"": 1, "a": 2, "a::b": 3, "a::b::c": 4, "a::bc": 5, "a:": 6, "a:::b": 7, "z": 8, "z::y": 9}
    by_deck = {1: [1], 3: [2, 3], 4: [4], 5: [5], 6: [6], 7: [7, 8], 9: [9]}
    check("deck counts: nested, empty parents, the deck itself, odd names",
          P.deck_counts(rel, by_deck) == brute(rel, by_deck), (P.deck_counts(rel, by_deck), brute(rel, by_deck)))
    rnd = random.Random(7)
    rel = {"": 0}
    for i in range(1, 400):
        parent = rnd.choice(list(rel))
        rel[(parent + "::" if parent else "") + f"d{i}"] = i
    by_deck = {d: list(range(rnd.randint(0, 3))) for d in rel.values()}
    check("deck counts: a random tree of 400 the same", P.deck_counts(rel, by_deck) == brute(rel, by_deck))
    flat = {"": 0, **{f"d{i}": i for i in range(1, 4001)}}
    t0 = _t.perf_counter()
    out = P.deck_counts(flat, {i: [i] for i in range(4001)})
    took = _t.perf_counter() - t0
    check("deck counts: 4,000 subdecks in well under a tenth of a second (was about a second)",
          out[""] == 4001 and out["d7"] == 1 and took < 0.1, took)


def test_plans_buried_siblings():
    """A new card whose note has a card answered counts as seen: Anki
    buries and spaces siblings, so the date is done and never behind for
    them, and Due says when they come back. A suspended sibling stays out."""
    from due_crew import plans as P, due
    col = _plan_col()
    col.db.conn.execute("UPDATE cards SET queue = 2, type = 2 WHERE id = 5")
    col.db.conn.execute("UPDATE cards SET queue = -3, type = 0 WHERE id = 6")
    idx = P.DeckIndex(col, 10)
    check("siblings: c2 buried behind a studied c1 counts as seen", idx.counts({5, 6}) == [2, 2, 2], str(idx.counts({5, 6})))
    check("siblings: counted, and buried today", idx.siblings({5, 6}) == (1, 1))
    doc = {"units": [{"id": "u", "name": "Cloze", "opens": "2026-01-01", "due": "2026-01-02"}]}
    check("siblings: a past date isn't behind for them", P.ahead_behind(doc, {"u": idx.counts({5, 6})}, "2026-03-01") == [])
    col.db.conn.execute("UPDATE cards SET queue = -1 WHERE id = 6")
    idx = P.DeckIndex(col, 10)
    check("siblings: a suspended sibling isn't seen", idx.counts({5, 6}) == [1, 1, 2] and idx.siblings({5, 6}) == (0, 0))
    col.db.conn.execute("UPDATE cards SET queue = 0 WHERE id = 6")
    idx = P.DeckIndex(col, 10)
    check("siblings: unburied, they come back later", idx.siblings({5, 6}) == (1, 0))
    x = {"pid": "p", "uid": "u", "name": "Cloze", "opens": "2026-01-01", "seen": 2, "total": 2}
    check("siblings: Due says when they come back",
          due._date_row(dict(x, sibs=[12, 12]), set(), "2026-03-01")["n"] == "done \u00b7 12 siblings tomorrow"
          and due._date_row(dict(x, sibs=[1, 0]), set(), "2026-03-01")["n"] == "done \u00b7 1 sibling later"
          and due._date_row(x, set(), "2026-03-01")["n"] == "all done"
          and due._date_row(dict(x, sibs=[1, 0]), set(), "2026-03-01")["done"])
    # 3.7.3: a review card of an older note, due today, buries its new sibling;
    # that sibling was seen before today, so it isn't today's progress, nor behind
    from due_crew import plan_flow as F
    col.db.conn.execute("UPDATE cards SET queue = -3 WHERE id = 6")
    idx = P.DeckIndex(col, 10)
    check("siblings: buried today for a note started before today isn't today's", idx.buried_today({5, 6}, {}) == 0)
    check("siblings: buried today for a note started today is", idx.buried_today({5, 6}, {5: 0}) == 1)
    plan = {"id": "p", "doc": {"deck": "Step 1", "units": [
        {"id": "u", "name": "Cloze", "opens": _day(-3), "cards": [["guid000050", 0], ["guid000050", 1]]}]}}
    v = F.session_view(plan, {"deck_id": 10}, idx, {}, _day(0))
    check("behind: a sibling buried by an older note's review today isn't behind", v["behind"] == 0 and v["done"] == 0, v)
    v = F.session_view(plan, {"deck_id": 10}, idx, {5: 0}, _day(0))
    check("behind: a past date's cards seen today (one buried by a note started today) clear it",
          v["done"] == 0 and v["behind"] == 0, v)
    # 3.8.0: a day's new cards count the siblings Anki buried behind the ones seen,
    # so a cloze-heavy day isn't a missed one (the missed-days question, the recap)
    for o in (2, 3, 4):  # a five-card cloze: Anki shows c1, buries c2-c5
        fakes.add_card(col.db.conn, 60 + o, did=10, queue=-3, nid=50, ord_=o)
    idx = P.DeckIndex(col, 10)
    plan2 = {"id": "p", "sched": {"days": [1] * 7, "minutes": 60}, "doc": {"deck": "Step 1", "units": [
        {"id": "u", "name": "Cloze", "opens": _day(-1), "cards": [["guid000050", o] for o in range(5)]}]}}
    v2 = F.session_view(plan2, {"deck_id": 10}, idx, {5: 1}, _day(0))
    check("siblings: a day whose note started then, its buried sibling with it, isn't missed", _day(-1) not in v2["missed"], v2["missed"])


def test_settings_merge_v381():
    """3.8.1, the audit (#2): a settings save replaced the whole doc, so two
    computers saving close together lost one side's change. A save now names
    the rev it started from; turned away, the add-on merges (merge3) and saves
    the merge. Keys one side changed take that side's; lists merge item by
    item; anything both changed takes the save being made now."""
    from due_crew import account, app as appmod
    from due_crew.app import _state
    m = account.merge3
    check("merge: each side's own change kept",
          m({"paused": False, "muted": []}, {"paused": True, "muted": []}, {"paused": False, "muted": ["dre"]})
          == {"paused": True, "muted": ["dre"]})
    check("merge: a list both changed: both additions, in theirs' order then mine",
          m({"muted": ["a"]}, {"muted": ["a", "b"]}, {"muted": ["a", "c"]}) == {"muted": ["a", "c", "b"]})
    check("merge: one side took an item off, the other added: off stays off, the new one stays",
          m({"muted": ["a", "b"]}, {"muted": ["b"]}, {"muted": ["a", "b", "c"]}) == {"muted": ["b", "c"]})
    x = {"id": "aaaa", "t": "Read ch 3", "d": "", "done": "", "at": ""}
    y = {"id": "bbbb", "t": "Quiz", "d": "", "done": "", "at": ""}
    ticked = dict(x, done="2026-10-13")
    check("merge: to-dos item by item: theirs ticked one, mine added one",
          m({"due_items": [x]}, {"due_items": [x, y]}, {"due_items": [ticked]}) == {"due_items": [ticked, y]})
    check("merge: Delete my to-dos elsewhere, a new one here: the old go, the new one stays",
          m({"due_items": [x]}, {"due_items": [x, y]}, {"due_items": []}) == {"due_items": [y]})
    check("merge: ticks day by day",
          m({"due_ticks": {"p:u:1": "2026-10-12"}}, {"due_ticks": {"p:u:1": "2026-10-12", "p:u:2": "2026-10-13"}},
            {"due_ticks": {"p:u:3": "2026-10-13"}}) == {"due_ticks": {"p:u:3": "2026-10-13", "p:u:2": "2026-10-13"}})
    check("merge: a status both changed takes mine (the save being made now); squads by id",
          m({"status": "a", "squads": [{"id": "s1"}]}, {"status": "b", "squads": [{"id": "s1"}, {"id": "s2"}]},
            {"status": "c", "squads": [{"id": "s3"}]}) == {"status": "b", "squads": [{"id": "s3"}, {"id": "s2"}]})

    # two computers on one account, saving close together
    saved = (account.cfg, account.client, appmod.save_cfg, appmod._bg, appmod.swap, account.mw.col)

    def _bg(job, done=None):
        r = job()
        if done:
            done(r)
    store = world({"sam": "Sammy"}, {})
    a, b = new_client(store, "sam", "Sammy"), new_client(store, "sam", "Sammy")
    boxes = {"a": {"paused": False, "muted": [], "status": ""}, "b": {"paused": False, "muted": [], "status": ""}}
    who = {"now": "a"}
    clients = {"a": a, "b": b}
    try:
        appmod._bg, appmod.swap, account.mw.col = _bg, None, None
        account.cfg = lambda: dict(boxes[who["now"]])
        account.client = lambda: clients[who["now"]]
        appmod.save_cfg = lambda c, from_account=False: boxes[who["now"]].update(c)

        def as_(k):
            who["now"] = k
            _state.update(settings_ready=True, settings_pulling=False)
        as_("a")
        account.push(boxes["a"])  # the account's first save
        for k in ("a", "b"):
            as_(k)
            clients[k].session["settings_day"] = ""
            _state.update(settings_ready=False)
            account.ensure()
        check("two computers: both start from the same save", a.session.get("settings_rev") == b.session.get("settings_rev") == 1,
              str((a.session.get("settings_rev"), b.session.get("settings_rev"))))
        as_("a")
        boxes["a"]["muted"] = ["dre"]
        account.on_change(boxes["a"])
        as_("b")
        boxes["b"]["paused"] = True
        account.on_change(boxes["b"])  # over rev 1, which a has moved on from: turned away, merged, saved
        kept = store.settings["sam"]
        check("two computers: the second save keeps the first's change (it used to replace it)",
              kept["settings"].get("muted") == ["dre"] and kept["settings"].get("paused") is True and kept["rev"] == 3, str(kept))
        check("two computers: the merge is in this computer's config too, and nothing waits",
              boxes["b"]["muted"] == ["dre"] and not b.session.get("settings_dirty") and b.session.get("settings_rev") == 3)
        as_("a")
        a.session["settings_day"] = ""
        _state.update(settings_ready=False)
        account.ensure()
        check("two computers: the first takes the merged save at its next pull", boxes["a"]["paused"] is True and boxes["a"]["muted"] == ["dre"])
        # a save that comes back turned away more than MERGES times stops and waits for a pull
        n = {"puts": 0}
        real_put = a.put_settings

        def stubborn(at, settings, base=None):
            n["puts"] += 1
            from due_crew.backend.api import Saved
            return Saved(409, {"error": "conflict", "v": 1, "at": "x", "settings": {"status": "elsewhere"}, "rev": 99})
        a.put_settings = stubborn
        boxes["a"]["status"] = "here"
        account.on_change(boxes["a"])
        a.put_settings = real_put
        check("merge: turned away again and again, it stops after a few and the next pull sorts it out",
              n["puts"] == account.MERGES + 1, str(n))
    finally:
        account.cfg, account.client, appmod.save_cfg, appmod._bg, appmod.swap, account.mw.col = saved
        _state.update(settings_ready=False, settings_pulling=False)


def test_bug_squash_oct():
    """The October bug run: settings that never reach the account or that a
    new computer's defaults overwrite; show-up and pause leaking numbers;
    recover leeches touching a leech's siblings; a stale deck index; Hold
    back re-closing early dates; Behind counting even dates' shut slices;
    placeholders in names; Overview's description trusted."""
    from due_crew import account, app as appmod, plans as P, due_flow as F, room_model as rm, cards as K
    from due_crew.app import _state
    import due_crew as dc
    saved = (account.cfg, account.client, appmod.save_cfg, appmod._bg, appmod.swap, account.mw.col)

    def _bg(job, done=None):
        try:
            r = job()
        except Exception:
            r = None
        if done:
            done(r)
    try:
        appmod._bg, appmod.swap, account.mw.col = _bg, None, None
        store = world({"sam": "Sammy"}, {})
        a = new_client(store, "sam", "Sammy")
        a.put_settings("2026-10-01T00:00:00.000000Z", {"shared_decks": [{"id": 11, "name": "Big"}], "muted": ["troll"],
                       "share_retention": False})
        b = new_client(store, "sam", "Sammy")
        box = {"cfg": {"share_retention": True, "shared_decks": [], "emoji": ""}}
        account.cfg, account.client = (lambda: dict(box["cfg"])), (lambda: b)
        appmod.save_cfg = lambda c, from_account=False: box["cfg"].update(c)
        _state.update(settings_ready=False, settings_pulling=False)
        real = b.get_settings
        b.get_settings = lambda: (None, 0)  # the first pull doesn't answer
        account.ensure()
        b.get_settings = real
        box["cfg"]["emoji"] = "\U0001F525"
        account.on_change(box["cfg"])
        kept = store.settings["sam"]["settings"]
        check("settings: a new computer whose first pull failed doesn't put its defaults over the account",
              kept.get("muted") == ["troll"] and kept.get("share_retention") is False, kept)

        # an edit whose upload failed goes at the next good pull
        _state.update(settings_ready=False, settings_pulling=False)
        b.session["settings_day"] = ""
        account.ensure()  # pulled now: this computer holds the account's save
        real_put = b.put_settings
        b.put_settings = lambda at, s: False  # offline
        box["cfg"]["share_retention"] = True
        account.on_change(box["cfg"])
        b.put_settings = real_put
        check("settings: the failed upload leaves the edit dirty", b.session.get("settings_dirty") is True)
        _state.update(settings_ready=False, settings_pulling=False)
        b.session["settings_day"] = ""
        account.ensure()
        check("settings: the next pull with nothing newer up there sends it",
              store.settings["sam"]["settings"].get("share_retention") is True and not b.session.get("settings_dirty"),
              store.settings["sam"])
    finally:
        account.cfg, account.client, appmod.save_cfg, appmod._bg, appmod.swap, account.mw.col = saved

    # recover leeches: a leech's never-lapsed sibling stays shut
    col = _plan_col()
    col.db.conn.execute("UPDATE cards SET type = 2, lapses = 8, queue = -1 WHERE id = 5")
    col.db.conn.execute("UPDATE notes SET tags = ' leech ' WHERE id = 50")
    col.db.conn.execute("UPDATE cards SET type = 0, lapses = 0, queue = -1 WHERE id = 6")
    sql = []
    real_all = col.db.all
    col.db.all = lambda q, *a: (sql.append(q), real_all(q, *a))[1]
    try:
        F.recover_leeches(col)
    except Exception:
        pass
    col.db.all = real_all
    check("recover leeches: only cards that lapsed themselves", any("c.lapses > 0" in q for q in sql), sql)

    # the deck index sees a retag older than the newest note
    col = _plan_col()
    idx = P.DeckIndex(col, 10)
    col.db.conn.execute("UPDATE notes SET tags = 'Step1::Renal::New', mod = 1 WHERE id = (SELECT nid FROM cards WHERE id = 3)")
    check("deck index: a note edited with an older mtime is read again",
          P.DeckIndex(col, 10).tag_cards("Step1::Renal::New") == {3})

    # hold back leaves dates opened early alone; Behind counts what's open
    doc = {"units": [{"id": "a", "opens": "2026-09-01", "tags": ["Step1::Cardio::Arrhythmia"]},
                     {"id": "b", "opens": "2026-09-03", "tags": ["Step1::Renal"]}]}
    col = _plan_col()
    col.db.conn.execute("UPDATE cards SET queue = 0, type = 0 WHERE id IN (3, 8)")
    idx = P.DeckIndex(col, 10)
    check("hold back: a later date already opened here isn't held",
          P.holdable(idx, doc, "2026-09-01", applied={"b": "sig"}) == set()
          and 8 in P.holdable(idx, doc, "2026-09-01") | {8})
    check("Behind: opened and unseen only (an even date's later slices are shut on purpose)",
          P.waiting_new({"units": [{"id": "u", "opens": "2026-09-01"}]}, {"u": [2, 2, 10]}, "2026-09-05") == 0)

    # a crewmate's name holding a placeholder stays text
    js = rm.widget_js("bottom", {"title": "Al__KEY__x", "names": ["Al__KEY__x"]})
    check("widgets: a name with __KEY__ in it isn't replaced", "Al__KEY__x" in js and K.float_js({"text": "__KEY__"}).count("__KEY__") == 1)

    # Overview runs a deck's description: not one of our pages
    import inspect
    check("trust: Overview (a deck's description runs there) isn't one of our pages",
          '"aqt.overview"' not in inspect.getsource(dc._our_page))


def test_plans_ids_e1():
    """E1: note ids and card ids pasted onto a date: a note id brings every
    card of it, a card id that one card, only inside the plan's deck; they
    change the date's sig; the author's Anki counts them as "#ids"."""
    from due_crew import plans as P
    from due_crew.backend import shapes
    col = _plan_col()
    idx = P.DeckIndex(col, 10)
    check("ids: a note id brings both cards of the cloze", idx.match({"nids": [50]}) == {5, 6})
    check("ids: a card id brings just that card", idx.match({"cids": [6]}) == {6})
    check("ids: never outside the deck the plan runs on", idx.match({"nids": [7], "cids": [7]}) == set())
    check("ids: an id this copy doesn't have finds nothing", idx.match({"nids": [999999]}) == set())
    base = {"id": "u1", "tags": [], "decks": [], "cards": []}
    check("ids: new ids give the date a new sig (so they open)",
          P.unit_sig(base) != P.unit_sig(dict(base, nids=[50])) != P.unit_sig(dict(base, nids=[50], cids=[3])))
    counts = P.search_counts(idx, {"units": [dict(base, nids=[50, 999999], cids=[1])]})
    check("ids: the author's Anki counts what they find", counts["u1"]["#ids"] == 3, str(counts))
    u = shapes._clean_unit({"id": "u1", "name": "x", "opens": "2026-10-06", "nids": [50, "x", True, -1, 7], "cids": []})
    check("ids: cleaned on arrival to positive whole numbers", u.get("nids") == [50, 7] and "cids" not in u, str(u))
    rows = P.match_rows(idx, {"deck": "Step 1", "units": [{"id": "a", "name": "Staph", "opens": "2026-10-06",
                                                          "tags": [], "decks": [], "cards": [], "nids": [50]}]})
    check("ids: the follow dialog's row says what they found", rows == [("Staph", "2 cards", False)], str(rows))


def test_plans_portable_picks_365():
    """3.6.5: a date's pasted ids also travel as the cards the author's Anki
    found (`idr`, guid + card number), so a copy whose ids differ still finds
    them; `notes` picks every card of a note by its guid; ids that only mean
    something in one collection can't be a search."""
    from due_crew import plans as P
    from due_crew.backend import shapes
    col = _plan_col()
    idx = P.DeckIndex(col, 10)
    g50 = "guid000050"
    check("notes: a note's guid brings every card of it", idx.match({"notes": [g50]}) == {5, 6})
    check("notes: a guid this copy lacks finds nothing", idx.match({"notes": ["nope"]}) == set())
    # the author's copy: note 50 is a cloze; the refs are what its ids found
    unit = {"id": "u1", "nids": [50], "cids": [3]}
    refs = P.id_refs(idx, col, {"units": [dict(unit, tags=[]), {"id": "u2", "tags": ["x"]}]})
    check("refs: one entry a date with ids, the ids it was worked out from",
          list(refs) == ["u1"] and refs["u1"][:2] == [[50], [3]], str(refs))
    check("refs: the cards as guid and card number",
          sorted(map(tuple, refs["u1"][2])) == [("guid000003", 0), (g50, 0), (g50, 1)], str(refs))
    check("refs: capped", len(P.id_refs(idx, col, {"units": [unit]}, cap=2)["u1"][2]) == 2)
    # a classmate whose copy gave the same notes other ids
    other = sqlite3.connect(":memory:")
    fakes.make_collection(other)
    fakes.add_card(other, 103, did=10, queue=-1, nid=903)
    fakes.add_card(other, 105, did=10, queue=-1, nid=950, ord_=0)
    fakes.add_card(other, 106, did=10, queue=-1, nid=950, ord_=1)
    other.execute("UPDATE notes SET guid = 'guid000003' WHERE id = 903")
    other.execute("UPDATE notes SET guid = ? WHERE id = 950", (g50,))
    ocol = fakes.FakeCol(other, fakes.day_cutoff_for(TODAY))
    ocol.decks = fakes.FakeDecks({10: "Step 1"})
    oidx = P.DeckIndex(ocol, 10)
    check("refs: without them, other ids find nothing", oidx.match(unit) == set())
    check("refs: with them, the same cards", oidx.match(dict(unit, idr=refs["u1"][2])) == {103, 105, 106})
    check("notes: by guid in any copy", oidx.match({"notes": [g50]}) == {105, 106})
    check("missing: single cards and notes this copy lacks, of all of them",
          oidx.exact_missing({"cards": [[g50, 1], ["gone", 0]], "notes": [g50, "gone2"]}) == (2, 4))
    base = {"id": "u1", "tags": [], "decks": [], "cards": [], "nids": [50]}
    check("sig: notes, or refs arriving, give the date a new sig (so what they add opens)",
          len({P.unit_sig(base), P.unit_sig(dict(base, notes=[g50])), P.unit_sig(dict(base, idr=[[g50, 0]]))}) == 3)
    check("sig: a date with neither keeps the sig it had", P.unit_sig(base) == P.unit_sig(dict(base, notes=[], idr=[])))
    counts = P.search_counts(idx, {"units": [{"id": "n", "notes": [g50, "gone"]}]})
    check("notes: counted by the author's Anki", counts["n"]["#ids"] == 2 and counts["n"]["#pn"] == [2, 0, 1], str(counts))
    pn = P.date_counts(idx, {"deck": "Step 1", "units": [
        {"id": "b", "opens": "2026-10-06", "tags": ["Step1::Cardio"], "decks": []},
        {"id": "a", "opens": "2026-10-05", "tags": ["Step1::Cardio::Heart_failure"], "decks": [], "notes": [g50, "gone"]}]})
    check("counts (P1): in date order, what's new to a date, what an earlier one opens, notes not here",
          pn == {"a": [4, 0, 1], "b": [1, 2, 0]}, str(pn))
    rows = P.match_rows(idx, {"deck": "Step 1", "units": [{"id": "a", "name": "Staph", "opens": "2026-10-06",
                                                          "tags": [], "decks": [], "cards": [], "notes": [g50]}]})
    check("notes: the follow dialog's row says what they found", rows == [("Staph", "2 cards", False)], str(rows))
    u = shapes._clean_unit({"id": "u1", "name": "x", "opens": "2026-10-06", "notes": [g50, 5, ""],
                            "idr": [[g50, 0], ["x"], [g50, "1"], [3, 0]]})
    check("clean: notes are guids, refs [guid, number]",
          u.get("notes") == [g50] and u.get("idr") == [[g50, 0]], str(u))
    for q in ("nid:50", "cid:3,4", "deck:x nid:1"):
        check(f"search: {q} means nothing in someone else's Anki", not P.shareable_search(q))
    check("search: a plain one still goes", P.shareable_search("tag:x nidus"))


def test_plans_selector_365():
    """3.6.5: Anki's browser copies picked notes or cards as plan text that
    reads the same in anyone's copy: guids, card numbers from 1."""
    from due_crew import plans as P
    col = _plan_col()
    check("selector: notes by guid", P.selector(col, nids=[50, 3, 50]) == ("notes:guid000003 guid000050", 2))
    check("selector: cards as guid:number", P.selector(col, cids=[6, 5]) == ("cards:guid000050:1 guid000050:2", 2))
    check("selector: nothing picked", P.selector(col) == ("", 0))
    idx = P.DeckIndex(col, 10)
    text, _n = P.selector(col, cids=[6])
    g, n = text[len("cards:"):].rsplit(":", 1)
    check("selector: reads back to that card", idx.match({"cards": [[g, int(n) - 1]]}) == {6})


def test_export_for_my_ai_365():
    """3.6.5, P3: a plan's notes, or a deck's, in Anki's own plain-text
    format with the unique identifier first, for the person's own AI. To
    a file only; formatting and media out unless asked."""
    from due_crew import plans as P
    col = _plan_col()
    col.db.conn.execute("UPDATE notes SET flds = ? WHERE id = 1", ("<b>Heart</b> failure\x1f{{c1::BNP}} rises<br>[sound:x.mp3]\tand \"so\"",))
    idx = P.DeckIndex(col, 10)
    doc = {"deck": "Step 1", "units": [{"id": "hf", "opens": "2026-10-05", "tags": ["Step1::Cardio::Heart_failure"], "decks": []}],
           "pace": {"cover": ["tag:Step1::Cardio", "deck:Step 1::Extras"]}}
    check("export: what the plan's dates open, as notes", P.export_scope(idx, doc, "dates") == {1, 2})
    check("export: what the plan covers (the builder's ticks)", P.export_scope(idx, doc, "cover") == {1, 2, 3, 4})
    check("export: the whole deck", P.export_scope(idx, doc, "deck") == {1, 2, 3, 4, 50, 8, 9})
    text, n = P.export_notes(col, {1, 50})
    lines = text.splitlines()
    check("export: Anki's header, the guid column first", lines[:7] == ["#separator:tab", "#html:false", "#guid column:1",
          "#notetype column:2", "#deck column:3", "#tags column:4", "#cards column:5"] and n == 2, str(lines[:7]))
    row = next(x for x in lines if x.startswith("guid000001"))
    cells = row.split("\t")
    check("export: a row is guid, notetype, deck, tags, its card numbers (3.8.1), then the fields, as plain text",
          cells[2] == "Step 1" and "Step1::Cardio::Heart_failure" in cells[3] and cells[4] == "1" and cells[5] == "Heart failure"
          and cells[6] == '"{{c1::BNP}} rises and ""so"""', str(cells))
    col.db.conn.execute("INSERT INTO cards (id, nid, did, odid, type, queue, ivl, ord, due, lapses) VALUES (777, 1, 10, 0, 0, 0, 0, 2, 0, 0)")
    cells = next(x for x in P.export_notes(col, {1})[0].splitlines() if x.startswith("guid000001")).split("\t")
    check("export: a note's card numbers are the ones it has (a cloze with c1 and c3: 1 3)", cells[4] == "1 3", str(cells[4]))
    check("export: one line a note, no tabs inside a field", len(lines) == 9 and all(x.count("\t") >= 5 for x in lines[7:]))
    raw, _ = P.export_notes(col, {1}, plain=False)
    check("export: formatting kept when asked", "#html:true" in raw and "<b>Heart</b>" in raw)
    check("export: a size estimate errs high", P.export_size(col, {1, 50}) >= len(text) - 200)


def test_feedback_365():
    """3.6.5, P6: Send feedback, from Tools › Due Crew and Settings
    (the board's You tab, and the dialog), with the versions if ticked."""
    from due_crew import app as appmod
    store = world({"maya": "Maya"})
    maya = new_client(store, "maya", "Maya")
    check("feedback: sent with the versions, once", maya.send_feedback("  Plans tab is great  ", "add-on 3.6.5 ·\nAnki 24.11") == 201
          and store.feedback == [{"uid": "maya", "text": "Plans tab is great", "ver": "add-on 3.6.5 · Anki 24.11"}])
    for i in range(4):
        maya.send_feedback(f"more {i}")
    check("feedback: five a day", maya.send_feedback("one too many") == 429 and len(store.feedback) == 5)
    v = appmod.feedback_versions("3.6.5")
    check("feedback: the versions line", v.startswith("add-on 3.6.5 · Anki ") and v.count(" · ") == 2, v)
    html = board.settings_html({"tab": "you", "signed_in": True, "name": "Maya"}, {})
    check("feedback: a row on Settings › You, sent as setfeedback", "duecrew:setfeedback" in html and "Feedback" in html)
    check("feedback: not on the signed-out You tab", "setfeedback" not in board._settings_you({"signed_in": False}, {}))  # 3.10.0: Board's Language row has Suggest a wording, the same window
    import due_crew as dc
    from aqt.deckbrowser import DeckBrowser
    if "aqt.reviewer" not in sys.modules:
        sys.modules["aqt.reviewer"] = types.SimpleNamespace(Reviewer=type("Reviewer", (), {}))
    opened, saved = [], dc.open_feedback
    dc.open_feedback = lambda: opened.append(1)
    try:
        dc._on_js(False, as_board("duecrew:setfeedback"), DeckBrowser())
    finally:
        dc.open_feedback = saved
    check("feedback: the board's click reaches it", opened == [1])


def test_plans_what_in_a_day_p7():
    """3.6.5, P7: a date's topics on the Plans tab, as the site's print list
    groups them, with Browse; and one line of today's in the Today box."""
    from due_crew import plans as P
    u = {"id": "a", "name": "SLGs 1-3", "opens": "2026-10-03",
         "tags": ["#Big_Step1_v12::#V&B::02_Basic_Pharmacology::01_General::05_Pharmacokinetics",
                  "#Big_Step1_v12::#Lectures::Pharmacology::02_Pharmacokinetics::02_Drug_Elimination",
                  "#Big_Step1_v12::#Lectures::Pharmacology::02_Pharmacokinetics::05_Effect_of_Urine_pH",
                  "Step1::Renal"],
         "decks": ["Big Step 1::03_Extras"], "search": ["tag:x"], "notes": ["g1", "g2"], "nids": [5], "cards": [["g", 0]]}
    got = P.topics(u)
    check("topics: grouped by the resource part after the root, readable, order numbers off",
          got[:2] == [["V&B", ["Pharmacokinetics"]], ["Lectures", ["Drug Elimination", "Effect of Urine pH"]]], str(got))
    check("topics: tags with no resource part, and subdecks, under no heading",
          ["", ["Renal", "Extras"]] in got, str(got))
    check("topics: searches, notes picked by ID, single cards",
          ["Search", ["tag:x"]] in got and ["Picked by ID", ["3 notes"]] in got and ["Picked", ["1 single card"]] in got, str(got))
    line = P.topics_line([u, {"id": "b", "tags": ["#Big::#V&B::05_Biostats::07_Clinical_Trials"]}])
    check("today's line: one line, the same resource's topics together",
          line.startswith("V&B: Pharmacokinetics, Clinical Trials · Lectures: Drug Elimination"), line)
    from due_crew import board
    week = [{"day": "2026-10-03", "dow": "Sat", "num": 3, "today": True, "past": False, "rest": False, "prep": False, "events": [],
             "new": 109, "seen": 0, "units": [{"uid": "a", "name": "SLGs <1-3>", "total": 85, "seen": 0, "state": "open",
                                               "prep": False, "what": [["V&B", [["Pharma<b>", 0]]]]}]}]
    card = {"id": "p1", "title": "Plan", "sub": "", "rows": [], "lines": [], "change": None, "no_deck": False, "paused": False,
            "week": week, "week_offset": 0, "session": {"kind": "study", "target": 109, "done": 0, "due": 0, "behind": 0}}
    h = board._plan_card_html(card)
    check("day: what's in a block, escaped, with Browse sent as planbrowse",
          '<span class="g"><b>V&amp;B</b> &middot; <a class="tp"' in h and "Pharma&lt;b&gt;</a></span>" in h
          and "duecrew:planbrowse:p1:a" in h and "Browse 85 cards" in h and "<b>Pharma" not in h)
    check("day: 3.8.0, each topic opens its cards (plan, date, its place)", "duecrew:plantopic:p1:a:0" in h, h)
    check("today: 3.8.0, no Today box on the plan (Due's Today has today's dates and their topics)",
          'class="tw"' not in h and 'class="ptoday' not in h and "planstudy:p1" not in h, h)
    import due_crew as dc
    from due_crew import plan_flow as F
    from aqt.deckbrowser import DeckBrowser
    if "aqt.reviewer" not in sys.modules:
        sys.modules["aqt.reviewer"] = types.SimpleNamespace(Reviewer=type("Reviewer", (), {}))
    asked, saved = [], F.browse_date
    F.browse_date = lambda pid, uid: asked.append((pid, uid))
    try:
        dc._on_js(False, as_board("duecrew:planbrowse:p1:a"), DeckBrowser())
    finally:
        F.browse_date = saved
    check("browse: the board's click reaches it", asked == [("p1", "a")], str(asked))
    asked, saved = [], F.browse_topic
    F.browse_topic = lambda pid, uids, i: asked.append((pid, uids, i))
    try:
        dc._on_js(False, as_board("duecrew:plantopic:p1:a-b:1"), DeckBrowser())
        dc._on_js(False, as_board("duecrew:plantopic:p1:a:x"), DeckBrowser())
    finally:
        F.browse_topic = saved
    check("topic: the board's click reaches it, its dates and its place; a bad place is no place",
          asked == [("p1", ["a", "b"], 1), ("p1", ["a"], -1)], str(asked))


def test_browse_from_the_board_380():
    """3.8.0: what's left on a day, what's behind, a plan's leeches, a topic,
    and Browse › Show on my plan, each finding its own cards here, from the
    board's click (or the browser's menu)."""
    from due_crew import plans as P, plan_flow as F, board, due as DUE
    from due_crew.app import _state
    import due_crew as dc
    from aqt import mw
    from aqt.deckbrowser import DeckBrowser
    col = _plan_col()
    conn = col.db.conn
    conn.execute("UPDATE cards SET queue = 0 WHERE id = 1")  # Heart failure: 1 opened, 2 still shut
    fakes.add_card(conn, 10, did=10, ctype=2, queue=-1, tags="Step1::Cardio::Heart_failure leech")  # a leech Anki set aside
    plan = {"id": "pB", "name": "Step", "doc": {"deck": "Step 1", "units": [
        {"id": "a", "name": "Heart", "opens": _day(-1), "tags": ["Step1::Cardio::Heart_failure"]},
        {"id": "b", "name": "Renal", "opens": _day(-2), "tags": ["Step1::Renal"]},
        {"id": "c", "name": "Rhythm", "opens": _day(4), "tags": ["Step1::Cardio::Arrhythmia"]}]}}
    shown, said = [], []
    saved = (F.followed, F._state_cfg, F._today, F._browse, F.tooltip, F.app.swap, F.save_cfg, mw.col)
    try:
        F.followed = lambda: [plan]
        applied = {"a": _day(-1), "b": _day(-2)}
        F._state_cfg = lambda c=None: {"pB": {"deck_id": 10, "applied": applied}}
        F._today = lambda: _day(0)
        F._browse = lambda cids, q=None, empty="": shown.append((sorted(cids), q)) if cids else said.append(empty)
        F.tooltip = lambda msg, **k: said.append(msg)
        F.app.swap = lambda c=None: None
        kept = []
        F.save_cfg = lambda c: kept.append(dict(c))
        mw.col = col
        dc._on_js(False, as_board("duecrew:planleft:pB:a"), DeckBrowser())
        check("left: a date's cards I haven't seen; one suspended on it after it opened is set aside (3.9.6, Sam), and a seen leech isn't left",
              shown[-1][0] == [1], shown)
        dc._on_js(False, as_board("duecrew:planleft:pB:a-b"), DeckBrowser())
        check("left: a day's two dates together; a seen card isn't left", 8 not in shown[-1][0] and 1 in shown[-1][0], shown)
        dc._on_js(False, as_board("duecrew:planleft:pB"), DeckBrowser())
        check("behind: every date before today, what's opened and not seen", shown[-1][0] == [1], shown)
        applied["a"] = "skip:" + _day(-1)
        n = len(shown)
        dc._on_js(False, as_board("duecrew:planleft:pB"), DeckBrowser())
        check("behind: a date skipped here isn't behind, as Due counts it (the review)",
              len(shown) == n and said[-1] == "Nothing left to see.", (shown[-1], said[-1:]))
        applied["a"] = _day(-1)
        dc._on_js(False, as_board("duecrew:plantopic:pB:c:0"), DeckBrowser())
        check("topic: a date ahead's topic finds its cards", shown[-1][0] == [3], shown)
        n = len(shown)
        dc._on_js(False, as_board("duecrew:planleft:pB:zz"), DeckBrowser())
        check("left: a date that isn't there finds nothing, and says so", len(shown) == n and said[-1] == "Nothing left to see.", said)
        browser = types.SimpleNamespace(selected_cards=lambda: [3])
        F.show_on_plan(browser)
        week = (datetime.date.fromisoformat(P.week_start(_day(4))) - datetime.date.fromisoformat(P.week_start(_day(0)))).days // 7
        check("show on my plan: the Plans tab on that date's week, the day open",
              _state["plan_week"].get("pB") == week and _state["plan_focus"] == {"pB": _day(4)} and "Rhythm" in said[-1], said[-1])
        check("show on my plan: that plan stays the one shown (round five, pick 3)", kept and kept[-1].get("plan_pick") == "pB", kept[-1:])
        F.show_on_plan(types.SimpleNamespace(selected_cards=lambda: [7]))
        check("show on my plan: a card in no plan I follow says so", said[-1] == "It isn't on a plan you follow.", said[-1])
        wk = P.week_view(F.mine(plan)["doc"], {}, _day(0), P.week_start(_day(4)))
        html = board._week_html({"week": wk, "week_offset": week, "focus": _day(4)}, "pB")
        i = next(k for k, d in enumerate(wk) if d["day"] == _day(4))
        check("show on my plan: the board opens that day's details", f'id="dc-pd-pB-{i}"' in html
              and f'id="dc-pd-pB-{i}" hidden' not in html, html[-600:])
        dc._on_js(False, as_board("duecrew:planweek:pB:0"), DeckBrowser())
        check("show on my plan: moving the week lets go of the day", "plan_focus" not in _state)
    finally:
        (F.followed, F._state_cfg, F._today, F._browse, F.tooltip, F.app.swap, F.save_cfg, mw.col) = saved
        _state.pop("plan_focus", None)
        _state.get("plan_week", {}).pop("pB", None)
    # the board: a date's details say what's left, the Today box's behind, the leeches line, Due's rows
    week = [{"day": _day(0), "dow": "Sat", "num": 3, "today": True, "past": False, "rest": False, "prep": False, "events": [],
             "new": 40, "seen": 10, "units": [{"uid": "a", "name": "Heart", "total": 40, "seen": 10, "state": "open", "prep": False,
                                               "what": [["", [["Heart failure", 0]]]]}]}]
    card = {"id": "pB", "title": "Plan", "sub": "", "rows": [], "lines": [], "change": None, "no_deck": False, "paused": False,
            "week": week, "week_offset": 0, "waiting": 16,
            "aside": [3, 0, 0], "aside_ok": [0, 0], "session": {"kind": "study", "target": 40, "done": 10, "due": 0, "behind": 0}}
    h = board._plan_card_html(card)
    check("details: Browse 40 cards and the 30 left", "duecrew:planbrowse:pB:a" in h and "duecrew:planleft:pB:a" in h and "30 left</a>" in h, h)
    check("waiting: new from earlier days, with Catch up (Due's Behind opens them)",
          "<b>16</b> new from earlier days waiting" in h and "duecrew:plancatch:pB" in h, h)
    check("leeches: 3.8.0, not on the plan (they're the deck's: Insights)", "leech" not in h, h)
    dv = DUE.view(_day(0), [{"pid": "pB", "uid": "a", "plan": "Step", "name": "Heart", "opens": _day(0), "seen": 1, "total": 4,
                             "counted": True, "what": "Heart failure", "topics": [["", [["Heart failure", 0]]]]},
                            {"pid": "pB", "uid": "b", "plan": "Step", "name": "Renal", "opens": _day(-2), "seen": 1, "total": 9,
                             "counted": True, "what": "Renal", "topics": []}], [], {})
    dh = board._due_html(dv)
    check("due: a date's topics study their new and due cards (3.9.5); Behind's cards to see open what's behind",
          "duecrew:plantopicstudy:pB:a:0" in dh and ("pycmd('duecrew:planleft:pB|" + KK + "')") in dh and "8 cards to see</a>" in dh, dh)


def test_topic_items_380():
    """3.8.0: what each topic name stands for, so its click finds its cards:
    the same names and order as topics(), merged across dates by group and
    name, each with its own sources (unit-shaped, for DeckIndex.match)."""
    from due_crew import plans as P
    a = {"id": "a", "tags": ["#Big::#V&B::05_Biostats::07_Clinical_Trials", "Step1::Renal", "#Big::#Lectures::Pharm::02_Drug_Elimination"],
         "decks": ["Big Step 1::03_Extras"], "search": ["tag:x"], "notes": ["g1"], "nids": [5], "idr": [["g1", 0]], "cards": [["g", 0]]}
    b = {"id": "b", "tags": ["#Big::#V&B::05_Biostats::07_Clinical_Trials::01_Bias", "#Big::#V&B::02_Pharm::03_Kinetics"]}
    items = P.topic_items([a, b])
    names = [(g, x) for g, x, _s in items]
    check("topic items: one per group and name, in first-seen order",
          names == [("V&B", "Clinical Trials"), ("", "Renal"), ("Lectures", "Drug Elimination"), ("", "Extras"),
                    ("Search", "tag:x"), ("Picked by ID", "2 notes"), ("Picked", "1 single card"), ("V&B", "Bias"),
                    ("V&B", "Kinetics")], names)
    src = {(g, x): s for g, x, s in items}
    check("topic items: each with what it stands for",
          src[("", "Renal")] == {"tags": ["Step1::Renal"]} and src[("", "Extras")] == {"decks": ["Big Step 1::03_Extras"]}
          and src[("Search", "tag:x")] == {"search": ["tag:x"]}
          and src[("Picked by ID", "2 notes")] == {"notes": ["g1"], "nids": [5], "idr": [["g1", 0]]}
          and src[("Picked", "1 single card")] == {"cards": [["g", 0]]}, src)
    view = P.topic_view([a, b])
    check("topic view: grouped for the page, each name with its place in the items",
          view[0] == ["V&B", [["Clinical Trials", 0], ["Bias", 7], ["Kinetics", 8]]] and ["", [["Renal", 1], ["Extras", 3]]] in view, view)
    check("topics and the Today line read as before",
          P.topics(a)[0] == ["V&B", ["Clinical Trials"]]
          and P.topics_line([a, b]).startswith("V&B: Clinical Trials, Bias, Kinetics · Renal, Extras · Lectures: Drug Elimination"),
          P.topics_line([a, b]))
    idx = P.DeckIndex(_plan_col(), 10)
    got = [idx.match(s) for _g, _x, s in P.topic_items([{"id": "u", "tags": ["Step1::Cardio::Heart_failure", "Step1::Renal"]}])]
    check("topic items: each finds just its own cards here (children too, this deck only)", got == [{1, 2}, {8}], got)


def test_plans_matching_v31():
    """3.1: a unit's tags (children too, any case), subdecks, and single
    cards (that card, never its sibling), inside the chosen deck only."""
    from due_crew import plans as P
    col = _plan_col()
    idx = P.DeckIndex(col, 10)
    u = {x["id"]: x for x in _plan_units()}
    check("match: a tag brings its children, in any case, and nothing that only starts like it",
          idx.match(u["hf"], None, "Step 1") == {1, 2})
    check("match: only inside the deck it runs on", 7 not in idx.match(u["hf"], None, "Step 1"))
    check("match: a subdeck by its path under the plan's deck", idx.match(u["ex"], None, "Step 1") == {4})
    check("match: a single card is that card, not its cloze sibling",
          idx.match(u["cz"], None, "Step 1") == {6})
    check("match: a whole tag tree", idx.match({"tags": ["Step1::Cardio"]}) == {1, 2, 3})
    other = _plan_col("Step1_v11")
    oidx = P.DeckIndex(other, 10)
    doc = {"deck": "Step 1", "units": _plan_units()}
    swap = P.detect_swap(oidx, doc)
    check("swap: my tags start differently, and the add-on sees how", swap == ("Step1", "Step1_v11"), str(swap))
    check("swap: read through it, the plan lines up",
          oidx.match(u["hf"], swap, "Step 1") == {1, 2} and oidx.match(u["hf"], None, "Step 1") == set())
    check("swap: none when the tags already line up", P.detect_swap(idx, doc) is None)
    check("best deck: the one named like the plan's", P.best_deck(col, doc) == (10, None))
    col.decks = fakes.FakeDecks({10: "Big Deck v11", 11: "Big Deck v11::Extras", 20: "Other"})
    check("best deck: else the one where most of it is found", P.best_deck(col, doc)[0] == 10)
    prog = P.progress(idx, doc)
    check("progress: [opened, seen, total] per unit",
          prog["hf"] == [0, 0, 2] and prog["rn"] == [1, 1, 1] and prog["cz"] == [0, 0, 1])
    tags, decks = P.DeckIndex(_plan_col(), 10).tree()
    check("tree: names and counts only, a tag counting everything under it",
          ["Step1::Cardio", 3] in tags and ["Step 1::Extras", 1] in decks
          and all(isinstance(n, int) for _p, n in tags + decks))
    FD = P
    counted = dict(u["hf"], n=3)  # the author's copy had 3 under that tag; this one has 2
    rows = FD.match_rows(idx, {"deck": "Step 1", "units": [counted, u["ar"], u["cz"]]})
    check("follow: found of the author's count when the plan has one, else cards found",
          rows[0] == ("Heart failure", "2 of 3", False) and rows[1] == ("Arrhythmia", "1 card", False)
          and rows[2] == ("Cloze two", "1 of 1", False), str(rows))
    # 3.9.3 (Sam's pick): a card under two of a date's tags counts once, and what's missing is counted alike
    two = dict(u["hf"], tags=list(u["hf"]["tags"]) * 2, n=6)  # the author's builder added the same 2 (3 there) twice
    rows2 = FD.match_rows(idx, {"deck": "Step 1", "units": [two]})
    same = dict(u["hf"], tags=list(u["hf"]["tags"]) * 2, n=4)
    rows3 = FD.match_rows(idx, {"deck": "Step 1", "units": [same]})
    check("follow 3.9.3: two tags on the same cards count each card once, what's missing too",
          rows2[0][1] == "2 of 3" and rows3[0][1] == "2 of 2", (rows2, rows3))
    missing = FD.match_rows(idx, {"deck": "Step 1", "units": [dict(u["rn"], tags=["Nope"], n=40)]})
    check("follow: a date with none of its cards here says so", missing == [("Renal", "not in your copy", True)])
    check("code: typed, spaced, or a pasted link",
          P.code_from("7kq4 mx2d") == "7KQ4MX2D" == P.code_from("https://duecrew.com/p/7KQ4MX2D"))


def test_plans_morning_v31():
    """3.1: the morning opens what's due in one undo step and never
    suspends: not on a stop, not when a unit goes, not when a date moves
    later. Late joins both ways, dates moved earlier, cards added."""
    from due_crew import plan_flow as F
    from due_crew import plans as P
    store = world({"dre": "Dre", "maya": "Maya"})
    pid, code = store.add_plan("dre", "Step 1", "Step 1", _plan_units())
    maya = new_client(store, "maya", "Maya")
    plan, status = maya.follow_plan(code)
    plan0 = plan
    col = _plan_col()
    state = {pid: F.new_state(col, plan)}
    check("follow: runs on the deck named like the plan's", status == 200 and state[pid]["deck_id"] == 10)
    res = F.run(col, [plan], state, _day(0))
    check("morning: what has opened opens, and only that",
          _open(col) == {1, 2, 3, 8} and res["n"] == 3, str(_open(col)))
    check("morning: one undo step, named for it",
          [s[0] for s in col.undo_steps] == ["Due Crew: open 2 sets"]
          and sorted(col.undo_steps[0][1]) == [1, 2, 3] and res["label"] == P.step_label(["a", "b"]))
    check("morning: the toast's names and count", res["names"] == ["Heart failure", "Arrhythmia"]
          and res["per"][pid] == [["Heart failure", "Arrhythmia"], 3])
    again = F.run(col, [plan], state, _day(0))
    check("morning: a second run the same day does nothing, and makes no step",
          again["n"] == 0 and len(col.undo_steps) == 1)
    one = F.run(col, [plan], state, _day(3))
    check("morning: one unit's step says its name", col.undo_steps[-1][0] == "Due Crew: open Extras"
          and one["n"] == 1 and 4 in _open(col))
    col.undo()
    check("undo: Anki's undo puts that step's cards back, nothing else", 4 not in _open(col) and 1 in _open(col))

    # nothing suspends: a unit taken out, a date moved later, a stop
    col = _plan_col()
    state = {pid: F.new_state(col, plan)}
    F.run(col, [plan], state, _day(0))
    before = _queues(col)
    units = [dict(u, opens=_day(10), due=_day(12)) if u["id"] == "ar" else u for u in _plan_units() if u["id"] != "hf"]
    store.edit_plan(pid, units)
    moved = maya.fetch_board([_day(0)], with_decks=True)["plans"][0]
    F.run(col, [moved], state, _day(1))
    check("never suspends: a unit taken out, a date moved later", _queues(col) == before)
    later = F.run(col, [moved], state, _day(10))
    check("moved later: its cards stay open, and it isn't opened again when the date comes",
          "Arrhythmia" not in later["names"] and 3 in _open(col))
    was_open = _open(col)
    maya.unfollow_plan(pid)
    state.pop(pid)
    check("never suspends: stopping", _open(col) == was_open and store.follows.get((pid, "maya")) is None
          and not maya.session["plans"])

    # moved earlier, and cards added to an applied unit: both the next morning
    store.edit_plan(pid, _plan_units())
    plan, _ = maya.follow_plan(code)
    col = _plan_col()
    state = {pid: F.new_state(col, plan)}
    F.run(col, [plan], state, _day(0))
    store.edit_plan(pid, [dict(u, opens=_day(1)) if u["id"] == "cz" else u for u in _plan_units()])
    got, status = new_client(store, "dre", "Dre").add_plan_cards(pid, [["guid000009", 0]], unit="hf")
    check("add cards: the author puts a single card on a date", status == 200
          and got["doc"]["units"][0]["cards"] == [["guid000009", 0]] and got["version"] == store.plans[pid]["version"])
    plan = maya.fetch_board([_day(1)], with_decks=True)["plans"][0]
    res = F.run(col, [plan], state, _day(1))
    check("moved earlier: it opens the next morning (the cloze's c2, not c1)",
          6 in _open(col) and 5 not in _open(col))
    check("cards added to an opened unit open the next morning, and only they",
          9 in _open(col) and res["n"] == 2, f"{res}")

    # joining late, both ways
    plan = plan0
    col = _plan_col()
    state = {pid: F.new_state(col, plan)}
    check("late join: what's waiting", F.waiting(col, plan, state[pid], _day(0)) == (2, 3))
    F.run(col, [plan], state, _day(0), mode="skip")
    check("late join, start from the next unit: nothing opens now, or later",
          _open(col) == {8} and F.run(col, [plan], state, _day(2))["n"] == 0 and not col.undo_steps)
    F.run(col, [plan], state, _day(3))
    check("late join: the next unit opens on its morning", _open(col) == {4, 8})
    F.run(col, [plan], state, _day(3), everything=True)
    check("open everything now: the whole plan, skipped units too, in one step",
          _open(col) == {1, 2, 3, 4, 6, 8} and len(col.undo_steps) == 2
          and col.undo_steps[-1][0].startswith("Due Crew: open "))

    # Change deck: opened units open on the new deck, skipped ones stay skipped
    col = _plan_col()
    state = {pid: F.new_state(col, plan)}
    F.run(col, [plan], state, _day(0))
    col.decks = fakes.FakeDecks({10: "Step 1", 11: "Step 1::Extras", 20: "Other"})
    state[pid]["deck_id"] = 20
    F.run(col, [plan], state, _day(0))
    check("change deck: what had opened opens on the new deck", 7 in _open(col))


def test_plans_glue_v31():
    """3.1 glue: the morning waits for the AnkiWeb sync and runs once a
    day; pause; progress rides the sync only when it changed and only
    while sharing; the board's plans only on decks=1; the budget."""
    from due_crew import plan_flow as F
    from due_crew.app import _state
    store = world({"dre": "Dre", "maya": "Maya", "kai": "Kai", "lee": "Lee"})  # 3.9.5: Lee makes three counted
    pid, code = store.add_plan("dre", "Step 1 <i>", "Step 1", _plan_units())
    maya = new_client(store, "maya", "Maya")
    col = _plan_col()
    box = {"cfg": {}}
    toasts = []
    saved = {k: getattr(F, k) for k in ("cfg", "save_cfg", "_pcfg", "_psave", "client", "_today", "tooltip")}
    saved_col, saved_swap = F.mw.col, F.app.swap
    F.cfg = F._pcfg = lambda: box["cfg"]
    F.save_cfg = F._psave = lambda c: box.update(cfg=c)
    F.client = lambda: maya
    today = {"d": _day(0)}
    F._today = lambda: today["d"]
    F.tooltip = lambda text, **kw: toasts.append(text)
    F.mw.col = col
    F.app.swap = lambda c: None
    labels = [_day(-i) for i in range(7)]
    try:
        plan, _ = maya.follow_plan(code, team=True)  # 3.7.6: on its team, so her progress counts
        # followed here before its first date, and Anki not opened since
        box["cfg"]["plans"] = {pid: F.new_state(col, plan)}
        n = len(store.log)
        light = maya.fetch_board(labels)
        full = maya.fetch_board(labels, with_decks=True)
        again = maya.fetch_board(labels)
        check("board: plans ride the decks=1 refresh, and a light one when their stamp moved (3.7.3: never seen here)",
              len(store.log) - n == 3 and full["plans_fresh"] and light["plans_fresh"] and light["plans_update"]
              and not again["plans_fresh"] and full["plans"][0]["id"] == pid and again["plans"][0]["id"] == pid)
        F.maybe_morning(awaiting_sync=True, fresh=True)
        check("morning: waits for the day's AnkiWeb sync", _open(col) == {8} and "plans_day" not in box["cfg"])
        F.maybe_morning(awaiting_sync=False)
        check("morning: then runs, on the deck that matches, and says so",
              _open(col) == {1, 2, 3, 8} and box["cfg"]["plans_day"] == _day(0)
              and toasts == ["Due Crew opened 2 sets: 3 cards"], str(toasts))
        F.maybe_morning(awaiting_sync=False)
        check("morning: once a day", len(col.undo_steps) == 1)

        # progress: the sync carries it when it changed, while sharing
        prog = F.for_sync()
        check("progress: per unit, [opened, seen, total]", prog[pid]["hf"] == [2, 0, 2] and prog[pid]["rn"] == [1, 1, 1])
        n = len(store.log)
        maya.push(labels, {}, plans=prog)
        maya.push(labels, {}, plans=F.for_sync())
        sent = [b for m, p, b in store.bodies if p == "/sync"][-2:]
        check("progress: one sync is one request, and an unchanged one isn't sent again",
              len(store.log) - n == 2 and "plans" in sent[0] and "plans" not in sent[1])
        check("progress: the server keeps it", json.loads(store.follows[(pid, "maya")]["progress"])["hf"] == [2, 0, 2])
        kai = new_client(store, "kai", "Kai")
        kai.follow_plan(code, team=True)
        store.follows[(pid, "kai")]["progress"] = json.dumps({"hf": [2, 2, 2]})
        board_plan = maya.fetch_board(labels, with_decks=True)["plans"][0]
        check("crew (3.9.5, the audit's S1): two counted are two people, so no counts come at all",
              board_plan["followers"] == 2 and board_plan["crewDone"] is None, str(board_plan))
        dre = new_client(store, "dre", "Dre")
        dre.team_join(pid)
        board_plan = maya.fetch_board(labels, with_decks=True)["plans"][0]
        check("crew (3.9.5, Sam): the author on the team makes three, but my own taken away leaves one person's: none",
              store._in_squad(pid) == 3 and board_plan["crewDone"] is None, str(board_plan))
        dre.team_leave(pid)
        lee = new_client(store, "lee", "Lee")
        lee.follow_plan(code, team=True)
        store.follows[(pid, "lee")]["progress"] = json.dumps({"hf": [2, 2, 2], "rn": [1, 1, 1]})
        board_plan = maya.fetch_board(labels, with_decks=True)["plans"][0]
        check("crew: from three counted, followers and units done, counts only",
              board_plan["followers"] == 3 and board_plan["crewDone"] == {"hf": 2, "rn": 2}, str(board_plan))
        maya.set_follow(pid, share=False)
        check("sharing off (3.7.6: off the team): out of everyone's counts (two left: none), still mine for my own views",
              store.follows[(pid, "maya")]["progress"] is not None and (pid, "maya") not in store.team
              and maya.fetch_board(labels, with_decks=True)["plans"][0]["crewDone"] is None)
        check("sharing off: the sync still carries it, for my own views", pid in F.for_sync())
        maya.set_follow(pid, share=True)
        maya.push(labels, {}, plans=F.for_sync())
        check("sharing back on: the next sync sends it whole",
              json.loads(store.follows[(pid, "maya")]["progress"] or "{}").get("hf") == [2, 0, 2])

        # pause: no mornings until resumed
        maya.set_follow(pid, paused=True)
        today["d"] = _day(3)
        F.maybe_morning(awaiting_sync=False)
        check("pause: the morning skips a paused plan", 4 not in _open(col)
              and box["cfg"]["plans_day"] == _day(3))
        maya.set_follow(pid, paused=False)
        check("resume: what opened meanwhile is waiting",
              F.waiting(col, F.followed()[0], box["cfg"]["plans"][pid], _day(3)) == (1, 1))

        # the card: names escaped, crew counts, today's step, ahead and behind, the change note
        maya.fetch_board(labels, with_decks=True)  # 3.9.5: three counted again since sharing came back on
        _state["labels"] = labels
        _state["plan_progress"] = F.progress(col, F.followed(), box["cfg"]["plans"])
        box["cfg"]["plans_opened"] = {"day": _day(0), "label": "Due Crew: open 2 sets",
                                      "per": {pid: [["Heart <b>failure", "Arrhythmia"], 3]}}
        col.undo_steps.append(("Due Crew: open 2 sets", []))
        today["d"] = _day(0)
        view = F.board_view(box["cfg"])
        html = board.render({"entries": [], "labels": labels, "tomorrow": "", "pending": []},
                            {"period": "today"}, 0, plans=view, you={"tab": "plans", "plans": view})
        check("card: You › Plans, the plan's title, its set (plans, end to end: in place of its week) and followers",
              "Step 1 &lt;i&gt; · Dre’s plan" in html and "set 2 of 5 · 3 following" in html)
        check("card: the crew line; no Today box (Due's Today has today), names escaped",
              "Crew: 2 done with" in html and "ptoday" not in html and "planstudy:" not in html
              and "<b>failure" not in html, re.sub(r"<style.*?</style>", "", html, flags=re.S)[-2500:])
        cached = [p for p in F.client().session.get("plans") or [] if p.get("id") == pid]
        kept_crew = [p.get("crewDone") for p in cached]
        for p in cached:
            p["crewDone"] = None  # as the board brings it under three counted (3.9.5)
        few = F.board_view(box["cfg"])
        fh = board.render({"entries": [], "labels": labels, "tomorrow": "", "pending": []},
                          {"period": "today"}, 0, plans=few, you={"tab": "plans", "plans": few})
        check("card (3.9.5): under three counted, no crew line and no date's crew count",
              cached and "Crew:" not in fh and "crew 0/" not in fh and "crew 0 of" not in fh and "3 following" in fh,
              re.sub(r"<style.*?</style>", "", fh, flags=re.S)[-1500:])
        for p, c in zip(cached, kept_crew):
            p["crewDone"] = c
        check("morning: what it opened, while it's still Anki's latest step", F.morning_opened()["n"] == 3, F.morning_opened())
        from due_crew import due as DUE
        dv = dict(DUE.view(_day(0), [], [], {}), opened=F.morning_opened())
        dh = board.you_html({}, dv, {"tab": "today", "plans": view})
        check("morning: Due's Today says so, with Put off to tomorrow",
              "This morning opened 3 new cards." in dh and "duecrew:plannottoday" in dh, dh[-800:])
        ph = board.you_html({}, dv, {"tab": "plans", "plans": view, "opened": F.morning_opened()})
        check("morning: with Due on, not again on Plans", "plannottoday" not in ph)
        ph = board.you_html({}, None, {"tab": "plans", "plans": view, "opened": F.morning_opened()})
        check("morning: with Due off, on Plans", "This morning opened 3 new cards." in ph and "duecrew:plannottoday" in ph)
        check("morning: no Sync now while AnkiWeb has it all", "plansync" not in dh)
        mw = F.mw
        sv_pm, sv_col = getattr(mw, "pm", None), mw.col
        synced = []
        try:
            mw.pm = types.SimpleNamespace(sync_auth=lambda: object())
            mw.col = types.SimpleNamespace(mod=2000, db=types.SimpleNamespace(scalar=lambda q: 1000))
            ahead = F._unsynced()
            mw.col = types.SimpleNamespace(mod=2000, db=types.SimpleNamespace(scalar=lambda q: 2000))
            even = F._unsynced()
            mw.pm = types.SimpleNamespace(sync_auth=lambda: None)
            mw.col = types.SimpleNamespace(mod=2000, db=types.SimpleNamespace(scalar=lambda q: 0))
            nologin = F._unsynced()
            check("morning: Sync now only with an AnkiWeb login and changes since its last sync",
                  ahead is True and even is False and nologin is False, (ahead, even, nologin))
            mw.col = sv_col
            sh = board.you_html({}, dict(dv, opened={"n": 3, "sync": True}), {"tab": "today", "plans": view})
            check("morning: Sync now beside Put off to tomorrow", "duecrew:plansync" in sh and "Sync now</a>" in sh
                  and sh.index("plansync") < sh.index("plannottoday"))
            mw.on_sync_button_clicked = lambda: synced.append(1)
            import due_crew as dc
            from aqt.deckbrowser import DeckBrowser
            dc._on_js(False, as_board("duecrew:plansync"), DeckBrowser())
            check("morning: Sync now is Anki's own Sync", synced == [1], synced)
        finally:
            mw.col = sv_col
            if sv_pm is None:
                mw.__dict__.pop("pm", None)
            else:
                mw.pm = sv_pm
            mw.__dict__.pop("on_sync_button_clicked", None)
        col.undo_steps.append(("Edit note", []))
        check("morning: no Put off to tomorrow once Anki has done something since", F.morning_opened() is None)
        today["d"] = _day(1)
        col.undo_steps.pop()
        check("morning: nor on another day", F.morning_opened() is None)
        today["d"] = _day(3)
        html = board.render({"entries": [], "labels": labels, "tomorrow": "", "pending": []},
                            {"period": "today"}, 0, plans=view, you={"tab": "plans", "plans": view})
        check("card: behind, only for me (plans, end to end: its own line, with Behind…)",
              '<span class="late">Behind &middot; Heart failure, 2 left</span>' in html and f"planbehind:{pid}" in html
              and f"plancatch:{pid}" not in html, "")
        store.edit_plan(pid, [dict(u, name="Arrhythmia & co") if u["id"] == "ar" else
                              dict(u, opens=_day(21)) if u["id"] == "rn" else u for u in _plan_units()])
        maya.fetch_board(labels, with_decks=True)
        card = F.card_view(F.followed()[0], box["cfg"]["plans"][pid], {}, _day(0))
        check("change note: the author moved a date", card["change"] is not None
              and "moved " in "".join(t for t, _b in card["change"]) and "Renal" in [t for t, _b in card["change"]])
        F.seen_change(pid)
        check("change note: OK puts it away",
              F.card_view(F.followed()[0], box["cfg"]["plans"][pid], {}, _day(0))["change"] is None)
        ahead = F.card_view(F.followed()[0], dict(box["cfg"]["plans"][pid]), {"ex": [1, 0, 1]}, _day(1))
        check("ahead: the next unit already open",
              ahead["lines"][0][0] == "ahead" and "early" in "".join(t for t, _b in ahead["lines"][0][1]))

        # offers: from my squads, escaped, Look opens the follow
        sq = new_client(store, "dre", "Dre").create_squad("orca")
        store._join(sq["id"], "maya")
        store.add_plan("dre", "Pharm <script>", "Pharm", [], audience="squad", squad=sq["id"])
        box["cfg"]["squads"] = [dict(sq)]
        maya.fetch_board(labels, with_decks=True)
        view = F.board_view(box["cfg"])
        html = board.render({"entries": [], "labels": labels, "tomorrow": "", "pending": []},
                            {"period": "squads"}, 0, plans=view)
        check("offer: my squad's plan, as a banner with Look, escaped",
              "offered orca a plan: Pharm &lt;script&gt;" in html and "duecrew:planlook:" in html
              and "<script>" not in html)
        opt = next(o for o in maya.session["plan_offers"])
        check("offer: a squad plan can't be followed from outside the squad",
              new_client(store, "kai", "Kai").peek_plan(opt["code"])[1] == 404
              and maya.peek_plan(opt["code"])[1] == 200)
        box["cfg"]["plan_offers_dismissed"] = [opt["id"]]
        check("offer: waved off, it stays off", F.board_view(box["cfg"])["offers"] == [])
        check("site link: one request, a token for the fragment", maya.site_link() and
              store.log[-1] == ("POST", "/auth/link", 200))
        check("tree: names and counts go up", maya.put_tree("Step 1", [["Step1::Cardio", 3]], [])
              and store.plan_trees[("maya", "Step 1")]["tags"] == [["Step1", 0, [["Cardio", 3]]]])
        check("add cards: only the author", new_client(store, "kai", "Kai").add_plan_cards(
            pid, [["guid000001", 0]], unit="hf")[1] == 403)
        mine = maya.my_plans()
        check("my plans: the ones I follow", [p["id"] for p in mine] == [pid] and mine[0]["following"])
    finally:
        for k, v in saved.items():
            setattr(F, k, v)
        F.mw.col, F.app.swap = saved_col, saved_swap
        _state["labels"], _state["plan_progress"] = [], {}


# ---------------------------------------------------------------- 3.1.1: review fixes

_PLAN_KEYS = ("plans", "plans_day", "plans_opened", "plan_offers_dismissed")


class _PlanGlue:
    """plan_flow's glue pointed at a test world: a shared add-on config
    (the one every profile sees), per-profile folders, and a client and a
    collection per profile. Restores everything on exit."""

    def __init__(self, clients, cols, today=None):
        from due_crew import plan_flow as F
        self.F = F
        self.glob = {"cfg": {}}
        self.dirs = {name: tempfile.mkdtemp() for name in clients}
        self.clients, self.cols = clients, cols
        self.toasts = []
        self.today = {"d": today or _day(0)}

    def __enter__(self):
        F = self.F
        self.saved = {k: getattr(F, k, None) for k in ("cfg", "save_cfg", "_files", "client", "_today", "tooltip")}
        self.saved_mw = (F.mw.col, F.mw.pm.name, F.app.swap)
        F.cfg = lambda: self.glob["cfg"]
        F.save_cfg = lambda c: self.glob.update(cfg=c)
        F._files = lambda: self.dirs[F.mw.pm.name]
        F.client = lambda: self.clients[F.mw.pm.name]
        F._today = lambda: self.today["d"]
        F.tooltip = lambda text, **kw: self.toasts.append(text)
        F.app.swap = lambda c: None
        self.forget()
        self.profile(next(iter(self.clients)))
        return self

    def forget(self):
        """Drop plan_flow's cache of this profile's file."""
        if hasattr(self.F, "_store"):
            self.F._store.update(profile=None, data=None)

    def state(self):
        """This profile's plan state (before 3.1.1: the shared config)."""
        return self.F._pcfg() if hasattr(self.F, "_pcfg") else self.glob["cfg"]

    def profile(self, name):
        self.F.mw.pm.name = name
        self.F.mw.col = self.cols[name]

    def __exit__(self, *exc):
        F = self.F
        for k, v in self.saved.items():
            if v is None:
                delattr(F, k)
            else:
                setattr(F, k, v)
        F.mw.col, F.mw.pm.name, F.app.swap = self.saved_mw
        self.forget()
        from due_crew.app import _state
        _state["labels"], _state["plan_progress"] = [], {}
        return False


def test_plans_file_kept_when_unreadable_v380():
    """3.8.0: a plans.json that won't read was taken as no plans and written
    over at the next save, losing the list of cards a plan held back. It's
    moved aside as plans.json.bad (bad2, ... after that) and said once."""
    store = world({"maya": "Maya"})
    maya = new_client(store, "maya", "Maya")
    with _PlanGlue({"A": maya}, {"A": _plan_col()}) as g:
        F = g.F
        path = os.path.join(g.dirs["A"], "plans.json")
        with open(path, "w") as f:
            f.write('{"plans": {"p1": {"held": [1, 2')
        g.forget()
        check("plans file: an unreadable one reads as no plans", g.state() == {})
        check("plans file: moved aside, said once",
              os.path.exists(path + ".bad") and not os.path.exists(path)
              and len([t for t in g.toasts if "plans.json.bad" in t]) == 1, (os.listdir(g.dirs["A"]), g.toasts))
        g.state()
        check("plans file: read again from the cache, not said again", len(g.toasts) == 1, g.toasts)
        F._psave({"plans": {}})
        with open(path + ".bad") as f:
            kept = f.read()
        check("plans file: the next save leaves the old one alone", "held" in kept, kept)
        with open(path, "w") as f:
            f.write("not json")
        g.forget()
        g.state()
        check("plans file: a second bad one doesn't replace the first",
              os.path.exists(path + ".bad2") and "held" in open(path + ".bad").read(), os.listdir(g.dirs["A"]))


def test_plans_per_profile_v311():
    """3.1.1: plan state is the profile's, not the add-on's. Profile B's
    fresh board used to prune A's plans (A then reopened every past unit),
    and B's morning set the day for A. The old shared state moves once, to
    the profile whose decks it names."""
    store = world({"dre": "Dre", "maya": "Maya", "kai": "Kai"})
    pid, code = store.add_plan("dre", "Step 1", "Step 1", _plan_units())
    maya, kai = new_client(store, "maya", "Maya"), new_client(store, "kai", "Kai")
    col_b = _plan_col()
    col_b.decks = fakes.FakeDecks({30: "Biochem"})
    with _PlanGlue({"A": maya, "B": kai}, {"A": _plan_col(), "B": col_b}) as g:
        F = g.F
        plan, _ = maya.follow_plan(code)
        F.open_schedule = _skip_schedule
        F.on_followed(plan, 10, None, "open")
        col_a = g.cols["A"]
        g.profile("B")
        F.maybe_morning(False, fresh=True)  # B follows nothing
        g.profile("A")
        st = g.state().get("plans", {}).get(pid)
        check("profiles: B's fresh board leaves A's plan state alone",
              bool(st) and st["applied"].get("hf") and st["applied"].get("ar"), str(st))
        check("profiles: no plan state in the config every profile shares",
              not any(k in g.glob["cfg"] for k in _PLAN_KEYS), str(g.glob["cfg"]))
        col_a.db.conn.execute("UPDATE cards SET queue = -1 WHERE id = 1")  # suspended again by hand
        g.today["d"] = _day(1)
        maya.fetch_board([_day(1)], with_decks=True)
        F.maybe_morning(False, fresh=True)
        check("profiles: A's next morning doesn't reopen what it opened before", 1 not in _open(col_a))

    # the old shared config: each profile takes the plans on its own decks, once
    with _PlanGlue({"C": maya, "D": kai}, {"C": _plan_col(), "D": col_b}) as g:
        F = g.F
        g.glob["cfg"] = {"plans": {"pa": {"deck_id": 10, "applied": {"hf": "x"}},
                                   "pb": {"deck_id": 30, "applied": {}}},
                         "plans_day": _day(0), "plans_opened": {"day": _day(0), "label": "L"},
                         "plan_offers_dismissed": ["o1"], "sort": "reviews"}
        c_state = g.state()
        check("migrate: a profile takes the plans on its decks, with the day and the Undo",
              list(c_state["plans"]) == ["pa"] and c_state.get("plans_day") == _day(0)
              and c_state.get("plans_opened", {}).get("label") == "L"
              and c_state.get("plan_offers_dismissed") == ["o1"], str(c_state))
        check("migrate: the rest wait in the config for their own profile",
              list(g.glob["cfg"].get("plans") or {}) == ["pb"] and "plans_day" not in g.glob["cfg"])
        g.profile("D")
        d_state = g.state()
        check("migrate: the other profile takes its own, and the config lets go",
              list(d_state["plans"]) == ["pb"] and "plans_day" not in d_state
              and not any(k in g.glob["cfg"] for k in _PLAN_KEYS) and g.glob["cfg"].get("sort") == "reviews",
              f"{d_state} {g.glob['cfg']}")
        g.profile("C")
        g.forget()
        check("migrate: once; the profile's file is kept", list(g.state()["plans"]) == ["pa"])


def test_plans_followed_elsewhere_v311():
    """3.1.1: a plan first seen here (followed on another computer, or on
    the site) opens today's unit only; what opened before came with the
    AnkiWeb sync, or was skipped there on purpose. Following again here
    keeps what was applied."""
    store = world({"dre": "Dre", "maya": "Maya"})
    pid, code = store.add_plan("dre", "Step 1", "Step 1", _plan_units())
    maya = new_client(store, "maya", "Maya")
    with _PlanGlue({"A": maya}, {"A": _plan_col()}) as g:
        F, col = g.F, g.cols["A"]
        plan, _ = maya.follow_plan(code)
        maya.fetch_board([_day(0)], with_decks=True)
        F.maybe_morning(False, fresh=True)
        st = g.state()["plans"][pid]
        check("elsewhere: only today's unit opens", _open(col) == {3, 8}, str(_open(col)))
        check("elsewhere: the units before today are marked skipped", st["applied"]["hf"].startswith("skip:"))
        F.open_schedule = _skip_schedule
        F.on_followed(plan, 10, None, "open")
        check("follow again: what was applied here is kept (the skipped unit stays shut)",
              _open(col) == {3, 8} and g.state()["plans"][pid]["applied"]["hf"].startswith("skip:"),
              str(_open(col)))
        # 3.4 review, H1: a plan first seen here (followed on the site) asks
        # Follow's hold-back question, once, only when there's something to hold
        asked = []
        F.offer_hold([pid], ask=lambda name, n: asked.append(n) or False)
        check("hold on first sight: nothing active to hold, nothing asked", asked == [], str(asked))
        col.db.conn.execute("UPDATE cards SET queue = 0 WHERE queue = -1")  # a deck imported all active
        before = _open(col)
        F.offer_hold([pid], ask=lambda name, n: asked.append(n) or False)
        check("hold on first sight: asked, and a no leaves everything open", asked and _open(col) == before, str(asked))
        F.offer_hold([pid], ask=lambda name, n: True)
        held = g.state()["plans"][pid].get("held") or []
        check("hold on first sight: a yes holds back the later dates' cards, remembered for stop",
              held and all(c not in _open(col) for c in held) and len(held) == asked[-1], str(held))


def test_plans_changed_unit_v311():
    """3.1.1: when the author changes a unit already opened here, only the
    cards the change adds open. A card suspended since (by hand, or a
    leech Anki suspended) stays suspended; a leech never opens."""
    from due_crew import plan_flow as F
    from due_crew import plans as P
    store = world({"dre": "Dre", "maya": "Maya"})
    pid, code = store.add_plan("dre", "Step 1", "Step 1", _plan_units())
    plan, _ = new_client(store, "maya", "Maya").follow_plan(code)
    col = _plan_col()
    state = {pid: F.new_state(col, plan)}
    F.run(col, [plan], state, _day(0))
    conn = col.db.conn
    conn.execute("UPDATE cards SET queue = -1 WHERE id = 1")                          # by hand
    fakes.add_card(conn, 12, did=10, queue=-1, tags="Step1::Cardio::Heart_failure leech")  # Anki's leech
    fakes.add_card(conn, 13, did=10, queue=-1, tags="Step1::Cardiology leech")
    units = [dict(u, tags=u["tags"] + ["Step1::Cardiology"]) if u["id"] == "hf" else u
             for u in _plan_units()]
    changed = dict(plan, doc=dict(plan["doc"], units=units))
    check("changed unit: what's waiting is only what the change adds",
          F.waiting(col, changed, state[pid], _day(1)) == (1, 2))
    res = F.run(col, [changed], state, _day(1))
    check("changed unit: only the card it adds opens", 9 in _open(col) and res["n"] == 1, f"{res} {_open(col)}")
    check("changed unit: a card suspended since stays suspended", 1 not in _open(col))
    check("changed unit: a leech never opens", 12 not in _open(col) and 13 not in _open(col))
    check("open cards: never a leech, even asked directly", P.open_cards(col, {12, 13}, "x") == 0)
    F.run(col, [changed], state, _day(1), everything=True)
    check("open everything: still no leech", 12 not in _open(col) and 13 not in _open(col) and 1 in _open(col))
    # 3.6.5: the plan card says what it left shut, once
    check("aside: the leeches a date leaves shut, counted when it opens",
          F.aside(changed, state[pid]) == [2, 0, 0], str(state[pid].get("leeches")))
    from due_crew import board
    card = {"id": pid, "aside": F.aside(changed, state[pid]), "aside_ok": [0, 0]}
    html = board._plan_notes(card, pid)
    check("aside: 3.8.0, leeches aren't the plan's to say (Insights has the deck's)", not any("leech" in x for x in html), str(html))
    card = {"id": pid, "aside": [0, 2, 5], "aside_ok": [0, 0]}
    html = board._plan_notes(card, pid)
    check("aside: exact cards not in my deck, with OK",
          any("2 of 5 exact cards aren\u2019t in your deck." in x and f"planasideok:{pid}" in x for x in html), str(html))
    check("aside: said once, until it grows", not board._plan_notes(dict(card, aside_ok=[0, 2]), pid)
          and board._plan_notes(dict(card, aside=[0, 3, 5], aside_ok=[0, 2]), pid))
    import due_crew as dc
    from aqt.deckbrowser import DeckBrowser
    if "aqt.reviewer" not in sys.modules:
        sys.modules["aqt.reviewer"] = types.SimpleNamespace(Reviewer=type("Reviewer", (), {}))
    pc = {}
    saved = (F._state_cfg, F.followed, F._pcfg, F._psave, F.app.swap)
    F._state_cfg, F.followed, F._pcfg = (lambda c=None: state), (lambda: [changed]), (lambda: pc)
    F._psave, F.app.swap = (lambda d: None), (lambda c: None)
    try:
        dc._on_js(False, as_board(f"duecrew:planasideok:{pid}"), DeckBrowser())
    finally:
        F._state_cfg, F.followed, F._pcfg, F._psave, F.app.swap = saved
    check("aside: OK, sent as the board sends it, remembers what was said", pc.get("aside_ok", {}).get(pid) == [2, 0], str(pc))


def test_plans_changed_unit_with_search_and_ids():
    """A date with a search (C3) or pasted ids (E1) that the author changes
    after it opened here: the morning opens what the change adds, and no
    more (it used to stop on the date's longer record)."""
    from due_crew import plan_flow as F
    store = world({"dre": "Dre", "maya": "Maya"})
    units = [dict(u, search=["tag:Step1::Cardio::Arrhythmia"], nids=[50]) if u["id"] == "hf" else u for u in _plan_units()]
    pid, code = store.add_plan("dre", "Step 1", "Step 1", units)
    plan, _ = new_client(store, "maya", "Maya").follow_plan(code)
    col = _plan_col()
    state = {pid: F.new_state(col, plan)}
    F.run(col, [plan], state, _day(0))
    check("search+ids: the first morning opens the tag, the search and the note", {1, 2, 3, 5, 6} <= _open(col), str(_open(col)))
    conn = col.db.conn
    conn.execute("UPDATE cards SET queue = -1 WHERE id IN (3, 5)")   # closed since, by hand
    changed_units = [dict(u, tags=u["tags"] + ["Step1::Cardiology"]) if u["id"] == "hf" else u for u in units]
    changed = dict(plan, doc=dict(plan["doc"], units=changed_units))
    res = F.run(col, [changed], state, _day(1))
    check("search+ids: after the author's change only the added card opens", res["n"] == 1 and 9 in _open(col), f"{res} {_open(col)}")
    check("search+ids: what was closed by hand since stays closed", 3 not in _open(col) and 5 not in _open(col))


def test_plans_follower_days_g():
    """G1-G5: a follower's own days. My dates run `shift` days later and
    the ones I skip never open (the plan never changes, events never move);
    one date opens now and the morning leaves it; Not today opens it on
    tomorrow's morning, not today's; what's waiting from earlier dates is
    counted; the card offers Open now, Undo skip and Catch up."""
    from due_crew import plan_flow as F
    from due_crew import plans as P
    doc = {"deck": "Step 1", "units": _plan_units(), "events": [{"id": "q", "day": _day(5), "name": "Quiz"}],
           "reviews": [{"day": _day(4), "from": "hf", "to": "ar"}]}
    mine = P.my_doc(doc, 2, ["ex"])
    check("my view: dates, due dates and review days two days later; a skipped date gone; events stay",
          [u["id"] for u in mine["units"]] == ["hf", "ar", "cz", "rn"] and mine["units"][1]["opens"] == _day(2)
          and mine["units"][1]["due"] == _day(8) and mine["reviews"][0]["day"] == _day(6)
          and mine["events"][0]["day"] == _day(5) and doc["units"][1]["opens"] == _day(0), str(mine["units"][1]))
    check("my view: nothing to change, the plan itself", P.my_doc(doc) is doc)

    store = world({"dre": "Dre", "maya": "Maya"})
    pid, code = store.add_plan("dre", "Step 1", "Step 1", _plan_units())
    plan, _ = new_client(store, "maya", "Maya").follow_plan(code)
    col = _plan_col()
    state = {pid: F.new_state(col, plan)}
    shifted = dict(plan, shift=2, skipped=["hf"])
    F.run(col, [shifted], state, _day(0))
    check("shift: today's date waits two days; a skipped date never opens", _open(col) == {8}, str(_open(col)))
    F.run(col, [shifted], state, _day(2))
    check("shift: two days later it opens", 3 in _open(col) and 1 not in _open(col), str(_open(col)))

    col = _plan_col()
    state = {pid: F.new_state(col, plan)}
    res = F.open_one(col, plan, state[pid], "ex", _day(0))
    check("open now: one date, one undo step, today", res["n"] == 1 and 4 in _open(col) and res["names"] == ["Extras"])
    before = len(col.undo_steps)
    F.run(col, [plan], state, _day(3))
    check("open now: its morning leaves it be", 4 in _open(col) and "Extras" not in str(col.undo_steps[before:]))

    col = _plan_col()
    state = {pid: F.new_state(col, plan)}
    res = F.run(col, [plan], state, _day(0))
    check("the morning says which dates it opened", set(res["units"][pid]) == {"hf", "ar"}, str(res["units"]))
    conn = col.db.conn
    conn.execute("UPDATE cards SET queue = -1 WHERE id IN (1, 2, 3)")  # Anki's undo put them back
    F.put_off(state[pid], res["units"][pid], _day(0))
    again = F.run(col, [plan], state, _day(0))
    check("not today: not again today", again["n"] == 0 and not ({1, 2, 3} & _open(col)))
    tomorrow = F.run(col, [plan], state, _day(1))
    check("not today: tomorrow's morning opens them", {1, 2, 3} <= _open(col) and tomorrow["n"] == 3, str(tomorrow))

    check("waiting: new cards of earlier dates not seen yet",
          P.waiting_new({"units": _plan_units()}, {"hf": [2, 0, 2], "ar": [1, 1, 1]}, _day(1)) == 2)
    card = F.card_view(dict(plan, skipped=["ex"]), state[pid], {"hf": [2, 0, 2]}, _day(1))
    rows = {r["name"]: r for r in card["rows"]}
    check("card: the skipped date, with its id, crossed out", rows.get("Extras", {}).get("state") == "skip", str(card["rows"]))
    check("card: the next date carries its id, for Open now", rows.get("Cloze two", {}).get("uid") == "cz")
    check("card: what's waiting from earlier dates", card["waiting"] == 2)
    from due_crew import board
    html = board._plan_card_html(dict(card, id=pid))
    weeks = lambda day: (datetime.date.fromisoformat(P.week_start(day)) - datetime.date.fromisoformat(P.week_start(_day(1)))).days // 7
    in_week = lambda day: board._plan_card_html(dict(F.card_view(dict(plan, skipped=["ex"]), state[pid], {"hf": [2, 0, 2]},
                                                                   _day(1), week_offset=weeks(day)), id=pid))
    check("card: Open now (the next date's day), Undo skip (the skipped one's day) and Behind… (plans, end to end)",
          f"plannow:{pid}:cz" in in_week(_day(7)) and f"planunskip:{pid}:ex" in in_week(_day(3))
          and f"planbehind:{pid}" in html and "Skip it" in in_week(_day(7)), html[:400])


def test_your_own_days_376():
    """3.7.6: one date moved later on my copy, Reset to default, and the
    three ways to start a plan that began before I followed."""
    import due_crew as dc
    from aqt.deckbrowser import DeckBrowser
    from due_crew import plan_flow as F
    from due_crew import plans as P
    from due_crew import board
    doc = {"deck": "Step 1", "units": _plan_units(), "events": [{"id": "q", "day": _day(5), "name": "Quiz"}]}
    mine = P.my_doc(doc, 1, (), {"ar": 2})
    ar = next(u for u in mine["units"] if u["id"] == "ar")
    check("moved: that date runs its days later again, on top of the shift; the rest only the shift",
          ar["opens"] == _day(3) and ar["due"] == _day(9) and ar.get("_moved") == 2
          and next(u for u in mine["units"] if u["id"] == "ex")["opens"] == _day(4) and doc["units"][1]["opens"] == _day(0))
    week = P.week_view(mine, {}, _day(0), P.week_start(_day(3)))
    check("moved: the week marks it", any(u.get("moved") for d in week for u in d["units"] if u["uid"] == "ar"))
    ls = P.late_start(dict(doc, end=_day(16)), _day(0))
    check("late: the passed dates, how far back the start is, where it would end and what it runs past",
          ls["passed"] == ["hf"] and ls["shift"] == 7 and ls["ends"] == _day(21) and ls["after"] == ("the plan's end", _day(16)), ls)
    check("late: nothing passed, nothing to ask", P.late_start({"units": _plan_units()[1:]}, _day(0))["passed"] == [])
    check("reset: says exactly what goes back, and nothing when nothing changed",
          F.reset_lines({"doc": doc, "shift": 3, "skipped": ["ex"], "moved": {"ar": 2}, "until": _day(4)})
          == ["Your dates run 3 days later: back on time", "1 skipped set comes back: Extras",
              "1 moved set goes back: Arrhythmia", "Your pause ends"]
          and F.reset_lines({"doc": doc}) == [])

    store = world({"dre": "Dre", "maya": "Maya"})
    pid, code = store.add_plan("dre", "Step 1", "Step 1", _plan_units())
    maya = new_client(store, "maya", "Maya")
    col = _plan_col()
    labels = [_day(-i) for i in range(7)]
    saved = (F._bg, F.confirm if hasattr(F, "confirm") else None)
    with _PlanGlue({"A": maya}, {"A": col}):
        F._bg = lambda job, done=None: done(job()) if done else job()
        try:
            plan, _ = maya.follow_plan(code)
            F.on_followed(plan, 10, None, "skip:hf")
            check("late, where everyone is: the passed date is skipped on my follow, so behind nowhere",
                  store.follows[(pid, "maya")].get("skipped") == ["hf"] and 1 not in _open(col) and 3 in _open(col),
                  (store.follows[(pid, "maya")], _open(col)))
            maya.fetch_board(labels, with_decks=True)
            card = F.card_view(next(x for x in F.followed() if x["id"] == pid), F._state_cfg()[pid], {}, _day(0))
            html = board._plan_card_html(dict(card, id=pid))
            check("move: a date from today on has Move…", f"planmove:{pid}:ar" in html, html[:300])
            # 3.9.9: what's pressed and isn't a link is a button to the keyboard and a screen reader
            check("keys: a week's day is a button (a Tab stop, says whether it's open, names what it opens)",
                  re.search(r'<div class="pc[^"]*" onclick="[^"]*" role="button" tabindex="0" aria-expanded="(true|false)" '
                            r'aria-controls="dc-pd-[^"]+" aria-label="[A-Z][a-z]{2} \d+ [A-Z][a-z]{2}[^"]*: its sets"', html) is not None
                  and "setAttribute('aria-expanded','true')" in html, html[:400])
            check("keys: the path is one Tab stop, its sets walked with the arrows, each named",
                  html.count(' tabindex="0" data-rove="1"') == 1 and html.count('data-rove="1"') >= 2
                  and 'role="group" aria-label="Sets: ' in html and "Arrow keys move along them." in html
                  and re.search(r'<i class="[^"]*" title="[^"]*" aria-label="[^"&]*"', html) is not None)
            from due_crew.board import page as BP
            check("keys: one handler a page presses them on Enter or Space, and rides with the board's scripts",
                  "window.dcKeys" in BP.KEYS_JS and "'Enter'" in BP.KEYS_JS and "ArrowRight" in BP.KEYS_JS
                  and BP.KEYS_JS in BP.keep_me_in_view_js(True) and BP.KEYS_JS not in BP.keep_me_in_view_js(False))
            dc._on_js(False, as_board(f"duecrew:planskip:{pid}:ex"), DeckBrowser())  # a command the board sends, for the handler list
            F.move_date(pid, "cz", 2)
            check("move: kept on my follow; the plan itself unchanged",
                  store.follows[(pid, "maya")].get("moved") == {"cz": 2} and store.plans[pid]["doc"]["units"][3]["opens"] == _day(7))
            card = F.card_view(next(x for x in F.followed() if x["id"] == pid), F._state_cfg()[pid], {}, _day(0),
                               week_offset=(datetime.date.fromisoformat(P.week_start(_day(9))) - datetime.date.fromisoformat(P.week_start(_day(0)))).days // 7)
            html = board._plan_card_html(dict(card, id=pid))
            check("move: on its new day, marked moved, with Put it back", "&middot; moved" in html and f"planmoveback:{pid}:cz" in html)
            dc._on_js(False, as_board(f"duecrew:planmoveback:{pid}:cz"), DeckBrowser())
            check("move: Put it back (sent as the board does) takes it off", not store.follows[(pid, "maya")].get("moved"))
            dc._on_js(False, as_board(f"duecrew:planmoveto:{pid}:cz:2"), DeckBrowser())  # 3.9.9: the load view's Move
            check("load: its Move (sent as the board does) is my follow's, remembered for Put it back; the plan unchanged",
                  store.follows[(pid, "maya")].get("moved") == {"cz": 2} and F._state.get("load_moved") == (pid, "cz")
                  and store.plans[pid]["doc"]["units"][3]["opens"] == _day(7))
            dc._on_js(False, as_board(f"duecrew:planmoveback:{pid}:cz"), DeckBrowser())
            check("load: Put it back takes it off", not store.follows[(pid, "maya")].get("moved"))
            pid2, code2 = store.add_plan("dre", "Pharm", "Pharm", [
                {"id": "x1", "name": "Pharm 1", "opens": _day(3), "tags": ["Step1::Cardio::Heart_failure"]}])
            plan2, _ = maya.follow_plan(code2)
            F.on_followed(plan2, 10, None, "open")
            maya.fetch_board(labels, with_decks=True)
            F._last.update(key=None, got=None)
            F.refresh_progress()
            lv = F.load_view(F.followed(), F._state_cfg(), _day(0))
            had_labels, F._state["labels"] = F._state.get("labels"), labels  # the board's today
            in_board = F.board_view({})
            F._state["labels"] = had_labels
            check("load: through the glue: both plans on this deck, each set on my day with what's new to me then",
                  lv is not None and {x["pid"] for x in lv["plans"]} == {pid, pid2}
                  and lv["days"][3]["new"] == sum(lv["days"][3]["parts"]) > 1 and len(lv["days"]) == 7
                  and (in_board.get("load") or {}).get("plans") == lv["plans"]
                  and "Everything this week" in board.plancards._you_plans(in_board), lv)
            F.move_date(pid, "cz", 2)
            maya.set_days(pid, shift=3)
            asked = []
            F.confirm = lambda *a: asked.append(a[1] + "\n" + a[2]) or True
            from due_crew import ui as UI
            real_confirm, UI.confirm = UI.confirm, F.confirm
            try:
                dc._on_js(False, as_board(f"duecrew:planreset:{pid}"), DeckBrowser())
            finally:
                UI.confirm = real_confirm
            f = store.follows[(pid, "maya")]
            check("reset to default: one question saying what goes back, then all of it at once",
                  asked and "Reset to default?" in asked[0] and "Your dates run 3 days later" in asked[0]
                  and f.get("shift", 0) == 0 and not f.get("skipped") and not f.get("moved"), (asked, f))
        finally:
            F._bg = saved[0]
    store2 = world({"dre": "Dre", "kai": "Kai"})
    pid2, code2 = store2.add_plan("dre", "Step 1", "Step 1", _plan_units())
    kai = new_client(store2, "kai", "Kai")
    col2 = _plan_col()
    with _PlanGlue({"B": kai}, {"B": col2}):
        F._bg = lambda job, done=None: done(job()) if done else job()
        try:
            plan, _ = kai.follow_plan(code2)
            F.on_followed(plan, 10, None, "begin:7")
            check("late, from the beginning: my dates run that many days later; the first opens today",
                  store2.follows[(pid2, "kai")]["shift"] == 7 and 1 in _open(col2) and 3 not in _open(col2), str(_open(col2)))
        finally:
            F._bg = saved[0]
    store4 = world({"dre": "Dre", "bo": "Bo"})
    pid4, code4 = store4.add_plan("dre", "Step 1", "Step 1", _plan_units())
    bo = new_client(store4, "bo", "Bo")
    col4 = _plan_col()
    with _PlanGlue({"D": bo}, {"D": col4}):
        F._bg = lambda job, done=None: done(job()) if done else job()
        try:
            plan, _ = bo.follow_plan(code4)
            bo.set_days = lambda *a, **k: None  # offline
            F.on_followed(plan, 10, None, "skip:hf")
            check("late, offline: the passed date never opens (skipped here), today's does",
                  1 not in _open(col4) and 3 in _open(col4), str(_open(col4)))
        finally:
            F._bg = saved[0]
    store5 = world({"dre": "Dre", "cy": "Cy"})
    pid5, code5 = store5.add_plan("dre", "Step 1", "Step 1", _plan_units())
    cy = new_client(store5, "cy", "Cy")
    col5 = _plan_col()
    col5.db.conn.execute("UPDATE cards SET queue = 0 WHERE queue = -1")  # a deck imported all active
    with _PlanGlue({"E": cy}, {"E": col5}):
        F._bg = lambda job, done=None: done(job()) if done else job()
        try:
            plan, _ = cy.follow_plan(code5)
            F.on_followed(plan, 10, None, "begin:7", hold=True)
            st5 = F._state_cfg()[pid5]
            check("late, from the beginning with Hold back: what's later for me (the plan's today) is held",
                  3 in (st5.get("held") or []) and 1 not in (st5.get("held") or []), st5.get("held"))
        finally:
            F._bg = saved[0]
    store3 = world({"dre": "Dre", "lu": "Lu"})
    pid3, code3 = store3.add_plan("dre", "Step 1", "Step 1", _plan_units())
    lu = new_client(store3, "lu", "Lu")
    col3 = _plan_col()
    with _PlanGlue({"C": lu}, {"C": col3}):
        F._bg = lambda job, done=None: done(job()) if done else job()
        try:
            plan, _ = lu.follow_plan(code3)
            F.on_followed(plan, 10, None, "catch:1:14")
            st = F._state_cfg()[pid3]
            check("late, catch up: the passed date opens and a week's catch-up runs (+2 a day)",
                  1 in _open(col3) and st.get("catch", {}).get("extra") == 2 and st["catch"]["until"] == _day(6), st.get("catch"))
            card = F.card_view(next(x for x in F.followed() if x["id"] == pid3), st, {"hf": [2, 0, 2]}, _day(0))
            h = board._plan_card_html(dict(card, session={"kind": "study", "target": 3, "done": 0, "behind": 2}))
            check("late, catch up: what it's catching up on isn't called behind (plans, end to end: on the path neither)",
                  "Catching up: +2 new a day" in h and "pn warn" not in h and "behind" not in h
                  and '<i class="c" title="Heart failure &middot; catching up' in h and "planbehind" not in h, h)
        finally:
            F._bg = saved[0]


def test_plans_fresh_after_cached_morning_v311():
    """3.1.1: the morning at the sync can run on yesterday's cached plans;
    the day's fresh ones, arriving after, still get their look."""
    store = world({"dre": "Dre", "maya": "Maya"})
    pid, code = store.add_plan("dre", "Step 1", "Step 1", _plan_units())
    maya = new_client(store, "maya", "Maya")
    with _PlanGlue({"A": maya}, {"A": _plan_col()}) as g:
        F, col = g.F, g.cols["A"]
        plan, _ = maya.follow_plan(code)
        maya.session["plans"] = []           # the cache: from before the follow
        F.maybe_morning(False)               # at the sync, before the refresh
        check("fresh: the morning ran on the cache, and found nothing", g.state().get("plans_day") == _day(0)
              and _open(col) == {8})
        maya.fetch_board([_day(0)], with_decks=True)
        F.maybe_morning(False, fresh=True)   # the refresh
        check("fresh: the day's plans still open what's due today", 3 in _open(col), str(_open(col)))
        n = len(col.undo_steps)
        F.maybe_morning(False, fresh=True)
        check("fresh: a second look opens nothing twice, and makes no step", len(col.undo_steps) == n)


def test_plans_undo_waits_v311():
    """3.1.1: the board's Undo clears the card and counts only once Anki's
    undo has actually happened (a CollectionOp, run in the background)."""
    store = world({"dre": "Dre", "maya": "Maya"})
    pid, code = store.add_plan("dre", "Step 1", "Step 1", _plan_units())
    maya = new_client(store, "maya", "Maya")
    pending = []

    class Op:
        def __init__(self, parent, op):
            self.op, self.ok = op, None

        def success(self, fn):
            self.ok = fn
            return self

        def failure(self, fn):
            return self

        def run_in_background(self):
            pending.append(self)

    ops = types.ModuleType("aqt.operations")
    ops.CollectionOp = Op
    coll = types.ModuleType("aqt.operations.collection")
    coll.undo = lambda parent=None: pending.append(None)
    sys.modules["aqt.operations"], sys.modules["aqt.operations.collection"] = ops, coll
    try:
        with _PlanGlue({"A": maya}, {"A": _plan_col()}) as g:
            F, col = g.F, g.cols["A"]
            plan, _ = maya.follow_plan(code)
            F.open_schedule = _skip_schedule
            F.on_followed(plan, 10, None, "open")
            check("undo: set up", g.state().get("plans_opened", {}).get("label") == "Due Crew: open 2 sets")
            F.undo_morning()
            check("undo: nothing is cleared before the undo has happened",
                  bool(g.state().get("plans_opened")) and 1 in _open(col))
            op = next((p for p in pending if p is not None), None)
            if op is not None:
                op.ok(op.op(col))
            check("undo: once it has, the step's cards are back and the card forgets it",
                  op is not None and 1 not in _open(col) and not g.state().get("plans_opened")
                  and F._state["plan_progress"][pid]["hf"][0] == 0)
    finally:
        sys.modules.pop("aqt.operations", None)
        sys.modules.pop("aqt.operations.collection", None)


def test_plans_notes_mode_v311():
    """3.1.1: Add to a plan in the browser's Notes mode would take every
    card of the picked notes; it asks for Cards mode instead."""
    maya = new_client(world({"maya": "Maya"}), "maya", "Maya")
    with _PlanGlue({"A": maya}, {"A": _plan_col()}) as g:
        asked = []
        browser = types.SimpleNamespace(table=types.SimpleNamespace(is_notes_mode=lambda: True),
                                        selected_cards=lambda: asked.append(1) or [5])
        try:
            g.F.add_to_plan(browser)
        except Exception:
            pass
        check("notes mode: no cards are taken, and it says to switch to Cards",
              not asked and g.toasts and "Cards" in g.toasts[-1], str(g.toasts))


def test_plan_search_is_the_decks_v34():
    """3.4 review: the browser's search goes to a plan only when it finds the
    same cards in everyone's copy. Anki's own deck:current (the browser's
    default) would open a follower's whole deck; is:due, flags and ratings
    are one person's."""
    from due_crew import plans
    for q in ("deck:current", '"deck:current" tag:x', "is:due", "-is:suspended tag:a", "flag:1", "(rated:1 or tag:x)", " "):
        check(f"search: {q!r} isn't a plan's", not plans.shareable_search(q))
    for q in ("tag:*Cardio* -tag:*Pharm*", "tag:Step1::Renal", "current events", '"deck:Step 1::Renal"'):
        check(f"search: {q!r} is", plans.shareable_search(q))
    maya = new_client(world({"maya": "Maya"}), "maya", "Maya")
    with _PlanGlue({"A": maya}, {"A": _plan_col()}) as g:
        edit = types.SimpleNamespace(lineEdit=lambda: types.SimpleNamespace(text=lambda: "deck:current"))
        browser = types.SimpleNamespace(table=types.SimpleNamespace(is_notes_mode=lambda: False),
                                        form=types.SimpleNamespace(searchEdit=edit), selected_cards=lambda: [])
        try:
            g.F.add_to_plan(browser)
        except Exception:
            pass
        check("search: the default search with nothing picked asks for a search or cards",
              g.toasts and "Search for the cards" in g.toasts[-1], str(g.toasts))
        check("review: a filtered deck sits under Due Crew; a date named with :: makes no deeper one",
              g.F._deck_name("Checkpoint · Renal::Pharm") == "Due Crew::Checkpoint · Renal: Pharm"
              and g.F._deck_name("  ") == "Due Crew::Cards")


def test_sign_in_keeps_anki_synced_v311():
    """3.1.1: signing in or out mid-session doesn't forget that AnkiWeb has
    synced (it's about the collection); the plans' morning isn't held back."""
    import due_crew as dc
    from due_crew.app import _state
    saved = sys.modules.get("due_crew.ui.auth_dialog")
    fake = types.ModuleType("due_crew.ui.auth_dialog")

    class Dlg:
        def __init__(self, *a, **k):
            self.user, self.joined = ("sam", "Sam"), False

        def exec(self):
            return True
    fake.AuthDialog = Dlg
    sys.modules["due_crew.ui.auth_dialog"] = fake
    saved_fns = (dc.client, dc._on_sync_done)
    signed_in = new_client(world({"sam": "Sam"}), "sam", "Sam")
    dc.client, dc._on_sync_done = (lambda: signed_in), (lambda **kw: None)
    try:
        _state["anki_synced"] = True
        dc._on_signed_out()
        out_ok = _state["anki_synced"] is True
        _state["anki_synced"] = True
        try:
            dc.open_auth()
        except Exception:
            pass
        check("sign-in: AnkiWeb having synced survives signing out and in",
              out_ok and _state["anki_synced"] is True)
    finally:
        if saved is not None:
            sys.modules["due_crew.ui.auth_dialog"] = saved
        else:
            sys.modules.pop("due_crew.ui.auth_dialog", None)
        dc.client, dc._on_sync_done = saved_fns
        _state["anki_synced"] = False


def test_refresh_generation_v311():
    """3.1.1: a refresh still running when the profile switches doesn't
    land in the next profile, and doesn't hold back that profile's own."""
    import due_crew as dc
    from due_crew import app as appmod
    from due_crew.app import _state
    store = world({"sam": "Sammy", "dre": "Dre", "eve": "Eve"}, {"sam": ["dre"], "dre": ["sam"]})
    sam, eve = new_client(store, "sam", "Sammy"), new_client(store, "eve", "Eve")
    jobs = []

    class Thread:
        def __init__(self, target, daemon=None):
            self.target = target

        def start(self):
            jobs.append(self.target)

    who = {"cl": sam}
    saved = (dc.client, dc.threading, dc.account.ensure, dc._menu_done, dc.mw.col,
             dc.plan_flow.maybe_morning, dc._update_wrap, dc._update_returns)
    dc.client = lambda: who["cl"]
    dc.threading = types.SimpleNamespace(Thread=Thread)
    dc.account.ensure = lambda *a, **k: None
    dc._menu_done = True
    dc.plan_flow.maybe_morning = lambda *a, **k: None
    dc._update_wrap = lambda *a, **k: None
    dc._update_returns = lambda *a, **k: []
    dc.mw.col = make_user_col([TODAY])
    try:
        dc._reset_runtime()
        dc.refresh_board()
        old_job = jobs[-1] if jobs else None
        who["cl"] = eve
        n = len(jobs)
        dc._on_profile_open()
        check("profile switch: the new profile's first refresh isn't held back by the old one's",
              len(jobs) == n + 1)
        if old_job:
            old_job()
        check("profile switch: the old profile's board doesn't land in the new one",
              _state["entries"] is None and _state["my_code"] == "", str(_state["entries"])[:120])
        if len(jobs) > n:
            jobs[n]()
        check("profile switch: the new profile's own board does",
              bool(_state["entries"]) and _state["entries"][0]["user_id"] == "eve")
        gen = appmod.generation
        dc._on_profile_close()
        check("profile close: nothing in flight commits after it", not dc._current(gen))
    finally:
        (dc.client, dc.threading, dc.account.ensure, dc._menu_done, dc.mw.col,
         dc.plan_flow.maybe_morning, dc._update_wrap, dc._update_returns) = saved
        dc._closing = False
        dc._fetching = False
        dc._reset_runtime()


def test_morning_not_while_closing_v311():
    """3.1.1: Anki's close runs its own AnkiWeb sync after profile_will_close;
    the plans' morning doesn't run on it."""
    import due_crew as dc
    ran = []
    saved = dc.plan_flow.maybe_morning
    dc.plan_flow.maybe_morning = lambda *a, **k: ran.append(a)
    try:
        dc._closing = True
        dc._sync_failed()
        dc._morning_fallback()
        check("closing: no morning", ran == [], str(ran))
    finally:
        dc.plan_flow.maybe_morning = saved
        dc._closing = False


def test_close_sync_light_v391():
    """3.9.1: Anki's own sync as it closes (after profile_will_close) sends
    today's numbers only, as the pushes on open do, and nothing when the
    collection, my day and my config are as the last push that went had
    them. Any other sync is the full one, and leaving a room on close still
    goes (rooms.on_close pushes it itself)."""
    import due_crew as dc
    from due_crew.app import _state
    src = srcs.glue_src()
    check("close sync: Anki's sync tip lands in _on_anki_sync",
          "sync_did_finish.append(_on_anki_sync)" in src and "sync_did_finish.append(_on_sync_done)" not in src)
    col = make_user_col([TODAY - datetime.timedelta(days=i) for i in range(3)])
    col.mod = 111
    cl = new_client(world({"sam": "Sam"}), "sam", "Sam")
    files = tempfile.mkdtemp()
    pushes, lights = [], []
    from due_crew import team_flow
    names = ("client", "cfg", "_profile_files", "_awaiting_phone", "refresh_board", "_pushed", "_closing", "_last_attempt")
    saved = {k: getattr(dc, k) for k in names}
    saved_mods = (dc.mw.col, dc.account.ready, dc.plan_flow.for_sync, dc.plan_flow.maybe_morning, dc.crew_cards.for_sync,
                  dc.bingo_flow.for_row, team_flow.for_sync, _state.get("sync_error"))
    dc.mw.col, dc.client, dc.cfg, dc._profile_files = col, (lambda: cl), (lambda: {}), (lambda: files)
    dc._awaiting_phone = lambda: False
    dc.account.ready = lambda: True
    dc.refresh_board = lambda **kw: pushes.append(kw)
    dc.plan_flow.for_sync = lambda: None
    dc.plan_flow.maybe_morning = lambda *a, **k: None
    dc.crew_cards.for_sync = lambda c, light=False: lights.append(light) or None
    dc.bingo_flow.for_row = lambda c: None
    team_flow.for_sync = lambda c: None
    _state["sync_error"] = False
    try:
        dc._closing, dc._pushed = False, None
        dc._on_anki_sync()
        check("close sync: a sync while Anki is open is the full one, as before",
              len(pushes) == 1 and pushes[0]["backfill"] is not None and pushes[0]["heatmap"] is not None and lights == [False])
        check("close sync: a push keeps what its numbers came from", dc._pushed == (111, TODAY.isoformat(), {}), dc._pushed)
        dc._closing = True
        dc._on_anki_sync()
        check("close sync: closing with nothing new since the last push that went, nothing is gathered or sent",
              len(pushes) == 1)
        dc._on_sync_done(light=True, fetch=False)  # what rooms.on_close does
        check("close sync: leaving a room on close still goes", len(pushes) == 2 and pushes[1]["fetch"] is False)
        col.mod = 112  # the close's own sync sent or brought something
        dc._on_anki_sync()
        check("close sync: closing after something changed, today's numbers only: no week, decks, heatmap, known cards or log",
              len(pushes) == 3 and pushes[2]["upload_stats"] is not None and pushes[2]["backfill"] is None
              and pushes[2]["shared_decks"] is None and pushes[2]["heatmap"] is None and lights[-1] is True)
        _state["sync_error"] = True
        dc._on_anki_sync()
        check("close sync: the last push didn't go, so this one does", len(pushes) == 4)
        _state["sync_error"] = False
        dc._pushed = None
        dc._on_anki_sync()
        check("close sync: nothing pushed yet this time Anki was open, it goes", len(pushes) == 5)
    finally:
        for k, v in saved.items():
            setattr(dc, k, v)
        (dc.mw.col, dc.account.ready, dc.plan_flow.for_sync, dc.plan_flow.maybe_morning, dc.crew_cards.for_sync,
         dc.bingo_flow.for_row, team_flow.for_sync, _state["sync_error"]) = saved_mods


def test_morning_waits_for_decks_v380():
    """3.8.0: the morning never unsuspends on the review screen (its undo
    step would sit on top of the last answer). It waits for the Decks
    screen, which runs it as the call would have."""
    import sys as _sys
    import due_crew as dc
    from due_crew import plan_flow as F
    from due_crew.app import _state
    store = world({"dre": "Dre", "maya": "Maya"})
    pid, code = store.add_plan("dre", "Step 1", "Step 1", _plan_units())
    maya = new_client(store, "maya", "Maya")
    col = _plan_col()
    box = {"cfg": {}}
    saved = {k: getattr(F, k) for k in ("cfg", "save_cfg", "_pcfg", "_psave", "client", "_today", "tooltip")}
    saved_col, saved_swap, saved_state = F.mw.col, F.app.swap, F.mw.state
    saved_dc = {k: getattr(dc, k) for k in ("_awaiting_phone", "_swap", "client")}
    qt = _sys.modules["aqt.qt"]
    saved_timer = qt.QTimer
    F.cfg = F._pcfg = lambda: box["cfg"]
    F.save_cfg = F._psave = lambda c: box.update(cfg=c)
    F.client = dc.client = lambda: maya
    F._today = lambda: _day(0)
    F.tooltip = lambda text, **kw: None
    F.mw.col = col
    F.app.swap = lambda c: None
    try:
        plan, _ = maya.follow_plan(code)
        box["cfg"]["plans"] = {pid: F.new_state(col, plan)}
        maya.fetch_board([_day(0)], with_decks=True)
        F.mw.state = "review"
        F.maybe_morning(False)  # what the 3-minute fallback calls
        check("morning: not on the review screen: nothing unsuspends, no undo step",
              _open(col) == {8} and not col.undo_steps and "plans_day" not in box["cfg"])
        check("morning: it waits for the Decks screen, as called",
              _state["plans_morning"] == {"awaiting": False, "fresh": False}, str(_state["plans_morning"]))
        F.maybe_morning(True, fresh=True)  # a refresh while still reviewing, before any AnkiWeb sync
        check("morning: a later call still waiting for AnkiWeb leaves the waiting morning as it was",
              _state["plans_morning"] == {"awaiting": False, "fresh": False} and _open(col) == {8},
              str(_state["plans_morning"]))
        F.mw.state = "deckBrowser"
        qt.QTimer = type("QTimer", (), {"singleShot": staticmethod(lambda ms, fn: fn())})
        dc._awaiting_phone = lambda: True  # still no AnkiWeb sync: the fallback's word stands
        dc._swap = lambda c: None
        dc._on_did_render(None)
        check("morning: the Decks screen runs it, in one undo step",
              _open(col) == {1, 2, 3, 8} and len(col.undo_steps) == 1 and box["cfg"]["plans_day"] == _day(0)
              and _state["plans_morning"] is None, str(_open(col)))
        dc._on_did_render(None)
        check("morning: once", len(col.undo_steps) == 1)
    finally:
        for k, v in saved.items():
            setattr(F, k, v)
        for k, v in saved_dc.items():
            setattr(dc, k, v)
        qt.QTimer = saved_timer
        F.mw.col, F.app.swap, F.mw.state = saved_col, saved_swap, saved_state
        _state["plans_morning"] = None


def test_asks_and_tips_v390():
    """3.9.0 (Sam's picks, "Asks and tips"): 1, an ask still goes to everyone
    in the crew with the card, and the dialog says so first (W1); 2, a tip's,
    an ask's or a plan note's words are folded until Show, on the card and in
    the bar, so nothing gives away what a one-by-one card still hides (who
    knows it isn't folded: it names people); his note: the tip peeks in with
    its tipper's Pip, as who knows it does. Opened stays opened."""
    import shutil
    import subprocess
    from due_crew import cards as K, ui
    from due_crew.app import _state
    names = {"dre": ("Dre Ng", ""), "sam": ("Sam", "")}
    pips = {"dre": {"svg": "<svg></svg>", "a": ["#1e5fb4", "#7fb2f0"]}}
    # 1 · the Ask dialog's words
    got, saved = [], (getattr(ui, "ask_text", None), K._card, K.client, K.flag, dict(_state))
    store = world({"sam": "Sam"})
    sam = new_client(store, "sam", "Sam")
    card = types.SimpleNamespace(note=lambda: types.SimpleNamespace(guid="guid000001"), ord=0, id=1)
    try:
        ui.ask_text = lambda parent, title, label, text="": (got.append((title, label)), ("", False))[1]
        K._card, K.client, K.flag = (lambda: card), (lambda: sam), (lambda c, q: None)
        _state["entries"] = [{"user_id": "dre", "name": "Dre Ng", "you": False}, {"user_id": "mo", "name": "Mo", "you": False}]
        sam.session["cards"] = {"guid000001": {"knows": ["dre"], "tips": []}}
        K.ask()
        sam.session["cards"] = {"guid000001": {"knows": ["dre", "mo"], "tips": []}}
        K.ask()
        sam.session["cards"] = {}
        K.ask()
    finally:
        if saved[0] is not None:
            ui.ask_text = saved[0]
        K._card, K.client, K.flag = saved[1:4]
        _state.clear()
        _state.update(saved[4])
    check("ask: it says it goes to everyone with the card, then who has it down (Sam's pick, W1)",
          [g[1] for g in got] == ["Goes to everyone in your crew who has this card. Dre has it down. One line, optional.",
                                  "Goes to everyone in your crew who has this card. Dre and Mo have it down. One line, optional.",
                                  "Goes to everyone in your crew who has this card. One line, optional."]
          and got[0][0] == "Ask your crew about this card", got)
    # 2 · folded till Show; the tipper's Pip
    tip = K.chip_view({"tips": [{"from": "dre", "text": "think loops", "helped": False}]}, [], names, pips=pips)
    tip_off = K.chip_view({"tips": [{"from": "dre", "text": "think loops", "helped": False}]}, [], names)
    asked = K.chip_view(None, [], names, asks=[("dre", 1, "why axillary?")], pips=pips)
    bare = K.chip_view(None, [], names, asks=[("dre", 1)], pips=pips)
    knows = K.chip_view({"knows": ["dre"], "tips": []}, [], names, pips=pips)
    note = K.remark_view([{"name": "Block 1", "doc": {"remarks": [{"card": ["guid000001", 0], "text": "the second cloze"}]}}], "guid000001", 0)
    check("fold: a tip says who left it, with the Pip peeking in; Pip off, the same bubble with the bulb; the words wait",
          tip["fold"] == "Dre left a tip" and tip["peek"] == {"uids": ["dre"], "head": "Dre: think loops", "act": "This helped"}
          and tip["pip"] == pips["dre"] and tip["text"] == "\U0001F4A1 Dre: think loops"
          and tip_off["fold"] == "\U0001F4A1 Dre left a tip" and tip_off["peek"]["uids"] == [] and "pip" not in tip_off, (tip, tip_off))
    check("fold: an ask's line and a plan's note fold too; an ask with no line, and who knows it, don't (nothing to give away)",
          asked["fold"] == "Dre asked about this card" and asked["text"] == "Dre: \u201cwhy axillary?\u201d"
          and "fold" not in bare and "fold" not in knows and note["fold"] == "\U0001F4CC A note from Block 1", (asked, note))
    fj, bj = K.float_js(dict(tip, accent=["#2e7d32", "#7cc47f"])), K.chip_js(dict(tip, accent="#2e7d32"))
    check("fold: on the card, Show opens it (the words, This helped, more); no words on a hover while folded; drawn again opened, no pop",
          "var folded = !!(D.fold && !D.open);" in fj and "link('Show', acc, true, open)" in fj
          and "words.textContent = folded ? D.fold : (peek ? peek.head : D.text);" in fj
          and "if (D.title && !folded) { words.title = D.title; } else { words.removeAttribute('title'); }" in fj
          and "if (peek && !still && !D.open && bub.animate)" in fj and "pad.style.height = (box.offsetHeight + 12) + 'px'" in fj
          and "send(D.fold && !folded ? 'knowsbar:open' : 'knowsbar')" in fj)
    check("tip: a note, not a speech bubble (SC, 3.9.12; Sam, 3.9.0: too alike): a wash of its writer's colour (mine with Pip off), "
          "a folded corner, Tip over its words; a crewmate's or my own; who knows it, the plain bubble",
          "var note = !!peek && (D.kind === 'tip' || D.kind === 'hook');" in fj and "color-mix(in srgb, ' + tint + ' 13%, ' + c.bg + ')" in fj
          and "var tint = note ? (withPip ? peek.pips[0].a[night ? 1 : 0] : acc) : '';" in fj and "linear-gradient(225deg, transparent 50%, ' + tint + ' 50%)" in fj
          # the folded corner is cut off the note, and the shadow follows the cut (SC: nothing behind the fold)
          and "clip-path:polygon(0 0, calc(100% - 14px) 0, 100% 14px, 100% 100%, 0 100%);" in fj and "filter:drop-shadow(" in fj and "box-shadow:none;" in fj
          and "text-transform:uppercase;color:' + tint + ';', 'Tip')" in fj and "+ card + edge);" in fj and tip["kind"] == "tip" and knows["kind"] == "knows")
    check("tip: its writer's Pip waves while the note is folded and holds it out once it's opened (Show, or drawn again opened)",
          "if (fig && note && peek.pips[0].held) {" in fj and "pip(fig, {pip: {svg: peek.pips[0].held, a: peek.pips[0].a}, sevcss: D.sevcss}, night, '');" in fj
          and "var drawn = note && D.open && peek.pips[i].held ? {svg: peek.pips[i].held, a: peek.pips[i].a} : peek.pips[i];" in fj
          and 'p["held"] = peek_pip(u, "again")' in open(os.path.join(REPO, "due_crew", "cards.py"), encoding="utf-8").read()
          and "m-again" in (K.my_peek_pip() or {}).get("held", "") and "m-peek" in (K.my_peek_pip() or {}).get("svg", ""))
    check("fold: in the bar the same, a click opens it, then its act and its click as before",
          "var folded = !!(D.fold && !D.open);" in bj and "var act = folded ? 'Show' : D.act;" in bj
          and "if (D.actcmd && !folded)" in bj and "if (folded) { s.removeAttribute('title'); }" in bj
          and "if (folded) {\n      folded = false; said(); if (window.dcBarBalance) { window.dcBarBalance(); }" in bj)
    node = shutil.which("node")
    if node:
        ok = subprocess.run([node, "--check"], input=fj + "\n;" + bj, capture_output=True, text=True, timeout=30)
        check("fold: its scripts parse", ok.returncode == 0, ok.stderr[-400:])
    # opened stays opened: This helped draws it again open; the move to the bar keeps it open
    shown, bars, saved = [], [], (K._bottom, K._review_web, K._show, K.client, dict(_state), dict(K._LAST))
    sam.session["cards"] = {"guid000001": {"knows": [], "tips": [{"from": "dre", "text": "think loops", "at": 1, "helped": False}]}}
    try:
        K._bottom, K._review_web, K._show, K.client = (lambda: types.SimpleNamespace(eval=bars.append)), (lambda: None), shown.append, (lambda: sam)
        _state["entries"] = [{"user_id": "dre", "name": "Dre Ng", "you": False, "accent": "blue", "look": []}]
        K.on_answer(card)
        K.on_answer(card, opened=True)
        K._LAST["view"] = shown[0]
        K.on_message("knowsbar", ["duecrew", "knowsbar", "open"], from_card_page=True)
        K.on_message("knowsbar", ["duecrew", "knowsbar"], from_card_page=True)
    finally:
        K._bottom, K._review_web, K._show, K.client = saved[:4]
        _state.clear()
        _state.update(saved[4])
        K._LAST.clear()
        K._LAST.update(saved[5])
    check("open: a tip on the review screen peeks in with Dre's Pip, folded; drawn again after This helped, open",
          shown[0]["kind"] == "tip" and "open" not in shown[0] and shown[1]["open"] is True
          and len(shown[0]["peek"]["pips"]) == 1 and "m-peek" in shown[0]["peek"]["pips"][0]["svg"], shown)
    check("open: knowsbar:open moves it to the bar open; plain knowsbar, as it was",
          len(bars) == 2 and '"open": true' in bars[0] and '"open": true' not in bars[1], [b[-200:] for b in bars])
    import inspect
    check("open: This helped draws the card again with its words showing",
          "on_answer(card, opened=True)" in inspect.getsource(K.helped))


def test_plain_prompts_v311():
    """3.1.1: prompts that carry a crewmate's name are plain-text labels."""
    from due_crew import together, ui
    from due_crew.app import _state
    got = []
    saved = (getattr(ui, "ask_text", None), _state.get("entries"))
    ui.ask_text = lambda parent, title, label, text="": (got.append(label), ("", False))[1]
    _state["entries"] = [{"user_id": "dre", "name": "<b>Dre</b> K", "you": False}]
    try:
        together.send_luck_line("dre")  # off the board: Qt's plain-text prompt (3.9.1: on it, a sheet's textContent)
        check("prompts: a crewmate's name goes through the plain-text prompt",
              len(got) == 1 and got[0].startswith("A line for <b>Dre</b>'s exam morning"), got)
    finally:
        if saved[0] is not None:
            ui.ask_text = saved[0]
        _state["entries"] = saved[1]


def test_anki_day_labels_v311():
    """3.1.1: the Anki day before the first refresh (account._today), and
    day labels across a DST change with rollover at midnight."""
    import time as _time
    from due_crew import account
    from due_crew.app import _state
    saved_col = account.mw.col
    account.mw.col = make_user_col([])
    _state["labels"] = []
    try:
        check("account: before the first refresh, today is Anki's day", account._today() == TODAY.isoformat())
    finally:
        account.mw.col = saved_col
    if not hasattr(_time, "tzset"):
        return
    old_tz = os.environ.get("TZ")
    os.environ["TZ"] = "America/New_York"
    _time.tzset()
    try:
        # clocks go forward on Sun 8 Mar 2026: a 23-hour day
        cutoff = int(datetime.datetime(2026, 3, 9, 0, 0).timestamp())
        q = StatsQueries(types.SimpleNamespace(sched=types.SimpleNamespace(day_cutoff=cutoff)))
        got = [q.day_label(i) for i in (-1, 0, 1, 2)]
        check("day labels: rollover at midnight, across the spring DST change",
              got == ["2026-03-09", "2026-03-08", "2026-03-07", "2026-03-06"], str(got))
        cutoff = int(datetime.datetime(2026, 11, 2, 0, 0).timestamp())  # back on Sun 1 Nov
        q = StatsQueries(types.SimpleNamespace(sched=types.SimpleNamespace(day_cutoff=cutoff)))
        check("day labels: and the autumn one", [q.day_label(i) for i in (0, 1)] == ["2026-11-01", "2026-10-31"])
        cutoff = int(datetime.datetime(2026, 3, 9, 4, 0).timestamp())
        q = StatsQueries(types.SimpleNamespace(sched=types.SimpleNamespace(day_cutoff=cutoff)))
        check("day labels: unchanged at a 4am rollover", q.day_label(0) == "2026-03-08")
    finally:
        if old_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old_tz
        _time.tzset()


def _skip_schedule(pid, then=None):
    """The schedule dialog, as if Cancel was pressed (no Qt here)."""
    if then:
        then()


def _spread_col(n=10):
    """Step 1 (10): n suspended new cards tagged Renal, positions n..1 (so
    the deck's order is the reverse of their ids), one of them a leech."""
    conn = sqlite3.connect(":memory:")
    fakes.make_collection(conn)
    for i in range(n):
        fakes.add_card(conn, 100 + i, did=10, queue=-1, tags="Step1::Renal" + (" leech" if i == 0 else ""), due=n - i)
    col = fakes.FakeCol(conn, fakes.day_cutoff_for(TODAY))
    col.decks = fakes.FakeDecks({10: "Step 1"})
    return col


def test_schedule_model_v32():
    """3.2: a unit's cards spread over my study days in its window; rest
    days, catch-up weeks and the taper take none; a later start moves only
    my dates; pushing back can't pass the end date."""
    from due_crew import schedule as S
    D = S.d
    mon = D("2026-10-05")  # a Monday
    unit = {"id": "rn", "name": "Renal", "opens": "2026-10-05", "due": "2026-10-11"}
    doc = {"deck": "Step 1", "units": [unit]}
    five = {"days": [1, 1, 1, 1, 1, 0, 0], "minutes": 60}
    q = [S.quota(doc, unit, five, 100, mon + datetime.timedelta(days=i)) for i in range(7)]
    check("spread: five study days take a fifth each, and the weekend none",
          q == [20, 40, 60, 80, 100, 100, 100], str(q))
    double = {"days": [1, 1, 1, 1, 1, 2, 0], "minutes": 60}
    q2 = [S.quota(doc, unit, double, 70, mon + datetime.timedelta(days=i)) for i in range(7)]
    check("spread: a double day takes twice the share", q2[4] - q2[3] == 10 and q2[5] - q2[4] == 20, str(q2))
    check("spread: no schedule opens the unit whole on its first day, as 3.1 did",
          S.quota(doc, unit, None, 100, mon) == 100 and S.quota(doc, unit, None, 100, mon - datetime.timedelta(days=1)) == 0)
    check("spread: the last day of the window has it all open", S.quota(doc, unit, five, 7, D("2026-10-11")) == 7)
    weekend = {"id": "w", "name": "W", "opens": "2026-10-10", "due": "2026-10-11"}
    check("spread: a window with no study day opens whole on my next study day",
          S.quota({"units": [weekend]}, weekend, five, 9, D("2026-10-11")) == 0
          and S.quota({"units": [weekend]}, weekend, five, 9, D("2026-10-12")) == 9)
    nodue = [{"id": "a", "name": "A", "opens": "2026-10-05"}, {"id": "b", "name": "B", "opens": "2026-10-08"}]
    check("window: without a due date, up to the day before the next date opens",
          S.window({"units": nodue}, nodue[0]) == (mon, D("2026-10-07")))
    later = dict(five, start="2026-10-12")
    check("start later: my dates move by the difference, the plan's don't",
          S.shift_days(doc, later) == 7 and S.quota(doc, unit, later, 100, D("2026-10-09")) == 0
          and S.quota(doc, unit, later, 100, D("2026-10-12")) == 20)
    ph = {"deck": "x", "end": "2026-11-15", "phases": {"catchup": 4, "taper": 7},
          "units": [dict(unit, due=None)]}
    check("phases: every 4th week is a catch-up week",
          S.phase(ph, D("2026-10-26")) == "catchup" and S.phase(ph, D("2026-10-19")) == "build")
    check("phases: the taper is the last 7 days up to the end",
          S.phase(ph, D("2026-11-09")) == "taper" and S.phase(ph, D("2026-11-08")) == "build"
          and S.weight(ph, five, D("2026-11-10")) == 0)
    long_unit = {"id": "l", "name": "L", "opens": "2026-10-19", "due": "2026-11-01"}
    lp = dict(ph, units=[dict(unit, due=None), long_unit])
    q3 = [S.quota(lp, long_unit, five, 50, D("2026-10-19") + datetime.timedelta(days=i)) for i in range(14)]
    check("spread: a catch-up week in the window opens nothing new",
          q3[6] == 50 and q3[7] == 50 and q3[4] == 50, str(q3))
    check("push back: a later start, as a date", S.pushed_start(doc, five, 2)["start"] == "2026-10-07")
    check("push back: never past the plan's end date",
          S.pushed_start(dict(doc, end="2026-10-12"), five, 2) is None
          and S.pushed_start(dict(doc, end="2026-10-13"), five, 2) is not None)
    view = S.today_view(doc, five, {"rn": 100}, {"rn": 10}, 5, D("2026-10-07"), catch="spread")
    check("today: my share, plus a quarter of what I'm behind when I chose to spread it",
          view["share"] == 20 and view["behind"] == 30 and view["target"] == 28 and view["done"] == 5, str(view))
    leave = S.today_view(doc, five, {"rn": 100}, {"rn": 10}, 0, D("2026-10-07"), catch="leave")
    check("today: leaving it open keeps just the share", leave["target"] == 20)
    caught = S.today_view(doc, five, {"rn": 100}, {"rn": 10}, 30, D("2026-10-07"), catch="leave", seen_now={"rn": 40})
    check("today: catching up today clears behind (it's counted now, not this morning)",
          caught["behind"] == 0 and caught["target"] == 20 and caught["done"] == 0, str(caught))
    ahead = S.today_view(doc, five, {"rn": 100}, {"rn": 10}, 50, D("2026-10-07"), seen_now={"rn": 60})
    check("today: past what was behind, the rest is today's", ahead["behind"] == 0 and ahead["done"] == 20, str(ahead))
    sib = S.today_view(doc, five, {"rn": 100}, {"rn": 45}, 15, D("2026-10-07"), seen_now={"rn": 60})
    check("today: what was already seen (a started note's siblings) isn't asked again",
          sib["target"] == 15 and sib["done"] == 15 and sib["behind"] == 0, str(sib))
    rest = S.today_view(doc, five, {"rn": 100}, {"rn": 100}, 0, D("2026-10-10"))
    check("today: a rest day says so", rest["kind"] == "rest" and rest["target"] == 0)
    missed = S.missed_study_days(doc, five, D("2026-10-08"), {"2026-10-05": 20, "2026-10-06": 2},
                                 {"2026-10-05": 20, "2026-10-06": 20, "2026-10-07": 20})
    check("missed: study days under a quarter of their share, back to the last one kept",
          missed == [D("2026-10-07"), D("2026-10-06")], str(missed))
    lv = S.load_view(doc, five, {"rn": 500}, mon, [100] * 60, 8.0, 30.0)
    check("load: weeks of expected reviews, the new cards' reviews on top of what's due",
          lv["weeks"][0][1] > 100 and lv["new_a_day"] == 100 and lv["cap"] == S.cap_reviews(60, 8.0, 30.0, 100))
    check("load: a week over my time is called out", lv["over"] == [l for l, v, o in lv["weeks"] if o])
    check("plan week: 1 the week the first date opens",
          S.plan_week(doc, D("2026-10-07")) == 1 and S.plan_week(doc, D("2026-10-13")) == 2 and S.plan_week(doc, D("2026-10-01")) == 0)


def test_schedule_morning_v32():
    """3.2: the morning opens up to today's quota, first cards in the
    deck's order, never a leech; again the same day opens nothing; the
    last day opens the rest and marks the unit applied."""
    from due_crew import plan_flow as F
    store = world({"dre": "Dre", "maya": "Maya"})
    start = TODAY
    unit = {"id": "rn", "name": "Renal", "opens": _day(0), "due": _day(4), "tags": ["Step1::Renal"]}
    pid, code = store.add_plan("dre", "Step 1", "Step 1", [unit])
    maya = new_client(store, "maya", "Maya")
    every = {"days": [1] * 7, "minutes": 60}
    plan, status = maya.follow_plan(code, sched=every)
    check("follow: my schedule goes with the follow, and comes back", status == 200 and plan["sched"] == every)
    maya.remember_plan(plan)
    col = _spread_col()
    state = {pid: F.new_state(col, plan)}
    res = F.run(col, [plan], state, _day(0))
    check("morning: a fifth of the unit, the first in the deck's order (highest ids first here)",
          _open(col) == {109, 108} and res["n"] == 2, str(_open(col)))
    check("morning: again the same day opens nothing", F.run(col, [plan], state, _day(0))["n"] == 0)
    F.run(col, [plan], state, _day(2))
    check("morning: a missed morning catches up to today's quota, not more", len(_open(col)) == 6, str(_open(col)))
    F.run(col, [plan], state, _day(4))
    check("morning: the last day opens the rest, never the leech", _open(col) == set(range(101, 110)))
    check("morning: then the unit is applied, as in 3.1", "rn" in state[pid]["applied"])
    got = maya.set_schedule(pid, dict(every, start=_day(3)))
    check("my schedule: changed with one request, kept on the cached plan",
          got["start"] == _day(3) and maya.session["plans"][0]["sched"]["start"] == _day(3)
          and store.follows[(pid, "maya")]["sched"]["start"] == _day(3))
    b = maya.fetch_board([_day(0)], with_decks=True)
    check("board: my schedule rides the day's first refresh", b["plans"][0]["sched"]["start"] == _day(3))
    check("my schedule: a bad one doesn't take", maya.set_schedule(pid, {"days": [0] * 7, "minutes": 60}) is False)
    del start


def test_tree_nested_v33():
    """3.3: the tree goes up nested, each name once, so deep tags fit: the
    most useful first (question ids last), a kept tag keeps its parents,
    and it stays under the server's body limit."""
    from due_crew import plans as P
    rows = [["#Big", 9000], ["#Big::#Lectures", 3000], ["#Big::#Lectures::Cardiology", 900],
            ["#Big::#Lectures::Cardiology::02_Anatomy", 120],
            ["#Big::#Lectures::Cardiology::02_Anatomy::04_Penetrating_Cardiac_Trauma", 7],
            ["#Big::#QBank", 5000]]
    rows += [[f"#Big::#QBank::{10000 + i}", 2] for i in range(40000)]
    tree, kept, left = P.nest(rows, budget=60_000)
    flat = []

    def walk(level, pre=""):
        for x in level:
            p = f"{pre}::{x[0]}" if pre else x[0]
            flat.append(p)
            if len(x) == 3:
                walk(x[2], p)
    walk(tree)
    check("tree: a tag five levels down goes up", "#Big::#Lectures::Cardiology::02_Anatomy::04_Penetrating_Cardiac_Trauma" in flat)
    check("tree: question ids fill what's left, and some are left out", left > 0 and kept == len(flat))
    check("tree: every kept tag has its parents", all("::" not in p or p.rsplit("::", 1)[0] in set(flat) for p in flat))
    check("tree: it fits the budget", len(json.dumps(tree)) <= 60_000, str(len(json.dumps(tree))))
    store = world({"dre": "Dre"})
    dre = new_client(store, "dre", "Dre")
    check("tree: the server takes it", dre.put_tree("Step 1", rows[:6], []) and store.plan_trees[("dre", "Step 1")].get("v") == 2)


def test_hold_back_v33():
    """3.3: a deck whose cards are all active (a teacher's shared deck):
    Follow offers to hold back later dates' never-studied cards; asked,
    they're suspended in one undo step, open on their day, and stopping
    opens them again. Nothing studied, and nothing on an opened date, is held."""
    from due_crew import plans as P
    conn = sqlite3.connect(":memory:")
    fakes.make_collection(conn)
    for i in range(6):  # 100-102 unidad 1 (today), 103-105 unidad 2 (in three days); 105 already studied
        fakes.add_card(conn, 100 + i, did=10, queue=2 if i == 5 else 0, ctype=2 if i == 5 else 0,
                       tags="Unidad_1" if i < 3 else "Unidad_2", due=i)
    col = fakes.FakeCol(conn, fakes.day_cutoff_for(TODAY))
    col.decks = fakes.FakeDecks({10: "Español 1"})
    doc = {"deck": "Español 1", "units": [
        {"id": "u1", "name": "Unidad 1", "opens": _day(0), "tags": ["Unidad_1"], "decks": [], "cards": []},
        {"id": "u2", "name": "Unidad 2", "opens": _day(3), "tags": ["Unidad_2"], "decks": [], "cards": []}]}
    idx = P.DeckIndex(col, 10)
    held = P.holdable(idx, doc, _day(0))
    check("hold: only later dates' new, active cards", held == {103, 104}, str(held))
    n = P.hold_cards(col, held, "Due Crew: hold back Español")
    check("hold: suspended, one undo step", n == 2 and _open(col) == {100, 101, 102, 105}
          and col.undo_steps[-1][0] == "Due Crew: hold back Español")
    check("hold: nothing left to hold after", P.holdable(P.DeckIndex(col, 10), doc, _day(0)) == set())
    P.open_cards(col, held, "Due Crew: stop Español")
    check("hold: stopping opens them again", _open(col) == {100, 101, 102, 103, 104, 105})


def test_class_through_step_v33():
    """3.3, C1-C5: Anki's own limit shows on the card with the fix; a date
    opens days early; an Anki search is a date's contents; a renamed tag
    falls back to the author's note ids; the author's ids go up once."""
    from due_crew import plans as P
    from due_crew import plan_flow as F
    col = _spread_col()
    idx = P.DeckIndex(col, 10)
    # C3: a search, run by this collection and kept to the deck
    col.find_cards = lambda q: [101, 102, 999] if q == "tag:L14" else []
    idx = P.DeckIndex(col, 10)
    got = idx.match({"id": "s", "tags": [], "decks": [], "cards": [], "search": ["tag:L14"]}, None, "Step 1")
    check("search: its cards, only those in the plan's deck", got == {101, 102}, str(got))
    check("search: a unit's sig changes with its searches, and stays for one without",
          P.unit_sig({"tags": ["a"]}) == P.unit_sig({"tags": ["a"], "search": []})
          and P.unit_sig({"tags": ["a"]}) != P.unit_sig({"tags": ["a"], "search": ["tag:x"]}))
    # C5: a tag this copy doesn't have: the author's note ids find it
    guids = {cid: g for (g, _o), cid in idx.by_ref.items()}
    u = {"id": "r", "tags": ["Step1_v13::Renal"], "decks": [], "cards": [], "ids": [guids[103], guids[104]]}
    got = idx.match(u, None, "Step 1")
    check("renamed tag: matched by the author's note ids, and noted", got == {103, 104} and "r" in idx.fell_back, str(got))
    idx2 = P.DeckIndex(col, 10)
    check("renamed tag: a tag that matches doesn't use them", idx2.match(dict(u, tags=["Step1::Renal"]), None, "Step 1")
          == set(range(100, 110)) and not idx2.fell_back)
    snap = P.ids_snapshot(idx2, {"deck": "Step 1", "units": [{"id": "r", "tags": ["Step1::Renal"], "decks": []}]})
    check("snapshot: the note ids behind a date's tags, with the tags they came from",
          snap["r"][0] == ["Step1::Renal"] and len(snap["r"][2]) == 10)
    # C1 and C2 on the card
    week = [{"day": "2026-09-0%d" % (i + 1), "dow": "Mon", "num": i + 1, "today": i == 0, "past": False, "rest": False, "prep": False,
             "events": [], "units": [{"uid": "u1", "name": "L14", "total": 9, "seen": 3, "state": "open", "prep": False}] if i == 0 else [],
             "new": 9 if i == 0 else 0, "seen": 3 if i == 0 else 0} for i in range(7)]
    card = {"id": "p1", "title": "Block", "sub": "", "week": week, "rows": [{"name": "L14", "uid": "u1", "state": "now", "seen": [3, 9], "n": "crew 1/2"}],
            "lines": [], "change": None, "no_deck": False, "paused": False,
            "session": {"kind": "study", "target": 60, "done": 0, "due": 10, "minutes": 20, "behind": 0, "limit": 20, "fell_back": 3}}
    html = board._plan_card_html(card)
    check("limit: the card says Anki shows fewer, with Raise", "Anki shows 20 new a day" in html and "planlimit:p1" in html)
    check("limit: not when Anki shows enough", "planlimit" not in board._plan_card_html(
        dict(card, session=dict(card["session"], limit=80))))
    check("study: a day's Study builds its deck, in the day's details (3.9.6: the day's, not a set's)",
          "planstudyday:p1:2026-09-01" in html and "planstudydate" not in html and 'class="pday"' in html)
    enough = dict(card, session=dict(card["session"], limit=80))  # one note at a time: the limit comes first
    check("renamed tags: said once, with OK", "3 sets use tags your deck names differently" in board._plan_card_html(enough)
          and "planidsok:p1" not in board._plan_card_html(dict(enough, fallback_ok=True)))
    # C2: the morning looks ahead
    store = world({"dre": "Dre", "maya": "Maya"})
    unit = {"id": "rn", "name": "Renal", "opens": _day(2), "tags": ["Step1::Renal"]}
    pid, code = store.add_plan("dre", "Step 1", "Step 1", [unit])
    maya = new_client(store, "maya", "Maya")
    plan, _ = maya.follow_plan(code)
    maya.remember_plan(plan)
    col = _spread_col()
    state = {pid: F.new_state(col, plan)}
    F.run(col, [plan], state, _day(0))
    check("early: off, a date two days out stays shut", _open(col) == set())
    check("early: set with one request, kept on the plan", maya.set_early(pid, 2) and store.follows[(pid, "maya")]["early"] == 2)
    F.run(col, [dict(plan, early=2)], state, _day(0))
    check("early: two days early, it opens today", _open(col) == set(range(101, 110)))
    check("early: the plan's line says so", "· opens 2 days early ·" in F.card_view(dict(plan, early=2), state[pid], {}, _day(0))["sub"])
    # C5: the author's Anki sends the ids behind its plan's tags
    dre = new_client(store, "dre", "Dre")
    dre.fetch_board([_day(0)], with_decks=True)
    check("authored: my plans ride the day's first board", [a["id"] for a in dre.session.get("plans_authored") or []] == [pid])
    ok = dre.put_ids(pid, {"rn": [["Step1::Renal"], [], ["g1", "g2"]]})
    check("ids: kept on the date", ok and store.plans[pid]["doc"]["units"][0].get("ids") == ["g1", "g2"])
    # 3.4, D1: a pasted search's count, from my Anki, with the same request
    store.plans[pid]["doc"]["units"][0]["search"] = ["tag:L14"]
    dre.fetch_board([_day(0)], with_decks=True)
    lean = dre.session["plans_authored"][0]["doc"]
    check("authored: carries its searches", lean["units"][0]["search"] == ["tag:L14"])
    scol = _spread_col()
    scol.find_cards = lambda q: [101, 102, 103] if q == "tag:L14" else []
    counts = P.search_counts(P.DeckIndex(scol, 10), lean)
    check("search count: from my copy", counts["rn"]["tag:L14"] == 3, str(counts))
    check("search count: rides the ids request", dre.put_ids(pid, {}, counts)
          and store.plans[pid]["doc"]["units"][0].get("sn") == {"tag:L14": 3})
    # 3.6.5: pasted ids go up as the cards they are, kept while the ids hold
    store.plans[pid]["doc"]["units"][0].update(nids=[50], notes=["guid000003"])
    dre.fetch_board([_day(0)], with_decks=True)
    lean = dre.session["plans_authored"][0]["doc"]
    check("authored: carries its ids and notes", lean["units"][0].get("nids") == [50]
          and lean["units"][0].get("notes") == ["guid000003"], str(lean))
    acol = _plan_col()
    refs = P.id_refs(P.DeckIndex(acol, 10), acol, lean)
    check("refs: ride the ids request, kept on the date", dre.put_ids(pid, {}, None, refs)
          and sorted(map(tuple, store.plans[pid]["doc"]["units"][0].get("idr") or [])) == [("guid000050", 0), ("guid000050", 1)])
    stale = {"rn": [[51], [], [["guid000051", 0]]]}
    check("refs: worked out from ids the date no longer has: dropped", dre.put_ids(pid, {}, None, stale)
          and len(store.plans[pid]["doc"]["units"][0]["idr"]) == 2)
    doc = json.loads(json.dumps(store.plans[pid]["doc"]))
    doc["units"][0]["idr"] = [["forged", 0]]
    store.edit_plan(pid, doc["units"])
    check("refs: a site save can't set them, and keeps them while the ids hold",
          len(store.plans[pid]["doc"]["units"][0]["idr"]) == 2, str(store.plans[pid]["doc"]["units"][0].get("idr")))
    doc["units"][0]["nids"] = [51]
    store.edit_plan(pid, doc["units"])
    check("refs: new ids drop them until the author's Anki sends the new ones",
          "idr" not in store.plans[pid]["doc"]["units"][0])
    # 3.6.5, P1: what each date opens, counted here, kept while its picks are
    check("counts (P1): ride the ids request", dre.put_ids(pid, {}, {"rn": {"#pn": [80, 3, 1]}})
          and store.plans[pid]["doc"]["units"][0].get("pn") == [80, 3, 1])
    doc = json.loads(json.dumps(store.plans[pid]["doc"]))
    doc["units"][0]["pn"] = [1, 1, 1]
    store.edit_plan(pid, doc["units"])
    check("counts (P1): a site save keeps the stored ones while the picks hold", store.plans[pid]["doc"]["units"][0].get("pn") == [80, 3, 1])
    doc["units"][0]["tags"] = ["Step1::Cardio"]
    store.edit_plan(pid, doc["units"])
    check("counts (P1): and drops them when they change", "pn" not in store.plans[pid]["doc"]["units"][0])


def test_plans_tab_v33():
    """3.3: plans have their own place (a Plans tab; You › Plans since
    3.8.0); Decks is decks again."""
    from due_crew import board
    card = {"id": "p1", "title": "Step 1 · Dre’s plan", "sub": "week 1 of 4", "rows": [], "lines": [], "change": None,
            "no_deck": False, "paused": False}
    data = {"entries": [], "labels": [TODAY.isoformat()], "tomorrow": "", "pending": []}
    plans, empty = {"cards": [card], "offers": []}, {"cards": [], "offers": []}
    with_plan = board.render(data, {"period": "today"}, 0, plans=plans, you={"tab": "plans", "plans": plans})
    check("You › Plans: the card on it, the tab beside Insights",
          "duecrew:duetab:plans" in with_plan and "duecrew:duetab:insights" in with_plan and "Step 1 · Dre’s plan" in with_plan)
    check("the board: Crew and Squads, no Plans tab", "period:plans" not in with_plan and "period:squads" in with_plan)
    decks = board.render(data, {"period": "decks"}, 0, plans=plans, you={"tab": "insights", "plans": plans})
    check("plans: the card isn't on Crew › Decks, nor under Insights", "Step 1 · Dre’s plan" not in decks)
    none = board.render(data, {"period": "today"}, 0, plans=empty, you={"tab": "plans", "plans": empty})
    check("You › Plans: following nothing, the ways in (plans, end to end: a code or link, Make a plan, the library)",
          "planfollowcode" in none and "planlibrary" in none and "planopennew" in none and "dc-plancode" in none)
    hidden = board.render(data, {"period": "plans", "hidden_tabs": ["plans", "decks"]}, 0, plans=plans,
                          you={"tab": "plans", "plans": plans})
    check("tabs: hidden in Settings, gone, and a saved Plans period falls back to Crew's Today",
          "duetab:plans" not in hidden and "Step 1 · Dre" not in hidden and "period:decks" not in hidden
          and "period:squads" in hidden and 'dc-pill on" href="#" onclick="pycmd(\'duecrew:period:today' in hidden)
    bare = board.render(data, {"hidden_tabs": ["plans", "insights"]}, 0, plans=plans, you={"tab": "plans", "plans": plans})
    check("You: Due off, Plans and Insights hidden: no bubble at all", 'class="du' not in bare and "duetab" not in bare)
    old = board.render(data, {"hidden_tabs": ["today", "week"]}, 0)
    check("tabs: Crew can't be hidden, nor Week (Crew's picker since 3.8.0)",
          "period:today" in old and "period:week" in old)


def test_even_split_v33():
    """3.3: a date the author split evenly opens in the same slices for
    someone without a schedule: the plan's days, the deck's order; the
    server keeps `even` and the pace, and an old add-on's shapes drop them."""
    from due_crew import plan_flow as F
    from due_crew.backend import shapes
    store = world({"dre": "Dre", "maya": "Maya"})
    unit = {"id": "rn", "name": "Renal", "opens": _day(0), "due": _day(4), "tags": ["Step1::Renal"], "even": True}
    pid, code = store.add_plan("dre", "Step 1", "Step 1", [unit])
    check("even: kept on the plan", store.plans[pid]["doc"]["units"][0].get("even") is True)
    bad = None
    try:
        store._plan_doc({"deck": "x", "units": [dict(unit, due=_day(0))]})
    except fakes.Bad as e:
        bad = e
    check("even: needs a window of more than one day", bad is not None)
    maya = new_client(store, "maya", "Maya")
    plan, status = maya.follow_plan(code)
    check("even: followed without a schedule", status == 200 and not plan.get("sched") and plan["doc"]["units"][0].get("even"))
    maya.remember_plan(plan)
    col = _spread_col()
    state = {pid: F.new_state(col, plan)}
    F.run(col, [plan], state, _day(0))
    check("even: day one opens a fifth, first in the deck's order", _open(col) == {109, 108}, str(_open(col)))
    F.run(col, [plan], state, _day(2))
    check("even: a missed morning catches up to the day's slice", len(_open(col)) == 6, str(_open(col)))
    F.run(col, [plan], state, _day(4))
    check("even: the last day opens the rest, then it's applied",
          _open(col) == set(range(101, 110)) and "rn" in state[pid]["applied"])
    doc = shapes.clean_plan_doc({"deck": "x", "pace": {"mode": "end", "days": [1, 1, 1, 1, 1, 0, 0], "daily": 90, "cover": ["tag:a"]},
                                 "units": [dict(unit), dict(unit, id="b", even="yes")]})
    check("shapes: even, the plan's days and what it covers (3.6.5, for the export) come through, nothing else of the pace",
          doc["pace"] == {"days": [1, 1, 1, 1, 1, 0, 0], "cover": ["tag:a"]} and doc["units"][0]["even"] is True and "even" not in doc["units"][1])


def _knows_col():
    """Step 1 (10) with Sub (11), and Other (20). 1: mature and clean;
    2: mature but missed yesterday; 3: lapsed three times; 4: young, missed
    today; 5: mature, in Other; 6: mature, in Sub."""
    conn = sqlite3.connect(":memory:")
    fakes.make_collection(conn)
    fakes.add_card(conn, 1, did=10, ctype=2, queue=2, ivl=40)
    fakes.add_card(conn, 2, did=10, ctype=2, queue=2, ivl=40)
    fakes.add_card(conn, 3, did=10, ctype=2, queue=2, ivl=3, lapses=3)
    fakes.add_card(conn, 4, did=10, ctype=2, queue=2, ivl=2)
    fakes.add_card(conn, 5, did=20, ctype=2, queue=2, ivl=90)
    fakes.add_card(conn, 6, did=11, ctype=2, queue=2, ivl=30)
    noon = int(datetime.datetime.combine(TODAY, datetime.time(12)).timestamp() * 1000)
    fakes.add_review(conn, noon - 86400000, ease=1, cid=2)
    fakes.add_review(conn, noon, ease=1, cid=4)
    fakes.add_review(conn, noon + 60000, ease=3, time_ms=90000, rtype=0, cid=4)
    col = fakes.FakeCol(conn, fakes.day_cutoff_for(TODAY))
    col.decks = fakes.FakeDecks({10: "Step 1", 11: "Step 1::Sub", 20: "Other"})
    return col


def test_who_knows_v32():
    """3.2: the cards I know and the ones I'm stuck on (in decks I share),
    sent as changes; who knows mine comes back in the same sync; the chip;
    an ask; This helped; my log."""
    from due_crew import cards as K
    col = _knows_col()
    known, stuck = K.known_and_stuck(col, [10], fakes.day_cutoff_for(TODAY))
    check("known: mature, no miss in 30 days, in the deck I share and its subdecks",
          known == {"guid000001", "guid000006"}, str(known))
    check("stuck: lapsed twice or more, or missed today; most lapses first",
          stuck == ["guid000003", "guid000004"], str(stuck))
    check("known and stuck: nothing without a shared deck", K.known_and_stuck(col, [], 0) == (set(), []))
    labels = [_day(0)]
    store = world({"sam": "Sam", "dre": "Dre", "mo": "Mo"},
                  {"sam": ["dre", "mo"], "dre": ["sam"], "mo": ["sam"]})
    sam, dre = new_client(store, "sam", "Sam"), new_client(store, "dre", "Dre")
    ok, _g = dre.push(labels, {}, known={"guid000003", "guid000009"})
    check("knows: the first upload starts from nothing", ok and store.bodies[-1][2]["knows"]["reset"] is True
          and store.knows == {("dre", "guid000003"), ("dre", "guid000009")})
    dre.push(labels, {}, known={"guid000003", "guid000010"})
    check("knows: then only what changed", store.bodies[-1][2]["knows"] == {"add": ["guid000010"], "del": ["guid000009"]})
    dre.push(labels, {}, known={"guid000003", "guid000010"})
    check("knows: nothing changed, nothing sent", "knows" not in store.bodies[-1][2])
    many = {f"g{i:05d}" for i in range(2500)}
    other = new_client(store, "mo", "Mo")
    other.push(labels, {}, known=many)
    other.push(labels, {}, known=many)
    check("knows: at most 2,000 a sync, the rest at the next",
          len(store.bodies[-2][2]["knows"]["add"]) == 2000 and len(store.bodies[-1][2]["knows"]["add"]) == 500
          and sum(1 for u, _g in store.knows if u == "mo") == 2500)
    dre.send_cheer("sam", "\U0001F4A1", "Loop of Henle", guid="guid000003")
    sam.push(labels, {}, stuck=["guid000003", "guid000004"])
    cardsin = sam.session["cards"]
    check("stuck: who knows it and their tips come back in the same sync",
          cardsin == {"guid000003": {"knows": ["dre"], "tips": [{"from": "dre", "text": "Loop of Henle", "helped": False}]}},
          str(cardsin))
    check("helped: one request, and the session keeps it",
          sam.tip_helped("guid000003", "dre") and cardsin["guid000003"]["tips"][0]["helped"] is True
          and ("guid000003", "dre", "sam") in store.helped)
    names = {"dre": ("Dre Ng", "\U0001F419"), "mo": ("Mo", "")}
    v = K.chip_view({"knows": ["dre", "mo"], "tips": []}, [], names)
    check("chip: who knows it, and Ask", v["text"] == "\U0001F419 Dre and 1 more know this" and v["cmd"] == "knowsask")
    check("chip: a tip comes first", K.chip_view(cardsin["guid000003"], [], names)["cmd"] == "knowstip")
    both = K.chip_view(cardsin["guid000003"], [{"from": "dre", "name": "Dre Ng", "note": "same tip"},
                                               {"from": "mo", "name": "Mo", "note": "another"}], names)
    check("chip: one tip per person, the rest counted, This helped for the first",
          both["more"] == 1 and both["actcmd"] == "knowshelped:dre" and both["act"] == "\u2713 Helped", str(both))
    check("chip: nobody I can name, nothing", K.chip_view({"knows": ["zed"], "tips": []}, [], names) is None)
    asked = K.chip_view(None, [], names, asks=[("dre", 1)])
    check("chip: a crewmate's ask on a card I have, with Tip", asked["cmd"] == "knowsreply:dre:1" and asked["act"] == "Tip")
    asked_q = K.chip_view(None, [], names, asks=[("dre", 1, "why axillary?")])
    check("chip: a crewmate's ask shows their line, and a short form for a narrow bar",
          asked_q["text"] == "\U0001F419 Dre: \u201cwhy axillary?\u201d" and asked_q["short"] == "\U0001F419 Dre asked"
          and asked["text"] == "\U0001F419 Dre asked about this", str(asked_q))
    check("chip: once I've asked, it says so (Asked changes my line)",
          K.chip_view({"knows": ["dre"]}, [], names, mine=True)["act"] == "Asked" and v["act"] == "Ask"
          and v["short"] == "\U0001F419 Dre +1")
    check("chip: a tip's short form names whose tip it is",
          K.chip_view(cardsin["guid000003"], [], names)["short"] == "\U0001F4A1 Dre's tip")
    js = K.chip_js({"text": "</span><script>x</script>", "cmd": "knowsask", "act": "Ask", "accent": "#0a0"})
    check("chip: text goes in as text (3.8.22: the one markup is a Pip's own drawing)", "textContent" in js and js.count("innerHTML") == 1 and "p.innerHTML = D.pip.svg" in js)
    acked(sam, sam.fetch_board(labels))  # Dre's tip is read, and the next refresh
    sam.fetch_board(labels)               # says so: a flag on that card may go up again
    sam.session["tricky"] = [{"guid": "guid000003", "deck": "Step 1", "at": _day(0), "text": "A card", "q": "Trick?"}]
    from due_crew import together
    from due_crew.app import _state
    real_client, real_entries, real_labels = together.client, _state["entries"], _state["labels"]
    together.client = lambda: sam
    _state["labels"] = labels
    col.db.conn.execute("UPDATE notes SET flds = ? WHERE guid = 'guid000001'", ("Insulin drives {{c1::K}} in\x1fback",))
    _state["entries"] = [{"user_id": "dre", "name": "Dre Ng", "you": False}]
    sam.session.setdefault("cards", {})["guid000003"] = {"knows": ["dre"], "tips": []}
    w = together._wrap_data()
    w["tips"] = {"guid000001": [{"from": "dre", "name": "Dre Ng", "note": "x", "day": _day(0)}]}
    sys.modules["aqt"].mw.col = col
    asks = together.my_asks_view()
    sys.modules["aqt"].mw.col = None
    check("your asks (K3): my open ask says who has it down; an answered one reads its text from my copy",
          [(a["guid"], a["state"], a["who"]) for a in asks] == [("guid000003", "open", ["Dre"]), ("guid000001", "answered", ["Dre"])]
          and asks[1]["text"] == "Insulin drives [\u2026] in", str(asks))
    w.pop("tips", None)
    together.client, _state["entries"], _state["labels"] = real_client, real_entries, real_labels
    doc = sam.week_doc(labels, {})
    check("ask: rides my week as the guid and my line, never the card's text",
          doc["tricky"] == [{"guid": "guid000003", "deck": "Step 1", "at": _day(0), "q": "Trick?"}])
    sam.push(labels, {})
    board_ = dre.fetch_board(labels)
    check("ask: the crewmate reads it", board_["entries"][1]["tricky"][0]["q"] == "Trick?")
    check("ask: a card I know is known", K.i_know(col, ["guid000001", "guid000003"]) == {"guid000001"})
    log = K.log_days(col, 8)
    check("log: minutes, reviews, new cards and retention, studied days only",
          log == {_day(-1): [0, 1, 1, 0.0], _day(0): [2, 2, 1, 50.0]}, str(log))
    sam.push(labels, {}, log={f"2026-0{m}-1{d}": [1, 1, 0, None] for m in (5, 6) for d in range(9)}, log_window="full")
    check("log: the long first upload marks it sent", sam.session["log_full"] == "sam" and len(store.logs["sam"]) == 18)
    dre.session.pop("log_full", None)
    dre.push(labels, {}, log={}, log_window="full")
    check("log: a first window with nothing in it (months away) still counts as sent, so the history import can start",
          dre.session.get("log_full") == "dre")
    sam.push(labels, {}, log={"2026-06-19": [1, 1, 0, None]})
    sam.push(labels, {}, log={"2026-06-19": [1, 1, 0, None]})
    check("log: unchanged, not sent again", "log" not in store.bodies[-1][2])
    got = sam._call("GET", "/log")[1]
    check("log: mine to read", len(got["days"]) == 19)
    sam.session["recap"] = {"name": "Step 1", "n": 3, "day": _day(0)}
    sam.push(labels, {})
    check("recap: rides my week, and a crewmate sees it",
          dre.fetch_board(labels)["entries"][1]["recap"] == {"name": "Step 1", "n": 3, "day": _day(0)})


def test_older_server_v32():
    """3.2 against a Worker still on 3.1 (merged, not yet deployed): a sync
    it refuses for 3.2's parts goes again without them, and the day's
    numbers still land. Nothing 3.2 is marked sent."""
    store = world({"sam": "Sam"})
    real = store._sync

    def old_sync(me, body):
        if set(body) - {"profile", "week", "decks", "heatmap", "squads", "settings", "plans"} or "recap" in (body.get("week") or {}):
            raise fakes.Bad(400, "bad_sync")
        return real(me, body)
    store._sync = old_sync
    sam = new_client(store, "sam", "Sam")
    sam.session["recap"] = {"name": "Step 1", "n": 2, "day": _day(0)}
    ok, _g = sam.push([_day(0)], {}, known={"g1"}, stuck=["g2"], log={_day(0): [1, 1, 0, None]})
    sent = [b for m, p, b in store.bodies if p == "/sync"]
    check("older server: the sync still goes, without 3.2's parts", ok and len(sent) == 2
          and not {"knows", "stuck", "log"} & set(sent[1]) and "recap" not in sent[1]["week"])
    check("older server: nothing 3.2 is marked sent", "log_hash" not in sam.session and sam._load_known()[1] is None)


def test_knows_due_v390():
    """3.9.0 (Sam's pick, "Open calls" A): the day's first sync asks who
    knows the cards due today too, and that answer is kept for the day, so
    a card I miss for the first time shows the chip the next time it comes
    up, without a sync; only once I'm stuck on it. An older Worker gets the
    sync without it, and isn't asked again that day."""
    from due_crew import cards as K
    col = _knows_col()
    conn = col.db.conn
    conn.execute("UPDATE cards SET due = 999 WHERE id = 3")
    conn.execute("UPDATE cards SET due = 1000 WHERE id = 4")
    fakes.add_card(conn, 7, did=10, ctype=2, queue=2, ivl=5, due=1001)        # due tomorrow
    fakes.add_card(conn, 8, did=10, ctype=1, queue=1, due=1790000000)         # learning, due later today
    fakes.add_card(conn, 9, did=10, ctype=2, queue=-1, ivl=5)                 # suspended
    fakes.add_card(conn, 12, did=30, odid=10, ctype=2, queue=2, ivl=5, due=-5)  # in a filtered deck, due at home
    fakes.add_card(conn, 13, did=30, odid=10, ctype=2, queue=2, ivl=5, due=-4)  # in a filtered deck, not due at home
    conn.execute("UPDATE cards SET odue = 998 WHERE id = 12")
    conn.execute("UPDATE cards SET odue = 1005 WHERE id = 13")
    due = K.due_today(col, [10], skip=["guid000003"])
    check("due today: reviews due today or before and learning cards, in my shared deck and its subdecks, filtered ones "
          "by their home deck's day, the most overdue first; not the stuck ones, tomorrow's, suspended or another deck's",
          due == ["guid000001", "guid000002", "guid000006", "guid000012", "guid000004", "guid000008"], due)
    real_max = K.DUE_MAX
    try:
        K.DUE_MAX = 2
        check("due today: DUE_MAX at most, the most overdue kept", K.due_today(col, [10]) == ["guid000001", "guid000002"])
    finally:
        K.DUE_MAX = real_max
    check("due today: nothing without a shared deck", K.due_today(col, []) == [])

    labels = [_day(0)]
    store = world({"sam": "Sam", "dre": "Dre", "zed": "Zed"}, {"sam": ["dre"], "dre": ["sam"], "zed": ["sam"]})
    sam, dre, zed = new_client(store, "sam", "Sam"), new_client(store, "dre", "Dre"), new_client(store, "zed", "Zed")
    dre.push(labels, {}, known={"guid000001", "guid000003"})
    zed.push(labels, {}, known={"guid000002"})
    mw = sys.modules["aqt"].mw
    saved = (K.client, mw.col, K._bottom, K._review_web, K._show, dict(K._state))
    shown = []
    try:
        K.client, mw.col = (lambda: sam), col
        first = K.for_sync({"shared_decks": [10]}, light=True)
        due = [g for g in due if g != "guid000004"]  # stuck too, so it goes with those
        check("the day's first sync, light or full, carries the cards due today (not the stuck ones), and the day",
              first["due"] == due and first["due_day"] == _day(0) and first["stuck"] == ["guid000003", "guid000004"], first)
        n = len(store.log)
        ok, _g = sam.push(labels, {}, **first)
        sent = store.bodies[-1][2]
        check("one request: who knows them comes back with the stuck cards' answer",
              ok and len(store.log) == n + 1 and sent["due"] == due and sent["stuck"] == ["guid000003", "guid000004"])
        check("the answers kept apart: the stuck ones for this sync, the due ones for the day; a one-way friend's never",
              sam.session["cards"] == {"guid000003": {"knows": ["dre"], "tips": []}}
              and sam.session["cards_due"] == {"guid000001": {"knows": ["dre"], "tips": []}}
              and sam.session["due_day"] == _day(0), (sam.session.get("cards"), sam.session.get("cards_due")))
        later = K.for_sync({"shared_decks": [10]}, light=True)
        sam.push(labels, {}, **later)
        check("a later sync that day doesn't ask again, and keeps the morning's answer",
              "due" not in later and "due" not in store.bodies[-1][2] and sam.session["cards_due"] == {"guid000001": {"knows": ["dre"], "tips": []}})

        K._bottom, K._review_web, K._show = (lambda: object()), (lambda: None), (lambda v: shown.append(v))
        K._state["entries"] = [{"user_id": "dre", "name": "Dre Ng", "you": False}]
        card = types.SimpleNamespace(note=lambda: types.SimpleNamespace(guid="guid000001"), ord=0, id=1, lapses=0)
        n = len(store.log)
        K.on_answer(card)
        noon = int(datetime.datetime.combine(TODAY, datetime.time(13)).timestamp() * 1000)
        fakes.add_review(conn, noon, ease=1, cid=1)
        K.on_answer(card)
        K.on_answer(types.SimpleNamespace(note=lambda: types.SimpleNamespace(guid="guid000002"), ord=0, id=2, lapses=3))
        sam.session["due_day"] = _day(-1)
        K.on_answer(card)
        sam.session["due_day"] = _day(0)
        check("the chip: not before I miss it; the first miss today shows who knows it, with no request; "
              "a card nobody I can name knows, nothing; yesterday's answer, only the way to add a tip",
              shown[0] is None and shown[1] and shown[1]["kind"] == "knows" and shown[1]["text"].endswith("Dre knows this")
              and shown[2] is None and len(store.log) == n
              # 3.9.12 (SC: "lets loosen"): with nothing else to say, a card missed today offers a tip, lapses or none
              and shown[3]["kind"] == "hookadd" and card.lapses == 0, shown)
        lapsed = types.SimpleNamespace(note=lambda: types.SimpleNamespace(guid="guid000001"), ord=0, id=99, lapses=2)
        check("stuck now: lapsed twice, or missed today", K.stuck_now(col, lapsed, col.sched.day_cutoff)
              and K.stuck_now(col, card, col.sched.day_cutoff)
              and not K.stuck_now(col, types.SimpleNamespace(id=2, lapses=0), col.sched.day_cutoff))
    finally:
        K.client, mw.col, K._bottom, K._review_web, K._show = saved[:5]
        K._state.clear()
        K._state.update(saved[5])

    old = world({"sam": "Sam"})
    real = old._sync

    def old_sync(me, body):
        if "due" in body:
            raise fakes.Bad(400, "bad_sync")
        return real(me, body)
    old._sync = old_sync
    s2 = new_client(old, "sam", "Sam")
    ok, _g = s2.push(labels, {}, stuck=["g2"], due=["g1"], due_day=_day(0))
    sent = [b for m, p, b in old.bodies if p == "/sync"]
    check("older Worker: the sync goes again without `due`, the stuck cards still asked; not asked again today",
          ok and len(sent) == 2 and "due" not in sent[1] and sent[1]["stuck"] == ["g2"]
          and s2.session["due_day"] == _day(0) and s2.session["cards_due"] == {})


def test_knows_peek_v390():
    """3.9.0 (Sam's pick, "Open calls" C): with Pip on, who knows the card
    peeks up from the bottom of the review screen, waving, a lightbulb over
    their head: "I know this one", Ask Dre, Not now. The bar's chip and every
    other kind of card stay as they were; nothing moves with Reduce motion."""
    import shutil
    import subprocess
    from due_crew import cards as K, sev
    from due_crew.app import _state
    names = {"dre": ("Dre <b>Ng", ""), "mo": ("Mo", "")}
    pips = {"dre": {"svg": "<svg></svg>", "a": ["#1e5fb4", "#7fb2f0"]}, "mo": {"svg": "<svg></svg>", "a": ["#2e7d32", "#7cc47f"]}}
    one = K.chip_view({"knows": ["dre"], "tips": []}, [], names, pips=pips)
    two = K.chip_view({"knows": ["dre", "mo"], "tips": []}, [], names, pips=pips)
    mine = K.chip_view({"knows": ["dre"], "tips": []}, [], names, mine=True, pips=pips)
    plain = K.chip_view({"knows": ["dre"], "tips": []}, [], names)
    names4 = dict(names, jo=("Jo", ""), al=("Al", ""))
    three = K.chip_view({"knows": ["dre", "mo", "jo"], "tips": []}, [], names4, pips=dict(pips, jo=pips["mo"], al=pips["mo"]))
    four = K.chip_view({"knows": ["dre", "mo", "jo", "al"], "tips": []}, [], names4, pips=dict(pips, jo=pips["mo"], al=pips["mo"]))
    check("peek (Sam's 2D): up to three Pips, the words name them; more than three, the rest counted",
          three["peek"]["uids"] == ["dre", "mo", "jo"] and three["peek"]["head"] == "Dre, Mo and Jo know this"
          and four["peek"]["uids"] == ["dre", "mo", "jo"] and four["peek"]["head"] == "Dre, Mo, Jo and 1 more know this"
          and four["peek"]["act"] == "Ask", (three["peek"], four["peek"]))
    check("peek: one who knows it speaks for themselves; more, the words say who; asked, it says so; no Pip, the same bubble saying who (Sam: always this version)",
          one["peek"] == {"uids": ["dre"], "head": "I know this one", "act": "Ask Dre"}
          and two["peek"] == {"uids": ["dre", "mo"], "head": "Dre and Mo know this", "act": "Ask"}
          and mine["peek"]["act"] == "Asked" and plain["peek"] == {"uids": [], "head": "Dre knows this", "act": "Ask"}
          and one["text"] == "Dre knows this" and one["act"] == "Ask", (one.get("peek"), two.get("peek")))
    tip = K.chip_view({"knows": ["dre"], "tips": [{"from": "dre", "text": "think loops"}]}, [], names, pips=pips)
    check("peek: a tip peeks in with its tipper's Pip (Sam's note on \"Asks and tips\"); an ask keeps its card",
          tip["peek"] == {"uids": ["dre"], "head": "Dre: think loops", "act": "This helped"} and tip["fold"] == "Dre left a tip"
          and "peek" not in K.chip_view(None, [], names, asks=[("dre", 1, "why?")], pips=pips), tip.get("peek"))
    shown, saved = [], (K._bottom, K._review_web, K._show, K.client, dict(_state))
    store = world({"sam": "Sam"})
    sam = new_client(store, "sam", "Sam")
    sam.session["cards"] = {"guid000001": {"knows": ["dre"], "tips": []}}
    try:
        K._bottom, K._review_web, K._show, K.client = (lambda: object()), (lambda: None), (lambda v: shown.append(v)), (lambda: sam)
        _state["entries"] = [{"user_id": "dre", "name": "Dre <b>Ng", "you": False, "accent": "blue", "look": ["headphones"]}]
        K.on_answer(types.SimpleNamespace(note=lambda: types.SimpleNamespace(guid="guid000001"), ord=0, id=1, lapses=3))
    finally:
        K._bottom, K._review_web, K._show, K.client = saved[:4]
        _state.clear()
        _state.update(saved[4])
    v = shown[0]
    shown2, saved2 = [], (K._bottom, K._review_web, K._show, K.client, K.pips_by_uid, dict(_state))
    try:
        K._bottom, K._review_web, K._show, K.client = (lambda: object()), (lambda: None), (lambda v: shown2.append(v)), (lambda: sam)
        K.pips_by_uid = lambda c=None, **kw: {}  # Pip off
        _state["entries"] = [{"user_id": "dre", "name": "Dre <b>Ng", "you": False, "accent": "blue", "look": ["headphones"]}]
        K.on_answer(types.SimpleNamespace(note=lambda: types.SimpleNamespace(guid="guid000001"), ord=0, id=1, lapses=3))
    finally:
        K._bottom, K._review_web, K._show, K.client, K.pips_by_uid = saved2[:5]
        _state.clear()
        _state.update(saved2[5])
    check("peek, Pip off: the same bubble in the same place, without the Pip (Sam: \"always this version, just without the pip\")",
          shown2[0]["peek"] == {"head": "Dre knows this", "act": "Ask", "pips": []}
          and "pip" not in shown2[0], shown2[0].get("peek"))
    shown3, saved3 = [], (K._bottom, K._review_web, K._show, K.client, dict(_state))
    sam.session["cards"] = {"guid000001": {"knows": ["dre", "mo", "jo"], "tips": []}}
    try:
        K._bottom, K._review_web, K._show, K.client = (lambda: object()), (lambda: None), (lambda v: shown3.append(v)), (lambda: sam)
        _state["entries"] = [{"user_id": u, "name": n, "you": False, "accent": "blue", "look": []}
                             for u, n in (("dre", "Dre"), ("mo", "Mo"), ("jo", "Jo"))]
        K.on_answer(types.SimpleNamespace(note=lambda: types.SimpleNamespace(guid="guid000001"), ord=0, id=1, lapses=3))
    finally:
        K._bottom, K._review_web, K._show, K.client = saved3[:4]
        _state.clear()
        _state.update(saved3[4])
    sam.session["cards"] = {"guid000001": {"knows": ["dre"], "tips": []}}
    ds = [x.get("d") for x in shown3[0]["peek"]["pips"]]
    js3 = K.float_js(shown3[0])
    check("peek, three side by side: each its own place in the blink, as a room's seats (Sam: they blinked as one)",
          ds == [sev.blink(i)[1] for i in range(3)] and [x.get("b") for x in shown3[0]["peek"]["pips"]] == [sev.blink(i)[0] for i in range(3)]
          and "'--sv-b:' + (+peek.pips[i].b || 4.6) + 's;--sv-d:' + (+peek.pips[i].d || 0) + 's;'" in js3
          and "sv-blink var(--sv-b, 4.6s) var(--sv-d, 0s)" in sev.CSS, ds)
    check("peek: on the review screen, their Pip waving in their look (sev.py's own markup, the name only its label, escaped)",
          v["kind"] == "knows" and set(v["peek"]) == {"head", "act", "pips"} and len(v["peek"]["pips"]) == 1
          and "m-peek" in v["peek"]["pips"][0]["svg"] and v["peek"]["pips"][0]["a"] == list(board.accent_pair("blue"))
          and "Dre &lt;b&gt;Ng’s Pip" in v["peek"]["pips"][0]["svg"] and "<b>" not in v["peek"]["pips"][0]["svg"], v.get("peek"))
    js = K.float_js(v)
    check("peek: drawn in the corner's place, up from the bottom; the words as text; it ducks back down; still with Reduce motion",
          "var peek = D.peek || null, withPip = !!(peek && peek.pips && peek.pips.length)" in js and "if (withPip) {" in js
          and "for (var i = peek.pips.length - 1; i >= 0; i--)" in js and "bulb.innerHTML" not in js
          and "translateY(105%)" in js and "var words = el('div'" in js
          and "peek ? peek.head : D.text" in js and "prefers-reduced-motion: reduce" in js and "if (peek && !still" in js
          and "window.dcKnowsOff(!D)" in js and "off(true)" in js and "knowsbar" in js)
    check("peek: always shown, as agreed (Sam: the pill \"is not the new version we agreed on\"): no corner check, never "
          "the bar's chip; room under the card, gone with it",
          "if (peek) {" in js and js.index("if (peek) {\n    // 3.9.0") < js.index("window.addEventListener('scroll'")
          and "dc-knows-pad" in js and "if (pad) { pad.remove(); }" in js and "oldPad.remove()" in js)
    bar = K.chip_js(v)
    check("peek: the bar's chip (Pip off, or no review page) says what it said", "peek" not in bar.split("var D = ")[0]
          and "t.textContent = folded ? D.fold : D.text" in bar and "D.peek" not in bar)
    node = shutil.which("node")
    if node:
        ok = subprocess.run([node, "--check"], input=js, capture_output=True, text=True, timeout=30)
        check("peek: its script parses", ok.returncode == 0, ok.stderr[-400:])


def test_admin_notice_v321():
    """3.2.1: the admin's notice rides the board (for my version), shows on
    top of every tab escaped, with More only for an https link, and a
    dismiss that sticks by id."""
    store = world({"sam": "Sam"})
    store.notices = [{"id": 1, "text": "Everyone <b>hi</b>", "link": "https://duecrew.com/plans"},
                     {"id": 2, "text": "Please update", "below": "3.2.1", "link": "javascript:x"}]
    sam = new_client(store, "sam", "Sam")
    sam.push([_day(0)], {}, version="3.1.1")
    got = sam.fetch_board([_day(0)])["notice"]
    check("notice: an older add-on gets the one for older versions, and no unsafe link",
          got == {"id": 2, "text": "Please update", "link": ""}, str(got))
    sam.push([_day(0)], {}, version="3.2.1")
    got = sam.fetch_board([_day(0)])["notice"]
    check("notice: a current one gets the one for everyone", got["id"] == 1 and got["link"] == "https://duecrew.com/plans")
    html_ = board.notice_html(got)
    check("notice: escaped, More opens it from Python, dismiss by id",
          "&lt;b&gt;hi&lt;/b&gt;" in html_ and "noticeopen" in html_ and "noticex:1" in html_ and "duecrew.com/plans" not in html_)
    check("notice: no link, no More", "noticeopen" not in board.notice_html({"id": 3, "text": "x", "link": ""}))
    page = board.render({"entries": [], "labels": [_day(0)], "tomorrow": "", "pending": []}, {"period": "week"}, 0,
                        notice=got)
    check("notice: on top of the board", "noticex:1" in page)


def test_session_card_v32():
    """3.2: today's session on my schedule, the missed-days question, the
    recap on a new plan week, checkpoints; the board draws them escaped."""
    from due_crew import plan_flow as F
    from due_crew import plans as P
    col = _spread_col(20)
    start = TODAY - datetime.timedelta(days=3)  # opened three days ago, due in four
    unit = {"id": "rn", "name": "Renal <i>", "opens": start.isoformat(), "due": _day(3), "tags": ["Step1::Renal"],
            "check": _day(0)}
    plan = {"id": "p1", "name": "Step 1", "ownerName": "Dre", "version": 1, "followers": 3,
            "doc": {"deck": "Step 1", "units": [unit]}, "sched": {"days": [1] * 7, "minutes": 60}}
    st = F.new_state(col, plan)
    F.run(col, [plan], {"p1": st}, _day(0))
    idx = P.DeckIndex(col, 10)
    # nothing seen on the three days before: all three missed
    v = F.session_view(plan, st, idx, {}, _day(0), (8.0, 30.0), due=40)
    check("session: today's share and what's waiting", v["share"] == 3 and v["behind"] == 9 and v["kind"] == "study", str(v))
    check("session: the question, with how much spreading adds a day and how far pushing goes",
          v["ask"] and v["ask"]["waiting"] == 9 and v["ask"]["spread"] == 3 and v["ask"]["push"] == 3
          and len(v["ask"]["days"]) == 3, str(v["ask"]))
    check("session: minutes from my pace: reviews due and today's new", v["minutes"] == round((40 * 8 + 3 * 30) / 60))
    st["catch"] = {"mode": "spread", "day": _day(0)}
    v2 = F.session_view(plan, st, idx, {}, _day(0), (8.0, 30.0), due=40)
    check("session: answered, the question goes, and spreading adds a quarter a day",
          v2["ask"] is None and v2["target"] == 3 + 3)
    seen_today = {c: 0 for c in list(idx.cards)[:4]}
    for c in seen_today:
        col.db.conn.execute("UPDATE cards SET type = 2, queue = 2 WHERE id = ?", (c,))
    v3 = F.session_view(plan, dict(st, catch=None), F_idx := P.DeckIndex(col, 10), seen_today, _day(0))
    check("session: cards seen today fill what's behind first (the oldest dates), then today's",
          v3["behind"] == 5 and v3["done"] == 0, str(v3))
    idx = F_idx
    html_ = board._plan_card_html(F.card_view(plan, st, {}, _day(0), session=v2))
    check("board: 3.8.0, no Today box on the plan (Due's Today has today's cards); names escaped",
          'class="ptoday' not in html_ and "planstudy:p1" not in html_
          and "<i>" not in html_.replace("<i style", "").replace("<i class", ""), html_[:600])
    html_q = board._plan_card_html(F.card_view(plan, st, {}, _day(0), session=v))
    check("board: the missed-days question, three ways",
          "planspread:p1" in html_q and "planpush:p1" in html_q and "planleave:p1" in html_q and "Missed" in html_q)
    check("board: 3.3, no schedule to set: the plan's days are it", "plansched:p1" not in board._plan_card_html(
        F.card_view(dict(plan, sched=None), st, {}, _day(0))))
    v0 = F.session_view(dict(plan, sched=None), st, idx, seen_today, _day(0))
    check("session: 3.3, without a schedule the plan's own days give today, and no missed-days question",
          v0 is not None and v0["ask"] is None and "target" in v0)
    # the recap: on the first day of a plan week
    monday = TODAY + datetime.timedelta(days=(7 - TODAY.weekday()) % 7)
    mon_plan = dict(plan, doc=dict(plan["doc"], units=[dict(unit, opens=(monday - datetime.timedelta(days=7)).isoformat(),
                                                             due=(monday + datetime.timedelta(days=6)).isoformat())]))
    rv = F.session_view(mon_plan, st, idx, {}, monday.isoformat())
    check("recap: week 1 done, the first day of week 2", rv["recap"] and rv["recap"]["n"] == 1
          and rv["recap"]["sessions"][1] == 7, str(rv["recap"]))
    # checkpoints
    due = F.checks_due(plan["doc"], st, plan["sched"], _day(0))
    check("checkpoint: due on its morning", [k for k, _n, _us, _c in due] == ["rn"])
    rdoc = dict(plan["doc"], reviews=[{"day": _day(0), "from": "rn", "to": "rn"}])
    check("review day: 3.9.5 (Sam's FSRS rule), none built without a quiz after it: reviews ahead of their date",
          [k for k, _n, _us, _c in F.checks_due(rdoc, st, plan["sched"], _day(0))] == ["rn"])
    rdoc = dict(rdoc, events=[{"id": "q1", "day": _day(3), "name": "Quiz"}])
    rdue = F.checks_due(rdoc, st, plan["sched"], _day(0))
    check("review day: 3.3, due on its morning with its dates, named for them (a quiz three days after it)",
          [(k, n) for k, n, _us, _c in rdue][-1] == (f"r:{_day(0)}:rn:rn", "Review · Renal <i>") and rdue[-1][3] == 200)
    check("…a quiz four days after it: none", [k for k, _n, _us, _c in F.checks_due(
        dict(rdoc, events=[{"id": "q1", "day": _day(4), "name": "Quiz"}]), st, plan["sched"], _day(0))] == ["rn"])
    check("checkpoint: not built late past three mornings", F.checks_due(plan["doc"], st, plan["sched"], _day(4)) == [])
    col.db.conn.execute("UPDATE cards SET type = 2, queue = 2, lapses = id - 100 WHERE id IN (105, 106, 107)")
    idx = P.DeckIndex(col, 10)
    picked = F.check_cards(col, idx, idx.match(unit, None, "Step 1"), n=2)
    check("checkpoint: seen cards, most lapses first", picked == [107, 106], str(picked))
    st["checks"] = {"rn": {"day": _day(0), "at": 0, "cids": [107, 106]}}
    cv = F.session_view(plan, st, idx, {}, _day(0), answered={107: (3, 1), 106: (1, 2)})
    check("checkpoint: the score, first answers since it was built",
          cv["checks"] == [{"name": "Renal <i>", "n": 2, "answered": 2, "right": 1, "day": _day(0)}])
    ch = board._plan_card_html(F.card_view(plan, st, {}, _day(0), session=cv))
    check("board: the checkpoint's score, its name escaped", "1 of 2" in ch and "Renal &lt;i&gt;" in ch)
    rows_ = board.build_rows([{"user_id": "dre", "name": "Dre", "you": False, "paused": False, "last_updated": "",
                               "days": {}, "recap": {"name": "Step 1", "n": 3, "day": _day(0)}}],
                             [_day(0)], "", "today", {})
    allrows = rows_[0] + rows_[1]
    check("recap: on a crewmate's row the day it's new", allrows and allrows[0]["recap"]["n"] == 3)


def test_schedule_parity_v32():
    """3.2: the site's schedule arithmetic (Sched in site/public/app.js) gives
    the add-on's quota on every case here. Needs node; skipped without it."""
    import shutil
    import subprocess
    from due_crew import schedule as S
    node = shutil.which("node")
    if not node:
        print("SKIP schedule parity: no node")
        return
    js = open(os.path.join(REPO, "site", "public", "app.js")).read()
    head = js[js.index("const MONTHS"):js.index("const today =")]
    sched_js = js[js.index("const Sched = (() => {"):js.index("// ---- 3.2: home")]
    docs = [
        {"deck": "x", "end": "2026-12-06", "phases": {"catchup": 4, "taper": 10},
         "units": [{"id": "a", "name": "A", "opens": "2026-10-05", "due": "2026-10-25"},
                   {"id": "b", "name": "B", "opens": "2026-10-26"},
                   {"id": "c", "name": "C", "opens": "2026-11-02", "due": "2026-11-30"}]},
        {"deck": "x", "units": [{"id": "a", "name": "A", "opens": "2026-10-10", "due": "2026-10-11"},
                                {"id": "b", "name": "B", "opens": "2026-10-12", "due": "2026-10-20"}]},
        # 3.3: even splits, over the plan's own days (weekends off) without a schedule
        {"deck": "x", "pace": {"mode": "placed", "days": [1, 1, 1, 1, 1, 0, 0]}, "phases": {"catchup": 3, "taper": 0},
         "units": [{"id": "a", "name": "A", "opens": "2026-10-05", "due": "2026-10-09", "even": True},
                   {"id": "b", "name": "B", "opens": "2026-10-07"},
                   {"id": "c", "name": "C", "opens": "2026-10-10", "due": "2026-10-11", "even": True},
                   {"id": "d", "name": "D", "opens": "2026-10-12", "due": "2026-10-30", "even": True}]},
    ]
    scheds = [None, {"days": [1, 1, 1, 1, 1, 2, 0], "minutes": 60},
              {"days": [1, 0, 1, 0, 1, 0, 0], "minutes": 60, "start": "2026-10-14"}]
    cases = []
    for di, doc in enumerate(docs):
        for si, sc in enumerate(scheds):
            for u in doc["units"]:
                for k in range(0, 70, 3):
                    day = (datetime.date(2026, 10, 1) + datetime.timedelta(days=k)).isoformat()
                    cases.append([di, si, u["id"], 97, day, S.quota(doc, u, sc, 97, S.d(day))])
    prog = head + "\n" + sched_js + (
        f"const docs = {json.dumps(docs)}; const scheds = {json.dumps(scheds)}; const cases = {json.dumps(cases)};\n"
        "let bad = 0; for (const [di, si, uid, total, day, want] of cases) {"
        " const doc = docs[di]; const u = doc.units.find((x) => x.id === uid);"
        " if (Sched.quota(doc, u, scheds[si], total, day) !== want) bad++; }"
        " console.log(bad);")
    out = subprocess.run([node, "-e", prog], capture_output=True, text=True, timeout=60)
    check("schedule: the site's arithmetic is the add-on's", out.stdout.strip() == "0", out.stdout + out.stderr)


# Names of the parts after this one. The package sets them as each of those parts loads
# (an import here would load a later part before the ones between).
_LATER = ("n", "t")
n = t = None
