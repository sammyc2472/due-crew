"""The suite: 3.9.2 to 3.9.5: leeches, Reviews ahead, Pip Party."""

from due_crew import board
import datetime
import fakes
import json
import os
import re
import sqlite3
import srcs
import tempfile
import types

from .base import REPO, SUITE_FILE, TODAY, as_board, check
from .v380 import _ahead_sample, dc_mw
from .board import _day, _patched_due_crew


def test_leeches_tag_only_v392():
    """3.9.2 (Sam's pick): since Anki 23.10 a preset's leech action is Tag
    Only: Anki tags a leech and keeps showing it, none suspended. Insights'
    line counts them ("N leeches still in your reviews · See them") and the
    view lists them after the rest: a tagged card at its deck's leech count
    or past it, in a deck that tags (a tag a shared deck shipped isn't one;
    one I unsuspended by hand in a deck that suspends isn't either)."""
    import due_crew as dc
    from aqt import mw
    from aqt.deckbrowser import DeckBrowser
    from due_crew import leech_flow as LF, plan_flow as F, team_flow as TF, board
    from due_crew.app import _state
    conn = sqlite3.connect(":memory:")
    fakes.make_collection(conn)
    cut = fakes.day_cutoff_for(TODAY)
    for cid, did, ctype, queue, lapses, due, tags, nid, ord_ in (
            (301, 10, 2, 2, 8, 1003, "Bio::Cells leech", None, 0),      # Tag Only: kept, back in 3 days
            (302, 10, 3, 1, 9, 0, "Bio::Krebs leech", None, 0),         # relearning: due today
            (303, 10, 2, 2, 3, 1002, "Bio::Krebs leech", None, 0),      # the tag a shared deck shipped
            (304, 10, 2, -1, 8, 1003, "Bio::Cells leech", None, 0),     # suspended by hand: Anki stopped showing it
            (305, 10, 2, 2, 7, 1001, "Bio::Cells", None, 0),            # Tag Only never suspends: not a miss away
            (306, 11, 2, 2, 8, 1001, "Bio::Sub leech", None, 0),        # a deck that suspends, put back by hand
            (307, 10, 2, -2, 8, 1000, "Bio::Cells leech", None, 0),     # buried: back tomorrow
            (308, 10, 2, 2, 8, 1003, "", 301, 1)):                      # 301's reversed card, a leech too
        kw = {"nid": nid, "ord_": ord_} if nid else {"tags": tags}
        fakes.add_card(conn, cid, did=did, ctype=ctype, queue=queue, ivl=3, due=due, lapses=lapses, **kw)
        fakes.add_review(conn, (cut - 3 * 86400) * 1000 + cid, ease=1, cid=cid)
    col = fakes.FakeCol(conn, cut)
    col.decks = fakes.FakeDecks({10: "Bio", 11: "Bio::Sub"})
    col.decks.config_dict_for_deck_id = lambda d: {"lapse": {"leechFails": 8, "leechAction": 0 if int(d) == 11 else 1}}
    col.mod = 1
    col.get_card = lambda cid: types.SimpleNamespace(id=cid, odid=0, did=10, note=lambda: types.SimpleNamespace(
        guid=f"guid{cid:06d}", fields=["x"]))
    pc, said = {}, []
    saved = (F._pcfg, F._psave, F._after_change, mw.col, LF.tooltip, LF.app.swap, _state.get("leech_view"), _state.get("leech_open"))
    try:
        F._pcfg, F._psave, F._after_change = (lambda: pc), (lambda d: None), (lambda: None)
        mw.col = col
        LF.tooltip = lambda m, **k: said.append(m)
        LF.app.swap = lambda c=None: None
        _state["leech_view"], _state["leech_open"] = {}, {}
        deck = TF._deck_sql(col, 10)
        tags = lambda nid: conn.execute("SELECT tags FROM notes WHERE id = ?", (nid,)).fetchone()[0]  # noqa: E731
        q = lambda cid: conn.execute("SELECT queue, lapses FROM cards WHERE id = ?", (cid,)).fetchone()  # noqa: E731
        check("tag only: counts: the one suspended by hand, none a miss away, four kept in my reviews",
              LF.counts(col, deck) == (1, 0, 4), LF.counts(col, deck))
        v = LF.current(col, 10, deck)
        kept = [c["cid"] for c in v["kept"]]
        check("tag only: the view lists them, due soonest first; never the shipped tag, a deck that suspends, a near card",
              v["n_kept"] == 4 and kept[:2] == [302, 307] and set(kept) == {301, 302, 307, 308}
              and [c["cid"] for c in v["gone"]] == [304] and v["near"] == [], v)
        html = board._ins_leeches(10, v)
        check("board: the summary, its own group, due today and back tomorrow, Leave it out but no Bring back",
              "<b>4</b> still in your reviews" in html and "Leeches still in your reviews" in html
              and "due today" in html and "back tomorrow" in html
              and "insleech:10:out" not in html and "insleech:10:fresh" not in html and "Bring it back" not in html, html)
        line = board._insights_html(10, {"leeches": 0, "near": 0, "kept": 4})
        check("board: Insights' line: N leeches still in your reviews · See them (Sam's words)",
              "<b>4</b> leeches still in your reviews &middot; <a" in line and "duecrew:insleeches:10" in line, line)
        line = board._insights_html(10, {"leeches": 1, "near": 2, "kept": 1})
        check("board: with the others, said once",
              "<b>1</b> leech Anki stopped showing you &middot; <b>1</b> still in your reviews &middot; <b>2</b> one miss away" in line, line)
        dc._on_js(False, as_board("duecrew:insleech:10:fresh:301"), DeckBrowser())
        col.mod = 2
        v = LF.current(col, 10, deck)
        check("Learn it fresh on one: a new card; its note keeps the tag while the reversed card's still a leech",
              q(301) == (0, 0) and "leech" in tags(301) and 308 in [c["cid"] for c in v["kept"]] and 301 not in [c["cid"] for c in v["kept"]],
              (q(301), tags(301), v["kept"]))
        dc._on_js(False, as_board("duecrew:insleech:10:out:308"), DeckBrowser())
        col.mod = 3
        v = LF.current(col, 10, deck)
        check("Leave it out: still in my reviews, out of the list and the count, its way back at the foot",
              q(308) == (2, 8) and pc["leech_out"] == [308] and LF.counts(col, deck) == (1, 0, 2) and v["out"] == 1
              and "Put it back" in board._ins_leeches(10, v), v)
        dc._on_js(False, as_board("duecrew:insleech:10:fresh:302"), DeckBrowser())
        check("Learn it fresh on the last of a note: the tag comes off", q(302) == (0, 0) and "leech" not in tags(302), tags(302))
        # 3.9.2's QoL pass: Insights' line counts as the collection is now, and the ones left out
        col.mod = 4
        lc = LF.line_counts(col, 10, deck)
        check("QoL pass: the line's counts now, the one left out among them",
              lc == {"leeches": 1, "near": 0, "kept": 1, "leech_out": 1}, lc)
        v1 = LF.current(col, 10, deck)
        check("QoL pass: the view kept while nothing changed", LF.current(col, 10, deck) is v1)
        LF.app.client().session["cards"] = dict(LF.app.client().session.get("cards") or {})
        check("QoL pass: a sync's new tips work the open view out again (same collection)", LF.current(col, 10, deck) is not v1)
        from due_crew import team_flow as TF2, ahead_flow as AF2
        _state["leech_open"] = {10: True}
        sv2 = (TF2.cfg, TF2.save_cfg, TF2.app.swap, TF2.you_decks)
        TF2.cfg, TF2.save_cfg, TF2.app.swap, TF2.you_decks = (lambda: {}), (lambda c: None), (lambda c=None: None), (lambda: [{"did": 10}])
        try:
            TF2.go_insights(10)
        finally:
            TF2.cfg, TF2.save_cfg, TF2.app.swap, TF2.you_decks = sv2
        check("QoL pass: See ahead (or a plan's line) opens Insights itself, not a leeches view left open", not LF.is_open(10))
        keep_line, keep_shown = _state.get("ahead_line"), _state.get("board_shown")
        _state["ahead_line"], _state["board_shown"] = None, False
        AF2.check()
        check("QoL pass: no board drawn, the day's climb check waits (no forecast, no redraw)", _state["ahead_line"] is None)
        _state["ahead_line"], _state["board_shown"] = keep_line, keep_shown
    finally:
        F._pcfg, F._psave, F._after_change, mw.col, LF.tooltip, LF.app.swap, _state["leech_view"], _state["leech_open"] = saved


def test_qol_pass_v392():
    """3.9.2's last QoL pass (Sam: "last check for little things"): one card
    or one time said so; a day named with its month where the line's other
    days are; the scope's links apart from each other; a stop no longer among
    the choices keeps its own name and never compares a number with itself;
    an exam today isn't one ahead (and a stop to it ends tonight); the
    leeches' foot says only what's on the screen; a near leech alone says of
    what; an old leech's year; the plan card says where the stop is."""
    from due_crew import ahead as A, board
    check("time: the crew rows' 1h 13m; under an hour, minutes", board._hm(73) == "1h 13m" and board._hm(35) == "35 min")
    # a "week before" stop whose exam moved 45 days out: no longer a choice, its own name, no "95, not 95"
    pz = {"kind": "week", "exam": True, "from": 38}
    a = _ahead_sample(exam_in=45, off=(38, 45), pause=pz)
    h = board._ins_ahead(10, a, "Spanish")
    import re as _re
    nots = _re.findall(r"about <b>(\d+)</b> a day, not (\d+)", h)
    check("a stop no longer among the choices: its own kind's name, never Paused; never a number against itself",
          "Paused" not in h and "No new cards in Spanish" in h and all(x != y for x, y in nots), (nots, h[-1500:]))
    # an exam today: no "To your exam" over today alone; a stop to it ends tonight, not in six weeks
    v = A.view(A.existing([(0, 1)] * 40, *A.habits([])), A.GENERIC, [20.0] * 7, 0, 500, 300, [100] * 7, exam_in=0,
               off=A.stop_of({"kind": "now", "exam": True, "at": "2026-09-01"}, 0, "2026-09-01"), off_kind="now")
    on = next(w for w in v["ways"] if w["key"] == v["on"])
    check("an exam today: a stop to it is today's alone (not the six-week stop of the same kind)", tuple(on["stop"]) == (0, 0), on["stop"])
    h0 = board._ins_ahead(10, _ahead_sample(exam_in=0), "Spanish")
    check("an exam today: no 'To your exam' or 'exam day' over today alone", "To your exam" not in h0 and "exam day about" not in h0, h0[-1200:])
    # leeches
    one = {"cid": 1, "front": "x", "topic": "", "lapses": 1, "susp": False, "due": 2, "tip": [], "knows": []}
    lv = board._ins_leeches(10, {"near": [one], "n_near": 1, "gone": [], "kept": []})
    check("leeches: missed 1 time; no Bring back explained where there's none",
          "missed 1 time " in lv + " " and "missed 1 times" not in lv and "Bring back" not in lv and "Undo takes" not in lv, lv)
    g = dict(one, susp=True, lapses=8, day="2024-08-03")
    lg = board._ins_leeches(10, {"gone": [g], "n_gone": 1, "near": [], "kept": []})
    check("leeches: one to bring back says it; a leech from a year ago or more says its year",
          "Bring" not in lg and "since 3 Aug 2024" in lg, lg)
    line = board._insights_html(10, {"leeches": 0, "near": 1, "kept": 0})
    check("Insights' line: a near leech alone says of what", "<b>1</b> card one miss from a leech" in line, line)
    line = board._insights_html(10, {"leeches": 2, "near": 3})
    check("…and beside the others, as before", "<b>3</b> one miss away" in line, line)
    # the scope
    sc = board._ins_scope({"since": "2026-10-05", "since_why": "pick", "since_n": 1, "today": "2026-10-19"})
    check("scope: 1 card; Change and As it was apart; As it was says where it goes; no day after today",
          "&middot; 1 card " in sc + " " and "1 cards" not in sc and "</span> &middot; <a" in sc
          and 'title="Since your last exam, or the whole deck"' in sc and "duecrew:scopepick" in sc, sc)
    ex = board._insights_html(10, {"aim": {"day": "2026-10-23", "kind": "exam", "checked": True, "since": "", "today": "2026-10-19"}})
    check("the exam line: nothing at risk, then its scope, apart", "nothing at risk &middot; <div class=\"isc\">" in ex, ex)
    # every leech left out: the way back to them still on Insights
    lo = board._insights_html(10, {"leeches": 0, "near": 0, "kept": 0, "leech_out": 2})
    check("Insights' line: every leech left out, still a way to them", "<b>2</b> leeches you left out" in lo and "duecrew:insleeches:10" in lo, lo)
    # a stop to the week before an exam 60 days out: named from its own day; before it starts they're not off yet
    far = board._ins_ahead(10, _ahead_sample(exam_in=60, off=(53, 60), pause={"kind": "week", "exam": True, "from": 53}), "Spanish")
    check("a stop far ahead: from its own day (past the chart), and Keep them on, not Turn back on",
          "No new cards in Spanish from Sat 24 Oct till your exam, Sat 31 Oct" in far and "insaheadon" not in far, far[-900:])
    # Why: the stop on a parent deck is named as that deck
    from due_crew import why as W
    ctx = {"today": 500, "now": 1_000_000, "ahead": 1200, "deck": lambda d: {1: "Cardio"}.get(d, "?"),
           "left": lambda d: {"new": 0, "new_limit": 20, "paused": "Big"}, "rank": lambda c: 1, "size": lambda d: 1,
           "day": lambda n: f"day {n}", "clock": lambda t: "", "fsrs": True}
    said = W.reason({"id": 1, "did": 1, "odid": 0, "queue": 0, "due": 0, "lapses": 0, "leech": False}, ctx)["say"]
    check("why: a stop on the parent deck names that deck", said == "New: you stopped new cards in Big (Insights › Reviews ahead).", said)


def test_cheer_window_runs_v392():
    """3.9.2's QoL pass: the Cheer window run in node (tests/fake_dom.js, a
    small DOM whose elements are real EventTargets), not only read: a `var
    moved` overwrote the scroll/resize handler, so every close threw and
    nothing picked, sent or closed, while every string check passed. A quick
    pick and Send send one cheer and close; Cancel, Esc and the backdrop
    close; "other" asks for the computer's picker and a quick pick or a
    scroll puts it away. Needs node; skipped without it."""
    import shutil
    import subprocess
    from due_crew import board
    node = shutil.which("node")
    if not node:
        print("SKIP cheer window run: no node")
        return
    here = os.path.dirname(os.path.abspath(SUITE_FILE))
    with tempfile.TemporaryDirectory() as tmp:
        js = os.path.join(tmp, "cheer.js")
        with open(js, "w", encoding="utf-8") as f:
            f.write(board.cheer_overlay_js({"uid": "dre", "name": "Dre", "emojis": ["🎉", "🔥", "💪"], "native": True}))

        def run(steps):
            out = subprocess.run([node, os.path.join(here, "fake_dom.js"), js, steps], capture_output=True, text=True, timeout=30)
            return json.loads(out.stdout.strip().splitlines()[-1]) if out.stdout.strip() else {"errors": [out.stderr[-300:]]}
        r = run("quick:🔥,button:🎉 Send")
        check("cheer window: a quick pick and Send send one cheer, with it, and close; no errors",
              not r.get("errors") and not r.get("open") and len(r.get("sent") or []) == 1
              and r["sent"][0].startswith("duecrew:cheersend:") and "%F0%9F%94%A5" in r["sent"][0], r)
        for steps in ("button:Cancel", "esc", "backdrop"):
            r = run(steps)
            check(f"cheer window: {steps.split(':')[-1]} closes it, nothing sent, no errors",
                  not r.get("errors") and not r.get("open") and not r.get("sent"), r)
        for steps in ("button:other,quick:💪", "button:other,scroll"):
            r = run(steps)
            check(f"cheer window: other asks for the computer's picker; {steps.split(',')[1].split(':')[0]} puts it away",
                  not r.get("errors") and r.get("open") and [x.split(":")[1] for x in r.get("sent") or []] == ["emojipicker", "emojipickeroff"], r)


def test_one_overlay_v398():
    """3.9.8 (the tidy-ups, Sam's yes): the board's seven windows share one
    overlay (board.POP_JS, window.dcPop): the Cheer window, the song search,
    a sheet, Magic search's how-to, a crewmate's card, a squadmate's and the
    good-luck card. Each keeps its own card and look; the shade, its role and
    name, Esc, Tab kept inside, a click on the shade, the key back to what
    opened it, the bars' shade and the motion layer are the helper's. The
    three cards had none of the trap, the key back or a fade; the good-luck
    card had no Esc. A window's styles name it by its id or its data-pop, so
    it keeps its look while it goes (the id went first, and a closing window
    showed bare at the page's foot for its fade)."""
    import shutil
    import subprocess
    from due_crew import magic as M
    pops = {"cheer": board.cheer_overlay_js({"uid": "dre", "name": "Dre", "emojis": ["🎉"]}),
            "sheet": board.sheet_js({"id": "x", "title": "t"}),
            "magic": board.magic_howto_js(M.howto("Ctrl+Shift+F")),
            "stranger": board.stranger_card_js({"uid": "u2", "name": "Maya"}),
            "luck": board.luck_card_js("Marisa", [("Dre", "Go")]),
            "profile": board.profile_overlay_js({"name": "Dre", "uid": "dre", "cells": None})}
    dance = board.dance_js(scripts=True)
    check("one overlay: each window's script starts with it (the song search's with the floor's, once a page), and it's set up once a page",
          all(js.startswith(board.POP_JS) for js in pops.values()) and dance.startswith(board.POP_JS)
          and board.POP_JS + board.DANCE_JS in board.fridge_js() and board.POP_JS not in board.fridge_js(scripts=False)
          and not board.dance_js(scripts=False).startswith(board.POP_JS)
          and "if (window.dcPop) { return; }" in board.POP_JS and "window.dcPop.make(" in board.DANCE_JS)
    own = {k: js[len(board.POP_JS):] for k, js in pops.items()}
    check("one overlay: no window keeps its own shade, Esc, Tab trap, key back or fade; each asks dcPop for them",
          all("window.dcPop.make({ id: '" in js and "pop.show(card" in js and "downOnBack" not in js
              and "function trap(" not in js and "removeAttribute('id')" not in js and "document.addEventListener('keydown'" not in js
              and "duration: 160" not in js and "dcMotion.open" not in js and "position:fixed;inset:0" not in js
              for js in own.values()), [k for k, js in own.items() if "downOnBack" in js or "function trap(" in js])
    looks = {k: re.search(r"window\.dcPop\.make\(\{ id: '([a-z-]+)', label: .*?, z: (\d+), pad: '([^']+)' \}\)", js)
             for k, js in list(own.items()) + [("song", board.DANCE_JS)]}
    check("one overlay: each window's shade where it was: its layer and how far down the card sits (the cards, no side gap, as before)",
          {k: m.groups() for k, m in looks.items() if m} == {
              "cheer": ("dc-cheer", "80", "9vh 16px 16px"), "sheet": ("dc-sheet", "82", "12vh 16px 16px"),
              "magic": ("dc-magic", "82", "6vh 16px 16px"), "song": ("dc-song", "82", "10vh 16px 16px"),
              "stranger": ("dc-profile", "80", "16vh 0 0"), "luck": ("dc-profile", "80", "14vh 0 0"),
              "profile": ("dc-profile", "80", "14vh 0 0")}, {k: m and m.groups() for k, m in looks.items()})
    check("one overlay: a window's styles name it by id or data-pop, so its look outlasts the id (the bars' shade goes with the id)",
          board.pop_named("#dc-song .sw{} #dc-songs{} #dc-song{}", "dc-song")
          == ':is(#dc-song,[data-pop="dc-song"]) .sw{} #dc-songs{} :is(#dc-song,[data-pop="dc-song"]){}'
          and "back.setAttribute('data-pop', o.id);" in board.POP_JS and "back.removeAttribute('id');" in board.POP_JS
          and "new RegExp('#' + o.id + '(?![\\\\w-])', 'g')" in board.POP_JS
          and ':is(#dc-song,[data-pop=\\"dc-song\\"]) .sw' in board.DANCE_JS
          and all("pop.css(" in js for k, js in own.items()))
    check("one overlay: Esc is caught first and stays in the window; Tab wraps in it; the key goes back to what opened it; "
          "the motion layer brings it in and takes it out, else a 160 ms fade (none with Reduce motion)",
          "document.addEventListener('keydown', esc, true);" in board.POP_JS and "e.stopPropagation();" in board.POP_JS
          and "document.removeEventListener('keydown', esc, true);" in board.POP_JS
          and "if (was && was.isConnected && was.focus)" in board.POP_JS
          and "if (moved || still() || !back.animate) { back.remove(); return; }" in board.POP_JS
          and "duration: 160" in board.POP_JS)
    node = shutil.which("node")
    if not node:
        print("SKIP the windows in node: no node")
        return
    here = os.path.dirname(os.path.abspath(SUITE_FILE))
    with tempfile.TemporaryDirectory() as tmp:
        def run(name, steps):
            js = os.path.join(tmp, name + ".js")
            with open(js, "w", encoding="utf-8") as f:
                f.write(pops[name])
            env = dict(os.environ, POP_ID="dc-profile")
            out = subprocess.run([node, os.path.join(here, "fake_dom.js"), js, steps], capture_output=True, text=True,
                                 timeout=30, env=env)
            return json.loads(out.stdout.strip().splitlines()[-1]) if out.stdout.strip() else {"errors": [out.stderr[-300:]]}
        got = {(n, st): run(n, st) for n in ("luck", "profile", "stranger") for st in ("", "esc", "backdrop", "button:Close")}
        check("one overlay, run: each card opens, and Esc (the good-luck card's too, which had none), the shade and Close each close it; "
              "nothing sent, no errors",
              all(not r.get("errors") for r in got.values())
              and all(r.get("open") == (st == "") and not r.get("sent") for (n, st), r in got.items()),
              {k: v for k, v in got.items() if v.get("errors") or v.get("open") != (k[1] == "") or v.get("sent")})
        r = run("profile", "button:\U0001F389 Send a cheer")
        check("one overlay, run: a card's own button closes it and sends its one command",
              not r.get("errors") and not r.get("open") and r.get("sent") == ["duecrew:cheerpick:dre"], r)

def test_exam_dates_audit_v392():
    """3.9.2's audit: the next exam set on the last one's own day keeps it as
    the last (the scope starts after it); an upcoming exam moved keeps the
    scope I picked; a new exam starts from the default."""
    from due_crew import settings_model as SM
    today = datetime.date(2026, 10, 19)
    got = SM.change(["setexam", "2026-12-01"], {"exam_date": "2026-10-19", "exam_since": "all"}, today)
    check("set on the exam's own day: kept as the last, the scope back to the default",
          got == {"exam_date": "2026-12-01", "exam_last": "2026-10-19", "exam_since": ""}, got)
    got = SM.change(["setexam", "2026-11-03"], {"exam_date": "2026-11-02", "exam_since": "all"}, today)
    check("an upcoming exam moved a day: the scope I picked stays", got == {"exam_date": "2026-11-03"}, got)
    got = SM.change(["setexam", "2026-11-03"], {"exam_date": "", "exam_since": "2026-09-01"}, today)
    check("a new exam where there was none: the default", got == {"exam_date": "2026-11-03", "exam_since": ""}, got)
    got = SM.change(["setexam", "off"], {"exam_date": "2026-11-02", "exam_since": "all"}, today)
    check("no exam: the scope goes with it", got == {"exam_date": "", "exam_since": ""}, got)


def test_scope_map_and_words_392():
    """3.9.2 (Sam's picks C1-A, C2-A, F1-A): my exam covers the cards I
    started since my last exam (in the last 10 weeks; an exam is kept once
    it's passed) or since a day I pick, else the whole deck, said in its
    box with Change; the map by when I started them, a week a tile named
    by what it was, opening into its topics; and the words the students
    tripped on: never passed / lapsed, the map's % and cards and bar, the
    target beside right, Study N early."""
    from due_crew import team as T, team_flow as TF, board
    from due_crew.settings_model import change
    from due_crew import account
    # ---- 3.9.2, from a real deck: right % apart for the cards started these two weeks ----
    ans = [(c, 1, 3 if c % 3 else 1) for c in range(60)] + [(c, 1, 3 if c % 10 else 1) for c in range(100, 160)]
    rd = T.right_days(ans, set(range(60)))
    check("right: the cards started these two weeks apart from the rest", rd["young"] == [40, 60] and rd["older"] == [54, 60]
          and rd["now"] == [94, 120] and T.right_split(rd) == (67, 90, 60), rd)
    check("right: not split when close, or too few new ones, or no young set",
          T.right_split(T.right_days([(c, 1, 3 if c % 10 else 1) for c in range(120)], set(range(60)))) is None
          and T.right_split(T.right_days(ans, set(range(30)))) is None and T.right_split(T.right_days(ans)) is None)
    hd = board._insights_html(10, {"right": rd, "target": 90})
    check("right: the header says both, under the right %",
          "67% on the cards you started these 2 weeks (60 reviews) &middot; 90% on the rest" in hd, hd)
    # ---- 3.9.2, from a real deck: a week's name in the map's own topics, never the deck a card came from ----
    tg = {c: ["Big::#Source_Decks::Deck_A::Bugs", "Big::#Systems::03_Microbiology::02_Clinical_Bacteriology"] for c in range(30)}
    tg.update({c: ["Big::#Source_Decks::Deck_B", "Big::#Systems::01_Biochem"] for c in range(30, 90)})
    tg.update({c: ["Big::#Source_Decks::Deck_C::Mixed", "Big::#Systems::" + ("04_Cardio", "05_Renal", "06_GI", "07_Neuro")[c % 4]
                   + "::Topic_" + str(c)] for c in range(90, 130)})
    tg.update({c: ["Big::#Source_Decks::Deck_D::Only_here"] for c in range(130, 150)})
    tg.update({c: ["Cardio::Drugs::Beta_blockers"] for c in range(150, 160)})
    wd = {"": 160}
    for c in tg:
        for t in tg[c]:
            parts = t.split("::")
            for i in range(1, len(parts) + 1):
                k = "::".join(parts[:i]).lower()
                wd[k] = wd.get(k, 0) + 1
    check("week names: a tag's way is its family up to its first resource mark; no mark, plain tags",
          T.way_of("Big::#Systems::03_Microbiology") == "big::#systems" and T.way_of("Cardio::Drugs") == T.TAGS_WAY
          and T.way_of("Big::^Systems::Cardio") == "big::^systems")
    check("week names: in the map's own topics ('Microbiology · Clinical Bacteriology'), never the deck a card came from "
          "(Sam: 'isn't helpful ... should be organized by topic')",
          T.batch_name(list(range(30)), tg, wd, "big::#systems") == "Microbiology · Clinical Bacteriology"
          and "Bugs" not in T.batch_name(list(range(30)), tg, wd, "big::#systems"))
    check("week names: no one topic holds a third: its two biggest, by name; a week the map's topics don't reach: no name",
          T.batch_name(list(range(90, 130)), tg, wd, "big::#systems") == "Cardio, Renal"
          and T.batch_name(list(range(130, 150)), tg, wd, "big::#systems") == "")
    check("week names: plain tags are the map's way too", T.batch_name(list(range(150, 160)), tg, wd, T.TAGS_WAY) == "Drugs · Beta blockers",
          T.batch_name(list(range(150, 160)), tg, wd, T.TAGS_WAY))
    # ---- 3.9.2, from a real deck: the map's shade is the last time a card came due ----
    conn = sqlite3.connect(":memory:")
    fakes.make_collection(conn)
    cut = fakes.day_cutoff_for(TODAY)
    at = lambda d: (cut - d * 86400 - 3600) * 1000  # noqa: E731
    for cid, ctype, queue in ((1, 2, 2), (2, 2, 2), (3, 1, 1), (4, 2, -1)):
        fakes.add_card(conn, cid, did=10, ctype=ctype, queue=queue)
    fakes.add_review(conn, at(5), ease=3, cid=1, rtype=1)
    fakes.add_review(conn, at(9), ease=1, cid=2, rtype=1)
    fakes.add_review(conn, at(9) + 60000, ease=3, cid=2, rtype=2)  # its relearning step: not a review
    fakes.add_review(conn, at(8), ease=3, cid=2, rtype=1)          # back the next day and passed
    fakes.add_review(conn, at(1), ease=3, cid=3, rtype=0)          # never due yet: too soon to say
    fakes.add_review(conn, at(5), ease=3, cid=4, rtype=1)          # suspended: not in play
    fakes.add_card(conn, 5, did=10, ctype=2, queue=2)
    fakes.add_review(conn, at(60), ease=1, cid=5, rtype=1)         # not due these 4 weeks: its last review
    know, by = TF._know(fakes.FakeCol(conn, cut), "1,2,3,4,5", cut)
    check("map: each card's share of its reviews right these 4 weeks; a miss counts though it passed the next day; "
          "a relearning step isn't a review; not due in them, its last review; never due yet, too soon to say "
          "(3.9.2's audit: its last answer was the pass that graduated it); FSRS or not",
          know == {1: 1.0, 2: 0.5, 3: None, 5: 0.0} and by == "right", (know, by))
    soon = T.started_tiles({c: 1 for c in range(30)}, {c: ["Big::#Systems::Cardio"] for c in range(30)},
                           {c: None for c in range(30)}, set(range(30)), "2026-10-18")
    sm = board._ins_map(10, soon + [{"key": "x", "name": "Older", "n": 5, "started": 5, "know": 80}], "right")
    check("map: a week of cards started, none reviewed yet: started, and too soon to say (not 100%, not new)",
          soon[0]["started"] == 30 and soon[0]["know"] is None and "too soon<small>" in sm and "none reviewed yet" in sm, sm)
    check("map: the key names too soon when a tile shows it, new when one does", "<i class=\"sw sn\"></i>too soon" in sm
          and "<i class=\"sw sn\"></i>new, too soon" in board._ins_map(10, soon + [{"key": "n", "name": "Not started", "n": 9,
                                                                                     "started": 0, "know": None}], "right"), sm)
    one = board._ins_map(10, [{"key": "a", "name": "Cardio", "n": 30, "started": 30, "know": 90},
                              {"key": "b", "name": "Renal", "n": 20, "started": 20, "know": 80}], "right",
                         ways=[{"key": "s", "name": "Systems", "on": True},
                               {"key": "~start", "name": "When you started them", "on": False, "one": True}])
    check("map by start, picked, but all I've started is from one week: it says so (Sam's pick), by topic",
          "Everything you&rsquo;ve started is from one week, so this is by topic." in one, one)
    # ---- the scope, pure ----
    check("scope: since the day after my last exam, in the last 10 weeks; older, or none, the whole deck",
          T.scope("2026-11-02", "2026-09-04", "", "2026-10-18") == ("2026-09-05", "last")
          and T.scope("2026-10-01", "", "", "2026-10-18") == ("2026-10-02", "last")
          and T.scope("2026-11-02", "2026-07-01", "", "2026-10-18") == (None, "")
          and T.scope("2026-11-02", "", "", "2026-10-18") == (None, ""))
    check("scope: a day I picked, or the whole deck I picked, over the default",
          T.scope("2026-11-02", "2026-09-04", "2026-08-20", "2026-10-18") == ("2026-08-20", "set")
          and T.scope("2026-11-02", "2026-09-04", "all", "2026-10-18") == (None, ""))
    day = datetime.date(2026, 10, 18)
    check("setexam: a new date keeps the one that's passed (exam_last), and a picked scope starts over",
          change(["setexam", "2026-11-20"], {"exam_date": "2026-10-02", "exam_since": "2026-09-01"}, today=day)
          == {"exam_date": "2026-11-20", "exam_last": "2026-10-02", "exam_since": ""}
          and change(["setexam", "off"], {"exam_date": "2026-10-02"}, today=day) == {"exam_date": "", "exam_last": "2026-10-02"}
          and change(["setexam", "2026-11-20"], {"exam_date": "2026-11-02"}, today=day) == {"exam_date": "2026-11-20"}
          and change(["setexam", "2026-11-20"], {"exam_date": "2026-09-02", "exam_last": "2026-10-01"}, today=day)
          == {"exam_date": "2026-11-20"})
    check("setscope: a day (not ahead), the whole deck, back to the default; anything else nothing",
          change(["setscope", "2026-09-07"], {}, today=day) == {"exam_since": "2026-09-07"}
          and change(["setscope", "all"], {}, today=day) == {"exam_since": "all"}
          and change(["setscope", "auto"], {"exam_since": "all"}, today=day) == {"exam_since": ""}
          and change(["setscope", "2026-12-01"], {}, today=day) is None and change(["setscope", "soon"], {}, today=day) is None)
    check("scope: both keys follow the account", "exam_last" in account.ACCOUNT_KEYS and "exam_since" in account.ACCOUNT_KEYS)
    aim = {"day": "2026-11-02", "name": "Your exam", "in": 15, "kind": "exam", "since": "2026-09-05", "since_why": "last",
           "since_n": 1240, "since_pick": ""}
    html = board._ins_scope(aim)
    check("board: the box says what it covers, with Change (a day) and Whole deck",
          "Since Sat 5 Sep, the day after your last exam &middot; 1,240 cards" in html and "duecrew:scopepick" in html
          and 'type="date"' not in html and "duecrew:setscope:all" in html, html)
    check("board: a picked day goes back with As it was; the whole deck I picked, with Since your last exam",
          "duecrew:setscope:auto" in board._ins_scope(dict(aim, since_why="set"))
          and "Whole deck" in board._ins_scope(dict(aim, since="", since_why="", since_pick="all"))
          and "Since your last exam" in board._ins_scope(dict(aim, since="", since_why="", since_pick="all")))
    none = board._insights_html(10, {"aim": dict(aim, day="2026-11-02", checked=True), "hero": []})
    unseen = board._insights_html(10, {"aim": dict(aim, day="2026-11-02"), "hero": []})
    check("board: my exam with nothing at risk still says what it covers, with its Change; "
          "without FSRS (nothing looked at) it never says nothing's at risk (3.9.2's audit)",
          "Your exam, Mon 2 Nov: nothing at risk" in none and "duecrew:setscope:" in none
          and "nothing at risk" not in unseen and "Your exam, Mon 2 Nov " in unseen and "duecrew:setscope:" in unseen, none)
    # ---- the map by when I started them, pure ----
    tags = {c: ["Big::#Systems::" + ("Cardio::Pharm" if c < 40 else "Renal::Physio")] for c in range(100)}
    first = {c: (1 if c < 40 else 9 if c < 80 else 120) for c in range(100)}
    know = {c: (0.95 if c < 40 else 0.6) for c in range(100)}
    tiles = T.started_tiles(first, tags, know, set(range(110)), "2026-10-18")
    check("map by start: a week a tile, named by its dates and what it was; the last 8 weeks I started cards in, "
          "however long ago (3.9.2's audit); not started one",
          [(t["key"], t["name"], t["n"], t["know"]) for t in tiles]
          == [("2026-10-12", "This week · Cardio · Pharm", 40, 95), ("2026-10-05", "Last week · Renal · Physio", 40, 60),
              ("2026-06-15", "15–21 Jun · Renal · Physio", 20, 60), ("new", "Not started", 10, None)]
          and tiles[0]["find"] == {"cids": list(range(40))}, [(t["key"], t["name"], t["n"], t["know"]) for t in tiles])
    many = T.started_tiles({c: 7 * (c // 10) for c in range(100)}, tags, know, set(range(100)), "2026-10-18")
    check("map by start: more than 8 weeks with cards: 8 tiles, the rest before the oldest of them",
          len(many) == 9 and many[-1]["key"] == "before" and many[-1]["name"].startswith("Before 24 Aug") and many[-1]["n"] == 20,
          [(t["key"], t["name"], t["n"]) for t in many])
    mixed = {c: ["Big::#Systems::" + ("Cardio::Pharm" if c % 2 else "Renal::Physio"), "Big::#Source_Decks::Deck_A::X" + str(c % 2)]
             for c in range(200)}
    wk = T.started_tiles({c: (1 if c < 100 else 30) for c in range(200)}, mixed, {c: 0.9 for c in range(200)},
                         set(range(200)), "2026-10-18", "big::#systems")[0]
    kids = T.expand(wk, {c: 0.9 for c in range(200)})
    check("map by start: a week opens into the map's own topics, and each finds that week's cards alone "
          "(3.9.2's audit: a topic in it opened every card of the deck with its tag)",
          sorted(k["name"] for k in kids) == ["Cardio", "Renal"] and all(set(k["find"]["cids"]) <= set(range(100)) for k in kids)
          and sum(len(k["find"]["cids"]) for k in kids) == 100, [(k["name"], k["find"]) for k in kids])
    first2 = {c: 20 + (c % 3) for c in range(60)}
    longw = {c: ["Big::#Notes::Reproductive_Notes::Reproductive_Physiology_and_Embryology_Lecture_Notes"] if c < 40
             else ["Big::#Notes::Biochemistry_Notes::Molecular"] for c in range(80)}
    lt = T.started_tiles({c: 30 if c < 40 else 2 for c in range(80)}, longw, {c: 0.9 for c in range(80)}, set(range(80)),
                         "2026-10-18")[-1]["name"]
    check("map by start: a long name ends on a whole word, with an ellipsis (Sam's 'Reproductive Physiolo')",
          lt.endswith("…") and len(lt) <= T.NAME_MAX and not lt[:-1].endswith((" ", ",", "·"))
          and T.clip("Before 24 Aug · Biochemistry Notes · Molecular, Cellular, and Biochemical Basis") ==
          "Before 24 Aug · Biochemistry Notes · Molecular, Cellular…" and T.clip("short") == "short", lt)
    check("map by start: a week two weeks back by its days", T.started_tiles(first2, {}, {}, set(range(60)), "2026-10-18")[0]["name"]
          == "28 Sep–4 Oct", T.started_tiles(first2, {}, {}, set(range(60)), "2026-10-18")[0]["name"])
    mixed = {c: ["Big::Cardio::Pharm" if c % 2 else "Big::Renal::Physio"] for c in range(40)}
    check("map by start: what most share names it; a tag on nearly every card I started says nothing",
          T.batch_name(list(range(40)), mixed, {"": 40, "big": 40, "big::cardio": 20, "big::cardio::pharm": 20,
                                                "big::renal": 20, "big::renal::physio": 20}) in ("Cardio · Pharm", "Renal · Physio")
          and T.batch_name([1, 2], {1: ["leech"], 2: ["marked"]}, {"": 2}) == "")
    wk = {c: ["Spanish::" + ("Subjunctive::Present" if c < 20 else "Subjunctive::Past")] for c in range(40)}
    t0 = T.started_tiles({c: 1 for c in range(40)}, wk, {c: 0.9 for c in range(40)}, set(range(40)), "2026-10-18")[0]
    kids = T.expand(t0, {c: 0.9 for c in range(40)})
    check("map by start: a week opens into its topics", sorted(k["name"] for k in kids) == ["Past", "Present"], kids)
    # ---- the words ----
    rows = board._insights_html(10, {"rows": [{"name": "Renal", "src": "", "of": 30, "stuck": 8, "forgot": 3, "cids": [1]}]})
    check("words: never passed and lapsed, as Anki's Stats say them", "never passed" in rows and "lapsed" in rows
          and "not right yet" not in rows and "forgot<" not in rows, rows)
    mh = board._ins_map(10, [{"key": "a", "name": "Cardio", "n": 190, "know": 66, "started": 120, "find": {"tags": ["C"]}},
                             {"key": "b", "name": "Renal", "n": 80, "know": None, "started": 0, "find": {"tags": ["R"]}}], "fsrs")
    check("words: a tile's % and its cards; the key says what the % is and what the bar is",
          "<b>66%<small> &middot; 190</small></b>" in mh and "<b>new<small> &middot; 80</small></b>" in mh
          and "% you&rsquo;d recall now: " in mh and '<i class="sw bar"></i>started' in mh, mh)
    whole = board._ins_map(10, [{"key": "a", "name": "Week one", "n": 50, "know": 80, "started": 50, "find": {"tags": ["A"]}},
                                {"key": "b", "name": "Week two", "n": 30, "know": 70, "started": 30, "find": {"tags": ["B"]}}], "right")
    check("words: the key names the bar only when a tile shows one (by when I started them, none does)",
          'class="tmb"' not in whole and "sw bar" not in whole and "started" not in whole.split('class="ikey"')[1].split("</span></div>")[0], whole)
    head = board._insights_html(10, {"target": 90, "right": {"now": [86, 100], "before": [0, 0], "days": []},
                                     "aim": {"day": "2026-10-20", "in": 2}, "hero": [1, 2, 3]})
    check("words: right beside what Anki aims for; no date ahead, no Study (3.9.5, Sam's FSRS rule)",
          "right &middot; Anki aims for 90%" in head and "Study 3 early" not in head and "insbrowse:10:h" in head, head)
    dh = board._insights_html(10, {"target": 90, "right": {"now": [86, 100], "before": [0, 0], "days": []},
                                   "aim": {"day": "2026-10-20", "in": 2, "name": "Your exam", "kind": "exam"}, "hero": [1, 2, 3]})
    check("words: before my exam, Study 3 early (they aren't due yet)", "Study 3 early" in dh, dh)
    # ---- the glue: the exam box counts only what I started since my last exam ----
    from aqt import mw
    from due_crew import plan_flow as F
    from due_crew.app import _state
    conn = sqlite3.connect(":memory:")
    fakes.make_collection(conn)
    cut = fakes.day_cutoff_for(TODAY)
    at = lambda days: (cut - days * 86400 - 3600) * 1000  # noqa: E731
    for i in range(40):  # 20 started 30 days ago (before my last exam, 20 days ago), 20 started 10 days ago
        cid = 900 + i
        fakes.add_card(conn, cid, did=10, ctype=2, queue=2, ivl=3, tags="Step1::Renal", due=1030)
        conn.execute("UPDATE cards SET data = ? WHERE id = ?", (json.dumps({"s": 1}), cid))
        fakes.add_review(conn, at(30 if i < 20 else 10), ease=3, cid=cid, rtype=0)
        fakes.add_review(conn, at(2), ease=3, cid=cid)
    col = fakes.FakeCol(conn, cut)
    col.decks = fakes.FakeDecks({10: "Step 1"})
    col.conf["fsrs"] = True
    conf = {"exam_date": _day(5), "exam_last": _day(-20)}
    saved = (F._today, F._pcfg, F._psave, mw.col, TF.cfg, _state.get("insights"))
    try:
        F._today = lambda: _day(0)
        F._pcfg = lambda: {}
        F._psave = lambda d: None
        mw.col = col
        TF.cfg = lambda: conf
        _state["insights"] = {}
        v = TF.insights(10, None, _day(5))
        check("glue: since my last exam, the box counts the 20 I started after it, and says so",
              sorted(v.get("hero") or []) == list(range(920, 940)) and v["aim"]["since"] == _day(-19)
              and v["aim"]["since_why"] == "last" and v["aim"]["since_n"] == 20, (v.get("aim"), v.get("hero")))
        conf["exam_since"] = "all"
        v = TF.insights(10, None, _day(5))
        check("glue: the whole deck, picked: all 40, and the cache knew the scope changed",
              len(v.get("hero") or []) == 40 and v["aim"]["since"] == "" and v["aim"]["since_pick"] == "all", v.get("aim"))
        conf["ins_map_by"] = {"10": T.START_WAY}
        _state["insights"] = {}
        v = TF.insights(10, None, _day(5))
        check("glue: the map by when I started them, picked: a week a tile, its cards to Browse",
              [(t["n"], t["know"] is not None) for t in v.get("map") or []] == [(20, True), (20, True)]
              and next(w for w in v["map_ways"] if w["key"] == T.START_WAY)["on"]
              and TF._find_cids(col, 10, v["map"][0]["find"]) == list(range(920, 940)), v.get("map"))
        conn.execute("UPDATE revlog SET id = id + 20 * 86400000 + 997 WHERE cid < 920 AND type = 0")  # all started one week
        _state["insights"] = {}
        v = TF.insights(10, None, _day(5))
        sw = next(w for w in v["map_ways"] if w["key"] == T.START_WAY)
        check("glue: picked, but everything started in one week: not on, and it says so (Sam's pick)",
              sw.get("one") is True and not sw["on"], sw)
    finally:
        F._today, F._pcfg, F._psave, mw.col, TF.cfg, _state["insights"] = saved


def test_offline_stays_off_stderr_v392():
    """3.9.2 (Sam's report): a settings pull that got no answer printed its
    traceback, and Anki shows anything on stderr in its error window. A
    background job's TransportError is one line on stdout; a real bug still
    prints its traceback. And no handler that prints a traceback around a
    request lets a TransportError reach it."""
    import ast, contextlib, io, pathlib, threading
    from due_crew import app as appmod
    from due_crew.backend.shapes import TransportError

    def run(job):
        got, done, err, out = [], threading.Event(), io.StringIO(), io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            appmod._bg(job, lambda r: (got.append(r), done.set()))
            done.wait(5)
        return got, err.getvalue(), out.getvalue()

    def offline():
        raise TransportError("GET /settings failed")

    def bug():
        raise ValueError("a real bug")

    got, err, out = run(offline)
    check("offline: nothing on stderr (no error window), one line on stdout, None delivered",
          got == [None] and err == "" and "GET /settings failed" in out and "Traceback" not in out, (got, err, out))
    got, err, out = run(bug)
    check("a real bug still prints its traceback, and delivers None",
          got == [None] and "Traceback" in err and "a real bug" in err, (got, err))
    got, err, _ = run(lambda: 7)
    check("a job that works delivers its result", got == [7] and err == "", (got, err))

    root = pathlib.Path(SUITE_FILE).resolve().parent.parent / "due_crew"
    cls = next(n for n in ast.parse((root / "backend" / "api.py").read_text()).body
               if isinstance(n, ast.ClassDef) and n.name == "ApiClient")
    uses = {f.name: {c.func.attr for c in ast.walk(f) if isinstance(c, ast.Call)
                     and isinstance(c.func, ast.Attribute) and isinstance(c.func.value, ast.Name)
                     and c.func.value.id == "self"} for f in cls.body if isinstance(f, ast.FunctionDef)}
    net, grew = {"_call"}, True
    while grew:
        more = {m for m, cs in uses.items() if cs & net} - net
        net |= more
        grew = bool(more)
    loud = []
    for f in sorted(root.rglob("*.py")):
        if "backend" in f.parts:
            continue
        for t in ast.walk(ast.parse(f.read_text())):
            if not isinstance(t, ast.Try):
                continue
            asks = any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr in net - {"_call"}
                       for b in t.body for c in ast.walk(b))
            seen_te = False
            for h in t.handlers:
                names = {getattr(e, "id", "") for e in (h.type.elts if isinstance(h.type, ast.Tuple) else [h.type])} if h.type else {"Exception"}
                seen_te = seen_te or "TransportError" in names
                # 3.9.9: oops() prints it as print_exc() did (and counts it for Sam)
                prints = any(isinstance(c, ast.Call) and (getattr(c.func, "attr", "") == "print_exc"
                                                          or getattr(c.func, "id", "") == "oops") for c in ast.walk(h))
                if asks and prints and "Exception" in names and not seen_te:
                    loud.append(f"{f.name}:{h.lineno}")
    check("every handler that prints a traceback around a request catches TransportError first",
          not loud and len(net) > 20, loud)


def test_one_leech_is_it_v393():
    """3.9.3 (Sam, of Due's line "Recovered 1 leech as new cards · See them":
    "for a singular recovered card, should be 'see it'"): one card is "it",
    wherever the board names one leech: Due's morning note, the toast when
    Recover leeches is switched on, and Insights' leech line."""
    from due_crew import due_flow as F
    saved = F._day_state
    try:
        F._day_state = lambda: ({}, {"recovered": [5], "dismissed": []})
        one = F.notes()
        F._day_state = lambda: ({}, {"recovered": [5, 6], "dismissed": []})
        two = F.notes()
    finally:
        F._day_state = saved
    check("one leech: Due's note says a new card, See it; two say new cards, See them",
          one == [{"key": "recovered", "text": "Recovered 1 leech as a new card", "go": "See it"}]
          and two == [{"key": "recovered", "text": "Recovered 2 leeches as new cards", "go": "See them"}], (one, two))
    lines = [board._insights_html(10, v) for v in ({"leeches": 1}, {"kept": 1}, {"near": 1}, {"leeches": 1, "near": 1},
                                                    {"leech_out": 1}, {"leech_out": 2})]
    check("one leech: Insights' line says See it for one card, See them for more",
          [">See it</a>" in x for x in lines] == [True, True, True, False, True, False]
          and [">See them</a>" in x for x in lines] == [False, False, False, True, False, True], lines)


def test_todays_bars_v393():
    """3.9.3 (Sam: "a similar progress bar for reviews as appears with the new
    cards... perhaps all of them should fill as cards are pushed to at least
    tomorrow"; the Today's Bars mock, his yes to its picks): one rule for
    every bar on Today, through for today (answered, next due tomorrow or
    later), with what's answered and back later today in a lighter part;
    Reviews gets its bar; a plan's date ticks when its bar is full; a New
    cards row without a plan's date, Other new cards beside one."""
    import time
    from due_crew import due as D, due_flow as F, plans as P
    T = TODAY.isoformat()
    cut = fakes.day_cutoff_for(TODAY)
    conn = fakes.make_collection(sqlite3.connect(":memory:"))
    col = fakes.FakeCol(conn, cut)
    day = col.sched.today
    start = (cut - 86400) * 1000
    # (cid, did, type, queue, due, first answer today: (type, lastIvl) or None)
    cards = [(1, 1, 2, 2, day + 3, (1, 10)),        # a review, through
             (2, 1, 3, 1, cut - 3600, (1, 20)),     # a review missed, relearning back later today
             (3, 1, 2, 2, day, None),               # a review still due (Anki's tree counts it)
             (4, 1, 3, 3, day, None),               # relearning from yesterday, due today, not answered
             (5, 1, 1, 1, cut - 100, (0, 0)),       # a new card started today, in its steps
             (6, 2, 2, 2, day + 1, (0, 0)),         # a new card started today, graduated
             (7, 1, 2, 2, day + 1, (0, -600))]      # learning carried in from yesterday, through
    for cid, did, ctype, queue, due, first in cards:
        conn.execute("INSERT INTO notes (id, guid, tags) VALUES (?, ?, '')", (cid, f"g{cid}"))
        conn.execute("INSERT INTO cards (id, nid, did, type, queue, due) VALUES (?, ?, ?, ?, ?, ?)",
                     (cid, cid, did, ctype, queue, due))
        if first:
            conn.execute("INSERT INTO revlog (id, ease, time, type, cid, lastIvl) VALUES (?, 3, 5000, ?, ?, ?)",
                         (start + cid * 1000, first[0], cid, first[1]))
            conn.execute("INSERT INTO revlog (id, ease, time, type, cid, lastIvl) VALUES (?, 3, 5000, 1, ?, 5)",
                         (start + 900000 + cid, cid))  # a later answer: only the first one says what it was
    conn.execute("INSERT INTO revlog (id, ease, time, type, cid) VALUES (?, 3, 5000, 1, 99)", (start + 5,))  # a deleted card
    conn.execute("INSERT INTO revlog (id, ease, time, type, cid) VALUES (?, 3, 5000, 1, 1)", (start - 86400000,))  # yesterday
    node = lambda i, name, rv, new: types.SimpleNamespace(deck_id=i, name=name, review_count=rv, learn_count=0,  # noqa: E731
                                                          new_count=new, children=[])
    tree = types.SimpleNamespace(children=[node(1, "Big Step 1", 1, 5), node(2, "<Pharm>", 0, 3)])
    now = cut - 7200
    got = F.bars(col, tree, now, 1200, {5})
    check("bars: Reviews are the cards due from before today, carried learning too: 2 through, 1 back later, 2 still due",
          (got["whole"], got["through"], got["later"], got["left"], got["back"]) == (5, 2, 1, 2, 1)
          and got["at"] == f"{time.localtime(cut - 3600).tm_hour}:{time.localtime(cut - 3600).tm_min:02d}", got)
    check("bars: New cards are the ones started today and what Anki still gives, a line a top deck",
          got["new"] == {"through": 1, "later": 1, "whole": 10,
                         "decks": [["Big Step 1", 0, 6, 1], ["<Pharm>", 1, 4, 0]]}, got["new"])
    check("bars: Other new cards leave out today's plan dates' cards, and hold no limit's",
          got["other"] == {"through": 1, "later": 0, "whole": 1, "decks": [["<Pharm>", 1, 1, 0]]}, got["other"])
    check("bars: the box's one timer, at the first learning card back later today",
          got["first"] is True and got["_first"] == cut - 3600)
    # the deck index: what of a date is back later today
    conn.execute("UPDATE cards SET did = 10")
    conn.execute("INSERT INTO cards (id, nid, did, type, queue, due) VALUES (8, 8, 10, 1, 3, ?)", (day + 1,))
    conn.execute("INSERT INTO cards (id, nid, did, type, queue, due) VALUES (9, 9, 10, 1, 1, ?)", (cut + 60,))
    conn.execute("INSERT INTO notes (id, guid, tags) VALUES (8, 'g8', ''), (9, 'g9', '')")
    col.decks = fakes.FakeDecks({10: "Step 1"})
    idx = P.DeckIndex(col, 10)
    check("bars: the index knows the cards in their steps and due again today (not tomorrow's)",
          idx.again == {2, 4, 5}, sorted(idx.again))

    # the pure rows
    rv = dict(got, due=6, done=12)
    v = D.view(T, [], [], {}, reviews=rv)
    kinds = [(r["kind"], r.get("other")) for r in v["rows"]]
    check("bars: no plan's date today: Reviews, then New cards", kinds == [("reviews", None), ("new", False)], kinds)
    h = board._due_html(v)
    rh = h[h.index("<b>Reviews</b>"):h.index("<b>New cards</b>")]
    check("bars: Reviews says 2 / 5, its line the ones back and the ones due now, its bar two-tone",
          "2 / 5" in rh and "1 back at " in rh and "2 still due" in rh and 'class="wbar two"' in rh
          and 'style="width:40%"' in rh and 'class="lt" style="width:20%"' in rh, rh)
    check("bars: the bar is the row's own, after its end, the row's whole width",
          re.search(r'<span class="end">.*?</span></span><span class="wbar two"', rh) is not None
          and "#due-crew .du-r > .wbar { grid-column: 2 / -1; }" in board.DUE_CSS, rh)
    nh = h[h.index("<b>New cards</b>"):]
    check("bars: New cards, 1 / 10, a line a deck (names escaped)",
          "1 / 10" in nh and "<b>Big Step 1</b>" in nh and "0 / 6" in nh and "<b>&lt;Pharm&gt;</b>" in nh
          and "1 / 4" in nh and "<Pharm>" not in nh, nh[:900])
    check("bars: the day counts both rows, and Study today has the new cards to walk",
          v["total_n"] == 2 and v["done_n"] == 0 and v["study"])
    morning = D.view(T, [], [], {}, reviews={"due": 140, "done": 0, "whole": 140, "through": 0, "later": 0, "left": 140,
                                            "back": 0, "at": "", "new": {"whole": 20, "through": 0, "later": 0,
                                                                          "decks": [["Big Step 1", 0, 20, 0]]}})
    mh = board._due_html(morning)
    check("bars: the morning says 140 due and 20 new, bars empty, no line yet; one deck named under its row",
          "140 due" in mh and "20 new" in mh and "still due" not in mh and mh.count('class="wbar two"') == 2
          and "<small>Big Step 1</small>" in mh and "du-sub" not in mh[mh.index("New cards"):], mh)
    done = D.view(T, [], [], {}, reviews={"due": 0, "done": 160, "whole": 140, "through": 140, "later": 0, "left": 0,
                                         "back": 0, "at": "", "new": {"whole": 20, "through": 20, "later": 0, "decks": []}})
    dh = board._due_html(done)
    check("bars: through for today, both ticked, all done, the bars put away, the day done",
          dh.count("all done") == 2 and "wbar two" not in dh and done["done_n"] == done["total_n"] == 2
          and D.done_for_today(done), dh)
    last = D.view(T, [], [], {}, reviews={"due": 0, "done": 140, "whole": 140, "through": 134, "later": 6, "left": 0,
                                         "back": 6, "at": "14:30"})
    check("bars: everything answered but six back later: not done, 134 / 140, 6 back at 14:30",
          not last["rows"][0]["done"] and "134 / 140" in board._due_html(last) and "6 back at 14:30" in board._due_html(last)
          and not D.done_for_today(last))
    old = D.view(T, [], [], {}, reviews={"due": 12, "done": 3})
    check("bars: a count from before 3.9.3 is a number, no bar, as before",
          "12 due" in board._due_html(old) and "wbar two" not in board._due_html(old))
    none = D.view(T, [], [], {}, reviews={"due": 0, "done": 0, "whole": 0, "through": 0, "later": 0, "left": 0,
                                         "back": 0, "at": "", "new": {"whole": 0}})
    check("bars: no reviews and no new cards today: neither row is drawn, nothing counted",
          [r["kind"] for r in none["rows"]] == ["reviews"] and none["total_n"] == 0
          and "Reviews" not in board._due_html(none) and "New cards" not in board._due_html(none))

    # a plan's date: the same rule, and the tick with it
    x = {"pid": "p", "uid": "u", "plan": "MS2", "name": "Heart failure", "opens": T, "seen": 18, "later": 6, "total": 40,
         "parts": [["Videos", 14, 28, 5], ["Book", 4, 12, 1]]}
    pv = D.view(T, [x], [], {}, reviews=rv)
    row = next(r for r in pv["rows"] if r["kind"] == "plan")
    ph = board._due_html(pv)
    check("bars: a plan's date says 12 / 40, its parts 9 / 28 and 3 / 12, its bar 12 solid and 6 light",
          row["n"] == "12 / 40" and "9 / 28" in ph and "3 / 12" in ph
          and 'style="width:30%"></i><i class="lt" style="width:15%"' in ph, ph[:3000])
    check("bars: on a plan's day, Other new cards (the ones none of its dates holds), not on a plan",
          [r["kind"] for r in pv["rows"]] == ["reviews", "new", "plan"] and pv["rows"][1]["other"]
          and "<b>Other new cards</b>" in ph and "not on a plan" in ph and "<b>New cards</b>" not in ph)
    seen_all = dict(x, seen=40, later=2, parts=[])
    r2 = D._date_row(seen_all, set(), T)
    check("bars: every card seen but two back later today: 38 / 40, not ticked yet",
          r2["n"] == "38 / 40" and not r2["done"] and r2["part"])
    r3 = D._date_row(dict(seen_all, later=0), set(), T)
    check("bars: through for today: all done, ticked", r3["n"] == "all done" and r3["done"])
    behind, _mine = D.behind([dict(seen_all, opens="2026-01-01")], [], {}, T)
    check("bars: a date from before today, all seen, some in their steps today, isn't behind (seen still counts there)",
          behind == [], behind)
    js = open(os.path.join(REPO, "due_crew", "motion.js"), encoding="utf-8").read()
    check("bars: a bar's light part moves on its own key", '(el.classList.contains("lt") ? "lt:" : "")' in js)


def test_today_v395():
    """3.9.5 (Five mocks, reviewed; Sam: "give it a shot building all of
    it"): today's misses under a done Reviews row, where they were (each
    part opens Browse: a line, not a deck, Sam's FSRS rule). Next up and
    the deck-ran-out line went before it shipped (Sam's picks on the 3.9.5
    review page): the suggestion is new leeches, as before."""
    from due_crew import due as D, due_flow as F
    from due_crew.app import _state
    import due_crew as dc
    from aqt.deckbrowser import DeckBrowser
    T = TODAY.isoformat()
    # ---- pure: misses ----
    check("today: misses said: none, one, 23",
          D.misses_text({"n": 0}) is None and D.misses_text({"n": 1}) == "1 missed"
          and D.misses_text({"n": 23, "reviews": 214}) == "214 reviews, 23 missed")
    # ---- my pace and today's misses, from a log ----
    cut = fakes.day_cutoff_for(TODAY)
    conn = fakes.make_collection(sqlite3.connect(":memory:"))
    col = fakes.FakeCol(conn, cut)
    col.decks = fakes.FakeDecks({10: "Big Step 1"})
    start = (cut - 86400) * 1000
    saved = (F._today, F.mw.col, F._pf)
    F._today = lambda: T
    try:
        for i in range(5):
            fakes.add_review(conn, start + 1000 + i, ease=1, cid=3000 + i, last_ivl=9, ivl=1)  # five reviews missed today
            fakes.add_review(conn, start + 2000 + i, ease=1, rtype=2, cid=3000 + i)            # and again in relearning
        for i in range(10):
            fakes.add_review(conn, start + 5000 + i, cid=4000 + i, last_ivl=9, ivl=20)           # ten right
        fakes.add_review(conn, start + 9000, ease=1, rtype=0, cid=5000)                         # a new card's Again: not a miss
        box = {}
        F._pf = lambda: types.SimpleNamespace(_pcfg=lambda: box)
        m = F._misses(col)
        check("today: misses are reviews answered Again today, a card once, first missed first; reviews counted by card",
              m["n"] == 5 and m["cids"] == [3000, 3001, 3002, 3003, 3004] and m["reviews"] == 15 and "of" not in m, m)
        check("today: no map for the deck: the misses aren't split", (m["topics"], m["elsewhere"]) == ([], 0), m)
        check("today (the second review): a redraw with no new answer is the one worked out", F._misses(col) is m)
        fakes.add_review(conn, start + 9500, ease=1, cid=4000, last_ivl=20, ivl=1)
        m2 = F._misses(col)
        check("…a new miss, worked out again", m2 is not m and m2["n"] == 6 and m2["cids"][-1] == 4000, m2)
        from due_crew import team_flow as TF
        saved_map = (TF.deck_map, F._today_deck)
        TF.deck_map = lambda did: ([{"name": "Renal <x>", "_cids": [3000, 3001, 3002]}, {"name": "Cardio", "_cids": [3003, 9]},
                                    {"name": "Endo", "_cids": [8]}], set())
        F._today_deck = lambda col: 10
        _state["due_miss_topics"] = _state["due_misses"] = None
        try:
            m3 = F._misses(col)
            check("today: misses by the map's parts for today's deck, the most first, the rest elsewhere",
                  m3["topics"] == [("Renal <x>", [3000, 3001, 3002]), ("Cardio", [3003])] and m3["elsewhere"] == 2, m3)
            hm = board._due_html(dict(D.view(T, [], [], {}, reviews={"due": 0, "done": 9, "whole": 9, "through": 9, "later": 0,
                                                                     "left": 0, "back": 0, "at": ""}), misses=m3, mins=0))
            check("today board: each part a link to Browse just those, escaped; the rest elsewhere",
                  "Renal &lt;x&gt; 3</a>" in hm and "duecrew:duego:miss0" in hm and "Cardio 1</a>" in hm
                  and "duecrew:duego:miss1" in hm and "2 elsewhere" in hm and "<x>" not in hm, hm[hm.index("du-rc"):][:900])
        finally:
            TF.deck_map, F._today_deck = saved_map
            _state["due_miss_topics"] = _state["due_misses"] = None
    finally:
        F._today, F.mw.col, F._pf = saved
    # ---- the board ----
    rv = {"due": 0, "done": 214, "whole": 214, "through": 214, "later": 0, "left": 0, "back": 0, "at": ""}
    v = D.view(T, [], [], {}, reviews=rv)
    v.update(misses={"n": 23, "reviews": 214, "cids": []})
    mid = D.view(T, [], [], {}, reviews=dict(rv, through=100, left=114, done=100))
    check("today board: 3.9.5 (Sam: \"i don't love telling someone how much time they have left\"): no minutes left",
          "du-min" not in board._due_html(dict(mid, mins=68)) and " left</span>" not in board._due_html(mid))
    h = board._due_html(dict(v, done=False))
    rh = h[h.index("<b>Reviews</b>"):]
    check("today board: under a done Reviews row, today's misses; no Study (Sam's FSRS rule: a line, not a deck)",
          "214 reviews, <b>23 missed</b>" in rh and "again" not in rh[:rh.index("du-rc") + 400] and "Super decks" not in h, rh[:1200])
    check("today board: not a word while the reviews aren't done",
          "du-rc" not in board._due_html(dict(mid, misses=None)))
    # ---- Sam's picks: no Next up, no deck-ran-out line ----
    check("today board (Sam's picks): no Next up and no deck-ran-out line",
          "Next up" not in board._due_html(v) and "du-clr" not in board._due_html(v) and "cleared" not in board._due_html(v))
    from due_crew import team_flow as TF
    conf = {"due_suggest": True, "exam_date": ""}
    saved = (F.cfg, F._today, F._day_state, TF.insights, F.mw.col)
    F.cfg = lambda: conf
    F._today = lambda: T
    day = {"day": T, "dismissed": [], "recovered": []}
    F._day_state = lambda: ({}, day)
    asked = []
    TF.insights = lambda *a, **k: asked.append(a) or {}
    leeches = {"n": 4}
    F.mw.col = types.SimpleNamespace(mod=None, db=types.SimpleNamespace(scalar=lambda *a: leeches["n"]),
                                     sched=types.SimpleNamespace(day_cutoff=cut))
    try:
        _state["due_suggest"] = None
        s1 = F.suggestions(conf, T)
        check("suggestions: new leeches, as before 3.9.5; Insights isn't asked for a next thing",
              [x["key"] for x in s1] == ["leeches"] and s1[0]["text"] == "4 new leeches this week" and not asked, s1)
        day["dismissed"] = ["leeches"]
        _state["due_suggest"] = None
        check("suggestions: Not today puts it away", F.suggestions(conf, T) == [])
        check("glue: no Next up and no cleared watch left in Due's glue",
              not hasattr(F, "_next_up") and not hasattr(F, "_watch_ours") and not hasattr(F, "cleared"))
    finally:
        F.cfg, F._today, F._day_state, TF.insights, F.mw.col = saved
        _state["due_suggest"] = None
    # ---- a part of today's misses: its cards in Browse ----
    shown = []
    pf = types.SimpleNamespace(_browse=lambda cids, q=None, empty="": shown.append(list(cids)))
    saved = (F.mw.col, F._pf, F._today)
    F.mw.col, F._pf, F._today = types.SimpleNamespace(), (lambda: pf), (lambda: T)
    F._misses, saved_m = (lambda col: {"n": 3, "cids": [600, 601, 603], "topics": [("Renal", [601, 603]), ("Cardio", [600])]}), F._misses
    try:
        dc._on_js(False, as_board("duecrew:duego:miss0"), DeckBrowser())
        dc._on_js(False, as_board("duecrew:duego:miss7"), DeckBrowser())  # a part that isn't there: Browse says none
        check("misses: a part's link opens just its misses in Browse, through the board's own handler",
              shown == [[601, 603], []], shown)
    finally:
        F.mw.col, F._pf, F._today = saved
        F._misses = saved_m


def test_click_test_v395():
    """3.9.5, Sam's first click-test: Insights' exam date and its scope are
    picked in a Qt calendar (the page's own date picker went down with a
    redraw: "removing an exam date and then clicking add exam date makes
    anki quit"); an exam date comes off the day after it ("when an exam
    date passes let's remove it")."""
    import due_crew as dc
    from due_crew import due_flow as F, plan_flow as PF, ui as UI
    from aqt.deckbrowser import DeckBrowser
    T = TODAY.isoformat()
    conf = {"exam_date": "", "exam_since": "", "exam_last": ""}
    picked, asked = {"day": "2026-09-20"}, []

    def pick(parent, title, day, lo=None, hi=None):
        asked.append((title, day, lo, hi))
        return picked["day"]
    saved = (dc._swap, dc.cfg, dc.save_cfg, UI.pick_date, PF._today, dc.ahead_flow.exam_moved)
    dc._swap, dc.cfg, dc.save_cfg = (lambda c, focus=None: None), (lambda: conf), (lambda c, **k: None)
    UI.pick_date, PF._today, dc.ahead_flow.exam_moved = pick, (lambda: T), (lambda: None)
    try:
        send = lambda m: dc._on_js(False, as_board("duecrew:" + m), DeckBrowser())  # noqa: E731
        send("exampick")
        check("exam pick: a Qt calendar from today, a week out to start; the day picked is my exam date",
              conf["exam_date"] == "2026-09-20" and asked[-1][0] == "Exam date"
              and asked[-1][1] == TODAY + datetime.timedelta(days=7) and asked[-1][2] == TODAY, (conf, asked))
        send("exampick")
        check("exam pick: again, it starts on the day set", asked[-1][1] == datetime.date(2026, 9, 20), asked[-1])
        picked["day"] = None
        send("exampick")
        check("exam pick: Cancel changes nothing", conf["exam_date"] == "2026-09-20")
        picked["day"] = "2026-08-20"
        send("scopepick")
        check("scope pick: the day the exam's cards are counted from, no later than today",
              conf["exam_since"] == "2026-08-20" and asked[-1][0] == "Count the cards started since" and asked[-1][3] == TODAY,
              (conf, asked[-1]))
    finally:
        dc._swap, dc.cfg, dc.save_cfg, UI.pick_date, PF._today, dc.ahead_flow.exam_moved = saved
    # an exam date the day after it
    saved = (F._today, F.save_cfg)
    F.save_cfg = lambda c, **k: None
    try:
        F._today = lambda: "2026-09-21"
        c = {"exam_date": "2026-09-20", "exam_last": "2026-05-01", "exam_since": "2026-08-20"}
        gone = F.exam_gone(c)
        check("exam gone: the day after, it comes off as × takes it: kept as my last exam, its scope with it",
              gone and c["exam_date"] == "" and c["exam_last"] == "2026-09-20" and c["exam_since"] == "", c)
        F._today = lambda: "2026-09-20"
        c2 = {"exam_date": "2026-09-20"}
        check("exam gone: not on the exam's own day, and nothing without a date",
              not F.exam_gone(c2) and c2["exam_date"] == "2026-09-20" and not F.exam_gone({"exam_date": ""}))
    finally:
        F._today, F.save_cfg = saved
    # the second review: a failure taking it off never costs the day its morning
    saved = (F.exam_gone, F.morning, F.cfg)
    ran = []
    F.cfg = lambda: {}
    F.morning = lambda c: ran.append("morning")

    def broken(c):
        raise RuntimeError("bad exam_last")
    F.exam_gone = broken
    try:
        F.after_refresh()
        check("exam gone: an error in it, and the morning still runs", ran == ["morning"], ran)
    finally:
        F.exam_gone, F.morning, F.cfg = saved


def test_super_decks_gone_v395():
    """3.9.5: Super decks, built and click-tested, went before it shipped
    (Sam: "i think let's get rid of super decks for now"). What stays:
    a plan topic's Study and Browse on Today, and a deck made for a date
    goes the morning after it."""
    from due_crew import plan_flow as PF, settings_model, due_flow as F
    check("gone: no Super decks tab, nothing to hide in Settings, no tab Due's handler knows",
          [k for k, _l in board.YOU_MORE] == ["plans", "insights"] and "supers" not in settings_model.HIDEABLE
          and "supers" not in F.YOU_TABS and not os.path.exists(os.path.join(REPO, "due_crew", "superdecks.py")))
    pc = {"sd": {"71": {"kind": "quiz"}}}
    day = (TODAY + datetime.timedelta(days=2)).isoformat()
    saved = (PF._pcfg, PF._psave)
    PF._pcfg, PF._psave = (lambda: pc), (lambda c: None)
    try:
        PF._note_built(71, day)
        PF._note_built(72)
        check("noted: a deck for a date keeps its day (the morning after, it's emptied); one without, none; "
              "3.9.5's Super decks' notes go", PF.untils() == {71: day} and pc["built"] == [71, 72] and "sd" not in pc, pc)
        PF._note_built(71)
        check("noted: built again without a date, its day goes", PF.untils() == {}, pc)
    finally:
        PF._pcfg, PF._psave = saved


GAMES_SIM_JS = r"""
const out = [];
for (const id of Object.keys(GAMES)) {  // the menu's three and the three off it (their code kept)
  const g = GAMES[id];
  for (let N = 1; N <= g.max; N++) {
    const seats = Array.from({ length: N }, (_, i) => ({ peer: "p" + i, n: "P" + i }));
    const pres = seats.map(() => ({}));
    let step = 1, A = seats.map(() => null);
    const c = () => ({ N, seats, name: (i) => (seats[i] ? seats[i].n : "?"), A, pres: (i) => pres[i] || {}, here: () => true, bots: true });
    let S, phases = [], err = "", leaked = [];
    try {
      S = g.start(c());
      if (id === "links") S = Links.play(S);  // the TV's Start, past the teams
      if (id === "trivia" && S.ph === "topic") S = Trivia.block(S.ts[0][0]);  // the TV's pick of a subject
      phases.push(S.ph);
      for (let k = 0; k < 3; k++) {
        const x = g.pub(S, c()), sec = g.secrets ? g.secrets(S, c()) : [];
        const said = JSON.stringify(x);
        if (id === "trivia" && S.qs[S.k] && said.includes(JSON.stringify(S.qs[S.k].q))) leaked.push("question");
        if (id === "rounds" && S.hands.some((hd) => hd.some((w) => said.includes(JSON.stringify(w)) && !(x.flip || []).includes(w) && w !== x.ans))) leaked.push("hand");
        if (id === "links" && S.ph !== "end" && x.key) leaked.push("key");
        if (id === "imposter" && (said.includes(JSON.stringify(S.b)) && S.ph !== "last" && S.ph !== "end")) leaked.push("twin");
        A = seats.map((_, i) => {
          const p = g.bot(x, i, { s: step, seat: i, seats, N, me: Object.assign({ gm: id }, sec[i] || {}), pres: (j) => pres[j] || {} });
          if (!p) return null;
          if (p.d) pres[i] = { d: Object.assign({ s: step }, p.d) };
          return p.a ? Object.assign({ s: step }, p.a) : null;
        });
        const S2 = g.collect(S, A, c()) || (g.force && g.force(S, c()));
        if (!S2) break;
        S = S2; step++; A = seats.map(() => null);
        phases.push(S.ph);
      }
      if (id === "rounds") phases.push(Rounds.next(S, c()).ph);
    } catch (e) { err = String(e && e.stack || e).slice(0, 300); }
    out.push({ id, N, min: g.min, need: need(g), phases, err, leaked });
  }
}
console.log(JSON.stringify({ out, needs: NEEDS }));
"""

GAME_ROWS = [  # a collection's cards in gamenight's rows: (cid, ord, cloze, fields, tags)
    (n + 1, 0, True, [t, ""], [tag]) for n, (tag, t) in enumerate(
        [("Step1::Renal::Pharm", "Loop diuretics block the {{c1::Na-K-2Cl}} cotransporter"),
         ("Step1::Renal::Pharm", "Thiazides block the {{c1::Na-Cl}} cotransporter in the DCT"),
         ("Step1::Renal::Pharm", "{{c1::Spironolactone}} blocks aldosterone at the collecting duct"),
         ("Step1::Renal::Pharm", "{{c1::Acetazolamide}} inhibits carbonic anhydrase"),
         ("Step1::Renal::Nephritic", "RBC casts point to {{c1::nephritic syndrome}}"),
         ("Step1::Renal::Nephritic", "Post-strep GN shows {{c1::low C3}}"),
         ("Step1::Renal::Nephritic", "Anti-GBM disease: {{c1::Goodpasture}}"),
         ("Step1::Renal::Nephrotic", "Nephrotic range: more than {{c1::3.5 g}} protein a day"),
         ("Step1::Renal::Nephrotic", "Most common in kids: {{c1::minimal change disease}}"),
         ("Step1::Renal::Nephrotic", "Apple-green birefringence: {{c1::amyloidosis}}"),
         ("Step1::Cardio::Pharm", "{{c1::Digoxin}} inhibits the Na-K ATPase"),
         ("Step1::Cardio::Pharm", "{{c1::Amiodarone}} can cause pulmonary fibrosis"),
         ("Step1::Cardio::Pharm", "{{c1::Hydralazine}} can cause drug-induced lupus"),
         ("Step1::Cardio::Arrhythmia", "Delta wave: {{c1::WPW}}"),
         ("Step1::Cardio::Arrhythmia", "Torsades: give {{c1::magnesium}}"),
         ("Step1::Cardio::Arrhythmia", "Irregularly irregular: {{c1::atrial fibrillation}}"),
         ("Step1::Pulm::Asthma", "Curschmann spirals: {{c1::asthma}}"),
         ("Step1::Pulm::Asthma", "Rescue inhaler: {{c1::albuterol}}"),
         ("Step1::Pulm::COPD", "Pink puffer: {{c1::emphysema}}"),
         ("Step1::Pulm::COPD", "Panacinar: {{c1::alpha-1 antitrypsin}}"),
         ("Step1::Neuro::Pharm", "Absence seizures: {{c1::ethosuximide}}"),
         ("Step1::Neuro::Pharm", "Gingival hyperplasia: {{c1::phenytoin}}"),
         ("Step1::Neuro::Stroke", "Leg weakness: {{c1::ACA}} stroke"),
         ("Step1::Neuro::Stroke", "Lacunar strokes: {{c1::hypertension}}")])]


def test_game_night_from_your_cards_v395():
    """3.9.5, game night from Anki: tonight's cards become the six games'
    pack (gamenight.py, pure). A cloze asks its own number with one blank;
    a basic card its front; the wrong answers come from the tag nearest it;
    topic names read as people say them; Imposter's twins are the likeliest
    mix-ups first; a custom scope is one Anki search."""
    from due_crew import gamenight as G
    check("game night: a pick is one Anki search term, its name read as itself; nothing else is one",
          G.term("deck:Step 1") == '"deck:Step 1"' and G.term("tag:Step1::Heart_failure") == '"tag:Step1::Heart\\_failure"'
          and G.term('deck:a"b') == '"deck:a\\"b"' and G.term("note:x") == "" and G.term("tag:") == "")
    check("game night: a cloze asks its own number, the others shown; two pieces of one number aren't asked",
          G.cloze("{{c1::Loop}} diuretics block {{c2::Na-K-2Cl}}", 2) == ("Loop diuretics block ____", "Na-K-2Cl", "Loop diuretics block Na-K-2Cl")
          and G.cloze("{{c1::a}} and {{c1::b}}", 1) is None and G.cloze("{{c1::a::hint}}", 1)[1] == "a")
    it = G.item((9, 1, False, ["Front <b>side</b>", "Back&nbsp;side<br>[sound:x.mp3]"], ["leech", "Deck::Renal::Loop_diuretics::Extra"]))
    check("game night: a reversed card asks its back; fields as plain text; leech and plan tags aren't where it's from, nor Extra",
          it and it["q"] == "Back side" and it["a"] == "Front side" and it["tag"] == "Deck::Renal::Loop_diuretics" and it["where"] == "Loop diuretics", it)
    check("game night: no question from a long answer, a picture alone, or an answer the question gives away",
          G.item((1, 0, False, ["Q", "x" * 41], [])) is None and G.item((1, 0, False, ["<img src=a.png>", "A"], [])) is None
          and G.item((1, 0, False, ["Same", "same"], [])) is None)
    check("game night: a tag reads as people say it; two that end alike take their parent's name",
          G.topic_name("01_Growth_Adaptations") == "Growth Adaptations" and G.topic_name("#Path_Book") == "Path Book" and G.topic_name("12") == ""
          and G.names(["S::Renal::Pharm", "S::Neuro::Pharm", "S::Renal::Nephritic"]) == {"S::Renal::Pharm": "Renal pharm", "S::Neuro::Pharm": "Neuro pharm", "S::Renal::Nephritic": "Nephritic"})
    pack = G.build(GAME_ROWS, "Block 2, this week", seed=3)
    have, thin = G.fit(pack)
    q = next(x for x in pack["qs"] if x["a"] == "Na-K-2Cl")
    check("game night: every game can run from two dozen cards; Trivia's wrong answers come from the same tag first",
          not thin and have["links"] >= 25 and len(q["opts"]) == 4 and q["opts"][q["ans"]] == "Na-K-2Cl"
          and sum(o in ("Na-Cl", "Spironolactone", "Acetazolamide") for o in q["opts"]) == 3, (have, q))
    check("game night: Imposter's first twins are the likeliest mix-up, and say what tells them apart",
          {pack["twins"][0]["a"]["t"], pack["twins"][0]["b"]["t"]} == {"Nephritic", "Nephrotic"} and pack["twins"][0]["part"] == "Renal"
          and {"a": "low C3", "s": "Post-strep GN shows low C3"} in pack["twins"][0]["a"]["facts"] + pack["twins"][0]["b"]["facts"], pack["twins"][:2])
    check("game night: a thin scope says which games it can't fill (three cards: no three wrong answers, no twins, no board)",
          G.fit(G.build(GAME_ROWS[:3], seed=1))[1] == ["imposter", "links", "trivia"])
    check("game night: the pack has its caps", all(len(pack[k]) <= n for k, n in G.CAPS.items()) and pack["n"] == len(GAME_ROWS))
    # a small scope, and the cards around it (Sam's first night: a hand of six alike)
    few, around = GAME_ROWS[:6], GAME_ROWS[6:]
    alone, nearby = G.build(few, seed=2), G.build(few, seed=2, near=around)
    asked = {G.item(r)["q"] for r in few if G.item(r)}
    k = len(alone["qs"])
    check("game night: Trivia asks tonight's cards first, then (a small scope) the cards around them up to QS_MIN; black cards are tonight's alone",
          {q["q"] for q in nearby["qs"][:k]} <= asked and len(nearby["qs"]) > k and len(nearby["qs"]) <= max(k, G.QS_MIN)
          and {b["a"] for b in nearby["blacks"]} == {b["a"] for b in alone["blacks"]}, (k, len(nearby["qs"])))
    check("game night: ...but they deal the hands and fill the board: tonight's answers first, then theirs",
          len(alone["whites"]) == 6 and len(nearby["whites"]) > 20 and nearby["whites"][:6] == alone["whites"]
          and len(nearby["words"]) > len(alone["words"]) and len({w.lower() for w in nearby["whites"]}) == len(nearby["whites"]), (len(nearby["whites"]), len(nearby["words"])))
    wrong = {o for q in nearby["qs"] for i, o in enumerate(q["opts"]) if i != q["ans"]}
    check("game night: ...and give the wrong answers (some from outside tonight's cards)",
          wrong - {G.item(r)["a"] for r in few if G.item(r)}, wrong)
    from due_crew import gamenight_flow as GF
    import random
    import sqlite3
    db = sqlite3.connect(":memory:")
    db.executescript("CREATE TABLE cards (id INTEGER, nid INTEGER, did INTEGER, ord INTEGER); CREATE TABLE notes (id INTEGER, mid INTEGER, flds TEXT, tags TEXT);")
    for k, (cid, ord_, is_cloze, fields, tags) in enumerate(GAME_ROWS):
        db.execute("INSERT INTO cards VALUES (?, ?, ?, ?)", (cid, cid, 1 if k % 2 else 2, ord_))
        db.execute("INSERT INTO notes VALUES (?, ?, ?, ?)", (cid, 2 if is_cloze else 1, "\x1f".join(fields), " " + " ".join(tags) + " "))
    db.execute("INSERT INTO cards VALUES (999, 999, 3, 0)")
    db.execute("INSERT INTO notes VALUES (999, 1, ?, ' Elsewhere::Odd ')", ("Far front\x1ffar back",))
    db.execute("INSERT INTO cards VALUES (998, 998, 4, 0)")  # elsewhere, a blank before tonight's word ("____ cotransporter")
    db.execute("INSERT INTO notes VALUES (998, 2, ?, ' Elsewhere::Endo ')", ("SGLT2 inhibitors block the {{c1::Na-glucose}} cotransporter\x1f",))

    def tagged(search):
        want = re.findall(r'"tag:((?:[^"\\]|\\.)*)"', search)
        want = [w.replace("\\_", "_") for w in want]
        return [cid for cid, tags in db.execute("SELECT c.id, n.tags FROM cards c JOIN notes n ON n.id = c.nid")
                if any(t == w or t.startswith(w + "::") for t in tags.split() for w in want)]
    col = types.SimpleNamespace(find_cards=tagged, models=types.SimpleNamespace(get=lambda mid: {"type": 1 if mid == 2 else 0}),
                                db=types.SimpleNamespace(all=lambda q: db.execute(q).fetchall(), list=lambda q, *a: [r[0] for r in db.execute(q, a)]))
    was = GF._col
    GF._col = lambda: col
    try:
        mine = [r[0] for r in few]
        got = GF.near(GF.rows(mine), mine, cap=30, rng=random.Random(4))
        under = {r[0] for r in GAME_ROWS if any(t.startswith(G.topic_of(few[0][4])[0].rsplit("::", 1)[0]) for t in r[4])}
        slot = [r[0] for r in GF.near(GF.rows(mine), mine, cap=2, rng=random.Random(4), slots=True)]
    finally:
        GF._col = was
    ids = [r[0] for r in got]
    check("game night: near reads the cards around tonight's: under their topics' parent tags, their decks, then anywhere; never tonight's own",
          ids and not set(ids) & set(mine) and len(ids) == len(set(ids)) and set(ids) & (under - set(mine)) and 999 in ids, ids)
    check("game night: ...and Host's pack also the cards with a blank before the same word as tonight's (\"____ cotransporter\")",
          G.slots([G.item(r) for r in few if G.item(r)])[:1] == ["cotransporter"] and 998 in slot and not set(slot) & set(mine), slot)


def test_pip_party_host_off_the_main_thread_v395():
    """3.9.5's review: Host reads the collection on the main thread and
    builds tonight's pack off it (a big scope took seconds); the profile
    changed or signed out meanwhile, nothing opens (app.generation). Round
    three: the TV opens on the first game, and there are no bots' TVs."""
    import due_crew.app as appmod
    from due_crew import gamenight_flow as GF
    saved = (GF._pack_rows, GF._bg, GF._tv, GF.client, appmod.generation)
    jobs, tvs, said = [], [], []
    try:
        GF._pack_rows = lambda: ((list(GAME_ROWS),), {"near": [], "n": len(GAME_ROWS), "subs": {r[0]: "Renal" for r in GAME_ROWS}})
        GF._bg = lambda job, done=None: jobs.append((job, done))
        GF._tv = lambda payload: tvs.append((payload["mode"], payload["first"], {q.get("sub") for q in payload["pack"]["qs"]}))
        GF.client = lambda: types.SimpleNamespace(open_table=lambda: (200, {"code": "ABCD", "key": "k" * 43}))
        GF.Ops.start("trivia", said.append)
        check("pip party host: the pack's build is a background job; nothing opened yet", len(jobs) == 1 and not tvs and not said)
        job, done = jobs.pop()
        done(job())
        check("pip party host: built, the table's request is one more background job", len(jobs) == 1 and not tvs, (jobs, tvs))
        job, done = jobs.pop()
        done(job())
        check("pip party host: the table open, the TV opens on the first game, each question marked with its pick",
              tvs == [("tv", "trivia", {"Renal"})] and said == [None], (tvs, said))
        GF.Ops.start("trivia", said.append)
        job, done = jobs.pop()
        done(job())
        job, done = jobs.pop()  # the table's request
        appmod.generation += 1  # the profile changed while it was out
        done(job())
        check("pip party host: the profile changed while the table opened, no TV", len(tvs) == 1 and said[-1] is None, (tvs, said))
        GF.Ops.start("trivia", said.append)
        job, done = jobs.pop()
        appmod.generation += 1
        done(job())
        check("pip party host: ...nor while the pack was built", len(tvs) == 1 and not jobs, tvs)
        GF.client = lambda: types.SimpleNamespace(open_table=lambda: (429, {}))
        GF.Ops.start("trivia", said.append)
        job, done = jobs.pop()
        done(job())
        job, done = jobs.pop()
        done(job())
        check("pip party host: a refusal is said, no TV", len(tvs) == 1 and said[-1].startswith("That's a lot"), said[-1:])
    finally:
        GF._pack_rows, GF._bg, GF._tv, GF.client, appmod.generation = saved


def test_pip_party_wrong_answers_of_its_sort_v395():
    """3.9.5 round three, from a real-sized pack in a browser ("factor ____"
    offered Cleavage, Short, Bleeding): a numeral after type, class, factor
    and the like is offered its neighbours; an answer's last word names its
    sort, and answers ending in it come first ("Coombs test" among tests)."""
    import random
    from due_crew import gamenight as G
    r = random.Random(1)
    check("wrong answers: a numeral's neighbours, its suffix and case kept",
          all(G._numerals("III", random.Random(k)) in (["I", "II", "IV"], ["II", "IV", "V"]) for k in range(6)))
    check("wrong answers: XIIIa's are activated factors too; I's are II, III, IV",
          G._numerals("XIIIa", r) == ["Xa", "XIa", "XIIa"] and G._numerals("I", r) == ["II", "III", "IV"] and G._numerals("ii", r)[0] in ("i", "iii"))
    rows = [(1, 0, True, ["Rheumatoid arthritis is a type {{c1::III}} hypersensitivity reaction", ""], ["Step1::Immuno::Hypersensitivity"]),
            (2, 0, True, ["Vancomycin is given {{c1::IV}} for C. diff? No: by mouth", ""], ["Step1::Micro::Drugs"])]
    rows += [(10 + k, 0, True, [f"{{{{c1::{w}}}}} is an acronym in immunology", ""], ["Step1::Immuno::Hypersensitivity"]) for k, w in enumerate(("ATP", "RFLP", "MHC", "TCR"))]
    pool = [G.item(x) for x in rows]
    check("wrong answers: the made-up cards are questions", all(pool), [x is None for x in pool])
    P = G._Pool([x for x in pool if x])
    got = P.wrong(0, random.Random(3))
    check("wrong answers: type ____ hypersensitivity: III among numerals, never ATP or RFLP", sorted(got) in (["I", "II", "IV"], ["II", "IV", "V"]), got)
    check("wrong answers: IV with no type, class or factor before it is no numeral", G._ROMAN.match("IV") and P.slot[1][0] not in G._NUMERAL_AFTER)
    tests = ["Coombs test", "KOH whiff test", "Tzanck test", "Schilling test"]
    rows = [(30 + k, 0, True, [f"Next best step: {{{{c1::{a}}}}}", ""], ["Step1::Heme::Workup"]) for k, a in enumerate(tests)]
    rows += [(40 + k, 0, True, [f"Seen with {{{{c1::{a}}}}}", ""], ["Step1::Heme::Workup"]) for k, a in enumerate(("Stokes-Adams attacks", "Premature adrenarche", "Silver nitrate", "Bamboo spine"))]
    pool = [G.item(x) for x in rows]
    got = G._Pool(pool).wrong(0, random.Random(4))
    check("wrong answers: an answer's last word names its sort; tests among tests", G._head("Coombs test") == "test" and sorted(got) == sorted(tests[1:]), got)
    check("wrong answers: a word alone, or a last word that's a little one, names nothing", G._head("Coombs") == "" and G._head("pouch of the") == "")
    check("wrong answers: in a lowercase answer's case, but a name's disease keeps its capital",
          [G._cased(a, "heart failure") for a in ("Graves disease", "Crohn's disease", "Hyperthyroidism", "Thyroid storm")]
          == ["Graves disease", "Crohn's disease", "hyperthyroidism", "thyroid storm"])

def test_game_night_questions_make_sense_v395():
    """3.9.5, Sam: "don't want the questions to be dumb". Checked on a big
    shared deck's export (35k cards, every card tagged by each resource that
    covers it), restated here with made-up tags: a card's topic is what its
    tags agree on, never "Extra", a chapter number, a question bank's id or
    its name; a card isn't a question when its answer says nothing alone,
    sits in plain sight or needs its picture; wrong answers are the
    answer's sort, from the nearest cards and the same blank in others,
    never one that holds the answer or sits in the question; Imposter's
    pairs are two things, not one under two names."""
    import random
    from due_crew import gamenight as G
    many = ["Big::#ResA::02_Immunology::03_Responses::13_Hypersensitivity_types", "Big::#ResB::Immunology::11_Hypersensitivities",
            "Big::#ResC::04_Pathology::06_Hypersensitivity", "Big::#ResD::Immune::Hypersensitivity_Reactions::Extra",
            "Big::#QB::Step::12275", "Big::#QB2::9OaNuk", "Big::Original_decks::Somebody::immuno", "Big::#Low/HighYield::1-HighYield"]
    check("game night: a card's topic is what most of its tags say, not an id, a chapter, Extra or a resource's own name",
          G.topic_of(many)[1] in ("Hypersensitivity", "Hypersensitivity types", "Hypersensitivities"), G.topic_of(many))
    check("game night: ...a tag ending in a question's id names nothing; Extra and a chapter number are passed over; a section takes its parent",
          G.tag_topic("Big::#QB::Step::12275") == ("", "") and G.tag_topic("Big::#QB2::9OaNuk") == ("", "")
          and G.tag_topic("Deck::Renal::Loop_diuretics::Extra")[1] == "Loop diuretics" and G.tag_topic("Deck::Cardio::Week_3")[1] == "Cardio"
          and G.tag_topic("Step1::Renal::Pharm")[1] == "Renal pharm", [G.tag_topic(t) for t in ("Deck::Cardio::Week_3", "Step1::Renal::Pharm")])
    check("game night: ...and the card's own words break a tie (the topic it's about)",
          G.topic_of(["D::Cardio::Misc_stuff", "D::Vascular::Cholesterol_embolism"], "Purple toes after an angiogram: cholesterol embolism")[1]
          == "Cholesterol embolism")
    row = lambda text, tags=("D::Renal::Pharm",): (1, 0, True, [text, ""], list(tags))
    check("game night: no question from an answer that says nothing alone, one in plain sight, or no words around the blank",
          G.item(row("Major depression raises cortisol: it's {{c1::increased}}")) is None
          and G.item(row("Hydralazine and angina: {{c1::Increased (hyperkalemia)}}")) is None
          and G.item(row("Is digoxin renally cleared? {{c1::Yes}}")) is None
          and G.item(row("The {{c1::pulmonic}} valve closes late (pulmonic splitting)")) is None
          and G.item(row("{{c1::Furosemide}}")) is None
          and G.item(row("{{c1::Extra}}vascular hemolysis happens in the spleen")) is None
          and G.item((1, 0, True, ["<img src=x.png> The arrow shows the {{c1::pulmonic}} valve", ""], ["D::Cardio"])) is None)
    hint = G.item(row("Atrial flutter is treated like {{c1::atrial fibrillation::rhythm}}"))
    check("game night: a cloze's hint shows after its blank", hint and hint["q"] == "Atrial flutter is treated like ____ (rhythm)", hint)
    ex = G.item((5, 0, True, ["Bradykinin comes from {{c1::kallikrein}} cleaving HMWK", "It causes vasodilation and pain. Photo credit: Someone, CC BY-SA, via Wikimedia Commons"], ["D::Heme::Kinins"]))
    check("pip party: a card's Extra rides along for the TV after the reveal, without a picture's credit; long ones cut at a word",
          ex and ex["extra"] == "It causes vasodilation and pain." and G.extra("word " * 100).endswith("…") and len(G.extra("word " * 100)) <= G.EXTRA_MAX + 1, ex)
    valves = [row(f"Inspiration delays closure of the {{{{c1::{v}}}}} valve in case {k}", ("D::Cardio::Heart_sounds",))
              for k, v in enumerate(["pulmonic", "aortic", "mitral", "tricuspid"])]
    junk = [row(f"Card {k} says {{{{c1::{a}}}}} about something else entirely", ("D::Cardio::Heart_sounds",))
            for k, a in enumerate(["acute pancreatitis", "pancreatitis", "splitting", "12 mmHg", "Rheumatic fever", "ileocecal"])]
    rows = [(n, *r[1:]) for n, r in enumerate(valves + junk, 1)]
    q = G.item(rows[0])
    P = G._Pool([q] + [x for x in (G.item(r) for r in rows[1:]) if x])
    wrong = P.wrong(0, random.Random(3))
    check("game night: wrong answers fill the same blank in other cards first (other valves for \"the ____ valve\")",
          set(wrong) == {"aortic", "mitral", "tricuspid"}, wrong)
    g = G.item(row("Gallstones cause acute {{c1::pancreatitis}} and cholangitis"))
    pool = [g] + [x for x in (G.item(r) for r in rows) if x]
    wrong = G._Pool(pool).wrong(0, random.Random(1))
    check("game night: never a wrong answer that holds the answer (\"acute pancreatitis\"), nor a number for a word",
          all("pancreatitis" not in w.lower() for w in wrong) and "12 mmHg" not in wrong, wrong)
    ras = [row(f"{t} {{{{c1::{a}}}}} in case {k}", ("D::Onc::Ras",)) for k, (t, a) in enumerate([
        ("Mutations of Ras that alter the binding site of", "GTPase activating protein (GAP)"),
        ("Ras is switched off by", "GTPase activating proteins (GAPs)"), ("Ras passes the growth signal on as one of the", "signal transducers"),
        ("Cyclins act at the cell cycle's", "checkpoints (restriction points)"), ("Growth factors bind", "receptor tyrosine kinases")])]
    ras = [(n, *r[1:]) for n, r in enumerate(ras, 100)]
    wrong = G._Pool([x for x in (G.item(r) for r in ras) if x]).wrong(0, random.Random(2))
    check("game night: never a wrong answer that is the right one in the plural (Sam's \"GAPs\" for \"GAP\")",
          not any("gtpase" in w.lower() for w in wrong) and G._unique(["GAP", "GAPs", "gaps"]) == ["GAP"], wrong)
    check("game night: a wrong answer takes the right one's case, so neither stands out (acronyms and Greek as they are)",
          G._cased("Mitral", "pulmonic") == "mitral" and G._cased("aortic", "Pulmonic") == "Aortic" and G._cased("ACE", "pulmonic") == "ACE"
          and G._cased("β-blocker", "Pulmonic") == "β-blocker")
    check("game night: Imposter's pairs are two things: plurals, typos, and one name inside another are one topic",
          not G._alike("Nephritic", "Nephrotic") and not G._alike("Class I Antiarrhythmics", "Class II Antiarrhythmics")
          and G._alike("Hypersensitivity Reactions", "Hypersensitvity reactions") and G._alike("Transplant and Rejection", "Transplant-Rejection-Prophylaxis")
          and G._one("Cardiomyopathies") == G._one("Cardiomyopathy"))
    check("pip party: a question's subject for topic rounds is a level over its topic, what its tags agree on, a question bank's tags aside",
          G.area_of(["Big::#ResA::02_Immunology::03_Responses::Hypersensitivity", "Big::#ResB::Immunology::Hypersensitivities",
                     "Big::#ResC::13_Immunology::Clinical::Hypersensitivity", "Big::#QB::Step::12275"], "Hypersensitivity") == "Immunology"
          and G.area_of(["Step1::Renal::Pharm"], "Renal pharm") == "Renal" and G.area_of(["Lone"], "Lone") == "")
    rq = [{"q": "a", "a": "x"}, {"q": "b", "a": "y"}]
    G.rounds(rq, [{"q": "a", "a": "x", "tags": ["D::Cardio::HF"], "topic": "HF"}, {"q": "b", "a": "y", "tags": ["E::Cardiology::MI"], "topic": "MI"}])
    check("pip party: one subject under its names (Cardio and Cardiology are one round)", rq[0]["round"] == rq[1]["round"] != "", rq)
    check("game night: Links' board holds no word inside another (ACE and ACE inhibitors are one tile)",
          G._apart(["ACE", "ACE inhibitors", "Digoxin", "digoxin toxicity", "Statins"]) == ["ACE", "Digoxin", "Statins"])
    pack = G.build(GAME_ROWS, seed=3)
    topics = {it["topic"] for it in (G.item(r) for r in GAME_ROWS) if it}
    check("game night: what every phone sees outside Rounds is topic names; a card's answer joins Links' board only when the topics run short",
          set(pack["prompts"]) <= topics and (len(topics) >= G.WORDS_MIN or len(pack["words"]) <= G.WORDS_MIN),
          (pack["prompts"][:5], len(pack["words"])))
    for x in pack["qs"]:
        if any(G._overlaps(o, x["a"]) for i, o in enumerate(x["opts"]) if i != x["ans"]) or any(G._shown(o, x["q"]) for o in x["opts"]):
            check("game night: no Trivia question offers a wrong answer that holds the right one or sits in the question", False, x)
            break
    else:
        check("game night: no Trivia question offers a wrong answer that holds the right one or sits in the question", True)
    check("game night: white cards and words are never a number or a thin word", not any(G.empty(w) or G._shape(w)[0] == "n" for w in pack["whites"] + pack["words"]),
          [w for w in pack["whites"] + pack["words"] if G.empty(w) or G._shape(w)[0] == "n"])


def test_game_night_one_player_v395():
    """3.9.5, game night (site/public/table.js, on tonight's pack): each game
    starts at its own min since the release (FEW = Infinity; 1 while Sam
    tested it). Each game, one player through its most, still starts, and
    the stand-in players' answers move it on: alone, Rounds has no
    Attending, Imposter has nobody to vote for, and Links' clue giver picks
    on the TV too. What every phone gets carries no card's words in Trivia, no other
    hand in Rounds, no key in Links, no twin in Imposter: those are each
    seat's own (secrets), whispered."""
    import shutil
    import subprocess
    from due_crew import gamenight as G
    if not shutil.which("node"):
        check("game night: node runs the games (skipped: no node)", True)
        return
    src = open(os.path.join(REPO, "site", "public", "table.js"), encoding="utf-8").read()
    a, b = src.index("let D = null;"), src.index("// ---------- hubs")
    pack = G.build(GAME_ROWS, "test", seed=3)
    # the games and their helpers alone: nothing before the hubs draws until asked
    js = "const matchMedia = () => ({ matches: true });\n" + src[a:b].replace("let D = null;", "let D = " + json.dumps(pack) + ";", 1) + GAMES_SIM_JS
    r = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=60)
    check("game night: the games run in node", r.returncode == 0, r.stderr[:400])
    if r.returncode:
        return
    got = json.loads(r.stdout)
    runs = got["out"]
    by = {(x["id"], x["N"]): x for x in runs}
    check("game night: all six games, one player to their most, start and take their first answers without an error",
          len({x["id"] for x in runs}) == 6 and all(not x["err"] for x in runs), [x for x in runs if x["err"]][:2])
    check("game night: what every phone gets holds nobody's secret (Trivia's words, a hand, the key, the twin)",
          all(not x["leaked"] for x in runs), [(x["id"], x["N"], x["leaked"]) for x in runs if x["leaked"]][:4])
    check("game night: released, every game needs its own min (Imposter three, Links four, Trivia one)",
          all(x["need"] == x["min"] for x in runs) and by[("imposter", 1)]["need"] == 3 and by[("links", 1)]["need"] == 4
          and by[("trivia", 1)]["need"] == 1, sorted({(x["id"], x["need"]) for x in runs}))
    check("game night: alone, every game moves on from its first step (none waits on a second player)",
          all(len(by[(g, 1)]["phases"]) >= 2 for g in ("imposter", "rounds", "trivia", "draw", "between", "links")),
          {g: by[(g, 1)]["phases"] for g in ("imposter", "rounds", "trivia", "draw", "between", "links")})
    check("game night: alone, Rounds plays straight to the card's answer and on to the next round; with two, the Attending picks",
          by[("rounds", 1)]["phases"] == ["play", "chart", "play"] and by[("rounds", 2)]["phases"][:3] == ["play", "pick", "chart"])
    check("game night: alone, Imposter's vote ends it; Draw it is a chain of one; Links' clue giver guesses",
          by[("imposter", 1)]["phases"] == ["clue", "vote", "end"] and by[("draw", 1)]["phases"] == ["step", "reveal"]
          and by[("links", 1)]["phases"][:2] == ["clue", "guess"] and len(by[("links", 1)]["phases"]) >= 3, by[("links", 1)])
    small = G.build(GAME_ROWS[:6], seed=2, near=GAME_ROWS[6:])
    deal = subprocess.run(["node", "-e", "const matchMedia = () => ({ matches: true });\n" + src[a:b].replace("let D = null;", "let D = " + json.dumps(small) + ";", 1) + r"""
const out = [];
for (const N of [1, 3, 5]) {
  const c = { N, seats: Array.from({ length: N }, (_, i) => ({ n: "P" + i })), A: {}, here: () => true, name: (i) => "P" + i };
  let S = Rounds.start(c), dup = 0, short = 0;
  for (let r = 0; r < 15; r++) {
    const all = S.hands.flat().map(norm);
    if (new Set(all).size !== all.length) dup++;
    if (S.hands.some((hd, i) => i !== S.att && !hd.length)) short++;
    c.A = {}; S.hands.forEach((hd, i) => { if (i !== S.att && hd.length) c.A[i] = { c: hd[0] }; });
    S = Rounds.force(S, c) || S; if (S.ph === "pick") { c.A[S.att] = { f: 0 }; S = Rounds.force(S, c); } S = Rounds.next(S, c);
  }
  out.push([N, dup, short, Rounds.per(N)]);
}
console.log(JSON.stringify(out));
"""], capture_output=True, text=True, timeout=60)
    dealt = json.loads(deal.stdout or "[]")
    check("game night: Rounds never deals a card twice, in a hand or across them, and nobody's hand is empty (a small scope, 1 to 5 players)",
          dealt and all(d == 0 and e == 0 for _n, d, e, _p in dealt), dealt or deal.stderr[:300])
    check("game night: a hand is seven when there are cards enough", [p for _n, _d, _e, p in dealt] == [7, 7, 4], dealt)
    order = json.loads(re.search(r"const ORDER = (\[[^\]]*\]);", src).group(1))
    check("pip party: on the menu are Trivia, Imposter and Links (table.js's ORDER is gamenight.GAMES); the other three are off it, kept",
          order == [g for g, _l in G.GAMES] == ["trivia", "imposter", "links"] and all(f"const {n} = {{" in src for n in ("Rounds", "DrawIt", "Between")))
    tq = [{"q": f"Q{k} {t}", "a": f"A{k}", "tag": t, "opts": [f"A{k}", "x", "y", "z"], "ans": 0, "full": f"The card says A{k}", "extra": "Why"}
          for t in ("Renal pharm", "Vasculitis") for k in range(6)] + [{"q": "Q lone", "a": "A", "tag": "Lone", "opts": ["A", "b", "c", "d"], "ans": 0, "full": "", "extra": ""}]
    topic = subprocess.run(["node", "-e", "const matchMedia = () => ({ matches: true });\n" + src[a:b].replace("let D = null;", "let D = " + json.dumps(dict(small, qs=tq, subs=[])) + ";", 1) + r"""
const S = Trivia.start(), B = Trivia.block("Vasculitis"), M = Trivia.block(null);
const c = { N: 1, A: [{ o: 0 }], here: () => true };
const shown = Trivia.force(B, c);
console.log(JSON.stringify({ ph: S.ph, ts: S.ts, pub: Trivia.pub(S), skip: Trivia.force(S, c), tags: [...new Set(B.qs.map((q) => q.tag))], n: B.qs.length,
  mixed: M.qs.length, phone: JSON.stringify(Trivia.pub(shown)), one: Trivia.start.call(null) && 1 }));
"""], capture_output=True, text=True, timeout=60)
    t = json.loads(topic.stdout or "{}")
    check("pip party: Trivia picks a subject first when tonight has two with a block's worth (six or more), or mixes them",
          t.get("ph") == "topic" and t.get("ts") == [["Renal pharm", 6], ["Vasculitis", 6]] and t.get("pub") == {"ph": "topic", "k": 0, "n": 0}
          and t.get("skip") is None and t.get("tags") == ["Vasculitis"] and t.get("n") == 6 and t.get("mixed") == 10, t or topic.stderr[:300])
    check("pip party: after the reveal the card (its sentence, its Extra) is the TV's; phones get none of it",
          "The card says" not in t.get("phone", "x") and "Why" not in t.get("phone", "x") and "Q" not in t.get("phone", "Q"), t.get("phone"))
    phone = src[src.index("const Links = {"):]
    phone = phone[phone.index("  phone(x, seat, p) {"):]
    phone = phone[:phone.index("\n  },\n")]
    check("game night: Links is picked on the TV; a phone has no board to tap (Sam: too small), the clue giver's the key alone, "
          "in colours (Sam: \"colorful blocks\"), the words on the TV",
          "tap:" not in phone and "Links.blocks(x, key)" in phone and "Links.grid(" not in phone and "p.answer({ t:" not in phone, phone[:200])
    check("game night: what each game needs from the pack is gamenight.NEEDS (the twin)",
          {k: list(v) for k, v in G.NEEDS.items()} == got["needs"], got["needs"])
    node = subprocess.run(["node", "--check", "-"], input=src, capture_output=True, text=True)
    check("game night: table.js parses", node.returncode == 0, node.stderr[:300])
    check("game night: no sample packs: the site carries no questions of its own",
          not os.path.exists(os.path.join(REPO, "site", "public", "table-packs.js")) and "GN_PACKS" not in src)


def test_trivia_a_block_of_fair_questions_v395():
    """3.9.5, Sam's Trivia of two questions ("only saw two questions"), its
    label the answer ("Signal Transducers" over "____ (class)") and a wrong
    answer of the wrong sort: Trivia needs a block's worth (ten) to be on
    the menu, and a scope with few questions of its own (long answers,
    pictures) is filled from the cards around it, its own topics first;
    a hint after the blank picks wrong answers of its sort (Host also
    searches for cards with the same hint); a label that says the answer
    isn't shown; nor is a wrong answer the question shows in the plural; a
    card's line break is a sentence's end, not a run on."""
    from due_crew import gamenight as G
    check("trivia: a line break between sentences reads as two, a <br> or a newline; a list keeps its colon",
          G.clean("for cell proliferation<br>Ras proteins are") == "for cell proliferation. Ras proteins are"
          and G.clean("<div>one line</div><div>Then another</div>") == "one line. Then another"
          and G.clean("Causes:<br>fever") == "Causes: fever" and G.clean("the<br>ACE inhibitor") == "the ACE inhibitor"
          and G.clean("a\nb") == "a b")
    row = lambda n, text, tags: (n, 0, True, [text, ""], tags)
    rows = [row(1, "The Ras family of proto-oncogenes are {{c1::signal transducers::class}} found in carcinomas", ["S::Path::Onc::Signal_Transducers"]),
            row(2, "Myc proteins are {{c1::transcription factors::class}} that drive growth", ["S::Path::Onc::Nuclear"]),
            row(3, "ERBB2 proteins are {{c1::receptor tyrosine kinases::class}} on the cell surface", ["S::Path::Onc::Receptors"]),
            row(4, "Rb proteins are {{c1::tumor suppressors::class}} that hold the cell cycle", ["S::Path::Onc::Suppressors"]),
            row(5, "Down syndrome is inherited as {{c1::nondisjunction}} most often", ["S::Path::Genetics::Trisomy"]),
            row(6, "Cystic fibrosis is {{c1::autosomal recessive}} in inheritance", ["S::Path::Genetics::CF"]),
            row(7, "Marfan syndrome is {{c1::autosomal dominant}} in inheritance", ["S::Path::Genetics::Marfan"]),
            row(8, "Fragile X is {{c1::X-linked dominant}} in inheritance", ["S::Path::Genetics::FragX"]),
            row(9, "Kinases add a {{c1::phosphate group}} to proteins", ["S::Biochem::Kinase"])]
    pack = G.build(rows, seed=1)
    ras = next(q for q in pack["qs"] if q["a"] == "signal transducers")
    wrong = [o for o in ras["opts"] if o != ras["a"]]
    check("trivia: a hint after the blank picks wrong answers of its sort (\"(class)\": classes, not modes of inheritance)",
          set(wrong) == {"transcription factors", "receptor tyrosine kinases", "tumor suppressors"}, ras["opts"])
    check("trivia: a label that says the answer isn't shown (the topic \"Signal Transducers\" over \"signal transducers\")",
          ras["tag"] == "" and next(q for q in pack["qs"] if q["a"] == "transcription factors")["tag"] == "Nuclear", ras)
    check("trivia: a wrong answer the question already shows, in the singular or the plural, isn't on offer",
          G._shown("proto-oncogene", "The Ras family of proto-oncogenes encode ____") and G._shown("kinases", "a kinase adds ____")
          and not G._shown("tumor suppressor", "The Ras family of proto-oncogenes encode ____"))
    check("trivia: the hints tonight's blanks have, for Host's search (\"::class}}\")", G.hints([G.item(r) for r in rows]) == ["class"])
    src = open(os.path.join(REPO, "due_crew", "gamenight_flow.py"), encoding="utf-8").read()
    check("trivia: Host's search finds cards with a blank before tonight's word, or with tonight's hint",
          'f"%}}}} {w}%" for w in G.slots(its)' in src and 'f"%::{h}}}}}%" for h in G.hints(its)' in src)
    # a scope that makes few questions of its own: long answers, a picture
    long = [(100 + k, 0, False, [f"Describe stage {k} of the long process", "A long answer that runs on well past what a TV can show as one choice"], ["S::Path::Onc::Long"]) for k in range(20)]
    few = long + rows[:2]
    jun = row(10, "Jun proteins bind DNA as {{c1::AP-1 partners}} in the nucleus", ["S::Path::Onc::Nuclear"])  # tonight's topic, around it
    alone, filled = G.build(few, seed=1), G.build(few, seed=1, near=GAME_ROWS + rows[2:] + [jun])
    check("trivia: needs a block's worth (ten) to be on the menu; the table's NEEDS says the same",
          G.NEEDS["trivia"] == ("qs", 10) and "trivia" in G.fit(alone)[1] and len(alone["qs"]) < 10
          and 'trivia: ["qs", 10]' in open(os.path.join(REPO, "site", "public", "table.js"), encoding="utf-8").read(), len(alone["qs"]))
    check("trivia: a scope short of questions is filled from the cards around it, its own first, its own topics' next",
          len(filled["qs"]) >= 10 and "trivia" not in G.fit(filled)[1] and {q["a"] for q in filled["qs"][:2]} == {"signal transducers", "transcription factors"}
          and filled["qs"][2]["a"] == "AP-1 partners", [q["a"] for q in filled["qs"]][:6])


def test_pip_party_pack_for_the_vote_v395():
    """3.9.5, round three: the table votes on what to play, so the pack
    carries each question's, word's and pair's pick (or, with no picks,
    its subject), and a pack over several holds enough of each to play on
    its own (PER_SUB, SUB_CAPS at most)."""
    from due_crew import gamenight as G
    rows = GAME_ROWS
    subs = {r[0]: ("Renal" if "Renal" in " ".join(r[4]) else "Elsewhere") for r in rows}
    pack = G.build(rows, seed=3, subs=subs)
    check("vote pack: each question carries the pick its card is from",
          pack["qs"] and all(q["sub"] == subs[next(r[0] for r in rows if G.item(r) and G.item(r)["q"] == q["q"])] for q in pack["qs"]),
          [(q["a"], q["sub"]) for q in pack["qs"]][:6])
    check("vote pack: words and pairs carry their topic's pick, where it has one",
          set(pack["wsubs"].values()) <= {"Renal", "Elsewhere"} and pack["wsubs"] and all(p["sub"] in ("Renal", "Elsewhere", "") for p in pack["twins"]),
          (pack["wsubs"], [p["sub"] for p in pack["twins"]]))
    plain = G.build(rows, seed=3)
    check("vote pack: with no picks, a question's sub is its subject (its round)",
          all(q["sub"] == (q.get("round") or q.get("tag") or "") for q in plain["qs"]))
    items = [{"sub": f"S{k % 8}", "tags": [], "topic": ""} for k in range(80)]
    caps = G._caps(items, True)
    check("vote pack: eight picks raise the caps to PER_SUB each, SUB_CAPS at most; one pick keeps CAPS",
          caps["qs"] == 240 and caps["words"] == 200 and caps["twins"] == 32 and G._caps(items[:1], True) == G.CAPS, caps)


def test_pip_party_said_out_loud_v395():
    """3.9.5, Pip Party (Sam: "you have to imagine that people are sitting
    next to each other"): what can be said out loud isn't typed. Imposter
    (Sam: "the imposter doesn't have anything at all. the tv should
    designate the order"): every phone has the topic but the imposter's;
    the TV sets the order round the room, once or twice, and its Vote ends
    the words; the caught imposter guesses among the topic, its twin and
    two more. Links' clue giver says the word and taps how many it's for:
    the clue on the table is a number. No text box in the menu's three; a
    link with the code in it asks only for a name."""
    import shutil
    import subprocess
    from due_crew import gamenight as G
    if not shutil.which("node"):
        check("pip party out loud: node runs the games (skipped: no node)", True)
        return
    src = open(os.path.join(REPO, "site", "public", "table.js"), encoding="utf-8").read()
    a, b = src.index("let D = null;"), src.index("// ---------- hubs")
    pack = G.build(GAME_ROWS, "test", seed=3)
    js = "const matchMedia = () => ({ matches: true });\n" + src[a:b].replace("let D = null;", "let D = " + json.dumps(pack) + ";", 1) + r"""
const c = (N, A, here) => ({ N, seats: Array.from({ length: N }, (_, i) => ({ n: "P" + i })), A: A || [], here: here || (() => true), name: (i) => "P" + i });
const S = Imposter.start(c(3)), C = c(3);
const order = S.order.slice(), sec = Imposter.secrets(S, C), pub = Object.keys(Imposter.pub(S, C)).sort();
const waits = Imposter.collect(S, [{ said: 1 }, { said: 1 }, { said: 1 }], c(3, [{ said: 1 }, { said: 1 }, { said: 1 }]));
const V = Imposter.force(S, C), votes = [0, 1, 2].map((i) => ({ v: i === S.imp ? (i + 1) % 3 : S.imp }));
const L0 = Imposter.collect(V, votes, c(3, votes)), lastPub = L0 && Imposter.pub(L0, C);
const E = L0 && Imposter.collect(L0, Object.assign([], { [S.imp]: { g: S.a } }), c(3, Object.assign([], { [S.imp]: { g: S.a } })));
Imposter.laps = 1;  // the TV's Once round, kept for the next
const once = Imposter.start(c(3)).laps;
Imposter.laps = 2;
const bots = [0, 1, 2].map((i) => Imposter.bot(Imposter.pub(S, C), i, { seats: C.seats }));
const L = Links.play(Links.start(c(4))), g = L.givers[L.turn], LA = [];
LA[g] = { w: "typed", n: 3 };
const L2 = Links.collect(L, LA, c(4, LA));
const LB = []; LB[g] = { w: "typed" };
console.log(JSON.stringify({ order, imp: S.imp, a: S.a, b: S.b, sec, pub, waits, vote: V.ph, last: L0 && L0.ph, lastPub, end: E && E.ph, endA: E && Imposter.pub(E, C).a, once, bots,
  links: L2 && { ph: L2.ph, clue: L2.clue, left: L2.left, pub: Links.pub(L2).clue }, wordOnly: Links.collect(L, LB, c(4, LB)) }));
"""
    r = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=60)
    got = json.loads(r.stdout or "{}")
    check("pip party out loud: the games run in node", r.returncode == 0 and got, r.stderr[:400])
    if not got:
        return
    o = got["order"]
    check("Imposter: round the room from someone, each once, in the room's order",
          sorted(o) == [0, 1, 2] and all(o[k] == (o[0] + k) % 3 for k in range(3)), o)
    imp_ = got["imp"]
    check("Imposter: every phone has the topic but the imposter's, which has nothing (Sam: \"doesn't have anything at all\")",
          got["sec"][imp_] == {"imp": 1} and all(x == {"top": got["a"]} for i, x in enumerate(got["sec"]) if i != imp_), got["sec"])
    check("Imposter: every phone gets the order and how many times round, and no words; nothing a phone sends moves the words on",
          got["pub"] == ["laps", "order", "part", "ph"] and got["waits"] is None and got["bots"] == [None, None, None], got)
    check("Imposter: the TV's Vote ends the words; caught, the guess is among the topic, its twin and two more, and the topic reaches phones only at the end",
          got["vote"] == "vote" and got["last"] == "last" and len(got["lastPub"]["opts"]) == 4
          and {got["a"], got["b"]} <= set(got["lastPub"]["opts"]) and "a" not in got["lastPub"]
          and got["end"] == "end" and got["endA"] == got["a"], got)
    check("Imposter: once round when the TV says so (Sam: \"choose one or two rounds\"), kept for the next round", got["once"] == 1, got["once"])
    check("Links: the clue giver says the word and taps how many; the clue on the table is the number (a typed word goes nowhere)",
          got["links"] == {"ph": "guess", "clue": {"n": 3}, "left": 4, "pub": {"n": 3}} and got["wordOnly"] is None, got["links"])
    def block(start, end):
        part = src[src.index(start):]
        return part[:part.index(end)]
    phones = [block("const Imposter = {", "\nfunction fixRound"), block("const Trivia = {", "\nconst DrawIt = {"), block("const Links = {", "\n// Each game starts at its own min")]
    check("pip party out loud: no text box on a phone in Trivia, Imposter or Links",
          all('type: "text"' not in x and "p.draft(" not in x and "h(\"select\"" not in x for x in phones))
    imp = block("const Imposter = {", "\nfunction fixRound")
    check("Imposter: Once round and Twice round and Vote on the TV, the order's own way on (no Skip ahead beside it); a picked one shows as picked; no Said it",
          '[[1, "Once round"], [2, "Twice round"]]' in imp and '"aria-pressed": String(S.laps === n)' in imp and '"data-next": ""' in imp
          and 'body.querySelector("[data-next]")' in src and "Said it" not in imp
          and '.seg button[aria-pressed="true"]' in open(os.path.join(REPO, "site", "public", "table.css"), encoding="utf-8").read())
    last = imp[imp.index('    if (S.ph === "last") return', imp.index("  tv(S, c) {")):]
    last = last[:last.index("\n")]
    check("Imposter: caught, the TV never says the topic till the guess is in", "S.a" not in last and "S.b" not in last, last)
    join = block("function joinView(pre) {", "\nfunction botsView")
    check("pip party out loud: a link with the code asks only for a name (the code's box shows for Another table, a bad code or none)",
          "cd.hidden = linked;" in join and join.count("typeIt();") >= 3 and "Another table" in join
          and "(nm.value ? (linked ? go : cd) : nm).focus()" in join)


def test_pip_party_v395():
    """3.9.5's last round (Sam: "build both right now"; game night is Pip
    Party now, still gamenight in code). The pack's written cards: Rounds'
    black cards with a topic (about one in four, no answer of their own:
    the Attending's pick is the round, so alone there are none), Draw it's
    written prompts (about a quarter of the chains), Somewhere between's
    study-life ends beside its own; none without topics. You › Pip Party,
    after Insights for those it's open to: what to play from, the six the
    pick fills, Host or Try it with bots, the TV's code once it's open;
    worked out only on screen and kept a while; every click through _on_js."""
    import shutil
    import subprocess
    import due_crew as dc
    from due_crew import gamenight as G, gamenight_flow as GF
    from aqt.deckbrowser import DeckBrowser
    pack = G.build(GAME_ROWS, "test", seed=3)
    topics = {G.topic_name(r[4][0].split("::")[-1]) for r in GAME_ROWS} | set(G.names({r[4][0]: 1 for r in GAME_ROWS}).values())
    w = [b for b in pack["blacks"] if b.get("w")]
    mine = [b for b in pack["blacks"] if not b.get("w")]
    check("pip party: Rounds' written cards are marked, have no answer, say they're Pip Party's, and are a quarter of the deck",
          w and all(b["a"] == "" and b["tag"] == "Pip Party" and "____" in b["q"] for b in w)
          and len(w) == (len(mine) + 1) // 3 and abs(len(w) / len(pack["blacks"]) - 0.25) < 0.05, (len(w), len(pack["blacks"])))
    check("pip party: ...each {topic} one of tonight's topic names, the template filled, each template once",
          all("{" not in b["q"] for b in w) and len({b["q"] for b in w}) == len(w)
          and any(any(t in b["q"] for t in topics) for b in w), [b["q"] for b in w])
    check("pip party: Draw it's written prompts are tonight's topics in a spot, Somewhere between gets four study-life ends",
          len(pack["draws"]) == 8 and all("{" not in d and any(t in d for t in topics) for d in pack["draws"])
          and len(pack["scales"]) == G.SCALES_IN and all(tuple(x) in G.SCALES for x in pack["scales"]), (pack["draws"][:3], pack["scales"]))
    bare = G.build([(r[0], r[1], r[2], r[3], []) for r in GAME_ROWS], seed=3)
    check("pip party: no topics, no written cards, prompts or ends",
          not any(b.get("w") for b in bare["blacks"]) and bare["draws"] == [] and bare["scales"] == [])
    for t in G.WRITTEN + G.DRAWS + tuple(" ".join(x) for x in G.SCALES):
        if re.search(r"(?i)\b(compete|rival|beat|win)\b", t) or len(t) > 60:
            check("pip party: written copy is terse and friendly", False, t)
    if shutil.which("node"):
        src = open(os.path.join(REPO, "site", "public", "table.js"), encoding="utf-8").read()
        a, b = src.index("let D = null;"), src.index("// ---------- hubs")
        js = "const matchMedia = () => ({ matches: true });\n" + src[a:b].replace("let D = null;", "let D = " + json.dumps(pack) + ";", 1) + r"""
const mk = (N) => { const seats = Array.from({ length: N }, (_, i) => ({ n: "P" + i })); return { N, seats, A: [], here: () => true, name: (i) => "P" + i }; };
const alone = mk(1), three = mk(3);
const lone = Rounds.start(alone);
const wi = D.blacks.findIndex((b) => b.w);
let S = Rounds.start(three);
S = fixRound(Object.assign({}, S, { order: [wi].concat(S.order.filter((i) => i !== wi)), bi: 0 }));
three.A = S.hands.map((hd, i) => (i === S.att ? null : { c: hd[0] }));
S = Rounds.collect(S, three.A, three);
const picked = S.ph;
three.A = []; three.A[S.att] = { f: 0 };
S = Rounds.collect(S, three.A, three);
const x = Rounds.pub(S, three);
const starts = [1, 2, 3, 4, 8].map((N) => DrawIt.starts(N).filter((t) => D.draws.includes(t)).length);
const st8 = DrawIt.starts(8);
const B = Between.start(), ends = Between.ends();
console.log(JSON.stringify({ loneWritten: lone.order.filter((i) => D.blacks[i].w).length, loneN: lone.order.length, picked, ph: S.ph, x,
  hasBlank: JSON.stringify(S.hands).includes('""'),
  starts, st8n: st8.length, ends: ends.length, scalesIn: D.scales.every((sc) => ends.some((e) => e[0] === sc[0])), bEnds: B.ends.length,
  bPub: Object.keys(Between.pub(B)).join(",") }));
"""
        r = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=60)
        got = json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else {}
        check("pip party: alone, Rounds never draws a written card (nobody to pick)", got and got["loneWritten"] == 0 and got["loneN"] == len(mine), got or r.stderr[:300])
        check("pip party: a written card plays through: everyone plays, the Attending picks, the chart has the pick and no answer",
              got.get("picked") == "pick" and got.get("ph") == "chart" and got["x"].get("w") == 1 and got["x"].get("ans") == ""
              and got["x"].get("fav") == 0 and not got.get("hasBlank"), got)
        check("pip party: Draw it starts about a quarter of the chains from a written prompt (1, 2, 3, 4, 8 players)",
              got.get("starts") == [0, 1, 1, 1, 2] and got.get("st8n") == 8, got.get("starts"))
        check("pip party: Somewhere between's ends are its twelve and the pack's four; a round's ends ride its pub",
              got.get("ends") == 16 and got.get("scalesIn") and got.get("bEnds") == 16 and "L" in got.get("bPub", ""), got)
    else:
        check("pip party: node runs the games (skipped: no node)", True)

    # Sam: no game of anyone else's named, in the games, their glue or their pages
    names = re.compile(r"(?i)cards against|\bcah\b|codenames|telestrations|wavelength|horsepaste|jackbox|spyfall|kahoot|pictionary"
                       r"|trivial pursuit|apples to apples|quiplash|scattergories|taboo|werewolf|among us|dixit|charades")
    files = [os.path.join(REPO, *f) for f in (("site", "public", "table.js"), ("site", "public", "table.html"), ("site", "public", "table.css"),
                                              ("due_crew", "gamenight.py"), ("due_crew", "gamenight_flow.py"),
                                              ("due_crew", "ui", "game_night_tv.py"),
                                              ("worker", "src", "table.ts"))] + fakes.board_files()
    named = [(os.path.basename(f), m.group(0)) for f in files for m in names.finditer(open(f, encoding="utf-8").read())]
    check("pip party: no other game is named in its games, glue, window or pages (trademarks); each says its kind in our words",
          not named and "kind: \"Fill in the blank\"" in open(files[0], encoding="utf-8").read() and "like:" not in open(files[0], encoding="utf-8").read(), named)

    # You › Pip Party, round three: the glue against a small collection, every click as the board sends it
    import sqlite3
    import urllib.parse
    from due_crew import app as _app
    db = sqlite3.connect(":memory:")
    db.executescript("CREATE TABLE cards (id INTEGER, nid INTEGER, did INTEGER, odid INTEGER, ord INTEGER, queue INTEGER, type INTEGER);"
                     "CREATE TABLE notes (id INTEGER, mid INTEGER, flds TEXT, tags TEXT);")
    decks = {1: "Step 1", 2: "Step 1::Renal", 3: "Block <2>"}
    party_rows = list(GAME_ROWS) + [(900 + k, 0, False, [f"Q {k}", f"A {k}"], [f"QB::Block_A::{1001 + k}"]) for k in range(12)]
    for k, (cid, ord_, is_cloze, fields, tags) in enumerate(party_rows):
        did = 2 if "Renal" in " ".join(tags) else 3 if cid >= 900 else 1
        db.execute("INSERT INTO cards VALUES (?, ?, ?, 0, ?, 0, 2)", (cid, cid, did, ord_))
        db.execute("INSERT INTO notes VALUES (?, ?, ?, ?)", (cid, 2 if is_cloze else 1, "\x1f".join(fields), " " + " ".join(tags) + " "))

    def found(search):
        ids = [r[0] for r in db.execute("SELECT c.id FROM cards c")]
        tags = {c: t.split() for c, t in db.execute("SELECT c.id, n.tags FROM cards c JOIN notes n ON n.id = c.nid")}
        dids = dict(db.execute("SELECT id, did FROM cards"))
        out = set(ids)
        for neg, kind, name in re.findall(r'(-?)"?(tag|deck):((?:[^"\\]|\\.)*)"?', search):
            name = name.replace("\\_", "_").replace('\\"', '"').lower()
            if kind == "tag":
                hit = {c for c in ids if any(t.lower() == name or t.lower().startswith(name + "::") for t in tags[c])}
            else:
                hit = {c for c in ids if decks[dids[c]].lower() == name or decks[dids[c]].lower().startswith(name + "::")}
            out = out - hit if neg else out & hit
        if "rated:7:1" in search:
            out &= set(ids[:5])
        return sorted(out)
    col = types.SimpleNamespace(find_cards=found, sched=types.SimpleNamespace(day_cutoff=2000000000),
                                models=types.SimpleNamespace(get=lambda mid: {"type": 1 if mid == 2 else 0}),
                                decks=types.SimpleNamespace(all_names_and_ids=lambda: [types.SimpleNamespace(id=i, name=n) for i, n in decks.items()],
                                                            name=lambda i: decks.get(int(i), "")),
                                db=types.SimpleNamespace(all=lambda q, *a: db.execute(q, a).fetchall(), list=lambda q, *a: [r[0] for r in db.execute(q, a)]))
    from due_crew import team_flow
    calls, started, evals, clipped = [], [], [], []
    conf = {"due_tab": "party", "party": {"by": "tag"}}
    saved = (GF.shown, GF._col, GF._redraw, GF.cfg, GF.save_cfg, GF.Ops.start, GF._clip, GF.tooltip, dc.mw.col, GF._bg, GF._file,
             team_flow._know, _app.board_eval, GF._sys_decks, GF._sys_level, GF.near)
    kept_file = os.path.join(tempfile.mkdtemp(), "game_night.json")
    try:
        GF.shown, GF._col, dc.mw.col = (lambda: True), (lambda: col), col
        drawn = []
        GF._redraw = lambda: (calls.append("redraw"), drawn.append(GF.tab_view(conf)))  # the board draws the tab again, as Anki would
        GF.cfg, GF.save_cfg = (lambda: conf), (lambda c, **k: calls.append("saved"))
        GF._bg = lambda job, done=None: done(job())  # the builds, here and now
        GF._file = lambda: kept_file
        GF._clip, GF.tooltip = clipped.append, (lambda *a, **k: None)
        GF.near = lambda got, cids, cap=0, rng=None, slots=False: []
        team_flow._know = lambda c, deck, cutoff: ({r[0]: (0.95 if r[0] % 2 else 0.6) for r in party_rows[:20]}, "right")
        _app.board_eval = evals.append
        GF.TAB.update(gen=None)
        send = lambda m: dc._on_js(False, as_board("duecrew:" + m), DeckBrowser())
        v = GF.tab_view(conf)
        names = [t["name"] for t in v["tiles"]]
        check("pip party tab: by Tags, the tree's top level, the most carded first, each tile's cards, what I know of them, and whether it opens",
              names == ["Step1", "QB"] and v["tiles"][0]["n"] == len(GAME_ROWS) and v["tiles"][0]["kids"] and v["tiles"][0]["know"] is not None
              and v["tiles"][1]["know"] is None and v["all"] == "All of your tags" and v["n"] == len(party_rows), (names, v["tiles"][:1], v["all"], v["n"]))
        check("pip party tab: the three games up top with tonight's counts, the one the TV opens on first, kept picks, Host",
              [g["id"] for g in v["games"]] == ["trivia", "imposter", "links"] and v["first"] in ("trivia", "imposter", "links")
              and [g["first"] for g in v["games"]].count(True) == 1 and all(isinstance(g["n"], int) for g in v["games"]), v["games"])
        send("party:open:1")
        send("party:open:0")
        v = GF.tab_view(conf)
        check("pip party tab: › opens a tile; a level's question numbers fold into one tile (ten or more), the trail goes back",
              v["trail"] == ["QB", "Block A"] and v["tiles"] == [] and v["ids"] == {"n": 12, "tags": 12, "pick": ""}, (v["trail"], v["tiles"], v["ids"]))
        send("party:ids")
        v = GF.tab_view(conf)
        check("pip party tab: the folded tile picks its cards whole", v["picks"] and v["picks"][0]["kind"] == "ids" and v["n"] == 12 and v["ids"]["pick"] == "in", v["picks"])
        send("party:up:0")
        v = GF.tab_view(conf)
        send("party:pick:0")
        v = GF.tab_view(conf)
        check("pip party tab: a tap picks a tile; picks gather at the foot, and the count is theirs, no more",
              [p["name"] for p in v["picks"]] == ["12 cards by question number", "Step1"] and v["tiles"][0]["pick"] == "in"
              and v["n"] == len(party_rows) and v["all"] == "", ([p["name"] for p in v["picks"]], v["n"]))
        send("party:out:0")
        v = GF.tab_view(conf)
        check("pip party tab: a pick tapped at the foot is left out; the count drops it", v["picks"][0]["out"] and v["n"] == len(GAME_ROWS), v["n"])
        send("party:drop:0")
        send("party:of:missed")
        v = GF.tab_view(conf)
        check("pip party tab: which of their cards narrows it (missed in the last 7 days), and says so in the search",
              v["of"] == "missed" and v["n"] == 5 and "rated:7:1" in v["search"] and conf["party"]["of"] == "missed", (v["n"], v["search"]))
        send("party:of:all")
        was = len(calls)
        send("party:find:" + urllib.parse.quote("renal ph"))
        check("pip party tab: typing in Find draws the matches in the map's place alone (the box keeps its focus)",
              evals and "pp-map" in evals[-1] and "Renal" in evals[-1] and "redraw" not in calls[was:], (evals[-1:], calls[was:]))
        v = GF.tab_view(conf)
        check("pip party tab: a match says where it sits", v["hits"] and v["hits"][0]["name"] == "Pharm" and v["hits"][0]["where"] == "Tag · Step1 › Renal", v["hits"][:1])
        send("party:hit:0")
        v = GF.tab_view(conf)
        check("pip party tab: a match tapped is picked, its tag's cards, named with its parent", [p["name"] for p in v["picks"]][-1] == "Renal › Pharm" and v["n"] >= 2, v["picks"])
        send("party:find:")
        send("party:by:deck")
        v = GF.tab_view(conf)
        check("pip party tab: by Decks, the decks, a deck's subdecks' cards in its tile; names escaped when drawn",
              [t["name"] for t in v["tiles"]] == ["Step 1", "Block <2>"] and v["tiles"][0]["n"] == len(GAME_ROWS) and v["tiles"][0]["kids"]
              and "Block &lt;2&gt;" in board.party_html(v) and "Block <2>" not in board.party_html(v), [t["name"] for t in v["tiles"]])
        cards, subs, _w = GF.scope()
        pharm = [c for c in cards if any(t.startswith("Step1::Renal::Pharm") for t in dict((r[0], r[4]) for r in party_rows)[c])]
        check("pip party tab: Host plays on the picks, each card marked with its pick for the table's vote, a card in two the narrower one's",
              set(subs.values()) == {"Step1", "Renal › Pharm"} and set(cards) == set(subs) and pharm and all(subs[c] == "Renal › Pharm" for c in pharm), set(subs.values()))
        send("party:clear")
        cards, subs, _w = GF.scope()
        check("pip party tab: nothing picked, the tiles on the map are the night, each its own (the vote's choices)",
              set(subs.values()) == {"Step 1", "Block <2>"} and len(cards) == len(party_rows), set(subs.values()))
        send("party:pick:1")
        send("party:keep")
        v = GF.tab_view(conf)
        check("pip party tab: Keep this pick keeps it (this profile's file), a button over the map", v["kept"] == ["Block <2>"], v["kept"])
        send("party:clear")
        send("party:kept:0")
        v = GF.tab_view(conf)
        check("pip party tab: a kept pick's button puts it back", [p["name"] for p in v["picks"]] == ["Block <2>"], v["picks"])
        send("party:forget:0")
        check("pip party tab: × forgets it", GF.tab_view(conf)["kept"] == [])
        send("party:search:" + urllib.parse.quote('"deck:Step 1"'))
        v = GF.tab_view(conf)
        check("pip party tab: an edited search is the pick, one chip", [p["kind"] for p in v["picks"]] == ["search"] and v["n"] == len(GAME_ROWS), v["picks"])
        send("party:game:links")
        check("pip party tab: a game's box picks the one the TV opens on (this computer's)", conf["party"]["game"] == "links" and GF.TAB["game"] == "links")
        send("party:game:nope")
        check("pip party tab: a game that isn't one changes nothing", GF.TAB["game"] == "links")
        # Host: the picks read here, the pack built, a table, the TV on the first game
        GF.Ops.start = staticmethod(lambda first, done: started.append((first, done)))
        send("party:host")
        check("pip party: Host plays the picks, the TV opening on the first game that runs; it says it's opening",
              started and started[0][0] in ("links", "trivia", "imposter") and GF.TAB["busy"] and GF.TAB["said"] == "Opening a table…", started)
        send("party:host")
        check("pip party: while it opens, another Host does nothing", len(started) == 1)
        started[0][1]("That's a lot of tables for one hour. Try again in a while.")
        check("pip party: a refusal ends the wait and is said on the tab", not GF.TAB["busy"] and GF.TAB["said"].startswith("That's a lot"))
        args, kw = GF._pack_rows()
        check("pip party: Host's read: the picks' cards (each with its pick), the cards around them, a pack that carries the picks",
              len(args[0]) == len(GAME_ROWS) and set(kw["subs"].values()) == {"Your search"} and kw["n"] == len(GAME_ROWS), (len(args[0]), kw["n"]))
        out = board.party_html(v)
        check("pip party tab, drawn: the games' boxes (their pictures, First up on one), the map, Of their cards, the picks, Host the first game",
              out.count('class="pp-gm g-') == 3 and out.count(" on\"") >= 1 and "pp-art" in out and 'id="pp-map"' in out and "Of their cards" in out
              and "Your search" in out and "duecrew:party:host" in out and "Try it with bots" not in out and "Host " in out, out[:500])
        check("pip party tab: Imposter's odd Pip isn't grey (Sam): rose, with its question mark", "#d0587f" in board._party_art("imposter") and "<i>?</i>" in board._party_art("imposter"))
        # the TV: open, its code on the tab; closed, back to the picks
        from due_crew.ui import game_night_tv as TV
        sigs = []
        tv_win = types.SimpleNamespace(destroyed=types.SimpleNamespace(connect=sigs.append))
        was_tv, was_site = TV.open_tv, dc.plan_flow.site_base
        TV.open_tv = lambda parent, site, payload: tv_win
        dc.plan_flow.site_base = lambda: "https://duecrew.com"
        try:
            GF._tv({"mode": "tv", "code": "RRJA", "key": "k", "pack": {}, "first": "links"})
        finally:
            TV.open_tv, dc.plan_flow.site_base = was_tv, was_site
        v = drawn[-1]
        send("party:copy")
        check("pip party: the TV open, the tab has its code and where phones join, once with its burst; Copy link copies it",
              GF.TAB["open"] == {"bots": False, "code": "RRJA", "url": "https://duecrew.com/t/RRJA"} and v["burst"]
              and not GF.tab_view(conf)["burst"] and clipped == ["https://duecrew.com/t/RRJA"], (GF.TAB["open"], v.get("burst"), clipped))
        tvh = board.party_html(dict(v, burst=True))
        check("pip party tab: once the TV's open, its code and Copy link, nothing to pick; the burst once",
              "On the TV &middot; RRJA" in tvh and "duecrew:party:copy" in tvh and "duecrew:party:host" not in tvh and 'class="pp burst"' in tvh)
        send("party:host")
        send("party:pick:0")
        check("pip party: with the TV open, Host and the map do nothing (one table at a time)", len(started) == 1)
        sigs[0]()
        check("pip party: the TV closed, the tab is back to the picks", GF.TAB["open"] is None and GF.tab_view(conf)["picks"])
        # Systems: Insights' map of a deck, picked the same way
        tiles = [{"key": "k1", "name": "Renal", "n": 10, "know": 72, "started": 8, "kids": [], "_cids": [r[0] for r in GAME_ROWS[:10]]},
                 {"key": "k2", "name": "Cardio", "n": 6, "know": None, "started": 0, "kids": [], "_cids": [r[0] for r in GAME_ROWS[10:16]]}]
        GF._sys_decks = lambda: [{"did": 1, "name": "Step 1"}, {"did": 3, "name": "Block <2>"}]
        was_ins = team_flow.insights
        team_flow.insights = lambda did, pid=None, exam="": {"map": tiles if did == 1 else [], "_map_know": {}}
        try:
            send("party:clear")
            send("party:by:sys")
            v = GF.tab_view(conf)
            send("party:pick:1")
            v2 = GF.tab_view(conf)
            send("party:deck:3")
            v3 = GF.tab_view(conf)
        finally:
            team_flow.insights = was_ins
        check("pip party tab: by Systems, Insights' own tiles for the deck picked; a pick says its deck; a deck that doesn't split says so",
              [t["name"] for t in v["tiles"]] == ["Renal", "Cardio"] and v["decks"][1]["name"] == "Block <2>"
              and v2["picks"][0]["name"] == "Cardio" and v2["picks"][0]["deck"] == "Step 1" and v2["n"] == 6
              and v3["tiles"] == [] and "doesn&rsquo;t split by system yet" in board.party_html(v3), (v["tiles"][:1], v2["picks"], v3["tiles"]))
        # round one's saved scopes read as kept picks
        with open(kept_file, "w", encoding="utf-8") as f:
            json.dump({"scopes": [{"name": "Renal and more", "scope": {"in": ["tag:Step1::Renal"], "out": ["deck:Block <2>"], "missed": 7}}]}, f)
        k = GF.kept()
        check("pip party: round one's saved scopes are kept picks now (in, out, which cards)",
              k == [{"name": "Renal and more", "picks": [{"by": "tag", "path": "Step1::Renal", "out": False}, {"by": "deck", "path": "Block <2>", "out": True}], "of": "missed"}], k)
    finally:
        (GF.shown, GF._col, GF._redraw, GF.cfg, GF.save_cfg, GF.Ops.start, GF._clip, GF.tooltip, dc.mw.col, GF._bg, GF._file,
         team_flow._know, _app.board_eval, GF._sys_decks, GF._sys_level, GF.near) = saved
        GF.TAB.update(busy=False, said="", open=None, burst=False, gen=None, fits={}, fitting=None, picks=[], corpus=None, levels={}, counts={})


def test_pip_party_only_from_its_tab_v395():
    """3.9.5 round three (Sam: "I do not want parties to be prompted from
    the today page. their only access should be from the pip party tab"):
    no Party on Today (a plan's date, today's misses), on Insights' map or
    in Browse's right-click; Tools › Due Crew › Pip Party… opens the tab.
    Sam: "find a place to mark pip party as beta": its tab, the one way in."""
    from due_crew import due as D, plan_flow as PF, gamenight_flow as GF
    T = "2026-10-07"
    base = {"pid": "p1", "uid": "u1", "plan": "MS2", "name": "Path 2", "opens": T, "seen": 18, "total": 42,
            "counted": True, "parts": [], "topics": [["Videos", [["Cardio", 0]]]], "rm": []}
    rv = {"due": 0, "done": 214, "whole": 214, "through": 214, "later": 0, "left": 0, "back": 0, "at": ""}
    v = dict(D.view(T, [], [], {}, reviews=rv), misses={"n": 23, "reviews": 214, "cids": [600, 601]})
    v["rows"] = v["rows"] + [D._date_row(base, {}, T)]
    tiles = [{"key": "a", "name": "Cardio", "n": 10, "know": 80, "started": 10, "kids": []},
             {"key": "b", "name": "Renal", "n": 6, "know": None, "started": 0, "kids": []}]
    ins = {"decks": [{"did": 30, "name": "Big Step 1"}], "did": 30, "exam": "", "view": {"map": tiles}}
    you = {"plans": None, "insights": ins, "party_on": True}
    today, insights = board.you_html({}, v, dict(you, tab="today")), board.you_html({}, v, dict(you, tab="insights"))
    check("pip party: Today and Insights say nothing of it, the tab open to me or not; its tab is there",
          ">Party</a>" in today and "Pip Party" not in today and not re.search(r"(?i)party:|Party &rsaquo;|missparty|planparty|insmapparty", today + insights)
          and "Path 2" in today and "insmapshare" in insights, today[-600:])
    folded = board.you_html({}, None, dict(you, tab="insights", folded=True))
    alone = board.you_html({}, None, dict(you, tab="party"))
    check("pip party: out of Beta (3.9.10, Sam's): no tab says Beta, with Due's lists or alone; "
          "the folded line keeps the names",
          all(">Party</a>" in h and 'class="du-beta"' not in h for h in (today, insights, alone))
          and "&middot; Party" in folded and "du-beta" not in folded and board.BETA_TABS == () and board.PARTY_TAB == ("party", "Party"),
          (today.count("du-beta"), alone.count("du-beta"), folded[-300:]))
    acts = []

    class Menu:
        def addSeparator(self):
            pass

        def addAction(self, label):
            acts.append(label)
            return types.SimpleNamespace(triggered=types.SimpleNamespace(connect=lambda f: None))
    saved = (PF.client, GF.shown)
    try:
        PF.client = lambda: types.SimpleNamespace(signed_in=True, session={"plans_authored": [], "plans": []})
        GF.shown = lambda: True
        PF.browser_menu(types.SimpleNamespace(selected_cards=lambda: [7, 8]), Menu())
    finally:
        PF.client, GF.shown = saved
    check("pip party: nothing in Browse's right-click", not any("party" in a.lower() for a in acts), acts)
    check("pip party: no way in but the tab (no send from elsewhere in the glue)",
          not hasattr(GF, "send") and not hasattr(GF, "from_insights") and hasattr(GF, "open_tab"))

def test_pip_party_for_everyone_v395():
    """3.9.5's release (Sam: "let's make it available to others now ... we'll
    keep it as beta"): the tab and Tools › Due Crew › Pip Party… for anyone
    signed in, a table for anyone signed in (ten an hour, twenty a day), the
    table page anyone's, every game at its own min; its tab still says Beta."""
    from due_crew import gamenight_flow as GF
    saved = GF.client
    try:
        got = []
        for signed_in, uid in ((True, "someone"), (True, "the-admins-uid"), (False, "someone")):
            GF.client = lambda s=signed_in, u=uid: types.SimpleNamespace(signed_in=s, user_id=u)
            got.append(GF.shown())
    finally:
        GF.client = saved
    check("pip party for everyone: the tab shows for anyone signed in, never signed out", GF.TESTERS is None and got == [True, True, False], got)
    src = {p: open(os.path.join(REPO, *p.split("/")), encoding="utf-8").read()
           for p in ("worker/src/table.ts", "site/src/index.ts", "site/public/table.js")}
    check("pip party for everyone: anyone signed in opens a table, the table page is anyone's, each game needs its own min",
          "export const ADMINS_ONLY = false;" in src["worker/src/table.ts"] and "const TABLE_ADMINS_ONLY = false;" in src["site/src/index.ts"]
          and "const FEW = Infinity;" in src["site/public/table.js"])
    check("pip party for everyone: a day's ceiling on tables beside the hour's",
          "TABLES_PER_DAY = 20" in src["worker/src/table.ts"] and "`tableday:${uid}`, TABLES_PER_DAY, 86400" in src["worker/src/table.ts"])
    check("pip party for everyone: and out of Beta since 3.9.10", "party" not in board.BETA_TABS)


def test_pip_party_can_be_hidden_v395():
    """3.9.5 (Sam: "make pip party something someone can unshow"): Pip
    Party is one of Settings › Board's tabs, hidden as the others are (this
    computer's hidden_tabs): no tab, nothing worked out for it, not on the
    folded line. Tools › Due Crew › Pip Party… brings it back, as a link to
    a hidden tab does; so does Reset board."""
    import due_crew as dc
    from aqt.deckbrowser import DeckBrowser
    from due_crew import due_flow, gamenight_flow as GF, settings_model as SM
    check("pip party hidden: Settings › Board hides it and shows it again, in the tabs' order",
          SM.change(["settabs", "party", "0"], {"hidden_tabs": ["plans"]}) == {"hidden_tabs": ["plans", "party"]}
          and SM.change(["settabs", "party", "1"], {"hidden_tabs": ["party"]}) == {"hidden_tabs": []}
          and SM.BOARD_DEFAULTS["hidden_tabs"] == [])
    shown_bd = board.settings_html({"tab": "board", "signed_in": True}, {"hidden_tabs": []})
    hidden_bd = board.settings_html({"tab": "board", "signed_in": True}, {"hidden_tabs": ["party"]})
    check("pip party hidden: its pill beside Decks, Squads, Plans and Insights, on or off as set",
          "duecrew:settabs:party:0" in shown_bd and ">Party</button>" in shown_bd and "duecrew:settabs:party:1" in hidden_bd,
          re.findall(r"settabs:\w+:\d", hidden_bd))
    conf = {"hidden_tabs": [], "due_tab": "party"}
    calls = []
    from due_crew import plan_flow, team_flow
    saved = (dc._swap, dc.cfg, dc.save_cfg, GF.shown, GF.tab_view, GF.cfg, GF.save_cfg, GF.app.swap, dc.mw.col, due_flow._today,
             plan_flow.morning_opened, team_flow.plan_lines)
    plan_flow.morning_opened, team_flow.plan_lines = (lambda: None), (lambda cards: None)
    dc._swap = lambda c, focus=None: None
    dc.cfg = GF.cfg = lambda: conf
    dc.save_cfg = GF.save_cfg = lambda c, **k: None
    GF.shown = lambda: True
    GF.tab_view = lambda c: calls.append("party") or {"games": []}
    GF.app.swap = lambda c: calls.append("swap")
    dc.mw.col = object()
    due_flow._today = lambda: "2026-10-30"
    try:
        on = dc._you(conf, None, {})
        dc._on_js(False, as_board("duecrew:settabs:party:0"), DeckBrowser())
        off = dc._you(conf, None, {})
        drawn = board.you_html({}, None, dict(off, tab="party"))
        folded = board.you_html({}, None, dict(off, tab="party", folded=True))
        check("pip party hidden: the click hides it; no tab, nothing worked out for it, not on the folded line",
              on["party_on"] is True and calls == ["party"] and conf["hidden_tabs"] == ["party"] and off["party_on"] is False
              and "Pip Party" not in drawn and "party:" not in drawn and "Pip Party" not in folded, (conf, calls, folded[-200:]))
        GF.open_tab()
        check("pip party hidden: Tools › Due Crew › Pip Party… shows it again, open on it",
              conf["hidden_tabs"] == [] and conf["due_tab"] == "party" and dc._you(conf, None, {})["party_on"] is True
              and calls[-2:] == ["swap", "party"], (conf, calls))
    finally:
        (dc._swap, dc.cfg, dc.save_cfg, GF.shown, GF.tab_view, GF.cfg, GF.save_cfg, GF.app.swap, dc.mw.col, due_flow._today,
         plan_flow.morning_opened, team_flow.plan_lines) = saved


def test_pip_party_keeps_its_socket_v395():
    """3.9.5 (Sam: "very frequent reloads on the website-end"): a table's
    socket said nothing while the room did nothing (the lobby, between
    rounds), Cloudflare closes a quiet socket, and a phone that slept lost
    its own: each drop a "Reconnecting…", a seat blinking on the TV, and a
    join counted. Now a quiet socket pings every beat (the table answers
    pong); one whose ping goes unanswered a whole beat is dropped and opened
    again; a phone woken or back online comes back at once; a moment's
    reconnect isn't said. Run on table.js's own wsClient in node, its clock
    and socket stood in for."""
    import shutil
    import subprocess
    if not shutil.which("node"):
        check("pip party socket: node runs it (skipped: no node)", True)
        return
    src = open(os.path.join(REPO, "site", "public", "table.js"), encoding="utf-8").read()
    a, b = src.index("const BEAT = 25000"), src.index("// ---------- the TV: holds the game")
    js = r"""
let now = 1000, tid = 0; const timers = [];
Date.now = () => now;
global.setTimeout = (f, ms) => { const id = ++tid; timers.push({ id, at: now + ms, f, every: 0 }); return id; };
global.setInterval = (f, ms) => { const id = ++tid; timers.push({ id, at: now + ms, f, every: ms }); return id; };
global.clearTimeout = global.clearInterval = (id) => { const i = timers.findIndex((t) => t.id === id); if (i >= 0) timers.splice(i, 1); };
function advance(ms) { const end = now + ms; for (;;) { timers.sort((x, y) => x.at - y.at); const t = timers[0]; if (!t || t.at > end) break; now = t.at; if (t.every) t.at += t.every; else timers.shift(); t.f(); } now = end; }
const sockets = [];
global.WebSocket = class { constructor(url) { this.url = url; this.readyState = 0; this.sent = []; sockets.push(this); } send(d) { this.sent.push(d); } close(code) { this.closedBy = code; this.readyState = 3; } };
global.location = { protocol: "https:", host: "duecrew.com" };
const on = {};
global.document = { visibilityState: "visible", addEventListener: (e, f) => { (on[e] = on[e] || []).push(f); }, removeEventListener: (e, f) => { on[e] = (on[e] || []).filter((g) => g !== f); } };
global.window = { addEventListener: (e, f) => { (on[e] = on[e] || []).push(f); }, removeEventListener: (e, f) => { on[e] = (on[e] || []).filter((g) => g !== f); } };
global.sessionStorage = { getItem: () => "abcdefghijklmnopqrstu", setItem() {} };
const warn = () => {}, clone = (v) => JSON.parse(JSON.stringify(v)), merge = (o, p) => Object.assign({}, o, p);
""" + src[a:b] + r"""
const out = {}, states = [];
const c = wsClient("ABCD", "", (st) => states.push(st));
const hi = (w) => { w.readyState = 1; w.onmessage({ data: JSON.stringify({ t: "hi", you: "p1", peers: [] }) }); };
const pings = (w) => w.sent.filter((x) => x === '{"t":"ping"}').length;
hi(sockets[0]);
advance(BEAT - 1); out.quietBeforeBeat = pings(sockets[0]);
advance(1); out.pingAtBeat = pings(sockets[0]);
sockets[0].onmessage({ data: '{"t":"pong"}' });
advance(BEAT); out.answeredKeeps = sockets.length === 1 && pings(sockets[0]) === 2;
advance(BEAT); out.unansweredDropped = sockets[0].closedBy === 3000;
advance(1000); out.openedAgain = sockets.length === 2; out.saidAfterASecond = states.includes("reconnecting");
hi(sockets[1]); advance(3000); out.neverSaid = !states.includes("reconnecting");
sockets[1].readyState = 3; sockets[1].onclose({ code: 1006 }); advance(1600); out.saidWhenLong = states.includes("reconnecting");
const w2 = sockets[sockets.length - 1]; w2.readyState = 3; w2.onclose({ code: 1006 });  // that try failed too: the next waits on the backoff
const n = sockets.length; (on.visibilitychange || []).forEach((f) => f()); out.wokeOpensAtOnce = sockets.length === n + 1;
hi(sockets[sockets.length - 1]); now += 60000;
document.visibilityState = "hidden"; const m = sockets.length; (on.visibilitychange || []).forEach((f) => f()); out.hiddenDoesNothing = sockets.length === m && pings(sockets[m - 1]) === 0;
document.visibilityState = "visible"; (on.visibilitychange || []).forEach((f) => f()); out.wokeStalePings = pings(sockets[m - 1]) === 1;
advance(WAKE_WAIT); out.wokeDeadReopens = sockets[m - 1].closedBy === 3000;
c.leave(); const k = sockets.length; advance(60000); out.leftStaysLeft = sockets.length === k && !(on.visibilitychange || []).length;
console.log(JSON.stringify(out));
"""
    r = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=60)
    got = json.loads(r.stdout or "{}") if r.returncode == 0 else {}
    check("pip party socket: quiet, a ping every beat (none before it); answered, the socket stays",
          got.get("quietBeforeBeat") == 0 and got.get("pingAtBeat") == 1 and got.get("answeredKeeps"), got or r.stderr[:400])
    check("pip party socket: a ping unanswered a whole beat drops it and opens another; a moment's reconnect is never said",
          got.get("unansweredDropped") and got.get("openedAgain") and not got.get("saidAfterASecond") and got.get("neverSaid"), got)
    check("pip party socket: a longer outage says Reconnecting…", got.get("saidWhenLong"), got)
    check("pip party socket: a phone woken comes back at once; hidden, nothing; woken on a stale socket, a ping, and no answer reopens it",
          got.get("wokeOpensAtOnce") and got.get("hiddenDoesNothing") and got.get("wokeStalePings") and got.get("wokeDeadReopens"), got)
    check("pip party socket: left, it stays left (no beat, no wake)", got.get("leftStaysLeft"), got)


def test_pip_party_the_table_votes_v395():
    """3.9.5 round three (Sam's v3, "At the party: the table votes"): Anki's
    pack lists tonight's picks (or its subjects), each with its cards, and
    marks every question, word and pair with its own. In the lobby the
    phones vote, the host's taps on the TV win, nothing chosen is all of
    it; the games play on the chosen part alone, the boxes' counts are
    theirs, and Trivia doesn't ask for a subject again."""
    import shutil
    import subprocess
    from due_crew import gamenight as G
    subs = {r[0]: r[4][0].split("::")[1] for r in GAME_ROWS}
    pack = G.build(GAME_ROWS, "test", seed=3, subs=subs)
    names = [x["name"] for x in pack["subs"]]
    check("pip party vote: the pack lists the picks, the most carded first, each with its cards (all of them, not the sample)",
          pack["subs"][:2] == [{"name": "Renal", "n": 10}, {"name": "Cardio", "n": 6}] and set(names) == {"Renal", "Cardio", "Neuro", "Pulm"}, pack["subs"])
    check("pip party vote: every question, pair and word it marks is one of them",
          {q["sub"] for q in pack["qs"]} <= set(names) and {p["sub"] for p in pack["twins"]} <= set(names) | {""}
          and set(pack["wsubs"].values()) <= set(names), ({q["sub"] for q in pack["qs"]}, pack["wsubs"]))
    bare = G.build(GAME_ROWS, "test", seed=3)
    check("pip party vote: nothing picked, the choices are the questions' subjects",
          [x["name"] for x in bare["subs"]] and {x["name"] for x in bare["subs"]} <= {q["sub"] for q in bare["qs"]}, bare["subs"])
    if not shutil.which("node"):
        check("pip party vote: node runs the vote (skipped: no node)", True)
        return
    src = open(os.path.join(REPO, "site", "public", "table.js"), encoding="utf-8").read()
    a, b = src.index("let D = null;"), src.index("// ---------- hubs")
    js = "const matchMedia = () => ({ matches: true });\n" + src[a:b].replace("let D = null;", "let D = " + json.dumps(pack) + ";", 1) + r"""
const names = Vote.subs(D).map((x) => x.name);
const R = Vote.only(D, ["Renal"]), D0 = D;
D = R; const t = Trivia.start(); D = D0;
console.log(JSON.stringify({ names, none: Vote.picked(names, null, [[], []]), voted: Vote.picked(names, null, [["Renal"], ["Renal", "Pulm", "Nope"]]),
  mine: Vote.picked(names, ["Cardio"], [["Renal"]]), cleared: Vote.picked(names, [], [["Renal"]]),
  rq: [...new Set(R.qs.map((q) => q.sub))], rt: [...new Set(R.twins.map((x) => x.sub))],
  rw: R.words.filter((w) => D.wsubs[w] && D.wsubs[w] !== "Renal").length, all: Vote.only(D, []) === D,
  counts: ORDER.map((id) => Vote.count(R, id)), whole: ORDER.map((id) => Vote.count(D, id)), trivia: t.ph, tq: [...new Set(t.qs.map((q) => q.sub))] }));
"""
    r = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=60)
    got = json.loads(r.stdout or "{}")
    check("pip party vote: the TV's helpers run in node", r.returncode == 0 and got, r.stderr[:400])
    if not got:
        return
    check("pip party vote: nothing voted is all of it; the phones' votes pick (one not offered is nothing); the host's taps win, even none",
          got["names"] == names and got["none"] == [] and got["voted"] == ["Renal", "Pulm"] and got["mine"] == ["Cardio"] and got["cleared"] == [], got)
    check("pip party vote: the games play on the chosen part alone (questions, pairs, words); all chosen, the whole pack",
          got["rq"] == ["Renal"] and set(got["rt"]) <= {"Renal"} and got["rw"] == 0 and got["all"] is True, got)
    check("pip party vote: the boxes count the chosen part", got["counts"][0] == len(got and [q for q in pack["qs"] if q["sub"] == "Renal"])
          and got["whole"] == [len(pack["qs"]), len(pack["twins"]), len(pack["words"])], (got["counts"], got["whole"]))
    check("pip party vote: after a vote, Trivia goes straight to its questions (no subject asked again)",
          got["trivia"] == "ask" and got["tq"] == ["Renal"], (got["trivia"], got["tq"]))
    tv = src[src.index("function TV(root, client, opt) {"):src.index("// ---------- a phone")]
    phone = src[src.index("function Phone(root, client, name) {"):src.index("// ---------- bots")]
    check("pip party vote: the lobby tells phones the choices' names, nothing more (no counts, no cards); a phone's vote is its own presence",
          "subs: names().length > 1 ? names() : []" in tv and "x.n" not in tv[tv.index("function publish()"):tv.index("// each seat's own part")]
          and "client.presence({ v: P.votes })" in phone and "What should we play on?" in phone and "What are we playing on?" in tv)
    check("pip party vote: Play plays the chosen part; the game Anki opened on is picked first; Go with the votes undoes the host's taps",
          "tonight();\n    const id = play()" in tv and "ORDER.includes(opt.first) ? opt.first" in tv and 'btn("Go with the votes", () => { T.mine = null;' in tv)

def test_pip_party_find_v395():
    """3.9.5 round three, Sam: "make sure the search works" and "as a
    search hasn't worked to open things". The tab's own script (dcParty:
    Find's typing, As a search, the and-N-more tile) never ran: a tab switch
    draws by innerHTML, which runs no <script>; it rides with the board's
    scripts now. Find, tried on a big shared deck's export (35k cards, 808k
    tags on cards, 45k tags): a word typed is the start of one ("renal" not
    in "adrenal"); a parent and its part both count ("Renal › Physiology"
    first, the most carded); "b&b" is B&B; a keystroke is string checks on
    an index made once (off the main thread when the tab draws)."""
    import time as _t
    from due_crew import app as _app, gamenight_flow as GF
    js = board.keep_me_in_view_js()
    check("find: the tab's script rides with the board's own, after every draw (a swap runs no <script>)",
          board.PARTY_JS in js and board.PARTY_JS not in board.keep_me_in_view_js(scripts=False) and "window.dcParty = {" in board.PARTY_JS)
    v = {"games": [], "by": "tag", "tiles": [{"key": "a", "name": "A", "n": 3, "know": None, "kids": True, "pick": ""}], "ofs": [("all", "all")],
         "of": "all", "picks": [], "n": 3, "all": "All of your tags", "search": '"tag:a"', "more": 4}
    out = board.party_html(v)
    check("find: the tab carries no script of its own; Find, As a search and and-N-more call dcParty",
          "<script" not in out and 'oninput="dcParty.find(this)"' in out and "dcParty.srch()" in out and "dcParty.focus()" in out, out[:300])
    full = {"FA::14_Renal::03_Physiology::07_ADH": [1, 2, 3, 4, 5, 6], "FA::14_Renal::03_Physiology::08_GFR": [7, 8, 9],
            "FA::08_Endocrine::02_Adrenal_steroids": [10, 11, 12, 13, 14, 15, 16, 17, 18, 19],
            "Sys::Renal::Physiology": [1, 2, 3, 20], "Other::Renal_Physiology_leaf": [21], "Big::B&B::04_Biochem": [30, 31],
            "Big::Bootcamp::Biochem": [32, 33, 34, 35], "QB::Renal::123456": [40], "QB::Renal::123457": [41]}
    rows = sorted({(c, 1) for cs in full.values() for c in cs})
    data = {"rows": rows, "know": {c: 0.8 for c, _d in rows}, "decks": {1: "Big Step 1"}, "full": full}
    saved = (dict(GF.TAB), GF._bg, GF._fit, GF.find)
    try:
        GF._fit, GF.find = (lambda: None), (lambda q: [])  # the counts and the quick build, not Find's business
        GF.TAB.update(gen=_app.generation, corpus=(_app.generation, _t.time(), data), levels={})
        names = lambda q: [(h["name"], h["n"]) for h in GF.hits(q)]
        rp = names("renal phys")
        check("find: a parent and its part both count, the most carded first; every word the start of one",
              rp[:2] == [("03 Physiology", 9), ("Physiology", 4)] and ("Renal Physiology leaf", 1) in rp, rp)
        check("find: renal isn't in adrenal", not any("Adrenal" in n for n, _k in names("renal")), names("renal"))
        check("find: what's typed as it is counts when it's more than words (b&b is B&B, not every b)",
              names("b&b")[0] == ("B&B", 2), names("b&b"))
        check("find: a question number is never a match", not any(n.isdigit() for n, _k in names("12345")), names("12345"))
        check("find: the index is made once a corpus", "find_ix" in data and GF._find_ix(data) is data["find_ix"])
        check("find: a pick from it is named with its parent, its running numbers off (Physiology alone could be anyone's)",
              GF.pick_name({"by": "tag", "path": "FA::14_Renal::03_Physiology"}) == "Renal › Physiology"
              and GF.pick_name({"by": "tag", "path": "Step1"}) == "Step1")
        made = []
        GF._bg = lambda job, done=None: made.append(job)
        data.pop("find_ix", None)
        GF.TAB.update(by="tag", at=[], picks=[], indexing=False)
        GF.tab_view({})
        check("find: the tab drawn, Find's index starts off the main thread (once)", len(made) == 1 and GF.TAB["indexing"], made)
        GF.tab_view({})
        check("find: ...and not twice while it's made", len(made) == 1)
    finally:
        GF.TAB.clear()
        GF.TAB.update(saved[0])
        GF._bg, GF._fit, GF.find = saved[1:]
        GF.TAB.update(gen=None, corpus=None, levels={}, indexing=False, counts={}, fits={}, fitting=None)

def test_pip_party_everyones_pip_v395():
    """3.9.5 round three (Sam: "make sure the user pips are showing up where
    they should"): a player is named with their Pip, in their seat's colour,
    everywhere: the lobby's seats and its votes, Imposter's order, who's in
    and its tally, Imposter's vote on a phone, Links' teams (each their own
    Pip; the team is its box's colour); and a phone's own Pip is its seat's,
    as the TV draws it (where it sat down, till a game seats it). The TV and
    every phone work out the order alike (seated)."""
    import shutil
    import subprocess
    src = open(os.path.join(REPO, "site", "public", "table.js"), encoding="utf-8").read()
    part = lambda a, b: src[src.index(a):src.index(b)]
    imp, links = part("const Imposter = {", "\nfunction fixRound"), part("const Links = {", "\n// Each game starts at its own min")
    tv, phone = part("function TV(root, client, opt) {", "// ---------- a phone"), part("function Phone(root, client, name) {", "// ---------- bots")
    check("pips: Imposter's order, who's in and its tally name each player with their Pip; a phone's vote too",
          "who(i, nm(i))" in imp and imp.count("who(i, nm(i))") >= 3 and "who(i, p.name(i))" in imp, imp[:200])
    check("pips: Links' teams, each player's own Pip (no team-coloured one for everyone)", "who(i, n)" in links and "seatPip(0," not in src)
    check("pips: the lobby's seats and the vote's voters are their Pips; the TV's seats are seated()'s order",
          "seatPip(i, `${clip(p.presence.n, 16) || \"Someone\"}'s Pip`)" in tv and "const players = () => seated(" in tv
          and "voters.map(([p, i]) => seatPip(i," in tv)
    check("pips: a phone's own Pip in its seat's colour, where it sat down till a game seats it",
          "seated(P.peers).findIndex((x) => x.peer === me)" in phone and "pip(mood, 40, at >= 0 ? seatTone(at) : null)" in phone and ", sat]);" in phone)
    if not shutil.which("node"):
        return
    a, b = src.index("let D = null;"), src.index("// ---------- hubs")
    js = "const matchMedia = () => ({ matches: true });\n" + src[a:b] + r"""
const P = (peer, t, extra) => Object.assign({ peer, presence: { r: "p", n: peer, t } }, extra || {});
const order = seated([P("c", 30), P("a", 10), { peer: "tv", presence: { r: "tv" } }, P("w", 5, { wait: true }), P("b", 10), { peer: "x", presence: { r: "p" } }]).map((p) => p.peer);
console.log(JSON.stringify({ order, dark: seatTone(1), wrap: seatTone(7) }));
"""
    r = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=60)
    got = json.loads(r.stdout or "{}")
    check("pips: seated is who sat down, in the order they did (a tie by id); not the TV, not one at the door, not one without a name",
          got.get("order") == ["a", "b", "c"], got or r.stderr[:300])
    check("pips: a seat's colour by the device's theme (night: the light one), round the six for a seventh",
          got.get("dark") == "#8fb0ff" and got.get("wrap") == "#8fb0ff", got)

def test_pip_party_pictures_play_v395():
    """3.9.5 round three (Sam: "add some animation to the trivia / imposter
    / links pieces"): each game's picture is still till pointed at (the
    tab's Pips are), then plays: Trivia's shapes pop in turn and Pip
    thinks, Imposter's two Pips bob and the odd one looks about with its ?
    wobbling, a wave crosses Links' board corner to corner. A box picked
    plays its picture once, on that draw alone. Nothing moves with Reduce
    motion; the logo's rule (transforms only) holds here too."""
    import re as _re
    from due_crew import gamenight_flow as GF
    css = board.DUE_CSS
    motion = css[css.index("@media (prefers-reduced-motion: no-preference)", css.index(".pp-art {")):]
    motion = motion[:motion.index("\n    }\n")]
    check("pictures: pointed at, each piece plays, and all of it under no-preference (nothing with Reduce motion)",
          all(k in motion for k in (".pp-gm:not(.thin):hover .pp-sh", "pp-think", "pp-bob", "pp-look", "pp-q", "pp-wave", "pp-chosen")), motion[:300])
    frames = _re.findall(r"@keyframes (pp-[a-z]+) \{(.*?)\} \}", motion)
    check("pictures: transforms only, so nothing in the box moves but the picture's own pieces",
          len(frames) == 7 and all(_re.sub(r"(transform: [^;]+;|none|[0-9%, ]+\{|\}| )", "", body) == "" for _n, body in frames), frames)
    check("pictures: Trivia's four shapes take turns; Links' squares each know their row and column",
          all(f"#due-crew .pp-sh.s{i} {{ --k: " in css for i in (1, 2, 3)) and board._party_art("links").count("style=\"--d:") == 25
          and 'style="--d:8"' in board._party_art("links") and board._party_art("imposter").count('class="pp-p') == 2)
    games = [{"id": "trivia", "label": "Trivia", "n": 40, "need": 10, "first": True, "just": True},
             {"id": "links", "label": "Links", "n": 40, "need": 25, "first": False, "just": False}]
    out = board.party_html({"games": games, "first": "trivia", "picks": [], "n": 40, "ofs": []})
    check("pictures: the box just picked plays once (.just); the others rest", 'class="pp-gm g-trivia on just"' in out and "g-links just" not in out, out[:400])
    saved = (GF._redraw, GF._keep_state, dict(GF.TAB))
    try:
        GF._redraw, GF._keep_state = (lambda: None), (lambda: None)
        GF.TAB.update(open=None, gen=GF.app.generation)
        GF.on_message(["duecrew", "party", "game", "links"])
        check("pictures: a game's box picked asks for its play on the next draw", GF.TAB.get("chose") == "links")
        GF.TAB.pop("chose", None)
        GF.on_message(["duecrew", "party", "game", "nope"])
        check("pictures: ...a game that isn't one asks for nothing", "chose" not in GF.TAB)
    finally:
        GF._redraw, GF._keep_state = saved[0], saved[1]
        GF.TAB.clear()
        GF.TAB.update(saved[2])

def test_browse_due_says_when_a_plan_opens_v395():
    """3.9.5 (Sam: "I want to be able to see if a card will be unsuspended
    by a plan in the due column"; his pick B, "no up next or your pace or
    leech or anything. just the date it will open then the plan"): in
    Browse, a suspended card a plan I follow opens on a day ahead says
    "Thu 5 Nov · Heme 2" in Due, the soonest plan's when two have it.
    Every other card keeps Anki's words: not suspended, a leech, not on a
    plan, a date already opened or skipped, my own pace (Sam: "let's pause
    on it"), a paused plan, a date that opens in slices; Notes mode too."""
    from due_crew import plan_flow as PF, plans as P
    T = "2026-10-30"
    units = [{"id": "u0", "opens": "2026-10-20"}, {"id": "u1", "opens": "2026-11-05"}, {"id": "u2", "opens": T},
             {"id": "u3", "opens": "2026-11-12"}, {"id": "u4", "opens": "2026-11-19", "even": True}, {"id": "u5", "opens": "2026-12-01"}]
    ahead = P.opens_ahead(units, {"u3": "sig", "u5": "skip:sig"}, T)
    check("opens: a plan's dates still to open, from today on, soonest first; not opened or skipped here, not one in slices",
          [u["id"] for _d, u in ahead] == ["u2", "u1"], ahead)
    check("opens: none at my own pace, while paused, or on a schedule that opens in slices",
          P.opens_ahead(units, {}, T, own=True) == [] and P.opens_ahead(units, {}, T, paused=True) == []
          and P.opens_ahead(units, {}, T, sched=True) == [])
    check("opens: the words are the day, then the plan (Sam's B); the year when it isn't this one",
          P.opens_words("2026-11-05", "Heme 2", T) == "Thu 5 Nov · Heme 2" and P.opens_words("2027-01-05", "Heme 2", T) == "Tue 5 Jan 2027 · Heme 2")
    plans = [{"id": "p1", "name": "Heme 2", "doc": {"units": units}},
             {"id": "p2", "name": "MS2 block 3", "doc": {"units": [{"id": "v1", "opens": "2026-11-03"}]}},
             {"id": "p3", "name": "My pace", "own": "own", "doc": {"units": [{"id": "w1", "opens": "2026-11-01"}]}}]
    cards = {"u1": {10, 11, 12, 13}, "u2": {14}, "v1": {11}, "w1": {15}, "u3": {16}}
    rows = {10: (-1, " heme "), 11: (-1, ""), 12: (0, ""), 13: (-1, " Leech heme "), 14: (-1, ""), 15: (-1, ""), 16: (-1, ""), 17: (-1, "")}

    class Idx:
        def __init__(self, col, did):
            pass

        def match(self, u, swap, doc):
            return set(cards.get(u["id"], ()))
    col = types.SimpleNamespace(db=types.SimpleNamespace(first=lambda q, cid: rows.get(cid)))
    saved = (PF.followed, PF._state_cfg, PF._deck_ok, P.DeckIndex, PF._today, PF.mw.col, P.own_pace)
    cols = ["noteFld", "template", "cardDue", "deck"]

    def due(cid, is_note=False, columns=cols, anki="(New #39026)"):
        row = types.SimpleNamespace(cells=tuple(types.SimpleNamespace(text=x) for x in ("Front", "Cloze 1", anki, "Big Step 1")))
        PF.browser_row(cid, is_note, row, columns)
        return row.cells[2].text
    try:
        PF.followed = lambda: plans
        PF._state_cfg = lambda c=None: {"p1": {"deck_id": 1, "applied": {"u3": "sig"}}, "p2": {"deck_id": 1}, "p3": {"deck_id": 1}}
        PF._deck_ok, P.DeckIndex, PF._today, PF.mw.col = (lambda c, d: True), Idx, (lambda: T), col
        P.own_pace = lambda p: p.get("own") == "own"
        PF.opens_reset()
        check("opens: a suspended card a plan opens on a day ahead says the day and the plan in Due",
              due(10) == "Thu 5 Nov · Heme 2" and due(14) == "Fri 30 Oct · Heme 2", (due(10), due(14)))
        check("opens: two plans have it: the soonest one's day and name", due(11) == "Tue 3 Nov · MS2 block 3", due(11))
        check("opens: Anki's words for a card not suspended, a leech, one on no plan, a date opened already, my own pace",
              [due(c) for c in (12, 13, 17, 16, 15)] == ["(New #39026)"] * 5, [due(c) for c in (12, 13, 17, 16, 15)])
        check("opens: Notes mode, or no Due column, leaves the row alone",
              due(10, is_note=True) == "(New #39026)" and due(10, columns=["noteFld", "template", "deck", "cardMod"]) == "(New #39026)")
        PF.followed = lambda: []
        check("opens: the days are kept while Browse is open (Browse opening again, or a morning's open, works them out again)",
              due(10) == "Thu 5 Nov · Heme 2")
        PF.opens_reset()
        check("opens: ...and worked out again after a reset", due(10) == "(New #39026)")

        def broken():
            raise RuntimeError("no deck")
        PF.followed = broken
        PF.opens_reset()
        PF._OPENS["said"] = False
        check("opens: never raises (Anki drops a row tip that does), and says so once", due(10) == "(New #39026)" and PF._OPENS["said"])
    finally:
        PF.followed, PF._state_cfg, PF._deck_ok, P.DeckIndex, PF._today, PF.mw.col, P.own_pace = saved
        PF.opens_reset()
        PF._OPENS["said"] = False
    src = srcs.glue_src()
    flow = srcs.flow_src()
    check("opens: Browse's rows ask the tip; Browse opening works the days out again; so does the morning's open",
          "gui_hooks.browser_did_fetch_row.append(plan_flow.browser_row)" in src and "plan_flow.opens_reset()" in src
          and "    opens_reset()  # 3.9.5" in flow[flow.index("def run(col, plan_list"):flow.index("def run(col, plan_list") + 2500])

def test_pip_party_no_repeats_v396():
    """3.9.6 (Sam: "imposter also gave my friends and I a repeat of a
    previously done item like three rounds after we saw it before"): a
    sitting remembers what it played, by name. Imposter plays a pair whose
    topics nobody's seen first, then a pair not played, and starts over only
    once all of them have been; Trivia's blocks and Links' boards draw what's
    new first the same way."""
    import shutil
    import subprocess
    if not shutil.which("node"):
        check("pip party no repeats: node runs the games (skipped: no node)", True)
        return
    src = open(os.path.join(REPO, "site", "public", "table.js"), encoding="utf-8").read()
    a, b = src.index("let D = null;"), src.index("// ---------- hubs")
    t = lambda w: {"t": w, "facts": ["x"]}
    twins = [{"part": "P", "a": t(x), "b": t(y)} for x, y in
             (("A1", "B1"), ("A1", "C1"), ("A2", "B2"), ("A3", "B3"), ("B2", "C2"), ("A4", "B4"), ("A5", "B5"))]
    qs = [{"q": f"Q{k}", "a": f"A{k}", "tag": "", "opts": [f"A{k}", "x", "y", "z"], "ans": 0} for k in range(35)]
    words = [f"W{k}" for k in range(60)]
    pack = {"twins": twins, "qs": qs, "words": words, "prompts": ["p"], "blacks": [], "whites": [], "draws": [], "scales": [], "subs": []}
    js = ("const matchMedia = () => ({ matches: true });\n" + src[a:b].replace("let D = null;", "let D = " + json.dumps(pack) + ";", 1) + r"""
const c = { N: 3, seats: [{}, {}, {}], A: [], here: () => true };
const imp = [];
for (let k = 0; k < 12; k++) { const S = Imposter.start(c); imp.push([S.a, S.b].sort().join("|")); }
const tri = [];
for (let k = 0; k < 4; k++) tri.push(Trivia.block(null).qs.map((q) => q.q));
const lnk = [];
for (let k = 0; k < 3; k++) lnk.push(Links.board().tiles);
console.log(JSON.stringify({ imp, tri, lnk }));
""")
    r = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=60)
    got = json.loads(r.stdout or "{}")
    imp = got.get("imp") or []
    topics = lambda ps: [w for p in ps for w in p.split("|")]
    # seven pairs over ten topics: the ones that share no topic come first, the rest before any pair plays again
    first = imp[:5]
    check("pip party no repeats: Imposter's first rounds never show a topic again while a pair of new ones is left",
          len(imp) == 12 and len(set(topics(first))) == len(topics(first)) == 10, (imp, r.stderr[:300]))
    check("pip party no repeats: no pair again till every pair has played, then it starts over",
          len(set(imp[:7])) == 7 and set(imp[:7]) == {"|".join(sorted([p["a"]["t"], p["b"]["t"]])) for p in twins}, imp)
    tri = got.get("tri") or []
    check("pip party no repeats: Trivia's blocks of ten draw new questions first (35: three blocks, then a fourth starts over)",
          len(tri) == 4 and all(len(x) == 10 for x in tri) and len(set(sum(tri[:3], []))) == 30
          and len(set(tri[3]) & set(sum(tri[:3], []))) == 5, tri)
    lnk = got.get("lnk") or []
    check("pip party no repeats: Links' second board is 25 new words; the third tops up from the first",
          len(lnk) == 3 and not set(lnk[0]) & set(lnk[1]) and len(set(lnk[2]) - set(lnk[0]) - set(lnk[1])) == 10, lnk)

def test_pip_party_tab_shows_first_v396():
    """3.9.6 (Sam: "the transition from any other tab to pip party takes a
    while, and clicks on bento sections also take a long time"): the tab
    shows at once, saying it's reading your cards, and reads them just after
    (mw.progress.single_shot); its redraws replace Pip Party's part of the
    board alone, never the whole board, and the Find box keeps its focus."""
    from due_crew import gamenight_flow as GF
    queued, evals, swaps, read = [], [], [], []
    conf = {"due_tab": "party", "party": {"by": "tag"}}
    saved = (GF.mw.progress if hasattr(GF.mw, "progress") else None, GF._warm, GF.level, GF.cfg, GF.app.board_eval, GF.app.swap,
             dict(GF.TAB))
    try:
        GF.mw.progress = types.SimpleNamespace(single_shot=lambda ms, fn, *a: queued.append((ms, fn)))
        GF.cfg = lambda: conf
        GF._warm = lambda: GF.TAB.get("warmed") is not None
        GF.level = lambda: read.append("level") or {"tiles": [], "trail": [], "ids": None, "where": "", "at": [], "by": "tag", "decks": [], "did": 0}
        GF.app.board_eval, GF.app.swap = evals.append, (lambda c: swaps.append(c))
        GF.TAB.update(gen=None, warmed=None, warming=False, open=None)
        v = GF.tab_view(conf)
        html = board.party_html(v)
        check("pip party tab shows first: the games and 'Reading your cards…', nothing read yet, the reading queued for after",
              v.get("loading") is True and [g["id"] for g in v["games"]] == [g for g, _l in GF.G.GAMES] and "Reading your cards&hellip;" in html
              and read == [] and len(queued) == 1 and queued[0][0] > 0, (v.get("loading"), read, queued))
        GF.tab_view(conf)
        check("pip party tab shows first: a second draw meanwhile doesn't queue the reading again", len(queued) == 1, queued)
        queued.pop()[1]()
        check("pip party tab shows first: the reading, then the tab drawn again in its place alone, never the whole board",
              read and evals and not swaps and "#due-crew .pp" in evals[-1] and "outerHTML" in evals[-1], (read, swaps, evals[-1:]))
        check("pip party tab shows first: what's typed in Find keeps its focus and caret through a redraw",
              "pp-find" in evals[-1] and "setSelectionRange" in evals[-1] and "i.focus()" in evals[-1])
    finally:
        (prog, GF._warm, GF.level, GF.cfg, GF.app.board_eval, GF.app.swap, tab) = saved
        if prog is None:
            try:
                del GF.mw.progress
            except AttributeError:
                pass
        else:
            GF.mw.progress = prog
        GF.TAB.clear()
        GF.TAB.update(tab)


def test_energy_and_security_review_v397():
    """3.9.7 (Sam: Anki at an Energy Impact of 2,400: "could we be causing
    this?", then "structurally simplify / make efficient / ensure security /
    speed"): a resting pointer isn't pointing; Pip Party's picked picture plays
    once; the dance floor's tick only while it dances; the board's stylesheet
    once a page; Magic search's window goes when closed; the room's cheer once
    a minute; no redirect followed with the session's token."""
    import shutil
    import subprocess
    import due_crew as dc
    from due_crew import app as A, rooms, together, room_model as rm, sev as SV
    from due_crew.app import _state
    from aqt.deckbrowser import DeckBrowser
    src = fakes.board_source()
    # -- a resting pointer isn't pointing --
    check("rest: every point-to-play loop reads the page's rest (--sv-hover), none is forever on its own",
          "--sv-on: infinite;" not in src and "--sv-on: infinite;" not in SV.CSS and src.count("--sv-on: var(--sv-hover, infinite);") == 6
          and ".sv:hover, .sv-slot:hover .sv { --sv-on: var(--sv-hover, infinite); }" in SV.CSS and ".dc-rest { --sv-hover: 1; }" in SV.CSS)
    check("rest: the watcher rides the Decks page's scripts (once a page) and the bars' widgets",
          SV.REST_JS in board.keep_me_in_view_js(True) and SV.REST_JS not in board.keep_me_in_view_js(False)
          and rm.widget_js("chip", {"x": 1}).startswith(SV.REST_JS) and "if (window.dcRest ||" in SV.REST_JS)
    if shutil.which("node"):
        run = r"""
        var L = {}, D = {}, T = [], cls = new Set();
        global.window = { addEventListener: function (e, f) { L[e] = f; } };
        global.document = { hidden: false, addEventListener: function (e, f) { D[e] = f; },
          documentElement: { classList: { add: function (c) { cls.add(c); }, remove: function (c) { cls.delete(c); },
                                           contains: function (c) { return cls.has(c); } } } };
        global.setTimeout = function (f, ms) { T.push([f, ms]); return T.length; };
        global.clearTimeout = function () {};
        eval(process.argv[1]);
        var out = [cls.has('dc-rest'), T[T.length - 1][1]];
        T[T.length - 1][0](); out.push(cls.has('dc-rest'));        // REST_S with no move: at rest
        var now = Date.now; Date.now = function () { return now() + 1000; };
        L.pointermove(); out.push(cls.has('dc-rest'));             // a move: awake
        L.blur(); out.push(cls.has('dc-rest'));                    // Anki not in front: at rest at once
        L.focus(); out.push(cls.has('dc-rest'));
        console.log(JSON.stringify(out));
        """
        r = subprocess.run(["node", "-e", run, SV.REST_JS], capture_output=True, text=True)
        check("rest, run: awake on load, at rest after REST_S still, awake on a move, at rest on blur, awake on focus",
              r.stdout.strip() == json.dumps([False, SV.REST_S * 1000, True, False, True, False]).replace(" ", ""), (r.stdout, r.stderr[-300:]))
    # -- Pip Party: picked, a picture plays once --
    once = src.index("#due-crew .pp-gm.just .pp-25 i { animation-iteration-count: 1; }")
    check("Pip Party: a picked game's picture plays once: its rule comes after every rule that plays it, and names each part as they do",
          all(src.index(x) < once for x in ("animation: pp-think", "animation: pp-bob", "animation: pp-look", "animation: pp-q", "animation: pp-wave"))
          and all(x in src[once - 400:once + 80] for x in (".pp-gm.just .pp-4 + .pp-p", ".pp-gm.just .pp-3 .pp-p", ".pp-gm.just .pp-odd i")))
    # -- the dance floor: the half-beat tick only while it dances --
    dj = board.DANCE_JS
    check("dance floor: the half-beat tick while it dances, a bubble's turn's while it rests; a resting pointer doesn't keep it dancing; "
          "no turns while Anki isn't in front",
          "function pace(ms)" in dj and "pace(TICK * SAY)" in dj and "(S.hover && !resting())" in dj
          and "!away() && !S.open && !folded(f)" in dj and "setInterval(tick, TICK)" not in dj)
    # -- the board's stylesheet, once a page --
    mine = '<div id="due-crew" class="dc-frame"><style>#due-crew { a: 1 }</style>\n<style>#due-crew b { c: 2 }</style><div>board</div></div>'
    body, css = board.split_css(mine)
    check("stylesheet: a board's leading stylesheets come off it, in their order",
          body == '<div id="due-crew" class="dc-frame"><div>board</div></div>' and css == "#due-crew { a: 1 }#due-crew b { c: 2 }"
          and board.split_css('<div id="due-crew">x</div>') == ('<div id="due-crew">x</div>', ""))
    key = board.css_key(mine)
    first, held = board.swap_js(mine), board.swap_js(mine, key)
    check("stylesheet: a swap sends it to a page without it (into #dc-css, just before the board), and not to one that holds it",
          json.dumps(css) in first and "CSS = null" in held and json.dumps(css) not in held and json.dumps(body) in held
          and "el.parentNode.insertBefore(st, el)" in held and "pycmd('duecrew:css|' + window.dcBK)" in held)
    mw = dc_mw()
    sent = []
    saved = (getattr(mw, "web", None), dc._board_html, dc._arrive_js, dc._play_cheers, together.show_luck_card,
             rooms.refresh_widgets, dict(_state), mw.state, A._decks[0])
    try:
        mw.web = types.SimpleNamespace(eval=sent.append)
        mw.state, A._decks[0] = "deckBrowser", True  # the Decks page is up
        dc._board_html = lambda c: mine
        dc._arrive_js = lambda: ""
        dc._play_cheers = lambda: None
        together.show_luck_card = lambda: None
        rooms.refresh_widgets = lambda: None
        _state.update(entries=[], wrapped_open=False, plans_midday=False, plans_morning=None)
        A.on_set_content(None, None)
        dc._on_did_render(None)
        dc._swap({})
        dc._swap({})
        A.on_set_content(None, None)  # another page
        dc._swap({})
        dc._on_did_render(None)  # the Decks screen drawn anew
        dc._swap({})
        dc._on_js(False, as_board("duecrew:css"), DeckBrowser())  # a page that lost it asks
        dc._on_js(False, "duecrew:css", type("Previewer", (), {})())  # a card's script can't
        _drawn, s1, s2, s3, _drawn2, s4, s5 = sent
    finally:
        mw.web, dc._board_html, dc._arrive_js, dc._play_cheers, together.show_luck_card, rooms.refresh_widgets = saved[:6]
        mw.state, A._decks[0] = saved[7], saved[8]
        _state.clear()
        _state.update(saved[6])
    has = lambda js: json.dumps(css) in js  # noqa: E731
    check("stylesheet, through the glue: the first swap on a page carries it, the next doesn't; another page, or the Decks screen "
          "drawn anew, gets it again; the page's ask (keyed, the board's) sends it once more",
          has(s1) and not has(s2) and "CSS = null" in s2 and has(s3) and has(s4) and has(s5) and len(sent) == 7, [has(x) for x in sent])
    # -- Magic search's window goes when it's closed --
    mwin = open(os.path.join(REPO, "due_crew", "ui", "magic_window.py"), encoding="utf-8").read()
    check("Magic search: closed, its window goes (its page and its deck's index with it), as the plan window does",
          "WA_DeleteOnClose" in mwin and "self.web.cleanup()" in mwin)
    # -- the room's cheer, once a minute --
    from due_crew import social
    cheered, said = [], []
    saved = (social._send_cheer, social.cheer_allowed, rooms.my_room, rooms.tooltip, dict(rooms._room_cheered), list(_state.get("entries") or []))
    try:
        social._send_cheer = lambda uid, name, emoji: cheered.append(uid)
        social.cheer_allowed = lambda e: e
        rooms.my_room = lambda: "r1"
        rooms.tooltip = said.append
        _state["entries"] = [{"user_id": "me", "you": True, "room": "r1"}, {"user_id": "dre", "name": "Dre", "you": False, "room": "r1"}]
        saved_members = rm.members
        rm.members = lambda entries, room: [("dre", "Dre", False), ("me", "Me", True)]
        rooms._room_cheered["at"] = 0.0
        rooms.cheer_room()
        rooms.cheer_room()
        rm.members = saved_members
    finally:
        social._send_cheer, social.cheer_allowed, rooms.my_room, rooms.tooltip = saved[:4]
        rooms._room_cheered.clear()
        rooms._room_cheered.update(saved[4])
        _state["entries"] = saved[5]
    check("security: the room's cheer once a minute, however it's sent (a card's script could learn the widget's key)",
          cheered == ["dre"] and said == ["Cheered just now."], (cheered, said))
    api = open(os.path.join(REPO, "due_crew", "backend", "api.py"), encoding="utf-8").read()
    check("security: no redirect is followed with the session's token", '"allow_redirects": False' in api)
    # -- the bars: what a page keeps goes again only when that page is drawn anew --
    class Sig:
        def __init__(self):
            self.fns = []

        def connect(self, f):
            self.fns.append(f)

        def fire(self):
            for f in self.fns:
                f()

    class Web:
        def __init__(self):
            self.loadStarted, self.sent = Sig(), []

        def eval(self, js):
            self.sent.append(js)

    top = Web()
    rooms._draw(top, ["the chip"])
    rooms._draw(top, ["the chip"])
    A.on_set_content(None, None)  # another view's page: the reviewer's, the Decks screen's
    rooms._draw(top, ["the chip"])
    sent_before_reload = len(top.sent)
    top.loadStarted.fire()  # the bar's own page anew
    rooms._draw(top, ["the chip"])
    plain = types.SimpleNamespace(sent=[])
    plain.eval = plain.sent.append
    rooms._draw(plain, ["x"])
    A.on_set_content(None, None)
    rooms._draw(plain, ["x"])
    init = srcs.glue_src()
    keep = {k: _state.get(k) for k in ("settings_tab", "closet_open", "wrapped_open")}
    try:
        _state.update(settings_tab=False, closet_open=False, wrapped_open=False)
        off, on = dc._board_off({"show_leaderboard": False}), dc._board_off({})
        _state["settings_tab"] = True
        off_in_settings = dc._board_off({"show_leaderboard": False})
    finally:
        _state.update(keep)
    check("board off: a refresh doesn't build Anki's Decks screen again (nothing of ours on it); its cheers play over it; "
          "Settings, the closet or Wrapped up are ours, so they're drawn",
          off and not on and not off_in_settings
          and 'elif _board_off(c) and mw.state == "deckBrowser":\n' in init and init.index("elif _board_off(c)") < init.index("_rerender()         # deck_browser_did_render"))
    check("bars: a widget goes once a page: another view's new page doesn't send the top bar's again (it sent 71 KB and "
          "restarted its Pip at every screen change); its own page anew does; a view that can't say counts every page, as before",
          sent_before_reload == 1 and len(top.sent) == 2 and len(plain.sent) == 2, (sent_before_reload, len(top.sent), len(plain.sent)))


def test_good_luck_card_on_a_refresh_v399():
    """3.9.9 (Sam: "not sure it did work for my last exam"): a crewmate's line
    for my exam morning came with a refresh, was kept for the card, and the
    card waited for the Decks screen to be drawn anew: a refresh redraws the
    board in place (or, the board off, nothing), and only a draw showed it.
    Mostly the line comes with the morning's first refresh, after Anki has
    drawn the Decks screen, so the card showed at the next draw, after a
    study session, if at all. The refresh that brings it shows it now, in
    both ways a refresh ends on the Decks screen; once, as before. (Checked
    in Anki's own engine too: the line sent, the card up, Thanks back.)"""
    import due_crew as dc
    from due_crew import app as A, closet_flow as CF, due_flow, rooms, together
    from due_crew.app import _state
    wrap = _patched_due_crew()
    labels = [(TODAY - datetime.timedelta(days=i)).isoformat() for i in range(7)]
    tomorrow = (TODAY + datetime.timedelta(days=1)).isoformat()
    mw = dc_mw()
    shown = []
    cl = types.SimpleNamespace(session={}, signed_in=True, user_id="me", display_name="Sam Caplan",
                               _save_session=lambda: None)

    def refresh(c, cheers):
        ents = [{"user_id": u, "name": u.title(), "you": u == "me", "paused": False, "decks": [], "days": {}}
                for u in ("me", "dre")]
        dc._commit({"entries": ents, "pending": [], "cheers": cheers, "my_code": "ABC", "my_friends": ["dre"]},
                   c, labels, tomorrow)

    line = {"from": "dre", "name": "Dre", "emoji": "\U0001F340", "note": "You've got this", "luck": True,
            "guid": "", "at": f"{TODAY.isoformat()}T07:00:00Z"}
    saved = (dc.client, together.client, dc._morning, dc._awaiting_phone, due_flow.after_refresh, due_flow._reviews,
             CF.check, dc.tooltip, dc._rerender, dc._swap, rooms.refresh_widgets, dc.account.saved_elsewhere,
             dc._play_cheers, dc._joy_show, A.board_eval, getattr(mw, "state", None), dict(_state))
    try:
        dc.client = together.client = lambda: cl
        dc._morning = lambda *a, **k: None
        dc._awaiting_phone = lambda: False
        due_flow.after_refresh = lambda: None
        due_flow._reviews = lambda: {"done": 12, "due": 0}
        CF.check = lambda today: []
        dc.tooltip = lambda *a, **k: None
        dc._rerender = dc._swap = rooms.refresh_widgets = dc._play_cheers = dc._joy_show = lambda *a, **k: None
        dc.account.saved_elsewhere = lambda at: None
        A.board_eval = shown.append
        mw.state = "deckBrowser"
        out = {}
        for way, c, on in (("board", {"exam_date": TODAY.isoformat()}, True),
                           ("off", {"exam_date": TODAY.isoformat(), "show_leaderboard": False}, False)):
            wrap = _patched_due_crew()  # a profile of its own: nothing kept from the way before
            cl.session = {}
            shown.clear()
            _state.update(board_shown=on, prev_label="", prev_counts={}, prev_streaks={}, days={}, decks={},
                          entries=None, labels=[], settings_tab=None, closet_open=False, wrapped_open=False)
            refresh(c, [line])
            first = list(shown)
            refresh(c, [line])
            out[way] = (first, list(shown), wrap._wrap_data().get("luck"))
        # no exam today: the line is a cheer, no card
        wrap = _patched_due_crew()
        cl.session = {}
        shown.clear()
        _state.update(board_shown=True, prev_label="", prev_counts={}, prev_streaks={}, days={}, decks={}, entries=None)
        refresh({"exam_date": tomorrow}, [line])
        ahead = (list(shown), wrap._wrap_data().get("luck"))
    finally:
        (dc.client, together.client, dc._morning, dc._awaiting_phone, due_flow.after_refresh, due_flow._reviews,
         CF.check, dc.tooltip, dc._rerender, dc._swap, rooms.refresh_widgets, dc.account.saved_elsewhere,
         dc._play_cheers, dc._joy_show, A.board_eval, mw.state) = saved[:16]
        _state.clear()
        _state.update(saved[16])
    for way in ("board", "off"):
        first, after, kept = out[way]
        check(f"good luck ({way}): the refresh that brings a line on my exam morning shows the card, with the line",
              len(first) == 1 and "Good luck today, Sam" in first[0] and "You've got this" in first[0]
              and kept and kept["shown"] is True, (way, len(first), kept))
        check(f"good luck ({way}): once; the next refresh doesn't show it again", after == first, len(after))
    check("good luck: a line for an exam tomorrow is kept for that morning, no card today",
          ahead[0] == [] and ahead[1] and ahead[1]["exam"] == tomorrow and ahead[1]["shown"] is False, ahead)


def test_first_answers_quick_read_v399():
    """3.9.9 (the slow card, Sam: "it's over 5-10 seconds"): each card's first
    answer was read with ease > 0 in the query, which visits every row of
    the deck's log (0.4 s on a 300,000-row log, once a day on the main
    thread, 1.5 s after the board draws: Reviews ahead's line, its track
    record, Insights by start week). first_answers reads each card's first
    row off the index and looks again only at a card whose first row isn't
    an answer: the same answer, in every case."""
    import sqlite3
    from due_crew.stats.queries import first_answers
    conn = fakes.make_collection(sqlite3.connect(":memory:"))
    conn.execute("CREATE INDEX ix_revlog_cid ON revlog (cid)")
    db = fakes.FakeDB(conn)
    t0 = 1_700_000_000_000
    for cid, did in ((1, 10), (2, 10), (3, 10), (4, 10), (5, 20), (6, 10)):
        fakes.add_card(conn, cid, did)
    fakes.add_review(conn, t0, cid=1)                         # an answer first
    fakes.add_review(conn, t0 + 9000, cid=1)
    fakes.add_review(conn, t0 + 100, ease=0, rtype=4, cid=2)  # Set Due Date first, then answers
    fakes.add_review(conn, t0 + 5000, cid=2)
    fakes.add_review(conn, t0 + 7000, ease=1, cid=2)
    fakes.add_review(conn, t0 + 200, ease=0, rtype=4, cid=3)  # only ever rescheduled: never answered
    fakes.add_review(conn, t0 + 300, cid=5)                   # another deck
    fakes.add_review(conn, t0 + 400, ease=0, rtype=4, cid=6)  # two manual rows, then an answer
    fakes.add_review(conn, t0 + 500, ease=0, rtype=4, cid=6)
    fakes.add_review(conn, t0 + 600, ease=2, cid=6)
    deck = "SELECT id FROM cards WHERE did IN (10) OR odid IN (10)"
    old = {int(c): int(t) for c, t in db.all(
        f"SELECT cid, min(id) FROM revlog WHERE ease > 0 AND cid IN ({deck}) GROUP BY cid")}
    got = first_answers(db, deck)
    check("first answers: the quick read gives what the filtered one did (a manual row first, never answered, "
          "another deck's, a card never seen)", got == old == {1: t0, 2: t0 + 5000, 6: t0 + 600}, (got, old))
    check("first answers: an empty deck reads as nothing", first_answers(db, "SELECT id FROM cards WHERE did = 99") == {})
    import inspect
    from due_crew import ahead_flow, team_flow
    srcs = inspect.getsource(ahead_flow) + inspect.getsource(team_flow)
    check("first answers: Reviews ahead, its track record and Insights by start week use it; no filtered read of a "
          "deck's whole log is left", srcs.count("first_answers(col.db, deck)") == 3
          and "min(id) FROM revlog WHERE ease > 0 AND cid IN ({deck})" not in srcs)
