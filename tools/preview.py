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
                            rules_stale=(period == "today"))
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
             "today_names": ["Path Book 2 · Inflammation"], "next": {"name": "V&B Metabolism 1", "uid": "d", "day": "Thursday", "n": 38},
             "week": PL.week_view(_PDOC, {"a": [283, 283, 283], "b": [96, 80, 96], "c": [42, 18, 42]}, _PT, PL.week_start(_PT)),
             "week_offset": 0, "opened": {"names": ["Path Book 2 · Inflammation"], "n": 42, "undo": True},
             "today_what": PL.topics_line([_PDOC["units"][1], _PDOC["units"][2]]),  # two dates: long enough to need its "…"
             "session": {"kind": "study", "target": 42, "done": 18, "due": 311, "minutes": 48, "behind": 0},
             "lines": [], "change": None, "no_deck": False, "paused": False, "today": "Wed 7 Oct", "sched": False,
             "waiting": 16}
sections.append("<h3>3.5.0: a plan I follow, on the Plans tab</h3>" + board.render(
    DATA, {"period": "plans"}, now_ts - 60, plans={"cards": [PLAN_CARD], "offers": []}))
sections.append("<h3>3.5.0: the Plans tab, following nothing</h3>" + board.render(
    DATA, {"period": "plans"}, now_ts - 60, plans={"cards": [], "offers": []}))
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
# Due: above the board on every tab, each of its tabs and folded
from due_crew import due as _D
_T = L[0]
_d = lambda n: (TODAY + datetime.timedelta(days=n)).isoformat()
_DATES = [
    {"pid": "p1", "uid": "u0", "plan": "Big Step 1 · F3", "name": "F2-4 SLGs 6–8", "opens": _d(-2), "seen": 40, "total": 96},
    {"pid": "p1", "uid": "u1", "plan": "Big Step 1 · F3", "name": "F3-1 SLGs 1-3 · Absorption, distribution, elimination",
     "opens": _T, "seen": 31, "total": 109, "parts": [["Video Series", 6, 85], ["Path Book", 24, 24]],
     "todo": [{"k": "watch", "t": "lecture 14, renal clearance", "url": "https://example.com/l14"}],
     "what": "Video Series: Pharmacokinetics · Path Book: Drug elimination", "crew": [3, 8], "prep": "KSA F3-2"},
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
]
_DV = _D.view(_T, _DATES, _ITEMS, {}, events=[{"day": _d(4), "name": "KSA F3-2", "plan": "Big Step 1"}],
              review_days=[{"day": _d(3), "plan": "Big Step 1"}], reviews={"due": 214, "done": 120},
              suggestions=[{"key": "again", "text": "Go over today's 23 misses", "go": "Study"}])
for _tab in ("today", "upcoming", "later"):
    sections.append(f"<h3>Due: {_tab}</h3>" + board.render(DATA, {"period": "today"}, now_ts - 60,
                                                            due=dict(_DV, tab=_tab)).replace('id="du-', f'id="du{_tab}-'))
sections.append("<h3>Due: folded</h3>" + board.render(DATA, {"period": "week"}, now_ts - 60, due=dict(_DV, folded=True)))
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
  body {{ margin: 0; padding: 24px 12px 60px; background: #ffffff;
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
