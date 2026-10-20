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
import html
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


def unit_sources(unit, deck_id=None, swap=None, pt=None):
    """What a unit matched with when it was applied here: its deck, swap and
    sources. A later change opens only what the new sources add. pt (3.8.1):
    the cards it had then from the plan's own tags (DeckIndex.plan_part), so
    a change to those tags opens just what it adds; a cut's search is the cut's."""
    out = [deck_id, list(swap or []), list(unit.get("tags") or []), list(unit.get("decks") or []),
           [list(c) for c in unit.get("cards") or []]]
    cut_q = {c.get("q") for c in unit.get("cut") or []} if pt is not None else set()
    search = [q for q in unit.get("search") or [] if q not in cut_q]
    if search:
        out.append(search)  # 3.3, C3
    if unit.get("nids") or unit.get("cids"):
        out.append([list(unit.get("nids") or []), list(unit.get("cids") or [])])  # E1
    if unit.get("notes") or unit.get("idr"):
        out.append({"notes": list(unit.get("notes") or []), "idr": [list(r) for r in unit.get("idr") or []]})  # 3.6.5
    if unit.get("ids"):
        out.append({"ids": list(unit["ids"])})  # 3.7.2: C5's note ids, so ones arriving later open what they add
    if pt is not None:
        out.append({"pt": sorted(int(c) for c in pt)})  # 3.8.1
    return out


def unit_sig_v1(unit, deck_id=None, swap=None):
    """The sig before 3.7.2, which left C5's `ids` out (plan_flow._sig
    carries a unit applied under it over once)."""
    return unit_sig({k: v for k, v in unit.items() if k != "ids"}, deck_id, swap)


def unit_sig(unit, deck_id=None, swap=None):
    """What a unit opens on this computer: its sources, the deck it runs on
    and the tag swap. Remembered once applied; a unit whose date moves keeps
    its sig (so moving it later changes nothing), one the author adds cards
    to gets a new one (so the new cards open the next morning)."""
    blob = json.dumps([deck_id, list(swap or []), sorted(str(t).lower() for t in unit.get("tags") or []),
                       sorted(str(d).lower() for d in unit.get("decks") or []),
                       sorted(f"{g}:{o}" for g, o in unit.get("cards") or [])]
                      + ([sorted(unit.get("notes") or []), sorted(f"{g}:{o}" for g, o in unit.get("idr") or [])]
                         if unit.get("notes") or unit.get("idr") else [])
                      + ([sorted(unit["search"])] if unit.get("search") else [])
                      + ([sorted(unit.get("nids") or []), sorted(unit.get("cids") or [])]
                         if unit.get("nids") or unit.get("cids") else [])
                      + ([{"ids": sorted(str(g) for g in unit["ids"])}] if unit.get("ids") else [])
                      # 3.8.1: its cuts, and what the plan's own tags it uses hold (shapes' ptv)
                      + ([{"cut": sorted(f"{str(c.get('tag')).lower()}|{c.get('in')}" for c in unit["cut"])}] if unit.get("cut") else [])
                      + ([{"ptv": unit["ptv"]}] if unit.get("ptv") else []))
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
_STATIC_KEYS = ("leech", "by_deck", "by_ref", "home", "by_tag", "tag_names", "tag_keys", "by_guid", "guid_of", "by_nid", "nid_of", "_searches")


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
               tuple(col.db.first("SELECT count(), max(n.mod), total(n.mod), max(c.id), sum(c.did), sum(c.odid), sum(c.ord) "
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
        self.again = set()   # 3.9.3: in (re)learning and due again today: answered, not through for today
        try:
            day, cut = int(col.sched.today), int(col.sched.day_cutoff)
        except Exception:
            day = cut = None
        home = self.home
        for cid, queue, ctype, due in col.db.all(f"SELECT c.id, c.queue, c.type, c.due FROM cards c {where}"):
            cid = int(cid)
            if cid in home:
                queue, due = int(queue), int(due or 0)
                self.cards[cid] = (queue, int(ctype))
                self.order[cid] = (int(ctype) == 0, due, cid)
                if day is not None and ((queue == 1 and due < cut) or (queue == 3 and due <= day)):
                    self.again.add(cid)
        self.fell_back = set()  # unit ids matched by their note ids (C5)
        self._started = None  # note ids with a card answered: siblings wait on these
        self._before = None  # 3.9.1: (first_seen, the notes started before today), for buried_today
        self._fresh = {}  # a search about my own reviews: this refresh only
        self._ptc = {}  # 3.8.1: what each of a plan's own tags holds here, this refresh

    def _read_static(self, col, tree, where):
        rows = col.db.all(
            "SELECT c.id, CASE WHEN c.odid != 0 THEN c.odid ELSE c.did END, c.ord, n.guid, n.tags, n.id "
            f"FROM cards c JOIN notes n ON n.id = c.nid {where}")
        self.leech = set()   # cids whose note Anki tagged leech: a plan never opens them
        self.by_deck = {}    # did -> [cid]
        self.by_ref = {}     # (guid, ord) -> cid
        self.home = set()    # the cids in this deck and its subdecks
        self.by_nid = {}     # E1: note id -> [cid]
        self.nid_of = {}     # cid -> note id
        by_tag = {}          # lowercased tag -> [cid]
        self.tag_names = {}  # lowercased tag -> as written
        treeset = set(tree)
        for cid, home, ord_, guid, tags, nid in rows:
            if int(home) not in treeset:
                continue
            cid = int(cid)
            self.home.add(cid)
            self.by_nid.setdefault(int(nid), []).append(cid)
            self.nid_of[cid] = int(nid)
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
        """3.3, C3: an Anki search, run by this collection, kept to this deck.
        One about the deck is kept while the notes are; one about my own
        reviews (is:due, rated:, prop:…, typed into a plan's Text) changes
        as I study, so it's run again each refresh."""
        kept = self._fresh if _PERSONAL.search(str(q)) else self._searches
        if q not in kept:
            try:
                found = {int(c) for c in self.col.find_cards(str(q))}
            except Exception:
                found = set()  # a search this Anki can't read finds nothing
            kept[q] = {c for c in found if c in self.cards}
        return kept[q]

    def match(self, unit, swap=None, plan=""):
        """{cid} for one unit on this deck. plan: the plan's doc, or the name
        of its deck. With the doc (3.8.1), a tag of the plan's own reads what
        that tag holds, single cards and all, and a cut reads its tag kept to
        one; without it, they're read as the Anki tag and the cut's search."""
        doc = plan if isinstance(plan, dict) else None
        plan_deck = str(doc.get("deck") or "") if doc is not None else plan
        own = plan_tag_map(doc)
        out = set()
        missing = False
        for t in unit.get("tags") or []:
            pt = own.get(str(t).lower())
            got = self.plan_tag_cards(doc, pt, swap) if pt else self.tag_cards(swapped(t, swap))
            missing = missing or not got
            out |= got
        cut_q = set()
        for c in unit.get("cut") or []:
            pt = own.get(("id", c.get("in")))
            if not pt:
                continue  # its tag went: its search reads it, as an older add-on does
            cut_q.add(c.get("q"))
            got = self.tag_cards(swapped(c.get("tag"), swap))
            missing = missing or not got
            out |= got & self.plan_tag_cards(doc, pt, swap)
        for d in unit.get("decks") or []:
            got = self.deck_cards(d, plan_deck)
            missing = missing or not got
            out |= got
        if missing and unit.get("ids"):
            # 3.3, C5: a tag this copy names differently (a newer version of the deck):
            # the author's note ids behind the date find its cards
            by_id = {c for g in unit["ids"] for c in self.by_guid.get(g, ())}
            if by_id - out:
                self.fell_back.add(unit.get("id"))
                out |= by_id
        for q in unit.get("search") or []:
            if q not in cut_q:
                out |= self.search_cards(q)
        for g, o in unit.get("cards") or []:
            cid = self.by_ref.get((str(g), int(o)))
            if cid is not None:
                out.add(cid)
        out |= self.id_cards(unit)
        return out

    def plan_tag_cards(self, doc, tag, swap=None):
        """3.8.1: the cards one of the plan's own tags holds here: every card
        of the notes it holds whole (as its Anki tag does) and just the
        single cards it names (Anki's tag is on their notes too)."""
        key = (str(tag.get("id")), json.dumps({k: tag.get(k) for k in ("notes", "cards", "tags", "decks", "search")},
                                               sort_keys=True), tuple(swap or ()))
        got = self._ptc.get(key)
        if got is None:
            got = {c for n in tag_whole_notes(self, doc, tag, swap) for c in self.by_nid.get(n, ())}
            for g, o in tag.get("cards") or []:
                cid = self.by_ref.get((str(g), int(o)))
                if cid is not None:
                    got.add(cid)
            self._ptc[key] = got
        return got

    def plan_part(self, unit, doc, swap=None):
        """3.8.1: the cards a unit has from the plan's own tags now (the tags
        it names, its cuts), or None when it has none: kept when it opens,
        so a later change to those tags opens just what the change adds."""
        own = plan_tag_map(doc)
        used = [own[str(t).lower()] for t in unit.get("tags") or [] if str(t).lower() in own]
        cuts = [(c, own[("id", c.get("in"))]) for c in unit.get("cut") or [] if ("id", c.get("in")) in own]
        if not used and not cuts:
            return None
        out = set()
        for pt in used:
            out |= self.plan_tag_cards(doc, pt, swap)
        for c, pt in cuts:
            out |= self.tag_cards(swapped(c.get("tag"), swap)) & self.plan_tag_cards(doc, pt, swap)
        return out

    def pasted_cards(self, unit):
        """E1: the cards of a date's pasted note ids and card ids, in this deck.
        The same in copies of one import; a copy made otherwise has its own."""
        out = set()
        for n in unit.get("nids") or []:
            out.update(c for c in self.by_nid.get(int(n), ()) if c in self.cards)
        for c in unit.get("cids") or []:
            if int(c) in self.cards:
                out.add(int(c))
        return out

    def id_cards(self, unit):
        """Every exact pick but single cards: pasted ids, the cards the author's
        Anki found them to be (3.6.5, `idr`: guid + card number, so a copy
        whose ids differ still finds them), and notes by guid (`notes`)."""
        out = self.pasted_cards(unit)
        for g, o in unit.get("idr") or []:
            cid = self.by_ref.get((str(g), int(o)))
            if cid is not None:
                out.add(cid)
        for g in unit.get("notes") or []:
            out.update(self.by_guid.get(str(g), ()))
        return out

    def exact_missing(self, unit):
        """3.6.5: (missing, of) for a date's exact picks by guid (single cards
        and notes): the ones this copy doesn't have, for the plan card's note."""
        refs = [(str(g), int(o)) for g, o in unit.get("cards") or []]
        notes = [str(g) for g in unit.get("notes") or []]
        missing = sum(1 for r in refs if r not in self.by_ref) + sum(1 for g in notes if g not in self.by_guid)
        return missing, len(refs) + len(notes)

    def single_found(self, unit):
        return sum(1 for g, o in unit.get("cards") or [] if (str(g), int(o)) in self.by_ref)

    # -- numbers --

    def started(self):
        """Note ids with a card answered at least once."""
        if self._started is None:
            nid_of = self.nid_of
            self._started = {nid_of[c] for c, (_q, t) in self.cards.items() if t != 0}
        return self._started

    def unseen(self, cids):
        """3.8.0: the cards counts() doesn't call seen: what's left to see."""
        started, nid_of = self.started(), self.nid_of
        return {c for c in cids if self.cards[c][1] == 0 and not (self.cards[c][0] != -1 and nid_of.get(c) in started)}

    def counts(self, cids):
        """[opened, seen, total]: opened = not suspended, seen = answered at
        least once (Anki's own "not new"), or a new sibling of a card that
        was: Anki buries siblings and spaces them out, so a date whose notes
        are all started is done, and never behind for them."""
        opened = seen = 0
        started, nid_of = self.started(), self.nid_of
        for cid in cids:
            queue, ctype = self.cards[cid]
            opened += queue != -1
            seen += ctype != 0 or (queue != -1 and nid_of.get(cid) in started)
        return [opened, seen, len(cids)]

    def siblings(self, cids):
        """(new cards counted as seen for a started note, how many of them
        Anki has buried today)."""
        n = buried = 0
        started, nid_of = self.started(), self.nid_of
        for cid in cids:
            queue, ctype = self.cards[cid]
            if ctype == 0 and queue != -1 and nid_of.get(cid) in started:
                n += 1
                buried += queue in (-2, -3)
        return n, buried

    def buried_today(self, cids, first_seen):
        """New siblings Anki buried today whose note was started today: today's
        own progress. A note started before today had them counted as seen
        already; a review card of it due today buries them too, and that
        burial isn't today's progress (nor makes them behind). first_seen:
        {cid: days ago its first answer was} (0 today), read as it is at the
        first ask. 3.9.1: the notes started before today are found once per
        index and first_seen, not once per date (session_view asks for each:
        a pass over the whole deck every time, 171 ms a refresh on 35,000 cards)."""
        if self._before is None or self._before[0] is not first_seen:
            self._before = (first_seen, {self.nid_of[c] for c, (_q, t) in self.cards.items()
                                         if t != 0 and first_seen.get(c) != 0})
        before = self._before[1]
        started, nid_of = self.started(), self.nid_of
        return sum(1 for c in cids
                   if self.cards[c][1] == 0 and self.cards[c][0] in (-2, -3)
                   and nid_of.get(c) in started and nid_of.get(c) not in before)

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


def tree_rows(idx):
    """(tags, decks) of a deck as they go up for the builder (DeckIndex.tree),
    each path one printable line of at most 200 characters (the server's)."""
    tags, decks = idx.tree()
    ok = lambda path: len(path) <= 200 and path.isprintable()
    return [t for t in tags if ok(t[0])], [d for d in decks if ok(d[0])]


def tree_hash(deck, tags, decks):
    """3.8.1: what a deck's tree was when this computer last sent it."""
    blob = json.dumps([str(deck), tags, decks], separators=(",", ":"))
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


def _qid(path):
    """A question bank's id: a leaf that's only digits.
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
    return {u["id"]: idx.match(u, swap, doc) for u in units(doc)}


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


def _missing(idx, u, of, n, swap=None, doc=None):
    """The cards of a date the author has and this copy doesn't, each
    counted once. The author's count adds up each tag's and subdeck's cards
    (the builder's, from the tag tree: a card under two of a date's tags,
    a video's and a system's, counts twice); this copy counted the same way
    says how many are missing, then each card once as the date's tags here
    hold them (3.9.3, Sam's pick: "14 of 28" when nothing was missing)."""
    deck = str((doc or {}).get("deck") or "")
    mine = (sum(len(idx.tag_cards(swapped(t, swap))) for t in u.get("tags") or [])
            + sum(len(idx.deck_cards(d, deck)) for d in u.get("decks") or []))
    gap = max(0, int(of) - mine)
    return round(gap * n / mine) if mine > n else gap


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
            n = len(idx.match(dict(u, cards=[], nids=[], cids=[], notes=[], idr=[]), swap, doc))
            of = u.get("n")  # the author's count, when the builder saved one
            text = (f"{n:,} of {n + _missing(idx, u, of, n, swap, doc):,}" if isinstance(of, int) and of else _cards(n)) \
                if n else "not in your copy"
            rows.append((name, text, not n))
        if u.get("nids") or u.get("cids") or u.get("notes"):
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
            cids |= idx.match(u, swap, doc)
        rows.append((f"… {len(rest)} more date{'s' if len(rest) != 1 else ''}", _cards(len(cids)), False))
    return rows


def _later(iso, days):
    try:
        return (datetime.date.fromisoformat(str(iso)) + datetime.timedelta(days=days)).isoformat()
    except ValueError:
        return iso


def my_doc(doc, shift=0, skipped=(), moved=None):
    """G3, G4: the plan as this follower runs it: every date `shift` days
    later (their due dates, checkpoints, review days and end with them),
    the dates they skip left out, and (3.7.6) a date I moved, that many
    days later again, marked `_moved`. Events are fixed days: they never
    move. The plan itself never changes."""
    skipped = set(skipped or ())
    moved = {k: int(v) for k, v in (moved or {}).items() if isinstance(v, int) and v > 0}
    if not shift and not skipped and not moved:
        return doc
    out = dict(doc or {})
    us = []
    for u in units(doc):
        if u["id"] in skipped:
            continue
        v = dict(u)
        by = shift + moved.get(u["id"], 0)
        if by:
            for k in ("opens", "due", "check"):
                if v.get(k):
                    v[k] = _later(v[k], by)
        if moved.get(u["id"]):
            v["_moved"] = moved[u["id"]]
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


def load(idx, doc, swap=None):
    """3.7.81, plan load: {unit id: [seen, open, locked]} for my own dates
    (doc is my_doc: my days), each card counted on its earliest date only
    (keeping to the plan, I meet it there first) and a suspended leech left
    out (the plan never opens one). seen as counts() says it (a new
    sibling of a started note too); open is unsuspended and not seen, so in
    my Anki now; locked is still suspended: new to me on its day."""
    ms = unit_matches(idx, doc, swap)
    started, nid_of = idx.started(), idx.nid_of
    before, out = set(), {}
    for u in sorted(units(doc), key=lambda x: str(x.get("opens") or "")):
        mine = ms.get(u["id"]) or set()
        s_ = o_ = l_ = 0
        for cid in mine - before:
            queue, ctype = idx.cards[cid]
            if queue == -1 and cid in idx.leech and ctype == 0:
                continue
            if ctype != 0 or (queue != -1 and nid_of.get(cid) in started):
                s_ += 1
            elif queue == -1:
                l_ += 1
            else:
                o_ += 1
        before |= mine
        out[u["id"]] = [s_, o_, l_]
    return out


def load_ask(ld, day, today):
    """What a date asks of me on its day: ahead, what's still locked (new to
    me then); today and before, what I haven't seen."""
    s_, o_, l_ = ld
    return l_ if day > today else o_ + l_


def week_view(doc, prog, today, start, skipped=(), ld=None, shut=()):
    """3.5.0, the Plans tab's week: seven days from `start` (a Monday) of
    my own plan (my_doc), each {day, dow, num, today, past, rest, prep,
    events, units, new, seen}. A unit is {uid, name, total, seen, state}:
    done, open, later, or skip (`skipped`: [unit] from the plan itself,
    shown on the day they'd have opened). Rest: not one of the plan's
    study days and nothing opens. Numbers only; the board escapes names.
    shut (3.8.1): the ids of dates that opened here and have none of their
    cards open now (Edit › Undo), or at my own pace aren't opened yet:
    marked `shut`, so the day offers Open now."""
    prog = prog or {}
    shut = set(shut or ())
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
                         "seen": 0 if skip else int(s), "state": state,
                         "prep": bool(u.get("for")) and not reinforces(doc, u),  # 3.8.1: after its event, not prep
                         "moved": bool(u.get("_moved")) and not skip,  # 3.7.6
                         "what": topic_view([u])})  # P7; 3.8.0: each name with its place, for its click
            rm = topic_remarks(doc, [u])
            if rm:
                rows[-1]["rm"] = rm  # 3.8.1: the authors' notes under the topics they name
            todo = [x for x in u.get("todo") or [] if isinstance(x, dict)]
            if todo and not skip:
                rows[-1]["todo"] = todo  # round five: its authors' lines, in its day's details
            if u.get("for") and not skip and for_words(doc, u):
                rows[-1]["ev"] = for_words(doc, u)  # 3.8.1: "for Heme quiz", or "after Heme quiz"
            if not skip and state != "later" and u["id"] in shut:
                rows[-1]["shut"] = True  # 3.8.1
            if ld and u["id"] in ld and not skip:  # 3.7.81: plan load
                rows[-1]["ld"] = list(ld[u["id"]])
                rows[-1]["ask"] = load_ask(ld[u["id"]], d, today)
        live = [r for r in rows if r["state"] != "skip"]
        dd = first + datetime.timedelta(days=i)
        out.append({"day": d, "dow": f"{dd:%a}", "num": dd.day, "today": d == today, "past": d < today,
                    "rest": not pdays[i] and not live, "prep": any(r["prep"] for r in live),
                    "events": evs.get(d, []), "units": rows,
                    "new": sum(r["total"] for r in live), "seen": sum(r["seen"] for r in live),
                    # 3.7.81: the day's size and what it asks, when the load is counted
                    "size": sum(sum(r["ld"]) for r in live if "ld" in r) if any("ld" in r for r in live) else None,
                    "ask": sum(r["ask"] for r in live if "ask" in r)})
    return out


def waiting_new(doc, prog, today):
    """G5: new cards of dates opened before today that I haven't seen yet."""
    n = 0
    for u in units(doc):
        if str(u.get("opens") or "9999") < today:
            o, s, _t = prog.get(u["id"], [0, 0, 0])
            n += max(0, int(o) - int(s))  # opened and not seen: an even date's later slices are shut on purpose
    return n


def prep_for(doc, today):
    """F1: the next event (today or later) that today's dates, or the next
    ones, prep for: {name, day, left}, `left` the prep days after today."""
    evs = {e["id"]: e for e in (doc or {}).get("events") or [] if str(e.get("day") or "") >= today}
    if not evs:
        return None
    us = units(doc)
    now = [u for u in us if u.get("for") in evs and str(u.get("opens") or "") <= today]
    ahead = [u for u in us if u.get("for") in evs and str(u.get("opens") or "") > today
             and not reinforces(doc, u)]  # 3.8.1: a date after its event doesn't prep for it
    pick = (now[-1] if now else ahead[0] if ahead else None)
    if not pick:
        return None
    ev = evs[pick["for"]]
    # days, not dates: a day can hold several dates
    left = len({str(u.get("opens")) for u in us if u.get("for") == ev["id"] and today < str(u.get("opens") or "") <= ev["day"]})
    return {"name": ev.get("name") or "?", "day": ev["day"], "left": left, "today": ev["day"] == today}


QUIZ_DAYS = 3  # Study for a quiz shows from this many days before it


def quiz(doc, today, prog=None, days=QUIZ_DAYS):
    """3.8.1 (plans, rethought), Study for a quiz: the next event, today or
    within `days`, with dates that prep for it (`for` it, not after it) and
    have cards opened here: {id, name, day, units: [date ids], open: n}, `n`
    their opened cards (prog: {unit id: [opened, seen, total]}). Events never
    move; my own (shifted) dates decide what preps. None otherwise."""
    try:
        t = datetime.date.fromisoformat(today)
    except (TypeError, ValueError):
        return None
    prog = prog or {}
    for e in sorted((e for e in (doc or {}).get("events") or [] if isinstance(e, dict) and e.get("id")),
                    key=lambda e: str(e.get("day") or "")):
        try:
            d = datetime.date.fromisoformat(str(e.get("day") or ""))
        except ValueError:
            continue
        if not 0 <= (d - t).days <= days:
            continue
        us = [u for u in units(doc) if u.get("for") == e["id"] and not reinforces(doc, u)
              and str(u.get("opens") or "9999") <= today]
        n = sum(int((prog.get(u["id"]) or [0])[0] or 0) for u in us)
        if us and n:
            return {"id": str(e["id"]), "name": str(e.get("name") or "the quiz"), "day": str(e["day"]),
                    "units": [u["id"] for u in us], "open": n}
    return None


def event_of(doc, u):
    """The event a date preps for (its `for` is the event's id), or None."""
    want = (u or {}).get("for")
    if not want:
        return None
    return next((e for e in (doc or {}).get("events") or [] if isinstance(e, dict) and e.get("id") == want), None)


def opened_by_date(doc, today):
    return [u for u in units(doc) if str(u.get("opens") or "9999") <= today]


def late_start(doc, today):
    """3.7.6, following after dates have passed: {passed: [unit ids before
    today], shift: days my dates would run later to start at the first,
    ends: my last date then, after: (event name, day) that last date falls
    after, or None}. Pure."""
    us = units(doc)
    passed = [u["id"] for u in us if str(u.get("opens") or "9999") < today]
    first = min((str(u["opens"]) for u in us if u.get("opens")), default=None)
    if not passed or not first:
        return {"passed": [], "shift": 0, "ends": None, "after": None}
    shift = (datetime.date.fromisoformat(today) - datetime.date.fromisoformat(first)).days
    last = max(str(u.get("due") or u["opens"]) for u in us if u.get("opens"))
    ends = _later(last, shift)
    evs = [(str(e.get("name") or "the exam"), str(e["day"])) for e in (doc or {}).get("events") or []
           if isinstance(e, dict) and e.get("day")]
    end = (doc or {}).get("end")
    if end:
        evs.append(("the plan's end", str(end)))
    after = max((x for x in evs if x[1] < ends and x[1] >= last), key=lambda x: x[1], default=None)
    return {"passed": passed, "shift": shift, "ends": ends, "after": after}


def next_unit(doc, today):
    return next((u for u in units(doc) if str(u.get("opens") or "") > today), None)


def open_counts(col, cids):
    """3.8.0, Browse's open sheet: of these cards, {"open": suspended ones that
    would open, "already": open now, "leech": suspended leeches, which stay}."""
    out = {"open": 0, "already": 0, "leech": 0}
    cl = sorted({int(c) for c in cids})
    for i in range(0, len(cl), 500):
        chunk = ",".join(str(c) for c in cl[i:i + 500])
        for queue, leech in col.db.all(
                f"SELECT c.queue, (' ' || lower(n.tags) || ' ') LIKE '% leech %' FROM cards c JOIN notes n ON n.id = c.nid "
                f"WHERE c.id IN ({chunk})"):
            key = "already" if int(queue) != -1 else "leech" if leech else "open"
            out[key] += 1
    return out


def first_in_line(col, cids):
    """3.8.0: these cards' new ones to the front of Anki's line of new cards,
    in the order they had (Anki's Reposition, shifting the rest along).
    Inside the caller's undo step. Returns how many moved."""
    cl = sorted(int(c) for c in cids)
    rows = []
    for i in range(0, len(cl), 500):
        chunk = ",".join(str(c) for c in cl[i:i + 500])
        rows += col.db.all(f"SELECT id, due FROM cards WHERE type = 0 AND queue = 0 AND id IN ({chunk})")
    ids = [int(c) for c, _d in sorted(rows, key=lambda r: (r[1], r[0]))]
    if not ids or not hasattr(col.sched, "reposition_new_cards"):
        return 0
    col.sched.reposition_new_cards(card_ids=ids, starting_from=0, step_size=1, randomize=False, shift_existing=True)
    return len(ids)


def openable_ids(col, cids):
    """The ids among `cids` that open_cards would open: suspended, not a leech."""
    ids = []
    cl = sorted(int(c) for c in cids or ())
    for i in range(0, len(cl), 500):
        chunk = ",".join(str(c) for c in cl[i:i + 500])
        ids += col.db.list(
            f"SELECT c.id FROM cards c JOIN notes n ON n.id = c.nid WHERE c.queue = -1 "
            f"AND c.id IN ({chunk}) AND (' ' || lower(n.tags) || ' ') NOT LIKE '% leech %'")
    return [int(c) for c in ids]


def open_cards(col, cids, label, dry=False, first=False):
    """Unsuspend the suspended ones among `cids`, as one undo step named
    `label`. Only queue -1 is touched, and never a leech (Anki suspended it
    for a reason); never suspends. Returns how many opened (0: nothing was
    suspended, and no undo step is made). dry (3.7.3): how many it would.
    first (3.8.0): and put them first in Anki's line of new cards."""
    if not cids:
        return 0
    ids = openable_ids(col, cids)
    if not ids or dry:
        return len(ids)
    pos = None
    if hasattr(col, "add_custom_undo_entry"):
        try:
            pos = col.add_custom_undo_entry(label)
        except Exception:
            pos = None
    col.sched.unsuspend_cards(ids)
    if first:
        first_in_line(col, ids)
    if pos is not None and hasattr(col, "merge_undo_entries"):
        try:
            col.merge_undo_entries(pos)
        except Exception:
            pass
    return len(ids)


def holdable(idx, doc, today, swap=None, applied=None, own=False, kept=None):
    """3.3, "Hold back later dates until their day": the cards of dates
    that haven't opened yet which are active now and never studied (new,
    not suspended, not a leech). A card that is also on an opened date is
    never held. A date already applied here (opened early, C2) counts as
    opened. What Follow offers to suspend, once, when asked. own (3.8.0,
    at my own pace): a date is opened only when I opened it, whatever its day.
    kept (3.8.1): cards a date opened here (what it matched when it opened,
    plan_flow._opened_cids): never held, even when the author has since
    moved one to a later date."""
    applied = applied or {}
    opened, later = set(kept or ()), set()
    for u in units(doc):
        cids = idx.match(u, swap, doc)
        have = applied.get(u["id"])
        done = isinstance(have, str) and not have.startswith("skip:")
        (opened if done or (not own and str(u.get("opens") or "") <= today) else later).update(cids)
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


def dates_with(idx, doc, cids, swap=None):
    """3.8.0, Browse › Show on my plan: the dates of a plan (my days) whose
    cards include any of `cids`, in plan order."""
    want = {int(c) for c in cids}
    return [u for u in units(doc) if want & idx.match(u, swap, doc or {})]


def note_ids(idx, unit, plan=""):
    """3.3, C5: the note ids behind a unit's tags and subdecks here, for the
    author's Anki to keep on the plan; 3.8.1, and its cuts' (plan: the doc)."""
    plan_deck = str(plan.get("deck") or "") if isinstance(plan, dict) else plan
    got = set()
    for t in unit.get("tags") or []:
        got |= idx.tag_cards(t)
    for d in unit.get("decks") or []:
        got |= idx.deck_cards(d, plan_deck)
    if unit.get("cut") and isinstance(plan, dict):
        got |= idx.match({"cut": unit["cut"]}, None, plan)
    return sorted({idx.guid_of[c] for c in got if c in idx.guid_of})


def _word(seg):
    """A tag part, readable: "05_Elimination_Kinetics" reads "Elimination
    Kinetics", "#Videos" reads "Videos" (builder.js Tags.word, the order number off)."""
    s = re.sub(r"^[#^$!]+", "", str(seg))
    s = re.sub(r"(?i)^AK_", "", s)
    s = re.sub(r"(?i)_v\d+$", "", s)
    s = re.sub(r"\s+", " ", s.replace("_", " ")).strip()
    m = re.match(r"^0*\d+\s*[.)-]?\s+(\S.*)$", s)
    return (m.group(1) if m else s) or str(seg)


def topic_items(us):
    """3.8.0: the topics of one date or several (the Today box), each with
    what it stands for: [[group, name, sources]], one per group and name,
    in the order the names first appear. Groups as the site's print list
    has them: each tag under the first #/^ part after its root (a video
    series, a book), named readably; subdecks by name; searches, picked
    notes and single cards as counts. sources is unit-shaped (tags, decks,
    search, the picks), so a click on a name finds its cards here with
    DeckIndex.match."""
    items, at = [], {}

    def put(g, x, src):
        if (g, x) not in at:
            at[(g, x)] = len(items)
            items.append([g, x, {}])
        have = items[at[(g, x)]][2]
        for k, v in src.items():
            got = have.setdefault(k, [])
            got += [y for y in v if y not in got]
    for u in us:
        for t in u.get("tags") or []:
            segs = str(t).split(_SEP)
            ri = next((i for i, x in enumerate(segs) if i > 0 and x[:1] in "#^"), -1)
            put(_word(segs[ri]) if 0 <= ri < len(segs) - 1 else "", _word(segs[-1]), {"tags": [t]})
        for d in u.get("decks") or []:
            put("", _word(str(d).split(_SEP)[-1]), {"decks": [d]})
        cut_q = set()
        for c in u.get("cut") or []:
            if not c.get("nm"):
                continue  # its tag went: its search names it
            cut_q.add(c.get("q"))
            segs = str(c.get("tag")).split(_SEP)
            ri = next((i for i, x in enumerate(segs) if i > 0 and x[:1] in "#^"), -1)
            put(_word(segs[ri]) if 0 <= ri < len(segs) - 1 else "", f"{_word(segs[-1])} \u00b7 {c['nm']}",
                {"cut": [dict(c)], "search": [c.get("q")]})  # 3.8.1: "Cephalosporins · SLG 12"
        for q in u.get("search") or []:
            if q in cut_q:
                continue
            put("Search", str(q)[:40] + ("…" if len(str(q)) > 40 else ""), {"search": [q]})
        named = _pick_items(u)  # 3.8.1: "Herpes Viruses · 88 picked", when this copy has named them
        for g, x, src in named:
            put(g, x, src)
        notes = len(u.get("notes") or []) + len(u.get("nids") or [])
        if notes and not named:
            put("Picked by ID", f"{notes:,} note{'s' if notes != 1 else ''}",
                {k: list(u[k]) for k in ("notes", "nids", "idr") if u.get(k)})
        singles = len(u.get("cids") or []) + len(u.get("cards") or [])
        if singles and not named:
            put("Picked", f"{singles:,} single card{'s' if singles != 1 else ''}",
                {k: list(u[k]) for k in ("cards", "cids") if u.get(k)})
    return items


def topic_view(us):
    """[[group, [[name, i]]]]: topic_items grouped for the page, each name
    with its place in topic_items, which the board's click sends."""
    groups = {}
    for i, (g, x, _src) in enumerate(topic_items(us)):
        groups.setdefault(g, []).append([x, i])
    return [[g, xs] for g, xs in groups.items()]


def topics(unit):
    """3.6.5, P7: [[group, [topic]]] for a date (topic_items, names only)."""
    return [[g, [x for x, _i in xs]] for g, xs in topic_view([unit])]


def parts(idx, unit, swap=None, plan=""):
    """Due: [[group, seen, total, back later today]] for a date's resources here, grouped as
    `topics` groups its tags (a video series, a book); what else it opens
    (subdecks, searches, picks) is "Other". [] when there's one group or
    none: then the date's own numbers say it all."""
    groups = {}
    own = plan_tag_map(plan) if isinstance(plan, dict) else {}
    for t in unit.get("tags") or []:
        segs = str(t).split(_SEP)
        ri = next((i for i, x in enumerate(segs) if i > 0 and x[:1] in "#^"), -1)
        g = _word(segs[ri]) if 0 <= ri < len(segs) - 1 else ""
        groups.setdefault(g, set()).update(idx.match({"tags": [t]}, swap, plan))
    for c in unit.get("cut") or []:  # 3.8.1: a video kept to an SLG counts in the video's group
        if ("id", c.get("in")) not in own:
            continue
        segs = str(c.get("tag")).split(_SEP)
        ri = next((i for i, x in enumerate(segs) if i > 0 and x[:1] in "#^"), -1)
        g = _word(segs[ri]) if 0 <= ri < len(segs) - 1 else ""
        groups.setdefault(g, set()).update(idx.match({"cut": [c]}, swap, plan))
    rest = idx.match(unit, swap, plan) - set().union(*groups.values()) if groups else set()
    if rest:
        groups.setdefault("", set()).update(rest)
    named = [(g, c) for g, c in groups.items() if c]
    if len(named) < 2:
        return []
    out = []
    for g, cids in named:
        _o, seen, total = idx.counts(cids)
        out.append([g or "Other", seen, total, len(cids & idx.again)])  # 3.9.3: and back later today
    return out


def topics_line(us):
    """P7: one line for the Today box, today's dates' topics together."""
    return " · ".join((f"{g}: " if g else "") + ", ".join(x for x, _i in xs) for g, xs in topic_view(us))


# ---- 3.8.1: what a date's picked cards are, and the authors' notes on its topics ----

PICK_KEYS = ("cards", "notes", "nids", "cids", "idr")
_NOT_A_RESOURCE = ("leech", "marked")


def picks(unit):
    """3.8.1: a date's picked cards as sources DeckIndex.match reads (single
    cards, notes, pasted ids and their refs); {} for a date with none."""
    return {k: list(unit[k]) for k in PICK_KEYS if unit.get(k)}


def _resource_at(segs):
    """The place of a tag's first #/^ part after its root (a video series, a
    book), as topic_items groups; -1 for none."""
    return next((i for i, x in enumerate(segs) if i > 0 and x[:1] in "#^"), -1)


_TAGS_OF = ("#tags of each card",)  # a key no search is: kept with the index's searches


def _tags_of(idx):
    """{cid: [lowercased tag]}: each card's own tags, read once and kept with
    the deck's searches, which go when its notes change."""
    kept = idx._searches.get(_TAGS_OF)
    if kept is None:
        kept = {}
        for low, lst in idx.by_tag.items():
            for c in lst:
                kept.setdefault(c, []).append(low)
        idx._searches[_TAGS_OF] = kept
    return kept


def pick_labels(idx, cids, most=3):
    """3.8.1: the deck tags a set of cards sits under, [[path, n]] (at most
    `most`): the tag covering the most of them, the deepest of those, a tag
    under a #/^ resource part read from that part down (so a series' root
    never names them); then the same for what's left. n counts the cards it
    names that no label before it did. Paths as this copy writes them.
    Question-id tags (a last part of digits), Anki's leech and marked, and
    the plans' own DueCrew tags never name anything. Pure over the index:
    only the tags these cards carry (each card's, kept with the deck's notes)."""
    left = {int(c) for c in cids}
    if not left:
        return []
    tags_of, hits = _tags_of(idx), {}
    for c in left:
        for low in tags_of.get(c, ()):
            hits.setdefault(low, set()).add(c)
    cover, spelled, res = {}, {}, {}
    for low, hit in hits.items():
        if low in _NOT_A_RESOURCE or low == "duecrew" or low.startswith("duecrew::"):
            continue
        parts, lparts = idx.tag_names[low].split(_SEP), low.split(_SEP)
        if parts[-1].isdigit() or len(parts) != len(lparts):
            continue  # a question's id: not a resource
        ri = _resource_at(parts)
        for n in range(max(ri, 0) + 1, len(parts) + 1):
            key = _SEP.join(lparts[:n])
            if len(key) > 200:
                break  # longer than the server keeps: a shallower one names it
            got = cover.get(key)
            if got is None:
                cover[key] = set(hit)
                spelled[key] = _SEP.join(parts[:n])
                res[key] = ri > 0
            else:
                got |= hit
    out = []
    while cover and len(out) < most:
        key = min(cover, key=lambda k: (-len(cover[k]), not res[k], -k.count(_SEP), k))
        took = cover.pop(key)
        out.append([spelled[key], len(took)])
        for k in list(cover):
            cover[k] -= took
            if not cover[k]:
                del cover[k]
    return out


def with_picks(doc, labels):
    """3.8.1: a copy of the doc whose dates carry their picks' labels here
    (`_pl`; labels: {unit id: [[path, n], ...]}, plan_flow.pick_names), for
    topic_items; the doc itself when there are none."""
    if not labels or not doc:
        return doc
    return dict(doc, units=[dict(u, _pl=labels[u["id"]]) if isinstance(u, dict) and u.get("id") in labels else u
                            for u in doc.get("units") or []])


def _pick_items(u):
    """3.8.1: a date's picked cards as topics, by the deck tags they sit under
    in this copy (`_pl`, set by plan_flow from pick_labels): "Herpes Viruses ·
    88 picked", grouped as a tag of that series is, then "12 more picked" for
    the ones under none of them. [] without `_pl`: the counts, as before."""
    src = picks(u)
    labels = [x for x in u.get("_pl") or [] if isinstance(x, (list, tuple)) and len(x) == 2]
    if not src or not labels:
        return []
    out, named = [], [str(p) for p, _n in labels if p]
    for p, n in labels:
        if p:
            segs = str(p).split(_SEP)
            ri = _resource_at(segs)
            out.append((_word(segs[ri]) if 0 <= ri < len(segs) - 1 else "",
                        f"{_word(segs[-1])} · {int(n):,} picked", dict(src, _in=[str(p)])))
        elif int(n) > 0:
            out.append(("", f"{int(n):,} more picked", dict(src, _out=named)))
    return out


def topic_cards(idx, src, swap=None, plan=""):
    """3.8.1: the cards one topic (topic_items' sources) stands for here: a
    picked resource's are the date's picks under its tag (`_in`, this copy's
    path), the rest the picks under none of them (`_out`)."""
    cids = idx.match(src, swap, plan)
    if src.get("_in"):
        cids &= set().union(*(idx.tag_cards(p) for p in src["_in"]))
    if src.get("_out"):
        cids -= set().union(*(idx.tag_cards(p) for p in src["_out"]))
    return cids


def topic_remarks(doc, us):
    """3.8.1: [[i, text]]: the authors' notes on a tag (the doc's `remarks`),
    each with the place in topic_items(us) of a topic that names that tag or
    one under it (a deck tag, a cut's tag or its plan tag, a plan tag). Names
    and the authors' words; the board escapes them."""
    rs = [(str(r.get("tag")).lower(), str(r.get("text") or "")) for r in (doc or {}).get("remarks") or []
          if isinstance(r, dict) and r.get("tag") and r.get("text")]
    if not rs:
        return []
    own = plan_tag_map(doc)
    out = []
    for i, (_g, _x, src) in enumerate(topic_items(us)):
        paths = [str(t).lower() for t in list(src.get("tags") or []) + list(src.get("_in") or [])]
        for c in src.get("cut") or []:
            paths.append(str(c.get("tag")).lower())
            pt = own.get(("id", c.get("in")))
            if pt:
                paths.append(tag_path(doc, pt).lower())
        for tag, text in rs:
            if any(p == tag or p.startswith(tag + _SEP) for p in paths) and [i, text] not in out:
                out.append([i, text])
    return out


def card_remarks(plans, guid, ord_):
    """3.8.1: [(plan name, text)]: what the authors of the plans I follow
    wrote on this one card (guid + card number), for the review screen."""
    out = []
    for p in plans or []:
        for r in ((p or {}).get("doc") or {}).get("remarks") or []:
            card = r.get("card") if isinstance(r, dict) else None
            if card and str(card[0]) == str(guid) and int(card[1]) == int(ord_) and r.get("text"):
                out.append((str(p.get("name") or "Plan"), str(r["text"])))
    return out


def search_counts(idx, lean_doc):
    """3.4, D1: {unit id: {search: cards it finds here}} for a plan I write;
    E1: "#ids" is how many cards its pasted ids find; 3.6.5, P1: "#pn",
    what the date opens here (date_counts)."""
    out = {}
    pn = date_counts(idx, lean_doc)
    for u in lean_doc.get("units") or []:
        c = {q: len(idx.search_cards(q)) for q in u.get("search") or []}
        if u.get("nids") or u.get("cids") or u.get("notes"):
            c["#ids"] = len(idx.id_cards(u))
        if u["id"] in pn:
            c["#pn"] = pn[u["id"]]
        if c:
            out[u["id"]] = c
    return out


def date_counts(idx, lean_doc):
    """3.6.5, P1: {unit id: [new, repeat, missing]} for a plan I write, in
    date order: the cards a date finds here that no earlier date has, the
    ones an earlier date already opens, and its picked notes this copy
    doesn't have. Single cards aren't in the lean doc and count apart."""
    seen, out = set(), {}
    units = sorted(lean_doc.get("units") or [], key=lambda u: str(u.get("opens") or ""))
    for u in units:
        cids = idx.match(dict(u, cards=[], ids=[]), None, lean_doc)
        new = len(cids - seen)
        seen |= cids
        miss = sum(1 for g in u.get("notes") or [] if str(g) not in idx.by_guid)
        out[u["id"]] = [new, len(cids) - new, miss]
    return out


def ids_snapshot(idx, lean_doc, cap=50000):
    """{unit id: [tags, decks, [guid]]} for a plan I write, from my copy;
    at most `cap` ids in all."""
    out, n = {}, 0
    for u in lean_doc.get("units") or []:
        if not (u.get("tags") or u.get("decks") or u.get("cut")):
            continue  # a date of searches only: its count is enough (search_counts)
        ids = note_ids(idx, u, lean_doc)[:max(0, cap - n)]
        n += len(ids)
        out[u["id"]] = [list(u.get("tags") or []), list(u.get("decks") or []), ids]
        if u.get("cut"):  # 3.8.1: kept only while the date's cuts are these
            out[u["id"]].append([[c.get("tag"), c.get("in")] for c in u["cut"]])
    return out


def id_refs(idx, col, lean_doc, cap=50000):
    """3.6.5: {unit id: [nids, cids, [[guid, ord]]]} for a plan I write: the
    cards its pasted ids are in my copy, as references that work in anyone's.
    At most `cap` in all; the ids sent back say what they were worked out from."""
    out, n = {}, 0
    for u in lean_doc.get("units") or []:
        if not (u.get("nids") or u.get("cids")):
            continue
        refs = card_refs(col, idx.pasted_cards(u))[:max(0, min(20000, cap - n))]
        n += len(refs)
        out[u["id"]] = [list(u.get("nids") or []), list(u.get("cids") or []), refs]
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


SNAP_TAGS = "#tags"  # 3.8.1: the snapshot's key for the plan's tags (a date's id is [a-z0-9])


def snapshot(doc):
    """What a change note compares: {unit id: [name, opens, what it picks]}
    (3.7.3: the third, a short hash of its sources, so "updated" can be said;
    a snapshot from before has two). 3.8.1: and the plan's tags {id: name}
    under SNAP_TAGS (a snapshot from before has none)."""
    # what the author picked, not what their Anki worked out (C5 ids, refs):
    # those arrive on their own and would say "updated" for nothing
    picked = lambda u: {k: v for k, v in u.items() if k not in ("ids", "idr")}
    out = {u["id"]: [str(u.get("name") or ""), str(u.get("opens") or ""), unit_sig(picked(u))[:8]] for u in units(doc)}
    out[SNAP_TAGS] = {str(t["id"]): str(t.get("name") or "") for t in plan_tags(doc)}
    return out


def change_note(owner, old, doc):
    """"Dre moved Renal pharm to Mon 2 Nov and added Pulm · Asthma." as
    segments, or None. At most two of each kind by name, then a count."""
    new = snapshot(doc)
    tags_now, tags_then = new.pop(SNAP_TAGS), (old or {}).get(SNAP_TAGS)
    old = {k: v for k, v in (old or {}).items() if k != SNAP_TAGS}
    moved = [(new[u][0], new[u][1]) for u in new if u in old and old[u][1] != new[u][1]]
    added = [new[u][0] for u in new if u not in old]
    gone = [old[u][0] for u in old if u not in new]
    # 3.7.3: a date whose cards changed (a tag, a search, cards added or taken off)
    changed = [new[u][0] for u in new if u in old and len(old[u]) > 2 and old[u][2] != new[u][2]
               and old[u][1] == new[u][1]]
    # 3.8.1: a date whose only change is its name, by its day: "updated Fri 16 Oct"
    changed += [fmt_day(new[u][1]) for u in new if u in old and old[u][0] != new[u][0] and old[u][1] == new[u][1]
                and (len(old[u]) < 3 or old[u][2] == new[u][2])]
    # 3.8.1: the plan's tags, when the last snapshot had them: "renamed 10 tags"
    tag_words = []
    if isinstance(tags_then, dict):
        for verb, n in (("renamed", sum(1 for k in tags_now if k in tags_then and tags_then[k] != tags_now[k])),
                        ("added", sum(1 for k in tags_now if k not in tags_then)),
                        ("took off", sum(1 for k in tags_then if k not in tags_now))):
            if n:
                tag_words.append([(f"{verb} {n:,} tag{'s' if n != 1 else ''}", False)])
    if not (moved or added or gone or changed or tag_words):
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
    if changed:
        clauses.append(names(changed, "updated"))
    clauses += tag_words
    segs = [(f"{owner or '?'} ", False)]
    for i, c in enumerate(clauses):
        if i:
            segs.append((" and " if i == len(clauses) - 1 else ", ", False))
        segs += c
    segs.append((".", False))
    return segs


# ---- 3.8.0: at my own pace ----
# A follow's `own`: None, the plan's dates open its cards (as before);
# "ready", nothing opens by itself and I open the next date (You › Plans,
# Browse); "next", the same, and once I've seen most of the last one I
# opened, the next opens the morning after. The plan still gives the order;
# its dates still show as the plan's. Mine only: the plan never changes.

OWN = ("ready", "next")
SEEN_ENOUGH = 0.9  # "next": the last date counts as seen at 90% of its open cards
PACE_DAYS = 14     # "your pace": the dates I opened in the last two weeks


def own_pace(plan):
    return (plan or {}).get("own") in OWN


def opened_here(applied, u, prog=None):
    """A date I opened here: applied, not skipped, and (with progress) not
    shut again since (Edit › Undo after an Open puts its cards back)."""
    have = (applied or {}).get(u["id"])
    if not isinstance(have, str) or have.startswith("skip:"):
        return False
    if prog is not None:
        o, _s, t = (prog.get(u["id"]) or [0, 0, 0])[:3]
        if int(t) and not int(o):
            return False
    return True


def up_next(doc, applied, prog=None):
    """At my own pace, the dates still to open, in the plan's order: not
    opened here, and not skipped (at a late join, or as one of my own skips)."""
    out = []
    for u in units(doc):
        have = (applied or {}).get(u["id"])
        if isinstance(have, str) and have.startswith("skip:"):
            continue
        if not opened_here(applied, u, prog):
            out.append(u)
    return out


def own_due(doc, applied, sig):
    """At my own pace, what a morning opens by itself: only what an author's
    update adds to dates I've opened. [(unit, "open")]."""
    out = []
    for u in units(doc):
        have = (applied or {}).get(u["id"])
        if isinstance(have, str) and not have.startswith("skip:") and have != sig(u):
            out.append((u, "open"))
    return out


def own_last(doc, opened_days):
    """The date I opened last at my own pace (the latest day; on one day, the
    later in the plan), or None."""
    by = {u["id"]: (i, u) for i, u in enumerate(units(doc))}
    keys = [k for k in (opened_days or {}) if k in by]
    if not keys:
        return None
    return by[max(keys, key=lambda k: (str(opened_days[k]), by[k][0]))][1]


def next_by_itself(doc, applied, opened_days, prog):
    """"next": the date that opens this morning, or None. Only after I've
    opened one myself, and once I've seen SEEN_ENOUGH of the last one's open
    cards (one with nothing open counts as seen); one a morning."""
    last = own_last(doc, opened_days)
    left = up_next(doc, applied, prog)
    if last is None or not left:
        return None
    o, s, _t = ((prog or {}).get(last["id"]) or [0, 0, 0])[:3]
    if int(o) and int(s) < SEEN_ENOUGH * int(o):
        return None
    return left[0]


def plan_at(doc, today):
    """Where the plan's own dates are today, for someone at their own pace."""
    us = units(doc)
    if not us:
        return ""
    past = [u for u in us if str(u.get("opens") or "") <= today]
    if not past:
        return f"The plan's dates start {fmt_day(us[0]['opens'])}."
    last = past[-1]
    end = str(last.get("due") or last.get("opens") or "")
    if len(past) == len(us) and end < today:
        return f"The plan's dates ended {fmt_day(end)}."
    return f"The plan's dates are at {last.get('name') or '?'} today."


def recent_opens(opened_days, today, days=PACE_DAYS):
    """How many dates I opened in the last `days` days."""
    since = (datetime.date.fromisoformat(today) - datetime.timedelta(days=days - 1)).isoformat()
    return sum(1 for d in (opened_days or {}).values() if since <= str(d) <= today)


def finish_check(doc, left, recent, today, days=PACE_DAYS):
    """When the plan has an exam (its last event ahead) or an end: the day my
    pace opens its last date, against it. A line, or None."""
    if not left or not recent:
        return None
    evs = sorted((e for e in doc.get("events") or [] if isinstance(e, dict) and str(e.get("day") or "") >= today),
                 key=lambda e: e["day"])
    if evs:
        day, name = evs[-1]["day"], str(evs[-1].get("name") or "the exam")
    elif doc.get("end") and str(doc["end"]) >= today:
        day, name = doc["end"], "the plan's end"
    else:
        return None
    need = -(-left * days // recent)  # days, rounded up
    done = datetime.date.fromisoformat(today) + datetime.timedelta(days=need)
    late = (done - datetime.date.fromisoformat(day)).days
    when = fmt_day(done.isoformat())
    if late > 0:
        return f"At that pace you open the last date on {when}, {late} day{'s' if late != 1 else ''} after {name}."
    return f"At that pace you open the last date on {when}, in time for {name}."


# ---- 3.8.1: a follower's day (plans, round three) ----

AWAY_DAYS = 3   # Welcome back: this many days I studied nothing, whose dates a morning would open, ask first
AWAY_LOOK = 60  # ...looked for this far back (one revlog query)


def reinforces(doc, u):
    """A date for an event (its `for`) that opens after the event's day is
    reinforcement: "after Heme quiz", not "for Heme quiz" (the builder says
    the same). The event, or None. Read on the dates as given: my own days
    in Anki (events never move)."""
    ev = event_of(doc, u)
    day = str((ev or {}).get("day") or "")
    return ev if day and day < str((u or {}).get("opens") or "") else None


def for_words(doc, u):
    """"for Heme quiz", "after Heme quiz" for reinforcement, "" with no event.
    Raw: the board escapes the name."""
    ev = event_of(doc, u)
    if not ev:
        return ""
    return f"{'after' if reinforces(doc, u) else 'for'} {ev.get('name') or '?'}"


def away_days(us, applied, today, studied, since=""):
    """Welcome back: the days before today (and from `since`) with one of
    these dates (what a morning would open) never opened here, on which I
    studied nothing at all (`studied`: the days I answered any card, iso).
    Oldest first."""
    days = {str(u.get("opens") or "") for u in us if (applied or {}).get(u["id"]) is None}
    return sorted(d for d in days if d and since <= d < today and d not in studied)


def study_cards(idx, cids):
    """Study this date: its open cards, new and review, due or not (a cram
    before a quiz): not suspended (a leech stays out) and not buried."""
    return sorted(c for c in cids if c in idx.cards and idx.cards[c][0] >= 0)


def held_rows(idx, doc, held, swap=None):
    """Held back: what a plan holds shut here now, by date: [[name, opens,
    n]] in the plan's order, a card on its first date only; what's on no date
    any more is one row, [None, "", n]."""
    left, out = set(held), []
    for u in units(doc):
        got = idx.match(u, swap, doc) & left
        if got:
            out.append([str(u.get("name") or "?"), str(u.get("opens") or ""), len(got)])
            left -= got
    if left:
        out.append([None, "", len(left)])
    return out


# ---- 3.8.0: plan tags ----
# A plan's own tags (SLG 12): made in an author's Anki (exact notes by guid)
# or on duecrew.com (a tag's, a subdeck's or a search's cards in each copy).
# Each follower's Anki puts them on its own notes as DueCrew::<the plan's
# part>::<the tag's>, as soon as the plan's update is here; a date uses one
# as any tag. Only those tags are ever touched here, never anyone's own.

TAG_PARENT = "DueCrew"
TAG_ROOT_MAX = 60


def _slug(name):
    s = re.sub(r"\s+", "_", str(name or ""))
    s = re.sub(r'["*\\%]', "", s).replace(":", "-")
    s = re.sub(r"_+", "_", s)
    return re.sub(r"^[_-]+|[_-]+$", "", s)


def tag_part(name):
    """A name as one part of an Anki tag: spaces are _, the characters a tag
    or a search can't hold go, a : is a -. The twin of plans.ts tagPart and
    Tags.part in builder.js: change one, change all three."""
    return _slug(name) or "tag"


def tag_root(plan_name):
    """The plan's own part, from its name when its first tag is made (then
    kept in the doc as `tagroot`). plans.ts tagRoot, Tags.root."""
    return re.sub(r"[_-]+$", "", _slug(plan_name)[:TAG_ROOT_MAX]) or "plan"


def plan_tags(doc):
    """The plan's tags, as its doc carries them (cleaned)."""
    return [t for t in (doc or {}).get("tags") or [] if isinstance(t, dict) and t.get("id")]


def tags_sig(doc):
    """What the plan's tags are, short: the glue reads the deck again only when it changes."""
    body = json.dumps({"root": (doc or {}).get("tagroot"), "tags": plan_tags(doc)}, sort_keys=True)
    return hashlib.sha1(body.encode()).hexdigest()[:16]


def tag_base(doc):
    return f"{TAG_PARENT}{_SEP}{(doc or {}).get('tagroot') or 'plan'}"


def tag_path(doc, tag):
    """DueCrew::MS2_Block_1::SLG_12: the tag as this Anki writes it."""
    return f"{tag_base(doc)}{_SEP}{tag_part(tag.get('name'))}"


def tag_search(path):
    """An Anki search for one tag, its \\ " _ * read as themselves (Tags.ankiSearch
    in builder.js escapes a tag the same way); open, so a caller can end it
    with ::* before the closing quote."""
    esc = re.sub(r'([\\"*_])', r"\\\1", str(path))
    return f'"tag:{esc}'


def plan_tag_map(doc):
    """3.8.1: the plan's own tags by their Anki tag (lowercased) and by
    ("id", id), for DeckIndex.match. {} for a plan without them."""
    out = {}
    for t in plan_tags(doc) if isinstance(doc, dict) and doc.get("tags") else ():
        out[tag_path(doc, t).lower()] = t
        out[("id", t.get("id"))] = t
    return out


def tag_whole_notes(idx, doc, tag, swap=None):
    """3.8.1: the note ids a plan tag holds whole in this copy: its notes by
    guid, and what its tags, subdecks and searches find, in the plan's deck."""
    unit = {"tags": tag.get("tags") or [], "decks": tag.get("decks") or [],
            "search": tag.get("search") or [], "notes": tag.get("notes") or []}
    cids = idx.match(unit, swap, (doc or {}).get("deck", ""))
    return {idx.nid_of[c] for c in cids if c in idx.nid_of}


def tag_notes(idx, doc, tag, swap=None):
    """(the note ids the tag goes on in this copy, how many of its exact notes
    this copy doesn't have): what it holds whole, and the notes of its single
    cards (3.8.1: Anki tags notes; Due Crew reads just those cards)."""
    nids = tag_whole_notes(idx, doc, tag, swap)
    for g, o in tag.get("cards") or []:
        cid = idx.by_ref.get((str(g), int(o)))
        if cid is not None and cid in idx.nid_of:
            nids.add(idx.nid_of[cid])
    exact = set(str(g) for g in tag.get("notes") or []) | {str(g) for g, _o in tag.get("cards") or []}
    missing = sum(1 for g in exact if g not in idx.by_guid)
    return nids, missing


def _tagged(col, path):
    """The notes carrying exactly this tag (any case)."""
    return {int(n) for n in col.db.list(
        "SELECT id FROM notes WHERE instr(' ' || lower(tags) || ' ', ?) > 0", f" {str(path).lower()} ")}


def sync_tags(col, idx, doc, applied, label, swap=None):
    """Make this copy's notes carry the plan's tags as the plan says, as one
    undo step `label`: each tag on the notes it holds here and on no others,
    one renamed in the plan renamed here, one gone taken off. applied: {tag
    id: the tag as last written here}. Returns (applied now, {added, removed,
    new: [names new here], missing: {name: exact notes not in this copy}})."""
    applied = {str(k): str(v) for k, v in (applied or {}).items()}
    tags = plan_tags(doc)
    wanted = {}
    out = {"added": 0, "removed": 0, "new": [], "missing": {}}
    for t in tags:
        nids, miss = tag_notes(idx, doc, t, swap)
        wanted[str(t["id"])] = (tag_path(doc, t), nids, str(t.get("name") or ""))
        if miss:
            out["missing"][str(t.get("name") or "")] = miss
    ours = tag_base(doc).lower() + _SEP
    steps = []
    for tid, old in applied.items():
        if not old.lower().startswith(TAG_PARENT.lower() + _SEP):
            continue  # never anyone's own tag
        if tid not in wanted:
            steps.append(("drop", old))
        elif wanted[tid][0].lower() != old.lower():
            steps.append(("rename", old, wanted[tid][0]))
    plan_moves = []
    for tid, (path, nids, name) in wanted.items():
        if not path.lower().startswith(ours):
            continue
        have = _tagged(col, path) if tid in applied else set()
        if tid in applied and any(st[0] == "rename" and st[2] == path for st in steps):
            have = _tagged(col, applied[tid])  # what the rename will carry over
        add, take = sorted(nids - have), sorted(have - nids)
        if add:
            plan_moves.append(("add", path, add))
        if take:
            plan_moves.append(("take", path, take))
        if tid not in applied and nids:
            out["new"].append(name)
    if not steps and not plan_moves:
        return {tid: w[0] for tid, w in wanted.items()}, out
    pos = None
    if hasattr(col, "add_custom_undo_entry"):
        try:
            pos = col.add_custom_undo_entry(label)
        except Exception:
            pos = None
    for st in steps:
        if st[0] == "drop":
            col.tags.remove(st[1])
        else:
            col.tags.rename(st[1], st[2])
    for kind, path, nids in plan_moves:
        for i in range(0, len(nids), 5000):
            part = nids[i:i + 5000]
            if kind == "add":
                col.tags.bulk_add(part, path)
                out["added"] += len(part)
            else:
                col.tags.bulk_remove(part, path)
                out["removed"] += len(part)
    if pos is not None and hasattr(col, "merge_undo_entries"):
        try:
            col.merge_undo_entries(pos)
        except Exception:
            pass
    return {tid: w[0] for tid, w in wanted.items()}, out


def drop_tags(col, doc_or_base, label):
    """Unfollow: the plan's tags off every note here, as one undo step; and
    the DueCrew parent too once no note carries anything under it. Returns
    how many notes carried one."""
    base = doc_or_base if isinstance(doc_or_base, str) else tag_base(doc_or_base)
    if not base.lower().startswith(TAG_PARENT.lower() + _SEP):
        return 0
    n = int(col.db.scalar("SELECT count() FROM notes WHERE instr(' ' || lower(tags), ?) > 0",
                          f" {base.lower()}{_SEP}") or 0)
    pos = None
    if hasattr(col, "add_custom_undo_entry"):
        try:
            pos = col.add_custom_undo_entry(label)
        except Exception:
            pos = None
    col.tags.remove(base)
    low = TAG_PARENT.lower()
    left = int(col.db.scalar("SELECT count() FROM notes WHERE instr(' ' || lower(tags), ?) > 0 "
                             "OR instr(' ' || lower(tags) || ' ', ?) > 0", f" {low}{_SEP}", f" {low} ") or 0)
    if not left:
        col.tags.remove(TAG_PARENT)
    if pos is not None and hasattr(col, "merge_undo_entries"):
        try:
            col.merge_undo_entries(pos)
        except Exception:
            pass
    return n


# ---- the browser: which cards ----

# searches whose answer is this person's own Anki, not the deck: another
# follower's would find something else (deck:current is the browser's default)
_PERSONAL = re.compile(r"(?i)(?:^|[\s(\"-])(?:deck:current|is:(?:due|new|learn|review|suspended|buried|susp)|"
                       r"rated:|prop:|introduced:|added:|edited:|resched:|flag:|nid:|cid:)")
# 3.6.5: nid:/cid: name notes by this copy's ids, which another copy may not
# share: picked cards go up as These cards (guid + card number) instead


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


def selector(col, cids=(), nids=()):
    """3.6.5: the browser's pick as plan text anyone's copy can read: notes
    by guid ("notes:G G", every card of each), or cards as guid and card
    number from 1 ("cards:G:1 G:3"). A note's guid is the same in every
    copy of a deck; its ids may not be. ("", 0) for nothing."""
    if nids:
        nl = sorted({int(n) for n in nids})
        gs = []
        for i in range(0, len(nl), 500):
            gs += [str(g) for (g,) in col.db.all(f"SELECT guid FROM notes WHERE id IN ({','.join(map(str, nl[i:i + 500]))})")]
        gs = sorted(set(g for g in gs if g and " " not in g))
        return ("notes:" + " ".join(gs), len(gs)) if gs else ("", 0)
    refs = sorted({(g, o) for g, o in card_refs(col, cids) if g and " " not in g})
    return ("cards:" + " ".join(f"{g}:{o + 1}" for g, o in refs), len(refs)) if refs else ("", 0)


# ---- my cards, for my own AI (3.6.5, P3) ----

_TAG_RE = re.compile(r"<[^>]*>")
_MEDIA_RE = re.compile(r"\[sound:[^\]]*\]")


def _plain(text):
    """A field without its formatting or media: what an AI needs to read it."""
    t = _MEDIA_RE.sub(" ", str(text or ""))
    t = re.sub(r"(?i)<br\s*/?>|</div>|</p>|</li>", " ", t)
    t = html.unescape(_TAG_RE.sub("", t))
    return re.sub(r"\s+", " ", t).strip()


def _cell(text):
    """One tab-separated cell: no tabs or line breaks inside; a quote quoted."""
    t = re.sub(r"[\t\r\n]+", " ", str(text or ""))
    return '"' + t.replace('"', '""') + '"' if '"' in t else t


def export_scope(idx, doc, scope, swap=None):
    """{note id} a plan's export takes from this deck: "dates" (what its dates
    open here), "cover" (the tags and subdecks the builder ticked), or
    "deck" (all of it)."""
    if scope == "deck":
        cids = set(idx.cards)
    elif scope == "cover":
        keys = list(((doc or {}).get("pace") or {}).get("cover") or [])
        unit = {"tags": [k[4:] for k in keys if str(k).startswith("tag:")],
                "decks": [k[5:] for k in keys if str(k).startswith("deck:")]}
        cids = idx.match(unit, swap, doc or {})
    else:
        cids = set()
        for u in units(doc or {}):
            cids |= idx.match(u, swap, doc or {})
    return {n for n, cs in idx.by_nid.items() if any(c in cids for c in cs)}


CARDS_TEXT = 500  # builder.js CARDS_TEXT: past this, a date's single cards are a count in its text


def _date_line(u, doc):
    """A date as the plan's text writes it (builder.js toText's line, the twin):
    date | name | tag:…, tag:… in SLG 12, deck:… | search:… | notes:… | cards:G:N | due … | for …"""
    tags = {t.get("id"): t for t in plan_tags(doc)}
    evs = {e.get("id"): e for e in (doc or {}).get("events") or [] if isinstance(e, dict)}
    first = ", ".join([f"tag:{t}" for t in u.get("tags") or []]
                      + [f"tag:{c.get('tag')} in {(tags.get(c.get('in')) or {}).get('name') or '?'}" for c in u.get("cut") or []]
                      + [f"deck:{d}" for d in u.get("decks") or []])
    cut_q = {c.get("q") for c in u.get("cut") or []}
    cards = u.get("cards") or []
    parts = [str(u.get("opens") or ""), str(u.get("name") or ""), first,
             *[f"search:{q}" for q in u.get("search") or [] if q not in cut_q],
             f"nids:{','.join(str(n) for n in u['nids'])}" if u.get("nids") else "",
             f"cids:{','.join(str(n) for n in u['cids'])}" if u.get("cids") else "",
             f"notes:{' '.join(u['notes'])}" if u.get("notes") else "",
             f"due {u['due']}" if u.get("due") else "", "even" if u.get("even") else "",
             f"{len(cards)} single cards" if len(cards) > CARDS_TEXT
             else "cards:" + " ".join(f"{g}:{int(o) + 1}" for g, o in cards) if cards else "",
             f"for {evs[u['for']].get('name')}" if u.get("for") in evs else "",
             *[f"{x.get('k')}: {x.get('t')}" + (f" {x['url']}" if x.get("url") else "") for x in u.get("todo") or []]]
    return " | ".join(p for p in parts[:2]) + "".join(f" | {p}" for p in parts[2:] if p)


def export_plan_lines(idx, doc, name="", swap=None):
    """3.8.1, Export cards for my AI, with the plan: comment lines for the top
    of the file. Each date in the plan's text format with how many cards it
    has in this copy and how many of those another date has too; its events;
    the plan's tags (name, full path, cards here); the authors' notes (tag
    and card ones). Names, tags, ids, counts and the authors' own words:
    never a card's text (those are the rows, by #guid and #cards)."""
    us = units(doc)
    ms = {u["id"]: idx.match(u, swap, doc or {}) for u in us}
    seen = {}
    for cs in ms.values():
        for c in cs:
            seen[c] = seen.get(c, 0) + 1
    out = [f'# The plan "{name or "Plan"}", as its Text tab writes it (duecrew.com/plan-text): each date with its cards '
           "in this copy and how many of those another date has too; its tags; its notes. Its cards are the rows below, "
           "by their #guid and #cards columns."]
    lines = []
    for u in us:
        n, also = len(ms[u["id"]]), sum(1 for c in ms[u["id"]] if seen[c] > 1)
        lines.append(f"{_date_line(u, doc)} | {n:,} card{'s' if n != 1 else ''} here, {also:,} also on another date")
    lines += [f"{e['day']} | event | {e.get('name') or '?'}" for e in (doc or {}).get("events") or []
              if isinstance(e, dict) and e.get("day")]
    out += [f"# {x}" for x in sorted(lines)]
    for t in plan_tags(doc):
        n = len(idx.plan_tag_cards(doc, t, swap))
        out.append(f"# tag | {t.get('name')} | {tag_path(doc, t)} | {n:,} card{'s' if n != 1 else ''} here")
    for r in (doc or {}).get("remarks") or []:
        if r.get("tag"):
            out.append(f"# note | tag:{r['tag']} | {r.get('text')}")
        elif r.get("card"):
            out.append(f"# note | card:{r['card'][0]}:{int(r['card'][1]) + 1} | {r.get('text')}")
    return [re.sub(r"[\r\n\t]+", " ", x) for x in out]


def export_notes(col, nids, plain=True, plan_lines=None):
    """(text, notes): the notes in Anki's own plain-text export format, with
    the unique identifier (a note's guid, the same in every copy of a deck)
    first, so an AI can answer with notes: lines; 3.8.1, and each note's
    card numbers (cards:ID:N, a cloze's N its cloze number), and (with the
    plan) its plan_lines after Anki's header lines. Written to a file on
    this computer only; nothing here is sent anywhere."""
    nl = sorted({int(n) for n in nids})
    rows = []
    names = {}
    nums = {}
    for i in range(0, len(nl), 500):
        chunk = ",".join(str(n) for n in nl[i:i + 500])
        rows += col.db.all(
            f"SELECT n.id, n.guid, n.mid, n.flds, n.tags, (SELECT c.did FROM cards c WHERE c.nid = n.id "
            f"ORDER BY c.ord LIMIT 1) FROM notes n WHERE n.id IN ({chunk})")
        for nid, ord_ in col.db.all(f"SELECT nid, ord FROM cards WHERE nid IN ({chunk})"):
            nums.setdefault(int(nid), set()).add(int(ord_) + 1)
    out = ["#separator:tab", f"#html:{'false' if plain else 'true'}", "#guid column:1",
           "#notetype column:2", "#deck column:3", "#tags column:4", "#cards column:5"]
    out += [str(x) for x in plan_lines or []]  # 3.8.1: the plan, as comment lines
    for nid, guid, mid, flds, tags, did in rows:
        if mid not in names:
            try:
                names[mid] = str((col.models.get(mid) or {}).get("name") or "")
            except Exception:
                names[mid] = ""
        try:
            deck = col.decks.name(did) if did else ""
        except Exception:
            deck = ""
        fields = str(flds or "").split("\x1f")
        fields = [_plain(f) if plain else f for f in fields]
        card_nums = " ".join(str(n) for n in sorted(nums.get(int(nid), ())))
        out.append("\t".join(_cell(x) for x in [guid, names[mid], deck, str(tags or "").strip(), card_nums] + fields))
    return "\n".join(out) + "\n", len(rows)


def export_size(col, nids):
    """About how many bytes export_notes writes for these notes, from the
    fields' length (formatting counted, so it errs high)."""
    nl = sorted({int(n) for n in nids})
    total = 0
    for i in range(0, len(nl), 500):
        chunk = ",".join(str(n) for n in nl[i:i + 500])
        total += col.db.scalar(f"SELECT COALESCE(SUM(LENGTH(flds) + LENGTH(tags) + 40), 0) FROM notes WHERE id IN ({chunk})") or 0
    return int(total)


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


PARENT = "Due Crew"  # 3.8.0: Due Crew's filtered decks sit under one parent deck
FILTERED_PREFIX = "Due Crew · "  # before 3.8.0, at the top


def our_deck(name):
    """A filtered deck Due Crew builds: "Due Crew::Renal", under the one
    parent deck, so they fold away in Anki's deck list. "::" in the name
    would make another level."""
    return f"{PARENT}::" + (" ".join(str(name).replace("::", ": ").split())[:120] or "Cards")


def tidy(filtered, built, parent=None):
    """3.8.0: which of the filtered decks Due Crew built go: the empty ones.
    filtered: [(deck id, name, cards in it)], Anki's filtered decks; built:
    the ids Due Crew built here. Ours: built here, under "Due Crew::", or
    named "Due Crew · …" (before the parent, and the list). One with cards
    in it stays: a checkpoint not done yet, a date half studied. parent:
    (its id, the decks under it, cards in it): the parent deck, when Due
    Crew made it, goes too once it's empty with nothing left under it."""
    built = {int(x) for x in built}
    gone = [int(d) for d, name, n in filtered
            if not n and (int(d) in built or str(name).startswith((FILTERED_PREFIX, PARENT + "::")))]
    if parent:
        pid, kids, n = parent
        if int(pid) in built and not n and {int(k) for k in kids} <= set(gone):
            gone.append(int(pid))
    return gone
