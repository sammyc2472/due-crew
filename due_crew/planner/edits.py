"""What an author changes in a plan from Your plans (docs/planner.md), on
the doc as the server keeps it (GET /plans/{id}, every field), so a save
sends back everything it didn't touch. Pure: each takes a doc and returns
a new one, or raises Refused with the words to show. The server still
checks everything (plans.ts planDoc); these say it first, in words, the
builder's (site/public/builder.js: the twin of each is named).

A date: a deck tag or subdeck on or off, a search, note or card IDs,
picked notes and cards, a tag kept to one of the plan's own tags (a cut)
or without its extras, renamed, moved, a due date, spread evenly, what it
preps for, its lines to tick; a new date, a date deleted, a date split by
its tags or evenly. An event: made, renamed, moved, taken off. A review
day. The plan's lines every week, a note for followers on a tag. Plans end
to end (the builder's site-only tools): a source less the cards also
tagged something (Overlap's "but not"), a source moved to another date
(moveChip), a plan from a resource at my pace. A save is the builder's:
PUT /plans/{id} with the version it started from (remote.save)."""

import copy
import datetime
import math
import random
import re

from .. import plans as P
from . import build as B

SOURCES_MAX = 50   # plans.ts SOURCES_MAX: tags, and subdecks, a date
UNITS_MAX = B.CEILINGS["sets"]      # plans.ts UNITS_MAX
NAME_MAX = 60      # validate.ts NAME_MAX
PATH_MAX = 200     # plans.ts PATH_MAX
EVENTS_MAX = B.CEILINGS["events"]   # plans.ts EVENTS_MAX
REVIEWS_MAX = B.CEILINGS["reviews"]  # plans.ts REVIEWS_MAX
_ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789"  # app.js uid8


class Refused(Exception):
    """An edit the plan can't take; str() is the window's words."""


def _day(iso):
    try:
        return datetime.date.fromisoformat(str(iso))
    except ValueError:
        raise Refused("That isn't a date.") from None


def _later(iso, days):
    return (_day(iso) + datetime.timedelta(days=days)).isoformat()


def _unit(doc, uid):
    u = next((x for x in doc.get("units") or [] if isinstance(x, dict) and x.get("id") == uid), None)
    if u is None:
        raise Refused("That set isn't on the plan any more.")
    return u


def _cut(text, most):
    """Cut to `most` as the Worker counts (UTF-16 units: an emoji is two),
    never splitting one."""
    out, n = [], 0
    for ch in str(text):
        n += 2 if ord(ch) > 0xFFFF else 1
        if n > most:
            break
        out.append(ch)
    return "".join(out)


def _name(text):
    """A name as the server keeps one: one line, 60 characters as it counts them."""
    name = _cut(" ".join(str(text or "").split()), NAME_MAX).strip()
    if not name:
        raise Refused("A set needs a name.")
    return name


def _path(p):
    p = str(p)
    if not p or len(p) > PATH_MAX or not p.isprintable():
        raise Refused("That tag's name is too long for a plan.")
    return p


def _sorted(doc):
    doc["units"] = sorted(doc.get("units") or [], key=lambda u: str(u.get("opens") or ""))
    return doc


def has_sources(u):
    """What the builder keeps a date for (its cleanup drops the rest)."""
    return bool(u.get("tags") or u.get("decks") or u.get("cards") or u.get("search") or u.get("cut")
                or u.get("nids") or u.get("cids") or u.get("notes"))


def new_id(doc, rng=random):
    """A date's id, as the builder makes one (app.js uid8): 8 letters and
    digits, not one the plan has, never "every"."""
    taken = {str(u.get("id")) for u in doc.get("units") or [] if isinstance(u, dict)}
    taken |= {str(e.get("id")) for e in doc.get("events") or [] if isinstance(e, dict)}
    while True:
        uid = "".join(rng.choice(_ALPHABET) for _ in range(8))
        if uid not in taken and uid != "every":
            return uid


def auto_name(tags=(), decks=()):
    """A new date's first name from what's on it (the first source's last
    part read, "+ 2 more"), till name_dates names it as the builder would."""
    srcs = list(tags) + list(decks)
    if not srcs:
        return "?"
    first = B.tag_word(str(srcs[0]).split("::")[-1])
    return _cut(f"{first}{f' + {len(srcs) - 1} more' if len(srcs) > 1 else ''}", NAME_MAX)


def add_sources(doc, uid, tags=(), decks=()):
    """Deck tags and subdecks onto a date, each once. (doc, how many it took)."""
    doc = copy.deepcopy(doc)
    u = _unit(doc, uid)
    took = 0
    for field, items in (("tags", tags), ("decks", decks)):
        have = list(u.get(field) or [])
        low = {str(x).lower() for x in have}
        for p in items:
            p = _path(p)
            if p.lower() in low:
                continue
            if len(have) >= SOURCES_MAX:
                raise Refused(f"A set holds up to {SOURCES_MAX} {'tags' if field == 'tags' else 'subdecks'}.")
            have.append(p)
            low.add(p.lower())
            took += 1
        u[field] = have
    return doc, took


def take_source(doc, uid, key):
    """One of a date's sources off it, by its key (model.sources): a deck tag,
    a subdeck, a tag kept to a plan tag (a cut: its search goes with it), or a
    bank's questions. Not the last one: a date with nothing on it goes
    (delete_date says so first)."""
    doc = copy.deepcopy(doc)
    u = _unit(doc, uid)
    what = key[0] if key else ""
    if what == "tag":
        u["tags"] = [t for t in u.get("tags") or [] if t != key[1]]
    elif what == "questions":
        drop = set(key[1])
        u["tags"] = [t for t in u.get("tags") or [] if t not in drop]
    elif what == "deck":
        u["decks"] = [d for d in u.get("decks") or [] if d != key[1]]
    elif what == "search":
        _take_search(u, key[1])
    elif what == "picks":
        u["cards"] = []
        for k in ("nids", "cids", "notes", "idn", "idr", "pl"):
            u.pop(k, None)
    elif what == "cut":
        gone = [c for c in u.get("cut") or [] if c.get("tag") == key[1] and c.get("in") == key[2]]
        u["cut"] = [c for c in u.get("cut") or [] if c not in gone]
        qs = {c.get("q") for c in gone}
        if u.get("search"):
            u["search"] = [q for q in u["search"] if q not in qs]
        if isinstance(u.get("sn"), dict):
            u["sn"] = {q: n for q, n in u["sn"].items() if q not in qs}
        for k in ("cut", "search", "sn"):
            if k in u and not u[k]:
                del u[k]
    else:
        raise Refused("That one is changed on duecrew.com.")
    if not has_sources(u):
        raise Refused("That's the last thing on this set: delete the set instead.")
    return doc


def rename(doc, uid, name):
    doc = copy.deepcopy(doc)
    _unit(doc, uid)["name"] = _name(name)
    return doc


def move(doc, uid, opens):
    """A date to another day, its due date and checkpoint the same days later
    (the builder's shiftUnit)."""
    doc = copy.deepcopy(doc)
    u = _unit(doc, uid)
    delta = (_day(opens) - _day(u["opens"])).days
    u["opens"] = _day(opens).isoformat()
    for k in ("due", "check"):
        if u.get(k):
            u[k] = _later(u[k], delta)
    return _sorted(doc)


def set_due(doc, uid, due):
    """A date's due date, or none (None). An even split needs one after it opens."""
    doc = copy.deepcopy(doc)
    u = _unit(doc, uid)
    if due:
        if _day(due) < _day(u["opens"]):
            raise Refused("Finish by is before the set opens.")
        u["due"] = _day(due).isoformat()
    else:
        u.pop("due", None)
    if u.get("even") and not (u.get("due") and u["due"] > u["opens"]):
        u.pop("even", None)
    return doc


def add_date(doc, opens, tags=(), decks=(), name=None, rng=random):
    """A new date on `opens` with these sources. (doc, its id)."""
    doc = copy.deepcopy(doc)
    if len(doc.get("units") or []) >= UNITS_MAX:
        raise Refused(f"A plan holds up to {UNITS_MAX} sets.")
    if not (tags or decks):
        raise Refused("Pick something for the set first.")
    uid = new_id(doc, rng)
    doc.setdefault("units", []).append({"id": uid, "name": _name(name or auto_name(tags, decks)),
                                        "opens": _day(opens).isoformat(), "tags": [], "decks": [], "cards": []})
    doc, _n = add_sources(doc, uid, tags, decks)
    return _sorted(doc), uid


def add_empty_date(doc, opens, name, rng=random):
    """Round five: a date named from the course's calendar with nothing on
    it yet (its cards are suggestions till the author adds them). The
    server keeps a date with no cards; it opens nothing. (doc, its id)."""
    doc = copy.deepcopy(doc)
    if len(doc.get("units") or []) >= UNITS_MAX:
        raise Refused(f"A plan holds up to {UNITS_MAX} sets.")
    uid = new_id(doc, rng)
    doc.setdefault("units", []).append({"id": uid, "name": _name(name), "opens": _day(opens).isoformat(),
                                        "tags": [], "decks": [], "cards": []})
    return _sorted(doc), uid


def shift_from(doc, uid, days):
    """Round five's "this and every date after": the date and every date on
    or after its day `days` days later (or earlier), their finish-by days
    and checkpoints with them, and the review days from its day on;
    quizzes and exams stay on their days (the school's)."""
    doc = copy.deepcopy(doc)
    day = _unit(doc, uid)["opens"]
    for u in doc.get("units") or []:
        if str(u.get("opens") or "") >= day:
            for k in ("opens", "due", "check"):
                if u.get(k):
                    u[k] = _later(u[k], days)
    for r in doc.get("reviews") or []:
        if str(r.get("day") or "") >= day:
            r["day"] = _later(r["day"], days)
    return _sorted(doc)


def drop_if_empty(doc, uid):
    """After Split by its tags: the split date goes only when nothing came
    back onto it (a date with no cards on purpose, a lecture waiting for
    its cards, stays where cleanup would take it)."""
    u = next((x for x in doc.get("units") or [] if x.get("id") == uid), None)
    if u is not None and not has_sources(u):
        doc["units"] = [x for x in doc["units"] if x is not u]
        _drop_reviews(doc, uid)
    return doc


def add_event(doc, day, name, rng=random, exam=False):
    """A named day (a quiz, the exam) the dates prep for. (doc, its id).
    exam (3.9.9): marked the exam, which a follower's board offers as theirs."""
    doc = copy.deepcopy(doc)
    if len(doc.get("events") or []) >= EVENTS_MAX:
        raise Refused(f"A plan holds up to {EVENTS_MAX} quizzes and exams.")
    eid = new_id(doc, rng)
    doc.setdefault("events", []).append(dict({"id": eid, "day": _day(day).isoformat(), "name": _name(name)},
                                             **({"kind": "exam"} if exam else {})))
    doc["events"].sort(key=lambda e: str(e.get("day") or ""))
    return doc, eid


def prep_for(doc, chosen=None):
    """Each date preps for an event (its `for`): one `chosen` names for it
    ({unit id: [event id]}, what an exam's line covers), the earliest of
    those on or after its day; else the next event on or after it."""
    doc = copy.deepcopy(doc)
    events = sorted((e for e in doc.get("events") or [] if isinstance(e, dict)), key=lambda e: str(e.get("day") or ""))
    days = {e["id"]: str(e.get("day") or "") for e in events}
    for u in doc.get("units") or []:
        opens = str(u.get("opens") or "")
        named = [eid for eid in (chosen or {}).get(u.get("id"), ()) if days.get(eid, "") >= opens]
        pick = min(named, key=lambda eid: days[eid]) if named else next(
            (e["id"] for e in events if str(e.get("day") or "") >= opens), None)
        if pick:
            u["for"] = pick
        else:
            u.pop("for", None)
    return doc


def from_sessions(doc, sessions, picks, scopes=None, rng=random):
    """A block's sessions onto a plan: a quiz or exam an event, every other
    session with tags picked a date on its day named as it is, each date
    prepping for the next event (or the one whose scope names it). picks:
    {session index: [tag]}; scopes: {session index of an event: [session
    index it covers]}. (doc, {session index: unit id}, {session index:
    event id}); a session nothing was picked for isn't put on."""
    from .reading import EVENT_KINDS
    units, events = {}, {}
    for i, s in enumerate(sessions):
        if s.get("kind") in EVENT_KINDS:
            doc, events[i] = add_event(doc, s["date"], s.get("title") or s["kind"].capitalize(), rng)
    for i, s in enumerate(sessions):
        tags = [t for t in (picks or {}).get(i) or [] if t]
        if s.get("kind") in EVENT_KINDS or not tags:
            continue
        doc, units[i] = add_date(doc, s["date"], tags[:SOURCES_MAX], name=s.get("title"), rng=rng)
    chosen = {}
    for ei, covered in (scopes or {}).items():
        if ei in events:
            for i in covered:
                if i in units:
                    chosen.setdefault(units[i], []).append(events[ei])
    return prep_for(doc, chosen), units, events


def new_plan_doc(deck, sessions, end_name, end_day):
    """A new plan's doc: each session a date on its day named as it is,
    with no cards (the author puts them on: nothing is picked for them),
    each quiz or exam an event, the end (the exam named, an event, on its
    day), the dates tested on the next quiz after them, the pace fitting
    what's ticked to the end. Round five's New plan (new_plan.py), the
    add-on's own: the builder starts a plan from its deck on the site.
    (doc, [date ids])."""
    from .reading import EVENT_KINDS
    doc, uids = {"deck": deck, "units": []}, []
    have = set()
    for s in sessions:
        title = " ".join(str(s.get("title") or "").split())[:60] or s.get("kind", "Session").capitalize()
        if s.get("kind") in EVENT_KINDS:
            doc, _eid = add_event(doc, s["date"], title, exam=s.get("kind") == "exam")
            have.add((s["date"], title.lower()))
            continue
        doc, uid = add_empty_date(doc, s["date"], title)
        uids.append(uid)
    end_name = " ".join(str(end_name or "").split())[:60]
    if end_name and end_day and (end_day, end_name.lower()) not in have:
        doc, _eid = add_event(doc, end_day, end_name, exam=True)  # 3.9.9: "the exam it ends with" is the exam
    if end_day:
        doc = set_end(doc, end_day)
    doc = set_pace(doc, "end" if end_day else "daily", [1, 1, 1, 1, 1, 0, 0], 20)
    if uids and doc.get("events"):
        doc = prep_for(doc, {})
    return doc, uids


def delete_date(doc, uid):
    """A date off the plan, and the review days that name it (plans.ts
    refuses a review day whose date went)."""
    doc = copy.deepcopy(doc)
    _unit(doc, uid)
    doc["units"] = [u for u in doc.get("units") or [] if u.get("id") != uid]
    if doc.get("reviews"):
        doc["reviews"] = [r for r in doc["reviews"] if r.get("from") != uid and r.get("to") != uid]
        if not doc["reviews"]:
            del doc["reviews"]
    return doc


def recount(doc, idx, uids, swap=None):
    """The builder's count on a date (a follower's "204 of 212"): its tags'
    and subdecks' cards in this copy, each counted as the deck's tree counts
    it; none when it has neither."""
    doc = copy.deepcopy(doc)
    deck = str(doc.get("deck") or "")
    for u in doc.get("units") or []:
        if u.get("id") not in uids:
            continue
        if u.get("tags") or u.get("decks"):
            u["n"] = (sum(len(idx.tag_cards(P.swapped(t, swap))) for t in u.get("tags") or [])
                      + sum(len(idx.deck_cards(d, deck)) for d in u.get("decks") or []))
        else:
            u.pop("n", None)
    return doc


def lean(doc):
    """The doc as a save sends it: what only the author's Anki sends (a
    date's note ids, its pasted ids' refs and counts, what its picks are)
    stays with the server, which keeps its own and never takes a save's
    (plans.ts keepIdr): sent back, it only costs size."""
    doc = copy.deepcopy(doc)
    for u in doc.get("units") or []:
        for k in ("ids", "idr", "pn", "pl"):
            u.pop(k, None)
    return doc


def what_changed(before, after):
    """One line for the plan's history (a save's summary): "Mon 9 Nov: added
    Videos › Heart failure", "added Tue 10 Nov", "took off Fri 13 Nov"."""
    a = {u["id"]: u for u in before.get("units") or [] if isinstance(u, dict) and u.get("id")}
    b = {u["id"]: u for u in after.get("units") or [] if isinstance(u, dict) and u.get("id")}
    out = []
    for uid in b.keys() - a.keys():
        out.append(f"added {P.fmt_day(b[uid]['opens'])}")
    for uid in a.keys() - b.keys():
        out.append(f"took off {P.fmt_day(a[uid]['opens'])}")
    for uid in a.keys() & b.keys():
        x, y = a[uid], b[uid]
        day = P.fmt_day(y["opens"])
        if x.get("opens") != y.get("opens"):
            out.append(f"moved {P.fmt_day(x['opens'])} to {day}")
        if x.get("name") != y.get("name"):
            out.append(f"renamed {day}")
        if x.get("due") != y.get("due"):
            out.append(f"{day}: due {P.fmt_day(y['due'])}" if y.get("due") else f"{day}: no due date")
        if bool(x.get("even")) != bool(y.get("even")):
            out.append(f"{day}: {'spread evenly' if y.get('even') else 'not spread'}")
        for field, one, many in (("tags", "tag", "tags"), ("decks", "subdeck", "subdecks"), ("cut", "cut", "cuts"),
                                 ("search", "search", "searches"), ("cards", "single card", "single cards"),
                                 ("notes", "note", "notes"), ("nids", "note ID", "note IDs"), ("cids", "card ID", "card IDs")):
            got = len(y.get(field) or []) - len(x.get(field) or [])
            if got > 0:
                out.append(f"{day}: added {got:,} {one if got == 1 else many}")
            elif got < 0:
                out.append(f"{day}: took off {-got:,} {one if got == -1 else many}")
        if x.get("for") != y.get("for"):
            ev = next((e for e in after.get("events") or [] if isinstance(e, dict) and e.get("id") == y.get("for")), None)
            out.append(f"{day}: for {ev.get('name') or '?'}" if ev else f"{day}: for nothing")
        if (x.get("todo") or []) != (y.get("todo") or []):
            out.append(f"{day}: to-dos")
    ea = {e["id"]: e for e in before.get("events") or [] if isinstance(e, dict) and e.get("id")}
    eb = {e["id"]: e for e in after.get("events") or [] if isinstance(e, dict) and e.get("id")}
    for eid in eb.keys() - ea.keys():
        out.append(f"added {eb[eid].get('name') or 'an event'}")
    for eid in ea.keys() - eb.keys():
        out.append(f"took off {ea[eid].get('name') or 'an event'}")
    for eid in ea.keys() & eb.keys():
        if ea[eid].get("day") != eb[eid].get("day"):
            out.append(f"moved {eb[eid].get('name') or 'an event'} to {P.fmt_day(eb[eid]['day'])}")
        if ea[eid].get("name") != eb[eid].get("name"):
            out.append(f"renamed {ea[eid].get('name') or 'an event'}")
    for key, word in (("reviews", "review days"), ("every", "lines every week"), ("remarks", "notes for followers"),
                      ("tags", "the plan's tags"), ("pace", "the pace"), ("end", "the end date"), ("phases", "catch-up weeks")):
        if (before.get(key) or None) != (after.get(key) or None):
            out.append(f"changed {word}")
    return ("; ".join(out) or "changed the plan")[:110] + " (in Anki)"


# ---- 3.9.3: the rest of the builder's edits ----

def _take_search(u, q):
    """takeSearch: a search off a date, its count and any cut it is with it."""
    u["search"] = [x for x in u.get("search") or [] if x != q]
    if isinstance(u.get("sn"), dict):
        u["sn"] = {k: v for k, v in u["sn"].items() if k != q}
    if u.get("cut"):
        u["cut"] = [c for c in u["cut"] if c.get("q") != q]
    for k in ("search", "sn", "cut"):
        if k in u and not u[k]:
            del u[k]


def _searches(u):
    return list(u.get("search") or [])


def add_search(doc, uid, q, n=None):
    """An Anki search onto a date (3.3, C3), each follower's Anki runs it in
    the plan's deck: 500 characters, nothing about one person's own Anki,
    ten searches and cuts a date. n: the cards it finds here, kept as the
    builder's count (sn) for the site."""
    doc = copy.deepcopy(doc)
    u = _unit(doc, uid)
    q = " ".join(str(q or "").split())
    if not q:
        raise Refused("Type an Anki search first.")
    if len(q) > B.SEARCH_LEN:
        raise Refused(f"A search is at most {B.SEARCH_LEN} characters.")
    if not P.shareable_search(q):
        raise Refused("That finds different cards in each person's Anki. Use tags or decks.")
    have = _searches(u)
    if q in have:
        raise Refused("That search is on this set already.")
    if len(have) >= B.SEARCH_MAX:
        raise Refused(f"A set holds up to {B.SEARCH_MAX} searches and cuts.")
    u["search"] = have + [q]
    if isinstance(n, int) and n >= 0:
        u["sn"] = dict(u.get("sn") or {}, **{q: n})
    return doc


def add_ids(doc, uid, kind, ids):
    """Note IDs or card IDs pasted onto a date (E1): this Anki's own numbers,
    turned into notes everyone's copy has once the author's Anki sends them."""
    if kind not in ("nids", "cids"):
        raise Refused("Note IDs or card IDs.")
    doc = copy.deepcopy(doc)
    u = _unit(doc, uid)
    got = list(dict.fromkeys(int(x) for x in ids if int(x) > 0))
    if not got:
        raise Refused("No IDs in that.")
    every = list(dict.fromkeys(list(u.get(kind) or []) + got))
    if len(every) > B.IDS_MAX:
        raise Refused(f"A set takes up to {B.IDS_MAX:,} IDs of each kind.")
    u[kind] = every
    u.pop("idn", None)
    return doc


def add_picks(doc, uid, notes=(), cards=()):
    """Notes by guid (all their cards) and single cards ([guid, ord]) onto a
    date: what Browse's Copy as plan selector copies (3.6.5)."""
    doc = copy.deepcopy(doc)
    u = _unit(doc, uid)
    if not notes and not cards:
        raise Refused("No notes or cards in that.")
    if notes:
        every = list(dict.fromkeys(list(u.get("notes") or []) + [str(g) for g in notes]))
        if len(every) > B.IDS_MAX:
            raise Refused(f"A set takes up to {B.IDS_MAX:,} notes.")
        u["notes"] = every
        u.pop("idn", None)
    have = {(str(g), int(o)) for g, o in u.get("cards") or []}
    u["cards"] = list(u.get("cards") or [])
    for g, o in cards:
        if (str(g), int(o)) not in have:
            have.add((str(g), int(o)))
            u["cards"].append([str(g), int(o)])
    return doc


def set_even(doc, uid, on):
    """Spread a date evenly over its days to its due date (3.3), or not."""
    doc = copy.deepcopy(doc)
    u = _unit(doc, uid)
    if on:
        if not (u.get("due") and u["due"] > u["opens"]):
            raise Refused("Give it a Finish by day after it opens first.")
        u["even"] = True
    else:
        u.pop("even", None)
    return doc


def set_for(doc, uid, eid):
    """What a date preps for (F1): an event's id, or None. One after its day
    reads "after" it, reinforcement (plans.reinforces)."""
    doc = copy.deepcopy(doc)
    u = _unit(doc, uid)
    if eid:
        if not any(isinstance(e, dict) and e.get("id") == eid for e in doc.get("events") or []):
            raise Refused("That quiz or exam isn't on the plan any more.")
        u["for"] = eid
    else:
        u.pop("for", None)
    return doc


def _event(doc, eid):
    e = next((e for e in doc.get("events") or [] if isinstance(e, dict) and e.get("id") == eid), None)
    if e is None:
        raise Refused("That quiz or exam isn't on the plan any more.")
    return e


def mark_exam(doc, eid, on=True):
    """3.9.9 (Sam's pick B): an event marked the exam ({"kind": "exam"}); a
    follower's board asks them once whether it's their exam. Off, it's a
    named day again. A plan can have more than one (a block's exams)."""
    doc = copy.deepcopy(doc)
    e = _event(doc, eid)
    if on:
        e["kind"] = "exam"
    else:
        e.pop("kind", None)
    return doc


def rename_event(doc, eid, name):
    doc = copy.deepcopy(doc)
    _event(doc, eid)["name"] = _name(name)
    return doc


def move_event(doc, eid, day):
    doc = copy.deepcopy(doc)
    _event(doc, eid)["day"] = _day(day).isoformat()
    doc["events"].sort(key=lambda e: str(e.get("day") or ""))
    return doc


def take_event(doc, eid):
    """takeEvent: the event off, and off every date that prepped for it."""
    doc = copy.deepcopy(doc)
    _event(doc, eid)
    doc["events"] = [e for e in doc.get("events") or [] if e.get("id") != eid]
    if not doc["events"]:
        del doc["events"]
    for u in doc.get("units") or []:
        if u.get("for") == eid:
            del u["for"]
    return doc


def set_todo(doc, uid, lines):
    """A date's lines to tick by hand (Due: watch, read, do), Todo.clean's."""
    doc = copy.deepcopy(doc)
    u = _unit(doc, uid)
    clean = B.todo_clean(lines)
    if len([x for x in lines or [] if str((x or {}).get("t") or "").strip()]) > B.TODO_MAX:
        raise Refused(f"A set keeps {B.TODO_MAX} lines to tick.")
    if clean:
        u["todo"] = clean
    else:
        u.pop("todo", None)
    return doc


def set_every(doc, lines):
    """The plan's lines every week (3.8.0), Every.clean's."""
    doc = copy.deepcopy(doc)
    clean = B.every_clean(lines)
    if len([x for x in lines or [] if str((x or {}).get("t") or "").strip()]) > B.EVERY_MAX:
        raise Refused(f"A plan keeps {B.EVERY_MAX} lines every week.")
    if clean:
        doc["every"] = clean
    else:
        doc.pop("every", None)
    return doc


def set_review(doc, day, frm, to):
    """A review day (3.3, C4): that morning followers get a Due Crew deck of
    what they've seen of these dates, most missed first. One a day."""
    doc = copy.deepcopy(doc)
    day = _day(day).isoformat()
    a, b = _unit(doc, frm), _unit(doc, to)
    if a["opens"] > b["opens"]:
        a, b = b, a
    if b["opens"] > day:
        raise Refused("A review day comes after the sets it reviews.")
    rs = [r for r in doc.get("reviews") or [] if isinstance(r, dict) and r.get("day") != day]
    if len(rs) >= REVIEWS_MAX:
        raise Refused(f"A plan holds up to {REVIEWS_MAX} review days.")
    doc["reviews"] = sorted(rs + [{"day": day, "from": a["id"], "to": b["id"]}], key=lambda r: r["day"])
    return doc


def take_review(doc, day):
    doc = copy.deepcopy(doc)
    rs = [r for r in doc.get("reviews") or [] if isinstance(r, dict) and r.get("day") != day]
    if rs:
        doc["reviews"] = rs
    else:
        doc.pop("reviews", None)
    return doc


def set_cut(doc, uid, tag_path, ptag_id):
    """setCut: a deck tag on a date kept to what one of the plan's own tags
    holds ("Cephalosporins · SLG 12"), or all of it again (None)."""
    doc = copy.deepcopy(doc)
    u = _unit(doc, uid)
    had = next((c for c in u.get("cut") or [] if c.get("tag") == tag_path), None)
    if had:
        _take_search(u, had.get("q"))
        u["cut"] = [c for c in u.get("cut") or [] if c is not had]
        if not u["cut"]:
            del u["cut"]
    u["tags"] = [t for t in u.get("tags") or [] if t != tag_path]
    t = next((x for x in P.plan_tags(doc) if x.get("id") == ptag_id), None) if ptag_id else None
    if t is None:
        u["tags"].append(tag_path)
        return doc
    q = B.cut_q(tag_path, P.tag_path(doc, t))
    if q not in _searches(u):  # addSearch: an Overlap search from before 3.8.1 may be it already
        if len(_searches(u)) >= B.SEARCH_MAX:
            raise Refused(f"A set holds up to {B.SEARCH_MAX} searches and cuts.")
        u["search"] = _searches(u) + [q]
    u["cut"] = list(u.get("cut") or []) + [{"tag": tag_path, "in": t["id"], "q": q}]
    return doc


def set_extras(doc, uid, path, without, extra_kids, main_n=None):
    """extrasPick: a deck tag with its extras (Extra, Bonus) or without them,
    the search that is it without them in its place (main_n: its count)."""
    doc = copy.deepcopy(doc)
    u = _unit(doc, uid)
    q = B.without_q(path, extra_kids)
    if without:
        if q not in _searches(u):
            if len(_searches(u)) >= B.SEARCH_MAX:
                raise Refused(f"A set holds up to {B.SEARCH_MAX} searches and cuts.")
            u["search"] = _searches(u) + [q]
        u["tags"] = [t for t in u.get("tags") or [] if t != path]
        if isinstance(main_n, int):
            u["sn"] = dict(u.get("sn") or {}, **{q: main_n})
    else:
        _take_search(u, q)
        if path not in (u.get("tags") or []):
            u["tags"] = list(u.get("tags") or []) + [path]
    return doc


def set_tag_remark(doc, path, text, rng=random):
    """setTagRemark: a note for followers on a tag (one line, 280), changed,
    or taken off (empty)."""
    doc = copy.deepcopy(doc)
    t = B.remark_clean(text)[:B.REMARK_TEXT]
    rs = [r for r in doc.get("remarks") or [] if isinstance(r, dict)]
    have = next((r for r in rs if r.get("tag") and str(r["tag"]).lower() == str(path).lower()), None)
    if not t:
        rs = [r for r in rs if r is not have]
    elif have:
        have["text"] = t
    else:
        if len(rs) >= B.REMARKS_MAX:
            raise Refused(f"A plan holds up to {B.REMARKS_MAX} notes on tags and cards.")
        rs.append({"id": new_id(doc, rng), "tag": str(path), "text": t})
    if rs:
        doc["remarks"] = rs
    else:
        doc.pop("remarks", None)
    return doc


def take_remark(doc, rid):
    """A note for followers off (one on a card, written in Browse)."""
    doc = copy.deepcopy(doc)
    rs = [r for r in doc.get("remarks") or [] if isinstance(r, dict) and r.get("id") != rid]
    if rs:
        doc["remarks"] = rs
    else:
        doc.pop("remarks", None)
    return doc


def split_even(doc, uid, source, study_days, rng=random):
    """Split's Evenly: one source of a date spread over its next study days
    (study_days: [iso], the first its own day), a date of its own due on
    the last, evenly (evenUnit); the source comes off the date it was on."""
    if len(study_days) < 2:
        raise Refused("Evenly takes 2 study days or more.")
    field, path = source
    doc = copy.deepcopy(doc)
    u = _unit(doc, uid)
    if path not in (u.get(field) or []):
        raise Refused("That's not on this set any more.")
    if len(doc.get("units") or []) >= UNITS_MAX:
        raise Refused(f"A plan holds up to {UNITS_MAX} sets.")
    u[field] = [x for x in u[field] if x != path]
    nid = new_id(doc, rng)
    doc["units"].append({"id": nid, "name": _name(auto_name(**{field: [path]})), "opens": study_days[0],
                         "due": study_days[-1], "even": True, "tags": [path] if field == "tags" else [],
                         "decks": [path] if field == "decks" else [], "cards": []})
    if not has_sources(u):
        doc["units"] = [x for x in doc["units"] if x is not u]
        _drop_reviews(doc, u["id"])
    return _sorted(doc), nid


def place(doc, items, rng=random):
    """Fill's dates: items [(iso, field, path)] each onto that day's date
    (a new one when the day has none), named for what's on it: what
    Split by its tags and Lay it out make (build.fill says where). The
    dates touched."""
    doc = copy.deepcopy(doc)
    touched = set()
    for day, field, path in items:
        u = next((x for x in doc.get("units") or [] if x.get("opens") == day and not x.get("even")), None)
        if u is None:
            if len(doc.get("units") or []) >= UNITS_MAX:
                raise Refused(f"A plan holds up to {UNITS_MAX} sets.")
            u = {"id": new_id(doc, rng), "name": "", "opens": day, "tags": [], "decks": [], "cards": []}
            doc.setdefault("units", []).append(u)
        have = list(u.get(field) or [])
        if path not in have:
            if len(have) >= SOURCES_MAX:
                raise Refused(f"A set holds up to {SOURCES_MAX} {'tags' if field == 'tags' else 'subdecks'}.")
            u[field] = have + [path]
        if not u.get("name"):
            u["name"] = _name(auto_name(u.get("tags") or [], u.get("decks") or []))
        touched.add(u["id"])
    return _sorted(doc), touched


def _drop_reviews(doc, uid):
    if doc.get("reviews"):
        doc["reviews"] = [r for r in doc["reviews"] if r.get("from") != uid and r.get("to") != uid]
        if not doc["reviews"]:
            del doc["reviews"]


def take_off(doc, uid, field, path, keep=False):
    """A tag or subdeck off a date, the date going with it when it was all
    that was on it. keep (Split by its tags, takeOut): the date stays, empty,
    so its parts fill onto it first and it keeps its name, due date, prep,
    to-dos and review days; cleanup after the fill takes it if nothing did."""
    doc = copy.deepcopy(doc)
    u = _unit(doc, uid)
    u[field] = [x for x in u.get(field) or [] if x != path]
    if not keep and not has_sources(u):
        doc["units"] = [x for x in doc["units"] if x is not u]
        _drop_reviews(doc, uid)
    return doc


def migrate_checks(doc):
    """builder.js on load: a date's checkpoint from before review days
    (`check`) is a review day of that date. The doc itself when there's none."""
    if not any(isinstance(u, dict) and u.get("check") for u in doc.get("units") or []):
        return doc
    doc = copy.deepcopy(doc)
    for u in doc["units"]:
        if isinstance(u, dict) and u.get("check"):
            doc.setdefault("reviews", []).append({"day": u["check"], "from": u["id"], "to": u["id"]})
            del u["check"]
    return doc


def cleanup(doc):
    """builder.js cleanup, after a fill: a date with nothing on it goes, and the review days that name it."""
    _cleanup(doc)
    return doc


def name_dates(doc, before, tree=None):
    """renameAll after a change: a date still named for what was on it
    (before: the doc before the change), or with no name, is named for
    what's on it now (B.auto_name). One an author named keeps it, and so
    does one this change named (nameIt), unless it left it blank."""
    was = {u.get("id"): u for u in P.units(before or {})}
    placed_was, placed = B.placed_keys(before or {}, tree), B.placed_keys(doc, tree)
    for u in doc.get("units") or []:
        if not isinstance(u, dict):
            continue
        old, name = was.get(u.get("id")), str(u.get("name") or "").strip()
        if not name:
            auto = True
        elif old is None:
            auto = name == auto_name(u.get("tags") or [], u.get("decks") or [])  # an edit's first name, not one typed
        else:
            auto = old.get("name") == u.get("name") and old.get("name") == B.auto_name(before, tree, old, placed_was)
        if auto:
            u["name"] = _name(B.auto_name(doc, tree, u, placed))
    return doc


# ---- 3.9.3: Lay it out: the pace, the start, the end, the plan's own tags ----

COVER_MAX = 500                                # plans.ts COVER_MAX


def set_pace(doc, mode, days, daily=None, cover=None):
    """The builder's pace (plans.ts pace): how it's laid out (an end date,
    cards a day, or each day placed), its study days, cards a day, and
    what it covers ("tag:PATH", "deck:PATH"; in the order given, as the
    builder saves them in the deck's, 500 at most as the server keeps)."""
    if mode not in ("end", "daily", "placed"):
        raise Refused("That isn't a pace.")
    days = [1 if x else 0 for x in days]
    if len(days) != 7 or not any(days):
        raise Refused("Pick a study day.")
    doc = copy.deepcopy(doc)
    pace = {"mode": mode, "days": days}
    if daily is not None:
        pace["daily"] = max(1, min(5000, int(daily)))
    if cover:
        pace["cover"] = list(dict.fromkeys(cover))[:COVER_MAX]
    doc["pace"] = pace
    return doc


def shift_all(doc, days):
    """The start moved: every date, review day, event and the end date with it."""
    doc = copy.deepcopy(doc)
    for u in doc.get("units") or []:
        for k in ("opens", "due", "check"):
            if u.get(k):
                u[k] = _later(u[k], days)
    for r in doc.get("reviews") or []:
        r["day"] = _later(r["day"], days)
    for e in doc.get("events") or []:
        e["day"] = _later(e["day"], days)
    if doc.get("end"):
        doc["end"] = _later(doc["end"], days)
    return _sorted(doc)


def set_end(doc, end):
    """The plan's end (the exam, the course's last day), or none: its
    review-only days at the end go with it."""
    doc = copy.deepcopy(doc)
    if end:
        doc["end"] = _day(end).isoformat()
    else:
        doc.pop("end", None)
        if doc.get("phases"):
            doc["phases"]["taper"] = 0
            if not doc["phases"].get("catchup"):
                del doc["phases"]
    return doc


def set_phases(doc, catchup=None, taper=None):
    """Catch-up weeks (every 3rd or 4th: nothing new) and review-only days
    before the end date (plans.ts phases)."""
    doc = copy.deepcopy(doc)
    ph = dict(doc.get("phases") or {"catchup": 0, "taper": 0})
    if catchup is not None:
        if catchup not in (0, 2, 3, 4, 5, 6, 7, 8):
            raise Refused("Catch-up weeks come every 2nd to 8th week.")
        ph["catchup"] = catchup
    if taper is not None:
        if not 0 <= int(taper) <= 60:
            raise Refused("Review-only days are 0 to 60.")
        if taper and not doc.get("end"):
            raise Refused("Review-only days run up to the end date: set one first.")
        ph["taper"] = int(taper)
    ph = {"catchup": int(ph.get("catchup") or 0), "taper": int(ph.get("taper") or 0)}
    if ph["catchup"] or ph["taper"]:
        doc["phases"] = ph
    else:
        doc.pop("phases", None)
    return doc


def _tag_re(path, flags=re.I):
    """tagRe: a tag where it sits in a search, whole (SLG_1 isn't in SLG_12),
    as Tags.ankiSearch writes it or plain."""
    quoted = B.anki_search("tag", path)[1:-1]
    return re.compile(f"({re.escape(quoted)}|{re.escape('tag:' + str(path))})(?=::|$|[\\s\")])", flags)


def _drop_search(u, q):
    u["search"] = [x for x in u.get("search") or [] if x != q]
    if isinstance(u.get("sn"), dict):
        u["sn"] = {k: v for k, v in u["sn"].items() if k != q}
    for k in ("search", "sn"):
        if k in u and not u[k]:
            del u[k]


def _sync_cuts(doc):
    """syncCuts: each date's cuts as the plan's tags are now: one whose tag
    went is its whole tag again; a renamed tag's cut searches by its new name."""
    tags = {t.get("id"): t for t in P.plan_tags(doc)}
    for u in doc.get("units") or []:
        if not u.get("cut"):
            u.pop("cut", None)
            continue
        keep = []
        for c in u["cut"]:
            t = tags.get(c.get("in"))
            if t is None:
                _drop_search(u, c.get("q"))
                u["tags"] = list(dict.fromkeys(list(u.get("tags") or []) + [c["tag"]]))
                continue
            q = B.cut_q(c["tag"], P.tag_path(doc, t))
            if q != c.get("q"):
                was = (u.get("sn") or {}).get(c.get("q"))
                _drop_search(u, c.get("q"))
                if was is not None:
                    u["sn"] = dict(u.get("sn") or {}, **{q: was})
                c["q"] = q
            if q not in (u.get("search") or []):
                u["search"] = list(u.get("search") or []) + [q]
            keep.append(c)
        if keep:
            u["cut"] = keep
        else:
            u.pop("cut", None)


def _cleanup(doc):
    """cleanup: a date with nothing on it goes, and the review days that name it."""
    doc["units"] = [u for u in doc.get("units") or [] if has_sources(u)]
    ids = {u["id"] for u in doc["units"]}
    if doc.get("reviews"):
        doc["reviews"] = [r for r in doc["reviews"] if r.get("from") in ids and r.get("to") in ids]
        if not doc["reviews"]:
            del doc["reviews"]


def _retag(doc, old, new):
    """retag: a plan tag renamed (or gone, new None): the dates using it
    follow, as a tag and in their searches, and so does a note on it."""
    low = str(old).lower()
    nq = B.anki_search("tag", new)[1:-1] if new else None
    for u in doc.get("units") or []:
        if any(str(t).lower() == low for t in u.get("tags") or []):
            u["tags"] = ([new if str(t).lower() == low else t for t in u["tags"]] if new
                         else [t for t in u["tags"] if str(t).lower() != low])
        for q in list(u.get("search") or []):
            if not _tag_re(old).search(q):
                continue
            if not nq:
                _drop_search(u, q)
                continue
            q2 = _tag_re(old).sub(lambda m: nq, q)
            u["search"] = [q2 if x == q else x for x in u["search"]]
            if (u.get("sn") or {}).get(q) is not None:
                u["sn"][q2] = u["sn"].pop(q)
    rs = [r for r in doc.get("remarks") or [] if isinstance(r, dict)]
    if any(r.get("tag") and str(r["tag"]).lower() == low for r in rs):
        rs = ([dict(r, tag=new) if r.get("tag") and str(r["tag"]).lower() == low else r for r in rs] if new
              else [r for r in rs if not (r.get("tag") and str(r["tag"]).lower() == low)])
        if rs:
            doc["remarks"] = rs
        else:
            doc.pop("remarks", None)
    _sync_cuts(doc)
    _cleanup(doc)


def rename_plan_tag(doc, tid, name):
    """One of the plan's own tags renamed (40 characters, a name no other has):
    every date, search and note using it follows."""
    doc = copy.deepcopy(doc)
    t = next((x for x in P.plan_tags(doc) if x.get("id") == tid), None)
    if t is None:
        raise Refused("That tag isn't the plan's any more.")
    v = _cut(" ".join(str(name or "").split()), 40).strip()
    if not v:
        raise Refused("A tag needs a name.")
    clash = next((x for x in P.plan_tags(doc) if x is not t and P.tag_part(x.get("name")).lower() == P.tag_part(v).lower()), None)
    if clash is not None:
        raise Refused(f"There's a tag called {clash.get('name')} already.")
    old, before = P.tag_path(doc, t), copy.deepcopy(doc)
    t["name"] = v
    _retag(doc, old, P.tag_path(doc, t))
    return name_dates(doc, before)  # renameAll: "Heart Failure · SLG 12" follows the tag


def drop_say(doc, tid):
    """dropSay: what deleting a plan tag does to the dates, said first."""
    t = next((x for x in P.plan_tags(doc) if x.get("id") == tid), None)
    if t is None:
        return ""
    path = P.tag_path(doc, t)

    def uses(u):
        return (any(str(x).lower() == path.lower() for x in u.get("tags") or [])
                or any(c.get("in") == tid for c in u.get("cut") or [])
                or any(_tag_re(path).search(q) for q in u.get("search") or []))

    def bare(u):
        return not (any(str(x).lower() != path.lower() for x in u.get("tags") or []) or u.get("decks") or u.get("cards")
                    or u.get("nids") or u.get("cids") or u.get("notes") or u.get("cut")
                    or any(not _tag_re(path).search(q) for q in u.get("search") or []))
    us = sorted((u for u in P.units(doc) if uses(u)), key=lambda u: str(u["opens"]))
    if not us:
        return f"{t.get('name')} is on no sets."

    def listed(xs):
        return ", ".join(P.fmt_day(u["opens"]) for u in xs[:4]) + (f" and {len(xs) - 4} more" if len(xs) > 4 else "")
    gone = [u for u in us if bare(u)]
    out = f"{t.get('name')} is on {len(us)} set{'s' if len(us) != 1 else ''}: {listed(us)}."
    if gone:
        who = ("It has" if len(us) == 1 else "They have") if len(gone) == len(us) else f"{listed(gone)} ha{'s' if len(gone) == 1 else 've'}"
        out += f" {who} nothing else, so {'it goes' if len(gone) == 1 else 'they go'}, to-dos too."
    if any(c.get("in") == tid for u in us for c in u.get("cut") or []):
        out += " A tag kept to it there is all of that tag again."
    return out


def delete_plan_tag(doc, tid):
    """One of the plan's own tags deleted: off every date (a cut kept to it
    is its whole tag again), a date with nothing else going with it."""
    doc = copy.deepcopy(doc)
    t = next((x for x in P.plan_tags(doc) if x.get("id") == tid), None)
    if t is None:
        raise Refused("That tag isn't the plan's any more.")
    path, before = P.tag_path(doc, t), copy.deepcopy(doc)
    rest = [x for x in doc.get("tags") or [] if x.get("id") != tid]
    if rest:
        doc["tags"] = rest
    else:
        doc.pop("tags", None)
    _retag(doc, path, None)
    return name_dates(doc, before)  # renameAll


# ---- 3.9.3: Settings and Progress ----

_DECK_URL = re.compile(r"https://[\x21\x23-\x26\x28-\x2e\x30-\x3b\x3d\x3f-\x7e][\x21\x23-\x26\x28-\x3b\x3d\x3f-\x7e]*")


def deck_link(url):
    """deckLink (app.js), plans.ts DECK_URL: https, printable, no space or quote, 300 at most."""
    return isinstance(url, str) and len(url) <= 300 and bool(_DECK_URL.fullmatch(url))


def set_deck_url(doc, url):
    """Where to get the deck (its link page, poster, and Anki for anyone with
    no deck by its name), or none."""
    url = str(url or "").strip()
    if url and not deck_link(url):
        raise Refused("A link starts with https://, has no spaces or quotes, and is 300 characters at most.")
    doc = copy.deepcopy(doc)
    if url:
        doc["deckUrl"] = url
    else:
        doc.pop("deckUrl", None)
    return doc


def breather(doc, today, days):
    """classHints' Give the class a day: every date still to come one study
    day later, and the review days after today; events stay on their days.
    (doc, how many dates moved)."""
    dd = B._Days(doc, days)
    doc = copy.deepcopy(doc)
    later = [u for u in doc.get("units") or [] if str(u.get("opens") or "") > today]
    for u in sorted(later, key=lambda u: str(u["opens"]), reverse=True):
        k = (_day(dd.next(u["opens"])) - _day(u["opens"])).days
        for f in ("opens", "due", "check"):
            if u.get(f):
                u[f] = _later(u[f], k)
    dr = B._Days(doc, days)  # the builder's nextStudy on the plan as its dates now are (a catch-up week counts from its first)
    for r in doc.get("reviews") or []:
        if str(r.get("day") or "") > today:
            r["day"] = dr.next(r["day"])
    return _sorted(doc), len(later)


def next_year_name(name):
    """nextYear's named: "… (next year)" within a plan name's 60, an earlier
    "(next year)" or "(copy)" off, cut at a word."""
    b = re.sub(r"\s*\((?:next year|copy)\)\s*$", "", str(name or ""), flags=re.I).strip()
    if len(b) > 48:
        b = b[:48]
        sp = b.rfind(" ")
        if sp > 24:
            b = b[:sp]
    return f"{b.rstrip()} (next year)"


def first_day(doc):
    """nextYear's firstOf: the plan's first date or event."""
    days = sorted([str(u.get("opens")) for u in doc.get("units") or [] if u.get("opens")]
                  + [str(e.get("day")) for e in doc.get("events") or [] if isinstance(e, dict) and e.get("day")])
    return days[0] if days else None


def behind(doc, progress, today, total_of=None):
    """classHints: a date most of the class hasn't finished two days after it
    (3 or more in its squad, 3.9.5: an author on the team among them, and 2
    sharing besides me; under half of the followers sharing done), the latest
    two. [(unit, done, days late)]."""
    sharing = int(progress.get("sharing") or 0)
    if int(progress.get("inSquad", sharing) or 0) < 3 or int(progress.get("others", sharing) or 0) < 2 or not sharing:
        return []
    units = progress.get("units") or {}
    out = []
    for u in P.units(doc):
        end = u.get("due") or u.get("opens")
        done = int((units.get(u["id"]) or {}).get("done") or 0)
        if _later(end, 2) <= today and done < sharing / 2:
            out.append((u, done, (_day(today) - _day(end)).days))
    return sorted(out, key=lambda x: str(x[0].get("due") or x[0]["opens"]), reverse=True)[:2]


CLASS_SHOWN = 4  # sets Insights lists as where the class fell behind


def class_lines(doc, progress, today):
    """3.9.9 (the plans review's mock 5; Sam: "yes"): Insights' lines for an
    author on where the plan's squad fell behind: each set that ended two
    days ago or more with people still not through it, the worst first,
    CLASS_SHOWN at most. By the counts' own rule (3 in its squad, 2 besides
    me): under it, one line saying so; nothing at all with nobody sharing."""
    if not isinstance(progress, dict):
        return []
    sharing = int(progress.get("sharing") or 0)
    squad = int(progress.get("inSquad", sharing) or 0)
    if not sharing and not squad:
        return []
    if squad < 3 or int(progress.get("others", sharing) or 0) < 2 or not sharing:
        return [f"{squad:,} {'is' if squad == 1 else 'are'} in its squad: where they fall behind shows from 3."]
    units, rows = progress.get("units") or {}, []
    for u in P.units(doc):
        end = u.get("due") or u.get("opens")
        if not end or _later(end, 2) > today:
            continue
        left = sharing - int((units.get(u["id"]) or {}).get("done") or 0)
        if left > 0:
            rows.append((left, str(end), str(u.get("name") or "?")))
    if not rows:
        return [f"Its squad is keeping up: all {sharing:,} sharing are through every set that's ended."]
    rows.sort(key=lambda r: (-r[0], r[1]))
    out = [f"Where its squad fell behind ({sharing:,} sharing):"]
    out += [f"{name}: {left:,} of {sharing:,} not through it yet ({P.fmt_day(day)})." for left, day, name in rows[:CLASS_SHOWN]]
    if len(rows) > CLASS_SHOWN:
        out.append(f"And {len(rows) - CLASS_SHOWN:,} more set{'s' if len(rows) - CLASS_SHOWN != 1 else ''} with someone behind.")
    return out


# ---- plans end to end: the builder's site-only edits, in Anki ----

def _cut_key(u, key):
    """A search that is a cut's (its q) is that cut: it goes as one."""
    if key and key[0] == "search":
        c = next((c for c in u.get("cut") or [] if c.get("q") == key[1]), None)
        if c is not None:
            return ("cut", c.get("tag"), c.get("in"))
    return key


def _bracket(q):
    """A search with an OR at its top in brackets, so what's added after it
    holds for all of it: Anki reads `A OR B -C` as `A OR (B -C)`."""
    depth, quoted, word, top_or = 0, False, "", False
    for ch in str(q) + " ":
        if ch == '"':
            quoted = not quoted
        if quoted:
            word = ""
            continue
        if ch in "()":
            depth += 1 if ch == "(" else -1
        if ch.isspace() or ch in "()":
            if depth == 0 and word.lower() == "or":
                top_or = True
            word = ""
        else:
            word += ch
    return f"({q})" if top_or else q


def leave_out(doc, uid, key, other, n=None):
    """Leave out cards also tagged (the builder's Overlap, "but not"): one of
    a date's sources less the cards also tagged `other` (a deck tag, or one
    of the plan's own by its Anki tag), as the search the builder writes,
    "tag:A" -"tag:B" (searchName: "SLG 12 but not Pharm"), in the source's
    place: a tag or subdeck comes off for it, a search gets the -"tag:B" (a
    tag without its extras: "Cardio but not Extra, Pharm"), a cut becomes
    its search with it (a cut is a whole tag kept to a plan tag). Picked
    cards are picked one by one. n: the cards it keeps here (the builder's
    count, sn; the author's Anki counts it again). Every add-on since 3.3
    opens the same cards by the search."""
    doc = copy.deepcopy(doc)
    u = _unit(doc, uid)
    other = _path(other)
    low = other.lower()
    neg = f"-{B.anki_search('tag', other)}"
    key = _cut_key(u, key)
    k = key[0] if key else ""
    have = _searches(u)

    def covers(path):  # the tag itself or one above it: nothing would be left
        p = str(path).lower()
        return p == low or p.startswith(low + "::")
    at = None
    if k == "deck":
        # a subdeck is read in each follower's own deck (deck_cards); a search runs as typed, so
        # "deck:<my path>" finds nothing where theirs sits elsewhere (3.9.6's review)
        raise Refused("A subdeck's cards can't be left out by a tag: add its tag instead, then leave them out of that.")
    if k == "tag":
        if key[1] not in (u.get("tags") or []):
            raise Refused("That's not on this set any more.")
        if covers(key[1]):
            raise Refused("Every one of its cards is tagged that: take it off instead.")
        q = f"{B.anki_search(k, key[1])} {neg}"
    elif k == "search":
        if key[1] not in have:
            raise Refused("That's not on this set any more.")
        if neg in key[1]:
            raise Refused("It leaves those out already.")
        q, at = f"{_bracket(key[1])} {neg}", have.index(key[1])
    elif k == "cut":
        c = next((c for c in u.get("cut") or [] if c.get("tag") == key[1] and c.get("in") == key[2]), None)
        if c is None:
            raise Refused("That's not on this set any more.")
        if covers(c["tag"]):
            raise Refused("Every one of its cards is tagged that: take it off instead.")
        q, at = f"{c['q']} {neg}", have.index(c["q"]) if c.get("q") in have else None
    else:
        raise Refused("Picked cards are picked one by one: take off the ones to leave out.")
    if len(q) > B.SEARCH_LEN:
        raise Refused(f"A search is at most {B.SEARCH_LEN} characters.")
    if q in have:
        raise Refused("That's on this set already.")
    if at is None and len(have) >= B.SEARCH_MAX:
        raise Refused(f"A set holds up to {B.SEARCH_MAX} searches and cuts.")
    if k == "tag":
        u["tags"] = [x for x in u.get("tags") or [] if x != key[1]]
        u["search"] = have + [q]
    else:
        old = have[at] if at is not None else c["q"]
        u["search"] = have[:at] + [q] + have[at + 1:] if at is not None else have + [q]
        if isinstance(u.get("sn"), dict):
            u["sn"] = {x: v for x, v in u["sn"].items() if x != old}
        if k == "cut":
            u["cut"] = [x for x in u.get("cut") or [] if x is not c]
    if isinstance(n, int) and not isinstance(n, bool) and n >= 0:
        u["sn"] = dict(u.get("sn") or {}, **{q: n})
    for f in ("cut", "sn"):
        if f in u and not u[f]:
            del u[f]
    return doc


def move_source(doc, uid, key, to=None, day=None, rng=random):
    """moveChip: one of a date's sources (model.sources' key) onto another
    date (to: its id), or onto a day (day: that day's date, a new one when
    it has none, as the builder's unitOn; never an evenly spread one), off
    the date it was on. A tag or subdeck goes as it is; a search with its
    count; a cut with its search, or just goes onto a date with that whole
    tag; picked cards all together, IDs and single cards. The date it was on
    goes when nothing's left on it (the builder's cleanup), its review days
    with it. (doc, the date it's on now, whether the first went)."""
    doc = copy.deepcopy(doc)
    u = _unit(doc, uid)
    key = _cut_key(u, key)
    k = key[0] if key else ""
    made = False
    if to:
        if to == uid:
            raise Refused("It's on that set already.")
        t = _unit(doc, to)
    else:
        day = _day(day).isoformat()
        if day == u.get("opens") and not u.get("even"):
            raise Refused("It's on that day already.")
        t = next((x for x in doc.get("units") or [] if x.get("opens") == day and not x.get("even") and x is not u), None)
        if t is None:
            if len(doc.get("units") or []) >= UNITS_MAX:
                raise Refused(f"A plan holds up to {UNITS_MAX} sets.")
            t, made = {"id": new_id(doc, rng), "name": "", "opens": day, "tags": [], "decks": [], "cards": []}, True
            doc["units"].append(t)
    gone = "That's not on this set any more."
    if k in ("tag", "deck", "questions"):
        field = "decks" if k == "deck" else "tags"
        paths = [str(p) for p in key[1]] if k == "questions" else [str(key[1])]
        if not paths or not all(p in (u.get(field) or []) for p in paths):
            raise Refused(gone)
        moved = list(t.get(field) or [])
        for p in paths:
            if p not in moved:
                if len(moved) >= SOURCES_MAX:
                    raise Refused(f"A set holds up to {SOURCES_MAX} {'tags' if field == 'tags' else 'subdecks'}.")
                moved.append(p)
        t[field] = moved
        u[field] = [x for x in u.get(field) or [] if x not in paths]
    elif k == "search":
        q = key[1]
        if q not in _searches(u):
            raise Refused(gone)
        if q not in _searches(t):
            if len(_searches(t)) >= B.SEARCH_MAX:
                raise Refused(f"A set holds up to {B.SEARCH_MAX} searches and cuts.")
            t["search"] = _searches(t) + [q]
        if (u.get("sn") or {}).get(q) is not None:
            t["sn"] = dict(t.get("sn") or {}, **{q: u["sn"][q]})
        _take_search(u, q)
    elif k == "cut":
        c = next((x for x in u.get("cut") or [] if x.get("tag") == key[1] and x.get("in") == key[2]), None)
        if c is None:
            raise Refused(gone)
        has = c["tag"] in (t.get("tags") or []) or any(x.get("tag") == c["tag"] and x.get("in") == c["in"] for x in t.get("cut") or [])
        n0 = (u.get("sn") or {}).get(c.get("q"))
        if not has:
            if c["q"] not in _searches(t):
                if len(_searches(t)) >= B.SEARCH_MAX:
                    raise Refused(f"A set holds up to {B.SEARCH_MAX} searches and cuts.")
                t["search"] = _searches(t) + [c["q"]]
            t["cut"] = list(t.get("cut") or []) + [dict(c)]
            if n0 is not None:
                t["sn"] = dict(t.get("sn") or {}, **{c["q"]: n0})
        u["cut"] = [x for x in u.get("cut") or [] if x is not c]
        _take_search(u, c["q"])
        if "cut" in u and not u["cut"]:
            del u["cut"]
    elif k == "picks":
        if not P.picks(u):
            raise Refused(gone)
        if any(u.get(x) for x in ("nids", "cids", "notes")):
            for x in ("nids", "cids", "notes"):
                every = list(dict.fromkeys(list(t.get(x) or []) + list(u.get(x) or [])))
                if len(every) > B.IDS_MAX:
                    raise Refused(f"A set takes up to {B.IDS_MAX:,} IDs of each kind.")
                if every:
                    t[x] = every
            t.pop("idn", None)
            t.pop("idr", None)
        have = {(str(g), int(o)) for g, o in t.get("cards") or []}
        t["cards"] = list(t.get("cards") or [])
        for g, o in u.get("cards") or []:
            if (str(g), int(o)) not in have:
                have.add((str(g), int(o)))
                t["cards"].append([str(g), int(o)])
        u["cards"] = []
        for x in ("nids", "cids", "notes", "idn", "idr", "pl"):
            u.pop(x, None)
        t.pop("pl", None)
    else:
        raise Refused("Move which of its cards?")
    went = not has_sources(u)
    if went:
        doc["units"] = [x for x in doc["units"] if x is not u]
        _drop_reviews(doc, u["id"])
    if made:
        t["name"] = _name(B.auto_name(doc, None, t, B.placed_keys(doc)))
    return _sorted(doc), t["id"], went


def resource_plan(idx, tree, path, start, days=(1, 1, 1, 1, 1, 0, 0), daily=None, by=None, only=None,
                  deck=None, name=None, exam=None, rng=random):
    """A resource, chapter by chapter (plans end to end: New plan's window): a part of the deck,
    `path` (a resource's tag, its chapters the tags under it), as a plan of
    its own. A date a chapter (model.chapters: each tag right under it that
    isn't a bank's question, in the deck's order), and, when there are any,
    the cards no chapter holds as the last date, "Path Book · the rest" (the
    tag less every tag under it, "tag:X" -"tag:X::*"; less its chapters,
    when a bank's questions sit under it too); a part with no chapters is
    one date. only (a deck tag: a high-yield one): the plan's one own tag,
    holding it, and each date kept to it (3.8.1 cuts, their search in
    `search`, so an older add-on opens the same cards), its rest too.
    Laid out as the builder's Fill lays chapters (build.fill, apart: a
    date of its own each), about `daily` new cards a study day, or to fit
    by `by` (a day; its pace the fewest a day that fit, as Fill to an end
    date finds it); a chapter bigger than a day's spread evenly over its
    days (`even`, to its due date). exam: a name for an event on `by`, the
    dates ending the day before it, each prepping for it. Days off: a
    plan's doc has none (its study days are a week's). idx: plans.DeckIndex
    (its cards; None counts by the tree, and takes no Only); tree:
    build.Tree. (doc, summary): summary {lessons, new, first, last,
    busiest, busiest_day, daily, rest, left, note, dates: [{id, name,
    opens, due, n}]}."""
    from . import model as M
    days = [1 if x else 0 for x in days][:7]
    if len(days) != 7 or not any(days):
        raise Refused("Pick a study day.")
    if tree is None:
        raise Refused("The deck isn't in this Anki.")
    path, start = _path(path), _day(start).isoformat()
    by = _day(by).isoformat() if by else None
    if only and idx is None:
        raise Refused("Only reads the deck's cards: open the deck here first.")
    only = _path(only) if only else None
    name = " ".join(str(name or M.resource_name(path, only)).split())[:60] or "Plan"
    keep = idx.tag_cards(only) if only else None

    def cards(p):
        c = set(idx.tag_cards(p))
        return c & keep if keep is not None else c
    whole = cards(path) if idx is not None else None
    lessons, held = [], set()
    for p in M.chapters(tree, path):
        c = cards(p) if idx is not None else set()
        n = len(c) if idx is not None else tree.n(f"tag:{p}")
        if n:
            lessons.append({"path": p, "n": n, "cids": c})
            held |= c
    single = not lessons
    if single:
        n = len(whole) if idx is not None else tree.n(f"tag:{path}")
        lessons = [{"path": path, "n": n, "cids": whole or set()}]
        rest_n = 0
    else:
        rest_n = len(whole - held) if idx is not None else max(0, tree.n(f"tag:{path}") - sum(x["n"] for x in lessons))
    if not sum(x["n"] for x in lessons) + rest_n:
        raise Refused(f"None of its cards are also tagged {B.tag_word(only.split('::')[-1])}." if only
                      else "That part has no cards here.")
    doc = {"deck": str(deck or (idx.name if idx is not None else "") or ""), "units": []}
    if not doc["deck"]:
        raise Refused("Which deck?")
    ptag = ppath = None
    if only:
        doc["tagroot"] = P.tag_root(name)
        ptag = {"id": "", "name": _cut(B.tag_word(only.split("::")[-1]), 40).strip() or "Only", "tags": [only]}
        ppath = P.tag_path(doc, ptag)
    rest_q = None
    if rest_n:
        head = f"{B.anki_search('tag', ppath)} " if ppath else ""
        if not any(M.is_question(B.path_of(k)) for k in tree.kids(f"tag:{path}")):
            rest_q = f"{head}{B.anki_search('tag', path)} -{B.anki_search('tag', path)[:-1]}::*\""
        else:
            q = head + B.without_q(path, [x["path"] for x in lessons])
            rest_q = q if len(q) <= B.SEARCH_LEN else None
    items = [{"key": f"tag:{x['path']}", "n": x["n"]} for x in lessons if x["n"]]
    if rest_q:
        items.append({"key": f"tag:{path}", "n": rest_n, "rest": True})
    end = (_later(by, -1) if exam else by) if by else None
    if end:
        dd = B._Days(doc, days)
        first = dd.first(start)
        n_days = dd.count(first, end) if first <= end else 0
        if not n_days:
            raise Refused(f"No study days from {P.fmt_day(start)} to {P.fmt_day(end)}.")
        cap = max(1, min(5000, math.ceil(sum(x["n"] for x in items) / n_days)))
    else:
        cap = max(1, min(5000, int(daily or 20)))
    ids = []

    def nid():
        ids.append(new_id(doc, rng))
        return ids[-1]
    for tries in range(8):
        doc["units"], ids[:] = [], []
        r = B.fill(doc, [dict(x, even=x["n"] > cap) for x in items], start, end, cap, days, nid, end, apart=True)
        if not end or not (r["left"] or r["clipped"]) or r["note"] or tries >= 7:
            break
        cap = min(5000, math.ceil(cap * 1.1))
    by_id = {u["id"]: u for u in doc["units"]}
    if ptag:
        ptag["id"] = new_id(doc, rng)
        doc["tags"] = [ptag]
    for x, uid in zip(items, ids):
        u, p = by_id[uid], B.path_of(x["key"])
        if x.get("rest"):
            u["tags"], u["search"], u["sn"] = [], [rest_q], {rest_q: x["n"]}
            u["name"] = _name(f"{B.tag_word(path.split('::')[-1])} · the rest")
            continue
        u["name"] = _name(B.tag_word(p.split("::")[-1]))
        if ptag:
            q = B.cut_q(p, ppath)
            u["tags"], u["cut"], u["search"], u["sn"] = [], [{"tag": p, "in": ptag["id"], "q": q}], [q], {q: x["n"]}
        elif idx is not None:
            u["n"] = len(idx.tag_cards(p))  # the builder's count of a tag (recount's)
    doc = set_pace(doc, "end" if by else "daily", days, cap)
    if by:
        doc = set_end(doc, by)
        if exam:
            doc, eid = add_event(doc, by, exam, rng)
            for u in doc["units"]:
                u["for"] = eid
    placed = items[:len(ids)]
    n_of = {uid: x["n"] for x, uid in zip(placed, ids)}
    work = B.work_map(doc, lambda u: n_of.get(u["id"], 0), days)
    top = max(sorted(work), key=lambda d: work[d]["n"]) if work else None
    if idx is not None:
        got = set()
        for x in placed:
            got |= (whole - held) if x.get("rest") else next(y["cids"] for y in lessons if y["path"] == B.path_of(x["key"]))
        new = len(got)
    else:
        new = sum(x["n"] for x in placed)
    left_n = sum(x["n"] for x in r["left"]) + (rest_n if rest_n and not rest_q else 0)
    words = []
    if r["left"]:
        words.append(f"{r['note'] + ' ' if r['note'] else ''}{sum(x['n'] for x in r['left']):,} didn't fit"
                     f"{' by ' + P.fmt_day(end) if end and not r['note'] else ''}: {B.left_names(r['left'])}.")
    if rest_n and not rest_q:
        words.append(f"{rest_n:,} of its cards are under none of its chapters: no set has them.")
    us = sorted(doc["units"], key=lambda u: str(u.get("opens")))
    summary = {"lessons": len(ids), "new": new, "first": us[0]["opens"] if us else None, "last": B.last_day(doc) or None,
               "busiest": work[top]["n"] if top else 0, "busiest_day": top, "daily": cap,
               "rest": rest_n if any(x.get("rest") for x in placed) else 0, "left": left_n, "note": " ".join(words),
               "dates": [{"id": u["id"], "name": u["name"], "opens": u["opens"], "due": u.get("due"), "n": n_of.get(u["id"], 0)}
                         for u in us]}
    return doc, summary
