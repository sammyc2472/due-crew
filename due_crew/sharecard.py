"""3.8.0: my day, my week, my year and all time as pictures, made in Anki
with Copy picture and Save… (Sam: "make the copy picture do the same thing
for all the other places it is instead of opening the website"). They are
the site's cards (site/public/cards.js: its layouts, look and words), from
my own Anki's reviews. Pure: the numbers, the switches, and each card as a
list of things to draw; ui/share_card_dialog.py paints and copies.

Made here and kept here: the picture goes only where I paste it. One
person's own numbers, no names, no ranks. My Privacy switches are about
what my crew sees on the board; a picture I make by hand starts with the
numbers they keep home switched off, and I can turn them on."""

import datetime
import math

from .mapcard import mix

# cards.js LOOKS and SIZES (the square size is bingo's, not drawn here)
LOOKS = {
    "light": {"bg": "#fbfbf6", "ink": "#1f2a1f", "mut": "#6a7568", "g": "#2e7d32", "g3": "#e3efe3",
              "line": "#e3efe3", "on": "#ffffff"},
    "dark": {"bg": "#141813", "ink": "#eef2ea", "mut": "#9fae9b", "g": "#7cc47f", "g3": "#243223",
             "line": "#2c3a2b", "on": "#122912"},
}
SIZES = {"story": (1080, 1350), "link": (1200, 630)}
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
LOGO = 910 / 76  # the one-line logo's width over its height


def level(pal, lv):
    """A day's square: the Log's heat levels, 28/52/76/100% of the green."""
    return pal["g3"] if lv <= 0 else mix(pal["g"], pal["g3"], (0, 0.28, 0.52, 0.76, 1)[min(4, lv)])


def _day(label):
    return datetime.date.fromisoformat(str(label))


def short(label):
    """A date as the cards say it: "28 Sep"."""
    d = _day(label)
    return f"{d.day} {MONTHS[d.month - 1]}"


def n(v):
    return f"{int(v):,}"


def hm(ms):
    m = int(ms / 60000 + 0.5)
    return f"{m // 60}h {m % 60:02d}m" if m >= 60 else f"{m}m"


def _plural(k, word):
    return f"{n(k)} {word}{'' if k == 1 else 's'}"


def _did(days, label):
    r = days.get(label)
    return bool(r) and bool(r[0] or r[1])


def heat_level(days):
    """A day's shade by minutes (0-4), against my own log's quarters."""
    mins = sorted(t / 60000 for _r, t in days.values() if t > 0)
    cut = [mins[int(q * (len(mins) - 1))] if mins else 0 for q in (0.25, 0.5, 0.75)]
    return lambda m: 0 if not m else 1 if m <= cut[0] else 2 if m <= cut[1] else 3 if m <= cut[2] else 4


# ---- the numbers. days: {label: (reviews, time_ms)}, the days I answered a card ----

def week(days, today, one=False, fresh=None, streak=0, crew=0, sev=False):
    """My week (Monday to today), or today alone (one): seven squares,
    and the numbers over the days so far. fresh: {label: new cards};
    streak: my streak; crew: how many of my crew studied too; sev: Sev
    hops across it (Settings › Sev here; the site always)."""
    t = _day(today)
    mon = t - datetime.timedelta(days=t.weekday())
    lv = heat_level(days)
    cells, sofar = [], []
    for i in range(7):
        lb = (mon + datetime.timedelta(days=i)).isoformat()
        fut = lb > today
        if not fut:
            sofar.append(lb)
        on = not fut and _did(days, lb)
        cells.append({"label": "MTWTFSS"[i], "future": fut, "today": lb == today, "studied": on,
                      "lvl": max(1, lv(days[lb][1] / 60000)) if on else 0})
    span = [today] if one else sofar
    sun = (mon + datetime.timedelta(days=6)).isoformat()
    return {"one": one, "range": f"{WEEKDAYS[t.weekday()]} {short(today)}" if one else f"{short(mon.isoformat())} – {short(sun)}",
            "days": cells, "studied": (1 if cells[t.weekday()]["studied"] else 0) if one else sum(1 for c in cells if c["studied"]),
            "elapsed": len(sofar), "time": sum((days.get(lb) or (0, 0))[1] for lb in span),
            "reviews": sum((days.get(lb) or (0, 0))[0] for lb in span),
            "newCards": sum(int((fresh or {}).get(lb) or 0) for lb in span),
            "streak": int(streak or 0), "crew": int(crew or 0), "sev": bool(sev)}


def year(days, y, today, cheers=None):
    """My year in Anki: the calendar year, Monday-first columns, days
    before my first review dashed; how many days, the hours and reviews,
    the longest streak and the biggest day. cheers: received that year,
    None while unknown."""
    jan1, dec31 = datetime.date(int(y), 1, 1), datetime.date(int(y), 12, 31)
    first = min(days) if days else today
    lv = heat_level(days)
    cells = []
    d = jan1 - datetime.timedelta(days=jan1.weekday())
    end = dec31 + datetime.timedelta(days=6 - dec31.weekday())
    while d <= end:
        lb = d.isoformat()
        cells.append({"out": True} if d < jan1 or d > dec31 else {"pre": True} if lb < first
                     else {"fut": True} if lb > today else {"lvl": max(1, lv(days[lb][1] / 60000)) if _did(days, lb) else 0})
        d += datetime.timedelta(days=1)
    mine = sorted(lb for lb in days if jan1.isoformat() <= lb <= min(dec31.isoformat(), today))
    streak = run = 0
    prev, best = None, None
    for lb in mine:
        if not _did(days, lb):
            run, prev = 0, lb
            continue
        run = run + 1 if prev and run and (_day(prev) + datetime.timedelta(days=1)).isoformat() == lb else 1
        prev = lb
        streak = max(streak, run)
        if not best or days[lb][0] > best["n"]:
            best = {"n": days[lb][0], "day": short(lb)}
    return {"year": int(y), "studied": sum(1 for lb in mine if _did(days, lb)),
            "since": short(first) if first > jan1.isoformat() and first <= dec31.isoformat() else "",
            "cols": len(cells) // 7, "cells": cells, "minutes": sum(days[lb][1] for lb in mine) / 60000,
            "reviews": sum(days[lb][0] for lb in mine), "streak": streak,
            "best": best if best and best["n"] else None, "cheers": cheers}


def alltime(days, today, cheers=None):
    """My Anki, all time: a bar a year (days studied), the reviews, the
    longest streak and the best year; None before my first review."""
    mine = sorted(lb for lb in days if lb <= today and _did(days, lb))
    if not mine:
        return None
    y0, y1 = int(mine[0][:4]), int(today[:4])
    years = [{"year": y, "days": sum(1 for lb in mine if lb.startswith(f"{y}-"))} for y in range(y0, y1 + 1)]
    streak = run = 0
    prev, streak_year = None, None
    for lb in mine:
        run = run + 1 if prev and (_day(prev) + datetime.timedelta(days=1)).isoformat() == lb else 1
        prev = lb
        if run > streak:
            streak, streak_year = run, int(lb[:4])
    best = None
    for r in years:
        if best is None or r["days"] > best["days"]:
            best = r
    first = _day(mine[0])
    return {"since": f"{MONTHS[first.month - 1]} {first.year}", "years": years, "days": len(mine),
            "reviews": sum(days[lb][0] for lb in mine), "minutes": sum(days[lb][1] for lb in mine) / 60000,
            "streak": streak, "streakYear": streak_year, "bestYear": best if len(years) > 1 else None,
            "cheers": cheers}


def year_options(days, today):
    """The picker: the years I studied in, this one always, newest first,
    then All time. [(key, label)]"""
    ys = {lb[:4] for lb in days if lb <= today and _did(days, lb)} | {today[:4]}
    return [(y, y) for y in sorted(ys, reverse=True)] + [("all", "All time")]


def privacy(cfg):
    """{switch: on} for my day and week: what my Privacy switches let out
    (Just show up lets none). A picture is mine to make, so these are
    where the switches start, not a lock."""
    if cfg.get("show_up"):
        return {"time": False, "reviews": False, "streak": False}
    return {"time": bool(cfg.get("share_time", True)), "reviews": bool(cfg.get("share_reviews", True)),
            "streak": bool(cfg.get("share_streak", True))}


def switches(kind, d, priv=None, cheers_say=""):
    """[(key, label, note, on, enabled)]: a switch for each number on the
    card. note: why it starts off or can't be on. cheers_say: what the
    cheers switch says while the count isn't here ("counting…")."""
    priv = priv or {}
    home = "off in Privacy"
    if kind in ("week", "today"):
        none = "none yet today" if kind == "today" else "none yet this week"
        return [("time", "Time studied", "" if priv.get("time", True) else home, priv.get("time", True), True),
                ("reviews", "Reviews and new cards", "" if priv.get("reviews", True) else home, priv.get("reviews", True), True),
                ("streak", "Streak", "none yet" if not d.get("streak") else "" if priv.get("streak", True) else home,
                 bool(d.get("streak")) and priv.get("streak", True), bool(d.get("streak"))),
                ("crew", "How many crew studied too", "" if d.get("crew") else none, bool(d.get("crew")), bool(d.get("crew")))]
    cheers = d.get("cheers")
    say = cheers_say if cheers is None else "" if cheers else "none yet"
    best = "Biggest day" if kind == "year" else "Best year"
    has_best = bool(d.get("best") if kind == "year" else d.get("bestYear"))
    return [("time", "Hours studied", "", True, True), ("reviews", "Reviews", "", True, True),
            ("streak", "Longest streak", "", True, True),
            ("best", best, "" if has_best else ("none yet" if kind == "year" else "one year so far"), has_best, has_best),
            ("cheers", "Cheers from my crew", say, bool(cheers), bool(cheers))]


# ---- the cards, as things to draw ----

class _Ops:
    """What a card draws, in order: ("logo", x, y, h); ("text", s, x, y,
    px, color, weight, align, track), y the baseline; ("rect", x, y, w,
    h, r, color); ("ring", x, y, w, h, r, color, width, dashed); ("dot",
    x, y, r, color), a filled circle; ("sev", pose, x, y, size, color),
    sev.still(pose, color) in that square."""

    def __init__(self, measure, pal):
        self.ops, self.measure, self.pal = [], measure, pal

    def text(self, s, x, y, px, color, weight=400, align="left", track=0.0):
        self.ops.append(("text", s, x, y, px, color, weight, align, track))

    def eyebrow(self, s, x, y, px):
        self.text(s.upper(), x, y, px, self.pal["mut"], 700, track=px * 0.12)

    def rect(self, x, y, w, h, r, color):
        self.ops.append(("rect", x, y, w, h, r, color))

    def ring(self, x, y, w, h, r, color, width, dashed=False):
        self.ops.append(("ring", x, y, w, h, r, color, width, dashed))

    def logo(self, x, y, h):
        self.ops.append(("logo", x, y, h))

    def dot(self, x, y, r, color):
        self.ops.append(("dot", x, y, r, color))

    def sev(self, pose, x, y, size, color):
        self.ops.append(("sev", pose, x, y, size, color))

    def fit(self, s, width, px, least, weight=400):
        """(s, px): the biggest size from px down to least that fits, else
        least, cut short with an ellipsis."""
        z = px
        while z > least:
            if self.measure(s, z, weight) <= width:
                return s, z
            z -= 2
        t = s
        while len(t) > 1 and self.measure(t + "…", least, weight) > width:
            t = t[:-1]
        return (s if t == s else t.rstrip() + "…"), least


def draw(kind, size, d, on, look, measure):
    """(W, H, ops): the card. kind: today, week, year or alltime; size:
    story or link (year is story only); on: {switch: bool}; measure(s,
    px, weight): a line's width in pixels."""
    if kind == "year":
        size = "story"
    W, H = SIZES[size]
    o = _Ops(measure, LOOKS[look])
    {"today": _week, "week": _week, "year": _year, "alltime": _alltime}[kind](o, W, H, size, d, on)
    return W, H, o.ops


def _day_cell(o, x, y, s, c, r, ring):
    pal = o.pal
    if c["future"]:
        o.ring(x + 1.5, y + 1.5, s - 3, s - 3, r, pal["g3"], 3)
        return
    o.rect(x, y, s, s, r, level(pal, c["lvl"]))
    if c["today"]:
        o.ring(x - ring, y - ring, s + 2 * ring, s + 2 * ring, r + ring, pal["ink"], ring * 0.75)


# 3.8.1, the week card's Sev (Sam's pick, "Sev hops across the week"): it
# lands on the days I studied and hops over the rest. A picture is still,
# so the hops are its trail, a dotted arc from each day it landed on to
# the next, and Sev stands on the last. Sizes are over a square's side.
SEV_SIZE = 1.8  # Sev's drawing: its body about a square
SEV_FEET = 72.5 / 80  # where its feet end in its drawing (sev.py)
HOP = 0.45  # a hop's height, times the root of the days it spans: a day off, a longer one
DOT, STEP = 0.035, 0.16  # the trail: a dot's radius, and the way between two dots
ROOM = 100  # on a story, the squares and what's under them move down this much for Sev


def landings(d):
    """The days Sev lands on (indexes into d["days"]): the days studied so
    far, or today alone on today's card; none with Sev off."""
    if not d.get("sev"):
        return []
    return [i for i, c in enumerate(d["days"]) if c["studied"] and not c["future"] and (c["today"] or not d["one"])]


def hops(d, x0, top, s, gap, ring):
    """Sev on the row of squares (from x0, top; side s, gap apart; today's
    ringed `ring` out): {"arcs": [(day, next day)], "dots": [(x, y)],
    "r": a dot's radius, "sev": (x, y, size) or None}. Each arc runs from
    the top of a square it landed on to the next one's, and Sev stands on
    the last. cards.js hops() is its twin."""
    land = landings(d)
    out = {"arcs": [], "dots": [], "r": s * DOT, "sev": None}
    if not land:
        return out

    def foot(i):  # where it lands: the square's top, or the top of today's ring
        return x0 + i * (s + gap) + s / 2, top - (ring * 1.375 if d["days"][i]["today"] else 0)
    for a, b in zip(land, land[1:]):
        out["arcs"].append((a, b))
        out["dots"] += _trail(foot(a), foot(b), s * HOP * math.sqrt(b - a), s * STEP)
    x, y = foot(land[-1])
    z = s * SEV_SIZE
    out["sev"] = (x - z / 2, y - z * SEV_FEET, z)
    return out


def _trail(a, b, h, step):
    """Dots along a hop from a to b, its top h above them, about step
    apart along the curve; none at either end (a square is there)."""
    N = 48
    pts = []
    for k in range(N + 1):
        t = k / N
        pts.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t - 4 * h * t * (1 - t)))
    run = [0.0]
    for k in range(N):
        dx, dy = pts[k + 1][0] - pts[k][0], pts[k + 1][1] - pts[k][1]
        run.append(run[k] + math.sqrt(dx * dx + dy * dy))
    n = max(2, int(run[N] / step + 0.5))
    dots, k = [], 0
    for i in range(1, n):
        want = run[N] * i / n
        while run[k + 1] < want:
            k += 1
        f = (want - run[k]) / (run[k + 1] - run[k])
        dots.append((pts[k][0] + (pts[k + 1][0] - pts[k][0]) * f, pts[k][1] + (pts[k + 1][1] - pts[k][1]) * f))
    return dots


def _hop(o, hp):
    if not hp["sev"]:
        return
    for x, y in hp["dots"]:
        o.dot(x, y, hp["r"], o.pal["g"])
    o.sev("hop", *hp["sev"], o.pal["g"])


def _week(o, W, H, size, d, on):
    pal = o.pal
    time = hm(d["time"]) if on.get("time") and d.get("time") else None
    rev = d["reviews"] if on.get("reviews") and d.get("reviews") is not None else None
    big = time or (f"{n(rev)} reviews" if rev is not None
                   else ("Studied" if d["studied"] else "Not yet") if d["one"] else _plural(d["studied"], "day"))
    so_far = " so far" if d["elapsed"] < 7 else ""
    days = "today" if d["one"] else f"{d['studied']} of {_plural(d['elapsed'], 'day')}{so_far}"
    crew = f"with {d['crew']} crew {'today' if d['one'] else 'this week'}" if on.get("crew") and d.get("crew") else ""
    brow = f"Today · {d['range']}" if d["one"] else f"My week · {d['range']}"
    streak = d["streak"] if on.get("streak") and d.get("streak") else None
    if size == "link":
        P = 64
        o.logo(P, P, 34)
        o.eyebrow(brow, P, 214, 24)
        s, z = o.fit(big, 720 - 40 - P, 104, 60, 700)
        o.text(s, P, 330, z, pal["ink"], 700)
        bits = [f"{n(rev)} reviews" if time and rev is not None else None,
                f"{n(d['newCards'])} new" if on.get("reviews") and d.get("newCards") else None,
                None if d["one"] else days, f"🔥 {streak}" if streak else None]
        o.text(o.fit(" · ".join(b for b in bits if b), 600, 30, 24)[0], P, 392, 30, pal["mut"])
        x0 = 720
        w, gap = W - P - x0, 12
        s = (w - 6 * gap) / 7
        for i, c in enumerate(d["days"]):
            _day_cell(o, x0 + i * (s + gap), 230, s, c, 12, 4)
            o.text(c["label"], x0 + i * (s + gap) + s / 2, 230 + s + 38, 22, pal["mut"], 700, "center")
        _hop(o, hops(d, x0, 230, s, gap, 4))  # the room above the squares is free
        o.text(" · ".join(b for b in (crew, "duecrew.com") if b), P, H - P, 26, pal["mut"])
        return
    P = 78
    o.logo(P, P, 40)
    o.eyebrow(brow, P, 236, 30)
    w = W - 2 * P
    s, z = o.fit(big, w, 150, 90, 700)
    o.text(s, P, 396, z, pal["ink"], 700)
    sub = ("studied today" if d["studied"] or time or rev else "nothing yet today") if d["one"] else f"studied, {days}"
    o.text(sub, P, 462, 38, pal["mut"])
    gap = 20
    s = (w - 6 * gap) / 7
    dy = ROOM if landings(d) else 0
    for i, c in enumerate(d["days"]):
        _day_cell(o, P + i * (s + gap), 560 + dy, s, c, 26, 8)
        o.text(c["label"], P + i * (s + gap) + s / 2, 560 + dy + s + 54, 30, pal["mut"], 700, "center")
    _hop(o, hops(d, P, 560 + dy, s, gap, 8))
    o.rect(P, 812 + dy, w, 3, 0, pal["line"])
    stats = [(n(rev), "reviews") if rev is not None and time else None,
             (n(d["newCards"]), "new cards") if on.get("reviews") and d.get("newCards") is not None else None,
             (f"🔥 {streak}", "day streak") if streak else None]
    for i, (v, lb) in enumerate(x for x in stats if x):
        x = P + i * w / 3
        o.text(v, x, 912 + dy, 64, pal["ink"], 700)
        o.text(lb, x, 962 + dy, 32, pal["mut"])
    if crew:
        o.text(crew, P, H - P, 34, pal["mut"])
    o.text("duecrew.com", W - P, H - P, 34, pal["mut"], align="right")


def _cheered(o, d, on, x, y, px=34):
    """Cheers my crew sent me (received only, never sent; my own cards only)."""
    if on.get("cheers") and d.get("cheers"):
        o.text(f"🎉 Cheered on {_plural(d['cheers'], 'time')} by my crew", x, y, px, o.pal["ink"], 600)


def _year(o, W, H, size, d, on):
    pal = o.pal
    P = 72
    o.logo(P, P, 40)
    o.eyebrow(f"My year in Anki · {d['year']}", P, 236, 30)
    o.text(_plural(d["studied"], "day"), P, 380, 132, pal["ink"], 700)
    o.text(f"studied, since {d['since']}" if d["since"] else f"studied in {d['year']}", P, 446, 38, pal["mut"])
    w, cols, gap = W - 2 * P, d["cols"], 4
    s = (w - (cols - 1) * gap) / cols
    for i, c in enumerate(d["cells"]):
        cx, cy = P + (i // 7) * (s + gap), 520 + (i % 7) * (s + gap)
        if c.get("pre"):
            o.ring(cx + 1, cy + 1, s - 2, s - 2, 3, pal["g3"], 2, True)
        elif not c.get("out"):
            o.rect(cx, cy, s, s, 3, mix(pal["g3"], pal["bg"], 0.5) if c.get("fut") else level(pal, c["lvl"]))
    top = 520 + 7 * (s + gap) + 40
    o.rect(P, top, w, 3, 0, pal["line"])
    stats = [(f"{n(round(d['minutes'] / 60))}h", "studied") if on.get("time") and d.get("minutes") else None,
             (n(d["reviews"]), "reviews") if on.get("reviews") and d.get("reviews") is not None else None,
             (_plural(d["streak"], "day"), "longest streak") if on.get("streak") and d.get("streak") else None,
             (n(d["best"]["n"]), f"biggest day · {d['best']['day']}") if on.get("best") and d.get("best") else None]
    for i, (v, lb) in enumerate(x for x in stats if x):
        x, y = P + (i % 2) * (w / 2), top + 110 + (i // 2) * 150
        o.text(v, x, y, 64, pal["ink"], 700)
        o.text(lb, x, y + 48, 32, pal["mut"])
    _cheered(o, d, on, P, H - P - 64)
    o.text("duecrew.com", P, H - P, 34, pal["mut"])


def _bars(o, x, y, w, h, years, label):
    pal = o.pal
    most = max([1] + [r["days"] for r in years])
    best = None
    for r in years:
        if best is None or r["days"] > best["days"]:
            best = r
    gap = min(24, w / len(years) / 4)
    bw = min(140, (w - gap * (len(years) - 1)) / len(years))
    for i, r in enumerate(years):
        bh = max(6 if r["days"] else 0, round(r["days"] / most * h))
        bx = x + i * (bw + gap)
        if bh:
            o.rect(bx, y + h - bh, bw, bh, min(10, bw / 4), pal["g"] if r is best else mix(pal["g"], pal["g3"], 0.5))
        o.text(f"’{str(r['year'])[2:]}", bx + bw / 2, y + h + label, label * 0.75, pal["mut"], 700, "center")


def _alltime(o, W, H, size, d, on):
    pal = o.pal
    brow = f"My Anki, all time · since {d['since']}"
    big = n(d["reviews"])
    stats = [(_plural(d["days"], "day"), "studied"),
             (f"{n(round(d['minutes'] / 60))}h", "in Anki") if on.get("time") and d.get("minutes") else None,
             (_plural(d["streak"], "day"), "longest streak" + (f" · {d['streakYear']}" if d.get("streakYear") else ""))
             if on.get("streak") and d.get("streak") else None,
             (str(d["bestYear"]["year"]), f"best year · {n(d['bestYear']['days'])} days")
             if on.get("best") and d.get("bestYear") else None]
    stats = [x for x in stats if x]
    if size == "link":
        P = 64
        o.logo(P, P, 34)
        o.eyebrow(brow, P, 200, 22)
        o.text(big, P, 316, 104, pal["ink"], 700)
        line = " · ".join(["reviews"] + [f"{v} {lb}" for v, lb in stats[:2]])
        o.text(o.fit(line, 560, 28, 22)[0], P, 374, 28, pal["mut"])
        _bars(o, 700, 150, W - P - 700, 300, d["years"], 34)
        _cheered(o, d, on, P, H - P - 46, 26)
        o.text("duecrew.com", P, H - P, 26, pal["mut"])
        return
    P = 72
    o.logo(P, P, 40)
    o.eyebrow(brow, P, 236, 30)
    o.text(big, P, 380, 132, pal["ink"], 700)
    o.text("reviews", P, 446, 38, pal["mut"])
    w = W - 2 * P
    _bars(o, P, 510, w, 200, d["years"], 40)
    o.text("days studied, a bar a year", P, 800, 28, pal["mut"])
    top = 836
    o.rect(P, top, w, 3, 0, pal["line"])
    for i, (v, lb) in enumerate(stats):
        x, y = P + (i % 2) * (w / 2), top + 96 + (i // 2) * 136
        o.text(v, x, y, 60, pal["ink"], 700)
        o.text(lb, x, y + 46, 30, pal["mut"])
    _cheered(o, d, on, P, H - P - 64)
    o.text("duecrew.com", W - P, H - P, 34, pal["mut"], align="right")
