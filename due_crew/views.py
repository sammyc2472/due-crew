"""3.9.12, the foundations round: a named shape for what a page is told to
draw, checked where it crosses from Python to the page. Each surface had
its own dictionary, known only to the code that made it and the script
that drew it; a key misspelt on one side drew nothing and said nothing.

A shape is {key: the type(s) it may be}. `wrong(view, shape)` says what
doesn't fit (a key the page doesn't know, a value of the wrong type); the
glue counts it for the field's sheet (`view:<name>`, errs.py) and draws the
view anyway, so a slip is seen and nothing a person had goes missing.

The first shape here was the review screen's chip (cards.py: who knows it,
a hook, an ask, a plan's note, my own hook); then a plan's card, Insights
and the dance floor (`seen`, called where each is drawn). The next surface
to get one adds it here, with its test. Pure: no Anki.
"""

CHIP_KINDS = ("knows", "tip", "asked", "remark", "hook", "hookask", "hookadd")

# the review chip (cards._CHIP_JS and the card above the bar read exactly these, as D.<key>)
CHIP = {
    "kind": str,          # which of CHIP_KINDS
    "text": str,          # its words, set as text
    "short": str,         # the words for a narrow bar
    "title": str,         # the hover's words
    "fold": str,          # what it says till Show: the words wait (a one-by-one card isn't given away)
    "open": bool,         # drawn with its words showing (Show was pressed)
    "cmd": str,           # the click on its words, a card-page command (room_model.CARD_PAGE_CMDS)
    "act": str,           # its button's word
    "actcmd": str,        # its button's command
    "more": int,          # how many more there are
    "ask": bool,          # whether Ask is still to press
    "bar": bool,          # it stays in the bar, never over the card
    "accent": (str, list, tuple),
    "pip": dict,          # a Pip to draw beside it
    "peek": dict,         # who peeks in from the corner: {uids, head, act, pips, pop}
    "sevcss": str,        # Pip's sheet, sent once a page
}
PEEK = {"uids": list, "head": str, "act": str, "pips": list, "pop": bool}

# 3.9.12, Stage D's first three: the plan card, Insights and the dance floor. Written from every one the
# suites and the preview draw, with every key their drawing reads; a value may always be None. One level:
# what's inside a day, a tile or a row is the next round's.

# a plan's card on You › Plans (board._plan_card_html reads exactly these)
PLAN_CARD = {
    "aside": (list, tuple),
    "aside_ok": (list, tuple),
    "behind": dict,
    "catch": dict,
    "change": (list, tuple),
    "exam_ask": dict,
    "fallback_ok": bool,
    "focus": str,
    "id": str,
    "ins": dict,
    "joy": dict,
    "lesson_deck": dict,
    "line": dict,
    "lines": (list, tuple),
    "name": str,
    "no_deck": bool,
    "own": dict,
    "owner_name": str,
    "path": dict,
    "paused": bool,
    "posts": (list, tuple),
    "prep": dict,
    "put_off": (list, tuple),
    "put_off_ask": bool,
    "quiz": dict,
    "rows": (list, tuple),
    "session": dict,
    "slid": (int, float),
    "status": dict,
    "sub": str,
    "tabs": dict,
    "tag_news": dict,
    "team_ask": bool,
    "title": str,
    "update": object,
    "waiting": (int, float),
    "week": (list, tuple),
    "week_offset": (int, float),
}

# You › Insights for a deck (board._insights_html)
INSIGHTS = {
    "_map_missed": (set, frozenset, list, tuple),
    "ahead": dict,
    "aim": dict,
    "bank": bool,
    "behind": (int, float),
    "deck_name": str,
    "did": (int, float),
    "fsrs": dict,
    "fsrs_on": bool,
    "hard": dict,
    "hero": (list, tuple),
    "kept": (int, float),
    "leech": dict,
    "leech_out": (int, float),
    "leeches": (int, float),
    "map": (list, tuple),
    "map_at": (list, tuple),
    "map_by": str,
    "map_ways": (list, tuple),
    "near": (int, float),
    "open": (str, list, tuple, dict, bool, int, float),
    "pid": str,
    "right": dict,
    "rows": (list, tuple),
    "target": (int, float),
    "two": str,
}

# the dance floor (board.dance_html)
DANCE = {
    "_seen": dict,
    "app": str,
    "ask": bool,
    "crew": (list, tuple),
    "folded": bool,
    "me": dict,
    "motion": str,
    "pip": bool,
}
DANCER = {
    "accent": str,
    "fresh": bool,
    "look": (list, tuple),
    "name": str,
    "song": dict,
    "uid": str,
}
SONG = {
    "a": str,
    "al": str,
    "art": str,
    "at": str,
    "id": (int, float),
    "t": str,
    "url": str,
    "y": (int, float),
}


def wrong(view, shape, kinds=None):
    """What about `view` doesn't fit `shape`: ["key: why"], [] when it fits
    (or there's nothing to draw). kinds: what its "kind" may be."""
    if view is None:
        return []
    if not isinstance(view, dict):
        return ["not a dict"]
    out = []
    for k, v in view.items():
        if k not in shape:
            out.append(f"{k}: not in the shape")
        elif v is not None and not isinstance(v, shape[k]):
            out.append(f"{k}: {type(v).__name__}")
        elif shape[k] is int and isinstance(v, bool):
            out.append(f"{k}: bool")
    if kinds is not None and view.get("kind") not in kinds:
        out.append(f"kind: {view.get('kind')!r}")
    return out


def chip_wrong(view):
    """The review chip's view against CHIP (and its peek against PEEK)."""
    out = wrong(view, CHIP, CHIP_KINDS)
    if isinstance(view, dict) and isinstance(view.get("peek"), dict):
        out += ["peek." + x for x in wrong(view["peek"], PEEK)]
    return out


def plan_wrong(card):
    return wrong(card, PLAN_CARD)


def insights_wrong(view):
    return wrong(view, INSIGHTS)


def dance_wrong(view):
    """The dance floor against DANCE, each dancer against DANCER, and every song against SONG."""
    out = wrong(view, DANCE)
    if isinstance(view, dict):
        if isinstance(view.get("me"), dict):
            out += ["me." + x for x in wrong(view["me"], SONG)]
        for p in view.get("crew") or []:
            out += ["crew." + x for x in wrong(p, DANCER)]
            if isinstance(p, dict) and isinstance(p.get("song"), dict):
                out += ["crew.song." + x for x in wrong(p["song"], SONG)]
    return out


CHECKS = {"chip": chip_wrong, "plan": plan_wrong, "insights": insights_wrong, "dance": dance_wrong}

SLIPS = []


def seen(name, view):
    """A view as it's drawn: one that doesn't fit its shape is counted (`view:<name>`, errs.py) and drawn
    anyway. Never in the drawing's way: whatever goes wrong here is swallowed."""
    try:
        bad = CHECKS[name](view) if view is not None else []
        if bad:
            if len(SLIPS) < 20:
                SLIPS.append((name, bad[:3]))  # the last few, for whoever is looking (the suite reads it: none)
            from . import errs
            errs.count("view:" + name)
            return False
    except Exception:
        pass
    return True
