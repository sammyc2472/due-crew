"""3.9.5, How you study (due_crew/habits.py, habits_flow.py): the findings on
synthetic logs (a planted effect is found and passes; a log with none
doesn't, over several seeds), the board's line and view, Slow but right and
its track record, the Fifteen at 35, and each new duecrew: command through
the add-on's own handler. Standard library only.

Run: python3 tests/test_habits.py
"""

import datetime
import os
import random
import re
import sqlite3
import sys
import time
import types

HARNESS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HARNESS)
sys.path.insert(0, HARNESS)

import fakes  # noqa: E402

fakes.install_fake_requests(fakes.FakeWorker())
fakes.install_fake_aqt()
sys.path.insert(0, REPO)

from due_crew import board  # noqa: E402
from due_crew import habits as H  # noqa: E402

CHECKS = []
TODAY = datetime.date(2026, 10, 26)
CUT = fakes.day_cutoff_for(TODAY)
DAY = H.DAY_MS


def check(name, cond, detail=""):
    CHECKS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond or detail == "" else f"\n     {detail}"))


def as_board(message):
    """A message as the Decks page sends it: with the board's key."""
    return message + "|" + board.BOARD_KEY


def at(days, minutes=0, cutoff=CUT):
    """ms: `minutes` past 8:00 into the Anki day `days` before today."""
    return (cutoff - (days + 1) * 86400) * 1000 + 8 * 3600000 + int(minutes * 60000)


# ---- synthetic logs ----

def speed_log(seed, effect=True, cards=900, days=55, base=0.13, slow_p=0.32, cutoff=CUT):
    """Review answers of `cards` cards over `days` days. A right answer that
    took 1.5-3x the card's own pace is followed by a miss with slow_p
    (effect) or base (none); everything else, base."""
    rng = random.Random(seed)
    start = (cutoff - days * 86400) * 1000
    rows, ids = [], set()
    for cid in range(1, cards + 1):
        u = rng.uniform(5000, 14000)
        last, prev_slow = rng.choice([2, 4, 9, 15, 30, 45, 80]), False
        for a in sorted(rng.uniform(0, (days - 0.1) * DAY) for _ in range(rng.randint(4, 9))):
            miss = rng.random() < (slow_p if effect and prev_slow else base)
            x = rng.random()
            m = (rng.uniform(0.55, 1.2) if x < 0.74 else rng.uniform(1.2, 1.5) if x < 0.88
                 else rng.uniform(1.5, 3.0) if x < 0.97 else rng.uniform(3.0, 6.0))
            ivl = 1 if miss else max(1, int(last * rng.uniform(1.8, 2.6)))
            i = start + int(a)
            while i in ids:
                i += 1
            ids.add(i)
            rows.append((i, cid, 1 if miss else rng.choice((3, 3, 3, 2, 4)), ivl, last, min(60000, int(u * m)), 1))
            prev_slow, last = not miss and 1.5 <= m < 3.0, ivl
    return sorted(rows)


def sit_log(seed, effect=True, days=50, base=0.86, drop=0.07, from_min=40, cutoff=CUT):
    """Two sittings a day of 20-120 minutes, answers 6-14 s apart; right
    falls by `drop` from `from_min` minutes in (effect), else stays."""
    rng = random.Random(seed)
    rows = []
    for d in range(days, 0, -1):
        day0 = (cutoff - (d + 1) * 86400) * 1000 + 6 * 3600000
        for s in range(2):
            t = begun = day0 + s * 5 * 3600000 + int(rng.uniform(0, 3600000))
            end = t + int(rng.uniform(20, 120) * 60000)
            while t < end:
                dt = int(rng.uniform(6000, 14000))
                t += dt
                last = rng.choice([2, 5, 12, 30, 70])
                p = base - (drop if effect and (t - begun) / 60000 >= from_min else 0) + (0.05 if last >= 21 else 0)
                ok = rng.random() < p
                rows.append((t, rng.randint(1, 4000), 3 if ok else 1, last * 2 if ok else 1, last, dt, 1))
    return sorted(rows)


# ---- the pure part ----

def test_basics():
    check("bands: 1-6, 7-20, 21-60, 61+ (a learning step's negative interval is the first)",
          [H.band(x) for x in (0, 1, 6, 7, 20, 21, 60, 61, 400, -600)] == [0, 0, 0, 1, 1, 2, 2, 3, 3, 0])
    check("days: the person's Anki day (its rollover), 0 today",
          (H.days_ago(CUT * 1000 - 1, CUT), H.days_ago(CUT * 1000 - DAY, CUT), H.days_ago(CUT * 1000 - DAY - 1, CUT)) == (0, 0, 1)
          and H.today_of(CUT) == TODAY)
    check("median", H.median([3, 1, 2]) == 2 and H.median([1, 2, 3, 4]) == 2.5 and H.median([]) == 0)
    tot = [10, 1, 10, 3, 0, 0, 0, 0, 20, 2, 5, 2, 0, 0, 0, 0]  # band 0: 10% vs 30%; band 2: 10% vs 40%
    g = H.matched_gap(tot)
    check("the matched gap: band by band, weighted as group 1 falls (2:1 here)",
          abs(g - (10 / 15 * 0.2 + 5 / 15 * 0.3)) < 1e-9, g)
    check("…None with no band in both groups", H.matched_gap([5, 1, 0, 0] + [0] * 4 + [0, 0, 3, 1] + [0] * 4) is None)
    vecs = [[(0, 1), (1, 1)], [(2, 1), (3, 1)], [(0, 1)], [(2, 1)]] * 20
    a, b = H.resample(vecs, H.matched_gap), H.resample(vecs, H.matched_gap)
    check("the range: 300 resamples, Random(7), the same every time; low under high", a == b and a[0] <= a[1], a)


def test_speed_finding():
    runs = [H.work_out(speed_log(s), CUT)["speed"] for s in (1, 2, 3)]
    check("slow but right: a planted effect is found and passes (3 seeds), the range above zero",
          all(r["pass"] and r["lo"] > 0 and r["slow"] > r["quick"] for r in runs),
          [(r["pass"], round(r["lo"], 3), round(r["slow"], 3), round(r["quick"], 3)) for r in runs])
    check("…on enough right answers that have a next one (1,500+), slow ones a few hundred",
          all(r["n"] >= H.SPEED_N and 200 < r["n_slow"] < r["n"] for r in runs), [(r["n"], r["n_slow"]) for r in runs])
    nulls = [H.work_out(speed_log(s, effect=False), CUT)["speed"] for s in (1, 2, 3, 4, 5, 6)]
    check("…a log with no effect doesn't pass (6 seeds): the range takes in zero",
          not any(r["pass"] for r in nulls) and all(r["lo"] <= 0 for r in nulls), [(round(r["lo"], 3), round(r["hi"], 3)) for r in nulls])
    small = H.work_out(speed_log(1, cards=200), CUT)["speed"]
    short = H.work_out(speed_log(1, cards=1500, days=20), CUT)["speed"]
    check("…nor under 1,500 answers with a next one, nor under 4 weeks of log (however strong)",
          not small["pass"] and small["n"] < H.SPEED_N and not short["pass"] and short["n"] >= H.SPEED_N, (small["n"], short["n"]))
    again = H.work_out(speed_log(1), CUT)["speed"]
    check("…worked out again, the same numbers", (again["lo"], again["hi"], again["gap"]) == (runs[0]["lo"], runs[0]["hi"], runs[0]["gap"]))


def test_sittings_finding():
    runs = [H.work_out(sit_log(s), CUT)["sit"] for s in (1, 2, 3)]
    check("long sittings: a planted slide is found and passes (3 seeds): 20+ long ones, 3+ points, the range below zero",
          all(r["pass"] and r["n"] >= H.SIT_N and r["gap"] <= -H.SIT_DROP and r["hi"] < 0 for r in runs),
          [(r["pass"], r["n"], round(r["gap"], 3), round(r["hi"], 3)) for r in runs])
    c = runs[0]["curve"]
    check("…its curve: six bands of minutes in, the first above the 30-45 one",
          [x[:2] for x in c] == [[0, 15], [15, 30], [30, 45], [45, 60], [60, 90], [90, None]] and c[0][2] > c[2][2] + 1, c)
    nulls = [H.work_out(sit_log(s, effect=False), CUT)["sit"] for s in (1, 2, 3, 4, 5, 6)]
    check("…a log with no slide doesn't pass (6 seeds)", not any(r["pass"] for r in nulls),
          [(round(r["gap"], 3), round(r["hi"], 3)) for r in nulls])
    small = [H.work_out(sit_log(s, drop=0.02), CUT)["sit"] for s in (1, 2, 3)]
    check("…nor a slide under 3 points", not any(r["pass"] for r in small), [round(r["gap"], 3) for r in small])
    few = H.work_out(sit_log(1, days=8), CUT)["sit"]
    check("…nor with under 20 sittings of an hour or more", not few["pass"] and few["n"] < H.SIT_N, few["n"])


def test_matured_and_time():
    rows = [
        (at(0, 5), 1, 3, 25, 10, 9000, 1),      # today: 10 days → 25: matured
        (at(3, 1), 2, 3, 21, 15, 10000, 1),     # 15 → 21: matured
        (at(3, 2), 3, 3, 40, 21, 20000, 1),     # mature already
        (at(2, 1), 5, 3, 25, 10, 30000, 2),     # a relearning step, not a review
        (at(8, 1), 4, 3, 30, 12, 12000, 1),     # last week
        (at(8, 2), 9, 0, 0, 0, 0, 4),           # a reschedule, no answer
        (at(50, 1), 6, 3, 22, 3, 7000, 1),      # 8 weeks ago (the oldest week)
        (at(60, 1), 7, 3, 30, 10, 7000, 1),     # before the 8 weeks
    ]
    r = H.work_out(rows, CUT)
    m = r["matured"]
    check("matured: review answers from under 21 days to 21 or more, this week (cards), and each of the 8 weeks, oldest first",
          m["n"] == 2 and m["cids"] == [1, 2] and m["weeks"] == [1, 0, 0, 0, 0, 0, 1, 2], m)
    check("…each week named by its first day, this week's 6 days back",
          m["from"][-1] == (TODAY - datetime.timedelta(days=6)).isoformat() and m["from"][0] == (TODAY - datetime.timedelta(days=55)).isoformat())
    check("the log's span: from its first answer in the 8 weeks", r["span"] == 51, r["span"])
    check("my time: minutes a studied day over the days before today (today's left out), seconds a review answer",
          abs(r["mins"] - 72000 / 60000 / 3) < 1e-9 and abs(r["secs"] - 14.0) < 1e-9, (r["mins"], r["secs"]))


def _card(cid, times, last_day, last_ease=3, last_time=None, start=40):
    """A card's review answers: right ones `times` (ms) on days from `start`
    down, then one more on `last_day`."""
    rows = [(at(start - 5 * k, cid % 50), cid, 3, 10, 5, t, 1) for k, t in enumerate(times)]
    rows.append((at(last_day, cid % 50 + 1), cid, last_ease, 20 if last_ease > 1 else 1, 10, last_time, 1))
    return rows


def test_slow_cards():
    rows = (_card(1, [8000] * 3, 2, last_time=16000)              # 2x its usual, 2 days ago: in
            + _card(2, [8000] * 3, 2, last_time=30000)            # past 3x: stepped away
            + _card(3, [8000] * 3, 9, last_time=16000)            # slow, but 9 days ago
            + _card(4, [8000] * 3, 2, last_ease=1, last_time=16000)  # a miss
            + _card(5, [8000], 2, last_time=16000, start=20)      # two right answers: no usual yet
            + _card(6, [8000] * 3, 1, last_time=22000)            # 2.75x: in, and slower
            + _card(7, [8000] * 3, 3, last_time=11000))           # 1.375x: quick enough
    r = H.work_out(sorted(rows), CUT)
    check("Slow but right: the cards whose latest review answer, in 7 days, was right and took 1.5-3x their usual; slowest first",
          r["slow"] == [6, 1] and set(r["slow_at"]) == {1, 6}, r["slow"])


def _tracked(n_studied, missed, rest_cards, rest_missed, built_days=40, look=True):
    """Studied cards (built `built_days` ago, looked at an hour later, then a
    review answer 10 days after) and never-studied slow ones."""
    rows, book = [], {}
    for k in range(n_studied):
        cid = 1000 + k
        built = at(built_days, k)
        book[cid] = built
        rows += [(at(built_days + 20 + j, k), cid, 3, 10, 5, 8000, 1) for j in range(3)]
        if look:
            rows.append((built + 3600000, cid, 3, 4, 10, 9000, 3))  # the look, in the filtered deck
        rows.append((at(built_days - 10, k), cid, 1 if k < missed else 3, 5, 10, 8000, 1))
    for k in range(rest_cards):
        cid = 5000 + k
        rows += [(at(45 + j, k), cid, 3, 10, 5, 8000, 1) for j in range(3)]
        rows.append((at(30, k), cid, 3, 12, 10, 16000, 1))   # slow, right
        rows.append((at(20, k), cid, 1 if k < rest_missed else 3, 1, 12, 8000, 1))
    return sorted(rows), book


def test_track_record():
    rows, book = _tracked(30, 3, 20, 6)
    t = H.work_out(rows, CUT, book)["track"]
    check("track record: studied ones by their next review answer after the look, against the slow ones never studied",
          t["n"] == 30 and abs(t["studied"] - 0.1) < 1e-9 and abs(t["rest"] - 0.3) < 1e-9 and t["ready"] and not t["against"], t)
    rows, book = _tracked(29, 3, 20, 6)
    check("…said only once 30 have had a next answer", not H.work_out(rows, CUT, book)["track"]["ready"])
    rows, book = _tracked(30, 3, 20, 6, built_days=20)
    t = H.work_out(rows, CUT, book)["track"]
    check("…and 4 weeks have passed since the first went in", not t["ready"], t)
    rows, book = _tracked(30, 10, 20, 6)
    t = H.work_out(rows, CUT, book)["track"]
    check("…studied ones not missed less: against it", t["ready"] and t["against"] and t["studied"] >= t["rest"], t)
    rows, book = _tracked(30, 3, 20, 6, look=False)
    t = H.work_out(rows, CUT, book)["track"]
    check("…a card that went in but wasn't answered within 3 days isn't one studied", t["n"] == 0 and not t["ready"], t)
    check("…nothing studied, no record", H.work_out(rows, CUT)["track"] is None)


def _res(speed=True, sit=True, track=None, span=40, n=38):
    sp = {"pass": speed, "slow": 0.22, "quick": 0.13, "gap": 0.08, "lo": 0.04, "hi": 0.12, "n_slow": 310, "n_quick": 2000, "n": 2310}
    curve = [[0, 15, 84.1, 900], [15, 30, 83.4, 800], [30, 45, 78.9, 700], [45, 60, 79.9, 500], [60, 90, 75.5, 300], [90, None, 73.7, 90]]
    return {"day": CUT, "span": span, "mins": 113.0, "secs": 9.2,
            "matured": {"n": n, "weeks": [12, 18, 15, 22, 26, 24, 31, n], "cids": list(range(n)),
                        "from": [(TODAY - datetime.timedelta(days=7 * k + 6)).isoformat() for k in reversed(range(8))]},
            "speed": sp, "slow": [1, 2], "slow_at": {1: 1, 2: 2}, "track": track,
            "sit": {"pass": sit, "curve": curve, "gap": -0.05, "lo": -0.08, "hi": -0.02, "n": 26}}


def test_summary():
    s = H.summary(_res(), 46)
    check("summary: what passes, with Study N", s["speed"] and s["sit"] and s["study"] == 46 and s["track"] is None
          and (s["sit"]["from"], s["sit"]["to"]) == (84.1, 78.9))
    s = H.summary(_res(speed=False, sit=False), 46)
    check("…a finding that doesn't pass isn't there at all (nor Study)", s["speed"] is None and s["sit"] is None and s["study"] == 0)
    tr = {"n": 34, "studied": 0.14, "rest": 0.22, "rest_n": 300, "ready": True, "against": False}
    s = H.summary(_res(track=tr), 46)
    check("…the track record, once it's ready", s["track"] == {"studied": 0.14, "rest": 0.22, "n": 34} and s["study"] == 46)
    s = H.summary(_res(track=dict(tr, studied=0.25, against=True)), 46)
    check("…against it: Study goes away, the tile stays", s["speed"] and s["study"] == 0 and s["track"]["studied"] == 0.25)


def test_sitting_now():
    s = H.fold_sitting(None, [(1000000 + k * 60000, 8000) for k in range(41)])
    check("the sitting going on: answers 10 minutes apart at most, from the first one's start",
          s == [1000000 - 8000, 1000000 + 40 * 60000])
    s2 = H.fold_sitting(s, [(s[1] + 11 * 60000, 5000)])
    check("…a gap over 10 minutes starts a new one", s2 == [s[1] + 11 * 60000 - 5000, s[1] + 11 * 60000])
    now = s[1] + 30000
    check("…past 35 minutes, still going: the chip", H.sit_due(s, now))
    check("…not when it's over (no answer for 10 minutes)", not H.sit_due(s, s[1] + 11 * 60000))
    check("…not when waved off this sitting", not H.sit_due(s, now, dismissed=s[0]) and H.sit_due(s, now, dismissed=s[0] - 1))
    check("…after a Fifteen or a room, 35 minutes from its end", not H.sit_due(s, now, floor=s[1] - 20 * 60000)
          and H.sit_due(s, now, floor=s[1] - 36 * 60000))
    check("…not under 35 minutes", not H.sit_due([s[0], s[0] + 34 * 60000], s[0] + 34 * 60000))


# ---- the board ----

def _hv(**kw):
    s = H.summary(_res(**{k: v for k, v in kw.items() if k in ("speed", "sit", "track", "n")}), kw.get("study", 46))
    s["open"] = kw.get("open", True)
    return s


def _ins(habits, view=None):
    return {"decks": [{"did": 7, "name": "Big Step 1", "full": "Big Step 1"}], "did": 7, "exam": "", "view": view or {},
            "habits": habits}


def test_board():
    line = board._you_insights(_ins(_hv(open=False)))
    check("Insights: the line on top, How you study › and the week's matured, opening the view",
          "How you study &rsaquo;" in line and "<b>38</b> matured this week" in line
          and f"duecrew:inshabits:7:open|{board.BOARD_KEY}" in line, line[:600])
    check("…under two weeks of log, no line at all (board_view gives none)",
          "How you study" not in board._you_insights(_ins(None)))
    check("…not over the leeches view", "How you study" not in board._you_insights(_ins(_hv(open=False), {"leech": {}})))
    v = board._you_insights(_ins(_hv()))
    check("the view in Insights' place: ‹ Insights back, its name, my time in its head",
          "&lsaquo; Insights" in v and "duecrew:inshabits:7:shut" in v and "<b>How you study</b>" in v
          and "<b>1h 53m</b> a day &middot; <b>9 s</b> a card" in v and "Not sticking" not in v)
    check("…the win: matured, Anki's word, its hover, eight bars (each its title), See them",
          'title="Next review 3 weeks or more away">38<small>matured this week</small>' in v
          and v.count("matured</title>") == 8 and "This week: 38 matured</title>" in v
          and "duecrew:inshabits:7:see" in v)
    check("…Slow but right (3.9.5, Sam: \"this doesn't make much sense\"): the cards to look at again, the raw rates "
          "as two bars, quick and slow, missed next time, the range in their titles, Study N",
          ">46<small>right, but slow, this week</small>" in v and ">quick</text>" in v and ">slow</text>" in v
          and '<div class="hs-cap">missed next time</div>' in v and ">13%</text>" in v and ">22%</text>" in v
          and v.count("At the same intervals: +8 points, could be 4 to 12</title>") == 2
          and ">Study 46</a>" in v and "duecrew:inshabits:7:slow" in v)
    check("…long sittings: the first band to the 30-45 one, 35 marked, a point a band with its title, Start a Fifteen",
          ">35 min<small>then you start missing more</small>" in v and 'title="84% right in your first 15 minutes, 79% at 30 to 45"' in v
          and '<div class="hs-cap">right, by minutes in one go</div>' in v and ">35</text>" in v
          and v.count('class="t-dot"') == 6 and "0&ndash;15 min in: 84% right (900 answers)</title>" in v
          and f"duecrew:room15|{board.BOARD_KEY}" in v and "Start a Fifteen" in v)
    check("…charts on the board's tokens (dark works): no colour of their own",
          not re.search(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?\b", board.HABITS_CSS)
          and "color-mix(in srgb, var(--dc-accent) 34%" in board.HABITS_CSS and "fill=" not in v)
    none = board._you_insights(_ins(_hv(speed=False, sit=False)))
    check("nothing passed: the win, and one line", "More as you study." in none and "Study 46" not in none
          and "Start a Fifteen" not in none and "missed next time" not in none and "matured this week" in none)
    only = board._you_insights(_ins(_hv(sit=False)))
    check("…a finding that doesn't pass has no tile", "Start a Fifteen" not in only and "Study 46" in only
          and "More as you study." not in only)
    gone = board._you_insights(_ins(_hv(study=0)))
    check("…Study gone (its record against it, or none to study): the tile stays", "Study " not in gone and ">0<small>right, but slow" in gone)
    tr = {"n": 34, "studied": 0.14, "rest": 0.22, "rest_n": 300, "ready": True, "against": False}
    rec = board._you_insights(_ins(_hv(track=tr)))
    check("…its track record, once it has one", "Studied ones: 14% missed next time &middot; 22% the rest" in rec)
    zero = board._you_insights(_ins(_hv(n=0, speed=False, sit=False)))
    check("…none matured this week: no See them", "inshabits:7:see" not in zero and ">0<small>" in zero)
    hv = _hv()
    hv["matured"]["from"][0] = '<img src=x onerror="alert(1)">'
    hv["mins"] = None
    bad = board._you_insights(_ins(hv))
    check("…what isn't a day draws nothing; no time, no head numbers", "<img" not in bad and "onerror" not in bad
          and "Week of : 12 matured" in bad and "a day &middot;" not in bad)
    narrow = board.HABITS_CSS
    check("…tiles wrap to one a row when narrow", "repeat(auto-fit, minmax(160px, 1fr))" in narrow and "min-width: 0" in narrow)
    for src in ("habits.py", "habits_flow.py"):
        text = open(os.path.join(REPO, "due_crew", src)).read()
        check(f"never sent: {src} makes no request and keeps no account key",
              "client(" not in text and "requests" not in text and "_bg(lambda: cl" not in text and "ACCOUNT_KEYS" not in text)


# ---- the glue ----

def _col(rows, cards=(), cutoff=CUT):
    conn = sqlite3.connect(":memory:")
    fakes.make_collection(conn)
    conn.executemany("INSERT INTO revlog (id, cid, ease, ivl, lastIvl, time, type) VALUES (?,?,?,?,?,?,?)", rows)
    have = set()
    for cid, queue, odid in cards:
        fakes.add_card(conn, cid, 1, ctype=2, queue=queue, odid=odid)
        have.add(cid)
    for cid in sorted({r[1] for r in rows} - have):
        fakes.add_card(conn, cid, 1, ctype=2, queue=2)
    col = fakes.FakeCol(conn, cutoff)
    col.mod = 1
    col.decks = fakes.FakeDecks({1: "Big Step 1"})
    return col


class Rig:
    """habits_flow over a fake collection: the job run right away, plans.json
    in memory, the board's redraws and the browser counted."""

    def __init__(self, col):
        from due_crew import habits_flow as F, plan_flow as PF, app as A
        self.F, self.PF, self.A = F, PF, A
        self.pc, self.swaps, self.browsed, self.built, self.moved = {}, [], [], [], []
        self.saved = (F.mw.col, F.mw.state, A._bg, A.swap, A.board_up, PF._pcfg, PF._psave, PF._browse, PF._filtered,
                      PF._after_change, getattr(F.mw, "moveToState", None), F._now_ms)
        F.mw.col, F.mw.state = col, "deckBrowser"
        F._now_ms = lambda: CUT * 1000 - 60000  # the synthetic log's day, whatever the machine's clock says
        A._bg = lambda job, done=None: done(job()) if done else job()
        A.swap = lambda c, **k: self.swaps.append(1)
        A.board_up = lambda: True
        PF._pcfg = lambda: self.pc
        PF._psave = lambda c: self.pc.update(c)
        PF._browse = lambda cids, q=None, empty="": self.browsed.append(list(cids))
        PF._filtered = lambda col_, name, cids, order=4: (self.built.append((name, list(cids))),
                                                          col_.decks.names.__setitem__(99, name)) and True
        PF._after_change = lambda: None
        F.mw.moveToState = lambda s: self.moved.append(s)
        col.decks.select = lambda did: None
        A._state.pop("habits", None)

    def close(self):
        F, PF, A = self.F, self.PF, self.A
        (F.mw.col, F.mw.state, A._bg, A.swap, A.board_up, PF._pcfg, PF._psave, PF._browse, PF._filtered,
         PF._after_change, mts, F._now_ms) = self.saved
        if mts is not None:
            F.mw.moveToState = mts
        A._state.pop("habits", None)


def test_flow():
    rows = speed_log(4)
    res = H.work_out(rows, CUT)
    cand = res["slow"]
    shut = cand[:3]  # suspended, buried, in a filtered deck already
    rig = Rig(_col(rows, [(shut[0], -1, 0), (shut[1], -2, 0), (shut[2], 2, 9)]))
    F = rig.F
    try:
        check("flow: nothing worked out yet, then once a day: one read, the sums (off the main thread in Anki)",
              F.result() is None and F.next_up() is not None and F.result()["day"] == CUT and rig.swaps == [1])
        F.check()
        check("…asked again the same day, nothing new is read or drawn", len(rig.swaps) == 1)
        live = F.slow_now()
        check("…Slow but right as the collection is now: not suspended, buried or in a filtered deck",
              live == [c for c in cand if c not in shut] and len(live) >= H.NEXT_UP_MIN, (len(cand), len(live)))
        nu = F.next_up()
        n = len(live)
        check("Next up: the slow ones, with their Study", nu == {"key": "slow", "text": f"{n} you got right, but slowly. One more look.",
                                                                  "go": f"Study {n}", "n": n}, nu)
        bv = F.board_view()
        check("…and the view: the finding, Study N, closed", bv["speed"] and bv["study"] == n and bv["open"] is False)
        F.study_slow()
        name, cids = rig.built[-1]
        book = rig.pc.get("slow_studied") or {}
        check("Study N: Due Crew's filtered deck, Slow but right, slowest first, and into it",
              name == "Due Crew::Slow but right" and cids == live and rig.moved == ["overview"], (name, len(cids)))
        check("…each card kept with when it went in (this profile's plans.json, never sent)",
              sorted(int(k) for k in book) == sorted(live) and all(isinstance(v, int) and v > 0 for v in book.values()))
        rig.F.mw.col.mod = 2
        check("…studied since: none left, so no Next up", F.slow_now() == [] and F.next_up() is None)
        F._mine()["res"]["track"] = {"against": True}
        rig.pc["slow_studied"] = {}
        check("a track record against it: no Next up, no Study", F.next_up() is None and F.board_view()["study"] == 0)
        F._mine()["res"]["track"] = None
        F.see_matured()
        check("See them: this week's matured, in the browser", rig.browsed == [res["matured"]["cids"]])
        gen = rig.A.generation
        rig.A.generation += 1
        check("another profile or account: nothing of the last one's", F.result() is None)
        rig.A.generation = gen
    finally:
        rig.close()
    rig = Rig(_col(speed_log(1, days=10)))
    try:
        check("under two weeks of log: no How you study", rig.F.board_view() is None and rig.F.result()["span"] <= 10)
    finally:
        rig.close()
    rig = Rig(_col(speed_log(5)))
    waiting = []
    rig.A._bg = lambda job, done=None: waiting.append((job, done))
    try:
        rig.F.check()
        rig.A.generation += 1
        job, done = waiting.pop()
        done(job())
        check("a log worked out for a profile since closed lands nowhere", rig.F.result() is None and rig.swaps == [])
    finally:
        rig.close()
    rig = Rig(_col(speed_log(2, cards=100)))
    threads = []
    rig.A._bg = lambda job, done=None: threads.append(1)
    try:
        rig.F.check()
        check("a light log is worked out right there (no thread; the board drawing now has it, no redraw)",
              threads == [] and rig.F.result() is not None and rig.swaps == [])
    finally:
        rig.close()


def _dc():
    import due_crew as dc
    from aqt.deckbrowser import DeckBrowser
    if "aqt.reviewer" not in sys.modules:
        sys.modules["aqt.reviewer"] = types.SimpleNamespace(Reviewer=type("Reviewer", (), {}))
    return dc, DeckBrowser


def test_commands():
    """Every new duecrew: command, through _on_js as the board and the top bar send them."""
    dc, DeckBrowser = _dc()
    from due_crew import rooms as R, room_model as rm, habits_flow as F
    rows = speed_log(4)
    rig = Rig(_col(rows))
    got = []
    saved = (F.study_slow,)
    try:
        send = lambda m: dc._on_js(False, as_board("duecrew:" + m), DeckBrowser())  # noqa: E731
        F.check()
        n0 = len(rig.swaps)
        send("inshabits:7:open")
        check("inshabits:<deck>:open: How you study in Insights' place", F._mine().get("open") is True and len(rig.swaps) == n0 + 1)
        check("…the view it draws comes with it (all decks)", F.board_view()["open"] is True)
        send("inshabits:7:shut")
        check("…:shut, back to Insights", F._mine().get("open") is False and len(rig.swaps) == n0 + 2, (n0, rig.swaps))
        send("inshabits:7:see")
        check("…:see, this week's matured in the browser", rig.browsed == [F.result()["matured"]["cids"]])
        F.study_slow = lambda: got.append("slow")
        send("inshabits:7:slow")
        check("…:slow, Study N", got == ["slow"])
        send("inshabits:x:slow")
        send("inshabits:7:nope")
        dc._on_js(False, "duecrew:inshabits:7:slow", DeckBrowser())  # no board key: a page before's, not the board's
        check("…a deck that isn't one, an act that isn't one, a message without the board's key: nothing", got == ["slow"])
        F._mine()["open"] = True
        from due_crew import team_flow as T
        saved_t = (T.you_decks, T.cfg, T.save_cfg)
        T.you_decks, T.cfg, T.save_cfg = (lambda: [{"did": 7}]), (lambda: {}), (lambda c: None)
        try:
            send("insdeck:7")
        finally:
            T.you_decks, T.cfg, T.save_cfg = saved_t
        check("…a deck picked above it: that deck's Insights", F._mine().get("open") is False)
        # every duecrew: command the line and the view put on the board has its handler
        h = H.summary(_res(), 46)
        html_ = board._habits_html(7, h) + board._habits_line(7, h)
        cmds = set(re.findall(r"duecrew:([a-z0-9]+)", html_))
        src = open(os.path.join(REPO, "due_crew", "team_flow.py")).read() + open(os.path.join(REPO, "due_crew", "rooms.py")).read()
        check("…the board's commands here are inshabits and room15, each handled",
              cmds == {"inshabits", "room15"} and all(f'cmd == "{c}"' in src for c in cmds), cmds)
    finally:
        F.study_slow = saved[0]
        rig.close()
    # the top bar's chip: Take five and ×, keyed, from the top bar only
    tb = types.ModuleType("aqt.toolbar")
    tb.TopToolbar = type("TopToolbar", (), {"__init__": lambda self, toolbar=None: None})
    tb.Toolbar = type("Toolbar", (), {})
    saved_mod = sys.modules.get("aqt.toolbar")
    sys.modules["aqt.toolbar"] = tb
    cl = types.SimpleNamespace(signed_in=True, user_id="me", session={}, _save_session=lambda: None)
    t0 = datetime.datetime(2026, 10, 26, 18, 0, tzinfo=datetime.timezone.utc)
    breaks, refreshed = [], []
    from due_crew import app as A
    from due_crew.app import _state
    keep = (R.client, R._now, R._show_break, R.refresh_widgets, A.sync, A.swap, R.mw.state, dict(_state))
    try:
        R.client, R._now = (lambda: cl), (lambda: t0)
        R._show_break = lambda room: breaks.append(room)
        R.refresh_widgets = lambda: refreshed.append(1)
        A.sync, A.swap = (lambda **k: None), (lambda c, **k: None)
        R.mw.state = "review"
        _state["entries"] = [{"user_id": "me", "you": True, "room": None, "live_until": ""}]
        _state["labels"] = ["2026-10-26"]
        dc._on_js(False, f"duecrew:room15sit|{rm.CMD_KEY}", type("Previewer", (), {})())
        check("room15sit from a card's page: nothing (not one of the widgets' own there)", "room" not in cl.session)
        dc._on_js(False, f"duecrew:room15sit|{rm.CMD_KEY}", tb.TopToolbar())
        room = cl.session.get("room")
        p = rm.phase(room, t0) if room else {}
        check("room15sit (Take five), from the top bar: a fifteen already in its break, the first counted as just ended",
              rm.is_fifteen(room) and room["rounds"] == 2 and p.get("state") == "break" and p.get("round") == 1
              and p.get("left") == 300 and rm.fifteen_spent(room, t0) == (1, 15), (room, p))
        check("…the break in place of the card, as after any fifteen; my crew sees studying now",
              breaks == [room] and cl.session.get("live_until") == "2026-10-26T18:25:00Z", (breaks, cl.session))
        later = rm.phase(room, t0 + datetime.timedelta(minutes=5, seconds=1))
        ask = rm.phase(room, t0 + datetime.timedelta(minutes=20, seconds=1))
        check("…then a fifteen, then its question", later["state"] == "round" and later["round"] == 2 and ask["state"] == "ask")
        F._mine()["sit"] = [111, 222]
        dc._on_js(False, f"duecrew:room15sitx|{rm.CMD_KEY}", tb.TopToolbar())
        check("room15sitx (×): not again this sitting, and the bar drawn again", F._mine().get("sit_x") == 111 and refreshed)
    finally:
        (R.client, R._now, R._show_break, R.refresh_widgets, A.sync, A.swap, R.mw.state) = keep[:7]
        _state.clear()
        _state.update(keep[7])
        if saved_mod is None:
            sys.modules.pop("aqt.toolbar", None)
        else:
            sys.modules["aqt.toolbar"] = saved_mod
        F._state.pop("habits", None)


def test_fifteen_at_35():
    from due_crew import rooms as R, room_model as rm, habits_flow as F, app as A
    from due_crew.app import _state
    on = rm.start_data(("#2e7d32", "#7cc47f"), "right", True, sit=35)
    off = rm.start_data(("#2e7d32", "#7cc47f"), "right", True)
    js = rm.widget_js("start", on)
    check("the chip: ▶ Fifteen?'s place, its minutes, Take five and ×, no Pip drawn for it",
          on["sit"] == 35 and off["sit"] == 0 and on["sev"] is None and off["sev"] and '"sit": 35' in js
          and "'room15sit'" in js and "'room15sitx'" in js and "min in" in js and "Take five" in js)
    check("…in the accent: the background is the accent, its words the page's", "background:' + c.a + ';color:' + c.bg" in js)
    now = int(time.time() * 1000)
    rows = [(now - 40 * 60000 + k * 30000, 100 + k, 3, 10, 5, 8000, 1) for k in range(80)]
    col = _col(rows)
    sent = []

    class Web:
        def eval(self, js_):
            sent.append(js_)
    top = Web()
    keep = (F.mw.col, F.mw.state, R._webs, R.client, R.cfg, R.my_room, R._data, R._where, dict(_state))
    try:
        F.mw.col, F.mw.state = col, "review"
        A._state.pop("habits", None)
        F._mine()["res"] = {"sit": {"pass": True}}
        check("reviewing, my long sittings slide, 40 minutes in one go: the chip", F.sit_chip() is True)
        F._mine()["res"] = {"sit": {"pass": False}}
        check("…not when my own log doesn't show the slide", F.sit_chip() is False)
        F._mine()["res"] = {"sit": {"pass": True}}
        F.mw.state = "deckBrowser"
        check("…only while reviewing", F.sit_chip() is False)
        F.mw.state = "review"
        R._webs = lambda: (top, None, None)
        R.client = lambda: types.SimpleNamespace(signed_in=True, session={})
        R.cfg = lambda: {}
        R.my_room = lambda: None
        R._DRAWN.clear()
        _state["entries"] = [{"user_id": "me", "name": "Sam", "you": True}]
        R.refresh_widgets()
        check("the top bar draws it in ▶ Fifteen?'s place", sent and '"sit": 35' in sent[-1])
        R.cfg = lambda: {"fifteen": False}
        R._DRAWN.clear()
        sent.clear()
        R.refresh_widgets()
        check("…not with the Fifteen switched off in Settings", not any('"sit": 35' in s for s in sent))
        R.cfg = lambda: {}
        room = rm.make_fifteen("me", datetime.datetime.now(datetime.timezone.utc))
        R.my_room = lambda: room
        R._data = lambda room_, **k: rm.widget_data(room_, [], ("#2e7d32", "#7cc47f"), sev=False)
        R._where = lambda: "chip"
        R.refresh_widgets()
        check("…a Fifteen running: none, and the 35 minutes count from its end", F._mine().get("floor", 0) >= now
              and F.sit_chip() is False)
        F._mine().pop("floor")
        F._mine()["sit"] = None
        check("…its end long past: the chip again", F.sit_chip() is True)
        F.dismiss_sit()
        check("…× waves it off for this sitting", F.sit_chip() is False)
    finally:
        F.mw.col, F.mw.state, R._webs, R.client, R.cfg, R.my_room, R._data, R._where = keep[:8]
        _state.clear()
        _state.update(keep[8])
        R._DRAWN.clear()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    failed = [n for n, ok in CHECKS if not ok]
    print(f"\n{len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed")
    sys.exit(1 if failed else 0)
