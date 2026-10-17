"""3.9.1, doodle cheers: the fridge. The drawings and signs my crew sends
stay pinned around the Decks screen, like magnets on a fridge (Sam: "could
the fridge just be the periphery of the decks window, like dragged around
the anki window?"), each with the note it came with under it and who sent
it, till I take it down. The last KEEP; each where I dragged it (p: its
place as thousandths of the window, so it keeps its spot when the window
changes size), a new one in the gutter beside the board. It's mine: kept
in wrap.json on this computer, never sent. Pure; the glue is
closet_flow's, the drawing board.fridge_html and fridge_js."""

import hashlib

from .backend.shapes import clean_doodle, clean_note

KEEP = 12  # what fits around a board on a laptop's screen


def key(item):
    """A doodle's own short name on the fridge (its sender and when)."""
    return hashlib.sha1(f'{item.get("from")}|{item.get("at")}'.encode()).hexdigest()[:10]


def _place(p):
    if (isinstance(p, (list, tuple)) and len(p) == 2
            and all(isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 1000 for v in p)):
        return [p[0], p[1]]
    return None


def clean(v):
    """wrap.json's "fridge", as this writes it, or less: oldest first."""
    out = []
    for x in v if isinstance(v, list) else []:
        d = clean_doodle(x.get("d")) if isinstance(x, dict) else None
        if not d:
            continue
        item = {"from": str(x.get("from") or "")[:64], "name": " ".join(str(x.get("name") or "?").split())[:60],
                "at": str(x.get("at") or "")[:40], "a": str(x.get("a") or "")[:16], "n": clean_note(x.get("n")), "d": d}
        if _place(x.get("p")):
            item["p"] = _place(x.get("p"))
        out.append(item)
    return out[-KEEP:]


def add(items, cheers, accents):
    """`items` with the cheers that carried a doodle stuck on, each once,
    with the note that came with it. accents: {uid: accent name}, their
    colour as it was when it came."""
    items = clean(items)
    have = {key(x) for x in items}
    for ch in cheers or []:
        d = clean_doodle(ch.get("doodle"))
        item = {"from": str(ch.get("from") or ""), "name": str(ch.get("name") or "?"), "at": str(ch.get("at") or ""),
                "a": str((accents or {}).get(ch.get("from")) or ""), "n": clean_note(ch.get("note")), "d": d}
        if d and key(item) not in have:
            have.add(key(item))
            items.append(item)
    return clean(items)


def take_down(items, k):
    return [x for x in clean(items) if key(x) != k]


def move(items, k, x, y):
    """Where I dragged it: x and y in thousandths of the window (clamped)."""
    out = clean(items)
    for item in out:
        if key(item) == k:
            item["p"] = [max(0, min(1000, int(x))), max(0, min(1000, int(y)))]
    return out
