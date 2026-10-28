"""Game night from Anki (3.9.5): tonight's cards as the six games' pack.

Pure: a scope as an Anki search, and a pack from rows of cards (the glue,
gamenight_flow.py, reads them from the collection). The TV is a window in
Anki (ui/game_night_window.py) that the add-on hands this pack; it never
goes to duecrew.com. What reaches phones through the table is the games'
business (site/public/table.js): Trivia sends none of a card's words,
Rounds sends each hand its answers (Sam's yes), and the rest send topic
names, which plans already send.

A pack: {name, n, qs, blacks, whites, words, prompts, twins}
  qs      Trivia: {q, a, tag, opts (four), ans (the right one's place)}
  blacks  Rounds' black cards: {q, a, full, tag}; whites: answers
  words   Links' board: topic names, then short answers
  prompts Draw it, Somewhere between: topic names, then short answers
  twins   Imposter: {part, a: {t, facts}, b: {t, facts}}, sibling tags
"""

import html
import os
import random
import re

Q_MAX = 200        # a question, as the TV shows it
A_MAX = 40         # an answer: a card with a longer one isn't a question
WHITE_MAX = 32     # a white card in a hand
WORD_MAX = 18      # a Links tile
TOPIC_MAX = 36
CAPS = {"qs": 150, "blacks": 150, "whites": 300, "words": 80, "prompts": 80, "twins": 30}
READ_MAX = 1500    # cards read for a pack: a big scope is sampled
BLANK = "____"
# what each game needs from a pack before its tile lights up
NEEDS = {"trivia": ("qs", 1), "rounds": ("blacks", 1), "links": ("words", 25), "imposter": ("twins", 1),
         "draw": ("prompts", 1), "between": ("prompts", 1)}
SKIP_TAGS = ("leech", "marked")

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
    tags gone, entities read."""
    t = re.sub(r"<(script|style)\b.*?</\1\s*>", " ", str(text or ""), flags=re.S | re.I)
    t = re.sub(r"\[sound:[^\]]*\]|\[\[type:[^\]]*\]\]", " ", t)
    t = re.sub(r"<br\s*/?>|</(div|p|li)>", " ", t, flags=re.I)
    t = re.sub(r"<[^>]*>", "", t)
    return " ".join(html.unescape(t).split())


def cloze(text, n):
    """(question, answer, full) for cloze number n: its deletions a blank,
    the others shown; None when there's no such cloze, or more than one
    piece of it (two blanks read badly on a TV)."""
    hits = [m for m in _CLOZE.finditer(str(text or "")) if m.group(1) == str(n)]
    if len(hits) != 1:
        return None
    ans = clean(hits[0].group(2))
    q = _CLOZE.sub(lambda m: BLANK if m.group(1) == str(n) else m.group(2), str(text))
    full = _CLOZE.sub(lambda m: m.group(2), str(text))
    return clean(q), ans, clean(full)


def item(row):
    """One card as a question, or None. row: (cid, ord, is_cloze, fields,
    tags). A cloze asks its own number (ord + 1); a basic card its front,
    a reversed one its back."""
    cid, ord_, is_cloze, fields, tags = row
    fields = list(fields or [])
    if is_cloze:
        got = cloze(fields[0] if fields else "", int(ord_) + 1)
        if not got:
            return None
        q, a, full = got
    else:
        if len(fields) < 2:
            return None
        front, back = (fields[1], fields[0]) if int(ord_) == 1 else (fields[0], fields[1])
        q, a = clean(front), clean(back)
        full = f"{q} {a}"
    if not q or not a or len(a) > A_MAX or len(q) > Q_MAX or norm(a) == norm(q) or not norm(a):
        return None
    tag = deepest(tags)
    return {"cid": int(cid), "q": q, "a": a, "full": full[:Q_MAX + A_MAX], "tag": tag, "where": label(tag), "cloze": bool(is_cloze)}


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


def topic_name(part):
    """A tag's part as people read it: "01_Growth_Adaptations" → "Growth
    adaptations"; "" when nothing readable is left."""
    t = str(part).lstrip("#^$!@").replace("_", " ")
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
_DX = re.compile(r"(itis|osis|emia|oma|pathy|syndrome|disease|failure|fibrillation|flutter|necrosis)\b")


def _shape(a):
    """What sort of answer: a value (it starts with a number), a drug's
    name, a diagnosis, or a word; and its length, roughly."""
    t = a.lower().strip()
    kind = ("n" if re.match(r"^[<>~≈]?\d", t) else "rx" if " " not in t and _DRUG.search(t)
            else "dx" if _DX.search(t) else "w")
    return kind, min(4, len(t) // 8)


def distractors(it, pool, rng, k=3):
    """Three wrong answers for a question, from the cards nearest it in the
    tag tree: its own tag first, then each parent's, then anything; ones
    shaped like the answer (a number for a number, a short word for a
    short word) before the rest."""
    want, mine = _shape(it["a"]), norm(it["a"])
    tag = it["tag"]
    rings = []
    parts = tag.split("::") if tag else []
    for depth in range(len(parts), 0, -1):
        pre = "::".join(parts[:depth]).lower()
        rings.append([o for o in pool if o["tag"].lower() == pre or o["tag"].lower().startswith(pre + "::")])
    rings.append(pool)
    out, seen = [], {mine}
    for ring in rings:
        cand = [o["a"] for o in ring if norm(o["a"]) not in seen]
        rng.shuffle(cand)
        cand.sort(key=lambda a: (_shape(a)[0] != want[0], _shape(a) != want))  # its sort first, then its size; the shuffle breaks ties
        for a in cand:
            if norm(a) in seen:
                continue
            out.append(a)
            seen.add(norm(a))
            if len(out) == k:
                return out
    return out


def build(rows, name="", n=None, seed=None):
    """The pack for rows of cards (item's rows); n: how many cards the scope
    has (the rows may be a sample of it)."""
    rng = random.Random(seed)
    items, dup = [], set()
    for row in rows:
        it = item(row)
        if it and (norm(it["q"]), norm(it["a"])) not in dup:
            dup.add((norm(it["q"]), norm(it["a"])))
            items.append(it)
    rng.shuffle(items)
    qs = []
    for it in items:
        wrong = distractors(it, items, rng)
        if len(wrong) == 3:
            opts = [it["a"]] + wrong
            rng.shuffle(opts)
            qs.append({"q": it["q"], "a": it["a"], "tag": it["where"], "opts": opts, "ans": opts.index(it["a"])})
    blacks = [{"q": it["q"] if BLANK in it["q"] else f"{it['q']} {BLANK}", "a": it["a"], "full": it["full"], "tag": it["where"]}
              for it in items if len(it["a"]) <= WHITE_MAX]
    whites = _unique(it["a"] for it in items if len(it["a"]) <= WHITE_MAX)
    counts = {}
    for it in items:
        if it["tag"]:
            counts[it["tag"]] = counts.get(it["tag"], 0) + 1
    named = names(counts)
    topics = _unique(named[t] for t in sorted(counts, key=lambda t: -counts[t]))
    short = _unique(it["a"] for it in items if len(it["a"]) <= WORD_MAX)
    words = _unique([t for t in topics if len(t) <= WORD_MAX] + short)
    prompts = _unique(topics + [it["a"] for it in items if len(it["a"]) <= TOPIC_MAX])
    pack = {"name": str(name)[:60], "n": len(rows) if n is None else int(n),
            "qs": qs, "blacks": blacks, "whites": whites, "words": words, "prompts": prompts,
            "twins": twins(items, rng, named)}
    for k, cap in CAPS.items():
        pack[k] = pack[k][:cap]
    return pack


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
    """Imposter's pairs: two tags side by side under one parent, two cards
    each at least, the likeliest to be mixed up first (names that start
    alike: Nephritic, Nephrotic); a few of each one's answers to tell them
    apart."""
    by = {}
    for it in items:
        if it["tag"] and "::" in it["tag"]:
            by.setdefault(it["tag"], []).append(it)
    name = lambda t: (named or {}).get(t) or topic_name(t.split("::")[-1])
    kids = {}
    for t, its in by.items():
        if len(its) >= 2 and name(t):
            kids.setdefault(t.rsplit("::", 1)[0], []).append(t)
    pairs = []
    for parent, ts in kids.items():
        ts = sorted(ts)
        for i, a in enumerate(ts):
            for b in ts[i + 1:]:
                na, nb = name(a), name(b)
                if norm(na) == norm(nb):
                    continue
                same = len(os.path.commonprefix([norm(na), norm(nb)]))
                pairs.append((-same, rng.random(), parent, a, b, na, nb))
    pairs.sort()
    return [{"part": label(parent) or topic_name(parent.split("::")[-1]),
             "a": {"t": na, "facts": _unique(x["a"] for x in by[a] if len(x["a"]) <= WHITE_MAX)[:3]},
             "b": {"t": nb, "facts": _unique(x["a"] for x in by[b] if len(x["a"]) <= WHITE_MAX)[:3]}}
            for _s, _r, parent, a, b, na, nb in pairs[:CAPS["twins"]]]


def _unique(xs):
    seen, out = set(), []
    for x in xs:
        k = norm(x)
        if x and k and k not in seen:
            seen.add(k)
            out.append(x)
    return out


def fit(pack):
    """{game: how much of what it needs the pack has}, and which can't run."""
    have = {g: len((pack or {}).get(k) or []) for g, (k, _n) in NEEDS.items()}
    return have, sorted(g for g, (_k, n) in NEEDS.items() if have[g] < n)
