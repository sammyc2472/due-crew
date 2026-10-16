"""3.8.2: Pip's closet (the Fun Round, round two; Sam: "costumes tied to
achievements ... more more more"). Pure: no aqt.

Things Pip earns by showing up, coming back, studying together, finishing a
plan and caring for your own cards. Never for getting cards right (Again
stays honest), never for one big day (the big review counts are a whole Anki
life's), never bought, never taken away. What's earned is the account's
(sev_closet: {thing: the day it came}); what Pip has on is too (sev_look),
and it rides with the accent to mutual friends, whose boards show Pip
wearing it.

A look is one thing in each place on Pip (SLOTS): a hat, something on the
face, on the body, in the hand, on the back. A thing replaces whatever was
in its place, and a thing that reaches into another place too (the winter
earmuffs come with a scarf) takes that place as well, so two things never
sit on top of each other. A costume is the whole look while it's on: one at
a time (a second replaces the first; Sam: "one should replace the other"),
your own things waiting under it to come back when it comes off, and
putting any of them on takes the costume off. wear() is the one way a look
changes; clean() makes any look (an old one, a crewmate's off the server)
follow the same rules.

The facts each thing needs (THINGS' `need`) are worked out in Anki:
from_days and from_hours read the revlog's days and hours (closet_flow asks
once a day), and the rest is the board's and a few tallies this computer
keeps (wrap.json). The drawings are closet_art's; sev.py puts them on Pip.
"""

import datetime as _dt

from .closet_art import ART

SLOTS = ("back", "body", "face", "head", "hand")  # drawn in this order, the hand in the arm
COSTUME = "costume"
LOOK_MAX = len(SLOTS) + 1  # one in each place, and a costume over them

GROUPS = ("Showing up", "Fifteens", "Crew", "Squads", "Plans", "Coming back", "Card care", "Beasts", "Seasons", "Secret")

# (key, place, group, name, rule, (fact, n)[, extra]). Order is the closet's.
# extra: when (a season's dates), tip (what the rule means, in a tooltip),
# also (another place it takes).
_T = (
    ("sprout", "head", "Showing up", "Sprout", "Your first day", ("days", 1)),
    ("beanie", "head", "Showing up", "Beanie", "7 days in a row", ("run", 7)),
    ("cap", "head", "Showing up", "Cap", "14 days in a row", ("run", 14)),
    ("scarf", "body", "Showing up", "Scarf", "30 days in a row", ("run", 30)),
    ("cape", "back", "Showing up", "Cape", "60 days in a row", ("run", 60)),
    ("medal", "body", "Showing up", "Medal", "100 days in a row", ("run", 100)),
    ("laurel", "head", "Showing up", "Laurels", "365 days in a row", ("run", 365)),
    ("glasses", "face", "Showing up", "Round glasses", "100 days studied", ("days", 100)),
    ("nest", "head", "Showing up", "A bird’s nest", "5 mornings before 8", ("mornings", 5)),
    ("nightcap", "head", "Showing up", "Night cap", "10 evenings after 9", ("evenings", 10)),
    ("toque", "head", "Showing up", "Chef’s hat", "Nothing left due, 7 days running", ("clear", 7),
     {"tip": "Days you studied until nothing was left due, seven in a row"}),
    ("stetho", "body", "Showing up", "Stethoscope", "10,000 reviews", ("reviews", 10000)),
    ("mustache", "face", "Showing up", "Moustache", "25,000 reviews", ("reviews", 25000)),
    ("tophat", "head", "Showing up", "Top hat", "50,000 reviews", ("reviews", 50000)),
    ("monocle", "face", "Showing up", "Monocle", "100,000 reviews", ("reviews", 100000)),
    ("cardlei", "body", "Showing up", "A lei of cards", "1,000 cards learned", ("learned", 1000),
     {"tip": "Cards that have made it out of learning"}),
    ("headphones", "head", "Fifteens", "Headphones", "Your first Fifteen", ("fifteens", 1)),
    ("propeller", "head", "Fifteens", "Propeller cap", "10 Fifteens", ("fifteens", 10)),
    ("sweatband", "head", "Fifteens", "Sweatband", "4 Fifteens in one go", ("fifteen_go", 4)),
    ("mug", "hand", "Fifteens", "Coffee mug", "10 Fifteens before 9", ("fifteen_am", 10)),
    ("jetpack", "back", "Fifteens", "Jetpack", "100 Fifteens", ("fifteens", 100)),
    ("bowtie", "body", "Crew", "Bow tie", "Your first crewmate", ("crew", 1)),
    ("blush", "face", "Crew", "Heart cheeks", "A cheer from a crewmate", ("cheered_by", 1)),
    ("partyhat", "head", "Crew", "Party hat", "A room with your crew", ("rooms", 1)),
    ("shades", "face", "Crew", "Sunglasses", "A day your whole crew studied", ("crew_day", 1)),
    ("halo", "head", "Crew", "Halo", "Cheered 10 different crewmates", ("cheered", 10)),
    ("balloon", "hand", "Crew", "Balloon", "Cheered a 100-day streak", ("big_cheer", 1)),
    ("wings", "back", "Crew", "Little wings", "Cheers on 30 different days", ("cheer_days", 30)),
    ("lanyard", "body", "Squads", "Squad lanyard", "Joined a squad", ("squads", 1)),
    ("starpin", "body", "Squads", "Star pin", "A bingo line with your squad", ("bingo_line", 1)),
    ("facestar", "face", "Squads", "Star sticker", "A whole bingo card", ("bingo_card", 1)),
    ("flag", "hand", "Squads", "Squad flag", "Started a squad", ("founder", 1)),
    ("backpack", "back", "Plans", "Backpack", "Your first plan", ("plans", 1)),
    ("gradcap", "head", "Plans", "Grad cap", "A plan, every date done", ("plan_done", 1)),
    ("umbrella", "hand", "Coming back", "Umbrella", "Back after a week away", ("back7", 1)),
    ("phoenix", "back", "Coming back", "Phoenix wings", "Back after a month away", ("back30", 1)),
    ("pencil", "hand", "Card care", "Pencil", "50 cards you added", ("own_cards", 50),
     {"tip": "Cards you add in Anki’s Add window, counted from when the closet came"}),
    ("magnifier", "hand", "Card care", "Magnifying glass", "10 leeches turned around", ("leeches", 10),
     {"tip": "A card that lapsed 8 times, now going three weeks or more between reviews"}),
    ("viking", "head", "Beasts", "Viking helmet", "5 beasts beaten", ("beasts", 5)),  # 3.9.0: the Backlog Beast
    ("pumpkin", "head", "Seasons", "Pumpkin", "A day of Halloween week", ("halloween", 1), {"when": "24 to 31 Oct"}),
    ("witch", "head", "Seasons", "Witch hat", "Two days of Halloween week", ("halloween", 2), {"when": "24 to 31 Oct"}),
    ("batwings", "back", "Seasons", "Bat wings", "Three days of Halloween week", ("halloween", 3), {"when": "24 to 31 Oct"}),
    ("winter", "head", "Seasons", "Earmuffs and a scarf", "A day in winter", ("winter", 1),
     {"when": "1 Dec to 6 Jan", "also": ("body",)}),
    ("lantern", "hand", "Seasons", "Lantern", "The longest night", ("longnight", 1), {"when": "21 Dec"}),
    ("newyear", "head", "Seasons", "Gold party hat", "New Year", ("newyear", 1), {"when": "31 Dec and 1 Jan"}),
    ("hearts", "head", "Seasons", "Heart antennae", "Friends’ day", ("friends", 1), {"when": "14 Feb"}),
    ("flowers", "head", "Seasons", "Flower crown", "First day of spring", ("spring", 1), {"when": "20 Mar"}),
    ("sunhat", "head", "Seasons", "Sun hat", "First day of summer", ("summer", 1), {"when": "21 Jun"}),
    ("piehat", "head", "Secret", "A pie", "Pi day: 14 March", ("pi", 1)),
    ("catears", "head", "Secret", "Cat ears", "A Friday the 13th", ("fri13", 1)),
    ("cakehat", "head", "Secret", "Birthday cake", "A year with your Pip", ("sev_days", 365)),
    ("popper", "hand", "Secret", "Party popper", "Studied as the year turned", ("yearturn", 1)),
    # whole costumes
    ("dino", COSTUME, "Showing up", "Dinosaur", "200 days in a row", ("run", 200)),
    ("robot", COSTUME, "Showing up", "Robot", "250 days studied", ("days", 250)),
    ("wizard", COSTUME, "Showing up", "Wizard", "500 days studied", ("days", 500)),
    ("astronaut", COSTUME, "Showing up", "Astronaut", "1,000 days studied", ("days", 1000)),
    ("bee", COSTUME, "Crew", "Bee", "10 rooms with your crew", ("rooms", 10)),
    ("doctor", COSTUME, "Plans", "Doctor", "A plan finished, exam and all", ("plan_exam", 1),
     {"tip": "Every date of a plan with an exam on it done, and the exam behind you"}),
    ("detective", COSTUME, "Card care", "Detective", "50 leeches turned around", ("leeches", 50),
     {"tip": "A card that lapsed 8 times, now going three weeks or more between reviews"}),
    ("beasthood", COSTUME, "Beasts", "Beast hood", "Your first beast beaten", ("beasts", 1),
     {"tip": "When your overdue reviews pile up they turn up as a beast; review them to beat it"}),
    ("knight", COSTUME, "Beasts", "Knight", "10 beasts beaten", ("beasts", 10)),
    ("ghost", COSTUME, "Seasons", "Ghost", "Four days of Halloween week", ("halloween", 4), {"when": "24 to 31 Oct"}),
    ("mummy", COSTUME, "Seasons", "Mummy", "Five days of Halloween week", ("halloween", 5), {"when": "24 to 31 Oct"}),
    ("frog", COSTUME, "Secret", "Frog", "A leap day", ("leap", 1)),
)

THINGS = tuple(dict(k=t[0], slot=t[1], group=t[2], name=t[3], rule=t[4], need=t[5], **(t[6] if len(t) > 6 else {}))
               for t in _T)
BY = {t["k"]: t for t in THINGS}

# what a fact counts, for the bar under a thing you're close to
UNITS = {"run": "days in a row", "days": "days studied", "mornings": "mornings before 8",
         "evenings": "evenings after 9", "clear": "days with nothing left due", "reviews": "reviews",
         "learned": "cards learned", "fifteens": "Fifteens", "fifteen_am": "Fifteens before 9",
         "rooms": "rooms with your crew", "cheered": "crewmates cheered", "cheer_days": "days you cheered",
         "own_cards": "cards added", "leeches": "leeches turned around", "beasts": "beasts beaten"}


def places(k):
    """The places on Pip a thing takes: its own, and any it reaches into."""
    t = BY.get(k)
    if not t:
        return frozenset()
    return frozenset({t["slot"]}) | frozenset(t.get("also") or ())


def wear(look, k):
    """The look with `k` put on, or taken off when it's on already. A
    costume replaces the costume on (the things under it stay, for when it
    comes off); anything else takes the costume off and replaces whatever
    was in its places."""
    cur = clean(look)
    t = BY.get(k)
    if t is None:
        return cur
    if k in cur:
        return [x for x in cur if x != k]
    if t["slot"] == COSTUME:
        return [x for x in cur if BY[x]["slot"] != COSTUME] + [k]
    mine = places(k)
    return [x for x in cur if BY[x]["slot"] != COSTUME and not (places(x) & mine)] + [k]


def clean(look):
    """A look anyone sent, made one this closet can draw: things it knows,
    each put on in turn as wear() would (so of two that clash, the later
    stays), at most one in each place and one costume."""
    out = []
    for k in (look if isinstance(look, (list, tuple)) else [])[:2 * LOOK_MAX + 2]:
        if isinstance(k, str) and k in BY and k not in out:
            if BY[k]["slot"] == COSTUME:
                out = [x for x in out if BY[x]["slot"] != COSTUME] + [k]
            else:
                out = [x for x in out if not (places(x) & places(k))] + [k]
    return out


def costume(look):
    """The costume a look is wearing, or None."""
    return next((k for k in clean(look) if BY[k]["slot"] == COSTUME), None)


def shown(look):
    """What's showing: the costume alone while one's on, else the look."""
    c = costume(look)
    return [c] if c else clean(look)


DOWN = (4, 12)  # a held thing set down: on the ground at Pip's right (Sam: it never just goes)


def art(look, pose_holds=False):
    """The look's drawing for sev.py: (back, front, hand). hand: what the
    right hand holds, drawn at the hand of a hanging arm (sev moves it to
    the hand's place). While the pose's hands are busy (pose_holds: the
    card in a fifteen, the clock, a gift) it's set down beside Pip instead,
    behind it, so a look never loses a thing for a moment."""
    order = {s: i for i, s in enumerate(SLOTS + (COSTUME,))}
    ks = sorted(shown(look), key=lambda k: order.get(BY[k]["slot"], 0))
    back = "".join(ART[k][1] for k in ks if k in ART)
    front = "".join(ART[k][0] for k in ks if k in ART and BY[k]["slot"] != "hand")
    hand = "".join(ART[k][0] for k in ks if k in ART and BY[k]["slot"] == "hand")
    if pose_holds and hand:
        back, hand = back + f'<g class="cl-down" transform="translate({DOWN[0]} {DOWN[1]})">{hand}</g>', ""
    return back, front, hand


def clean_closet(v):
    """The account's closet, {thing: day}: things this closet knows, each
    with an ISO date."""
    out = {}
    if isinstance(v, dict):
        for k, d in v.items():
            if k in BY and isinstance(d, str) and len(d) == 10:
                try:
                    _dt.date.fromisoformat(d)
                except ValueError:
                    continue
                out[k] = d
    return out


def merge_closets(a, b):
    """Two computers' closets: everything either earned, each on its first day."""
    a, b = clean_closet(a), clean_closet(b)
    out = dict(a)
    for k, d in b.items():
        out[k] = min(d, out.get(k, d))
    return out


def earned(facts):
    """The things `facts` give (keys, in the closet's order)."""
    f = facts or {}
    return [t["k"] for t in THINGS if _n(f.get(t["need"][0])) >= t["need"][1]]


def offered(t, have=()):
    """3.9.0: a thing the closet shows and counts. The Backlog Beast's wait
    for the beast (beast.READY); one already had stays."""
    from . import beast
    return t["group"] != "Beasts" or beast.READY or t["k"] in have


def new(facts, have, today):
    """{thing: today} for each thing earned now that wasn't before."""
    have = clean_closet(have)
    return {k: today for k in earned(facts) if k not in have}


def near(facts, have, n=4):
    """The few you're close to: in each line of things counting the same
    fact (days in a row: 7, 14, 30 ...) only the next one, when it's at
    least half there. [(key, got, need, unit)], closest first. Never
    seasons or secrets: they're dates, not progress."""
    f, have = facts or {}, clean_closet(have)
    out, lines = [], set()
    for t in THINGS:
        fact, need = t["need"]
        if fact in lines or t["k"] in have or fact not in UNITS or not offered(t, have):
            continue
        got = _n(f.get(fact))
        if got >= need:
            continue  # earned, not yet recorded: the next refresh adds it
        lines.add(fact)
        if need > 1 and got * 2 >= need:
            out.append((t["k"], got, need, UNITS[fact]))
    out.sort(key=lambda x: -x[1] / x[2])
    return out[:n]


def progress(facts, have):
    """How far along each thing not yet earned is, for those that count up
    (days, reviews, Fifteens ...): {key: (got, need)}. Never seasons or
    secrets (dates, not progress), never a thing of one (had or not)."""
    f, have = facts or {}, clean_closet(have)
    out = {}
    for t in THINGS:
        fact, need = t["need"]
        if t["k"] in have or fact not in UNITS or need <= 1 or t["group"] == "Secret" or not offered(t, have):
            continue
        got = _n(f.get(fact))
        if got < need:
            out[t["k"]] = (got, need)
    return out


def _n(v):
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, (list, tuple, set, frozenset, dict)):
        return len(v)
    return 0


# ---- facts from the revlog ----

def _season_days(dates, month_day_from, month_day_to):
    """The most days studied in one year's window (mm-dd to mm-dd, a window
    that runs past New Year counted from its December)."""
    best, by_year = 0, {}
    for d in dates:
        md = (d.month, d.day)
        if month_day_from <= month_day_to:
            if month_day_from <= md <= month_day_to:
                by_year.setdefault(d.year, set()).add(d)
        elif md >= month_day_from:
            by_year.setdefault(d.year, set()).add(d)
        elif md <= month_day_to:
            by_year.setdefault(d.year - 1, set()).add(d)
    for s in by_year.values():
        best = max(best, len(s))
    return best


def from_days(labels):
    """The facts a list of days studied gives (Anki days, ISO dates, any
    order): how many, the longest run, the comebacks, the seasons, the
    dates."""
    dates = set()
    for lb in labels or ():
        try:
            dates.add(_dt.date.fromisoformat(str(lb)))
        except ValueError:
            continue
    out = {"days": len(dates), "run": 0, "back7": 0, "back30": 0}
    if not dates:
        return out
    run, prev = 0, None
    for d in sorted(dates):
        gap = (d - prev).days if prev else 1
        run = run + 1 if gap == 1 else 1
        out["run"] = max(out["run"], run)
        if prev and gap > 7:
            out["back7"] += 1
        if prev and gap > 30:
            out["back30"] += 1
        prev = d
    md = {(d.month, d.day) for d in dates}
    out.update(
        halloween=_season_days(dates, (10, 24), (10, 31)),
        winter=_season_days(dates, (12, 1), (1, 6)),
        longnight=int((12, 21) in md), newyear=int((12, 31) in md or (1, 1) in md),
        friends=int((2, 14) in md), spring=int((3, 20) in md), summer=int((6, 21) in md),
        pi=int((3, 14) in md), leap=int((2, 29) in md),
        fri13=int(any(d.day == 13 and d.weekday() == 4 for d in dates)))
    return out


MORNING = (5, 6, 7)  # before 8, not the small hours
EVENING = (21, 22, 23, 0, 1, 2)  # after 9, an evening that runs past midnight


def from_hours(starts):
    """The facts the hours studied give (each a local datetime: an hour
    with a review in it): mornings before 8, evenings after 9 (counted by
    the evening's date), and the year turning (the last hour of 31 Dec or
    the first of 1 Jan)."""
    morn, eve, turn = set(), set(), 0
    for h in starts or ():
        if h.hour in MORNING:
            morn.add(h.date())
        if h.hour in EVENING:
            eve.add((h - _dt.timedelta(hours=3)).date())
        if (h.month, h.day, h.hour) in ((12, 31, 23), (1, 1, 0)):
            turn = 1
    return {"mornings": len(morn), "evenings": len(eve), "yearturn": turn}


# ---- Halloween week (3.8.22) ----

HALLOWEEN = ("pumpkin", "witch", "batwings", "ghost", "mummy")  # a day of the week, two, three, four, five
HALLOWEEN_WEEK = ((10, 24), (10, 31))


def _date(v):
    try:
        return _dt.date.fromisoformat(str(v))
    except ValueError:
        return None


def halloween(today, studied, have):
    """Halloween week's line on the board (Sam's pick, round three), or None
    outside 24 to 31 Oct. today: the Anki day (ISO); studied: the days I
    studied (ISO; the board's eight are the whole week); have: the closet.
    {days: this week's, things: [(key, days it takes, mine)], next: (key,
    more days) or None, today: studied today}. The next is the first thing
    not mine that the days left this week can still reach."""
    t = _date(today)
    if t is None or not HALLOWEEN_WEEK[0] <= (t.month, t.day) <= HALLOWEEN_WEEK[1]:
        return None
    start = _dt.date(t.year, *HALLOWEEN_WEEK[0])
    week = {d for d in (_date(x) for x in studied or ()) if d and start <= d <= t}
    days, mine = len(week), clean_closet(have)
    things = [(k, BY[k]["need"][1], k in mine or BY[k]["need"][1] <= days) for k in HALLOWEEN]
    left = (_dt.date(t.year, *HALLOWEEN_WEEK[1]) - t).days + (0 if t in week else 1)
    nxt = next(((k, n - days) for k, n, got in things if not got and n - days <= left), None)
    return {"days": days, "things": things, "next": nxt, "today": t in week}


def spooky(looks):
    """Every Pip on the crew's rows has something of Halloween's showing,
    two Pips at least (a crewmate who isn't a mutual friend has no look, so
    a plain Pip): the board's cobweb."""
    looks = list(looks or ())
    return len(looks) >= 2 and all(set(shown(x)) & set(HALLOWEEN) for x in looks)


def longest_run(labels):
    """The longest run of consecutive dates among `labels` (ISO dates)."""
    return from_days(labels)["run"]
