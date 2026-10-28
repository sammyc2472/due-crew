# Due Crew's logo and Pip: Copyright (c) 2026 Sammy Caplan, all rights reserved (see LICENSE).
"""Pip, the square from the logo's seven days (3.8.1, the "Pip Design" page:
Block, Sam's picks: no belt, big round eyes, stubby arms, cheeks only when
a cheer lands). Pure: no aqt.

One drawing for every pose, and one motion sheet (CSS). The board draws Pip
from here, and the room's widgets get its markup from here as data, so it's
never drawn twice and there's no JS twin; the week picture card draws
`still`, and the site's cards.js keeps a copy of it the suite checks. 3.8.2:
the site's crew rows fill in `site_kit` (sev.js, written by
tools/gen_sev_js.py), the one drawing again; only the closet's rules for a
look are restated there.
Every pose draws the same named parts (sv-body, sv-eyes, sv-pupils,
sv-armL/R, sv-card, sv-clock, ...), so a moment (`m-*`) moves whatever
pose it's given.

By the logo it's a moment: it comes when something happens and goes
(`moment`). Still is the frame: each moment's resting markup is the frame that says it
standing still, and the motion lives under prefers-reduced-motion:
no-preference, the computer's Reduce motion. Anki's own is on unless
switched off, so it isn't asked (Sam's call). A moment that happens once (a
hop, a cheer) plays once; drawn again the same day it rests (`rest`).
Transforms and opacity only. Colours come from the page: --sv-a (the
accent), --sv-line, --sv-amb, --sv-mut, with a fallback each.
"""

import functools
import math
import random
import re

INK = "var(--sv-ink,#1f2a1f)"
AMB = "var(--sv-amb,#b26a00)"
LINE = "var(--sv-line,#e2e2da)"
ACC = "var(--sv-a,#2e7d32)"
MUT = "var(--sv-mut,#6f736b)"
BLUSH = "var(--sv-blush,#ff8fa3)"


def _n(x):
    return f"{round(x, 1):g}"


def _r(x, y, w, h, rx, fill, extra="", stroke=""):
    return (f'<rect x="{_n(x)}" y="{_n(y)}" width="{_n(w)}" height="{_n(h)}" rx="{_n(rx)}" '
            f'style="fill:{fill}{";stroke:" + stroke if stroke else ""}"{extra}/>')


# what each pose's face, arms and hands are doing; the moment says how it moves
POSES = {
    "idle": {"eyes": "open", "mouth": "smile", "arms": "down"},
    "nap": {"eyes": "closed", "mouth": "o", "arms": "down", "fx": ("zz",)},
    "peek": {"eyes": "open", "mouth": "smile", "arms": "wave"},
    "ready": {"eyes": "happy", "mouth": "grin", "arms": "pump"},
    "focus": {"eyes": "down", "mouth": "flat", "arms": "hold", "prop": "card"},
    "ring": {"eyes": "wide", "mouth": "o", "arms": "hold", "prop": "clock", "fx": ("rings",)},
    "stretch": {"eyes": "happy", "mouth": "smile", "arms": "up"},
    "breathe": {"eyes": "closed", "mouth": "smile", "arms": "down", "fx": ("box",)},
    "rest": {"eyes": "closed", "mouth": "smile", "arms": "down"},
    "again": {"eyes": "open", "mouth": "smile", "arms": "hold", "prop": "card"},
    "hop": {"eyes": "happy", "mouth": "grin", "arms": "up", "fx": ("confetti",)},
    "stack": {"eyes": "happy", "mouth": "smile", "arms": "out", "fx": ("stack",)},
    "cheer": {"eyes": "happy", "mouth": "grin", "arms": "up", "prop": "gift", "cheeks": True, "fx": ("sparks",)},
    "exam": {"eyes": "open", "mouth": "smile", "arms": "cross", "fx": ("star",)},
    "away": {"eyes": "open", "mouth": "smile", "arms": "walk", "prop": "case"},
    "hello": {"eyes": "happy", "mouth": "smile", "arms": "wave"},
}

# the moment each pose plays when it's drawn, unless told otherwise
MOMENT = {"idle": "idle", "nap": "nap", "peek": "peek", "ready": "ready", "focus": "focus", "ring": "ring",
          "stretch": "stretch", "breathe": "breathe", "rest": "breathe", "again": "again", "hop": "hop",
          "stack": "stack", "cheer": "cheer", "exam": "exam", "away": "away", "hello": "in"}

# moments that happen once (an event); the rest loop while their state lasts
ONCE = frozenset({"peek", "ready", "ring", "again", "hop", "stack", "cheer", "in",
                  "twirl", "shuffle", "jump", "hug", "giftspin", "walkin", "popup", "point", "bigring",
                  "wobble", "catch", "knock", "bounce"})

LABELS = {"idle": "Pip", "nap": "Pip, napping", "peek": "Pip, peeking in", "ready": "Pip: let's go",
          "focus": "Pip, heads down", "ring": "Pip: fifteen's up", "stretch": "Pip, stretching",
          "breathe": "Pip, breathing", "rest": "Pip, resting", "again": "Pip: back to it",
          "hop": "Pip: day done", "stack": "Pip: session done", "cheer": "Pip: a cheer",
          "exam": "Pip: good luck", "away": "Pip, away", "hello": "Pip"}

# an angle per arm, from hanging straight down
_ARMS = {"down": (32, -32), "up": (155, -155), "wave": (32, -150), "hold": (-50, 50), "out": (100, -100),
         "pump": (32, -172), "cross": (-62, 62), "walk": (20, -12)}
_HOLD, _SIDE, _TOP = (40, 56), (67, 58), (40, 27)


HAND = (64.6, 56.8)  # the right hand of a hanging arm, where the closet draws what it holds


def _held_in(hand, arms):
    """What the right hand holds (drawn at HAND), moved into the right arm
    as `arms` (_ARMS) holds it: at its hand, upright. "" when it holds nothing."""
    a = _ARMS.get(arms, _ARMS["down"])
    return (f'<g transform="translate(0 11.5) rotate({-a[1]})"><g transform="translate({-HAND[0]} {-HAND[1]})">{hand}</g></g>'
            if hand else "")


def _arms(pose, hand=""):
    """The arms, behind or in front. hand (3.8.2): what the right hand
    holds, drawn at HAND; it's moved into the arm, so it goes where the hand
    goes (up for a hop, round for a wave), and stays upright."""
    a = _ARMS.get(pose, _ARMS["down"])
    limb = _r(-2.6, -1, 5.2, 12.5, 2.6, ACC)
    held = _held_in(hand, pose)
    html = "".join(f'<g transform="translate({x} 47) rotate({ang})"><g class="sv-arm{side}">{limb}{held if side == "R" else ""}</g></g>'
                   for side, x, ang in (("L", 21.5, a[0]), ("R", 58.5, a[1])))
    return ("", html) if pose in ("hold", "cross") else (html, "")  # held things go in front


def _eyes(st):
    out, pup = "", ""
    dx = 1.5 if st == "look" else 0
    dy = 1.6 if st == "down" else 0
    for x in (33, 47):
        if st in ("closed", "happy"):
            up = st == "happy"
            out += (f'<path d="M{_n(x - 4.2)} {_n(43 + (1.4 if up else .2))} q4.2 {_n(-4.6 if up else 3.8)} 8.4 0" '
                    f'fill="none" style="stroke:{INK}" stroke-width="2.2" stroke-linecap="round"/>')
            continue
        wide = st == "wide"
        out += f'<circle cx="{x}" cy="43" r="{6.4 if wide else 5.6}" fill="#fff"/>'
        pup += f'<circle cx="{_n(x + dx)}" cy="{_n(43 + dy)}" r="{2.1 if wide else 2.6}" style="fill:{INK}"/>'
    return f'<g class="sv-eyes">{out}' + (f'<g class="sv-pupils">{pup}</g>' if pup else "") + "</g>"


def _mouth(st):
    s = f'style="stroke:{INK}" stroke-width="2.2" stroke-linecap="round" fill="none"'
    if st == "grin":
        return f'<path d="M35 50.5 q5 7 10 0 z" style="fill:{INK}"/>'
    if st == "o":
        return f'<ellipse cx="40" cy="52.1" rx="1.9" ry="2.2" style="fill:{INK}"/>'
    if st == "flat":
        return f'<path d="M37 52.5 h6" {s}/>'
    return f'<path d="M36 51.5 q4 3.6 8 0" {s}/>'


def _cheeks():
    return "".join(f'<ellipse class="sv-cheek" cx="{x}" cy="50" rx="3.1" ry="1.8" style="fill:{BLUSH}"/>'
                   for x in (27.5, 52.5))


def _held(prop):
    h, out = _HOLD, ""
    if prop == "card":
        out = ('<g class="sv-card">' + _r(h[0] - 10, h[1] - 6.5, 20, 13, 2.4, "#fff", ' stroke-width=".8"', LINE)
               + _r(h[0] - 6.5, h[1] - 3, 9, 1.8, .9, MUT, ' opacity=".45"') + _r(h[0] - 6.5, h[1] + .6, 13, 1.8, .9, MUT, ' opacity=".3"')
               + _r(h[0] + 5.5, h[1] - 4.2, 2.6, 2.6, .5, ACC) + "</g>")
    elif prop == "clock":
        c = h
        out = ('<g class="sv-clock">' + _r(c[0] - 7.2, c[1] - 11.4, 4.4, 3, 1.2, AMB) + _r(c[0] + 2.8, c[1] - 11.4, 4.4, 3, 1.2, AMB)
               + f'<circle cx="{c[0]}" cy="{c[1]}" r="8.4" style="fill:#fff;stroke:{AMB}" stroke-width="2.2"/>'
               + f'<path d="M{c[0]} {c[1]} V{_n(c[1] - 5.2)} M{c[0]} {c[1]} L{_n(c[0] + 3.6)} {c[1] + 2}" '
               f'style="stroke:{INK}" stroke-width="1.6" stroke-linecap="round"/></g>')
    elif prop == "case":
        s = _SIDE
        out = (f'<g class="sv-case"><rect x="{_n(s[0] - 2.6)}" y="{_n(s[1] - 3.6)}" width="5.2" height="4.4" rx="1.6" '
               f'fill="none" style="stroke:{AMB}" stroke-width="1.6"/>' + _r(s[0] - 6, s[1], 12, 14, 2.4, AMB)
               + _r(s[0] - 6, s[1] + 5.2, 12, 1.6, 0, "#fff", ' opacity=".45"') + "</g>")
    elif prop == "gift":
        t = _TOP
        out = ('<g class="sv-gift">' + _r(t[0] - 5.5, t[1] - 15, 11, 11, 2, AMB) + _r(t[0] - .9, t[1] - 15, 1.8, 11, 0, "#fff")
               + _r(t[0] - 5.5, t[1] - 10.4, 11, 1.8, 0, "#fff")
               + f'<path d="M{t[0]} {t[1] - 15} q-3.5 -4 -4.5 -1 q0 2 4.5 1 q3.5 -4 4.5 -1 q0 2 -4.5 1" '
               f'fill="none" style="stroke:{AMB}" stroke-width="1.4"/></g>')
    return out


def _star(x, y, rr, fill):
    pts = []
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        rad = rr * .45 if i % 2 else rr
        pts.append(f"{_n(x + rad * math.cos(a))},{_n(y + rad * math.sin(a))}")
    return f'<polygon points="{" ".join(pts)}" style="fill:{fill}" stroke-linejoin="round"/>'


def _spark(x, y, rr, cls):
    return (f'<path class="spark {cls}" d="M{_n(x)} {_n(y - rr)} Q{_n(x)} {_n(y)} {_n(x + rr)} {_n(y)} '
            f'Q{_n(x)} {_n(y)} {_n(x)} {_n(y + rr)} Q{_n(x)} {_n(y)} {_n(x - rr)} {_n(y)} '
            f'Q{_n(x)} {_n(y)} {_n(x)} {_n(y - rr)}z" style="fill:{AMB}"/>')


def _fx(kinds, stack=3):
    """The moment's effects, drawn outside the body so they don't squash with it."""
    t, back, front = _TOP, "", ""
    for k in kinds:
        if k == "zz":
            for cls, size in (("z1", 8), ("z2", 9.5), ("z3", 11)):
                front += (f'<text class="sv-z {cls}" x="{_n(t[0] + 14)}" y="{_n(t[1] + 2)}" font-size="{size}" '
                          f'font-weight="800" style="fill:{MUT}">z</text>')
        elif k == "rings":
            c = _HOLD
            front += (f'<path class="sv-ring r1" d="M{_n(c[0] - 9)} {_n(c[1] - 9)} A12.5 12.5 0 0 1 {_n(c[0] + 9)} {_n(c[1] - 9)}" '
                      f'fill="none" style="stroke:{AMB}" stroke-width="1.8" stroke-linecap="round"/>'
                      f'<path class="sv-ring r2" d="M{_n(c[0] - 12.5)} {_n(c[1] - 11)} A16.5 16.5 0 0 1 {_n(c[0] + 12.5)} {_n(c[1] - 11)}" '
                      f'fill="none" style="stroke:{AMB}" stroke-width="1.5" stroke-linecap="round"/>')
        elif k == "star":
            front += (f'<g class="sv-star">{_star(t[0], t[1] - 12, 6.5, AMB)}</g>'
                      + _spark(t[0] - 13, t[1] - 16, 2.6, "s1") + _spark(t[0] + 13, t[1] - 9, 2.2, "s2"))
        elif k == "confetti":
            # the week's squares fly, Thursday's grey (Sam's pick)
            for i in range(7):
                a = (-160 + i * 23.3) * math.pi / 180
                d = 28 + (i % 2) * 6
                fill = LINE if i == 3 else ACC
                front += (f'<rect class="cf" x="{_n(t[0] - 2.6)}" y="{_n(t[1] - 5)}" width="5.2" height="5.2" rx=".9" '
                          f'style="fill:{fill};--dx:{_n(d * math.cos(a))}px;--dy:{_n(d * math.sin(a))}px;--r:{i * 47 - 120}deg"/>')
        elif k == "stack":
            for j in range(stack):
                front += (f'<g class="stk k{j + 1}">' + _r(t[0] - 5, t[1] - 13 - j * 11, 10, 10, 1.8, ACC,
                                                         ' stroke="#fff" stroke-width="1.2"') + "</g>")
            front += _spark(t[0] - 16, t[1] - 22, 3, "s1") + _spark(t[0] + 16, t[1] - 30, 2.6, "s2")
        elif k == "sparks":
            front += _spark(t[0] - 15, t[1] - 10, 2.8, "s1") + _spark(t[0] + 15, t[1] - 14, 2.4, "s2")
        elif k == "box":
            # breathe with Pip: a square, four counts a side
            back += (f'<rect x="8" y="8" width="64" height="64" rx="12" fill="none" style="stroke:{LINE}" '
                     'stroke-width="1.6" stroke-dasharray="3 3"/>'
                     f'<circle class="sv-boxdot" cx="8" cy="8" r="3.2" style="fill:{ACC}"/>')
            for cls, x, y, anchor, word in (("l1", 40, 4, "middle", "in"), ("l2", 78, 42, "start", "hold"),
                                            ("l3", 40, 80.5, "middle", "out"), ("l4", 2, 42, "end", "hold")):
                back += (f'<text class="lab {cls}" x="{x}" y="{y}" text-anchor="{anchor}" font-size="6.5" '
                         f'font-weight="700" style="fill:{MUT}">{word}</text>')
    return back, front


def busy(pose):
    """Whether `pose`'s hands are full (a card, the clock, a gift, the
    case, fingers crossed): then the closet's held thing is set down beside
    it (closet.art)."""
    p = POSES.get(pose) or POSES["idle"]
    return bool(p.get("prop")) or p["arms"] in ("hold", "cross")


def _figure(p, blush, look=None, worn=None):
    """Pip itself: feet, body, face, arms and what it holds. Every drawing's.
    look (3.8.2): what it has on from the closet: behind it, over it, in its
    hand. worn: that look already drawn, (back, front, hand), in its place
    (site_kit's blanks)."""
    back, front, hand = worn or ("", "", "")
    if look and not worn:
        from . import closet  # its drawings only when there's a look to draw
        back, front, hand = closet.art(look, pose_holds=bool(p.get("prop")) or p["arms"] in ("hold", "cross"))
    back_arms, front_arms = _arms(p["arms"], hand)
    body = (_r(28.5, 63, 9, 9.5, 3, ACC, ' class="sv-footL"') + _r(42.5, 63, 9, 9.5, 3, ACC, ' class="sv-footR"')
            + _r(20, 27, 40, 39, 12.5, ACC) + _r(25, 31, 11, 5, 2.5, "#fff", ' opacity=".22"')
            + _eyes(p["eyes"]) + _mouth(p["mouth"]) + (_cheeks() if blush else ""))
    return f'<g class="sv-body">{back}{back_arms}{body}{front}{front_arms}{_held(p.get("prop"))}</g>'


def svg(pose, moment=None, size=None, rest=False, label=None, cheeks=None, stack=None, look=None, worn=None):
    """Pip in `pose` (POSES), moving as `moment` (its own by default). rest:
    a moment that happens once has played already; it rests (and blinks).
    cheeks: blushing, which only a cheer does (Sam's pick) unless asked.
    stack: squares on its head, one a fifteen (three at most). look (3.8.2):
    what it has on from the closet (closet.clean rules it); worn: a look
    already drawn, (back, front, hand), in place of `look` (site_kit).
    3.9.1 (the efficiency run): the same Pip is drawn once, then kept (a
    fifteen's widgets draw thirty); a look that can't be a key is drawn as
    it comes."""
    if all(v is None or isinstance(v, (list, tuple)) for v in (look, worn)):
        try:
            return _svg_kept(pose, moment, size, rest, label, cheeks, stack,
                             tuple(look) if look else None, tuple(worn) if worn else None)
        except TypeError:
            pass
    return _svg(pose, moment, size, rest, label, cheeks, stack, look, worn)


@functools.lru_cache(maxsize=512)
def _svg_kept(pose, moment, size, rest, label, cheeks, stack, look, worn):
    return _svg(pose, moment, size, rest, label, cheeks, stack, list(look) if look else None, worn)


def _svg(pose, moment, size, rest, label, cheeks, stack, look, worn):
    p = POSES.get(pose) or POSES["idle"]
    m = moment or MOMENT.get(pose, "idle")
    blush = p.get("cheeks") if cheeks is None else cheeks
    fx_back, fx_front = _fx(p.get("fx") or (), max(1, min(3, int(stack or 3))))
    dims = f' width="{int(size)}" height="{int(size)}"' if size else ""
    cls = f"sv m-{m}" + (" rest" if rest and m in ONCE else "")
    return (f'<svg class="{cls}"{dims} viewBox="0 0 80 80" role="img" aria-label="{label or LABELS.get(pose, "Pip")}">'
            f'<ellipse class="sv-shadow" cx="40" cy="74.5" rx="16" ry="2.6" style="fill:{LINE}"/>{fx_back}'
            f'{_figure(p, blush, look, worn)}{fx_front}</svg>')


def still(pose, accent=None, line=None, ink=None, amb=None, mut=None, blush=None, look=None):
    """Pip in `pose` for a picture: an SVG of its own (it has the xmlns,
    width and height), each colour given or the drawing's own fallback, no
    classes, no motion. Just Pip: no shadow (it stands on what's under
    it) and none of the moment's effects (they're motion). The week card
    draws it (sharecard), in Qt here and on the site's canvas, whose
    cards.js keeps a copy the suite checks against this. look (3.8.2): what
    it has on from the closet; the copy draws Pip without one."""
    p = POSES.get(pose) or POSES["idle"]
    given = {"a": accent, "line": line, "ink": ink, "amb": amb, "mut": mut, "blush": blush}
    art = re.sub(r"var\(--sv-([a-z]+),(#[0-9a-f]+)\)", lambda m: given.get(m.group(1)) or m.group(2), _figure(p, p.get("cheeks"), look))
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80" viewBox="0 0 80 80">'
            + re.sub(r' class="[^"]*"', "", art) + "</svg>")


# Pip's body sits low in its drawing (its effects need the room above), so
# a box the drawing's size centres it too low and too loose. A slot is the
# body's own size: SLOT[0] of the drawing square, with the drawing placed so
# the body (arms, feet) sits in its middle; effects spill out of it. The
# widgets place it the same way, from these numbers (room_model hands them over).
SLOT = (0.6, -0.2, -0.32)


def slot(markup, size):
    """An svg() drawing, `size` px square, in a slot its body fills."""
    w, x, y = (round(size * k) for k in SLOT)
    return (f'<span class="sv-slot" style="width:{w}px;height:{w}px">'
            + markup.replace('<svg class="', f'<svg style="left:{x}px;top:{y}px;width:{size}px;height:{size}px" class="', 1)
            + "</span>")


# 3.8.2: duecrew.com's crew rows show each person's Pip as the add-on's do
# (board.row_sev). The site never draws Pip itself: site/public/sev.js holds
# this kit (tools/gen_sev_js.py writes it) and only fills in its blanks; the
# suite checks the file holds this kit, and that what it fills in is svg()'s.
ROW_SIZE = 30  # px: a crew row's Pip (board.row_sev), in its slot()
BLANKS = ("%B%", "%F%", "%H%")  # where a look's back, front and held things go


# 3.9.5: game night's places (site/public/table.js), each with its moves as here
GAME_PLACES = ("idle", "hello", "peek", "ready", "focus", "cheer", "hop", "again")


def site_kit():
    """A crew row's Pip for the site, as data. row: the still idle Pip in
    its slot, BLANKS where the look goes, its colours the page's (--sv-a and
    the rest, as svg()'s); held: what puts a held thing (its %H%) in the
    right hand; slots, costume, max: closet's SLOTS (drawn in that order,
    then a costume), COSTUME and LOOK_MAX; things: each thing's place, the
    other places it takes, and its drawing (front, back). Filled in as
    closet.art fills them, it's slot(svg("idle", rest=True, look=look),
    ROW_SIZE), to the byte. 3.9.5, game night: stage, each of GAME_PLACES'
    moves drawn as move() draws it ("place:moment" its key); places, the
    keys a place has, its own first; css, the motion sheet (CSS)."""
    from . import closet
    from .closet_art import ART
    held = _held_in(BLANKS[2], POSES["idle"]["arms"])
    row = slot(svg("idle", rest=True, worn=BLANKS), ROW_SIZE)
    if row.count(held) != 1 or any(row.count(b) != 1 for b in BLANKS):
        raise ValueError("site_kit: a blank isn't where the look goes")
    places = {pl: [f"{pl}:{m}" for m in moves(pl)] for pl in GAME_PLACES}
    stage = {k: move(k.split(":")[0], k.split(":")[1]) for ks in places.values() for k in ks}
    return {"row": row.replace(held, BLANKS[2]), "held": held, "slots": list(closet.SLOTS), "costume": closet.COSTUME,
            "max": closet.LOOK_MAX, "places": places, "stage": stage, "css": CSS,
            "things": {t["k"]: [t["slot"], list(t.get("also") or ()), ART[t["k"]][0], ART[t["k"]][1]]
                       for t in closet.THINGS}}


def stack_reach(n, size):
    """How far the squares Pip stacks (n of them, three at most) and its
    shadow reach out of its slot(), in px: (above, below). The session's
    line pads its Pip by these, so the box fits what's drawn (one square
    or three) and its words centre on Pip and its stack together."""
    k, y, w = size / 80, round(size * SLOT[2]), round(size * SLOT[0])
    top = _TOP[1] - 13 - 11 * (max(1, min(3, int(n or 1))) - 1)  # the highest square's top (_fx)
    return max(0, math.ceil(-(y + top * k))), max(0, math.ceil(y + 77.1 * k - w))  # 77.1: the shadow's bottom


# 3.8.1: in a study room each member is their Pip (room_model.seats); 3.9.0
# the peek's Pips, a bingo square's stamps, a plan card's squad line. Side by
# side they never blink together, nor one after another in turn (Sam: "still
# looks kinda creepy"): each blinks on its own clock, a cycle of its own
# (--sv-b) and its own place in it (--sv-d, a negative delay), so they drift
# past each other and no order shows for long.
BLINK = 4.6  # s: a Pip's blink cycle on its own (sv-blink, below)


def blink(i):
    """The i-th Pip of several: (cycle, delay) in s for its blink. Cycles
    from 3.4 to 6.4 s and places in them spread apart (golden steps, a
    little jitter), so no two of a group start or stay together; from i
    alone, so a redraw draws the same and nothing moves for it."""
    r = random.Random(f"sev-blink:{i}")
    cycle = round(3.4 + ((i * 0.382 + r.random() * 0.08) % 1) * 3.0, 2)
    return cycle, -round(((i * 0.618 + r.random() * 0.08) % 1) * cycle, 2)


def blink_css(i):
    """blink(i) as the style that sets it, on a Pip's wrapper."""
    cycle, delay = blink(i)
    return f"--sv-b:{cycle}s;--sv-d:{delay}s"


# 3.8.1 (Sam): by the logo Pip is a moment, not a fixture. It comes when
# something just happened, plays it, and goes; the rest of the time the
# logo is alone. LOGO_SECONDS: how long it stays.
LOGO_SECONDS = 5


def moment(cheered=False, back=False, exam_eve=False, day_done=False):
    """What brings Pip beside the logo, or None: a cheer that just landed,
    the first day back from away (a wave), the night before an exam (a
    star), the day done (a hop, the week's squares flying). Never a mood
    that lasts, never cross."""
    if cheered:
        return "cheer"
    if back:
        return "hello"
    if exam_eve:
        return "exam"
    if day_done:
        return "hop"
    return None


# 3.8.1 (Sam: "variety!"): each place Pip goes has its mix of moves, the
# place's own first, as (pose, moment). Each time it comes it plays a
# different one, never the same twice in a row (pick: at random, not the
# last; nth: in turn). Where it stays a while (a fifteen, a break, a room's
# seats) the move loops, one small thing now and then. A break's moves are
# Stretch's; Breathe stays itself.
MOVES = {
    "hop": (("hop", "hop"), ("hop", "twirl"), ("hop", "shuffle"), ("hop", "jump")),
    "cheer": (("cheer", "cheer"), ("cheer", "hug"), ("cheer", "giftspin")),
    "hello": (("hello", "in"), ("hello", "walkin"), ("hello", "popup")),
    "exam": (("exam", "exam"), ("exam", "pep")),
    "focus": (("focus", "focus"), ("focus", "nod"), ("focus", "think"), ("focus", "tap")),
    "stretch": (("stretch", "stretch"), ("stretch", "shake"), ("idle", "march"), ("idle", "look")),
    "ring": (("ring", "ring"), ("ring", "point"), ("ring", "bigring")),
    "stack": (("stack", "stack"), ("stack", "wobble"), ("stack", "catch")),
    "peek": (("peek", "peek"), ("peek", "knock"), ("peek", "bounce")),
}
# a study room's seats, each its own: blinks, reads, nods, reaches, looks around
SEAT_MOVES = ("idle", "sread", "snod", "sreach", "slook")


def moves(place):
    """The moments Pip can play at `place` (a MOVES key, or any pose: just its own), its own first."""
    return tuple(m for _p, m in MOVES[place]) if place in MOVES else (MOMENT.get(place, "idle"),)


def pick(place, last=None, rnd=random):
    """A move for `place`, at random, never `last` (the one it played there last time)."""
    ms = moves(place)
    return rnd.choice([m for m in ms if m != last] or list(ms))


def nth(place, n):
    """The n-th of `place`'s moves, in turn: one after another, never the same."""
    ms = moves(place)
    return ms[int(n) % len(ms)]


def move(place, m=None, **kw):
    """Pip at `place` playing its move `m` (its own when m isn't one of
    them), labelled as the place is; the rest goes to svg()."""
    pose, mm = next(((p, x) for p, x in MOVES.get(place, ()) if x == m), (place, None))
    kw.setdefault("label", LABELS.get(place))
    return svg(pose, mm, **kw)


# the motion sheet. Outside the media query: the still frame of each moment.
# Inside it: the motion, which ends where a moment rests.
CSS = r"""
svg.sv { overflow: visible; display: block; flex: none; }
.sv-slot { position: relative; display: inline-block; flex: none; vertical-align: middle; }
.sv-slot > svg.sv { position: absolute; }
.sv .sv-body, .sv .sv-shadow, .sv .sv-eyes, .sv .sv-pupils, .sv .sv-card, .sv .sv-clock,
.sv .sv-case, .sv .sv-star, .sv .sv-gift, .sv .sv-z, .sv .cf, .sv .stk, .sv .sv-ring, .sv .spark, .sv .sv-cheek,
.sv .sv-footL, .sv .sv-footR, .sv .sv-boxdot { transform-box: fill-box; }
.sv .sv-body { transform-origin: 50% 100%; }
.sv .sv-shadow, .sv .sv-eyes, .sv .sv-card, .sv .sv-clock, .sv .sv-star, .sv .sv-gift, .sv .sv-z, .sv .cf, .sv .stk,
.sv .spark, .sv .sv-ring { transform-origin: 50% 50%; }
/* 3.8.2: an arm turns at its shoulder, the origin of its own drawing, whatever its hand holds */
.sv .sv-armL, .sv .sv-armR { transform-box: view-box; transform-origin: 0 0; }
.sv .sv-footL, .sv .sv-footR { transform-origin: 30% 100%; }
.sv .sv-case { transform-origin: 50% 0%; }
.sv .sv-cheek { opacity: .6; }
.sv.m-stack .spark, .sv.m-cheer .spark, .sv.m-hug .spark, .sv.m-giftspin .spark, .sv.m-wobble .spark,
.sv.m-catch .spark { opacity: 0; } /* they twinkle once and go: at rest, and still, they're gone */
.sv .sv-z.z2 { transform: translate(6px, -8px); }
.sv .sv-z.z3 { transform: translate(12px, -16px); }
.sv .cf { transform: translate(var(--dx), var(--dy)) rotate(var(--r)); }
.sv .lab { opacity: .35; }
.sv .lab.l1 { opacity: 1; }
/* 3.9.0: moved in the drawing's own units, a plain body's share (45.5 tall: 22% is 10), never a share of
   the body's box, which what Pip has on makes taller (Sam: a pumpkin and an umbrella sank it) */
.sv.m-peek .sv-body, .sv.m-knock .sv-body, .sv.m-bounce .sv-body { transform: translateY(10px); }
.sv.m-peek .sv-shadow, .sv.m-in .sv-shadow, .sv.m-knock .sv-shadow, .sv.m-bounce .sv-shadow,
.sv.m-popup .sv-shadow { display: none; }
.sv.m-hop .sv-body, .sv.m-twirl .sv-body, .sv.m-shuffle .sv-body, .sv.m-jump .sv-body { transform: translateY(-12px); }
/* 3.8.2: the closet's things that move: each turns on its own point */
.sv .cl-prop, .sv .cl-steam, .sv .cl-flame, .sv .cl-flick, .sv .cl-bal, .sv .cl-flag, .sv .cl-blink, .sv .cl-glow,
.sv .cl-wing { transform-box: fill-box; }
.sv .cl-prop, .sv .cl-blink, .sv .cl-glow { transform-origin: 50% 50%; }
.sv .cl-flame { transform-origin: 50% 0%; }
.sv .cl-flick, .sv .cl-steam { transform-origin: 50% 100%; }
.sv .cl-bal { transform-origin: 0% 100%; }
.sv .cl-flag { transform-origin: 0% 50%; }
.sv .cl-wl { transform-origin: 100% 40%; }
.sv .cl-wr { transform-origin: 0% 40%; }
/* 3.9.1 (the efficiency run; Sam's pick, "Pip at rest" A): each loop plays
   about twelve seconds once Pip's drawn, then Pip rests (a loop that never
   ended kept Anki drawing 60 frames a second, on every screen); pointing at
   Pip plays it on. The break's breathing and stretch go on for the break:
   they're the exercise */
.sv:hover, .sv-slot:hover .sv { --sv-on: infinite; }
@media (prefers-reduced-motion: no-preference) {
  .sv .sv-eyes { animation: sv-blink var(--sv-b, 4.6s) var(--sv-d, 0s) var(--sv-on, 3); }
  @keyframes sv-blink { 0%, 90%, 100% { transform: scaleY(1); } 93% { transform: scaleY(.12); } 96% { transform: scaleY(1); } }
  /* napping: nothing studied yet today */
  .sv.m-nap .sv-body { animation: sv-breathe 3.2s ease-in-out var(--sv-on, 4); }
  .sv.m-nap .sv-eyes { animation: none; }
  .sv.m-nap .sv-z { animation: sv-zf 3.6s ease-out var(--sv-on, 4); }
  .sv.m-nap .sv-z.z2 { animation-delay: 1.2s; }
  .sv.m-nap .sv-z.z3 { animation-delay: 2.4s; }
  @keyframes sv-breathe { 0%, 100% { transform: scale(1, 1); } 50% { transform: scale(1.025, 1.05); } }
  @keyframes sv-zf { 0% { opacity: 0; transform: translate(0, 0) scale(.6); } 20% { opacity: 1; }
    100% { opacity: 0; transform: translate(9px, -18px) scale(1.15); } }
  /* peeking in, from behind the nudge: up once, a wave */
  .sv.m-peek .sv-body { animation: sv-peek .7s cubic-bezier(.34, 1.56, .64, 1) 1 both; }
  .sv.m-peek .sv-armR { animation: sv-wave 1.6s ease-in-out .5s 1 both; }
  @keyframes sv-peek { from { transform: translateY(34.1px); } to { transform: translateY(10px); } }
  @keyframes sv-wave { 0%, 100% { transform: rotate(0); } 20%, 60% { transform: rotate(-26deg); } 40%, 80% { transform: rotate(10deg); } }
  /* let's go: a squash, a jump, a fist */
  .sv.m-ready .sv-body { animation: sv-ready .9s ease-out 1 both; }
  .sv.m-ready .sv-armR { animation: sv-pump .9s ease-out 1 both; }
  .sv.m-ready .sv-shadow, .sv.m-hop .sv-shadow { animation: sv-shad .9s ease-out 1 both; }
  @keyframes sv-ready { 0% { transform: none; } 22% { transform: scale(1.14, .84); } 50% { transform: translateY(-13px) scale(.93, 1.09); }
    78% { transform: translateY(0) scale(1.08, .92); } 100% { transform: none; } }
  @keyframes sv-pump { 0%, 25% { transform: rotate(0); } 50% { transform: rotate(-24deg); } 70% { transform: rotate(14deg); } 100% { transform: rotate(0); } }
  @keyframes sv-shad { 0%, 20% { transform: scaleX(1); opacity: 1; } 50% { transform: scaleX(.62); opacity: .55; } 100% { transform: scaleX(1); opacity: 1; } }
  /* heads down: a blink every seven seconds, eyes along the card, the card turns now and then */
  .sv.m-focus .sv-eyes { animation-duration: 7s; }
  .sv.m-focus .sv-pupils { animation: sv-read 1.75s ease-in-out var(--sv-on, 8) alternate; }
  .sv.m-focus .sv-card { animation: sv-flip 7s ease-in-out var(--sv-on, 2); }
  @keyframes sv-read { from { transform: translateX(-1.4px); } to { transform: translateX(1.4px); } }
  @keyframes sv-flip { 0%, 46%, 54%, 100% { transform: scaleX(1); } 50% { transform: scaleX(.06); } }
  /* the fifteen's up: the clock rings */
  .sv.m-ring .sv-clock { animation: sv-shake .8s linear 1 both; }
  .sv.m-ring .sv-body { animation: sv-startle .8s ease-out 1 both; }
  .sv.m-ring .sv-ring { animation: sv-rings 1.2s ease-out 1 both; }
  .sv.m-ring .sv-ring.r2 { animation-delay: .18s; }
  @keyframes sv-shake { 0%, 100% { transform: rotate(0); } 10%, 30%, 50% { transform: rotate(-15deg); } 20%, 40%, 60% { transform: rotate(15deg); }
    75% { transform: rotate(-6deg); } }
  @keyframes sv-startle { 0% { transform: none; } 15% { transform: translateY(-6px) scale(.95, 1.06); } 40% { transform: scale(1.05, .95); } 60%, 100% { transform: none; } }
  @keyframes sv-rings { 0% { opacity: 0; transform: scale(.8); } 15% { opacity: 1; } 100% { opacity: 0; transform: scale(1.35); } }
  /* the break: a stretch, or breathe with Pip (a square, four counts a side) */
  .sv.m-stretch .sv-body { animation: sv-stretch 4s ease-in-out infinite; }
  .sv.m-stretch .sv-armL { animation: sv-armwig 4s ease-in-out infinite; }
  .sv.m-stretch .sv-armR { animation: sv-armwig 4s ease-in-out infinite reverse; }
  @keyframes sv-stretch { 0%, 100% { transform: none; } 20% { transform: rotate(-9deg); } 40% { transform: none; }
    55% { transform: translateY(-4px) scale(.96, 1.07); } 70% { transform: none; } 85% { transform: rotate(9deg); } }
  @keyframes sv-armwig { 0%, 100% { transform: rotate(0); } 25% { transform: rotate(14deg); } 75% { transform: rotate(-14deg); } }
  .sv.m-breathe .sv-body { animation: sv-box 16s ease-in-out infinite; }
  .sv.m-breathe .sv-eyes { animation: none; }
  .sv.m-breathe .sv-boxdot { animation: sv-boxdot 16s linear infinite; }
  .sv.m-breathe .lab { animation: sv-lab 16s linear infinite; opacity: .35; }
  .sv.m-breathe .lab.l2 { animation-delay: 4s; } .sv.m-breathe .lab.l3 { animation-delay: 8s; } .sv.m-breathe .lab.l4 { animation-delay: 12s; }
  @keyframes sv-box { 0% { transform: scale(1); } 25%, 50% { transform: scale(1.08); } 75%, 100% { transform: scale(1); } }
  @keyframes sv-boxdot { 0% { transform: translate(0, 0); } 25% { transform: translate(64px, 0); } 50% { transform: translate(64px, 64px); }
    75% { transform: translate(0, 64px); } 100% { transform: translate(0, 0); } }
  @keyframes sv-lab { 0%, 24.5% { opacity: 1; } 25%, 100% { opacity: .35; } }
  /* back to it: shake it out, a fresh card pops into its hands */
  .sv.m-again .sv-body { animation: sv-shakeout .8s ease-in-out 1 both; }
  .sv.m-again .sv-card { animation: sv-popin .8s cubic-bezier(.34, 1.56, .64, 1) .3s 1 both; }
  @keyframes sv-shakeout { 0%, 100% { transform: none; } 20% { transform: rotate(-8deg); } 40% { transform: rotate(8deg); } 60% { transform: rotate(-5deg); } 80% { transform: rotate(5deg); } }
  @keyframes sv-popin { 0% { transform: scale(0); } 60% { transform: scale(1.15); } 100% { transform: scale(1); } }
  /* day done: a hop, and the week's squares fly */
  .sv.m-hop .sv-body { animation: sv-hop 1.2s ease-out 1 both; }
  .sv.m-hop .sv-shadow { animation-duration: 1.2s; }
  .sv.m-hop .cf { animation: sv-cf 1.8s cubic-bezier(.2, .7, .3, 1) 1 both; }
  @keyframes sv-hop { 0% { transform: none; } 15% { transform: scale(1.16, .82); } 40% { transform: translateY(-20px) scale(.92, 1.1); }
    62% { transform: translateY(-22px) scale(1); } 85% { transform: translateY(0) scale(1.12, .88); } 100% { transform: none; } }
  @keyframes sv-cf { 0%, 25% { opacity: 0; transform: translate(0, 0) scale(.4); } 32% { opacity: 1; }
    65% { opacity: 1; transform: translate(var(--dx), var(--dy)) rotate(var(--r)) scale(1); }
    100% { opacity: 0; transform: translate(var(--dx), calc(var(--dy) + 12px)) rotate(var(--r)); } }
  /* a session done: a square on its head for each fifteen */
  .sv.m-stack .stk { animation: sv-stk .6s cubic-bezier(.34, 1.4, .64, 1) 1 both; }
  .sv.m-stack .stk.k2 { animation-delay: .5s; } .sv.m-stack .stk.k3 { animation-delay: 1s; }
  .sv.m-stack .sv-body { animation: sv-stkbody 1.6s ease-out 1 both; }
  @keyframes sv-stk { 0% { opacity: 0; transform: translateY(-30px); } 60% { opacity: 1; transform: translateY(0) scale(1.12, .84); } 100% { opacity: 1; transform: none; } }
  @keyframes sv-stkbody { 0%, 20% { transform: none; } 27% { transform: scale(1.05, .95); } 35%, 51% { transform: none; } 58% { transform: scale(1.05, .95); }
    66%, 82% { transform: none; } 89% { transform: scale(1.05, .95); } 100% { transform: none; } }
  .sv.m-stack .spark, .sv.m-cheer .spark { animation: sv-spark 1.4s ease-out 1.1s 1 both; }
  .sv.m-stack .spark.s2, .sv.m-cheer .spark.s2 { animation-delay: 1.3s; }
  @keyframes sv-spark { 0% { opacity: 0; transform: scale(.2) rotate(0); } 30% { opacity: 1; transform: scale(1.2) rotate(30deg); } 100% { opacity: 0; transform: scale(.6) rotate(60deg); } }
  /* a cheer lands: a gift, caught, and a blush */
  .sv.m-cheer .sv-gift { animation: sv-gift 1.2s cubic-bezier(.5, 0, .75, 0) 1 both; }
  .sv.m-cheer .sv-body { animation: sv-catch 1.4s ease-out 1 both; }
  .sv.m-cheer .sv-cheek { animation: sv-blush 1.6s ease-out 1 both; }
  .sv.m-cheer .spark { animation-delay: .9s; } .sv.m-cheer .spark.s2 { animation-delay: 1.1s; }
  @keyframes sv-gift { 0% { opacity: 0; transform: translateY(-36px) rotate(-12deg); } 15% { opacity: 1; } 70% { transform: translateY(0) rotate(0); }
    82% { transform: translateY(2px) scale(1.12, .86); } 100% { transform: none; opacity: 1; } }
  @keyframes sv-catch { 0%, 55% { transform: none; } 68% { transform: scale(1.08, .9); } 85%, 100% { transform: none; } }
  @keyframes sv-blush { 0%, 60% { opacity: 0; } 100% { opacity: .6; } }
  /* exam eve: a star that twinkles, fingers crossed */
  .sv.m-exam .sv-star { animation: sv-twinkle 2.6s ease-in-out var(--sv-on, 5); }
  .sv.m-exam .sv-body { animation: sv-bob 2.6s ease-in-out var(--sv-on, 5); }
  .sv.m-exam .spark { animation: sv-sparkle 2.6s ease-in-out var(--sv-on, 5); }
  .sv.m-exam .spark.s2 { animation-delay: 1.3s; }
  @keyframes sv-twinkle { 0%, 100% { transform: rotate(0) scale(1); } 50% { transform: rotate(18deg) scale(1.24); } }
  @keyframes sv-sparkle { 0%, 100% { opacity: .2; transform: scale(.6); } 50% { opacity: 1; transform: scale(1.1); } }
  /* away: off on a trip */
  .sv.m-away .sv-body { animation: sv-bob 1.2s ease-in-out var(--sv-on, 10); }
  .sv.m-away .sv-footL { animation: sv-step 1.2s ease-in-out var(--sv-on, 10); }
  .sv.m-away .sv-footR { animation: sv-step 1.2s ease-in-out -.6s var(--sv-on, 10); }
  .sv.m-away .sv-case { animation: sv-sway 1.2s ease-in-out var(--sv-on, 10); }
  @keyframes sv-bob { 0%, 50%, 100% { transform: none; } 25%, 75% { transform: translateY(-2.5px); } }
  @keyframes sv-step { 0%, 50%, 100% { transform: none; } 25% { transform: translateY(-3px); } }
  @keyframes sv-sway { 0%, 100% { transform: rotate(-5deg); } 50% { transform: rotate(5deg); } }
  /* hello: Pip switched on in Settings pops in and waves */
  .sv.m-in .sv-body { animation: sv-in .5s cubic-bezier(.34, 1.56, .64, 1) 1 both; }
  .sv.m-in .sv-armR { animation: sv-wave 1.6s ease-in-out .3s 1 both; }
  @keyframes sv-in { 0% { transform: scale(0); } 70% { transform: scale(1.14); } 100% { transform: scale(1); } }
  /* 3.8.1, more moves: the day's done */
  .sv.m-twirl .sv-body { animation: sv-twirl 1.5s ease-in-out 1 both; }
  .sv.m-twirl .cf, .sv.m-shuffle .cf, .sv.m-jump .cf { animation: sv-cf 1.8s cubic-bezier(.2, .7, .3, 1) .35s 1 both; }
  .sv.m-twirl .sv-shadow, .sv.m-jump .sv-shadow { animation: sv-shad 1.4s ease-out 1 both; }
  @keyframes sv-twirl { 0% { transform: none; } 14% { transform: scale(1.12, .88); } 34% { transform: translateY(-14px) scaleX(-1); }
    54% { transform: translateY(-17px) scaleX(1); } 74% { transform: translateY(-8px) scaleX(-1); } 90% { transform: translateY(0) scale(1.08, .92); } 100% { transform: none; } }
  .sv.m-shuffle .sv-body { animation: sv-shuffle .8s ease-in-out 3 both; }
  .sv.m-shuffle .sv-footL { animation: sv-step .4s ease-in-out 6; }
  .sv.m-shuffle .sv-footR { animation: sv-step .4s ease-in-out -.2s 6; }
  .sv.m-shuffle .sv-armL, .sv.m-shuffle .sv-armR { animation: sv-armwig .8s ease-in-out 3; }
  @keyframes sv-shuffle { 0%, 100% { transform: none; } 25% { transform: translateX(-5px) rotate(-7deg); } 50% { transform: none; } 75% { transform: translateX(5px) rotate(7deg); } }
  .sv.m-jump .sv-body { animation: sv-jump 1.4s cubic-bezier(.3, .7, .4, 1) 1 both; }
  .sv.m-jump .sv-armL { animation: sv-pumpL 1.4s ease-out 1 both; }
  .sv.m-jump .sv-armR { animation: sv-pump 1.4s ease-out 1 both; }
  @keyframes sv-jump { 0% { transform: none; } 22% { transform: scale(1.24, .74); } 46% { transform: translateY(-34px) scale(.9, 1.12); }
    62% { transform: translateY(-36px) rotate(10deg); } 84% { transform: translateY(0) scale(1.16, .84); } 100% { transform: none; } }
  @keyframes sv-pumpL { 0%, 25% { transform: rotate(0); } 50% { transform: rotate(24deg); } 70% { transform: rotate(-14deg); } 100% { transform: rotate(0); } }
  /* 3.8.1, more moves: a cheer lands */
  .sv.m-hug .sv-gift, .sv.m-giftspin .sv-gift { animation: sv-gift 1.2s cubic-bezier(.5, 0, .75, 0) 1 both; }
  .sv.m-hug .sv-body { animation: sv-hug 2.6s ease-in-out 1 both; }
  .sv.m-hug .sv-cheek, .sv.m-giftspin .sv-cheek { animation: sv-blush 1.6s ease-out .5s 1 both; }
  @keyframes sv-hug { 0%, 46% { transform: none; } 56% { transform: scale(1.07, .93) rotate(-6deg); } 68% { transform: scale(1.07, .93) rotate(6deg); }
    80% { transform: scale(1.05, .95) rotate(-4deg); } 92%, 100% { transform: none; } }
  .sv.m-giftspin .sv-body { animation: sv-giftspin 2.2s ease-in-out 1 both; }
  .sv.m-hug .spark, .sv.m-giftspin .spark { animation: sv-spark 1.4s ease-out 1.3s 1 both; }
  .sv.m-hug .spark.s2, .sv.m-giftspin .spark.s2 { animation-delay: 1.5s; }
  @keyframes sv-giftspin { 0%, 50% { transform: none; } 62% { transform: translateY(-8px) scaleX(-1); } 74% { transform: translateY(-10px) scaleX(1); }
    86% { transform: translateY(0) scale(1.07, .93); } 100% { transform: none; } }
  /* 3.8.1, more moves: back from away */
  .sv.m-walkin .sv-body, .sv.m-walkin .sv-shadow { animation: sv-walkin 1.4s linear 1 both; }
  .sv.m-walkin .sv-footL { animation: sv-step .35s ease-in-out 4; }
  .sv.m-walkin .sv-footR { animation: sv-step .35s ease-in-out -.175s 4; }
  .sv.m-walkin .sv-armR { animation: sv-wave 1.6s ease-in-out 1.35s 1 both; }
  @keyframes sv-walkin { 0% { transform: translateX(-40px); } 12% { transform: translateX(-34px) translateY(-2px); } 24% { transform: translateX(-28px); }
    36% { transform: translateX(-22px) translateY(-2px); } 48% { transform: translateX(-16px); } 60% { transform: translateX(-10px) translateY(-2px); }
    72% { transform: translateX(-5px); } 84% { transform: translateX(-1px) translateY(-2px); } 100% { transform: none; } }
  .sv.m-popup .sv-body { animation: sv-popup .9s cubic-bezier(.34, 1.56, .64, 1) 1 both; }
  .sv.m-popup .sv-armR { animation: sv-wave 1.6s ease-in-out .55s 1 both; }
  .sv.m-popup .sv-armL { animation: sv-waveL 1.6s ease-in-out .65s 1 both; }
  @keyframes sv-popup { 0% { transform: translateY(36.4px) scale(.92); } 65% { transform: translateY(-8px); } 100% { transform: none; } }
  @keyframes sv-waveL { 0%, 100% { transform: rotate(0); } 20%, 60% { transform: rotate(26deg); } 40%, 80% { transform: rotate(-10deg); } }
  /* 3.8.1, more moves: exam eve */
  .sv.m-pep .sv-star { animation: sv-spin 2.6s ease-in-out var(--sv-on, 5); }
  .sv.m-pep .sv-armR { animation: sv-pep 2.6s ease-out var(--sv-on, 5); }
  .sv.m-pep .sv-body { animation: sv-pepb 2.6s ease-out var(--sv-on, 5); }
  .sv.m-pep .spark { animation: sv-sparkle 2.6s ease-in-out var(--sv-on, 5); }
  @keyframes sv-spin { 0% { transform: rotate(0) scale(1); } 50% { transform: rotate(180deg) scale(1.25); } 100% { transform: rotate(360deg) scale(1); } }
  @keyframes sv-pep { 0%, 40%, 100% { transform: rotate(0); } 52% { transform: rotate(-30deg); } 64% { transform: rotate(6deg); } 76% { transform: rotate(-30deg); } 88% { transform: rotate(0); } }
  @keyframes sv-pepb { 0%, 40%, 100% { transform: none; } 52%, 76% { transform: translateY(-3px) scale(.97, 1.04); } 64%, 88% { transform: scale(1.04, .96); } }
  /* 3.8.1, more moves: in a fifteen: the same reading, plus one small thing now and then */
  .sv.m-nod .sv-eyes, .sv.m-think .sv-eyes, .sv.m-tap .sv-eyes { animation-duration: 7s; }
  .sv.m-nod .sv-pupils, .sv.m-tap .sv-pupils { animation: sv-read 1.75s ease-in-out var(--sv-on, 8) alternate; }
  .sv.m-nod .sv-card, .sv.m-tap .sv-card { animation: sv-flip 9s ease-in-out var(--sv-on, 2); }
  .sv.m-nod .sv-body { animation: sv-nod 6s ease-in-out var(--sv-on, 2); }
  @keyframes sv-nod { 0%, 70%, 100% { transform: none; } 75% { transform: rotate(5deg) translateY(1px); } 80% { transform: none; }
    85% { transform: rotate(5deg) translateY(1px); } 90% { transform: none; } }
  .sv.m-think .sv-armR { animation: sv-scratch 7s ease-in-out var(--sv-on, 2); }
  .sv.m-think .sv-pupils { animation: sv-lookup 7s ease-in-out var(--sv-on, 2); }
  @keyframes sv-scratch { 0%, 55%, 100% { transform: rotate(0); } 63% { transform: rotate(-205deg); } 67% { transform: rotate(-192deg); } 71% { transform: rotate(-205deg); }
    75% { transform: rotate(-192deg); } 79% { transform: rotate(-205deg); } 88% { transform: rotate(0); } }
  @keyframes sv-lookup { 0%, 55%, 90%, 100% { transform: none; } 62%, 84% { transform: translate(1.3px, -1.5px); } }
  .sv.m-tap .sv-footR { animation: sv-tap .9s ease-in-out var(--sv-on, 14); }
  @keyframes sv-tap { 0%, 50%, 100% { transform: none; } 25% { transform: rotate(-16deg); } }
  /* 3.8.1, more moves: on a break */
  .sv.m-shake .sv-body { animation: sv-shake2 3.2s ease-in-out var(--sv-on, 4); }
  .sv.m-shake .sv-armL { animation: sv-flap 3.2s ease-in-out var(--sv-on, 4); }
  .sv.m-shake .sv-armR { animation: sv-flap 3.2s ease-in-out -.1s var(--sv-on, 4) reverse; }
  @keyframes sv-shake2 { 0%, 50%, 100% { transform: none; } 56% { transform: rotate(-9deg); } 62% { transform: rotate(9deg); } 68% { transform: rotate(-7deg); }
    74% { transform: rotate(7deg); } 80% { transform: rotate(-3deg); } 86% { transform: none; } }
  @keyframes sv-flap { 0%, 50%, 100% { transform: rotate(0); } 56% { transform: rotate(32deg); } 62% { transform: rotate(-22deg); } 68% { transform: rotate(28deg); }
    74% { transform: rotate(-16deg); } 82% { transform: rotate(0); } }
  .sv.m-march .sv-body { animation: sv-bob .9s ease-in-out var(--sv-on, 14); }
  .sv.m-march .sv-footL { animation: sv-stepup .9s ease-in-out var(--sv-on, 14); }
  .sv.m-march .sv-footR { animation: sv-stepup .9s ease-in-out -.45s var(--sv-on, 14); }
  .sv.m-march .sv-armL { animation: sv-armwig .9s ease-in-out var(--sv-on, 14); }
  .sv.m-march .sv-armR { animation: sv-armwig .9s ease-in-out -.45s var(--sv-on, 14); }
  @keyframes sv-stepup { 0%, 50%, 100% { transform: none; } 25% { transform: translateY(-5px); } }
  .sv.m-look .sv-pupils { animation: sv-look 7s ease-in-out var(--sv-on, 2); }
  .sv.m-look .sv-body { animation: sv-lean 7s ease-in-out var(--sv-on, 2); }
  @keyframes sv-look { 0%, 100% { transform: none; } 15%, 30% { transform: translate(-1.7px, -1px); } 45%, 60% { transform: translate(1.7px, -1px); }
    72%, 86% { transform: translate(0, -1.8px); } }
  @keyframes sv-lean { 0%, 100% { transform: none; } 22% { transform: rotate(-3deg); } 52% { transform: rotate(3deg); } 78% { transform: translateY(-2px); } }
  /* 3.8.1, more moves: the question */
  .sv.m-point .sv-clock { animation: sv-shake .8s linear .5s 1 both; }
  .sv.m-point .sv-armR { animation: sv-point 2s ease-in-out 1 both; }
  .sv.m-point .sv-ring { animation: sv-rings 1.2s ease-out .5s 1 both; }
  .sv.m-point .sv-ring.r2 { animation-delay: .68s; }
  @keyframes sv-point { 0% { transform: rotate(0); } 25% { transform: rotate(-78deg); } 40% { transform: rotate(-66deg); } 55% { transform: rotate(-78deg); }
    70% { transform: rotate(-66deg); } 85%, 100% { transform: rotate(-74deg); } }
  .sv.m-bigring .sv-body { animation: sv-jump 1.3s cubic-bezier(.3, .7, .4, 1) 1 both; }
  .sv.m-bigring .sv-clock { animation: sv-shake .8s linear .2s 2 both; }
  .sv.m-bigring .sv-ring { animation: sv-rings 1.2s ease-out .2s 2 both; }
  .sv.m-bigring .sv-ring.r2 { animation-delay: .38s; }
  .sv.m-bigring .sv-shadow { animation: sv-shad 1.3s ease-out 1 both; }
  /* 3.8.1, more moves: the session's line */
  .sv.m-wobble .stk { animation: sv-stkw 2.2s ease-out 1 both; transform-origin: 50% 100%; }
  .sv.m-wobble .stk.k2 { animation-delay: .35s; } .sv.m-wobble .stk.k3 { animation-delay: .7s; }
  @keyframes sv-stkw { 0% { opacity: 0; transform: translateY(-30px); } 22% { opacity: 1; transform: translateY(0) scale(1.1, .86); } 34% { transform: none; }
    48% { transform: rotate(10deg); } 60% { transform: rotate(-8deg); } 72% { transform: rotate(5deg); } 84% { transform: rotate(-2deg); } 100% { opacity: 1; transform: none; } }
  .sv.m-wobble .sv-body { animation: sv-wobb 2.2s ease-in-out 1 both; }
  @keyframes sv-wobb { 0%, 40% { transform: none; } 48% { transform: rotate(-4deg); } 60% { transform: rotate(4deg); } 72% { transform: rotate(-2deg); } 84%, 100% { transform: none; } }
  .sv.m-catch .stk { animation: sv-stk .6s cubic-bezier(.34, 1.4, .64, 1) 1 both; }
  .sv.m-catch .stk.k1 { animation-delay: .5s; } .sv.m-catch .stk.k2 { animation-delay: 1s; } .sv.m-catch .stk.k3 { animation-delay: 1.5s; }
  .sv.m-catch .sv-body, .sv.m-catch .sv-shadow { animation: sv-under 2.2s ease-in-out 1 both; }
  @keyframes sv-under { 0% { transform: translateX(-18px); } 18% { transform: translateX(3px); } 26% { transform: none; } 40% { transform: translateX(-3px); }
    48% { transform: none; } 62% { transform: translateX(3px); } 70%, 100% { transform: none; } }
  .sv.m-wobble .spark, .sv.m-catch .spark { animation: sv-spark 1.4s ease-out 1.6s 1 both; }
  .sv.m-wobble .spark.s2, .sv.m-catch .spark.s2 { animation-delay: 1.8s; }
  /* 3.8.1, more moves: the nudge */
  .sv.m-knock .sv-body { animation: sv-peek .7s cubic-bezier(.34, 1.56, .64, 1) 1 both; }
  .sv.m-knock .sv-armR { animation: sv-knock 1.4s ease-in-out .6s 1 both; }
  @keyframes sv-knock { 0%, 100% { transform: rotate(0); } 15% { transform: rotate(-52deg); } 25% { transform: rotate(-30deg); } 35% { transform: rotate(-52deg); }
    45% { transform: rotate(-30deg); } 55% { transform: rotate(-52deg); } 70% { transform: rotate(-10deg); } }
  .sv.m-bounce .sv-body { animation: sv-bounce 1.6s cubic-bezier(.34, 1.2, .64, 1) 1 both; }
  @keyframes sv-bounce { 0% { transform: translateY(34.1px); } 25% { transform: translateY(3.6px); } 42% { transform: translateY(20.5px); } 66% { transform: translateY(.9px); }
    82% { transform: translateY(12.7px); } 100% { transform: translateY(10px); } }
  /* 3.8.1, more moves: a room's seats: each does one small thing now and then, at its own time */
  .sv.m-sread .sv-pupils { animation: sv-read 1.75s ease-in-out var(--sv-on, 8) alternate; }
  .sv.m-snod .sv-body { animation: sv-nod 6s ease-in-out var(--sv-d, 0s) var(--sv-on, 2); }
  .sv.m-sreach .sv-armL, .sv.m-sreach .sv-armR { animation: sv-reach 8s ease-in-out var(--sv-d, 0s) var(--sv-on, 2); }
  .sv.m-sreach .sv-armR { animation-direction: reverse; }
  @keyframes sv-reach { 0%, 70%, 100% { transform: rotate(0); } 78%, 86% { transform: rotate(40deg); } }
  .sv.m-slook .sv-pupils { animation: sv-look 7s ease-in-out var(--sv-d, 0s) var(--sv-on, 2); }
  /* 3.8.2: the closet's things: a propeller turns, steam rises, wings flap, a balloon sways */
  .sv .cl-prop { animation: cl-prop .5s linear var(--sv-on, 24); }
  .sv .cl-steam { animation: cl-steam 2.4s ease-in-out var(--sv-on, 5); }
  .sv .cl-flame { animation: cl-flame .35s ease-in-out var(--sv-on, 36) alternate; }
  .sv .cl-flick { animation: cl-flick 1.1s ease-in-out var(--sv-on, 12) alternate; }
  .sv .cl-bal { animation: cl-bal 3.2s ease-in-out var(--sv-on, 4); }
  .sv .cl-flag { animation: cl-flag 1.6s ease-in-out var(--sv-on, 8); }
  .sv .cl-blink { animation: cl-blink 1.8s steps(1) var(--sv-on, 7); }
  .sv .cl-glow { animation: cl-glow 2.4s ease-in-out var(--sv-on, 5); }
  .sv .cl-wl { animation: cl-wl 1.4s ease-in-out var(--sv-on, 9); }
  .sv .cl-wr { animation: cl-wr 1.4s ease-in-out var(--sv-on, 9); }
  @keyframes cl-prop { 0%, 100% { transform: scaleX(1); } 50% { transform: scaleX(-1); } }
  @keyframes cl-steam { 0% { opacity: 0; transform: translateY(2px); } 40% { opacity: 1; } 100% { opacity: 0; transform: translateY(-4px); } }
  @keyframes cl-flame { from { transform: scaleY(.8); } to { transform: scaleY(1.15); } }
  @keyframes cl-flick { from { transform: scale(.9); opacity: .85; } to { transform: scale(1.08); opacity: 1; } }
  @keyframes cl-bal { 0%, 100% { transform: rotate(-4deg); } 50% { transform: rotate(5deg); } }
  @keyframes cl-flag { 0%, 100% { transform: scaleY(1); } 50% { transform: scaleY(.86); } }
  @keyframes cl-blink { 0%, 60% { opacity: 1; } 61%, 100% { opacity: .35; } }
  @keyframes cl-glow { 0%, 100% { opacity: .3; } 50% { opacity: .6; } }
  @keyframes cl-wl { 0%, 100% { transform: rotate(0); } 50% { transform: rotate(-14deg); } }
  @keyframes cl-wr { 0%, 100% { transform: rotate(0); } 50% { transform: rotate(14deg); } }
  /* drawn again after it played: it rests, and blinks */
  .sv.rest .sv-body, .sv.rest .sv-armR, .sv.rest .sv-armL, .sv.rest .sv-shadow, .sv.rest .sv-clock,
  .sv.rest .sv-card, .sv.rest .sv-gift, .sv.rest .stk, .sv.rest .sv-cheek, .sv.rest .spark,
  .sv.rest .sv-footL, .sv.rest .sv-footR, .sv.rest .cf, .sv.rest .sv-ring { animation: none; }
}
/* at rest, still too: landed, what flew gone (a banner that stays isn't left mid-hop) */
.sv.rest .sv-body, .sv.rest .sv-armR, .sv.rest .sv-armL, .sv.rest .sv-shadow, .sv.rest .sv-clock,
.sv.rest .sv-card, .sv.rest .sv-gift, .sv.rest .stk, .sv.rest .sv-cheek, .sv.rest .spark,
.sv.rest .sv-footL, .sv.rest .sv-footR { transform: none; }
.sv.rest .cf, .sv.rest .spark, .sv.rest .sv-ring { opacity: 0; }
.sv.rest.m-peek .sv-body, .sv.rest.m-knock .sv-body, .sv.rest.m-bounce .sv-body { transform: translateY(10px); }
"""
