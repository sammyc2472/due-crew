"""Labs (docs/planner.md): what an author changes in a plan from the plan
window, on the doc as the server keeps it (GET /plans/{id}, every field),
so a save sends back everything it didn't touch. Pure: each takes a doc and
returns a new one, or raises Refused with the words to show. The server
still checks everything (plans.ts planDoc); these say it first, in words.

The edits the window makes: a deck tag or subdeck onto a date, one off it,
a date renamed, moved (its due date and checkpoint with it) or given a due
date, a new date, a date deleted. A save is the builder's: PUT /plans/{id}
with the version it started from (remote.save)."""

import copy
import datetime
import random

from .. import plans as P

SOURCES_MAX = 50   # plans.ts SOURCES_MAX: tags, and subdecks, a date
UNITS_MAX = 200    # plans.ts UNITS_MAX
NAME_MAX = 60      # validate.ts NAME_MAX
PATH_MAX = 200     # plans.ts PATH_MAX
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
        for field, word in (("tags", "tags"), ("decks", "subdecks"), ("cut", "cuts")):
            got = len(y.get(field) or []) - len(x.get(field) or [])
            if got > 0:
                out.append(f"{day}: added {got} {word if got != 1 else word[:-1]}")
            elif got < 0:
                out.append(f"{day}: took off {-got} {word if got != -1 else word[:-1]}")
    return ("; ".join(out) or "changed the plan")[:110] + " (in Anki)"
