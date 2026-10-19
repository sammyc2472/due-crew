"""The collection side of the course PoC (anki, never aqt, so the tests run
it on Anki's own engine): the deck read into an index, a lecture run as
steps (model calls off the main thread, collection reads on it), opening
and tagging in one undo step, a tag's cards split by lecture (Browse), and
measuring against an answer key's tags."""

import re
import time

from . import course as C
from . import find as F
from . import jobs as J

DEFAULTS = {"groups_max": 10, "tag_max_notes": 400, "part_max": 60, "found_max": 30, "read_batch": 10,
            "prompt_chars": 5200, "first_in_line": True, "day_first": False, "calendar_chars": 1800}


def deck_ids(col, did):
    try:
        return [int(x) for x in col.decks.deck_and_child_ids(int(did))]
    except Exception:
        return [int(did)]


def build_index(col, did):
    """The deck's notes and cards, by tag: one read, a second or two on a big deck."""
    dids = ",".join(str(d) for d in deck_ids(col, did))
    cards = col.db.all(f"SELECT id, nid, ord, queue, type FROM cards WHERE did IN ({dids}) OR odid IN ({dids})")
    nids = sorted({int(r[1]) for r in cards})
    notes = {}
    for i in range(0, len(nids), 2000):
        chunk = ",".join(str(n) for n in nids[i:i + 2000])
        for nid, guid, tags in col.db.all(f"SELECT id, guid, tags FROM notes WHERE id IN ({chunk})"):
            notes[int(nid)] = (str(guid), str(tags or ""))
    return F.DeckIndex(notes, cards)


def refresh_states(col, idx, did):
    """Cards' queue and type read again (one quick query): an open, an undo
    or a review elsewhere changes them; tags and notes stay as read."""
    dids = ",".join(str(d) for d in deck_ids(col, did))
    for cid, q, typ in col.db.all(f"SELECT id, queue, type FROM cards WHERE did IN ({dids}) OR odid IN ({dids})"):
        got = idx.card.get(int(cid))
        if got and (got[2], got[3]) != (int(q), int(typ)):
            idx.card[int(cid)] = (got[0], got[1], int(q), int(typ))


def fields_of(col, nids):
    out = {}
    nl = sorted({int(n) for n in nids})
    for i in range(0, len(nl), 500):
        chunk = ",".join(str(n) for n in nl[i:i + 500])
        for nid, flds in col.db.all(f"SELECT id, flds FROM notes WHERE id IN ({chunk})"):
            out[int(nid)] = str(flds or "").split("\x1f")
    return out


def samples(col, idx, nids, k=2):
    """A few of a tag's cards, as their fronts read: not-yet-studied ones first."""
    def rank(n):
        cs = [idx.card[c] for c in idx.cards_of.get(n, [])]
        return (0 if any(t == 0 for _n, _o, _q, t in cs) else 1, n)
    pick = sorted(nids, key=rank)[:k]
    f = fields_of(col, pick)
    return [F.plain(f[n][0])[:120] for n in pick if n in f and f[n]]


def note_rows(col, nids, limit=360):
    f = fields_of(col, nids)
    return [{"nid": int(n), "text": F.note_text(f[n], limit), "clozes": F.cloze_nums(f[n])} for n in nids if n in f]


def find_text(col, idx, terms, exclude=(), limit=30, scan=2500):
    """Notes in the deck whose text holds the words, outside `exclude`, best
    first: two or more of the terms, or one term two words long."""
    q = F.search_terms(terms)
    if not q:
        return []
    try:
        got = [int(n) for n in col.find_notes(q)]
    except Exception:
        return []
    ex = set(exclude)
    got = [n for n in got if n in idx.guid and n not in ex][:scan]
    f = fields_of(col, got)
    scored = []
    for n in got:
        hit = F.term_hits(" ".join(F.plain(x) for x in f.get(n, [])), terms)
        if len(hit) >= 2 or any(len(t.split()) >= 2 for t in hit):
            scored.append((-len(hit), n))
    return [n for _s, n in sorted(scored)[:limit]]


class LectureRun:
    """One lecture through the four jobs, as steps that alternate between
    off the main thread ("bg": the model) and on it ("main": the
    collection). run_all() takes them in a row."""

    def __init__(self, course, lec, idx, runner, log, cfg, col_fn, cancel=lambda: False):
        self.course, self.lec, self.idx = course, lec, idx
        self.runner, self.log, self.col_fn, self.cancel = runner, log, col_fn, cancel
        self.cfg = {**DEFAULTS, **(cfg or {})}
        self.start = time.time()
        self.cands, self.pickable, self.picks = [], [], {}
        self.samples, self.reading, self.part_nids, self.found = {}, [], {}, []
        self.fits, self.unread = {}, []

    def steps(self):
        return [("bg", self.s_terms), ("bg", self.s_find), ("main", self.s_samples), ("bg", self.s_pick),
                ("main", self.s_gather), ("bg", self.s_read), ("main", self.s_finish)]

    def run_all(self):
        for _where, fn in self.steps():
            if self.cancel():
                return False
            fn()
        return True

    def s_terms(self):
        lec = self.lec
        lec["state"] = "running"
        if lec.get("terms_set") and lec.get("terms"):
            lec.setdefault("how", {})["terms"] = "yours"
            return
        terms, how = J.terms_for(self.runner, lec, self.log)
        lec["terms"], lec.setdefault("how", {})["terms"] = terms, how

    def s_find(self):
        """The tags the words name: the index alone, no collection, so off the main thread."""
        lec, idx = self.lec, self.idx
        others = [o for o in C.lectures(self.course) if o["id"] != lec["id"] and C.studied(o)]
        self.cands = F.candidates(idx, lec["terms"], lec["title"], self.cfg["tag_max_notes"], self.cfg["groups_max"])
        for c in self.cands:
            c["res"], c["name"] = F.resource_of(c["tag"])
            c["label"] = f"{c['res']} › {c['name']}" if c["res"] else c["name"]
            c["n"] = len(idx.cids_of(c["nids"]))
            mine = F.title_score(lec["title"], c["tag"], idx)
            later = [o for o in others if F.title_score(o["title"], c["tag"], idx) == 2]
            c["later"] = f"{later[0]['title']}, {later[0]['date']}" if later and mine < 2 else None
        self.pickable = [c for c in self.cands if not c["later"]]

    def s_samples(self):
        col = self.col_fn()
        self.samples = {i: samples(col, self.idx, c["nids"]) for i, c in enumerate(self.pickable, 1)}

    def s_pick(self):
        self.picks, how = J.pick(self.runner, self.lec, self.pickable, self.samples, self.log, self.cfg["prompt_chars"])
        self.lec["how"]["pick"] = how

    def s_gather(self):
        idx, col, terms = self.idx, self.col_fn(), self.lec["terms"]
        whole = set()
        for i, c in enumerate(self.pickable, 1):
            if self.picks.get(i, ("no",))[0] == "whole":
                whole |= c["nids"]
        want = []
        for i, c in enumerate(self.pickable, 1):
            if self.picks.get(i, ("no",))[0] != "part":
                continue
            nids = sorted(c["nids"] - whole)
            if len(nids) > self.cfg["part_max"]:  # the ones holding the words first
                f = fields_of(col, nids)
                nids = sorted(nids, key=lambda n: -len(F.term_hits(" ".join(F.plain(x) for x in f.get(n, [])), terms)))
                nids = nids[:self.cfg["part_max"]]
            self.part_nids[i] = nids
            want += nids
        every = set().union(*[c["nids"] for c in self.cands]) if self.cands else set()
        self.found = find_text(col, idx, terms, every, self.cfg["found_max"])
        want += self.found
        self.reading = note_rows(col, list(dict.fromkeys(want)))

    def s_read(self):
        self.fits, how, self.unread = J.read(self.runner, self.lec, self.reading, self.lec["terms"], self.log,
                                             self.cfg["read_batch"], self.cfg["prompt_chars"], self.cancel)
        self.lec["how"]["read"] = how

    def s_finish(self):
        lec = self.lec
        rows = []
        unread = set(self.unread)
        for i, c in enumerate(self.pickable, 1):
            use, objs = self.picks.get(i, ("no", []))
            row = {"kind": "tag", "tag": c["tag"], "res": c["res"], "name": c["name"], "use": use, "later": None,
                   "objs": objs, "fit": {}, "unread": [], "n_notes": len(c["nids"]), "terms": c["terms"]}
            if use == "part":
                row["fit"] = {str(n): list(self.fits[n]) for n in self.part_nids.get(i, []) if n in self.fits}
                row["unread"] = [n for n in self.part_nids.get(i, []) if n in unread]
            row["on"] = C.default_on(row)
            rows.append(row)
        for c in self.cands:
            if c["later"]:
                rows.append({"kind": "tag", "tag": c["tag"], "res": c["res"], "name": c["name"], "use": "later",
                             "later": c["later"], "objs": [], "fit": {}, "unread": [], "n_notes": len(c["nids"]),
                             "terms": c["terms"], "on": False})
        if self.found:
            row = {"kind": "found", "tag": "", "res": "", "name": "Found by the words", "use": "part", "later": None,
                   "objs": [], "fit": {str(n): list(self.fits[n]) for n in self.found if n in self.fits},
                   "unread": [n for n in self.found if n in unread], "n_notes": len(self.found), "terms": []}
            row["on"] = C.default_on(row)
            rows.append(row)
        order = {"whole": 0, "part": 1, "no": 3, "later": 4}
        rows.sort(key=lambda r: (2 if r["kind"] == "found" else order.get(r["use"], 3), -len(r.get("terms") or [])))
        lec["rows"] = rows
        lec["state"] = "done"
        lec["secs"] = round(time.time() - self.start, 1)
        self.log(f"{lec['title']}: {len(rows)} rows in {lec['secs']} s "
                 f"(words: {lec['how'].get('terms')}; pick: {lec['how'].get('pick')}; read: {lec['how'].get('read')})")


# ---- what a click does (main thread) ----

def openable(col, cids):
    """Suspended and not a leech: what opening would unsuspend."""
    ids = []
    cl = sorted(int(c) for c in cids or ())
    for i in range(0, len(cl), 500):
        chunk = ",".join(str(c) for c in cl[i:i + 500])
        ids += col.db.list(
            f"SELECT c.id FROM cards c JOIN notes n ON n.id = c.nid WHERE c.queue = -1 "
            f"AND c.id IN ({chunk}) AND (' ' || lower(n.tags) || ' ') NOT LIKE '% leech %'")
    return [int(c) for c in ids]


def _first_in_line(col, ids):
    cl = sorted(int(c) for c in ids)
    rows = []
    for i in range(0, len(cl), 500):
        chunk = ",".join(str(c) for c in cl[i:i + 500])
        rows += col.db.all(f"SELECT id, due FROM cards WHERE type = 0 AND queue = 0 AND id IN ({chunk})")
    new = [int(c) for c, _d in sorted(rows, key=lambda r: (r[1], r[0]))]
    if new and hasattr(col.sched, "reposition_new_cards"):
        col.sched.reposition_new_cards(card_ids=new, starting_from=0, step_size=1, randomize=False, shift_existing=True)


def open_cards(col, cids, label, first=True):
    """Unsuspend the suspended ones (never a leech, never suspends), as one
    undo step; first in Anki's line of new cards if asked. How many opened."""
    ids = openable(col, cids)
    if not ids:
        return 0
    pos = col.add_custom_undo_entry(label) if hasattr(col, "add_custom_undo_entry") else None
    col.sched.unsuspend_cards(ids)
    if first:
        _first_in_line(col, ids)
    if pos is not None and hasattr(col, "merge_undo_entries"):
        col.merge_undo_entries(pos)
    return len(ids)


def slug(s):
    s = re.sub(r"\s+", "_", str(s or "").strip())
    s = re.sub(r'["*\\%:]', "", s)
    return re.sub(r"_+", "_", s).strip("_-") or "x"


def lecture_tags(course, lec, idx):
    """{tag: [nids]}: the lecture's tag on every note it brings, and each
    objective's on the notes that fit it. Course::<course>::<date>_<title>."""
    base = f"Course::{slug(course['name'])}"
    out = {}
    lec_tag = f"{base}::{lec['date']}_{slug(lec['title'])[:50]}"
    objs = lec.get("objectives") or []
    for r in lec.get("rows") or []:
        if not r.get("on"):
            continue
        out.setdefault(lec_tag, set()).update(C.row_nids(r, idx))
        for n, v in (r.get("fit") or {}).items():
            if v[0] and 1 <= v[1] <= len(objs):
                out.setdefault(f"{base}::{slug(C.key_of(objs[v[1] - 1], v[1]))[:40]}", set()).add(int(n))
    return {t: sorted(n) for t, n in out.items() if n}


def tag_notes(col, tag_map, label):
    """Add the tags, one undo step. How many notes got one."""
    if not tag_map:
        return 0
    pos = col.add_custom_undo_entry(label) if hasattr(col, "add_custom_undo_entry") else None
    touched = set()
    for tag, nids in tag_map.items():
        col.tags.bulk_add(list(nids), tag)
        touched |= set(nids)
    if pos is not None and hasattr(col, "merge_undo_entries"):
        col.merge_undo_entries(pos)
    return len(touched)


# ---- a tag's cards by lecture (Browse) ----

def assign(course, idx):
    """{cid: lecture}: the first lecture (by date) whose ticked rows bring the card."""
    out = {}
    for lec in C.lectures(course):
        for c in C.lecture_cids(lec, idx):
            out.setdefault(c, lec)
    return out


def split_tag(course, idx, tag):
    """A tag's cards in the deck: by lecture (to open), open already, and
    the ones the course doesn't ask for (their notes, for the model)."""
    nids = idx.under(tag)
    cids = idx.cids_of(nids)
    who = assign(course, idx)
    by, open_, rest = {}, [], []
    for c in cids:
        q = idx.card[c][2]
        if q != -1:
            open_.append(c)
        elif c in who:
            by.setdefault(who[c]["id"], []).append(c)
        else:
            rest.append(c)
    rest_nids = sorted({idx.card[c][0] for c in rest})
    return {"total": len(cids), "by": by, "open": open_, "rest": rest, "rest_nids": rest_nids}


def course_as_lecture(course, near=None, budget=1400):
    """Every studied lecture's objectives as one list, for reading cards
    against the whole course: (pseudo-lecture, [lecture for each objective])."""
    lecs = [l for l in C.lectures(course) if C.studied(l) and l.get("objectives")]
    if near:
        lecs.sort(key=lambda l: abs(_days(l["date"], near)))
    objs, owner, used = [], [], 0
    for l in lecs:
        for o in l["objectives"]:
            text = f"{l['title']}: {o['text']}"
            if used + len(text) > budget:
                break
            objs.append({"label": o.get("label", ""), "text": text})
            owner.append(l)
            used += len(text) + 6
    return {"title": f"{course['name']} (every lecture)", "objectives": objs}, owner


def _days(a, b):
    import datetime as dt
    try:
        return (dt.date.fromisoformat(a) - dt.date.fromisoformat(b)).days
    except ValueError:
        return 9999


def add_reads(course, tag, idx, res, fits, owner):
    """Cards read against the whole course land on their lecture, as a part
    of that tag (merged with a row for it if there is one)."""
    by = {}
    for n, (fits_, o, cl) in fits.items():
        if fits_ and 1 <= o <= len(owner):
            by.setdefault(owner[o - 1]["id"], {})[str(n)] = [True, _local_obj(owner[o - 1], owner, o), cl]
    r_, name = F.resource_of(tag)
    for lec in C.lectures(course):
        got = by.get(lec["id"])
        if not got:
            continue
        row = next((r for r in lec.get("rows") or [] if r.get("tag") == tag), None)
        if row is None:
            row = {"kind": "tag", "tag": tag, "res": r_, "name": name, "use": "part", "later": None, "objs": [],
                   "fit": {}, "unread": [], "n_notes": len(idx.under(tag)), "terms": []}
            lec.setdefault("rows", []).append(row)
        if row["use"] in ("no", "later"):
            row["use"] = "part"
        row["fit"].update(got)
        row["on"] = True
    return {lid: len(v) for lid, v in by.items()}


def _local_obj(lec, owner, o):
    """The objective's number within its own lecture."""
    first = owner.index(lec)
    return o - first


# ---- measuring ----

def measure_objective(col, idx, runner, log, cfg, root, label, text, deck_course=None):
    """One objective as its own lecture, run through the jobs; scored on
    the notes the answer key's tag holds. (score, seconds, lecture)."""
    lec = C.new_lecture("2000-01-01", text[:100], "lecture", [{"label": label, "text": text}])
    course = deck_course or C.new_course("Measure")
    run = LectureRun({**course, "lectures": [lec]}, lec, idx, runner, log, cfg, lambda: col)
    t0 = time.time()
    run.run_all()
    predicted = set()
    for r in lec["rows"]:
        if r.get("on"):
            predicted |= C.row_nids(r, idx)
    answer = idx.under(C.key_tag(root, label))
    return C.score(predicted, answer), round(time.time() - t0, 1), lec
