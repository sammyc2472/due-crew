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
day. The plan's lines every week, a note for followers on a tag. A save is
the builder's: PUT /plans/{id} with the version it started from
(remote.save)."""

import copy
import datetime
import random

from .. import plans as P
from . import build as B

SOURCES_MAX = 50   # plans.ts SOURCES_MAX: tags, and subdecks, a date
UNITS_MAX = 200    # plans.ts UNITS_MAX
NAME_MAX = 60      # validate.ts NAME_MAX
PATH_MAX = 200     # plans.ts PATH_MAX
EVENTS_MAX = 200   # plans.ts EVENTS_MAX
REVIEWS_MAX = 60   # plans.ts REVIEWS_MAX
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
        raise Refused("That date isn't on the plan any more.")
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
        raise Refused("A date needs a name.")
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
    """A new date's name from what's on it, as the builder names one: the
    first source's last part read, "+ 2 more"."""
    srcs = list(tags) + list(decks)
    if not srcs:
        return "?"
    first = P._word(str(srcs[0]).split("::")[-1])
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
                raise Refused(f"A date holds up to {SOURCES_MAX} {'tags' if field == 'tags' else 'subdecks'}.")
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
        raise Refused("That's the last thing on this date: delete the date instead.")
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
            raise Refused("The due date is before the date opens.")
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
        raise Refused(f"A plan holds up to {UNITS_MAX} dates.")
    if not (tags or decks):
        raise Refused("Pick something for the date first.")
    uid = new_id(doc, rng)
    doc.setdefault("units", []).append({"id": uid, "name": _name(name or auto_name(tags, decks)),
                                        "opens": _day(opens).isoformat(), "tags": [], "decks": [], "cards": []})
    doc, _n = add_sources(doc, uid, tags, decks)
    return _sorted(doc), uid


def add_event(doc, day, name, rng=random):
    """A named day (a quiz, the exam) the dates prep for. (doc, its id)."""
    doc = copy.deepcopy(doc)
    if len(doc.get("events") or []) >= EVENTS_MAX:
        raise Refused(f"A plan holds up to {EVENTS_MAX} quizzes and exams.")
    eid = new_id(doc, rng)
    doc.setdefault("events", []).append({"id": eid, "day": _day(day).isoformat(), "name": _name(name)})
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
        for field, word in (("tags", "tags"), ("decks", "subdecks"), ("cut", "cuts"), ("search", "searches"),
                            ("cards", "single cards"), ("notes", "notes"), ("nids", "note IDs"), ("cids", "card IDs")):
            got = len(y.get(field) or []) - len(x.get(field) or [])
            if got > 0:
                out.append(f"{day}: added {got:,} {word if got != 1 else word[:-1]}")
            elif got < 0:
                out.append(f"{day}: took off {-got:,} {word if got != -1 else word[:-1]}")
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
        raise Refused("That search is on this date already.")
    if len(have) >= B.SEARCH_MAX:
        raise Refused(f"A date holds up to {B.SEARCH_MAX} searches and cuts.")
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
        raise Refused(f"A date takes up to {B.IDS_MAX:,} IDs of each kind.")
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
            raise Refused(f"A date takes up to {B.IDS_MAX:,} notes.")
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
            raise Refused("Give it a due date after it opens first.")
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
        raise Refused(f"A date keeps {B.TODO_MAX} lines to tick.")
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
        raise Refused("A review day comes after the dates it reviews.")
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
    if len(_searches(u)) >= B.SEARCH_MAX:
        raise Refused(f"A date holds up to {B.SEARCH_MAX} searches and cuts.")
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
                raise Refused(f"A date holds up to {B.SEARCH_MAX} searches and cuts.")
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
        raise Refused("That's not on this date any more.")
    if len(doc.get("units") or []) >= UNITS_MAX:
        raise Refused(f"A plan holds up to {UNITS_MAX} dates.")
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
                raise Refused(f"A plan holds up to {UNITS_MAX} dates.")
            u = {"id": new_id(doc, rng), "name": "", "opens": day, "tags": [], "decks": [], "cards": []}
            doc.setdefault("units", []).append(u)
        have = list(u.get(field) or [])
        if path not in have:
            if len(have) >= SOURCES_MAX:
                raise Refused(f"A date holds up to {SOURCES_MAX} {'tags' if field == 'tags' else 'subdecks'}.")
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


def take_off(doc, uid, field, path):
    """A tag or subdeck off a date, the date going with it when it was all
    that was on it (Split by its tags moves it to its parts)."""
    doc = copy.deepcopy(doc)
    u = _unit(doc, uid)
    u[field] = [x for x in u.get(field) or [] if x != path]
    if not has_sources(u):
        doc["units"] = [x for x in doc["units"] if x is not u]
        _drop_reviews(doc, uid)
    return doc


def name_dates(doc, ids, before=None):
    """renameAll, for these dates: one with no name, or still named for what
    was on it (before: the doc before the change), is named for what's on
    it now. A date an author named keeps its name."""
    was = {u.get("id"): u for u in (before or {}).get("units") or [] if isinstance(u, dict)}
    for u in doc.get("units") or []:
        if u.get("id") not in ids:
            continue
        old = was.get(u["id"])
        auto = (not str(u.get("name") or "").strip() or old is None
                or old.get("name") == auto_name(old.get("tags") or [], old.get("decks") or []))
        if auto and (u.get("tags") or u.get("decks")):
            u["name"] = _name(auto_name(u.get("tags") or [], u.get("decks") or []))
        elif not str(u.get("name") or "").strip():
            u["name"] = "Date"
    return doc
