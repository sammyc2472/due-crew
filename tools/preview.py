"""Render the real board.py output into a standalone page for visual audit.

Mimics Anki's deck browser context: same body font scale, a theme toggle
that flips the nightMode class, and buttons that run the real overlay JS.
"""

import html
import datetime
import json
import sys

import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tests"))  # the fake collection/aqt
import fakes  # noqa: E402

fakes.install_fake_requests(fakes.FakeWorker())
fakes.install_fake_aqt()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from due_crew import board  # noqa: E402

TODAY = datetime.date(2026, 9, 1)
L = [(TODAY - datetime.timedelta(days=i)).isoformat() for i in range(7)]
TOMORROW = (TODAY + datetime.timedelta(days=1)).isoformat()
NOW = datetime.datetime.now(datetime.timezone.utc)


def ago(**kw):
    return (NOW - datetime.timedelta(**kw)).strftime("%Y-%m-%dT%H:%M:%SZ")


def day(reviews, ms, acc, streak):
    return {"reviews": reviews, "studyTimeMs": ms, "accuracy": acc,
            "streak": streak, "studied": reviews > 0}


SIG = ["g%02d" % i for i in range(20)]
SIG2 = ["j%02d" % i for i in range(20)]

ENTRIES = [
    {"user_id": "sam", "name": "Sammy", "you": True, "paused": False,
     "last_updated": ago(minutes=1), "exam_date": (TODAY + datetime.timedelta(days=10)).isoformat(),
     "days": {L[0]: day(512, 4320000, 91.6, 12), L[1]: day(430, 3900000, 90.2, 11),
              L[2]: day(388, 3300000, 88.9, 10), L[4]: day(510, 4000000, 92.0, 8),
              L[5]: day(220, 2000000, 85.5, 7), L[6]: day(240, 2100000, 86.5, 6)},
     "decks": [{"name": "Big Step 1", "sig": SIG, "total": 32104, "seen": 4012, "mature": 2100, "open": 9800, "today": 212, "day": L[0], "ret": 91.2},
               {"name": "Japanese Core 2k", "sig": SIG2, "total": 2000, "seen": 1820, "mature": 1540}]},
    {"user_id": "dre", "name": "Dre", "you": False, "paused": False,
     "last_updated": ago(minutes=12), "exam_date": "",
     "days": {lb: day(700 + i * 30, 7440000, 93.1, 41 - i) for i, lb in enumerate(L)},
     "decks": [{"name": "Big Step 1", "sig": SIG, "total": 32104, "seen": 11240, "mature": 8020, "open": 12900, "today": 640, "day": L[0], "ret": 88.4}]},
    {"user_id": "marisa", "name": "Marisa K.", "you": False, "paused": False,
     "last_updated": ago(hours=1),
     "exam_date": (TODAY + datetime.timedelta(days=3)).isoformat(),
     "days": {L[0]: day(640, 5820000, 88.4, 17), L[2]: day(500, 4600000, 87.0, 15),
              L[3]: day(410, 3600000, 89.1, 14), L[5]: day(380, 3400000, 86.2, 12)},
     "decks": []},
    {"user_id": "long", "name": "Bartholomew Fitzgerald-Montgomery the Third of Pharmacology",
     "you": False, "paused": False, "last_updated": ago(minutes=3), "exam_date": "",
     "days": {L[0]: day(12345, 359940000, 100.0, 1234)}, "decks": []},
    {"user_id": "priya", "name": "Priya", "you": False, "paused": False,
     "last_updated": ago(hours=26), "exam_date": "",
     "days": {L[1]: day(233, 2400000, 86.0, 9), L[3]: day(310, 2900000, 84.4, 7)},
     "decks": [{"name": "Core 2k (JP)", "sig": SIG2, "total": 2000, "seen": 1281, "mature": 760}]},
    {"user_id": "noah", "name": "Noah", "you": False, "paused": False,
     "last_updated": ago(minutes=3), "exam_date": "", "back": True,
     "days": {L[0]: day(118, 1320000, 88.0, 1)}, "decks": []},
    {"user_id": "theo", "name": "Theo", "you": False, "paused": True,
     "last_updated": ago(days=2), "exam_date": "", "days": {}, "decks": []},
]

# v2.2: statuses ride today's doc; an away spell flags days ahead of time.
ENTRIES[0]["days"][L[0]]["status"] = "coffee, then 400 cards"
ENTRIES[2]["days"][L[0]]["status"] = ("Step 2 in 30 days, send help and also snacks, "
                                       "this is a long one to test the ellipsis")
ENTRIES[4]["days"][L[0]] = {"away": True,
                             "awayTo": (TODAY + datetime.timedelta(days=4)).isoformat()}

DATA = {"entries": ENTRIES, "labels": L, "tomorrow": TOMORROW, "pending": ["Jules"]}

# a crew past the row cap: the table scrolls inside the card and opens
# with your row in view (Sammy lands mid-table here)
MANY = ENTRIES + [
    {"user_id": f"m{i}", "name": n, "you": False, "paused": False,
     "last_updated": ago(minutes=5 + i), "exam_date": "",
     "days": {L[0]: day(980 - i * 41, 3000000 - i * 90000, 85.0 + i * 0.4, 20 - i)},
     "decks": [{"name": "Big Step 1", "sig": SIG, "total": 32104,
                "seen": 900 * (i + 1), "mature": 400 * (i + 1), "open": 1200 * (i + 1)}]}
    for i, n in enumerate(["Riley", "Sasha", "Jun", "Tomás", "Nia", "Owen", "Zara",
                           "Kai", "Lena", "Mateo", "Inés", "Yara", "Bo", "Eli"])
]
DATA_MANY = {"entries": MANY, "labels": L, "tomorrow": TOMORROW, "pending": []}

# show-up only: two crewmates who share presence and nothing else
SHOWUP = [
    {"user_id": "kai", "name": "Kai", "you": False, "paused": False, "last_updated": ago(minutes=9),
     "exam_date": "", "days": {lb: {"studied": i not in (2, 5)} for i, lb in enumerate(L)}, "decks": []},
    {"user_id": "nia", "name": "Nia", "you": False, "paused": False, "last_updated": ago(hours=3),
     "exam_date": "", "days": {lb: {"studied": i not in (1, 3, 4)} for i, lb in enumerate(L)}, "decks": []},
]
DATA_SHOWUP = {"entries": ENTRIES + SHOWUP, "labels": L, "tomorrow": TOMORROW, "pending": []}
WRAP = {"reviews": 21430, "time_ms": 148320000, "best_name": "Marisa K.", "full_days": 5}
DELTAS = {("sam", "Big Step 1"): 124}

now_ts = datetime.datetime.now().timestamp()
sections = []
EVE = {"people": [("marisa", "Marisa K.")]}
for period, wrap in (("today", WRAP), ("week", None), ("decks", None)):
    cfg = {"period": period}
    html_out = board.render(DATA, cfg, now_ts - 180, wrap=wrap, deltas=DELTAS,
                            exam_eve=EVE if period == "today" else None,
                            rules_stale=(period == "today"),
                            sticking={"Big Step 1": 10} if period == "decks" else None)  # 3.8.0: to Insights
    sections.append(f'<h3>{period}</h3>{html_out}')
SROWS = [
    {"user_id": "u1", "name": "StepQueen", "day": L[0], "reviews": 1412,
     "time_ms": 10920000, "streak": 88},
    {"user_id": "dre", "name": "Dre", "day": L[0], "reviews": 812,
     "time_ms": 7440000, "retention": 92.1, "streak": 41, "crew": True},
    {"user_id": "sam", "name": "Sammy", "day": L[0], "reviews": 512,
     "time_ms": 4320000, "retention": 91.6, "streak": 12, "you": True},
    {"user_id": "u2", "name": "Maya R.", "day": L[0], "reviews": 488,
     "time_ms": 3900000, "retention": 89.0, "streak": 31, "pending": True},
    {"user_id": "u3", "name": "Jordan", "day": L[0], "reviews": 302,
     "time_ms": 2400000, "retention": 94.2, "streak": 9, "knocked_me": True},
    {"user_id": "u4", "name": "Marcus", "day": L[1], "reviews": 220,
     "time_ms": 1860000, "retention": 87.4, "streak": 0},
]
SQUAD_VIEW = {"state": "ok", "squads": [{"id": "abc", "name": "busm"}, {"id": "def", "name": "MS2"}],
              "current": "abc", "name": "busm", "open": True, "founder_me": True,
              "rows": SROWS, "day": L[0], "yesterday": L[1], "people": 5, "studying": 4,
              "reviews": 2114}
KNOCKS = [{"uid": "u3", "name": "Jordan", "squad": "busm"}]
sections.append("<h3>today, two crewmates on show-up only (as everyone else sees them)</h3>"
                + board.render(DATA_SHOWUP, {"period": "today"}, now_ts - 60))
sections.append("<h3>week, same crew</h3>" + board.render(DATA_SHOWUP, {"period": "week"}, now_ts - 60))
sections.append("<h3>show-up mode: the one crew view (what a show-up person sees)</h3>"
                + board.render(DATA_SHOWUP, {"period": "today", "show_up": True}, now_ts - 60,
                               wrap={"reviews": 21430, "time_ms": 148320000, "full_days": 5}))
SROWS_SHOWUP = SROWS + [
    {"user_id": "s_kai", "name": "Kai", "day": L[0], "week": 5},
    {"user_id": "s_nia", "name": "Nia", "day": L[1], "week": 3}]
sections.append("<h3>squad with two show-up-only members</h3>" + board.render(
    DATA, {"period": "squads"}, now_ts - 60,
    squad_view=dict(SQUAD_VIEW, rows=SROWS_SHOWUP, people=8, studying=6)))
sections.append("<h3>squad in show-up mode</h3>" + board.render(
    DATA, {"period": "squads", "show_up": True}, now_ts - 60,
    squad_view=dict(SQUAD_VIEW, rows=SROWS_SHOWUP, people=8, studying=6)))
for period in ("today", "decks"):
    sections.append(f"<h3>{period}, 21 in the crew (the row cap)</h3>"
                    + board.render(DATA_MANY, {"period": period}, now_ts - 60))
SROWS_MANY = SROWS + [
    {"user_id": f"s{i}", "name": n, "day": L[0], "reviews": 700 - i * 15,
     "time_ms": 5000000 - i * 100000, "retention": 90.0 - i * 0.3, "streak": 30 - i}
    for i, n in enumerate(["Riley", "Sasha", "Jun", "Tomás", "Nia", "Owen", "Zara",
                           "Kai", "Lena", "Mateo", "Inés", "Yara"])]
sections.append("<h3>squad of 18 (the row cap)</h3>" + board.render(
    DATA, {"period": "squads"}, now_ts - 60,
    squad_view=dict(SQUAD_VIEW, rows=SROWS_MANY, people=18, studying=17)))
# 3.1-3.3: a plan I follow, on my schedule, on the Decks tab
# Due: Today, Upcoming and Later, the You bubble's lists (3.8.0)
from due_crew import due as _D
_T = L[0]
_d = lambda n: (TODAY + datetime.timedelta(days=n)).isoformat()
_DATES = [
    {"pid": "p1", "uid": "u0", "plan": "Big Step 1 · F3", "name": "F2-4 SLGs 6–8", "opens": _d(-2), "seen": 40, "total": 96},
    {"pid": "p1", "uid": "u1", "plan": "Big Step 1 · F3", "name": "F3-1 SLGs 1-3 · Absorption, distribution, elimination",
     "opens": _T, "seen": 31, "total": 109, "parts": [["Video Series", 6, 85], ["Path Book", 24, 24]],
     "todo": [{"k": "watch", "t": "lecture 14, renal clearance", "url": "https://example.com/l14"}],
     "what": "Video Series: Pharmacokinetics · Path Book: Drug elimination", "crew": [3, 8], "prep": "KSA F3-2",
     "topics": [["Video Series", [["Pharmacokinetics", 0]]], ["Path Book", [["Drug elimination", 1]]]],  # 3.8.0: links
     "rm": [[1, "Pages 40-44 only; the rest is next week"]]},  # 3.8.1: an author's note on a tag, under its topic
    {"pid": "p1", "uid": "u2", "plan": "Big Step 1 · F3", "name": "F3-2 SLG 5 · Clinical trial phases", "opens": _T, "seen": 24, "total": 24},
    {"pid": "p1", "uid": "u3", "plan": "Big Step 1 · F3", "name": "F3-2 SLGs 6a–6b · Drug interactions", "opens": _d(1), "seen": 0, "total": 129},
    {"pid": "p1", "uid": "u4", "plan": "Big Step 1 · F3", "name": "F3-2 SLG 7 · Autonomic drugs", "opens": _d(2), "seen": 0, "total": 96,
     "todo": [{"k": "watch", "t": "lecture 15"}]},
    {"pid": "p1", "uid": "u5", "plan": "Big Step 1 · F3", "name": "F4-1 SLGs 1–2 · Cardio phys", "opens": _d(9), "seen": 0, "total": 110},
]
_ITEMS = [
    {"id": "i0001", "t": "Email the course director about the retake", "d": _d(-2), "done": "", "at": _d(-3)},
    {"id": "i0002", "t": "Book the practice exam room", "d": _T, "done": "", "at": _T},
    {"id": "i0003", "t": "Practice exam 3", "d": _d(1), "done": "", "at": _T},
    {"id": "i0004", "t": "Return library books", "d": "", "done": "", "at": _T},
    {"id": "i0005", "t": "Ask Dre about the renal deck", "d": "", "done": "", "at": _T},
    # 3.8.0: a repeat, on today's weekday (TODAY is a Tuesday)
    {"id": "i0006", "t": "Practice block", "d": _T, "done": "", "at": _T, "r": "13"},
]
_DV = _D.view(_T, _DATES, _ITEMS, {}, events=[{"day": _d(4), "name": "KSA F3-2", "plan": "Big Step 1"}],
              review_days=[{"day": _d(3), "plan": "Big Step 1"}], reviews={"due": 214, "done": 120},
              suggestions=[{"key": "again", "text": "Go over today's 23 misses", "go": "Study"}],
              # 3.8.0: a plan's lines every week
              every=[{"pid": "p1", "plan": "Big Step 1", "first": _d(-30), "last": _d(40),
                      "lines": [{"k": "do", "t": "Practice questions (40)", "r": "0123456"},
                                {"k": "watch", "t": "Weekly review session", "r": str((_D.d(_T).weekday() + 3) % 7),
                                 "url": "https://example.com/r"}]}])
from due_crew import plans as PL  # noqa: E402
_PT = "2026-10-07"
_PDOC = {"pace": {"days": [1, 1, 1, 1, 1, 0, 0]},
         "units": [{"id": "a", "name": "Path Book 1 · Cell injury", "opens": "2026-10-05", "n": 283},
                   {"id": "b", "name": "V&B Biochem · Enzymes", "opens": "2026-10-06", "n": 96},
                   {"id": "c", "name": "Path Book 2 · Inflammation", "opens": "2026-10-07", "n": 42,
                    "tags": ["#Deck::#Path_Book::02_Inflammation::Acute", "#Deck::#Path_Book::02_Inflammation::Chronic",
                             "#Deck::#Video_Series::Immunology::Complement"], "search": ["tag:extra::mediators"]},
                   {"id": "d", "name": "V&B Metabolism 1", "opens": "2026-10-08", "n": 38, "for": "q"},
                   {"id": "e", "name": "Path Book 3 · Neoplasia", "opens": "2026-10-09", "n": 55, "for": "q"}],
         "events": [{"id": "q", "day": "2026-10-09", "name": "Cardio quiz"}]}
PLAN_CARD = {"id": "p1", "title": "MS2 Block 1 · Dre's plan", "sub": "week 3 of 9 · 6 following",
             "rows": [{"name": "Path Book 1 · Cell injury", "state": "open", "crew": [5, 6]}],
             "week": PL.week_view(_PDOC, {"a": [283, 283, 283], "b": [96, 80, 96], "c": [42, 18, 42]}, _PT, PL.week_start(_PT)),
             "week_offset": 0, "session": {"kind": "study", "target": 42, "done": 18, "due": 311, "minutes": 48, "behind": 0},
             "lines": [], "change": None, "no_deck": False, "paused": False,
             "waiting": 16, "aside": [0, 0, 0], "aside_ok": [0, 0],
             "ins": {"n": 53, "did": 10, "name": "KSA F3-3", "day": "2026-10-13"}}  # 3.8.0: the next exam's cards, from Insights
PLANS = {"cards": [PLAN_CARD], "offers": []}
_YOU = lambda tab, **kw: dict({"tab": tab, "plans": PLANS}, **kw)  # noqa: E731
sections.append("<h3>3.8.0: You › Plans, a plan I follow (Due on, so its lists first)</h3>" + board.render(
    DATA, {"period": "today"}, now_ts - 60, plans=PLANS, due=_DV, you=_YOU("plans")))
# 3.8.0: the plan's squad: a line on the plan card, and a pill on the Squads tab
_SQ = {"cards": [dict(PLAN_CARD, tabs={"unread": 2, "summary": {
    "shown": 5, "of": 12, "faces": ["\U0001F419", "\U0001F98A", "\U0001F331"], "last": {"name": "Maya"}}})], "offers": []}
sections.append("<h3>3.8.0: a plan I follow, in its squad (the line goes there); Due off</h3>" + board.render(
    DATA, {"period": "week", "due_show": False}, now_ts - 60, plans=_SQ, you=_YOU("plans", plans=_SQ)))
# 3.8.0: at my own pace: Up next with Open, what follows, the last step's Undo, quiet lines (no Behind)
_OWN = {"mode": "ready", "next": {"uid": "u2", "name": "SLG 13 · Heart failure", "n": 180},
        "then": ["SLG 14 · Arrhythmias · 96", "SLG 15 · Valves · 122", "SLG 16 · 140"], "more": 29,
        "at": "The plan's dates are at SLG 14 today.", "pace": "You opened 5 dates in the last two weeks.",
        "finish": "At that pace you open the last date on Tue 8 Dec, 3 days after Block exam.",
        "last": "Opened SLG 12 · Cardiac receptors · 214 cards, first in line.", "back": None}
sections.append("<h3>3.8.0: a plan at my own pace (When I'm ready), just after Open</h3>" + board.render(
    DATA, {"period": "today"}, now_ts - 60, plans=PLANS, due=_DV, you=_YOU("plans", plans={"cards": [dict(
        PLAN_CARD, sub="at your pace · 6 following", tabs={"summary": None}, ins=None, lines=[], waiting=0, own=_OWN)], "offers": []})))
sections.append("<h3>3.8.0: at my own pace, later (Put back), every date open</h3>" + board.render(
    DATA, {"period": "today"}, now_ts - 60, plans=PLANS, due=_DV, you=_YOU("plans", plans={"cards": [dict(
        PLAN_CARD, sub="at your pace · 6 following", tabs={"summary": None}, ins=None, lines=[], waiting=0,
        own=dict(_OWN, last=None, back={"name": "SLG 13 · Heart failure", "n": 180})),
        dict(PLAN_CARD, id="p2", title="Micro · Dre's plan", sub="at your pace · 2 following", tabs={"summary": None}, ins=None, lines=[],
             own=dict(_OWN, next=None, then=[], more=0, last=None, back=None, finish=None, pace=None,
                      at="The plan's dates ended Fri 4 Dec."))], "offers": []})))
sections.append("<h3>3.8.0: a plan I follow, not in its squad, behind</h3>" + board.render(
    DATA, {"period": "today"}, now_ts - 60, plans=PLANS, due=_DV, you=_YOU("plans", plans={"cards": [dict(
        PLAN_CARD, tabs={"summary": None}, ins=None,
        lines=[("behind", [("Path Book 1 · Cell injury", True), (" was due Mon. 54 cards not seen yet.", False)])])], "offers": []})))
# 3.8.1, plans round three: an invite to co-write and a hand-over above the plans; today's date
# with an author's note under the topic it names, and its picked cards named by their resource here
_R3DOC = dict(_PDOC, remarks=[{"id": "r1", "tag": "#Deck::#Path_Book::02_Inflammation", "text": "Figures 2-4 are on the quiz <b>"}],
              units=[dict(u, notes=[f"g{i}" for i in range(91)], _pl=[["#Deck::#Video_Series::Microbiology::Herpes_Viruses", 88], ["", 3]])
                     if u["id"] == "c" else u for u in _PDOC["units"]])
_R3 = {"cards": [dict(PLAN_CARD, tabs={"summary": None}, ins=None,
                      week=PL.week_view(_R3DOC, {"a": [283, 283, 283], "b": [96, 80, 96], "c": [42, 18, 42]}, _PT, PL.week_start(_PT)))],
       "offers": [], "invites": [{"id": "p9", "name": "MS2 Block 2", "kind": "coauthor", "by": {"name": "Kim", "emoji": ""}},
                                 {"id": "p8", "name": "Renal <b> block", "kind": "owner", "by": {"name": "Dre", "emoji": ""}}]}
sections.append("<h3>3.8.1: invites above the plans; a tag's note under its topic; picks named by their resource</h3>" + board.render(
    DATA, {"period": "today"}, now_ts - 60, plans=_R3, due=_DV, you=_YOU("plans", plans=_R3)))
# 3.8.1, plans round three: a follower's day. The morning's line by date; Study on a plan's date (the week,
# and Due); why a date left cards shut; a date after its event; the plan's day line apart from my own load;
# Then's dates as links, and what Open did; Welcome back's Not today
_PDOC3 = dict(_PDOC, units=_PDOC["units"] + [
    {"id": "f", "name": "Path Book 2 · Review", "opens": "2026-10-10", "n": 30, "for": "q"}])  # after the quiz
_W3 = PL.week_view(_PDOC3, {"a": [283, 283, 283], "b": [96, 80, 96], "c": [42, 18, 42]}, _PT, PL.week_start(_PT))
for _d in _W3:  # what plan_flow._week_more adds from this computer
    if _d["day"] >= _PT:
        _d["mine"] = {"2026-10-07": 311, "2026-10-08": 240, "2026-10-09": 198, "2026-10-10": 260}.get(_d["day"], 0)
    for _r in _d["units"]:
        if _r["state"] in ("open", "done"):
            _r["study"] = True
        if _r["uid"] == "a":
            _r["why"] = {"lee": 2, "miss": 3}
_C3 = dict(PLAN_CARD, week=_W3, tabs={"summary": None}, ins=None, waiting=0)
_DV3 = dict(_DV, rows=[dict(r, study=True) if r.get("kind") == "plan" and r["uid"] in ("u1", "u2") else r for r in _DV["rows"]],
            opened={"n": 120, "dates": [["p1", "u1", "Renal physiology", 80], ["p1", "u2", "Antiarrhythmics", 40]]})
_DV3["rows"] = [dict(r, after=True, prep="KSA F3-1") if r.get("uid") == "u2" else r for r in _DV3["rows"]]
# 3.8.1 (plans, rethought): Study for a quiz, from three days out, on what the plan says about now
sections.append("<h3>3.8.1: Study for a quiz, three days out</h3>" + board.render(
    DATA, {"period": "today"}, now_ts - 60, plans=PLANS, due=_DV, you=_YOU("plans", plans={"cards": [
        dict(_C3, prep={"name": "Cardio <quiz>", "day": "2026-10-09", "when": "Fri", "left": 2, "today": False},
             quiz={"id": "q", "name": "Cardio <quiz>", "day": "2026-10-09", "when": "Fri", "today": False, "units": ["a", "b"], "open": 412})],
        "offers": []})).replace('id="du-', 'id="duq-'))
sections.append("<h3>3.8.1: Today: the morning's line by date, Study on a plan's date, a date after its quiz</h3>" + board.render(
    DATA, {"period": "today"}, now_ts - 60, plans=PLANS, due=_DV3, you=_YOU("today")).replace('id="du-', 'id="du3-'))
sections.append("<h3>3.8.1: the morning's line, four or more dates</h3>" + board.render(
    DATA, {"period": "today"}, now_ts - 60, plans=PLANS, due=dict(_DV3, opened={"n": 344, "dates": [
        ["p1", f"u{i}", n, k] for i, (n, k) in enumerate((("Renal physiology", 80), ("Antiarrhythmics", 40),
                                                          ("Heart failure", 96), ("Valves", 128)))]}),
    you=_YOU("today")).replace('id="du-', 'id="du4-'))
sections.append("<h3>3.8.1: You › Plans: a past date left cards shut (its details open); Study on each open date</h3>" + board.render(
    DATA, {"period": "today"}, now_ts - 60, plans=PLANS, due=_DV, you=_YOU("plans", plans={"cards": [
        dict(_C3, focus="2026-10-05")], "offers": []})))
sections.append("<h3>3.8.1: today's details: what the plan opens, then my own load; a date after its quiz</h3>" + board.render(
    DATA, {"period": "today"}, now_ts - 60, plans=PLANS, due=_DV, you=_YOU("plans", plans={"cards": [
        dict(_C3, focus="2026-10-07"), dict(_C3, id="p2", focus="2026-10-10", title="MS2 Block 1 · after the quiz")],
        "offers": []})))
sections.append("<h3>3.8.1: Welcome back's Not today: the dates wait; at my own pace, Then's dates are links</h3>" + board.render(
    DATA, {"period": "today"}, now_ts - 60, plans=PLANS, due=_DV, you=_YOU("plans", plans={"cards": [
        dict(_C3, put_off=["F3-1 SLGs 1-3", "F3-2 SLG 5", "F3-2 SLG 7", "F3-3 SLG 1"], put_off_ask=True),
        dict(PLAN_CARD, id="p3", sub="at your pace · 6 following", tabs={"summary": None}, ins=None, lines=[], waiting=0,
             own=dict(_OWN, then_items=[{"uid": "u3", "name": "SLG 14 · Arrhythmias", "n": 96},
                                         {"uid": "u4", "name": "SLG 15 · Valves", "n": 122},
                                         {"uid": "u5", "name": "SLG 16", "n": 140}],
                      last="Opened SLG 15 · Valves (ahead of SLG 13 · Heart failure) · 122 cards, first in line."))],
        "offers": []})))
_EV = {"squares": [{"done": i in (0, 2, 5)} for i in range(8)], "middle": {"done": False, "have": 7, "goal": 9}, "lines": 0}
_TEAM = {"on": True, "count": 12, "shown": 5, "streak": 4, "more": 4, "bingo": {"card": {"wk": "2026-W41"}, "ev": _EV},
         "faces": [{"uid": "u1", "name": "Maya", "emoji": "\U0001F419", "shown": True},
                   {"uid": "me", "name": "Sam", "emoji": "\U0001F331", "shown": True},
                   {"uid": "u2", "name": "Dre", "emoji": "", "shown": True},
                   {"uid": "u3", "name": "Kai", "emoji": "\U0001F98A", "shown": True},
                   {"uid": "u4", "name": "Ameya", "emoji": "", "shown": True},
                   {"uid": "u5", "name": "Jordan", "emoji": "", "shown": False},
                   {"uid": "u6", "name": "Lee", "emoji": "\U0001F43C", "shown": False},
                   {"uid": "u7", "name": "Priya", "emoji": "", "shown": False}],
         "asks": [{"id": 1, "uid": "u1", "name": "Maya", "emoji": "\U0001F419", "text": "Why does isoproterenol drop diastolic pressure?",
                   "at": int(NOW.timestamp()) - 7200, "act": int(NOW.timestamp()) - 3600, "topic": "Direct Sympathomimetics",
                   "guid": "g1", "ord": 0, "mine": False, "remove": False, "author": False,
                   "replies": [{"id": 2, "uid": "u2", "name": "Dre", "emoji": "", "text": "\u03b22 vasodilation in skeletal muscle beds",
                                "at": int(NOW.timestamp()) - 3600, "helped": False, "author": True, "mine": False, "remove": False}]},
                  {"id": 3, "uid": "u3", "name": "Kai", "emoji": "\U0001F98A", "text": "Is Friday's quiz open-book for the PK formulas?",
                   "at": int(NOW.timestamp()) - 18000, "act": int(NOW.timestamp()) - 18000, "topic": "", "guid": "", "ord": 0,
                   "mine": False, "remove": False, "author": False, "replies": []}]}
_PSQ = {"kind": "plan", "pid": "p1", "name": "MS2 Block 1 \u00b7 Dre's plan", "current": "plan:p1",
        "squads": [{"id": "abc", "name": "busm"}, {"id": "def", "name": "MS2"}],
        "plan_squads": [{"id": "plan:p1", "pid": "p1", "name": "MS2 Block 1 \u00b7 Dre's plan", "unread": 0},
                        {"id": "plan:p2", "pid": "p2", "name": "Step 1 dedicated", "unread": 3}],
        "team": _TEAM, "team_state": "ok", "me": "me", "known": {"down": ["g1"], "have": ["g1"]}}
sections.append("<h3>3.8.0: a plan's squad on the Squads tab</h3>" + board.render(
    DATA, {"period": "squads"}, now_ts - 60, squad_view=_PSQ))
# 3.7.9: Insights, with the numbers of Sam's own snapshot (Wed 7 Oct)
_INS = {"target": 90, "right": {"now": [1308, 1519], "before": [1590, 1836],
                                "days": [84, 80, 88, 89, 85, 75, 94, 79, 82, 88, 91, 84, 94, 88][::-1]},
        "aim": {"day": "2026-10-13", "name": "KSA F3-3", "in": 6, "scoped": True}, "hero": list(range(53)), "behind": 0,
        "rows": [{"name": "Direct Sympathomimetics", "src": "Video Series › Autonomic System", "of": 27, "stuck": 9, "forgot": 0, "cids": [1]},
                 {"name": "Sympathomimetics", "src": "Picture Series › Sympathetic", "of": 44, "stuck": 8, "forgot": 2, "cids": [1]},
                 {"name": "Cholinomimetics", "src": "Picture Series › Parasympathetic", "of": 31, "stuck": 6, "forgot": 0, "cids": [1]},
                 {"name": "Muscarinic antagonists", "src": "Picture Series › Parasympathetic", "of": 47, "stuck": 4, "forgot": 0, "cids": [1]}],
        "week": {"past": [("2026-09-30", 0), ("2026-10-01", 14), ("2026-10-02", 0), ("2026-10-03", 50), ("2026-10-04", 66),
                          ("2026-10-05", 61), ("2026-10-06", 74)],
                 "ahead": [("2026-10-07", 130, 145, 0), ("2026-10-08", 204, 204, 133), ("2026-10-09", 237, 242, 122),
                           ("2026-10-10", 210, 220, 79), ("2026-10-11", 217, 228, 74), ("2026-10-12", 231, 246, 63),
                           ("2026-10-13", 128, 133, 55)], "avg": 204, "was": 38, "today_done": 46},
        "fsrs": {"right": 85, "n": 486, "target": 90}}
_DECKS = [{"did": 10, "name": "Big Step 1", "full": "Big Step 1"}, {"did": 20, "name": "Spanish", "full": "Languages::Spanish"}]
def _tile(name, n, kn, kids=(), st=None):
    t = {"key": name.lower(), "name": name, "n": n, "know": kn, "started": n if st is None else st,
         "find": {"tags": ["Big::^Systems::" + name]}}
    return dict(t, kids=list(kids)) if kids else t


# 3.8.0: the cards in play split a level down (one block open: Cardio's parts), a bar where some aren't started
_MAP = [_tile("Cardio · Physiology", 412, 86, [_tile("Cardiac output", 160, 91), _tile("Valves", 132, 79), _tile("ECG", 84, 88),
                                               _tile("Vessels", 36, 94)]),
        _tile("Cardio · Pathology", 318, 77, st=240), _tile("Cardio · Pharm", 260, 84, st=120), _tile("Renal · Physiology", 190, 66),
        _tile("Pulm · Pathology", 150, 88), _tile("Heme", 120, None, st=0), _tile("Endo", 96, 71, st=60), _tile("MSK", 64, 94)]
_PLAN_INS = {"decks": _DECKS, "did": 10, "exam": True, "plan": {"id": "p1", "name": "MS2 Block 1 · Dre's plan"},
             "view": dict(_INS, did=10, pid="p1", leeches=3, week=dict(_INS["week"], src="plan"), map=_MAP, map_by="fsrs",
                          map_ways=[{"key": "s", "name": "Systems", "on": True}, {"key": "b", "name": "Videos", "on": False},
                                    {"key": "y", "name": "HighYield", "on": False}, {"key": "~decks", "name": "Subdecks", "on": False}])}
sections.append("<h3>3.8.0: You › Insights, a deck with my plan on it (Sam's numbers)</h3>" + board.render(
    DATA, {"period": "today"}, now_ts - 60, plans=PLANS, due=_DV, you=_YOU("insights", insights=_PLAN_INS)))
_DECK_INS = dict(_INS, did=20, behind=0, leeches=0, fsrs=None,
                 aim={"day": "2026-10-14", "name": "Your exam", "in": 7, "scoped": False, "kind": "exam"},
                 rows=[{"name": "Subjunctive", "src": "Grammar", "of": 41, "stuck": 7, "forgot": 3, "cids": [1]},
                       {"name": "Preterite", "src": "Grammar", "of": 63, "stuck": 5, "forgot": 1, "cids": [1]}],
                 week=dict(_INS["week"], src="anki"))
sections.append("<h3>3.8.0: You › Insights, the map opened on Cardio</h3>" + board.render(
    DATA, {"period": "today"}, now_ts - 60, plans=PLANS, due=_DV,
    you=_YOU("insights", insights=dict(_PLAN_INS, view=dict(_PLAN_INS["view"], map_at=["cardio · physiology"])))))
sections.append("<h3>3.8.0: You › Insights, a deck with no plan (my exam date, its tags), Due off</h3>" + board.render(
    DATA, {"period": "today", "due_show": False}, now_ts - 60, plans=PLANS,
    you=_YOU("insights", insights={"decks": _DECKS, "did": 20, "exam": True, "plan": None, "view": _DECK_INS})))
sections.append("<h3>3.8.0: You › Insights, no exam date, nothing yet</h3>" + board.render(
    DATA, {"period": "today", "due_show": False}, now_ts - 60, plans=PLANS,
    you=_YOU("insights", insights={"decks": _DECKS[1:], "did": 20, "exam": False, "plan": None, "view": {}})))
sections.append("<h3>3.8.0: You › Plans, following nothing</h3>" + board.render(
    DATA, {"period": "today"}, now_ts - 60, due=_DV, you=_YOU("plans", plans={"cards": [], "offers": []})))
sections.append("<h3>3.8.0: Due off, folded: Plans and Insights on one line</h3>" + board.render(
    DATA, {"period": "today", "due_show": False}, now_ts - 60, plans=PLANS, you=_YOU("plans", folded=True)))
# 3.5.0: Settings in the board, each tab, and a Decks tab with asks both ways
SET_VIEW = {"signed_in": True, "name": "Sammy", "emoji": "\U0001F98A", "status": "coffee, then 400 cards",
            "sync": "sam@school.edu · Synced 2m ago · v3.5.0", "crew": 6, "squads": ["BUSM 2028", "Block 3"],
            "decks": ["Big Step 1"]}
SET_CFG = {"accent": "green", "hidden_tabs": ["squads"], "crew_label": "busm", "exam_date": "2026-10-14"}
for tab in ("you", "board", "privacy"):
    sections.append(f"<h3>3.5.0: Settings, {tab}</h3>" + board.settings_html(dict(SET_VIEW, tab=tab), SET_CFG))
sections.append("<h3>3.5.0: decks, asked of you and your asks</h3>" + board.render(
    DATA, {"period": "decks"}, now_ts - 60,
    tricky=[{"name": "Maya", "text": "Which nerve innervates the deltoid?", "deck": "Big Deck", "q": "why axillary?",
             "uid": "m", "index": 0, "known": True}],
    asks=[{"text": "The external iliac artery becomes the femoral artery as it c", "who": [], "state": "open", "index": 0},
          {"text": "Warfarin inhibits vitamin K epoxide reductase", "who": ["Dre"], "state": "answered"}]))
for _tab in ("today", "upcoming", "later"):
    sections.append(f"<h3>You: {_tab}</h3>" + board.render(DATA, {"period": "today"}, now_ts - 60, plans=PLANS,
                                                            due=dict(_DV, tab=_tab, opened={"n": 42} if _tab == "today" else None),
                                                            you=_YOU(_tab)).replace('id="du-', f'id="du{_tab}-'))
# 3.8.0: reviews done but learning cards back later; the morning's line with Sync now
_DV2 = _D.view(_T, _DATES[:2], _ITEMS, {}, reviews={"due": 0, "done": 120, "back": 4, "at": "9:42"})
sections.append("<h3>3.8.0: learning back at 9:42, a repeat, the morning's Sync now</h3>" + board.render(
    DATA, {"period": "today"}, now_ts - 60, plans=PLANS, due=dict(_DV2, opened={"n": 42, "sync": True}),
    you=_YOU("today")).replace('id="du-', 'id="dub-'))
sections.append("<h3>3.8.0: Insights, no plan, the exam date in its head; the Hard habit</h3>" + board.render(
    DATA, {"period": "today", "due_show": False}, now_ts - 60, plans=PLANS,
    you=_YOU("insights", insights={"decks": _DECKS, "did": 20, "exam": "2026-10-14", "plan": None,
                                   "view": dict(_DECK_INS, hard={"pct": 22, "n": 640})})))
sections.append("<h3>Due: folded</h3>" + board.render(DATA, {"period": "week"}, now_ts - 60, due=dict(_DV, folded=True),
                                                       plans=PLANS, you=_YOU("today", folded=True)))
sections.append("<h3>Due: done for today, a long tomorrow</h3>" + board.render(
    DATA, {"period": "week"}, now_ts - 60, due=dict(_DV, folded=True, done=True, behind_n=0, start=None, tomorrow=[
        "F3-1 SLGs 1-3 - Drug delivery and elimination kinetics", "F3-2 SLG 7 - Autonomic wiring and muscarinic antagonists"])))
sections.append("<h3>Due: added somewhere else</h3>" + board.render(
    DATA, {"period": "today"}, now_ts - 60, due=dict(_DV, toast={"text": "Added to Fri 9 Oct", "tab": "upcoming"},
                                                     rows=[], behind_n=0, behind_plans=[], behind_mine=[], suggestions=[])))
# the preview holds many boards; the add-on runs this once, for its one
sections.append("<script>" + board.keep_me_in_view_js().replace(
    "var box = document.querySelector('#due-crew .dc-scroll');\n        if (!box) { return; }",
    "document.querySelectorAll('#due-crew .dc-scroll').forEach(function(box) {")
    .replace("if (want > 0) { box.scrollTop = want; }\n    })();", "if (want > 0) { box.scrollTop = want; }\n    }); })();") + "</script>")
sections.append("<h3>squads (founder view)</h3>" + board.render(
    DATA, {"period": "squads"}, now_ts - 60, squad_view=SQUAD_VIEW))
# 3.6: squad bingo, as the Worker draws it (seeded squares from migration 0011)
from due_crew import bingo as _B
_SQ = [
    ("early", "m", "🌅", "Early bird", "Before 8am, on 2 days", "window", {"from": 0, "to": 8, "days": 2}, "third"),
    ("often", "m", "🧦", "Weekend", "Saturday and Sunday", "days", {"days": 2, "dow": [5, 6]}, "third"),
    ("clean", "e", "🧹", "Due zero", "A day with nothing left due", "zero", {"days": 1}, "half"),
    ("wild", "h", "🕰️", "Same time", "Start in the same hour, 4 days running", "samehour", {"run": 4}, 1),
    ("fresh", "m", "🌿", "New done", "All your new cards, 3 days in a row", "newdone", {"days": 3, "row": True}, "third"),
    ("focus", "e", "⏱️", "Twenty minutes", "20 minutes, no break", "focus", {"minutes": 20, "gap": 5}, "half"),
    ("volume", "h", "🚀", "Best in a month", "Your biggest day in 30", "best", {"days": 30}, 1),
    ("spread", "e", "🔁", "Two sittings", "2 sessions in a day, an hour apart", "sittings", {"n": 2, "gap": 60}, "half"),
]
_WK = _B.week_key(L[0])
_CARD = _B.clean_card({"wk": _WK, "squares": [
    {"id": f"s{i}", "fam": f, "diff": d, "icon": ic, "title": t, "rule": r, "detail": r + ".", "type": ty, "params": pa, "need": n}
    for i, (f, d, ic, t, r, ty, pa, n) in enumerate(_SQ)],
    "middle": {"id": "room", "group": "crew", "icon": "🏕️", "name": "Campfire", "rule": "3 of you in a study room",
               "detail": "Three of you join a study room this week.", "type": "people", "params": {"key": "rm"}, "goal": "third", "unit": "joined"}})
_MON = _B.week_labels(L[0])[0]
_ROWS = [dict(r, user_id=u, emoji=e, day=L[0], joined="2026-01-01", play={"wk": _B.wk_num(_WK), "s": s_, "rm": rm})
         for (u, e, s_, rm), r in zip([("sam", "😺", 0b10110101, 1), ("dre", "🦊", 0b10100111, 1), ("maya", "🐸", 0b00100001, 0),
                                        ("theo", "🐧", 0b00000001, 0), ("noah", "🦄", 0, 0)], [{}] * 5)] + [
    {"user_id": "pat", "emoji": "🐢", "day": L[0], "joined": "2026-01-01"}]  # on 3.5: no play
def _bv(rows, new=False, show_up=False):
    ev = _B.evaluate(_CARD, rows)
    return {"card": _CARD, "ev": ev, "me": "sam", "new": new, "show_up": show_up, "today": L[0],
            "progress": [(True, "Done"), (False, "1 of 2 days"), (True, "Done"), (False, "2 of 4 days running"),
                         (False, "1 of 3 days"), (True, "Done"), (False, "38 to go today (your best is 212)"), (True, "Done")],
            "names": {"pat": ("Pat", "🐢"), "sam": ("Sammy", "😺"), "dre": ("Dre", "🦊"), "maya": ("Maya", "🐸"), "theo": ("Theo", "🐧"), "noah": ("Noah", "🦄")},
            "squad": "BUSM 2028", "squad_id": "sq1", "closest": _B.closest(_CARD, ev)}
_LINE = [dict(r, play=dict(r["play"], rm=1, s=r["play"]["s"] | (0b1000 if r["user_id"] == "sam" else 0)))
         for r in _ROWS if "play" in r]  # everyone updated; Sam also kept the same hour: the left column is a line
sections.append("<h3>3.6: squad bingo on the Squads tab (Monday)</h3>" + board.render(
    DATA, {"period": "squads"}, now_ts - 60, squad_view=dict(SQUAD_VIEW, bingo=_bv(_ROWS, new=True))))
sections.append("<h3>3.6: squad bingo on the Squads tab (midweek)</h3>" + board.render(
    DATA, {"period": "squads"}, now_ts - 60, squad_view=dict(SQUAD_VIEW, bingo=_bv(_ROWS))))
sections.append("<h3>3.6: the whole card, midweek</h3>" + board.bingo_html(_bv(_ROWS), {}))
sections.append("<h3>3.6: the whole card, the middle unlocked: BINGO</h3>" + board.bingo_html(_bv(_LINE), {}))
sections.append("<h3>3.6: no card yet</h3>" + board.bingo_html(None, {}))
sections.append("<h3>squads (none yet)</h3>" + board.render(
    DATA, {"period": "squads"}, now_ts - 60,
    squad_view={"state": "none", "squads": [], "current": ""}))
sections.append("<h3>today with a knock banner</h3>" + board.render(
    DATA, {"period": "today"}, now_ts - 60, knocks=KNOCKS))
sections.append("<h3>someone added my code (2.9)</h3>" + board.render(
    DATA, {"period": "today"}, now_ts - 60,
    knocks=[{"uid": "p1", "name": "Priya", "squad": "", "via_code": True}]))
LIVE_AT = (NOW + datetime.timedelta(minutes=40)).strftime("%Y-%m-%dT%H:%M:%SZ")
TOGETHER = [dict(e) for e in ENTRIES]
TOGETHER[1]["live_until"] = LIVE_AT
TOGETHER[0]["live_until"] = LIVE_AT
TOGETHER[0]["days"] = dict(TOGETHER[0]["days"], **{L[0]: dict(TOGETHER[0]["days"][L[0]], status="600 cards, then bed")})
TOGETHER[2]["days"] = dict(TOGETHER[2]["days"], **{L[0]: dict(TOGETHER[2]["days"][L[0]], status="500 before lunch")})
sections.append("<h3>2.10: studying now, a plan, a 100-day streak</h3>" + board.render(
    dict(DATA, entries=TOGETHER), {"period": "today"}, now_ts - 60, live=True,
    milestones=[("dre", "Dre", 100)]))
sections.append("<h3>2.10: a flagged card on the Decks tab</h3>" + board.render(
    DATA, {"period": "decks"}, now_ts - 60,
    tricky=[{"uid": "dre", "name": "Dre", "index": 0, "text": "Heart sounds: S3 is heard in [\u2026]",
             "deck": "Cardio"}]))
SOLO = {"entries": [ENTRIES[0]], "labels": L, "tomorrow": TOMORROW, "pending": [],
        "my_code": "K7Q2ZP"}
# 2.12: study rooms, in the room, invited, and done
from due_crew import room_model  # noqa: E402
_room = room_model.make_room(DATA["entries"][1]["user_id"],
                             NOW - datetime.timedelta(minutes=36), 4, 25, 5)
ROOMED = [dict(e, room=_room) if i in (1, 2) or e["you"] else e for i, e in enumerate(DATA["entries"])]
sections.append("<h3>2.12: in a study room</h3>" + board.render(
    dict(DATA, entries=ROOMED), {"period": "today"}, now_ts - 60,
    room=room_model.board_view(_room, ROOMED)))
INVITED = [dict(e, room=_room) if i in (1, 2) else e for i, e in enumerate(DATA["entries"])]
sections.append("<h3>2.12: invited, and a room I finished</h3>" + board.render(
    dict(DATA, entries=INVITED), {"period": "today"}, now_ts - 60,
    room=dict(room_model.board_view(None, INVITED),
              done={"rounds": 4, "minutes": 115, "with": "Dre and Ameya"})))
sections.append("<h3>just me, the day I joined (2.9)</h3>" + board.render(SOLO, {"period": "today"}, now_ts - 60))
# 3.8.1: the Fifteen and Sev: the nudge with Sev napping by the logo, a fifteen
# under way, its question on the Decks screen, the session's line
from due_crew import sev as _sev  # noqa: E402
_DVN = dict(_DV, nudge=True, nudge_sev=_sev.svg("peek"), done_n=0)
sections.append("<h3>3.8.1: not started by my usual time: the nudge</h3>" + board.render(
    DATA, {"period": "today"}, now_ts - 60, plans=PLANS, due=_DVN, you=_YOU("today")).replace('id="du-', 'id="dun-'))
_fif = room_model.make_fifteen("sam", NOW - datetime.timedelta(minutes=6))
sections.append("<h3>3.8.1: a fifteen under way (Sev heads down)</h3>" + board.render(
    DATA, {"period": "today"}, now_ts - 60,
    room={"mine": dict(room_model.fifteen_view(_fif), sev=_sev.svg("focus")), "invites": [], "done": None}))
_ask = room_model.make_fifteen("sam", NOW - datetime.timedelta(minutes=16))
sections.append("<h3>3.8.1: the fifteen's question on the Decks screen</h3>" + board.render(
    DATA, {"period": "today"}, now_ts - 60,
    room={"mine": dict(room_model.fifteen_view(_ask), cards=38, sev=_sev.svg("ring")), "invites": [], "done": None}))
_brk = room_model.fifteen_next(_ask)
sections.append("<h3>3.8.1: its break</h3>" + board.render(
    DATA, {"period": "today"}, now_ts - 60,
    room={"mine": dict(room_model.fifteen_view(_brk), sev=_sev.svg("rest")), "invites": [], "done": None}))
sections.append("<h3>3.8.1: the session's line; Sev hops by the logo for a moment (the day's done)</h3>" + board.render(
    DATA, {"period": "today"}, now_ts - 60, sev={"svg": _sev.svg("hop"), "ago": 0},
    room={"mine": None, "invites": [], "done": None,
          "fifteen_done": {"n": 3, "minutes": 45, "cards": 212, "walked": False, "sev": _sev.svg("stack", stack=3)}}))
sections.append("<h3>3.8.1: by the logo for a moment: a cheer lands; exam eve; back from away</h3>" + "".join(board.render(
    SOLO, {"period": "today"}, now_ts - 60, sev={"svg": _sev.svg(k), "ago": 0}) for k in ("cheer", "exam", "hello")))
# Each board styles `#due-crew`; on one page the last <style> would win for
# all of them, so every accent gets its own document via srcdoc.
def _framed(markup, dark):
    page = ("<body class='%s' style='margin:0;padding:12px;background:%s'>%s</body>"
            % ("night_mode" if dark else "", "#2a2a2a" if dark else "#ececec", markup))
    return ("<iframe class='dc-acc' data-theme='%s' style='width:470px;height:430px;border:0;margin:0 6px 6px 0' "
            "srcdoc=\"%s\"></iframe>" % ("dark" if dark else "light", html.escape(page, quote=True)))


for accent in board.ACCENTS:
    frames = "".join(
        _framed(board.render(DATA, {"period": "today", "accent": accent, "theme": theme},
                             now_ts - 60), theme == "dark")
        for theme in ("light", "dark"))
    sections.append(f"<h3>accent: {accent}</h3><div style='display:flex;flex-wrap:wrap'>{frames}</div>")
sections.append("<h3>signed-out card</h3>" + board.signed_out_card({}))

profile_js = board.profile_overlay_js({
    "name": "Dre", "streak": 41, "last_active": ago(minutes=12),
    # until 2.9 this was `[...][i * 7 % 7]`, always 0: the preview never lit a cell
    "cells": [([0, 1, 3, 12, 30, 70, 160][(i * 3) % 7] if (i % 9) else 0) for i in range(182)],
    "start": (TODAY - datetime.timedelta(days=181)).isoformat(),
    "same_days": 118, "decks_line": "Big Step 1", "uid": "dre",
    "you": False, "paused": False, "exam": "",
    "duet": {"run": 5, "best": 23,
             "mine_week": [True, True, False, True, True, True, True],
             "theirs_week": [True, True, True, True, True, True, True]},
})
flurry = board.flurry_js(["\U0001F389"], "Dre sent cheers", back=("dre", "\U0001F389"),
                         season=board.season_emoji(TODAY))
luck_js = board.luck_card_js("Marisa", [("Dre", "You've done the work. Go get it."),
                                        ("Sammy", "Breakfast first. Then crush it."),
                                        ("Adina", "Proud of you either way \U0001F49A")])
stranger_js = board.stranger_card_js({"uid": "u2", "name": "Maya R.",
                                      "reviews": 488, "time_ms": 3900000,
                                      "retention": 89.0, "streak": 31, "rank": 3,
                                      "squad": "busm", "today": True,
                                      "pending": False, "knocked_me": False,
                                      "founder_me": True})

page = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Due Crew board preview</title>
<style>
  body {{ margin: 0; padding: 24px 12px 60px; background: #f5f5f5;  /* Anki's canvas (26.x) */
         font-family: -apple-system, sans-serif; }}
  body.nightMode {{ background: #2c2c2c; color: #d7d7d7; }}
  /* Anki 26.x deck screen: every table gets a translucent glass fill */
  :root {{ --canvas-glass: rgba(255, 255, 255, 0.7); }}
  body.nightMode {{ --canvas-glass: rgba(255, 255, 255, 0.10); }}
  .fancy table {{ background: var(--canvas-glass); }}
  h3 {{ max-width: 640px; margin: 26px auto 4px; font-size: 13px;
        font-family: monospace; opacity: 0.6; }}
  /* Anki's Decks screen, as the board meets it (3.5.0): the page sits in
     a <center> and every button gets Anki's own look. A board part that
     leans on either shows it here, not first in someone's Anki. */
  center button {{ margin: 4px 6px; padding: 6px 14px; border-radius: 10px;
                   box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3); min-width: 60px; }}
  .bar {{ position: fixed; top: 8px; right: 12px; z-index: 99; display: flex; gap: 6px; }}
  .bar button {{ font-size: 12px; padding: 4px 10px; }}
</style></head><body class="fancy">
<div class="bar">
  <button onclick="document.body.classList.toggle('nightMode')">theme</button>
  <button onclick="eval(PROFILE_JS)">profile</button>
  <button onclick="eval(FLURRY_JS)">flurry</button>
  <button onclick="eval(STRANGER_JS)">stranger</button>
  <button onclick="eval(LUCK_JS)">luck</button>
</div>
<center>{''.join(sections)}</center>
<script>
  function pycmd(cmd) {{ console.log('pycmd', cmd); return false; }}
  var PROFILE_JS = {json.dumps(profile_js)};
  var FLURRY_JS = {json.dumps(flurry)};
  var STRANGER_JS = {json.dumps(stranger_js)};
  var LUCK_JS = {json.dumps(luck_js)};
</script>
</body></html>"""

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "preview.html")
with open(out, "w") as f:
    f.write(page)
print("wrote", out, len(page), "bytes")
