"""3.9.0: the Backlog Beast, yours (Sam's pick, the fun round's third round:
"Build · Yours · Rule B · My beast on to start · Steady · In parts of three
weeks"; reworked before it shipped, "Just the cards": no bite, no pace, no
speech, three lines on how it works). Pure: no aqt.

When your overdue reviews pile up they turn up as a creature. Its kind says
why the pile built (KINDS). It never grows: its cards are the ones overdue
(due before today) the morning it came, and each is off it once Anki has it
due tomorrow or later (Sam): a review that sends it ahead, Again only once
it's got right.
Study them opens its cards, the most overdue first, as many as you like.
Nothing to lose: a day off and it waits; Let it go and it leaves, nobody's
told. Beat it and it's a pet (and the closet's beast hood, viking helmet
and knight).

The pile: review cards due before today (not new, not learning, not
suspended or buried) in decks studied in the last 30 days. It turns up
(rule B, the round's simulation) when the pile is two usual days or more
and 100 cards or more, a week after the last one left, not while away or
paused. A bigger pile than three weeks of half a usual day comes in parts:
the most overdue first (relative to their intervals), the rest next time.

The account keeps it (`beast`: the one now and the last ones met), so
every computer has the same beast; this computer keeps its cards. With
My beast on (Privacy), my week says its kind and how far it's beaten,
never its size or its cards (week_field).
"""

import datetime as _dt
import statistics

MIN_PILE = 100
USUAL_DAYS = 2  # the pile, in usual days, before one turns up
REST_DAYS = 7  # after one leaves, beaten or let go
PART_DAYS = 21  # a beast is never more than three weeks of half a usual day (Sam's "in parts of three weeks")
WANDER_SHARE = 2  # half its cards gone without a review (suspended, deleted, made new): it wanders off
DECK_DAYS = 30  # a deck counts when it was studied this recently
USUAL_WINDOW = 28  # the usual day: the middle of the days studied in the last four weeks
SNOOZE_GAP, OWL_DAYS, LEECH_SHARE, PILE_DAYS = 7, 14, 0.15, 5
LEECH_LAPSES = 8
KEEP = 50  # beasts met, kept for the closet, Wrapped and the town
PACES = {"gentle": 0.25, "steady": 0.5, "fast": 1.0}  # a share of the usual day; only Steady sizes a beast's parts now
DEFAULT_PACE = "steady"
SHOW_DAYS = 2  # a crewmate's beaten beast: a banner for two days
ENDS = ("beaten", "let", "wandered")

KINDS = {
    # from: what its one line says after "17 overdue cards" (subtitle); None
    # says how many of your usual days it is
    "snooze": {"name": "The Snoozasaurus", "from": " that came due while you were away"},
    "owl": {"name": "The Overdue Owl", "from": ", most of them two weeks late or more"},
    "leech": {"name": "The Leech Lord", "from": ", many of them leeches (cards you keep forgetting)"},
    "pile": {"name": "The Pile", "from": None},
    "backlog": {"name": "The Backlog Beast", "from": None},
}
ORDER = ("snooze", "owl", "leech", "pile", "backlog")  # which cause wins when more than one is true


def _date(v):
    if isinstance(v, _dt.date):
        return v
    try:
        return _dt.date.fromisoformat(str(v))
    except ValueError:
        return None


def usual(day_counts, today):
    """Your usual day: the middle of your reviews on the days you studied
    in the last four weeks before today. day_counts: {ISO day: reviews}."""
    t = _date(today)
    xs = [int(n) for d, n in (day_counts or {}).items()
          if _date(d) and 0 < (t - _date(d)).days <= USUAL_WINDOW and int(n) > 0]
    return int(statistics.median(xs)) if xs else 0


def bite(usual_day, pace=DEFAULT_PACE):
    """A share of your usual day (half at Steady), one at least: three weeks
    of it is the most one beast holds (pick)."""
    return max(1, round(usual_day * PACES.get(pace, PACES[DEFAULT_PACE])))


def kind(gap_days, pile, usual_day, overdue_days, leeches):
    """Why the pile built, from the facts the morning it turns up: the days
    off just before, its size, how overdue its cards are (each card's days
    past due) and how many are leeches."""
    od = sorted(overdue_days or [])
    middle = od[len(od) // 2] if od else 0
    facts = {"snooze": gap_days >= SNOOZE_GAP, "owl": middle >= OWL_DAYS,
             "leech": pile and leeches / max(1, pile) >= LEECH_SHARE,
             "pile": usual_day and pile >= PILE_DAYS * usual_day}
    return next((k for k in ORDER if facts.get(k)), "backlog")


def should_turn_up(pile, usual_day, state, today, away=False, paused=False):
    """Rule B: a pile of two usual days or more and 100 cards or more, no
    beast already, a week since the last left, not away or paused, beasts
    on, and a usual day to measure by."""
    s = clean(state)
    if s.get("off") or s.get("now") or away or paused or usual_day <= 0:
        return False
    rest = _date(s.get("rest") or "")
    if rest and _date(today) < rest:
        return False
    return pile >= max(MIN_PILE, USUAL_DAYS * usual_day)


def pick(cards, usual_day, pace=DEFAULT_PACE):
    """The beast's cards from the pile: [(card id, days overdue, interval)],
    the most overdue for their interval first (Anki's relative
    overdueness), at most three weeks of half a usual day. (ids, capped)."""
    order = sorted(cards, key=lambda c: (-(c[1] / max(1, c[2])), -c[1], c[0]))
    most = PART_DAYS * bite(usual_day, pace)
    ids = [c[0] for c in order[:most]]
    return ids, len(order) > most


def turn_up(today, kind_key, cids, usual_day, pace=DEFAULT_PACE, capped=False, pile=0):
    """The beast that turns up this morning: what the account keeps of it.
    Its cards stay on this computer (the glue's beast.json)."""
    pace = pace if pace in PACES else DEFAULT_PACE
    return {"k": kind_key, "day": str(today), "size": len(cids), "usual": int(usual_day), "pace": pace,
            "capped": bool(capped), "pile": int(pile or len(cids)), "hit": 0, "gone": 0}


def progress(now):
    """(how far it's beaten, 0 to 1; cards left)."""
    size = max(1, int(now.get("size") or 0))
    done = min(size, int(now.get("hit") or 0) + int(now.get("gone") or 0))
    hit = min(size, int(now.get("hit") or 0))
    return hit / max(1, size - (done - hit)), size - done


def stage(frac):
    """0 whole, 1 a horn gone (a quarter), 2 both and a sweat (half), 3 dizzy (three quarters), 4 beaten."""
    return 4 if frac >= 1 else 3 if frac >= 0.75 else 2 if frac >= 0.5 else 1 if frac >= 0.25 else 0


def subtitle(kind_key, n, usual_day=0):
    """Its one line: what it is and why it came, in plain words. "860
    overdue cards that came due while you were away." The Pile and the
    Backlog Beast say how many of your usual days: "380 overdue cards:
    about 3 days of your usual reviews." """
    k = KINDS.get(kind_key, KINDS["backlog"])
    n = int(n)
    cards = f"{n:,} overdue card{'' if n == 1 else 's'}"
    if k["from"] is not None:
        return f"{cards}{k['from']}."
    if int(usual_day or 0) <= 0:
        return f"{cards}."
    d = max(1, round(n / int(usual_day)))
    return f"{cards}: about {d} day{'' if d == 1 else 's'} of your usual reviews."


def update(state, hit, gone, today):
    """The account's beast after counting: its hits and cards gone; beaten
    when none are left, wandered off when half went without a review. An
    end moves it to the ones met and starts the week's rest."""
    s = clean(state)
    now = s.get("now")
    if not now:
        return s
    now = dict(now, hit=max(int(now.get("hit") or 0), int(hit)), gone=int(gone))
    size = int(now["size"])
    how = ("wandered" if now["gone"] * WANDER_SHARE >= size else
           "beaten" if now["hit"] + now["gone"] >= size else None)
    if how is None:
        return dict(s, now=now)
    return end(dict(s, now=now), how, today)


def end(state, how, today):
    """It leaves: beaten, let go, or wandered off. Kept among the ones met
    (beaten ones become pets), and a week's rest before the next."""
    s = clean(state)
    now = s.get("now")
    if not now:
        return s
    met = (s.get("met") or []) + [{"k": now["k"], "day": now["day"], "end": str(today), "size": int(now["size"]), "how": how}]
    rest = (_date(today) + _dt.timedelta(days=REST_DAYS)).isoformat()
    return dict({k: v for k, v in s.items() if k != "now"}, met=met[-KEEP:], rest=rest)


def beaten(state, year=None):
    """The beasts beaten (in a year): [{k, name, day, end, size, days}]."""
    out = []
    for m in clean(state).get("met") or []:
        if m["how"] != "beaten" or (year and not str(m["end"]).startswith(str(year))):
            continue
        days = max(1, (_date(m["end"]) - _date(m["day"])).days)
        out.append(dict(m, name=KINDS[m["k"]]["name"], days=days))
    return out


def week_field(state, today, share=True):
    """What rides my week to mutual friends, with My beast on (Privacy):
    the kind and how far it's beaten, never its size or its cards; a
    beaten one for two days after (its end day, for their banner). None
    otherwise."""
    if not share:
        return None
    s = clean(state)
    now = s.get("now")
    if now:
        return {"k": now["k"], "p": int(progress(now)[0] * 100)}
    last = (s.get("met") or [None])[-1]
    if last and last["how"] == "beaten" and 0 <= (_date(today) - _date(last["end"])).days < SHOW_DAYS:
        return {"k": last["k"], "p": 100, "end": last["end"]}
    return None


def clean_week(v, today=None):
    """A crewmate's beast off their week: {k, p[, end]}, or None (an end
    older than two days, too)."""
    if not isinstance(v, dict) or v.get("k") not in KINDS:
        return None
    p = v.get("p")
    if not isinstance(p, int) or isinstance(p, bool) or not 0 <= p <= 100:
        return None
    out = {"k": v["k"], "p": p}
    if "end" in v:
        e = _date(v.get("end"))
        if not e or p != 100:
            return None
        if today and not 0 <= (_date(today) - e).days < SHOW_DAYS:
            return None
        out["end"] = e.isoformat()
    return out


def _n(v, lo=0, hi=10 ** 7):
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v < hi


def clean(v):
    """The account's beast, as this add-on writes it, or less: {off, rest,
    now: {k, day, size, usual, pace, capped, pile, hit, gone}, met: [...]}."""
    out = {}
    if not isinstance(v, dict):
        return out
    if v.get("off") is True:
        out["off"] = True
    if _date(v.get("rest") or ""):
        out["rest"] = str(v["rest"])[:10]
    n = v.get("now")
    if isinstance(n, dict) and n.get("k") in KINDS and _date(n.get("day") or "") and _n(n.get("size"), 1):
        out["now"] = {"k": n["k"], "day": str(n["day"])[:10], "size": n["size"],
                      "usual": n["usual"] if _n(n.get("usual")) else 0,
                      "pace": n["pace"] if n.get("pace") in PACES else DEFAULT_PACE,
                      "capped": n.get("capped") is True, "pile": n["pile"] if _n(n.get("pile")) else n["size"],
                      "hit": min(n["size"], n["hit"]) if _n(n.get("hit")) else 0,
                      "gone": min(n["size"], n["gone"]) if _n(n.get("gone")) else 0}
    met = []
    for m in v.get("met") or [] if isinstance(v.get("met"), list) else []:
        if (isinstance(m, dict) and m.get("k") in KINDS and m.get("how") in ENDS and _date(m.get("day") or "")
                and _date(m.get("end") or "") and _n(m.get("size"), 1)):
            met.append({"k": m["k"], "day": str(m["day"])[:10], "end": str(m["end"])[:10], "size": m["size"], "how": m["how"]})
    if met:
        out["met"] = met[-KEEP:]
    return out


def merge(a, b):
    """Two computers' beasts: the ones met, each once (by its day); the one
    now from the side that's counted further; off if either turned it off
    last... the newer save decides off and pace (b is the newer)."""
    a, b = clean(a), clean(b)
    out = dict(b)
    seen, met = set(), []
    for m in sorted((a.get("met") or []) + (b.get("met") or []), key=lambda m: (m["end"], m["day"])):
        if m["day"] not in seen:
            seen.add(m["day"])
            met.append(m)
    if met:
        out["met"] = met[-KEEP:]
    ended = {m["day"] for m in met}
    nows = [x for x in (a.get("now"), b.get("now")) if x and x["day"] not in ended]
    if nows:
        out["now"] = max(nows, key=lambda x: (x["day"], x["hit"] + x["gone"]))
    else:
        out.pop("now", None)
    rests = [x for x in (a.get("rest"), b.get("rest")) if x]
    if rests:
        out["rest"] = max(rests)
    return out
