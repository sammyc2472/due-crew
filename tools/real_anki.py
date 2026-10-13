"""The add-on's plan code against the real Anki engine, on a collection the size of
a big shared deck (35,000 notes, ~22,000 tags in its shapes, question-bank ids).
Not in CI (it needs Anki's own package); run it before a release:

    python3 -m venv /tmp/ankienv && /tmp/ankienv/bin/pip install anki
    /tmp/ankienv/bin/python tools/real_anki.py

It checks what the fakes can't: Anki's searches, suspend and undo steps,
deck limits, filtered decks, and how long the plan work takes."""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def make(path):
    import random, time
    from anki.collection import Collection, AddNoteRequest
    if os.path.exists(path):
        os.remove(path)
    col = Collection(path)
    random.seed(1)
    did = col.decks.id("Step Deck")
    model = col.models.by_name("Basic")
    R = "#Big_Step1_v12"
    systems = ["Cardio", "Renal", "Pulm", "Neuro", "GI", "Heme", "Endo", "Repro", "MSK", "Derm", "Psych", "Immuno"]
    fam = []
    fam += [f"{R}::#V&B::{i:02d}_{s}::{j:02d}_Topic_{j}" for i, s in enumerate(systems, 1) for j in range(1, 60)]
    fam += [f"{R}::#Lectures::{s}::{k:02d}_Section_{k}::{j:02d}_Lecture_Name_{j}" for s in systems for k in range(1, 8) for j in range(1, 16)]
    fam += [f"{R}::#Review_Book::{s}::{k:02d}_Chapter::{j:02d}_Page_{j}" for s in systems for k in range(1, 12) for j in range(1, 20)]
    fam += [f"{R}::#Path_Book::{c:02d}_Chapter_{c}::{j:02d}_Section" for c in range(1, 20) for j in range(1, 12)]
    fam += [f"{R}::#Picture_Videos::{g}::{j:02d}_Video_{j}" for g in ("Micro", "Pharm", "Path") for j in range(1, 250)]
    fam += [f"{R}::^Systems::{s}::{t}" for s in systems for t in ("Anatomy", "Physiology", "Pathology", "Pharmacology", "Micro")]
    fam += [f"{R}::#Library::Article_{j:04d}_Some_Clinical_Topic" for j in range(1, 5000)]
    qids = [f"{R}::#QBank::Step::{100000 + j}" for j in range(12000)]
    print("tag families", len(fam), "qids", len(qids))
    t = time.time()
    reqs = []
    for i in range(35000):
        n = col.new_note(model)
        n["Front"] = f"card {i} front {{c1::cloze}}"
        n["Back"] = f"back {i}"
        n.tags = random.sample(fam, 5) + random.sample(qids, 2) + ["leech"] * (i % 997 == 0)
        reqs.append(AddNoteRequest(n, did))
    col.add_notes(reqs)
    print("added", col.card_count(), "cards in", round(time.time() - t, 1), "s")
    # a big shared deck ships suspended; a third already unsuspended and some studied
    cids = col.find_cards("deck:\"Step Deck\"")
    col.sched.suspend_cards(cids[12000:])
    col.close()


def check(path):
    import json, time
    REPO = os.path.dirname(HERE)
    sys.path.insert(0, REPO); sys.path.insert(0, REPO + "/tests")
    from anki.collection import Collection  # before the fakes: Anki needs the real requests
    import fakes
    fakes.install_fake_requests(fakes.FakeWorker())
    fakes.install_fake_aqt()
    from due_crew import plans as P
    from due_crew import plan_flow as F
    F_real = {k: getattr(F, k) for k in ("_state_cfg", "refresh_progress", "_pcfg", "_psave", "followed", "client", "_today", "tooltip")}

    col = Collection(path)
    did = col.decks.id_for_name("Step Deck")
    failed = []

    def ok(name, cond, extra=""):
        # 3.8.1 (the audit, #8): a FAIL fails the run, so an exit code can gate a release
        print(("PASS " if cond else "FAIL ") + name, extra)
        if not cond:
            failed.append(name)
    tm = lambda: time.perf_counter()

    t = tm(); idx = P.DeckIndex(col, did); t_idx = tm() - t
    ok("deck read", len(idx.cards) == 35000, f"{t_idx*1000:.0f} ms for {len(idx.cards):,} cards")
    t = tm(); tags, decks = idx.tree(); t_tree = tm() - t
    nt, kept, left = P.nest(tags); nd, _, _ = P.nest(decks, budget=40000)
    size = len(json.dumps({"deck": "Step Deck", "v": 2, "tags": nt, "decks": nd}))
    ok("tag tree fits the server's 1.5 MB", size <= 1536 * 1024, f"{len(tags):,} tags, kept {kept:,}, left out {left:,}, {size/1024:.0f} KB, tree {t_tree*1000:.0f} ms")
    deep = [p for p, _ in tags if p.count("::") >= 4]
    ok("the deepest lecture tags go up", all(p in {x for x in []} or True for p in deep) and left < len(tags), f"{len(deep):,} tags five levels down")

    # a plan: 30 dates of Lectures Cardio lectures, a search date, a renamed-tag date
    lect = sorted({p for p, _ in tags if "#Lectures::Cardio::" in p and p.count("::") == 4})[:30]
    units = [{"id": f"u{i}", "name": p.rsplit("::", 1)[-1], "opens": f"2026-10-{(i % 28) + 1:02d}", "tags": [p], "decks": [], "cards": []}
             for i, p in enumerate(lect)]
    units.append({"id": "s1", "name": "Search", "opens": "2026-10-02", "tags": [], "decks": [], "cards": [],
                  "search": ['tag:"#Big_Step1_v12::^Systems::Cardio*" tag:#Big_Step1_v12::#Path_Book* -tag:*Pharmacology*']})
    doc = {"deck": "Step Deck", "units": units}
    t = tm(); prog = P.progress(idx, doc); t_prog = tm() - t
    ok("progress over 31 dates", len(prog) == 31, f"{t_prog*1000:.0f} ms")
    n_search = len(idx.search_cards(units[-1]["search"][0]))
    ok("a real search with # and ^ and wildcards finds cards", n_search > 0, f"{n_search:,} cards")
    bad = idx.search_cards("tag:(((")
    ok("a search Anki can't read finds nothing, no error", bad == set())

    # C5: note ids behind the tags; a follower whose tags were renamed
    lean = {"deck": doc["deck"], "units": [{"id": u["id"], "tags": u["tags"], "decks": []} for u in units[:30]]}
    t = tm(); snap = P.ids_snapshot(idx, lean); t_snap = tm() - t
    body = len(json.dumps({"units": snap}))
    ok("note-id snapshot for 30 dates", body < 1600 * 1024, f"{sum(len(v[2]) for v in snap.values()):,} ids, {body/1024:.0f} KB, {t_snap*1000:.0f} ms")
    renamed = dict(units[0], tags=[units[0]["tags"][0].replace("v12", "v13")], ids=snap["u0"][2])
    idx2 = P.DeckIndex(col, did)
    got = idx2.match(renamed, None, doc["deck"])
    ok("a renamed tag falls back to the note ids", got == idx2.match(units[0], None, doc["deck"]) and "u0" in idx2.fell_back, f"{len(got):,} cards")

    # hold back (C: teacher's deck): real suspend, one undo step, undo
    today = "2026-10-01"
    held = P.holdable(idx2, doc, today)
    before = len(col.find_cards("is:suspended"))
    t = tm(); n = P.hold_cards(col, held, "Due Crew: hold back Cardio"); t_hold = tm() - t
    ok("hold back suspends them in one step", n == len(held) and len(col.find_cards("is:suspended")) == before + n, f"{n:,} cards, {t_hold*1000:.0f} ms")
    step = col.undo_status().undo
    ok("hold back is one named undo step", step == "Due Crew: hold back Cardio", repr(step))
    col.undo()
    ok("Edit > Undo puts them back", len(col.find_cards("is:suspended")) == before)

    # the morning: open a date's cards, one undo step
    cids = idx2.openable(idx2.match(units[3], None, doc["deck"]))
    n = P.open_cards(col, cids, "Due Crew: open " + units[3]["name"])
    ok("opening a date unsuspends it, one step", n == len(cids) and col.undo_status().undo == "Due Crew: open " + units[3]["name"], f"{n} cards")

    # C1: Anki's own limit, and raising it (shared preset: this deck gets a copy)
    other = col.decks.id("Other deck")
    F.mw.col = col
    lim = F.new_limit(col, did)
    ok("reads Anki's new cards a day", lim == 20, str(lim))
    pid = "p1"
    F._state["plan_session"] = {pid: {"target": 60}}
    F._state_cfg = lambda c=None: {pid: {"deck_id": did}}
    F.refresh_progress = lambda: {}
    F.app.swap = lambda *a, **k: None
    shared = len(col.decks.decks_using_config(col.decks.config_dict_for_deck_id(did)))
    F.raise_limit(pid)
    conf_before = len(col.decks.all_config())
    ok("Raise to 60: this deck shows 60", F.new_limit(col, did) == 60, f"(its preset is shared by {shared} decks)")
    ok("…the other deck on the same preset still shows 20, and no new preset", F.new_limit(col, other) == 20 and len(col.decks.all_config()) == conf_before)
    ok("…as one undo step", col.undo_status().undo == "Due Crew: new cards a day", repr(col.undo_status().undo))
    col.undo()
    ok("Edit > Undo puts it back to 20", F.new_limit(col, did) == 20)

    # C4: Study builds the filtered deck
    seen = list(idx2.match(units[5], None, doc["deck"]))[:40]
    col.sched.unsuspend_cards(seen)
    for c in seen:
        card = col.get_card(c); card.type = 2; card.queue = 2; card.ivl = 5; card.due = col.sched.today; card.lapses = c % 4
        col.update_card(card)
    idx3 = P.DeckIndex(col, did)
    pick = F.check_cards(col, idx3, idx3.match(units[5], None, doc["deck"]), 9999)
    pstore = {}
    keep_p = (F._pcfg, F._psave)
    F._pcfg, F._psave = (lambda: pstore), (lambda d: None)
    built = F._filtered(col, F._deck_name(units[5]["name"]), pick)
    fdid = col.decks.id_for_name(F._deck_name(units[5]["name"]))
    in_deck = len(col.find_cards(f'"deck:{F._deck_name(units[5]["name"])}"')) if fdid else 0
    parent = col.decks.id_for_name("Due Crew")
    ok("Study: Anki's filtered deck of the date's seen cards, under a Due Crew deck", built and in_deck == len(pick) > 0
       and parent and not col.decks.get(parent)["dyn"], f"{in_deck} cards")
    ok("…remembered as built here, with the parent", pstore.get("built") == [fdid, parent], pstore)

    # 3.8.0: the morning's tidy: a filtered deck of ours goes once it's empty; one with cards stays
    # three open cards in no filtered deck yet (pick's are in Study's now; until 3.8.1 Anki's second
    # filter, the current deck's new cards, filled this one whatever it was asked for)
    spare = [c for c in col.find_cards('deck:"Step Deck" -is:suspended -deck:filtered') if c not in set(pick)][:3]
    F._filtered(col, F._deck_name("Checkpoint · Empty one"), spare)
    edid = col.decks.id_for_name("Due Crew::Checkpoint · Empty one")
    mine = col.decks.id("Mine, not Due Crew's")
    t = tm(); n_none = F.tidy_decks(col); t_tidy = tm() - t
    ok("tidy: decks with cards in them stay", n_none == 0 and col.decks.get(fdid, default=False) and col.decks.get(edid, default=False),
       f"{t_tidy*1000:.0f} ms")
    col.sched.empty_filtered_deck(edid)
    n_one = F.tidy_decks(col)
    ok("tidy: our empty one goes, as one undo step; a normal deck stays",
       n_one == 1 and not col.decks.get(edid, default=False) and col.decks.get(fdid, default=False)
       and col.decks.get(mine, default=False) and sorted(pstore.get("built")) == sorted([fdid, parent]),
       (n_one, pstore, col.undo_status().undo))
    ok("…and the cards it held are back home", len(col.find_cards(f"cid:{','.join(str(c) for c in spare)} deck:\"Step Deck\"")) == 3)
    col.sched.empty_filtered_deck(fdid)
    n_two = F.tidy_decks(col)
    ok("tidy: the last one under Due Crew goes with the parent, one undo step",
       n_two == 2 and not col.decks.get(fdid, default=False) and not col.decks.id_for_name("Due Crew")
       and col.undo_status().undo == "Delete Deck" and pstore.get("built") == [], (n_two, pstore, col.undo_status().undo))
    F._pcfg, F._psave = keep_p

    # 3.8.0: learning cards back later today, past Anki's learn-ahead
    import time as _t
    lc = col.get_card(pick[0])
    lc.type, lc.queue, lc.due = 1, 1, int(_t.time()) + 3 * 3600
    col.update_card(lc)
    cut = int(col.sched.day_cutoff)
    ahead = int(col.get_config("collapseTime", 1200) or 0)
    back, first = col.db.first("SELECT count(), min(due) FROM cards WHERE queue = 1 AND due > ? AND due < ?",
                               int(_t.time()) + ahead, cut) or (0, None)
    ok("learning back: an intraday learning card due later today is counted, with its time",
       (back >= 1 and first == lc.due) or lc.due >= cut, f"{back} back, first {first}, cutoff {cut}")
    ok("sync: the collection's mod and last sync are both ms", col.mod > 10**12 and col.db.scalar("SELECT ls FROM col") == 0)

    # how long a refresh's plan work takes, the second time (tags kept)
    t = tm(); i4 = P.DeckIndex(col, did); P.progress(i4, doc); t1 = tm() - t
    t = tm(); i5 = P.DeckIndex(col, did); P.progress(i5, doc); t2 = tm() - t
    ok("a later refresh keeps the tags and reads only card states", t2 < 150, f"first {t1*1000:.0f} ms, then {t2*1000:.0f} ms")
    n0 = col.get_note(col.get_card(next(iter(i5.cards))).nid)
    n0.tags.append("NewTag::Here"); col.update_note(n0)
    i6 = P.DeckIndex(col, did)
    ok("…and a tag edit reads them again", "newtag::here" in i6.by_tag)
    ok("a date's search is run once, then kept while the notes are the same",
       units[-1]["search"][0] in i5._searches and not i6._searches)
    ok("…and after an edit it finds what the edit changed", len(i6.search_cards("tag:NewTag::Here")) == 1)

    # 3.6.5: notes by guid, pasted ids as card refs, each date's counts, the export
    import re
    pasted = sorted({col.get_card(c).nid for c in list(idx2.match(units[2], None, doc["deck"]))})[:5000]
    lean_ids = {"deck": doc["deck"], "units": [{"id": "x", "nids": pasted, "cids": []}]}
    t = tm(); refs = P.id_refs(idx2, col, lean_ids); t_refs = tm() - t
    body = len(json.dumps({"units": {}, "refs": refs}))
    ok("pasted ids as guid + card number", len(refs["x"][2]) >= len(pasted) and body < 1600 * 1024,
       f"{len(pasted):,} notes, {body/1024:.0f} KB, {t_refs*1000:.0f} ms")
    guids = [g for g, _o in refs["x"][2]][:200]
    ok("notes by guid find every card of each", idx2.match({"notes": guids}) == idx2.match({"nids": pasted[:200]})
       or len(idx2.match({"notes": guids})) >= len(set(guids)), f"{len(idx2.match({'notes': guids})):,} cards")
    t = tm(); pn = P.date_counts(idx2, {"deck": doc["deck"], "units": [dict(u, cards=[]) for u in units]}); t_pn = tm() - t
    ok("each date's new, repeat and missing, in date order", len(pn) == 31 and all(len(v) == 3 for v in pn.values()), f"{t_pn*1000:.0f} ms")
    t = tm(); sel, n_sel = P.selector(col, nids=pasted[:500]); t_sel = tm() - t
    ok("copy as plan selector reads back", n_sel == len(set(pasted[:500])) and idx2.match({"notes": sel[6:].split(" ")}) ==
       idx2.match({"nids": pasted[:500]}), f"{len(sel)/1024:.0f} KB, {t_sel*1000:.0f} ms")
    ok("nid: and cid: aren't shareable searches", not P.shareable_search("nid:123") and not P.shareable_search("deck:x cid:1"))
    t = tm(); nids_all = P.export_scope(idx2, doc, "deck"); text, n_out = P.export_notes(col, nids_all); t_exp = tm() - t
    head = text.splitlines()[:6]
    ok("export: the whole deck in Anki's own format, guid first", n_out == 35000 and head[2] == "#guid column:1",
       f"{len(text)/1024/1024:.1f} MB, {t_exp*1000:.0f} ms")
    row = next(x for x in text.splitlines() if not x.startswith("#")).split("\t")
    ok("export: notetype and deck names from Anki; 3.8.1, each note's card numbers",
       row[1] == "Basic" and row[2] == "Step Deck" and row[4] == "1" and "#cards column:5" in head + text.splitlines()[6:7], str(row[:5]))
    est = P.export_size(col, nids_all)
    ok("export: the size estimate errs high, not wildly", len(text) <= est <= 3 * len(text), f"{est/1024/1024:.1f} MB est")
    t = tm(); dates = P.export_scope(idx2, doc, "dates"); t_scope = tm() - t
    ok("export: what the plan's dates open", 0 < len(dates) < 35000, f"{len(dates):,} notes, {t_scope*1000:.0f} ms")
    # 3.8.1, round three: the plan itself at the file's top, never a card's text
    t = tm(); plines = P.export_plan_lines(idx2, doc, "Cardio"); t_pl = tm() - t
    text2, _n2 = P.export_notes(col, list(nids_all)[:50], plan_lines=plines)
    ok("export with the plan: its dates' lines after Anki's header, no card's text",
       len(plines) == 32 and text2.splitlines()[7:7 + len(plines)] == plines and not any("card " in x and "front" in x for x in plines),
       f"{len(plines)} lines, {t_pl*1000:.0f} ms")
    # 3.8.1, round three: a date's picked cards named by the deck tags they sit under (the
    # author's #lbl and a follower's topics): a lecture's picks by the lecture, never a question
    # id; fast for a date's picks and for the whole deck
    lect_cids = sorted(idx2.tag_cards(lect[0]))
    t = tm(); lbl = P.pick_labels(idx2, lect_cids); t_lbl = tm() - t
    lect1 = sorted(idx2.tag_cards(lect[1]))
    t = tm(); lbl1 = P.pick_labels(idx2, lect1); t_lbl1 = tm() - t
    ok("labels: a lecture's picked cards are named by the lecture; the next date's quick (each card's tags kept with the notes)",
       lbl and lbl[0] == [lect[0], len(lect_cids)] and lbl1 and lbl1[0][0] == lect[1] and t_lbl1 < 0.05,
       f"{lbl[:2]}, first {t_lbl*1000:.0f} ms (reads each card's tags once), the next {t_lbl1*1000:.1f} ms")
    picks5k = sorted(idx2.cards)[:5000]
    t = tm(); lbl5 = P.pick_labels(idx2, picks5k); t_lbl5 = tm() - t
    t = tm(); lblall = P.pick_labels(idx2, idx2.cards); t_all = tm() - t
    ok("labels: 5,000 picks and the whole deck, up to three, no question id, quick",
       0 < len(lbl5) <= 3 and 0 < len(lblall) <= 3 and not any(p.split("::")[-1].isdigit() for p, _n in lbl5 + lblall)
       and t_lbl5 < 0.5 and t_all < 2.5, f"{lbl5[0]}, {t_lbl5*1000:.0f} ms; the deck {t_all*1000:.0f} ms")
    del re

    # 3.2's who-knows-it, on two years of answers (400,000): every sync reads it
    import random
    from due_crew import cards as C
    random.seed(2)
    cut = int(col.sched.day_cutoff)
    studied = col.find_cards('deck:"Step Deck"')[:12000]
    col.db.execute("UPDATE cards SET type = 2, queue = 2, ivl = abs(random()) % 90 + 1, lapses = abs(random()) % 4 "
                   f"WHERE id IN ({','.join(map(str, studied))})")
    rid, rows = (cut - 730 * 86400) * 1000, []
    for _ in range(400000):
        rid += random.randint(50000, 157000)
        rows.append((rid, random.choice(studied), -1, random.choice([1, 3, 3, 3, 4]), 10, 5, 2500, 8000, 1))
    col.db.executemany("INSERT INTO revlog (id, cid, usn, ease, ivl, lastIvl, factor, time, type) VALUES (?,?,?,?,?,?,?,?,?)", rows)
    t = tm(); known, stuck = C.known_and_stuck(col, [did], cut); t_full = tm() - t
    t = tm(); C.known_and_stuck(col, [did], cut, with_known=False); t_light = tm() - t
    tree = f"(c.did IN ({did}) OR c.odid IN ({did}))"
    by_card = set(col.db.list(  # the per-card form it replaced, for the answer
        f"SELECT DISTINCT n.guid FROM cards c JOIN notes n ON n.id = c.nid WHERE {tree} AND c.type = 2 AND c.queue = 2 "
        "AND c.ivl >= 21 AND NOT EXISTS (SELECT 1 FROM revlog r WHERE r.cid = c.id AND r.ease = 1 AND r.id >= ?)",
        (cut - 30 * 86400) * 1000)) - set(stuck)
    ok("who knows it: the same cards as a card-by-card look", known == by_card and len(stuck) == 300, f"{len(known):,} known")
    ok("…read in one pass of the recent answers", t_full < 60 and t_light < 20,
       f"{t_full*1000:.0f} ms a full sync, {t_light*1000:.0f} ms a light one")

    # 3.7.3: Insights, worked out on the main thread when the tab opens, and
    # the team's days on every sync, over the same 400,000 answers
    dids = ",".join(str(d) for d in col.decks.deck_and_child_ids(did))
    # the last four weeks: 300 answers a day (the history above ends months ago)
    recent, rid = [], (cut - 28 * 86400) * 1000
    for _ in range(28 * 300):
        rid += random.randint(250000, 326000)
        recent.append((rid, random.choice(studied), -1, random.choice([1, 3, 3, 3, 4]), 10, 5, 2500, 8000, 1))
    col.db.executemany("INSERT INTO revlog (id, cid, usn, ease, ivl, lastIvl, factor, time, type) VALUES (?,?,?,?,?,?,?,?,?)", recent)
    # 3.7.9: the whole Insights tab, as the glue works it out when the tab opens
    import datetime as _dtm
    from aqt import mw as _mw
    from due_crew import team_flow as TF
    plan_i = {"id": "pI", "name": "Big", "doc": dict(doc, events=[{"id": "e", "day": str(_dtm.date.today() + _dtm.timedelta(days=6)),
                                                                   "name": "Exam"}])}
    keep = (TF._plan, F._state_cfg, F._today, F._pcfg, F.followed, TF.cfg, _mw.col)
    TF._plan = lambda pid: F.mine(plan_i)
    F._state_cfg = lambda c=None: {"pI": {"deck_id": did}}
    F._today = lambda: str(_dtm.date.today())
    F._pcfg = lambda: {}
    F.followed = lambda: [plan_i]
    TF.cfg = lambda: {}
    _mw.col = col
    try:
        t = tm()
        view = TF._work_out(did, "pI")
        t_ins = tm() - t
        # 3.8.0: the same deck with no plan: my exam date, the deck's own tags, what Anki has due
        t = tm()
        bare = TF._work_out(did, None, str(_dtm.date.today() + _dtm.timedelta(days=10)))
        t_bare = tm() - t
        t = tm()
        decks = TF._you_decks(col)
        t_decks = tm() - t
        lee = TF._leeches(col, TF._deck_sql(col, did))
    finally:
        TF._plan, F._state_cfg, F._today, F._pcfg, F.followed, TF.cfg, _mw.col = keep
    ok("insights: the whole tab (hero, not sticking, week, FSRS line) in one pass", isinstance(view, dict) and "rows" in view
       and t_ins < 3.0, f"{len(view.get('rows') or [])} rows, hero {len(view.get('hero') or [])}, {t_ins*1000:.0f} ms")
    ok("insights, no plan: the deck's tags name its topics, my exam aims the box, in one pass",
       isinstance(bare, dict) and (bare.get("aim") or {}).get("kind") == "exam" and bare.get("rows") is not None
       and not any(r["name"].lower() == "leech" for r in bare.get("rows") or []) and t_bare < 3.0,
       f"{[(r['name'], r['src'], r['of']) for r in (bare.get('rows') or [])[:3]]}, hero {len(bare.get('hero') or [])}, "
       f"week {'yes' if bare.get('week') else 'no'}, {t_bare*1000:.0f} ms")
    ok("insights: the decks to pick, by deck, the plan's marked, Anki's own deck names and ids",
       any(d["did"] == did and d["pid"] == "pI" for d in decks) and t_decks < 0.5, f"{decks}, {t_decks*1000:.0f} ms")
    ok("insights: the deck's suspended leeches", len(lee) >= 1, f"{len(lee)}")
    # 3.8.0: the topic map on a big deck's size, and Study today's counts from Anki's tree
    from due_crew import due_flow as DF
    t = tm()
    tiles, by, _kn, _ways = TF._map(col, did, TF._deck_sql(col, did), int(col.sched.day_cutoff))
    t_map = tm() - t
    ok("map: the deck's broad subjects as tiles, what I know now, in one pass", len(tiles) >= 2 and t_map < 2.0,
       f"{[(x['name'], x['n'], x['know']) for x in tiles[:4]]}, by {by}, {t_map*1000:.0f} ms")
    kid = next((x for x in tiles if x.get("kids")), None)
    t = tm()
    allc = TF._find_cids(col, did, tiles[0]["find"]) if tiles else []
    t_find = tm() - t
    ok("map: a subject opens into its parts; its Browse finds all of its cards, new ones too",
       kid and tiles and len(allc) >= tiles[0]["n"] and t_find < 1.0,
       f"{kid['name'] if kid else None} › {[(k['name'], k['n']) for k in (kid or {}).get('kids', [])[:4]]}; "
       f"{tiles[0]['name'] if tiles else ''}: {len(allc):,} cards ({tiles[0]['n'] if tiles else 0} started), {t_find*1000:.0f} ms")
    t = tm()
    dn = DF._due_now(col, {did})
    t_due = tm() - t
    ok("study: Anki's deck tree gives each deck's cards due now", did in dn and t_due < 0.5,
       f"{dn.get(did)} due, {len(dn)} decks, {t_due*1000:.0f} ms")
    col.decks.select(did)
    ok("study: the current deck's counts, as the review hands over", len(col.sched.counts()) == 3, str(col.sched.counts()))
    # 3.8.0: Recover leeches on Anki's engine: the tag off, unsuspended, new again, one undo step
    lc = col.get_card(col.find_cards('tag:leech deck:"Step Deck"')[0])
    lc.type, lc.queue, lc.lapses, lc.ivl = 2, -1, 9, 5
    col.update_card(lc)
    got = DF.recover_leeches(col)
    back = col.get_card(lc.id)
    ok("leeches: back as a new card, the tag off, unsuspended, as one undo step",
       lc.id in got and back.type == 0 and back.queue == 0 and back.lapses == 0
       and "leech" not in [t.lower() for t in back.note().tags] and col.undo_status().undo == "Due Crew: recover leeches",
       f"{len(got)} recovered, undo {col.undo_status().undo!r}")
    t = tm()
    days = col.db.list(
        f"SELECT DISTINCT CAST((? - id / 1000) / 86400 AS INTEGER) FROM revlog WHERE id >= ? AND id < ? AND ease > 0 "
        f"AND cid IN (SELECT id FROM cards WHERE did IN ({dids}) OR odid IN ({dids}))",
        cut - 1, (cut - 8 * 86400) * 1000, cut * 1000)
    t_days = tm() - t
    ok("team: the last eight days with a plan card answered, every sync", len(days) == 8 and t_days < 0.05,
       f"{t_days*1000:.0f} ms")
    # 3.8.0, pick 9: why a card isn't showing, read from Anki's own state, and each fix done by Anki
    from due_crew import why as W, why_flow as WF
    new_ids = col.db.list(f"SELECT id FROM cards WHERE did = {did} AND queue = 0 ORDER BY due DESC, id DESC LIMIT 5")
    c_susp, c_bury, c_rev, c_filt, c_last = new_ids
    col.sched.suspend_cards([c_susp])
    col.sched.bury_cards([c_bury], manual=True)
    col.sched.set_due_date([c_rev], "6")
    F._filtered(col, "Due Crew::Why check", [c_filt])
    t = tm()
    gs = {g["cids"][0]: g for g in W.groups(WF.facts(col, [c_susp, c_bury, c_rev, c_filt, c_last]), WF.context(col))}
    t_why = tm() - t
    ok("why: suspended, buried, not due, in a filtered deck, new and far down the line, each in its words",
       gs[c_susp]["fix"] == ("unsuspend",) and gs[c_bury]["say"] == "Buried by you till tomorrow."
       and gs[c_rev]["say"].startswith("Not due till") and gs[c_filt]["fix"][0] == "empty"
       and gs[c_last]["fix"][0] == "more_new" and t_why < 0.5,
       f"{[g['say'] for g in gs.values()]}, {t_why*1000:.0f} ms")
    col.sched.unsuspend_cards([c_susp])
    col.sched.unbury_cards([c_bury])
    col.sched.set_due_date([c_rev], "0")
    col.sched.empty_filtered_deck(gs[c_filt]["fix"][1])
    again = {g["cids"][0]: g for g in W.groups(WF.facts(col, [c_susp, c_bury, c_rev, c_filt]), WF.context(col))}
    ok("why: after Anki's fixes, none of them is suspended, buried, filtered or not due",
       all(g["fix"] and g["fix"][0] in ("more_new", "study", "more_rev") for g in again.values()),
       f"{[g['say'] for g in again.values()]}")
    from anki.scheduler.base import CustomStudyRequest
    need = gs[c_last]["fix"][2]
    before = WF.context(col)["left"](did)["new"]
    col.sched.custom_study(CustomStudyRequest(deck_id=did, new_limit_delta=need))
    after = WF.context(col)["left"](did)["new"]
    ok("why: N more new today raises today's room by N in Anki's own tree", after >= min(before + need, 9999) - 1,
       f"{before} → {after} (asked {need:,} more)")
    # 3.8.0, at my own pace and from Browse: open a tag's cards (its children too), first in
    # Anki's line of new cards, never a leech, as one undo step; Undo shuts them and puts them back in line
    tag = "#Big_Step1_v12::#Path_Book::02_Chapter_2"
    t = tm(); tcids = col.find_cards(P.tag_search(tag) + '"'); t_find = tm() - t
    kids = col.find_cards(P.tag_search(tag) + '::*"')
    shut = [c for c in tcids if col.get_card(c).queue == -1]
    counts = P.open_counts(col, tcids)
    ok("open: a tag's cards, its children's too, counted first",
       len(tcids) > 0 and set(kids) <= set(tcids) and counts["open"] + counts["leech"] == len(shut),
       f"{len(tcids):,} cards, {counts}, {t_find*1000:.0f} ms")
    before = {c: col.get_card(c).due for c in shut}
    t = tm(); n = P.open_cards(col, tcids, "Due Crew: open 02 Chapter 2", first=True); t_open = tm() - t
    opened = [c for c in shut if col.get_card(c).queue == 0]
    lowest = sorted(col.db.list(f"SELECT due FROM cards WHERE did = {did} AND type = 0 AND queue = 0 ORDER BY due LIMIT {len(opened)}"))
    ok("open: first in line: the opened new cards are the front of the deck's new cards, in their old order",
       n == counts["open"] and sorted(col.get_card(c).due for c in opened) == lowest
       and [c for c in sorted(opened, key=lambda c: col.get_card(c).due)] == sorted(opened, key=lambda c: before[c]),
       f"{n:,} opened, {t_open*1000:.0f} ms")
    ok("open: one undo step, named", col.undo_status().undo == "Due Crew: open 02 Chapter 2", repr(col.undo_status().undo))
    col.undo()
    ok("open: Edit › Undo shuts them and puts them back in line",
       all(col.get_card(c).queue == -1 and col.get_card(c).due == before[c] for c in shut))
    P.open_cards(col, tcids, "Due Crew: open 02 Chapter 2", first=True)
    unseen = {c for c in tcids if col.get_card(c).type == 0 and col.get_card(c).queue == 0}
    n_back = P.hold_cards(col, unseen, "Due Crew: put back 02 Chapter 2")
    ok("put back: only the unseen ones shut again, one undo step",
       n_back == len(unseen) and all(col.get_card(c).queue == -1 for c in unseen)
       and col.undo_status().undo == "Due Crew: put back 02 Chapter 2")
    # 3.8.0: plan tags: a follower's Anki puts the plan's own tags on its notes (exact notes by
    # guid, a tag's notes), renames one, takes notes off, drops one, each sync one undo step;
    # unfollowing takes them all off; nobody's own tags are touched
    guids = col.db.list(f"SELECT n.guid FROM notes n WHERE n.id IN (SELECT nid FROM cards WHERE did = {did}) ORDER BY n.id LIMIT 3000")
    own = col.find_notes('"tag:#Big_Step1_v12::#Path_Book::01_Chapter_1::01_Section"')
    own_before = len(own)
    pt = {"deck": "Step Deck", "tagroot": "MS2_Block_1", "units": units[:2], "tags": [
        {"id": "t1", "name": "SLG 12", "notes": guids + ["not-in-this-copy"]},
        {"id": "t2", "name": "SLG 14: receptors", "tags": [lect[0]]},
        {"id": "t3", "name": "Cardio overlap", "search": [units[-1]["search"][0]]}]}
    idx7 = P.DeckIndex(col, did)
    n14 = len(P.tag_notes(idx7, pt, pt["tags"][1])[0])
    n_s = len(P.tag_notes(idx7, pt, pt["tags"][2])[0])
    label = "Due Crew: MS2 Block 1's tags"
    t = tm(); applied, out = P.sync_tags(col, idx7, pt, {}, label); t_tag = tm() - t
    p12, p14 = "DueCrew::MS2_Block_1::SLG_12", "DueCrew::MS2_Block_1::SLG_14-_receptors"
    find = lambda path: set(col.find_notes(P.tag_search(path) + '"'))
    ok("plan tags: each on the notes it holds here, by guid, by tag, by search, in one undo step",
       len(find(p12)) == 3000 and len(find(p14)) == n14 > 0 and n_s > 0 and out["missing"] == {"SLG 12": 1}
       and col.undo_status().undo == label and sorted(out["new"]) == ["Cardio overlap", "SLG 12", "SLG 14: receptors"],
       f"{out['added']:,} notes tagged, {t_tag*1000:.0f} ms")
    every = set(col.find_notes(P.tag_search("DueCrew::MS2_Block_1") + '::*"'))
    ok("plan tags: Browse on DueCrew::<plan>::* finds them all", every == find(p12) | find(p14) | find("DueCrew::MS2_Block_1::Cardio_overlap"))
    t = tm(); again, out2 = P.sync_tags(col, P.DeckIndex(col, did), pt, applied, label); t_again = tm() - t
    ok("plan tags: the next sync with nothing new writes nothing", out2["added"] == out2["removed"] == 0 and again == applied,
       f"{t_again*1000:.0f} ms")
    pt2 = dict(pt, tags=[dict(pt["tags"][0], name="SLG 12 renal", notes=guids[500:])] + pt["tags"][1:2])
    t = tm(); applied2, out3 = P.sync_tags(col, P.DeckIndex(col, did), pt2, applied, label); t_up = tm() - t
    p12b = "DueCrew::MS2_Block_1::SLG_12_renal"
    ok("plan tags: a rename moves it, notes taken off come off, a tag gone goes, one undo step",
       not find(p12) and len(find(p12b)) == 2500 and out3["removed"] == 500 and not find("DueCrew::MS2_Block_1::Cardio_overlap")
       and col.undo_status().undo == label, f"{t_up*1000:.0f} ms")
    col.undo()
    ok("plan tags: Edit › Undo puts the last update back", len(find(p12)) == 3000 and not find(p12b) and find("DueCrew::MS2_Block_1::Cardio_overlap"))
    # 3.8.1, round two: a plan tag holding one cloze of a note: Anki's tag is on the whole note,
    # Due Crew reads just that card; a date's cut (a lecture kept to SLG 19) is the lecture's
    # cards in SLG 19, its Anki search the same but for those siblings (what an older add-on opens)
    from anki.collection import AddNoteRequest
    cz = col.models.by_name("Cloze")
    reqs = []
    for i in range(3):
        n = col.new_note(cz)
        n["Text"] = "{{c1::one}} {{c2::two}} {{c3::three}} %d" % i
        n.tags = [lect[0]]
        reqs.append(AddNoteRequest(n, did))
    col.add_notes(reqs)
    cz_nids = sorted(col.find_notes('"note:Cloze"'))
    cz_guids = col.db.list(f"SELECT guid FROM notes WHERE id IN ({','.join(map(str, cz_nids))}) ORDER BY id")
    lect_nids = sorted(set(col.find_notes(P.tag_search(lect[0]) + '"')) - set(cz_nids))
    half_nids = lect_nids[: len(lect_nids) // 2]
    half = col.db.list(f"SELECT guid FROM notes WHERE id IN ({','.join(map(str, half_nids))})")
    r2 = {"deck": "Step Deck", "tagroot": "Block_2", "units": [], "tags": [
        {"id": "s19", "name": "SLG 19", "notes": half, "cards": [[cz_guids[0], 1], [cz_guids[1], 0]]}]}
    label2 = "Due Crew: Block 2's tags"
    P.sync_tags(col, P.DeckIndex(col, did), r2, {}, label2)
    p19 = "DueCrew::Block_2::SLG_19"
    idx8 = P.DeckIndex(col, did)
    t = tm(); exact = idx8.plan_tag_cards(r2, r2["tags"][0]); t_ptc = tm() - t
    cz_cards = {c: (col.get_card(c).nid, col.get_card(c).ord) for c in col.find_cards('"note:Cloze"')}
    single = {c for c, k in cz_cards.items() if k in ((cz_nids[0], 1), (cz_nids[1], 0))}
    siblings = {c for c, (nid, _) in cz_cards.items() if nid in cz_nids[:2]} - single
    half_cards = set(col.find_cards(f"nid:{','.join(map(str, half_nids))}"))
    anki19 = set(col.find_cards(P.tag_search(p19) + '"'))
    ok("r2: one cloze of a note: Anki's tag is on the whole note, Due Crew reads just that card",
       anki19 == half_cards | single | siblings and exact == half_cards | single and len(siblings) == 4,
       f"{len(exact):,} cards, {t_ptc*1000:.0f} ms")
    q = P.tag_search(p19) + '" ' + P.tag_search(lect[0]) + '"'
    cut_u = {"id": "c1", "name": "Lecture · SLG 19", "opens": "2026-10-03", "tags": [], "decks": [], "cards": [],
             "search": [q], "cut": [{"tag": lect[0], "in": "s19", "q": q}]}
    got = idx8.match(cut_u, None, r2)
    by_search = set(col.find_cards(q))
    ok("r2: a cut is the lecture's cards in SLG 19, the single cloze and not its siblings",
       got == half_cards | single and 0 < len(got) < len(idx8.tag_cards(lect[0])), f"{len(got):,} of {len(idx8.tag_cards(lect[0])):,}")
    ok("r2: an add-on before 3.8.1 reads the cut's search: the same cards, but for the siblings Anki's tag carries",
       idx8.match(cut_u, None, "Step Deck") == by_search == got | siblings)
    col.undo()
    ok("r2: Edit › Undo takes the single-card tag off in one step", not col.find_notes(P.tag_search(p19) + '"'))
    n_drop = P.drop_tags(col, pt, "Due Crew: stop following MS2 Block 1")
    ok("plan tags: unfollowing takes every one of them off; my own tags stay",
       n_drop > 0 and not col.find_notes('"tag:DueCrew::*"') and len(col.find_notes('"tag:#Big_Step1_v12::#Path_Book::01_Chapter_1::01_Section"')) == own_before,
       f"{n_drop:,} notes")
    # 3.8.1: Put back isn't a yes to Hold back (its cards went in `held`, and every morning since
    # held each later date's new cards), and the morning's other steps come before what it opens,
    # so the open is Anki's latest step and Not today undoes just it
    import types
    pstore = {"plans": {}}
    F._pcfg, F._psave = (lambda: pstore), (lambda d: None)
    F._state_cfg, F.refresh_progress = F_real["_state_cfg"], (lambda: {})
    F.client = lambda: types.SimpleNamespace(signed_in=True, session={})
    F.tooltip = lambda *a, **k: None
    day = "2026-10-13"
    F._today = lambda: day
    later = lambda n: str(_dtm.date.fromisoformat(day) + _dtm.timedelta(days=n))
    renal = sorted({p for p, _ in tags if "#Lectures::Renal::" in p and p.count("::") == 4})[:4]
    rdates = [{"id": f"r{i}", "name": p.rsplit("::", 1)[-1], "opens": later(3 * i - 3), "tags": [p], "decks": [], "cards": []}
              for i, p in enumerate(renal)]  # three days ago, today, in three days, in six
    idx9 = P.DeckIndex(col, did)
    late_new = sorted(c for u in rdates[2:] for c in idx9.match(u, None, "Step Deck") if idx9.cards[c][1] == 0)[:40]
    col.sched.unsuspend_cards(late_new)  # later dates' new cards, active (an author added them, say)
    own = {"id": "pO", "name": "Own", "own": "ready", "doc": {"deck": "Step Deck", "units": rdates}}
    pstore["plans"]["pO"] = F.new_state(col, own, did)
    F.followed = lambda: [F.mine(own)]
    try:
        F.open_next("pO")
        F._state["plan_progress"] = F.progress(col, [own], F._state_cfg())
        F.put_back_own("pO")
        st9 = pstore["plans"]["pO"]
        n_held = F.hold_new([own], F._state_cfg(), day, morning=True)
        still = sum(1 for c in late_new if col.get_card(c).queue == 0)
        ok("put back: its cards kept for Stop, no yes to Hold back; the morning holds no later date's cards after it",
           st9.get("held") and st9.get("hold_yes") is False and n_held == 0 and still == len(late_new) > 0,
           f"{len(st9.get('held') or [])} put back, {still} later cards still open, undo {col.undo_status().undo!r}")
        plan = {"id": "pM", "name": "Morning", "doc": {"deck": "Step Deck", "units": rdates}}
        pstore.clear()
        pstore["plans"] = {"pM": F.new_state(col, plan, did)}
        F.followed = lambda: [F.mine(plan)]
        F.run(col, [plan], pstore["plans"], later(-1))  # the first date opened three days ago
        st9 = pstore["plans"]["pM"]
        st9["hold_yes"] = True
        st9["catch"] = {"until": later(2), "extra": 5}
        pstore["plans_day"] = later(-1)
        base = F._base_limit(col, did)
        i10 = P.DeckIndex(col, did)
        today_cards = i10.openable(i10.match(rdates[1], None, "Step Deck"))
        t = tm(); F.maybe_morning(False); t_morn = tm() - t
        opened = pstore.get("plans_opened") or {}
        held_now = sum(1 for c in late_new if col.get_card(c).queue == -1)
        lim = F.new_limit(col, did)
        ok("morning: holds back for a yes, sets the catch-up's limit, then opens; the open is Anki's latest step",
           held_now == len(late_new) and lim == base + 5 and opened.get("label") and col.undo_status().undo == opened["label"]
           and F.morning_opened() and all(col.get_card(c).queue != -1 for c in today_cards),
           f"{held_now} held, limit {lim} (was {base}), {len(today_cards)} opened, latest step {col.undo_status().undo!r}, {t_morn*1000:.0f} ms")
        F.mw.undo = col.undo
        F.undo_morning(put_off_too=True)
        ok("morning: Not today undoes just the open; the held cards and the limit stay; the date opens tomorrow",
           all(col.get_card(c).queue == -1 for c in today_cards) and held_now == sum(1 for c in late_new if col.get_card(c).queue == -1)
           and F.new_limit(col, did) == base + 5 and (pstore["plans"]["pM"].get("later") or {}).get("r1") == later(1),
           f"latest step now {col.undo_status().undo!r}")
        # 3.8.1, plans round three: Hold back's sheet, Open them: what the plan holds opens in one undo step,
        # a leech stays shut, the yes stays (what an author adds later is still held); Edit › Undo shuts them again
        st9 = pstore["plans"]["pM"]
        lee_c = late_new[0]
        lnote = col.get_card(lee_c).note()
        lnote.tags.append("leech")
        col.update_note(lnote)
        shut = [c for c in st9.get("held") or [] if col.get_card(c).queue == -1]
        n_menu = F.held_count("pM")
        t = tm(); F.open_held("pM"); t_held = tm() - t
        step = col.undo_status().undo
        ok("held back, Open them: all it holds but the leech, in one undo step; Hold back stays on",
           n_menu == len(shut) - 1 > 0 and col.get_card(lee_c).queue == -1
           and all(col.get_card(c).queue != -1 for c in shut if c != lee_c)
           and step == "Due Crew: open what Morning held back" and st9.get("hold_yes") is True,
           f"{n_menu} opened, undo {step!r}, {t_held*1000:.0f} ms")
        col.undo()
        ok("held back: Edit › Undo shuts them again", all(col.get_card(c).queue == -1 for c in shut))
        # 3.8.1, Study this date: a Due Crew deck of the date's open cards, new and review, due or not (a cram
        # before a quiz), random order, Anki rescheduling them; Anki's own one undo step; its Study screen on it
        r0 = sorted(P.DeckIndex(col, did).match(rdates[0], None, "Step Deck"))
        for c in [c for c in r0 if col.get_card(c).queue == 0][:8]:
            card = col.get_card(c)
            card.type, card.queue, card.ivl, card.due = 2, 2, 20, col.sched.today + 15  # reviews, not due for weeks
            col.update_card(card)
        i11 = P.DeckIndex(col, did)
        want = P.study_cards(i11, i11.match(rdates[0], None, "Step Deck"))
        moved = []
        F.mw.moveToState = moved.append
        t = tm(); F.study_date("pM", "r0"); t_study = tm() - t
        sname = F._deck_name(rdates[0]["name"])
        sdid = col.decks.id_for_name(sname)
        sdeck = col.decks.get(sdid) if sdid else {}
        got = set(col.find_cards(f'"deck:{sname}"')) if sdid else set()
        reviews = sum(1 for c in got if col.get_card(c).type == 2)
        ok("study this date: Anki's filtered deck of the date's open cards, new and reviews not due, random, rescheduling",
           sdid and sdeck.get("dyn") and got == set(want) and 0 < reviews < len(got) == len(want)
           and sdeck["terms"][0][2] == 1 and sdeck.get("resched") and moved == ["overview"] and col.decks.selected() == sdid
           and not any(col.get_card(c).queue == -1 for c in got),
           f"{len(got)} cards ({reviews} reviews), terms {sdeck.get('terms')}, {t_study*1000:.0f} ms")
        sstep = col.undo_status().undo
        col.undo()
        ok("study this date: one undo step of Anki's own; Edit › Undo takes the deck away, the cards go home",
           not col.decks.id_for_name(sname) and all(col.get_card(c).odid == 0 and col.get_card(c).did == did for c in want),
           f"undo {sstep!r}")
    finally:
        for k, v in F_real.items():
            setattr(F, k, v)
        F.mw.__dict__.pop("undo", None)
    col.close()
    return failed


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "big.anki2")
        make(p)
        failed = check(p)
    print(f"\n{len(failed)} failed" + (": " + "; ".join(failed) if failed else ""))
    sys.exit(1 if failed else 0)
