"""3.8.0, "What I know": the topic map as a picture card and as text, to
share by hand (Sam: "is there a way to make a bento shareable"; "is there
a text-based version"). Pure: the card's layout and words, the text, and
last week's map for the change; ui/map_card_dialog.py paints and copies.

Insights are mine alone and never sent (CLAUDE.md), so the card is made
here, from my own Anki, and only goes where I paste it. It wears the
site's picture cards' look (site/public/cards.js: palette, eyebrow,
duecrew.com at the foot), the board's shades (team.map_shade), and the
board's amber for under 70%."""

import datetime

from .team import map_shade

SIZE = 1080      # the card is square, 1080 x 1080, as the site's
PAD = 66         # its margin
TOP = 226        # where the tiles start, under the eyebrow and the deck
FOOT = 118       # and the room they leave at the foot
GAP = 14         # between tiles
TILES = 12       # the map's own cap
SNAP_KEEP = 3    # a deck's weekly maps kept, newest last
SNAP_EVERY = 7   # days between them

# cards.js LOOKS, plus the board's amber (--dc-hours) for under 70%
LOOKS = {
    "light": {"bg": "#fbfbf6", "ink": "#1f2a1f", "mut": "#6a7568", "g": "#2e7d32", "g3": "#e3efe3",
              "on": "#ffffff", "amber": "#b26a00"},
    "dark": {"bg": "#141813", "ink": "#eef2ea", "mut": "#9fae9b", "g": "#7cc47f", "g3": "#243223",
             "on": "#122912", "amber": "#dda45c"},
}


def mix(a, b, k):
    """#rrggbb: k of a, the rest b."""
    pa, pb = [int(a[i:i + 2], 16) for i in (1, 3, 5)], [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x * k + y * (1 - k)):02x}" for x, y in zip(pa, pb))


def fill(look, shade):
    """A tile's colour: the board's (amber under 70, then 25%, 55% and all of
    the green); None (nothing started) the card's quiet green."""
    pal = LOOKS[look]
    if shade is None:
        return pal["g3"]
    return [pal["amber"], mix(pal["g"], pal["bg"], 0.25), mix(pal["g"], pal["bg"], 0.55), pal["g"]][shade]


def ink(look, shade):
    """The words on a tile."""
    pal = LOOKS[look]
    if shade is None:
        return pal["mut"]
    return pal["on"] if shade == 3 else pal["bg"] if shade == 0 else pal["ink"]


def squarify(sizes, x, y, w, h):
    """Rectangles for these sizes (biggest first) filling x, y, w, h, each
    as near square as it can be (Bruls, Huizing, van Wijk). [(x, y, w, h)]
    in the order given."""
    total = float(sum(sizes)) or 1.0
    scale = w * h / total
    rest = [s * scale for s in sizes]
    out = []

    def worst(row, side):
        s = sum(row)
        return max(side * side * max(row) / (s * s), s * s / (side * side * min(row)))
    while rest:
        side = min(w, h)
        i = 1
        while i < len(rest) and worst(rest[:i + 1], side) <= worst(rest[:i], side):
            i += 1
        row, s = rest[:i], sum(rest[:i])
        if w >= h:
            cw = s / h if h else 0
            yy = y
            for a in row:
                th = a / cw if cw else 0
                out.append((x, yy, cw, th))
                yy += th
            x, w = x + cw, w - cw
        else:
            rh = s / w if w else 0
            xx = x
            for a in row:
                tw = a / rh if rh else 0
                out.append((xx, y, tw, rh))
                xx += tw
            y, h = y + rh, h - rh
        rest = rest[i:]
    return out


def _date(day):
    d = datetime.date.fromisoformat(str(day))
    return f"{d.day} {d:%b}"


def card(deck, day, tiles, by="fsrs", pct=True, prev=None, since=""):
    """The card as drawn: {eyebrow, title, tiles: [{name, k (0-100 or None,
    nothing started), shade, d (the change since `since`, or None), x, y,
    w, h}], foot, key (the shades in words when the numbers are off)}.
    tiles: the map's (name, n, know, started, key); prev: {key: know a
    week or more ago} for the change."""
    ts = sorted((t for t in tiles or () if int(t.get("n") or 0) > 0), key=lambda t: -int(t["n"]))[:TILES]
    room = squarify([int(t["n"]) for t in ts], PAD - GAP / 2, TOP - GAP / 2,
                    SIZE - 2 * PAD + GAP, SIZE - FOOT - TOP + GAP)
    out = []
    for t, (x, y, w, h) in zip(ts, room):
        k = t.get("know")
        d = None
        if prev is not None and k is not None and prev.get(t.get("key")) is not None:
            d = int(k) - int(prev[t["key"]])
        out.append({"name": str(t.get("name") or "?"), "k": None if k is None else int(k),
                    "shade": None if k is None else map_shade(int(k)), "d": d,
                    "x": x + GAP / 2, "y": y + GAP / 2, "w": max(0.0, w - GAP), "h": max(0.0, h - GAP)})
    cards = sum(int(t["n"]) for t in ts)
    started = sum(int(t.get("started") or 0) for t in ts if t.get("know") is not None)
    now = (sum(int(t["know"]) * int(t.get("started") or 0) for t in ts if t.get("know") is not None) / started
           if started else None)
    said = "I’d remember now" if by == "fsrs" else "right in their reviews these 4 weeks"
    foot = ""
    if pct and now is not None:
        foot = f"{round(now)}% {said} · {cards:,} cards"
        changed = [x for x in out if x["d"] is not None]
        if prev is not None and changed and since:
            up = round(sum(x["d"] for x in changed) / len(changed))
            foot = f"{round(now)}% now · {'up' if up >= 0 else 'down'} {abs(up)} since {_date(since)}"
    eyebrow = f"What I know · {_date(day)}"
    return {"eyebrow": eyebrow.upper(), "title": str(deck or "My deck"), "tiles": out, "foot": foot,
            "key": not pct, "pct": bool(pct)}


SQUARES = ((80, "\U0001F7E9"), (70, "\U0001F7E8"), (0, "\U0001F7E7"))  # green, yellow, orange
NEW_SQUARE = "⬜"


def square(k):
    """A subject's square in the text: green 80 and up, yellow from 70,
    orange under, white with nothing started."""
    if k is None:
        return NEW_SQUARE
    return next(sq for lo, sq in SQUARES if int(k) >= lo)


def text(deck, day, tiles, by="fsrs", pct=True, prev=None, since=""):
    """The same, to paste: a square and a line a subject, biggest first."""
    from .share import FOOTER
    c = card(deck, day, tiles, by, pct, prev, since)
    lines = [f"What I know · {c['title']} · {_date(day)}"]
    for t in c["tiles"]:
        bit = f"{square(t['k'])} {t['name']}"
        if pct:
            bit += " new" if t["k"] is None else f" {t['k']}%"
            if t["d"]:
                bit += f" {'↑' if t['d'] > 0 else '↓'}{abs(t['d'])}"
        lines.append(bit)
    if c["foot"]:
        lines.append(c["foot"])
    return "\n".join(lines + [FOOTER])


def keep(snaps, day, tiles):
    """One way's weekly maps ([{day, k: {key: know}}], newest last) with
    today's added when the newest is SNAP_EVERY days old or more: the same
    list when nothing's due, so it's written once a week at most."""
    snaps = [s for s in snaps or () if isinstance(s, dict) and isinstance(s.get("k"), dict) and s.get("day")]
    k = {str(t["key"]): int(t["know"]) for t in tiles or () if t.get("know") is not None}
    if not k:
        return snaps
    if snaps and (datetime.date.fromisoformat(day) - datetime.date.fromisoformat(str(snaps[-1]["day"]))).days < SNAP_EVERY:
        return snaps
    return (snaps + [{"day": day, "k": k}])[-SNAP_KEEP:]


def keep_ways(ways, way, day, tiles, most=4):
    """A deck's weekly maps by way ({way: [...]}): this way's kept (keep),
    the ways seen longest ago dropped past `most`, so switching ways never
    pushes out another way's week."""
    ways = {str(w): v for w, v in (ways or {}).items() if isinstance(v, list)} if isinstance(ways, dict) else {}
    ways[str(way)] = keep(ways.get(str(way)), day, tiles)
    newest = lambda w: max((str(s.get("day") or "") for s in ways[w] if isinstance(s, dict)), default="")  # noqa: E731
    for w in sorted(ways, key=newest)[:max(0, len(ways) - most)]:
        if w != str(way):
            ways.pop(w)
    return ways


def week_ago(snaps, day):
    """(one way's map a week ago or more, its day) for the change, or (None, "")."""
    cut = (datetime.date.fromisoformat(day) - datetime.timedelta(days=SNAP_EVERY)).isoformat()
    for s in reversed(snaps or ()):
        if isinstance(s, dict) and str(s.get("day") or "") <= cut and isinstance(s.get("k"), dict):
            return dict(s["k"]), str(s["day"])
    return None, ""
