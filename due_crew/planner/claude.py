"""Labs, Claude's jobs (docs/planner.md): what reading.py's plain rules leave
when a plan starts from a block's calendar, and what Claude would be asked
for it. Claude isn't connected yet: a stand-in answers in its place, by
looser rules of its own, so every step can be tried, and everything it
answers says it's the stand-in's. Nothing is sent.

Plain rules go first in every job; Claude is asked only for what they leave:
- calendar: a paste in which no line starts with a date and no table row
  has one (prose, a file's text): the stand-in finds a date anywhere in a
  line;
- pick: a session whose words match none of the deck's tags well enough:
  the stand-in reads its abbreviations and a few common words the way a
  reader would (HFrEF, systolic; pharm, drugs) and takes the best it finds;
- scope: the parts of an exam's line plain rules couldn't place ("week 4's
  two pharm lectures"): the stand-in takes that week's sessions whose
  titles, or the names of the tags ticked for them, have those words.

What Claude would get is built here (request()), so the window can show it
before anything is ever sent: the pasted text, a session's title,
objectives and listed resources, and the names of the deck's tags that
could fit or are ticked (paths, with how many cards each holds); never a
card's text, an id, or anything about anyone else. Pure.
"""

import re

from . import model as M
from . import reading as R

class StandIn:
    """Claude's stand-in. `fake`: its answers are made here, by rules, and
    said to be."""

    name = "Claude’s stand-in"
    fake = True

    def status(self):
        return ("Claude isn’t connected yet. Where plain rules leave something, a stand-in answers in its "
                "place so you can try each step; its answers say so. Nothing is sent.")

    # ---- the calendar ----

    def calendar(self, text, today, day_first=False):
        """Sessions from lines with a date anywhere in them ("we meet on Oct
        26 for heart failure"): [session] or []."""
        out = []
        for raw in str(text or "").splitlines():
            line = raw.strip()
            for k in range(len(line)):
                if k and line[k - 1].isalnum():
                    continue
                d, rest = R.parse_date(line[k:], today, day_first)
                if not d:
                    continue
                title = re.sub(r"(?i)^the\s+", "", R.clean_title(_FILLER.sub(" ", f"{line[:k]} {rest}")).strip(" ."))
                title = title[:1].upper() + title[1:]
                if title and not R._SKIP.search(title):
                    out.append(R.session(d, title, R.kind_of(title)))
                break
        return R.merge(out)

    # ---- a session's tags ----

    def pick(self, idx, s, cands=None, most=2):
        """(candidates, [index], why) for a session plain rules matched to
        nothing: found again with the stand-in's own words, its title's
        words one at a time first, then its abbreviations and short names
        read as a reader would (HFrEF as systolic); the best (at most one a
        resource) taken with a lower bar."""
        title = str(s.get("title") or "")
        alone = [w for w in R.words(title) if len(w) >= 5]
        says = []
        for t in R.terms_of(s):
            for x in t:
                if x in SAYS and x not in [y for y, _v in says]:
                    says.append((x, SAYS[x]))
        tries = [(alone, "matched its words one at a time")]
        if says:
            tries.append((sorted({w for _x, v in says for w in v}), "read " + "; ".join(
                f"{_spelled(x, title)} as {' or '.join(v[:2])}" for x, v in says[:2])))
        for extra, why in tries:
            if not extra:
                continue
            got = R.candidates(idx, s, extra=extra)
            out = _best(got, most)
            if out:
                return got, out, why
        return (cands if cands is not None else R.candidates(idx, s)), [], "found nothing that fits"

    # ---- what an exam covers ----

    def scope(self, phrases, sessions, tags=None):
        """([index], [phrase it couldn't place]): "week 4's two pharm
        lectures" is week 4's sessions about pharm; "the renal lectures"
        every session about renal. What a session is about: its title, and
        the names of the tags ticked for it (tags: {index: [tag]}), as a
        reader would know diuretics are renal."""
        about = {}
        for i, x in enumerate(sessions):
            ws = set(R.words(x["title"]))
            for t in (tags or {}).get(i) or ():
                ws |= set(R.words(" ".join(M.label(seg) for seg in str(t).split(M.SEP))))
            about[i] = ws
        got, left = set(), []
        lectures = [i for i, x in enumerate(sessions) if x["kind"] not in R.EVENT_KINDS]
        for p in phrases:
            wk = re.search(r"\bweeks?\s+(\d{1,2})\b", p, re.I)
            want = [w for w in R.words(re.sub(r"\bweeks?\s+\d+\b", " ", p)) if w not in _COUNTING]
            want = sorted({w for x in want for w in (x,) + SAYS.get(x, ())})
            hits = {i for i in lectures
                    if (not wk or int(sessions[i].get("week") or 0) == int(wk.group(1)))
                    and want and any(R.same(w, t) for w in want for t in about[i])}
            if hits:
                got |= hits
            else:
                left.append(p)
        return sorted(got), left


def _best(cands, most):
    """The stand-in's bar: anything its words name, at most one a resource."""
    out, groups = [], set()
    for i, c in enumerate(cands):
        if c["score"] < 2 or (c["group"], c["kind"]) in groups:
            continue
        out.append(i)
        groups.add((c["group"], c["kind"]))
        if len(out) >= most:
            break
    return out


def _spelled(word, text):
    """A word as the text spells it ("HFrEF", not "hfref")."""
    m = re.search(r"\b" + re.escape(word) + r"\b", str(text), re.I)
    return m.group(0) if m else word


# a sentence's own words around a date: "we meet on Oct 26 for heart failure"
_FILLER = re.compile(r"(?i)\b(?:we|meet|meets|will|be|on|for|at|class|session|is|are|there)\b|[,;:]")

_COUNTING = {"one", "two", "three", "four", "five", "six", "both", "all", "lectures", "lecture", "sessions",
             "classes", "topics", "talks"}

# the stand-in's reading of a few words, as a reader would take them (abbreviations, short names)
SAYS = {
    "hfref": ("systolic", "reduced"), "hfpef": ("diastolic", "preserved"),
    "pharm": ("pharmacology", "drugs"), "drugs": ("pharmacology", "pharm"), "drug": ("pharmacology", "pharm"),
    "cardio": ("cardiovascular", "cardiac", "heart"), "heart": ("cardiac", "cardio"),
    "renal": ("kidney", "nephrology"), "kidney": ("renal",),
    "neuro": ("neurology", "nervous"), "heme": ("hematology", "blood"), "onc": ("oncology", "cancer"),
    "micro": ("microbiology",), "path": ("pathology",), "ecg": ("ekg", "electrocardiogram"), "ekg": ("ecg",),
    "htn": ("hypertension",), "afib": ("fibrillation", "atrial"), "raas": ("renin", "angiotensin", "aldosterone"),
    "bnp": ("natriuretic",), "copd": ("pulmonary", "obstructive"), "ckd": ("kidney", "chronic"),
    "aki": ("kidney", "acute"), "uti": ("urinary",), "gerd": ("reflux",), "ibd": ("inflammatory", "bowel"),
}


# ---- what Claude would get ----

CALENDAR_SHAPE = {"type": "object", "properties": {"sessions": {"type": "array", "items": {
    "type": "object", "required": ["date", "kind", "title"],
    "properties": {"date": {"type": "string", "description": "YYYY-MM-DD"},
                   "kind": {"type": "string", "enum": list(R.KINDS)},
                   "title": {"type": "string"},
                   "objectives": {"type": "array", "items": {"type": "string"}},
                   "listed": {"type": "array", "items": {"type": "string"}}}}}}}
PICK_SHAPE = {"type": "object", "required": ["picks"], "properties": {"picks": {"type": "array", "items": {
    "type": "object", "required": ["n", "fit"],
    "properties": {"n": {"type": "integer", "description": "a tag's number in the list"},
                   "fit": {"type": "string", "enum": ["whole", "part", "no"]}}}}}}
SCOPE_SHAPE = {"type": "object", "required": ["sessions"], "properties": {"sessions": {
    "type": "array", "items": {"type": "integer", "description": "a session's number in the list"}}}}


def request(job, **kw):
    """What a connected Claude would be sent for one job, as the window shows
    it: {job, instructions, input, answer}. It answers by number in lists
    made here, never with a name it could invent; each answer would be
    checked against `answer` before anything is used. pick's cands: the
    tags it could choose among (reading.could_fit)."""
    if job == "calendar":
        return {"job": "Read a block's calendar",
                "instructions": "Each session in this calendar: its date, what kind it is, its title, its "
                                "objectives and the resources it lists. Leave out breaks and holidays.",
                "input": {"today": str(kw.get("today") or ""), "text": str(kw.get("text") or "")[:12000]},
                "answer": CALENDAR_SHAPE}
    if job == "pick":
        s = kw.get("session") or {}
        cands = kw.get("cands") or []
        return {"job": "Match a session to the deck's tags",
                "instructions": "Which of these tags fit this session: the whole tag, part of it, or not at all.",
                "input": {"session": {"title": s.get("title") or "",
                                      "objectives": [o.get("text") or "" for o in s.get("objectives") or []][:20],
                                      "listed": [x.get("text") or "" for x in s.get("listed") or []][:10]},
                          "tags": [{"n": i + 1, "tag": c["tag"], "cards": c["cards"]} for i, c in enumerate(cands[:12])]},
                "answer": PICK_SHAPE}
    if job == "scope":
        sessions = kw.get("sessions") or []
        return {"job": "What an exam covers",
                "instructions": "Which of these sessions this line says the exam covers.",
                "input": {"said": [str(p) for p in kw.get("phrases") or []],
                          "sessions": [{"n": i + 1, "date": x["date"], "week": x.get("week"), "title": x["title"],
                                        "tags": [str(t) for t in (kw.get("tags") or {}).get(i) or []][:12]}
                                       for i, x in enumerate(sessions) if x["kind"] not in R.EVENT_KINDS][:200]},
                "answer": SCOPE_SHAPE}
    raise ValueError(job)
