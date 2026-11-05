"""Magic search (3.9.7, Sam's "say what you want to study"): one box that
reads what's typed into what to find (a deck's own tags, Anki's filters, a
bank's QIDs, IDs, a search) and what's coming up (a quiz, an exam, an
away spell, a plan's dates as text). Rules, not AI: every word is matched
to the deck's tags on this computer and nothing leaves it.

Pure: the text, the deck's tags (Tree), today and the plans in; a reading
out, and the Anki search for it. magic_flow is the glue.

How topic words land (the mock's rules, Sam's picks):
- a word hits a tag's part when it's the same, the same once a plural is
  off, a prefix of 4+ letters, one letter off at 5+, or the initials of
  a run of the part's words ("hf" is Heart Failure inside
  Heart_Failure_Drugs);
- a tag is found when every word hits one of its parts and one of them
  hits its last part; tags are grouped by that last part's name (one chip
  a topic, its many tags inside), and a parent covers its children;
- only a topic the words name whole is ticked (Sam: "only what you
  named"); the rest are offered beside it;
- "and", ",", "or", "&" split topics; "but not", "except", "without",
  "not" leave one out; words no tag has search the cards' text."""

import datetime
import functools
import re

SEP = "::"
GROUPS_MAX = 8        # chips offered for one topic
NEG_MAX = 4           # topics left out at once
LIMIT_MAX = 9999      # "10 new platelets": a number before the topic, at most this
SOON = 14             # days: an exam this soon (or a quiz any time) is a date on a plan; later, Settings' exam
LINES_MAX = 400       # plan text: lines read

GENERIC = frozenset("disorders disorder disease diseases overview basics basic intro introduction general misc "
                    "miscellaneous other others principles review high yield fundamentals summary soap soa notes part "
                    "the of and".split())
STOP = frozenset("i i'd i'm im i've ive me my mine the a an cards card from on for everything all of to that this "
                 "these those yet ones one some about with study studying in at deck decks stuff topics topic show "
                 "find get give want need please have has had got there is are was be will ill i'll its it's so "
                 "just only also do does what which any every by before till until next week weeks lets let's go "
                 "into onto up over again more most cover covering covers learn notes note review reviews revise "
                 "revising cram cramming drill quiz test exam practice look looking at can could should would "
                 "really still left and or".split())
_DOWS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_MONS = {m: i + 1 for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())}

# Anki's filters, in the order they're read: (key, words, label, search). A
# key with N takes the number the words caught. The board's row offers the
# ones without N (ROW).
FILTERS = (
    ("mN", r"\bmissed in the (?:last|past) (\d{1,3}) days?\b", "Missed in {n} days", "rated:{n}:1"),
    ("dN", r"\bdue (?:in the next|within|in) (\d{1,3}) days?\b", "Due in {n} days", "prop:due<={n} -is:new"),
    ("aN", r"\badded in the (?:last|past) (\d{1,3}) days?\b", "Added in {n} days", "added:{n}"),
    ("new", r"\b(?:not seen(?: yet)?|haven'?t seen(?: yet)?|never seen|unseen|new)\b", "New", "is:new"),
    ("seen", r"\b(?:seen|reviewed|studied|started)\b", "Seen", "-is:new"),
    ("susp", r"\bsuspended\b", "Suspended", "is:suspended"),
    ("learn", r"\b(?:in learning|learning|relearning)\b", "Learning", "is:learn"),
    ("tom", r"\bdue tomorrow\b", "Due tomorrow", "prop:due=1"),
    ("due", r"\b(?:due today|due now|due)\b", "Due today", "is:due"),
    ("m1", r"\b(?:missed|got wrong|failed) today\b", "Missed today", "rated:1:1"),
    ("m7", r"\b(?:i )?(?:missed|got wrong|failed)(?: this week)?\b", "Missed this week", "rated:7:1"),
    ("leech", r"\bleech(?:es)?\b", "Leeches", "tag:leech"),
    ("flag", r"\bflagged\b", "Flagged", "-flag:0"),
    ("add7", r"\badded this week\b", "Added this week", "added:7"),
)
_FILT = {k: (re.compile(rx), label, q) for k, rx, label, q in FILTERS}
ROW = ("new", "seen", "susp", "learn", "due", "tom", "m1", "m7", "leech", "flag", "add7")

_SEARCHY = re.compile(r"(?:^|[\s(])-?(?:tag|deck|nid|cid|note|card|is|flag|prop|added|rated|introduced|"
                      r"edited|preset):", re.I)  # Anki's own words; "anemia or platelets" is ours (two topics)
_LONG = re.compile(r"(?<![0-9])[0-9]{10,13}(?![0-9])")
_SHORT = re.compile(r"(?<![0-9])[0-9]{3,9}(?![0-9])")
_IDS_ONLY = re.compile(r"^(?:[\s,;|/#.\-:()\u2229]|qids?|question|questions|ids?|nids?|cids?|notes?|cards?|q|and|or)*$", re.I)
_PLAN_LINE = re.compile(r"^\s*(?:[-*\u2022]\s+)?`?\d{4}-\d{2}-\d{2}\s*\|")
_KINDS = ("practice exam", "block exam", "shelf exam", "midterm", "final", "quiz", "test", "exam", "shelf")
_NAME_ONLY = frozenset("practice block shelf pop big class unit module weekly my our a an the".split())


# ---- words ----

def stem(w):
    """A word with its plural off: "ies" to "y", a last "s" (not "ss") gone."""
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("s") and not w.endswith("ss") and len(w) > 3:
        return w[:-1]
    return w


def lev1(a, b):
    """Within one letter: one added, gone, changed, or two side by side swapped."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    i = 0
    while i < len(a) and i < len(b) and a[i] == b[i]:
        i += 1
    if len(a) == len(b):
        return a[i + 1:] == b[i + 1:] or (i + 1 < len(a) and a[i] == b[i + 1] and a[i + 1] == b[i] and a[i + 2:] == b[i + 2:])
    return a[i + 1:] == b[i:] if len(a) > len(b) else a[i:] == b[i + 1:]


FILLER = frozenset("chapter chapters ch section sections sec lecture lectures lec part unit video videos module "
                   "lesson lessons page pages".split())  # "chapter 3": a word a tag may leave out
_SMALL = frozenset("and of the in to for with a an on vs or at by from".split())  # not in a name's initials
_ROMAN = re.compile(r"^(?:i|ii|iii|iv|v|vi|vii|viii|ix|x|\d+)$")


def _bare(part):
    """A tag part without its marks: #/^/*/!/$ and a leading number ("05_", "*30 ") off."""
    p = re.sub(r"^[#^*!$~]+", "", str(part))
    p = re.sub(r"^\*?[0-9]+[_.\-\s]+(?=\D)", "", p)
    return p.lstrip("*_ ")


def _lead(part):
    """A part's leading number ("03_Neoplasia": 3), or None."""
    m = re.match(r"^[#^*!$~]*\*?([0-9]{1,3})[_.\-\s]", str(part))
    return int(m.group(1)) if m else None


def _main(part):
    """A part's name outside its brackets: "Acute_Kidney_Injury_(AKI)_[OLD" is Acute Kidney Injury."""
    p = _bare(part).replace("_", " ")
    p = re.sub(r"\([^)]*\)?|\[[^\]]*\]?", " ", p)
    return p


_ROMANS = {"i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6", "vii": "7", "viii": "8", "ix": "9", "x": "10"}


def part_words(part):
    """A tag part's words, its name's alone (brackets off): split on _ and
    spaces, a roman number read as one ("Type II" is type 2)."""
    ws = [w for w in re.split(r"[\s\-/&+.,:;()\[\]'*]+", _main(part).lower()) if w]
    return [_ROMANS.get(w, w) if i else w for i, w in enumerate(ws)]


def abbrs(part):
    """The short names a part gives itself in brackets: "Acute Kidney Injury (AKI)" gives aki."""
    return [x.lower() for x in re.findall(r"\(([A-Za-z][A-Za-z0-9]{1,7})\)", _bare(part).replace("_", " "))]


def pretty(part):
    """A tag part as a name: "05_Heart_Failure_(HF)" is "Heart Failure"."""
    return " ".join(_main(part).split()).strip(" :-&,") or " ".join(_bare(part).replace("_", " ").split()) or str(part)


def initials(ws):
    """A run of words' initials, the small ones skipped ("mice and men": mm)."""
    return _initials(tuple(ws))


@functools.lru_cache(maxsize=1 << 16)
def _initials(ws):
    # 3.9.7 (the energy review): asked for every tag's run of words at every keystroke; worked out once each
    return "".join(x[0] for x in ws if x not in _SMALL and not _ROMAN.match(x))


SAME, PREFIX, FUZZY, INITIALS, ABBR = "same", "prefix", "fuzzy", "initials", "abbr"


def cover(w, ws, short=()):
    """Which of a part's words (ws) the typed word w names, and how: (places,
    how) or None. Its bracketed short name ("aki" for Acute Kidney Injury
    (AKI)) names it all; the initials of a run of two or more ("hf": heart
    failure); else one word the same, plural or not, begun (4+ letters), or
    one letter off (5+)."""
    if w in short and ws:
        return set(range(len(ws))), ABBR
    sw = stem(w)
    same = {i for i, x in enumerate(ws) if x == w or stem(x) == sw}
    if same:
        return same, SAME
    pre = {i for i, x in enumerate(ws) if len(w) >= 4 and x.startswith(w)}
    if pre:
        return pre, PREFIX
    if len(w) >= 2:
        sig = [i for i, x in enumerate(ws) if x not in _SMALL and not _ROMAN.match(x)]
        for a in range(len(sig)):
            for z in range(a + 2, len(sig) + 1):
                if w == "".join(ws[i][0] for i in sig[a:z]):
                    return set(range(sig[a], sig[z - 1] + 1)), INITIALS
    if len(w) >= 5:
        fz = {i for i, x in enumerate(ws) if lev1(w, x) or lev1(sw, stem(x))}
        if fz:
            return fz, FUZZY
    return None


# ---- the deck's tags ----

class Tree:
    """The deck's tags, every level of them (a card's tag a::b::c is a, a::b
    and a::b::c): names, as written, keyed lowercased; cards(path) counts
    what's under one. Question tags (a last part of digits), leech, marked
    and Due Crew's own plan tags aren't topics.

    What the deck says of itself: its resources (a #part under its root,
    "#M&M", said "m&m" or "mice and men", or "charts" for every #Charts…)
    and its short names ("(AKI)" after Acute Kidney Injury: aki is that,
    and only that, wherever else its letters fall)."""

    def __init__(self, names, cards=None):
        self.cards = cards or (lambda _path: set())
        self.paths = {}     # lowercased path -> as written
        for wr in names:
            parts = str(wr).split(SEP)
            for k in range(1, len(parts) + 1):
                p = SEP.join(parts[:k])
                self.paths.setdefault(p.lower(), p)
        self.parts = {}     # lowercased path -> [its parts' words]
        self.leads = {}     # lowercased path -> its parts' leading numbers ("03_Neoplasia": 3), None where there's none
        self.by_last = {}   # a last part's words, joined -> [lowercased path]
        self.by_letter = {}  # a first letter of a last part's words (or its short name) -> those last parts
        self.short = {}     # a last part's words, joined -> its short names
        self.by_lead = {}   # a last part's leading number -> those last parts ("chapter 3")
        self.means = {}     # a short name -> the names it's written beside ("aki": {"acute kidney injury"})
        self.resources = {}  # a resource's letters ("mm", "chartsmicro") -> its parts, lowercased ("#m&m")
        self.qnums = set()   # the question numbers its tags end in (QBank QIDs: "10234", zeros off the front)
        for low, wr in self.paths.items():
            parts = wr.split(SEP)
            if len(parts) > 1 and parts[-1][:1] in "#^":
                key_r = re.sub(r"[^a-z0-9]", "", parts[-1].lower())
                if len(key_r) >= 2:
                    self.resources.setdefault(key_r, set()).add(parts[-1].lower())
            last = parts[-1]
            if last.isdigit() and 3 <= len(last) <= 9:
                self.qnums.add(last.lstrip("0") or "0")
            if not part_words(last) or last.isdigit() or low in ("leech", "marked") or low.startswith("duecrew"):
                continue
            self.parts[low] = [part_words(x) for x in parts]
            self.leads[low] = [_lead(x) for x in parts]
            key = " ".join(self.parts[low][-1])
            if self.leads[low][-1] is not None:
                self.by_lead.setdefault(self.leads[low][-1], set()).add(key)
            sh = abbrs(last)
            if key not in self.by_last:
                for x in self.parts[low][-1]:
                    self.by_letter.setdefault(x[0], set()).add(key)
            for x in sh:
                self.short.setdefault(key, set()).add(x)
                self.by_letter.setdefault(x[0], set()).add(key)
                tail = [y for y in self.parts[low][-1]]
                # the words it stands for: the run at the name's end whose initials are it, else the name
                for st in range(len(tail)):
                    if initials(tail[st:]) == x:
                        self.means.setdefault(x, set()).add(" ".join(stem(y) for y in tail[st:]))
                        break
                else:
                    self.means.setdefault(x, set()).add(" ".join(stem(y) for y in tail))
            self.by_last.setdefault(key, []).append(low)
        self._hit = {}

    def _hits(self, w, ws_key, ws, short=()):
        k = (w, ws_key)
        if k not in self._hit:
            self._hit[k] = cover(w, ws, short)
        return self._hit[k]

    def resource_named(self, toks):
        """The resource a run of typed words names, from its first: (how many
        words, {its parts}) or None. Its letters whole ("m&m", "quick ref",
        "charts micro"), the run's initials ("mice and men"), or one
        word that begins a family of them ("charts")."""
        for n in range(min(4, len(toks)), 0, -1):
            run = toks[:n]
            joined = re.sub(r"[^a-z0-9]", "", "".join(run))
            if not joined:
                continue
            if joined in self.resources:
                return n, set(self.resources[joined])
            if n >= 3 and run[0] not in _SMALL and run[-1] not in _SMALL and any(x in ("and", "&", "of", "n") for x in run[1:-1]):
                ini = initials(run)  # "mice and men" is M&M; "beta blockers" is a topic, not a resource
                if len(ini) >= 2 and ini in self.resources:
                    return n, set(self.resources[ini])
            if n == 1 and len(joined) >= 5:
                fam = [k for k in self.resources if k.startswith(joined)]
                if len(fam) >= 2:
                    return 1, set().union(*(self.resources[k] for k in fam))
        return None

    def resource_group(self, parts):
        """A resource said alone: a chip a resource ("charts": each of them), every tag that ends at it."""
        out = []
        for part in sorted(parts):
            lows = [low for low in self.paths if low.split(SEP)[-1] == part and SEP in low]
            if not lows:
                continue
            cards = set()
            for x in lows:
                cards |= set(self.cards(x))
            name = spaced(pretty(self.paths[lows[0]].split(SEP)[-1]))
            out.append({"key": "res:" + part, "name": name, "tags": sorted(self.paths[x] for x in lows), "named": True,
                        "tier": 3, "cards": len(cards)})
        return sorted(out, key=lambda g: -g["cards"])

    def groups(self, words, within=None):
        """A topic's words -> [group]: {key, name, tags (as written), named
        (the words name it whole), tier (how well: 3 the words or the deck's
        own short name, 2 its name begins with them, 1 a letter off, 0 only
        offered), cards}, the best first, then the most cards. One group a
        name: every tag whose last part is called that. within: a resource's
        parts, the tags kept to the ones under it."""
        words = [w for w in words if w]
        if not words:
            return []
        found = {}
        keys = set()
        numbered = any(w in FILLER for w in words)  # "chapter 3", "section 4": a part's own number says it
        for w in words:  # every rule but a one-letter-off at the first letter keeps it: the parts worth a look
            keys |= self.by_letter.get(w[0], set())
            if numbered and w.isdigit():
                keys |= self.by_lead.get(int(w), set())
        for last_key in sorted(keys):
            lows = self.by_last[last_key]
            last_ws = last_key.split()
            short = self.short.get(last_key, ())
            if not any(self._hits(w, last_key, last_ws, short) for w in words) and not (
                    numbered and any(w.isdigit() and last_key in self.by_lead.get(int(w), ()) for w in words)):
                continue
            for low in lows:
                if within is not None and not any(x in within for x in low.split(SEP)):
                    continue
                ps = self.parts[low]
                said, hows, ctx, lead = set(), set(), 0, None
                ok = True
                for w in words:
                    on_last = self._hits(w, last_key, last_ws, short)
                    if on_last:
                        said |= on_last[0]
                        hows.add(on_last[1])
                        continue
                    if numbered and w.isdigit() and (self.leads.get(low) or [None])[-1] == int(w):
                        said |= set(range(len(last_ws)))  # "chapter 3": the part numbered 3 is it
                        hows.add(SAME)
                        lead = len(ps)
                        continue
                    if numbered and w.isdigit() and int(w) in (self.leads.get(low) or ()):
                        ctx += 1
                        continue  # in a part numbered 3
                    if w in FILLER:
                        continue
                    if not any(self._hits(w, " ".join(p), p) for p in ps[:-1]):
                        ok = False
                        break
                    ctx += 1
                if not ok or not said:
                    continue
                key = " ".join(stem(x) for x in last_ws)
                g = found.setdefault(key, {"key": key, "name": pretty(self.paths[low].split(SEP)[-1]),
                                           "lows": [], "tier": 0, "lead": None, "num": False})
                g["lows"].append(low)
                if lead is not None:
                    g["lead"] = min(g["lead"] or 99, lead)
                g["num"] = g["num"] or any(w.isdigit() for w in words)
                need = {i for i, x in enumerate(last_ws) if x not in GENERIC} or set(range(len(last_ws)))
                tier = 0
                if need <= said:
                    tier = 1 if FUZZY in hows else 2 if (PREFIX in hows and len(need) == 1 and SAME not in hows
                                                          and ABBR not in hows) else 3  # "thyroid" isn't thyroiditis
                    if INITIALS in hows:
                        # initials name it when the deck doesn't write those letters beside another name,
                        # and two letters alone ("mi") only when it writes them beside this one
                        ini = [w for w in words if (self._hits(w, last_key, last_ws, short) or (0, ""))[1] == INITIALS]
                        means = set().union(*(self.means.get(w, set()) for w in ini))
                        if means:
                            tier = 3 if key in means else 0
                        elif len(words) == 1 and len(ini[0]) == 2:
                            tier = 0
                elif not ctx and min(said) == 0 and said == set(range(len(said))) and FUZZY not in hows:
                    tier = 2  # its name begins with the words, all of them: about them
                g["tier"] = max(g["tier"], tier)
        # "chapter 3": the shallowest part numbered 3 (a chapter, not its third section, nor a "Part 3")
        tops = [g["lead"] for g in found.values() if g["lead"] is not None and g["tier"] == 3]
        if tops:
            top = min(tops)
            for g in found.values():
                if g["tier"] == 3 and g["num"] and (g["lead"] or 99) > top:
                    g["tier"] = 0
        # a name that's another's initials ("AKI") is that one
        keys = list(found)
        for a in keys:
            for b in keys:
                if a == b or a not in found or b not in found or " " not in b:
                    continue
                if a.replace(" ", "") in (initials(b.split()), stem(initials(b.split()))) and a.replace(" ", "") in self.means \
                        and b in self.means[a.replace(" ", "")]:
                    found[b]["lows"] += found[a]["lows"]
                    found[b]["tier"] = max(found[b]["tier"], found[a]["tier"])
                    del found[a]
        out = []
        for g in found.values():
            lows = sorted(set(g["lows"]))
            lows = [x for x in lows if not any(x != y and x.startswith(y + SEP) for y in lows)]  # a parent covers its children
            cards = set()
            for x in lows:
                cards |= set(self.cards(x))
            out.append({"key": g["key"], "name": g["name"], "tags": [self.paths[x] for x in lows],
                        "named": g["tier"] == 3, "tier": g["tier"], "cards": len(cards)})
        out.sort(key=lambda g: (-g["tier"], -g["cards"], g["name"].lower()))
        return out


def ticks(gs):
    """Which of a topic's chips are ticked (Sam: only what you named): the
    best tier there is, 3 (the words name it) or else 2 (its name begins
    with them, or a one-word name the word begins: the big ones, a quarter
    of the biggest's cards or more) or else 1 (a letter off); none when
    there's only what's offered ("mi" could be several: they're there to tap)."""
    best = max((g["tier"] for g in gs), default=0)
    top = max((g["cards"] for g in gs if g["tier"] == best), default=0)
    return [g["tier"] == best and best > 0 and (best != 2 or 4 * g["cards"] >= top) for g in gs]


# ---- days ----

def _add(today, n):
    return today + datetime.timedelta(days=n)


def find_day(low, today):
    """The first day the words say, and the words that said it: (date, words,
    weekend) or None. Today, tomorrow, this weekend, in 3 days, in 2 weeks,
    (next) Friday, Friday's, Dec 12, 12 December, 12/12 (month first)."""
    m = re.search(r"\btoday\b", low)
    if m:
        return today, m.group(0), False
    m = re.search(r"\btomorrow\b", low)
    if m:
        return _add(today, 1), m.group(0), False
    m = re.search(r"\b(?:this )?weekend\b", low)
    if m:
        return _add(today, (5 - today.weekday()) % 7), m.group(0), True
    m = re.search(r"\bin (\d{1,3}) (days?|weeks?)\b", low)
    if m:
        return _add(today, int(m.group(1)) * (7 if m.group(2)[0] == "w" else 1)), m.group(0), False
    m = re.search(r"\b(next )?(mon|tue|wed|thu|fri|sat|sun)(?:day|sday|nesday|rsday|urday|s|rs)?(?:'s)?\b", low)
    if m:
        n = (_DOWS.index(m.group(2)) - today.weekday()) % 7 or 7
        if m.group(1):
            n += 7
        return _add(today, n), m.group(0), False
    m = (re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.? (\d{1,2})(?:st|nd|rd|th)?\b", low)
         or re.search(r"\b(\d{1,2})(?:st|nd|rd|th)? (?:of )?(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b", low))
    if m:
        a, b = m.group(1), m.group(2)
        mon, day = (_MONS[a], int(b)) if not a.isdigit() else (_MONS[b], int(a))
        return _dated(today, mon, day, m.group(0))
    m = re.search(r"\b(\d{1,2})/(\d{1,2})\b", low)
    if m:
        return _dated(today, int(m.group(1)), int(m.group(2)), m.group(0))
    return None


def _dated(today, mon, day, said):
    for year in (today.year, today.year + 1):
        try:
            d = datetime.date(year, mon, day)
        except ValueError:
            return None
        if d >= today:
            return d, said, False
    return None


# ---- statements: what's coming up ----

def statements(low, today, quiz_known=False):
    """(acts, the words left): a quiz or test (a date on a plan), an exam far
    off (Settings' exam), away (my away spell), push my plan back N days,
    pause my plan. Each act: {k, ...}, its days as "YYYY-MM-DD".
    quiz_known: the words named a quiz a plan has (plan_words), not a new one."""
    acts = []
    kind = None if quiz_known else next((k for k in _KINDS if re.search(r"\b" + k + r"s?\b", low)), None)
    day = find_day(low, today) if kind else None
    if kind and day:
        d, said, _weekend = day
        far = (d - today).days >= SOON and kind in ("exam", "final", "shelf", "shelf exam")
        before = re.search(r"\b([a-z][a-z0-9']*) " + kind + r"s?\b", low)
        word = before.group(1) if before else ""
        lead = word if word in _NAME_ONLY - {"my", "our", "a", "an", "the"} else ""
        topic = word if (word and not lead and word not in STOP and word not in _NAME_ONLY
                         and not find_day(word.replace("'s", ""), today)) else ""
        name = " ".join(x for x in (lead or topic, kind) if x)
        acts.append({"k": "exam", "day": d.isoformat()} if far
                    else {"k": "event", "day": d.isoformat(), "name": name[:1].upper() + name[1:], "topic": topic})
        if topic:
            low = re.sub(r"\b" + re.escape(topic) + r"(?= " + re.escape(kind) + r")", " ", low, count=1)
        low = low.replace(said, " ")
        low = re.sub(r"\b(?:i have |i've got |i got |got |there'?s |there is |my |our )?(?:a |an |the )?"
                     + (re.escape(lead) + " " if lead else "") + re.escape(kind) + r"s?\b", " ", low)
        low = re.sub(r"\b(?:on|this|is|by|due|coming up)\b", " ", low)
    m = re.search(r"\b(?:(?:i'?m |i am |i'?ll be |i will be |gonna be |going to be )(?:away|off|out)|away|"
                  r"travel?ling|on vacation|on holiday|out of town)\b", low)
    if m:
        day = find_day(low, today)
        if day:
            d, said, weekend = day
            start = d if weekend else _add(today, 1)
            end = _add(d, 1) if weekend else d
            start, end = min(start, end), max(start, end)
            low = low.replace(said, " ")
        else:
            start, end = _add(today, 1), _add(today, 3)
        acts.append({"k": "away", "from": start.isoformat(), "to": end.isoformat()})
        low = low.replace(m.group(0), " ")
        low = re.sub(r"\b(?:till|until|through|thru|to|from)\b", " ", low)
    m = re.search(r"\b(?:push|slide|move|shift)(?: back)? (?:my |the )?(?:plan|dates|days|sets)?(?: back)?(?: by)? "
                  r"(\d{1,2}) days?(?: back)?\b", low)
    if m:
        acts.append({"k": "slide", "days": int(m.group(1))})
        low = low.replace(m.group(0), " ")
    m = re.search(r"\bpause (?:my |the )?plans?\b", low)
    if m:
        acts.append({"k": "pause"})
        low = low.replace(m.group(0), " ")
    return acts, low


# ---- plan words: "tomorrow's set", "friday's quiz" ----

def plan_words(low, today, plans):
    """A date or quiz of a plan I follow, said by its day or name: (hit,
    the words left). plans: [{id, name, units: [{id, name, opens, for}],
    events: [{id, name, day}]}] (my dates). hit: {pid, name, uids,
    what: "set" | "quiz"} or None."""
    plans = list(plans or ())
    m = re.search(r"\b(today|tomorrow|mon|tue|wed|thu|fri|sat|sun)[a-z]*'?s?\s+(set|sets|lesson|date|plan|cards)\b", low)
    if m and plans:
        day = find_day(m.group(1), today)
        if day:
            iso = day[0].isoformat()
            for p in plans:
                us = [u for u in p.get("units") or () if str(u.get("opens") or "") == iso]
                if us:
                    return ({"pid": p["id"], "name": f"{p.get('name') or 'Plan'} · {us[0].get('name') or 'set'}",
                             "uids": [u["id"] for u in us], "what": "set"}, low.replace(m.group(0), " "))
    m = re.search(r"\b(?:for |everything for |all of )?(?:the |my )?([a-z0-9']+)?\s*(quiz|test|exam|midterm|final)\b", low)
    if m and plans:
        word = (m.group(1) or "").replace("'s", "")
        day = find_day(word, today) if word else None
        said_day = find_day(low.replace(m.group(0), " "), today)  # "heme quiz on friday": a quiz on Friday, not Tuesday's
        for p in plans:
            for e in p.get("events") or ():
                same = (day and str(e.get("day") or "") == day[0].isoformat()) or (
                    word and word not in STOP and len(word) >= 3 and word in str(e.get("name") or "").lower())
                if said_day and said_day[0].isoformat() != str(e.get("day") or ""):
                    continue
                if same and str(e.get("day") or "") >= today.isoformat():
                    uids = [u["id"] for u in p.get("units") or () if u.get("for") == e.get("id")]
                    if uids:
                        low = low.replace(m.group(0), " ")
                        when = find_day(low, today)
                        if when and when[0].isoformat() == str(e.get("day") or ""):
                            low = re.sub(r"\b(?:on |this |next )?" + re.escape(when[1]), " ", low)
                        return ({"pid": p["id"], "name": str(e.get("name") or "the quiz"), "uids": uids, "what": "quiz",
                                 "eid": e.get("id")}, low)
    return None, low


# ---- a deck by its name ----

def deck_named(low, decks):
    """A deck said by its name ("in heme lectures"): (did, the words left),
    the longest name first; a subdeck by its last part when that's unique."""
    names = []
    leaf_count = {}
    for did, name in decks or ():
        leaf = str(name).split(SEP)[-1].lower()
        leaf_count[leaf] = leaf_count.get(leaf, 0) + 1
    for did, name in decks or ():
        full = " ".join(str(name).lower().replace(SEP, " ").replace("_", " ").split())
        names.append((full, did))
        leaf = " ".join(str(name).split(SEP)[-1].lower().replace("_", " ").split())
        if leaf_count.get(str(name).split(SEP)[-1].lower()) == 1 and leaf != full:
            names.append((leaf, did))
    for said, did in sorted(names, key=lambda x: -len(x[0])):
        if len(said) < 4:
            continue
        m = re.search(r"\b(?:in |from )(?:the |my )?" + re.escape(said) + r"(?: deck)?\b", low)
        if not m and " " in said:
            m = re.search(r"\b(?:the |my )?" + re.escape(said) + r"(?: deck)?\b", low)
        if m:
            return did, low.replace(m.group(0), " ")
    return None, low


# ---- reading it all ----

def _resources(low, tree):
    """(the words left, {resource parts}): the deck's resources the words
    say ("m&m", "quick ref", "mice and men", "charts"), taken out."""
    found = set()
    if tree is None or not tree.resources:
        return low, found
    toks = re.findall(r"[a-z0-9][a-z0-9&'+.]*", low)
    i = 0
    while i < len(toks):
        got = tree.resource_named(toks[i:]) if toks[i] not in STOP and not toks[i].isdigit() else None
        if got:
            n, parts = got
            rx = r"(?<![a-z0-9])" + r"[^a-z0-9]+".join(re.escape(x) for x in toks[i:i + n]) + r"(?![a-z0-9&])"
            low = re.sub(rx, " ", low, count=1)
            found |= parts
            i += n
        else:
            i += 1
    return low, found


def _words(s):
    """A topic's words: the little ones off, a number of three digits or more off (a short one stays: "type 2")."""
    ws = [w.strip("'") for w in re.split(r"[^a-z0-9']+", s)
          if w and w not in STOP and not (w.isdigit() and len(w) > 2) and w.strip("'")]
    return [_ROMANS.get(w, w) if i and w != "i" else w for i, w in enumerate(ws)]


BOTH = "\u2229"  # a topic's cards that are another's too: "both A and B", A AND B, A with B


def _both(low):
    """"both A, B and C": A ∩ B ∩ C, its commas and ands to the next or, ; or
    the end ("…, or renal" is beside them; "m&m" is a name, not an and)."""
    def one(m):
        return " " + re.sub(r"\band\b|,|(?<![a-z0-9])&(?![a-z0-9])|\+", f" {BOTH} ", m.group(1)) + " "
    return re.sub(r"\bboth\b\s+(.*?)(?=;|\bor\b|$)", one, low)


def _segments(low, tree, within, amp=True):
    """A topic's words, each its own: (segs, terms). "and", "or", commas
    (and &, + and / when amp) put another topic beside it, each one's cards;
    ∩ puts one inside it, the cards in both, as does "with" when each side
    names a topic and no tag says the whole ("heart failure with pharm"; a
    tag "Diabetes with complications" stays one). terms: [[seg]], a term's
    segs the ones it takes the cards in all of."""
    rx = r"\band\b|,|\bor\b|&|\+|/|;" if amp else r"\band\b|,|\bor\b|\+|/|;"
    segs, terms = [], []
    for term in re.split(rx, low):
        fs = []
        for f in term.split(BOTH):
            fs += _with(f, tree, within)
        if fs:
            terms.append(list(range(len(segs), len(segs) + len(fs))))
            segs += fs
    return segs, terms


def _with(f, tree, within):
    """One part's words, or two when "with" joins two topics: [[words]]."""
    ws = _words(f)
    if not ws:
        return []
    m = re.search(r"\bwith\b", f)
    if not m or tree is None:
        return [ws]
    a, b = _words(f[:m.start()]), f[m.end():]
    if not a or not _words(b):
        return [ws]
    named = lambda words: any(g["tier"] >= 2 for g in tree.groups(words, within=within or None))  # noqa: E731
    whole = a + ["with"] + _words(b)  # "Diabetes_with_Complications" has its with
    if any(g["tier"] == 3 for g in tree.groups(whole, within=within or None)):
        return [whole]  # a tag says it whole, with and all
    if any(g["tier"] == 3 for g in tree.groups(ws, within=within or None)) or not named(a):
        return [ws]  # a tag says it whole, or the first side isn't a topic: as said
    rest = _with(b, tree, within)
    return [a] + rest if rest and named(rest[0]) else [ws]


def read(text, tree, today, decks=(), plans=()):
    """What a box says. {kind, groups, neg, filters, limit, deck, plan, text,
    qids, ids, search, acts, lines}:
    kind: "empty"; "plantext" (dates as the Text tab writes them: lines,
    the text itself); "search" (Anki's own words, as pasted); "ids" (QIDs,
    the short numbers; note or card ids, the long); "do" (only what's
    coming up: acts); else "words".
    groups: each topic's chips, [{key, name, tags, named, cards, on, seg}]
    (on: ticked; seg: which topic the words were); neg: the ones left out;
    filters: [{k, n?}]; limit: how many, or None; deck: a deck said by
    name; plan: plan_words' hit; text: words no tag has."""
    out = {"kind": "words", "groups": [], "neg": [], "filters": [], "limit": None, "deck": None, "plan": None,
           "text": "", "qids": [], "ids": [], "search": "", "acts": [], "lines": [], "raw": str(text or ""),
           "res": [], "bank": None, "terms": [], "seg_words": []}
    t = str(text or "").strip()
    if not t:
        out["kind"] = "empty"
        return out
    lines = [x for x in t.split("\n") if x.strip()][:LINES_MAX]
    dated = [x for x in lines if _PLAN_LINE.match(x)]
    if dated and 2 * len(dated) >= len(lines):
        out["kind"], out["lines"] = "plantext", lines
        return out
    if _SEARCHY.search(t):
        out["kind"], out["search"] = "search", " ".join(t.split())
        return out
    longs, shorts = _LONG.findall(t), _SHORT.findall(t)
    # Sam: "AND statements and OR statements on tags": AND in capitals, as Anki writes it, is both (∩);
    # "and" and "or" in words are another topic, each one's cards
    t = re.sub(r"(?<![A-Za-z0-9])AND(?![A-Za-z0-9])", " \u2229 ", t)
    low = " " + re.sub(r"[\u2018\u2019\u02bc]", "'", t.lower()) + " "
    low = re.sub(r"\s+", " ", low)
    if longs or shorts:
        rest, said = _resources(_SHORT.sub(" ", _LONG.sub(" ", low)), tree)
        # round 2 (Sam: "this is replacing QBank QID search"): a block's results pasted the way its bank
        # copies them ("Block 3 · 12 Oct / Missed: 10234, 10911 · 65%") are QIDs when two or more of the
        # numbers, and a third of them, are this deck's questions: the words around them aren't a topic
        nums = {x.lstrip("0") or "0" for x in shorts}
        hits = len(nums & tree.qnums) if tree is not None and not longs else 0
        if _IDS_ONLY.match(rest) or (hits >= 2 and 3 * hits >= len(nums)):  # QIDs (with their bank's name, "qbank 2345"), or ids
            out["kind"] = "ids"
            out["ids"] = list(dict.fromkeys(longs))
            out["qids"] = list(dict.fromkeys(x.lstrip("0") or "0" for x in shorts))
            out["bank"] = sorted(said)[0] if said else None
            return out
    hit, low = plan_words(low, today, plans)
    out["plan"] = hit
    acts, low = statements(low, today, quiz_known=bool(hit and hit.get("what") == "quiz"))
    # filters before the number: "missed in the last 3 days" isn't 3 of anything
    fs = []
    for k, rx, _label, _q in FILTERS:
        m = _FILT[k][0].search(low)
        if not m:
            continue
        if k == "seen" and re.search(r"\b(?:not|haven'?t|never) seen\b", low):
            continue
        fs.append({"k": k, "n": int(m.group(1))} if "N" in k else {"k": k})
        low = low[:m.start()] + " " + low[m.end():]
    have = {f["k"] for f in fs}
    if have & {"m1", "mN"}:
        fs = [f for f in fs if f["k"] != "m7"]
    if have & {"tom", "dN"}:
        fs = [f for f in fs if f["k"] != "due"]
    out["filters"] = fs
    m = re.search(r"(?<![\w:/])(\d{1,4})\s+(?!days?\b|weeks?\b|months?\b|hours?\b|minutes?\b)(?=[a-z])", low)
    if m and not _words(low[:m.start()]):  # "10 new platelets", "give me 10": how many; "type 2 diabetes" isn't
        n = int(m.group(1))
        if 0 < n <= LIMIT_MAX:
            out["limit"] = n
        low = low[:m.start()] + " " + low[m.end():]
    did, low = deck_named(low, decks)
    out["deck"] = did
    neg = ""
    m = re.search(r"\b(?:but not|except(?: for)?|without|excluding|not)\b(.*)$", low)
    if m:
        neg, low = m.group(1), low[:m.start()]
    low = _both(low)  # "both heart failure and pharm": the cards in both
    said_low = low
    low, within = _resources(low, tree)  # "m&m heart failure": heart failure, in that resource
    segs, terms = _segments(low, tree, within)
    if within and segs and tree is not None and not any(tree.groups(ws, within=within) for ws in segs):
        low, within = said_low, set()  # "pathbook chapter 3": a tag called that, wherever it is
        segs, terms = _segments(low, tree, within, amp=False)
    out["res"] = sorted(within)
    out["terms"] = terms  # [[seg]]: each term's topics' cards in all of them; the terms' together
    out["seg_words"] = [" ".join(ws) for ws in segs]
    if not segs and within and tree is not None:
        gs = tree.resource_group(within)
        out["groups"] += [dict(g, seg=0, on=True) for g in gs]
    text_words = []
    for i, ws in enumerate(segs):
        gs = tree.groups(ws, within=within or None)[:GROUPS_MAX] if tree is not None else []
        if not gs:
            if not acts and not hit:
                text_words += ws  # words no tag has: the cards' text (not beside a statement or a plan's set)
            continue
        for g, on in zip(gs, ticks(gs)):
            out["groups"].append(dict(g, seg=i, on=on))
    ev = next((a for a in acts if a["k"] == "event" and a.get("topic")), None)
    if ev and not out["groups"] and tree is not None:  # "heme quiz friday": its name is the topic, when nothing else is
        gs = tree.groups([ev["topic"]])[:GROUPS_MAX]
        for g, on in zip(gs, ticks(gs)):
            out["groups"].append(dict(g, seg=0, on=on))
    out["text"] = " ".join(text_words)
    nws = [ws for ws in (_words(s) for s in re.split(r"\band\b|,|\bor\b|&|\+|/|;|\bnor\b", neg)) if ws]
    for ws in nws:
        gs = tree.groups(ws) if tree is not None else []
        for g, on in zip(gs, ticks(gs)):
            if on and len(out["neg"]) < NEG_MAX:
                out["neg"].append(dict(g, on=True))
    ev = next((a for a in acts if a["k"] == "event"), None)
    if ev and any(g["on"] for g in out["groups"]):
        acts.append({"k": "before", "day": ev["day"]})  # its topics on the days before it
    out["acts"] = acts
    if acts and not (out["groups"] or out["filters"] or out["plan"] or out["text"] or out["deck"]):
        out["kind"] = "do"
    return out


def topics_said(groups, terms=None):
    """The topics named, one a typed topic: its first ticked chip's name
    ("Platelets and Anemia"); two in one term, the cards in both, "with"
    ("Heart Failure with Pharm")."""
    first = {}
    for g in groups:
        if g.get("on") and g.get("seg") not in first:
            first[g.get("seg")] = g["name"]
    names = []
    for term in terms or [[s] for s in first]:
        said = [first[s] for s in term if s in first]
        if said:
            names.append(" with ".join(said))
    if len(names) <= 2:
        return " and ".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def ticked_by_seg(r, off_groups=(), off_tags=()):
    """{seg: [tag]}: each typed topic's ticked tags (a seg with none ticked isn't in it)."""
    out = {}
    for i, g in enumerate(r.get("groups") or ()):
        on = g.get("on") if i not in set(off_groups) else not g.get("on")
        if on:
            ts = out.setdefault(g.get("seg"), [])
            ts += [t for t in g.get("tags") or () if t not in set(off_tags) and t not in ts]
    return out


def joined(r):
    """Whether any of the reading's topics are taken in both (a term of two or more)."""
    return any(len(t) > 1 for t in r.get("terms") or ())


def filter_label(f):
    k = f.get("k")
    if k not in _FILT:
        return ""
    return _FILT[k][1].format(n=f.get("n") or 0)


def filter_q(f):
    k = f.get("k")
    if k not in _FILT:
        return ""
    return _FILT[k][2].format(n=int(f.get("n") or 0))


# ---- Anki's search for it ----

def esc(x):
    """A tag or deck name inside a quoted Anki search: \\ " * _ escaped (_ and * are wildcards)."""
    return re.sub(r'([\\"*_])', r"\\\1", str(x))


def tag_q(path):
    return f'"tag:{esc(path)}"'


def deck_q(name):
    return f'"deck:{esc(name)}"'


def search(r, deck_name="", tags=(), cids=(), off=()):
    """The reading as one Anki search, inside the deck (deck_name; "" for
    every deck): what it finds (tags ticked, a plan's cards, the cards'
    text, ids, a pasted search), less the topics left out, with the
    filters. tags: the ticked tags (the window's picks; the reading's own
    when None); cids: cards found by number (QIDs, a plan's dates); off:
    filters taken off. "" when there's nothing to find."""
    parts = []
    finds = []
    if r.get("kind") == "search":
        finds.append(f"({r['search']})")
    if tags:
        finds.append("(" + " OR ".join(tag_q(t) for t in tags) + ")" if len(tags) > 1 else tag_q(tags[0]))
    if cids:
        finds.append("cid:" + ",".join(str(int(c)) for c in sorted(set(cids))))
    if r.get("kind") == "ids" and r.get("ids"):
        ids = ",".join(r["ids"])
        finds.append(f"nid:{ids}")
        finds.append(f"cid:{ids}")
    if r.get("text") and not tags:
        finds.append(" ".join('"' + esc(stem(w) if len(w) >= 5 else w) + '"' for w in r["text"].split()))
    if len(finds) > 1:
        parts.append("(" + " OR ".join(finds) + ")")
    elif finds:
        parts.append(finds[0])
    has_find = bool(finds)
    fs = [f for f in r.get("filters") or () if f.get("k") not in set(off)]
    if not has_find and not fs and not r.get("deck"):
        return ""
    if deck_name:
        parts.insert(0, deck_q(deck_name))
    for g in r.get("neg") or ():
        ts = g.get("tags") or ()
        if ts:
            parts.append("-(" + " OR ".join(tag_q(t) for t in ts) + ")" if len(ts) > 1 else "-" + tag_q(ts[0]))
    parts += [filter_q(f) for f in fs]
    return " ".join(p for p in parts if p)


def ticked_tags(r, off_groups=(), off_tags=()):
    """The tags the chips have ticked: each ticked group's (less the ones
    unticked in its list), in order, once each."""
    out = []
    for i, g in enumerate(r.get("groups") or ()):
        on = g.get("on") if i not in set(off_groups) else not g.get("on")
        if not on:
            continue
        for t in g.get("tags") or ():
            if t not in set(off_tags) and t not in out:
                out.append(t)
    return out


def filters_q(filters, off=()):
    """The filters as Anki's search terms, one string ("" for none)."""
    return " ".join(q for q in (filter_q(f) for f in filters or () if f.get("k") not in set(off)) if q)


def text_q(text):
    """Words no tag has, as Anki's search of the cards' text: each word, its plural off when it's long."""
    return " ".join('"' + esc(stem(w) if len(w) >= 5 else w) + '"' for w in str(text or "").split())


# ---- a tag in its chip's list: its resource first ----

def root_name(part):
    """A deck's root as it's said: its version and a short prefix of
    capitals off, a number set apart ("Big_Step1_v12" is Big Step 1,
    "XY_Step2_v12" Step 2)."""
    words = [w for w in pretty(part).split() if not re.fullmatch(r"v\d+", w, re.I)]
    if len(words) > 1 and re.fullmatch(r"[A-Z]{2,3}", words[0]):
        words = words[1:]
    return re.sub(r"(?<=[A-Za-z])(?=\d)", " ", " ".join(words)) or pretty(part)


def tag_row(path, roots=False):
    """A tag as its topic's tree shows it: {res, path}: where it's from (the
    first #part under its root, "M&M", else its root, "Heme lectures"; none
    for a one-part tag) and every part after that to the last one (Sam: "the
    tag tree to go all the way to the last tag"). roots: the topic's tags are
    under more than one root, so the root says which ("Step 1 › Cardio ›
    Heart Failure")."""
    parts = str(path).split(SEP)
    at = next((i for i, x in enumerate(parts) if i > 0 and x[:1] in "#^"), 0 if len(parts) > 1 else None)
    res = spaced(pretty(parts[at])) if at is not None else ""
    shown = [pretty(x) for x in parts[(at + 1) if at is not None else 0:]]
    if roots and at:
        shown = [root_name(parts[0])] + shown
    return {"res": res, "path": " \u203a ".join(shown)}


def tag_list(rows, cards=None):
    """A topic's tags, by where they're from: [{res, n, tags: [row]}]. rows:
    [{t, res, path, n, on}]. A resource's n is its cards once each (cards: a
    tag's cards; a child tag's are its parent's too, and a note can carry a
    tag in both halves of a deck), else its tags' added. Its tags in their
    own order, so a child sits right under its parent; the resource with
    most cards first. Two that would read the same say their tags as written."""
    by = {}
    for x in rows:
        by.setdefault(x["res"], []).append(dict(x))
    out = []
    for k, v in by.items():
        said = {}
        for x in v:
            said.setdefault(x["path"].lower(), []).append(x)
        for xs in said.values():
            if len(xs) > 1:
                for x in xs:
                    x["path"] = " \u203a ".join(y.replace("_", " ") for y in str(x["t"]).split(SEP)[1:]) or x["path"]
        if cards is not None:
            got = set()
            for x in v:
                got |= set(cards(x["t"]))
            n = len(got)
        else:
            n = sum(x["n"] for x in v)
        out.append({"res": k, "n": n, "tags": sorted(v, key=lambda x: str(x["t"]).lower())})
    return sorted(out, key=lambda g: (-g["n"], g["res"].lower()))


# ---- how long, at my pace ----

PACE = {"new_s": 30, "rev_s": 10, "day_min": 60, "known": False}  # before there's a log to read


def pace_from(new_ms, new_cards, rev_ms, rev_n, days):
    """My pace from my answer log these weeks (magic_flow.Ops.pace): a new
    card's first-day seconds (its learning answers' time over the cards),
    a review's seconds, and my usual day's minutes (the middle of the days I
    studied). PACE where there's too little to go on."""
    out = dict(PACE)
    if new_cards >= 10:
        out["new_s"] = max(8, min(240, new_ms / 1000 / new_cards))
    if rev_n >= 20:
        out["rev_s"] = max(3, min(90, rev_ms / 1000 / rev_n))
    mins = sorted(m for m in (days or ()) if m > 0)
    if len(mins) >= 3:
        out["day_min"] = max(10, mins[len(mins) // 2])
        out["known"] = True
    return out


def took(new, rev, pace):
    """Seconds for `new` new cards and `rev` reviews at this pace."""
    return new * pace["new_s"] + rev * pace["rev_s"]


def says_time(sec):
    """"about 2 min", "about 45 min", "about 3 h 40 min"."""
    m = int(round(sec / 60))
    if m < 1:
        return "under a minute"
    if m < 60:
        return f"about {m} min"
    m = int(round(m / 5) * 5)
    h, r = divmod(m, 60)
    return f"about {h} h" + (f" {r} min" if r else "")


def days_for(sec, pace, most=14):
    """How many of my usual days it takes: 1 at least."""
    return max(1, min(most, -(-int(sec) // int(pace["day_min"] * 60))))


def spaced(name):
    """A resource's name as it's said: "QuickRef" is Quick Ref, "ChartsMicro" Charts Micro (M&M stays)."""
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(name))


# ---- the how-to (Sam: "awesome and comprehensive and clear"): the Decks screen's first-time card and the window's ? ----

HOWTO = {
    "lede": "Say what you want to study, or what\u2019s coming up, the way you\u2019d say it. It reads your deck\u2019s "
            "own tags, on this computer; nothing you type leaves it.",
    "parts": [
        {"k": "topic", "t": "A topic", "w": "Its name, its initials or a typo: every tag that says it, as one topic. "
                                            "\u201cand\u201d or \u201cor\u201d adds another.",
         "try": ["heart failure", "hf drugs"]},
        {"k": "res", "t": "A resource", "w": "Its name or its letters, alone or with a topic; a chapter by its number.",
         "try": []},
        {"k": "filter", "t": "A filter", "w": "New, seen, due, due tomorrow, missed today or this week, learning, "
                                              "suspended, leeches, flagged. Or tap them under the box.",
         "try": ["anemia I missed this week"]},
        {"k": "limit", "t": "Both, how many, leaving some out", "w": "\u201cboth \u2026 and \u2026\u201d, \u201cwith\u201d "
                                                                      "or AND: only the cards in both. A number first takes "
                                                                      "that many, in the deck\u2019s order; \u201cbut not\u201d, "
                                                                      "\u201cexcept\u201d or \u201cwithout\u201d leaves one out.",
         "try": ["both heart failure and pharm", "10 new platelets", "platelets but not itp"]},
        {"k": "ids", "t": "QBank QIDs, IDs, a search", "w": "Paste a block\u2019s question IDs (its bank\u2019s name "
                                                             "first if you have two): their cards, and the topics they\u2019re "
                                                             "in. Note or card IDs, or an Anki search, too.",
         "try": ["10234 10911 11002"], "label": ["a block\u2019s QIDs"]},
        {"k": "coming", "t": "What\u2019s coming up", "w": "A quiz goes on a plan, its topics on the days before it. "
                                                            "An exam, or being away, goes in Settings.",
         "try": ["quiz friday on anemia", "I\u2019m away till monday"]},
        {"k": "lines", "t": "Plan lines", "w": "Lines from our prompts or the Text tab become a plan\u2019s dates and events.",
         "code": "2026-11-12 | Anemia | tag:\u2026"},
        {"k": "plan", "t": "Your plan\u2019s words", "w": "\u201ctomorrow\u2019s set\u201d, \u201cthe heme quiz\u201d: "
                                                          "the cards your plan has for them.", "try": ["tomorrow\u2019s set"]},
    ],
    "then": ["Study now: the new and due ones (all of them for a filter or QIDs), suspended ones too; leeches stay out.",
             "Schedule ahead: a date on My plan for each day you pick.",
             "Make a new filtered deck, named by you.",
             "Unsuspend them.",
             "Add them to a filtered deck you have, or Browse them."],
}
TRIED = ("topic", "res", "filter", "limit", "ids")  # the parts whose tries need the deck's tags: the window reads them first


def howto(kbd, tries=None):
    """The how-to's words, with this computer's key for Magic search. tries:
    {part's k: [what to try]}, the deck's own (examples) or what reading
    them found (the window drops a try that ticks nothing)."""
    parts = []
    for x in HOWTO["parts"]:
        x = dict(x)
        if tries and x["k"] in tries:
            x["try"] = list(tries[x["k"]])
            if x["k"] != "ids":  # a block's QIDs keeps its words; the numbers are the deck's own
                x.pop("label", None)
        parts.append(x)
    return dict(HOWTO, parts=parts,
                foot=f"In the You box\u2019s head, and {kbd} from any screen. ? in the window brings this back.")


def examples(names):
    """The how-to's tries from the deck's own tags, {res, ids} (either may be
    missing). res: the #part under a root with the most tags (not a QBank's,
    whose tags end in a number), said as its name, with its biggest part
    after it ("quick ref cardiovascular"). ids: three of the questions of
    the bank with the most, spread over its numbers ("1151 5023 11514")."""
    seen = {}  # lowercased path to the #part -> [its name, tags, ones ending in a number, {next part: tags}]
    qs = {}    # a bank's #part, lowercased -> its question numbers
    for wr in names:
        parts = str(wr).split(SEP)
        at = next((i for i, x in enumerate(parts) if i > 0 and x[:1] == "#"), None)
        if at is None:
            continue
        r = seen.setdefault(SEP.join(parts[:at + 1]).lower(), [parts[at], 0, 0, {}])
        r[1] += 1
        r[2] += parts[-1].isdigit()
        if parts[-1].isdigit() and 3 <= len(parts[-1]) <= 9:
            qs.setdefault(parts[at].lower(), set()).add(int(parts[-1]))
        if len(parts) > at + 1:
            r[3][parts[at + 1]] = r[3].get(parts[at + 1], 0) + 1
    out = {}
    if qs:
        nums = sorted(max(qs.values(), key=len))
        if len(nums) >= 3:
            out["ids"] = [" ".join(str(nums[len(nums) * k // 4]) for k in (1, 2, 3))]
    for _k, (part, n, digits, kids) in sorted(seen.items(), key=lambda kv: (-kv[1][1], kv[0])):
        said = spaced(pretty(part)).lower()
        if n < 3 or digits * 2 > n or not re.fullmatch(r"[a-z0-9&' ]{2,30}", said):
            continue
        for kid, _m in sorted(kids.items(), key=lambda kv: (-kv[1], kv[0].lower())):
            w = pretty(kid).lower()
            if re.fullmatch(r"[a-z]{3,}(?: [a-z]{2,}){0,2}", w) and w.split()[0] not in FILLER:
                out["res"] = [f"{said} {w}"]
                return out
    return out


# ---- the days a set goes on ----

def split(cids, days):
    """Cards spread over picked days, in order, the first days a card more
    when they don't divide: [(day, [cid])]."""
    cids, days = list(cids), sorted(set(days))
    if not days:
        return []
    k, extra = divmod(len(cids), len(days))
    out, at = [], 0
    for i, d in enumerate(days):
        n = k + (1 if i < extra else 0)
        out.append((d, cids[at:at + n]))
        at += n
    return out


def day_name(name, i, n):
    """A day's set's name: the topics', with "1 of 3" when the set is split."""
    base = " ".join(str(name or "Cards").split())[:56] or "Cards"
    return f"{base} {i + 1} of {n}" if n > 1 else base


def words_span(a, b):
    """"Thu 5 – Mon 9 Nov", or "Thu 5 Nov" for one day."""
    da, db = datetime.date.fromisoformat(a), datetime.date.fromisoformat(b)
    if da == db:
        return f"{da:%a} {da.day} {da:%b}"
    if da.month == db.month and da.year == db.year:
        return f"{da:%a} {da.day} \u2013 {db:%a} {db.day} {db:%b}"
    return f"{da:%a} {da.day} {da:%b} \u2013 {db:%a} {db.day} {db:%b}"
