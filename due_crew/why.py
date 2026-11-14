"""3.8.0, "Why isn't this card showing?" (pick 9 of The First Month):
Browse › right-click says in one plain sentence why Anki won't show a
card today, and offers Anki's own fix. Pure: a card's facts and the day's
limits in, the reason out; why_flow.py reads the collection, shows them
(ui/why_dialog.py) and runs the fixes.

Anki shows a suspended card, a buried one, one sitting in a filtered
deck, a new card past today's limit and a review not due till Friday the
same way: it just isn't there. Each gets its own words here, in Anki's
own terms (Suspended, Buried, filtered deck), since those are what
Browse shows next to it.

A fix is an action and its label: ("unsuspend",), ("unbury",),
("empty", filtered deck id), ("more_new", deck id, n), ("more_rev",
deck id, n), ("due_now",), ("study", deck id); None when there's nothing
to do (a learning card comes back by itself)."""

from .words import later as _later, t as _t

REV_MORE = 50     # "more reviews today" adds this many
MOST = 2000       # cards read at once; past it, the first this many

# Anki's queues
NEW, LEARN, REVIEW, DAY_LEARN, PREVIEW = 0, 1, 2, 3, 4
SUSPENDED, BURIED_SIBLING, BURIED_USER = -1, -2, -3


def _tn(one, many, count, **names):
    """words.tn with the count's comma ("1,204 cards"): {n} is the count unless it's given."""
    names.setdefault("n", f"{int(count):,}")
    return _t(one if int(count) == 1 else many, **names)


def reason(c, ctx):
    """One card's reason: {kind, group, say, fix, did}. c: {id, did, odid,
    queue, due, lapses, leech}; ctx: {today: Anki's day number, now: epoch
    seconds, ahead: learn-ahead seconds, deck(did) -> name, day(n) -> "Fri
    16", clock(secs) -> "15:40", left(did) -> {new, rev, new_limit,
    rev_limit} today, rank(c) -> its place among its deck's new cards (1
    first), size(did) -> cards in a filtered deck, fsrs}."""
    q, did, odid = int(c["queue"]), int(c["did"]), int(c.get("odid") or 0)
    home = int(odid or did)
    deck = ctx["deck"](home)
    if q == SUSPENDED:
        if c.get("leech"):
            n = int(c.get("lapses") or 0)
            say = (_tn("Suspended as a leech: forgotten {n} time.", "Suspended as a leech: forgotten {n} times.", n) if n
                   else _t("Suspended as a leech."))
            return _r("leech", "suspended", say, ("unsuspend",), home)
        return _r("suspended", "suspended", _t("Suspended, so Anki never shows it."), ("unsuspend",), home)
    if q == BURIED_SIBLING:
        return _r("buried", "buried", _t("Buried till tomorrow: another card from its note came up today."), ("unbury",), home)
    if q == BURIED_USER:
        return _r("buried", "buried", _t("Buried by you till tomorrow."), ("unbury",), home)
    if odid:
        name, size = ctx["deck"](did), int(ctx["size"](did) or 0)
        say = _t("In {name}, a filtered deck, not in {deck}: it shows when you study {name}.", name=name, deck=deck)
        if size > 1:
            say += " " + _t("Emptying it sends its {n} cards home.", n=f"{size:,}")
        return _r("filtered", f"filtered:{did}", say, ("empty", did), did)
    if q == NEW:
        left = ctx["left"](did)
        lim, room = int(left.get("new_limit") or 0), int(left.get("new") or 0)
        rank = int(ctx["rank"](c) or 1)
        if left.get("paused"):
            on = left["paused"] if isinstance(left["paused"], str) else deck  # the deck the stop is on, maybe a parent
            return _r("new_paused", f"new:{did}", _t("New: you stopped new cards in {deck} (Insights › Reviews ahead).", deck=on),
                      None, did)
        if lim <= 0:
            return _r("new_off", f"new:{did}", _t("New, and {deck} takes no new cards a day.", deck=deck),
                      ("more_new", did, rank), did)
        if room <= 0:
            return _r("new_done", f"new:{did}", _tn("New: today's {n} new card in {deck} are done.", "New: today's {n} new cards in {deck} are done.", lim, deck=deck),
                      ("more_new", did, rank), did)
        if rank > room:
            return _r("new_line", f"new:{did}",
                      _tn("New: about {n} new card come before it, and {deck} has {left} left today.",
                          "New: about {n} new cards come before it, and {deck} has {left} left today.", rank - 1, deck=deck, left=f"{room:,}"),
                      ("more_new", did, rank - room), did)
        return _r("new_today", f"study:{did}", _t("New, and in today's new cards: study {deck} to see it.", deck=deck),
                  ("study", did), did)
    if q == LEARN:
        if int(c["due"]) <= int(ctx["now"]) + int(ctx.get("ahead") or 0):
            return _r("due", f"study:{did}", _t("Learning, and due now: study {deck} to see it.", deck=deck), ("study", did), did)
        return _r("learning", "learning", _t("Learning: back at {time}. Nothing to do: it comes back on its own.", time=ctx["clock"](int(c["due"]))),
                  None, did)
    if q == DAY_LEARN and int(c["due"]) > int(ctx["today"]):
        return _r("learning", "learning", _t("Learning: back {day}. Nothing to do: it comes back on its own.", day=ctx["day"](int(c["due"]))),
                  None, did)
    if q == REVIEW and int(c["due"]) > int(ctx["today"]):
        day = ctx["day"](int(c["due"]))
        say = _t("Not due till {day}, by FSRS.", day=day) if ctx.get("fsrs") else _t("Not due till {day}, by Anki's schedule.", day=day)
        return _r("not_due", "not_due", say, ("due_now",), did, int(c["due"]))
    if q in (REVIEW, DAY_LEARN):
        left = ctx["left"](did)
        if int(left.get("rev") or 0) <= 0:
            lim = int(left.get("rev_limit") or 0)
            say = (_tn("Due, but today's {n} review in {deck} are done.", "Due, but today's {n} reviews in {deck} are done.", lim, deck=deck)
                   if lim > 0 else _t("Due, but {deck} takes no reviews a day.", deck=deck))
            return _r("rev_done", f"rev:{did}", say, ("more_rev", did, REV_MORE), did)
        return _r("due", f"study:{did}", _t("Due today: study {deck} to see it.", deck=deck), ("study", did), did)
    return _r("other", "other", _t("Anki has it in a state this can't read."), None, did)


def _r(kind, group, say, fix, did, due=None):
    return {"kind": kind, "group": group, "say": say, "fix": fix, "did": did, "due": due}


LABELS = {"unsuspend": (_later("Unsuspend"), _later("Unsuspend them")), "unbury": (_later("Show it today"), _later("Show them today")),
          "due_now": (_later("Study it now"), _later("Study them now"))}


def label(fix, n, ctx):
    """A fix's button: what it does, in a few words."""
    act = fix[0]
    if act in LABELS:
        return _t(LABELS[act][0 if n == 1 else 1])
    if act == "empty":
        return _t("Empty {deck}", deck=ctx["deck"](fix[1]))
    if act == "more_new":
        return _t("{n} more new today", n=f"{fix[2]:,}")
    if act == "more_rev":
        return _t("{n} more reviews today", n=f"{fix[2]:,}")
    if act == "study":
        return _t("Study {deck}", deck=ctx["deck"](fix[1]))
    return ""


def groups(cards, ctx):
    """The selected cards' reasons, alike ones together, the most cards
    first: [{group, n, say, fix, label, cids}]. One card says its own
    sentence; several say how many and why."""
    by = {}
    for c in cards[:MOST]:
        r = reason(c, ctx)
        g = by.setdefault(r["group"], {"rs": [], "cids": []})
        g["rs"].append(r)
        g["cids"].append(int(c["id"]))
    out = []
    for key, g in by.items():
        rs, n = g["rs"], len(g["rs"])
        fix = rs[0]["fix"]
        if fix and fix[0] in ("more_new",):  # enough for the furthest in line
            fix = (fix[0], fix[1], max(r["fix"][2] for r in rs))
        say = rs[0]["say"] if n == 1 else _many(rs, ctx)
        out.append({"group": key, "n": n, "say": say, "fix": fix, "label": label(fix, n, ctx) if fix else "",
                    "cids": g["cids"]})
    out.sort(key=lambda g: (-g["n"], g["group"]))
    return out


def _many(rs, ctx):
    k, n, did = rs[0]["kind"], len(rs), rs[0]["did"]
    deck = ctx["deck"](did)
    kinds = {r["kind"] for r in rs}
    if rs[0]["group"] == "suspended":
        leech = sum(1 for r in rs if r["kind"] == "leech")
        return (_t("{n} suspended, {leech} of them as leeches.", n=f"{n:,}", leech=f"{leech:,}") if leech
                else _t("{n} suspended.", n=f"{n:,}"))
    if k == "buried":
        return _t("{n} buried till tomorrow.", n=f"{n:,}")
    if k == "filtered":
        return _t("{n} in {deck}, a filtered deck: they show when you study it.", n=f"{n:,}", deck=deck)
    if rs[0]["group"].startswith("new:"):
        left = ctx["left"](did)
        if "new_paused" in kinds:
            on = left["paused"] if isinstance(left.get("paused"), str) else deck
            return _t("{n} new: you stopped new cards in {deck} (Insights › Reviews ahead).", n=f"{n:,}", deck=on)
        if "new_off" in kinds:
            return _t("{n} new, and {deck} takes no new cards a day.", n=f"{n:,}", deck=deck)
        if int(left.get("new") or 0) <= 0:
            lim = int(left.get("new_limit") or 0)
            return _tn("{n} new, past today's {limit} new card in {deck}.", "{n} new, past today's {limit} new cards in {deck}.",
                       lim, n=f"{n:,}", limit=f"{lim:,}", deck=deck)
        return _t("{n} new, further in line than the {left} {deck} has left today.", n=f"{n:,}",
                  left=f"{int(left.get('new') or 0):,}", deck=deck)
    if k == "learning":
        return _t("{n} learning: they come back on their own.", n=f"{n:,}")
    if k == "not_due":
        soon = min(r["due"] for r in rs if r["due"] is not None)
        return _t("{n} not due yet, the soonest {day}.", n=f"{n:,}", day=ctx["day"](soon))
    if k == "rev_done":
        return _t("{n} due, past today's reviews in {deck}.", n=f"{n:,}", deck=deck)
    if rs[0]["group"].startswith("study:"):
        return _t("{n} in today's cards: study {deck} to see them.", n=f"{n:,}", deck=deck)
    return _t("{n} in a state this can't read.", n=f"{n:,}")
