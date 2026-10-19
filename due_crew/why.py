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

REV_MORE = 50     # "more reviews today" adds this many
MOST = 2000       # cards read at once; past it, the first this many

# Anki's queues
NEW, LEARN, REVIEW, DAY_LEARN, PREVIEW = 0, 1, 2, 3, 4
SUSPENDED, BURIED_SIBLING, BURIED_USER = -1, -2, -3


def _s(n, one, many=None):
    return f"{n:,} {one if n == 1 else (many or one + 's')}"


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
            say = f"Suspended as a leech: forgotten {_s(n, 'time')}." if n else "Suspended as a leech."
            return _r("leech", "suspended", say, ("unsuspend",), home)
        return _r("suspended", "suspended", "Suspended, so Anki never shows it.", ("unsuspend",), home)
    if q == BURIED_SIBLING:
        return _r("buried", "buried", "Buried till tomorrow: another card from its note came up today.", ("unbury",), home)
    if q == BURIED_USER:
        return _r("buried", "buried", "Buried by you till tomorrow.", ("unbury",), home)
    if odid:
        name, size = ctx["deck"](did), int(ctx["size"](did) or 0)
        say = f"In {name}, a filtered deck, not in {deck}: it shows when you study {name}."
        if size > 1:
            say += f" Emptying it sends its {_s(size, 'card')} home."
        return _r("filtered", f"filtered:{did}", say, ("empty", did), did)
    if q == NEW:
        left = ctx["left"](did)
        lim, room = int(left.get("new_limit") or 0), int(left.get("new") or 0)
        rank = int(ctx["rank"](c) or 1)
        if left.get("paused"):
            return _r("new_paused", f"new:{did}", f"New: you stopped new cards in {deck} (Insights › Reviews ahead).",
                      None, did)
        if lim <= 0:
            return _r("new_off", f"new:{did}", f"New, and {deck} takes no new cards a day.",
                      ("more_new", did, rank), did)
        if room <= 0:
            return _r("new_done", f"new:{did}", f"New: today's {_s(lim, 'new card')} in {deck} are done.",
                      ("more_new", did, rank), did)
        if rank > room:
            return _r("new_line", f"new:{did}",
                      f"New: about {_s(rank - 1, 'new card')} come before it, and {deck} has {room:,} left today.",
                      ("more_new", did, rank - room), did)
        return _r("new_today", f"study:{did}", f"New, and in today's new cards: study {deck} to see it.",
                  ("study", did), did)
    if q == LEARN:
        if int(c["due"]) <= int(ctx["now"]) + int(ctx.get("ahead") or 0):
            return _r("due", f"study:{did}", f"Learning, and due now: study {deck} to see it.", ("study", did), did)
        return _r("learning", "learning", f"Learning: back at {ctx['clock'](int(c['due']))}. Nothing to do: it comes back on its own.",
                  None, did)
    if q == DAY_LEARN and int(c["due"]) > int(ctx["today"]):
        return _r("learning", "learning", f"Learning: back {ctx['day'](int(c['due']))}. Nothing to do: it comes back on its own.",
                  None, did)
    if q == REVIEW and int(c["due"]) > int(ctx["today"]):
        by = "by FSRS" if ctx.get("fsrs") else "by Anki's schedule"
        return _r("not_due", "not_due", f"Not due till {ctx['day'](int(c['due']))}, {by}.", ("due_now",), did, int(c["due"]))
    if q in (REVIEW, DAY_LEARN):
        left = ctx["left"](did)
        if int(left.get("rev") or 0) <= 0:
            lim = int(left.get("rev_limit") or 0)
            say = (f"Due, but today's {_s(lim, 'review')} in {deck} are done." if lim > 0
                   else f"Due, but {deck} takes no reviews a day.")
            return _r("rev_done", f"rev:{did}", say, ("more_rev", did, REV_MORE), did)
        return _r("due", f"study:{did}", f"Due today: study {deck} to see it.", ("study", did), did)
    return _r("other", "other", "Anki has it in a state this can't read.", None, did)


def _r(kind, group, say, fix, did, due=None):
    return {"kind": kind, "group": group, "say": say, "fix": fix, "did": did, "due": due}


LABELS = {"unsuspend": ("Unsuspend", "Unsuspend them"), "unbury": ("Show it today", "Show them today"),
          "due_now": ("Study it now", "Study them now")}


def label(fix, n, ctx):
    """A fix's button: what it does, in a few words."""
    act = fix[0]
    if act in LABELS:
        return LABELS[act][0 if n == 1 else 1]
    if act == "empty":
        return f"Empty {ctx['deck'](fix[1])}"
    if act == "more_new":
        return f"{fix[2]:,} more new today"
    if act == "more_rev":
        return f"{fix[2]:,} more reviews today"
    if act == "study":
        return f"Study {ctx['deck'](fix[1])}"
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
        return f"{n:,} suspended" + (f", {leech:,} of them as leeches." if leech else ".")
    if k == "buried":
        return f"{n:,} buried till tomorrow."
    if k == "filtered":
        return f"{n:,} in {deck}, a filtered deck: they show when you study it."
    if rs[0]["group"].startswith("new:"):
        left = ctx["left"](did)
        if "new_paused" in kinds:
            return f"{n:,} new: you stopped new cards in {deck} (Insights › Reviews ahead)."
        if "new_off" in kinds:
            return f"{n:,} new, and {deck} takes no new cards a day."
        if int(left.get("new") or 0) <= 0:
            return f"{n:,} new, past today's {_s(int(left.get('new_limit') or 0), 'new card')} in {deck}."
        return f"{n:,} new, further in line than the {int(left.get('new') or 0):,} {deck} has left today."
    if k == "learning":
        return f"{n:,} learning: they come back on their own."
    if k == "not_due":
        soon = min(r["due"] for r in rs if r["due"] is not None)
        return f"{n:,} not due yet, the soonest {ctx['day'](soon)}."
    if k == "rev_done":
        return f"{n:,} due, past today's reviews in {deck}."
    if rs[0]["group"].startswith("study:"):
        return f"{n:,} in today's cards: study {deck} to see them."
    return f"{n:,} in a state this can't read."
