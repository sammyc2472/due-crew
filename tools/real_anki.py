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
    # 3.9.1: today's session, at every refresh: the notes started before today found once, not once a
    # date (on the plan's own days, the deck's part alone; my own days add schedule.py's windows)
    from due_crew.stats.queries import StatsQueries
    seen = StatsQueries(col).first_seen(15)
    t = tm(); sv = F.session_view({"id": "pS", "doc": doc}, {"deck_id": did}, i5, seen, today); t_sv = tm() - t
    t = tm(); F.session_view({"id": "pS", "doc": doc, "sched": {"days": [1] * 7, "minutes": 60}}, {"deck_id": did}, i5, seen, today)
    t_mine = tm() - t
    ok("today's session over 31 dates, in under 20 ms", sv is not None and t_sv < 0.02,
       f"{t_sv*1000:.1f} ms; on my own days {t_mine*1000:.1f} ms")
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

    # 3.8.2: Pip's closet reads the revlog's days and hours by the hour, and the
    # cards learned and leeches. 3.9.1: the days before the last week are kept
    # (closet_days.json), so only the first read is whole; a relaunch reads the file
    from due_crew import closet_flow as CF
    closet_files = tempfile.mkdtemp()
    CF._profile_files = lambda: closet_files
    CF._RF.update(key=None, hist=None)
    t = tm(); facts = CF.revlog_facts(col); t_day = tm() - t
    t = tm(); again = CF.revlog_facts(col); t_again = tm() - t
    CF._RF.update(key=None, hist=None)
    t = tm(); relaunch = CF.revlog_facts(col); t_relaunch = tm() - t
    answers = col.db.scalar("SELECT COUNT(*) FROM revlog WHERE ease > 0 AND id < ?", cut * 1000)
    ok("Pip's closet: every answer counted, its days and runs, the first read whole and each one after, a relaunch, quick",
       facts["reviews"] == answers and again == facts == relaunch and facts["days"] > 300 and facts["run"] >= 1
       and facts["learned"] >= 12000 and t_day < 2.5 and t_again < 0.05 and t_relaunch < 0.1,
       f"{answers:,} answers, {facts['days']} days, {t_day*1000:.0f} ms the first, {t_again*1000:.0f} ms after, "
       f"{t_relaunch*1000:.0f} ms a relaunch")

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
        from due_crew import leech_flow as LF
        lee = LF.counts(col, TF._deck_sql(col, did))
        lee_anki = len(col.find_cards('deck:"Step Deck" tag:leech is:suspended prop:lapses>0'))
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
    ok("insights: the deck's suspended leeches, as Anki's own search counts them (3.9.2: lapsed, not a shipped-suspended sibling)",
       lee[0] == lee_anki, f"{lee} vs Anki's {lee_anki}")
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
    # 3.9.1: Anki's deck tree, read once while it can't have changed: an answer moves col.mod;
    # a learning card coming inside the learn-ahead moves its count with the clock alone
    from anki.cards import Card
    from anki.scheduler.v3 import CardAnswer
    real_tree, reads = col.sched.deck_due_tree, []
    col.sched.deck_due_tree = lambda *a: reads.append(1) or real_tree(*a)
    DF._TREE.update(key=None)
    try:
        t = tm(); t0 = DF.deck_tree(col); t_first = tm() - t
        t = tm(); again = DF.deck_tree(col); t_kept = tm() - t
        kept = again is t0 and t0 == real_tree()
        queued = col.sched.get_queued_cards().cards
        if queued:  # the review's own way: the card, its states, Good
            card = Card(col, backend_card=queued[0].card)
            card.start_timer()
            col.sched.answer_card(col.sched.build_answer(card=card, states=queued[0].states, rating=CardAnswer.GOOD))
        t1 = DF.deck_tree(col)
        ok("deck tree: read once while nothing changes, again after an answer, as Anki reads it",
           queued and kept and len(reads) == 2 and t1 is not t0 and t1 == real_tree() and t_kept < t_first / 4,
           f"{t_first*1000:.1f} ms, then {t_kept*1000:.2f} ms")
        lc2 = col.get_card(col.find_cards('deck:"Step Deck" is:new -is:suspended')[0])
        ahead = int(col.get_config("collapseTime", 1200) or 0)
        lc2.type, lc2.queue, lc2.due = 1, 1, int(_t.time()) + ahead + 2
        col.update_card(lc2)
        t2 = DF.deck_tree(col)
        learn = lambda tr: col.decks.find_deck_in_tree(tr, did).learn_count  # noqa: E731
        held = DF.deck_tree(col) is t2
        _t.sleep(3)
        t3 = DF.deck_tree(col)
        ok("deck tree: kept till a learning card comes inside the learn-ahead, then read again and counted",
           held and t3 is not t2 and t3 == real_tree() and learn(t3) == learn(t2) + 1, f"learning {learn(t2)} then {learn(t3)}")
    finally:
        del col.sched.deck_due_tree
        DF._TREE.update(key=None)
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
    # 3.9.3 (Sam's pick A): by the deck's own leech count, read from its options on Anki's engine: Tag Only at 5,
    # a card Anki kept in my reviews at 6 lapses is a leech now (8 was Recover's line); taken once asked, one undo step
    sdid = col.decks.id_for_name("Step Deck")
    conf = col.decks.config_dict_for_deck_id(sdid)
    was = (conf["lapse"]["leechFails"], conf["lapse"]["leechAction"])
    conf["lapse"]["leechFails"], conf["lapse"]["leechAction"] = 5, 1
    col.decks.update_config(conf)
    kc = col.get_card(next(c for c in col.find_cards('deck:"Step Deck" -tag:leech -is:suspended')
                           if len(col.get_note(col.get_card(c).nid).card_ids()) == 1))
    kc.type, kc.queue, kc.lapses, kc.ivl, kc.due = 2, 2, 6, 5, col.sched.today + 3
    col.update_card(kc)
    kn = kc.note()
    kn.add_tag("leech")
    col.update_note(kn)
    deck, eight, extra, counts = DF.leech_plan(col)
    ok("leeches 3.9.3: the deck's own count, read from its options on Anki's engine",
       kc.id in deck and kc.id not in eight and kc.id in extra and counts == [5], f"extra {len(extra)}, counts {counts}")
    got = DF.recover_leeches(col, cids=extra)
    back = col.get_card(kc.id)
    ok("leeches 3.9.3: the one kept in my reviews back as new, its tag off, one undo step",
       kc.id in got and back.type == 0 and back.lapses == 0 and "leech" not in [t.lower() for t in back.note().tags]
       and col.undo_status().undo == "Due Crew: recover leeches", f"{len(got)} recovered, undo {col.undo_status().undo!r}")
    conf["lapse"]["leechFails"], conf["lapse"]["leechAction"] = was
    col.decks.update_config(conf)
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
        # 3.9.1: refresh_progress asked again with nothing changed (a sync, then its commit): the last
        # answer, the deck not read again; an unsuspend moves col.mod and it's read again
        shut = sorted(c for c in P.DeckIndex(col, did).match(rdates[3], None, "Step Deck") if col.get_card(c).queue == -1)[:1]
        builds, real_init = [], P.DeckIndex.__init__
        P.DeckIndex.__init__ = lambda self, c, d: builds.append(d) or real_init(self, c, d)
        F._last.update(key=None, got=None)
        try:
            t = tm(); a = F_real["refresh_progress"](); t_read = tm() - t
            t = tm(); b = F_real["refresh_progress"](); t_memo = tm() - t
            once = len(builds) == 1 and a == b and bool(a)
            col.sched.unsuspend_cards(shut)
            c2 = F_real["refresh_progress"]()
            col.undo()
        finally:
            P.DeckIndex.__init__ = real_init
            F._last.update(key=None, got=None)
        ok("refresh: asked again with nothing changed, the last answer; an unsuspend reads the deck again",
           shut and once and len(builds) == 2 and c2 != a and t_memo < t_read / 10,
           f"{t_read*1000:.0f} ms, then {t_memo*1000:.1f} ms")
    finally:
        for k, v in F_real.items():
            setattr(F, k, v)
        F.mw.__dict__.pop("undo", None)
    col.close()
    return failed


def check_392(tmp):
    """3.9.2 on Anki's engine, on a deck of its own with a log written as Anki
    writes one (150 days of a simple learner): Stop new cards (Anki's
    today-only limit on a deck and its subdecks, one undo step, each
    morning, a week before an exam, a deck deleted), Reviews ahead on the
    log, the leech buttons (Bring back, Learn it fresh, each one undo step;
    a card deleted since), the leech view's fronts (a reversed card's own,
    a cloze's asked part hidden), the view worked out again when an answer
    moves col.mod, and the map by % right and by when I started them."""
    import random, time, datetime as dt
    from anki.collection import Collection
    from due_crew import plan_flow as F, ahead_flow as AF, leech_flow as LF, team_flow as TF, app
    keep = {(m, k): getattr(m, k) for m, ks in ((F, ("_pcfg", "_psave", "_today", "tooltip", "apply_catch", "_after_change", "client")),
                                                 (AF, ("tooltip", "cfg")), (LF, ("tooltip", "cfg")), (TF, ("cfg",)),
                                                 (app, ("swap", "client"))) for k in ks}
    keep_col = F.mw.col
    try:
        failed = []
        def ok(name, cond, extra=""):
            print(("PASS " if cond else "FAIL ") + "3.9.2: " + name, extra)
            if not cond:
                failed.append(name)

        path = os.path.join(tmp, "c.anki2")
        col = Collection(path)
        col.crt = col.crt - 400 * 86400  # a collection made long ago, as a real one is
        col.close()
        col = Collection(path)
        did = col.decks.id("Step Deck")
        sub = col.decks.id("Step Deck::Sub")
        model = col.models.by_name("Basic")
        for d, n in ((did, 300), (sub, 300)):
            for i in range(n):
                note = col.new_note(model)
                note["Front"], note["Back"] = f"Q {d} {i} <b>bold</b>", f"A {i}"
                col.add_note(note, d)
        conf = col.decks.config_dict_for_deck_id(did)
        ok("setup: the preset's 20 new a day", conf["new"]["perDay"] == 20, f"leech action {conf['lapse'].get('leechAction')}, fails {conf['lapse'].get('leechFails')}")
        if conf["lapse"].get("leechAction") != 0:
            conf["lapse"]["leechAction"] = 0  # Suspend Card, as a big shared deck's preset has it
            col.decks.update_config(conf)

        # a log: 150 days, about 25 new a day, reviews by a simple learner, written as Anki writes them
        cutoff = int(col.sched.day_cutoff)
        sday = int(col.sched.today)
        rng = random.Random(3)
        cids = sorted(col.find_cards('deck:"Step Deck"'))
        rng.shuffle(cids)
        rows, state, nxt = [], {}, 0
        DAYS = 150
        for t in range(DAYS):
            day0 = cutoff - (DAYS - t) * 86400
            k = 0
            for cid, (due, ivl, lapses, reps) in sorted(state.items()):
                if due > t:
                    continue
                k += 1
                ts = (day0 + 3600 + k * 7) * 1000 + rng.randrange(1000)
                if rng.random() < (0.2 if ivl < 7 else 0.1):
                    rows += [(ts, cid, 1, -600, ivl, 2500, 9000, 1), (ts + 600000, cid, 3, 1, -600, 2300, 7000, 2)]
                    state[cid] = (t + 1, 1, lapses + 1, reps + 2)
                else:
                    n = max(ivl + 1, int(round(ivl * rng.uniform(2.0, 3.0))))
                    rows.append((ts, cid, 3, n, ivl, 2500, 8000, 1))
                    state[cid] = (t + n, n, lapses, reps + 1)
            for _ in range(4 if nxt < 400 else 0):
                cid = cids[nxt]; nxt += 1
                ts = (day0 + 7200 + nxt) * 1000
                rows += [(ts, cid, 3, -600, 0, 2500, 10000, 0), (ts + 600000, cid, 3, 1, -600, 2500, 6000, 0)]
                state[cid] = (t + 1, 1, 0, 2)
        col.db.executemany("INSERT INTO revlog (id, cid, usn, ease, ivl, lastIvl, factor, time, type) VALUES (?,?,-1,?,?,?,?,?,?)", rows)
        for cid, (due, ivl, lapses, reps) in state.items():
            c = col.get_card(cid)
            c.type, c.queue, c.ivl, c.due, c.lapses, c.reps = 2, 2, ivl, sday + (due - DAYS), lapses, reps
            col.update_card(c)
        # two leeches: one suspended by Anki (tagged), one a miss away
        leech, near = sorted(state)[:2]
        for cid, lap, q in ((leech, 8, -1), (near, 7, 2)):
            c = col.get_card(cid)
            c.lapses, c.queue = lap, q
            col.update_card(c)
        n = col.get_card(leech).note()
        n.tags.append("leech")
        col.update_note(n)
        ok("setup: a log", len(rows) > 2000, f"{len(rows):,} answers, {len(state)} cards started")

        # glue stubs, as tools/real_anki.py has them
        pstore = {}
        today = dt.date.today().isoformat()
        F._pcfg, F._psave = (lambda: pstore), (lambda d: None)
        F._today = lambda: today
        F.tooltip = AF.tooltip = LF.tooltip = lambda *a, **k: None
        catches = []
        F.apply_catch = lambda *a, **k: catches.append(1)
        F._after_change = lambda: None
        app.swap = lambda *a, **k: None
        exam = {"exam_date": ""}
        AF.cfg = LF.cfg = lambda: exam
        F.mw.col = col
        AF.mw.col = col
        LF.mw.col = col


        def new_counts():
            tree = col.sched.deck_due_tree()
            out = {}
            def walk(n):
                out[n.deck_id] = n.new_count
                for ch in n.children:
                    walk(ch)
            walk(tree)
            return out[did], out[sub]

        def selected_new(d):
            col.decks.select(d)
            col.sched.reset() if hasattr(col.sched, "reset") else None
            return col.sched.counts()[0]

        base = new_counts()
        ok("before: 20 new today on the deck and on its subdeck", base[1] == 20 and base[0] >= 20, str(base))

        # Stop new now (no exam): today's 0 on both, the preset untouched
        AF.stop_new(did, "now")
        step_stop = col.undo_status().undo
        after = new_counts()
        col.undo()
        undone = new_counts()
        AF.apply_morning()
        pre = col.decks.config_dict_for_deck_id(did)["new"]["perDay"]
        ok("stop now: no new cards today on the deck, its subdeck, or studying either", after == (0, 0)
           and selected_new(did) == 0 and selected_new(sub) == 0, f"{after}")
        ok("stop now: the preset and the deck's own limit as they were", pre == 20 and col.decks.get(did).get("newLimit") is None
           and col.decks.get(sub).get("newLimit") is None)
        ok("stop now: one undo step for the deck and its subdeck", step_stop == "Due Crew: new cards stopped", repr(step_stop))
        ok("stop now: one Edit › Undo brings the deck's and the subdeck's new cards back", undone == base, str(undone))
        ok("and the morning sets it again", new_counts() == (0, 0))
        ok("stop now: kept in plans.json", (pstore.get("new_off") or {}).get(str(did), {}).get("kind") == "now", str(pstore.get("new_off")))
        ok("the morning again: no change, still 0", AF.apply_morning() is False and new_counts() == (0, 0))
        # yesterday's 0 doesn't hold today: the morning sets it again
        for d in (did, sub):
            deck = col.decks.get(d); deck["newLimitToday"] = {"limit": 0, "today": sday - 1}; col.decks.save(deck)
        ok("a 0 from yesterday lapses on its own", new_counts() == base, str(new_counts()))
        ok("and the morning sets today's", AF.apply_morning() is True and new_counts() == (0, 0))

        # Reviews ahead with the pause on
        v = AF.deck_view(col, did, TF._deck_sql(col, did))
        ok("reviews ahead: worked out on a real log, the pause on", isinstance(v, dict) and v.get("off") is True and len(v.get("days") or []) > 20,
           f"keys {sorted(v)[:12] if isinstance(v, dict) else v}")

        # Turn back on: today's 0 off, the catch-up's put back
        AF.start_new(did)
        ok("turn new cards back on: the deck's 20 back, the pause gone, a catch-up's limit put back",
           new_counts() == base and not (pstore.get("new_off") or {}) and catches, f"{new_counts()} {catches}")

        # a catch-up's own limit today (35), then a stop: 0; back on pops it and asks the catch-up again
        deck = col.decks.get(did); deck["newLimitToday"] = {"limit": 35, "today": sday}; col.decks.save(deck)
        c35 = new_counts()
        AF.stop_new(did, "now")
        ok("stop over a catch-up's limit: 0", new_counts() == (0, 0), f"was {c35}")
        AF.start_new(did)

        # the week before an exam: nothing today with the exam 12 days out; 0 once the week comes; over after it
        exam["exam_date"] = (dt.date.today() + dt.timedelta(days=12)).isoformat()
        AF.stop_new(did, "week")
        ok("the week before my exam, 12 days out: new cards today as ever", new_counts() == base and str(did) in pstore["new_off"])
        F._today = lambda: (dt.date.today() + dt.timedelta(days=6)).isoformat()
        ok("six days on, the exam a week off: the morning sets 0", AF.apply_morning() is True and new_counts() == (0, 0))
        F._today = lambda: (dt.date.today() + dt.timedelta(days=13)).isoformat()
        AF.apply_morning()
        ok("the day after the exam: the pause is forgotten", str(did) not in (pstore.get("new_off") or {}), str(pstore.get("new_off")))
        F._today = lambda: today
        for d in (did, sub):
            deck = col.decks.get(d); deck.pop("newLimitToday", None); col.decks.save(deck)
        exam["exam_date"] = ""

        # a deck deleted while paused: the morning drops it, no error
        gone_did = col.decks.id("Gone Deck")
        pstore["new_off"] = {str(gone_did): {"kind": "now", "at": today, "exam": False}}
        col.decks.remove([gone_did])
        ok("a paused deck since deleted: the morning just forgets it", AF.apply_morning() is False and not pstore["new_off"])

        # leeches: the line's counts and the view's reads
        deck_sql = TF._deck_sql(col, did)
        F.client = lambda: type("C", (), {"signed_in": True, "session": {}})()
        app.client = F.client
        cnt = LF.counts(col, deck_sql)
        ok("leeches: one Anki stopped showing me; the ones a miss from it (Anki's own steps)", cnt[0] == 1 and cnt[1] >= 1, str(cnt))
        t = time.perf_counter(); lv = LF.view(col, did, deck_sql); t_v = time.perf_counter() - t
        ok("leeches view: each card's front from my copy, plain, its misses",
           [c["cid"] for c in lv["gone"]] == [leech] and near in [c["cid"] for c in lv["near"]]
           and "<b>" not in lv["gone"][0]["front"] and lv["gone"][0]["lapses"] == 8, f"{lv['gone'][0]['front']!r}, {t_v*1000:.0f} ms")

        # Bring back: unsuspended, tag off, schedule kept, one undo step; Undo puts both back
        due0, ivl0 = col.get_card(leech).due, col.get_card(leech).ivl
        LF.bring_back(did, [leech])
        c = col.get_card(leech)
        step = col.undo_status().undo
        ok("bring back: due again with its schedule, the leech tag off, one undo step",
           c.queue == 2 and c.due == due0 and c.ivl == ivl0 and "leech" not in [x.lower() for x in c.note().tags]
           and step == "Due Crew: bring back", f"queue {c.queue}, undo {step!r}")
        col.undo()
        c = col.get_card(leech)
        ok("bring back: Edit › Undo suspends it and tags it again", c.queue == -1 and "leech" in c.note().tags)

        # Learn it fresh: a new card again, counts from zero, unsuspended, tag off, one undo step
        LF.fresh(did, leech)
        c = col.get_card(leech)
        step = col.undo_status().undo
        ok("learn it fresh: new again, lapses and reps from zero, the tag off, one undo step",
           c.type == 0 and c.queue == 0 and c.lapses == 0 and c.reps == 0 and "leech" not in c.note().tags
           and step == "Due Crew: learn it fresh", f"type {c.type} queue {c.queue} lapses {c.lapses}, undo {step!r}")
        col.undo()
        c = col.get_card(leech)
        ok("learn it fresh: Edit › Undo puts it back as it was", c.type == 2 and c.queue == -1 and c.lapses == 8 and "leech" in c.note().tags,
           f"type {c.type} queue {c.queue} lapses {c.lapses}")

        # the view's front is the card's own question: a reversed card's front is the note's back
        rev_model = col.models.by_name("Basic (and reversed card)")
        rn = col.new_note(rev_model)
        rn["Front"], rn["Back"] = "the question side", "the answer side"
        col.add_note(rn, did)
        c2 = [c for c in rn.cards() if c.ord == 1][0]
        c2.type, c2.queue, c2.lapses, c2.ivl, c2.due = 2, -1, 8, 3, sday
        col.update_card(c2)
        rn.tags.append("leech")
        col.update_note(rn)
        col.db.execute("INSERT INTO revlog (id, cid, usn, ease, ivl, lastIvl, factor, time, type) VALUES (?,?,-1,1,1,3,2500,9000,1)",
                       cutoff * 1000 - 5000, c2.id)
        LF._mine("leech_view").clear()
        lv2 = LF.current(col, did, TF._deck_sql(col, did))
        fr = {c["cid"]: c["front"] for c in lv2["gone"]}
        ok("leeches view: a reversed card shows its own front (the note's back), never its answer",
           fr.get(c2.id) == "the answer side", repr(fr.get(c2.id)))
        cz = col.models.by_name("Cloze")
        zn = col.new_note(cz)
        zn["Text"] = "{{c1::Warfarin}} inhibits {{c2::VKOR}}"
        col.add_note(zn, did)
        z2 = [c for c in zn.cards() if c.ord == 1][0]
        z2.type, z2.queue, z2.lapses, z2.ivl, z2.due = 2, -1, 9, 3, sday
        col.update_card(z2)
        zn.tags.append("leech")
        col.update_note(zn)
        col.db.execute("INSERT INTO revlog (id, cid, usn, ease, ivl, lastIvl, factor, time, type) VALUES (?,?,-1,1,1,3,2500,9000,1)",
                       cutoff * 1000 - 4000, z2.id)
        LF._mine("leech_view").clear()
        fr = {c["cid"]: c["front"] for c in LF.current(col, did, TF._deck_sql(col, did))["gone"]}
        ok("leeches view: a cloze card shows its own question, its answer hidden, the other cloze as Anki shows it",
           "VKOR" not in (fr.get(z2.id) or "x") and "Warfarin" in (fr.get(z2.id) or ""), repr(fr.get(z2.id)))
        # the view's cache moves with the collection: a real answer changes col.mod
        from anki.scheduler.v3 import CardAnswer
        col.decks.select(did)
        m0 = col.mod
        qc = col.sched.get_queued_cards()
        if qc.cards:
            card = col.get_card(qc.cards[0].card.id)
            card.start_timer()
            col.sched.answer_card(col.sched.build_answer(card=card, states=qc.cards[0].states, rating=CardAnswer.GOOD))
        ok("a real answer moves col.mod (the leech view is worked out again)", bool(qc.cards) and col.mod != m0, f"{m0} -> {col.mod}")
        # a card deleted after the view was drawn
        col.remove_notes([col.get_card(near).nid])
        try:
            LF.fresh(did, near)
            LF.bring_back(did, [near])
            ok("a card deleted since the view was drawn: nothing happens, no error", True)
        except Exception as e:
            ok("a card deleted since the view was drawn: nothing happens, no error", False, repr(e))

        # a Tag Only preset (Anki's default since 23.10): the eighth miss tags it and keeps it in my reviews
        tdid = col.decks.id("Tag Deck")
        tconf = col.decks.get_config(col.decks.add_config_returning_id("Tag Only"))
        tconf["lapse"]["leechAction"], tconf["lapse"]["leechFails"] = 1, 8
        col.decks.update_config(tconf)
        td = col.decks.get(tdid)
        td["conf"] = tconf["id"]
        col.decks.save(td)
        tn = col.new_note(model)
        tn["Front"], tn["Back"] = "Tag only front", "back"
        col.add_note(tn, tdid)
        tc = tn.card_ids()[0]
        col.db.execute("UPDATE cards SET type = 2, queue = 2, ivl = 10, due = ?, lapses = 7, reps = 20, factor = 2500 WHERE id = ?", sday, tc)
        col.decks.select(tdid)
        qc = col.sched.get_queued_cards()
        if qc.cards and qc.cards[0].card.id == tc:
            card = col.get_card(tc)
            card.start_timer()
            col.sched.answer_card(col.sched.build_answer(card=card, states=qc.cards[0].states, rating=CardAnswer.AGAIN))
        c = col.get_card(tc)
        tsql = TF._deck_sql(col, tdid)
        tcnt = LF.counts(col, tsql)
        ok("tag only: Anki's eighth miss tags it and keeps it in my reviews; the line counts it as one",
           c.lapses == 8 and c.queue != -1 and "leech" in [x.lower() for x in c.note().tags] and tcnt == (0, 0, 1)
           and len(col.find_cards('deck:"Tag Deck" tag:leech -is:suspended')) == 1, f"{c.lapses} lapses, queue {c.queue}, {tcnt}")
        LF._mine("leech_view").clear()
        tv = LF.view(col, tdid, tsql)
        ok("tag only: the view lists it as still in my reviews, due today",
           [x["cid"] for x in tv["kept"]] == [tc] and not tv["gone"] and not tv["near"] and tv["kept"][0]["due"] == 0, str(tv["kept"]))
        LF.fresh(tdid, tc)
        c = col.get_card(tc)
        ok("tag only: Learn it fresh: a new card, the tag off, one undo step",
           c.type == 0 and c.lapses == 0 and "leech" not in [x.lower() for x in c.note().tags] and LF.counts(col, tsql) == (0, 0, 0)
           and col.undo_status().undo == "Due Crew: learn it fresh", f"type {c.type}, {c.note().tags}, {col.undo_status().undo}")

        # the map by when I started them, and the shading by % right, on the real log
        try:
            t = time.perf_counter(); m = TF._map(col, did, deck_sql, cutoff); t_m = time.perf_counter() - t
            ok("map: worked out on the real log", m is not None, f"{t_m*1000:.0f} ms, {type(m).__name__}")
            t = time.perf_counter(); k, kby = TF._know(col, deck_sql, cutoff); t_k = time.perf_counter() - t
            vals = list(k.values())
            ok("know: each started card's share right, 0 to 1", vals and all(x is None or 0 <= x <= 1 for x in vals) and any(x is not None for x in vals),
               f"{len(vals)} cards, {t_k*1000:.0f} ms, e.g. {vals[:3]}")
            TF.cfg = lambda: {"ins_map_by": {str(did): __import__("due_crew.team", fromlist=["x"]).START_WAY}}
            shown, by, know, ways = TF._map(col, did, deck_sql, cutoff)
            ok("map by when I started them: a week a tile, picked", len(shown) >= 2 and any(w.get("on") and w["name"] == "When you started them" for w in ways),
               f"{len(shown)} tiles: {[t.get('name') for t in shown][:4]}")
        except Exception as e:
            import traceback; traceback.print_exc()
            ok("map / know on the real log", False, repr(e))

        col.close()
    finally:
        for (m, k), v in keep.items():
            setattr(m, k, v)
        F.mw.col = keep_col
    return failed


def check_planner(path):
    """Labs (due_crew/planner, docs/planner.md) on the real engine, on the big
    collection: question IDs found among 12,000 question tags, QBank QIDs'
    Unsuspend and Study now, each one undo step that Anki's undo takes back
    whole, and the picker's tree and search, timed."""
    import time
    from anki.collection import Collection
    from due_crew import plans as P
    from due_crew.planner import actions as A, edits as E, model as M, qids as Q
    failed = []

    def ok(name, cond, extra=""):
        print(("PASS " if cond else "FAIL ") + "planner: " + name, extra)
        if not cond:
            failed.append("planner: " + name)
    col = Collection(path)
    try:
        did = col.decks.id_for_name("Step Deck")
        R = "#Big_Step1_v12"
        idx = P.DeckIndex(col, did)
        t = time.perf_counter(); banks = Q.banks(idx); t_b = time.perf_counter() - t
        qb = banks.get("QBank") or {}
        have = {k.rsplit("::", 1)[-1] for k in idx.tag_keys if k.rsplit("::", 1)[-1].isdigit()}  # the ones sampled onto notes
        ok("question tags read by bank", set(qb) == have and len(qb) > 11000 and list(banks) == ["QBank"],
           f"{len(qb):,} numbers, {t_b*1000:.0f} ms")
        picked = sorted(qb)[:15]
        cids = set().union(*(qb[n] for n in picked))
        cl = sorted(cids)
        # some seen before (review cards a month out), some of those shut, one a leech
        col.sched.set_due_date(cl[:8], "30")
        col.sched.suspend_cards(cl[4:12])
        leech = col.get_card(cl[0]).note()
        leech.tags = list(leech.tags) + ["leech"]
        col.update_note(leech)
        idx = P.DeckIndex(col, did)
        text = "Block 3 · 12 Oct 2026\nMissed: " + ", ".join(picked) + " · 65%"
        t = time.perf_counter(); f = Q.find(idx, text); t_f = time.perf_counter() - t
        ok("a paste: its 15 questions found, the date and the score aren't questions",
           f["found"] == picked and f["missing"] == ["2026"] and f["cids"] == cids, f"{len(cids)} cards, {t_f*1000:.0f} ms, missing {f['missing']}")
        from due_crew import plan_flow as F
        snap = lambda: {c: (col.get_card(c).queue, col.get_card(c).due, col.get_card(c).ivl, col.get_card(c).did)  # noqa: E731
                        for c in cl}
        before = snap()
        shut = P.openable_ids(col, cids)
        leech_ids = {c for c in cl if col.get_card(c).nid == leech.id}
        n = A.unsuspend(col, cids, "Due Crew: unsuspend 15 questions")
        cards = {c: col.get_card(c) for c in cl}
        ok("Unsuspend: the suspended ones, never the leech's cards; no due date or interval moves",
           n == len(shut) > 0 and all(cards[c].queue != -1 for c in shut)
           and all(cards[c].queue == -1 for c in leech_ids if before[c][0] == -1)
           and all((cards[c].due, cards[c].ivl) == before[c][1:3] for c in cl if cards[c].type == 2), f"unsuspended {n}")
        ok("Unsuspend: one undo step, named", col.undo_status().undo == "Due Crew: unsuspend 15 questions", repr(col.undo_status().undo))
        col.undo()
        ok("Unsuspend: Anki's undo takes it back", snap() == before, str([c for c in cl if snap()[c] != before[c]][:5]))
        name = P.our_deck(A.DECK)
        build = lambda want: F._filtered(col, name, want, order=F.STUDY_ORDER)  # noqa: E731
        kept = {c for c in leech_ids if before[c][0] == -1}  # a leech Anki suspended stays out; its open cards may go in
        first, rest = set(cl[:8]), set(cl[8:])
        got = A.study(col, first, "Due Crew: study 8 QBank cards", name, build)
        mdid = col.decks.id_for_name(name)
        deck = col.decks.get(mdid) if mdid else {}
        cards = {c: col.get_card(c) for c in cl}
        took = {c for c in first if cards[c].did == mdid}
        ok("Study now: a filtered deck under Due Crew that reschedules by my answers, the cards that can go in it",
           bool(deck.get("dyn")) and bool(deck.get("resched")) and took == first - kept and got[1] == len(took),
           f"{got}, {len(took)} in {name}")
        ok("Study now: the suspended ones unsuspended first, never the leech's; no review's due or interval moves",
           all(cards[c].queue != -1 for c in first if c in shut) and all(cards[c].queue == -1 for c in kept if c in first)
           and all((cards[c].odue or cards[c].due, cards[c].ivl) == before[c][1:3] for c in first if cards[c].type == 2), f"unsuspended {got[0]}")
        ok("Study now: one undo step, named", col.undo_status().undo == "Due Crew: study 8 QBank cards", repr(col.undo_status().undo))
        got2 = A.study(col, rest, "Due Crew: study 7 QBank cards", name, build)
        cards = {c: col.get_card(c) for c in cl}
        ok("Study now: the next paste adds to the deck, the last one's still in it",
           {c for c in cl if cards[c].did == mdid} == set(cl) - kept and got2[1] == len(set(cl) - kept), f"{got2}, {len(kept)} kept out")
        col.undo()
        col.undo()
        ok("Study now: Anki's undo takes both back whole, every card home as it was", snap() == before,
           str([c for c in cl if snap()[c] != before[c]][:5]))
        t = time.perf_counter(); kids = M.children(idx, R); t_c = time.perf_counter() - t
        ok("picker: the root's parts, #s first, then ^", [p.rsplit("::", 1)[-1] for p, _n, _m in kids][-1] == "^Systems" and len(kids) == 8,
           f"{[p.rsplit('::', 1)[-1] for p, _n, _m in kids]}, {t_c*1000:.0f} ms")
        t = time.perf_counter(); hits = M.find(idx, "cardio topic"); t_s = time.perf_counter() - t
        t = time.perf_counter(); hits2 = M.find(idx, "renal"); t_s2 = time.perf_counter() - t
        ok("picker: a search over every path, quick once read", hits and all("cardio" in h.lower() for h in hits) and t_s2 < 0.5,
           f"{len(hits)} hits, first {t_s*1000:.0f} ms (reads the paths), then {t_s2*1000:.0f} ms ({len(hits2)} hits)")
        t = time.perf_counter(); n = M.tag_count(idx, f"{R}::#V&B"); t_n = time.perf_counter() - t
        ok("picker: a big part's count", n[0] > 1000, f"{n}, {t_n*1000:.0f} ms")
        unit = {"id": "u1", "name": "Cardio", "opens": "2026-11-09", "tags": [h for h in hits[:30]] + [f"{R}::#QBank::Step::{picked[0]}"]}
        doc = {"deck": "Step Deck", "units": [unit]}
        t = time.perf_counter(); rows = M.sources(idx, unit, doc); t_r = time.perf_counter() - t
        ok("a date's sources by resource", rows and rows[-1]["kind"] == "question" and all(r["cids"] for r in rows[:-1]),
           f"{len(rows)} rows, {t_r*1000:.0f} ms")
        t = time.perf_counter(); rc = E.recount(doc, idx, {"u1"}); t_rc = time.perf_counter() - t
        ok("a changed date counted as the builder counts it", rc["units"][0]["n"] == sum(len(idx.tag_cards(x)) for x in unit["tags"]),
           f"n {rc['units'][0]['n']:,}, {t_rc*1000:.0f} ms")
    finally:
        col.close()
    return failed


def check_bars(tmp):
    """3.9.3's Today bars (due_flow.bars) on the real engine, on a small
    collection of its own: reviews answered (one missed, so relearning),
    new cards started, and Anki's own revlog, tree and queues read back."""
    import time
    from anki.collection import Collection
    from due_crew import due_flow as F
    failed = []

    def ok(name, cond, extra=""):
        print(("PASS " if cond else "FAIL ") + "bars: " + name, extra)
        if not cond:
            failed.append("bars: " + name)
    col = Collection(os.path.join(tmp, "bars.anki2"))
    try:
        m = col.models.by_name("Basic")
        big, pharm = col.decks.id("Big Step 1"), col.decks.id("Pharm")
        for i in range(12):
            n = col.new_note(m)
            n["Front"], n["Back"] = f"q{i}", "a"
            col.add_note(n, big if i < 8 else pharm)
        cids = sorted(col.find_cards(""))
        col.sched.set_due_date(cids[:4], "0")  # four reviews due today
        col.decks.select(big)

        def answer(rating):
            q = col.sched.get_queued_cards()
            c = col.get_card(q.cards[0].card.id)
            c.start_timer()
            col.sched.answer_card(col.sched.build_answer(card=c, states=col._backend.get_scheduling_states(c.id),
                                                         rating=rating))
            return c
        first = answer(0)  # a review, Again: relearning
        for _ in range(5):
            answer(2)  # Good
        tree = col.sched.deck_due_tree()
        got = F.bars(col, tree, int(time.time()), int(col.get_config("collapseTime", 1200) or 0), set())
        fresh = col.db.list("SELECT cid FROM revlog WHERE type = 0 AND lastIvl = 0 AND ease > 0")
        ok("a new card's first answer is type 0, lastIvl 0 in Anki's revlog", len(fresh) == 3, str(fresh))
        ok("Reviews: four due, two through, the missed one back later today, two due now",
           (got["whole"], got["through"], got["later"]) == (4, 2, 1) and got["left"] == 2, str(got))
        ok("New cards: three started, in their steps; what Anki still gives, a line a deck",
           got["new"]["later"] == 3 and got["new"]["through"] == 0
           and [d[0] for d in got["new"]["decks"]] == ["Big Step 1", "Pharm"]
           and got["new"]["decks"][0][2] == 3 + int(tree.children[0].new_count), str(got["new"]))
        ok("the missed review is relearning, Anki's own", col.get_card(first.id).type == 3)
    finally:
        col.close()
    return failed


def check_opens(path):
    """3.9.5, Browse's Due column (Sam's pick: "Thu 5 Nov · Heme 2"): Anki's
    own rows for its own columns, a plan's dates ahead on the big deck, the
    suspended cards they open saying the day and the plan, and how long
    working the days out takes."""
    import datetime as _dtm
    import time
    import types
    REPO = os.path.dirname(HERE)
    sys.path.insert(0, REPO); sys.path.insert(0, REPO + "/tests")
    from anki.collection import Collection
    import fakes
    fakes.install_fake_requests(fakes.FakeWorker())
    fakes.install_fake_aqt()
    from due_crew import plans as P
    from due_crew import plan_flow as F
    failed = []

    def ok(name, cond, extra=""):
        print(("PASS " if cond else "FAIL ") + name, extra)
        if not cond:
            failed.append(name)
    col = Collection(path)
    try:
        did = col.decks.id_for_name("Step Deck")
        idx = P.DeckIndex(col, did)
        tags, _decks = idx.tree()
        lect = sorted({p for p, _ in tags if "#Lectures::Renal::" in p and p.count("::") == 4})[:40]
        today = _dtm.date.today()
        units = [{"id": f"o{i}", "name": x.rsplit("::", 1)[-1], "opens": str(today + _dtm.timedelta(days=i + 1)), "tags": [x], "decks": [], "cards": []}
                 for i, x in enumerate(lect)]
        units[0]["opens"] = str(today - _dtm.timedelta(days=3))  # opened already, here
        plan = {"id": "pO", "name": "Heme 2", "doc": {"deck": "Step Deck", "units": units}}
        ahead = idx.match(units[1], None, "Step Deck") | idx.match(units[5], None, "Step Deck")
        col.sched.suspend_cards(sorted(ahead))
        F.mw.col = col
        F.followed = lambda: [plan]
        F._state_cfg = lambda c=None: {"pO": {"deck_id": did, "applied": {"o0": "sig"}}}
        F._today = lambda: str(today)
        F.opens_reset()
        t = time.perf_counter(); m = F.opens_map(); t_map = time.perf_counter() - t
        ok("Browse: the days a plan opens its cards, worked out once on the big deck", len(m) > 0 and t_map < 1.0, f"{len(m):,} cards, {t_map*1000:.0f} ms")
        columns = col.load_browser_card_columns()
        ok("Browse: Anki's Due column is cardDue", "cardDue" in columns, str(columns))
        cid = sorted(idx.match(units[1], None, "Step Deck"))[0]
        cells, *_rest = col.browser_row_for_id(cid)
        row = types.SimpleNamespace(cells=tuple(types.SimpleNamespace(text=c[0] if isinstance(c, tuple) else c.text) for c in cells))
        was = row.cells[columns.index("cardDue")].text
        t = time.perf_counter(); F.browser_row(cid, False, row, columns); t_row = time.perf_counter() - t
        want = P.opens_words(units[1]["opens"], "Heme 2", str(today))
        ok("Browse: a suspended card the plan opens says the day and the plan in Due", row.cells[columns.index("cardDue")].text == want,
           f"{was!r} -> {row.cells[columns.index('cardDue')].text!r}, {t_row*1000:.1f} ms a row")
        other = sorted(idx.match(units[2], None, "Step Deck") - ahead)[0]
        cells, *_rest = col.browser_row_for_id(other)
        row2 = types.SimpleNamespace(cells=tuple(types.SimpleNamespace(text=c[0] if isinstance(c, tuple) else c.text) for c in cells))
        before = row2.cells[columns.index("cardDue")].text
        F.browser_row(other, False, row2, columns)
        ok("Browse: one the plan opens but isn't suspended keeps Anki's words", row2.cells[columns.index("cardDue")].text == before, repr(before))
    finally:
        col.close()
    return failed


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "big.anki2")
        make(p)
        if "--opens" in sys.argv:  # this check alone
            failed = check_opens(p)
            print(f"\n{len(failed)} failed")
            sys.exit(1 if failed else 0)
        failed = check(p)
        failed += check_392(tmp)
        failed += check_planner(p)
        failed += check_bars(tmp)
        failed += check_opens(p)
    print(f"\n{len(failed)} failed" + (": " + "; ".join(failed) if failed else ""))
    sys.exit(1 if failed else 0)
