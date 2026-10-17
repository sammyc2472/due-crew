"""3.9.1, doodle cheers: the fridge, a page of Pip's closet. The drawings
and signs my crew sends stay on it, the last KEEP, until I take one down.
It's mine: kept in wrap.json on this computer, never sent. Pure; the glue
is closet_flow's."""

import hashlib

from .backend.shapes import clean_doodle

KEEP = 24


def key(item):
    """A doodle's own short name on the fridge (its sender and when)."""
    return hashlib.sha1(f'{item.get("from")}|{item.get("at")}'.encode()).hexdigest()[:10]


def clean(v):
    """wrap.json's "fridge", as this writes it, or less: oldest first."""
    out = []
    for x in v if isinstance(v, list) else []:
        d = clean_doodle(x.get("d")) if isinstance(x, dict) else None
        if not d:
            continue
        out.append({"from": str(x.get("from") or "")[:64], "name": " ".join(str(x.get("name") or "?").split())[:60],
                    "at": str(x.get("at") or "")[:40], "a": str(x.get("a") or "")[:16], "d": d})
    return out[-KEEP:]


def add(items, cheers, accents):
    """`items` with the cheers that carried a doodle stuck on, each once.
    accents: {uid: accent name}, their colour as it was when it came."""
    items = clean(items)
    have = {key(x) for x in items}
    for ch in cheers or []:
        d = clean_doodle(ch.get("doodle"))
        item = {"from": str(ch.get("from") or ""), "name": str(ch.get("name") or "?"), "at": str(ch.get("at") or ""),
                "a": str((accents or {}).get(ch.get("from")) or ""), "d": d}
        if d and key(item) not in have:
            have.add(key(item))
            items.append(item)
    return clean(items)


def take_down(items, k):
    return [x for x in clean(items) if key(x) != k]
