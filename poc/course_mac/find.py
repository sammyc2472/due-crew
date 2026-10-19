"""Finding a lecture's cards in a deck, without a model: the deck's tags
indexed, a word list matched to tag paths the way the builder's Suggest
matches a date's name (every word in the path, one in its last part), tags
grouped by resource (the first #/^ part after the root: a video series, a
book), and card text made plain for the model to read. Pure: the index is
built from rows the glue reads."""

import bisect
import html
import re
import unicodedata

SEP = "::"
STOP = {"and", "the", "for", "with", "part", "lecture", "lec", "week", "day", "read", "watch", "chapter", "unit",
        "video", "videos", "intro", "introduction", "review", "notes", "extra", "extras", "session", "class",
        "describe", "explain", "define", "list", "identify", "discuss", "compare", "contrast", "understand", "name",
        "outline", "apply", "relate", "recognize", "including", "between", "their", "they", "this", "that", "from",
        "into", "how", "why", "what", "which", "when", "only", "also", "make", "made", "role", "roles", "use", "used",
        "basic", "overview", "principles", "concepts", "objective", "objectives", "student", "students", "able",
        "will", "should", "each", "other", "these", "those", "its", "are", "was", "were", "has", "have", "can",
        "worse", "better", "relieve", "lower", "rises", "ones"}
# a deck's own bookkeeping, never a lecture's
SKIP_ROOTS = ("duecrew", "course", "leech", "marked", "#ak_other", "ak_other")
_TAG_RE = re.compile(r"<[^>]*>")
_MEDIA_RE = re.compile(r"\[sound:[^\]]*\]")
_CLOZE = re.compile(r"\{\{c(\d+)::(.*?)(?:::[^}]*)?\}\}", re.S)


def norm(s):
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()


def words(s, keep_short=False):
    """The words that name something: lowercase, no stop words; numbers out
    (a "03_" is a deck's order)."""
    out = []
    for w in re.split(r"[^a-z0-9]+", norm(s)):
        if not w or w in STOP or w.isdigit():
            continue
        if len(w) < 3 and not keep_short:
            continue
        out.append(w)
    return out


def same(a, b):
    """"arrhythmia" and "arrhythmias", "cardiac" and "cardio": one word here
    (builder.js Suggest.same)."""
    s, l = (a, b) if len(a) <= len(b) else (b, a)
    if s == l or (len(s) >= 4 and l.startswith(s)):
        return True
    k = 0
    while k < len(s) and s[k] == l[k]:
        k += 1
    return k >= 5 and k >= 0.8 * len(s)


def word(seg):
    """A tag part, readable: "05_Elimination_Kinetics" reads "Elimination
    Kinetics", "#Videos" reads "Videos" (Due Crew's plans._word)."""
    s = re.sub(r"^[#^$!]+", "", str(seg))
    s = re.sub(r"(?i)^AK_", "", s)
    s = re.sub(r"(?i)_v\d+$", "", s)
    s = re.sub(r"\s+", " ", s.replace("_", " ")).strip()
    m = re.match(r"^0*\d+\s*[.)-]?\s+(\S.*)$", s)
    return (m.group(1) if m else s) or str(seg)


def resource_of(path):
    """(resource, the rest, readable): "#Deck_v1::#VideosA::Cardio::Heart_Failure"
    -> ("VideosA", "Cardio › Heart Failure")."""
    segs = str(path).split(SEP)
    ri = next((i for i, x in enumerate(segs) if i > 0 and x[:1] in "#^"), -1)
    if 0 <= ri < len(segs) - 1:
        return word(segs[ri]), " › ".join(word(x) for x in segs[ri + 1:])
    return word(segs[0]) if len(segs) > 1 else "", " › ".join(word(x) for x in segs[1:] or segs)


def plain(text):
    """A field without formatting or media; a cloze as [c1: its words]."""
    t = _MEDIA_RE.sub(" ", str(text or ""))
    t = _CLOZE.sub(lambda m: f"[c{m.group(1)}: {m.group(2)}]", t)
    t = re.sub(r"(?i)<br\s*/?>|</div>|</p>|</li>", " ", t)
    t = html.unescape(_TAG_RE.sub("", t))
    return re.sub(r"\s+", " ", t).strip()


def note_text(fields, limit=360):
    """A note to read: its first fields, plain, joined, cut at `limit`."""
    parts = [plain(f) for f in fields if plain(f)]
    t = " | ".join(parts)
    return t if len(t) <= limit else t[:limit - 1].rsplit(" ", 1)[0] + "…"


def cloze_nums(fields):
    return sorted({int(n) for f in fields for n in re.findall(r"\{\{c(\d+)::", str(f or ""))})


class DeckIndex:
    """One deck's notes and cards, by tag. notes: {nid: (guid, tags string)};
    cards: [(cid, nid, ord, queue, type)]. Built once a run (the glue reads
    the rows on the main thread)."""

    def __init__(self, notes, cards):
        self.guid = {int(n): g for n, (g, _t) in notes.items()}
        self.tags_of = {}
        self.full = {}  # lowercased full tag -> set of nids
        self.case = {}  # lowercased tag or prefix -> as written
        for nid, (_g, tags) in notes.items():
            ts = [t for t in str(tags or "").split() if t]
            self.tags_of[int(nid)] = ts
            for t in ts:
                lo = t.lower()
                self.full.setdefault(lo, set()).add(int(nid))
                segs = t.split(SEP)
                for i in range(1, len(segs) + 1):
                    p = SEP.join(segs[:i])
                    self.case.setdefault(p.lower(), p)
        self.cards_of = {}
        self.card = {}
        for cid, nid, ord_, q, typ in cards:
            self.cards_of.setdefault(int(nid), []).append(int(cid))
            self.card[int(cid)] = (int(nid), int(ord_), int(q), int(typ))
        self._under = {}
        self._tok = None
        self._leaf_ix = {}
        self._keys = None

    def under(self, prefix, cap=None):
        """The nids under a tag (it, or anything below it); None past `cap`
        notes (too broad to be a lecture's, and not worth gathering)."""
        lo = str(prefix).lower()
        if lo in self._under:
            got = self._under[lo]
            return None if cap and len(got) > cap else got
        if self._keys is None:
            self._keys = sorted(self.full)
        got = set(self.full.get(lo, ()))
        i = bisect.bisect_left(self._keys, lo + "::")
        while i < len(self._keys) and self._keys[i].startswith(lo + "::"):
            got |= self.full[self._keys[i]]
            if cap and len(got) > cap:
                return None
            i += 1
        self._under[lo] = got
        return got

    def cids_of(self, nids, clozes=None):
        """The cards of these notes; clozes: {nid: [cloze numbers]} keeps a
        cloze note to those cards (its ord + 1)."""
        out = []
        for n in nids:
            keep = (clozes or {}).get(n) or (clozes or {}).get(str(n))
            for c in self.cards_of.get(int(n), []):
                if keep and self.card[c][1] + 1 not in keep:
                    continue
                out.append(c)
        return out

    def tokens(self):
        """{prefix lower: (leaf words, all words, depth)}, once, parents
        first so a path's words are its parent's and its own; and the leaf
        words' first four letters indexed (same() needs them to agree)."""
        if self._tok is None:
            memo, tok, ix = {}, {}, {}
            for lo in sorted(self.case, key=lambda k: k.count(SEP)):
                root = lo.split(SEP, 1)[0]
                if root.lstrip("#^") in SKIP_ROOTS or root in SKIP_ROOTS:
                    continue
                seg = self.case[lo].rsplit(SEP, 1)[-1]
                leaf = memo.get(seg)
                if leaf is None:
                    leaf = memo[seg] = tuple(words(word(seg)))
                parent = lo.rsplit(SEP, 1)[0] if SEP in lo else None
                every = (tok[parent][1] if parent in tok else ()) + leaf
                tok[lo] = (leaf, every, lo.count(SEP) + 1)
                for w in set(leaf):
                    ix.setdefault(w[:4], []).append(lo)
            self._tok, self._leaf_ix = tok, ix
        return self._tok

    def named_by(self, word_lists):
        """The prefixes whose last part has a word that could be one of these."""
        self.tokens()
        out = set()
        for ws in word_lists:
            for w in ws:
                out.update(self._leaf_ix.get(w[:4], ()))
        return out

    def counts(self, cids):
        """(cards, never studied, suspended, leeches) among cids."""
        n = new = sus = 0
        for c in cids:
            _nid, _o, q, typ = self.card.get(c, (0, 0, 0, 0))
            n += 1
            new += typ == 0
            sus += q == -1
        return n, new, sus, sum(1 for c in cids if self.is_leech(c))

    def is_leech(self, cid):
        nid = self.card.get(cid, (0,))[0]
        return any(t.lower() == "leech" for t in self.tags_of.get(nid, ()))


def _in(w, ws):
    return w in ws or any(same(w, x) for x in ws)


def hits(term_words, leaf, every):
    """A term names this tag: every word of it in the path, one in its last part."""
    if not term_words:
        return False
    if not all(_in(w, every) for w in term_words):
        return False
    return any(_in(w, leaf) for w in term_words)


def head_hit(term_words, leaf):
    """A looser match for a term two or more words long: its last word (the
    thing it names) is in the tag's last part. "loop diuretic" names
    "Diuretics"."""
    return len(term_words) >= 2 and any(same(term_words[-1], x) for x in leaf)


def candidates(idx, terms, title, max_notes=400, limit=10, skip=()):
    """The tags these terms name, best first: [{tag, terms, title_hit,
    nids}]. A term naming a tag outright counts twice a looser one. A tag
    holding more than max_notes notes is too broad to be a lecture's; a
    parent with the same notes as a child gives way to it."""
    tw = [(t, words(t)) for t in terms]
    tw = [(t, w) for t, w in tw if w]
    title_w = words(title)
    found = []
    tok = idx.tokens()
    by_key = {}  # a word's first four letters -> the terms holding such a word
    for i, (_t, w) in enumerate(tw):
        for x in w:
            by_key.setdefault(x[:4], set()).add(i)
    title_keys = {x[:4] for x in title_w}
    skip_lo = [s.lower() for s in skip]
    for lo in idx.named_by([w for _t, w in tw] + [title_w]):
        leaf, every, depth = tok[lo]
        if depth < 2 or any(lo == s or lo.startswith(s + "::") for s in skip_lo):
            continue
        maybe = sorted(set().union(*[by_key.get(x[:4], ()) for x in leaf])) if leaf else []
        got = [tw[i][0] for i in maybe if hits(tw[i][1], leaf, every)]
        loose = [tw[i][0] for i in maybe if tw[i][0] not in got and head_hit(tw[i][1], leaf)]
        th = bool(title_w) and any(x[:4] in title_keys for x in leaf) and hits(title_w, leaf, every)
        if not got and not loose and not th:
            continue
        nids = idx.under(lo, max_notes)
        if not nids:
            continue
        found.append({"tag": idx.case[lo], "terms": got + loose, "score": 2 * len(got) + len(loose) + (6 if th else 0),
                      "title_hit": th, "nids": nids, "depth": depth})
    found.sort(key=lambda f: (-f["score"], -f["depth"], len(f["nids"])))
    out = []
    for f in found:
        # the same notes as one already in (a parent of a single child): one row
        if any(f["nids"] == g["nids"] for g in out):
            continue
        # a tag inside one already in adds nothing
        if any(f["tag"].lower().startswith(g["tag"].lower() + "::") for g in out):
            continue
        out.append(f)
        if len(out) >= limit:
            break
    return out


def title_score(title, tag, idx):
    """How fully a lecture's title names a tag: 2 every word, 1 some, 0 none."""
    tw = words(title)
    tok = idx.tokens().get(str(tag).lower())
    if not tw or not tok:
        return 0
    leaf, every, _d = tok
    if hits(tw, leaf, every):
        return 2
    return 1 if any(any(same(w, x) for x in leaf) for w in tw) else 0


def term_hits(text, terms):
    """Which terms a card's text holds, as whole words."""
    t = " " + norm(text) + " "
    out = []
    for term in terms:
        w = norm(term).strip()
        if w and re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", t):
            out.append(term)
    return out


def search_terms(terms):
    """An Anki search for any of the terms as whole words, inside parentheses."""
    parts = []
    for t in terms:
        s = re.sub(r"[^A-Za-z0-9 '\-]", " ", str(t)).strip()
        s = re.sub(r"\s+", " ", s)
        if len(s) < 2:
            continue
        parts.append(f'"w:{s}"')
    return "(" + " OR ".join(parts) + ")" if parts else ""


def tag_search(path):
    """A tag and everything under it, its \\ " _ * read as themselves."""
    esc = re.sub(r'([\\"*_])', r"\\\1", str(path))
    return f'("tag:{esc}" OR "tag:{esc}::*")'
