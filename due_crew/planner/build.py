"""The builder's rules (site/public/builder.js), restated for Your plans
(3.9.3): pure, nothing of Anki's. Each is a twin of the builder's, named
where it's from; change one, change both (CLAUDE.md's twins).

- A date's lines to tick (Todo), the plan's lines every week (Every), a
  note for followers on a tag or a card (Remarks), notes: and cards: in a
  paste (Picks), a search's name (searchName).
- What a date's name points at in the deck (Suggest.tags).
- A date's work over its days (Work), and the reviews that brings, a
  typical card's (Reviews).
"""

import datetime
import math
import re
import unicodedata

from .. import schedule as S

# ---- Todo: a date's lines to tick by hand ----

TODO_MAX = 8                                   # plans.ts TODO_MAX
TODO_LABEL = {"watch": "Watch", "read": "Read", "do": "Do"}
TODO_TEXT = 140
_URL = re.compile(r"https://[^\s\"'<>]{1,492}")


def ok_url(v):
    """Todo.okUrl: a link starts with https://, no spaces or quotes, 500 at most."""
    return bool(_URL.fullmatch(str(v or "")))


def todo_parse(k, rest):
    """Todo.parse: "watch: lecture 14 https://…" -> {k, t, url}."""
    m = re.fullmatch(r"(.*?)\s+(https://\S+)", str(rest).strip())
    if m and ok_url(m.group(2)):
        return {"k": str(k).lower(), "t": m.group(1).strip()[:TODO_TEXT], "url": m.group(2)}
    return {"k": str(k).lower(), "t": str(rest).strip()[:TODO_TEXT]}


def todo_clean(lines):
    """Todo.clean: what a save sends, lines with words, at most TODO_MAX."""
    out = []
    for x in lines or []:
        if not isinstance(x, dict) or x.get("k") not in TODO_LABEL or not str(x.get("t") or "").strip():
            continue
        line = {"k": x["k"], "t": str(x["t"]).strip()[:TODO_TEXT]}
        if x.get("url") and ok_url(x["url"]):
            line["url"] = x["url"]
        out.append(line)
    return out[:TODO_MAX]


# ---- Every: the plan's lines every week ----

EVERY_MAX = 6                                  # plans.ts EVERY_MAX
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def every_clean(lines):
    """Every.clean: lines with words and days (Monday "0"), at most EVERY_MAX."""
    out = []
    for x in lines or []:
        if not isinstance(x, dict) or not re.fullmatch(r"[0-6]{1,7}", str(x.get("r") or "")):
            continue
        line = todo_clean([x])
        if line:
            out.append(dict(line[0], r="".join(sorted(set(x["r"])))))
    return out[:EVERY_MAX]


def every_label(r):
    """Every.label: "every day", "weekdays", "every Mon, Thu"."""
    return ("every day" if r == "0123456" else "weekdays" if r == "01234"
            else "every " + ", ".join(DAYS[int(k)] for k in str(r)))


# ---- Remarks: notes for followers on a tag or a card ----

REMARKS_MAX = 300                              # plans.ts REMARKS_MAX
REMARK_TEXT = 280


def remark_clean(s):
    """Remarks.clean: one line, no control characters."""
    s = re.sub(r"[\r\n\t]+", " ", str(s or ""))
    s = re.sub(r"[\u0000-\u001f]", "", s)
    return " ".join(s.split())


def remark_line(r):
    """Remarks.line: note | tag:PATH | words, or note | card:GUID:N | words (N from 1)."""
    if r.get("card"):
        return f"note | card:{r['card'][0]}:{int(r['card'][1]) + 1} | {r.get('text') or ''}"
    return f"note | tag:{r.get('tag')} | {r.get('text') or ''}"


def remark_take(rest):
    """Remarks.take: the part after "note |": {card: [guid, ord], text} or
    {tag, text}, {bad: True}, or None."""
    m = re.match(r"card:(\S+?):(\d+)(?:\s+\|\s*|\s{2,})(.*)$", rest, re.I | re.S)
    if m:
        n = int(m.group(2))
        return ({"card": [m.group(1), n - 1], "text": m.group(3)} if len(m.group(1)) <= 40 and 1 <= n <= 1001
                else {"bad": True})
    m = re.match(r"tag:(.+?)(?:\s*\|\s*|\s{2,})(.*)$", rest, re.I | re.S)
    return {"tag": m.group(1).strip(), "text": m.group(2)} if m else None


def remark_same(a, b):
    """Remarks.same: the same tag (any case) or the same card."""
    if a.get("card"):
        return bool(b.get("card")) and list(a["card"]) == list(b["card"])
    return bool(b.get("tag")) and str(a.get("tag")).lower() == str(b["tag"]).lower()


# ---- Picks: notes: and cards: in a paste ----

_PICK_SEG = re.compile(r"(^|\|)\s*(notes|cards):[ \t]*(.*?)[ \t]*(?=\s\|(?:\s|$)|$)", re.I)


def _guid_ok(g):
    return 1 <= len(g) <= 40


def picks_take(line):
    """Picks.take: {line: what's left, notes, cards: [[guid, ord]], bad: [tokens]}."""
    out = {"line": str(line), "notes": [], "cards": [], "bad": []}
    while True:
        m = _PICK_SEG.search(out["line"])
        if not m:
            break
        for tok in m.group(3).split():
            if m.group(2).lower() == "notes":
                (out["notes"] if _guid_ok(tok) else out["bad"]).append(tok)
                continue
            at = tok.rfind(":")
            g, n = tok[:at], tok[at + 1:]
            if at > 0 and _guid_ok(g) and n.isdigit() and 1 <= int(n) <= 1001:
                out["cards"].append([g, int(n) - 1])
            else:
                out["bad"].append(tok)
        out["line"] = f"{out['line'][:m.start()]}{m.group(1)} {out['line'][m.end():]}"
    out["notes"] = list(dict.fromkeys(out["notes"]))
    seen, cards = set(), []
    for g, o in out["cards"]:
        if (g, o) not in seen:
            seen.add((g, o))
            cards.append([g, o])
    out["cards"] = cards
    return out


def notes_text(gs):
    return "notes:" + " ".join(gs)


def cards_text(cs):
    return "cards:" + " ".join(f"{g}:{int(o) + 1}" for g, o in cs)


# ---- Tags: a tag or subdeck as an Anki search ----

def anki_search(kind, path):
    """Tags.ankiSearch: a tag or subdeck as a search to paste into Browse;
    a versioned root (…_v12) matches any version, as copies of a deck differ."""
    esc = lambda x: re.sub(r'([\\"*_])', r"\\\1", str(x))  # noqa: E731
    if kind == "deck":
        return f'"deck:{esc(path)}"'
    segs = str(path).split("::")
    first = re.sub(r"\\_v\d+$", lambda m: "\\_v*", esc(segs[0]), flags=re.I)
    return '"tag:' + "::".join([first] + [esc(x) for x in segs[1:]]) + '"'


def cut_q(tag_path, ptag_path):
    """cutQ: a tag kept to what one of the plan's own tags holds, as a search
    (plans.ts reroot reads it back)."""
    return f"{anki_search('tag', ptag_path)} {anki_search('tag', tag_path)}"


EXTRA = re.compile(r"^(extras?|bonus|supplement)$", re.I)


def is_extra(seg):
    """isExtra: a deck tag's extras, a child named Extra, Extras, Bonus or Supplement."""
    return bool(EXTRA.match(re.sub(r"[_#]", "", str(seg))))


def without_q(path, extra_kids):
    """withoutQ: the tag less its extras, "tag:X" -"tag:X::Extra"."""
    return " ".join([anki_search("tag", path)] + [f"-{anki_search('tag', k)}" for k in extra_kids])


# ---- searches ----

SEARCH_MAX = 10                                # plans.ts SEARCH_MAX: searches and cuts, a date
SEARCH_LEN = 500
IDS_MAX = 5000                                 # a date's note ids, card ids or notes, each


def _tag_word(seg):
    from .. import plans as P
    return P._word(seg)


_OR = re.compile(r"\sOR\s")


def search_name(q):
    """searchName: a search's name from its tags; two of them, as Overlap
    writes them, read "SLG 12 but not Pharm"; a tag without its extras
    "Cardio but not Extra, Bonus"; else "Search: Cardio"."""
    ws = []
    for m in re.finditer(r'(-?)"?tag:"?((?:\\.|[^\s"])+)', str(q), re.I):
        parts = [x for x in re.sub(r"\\(.)", r"\1", m.group(2)).split("::") if x.replace("*", "")]
        w = _tag_word(parts[-1]).replace("*", "") if parts else ""
        if w:
            ws.append((m.group(1), w))
    if len(ws) == 2 and not ws[0][0]:
        how = "but not" if ws[1][0] else "or" if _OR.search(str(q)) else "and"
        return f"{ws[0][1]} {how} {ws[1][1]}"
    if len(ws) > 2 and not ws[0][0] and all(neg for neg, _w in ws[1:]):
        return f"{ws[0][1]} but not {', '.join(w for _n, w in ws[1:])}"
    w = next((w for neg, w in ws if not neg), None)
    return f"Search: {w}" if w else "Search"


# ---- Suggest: the deck's tags a date's name points at ----

_STOP = {"and", "the", "for", "with", "part", "lecture", "lec", "week", "day", "read", "watch", "chapter", "unit",
         "video", "videos", "intro", "introduction", "review", "notes", "extra", "extras", "session", "class"}


def words(s):
    """Suggest.words: lower case, accents off, three letters up, no stop words or numbers."""
    s = unicodedata.normalize("NFKD", str(s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return [w for w in re.split(r"[^a-z0-9]+", s) if len(w) >= 3 and w not in _STOP and not w.isdigit()]


def _nums(s):
    return [int(x) for x in re.findall(r"\d+", str(s or ""))]


def _part_nums(seg):
    """A tag part's own numbers: a leading "03_" is the deck's order, not one."""
    return _nums(re.sub(r"^[#^]?\d+[_ .-]+", "", str(seg)))


def same_word(a, b):
    """Suggest's same: "arrhythmia" and "arrhythmias", "cardiac" and "cardio"."""
    s, l = (a, b) if len(a) <= len(b) else (b, a)
    if s == l or (len(s) >= 4 and l.startswith(s)):
        return True
    k = 0
    while k < len(s) and s[k] == l[k]:
        k += 1
    return k >= 5 and k >= 0.8 * len(s)


def suggest(name, rows, skip=lambda p: False, most=3):
    """Suggest.tags: [(path, n)] the deck's tags (rows: [(path, cards)]) a
    date's name points at, best first: every word of the name in the tag's
    path, one of them in its last part; a part a word matched that carries
    its own number carries one of the name's ("SLG 12" is never SLG 3)."""
    want = list(dict.fromkeys(words(name)))
    if not want:
        return []
    have = set(_nums(name))
    found = []
    for path, n in rows:
        if not n:
            continue
        segs = str(path).split("::")
        leaf = words(segs[-1])
        every = words(" ".join(segs))
        hit = sum(1 for w in want if any(same_word(w, x) for x in every))
        if not hit or not any(same_word(w, x) for w in want for x in leaf):
            continue
        if have and any(any(same_word(w, x) for w in want for x in words(g)) and _part_nums(g)
                        and not any(k in have for k in _part_nums(g)) for g in segs):
            continue
        if skip(path):
            continue
        found.append((path, n, hit / len(want), len(segs)))
    found.sort(key=lambda x: (-x[2], -x[3], x[1]))
    need = 1 if (found and found[0][2] >= 1) or len(want) <= 2 else (len(want) - 1) / len(want)
    return [(p, n) for p, n, score, _d in found if score >= need - 1e-9][:most]


# ---- Work: a date's cards over its study days ----

def _iso(day):
    return day.isoformat()


def _d(iso):
    return datetime.date.fromisoformat(str(iso))


def spread(doc, u, total, days):
    """Work.spread: [(iso, n)], the cards a date opens over its window's
    study days as the plan's days weigh them (Sched); all on the next study
    day when the window has none."""
    if not (total and total > 0) or not u.get("opens"):
        return []
    sch = {"days": days}
    a, b = S.window(doc, u, 0)
    ws, whole, x = [], 0, a
    while x <= b:
        w = int(S.weight(doc, sch, x, 0) or 0)
        ws.append((x, w))
        whole += w
        x += datetime.timedelta(days=1)
    if not whole:
        for i in range(1, 61):
            x = b + datetime.timedelta(days=i)
            if S.weight(doc, sch, x, 0):
                return [(_iso(x), total)]
        return [(_iso(a), total)]
    out, upto, prev = [], 0, 0
    for x, w in ws:
        upto += w
        q = min(total, -(-(total * upto) // whole))
        if q > prev:
            out.append((_iso(x), q - prev))
        prev = q
    return out


def work_map(doc, total_of, days):
    """Work.map: {iso: {"n", "by": [(unit, n)]}}, every date's work."""
    out = {}
    for u in S.units(doc):
        for day, k in spread(doc, u, total_of(u), days):
            e = out.setdefault(day, {"n": 0, "by": []})
            e["n"] += k
            e["by"].append((u, k))
    return out


def over(work, cap):
    """Work.over: runs of days over the pace (a quarter over it): [{a, b, top}]."""
    runs = []
    if not cap:
        return runs
    for day in sorted(work):
        v = work[day]["n"]
        if v <= cap * 1.25:
            continue
        r = runs[-1] if runs else None
        if r and _iso(_d(r["b"]) + datetime.timedelta(days=1)) == day:
            r["b"], r["top"] = day, max(r["top"], v)
        else:
            runs.append({"a": day, "b": day, "top": v})
    return runs


# ---- Reviews: the reviews a plan's dates bring, by week ----

def curve():
    """Reviews.CURVE: a typical card's next six weeks (ahead.GENERIC's cards)."""
    from .. import ahead
    return list(ahead.GENERIC[0])


def review_weeks(work):
    """Reviews.weeks: [{a: the week's first day, n: reviews a day}], from the
    first date to four weeks past the last."""
    ds = sorted(work)
    if not ds:
        return []
    cv = curve()
    per = {}
    for day, e in work.items():
        for k in range(1, len(cv)):
            x = _iso(_d(day) + datetime.timedelta(days=k))
            per[x] = per.get(x, 0) + e["n"] * cv[k]
    out, end, a = [], _d(ds[-1]) + datetime.timedelta(days=28), _d(ds[0])
    while a <= end:
        n = sum(per.get(_iso(a + datetime.timedelta(days=i)), 0) for i in range(7))
        out.append({"a": _iso(a), "n": n / 7})
        a += datetime.timedelta(days=7)
    return out


def review_peak(ws):
    """Reviews.peak: the busiest week, {wk: from 1, n}, or None."""
    best = None
    for i, w in enumerate(ws):
        if best is None or w["n"] > best["n"]:
            best = {"wk": i + 1, "n": w["n"]}
    return best


def _round(x):
    """JavaScript's Math.round: halves up (Python's round goes to even)."""
    return math.floor(x + 0.5)


def about(x):
    """Reviews.about: never more exact than it is (ahead.r)."""
    v = _round(x) if x < 30 else _round(x / 5) * 5 if x < 200 else _round(x / 10) * 10
    return f"{int(v):,}"


def weekly(ws):
    """weekly: a week by week line, a break between a plan's parts said
    once ("0 for 24 weeks"), its tail's zeros left off."""
    parts, z = [], 0
    for w in ws:
        s = about(w["n"])
        if s == "0":
            z += 1
            continue
        if z:
            parts.append(f"0 for {z} weeks" if z > 1 else "0")
        z = 0
        parts.append(s)
    return parts


# ---- the deck's tree, as the builder reads it (counts, children, order) ----

def natural(s):
    """Tags.natural's order: numbers by value, letters without case."""
    return [(0, int(x), "") if x.isdigit() else (1, 0, x.lower()) for x in re.findall(r"\d+|\D+", str(s))]


class Tree:
    """The deck's tags and subdecks as the builder sees them (its `count`,
    `kids`, `order`): keys "tag:PATH" and "deck:PATH", every path above a
    tag too; n(key) its cards here, everything under it. paths: [(path,
    cards)] for tags, decks the same; count: a function for a path's cards
    when they're asked for (a big deck's 30,000 tags aren't all counted)."""

    def __init__(self, tags=(), decks=(), count=None):
        self._n = {}
        self._count = count
        self.kids_of = {"root:tag": [], "root:deck": []}
        for kind, rows in (("tag", tags), ("deck", decks)):
            have = {}
            for row in rows:
                path, n = (row if isinstance(row, (tuple, list)) else (row, None))
                have[str(path).lower()] = str(path)
                if n is not None:
                    self._n[f"{kind}:{path}"] = int(n)
            for low, path in have.items():
                parts = path.split("::")
                parent = f"root:{kind}"
                for i in range(len(parts) - 1, 0, -1):
                    anc = "::".join(parts[:i]).lower()
                    if anc in have:
                        parent = f"{kind}:{have[anc]}"
                        break
                self.kids_of.setdefault(parent, []).append(f"{kind}:{path}")
        for k in self.kids_of:
            self.kids_of[k].sort(key=lambda x: natural(path_of(x)))
        self.order = {}
        self._walk("root:tag")
        self._walk("root:deck")

    def _walk(self, key):
        stack = list(reversed(self.kids_of.get(key) or []))
        while stack:
            k = stack.pop()
            self.order[k] = len(self.order)
            stack.extend(reversed(self.kids_of.get(k) or []))

    def has(self, key):
        return key in self.order

    def n(self, key):
        if key not in self._n:
            self._n[key] = int(self._count(kind_of(key), path_of(key))) if self._count and self.has(key) else 0
        return self._n[key]

    def kids(self, key):
        return self.kids_of.get(key) or []

    def only(self, key):
        """The cards on a tag and on none below it (overlaps make this a guess)."""
        return max(0, self.n(key) - sum(self.n(k) for k in self.kids(key)))

    def extra_kids(self, key):
        return [k for k in self.kids(key) if kind_of(key) == "tag" and is_extra(path_of(k).split("::")[-1])]


def kind_of(key):
    return key[:key.index(":")]


def path_of(key):
    return key[key.index(":") + 1:]


def under(a, b):
    """b is below a, the same kind (any case)."""
    return kind_of(a) == kind_of(b) and path_of(b).lower().startswith(path_of(a).lower() + "::")


def srcs(u):
    return [f"tag:{t}" for t in u.get("tags") or []] + [f"deck:{d}" for d in u.get("decks") or []]


def extras_of(tree, q):
    """The tag a without-its-extras search is, or None."""
    for key in tree.order:
        if kind_of(key) == "tag" and tree.extra_kids(key):
            if without_q(path_of(key), [path_of(k) for k in tree.extra_kids(key)]) == q:
                return path_of(key)
    return None


def placed_keys(doc, tree=None):
    """placedKeys: every tag and subdeck on a date (a tag kept without its
    extras is on the calendar too)."""
    out = set()
    for u in S.units(doc):
        out.update(srcs(u))
        if tree is not None:
            for q in u.get("search") or []:
                if "-" in q:
                    p = extras_of(tree, q)
                    if p:
                        out.add(f"tag:{p}")
    return out


def is_placed(key, placed):
    return key in placed or any(under(p, key) for p in placed)


def placed_below(key, placed):
    below = [p for p in placed if under(key, p)]
    return [p for p in below if not any(q != p and under(q, p) for q in below)]


def eff(tree, key, placed):
    """A source's cards not already on another date through a tag below it."""
    return max(0, tree.n(key) - sum(tree.n(p) for p in placed_below(key, placed)))


def unit_total(tree, u, placed):
    """unitTotal: what a date opens, as the builder counts it."""
    ids = len(u.get("nids") or []) + len(u.get("cids") or []) + len(u.get("notes") or [])
    ids_n = (u.get("idn") if u.get("idn") is not None else ids) if ids else 0
    sn = sum(int((u.get("sn") or {}).get(q) or 0) for q in u.get("search") or [])
    return sum(eff(tree, k, placed) for k in srcs(u)) + len(u.get("cards") or []) + sn + int(ids_n)


def label(tree, key, placed):
    w = _tag_word(path_of(key).split("::")[-1])
    return f"{w} · the rest" if placed_below(key, placed) else w


def auto_name(tree, u, placed):
    """autoName: a date named for what's on it."""
    ks = srcs(u)
    if not ks and u.get("cut"):
        return None  # a cut's name is its plan tag's: the caller keeps the one it has
    if not ks:
        wo = next((extras_of(tree, q) for q in u.get("search") or [] if "-" in q and extras_of(tree, q)), None)
        if wo:
            return label(tree, f"tag:{wo}", placed)[:60]
        if u.get("search"):
            return "Search"
        n = len(u.get("cards") or [])
        return f"{n} single card{'s' if n != 1 else ''}" if n else None
    return f"{label(tree, ks[0], placed)}{f' + {len(ks) - 1} more' if len(ks) > 1 else ''}"[:60]


def pieces(tree, key, cap, placed):
    """The pieces of `key` still to place, chapters kept whole where they fit
    `cap`: a bigger one splits by its own tags, the part only on it goes last,
    and a big one with nothing below splits evenly."""
    if is_placed(key, placed):
        return []
    below = placed_below(key, placed)
    whole = eff(tree, key, placed)
    if not whole:
        return []
    if not below and (not cap or tree.n(key) <= cap):
        return [{"key": key, "n": tree.n(key)}]
    ks = tree.kids(key)
    if not ks:
        return [{"key": key, "n": whole, "even": bool(cap) and whole > cap}]
    out = []
    for k in ks:
        out.extend(pieces(tree, k, cap, placed))
    rest = tree.only(key)
    if rest > 0:
        out.append({"key": key, "n": rest, "rest": True, "even": bool(cap) and rest > cap})
    return out


UNITS_MAX = 200
SOURCES_MAX = 50
FULL = f"A plan holds up to {UNITS_MAX} dates."


class _Days:
    """A plan's study days, as Sched weighs them (its pace's days)."""

    def __init__(self, doc, days):
        self.doc, self.sch = doc, {"days": days}

    def study(self, iso):
        return int(S.weight(self.doc, self.sch, _d(iso), 0) or 0) > 0

    def next(self, iso):
        x = _d(iso)
        for _i in range(400):
            x += datetime.timedelta(days=1)
            if self.study(_iso(x)):
                return _iso(x)
        return _iso(_d(iso) + datetime.timedelta(days=1))

    def first(self, iso):
        return iso if self.study(iso) else self.next(iso)

    def count(self, a, b):
        n, x = 0, _d(a)
        while x <= _d(b):
            n += self.study(_iso(x))
            x += datetime.timedelta(days=1)
        return n


def fill(doc, items, frm, until, cap, days, new_id, end=None):
    """The builder's fill: puts `items` (pieces) on study days from `frm`
    (none starting after `until`), `cap` cards a day, chapters whole;
    nothing runs past `end` (an even piece there takes fewer days:
    clipped). Works on `doc` itself. {placed, last, left, clipped, note,
    touched}: the cards it put on, its last day, what didn't go on (in
    order), the note a ceiling left, the dates it made or added to."""
    dd = _Days(doc, days)
    units = doc.setdefault("units", [])
    out = {"placed": 0, "last": None, "left": [], "clipped": False, "note": "", "touched": set()}
    state = {"d": dd.first(frm), "room": cap or float("inf"), "used": 0}

    def nxt():
        state["d"], state["room"], state["used"] = dd.next(state["d"]), cap or float("inf"), 0

    def unit_on(d):
        u = next((x for x in units if x.get("opens") == d and not x.get("even")), None)
        if u is None:
            if len(units) >= UNITS_MAX:
                out["note"] = FULL
                return None
            u = {"id": new_id(), "name": "", "opens": d, "tags": [], "decks": [], "cards": []}
            units.append(u)
        return u

    def room_for(it):
        f = "tags" if kind_of(it["key"]) == "tag" else "decks"
        u = next((x for x in units if x.get("opens") == state["d"] and not x.get("even")), None)
        return u is None or path_of(it["key"]) in (u.get(f) or []) or len(u.get(f) or []) < SOURCES_MAX

    def add_to(d, key):
        f = "tags" if kind_of(key) == "tag" else "decks"
        had = next((x for x in units if x.get("opens") == d and not x.get("even")), None)
        if had and path_of(key) not in (had.get(f) or []) and len(had.get(f) or []) >= SOURCES_MAX:
            out["note"] = f"A date holds up to {SOURCES_MAX} {'tags' if f == 'tags' else 'subdecks'}."
            return None
        u = unit_on(d)
        if u is None:
            return None
        u[f] = list(u.get(f) or [])
        if path_of(key) not in u[f]:
            u[f].append(path_of(key))
        out["touched"].add(u["id"])
        return u

    def even_unit(d, key, k):
        last = d
        for _i in range(1, k):
            last = dd.next(last)
        if last == d:
            return add_to(d, key)
        if len(units) >= UNITS_MAX:
            out["note"] = FULL
            return None
        u = {"id": new_id(), "name": "", "opens": d, "due": last, "even": True, "tags": [], "decks": [], "cards": []}
        u["tags" if kind_of(key) == "tag" else "decks"].append(path_of(key))
        units.append(u)
        out["touched"].add(u["id"])
        return u

    i = 0
    while i < len(items):
        it = items[i]
        if until and state["d"] > until:
            break
        if it.get("even"):
            if state["used"]:
                nxt()
                if until and state["d"] > until:
                    break
            k = max(2, -(-it["n"] // cap))
            if end and dd.count(state["d"], end) < k:
                k = dd.count(state["d"], end)
                out["clipped"] = True
            u = even_unit(state["d"], it["key"], k)
            if u is None:
                break
            out["placed"] += it["n"]
            out["last"] = u.get("due") or state["d"]
            state["d"], state["room"], state["used"] = dd.next(u.get("due") or state["d"]), cap, 0
            i += 1
            continue
        if not cap:
            if state["used"]:
                nxt()
        elif it["n"] > state["room"] and state["used"]:
            nxt()
        if until and state["d"] > until:
            break
        if not room_for(it):
            nxt()
            if until and state["d"] > until:
                break
        if add_to(state["d"], it["key"]) is None:
            break
        state["room"] -= it["n"]
        state["used"] += 1
        out["placed"] += it["n"]
        out["last"] = state["d"]
        i += 1
    out["left"] = items[i:]
    doc["units"] = sorted(units, key=lambda u: str(u.get("opens") or ""))
    return out


def left_names(xs):
    """leftNames: what a fill left off, by name: "Renal, Pulm · the rest and 2 more"."""
    names = [f"{_tag_word(path_of(x['key']).split('::')[-1])}{' · the rest' if x.get('rest') else ''}" for x in xs[:3]]
    return ", ".join(names) + (f" and {len(xs) - 3} more" if len(xs) > 3 else "")


# ---- what to cover, and laying it out (layOut) ----

def tag_kind(path):
    """Tags.kind: a ^ part makes a tag a system's, a # part a resource's, else other."""
    segs = str(path).split("::")
    return "system" if any(s.startswith("^") for s in segs) else "resource" if any(s.startswith("#") for s in segs) else "other"


def kinds_below(tree, key, memo=None):
    """kindsBelow: the views a tag holds, itself and everything under it."""
    memo = {} if memo is None else memo
    if key in memo:
        return memo[key]
    out = {tag_kind(path_of(key))} if key.startswith("tag:") else set()
    for k in tree.kids(key):
        out |= kinds_below(tree, k, memo)
    memo[key] = out
    return out


def in_view(tree, key, view, memo=None):
    """inView: what ticking a key covers in a view: a tag holding more than
    one view (a big shared deck's top tag holds resources and systems, the
    same cards twice) covers only what this view shows of it."""
    if view == "deck" or kind_of(key) == "deck":
        return [key]
    if len(kinds_below(tree, key, memo)) > 1:
        out = []
        for c in tree.kids(key):
            if view in kinds_below(tree, c, memo):
                out.extend(in_view(tree, c, view, memo))
        return out
    return [key]


def covered(cover, key):
    return key in cover or any(under(c, key) for c in cover)


def partly(cover, key):
    return any(under(key, c) for c in cover)


def ticked(cover, tree, key, view, memo=None):
    """A row's tick: covered, or all it covers in this view is."""
    keys = in_view(tree, key, view, memo) if tree is not None else [key]
    return covered(cover, key) or (len(keys) > 1 and all(covered(cover, x) for x in keys))


def toggle(cover, tree, key, view, memo=None):
    """The builder's tick on What to cover: a ticked one off; else what it
    covers in this view on, anything under it it now holds off."""
    cover = set(cover)
    if key in cover:
        cover.discard(key)
        return cover
    keys = in_view(tree, key, view, memo)
    if len(keys) > 1 and all(covered(cover, x) for x in keys):
        return cover - set(keys)
    if covered(cover, key):
        return cover
    for x in keys:
        for c in list(cover):
            if under(x, c):
                cover.discard(c)
        cover.add(x)
    return cover


def cover_items(tree, cover):
    """coverItems: what's ticked, none under another ticked one, in the tree's order."""
    have = [k for k in cover if tree.has(k) and not any(c != k and under(c, k) for c in cover)]
    return sorted(have, key=lambda k: tree.order.get(k, 0))


def cover_left(tree, cover, placed):
    """coverLeft: cards ticked but on no date yet."""
    return sum(0 if is_placed(k, placed) else eff(tree, k, placed) for k in cover_items(tree, cover))


def last_day(doc):
    """lastDay: the plan's last day, an even date's due date."""
    days = [str(u.get("due") if u.get("even") and u.get("due") else u.get("opens") or "") for u in S.units(doc)]
    return max(days) if days else ""


def plan_start(doc, fallback):
    us = S.units(doc)
    return min(str(u["opens"]) for u in us) if us else fallback


def next_monday(today):
    d = _d(today)
    while d.weekday() != 0:
        d += datetime.timedelta(days=1)
    return _iso(d)


def _after(doc, start):
    ld = last_day(doc)
    a = _iso(_d(ld) + datetime.timedelta(days=1)) if ld else start
    return a if a > start else start


def pace_daily(pace):
    """paceDaily: 0 when each day is placed by hand."""
    return 0 if pace.get("mode") == "placed" else max(1, int(pace.get("daily") or 0))


def end_daily(doc, tree, pace, cover, start):
    """endDaily: the cards a day that finish what's left by the end date."""
    if not doc.get("end"):
        return int(pace.get("daily") or 0)
    dd = _Days(doc, pace.get("days") or [1] * 7)
    frm = _after(doc, start)
    days = dd.count(frm, doc["end"]) if frm <= doc["end"] else 0
    rest = cover_left(tree, cover, placed_keys(doc, tree))
    return max(1, -(-rest // days)) if days and rest else 0


def finish_by(doc, tree, pace, cover, start, daily):
    """finishBy: the day what's left is done at `daily` a study day."""
    rest = cover_left(tree, cover, placed_keys(doc, tree))
    if not daily or not rest:
        return None
    dd = _Days(doc, pace.get("days") or [1] * 7)
    d = dd.first(_after(doc, start))
    for _i in range(2000):
        rest -= daily
        if rest <= 0:
            break
        d = dd.next(d)
    return d


def lay_out(doc, tree, pace, cover, start, today, new_id, week_ahead=False, aim=None):
    """layOut: what's ticked and not on a date yet, laid on the plan's study
    days after its last date (or from its start), at the pace: Fill to the
    end date (a little more a day, up to about twice the pace, until it all
    fits; past that it stops there and says what's left), Fill at N a day,
    or just next week. aim: an event's id; the new dates before it prep for
    it. Works on `doc` itself. {note, daily, touched}: daily, the pace it
    was filled at (Finish by)."""
    from .. import plans as P
    days = pace.get("days") or [1] * 7
    dd = _Days(doc, days)
    end = doc.get("end") if pace.get("mode") == "end" and doc.get("end") else None
    frm = _after(doc, start)
    until = end
    if week_ahead:
        nm = next_monday(today)
        if frm < nm:
            frm = nm
        mon = _iso(S.monday(_d(frm)))
        frm = mon if frm < mon else frm
        sun = _iso(_d(mon) + datetime.timedelta(days=6))
        until = end if end and end < sun else sun
    out = {"note": "", "daily": None, "touched": set()}
    if until and dd.first(frm) > until:
        out["note"] = (f"Nothing fits by {P.fmt_day(end)}: "
                       + (f"the dates already run to {P.fmt_day(last_day(doc))}" if last_day(doc) else f"the plan starts {P.fmt_day(start)}")
                       + ". Move the finish date." if end and until == end else "No study days left in that week.")
        return out
    if pace.get("mode") == "end":
        d1 = end_daily(doc, tree, pace, cover, start)
        if d1:
            pace = dict(pace, daily=d1)
    cap = pace_daily(pace)
    placed = placed_keys(doc, tree)
    items = [p for k in cover_items(tree, cover) for p in pieces(tree, k, cap, placed)]
    if not items:
        out["note"] = "Everything ticked is on the calendar already." if cover else "Tick what to cover first."
        return out
    before = {u["id"] for u in S.units(doc)}
    was = [dict(u) for u in doc.get("units") or []]
    tries = 0
    while True:
        doc["units"] = [dict(u) for u in was]
        r = fill(doc, [p for k in cover_items(tree, cover) for p in pieces(tree, k, cap, placed)], frm, until, cap, days,
                 new_id, end)
        if not end or week_ahead or not (r["left"] or r["clipped"]) or r["note"] or tries >= 7:
            break
        tries += 1
        cap = min(5000, math.ceil(cap * 1.1))
    if pace.get("mode") == "end":
        out["daily"] = cap
    ev = next((e for e in doc.get("events") or [] if isinstance(e, dict) and e.get("id") == aim), None) \
        if aim and pace.get("mode") == "end" else None
    if ev:
        for u in doc["units"]:
            if u["id"] not in before and str(u["opens"]) < str(ev.get("day")) and not u.get("for"):
                u["for"] = ev["id"]
    left_n = sum(x["n"] for x in r["left"])
    words = [f"Put {r['placed']:,} cards on {P.fmt_day(dd.first(frm))} to {P.fmt_day(r['last'])}." if r["placed"]
             else "No study days left in that week." if week_ahead else "Nothing fit."]
    if left_n and (r["note"] or not week_ahead):
        words.append(f"{r['note'] + ' ' if r['note'] else ''}{left_n:,} didn't fit"
                     f"{' by ' + P.fmt_day(end) if end and not r['note'] else ''}: {left_names(r['left'])}.")
    out["note"] = " ".join(words)
    out["touched"] = r["touched"]
    return out


def heavy(doc, tree, pace, cover, start, total_of):
    """heavyNote: the first run of days whose work is over the pace (a
    quarter over it): {a, b, top, unit, total, last, cap} or None."""
    cap = (end_daily(doc, tree, pace, cover, start) or int(pace.get("daily") or 0)) if pace.get("mode") == "end" \
        else int(pace.get("daily") or 0) if pace.get("mode") == "daily" else 0
    if not cap:
        return None
    work = work_map(doc, total_of, pace.get("days") or [1] * 7)
    runs = over(work, cap)
    if not runs:
        return None
    run = runs[0]
    u, _k = sorted(work[run["a"]]["by"], key=lambda x: -x[1])[0]
    last = _iso(S.window(doc, u, 0)[1])
    return dict(run, unit=u, total=total_of(u), last=last, cap=cap)


def biggest(tree, u, placed):
    """heavyNote's Split: a date's biggest tag or subdeck this Anki counts
    (none on an even date: it's spread already)."""
    if u.get("even"):
        return None
    ks = [k for k in srcs(u) if eff(tree, k, placed) > 0]
    return max(ks, key=lambda k: eff(tree, k, placed)) if ks else None


def give_till(doc, days, u, total, cap):
    """heavyNote's Give it till: the day by which the pace's study days, from
    the date's own, hold all it opens (a year at most)."""
    dd = _Days(doc, days)
    need = -(-int(total) // max(1, int(cap)))
    till, k = str(u["opens"]), 1 if dd.study(u["opens"]) else 0
    lim = _iso(_d(u["opens"]) + datetime.timedelta(days=366))
    while k < need and till < lim:
        till = _iso(_d(till) + datetime.timedelta(days=1))
        k += dd.study(till)
    return till
