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

    def __init__(self, tags=None):
        self.did, self.name = 1, "Big Step 1"
        self.by_tag, self.tag_names, self.cards, self.order = {}, {}, {}, {}
        self.due_now, self.leech, self.nid_of, self.state = set(), set(), {}, {}
        cid = 1000
        for i, (t, n) in enumerate(sorted((TAGS if tags is None else tags).items())):
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
          sorted(ticked(r)) == ["Charts Micro", "Charts Pharm"], r["groups"])
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
    r = read("Block 3 · 12 Oct 2026\nMissed: 10234, 10235, 99999 · 65%")
    check("round 2 (QBank QIDs' paste, any way the bank copies it): a block's results with words around them are its QIDs "
          "when two or more are this deck's questions (no Missed filter, no topic from the words)",
          r["kind"] == "ids" and r["qids"] == ["2026", "10234", "10235", "99999"] and not r["filters"] and not r["groups"], r)
    r = read("Block 3 notes, question 10234")
    check("…one of them alone, with words: not a paste of QIDs", r["kind"] != "ids" or r["qids"] == ["10234"], r["kind"])
    r = read("anemia due 2026 and 2027")
    check("…numbers that aren't its questions: the words as words", r["kind"] == "words" and r["groups"], r["kind"])
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

    def study(self, cids, name, order=None):
        self.log.append(("study", list(cids), name, order))
        return True

    def plan_dates(self, did, idx, cids):
        return [("My plan", ["Thu 5 Nov"])] if cids else []

    PACE = {"new_s": 30, "rev_s": 10, "day_min": 20, "known": True}  # a new card's half minute, a review's 10 s, 20 min a day

    def pace(self):
        return dict(self.PACE)

    def in_filtered(self, cids):
        return list(getattr(self, "infilt", []))

    def deck_map(self, did):
        self.log.append(("deck_map", did))
        return getattr(self, "tiles", ([], set()))

    def study_topic(self, name, cids):
        self.log.append(("study_topic", name, list(cids)))
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
    check("round 2 (Sam: the how-to \"should pop up on the main decks screen\"): the window opens on its box, the "
          "how-to the Decks screen's; the filters row always there, every filter off",
          not v["intro"] and v["howto"] is None and [f["k"] for f in v["filters"]] == list(M.ROW)
          and not any(f["on"] for f in v["filters"]), v["filters"])
    face.on("intro", {"show": True})
    check("? brings the how-to back, its words magic.HOWTO's", face.view()["intro"] and face.view()["howto"]["lede"] == M.HOWTO["lede"])
    face.on("intro", {"show": False})
    check("Got it: seen, once a person (an account key)", ops.seen and not face.view()["intro"])
    face.on("type", {"text": "heart failure"})
    v = face.view()
    hf = IDX.tag_cards(R + "#Videos::03_Cardio::05_Heart_Failure") | IDX.tag_cards(R + "#Path::Cardio::Heart_Failure") \
        | IDX.tag_cards(R + "#M&M::Cardio::Heart_Failure")
    check("its cards are its tags' in the deck's index, counted", v["count"]["n"] == len(hf) == 27, v["count"])
    tp = v["topics"][0]
    check("round 3: one row a typed topic, its tags' cards once each, its tree open", tp["name"] == "Heart Failure"
          and tp["on"] and tp["n"] == 27 and tp["ntags"] == 3 and tp["open"] and tp["in"] is None, tp)
    check("round 3 (Sam: \"the tag tree to go all the way to the last tag\"): each tag under where it's from, "
          "the one with most cards first, its path to its end",
          [(g["res"], g["n"], [t["path"] for t in g["tags"]]) for g in tp["tree"]]
          == [("Videos", 16, ["Cardio \u203a Heart Failure"]), ("Path", 7, ["Cardio \u203a Heart Failure"]),
              ("M&M", 4, ["Cardio \u203a Heart Failure"])], tp["tree"])
    check("its near names as Also under it, each with its cards", tp["also"] == [{"i": 1, "name": "Heart Failure Drugs", "n": 6}], tp["also"])
    face.on("open", {"seg": 0})
    check("its tags' count folds the tree", not face.view()["topics"][0]["open"] and "tree" not in face.view()["topics"][0])
    face.on("open", {"seg": 0})
    face.on("tag", {"t": R + "#Path::Cardio::Heart_Failure"})
    check("unticking one of its tags leaves its cards out", face.view()["count"]["n"] == 20)
    face.on("tags", {"ts": [R + "#Videos::03_Cardio::05_Heart_Failure"], "on": False})
    check("a resource's tick takes its tags out together…", face.view()["count"]["n"] == 4
          and not face.view()["topics"][0]["tree"][0]["tags"][0]["on"], face.view()["count"])
    face.on("tags", {"ts": [R + "#Videos::03_Cardio::05_Heart_Failure"], "on": True})
    check("…and back in together (Path's still out)", face.view()["count"]["n"] == 20)
    face.on("chip", {"i": 1})
    tp = face.view()["topics"][0]
    check("an Also tapped joins the topic's row, and leaves the Also", face.view()["count"]["n"] == 26
          and tp["ntags"] == 4 and not tp["also"], tp)
    face.on("seg", {"seg": 0})
    check("the topic's tick: all of it out", face.view()["count"]["n"] == 0 and not face.view()["topics"][0]["on"])
    face.on("seg", {"seg": 0})
    check("…and back", face.view()["count"]["n"] == 26)
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
    tp = face.view()["topics"][0]
    check("nothing ticked: no line; its names under Which?, to tap", not face.view()["lines"] and not tp["can"] and tp["also"], (face.view()["lines"], tp))
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
    face.on("study", {"all": True})
    st = [x for x in ops.log if x[0] == "study"][-1]
    check("Study all N: every one but a leech", st[1] == [c for c in cids if c not in IDX.leech])
    face.how = "nd"
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


def test_what_it_found_and_the_tiles():
    """Round 3 (Sam: "giving the user enough information about what has been
    found so that they can take the appropriate action"; four tiles: "Study
    now, Schedule ahead, Make a new filtered deck", and "make unsuspend a core
    button in the bottom pills")."""
    check("my pace from my log: a new card's seconds, a review's, the middle of my days",
          M.pace_from(60000 * 10, 20, 8000 * 40, 40, [30, 50, 0, 40, 90]) == {"new_s": 30.0, "rev_s": 8.0, "day_min": 50, "known": True})
    check("too little to go on: the usual guess, not said as mine",
          M.pace_from(1000, 2, 1000, 3, [30, 40]) == dict(M.PACE) and not M.PACE["known"])
    check("a pace's ends held (a card left open over lunch)", M.pace_from(10 ** 9, 10, 10, 20, [])["new_s"] == 240
          and M.pace_from(10, 10, 10, 20, [])["rev_s"] == 3)
    check("the time said short", [M.says_time(x) for x in (20, 120, 2700, 3600, 13190)]
          == ["under a minute", "about 2 min", "about 45 min", "about 1 h", "about 3 h 40 min"])
    pace = {"new_s": 30, "rev_s": 10, "day_min": 20, "known": True}
    check("how many of my days it takes, one at least, two weeks at most",
          (M.days_for(60, pace), M.days_for(1201, pace), M.days_for(10 ** 6, pace)) == (1, 2, 14))
    face, ops, _closed = window()
    face.on("intro", {"show": False})
    face.on("type", {"text": "heart failure"})
    v = face.view()
    f, t = v["found"], v["tiles"]
    check("what it found, each card once: due, new (its suspended said), seen and not due, none a leech here",
          (f["n"], f["due"], f["new"], f["susp_new"], f["notdue"], f["leech"]) == (27, 2, 17, 9, 8, 0)
          and f["due"] + f["new"] + f["notdue"] + f["leech"] == f["n"], f)
    check("Study now's set at my pace, beside my usual day", f["study"] == 19 and f["time"] == "about 9 min" and f["usual"] == "20 min"
          and not f["big"] and f["days"] == 0, f)
    check("four tiles: under my day, Study now's filled; Study all the seen ones too; Unsuspend's count; the new deck's name",
          t == {"study": 19, "all": 27, "days": 0, "keep": "Heart Failure", "uns": 9, "rec": "study", "deck": "Due Crew \u203a Heart Failure"}, t)
    ops.PACE = dict(Ops.PACE, day_min=5)
    face = MF.Search(ops)
    face.push, face.close_win = (lambda: None), (lambda: None)
    face.on("type", {"text": "heart failure"})
    v = face.view()
    check("more than my usual day: Schedule ahead filled, the days it takes said", v["found"]["big"] and v["found"]["days"] == 2
          and v["tiles"]["rec"] == "days" and v["tiles"]["days"] == 2, v["found"])
    face.on("days", {"show": True})
    check("Schedule ahead: the days it takes picked, from tomorrow", face.picked == ["2026-11-05", "2026-11-06"], face.picked)
    face.on("day", {"iso": "2026-11-09"})
    face.on("days", {"show": False})
    face.on("days", {"show": True})
    check("…not again once I've picked my own", face.picked == ["2026-11-05", "2026-11-06", "2026-11-09"], face.picked)
    ops.infilt = [("Due Crew::Heart Failure", 3), ("QBank misses", 2)]
    face.on("type", {"text": "heart failure "})
    check("some sitting in a filtered deck: said, its own deck aside (Study now rebuilds that one)",
          face.view()["found"]["infilt"] == [["QBank misses", 2]], face.view()["found"]["infilt"])
    face.on("type", {"text": "anemia I missed this week"})
    tp = face.view()["topics"][0]
    check("a topic narrowed by a filter says how many of its cards are in (\"13 of 798\")", tp["in"] is not None
          and tp["in"] == face.view()["found"]["n"] < tp["n"], tp)
    face.on("type", {"text": "seen"})
    f = face.view()["found"]
    t = face.view()["tiles"]
    check("a filter alone: Study now takes every one but a leech, so no Study all; none suspended, Unsuspend has none",
          f["all"] and f["study"] == f["due"] + f["notdue"] + f["new"] == f["n"] - f["leech"] and t["all"] == 0 and t["uns"] == 0, (f, t))
    js = open(os.path.join(REPO, "due_crew", "magicpage", "magic.js")).read()
    check("the page: the four tiles, in Sam's words", all(w in js for w in ("Study now", "Schedule ahead", "Make a new filtered deck", "Unsuspend")))
    check("the page: Study all N sends study with all", "'Study all ' + n(T.all), 'study', { all: true }" in js)


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
    check("said, with Undo and the plan", s["text"].startswith("Made My plan: ") and s["undo"] == "save" and s["open"] == "pMine", s)
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


def test_days_from_the_words_v399():
    """3.9.9 (Sam: "spread things out across a period of time"): a period in
    the words was no topic's and the box found nothing ("cardio friday": no
    such tag). Now the days are read off the words and picked in Schedule
    ahead. TODAY is Wed 4 Nov 2026."""
    def days(q):
        r = M.read(q, TREE, TODAY, [(1, "Big Step 1")], PLANS)
        sp = r.get("span") or {}
        return len(r["groups"]) > 0 and not r["text"], sp.get("days") or [], sp.get("per")
    want = {"platelets over the next 5 days": ("2026-11-05", "2026-11-09", 5),
            "spread platelets over 2 weeks": ("2026-11-05", "2026-11-18", 14),
            "spread platelets out evenly across the next three days": ("2026-11-05", "2026-11-07", 3),
            "platelets from monday to friday": ("2026-11-09", "2026-11-13", 5),
            "platelets friday to sunday": ("2026-11-06", "2026-11-08", 3),
            "platelets by friday": ("2026-11-05", "2026-11-06", 2),
            "platelets before friday": ("2026-11-05", "2026-11-05", 1),
            "platelets this week": ("2026-11-05", "2026-11-08", 4),
            "platelets next week": ("2026-11-09", "2026-11-15", 7),
            "platelets on friday": ("2026-11-06", "2026-11-06", 1),
            "platelets tomorrow": ("2026-11-05", "2026-11-05", 1),
            "platelets in 3 days": ("2026-11-07", "2026-11-07", 1),
            "platelets dec 12": ("2026-12-12", "2026-12-12", 1)}
    got = {q: days(q) for q in want}
    bad = {q: g for q, g in got.items() if not g[0] or (g[1][0], g[1][-1], len(g[1])) != want[q]}
    check("days from the words: over, across, from … to, by, before, this and next week, on a day; the topic still read", not bad, bad)
    ok, ds, per = days("platelets 20 a day")
    ok2, ds2, per2 = days("platelets 15 a day by friday")
    check("so many a day: with or without its days", (ok, ds, per) == (True, [], 20) and ok2 and per2 == 15 and len(ds2) == 2, (ds, per, ds2, per2))
    same = {q: (M.read(q, TREE, TODAY, [(1, "Big Step 1")], PLANS).get("span"), M.read(q, TREE, TODAY, [(1, "Big Step 1")], PLANS)["limit"])
            for q in ("platelets", "10 new platelets", "missed in the last 3 days", "due tomorrow", "sun exposure", "type 2 diabetes")}
    check("no days asked: nothing picked (a filter's days are its own, 'sun' is no Sunday, a count is a count)",
          all(v[0] is None for v in same.values()) and same["10 new platelets"][1] == 10, same)
    r = M.read("heme quiz friday", TREE, TODAY, [(1, "Big Step 1")], PLANS)
    check("a quiz's day is the quiz's: its row, as before", r.get("span") is None and [a["k"] for a in r["acts"]][:1] == ["event"], r["acts"])
    face, ops, _closed = window()
    face.on("ready", {})
    face.on("type", {"text": "platelets over the next 3 days"})
    v = face.view()
    check("the window: Schedule ahead open on those days, the cards shared between them",
          [e["iso"] for e in v["days"]["each"]] == ["2026-11-05", "2026-11-06", "2026-11-07"]
          and sum(e["n"] for e in v["days"]["each"]) == v["count"]["n"] > 0, v.get("days"))
    face.on("day", {"iso": "2026-11-06"})
    check("a tap still takes a day off", [e["iso"] for e in face.view()["days"]["each"]] == ["2026-11-05", "2026-11-07"])
    face.on("type", {"text": "platelets over the next 4 weeks"})
    v = face.view()
    f = v["days"]["fill"]
    check("more than the picker's two weeks: the fill-in takes the stretch, a set a day, about so many each",
          len(v["days"]["each"]) == 28 and f["on"] and f["n"] == 28 and f["study"] == 28 and f["per"] >= 1
          and sum(e["n"] for e in v["days"]["each"]) == v["count"]["n"], (len(v["days"]["each"]), f))
    face.on("fillskip", {"dow": 6})
    face.on("fillskip", {"dow": 5})
    v = face.view()
    wk = [__import__("datetime").date.fromisoformat(e["iso"]).weekday() for e in v["days"]["each"]]
    check("the fill-in: weekdays skipped come off, the cards shared over what's left", len(wk) == 20 and not set(wk) & {5, 6}
          and v["days"]["fill"]["skip"] == [5, 6] and sum(e["n"] for e in v["days"]["each"]) == v["count"]["n"], wk)
    for d in range(5):
        face.on("fillskip", {"dow": d})
    check("…never every weekday", len(face.view()["days"]["each"]) >= 1 and len(face.fill["skip"]) == 6, face.fill)
    face.on("fill", {"n": 500})
    check("…at most ninety days out and sixty study days", face.view()["days"]["fill"]["n"] <= MF.FILL_SPAN + 1
          and len(face.picked) <= MF.FILL_MAX, (face.view()["days"]["fill"]["n"], len(face.picked)))
    face.on("fill", {"off": True})
    check("Pick days: back to the picker's two weeks, what was picked in them kept", face.fill is None
          and 0 < len(face.picked) <= 13, len(face.picked))
    face.on("fill", {"n": 30})
    face.on("day", {"iso": face.picked[0]})
    check("a tap on a day is my own choice again: the fill-in lets go, the other days stay", face.fill is None and len(face.picked) == 29)
    face.on("type", {"text": "platelets"})
    check("the words stop asking: the picker they opened shuts", "days" not in face.view())
    face.on("type", {"text": "spread platelets"})
    check("only 'spread': Schedule ahead opens (the days it takes, when it's a lot)", face.mode == "days")


def test_schedule_ahead_spreads_open_cards_v399():
    """3.9.9 (Sam: unsuspended cards due on one day, put on the next few,
    stayed put): a plan's date only opens what's suspended, so cards open
    already never moved. Schedule ahead now holds a later day's new cards
    back and moves its due reviews, in one step that goes back with Undo;
    the picker says so before the press."""
    face, ops, _closed = window()
    face.on("ready", {})
    face.on("type", {"text": "platelets over the next 2 days"})
    cids = face.cards()[0]
    kinds = {c: ("new" if i % 3 == 0 else "rev" if i % 3 == 1 else "learn" if i == 2 else "") for i, c in enumerate(cids)}
    calls = []
    ops.open_kinds = lambda cs: {c: k for c, k in kinds.items() if k}
    ops.spread = lambda shares: (calls.append(shares) or (sum(len(n) for d, n, _r in shares if d > 0),
                                                           sum(len(r) for d, _n, r in shares if d > 0), "Due Crew: spread"))
    undone = []
    ops.undo_anki = lambda label: undone.append(label) or True
    face._kinds = None
    v = face.view()
    new_n, rev_n = sum(1 for k in kinds.values() if k == "new"), sum(1 for k in kinds.values() if k == "rev")
    check("…and that a card in its learning steps stays with today (it isn't moved)",
          "mid-learning" in face.view()["days"]["note"] or all(k != "learn" for c, k in kinds.items() if c in face.cards()[0][len(face.cards()[0]) // 2:]),
          face.view()["days"]["note"])
    check("the picker says what a date alone can't do: the open new ones held back, the due reviews moved",
          f"{new_n:,} " in v["days"]["note"] and "held back" in v["days"]["note"] and "due date" in v["days"]["note"], v["days"].get("note"))
    face.on("put", {})
    sh = calls[-1]
    check("Put: each day's share of the open cards, by how far off its day is; every open card in one share",
          [d for d, _n, _r in sh] == [1, 2] and sum(len(n) for _d, n, _r in sh) == new_n and sum(len(r) for _d, _n, r in sh) == rev_n, sh)
    s = face.view()["said"]
    check("said with the plan's dates, one Undo for both", "held back" in s["text"] and "moved to their days" in s["text"] and s["undo"] == "save", s)
    check("held only once the dates are on the plan: the save first, then Anki's step",
          [x[0] for x in ops.log if x[0] == "write"] and len(calls) == 1)
    face.on("undo", {})
    check("Undo: the plan's save and Anki's step", ("undo_save", "pMine", 7) in ops.log and undone == ["Due Crew: spread"], (ops.log[-2:], undone))
    # a save that fails: nothing was held or moved (they'd be suspended with no date to open them)
    n_calls = len(calls)
    real = ops.write_plan
    ops.write_plan = lambda pid, o, idx, done, name=None, deck=None: done(("failed", pid, None, "Couldn't save it."))
    face.picked = ["2026-11-05", "2026-11-06"]
    face.on("put", {})
    check("a save that fails: the cards aren't touched, and it says the save failed",
          len(calls) == n_calls and face.view()["said"]["text"] == "Couldn't save it.", face.view()["said"])
    ops.write_plan = real
    # onto a plan with followers: the dates wait in Review and send, so nothing is held yet, and it says so
    face.on("dest", {"key": "pB"})
    face.picked = ["2026-11-05", "2026-11-06"]
    face.on("put", {})
    s2 = face.view()["said"]
    check("waiting in Review and send: the open cards stay put till it's sent, said", len(calls) == n_calls
          and "open already" in s2["text"] and "till it's sent" in s2["text"] and s2["undo"] == "draft", s2)
    face.on("undo", {})
    face.on("dest", {"key": "mine"})
    # today's share stays as it is; nothing open, nothing said or done
    face.on("type", {"text": "platelets"})
    face.on("days", {"show": True})
    face.picked = [TODAY.isoformat()]
    check("a share for today isn't touched", all(d == 0 for d, _n, _r in face.shares(cids, face.picked))
          and not face.view()["days"]["note"], face.view()["days"])


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
    win = open(os.path.join(REPO, "due_crew", "ui", "magic_window.py")).read()
    missing = sorted(c for c in sent if not hasattr(MF.Search, "c_" + c) and not (c == "size" and 'a["cmd"] == "size"' in win))
    css = open(os.path.join(REPO, "due_crew", "magicpage", "magic.css")).read()
    rule = re.search(r"body \.dcm select\.b \{[^}]*\}", css)
    check("round 2 (Sam: \"not clear that this is a drop down\"): a dropdown in the buttons' look keeps its arrow "
          "(.b's background would take it)", rule and "background-image" in rule.group(0) and "!important" in rule.group(0), rule)
    check("every command the page sends has a handler (size, the window's own: its height)",
          not missing and len(sent) > 15 and "size" in sent, missing)
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
    # 3.9.9 (Sam's pick G2): a field under Anki's deck list, over its "Studied…" line; the You box's head has no link
    fld = board.magic_field({"accent": "blue"})
    check("the field under the decks: the board's input, the window's magnifier and star, its key, what it says to a screen reader",
          'id="dc-mgf" role="search"' in fld and '<input type="text" aria-label="Magic search: ' in fld and board.MAGIC_KBD in fld
          and 'class="st"' in fld and 'aria-label="Open Magic search"' in fld and 'maxlength="400"' in fld)
    check("…it carries the board's tokens itself (it's outside the board), in my accent, both themes",
          "#dc-mgf { --dc-bg: #ffffff;" in fld and "#1e5fb4" in fld and "night" in fld and "--dc-hours" in fld)
    check("…Enter sends what's typed, encoded and keyed as the board's commands are",
          "pycmd('duecrew:magic'+(q?':'+encodeURIComponent(q):'')+'|" + board.BOARD_KEY + "');return false;" in fld
          and "function go() { f.querySelector('button.go').click(); }" in fld)
    check("…it moves about twelve seconds, then rests till pointed at; nothing with Reduce motion; no </script> from its words",
          "12000" in fld and "rounds >= 3" in fld and "prefers-reduced-motion" in fld and fld.count("</script>") == 1
          and all(x in fld for x in board.MAGIC_EXAMPLES[:1]))
    due = None
    on = board._due_html(due, (("plans", "Plans"),), "plans", "", magic=True)
    check("the You box's head has no Magic search link any more", "Magic search" not in on and "du-mg" not in on)
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
        dc._on_js(False, "duecrew:magic:cardio%20pharm%3A%20due%20%7C%20this%20week|" + board.BOARD_KEY, DeckBrowser())
        check("the field's Enter opens it on what was typed (a colon and a bar in it too)", opened == ["", "cardio pharm: due | this week"], opened)
        dc._on_js(False, "duecrew:magic:" + "a" * 900 + "|" + board.BOARD_KEY, DeckBrowser())
        check("…kept to 400", len(opened[-1]) == 400)
        dc._on_js(False, "duecrew:magic:tag%3Ax", type("Previewer", (), {})())
        check("…and never from a card's own script", len(opened) == 3)
    finally:
        MF.open_search = saved


def test_and_or_and_both():
    """Sam: "AND statements and OR statements on tags": "and", "or" and
    commas put another topic beside one (each one's cards); "both … and …",
    AND in capitals (Anki's word) and "with" take only the cards in both."""
    for q in ("anemia or platelets", "anemia OR platelets", "anemia and platelets", "anemia, platelets"):
        r = read(q)
        check(f"{q!r}: two topics, each one's cards", r["kind"] == "words" and r["terms"] == [[0], [1]]
              and "Anemia" in ticked(r) and "Platelets" in ticked(r), (r["kind"], r["terms"]))
    check("an Anki search with its own OR is still Anki's", read("tag:a OR tag:b")["kind"] == "search")
    for q in ("both heart failure and anemia", "heart failure AND anemia", "heart failure with anemia"):
        r = read(q)
        check(f"{q!r}: the cards in both", r["terms"] == [[0, 1]] and ticked(r)[:1] == ["Heart Failure"] and "Anemia" in ticked(r)
              and M.joined(r), (r["terms"], ticked(r)))
    r = read("itp AND platelets, or anemia")
    check("both, then or: ITP's cards that are Platelets', and Anemia's", r["terms"] == [[0, 1], [2]], r["terms"])
    r = read("both anemia, platelets and itp")
    check("…both binds its list, to an or", r["terms"] == [[0, 1, 2]], r["terms"])
    r = read("both anemia and itp, or platelets")
    check("…an or puts another beside it", r["terms"] == [[0, 1], [2]], r["terms"])
    r = read("m&m heart failure")
    check("a resource's & is its name, not an and", r["res"] == ["#m&m"] and r["terms"] == [[0]], r)
    tree = M.Tree(["#B::#Path::Endo::Diabetes_with_Complications", "#B::#Path::Endo::Diabetes", "#B::#Path::Renal::Complications"])
    r = M.read("diabetes with complications", tree, TODAY)
    check("with: a tag that says the whole stays one topic", r["terms"] == [[0]] and ticked(r)[:1] == ["Diabetes with Complications"],
          (r["terms"], ticked(r)))
    r = read("anemia with zzqx words")
    check("…and one side no topic names: as said", r["terms"] == [[0]], r["terms"])
    check("its name: with between them", M.topics_said([{"seg": 0, "on": True, "name": "Heart Failure"},
                                                        {"seg": 1, "on": True, "name": "Anemia"}], [[0, 1]]) == "Heart Failure with Anemia")
    # the window: the cards in both, from a deck whose cards carry two tags
    both = Idx({"#Path::Cardio::Heart_Failure": 6, "#Path::Pharm::Diuretics": 5, "#Path::Heme::Anemia": 4})
    hf, di = both.by_tag[(R + "#Path::Cardio::Heart_Failure").lower()], both.by_tag[(R + "#Path::Pharm::Diuretics").lower()]
    di += hf[:3]  # three heart failure cards are a diuretic's too
    both.tag_keys = sorted(both.by_tag)

    class BothOps(Ops):
        def index(self, did):
            return both
    face = MF.Search(BothOps())
    face.push = face.close_win = lambda: None
    face.on("type", {"text": "both heart failure and diuretics"})
    v = face.view()
    check("the window: only the cards in both", sorted(face.cards()[0]) == sorted(hf[:3]) and v["count"]["n"] == 3, v["count"])
    check("…named with with, the page told which chips go together", face.name() == "Heart Failure with Diuretics"
          and v["terms"] == [[0, 1]], (face.name(), v["terms"]))
    face.on("type", {"text": "heart failure or diuretics"})
    check("or: either's", face.view()["count"]["n"] == 6 + 5, face.view()["count"])
    face.on("type", {"text": "heart failure AND anemia"})
    v = face.view()
    check("none in both: no cards, and said", v["count"]["n"] == 0 and v["lines"] == ["No card here is in both."], v["lines"])
    face.on("type", {"text": "both heart failure and diuretics"})
    face.on("seg", {"seg": 1})
    check("a side's topic off: nothing is in both", face.view()["count"]["n"] == 0)
    js = open(os.path.join(REPO, "due_crew", "magicpage", "magic.js")).read()
    check("the page: a quiet with between the chips taken in both", "text: 'with', title: 'Only the cards in both'" in js)


def test_tag_rows_say_their_resource():
    """Round 2 (Sam, on a topic's tags: "i'm not really able to find the
    overarching resource which is an important thing")."""
    row = M.tag_row
    A = " \u203a "
    check("round 3 (Sam: \"all the way to the last tag\"): its resource, the first #part under its root, and every part after it",
          row("#Big::#QuickRef::04_Pathology::03_Neoplasia::16_Paraneoplastic::01_Skin::*Lesser_Sign")
          == {"res": "Quick Ref", "path": A.join(["Pathology", "Neoplasia", "Paraneoplastic", "Skin", "Lesser Sign"])})
    check("the topic's own name kept at the end", row(R + "#M&M::Cardio::Heart_Failure") == {"res": "M&M", "path": "Cardio" + A + "Heart Failure"})
    check("a resource said alone: its name, nothing after", row(R + "#ChartsMicro") == {"res": "Charts Micro", "path": ""})
    check("no #part: its root is where it's from", row("Heme_lectures::Week_2::Anemia") == {"res": "Heme lectures", "path": "Week 2" + A + "Anemia"})
    check("a one-part tag: no resource", row("anemia") == {"res": "", "path": "anemia"})
    check("tags under two roots: the root says which, said short (its version and a short prefix of capitals off)",
          row("#Big_Step1_v12::#M&M::06_Cardio::06_Heart_Failure", roots=True)["path"] == A.join(["Big Step 1", "Cardio", "Heart Failure"])
          and row("XY_Step2_v12::#M&M::02_Cardio", roots=True)["path"] == "Step 2" + A + "Cardio"
          and row("XY_Step2_v12::#M&M::02_Cardio")["path"] == "Cardio")
    check("a root's name: no version, no short capitals before it, a number set apart",
          [M.root_name(x) for x in ("Big_Step1_v12", "XY_Step2_v12", "Heme_lectures", "AB")] == ["Big Step 1", "Step 2", "Heme lectures", "AB"])
    rows = [{"t": "b", "res": "Path", "path": "Heme", "n": 3, "on": True}, {"t": "c", "res": "Videos", "path": "Heme", "n": 9, "on": True},
            {"t": "a", "res": "Path", "path": "Renal", "n": 8, "on": False}]
    got = M.tag_list(rows)
    check("by resource, the one with most cards first, each one's tags in their own order (a child under its parent)",
          [(g["res"], g["n"], [t["t"] for t in g["tags"]]) for g in got] == [("Path", 11, ["a", "b"]), ("Videos", 9, ["c"])], got)
    has = {"a": {1, 2, 3}, "b": {3, 4}, "c": {5}}
    got = M.tag_list(rows, lambda t: has[t])
    check("round 3: a resource's cards once each (a note can carry a parent and its child, or both halves of a deck)",
          [(g["res"], g["n"]) for g in got] == [("Path", 4), ("Videos", 1)], got)
    twins = [dict(M.tag_row(t), t=t, n=n, on=True) for t, n in (
        ("#Big_Step1::#M&M::06_Cardio::06_Heart_Failure", 5), ("#Big_Step2::#M&M::02_Cardio::03_Heart_Failure", 4))]
    got = M.tag_list(twins)
    check("two of a resource's that would read the same say their tags as written (a resource in two versions of a deck)",
          [t["path"] for t in got[0]["tags"]] == ["#M&M" + A + "06 Cardio" + A + "06 Heart Failure", "#M&M" + A + "02 Cardio" + A + "03 Heart Failure"], got)
    js = open(os.path.join(REPO, "due_crew", "magicpage", "magic.js")).read()
    check("the page: a resource with several tags a heading with its own tick (all in, all out, some: neither)",
          "send('tags', { ts: ts, on: all.checked })" in js and "all.indeterminate = ons > 0 && ons < g.tags.length" in js)


def test_the_how_to():
    """Round 2 (Sam: "the modal introducing for the first time should pop up
    on the main decks screen"; "awesome and comprehensive and clear")."""
    from due_crew import board
    h = M.howto("Ctrl+Shift+F")
    check("the how-to: every way to say it, then what it does, then where it lives",
          [x["k"] for x in h["parts"]] == ["topic", "res", "filter", "limit", "ids", "coming", "lines", "plan"]
          and len(h["then"]) == 5 and "Ctrl+Shift+F" in h["foot"] and "You box" in h["foot"], [x["k"] for x in h["parts"]])
    words = " ".join([h["lede"], h["foot"]] + h["then"] + [x["t"] + " " + x["w"] for x in h["parts"]]
                     + [q for x in h["parts"] for q in x.get("try") or []])
    check("its words name no resource, bank or deck of anyone's: the resource's try is the deck's own",
          not h["parts"][1]["try"] and not re.search(r"(?i)b&b|boards|first ?aid|sketchy|pathoma|uworld|amboss|anking", words))
    ex = M.examples(IDX.tag_names.values())
    check("the deck's own resource try: the #part with most tags (not a bank's numbers), with its biggest part",
          ex == {"res": ["path endo"]}, ex)
    r = read(ex["res"][0])
    check("…and it reads as that resource and topic", r["res"] == ["#path"] and ticked(r) == ["Endo"], (r["res"], r["groups"]))
    check("a deck whose biggest #part is a bank's: the next; and its QIDs try three of the bank's own, spread over its numbers",
          M.examples([R + "#Bank::Step::" + str(10000 + i) for i in range(9)]
                     + [R + "#Notes::Renal::AKI", R + "#Notes::Renal::CKD", R + "#Notes::Heme::ITP"])
          == {"res": ["notes renal"], "ids": ["10002 10004 10006"]})
    check("no #parts: no try of the deck's own", M.examples(["Spanish::Unit_12", "Spanish::Verbs"]) == {})
    h2 = M.howto("Ctrl+Shift+F", {"ids": ["10002 10004 10006"]})
    check("…a block's QIDs keeps its words, its numbers the deck's", h2["parts"][4]["try"] == ["10002 10004 10006"]
          and h2["parts"][4]["label"] == ["a block’s QIDs"])
    face, ops, _closed = window()
    face.on("intro", {"show": True})
    tries = {x["k"]: x.get("try") for x in face.view()["howto"]["parts"]}
    check("the window's ?: each try that needs a tag kept only when it ticks something in this deck",
          tries["topic"] == ["heart failure", "hf drugs"] and tries["res"] == ["path endo"] and tries["filter"] == ["anemia I missed this week"]
          and tries["limit"] == ["both heart failure and pharm", "10 new platelets", "platelets but not itp"]
          and tries["coming"] == M.HOWTO["parts"][5]["try"]
          and tries["ids"] == ["10234 10911 11002"], tries)  # two questions here, too few to make its own; 10234 is one
    js = open(os.path.join(REPO, "due_crew", "magicpage", "magic.js")).read()
    check("the window draws the how-to from its words, not its own", "H.parts" in js and "Its name, its initials" not in js)
    # the Decks screen's card
    saved = (MF.mw.col, MF.cfg, MF.on, dict(MF._TRIES))
    MF.mw.col = types.SimpleNamespace(tags=types.SimpleNamespace(all=lambda: list(IDX.tag_names.values())))
    conf = {}
    MF.cfg = lambda: conf
    MF._TRIES.clear()
    try:
        v = MF.board_howto()
        check("the Decks screen's card: the how-to, the deck's own resource try", v and v["parts"][1]["try"] == ["path endo"], v)
        conf["magic_seen"] = True
        check("…once a person: seen, none", MF.board_howto() is None)
        conf.pop("magic_seen")
        MF.on = lambda: False
        check("…and none with Magic search off", MF.board_howto() is None)
    finally:
        MF.mw.col, MF.cfg, MF.on = saved[0], saved[1], saved[2]
        MF._TRIES.clear()
        MF._TRIES.update(saved[3])
    js = board.magic_howto_js(dict(M.howto("Ctrl+Shift+F"), lede="a </script> b"))
    check("its script: the words as JSON, no </ to end it, its buttons keyed as the board's",
          "</script> b" not in js and "a <\\/script> b" in js and "'duecrew:magichow:' + how + ':' + encodeURIComponent(q || '') + '|' + window.dcBK" in js)
    check("…over the board the bars dim with (VEIL_IDS), and only once the board is clear and Magic search's field is there",
          "dc-magic" in board.VEIL_IDS and "document.getElementById('dc-mgf')" in js and '"dc-show"' in js and '"dc-sheet"' in js)
    import due_crew as dc
    from aqt.deckbrowser import DeckBrowser
    opened, seen = [], []
    saved = (MF.open_search, MF.Ops.saw_intro)
    MF.open_search = lambda text="", cids=None: opened.append(text)
    MF.Ops.saw_intro = lambda self: seen.append(1)
    try:
        dc._on_js(False, "duecrew:magichow:try:heart%20failure%3A%20drugs|" + board.BOARD_KEY, DeckBrowser())
        dc._on_js(False, "duecrew:magichow:open:|" + board.BOARD_KEY, DeckBrowser())
        dc._on_js(False, "duecrew:magichow:seen:|" + board.BOARD_KEY, DeckBrowser())
        check("its buttons through the board: a try opens the window with it, Open with nothing, Got it nothing; each is seen",
              opened == ["heart failure: drugs", ""] and len(seen) == 3, (opened, seen))
        dc._on_js(False, "duecrew:magichow:try:x", type("Previewer", (), {})())
        check("…and a card's own script can't", opened == ["heart failure: drugs", ""] and len(seen) == 3)
    finally:
        MF.open_search, MF.Ops.saw_intro = saved
    init = open(os.path.join(REPO, "due_crew", "__init__.py")).read()
    check("the glue shows it after the Decks screen draws, not while closing or with Wrapped up",
          "QTimer.singleShot(900, _magic_howto)" in init and "magic_flow.show_board_howto()" in init)


QTAGS = {"#Path::Heme::Anemia": 4, "#Path::Renal::AKI": 3, "#QBank::Step::10234": 2, "#QBank::Step::10235": 1,
         "#QBank::Step::10236": 1, "#Other::Step::10234": 1, "#Other::Step::10777": 1}


def test_qids_in_magic_search():
    """Round 2 (Sam: "this is replacing QBank QID search"): what its window did, here."""
    from due_crew.planner import actions
    idx2 = Idx(QTAGS)
    q = {n: idx2.tag_cards(R + "#QBank::Step::" + n) for n in ("10234", "10235", "10236")}

    class QOps(Ops):
        def index(self, did):
            return idx2
    ops = QOps()
    ops.tiles = ([{"name": "Heme", "_cids": sorted(q["10234"] | q["10235"]), "know": 66, "started": 4},
                  {"name": "Renal", "_cids": sorted(q["10236"]), "know": None, "started": 0}], set(q["10234"]))
    face = MF.Search(ops)
    face.push = face.close_win = lambda: None
    face.on("type", {"text": "10234 10235 10236 99999"})
    v = face.view()
    check("QIDs: how many are questions, their cards, the bank with most", v["qids"]["q"] == 3 and v["count"]["n"] == 4
          and v["qids"]["bank"] == "QBank" and not v["qids"]["ask"], v["qids"])
    check("QIDs: what isn't a question here, and my plan's dates holding them", v["lines"] == [
        "1 number isn’t a question here: 99999", "On My plan: Thu 5 Nov"], v["lines"])
    check("QIDs: Their topics, the map's parts they're in, a Study where I missed some (3.9.5)",
          [(t["name"], t["line"], t["missed"]) for t in v["qids"]["topics"]] == [("Heme", "2 questions · 66% here", 2), ("Renal", "1 question · new", 0)],
          v["qids"]["topics"])
    face.on("topic", {"i": 0})
    check("Their topics' Study: the map's deck of what I missed there", ops.log[-1] == ("study_topic", "Heme", sorted(q["10234"])), ops.log[-1])
    check("the map read once a deck", sum(1 for x in ops.log if x[0] == "deck_map") == 1)
    check("QIDs' Study now: Due Crew › QBank cards, as its window's (each paste adds to it), in random order",
          face.name() == actions.DECK and v["tiles"]["deck"] == "Due Crew › QBank cards", v["tiles"])
    face.on("study", {})
    st = [x for x in ops.log if x[0] == "study"][-1]
    check("…its cards, all of them, mixed", st[2] == actions.DECK and st[3] == MF.plan_flow.STUDY_ORDER and len(st[1]) == 4 - len(
        [c for c in st[1] if c in idx2.leech]), st)
    face.on("type", {"text": "10234 10235"})
    v = face.view()
    check("two banks close (the second has half as many): which, the one with most first, till I pick",
          v["qids"]["ask"] and v["qids"]["banks"] == ["QBank", "Other"] and v["qids"]["bank"] == "QBank", v["qids"])
    face.on("bank", {"name": "Other"})
    v = face.view()
    check("…a pick takes that bank's cards, and stays asked", v["qids"]["bank"] == "Other" and v["count"]["n"] == 1 and v["qids"]["ask"]
          and v["lines"][:1] == ["1 number isn’t a question here: 10235"], (v["qids"], v["lines"]))
    face.on("type", {"text": "10234 10235 "})
    check("…a new paste: the bank its numbers say", face.bank_pick is None)
    face.on("type", {"text": "55555 66666"})
    v = face.view()
    check("none of them questions here: said", v["lines"] == ["None of these are questions in Big Step 1."], v["lines"])
    idx3 = Idx({"#Path::Heme::Anemia": 3})

    class NoBank(Ops):
        def index(self, did):
            return idx3
    plain = MF.Search(NoBank())
    plain.push = plain.close_win = lambda: None
    plain.on("type", {"text": "55555"})
    check("a deck with no question tags: said", plain.view()["lines"] == ["Big Step 1 has no question IDs in its tags."]
          and plain.view()["qids"] is None, plain.view()["lines"])
    plain.on("intro", {"show": True})
    tries = {x["k"]: x.get("try") for x in plain.view()["howto"]["parts"]}
    check("the how-to in a deck without heart failure: no heart failure to tap, no QIDs it hasn't", tries["topic"] == []
          and tries["ids"] == [] and tries["coming"], tries)
    check("the old window's gone, its pure find kept", not os.path.exists(os.path.join(REPO, "due_crew", "planner", "qid_window.py"))
          and os.path.exists(os.path.join(REPO, "due_crew", "planner", "qids.py")))


MAGIC_PRESS_JS = r"""
const fs = require("fs"), vm = require("vm");
const [JS, STATES] = process.argv.slice(1);
const src = fs.readFileSync(JS, "utf8"), states = JSON.parse(fs.readFileSync(STATES, "utf8"));
function El(tag) { this.tagName = String(tag).toUpperCase(); this.children = []; this.parent = null; this.attrs = {}; this.style = {}; this.className = "";
  this._t = ""; this.ls = {}; this.value = ""; this.hidden = false; this.checked = false; this.scrollHeight = 20; }
Object.defineProperty(El.prototype, "textContent", { get() { return this._t + this.children.map((c) => c.textContent || "").join(""); },
  set(v) { this._t = String(v); this.children.forEach((c) => { c.parent = null; }); this.children = []; } });
Object.defineProperty(El.prototype, "innerHTML", { set(v) { this._t = ""; this.children = []; }, get() { return ""; } });
Object.defineProperty(El.prototype, "firstChild", { get() { return this.children[0] || null; } });
Object.defineProperty(El.prototype, "parentNode", { get() { return this.parent; } });
El.prototype.appendChild = function (c) { if (c.parent) { c.remove(); } c.parent = this; this.children.push(c); return c; };
El.prototype.insertBefore = function (c) { return this.appendChild(c); };
El.prototype.removeChild = function (c) { c.remove(); return c; };
El.prototype.remove = function () { if (this.parent) { this.parent.children = this.parent.children.filter((x) => x !== this); this.parent = null; } };
El.prototype.setAttribute = function (k, v) { this.attrs[k] = String(v); if (k === "disabled") { this.disabled = true; } };
El.prototype.getAttribute = function (k) { return k in this.attrs ? this.attrs[k] : null; };
El.prototype.removeAttribute = function (k) { delete this.attrs[k]; };
El.prototype.addEventListener = function (t, f) { (this.ls[t] = this.ls[t] || []).push(f); };
El.prototype.classList = null;
function all(el) { const out = []; (function walk(n) { (n.children || []).forEach((c) => { if (c instanceof El) { out.push(c); walk(c); } }); })(el); return out; }
El.prototype.querySelectorAll = function (sel) { return all(this).filter((c) => c.tagName === sel.toUpperCase() || (sel[0] === "." && (" " + c.className + " ").indexOf(" " + sel.slice(1) + " ") >= 0)); };
El.prototype.querySelector = function (sel) { return this.querySelectorAll(sel)[0] || null; };
El.prototype.getBoundingClientRect = function () { return { left: 0, top: 0, right: 10, bottom: 10, width: 10, height: 10 }; };
["focus", "blur", "select", "scrollIntoView", "setSelectionRange", "animate"].forEach((k) => { El.prototype[k] = function () { return { finished: Promise.resolve() }; }; });
function Text(t) { this.textContent = String(t); this.parent = null; }
Text.prototype.remove = El.prototype.remove;
const ev = { stopPropagation() {}, preventDefault() {}, key: "Enter", shiftKey: false };
function fire(el, t) { (el.ls[t] || []).slice().forEach((f) => f.call(el, ev)); if (typeof el["on" + t] === "function") { el["on" + t].call(el, ev); } }
function page(st) {
  const root = new El("div"), docLs = {};
  const ctx = { console, JSON, setTimeout: (f) => { try { f(); } catch (e) { /* a focus */ } return 0; }, clearTimeout() {}, Promise,
    matchMedia: () => ({ matches: false }), requestAnimationFrame: (f) => 0,
    document: { createElement: (t) => new El(t), createTextNode: (t) => new Text(t), getElementById: () => root, activeElement: null,
      addEventListener: (t, f) => { (docLs[t] = docLs[t] || []).push(f); }, body: new El("body") } };
  ctx.window = ctx;
  El.prototype.classList = { add() {}, remove() {}, toggle() {}, contains() { return false; } };
  vm.createContext(ctx); vm.runInContext(src, ctx);
  ctx.dcMagic.start(st, true);
  ctx.dcMagicSent = [];
  return { ctx, root };
}
function hidden(el) { for (let x = el; x; x = x.parent) { if (x.hidden) { return true; } } return false; }
/* what a person can press: what's shown and on; with the how-to up (it covers the window: magic.css .intro), only what's on it */
function controls(root) {
  const intro = root.querySelector(".intro"), on = intro && !intro.hidden ? intro : root;
  return all(on).filter((el) => !el.disabled && !hidden(el) && (on !== root || !intro || !intro.contains(el))
    && (el.ls.click || el.ls.change || el.ls.input || typeof el.onclick === "function"));
}
El.prototype.contains = function (x) { for (; x; x = x.parent) { if (x === this) { return true; } } return false; };
function shape(root) { return JSON.stringify(all(root).map((e) => [e.tagName, e.className, e.hidden, e._t, e.attrs["aria-expanded"] || ""])); }
const out = {};
for (const [key, st] of Object.entries(states)) {
  const errors = [], presses = [];
  let n = 0;
  try { n = controls(page(st).root).length; } catch (e) { errors.push("draw: " + e.message); }
  for (let i = 0; i < n; i++) {
    try {
      const { ctx, root } = page(st), el = controls(root)[i], was = shape(root);
      if (el.tagName === "SELECT") { const o = el.children.filter((c) => c.tagName === "OPTION" && c.attrs.value !== el.value); el.value = o.length ? o[0].attrs.value : el.value; fire(el, "change"); }
      else if (el.tagName === "INPUT" && el.attrs.type === "checkbox") { el.checked = !el.checked; fire(el, "change"); }
      else if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") { el.value = el.value ? el.value + " typed" : "Typed here"; fire(el, "input"); fire(el, "change"); }
      else { fire(el, "click"); }
      presses.push([(el.attrs["aria-label"] || el.textContent || el.tagName).slice(0, 50), ctx.dcMagicSent.slice(), shape(root) !== was,
        el.attrs["aria-pressed"] === "true"]);
    } catch (e) { errors.push(i + ": " + e.message); }
  }
  out[key] = { errors, presses, n };
}
process.stdout.write(JSON.stringify(out));
"""


def test_every_control_pressed():
    """The window's page (magicpage/magic.js) run in node and pressed, as
    the plan window's is (Sam, 7 Nov: two plan sheets whose yes went
    nowhere, each with a test that called the command itself): in each
    state the suite gets it into (the how-to, a topic with its tree, the
    days, a plan of mine, a quiz, plan lines, IDs, after Study, Browse's
    cards), every control fired; each message the page sends goes through
    a fresh window in that state (Search.on). Each has its handler, takes
    its arguments, and does something."""
    import json
    import shutil
    import subprocess
    import tempfile
    import traceback
    if not shutil.which("node"):
        print("SKIP the window pressed: no node")
        return
    pl = "2026-11-05 | Platelets | tag:" + R + "#Path::Heme::Platelets\n2026-11-10 | event | Heme quiz"
    recipes = {
        "the how-to": [("intro", {"show": True})], "a topic": [("intro", {"show": False}), ("type", {"text": "heart failure"})],
        "a topic, its tree open": [("intro", {"show": False}), ("type", {"text": "heart failure"}), ("open", {"seg": 0})],
        "filters, how many, but not": [("intro", {"show": False}), ("type", {"text": "10 new platelets but not itp"})],
        "the days": [("ready", {}), ("type", {"text": "platelets"}), ("days", {"show": True}), ("day", {"iso": "2026-11-06"})],
        "the days, a plan I write": [("ready", {}), ("type", {"text": "platelets"}), ("days", {"show": True}), ("dest", {"key": "pB"})],
        "a quiz": [("type", {"text": "quiz friday on platelets and anemia"})], "plan lines": [("type", {"text": pl})],
        "ids": [("type", {"text": "10234 10235 99999"})], "after Study": [("type", {"text": "anemia"}), ("study", {})],
        "after Put on days": [("ready", {}), ("type", {"text": "platelets"}), ("days", {"show": True}), ("day", {"iso": "2026-11-06"}), ("put", {})],
        "recent": [("type", {"text": "anemia"}), ("type", {"text": ""})],
    }

    def made(steps, picked=None):
        face, ops, closed = window()
        ops.recents = ["anemia", "heart failure"]
        if picked:
            face.prefill("", picked)
        for c, a in steps:
            face.on(c, a)
        return face, ops, closed
    makers = {k: (lambda s=s: made(s)) for k, s in recipes.items()}
    makers["Browse's cards"] = lambda: made([], sorted(IDX.cards)[:7])
    views = {k: mk()[0].view() for k, mk in makers.items()}
    with tempfile.TemporaryDirectory() as tmp:
        sp = os.path.join(tmp, "states.json")
        with open(sp, "w", encoding="utf-8") as f:
            json.dump(views, f)
        got = subprocess.run(["node", "-e", MAGIC_PRESS_JS, os.path.join(REPO, "due_crew", "magicpage", "magic.js"), sp],
                             capture_output=True, text=True, timeout=180)
    try:
        out = json.loads(got.stdout)
    except ValueError:
        check("pressed: the page ran in node", False, got.stderr[-1500:])
        return
    errs = {k: o["errors"][:2] for k, o in out.items() if o["errors"]}
    check(f"pressed: the page drew all {len(out)} states and fired every control without an error "
          f"({sum(o['n'] for o in out.values())} controls)", not errs and all(o["n"] for o in out.values()), errs)
    printed = []
    print_exc = traceback.print_exc
    traceback.print_exc = lambda *a, **k: printed.append(1) or print_exc(*a, **k)
    nothing, wrong, idle = [], [], []
    try:
        for key, o in out.items():
            seen = set()
            for label, msgs, changed, on in o["presses"]:
                msgs = [m for m in msgs if json.loads(m[len("dcmagic:"):])["cmd"] != "size"]  # the window's own (ui/magic_window.py: its height)
                if tuple(msgs) in seen:
                    continue
                seen.add(tuple(msgs))
                face, ops, closed = makers[key]()
                before = json.dumps([face.view(), ops.log, closed], sort_keys=True, default=str)
                for m in msgs:  # a press's messages in turn, on one window (Put on N days: its name, then put)
                    a = json.loads(m[len("dcmagic:"):])
                    if not callable(getattr(face, "c_" + a["cmd"], None)):
                        nothing.append((key, label, m))
                        continue
                    printed.clear()
                    face.on(a["cmd"], a)
                    if printed:
                        wrong.append((key, label, m))
                # nothing, but on the page alone (Make a new filtered deck's name box), or the choice already on, is idle
                if not changed and not on and json.dumps([face.view(), ops.log, closed], sort_keys=True, default=str) == before:
                    idle.append((key, label, msgs))
    finally:
        traceback.print_exc = print_exc
    check("pressed: every message the page sends has its handler (or is the window's own size)", not nothing, nothing[:5])
    check("pressed: no handler took the wrong arguments", not wrong, wrong[:5])
    check("pressed: every control sends something, and what it sends does something", not idle, idle[:6])


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
