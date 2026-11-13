"""3.9.10, the scrapbook (Sam, 12 Nov: "a combo wrapped and home for
polaroids / notes, etc. that are ephemeral at the moment or deleted
permanently when taken away from the screen"): what my crew sent me and
what I did, by month, kept on this computer and never sent.

A keepsake is one of five kinds (k):
  pz     a polaroid off the fridge: taken down, or pushed out by a newer one
  luck   a good-luck line, once its card has shown on my exam morning
  tip    a tip's words and the deck part it was for (never the card), once I said it helped
  cheer  a cheer that came with words (one with none is only counted, by the tallies)
  mine   something I did: a plan finished, a bingo line, something Pip earned

Pure: the shapes, the cleaning, months and years, and each month's line.
The file and the hooks are scrap_flow's; the page board.scrapbook_html."""

import hashlib

from .backend.shapes import clean_doodle, clean_emoji, clean_note

KINDS = ("pz", "luck", "tip", "cheer", "mine")
KEEP = 3000          # keepsakes kept in all (a polaroid is a few hundred bytes; the oldest go first)
HEAD_MAX, SUB_MAX, PART_MAX = 80, 160, 60
POSES = ("cheer", "hop", "hello")
WHATS = ("plan", "bingo", "pip", "hook")  # what a moment of mine was (the year page counts plans and what Pip earned)
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December")


def _text(v, n):
    return " ".join(str(v or "").split())[:n]


def _day(v):
    """The day of an ISO stamp or day ("2026-11-09T…" or "2026-11-09"), or ""."""
    s = str(v or "")[:10]
    ok = len(s) == 10 and s[4] == "-" and s[7] == "-" and (s[:4] + s[5:7] + s[8:]).isdigit()
    return s if ok and "01" <= s[5:7] <= "12" and "01" <= s[8:] <= "31" else ""


def key(item):
    """A keepsake's own short name: its kind, whose it is, when, and its words."""
    said = item.get("n") or item.get("head") or (item.get("d") or {}).get("t") or ""
    return hashlib.sha1(f'{item.get("k")}|{item.get("from")}|{item.get("at")}|{said}'.encode()).hexdigest()[:12]


def clean_one(x):
    """One keepsake as this writes it, or None."""
    if not isinstance(x, dict) or x.get("k") not in KINDS or not _day(x.get("at")):
        return None
    k = x["k"]
    out = {"k": k, "at": str(x["at"])[:40]}
    if k == "mine":
        out["head"], out["sub"] = _text(x.get("head"), HEAD_MAX), _text(x.get("sub"), SUB_MAX)
        out["pose"] = x.get("pose") if x.get("pose") in POSES else "cheer"
        out["w"] = x.get("w") if x.get("w") in WHATS else ""
        return out if out["head"] else None
    out["from"], out["name"] = str(x.get("from") or "")[:64], _text(x.get("name") or "?", 60)
    out["n"] = clean_note(x.get("n"))
    if k == "pz":
        d = clean_doodle(x.get("d"))
        if not d:
            return None
        out["d"], out["a"] = d, str(x.get("a") or "")[:16]
    elif k == "tip":
        out["part"] = _text(x.get("part"), PART_MAX)
    elif k == "cheer":
        out["e"] = clean_emoji(x.get("e"))
    return out if (k == "pz" or out["n"]) else None


def clean(v):
    """The file's list as this writes it: each keepsake once, oldest first, KEEP at most."""
    out, have = [], set()
    for x in v if isinstance(v, list) else []:
        item = clean_one(x)
        if item and key(item) not in have:
            have.add(key(item))
            out.append(item)
    out.sort(key=lambda i: i["at"])
    return out[-KEEP:]


def add(items, item):
    """`items` with one more (once)."""
    return clean(list(items or []) + [item])


def drop(items, k):
    return [x for x in clean(items) if key(x) != k]


def from_fridge(item):
    """A polaroid off the fridge (fridge.clean's shape) as a keepsake."""
    return {"k": "pz", "from": item.get("from"), "name": item.get("name"), "at": item.get("at"),
            "a": item.get("a"), "n": item.get("n"), "d": item.get("d")}


def to_fridge(item):
    """A kept polaroid as the fridge holds one (Pin up)."""
    return {"from": item.get("from"), "name": item.get("name"), "at": item.get("at"),
            "a": item.get("a"), "n": item.get("n"), "d": item.get("d")}


def years(items, this_year):
    """The years it has pages for, newest first: this one always."""
    ys = {int(this_year)} | {int(x["at"][:4]) for x in clean(items)}
    return sorted(ys, reverse=True)


def months(items, year):
    """[(month 1-12, [its keepsakes, newest first])] for a year, newest month first."""
    by = {}
    for x in clean(items):
        if x["at"][:4] == str(int(year)):
            by.setdefault(int(x["at"][5:7]), []).append(x)
    return [(m, sorted(by[m], key=lambda i: i["at"], reverse=True)) for m in sorted(by, reverse=True)]


def counts(items, year=None):
    """How many of each kind (in a year, or in all)."""
    out = {k: 0 for k in KINDS}
    for x in clean(items):
        if year is None or x["at"][:4] == str(int(year)):
            out[x["k"]] += 1
    return out


def _n(v):
    return f"{int(v):,}"


def month_line(mine, days):
    """A month in one line, as its page opens: (before, the part in the
    accent, after). What I did leads (the newest), else the days I showed up."""
    if mine:
        head = mine[0]["head"]
        more = len(mine) - 1
        return ("", head, f", and {more} more." if more else ".")
    if days:
        return ("", f"{_n(days)} day{'s' if days != 1 else ''}", " you showed up.")
    return ("", "", "")


def month_sub(days, reviews, cheers):
    """The month's numbers under its line: study days, reviews, cheers (each only when there is one)."""
    bits = []
    if days:
        bits.append(f"{_n(days)} study day{'s' if days != 1 else ''}")
    if reviews:
        bits.append(f"{_n(reviews)} review{'s' if reviews != 1 else ''}")
    if cheers:
        bits.append(f"cheered {_n(cheers)} time{'s' if cheers != 1 else ''}")
    return " · ".join(bits)


def year_line(year, days, reviews, so_far):
    """The year page's line: (before, the part in the accent, after)."""
    if not days:
        return (f"{int(year)}{' so far' if so_far else ''}: nothing studied yet.", "", "")
    return (f"{_n(days)} day{'s' if days != 1 else ''} you showed up, and ", f"{_n(reviews)} review{'s' if reviews != 1 else ''}", ".")


def year_stats(run, plans, c, cheers, earned):
    """The year page's small numbers: [(number, words)], each only when there is one."""
    out = []
    for n, one, many in ((run, "day, your longest run", "days, your longest run"),
                         (plans, "plan finished", "plans finished"),
                         (c.get("pz", 0), "drawing or sign", "drawings and signs"),
                         (c.get("luck", 0), "good-luck card", "good-luck cards"),
                         (c.get("tip", 0), "tip that helped", "tips that helped"),
                         (cheers, "cheer", "cheers"),
                         (earned, "thing Pip earned", "things Pip earned")):
        if n:
            out.append((_n(n), one if int(n) == 1 else many))
    return out
