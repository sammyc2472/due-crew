"""The course PoC on Anki's own engine (`pip install anki` in a venv; no
aqt): a made-up deck shaped like a big shared deck (resources as #-tags,
cards suspended until opened), the calendar read, a lecture through the
jobs with no model and with a scripted one, opening and tagging in one
undo step, a tag split by lecture, plan text, and measuring.

    python -m unittest poc/tests/test_course_mac.py
"""
import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from course_mac import cal, course as C, engine as E, find as F, jobs as J, model as M, store  # noqa: E402

try:
    from anki.collection import Collection
except ImportError:  # the pure tests still run
    Collection = None

ROOT = "#Big_Step_v1"
VA = f"{ROOT}::#VideosA::Cardio::Heart_Failure"
VB = f"{ROOT}::#VideosB::Cardiology::Heart_Failure"
BP = f"{ROOT}::#BookC::07_Cardiovascular::04_Pathology::Heart_Failure"
BD = f"{ROOT}::#BookC::07_Cardiovascular::05_Pharm::Heart_Failure_Drugs"
DI = f"{ROOT}::#BookC::14_Renal::05_Pharm::Diuretics"
PV = f"{ROOT}::#BookC::07_Cardiovascular::03_Physiology::Pressure_Volume_Loops"
NP = f"{ROOT}::#BookC::14_Renal::03_Physiology::Hormones"
MI = f"{ROOT}::#BookC::03_Microbiology::Bacteria"
KEY = "DueCrew::Test_Plan"

CALENDAR = """BLOCK 2 · WEEK 1
Mon 10/26  8:00  LEC   Heart failure
    SLG 1  Define systolic and diastolic heart failure
    SLG 2  Explain how RAAS and sympathetic activation compensate
    SLG 5  Name the drugs that lower mortality in heart failure
Tue 10/27  8:00  LEC   Pressure-volume loops
    SLG 6  Draw a pressure-volume loop and read its parts
Wed 10/28 No class
Fri 10/30  9:00  QUIZ  Cardio quiz 1
"""


class FakeRunner(M.Runner):
    """A model that answers from a script, by job: the shapes come back as
    the real one's would (through conform), so the parsing is what's tested."""
    name = "fake"
    label = "Fake model"
    guided = True

    def __init__(self, script):
        self.script = script
        self.calls = []

    def ask(self, job, instructions, prompt, schema, max_tokens=None, timeout=None):
        self.calls.append((job, prompt))
        if job not in self.script:
            raise M.ModelError(f"no script for {job}", "unavailable")
        got = self.script[job](prompt) if callable(self.script[job]) else self.script[job]
        if isinstance(got, Exception):
            raise got
        return M.conform(got, schema), 5, json.dumps(got)


def nolog(*_a, **_k):
    pass


class PureTests(unittest.TestCase):
    today = dt.date(2026, 10, 18)

    def test_dates(self):
        for s, want in [("Mon 10/26 8:00 LEC Heart failure", "2026-10-26"), ("2026-10-26 | x", "2026-10-26"),
                        ("Oct 26 Heart failure", "2026-10-26"), ("26 October 2027 x", "2027-10-26"),
                        ("Monday, October 26th: Heart failure", "2026-10-26"), ("10/26/26 x", "2026-10-26"),
                        ("Jan 5 Neuro", "2027-01-05")]:
            d, _rest = cal.parse_date(s, self.today)
            self.assertEqual(d.isoformat(), want, s)
        self.assertIsNone(cal.parse_date("SLG 1 Define it", self.today)[0])
        self.assertEqual(cal.parse_date("26/10 x", self.today, day_first=True)[0].isoformat(), "2026-10-26")

    def test_read_lines(self):
        got = cal.read_lines(CALENDAR, self.today)
        self.assertEqual([(s["date"], s["kind"], s["title"]) for s in got],
                         [("2026-10-26", "lecture", "Heart failure"), ("2026-10-27", "lecture", "Pressure-volume loops"),
                          ("2026-10-30", "quiz", "Cardio quiz 1")])
        self.assertEqual([o["label"] for o in got[0]["objectives"]], ["SLG 1", "SLG 2", "SLG 5"])
        self.assertTrue(got[0]["objectives"][2]["text"].startswith("Name the drugs"))

    def test_chunks_keep_sessions_whole(self):
        text = "\n".join(f"Mon 10/{d:02d} LEC Topic {d}\n  SLG {d} " + "words " * 40 for d in range(1, 29))
        parts = cal.chunks(text, 600)
        self.assertGreater(len(parts), 3)
        for p in parts:
            self.assertIsNotNone(cal.parse_date(p.splitlines()[0], self.today)[0], p[:40])

    def test_conform_and_json(self):
        s = J.PICK_SCHEMA
        got = M.conform({"groups": [{"r": "2", "use": "WHOLE", "objectives": ["1", 3]}, {"r": 1, "use": "maybe"}]}, s)
        self.assertEqual(got, {"groups": [{"r": 2, "use": "whole", "objectives": [1, 3]}]})
        self.assertEqual(M.json_in('Sure!\n```json\n{"terms": ["a {b}", "c"]}\n```'), {"terms": ["a {b}", "c"]})
        with self.assertRaises(M.ModelError):
            M.json_in("no json here")
        self.assertIn('"use": "whole|part|no"', M.example(s))
        self.assertEqual(M.json_schema(J.WORDS_SCHEMA)["properties"]["terms"]["maxItems"], 14)
        self.assertEqual(M.kind_of("exceededContextWindowSize(...)"), "context")
        self.assertEqual(M.kind_of("guardrailViolation"), "guardrail")

    def test_words_and_matching(self):
        self.assertEqual(F.word("05_Elimination_Kinetics"), "Elimination Kinetics")
        self.assertEqual(F.resource_of(BD), ("BookC", "Cardiovascular › Pharm › Heart Failure Drugs"))
        self.assertTrue(F.same("arrhythmia", "arrhythmias"))
        self.assertTrue(F.hits(F.words("heart failure"), F.words("Heart Failure Drugs"), F.words("Cardio Heart Failure Drugs")))
        self.assertFalse(F.hits(F.words("heart failure"), F.words("Cardio"), F.words("Cardio")))
        self.assertEqual(F.term_hits("Loop diuretics in HF; furosemide", ["loop diuretics", "HF", "BNP"]), ["loop diuretics", "HF"])
        self.assertEqual(F.search_terms(['BNP', 'heart "failure"']), '("w:BNP" OR "w:heart failure")')
        self.assertEqual(F.plain("{{c1::Furosemide::drug}} blocks <b>NKCC2</b>"), "[c1: Furosemide] blocks NKCC2")
        self.assertEqual(J.clean_terms(["1. BNP", "BNP", "x", "lecture", "a very long term that has too many words"]), ["BNP"])
        self.assertEqual(C.key_tag(KEY, "SLG 12"), "DueCrew::Test_Plan::SLG_12")

    def test_store_roundtrip(self):
        d = tempfile.mkdtemp()
        try:
            store.save(d, "Sam", {"courses": [{"name": "x"}], "current": 0})
            self.assertEqual(store.load(d, "Sam")["courses"][0]["name"], "x")
            self.assertEqual(store.load(d, "Other"), {"courses": [], "current": 0})
        finally:
            shutil.rmtree(d)


FAKE_HELPER = r"""#!/usr/bin/env python3
# Speaks helper.swift's protocol: one JSON request a line in, one answer a line out.
import json, sys, time
for line in sys.stdin:
    req = json.loads(line)
    out = {"id": req.get("id")}
    if req["op"] == "probe":
        out.update(ok=True, available=True, context=4096)
    elif req["op"] == "pdf":
        out.update(ok=True, text="Mon 10/26 LEC Heart failure")
    elif "SLEEP" in req["prompt"]:
        time.sleep(5)
        out.update(ok=True, json="{}")
    elif "GUARD" in req["prompt"] and req.get("schema"):
        out.update(ok=False, error="guardrailViolation(...)")
    elif req.get("schema"):
        out.update(ok=True, json=json.dumps({"terms": ["heart failure", "BNP"]}), ms=12)
    else:
        out.update(ok=True, text='Sure: {"terms": ["from text"]}', ms=9)
    sys.stdout.write(json.dumps(out) + "\n")
    sys.stdout.flush()
"""


class HelperProtocolTests(unittest.TestCase):
    """HelperRunner against a stand-in for the built helper: the probe, a
    guided answer, the guardrail retry as plain text, a stuck call, a PDF."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.h = M.HelperRunner(self.dir, nolog, timeout=2)
        with open(self.h.bin, "w") as f:
            f.write(FAKE_HELPER.replace("#!/usr/bin/env python3", "#!" + sys.executable))
        os.chmod(self.h.bin, 0o755)
        with open(self.h.stamp, "w") as f:
            f.write(f"{self.h.source_hash()} permissive\n")

    def tearDown(self):
        self.h.close()
        shutil.rmtree(self.dir)

    def test_protocol(self):
        self.assertTrue(self.h.built())
        ok, why = self.h.available()
        self.assertTrue(ok, why)
        self.assertIn("4,096-token window", why)
        self.h.first = False
        got, ms, _raw = self.h.ask("words", "i", "Lecture: x", J.WORDS_SCHEMA)
        self.assertEqual(got, {"terms": ["heart failure", "BNP"]})
        got, _ms, _raw = self.h.ask("words", "i", "GUARD Lecture: x", J.WORDS_SCHEMA)
        self.assertEqual(got, {"terms": ["from text"]})  # refused with the shape, read from the plain answer
        with self.assertRaises(M.ModelError) as e:
            self.h.ask("words", "i", "SLEEP", J.WORDS_SCHEMA, timeout=1)
        self.assertEqual(e.exception.kind, "timeout")
        got, _ms, _raw = self.h.ask("words", "i", "again", J.WORDS_SCHEMA)  # a fresh helper after the stuck one
        self.assertEqual(got["terms"][0], "heart failure")
        self.assertEqual(self.h.pdf_text("/x.pdf"), "Mon 10/26 LEC Heart failure")

    def test_source_change_means_rebuild(self):
        with open(self.h.stamp, "w") as f:
            f.write("0000 permissive\n")
        self.assertFalse(self.h.built())
        self.assertEqual(M.pick_runner("auto", self.dir).name, "fm" if M.FmRunner().path else "none")


def _note(col, model, deck_id, fields, tags, suspend=True, study=False):
    n = col.new_note(model)
    for i, f in enumerate(fields):
        n.fields[i] = f
    n.tags = tags
    col.add_note(n, deck_id)
    cids = [c.id for c in n.cards()]
    if suspend:
        col.sched.suspend_cards(cids)
    if study:
        col.db.execute(f"UPDATE cards SET type = 2, queue = 2, ivl = 5 WHERE id IN ({','.join(map(str, cids))})")
    return n


@unittest.skipIf(Collection is None, "needs `pip install anki`")
class EngineTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.col = Collection(os.path.join(self.dir, "c.anki2"))
        col = self.col
        self.did = col.decks.id("Big Step 1")
        basic, cloze = col.models.by_name("Basic"), col.models.by_name("Cloze")
        self.n = {}
        add = lambda key, front, back, tags, **kw: self.n.setdefault(key, []).append(  # noqa: E731
            _note(col, basic, self.did, [front, back], tags, **kw))
        for i in range(8):
            add("va", f"Heart failure fact {i}: reduced ejection fraction", "HFrEF", [VA, BP] if i < 4 else [VA])
        add("va", "Heart failure leech: S3 gallop", "volume", [VA, "leech"])
        for i in range(6):
            add("vb", f"Heart failure video B {i}", "HF", [VB, VA] if i < 5 else [VB])
        for i in range(3):
            add("bp", f"Pathology of heart failure {i}: JVD and edema", "right failure", [BP])
        add("bd", "Spironolactone lowers mortality in heart failure", "aldosterone", [BD, f"{KEY}::SLG_5"])
        add("bd", "Beta blockers lower mortality in HFrEF", "metoprolol", [BD, f"{KEY}::SLG_5"])
        add("bd", "Digoxin relieves symptoms only", "no mortality benefit", [BD])
        add("bd", "Nitrate tolerance", "angina", [BD])
        for i in range(3):
            add("di", f"Thiazide fact {i}", "hypercalcemia", [DI])
        add("di", "Loop diuretic for congestion in heart failure", "furosemide", [DI, f"{KEY}::SLG_5"])
        add("pv", "Pressure-volume loop: the parts", "ESPVR", [PV])
        add("np", "BNP rises with ventricular stretch in heart failure", "natriuretic peptide", [NP])
        add("np", "ANP from atria", "stretch", [NP])
        for i in range(10):
            add("mi", f"Bacteria {i}", "gram stain", [MI])
        add("studied", "Heart failure studied card", "seen", [VA], suspend=False, study=True)
        c = col.new_note(cloze)
        c.fields[0] = "{{c1::Furosemide}} is a loop diuretic; {{c2::ACE inhibitors}} lower mortality in heart failure"
        c.tags = [DI]
        col.add_note(c, self.did)
        col.sched.suspend_cards([x.id for x in c.cards()])
        self.cloze = c
        self.idx = E.build_index(col, self.did)
        self.course = C.new_course("Block 2", self.did, "Big Step 1")
        for s in cal.read_lines(CALENDAR, dt.date(2026, 10, 18)):
            self.course["lectures"].append(C.new_lecture(s["date"], s["title"], s["kind"], s["objectives"]))
        self.hf = next(l for l in self.course["lectures"] if l["title"] == "Heart failure")

    def tearDown(self):
        self.col.close()
        shutil.rmtree(self.dir)

    def nids(self, key):
        return {n.id for n in self.n[key]}

    def run_lec(self, runner, lec=None):
        lec = lec or self.hf
        run = E.LectureRun(self.course, lec, self.idx, runner, nolog, {}, lambda: self.col)
        self.assertTrue(run.run_all())
        return lec

    def test_index(self):
        self.assertEqual(self.idx.under(VA), self.nids("va") | self.nids("vb") - {self.n["vb"][5].id} | self.nids("studied"))
        self.assertEqual(len(self.idx.cids_of({self.cloze.id})), 2)
        self.assertEqual(len(self.idx.cids_of({self.cloze.id}, {self.cloze.id: [2]})), 1)

    def test_no_model(self):
        lec = self.run_lec(M.NoModel())
        rows = {r["tag"] or r["name"]: r for r in lec["rows"]}
        self.assertEqual(lec["how"], {"terms": "rules", "pick": "rules", "read": lec["how"]["read"]})
        self.assertEqual(rows[VA]["use"], "whole")  # the title names it
        self.assertTrue(rows[VA]["on"])
        self.assertNotIn(MI, rows)
        self.assertEqual(lec["terms"][0], "Heart failure")
        self.assertNotIn("heart", lec["terms"])  # the title's words alone match too much
        s = C.summary(self.course, lec, self.idx)
        self.assertGreater(s["new"], 0)
        self.assertEqual(s["event"], ("Cardio quiz 1", 4))
        self.assertGreaterEqual(s["leeches"], 1)
        self.assertGreaterEqual(s["open_already"], 1)

    def scripted(self, read_fail=False):
        def pick(prompt):
            groups = []
            for line in prompt.splitlines():
                if not line.startswith("G"):
                    continue
                r = int(line[1:line.index(".")])
                use = ("part" if "Drugs" in line or "Diuretics" in line or "Hormones" in line
                       else "no" if "VideosB" in line else "whole")
                groups.append({"r": r, "use": use, "objectives": [1, 2] if use == "whole" else [3]})
            return {"groups": groups + [{"r": 99, "use": "whole", "objectives": []}]}  # 99: wasn't shown, dropped

        def read(prompt):
            if read_fail:
                return M.ModelError("guardrailViolation", "guardrail")
            cards = []
            for line in prompt.splitlines():
                if not line.startswith("C") or "." not in line[:5]:
                    continue
                c = int(line[1:line.index(".")])
                fits = any(w in line.lower() for w in ("mortality", "loop diuretic", "bnp"))
                obj = 2 if "bnp" in line.lower() else 3
                cards.append({"c": c, "fits": fits, "objective": obj if fits else 0,
                              "clozes": [2] if "[c2:" in line else []})
            return {"cards": cards}
        return FakeRunner({"words": {"terms": ["heart failure", "HFrEF", "BNP", "loop diuretic", "mortality", "pressure-volume loops", "lecture"]},
                           "pick": pick, "read": read})

    def test_scripted_model(self):
        runner = self.scripted()
        lec = self.run_lec(runner)
        self.assertEqual([j for j, _p in runner.calls][:2], ["words", "pick"])
        self.assertNotIn("lecture", lec["terms"])
        rows = {r["tag"] or r["name"]: r for r in lec["rows"]}
        self.assertEqual(rows[VB]["use"], "no")
        self.assertFalse(rows[VB]["on"])
        bd = rows[BD]
        self.assertEqual(bd["use"], "part")
        fits = {int(n) for n, v in bd["fit"].items() if v[0]}
        self.assertLessEqual({self.n["bd"][0].id, self.n["bd"][1].id}, fits)  # the mortality ones
        self.assertNotIn(self.n["bd"][3].id, fits)  # not nitrates
        di = rows[DI]  # "loop diuretic" names Diuretics
        self.assertEqual(di["use"], "part")
        self.assertEqual(di["fit"][str(self.cloze.id)], [True, 3, [2]])  # one cloze of two
        self.assertEqual(len(C.row_cids(di, self.idx)), len(C.row_nids(di, self.idx)))  # the cloze brings one card
        pv = rows[PV]  # "pressure-volume loops" names it, but Tue 27's title names it outright
        self.assertEqual(pv["use"], "later")
        self.assertFalse(pv["on"])
        self.assertIn("Pressure-volume loops", pv["later"])
        # the prompts never carry an id
        for _job, p in runner.calls:
            for n in self.idx.guid:
                self.assertNotIn(str(n), p)
        text = C.plan_text(self.course, self.idx)
        self.assertIn(f"tag | SLG 5 | notes:{self.idx.guid[self.n['bd'][0].id]}", text)
        self.assertIn(f"tag | SLG 5 | cards:{self.idx.guid[self.cloze.id]}:2", text)
        self.assertIn(f"tag:{BD} in SLG 5", text)
        self.assertIn(f"tag:{VA}", text)
        self.assertIn("| for Cardio quiz 1", text)
        self.assertIn("2026-10-30 | event | Cardio quiz 1", text)
        self.assertRegex(text, r"# 2026-10-26: .*VideosA Cardio › Heart Failure, all \d+")
        lines = text.splitlines()
        self.assertLess(max(i for i, l in enumerate(lines) if l.startswith("tag |")),
                        min(i for i, l in enumerate(lines) if l.startswith("2026-")))

    def test_read_refused_stays_unread(self):
        lec = self.run_lec(self.scripted(read_fail=True))
        part = [r for r in lec["rows"] if r["use"] == "part" and r["kind"] == "tag"]
        self.assertTrue(part)
        self.assertTrue(all(r["unread"] and not r["on"] for r in part))
        self.assertIn("unread", lec["how"]["read"])

    def test_context_error_halves_the_batch(self):
        sizes = []

        def read(prompt):
            n = sum(1 for l in prompt.splitlines() if l.startswith("C") and "." in l[:5])
            sizes.append(n)
            if n > 2:
                return M.ModelError("exceededContextWindowSize", "context")
            return {"cards": [{"c": i, "fits": True, "objective": 1, "clozes": []} for i in range(1, n + 1)]}
        notes = [{"nid": i, "text": f"card {i}", "clozes": []} for i in range(1, 9)]
        fits, how, unread = J.read(FakeRunner({"read": read}), self.hf, notes, ["x"], nolog, batch=8)
        self.assertEqual(sorted(fits), list(range(1, 9)))
        self.assertEqual(unread, [])
        self.assertEqual(sizes[:3], [8, 4, 2])

    def test_open_and_tag_one_undo_each(self):
        lec = self.run_lec(M.NoModel())
        cids = C.lecture_cids(lec, self.idx)
        ids = E.openable(self.col, cids)
        self.assertTrue(ids)
        leech = self.idx.cids_of({self.n["va"][8].id})
        self.assertFalse(set(leech) & set(ids))
        n = E.open_cards(self.col, ids, "Course: Heart failure")
        self.assertEqual(n, len(ids))
        self.assertEqual(self.col.db.scalar(f"SELECT count() FROM cards WHERE queue = -1 AND id IN ({','.join(map(str, ids))})"), 0)
        self.col.undo()
        self.assertEqual(self.col.db.scalar(f"SELECT count() FROM cards WHERE queue = -1 AND id IN ({','.join(map(str, ids))})"), len(ids))
        tags = E.lecture_tags(self.course, lec, self.idx)
        self.assertIn("Course::Block_2::2026-10-26_Heart_failure", tags)
        got = E.tag_notes(self.col, tags, "Course: tag Heart failure")
        self.assertGreater(got, 0)
        some = next(iter(tags.values()))[0]
        self.assertIn("Course::Block_2::2026-10-26_Heart_failure", self.col.get_note(some).tags)
        self.col.undo()
        self.assertNotIn("Course::Block_2::2026-10-26_Heart_failure", self.col.get_note(some).tags)

    def test_split_tag_and_reads(self):
        lec = self.run_lec(self.scripted())
        sp = E.split_tag(self.course, self.idx, DI)
        self.assertIn(lec["id"], sp["by"])
        self.assertTrue(sp["rest_nids"])
        whole, owner = E.course_as_lecture(self.course)
        self.assertEqual(len(owner), len(whole["objectives"]))
        pv = next(l for l in self.course["lectures"] if l["title"].startswith("Pressure"))
        first_pv = owner.index(pv)
        fits = {sp["rest_nids"][0]: (True, first_pv + 1, [])}
        added = E.add_reads(self.course, DI, self.idx, "BookC", fits, owner)
        self.assertEqual(added, {pv["id"]: 1})
        row = next(r for r in pv["rows"] if r["tag"] == DI)
        self.assertEqual(row["fit"][str(sp["rest_nids"][0])][1], 1)  # SLG 6 is Pressure-volume loops' first

    def test_measure(self):
        score, secs, lec = E.measure_objective(self.col, self.idx, self.scripted(), nolog, {}, KEY, "SLG 5",
                                               "Name the drugs that lower mortality in heart failure")
        self.assertEqual(score["key"], 3)
        self.assertGreater(score["found"], 0)
        self.assertLessEqual(score["right"], 1)


if __name__ == "__main__":
    unittest.main()
