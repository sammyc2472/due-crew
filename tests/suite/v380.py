"""The suite: 3.8.0: the You bubble, Due, plan updates, the board's motion."""

from due_crew import board
from due_crew.backend import api
from due_crew.backend import shapes
from due_crew.stats.queries import StatsQueries
import datetime
import fakes
import json
import os
import re
import sqlite3
import srcs
import sys
import tempfile
import types

from .base import KK, REPO, TODAY, as_board, check, make_user_col, new_client, world
from .plans import _PlanGlue, _skip_schedule, _spread_col
from .board import _day, _open, _patched_due_crew, _plan_col, _plan_units, _row_sync, _squad_fixture


def test_site_today_is_anki_day_v380():
    """3.8.0: the site's today rolls over at the hour the add-on said
    (/auth/me's rollover), as Anki's day does, not at midnight. Needs node."""
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        print("SKIP site today: no node")
        return
    js = open(os.path.join(REPO, "site", "public", "app.js")).read()
    head = js[js.index("const MONTHS"):js.index("const nextMonday")]
    prog = head + (
        "Date.now = () => Date.parse('2026-10-08T02:30:00Z');"
        "const a = today(); rollover = 4; const b = today(); rollover = 0;"
        "console.log(a + ' ' + b + ' ' + today());")
    out = subprocess.run([node, "-e", prog], capture_output=True, text=True, timeout=60,
                         env=dict(os.environ, TZ="UTC"))
    check("site: 02:30 is still yesterday with a 4am rollover",
          out.stdout.split() == ["2026-10-08", "2026-10-07", "2026-10-08"], out.stdout + out.stderr)
    check("site: whoami takes the rollover from /auth/me",
          "rollover = Math.max(0, Math.min(23, Number(me?.rollover) || 0));" in js)


def test_plans_tab_v341():
    """3.5.0: the Plans tab. The week of my own plan, a Today box in each
    kind of day, a day's details, the tab with no plan, and names escaped."""
    from due_crew import plans as P
    mon = P.week_start("2026-10-07")
    check("week: starts on Monday, and moves by weeks", mon == "2026-10-05" and P.week_start("2026-10-07", 1) == "2026-10-12"
          and P.week_start("2026-10-05") == "2026-10-05")
    doc = {"pace": {"days": [1, 1, 1, 1, 1, 0, 0]},
           "units": [{"id": "a", "name": "Path Book 1", "opens": "2026-10-05", "n": 40},
                     {"id": "b", "name": "V&B <i>", "opens": "2026-10-06", "cards": [["g", 0]] * 3, "sn": {"x": 5}},
                     {"id": "c", "name": "Path Book 2", "opens": "2026-10-07", "n": 42, "for": "q"},
                     {"id": "d", "name": "Metab", "opens": "2026-10-08", "idn": 38}],
           "events": [{"id": "q", "day": "2026-10-09", "name": "Cardio quiz"}]}
    w = P.week_view(doc, {"a": [40, 40, 40], "b": [8, 6, 8], "c": [42, 18, 42]}, "2026-10-07", mon,
                    skipped=[{"id": "x", "name": "Extras", "opens": "2026-10-09"}])
    by = {d["day"]: d for d in w}
    check("week: seven days, today marked, past before it", len(w) == 7 and by["2026-10-07"]["today"]
          and by["2026-10-05"]["past"] and not by["2026-10-08"]["past"])
    check("week: a unit's state, done, open or later, with its counts",
          [u["state"] for u in by["2026-10-05"]["units"]] == ["done"] and by["2026-10-06"]["units"][0]["state"] == "open"
          and {k: v for k, v in by["2026-10-08"]["units"][0].items() if k != "what"}
          == {"uid": "d", "name": "Metab", "total": 38, "seen": 0, "state": "later", "prep": False, "moved": False})
    check("week: a date's count before it opens (author's n, cards, searches, ids)",
          P.unit_total(doc["units"][1]) == 8 and P.unit_total(doc["units"][3]) == 38)
    check("week: rest days are the plan's off days with nothing opening; prep and events marked",
          by["2026-10-10"]["rest"] and not by["2026-10-09"]["rest"] and by["2026-10-07"]["prep"]
          and by["2026-10-09"]["events"] == ["Cardio quiz"] and by["2026-10-09"]["units"][0]["state"] == "skip"
          and by["2026-10-09"]["new"] == 0)
    week = w
    base = {"id": "p1", "title": "MS2 <b>Block</b>", "sub": "week 3 of 9", "rows": [{"name": "Path Book 1", "state": "open", "crew": [5, 6]}],
            "lines": [], "change": None, "no_deck": False, "paused": False, "week": week, "week_offset": 0,
            "session": {"kind": "study", "target": 42, "done": 18, "due": 311, "minutes": 48, "behind": 0}}
    h = board._plan_card_html(base)
    check("card: 3.8.0, no Today box (Due's Today has today), so no Study now or time guess here",
          'class="ptoday' not in h and "planstudy:p1" not in h and "~48" not in h and "</b> min" not in h
          and "<b>MS2 &lt;b&gt;Block&lt;/b&gt;</b>" in h)
    tidx = next(i for i, d in enumerate(week) if d["today"])
    cells = h.split('<div class="pwk">')[1].split('<div class="pday"')[0]
    check("week: round five, Sam's pick A, seven small days: names in the details, not the days; every day's details shut "
          "until its click; names escaped",
          'class="pwk"' in h and "V&amp;B &lt;i&gt;" in h and "<i>" not in h.replace("<i class", "").replace("<i style", "")
          and 'class="pc now"' in h and " sel\"" not in h and "Path Book" not in cells and 'class="chip' not in h
          and f'id="dc-pd-p1-{tidx}" hidden>' in h and h.count('class="pday"') == h.count('" hidden>')
          and "onclick=\"var w=this.parentNode" in h and '<span class="ev">Cardio quiz</span>' in cells
          and "plansite" not in h and "Month &#8599;" not in h
          and "planweek:p1:next" in h and "planweek:p1:prev" in h and 'class="tb here"' in h)
    check("week: a day says what's left: done, behind (amber), to go today, new ahead; a quiz under its day",
          "&#10003;" in cells and '<span class="late">2<span class="w"> left</span></span>' in cells
          and '24<span class="w"> to go</span>' in cells and '38<span class="w"> new</span>' in cells
          and 'class="pc ev1"' in cells and cells.count("rest") == 2, cells)
    seen_day = board._plan_card_html(dict(base, focus=week[tidx + 1]["day"]))
    check("week: Show on my plan's day opens, the box on it (no Done: the week's always there)",
          f'id="dc-pd-p1-{tidx + 1}">' in seen_day and seen_day.count(" sel\"") == 1 and ">Done</a>" not in seen_day)
    check("week: a later day offers Open now, Skip it, Move…; a skipped date Undo skip (my dates later is Settings')",
          "plannow:p1:d" in h and "planskip:p1:d" in h and "planmove:p1:d" in h and "Undo skip" in h and "planshift" not in h)
    tue = h.split('id="dc-pd-p1-1"')[1].split('<div class="pday"')[0]
    check("week: a day's details have its dates whole: name, seen of its cards, its bar, Browse, the ones left; the day's Study",
          "<b>V&amp;B &lt;i&gt;</b>" in tue and "6 / 8" in tue and 'class="wbar"' in tue and "planbrowse:p1:b" in tue
          and "planleft:p1:b" in tue and f"planstudyday:p1:{week[1]['day']}" in tue and "planstudydate" not in tue
          and "planmove" not in tue)
    w2 = P.week_view(dict(doc, units=[dict(u, todo=[{"k": "watch", "t": "Lecture <14>", "url": "https://example.com/l14"}, {"k": "read", "t": "Ch 3"}])
                                      if u["id"] == "c" else u for u in doc["units"]]),
                     {"a": [40, 40, 40], "b": [8, 6, 8], "c": [42, 18, 42]}, "2026-10-07", mon)
    full = board._plan_card_html(dict(base, week=w2, quiz={"id": "q", "name": "Cardio quiz", "day": "2026-10-09", "open": 12}))
    wed = full.split(f'id="dc-pd-p1-{tidx}"')[1].split('<div class="pday"')[0]
    fri = full.split(f'id="dc-pd-p1-{tidx + 2}"')[1].split('<div class="pday"')[0].split('<div class="pn">')[0]
    check("week: and its authors' lines, a link opening in the browser by the line's key; its quiz by name (Study for it once, the row under the week)",
          "<b>&#9654; Watch</b>" in wed.replace("\u25b6", "&#9654;") and "Lecture &lt;14&gt;" in wed and "duecrew:duelink:p1:c:" in wed
          and "<b>Read</b> &middot; Ch 3" in wed and "for Cardio quiz" in wed
          and '<div class="pev"><span><b>Cardio quiz</b></span></div>' in fri and "planquiz" not in fri
          and full.count("planquiz:p1:q") == 1, wed + fri)
    check("crew: in words", "Crew: 5 done with Path Book 1" in h)
    moved = board._plan_card_html(dict(base, week_offset=1))
    check("week: moved, it says which, Today between the arrows, the details shut",
          "Week of 5 Oct" in moved and 'class="tb" onclick' in moved and "planweek:p1:0" in moved
          and " sel\"" not in moved and moved.count('class="pday"') == moved.count('" hidden>'))
    rest = board._plan_card_html(dict(base, session={"kind": "rest", "due": 212}))
    check("now: a rest day says no new cards", "Today is a rest day: reviews, and no new cards." in rest)
    taper = board._plan_card_html(dict(base, session={"kind": "taper", "due": 212}))
    check("now: so does the taper", "in its taper" in taper)
    late = {"uid": "b", "name": "V&B <i>", "more": 0, "left": 2, "uids": ["b"], "since": "2026-10-06", "days": 1}
    behind = board._plan_card_html(dict(base, status={"togo": 24, "behind": 2, "since": "Monday"}, behind=late,
                                        lines=[("behind", [("Path Book 1", True), (" was due Mon. 2 cards not seen yet.", False)])]))
    check("behind: round five's line says what's left today; plans, end to end: what's behind is its own line, "
          "with Behind… where Catch up… was; not a note as well",
          '<div class="pst"><span><b>24</b> to go today</span></div>' in behind
          and '<div class="pst pbh"><span class="late">Behind &middot; V&amp;B &lt;i&gt;, 2 left</span>' in behind
          and behind.count("planbehind:p1") == 1 and "plancatch:p1" not in behind
          and "was due Mon." not in behind and 'class="pn warn"' not in behind, behind)
    five = board._plan_card_html(dict(base, status={"togo": 0, "behind": 5}, behind=dict(late, left=5, more=1)))
    check("behind: nothing left today and nothing behind, no line; only behind, no 0 to go, and how many more",
          'class="pst"' not in board._plan_card_html(dict(base, status={"togo": 0, "behind": 0}))
          and "to go today" not in five and "Behind &middot; V&amp;B &lt;i&gt; and 1 more, 5 left" in five, five)
    catching = board._plan_card_html(dict(base, status={"togo": 24, "behind": 2, "since": "Monday"}, behind=late,
                                          catch={"extra": 2, "until": "Mon"}))
    check("behind: a catch-up running says so in its note, and the line isn't called behind",
          "<b>24</b> to go today</span>" in catching and "behind" not in catching.split('class="pst"')[1].split("</div>")[0]
          and "plancatch:p1" not in catching and "planbehind:p1" not in catching and "plancatchstop:p1" in catching)
    from due_crew import due as D
    lists = board.you_html({}, due=D.view("2026-10-07", [], [], {}), you={"tab": "plans", "plans": {"cards": [base]}})
    check("due on: the week is on the card whether Due's lists are on or off (Sam's pick A)",
          'class="pwk"' in lists and 'class="pwk"' in board.you_html({}, due=None, you={"tab": "plans", "plans": {"cards": [base]}}))
    paused = board._plan_card_html(dict(base, paused=True, sub="paused until Mon 12 Oct", session=None))
    check("now: paused, with Resume now", "paused until Mon 12 Oct" in paused and "No new cards while it&rsquo;s paused." in paused
          and "planresume:p1" in paused)
    ins = board._plan_card_html(dict(base, ins={"n": 12, "did": 10, "name": "Cardio <quiz>", "day": "2026-10-09"}))
    check("now: the next exam's cards at risk, from Insights, with Study (round five: no Insights ›, the tab beside it)",
          "12 cards</a> Anki won&rsquo;t show you before <b>Cardio &lt;quiz&gt;</b> on Fri 9" in ins
          and "duecrew:insbrowse:10:h" in ins and "duecrew:insstudy:10:h" in ins and "youins" not in ins, ins)
    check("now: none at risk, no line", "insstudy" not in board._plan_card_html(dict(base, ins={"n": 0, "did": 10})))
    notes = board._plan_card_html(dict(base, waiting=16, put_off=["Path Book 2"], change=[("Dre moved a date", False)]))
    check("notes: one at a time, the most pressing first", notes.count('class="pn') == 1 and "planok:p1" in notes)
    waits = board._plan_card_html(dict(base, waiting=16, status={"togo": 4, "behind": 9, "since": "Monday"}, behind=dict(late, left=9)))
    check("notes: one way a card: the Behind line has it, so the waiting note (and its Catch up…) goes",
          waits.count("planbehind:p1") == 1 and "plancatch:p1" not in waits and "new from earlier days waiting" not in waits
          and "new from earlier days waiting" in board._plan_card_html(dict(base, waiting=16)))
    plans = {"cards": [base], "offers": []}
    css = board.render({"entries": [], "labels": ["2026-10-07"], "tomorrow": "", "pending": []}, {"period": "today"}, 0,
                       plans=plans, you={"tab": "plans", "plans": plans})
    check("narrow: the seven days stay seven, their words and quiz names in the day's details",
          "#due-crew .pwk { grid-template-columns: 1fr; }" not in css
          and "#due-crew .pwk .pc .dow, #due-crew .pwk .pc .w, #due-crew .pwk .pc .ev { display: none; }" in css)


def _bingo_card(wk="2026-W36", needs=(1, 1, 1, 1, 1, 1, 1, 1), middle=None, squares=None):
    sq = squares or [{"id": f"q{i}", "fam": "often", "diff": "e", "icon": "✋", "title": f"Square {i}",
                      "rule": "Study on 1 day", "detail": "d", "type": "days", "params": {"days": 1}} for i in range(8)]
    return {"wk": wk, "squares": [dict(x, need=n) for x, n in zip(sq, needs)],
            "middle": dict({"id": "m", "group": "crew", "icon": "🎨", "name": "Picture day", "rule": "Everyone has an emoji",
                            "detail": "d", "type": "free", "params": {}, "goal": 1, "unit": ""}, **(middle or {}))}


def test_board_escapes_everything():
    """A crewmate whose every field is hostile: no tab ever makes it markup."""
    x = '<zz onmouseover="a()">'
    labels = [(TODAY - datetime.timedelta(days=i)).isoformat() for i in range(7)]
    day = {"studied": True, "reviews": 50, "studyTimeMs": 100000, "accuracy": 88.0, "streak": 3, "newCards": 2,
           "status": x, "emoji": x[:8], "room": {"host": x, "start": 0, "rounds": 2, "round": 25, "brk": 5}}
    bad = {"user_id": "u'<zz>", "name": x, "emoji": x[:8], "you": False, "paused": False, "last_updated": x,
           "exam_date": x, "status": x, "days": {labels[0]: day, labels[1]: day},
           "decks": [{"name": x, "mature": 5, "young": 2, "total": 10, "id": 1}]}
    me = dict(bad, user_id="sam", name="Sammy", you=True, emoji="", status="", exam_date="")
    base = {"entries": [me, bad], "labels": labels, "tomorrow": "", "pending": [(x, x)]}
    out = ""
    for period in ("today", "week", "decks", "squads", "plans"):
        try:
            out += board.render(base, {"period": period}, 0)
        except Exception as e:  # a field in a shape the board doesn't take is a test gap, not a pass
            out += f"RAISED {period} {e!r}"
    check("board: every tab keeps a hostile crewmate's fields as text", "<zz" not in out and "RAISED" not in out,
          [out[max(0, i - 80):i + 40] for i in [out.find("<zz")] if i >= 0] or out[out.find("RAISED"):][:200])


def test_bingo_escapes_everything():
    """Every word on the card and every name comes from the server: none of
    it is ever markup, on the Squads tab's card or the whole card."""
    from due_crew import bingo as B
    x = '<zz onmouseover="a()">'
    hostile = [{"id": f"q{i}", "fam": "often", "diff": "m", "icon": x[:8], "title": x, "rule": x, "detail": x,
                "type": "days", "params": {"days": 1}, "need": "half"} for i in range(8)]
    card = B.clean_card(_bingo_card(squares=hostile, middle={"icon": x[:8], "name": x, "rule": x, "detail": x,
                                                             "unit": x, "type": "people", "params": {"key": "dk"}, "goal": "half"}))
    rows = [{"user_id": u, "emoji": x[:8], "day": "2026-09-01", "joined": "2026-01-01",
             "play": {"wk": 202636, "s": 0b1111, "dk": 1}} for u in ("a", "b")] + [
            {"user_id": "old", "emoji": "", "day": "2026-09-01", "joined": "2026-01-01"}]
    ev = B.evaluate(card, rows)
    bv = {"card": card, "ev": ev, "names": {u: (x, x[:8]) for u in ("a", "b", "old")}, "me": "a", "squad": x,
          "squad_id": "s", "closest": B.closest(card, ev), "progress": [(False, x)] * 8, "new": True,
          "withheld": [], "today": "2026-09-01"}
    html = board.bingo_html(bv, {}) + board.bingo_card_html(bv) + board.bingo_card_html(dict(bv, new=False))
    check("bingo: the server's words and names are never markup", "<zz" not in html and "&lt;zz" in html, html[:0])


def test_bingo_rules():
    """3.6: each square from my own reviews, as marks passed on the way up;
    my play; a squad's card from its rows (bingo.ts: evaluate, restated)."""
    from due_crew import bingo as B
    D, T = datetime.date, datetime.datetime
    check("bingo: weeks are ISO weeks of Anki days, Monday to Sunday",
          B.week_key("2026-09-01") == "2026-W36" and B.week_labels("2026-09-03")[0] == "2026-08-31"
          and B.week_key("2027-01-01") == "2026-W53" and B.week_labels_for("2026-W36")[6] == "2026-09-06")
    week = B.week_labels("2026-09-03")          # Mon 31 Aug .. Sun 6 Sep; today is Thursday
    mon, tue, wed, thu = week[:4]
    at = lambda day, hm: T.combine(D.fromisoformat(day), datetime.time(*hm))
    times = {
        mon: [at(mon, (7, 30)), at(mon, (8, 20)), at(mon, (10, 0)), at(mon, (19, 0))],
        tue: [at(tue, (9, 0)), at(tue, (23, 11)), at(wed, (1, 30))],   # 1:30 after Tuesday: still Tuesday's night
        wed: [at(wed, (6, 59))] + [at(wed, (9, 0)) + datetime.timedelta(minutes=3 * i) for i in range(15)],
        thu: [at(thu, (12, 15))],
    }
    before = {(D(2026, 8, 31) - datetime.timedelta(days=i)).isoformat(): 100 for i in range(1, 31)}
    daily = dict(before, **{week[0]: 120, week[1]: 90, week[2]: 130, week[3]: 40})
    f = B.facts(week, thu, times, daily, {mon: 5, wed: 2}, zero={mon, tue}, newdone={mon}, rollover=4)
    P = lambda typ, **params: B.progress({"type": typ, "params": params}, f)
    check("bingo: before 8am on 2 days (Mon 7:30, Wed 6:59); after midnight isn't morning",
          P("window", **{"from": 0, "to": 8, "days": 2})[0] and not P("window", **{"from": 0, "to": 8, "days": 3})[0])
    check("bingo: after 10pm, 2 nights: 23:11 and 1:30 are both Tuesday's night, so one",
          P("window", **{"from": 22, "to": 24, "days": 1})[0] and not P("window", **{"from": 22, "to": 24, "days": 2})[0])
    check("bingo: Monday before noon, by weekday", P("window", **{"from": 0, "to": 12, "days": 1, "dow": [0]})[0]
          and not P("window", **{"from": 0, "to": 9, "days": 1, "dow": [3]})[0])
    check("bingo: a review at 11:11 (or 23:11)", P("minute", hm=["11:11", "23:11"])[0] and not P("minute", hm=["15:14"])[0])
    check("bingo: sittings an hour apart (Monday: 7:30 and 8:20 are one, then 10:00, then 19:00)",
          P("sittings", n=3, gap=60)[0] and not P("sittings", n=4, gap=60)[0] and P("sittings", n=4, gap=60)[1] == "Best day: 3 of 4 sittings")
    check("bingo: parts of one day", P("parts", parts=[[0, 12], [18, 24]], days=1)[0]
          and not P("parts", parts=[[0, 12], [12, 18], [18, 24]], days=1)[0])
    check("bingo: focus is the longest stretch without a 5-minute gap (Wednesday: 42 minutes)",
          P("focus", minutes=40, gap=5)[0] and P("focus", minutes=60, gap=5) == (False, "Longest: 42 of 60 min"))
    check("bingo: more than the day before (Mon 120 > Sun 100; Wed 130 > Tue 90), never 3 running",
          P("beat", run=2)[0] is False and P("beat", run=1)[0])
    check("bingo: 1.5x my usual (100 over 30 days: 150): 110 to go today",
          P("rel", x=1.5) == (False, "110 to go today (150 is 1.5× your usual)"))
    check("bingo: best in a month: Wednesday's 130 beats every day of the 30 before it", P("best", days=30)[0])
    check("bingo: new cards on days, new done, study days by weekday, due zero",
          P("newdays", days=2)[0] and not P("newdays", days=3)[0] and P("newdone", days=1)[0]
          and P("days", days=4)[0] and not P("days", days=1, dow=[5, 6])[0] and P("zero", days=2)[0] and not P("zero", days=3)[0])
    check("bingo: counts say how far: 2 of 3 days", P("newdays", days=3) == (False, "2 of 3 days"))
    check("bingo: a rule this version doesn't know asks for an update",
          B.progress({"type": "teleport", "params": {}}, f) == (False, "Update Due Crew to play this one")
          and not B.known({"type": "teleport"}))
    new = B.facts(week, thu, times, {thu: 10}, {}, rollover=4)
    check("bingo: until there's a week of history, my usual day is 50", new["usual"] == 50)

    card = _bingo_card(squares=[
        {"id": "a", "fam": "early", "diff": "m", "icon": "🌅", "title": "Early bird", "rule": "r", "detail": "d", "type": "window", "params": {"from": 0, "to": 8, "days": 2}},
        {"id": "b", "fam": "often", "diff": "e", "icon": "✋", "title": "Four days", "rule": "r", "detail": "d", "type": "days", "params": {"days": 4}},
        {"id": "c", "fam": "focus", "diff": "h", "icon": "🧘", "title": "Hour", "rule": "r", "detail": "d", "type": "focus", "params": {"minutes": 60, "gap": 5}},
        {"id": "d", "fam": "clean", "diff": "e", "icon": "🧹", "title": "Zero", "rule": "r", "detail": "d", "type": "zero", "params": {"days": 1}},
        {"id": "e", "fam": "wild", "diff": "m", "icon": "✨", "title": "11:11", "rule": "r", "detail": "d", "type": "minute", "params": {"hm": ["23:11"]}},
        {"id": "f", "fam": "fresh", "diff": "e", "icon": "🌱", "title": "New", "rule": "r", "detail": "d", "type": "newdays", "params": {"days": 1}},
        {"id": "g", "fam": "volume", "diff": "h", "icon": "🚀", "title": "Best", "rule": "r", "detail": "d", "type": "best", "params": {"days": 30}},
        {"id": "h", "fam": "spread", "diff": "e", "icon": "🔁", "title": "Two", "rule": "r", "detail": "d", "type": "teleport", "params": {}},
    ], wk="2026-W36")
    play = B.play(card, f, counts={"ch": 2, "zz": 5, "rm": 0})
    check("play: squares passed as bits (not the hour, not the unknown one), the days, early and late days, counts",
          play == {"wk": 202636, "s": 0b1111011, "d": 0b1111, "z": 0b11, "e8": 0b101, "n10": 0b10, "ch": 2}, play)
    quiet = B.play(card, f, hide=B.withheld({"share_time": False, "share_reviews": False}))
    check("play: with Reviews and Time switched off, the squares built from them stay home (the hour, best)",
          B.withheld({"share_time": False}) == {"focus"} and quiet["s"] == play["s"] & ~(1 << 6) and B.withheld({}) == set()
          and B.withheld({"show_up": True}) == set(B.SQUARE_TYPES) - set(B.SHOW_UP_TYPES))
    shy = B.play(card, f, show_up=True)
    check("play: show-up mode sends which days only: no times, no amounts",
          shy == {"wk": 202636, "s": 0b101010, "d": 0b1111, "z": 0b11}, shy)

    # a squad's card: bingo.ts evaluate, restated case for case
    row = lambda uid, p, **x: dict({"user_id": uid, "emoji": "", "day": "2026-09-01", "joined": "2026-01-01",
                                    "play": None if p is None else dict(p, wk=202636)}, **x)
    c = _bingo_card(needs=("half", 3, 2, 1, 1, 1, 1, 1))
    rows = [row("a", {"s": 0b111}), row("b", {"s": 0b011}), row("c", {"s": 0b001}), row("d", None),
            row("gone", None, day="2026-08-01")]
    e = B.evaluate(c, rows)
    check("evaluate: team squares need that many; half is half the active; the long-quiet don't count, "
          "nor someone studying on an add-on that can't play (they're told apart)",
          e["active"] == 3 and e["older"] == 1
          and [(len(q["who"]), q["need"], q["done"]) for q in e["squares"][:3]] == [(3, 2, True), (2, 3, False), (1, 2, False)], e)
    lag = B.evaluate(c, [row("a", {"s": 1}), row("b", None, play={"wk": 202635, "s": 0})])
    check("evaluate: a squadmate who plays but hasn't synced this week still counts toward the goals",
          lag["active"] == 2 and lag["older"] == 0 and lag["squares"][0]["need"] == 2, lag)
    big = [row(f"p{i}", {"s": 1 if i < 15 else 0}) for i in range(30)]
    two = [row("a", {"s": 0b10}), row("b", {"s": 0b10})]
    check("evaluate: half of a squad of 30 is 15, no cap; a need is never more than there are of you",
          B.evaluate(c, big)["squares"][0]["need"] == 15 and B.evaluate(c, big)["squares"][0]["done"]
          and B.evaluate(c, two)["squares"][1] == {"who": ["a", "b"], "need": 2, "done": True})
    check("evaluate: last week's play counts for nothing",
          not B.evaluate(c, [row("a", None, play={"wk": 202635, "s": 255})])["squares"][3]["done"])
    rows = [row("a", {"d": 0b1000001, "ch": 3, "z": 1}, emoji="🦊"), row("b", {"d": 0b0000001, "ch": 2}, emoji="🐙"),
            row("c", {"d": 0b1000000}, joined="2026-09-02")]
    M = lambda **m: B.evaluate(_bingo_card(middle=m), rows)["middle"]
    check("evaluate: the middle's kinds",
          M(type="day", params={"key": "d"}, goal="all")["done"] is False
          and M(type="day", params={"key": "d", "day": 6}, goal=2)["done"]
          and M(type="people", params={"key": "d"}, goal="all")["done"]
          and M(type="sum", params={"key": "ch"}, goal=5)["have"] == 5
          and M(type="sum", params={"key": "ch"}, goal=9)["goal"] == 9
          and M(type="people", params={"key": "z"}, goal=4)["goal"] == 3
          and M(type="emoji", params={}, goal="all")["have"] == 2
          and M(type="joined", params={}, goal=1)["done"])
    lined = B.evaluate(_bingo_card(), [row("a", {"s": 0b11000})])
    whole = B.evaluate(_bingo_card(), [row("a", {"s": 255})])
    check("evaluate: the middle row is a line; every square and the middle, all eight lines",
          lined["lines"] == 1 and lined["cells"] == [3, 4, 5] and whole["lines"] == 8)
    locked = B.evaluate(_bingo_card(middle={"type": "sum", "params": {"key": "ch"}, "goal": 99}), [row("a", {"s": 0b11000})])
    text = B.share_text(_bingo_card(), locked, "orca <b>")
    check("share: the grid in emoji, the middle locked until it's unlocked, no names",
          text.splitlines()[1:4] == ["⬜⬜⬜", "🟩🔒🟩", "⬜⬜⬜"] and "a" not in text.splitlines()[1] and "2 of 9" in text
          and B.closest(_bingo_card(middle={"type": "sum", "params": {"key": "ch"}, "goal": 99}), locked) == ["Picture day"], text)
    check("card: a card that isn't eight squares and a middle is no card; words bounded",
          B.clean_card({"wk": "2026-W36", "squares": [], "middle": {}}) is None
          and B.clean_card(dict(_bingo_card(), wk="36")) is None
          and len(B.clean_card(dict(_bingo_card(), squares=[dict(q, title="x" * 99) for q in _bingo_card()["squares"]]))["squares"][0]["title"]) == 28)


def test_bingo_board():
    """3.6: the card on the Squads tab and in the board's place: every
    server string escaped, laid out left inside Anki's <center>, its
    clicks wired, a square's details in the page."""
    from due_crew import bingo as B
    card = B.clean_card(_bingo_card(needs=("half", 1, 1, 2, 1, 1, 1, 1), middle={"name": "Picture <b>", "type": "emoji", "goal": "all"}))
    card["squares"][1]["title"] = "Early <i>"
    rows = [{"user_id": "sam", "emoji": "😺", "day": "2026-09-01", "joined": "2026-01-01", "play": {"wk": 202636, "s": 0b11}},
            {"user_id": "dre", "emoji": "", "day": "2026-09-01", "joined": "2026-01-01", "play": {"wk": 202636, "s": 0b1}}]
    ev = B.evaluate(card, rows)
    bv = {"card": card, "ev": ev, "progress": [(True, "Done")] + [(False, "1 of 4 days")] * 7, "me": "sam",
          "names": {"sam": ("Sammy", "😺"), "dre": ("Dre <x>", "")}, "squad": "orca <b>", "squad_id": "sq1",
          "new": True, "closest": B.closest(card, ev), "withheld": ["days"], "today": "2026-09-01"}
    full = board.bingo_html(bv, {})
    check("bingo: the card escapes the server's words and names",
          "Early &lt;i&gt;" in full and "Picture &lt;b&gt;" in full and "orca &lt;b&gt;" in full and "Dre &lt;x&gt;" in full
          and "<i>" not in full.split("</style>")[-1].replace("<i style", "").replace("<i></i>", ""), full[-1500:])
    check("bingo: laid out left inside Anki's <center>, its buttons from the reset, [hidden] hidden",
          "#due-crew .bg-card, #due-crew.bg-full, #due-crew .bg-row, #due-crew .bg-bar, #due-crew .bg-info { text-align: left; }" in full
          and 'id="due-crew" class="dc-frame bg-full"' in full and "#due-crew a.bg-a {" in full
          and "#due-crew button {" in full and "#due-crew [hidden] { display: none !important; }" in full)
    check("bingo: nine squares, a way back, Copy, and each square's details in the page",
          full.count('class="bg-sq') == 9 and "duecrew:bingoback" in full and "duecrew:bingocopy" in full
          and full.count('<div data-i="') == 10 and "You: done." in full and "You: 1 of 4 days" in full)
    check("bingo: a team square says how many of you, and so far", "2 of you" in full and "&#128101;" in full)
    check("bingo: a square my switches keep home still shows me my progress, and says it stays here",
          "keep yours on this computer" in full)
    check("bingo: while the squad loads, the card says so, not that there's none",
          "Fetching" in board.bingo_html(None, {}, loading=True) and "No card" not in board.bingo_html(None, {}, loading=True))
    check("bingo: the middle locked, with how far", "&#128274;" in full and "1 of 2" in full)
    small = board.bingo_card_html(bv)
    check("bingo: the Squads tab's card: the Monday line, and Open", "A new card" in small and "Picture &lt;b&gt;" in small
          and "duecrew:bingo" in small and small.count("<i") == 9)
    later = board.bingo_card_html(dict(bv, new=False))
    check("bingo: later in the week, how far and what's closest, never who's ahead",
          "of 9" in later and "away from bingo" in later and "middle" not in later and "Sammy" not in later)
    sv = {"state": "ok", "name": "orca", "rows": [], "people": 0, "day": "2026-09-01", "squads": [], "current": "sq1", "bingo": bv}
    tab = board._squads_html(sv, {})
    check("bingo: on the Squads tab, above the table", "bg-card" in tab and "bg-mini" in tab)
    check("bingo: no card yet, the full view says so and has its way back",
          "No card this week" in board.bingo_html(None, {}) and "duecrew:bingoback" in board.bingo_html(None, {}))


def test_bingo_end_to_end():
    """3.6: the card rides the day's first refresh and the squad fetch; my
    play rides the sync's squad row, worked out from my own collection;
    the board's clicks reach their handlers."""
    from due_crew import bingo as B, bingo_flow
    store, sam, squad = _squad_fixture()
    sid = squad["id"]
    dre = new_client(store, "dre", "Dre")
    dre.join_squad(sid, squad["code"])
    wk = B.week_key(TODAY.isoformat())
    store.bingo_cards[wk] = _bingo_card(wk=wk, needs=("half", 1, 1, 1, 1, 1, 1, 1))
    labels = [(TODAY - datetime.timedelta(days=i)).isoformat() for i in range(7)]
    n = len(store.log)
    sam.fetch_board(labels, with_decks=True)
    check("bingo: the day's first refresh brings the card, in the same one request",
          sam.session.get("bingo", {}).get("wk") == wk and len(store.log) == n + 1)
    del store.bingo_cards[wk]
    sam.fetch_board(labels)
    check("bingo: later refreshes keep the day's card", sam.session["bingo"]["wk"] == wk)
    store.bingo_cards[wk] = _bingo_card(wk=wk, needs=("half", 1, 1, 1, 1, 1, 1, 1))
    ok, _gone = _row_sync(dre, {"name": "Dre", "day": TODAY.isoformat(), "play": {"wk": B.wk_num(wk), "s": 1, "d": 2}}, [sid])
    data = sam.fetch_squad(sid, wk=wk)
    row = next(r for r in data["rows"] if r["user_id"] == "dre")
    check("bingo: play rides the squad row and comes back with the squad; the card too",
          ok and row["play"] == {"wk": B.wk_num(wk), "s": 1, "d": 2} and row["joined"] and data["bingo"]["wk"] == wk)
    check("bingo: a play the Worker wouldn't take isn't sent quietly: the sync fails",
          _row_sync(dre, {"name": "Dre", "play": {"s": 1}}, [sid])[0] is False)

    # my play from my own collection, at the sync (main thread)
    col = make_user_col([])
    conn = col.db.conn
    fakes.add_card(conn, 7, did=1)
    tue9 = int(datetime.datetime.combine(TODAY, datetime.time(9)).timestamp() * 1000)
    for i in range(3):
        fakes.add_review(conn, tue9 + i * 60000, cid=7)
    col.sched.due = {1: (0, 0)}
    tmp = tempfile.mkdtemp()
    saved = (bingo_flow.mw.col, bingo_flow._profile_files, bingo_flow._profile_key, bingo_flow.client)
    bingo_flow.mw.col = col
    bingo_flow._profile_files = lambda: tmp
    bingo_flow._profile_key = lambda: "p1"
    bingo_flow._mem.update(profile=None, data=None)
    bingo_flow.client = lambda: sam
    try:
        bingo_flow.bump("ch")
        bingo_flow.bump("ch")
        bingo_flow.bump("nope")
        play = bingo_flow.for_row({"squads": [{"id": sid}], "status": "coffee"})
        check("bingo: my play from my own reviews: Tuesday studied and due-zero, square 0 passed, my counts",
              play is not None and play["wk"] == B.wk_num(wk) and play["d"] == 0b10 and play["z"] == 0b10
              and play["s"] & 1 and play["ch"] == 2 and play["st"] == 1 and "nope" not in play, play)
        check("bingo: in no squad, or paused, no play", bingo_flow.for_row({"squads": []}) is None
              and bingo_flow.for_row({"squads": [{"id": sid}], "paused": True}) is None)
        saved_json = json.load(open(os.path.join(tmp, "bingo.json")))
        check("bingo: this week's record on this computer, started over each week",
              saved_json["wk"] == wk and saved_json["zero"] == [TODAY.isoformat()] and saved_json["counts"] == {"ch": 2})
        # a redraw since the sync: my squares against the new card, at once
        from due_crew.app import _state as st
        was_labels = st["labels"]
        st["labels"] = labels
        bingo_flow.for_row({"squads": [{"id": sid}]})
        redrawn = B.clean_card(_bingo_card(wk=wk, needs=("half", 1, 1, 1, 1, 1, 1, 1)))
        redrawn["squares"] = redrawn["squares"][1:] + redrawn["squares"][:1]  # square 0 now last
        sam.session["bingo"] = redrawn
        me_row = {"user_id": "sam", "emoji": "", "day": TODAY.isoformat(), "joined": "2026-01-01", "play": st["bingo_mine"]["play"]}
        v = bingo_flow.view({"state": "ok", "rows": [me_row], "name": "s", "current": sid}, {"squads": [{"id": sid}]})
        check("bingo: a card redrawn since the sync: my stamps move with their squares, now",
              v is not None and st["bingo_mine"]["ids"] == [q["id"] for q in redrawn["squares"]]
              and st["bingo_mine"]["play"] is not None and st["bingo_mine"]["progress"] is not None)
        st["labels"] = was_labels
    finally:
        bingo_flow.mw.col, bingo_flow._profile_files, bingo_flow._profile_key, bingo_flow.client = saved

    # the board's clicks, as the board sends them
    import due_crew as dc
    from aqt.deckbrowser import DeckBrowser
    if "aqt.reviewer" not in sys.modules:
        sys.modules["aqt.reviewer"] = types.SimpleNamespace(Reviewer=type("Reviewer", (), {}))
    conf = {"period": "squads", "squads": [{"id": sid, "code": squad["code"], "name": "orca"}]}
    copied, swaps = [], []
    saved = (dc._swap, dc.cfg, dc.save_cfg, dc._fetch_squad, dc.copy_text, dc._bingo_view, bingo_flow.seen)
    dc._swap = lambda c, focus=None: swaps.append(1)
    dc.cfg = lambda: conf
    dc.save_cfg = lambda c, **k: None
    dc._fetch_squad = lambda force=False: None
    dc.copy_text = copied.append
    card = B.clean_card(store.bingo_cards[wk])
    dc._bingo_view = lambda c: {"card": card, "ev": B.evaluate(card, []), "squad": "orca"}
    bingo_flow.seen = lambda: None
    try:
        send = lambda m: dc._on_js(False, as_board("duecrew:" + m), DeckBrowser())
        send("bingo")
        opened = dc._state.get("bingo_open")
        send("bingocopy")
        send("bingoback")
        back = dc._state.get("bingo_open")
        send("bingo")
        send("period:today")
        check("bingo: Open, Copy and back reach their handlers; another tab closes the card",
              opened is True and back is False and dc._state.get("bingo_open") is False
              and copied and copied[0].startswith("orca · squad bingo") and len(swaps) >= 4, (opened, back, copied))
    finally:
        dc._swap, dc.cfg, dc.save_cfg, dc._fetch_squad, dc.copy_text, dc._bingo_view, bingo_flow.seen = saved
        dc._state["bingo_open"] = False


def test_crew_picker_v380():
    """3.8.0 (Sam): Today and Week are one Crew tab with a picker, as a squad
    is picked on the Squads tab (and Decks with them, the board being my
    people: Crew and Squads). The Crew pill goes back to the last one
    picked; show-up mode has This week (one view for both) and Decks."""
    import re as _re
    labels = [(TODAY - datetime.timedelta(days=i)).isoformat() for i in range(7)]
    data = {"entries": [{"user_id": "me", "name": "Sam", "you": True, "paused": False, "last_updated": "",
                         "days": {labels[0]: {"reviews": 5, "studied": True}}}], "labels": labels, "tomorrow": ""}
    pills = lambda h: _re.findall(r'<a class="dc-pill[^"]*"[^>]*period:([a-z]+)[^>]*>([^<]+)</a>', h)
    today = board.render(data, {"period": "today"}, 0)
    week = board.render(data, {"period": "week"}, 0)
    check("crew: two pills, Crew on for Today and for Week",
          [x[1] for x in pills(today)] == ["Crew", "Squads"]
          and 'dc-pill on" href="#" onclick="pycmd(\'duecrew:period:today' in today
          and 'dc-pill on" href="#" onclick="pycmd(\'duecrew:period:week' in week, pills(today))
    pick = lambda h: _re.sub(r' data-t="[^"]*"', "", _re.search(r'<div class="dc-sw">(.*?)</div>', h).group(1))  # (3.9.10: each word's bold room)
    check("crew: the picker, Today picked, then Week picked",
          ('<a class="on" href="#" onclick="pycmd(\'duecrew:period:today|' + KK + '\'); return false;">Today</a>') in pick(today)
          and ('<a href="#" onclick="pycmd(\'duecrew:period:week|' + KK + '\'); return false;">Week</a>') in pick(today)
          and ('<a href="#" onclick="pycmd(\'duecrew:period:decks|' + KK + '\'); return false;">Decks</a>') in pick(today)
          and ('<a class="on" href="#" onclick="pycmd(\'duecrew:period:week|' + KK + '\'); return false;">Week</a>') in pick(week))
    sq = board.render(data, {"period": "squads", "crew_view": "decks"}, 0)
    check("crew: from Squads, the Crew pill goes back to the last view picked (Decks too, since 3.8.0)",
          ("decks", "Crew") in pills(sq) and "period:today'); return false;\">Today</a>" not in sq)
    decks = board.render(data, {"period": "decks", "crew_view": "decks"}, 0)
    check("crew: Decks is Crew's third view, picked", ("decks", "Crew") in pills(decks)
          and ('<a class="on" href="#" onclick="pycmd(\'duecrew:period:decks|' + KK + '\'); return false;">Decks</a>') in pick(decks))
    gone = board.render(data, {"period": "squads", "crew_view": "decks", "hidden_tabs": ["decks"]}, 0)
    check("crew: Decks hidden in Settings, the pill goes to Today and the picker has two",
          ("today", "Crew") in pills(gone) and "period:decks" not in gone)
    js = open(os.path.join(REPO, "site", "public", "app.js"), encoding="utf-8").read()
    check("twin: the site's board is Crew and Squads, Crew's views Today, Week and Decks (This week and Decks in show-up mode)",
          'const tabs = [["crew", "Crew"], ["squads", "Squads"]];' in js
          and '[["today", "This week"], ["decks", "Decks"]] : [["today", "Today"], ["week", "Week"], ["decks", "Decks"]]' in js
          and [v for v in board.crew_views()] == [("today", "Today"), ("week", "Week"), ("decks", "Decks")]
          and [v for v in board.crew_views(True)] == [("today", "This week"), ("decks", "Decks")]
          and '["plans", "Plans"]' not in js)
    mode = board.render(data, {"period": "week", "show_up": True}, 0)
    check("crew: show-up mode, This week (one view for Today and Week) and Decks",
          "period:week'); return false;\">Week</a>" not in mode and ">Today</a>" not in mode and ">Crew</a>" in mode
          and ('<a class="on" href="#" onclick="pycmd(\'duecrew:period:today|' + KK + '\'); return false;">This week</a>') in pick(mode)
          and "period:decks" in pick(mode))
    import due_crew as dc
    from aqt.deckbrowser import DeckBrowser
    conf = {"period": "today"}
    saved = (dc._swap, dc.cfg, dc.save_cfg, dc._fetch_squad, dc._fetch_decks)
    dc._swap = lambda c, focus=None: None
    dc.cfg = lambda: conf
    dc.save_cfg = lambda c, **k: None
    dc._fetch_squad = dc._fetch_decks = lambda *a, **k: None
    try:
        dc._on_js(False, as_board("duecrew:period:week"), DeckBrowser())
        week_set = (conf.get("period"), conf.get("crew_view"))
        dc._on_js(False, as_board("duecrew:period:decks"), DeckBrowser())
        decks_set = (conf.get("period"), conf.get("crew_view"))
        dc._on_js(False, as_board("duecrew:period:squads"), DeckBrowser())
        check("crew: the picker's click reaches its handler and is remembered; Squads keeps it",
              week_set == ("week", "week") and decks_set == ("decks", "decks")
              and conf.get("period") == "squads" and conf.get("crew_view") == "decks", (week_set, decks_set, conf))
        dc._on_js(False, as_board("duecrew:period:plans"), DeckBrowser())
        check("crew: 3.8.0, an old board's Plans tab is no period", conf.get("period") == "squads")
    finally:
        dc._swap, dc.cfg, dc.save_cfg, dc._fetch_squad, dc._fetch_decks = saved


def test_you_bubble_v380():
    """3.8.0 (Sam): Due and Crew split. The board is my people (Crew:
    Today, Week, Decks; Squads); what's mine is the You bubble over it:
    Today, Upcoming and Later (Due's lists, when on), then Plans and
    Insights, each hideable in Settings. A saved Plans tab opens there.
    Every click reaches its handler."""
    import due_crew as dc
    from aqt.deckbrowser import DeckBrowser
    from due_crew import due as DUE, due_flow, team_flow, plan_flow
    from due_crew.app import _state
    labels = [(TODAY - datetime.timedelta(days=i)).isoformat() for i in range(7)]
    data = {"entries": [{"user_id": "me", "name": "Sam", "you": True, "paused": False, "last_updated": "",
                         "days": {labels[0]: {"reviews": 5, "studied": True}}}], "labels": labels, "tomorrow": ""}
    dv = DUE.view(labels[0], [], DUE.clean_items([{"id": "item01", "t": "Read <b>ch 3</b>", "d": labels[0], "done": "", "at": labels[0]}]), {})
    plans = {"cards": [{"id": "p1", "title": "Block <b>", "sub": "week 1 of 4", "rows": [], "lines": []}], "offers": []}
    tabs = lambda h: re.findall(r"duecrew:duetab:([a-z]+)", h.split('class="dc-sheet"')[0])
    html = board.render(data, {"period": "today"}, 0, plans=plans, due=dv, you={"tab": "today", "plans": plans})
    check("you: over the board, Due's lists then Plans and Insights",
          tabs(html) == ["today", "upcoming", "plans", "insights"] and 'class="du-tabs du-more"' in html
          and html.index('class="du"') < html.index('class="dc-sheet"') and "dc-split" in html, tabs(html))
    check("you: Today's list, escaped; the board under it is Crew and Squads",
          "Read &lt;b&gt;ch 3&lt;/b&gt;" in html and "<b>ch 3" not in html and "period:squads" in html
          and "period:plans" not in html and "0 of 1 done" in html)
    ph = board.render(data, {"period": "today"}, 0, plans=plans, due=dv, you={"tab": "plans", "plans": plans})
    check("you › plans: the plan on it, Due's count not beside it",
          "Block &lt;b&gt;" in ph and "<b>Block <b>" not in ph and "0 of 1 done" not in ph and "Read &lt;b&gt;" not in ph)
    hid = board.render(data, {"period": "today", "hidden_tabs": ["plans"]}, 0, plans=plans, due=dv,
                       you={"tab": "plans", "plans": plans})
    check("you: a tab hidden in Settings is gone, and a saved one falls back to Today",
          tabs(hid) == ["today", "upcoming", "insights"] and "Block &lt;b&gt;" not in hid and "Read &lt;b&gt;" in hid)
    off = board.render(data, {"period": "today", "due_show": False}, 0, plans=plans, due=None, you={"tab": "today", "plans": plans})
    check("you: Due off, Plans and Insights still there, Plans first", tabs(off) == ["plans", "insights"]
          and "Block &lt;b&gt;" in off and "Hide &#9652;" in off)
    folded = board.render(data, {"period": "today"}, 0, plans=plans, due=None, you={"tab": "plans", "plans": plans, "folded": True})
    check("you: Due off and folded, one line naming what's in it, with Show",
          "<b>Plans &middot; Insights</b>" in folded and "Show &#9662;" in folded and "Block" not in folded)
    none = board.render(data, {"period": "today", "hidden_tabs": ["plans", "insights"]}, 0, plans=plans, due=None,
                        you={"tab": "plans", "plans": plans})
    check("you: Due off and both hidden, no bubble", "duetab" not in none and "duefold" not in none)
    check("you: the old render (no you) is Due alone", "duetab:plans" not in board.render(data, {"period": "today"}, 0, due=dv))
    # 3.8.0, refined: calmer, nothing lost
    lb0 = labels[0]
    tm = (TODAY + datetime.timedelta(days=1)).isoformat()
    dates = [{"pid": "p1", "uid": "u1", "plan": "Big Step 1", "name": "Renal <1>", "opens": lb0, "seen": 3, "total": 9, "counted": True,
              "parts": [["Video Series", 1, 4], ["Path Book", 2, 5]],
              "topics": [["Video Series", [["Acid base", 0]]], ["Path Book", [["Kidney <b>", 1]]], ["Search", [["tag:x", 2]]]]},
             {"pid": "p1", "uid": "u0", "plan": "Big Step 1", "name": "Old", "opens": (TODAY - datetime.timedelta(days=2)).isoformat(),
              "seen": 0, "total": 4, "counted": True},
             {"pid": "p1", "uid": "u2", "plan": "Big Step 1", "name": "Heart", "opens": tm, "seen": 0, "total": 6}]
    dv2 = DUE.view(lb0, dates, [], {}, events=[{"day": tm, "name": "Quiz <q>", "plan": "Big Step 1"}])
    th = board._due_html(dv2)
    check("refined: a date's topics on their resource's row; what has no resource stays on its own line",
          "<b>Video Series</b> &middot; <a class=\"tp dc-tpn\"" in th and "Kidney &lt;b&gt;</a>" in th and "<b>Kidney" not in th
          and "duecrew:plantopicstudy:p1:u1:1" in th and "<b>Search</b> &middot; <a" in th and "Video Series</b> &middot; <a" in th
          and th.count("Video Series") == 1, th[:3000])
    up = board._due_html(dict(dv2, tab="upcoming"))
    check("simpler: Today ends with its list; tomorrow and the exam are Upcoming's, the exam escaped",
          "du-next" not in th and "Tomorrow:" not in th and "Quiz" not in th and "Upcoming &rsaquo;" not in th
          and "Heart" in up and "Quiz &lt;q&gt;" in up and "Quiz <q>" not in up)
    check("simpler: no Later tab while Later is empty; a saved Later falls back to Today",
          "duetab:later" not in th and "duetab:later" not in board._due_html(dict(dv2, tab="later"))
          and ('class="on" onclick="pycmd(\'duecrew:duetab:today|' + KK + '\')') in board._due_html(dict(dv2, tab="later")))
    dv3 = DUE.view(lb0, dates, [{"id": "item01", "t": "Some day", "d": "", "done": False}], {}, tab="later")
    l3 = board._due_html(dv3)
    check("simpler: Later shows, with its count, once it holds something",
          ">Later 1</a>" in l3 and "Some day" in l3 and ('class="on" onclick="pycmd(\'duecrew:duetab:later|' + KK + '\')') in l3, l3[:1500])
    check("refined: Behind is Today's alone", "du-sec warn" in th and "du-sec warn" not in up and "Old" not in up)
    bh = board.render(dict(data, pending=["Jules"]), {"period": "today"}, 0, due=dv2, plans=plans, you={"tab": "today", "plans": plans})
    check("refined: the box's tabs are words, Hide a word", 'class="du-tabs du-more"' in bh and "border: 1px solid var(--dc-line);\n"
          "      border-radius: 99px; padding: 2px 10px" not in bh and ">Hide &#9652;</a>" in bh)
    foot = bh.split('class="dc-foot"')[1]
    # 3.9.10 (Sam: "I've been meaning to redo the bottom"): three words, each saying what it opens
    words = re.findall(r'<a [^>]*onclick="pycmd\(\'duecrew:([a-z]+)\|[^>]*>([^<]+)</a>', foot.split('class="sp"')[0])
    check("the foot: Friends opens the Friends window, Scrapbook the scrapbook, Share my stats the share menu; no pill, no room, no Crew menu; who's waiting stays",
          words[:3] == [("friends", "Friends"), ("scrapbook", "Scrapbook"), ("sharemenu", "Share my stats")] and 'class="pb' not in foot
          and "Open a room" not in foot and ">Crew</a>" not in foot and 'class="warn"' in foot and "1 waiting" in foot, words)
    css = board.render(data, {"period": "today"}, 0, due=dv2, plans=plans, you={"tab": "today", "plans": plans})
    check("simpler: the box is a card like the board's, no border of its own; one underline for every word tab",
          "#due-crew .du { text-align: left; border-radius: 12px; padding: 12px 18px;" in css
          and "border: 1.5px solid var(--dc-accent)" not in css.split("DUE_CSS")[0].split("#due-crew .du {")[1][:120]
          and "box-shadow: inset 0 -2px var(--dc-accent)" in css and "1px dotted currentColor" not in css)
    check("simpler: Behind, then today's rows, no Today label under the Today tab", 'du-sec">Today<' not in th)
    # the glue: only the tab on screen is worked out
    calls = []
    saved = (team_flow.plan_lines, team_flow.you_view, plan_flow.morning_opened, dc.mw.col, due_flow._today)
    due_flow._today = lambda: labels[0]
    team_flow.plan_lines = lambda cards: calls.append("plans")
    team_flow.you_view = lambda c: calls.append("insights") or {"decks": []}
    plan_flow.morning_opened = lambda: {"n": 4}
    dc.mw.col = object()
    try:
        you = dc._you({"due_tab": "insights"}, dv, plans)
        check("glue: Insights on screen, only it is worked out", calls == ["insights"] and you["insights"] == {"decks": []})
        calls.clear()
        you = dc._you({"due_tab": "plans"}, dv, plans)
        check("glue: Plans on screen, each plan's line; Due on, the morning's line stays under Today",
              calls == ["plans"] and not you.get("opened"))
        calls.clear()
        you = dc._you({"due_tab": "plans"}, None, plans)
        check("glue: Due off, the morning's line comes to Plans", you.get("opened") == {"n": 4})
        calls.clear()
        dc._you({"due_tab": "today"}, dv, plans)
        dc._you({"due_tab": "insights", "hidden_tabs": ["insights"]}, dv, plans)
        dc._you({"due_tab": "plans", "due_fold": {"day": labels[0], "folded": True}}, None, plans)
        check("glue: Today, a hidden tab, or folded: nothing worked out", calls == [], calls)
    finally:
        team_flow.plan_lines, team_flow.you_view, plan_flow.morning_opened, dc.mw.col, due_flow._today = saved
    # the clicks
    conf = {"period": "today", "hidden_tabs": ["plans", "decks"], "due_tab": "today",
            "due_fold": {"day": labels[0], "folded": True}}
    saved = (dc._swap, dc.cfg, dc.save_cfg, due_flow.cfg, due_flow.save_cfg, due_flow._swap, due_flow._today)
    dc._swap = due_flow._swap = lambda c, focus=None: None
    dc.cfg = due_flow.cfg = lambda: conf
    dc.save_cfg = due_flow.save_cfg = lambda c, **k: None
    due_flow._today = lambda: labels[0]
    try:
        dc._on_js(False, as_board("duecrew:duetab:plans"), DeckBrowser())
        check("duetab: a tab's click picks it, opens the bubble, and shows a hidden one again",
              conf["due_tab"] == "plans" and conf["due_fold"] == {"day": labels[0], "folded": False}
              and conf["hidden_tabs"] == ["decks"], conf)
        dc._on_js(False, as_board("duecrew:duetab:insights"), DeckBrowser())
        check("duetab: Insights too", conf["due_tab"] == "insights")
        dc._on_js(False, as_board("duecrew:duetab:squads"), DeckBrowser())
        check("duetab: not a tab of the bubble, nothing", conf["due_tab"] == "insights")
        conf["due_show"] = False
        dc._on_js(False, as_board("duecrew:duefold"), DeckBrowser())
        check("duefold: Due off, Hide folds the bubble for today", conf["due_fold"] == {"day": labels[0], "folded": True})
        dc._on_js(False, as_board("duecrew:duefold"), DeckBrowser())
        check("duefold: and Show opens it", conf["due_fold"] == {"day": labels[0], "folded": False})
        # 3.8.0: an older install's saved Plans tab, and a hidden Week
        conf.clear()
        conf.update(period="plans", hidden_tabs=["week", "plans", "today", "squads"])
        dc._settle_tabs()
        check("settle: a saved Plans tab opens in the bubble, Crew's Today under it; only hideable tabs stay hidden",
              conf == {"period": "today", "due_tab": "plans", "hidden_tabs": ["plans", "squads"]}, conf)
    finally:
        dc._swap, dc.cfg, dc.save_cfg, due_flow.cfg, due_flow.save_cfg, due_flow._swap, due_flow._today = saved
    # Settings: what the board and the bubble show
    st = board._settings_board({"hidden_tabs": ["plans"]})
    check("settings: Tabs, Crew always, then Decks, Squads, Plans and Insights, each a switch; Today's lists on Study",
          '<button class="st-pill on" disabled aria-pressed="true">Crew</button>' in st
          and "settabs:plans:1" in st and "settabs:decks:0" in st and "settabs:squads:0" in st
          and "settabs:insights:0" in st and "Today, Upcoming, Later" not in st
          and "Today, Upcoming, Later" in board._settings_study({}))
    from due_crew import settings_model
    check("settings: the hideable tabs are the board's", set(settings_model.HIDEABLE) == {k for k, _l in board.HIDEABLE_TABS})
    # Crew › Decks: my own deck, to how it's sticking
    me = dict(data["entries"][0], decks=[{"name": "Step <1>", "sig": "s", "total": 10, "seen": 5, "mature": 2, "open": 6}])
    dk = board.render(dict(data, entries=[me]), {"period": "decks"}, 0, sticking={"Step <1>": 10})
    check("decks: no How it's sticking beside a deck's name (3.9.10: Insights has it)", "youins" not in dk and "sticking" not in dk
          and "Step &lt;1&gt;" in dk)
    check("decks: none for a deck Insights doesn't have", "youins" not in board.render(dict(data, entries=[me]), {"period": "decks"}, 0))
    _state["labels"] = []


def test_bingo_pool_plays():
    """Every square and middle the migrations seed is one this add-on plays:
    none shows "Update Due Crew to play" on a card drawn from it, and a
    streak's words say days in a row."""
    import glob
    import re as _re
    from due_crew import bingo as B
    pool = {}
    for path in sorted(glob.glob(os.path.join(REPO, "worker", "migrations", "*.sql"))):
        for line in open(path, encoding="utf-8"):
            m = _re.search(r"VALUES \('([a-z0-9]+)', '(square|middle)', '(.*)', [01], 0\)", line) \
                or _re.search(r"SET json = '(.*)' WHERE id = '([a-z0-9]+)'", line)
            if not m:
                continue
            if line.lstrip().startswith("UPDATE"):
                raw, eid = m.group(1), m.group(2)
                kind = pool[eid][0]
            else:
                eid, kind, raw = m.group(1), m.group(2), m.group(3)
            pool[eid] = (kind, json.loads(raw.replace("''", "'")))
    check("pool: the migrations seed at least 40 entries", len(pool) > 40, len(pool))
    D, T = datetime.date, datetime.datetime
    week = B.week_labels("2026-09-04")
    times = {lb: [T.combine(D.fromisoformat(lb), datetime.time(h)) for h in (7, 12, 19)] for lb in week[:5]}
    f = B.facts(week, week[4], times, {lb: 80 for lb in week[:5]}, {lb: 3 for lb in week[:5]},
                zero=set(week[:5]), newdone=set(week[:5]), rollover=4)
    bad = []
    for eid, (kind, e) in pool.items():
        if kind == "square":
            sq = B.clean_card({"wk": "2026-W36", "squares": [dict(e, id=eid)] * 8,
                               "middle": {"type": "free"}})["squares"][0]
            done, words = B.progress(sq, f)
            if not B.known(sq) or "Update" in words or (sq["params"].get("row") and not done and "in a row" not in words):
                bad.append((eid, words))
        elif e.get("type") not in B.MIDDLE_TYPES:
            bad.append((eid, e.get("type")))
    check("pool: every seeded square and middle is one this add-on plays", not bad, bad)


def test_bingo_scales_and_streaks():
    """3.6.1: team squares and the middle are shares of the squad (at least
    2, never more than there are), so a bigger squad needs more of you;
    streak squares want that many days in a row (bingo.ts: the same)."""
    from due_crew import bingo as B
    check("shares: half, a third, a quarter of the active, at least 2",
          [B.how_many("half", n) for n in (1, 2, 3, 8, 20, 40)] == [1, 2, 2, 4, 10, 20]
          and [B.how_many("third", n) for n in (1, 2, 3, 8, 20, 40)] == [1, 2, 2, 3, 7, 14]
          and [B.how_many("quarter", n) for n in (1, 2, 3, 8, 20, 40)] == [1, 2, 2, 2, 5, 10]
          and B.how_many("all", 7) == 7 and B.how_many(3, 2) == 2)
    card = B.clean_card(_bingo_card(needs=("half", "third", "quarter", 1, 1, 1, 1, 1),
                                    middle={"type": "people", "params": {"key": "dk"}, "goal": "third"}))
    check("card: shares come through; an unknown need is one person", [q["need"] for q in card["squares"][:4]] == ["half", "third", "quarter", 1]
          and B.clean_card(_bingo_card(needs=("lots", 1, 1, 1, 1, 1, 1, 1)))["squares"][0]["need"] == 1)
    row = lambda uid, p: {"user_id": uid, "emoji": "", "day": "2026-09-01", "joined": "2026-01-01", "play": dict(p, wk=202636)}
    nine = [row(f"u{i}", {"s": (0b11 if i < 4 else 0b1) | (0b100 if i < 2 else 0), "dk": 1 if i < 3 else 0}) for i in range(9)]
    e = B.evaluate(card, nine)
    check("evaluate: a squad of 9: half is 5, a third 3, a quarter 3; the middle a third (3 sharing: done)",
          [(q["need"], q["done"]) for q in e["squares"][:3]] == [(5, True), (3, True), (3, False)]
          and e["middle"] == {"have": 3, "goal": 3, "done": True, "known": True}, e)
    lag3 = B.evaluate(card, [nine[0], {"user_id": "o1", "emoji": "", "day": "2026-09-01", "joined": "2026-01-01"},
                             {"user_id": "o2", "emoji": "", "day": "2026-09-01", "joined": "2026-01-01"}])
    check("evaluate: a share counts everyone studying: 1 playing and 2 on an older add-on still needs 2, not 1",
          lag3["active"] == 1 and lag3["older"] == 2 and [q["need"] for q in lag3["squares"][:3]] == [2, 2, 2], lag3)
    board_html = board.bingo_html({"card": card, "ev": e, "names": {}, "me": "u0", "squad": "s", "closest": []}, {})
    check("board: a team square says how many, as a number", "5 of you" in board_html and "3 of you" in board_html
          and "a third of you" not in board_html)

    D, T = datetime.date, datetime.datetime
    week = B.week_labels("2026-09-04")          # Mon 31 Aug .. Fri 4 Sep today
    at = lambda day, h: T.combine(D.fromisoformat(day), datetime.time(h))
    times = {week[0]: [at(week[0], 7)], week[1]: [at(week[1], 7)], week[2]: [at(week[2], 12)],
             week[3]: [at(week[3], 7)], week[4]: [at(week[4], 7)]}
    f = B.facts(week, week[4], times, {lb: 5 for lb in week[:5]}, {}, zero={week[0], week[1], week[3]}, rollover=4)
    P = lambda typ, **p: B.progress({"type": typ, "params": p}, f)
    check("streak: before 8am on 4 days, but at most 2 in a row (Wednesday broke it)",
          P("window", **{"from": 0, "to": 8, "days": 4})[0]
          and P("window", **{"from": 0, "to": 8, "days": 3, "row": True}) == (False, "2 of 3 days in a row")
          and P("window", **{"from": 0, "to": 8, "days": 2, "row": True})[0])
    check("streak: due zero Mon, Tue, Thu is 2 in a row; study 5 days in a row",
          P("zero", days=2, row=True)[0] and not P("zero", days=3, row=True)[0] and P("days", days=5, row=True)[0])
    check("card: row survives cleaning (a true/false, nothing else)",
          B.clean_card(_bingo_card(squares=[dict(q, params={"days": 2, "row": True}) for q in _bingo_card()["squares"]]))
          ["squares"][0]["params"] == {"days": 2, "row": True})


def test_account_survives_a_reset_config():
    """3.6.1: a reinstall into another folder starts from the default config,
    while user_files (and the session, which remembered the account save it
    had seen) survive: the add-on thought it was up to date, kept the
    defaults, and lost the squads, emoji and accent. The config now
    remembers its own save; one that doesn't takes the account's. And the
    squads I'm in come back from the server's membership."""
    from due_crew import account, squads as SQ, app as appmod
    from due_crew.app import _state
    doc = {"at": "2026-09-28T10:00:00.000000Z",
           "settings": {"squads": [{"id": "sq1", "code": "ABCD2345", "name": "orca", "founder": "x"}],
                        "emoji": "🦊", "accent": "rose"}}
    box = {"cfg": {"squads": [], "emoji": "", "accent": "green"}}  # the defaults, after the reset
    saved = (account.cfg, appmod.save_cfg, account.client, appmod.swap)
    cl = types.SimpleNamespace(session={"settings_seen": doc["at"], "settings_dirty": True,
                                        "settings_local_at": "2026-09-29T00:00:00Z"},
                               _save_session=lambda: None, signed_in=True)
    account.cfg = lambda: dict(box["cfg"])
    appmod.save_cfg = lambda c, from_account=False: box.update(cfg=dict(c))
    account.client = lambda: cl
    appmod.swap = None
    try:
        account._pulled((doc, 200))
        c = box["cfg"]
        check("reset config: takes the account's squads, emoji and accent, though the session had seen that save",
              c["squads"] and c["squads"][0]["id"] == "sq1" and c["emoji"] == "🦊" and c["accent"] == "rose"
              and c[account.SEEN_KEY] == doc["at"], c)
        box["cfg"] = dict(c, emoji="🐙")
        account._pulled((doc, 200))
        check("a config that holds that save keeps its own changes", box["cfg"]["emoji"] == "🐙")
    finally:
        account.cfg, appmod.save_cfg, account.client, appmod.swap = saved

    saved = (SQ.cfg, SQ.save_cfg)
    box = {"cfg": {"squads": [{"id": "sq1", "code": "ABCD2345", "name": "orca", "founder": "x"}]}}
    SQ.cfg = lambda: dict(box["cfg"])
    SQ.save_cfg = lambda c: box.update(cfg=c)
    _state["squads_left"] = {"sqLeft"}
    try:
        SQ.heal_squads([{"id": "sq1", "name": "orca", "founder": "x"}, {"id": "sq2", "name": "ms2", "founder": "y"},
                        {"id": "sqLeft", "name": "old", "founder": "z"}, {"id": "sqGone", "name": "g", "founder": "z"}],
                       gone=["sqGone"])
        ids = [q["id"] for q in box["cfg"]["squads"]]
        check("squads heal: the one the server has and the config lost comes back (no code); never one I just left or one the sync said I'm out of",
              ids == ["sq1", "sq2"] and box["cfg"]["squads"][1]["code"] == "" and box["cfg"]["squads"][0]["code"] == "ABCD2345", ids)
    finally:
        SQ.cfg, SQ.save_cfg = saved
        _state["squads_left"] = set()


def test_crew_menu_pictures():
    """3.7.1, H3: Crew ▾ is people, Share ▾ everything you post (as text,
    then as a picture), and a handler for every key either can offer."""
    text = srcs.glue_src()
    for fn, nxt, keys in (
            ("def _share_menu", "def open_friends",
             {k for show_up in (False, True) for _l, k in board.share_menu_items(show_up, True) if _l}),):
        run = text[text.index(fn):text.index(nxt)]
        handled = set(re.findall(r'"([a-z]+)": lambda', run))
        check(f"{fn[4:]}: every key handled", keys <= handled, sorted(keys - handled))
    full = board.share_menu_items(False, True)
    check("share menu: as text, then as a picture, year and all time made here (3.8.0)",
          [l or k for l, k in full] == ["As text", "My day", "Our week", "The squad's day", "As a picture",
                                        "My day…", "My week…", "My year…", "All time…"]
          and "head.setEnabled(False)" in text
          and 'share_picture("picturealltime")' in text and 'share_picture("pictureyear")' in text)
    # 3.9.10: the Crew menu went: Friends opens the Friends window (its list, the code, Copy invite), and
    # sharing a deck starts on Crew › Decks
    fd = open(os.path.join(REPO, "due_crew", "ui", "friends_dialog.py"), encoding="utf-8").read()
    dk = board._decks_body({"entries": [{"user_id": "me", "name": "Me", "you": True, "decks": [{"name": "D", "cards": 10, "seen": 5, "mature": 2}]},
                                        {"user_id": "a", "name": "A", "you": False, "decks": [{"name": "D", "cards": 10, "seen": 4, "mature": 1}]}],
                            "labels": []})
    check("no Crew menu: Friends has the code and Copy invite; Crew › Decks starts sharing a deck",
          not hasattr(board, "crew_menu_items") and "def _crew_menu" not in text and '"crewmenu"' not in text
          and 'QPushButton("Copy invite")' in fd
          and ('<div class="dc-add"><a href="#" title="Pick the decks your crew sees" onclick="pycmd(\'duecrew:decks|' + board.BOARD_KEY + "'); return false;\">+ Share a deck</a>") in dk
          and "Matching decks pair up" not in dk, dk[-300:])
    import due_crew as dc
    import aqt.utils as au
    from aqt.deckbrowser import DeckBrowser
    if "aqt.reviewer" not in sys.modules:
        sys.modules["aqt.reviewer"] = types.SimpleNamespace(Reviewer=type("Reviewer", (), {}))
    got, saved, saved_link = [], dc._share_menu, getattr(au, "openLink", None)
    dc._share_menu = lambda c: got.append("share")
    au.openLink = lambda url: got.append(url)
    try:
        dc._on_js(False, as_board("duecrew:sharemenu"), DeckBrowser())
        dc._on_js(False, as_board("duecrew:privacypage"), DeckBrowser())
    finally:
        dc._share_menu = saved
        au.openLink = saved_link
    page = board.settings_html({"tab": "privacy", "signed_in": True}, {})
    check("footer's Share and Privacy's What Due Crew keeps reach their handlers (3.7.1, D3)",
          got[0] == "share" and got[1].endswith("/privacy") and "duecrew:privacypage" in page, got)


def test_long_quiet_friends_fold():
    """Q3: friends with no sync in 90+ days fold into one line under
    everyone, opened in the page; a friend quiet for a week doesn't."""
    from datetime import datetime, timedelta, timezone
    labels = [(datetime.now() - timedelta(days=i)).date().isoformat() for i in range(7)]
    ago = lambda d: (datetime.now(timezone.utc) - timedelta(days=d)).isoformat().replace("+00:00", "Z")
    def ent(uid, name, last, days=None, you=False):
        return {"user_id": uid, "name": name, "you": you, "paused": False, "last_updated": last,
                "exam_date": "", "days": days or {}, "decks": []}
    data = {"entries": [ent("me", "Sammy", ago(0), {labels[0]: {"studied": True, "reviews": 5}}, you=True),
                        ent("w", "Wren", ago(8)), ent("p", "Priya", ago(120)), ent("t", "Theo<", ago(200))],
            "labels": labels, "tomorrow": "", "pending": []}
    page = board.render(data, {"period": "today"}, 0)
    fold = page[page.index('class="qfold"'):]
    fold = fold[:fold.index("</tr>")]
    check("quiet fold: two long-quiet friends fold into one line, names escaped; a week-quiet one stays a row",
          "2 quiet" in fold and "Priya and Theo&lt; haven't been here since" in fold
          and page.count('<tr class="qh ') == 2 and page.index(">Wren<") < page.index('class="qfold"')
          and "qopen" in fold and "pycmd" not in fold, fold)
    one = dict(data, entries=data["entries"][:3])
    check("quiet fold: one person reads 'hasn't'", "Priya hasn't been here" in board.render(one, {"period": "today"}, 0))
    near = dict(data, entries=data["entries"][:2])
    check("quiet fold: none when no one's been away 90 days", 'class="qfold"' not in board.render(near, {"period": "today"}, 0))
    view = {"state": "ok", "squads": [{"id": "s", "name": "S"}], "current": "s", "name": "S", "open": True,
            "rows": [{"user_id": "a", "name": "Ann", "day": labels[0], "reviews": 9, "time_ms": 60000, "week": 3},
                     {"user_id": "b", "name": "Bo", "day": labels[3], "reviews": 4, "week": 1},
                     {"user_id": "c", "name": "Cy", "day": "2026-01-02", "reviews": 4, "week": 0}],
            "day": labels[0], "yesterday": labels[1], "people": 3, "reviews": 9}
    sq = board._squads_html(view, {})
    check("quiet fold: on a squad board too, after the recent ones", "1 quiet" in sq and "Cy hasn't been here since Jan" in sq
          and sq.count('<tr class="qh') == 1 and sq.index(">Bo<") < sq.index("qfold"), sq[sq.find("qfold") - 20:sq.find("qfold") + 300])


def _due_js_parity(D, T):
    """3.8.0: board.DUE_JS's parse (the add box's preview) reads every case
    as due.parse does: change one, change both. Needs node."""
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        print("SKIP due parity: no node")
        return
    js = board.DUE_JS
    body = js[js.index("var DAYS"):js.index("  function label")]
    cases = ["Book the room fri", "Call tom", "a today", "a tomorrow", "a later", "Pay rent next week",
             "Read 12 oct", "x sept 30", "fri", "x on friday", "x next tue", "x 31 feb", "x 3rd nov",
             "x nov 3rd", "x, oct 12", "Read \u0661\u0662 oct", "x 12 \u043e\u043a\u0442", "x 007 oct", "x 1 de",
             "  spaced   out   tmrw ", "x december 1st", "x dec. 25", "x 0 oct", "x 40 oct", "x sometime"]
    want = [list(D.parse(c, T)) for c in cases]
    prog = ("var window = {};" + body + "var cases = " + json.dumps(cases) + ";"
            "console.log(JSON.stringify(cases.map(function (c) { var p = parse(c, " + json.dumps(T) + "); return [p.text, p.day]; })));")
    out = subprocess.run([node, "-e", prog], capture_output=True, text=True, timeout=60)
    try:
        got = json.loads(out.stdout)
    except ValueError:
        got = None
    bad = [(c, w, g) for c, w, g in zip(cases, want, got or [])]
    bad = [x for x in bad if x[1] != x[2]]
    check("due: the add box's preview parses as due.parse does", got is not None and not bad, (bad, out.stderr[:300]))
    rcases = ["Practice block every mon", "every mon: practice block", "gym daily", "Read ch 3 weekdays",
              "Call home every sun and wed", "mondays", "Clean mondays", "Every Monday: review", "pick up every thing",
              "x every we", "x every wed, fri", "x each day", "a: b", "every mon:", "x every tu", "x tuesdays",
              "  x   every   thu  "]
    rwant = [list(D.parse_repeat(c)) for c in rcases] + [D.repeat_label(r) for r in ("0", "03", "01234", "0123456", "56")]
    prog = ("var window = {};" + body + "var cases = " + json.dumps(rcases) + ";"
            "var out = cases.map(function (c) { var p = parseRepeat(c); return [p.text, p.rule]; });"
            "['0', '03', '01234', '0123456', '56'].forEach(function (r) { out.push(repeatLabel(r)); });"
            "console.log(JSON.stringify(out));")
    out = subprocess.run([node, "-e", prog], capture_output=True, text=True, timeout=60)
    try:
        got = json.loads(out.stdout)
    except ValueError:
        got = None
    bad = [x for x in zip(rcases + ["labels"] * 5, rwant, got or []) if x[1] != x[2]]
    check("due: the preview reads a repeat as due.parse_repeat does", got is not None and not bad, (bad, out.stderr[:300]))


def test_due_model():
    """Due (mock "My List"): day words, own items, Behind, the three tabs."""
    from due_crew import due as D
    T = "2026-10-03"  # a Saturday
    check("due: a day at the end comes off", D.parse("Book the room fri", T) == ("Book the room", "2026-10-09"))
    check("due: a name is never a day", D.parse("Call tom", T) == ("Call tom", None))
    check("due: today, tomorrow, later", [D.parse(x, T)[1] for x in ("a today", "a tomorrow", "a later")]
          == [T, "2026-10-04", ""])
    check("due: next week is Monday", D.parse("Pay rent next week", T)[1] == "2026-10-05")
    check("due: a date in words, this year or next",
          D.parse("Read 12 oct", T)[1] == "2026-10-12" and D.parse("x sept 30", T)[1] == "2027-09-30")
    check("due: a day alone stays text", D.parse("fri", T) == ("fri", None))
    check("due: a weekday on that weekday is next week's", D.when_word("sat", T) == "2026-10-10")
    check("due: digits are 0-9 only, as the preview reads them", D.parse("Read \u0661\u0662 oct", T) == ("Read \u0661\u0662 oct", None))
    _due_js_parity(D, T)
    check("due: a repeat, said at the end or before a colon",
          D.parse_repeat("Practice block every mon") == ("Practice block", "0")
          and D.parse_repeat("every mon and thu: Practice") == ("Practice", "03")
          and D.parse_repeat("gym daily") == ("gym", "0123456") and D.parse_repeat("Read weekdays") == ("Read", "01234"))
    check("due: no repeat in a plain line, or alone", D.parse_repeat("pick up every thing") == ("pick up every thing", None)
          and D.parse_repeat("mondays") == ("mondays", None) and D.parse_repeat("x every we") == ("x every we", None))
    reps, rp = D.add([], "Practice block", "", T, ident="rrrr1", rule="0")
    reps, rs = D.add(reps, "Weekly review", "2026-11-01", T, ident="rrrr2", rule="5")
    check("due: a repeat starts today, whatever day was picked", rp["d"] == T and rp["r"] == "0" and rs["d"] == T)
    rv = D.view(T, [], reps, {})
    check("due: a repeat on its day is today's; not on others", [r["text"] for r in rv["rows"]] == ["Weekly review"]
          and rv["rows"][0]["tag"] == "every Sat" and rv["rows"][0]["done"] is False)
    up = {dd["day"]: [r["text"] for r in dd["rows"]] for dd in rv["days"] if "day" in dd}
    check("due: Upcoming has a repeat once: today's, else its next day", up.get("2026-10-05") == ["Practice block"]
          and "2026-10-12" not in up and "2026-10-10" not in up and up.get(T) == ["Weekly review"], up)
    nx = board._due_html(dict(rv, tab="upcoming"))
    check("due board: a repeat's next day has no tick yet", "duecrew:duetick:rrrr1" not in nx and "duecrew:duetick:rrrr2" in nx)
    tk = D.change(reps, "rrrr2", T, done=True)
    tv = D.view(T, [], tk, {})
    nxt = D.view("2026-10-10", [], tk, {})
    tup = {dd["day"]: [r["text"] for r in dd["rows"]] for dd in tv["days"] if "day" in dd}
    check("due: ticked, a repeat is done today and back next week; Upcoming shows that next day too",
          tv["rows"][0]["done"] is True and tv["done_n"] == 1 and nxt["rows"][0]["done"] is False
          and tup.get(T) == ["Weekly review"] and tup.get("2026-10-10") == ["Weekly review"], tup)
    check("due: a repeat is never behind, never Later, never pruned, always open",
          not D.view("2026-10-06", [], reps, {})["behind_mine"] and not rv["later"]
          and len(D.prune(tk, "2026-12-01")) == 2 and D.open_count(tk) == 2)
    check("due: a repeat keeps its weekdays through clean; a bad rule is dropped",
          D.clean_items(tk)[1].get("r") == "5" and "r" not in D.clean_items([dict(rp, r="9x")])[0])
    stop = D.change(tk, "rrrr2", T, r="")
    check("due: Stop repeating: a one-off today, its tick kept", "r" not in stop[1] and stop[1]["d"] == T and stop[1]["done"] == T)
    check("due: a repeat isn't moved to a day", D.change(reps, "rrrr1", T, d="2026-10-20")[0]["d"] == T)
    rb = board._due_html(rv)
    check("due board: a repeat's tag says when, and opens its menu", "every Sat &#9662;" in rb and "duecrew:dueitem:rrrr2" in rb)
    check("due: nothing behind today", not D.day_ok("2026-10-02", T) and D.day_ok("", T) and D.day_ok(T, T))
    items, it = D.add([], "  Email   the director ", T, T, ident="aaaa1")
    check("due: add tidies text", it and it["t"] == "Email the director" and it["d"] == T)
    items, _ = D.add(items, "Practice exam 3", "2026-10-04", T, ident="aaaa2")
    items, _ = D.add(items, "Old thing", "", T, ident="aaaa3")
    full = [{"id": f"x{i:04d}", "t": "x", "d": "", "done": "", "at": T} for i in range(D.MAX_OPEN)]
    check("due: 60 open at most", D.add(full, "one more", "", T)[1] is None)
    check("due: clean drops bad items", D.clean_items([{"id": "!!", "t": "x"}, {"id": "abcd", "t": ""},
                                                       {"id": "abcd", "t": "ok", "d": "nope"}])
          == [{"id": "abcd", "t": "ok", "d": "", "done": "", "at": ""}])
    moved = D.change(items, "aaaa3", T, d="2026-10-08")
    check("due: move to a day", next(i for i in moved if i["id"] == "aaaa3")["d"] == "2026-10-08")
    check("due: never moved behind today",
          next(i for i in D.change(items, "aaaa3", T, d="2026-01-01") if i["id"] == "aaaa3")["d"] == "")
    ticked = D.change(items, "aaaa1", T, done=True)
    check("due: ticked items go after a week",
          len(D.prune(ticked, "2026-10-09")) == 3 and len(D.prune(ticked, "2026-10-10")) == 2)
    # a plan: one date behind (opened Thu, not done), one today, one tomorrow, an exam Wed
    dates = [
        {"pid": "p1", "uid": "u0", "plan": "Big Step 1", "name": "Done date", "opens": "2026-09-30", "seen": 9, "total": 9},
        {"pid": "p1", "uid": "u1", "plan": "Big Step 1", "name": "Cardio", "opens": "2026-10-01", "seen": 3, "total": 10},
        {"pid": "p1", "uid": "u2", "plan": "Big Step 1", "name": "Pharm", "opens": T, "seen": 4, "total": 8,
         "parts": [["Video Series", 4, 4], ["Path Book", 0, 4]],
         "todo": [{"k": "watch", "t": "lecture 14"}]},
        {"pid": "p1", "uid": "u3", "plan": "Big Step 1", "name": "Renal", "opens": "2026-10-04", "seen": 0, "total": 12},
        {"pid": "p1", "uid": "u4", "plan": "Big Step 1", "name": "Far", "opens": "2026-11-30", "seen": 0, "total": 5},
    ]
    old = [{"id": "bbbb1", "t": "Left from Thu", "d": "2026-10-01", "done": "", "at": "2026-10-01"}]
    v = D.view(T, dates, items + old, {}, events=[{"day": "2026-10-07", "name": "KSA", "plan": "Big Step 1"}],
               reviews={"due": 40, "done": 0})
    check("due: Behind has the undone date as its plan's line", v["behind_plans"] == [
        {"kind": "behind", "pid": "p1", "plan": "Big Step 1", "dates": 1, "left": 7, "first": "2026-10-01", "uid": "u1"}])
    check("due: Behind has my item from Thu", [r["text"] for r in v["behind_mine"]] == ["Left from Thu"]
          and v["behind_mine"][0]["tag"] == "since Thu" and v["behind_n"] == 2)
    kinds = [r["kind"] for r in v["rows"]]
    check("due: Today is reviews, the date, my item", kinds == ["reviews", "plan", "mine"], kinds)
    pr = v["rows"][1]
    check("due: a date's parts and author line", [ln["kind"] for ln in pr["lines"]] == ["part", "part", "todo"]
          and pr["lines"][0]["done"] and not pr["lines"][1]["done"] and pr["part"] and not pr["done"])
    v2 = D.view(T, [dict(dates[2], seen=8)], [], {"p1:u2:0": T})
    check("due: a date ticks itself when seen and its lines are ticked", v2["rows"][0]["done"] and v2["done_n"] == 1)
    v3 = D.view(T, [dict(dates[2], seen=8)], [], {})
    check("due: ...and not while an author line is open", not v3["rows"][0]["done"])
    ups = v["days"]
    check("due: Upcoming starts with today", ups[0]["today"] and ups[0]["head"].startswith("Today"))
    check("due: tomorrow's date and my item", [r.get("name") or r.get("text") for r in ups[1]["rows"]]
          == ["Renal", "Practice exam 3"] and ups[1]["head"].startswith("Tomorrow"))
    check("due: quiet days fold to one line, the event has its day",
          ups[2].get("quiet") and ups[3]["day"] == "2026-10-07" and ups[3]["events"] == ["KSA"])
    check("due: two weeks only", all((x.get("day") or x["quiet"][1]) <= "2026-10-17" for x in ups))
    check("due: Later holds the undated", [r["text"] for r in v["later"]] == ["Old thing"] and v["later_n"] == 1)
    check("due: tomorrow's line", v["tomorrow"] == ["Renal", "Practice exam 3"])
    check("due: the next exam", v["event"]["name"] == "KSA" and v["event"]["when"] == "Wed")
    check("due: done counts today only", (v["done_n"], v["total_n"]) == (0, 3))
    check("due: a date with nothing to see never sits behind as done",
          not D.date_state({"pid": "p", "uid": "u", "opens": T, "seen": 0, "total": 0}, {})[0])
    check("due: suggestions at most two", len(D.view(T, [], [], {}, suggestions=[{"key": str(i)} for i in range(4)])
                                                ["suggestions"]) == 2)
    check("due: empty when nothing", D.empty(D.view(T, [], [], {})))


def test_due_author_lines_arrive_clean():
    """Due: a date's author lines, as a plan arrives: words, a kind, an https link only, 8 at most."""
    from due_crew.backend import shapes
    doc = shapes.clean_plan_doc({"deck": "D", "units": [{"id": "a", "name": "A", "opens": "2026-10-03", "todo": [
        {"k": "watch", "t": "Lecture  14", "url": "https://example.com/x"}, {"k": "watch", "t": "x", "url": "javascript:alert(1)"},
        {"k": "sing", "t": "y"}, {"k": "read", "t": ""}, {"k": "read", "t": "Lec\nture"}, {"k": "read", "t": " "}]
        + [{"k": "do", "t": str(i)} for i in range(10)]}]})
    todo = doc["units"][0]["todo"]
    check("due lines: as the server keeps them (so a tick's key is the site's too), https only; unknown kinds, "
          "empty ones and control characters dropped, 8 at most",
          todo[0] == {"k": "watch", "t": "Lecture  14", "url": "https://example.com/x"} and todo[1] == {"k": "watch", "t": "x"}
          and len(todo) == 8 and not any("\n" in x["t"] or not x["t"].strip() for x in todo), todo)


def test_due_folds_itself_when_done():
    """Due folds to its one line once today's all ticked and nothing's behind,
    opens again tomorrow, and a Hide or Show by hand holds for the day."""
    from due_crew import due as D
    T = "2026-10-03"
    done = D.view(T, [{"pid": "p", "uid": "u", "plan": "P", "name": "A", "opens": T, "seen": 5, "total": 5},
                      {"pid": "p", "uid": "v", "plan": "P", "name": "Next one", "opens": "2026-10-04", "seen": 0, "total": 9}], [], {})
    left = D.view(T, [{"pid": "p", "uid": "u", "plan": "P", "name": "A", "opens": T, "seen": 2, "total": 5}], [], {})
    check("fold: done for today folds itself; not done stays open",
          D.fold_state(None, done, T) is True and D.fold_state(None, left, T) is False)
    check("fold: my Show today wins; yesterday's choice doesn't",
          D.fold_state({"day": T, "folded": False}, done, T) is False
          and D.fold_state({"day": "2026-10-02", "folded": True}, left, T) is False)
    check("fold: nothing at all today isn't 'done'", D.fold_state(None, D.view(T, [], [], {}), T) is False)
    h = board._due_html(dict(done, folded=True, done=True))
    check("fold: the line says done and what's next, with Show",
          "Done for today" in h and "Tomorrow: Next one" in h and "Show &#9662;" in h, h)
    check("fold: open, Hide says what it does", "Hide &#9652;" in board._due_html(dict(left, folded=False)))
    bk = D.view(T, [], [], {}, reviews={"due": 0, "done": 30, "back": 4, "at": "9:42"})
    hb = board._due_html(bk)
    check("fold: learning cards back later today keep Reviews open, with their time",
          D.fold_state(None, bk, T) is False and bk["rows"][0]["done"] is False and "4 back at 9:42" in hb
          and "all done" not in hb and bk["total_n"] == 1 and bk["done_n"] == 0, hb[:1200])
    check("fold: none back, Reviews done",
          D.view(T, [], [], {}, reviews={"due": 0, "done": 30, "back": 0, "at": ""})["rows"][0]["done"] is True
          and "back" not in board._due_html(dict(bk, rows=[dict(bk["rows"][0], due=7)])).split("Reviews")[1][:80])
    css = board.DUE_CSS
    check("fold: a long 'Tomorrow' gives way (ellipsis, the whole in its tooltip) so Show stays in the box",
          "#due-crew .du-one .du-tm { flex: 0 1 auto; min-width: 0;" in css
          and css.index("#due-crew .du-one .du-tm") > css.index("#due-crew .du-one > * { flex: none; }")
          and 'title="Next one"' in h, h)


def test_due_board_and_clicks():
    """Due on the board: the three tabs, escaped, every click sent as the
    board sends it; adding with a day said at the end; Behind; recover leeches."""
    from due_crew import due as D, due_flow as F, app as appmod
    import due_crew as dc
    from aqt.deckbrowser import DeckBrowser
    if "aqt.reviewer" not in sys.modules:
        sys.modules["aqt.reviewer"] = types.SimpleNamespace(Reviewer=type("Reviewer", (), {}))
    T = "2026-10-03"
    dates = [{"pid": "p1", "uid": "u2", "plan": "Big <Step>", "name": "Pharm <b>", "opens": T, "seen": 4, "total": 8,
              "parts": [["Video Series", 4, 4], ["Path Book", 0, 4]], "todo": [{"k": "watch", "t": "lecture <14>",
                                                                                  "url": "javascript:alert(1)"}]},
             {"pid": "p1", "uid": "u1", "plan": "Big <Step>", "name": "Cardio", "opens": "2026-10-01", "seen": 3, "total": 10}]
    items = [{"id": "aaaa1", "t": "Email <the> director", "d": T, "done": "", "at": T},
             {"id": "aaaa2", "t": "Someday", "d": "", "done": "", "at": T}]
    v = D.view(T, dates, items, {}, reviews={"due": 12, "done": 3}, suggestions=[{"key": "again", "text": "Go <over>", "go": "Study"}])
    h = board._due_html(v)
    check("due board: escaped, no raw markup from names or lines",
          "<b>Pharm &lt;b&gt;</b>" in h and "Email &lt;the&gt; director" in h and "lecture &lt;14&gt;" in h
          and "Big &lt;Step&gt;" in h and "Go &lt;over&gt;" in h and "<the>" not in h)
    check("due board: a link only when it's a web address", "javascript:" not in h)
    check("due board: Behind on top, then Today", h.index("Behind") < h.index("Pharm") and "Catch up" in h
          and "duecrew:plancatch:p1" in h)
    check("due board: tabs, fold, tick, item menu, add line", all(x in h for x in (
        "duecrew:duetab:upcoming", "duecrew:duetab:later", "duecrew:duefold", "duecrew:duetick:aaaa1",
        "duecrew:dueitem:aaaa1", 'id="du-in"', "duecrew:duego:again", "duecrew:duex:again", "Reviews", "12 due")))
    up = board._due_html(dict(v, tab="upcoming"))
    check("due board: Upcoming has today, + per day", "Today · Sat 3 Oct" in up and "dcDue.plus('2026-10-03')" in up)
    lt = board._due_html(dict(v, tab="later"))
    check("due board: Later has Do today", "duecrew:duedo:aaaa2" in lt and '<option value="later" selected>' in lt)
    one = board._due_html(dict(v, folded=True))
    check("due board: folded is one line", 'class="du du-one"' in one and "1 behind" in one and "du-tabs" not in one)
    check("due board: off is nothing", board._due_html(None) == "")
    js = board.keep_me_in_view_js()
    check("due board: the add line's script rides every draw", "window.dcDue" in js and "dueadd" in js)
    st = board.settings_html({"tab": "study", "signed_in": True}, {})
    check("due settings: three switches on Study", all(f"duecrew:set:{k}:" in st for k in ("due_show", "due_suggest", "due_leeches")))
    from due_crew import settings_model as SM
    check("due settings: the switches are whitelisted", SM.change(["set", "due_leeches", "1"], {}) == {"due_leeches": True})
    # clicks, through the add-on's own handler
    conf = {"due_items": [], "due_tab": "today"}
    saved = (F.cfg, F.save_cfg, appmod.swap, F._today, F.plan_dates)
    F.cfg = lambda: conf
    F.save_cfg = lambda c, **k: conf.update(c)
    appmod.swap = lambda c, focus=None: None
    F._today = lambda: T
    F.plan_dates = lambda today: ([], [], [])
    try:
        send = lambda m: dc._on_js(False, as_board("duecrew:" + m), DeckBrowser())
        send("dueadd:today:0:" + "Book%20the%20room%3A%20B12%20fri")
        it = conf["due_items"][-1] if conf["due_items"] else {}
        check("due add: a day said at the end, text kept with its colon", it.get("t") == "Book the room: B12"
              and it.get("d") == "2026-10-09", conf)
        check("due add: it says where it went", (F._toast() or {}).get("text") == "Added to Fri 9 Oct")
        send("dueadd:later:1:" + "Call%20mom%20fri")
        check("due add: x keeps the words", conf["due_items"][-1]["t"] == "Call mom fri" and conf["due_items"][-1]["d"] == "")
        send("dueadd:2026-01-01:0:Old")
        check("due add: never behind today", conf["due_items"][-1]["d"] == T)
        ident = conf["due_items"][0]["id"]
        send("duetick:" + ident)
        check("due tick", conf["due_items"][0]["done"] == T)
        send("duetick:" + ident)
        check("due untick", conf["due_items"][0]["done"] == "")
        send("duedo:" + conf["due_items"][1]["id"])
        check("due: Do today", conf["due_items"][1]["d"] == T)
        send("duetab:upcoming")
        check("due tab", conf["due_tab"] == "upcoming")
        send("duefold")
        check("due fold: Hide holds for today", conf["due_fold"] == {"day": T, "folded": True}, conf.get("due_fold"))
        send("dueshow:later")
        check("due show", conf["due_tab"] == "later")
        # 3.8.0: a repeat, said in the words; T is a Saturday
        conf["due_tab"] = "today"
        send("dueadd:today:0:" + "Practice%20block%20every%20mon")
        rep = conf["due_items"][-1]
        check("due add: a repeat said at the end, from today", rep.get("t") == "Practice block" and rep.get("r") == "0"
              and rep.get("d") == T and (F._toast() or {}).get("text") == "Added, every Mon", (rep, F._toast()))
        send("dueadd:today:0:" + "every%20sat%3A%20Weekly%20review")
        sat = conf["due_items"][-1]
        check("due add: a repeat said first, before a colon; on today, no toast", sat.get("t") == "Weekly review"
              and sat.get("r") == "5")
        send("duetick:" + sat["id"])
        check("due tick: a repeat is done for today only", sat["id"] in [i["id"] for i in conf["due_items"]]
              and next(i for i in conf["due_items"] if i["id"] == sat["id"])["done"] == T)
        send("duetick:" + sat["id"])
        check("due untick: a repeat", next(i for i in conf["due_items"] if i["id"] == sat["id"])["done"] == "")
        send("dueadd:today:1:" + "Read%20mondays")
        check("due add: x keeps a repeat's words too", conf["due_items"][-1]["t"] == "Read mondays"
              and not conf["due_items"][-1].get("r"))
        F.stop_repeat(conf, sat["id"])
        one = next(i for i in conf["due_items"] if i["id"] == sat["id"])
        check("due: Stop repeating leaves a one-off today", "r" not in one and one["d"] == T)
    finally:
        F.cfg, F.save_cfg, appmod.swap, F._today, F.plan_dates = saved
    # recover leeches: tag off, unsuspended, new again, one undo step; the note's other card untouched
    conn = sqlite3.connect(":memory:")
    fakes.make_collection(conn)
    fakes.add_card(conn, 1, did=10, ctype=2, queue=-1, tags="leech Cardio", lapses=8)
    fakes.add_card(conn, 2, did=10, ctype=2, queue=2, nid=1, ord_=1, lapses=1)
    fakes.add_card(conn, 3, did=10, ctype=2, queue=2, tags="Cardio", lapses=9)
    col = fakes.FakeCol(conn, fakes.day_cutoff_for(TODAY))
    got = F.recover_leeches(col)
    rows = {cid: (t, q, lp) for cid, t, q, lp in conn.execute("SELECT id, type, queue, lapses FROM cards")}
    tags = conn.execute("SELECT tags FROM notes WHERE id = 1").fetchone()[0].split()
    check("leeches: the leech back as new, its tag off, counts reset", got == [1] and rows[1] == (0, 0, 0)
          and tags == ["Cardio"], (got, rows, tags))
    check("leeches: its sibling and a non-leech left alone", rows[2] == (2, 2, 1) and rows[3] == (2, 2, 9))
    check("leeches: one undo step", len(col.undo_steps) == 1 and col.undo_steps[0][0].startswith("Due Crew"))
    check("leeches: none, no step", F.recover_leeches(col) == [] and len(col.undo_steps) == 1)
    # 3.8.0: switched on, they come back now, and it says so
    fakes.add_card(conn, 4, did=10, ctype=2, queue=-1, tags="leech Renal", lapses=9)
    conf2, said = {"due_leeches": False}, []
    saved2 = (dc.cfg, dc.save_cfg, F.cfg, F.mw.col, F.tooltip, F._today, F._pf)
    store = {}
    try:
        dc.cfg = F.cfg = lambda: conf2
        dc.save_cfg = lambda c, **k: conf2.update(c)
        F.mw.col, F.tooltip, F._today = col, (lambda m, **k: said.append(m)), (lambda: T)
        F._pf = lambda: types.SimpleNamespace(_pcfg=lambda: store, _psave=lambda d: None, _after_change=lambda: None)
        dc._state["settings_tab"] = "board"
        dc._on_js(False, as_board("duecrew:set:due_leeches:1"), DeckBrowser())
        check("leeches: switched on, today's come back at once, and it says so",
              conf2.get("due_leeches") is True and said and said[-1] == "1 leech back as a new card. Edit › Undo puts it back.", (said, store))
        dc._on_js(False, as_board("duecrew:set:due_leeches:1"), DeckBrowser())
        check("leeches: on again changes nothing", len(said) == 1)
    finally:
        (dc.cfg, dc.save_cfg, F.cfg, F.mw.col, F.tooltip, F._today, F._pf) = saved2
        dc._state["settings_tab"] = None


def test_plan_windows_ways_in_v393():
    """3.9.3 (Sam's picks): the plan windows, for everyone, and their ways in:
    each card's Your plans… (round five: the head row's Open plans and New
    plan ▾, the card's Open and Plan ▾ went), the empty state's ways (New
    plan…, Your plans…), Insights' Missed questions line on a deck with a
    bank, Find a setting. Each click sent as the board sends it."""
    import due_crew as dc
    from due_crew import plan_flow
    from due_crew.planner import flow as pflow
    from aqt.deckbrowser import DeckBrowser
    card = {"id": "p1", "title": "MS2 <Block> 1", "sub": "week 3 of 9", "tabs": {}}
    html = board._you_plans({"cards": [card]})
    check("ways in: round five, no head row; a plan card's one button, Your plans…, on the plan; its name escaped",
          html.startswith('<div class="dc-pc">') and "dc-ph" not in html and "duecrew:plannew|" not in html
          and "duecrew:planyours:p1|" in html and "Your plans&hellip;</a>" in html and "planmenu" not in html
          and "Plan &#9662;" not in html and ">Open</a>" not in html and "MS2 &lt;Block&gt; 1" in html, html[:400])
    none = board._you_plans({"cards": []})
    writes = board._you_plans({"cards": [], "writes": True})
    check("ways in: no plan yet, Make a plan (plans, end to end: the new plan window), and Your plans… for the plans I write",
          "dc-ph" not in none and "duecrew:planopennew|" in none and "duecrew:planmake|" not in none
          and "Make a plan</a>" in none and "From a deck&hellip;" not in none and "duecrew:planyours|" not in none
          and "duecrew:planyours|" in writes)
    calls = []
    saved = (pflow.open_plans, pflow.open_new, plan_flow.new_plan_menu)
    pflow.open_plans = lambda select=None, tab=None: calls.append(("plans", select))
    pflow.open_new = lambda: calls.append(("start",))
    plan_flow.new_plan_menu = lambda: calls.append(("new",))
    try:
        send = lambda m: dc._on_js(False, as_board("duecrew:" + m), DeckBrowser())
        for m in ("planyours", "planyours:p1", "planyours:bad id!", "plannew", "planstart", "planmissed:20", "planmissed"):
            send(m)
    finally:
        pflow.open_plans, pflow.open_new, plan_flow.new_plan_menu = saved
    check("ways in: each click reaches its window (a plan's id, nothing else, picks the plan); 3.9.7: QBank QIDs' old "
          "planmissed opens nothing, Magic search has its paste",
          calls == [("plans", None), ("plans", "p1"), ("plans", None), ("new",), ("start",)], calls)
    v = {"right": {}, "target": 90}
    from due_crew import due as D
    dv = D.view(TODAY.isoformat(), [], [], {}, reviews={"due": 10, "done": 0})
    check("3.9.5 (Sam: \"this line is extra because QIDs is in the header\"): no QBank QIDs line in Insights",
          "planmissed" not in board._insights_html(20, dict(v, bank=True)) and "practice block" not in board._insights_html(20, v))
    off = board._due_html(None, more=[("plans", "Plans"), ("insights", "Insights")], more_tab="insights",
                          more_body="<p>x</p>", magic=True)
    off_one = board._due_html(None, more=[("plans", "Plans"), ("insights", "Insights")], folded=True, magic=True)
    check("3.9.7, round 2 (Sam: \"this is replacing QBank QID search\"): Due's lists off, Magic search is in the head "
          "(and the folded line), QBank QIDs' chip gone",
          # 3.9.9 (Sam's pick G2): it's the field under the deck list now, whatever the You box shows; no link in the box
          "duecrew:magic" not in off + off_one and "planmissed" not in off + off_one
          and "QBank QIDs</a>" not in off + off_one and "pasted question IDs" in board.magic_field({}), off)
    head = board._due_html(dict(dv, qids=True), magic=True)
    head = head[:head.index("</div>")]
    check("ways in: Magic search in the box's head (QBank QIDs' place, Sam's pick 1), its title saying QIDs, no QIDs chip",
          "duecrew:magic" not in head and ">QBank QIDs</a>" not in head and "planmissed" not in head
          and "pycmd('duecrew:magic'+" in board.magic_field({}), head)
    up = board._due_html(dict(dv, tab="upcoming"), magic=True)
    one = board._due_html(dict(dv, folded=True), magic=True)
    plans_tab = board._due_html(dv, more=[("plans", "Plans")], more_tab="plans", more_body="<p>x</p>", magic=True)
    check("ways in: …on every tab and on the folded line (Sam: \"missing the QID chip on the top right\": Magic search's now)",
          # 3.9.9: one field for every tab and the folded line: it's above the box, drawn with the Decks page
          not any("duecrew:magic" in x for x in (up, one, plans_tab)) and "du-fold" in one, one)
    check("ways in: …on one baseline with the rest (Sam: \"a bit higher than everything else\"): one line height for the head's words, the folded line by baseline",
          "#due-crew .du-one > a, #due-crew .du-one > .du-n { line-height: 16px; }" in fakes.board_source()
          and "#due-crew .du-one { display: flex; align-items: baseline;" in fakes.board_source())
    from due_crew import due_flow
    check("3.9.7: no tag read for a QIDs chip any more (has_qids went with it)", not hasattr(due_flow, "has_qids"))
    ix = board.settings_index({"tab": "board", "signed_in": True}, {"accent": "green"})
    wins = {x["l"]: x for x in ix if x.get("p")}
    check("ways in: Find a setting finds the windows by the words people use, after every setting (3.9.7: Magic search)",
          set(wins) == {"Your plans", "New plan", "Magic search"}
          and "calendar" in wins["New plan"]["k"] and "missed" in wins["Magic search"]["k"] and "qids" in wins["Magic search"]["k"]
          and "filtered" in wins["Magic search"]["k"]
          and wins["Your plans"]["p"] == "planyours" and wins["Magic search"]["p"] == "magic"
          and all(x.get("p") for x in ix[-3:]) and not ix[-4].get("p"), list(wins))
    check("ways in: a window picked in Find a setting is opened, not looked for on a tab",
          "if (h.p) { pycmd('duecrew:' + h.p + '|' + window.dcBK); return; }" in board.FIND_JS)


def test_recover_by_deck_count_v393():
    """3.9.3, Sam's pick A: Recover leeches takes a leech by its deck's own
    leech count (as Insights' Leeches counts them), never one I left out,
    and asks once before the ones its old line (8 lapses) left in my
    reviews."""
    from due_crew import due_flow as F
    T = TODAY.isoformat()
    rows = [(1, 1, 8, -1, 10), (5, 5, 6, 2, 10), (6, 6, 6, 2, 20), (7, 7, 9, 2, 10), (8, 8, 3, -1, 10), (9, 9, 0, -1, 10)]
    limits = {10: (5, 1), 20: (8, 0)}
    deck, eight, extra = F.leech_sets(rows, limits, out={8})
    check("recover 3.9.3: by the deck's count, a suspended one always, none I left out, none never lapsed",
          deck == [1, 5, 7] and eight == [1, 7] and extra == [5], (deck, eight, extra))
    check("recover 3.9.3: a deck with no options read counts at 8", F.leech_sets([(3, 3, 6, 2, 99)], {})[0] == [])

    def col_with():
        conn = sqlite3.connect(":memory:")
        fakes.make_collection(conn)
        for cid, did, q, lp in ((1, 10, -1, 8), (5, 10, 2, 6), (6, 20, 2, 6), (7, 10, 2, 9), (8, 10, -1, 3)):
            fakes.add_card(conn, cid, did=did, ctype=2, queue=q, tags="leech Cardio", lapses=lp)
        col = fakes.FakeCol(conn, fakes.day_cutoff_for(TODAY))
        col.decks = fakes.FakeDecks({10: "Big Step 1", 20: "Mine"})
        col.decks.config_dict_for_deck_id = lambda d: {"lapse": {"leechFails": 5 if int(d) == 10 else 8,
                                                                 "leechAction": 1 if int(d) == 10 else 0}}
        return conn, col
    conn, col = col_with()
    check("recover 3.9.3: the plan over a collection, with the counts the question names",
          F.leech_plan(col, {8}) == ([1, 5, 7], [1, 7], [5], [5]), F.leech_plan(col, {8}))
    pc, asked, said, changed = {}, [], [], []
    store = {"pc": pc}
    import aqt.qt as Q
    saved = (F._pf, F.mw.col, F._today, getattr(F.mw, "state", None), F.ask_reach, F._left_out, F.tooltip,
             Q.QTimer.singleShot)
    try:
        Q.QTimer.singleShot = staticmethod(lambda ms, fn: fn())  # the question, once the board has drawn
        F._pf = lambda: types.SimpleNamespace(_pcfg=lambda: store["pc"], _psave=lambda d: store.update(pc=d),
                                              _after_change=lambda: changed.append(1))
        F.mw.col, F._today, F.mw.state = col, (lambda: T), "deckBrowser"
        F.ask_reach = lambda n, counts: asked.append((n, counts))
        F._left_out = lambda: {8}
        F.tooltip = lambda m, **k: said.append(m)
        F.morning({"due_leeches": True})
        st = store["pc"]["due"]
        check("recover 3.9.3: the first morning takes what Recover always took, and asks about the rest",
              sorted(st["recovered"]) == [1, 7] and asked == [(1, [5])] and "leech_reach" not in store["pc"]
              and changed, (st, asked, store["pc"]))
        F.morning({"due_leeches": True})
        check("recover 3.9.3: asked once a morning", len(asked) == 1)
        F.set_reach(True)
        rows_now = {cid: q for cid, q in conn.execute("SELECT id, queue FROM cards")}
        check("recover 3.9.3: Learn them fresh: the deck's count from now on, today's extra ones now, said",
              store["pc"]["leech_reach"] == "deck" and rows_now[5] == 0 and sorted(store["pc"]["due"]["recovered"]) == [1, 5, 7]
              and said[-1] == "1 leech back as a new card. Edit › Undo puts it back.", (store["pc"], rows_now, said))
        check("recover 3.9.3: the one I left out stays shut", rows_now[8] == -1)
        conn2, col2 = col_with()
        F.mw.col = col2
        store["pc"] = {"leech_reach": "eight"}
        F.morning({"due_leeches": True})
        check("recover 3.9.3: after Not these, Recover keeps to 8 lapses, and doesn't ask",
              sorted(store["pc"]["due"]["recovered"]) == [1, 7] and len(asked) == 1)
        store["pc"] = {}
        F.set_reach(False)
        check("recover 3.9.3: Not these is kept", store["pc"]["leech_reach"] == "eight")
        conn3, col3 = col_with()
        conn3.execute("UPDATE cards SET lapses = 9 WHERE id = 5")
        F.mw.col, store["pc"] = col3, {}
        F.morning({"due_leeches": True})
        check("recover 3.9.3: nothing the old line left, no question: the deck's count",
              store["pc"]["leech_reach"] == "deck" and len(asked) == 1 and sorted(store["pc"]["due"]["recovered"]) == [1, 5, 7])
        conn4, col4 = col_with()
        F.mw.col, store["pc"] = col4, {"leech_reach": "eight"}
        saved_cfg = F.cfg
        F.cfg = lambda: {"due_leeches": True}
        try:
            F.recover_now()
        finally:
            F.cfg = saved_cfg
        check("recover 3.9.3: switched on again, its question comes again", len(asked) == 2 and "leech_reach" not in store["pc"])
    finally:
        F._pf, F.mw.col, F._today, F.mw.state, F.ask_reach, F._left_out, F.tooltip, single = saved
        Q.QTimer.singleShot = staticmethod(single)
    st_html = board.settings_html({"tab": "study"}, {"due_leeches": True})
    st_eight = board.settings_html({"tab": "study", "leech_reach": "eight"}, {"due_leeches": True})
    check("recover 3.9.3: Settings says which line it uses",
          "at each deck&#x27;s leech count" in st_html or "at each deck's leech count" in st_html, st_html[-400:])
    check("recover 3.9.3: and after Not these, 8 lapses", "at 8 lapses" in st_eight)
    import inspect
    src = inspect.getsource(F.ask_reach)
    check("recover 3.9.3: the question is the board's sheet, Not these its other answer",
          "sheets.confirm(" in src and 'no_label="Not these"' in src and "gen == app.generation" in src)


def test_history_import():
    """3.7.1: once the first 120 days have gone, each full sync carries one
    more year of my log until my first review; an empty year is passed
    over; a server that doesn't say it keeps the whole log never moves it on."""
    from due_crew import cards as C
    conn = sqlite3.connect(":memory:")
    fakes.make_collection(conn)
    col = fakes.FakeCol(conn, fakes.day_cutoff_for(TODAY))
    cutoff = col.sched.day_cutoff
    for ago in (3, 200, 400, 1300):  # recent, last year, two years back, gap, four years back
        fakes.add_review(conn, (cutoff - ago * 86400 - 3600) * 1000, cid=ago)
    cl = types.SimpleNamespace(user_id="me", session={"log_full": "me"}, _save_session=lambda: None)
    got = C.history_part(col, cl)
    check("history: the year before the first 120 days", got and len(got[0]) == 2 and got[1] == C.LOG_FULL + 366, got)
    cl.session["log_back"] = {"uid": "me", "skip": got[1]}
    got2 = C.history_part(col, cl)
    check("history: an empty year is passed over to the next with something",
          got2 and len(got2[0]) == 1 and got2[1] == C.LOG_FULL + 4 * 366, got2)
    cl.session["log_back"] = {"uid": "me", "skip": got2[1]}
    check("history: done at my first review", C.history_part(col, cl) is None and cl.session["log_back"].get("done"))
    check("history: never before the first 120 days have gone",
          C.history_part(col, types.SimpleNamespace(user_id="me", session={}, _save_session=lambda: None)) is None)
    cl2 = api.ApiClient(os.path.join(tempfile.mkdtemp(), "s.json"))
    cl2.session.update(token="t", uid="u1")
    sent = {}
    cl2._call = lambda m, path, body=None, **k: (sent.update(body or {}), (200, {"ok": True}))[1]
    labels = [(datetime.date(2026, 10, 3) - datetime.timedelta(days=i)).isoformat() for i in range(8)]
    try:
        cl2.push(labels, {}, log={labels[0]: [5, 10, 1, 90.0]}, log_back=({"2025-01-02": [9, 20, 2, None]}, 486))
    except Exception as e:
        sent["err"] = repr(e)
    check("history: the year rides the sync with the recent days",
          set((sent.get("log") or {}).get("days", {})) == {labels[0], "2025-01-02"}, sent.get("log"))
    check("history: a server that didn't say logAll doesn't move it on", "log_back" not in cl2.session, cl2.session.get("log_back"))
    cl2._call = lambda m, path, body=None, **k: (200, {"ok": True, "logAll": True, "logCut": True})
    cl2.push(labels, {}, log={labels[0]: [5, 10, 1, 90.0]}, log_back=({"2025-01-02": [9, 20, 2, None]}, 486))
    check("history: after Delete my log (logCut) the import is done: the old years stay home (3.7.1, D2)",
          (cl2.session.get("log_back") or {}).get("done") is True)


NEW_CARDS_213 = ("SELECT CAST((? - r.id / 1000) / 86400 AS INTEGER), COUNT(DISTINCT r.cid) "
                 "FROM revlog r WHERE r.ease > 0 AND r.id >= ? AND r.id < ? AND NOT EXISTS "
                 "(SELECT 1 FROM revlog p WHERE p.cid = r.cid AND p.ease > 0 AND p.id < r.id) GROUP BY 1")


def test_new_cards_first_answer_v391():
    """3.9.1, the history import's new cards: each card answered in the
    window has its first answer read once, where every answer used to look
    for an earlier one (2.13's query, kept here). The same count, window by
    window, for cards whose first local row isn't a learn (imported with
    their schedule, set due first, a filtered deck's preview), relearned,
    forgotten and learned again, or only ever rescheduled; a first local
    row being a learn (type 0) isn't what makes a card new."""
    conn = sqlite3.connect(":memory:")
    fakes.make_collection(conn)
    col = fakes.FakeCol(conn, fakes.day_cutoff_for(TODAY))
    q = StatsQueries(col)
    cut = col.sched.day_cutoff
    cards = {  # cid: (days ago, type, ease), oldest first
        1: [(400, 0, 1), (400, 0, 3), (300, 1, 3), (100, 1, 1), (100, 2, 3)],  # learned, lapsed, relearned
        2: [(500, 1, 3), (200, 1, 3)],                                         # imported: its first row a review
        3: [(450, 4, 0), (130, 1, 3), (5, 1, 4)],                              # set due date first (ease 0)
        4: [(140, 3, 3), (139, 0, 3), (2, 1, 3)],                              # a filtered deck's preview first
        5: [(800, 0, 3), (700, 1, 3), (125, 4, 0), (125, 0, 3), (3, 0, 3)],    # forgotten, learned again
        6: [(126, 5, 0), (126, 5, 0)],                                         # rescheduled, never answered
        7: [(6, 0, 1), (6, 0, 3), (0, 1, 3)],                                  # new this week
        8: [(1, 0, 3)],
        9: [(0, 0, 3)],
    }
    for cid, rows in cards.items():
        for ago, typ, ease in rows:
            fakes.add_review(conn, (cut - ago * 86400 - 5 * 3600) * 1000, ease=ease, rtype=typ, cid=cid)

    def before(days, skip=0, typed=False):
        s, e = (cut - (days + skip) * 86400) * 1000, (cut - skip * 86400) * 1000
        sql = NEW_CARDS_213.replace("r.ease > 0 AND", "r.ease > 0 AND r.type = 0 AND") if typed else NEW_CARDS_213
        return {q.day_label(int(a)): int(n) for a, n in col.db.all(sql, cut - 1, s, e)}

    windows = ([(1, 0), (7, 0), (8, 0), (31, 0), (32, 0), (120, 0), (366, 120), (366, 486), (366, 852)]
               + [(30, s) for s in range(0, 900, 30)] + [(60, s) for s in range(0, 900, 60)])
    bad, per = {}, StatsQueries.PER_CARD_DAYS
    try:
        for name, n in (("each card once", 0), ("each answer", 10 ** 6), ("as it picks", per)):
            StatsQueries.PER_CARD_DAYS = n
            bad[name] = [(d, s) for d, s in windows if q.new_cards_by_day(d, s) != before(d, s)]
    finally:
        StatsQueries.PER_CARD_DAYS = per
    check("new cards: each card's first answer, read once, counts as 2.13's query did, in every window "
          "(as does each answer looking for an earlier one, and the pick between them by the window's length)",
          all(v == [] for v in bad.values()), bad)
    check("new cards: a card imported with its schedule, set due first or previewed is new on its first answer",
          sum(q.new_cards_by_day(366, 120).values()) == 3 and sum(q.new_cards_by_day(366, 486).values()) == 2
          and q.new_cards_by_day(8) == {q.day_label(6): 1, q.day_label(1): 1, q.day_label(0): 1}
          and q.new_cards_by_day(366, 486) != before(366, 486, typed=True), q.new_cards_by_day(366, 486))
    check("new cards: relearned, forgotten and learned again, or only rescheduled, it isn't new again",
          q.new_cards_by_day(120) == {q.day_label(6): 1, q.day_label(1): 1, q.day_label(0): 1}
          and q.day_label(125) not in q.new_cards_by_day(366, 120) and q.day_label(126) not in q.new_cards_by_day(366, 120))
    from due_crew.stats import queries as SQ
    SQ._FRESH["key"] = None
    ran = []
    real_all = col.db.all
    col.db.all = lambda sql, *a: ran.append((sql, a)) or real_all(sql, *a)
    q.new_cards_by_day(366, 120)
    week = q.new_cards_by_day(8)
    today, again = q.new_cards_by_day(1), q.new_cards_by_day(8)
    col.db.all = real_all
    plan = " ".join(str(r[-1]) for r in real_all("EXPLAIN QUERY PLAN " + ran[0][0], *ran[0][1]))
    check("new cards: a year looks each card's first answer up once (its select isn't flattened into the count's); "
          "a week, each answer for an earlier one, as in 2.13",
          len(ran) == 2 and plan.count("CORRELATED SCALAR SUBQUERY") == 1 and "LIMIT -1" in ran[0][0]
          and ran[1][0] == NEW_CARDS_213, plan)
    check("new cards (3.9.8): a sync's today and week again are the week's read, no pass of their own; today is the week's today",
          len(ran) == 2 and again == week and today == {k: v for k, v in week.items() if k == q.day_label(0)}, (len(ran), today))
    SQ._FRESH["key"] = None


def test_offline_error_names_no_code():
    """3.7.1 review: requests' own error carries the whole URL (a friend,
    plan or squad code); the add-on's error is raised without it, so a
    traceback printed by _bg can't show it either."""
    import traceback as tb
    cl = api.ApiClient(os.path.join(tempfile.mkdtemp(), "s.json"))
    cl.session.update(token="t", uid="u1")

    class Down:
        def request(self, method, url, **kw):
            raise api.requests.RequestException(f"Max retries exceeded with url: {url}")
    cl.http = Down()
    path = "/codes/" + "ABCD" + "1234" + "/add"  # (a traceback quotes this line, not the code)
    try:
        cl._call("POST", path)
        text = ""
    except Exception as e:
        text = "".join(tb.format_exception(type(e), e, e.__traceback__))
    check("offline: the error and its traceback name no code", text and "ABCD1234" not in text, text[-300:])
    p = cl.session_file
    cl._save_session()
    check("session file: mine alone", (os.stat(p).st_mode & 0o077) == 0)


def test_remaining_oct():
    """What the October bug run left: a date opened before its author's note
    ids came picks them up; an author's lines keep their ticks when they're
    reordered."""
    from due_crew import plans as P, plan_flow as F, due as D
    col = _spread_col()
    idx = P.DeckIndex(col, 10)
    guids = {cid: g for (g, _o), cid in idx.by_ref.items()}
    day = TODAY.isoformat()
    unit = {"id": "r", "name": "Renal", "opens": day, "tags": ["Step1_v13::Renal"], "decks": [], "cards": []}
    p = {"doc": {"deck": "Step 1", "units": [unit]}}
    st = {"deck_id": 10, "applied": {}, "src": {}}
    names, cids, _u = F._spread(col, p, st, day)
    check("ids: a date whose tag matches nothing here opens nothing, and is applied", not cids and "r" in st["applied"])
    unit["ids"] = [guids[103], guids[104]]
    names, cids, _u = F._spread(col, p, st, day)
    check("ids: the author's note ids arriving later open what they find", cids == {103, 104}, str(cids))
    check("ids: and then it's applied as it stands", F._spread(col, p, st, day)[1] == set())
    old = {"deck_id": 10, "applied": {"r": P.unit_sig_v1(unit, 10, None)}, "src": {"r": P.unit_sources(dict(unit, ids=[]), 10, None)}}
    check("ids: a date applied before 3.7.2 is carried over as it stands",
          F._spread(col, p, old, day)[1] == set() and old["applied"]["r"] == P.unit_sig(unit, 10, None) and old["sig2"])
    unit["ids"] = unit["ids"] + [guids[105]]
    check("ids: from then on, one more opens", F._spread(col, p, old, day)[1] == {105})

    x = {"pid": "p1", "uid": "u1", "todo": [{"k": "watch", "t": "Lecture 14"}, {"k": "read", "t": "Ch 3"}]}
    keys = D.line_keys("p1", "u1", x["todo"])
    ticks = {keys[0]: day}
    moved = dict(x, todo=list(reversed(x["todo"])))
    check("ticks: keyed by the line, so a reorder moves the tick with it",
          D.line_ticked(x, ticks) == [True, False] and D.line_ticked(moved, ticks) == [False, True])
    check("ticks: two identical lines are told apart",
          len(set(D.line_keys("p", "u", [{"k": "do", "t": "Qs"}, {"k": "do", "t": "Qs"}]))) == 2)
    check("ticks: one from before 3.7.2 (the line's place) still reads",
          D.line_ticked(x, {D.todo_key("p1", "u1", 1): day}) == [False, True])
    import re as _re
    app_js = open(os.path.join(REPO, "site", "public", "app.js"), encoding="utf-8").read()
    init_src = srcs.glue_src()
    check("cheers: the main thread's commit is what says they arrived (cheers_got from the reply's cheers_at)",
          'got = data.get("cheers_at") or 0' in init_src and 'cl.session["cheers_got"] = got' in init_src)
    check("ticks: the site hashes lines the same way (FNV-1a, code points)",
          "0x811c9dc5" in app_js and "0x01000193" in app_js and "codePointAt" in app_js
          and _re.search(r"ticks\[keys\[i\]\]", app_js))


def test_plan_switch_round5():
    """Round five, Sam's pick 3 ("with multiple plans, we don't need two
    buttons for your plans", then "Let's go with 3"): two or more plans
    followed show one at a time, their names a switch in the card's head
    with one Your plans… on the plan shown; this computer keeps the pick
    (`plan_pick`), and Browse › Show on my plan's plan comes first."""
    from due_crew import plans as P
    from due_crew.app import _state
    from aqt.deckbrowser import DeckBrowser
    import due_crew as dc
    import due_crew.plan_flow as F
    t = _day(0)

    def card(pid, name, behind=0, **kw):
        doc = {"pace": {"days": [1] * 7}, "events": [], "units": [{"id": "u" + pid, "name": name + " date", "opens": t, "n": 10}]}
        return dict({"id": pid, "title": f"{name} · Dre\u2019s plan", "name": name, "sub": f"{name} line", "rows": [], "lines": [],
                     "change": None, "no_deck": False, "paused": False, "waiting": 0, "aside": [0, 0, 0], "aside_ok": [0, 0],
                     "week": P.week_view(doc, {}, t, P.week_start(t)), "week_offset": 0,
                     "status": {"togo": 10, "behind": behind, "since": "Monday"}}, **kw)

    a, b = card("pa", "Block <1>", behind=54), card("pb", "Micro")
    one = board._plans_html({"cards": [a]}, None, {})
    check("one plan: as built, its name and its Your plans…, no switch",
          'class="psw"' not in one and one.count("planyours:") == 1 and "Block &lt;1&gt; · Dre" in one, one[:600])
    two = board._plans_html({"cards": [a, b]}, None, {})
    check("two: one Your plans…, on the plan shown", two.count("planyours:") == 1 and "duecrew:planyours:pa" in two, two[:900])
    check("two: their names a switch, the first pressed; names escaped",
          'class="psw"' in two and two.count('aria-pressed="true"') == 1 and "duecrew:planpick:pa" in two
          and "duecrew:planpick:pb" in two and ">Block &lt;1&gt;<i" in two and "Block <1>" not in two, two[:900])
    check("two: the one shown's week and line alone", "dc-pd-pa-" in two and "dc-pd-pb-" not in two
          and "Micro date" not in two and "Block &lt;1&gt; line" in two and "Micro line" not in two)
    check("two: an amber dot on the one behind, none on the other", two.count('class="dot"') == 1 and 'title="54 behind"' in two)
    picked = board._plans_html({"cards": [a, b]}, None, {"plan_pick": "pb"})
    on = lambda h, pid: 'aria-pressed="true" title="' in h and h.split('aria-pressed="true"')[1].split("</a>")[0].count(f"planpick:{pid}") == 1  # noqa: E731
    check("the pick: Micro shown, its Your plans…", on(picked, "pb") and "duecrew:planyours:pb" in picked
          and "dc-pd-pb-" in picked and "dc-pd-pa-" not in picked, picked[:900])
    jumped = board._plans_html({"cards": [a, dict(b, focus=t)]}, None, {"plan_pick": "pa"})
    check("Show on my plan's plan comes before the pick", on(jumped, "pb") and "dc-pd-pb-" in jumped)
    check("a pick no longer followed: the first", on(board._plans_html({"cards": [a, b]}, None, {"plan_pick": "gone"}), "pa"))
    check("a catch-up running isn't behind: no dot",
          'class="dot"' not in board._plans_html({"cards": [dict(a, catch={"extra": 5, "until": "Fri"}), b]}, None, {}))
    same = board._plans_html({"cards": [b, dict(card("pc", "Micro"), title="Micro · Priya\u2019s plan")]}, None, {})
    check("two plans of one name: their whole titles", ">Micro · Dre\u2019s plan</a>" in same and ">Micro · Priya\u2019s plan</a>" in same, same[:900])
    # the click, as the board sends it
    conf, saves, swaps = {"period": "today"}, [], []
    saved = (F.cfg, F.save_cfg, F.app.swap)
    try:
        F.cfg = lambda: conf
        F.save_cfg = lambda c: saves.append(dict(c))
        F.app.swap = lambda c=None: swaps.append(1)
        _state["plan_focus"] = {"pa": t}
        dc._on_js(False, as_board("duecrew:planpick:pb"), DeckBrowser())
        check("planpick: kept on this computer, a jumped-to day let go, the board drawn again",
              conf.get("plan_pick") == "pb" and saves and saves[-1].get("plan_pick") == "pb"
              and "plan_focus" not in _state and swaps, (conf, saves, swaps))
        n = len(saves)
        dc._on_js(False, as_board("duecrew:planpick:no<pe"), DeckBrowser())
        dc._on_js(False, as_board("duecrew:planpick"), DeckBrowser())
        check("planpick: anything but a plan id does nothing", conf["plan_pick"] == "pb" and len(saves) == n)
    finally:
        (F.cfg, F.save_cfg, F.app.swap) = saved
        _state.pop("plan_focus", None)


def test_date_details_round5():
    """Round five (Sam: "what happens when you click on a date? worried
    about overlap with the today page"): a plan's date on Today and Upcoming
    opens its details, a click on its name, with what the Plans tab's week
    had for it: Browse its cards, the ones left, Open now, Move…, Skip it,
    Put it back, why it left cards shut. Each click as the board sends it."""
    import due_crew as dc
    from due_crew import due as D, plan_flow as PF
    from aqt.deckbrowser import DeckBrowser
    T = "2026-10-07"
    base = {"pid": "p1", "uid": "u1", "plan": "MS2", "name": "Path <Book> 2", "opens": T, "seen": 18, "total": 42,
            "counted": True, "parts": [], "topics": [["Videos", [["Cardio", 0]]]], "rm": []}
    h = board._due_plan(D._date_row(dict(base, moved=True, why={"lee": 2, "miss": 1}), {}, T))
    check("details: today's date, its name opens them (shut till the click), name escaped",
          '<a class="du-nm" href="#"' in h and '<div class="du-dd" id="dc-dd-p1-u1" hidden>' in h
          and "document.getElementById('dc-dd-p1-u1')" in h and "<b>Path &lt;Book&gt; 2</b>" in h, h)
    check("details: Browse its cards and the ones left, Move…, Put it back, its leeches; no Open now or Skip it today",
          "planbrowse:p1:u1" in h and "Browse 42 cards" in h and "planleft:p1:u1" in h and "24 left" in h
          and "planmove:p1:u1" in h and "planmoveback:p1:u1" in h and "planleech:p1:u1" in h and "1 pick isn" in h
          and "plannow" not in h and "planskip" not in h)
    check("details: today's row keeps its topics on the row (each its Study and Browse, 3.9.5), not again under it",
          h.count("plantopicstudy:p1:u1:0") == 1 and h.count("plantopic:p1:u1:0") == 1)
    check("details: a topic's name shows its two ways beside it (Sam: \"need that option to browse or make the filtered deck\")",
          'id="dc-tp-p1u1-0" hidden><a href="#" title="A filtered deck: ' in h and "pycmd('duecrew:plantopicstudy:p1:u1:0|" in h
          and "document.getElementById('dc-tp-p1u1-0')" in h and ">Browse</a></span>" in h, h)
    check("details: the name stays underlined while they show; the one clicked stays marked (Sam: \"they should underline "
          "and show that they are being selected\")",
          "this.classList.toggle('on',!x.hidden)" in h and h.count("this.classList.add('on')") == 2
          and "a.dc-tpn.on { text-decoration: underline" in board.DUE_CSS and ".du-tpgo a:hover" in board.DUE_CSS, h)
    up = board._due_short(D._date_row(dict(base, opens="2026-10-09", seen=0), {}, T, short=True))
    check("details: an Upcoming date: Open now, Move…, Skip it, Browse, and its topics (the line has none)",
          all(c in up for c in ("plannow:p1:u1", "planmove:p1:u1", "planskip:p1:u1", "planbrowse:p1:u1", "plantopic:p1:u1:0"))
          and "planleft" not in up and "planmoveback" not in up and 'class="du-dd"' in up)
    shut = board._due_plan(D._date_row(dict(base, shut=True), {}, T))
    check("details: a date shut again (Edit › Undo) opens from here", "plannow:p1:u1" in shut)
    own = board._due_short(D._date_row(dict(base, opens="2026-10-09", seen=0, own=True), {}, T, short=True))
    check("details: at my own pace, no Move… or Skip it", "planmove" not in own and "planskip" not in own and "plannow:p1:u1" in own)
    done = board._due_plan(D._date_row(dict(base, seen=42), {}, T))
    check("details: a date done, Browse still, nothing to move", "planbrowse:p1:u1" in done and "planmove" not in done)
    bare = board._due_plan(D._date_row(dict(base, total=0, seen=0, topics=[]), {}, T))
    check("details: nothing in them, the plain name", 'class="du-nm"' not in bare and 'class="du-dd"' not in bare
          and "<b>Path &lt;Book&gt; 2</b>" in bare)
    calls = []
    names = ("open_date", "browse_date", "browse_left", "move_menu", "move_date", "set_skip", "browse_leeches")
    saved = {n: getattr(PF, n) for n in names}
    PF.open_date = lambda pid, uid: calls.append(("open", pid, uid))
    PF.browse_date = lambda pid, uid: calls.append(("browse", pid, uid))
    PF.browse_left = lambda pid, uids: calls.append(("left", pid, tuple(uids)))
    PF.move_menu = lambda pid, uid: calls.append(("move", pid, uid))
    PF.move_date = lambda pid, uid, n: calls.append(("back", pid, uid, n))
    PF.set_skip = lambda pid, uid, on: calls.append(("skip", pid, uid, on))
    PF.browse_leeches = lambda pid, uid: calls.append(("leech", pid, uid))
    try:
        for m in ("plannow:p1:u1", "planbrowse:p1:u1", "planleft:p1:u1", "planmove:p1:u1", "planmoveback:p1:u1",
                  "planskip:p1:u1", "planleech:p1:u1"):
            dc._on_js(False, as_board("duecrew:" + m), DeckBrowser())
    finally:
        for n, f in saved.items():
            setattr(PF, n, f)
    check("details: each click reaches its step", calls == [
        ("open", "p1", "u1"), ("browse", "p1", "u1"), ("left", "p1", ("u1",)), ("move", "p1", "u1"),
        ("back", "p1", "u1", 0), ("skip", "p1", "u1", True), ("leech", "p1", "u1")], calls)


def test_remaining_oct_due():
    """Due, from what the bug run left: an even date while it runs counts
    what has opened so far (and shows under Behind when that's not seen); a
    date with nothing of it in this copy is done once counted, so Due folds."""
    from due_crew import due as D, due_flow as F
    from due_crew.app import _state
    T = "2026-10-05"
    unit = {"id": "e", "name": "Renal", "opens": "2026-10-02", "due": "2026-10-09", "even": True}
    empty = {"id": "z", "name": "Nothing here", "opens": T}
    plan = {"id": "p1", "name": "Big", "doc": {"deck": "Step 1", "units": [unit, empty]}}
    st = {"deck_id": 10, "applied": {}}
    saved = (F._pf, sys.modules["aqt"].mw.col, dict(_state))
    from due_crew import plan_flow as PFL
    F._pf = lambda: types.SimpleNamespace(_state_cfg=lambda: {"p1": st}, followed=lambda: [plan], _deck_ok=lambda col, d: True,
                                          _shut_dates=PFL._shut_dates)
    sys.modules["aqt"].mw.col = object()
    try:
        _state["plan_progress"] = {"p1": {"e": [40, 25, 100], "z": [0, 0, 0]}}
        _state["plan_parts"], _state["plan_sibs"] = {}, {}
        dates, _e, _r = F.plan_dates(T)
        e = next((x for x in dates if x["uid"] == "e"), None)
        check("even date running: shown, and what's due is what has opened (40), not the whole 100",
              e is not None and e["total"] == 40 and e["seen"] == 25, str(dates))
        v = D.view(T, dates, [], {})
        check("even date running: its unseen opened slice is Behind (15 left), not the shut 60",
              [(b["uid"], b["left"]) for b in v["behind_plans"]] == [("e", 15)], str(v["behind_plans"]))
        _state["plan_progress"]["p1"]["e"] = [40, 40, 100]
        dates, _e, _r = F.plan_dates(T)
        v = D.view(T, dates, [], {})
        z = next(x for x in dates if x["uid"] == "z")
        check("nothing of it here: counted, so done", z["counted"] and D.date_state(z, {})[0])
        check("fold: today done, with the slice seen and the empty date counted", D.fold_state(None, v, T) is True)
        _state["plan_progress"] = {}
        dates, _e, _r = F.plan_dates(T)
        z = next(x for x in dates if x["uid"] == "z")
        check("nothing counted yet: not done (the deck hasn't been read)", not D.date_state(z, {})[0])
        st["applied"]["e"] = "skip:x"
        _state["plan_progress"] = {"p1": {"e": [40, 0, 100]}}
        check("a skipped date stays out", all(x["uid"] != "e" for x in F.plan_dates(T)[0]))
        # round five: what a date's details say (board._date_more), as the Plans tab's week had it
        st.update(applied={"e": "sig-e"}, leeches={"e": 3}, missing={"e": [2, 0]})
        plan["moved"] = {"e": 1}
        _state["plan_progress"] = {"p1": {"e": [0, 0, 100], "z": [0, 0, 0]}}
        e = next(x for x in F.plan_dates(T)[0] if x["uid"] == "e")
        row = D._date_row(e, {}, T)
        check("details: a date carries moved, shut (opened, none of it open now), why (leeches, picks missing), own pace",
              e["moved"] and e["shut"] and e["why"] == {"lee": 3, "miss": 2} and e["own"] is False
              and (row["moved"], row["shut"], row["why"], row["own"]) == (True, True, {"lee": 3, "miss": 2}, False), str(e))
        z = next(x for x in F.plan_dates(T)[0] if x["uid"] == "z")
        check("details: one not opened here says no why, isn't shut, wasn't moved", z["why"] is None and not z["shut"]
              and not z["moved"])
    finally:
        F._pf, sys.modules["aqt"].mw.col = saved[0], saved[1]
        _state.clear()
        _state.update(saved[2])


def test_remaining_oct_spread_undo():
    """Plain Undo after a morning that opened a slice of an even date leaves
    it to its schedule (its next morning opens what's due), so the last day
    of a window never stays applied with its cards shut. Other dates keep
    plain Undo's meaning: they stay applied."""
    from due_crew import plan_flow as F
    pc = {"plans": {"p1": {"applied": {"e": "sig-e", "n": "sig-n"}, "src": {"e": [1], "n": [1]}}},
          "plans_opened": {"day": "2026-10-05", "label": "Due Crew: open 2 sets",
                           "units": {"p1": ["e", "n"]}, "spread": {"p1": ["e"]}}}
    saved = (F._pcfg, F._psave, F._undo_ok, F.refresh_progress, F.app.swap, F.cfg, sys.modules.get("aqt.operations"))
    undone = []
    F._pcfg, F._psave, F._undo_ok = (lambda: pc), (lambda d: None), (lambda label: True)
    F.refresh_progress, F.app.swap, F.cfg = (lambda: None), (lambda c, **k: None), (lambda: {})
    sys.modules["aqt.operations"] = types.ModuleType("aqt.operations")  # no CollectionOp: mw.undo, now
    real_undo = getattr(F.mw, "undo", None)
    F.mw.undo = lambda: undone.append(1)
    try:
        F.undo_morning()
        st = pc["plans"]["p1"]
        check("spread undo: the even date goes back to its schedule; the plain date stays applied",
              undone and "e" not in st["applied"] and "e" not in st["src"] and st["applied"].get("n") == "sig-n", str(pc))
    finally:
        F._pcfg, F._psave, F._undo_ok, F.refresh_progress, F.app.swap, F.cfg = saved[:6]
        if saved[6] is None:
            sys.modules.pop("aqt.operations", None)
        else:
            sys.modules["aqt.operations"] = saved[6]
        if real_undo is None:
            del F.mw.undo
        else:
            F.mw.undo = real_undo


def test_plan_updates_v38():
    """3.7.3: an author's save reaches a follower at their next refresh (the
    stamp moved); what it adds to today waits for Open (only on the Decks
    screen, never mid-review); Not today leaves it to tomorrow's morning;
    a follower who chose Hold back has new later cards held too; the
    authors' posts show once; the change note says a date was updated."""
    import due_crew as dc
    from due_crew import plan_flow as F
    from due_crew.app import _state
    from aqt.deckbrowser import DeckBrowser
    if "aqt.reviewer" not in sys.modules:
        sys.modules["aqt.reviewer"] = types.SimpleNamespace(Reviewer=type("Reviewer", (), {}))
    store = world({"dre": "Dre", "maya": "Maya"})
    pid, code = store.add_plan("dre", "Step 1", "Step 1", _plan_units())
    maya = new_client(store, "maya", "Maya")
    labels = [_day(-i) for i in range(7)]
    col = _plan_col()
    col.db.conn.execute("UPDATE cards SET queue = 0, type = 0 WHERE id = 9")  # active and new: holdable
    saved_state = getattr(F.mw, "state", None)
    saved_swap = dc.plan_flow.app.swap
    try:
        with _PlanGlue({"A": maya}, {"A": col}) as g:
            plan, _ = maya.follow_plan(code)
            F.open_schedule = _skip_schedule
            F.on_followed(plan, 10, None, "open")
            st = g.state()["plans"][pid]
            st["held"] = [999]  # this follower chose Hold back
            pc = g.state()
            pc["plans_day"] = _day(0)
            F._psave(pc)
            first = maya.fetch_board(labels, with_decks=True)
            check("updates: the day's first refresh brings the plans and their stamp",
                  first["plans_fresh"] and not first["plans_update"] and maya.session.get("plans_pv"))
            check("updates: nothing moved, nothing comes", not maya.fetch_board(labels)["plans_fresh"])
            units = _plan_units()
            units[1] = dict(units[1], decks=["Step 1::Extras"])          # today's date: card 4 added
            units[4] = dict(units[4], tags=["Step1::Renal", "Step1::Cardiology"])  # a later date: card 9 added
            store.edit_plan(pid, units)
            store.add_post(pid, "dre", "Added the <extras> to today.")
            upd = maya.fetch_board(labels)
            check("updates: the author's save comes with the next refresh", upd["plans_fresh"] and upd["plans_update"]
                  and upd["plans"][0]["posts"][0]["text"] == "Added the <extras> to today.")
            F.mw.state = "review"
            _state["plan_updates"] = {}
            F.maybe_morning(False, fresh=True, update=True)
            check("updates: never mid-review: it waits for the Decks screen",
                  _state.get("plans_midday") is True and 4 not in _open(col) and not _state["plan_updates"]
                  and 9 in _open(col))
            F.mw.state = "deckBrowser"
            F.maybe_morning(False, fresh=True, update=True)
            u = _state["plan_updates"].get(pid) or {}
            check("updates: today's addition waits for Open, counted", u.get("n") == 1 and u.get("units") == ["ar"]
                  and 4 not in _open(col), str(_state["plan_updates"]))
            check("updates: held back, a later date's new card is held too (that was the follower's yes)",
                  9 not in _open(col) and 9 in g.state()["plans"][pid]["held"])
            card = F.card_view(next(p for p in F.followed() if p["id"] == pid), g.state()["plans"][pid], {}, _day(0))
            notes = "".join(board._plan_notes(card, pid))
            check("updates: the line says who added what, with Open and Not today",
                  "Dre added 1 card to <b>Arrhythmia</b>." in notes and "duecrew:planupdopen:" + pid in notes
                  and "duecrew:planupdlater:" + pid in notes, notes)
            check("posts: the authors' words, escaped, with OK", "<b>Dre</b>: Added the &lt;extras&gt; to today." in notes
                  and "duecrew:planpostok:" + pid in notes)
            check("change: a date whose cards changed is said", "updated" in str(card.get("change")), str(card.get("change")))
            from due_crew import due as D
            row = D._date_row({"pid": pid, "uid": "ar", "plan": "Step 1", "name": "Arrhythmia", "opens": _day(0),
                               "seen": 0, "total": 1, "upd": 1}, {}, _day(0))
            h = board._due_plan(row)
            check("updates: Due's row says it, with Open", "+1 added" in h and "duecrew:planupdopen:" + pid in h, h)
            dc._on_js(False, as_board("duecrew:planupdlater:" + pid), DeckBrowser())
            check("updates: Not today: nothing opens, tomorrow's morning will (still applied as it was)",
                  4 not in _open(col) and pid not in _state["plan_updates"]
                  and (g.state()["plans"][pid].get("later") or {}).get("ar") == _day(1)
                  and g.state()["plans"][pid]["applied"].get("ar"))
            g.state()["plans"][pid]["later"].pop("ar")
            F.maybe_morning(False, fresh=True, update=True)
            dc._on_js(False, as_board("duecrew:planupdopen:" + pid), DeckBrowser())
            check("updates: Open opens what it adds, in one step", 4 in _open(col) and pid not in _state["plan_updates"])
            dc._on_js(False, as_board("duecrew:planpostok:" + pid), DeckBrowser())
            card = F.card_view(next(p for p in F.followed() if p["id"] == pid), g.state()["plans"][pid], {}, _day(0))
            check("posts: read once, then gone", card["posts"] == [])
    finally:
        F.mw.state = saved_state
        dc.plan_flow.app.swap = saved_swap
        _state["plan_updates"], _state["plans_midday"] = {}, False


def test_plan_team_v39():
    """3.7.3: a plan's team (opt-in; who showed up today, questions and
    answers, the team's bingo) and its Insights tab (3.7.9's own test). The sync carries the showed-up day only for
    teams I'm on; the board escapes everyone's words; every click reaches
    its handler."""
    import due_crew as dc
    from urllib.parse import quote
    from due_crew import plan_flow as F, team as T, team_flow as TF, app as appmod
    from due_crew.app import _state
    from aqt.deckbrowser import DeckBrowser
    # ---- pure: topics and the table ----
    topics = T.topic_list({"units": [
        {"id": "a", "name": "A", "opens": _day(0), "tags": ["Big::#Video_Series::05_Complement", "Big::#Path_Book_2::Complement"]},
        {"id": "b", "name": "B", "opens": _day(1), "tags": ["Big::#Path_Book_2::Chronic_inflammation"],
         "todo": [{"k": "watch", "t": "Lecture 3", "url": "https://example.com/v"}]}]})
    check("insights: one topic per name, across resources", [(t[1], t[2]) for t in topics]
          == [("Complement", ["Video Series", "Path Book 2"]), ("Chronic inflammation", ["Path Book 2"])], topics)
    check("team: unread is threads that moved since I looked", T.unread({"act": [30, 20, 10]}, 15) == 2 and T.unread(None, 0) == 0)
    ev = {"squares": [{"done": i in (0, 1)} for i in range(8)], "middle": {"done": False}, "lines": 0}
    check("team bingo: the line in words", T.bingo_line(ev) == "2 of 9 · one away from bingo", T.bingo_line(ev))
    # ---- the board: tabs, the team, Insights; everyone's words escaped ----
    bad = "<img src=x onerror=alert(1)>"
    v = {"on": True, "count": 3, "shown": 2, "streak": 4, "more": 0,
         "faces": [{"uid": "kai", "name": bad, "emoji": "🐙", "shown": True}, {"uid": "maya", "name": "Maya", "emoji": "", "shown": False}],
         "asks": [{"id": 7, "uid": "kai", "name": bad, "emoji": "", "text": bad, "at": 1, "act": 1, "topic": bad, "guid": "g1", "ord": 0,
                   "mine": False, "remove": False, "author": False,
                   "replies": [{"id": 8, "uid": "maya", "name": "Maya", "emoji": "", "text": bad, "at": 1, "helped": True,
                                "author": False, "mine": True, "remove": True}]}]}
    html = board._plan_squad_html("p1", {"team": v, "team_state": "ok", "me": "maya", "known": {"down": ["g1"], "have": ["g1"]}})
    check("team: everyone's words escaped", "<img" not in html and html.count("&lt;img") >= 4, html)
    check("team: faces lit or not, You for me, the streak",
          "Showed up today &middot; 2 of 3 &middot; 4 days running" in html and ">You</b>" in html and 'class="face away"' in html)
    check("team: a card question I have down says so, with Answer and See the card",
          "on a card you have down" in html and "duecrew:planteamreply:p1:7" in html
          and "duecrew:planteamcard:p1:7" in html and "duecrew:planteamreport:p1:7" in html)
    check("squad: my own answer can go; Leave and Open the plan are there",
          "duecrew:planteamremove:p1:8" in html and "duecrew:planteamleave:p1" in html and "duecrew:duetab:plans" in html)
    check("3.8.0: who showed up comes first, then Ask the squad and its threads",
          html.index("Showed up today") < html.index("Ask the squad") < html.index("on a card you have down"))
    join = board._plan_squad_html("p1", {"team": {"on": False, "count": 5}, "team_state": "ok"})
    check("squad: not in it, Join its squad says what it shares", "5 in its squad" in join and "duecrew:planteamjoin:p1" in join
          and "Never your numbers" in join)
    card = board._plan_card_html({"id": "p1", "title": "Plan", "tabs": {"unread": 3}})
    check("3.8.0: the plan card has no tabs: Insights is the bubble's, the squad is on Squads",
          "plansub" not in card and "Insights</a>" not in card and "Team" not in card, card)
    line = board._squad_line("p1", {"summary": {"shown": 2, "of": 5, "faces": ["\U0001F419"], "last": {"name": bad}}, "unread": 1})
    check("3.8.0: the plan card's squad line: who showed up, who asked, the way there",
          "Squad: 2 of 5 showed up" in line and "duecrew:squadplan:p1" in line and "&lt;img" in line and "<img" not in line, line)
    check("3.8.0: nothing new, the line says Open", "Open &rsaquo;" in board._squad_line("p1", {"summary": {"shown": 0, "of": 5}, "unread": 0}))
    check("3.8.0: not in it, no squad line", board._squad_line("p1", {"summary": None}) == "")
    sw = board._switcher({"squads": [{"id": "s1", "name": "Pod"}], "current": "s1",
                          "plan_squads": [{"id": "plan:p1", "pid": "p1", "name": bad, "unread": 2}]})
    check("3.8.0: a plan's squad is a pill beside mine, its name escaped, the badge its new threads",
          "duecrew:squad:s1" in sw and "duecrew:squadplan:p1" in sw and "<i>2</i>" in sw and "&lt;img" in sw and "<img" not in sw, sw)
    # ---- the client against the fake Worker, and the glue ----
    store = world({"dre": "Dre", "maya": "Maya", "kai": "Kai"})
    store.today = _day(0)
    pid, code = store.add_plan("dre", "Step 1", "Step 1", _plan_units())
    maya, kai = new_client(store, "maya", "Maya"), new_client(store, "kai", "Kai")
    labels = [_day(-i) for i in range(7)]
    col = _plan_col()
    saved = (appmod._bg, appmod.swap, appmod.sync, TF.client, TF.tooltip, TF.cfg, TF.save_cfg)
    conf = {"cfg": {}}
    try:
        appmod._bg = TF._bg = lambda job, done=None: done(job()) if done else job()
        TF.tooltip = lambda *a, **k: None
        TF.cfg = lambda: conf["cfg"]
        TF.save_cfg = lambda c: conf.update(cfg=c)
        appmod.sync = lambda **k: None
        with _PlanGlue({"A": maya}, {"A": col}):
            TF.client = lambda: maya
            plan, _ = maya.follow_plan(code)
            kai.follow_plan(code)
            F.open_schedule = _skip_schedule
            F.on_followed(plan, 10, None, "open")
            maya.fetch_board(labels, with_decks=True)
            check("team: none until I join; the sync sends no team part",
                  not maya.session.get("teams") and TF.for_sync({}) is None)
            _state["labels"] = labels
            phtml = board._plan_card_html(F.board_view({})["cards"][0])
            check("3.8.0: not in its squad, the plan card asks before it joins (Join its squad)",
                  f"duecrew:planteamjoin:{pid}:ask" in phtml and f"plansub:{pid}:team" not in phtml, phtml[-500:])
            n_log = len(store.log)
            dc._on_js(False, as_board(f"duecrew:plansub:{pid}:team"), DeckBrowser())
            check("3.8.0: an older page's Team link, not in its squad: nothing happens, nothing's asked",
                  len(store.log) == n_log and (_state.get("plan_sub") or {}).get(pid) != "team" and not conf["cfg"].get("squad"))
            check("3.7.6: following alone shares nothing", not store.follows[(pid, "maya")]["share"]
                  and [b for m, pa, b in store.bodies if pa == "/plans/follow"][0].get("team") is False)
            dc._on_js(False, as_board(f"duecrew:planteamjoin:{pid}:ask"), DeckBrowser())
            check("team: Join puts me on it", (pid, "maya") in store.team and pid in maya.session["teams"])
            ps = TF.plan_squads()
            check("3.8.0: its squad is a pill on the Squads tab at once, named for the plan",
                  [(q["id"], q["name"]) for q in ps] == [("plan:" + pid, "Step 1")], ps)
            check("3.8.0: with no squad of my own, it's the one the tab shows", TF.picked(conf["cfg"])["pid"] == pid)
            pline = board._plan_card_html(F.board_view({})["cards"][0])
            check("3.8.0: the plan card's line goes to it", f"duecrew:squadplan:{pid}" in pline and "Join its squad" not in pline)
            n_log = len(store.log)
            dc._on_js(False, as_board(f"duecrew:squadplan:{pid}"), DeckBrowser())
            check("3.8.0: Open picks it on the Squads tab; what the join brought back is fresh, nothing's asked",
                  conf["cfg"].get("squad") == "plan:" + pid and conf["cfg"].get("period") == "squads"
                  and _state["team_view"][pid]["data"]["on"] and len(store.log) == n_log, (conf["cfg"], store.log[n_log:]))
            _state["team_view"].pop(pid)
            dc._on_js(False, as_board(f"duecrew:squadplan:{pid}"), DeckBrowser())
            check("3.8.0: and fetches it when it isn't (one request)",
                  _state["team_view"][pid]["data"]["on"] and len(store.log) == n_log + 1, store.log[n_log:])
            sv = dc._squad_view_with_bingo(conf["cfg"])
            shtml = board._squads_html(sv, conf["cfg"])
            check("3.8.0: the Squads tab draws it: its pill on, who showed up, Ask the squad",
                  sv["kind"] == "plan" and "Showed up today" in shtml and "Ask the squad" in shtml
                  and f"<a class=\"on\" href=\"#\" title=\"Step 1\" onclick=\"pycmd('duecrew:squadplan:{pid}|{KK}')" in shtml, shtml[:600])
            check("3.7.6: and shares my progress, here and on the server",
                  store.follows[(pid, "maya")]["share"] and next(p for p in maya.session["plans"] if p["id"] == pid)["share"])
            # someone who shared before the merge is asked once on the plan card
            store.follows[(pid, "kai")]["teamAsk"] = True
            kplan = next(x for x in kai.fetch_board(labels, with_decks=True)["plans"] if x["id"] == pid)
            kcard = F.card_view(kplan, F.new_state(col, kplan), {}, _day(0))
            khtml = "".join(board._plan_notes(kcard, pid))
            check("3.7.6: the ask: Join this plan's squad?, with Join and No thanks",
                  kcard["team_ask"] and "Join this plan&rsquo;s squad?" in khtml
                  and f"duecrew:planteamjoin:{pid}" in khtml and f"duecrew:planteamno:{pid}" in khtml, khtml[:400])
            TF.client = lambda: kai
            dc._on_js(False, as_board(f"duecrew:planteamno:{pid}"), DeckBrowser())
            TF.client = lambda: maya
            check("3.7.6: No thanks ends the ask without a question, and shares nothing",
                  not store.follows[(pid, "kai")].get("teamAsk") and not store.follows[(pid, "kai")]["share"]
                  and (pid, "kai") not in store.team)
            kai.team_join(pid)
            kai.team_ask(pid, "Does Friday's quiz include complement?")
            dc._on_js(False, as_board(f"duecrew:planteamask:{pid}:" + quote("Same question: does it? <b>")), DeckBrowser())
            asked = [a["text"] for a in store.team_asks]
            check("team: Ask sends the box's words (a colon in them too)", asked[-1] == "Same question: does it? <b>", asked)
            maya.fetch_board(labels)
            check("team: the board carries the counts, the newest question from someone else",
                  maya.session["teams"][pid]["of"] == 2 and maya.session["teams"][pid]["last"]["name"] == "Kai")
            # today, one of the plan's cards answered: showed up rides the sync, once
            cut = fakes.day_cutoff_for(TODAY)
            fakes.add_review(col.db.conn, (cut - 3600) * 1000, ease=1, rtype=1, cid=8)
            fakes.add_review(col.db.conn, (cut - 3 * 86400 - 3600) * 1000, ease=3, rtype=1, cid=8)  # a phone's, come late
            fakes.add_review(col.db.conn, (cut - 20 * 86400) * 1000, ease=3, rtype=1, cid=8)       # too long ago to say
            part = TF.for_sync({})
            check("team: the sync says the days of the last eight I answered a plan card, a late one too",
                  part[pid]["days"] == [_day(-3), _day(0)], part)
            from due_crew import bingo_flow
            check("team: the play is my squad rows' play, the same everywhere (3.7.3)",
                  part[pid].get("play") == bingo_flow.my_play({}), part)
            maya.push(labels, {}, team=part)
            check("team: the fake Worker kept the days", store.team[(pid, "maya")]["days"] == [_day(-3), _day(0)])
            maya.push(labels, {}, team=part)
            check("team: the same part again isn't sent", maya.session.get("team_hash") and store.team[(pid, "maya")]["days"] == [_day(-3), _day(0)])
            check("team: an older server's retry drops the team part", "team" not in maya._without_32({"team": part, "week": {}}))
            _state["labels"] = labels
            card = F.board_view({})["cards"][0]
            check("3.8.0: the plan's card carries its squad line, and no tab (Insights is the bubble's)",
                  card["tabs"]["on"] and card["tabs"]["summary"] and "sub" not in card["tabs"], card["tabs"])
            sq_card = {"wk": "2026-W36", "squares": [], "middle": {"name": "Squad's"}}
            maya.session.pop("bingo", None)
            TF._seed_card({"bingo": {"card": {"wk": "2026-W36", "squares": [], "middle": {"name": "Ask away"}}}})
            seeded = maya.session.get("bingo")
            maya.session["bingo"] = sq_card
            TF._seed_card({"bingo": {"card": {"wk": "2026-W36", "squares": [], "middle": {"name": "Ask away"}}}})
            check("team bingo: someone in no squad gets the week's card from the team's; a squad's card stays",
                  seeded and seeded["middle"]["name"] == "Ask away" and maya.session["bingo"] is sq_card)
            maya.session.pop("bingo", None)
            conf["cfg"]["squad"] = "plan:" + pid
            dc._on_js(False, as_board(f"duecrew:planteamleave:{pid}"), DeckBrowser())
            check("3.8.0: Leave takes its pill away, and the Squads tab back to my own",
                  (pid, "maya") not in store.team and not TF.plan_squads() and not conf["cfg"].get("squad")
                  and dc._squad_view_with_bingo(conf["cfg"]).get("kind") != "plan")
    finally:
        appmod._bg, appmod.swap, appmod.sync, TF.client, TF.tooltip, TF.cfg, TF.save_cfg = saved
        TF._bg = saved[0]
        for k in ("team_view", "team_draft", "insights"):
            _state[k] = {}
        _state["labels"] = []


def test_team_times_377():
    """3.7.7: a Team question's time is today's Unix seconds (past 10**9);
    the cleaner kept 10**9 at most, so every question read "20733d" (since
    1970) and the Team badge never counted anything as new."""
    import time as _time
    from due_crew.backend import shapes as S
    from due_crew import team as T
    now = int(_time.time())
    v = S.clean_team_view({"on": True, "count": 2, "asks": [
        {"id": 1, "uid": "u" * 28, "name": "Ameya", "text": "why?", "at": now - 7200, "act": now - 3600,
         "replies": [{"id": 2, "uid": "u" * 28, "name": "Sam", "text": "this", "at": now - 3600}]}]})
    a = v["asks"][0]
    check("team times: a question keeps its time and its last activity", a["at"] == now - 7200 and a["act"] == now - 3600, a)
    check("team times: a reply keeps its time", a["replies"][0]["at"] == now - 3600, a["replies"])
    check("team times: the row says 1h, not days since 1970", board._team_ago(a["act"], now) == "1h")
    summ = S.clean_teams({"abcdefghij": {"shown": 1, "of": 2, "act": [now - 60, now - 7200]}})["abcdefghij"]
    check("team times: the badge's activity times survive", summ["act"] == [now - 60, now - 7200], summ)
    check("team times: the badge counts what's newer than seen", T.unread(summ, now - 3600) == 1)


def test_team_faces_no_emoji_378():
    """3.7.8: someone with no emoji gets the first letter of their name in a
    circle (not "&#128100;" escaped twice); names stay escaped."""
    html = board._plan_squad_html("p1", {"team": {"on": True, "count": 3, "faces": [
        {"uid": "u1", "name": "BIG DOG", "emoji": "", "shown": False},
        {"uid": "u2", "name": "\u00e9va <b>x</b>", "emoji": "", "shown": True},
        {"uid": "u3", "name": "changster", "emoji": "\U0001F346", "shown": True}], "asks": [
        {"id": 1, "uid": "u1", "name": "reyrey", "emoji": "", "text": "why?", "at": 1, "act": 1, "replies": []}]}, "me": "u9"})
    check("team faces: no emoji is the first letter in a circle", '<span class="ini">B</span>' in html and "#128100" not in html, html[:300])
    check("team faces: a name's first letter, escaped", '<span class="ini">B</span>' in html and '<span class="ini">\u00c9</span>' in html and "&lt;b&gt;x&lt;/b&gt;" in html, html[:400])
    check("team faces: a picked emoji stays", "\U0001F346" in html)
    check("team faces: a question's asker too, small", '<span class="ini sm">R</span>' in html)
    check("initial: no letter or digit is ?", board.initial("  !!") == "?" and board.initial("4chan") == "4" and board.initial("") == "?")


def test_prep_days_are_days_378():
    """3.7.8: "days of prep" counts days, not dates: two dates on one day
    that prep for the same event are one day."""
    from due_crew import plans as P
    doc = {"events": [{"id": "e1", "day": "2026-10-20", "name": "KSA F3-3"}], "units": [
        {"id": "a", "name": "A", "opens": "2026-10-13", "tags": ["x"], "for": "e1"},
        {"id": "b", "name": "B", "opens": "2026-10-13", "tags": ["y"], "for": "e1"},
        {"id": "c", "name": "C", "opens": "2026-10-14", "tags": ["z"], "for": "e1"},
        {"id": "d", "name": "D", "opens": "2026-10-14", "tags": ["w"], "for": "e1"}]}
    pf = P.prep_for(doc, "2026-10-12")
    check("prep: two days left, not four dates", pf and pf["left"] == 2, pf)


def test_plan_load_3781():
    """3.7.81: the plan load in Anki's week. Each card counts on its earliest
    of my dates, a suspended leech never counts, a started note's new sibling
    is seen; a date ahead asks what's still locked, today and before what
    isn't seen; a day's bar is its size against the week's biggest."""
    from due_crew import plans as P
    class Idx:
        # cid: (queue, type); 1-3 seen/open/locked on A; 3 also on B; 7 a leech
        cards = {1: (2, 2), 2: (0, 0), 3: (-1, 0), 4: (-1, 0), 5: (0, 0), 6: (-1, 0), 7: (-1, 0), 8: (0, 0)}
        leech = {7}
        nid_of = {8: 80}
        def started(self):
            return {80}
        def match(self, u, swap, deck):
            return set(u["_c"])
    doc = {"deck": "Step 1", "units": [
        {"id": "b", "name": "B", "opens": "2026-10-09", "_c": [3, 4, 5, 6, 7]},
        {"id": "a", "name": "A", "opens": "2026-10-07", "_c": [1, 2, 3, 8]}]}
    ld = P.load(Idx(), doc)
    check("load: earliest date first, sibling seen", ld["a"] == [2, 1, 1], ld)
    check("load: a card on an earlier date and a suspended leech don't count again", ld["b"] == [0, 1, 2], ld)
    check("load: ahead asks what's locked; today and before what isn't seen",
          P.load_ask([0, 1, 2], "2026-10-09", "2026-10-07") == 2 and P.load_ask([2, 1, 1], "2026-10-07", "2026-10-07") == 2)
    wk = P.week_view({"units": [{"id": "a", "name": "A", "opens": "2026-10-07"}, {"id": "b", "name": "B", "opens": "2026-10-09"}]},
                     {}, "2026-10-07", "2026-10-05", ld=ld)
    wed, fri = wk[2], wk[4]
    check("load: the week carries a day's size and ask", (wed["size"], wed["ask"], fri["size"], fri["ask"]) == (4, 2, 3, 2), (wed, fri))
    check("load: a day without the load stays as it was", wk[0]["size"] is None)
    html = board._week_html({"week": wk, "week_offset": 0}, "pid1")
    check("load: today says what's to go, ahead what's new to me", '2<span class="w"> to go</span>' in html
          and '2<span class="w"> new</span>' in html, html[:500])
    check("load: round five, a day's bar is what of it I've done (no bar of its size, no key)",
          'title="2 of 4"' in html and 'style="width:50%"' in html and 'class="abar' not in html and "new to you" not in html)
    check("load: a date ahead's details say what's new and what's seen before",
          "2 of 3 new &middot; 1 already seen or in your Anki" in html and "2 of 4 seen" in html)
    past = P.week_view({"units": [{"id": "a", "name": "A", "opens": "2026-10-07"}]}, {}, "2026-10-08", "2026-10-05", ld=ld)
    hp = board._week_html({"week": past, "week_offset": 0}, "pid1")
    check("load: a past day says what's left, in the warm colour, its bar too (round five: the day opens, its details Browse)",
          '<span class="late">2<span class="w"> left</span></span>' in hp and 'class="wbar late"' in hp, hp)


def _ahead_sample(exam_in=None, off=None, trust=(0.09, [0.05, 0.07, 0.09, 0.1, 0.11, 0.12]), name_days=True, pause=None):
    """3.9.2: a Reviews ahead view as ahead_flow.deck_view makes one: 40 due today,
    20 a day after, 20 new cards a day, a week of 100 a day behind. pause: the
    pause I made, when off (default: "now", to the exam when there is one)."""
    from due_crew import ahead as A
    hab, extra = A.habits([])
    st = [(0, 1)] * 40 + [(d, 10) for d in range(1, 14) for _ in range(20)]
    if off and pause is None:
        pause = {"kind": "now", "exam": exam_in is not None and exam_in >= 1, "from": off[0]}
    v = A.view(A.existing(st, hab, extra), A.GENERIC, [20.0] * 7, 0, 500, 300, [100] * 7, exam_in=exam_in, off=off,
               off_kind=(pause or {}).get("kind"))
    t0 = datetime.date(2026, 9, 1)
    v.update(did=10, today=t0.isoformat(), days=[(t0 + datetime.timedelta(days=k)).isoformat() for k in range(-7, A.H)],
             exam=exam_in, done=30, own=True, secs=8.0, rate=140, unlocked=300, left=500, off=bool(off), trust=trust,
             pause=pause if off else None)
    return v


def test_insights_379():
    """3.7.9 (mock "Insights"): mine alone, worked out in my Anki. The hero is
    the started cards Anki won't show me before the plan's next event that
    FSRS has under my target by then; Not sticking yet is cards never right in
    a review yet (as of now) plus those forgotten after being right, for a
    topic with 20+ reviewed; my week is in minutes at my own pace; Optimize
    FSRS shows when my newest cards fall 3+ points short with 300+ answers,
    and Not now puts it away for 30 days. 3.8.0: for everyone, a deck at a
    time (You › Insights): with no plan on it, my own exam date aims the box,
    the deck's tags (or subdecks) name the topics, and the week is what Anki
    has due. Every click reaches its handler."""
    import json as _json
    import due_crew as dc
    from aqt import mw
    from aqt.deckbrowser import DeckBrowser
    from due_crew import team as T, team_flow as TF, plan_flow as F, board
    from due_crew.app import _state
    # ---- pure ----
    check("recall: FSRS's curve, 90% at t = s, and FSRS-6's own decay",
          abs(T.recall(10, 10) - 0.9) < 1e-9 and abs(T.recall(10, 10, 0.2) - 0.9) < 1e-9 and T.recall(20, 10) < 0.9)
    ev = [{"id": "q", "day": "2026-09-05", "name": "Quiz"}, {"id": "f", "day": "2026-10-30", "name": "Far"},
          {"id": "g", "day": "2026-08-30", "name": "Gone"}]
    check("aim: the next event in 3 weeks, else a week out", T.aim(ev, "2026-09-01") == ("2026-09-05", "Quiz", 4, "q")
          and T.aim(ev[1:], "2026-09-01") == ("2026-09-08", "", 7, ""))
    check("aim: the dates that prep for it, none without an event",
          T.prep_units([{"id": "a", "for": "q"}, {"id": "b"}, {"id": "c", "for": "f"}], "q") == ["a"]
          and T.prep_units([{"id": "a", "for": "q"}], "") == [])
    check("hero: not shown before the aim and under target, least likely first",
          T.hero({1: (0.95, False), 2: (0.5, False), 3: (0.6, True), 4: (0.7, False)}, 0.9) == [2, 4])
    check("source: the resource and the part above the topic",
          T.source(["Big::#Videos::Basic_Pharmacology::General::Pharmacokinetics"]) == "Videos › General"
          and T.source(["Big::#Video_Series::Renal"]) == "Video Series" and T.source(["Renal"]) == "")
    topics = [("renal", "Renal", [], ["t:r"], []), ("thin", "Thin", [], ["t:t"], [])]
    of = {"t:r": set(range(1, 31)), "t:t": set(range(40, 50))}
    rows = T.not_sticking(topics, lambda t: of[t], set(range(1, 31)) | set(range(40, 50)), {1, 2, 3, 40, 41}, {3, 4, 5})
    check("not sticking: never right yet, plus forgot (not counted twice); a thin topic stays out",
          [(r["name"], r["of"], r["stuck"], r["forgot"], r["cids"]) for r in rows] == [("Renal", 30, 3, 2, [1, 2, 3, 4, 5])], rows)
    check("fsrs: 3+ points short with 300+ answers, else nothing",
          T.fsrs_gap(255, 300, 0.9) == {"right": 85, "n": 300, "target": 90} and T.fsrs_gap(264, 300, 0.9) is None
          and T.fsrs_gap(200, 250, 0.9) is None)
    rd = T.right_days([(1, 0, 3), (1, 0, 1), (2, 0, 1), (3, 20, 3)])
    check("right: the first answer of each card each day; now and before",
          rd["now"] == [1, 2] and rd["before"] == [1, 1] and rd["days"][-1] == 50 and rd["days"][0] is None, rd)
    check("source: 3.8.0, no resource in the tag: the part above the topic",
          T.source(["Path_Book::Inflammation"]) == "Path Book" and T.source(["Renal"]) == "")
    tags_of = {i: ["Step1::Cardio::Heart_failure"] for i in range(1, 13)}
    tags_of.update({i: ["Step1::Cardio::Arrhythmia", "leech"] for i in range(13, 25)})
    tags_of.update({i: ["Step1::#Videos::Renal::Acid_base"] for i in range(30, 52)})
    tags_of.update({i: ["Step1::Other"] for i in range(60, 70)})
    tags_of.update({i: ["Path_Book", "Path_Book::Inflammation"] for i in range(70, 95)})
    topics, groups = T.deck_topics(tags_of, set(tags_of))
    check("deck topics: a thin leaf rolls up its own tag to a level with 20 reviewed; a resource's leaf stands; "
          "never the root, never Anki's leech; a parent tag beside its child counts once",
          sorted(t[1] for t in topics) == ["Acid base", "Cardio", "Inflammation"]
          and groups["Step1::Cardio"] == set(range(1, 25)) and "leech" not in groups, (topics, sorted(groups)))
    check("deck topics: a subdeck's path works the same",
          [t[1] for t in T.deck_topics({i: ["Verbs"] for i in range(25)}, set(range(25)))[0]] == ["Verbs"])
    # ---- the board ----
    bad = "<img src=x onerror=alert(1)>"
    view = {"target": 90, "right": {"now": [86, 100], "before": [87, 100], "days": [80, None, 90]},
            "aim": {"day": "2026-09-04", "name": bad, "in": 3, "scoped": True}, "hero": [1, 2, 3], "behind": 12, "pid": "p1",
            "rows": [{"name": bad, "src": bad, "of": 27, "stuck": 9, "forgot": 1, "cids": [1]}],
            "ahead": _ahead_sample(exam_in=3),
            "fsrs": {"right": 85, "n": 486, "target": 90}, "leeches": 2}
    html = board._insights_html(10, view)
    check("insights: the board escapes the plan's words", "<img" not in html and "&lt;img" in html)
    check("insights: header, hero with Study, behind with Catch up (3.8.0: a deck's id in each command)",
          "<b>86%</b>" in html and "87% the 2 weeks before" in html and "3 cards</a> Anki won&rsquo;t show you before Fri" in html
          and "duecrew:insstudy:10:h" in html and "12 new cards behind" in html and "plancatch" not in html, html[:900])  # (3.9.10: data only)
    check("insights: not sticking yet, one Study a row",
          "Not sticking yet" in html and "<b>10</b> of 27" in html and "duecrew:insstudy:10:0" in html and "Re-watch" not in html)
    check("insights: 3.9.2, Reviews ahead in Your week's place, the exam marked on its day",
          "Reviews ahead" in html and "Your week" not in html and ">Exam<" in html and ">today<" in html, html)
    check("insights: Optimize FSRS and Not now",
          "Newest cards 85% right, Anki aims for 90%" in html and "insfsrs" not in html)  # (3.9.10: said, nothing to press)
    check("insights: 3.8.0, the deck's leeches, from the plan card, with See them",
          "<b>2</b> leeches Anki stopped showing you" in html and "duecrew:insleeches:10" in html)
    check("insights: no plan, no behind line", "behind" not in board._insights_html(10, dict(view, pid=None)))
    loose = board._insights_html(10, dict(view, aim={"day": "2026-09-04", "name": "Quiz", "in": 3, "scoped": False}))
    check("insights: an event no date preps for: the box goes by the day, not the event's name",
          "Before Fri 4 &middot; 3 days" in loose and "Quiz &middot;" not in loose
          and "3 cards</a> Anki won&rsquo;t show you before Fri" in loose, loose[:700])
    mine = board._insights_html(10, dict(view, aim={"day": "2026-09-04", "name": "Your exam", "in": 3, "scoped": False, "kind": "exam"}))
    check("insights: 3.8.0, no plan, my own exam date names the box", "Your exam &middot; Fri 4 &middot; 3 days" in mine, mine[:700])
    check("insights: 3.8.0, the hero's count and each topic's name open their cards in Browse",
          "duecrew:insbrowse:10:h" in html and "duecrew:insbrowse:10:0" in html, html)
    hh = board._insights_html(10, {"hard": {"pct": 22, "n": 640}})
    check("insights: the Hard habit said, with Not now", "You press Hard on 22% of reviews. Anki counts Hard as remembered." in hh
          and "inshardno" not in hh and "instwo" not in hh and "640 reviews in 4 weeks" in hh, hh)
    from due_crew import team as T
    check("insights: the Hard habit needs 15% of 200 answers or more",
          T.hard_habit(30, 200) == {"pct": 15, "n": 200} and T.hard_habit(29, 200) is None and T.hard_habit(100, 199) is None)
    R, sy = "#Big_v1", ["Cardio", "Renal", "Pulm", "Neuro", "GI", "Heme"]
    paths = {c: [f"{R}::^Systems::{sy[c % 6]}::{['Anatomy', 'Pathology'][c // 6 % 2]}",
                 f"{R}::#Lectures::{sy[c % 6]}::01_Sec", f"{R}::#Lectures::{sy[(c + 1) % 6]}::01_Sec",
                 f"{R}::#Library::Article_{c:04d}", f"{R}::#QBank::Step::{100000 + c}", "leech"] for c in range(240)}
    know = {c: (0.5 if c < 60 else 0.95) for c in range(240)}
    tm = T.subjects(paths, know)
    check("map: what's in play split into its subjects, from the tags that sort each card once (no lecture in two systems)",
          [(t["name"], t["n"], t["know"]) for t in tm][:2] == [("Cardio", 40, 84), ("GI", 40, 84)] and len(tm) == 6
          and tm[0]["find"] == {"tags": [f"{R}::^Systems::Cardio"]} and "cids" not in tm[0] and tm[0]["started"] == 40, tm)
    kids = tm[0].get("kids") or []
    check("map: a subject opens into its parts, each with its own way to Browse",
          [(t["name"], t["n"]) for t in kids] == [("Anatomy", 20), ("Pathology", 20)]
          and kids[0]["find"] == {"tags": [f"{R}::^Systems::Cardio::Anatomy"]} and not kids[0].get("kids"), kids)
    # Sam: one block unsuspended, the deck's top level is one big tile: a level down instead
    block = {}
    for c in range(250):
        part = ("Cardio::Physiology", "Cardio::Pathology", "Cardio::Pharm", "Renal::Physiology", "Pulm::Pathology")[
            0 if c < 80 else 1 if c < 150 else 2 if c < 200 else 3 if c < 230 else 4]
        block[c] = [f"{R}::^Systems::{part}"]
    bk = T.subjects(block, {c: 0.9 for c in range(0, 250, 2)}, active=range(250))
    check("map: one block in play: a level down, each named by the level above when two read the same",
          [(t["name"], t["n"], t["started"]) for t in bk] == [("Cardio · Physiology", 80, 40), ("Cardio · Pathology", 70, 35),
                                                              ("Cardio · Pharm", 50, 25), ("Renal · Physiology", 30, 15),
                                                              ("Pulm · Pathology", 20, 10)], bk)
    # Sam: yield tiers split a deck evenly, and say nothing about what's in it
    tiers = ["1-HighYield", "2-RelativelyHighYield", "3-HighYield-temporary", "4-LowerYield", "5-LowYield"]
    yt = {c: [f"{R}::$HighYield::{tiers[c % 5]}", f"{R}::^Systems::{sy[c % 6]}::{['Anatomy', 'Pathology'][c // 6 % 2]}"]
          for c in range(300)}
    yk = {c: 0.9 for c in range(300)}
    ytiles, yways = T.subjects_by(yt, yk)
    check("map: a topic tree beats a flat rating that splits as evenly; the rating stays a way to pick",
          [t["name"] for t in ytiles][:2] == ["Cardio", "GI"] and [(w["name"], w["on"]) for w in yways] == [("Systems", True), ("HighYield", False)]
          and yways[0]["score"] > yways[1]["score"], (ytiles[:2], yways))
    pt, pw = T.subjects_by(yt, yk, by=yways[1]["key"])
    check("map: picked, the other way", sorted(t["name"] for t in pt) == sorted(tiers) and [w["on"] for w in pw] == [False, True], pw)
    check("map: a pick that's no longer there, the best way", T.subjects_by(yt, yk, by="gone")[1][0]["on"] is True)
    fresh = T.subjects({c: [f"Deck::{'Verbs' if c < 30 else 'Nouns' if c < 60 else 'Phrases'}"] for c in range(90)},
                       {c: 0.8 for c in range(30)}, active=range(90))
    check("map: the cards in play, started or not; a subject with none started yet has no score",
          [(t["name"], t["n"], t["started"], t["know"]) for t in fresh] == [("Nouns", 30, 0, None), ("Phrases", 30, 0, None),
                                                                            ("Verbs", 30, 30, 80)], fresh)
    both = {c: ["Pharm::Autonomics"] + (["Micro::Bugs"] if c < 10 else []) for c in range(60)}
    both.update({c: ["Micro::Bugs::Gram"] for c in range(60, 90)})
    both.update({c: ["Physio"] for c in range(90, 115)})
    bt = T.subjects(both, {c: 0.9 for c in both})
    check("map: a card in two subjects counts once, in the bigger",
          [(t["name"], t["n"]) for t in bt] == [("Pharm", 60), ("Micro", 30), ("Physio", 25)], bt)
    root = T.subjects({c: ["Step1::Renal" if c < 30 else "Step1::Cardio"] for c in range(70)}, {c: 0.9 for c in range(70)})
    check("map: every tag under one root: the subjects under it",
          [(t["name"], t["n"], t["find"]["tags"]) for t in root] == [("Cardio", 40, ["Step1::Cardio"]), ("Renal", 30, ["Step1::Renal"])], root)
    ch = T.subjects({c: ["Book::#Ch::%02d_Chapter" % (1 + c // 30)] for c in range(60)}, {c: 0.9 for c in range(60)})
    check("map: names that read the same keep their numbers", [t["name"] for t in ch] == ["01 Chapter", "02 Chapter"], ch)
    sub = T.subjects({c: ["Verbs::Irregular" if c < 25 else "Nouns"] for c in range(50)}, {c: 0.9 for c in range(50)}, decks=True)
    check("map: by subdecks, Browse by the subdeck", [(t["name"], t["find"]) for t in sub]
          == [("Nouns", {"decks": ["Nouns"]}), ("Verbs", {"decks": ["Verbs"]})], sub)
    check("map: nothing to say, no tiles", T.subjects({}, {1: 0.5}) == [] and T.subjects({1: ["leech"]}, {1: 0.5}) == [])
    check("map: where it is, the keys opened that still open",
          T.map_level(tm, ["cardio"]) == ([tm[0]], kids) and T.map_level(tm, ["nope"]) == ([], tm)
          and T.map_level(tm, ["cardio", "anatomy"]) == ([tm[0]], kids) and T.map_level(tm, None) == ([], tm))
    ids = {c: ["Big::#QBank::Step::%d" % (100000 + c), "Big::#Videos::Renal"] for c in range(30)}
    dt, _g = T.deck_topics(ids, set(range(30)), min_n=20)
    check("topics: a question bank's ids are never a topic", [x[1] for x in dt] == ["Renal"], dt)
    check("map: shades at 70, 80, 90", [T.map_shade(k) for k in (69, 70, 85, 90)] == [0, 1, 2, 3])
    leaf = lambda k, name, n, kn: {"key": k, "name": name, "n": n, "know": kn, "find": {"tags": [name]}}  # noqa: E731
    nest = [dict(leaf("cardio", "<b>Cardio", 50, 95), kids=[
                dict(leaf("valves", "Valves", 20, 70), kids=[leaf("mitral", "Mitral", 10, 60), leaf("aortic", "Aortic", 10, 80)]),
                leaf("rhythm", "Rhythm", 30, 85)]),
            leaf("renal", "Renal", 30, 85)]
    mh = board._ins_map(10, nest, "fsrs")
    check("map: tiles sized by cards, shaded, escaped; one that opens says so, one that doesn't opens Browse",
          'class="tm s3"' in mh and 'class="tm s2"' in mh and "flex:50 1" in mh and "&lt;b&gt;Cardio" in mh
          and "<b>Cardio" not in mh and "duecrew:insmap:10:0" in mh and "duecrew:insmap:10:1" in mh
          and mh.count("&rsaquo;</i>") == 1 and "Open it." in mh and "Browse them." in mh
          and "remember now (FSRS)" in mh and 'class="tmt"' not in mh, mh)
    deep = board._ins_map(10, nest, "fsrs", ["cardio", "valves"])
    check("map: opened two down, the trail back (All, Cardio), where I am, Browse all; its tiles",
          'class="tmt"' in deep and ("duecrew:insmapup:10:0|" + KK + "'); return false;\">All</a>") in deep
          and ("duecrew:insmapup:10:1|" + KK + "'); return false;\">&lt;b&gt;Cardio</a>") in deep and "<b>Valves</b> &middot; 20 cards, 70%" in deep
          and "duecrew:insmapall:10" in deep and ">Mitral<" in deep and ">Aortic<" in deep and ">Rhythm<" not in deep, deep)
    nw = board._ins_map(10, [dict(leaf("a", "Verbs", 40, 80), started=20), dict(leaf("b", "Nouns", 30, None), started=0)], "fsrs")
    check("map: none started yet reads new, with its swatch; a bar along the foot says how much is started",
          'class="tm sn"' in nw and "<b>new<small>" in nw and '<i class="sw sn"></i>new' in nw
          and '<i class="tmb" style="width:50%"></i>' in nw and "40 cards, 20 started, 80%" in nw
          and "30 cards, none started yet" in nw and '<i class="sw sn">' not in mh, nw)
    wy = board._ins_map(10, nest, "fsrs", (), [{"key": "a", "name": "Systems", "on": True}, {"key": "b", "name": "<Yield>", "on": False}])
    check("map: more than one way, a pick in the heading, the one on screen chosen, escaped",
          'aria-label="Split by"' in wy and "duecrew:insmapby:10:" in wy and '<option value="0" selected>Systems</option>' in wy
          and '<option value="1">&lt;Yield&gt;</option>' in wy and "by topic, now" not in wy
          and "Split by" not in board._ins_map(10, nest, "fsrs", (), [{"key": "a", "name": "Systems", "on": True}]), wy)
    wy2 = board._ins_map(10, nest, "fsrs", (), [{"key": "a", "name": "Systems", "on": False}, {"key": "b", "name": "A much longer way <x>", "on": True}])
    src = fakes.board_source()
    check("map (3.9.5, Sam: \"the carets are justified to the longest thing\"): the pick shows the way picked, its ▾ beside it, "
          "the select laid over them; no ▾ on the board sits after a select",
          '<span class="dc-wp"><b>Systems</b><i aria-hidden="true">&#9662;</i><select' in wy
          and '<b>A much longer way &lt;x&gt;</b><i aria-hidden="true">&#9662;</i>' in wy2
          and "</select><i" not in src and "#due-crew .dc-wp > select { position: absolute;" in board._css({}), wy2)
    check("map: one tile says nothing", board._ins_map(10, nest[:1], "fsrs") == ""
          and "right in their reviews these 4 weeks" in board._ins_map(10, nest, "right"))
    check("insights: nothing yet says so", "Insights fill in after a week of reviews." in board._insights_html(10, {"right": {"now": [1, 2]}}))
    ins = {"decks": [{"did": 10, "name": "Step 1", "full": "Step 1"}, {"did": 20, "name": bad, "full": bad}],
           "did": 10, "exam": False, "plan": {"id": "p1", "name": bad}, "view": view}
    yh = board._you_insights(ins)
    check("you › insights: the decks picked as a squad is, mine escaped",
          'class="dc-sw"' in yh and ('<a class="on" href="#" title="Step 1" onclick="pycmd(\'duecrew:insdeck:10|' + KK + '\')') in yh
          and "duecrew:insdeck:20" in yh and "<img" not in yh, yh[:600])
    check("you › insights: the deck's, plan or not: no way off to the plan, my exam date right here",
          "duecrew:duetab:plans" not in yh and "duecrew:exampick" in yh and "<img" not in yh)
    lone = board._you_insights(dict(ins, decks=ins["decks"][:1], plan=None))
    check("you › insights: one deck, no picker; no plan, my exam date set right here (3.9.5: in a Qt calendar)",
          'class="dc-sw"' not in lone and "duecrew:exampick" in lone and 'type="date"' not in lone
          and "showPicker" not in lone and "settings:privacy" not in lone)
    mine = board._you_insights(dict(ins, plan=None, exam="2026-11-30"))
    check("you › insights: my exam date shows in it, on every deck; one that isn't a day, not at all",
          ">Exam Mon 30 Nov</a>" in mine and 'class="dc-sw"' in mine and "exampick" in yh
          and "Add exam date" in board._you_insights(dict(ins, plan=None, exam='"><img x>'))
          and "<img x>" not in board._you_insights(dict(ins, plan=None, exam='"><img x>')))
    check("you › insights: 3.8.0 (Sam), one deck still says its name; no date, Add exam date opens the picker",
          '<b class="ideck" title="Step 1">Step 1</b>' in lone and ">Add exam date</a>" in lone and "duecrew:exampick" in lone
          and "setexam:off" not in lone)
    check("you › insights: a date set reads as the day, with × to take it off",
          ">Exam Mon 30 Nov</a>" in mine and "duecrew:setexam:off" in mine and "Add exam date" not in mine, mine[:900])
    check("you › insights: no decks reviewed yet", "Insights fill in" in board._you_insights({"decks": []}))
    # ---- the glue, on a collection ----
    conn = sqlite3.connect(":memory:")
    fakes.make_collection(conn)
    cut = fakes.day_cutoff_for(TODAY)
    at = lambda days: (cut - days * 86400 - 3600) * 1000  # noqa: E731
    for i in range(30):  # Renal: 200-209 Anki shows before the quiz; 210-219 weak and not shown; 220-229 strong
        cid = 200 + i
        fakes.add_card(conn, cid, did=10, ctype=2, queue=2, ivl=3, tags="Step1::Renal", due=1001 if i < 10 else 1010)
        conn.execute("UPDATE cards SET data = ? WHERE id = ?", (_json.dumps({"s": 1 if 10 <= i < 20 else 100}), cid))
        if i < 8:
            fakes.add_review(conn, at(2), ease=1, cid=cid)                   # never right yet
        elif 10 <= i < 13:
            fakes.add_review(conn, at(20), ease=3, cid=cid)                  # right once...
            fakes.add_review(conn, at(2), ease=1, cid=cid)                   # ...then forgot
        else:
            fakes.add_review(conn, at(2), ease=3, cid=cid)
    for i in range(10):  # other cards in the deck: my newest come back 80% right, 300 answers
        fakes.add_card(conn, 300 + i, did=10, ctype=2, queue=2, ivl=2, tags="Step1::Other", due=1020)
    for j in range(300):
        fakes.add_review(conn, at(1 + j % 6), ease=1 if j % 5 == 0 else 3, cid=300 + j % 10, last_ivl=2, time_ms=9000)
    for i in range(50):  # new cards started 10 days ago: 3 answers each in their first week
        fakes.add_card(conn, 400 + i, did=10, ctype=2, queue=2, ivl=10, tags="Step1::Started", due=1030)
        for d in (10, 9, 8):
            fakes.add_review(conn, at(d), ease=3, rtype=0 if d == 10 else 1, cid=400 + i, time_ms=18000)
    for i in range(20):  # tomorrow's date: still locked
        fakes.add_card(conn, 500 + i, did=10, queue=-1, tags="Step1::Later")
    fakes.add_card(conn, 700, did=10, ctype=2, queue=-1, tags="Step1::Renal leech", lapses=8)  # a leech Anki set aside
    for i in range(25):  # another deck, reviewed less: French, its cards in subdecks and untagged
        fakes.add_card(conn, 800 + i, did=21 if i < 13 else 22, ctype=2, queue=2, ivl=5, due=1040)
        fakes.add_review(conn, at(3), ease=1 if i < 13 else 3, cid=800 + i)
    col = fakes.FakeCol(conn, cut)
    col.decks = fakes.FakeDecks({10: "Step 1", 20: "French", 21: "French::Verbs", 22: "French::Nouns", 30: "Unused"})
    col.conf["fsrs"] = True
    plan = {"id": "pI", "name": "Step", "doc": {"deck": "Step 1",
            "events": [{"id": "q", "day": _day(3), "name": "Quiz"}],
            "units": [{"id": "r", "name": "Renal", "opens": _day(-3), "tags": ["Step1::#Videos::Kidney::Renal"]},
                      {"id": "l", "name": "Later", "opens": _day(1), "tags": ["Step1::Later"]}]}}
    conn.execute("UPDATE notes SET tags = ' Step1::#Videos::Kidney::Renal ' WHERE id BETWEEN 200 AND 229")
    pc, conf = {}, {}
    saved = (TF._plan, F._state_cfg, F.followed, F._today, F._pcfg, F._psave, F._filtered, F._browse, mw.col, TF.app.swap,
             TF.cfg, TF.save_cfg, dc.cfg, dc.save_cfg)
    built, shown = [], []
    try:
        TF._plan = lambda pid: F.mine(plan) if pid == "pI" else None
        F._state_cfg = lambda c=None: {"pI": {"deck_id": 10}}
        F.followed = lambda: [plan]
        F._today = lambda: _day(0)
        F._pcfg = lambda: pc
        F._psave = lambda d: None
        F._filtered = lambda c, name, cids, **kw: built.append((name, sorted(cids))) or False
        F._browse = lambda cids, q=None, empty="": shown.append(sorted(cids) if cids else empty)
        TF.app.swap = lambda c=None: None
        TF.cfg = dc.cfg = lambda: conf
        TF.save_cfg = dc.save_cfg = lambda c, **k: None
        mw.col = col
        _state["insights"], _state["you_decks"] = {}, None
        # the plan's deck: its exam, its topics
        v = TF.insights(10, "pI")
        check("glue: the hero is the weak cards Anki won't show before the quiz", v.get("hero") == list(range(210, 220)), v.get("hero"))
        check("glue: Renal not sticking: 8 never right, 3 forgot, of 30", [(r["name"], r["of"], r["stuck"], r["forgot"])
              for r in v.get("rows") or []] == [("Renal", 30, 8, 3)], v.get("rows"))
        check("glue: Optimize FSRS from my newest cards", v.get("fsrs") == {"right": 80, "n": 300, "target": 90}, v.get("fsrs"))
        check("glue: 3.9.2, under 100 cards started, no Reviews ahead (a forecast needs a past)",
              v.get("ahead") is None and "week" not in v, sorted(v))
        check("glue: not behind; the plan named for its Catch up", v.get("behind") == 0 and v.get("pid") == "pI")
        check("glue: 3.8.0, the deck's suspended leeches", v.get("leeches") == 1, v.get("leeches"))
        dc._on_js(False, as_board("duecrew:insstudy:10:h"), DeckBrowser())
        dc._on_js(False, as_board("duecrew:insstudy:10:0"), DeckBrowser())
        check("glue: no date preps for the quiz: the whole plan, the box by the day", v["aim"]["scoped"] is False)
        check("glue: Study builds the hero's deck and a topic's", built == [("Due Crew::Before Fri 4", list(range(210, 220))),
              ("Due Crew::Renal", [200, 201, 202, 203, 204, 205, 206, 207, 210, 211, 212])], built)
        dc._on_js(False, as_board("duecrew:insbrowse:10:h"), DeckBrowser())
        dc._on_js(False, as_board("duecrew:insbrowse:10:0"), DeckBrowser())
        check("glue: 3.8.0, Browse: the box's cards; a topic's name, all of its cards (Study, the hard ones)",
              shown == [list(range(210, 220)), list(range(200, 230))], shown)
        n = len(built) + len(shown)
        for cmd in ("insstudy:x:h", "insstudy:10:zz", "insbrowse:10:", "insdeck:", "youins:abc"):
            dc._on_js(False, as_board("duecrew:" + cmd), DeckBrowser())
        check("glue: a command without a deck's id (or a row) does nothing", len(built) + len(shown) == n)
        lines = [{"id": "pI"}, {"id": "pX"}, {"id": "pI", "paused": True}]
        TF.plan_lines(lines)
        check("glue: You › Plans, the plan's line from its deck's Insights (none for a plan not here, or paused)",
              lines[0].get("ins") == {"n": 10, "did": 10, "day": _day(3), "name": ""} and "ins" not in lines[1]
              and "ins" not in lines[2], lines)
        # the quiz's prep dates: only their cards, the box by the event's name
        plan["doc"]["units"][1]["for"] = "q"  # Later: nothing started, so nothing to study before it
        _state["insights"].pop(10, None)
        v2 = TF.insights(10, "pI")
        check("glue: an event with prep dates counts only theirs", v2["aim"]["scoped"] and not v2.get("hero"), v2.get("hero"))
        plan["doc"]["units"][0]["for"] = "q"
        _state["insights"].pop(10, None)
        v3 = TF.insights(10, "pI")
        built.clear()
        dc._on_js(False, as_board("duecrew:insstudy:10:h"), DeckBrowser())
        check("glue: Renal preps for the quiz too: its weak cards, the deck by the event's name",
              v3.get("hero") == list(range(210, 220)) and built == [("Due Crew::Before Quiz", list(range(210, 220)))], built)
        # the same deck with no plan: my exam date, the deck's own tags, what Anki has due
        for i in range(12):
            fakes.add_card(conn, 600 + i, did=10, queue=0, tags="Step1::New")
        col.decks.config_dict_for_deck_id = lambda did: {"new": {"perDay": 5}, "desiredRetention": 0.9}
        w0 = TF.insights(10, None, _day(3))
        hero = set(w0.get("hero") or [])
        check("glue, no plan: my exam date aims the box over the whole deck",
              {k: x for k, x in w0["aim"].items() if k != "today"} == {"day": _day(3), "name": "Your exam", "in": 3, "scoped": False,
                                                                       "kind": "exam", "since": "", "since_why": "", "since_pick": "",
                                                                       "checked": True}
              and len(str(w0["aim"].get("today"))) == 10  # the scope's picker stops at today
              and set(range(210, 220)) <= hero and not hero & (set(range(200, 210)) | set(range(220, 230)) | set(range(500, 520))),
              (w0["aim"], sorted(hero)))
        check("glue, no plan: the deck's tags name the topics, the resource's part as the source",
              [(r["name"], r["src"], r["of"], r["stuck"], r["forgot"]) for r in w0.get("rows") or []]
              == [("Renal", "Videos › Kidney", 30, 8, 3)], w0.get("rows"))
        check("glue, no plan: no behind", "behind" not in w0 and "pid" not in w0, sorted(w0))
        soon, late = TF.insights(10, "pI", _day(2))["aim"], TF.insights(10, "pI", _day(10))["aim"]
        check("glue: with a plan, my own exam date aims the box when it's sooner, over the whole deck; else the plan's quiz",
              (soon["kind"], soon["day"], soon["scoped"]) == ("exam", _day(2), False)
              and (late["kind"], late["name"], late["day"]) == ("", "Quiz", _day(3)), (soon, late))
        check("glue, no plan: no exam date, a week out", TF.insights(10, None, "")["aim"]["kind"] == ""
              and TF.insights(10, None, "")["aim"]["day"] == _day(7))
        fr = TF.insights(20)
        check("glue, no plan: untagged cards, the subdecks name the topics",
              [(r["name"], r["of"], r["stuck"]) for r in fr.get("rows") or []] == [("Verbs", 13, 13)] or
              [(r["name"], r["of"]) for r in fr.get("rows") or []] == [], fr.get("rows"))
        check("glue: a deck that isn't there has none", TF.insights(99) == {})
        # the picker: by deck, the ones I've reviewed most first; a plan on one says so (pid)
        decks = TF.you_decks()
        check("you decks: my reviewed roots, by reviews, a plan's marked",
              [(d["did"], d["name"], d["pid"]) for d in decks] == [(10, "Step 1", "pI"), (20, "French", None)], decks)
        yv = TF.you_view({})
        check("you view: the first deck, sharpened by the plan on it", yv["did"] == 10 and "plan" not in yv
              and yv["view"].get("pid") == "pI")
        dc._on_js(False, as_board("duecrew:insdeck:20"), DeckBrowser())
        check("picker: a deck's click picks it (this computer's)", conf.get("ins_deck") == 20)
        yv = TF.you_view(conf)
        check("you view: the deck picked, no plan on it", yv["did"] == 20 and not yv["view"].get("pid"))
        dc._on_js(False, as_board("duecrew:insdeck:30"), DeckBrowser())
        check("picker: a deck it doesn't list isn't picked", conf.get("ins_deck") == 20)
        conf.update(hidden_tabs=["insights", "decks"], due_tab="today")
        _state["labels"] = [_day(0)]
        dc._on_js(False, as_board("duecrew:youins:30"), DeckBrowser())
        check("youins: the bubble opens on Insights, unfolded and shown again, the deck picked and listed",
              conf.get("due_tab") == "insights" and conf.get("due_fold") == {"day": _day(0), "folded": False}
              and conf.get("hidden_tabs") == ["decks"] and conf.get("ins_deck") == 30
              and 30 in [d["did"] for d in TF.you_decks()], conf)
        _state["you_decks"] = None
        check("youins: the deck picked stays listed when the list is worked out again", 30 in [d["did"] for d in TF.you_decks()])
        check("glue: no Hard habit on this deck", not TF.insights(10, "pI").get("hard"))
        for j in range(120):
            fakes.add_review(conn, at(4), ease=2, cid=400 + j % 50, time_ms=5000)
        _state["insights"] = {}
        h = TF.insights(10, "pI").get("hard")
        check("glue: the Hard habit, the deck's review answers in 4 weeks", bool(h) and h["pct"] >= 15 and h["n"] >= 200, h)
        dc._on_js(False, as_board("duecrew:inshardno:10"), DeckBrowser())
        check("glue: Not now puts the Hard habit away for a while", pc.get("ins_hard_hide") and not TF.insights(10, "pI").get("hard"))
        # 3.8.0: the topic map
        vp, vd = TF.insights(10, "pI"), TF.insights(10)
        check("map: the deck's cards in play by its own tags, plan or not, new ones too; all under one root, what's under it",
              [(t["name"], t["n"]) for t in vp.get("map") or []] == [("Started", 50), ("New", 12), ("Other", 10)]
              and vp.get("map_by") == "right" and [t["name"] for t in vd.get("map") or []] == ["Started", "New", "Other"]
              and 0 <= vp["map"][0]["know"] <= 100 and vp["map"][1]["know"] is None, vp.get("map"))
        shown.clear()
        dc._on_js(False, as_board("duecrew:insmap:10:2"), DeckBrowser())
        check("map: a tile that doesn't split opens all of its cards in Browse", shown == [list(range(300, 310))], shown)
        # a deck whose subjects split again: Cardio opens into Valves and Rhythm
        for i in range(80):  # a lecture's tag on some: the systems sort them all
            tag = ("Med::^Sys::Cardio::Valves", "Med::^Sys::Cardio::Rhythm", "Med::^Sys::Renal::Tubule", "Med::^Sys::Pulm")[i // 20]
            fakes.add_card(conn, 900 + i, did=30, ctype=2, queue=2, ivl=4, due=1050,
                           tags=tag + (" Med::#Lectures::L%d" % (i % 7) if i % 3 == 0 else "")
                           + (" Med::$Yield::High" if i % 2 else " Med::$Yield::Low"))
            fakes.add_review(conn, at(2), ease=3, cid=900 + i)
        fakes.add_card(conn, 990, did=30, tags="Med::^Sys::Cardio::Valves")  # new: not on the map, in Browse
        m = TF.insights(30).get("map") or []
        check("map: the tags that sort every card in play (not the lectures); Cardio splits again",
              [(t["name"], t["n"], t["started"], bool(t.get("kids"))) for t in m]
              == [("Cardio", 41, 40, True), ("Pulm", 20, 20, False), ("Renal", 20, 20, False)], m)
        _state.pop("map_at", None)
        dc._on_js(False, as_board("duecrew:insmap:30:0"), DeckBrowser())
        yv = TF.you_view(dict(conf, ins_deck=30))
        check("map: a tile that splits opens into its parts, the trail back above them",
              (_state.get("map_at") or {}).get(30) == ["cardio"] and yv["view"].get("map_at") == ["cardio"]
              and ">Rhythm<" in board._ins_map(30, m, "fsrs", yv["view"]["map_at"]), _state.get("map_at"))
        shown.clear()
        dc._on_js(False, as_board("duecrew:insmap:30:0"), DeckBrowser())
        dc._on_js(False, as_board("duecrew:insmapall:30"), DeckBrowser())
        check("map: inside, a part opens its cards; Browse all, the open subject's, new ones too",
              shown == [list(range(900, 920)) + [990], list(range(900, 940)) + [990]], shown)
        dc._on_js(False, as_board("duecrew:insmapup:30:0"), DeckBrowser())
        check("map: All goes back to the top", (_state.get("map_at") or {}).get(30) == [])
        ways = TF.insights(30).get("map_ways") or []
        check("map: its ways, the systems first, the yield tiers to pick (3.9.2: and when I started them)",
              [(w["name"], w["on"]) for w in ways] == [("Sys", True), ("Yield", False), ("When you started them", False)], ways)
        dc._on_js(False, as_board("duecrew:insmap:30:0"), DeckBrowser())
        dc._on_js(False, as_board("duecrew:insmapby:30:1"), DeckBrowser())
        yv = TF.you_view(dict(conf, ins_deck=30))
        check("map: picked by Yield, this deck's, kept on this computer; it starts from the top",
              (conf.get("ins_map_by") or {}).get("30") == ways[1]["key"] and sorted(t["name"] for t in yv["view"].get("map") or [])
              == ["High", "Low"] and not (_state.get("map_at") or {}).get(30), (conf.get("ins_map_by"), yv["view"].get("map")))
        dc._on_js(False, as_board("duecrew:insmapby:30:9"), DeckBrowser())
        check("map: no such way, nothing", (conf.get("ins_map_by") or {}).get("30") == ways[1]["key"])
        dc._on_js(False, as_board("duecrew:insmapby:30:0"), DeckBrowser())
        # 3.8.0: Share › on the map: the card of the level on screen, made here
        made = []

        class Card:
            def __init__(self, parent, title, day, tiles, by, prev, since, tooltip=None, part=False):
                made.append((title, day, [t["name"] for t in tiles], by, prev, since, part))

            def show(self):
                made.append("shown")
        sys.modules["due_crew.ui.map_card_dialog"] = types.SimpleNamespace(MapCardDialog=Card)
        try:
            TF.you_view(dict(conf, ins_deck=30))
            dc._on_js(False, as_board("duecrew:insmapshare:30"), DeckBrowser())
            check("share: the deck's map, its name and today, shown", made and made[0][:4] == ("Unused", _day(0), ["Cardio", "Pulm", "Renal"], "right")
                  and made[-1] == "shown", made)
            check("share: no map a week old yet, no change", made[0][4] is None and made[0][5] == "")
            sys30 = ((pc.get("map_snaps") or {}).get("30") or {}).get("med::^sys|due") or []
            check("share: today's map kept for next week's change, by way, in this profile's plans file",
                  [x["day"] for x in sys30] == [_day(0)] and "med::$yield|due" in pc["map_snaps"]["30"], pc.get("map_snaps"))
            sys30[0]["day"] = _day(-8)
            _state["insights"].pop(30, None)
            TF.you_view(dict(conf, ins_deck=30))
            dc._on_js(False, as_board("duecrew:insmapshare:30"), DeckBrowser())
            check("share: a week on, the change since then; today's kept too", made[-2][4] and made[-2][5] == _day(-8)
                  and [x["day"] for x in pc["map_snaps"]["30"]["med::^sys|due"]] == [_day(-8), _day(0)], (made[-2], pc["map_snaps"]["30"]))
            dc._on_js(False, as_board("duecrew:insmap:30:0"), DeckBrowser())
            dc._on_js(False, as_board("duecrew:insmapshare:30"), DeckBrowser())
            check("share: opened, the parts on screen, named by the trail; the change is the deck's level only",
                  made[-2][0] == "Unused · Cardio" and made[-2][2] == ["Valves", "Rhythm"] and made[-2][4] is None
                  and made[-2][6] is True and made[0][6] is False, made[-2])
            dc._on_js(False, as_board("duecrew:insmapup:30:0"), DeckBrowser())
        finally:
            sys.modules.pop("due_crew.ui.map_card_dialog", None)
        dc._on_js(False, as_board("duecrew:insmap:30:9"), DeckBrowser())
        dc._on_js(False, as_board("duecrew:insmapall:30"), DeckBrowser())
        check("map: no such tile, or nothing open: nothing", len(shown) == 2 and not (_state.get("map_at") or {}).get(30))
        dc._on_js(False, as_board("duecrew:insfsrsno:10"), DeckBrowser())
        check("glue: Not now puts Optimize FSRS away, on every deck", pc.get("ins_fsrs_hide") and not TF.insights(10, "pI").get("fsrs")
              and not TF.insights(10).get("fsrs"))
        opened = []
        sys.modules["aqt.deckoptions"] = types.SimpleNamespace(display_options_for_deck_id=opened.append)
        dc._on_js(False, as_board("duecrew:insfsrs:10"), DeckBrowser())
        check("glue: Optimize FSRS opens the deck's options", opened == [10], opened)
        dc._on_js(False, as_board("duecrew:setexam:2026-11-30"), DeckBrowser())
        check("youins: the exam date set in Insights is my exam date, there too",
              conf.get("exam_date") == "2026-11-30" and TF.you_view(conf)["exam"] == "2026-11-30", conf.get("exam_date"))
        dc._on_js(False, as_board("duecrew:setexam:off"), DeckBrowser())
        check("youins: cleared there, it's gone", conf.get("exam_date") == "")
    finally:
        (TF._plan, F._state_cfg, F.followed, F._today, F._pcfg, F._psave, F._filtered, F._browse, mw.col, TF.app.swap,
         TF.cfg, TF.save_cfg, dc.cfg, dc.save_cfg) = saved
        sys.modules.pop("aqt.deckoptions", None)
        _state["insights"], _state["you_decks"], _state["labels"] = {}, None, []


def test_tidy_filtered_v380():
    """3.8.0: the morning clears the filtered decks Due Crew built once
    they're empty; a deck with cards, or one it didn't build, stays."""
    from due_crew import plans as P, plan_flow as F
    rows = [(1, "Due Crew · Renal", 0), (2, "Due Crew::Today's misses", 3), (3, "Checkpoint · Cardio", 0),
            (4, "My cram", 0), (5, "Checkpoint · Pulm", 4), (6, "Due Crew::Renal", 0)]
    check("tidy: ours and empty go; with cards, or not ours, stay",
          P.tidy(rows, [3, 5]) == [1, 3, 6])
    check("tidy: nothing built, only the Due Crew names", P.tidy(rows, []) == [1, 6])
    check("tidy: the parent goes with the last of what's under it, if Due Crew made it, and empty",
          P.tidy(rows, [8], (8, [6], 0)) == [1, 6, 8] and P.tidy(rows, [8], (8, [2, 6], 0)) == [1, 6]
          and P.tidy(rows, [], (8, [6], 0)) == [1, 6] and P.tidy(rows, [8], (8, [6], 2)) == [1, 6]
          and P.tidy([], [8], (8, [], 0)) == [8])

    class Decks:
        def __init__(self):
            self.d = {1: ("Due Crew · Renal", True), 2: ("Due Crew::Today's misses", True),
                      3: ("Due Crew::Checkpoint · Cardio", True), 4: ("My cram", True), 6: ("Due Crew::Renal", True),
                      8: ("Due Crew", False), 9: ("Big Step 1", False)}
            self.removed = []

        def all_names_and_ids(self, skip_empty_default=False, include_filtered=True):
            return [types.SimpleNamespace(id=k, name=n) for k, (n, dyn) in self.d.items() if include_filtered or not dyn]

        def id_for_name(self, name):
            return next((k for k, (n, _d) in self.d.items() if n == name), None)

        def deck_and_child_ids(self, did):
            top = self.d[did][0]
            return [did] + [k for k, (n, _d) in self.d.items() if n.startswith(top + "::")]

        def remove(self, ids):
            self.removed.append(list(ids))
            for i in ids:
                self.d.pop(i, None)

    cards = {2: 3}
    emptied = []
    col = types.SimpleNamespace(decks=Decks(), db=types.SimpleNamespace(scalar=lambda q, *a: cards.get(a[0], 0)),
                                sched=types.SimpleNamespace(empty_filtered_deck=lambda d: emptied.append(d)))
    pc = {"built": [3, 2, 8, 77, "x"], "misses_day": "2026-10-14"}
    saved = (F._pcfg, F._psave, F._today)
    try:
        F._pcfg, F._psave, F._today = (lambda: pc), (lambda c: None), (lambda: "2026-10-14")
        n = F.tidy_decks(col)
        check("tidy: one step, the empty ones of ours; the parent stays while a deck under it has cards",
              n == 3 and col.decks.removed == [[1, 3, 6]] and pc["built"] == [2, 8], (n, col.decks.removed, pc))
        check("tidy: 3.9.5, Today's misses (a deck Due Crew no longer makes) is emptied back into its decks", emptied == [2], emptied)
        pc["until"] = {"2": "2026-10-14"}
        F._today = lambda: "2026-10-15"
        F.tidy_decks(col)
        check("tidy: 3.9.5, a deck past its day (a quiz gone) is emptied back too", emptied == [2, 2, 2], emptied)
        cards[2] = 0
        n = F.tidy_decks(col)
        check("tidy: the last one under it studied, it goes with the parent, one step",
              n == 2 and col.decks.removed[1:] == [[2, 8]] and pc["built"] == [] and 8 not in col.decks.d, (n, col.decks.removed, pc))
        check("tidy: again, nothing to do", F.tidy_decks(col) == 0 and len(col.decks.removed) == 2)
        F._note_built(5)
        F._note_built(2)
        check("tidy: a deck built is remembered once, newest last", pc["built"] == [5, 2], pc)
    finally:
        F._pcfg, F._psave, F._today = saved


def test_due_repeat_site_twin():
    """3.8.0: the site's Due panel reads a repeating to-do as due.on_day does
    (dueRepeats, dueOnDay in app.js). Needs node."""
    import shutil
    import subprocess
    from due_crew import due as D
    node = shutil.which("node")
    if not node:
        print("SKIP due repeat site twin: no node")
        return
    js = open(os.path.join(REPO, "site", "public", "app.js"), encoding="utf-8").read()
    src = js[js.index("const parseIso"):js.index("\n", js.index("const parseIso"))] + "\n" + \
        js[js.index("function dueRepeats"):js.index("/** Due, as the site can show it")]
    items = [{"t": "a", "d": "2026-10-03", "r": "0"}, {"t": "b", "d": "2026-10-10", "r": "56"}, {"t": "c", "d": "", "r": "0123456"},
             {"t": "d", "d": "2026-10-05"}, {"t": "e", "d": "2026-10-05", "r": "9"}, {"t": "f", "d": "2026-10-05", "r": 3}]
    days = ["2026-10-03", "2026-10-04", "2026-10-05", "2026-10-10", "2026-10-11", "2026-10-12"]
    want = [[D.on_day(dict(it, done="", id="x", r=D._rule(it.get("r")) or None) if D._rule(it.get("r")) else dict(it, done=""), day)
             if D._rule(it.get("r")) else False for day in days] for it in items]
    prog = (src + "var items = " + json.dumps(items) + ", days = " + json.dumps(days) + ";"
            "console.log(JSON.stringify(items.map(function (x) { return days.map(function (d) { return dueOnDay(x, d); }); })));")
    out = subprocess.run([node, "-e", prog], capture_output=True, text=True, timeout=60)
    try:
        got = json.loads(out.stdout)
    except ValueError:
        got = None
    check("due: the site puts a repeat on the days due.on_day does", got == want, (got, want, out.stderr[:300]))
    check("due: the site counts a repeat open, and a ticked one not",
          "(x) => x && (dueRepeats(x) || !x.done)" in js and "!(set.due_ticks || {})[x.id]" not in js)


def test_no_jumps_v380():
    """3.8.0: a redraw under the pointer doesn't make the You box or the board
    shorter (each holds its height until the pointer leaves); a part still
    fetching holds it either way; Hide folds at once. _swap draws through it."""
    js = board.swap_js('<div id="due-crew">x</div>')
    init_src = srcs.glue_src()
    check("no jumps: _swap redraws through swap_js", "board.swap_js(html_out, have)" in init_src and "replaceChild" in js)
    check("no jumps: held while the pointer is on it, released when it leaves, never a folded box",
          "matches(':hover')" in js and "mouseleave" in js and "du-one" in js and "boxSizing = 'border-box'" in js
          and "minHeight = ''" in js and "addEventListener('resize', free)" in js)
    check("no jumps: no easing on the release (it lagged behind a window resize)", "transition: min-height" not in board._css({}))
    check("no jumps: a fetching part holds its height", ".dc-wait" in js)
    css = board.DUE_CSS
    check("no jumps: the box's rows stay at the top when it's held", "display: grid; gap: 6px; align-content: start;" in css)
    html = board.render({"entries": [], "labels": [], "tomorrow": "", "pending": []}, {"period": "squads"}, 0,
                        squad_view={"state": "loading"})
    check("no jumps: Squads' Fetching is marked as waiting", "dc-wait" in html and "Fetching&hellip;" in html)


def test_one_settings_keys_study_v380():
    """3.8.0: one Settings (the board's, from anywhere), the two keys and
    their switch, and Study today's walk through the day."""
    import due_crew as dc
    from due_crew import due as D, due_flow as F, team_flow as TF, settings_model as SM
    from due_crew.app import _state
    from aqt.deckbrowser import DeckBrowser
    mw = dc.mw
    saved = (dc._board_on_screen, dc._swap, dc._rerender, getattr(mw, "moveToState", None), mw.state, dc.cfg, dc.save_cfg,
             _state.get("settings_tab"), dc._apply_keys, TF.tooltip, F.tooltip)
    calls = []
    conf = {}
    try:
        dc.cfg, dc.save_cfg = (lambda: conf), (lambda c, **k: conf.update(c))
        dc._swap = lambda c, focus=None: calls.append("swap")
        dc._rerender = lambda: calls.append("rerender")
        mw.moveToState = lambda st: calls.append("move:" + st)
        # one Settings: on the board when it's there; else the Decks screen draws it
        dc._board_on_screen = lambda: True
        mw.state = "deckBrowser"
        dc.open_settings("privacy")
        check("one settings: on the board, in place, on the tab asked", _state["settings_tab"] == "privacy" and calls == ["swap"], calls)
        calls.clear()
        mw.state = "review"
        dc.open_settings()
        check("one settings: from another screen, the Decks screen opens on it", calls == ["move:deckBrowser"]
              and _state["settings_tab"] == "you", calls)
        calls.clear()
        mw.state, dc._board_on_screen = "deckBrowser", (lambda: False)
        dc.open_settings("board")
        check("one settings: the board off or signed out, the screen redraws with it", calls == ["rerender"])
        content = types.SimpleNamespace(stats="")
        conf.update(show_leaderboard=False)
        dc._on_render(None, content)
        check("one settings: drawn even with the board off (it's how it comes back)", 'class="st-bar"' in content.stats
              and "Shortcuts" in content.stats)
        dc._toggle_board()
        check("one settings: Tools › Show on the Decks screen turns it back on, Settings closed",
              conf.get("show_leaderboard") is True and _state["settings_tab"] is None)
        init_src = srcs.glue_src()
        check("one settings: no Qt window left", "settings_dialog" not in init_src
              and not os.path.exists(os.path.join(REPO, "due_crew", "ui", "settings_dialog.py")))
        # the keys: listed, one switch, and it applies at once
        st = board.settings_html({"tab": "study", "signed_in": True}, conf)
        keys = ("⌘⇧S", "⌃⇧Q") if sys.platform == "darwin" else ("Ctrl+Shift+S", "Ctrl+Shift+Q")  # 3.9.3: the suite on a Mac too
        check("keys: Settings › Study lists both in this computer's names; 3.9.12 (SC agreed): no switch, the keys are on",
              keys == (board.STUDY_KBD, board.ASK_KBD) and all(k in st for k in keys) and "set:shortcuts" not in st
              and SM.change(["set", "shortcuts", "0"], {}) is None and SM.BOARD_DEFAULTS["shortcuts"] is True, keys)
        said = []
        TF.tooltip = lambda m, **k: said.append(m)
        mw.state = "deckBrowser"
        TF.ask_this_card()
        check("keys: Ctrl+Shift+Q off the review screen says what it's for", said and "reviewing" in said[0], said)
        # Study today: the walk's order
        check("study: the plans' decks first, in plan order", D.study_next([5, 3], {5: 0, 3: 4, 9: 40}) == ("deck", 3))
        check("study: then the deck with the most due", D.study_next([5], {5: 0, 7: 3, 9: 40}) == ("deck", 9))
        check("study: then done; no misses step (3.8.1, Sam: it built a deck nobody asked for)",
              D.study_next([5], {5: 0, 9: 0}) is None and D.study_next([], {}) is None)
        # the walk, through Anki's screens
        sel = []
        F.tooltip = lambda m, **k: said.append(m)
        due = {"n": {3: 4, 9: 0}}
        counts = {"left": (0, 0, 0)}
        mw.col = types.SimpleNamespace(
            decks=types.SimpleNamespace(select=lambda d: sel.append(d), name=lambda d: f"Deck {d}", id_for_name=lambda n: 77),
            sched=types.SimpleNamespace(counts=lambda: counts["left"]))
        sv = (F._plan_decks, F._due_now, F._reviews)
        F._plan_decks = lambda: [3]
        F._due_now = lambda col, dids: dict(due["n"])
        F._reviews = lambda: {"back": 0, "at": ""}
        from due_crew import plan_flow as PF
        built, sv_filtered = [], PF._filtered
        PF._filtered = lambda col, name, cids, order=4, **kw: (built.append(name), True)[1]
        calls.clear()
        try:
            dc._on_js(False, as_board("duecrew:duestudy"), DeckBrowser())
            check("study: the button starts on the plan's deck, in Anki's review", sel == [3] and calls == ["move:review"]
                  and _state.get("study_walk"), (sel, calls))
            due["n"] = {3: 0, 9: 6}
            F.on_state("overview", "review")  # the deck ran out (the timer is a fake: step by hand)
            check("study: a deck that runs out keeps the walk", _state.get("study_walk") is not None)
            F.study_step()
            check("study: on to the next deck, said", sel == [3, 9] and "Next: Deck 9" in said[-1], (sel, said))
            counts["left"] = (2, 0, 5)
            F.on_state("overview", "review")
            check("study: leaving a deck with cards left ends the walk", _state.get("study_walk") is None)
            due["n"] = {3: 0, 9: 0}
            F.study_today()
            check("study: nothing due, it says so and stays put", "Nothing due now." in said[-1] and _state.get("study_walk") is None)
            check("study: the walk never builds a deck, whatever today's misses (a Fifteen starts it)", built == [], built)
        finally:
            F._plan_decks, F._due_now, F._reviews = sv
            PF._filtered = sv_filtered
            mw.col = None
        T0 = "2026-10-03"
        v = D.view(T0, [{"pid": "p", "uid": "u", "plan": "P", "name": "A", "opens": T0, "seen": 2, "total": 5}], [], {},
                   reviews={"due": 10, "done": 0})
        h = board._due_html(v)
        check("study: 3.9.3, Today's head has no Study today (Sam), open or folded",
              "duestudy" not in h and "Study today" not in h and "duestudy" not in board._due_html(dict(v, folded=True)))
        one = D.view(T0, [{"pid": "p", "uid": "u", "plan": "P", "name": "A", "opens": T0, "seen": 2, "total": 5},
                          {"pid": "p", "uid": "o", "plan": "P", "name": "Old", "opens": "2026-09-30", "seen": 0, "total": 4}], [], {},
                     reviews={"due": 10, "done": 0})
        oh = board._due_html(one)
        check("study: no Study in the box (none on a date or on Behind; 3.9.3, Study today gone too)",
              "Study" not in oh and "planstudy:" not in oh and "plancatch:p" in oh, oh[:2500])
    finally:
        (dc._board_on_screen, dc._swap, dc._rerender, ms, mw.state, dc.cfg, dc.save_cfg,
         _state["settings_tab"], dc._apply_keys, TF.tooltip, F.tooltip) = saved
        if ms is None:
            mw.__dict__.pop("moveToState", None)
        else:
            mw.moveToState = ms
        _state["study_walk"] = None


def test_site_audit_v380():
    """3.8.0, the site audit: what was fixed stays fixed. The lone row
    takes no medal on either side (a twin); the rest is the site's CSS."""
    T0 = TODAY.isoformat()
    lone = board.render({"entries": [{"user_id": "me", "name": "Sam", "you": True, "paused": False, "last_updated": "",
                                      "days": {}}], "labels": [T0], "tomorrow": "", "pending": []}, {"period": "week"}, 0)
    check("site audit: alone with nothing yet, no medal (the add-on)", "&#129351;" not in lone and "&mdash;" in lone and '<td class="rk"></td>' in lone)
    js = open(os.path.join(REPO, "site", "public", "app.js"), encoding="utf-8").read()
    css = open(os.path.join(REPO, "site", "public", "app.css"), encoding="utf-8").read()
    check("site audit: alone with nothing yet, no medal (the site, its twin)",
          'tr(r, r.showup ? "✓" : "")' in js and "MEDALS" not in js and "`#${n}`" not in js.split("function table(")[1].split("function ")[0])
    check("site audit: columns hide by name, so a squad's two-column line can't shift them",
          ".brdt .k-time, .brdt .k-retention { display: none; }" in css and "nth-child(4)" not in css
          and 'class: "n k-time"' in js and "k-${k}" in js)
    check("site audit: the rail can't widen the page; a long word wraps",
          "grid-template-columns: minmax(0, 1fr); }  /* a long word" in css and "min-width: 0; overflow-wrap: anywhere; }" in css)
    check("site audit: the cheer popup sits on the page, not in the table's scroll box",
          "document.body.append(pop);" in js and 'position: "fixed"' in js)
    check("site audit: picker underline straight, long squad names cut, text not faint, one tile a tile wide, the footer at the bottom",
          "border-radius: 0; padding-bottom: 3px; max-width: 180px" in css and ".brdt tr.dim td { color: var(--muted); }" in css
          and ".ts:only-child { max-width: 300px; }" in css and "nav .navme summary::after { content: none; }" in css
          and "grid-template-rows: auto 1fr auto; }" in css)
    solo = board.render({"entries": [{"user_id": "me", "name": "Sam", "you": True, "paused": False, "last_updated": "", "days": {}}],
                         "labels": [T0], "tomorrow": "", "pending": [], "my_code": "ABC123"}, {"period": "today"}, 0)
    check("site audit: the empty crew box says what to do when nobody's added yet, the same on both sides",
          "Once you’ve added each other, they’re here." in solo and "Once you’ve added each other, they’re here." in js
          and "They show up here once they add you back." not in js + solo and "codepill\" }, spaced(b.me.code)), \n" not in js)
    idx = open(os.path.join(REPO, "site", "public", "index.html"), encoding="utf-8").read()
    check("site audit: the landing picture has its dark one", 'srcset="/board-dark.png" media="(prefers-color-scheme: dark)"' in idx
          and os.path.exists(os.path.join(REPO, "site", "public", "board-dark.png")))


def test_review_fixes_v380():
    """3.8.0, the night's review: what it found stays fixed. Insights: one
    plan a deck (a second plan's line can't act on the first's cards); a
    tile's cards found whatever its tags' alphabet; the Tags way pickable;
    a pick out of the ways shown falls back to the best; short numbers are
    names, long ones a question bank's ids; tooltips not escaped twice. The
    fake server answers as the Worker does: a date can't be "every", a
    date's own lines are checked like the weekly ones (JavaScript's length
    and trim), new codes have a ceiling, the routes 2.x used say 405."""
    import sqlite3
    from due_crew import team_flow as TF, team as T, plan_flow as PF
    from due_crew.app import _state
    import due_crew as dc
    # two plans on one deck: the deck's Insights are the first plan's
    calls = []
    saved = (PF._state_cfg, PF.followed, PF._deck_ok, TF.cfg, TF._work_out, dc.mw.col, _state.get("insights"))
    try:
        PF._state_cfg = lambda c=None: {"pA": {"deck_id": 10}, "pB": {"deck_id": 10}}
        PF.followed = lambda: [{"id": "pA"}, {"id": "pB"}]
        PF._deck_ok = lambda col, did: True
        TF.cfg = lambda: {}
        heroes = {"pA": [1, 2, 3], "pB": [7, 8]}
        TF._work_out = lambda did, pid=None, exam="": (calls.append(pid) or
                                                       {"hero": heroes[pid], "aim": {"day": "2026-10-15", "name": "Quiz", "scoped": True}})
        dc.mw.col = types.SimpleNamespace()
        _state["insights"] = {}
        for _render in range(3):
            cards = [{"id": "pA"}, {"id": "pB"}]
            TF.plan_lines(cards)
        check("review: two plans on one deck, the first plan's line; worked out once, not every redraw",
              cards[0].get("ins", {}).get("n") == 3 and "ins" not in cards[1] and calls == ["pA"], (cards, calls))
        check("review: its Study acts on its own cards", TF._pick(10, "h")[0] == [1, 2, 3], TF._pick(10, "h"))
    finally:
        PF._state_cfg, PF.followed, PF._deck_ok, TF.cfg, TF._work_out, dc.mw.col, _state["insights"] = saved
    # a tile's cards, whatever the alphabet (SQLite folds ASCII only)
    conn = sqlite3.connect(":memory:")
    fakes.make_collection(conn)
    for cid, tags in ((1, "Анатомия::Сердце"), (2, "Анатомия::Сердце::Клапаны"), (3, "Ökologie"), (4, "ökologie::Wald"),
                      (5, "Анатомия::Мозг"), (6, "Cardio_x"), (7, "Cardio%")):
        fakes.add_card(conn, cid, 10, tags=tags)
    col = fakes.FakeCol(conn, 0)
    col.decks = fakes.FakeDecks({10: "Deck"})
    check("review: a tile's cards found with any alphabet, children too, not a sibling",
          TF._find_cids(col, 10, {"tags": ["Анатомия::Сердце"]}) == [1, 2]
          and TF._find_cids(col, 10, {"tags": ["ökologie"]}) == [3, 4], TF._find_cids(col, 10, {"tags": ["Анатомия::Сердце"]}))
    check("review: _ and % in a tag are just letters", TF._find_cids(col, 10, {"tags": ["Cardio_x"]}) == [6])
    # the Tags way can be picked
    mixed = {c: [f"#R::^Systems::{['Cardio', 'Renal', 'Pulm', 'GI', 'Neuro'][c % 5]}::Part{c % 2}",
                 f"{['Week1', 'Week2', 'Week3', 'Week4', 'Week5', 'Week6'][c % 6]}::Lecture"] for c in range(300)}
    mk = {c: 0.9 for c in range(300)}
    _tiles, ways = T.subjects_by(mixed, mk)
    tags_way = next((w for w in ways if w["name"] == "Tags"), None)
    check("review: the plain tags are a way, with a key a pick keeps", tags_way is not None and tags_way["key"] == T.TAGS_WAY, ways)
    tt, tw = T.subjects_by(mixed, mk, by=T.TAGS_WAY)
    check("review: picked, the map by the plain tags", sorted(t["name"] for t in tt)[:2] == ["Week1", "Week2"]
          and [w["name"] for w in tw if w["on"]] == ["Tags"], (tt, tw))
    # a pick that's dropped out of the ways shown: the best, and one is on
    six = {c: [f"#R::^{f}::{'abcdefgh'[(c + i) % (2 + i)]}" for i, f in enumerate("ABCDEF")] for c in range(240)}
    sk = {c: 0.9 for c in range(240)}
    _t, all_ways = T.subjects_by(six, sk)
    order = [w["key"] for w in all_ways]
    hidden = next(("#r::^" + f.lower() for f in "ABCDEF" if "#r::^" + f.lower() not in order), None)
    if hidden:
        _t2, w2 = T.subjects_by(six, sk, by=hidden)
        check("review: a pick no longer among the ways shown: the best way, on", w2 and w2[0]["on"], w2)
    # numbers: a week or a lecture is a name; a question bank's long id isn't
    lect = T.subjects_by({c: [f"{['01', '02', '03', '04'][c % 4]}"] for c in range(80)}, {c: 0.9 for c in range(80)}, decks=True)[0]
    weeks = T.subjects({c: [f"Pharm::Week::{c % 4 + 1}"] for c in range(80)}, {c: 0.9 for c in range(80)})
    bank = T.subjects({c: [f"Bank::Step::{104520 + c % 4}"] for c in range(80)}, {c: 0.9 for c in range(80)})
    check("review: subdecks named 01 to 04 and tags Week::1 to 4 make a map; a bank's ids don't",
          sorted(t["name"] for t in lect) == ["01", "02", "03", "04"] and len(weeks) >= 1 and bank == [], (lect, weeks, bank))
    # a tile's tooltip: its apostrophe once
    tip = board._ins_map(10, [{"key": "a", "name": "Cardio", "n": 40, "started": 40, "know": 80},
                              {"key": "b", "name": "Renal", "n": 30, "started": 30, "know": 70}], "fsrs")
    check("review: a tile's tooltip isn't escaped twice", "you’d remember now" in tip and "&amp;rsquo;" not in tip, tip[:300])
    # the fake server, as the Worker
    w = fakes.FakeWorker()
    w.add_user("dre", "Dre")
    unit = lambda **k: dict({"id": "u1", "name": "Heart", "opens": "2026-10-12"}, **k)  # noqa: E731
    for bad, why in (([unit(id="every")], "a date called every"),
                     ([unit(todo=[{"k": "do", "t": "😀" * 71}])], "a line over 140 in JavaScript's count"),
                     ([unit(todo=[{"k": "do", "t": "x", "r": "1"}])], "a date's line with weekdays"),
                     ([unit(todo=[{"k": "do", "t": "﻿ "}])], "a line that's only a byte-order mark")):
        try:
            w.add_plan("dre", "P", "Step 1", bad)
            ok = False
        except fakes.Bad as e:
            ok = e.status == 400
        check(f"review: the fake refuses {why}, as plans.ts does", ok)
    pid, _code = w.add_plan("dre", "P", "Step 1", [unit(todo=[{"k": "read", "t": " Ch. 6\u0085"}, {"k": "do", "t": "😀" * 70}])])
    todo = w.plans[pid]["doc"]["units"][0]["todo"]
    check("review: a date's lines kept, trimmed as JavaScript trims", todo[0]["t"] == "Ch. 6\u0085" and len(todo) == 2, todo)
    tok = w.session_for("dre")
    hdr = {"Authorization": f"Bearer {tok}"}
    got = [w.handle("POST", "https://x/codes", hdr, {}).status_code for _ in range(21)]
    check("review: twenty new codes a day, then slow down", got[:20] == [200] * 20 and got[20] == 429, got[-3:])
    check("review: the 2.x restore routes say 405, as the Worker's router",
          w.handle("PUT", "https://x/friends", hdr, {"ids": []}).status_code == 405
          and w.handle("POST", "https://x/squads/restore", hdr, {}).status_code == 405)


def test_review_fixes_board_due_v380():
    """3.8.0, the night's review, the board and Due: a squad's long name is
    cut in the corner with the whole name on hover; a squad with no table
    starts where the corner does; no deck of mine shared says so; show-up
    mode keeps the invite; tooltips' dots once; tab lists have tabs. Due: a
    second identical line can be ticked (a dot rides in commands); Escape
    stops Study today; the tidy leaves a "Due Crew" deck the person made;
    leeches are recovered on the Decks screen only; a half-typed to-do
    survives a redraw; a line's words reach both sides the same (tick keys
    match the site's)."""
    import shutil
    import subprocess
    from due_crew import due as D, due_flow as F, plan_flow as PF
    from due_crew.backend import shapes
    from due_crew.app import _state
    T0 = TODAY.isoformat()
    css = board._css({})
    check("review: a long squad name is cut short in the corner",
          "#due-crew th.dc-corner .dc-sw a {" in css and "max-width: 8em; overflow: hidden; text-overflow: ellipsis;" in css)
    sw = board._switcher({"squads": [{"id": "x", "name": "Saturday <night> study crew"}], "current": "x"})
    check("review: its whole name on hover, escaped", 'title="Saturday &lt;night&gt; study crew"' in sw, sw)
    check("review: a squad with no table, and Decks' line, start where the corner's words do",
          "#due-crew .dc-sheet > .dc-sw { text-align: left; padding-left: 8px; }" in css
          and "text-align: left; padding: 0 8px; }" in css, css[css.find(".dc-pline"):css.find(".dc-pline") + 200])
    labels = [(TODAY - datetime.timedelta(days=i)).isoformat() for i in range(7)]
    me = {"user_id": "me", "name": "Sam", "you": True, "paused": False, "last_updated": "", "days": {T0: {"reviews": 5, "studied": True}}}
    dre = {"user_id": "dre", "name": "Dre", "you": False, "paused": False, "last_updated": "", "days": {},
           "decks": [{"name": "Step 1", "sig": ["a"], "total": 10, "seen": 5, "mature": 2}]}
    dk = board.render({"entries": [me, dre], "labels": labels, "tomorrow": ""}, {"period": "decks"}, 0)
    check("review: a friend shares a deck and I share none: the way in, not nothing", "No shared decks yet" in dk)
    solo = board.render({"entries": [me], "labels": labels, "tomorrow": "", "my_code": "ABC123"}, {"period": "today", "show_up": True}, 0)
    check("review: show-up mode on my own keeps the invite (as the site)", "Bring your crew" in solo and "showed up today" in solo)
    ins = board._insights_html(10, {"rows": [{"name": "Cardio", "src": "", "of": 40, "stuck": 5, "forgot": 2, "cids": [1]}]})
    check("review: Not sticking's tooltip isn't escaped twice", "Cardio · 40 cards reviewed" in ins and "&amp;middot;" not in ins, ins[:500])
    you = board.you_html({"show_up": False}, None, {"tab": "plans", "plans": {"cards": [], "offers": []}})
    check("review: a tab list's links are tabs, the open one selected", 'role="tab" aria-selected="true"' in you
          and 'role="tab" aria-selected="false"' in you, you[:400])
    # a dot rides in a command: a second identical line's key
    keys = D.line_keys("p1", "u1", [{"k": "do", "t": "Practice"}, {"k": "do", "t": "Practice"}])
    check("review: a second identical line's key reaches its handler whole", keys[1].endswith(".2")
          and f"duecrew:duetodo:{keys[1]}|{KK}'" in board._pycmd("duetodo:" + keys[1]), (keys, board._pycmd("duetodo:" + keys[1])))
    check("review: nothing that closes a quote rides", board._pycmd("x'y\"z<>;.") == ("pycmd('duecrew:xyz.|" + KK + "'); return false;"))
    # Escape stops the walk
    saved_walk = _state.get("study_walk")
    try:
        _state["study_walk"] = {"misses": False, "steps": 1}
        keys_on = []
        F.walk_keys("review", keys_on)
        none = []
        F.walk_keys("overview", none)
        check("review: Escape is a key while Study today walks the review, only then", [k for k, _f in keys_on] == ["Esc"] and none == [])
        keys_on[0][1]()
        check("review: Escape stops the walk", _state.get("study_walk") is None)
        idle = []
        F.walk_keys("review", idle)
        check("review: no walk, no Escape of ours", idle == [])
    finally:
        _state["study_walk"] = saved_walk
    # the tidy leaves a "Due Crew" deck of the person's own
    ids = {"Due Crew": 900}
    pc = {}

    class Deck:
        def __init__(self):
            self.name = ""
            self.config = types.SimpleNamespace(search_terms=[types.SimpleNamespace(search="", limit=0, order=0)], reschedule=False)

    def add(deck):
        ids.setdefault(deck.name, 1000 + len(ids))
        ids.setdefault(deck.name.split("::")[0], 1000 + len(ids))
    col = types.SimpleNamespace(decks=types.SimpleNamespace(id_for_name=lambda n: ids.get(n)),
                                sched=types.SimpleNamespace(get_or_create_filtered_deck=lambda deck_id=0: Deck(),
                                                            add_or_update_filtered_deck=add))
    saved = (PF._pcfg, PF._psave)
    try:
        PF._pcfg = lambda: pc
        PF._psave = lambda c: pc.update(c)
        PF._filtered(col, "Due Crew::Renal", [1, 2])
        check("review: a Due Crew deck I made myself isn't noted to tidy; the filtered one is",
              900 not in pc.get("built", []) and ids["Due Crew::Renal"] in pc.get("built", []), pc)
        ids.pop("Due Crew")
        pc.clear()
        PF._filtered(col, "Due Crew::Pharm", [3])
        check("review: a parent Due Crew made is noted", ids["Due Crew"] in pc.get("built", []), (ids, pc))
    finally:
        PF._pcfg, PF._psave = saved
    # leeches: on the Decks screen only
    got = []
    saved = (F._day_state, F.recover_leeches, F._put_day, F._today, getattr(dc_mw(), "state", None), dc_mw().col,
             F.leech_plan)
    try:
        st = {}
        F._day_state = lambda: ({}, st)
        F._put_day = lambda pc, s: None
        F.recover_leeches = lambda col, **k: got.append("ran") or []
        F.leech_plan = lambda col, out=(): ([1], [1], [], [])
        F._today = lambda: T0
        dc_mw().col = object()
        dc_mw().state = "review"
        F.morning({"due_leeches": True})
        check("review: mid-review, the leeches wait (their undo step would sit on my answer)", got == [] and not st.get("leeches_done"))
        dc_mw().state = "deckBrowser"
        F.morning({"due_leeches": True})
        check("review: on the Decks screen, they're recovered", got == ["ran"] and st.get("leeches_done"))
    finally:
        F._day_state, F.recover_leeches, F._put_day, F._today, dc_mw().state, dc_mw().col, F.leech_plan = saved
    js = board.swap_js("<div id='due-crew'></div>")
    check("review: a half-typed to-do survives a redraw while it has focus; a sent one is cleared",
          "document.activeElement === din && din.value" in js and "n1.value = keep.v" in js
          and "inp.value = '';  // sent" in fakes.board_source())
    # a line's words as served: the same tick keys on both sides
    raw = [{"k": "do", "t": "Practice  questions", "r": "4"}, {"k": "do", "t": "👩‍⚕️ rounds", "r": "1"},
           {"k": "read", "t": "Read ch. 6­", "r": "2"}]
    served = shapes.clean_plan_doc({"deck": "D", "units": [], "every": raw})["every"]
    check("review: a line's words reach Due as the server keeps them", [x["t"] for x in served] == [x["t"] for x in raw], served)
    node = shutil.which("node")
    if not node:
        print("SKIP line keys twin: no node")
        return
    appjs = open(os.path.join(REPO, "site", "public", "app.js"), encoding="utf-8").read()
    src = appjs[appjs.index("function dueLineHash"):appjs.index("/** 3.8.0: a repeating to-do's weekdays")]
    out = subprocess.run([node, "-e", src + f"\nconsole.log(JSON.stringify(dueLineKeys('p1', 'every', {json.dumps(raw)})))"],
                         capture_output=True, text=True, timeout=20)
    check("review: the same tick keys on the site (dueLineKeys) as in Anki, odd spaces and joined emoji too",
          json.loads(out.stdout or "null") == D.every_keys("p1", served), (out.stdout, out.stderr, D.every_keys("p1", served)))


def dc_mw():
    from aqt import mw
    return mw


def test_head_row_b_v380():
    """3.8.0, head row B (Sam's pick, from the spec's four): Crew's views sit
    in the table's top-left corner, where the header was empty, and a
    squad's names in its table's; what was in that corner (show-up mode's
    "N showed up today", a squad's headline) goes under the table, and the
    bingo card under that. Decks has no table: its picker has a line of its
    own with the key at the right. The site draws the same (the twin).
    Crew and Share in the footer lose their carets (Sam)."""
    import re as _re
    T0 = TODAY.isoformat()
    labels = [(TODAY - datetime.timedelta(days=i)).isoformat() for i in range(7)]
    me = {"user_id": "me", "name": "Sam", "you": True, "paused": False, "last_updated": "",
          "days": {T0: {"reviews": 5, "studied": True}},
          "decks": [{"name": "Step <1>", "sig": ["a", "b"], "total": 100, "seen": 40, "mature": 20}]}
    dre = {"user_id": "dre", "name": "Dre", "you": False, "paused": False, "last_updated": "",
           "days": {T0: {"reviews": 9, "studied": True}},
           "decks": [{"name": "Step 1", "sig": ["a"], "total": 100, "seen": 60, "mature": 30}]}
    data = {"entries": [me, dre], "labels": labels, "tomorrow": ""}
    corner = '<th class="lt dc-corner" colspan="2"><div class="dc-sw">'
    today = board.render(data, {"period": "today"}, 0)
    check("head row B: Crew's views in the header's corner, not a line above the table",
          corner + ('<a class="on" data-t="Today" href="#" onclick="pycmd(\'duecrew:period:today|' + KK + '\'); return false;">Today</a>') in today
          and today.index(corner) > today.index("<table class=\"dc-s-") and "<th></th><th></th>" not in today
          and today.count('<div class="dc-sw">') == 1)
    week = board.render(data, {"period": "week"}, 0)
    check("head row B: Week too, Week picked", corner in week
          and ('<a class="on" data-t="Week" href="#" onclick="pycmd(\'duecrew:period:week|' + KK + '\'); return false;">Week</a>') in week)
    mode = board.render(data, {"period": "today", "show_up": True}, 0)
    check("head row B: show-up mode's corner is the picker; who showed up today goes under the table",
          corner in mode and '<div class="dc-line dc-sum">2 showed up today</div>' in mode
          and mode.index("showed up today") > mode.index("</table>"), mode[-900:])
    alone = board._presence_html([], [], labels, [])
    check("head row B: with no picker the count keeps the corner",
          '<th class="lt" colspan="2">0 showed up today</th>' in alone and "dc-sum" not in alone)
    decks = board.render(data, {"period": "decks"}, 0)
    line = _re.search(r'<div class="dc-pline">(.*?)</span></div>', decks)
    check("head row B: Decks, the picker on a line of its own with the key at its right, the key once",
          line is not None and "period:decks|" + KK + "'); return false;\">Decks</a>" in line.group(1)
          and '<span class="dkey">' in line.group(1) and decks.count('class="dkey"') == 1
          and decks.index("dc-pline") < decks.index('class="dg"'))
    pick = board._crew_picker("decks")
    asks = board._decks_body(data, None, None, pick, '<div class="dc-flag">an ask</div>')
    check("head row B: with asks between, the key stays under the bars",
          '<div class="dc-pline">' + pick + "</div>" in asks and asks.count('class="dkey"') == 1
          and asks.index("dkey") > asks.index('class="dg"') > asks.index("an ask"))
    none = board._decks_body(dict(data, entries=[dict(me, decks=[])]), None, None, pick)
    check("head row B: no shared decks, the picker and the way in, no key",
          none.startswith('<div class="dc-pline">' + pick + "</div>") and "No shared decks yet" in none
          and "dkey" not in none)
    check("head row B: the old ways still draw (no picker)",
          "dc-pline" not in board._decks_body(data) and 'class="dkey"' in board._decks_body(data)
          and "<th></th><th></th>" in board._table_html(data, {}, "today"))
    sq = {"state": "ok", "name": "<b>ORCA", "squads": [{"id": "x", "name": "<i>orca"}, {"id": "y", "name": "MS2"}],
          "current": "x", "day": T0, "yesterday": "", "people": 2, "reviews": 40, "bingo": {"x": 1},
          "rows": [{"user_id": "a", "name": "A", "day": T0, "reviews": 30, "week": 5, "you": True},
                   {"user_id": "b", "name": "B", "day": T0, "reviews": 10, "week": 3}]}
    saved = board.bingo_card_html
    board.bingo_card_html = lambda v: '<div class="bg-card">BINGO</div>'
    try:
        html = board._squads_html(sq, {})
        up = board._squads_html(sq, {"show_up": True})
        empty = board._squads_html(dict(sq, rows=[]), {})
    finally:
        board.bingo_card_html = saved
    check("head row B: a squad's names in its table's corner, escaped",
          '<th class="lt dc-corner" colspan="2">' + board._switcher(sq) + "</th>" in html
          and "&lt;i&gt;orca" in html and "<i>orca" not in html and not html.startswith('<div class="dc-sw">'))
    check("head row B: the squad's headline, its week and its bingo card under the table, in that order",
          html.index("</table>") < html.index("2 in &lt;b&gt;ORCA &middot; 2 studying today &middot; 40 reviews together")
          < html.index("Last 7 days") < html.index("BINGO") < html.index("squadinvite"), html[-700:])
    check("head row B: show-up mode the same, its own headline", "dc-corner" in up
          and up.index("</table>") < up.index("2 in &lt;b&gt;ORCA &middot; 2 showed up today") and "&#128197; 7 days" in up)
    check("head row B: no table (nobody synced), the names stay on top",
          empty.startswith('<div class="dc-sw">') and "dc-corner" not in empty)
    for st in ("none", "loading", "error"):
        check(f"head row B: {st}, the names on top",
              board._squads_html({"state": st, "squads": [{"id": "x", "name": "x"}]}, {}).startswith('<div class="dc-sw">'))
    site_js = open(os.path.join(REPO, "site", "public", "app.js"), encoding="utf-8").read()
    rw = open(os.path.join(REPO, "due_crew", "room_widget.js"), encoding="utf-8").read()
    from due_crew import rooms as _rooms
    check("the site's foot says the same two words (the scrapbook is Anki's alone); sharing a deck points at Crew › Decks",
          'menu("Friends", crewItems), menu("Share my stats", shareItems)' in site_js and 'menu("Crew"' not in site_js
          and "Settings › Shared decks" not in site_js and "Crew › Decks › Share a deck" in site_js)
    check("Open a room is the top bar's: ▶ Fifteen?'s arrow sends its own keyed command, which offers the two ways",
          "send('room15menu')" in rw and "e.stopPropagation()" in rw
          and [k for _l, k in _rooms.START_WAYS] == ["fifteen", "room"] and 'cmd == "room15menu"' in open(_rooms.__file__, encoding="utf-8").read())
    check("footer: Friends and Share my stats, without carets (Sam)",
          ("duecrew:friends|" + KK + "'); return false;\">Friends</a>") in today
          and ("duecrew:sharemenu|" + KK + "'); return false;\">Share my stats</a>") in today
          and "&#9662;" not in today.split('class="dc-foot"')[1])
    js = open(os.path.join(REPO, "site", "public", "app.js"), encoding="utf-8").read()
    css = open(os.path.join(REPO, "site", "public", "app.css"), encoding="utf-8").read()
    check("head row B, the site's twin: the corner, the line under, Decks' line, the squads' corner, no carets",
          'const corner = (picker) => h("th", { class: "lt corner", colspan: 2 }, picker);' in js
          and 'picker ? corner(picker) : [h("th"), h("th")]' in js
          and 'picker ? h("p", { class: "muted small sum" }, said) : null' in js
          and 'h("div", { class: "pline" }, picker, mine.length ? key() : null)' in js
          and ('h("thead", {}, h("tr", {}, corner(sw), heads)), h("tbody", {}, body))), '
               'h("p", { class: "muted small sum" }, line), wkLine, bingo, foot)') in js
          and "Board.decks(b.me, crew, b.decks || {}, t, picker)" in js and "Board.table(people, view, t, draw, picker)" in js
          and "Board.presence(people, t, picker)" in js and "${label} ▾" not in js and '"Crew ▾"' not in js
          and ".brdt th.corner {" in css and ".pline {" in css and "p.sum {" in css and "th.sqt" not in css)


def test_squad_week_v380():
    """3.8.0: a squad's last 7 days together, totals only, under its table,
    on both sides (squadWeek in app.js is the twin). No line for one. A
    row's week is its 7 days to its own last sync: a sync 2 days ago counts
    at most 5 of them, one a week old or more none (the review: a member
    gone since March kept adding their 7)."""
    import shutil
    import subprocess
    D = "2026-10-12"
    ago = lambda n: (datetime.date(2026, 10, 12) - datetime.timedelta(days=n)).isoformat()  # noqa: E731
    rows = [{"week": 5, "day": D}, {"week": 7, "day": D}, {"week": 0, "day": D}, {"week": None, "day": D},
            {"week": 9, "day": D}, {"week": 2.6, "day": D}, {"week": True, "day": D}, {"week": "4", "day": D}, {},
            {"week": -3, "day": D}, {"week": float("nan"), "day": D}, {"week": 7, "day": ago(2)}, {"week": 3, "day": ago(2)},
            {"week": 7, "day": ago(7)}, {"week": 7, "day": "2026-03-01"}, {"week": 4, "day": ago(-1)}, {"week": 6}]
    check("squad week: the days added up (7 at most each, fewer for an older sync), and how many studied",
          board.squad_week(rows, D) == (5 + 7 + 0 + 7 + 2 + 0 + 5 + 3 + 4, 7), board.squad_week(rows, D))
    check("squad week: nothing to add", board.squad_week([], D) == (0, 0) and board.squad_week(None, D) == (0, 0)
          and board.squad_week(rows, "") == (0, 0))
    T0 = TODAY.isoformat()
    sq = {"state": "ok", "name": "<b>ORCA", "day": T0, "yesterday": "", "people": 3,
          "rows": [{"user_id": "a", "name": "A", "day": T0, "reviews": 30, "week": 5, "you": True},
                   {"user_id": "b", "name": "B", "day": T0, "reviews": 10, "week": 3},
                   {"user_id": "c", "name": "C", "day": "", "week": 0}]}
    html = board._squads_html(sq, {})
    check("squad week: under the table, terse, no one ahead", "Last 7 days: <b>8</b> study days between 2 of you" in html
          and html.index("Last 7 days") > html.index("</table>"), html[-600:])
    one = dict(sq, rows=sq["rows"][:1] + [dict(sq["rows"][1], week=0)])
    check("squad week: one of you studied, no line", "Last 7 days" not in board._squads_html(one, {}))
    check("squad week: show-up view too", "between 2 of you" in board._squads_html(sq, {"show_up": True}))
    js = open(os.path.join(REPO, "site", "public", "app.js"), encoding="utf-8").read()
    check("squad week: the site draws the same line", "Last 7 days: " in js and "study days between ${wkPeople" in js
          and "wkPeople >= 2" in js and "squadWeek(rows, day)" in js)
    node = shutil.which("node")
    if not node:
        print("SKIP squad week twin: no node")
        return
    src = js[js.index("function squadWeek"):js.index("// ---- 3.3: the board")]
    jsrows = [r for r in rows if not (isinstance(r.get("week"), float) and r["week"] != r["week"])]
    out = subprocess.run([node, "-e", src + f"\nconsole.log(JSON.stringify(squadWeek({json.dumps(jsrows)}, {json.dumps(D)})))"],
                         capture_output=True, text=True, timeout=20)
    check("squad week: the site adds up as the add-on does (the twin)",
          json.loads(out.stdout or "null") == list(board.squad_week(jsrows, D)), (out.stdout, out.stderr))


def test_every_lines_v380():
    """3.8.0: a plan's lines every week ("every Fri: practice questions"):
    on their weekdays from the plan's first date to its last, ticked by hand
    for the day, never behind; kept as they arrive; drawn escaped; a tick
    and a link through the board's own handler."""
    from due_crew import due as D, due_flow as F, app as appmod
    from due_crew.backend import shapes
    import due_crew as dc
    from aqt.deckbrowser import DeckBrowser
    T = "2026-10-03"  # a Saturday ("5")
    lines = [{"k": "do", "t": "Practice <q>", "r": "5"}, {"k": "watch", "t": "Review", "r": "1", "url": "https://x.example/v"}]
    every = [{"pid": "p1", "plan": "Step <b>", "first": "2026-09-28", "last": "2026-10-31", "lines": lines}]
    keys = D.every_keys("p1", lines)
    check("every: keyed by what each says, a tick key Due keeps", keys[0].startswith("p1:every:")
          and D.clean_ticks({keys[0]: T}) == {keys[0]: T})
    v = D.view(T, [], [], {}, every=every)
    today = [r for r in v["rows"] if r["kind"] == "every"]
    check("every: today's on its weekday, with the plan and the days said",
          [(r["text"], r["plan"], r["tag"], r["done"]) for r in today] == [("Practice <q>", "Step <b>", "every Sat", False)], today)
    days = {dd["day"]: [r["text"] for r in dd["rows"] if r["kind"] == "every"] for dd in v["days"] if "day" in dd}
    check("every: Upcoming, each once, on its next day", days.get(T) == ["Practice <q>"] and days.get("2026-10-06") == ["Review"]
          and "Practice <q>" not in days.get("2026-10-10", []), days)
    vt = D.view(T, [], [], {keys[0]: T}, every=every)
    dt = {dd["day"]: [r["text"] for r in dd["rows"] if r["kind"] == "every"] for dd in vt["days"] if "day" in dd}
    check("every: ticked, done for today; Upcoming shows its next one too",
          [r["done"] for r in vt["rows"] if r["kind"] == "every"] == [True] and dt.get("2026-10-10") == ["Practice <q>"], dt)
    check("every: yesterday's tick isn't today's", [r["done"] for r in D.view(T, [], [], {keys[0]: "2026-09-26"}, every=every)["rows"]
                                                    if r["kind"] == "every"] == [False])
    gone = D.view(T, [], [], {}, every=[dict(every[0], last="2026-10-02")])
    check("every: after the plan's last day, none", not [r for r in gone["rows"] if r["kind"] == "every"]
          and not any(r["kind"] == "every" for dd in gone["days"] for r in dd.get("rows", [])))
    check("every: before its first day, none", not [r for r in D.view(T, [], [], {}, every=[dict(every[0], first="2026-10-04")])["rows"]
                                                    if r["kind"] == "every"])
    check("every: never behind", D.view("2026-10-05", [], [], {}, every=every)["behind_n"] == 0)
    doc = shapes.clean_plan_doc({"deck": "D", "units": [], "every": [{"k": "do", "t": "Practice  questions", "r": "414"},
                                                                     {"k": "do", "t": "No days"}, {"k": "do", "t": "x", "r": "9"},
                                                                     {"k": "read", "t": "y", "r": "0", "url": "javascript:alert(1)"}]
                                  + [{"k": "do", "t": str(i), "r": "0"} for i in range(9)]})
    check("every: arrives clean: weekdays sorted, none without them, https only, 6 at most",
          doc["every"][0] == {"k": "do", "t": "Practice  questions", "r": "14"} and doc["every"][1] == {"k": "read", "t": "y", "r": "0"}
          and len(doc["every"]) == 6, doc.get("every"))
    # drawn
    h = board._due_html(v)
    up = board._due_html(dict(v, tab="upcoming"))
    check("every: on Today, escaped, ticked by hand", "Practice &lt;q&gt;" in h and "Step &lt;b&gt;" in h and "<q>" not in h
          and f"duecrew:duetodo:{keys[0]}" in h and "every Sat" in h, h[:2000])
    check("every: in Upcoming, a day ahead's box ticks on that day; its link opens through Anki",
          f"duecrew:duelink:{keys[1]}" in up and up.count(f"duecrew:duetodo:{keys[1]}") == 0 and ">Review</a>" in up)
    # clicks, through the add-on's own handler
    conf = {"due_items": [], "due_tab": "today"}
    opened = []
    saved = (F.cfg, F.save_cfg, appmod.swap, F._today, F.plan_every, F.plan_dates)
    import aqt.utils as AU
    saved_open = getattr(AU, "openLink", None)
    F.cfg = lambda: conf
    F.save_cfg = lambda c, **k: conf.update(c)
    appmod.swap = lambda c, focus=None: None
    F._today = lambda: T
    F.plan_every = lambda today: every
    F.plan_dates = lambda today: ([], [], [])
    AU.openLink = opened.append
    try:
        send = lambda m: dc._on_js(False, as_board("duecrew:" + m), DeckBrowser())
        send("duetodo:" + keys[0])
        check("every tick: for today", F._ticks(conf).get(keys[0]) == T, conf.get("due_ticks"))
        send("duetodo:" + keys[0])
        check("every untick", keys[0] not in F._ticks(conf))
        send("duetodo:" + keys[1])
        check("every tick: not on a day it isn't", keys[1] not in F._ticks(conf))
        send("duetodo:p1:every:00000000")
        check("every tick: a key no line has does nothing", "p1:every:00000000" not in F._ticks(conf))
        send("duelink:" + keys[1])
        send("duelink:" + keys[0])
        check("every link: only a line's https one", opened == ["https://x.example/v"], opened)
    finally:
        F.cfg, F.save_cfg, appmod.swap, F._today, F.plan_every, F.plan_dates = saved
        if saved_open is not None:
            AU.openLink = saved_open
    # the glue: from the plans I follow, as I run them
    PF = F._pf()
    saved2 = (PF.followed, PF._state_cfg, PF._deck_ok, F.mw.col)
    units = [{"id": "a", "name": "A", "opens": "2026-10-01"}, {"id": "b", "name": "B", "opens": "2026-10-20"}]
    PF.followed = lambda: [{"id": "p1", "name": "Step", "doc": {"deck": "D", "units": units, "every": lines,
                                                                "events": [{"id": "e", "day": "2026-11-02", "name": "Exam"}]}},
                           {"id": "p2", "name": "Paused", "paused": True, "doc": {"deck": "D", "units": units, "every": lines}},
                           {"id": "p3", "name": "None", "doc": {"deck": "D", "units": units}},
                           {"id": "p4", "name": "Gone", "doc": {"deck": "D", "units": units, "every": lines}}]
    PF._state_cfg = lambda c=None: {"p1": {"deck_id": 10}, "p2": {"deck_id": 10}, "p3": {"deck_id": 10}}
    PF._deck_ok = lambda col, did: True
    F.mw.col = object()
    try:
        got = F.plan_every(T)
        check("every glue: the plans I run here with lines, paused ones not, from my first date to the last event",
              [(x["pid"], x["first"], x["last"], x["lines"]) for x in got] == [("p1", "2026-10-01", "2026-11-02", lines)], got)
    finally:
        PF.followed, PF._state_cfg, PF._deck_ok, F.mw.col = saved2


def test_every_site_twin_v380():
    """3.8.0: the site's Due panel reads a plan's weekly lines as due.py
    does: the same days (dueEveryOn ↔ every_on), keys (dueLineKeys with
    "every" ↔ every_keys) and words (dueRepeatLabel ↔ repeat_label). Needs node."""
    import shutil
    import subprocess
    from due_crew import due as D
    js = open(os.path.join(REPO, "site", "public", "app.js"), encoding="utf-8").read()
    check("every site: the panel draws them, ticked for the day", "dueEveryOn(span, ln, t)" in js
          and "ticks[keys[i]] === t" in js and 'dueLineKeys(p.id, "every", every)' in js)
    node = shutil.which("node")
    if not node:
        print("SKIP every site twin: no node")
        return
    src = js[js.index("const parseIso"):js.index("\n", js.index("const parseIso"))] + "\n" + \
        js[js.index("function dueLineHash"):js.index("/** Due, as the site can show it")]
    span = {"first": "2026-10-02", "last": "2026-10-20"}
    lines = [{"k": "do", "t": "Practice questions", "r": "4"}, {"k": "watch", "t": "Review ✓", "r": "0123456"},
             {"k": "read", "t": "Practice questions", "r": "4"}, {"k": "do", "t": "Practice questions", "r": "4"},
             {"k": "do", "t": "x", "r": "01234"}, {"k": "do", "t": "y", "r": "9"}, {"k": "do", "t": "z"}]
    days = ["2026-10-01", "2026-10-02", "2026-10-09", "2026-10-12", "2026-10-20", "2026-10-21"]
    want = {"on": [[D.every_on(span, ln, d) for d in days] for ln in lines], "keys": D.every_keys("p1", lines),
            "labels": [D.repeat_label(r) for r in ("0123456", "01234", "4", "036")]}
    prog = (src + f"\nconst span = {json.dumps(span)}, lines = {json.dumps(lines)}, days = {json.dumps(days)};"
            "\nconsole.log(JSON.stringify({on: lines.map((ln) => days.map((d) => dueEveryOn(span, ln, d))),"
            " keys: dueLineKeys('p1', 'every', lines), labels: ['0123456', '01234', '4', '036'].map(dueRepeatLabel)}));")
    out = subprocess.run([node, "-e", prog], capture_output=True, text=True, timeout=20)
    check("every site: the same days, keys and words as the add-on (the twin)", json.loads(out.stdout or "null") == want,
          (out.stdout, out.stderr, want))


def test_find_a_setting_v380():
    """3.8.0, pick 28: a box atop Settings finds a setting on any tab by a
    word (its label, its section, a few plain synonyms); the index is read
    from the tabs as drawn, holds none of the person's own names, and a
    pick on another tab asks for that tab (an existing command)."""
    import html as H
    view = {"signed_in": True, "name": "Sammy Q", "emoji": "🦊", "status": "secret plans", "crew": 3,
            "squads": ["orca <b>"], "decks": ["Private Deck"], "sync": "now", "tab": "board"}
    ix = board.settings_index(view, {})
    by = {x["l"]: x for x in ix}
    check("find: rows from all four tabs, each with where it lives",
          by["Accent"]["t"] == "board" and by["Accent"]["w"] == "Board \u203a Look"
          and by["\u2708\ufe0f Away"]["t"] == "you" and by["\u2708\ufe0f Away"]["w"] == "You \u203a Your dates"
          and by["Two buttons"]["t"] == "study" and by["Two buttons"]["w"] == "Study \u203a Reviewing"
          and by["Heatmap"]["t"] == "privacy" and by["Sign out"]["t"] == "you" and len(ix) >= 30, sorted(by))
    words = lambda q: [x["l"] for x in ix if all((" " + x["k"]).find(" " + w) >= 0 for w in q.split())]  # noqa: E731
    check("find: by label, by a word it doesn't say (colour, holiday, test, log out), by its section",
          words("accent") == ["Accent"] and words("colour") == ["Accent"] and words("holiday") == ["\u2708\ufe0f Away"]
          and "\U0001f4d6 Exam" in words("test") and words("log out") == ["Sign out"] and "Study time" in words("study time"),
          (words("colour"), words("holiday"), words("test")))
    check("find: a switch is found whichever way it's set (its command without the state)",
          by["Study time"]["f"] == "set:share_time:" and by["Calm board"]["f"] == "set:calm:")
    text = repr(ix)
    check("find: the person's name, status, squads and decks stay out of it",
          not any(x in text for x in ("Sammy", "secret", "orca", "Private Deck")), text[:300])
    page = board.settings_html(view, {})
    got = re.search(r'<input type="search" class="st-in" placeholder="Find a setting"[^>]*data-ix="([^"]*)"', page)
    check("find: the box sits in Settings' bar with its index, which reads back the same",
          got and json.loads(H.unescape(got.group(1))) == ix and 'oninput="dcFind.type(this)"' in page)
    js = board.FIND_JS
    check("find: what's found is written as text, never markup; another tab is asked for by a command the add-on has",
          "innerHTML" not in js and "textContent = h.l" in js and "pycmd('duecrew:settab:' + h.t + '|' + window.dcBK)" in js
          and js in board.keep_me_in_view_js()
          and 'cmd == "settab"' in srcs.glue_src())


def test_site_plan_page_is_the_addons():
    """Your plans on duecrew.com is the add-on's plan page (Sam's call): one
    look, one set of page scripts. site/public/planpage/ holds
    due_crew/planner/page/*.js and *.css byte for byte (tools/gen_plan_page.py
    writes them; running it again changes nothing); the site's face
    (planface.js) draws its view on builder.js's plan. tests/planface_test.js
    drives the face in node: every command the page can send has its handler,
    a save goes out as the builder's, changes wait while anyone follows."""
    import importlib.util
    import json
    import shutil
    import subprocess
    page = os.path.join(REPO, "due_crew", "planner", "page")
    site = os.path.join(REPO, "site", "public")
    names = sorted(n for n in os.listdir(page) if n.endswith((".js", ".css")))
    same = [n for n in names if os.path.exists(os.path.join(site, "planpage", n))
            and open(os.path.join(page, n), "rb").read() == open(os.path.join(site, "planpage", n), "rb").read()]
    check("the site's plan page: each of the add-on's page files, byte for byte (tools/gen_plan_page.py)",
          names and same == names and sorted(os.listdir(os.path.join(site, "planpage"))) == names, sorted(set(names) - set(same)))
    spec = importlib.util.spec_from_file_location("gen_plan_page", os.path.join(REPO, "tools", "gen_plan_page.py"))
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    check("the site's plan page: running tools/gen_plan_page.py again changes nothing", gen.stale() == [], gen.stale())
    html = open(os.path.join(site, "app.html"), encoding="utf-8").read()
    want = ['<link rel="stylesheet" href="/planpage/plan.css">', '<link rel="stylesheet" href="/planface.css">',
            '<script src="/builder.js" defer></script>\n<script src="/planpage/plan.js" defer></script>\n<script src="/planpage/tabs.js" defer></script>\n'
            '<script src="/planpage/new.js" defer></script>\n<script src="/planface.js" defer></script>']
    check("the site's plan page: the app page loads the page's files, then the face, after builder.js", all(x in html for x in want))
    face = open(os.path.join(site, "planface.js"), encoding="utf-8").read()
    check("the site's plan page: the face sets no markup (the page sets every name as text)",
          "innerHTML" not in face and "insertAdjacentHTML" not in face)
    node = shutil.which("node")
    if not node:
        print("SKIP the site's plan face in node: no node")
        return
    # Add to my calendar: the face's Ics restates planner/ics.py (change one, change both): the same file on the same docs
    import datetime as _dt
    from due_crew.planner import ics as ICS
    docs = [("p1", "Path, six weeks; done", {"units": [
                {"id": "a", "name": "Cell injury, part 1", "opens": "2026-11-02", "due": "2026-11-04"},
                {"id": "b", "name": "Inflammation\nand more", "opens": "2026-11-05", "due": "2026-11-01"},
                {"id": "c", "name": "", "opens": "2026-11-09"}, {"id": "d", "name": "Skipped", "opens": "2026-11-10"},
                {"id": "e", "name": "Bad day", "opens": "2026-13-40"}, "not a set"],
             "events": [{"id": "q1", "day": "2026-11-12", "name": "Heme quiz"}, {"id": "q2", "day": "x"}],
             "reviews": [{"day": "2026-11-11", "from": "a", "to": "b"}]}, {"a": 120, "b": 1, "c": 0}, ["d"]),
            ("p2", "Ünïcödé " + "名前 " * 30, {"units": [{"id": "u", "name": "Ωmega " * 20, "opens": "2026-12-31"}]}, {"u": 1234567}, []),
            ("p3", None, {}, None, [])]
    now = _dt.datetime(2026, 11, 1, 9, 5, 7, tzinfo=_dt.timezone.utc)
    prog = ("const vm = require('vm'), fs = require('fs');"
            "const ctx = { console, URL, Blob: undefined, Date, JSON, Math, Set, Map, Object, Array, String, Number, RegExp };"
            "ctx.addDays = (s, n) => { const d = new Date(`${s}T00:00:00Z`); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };"
            "vm.createContext(ctx); vm.runInContext(fs.readFileSync(process.argv[1], 'utf8') + ';this.PF = PlanFace;', ctx);"
            "const cases = JSON.parse(process.argv[2]), now = new Date(process.argv[3]);"
            "process.stdout.write(JSON.stringify(cases.map(([pid, name, doc, counts, skip]) => [ctx.PF.Ics.calendar(pid, name, doc, counts, skip, now), ctx.PF.Ics.fileName(name)])));")
    got = subprocess.run([node, "-e", prog, os.path.join(site, "planface.js"), json.dumps(docs), now.isoformat()],
                         capture_output=True, text=True, timeout=60)
    try:
        js = json.loads(got.stdout)
    except ValueError:
        js = None
    want = [[ICS.calendar(pid, name, doc, counts, skip, now=now), ICS.file_name(name)] for pid, name, doc, counts, skip in docs]
    check("the site's plan face: Add to my calendar makes ics.py's file, byte for byte, and its name (the face's Ics, its twin)",
          js == want, (got.stderr[-600:] if js is None else [a[0][:400] for a, b in zip(js, want) if a != b][:1]))
    got = subprocess.run([node, os.path.join(REPO, "tests", "planface_test.js")], capture_output=True, text=True, timeout=180)
    try:
        out = json.loads(got.stdout)
    except ValueError:
        check("the site's plan face ran in node", False, (got.stdout + got.stderr)[-1500:])
        return
    check("the site's plan face ran in node", not out.get("crash"), out.get("crash"))
    for name, ok, detail in out["checks"]:
        check(name, ok, detail)


def test_board_motion_v380():
    """3.8.0, "Board in Motion" (all seventeen): one motion.js, byte for byte
    on the board and duecrew.com; the swap notes the board before and moves
    what changed after; every add-on class its rules name is still drawn;
    nothing moves on its own clock but studying now, and only without
    Reduce motion; a cheer sent floats; the open box says Done for today."""
    root = os.path.join(REPO, "due_crew", "motion.js")
    js = open(root, encoding="utf-8").read()
    site = open(os.path.join(REPO, "site", "public", "motion.js"), encoding="utf-8").read()
    check("motion: one file, the same on the board and the site", js == site)
    sw = board.swap_js("<div id='due-crew'></div>")
    check("motion: the swap notes the board before it and moves what changed after; a fault in it never stops the swap",
          "try { mo = window.dcMotion ? dcMotion.before(el) : null; } catch (e) { mo = null; }" in sw
          and "try { if (mo) { dcMotion.after(nu, mo); } } catch (e) {}" in sw
          and sw.index("dcMotion.before(el)") < sw.index("replaceChild(nu, el)") < sw.index("dcMotion.after(nu, mo)"))
    check("motion: loaded with the board's script after every draw", board.MOTION_JS == js and js in board.keep_me_in_view_js())
    check("motion: Reduce motion stops it all (the script asks; the CSS only moves without it)",
          "prefers-reduced-motion: reduce" in js and "if (!el || !el.animate || !M.ok()) return null;" in js
          and "@media (prefers-reduced-motion: no-preference)" in board._css({}))
    css = board._css({})
    breathing = css[css.index("@media (prefers-reduced-motion: no-preference)"):]
    check("motion: studying now breathes, and ↻ turns, only there", "dcbreathe 2.4s" in breathing and "dcspin" in breathing
          and "animation:" not in css[:css.index("@media (prefers-reduced-motion: no-preference)")].split("dcfall")[0].replace("animation: none", ""))
    sel = " ".join(re.findall(r'sel: "([^"]+)"', js)) + " " + " ".join(re.findall(r"closest\(['\"]([^'\"]+)['\"]\)", js))
    site_only = {"pills", "sqsw", "bgmini", "bgt", "brd", "foot", "dc-panel", "st-tabs", "logo-inline"}
    names = sorted({c for c in re.findall(r"\.([a-z][a-z0-9-]*)", sel)} - site_only)
    drawn = fakes.board_source()
    missing = [c for c in names if not re.search(r'class="[^"]*\b%s\b|class=\\?"[^"]*\b%s\b|\.%s\b' % (c, c, c), drawn)]
    check("motion: every class its rules name is one the board draws (a rename can't switch a motion off)",
          len(names) >= 25 and not missing, (missing, names))
    check("motion: nothing in it sorts, so no row slides past another (never a race)", "sort(" not in js)
    social = open(os.path.join(REPO, "due_crew", "social.py"), encoding="utf-8").read()
    check("motion: a cheer sent floats up from their row (the glue asks, escaped as JSON)",
          'mw.web.eval("window.dcMotion&&dcMotion.cheer(%s,%s)" % (json.dumps(str(to_uid)), json.dumps(str(emoji))))' in social)
    check("motion: Add tells the next redraw what it added and from where", "dcMotion.say({add: inp.value.trim().slice(0, 16), when: w" in board.DUE_JS)
    from due_crew import due as D
    day = TODAY.isoformat()
    v = D.view(day, [], [{"id": "z1", "t": "Practice", "d": day, "done": day, "at": day}], {}, reviews={"due": 0, "done": 5})
    v["done"] = D.done_for_today(v)  # as due_flow sets it
    html = board._due_html(v)
    check("motion: the open box says Done for today, as the folded line does; the foot's Updated is its own span",
          "&#10003; Done for today" in html and '<span class="upd">Updated ' in board.render(
              {"entries": [], "labels": [day], "tomorrow": "", "pending": []}, {}, 0), html[:600])


def test_board_motion_round_two_v380():
    """3.8.0, Board in Motion round two (all eighteen): the rules for what
    leaves and what comes in, Settings sliding over the board, a profile out
    of its name, and the memory that lets a board drawn anew (back from a
    review) move what changed while I was away; the glue's parts: a friend
    arriving once, Study today's next deck, Copied ✓ on the link itself."""
    js = open(os.path.join(REPO, "due_crew", "motion.js"), encoding="utf-8").read()
    for sel in ("th > a.on", ".dc-wrap", ".du-line", ".dc-room .fc > i", ".irow", ".tmap .tm", ".du-bh"):
        check(f"motion 2: a rule for {sel}", f'sel: "{sel}"' in js)
    plan = js[js.index("    plan: function (el, was) {"):js.index("    map: function (el, was, v, snap)")]
    check("3.9.3: switching plans slides (Sam): a rule for the names, the pressed one moves, the plan comes from its side, the box to its height",
          'sel: ".psw", kind: "plan"' in js and "slide(el, x.on)" in plan and "now.i < x.on.i ? -1 : 1" in plan
          and 'translateX(" + (24 * dir) + "px)' in plan and "inner(box, x.h)" in plan, plan[:300])
    check("motion 2: what leaves comes back for a moment only where it sat, under the same heading, and never twice",
          "function putBack(root, o, sel)" in js and "sig(p, sel) !== o.pc" in js and '"[data-dc-ghost]"' in js
          and 'g.style.pointerEvents = "none"' in js and 'removeAttribute("id")' in js)
    check("motion 2: a topic pushed out by another isn't 'sticking now'; a tab's own lines don't slide in",
          'rule.leave.fx === "sticking" && fresh.irow' in js and '(x[0] === "wrap" || x[0] === "note" || x[0] === "face")' in js)
    check("motion 2: the memory moves changes only (no tab, fold, map or enter), the same Anki day, a few hours at most",
          "var MEMO = { tick: 1, bar: 1, text: 1, due: 1, row: 1, num: 1, pop: 1, stamp: 1, shout: 1, irow: 1, shade: 1 };" in js
          and "snap.day === day(root) && snap.me === me(root) && Date.now() - snap.t < 3 * 3600 * 1000" in js
          and "if (!cold && !snap.mem) entered.push" in js and "Date.now() - (M.swapped || 0) > 1000" in js)
    keep = board.keep_me_in_view_js()
    check("motion 2: every draw tells the memory, after the motion layer loads, and a fault never stops the board",
          keep.endswith(board.MOTION_DRAWN) and "try { if (window.dcMotion) { dcMotion.drawn(document.getElementById('due-crew')); } } catch (e) {}"
          in board.MOTION_DRAWN and keep.index(board.MOTION_JS) < keep.index(board.MOTION_DRAWN))
    check("motion 2: Settings and the board slide past each other, as a page", 'if (snap.mode && snap.mode !== mode(root)) { turn(root, snap); return; }' in js)
    for name, card_js in (("profile", board.profile_overlay_js({"name": "Dre", "uid": "dre", "cells": [1] * 14, "start": TODAY.isoformat()})),
                          ("good-luck", board.luck_card_js("Marisa", [("Dre", "Go")])),
                          ("stranger", board.stranger_card_js({"uid": "u2", "name": "Maya"}))):
        check(f"motion 2: the {name} card opens through the motion layer (out of the name; every close goes back)",
              card_js.count("dcMotion.open(back, card)") == 1
              and card_js.index("document.body.appendChild(back);") < card_js.index("dcMotion.open(back, card)"))
    check("motion 2: the card's close is its own remove, so ✕, Escape and a click outside all go back into the name",
          "back.remove = function ()" in js and "Element.prototype.remove.bind(back)" in js)
    from due_crew import due as D
    day = TODAY.isoformat()
    v = D.view(day, [], [], {}, reviews={"due": 30, "done": 5})
    full = board._due_html(dict(v, study_to="<Cardio>"))
    one = board._due_html(dict(v, study_to="<Cardio>", folded=True))
    check("3.9.3: no Study today in the box, open or folded (Sam); Ctrl+Shift+S still walks the day",
          "duestudy" not in full and "Study today" not in full and "duestudy" not in one and "Study today" not in one, full[:400])
    site = open(os.path.join(REPO, "site", "public", "app.js"), encoding="utf-8").read()
    builder = open(os.path.join(REPO, "site", "public", "builder.js"), encoding="utf-8").read()
    check("motion 2: duecrew.com's copies say Copied ✓ in place; the code's digits land; a year waves once a page",
          "if (window.dcMotion) return dcMotion.copied(btn);" in site and "if (window.dcMotion) return dcMotion.copied(b);" in builder
          and 'status.textContent = "Signed in ✓"' in site and "yearHeat.waved ||= new Set()" in site)
    check("motion 2: a friend arrives on duecrew.com too, once each in this browser, never the first time",
          "`dc-seen:${b.me.uid}`" in site and "if (Array.isArray(was))" in site)
    wave = js[js.index("M.logo = function"):js.index("// 13: a cheer you send")]
    check("motion 2: the logo does the wave: its studied days only, by a move alone (never a fill or a shape), once at a time",
          'translateY(-15px)' in wave and "if (!off) anim(d," in wave and "fill" not in wave.split("if (!off) anim(d,")[1].split("i++;")[0]
          and "setAttribute(\"fill\"" not in wave and ".style.fill" not in wave and 'svg.getAttribute("data-waving")' in wave)
    check("motion 2: it waves on a hover, with the first board of the day, and when the day's done",
          'closest("svg.dc-mark, svg.logo-inline")' in js and 'sessionStorage.getItem(MEM + ":logo") !== today' in js
          and 'sweep(el); M.logo(el.closest("#due-crew, .brd") || document, 500);' in js)
    check("motion 2: the plan calendar: ‹ › slide it, a moved date settles (its chips keyed by unit and source)",
          '"data-k": c.u ?' in builder and "slid = k;" in builder
          and 'M.moved(".cal2 .ch[data-k]", "data-k", was, slid, ".cal2", ".d")' in builder and "(slid || at === `${view}|${anchor}`)" in builder)


def test_board_motion_round_two_glue_v380():
    """3.8.0, Board in Motion round two, the add-on's part: a friend new to
    this profile's board arrives once (wrap.json); Study today's first deck
    comes from the deck tree the box already read; a copy tells the page."""
    wrap = _patched_due_crew()
    me = {"user_id": "me", "you": True}
    ents = [me, {"user_id": "dre"}, {"user_id": "maya"}]
    check("arrive: the first time, everyone's known already: nothing moves, all kept",
          wrap._arrivals(ents, "me") == [] and wrap._wrap_data()["crew_seen"] == {"uid": "me", "seen": ["dre", "maya"]})
    check("arrive: someone new, once; then not again", wrap._arrivals(ents + [{"user_id": "noah"}], "me") == ["noah"]
          and wrap._arrivals(ents + [{"user_id": "noah"}], "me") == [])
    check("arrive: under another account, it starts over without a fuss", wrap._arrivals(ents, "other") == []
          and wrap._wrap_data()["crew_seen"]["uid"] == "other")
    check("arrive: no board yet, or nobody signed in: nothing", wrap._arrivals(None, "me") == [] and wrap._arrivals(ents, "") == [])
    check("arrive: an empty crew is still a first time, so the first friend arrives",
          wrap._arrivals([{"user_id": "x", "you": True}], "x") == [] and wrap._arrivals([{"user_id": "x", "you": True}, {"user_id": "p"}], "x") == ["p"])
    wrap._wrap_data()["crew_seen"] = {"uid": "me", "seen": [f"u{i}" for i in range(wrap.CREW_SEEN_MAX)]}
    wrap._arrivals(ents, "me")
    check("arrive: the list is capped, newest kept", len(wrap._wrap_data()["crew_seen"]["seen"]) == wrap.CREW_SEEN_MAX
          and wrap._wrap_data()["crew_seen"]["seen"][-2:] == ["dre", "maya"])
    import due_crew as dc
    saved = (dc._arrivals, dc.client)
    try:
        dc._arrivals = lambda e, me: ["dre</script>"]
        dc.client = lambda: types.SimpleNamespace(user_id="me")
        got = dc._arrive_js()
        check("arrive: the page is told by JSON, after the draw and after a swap",
              got == 'try{window.dcMotion&&dcMotion.arrive(["dre</script>"]);}catch(e){}', got)
        dc._arrivals = lambda e, me: []
        check("arrive: nobody new, nothing said", dc._arrive_js() == "")
    finally:
        dc._arrivals, dc.client = saved
    src = srcs.glue_src()
    check("arrive: both draws carry it (3.9.1: after the board's scripts, or their calls)",
          "keep, fridge = _board_js(drawn=True)\n    mw.web.eval(\"window.dcBK=%s;\" % board._json.dumps(board.BOARD_KEY)" in src
          and "                + keep + _arrive_js()" in src
          and "keep, fridge = _board_js()\n    js = board.swap_js(html_out, have) + keep + _arrive_js()" in src)
    from due_crew import ui as U
    said = []
    saved = (U._clip, getattr(U.mw, "web", None))
    try:
        U._clip = lambda t: True
        U.mw.web = types.SimpleNamespace(eval=said.append)
        check("copied: a copy tells the page, which says Copied ✓ on the link clicked",
              U.copy_text("hi") is True and said == ["try{window.dcMotion&&dcMotion.copied();}catch(e){}"], said)
    finally:
        U._clip = saved[0]
        U.mw.web = saved[1]


def _tag_col():
    """Six notes in deck 10 ("Step 1"): 1-3 under #Book::Ch07, 4-6 under
    #Video::Auto; 6 also carries the person's own tag "mine"."""
    conn = sqlite3.connect(":memory:")
    fakes.make_collection(conn)
    for i in range(1, 7):
        fakes.add_card(conn, i, did=10, tags=("#Book::Ch07" if i <= 3 else "#Video::Auto") + (" mine" if i == 6 else ""))
    col = fakes.FakeCol(conn, fakes.day_cutoff_for(TODAY))
    col.decks = fakes.FakeDecks({10: "Step 1"})
    return col


def _tags_of(col, nid):
    return str(col.db.conn.execute("SELECT tags FROM notes WHERE id = ?", (nid,)).fetchone()[0]).split()


def test_plan_tags_v380():
    """3.8.0, plan tags (Sam's picks: real tags, owner and co-authors only,
    the AI on duecrew.com; DueCrew::<plan>::<tag>; made from tags too;
    a follower's Anki gets one as soon as the plan updates). The name rule
    is one in three places; the doc keeps names and guids only; this copy's
    notes carry each tag exactly where the plan says, in one undo step,
    and nothing else is ever touched."""
    from due_crew import plans as P
    from due_crew.backend import shapes
    # the same cases as worker/test/plantags.test.ts
    check("tags: a name is one part of an Anki tag (plans.ts tagPart's cases)",
          (P.tag_part("SLG 12"), P.tag_part("  SLG  12: receptors "), P.tag_part('a "quoted"*\\%name'), P.tag_part("___"))
          == ("SLG_12", "SLG_12-_receptors", "a_quotedname", "tag"))
    check("tags: the plan's part from its name (tagRoot's cases)",
          (P.tag_root("MS2 Block 1"), len(P.tag_root("x" * 80)), P.tag_root(":::")) == ("MS2_Block_1", 60, "plan"))
    builder = open(os.path.join(REPO, "site", "public", "builder.js"), encoding="utf-8").read()
    worker = open(os.path.join(REPO, "worker", "src", "plans.ts"), encoding="utf-8").read()
    rule = 'replace(/\\s+/gu, "_").replace(/["*\\\\%]/g, "").replace(/:/g, "-")'
    check("tags: builder.js and plans.ts spell the rule the same way (the twins)", rule in builder and rule in worker, rule)
    doc = shapes.clean_plan_doc({"deck": "Step 1", "units": [], "tagroot": "MS2_Block_1", "tags": [
        {"id": "t1", "name": "SLG 12", "notes": ["guid000001", "guid000002", "gone"], "text": "card text"},
        {"id": "t2", "name": "SLG 14", "tags": ["#Book::Ch07"], "n": 3},
        {"id": "t3", "name": "Empty"}, {"id": "BAD!", "name": "x", "tags": ["A"]}]})
    check("tags: cleaned on arrival: names, guids and sources only; one holding nothing goes",
          doc.get("tagroot") == "MS2_Block_1" and [t["id"] for t in doc.get("tags", [])] == ["t1", "t2"]
          and "text" not in doc["tags"][0] and doc["tags"][1]["n"] == 3, str(doc.get("tags")))
    check("tags: a root that isn't one Anki tag part is dropped, and its tags with it",
          "tags" not in shapes.clean_plan_doc({"deck": "D", "units": [], "tagroot": "MS2 Block", "tags": doc["tags"]}))
    col = _tag_col()
    idx = P.DeckIndex(col, 10)
    applied, res = P.sync_tags(col, idx, doc, {}, "Due Crew: MS2 Block 1's tags")
    check("tags: on the notes they hold here: by guid, and a tag's cards in this copy",
          applied == {"t1": "DueCrew::MS2_Block_1::SLG_12", "t2": "DueCrew::MS2_Block_1::SLG_14"}
          and "DueCrew::MS2_Block_1::SLG_12" in _tags_of(col, 1) and "DueCrew::MS2_Block_1::SLG_12" in _tags_of(col, 2)
          and all("DueCrew::MS2_Block_1::SLG_14" in _tags_of(col, n) for n in (1, 2, 3))
          and not any(t.startswith("DueCrew") for n in (4, 5, 6) for t in _tags_of(col, n)), str(applied))
    check("tags: what's new is said, with the exact notes this copy lacks",
          res["new"] == ["SLG 12", "SLG 14"] and res["missing"] == {"SLG 12": 1} and res["added"] == 5, str(res))
    check("tags: one undo step, named", [x[0] for x in col.undo_steps] == ["Due Crew: MS2 Block 1's tags"], str(col.undo_steps))
    again = P.sync_tags(col, P.DeckIndex(col, 10), doc, applied, "again")
    check("tags: nothing to do, nothing done (no undo step)", again[1]["added"] == again[1]["removed"] == 0
          and len(col.undo_steps) == 1 and again[1]["new"] == [])
    doc2 = dict(doc, tags=[dict(doc["tags"][0], name="SLG 12b", notes=["guid000002", "guid000004"])])
    applied2, res2 = P.sync_tags(col, P.DeckIndex(col, 10), doc2, applied, "Due Crew: update")
    check("tags: renamed in the plan, renamed here; a note taken out and one put in; a gone tag comes off",
          applied2 == {"t1": "DueCrew::MS2_Block_1::SLG_12b"}
          and "DueCrew::MS2_Block_1::SLG_12b" in _tags_of(col, 2) and "DueCrew::MS2_Block_1::SLG_12b" in _tags_of(col, 4)
          and not any(t.startswith("DueCrew") for t in _tags_of(col, 1)) and not any("SLG_14" in t for n in (1, 2, 3) for t in _tags_of(col, n))
          and res2["new"] == [] and len(col.undo_steps) == 2, str((applied2, res2, [_tags_of(col, n) for n in range(1, 7)])))
    check("tags: the person's own tags and the deck's are never touched",
          "mine" in _tags_of(col, 6) and "#Book::Ch07" in _tags_of(col, 1) and "#Video::Auto" in _tags_of(col, 4))
    sneaky = {"t9": "mine", "t1": "DueCrew::MS2_Block_1::SLG_12b"}
    P.sync_tags(col, P.DeckIndex(col, 10), doc2, sneaky, "x")
    check("tags: a stored name not under DueCrew is never taken off", "mine" in _tags_of(col, 6))
    n = P.drop_tags(col, doc2, "Due Crew: MS2 Block 1's tags off")
    check("tags: unfollowing takes the plan's tags off every note, one step",
          n == 2 and not any(t.lower().startswith("duecrew") for k in range(1, 7) for t in _tags_of(col, k))
          and col.undo_steps[-1][0] == "Due Crew: MS2 Block 1's tags off")
    check("tags: an Anki search for one, its _ \" * \\ read as themselves",
          P.tag_search('DueCrew::MS2_Block_1::a"b*c') == '"tag:DueCrew::MS2\\_Block\\_1::a\\"b\\*c')
    check("tags: only under DueCrew, ever", P.drop_tags(col, "mine::x", "x") == 0 and "mine" in _tags_of(col, 6))


def test_plans_review_tag_roots_and_ids_twin():
    """3.8.1's plans review, the fake's side (worker/test/plansreview.test.ts
    is the Worker's): a plan whose name fifty plans share still makes its
    first tag, on a root ending in its own id; a site save keeps a date's
    note ids only while its tags, subdecks and cuts are what they came from."""
    w = world({"dre": "Dre", "maya": "Maya"})
    pid, _code = w.add_plan("dre", "Block", "Step 1", [])
    for r in ["block"] + [f"Block_{i}" for i in range(2, 51)]:  # case aside, as Anki's tags
        other, _c = w.add_plan("someone", "Other", "Step 1", [])
        w.plans[other]["doc"]["tagroot"] = r
    dre = new_client(w, "dre", "Dre")
    got, status = dre.tag_plan_notes(pid, "SLG 12", add=["guid000001"])
    check("roots: past _50, the plan's own id makes it its own, and it fits",
          status == 200 and got["doc"]["tagroot"] == f"Block_{pid}" and len(got["doc"]["tagroot"]) <= 60, str((status, got and got["doc"])))
    full, _c = w.add_plan("dre", "Block", "Step 1", [])
    for r in (f"Block_{full}", full):
        other, _c = w.add_plan("someone", "Other", "Step 1", [])
        w.plans[other]["doc"]["tagroot"] = r
    try:
        said = dre.tag_plan_notes(full, "SLG 1", add=["guid000001"])[1]
    except shapes.TransportError as e:
        said = e.status
    check("roots: every one taken is try again, not a crash", said == 503, str(said))
    # a date's note ids (3.3, C5), from the author's Anki, through a site save
    w2 = world({"dre": "Dre"})
    qid, _c = w2.add_plan("dre", "Cardio", "Step 1", _plan_units())
    dre = new_client(w2, "dre", "Dre")
    units = w2.plans[qid]["doc"]["units"]
    snap = {u["id"]: [u["tags"], u["decks"], [f"n{i}"]] for i, u in enumerate(units) if u["id"] in ("hf", "ar")}
    check("ids: the author's Anki sends them", dre.put_ids(qid, snap))
    ids = lambda: {u["id"]: u.get("ids") for u in w2.plans[qid]["doc"]["units"] if u["id"] in ("hf", "ar")}
    doc = json.loads(json.dumps(w2.plans[qid]["doc"]))
    w2.edit_plan(qid, [dict(u, name="HF") if u["id"] == "hf" else u for u in doc["units"]])
    check("ids: a save that keeps a date's tags keeps them", ids() == {"hf": ["n0"], "ar": ["n1"]}, str(ids()))
    doc = json.loads(json.dumps(w2.plans[qid]["doc"]))
    w2.edit_plan(qid, [dict(u, tags=u["tags"] + ["Step1::Cardio::Cardiomyopathy"]) if u["id"] == "hf" else u for u in doc["units"]])
    check("ids: a tag added to a date drops its ids (worked out from the tags it had); the others stay",
          ids() == {"hf": None, "ar": ["n1"]}, str(ids()))
    doc = json.loads(json.dumps(w2.plans[qid]["doc"]))
    w2.edit_plan(qid, [dict(u, ids=["forged"]) for u in doc["units"]])
    check("ids: a save never sets them", ids() == {"hf": None, "ar": ["n1"]}, str(ids()))


def test_plans_review_follows_authors_twin():
    """3.8.1's plans review, the fake's side: the follow ceiling counts the
    plans I can see (a squad's plan I left is hidden, kept, not counted); a
    co-author uploads ids and adds cards as the owner does; my list carries
    the plans I co-author; the board and its stamp move with leaving a
    squad, a co-author's plan saved, and a plan offered to my squad."""
    w = world({"dre": "Dre", "maya": "Maya", "jo": "Jo"})
    dre, maya, jo = new_client(w, "dre", "Dre"), new_client(w, "maya", "Maya"), new_client(w, "jo", "Jo")
    sq = dre.create_squad("MS2")
    check("follows: in the squad", maya.join_squad(sq["id"], sq["code"]) == 200)
    codes = [w.add_plan("dre", f"Week {i + 1}", "Step 1", [], audience="squad", squad=sq["id"])[1] for i in range(20)]
    check("follows: twenty of the squad's plans", all(maya.follow_plan(c)[1] == 200 for c in codes))
    _other, other_code = w.add_plan("jo", "Renal", "Step 1", [])
    check("follows: twenty I can see is the ceiling", maya.follow_plan(other_code)[1] == 409)
    labels = [_day(0)]
    maya.fetch_board(labels, with_decks=True)
    pv = maya.session.get("plans_pv")
    check("follows: leaving the squad", maya.leave_squad(sq["id"]))
    upd = maya.fetch_board(labels)
    check("follows: its plans leave my board at the next refresh (the stamp moved)",
          upd["plans_fresh"] and maya.session.get("plans_pv") != pv and maya.session.get("plans") == [], str(maya.session.get("plans")))
    check("follows: and my list", maya.my_plans() == [])
    check("follows: hidden ones don't count toward the twenty", maya.follow_plan(other_code)[1] == 200)
    # a co-author: ids, cards, my list, my board's authored plans
    pid, _c = w.add_plan("dre", "Cardio", "Step 1", _plan_units())
    w.plans[pid]["editors"] = {"jo"}
    hf = next(u for u in w.plans[pid]["doc"]["units"] if u["id"] == "hf")
    check("co-author: uploads the note ids behind a date", jo.put_ids(pid, {"hf": [hf["tags"], hf["decks"], ["g1"]]})
          and next(u for u in w.plans[pid]["doc"]["units"] if u["id"] == "hf").get("ids") == ["g1"])
    check("co-author: adds cards from Anki's browser", jo.add_plan_cards(pid, [["guid000077", 0]], unit="ar")[1] == 200)
    check("co-author: not a follower, who can't", maya.add_plan_cards(pid, [["guid000077", 0]], unit="ar")[1] == 403
          and not maya.put_ids(pid, {}))
    mine = jo.my_plans()
    check("co-author: my list carries the plans I co-author, as an editor",
          [(p["id"], p["role"]) for p in mine if p["id"] == pid] == [(pid, "editor")], str([(p["id"], p["role"]) for p in mine]))
    jo.fetch_board(labels, with_decks=True)
    v = next(a["version"] for a in jo.session["plans_authored"] if a["id"] == pid)
    check("stamp: nothing moved, nothing comes", not jo.fetch_board(labels)["plans_fresh"])
    maya.fetch_board(labels)  # her own follow since her last refresh: seen
    w.edit_plan(pid, w.plans[pid]["doc"]["units"])
    jo.fetch_board(labels)
    check("stamp: a save to a plan I co-author reaches my Anki at the next refresh",
          next(a["version"] for a in jo.session["plans_authored"] if a["id"] == pid) == v + 1)
    check("stamp: and moves no one else's", not maya.fetch_board(labels)["plans_fresh"])
    # a plan offered to a squad I'm in
    check("offers: back in the squad", maya.join_squad(sq["id"], sq["code"]) == 200)
    maya.fetch_board(labels)
    w.add_plan("dre", "Neuro", "Step 1", [], audience="squad", squad=sq["id"])
    maya.fetch_board(labels)
    check("offers: a plan offered to my squad comes at the next refresh",
          "Neuro" in [o["name"] for o in maya.session.get("plan_offers") or []], str(maya.session.get("plan_offers")))
    check("offers: and the squad's plans I follow are back on my board",
          len(maya.session.get("plans") or []) == 21, str(len(maya.session.get("plans") or [])))


def test_coauthors_say_yes_v381():
    """3.8.1, round three, the fake's side (worker/src/plans.ts): asking
    someone to co-write a plan is an invite until they say yes: no saves, no
    tags in their Anki, listed only to the authors. The day's first board
    carries my invites (who asked, by name and emoji) and the stamp moves
    with them, so an invite costs no request of its own. An owner offers the
    plan to a co-author; a yes swaps them, the plan's code and followers stay."""
    w = world({"dre": "Dre", "jo": "Jo", "kim": "Kim"}, friends={"dre": ["jo"], "jo": ["dre"]})
    dre, jo, kim = new_client(w, "dre", "Dre"), new_client(w, "jo", "Jo"), new_client(w, "kim", "Kim")
    w.users["dre"]["emoji"] = "🦊"
    pid, code = w.add_plan("dre", "MS2 Block 1", "Step 1", _plan_units())
    check("follow: kim follows it", kim.follow_plan(code)[1] == 200)
    labels = [_day(0)]
    jo.fetch_board(labels, with_decks=True)
    pv = jo.session.get("plans_pv")
    check("invite: a stranger to the owner can't be asked", dre._call("POST", f"/plans/{pid}/editors", {"uid": "kim"})[0] == 403)
    st, view = dre._call("POST", f"/plans/{pid}/editors", {"uid": "jo"})
    check("invite: the owner sees it waiting", st == 200 and view["editors"] == [{"uid": "jo", "name": "Jo", "emoji": "", "pending": True}],
          str(view.get("editors")))
    check("invite: a follower doesn't", kim._call("GET", f"/plans/{pid}")[1]["editors"] == [])
    n = len(w.requests())
    upd = jo.fetch_board(labels)
    check("invite: it arrives with the next refresh, no request of its own (the stamp moved)",
          upd["plans_fresh"] and jo.session.get("plans_pv") != pv and len(w.requests()) == n + 1)
    st, b = jo._call("GET", "/board?decks=1")
    check("invite: the day's first board names who asked, by name and emoji only",
          b["planInvites"] == [{"id": pid, "name": "MS2 Block 1", "kind": "coauthor", "by": {"name": "Dre", "emoji": "🦊"}}],
          str(b.get("planInvites")))
    check("invite: and the site's home", jo._call("GET", "/board?keep=1")[1].get("planInvites") == b["planInvites"])
    check("invite: until a yes, not a co-author: no ids, no notes, not in my Anki's authored plans",
          not jo.put_ids(pid, {}) and jo._call("POST", f"/plans/{pid}/remarks", {"add": {"card": ["g", 0], "text": "x"}})[0] == 403
          and b["authored"] == [] and jo.my_plans() == [])
    check("invite: a yes", jo._call("POST", f"/plans/{pid}/invite", {"yes": True})[1].get("role") == "editor")
    st, b = jo._call("GET", "/board?decks=1")
    check("invite: answered, it goes; the plan is one I write", b["planInvites"] == [] and [a["id"] for a in b["authored"]] == [pid])
    check("invite: nothing more to answer", jo._call("POST", f"/plans/{pid}/invite", {"yes": True}) == (404, {"error": "no_invite"}))
    # the plan handed over
    check("owner: only to a co-author who said yes",
          dre._call("POST", f"/plans/{pid}/owner", {"uid": "kim"}) == (400, {"error": "not_coauthor"}))
    st, view = dre._call("POST", f"/plans/{pid}/owner", {"uid": "jo"})
    check("owner: offered, the authors see to whom", st == 200 and view.get("handover") == "jo"
          and "handover" not in kim._call("GET", f"/plans/{pid}")[1])
    check("owner: it waits on her board", jo._call("GET", "/board?decks=1")[1]["planInvites"]
          == [{"id": pid, "name": "MS2 Block 1", "kind": "owner", "by": {"name": "Dre", "emoji": "🦊"}}])
    st, view = jo._call("POST", f"/plans/{pid}/invite", {"yes": True})
    check("owner: a yes makes it hers, its owner a co-author; its code and followers stay",
          view["role"] == "owner" and w.plans[pid]["owner"] == "jo" and w.plans[pid]["editors"] == {"dre"}
          and w.plans[pid]["code"] == code and (pid, "kim") in w.follows and w.plans[pid].get("handover") is None, str(view))
    check("owner: the old owner writes it still, as a co-author", dre._call("GET", f"/plans/{pid}")[1]["role"] == "editor")
    jo._call("POST", f"/plans/{pid}/owner", {"uid": "dre"})
    check("owner: no leaves it hers", dre._call("POST", f"/plans/{pid}/invite", {"yes": False})[1]["role"] == "editor"
          and w.plans[pid]["owner"] == "jo")
    jo._call("POST", f"/plans/{pid}/owner", {"uid": "dre"})
    check("owner: removing the one it's offered to ends the offer",
          dre._call("DELETE", f"/plans/{pid}/editors/dre")[0] == 200 and w.plans[pid].get("handover") is None
          and "dre" not in w.plans[pid]["editors"])


def test_remarks_deck_link_and_picks_named_v381():
    """3.8.1, round three, the fake's side: where to get the deck (deckUrl,
    an https link); the authors' notes on a tag or a card (remarks), in the
    doc and one at a time from Anki's Browse; what a date's picked cards are
    (pl, from the author's "#lbl" counts), kept while its picks are the same."""
    w = world({"dre": "Dre", "kim": "Kim"})
    dre, kim = new_client(w, "dre", "Dre"), new_client(w, "kim", "Kim")
    pid, code = w.add_plan("dre", "MS2 Block 1", "Step 1", _plan_units())
    kim.follow_plan(code)
    base = w.plans[pid]["doc"]

    def doc_ok(**extra):
        try:
            return w._plan_doc(dict(base, **extra))
        except fakes.Bad:
            return None
    check("deck link: an https link is kept", doc_ok(deckUrl="https://example.org/deck?v=2")["deckUrl"] == "https://example.org/deck?v=2")
    check("deck link: none is none", "deckUrl" not in doc_ok(deckUrl=""))
    check("deck link: not http, a space, no host, or past 300",
          all(doc_ok(deckUrl=u) is None for u in ("http://example.org", "https://e.org/a b", "https://", "https:///x",
                                                   "https://e.org/" + "x" * 300, 7)))
    got = doc_ok(remarks=[{"id": "r1", "tag": "Step1::Micro::Herpes_Viruses", "text": " Watch the\nvideo first "},
                          {"id": "r2", "card": ["guid000050", 1], "text": "Mixes up with the next"}])
    check("remarks: a tag's and a card's, one line each", got["remarks"] == [
        {"id": "r1", "tag": "Step1::Micro::Herpes_Viruses", "text": "Watch the video first"},
        {"id": "r2", "card": ["guid000050", 1], "text": "Mixes up with the next"}], str(got.get("remarks")))
    check("remarks: exactly one target, 280 at most, ids unique, 300 a plan", all(doc_ok(remarks=r) is None for r in (
        [{"id": "r1", "tag": "T", "card": ["g", 0], "text": "both"}], [{"id": "r1", "text": "neither"}],
        [{"id": "r1", "card": ["g", -1], "text": "x"}], [{"id": "r1", "tag": "T", "text": "x" * 281}],
        [{"id": "r1", "tag": "T", "text": "a"}, {"id": "r1", "tag": "U", "text": "b"}],
        [{"id": f"r{i}", "tag": "T", "text": "a"} for i in range(301)])))
    v = w.plans[pid]["version"]
    st, view = dre._call("POST", f"/plans/{pid}/remarks", {"add": {"card": ["guid000050", 1], "text": "Read it twice"}})
    rid = (view.get("doc", {}).get("remarks") or [{}])[0].get("id")
    check("remarks: one from Browse is a save", st == 200 and w.plans[pid]["version"] == v + 1 and rid, str(view.get("doc", {}).get("remarks")))
    dre._call("POST", f"/plans/{pid}/remarks", {"add": {"card": ["guid000050", 1], "text": "Read it once"}})
    check("remarks: a second on that card changes its text", w.plans[pid]["doc"]["remarks"] == [
        {"id": rid, "card": ["guid000050", 1], "text": "Read it once"}])
    check("remarks: a follower can't", kim._call("POST", f"/plans/{pid}/remarks", {"remove": rid})[0] == 403)
    check("remarks: the author takes it off", dre._call("POST", f"/plans/{pid}/remarks", {"remove": rid})[0] == 200
          and "remarks" not in w.plans[pid]["doc"])
    check("remarks: a follower's board carries them with the plan",
          dre._call("POST", f"/plans/{pid}/remarks", {"add": {"tag": "Step1::Renal", "text": "Start here"}})[0] == 200
          and kim._call("GET", "/board?decks=1")[1]["plans"][0]["doc"]["remarks"][0]["text"] == "Start here")
    # a date's picks, named by the author's Anki
    lbl = [["Step1::Micro::Herpes_Viruses", 88], ["Step1::Micro::Pox", 2]]
    check("picks: named from the author's Anki", dre.put_ids(pid, {}, counts={"cz": {"#lbl": lbl}, "hf": {"#lbl": lbl}}))
    cz = lambda: next(u for u in w.plans[pid]["doc"]["units"] if u["id"] == "cz")
    hf = next(u for u in w.plans[pid]["doc"]["units"] if u["id"] == "hf")
    check("picks: kept as the date's pl; a date with no picks has nothing to name", cz().get("pl") == lbl and "pl" not in hf)
    dre.put_ids(pid, {}, counts={"cz": {"#lbl": [["a", 1]] * 4}})
    check("picks: anything else is skipped", cz().get("pl") == lbl)
    w.edit_plan(pid, [dict(u, name="Cloze 2") if u["id"] == "cz" else u for u in w.plans[pid]["doc"]["units"]])
    check("picks: a save with the same picks keeps it", cz().get("pl") == lbl and cz()["name"] == "Cloze 2")
    check("picks: and its followers get it", kim._call("GET", "/board?decks=1")[1]["plans"][0]["doc"]["units"][3].get("pl") == lbl)
    dre.add_plan_cards(pid, [["guid000051", 0]], unit="cz")
    check("picks: cards added from Browse: gone until it's named again", "pl" not in cz())
    dre.put_ids(pid, {}, counts={"cz": {"#lbl": lbl}})
    w.edit_plan(pid, [dict(u, cards=[["guid000050", 1]]) if u["id"] == "cz" else u for u in w.plans[pid]["doc"]["units"]])
    check("picks: other picks on the site: gone", "pl" not in cz())


# Names of the parts after this one. The package sets them as each of those parts loads
# (an import here would load a later part before the ones between).
_LATER = ("n", "t", "tag")
n = t = tag = None
