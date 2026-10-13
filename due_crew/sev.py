"""Sev, the square from the logo's seven days (3.8.1, the "Sev Design" page:
Block, Sam's picks: no belt, big round eyes, stubby arms, cheeks only when
a cheer lands). Pure: no aqt.

One drawing for every pose, and one motion sheet (CSS). The board draws Sev
from here, and the room's widgets get its markup from here as data, so it's
never drawn twice and there's no JS twin. Every pose draws the same named
parts (sv-body, sv-eyes, sv-pupils, sv-armL/R, sv-card, sv-clock, ...), so
a moment (`m-*`) moves whatever pose it's given.

Still is the frame: each moment's resting markup is the frame that says it
standing still, and the motion lives under prefers-reduced-motion:
no-preference, the computer's Reduce motion. Anki's own is on unless
switched off, so it isn't asked (Sam's call). A moment that happens once (a
hop, a cheer) plays once; drawn again the same day it rests (`rest`).
Transforms and opacity only. Colours come from the page: --sv-a (the
accent), --sv-line, --sv-amb, --sv-mut, with a fallback each.
"""

import math

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
ONCE = frozenset({"peek", "ready", "ring", "again", "hop", "stack", "cheer", "in"})

LABELS = {"idle": "Sev", "nap": "Sev, napping", "peek": "Sev, peeking in", "ready": "Sev: let's go",
          "focus": "Sev, heads down", "ring": "Sev: fifteen's up", "stretch": "Sev, stretching",
          "breathe": "Sev, breathing", "rest": "Sev, resting", "again": "Sev: back to it",
          "hop": "Sev: day done", "stack": "Sev: session done", "cheer": "Sev: a cheer",
          "exam": "Sev: good luck", "away": "Sev, away", "hello": "Sev"}

# an angle per arm, from hanging straight down
_ARMS = {"down": (32, -32), "up": (155, -155), "wave": (32, -150), "hold": (-50, 50), "out": (100, -100),
         "pump": (32, -172), "cross": (-62, 62), "walk": (20, -12)}
_HOLD, _SIDE, _TOP = (40, 56), (67, 58), (40, 27)


def _arms(pose):
    a = _ARMS.get(pose, _ARMS["down"])
    limb = _r(-2.6, -1, 5.2, 12.5, 2.6, ACC)
    html = "".join(f'<g transform="translate({x} 47) rotate({ang})"><g class="sv-arm{side}">{limb}</g></g>'
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
            # breathe with Sev: a square, four counts a side
            back += (f'<rect x="8" y="8" width="64" height="64" rx="12" fill="none" style="stroke:{LINE}" '
                     'stroke-width="1.6" stroke-dasharray="3 3"/>'
                     f'<circle class="sv-boxdot" cx="8" cy="8" r="3.2" style="fill:{ACC}"/>')
            for cls, x, y, anchor, word in (("l1", 40, 4, "middle", "in"), ("l2", 78, 42, "start", "hold"),
                                            ("l3", 40, 80.5, "middle", "out"), ("l4", 2, 42, "end", "hold")):
                back += (f'<text class="lab {cls}" x="{x}" y="{y}" text-anchor="{anchor}" font-size="6.5" '
                         f'font-weight="700" style="fill:{MUT}">{word}</text>')
    return back, front


def svg(pose, moment=None, size=None, rest=False, label=None, cheeks=None, stack=None):
    """Sev in `pose` (POSES), moving as `moment` (its own by default). rest:
    a moment that happens once has played already; it rests (and blinks).
    cheeks: blushing, which only a cheer does (Sam's pick) unless asked.
    stack: squares on its head, one a fifteen (three at most)."""
    p = POSES.get(pose) or POSES["idle"]
    m = moment or MOMENT.get(pose, "idle")
    back_arms, front_arms = _arms(p["arms"])
    blush = p.get("cheeks") if cheeks is None else cheeks
    body = (_r(28.5, 63, 9, 9.5, 3, ACC, ' class="sv-footL"') + _r(42.5, 63, 9, 9.5, 3, ACC, ' class="sv-footR"')
            + _r(20, 27, 40, 39, 12.5, ACC) + _r(25, 31, 11, 5, 2.5, "#fff", ' opacity=".22"')
            + _eyes(p["eyes"]) + _mouth(p["mouth"]) + (_cheeks() if blush else ""))
    fx_back, fx_front = _fx(p.get("fx") or (), max(1, min(3, int(stack or 3))))
    dims = f' width="{int(size)}" height="{int(size)}"' if size else ""
    cls = f"sv m-{m}" + (" rest" if rest and m in ONCE else "")
    return (f'<svg class="{cls}"{dims} viewBox="0 0 80 80" role="img" aria-label="{label or LABELS.get(pose, "Sev")}">'
            f'<ellipse class="sv-shadow" cx="40" cy="74.5" rx="16" ry="2.6" style="fill:{LINE}"/>{fx_back}'
            f'<g class="sv-body">{back_arms}{body}{front_arms}{_held(p.get("prop"))}</g>{fx_front}</svg>')


def mood(away=False, in_session=False, cheered=False, exam_eve=False, day_done=False, studied=False):
    """Sev beside the logo: how my day is going, never how much I did.
    Away first (off on a trip), then a session under way, a cheer that just
    landed, the night before an exam, the day done (a hop), studying (a
    blink), and before all that, a nap. Never cross: a gap gets a nap."""
    if away:
        return "away"
    if in_session:
        return "focus"
    if cheered:
        return "cheer"
    if exam_eve:
        return "exam"
    if day_done:
        return "hop"
    return "idle" if studied else "nap"


# the motion sheet. Outside the media query: the still frame of each moment.
# Inside it: the motion, which ends where a moment rests.
CSS = r"""
svg.sv { overflow: visible; display: block; flex: none; }
.sv .sv-body, .sv .sv-shadow, .sv .sv-eyes, .sv .sv-pupils, .sv .sv-armL, .sv .sv-armR, .sv .sv-card, .sv .sv-clock,
.sv .sv-case, .sv .sv-star, .sv .sv-gift, .sv .sv-z, .sv .cf, .sv .stk, .sv .sv-ring, .sv .spark, .sv .sv-cheek,
.sv .sv-footL, .sv .sv-footR, .sv .sv-boxdot { transform-box: fill-box; }
.sv .sv-body { transform-origin: 50% 100%; }
.sv .sv-shadow, .sv .sv-eyes, .sv .sv-card, .sv .sv-clock, .sv .sv-star, .sv .sv-gift, .sv .sv-z, .sv .cf, .sv .stk,
.sv .spark, .sv .sv-ring { transform-origin: 50% 50%; }
.sv .sv-armL, .sv .sv-armR { transform-origin: 50% 8%; }
.sv .sv-case { transform-origin: 50% 0%; }
.sv .sv-cheek { opacity: .6; }
.sv .sv-z.z2 { transform: translate(6px, -8px); }
.sv .sv-z.z3 { transform: translate(12px, -16px); }
.sv .cf { transform: translate(var(--dx), var(--dy)) rotate(var(--r)); }
.sv .lab { opacity: .35; }
.sv .lab.l1 { opacity: 1; }
.sv.m-peek .sv-body { transform: translateY(22%); }
.sv.m-peek .sv-shadow, .sv.m-in .sv-shadow { display: none; }
.sv.m-hop .sv-body { transform: translateY(-12px); }
@media (prefers-reduced-motion: no-preference) {
  .sv .sv-eyes { animation: sv-blink 4.6s infinite; }
  @keyframes sv-blink { 0%, 90%, 100% { transform: scaleY(1); } 93% { transform: scaleY(.12); } 96% { transform: scaleY(1); } }
  /* napping: nothing studied yet today */
  .sv.m-nap .sv-body { animation: sv-breathe 3.2s ease-in-out infinite; }
  .sv.m-nap .sv-eyes { animation: none; }
  .sv.m-nap .sv-z { animation: sv-zf 3.6s ease-out infinite; }
  .sv.m-nap .sv-z.z2 { animation-delay: 1.2s; }
  .sv.m-nap .sv-z.z3 { animation-delay: 2.4s; }
  @keyframes sv-breathe { 0%, 100% { transform: scale(1, 1); } 50% { transform: scale(1.025, 1.05); } }
  @keyframes sv-zf { 0% { opacity: 0; transform: translate(0, 0) scale(.6); } 20% { opacity: 1; }
    100% { opacity: 0; transform: translate(9px, -18px) scale(1.15); } }
  /* peeking in, from behind the nudge: up once, a wave */
  .sv.m-peek .sv-body { animation: sv-peek .7s cubic-bezier(.34, 1.56, .64, 1) 1 both; }
  .sv.m-peek .sv-armR { animation: sv-wave 1.6s ease-in-out .5s 1 both; }
  @keyframes sv-peek { from { transform: translateY(75%); } to { transform: translateY(22%); } }
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
  .sv.m-focus .sv-pupils { animation: sv-read 1.75s ease-in-out infinite alternate; }
  .sv.m-focus .sv-card { animation: sv-flip 7s ease-in-out infinite; }
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
  /* the break: a stretch, or breathe with Sev (a square, four counts a side) */
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
  .sv.m-exam .sv-star { animation: sv-twinkle 2.6s ease-in-out infinite; }
  .sv.m-exam .sv-body { animation: sv-bob 2.6s ease-in-out infinite; }
  .sv.m-exam .spark { animation: sv-sparkle 2.6s ease-in-out infinite; }
  .sv.m-exam .spark.s2 { animation-delay: 1.3s; }
  @keyframes sv-twinkle { 0%, 100% { transform: rotate(0) scale(1); } 50% { transform: rotate(18deg) scale(1.24); } }
  @keyframes sv-sparkle { 0%, 100% { opacity: .2; transform: scale(.6); } 50% { opacity: 1; transform: scale(1.1); } }
  /* away: off on a trip */
  .sv.m-away .sv-body { animation: sv-bob 1.2s ease-in-out infinite; }
  .sv.m-away .sv-footL { animation: sv-step 1.2s ease-in-out infinite; }
  .sv.m-away .sv-footR { animation: sv-step 1.2s ease-in-out -.6s infinite; }
  .sv.m-away .sv-case { animation: sv-sway 1.2s ease-in-out infinite; }
  @keyframes sv-bob { 0%, 50%, 100% { transform: none; } 25%, 75% { transform: translateY(-2.5px); } }
  @keyframes sv-step { 0%, 50%, 100% { transform: none; } 25% { transform: translateY(-3px); } }
  @keyframes sv-sway { 0%, 100% { transform: rotate(-5deg); } 50% { transform: rotate(5deg); } }
  /* hello: Sev switched on in Settings pops in and waves */
  .sv.m-in .sv-body { animation: sv-in .5s cubic-bezier(.34, 1.56, .64, 1) 1 both; }
  .sv.m-in .sv-armR { animation: sv-wave 1.6s ease-in-out .3s 1 both; }
  @keyframes sv-in { 0% { transform: scale(0); } 70% { transform: scale(1.14); } 100% { transform: scale(1); } }
  /* drawn again after it played: it rests, and blinks */
  .sv.rest .sv-body, .sv.rest .sv-armR, .sv.rest .sv-armL, .sv.rest .sv-shadow, .sv.rest .sv-clock,
  .sv.rest .sv-card, .sv.rest .sv-gift, .sv.rest .stk, .sv.rest .sv-cheek { animation: none; transform: none; }
  .sv.rest .cf, .sv.rest .spark, .sv.rest .sv-ring { animation: none; opacity: 0; }
  .sv.rest.m-peek .sv-body { transform: translateY(22%); }
}
"""
