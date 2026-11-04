"""Magic search (3.9.7): what a box says (magic.py: topics by the deck's own
tags, its resources and short names, filters, how many, leave out, IDs,
what's coming up, a plan's words and lines), the window's logic
(magic_flow.Search on a made-up deck: what it finds, Study now, Keep as a
filtered deck, Add to a filtered deck, Unsuspend, Put on days, the rows,
Undo, the first-time card) and its ways in (the You box's head, Settings,
the board's command). The rules were tried on a big shared deck's export
(28k notes, 45k tags), restated here with made-up tags. Standard library
only: python3 tests/test_magic.py."""

import datetime
import os
import re
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import fakes  # noqa: E402

STORE = fakes.FakeWorker()
fakes.install_fake_requests(STORE)
fakes.install_fake_aqt()

from due_crew import magic as M                               # noqa: E402
from due_crew import magic_flow as MF                         # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECKS = []
TODAY = datetime.date(2026, 11, 4)  # a Wednesday


def check(name, cond, detail=""):
    CHECKS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond or detail == "" else f"\n     {detail}"))


R = "#Big_Step1::"
TAGS = {  # tag: cards (made up: a big shared deck's shapes, its resources, its short names in brackets)
    "#Videos::03_Cardio::05_Heart_Failure": 10, "#Videos::03_Cardio::05_Heart_Failure::01_Systolic": 6,
    "#Path::Cardio::Heart_Failure": 7, "#Videos::09_Pharm::Heart_Failure_Drugs": 6, "#M&M::Cardio::Heart_Failure": 4,
    "#Notes::Renal::Acute_Kidney_Injury_(AKI)": 8, "#Notes::Renal::Intro_to_Acute_Kidney_Injury_(AKI)": 3,
    "#Path::Renal::AKI": 5, "#M&M::Renal": 6, "#M&M::Renal::Nephritic_Syndrome": 3,
    "#Path::Heme::Immune_Thrombocytopenic_Purpura_(ITP)": 6, "#Bootcamp::Derm::Isotretinoin_Therapy_Precautions": 2,
    "#Path::Cardio::Myocardial_Infarction": 9, "#Path::Genetics::Male_Infertility": 3, "#Images::^Missing_image": 20,
    "#Path::Endo::Graves_Disease": 5, "#Path::Onc::Tumor_Grade": 4,
    "#Path::Endo::Type_II_Diabetes": 7, "#Path::Endo::Diabetes::02_Type_1_Diabetes": 5,
    "#PathBook::03_Neoplasia::01_Neoplasia_Basics": 6, "#PathBook::03_Neoplasia::03_Tumor_Progression": 4,
    "#PathBook::04_Hemostasis::01_Bleeding": 5, "#PathBook::05_RBC::02_Microcytic::part_3": 3,
    "#ChartsMicro::Staph::Staph_Aureus": 6, "#ChartsMicro::Strep::Strep_Pneumoniae": 4,
    "#ChartsPharm::Antibiotics::Penicillins": 5,
    "#QuickRef::Cardiovascular": 40, "#QuickRef::Cardiomyopathies": 4,
    "#Path::Pharm::Beta_Blockers": 5, "#Path::Muscle::Muscle_Myopathies": 3,
    "#Path::Endo::Thyroid": 9, "#Path::Endo::Thyroiditis": 4,
    "#Path::Heme::Platelets": 8, "#Path::Heme::Platelet_Disorders": 6, "#Path::Heme::Anemia": 12,
    "#QBank::Step::10234": 2, "#QBank::Step::10235": 1,
}


class Idx:
    """A DeckIndex of the made-up deck: one card a note, the states the window reads."""

    def __init__(self):
        self.did, self.name = 1, "Big Step 1"
        self.by_tag, self.tag_names, self.cards, self.order = {}, {}, {}, {}
        self.due_now, self.leech, self.nid_of, self.state = set(), set(), {}, {}
        cid = 1000
        for i, (t, n) in enumerate(sorted(TAGS.items())):
            for k in range(n):
                cid += 1
                full = R + t
                self.by_tag.setdefault(full.lower(), []).append(cid)
                self.tag_names[full.lower()] = full
                new = (cid % 3) != 0
                susp = new and (cid % 2 == 0)
                queue, ctype = (-1 if susp else 0, 0) if new else (2, 2)
                self.cards[cid] = (queue, ctype)
                self.order[cid] = (ctype == 0, cid, cid)
                self.nid_of[cid] = cid + 1583285000000
                if not new and cid % 4 == 0:
                    self.due_now.add(cid)
                self.state[cid] = {"text": t.split("::")[-1].lower().replace("_", " "), "missed": cid % 7 == 0 and not new,
                                   "added": 3 if cid % 11 == 0 else 99}
        self.leech = {c for c in self.cards if c % 37 == 0}
        self.tag_keys = sorted(self.by_tag)
        self.home = set(self.cards)
        self.by_deck = {1: sorted(self.cards)}
        self._searches = {}

    def tag_cards(self, path):
        low = str(path).lower()
        out = set(self.by_tag.get(low, ()))
        for k, v in self.by_tag.items():
            if k.startswith(low + "::"):
                out.update(v)
        return out

    def tree(self):
        return [[self.tag_names[k], len(v)] for k, v in sorted(self.by_tag.items())], [[self.name, len(self.cards)]]

    def match(self, u, swap=None, doc=None):
        out = set()
        for t in u.get("tags") or ():
            out |= self.tag_cards(t)
        return out


IDX = Idx()
TREE = M.Tree(list(IDX.tag_names.values()), IDX.tag_cards)
PLANS = [{"id": "p1", "name": "Heme 2",
          "units": [{"id": "u1", "name": "Platelets", "opens": "2026-11-05", "for": "e1"},
                    {"id": "u2", "name": "Anemia", "opens": "2026-11-09", "for": "e1"}],
          "events": [{"id": "e1", "name": "Heme quiz", "day": "2026-11-10"}]}]


def read(text):
    return M.read(text, TREE, TODAY, [(1, "Big Step 1"), (2, "Big Step 1::Heme lectures")], PLANS)


def ticked(r):
    return [g["name"] for g in r["groups"] if g["on"]]


def offered(r):
    return [g["name"] for g in r["groups"] if not g["on"]]


# ---- what a box says ----

def test_topics_by_the_decks_tags():
    r = read("heart failure")
    g = r["groups"][0]
    check("a topic: one chip, every tag whose last part says it, a parent covering its children; drugs offered",
          ticked(r) == ["Heart Failure"] and len(g["tags"]) == 3 and "Heart Failure Drugs" in offered(r)
          and g["cards"] == 27, (ticked(r), offered(r), g))
    r = read("hf drugs")
    check("initials and a word: Heart Failure Drugs", ticked(r) == ["Heart Failure Drugs"], r["groups"])
    r = read("anemai")
    check("one letter off still finds it", ticked(r) == ["Anemia"], r["groups"])
    r = read("platelets and anemia")
    check("and: two topics, each ticked", set(ticked(r)) >= {"Platelets", "Anemia"} and {g["seg"] for g in r["groups"]} == {0, 1}, r["groups"])


def test_the_decks_own_short_names():
    r = read("aki")
    check("aki: what the deck writes beside (AKI), its bracket off the name, the tag called AKI with it",
          ticked(r)[:1] == ["Acute Kidney Injury"] and "#Big_Step1::#Path::Renal::AKI" in r["groups"][0]["tags"]
          and "Intro to Acute Kidney Injury" in ticked(r), r["groups"])
    r = read("itp")
    check("itp: the deck says it's Immune Thrombocytopenic Purpura; another name with those letters only offered",
          ticked(r) == ["Immune Thrombocytopenic Purpura"] and "Isotretinoin Therapy Precautions" in offered(r), r["groups"])
    r = read("mi")
    check("two letters the deck never writes beside a name: offered, none ticked",
          not ticked(r) and {"Myocardial Infarction", "Male Infertility"} <= set(offered(r)), r["groups"])


def test_how_well_a_name_is_said():
    r = read("graves")
    check("a name said beats one a letter off", ticked(r) == ["Graves Disease"] and "Tumor Grade" in offered(r), r["groups"])
    r = read("thyroid")
    check("a one-word name begun isn't the word said (thyroid isn't thyroiditis)",
          ticked(r) == ["Thyroid"] and "Thyroiditis" in offered(r), r["groups"])
    r = read("type 2 diabetes")
    check("type 2 diabetes: a roman number is a number; a short number is a word, not how many",
          ticked(r) == ["Type II Diabetes"] and r["limit"] is None and "Type 1 Diabetes" not in ticked(r), (r["groups"], r["limit"]))
    r = read("beta blockers")
    check("a topic whose initials look like a resource's stays a topic", ticked(r) == ["Beta Blockers"] and not r["res"], r)


def test_resources_the_deck_has():
    r = read("m&m heart failure")
    check("a resource by its letters: the topic in it alone",
          ticked(r) == ["Heart Failure"] and r["groups"][0]["tags"] == ["#Big_Step1::#M&M::Cardio::Heart_Failure"], r["groups"])
    r = read("mice and men renal")
    check("a resource by its words' initials, with its and", ticked(r) == ["Renal"] and r["res"] == ["#m&m"], r)
    r = read("muscle myopathies")
    check("two words with those initials but no and: a topic", ticked(r) == ["Muscle Myopathies"] and not r["res"], r)
    r = read("charts")
    check("a word that begins a family of resources: a chip each, ticked",
          sorted(ticked(r)) == ["ChartsMicro", "ChartsPharm"], r["groups"])
    r = read("charts micro staph")
    check("a resource by its letters whole, then its topic (its parent part covering its children)", ticked(r) == ["Staph"], r["groups"])
    r = read("quick ref cardio")
    check("in a resource, a word that begins one-word names: the big one", ticked(r) == ["Cardiovascular"]
          and "Cardiomyopathies" in offered(r), r["groups"])


def test_chapters_by_their_numbers():
    r = read("pathbook chapter 3")
    check("chapter 3: the resource's part numbered 3, not a section 3 or a part 3", ticked(r) == ["Neoplasia"], r["groups"])
    r = read("pathbook chapter 4")
    check("chapter 4", ticked(r) == ["Hemostasis"], r["groups"])


def test_filters_how_many_and_leaving_out():
    r = read("anemia I missed this week")
    check("a filter: missed this week", [f["k"] for f in r["filters"]] == ["m7"] and ticked(r) == ["Anemia"], r)
    r = read("10 new platelets")
    check("a number first: how many", r["limit"] == 10 and [f["k"] for f in r["filters"]] == ["new"], r)
    r = read("give me 5 new platelets")
    check("after words that say nothing, still how many", r["limit"] == 5, r["limit"])
    r = read("platelets but not itp")
    check("but not: struck, its tags taken out", [g["name"] for g in r["neg"]] == ["Immune Thrombocytopenic Purpura"]
          and "Platelets" in ticked(r), r["neg"])
    r = read("due tomorrow")
    q = M.filters_q(r["filters"])
    check("filters alone are Anki's own words", r["kind"] == "words" and q == "prop:due=1", q)
    check("every filter on the row has its words", all(M.filter_label({"k": k}) and M.filter_q({"k": k}) for k in M.ROW))


def test_ids_searches_and_plan_lines():
    r = read("10234 10235 99999")
    check("QIDs", r["kind"] == "ids" and r["qids"] == ["10234", "10235", "99999"], r)
    r = read("qbank 10234 10235")
    check("QIDs with their bank's name: that bank", r["kind"] == "ids" and r["bank"] == "#qbank", r)
    r = read("Question ID: 20769")
    check("a QID as a bank shows it", r["kind"] == "ids" and r["qids"] == ["20769"], r)
    r = read("1583285845282")
    check("a long number: a note or card id", r["kind"] == "ids" and r["ids"] == ["1583285845282"], r)
    r = read('tag:foo OR "deck:bar"')
    check("Anki's own search, as it is", r["kind"] == "search", r)
    r = read("2026-11-05 | Platelets | tag:x\n2026-11-06 | ITP | tag:y\nsome note")
    check("lines with days and bars: plan text", r["kind"] == "plantext" and len(r["lines"]) == 3, r["kind"])
    r = read("kidney stones")
    check("words no tag has: the cards' text", r["text"] == "kidney stones" and not r["groups"]
          and M.text_q(r["text"]) == '"kidney" "stone"', r)


def test_whats_coming_up():
    r = read("I have a quiz on Friday")
    check("a quiz: a date on a plan", r["kind"] == "do" and r["acts"][0]["k"] == "event" and r["acts"][0]["day"] == "2026-11-06"
          and r["acts"][0]["name"] == "Quiz", r["acts"])
    r = read("quiz friday on platelets and anemia")
    check("a quiz with topics: they go on the days before it", [a["k"] for a in r["acts"]] == ["event", "before"]
          and set(ticked(r)) >= {"Platelets", "Anemia"}, r["acts"])
    r = read("heme quiz friday on itp")
    check("the word before a quiz is its name, not glued to its topics", r["acts"][0]["name"] == "Heme quiz"
          and ticked(r) == ["Immune Thrombocytopenic Purpura"], (r["acts"], r["groups"]))
    r = read("my exam is december 12")
    check("an exam far off: Settings' exam", r["acts"] == [{"k": "exam", "day": "2026-12-12"}], r["acts"])
    r = read("I'm away till monday")
    check("away: from tomorrow to the day", r["acts"] == [{"k": "away", "from": "2026-11-05", "to": "2026-11-09"}], r["acts"])
    r = read("push my plan back 2 days")
    check("push my plan back", r["acts"] == [{"k": "slide", "days": 2}], r["acts"])
    r = read("the heme quiz")
    check("a quiz a plan has, by its name: its dates' cards", r["plan"] and r["plan"]["uids"] == ["u1", "u2"] and not r["acts"], r)
    r = read("heme quiz on friday")
    check("a quiz on another day than the plan's is a new one", r["acts"][0]["k"] == "event" and not r["plan"], r)
    r = read("tomorrow's set")
    check("tomorrow's set: the plan's date that opens tomorrow", r["plan"] and r["plan"]["uids"] == ["u1"], r["plan"])


def test_days():
    check("split: the first days a card more", M.split(list(range(7)), ["2026-11-06", "2026-11-05"])
          == [("2026-11-05", [0, 1, 2, 3]), ("2026-11-06", [4, 5, 6])])
    check("a day's set's name", M.day_name("Platelets", 1, 3) == "Platelets 2 of 3" and M.day_name("Platelets", 0, 1) == "Platelets")
    check("a span in words", M.words_span("2026-11-05", "2026-11-09") == "Thu 5 – Mon 9 Nov")
    check("add_cids keeps one list after its own search",
          MF.add_cids("(tag:x) OR cid:3,1", [2, 3]) == "(tag:x) OR cid:1,2,3" and MF.add_cids("deck:A", [5]) == "(deck:A) OR cid:5")


# ---- the window's logic, on the made-up deck ----

class Ops(MF.Ops):
    """The collection and the requests, as the window asks for them, written down."""

    def __init__(self):
        self.log, self.seen, self.recents = [], False, []

    def today(self):
        return TODAY

    def decks(self):
        return [(1, "Big Step 1")]

    def all_decks(self):
        return [(1, "Big Step 1")]

    def deck_name(self, did):
        return "Big Step 1"

    def home_deck(self, cid):
        return 1

    def deck_cards(self, did, idx):
        return set(idx.home)

    def filtered_decks(self):
        return [(9, "QBank misses")]

    def default_deck(self, choices):
        return 1

    def index(self, did):
        return IDX

    def top_of(self, did):
        return 1

    def find(self, q):
        """Anki's search, for the words the window sends it: the deck, filters, text, ids."""
        got = set(IDX.cards)
        for tok in re.findall(r'"[^"]*"|\S+', q):
            t = tok.strip('"')
            if t.startswith("deck:"):
                continue
            if t.startswith(("nid:", "cid:")):
                ids = {int(x) for x in t[4:].split(",") if x}
                got &= {c for c in IDX.cards if (IDX.nid_of[c] if t[0] == "n" else c) in ids}
            elif t == "is:new":
                got &= {c for c in got if IDX.cards[c][1] == 0}
            elif t == "-is:new":
                got &= {c for c in got if IDX.cards[c][1] != 0}
            elif t == "is:suspended":
                got &= {c for c in got if IDX.cards[c][0] == -1}
            elif t == "is:due":
                got &= IDX.due_now
            elif t.startswith("rated:"):
                got &= {c for c in got if IDX.state[c]["missed"]}
            elif t.startswith("added:"):
                got &= {c for c in got if IDX.state[c]["added"] <= int(t.split(":")[1])}
            elif t == "tag:leech":
                got &= IDX.leech
            else:
                got &= {c for c in got if t.lower() in IDX.state[c]["text"]}
        return got

    def followed(self):
        return []

    def plan_idx(self, pid):
        return None

    def day_loads(self, idx, today, days=MF.DAYS):
        return [5, 9, 3, 8, 2, 7, 6, 9, 4, 8, 1, 6, 7, 5][:days]

    def signed_in(self):
        return True

    def my_plans(self, done):
        done([{"id": "pB", "name": "Block 3", "role": "owner", "followers": 5, "following": True,
               "doc": {"deck": "Big Step 1"}}])

    def write_plan(self, pid, ops, idx, done, name=None, deck=None):
        self.log.append(("write", pid, ops))
        done(("waiting", pid, None, len(ops)) if pid == "pB" else ("saved", pid or "pMine", 7, "made" if pid is None else ""))

    def undo_save(self, pid, version, done):
        self.log.append(("undo_save", pid, version))
        done(True)

    def undo_draft(self, pid, n):
        self.log.append(("undo_draft", pid, n))
        return True

    def settings(self, parts):
        self.log.append(("settings", parts))
        return {"exam_date": ""}

    def put_back(self, old):
        self.log.append(("put_back", old))

    def set_days(self, pid, done, **fields):
        self.log.append(("set_days", pid, fields))
        done(fields)

    def unsuspend(self, cids):
        n = sum(1 for c in cids if IDX.cards[c][0] == -1 and c not in IDX.leech)
        self.log.append(("uns", len(cids)))
        return n

    def study(self, cids, name):
        self.log.append(("study", list(cids), name))
        return True

    def keep(self, name, q, cids, limit, order):
        self.log.append(("keep", name, q, limit))
        return 77

    def add_to(self, did, cids):
        self.log.append(("add_to", did, list(cids)))
        return 12

    def undo_anki(self, label):
        self.log.append(("undo_anki", label))
        return True

    def browse(self, cids, q=None):
        self.log.append(("browse", len(cids)))

    def refs(self, cids):
        return [[f"g{c}", 0] for c in cids]

    def open_plans(self, pid):
        self.log.append(("open_plans", pid))

    def seen_intro(self):
        return self.seen

    def saw_intro(self):
        self.seen = True

    def recent(self):
        return list(self.recents)

    def note_recent(self, text):
        if text and text not in self.recents:
            self.recents.insert(0, text)


def window():
    ops = Ops()
    face = MF.Search(ops)
    pushed = []
    face.push = lambda: pushed.append(1)
    closed = []
    face.close_win = lambda: closed.append(1)
    MF.plan_flow._pcfg = lambda: {}  # no My plan made on this computer yet
    return face, ops, closed


def test_the_window_finds():
    face, ops, _closed = window()
    v = face.view()
    check("first time: the how-to card; the filters row always there, every filter off",
          v["intro"] and [f["k"] for f in v["filters"]] == list(M.ROW) and not any(f["on"] for f in v["filters"]), v["filters"])
    face.on("intro", {"show": False})
    check("Got it: seen, once a person (an account key)", ops.seen and not face.view()["intro"])
    face.on("type", {"text": "heart failure"})
    v = face.view()
    hf = IDX.tag_cards(R + "#Videos::03_Cardio::05_Heart_Failure") | IDX.tag_cards(R + "#Path::Cardio::Heart_Failure") \
        | IDX.tag_cards(R + "#M&M::Cardio::Heart_Failure")
    check("its cards are its tags' in the deck's index, counted", v["count"]["n"] == len(hf) == 27, v["count"])
    check("a named topic with several tags shows them, open", v["chips"][0]["open"] and len(v["chips"][0]["list"]) == 3, v["chips"][0])
    face.on("tag", {"t": R + "#Path::Cardio::Heart_Failure"})
    check("unticking one of its tags leaves its cards out", face.view()["count"]["n"] == 20)
    face.on("chip", {"i": 1})
    check("ticking an offered chip adds it", face.view()["count"]["n"] == 26)
    face.on("filter", {"k": "new"})
    v = face.view()
    check("a filter from the row: on, and the cards kept to it", any(f["k"] == "new" and f["on"] for f in v["filters"])
          and v["count"]["seen"] == 0 and v["count"]["n"] > 0, v["count"])
    face.on("filter", {"k": "seen"})
    v = face.view()
    check("new and seen don't both stay on", [f["k"] for f in v["filters"] if f["on"]] == ["seen"], v["filters"])
    face.on("type", {"text": ""})
    face.on("filter", {"k": "due"})
    check("a filter alone: the deck's cards", face.view()["count"]["n"] == len(IDX.due_now), face.view()["count"])
    face.on("type", {"text": "10 new platelets"})
    check("how many: 10", face.view()["count"]["n"] == 10)
    face.on("type", {"text": "platelets but not itp"})
    itp = IDX.tag_cards(R + "#Path::Heme::Immune_Thrombocytopenic_Purpura_(ITP)")
    check("but not: none of its cards", not (set(face.cards()[0]) & itp) and face.cards()[0])
    face.on("type", {"text": "10234 10235 99999"})
    v = face.view()
    check("QIDs: their cards, a number that isn't one said", v["count"]["n"] == 3 and any("99999" in x for x in v["lines"]), v)
    c0 = sorted(IDX.cards)[5]
    face.on("type", {"text": str(IDX.nid_of[c0])})
    check("a note id finds its card", face.cards()[0] == [c0], face.cards()[0])
    face.on("type", {"text": "mi"})
    check("nothing ticked: a line says to tap", any("tap the ones" in x for x in face.view()["lines"]), face.view()["lines"])
    face.on("type", {"text": "kidney stones"})
    check("words no tag or card has: said, in the deck", face.view()["lines"] and "Big Step 1" in face.view()["lines"][0])


def test_the_window_does():
    face, ops, closed = window()
    face.on("intro", {"show": False})
    face.on("type", {"text": "anemia"})
    cids = face.cards()[0]
    face.on("study", {})
    st = next(x for x in ops.log if x[0] == "study")
    want = [c for c in cids if c not in IDX.leech and (IDX.cards[c][1] == 0 or c in IDX.due_now)]
    check("Study now: new and due, never a leech, its deck named for the topic; the window goes",
          st[1] == want and st[2] == "Anemia" and closed, st)
    face.on("how", {"how": "all"})
    face.on("study", {})
    st = [x for x in ops.log if x[0] == "study"][-1]
    check("All of them: every one but a leech", st[1] == [c for c in cids if c not in IDX.leech])
    face.on("how", {"how": "nd"})
    face.on("keep", {"name": "Anemia for Friday"})
    k = next(x for x in ops.log if x[0] == "keep")
    check("Keep as a filtered deck: named, its cards and New and due live (Rebuild fills it)",
          k[1] == "Anemia for Friday" and k[2].startswith("(cid:") and k[2].endswith("(is:new OR is:due)"), k)
    check("Keep: said, with Undo", face.view()["said"]["undo"] == "anki")
    face.on("undo", {})
    check("Undo: Anki's own undo of that step", ("undo_anki", "Due Crew: Anemia for Friday") in ops.log, ops.log[-1])
    face.on("addto", {"did": 9})
    a = next(x for x in ops.log if x[0] == "add_to")
    check("Add to a filtered deck I have: these cards into it", a[1] == 9 and a[2] and "QBank misses" not in face.view()["said"]["text"]
          or "12 cards" in face.view()["said"]["text"], (a, face.view()["said"]))
    check("the filtered decks I have are offered", face.view()["filtered"] == [{"did": 9, "name": "QBank misses"}])
    face.on("uns", {})
    check("Unsuspend: said", "Unsuspended" in face.view()["said"]["text"], face.view()["said"])
    face.on("browse", {})
    check("Browse", ops.log[-1][0] == "browse")


def test_put_on_days():
    face, ops, _closed = window()
    face.on("ready", {})
    face.on("type", {"text": "platelets"})
    face.on("days", {"show": True})
    v = face.view()
    check("the day picker: two weeks, each day's load, the light ones marked", len(v["days"]["list"]) == 14
          and sum(1 for d in v["days"]["list"] if d["light"]) == 3 and v["days"]["list"][0]["today"], v["days"]["list"][:3])
    face.on("day", {"iso": "2026-11-06"})
    face.on("day", {"iso": "2026-11-09"})
    face.on("day", {"iso": "2026-11-07"})
    face.on("day", {"iso": "2026-11-07"})  # tapped again: off
    v = face.view()
    n = v["count"]["n"]
    check("tap as many days as you like; a tap again takes one off; the split said",
          [e["iso"] for e in v["days"]["each"]] == ["2026-11-06", "2026-11-09"] and sum(e["n"] for e in v["days"]["each"]) == n, v["days"]["each"])
    check("where it goes: My plan (it starts it), or a plan I write (its followers wait for Review and send)",
          [d["key"] for d in v["dests"]] == ["mine", "pB"] and v["dests"][0]["note"] == "starts it"
          and "Review and send" in v["dests"][1]["note"], v["dests"])
    face.on("put", {})
    w = next(x for x in ops.log if x[0] == "write")
    check("Put on 2 days: a date a day on My plan, made first, each its share of the cards",
          w[1] is None and [o["op"] for o in w[2]] == ["add_date", "add_picks", "add_date", "add_picks"]
          and w[2][0]["day"] == "2026-11-06" and w[2][0]["name"] == "Platelets 1 of 2"
          and sum(len(o["cards"]) for o in w[2] if o["op"] == "add_picks") == n, w)
    s = face.view()["said"]
    check("said, with Undo and the plan", "My plan" in s["text"] and "starts here" in s["text"] and s["undo"] == "save" and s["open"] == "pMine", s)
    face.on("undo", {})
    check("Undo: the builder's undo of that save", ("undo_save", "pMine", 7) in ops.log)
    ops2 = face.day_ops(face.cards()[0], ["2026-11-05"], "Platelets")
    check("one day, whole topics: a date of its tags (cards added to them later come too)",
          ops2 == [{"op": "add_date", "day": "2026-11-05", "name": "Platelets",
                    "tags": [R + "#Path::Heme::Platelets", R + "#Path::Heme::Platelet_Disorders"]}], ops2)
    face.on("dest", {"key": "pB"})
    face.on("day", {"iso": "2026-11-12"})
    face.on("put", {})
    w = [x for x in ops.log if x[0] == "write"][-1]
    s = face.view()["said"]
    check("to a plan I write with followers: it waits in Review and send; Undo takes it back",
          w[1] == "pB" and "Review and send" in s["text"] and s["undo"] == "draft", (w[1], s))
    face.on("undo", {})
    check("…taken back", ops.log[-1][0] == "undo_draft" and ops.log[-1][1] == "pB")


def test_rows_for_whats_coming_up():
    face, ops, _closed = window()
    face.on("type", {"text": "quiz friday on platelets and anemia"})
    v = face.view()
    check("a quiz with topics: two rows, the quiz (My plan or yours) and its topics on the days before",
          [r["k"] for r in v["rows"]] == ["event", "before"] and v["rows"][0]["choose"], v["rows"])
    check("the days before it are picked already", face.picked == ["2026-11-05"] and v["days"]["each"], face.picked)
    face.on("act", {"i": 0})
    w = next(x for x in ops.log if x[0] == "write")
    check("Add: the quiz is an event on My plan", w[2] == [{"op": "add_event", "day": "2026-11-06", "name": "Quiz"}], w)
    check("its row says it's done, with Undo", face.view()["rows"][0]["done"])
    face.on("type", {"text": "my exam is december 12"})
    face.on("act", {"i": 0})
    check("an exam: Settings' own change", ("settings", ["setexam", "2026-12-12"]) in ops.log, ops.log[-1])
    face.on("undo", {})
    check("Undo: the setting as it was", ops.log[-1] == ("put_back", {"exam_date": ""}))
    face.on("type", {"text": "I'm away till monday"})
    face.on("act", {"i": 0})
    check("away: Settings' own change", ("settings", ["setaway", "2026-11-05", "2026-11-09"]) in ops.log)
    face.on("type", {"text": "2026-11-05 | Platelets | tag:" + R + "#Path::Heme::Platelets\n2026-11-10 | event | Heme quiz"})
    v = face.view()
    pt = v.get("plantext") or {}
    check("plan text: its dates and events, counted", v["kind"] == "plantext" and len(pt.get("dates", [])) == 1
          and len(pt.get("events", [])) == 1 and pt["dates"][0]["n"] == 8, pt)
    face.on("plantext", {})
    w = [x for x in ops.log if x[0] == "write"][-1]
    check("Add: the Text tab's own change", w[2] == [{"op": "text", "mode": "add", "text": face.text}], w)


def test_browse_and_the_page():
    face, ops, _closed = window()
    some = sorted(IDX.cards)[:7]
    face.prefill("", some)
    v = face.view()
    check("Browse's picked cards: in the window, the day picker open", v["picked"] and v["count"]["n"] == 7 and v["mode"] == "days", v["count"])
    js = open(os.path.join(REPO, "due_crew", "magicpage", "magic.js")).read()
    sent = set(re.findall(r"send\('([a-z_]+)'", js)) | set(re.findall(r"btn\([^,]+,\s*[^,]+,\s*'([a-z_]+)'", js))
    missing = sorted(c for c in sent if not hasattr(MF.Search, "c_" + c))
    check("every command the page sends has a handler", not missing and len(sent) > 15, missing)
    check("the page sets words as text, never markup", "innerHTML" not in js.replace("box.innerHTML = MAG", "").replace("t.innerHTML = MAG", ""))
    from due_crew.magic_html import page_html
    html = page_html(face.view(), {"theme": "auto", "accent": "green"}, preview=True)
    check("the page: the board's tokens, a script with the first view, nothing in it reading as markup",
          "--dc-accent" in html and "dcMagic.start(" in html and "</script><script>dcMagic" in html
          and "<b>" not in html.split("dcMagic.start(")[1], html[-300:])
    check("sparkles and pops stand still with Reduce motion",
          "prefers-reduced-motion: reduce" in open(os.path.join(REPO, "due_crew", "magicpage", "magic.css")).read())


def test_my_plan_on_the_server():
    """Put on days' requests (the suite's Worker): My plan made and its dates
    saved, then followed here; the next one onto it; a plan I write with
    someone following waits in Review and send (the plan window's draft)."""
    from due_crew import app
    from due_crew.planner import flow as PFL
    STORE.add_user("sam", "Sam", code="SAM123")
    cl = app.client()
    cl.session = {"user_id": "sam", "token": STORE.session_for("sam"), "display_name": "Sam",
                  "last_ok": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    pcfg, drafts = {}, {}
    sync = lambda job, done=None: done(job()) if done else job()  # noqa: E731
    saved = (MF._bg, MF.plan_flow._pcfg, MF.plan_flow._psave, MF.plan_flow._today, PFL._drafts, PFL._save_drafts,
             MF.Ops._note_saved)
    MF._bg = sync
    MF.plan_flow._pcfg = lambda: pcfg
    MF.plan_flow._psave = lambda c: pcfg.update(c)
    MF.plan_flow._today = lambda: TODAY.isoformat()
    PFL._drafts = lambda: drafts
    PFL._save_drafts = lambda d: drafts.update(d)
    MF.Ops._note_saved = lambda self, raw: None  # the board's copy: the glue's, not this test's
    had_col = MF.mw.col
    MF.mw.col = types.SimpleNamespace()  # a collection open: answers land only while one is
    followed, got = [], []
    try:
        ops = MF.Ops()
        ops._follow_new = lambda raw, did, done, code="": (followed.append((raw["id"], did, code)), done(("saved", raw["id"], raw.get("version"), "made")))
        day_ops = [{"op": "add_date", "day": "2026-11-05", "name": "Platelets"},
                   {"op": "add_picks", "date": "2026-11-05 Platelets", "cards": [["g1", 0], ["g2", 0]]}]
        ops.write_plan(None, day_ops, IDX, got.append, name="My plan", deck="Big Step 1")
        how, pid, version, more = got[-1]
        plan = STORE.plans.get(pid) or {}
        check("My plan: made, its date saved with its cards, then followed here on the deck (with its code)",
              how == "saved" and more == "made" and plan.get("name") == "My plan" and plan.get("owner") == "sam"
              and [(u["opens"], len(u.get("cards") or [])) for u in plan["doc"]["units"]] == [("2026-11-05", 2)]
              and followed and followed[0][0] == pid and followed[0][1] == 1 and followed[0][2], (got, plan.get("doc"), followed))
        ops.write_plan(pid, [{"op": "add_event", "day": "2026-11-06", "name": "Quiz"}], IDX, got.append)
        check("the next: onto it, one save", got[-1][0] == "saved" and len(STORE.plans) and
              [e["name"] for e in STORE.plans[pid]["doc"].get("events") or []] == ["Quiz"], (got[-1], STORE.plans[pid]["doc"]))
        STORE.add_user("lee", "Lee", code="LEE123")
        STORE.plans[pid]["followers"] = STORE.plans[pid].get("followers", 0)
        lee = app.client().__class__(os.path.join(os.environ.get("TMPDIR", "/tmp"), "dc-test-magic-lee.json"))
        lee.session = {"user_id": "lee", "token": STORE.session_for("lee"), "display_name": "Lee",
                       "last_ok": cl.session["last_ok"]}
        lee.follow_plan(STORE.plans[pid]["code"])
        ops.write_plan(pid, [{"op": "add_event", "day": "2026-11-12", "name": "Block exam"}], IDX, got.append)
        d = drafts.get("drafts", {}).get(pid)
        check("with someone following: it waits in Review and send, the plan as it was",
              got[-1][0] == "waiting" and d and len(d.get("ops") or []) == 1
              and [e["name"] for e in STORE.plans[pid]["doc"].get("events") or []] == ["Quiz"], (got[-1], d))
        check("…and Undo takes the waiting one back", ops.undo_draft(pid, 1) and not (drafts.get("drafts") or {}).get(pid))
        ops.write_plan("nope0000", day_ops, IDX, got.append)
        check("a plan that isn't there: said, nothing made", got[-1][0] == "failed" and got[-1][3], got[-1])
    finally:
        (MF._bg, MF.plan_flow._pcfg, MF.plan_flow._psave, MF.plan_flow._today, PFL._drafts, PFL._save_drafts,
         MF.Ops._note_saved) = saved
        MF.mw.col = had_col
        cl.session = {}


# ---- ways in ----

def test_ways_in():
    from due_crew import board, settings_model, account
    check("the You box's head: Magic search, with its key", 'duecrew:magic' in board.magic_link() and board.MAGIC_KBD in board.magic_link())
    due = None
    on = board._due_html(due, (("plans", "Plans"),), "plans", "", magic=True)
    off = board._due_html(due, (("plans", "Plans"),), "plans", "", magic=False)
    check("…on unless Settings has it off", "Magic search" in on and "Magic search" not in off)
    check("Settings › Board › Due: its switch", settings_model.change(["set", "magic_search", "0"], {}) == {"magic_search": False})
    check("an account key, on every computer, with its first-time card's",
          "magic_search" in account.ACCOUNT_KEYS and "magic_seen" in account.ACCOUNT_KEYS and "magic_seen" in account._BOOLS)
    st = board.settings_html({"tab": "board", "signed_in": True}, {"tab": "board"})
    check("the switch is on Settings' Board tab", "magic_search" in st, st[:200])
    import due_crew as dc
    from aqt.deckbrowser import DeckBrowser
    if "aqt.reviewer" not in sys.modules:
        sys.modules["aqt.reviewer"] = types.SimpleNamespace(Reviewer=type("Reviewer", (), {}))
    opened = []
    saved = MF.open_search
    MF.open_search = lambda text="", cids=None: opened.append(text)
    try:
        dc._on_js(False, "duecrew:magic|" + board.BOARD_KEY, DeckBrowser())
        check("the board's command opens it", opened == [""], opened)
        dc._on_js(False, "duecrew:magic", type("Previewer", (), {})())
        check("…and a card's own script can't", opened == [""], opened)
    finally:
        MF.open_search = saved


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except Exception:  # noqa: BLE001 (a test that raises is a failure, said)
                import traceback
                traceback.print_exc()
                check(name + " ran", False)
    bad = [n for n, ok in CHECKS if not ok]
    print(f"\n{len(CHECKS) - len(bad)}/{len(CHECKS)} passed")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
