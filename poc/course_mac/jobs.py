"""The four jobs the model does, each with its prompt, its answer's shape,
a check on what comes back, and plain rules for when there's no model (or
it fails): read the calendar, give the search words, pick the resources,
read the cards. The model never sees an id: it answers by place in a list
it was shown, and nothing it says is kept unless it fits the shape. Pure
apart from the runner it's given."""

import re
import time

from . import cal
from . import find as F
from .model import ModelError, arr, boolean, integer, obj, string

INSTRUCTIONS = ("You help a student match a course's sessions to the flashcards in their own deck. "
                "Answer only in the shape asked for, from what you are shown. Never invent a number you weren't shown.")

CAL_SCHEMA = obj("Calendar", [("sessions", arr(obj("Session", [
    ("date", string(), "the date exactly as written"),
    ("kind", string(cal.KINDS)),
    ("title", string()),
    ("objectives", arr(obj("Objective", [("label", string(), "like SLG 12, or empty"), ("text", string())]), 12)),
]), 14))])
WORDS_SCHEMA = obj("Words", [("terms", arr(string(), 14))])
PICK_SCHEMA = obj("Pick", [("groups", arr(obj("Group", [
    ("r", integer(), "the group's number"),
    ("use", string(["whole", "part", "no"])),
    ("objectives", arr(integer(), 12), "the objective numbers it serves"),
]), 16))])


def read_schema(n):
    return obj("Read", [("cards", arr(obj("Card", [
        ("c", integer(), "the card's number"),
        ("fits", boolean()),
        ("objective", integer(), "the objective it serves best, 0 if none"),
        ("clozes", arr(integer(), 20), "for a cloze card, the cloze numbers that fit, if only some do"),
    ]), max(1, n)))])


def _ask(runner, log, job, prompt, schema, max_tokens, timeout=None):
    """One call, logged: (value, ms). ModelError passes up."""
    start = time.time()
    try:
        value, ms, raw = runner.ask(job, INSTRUCTIONS, prompt, schema, max_tokens=max_tokens, timeout=timeout)
    except ModelError as e:
        log(f"{job}: {e.kind} after {time.time() - start:.1f} s ({len(prompt):,} chars in): {str(e)[:160]}")
        raise
    ms = ms or int((time.time() - start) * 1000)
    log(f"{job}: {ms / 1000:.1f} s, {len(prompt):,} chars in", raw)
    return value, ms


def objectives_block(objs, limit=1400):
    lines = []
    for i, o in enumerate(objs, 1):
        lab = f"{o.get('label')}: " if o.get("label") else ""
        lines.append(f"{i}. {lab}{o.get('text', '')}")
    t = "\n".join(lines)
    return t if len(t) <= limit else t[:limit].rsplit("\n", 1)[0]


# ---- 1. the calendar ----

def read_calendar(runner, text, today, log, size=1800, day_first=False):
    """[session] from a pasted calendar, and how it was read. The model reads
    each piece; its dates are read here, not by it. A piece it can't read
    is read as lines."""
    if not runner or runner.name == "none":
        return cal.read_lines(text, today, day_first), "lines"
    out, failed = [], 0
    year = f" (it's {today:%B %Y} now)"
    for piece in cal.chunks(text, size):
        prompt = (f"Part of a course calendar{year}:\n---\n{piece}\n---\n"
                  "List every dated session in it: its date exactly as written, its kind (lecture, quiz, exam, lab or "
                  "other), its title, and its learning objectives if any are listed under it (with a label like "
                  "\"SLG 12\" if it has one). Skip breaks and holidays.")
        try:
            got, _ms = _ask(runner, log, "calendar", prompt, CAL_SCHEMA, 1400)
        except ModelError:
            failed += 1
            out += cal.read_lines(piece, today, day_first)
            continue
        for s in got["sessions"]:
            d, _rest = cal.parse_date(s["date"], today, day_first)
            title = cal.clean_title(s["title"])
            if not d or not title:
                continue
            objs = [{"label": o["label"][:20], "text": o["text"][:300]} for o in s["objectives"] if len(o["text"]) >= 6]
            out.append({"date": d.isoformat(), "kind": cal.kind_of(title, s["kind"]), "title": title, "objectives": objs})
    return cal.merge(out), "model" + (f" ({failed} piece{'s' if failed != 1 else ''} as lines)" if failed else "")


# ---- 2. the words ----

def rule_terms(title, objs, limit=14):
    """No model: the title, its words, and the objectives' naming words
    (abbreviations kept: BNP, JVD, S3)."""
    out = []

    def put(t):
        t = t.strip()
        if t and t.lower() not in {x.lower() for x in out}:
            out.append(t)
    lead = re.sub(r"[:(].*$", "", title).strip()
    if len(F.words(lead)) <= 4:
        put(lead)  # the title as one term: its words alone match too much
    else:  # a sentence (an objective as the title): its pairs of naming words
        ws = [w for w in re.split(r"[^A-Za-z0-9-]+", lead) if w and w.lower() not in F.STOP and len(w) > 2]
        for a, b in zip(ws, ws[1:]):
            put(f"{a} {b}")
    text = " ".join(o.get("text", "") for o in objs)
    for ab in re.findall(r"\b[A-Z][A-Z0-9]{1,5}\b", text):
        put(ab)
    seen, own = {}, set(F.words(title))
    for w in F.words(text):
        if len(w) >= 6 and w not in own:
            seen[w] = seen.get(w, 0) + 1
    for w, _n in sorted(seen.items(), key=lambda kv: -kv[1]):
        put(w)
    return out[:limit]


def clean_terms(terms, limit=14):
    out = []
    for t in terms:
        t = re.sub(r"^[\s\-*•\d.)]+", "", str(t)).strip(" .,;:\"'")
        if not (2 <= len(t) <= 40) or len(t.split()) > 4:
            continue
        if t.lower() in F.STOP or t.lower() in {x.lower() for x in out}:
            continue
        out.append(t)
    return out[:limit]


def terms_for(runner, lec, log):
    """(terms, how) for a lecture."""
    title, objs = lec["title"], lec.get("objectives") or []
    if not runner or runner.name == "none":
        return rule_terms(title, objs), "rules"
    prompt = (f"Lecture: {title}\nObjectives:\n{objectives_block(objs) or '(none listed)'}\n\n"
              "Give up to 12 short search terms a flashcard deck would use for this lecture's topics: the diseases, "
              "drugs, structures, mechanisms, signs and abbreviations it covers. Use the words a textbook index "
              "would use. One to three words each.")
    try:
        got, _ms = _ask(runner, log, "words", prompt, WORDS_SCHEMA, 220)
    except ModelError as e:
        return rule_terms(title, objs), f"rules ({e.kind})"
    terms = clean_terms(got["terms"])
    if not terms:
        return rule_terms(title, objs), "rules (empty answer)"
    # the title's own words stay in: what the lecture is called is what its tag is called
    lead = re.sub(r"[:(].*$", "", title).strip()
    if lead and lead.lower() not in {t.lower() for t in terms}:
        terms = [lead] + terms[:13]
    return terms, "model"


# ---- 3. the resources ----

def rule_pick(cands, n_obj):
    """No model: a group the title names is whole; one with two or more of the
    words, part; the rest, no."""
    out = {}
    for i, c in enumerate(cands, 1):
        if c.get("title_hit"):
            out[i] = ("whole", list(range(1, n_obj + 1)))
        elif len(c.get("terms") or []) >= 2:
            out[i] = ("part", [])
        else:
            out[i] = ("no", [])
    return out


def pick(runner, lec, cands, samples, log, budget=5200):
    """({group number: (use, [objective numbers])}, how). cands: the rows
    find.candidates gave, named; samples: {group number: [card fronts]}."""
    objs = lec.get("objectives") or []
    if not cands:
        return {}, "nothing to pick"
    if not runner or runner.name == "none":
        return rule_pick(cands, len(objs)), "rules"
    head = f"Lecture: {lec['title']}\nObjectives:\n{objectives_block(objs) or '(none listed)'}\n\nCard groups in the student's deck:\n"
    tail = ("\nFor each group, say whether this lecture needs all of it (whole), only some of its cards (part), or "
            "none (no), and which objective numbers it serves. A group about this lecture's main topic is whole. A "
            "group mostly about something else, with a few cards this lecture needs, is part.")
    for keep in (2, 1, 0):
        lines = []
        for i, c in enumerate(cands, 1):
            ex = "; ".join(s[:90] for s in (samples.get(i) or [])[:keep])
            lines.append(f"G{i}. {c['label']} ({c['n']} cards)" + (f". For example: {ex}" if ex else ""))
        prompt = head + "\n".join(lines) + tail
        if len(prompt) <= budget:
            break
    try:
        got, _ms = _ask(runner, log, "pick", prompt, PICK_SCHEMA, 520)
    except ModelError as e:
        return rule_pick(cands, len(objs)), f"rules ({e.kind})"
    out = {}
    for g in got["groups"]:
        if 1 <= g["r"] <= len(cands) and g["r"] not in out:
            out[g["r"]] = (g["use"], sorted({o for o in g["objectives"] if 1 <= o <= len(objs)}))
    for i in range(1, len(cands) + 1):
        out.setdefault(i, ("no", []))  # a group it skipped is left out, and shown so
    return out, "model"


# ---- 4. the cards ----

def rule_read(lec, notes, terms):
    """No model: a card holding two of the words (or one that's two words
    long) fits; its objective is the one sharing most words with it."""
    objs = lec.get("objectives") or []
    ow = [set(F.words(o.get("text", ""))) for o in objs]
    out = {}
    for n in notes:
        got = F.term_hits(n["text"], terms)
        fits = len(got) >= 2 or any(len(t.split()) >= 2 for t in got)
        best = 0
        if fits and ow:
            tw = set(F.words(n["text"]))
            scores = [len(tw & o) for o in ow]
            best = scores.index(max(scores)) + 1 if max(scores) else 0
        out[n["nid"]] = (fits, best, [])
    return out


def read(runner, lec, notes, terms, log, batch=10, budget=5200, cancel=lambda: False):
    """({nid: (fits, objective number, [cloze numbers])}, how, unread nids).
    notes: [{nid, text, clozes}], read about `batch` at a time; a batch the
    window can't hold is halved; one the model refuses stays unread (shown
    for you to look at), never guessed."""
    objs = lec.get("objectives") or []
    if not notes:
        return {}, "nothing to read", []
    if not runner or runner.name == "none":
        return rule_read(lec, notes, terms), "rules", []
    head = f"Lecture: {lec['title']}\nObjectives:\n{objectives_block(objs) or '(none listed)'}\n\nCards:\n"
    tail = ("\nFor each card, say whether it teaches something an objective asks for (fits), which objective number "
            "it serves best (0 if none), and for a cloze card ([c1: …]) the cloze numbers that fit, if only some do.")
    out, unread, kinds = {}, [], set()
    queue = [notes[i:i + batch] for i in range(0, len(notes), batch)]
    while queue:
        if cancel():
            unread += [n["nid"] for part in queue for n in part]
            break
        part = queue.pop(0)
        body = "\n".join(f"C{i}. {n['text']}" for i, n in enumerate(part, 1))
        prompt = head + body + tail
        if len(prompt) > budget and len(part) > 1:
            half = len(part) // 2
            queue[:0] = [part[:half], part[half:]]
            continue
        try:
            got, _ms = _ask(runner, log, "read", prompt, read_schema(len(part)), 40 + 34 * len(part))
        except ModelError as e:
            kinds.add(e.kind)
            if e.kind == "context" and len(part) > 1:
                half = len(part) // 2
                queue[:0] = [part[:half], part[half:]]
                continue
            unread += [n["nid"] for n in part]
            continue
        seen = set()
        for c in got["cards"]:
            if not (1 <= c["c"] <= len(part)) or c["c"] in seen:
                continue
            seen.add(c["c"])
            n = part[c["c"] - 1]
            o = c["objective"] if 1 <= c["objective"] <= len(objs) else 0
            cl = sorted({x for x in c["clozes"] if x in (n.get("clozes") or [])})
            if cl and len(cl) == len(n.get("clozes") or []):
                cl = []  # every cloze is the whole note
            out[n["nid"]] = (bool(c["fits"]), o, cl)
        unread += [n["nid"] for i, n in enumerate(part, 1) if i not in seen]
    how = "model" + (f" ({len(unread)} unread: {', '.join(sorted(kinds)) or 'skipped'})" if unread else "")
    return out, how, unread
