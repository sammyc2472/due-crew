"""3.1 plans: matching, progress and the morning's one step. Pure over a
collection: no aqt, no network, no config. The glue (state, the morning's
timing, the board, the menu) is plan_flow.py; see docs/plans-design.md.

A plan is a list of dates (units) for one shared deck. A unit's cards are
tags (a path; everything under it counts, case-insensitive), subdecks (a
path under the plan's deck) and single cards ([note guid, card ord]: that
card only, never its siblings). A follower runs it on one of their decks;
matching stays inside that deck and its subdecks.

Matching reads the deck once (DeckIndex: one query), then answers every
unit from memory: tag paths are found in a sorted list by prefix, so a
200-unit plan is 200 bisects, not 200 scans of the notes table.

Nothing here ever suspends a card. open_cards unsuspends, in one undo step.
"""

import bisect
import weakref
import datetime
import hashlib
import json
import re

from .backend.shapes import normalize_code

PLAN_CODE_LEN = 8
_SEP = "::"


# ---- words ----

def plan_title(plan):
    """"Step 1 · Dre's plan"."""
    return f'{plan.get("name") or "Plan"} · {plan.get("ownerName") or "?"}’s plan'


def fmt_day(iso):
    """"Mon 5 Oct"."""
    try:
        d = datetime.date.fromisoformat(str(iso))
    except ValueError:
        return str(iso)
    return f"{d:%a} {d.day} {d:%b}"


def weekday_or_day(iso, today):
    """"Monday" within the week before today, else "Mon 5 Oct"."""
    try:
        d, t = datetime.date.fromisoformat(str(iso)), datetime.date.fromisoformat(str(today))
    except ValueError:
        return str(iso)
    return f"{d:%A}" if 0 <= abs((t - d).days) < 7 else fmt_day(iso)


def code_from(text):
    """A plan code from a typed code or a pasted link (duecrew.com/p/CODE)."""
    text = str(text or "").strip()
    m = re.search(r"/p/([A-Za-z0-9 -]+)", text)
    return normalize_code(m.group(1) if m else text)


# ---- the plan doc, as it came from the server (already cleaned) ----

def units(doc):
    return [u for u in (doc or {}).get("units") or [] if isinstance(u, dict) and u.get("id")]


def unit_sources(unit, deck_id=None, swap=None):
    """What a unit matched with when it was applied here: its deck, swap and
    sources. A later change opens only what the new sources add."""
    out = [deck_id, list(swap or []), list(unit.get("tags") or []), list(unit.get("decks") or []),
           [list(c) for c in unit.get("cards") or []]]
    if unit.get("search"):
        out.append(list(unit["search"]))  # 3.3, C3
    if unit.get("nids") or unit.get("cids"):
        out.append([list(unit.get("nids") or []), list(unit.get("cids") or [])])  # E1
    return out


def unit_sig(unit, deck_id=None, swap=None):
    """What a unit opens on this computer: its sources, the deck it runs on
    and the tag swap. Remembered once applied; a unit whose date moves keeps
    its sig (so moving it later changes nothing), one the author adds cards
    to gets a new one (so the new cards open the next morning)."""
    blob = json.dumps([deck_id, list(swap or []), sorted(str(t).lower() for t in unit.get("tags") or []),
                       sorted(str(d).lower() for d in unit.get("decks") or []),
                       sorted(f"{g}:{o}" for g, o in unit.get("cards") or [])]
                      + ([sorted(unit["search"])] if unit.get("search") else [])
                      + ([sorted(unit.get("nids") or []), sorted(unit.get("cids") or [])]
                         if unit.get("nids") or unit.get("cids") else []))
    return hashlib.sha1(blob.encode()).hexdigest()[:12]


def span_weeks(doc, today):
    """(week, weeks) of the plan: "week 3 of 14". week 0 before it starts."""
    us = units(doc)
    if not us:
        return 0, 0
    try:
        first = datetime.date.fromisoformat(us[0]["opens"])
        last = max(datetime.date.fromisoformat(u.get("due") or u["opens"]) for u in us)
        now = datetime.date.fromisoformat(today)
    except ValueError:
        return 0, 0
    weeks = (last - first).days // 7 + 1
    week = 0 if now < first else min(weeks, (now - first).days // 7 + 1)
    return week, weeks


# ---- tags ----

def _parts(path):
    return [p for p in str(path).split(_SEP)]


def swapped(path, swap):
    """The plan's tag read in my copy: `Step1::X` as `Step1_v11::X`."""
    if not swap:
        return str(path)
    parts = _parts(path)
    if parts and parts[0].lower() == str(swap[0]).lower():
        parts[0] = str(swap[1])
    return _SEP.join(parts)


# ---- the deck, read once ----

_STATIC = {}  # (collection, deck id) -> (fingerprint, the parts that change only with notes, collection ref)
_STATIC_KEYS = ("leech", "by_deck", "by_ref", "home", "by_tag", "tag_names", "tag_keys", "by_guid", "guid_of", "by_nid", "_searches")


class DeckIndex:
    """One deck and its subdecks, read in one query: every card's id, home
    deck, ord, queue and type, with its note's guid and tags. Cards in a
    filtered deck count in their home deck."""

    def __init__(self, col, did):
        self.did = int(did)
        names = {int(r.id): str(r.name) for r in col.decks.all_names_and_ids()}
        self.name = names.get(self.did, "")
        tree = [int(d) for d in col.decks.deck_and_child_ids(self.did)]
        root = self.name.lower()
        # subdeck path under the chosen deck ("" is the deck itself) -> did
        self.rel = {}        # lowercased -> did
        self.spelled = {}    # lowercased -> as written
        for d in tree:
            n = names.get(d, "")
            rel = n[len(root) + 2:] if n.lower() != root else ""
            self.rel[rel.lower()] = d
            self.spelled[rel.lower()] = rel
        ids = ",".join(str(d) for d in tree) or "0"
        where = f"WHERE c.did IN ({ids}) OR c.odid IN ({ids})"
        self.col = col
        # 3.3: the tags, note ids and subdecks change only when notes do;
        # kept between refreshes while this fingerprint holds (a few ms),
        # and only each card's state is read again
        sig = (tuple(sorted((d, names.get(d, "")) for d in tree)),
               tuple(col.db.first("SELECT count(), max(n.mod), max(c.id), sum(c.did), sum(c.odid), sum(c.ord) "
                                  f"FROM cards c JOIN notes n ON n.id = c.nid {where}") or ()))
        key = (id(col), self.did)
        kept = _STATIC.get(key)
        if kept and kept[2]() is col and kept[0] == sig:
            self.__dict__.update(kept[1])
        else:
            self._read_static(col, tree, where)
            try:
                ref = weakref.ref(col)  # never keeps a closed collection alive
            except TypeError:
                ref = (lambda: None)
            for k in [k for k, v in _STATIC.items() if v[2]() is None]:
                _STATIC.pop(k, None)  # a closed profile's decks
            _STATIC[key] = (sig, {k: getattr(self, k) for k in _STATIC_KEYS}, ref)
        self.cards = {}      # cid -> (queue, type)
        self.order = {}      # cid -> the deck's own order: cards seen before first, then new by position
        home = self.home
        for cid, queue, ctype, due in col.db.all(f"SELECT c.id, c.queue, c.type, c.due FROM cards c {where}"):
            cid = int(cid)
            if cid in home:
                self.cards[cid] = (int(queue), int(ctype))
                self.order[cid] = (int(ctype) == 0, int(due or 0), cid)
        self.fell_back = set()  # unit ids matched by their note ids (C5)

    def _read_static(self, col, tree, where):
        rows = col.db.all(
            "SELECT c.id, CASE WHEN c.odid != 0 THEN c.odid ELSE c.did END, c.ord, n.guid, n.tags, n.id "
            f"FROM cards c JOIN notes n ON n.id = c.nid {where}")
        self.leech = set()   # cids whose note Anki tagged leech: a plan never opens them
        self.by_deck = {}    # did -> [cid]
        self.by_ref = {}     # (guid, ord) -> cid
        self.home = set()    # the cids in this deck and its subdecks
        self.by_nid = {}     # E1: note id -> [cid]
        by_tag = {}          # lowercased tag -> [cid]
        self.tag_names = {}  # lowercased tag -> as written
        treeset = set(tree)
        for cid, home, ord_, guid, tags, nid in rows:
            if int(home) not in treeset:
                continue
            cid = int(cid)
            self.home.add(cid)
            self.by_nid.setdefault(int(nid), []).append(cid)
            self.by_deck.setdefault(int(home), []).append(cid)
            self.by_ref[(str(guid), int(ord_))] = cid
            for t in str(tags or "").split():
                low = t.lower()
                if low == "leech":
                    self.leech.add(cid)
                by_tag.setdefault(low, []).append(cid)
                self.tag_names.setdefault(low, t)
        self.by_tag = by_tag
        self.tag_keys = sorted(by_tag)
        # searches run through the collection; note ids back a renamed tag
        self.by_guid = {}
        for (g, _o), cid in self.by_ref.items():
            self.by_guid.setdefault(g, []).append(cid)
        self.guid_of = {cid: g for (g, _o), cid in self.by_ref.items()}
        # a search's answer, kept with the rest: it changes when notes or cards
        # do (a plan's searches are about the deck, never one person's reviews)
        self._searches = {}

    # -- sources --

    def tag_cards(self, path):
        """Cards tagged `path` or anything under it."""
        low = str(path).lower().strip()
        if not low:
            return set()
        out = set(self.by_tag.get(low, ()))
        lo = bisect.bisect_left(self.tag_keys, low + _SEP)
        hi = bisect.bisect_left(self.tag_keys, low + ":;")  # just past every "low::…"
        for k in self.tag_keys[lo:hi]:
            out.update(self.by_tag[k])
        return out

    def has_tag(self, path):
        low = str(path).lower()
        if low in self.by_tag:
            return True
        i = bisect.bisect_left(self.tag_keys, low + _SEP)
        return i < len(self.tag_keys) and self.tag_keys[i].startswith(low + _SEP)

    def deck_cards(self, path, plan_deck=""):
        """A subdeck by its path in the plan (which starts with the plan's
        deck name), read under my chosen deck."""
        low, root = str(path).lower(), str(plan_deck or "").lower()
        if root and low == root:
            rel = ""
        elif root and low.startswith(root + _SEP):
            rel = low[len(root) + 2:]
        else:
            rel = low
        out = set()
        for r, d in self.rel.items():
            if not rel or r == rel or r.startswith(rel + _SEP):
                out.update(self.by_deck.get(d, ()))
        return out

    def search_cards(self, q):
        """3.3, C3: an Anki search, run by this collection, kept to this deck."""
        if q not in self._searches:
            try:
                found = {int(c) for c in self.col.find_cards(str(q))}
            except Exception:
                found = set()  # a search this Anki can't read finds nothing
            self._searches[q] = {c for c in found if c in self.cards}
        return self._searches[q]

    def match(self, unit, swap=None, plan_deck=""):
        """{cid} for one unit on this deck."""
        out = set()
        missing = False
        for t in unit.get("tags") or []:
            got = self.tag_cards(swapped(t, swap))
            missing = missing or not got
            out |= got
        for d in unit.get("decks") or []:
            got = self.deck_cards(d, plan_deck)
            missing = missing or not got
            out |= got
        if missing and unit.get("ids"):
            # 3.3, C5: a tag this copy names differently (a newer AnKing):
            # the author's note ids behind the date find its cards
            by_id = {c for g in unit["ids"] for c in self.by_guid.get(g, ())}
            if by_id - out:
                self.fell_back.add(unit.get("id"))
                out |= by_id
        for q in unit.get("search") or []:
            out |= self.search_cards(q)
        for g, o in unit.get("cards") or []:
            cid = self.by_ref.get((str(g), int(o)))
            if cid is not None:
                out.add(cid)
        out |= self.id_cards(unit)
        return out

    def id_cards(self, unit):
        """E1: the cards of a date's pasted note ids and card ids, in this deck."""
        out = set()
        for n in unit.get("nids") or []:
            out.update(c for c in self.by_nid.get(int(n), ()) if c in self.cards)
        for c in unit.get("cids") or []:
            if int(c) in self.cards:
                out.add(int(c))
        return out

    def single_found(self, unit):
        return sum(1 for g, o in unit.get("cards") or [] if (str(g), int(o)) in self.by_ref)

    # -- numbers --

    def counts(self, cids):
        """[opened, seen, total]: opened = not suspended, seen = answered at
        least once (Anki's own "not new")."""
        opened = seen = 0
        for cid in cids:
            queue, ctype = self.cards[cid]
            opened += queue != -1
            seen += ctype != 0
        return [opened, seen, len(cids)]

    def suspended(self, cids):
        return {cid for cid in cids if self.cards[cid][0] == -1}

    def in_order(self, cids):
        """[(cid, suspended)] in the deck's own order (3.2's spread opens the first ones)."""
        return [(cid, self.cards[cid][0] == -1) for cid in sorted(cids, key=self.order.__getitem__)]

    def openable(self, cids):
        """The suspended ones a plan may open: never a leech Anki suspended."""
        return {cid for cid in cids if self.cards[cid][0] == -1 and cid not in self.leech}

    # -- the builder's tree --

    def tree(self, with_tags=True, with_decks=True, cap=None):
        """(tags, decks) for PUT /plans/trees: [[path, cards]] each, names and
        counts only. A tag counts every card under it; a subdeck (and the
        deck itself, 3.3), every card in it and below. At most `cap` of each, shallowest and biggest first."""
        tags = []
        if with_tags:
            counts = {}
            for low, cids in self.by_tag.items():
                parts = _parts(self.tag_names[low])
                for i in range(1, len(parts) + 1):
                    counts.setdefault(_SEP.join(parts[:i]), set()).update(cids)
            # one spelling per path, case-insensitively
            merged = {}
            for path, cids in counts.items():
                merged.setdefault(path.lower(), [path, set()])[1].update(cids)
            tags = [[p, len(c)] for p, c in merged.values()]
            tags.sort(key=lambda x: (x[0].count(_SEP), -x[1], x[0].lower()))
            tags = sorted(tags[:cap] if cap else tags, key=lambda x: x[0].lower())
        decks = []
        if with_decks:
            for rel, d in self.rel.items():
                n = sum(len(self.by_deck.get(dd, ())) for r, dd in self.rel.items()
                        if not rel or r == rel or r.startswith(rel + _SEP))
                if n:
                    # 3.3: the deck itself too, for a deck with no tags or subdecks
                    decks.append([f"{self.name}{_SEP}{self.spelled[rel]}" if rel else self.name, n])
            decks.sort(key=lambda x: x[0].lower())
            decks = decks[:cap] if cap else decks
        return tags, decks

    def top_tags(self):
        """The first part of every tag here, as written."""
        out = {}
        for low in self.tag_keys:
            first = self.tag_names[low].split(_SEP)[0]
            out.setdefault(first.lower(), first)
        return out


# ---- the tree as it goes up (3.3) ----

TREE_BUDGET = 1_400_000  # bytes of JSON: under the server's 1.5 MB for a tree, with room for decks


def _qid(path):
    """A question-bank id (UWorld's, AMBOSS's…): a leaf that's only digits.
    Thousands of them, one card or two each; they go last."""
    return path.rsplit(_SEP, 1)[-1].strip().isdigit()


def nest(rows, budget=TREE_BUDGET):
    """[[path, n]] as the builder's tree: nested, each name once
    ([name, n] or [name, n, [children]]), the most useful first while it
    fits `budget` bytes: tags that aren't question ids, shallow before
    deep, big before small. A kept tag keeps its parents. Returns (tree,
    kept, left out)."""
    counts = {p: n for p, n in rows}
    order = sorted(rows, key=lambda r: (_qid(r[0]), r[0].count(_SEP), -r[1], r[0].lower()))
    kept, size, dropped = set(), 0, 0
    for p, _n in order:
        if p in kept:
            continue
        parts = p.split(_SEP)
        new = [a for a in (_SEP.join(parts[:i]) for i in range(1, len(parts) + 1)) if a not in kept]
        cost = sum(len(json.dumps(a.rsplit(_SEP, 1)[-1])) + len(str(counts.get(a, 0))) + 8 for a in new)
        if size + cost > budget:
            dropped += 1
            continue
        kept.update(new)
        size += cost
    root = {}
    for p in sorted(kept, key=lambda x: x.lower()):
        node = root
        parts = p.split(_SEP)
        for i, part in enumerate(parts):
            node = node.setdefault(part, {"n": counts.get(_SEP.join(parts[:i + 1]), 0), "k": {}})["k"]

    def out(level):
        return [[name, v["n"], out(v["k"])] if v["k"] else [name, v["n"]] for name, v in level.items()]
    return out(root), len(kept), dropped


# ---- following ----

def unit_matches(idx, doc, swap=None):
    """{unit id: {cid}} for a whole plan on one deck."""
    return {u["id"]: idx.match(u, swap, doc.get("deck", "")) for u in units(doc)}


def progress(idx, doc, swap=None):
    """{unit id: [opened, seen, total]}."""
    return {uid: idx.counts(cids) for uid, cids in unit_matches(idx, doc, swap).items()}


def found_total(idx, doc, swap=None):
    """Cards the plan finds in this deck, each counted once."""
    seen = set()
    for cids in unit_matches(idx, doc, swap).values():
        seen |= cids
    return len(seen)


def tag_hits(idx, doc, swap=None):
    """(tags found, tags in the plan): how well the plan's tags line up."""
    tags = {str(t) for u in units(doc) for t in u.get("tags") or []}
    return sum(1 for t in tags if idx.has_tag(swapped(t, swap))), len(tags)


def detect_swap(idx, doc):
    """When my tags start differently (another version of the deck renames
    the top tag): (plan top, my top) that makes the most of the plan's tags
    line up, or None when nothing beats reading them as they are."""
    tags = {str(t) for u in units(doc) for t in u.get("tags") or []}
    if not tags:
        return None
    base, n = tag_hits(idx, doc)
    if base * 2 >= n:
        return None
    theirs = {}
    for t in tags:
        first = t.split(_SEP)[0]
        theirs.setdefault(first.lower(), first)
    best, best_hits = None, base
    mine = idx.top_tags()
    for their_low, their in theirs.items():
        for my_low, my in mine.items():
            if my_low == their_low:
                continue
            hits, _n = tag_hits(idx, doc, (their, my))
            if hits > best_hits:
                best, best_hits = (their, my), hits
    return best


def due_now(doc, applied, today, sig):
    """Units that open by today and aren't applied here in their current
    form: [(unit, "open" | "skip")]. A unit marked skipped (joined late,
    started from the next one) stays skipped when its cards change."""
    out = []
    for u in units(doc):
        if str(u.get("opens") or "9999") > today:
            continue
        s = sig(u)
        have = applied.get(u["id"])
        if have == s or have == "skip:" + s:
            continue
        out.append((u, "skip" if isinstance(have, str) and have.startswith("skip:") else "open"))
    return out


def _cards(n):
    return f"{n:,} card{'s' if n != 1 else ''}"


def match_rows(idx, doc, swap=None, shown=5):
    """[(label, text, missing)] for the match list: a unit's tags and
    subdecks as one row (found of the author's count when the plan has
    one, else cards found), its single cards as another (found of picked). Past `shown`
    rows, the rest of the units are one row: how many, and their cards."""
    rows, rest = [], []
    for u in units(doc):
        if len(rows) >= shown:
            rest.append(u)
            continue
        name = u.get("name") or "?"
        if u.get("tags") or u.get("decks"):
            n = len(idx.match(dict(u, cards=[], nids=[], cids=[]), swap, doc.get("deck", "")))
            of = u.get("n")  # the author's count, when the builder saved one
            text = (f"{n:,} of {of:,}" if isinstance(of, int) and of else _cards(n)) if n else "not in your copy"
            rows.append((name, text, not n))
        if u.get("nids") or u.get("cids"):
            found = len(idx.id_cards(u))
            label = f"{name} · by ID" if (u.get("tags") or u.get("decks") or u.get("cards")) else name
            rows.append((label, _cards(found) if found else "not in your copy", not found))
        if u.get("cards"):
            found, total = idx.single_found(u), len(u["cards"])
            label = f"{name} · single cards" if (u.get("tags") or u.get("decks")) else name
            rows.append((label, f"{found:,} of {total:,}" if found else "not in your copy", not found))
    if rest:
        cids = set()
        for u in rest:
            cids |= idx.match(u, swap, doc.get("deck", ""))
        rows.append((f"… {len(rest)} more date{'s' if len(rest) != 1 else ''}", _cards(len(cids)), False))
    return rows


def _later(iso, days):
    try:
        return (datetime.date.fromisoformat(str(iso)) + datetime.timedelta(days=days)).isoformat()
    except ValueError:
        return iso


def my_doc(doc, shift=0, skipped=()):
    """G3, G4: the plan as this follower runs it: every date `shift` days
    later (their due dates, checkpoints, review days and end with them),
    the dates they skip left out. Events are fixed days: they never move.
    The plan itself never changes."""
    skipped = set(skipped or ())
    if not shift and not skipped:
        return doc
    out = dict(doc or {})
    us = []
    for u in units(doc):
        if u["id"] in skipped:
            continue
        v = dict(u)
        if shift:
            for k in ("opens", "due", "check"):
                if v.get(k):
                    v[k] = _later(v[k], shift)
        us.append(v)
    out["units"] = us
    if shift:
        if out.get("end"):
            out["end"] = _later(out["end"], shift)
        if out.get("reviews"):
            out["reviews"] = [dict(r, day=_later(r["day"], shift)) for r in out["reviews"]]
    return out


def unit_total(u):
    """A date's new cards as the plan counts them, before anyone opens it:
    the author's count, single cards, searches and ids (the Worker's
    unitCount)."""
    sn = u.get("sn") if isinstance(u.get("sn"), dict) else {}
    idn = u.get("idn")
    ids = int(idn) if isinstance(idn, int) else len(u.get("nids") or []) + len(u.get("cids") or [])
    return int(u.get("n") or 0) + len(u.get("cards") or []) + sum(int(v or 0) for v in sn.values()) + ids


def week_start(today, offset=0):
    """The Monday of today's week, `offset` weeks on."""
    d = datetime.date.fromisoformat(str(today))
    return (d - datetime.timedelta(days=d.weekday()) + datetime.timedelta(weeks=int(offset))).isoformat()


def week_view(doc, prog, today, start, skipped=()):
    """3.4.1, the Plans tab's week: seven days from `start` (a Monday) of
    my own plan (my_doc), each {day, dow, num, today, past, rest, prep,
    events, units, new, seen}. A unit is {uid, name, total, seen, state}:
    done, open, later, or skip (`skipped`: [unit] from the plan itself,
    shown on the day they'd have opened). Rest: not one of the plan's
    study days and nothing opens. Numbers only; the board escapes names."""
    prog = prog or {}
    pdays = ((doc or {}).get("pace") or {}).get("days")
    pdays = [1 if x else 0 for x in pdays] if isinstance(pdays, list) and len(pdays) == 7 and any(pdays) else [1] * 7
    first = datetime.date.fromisoformat(str(start))
    evs = {}
    for e in (doc or {}).get("events") or []:
        if isinstance(e, dict) and e.get("day"):
            evs.setdefault(str(e["day"]), []).append(str(e.get("name") or "?"))
    by_day = {}
    for u in units(doc):
        by_day.setdefault(str(u["opens"]), []).append((u, False))
    for u in skipped or ():
        if u.get("opens"):
            by_day.setdefault(str(u["opens"]), []).append((u, True))
    out = []
    for i in range(7):
        d = (first + datetime.timedelta(days=i)).isoformat()
        rows = []
        for u, skip in by_day.get(d, []):
            _o, s, t = prog.get(u["id"], [0, 0, 0])
            total = int(t) or unit_total(u)
            state = ("skip" if skip else "later" if d > today
                     else "done" if int(t) and int(s) >= int(t) else "open")
            rows.append({"uid": u["id"], "name": str(u.get("name") or "?"), "total": total,
                         "seen": 0 if skip else int(s), "state": state, "prep": bool(u.get("for"))})
        live = [r for r in rows if r["state"] != "skip"]
        dd = first + datetime.timedelta(days=i)
        out.append({"day": d, "dow": f"{dd:%a}", "num": dd.day, "today": d == today, "past": d < today,
                    "rest": not pdays[i] and not live, "prep": any(r["prep"] for r in live),
                    "events": evs.get(d, []), "units": rows,
                    "new": sum(r["total"] for r in live), "seen": sum(r["seen"] for r in live)})
    return out


def waiting_new(doc, prog, today):
    """G5: new cards of dates opened before today that I haven't seen yet."""
    n = 0
    for u in units(doc):
        if str(u.get("opens") or "9999") < today:
            _o, s, t = prog.get(u["id"], [0, 0, 0])
            n += max(0, int(t) - int(s))
    return n


def prep_for(doc, today):
    """F1: the next event (today or later) that today's dates, or the next
    ones, prep for: {name, day, left}, `left` the prep days after today."""
    evs = {e["id"]: e for e in (doc or {}).get("events") or [] if str(e.get("day") or "") >= today}
    if not evs:
        return None
    us = units(doc)
    now = [u for u in us if u.get("for") in evs and str(u.get("opens") or "") <= today]
    ahead = [u for u in us if u.get("for") in evs and str(u.get("opens") or "") > today]
    pick = (now[-1] if now else ahead[0] if ahead else None)
    if not pick:
        return None
    ev = evs[pick["for"]]
    left = sum(1 for u in us if u.get("for") == ev["id"] and today < str(u.get("opens") or "") <= ev["day"])
    return {"name": ev.get("name") or "?", "day": ev["day"], "left": left, "today": ev["day"] == today}


def opened_by_date(doc, today):
    return [u for u in units(doc) if str(u.get("opens") or "9999") <= today]


def next_unit(doc, today):
    return next((u for u in units(doc) if str(u.get("opens") or "") > today), None)


def open_cards(col, cids, label):
    """Unsuspend the suspended ones among `cids`, as one undo step named
    `label`. Only queue -1 is touched, and never a leech (Anki suspended it
    for a reason); never suspends. Returns how many opened (0: nothing was
    suspended, and no undo step is made)."""
    if not cids:
        return 0
    ids = []
    cl = sorted(int(c) for c in cids)
    for i in range(0, len(cl), 500):
        chunk = ",".join(str(c) for c in cl[i:i + 500])
        ids += col.db.list(
            f"SELECT c.id FROM cards c JOIN notes n ON n.id = c.nid WHERE c.queue = -1 "
            f"AND c.id IN ({chunk}) AND (' ' || lower(n.tags) || ' ') NOT LIKE '% leech %'")
    if not ids:
        return 0
    pos = None
    if hasattr(col, "add_custom_undo_entry"):
        try:
            pos = col.add_custom_undo_entry(label)
        except Exception:
            pos = None
    col.sched.unsuspend_cards(ids)
    if pos is not None and hasattr(col, "merge_undo_entries"):
        try:
            col.merge_undo_entries(pos)
        except Exception:
            pass
    return len(ids)


def holdable(idx, doc, today, swap=None):
    """3.3, "Hold back later dates until their day": the cards of dates
    that haven't opened yet which are active now and never studied (new,
    not suspended, not a leech). A card that is also on an opened date is
    never held. What Follow offers to suspend, once, when asked."""
    opened, later = set(), set()
    for u in units(doc):
        cids = idx.match(u, swap, doc.get("deck", ""))
        (opened if str(u.get("opens") or "") <= today else later).update(cids)
    return {c for c in later - opened if idx.cards[c] == (0, 0) and c not in idx.leech}


def hold_cards(col, cids, label):
    """Suspend these (still new and active) cards as one undo step. Only
    ever called when the person asked, at Follow. Returns how many."""
    if not cids:
        return 0
    ids = []
    cl = sorted(int(c) for c in cids)
    for i in range(0, len(cl), 500):
        chunk = ",".join(str(c) for c in cl[i:i + 500])
        ids += col.db.list(f"SELECT id FROM cards WHERE queue = 0 AND type = 0 AND id IN ({chunk})")
    if not ids:
        return 0
    pos = None
    if hasattr(col, "add_custom_undo_entry"):
        try:
            pos = col.add_custom_undo_entry(label)
        except Exception:
            pos = None
    col.sched.suspend_cards(ids)
    if pos is not None and hasattr(col, "merge_undo_entries"):
        try:
            col.merge_undo_entries(pos)
        except Exception:
            pass
    return len(ids)


def note_ids(idx, unit, plan_deck=""):
    """3.3, C5: the note ids behind a unit's tags and subdecks here, for the
    author's Anki to keep on the plan."""
    got = set()
    for t in unit.get("tags") or []:
        got |= idx.tag_cards(t)
    for d in unit.get("decks") or []:
        got |= idx.deck_cards(d, plan_deck)
    return sorted({idx.guid_of[c] for c in got if c in idx.guid_of})


def search_counts(idx, lean_doc):
    """3.4, D1: {unit id: {search: cards it finds here}} for a plan I write;
    E1: "#ids" is how many cards its pasted ids find."""
    out = {}
    for u in lean_doc.get("units") or []:
        c = {q: len(idx.search_cards(q)) for q in u.get("search") or []}
        if u.get("nids") or u.get("cids"):
            c["#ids"] = len(idx.id_cards(u))
        if c:
            out[u["id"]] = c
    return out


def ids_snapshot(idx, lean_doc, cap=50000):
    """{unit id: [tags, decks, [guid]]} for a plan I write, from my copy;
    at most `cap` ids in all."""
    out, n = {}, 0
    for u in lean_doc.get("units") or []:
        if not (u.get("tags") or u.get("decks")):
            continue  # a date of searches only: its count is enough (search_counts)
        ids = note_ids(idx, u, lean_doc.get("deck", ""))[:max(0, cap - n)]
        n += len(ids)
        out[u["id"]] = [list(u.get("tags") or []), list(u.get("decks") or []), ids]
    return out


def step_label(names):
    """The undo step: "Due Crew: open Renal physiology", or "… open 3 dates"."""
    names = list(names)
    if len(names) == 1:
        return f"Due Crew: open {names[0]}"
    return f"Due Crew: open {len(names)} dates"


# ---- lines only I see ----

def ahead_behind(doc, prog, today):
    """[(kind, segments)]: the next unit already open ("ahead"), and units
    whose due date passed with cards not seen ("behind", newest first, at
    most two). segments are [(text, bold)]."""
    out = []
    nxt = next_unit(doc, today)
    if nxt:
        o, _s, t = prog.get(nxt["id"], [0, 0, 0])
        if t and o >= t:
            out.append(("ahead", [("You opened ", False), (nxt.get("name") or "?", True),
                                  (f" early. Nothing to do on {weekday_or_day(nxt['opens'], today)}.", False)]))
    late = [u for u in units(doc) if u.get("due") and u["due"] < today]
    late.sort(key=lambda u: u["due"], reverse=True)
    n = 0
    for u in late:
        _o, s, t = prog.get(u["id"], [0, 0, 0])
        if t and s < t:
            out.append(("behind", [(u.get("name") or "?", True),
                                   (f" was due {weekday_or_day(u['due'], today)}. "
                                    f"{t - s:,} card{'s' if t - s != 1 else ''} not seen yet.", False)]))
            n += 1
            if n == 2:
                break
    return out


def snapshot(doc):
    """What a change note compares: {unit id: [name, opens]}."""
    return {u["id"]: [str(u.get("name") or ""), str(u.get("opens") or "")] for u in units(doc)}


def change_note(owner, old, doc):
    """"Dre moved Renal pharm to Mon 2 Nov and added Pulm · Asthma." as
    segments, or None. At most two of each kind by name, then a count."""
    new = snapshot(doc)
    moved = [(new[u][0], new[u][1]) for u in new if u in old and old[u][1] != new[u][1]]
    added = [new[u][0] for u in new if u not in old]
    gone = [old[u][0] for u in old if u not in new]
    if not (moved or added or gone):
        return None
    clauses = []

    def names(items, verb, tail=None):
        if len(items) > 2:
            return [(f"{verb} {len(items)} dates", False)]
        segs = [(verb + " ", False)]
        for i, it in enumerate(items):
            if i:
                segs.append((" and ", False))
            name = it[0] if isinstance(it, tuple) else it
            segs.append((name or "?", True))
            if tail:
                segs.append((tail(it), False))
        return segs
    if moved:
        clauses.append(names(moved, "moved", lambda it: f" to {fmt_day(it[1])}"))
    if added:
        clauses.append(names(added, "added"))
    if gone:
        clauses.append(names(gone, "took out"))
    segs = [(f"{owner or '?'} ", False)]
    for i, c in enumerate(clauses):
        if i:
            segs.append((" and " if i == len(clauses) - 1 else ", ", False))
        segs += c
    segs.append((".", False))
    return segs


# ---- the browser: which cards ----

# searches whose answer is this person's own Anki, not the deck: another
# follower's would find something else (deck:current is the browser's default)
_PERSONAL = re.compile(r"(?i)(?:^|[\s(\"-])(?:deck:current|is:(?:due|new|learn|review|suspended|buried|susp)|"
                       r"rated:|prop:|introduced:|added:|edited:|resched:|flag:)")


def shareable_search(q):
    """3.3, C3: a search worth giving a plan (not empty, not about my Anki)."""
    q = str(q or "").strip()
    return bool(q) and not _PERSONAL.search(q)

def card_refs(col, cids):
    """[[note guid, card ord]] for the picked cards: which cards, never text."""
    out = []
    cl = sorted(int(c) for c in cids)
    for i in range(0, len(cl), 500):
        chunk = ",".join(str(c) for c in cl[i:i + 500])
        out += [[str(g), int(o)] for g, o in col.db.all(
            f"SELECT n.guid, c.ord FROM cards c JOIN notes n ON n.id = c.nid WHERE c.id IN ({chunk})")]
    return out


# ---- which of my decks ----

def deck_choices(col):
    """[(did, name)]: normal decks, by name."""
    out = []
    for r in col.decks.all_names_and_ids():
        d = col.decks.get(int(r.id), default=False)
        if d and not d.get("dyn"):
            out.append((int(r.id), str(r.name)))
    return sorted(out, key=lambda x: x[1].lower())


def best_deck(col, doc, choices=None):
    """The deck to run a plan on: the one named like the plan's deck, else
    the top-level deck where the most of the plan is found (with a swap, if
    one lines the tags up). (did, swap) or (None, None)."""
    choices = choices if choices is not None else deck_choices(col)
    want = str((doc or {}).get("deck") or "").lower()
    for did, name in choices:
        if name.lower() == want:
            return did, None
    last = want.split(_SEP)[-1]
    for did, name in choices:
        if name.lower().split(_SEP)[-1] == last and last:
            return did, None
    best, best_n, best_swap = None, 0, None
    for did, name in choices:
        if _SEP in name:
            continue
        idx = DeckIndex(col, did)
        swap = detect_swap(idx, doc)
        n = found_total(idx, doc, swap)
        if n > best_n:
            best, best_n, best_swap = did, n, swap
    return best, best_swap
