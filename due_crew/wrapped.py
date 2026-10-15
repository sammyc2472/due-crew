"""3.9.0: your Wrapped (Sam's pick, the fun round's third round: "Build").
Pure: no aqt.

Your own year as a short story, made on this computer from Anki's own
review history and what Due Crew counts there (closet_flow's year counts,
the closet, the Beast). Nothing is sent, and only you see it unless you
share the picture at its end. Only the slides your year can fill are made
(SLIDES says when each is), and every line is kind: no missed days, no
"fewer than", no comparing, nobody else's numbers. The words are checked
(SAD): a test reads every line of every slide for three made-up years.

A slide is {kind, kicker, lead, big, line, small, tag, pose, ...}: plain
text (lead comes before the big number, line after it);
board.wrapped_html escapes it and draws it, Pip in your look. Days are
Anki days (after your rollover hour), as everywhere.
"""

import datetime as _dt

MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December")
NUM = ("no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve")
# never said, anywhere in it (Sam: kind, always); a test reads every slide
SAD = ("missed", "only", "fewer", "down", "worst", "lost", "fail", "behind", "less", "lazy", "skipped", "broke")
# when Due Crew began counting these on this computer: a year before says "since"
SINCE = {"fifteens": _dt.date(2026, 10, 12), "counts": _dt.date(2026, 10, 15)}
BANNER = ((12, 1), (1, 15))  # the board's line for it: 1 December to 15 January
OWL, BIRD = (21, 22, 23, 0, 1, 2, 3), (4, 5, 6, 7, 8)  # after 9 pm (into the small hours); before 9 am
TOD_DAYS = 30  # a night owl or an early bird needs this many days, so it isn't a guess
TURNED_LAPSES, TURNED_IVL = 8, 21  # a leech turned around: lapsed 8 times, now 3 weeks or more between
FRONT_MAX = 140

# each slide's ground (a story's, light text on it), and Pip's pose there
BG = {"cover": "#12301a", "days": "#0f2747", "run": "#3a2507", "back": "#0b2e2b", "time": "#14123a",
      "cards": "#3a1222", "turned": "#2a1d08", "fifteens": "#0b2e2b", "things": "#241640",
      "crew": "#12301a", "beasts": "#2a1240", "picture": "#f4f4ef"}
POSE = {"cover": "hop", "run": "hop", "back": "hello", "cards": "focus", "fifteens": "focus",
        "crew": "cheer", "picture": "hop"}

# when each slide is made (a test checks the code says the same)
SLIDES = (
    ("cover", "Always"),
    ("days", "Always; the steadiest month with three months or more"),
    ("run", "A run of 3 days or more"),
    ("back", "A week or more away, then back; four weeks or more gets the big one"),
    ("time", "30 days or more, and half the reviews after 9 pm or before 9 am"),
    ("cards", "Always; leeches turned around when there are some"),
    ("turned", "A card that lapsed 8 times or more now goes 3 weeks or more between (shown here only)"),
    ("fifteens", "One Fifteen or more"),
    ("things", "Something in Pip's closet"),
    ("crew", "A crew, and a number above 0"),
    ("beasts", "A beast beaten"),
    ("picture", "Always"),
)


def _date(v):
    if isinstance(v, _dt.date):
        return v
    try:
        return _dt.date.fromisoformat(str(v))
    except ValueError:
        return None


def n(v):
    return f"{int(round(v)):,}"


def plural(k, word, words=None):
    return f"{n(k)} {word if k == 1 else (words or word + 's')}"


def day_words(d):
    return f"{d.day} {MONTHS[d.month - 1]}"


def hour_words(h):
    h = int(h) % 24
    return "midnight" if h == 0 else "noon" if h == 12 else f"{h % 12} {'am' if h < 12 else 'pm'}"


def spell(k):
    return NUM[k] if 0 <= k < len(NUM) else n(k)


def default_year(today):
    """The year Wrapped is about: last year's in its first fortnight, else this one's."""
    t = _date(today)
    return t.year - 1 if (t.month, t.day) <= BANNER[1] else t.year


def banner_year(today):
    """The year the board's line is for, 1 December to 15 January; None the rest of the year."""
    t = _date(today)
    if t is None:
        return None
    if (t.month, t.day) >= BANNER[0]:
        return t.year
    if (t.month, t.day) <= BANNER[1]:
        return t.year - 1
    return None


# ---- the year's facts ----

def facts(year, today, days, hours=None, first_ever=None):
    """What a year of reviews says. days: {ISO day: (reviews, new cards met,
    ms)} (other years' are ignored); hours: {hour 0-23: reviews} for the
    year; first_ever: the first day of any review at all."""
    y0, y1, t = _date(f"{int(year)}-01-01"), _date(f"{int(year)}-12-31"), _date(today)
    end = min(t, y1)
    rows = {d: v for d, v in ((_date(k), v) for k, v in (days or {}).items())
            if d and y0 <= d <= end and v and int(v[0] or 0) > 0}
    studied = sorted(rows)
    first = _date(first_ever) if first_ever else None
    out = {"year": int(year), "today": t, "end": end, "so_far": t <= y1, "days": len(studied),
           "reviews": sum(int(v[0]) for v in rows.values()), "new": sum(int(v[1] or 0) for v in rows.values()),
           "ms": sum(int(v[2] or 0) for v in rows.values()), "met": first if first and y0 <= first <= y1 else None,
           "studied": [d.isoformat() for d in studied], "per_day": {d.isoformat(): int(rows[d][0]) for d in studied}, "hours": {int(h): int(c) for h, c in (hours or {}).items() if int(c) > 0}}
    start = max(y0, out["met"] or y0)
    out["elapsed"] = max(0, (end - start).days + 1)
    # the steadiest month: the most days, the earlier on a tie
    months = {}
    for d in studied:
        months[d.month] = months.get(d.month, 0) + 1
    out["months"] = months
    if len(months) >= 3:
        m = max(sorted(months), key=lambda k: months[k])
        last = (_dt.date(int(year) + (m == 12), m % 12 + 1, 1) - _dt.timedelta(days=1))
        out["steadiest"] = (m, months[m], last.day if end >= last else 0)
    # runs: the longest, and the one going now (today not yet studied keeps yesterday's alive)
    best, run, prev, run_from = (0, None, None), 0, None, None
    for d in studied:
        if prev and (d - prev).days == 1:
            run += 1
        else:
            run, run_from = 1, d
        if run > best[0]:
            best = (run, run_from, d)
        prev = d
    out["run"] = best
    alive = studied and (end - studied[-1]).days <= (1 if end == t else 0)
    out["now"] = run if alive else 0
    # coming back: 7 days or more away, then a day studied
    backs = []
    for a, b in zip(studied, studied[1:]):
        gap = (b - a).days - 1
        if gap >= 7:
            after = sum(1 for d in studied if d >= b)
            backs.append({"gap": gap, "day": b, "after": after, "span": (end - b).days + 1})
    out["backs"] = backs
    return out


# ---- the slides ----

def _since(year, key):
    s = SINCE[key]
    return f"Since {MONTHS[s.month - 1]}" if int(year) == s.year else ""


def slides(f, counts=None, have=None, look_names=(), crew=0, card=None, leeches=0, beasts=None, rollover=4,
           thing_names=None):
    """The story, slide by slide, for facts(). counts: closet_flow's year
    counts; have: the closet ({thing: day}); look_names: what Pip has on,
    by name; crew: how many crewmates; card: the card I turned around,
    {front, lapses, ivl} or None; leeches: how many are turned around;
    beasts: [{name, days}] beaten this year; thing_names: {key: name}."""
    y = f["year"]
    counts, have, thing_names = counts or {}, have or {}, thing_names or {}
    out = []
    if not f["days"]:
        return out

    def add(kind, **kw):
        kw.setdefault("pose", POSE.get(kind, "idle"))
        out.append(dict(kind=kind, bg=BG[kind], **kw))

    # cover
    if f["met"]:
        line = f"You and Anki met on {day_words(f['met'])}."
    else:
        line = "Your year so far, as Pip saw it." if f["so_far"] else "Your year, as Pip saw it."
    add("cover", kicker=f"Due Crew · {y}", big=f"Your {y}{' so far' if f['so_far'] else ''}", line=line)
    # days
    share = f["days"] / f["elapsed"] if f["elapsed"] else 0
    st = f.get("steadiest")
    add("days", kicker="Days", lead="Since then you showed up on" if f["met"] else "You showed up on",
        big=plural(f["days"], "day"),
        small=(f"Your steadiest month: {MONTHS[st[0] - 1]}, {st[1]} day{'s' if st[1] != 1 else ''}"
               + (f" of {st[2]}." if st[2] else " so far.")) if st else "",
        note="More days than not, by a long way." if share >= 0.7 else "More days than not." if share > 0.5 else "")
    # the longest run
    run, a, b = f["run"]
    if run >= 3:
        going = f["now"] == run and b >= f["end"] - _dt.timedelta(days=1)
        add("run", kicker="Your longest run", big=plural(run, "day"),
            line=f"since {day_words(a)}, and still going" if going else f"{day_words(a)} to {day_words(b)}",
            small=f"And you’re on {f['now']} right now." if f["now"] >= 3 and not going else "",
            run=[a.isoformat(), b.isoformat()])
    # coming back
    backs = f["backs"]
    big_back = max(backs, key=lambda x: x["gap"]) if backs else None
    if big_back and big_back["gap"] >= 28:
        weeks = big_back["gap"] // 7
        then = (f" Then you showed up on {big_back['after']} of the next {big_back['span']} days."
                if big_back["span"] >= 14 and big_back["after"] * 2 > big_back["span"] else "")
        add("back", kicker="You came back", big=day_words(big_back["day"]),
            line=f"after {spell(weeks)} weeks away.{then}",
            small="That’s a good story." if len(backs) == 1 else f"And {spell(len(backs) - 1)} more comeback{'s' if len(backs) > 2 else ''} besides.")
    elif backs:
        add("back", kicker="Coming back", lead="You came back", big="once" if len(backs) == 1 else f"{spell(len(backs))} times",
            small="after a week or more away. Every one counted." if len(backs) > 1 else "after a week or more away. It counted.")
    # night owl or early bird
    hrs = f["hours"]
    total = sum(hrs.values())
    if total and f["days"] >= TOD_DAYS:
        fav = max(sorted(hrs), key=lambda h: hrs[h])
        owl, bird = sum(hrs.get(h, 0) for h in OWL), sum(hrs.get(h, 0) for h in BIRD)
        if owl * 2 >= total:
            add("time", kicker="When you study", big="Night owl", pose="nap",
                line=f"Most of your reviews come after 9 pm. Your hour: {hour_words(fav)}.",
                small=f"Your Anki day ends at {hour_words(rollover)}, so a late night still counts for the day." if rollover else "")
        elif bird * 2 >= total:
            add("time", kicker="When you study", big="Early bird", pose="stretch",
                line=f"Most of your reviews come before 9 am. Your hour: {hour_words(fav)}.")
    # cards
    hours_studied = f["ms"] / 3_600_000
    grid = [(n(f["reviews"]), "reviews"), (n(f["new"]), "new cards met") if f["new"] else None,
            (n(hours_studied), "hours") if hours_studied >= 1 else (n(f["ms"] / 60000), "minutes") if f["ms"] else None,
            (n(leeches), "leeches turned around") if leeches else None]
    add("cards", kicker="Cards", grid=[g for g in grid if g])
    # the card I turned around: its front, drawn here and never on the picture
    if card and card.get("front"):
        add("turned", kicker="The card you turned around", tag="Stays on this computer, never on the picture",
            front=str(card["front"])[:FRONT_MAX],
            line=f"It slipped {plural(int(card.get('lapses') or 0), 'time')}. Now it goes {n(card.get('ivl') or 0)} days between reviews.")
    # Fifteens
    k = int(counts.get("fifteens") or 0)
    if k:
        hrs15 = counts.get("hours") or {}
        fav = max(sorted(hrs15, key=int), key=lambda h: hrs15[h]) if hrs15 else None
        mins = k * 15
        add("fifteens", kicker="Fifteens", tag=_since(y, "fifteens"), big=n(k),
            line=(f"{n(mins // 60)}{'½' if mins % 60 >= 30 else ''} hour{'' if mins < 90 else 's'}" if mins >= 60 else f"{mins} minutes")
            + ", a quarter of an hour at a time",
            small=f"Your favourite time to start one: just after {hour_words(int(fav))}." if fav is not None else "")
    # Pip's things
    mine = {t: d for t, d in have.items() if str(d)[:4] == str(y)}
    if mine:
        first_year = min(str(d) for d in have.values())[:4] == str(y)
        worn = counts.get("worn") or {}
        most = max(sorted(worn), key=lambda t: worn[t]) if worn else None
        add("things", kicker="Pip’s things" if first_year else "Pip’s year", big=plural(len(mine), "thing"),
            line="earned, none to lose", things=sorted(mine, key=lambda t: (str(mine[t]), t))[:12],
            small=(f"Worn most: the {thing_names.get(most, most).lower()}, {plural(worn[most], 'day')}." if most and worn[most] >= 7
                   else ("On now: " + _list([x.lower() for x in look_names]) + ".") if look_names else ""))
    # together
    if crew:
        bingo = sum(int(v) for v in (counts.get("bingo") or {}).values())
        grid = [(n(counts["cheers_sent"]), "cheers you sent") if counts.get("cheers_sent") else None,
                (n(counts["cheered_by"]), "cheers that reached you") if counts.get("cheered_by") else None,
                (n(counts["rooms"]), "rooms you sat in") if counts.get("rooms") else None,
                (n(counts["crew_days"]), "days the whole crew studied") if counts.get("crew_days") else None,
                (n(bingo), "bingo lines") if bingo else None]
        grid = [g for g in grid if g][:4]
        if grid:
            add("crew", kicker="You and your crew", tag=_since(y, "counts"), grid=grid,
                line="Your own numbers. Nobody else’s are here.")
    # beasts
    if beasts:
        longest = max(beasts, key=lambda b: int(b.get("days") or 0))
        add("beasts", kicker="Beasts", lead="You beat", big=plural(len(beasts), "beast"), beasts=[b.get("k") for b in beasts][:8],
            small=f"{longest.get('name') or 'One'} took {plural(int(longest.get('days') or 0), 'day')}. It’s a pet now.")
    # the picture
    third = (n(f["new"]), "new cards") if f["new"] * 3 >= max(1, f["reviews"]) else (n(f["reviews"]), "reviews")
    add("picture", kicker=f"My {y}{' so far' if f['so_far'] else ''} in Anki",
        grid=[(n(f["days"]), "days"), (n(run), "in a row"), third], small=f"See you in {y + 1}.")
    return out


def _list(xs):
    xs = list(xs)
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1] if xs else ""


def words(slide):
    """Every word a slide says, for the checks (and All on one page)."""
    bits = [slide.get(k) for k in ("kicker", "lead", "big", "line", "small", "note", "tag", "front")]
    bits += [f"{a} {b}" for a, b in slide.get("grid") or ()]
    return " ".join(str(b) for b in bits if b)


def heat(f):
    """The year as squares, Monday-first columns: [(ISO day, level 0-4) or
    None outside the year, or "" after today]. A level is the day's reviews
    against the year's own (quartiles), never anyone else's."""
    y = f["year"]
    jan1, dec31 = _dt.date(y, 1, 1), _dt.date(y, 12, 31)
    per = f.get("per_day") or {}
    xs = sorted(per.values())
    cut = [xs[int(len(xs) * q)] for q in (0.25, 0.5, 0.75)] if xs else []

    def level(v):
        return 0 if not v else 1 + sum(1 for c in cut if v > c)
    d = jan1 - _dt.timedelta(days=jan1.weekday())
    out = []
    while d <= dec31 + _dt.timedelta(days=6 - dec31.weekday()):
        out.append(None if d < jan1 or d > dec31 else "" if d > f["end"] else (d.isoformat(), level(per.get(d.isoformat()))))
        d += _dt.timedelta(days=1)
    return out
