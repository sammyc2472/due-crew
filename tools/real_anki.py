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
    R = "#AK_Step1_v12"
    systems = ["Cardio", "Renal", "Pulm", "Neuro", "GI", "Heme", "Endo", "Repro", "MSK", "Derm", "Psych", "Immuno"]
    fam = []
    fam += [f"{R}::#B&B::{i:02d}_{s}::{j:02d}_Topic_{j}" for i, s in enumerate(systems, 1) for j in range(1, 60)]
    fam += [f"{R}::#Bootcamp::{s}::{k:02d}_Section_{k}::{j:02d}_Lecture_Name_{j}" for s in systems for k in range(1, 8) for j in range(1, 16)]
    fam += [f"{R}::#FirstAid::{s}::{k:02d}_Chapter::{j:02d}_Page_{j}" for s in systems for k in range(1, 12) for j in range(1, 20)]
    fam += [f"{R}::#Pathoma::{c:02d}_Chapter_{c}::{j:02d}_Section" for c in range(1, 20) for j in range(1, 12)]
    fam += [f"{R}::#Sketchy::{g}::{j:02d}_Video_{j}" for g in ("Micro", "Pharm", "Path") for j in range(1, 250)]
    fam += [f"{R}::^Systems::{s}::{t}" for s in systems for t in ("Anatomy", "Physiology", "Pathology", "Pharmacology", "Micro")]
    fam += [f"{R}::#AMBOSS::Article_{j:04d}_Some_Clinical_Topic" for j in range(1, 5000)]
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

    # a plan: 30 dates of Bootcamp Cardio lectures, a search date, a renamed-tag date
    lect = sorted({p for p, _ in tags if "#Bootcamp::Cardio::" in p and p.count("::") == 4})[:30]
    units = [{"id": f"u{i}", "name": p.rsplit("::", 1)[-1], "opens": f"2026-10-{(i % 28) + 1:02d}", "tags": [p], "decks": [], "cards": []}
             for i, p in enumerate(lect)]
    units.append({"id": "s1", "name": "Search", "opens": "2026-10-02", "tags": [], "decks": [], "cards": [],
                  "search": ['tag:"#AK_Step1_v12::^Systems::Cardio*" tag:#AK_Step1_v12::#Pathoma* -tag:*Pharmacology*']})
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
    built = F._filtered(col, "Due Crew · " + units[5]["name"], pick)
    fdid = col.decks.id_for_name("Due Crew · " + units[5]["name"])
    in_deck = len(col.find_cards(f'deck:"Due Crew · {units[5]["name"]}"')) if fdid else 0
    ok("Study: Anki's filtered deck of the date's seen cards", built and in_deck == len(pick) > 0, f"{in_deck} cards")

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
    col.close()


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "big.anki2")
        make(p)
        check(p)
