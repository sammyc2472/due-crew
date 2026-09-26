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


def unit_sig(unit, deck_id=None, swap=None):
    """What a unit opens on this computer: its sources, the deck it runs on
    and the tag swap. Remembered once applied; a unit whose date moves keeps
    its sig (so moving it later changes nothing), one the author adds cards
    to gets a new one (so the new cards open the next morning)."""
    blob = json.dumps([deck_id, list(swap or []), sorted(str(t).lower() for t in unit.get("tags") or []),
                       sorted(str(d).lower() for d in unit.get("decks") or []),
                       sorted(f"{g}:{o}" for g, o in unit.get("cards") or [])])
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
        rows = col.db.all(
            "SELECT c.id, CASE WHEN c.odid != 0 THEN c.odid ELSE c.did END, c.ord, c.queue, c.type, "
            f"n.guid, n.tags FROM cards c JOIN notes n ON n.id = c.nid "
            f"WHERE c.did IN ({ids}) OR c.odid IN ({ids})")
        self.cards = {}      # cid -> (queue, type)
        self.by_deck = {}    # did -> [cid]
        self.by_ref = {}     # (guid, ord) -> cid
        by_tag = {}          # lowercased tag -> [cid]
        self.tag_names = {}  # lowercased tag -> as written
        treeset = set(tree)
        for cid, home, ord_, queue, ctype, guid, tags in rows:
            if int(home) not in treeset:
                continue
            cid = int(cid)
            self.cards[cid] = (int(queue), int(ctype))
            self.by_deck.setdefault(int(home), []).append(cid)
            self.by_ref[(str(guid), int(ord_))] = cid
            for t in str(tags or "").split():
                low = t.lower()
                by_tag.setdefault(low, []).append(cid)
                self.tag_names.setdefault(low, t)
        self.by_tag = by_tag
        self.tag_keys = sorted(by_tag)

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

    def match(self, unit, swap=None, plan_deck=""):
        """{cid} for one unit on this deck."""
        out = set()
        for t in unit.get("tags") or []:
            out |= self.tag_cards(swapped(t, swap))
        for d in unit.get("decks") or []:
            out |= self.deck_cards(d, plan_deck)
        for g, o in unit.get("cards") or []:
            cid = self.by_ref.get((str(g), int(o)))
            if cid is not None:
                out.add(cid)
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

    # -- the builder's tree --

    def tree(self, with_tags=True, with_decks=True, cap=5000):
        """(tags, decks) for PUT /plans/trees: [[path, cards]] each, names and
        counts only. A tag counts every card under it; a subdeck, every card
        in it and below. At most `cap` of each, shallowest and biggest first."""
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
            tags = sorted(tags[:cap], key=lambda x: x[0].lower())
        decks = []
        if with_decks:
            for rel, d in self.rel.items():
                if not rel:
                    continue
                n = sum(len(self.by_deck.get(dd, ())) for r, dd in self.rel.items()
                        if r == rel or r.startswith(rel + _SEP))
                if n:
                    decks.append([f"{self.name}{_SEP}{self.spelled[rel]}", n])
            decks.sort(key=lambda x: x[0].lower())
            decks = decks[:cap]
        return tags, decks

    def top_tags(self):
        """The first part of every tag here, as written."""
        out = {}
        for low in self.tag_keys:
            first = self.tag_names[low].split(_SEP)[0]
            out.setdefault(first.lower(), first)
        return out


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


def opened_by_date(doc, today):
    return [u for u in units(doc) if str(u.get("opens") or "9999") <= today]


def next_unit(doc, today):
    return next((u for u in units(doc) if str(u.get("opens") or "") > today), None)


def open_cards(col, cids, label):
    """Unsuspend the suspended ones among `cids`, as one undo step named
    `label`. Only queue -1 is touched; never suspends. Returns how many
    opened (0: nothing was suspended, and no undo step is made)."""
    if not cids:
        return 0
    ids = []
    cl = sorted(int(c) for c in cids)
    for i in range(0, len(cl), 500):
        chunk = ",".join(str(c) for c in cl[i:i + 500])
        ids += col.db.list(f"SELECT id FROM cards WHERE queue = -1 AND id IN ({chunk})")
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
