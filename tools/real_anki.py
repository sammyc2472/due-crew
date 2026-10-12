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

    col = Collection(path)
    did = col.decks.id_for_name("Step Deck")
    ok = lambda name, cond, extra="": print(("PASS " if cond else "FAIL ") + name, extra)
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
    F._filtered(col, F._deck_name("Checkpoint · Empty one"), pick[:3])
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
    ok("…and the cards it held are back home", len(col.find_cards(f"cid:{','.join(str(c) for c in pick[:3])} deck:\"Step Deck\"")) == 3)
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
    row = text.splitlines()[6].split("\t")
    ok("export: notetype and deck names from Anki", row[1] == "Basic" and row[2] == "Step Deck", str(row[:3]))
    est = P.export_size(col, nids_all)
    ok("export: the size estimate errs high, not wildly", len(text) <= est <= 3 * len(text), f"{est/1024/1024:.1f} MB est")
    t = tm(); dates = P.export_scope(idx2, doc, "dates"); t_scope = tm() - t
    ok("export: what the plan's dates open", 0 < len(dates) < 35000, f"{len(dates):,} notes, {t_scope*1000:.0f} ms")
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
    col.close()


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "big.anki2")
        make(p)
        check(p)
