"""3.9.12, the foundations round: a named shape for what a page is told to
draw, checked where it crosses from Python to the page. Each surface had
its own dictionary, known only to the code that made it and the script
that drew it; a key misspelt on one side drew nothing and said nothing.

A shape is {key: the type(s) it may be}. `wrong(view, shape)` says what
doesn't fit (a key the page doesn't know, a value of the wrong type); the
glue counts it for the field's sheet (`view:<name>`, errs.py) and draws the
view anyway, so a slip is seen and nothing a person had goes missing.

The first shape here is the review screen's chip (cards.py: who knows it,
a hook, an ask, a plan's note, my own hook): the next surface to get one
adds it here, with its test. Pure: no Anki.
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
