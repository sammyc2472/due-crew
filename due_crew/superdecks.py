"""3.9.5, Super decks (pure: no aqt; due_flow is the glue, board draws it):
Due Crew's own filtered decks, in a tab of their own in the You bubble
(Sam's pick B), and only for what Anki's scheduler (FSRS) can't know (Sam's
rule): a date ahead, cards you haven't started, a miss outside Anki.
Everything else is reviews ahead of their date, and FSRS has those.

A deck here is {key, kind, name, n, ...}: built (did, `made`: how many it
held when built) or ready to make (key "exam:<did>", "quiz:<plan>:<event>",
"day:<plan>", "leech"). kind is one of KINDS, or None for a Due Crew deck
built before kinds were kept (it has no group, only its tile). Words here
are the tab's and a deck's page's; they never leave the computer."""

import datetime

GROUPS = (("date", "Before a date"), ("new", "New"), ("outside", "From outside Anki"))
KINDS = ("exam", "quiz", "part", "day", "new", "leech", "qbank")
GROUP = {"exam": "date", "quiz": "date", "part": "date", "day": "new", "new": "new", "leech": "new", "qbank": "outside"}

# the kinds an empty tab lists, and when each shows up: (kind, name, when)
SOON = (("exam", "Before your exam", "once you add its date"),
        ("quiz", "Before a quiz", "three days before a plan’s quiz"),
        ("day", "The plan’s day", "when you follow a plan"),
        ("new", "A section’s cards", "a click on one, under a plan’s date"),
        ("leech", "Leeches", "when Anki sets cards aside"),
        ("qbank", "QBank cards", "when you paste QIDs"))


def _dow(day):
    try:
        return f"{datetime.date.fromisoformat(str(day)):%a}"
    except (TypeError, ValueError):
        return ""


def what(d):
    """The tile's line under its name."""
    k = d.get("kind")
    if k in ("exam", "quiz"):
        dow = _dow(d.get("day"))
        return f"would slip by {dow}" if dow else ""
    if k == "part":
        dow = _dow(d.get("day"))
        return f"missed lately, before {dow}" if dow else "missed lately"
    return {"day": "the plan’s day", "new": str(d.get("src") or "new and due"), "leech": "start fresh",
            "qbank": "from your QIDs"}.get(k, "")


def facts(d):
    """A deck's page: [(label, words)], in it, why a deck, when a card
    leaves, then. Plain text (the board escapes it)."""
    k, name = d.get("kind"), str(d.get("name") or "")
    dow = _dow(d.get("day")) or "the day"
    if k == "exam":
        return [("In it", f"Cards on the exam you’d likely have forgotten by {dow}. Anki would show them after."),
                ("Why a deck", f"Anki aims for your retention every day, not on {dow}."),
                ("Leaves", "When you get it right."), ("Then", "The day after the exam, it goes.")]
    if k == "quiz":
        quiz = name[7:] if name.startswith("Before ") else name
        return [("In it", f"Cards from the dates {quiz} tests."),
                ("Why a deck", f"Anki aims for your retention every day, not on {dow}."),
                ("Leaves", "When you get it right."), ("Then", "The day after the quiz, it goes.")]
    if k == "part":
        return [("In it", f"{name}: the cards you missed lately."),
                ("Why a deck", f"Anki aims for your retention every day, not on {dow}."),
                ("Leaves", "When you get it right."), ("Then", "The day after, it goes.")]
    if k == "day":
        return [("In it", f"The cards you haven’t seen from {d.get('plan') or 'the plan'}’s dates, in its order."),
                ("Why a deck", "Anki doesn’t say when a new card first shows. The plan does."),
                ("Leaves", "When it’s learned."), ("Then", "Tomorrow, the next day’s.")]
    if k == "new":
        return [("In it", f"{name}: the cards you haven’t seen, and any due today."),
                ("Why a deck", "Anki doesn’t say when a new card first shows. This keeps them together."),
                ("Leaves", "When it’s learned, or right."), ("Then", "Gone when it’s empty.")]
    if k == "leech":
        then = ("Gone when it’s empty." if d.get("did") else
                "Study starts them over: new cards, the leech tag off. Edit › Undo puts them back.")
        return [("In it", "Cards Anki set aside after you kept missing them."),
                ("Why a deck", "Started over, they’re new cards, and FSRS learns them anew."),
                ("Leaves", "When it’s learned."), ("Then", then)]
    if k == "qbank":
        return [("In it", "The cards behind the questions you missed."),
                ("Why a deck", "A miss in a question bank is one Anki never saw."),
                ("Leaves", "When you get it right."), ("Then", "Each paste adds to it.")]
    return [("Leaves", "When you get it right."), ("Then", "Gone when it’s empty.")]


def view(decks, page=None):
    """The tab: {n, groups: [(title, [deck])], rest: [deck] (no kind),
    soon: [(name, when)] every kind and when it shows up, with none here,
    page: the deck whose page is open, or None}. 3.9.5 (Sam: "don't want
    the pip on super decks and don't want the number of super decks...
    kinda overwhelming"): no Pip, no first-time line, no count."""
    decks = sorted(decks, key=lambda d: (KINDS.index(d["kind"]) if d.get("kind") in KINDS else len(KINDS),
                                         str(d.get("name") or "").lower()))
    groups = [(title, [d for d in decks if GROUP.get(d.get("kind")) == g]) for g, title in GROUPS]
    return {"n": len(decks), "groups": [(t, ds) for t, ds in groups if ds],
            "rest": [d for d in decks if d.get("kind") not in GROUP],
            "soon": [] if decks else [(name, when) for _k, name, when in SOON],
            "page": next((d for d in decks if d.get("key") == page), None) if page else None}
