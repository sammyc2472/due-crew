"""Game night from Anki (3.9.5): tonight's cards as the six games' pack.

Pure: a scope as an Anki search, and a pack from rows of cards (the glue,
gamenight_flow.py, reads them from the collection). The TV is a window in
Anki (ui/game_night_window.py) that the add-on hands this pack; it never
goes to duecrew.com. What reaches phones through the table is the games'
business (site/public/table.js): Trivia sends none of a card's words,
Rounds sends each hand its answers (Sam's yes), Links' board short answers
when the topics run short, and the rest send topic names, which plans
already send.

A pack: {name, n, qs, blacks, whites, words, prompts, twins, draws, scales}
  qs      Trivia: {q, a, tag, opts (four), ans (the right one's place)}
  blacks  Rounds' black cards: {q, a, full, tag}, and written ones (w: 1,
          no answer); whites: answers
  words   Links' board: topic names, then (short of WORDS_MIN) short answers
  prompts Draw it, Somewhere between, Imposter's guesses: topic names
  twins   Imposter: {part, a: {t, facts}, b: {t, facts}}, look-alike topics
  draws   Draw it's written prompts ("Renal pharm on its day off")
  scales  Somewhere between's written ends ([left, right])
Questions, black cards and twins come from tonight's cards; wrong answers,
white cards and topic names also from the cards around them (`near`), so
a small scope still plays.

A card's topic is the name most of its tags agree on (topic_of): a shared
deck tags a card by every resource that covers it. A card isn't a question
when its answer says nothing alone ("increased"), sits in plain sight, or
needs its picture; a wrong answer is one of the answer's sort, from the
nearest cards and the same blank in others ("____ valve"), never one that
holds the answer or sits in the question.
"""

import difflib
import functools
import html
import os
import random
import re

Q_MAX = 200        # a question, as the TV shows it
A_MAX = 40         # an answer: a card with a longer one isn't a question
EXTRA_MAX = 220    # a card's Extra, on the TV after the reveal
FACT_MAX = 120     # a card's sentence among Imposter's "what tells them apart"
WHITE_MAX = 32     # a white card in a hand
WORD_MAX = 18      # a Links tile
TOPIC_MAX = 36
CAPS = {"qs": 150, "blacks": 150, "whites": 300, "words": 80, "prompts": 80, "twins": 30, "draws": 10, "scales": 6}
READ_MAX = 1500    # cards read for a pack: a big scope is sampled
QS_MIN = 30        # Trivia's questions: tonight's cards, then (fewer than this) the cards around them
NEAR_MAX = 600     # and around it, for answer choices
WHITES_MIN = 120   # a hand's cards: tonight's, and at least this many more from around them
WORDS_MIN = 40     # Links' board: topic names, then (fewer than this) short answers
TWINS_MIN = 6
BLANK = "____"
# what each game needs from a pack before its tile lights up
NEEDS = {"trivia": ("qs", 10), "rounds": ("blacks", 1), "links": ("words", 25), "imposter": ("twins", 1),
         "draw": ("prompts", 1), "between": ("prompts", 1)}
SKIP_TAGS = ("leech", "marked")
# the six, as the lobby, the window and You › Pip Party name them
# what's on the menu (Sam, after a night on his own cards: "focus on the
# ones that we know work"): Trivia, Imposter and Links. Rounds, Draw it and
# Somewhere between are off it, their code kept (table.js's ORDER is this)
GAMES = (("trivia", "Trivia"), ("imposter", "Imposter"), ("links", "Links"))
# Rounds' written cards (3.9.5's last round): about one black card in four,
# each {topic} one of tonight's. No answer of their own: the Attending's
# pick is the round. Alone, nobody picks, so table.js leaves them out.
WRITTEN = (
    "What the attending actually wanted on {topic}: ____",
    "{topic}, explained in one card: ____",
    "The real reason I keep missing {topic}: ____",
    "My mnemonic for {topic}: ____",
    "{topic} would be easy if not for ____",
    "The card I'd suspend from {topic}: ____",
    "What I wrote on the {topic} quiz: ____",
    "Day three of {topic}, running on ____",
    "Overheard in the library, about {topic}: ____",
    "The one thing from {topic} I'll never forget: ____",
    "{topic} has a new leech: ____",
    "If {topic} were a person, it would be ____",
    "My study group's new name: ____",
    "What got me through the last block: ____",
    "Tomorrow's me will thank today's me for ____",
    "The last thing I see before I sleep: ____",
)
WRITTEN_TAG = "Pip Party"  # where a written card says it's from
# Draw it's written prompts: a quarter of a round's chains start from one
# (table.js mixes them in), each {topic} one of tonight's
DRAWS = (
    "{topic} as a superhero",
    "{topic} at 3am",
    "{topic} on its day off",
    "{topic} as a monster",
    "{topic} on a first date",
    "{topic} at the gym",
    "{topic} as a movie poster",
    "{topic}, but tiny",
    "{topic} running late",
    "{topic} on vacation",
)
# Somewhere between's written ends, about study life, beside table.js's
# fixed ones (a quarter of the dial's ends); the clue is still a topic
SCALES = (
    ("Forget it by Friday", "Know it forever"),
    ("Skim it", "Make a card for it"),
    ("A one-card topic", "A whole deck"),
    ("Fun to explain", "Please don't ask me"),
    ("Learned it today", "Learned it years ago"),
    ("Easy to draw", "Impossible to draw"),
)
SCALES_IN = 4  # of SCALES in a pack: table.js has twelve of its own

_CLOZE = re.compile(r"\{\{c(\d+)::(.*?)(?:::(.*?))?\}\}", re.S)


# ---- a scope, as an Anki search ----

def _quoted(kind, name):
    """deck:/tag: for one name, its \\ " _ * read as themselves (plans.tag_search's rule)."""
    esc = re.sub(r'([\\"*_])', r"\\\1", str(name))
    return f'"{kind}:{esc}"'


def term(key):
    """"deck:Step 1" or "tag:Step1::Renal" as a search term; "" for anything else."""
    kind, _, name = str(key).partition(":")
    return _quoted(kind, name) if kind in ("deck", "tag") and name else ""


def scope_search(scope, cids=None):
    """A custom scope as one Anki search. scope: {in, out (keys as term()
    takes), seen, missed (days), due (days), lapses (times), flags [1-7]};
    `search`, when set, is the person's own and wins. cids: the cards a
    plan's dates or Slow but right came to (the glue works those out)."""
    s = scope or {}
    own = str(s.get("search") or "").strip()
    if own:
        return own
    parts = []
    ins = [t for t in (term(k) for k in s.get("in") or []) if t]
    if ins:
        parts.append(ins[0] if len(ins) == 1 else "(" + " OR ".join(ins) + ")")
    parts += ["-" + t for t in (term(k) for k in s.get("out") or []) if t]
    if s.get("seen"):
        parts.append("-is:new")
    n = _days(s.get("missed"), 365)
    if n:
        parts.append(f"rated:{n}:1")
    n = _days(s.get("due"), 365)
    if n:
        parts.append(f"prop:due<={n}")
    n = _days(s.get("lapses"), 99)
    if n:
        parts.append(f"prop:lapses>={n}")
    flags = sorted({int(f) for f in s.get("flags") or [] if str(f).isdigit() and 1 <= int(f) <= 7})
    if flags:
        fl = [f"flag:{f}" for f in flags]
        parts.append(fl[0] if len(fl) == 1 else "(" + " OR ".join(fl) + ")")
    if cids is not None:
        parts.append("cid:" + (",".join(str(int(c)) for c in cids) or "0"))
    return " ".join(parts) or "deck:*"


def _days(v, top):
    try:
        n = int(v or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, min(top, n))


# ---- cards into questions ----

def clean(text):
    """A field as one plain line: scripts, styles, sounds and pictures out,
    tags gone, entities read. A line that ends without a stop and a next one
    that starts a sentence are two sentences ("…for cell proliferation. Ras
    proteins are…"), not one run on."""
    t = re.sub(r"<(script|style)\b.*?</\1\s*>", " ", str(text or ""), flags=re.S | re.I)
    t = re.sub(r"\[sound:[^\]]*\]|\[\[type:[^\]]*\]\]", " ", t)
    t = re.sub(r"<br\s*/?>|</(div|p|li)>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]*>", "", t)
    out = ""
    for line in html.unescape(t).split("\n"):
        line = " ".join(line.split())
        if line:
            out += line if not out else (". " if out[-1].isalnum() and line[:1].isupper() and not line[1:2].isupper() else " ") + line
    return out


def cloze(text, n):
    """(question, answer, full) for cloze number n: its deletions a blank,
    the others shown; None when there's no such cloze, or more than one
    piece of it (two blanks read badly on a TV)."""
    hits = [m for m in _CLOZE.finditer(str(text or "")) if m.group(1) == str(n)]
    if len(hits) != 1:
        return None
    ans = clean(hits[0].group(2))
    hint = clean(hits[0].group(3) or "")
    q = _CLOZE.sub(lambda m: (f"{BLANK} ({hint})" if hint else BLANK) if m.group(1) == str(n) else m.group(2), str(text))
    full = _CLOZE.sub(lambda m: m.group(2), str(text))
    return clean(q), ans, clean(full)


def item(row):
    """One card as a question, or None. row: (cid, ord, is_cloze, fields,
    tags). A cloze asks its own number (ord + 1); a basic card its front,
    a reversed one its back. None too for a question that isn't one: its
    answer in plain sight, no words around the blank, a picture it needs,
    or an answer that says nothing on its own ("increased", "Yes")."""
    cid, ord_, is_cloze, fields, tags = row
    fields = list(fields or [])
    if is_cloze:
        raw = fields[0] if fields else ""
        got = cloze(raw, int(ord_) + 1)
        if not got:
            return None
        q, a, full = got
    else:
        if len(fields) < 2:
            return None
        front, back = (fields[1], fields[0]) if int(ord_) == 1 else (fields[0], fields[1])
        raw = front
        q, a = clean(front), clean(back)
        full = f"{q} {a}"
    a = a.strip(" .,;:")
    if not q or not a or len(a) > A_MAX or len(q) > Q_MAX or norm(a) == norm(q) or not norm(a):
        return None
    if empty(a) or _shown(a, q) or len(re.findall(r"[A-Za-z]{2,}", q.replace(BLANK, ""))) < 2:
        return None
    if re.search(r"[A-Za-z0-9]" + re.escape(BLANK) + r"|" + re.escape(BLANK) + r"[A-Za-z0-9]", q):
        return None  # a blank inside a word ("____vascular": the card hid a piece of one)
    if "<img" in str(raw).lower() and _PICTURE.search(q):
        return None
    path, topic = topic_of(tags, f"{q} {a}")
    return {"cid": int(cid), "q": q, "a": a, "full": full[:Q_MAX + A_MAX], "tag": path, "where": topic, "topic": topic,
            "tags": [str(t) for t in tags or []], "cloze": bool(is_cloze), "extra": extra(fields[1] if is_cloze and len(fields) > 1 else
                                                                                       fields[2] if len(fields) > 2 else "")}


_CREDIT = re.compile(r"(photo|image|picture|figure)s?\s+(credit|source|from)|via wikimedia|creative commons|\bcc by\b|"
                     r"^\s*(watch|see|source|ref|more about|personal notes?|missed)\b", re.I)


def extra(text, top=EXTRA_MAX):
    """A card's Extra as the TV shows it after the reveal: plain, without a
    picture's credit or a pointer elsewhere ("Watch …"), at most `top` long."""
    t = clean(text)
    keep = [p for p in re.split(r"(?<=[.!?])\s+|\s+-\s+", t) if p and not _CREDIT.search(p)]
    t = " ".join(keep).strip()
    if len(t) > top:
        t = t[:top].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return t


_PICTURE = re.compile(r"\b(image|picture|pictured|shown|photo|figure|arrows?|above|below|labell?ed)\b", re.I)
# answers that say nothing on their own: a direction, a yes or a no, a side
EMPTY = frozenset("""increased decreased increase decrease elevated reduced raised lowered high low higher lower normal
unchanged nochange same different yes no true false none all both neither either left right upper lower central peripheral
proximal distal anterior posterior medial lateral superior inferior internal external small large big more less positive
negative up down before after early late male female men women children adults always never sometimes common rare
increases decreases inhibits stimulates activates blocks absent present hypo hyper ipsilateral contralateral bilateral
unilateral acute chronic primary secondary local systemic direct indirect active passive major minor first second third
type types it they this that these those upward upwards downward downwards fast slow rapid gradual sudden
one two three four five six seven eight nine ten single multiple several many few once twice""".split())


def empty(a):
    """An answer too thin to be a card's answer, a white card or a tile: a
    word from EMPTY, a letter or two, a lone symbol."""
    t = re.sub(r"[^a-z0-9 ]+", " ", re.sub(r"\([^)]*\)", " ", str(a).lower())).split()
    return not t or (len(t) == 1 and (t[0] in EMPTY or len(t[0]) < 2)) or all(w in EMPTY for w in t)


def _shown(a, q):
    """The answer, as words, already in the question (another cloze shows
    it), the singular and the plural one ("proto-oncogene" in "proto-oncogenes")."""
    w = _stoks(a)
    return bool(w) and f" {w} " in f" {_stoks(q.replace(BLANK, ' '))} "


@functools.lru_cache(maxsize=20000)
def _stoks(s):
    return " ".join(_sing(w) for w in _toks(s).split())


@functools.lru_cache(maxsize=20000)
def _toks(s):
    return " ".join(re.findall(r"[a-z0-9]+", str(s).lower()))


@functools.lru_cache(maxsize=50000)
def norm(s):
    return re.sub(r"[^a-z0-9]+", "", str(s).lower())


def deepest(tags):
    """A note's deepest tag (Anki's own and Due Crew's plan tags aside)."""
    best = ""
    for t in tags or []:
        t = str(t)
        if t.lower() in SKIP_TAGS or t.lower().startswith("duecrew::"):
            continue
        if not best or t.count("::") > best.count("::"):
            best = t
    return best


# a tag's part that says nothing about the topic: its card's place in a
# deck, a resource's chapter number, a question bank's id
JUNK = re.compile(r"^(extras?|misc(ellaneous)?|others?|general|overview|review|summary|intro(duction)?|basics?|images?|"
                  r"pictures?|figures?|tables?|high ?yield|low ?yield|[0-9]* ?high ?yield|low/high ?yield|cards?|new|"
                  r"new cards?|old|todo|to do|flagged|marked|leech|suspended|no dupes|dupes|only step ?\d*|step ?\d*|"
                  r"shelf|subjects?|systems?|topics?|resources?|by rotation|resources by rotation|original decks?|decks?|"
                  r"sub ?decks?|questions?|practice|notes?|facts|concepts|principles|definitions|qbank|qid|ids?|"
                  r"(chapter|ch|lecture|lec|week|wk|day|part|section|sec|unit|module|block|form|level|session|set|"
                  r"test|exam|quiz|lesson|video|vid|page|pg|book|volume|vol) ?[0-9ivx]+[a-z]?)$", re.I)
# a part that says which side of a topic it is: "Pharm" under "Renal"
SECTION = re.compile(r"^(pharm|pharmacology|patho|pathology|pathophysiology|physio|physiology|anatomy|embryo(logy)?|"
                     r"histo(logy)?|micro(biology)?|biochem(istry)?|genetics|immuno(logy)?|management|treatment|"
                     r"therapy|diagnosis|workup|clinical|clinical features|presentation|symptoms|signs|complications|"
                     r"epidemiology|etiology|causes|mechanism|mechanisms|prognosis|risk factors|screening|prevention|"
                     r"classification|labs|imaging|drugs|side effects|adverse effects)$", re.I)
_STOP = frozenset("and the of in on for with to a an by or vs from at as its type".split())


@functools.lru_cache(maxsize=20000)
def _part(part):
    """("ok", name), ("junk", "") for a part that says nothing (JUNK, a
    letter or two), or ("id", "") for an id: a number, or a word of letters
    and digits ("9OaNuk", "Step1"), which names a question, not a topic."""
    raw = str(part)
    n = topic_name(raw)
    if not re.search(r"[A-Za-z]", raw) or (not n and re.search(r"\d", raw)):
        return "id", ""
    if any(len(w) >= 5 and re.search(r"\d", w) and re.search(r"[A-Za-z]", w) for w in re.split(r"[\s_\-./]+", raw.lstrip("#^$!@*"))):
        return "id", ""
    n = re.sub(r"\s*\(?extras?\)?$", "", n, flags=re.I).strip()
    n = n.split(" + ")[0].strip()
    words = n.split()
    if any(len(w) >= 5 and re.search(r"\d", w) and re.search(r"[A-Za-z]", w) for w in words):
        return "id", ""
    if not n or JUNK.match(n) or _JUNKISH.search(n) or "," in n or len(re.findall(r"[A-Za-z]", n)) < 3:
        return "junk", ""
    return "ok", n[0].upper() + n[1:]


_JUNKISH = re.compile(r"^only\b|\bimages?\b|\bupdates?\b|\b(old )?version\b|\bretired\b|\bdupes?\b|\boverlap\b|\[|\bdecks?\b", re.I)


def part_name(part):
    """A tag's part as a topic's name, or "" when it names none (_part)."""
    return _part(part)[1]


@functools.lru_cache(maxsize=20000)
def tag_topic(tag):
    """(path, name) for one tag: its deepest part that names a topic, past
    parts that say nothing ("Extra"); a section ("Pharm") with the part
    above it ("Renal pharm"); ("", "") for a tag that ends in an id (a
    question's, not a topic) or names none below its root."""
    parts = [p for p in str(tag).split("::") if p]
    for i in range(len(parts) - 1, -1, -1):
        kind, n = _part(parts[i])
        if kind == "id":
            return "", ""
        if kind == "junk" or (i == 0 and len(parts) > 1):
            continue
        if SECTION.match(n):
            up = next((part_name(parts[j]) for j in range(i - 1, 0, -1) if part_name(parts[j]) and not SECTION.match(part_name(parts[j]))), "")
            if up and (_stems(n) <= _stems(up) or norm(n)[:5] == norm(up)[:5]):  # "Immunology" under "Immune"
                n = up
            elif up:
                both = f"{up} {n[0].lower() + n[1:]}"
                n = both if len(both) <= TOPIC_MAX else up
        return "::".join(parts[:i + 1]), n
    return "", ""


@functools.lru_cache(maxsize=20000)
def _stems(name):
    return frozenset(w[:6] for w in re.findall(r"[a-z]+", name.lower()) if len(w) >= 3 and w not in _STOP)


def topic_of(tags, text=""):
    """(path, name): a card's topic, from all its tags. With one tag it's
    that tag's; with many (a shared deck tags a card by every resource that
    covers it), the name the most of them agree on, its words counted
    across the card's tags and in the card's own words (text), so
    "Hypersensitivity" over "Extra", a chapter number or a resource's own
    name."""
    cands, freq = {}, {}
    for t in tags or []:
        t = str(t)
        if t.lower() in SKIP_TAGS or t.lower().startswith("duecrew::"):
            continue
        path, name = tag_topic(t)
        if not name:
            continue
        for st in _stems(name):  # every tag that says it counts, the same name twice twice
            freq[st] = freq.get(st, 0) + 1
        if norm(name) not in cands or path.count("::") > cands[norm(name)][0].count("::"):
            cands[norm(name)] = (path, name)
    if not cands:
        return "", ""
    if len(cands) == 1:
        return next(iter(cands.values()))

    said = _stems(text)

    def score(c):
        st = _stems(c[1])
        return ((sum(freq[x] for x in st) + 3 * len(st & said)) / max(1, len(st)) ** 0.5 if st else 0,
                len(st), c[0].count("::"), -len(c[1]))
    return max(cands.values(), key=score)


def rounds(qs, items):
    """Each question's subject for Trivia's topic rounds (its "round"):
    area_of, one subject under its names ("Cardio", "Cardiology": their first
    five letters), the pack's most used of them shown."""
    by_q = {(it["q"], it["a"]): it for it in items}
    area = {}
    for q in qs:
        it = by_q.get((q["q"], q["a"]))
        a = area_of(it["tags"], it["topic"]) if it else ""
        area[id(q)] = "" if a and _overlaps(q["a"], a) else a
    names = {}
    for q in qs:
        a = area[id(q)]
        if a:
            names.setdefault(norm(a)[:5], {}).setdefault(a, 0)
            names[norm(a)[:5]][a] += 1
    for q in qs:
        a = area[id(q)]
        q["round"] = max(names[norm(a)[:5]].items(), key=lambda kv: (kv[1], -len(kv[0])))[0] if a else ""


def area_of(tags, topic=""):
    """A card's subject, a level over its topic, for Trivia's topic rounds
    ("Renal", "Immunology", "Pharmacology"): the name its tags' middle parts
    (not the root, not the topic's own) agree on most; "" without one."""
    freq, cands = {}, {}
    for t in tags or []:
        t = str(t)
        if t.lower() in SKIP_TAGS or t.lower().startswith("duecrew::"):
            continue
        parts = [p for p in t.split("::") if p]
        if parts and _part(parts[-1])[0] == "id":
            continue  # a question's tag: its parts are a question bank's, not a subject
        for d, p in enumerate(parts[1:-1], 1):
            kind, n = _part(p)
            if kind != "ok" or norm(n) == norm(topic) or len(n) > WORD_MAX:
                continue
            for st in _stems(n):
                freq[st] = freq.get(st, 0) + 1
            if norm(n) not in cands or d > cands[norm(n)][1]:
                cands[norm(n)] = (n, d)
    if not cands:
        return ""
    # the most agreed on; between equals, the deeper (a subject sits under a resource's own name)
    score = lambda c: (sum(freq[x] for x in _stems(c[0])) / max(1, len(_stems(c[0]))) ** 0.5, c[1], -len(c[0]))
    return max(cands.values(), key=score)[0]


@functools.lru_cache(maxsize=20000)
def topic_name(part):
    """A tag's part as people read it: "01_Growth_Adaptations" → "Growth
    adaptations"; "" when nothing readable is left."""
    t = str(part).lstrip("#^$!@*").replace("_", " ")
    t = re.sub(r"^\s*\d+[\s.)-]*", "", t).strip()
    t = " ".join(t.split())
    if not t or not re.search(r"[A-Za-z]", t) or len(t) > TOPIC_MAX:
        return ""
    return t[0].upper() + t[1:]


def label(tag):
    """Where a card is from, short: "Renal › Pharm"."""
    parts = [topic_name(p) for p in str(tag).split("::") if p]
    parts = [p for p in parts if p]
    return " › ".join(parts[-2:])


_DRUG = re.compile(r"(mab|nib|pril|sartan|olol|azole|cillin|mycin|cycline|statin|dipine|tidine|prazole|azepam|"
                   r"ine|ide|ol|one|ate|ium|in|il)$")
# a one-word answer that describes ("atrial", "pulmonic", "ventricular"): its wrong answers describe too
_ADJ = re.compile(r"(al|ar|ic|ous|ive|ary|ory|ile|oid|eal|ial|ent|ant|less|ful|able|ible)$")
_DX = re.compile(r"(itis|osis|emia|oma|pathy|syndrome|disease|failure|fibrillation|flutter|necrosis|ism|embolism|aneurysm|"
                 r"dissection|infarction|cancer|tumou?r|deficiency|insufficiency|prolapse|atresia|hernia|ulcer|abscess|"
                 r"infection|palsy|ataxia|plasia|trophy|lupus|stenosis|regurgitation|block|arrest|shock|injury)\b")


@functools.lru_cache(maxsize=20000)
def _shape(a):
    """What sort of answer: a value (it starts with a number), a drug's
    name, a diagnosis, or a word; and its length, roughly."""
    t = a.lower().strip()
    kind = ("n" if re.match(r"^[<>~≈≤≥]?\s*[+-]?\d", t) else "rx" if " " not in t and _DRUG.search(t)
            else "dx" if _DX.search(t) else "adj" if " " not in t and _ADJ.search(t) else "w")
    return kind, min(4, len(t) // 8)


def _slot(q):
    """The words either side of the blank, lower case: "the ____ valve" is
    ("the", "valve"); a hint after the blank is skipped."""
    if BLANK not in q:
        return "", ""
    before, _, after = q.partition(BLANK)
    after = re.sub(r"^\s*\([^)]*\)", "", after)
    bw, aw = re.findall(r"[a-z0-9]+", before.lower())[-1:], re.findall(r"[a-z0-9]+", after.lower())[:1]
    return (bw[0] if bw else ""), (aw[0] if aw else "")


def _hint(q):
    """The hint after a blank, lower case ("class" in "____ (class)")."""
    m = re.search(re.escape(BLANK) + r"\s*\(([^)]{1,30})\)", q)
    return " ".join(re.findall(r"[a-z0-9]+", m.group(1).lower())) if m else ""


def hints(items, k=6):
    """Tonight's blanks' hints, the most used first ("class", "drug"): the
    glue finds other cards with the same hint, whose answers are the same
    sort."""
    count = {}
    for it in items:
        h = _hint(it["q"])
        if 3 <= len(h) <= 24:
            count[h] = count.get(h, 0) + 1
    return sorted(count, key=lambda h: -count[h])[:k]


def slots(items, k=8):
    """The words tonight's blanks sit before ("receptor" in "the ____
    receptor"), the most used first: the glue finds other cards with a blank
    there, whose answers make the best wrong ones."""
    count = {}
    for it in items:
        w = _slot(it["q"])[1]
        if len(w) >= 4 and w not in _STOP and not w.isdigit():
            count[w] = count.get(w, 0) + 1
    return sorted(count, key=lambda w: -count[w])[:k]


@functools.lru_cache(maxsize=20000)
def _style(a):
    t = a.replace("-", "").replace(" ", "")
    return "A" if t.isupper() and len(t) <= 8 else "C" if a[:1].isupper() else "l"


@functools.lru_cache(maxsize=20000)
def _words(a):
    """An answer's words, in the singular ("proteins" is "protein")."""
    return frozenset(_sing(w) for w in re.findall(r"[a-z0-9]+", str(a).lower()))


def _sing(w):
    return w[:-3] + "y" if w.endswith("ies") and len(w) > 4 else w[:-2] if w.endswith(("sses", "xes", "ches", "shes")) else (
        w[:-1] if w.endswith("s") and not w.endswith("ss") and len(w) > 3 else w)


def _overlaps(a, b):
    """Two answers one of which is (most of) the other: "pancreatitis" and
    "acute pancreatitis" can't both be on offer."""
    wa, wb = _words(a), _words(b)
    if not wa or not wb or norm(a) == norm(b):
        return True
    if wa <= wb or wb <= wa:  # in the singular: "GAP" and "GAPs" are one answer
        return True
    na, nb = _one(a), _one(b)
    return (len(na) >= 4 and na in nb) or (len(nb) >= 4 and nb in na) or len(wa & wb) * 2 > min(len(wa), len(wb)) * 1.5


class _Pool:
    """The cards a pack's wrong answers come from, indexed once: by the tags
    they share (a deeper shared tag counts more; one most of the pool shares
    says nothing) and by the words either side of their blank."""

    def __init__(self, items):
        self.items = items
        self.kind = [_shape(it["a"])[0] for it in items]
        self.nw = [len(it["a"].split()) for it in items]
        self.style = [_style(it["a"]) for it in items]
        self.slot = [_slot(it["q"]) for it in items]
        self.hint = [_hint(it["q"]) for it in items]
        pre = []
        df = {}
        for it in items:
            ps = set()
            for t in it.get("tags") or ([it["tag"]] if it["tag"] else []):
                ps.update(_prefixes(str(t)))
            pre.append(ps)
            for x in ps:
                df[x] = df.get(x, 0) + 1
        top = max(8, len(items) // 5)
        self.pre, self.by_pre, self.by_slot = [], {}, {}
        for i, ps in enumerate(pre):
            keep = sorted((x for x in ps if 2 <= df[x] <= top), key=lambda x: -x.count("::"))[:16]
            self.pre.append({x: x.count("::") + 1 for x in keep})
            for x in keep:
                self.by_pre.setdefault(x, []).append(i)
        for i, (bw, aw) in enumerate(self.slot):
            for side, w in (("a", aw), ("b", bw)):
                if len(w) >= 3 and w not in _STOP:
                    self.by_slot.setdefault((side, w), []).append(i)
            if self.hint[i]:
                self.by_slot.setdefault(("h", self.hint[i]), []).append(i)

    def wrong(self, i, rng, k=3):
        """k wrong answers for item i: answers of the same sort (a number for
        a number), from the cards nearest it, that fill the same blank in
        other cards ("____ receptor") or answer the same hint ("(class)"),
        alike in length and look; none that is the answer, holds it, sits in
        the question, or is another's twin."""
        it, items = self.items[i], self.items
        rel = {}
        for x, wgt in self.pre[i].items():
            for j in self.by_pre.get(x, ()):
                rel[j] = rel.get(j, 0) + wgt
        bw, aw = self.slot[i]
        slot = {}
        for side, w, wgt in (("a", aw, 2.5), ("b", bw, 1.0)):
            for j in self.by_slot.get((side, w), ()) if len(w) >= 3 and w not in _STOP else ():
                slot[j] = slot.get(j, 0) + wgt
        for j in self.by_slot.get(("h", self.hint[i]), ()) if self.hint[i] else ():
            slot[j] = slot.get(j, 0) + 3.0  # the card's own hint says what sort of answer
        cand = set(rel) | set(slot)
        if len(cand) < 40:
            cand |= set(rng.sample(range(len(items)), min(len(items), 80)))
        cand.discard(i)
        top = max(rel.values()) if rel else 1
        num, kind, nw, style = self.kind[i] == "n", self.kind[i], self.nw[i], self.style[i]
        cue = _CUE.search(it["q"])
        want = "dx" if cue and cue.group(1) else "rx" if cue and cue.group(2) else None
        scored = []
        for j in cand:
            a = items[j]["a"]
            if (self.kind[j] == "n") != num or _overlaps(a, it["a"]) or _shown(a, it["q"]):
                continue
            d = abs(self.nw[j] - nw)
            lens = sorted((len(a), len(it["a"])))
            sc = (2 * rel.get(j, 0) / top + slot.get(j, 0) + 1.5 * (self.kind[j] == kind) + 1.5 * (self.kind[j] == want)
                  + (1 if d == 0 else 0.5 if d == 1 else 0)
                  + 0.4 * (self.style[j] == style) - 1.0 * ((self.style[j] == "A") != (style == "A"))
                  + 0.3 * (("(" in a) == ("(" in it["a"])) - 1.5 * (lens[1] > 2.5 * max(1, lens[0]))
                  + 0.3 * rng.random())
            scored.append((-sc, j))
        scored.sort()
        out = []
        for _sc, j in scored:
            a = items[j]["a"]
            if any(_overlaps(a, o) for o in out):
                continue
            out.append(a)
            if len(out) == k:
                break
        return [_cased(o, it["a"]) for o in out]


_CUE = re.compile(r"\b(?:(diagnosis|disease|syndrome|condition|disorder)|(drug|medication|treated with|treatment of choice|agent))\b", re.I)


@functools.lru_cache(maxsize=50000)
def _prefixes(tag):
    """A tag and its parents, two parts deep and more, lower case."""
    parts = tag.split("::")
    return tuple("::".join(parts[:d]).lower() for d in range(2, len(parts) + 1))


def _cased(a, like):
    """A wrong answer in the right answer's case, so neither stands out
    ("loop" among "loop", "thiazide"; acronyms as they are)."""
    if not a or not a[:1].isascii() or not a[:1].isalpha() or _style(a) == "A" or (len(a) > 1 and a[1:2].isupper()):
        return a
    return (a[0].upper() if like[:1].isupper() else a[0].lower()) + a[1:]


def distractors(it, pool, rng, k=3):
    """Three wrong answers for a question (_Pool.wrong), from a pool of items."""
    pool = [it] + [o for o in pool if o is not it]
    return _Pool(pool).wrong(0, rng, k)


def _card(a, top):
    """An answer good on its own, as a white card, a tile or a prompt: not
    a number or value, not too thin, at most `top` long."""
    return len(a) <= top and not empty(a) and _shape(a)[0] != "n" and len(re.findall(r"[A-Za-z]", a)) >= 3 and not (
        " " in a and a.isupper())


def _plain(name):
    """A topic's name short and plain enough to draw or to set a dial by:
    three words at most, no "&", brackets or "of"."""
    return len(name.split()) <= 3 and not re.search(r"[&()/]|\bof\b", name, re.I)


def _apart(words, k=None):
    """Words none of which holds another ("ACE" and "ACE inhibitors" on one
    Links board are one word); the first k of them."""
    out = []
    for w in words:
        if not any(_overlaps(w, o) for o in out):
            out.append(w)
            if k and len(out) >= k:
                break
    return out


def _items(rows, dup):
    out = []
    for row in rows:
        it = item(row)
        if it and (norm(it["q"]), norm(it["a"])) not in dup:
            dup.add((norm(it["q"]), norm(it["a"])))
            out.append(it)
    return out


def _topics(items):
    """The cards' topic names, the most carded first, and {tag path: name}."""
    counts, named, shown = {}, {}, {}
    for it in items:
        if it.get("topic"):
            t = shown.setdefault(norm(it["topic"]), it["topic"])  # one topic, however it's capitalised
            counts[t] = counts.get(t, 0) + 1
            named.setdefault(it["tag"], t)
    return sorted(counts, key=lambda t: -counts[t]), named


def build(rows, name="", n=None, seed=None, near=()):
    """The pack for rows of cards (item's rows); n: how many cards the scope
    has (the rows may be a sample of it). near: rows of cards around the
    scope (gamenight_flow.near): answer choices and white cards, and when
    the scope's run short, Trivia's questions and the Links board and
    prompts."""
    rng = random.Random(seed)
    dup = set()
    items = _items(rows, dup)
    rng.shuffle(items)
    others = _items(near, dup)
    rng.shuffle(others)
    pool = items + others
    P = _Pool(pool)
    qs, asked = [], []

    def ask(i):
        it = pool[i]
        wrong = P.wrong(i, rng)
        if len(wrong) == 3:
            opts = [it["a"]] + wrong
            rng.shuffle(opts)
            # the whole card (its sentence, its Extra) is for the TV after the reveal; phones get shapes.
            # Its label says where it's from, unless that says the answer ("Signal Transducers")
            tag = it["where"] if it["where"] and not _overlaps(it["a"], it["where"]) else ""
            qs.append({"q": it["q"], "a": it["a"], "tag": tag, "opts": opts, "ans": opts.index(it["a"]),
                       "full": it["full"] if it["cloze"] else "", "extra": it["extra"]})
            asked.append(it)
    for i in range(min(len(items), CAPS["qs"] * 3 // 2)):  # a pack holds 150; a game asks ten
        ask(i)
    if len(qs) < QS_MIN:  # a small or picture-heavy scope: the cards around it, its own topics first
        mine = {norm(it["topic"]) for it in items if it["topic"]}
        around = sorted(range(len(items), len(pool)), key=lambda j: norm(pool[j]["topic"]) not in mine)
        for j in around:
            if len(qs) >= QS_MIN:
                break
            ask(j)
    blacks = [{"q": it["q"] if BLANK in it["q"] else f"{it['q']} {BLANK}", "a": it["a"], "full": it["full"], "tag": it["where"]}
              for it in items if _card(it["a"], WHITE_MAX)]
    # a hand: tonight's answers and as many from around them, so a small
    # scope still deals full, varied hands
    mine = _unique(it["a"] for it in items if _card(it["a"], WHITE_MAX))
    have = {norm(x) for x in mine}
    theirs = [a for a in _unique(it["a"] for it in others if _card(it["a"], WHITE_MAX)) if norm(a) not in have]
    whites = _unique(mine + theirs[:max(len(mine), WHITES_MIN)])
    topics, named = _topics(items)
    near_topics, near_named = _topics(others)
    # what reaches every phone: topic names (plans send those already);
    # card answers only for the Links board, and only when the topics run
    # short of a board's worth and more (CLAUDE.md's game-night exception)
    short = lambda its, top: [it["a"] for it in its if _card(it["a"], top)]
    words = _apart(_unique([t for t in topics + near_topics if len(t) <= WORD_MAX]), CAPS["words"])
    if len(words) < WORDS_MIN:
        words = _apart(_unique(words + short(items, WORD_MAX) + short(others, WORD_MAX)), WORDS_MIN)
    prompts = _unique([t for t in topics + near_topics if _plain(t)])
    blacks = mixed(blacks, topics, rng)
    rounds(qs, asked)
    pairs = twins(items, rng, named)
    if len(pairs) < TWINS_MIN:  # tonight's topics first, then their neighbours'
        have = {(p["a"]["t"], p["b"]["t"]) for p in pairs}
        pairs += [p for p in twins(pool, rng, dict(near_named, **named)) if (p["a"]["t"], p["b"]["t"]) not in have]
    pack = {"name": str(name)[:60], "n": len(rows) if n is None else int(n),
            "qs": qs, "blacks": blacks, "whites": whites, "words": words, "prompts": prompts,
            "twins": pairs, "draws": draws([t for t in topics if _plain(t)], rng), "scales": [list(x) for x in rng.sample(SCALES, SCALES_IN)] if topics else []}
    for k, cap in CAPS.items():
        pack[k] = pack[k][:cap]
    return pack


def pick_key(key):
    """A source's key (gamenight_flow.sources) for You › Pip Party's command,
    as hex: keys hold ":" and names, and a board command carries only
    letters, digits and :_.-"""
    return str(key).encode("utf-8").hex()


def unpick(arg):
    try:
        return bytes.fromhex(str(arg)).decode("utf-8")
    except ValueError:
        return None


def written(topics, k, rng):
    """k of Rounds' written cards, each its own, a {topic} one of tonight's;
    none without topics."""
    if not topics or k <= 0:
        return []
    out = []
    for t in rng.sample(WRITTEN, min(k, len(WRITTEN))):
        q = t.format(topic=rng.choice(topics)) if "{topic}" in t else t
        out.append({"q": q[0].upper() + q[1:], "a": "", "full": "", "tag": WRITTEN_TAG, "w": 1})
    return out


def draws(topics, rng, k=8):
    """Draw it's written prompts, k of them, each its own, filled with
    tonight's topics (each used once while they last); none without topics."""
    if not topics:
        return []
    names = rng.sample(topics, min(k, len(topics)))
    return [t.format(topic=names[i % len(names)]) for i, t in enumerate(rng.sample(DRAWS, min(k, len(DRAWS))))]


def mixed(blacks, topics, rng):
    """Tonight's black cards with the written ones among them, one in four."""
    out = list(blacks)
    for b in written(topics, (len(blacks) + 1) // 3, rng):
        out.insert(rng.randrange(len(out) + 1), b)
    return out


def names(tags):
    """{tag: its topic name}: the last part, or with its parent's in front
    where two tags end the same ("Renal pharm", "Neuro pharm")."""
    leaf = {t: topic_name(t.split("::")[-1]) for t in tags}
    seen = {}
    for t, n in leaf.items():
        seen.setdefault(norm(n), []).append(t)
    out = {}
    for t, n in leaf.items():
        if n and len(seen[norm(n)]) > 1 and "::" in t:
            up = topic_name(t.split("::")[-2])
            both = f"{up} {n[0].lower() + n[1:]}" if up else n
            out[t] = both if len(both) <= TOPIC_MAX else n
        else:
            out[t] = n
    return out


def twins(items, rng, named=None):
    """Imposter's pairs: two of tonight's topics, two cards each at least,
    the likeliest to be mixed up first: names that start alike (Nephritic,
    Nephrotic), share a word (Type I and Type III hypersensitivity), or sit
    side by side under one tag; never one inside the other ("Aortic
    stenosis", "Aortic stenosis murmur"). A few of each one's answers, none
    the other's, to tell them apart. named: unused (the cards carry their
    topics)."""
    by, path, name = {}, {}, {}
    for it in items:
        if it.get("topic"):
            t = name.setdefault(norm(it["topic"]), it["topic"])  # one topic, however it's capitalised
            by.setdefault(t, []).append(it)
            path.setdefault(t, it["tag"])
    facts = {t: [x for x in its if _card(x["a"], WHITE_MAX)] for t, its in by.items()}
    ts = sorted(t for t, its in by.items() if len(its) >= 2 and facts[t] and _concept(t) and _plain(t))
    pairs = []
    for i, a in enumerate(ts):
        for b in ts[i + 1:]:
            na, nb = _one(a), _one(b)
            same = len(os.path.commonprefix([na, nb]))
            share = len(_stems(a) & _stems(b))
            up_a, up_b = path[a].rsplit("::", 1)[0], path[b].rsplit("::", 1)[0]
            sib = "::" in path[a] and up_a == up_b
            if same < 4 and not share and not sib:  # unrelated: the most pairs, and the cheapest to tell
                continue
            if na in nb or nb in na or _words(a) <= _words(b) or _words(b) <= _words(a) or _numbered(a, b) or _alike(a, b):
                continue
            pairs.append((-(same + 3 * share + 2 * sib), rng.random(), a, b, up_a if sib else ""))
    pairs.sort()
    out = []
    for _s, _r, a, b, up in pairs:
        fa, fb = _apart_facts(facts[a], facts[b], a, b), _apart_facts(facts[b], facts[a], a, b)
        if not fa or not fb:
            continue
        part = tag_topic(up)[1] if up else ""
        if not part:
            common = [w for w in a.split() if w.lower() in {x.lower() for x in b.split()} and w.lower() not in _STOP]
            part = " ".join(common) if common else "Tonight's cards"
        out.append({"part": part[0].upper() + part[1:], "a": {"t": a, "facts": fa}, "b": {"t": b, "facts": fb}})
        if len(out) == CAPS["twins"]:
            break
    return out


def _apart_facts(mine, theirs, a, b, k=3):
    """What tells a topic from its twin, as its cards say it: up to k of its
    cards, each {a: its answer, s: its sentence, when short enough to read on
    the TV}; none whose answer names either topic or is the twin's too."""
    other = {_one(x["a"]) for x in theirs}
    mark = (_words(a) ^ _words(b)) - _STOP  # the words that tell the two names apart ("B6", "C")
    out, seen = [], set()
    for x in mine:
        if (_overlaps(x["a"], a) or _overlaps(x["a"], b) or _one(x["a"]) in other or _one(x["a"]) in seen
                or _words(x["a"]) & mark):  # a fact that names its topic gives the game away
            continue
        seen.add(_one(x["a"]))
        out.append({"a": x["a"], "s": x["full"] if x.get("cloze") and len(x["full"]) <= FACT_MAX else ""})
        if len(out) == k:
            break
    return out


@functools.lru_cache(maxsize=20000)
def _one(name):
    """A name in the singular, for telling two names of one thing apart."""
    return "".join(_sing(w) for w in re.findall(r"[a-z0-9]+", str(name).lower()))


def _concept(name):
    """A topic that is a thing to know, not a heading: no "Other …", no side
    of a subject ("Cardio pathology")."""
    w = name.split()
    return not re.match(r"(other|misc|more|additional|general)\b", name, re.I) and not (w and SECTION.match(w[-1]))


def _alike(a, b):
    """One topic under two names: one the other with more words to it
    ("Transplant and Rejection", "Transplant-Rejection-Prophylaxis"), or a
    typo apart ("Hypersensitvity"). Two that differ each their own way stay
    two ("Class I" and "Class II", "Nephritic" and "Nephrotic")."""
    wa, wb = _words(a) - _STOP, _words(b) - _STOP
    da, db = wa - wb, wb - wa
    if not da or not db:
        return True
    if len(da) != 1 or len(db) != 1:
        return False
    x, y = _one(next(iter(da))), _one(next(iter(db)))
    return min(len(x), len(y)) >= 5 and len(x) != len(y) and difflib.SequenceMatcher(None, x, y).ratio() >= 0.88


def _numbered(a, b):
    """Two parts of one heading: "Pharmacology I" and "Pharmacology II"."""
    x, y = _unnumbered(a), _unnumbered(b)
    return x == y or x in y or y in x


@functools.lru_cache(maxsize=20000)
def _unnumbered(n):
    return re.sub(r"\s+([ivx]+|\d+)$", "", n.strip(), flags=re.I).lower()


def _unique(xs):
    """The first of each, a plural and its singular one ("GAP", "GAPs")."""
    seen, out = set(), []
    for x in xs:
        k = _one(x)
        if x and k and k not in seen:
            seen.add(k)
            out.append(x)
    return out


def fit(pack):
    """{game: how much of what it needs the pack has}, and which of the
    menu's (GAMES) can't run."""
    have = {g: len((pack or {}).get(k) or []) for g, (k, _n) in NEEDS.items()}
    return have, sorted(g for g, _l in GAMES if have[g] < NEEDS[g][1])
