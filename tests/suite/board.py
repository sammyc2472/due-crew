"""The suite: the board, squads, decks, study rooms, the first plans (2.x to 3.0)."""

from due_crew import board
from due_crew.backend import api
from due_crew.backend import shapes
from due_crew.stats import gather_stats
from due_crew.stats import gather_week
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

from .base import BOARD_DREW, KK, REPO, TODAY, acked, as_board, check, fetch_as, make_user_col, new_client, showed_days, sync_once, world


# ---------------------------------------------------------------- scenarios

def test_one_sync_one_request():
    """A sync is one request carrying today, the week and the heatmap."""
    store = world({"sam": "Sammy"})
    cl = new_client(store, "sam", "Sammy")
    files = tempfile.mkdtemp()
    col = make_user_col([TODAY - datetime.timedelta(days=i) for i in range(16)])
    labels = sync_once(store, cl, col, files, {}, TODAY)
    check("sync: one request", store.requests() == [("POST", "/sync", 200)], str(store.log))
    week = json.loads(store.weeks["sam"][0])
    check("sync: the week holds the last seven days I studied", set(week["days"]) == set(labels))
    check("sync: the heatmap went with it, and its hash is kept",
          bool(store.heat.get("sam")) and bool(cl.session.get("heatmap_hash")))


def test_refused_sync_keeps_nothing():
    """A sync the server refuses (a shape it won't take) doesn't count as sent."""
    store = world({"sam": "Sammy"})
    cl = new_client(store, "sam", "Sammy")

    def refuse(_w):
        raise fakes.Bad(400, "bad_week")
    store._clean_week = refuse
    ok, gone = cl.push([TODAY.isoformat()], {}, heatmap={TODAY.isoformat(): 3})
    check("refused: the sync says it failed", ok is False and gone == [])
    check("refused: nothing is marked sent", not cl.session.get("heatmap_hash")
          and not cl.session.get("last_ok"))


def test_dots_gap():
    """Studies daily, syncs rarely: the week still arrives whole, because
    every sync sends the whole week."""
    store = world({"sam": "Sammy", "dre": "Dre"}, {"sam": ["dre"], "dre": ["sam"]})
    files = tempfile.mkdtemp()
    cl = new_client(store, "sam", "Sammy")
    study_days = [TODAY - datetime.timedelta(days=i) for i in range(16)]
    for sync_day in (TODAY - datetime.timedelta(days=2), TODAY):
        col = make_user_col([d for d in study_days if d <= sync_day], today=sync_day)
        sync_once(store, cl, col, files, {}, sync_day)
    dre = new_client(store, "dre", "Dre")
    data, labels, tomorrow = fetch_as(store, dre, make_user_col([TODAY]))
    sam_entry = next(e for e in data["entries"] if e["user_id"] == "sam")
    filled = showed_days(sam_entry, labels)
    streak_shown = (sam_entry["days"].get(labels[0]) or {}).get("streak")
    check(f"backfill: full week on the server ({filled}/7, streak {streak_shown})",
          filled == 7 and streak_shown == 16)


def test_backfill_costs():
    """A second sync the same day writes nothing; a new review rewrites the
    week once (and the heatmap, which counts it too)."""
    store = world({"sam": "Sammy"})
    cl = new_client(store, "sam", "Sammy")
    files = tempfile.mkdtemp()
    col = make_user_col([TODAY - datetime.timedelta(days=i) for i in range(9)])
    sync_once(store, cl, col, files, {}, TODAY)
    w0 = dict(store.wrote)
    sync_once(store, cl, col, files, {}, TODAY)       # nothing changed
    same = dict(store.wrote) == w0
    heat_sent = sum(1 for m, p, b in store.bodies if p == "/sync" and "heatmap" in (b or {}))
    noon = datetime.datetime.combine(TODAY, datetime.time(13))
    fakes.add_review(col.db.conn, int(noon.timestamp() * 1000))
    sync_once(store, cl, col, files, {}, TODAY)       # one new review today
    check("backfill: a no-change sync writes nothing", same, f"{w0} -> {store.wrote}")
    check("backfill: an unchanged heatmap isn't even sent", heat_sent == 1)
    check("backfill: a new review writes the week once",
          store.wrote.get("weeks") == w0.get("weeks", 0) + 1)


def test_studied_field_privacy():
    """All share_* off: no numbers reach the server, dots still work."""
    store = world({"sam": "Sammy", "dre": "Dre"}, {"sam": ["dre"], "dre": ["sam"]})
    cl = new_client(store, "sam", "Sammy")
    files = tempfile.mkdtemp()
    col = make_user_col([TODAY - datetime.timedelta(days=i) for i in (0, 1, 3)])
    cfg = {"share_reviews": False, "share_time": False,
           "share_retention": False, "share_streak": False}
    sync_once(store, cl, col, files, cfg, TODAY)
    days = json.loads(store.weeks["sam"][0])["days"]
    leaked = {k for d in days.values() for k in d
              if k in ("reviews", "studyTimeMs", "accuracy", "streak", "newCards")}
    dre = new_client(store, "dre", "Dre")
    data, labels, tomorrow = fetch_as(store, dre, make_user_col([TODAY]))
    sam_entry = next(e for e in data["entries"] if e["user_id"] == "sam")
    filled = showed_days(sam_entry, labels)
    check("privacy: no numeric fields uploaded when shares off", not leaked, str(leaked))
    check(f"privacy: studied flag still marks showed-up days ({filled}/7)", filled == 3)
    # a switch turned off takes the number off every day at once, light sync or not
    cl2 = new_client(store, "sam", "Sammy")
    cl2.session["week_raw"] = {labels[1]: {"reviews": 40, "streak": 2}}
    cl2.push(labels, {"share_streak": False})
    past = json.loads(store.weeks["sam"][0])["days"][labels[1]]
    check("privacy: turning a switch off clears it from past days too",
          past.get("reviews") == 40 and "streak" not in past, str(past))


def test_heatmap_roundtrip():
    store = world({"sam": "Sammy", "dre": "Dre"}, {"sam": ["dre"], "dre": ["sam"]})
    cl = new_client(store, "sam", "Sammy")
    counts = {(TODAY - datetime.timedelta(days=i)).isoformat(): i * 3 for i in range(60)}
    ok, _gone = cl.push([TODAY.isoformat()], {}, heatmap=counts)
    got = new_client(store, "dre", "Dre").fetch_heatmap("sam")
    check("heatmap: friend roundtrip preserves counts", ok and got == counts)
    stranger = world({"sam": "Sammy", "zed": "Zed"}, {"sam": ["zed"]})
    new_client(stranger, "sam").push([TODAY.isoformat()], {}, heatmap=counts)
    check("heatmap: not to someone I added who hasn't added me back",
          new_client(stranger, "zed").fetch_heatmap("sam") is None)


def test_heatmap_retraction():
    """Share off takes it down once; share back on puts it back."""
    store = world({"sam": "Sammy"})
    cl = new_client(store, "sam", "Sammy")
    files = tempfile.mkdtemp()
    col = make_user_col([TODAY])
    sync_once(store, cl, col, files, {}, TODAY)
    was_up = "sam" in store.heat
    off = {"share_heatmap": False}
    sync_once(store, cl, col, files, off, TODAY)
    gone = "sam" not in store.heat
    sent = lambda: sum(1 for m, p, b in store.bodies if p == "/sync" and "heatmap" in (b or {}))
    n0 = sent()
    sync_once(store, cl, col, files, off, TODAY)
    n1 = sent()
    sync_once(store, cl, col, files, {}, TODAY)
    back = "sam" in store.heat
    check("retract: heatmap uploaded, taken down once on share-off, restored on share-on",
          was_up and gone and n1 == n0 and back)


def test_version_probe():
    """GET /version once a day: below minClient, the footer says so."""
    store = world({"sam": "Sammy"})
    cl = new_client(store, "sam", "Sammy")
    ok_state = cl.check_version("2026-09-01", "3.0.0")
    again = len(store.log)
    cl.check_version("2026-09-01", "3.0.0")
    cached = len(store.log) == again
    store.min_client = "3.1.0"
    cl2 = new_client(store, "sam", "Sammy")
    stale_state = cl2.check_version("2026-09-01", "3.0.0")
    store.down = True
    cl3 = new_client(store, "sam", "Sammy")
    offline = cl3.check_version("2026-09-01", "3.0.0")
    store.down = False
    check("version: current client is fine", ok_state is False)
    check("version: asked once a day", cached)
    check("version: below minClient reads stale", stale_state is True and cl2.rules_stale)
    check("version: no network changes nothing", offline is False and not cl3.session.get("version_check"))


def test_duet_runs():
    from due_crew.stats import duet_runs
    mine = {"2026-08-28", "2026-08-29", "2026-08-30", "2026-08-31", "2026-09-01",
            "2026-08-20", "2026-08-21"}
    theirs = {"2026-08-29", "2026-08-30", "2026-08-31", "2026-08-20",
              "2026-08-21", "2026-08-22"}
    run, best = duet_runs(mine, theirs, "2026-09-01")
    # today not shared -> run counts back from yesterday: 31,30,29 = 3
    ok1 = (run, best) == (3, 3)
    run2, best2 = duet_runs(mine | {"2026-08-22"}, theirs, "2026-09-01")
    # 20,21,22 becomes best run of 3; current still 3
    ok2 = (run2, best2) == (3, 3)
    run3, best3 = duet_runs(set(), theirs, "2026-09-01")
    check("duet: current run tolerates a pending today", ok1, f"{run},{best}")
    check("duet: best run scans the window", ok2, f"{run2},{best2}")
    check("duet: empty overlap is 0/0", (run3, best3) == (0, 0))


def _patched_due_crew():
    """The wrap module with its per-profile files pointed at a temp dir."""
    from due_crew import wrap
    tmp = tempfile.mkdtemp()
    wrap._profile_files = lambda: tmp
    wrap._wrap["profile"] = None
    wrap._wrap["data"] = {}
    return wrap


def test_welcome_back():
    dc = _patched_due_crew()
    from due_crew import board as b
    labels = [(TODAY - datetime.timedelta(days=i)).isoformat() for i in range(7)]
    tomorrow = (TODAY + datetime.timedelta(days=1)).isoformat()
    w = dc._wrap_data()
    w["last_studied"] = {"noah": (TODAY - datetime.timedelta(days=12)).isoformat()}
    entries = [
        {"user_id": "sam", "name": "Sammy", "you": True, "paused": False,
         "days": {labels[0]: {"studied": True, "reviews": 5}}},
        {"user_id": "noah", "name": "Noah", "you": False, "paused": False,
         "days": {labels[0]: {"studied": True, "reviews": 118}}},
    ]
    toasts = dc._update_returns(entries, labels, tomorrow, {})
    again = dc._update_returns(entries, labels, tomorrow, {})
    check("welcome back: toast once with the true gap",
          len(toasts) == 1 and "12 days" in toasts[0] and "Noah" in toasts[0],
          str(toasts))
    check("welcome back: chip set, no repeat toast",
          entries[1].get("back") is True and not again)
    html = b._row_html({"user_id": "noah", "name": "Noah", "you": False,
                        "paused": False, "quiet": False, "stale": False,
                        "back": True, "exam": "", "last_updated": "",
                        "reviews": 118, "time_ms": 1, "retention": None,
                        "streak": 1}, "#2", {})
    check("welcome back: row renders the chip, in grey", '<span class="chip">back today</span>' in html)


def test_milestones():
    dc = _patched_due_crew()
    w = {"banner": {}}
    t1 = dc._accrue_milestones(w, 60_000, 3_600_000, "2026-09-01")
    t2 = dc._accrue_milestones(w, 50_000, 3_600_000, "2026-09-08")
    t3 = dc._accrue_milestones(w, 10, 0, "2026-09-15")
    check("milestones: quiet until a threshold", t1 is None)
    check("milestones: toast + banner clause at the crossing",
          t2 is not None and "100,000 reviews" in t2 and "September" in t2
          and w["banner"]["milestone"] == "100,000 reviews", str(t2))
    check("milestones: never repeats", t3 is None)


def test_exam_eve_and_rules_render():
    from due_crew import board as b
    labels = [(TODAY - datetime.timedelta(days=i)).isoformat() for i in range(7)]
    data = {"entries": [
        {"user_id": "sam", "name": "Sammy", "you": True, "paused": False,
         "last_updated": "", "exam_date": "", "days": {}, "decks": []}],
        "labels": labels, "tomorrow": "", "pending": []}
    html = b.render(data, {}, 0,
                    exam_eve={"people": [("p1", "Priya <x>")]},
                    rules_stale=True)
    check("exam eve: banner renders, name escaped, a line for their card wired (2.10)",
          "exam is tomorrow" in html and "Priya &lt;x&gt;" in html
          and "luckline:p1" in html and "Add a line to their card" in html and "evedismiss" in html)
    check("rules: footer notice renders",
          "server catching up" in html and "duecrew:rules" not in html)
    two = b.render(data, {}, 0, exam_eve={"people": [("p1", "Priya"), ("p2", "Theo")]})
    check("exam eve: two exams merge into one line",
          two.count("dc-wrap eve") == 1 and "have exams tomorrow" in two)


def test_copy_text():
    """Shares reach the clipboard as UTF-8: pbcopy on macOS, Qt fallback."""
    import subprocess
    from due_crew import ui as dc_ui
    text = "Today 📚 · ░▂█ — 🔥"
    calls = []
    real_run = subprocess.run
    real_platform = dc_ui.sys.platform

    def fake_run(args, **kw):
        calls.append((args, kw.get("input"), kw.get("env", {}).get("LC_ALL")))
        return None

    dc_ui.sys.platform = "darwin"
    subprocess.run = fake_run
    try:
        dc_ui.copy_text(text)
    finally:
        subprocess.run = real_run
    check("clipboard: macOS goes through pbcopy as UTF-8 under a UTF-8 locale",
          calls and calls[0][0] == ["pbcopy"] and calls[0][1] == text.encode("utf-8")
          and calls[0][2] == "en_US.UTF-8", str(calls))

    # pbcopy failing (or not macOS) -> Qt, and never an exception
    def boom(*a, **kw):
        raise OSError("no pbcopy")
    subprocess.run = boom
    seen = {}
    QApp = sys.modules["aqt.qt"].QApplication

    class Clip:
        def setMimeData(self, m):
            seen["mime"] = True
        def setText(self, t):
            seen["text"] = t
    QApp.clipboard = staticmethod(lambda: Clip())
    try:
        ok = dc_ui.copy_text(text)
    finally:
        subprocess.run = real_run
        dc_ui.sys.platform = real_platform
    check("clipboard: fallback lands on Qt without raising", ok and seen, str(seen))


def test_shares_v21():
    """Week squares, the today line, crew rows, and the honesty rules."""
    from due_crew import share
    labels = [(datetime.date(2026, 9, 1) + datetime.timedelta(days=i)).isoformat()
              for i in range(7)]
    flags = [True, True, True, False, True, True, True]
    mine = share.my_week(labels, flags, 3412, 28920000, 17)
    check("share: my week", mine.split("\n") == [
        "This week · Sep 1–7", "🟩🟩🟩⬜🟩🟩🟩 6 of 7 days",
        "3,412 reviews · 8h 02m · 🔥 17", share.FOOTER], mine)
    today = share.my_today("2026-09-09", 512, 4320000, 91.6, 17)
    check("share: today line", today.split("\n") == [
        "Today · Sep 9", "📚 512 reviews · ⏱ 1h 12m · 🎯 91.6% · 🔥 17", share.FOOTER], today)
    check("share: today without retention",
          share.my_today("2026-09-09", 3, 60000, None, 1).split("\n")[1]
          == "📚 3 reviews · ⏱ 1m · 🔥 1")
    crew = share.crew_week("orca", labels, [
        ("sammy", flags, ""),
        ("igk <b>\nx", [True] * 7, ""),
        ("Ameya", [True, False, True, True, False, True, True], "Tue"),
        ("Quiet", [False] * 7, ""),
    ], 21430, 148320000)
    rows = crew.split("\n")
    check("share: crew week header, order (most days first), absence silent",
          rows[0] == "orca · Sep 1–7" and len(rows) == 6
          and rows[1].endswith(" igk <b> x") and rows[2].endswith(" sammy")
          and rows[3] == "🟩⬜🟩🟩⬜🟩🟩 Ameya · as of Tue", crew)
    check("share: crew totals line",
          rows[4] == "21,430 reviews · 41h 12m together")
    check("share: nobody studied -> None",
          share.crew_week("orca", labels, [("a", [False] * 7, "")], 0, 0) is None)
    check("share: month-crossing range",
          share.date_range(["2026-08-30", "2026-09-05"]) == "Aug 30 – Sep 5")
    js = board.profile_overlay_js({"name": "Sammy", "you": True, "cells": None})
    check("share: own card offers today and week",
          "duecrew:sharetoday" in js and "duecrew:shareweek" in js)
    foot_week = board.render({"entries": [], "labels": labels[::-1], "tomorrow": "",
                              "pending": []}, {"period": "week"}, 0)
    check("share: the footer's Share menu offers the crew week (3.7.1, H3)",
          "crewmenu" not in foot_week and "sharemenu" in foot_week
          and ("Our week", "sharecrewweek") in board.share_menu_items(False))


def _luminance(hex_color):
    def chan(c):
        c = int(c, 16) / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (chan(hex_color[i:i + 2]) for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b):
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def test_accents():
    """Every accent clears WCAG AA both as text on its card and as the pill
    fill behind its ink; the theme CSS and overlays follow the choice."""
    worst = []
    for name, themes in board.ACCENTS.items():
        for theme, (accent, ink, you) in themes.items():
            bg = board.LIGHT["bg"] if theme == "light" else board.DARK["bg"]
            worst.append((name, theme, "text", round(_contrast(accent, bg), 2)))
            worst.append((name, theme, "pill", round(_contrast(ink, accent), 2)))
            worst.append((name, theme, "you-row-vs-card", round(_contrast(you, bg), 2)))
    fails = [w for w in worst if w[2] in ("text", "pill") and w[3] < 4.5]
    check("accents: all six pass AA for text and pill ink (light and dark)",
          not fails, str(fails))
    subtle = [w for w in worst if w[2] == "you-row-vs-card" and not (1.03 <= w[3] <= 1.6)]
    check("accents: your-row fills stay subtle against the card", not subtle, str(subtle))
    css = board._theme_css({"accent": "blue"})
    check("accents: theme CSS carries the chosen accent in both palettes",
          "#1e5fb4" in css and "#7fb2f0" in css and "#2e7d32" not in css)
    check("accents: unknown accent falls back to green",
          "#2e7d32" in board._theme_css({"accent": "plaid"}))
    js = board.profile_overlay_js({"name": "Dre", "you": False, "cells": None})
    check("accents: overlays take the board's tokens (accent, ink, card), not hard-coded colors",
          "'--dc-' + name" in js and "tok('accent'" in js and "tok('accent-ink'" in js
          and "tok('bg'" in js and "#23271f" not in js and "duecrew:cheerpick" in js)

def _render(data, labels, tomorrow, period):
    return board.render({"entries": data["entries"], "labels": labels,
                         "tomorrow": tomorrow, "pending": [], "decks": {},
                         "my_friends": []}, {"period": period}, 0)


def test_cheer_notes():
    """v2.2: a cheer may carry a note of at most 80 characters, one line."""
    store = world({"sam": "Sammy", "dre": "Dre"}, {"sam": ["dre"], "dre": ["sam"]})
    dre = new_client(store, "dre", "Dre")
    fire = "\U0001F525"
    ok = dre.send_cheer("sam", fire, "you're on fire  this\nweek")
    check("cheer note: stored as one line", ok is True
          and store.cheers[("sam", "dre")]["note"] == "you're on fire this week", str(store.cheers))
    long = dre.send_cheer("sam", fire, "x" * 200)
    check("cheer note: client trims to 80 before sending", long is True
          and len(store.cheers[("sam", "dre")]["note"]) == 80)
    bare = dre.send_cheer("sam", "\U0001F389")
    check("cheer note: no note, no field", bare is True and not store.cheers[("sam", "dre")]["note"])
    dre.send_cheer("sam", "\U0001F4AA", "big day")
    sam = new_client(store, "sam", "Sammy")
    data, _labels, _t = fetch_as(store, sam, make_user_col([TODAY]))
    ch = (data["cheers"] or [{}])[0]
    check("cheer note: arrives with the cheer, name from the profile",
          ch.get("note") == "big day" and ch.get("name") == "Dre"
          and ch.get("emoji") == "\U0001F4AA", str(data["cheers"]))
    check("cheer: delivered once", fetch_as(store, sam, make_user_col([TODAY]))[0]["cheers"] == [])
    js = board.flurry_js([fire], "Dre sent cheers", back=("dre", fire),
                         notes=["you're on fire <b>now</b>"])
    check("cheer note: flurry shows the note as text, longer linger",
          "you're on fire <b>now<\\/b>" in js and "'\u201c' + notes[n]" in js  # 3.9.7: no </ in its script
          and "notes.length ? 2500" in js)


def test_status_bubble():
    """v2.2: a one-line status rides today in my week (crew-only, like the
    numbers), shows as a bubble under the name on Today only, and clears
    when emptied."""
    store = world({"sam": "Sammy", "dre": "Dre"}, {"sam": ["dre"], "dre": ["sam"]})
    col = make_user_col([TODAY])
    files = tempfile.mkdtemp()
    dre = new_client(store, "dre", "Dre")
    labels = sync_once(store, dre, col, files,
                       {"status": "coffee, then <b>400</b> cards\nnow"}, TODAY)
    days = json.loads(store.weeks["dre"][0])["days"]
    check("status: uploaded as one line, today only",
          days[labels[0]].get("status") == "coffee, then <b>400</b> cards now"
          and not any("status" in d for lb, d in days.items() if lb != labels[0]), str(days))
    sam = new_client(store, "sam", "Sammy")
    data, labels, tomorrow = fetch_as(store, sam, col)
    entry = next(e for e in data["entries"] if e["user_id"] == "dre")
    check("status: a crewmate receives it",
          entry["days"][labels[0]].get("status") == "coffee, then <b>400</b> cards now")
    today_html = _render(data, labels, tomorrow, "today")
    check("status: bubble under the name on Today, escaped",
          'class="dc-st"' in today_html and "&lt;b&gt;400&lt;/b&gt;" in today_html
          and "<b>400</b>" not in today_html)
    check("status: nothing on Week", 'class="dc-st"' not in _render(data, labels, tomorrow, "week"))
    sync_once(store, dre, col, files, {"status": ""}, TODAY)
    check("status: emptied -> removed server-side",
          "status" not in json.loads(store.weeks["dre"][0])["days"][labels[0]])
    js = board.profile_overlay_js({"name": "Sammy", "you": True, "cells": None})
    check("status: own card offers to set one", "duecrew:status" in js and "Set a status" in js)
    js = board.profile_overlay_js({"name": "Dre", "you": False, "cells": None,
                                   "status": "hi <i>there</i>"})
    check("status: friend's card shows it escaped, no edit link",
          "hi &lt;i&gt;there&lt;/i&gt;" in js and "duecrew:status" not in js)
    junk = shapes._clean_day({"status": 5, "away": "yes", "awayTo": "soon"})
    good = shapes._clean_day({"status": "  hi\n there ", "away": True, "awayTo": "2026-09-04"})
    check("status/away: junk from the server is dropped",
          "status" not in junk and "away" not in junk
          and good == {"status": "hi there", "away": True, "awayTo": "2026-09-04"}, str((junk, good)))


def test_away_flag():
    """v2.2: away dates ride my week as a range (2.9), friend-gated like the
    numbers, so the crew sees the plane while I'm not syncing; readers flag
    each day inside it. Shrinking or clearing is one sync. Week shares show
    planes and still count only studied days."""
    from due_crew import share, shares
    store = world({"sam": "Sammy", "dre": "Dre"}, {"sam": ["dre"], "dre": ["sam"]})
    col = make_user_col([TODAY, TODAY - datetime.timedelta(days=2)])
    files = tempfile.mkdtemp()
    dre = new_client(store, "dre", "Dre")
    sam = new_client(store, "sam", "Sammy")
    d = lambda n: (TODAY + datetime.timedelta(days=n)).isoformat()
    sync_once(store, dre, col, files, {"away_from": d(-1), "away_to": d(3)}, TODAY)
    week = json.loads(store.weeks["dre"][0])
    check("away: the spell rides the week as a range",
          week.get("awayFrom") == d(-1) and week.get("awayTo") == d(3), str(week))
    data, labels, tomorrow = fetch_as(store, sam, col)
    days = next(e for e in data["entries"] if e["user_id"] == "dre")["days"]
    check("away: today reads away, with the end date and the numbers",
          days[d(0)].get("away") is True and days[d(0)].get("awayTo") == d(3) and "reviews" in days[d(0)])
    check("away: tomorrow reads away before they get there", (days.get(d(1)) or {}).get("away") is True)
    check("away: yesterday (unstudied) flagged, no numbers invented",
          days[d(-1)].get("away") is True and "reviews" not in days[d(-1)])
    check("away: a studied day outside the spell is untouched",
          "away" not in days[d(-2)] and "reviews" in days[d(-2)])
    sync_once(store, dre, col, files, {"away_from": d(-1), "away_to": d(1)}, TODAY)
    check("away: shrinking the spell is one sync", json.loads(store.weeks["dre"][0]).get("awayTo") == d(1))
    sync_once(store, dre, col, files, {}, TODAY)
    days = next(e for e in fetch_as(store, sam, col)[0]["entries"] if e["user_id"] == "dre")["days"]
    check("away: clearing unflags everything (numbers stay)",
          "away" not in days[d(0)] and "reviews" in days[d(0)] and not days.get(d(-1)))
    sync_once(store, dre, col, files, {"away_from": d(0), "away_to": d(0)}, TODAY)
    data, labels, tomorrow = fetch_as(store, sam, col)
    today_html = _render(data, labels, tomorrow, "today")
    check("away: Today row says when they're back",
          '<span class="chip">away · back tomorrow</span>' in today_html, today_html[-600:])
    doc3 = {"away": True, "awayTo": d(3)}
    check("away: badge names the return day",
          board._away_text(doc3, d(0)) == f"back {TODAY + datetime.timedelta(days=4):%b} {(TODAY + datetime.timedelta(days=4)).day}"
          and board._away_text({"away": True}, d(0)) == "away")
    check("away: day flags are three-state",
          shares._day_flag({"studied": True, "away": True}) is True
          and shares._day_flag({"away": True}) == "away"
          and shares._day_flag({}) is False and shares._day_flag(None) is False)
    week = [(datetime.date(2026, 9, 1) + datetime.timedelta(days=i)).isoformat() for i in range(7)]
    mine = share.my_week(week, [True, True, "away", "away", True, False, True], 900, 600000, 3)
    check("share: my week shows planes and counts studied days only",
          mine.split("\n")[1] == "🟩🟩✈️✈️🟩⬜🟩 4 of 7 days", mine)
    crew = share.crew_week("orca", week, [
        ("Ameya", ["away"] * 7, ""), ("igk", [True, "away", "away", True, True, True, True], "")],
        100, 60000)
    check("share: away-only week gets no row; planes in rows",
          crew is not None and crew.count("\n") == 3 and "🟩✈️✈️🟩🟩🟩🟩 igk" in crew, str(crew))


def _squad_fixture():
    """Sam founds orca; Dre, Eve, and Zed exist and aren't members yet."""
    store = world({"sam": "Sammy", "dre": "Dre", "eve": "Eve", "zed": "Zed"})
    sam = new_client(store, "sam", "Sammy")
    squad = sam.create_squad("  orca  <b> ")
    return store, sam, squad


def _denied(fn):
    try:
        fn()
        return False
    except shapes.TransportError:
        return True


def _row_sync(cl, row, sids):
    """A squad row the way a sync sends it: (ok, gone)."""
    return cl.push([TODAY.isoformat()], {}, squad_row=row, squads=sids)


def test_squads():
    """The door: create, peek, join while open, lock, remove, leave. The
    board: members read every row (with retention), nobody else does."""
    store, sam, squad = _squad_fixture()
    sid = squad["id"]
    check("squad: create makes the squad and the founder's row",
          bool(squad) and squad["name"] == "orca <b>" and sid in store.squads
          and (sid, "sam") in store.members, str(squad))
    check("squad: code is 8 safe chars; any spelling of it derives the id",
          len(squad["code"]) == 8
          and all(ch in shapes.SQUAD_ALPHABET for ch in squad["code"])
          and shapes.squad_id(squad["code"].lower() + "--") == sid)
    dre = new_client(store, "dre", "Dre")
    info, status = dre.peek_squad(squad["code"])
    check("squad: peek shows name, founder, open",
          bool(info) and info["name"] == "orca <b>" and info["founder"] == "sam"
          and info["open"], str((info, status)))
    check("squad: unknown code is a 404, not an error", dre.peek_squad("ZZZZZZZZ") == (None, 404))
    check("squad: join while open", dre.join_squad(sid, squad["code"]) == 200)
    eve = new_client(store, "eve", "Eve")
    check("squad: non-member cannot read the board", _denied(lambda: eve.fetch_squad(sid)))
    day = TODAY.isoformat()
    row = {"name": "Dre", "day": day, "reviews": 812, "studyTimeMs": 7440000,
           "accuracy": 91.25, "streak": 41}
    ok, gone = _row_sync(dre, row, [sid])
    n = store.wrote.get("members", 0)
    _row_sync(dre, row, [sid])
    check("squad: a row writes once; the same row again writes nothing",
          ok and gone == [] and n == 1 and store.wrote.get("members", 0) == 1)
    data = sam.fetch_squad(sid)
    dre_row = next((r for r in data["rows"] if r["user_id"] == "dre"), None)
    check("squad: members read every row, retention included",
          sorted(r["name"] for r in data["rows"]) == ["Dre", "Sammy"]
          and dre_row and dre_row["retention"] == 91.25 and dre_row["day"] == day
          and data["open"] and data["founder"] == "sam", str(data))
    check("squad: founder locks", sam.set_squad_open(sid, False))
    zed = new_client(store, "zed", "Zed")
    check("squad: join refused while locked", zed.join_squad(sid, squad["code"]) == 403)
    check("squad: existing member still writes while locked",
          _row_sync(dre, dict(row, reviews=900), [sid]) == (True, []))
    check("squad: non-founder cannot lock or remove",
          not dre.set_squad_open(sid, True) and not dre.remove_member(sid, "sam"))
    check("squad: founder removes a member", sam.remove_member(sid, "dre") and (sid, "dre") not in store.members)
    check("squad: a removed member's next row reports the squad gone, and creates nothing",
          _row_sync(dre, dict(row, reviews=1), [sid]) == (True, [sid])
          and (sid, "dre") not in store.members and _denied(lambda: dre.fetch_squad(sid)))
    check("squad: leave deletes my row", sam.leave_squad(sid) and (sid, "sam") not in store.members)


def test_knocks_squad():
    """Knocks need a squad both people are in; names come from profiles."""
    store, sam, squad = _squad_fixture()
    sid = squad["id"]
    dre = new_client(store, "dre", "Dre")
    dre.join_squad(sid, squad["code"])
    ok = dre.send_knock("sam", sid)
    check("knock: needs a squad both are in", not dre.send_knock("eve", sid))
    eve = new_client(store, "eve", "Eve")
    check("knock: squadmates can knock, outsiders cannot", ok and not eve.send_knock("sam", sid))
    knocks = sam.list_knocks()
    check("knock: names from profiles (no spoofing), squad id carried",
          knocks == [("dre", "Dre", sid)], str(knocks))
    sam.delete_knock("dre")
    check("knock: delete clears it", sam.list_knocks() == [])


def test_squads_ceiling_v395():
    """3.9.5 (the audit's A2): 20 squads a person, as the add-on keeps
    (account.MAX_SQUADS); the 21st join and a 21st squad are refused, said
    so, and leaving one opens the door again."""
    from due_crew.account import MAX_SQUADS
    store = world({"sam": "Sammy", "dre": "Dre", "kai": "Kai", "eve": "Eve"})
    sam, dre, kai, eve = (new_client(store, u) for u in ("sam", "dre", "kai", "eve"))
    made = [(sam if i < 11 else kai).create_squad(f"s{i}") for i in range(21)]
    joins = [dre.join_squad(q["id"], q["code"]) for q in made]
    check("ceiling: the server's is the add-on's", store.SQUADS_MAX == MAX_SQUADS == 20)
    check("ceiling: 20 joins go in, the 21st is refused as too many", joins[:20] == [200] * 20 and joins[20] == 409, joins)
    check("ceiling: so is a squad of my own, said apart from a failure", dre.create_squad("mine") == {"error": "too_many_squads"})
    dre.leave_squad(made[0]["id"])
    check("ceiling: leave one and the door opens", dre.join_squad(made[20]["id"], made[20]["code"]) == 200)
    tries = [eve.join_squad(made[1]["id"], "AAAAAAAA") for _ in range(31)]
    check("join tries (the second review): 30 an hour, right code or not, then a 429 (tools/dialogs.py draws what it says)",
          store.JOINS_PER_HOUR == 30 and tries[:30] == [403] * 30 and tries[30] == 429
          and eve.join_squad(made[1]["id"], made[1]["code"]) == 429, tries[-2:])


def test_squad_view_html():
    rows = [
        {"user_id": "u1", "name": "StepQueen <s>", "day": "2026-09-01", "reviews": 1412,
         "time_ms": 10920000, "retention": 92.1, "streak": 88},
        {"user_id": "sam", "name": "Sammy", "day": "2026-09-01", "reviews": 512,
         "time_ms": 4320000, "retention": None, "streak": 12, "you": True},
        {"user_id": "u2", "name": "Maya", "day": "2026-09-01", "reviews": 488,
         "time_ms": 3900000, "retention": 89.0, "streak": 31, "pending": True},
        {"user_id": "u3", "name": "Marcus", "day": "2026-08-31", "reviews": 220,
         "time_ms": 1860000, "retention": 87.4, "streak": 0},
        {"user_id": "u4", "name": "Priya", "day": "2026-09-01", "reviews": 301,
         "time_ms": 2400000, "retention": 94.2, "streak": 2, "knocked_me": True},
    ]
    view = {"state": "ok", "squads": [{"id": "abc", "name": "orca"},
                                      {"id": "def", "name": "MS2 <x>"}],
            "current": "abc", "name": "orca", "open": False, "founder_me": True,
            "rows": rows, "day": "2026-09-01", "yesterday": "2026-08-31",
            "people": 5, "studying": 4, "reviews": 2713}
    html = board._squads_html(view, {})
    check("squad view: plain ranks, no medals, no cheers",
          "#1" in html and "&#129351;" not in html and "dc-cheer" not in html)
    check("squad view: names escaped, card command wired, notes",
          "StepQueen &lt;s&gt;" in html and "ecard:u1" in html
          and "&middot; waiting" in html and "added you" in html and "&middot; crew" not in html)
    check("squad view: retention column and headline",
          "92.1%" in html and "5 in orca &middot; locked &middot; 4 studying today "
          "&middot; 2,713 reviews together" in html, html)
    check("squad view: yesterday's row is dim, unranked, and last",
          html.index("Marcus") > html.index("Priya") and "&middot; yesterday" in html
          and re.search(r'<td class="rk"></td><td class="nm">(?:(?!</tr>).)*ecard:u3', html) is not None)
    check("squad view: founder controls and the shared footer",
          "squadlock" in html and ">Open<" in html and "squadinvite" in html
          and "squadleave" in html)
    by_streak = board._squads_html(view, {"sort": "streak"})
    check("squad view: headers are the crew's sort links; sorting reorders ranks",
          ('onclick="pycmd(\'duecrew:sort:retention|' + KK + '\')') in html
          and by_streak.index("StepQueen") < by_streak.index("Maya")
          and by_streak.index("Maya") < by_streak.index("Sammy")
          and '<span class="hi">&#128293;</span><span class="hl">Streak</span> &#9662;' in by_streak, by_streak)
    check("squad view: switcher marks the current squad and escapes names",
          'class="on"' in html and "MS2 &lt;x&gt;" in html and "squadadd" not in html.split("</div>")[0])  # (3.9.10: under the squad, _squad_add)
    none = board._squads_html({"state": "none", "squads": [], "current": ""}, {})
    sq_page = board.render({"entries": [], "labels": ["2026-09-01"], "tomorrow": "", "pending": []}, {"period": "squads"}, 0,
                           squad_view={"state": "none", "squads": [], "current": ""})
    check("squad view: no squads yet; + Create / join a squad is on this tab alone, under the squad, never in the foot (3.9.10)",
          "No squads yet" in none and "<table>" not in none and '<div class="dc-add">' in none
          and ("duecrew:squadadd|" + board.BOARD_KEY + "'); return false;\">+ Create / join a squad</a>") in sq_page.split('class="dc-foot"')[0]
          and "squadadd" not in sq_page.split('class="dc-foot"')[1]
          and "Create / join a squad" not in board.render({"entries": [], "labels": ["2026-09-01"], "tomorrow": "", "pending": []},
                                                          {"period": "today"}, 0))
    gone = board._squads_html({"state": "gone", "squads": [{"id": "abc", "name": "orca"}],
                               "current": "abc", "name": "orca"}, {})
    check("squad view: removed -> Remove link", "squaddrop:abc" in gone)
    page = board.render({"entries": [], "labels": ["2026-09-01"], "tomorrow": "",
                         "pending": []}, {"period": "today"}, 0,
                        knocks=[{"uid": "u4", "name": "Priya <p>", "squad": "orca"}])
    check("knock banner: escaped name, Add back and Not now wired",
          "Priya &lt;p&gt;" in page and "added you from orca" in page
          and "addback:u4" in page and "knockmute:u4" in page)
    js = board.stranger_card_js({
        "uid": "u4", "name": "Priya <p>", "reviews": 301, "time_ms": 2400000,
        "retention": 94.2, "streak": 2, "rank": 4, "squad": "orca", "today": True,
        "pending": False, "knocked_me": True, "founder_me": True})
    check("squad card: retention, rank, Add back, founder Remove",
          "94.2% retention" in js and "#4 in orca today" in js
          and "duecrew:addback:u4" in js and "duecrew:squadkick:u4" in js)
    plain = board.stranger_card_js({
        "uid": "u1", "name": "Q", "reviews": 1, "time_ms": 1, "retention": None,
        "streak": 1, "rank": None, "squad": "orca", "today": False,
        "pending": False, "knocked_me": False, "founder_me": False})
    check("squad card: plain member gets Add, no Remove, no retention line",
          "duecrew:knock:u1" in plain and "squadkick" not in plain
          and "retention" not in plain)


def test_deletion_sweep():
    """Delete account: everything of mine goes in one request, and this
    computer is signed out."""
    store, sam, squad = _squad_fixture()
    sid = squad["id"]
    dre = new_client(store, "dre", "Dre")
    dre.join_squad(sid, squad["code"])
    dre.send_knock("sam", sid)
    sam.push([TODAY.isoformat()], {}, heatmap={TODAY.isoformat(): 3})
    n = len(store.log)
    sam.delete_account()
    check("deletion: one request", store.log[n:] == [("DELETE", "/account", 200)], str(store.log[n:]))
    check("deletion: membership, knocks, week and heatmap are swept; the squad passes on",
          (sid, "sam") not in store.members and not any("sam" in k for k in store.knocks)
          and "sam" not in store.weeks and "sam" not in store.heat
          and store.squads[sid]["founder"] == "dre")
    check("deletion: signed out here", not sam.signed_in and sam.session == {})


def test_hardening_v24():
    """The audit fixes that have a pure edge: command whitelist, error
    status, and per-sender cheer bookkeeping."""
    from due_crew import social
    check("pycmd: ids and keys pass, quote-breakers are dropped",
          board._pycmd("profile:abc_1-2") == ("pycmd('duecrew:profile:abc_1-2|" + KK + "'); return false;")
          and "'" not in board._pycmd("x:a')alert(1)//").replace("pycmd('duecrew:", "", 1)[:-len("'); return false;")])
    err = shapes.TransportError("query failed: 403", 403)
    check("transport error carries its status", err.status == 403 and str(err) == "query failed: 403")
    a1 = {"from": "a", "at": "2026-09-10T10:00:00Z", "emoji": "🔥", "name": "A", "note": ""}
    b_far = {"from": "b", "at": "9999-01-01T00:00:00Z", "emoji": "🎉", "name": "B", "note": ""}
    fresh, seen = social._fresh_cheers([a1, b_far], None, "")
    check("cheers: first run plays everything and marks per sender",
          [c["from"] for c in fresh] == ["a", "b"] and seen == {"a": a1["at"], "b": b_far["at"]})
    a2 = dict(a1, at="2026-09-10T11:00:00Z")
    fresh2, seen2 = social._fresh_cheers([a2, b_far], seen, "")
    check("cheers: a forged far-future stamp from B cannot hide A's next cheer",
          [c["from"] for c in fresh2] == ["a"] and seen2["a"] == a2["at"])
    fresh3, seen3 = social._fresh_cheers([a2], seen2, "")
    check("cheers: nothing new plays nothing; departed senders are forgotten",
          fresh3 == [] and seen3 == {"a": a2["at"]})
    fresh4, _ = social._fresh_cheers([a1, a2], None, a1["at"])
    check("cheers: migration folds the old global mark in (older stays quiet)",
          [c["at"] for c in fresh4] == [a2["at"]])
    store = world({"sam": "Sammy"})
    cl = new_client(store, "sam", "Sammy")
    check("server: users can't be listed", cl._call("GET", "/users")[0] == 404)
    check("server: a 61-char display name is refused, 60 is fine",
          not cl.set_display_name("x" * 61) and cl.set_display_name("x" * 60)
          and cl.display_name == "x" * 60)
    check("server: a profile is a name and an emoji, nothing more",
          new_client(store, "sam").profile("sam") == {"uid": "sam", "name": "x" * 60, "emoji": ""})


def test_v25_edges_emoji_week():
    """2.5: friendship is two edges, one per person; crew emoji; the squad
    week count; block list; founder handoff."""
    from due_crew import share, shares
    from due_crew.stats import week_days
    ce = shapes.clean_emoji
    check("emoji: one glyph passes, with skin tone and joiners; text does not",
          ce("🦊") == "🦊" and ce(" 🐢 ") == "🐢" and ce("👍🏽") == "👍🏽"
          and ce("👩‍💻") == "👩‍💻" and ce("🇺🇸") == "🇺🇸" and ce("🦊🐢") == "🦊"
          and ce("A") == "" and ce("<b>") == "" and ce("") == "" and ce(None) == "")
    store = world({"sam": "Sammy", "dre": "Dre", "eve": "Eve"}, {"eve": ["sam"]})
    sam = new_client(store, "sam", "Sammy")
    sam.push([TODAY.isoformat()], {"emoji": "🦊"})
    check("emoji: a sync carries it", store.users["sam"]["emoji"] == "🦊")
    info = sam.add_back("eve")
    check("edges: adding someone who added me makes it mutual at once", info and info["mutual"] is True)
    check("edges: a stranger can't be added by uid alone (D5: it would hand over the name)",
          sam.add_back("dre") is None and ("sam", "dre") not in store.friends)
    store.knocks[("sam", "dre")] = {"squad": "", "at": "2026-01-01T00:00:00Z"}  # dre added my code: a knock
    info = sam.add_back("dre")
    check("edges: adding someone who hasn't is pending", info and info["mutual"] is False)
    _code, people, _k = sam.friends_view()
    check("edges: the Friends dialog reads both, with mutual marked",
          [(u, m) for u, _n, _e, m in people] == [("dre", False), ("eve", True)], str(people))
    board_data, labels, _t = fetch_as(store, sam, make_user_col([TODAY]))
    check("edges: the board shows the crew, and the pending by name only",
          [e["user_id"] for e in board_data["entries"]] == ["sam", "eve"] and board_data["pending"] == ["Dre"])
    eve = new_client(store, "eve", "Eve")
    check("edges: someone else sees none of my edges",
          set(eve.profile("sam")) == {"uid", "name", "emoji"}
          and [e["user_id"] for e in fetch_as(store, eve, make_user_col([TODAY]))[0]["entries"]] == ["eve", "sam"])
    sam.remove_friend("eve")
    check("edges: removing ends their reads, the same request",
          [e["user_id"] for e in fetch_as(store, eve, make_user_col([TODAY]))[0]["entries"]] == ["eve"])

    # ---- squads: week + emoji on rows, block, handoff ----
    squad = sam.create_squad("orca")
    sid = squad["id"]
    dre = new_client(store, "dre", "Dre")
    dre.join_squad(sid, squad["code"])
    row = {"name": "Dre", "day": TODAY.isoformat(), "reviews": 10, "studyTimeMs": 1000, "streak": 1,
           "week": 5, "emoji": "🐢"}
    check("squad row: week and emoji ride along", _row_sync(dre, row, [sid]) == (True, []))
    check("squad row: week outside 0..7 is refused", _row_sync(dre, dict(row, week=9), [sid])[0] is False)
    check("week_days counts the last seven days from the revlog",
          week_days(StatsQueries(make_user_col([TODAY, TODAY - datetime.timedelta(days=1),
                                                TODAY - datetime.timedelta(days=9)]))) == 2)
    data = sam.fetch_squad(sid)
    drow = next(r for r in data["rows"] if r["user_id"] == "dre")
    check("squad fetch: week, emoji, and the ban list come back",
          drow["week"] == 5 and drow["emoji"] == "🐢" and data["banned"] == [])
    check("block: non-founder cannot", not dre.block_member(sid, "sam"))
    check("block: founder blocks; the member is gone",
          sam.block_member(sid, "dre") and (sid, "dre") not in store.members)
    check("block: rejoining is refused even with the door open", dre.join_squad(sid, squad["code"]) == 403)
    eve.join_squad(sid, squad["code"])
    check("handoff: only to a member",
          not sam.set_founder(sid, "dre") and sam.set_founder(sid, "eve")
          and store.squads[sid]["founder"] == "eve")
    check("handoff: the old founder can no longer lock", not sam.set_squad_open(sid, False))

    # ---- rendering + shares ----
    labels = [(TODAY - datetime.timedelta(days=i)).isoformat() for i in range(7)]
    rows = [{"user_id": "u1", "name": "igk", "emoji": "🐢", "day": labels[0], "reviews": 1412,
             "time_ms": 10920000, "retention": 92.1, "streak": 88, "week": 7},
            {"user_id": "sam", "name": "Sammy", "emoji": "🦊", "day": labels[0], "reviews": 512,
             "time_ms": 4320000, "retention": 91.6, "streak": 17, "week": 6, "you": True},
            {"user_id": "u3", "name": "Priya", "emoji": "", "day": labels[0], "reviews": 301,
             "time_ms": 2400000, "retention": 94.2, "streak": 2, "week": None}]
    view = {"state": "ok", "squads": [{"id": "abc", "name": "orca"}], "current": "abc",
            "name": "orca", "open": True, "founder_me": True, "rows": rows, "day": labels[0],
            "yesterday": labels[1], "people": 3, "studying": 3, "reviews": 2225}
    html = board._squads_html(view, {"sort": "week"})
    plain = board._squads_html(view, {"sort": "week", "sev": False})
    check("squad board: a Pip in front of each name (3.8.21; the emoji with Pip off), a rolling 7-days column, sortable by it",
          "🐢" not in html and "🦊" not in html and html.count('class="dc-rsev"') == 3
          and "🐢 igk" in plain and "🦊 Sammy" in plain and "dc-rsev" not in plain
          and "&middot; 7/7 days</span>" in html and "&middot; 6/7 days</span>" in html
          and "7 days</span> &#9662;" not in html and html.count("<th>") == 4 and '<table class="dc-s-reviews">' in html
          and html.index("igk") < html.index("Sammy") < html.index("Priya"))
    page = board.render({"entries": [], "labels": labels, "tomorrow": "", "pending": []},
                        {"period": "squads"}, 0, squad_view=view)
    check("squad board: Share the squad's day is in the Share menu, not on the squad's line",
          "squadshare" not in html and "sharemenu" in page
          and ("The squad's day", "squadshare") in board.share_menu_items(False, True)
          and not any(k == "squadshare" for _l, k in board.share_menu_items(False, False)))
    crew = board.render({"entries": [{"user_id": "sam", "name": "Sammy", "emoji": "🦊", "you": True,
                                       "paused": False, "last_updated": "", "exam_date": "",
                                       "days": {labels[0]: {"studied": True, "reviews": 3}}, "decks": []}],
                         "labels": labels, "tomorrow": "", "pending": []}, {"sort": "week", "sev": False}, 0)
    check("crew board: emoji by the name (Pip off: 3.8.2 puts Pip in its place); the squads-only sort falls back to reviews",
          "🦊 Sammy" in crew and '<span class="hl">Reviews</span> &#9662;' in crew)
    js = board.profile_overlay_js({"name": "Sammy", "you": True, "cells": None, "emoji": "🦊"})
    esc = lambda t: json.dumps(t)[1:-1]  # JS strings carry non-ASCII escaped
    check("own card: emoji by the name and a link to change it",
          esc("🦊 Sammy") in js and "duecrew:emoji" in js and "Change emoji" in js)
    card = board.stranger_card_js({"uid": "u1", "name": "igk", "emoji": "🐢", "reviews": 1,
                                   "time_ms": 1, "retention": None, "streak": 1, "rank": 1,
                                   "squad": "orca", "today": True, "pending": False,
                                   "knocked_me": False, "founder_me": True})
    check("squadmate card: founder sees Remove, Block, Make founder",
          "duecrew:squadkick:u1" in card and "duecrew:squadblock:u1" in card
          and "duecrew:squadfounder:u1" in card and esc("🐢 igk") in card)
    text = share.squad_today("orca", labels[0], [("igk", "🐢", 1412), ("Sammy", "🦊", 512),
                                                 ("Priya", "", 301), ("Zed", "", 5)], 4, 2230)
    check("squad share: headline, together line, top three with emoji",
          text.split("\n")[1] == "4 studying · 2,230 reviews together"
          and text.split("\n")[2] == "🟩 🐢 igk 1,412 · 🦊 Sammy 512 · Priya 301", text)
    week = list(reversed(labels))
    crew_txt = share.crew_week("orca", week, [("Sammy", [True] * 7, "", "🦊"), ("igk", [True] * 7, "")], 1, 1)
    check("crew week share: emoji rows, plain rows unchanged",
          "🟩🟩🟩🟩🟩🟩🟩 🦊 Sammy" in crew_txt and "🟩🟩🟩🟩🟩🟩🟩 igk" in crew_txt)
    check("share module still has the four builders", callable(shares._crew_week_text))


def test_personal_reviews():
    """Month and year reviews: one revlog pass, exact numbers, honest
    labels, and the board banners that carry them."""
    from due_crew import share, shares
    from due_crew.stats import period_review
    today = datetime.date(2026, 9, 13)
    studied = [datetime.date(2026, 9, 1), datetime.date(2026, 9, 2), datetime.date(2026, 9, 3),
               datetime.date(2026, 9, 10), datetime.date(2026, 8, 30), datetime.date(2026, 3, 3)]
    col = make_user_col(studied, today=today)   # 3 answers a day, one Again each
    q = StatsQueries(col)
    sept = period_review(q, datetime.date(2026, 9, 1), datetime.date(2026, 9, 30))
    check("month review: clamps to today, counts days and reviews, finds the best run",
          sept["span"] == 13 and sept["days"] == 4 and sept["reviews"] == 12
          and sept["longest_run"] == 3 and sept["best_day"][1] == 3
          and round(sept["retention"], 1) == 66.7, str(sept))
    year = period_review(q, datetime.date(2026, 1, 1), datetime.date(2026, 12, 31))
    check("year review: best month, six studied days, span to today",
          year["best_month"] == ("2026-09", 12) and year["days"] == 6 and year["span"] == 256, str(year))
    check("empty period is None, zero-review period shares nothing",
          period_review(q, datetime.date(2027, 1, 1), datetime.date(2027, 1, 31)) is None
          and share.my_month(period_review(q, datetime.date(2026, 5, 1), datetime.date(2026, 5, 31)), "May") is None)
    m = share.my_month(sept, "September", so_far=True)
    check("month share text", m.split("\n")[:3] == [
        "My September so far", "12 reviews · 1m · 4 of 13 days",
        "best day Sep 1 (3) · 🎯 66.7%"], m)
    y = share.my_year(year, 2026, so_far=True)
    check("year share text", y.split("\n")[:4] == [
        "My 2026 so far", "18 reviews · 1m · 6 of 256 days",
        "best month September (12) · best day Mar 3 (3)",
        "🔥 longest run 3 days · 🎯 66.7%"], y)
    first, end, name = shares._month_bounds(today, last=True)
    check("month bounds: last month is August 1–31",
          (first, end, name) == (datetime.date(2026, 8, 1), datetime.date(2026, 8, 31), "August"))
    first, end, name = shares._month_bounds(datetime.date(2026, 12, 5))
    check("month bounds: this month ends on the 31st across the year edge",
          (first, end, name) == (datetime.date(2026, 12, 1), datetime.date(2026, 12, 31), "December"))
    banners = {"month": {"key": "2026-08", "name": "August", "review": sept},
               "year": {"key": "2026", "review": year}}
    html = board.render({"entries": [], "labels": [today.isoformat()], "tomorrow": "", "pending": []},
                        {"period": "today"}, 0, reviews=banners)
    check("board: month and year banners with Copy and dismiss",
          "Your August:" in html and "Your 2026:" in html and "monthcopy" in html
          and "yeardismiss" in html and "&#128293; 3-day run" in html and "best day 3" in html)
    js = board.profile_overlay_js({"name": "Sammy", "you": True, "cells": None})
    check("own card offers month and year", "duecrew:sharemonth" in js and "duecrew:shareyear" in js)


def test_sync_reliability_v251():
    """A refused session is detected (and only a REFUSED one: offline is not
    signed out), the build number rides the profile, and staleness has a
    retry guard."""
    import due_crew
    store = world({"sam": "Sammy", "dre": "Dre"})
    cl = new_client(store, "sam", "Sammy")
    check("session: alive to begin with", cl.signed_in and not cl.session_dead)
    store.down = True
    check("session: offline is NOT signed out",
          _denied(lambda: cl.fetch_board([TODAY.isoformat()])) and not cl.session_dead)
    store.down = False
    store.fail_status = 503
    check("session: a 5xx is NOT signed out",
          _denied(lambda: cl.fetch_board([TODAY.isoformat()])) and not cl.session_dead)
    store.fail_status = None
    store.tokens.clear()  # signed out everywhere, or idle 180 days
    check("session: a refused token marks the session dead",
          _denied(lambda: cl.fetch_board([TODAY.isoformat()])) and cl.session_dead and cl.signed_in)
    check("session: a plain refusal isn't 'deleted for being quiet'", not cl.deleted_quiet)
    store.otp["sam@example.com"] = "123456"
    cl.verify_code("sam@example.com", "123456")
    check("session: signing in again clears it", not cl.session_dead and cl.signed_in)
    # Q4: an account deleted after 12 months quiet says so, once asked
    store.gone = {cl.user_id}
    store.tokens.clear()
    asked = len([r for r in store.log if r[1] == "/auth/gone"])
    _denied(lambda: cl.fetch_board([TODAY.isoformat()]))
    card = board.signed_out_card({}, expired=cl.session_dead, gone=cl.deleted_quiet)
    check("session: deleted for being quiet: the card says why, and how to start again",
          cl.deleted_quiet and "Welcome back" in card and "12 months without activity" in card and "duecrew:setup" in card
          and len([r for r in store.log if r[1] == "/auth/gone"]) == asked + 1)
    _denied(lambda: cl.fetch_board([TODAY.isoformat()]))
    check("session: asked once, not at every refusal", len([r for r in store.log if r[1] == "/auth/gone"]) == asked + 1)
    store.gone = set()
    store.otp["sam@example.com"] = "123456"
    cl.verify_code("sam@example.com", "123456")
    check("session: signing in again clears 'deleted'", not cl.deleted_quiet and not cl.session_dead)

    col = make_user_col([TODAY])
    cl.push([TODAY.isoformat()], {}, stats=gather_stats(col, tempfile.mkdtemp()), version="3.0.0",
            clock={"tz": -240, "rollover": 4})
    check("profile carries the client version and clock",
          store.users["sam"]["client_version"] == "3.0.0" and store.users["sam"]["tz"] == -240)

    squad = cl.create_squad("orca")
    sid = squad["id"]
    dre = new_client(store, "dre", "Dre")
    dre.join_squad(sid, squad["code"])
    bad = {"name": "Dre", "reviews": 1, "studyTimeMs": 1, "streak": 1, "week": 9, "day": TODAY.isoformat()}
    ok, gone = _row_sync(dre, bad, [sid])
    check("squad: a row the server refuses is NOT read as removal",
          ok is False and gone == [] and (sid, "dre") in store.members)
    cl.remove_member(sid, "dre")
    check("squad: once actually removed, the sync says gone", _row_sync(dre, dict(bad, week=3), [sid]) == (True, [sid]))

    ce, too_long = shapes.clean_emoji, shapes.emoji_too_long
    family = "\U0001F468\u200d\U0001F469\u200d\U0001F467\u200d\U0001F466"   # 11 UTF-16 units
    monster = "\U0001F468" + "\u200d\U0001F469" * 6                            # 20 units
    units = lambda t: len(t.encode("utf-16-le")) // 2
    check("emoji: the cap is the server's own unit (UTF-16), so a family emoji passes",
          ce(family) == family and units(family) == 11 and not too_long(family))
    check("emoji: past 16 units it is refused whole, never truncated or sent",
          units(monster) == 20 and ce(monster) == "" and too_long(monster)
          and not too_long("abc") and not too_long("🦊"))
    check("emoji: everything the client accepts fits the server's 16 units",
          all(ce(e) == e and units(e) <= 16
              for e in ("🦊", "🇺🇸", "👍🏽", "👩‍💻", "🧑🏽‍💻", "❤️‍🔥", family)))

    check("stale: an old board with no recent attempt refreshes",
          due_crew._is_stale(1000, 0, 0, 900))
    check("stale: a fresh board does not", not due_crew._is_stale(1000, 500, 0, 900))
    check("stale: an old board we JUST tried (offline) does not hammer",
          not due_crew._is_stale(1000, 0, 500, 900))

    card = board.signed_out_card({}, expired=True)
    check("board: an expired sign-in asks you back in, plainly",
          "Your sign-in expired." in card and "Sign in again" in card and "duecrew:setup" in card
          and "Join your crew" not in card)
    base = {"entries": [], "labels": [TODAY.isoformat()], "tomorrow": "", "pending": []}
    check("board: the footer admits a failed sync, and only then",
          "Couldn&rsquo;t sync" in board.render(base, {}, 0, sync_error=True)
          and "Couldn&rsquo;t sync" not in board.render(base, {}, 0))


def test_remove_sticks():
    """Found 2026-09-18: on an OPEN squad, Remove undid itself, because a
    row write could create membership. In 3.0 a row is an UPDATE on the
    server, and the join is the only way in."""
    store, sam, squad = _squad_fixture()
    sid = squad["id"]
    dre = new_client(store, "dre", "Dre")
    row = {"name": "Dre", "reviews": 5, "studyTimeMs": 1, "streak": 1, "day": TODAY.isoformat()}
    check("join: a row is not a join", _row_sync(dre, row, [sid]) == (True, [sid])
          and (sid, "dre") not in store.members)
    check("join: the real join works", dre.join_squad(sid, squad["code"]) == 200)
    check("row: a member's sync still lands", _row_sync(dre, row, [sid]) == (True, [])
          and store.members[(sid, "dre")]["reviews"] == 5)
    sam.remove_member(sid, "dre")            # the squad is OPEN — never locked
    check("remove sticks: the next sync reports gone and re-creates nothing",
          _row_sync(dre, dict(row, reviews=6), [sid]) == (True, [sid]) and (sid, "dre") not in store.members)
    check("remove sticks: the founder's board no longer lists them",
          sorted(r["name"] for r in sam.fetch_squad(sid)["rows"]) == ["Sammy"])
    check("a deliberate rejoin with the code still works — Block is what stops that",
          dre.join_squad(sid, squad["code"]) == 200)


def _deck_col():
    """Big Deck (1) with a Cardio subdeck (2), an unrelated deck (3), and one
    card sitting in a filtered deck (99) whose home is Cardio. By hand, for
    the Big Deck subtree: 6 cards, 4 seen, 2 mature, 5 unlocked."""
    conn = sqlite3.connect(":memory:")
    fakes.make_collection(conn)
    fakes.add_card(conn, 1, did=1, ctype=2, queue=2, ivl=30)     # seen, mature
    fakes.add_card(conn, 2, did=2, ctype=2, queue=2, ivl=5)      # seen, young
    fakes.add_card(conn, 3, did=2, ctype=0, queue=0)             # new, unlocked
    fakes.add_card(conn, 4, did=1, ctype=0, queue=-1)            # new, suspended: locked
    fakes.add_card(conn, 5, did=1, ctype=2, queue=-1, ivl=40)    # seen+mature, then suspended
    fakes.add_card(conn, 6, did=99, odid=2, ctype=2, queue=2, ivl=3)  # in a filtered deck
    fakes.add_card(conn, 7, did=3, ctype=2, queue=2, ivl=50)     # another deck entirely
    noon = lambda d: int(datetime.datetime.combine(d, datetime.time(12)).timestamp() * 1000)
    t = noon(TODAY)
    fakes.add_review(conn, t, ease=3, rtype=1, cid=1)
    fakes.add_review(conn, t + 1000, ease=1, rtype=1, cid=2)     # Again: graded, wrong
    fakes.add_review(conn, t + 2000, ease=3, rtype=1, cid=6)     # credited to its home deck
    fakes.add_review(conn, t + 3000, ease=3, rtype=3, cid=2)     # early review: an answer, not graded
    fakes.add_review(conn, t + 4000, ease=0, rtype=1, cid=1)     # a manual op, not an answer
    fakes.add_review(conn, t + 5000, ease=3, rtype=1, cid=7)     # the other deck
    fakes.add_review(conn, noon(TODAY - datetime.timedelta(days=3)), ease=3, rtype=1, cid=1)
    fakes.add_review(conn, noon(TODAY - datetime.timedelta(days=10)), ease=1, rtype=1, cid=1)  # too old
    col = fakes.FakeCol(conn, fakes.day_cutoff_for(TODAY))
    col.decks = fakes.FakeDecks({1: "Big Deck", 2: "Big Deck::Cardio", 3: "Other"})
    return col


def test_decks():
    """The Decks screen had no tests before 2.6. Its SQL runs here against a
    real (in-memory) database, so the JOIN and every CASE are exercised."""
    from due_crew.stats import decks as dk
    col = _deck_col()
    table = dk.all_deck_counts(col)
    check("decks: per-deck counts, filtered cards credited home, suspended-but-seen is unlocked",
          table[1] == [3, 2, 2, 2] and table[2] == [3, 2, 0, 3] and table[3] == [1, 1, 1, 1], str(table))
    check("decks: subtree roll-up", dk.subtree_counts(col, 1, table) == (6, 4, 2))
    act = dk.deck_activity(col)
    check("decks: activity credits home decks; manual ops and old reviews are out",
          act == {1: [1, 2, 2], 2: [3, 1, 2], 3: [1, 1, 1]}, str(act))
    check("decks: subtree extras (unlocked, today, correct, graded)",
          dk.subtree_extra(col, 1, table, act) == (5, 4, 3, 4))
    payload = dk.gather_shared_decks(col, {"shared_decks": [1]})
    d = payload[0]
    check("decks: the upload carries unlocked, today, retention, and its day",
          (d["name"], d["total"], d["seen"], d["mature"], d["open"], d["today"], d["ret"], d["day"])
          == ("Big Deck", 6, 4, 2, 5, 4, 75.0, TODAY.isoformat()), str(d))
    private = dk.gather_shared_decks(col, {"shared_decks": [1], "share_reviews": False,
                                           "share_retention": False})[0]
    check("decks: the privacy switches cover the new fields",
          "today" not in private and "ret" not in private and private["open"] == 5)
    clean = shapes._clean_decks
    check("decks: a friend's payload round-trips",
          clean(payload)[0] == dict(d, sig=d["sig"]))
    bad = dict(d, open=1, ret=140, mature=99)
    check("decks: nonsense from a friend is bounded, not trusted",
          clean([bad])[0]["open"] == 4 and "ret" not in clean([bad])[0] and clean([bad])[0]["mature"] == 4)
    check("decks: `today` without a valid day is dropped; an old client's payload still reads",
          "today" not in clean([dict(d, day="")])[0]
          and clean([{"name": "x", "sig": ["a"], "total": 10, "seen": 3, "mature": 1}])[0]
          == {"name": "x", "sig": ["a"], "total": 10, "seen": 3, "mature": 1})

    today, other = TODAY.isoformat(), (TODAY - datetime.timedelta(days=1)).isoformat()
    bar = board._bar("Ameya <a>", False, clean(payload)[0], delta=12, today_labels=(today,))
    check("bar: mature and seen from the left; the hatch starts where seen ends, never under it",
          'class="fo" style="left:67%;width:16%;"' in bar and 'class="fs" style="width:67%;"' in bar
          and 'class="fm" style="width:33%;"' in bar)
    done = board._bar("x", False, {"name": "d", "sig": [], "total": 10, "seen": 10, "mature": 4, "open": 10})
    check("bar: a fully seen deck has no hatch left to draw",
          'class="fo" style="left:100%;width:0%;"' in done)
    check("bar: hover has the exact numbers; the name is escaped",
          "4 seen · 2 mature · 5 unsuspended · 6 total · +12 this week · 75.0% retention, last 7 days" in bar
          and "<b>Ameya &lt;a&gt;</b>" in bar)
    check("bar: today and week chips, and retention beside the count",
          "+4 today &middot; +12 wk" in bar and "4 / 6 &middot; 75%" in bar)
    stale = board._bar("Ameya", False, clean(payload)[0], today_labels=(other,))
    check("bar: yesterday's 'today' is not shown as today", "today" not in stale.split("title=")[0]
          and "+4 today" not in stale)
    rows = bar + board._bar("igk", False, {"name": "d", "sig": [], "total": 10, "seen": 3, "mature": 1})
    check("bars: with one row showing +N today, the others keep a blank line, so rows are evenly spaced",
          board._even_bars(rows).count('class="dc-delta"') == 2 and "<!--dd-->" not in board._even_bars(rows)
          and 'class="dc-delta"' not in board._even_bars(board._bar("igk", False, {"name": "d", "sig": [], "total": 10, "seen": 3, "mature": 1})))
    old = board._bar("igk", False, {"name": "x", "sig": [], "total": 10, "seen": 3, "mature": 1})
    check("bar: an older client's deck renders without the unlocked fill",
          'class="fo"' not in old and "3 / 10" in old and "unlocked" not in old)
    # the Shared Decks dialog's "matches …" label. My own entry carries the
    # decks I already share, so through 2.5.1 a shared deck matched its owner.
    sig = [f"g{n}" for n in range(12)]
    crew = [{"user_id": "me", "name": "Sam", "you": True, "decks": [{"name": "A", "sig": sig}]},
            {"user_id": "f1", "name": "igk", "you": False, "decks": [{"name": "A", "sig": sig[:9]}]},
            {"user_id": "f2", "name": "Dre", "you": False, "decks": [{"name": "B", "sig": sig[:3]}]},
            {"user_id": "f3", "name": "Jo", "you": False}]
    check("deck matches: crewmates past the overlap bar, never yourself",
          dk.crew_matches(sig, crew) == ["igk"] and dk.crew_matches(sig, None) == []
          and dk.crew_matches([], crew) == [])

    # through 2.5.1 the legend said "light = seen, dark = mature", which is
    # backwards in dark mode, where the mature fill is the bright one
    legend = board._decks_html({"labels": [today], "entries": [
        {"user_id": "me", "name": "Sam", "you": True, "decks": clean(payload)}]})
    check("decks legend: a key drawn with the bars' own fills, which holds in both themes (3.7.1, I6)",
          '<i class="fm"></i>mature<i class="fs"></i>seen<i class="fo"></i>unsuspended' in legend
          and "light =" not in legend and "dark =" not in legend and "hover" not in legend)


def test_calendar_weeks_and_ledger():
    """2.6: "Week" is Monday-to-Sunday, and the numbers behind the "Last
    week" banner and the all-time milestones come from a per-day ledger.
    Before this, both were a rolling seven-day sum taken whenever Anki was
    first opened in a week: only "last week" if that was a Monday, and the
    all-time total double-counted or skipped days as the open-day moved."""
    D = datetime.date
    span = lambda end: [(end - datetime.timedelta(days=i)).isoformat() for i in range(7)]
    check("week labels: Wednesday sees Monday..Wednesday",
          board.week_labels(span(D(2026, 9, 16))) == ["2026-09-16", "2026-09-15", "2026-09-14"])
    check("week labels: Monday is a week of one, Sunday a week of seven",
          board.week_labels(span(D(2026, 9, 14))) == ["2026-09-14"]
          and len(board.week_labels(span(D(2026, 9, 20)))) == 7)

    def crew(labels):
        """Sam and Dre, every day: 100 each through Sep 13, then Dre does 150."""
        def day(lb, uid):
            n = 150 if (uid == "dre" and lb >= "2026-09-14") else 100
            return {"studied": True, "reviews": n, "studyTimeMs": 60000}
        return [{"user_id": u, "name": nm, "you": u == "sam", "paused": False,
                 "last_updated": "", "exam_date": "", "decks": [],
                 "days": {lb: day(lb, u) for lb in labels}}
                for u, nm in (("sam", "Sammy"), ("dre", "Dre"))]

    wed = span(D(2026, 9, 16))
    fresh, _dormant = board.build_rows(crew(wed), wed, "", "week", {})
    check("board: the Week view sums this week only (3 days), not the last seven",
          {r["name"]: r["reviews"] for r in fresh} == {"Sammy": 300, "Dre": 450})

    wrap = _patched_due_crew()
    keep = dict(wrap._state)
    try:
        def open_anki(day):
            labels = span(day)
            entries = crew(labels)
            wrap._state.update(labels=labels, entries=entries)
            wrap._update_wrap(entries, labels)
            return wrap._wrap_data(), wrap._wrap_info()

        w, banner = open_anki(D(2026, 9, 7))     # a Monday, first run ever
        check("ledger: first run folds nothing (the old accrual owned the past)",
              (w.get("life") or {}).get("reviews", 0) == 0)
        check("banner: last week from the six of its days the board has seen",
              banner["reviews"] == 1200 and banner["days_known"] == 6)

        w, banner = open_anki(D(2026, 9, 16))    # next open is a WEDNESDAY, nine days on
        check("ledger: a day joins the all-time total once, when it leaves the window",
              w["life"]["reviews"] == 200)       # Sep 7 only; Sep 8-9 were never seen
        check("banner: last week is Sep 7-13 exactly, and admits it saw 5 of 7 days",
              banner["reviews"] == 1000 and banner["days_known"] == 5 and banner["best_name"] == "")
        page = board.render({"entries": [], "labels": wed, "tomorrow": "", "pending": []},
                            {}, 0, wrap=banner)
        check("banner: the partial week is said out loud", "from 5 of its 7 days" in page)

        w, _b = open_anki(D(2026, 9, 17))        # Thursday
        check("ledger: opening again the next day adds just the one day that left",
              w["life"]["reviews"] == 400)

        w, banner = open_anki(D(2026, 9, 21))    # Monday again
        check("ledger: shifting open-days neither double-count nor skip (Sep 7,10-14 = 1,250)",
              w["life"]["reviews"] == 1250)
        check("banner: a whole last week, Mon-Sun, however late it is first opened",
              banner["reviews"] == 1750 and banner["days_known"] == 7 and banner["full_days"] == 7)
        check("banner: best week is judged against settled weeks before last",
              banner["best_name"] == "Dre" and w["best"] == {"sam": 600, "dre": 600})
        full = board.render({"entries": [], "labels": span(D(2026, 9, 21)), "tomorrow": "",
                             "pending": []}, {}, 0, wrap=banner)
        check("banner: a complete week says nothing about coverage", "of its 7 days" not in full)
        w["dismissed"] = wrap._week_key("2026-09-21")
        check("banner: dismissing lasts the week", wrap._wrap_info() is None)
    finally:
        wrap._state.clear()
        wrap._state.update(keep)


def test_wrap_file_is_durable():
    """wrap.json is read inside the deck browser's render hook, so a bad one
    must not raise there; and it holds the all-time totals, so a write that
    dies halfway must not take them with it."""
    wrap = _patched_due_crew()
    path = os.path.join(wrap._profile_files(), "wrap.json")
    keep = dict(wrap._state)
    try:
        good = {"r": 10, "t": 5, "all": False, "p": {"sam": 10}, "folded": False}
        for label, ledger in (("a list", []), ("a null day", {"2026-09-14": None}),
                              ("a day without counts", {"2026-09-14": {"p": {}}}),
                              ("text for a person's count", {"2026-09-14": dict(good, p={"sam": "x"})})):
            with open(path, "w") as f:
                json.dump({"ledger": ledger, "life": {"reviews": 900, "time_ms": 1, "since": "2026-01-01"},
                           "muted_knocks": ["u1"]}, f)
            wrap._wrap["profile"] = None
            w = wrap._wrap_data()
            wrap._state.update(labels=["2026-09-21"], entries=[])
            try:
                wrap._wrap_info()
                raised = False
            except Exception:
                raised = True
            check(f"wrap.json: a ledger that is {label} is dropped, the rest kept, nothing raises",
                  "ledger" not in w and w["life"]["reviews"] == 900 and w["muted_knocks"] == ["u1"]
                  and not raised)
        with open(path, "w") as f:
            json.dump(["not", "ours"], f)
        wrap._wrap["profile"] = None
        check("wrap.json: not even a dict loads as empty", wrap._wrap_data() == {})
        with open(path, "w") as f:
            json.dump({"ledger": {"2026-09-14": good}}, f)
        wrap._wrap["profile"] = None
        check("wrap.json: a ledger in our own shape is kept as it is",
              wrap._wrap_data()["ledger"] == {"2026-09-14": good})

        wrap._wrap["data"] = {"life": {"reviews": 1234}}
        wrap._save_wrap()
        with open(path) as f:
            saved = json.load(f)
        check("wrap.json: saved whole, no temp file left", saved == {"life": {"reviews": 1234}}
              and os.listdir(wrap._profile_files()) == ["wrap.json"])

        class DiesHalfway:  # 3.9.1: the text is made first, then written in one go
            def __init__(self, f):
                self.f = f

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self.f.close()

            def write(self, text):
                self.f.write(text[:len(text) // 2])
                raise OSError("disk full")

        from due_crew import store  # 3.9.12: every file is written by store.py
        store.open = lambda p, mode="r", *a, **k: DiesHalfway(open(p, mode, *a, **k)) if "w" in mode else open(p, mode, *a, **k)
        try:
            wrap._wrap["data"] = {"life": {"reviews": 0}}
            wrap._save_wrap()
        finally:
            del store.open
        with open(path) as f:
            after = json.load(f)
        check("wrap.json: a write that dies halfway leaves the last good file in place",
              after == {"life": {"reviews": 1234}}
              and os.listdir(wrap._profile_files()) == ["wrap.json"])
    finally:
        wrap._state.clear()
        wrap._state.update(keep)
        wrap._wrap["profile"] = None
        wrap._wrap["data"] = {}


def test_cheer_any_emoji():
    """v2.7: a cheer carries any one emoji. The server restates the shape
    rule; the client keeps one cluster on send and on receive."""
    from due_crew import social
    from due_crew.app import CHEER_QUICK
    store = world({"sam": "Sammy", "dre": "Dre"}, {"sam": ["dre"], "dre": ["sam"]})
    dre = new_client(store, "dre", "Dre")
    got = lambda: store.cheers[("sam", "dre")]["emoji"]
    party, thumbs = "\U0001F973", "\U0001F44D\U0001F3FD"
    check("any emoji: a new one lands", dre.send_cheer("sam", party) is True and got() == party)
    check("any emoji: a skin tone rides along as one cluster",
          dre.send_cheer("sam", thumbs) is True and got() == thumbs)
    check("any emoji: the client sends one cluster, whatever it was handed",
          dre.send_cheer("sam", party + "\U0001F389 yay") is True and got() == party)
    check("any emoji: text never leaves the client", dre.send_cheer("sam", "lol") is False and got() == party)
    refused = [dre._call("POST", "/cheers/sam", {"emoji": bad})[0]
               for bad in ("lol", "\U0001F525x", "\U0001F389" * 9, "", "\U0001F389 ")]
    check("server: letters, a trailing letter, 18 units, empty, and a space are refused",
          refused == [400] * 5 and got() == party, str(refused))
    store.cheers[("sam", "dre")]["emoji"] = "hello"  # as if the server had let it through
    sam = new_client(store, "sam", "Sammy")
    data, _l, _t = fetch_as(store, sam, make_user_col([TODAY]))
    check("any emoji: a cheer that isn't one emoji is dropped on receive", data["cheers"] == [])
    fetch_as(store, sam, make_user_col([TODAY]))
    check("any emoji: a delivered cheer is gone", ("sam", "dre") not in store.cheers)
    dre.send_cheer("sam", thumbs)
    data, _l, _t = fetch_as(store, sam, make_user_col([TODAY]))
    check("any emoji: a real one arrives intact", [c["emoji"] for c in data["cheers"]] == [thumbs])
    check("cheer picker: the quick row and the any-emoji box",
          social.cheer_choices() == (CHEER_QUICK, True))
    check("cheer gate: one cluster; text never",
          social.cheer_allowed(party + "\U0001F389") == party and social.cheer_allowed("lol") == "")


def test_request_paths_and_errors():
    """An id that isn't one never becomes another route, and a failed
    request's message never carries a code (codes are never logged)."""
    from due_crew.backend import api as A
    store = world({"sam": "Sammy"}, {})
    cl = new_client(store, "sam", "Sammy")
    for bad in ("/squads/../admin/people", "squads/x", "/squads/x\\..\\y"):
        try:
            cl._call("GET", bad)
            ok = False
        except A.TransportError:
            ok = True
        check(f"paths: {bad!r} refused before it goes", ok)
    check("errors: codes in paths are left out", A._said("/codes/ABC123/add?x=1") == "/codes/…/add"
          and A._said("/invites/ABCDEFGHJK/redeem") == "/invites/…/redeem" and A._said("/squads/s1") == "/squads/s1")


def test_studying_dot_by_itself_v3910():
    """3.9.10 (Sam: "get rid of I'm studying and just have it automatically
    pushed when someone has synced reviews within the last hour"): my dot
    for an hour after my last review, set as a sync is made ready and riding
    my week as the button's hour did; Privacy's switch, never for someone
    paused or just showing up; said once at the board's foot; the squad's
    square counts studying while a crewmate is."""
    import due_crew as dc
    from due_crew import together as T, account, settings_model as SM, bingo_flow
    from due_crew.app import _state
    from aqt.deckbrowser import DeckBrowser
    if "aqt.reviewer" not in sys.modules:
        sys.modules["aqt.reviewer"] = types.SimpleNamespace(Reviewer=type("Reviewer", (), {}))
    store = world({"sam": "Sam", "dre": "Dre"})
    cl = new_client(store, "sam", "Sam")
    now = datetime.datetime(2026, 11, 12, 15, 0, tzinfo=datetime.timezone.utc)
    ms = lambda mins: int((now - datetime.timedelta(minutes=mins)).timestamp() * 1000)  # noqa: E731
    iso = lambda mins: (now + datetime.timedelta(minutes=mins)).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    bumps = []
    saved = (T.client, bingo_flow.bump, _state.get("entries"), dc.cfg, dc.save_cfg, T.cfg, T.save_cfg, dc._swap, dc.open_settings)
    conf = {}
    try:
        T.client = lambda: cl
        bingo_flow.bump = lambda k, by=1: bumps.append(k)
        _state["entries"] = []
        cl.session.pop("live_until", None)
        check("the dot: a review 20 minutes ago: live for the 40 left of its hour",
              T.auto_live({}, ms(20), "2026-11-12", now) is True and cl.session["live_until"] == iso(40))
        check("…a newer review moves it on; the same one again changes nothing",
              T.auto_live({}, ms(5), "2026-11-12", now) is True and cl.session["live_until"] == iso(55)
              and T.auto_live({}, ms(5), "2026-11-12", now) is False)
        check("…a review over an hour ago, or none: no dot, and the hour it set goes",
              T.auto_live({}, ms(61), "2026-11-12", now) is True and "live_until" not in cl.session
              and T.auto_live({}, 0, "2026-11-12", now) is False)
        for off in ({"show_studying": False}, {"paused": True}, {"show_up": True}):
            cl.session.pop("live_until", None)
            cl.session.pop("live_auto", None)
            T.auto_live({}, ms(5), "", now)
            T.auto_live(off, ms(5), "", now)
            check(f"…{sorted(off)[0]}: no dot, the one it had set taken down", "live_until" not in cl.session and not T.live_on(off))
        cl.session["live_until"] = room = iso(90)  # a room's or a fifteen's hour
        T.auto_live({}, ms(5), "", now)
        T.auto_live({"show_studying": False}, ms(5), "", now)
        check("…a room's or a fifteen's longer hour is never shortened, nor taken down by the switch", cl.session.get("live_until") == room)
        cl.session.pop("live_until", None)
        cl.session.pop("live_lv", None)
        real_now = datetime.datetime.now(datetime.timezone.utc)
        soon = (real_now + datetime.timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        fresh = int((real_now - datetime.timedelta(minutes=2)).timestamp() * 1000)
        T.auto_live({}, fresh, "2026-11-12")
        _state["entries"] = [{"user_id": "dre", "you": False, "live_until": soon}]
        T.auto_live({}, fresh, "2026-11-12")
        T.auto_live({}, fresh, "2026-11-12")
        check("the squad's square (lv): the first time in a day I'm studying while a crewmate is, once",
              bumps == ["lv"] and cl.session.get("live_lv") == "2026-11-12", bumps)
        check("the switch is an account key, a bool, on unless turned off; telling is one too; a sharing change, so it syncs",
              {"show_studying", "live_told"} <= set(account.ACCOUNT_KEYS)
              and account.clean({"show_studying": False, "live_told": True}) == {"show_studying": False, "live_told": True}
              and SM.change(["set", "show_studying", "0"], {}) == {"show_studying": False}
              and "show_studying" in dc.SHARE_KEYS and "show_studying" not in SM.BOARD_DEFAULTS)
        pv = board._settings_privacy({})
        check("Privacy: Show when I'm studying, on, with what it does; paused: it says it's off",
              "duecrew:set:show_studying:0" in pv and "an hour after your last review" in pv
              and "Off while you&rsquo;re paused" in board._settings_privacy({"paused": True}))
        ix = board.settings_index({"signed_in": True}, {})
        check("Find a setting: dot, live or presence finds it, on Privacy",
              all(any(w in r["k"].split() and r["f"] == "set:show_studying:" and r["t"] == "privacy" for r in ix) for w in ("dot", "live", "presence")))
        data = {"entries": [], "labels": [TODAY.isoformat()], "tomorrow": "", "pending": []}
        told = {"use_told": True}
        line = board.render(data, dict(told), 0)
        check("the board says it once: a line at the foot with Privacy and Got it; not beside the line on what's counted, "
              "not once put away, not for someone paused",
              T.LIVE_NOTE in line and "duecrew:livesee|" in line and "duecrew:livetold|" in line
              and T.LIVE_NOTE not in board.render(data, {}, 0)
              and T.LIVE_NOTE not in board.render(data, dict(told, live_told=True), 0)
              and T.LIVE_NOTE not in board.render(data, dict(told, paused=True), 0))
        swaps, opened = [], []
        dc.cfg = T.cfg = lambda: conf
        dc.save_cfg = T.save_cfg = lambda c: conf.update(c)
        dc._swap = lambda c, focus=None: swaps.append(1)
        dc.open_settings = lambda tab=None: opened.append(tab)
        conf.update(use_told=True)
        dc._on_js(False, as_board("duecrew:livetold"), DeckBrowser())
        check("Got it: put away, the board drawn again", conf.get("live_told") is True and swaps == [1])
        conf.pop("live_told")
        dc._on_js(False, as_board("duecrew:livesee"), DeckBrowser())
        check("Privacy: put away, and Settings opens on Privacy", conf.get("live_told") is True and opened == ["privacy"])
        src = srcs.glue_src()
        check("it's set as a sync is made ready (no request of its own), from my last review; the button's command is gone",
              "together.auto_live(c, q.last_review_ms(), labels[0])" in src and '"live": (' not in src
              and not hasattr(T, "toggle_live"))
        mig = open(os.path.join(REPO, "worker", "migrations", "0031_bingo_together.sql"), encoding="utf-8").read()
        check("the square's words on the server say what it counts now, its key the same, only where the admin hasn't rewritten it",
              '"name":"Studying together"' in mig and '"params":{"key":"lv"}' in mig and "WHERE id = 'buddy' AND updated_at = 0" in mig)
        check("the privacy page says the dot shows by itself and where its switch is",
              "by itself, for an hour after your last review" in open(os.path.join(REPO, "site", "public", "privacy.html"), encoding="utf-8").read())
    finally:
        (T.client, bingo_flow.bump, _state["entries"], dc.cfg, dc.save_cfg, T.cfg, T.save_cfg, dc._swap, dc.open_settings) = saved


def test_request_budget():
    """3.0: a refresh is ONE request, whatever the crew's size, and a sync
    is one. The numbers below are the budget: a change here is a change in
    what the add-on costs, and must be deliberate."""
    import due_crew  # the glue: _wants_fetch, _open_push_due
    N = 25
    friends = [f"f{i}" for i in range(N)]
    store = world({"sam": "Sammy", **{f: f.upper() for f in friends}},
                  {"sam": friends, **{f: ["sam"] for f in friends}})
    labels = [(TODAY - datetime.timedelta(days=i)).isoformat() for i in range(7)]
    tomorrow = (TODAY + datetime.timedelta(days=1)).isoformat()
    for f in friends:
        new_client(store, f).push(labels, {}, stats=types.SimpleNamespace(
            reviews=100, time_ms=60000, accuracy=90.0, streak=3, new_cards=4))
    sam = new_client(store, "sam", "Sammy")
    count = lambda fn: (lambda n: (fn(), len(store.log) - n)[1])(len(store.log))
    check("budget: a refresh (light or full, with decks or not) is one request",
          count(lambda: sam.fetch_board(labels, tomorrow)) == 1
          and count(lambda: sam.fetch_board(labels, tomorrow, with_decks=True)) == 1)
    data = sam.fetch_board(labels, tomorrow)
    check(f"budget: and it carries all {N} weeks", sum(
        1 for e in data["entries"] if not e["you"] and board._showed(e["days"].get(labels[0]))) == N)
    col = make_user_col([TODAY])
    check("budget: a full sync is one request",
          count(lambda: sync_once(store, sam, col, tempfile.mkdtemp(), {}, TODAY)) == 1)
    check("budget: the version check is one request a day",
          count(lambda: [sam.check_version(labels[0], "3.0.0") for _ in range(3)]) == 1)
    new_client(store, "f0").send_cheer("sam", "\U0001F525")
    data = sam.fetch_board(labels, tomorrow)
    again = sam.fetch_board(labels, tomorrow)  # that reply was lost: nothing acked yet
    acked(sam, again)
    check("cheers: they ride the refresh, a lost reply loses none, and once seen they go",
          [c["from"] for c in data["cheers"]] == ["f0"] and [c["from"] for c in again["cheers"]] == ["f0"]
          and sam.fetch_board(labels, tomorrow)["cheers"] == [])
    store.friends.discard(("f4", "sam"))
    data = sam.fetch_board(labels, tomorrow)
    check("a friend who removed me drops off the board at the next refresh, no error",
          "f4" not in {e["user_id"] for e in data["entries"]} and "F4" in data["pending"])
    check("fetch after upload: only when the board is old, never while closing, always for a pure fetch",
          due_crew._wants_fetch(True, True, 30, False) is False
          and due_crew._wants_fetch(True, True, 300, False) is True
          and due_crew._wants_fetch(True, False, 0, False) is True
          and due_crew._wants_fetch(False, True, 0, False) is True
          and due_crew._wants_fetch(False, True, 9999, True) is False
          and due_crew._wants_fetch(True, True, 0, False, fetch=True) is True)
    check("push on open: goes unless something already pushed; the open's fetch is not a push",
          due_crew._open_push_due(1000, 0) and not due_crew._open_push_due(1000, 950))
    # 3.8.1: someone who writes a plan sends its deck's tree for the builder at the moment the
    # day's first refresh sends the plan's note ids: one PUT on a day its tags changed, none otherwise
    store.add_plan("sam", "Step 1", "Step 1", _plan_units())
    sam.fetch_board(labels, tomorrow, with_decks=True)
    col = _plan_col()
    trees = lambda: sum(1 for m, p, _s in store.log if m == "PUT" and p == "/plans/trees")
    with _PlanGlue({"A": sam}, {"A": col}) as g, _SyncBg(g.F):
        refresh = lambda: g.F.maybe_morning(True, fresh=True)  # the day's first refresh, before the AnkiWeb sync
        n = trees()
        refresh()
        refresh()
        first = trees() - n
        g.today["d"] = _day(1)
        refresh()
        same = trees() - n - first
        col.db.conn.execute("UPDATE notes SET tags = ' Step1::Cardio::Arrhythmia Step1::Cardio::Long_QT ' WHERE id = 3")
        g.today["d"] = _day(2)
        refresh()
        refresh()
        changed = trees() - n - first - same
    check("budget: a plan's deck tree goes up once on a day its tags changed, never on a day they didn't",
          first == 1 and same == 0 and changed == 1, (first, same, changed))


def test_week_doc_v29():
    """2.9's week doc, as 3.0's one shape: the week of a friend in one
    piece, the away spell as a range, the exam date, paused, and nothing
    written twice."""
    store = world({"sam": "Sammy", "f0": "F0", "f3": "F3", "f4": "F4", "f5": "F5"},
                  {"sam": ["f0", "f3", "f4", "f5"], "f0": ["sam"], "f3": ["sam"], "f4": ["sam"], "f5": ["sam"]})
    days = [TODAY - datetime.timedelta(days=i) for i in (0, 1, 3, 4, 6)]
    labels = [(TODAY - datetime.timedelta(days=i)).isoformat() for i in range(7)]
    tomorrow = (TODAY + datetime.timedelta(days=1)).isoformat()
    sync_once(store, new_client(store, "f0"), make_user_col(days), tempfile.mkdtemp(), {}, TODAY)
    week = json.loads(store.weeks["f0"][0])
    check("week doc: one doc holds the studied days of the week, numbers inside",
          sorted(week["days"]) == sorted(d.isoformat() for d in days) and "reviews" in week["days"][labels[0]])
    sam = new_client(store, "sam", "Sammy")
    f0 = next(e for e in sam.fetch_board(labels, tomorrow)["entries"] if e["user_id"] == "f0")
    check("week doc: a refresh carries the whole week",
          sum(1 for lb in labels if board._showed(f0["days"].get(lb))) == len(days))
    away = {"away_from": (TODAY + datetime.timedelta(days=1)).isoformat(),
            "away_to": (TODAY + datetime.timedelta(days=5)).isoformat(),
            "exam_date": (TODAY + datetime.timedelta(days=9)).isoformat()}
    sync_once(store, new_client(store, "f3"), make_user_col(days), tempfile.mkdtemp(), away, TODAY)
    e3 = next(e for e in sam.fetch_board(labels, tomorrow)["entries"] if e["user_id"] == "f3")
    check("week doc: an away spell flags my tomorrow for a friend, and the exam date rides along",
          (e3["days"].get(tomorrow) or {}).get("away") is True and e3["exam_date"] == away["exam_date"])
    sync_once(store, new_client(store, "f4"), make_user_col(days), tempfile.mkdtemp(), {"paused": True}, TODAY)
    wk = json.loads(store.weeks["f4"][0])
    check("week doc: pausing empties the days and says so", wk["paused"] is True and wk["days"] == {})
    e4 = next(e for e in sam.fetch_board(labels, tomorrow)["entries"] if e["user_id"] == "f4")
    check("week doc: a paused friend reads as paused from the doc itself",
          e4["paused"] is True and not any(e4["days"].get(lb) for lb in labels))
    f5, col5, files5 = new_client(store, "f5"), make_user_col(days), tempfile.mkdtemp()
    sync_once(store, f5, col5, files5, {}, TODAY)
    n = store.wrote.get("weeks", 0)
    sync_once(store, f5, col5, files5, {}, TODAY)
    check("week doc: a second sync with nothing new writes nothing", store.wrote.get("weeks", 0) == n)


def test_big_crews_v29():
    """2.9 (G1) was a crew past twenty friends failing its whole batch. In
    3.0 any crew is one request, decks included."""
    n = 40
    friends = [f"g{i}" for i in range(n)]
    store = world({"sam": "Sammy", **{f: f for f in friends}}, {"sam": friends, **{f: ["sam"] for f in friends}})
    labels = [(TODAY - datetime.timedelta(days=i)).isoformat() for i in range(7)]
    for f in friends:
        new_client(store, f).push(labels, {}, stats=types.SimpleNamespace(
            reviews=5, time_ms=1, accuracy=None, streak=1, new_cards=0),
            shared_decks=[{"name": "A", "sig": ["x"], "total": 5, "seen": 1, "mature": 0}])
    sam = new_client(store, "sam", "Sammy")
    data = sam.fetch_board(labels, with_decks=True)
    studied = sum(1 for e in data["entries"] if not e["you"] and board._showed(e["days"].get(labels[0])))
    check(f"big crew: {n} friends load in one request, decks too",
          studied == n and len(sam.fetch_decks()) == n, str(studied))


def test_profile_guard_v29():
    """The profile is written when a field of it changes, not on every sync;
    a sync with nothing new still counts as synced."""
    store = world({"sam": "Sammy"})
    sam = new_client(store, "sam", "Sammy")
    labels = [TODAY.isoformat()]
    push = lambda cfg: sam.push(labels, cfg, version="3.0.0", clock={"tz": 0, "rollover": 4})
    push({})
    a = store.wrote.get("users", 0)
    stamp = sam.session.get("last_ok")
    push({})
    b = store.wrote.get("users", 0)
    check("profile: a sync with nothing new doesn't rewrite it, and still counts as synced",
          a == 1 and b == 1 and sam.session.get("last_ok") >= stamp, f"{a} {b}")
    push({"emoji": "\U0001F98A"})
    check("profile: a new emoji rewrites it", store.wrote.get("users", 0) == 2)


def test_code_knocks_v29():
    """2.9 (J1): adding a code knocks its owner, so they add back in one click."""
    store = world({"sam": "Sammy", "priya": "Priya", "carl": "Carl"})
    store.codes.update(SAM123="sam", CRL456="carl")
    store.users["sam"]["code"], store.users["carl"]["code"] = "SAM123", "CRL456"
    priya = new_client(store, "priya", "Priya")
    friend, err = priya.add_friend("Study with me on Due Crew · my code SAM123")
    check("code knock: a pasted invite adds, and the owner is knocked",
          err is None and friend["user_id"] == "sam" and friend["knocked"] is True
          and ("priya", "sam") in store.friends and ("sam", "priya") in store.knocks)
    sam = new_client(store, "sam", "Sammy")
    check("code knock: the owner's list shows it, with no squad", sam.list_knocks() == [("priya", "Priya", "")])
    check("code knock: adding them back clears it, and they're crew",
          sam.add_back("priya")["mutual"] is True and sam.list_knocks() == [])
    check("code knock: errors say what happened",
          priya.add_friend("SAM123")[1] == "Already in your crew."
          and priya.add_friend("ZZZ999")[1] == "That code doesn't match anyone."
          and sam.add_friend("SAM123")[1] == "That's your own code.")
    fc = shapes.friend_code_from
    check("invite paste: a friend code from a code, a spaced code, or either invite wording",
          fc("k7q2zp") == "K7Q2ZP" and fc(" K7Q 2ZP ") == "K7Q2ZP"
          and fc("Study with me on Due Crew — Anki add-on 2035408484.\nMy friend code: K7Q2ZP") == "K7Q2ZP"
          and fc("Study with me on Due Crew · my code K7Q2ZP\n— Due Crew · Anki add-on 2035408484") == "K7Q2ZP"
          and fc("Join orca on Due Crew · code ABCD2345") == "")
    check("invite paste: a squad code from its invite, even from a squad named for codes",
          shapes.squad_code_from("Join code club on Due Crew · code ABCD2345\n— Due Crew") == "ABCD2345"
          and shapes.squad_code_from("abcd 2345") == "ABCD2345")
    store.add_user("newbie", None)
    newbie = new_client(store, "newbie", "Newbie")
    code, people, _k = newbie.friends_view()
    check("a new account gets its code the first time Friends (or Welcome) opens",
          code and store.codes.get(code) == "newbie" and people == [])


def test_new_code():
    """2.10: New code swaps my friend code; the old one stops working, the
    crew stays."""
    store = world({"sam": "Sammy", "priya": "Priya"}, {"sam": ["priya"], "priya": ["sam"]})
    store.codes["SAM123"] = "sam"
    store.users["sam"]["code"] = "SAM123"
    sam = new_client(store, "sam", "Sammy")
    code, err = sam.new_friend_code("SAM123")
    check("new code: a fresh code, mine; the old one gone",
          err is None and code and code != "SAM123" and store.codes.get(code) == "sam"
          and store.users["sam"]["code"] == code and "SAM123" not in store.codes)
    check("new code: the board shows it", sam.fetch_board([TODAY.isoformat()])["my_code"] == code)
    check("new code: the crew is untouched", store.mutual("sam", "priya"))
    priya = new_client(store, "priya", "Priya")
    check("new code: the old code no longer matches anyone",
          priya.add_friend("SAM123")[1] == "That code doesn't match anyone.")
    store.down = True
    check("new code: offline, the code is unchanged and it says so",
          sam.new_friend_code(code) == (None, "Couldn't make a new code. Check your connection.")
          and store.codes.get(code) == "sam")
    store.down = False


def test_squad_privacy_v29():
    """2.9 (G2): the Privacy switches reach squad rows, through the same
    gate as my week."""
    values = {"reviews": 40, "studyTimeMs": 90000, "accuracy": 91.0, "streak": 3}
    cfg = {"share_time": False, "share_retention": False}
    check("squad row: switched-off numbers stay home",
          shapes.shared_numbers(values, cfg) == {"reviews": 40, "streak": 3})
    check("squad row: just show up lets none out", shapes.shared_numbers(values, {"show_up": True}) == {})
    doc = shapes.day_doc(values, cfg)
    check("my week: the same gate", "studyTimeMs" not in doc and "accuracy" not in doc
          and doc["reviews"] == 40 and doc["streak"] == 3 and doc["studied"] is True)


def test_settings_follow_account_v213():
    """2.13: a person's settings follow their account. A second computer
    pulls them before it uploads anything, so it never sends defaults over
    them (the shared decks a friend lost, the privacy switches)."""
    from due_crew import account, app as appmod
    from due_crew.app import _state
    # pure: decks by id, else by name; junk dropped; bounds
    cfg_a = {"share_retention": False, "show_up": False, "exam_date": "2026-10-02",
             "shared_decks": [11, 12], "squads": [{"id": "sq1", "code": "ABCD2345", "name": "orca", "founder": "x"}],
             "status": "coffee", "accent": "rose", "sort": "time"}
    doc = account.pick(cfg_a, {11: "Big Deck", 12: "Path Book"}.get)
    check("pick: only what follows the account; decks with names; sort stays, the accent goes (3.5.0)",
          doc["accent"] == "rose" and "sort" not in doc
          and doc["shared_decks"] == [{"id": 11, "name": "Big Deck"}, {"id": 12, "name": "Path Book"}])
    here = {11: 11, 99: 99}                      # this computer: 11 by id, Path Book by name as 99
    resolve = lambda did, name: here.get(did) or {"Path Book": 99}.get(name)
    got = account.apply({"accent": "green", "share_retention": True}, doc, resolve)
    check("apply: the account's settings land, the accent too; the deck matches by id, else by name",
          got["share_retention"] is False and got["exam_date"] == "2026-10-02"
          and got["shared_decks"] == [11, 99] and got["accent"] == "rose" and got["shared_decks_set"])
    junk = account.clean({"share_retention": "no", "status": "x" * 500, "squads": [{"id": 5}, "x"],
                          "shared_decks": [{"id": "abc"}, {"id": 3, "name": 7}] + [{"id": 1}] * 500})
    check("clean: wrong types dropped, text and lists bounded",
          "share_retention" not in junk and len(junk["status"]) == 80 and junk["squads"] == []
          and len(junk["shared_decks"]) == account.MAX_DECKS and junk["shared_decks"][0] == {"id": 3, "name": "7"})

    # the doc: mine only
    store = world({"sam": "Sammy", "dre": "Dre"}, {"sam": ["dre"], "dre": ["sam"]})
    sam = new_client(store, "sam", "Sammy")
    ok = sam.put_settings("2026-09-24T10:00:00.000000Z", doc)
    back, status = sam.get_settings()
    check("settings doc: I write it and read it back", ok and status == 200
          and back["settings"]["shared_decks"][1]["name"] == "Path Book")
    dre = new_client(store, "dre", "Dre")
    check("settings doc: not even my crew can read it (GET /settings is only ever mine)",
          dre.get_settings()[1] == 404)

    # two computers, through the real pull and push
    saved = {k: getattr(account, k) for k in ("cfg", "client")}
    saved_app = {k: getattr(appmod, k) for k in ("_bg", "save_cfg", "swap")}
    saved_col = account.mw.col
    boxes = {}

    class Decks:
        def __init__(self, names): self.names = names
        def get(self, did, default=False): return {"id": did} if did in self.names else default
        def name(self, did): return self.names.get(did, "")
        def id_for_name(self, name): return next((d for d, n in self.names.items() if n == name), None)

    def computer(name, config, decks):
        cl = new_client(store, "sam", "Sammy")
        boxes[name] = {"cfg": config, "cl": cl, "decks": Decks(decks)}
        return boxes[name]

    def use(box):
        account.cfg = lambda: dict(box["cfg"])
        account.client = lambda: box["cl"]
        appmod.save_cfg = lambda c, from_account=False: box["cfg"].update(c)
        account.mw.col = types.SimpleNamespace(decks=box["decks"])
        _state.update(settings_ready=False, settings_pulling=False, labels=[TODAY.isoformat()])

    appmod._bg = lambda job, done=None: done(job()) if done else job()
    appmod.swap = None
    store.settings.pop("sam", None)
    try:
        a = computer("a", dict(cfg_a), {11: "Big Deck", 12: "Path Book"})
        use(a)
        synced = []
        account.ensure(lambda: synced.append("a"))
        check("first computer: nothing on the account yet, so its settings go up, then its sync runs",
              synced == ["a"] and "sam" in store.settings and account.ready())
        b = computer("b", {"share_retention": True, "shared_decks": [], "accent": "blue"},
                     {11: "Big Deck", 77: "Path Book"})
        use(b)
        order = []
        real_pulled = account._pulled
        account._pulled = lambda r, *a: (order.append("pulled"), real_pulled(r, *a))[1]
        account.ensure(lambda: order.append("sync"))
        account._pulled = real_pulled
        check("second computer: pulls before its first sync, and takes the account's settings",
              order == ["pulled", "sync"] and b["cfg"]["shared_decks"] == [11, 77]
              and b["cfg"]["share_retention"] is False and b["cfg"]["accent"] == "rose")
        b["cfg"]["status"] = "200 cards, then bed"
        account.on_change(b["cfg"])
        use(a)
        a["cl"].session["settings_day"] = ""  # the next day
        account.ensure()
        check("a change on one computer reaches the other on its next pull",
              a["cfg"]["status"] == "200 cards, then bed")
        # newest save wins: a has an unsent edit newer than the doc
        a["cl"].session.update(settings_dirty=True, settings_local_at="2999-01-01T00:00:00Z", settings_seen="old")
        a["cfg"]["exam_date"] = "2027-01-01"
        a["cl"].session["settings_day"] = ""
        account.ensure()
        check("newest save wins: an unsent edit here, newer than the account's, goes up instead",
              store.settings["sam"]["settings"]["exam_date"] == "2027-01-01")
        # offline: the pull fails, the sync still runs, and doesn't loop
        use(a)
        a["cl"].session["settings_day"] = ""
        real_get = a["cl"].get_settings
        tries = []
        a["cl"].get_settings = lambda: (tries.append(1), (None, 0))[1]
        runs = []

        def sync_like():
            runs.append(1)
            if not account.ready():
                account.ensure(sync_like)
        account.ensure(sync_like)
        a["cl"].get_settings = real_get
        check("offline: one failed pull, then the sync runs once, no loop",
              tries == [1] and runs == [1] and account.ready())
        # 3.7.1, D2: Delete my to-dos on the site reaches Anki at its next refresh
        use(a)
        a["cfg"]["due_items"] = [{"id": "x1", "t": "read ch 4"}]
        a["cl"].session.update(settings_dirty=False, settings_day=TODAY.isoformat())
        a["cl"].put_settings("2026-10-03T08:00:00.000000Z", account.pick(a["cfg"]))
        a["cl"].session.update(settings_seen="2026-10-03T08:00:00.000000Z", settings_dirty=False)
        a["cl"]._call("DELETE", "/account/todos")
        _state["settings_failed_ts"] = 0
        board = a["cl"].fetch_board([TODAY.isoformat()])
        account.saved_elsewhere(board["settings_at"])
        check("a save made elsewhere (the site's Delete my to-dos) is pulled at the next refresh",
              a["cfg"]["due_items"] == [] and a["cl"].session["settings_seen"] == store.settings["sam"]["at"])
        pulls = []
        real_get = a["cl"].get_settings
        a["cl"].get_settings = lambda: (pulls.append(1), real_get())[1]
        account.saved_elsewhere(store.settings["sam"]["at"])
        a["cl"].session["settings_dirty"] = True
        account.saved_elsewhere("2999-01-01T00:00:00.000000Z")
        a["cl"].get_settings = real_get
        a["cl"].session["settings_dirty"] = False
        check("...and a save already seen, or one of mine still unsent, isn't pulled again", pulls == [])
    finally:
        for k, v in saved.items():
            setattr(account, k, v)
        for k, v in saved_app.items():
            setattr(appmod, k, v)
        account.mw.col = saved_col
        _state.update(settings_ready=False, settings_pulling=False, labels=[])


def test_study_rooms_v212():
    """2.12: study rooms. A shared clock on the week doc, no reads; the
    room shows in the top bar, else the bottom bar, else the margin; the
    break waits for the card on screen."""
    from due_crew import room_model as rm
    utc = datetime.timezone.utc
    t0 = datetime.datetime(2026, 9, 24, 18, 0, tzinfo=utc)
    room = rm.make_room("dre", t0, 4, 25, 5)
    at = lambda m: t0 + datetime.timedelta(minutes=m)
    check("room: 4 x 25 with 5-min breaks is 115 minutes", rm.room_minutes(room) == 115
          and rm.room_end(room) == at(115))
    ph = [(m, rm.phase(room, at(m))) for m in (-10, 0, 24, 25, 29, 30, 60, 114, 115)]
    got = [(m, p["state"], p["round"], round(p["left"] / 60)) for m, p in ph]
    check("room: the clock, from the start time alone",
          got == [(-10, "before", 0, 10), (0, "round", 1, 25), (24, "round", 1, 1), (25, "break", 1, 5),
                  (29, "break", 1, 1), (30, "round", 2, 25), (60, "round", 3, 25), (114, "round", 4, 1),
                  (115, "done", 4, 0)], got)
    check("room: no breaks when the break is 0",
          rm.phase(rm.make_room("x", t0, 2, 25, 0), at(25))["state"] == "round")
    bad = rm.clean_room({"host": "<b>x</b>" * 40, "start": "2026-09-24T18:00:00Z", "rounds": 999,
                         "round": 0, "brk": -3})
    check("room: a friend's doc is bounded (rounds, lengths, host)",
          bad["rounds"] == rm.MAX_ROUNDS and bad["round"] == 5 and bad["brk"] == 0
          and len(bad["host"]) == rm.HOST_MAX)
    check("room: junk is no room", rm.clean_room({"host": "x", "start": "soon"}) is None
          and rm.clean_room("room") is None and rm.clean_room(None) is None)

    entries = [{"user_id": "dre", "name": "Dre <K>", "you": False, "room": room},
               {"user_id": "ameya", "name": "Ameya", "you": False, "room": room},
               {"user_id": "yas", "name": "Yashas", "you": False, "room": None},
               {"user_id": "me", "name": "sammy", "you": True, "room": None}]
    inv = rm.invites(entries, None, now=at(36))
    check("invites: a room my crew is in, with who's in",
          len(inv) == 1 and [m[1] for m in inv[0][1]] == ["Dre <K>", "Ameya"]
          and rm.names_line(inv[0][1]) == "Dre and Ameya")
    check("invites: not once I'm in, dismissed, or over",
          rm.invites(entries, room, now=at(36)) == [] and rm.invites(entries, None, {rm.cmd_key(room)}, at(36)) == []
          and rm.invites(entries, None, now=at(200)) == [])
    entries[3]["room"] = room
    view = rm.board_view(room, entries, now=at(36))
    check("lobby: round 2, minutes left, bars, faces, and the host by name",
          view["mine"]["title"] == "Dre\u2019s room" and view["mine"]["label"] == "19"
          and view["mine"]["bars"][0] == 1.0 and 0 < view["mine"]["bars"][1] < 1
          and view["mine"]["initials"] == ["D", "A", "S"] and view["invites"] == [])
    brk = rm.board_view(room, entries, now=at(26))["mine"]
    import re as _re
    with open(rm.__file__) as fh:
        drains = _re.findall(r"(?<!1 - )p\.left / p\.total", fh.read())
    check("rooms (3.8.1): a break's ring fills as it passes, as every ring does, on the board and in each widget; the number is what's left",
          brk["brk"] and brk["frac"] == 0.2 and brk["label"] == "4" and drains == [], str((brk["frac"], drains)))
    html = board.room_html(view)
    check("lobby html: names escaped, Study and Leave",
          "Dre <K>" not in html and "roomstudy" in html and "roomleave" in html)
    inv_html = board.room_html(rm.board_view(None, [dict(e, room=room) if e["user_id"] != "me" else dict(e, room=None) for e in entries], now=at(36)))
    check("invite html: Join by room key, names escaped",
          "roomjoin:" + rm.cmd_key(room) in inv_html and "&lt;K&gt;" not in inv_html
          and "Dre, Ameya and Yashas are in" in inv_html)
    done = {"rounds": 4, "minutes": 115, "with": "Dre and <Ameya>", "uids": [], "day": ""}
    dh = board.room_html({"mine": None, "invites": [], "done": done})
    # Join finds the room from what the command carries
    from due_crew import rooms as rooms_glue
    from due_crew.app import _state as st
    picked = []
    real_set = rooms_glue._set_room
    rooms_glue._set_room = lambda r, msg: picked.append(r)
    st["entries"] = [dict(e, room=room) if e["user_id"] != "me" else dict(e, room=None) for e in entries]
    try:
        cmd = inv_html.split("roomjoin:")[1].split("'")[0].split("|")[0]
        real_over = rm.is_over
        rooms_glue.room_model.is_over = lambda r, now=None: False
        rooms_glue.join(cmd)
    finally:
        rooms_glue._set_room = real_set
        rooms_glue.room_model.is_over = real_over
        st["entries"] = None
    check("join: the key in the Join command finds the room", picked == [room])
    check("done line: how long together and with whom, escaped",
          "1 h 55 m together" in dh and "&lt;Ameya&gt;" in dh and "roomshare" in dh)
    check("done share: one line for the chat",
          rm.done_share(done).startswith("Studied together on Due Crew: 4 rounds, 1 h 55 m with Dre"))

    check("placement: the top bar, else the bottom bar, else the margin",
          rm.placement(False, False) == "chip" and rm.placement(False, True) == "chip"
          and rm.placement(True, False) == "bottom" and rm.placement(True, True) == "gutter")
    data = rm.widget_data(room, entries, ("#6b3fb5", "#b89cf0"))
    js = rm.widget_js("chip", data)
    check("widgets: names ride as JSON data and go in as text",
          '"title": "Dre\\u2019s room"' in js and "innerHTML" not in js.replace("s.innerHTML = SQ", "").replace("w.innerHTML = D.sev[key2]", "")
          and "textContent" in js)
    check("widgets: faces are each person's own initial, mine too (not Y for 'you')",
          data["initials"] == ["D", "A", "S"] and data["names"][-1] == "you")
    check("widgets: the clock comes from start, lengths in ms",
          data["start"] == int(t0.timestamp() * 1000) and data["round"] == 25 * 60000 and data["brk"] == 5 * 60000)

    # the week doc carries it, and only while it lasts
    store = world({"sam": "Sammy"})
    sam = new_client(store, "sam", "Sammy")
    labels = [(TODAY - datetime.timedelta(days=i)).isoformat() for i in range(7)]
    now = datetime.datetime.now(utc)
    live_room = rm.make_room("sam", now - datetime.timedelta(minutes=10))
    week = lambda: json.loads(store.weeks["sam"][0])
    sam.session["room"] = live_room
    sam.push(labels, {})
    check("week doc: my room rides it", week().get("room", {}).get("host") == "sam")
    sam.session["room"] = rm.make_room("sam", now - datetime.timedelta(hours=5))
    sam.push(labels, {})
    check("week doc: an ended room is gone from it", "room" not in week())
    sam.session["room"] = live_room
    sam.push(labels, {"paused": True})
    check("week doc: paused, no room", "room" not in week())

    # the glue: the break, and the shortcuts under it
    from due_crew import rooms
    from due_crew.app import _state
    evals, calls = [], []
    web = types.SimpleNamespace(eval=evals.append)
    fake_mw = rooms.mw
    saved = {k: getattr(fake_mw, k, None) for k in ("state", "reviewer", "toolbar", "clearStateShortcuts", "setStateShortcuts", "pm")}
    fake_mw.state = "review"
    timers, replays, syncs = [], [], []
    fake_card = types.SimpleNamespace(start_timer=lambda: timers.append(1))
    fake_mw.reviewer = types.SimpleNamespace(web=web, bottom=types.SimpleNamespace(web=web),
                                             _shortcutKeys=lambda: ["keys"], card=fake_card,
                                             replayAudio=lambda: replays.append(1))
    real_sync = rooms.app.sync
    rooms.app.sync = lambda **kw: syncs.append(kw)
    fake_mw.toolbar = types.SimpleNamespace(web=web)
    fake_mw.clearStateShortcuts = lambda: calls.append("clear")
    fake_mw.setStateShortcuts = lambda k: calls.append(("set", k))
    fake_mw.pm = types.SimpleNamespace(hide_top_bar=lambda: False, hide_bottom_bar=lambda: False)
    real_client = rooms.client
    fake_cl = types.SimpleNamespace(signed_in=True, session={"room": rm.make_room("dre", now - datetime.timedelta(minutes=26))},
                                    _save_session=lambda: None, rules_stale=False, user_id="me")
    rooms.client = lambda: fake_cl
    real_cfg = rooms.cfg
    rooms.cfg = lambda: {}
    _state.update(entries=entries, labels=labels, room_skip=None, room_break=False)
    try:
        _state["room_refreshed"] = None
        rooms.on_question(None)
        check("break: after a round, the next question gets the break, and the keys go quiet",
              _state["room_break"] and calls == ["clear"] and any("'break'" in e or '"break"' in e for e in evals))
        check("break: answering from the card's own page is dropped while it's up",
              rooms.swallow("ans") and rooms.swallow("ease3") and not rooms.swallow("edit"))
        # called as Anki 2.1.50+ calls the filter: ((proceed, ease), reviewer, card)
        check("break: reviewer_will_answer_card, called as Anki calls it, holds the answer",
              rooms.will_answer((True, 3), None, None) == (False, 3))
        check("break: one light refresh for the round, to learn who's in", syncs == [{"light": True, "fetch": True}])
        rooms._state["room_break"] = False
        rooms.on_question(None)
        check("break: and only one per round, however many cards pass", len(syncs) == 1)
        rooms.skip_break()
        check("break: skip brings the card and its keys back",
              not _state["room_break"] and calls[-1] == ("set", ["keys"]))
        check("break: the card's timer starts over and its audio plays, so the break isn't study time",
              timers == [1] and replays == [1])
        check("break: answering works again after it", not rooms.swallow("ans"))
        check("break: and the answer filter lets it through as it came",
              rooms.will_answer((True, 2), None, None) == (True, 2)
              and rooms.will_answer((False, 4), None, None) == (False, 4))
        evals.clear(); calls.clear()
        rooms.on_question(None)
        check("break: a skipped break doesn't come back on the next card", calls == [] and not _state["room_break"])
        fake_cl.session["room"] = rm.make_room("dre", now - datetime.timedelta(minutes=10))
        evals.clear()
        rooms.on_question(None)
        check("placement: top bar showing, the chip goes there and the margin card doesn't",
              any('"chip"' in e and '"title"' in e for e in evals)
              and any(e.endswith('})("gutter");') and "var D =" not in e for e in evals))
        syncs.clear()
        rooms.on_close()
        check("close: closing Anki leaves the room, and pushes that", "room" not in fake_cl.session
              and syncs == [{"light": True, "fetch": False}])
    finally:
        rooms.app.sync = real_sync
        rooms.client, rooms.cfg = real_client, real_cfg
        for k, v in saved.items():
            setattr(fake_mw, k, v)
        _state.update(entries=None, labels=[], room_break=False, room_skip=None)


def test_streak_phone_v2111():
    """2.11.1: a day studied only on the phone reaches the desktop when Anki
    syncs, often after the add-on's first count of the day. The streak and
    heatmap caches notice, and what was already counted is never lost."""
    from due_crew.stats import heatmap, held_streak
    from due_crew.stats.streak import StreakTracker
    at_noon = lambda d: int(datetime.datetime.combine(d, datetime.time(12)).timestamp() * 1000)
    # desktop on days 2..40 ago, the phone yesterday: not synced yet
    col = make_user_col([TODAY - datetime.timedelta(days=i) for i in range(2, 41)])
    q = StatsQueries(col)
    files = tempfile.mkdtemp()
    tracker = StreakTracker(q, files)
    check("phone: before the sync, yesterday looks like a day off", tracker.current() == 0)
    fakes.add_review(col.db.conn, at_noon(TODAY - datetime.timedelta(days=1)))   # Anki syncs
    check("phone: once the sync brings yesterday in, the same day's count is the whole run",
          StreakTracker(q, files).current() == 40)
    fakes.add_review(col.db.conn, at_noon(TODAY))
    check("phone: today counts on top", StreakTracker(q, files).current() == 41)
    calls = []
    real_scan = StreakTracker._base_through_yesterday
    StreakTracker._base_through_yesterday = lambda self: calls.append(1) or real_scan(self)
    try:
        StreakTracker(q, files).current()
    finally:
        StreakTracker._base_through_yesterday = real_scan
    check("phone: with the gap still empty, a later sync doesn't rescan", calls == [])

    # the next day, yesterday's reviews are gone (a full sync that pulled an
    # older collection): the 41 counted yesterday stands
    col.db.conn.execute("DELETE FROM revlog WHERE id >= ?", (at_noon(TODAY) - 3600000,))
    col.sched.day_cutoff += 86400
    q2 = StatsQueries(col)
    check("floor: a run counted yesterday isn't shortened by a history that lost it",
          StreakTracker(q2, files).base() == 41)
    check("floor: only yesterday's count is kept; two days on, the history decides",
          (col.sched.__setattr__("day_cutoff", col.sched.day_cutoff + 86400) or True)
          and StreakTracker(StatsQueries(col), files).base() == 0)

    # heatmap: phone days older than yesterday used to stay missing all day
    col = make_user_col([TODAY - datetime.timedelta(days=i) for i in range(6, 100)])
    q = StatsQueries(col)
    files = tempfile.mkdtemp()
    heatmap(q, files, 182)
    for i in (5, 4, 3):
        fakes.add_review(col.db.conn, at_noon(TODAY - datetime.timedelta(days=i)))
    check("heatmap: a sync that brings older phone days in is counted the same day",
          heatmap(q, files, 182) == q.heatmap_counts(182) and q.day_label(4) in heatmap(q, files, 182))
    check("heatmap: the settled-days check counts exactly what the cache keeps",
          q.answers_in_days(2, 182) == sum(n for lb, n in q.heatmap_counts(182).items()
                                            if lb < q.day_label(1)))

    # before Anki's first sync, the streak sent to the crew doesn't drop
    own = {"2026-09-20": {"streak": 12}, "2026-09-22": {"streak": 40}}
    check("held: before the sync, a short count doesn't replace the 40 last sent",
          held_streak(0, own, "2026-09-24") == 40)
    check("held: a longer count goes out as is", held_streak(43, own, "2026-09-24") == 43)
    check("held: nothing sent yet, or junk, leaves the count alone",
          held_streak(3, {}, "2026-09-24") == 3 and held_streak(3, {"2026-09-22": {"streak": "x"}}, "2026-09-24") == 3)
    check("held: an upload from a later day (clock change) isn't the one held",
          held_streak(5, {"2026-09-30": {"streak": 90}}, "2026-09-24") == 5)


def test_streak_shortcut_v391():
    """3.9.1: the day after a day studied here, the streak's base is the run
    I saw yesterday when the day before it is still empty: no scan, and the
    answer 2.11.1's base (kept here) gives, scan and all. The phone filling
    that day late, a history that lost a day, a day off yesterday, later
    the same day, a run that isn't a number."""
    from due_crew.stats.streak import StreakTracker, _int

    def base_2111(t):
        today = t.q.day_label(0)
        cached = t._load()
        kept = 0
        if cached.get("date") == today:
            kept = _int(cached.get("base"))
            if t.q.reviews_for_day(kept + 1) == 0:
                return kept
        seen = cached.get("seen") if isinstance(cached.get("seen"), dict) else {}
        if seen.get("day") == t.q.day_label(1):
            kept = max(kept, _int(seen.get("run")))
        return max(t._base_through_yesterday(), kept)

    def case(agos, state):
        col = make_user_col([TODAY - datetime.timedelta(days=i) for i in agos])
        files = tempfile.mkdtemp()
        with open(os.path.join(files, "streak.json"), "w") as f:
            json.dump(state, f)
        t = StreakTracker(StatsQueries(col), files)
        want = base_2111(t)
        scans = []
        real = StreakTracker._base_through_yesterday
        StreakTracker._base_through_yesterday = lambda self: scans.append(1) or real(self)
        try:
            got = t.base()
        finally:
            StreakTracker._base_through_yesterday = real
        return got, want, len(scans), json.load(open(os.path.join(files, "streak.json")))

    lb = lambda i: (TODAY - datetime.timedelta(days=i)).isoformat()
    yday = {"date": lb(1), "base": 299, "seen": {"day": lb(1), "run": 300}}
    got, want, scans, saved = case(range(1, 301), yday)
    check("streak: the day after a day studied here, yesterday's run with the day before it empty is the base, unscanned",
          got == want == 300 and scans == 0 and saved["date"] == lb(0) and saved["base"] == 300, (got, want, scans))
    for name, agos, state, base in (
            ("the phone filled the day before the run late: scanned, the longer run", range(1, 321), yday, 320),
            ("a history that lost a day: the run I saw stands", [i for i in range(1, 301) if i != 150], yday, 300),
            ("a day off yesterday: yesterday's count was two days ago", range(2, 60),
             {"date": lb(2), "base": 57, "seen": {"day": lb(2), "run": 58}}, 0),
            ("later the same day", range(1, 301), dict(yday, date=lb(0), base=300), 300),
            ("a run that isn't a number", range(1, 301), dict(yday, seen={"day": lb(1), "run": "x"}), 300),
            ("nothing kept yet", range(1, 80), {}, 79)):
        got, want, scans, _ = case(agos, state)
        check(f"streak: {name}: the same base as 2.11.1's", got == want == base, (got, want, scans))


def test_main_thread_caches_v29():
    """2.9 (H5, H6): the per-sync SQL gets caches, and the Shared Decks
    dialog stops fingerprinting every deck. Each must give exactly what the
    uncached version gave."""
    from due_crew.stats import heatmap
    from due_crew.stats.streak import StreakTracker
    from due_crew.stats import decks as dk
    days = [TODAY - datetime.timedelta(days=i) for i in range(0, 200) if i % 5 != 3]
    col = make_user_col(days)
    q = StatsQueries(col)
    files = tempfile.mkdtemp()
    first = heatmap(q, files, 182)
    cached = json.load(open(os.path.join(files, "heatmap.json")))
    check("heatmap cache: the first call is the full query, and keeps only settled days",
          first == q.heatmap_counts(182) and q.day_label(0) not in cached["counts"]
          and q.day_label(1) not in cached["counts"] and q.day_label(2) in cached["counts"])
    noon = int(datetime.datetime.combine(TODAY, datetime.time(15)).timestamp() * 1000)
    fakes.add_review(col.db.conn, noon)
    check("heatmap cache: later the same day, today moves and the rest comes from the file",
          heatmap(q, files, 182) == q.heatmap_counts(182))

    for run in (3, 70, 150):
        c = make_user_col([TODAY - datetime.timedelta(days=i) for i in range(1, run + 1)])
        qq = StatsQueries(c)
        studied = qq.studied_days_ago()
        brute = 0
        while brute + 1 in studied:
            brute += 1
        got = StreakTracker(qq, tempfile.mkdtemp())._base_through_yesterday()
        check(f"streak: a {run}-day run through a widening window equals the full scan",
              got == brute == run, f"{got} {brute}")

    conn = sqlite3.connect(":memory:")
    fakes.make_collection(conn)
    for cid in range(1, 31):
        fakes.add_card(conn, cid, did=10 if cid <= 15 else 11)        # Big, Big::Sub
    for cid in range(31, 41):
        fakes.add_card(conn, cid, did=12)                             # Other
    big = fakes.FakeCol(conn, fakes.day_cutoff_for(TODAY))
    big.decks = fakes.FakeDecks({10: "Big", 11: "Big::Sub", 12: "Other"})
    names = {10: "Big", 11: "Big::Sub", 12: "Other"}
    crew = [{"user_id": "igk", "name": "igk", "you": False,
             "decks": [{"name": "Big", "sig": dk.deck_signature(big, 10)}]},
            {"user_id": "dre", "name": "Dre", "you": False,
             "decks": [{"name": "Sub", "sig": dk.deck_signature(big, 11)[:9]}]},
            {"user_id": "eve", "name": "Eve", "you": False,
             "decks": [{"name": "Elsewhere", "sig": [f"x{i}" for i in range(20)]}]}]
    brute = {did: dk.crew_matches(dk.deck_signature(big, did), crew) for did in names}
    brute = {did: who for did, who in brute.items() if who}
    got = dk.local_matches(big, crew, names)
    check("shared decks: matches found by lookup equal fingerprinting every deck",
          got == brute and got.get(10) == ["igk"] and "Dre" in got.get(11, []), f"{got} {brute}")
    calls = {"n": 0}
    real_all = big.db.all

    def counted(sql, *args):
        calls["n"] += "DISTINCT n.guid" in sql
        return real_all(sql, *args)
    big.db.all = counted
    dk.clear_cache()
    a = dk.deck_signature_cached(big, 10, TODAY.isoformat(), 30)
    b = dk.deck_signature_cached(big, 10, TODAY.isoformat(), 30)
    c = dk.deck_signature_cached(big, 10, TODAY.isoformat(), 31)
    check("fingerprint cache: one query per deck per day, again when its card count moves",
          a == b == c == dk.deck_signature(big, 10) and calls["n"] == 3, str(calls["n"]))
    big.db.all = real_all


def test_ways_in_v29():
    """2.9 (K4): the board's footer has a way into Settings, and your own
    card's Privacy… opens the Privacy tab (it landed on Account)."""
    labels = [TODAY.isoformat()]
    page = board.render({"entries": [], "labels": labels, "tomorrow": "", "pending": []}, {}, 0)
    foot = page[page.index('<div class="dc-foot">'):]
    check("ways in: Settings sits in the footer, after Refresh",
          ("duecrew:settings|" + KK + "')") in foot and foot.index("duecrew:refresh") < foot.index("duecrew:settings"))
    js = board.profile_overlay_js({"name": "Sammy", "you": True, "cells": None})
    check("ways in: your card's Privacy… opens Settings on Privacy",
          "duecrew:settings:privacy" in js)


def test_logo_accent():
    """2.10: the logo in the add-on is the kit's artwork, byte for byte,
    with only its fills swapped for the accent and theme."""
    from due_crew import logo
    here = os.path.join(REPO, "due_crew", "logo.svg")
    with open(here, "rb") as a, open(os.path.join(REPO, "docs", "logo", "svg", "due-crew-logo.svg"), "rb") as b:
        check("logo: the add-on's copy is the docs/logo original", a.read() == b.read())
    shapes = lambda s: re.sub(r'fill="#[0-9a-f]{6}"', 'fill=""', s)
    green = logo.svg("light", "green")
    check("logo: green in light is the original", green == open(here, encoding="utf-8").read())
    for name, shades in board.ACCENTS.items():
        for shade in ("light", "dark"):
            s = logo.svg(shade, name)
            pal = board.LIGHT if shade == "light" else board.DARK
            check(f"logo {name}/{shade}: six studied days in the accent, one off, the wordmark",
                  s.count(f'fill="{shades[shade][0]}"') == 6 and s.count(f'fill="{pal["line"]}"') == 1
                  and s.count(f'fill="{logo.WORDMARK[shade]}"') == 1)
            check(f"logo {name}/{shade}: only the fills change", shapes(s) == shapes(green))
    check("logo: an unknown accent falls back to green", logo.svg("light", "nope") == green)
    # the board's title is the one-line logo, coloured by the board's own tokens
    with open(os.path.join(REPO, "due_crew", "logo_line.svg"), "rb") as a, \
            open(os.path.join(REPO, "docs", "logo", "svg", "due-crew-logo-line.svg"), "rb") as b:
        check("logo: the board's one-line copy is the docs/logo original", a.read() == b.read())
    mark = logo.board_mark()
    check("board mark: six studied days, one off, the wordmark; no fixed colours",
          mark.count('class="on"') == 6 and mark.count('class="off"') == 1
          and mark.count('class="wm"') == 1 and "fill=" not in mark and 'aria-label="Due Crew"' in mark)
    css = board._css({"accent": "rose", "theme": "auto"})
    check("board mark: the CSS points it at the accent, line and mark tokens",
          ".dc-mark .on {{ fill: var(--dc-accent); }}".replace("{{", "{").replace("}}", "}") in css
          and "--dc-mark: #242424" in css and "--dc-mark: #e6e8e3" in css)
    check("board mark: tops the signed-out card, in place of the words",
          'class="dc-mark"' in board.signed_out_card({}) and "<b>Due Crew</b>" not in board.signed_out_card({}))


def test_together_v210():
    """2.10: studying now, tricky cards and tips, the good-luck card, the
    tiny plan, and the season. No new reads: all of it rides the week doc
    and cheers."""
    from due_crew import together
    from due_crew.app import _state
    wrapmod = _patched_due_crew()
    now = datetime.datetime.now(datetime.timezone.utc)
    store = world({"sam": "Sammy", "dre": "Dre"}, {"sam": ["dre"], "dre": ["sam"]})
    labels = [(TODAY - datetime.timedelta(days=i)).isoformat() for i in range(7)]
    tomorrow = (TODAY + datetime.timedelta(days=1)).isoformat()

    # L1 + L2 ride the week doc
    dre = new_client(store, "dre", "Dre")
    dre.session["live_until"] = (now + datetime.timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    dre.session["tricky"] = [{"guid": "guid000003", "text": "Heart sounds: S3 <b>", "deck": "Cardio",
                              "at": labels[0]}]
    sync_once(store, dre, make_user_col([TODAY]), tempfile.mkdtemp(), {}, TODAY)
    wk = json.loads(store.weeks["dre"][0])
    check("live + flags: the week doc carries liveUntil and the flagged card",
          "liveUntil" in wk and wk["tricky"][0]["guid"] == "guid000003")
    check("flags: the card's text never leaves this computer (3.0)",
          "Heart sounds" not in store.weeks["dre"][0] and "text" not in wk["tricky"][0])
    sam = new_client(store, "sam", "Sammy")
    data = sam.fetch_board(labels, tomorrow=tomorrow)
    d = next(e for e in data["entries"] if e["user_id"] == "dre")
    check("live + flags: a friend's refresh reads both, no extra reads",
          board.live_now(d["live_until"]) and d["tricky"][0]["guid"] == "guid000003")
    dre.session["live_until"] = (now - datetime.timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    sync_once(store, dre, make_user_col([TODAY]), tempfile.mkdtemp(), {}, TODAY)
    check("live: once the hour is up, the next push drops it",
          "liveUntil" not in json.loads(store.weeks["dre"][0]))

    rows = board.build_rows([dict(d, live_until=(now + datetime.timedelta(minutes=5)).isoformat())],
                            labels, tomorrow, "today", {})[0]
    html = board._row_html(rows[0], "#1", {})
    check("live: the row shows a dot and 'studying now'", "dc-live" in html and "studying now" in html)
    page = board.render({"entries": [], "labels": labels, "tomorrow": "", "pending": []}, {}, 0, live=False)
    stop = board.render({"entries": [], "labels": labels, "tomorrow": "", "pending": []}, {}, 0, live=True)
    check("3.9.10: the footer has no I'm studying (the dot shows by itself), whether I'm studying or not",
          "I&rsquo;m studying" not in page and "Stop studying" not in stop and "duecrew:live" not in page + stop)

    # L2: flags I share show on the Decks tab; tips go to the card
    col = make_user_col([TODAY])
    fakes.add_card(col.db.conn, 3, did=1)
    col.db.conn.execute("UPDATE notes SET flds = ? WHERE id = 3", ("Heart sounds: S3 <b>\x1fback",))
    sys.modules["aqt"].mw.col = col
    _state["entries"] = data["entries"]
    view = together.tricky_view()
    check("flags: only on notes I have, with who and where, the text from my own copy",
          [(v["uid"], v["index"], v["deck"], v["text"]) for v in view]
          == [("dre", 0, "Cardio", "Heart sounds: S3")], str(view))
    col2 = make_user_col([TODAY])
    sys.modules["aqt"].mw.col = col2
    check("flags: a card I don't have stays out of view", together.tricky_view() == [])
    sys.modules["aqt"].mw.col = None
    flags = board._tricky_html([dict(view[0], text="S3 <b>")])
    check("flags: escaped, with Tip wired, under Asked of you",
          "&lt;b&gt;" in flags and "tricktip:dre:0" in flags and "Asked of you" in flags and "Your asks" not in flags)
    mine = board._tricky_html([], [{"text": "K+ <i>", "state": "open", "who": ["Dre"]},
                                   {"text": "Digoxin", "state": "answered", "who": ["Priya <b>"]}])
    check("your asks (K3): where each stands, escaped, no Asked of you when nobody asked",
          "Your asks" in mine and "Asked of you" not in mine and "Dre knows this" in mine and "waiting" in mine
          and "Priya &lt;b&gt; answered" in mine and "1 tip" in mine and "<i>" not in mine)
    check("flags: a cloze shows as [...], never its answer",
          together._plain("<b>S3</b>&nbsp;is heard in {{c1::Kentucky::rhythm}}") == "S3 is heard in [\u2026]")

    # L3 + tips: cheers carry luck / guid
    check("luck: a line goes out marked", dre.send_cheer("sam", "\U0001F340", "Go get it", luck=True) is True
          and store.cheers[("sam", "dre")]["luck"] is True)
    got = sam.fetch_board(labels, tomorrow=tomorrow)["cheers"]
    check("luck: it arrives marked", got and got[0]["luck"] is True and got[0]["note"] == "Go get it")
    check("tips: a tip names its card", dre.send_cheer("sam", "\U0001F4A1", "Ken-tuck-y", guid="guid000003") is True
          and sam.fetch_board(labels, tomorrow=tomorrow)["cheers"][0]["guid"] == "guid000003")

    exam = (TODAY + datetime.timedelta(days=1)).isoformat()
    cheers = [{"from": "dre", "name": "Dre", "emoji": "\U0001F340", "note": "Go", "luck": True, "guid": ""},
              {"from": "eve", "name": "Eve", "emoji": "\U0001F4A1", "note": "S3 = Kentucky", "luck": False,
               "guid": "guid000003"},
              {"from": "kai", "name": "Kai", "emoji": "\U0001F389", "note": "", "luck": False, "guid": ""}]
    play, luck, tips = together.route_cheers(cheers, exam, TODAY.isoformat())
    check("routing: a luck line waits for the exam, a tip for its card, the rest play",
          [c["from"] for c in play] == ["kai"] and [c["from"] for c in luck] == ["dre"]
          and [c["from"] for c in tips] == ["eve"])
    play2, luck2, _t = together.route_cheers(cheers[:1], "", TODAY.isoformat())
    check("routing: with no exam ahead, a luck line plays as a cheer", play2 and not luck2)
    toasts = together.keep(luck, tips, exam, TODAY.isoformat())
    w = wrapmod._wrap_data()
    check("keeping: the line and the tip are held locally, and each says so",
          w["luck"]["exam"] == exam and w["luck"]["lines"][0]["note"] == "Go"
          and together.tips_for("guid000003") == [("Eve", "S3 = Kentucky")] and len(toasts) == 2)
    from due_crew import cards as crew_cards
    chip = crew_cards.chip_view(None, together.local_tips("guid000003"), {})
    check("tips: 3.5.0, K1, the tip's own words beside Edit, with This helped, never inside the card",
          chip["kind"] == "tip" and chip["text"] == "\U0001F4A1 Eve: S3 = Kentucky" and chip["title"] == "S3 = Kentucky"
          and chip["cmd"] == "knowstip" and chip.get("act") == "This helped"
          and chip.get("actcmd", "").startswith("knowshelped:") and "more" not in chip, str(chip))
    js = crew_cards.chip_js(dict(chip, accent="#0a0"))
    check("tips: This helped is its own click, the tip's words go in as text",
          "stopPropagation" in js and "duecrew:" in js and "textContent" in js and js.count("innerHTML") == 1 and "p.innerHTML = D.pip.svg" in js)
    from due_crew import room_model as rm
    check("bottom bar: the chip, a room beside Edit, and removing them keep the answer buttons centred",
          "dcBarBalance" in js and "dcBarBalance" in crew_cards.chip_js(None)
          and all("window.dcBarBalance()" in rm.widget_js(k, None) for k in ("bottom", "off"))
          and "window.dcBarBalance = function" in rm.BAR_BALANCE)
    check("bottom bar: our chip steps past a button another add-on draws over the bar",
          "position" in rm.BAR_BALANCE and "'absolute'" in rm.BAR_BALANCE and "marginLeft" in rm.BAR_BALANCE
          and "clear(chip)" in rm.BAR_BALANCE
          and "clear(document.getElementById('dc-room-bottom'))" in rm.BAR_BALANCE)
    kj = crew_cards.chip_js({"text": "x", "cmd": "knowsask", "act": "Ask", "accent": "#0a0"})
    check("bottom bar: the chip's words end in an ellipsis (never under its button); the answer buttons slide to the middle",
          "text-overflow:ellipsis" in kj and "flex:none" in kj and "s.title = D.title || D.text" in kj
          and "translateX(" in rm.BAR_BALANCE and ".style.width = side" not in rm.BAR_BALANCE
          and "data-short" in rm.BAR_BALANCE and "data-short" in kj and "data-full" in rm.BAR_BALANCE)
    check("bottom bar: beside More when there's room, else Edit's side; rebalanced when the bar changes, not by its own moves",
          "fits(r) ? r : fits(l) ? l" in rm.BAR_BALANCE and "MutationObserver" in rm.BAR_BALANCE
          and "n === chip" in rm.BAR_BALANCE and "chip.contains(x.target)" in rm.BAR_BALANCE)
    fj = crew_cards.float_js(dict(chip, accent=["#0a0", "#7c7"]))
    check("ask card: above the bar only while the corner is free, else back to the bar",
          "dc-knows-card" in fj and "knowsbar" in fj and "free()" in fj and "Not now" in fj
          and rm.CMD_KEY in fj and "textContent" in fj and fj.count("innerHTML") == 1 and "p.innerHTML = D.pip.svg" in fj
          and "bulb.innerHTML" not in fj  # 3.9.0, Sam's "2D": no lightbulb
          and "dc-knows-card" in crew_cards.float_js(None) and "dcKnowsOff(true)" in crew_cards.float_js(None)
          and len(crew_cards.float_js(None)) < 400 and len(crew_cards.chip_js(None)) < 300)  # 3.9.1: a remover, not the whole chip
    from due_crew import ui as _ui
    calls, asked = [], []
    real_toggle, real_ask = crew_cards.helped_toggle, _ui.confirm
    crew_cards.helped_toggle = calls.append
    real_tip = crew_cards._tip_from
    crew_cards._tip_from = lambda uid: {"name": "Eve Park", "helped": False, "from": uid}
    try:
        _ui.confirm = lambda parent, title, q, yes: asked.append(q) or False
        crew_cards.on_message("knowshelped", ["duecrew", "knowshelped", "eve"], from_card_page=True)
        no = list(calls)
        _ui.confirm = lambda parent, title, q, yes: asked.append(q) or True
        crew_cards.on_message("knowshelped", ["duecrew", "knowshelped", "eve"], from_card_page=True)
        crew_cards.on_message("knowshelped", ["duecrew", "knowshelped", "eve"])
    finally:
        crew_cards.helped_toggle, _ui.confirm, crew_cards._tip_from = real_toggle, real_ask, real_tip
    check("ask card: This helped from the review screen asks first; from the bar it doesn't",
          no == [] and calls == ["eve", "eve"] and len(asked) == 2 and "Eve" in asked[0], str((calls, asked)))
    old_style = crew_cards.chip_view(None, [("Eve", "S3 = Kentucky")], {})
    check("tips: a tip kept before 3.5.0 still shows, without This helped (no one to thank)",
          old_style["text"] == "\U0001F4A1 Eve: S3 = Kentucky" and "act" not in old_style)
    js = board.luck_card_js("Marisa", [("Dre", "</div><script>x</script>")])
    check("good-luck card: lines go in as text, and Thanks is wired",
          "textContent" in js and "innerHTML" not in js and "duecrew:luckthanks" in js
          and json.dumps("</div><script>x</script>")[1:-1] in js)
    eve = board.render({"entries": [], "labels": labels, "tomorrow": "", "pending": []}, {}, 0,
                       exam_eve={"people": [("m1", "Marisa")]})
    check("good-luck card: the eve banner asks for a line", "luckline:m1" in eve)

    # L4: the plan
    row = {"user_id": "a", "name": "Ann", "you": False, "paused": False, "quiet": False, "stale": False,
           "last_updated": "", "reviews": 140, "time_ms": 1, "retention": None, "streak": 1,
           "status": "200 cards, then bed"}
    doing = board._row_html(row, "#1", {"show_last_active": False})
    done = board._row_html(dict(row, reviews=205), "#1", {"show_last_active": False})
    plain = board._row_html(dict(row, reviews=None), "#1", {"show_last_active": False})
    check("plan: a number-led status fills in, then ticks; no numbers, no bar",
          "dc-plan" in doing and "140" in doing and "&#10003;" in done and "dc-plan" not in done
          and "dc-plan" not in plain and "&#10003;" not in plain)
    check("plan: only a leading number counts",
          board.plan_target("200 cards") == 200 and board.plan_target("cards: 200") is None
          and board.plan_target("0 today") is None)

    # L5: the season and the big streaks
    check("season: October is pumpkins, December snow",
          "\U0001F383" in board.season_emoji(datetime.date(2026, 10, 3))
          and "⛄" in board.season_emoji(datetime.date(2026, 12, 3)))
    js = board.flurry_js(["\U0001F389"], "Dre sent cheers", season=["\U0001F383"])
    check("season: flurries carry a sprinkle of it", json.dumps(["\U0001F389", "\U0001F389", "\U0001F383"]) in js)
    ban = board.render({"entries": [], "labels": labels, "tomorrow": "", "pending": []}, {}, 0,
                       milestones=[("dre", "Dre <b>", 100)])
    check("milestone: a 100-day streak gets a banner with a one-tap cheer",
          "Dre &lt;b&gt;" in ban and "milestonecheer:dre" in ban and "100-day streak" in ban)
    _state["entries"] = None


def test_row_cap():
    """2.7: past ten rows a view scrolls inside the card instead of growing
    the page, with the header pinned; a small crew is untouched. And the
    Decks tab no longer repeats "X shares Y" — the dialog shows that."""
    lb = TODAY.isoformat()
    mk = lambda n: [{"user_id": f"u{i}", "name": f"U{i}", "you": i == 0, "paused": False,
                     "last_updated": "", "exam_date": "",
                     "days": {lb: {"studied": True, "reviews": 900 - i}}, "decks": []}
                    for i in range(n)]
    base = {"labels": [lb], "tomorrow": "", "pending": []}
    small = board.render(dict(base, entries=mk(10)), {"period": "today"}, 0)
    big = board.render(dict(base, entries=mk(14)), {"period": "today"}, 0)
    check("cap: ten rows stand as before; eleven or more scroll inside the card",
          'class="dc-scroll"' not in small and 'class="dc-scroll"' in big
          and small.count("<tr class=") == 10 and big.count("<tr class=") == 14)
    check("cap: the header is pinned and given the card's fill, so rows slide under it",
          ".dc-scroll th { position: sticky" in big and "background: var(--dc-bg) !important" in big)
    check("cap: the box is about ten and a half rows tall, and follows compact mode",
          "max-height: 329px" in big
          and "max-height: 266px" in board.render(dict(base, entries=mk(14)), {"period": "today", "compact": True}, 0))
    sig = [f"g{i}" for i in range(10)]  # eight shared guids make a match
    decks = [{"name": "A", "sig": sig, "total": 10, "seen": 5, "mature": 2}]
    many = [dict(e, decks=decks) for e in mk(12)]
    d = board._decks_html(dict(base, entries=many))
    legend = '<div class="dc-line" style="padding-top: 2px;">'
    check("cap: the Decks tab scrolls its bars, legend outside the box",
          d.count('class="dc-scroll"') == 1 and d.count('class="dr') == 12
          and "</div></div>" + legend in d)
    few = board._decks_html(dict(base, entries=many[:3]))
    check("cap: three bars stand as before", "dc-scroll" not in few and "</div>" + legend in few)
    other = dict(mk(2)[1], decks=[{"name": "Only theirs", "sig": ["z"], "total": 5, "seen": 1, "mature": 0}])
    d2 = board._decks_html(dict(base, entries=[mk(1)[0], other]))
    check("decks: a deck only a friend shares is no longer announced on the tab",
          "shares" not in d2 and "open Shared decks" not in d2)
    rows = [{"user_id": f"s{i}", "name": f"S{i}", "day": lb, "reviews": 500 - i, "time_ms": 1000,
             "retention": 90.0, "streak": 3, "you": i == 12} for i in range(14)]
    view = {"state": "ok", "squads": [{"id": "x", "name": "orca"}], "current": "x", "name": "orca",
            "open": True, "founder_me": False, "rows": rows, "day": lb, "yesterday": "", "people": 14,
            "studying": 14, "reviews": 1}
    sq = board.render(dict(base, entries=mk(1)), {"period": "squads"}, 0, squad_view=view)
    check("cap: a squad table scrolls too, actions outside the box",
          'class="dc-scroll"' in sq and sq.index("Copy invite") > sq.index("dc-scroll"))
    js = board.keep_me_in_view_js()
    check("cap: after a render the you-row is scrolled into view, and only when it is out of view",
          "'#due-crew .dc-scroll'" in js and "tr.you" in js and ".dr.me" in js and "if (want > 0)" in js)


def test_show_up():
    """2.8: "Just show up" — share only that you studied, and see only that
    of others. Day docs and squad rows go numbers-free; the board becomes
    one view, a square per day; a show-up person reads as a check to the
    rest of the crew, counted but never ranked."""
    from due_crew import share
    lb = TODAY.isoformat()
    labels = [(TODAY - datetime.timedelta(days=i)).isoformat() for i in range(7)]
    store = world({"sam": "Sammy"})
    sam = new_client(store, "sam", "Sammy")
    values = {"reviews": 120, "studyTimeMs": 5000, "accuracy": 90.0, "streak": 4}
    doc = shapes.day_doc(values, {"show_up": True}, "hi")
    check("show-up: my day keeps studied and status, drops every number",
          doc.get("studied") is True and doc.get("status") == "hi"
          and not {"reviews", "studyTimeMs", "accuracy", "streak"} & set(doc))
    check("show-up: off, the toggles rule as before", shapes.day_doc(values, {"show_up": False})["reviews"] == 120)
    sam.session["week_raw"] = {lb: values}
    sam.push(labels, {"show_up": True})
    check("show-up: numbers already sent come off my week at the next sync",
          set(json.loads(store.weeks["sam"][0])["days"][lb]) == {"studied"})
    sid = sam.create_squad("orca")["id"]
    _row_sync(sam, {"name": "Sammy", "day": lb, "reviews": 500, "streak": 9}, [sid])
    _row_sync(sam, {"name": "Sammy", "week": 5, "day": lb}, [sid])
    m = store.members[(sid, "sam")]
    check("show-up: a numbers-free row clears the numbers that stood, and stays a member",
          m["reviews"] is None and m["streak"] is None and m["week"] == 5)

    def person(uid, name, you=False, numbers=True, studied=(), paused=False, away=None):
        days = {}
        for i in studied:
            days[labels[i]] = ({"studied": True, "reviews": 300 - 10 * i, "studyTimeMs": 100000,
                                "accuracy": 88.0, "streak": 3} if numbers else {"studied": True})
        if away is not None:
            days[labels[0]] = {"away": True, "awayTo": away}
        return {"user_id": uid, "name": name, "you": you, "paused": paused, "last_updated": "",
                "exam_date": "", "days": days, "decks": []}
    entries = [person("sam", "Sammy", you=True, studied=(0, 1, 2)),
               person("dre", "Dre", studied=(0, 1)),
               person("kai", "Kai", numbers=False, studied=(0, 2, 3)),
               person("nia", "Nia", numbers=False, studied=(1,)),
               person("pri", "Priya", studied=(1, 3), away="2026-09-06"),
               person("theo", "Theo", paused=True)]
    base = {"entries": entries, "labels": labels, "tomorrow": "", "pending": []}
    today = board.render(base, {"period": "today"}, 0)
    check("show-up rows, Today: a check in the name's line (3.9.10: no first column), after the ranked rows",
          '<td class="rk">&#10003;' not in today and '<span class="la faded">&#10003;' in today and today.index("Kai") > today.index("Dre")
          and '<td class="rk">#3</td>' not in today)
    week = board.render(base, {"period": "week"}, 0)
    check("show-up rows, Week: a check and the days this week, no rank (Nia studied Monday: she counts too)",
          "1 day this week" in week and week.count("&#10003;") == 2 and '<td class="rk">#3</td>' not in week)
    mode = board.render(base, {"period": "week", "show_up": True}, 0,
                        wrap={"reviews": 5, "time_ms": 1, "full_days": 5})
    check("mode: one crew pill, the week's totals banner gone, Share week offered, Share today not",
          ">Crew</a>" in mode and ">Today</a>" not in mode and ">Week</a>" not in mode
          and "Last week" not in mode
          and [k for _l, k in board.share_menu_items(True) if _l] == [
              "sharecrewweek", "pictureweek", "pictureyear", "picturealltime"])
    week_len = len(board.week_labels(labels))
    check("mode: a square per day Monday to today, today's letter marked, sorted by days then name",
          mode.count('class="sq on"') == 3 + 2 + 3 + 1 + 2 * 0 + 0  # per person within the calendar week
          if week_len >= 4 else True)
    check("mode: whoever studied today is counted, an away day is not; sorted by squares lit, then name",
          "3 showed up today" in mode and 'class="sqh on"' in mode
          # Nia has no doc today: a dim "yesterday" row after the live ones, as on the Today table
          and mode.index("Dre") < mode.index("Sammy") < mode.index("Kai") < mode.index("Priya") < mode.index("Nia"))
    check("mode: an away day is an outlined square and a note, a paused row stays dim",
          'class="sq away"' in mode and "&#9992;&#65039; back" in mode and "on a break" in mode)
    rows = [{"user_id": "a", "name": "Ann", "day": lb, "reviews": 500, "time_ms": 1000, "retention": 90.0, "streak": 3, "week": 4},
            {"user_id": "k", "name": "Kai", "day": lb, "reviews": None, "time_ms": None, "retention": None, "streak": None, "week": 5}]
    view = {"state": "ok", "squads": [{"id": "x", "name": "orca"}], "current": "x", "name": "orca",
            "open": True, "founder_me": False, "rows": rows, "day": lb, "yesterday": labels[1],
            "people": 2, "studying": 2, "reviews": 500}
    sq = board.render(base, {"period": "squads"}, 0, squad_view=view)
    sq_mode = board.render(base, {"period": "squads", "show_up": True}, 0, squad_view=view)
    check("squads: a show-up member is a check after the ranked rows, with their days",
          "#1" in sq and sq.count("&#10003;") == 1 and sq.index("Kai") > sq.index("Ann") and "5/7" in sq)
    check("squads in the mode: everyone is a check, days first, no numbers, no reviews together",
          sq_mode.count("&#10003;") == 2 and '<td class="rk">#1</td>' not in sq_mode and "showed up today" in sq_mode
          and "reviews together" not in sq_mode and sq_mode.index("Kai") < sq_mode.index("Ann"))
    card = board.stranger_card_js({"uid": "k", "name": "Kai", "reviews": None, "time_ms": None,
                                   "retention": None, "streak": None, "rank": None, "squad": "orca",
                                   "today": True, "week": 5})
    check("squadmate card for a show-up person: presence only",
          "showed up today" in card and "5/7 days this week" in card and "-day streak" not in card)
    txt = share.crew_week("orca", labels[::-1], [("Sammy", [True, False, True], "")], None, None)
    check("share: in the mode the crew week is squares alone, no totals line",
          "reviews" not in txt and "together" not in txt and "Sammy" in txt)
    js = board.stranger_card_js({"uid": "a", "name": "Ann", "reviews": 500, "time_ms": 1000,
                                 "retention": 90.0, "streak": 3, "rank": 1, "squad": "orca",
                                 "today": True, "week": 4, "show_up": True})
    check("squadmate card seen from the mode: their numbers stay out of sight",
          "showed up today" in js and "500" not in js and "-day streak" not in js)


def test_new_cards_v213():
    """2.13: under Reviews, how many were new cards: a card whose first
    answer ever was that day. A card seen before is a review, relearned or
    not. It goes out under the Reviews switch, never on its own."""
    from due_crew import share
    at = lambda d, h=12: int(datetime.datetime.combine(d, datetime.time(h)).timestamp() * 1000)
    conn = sqlite3.connect(":memory:")
    fakes.make_collection(conn)
    three_ago = TODAY - datetime.timedelta(days=3)
    fakes.add_review(conn, at(three_ago), cid=1)                  # first seen three days ago
    fakes.add_review(conn, at(TODAY, 9), ease=1, cid=1)           # relearned today
    fakes.add_review(conn, at(TODAY, 10), cid=1)
    fakes.add_review(conn, at(TODAY, 11), ease=1, cid=2)          # new today, twice
    fakes.add_review(conn, at(TODAY, 12), cid=2)
    fakes.add_review(conn, at(TODAY, 13), cid=3)                  # new today
    col = fakes.FakeCol(conn, fakes.day_cutoff_for(TODAY))
    q = StatsQueries(col)
    files = tempfile.mkdtemp()
    stats = gather_stats(col, files)
    check("new cards: first answered today, once each; a relearned card is a review",
          stats.reviews == 5 and stats.new_cards == 2, f"{stats.reviews} {stats.new_cards}")
    week = {d["label"]: d for d in gather_week(col, files)} if gather_week else {}
    check("new cards: each past day of the week carries its own count (today is upload_today's)",
          week.get(three_ago.isoformat(), {}).get("new_cards") == 1 and TODAY.isoformat() not in week)
    check("new cards: the week's count for Share week", sum(q.new_cards_by_day(7).values()) == 3)

    store = world({"sam": "Sammy"})
    sam = new_client(store, "sam", "Sammy")
    lb = TODAY.isoformat()
    values = {"reviews": 5, "studyTimeMs": 5000, "accuracy": 90.0, "streak": 4, "newCards": 2}
    on = shapes.day_doc(values, {})
    off = shapes.day_doc(values, {"share_reviews": False})
    up = shapes.day_doc(values, {"show_up": True})
    check("new cards: in my week with Reviews, gone without it or in show-up",
          on.get("newCards") == 2 and "newCards" not in off and "newCards" not in up)

    def ent(day):
        return {"user_id": "u", "name": "Nia", "you": False, "paused": False,
                "last_updated": "", "exam_date": "", "days": {lb: day}, "decks": []}
    base = {"labels": [lb], "tomorrow": "", "pending": []}
    # 3.4 review, T5: on the Week tab, where how much was new is the story
    some = board.render(dict(base, entries=[ent({"studied": True, "reviews": 205, "newCards": 12})]),
                        {"period": "week"}, 0)
    every = board.render(dict(base, entries=[ent({"studied": True, "reviews": 20, "newCards": 20})]),
                         {"period": "week"}, 0)
    none = board.render(dict(base, entries=[ent({"studied": True, "reviews": 20, "newCards": 0})]),
                        {"period": "week"}, 0)
    old = board.render(dict(base, entries=[ent({"studied": True, "reviews": 20})]), {"period": "week"}, 0)
    today_only = board.render(dict(base, entries=[ent({"studied": True, "reviews": 205, "newCards": 12})]),
                              {"period": "today"}, 0)
    check("board, T5: Today's rows are one line (no new line under Reviews)", 'class="nw"' not in today_only)
    check("board: a grey line under Reviews on the Week tab, with the whole count on hover",
          '<small class="nw">12 new</small>' in some and 'title="12 of 205 were new cards"' in some)
    check("board: \"all new\" when every review was new; nothing when none were or they didn't say",
          ">all new<" in every and 'class="nw"' not in none and 'class="nw"' not in old)
    mixed = board.render(dict(base, entries=[ent({"studied": True, "reviews": 205, "newCards": 12}),
                                             dict(ent({"studied": True, "reviews": 20, "newCards": 0}), uid="u2", name="Dre")]),
                         {"period": "week"}, 0)
    check("board: with one row showing new cards, the others hold half a line above and below, so rows match and the number stays level",
          mixed.count('class="nw"') == 1 and mixed.count('<small class="nwh"></small>') == 2 and "<!--nw-->" not in mixed
          and '<small class="nwh"></small>20<small class="nwh"></small>' in mixed
          and "<!--nw-->" not in none + today_only)
    wk = board._week_row({lb: {"reviews": 10, "newCards": 3},
                          (TODAY - datetime.timedelta(days=1)).isoformat(): {"reviews": 5, "newCards": 1}},
                         [lb, (TODAY - datetime.timedelta(days=1)).isoformat()])
    check("board: Week adds the days up", wk["new"] == 4 and wk["reviews"] == 15)

    # squad rows
    sid = sam.create_squad("orca")["id"]
    row = {"name": "Sammy", "day": lb, "reviews": 5, "newCards": 2}
    check("squad row: newCards lands", _row_sync(sam, row, [sid]) == (True, [])
          and store.members[(sid, "sam")]["newCards"] == 2)
    check("squad row: a negative count is refused", _row_sync(sam, dict(row, newCards=-1), [sid])[0] is False)
    drow = next(r for r in sam.fetch_squad(sid)["rows"] if r["user_id"] == "sam")
    check("squad row: read back as new_cards", drow["new_cards"] == 2)
    view = {"state": "ok", "squads": [{"id": sid, "name": "orca"}], "current": sid, "name": "orca",
            "open": True, "founder_me": True, "day": lb, "yesterday": "", "people": 1, "studying": 1,
            "reviews": 5, "rows": [dict(drow, you=True, crew=False, pending=False, knocked_me=False)]}
    sq = board.render(dict(base, entries=[]), {"period": "squads"}, 0, squad_view=view)
    check("squads: the same line under Reviews", '<small class="nw">2 new</small>' in sq)

    # the card and the shares
    check("card: Today line", board.today_text(205, 20) == "205 reviews (20 new)"
          and board.today_text(1, 1) == "1 review (all new)" and board.today_text(9, None) == "9 reviews")
    card = board.profile_overlay_js({"name": "Nia", "today": (205, 20), "cells": None, "last_active": ""})
    check("card: the profile says today's reviews and new cards", "Today: 205 reviews (20 new)" in card)
    t = share.my_today(lb, 205, 60000, 90.0, 3, 20)
    w = share.my_week([lb], [True], 205, 60000, 3, 205)
    check("share: (N new) after the reviews; (all new); none when none were",
          "205 reviews (20 new)" in t and "205 reviews (all new)" in w
          and "(" not in share.my_today(lb, 205, 60000, None, 3, 0).split("\n")[1])


def test_sign_in_v30():
    """3.0: an email, then the six-digit code it gets. A new address is a
    new account, asked for a name. Signing in again keeps what this
    computer knew about the account; another account starts clean. 3.8.0:
    what a 2.x session kept is cleared, and nothing is restored."""
    store = world({"sam": "Sammy"})
    tmp = tempfile.mkdtemp()
    cl = api.ApiClient(os.path.join(tmp, "session.json"))
    try:
        cl.request_code("nope")
        bad = None
    except shapes.AuthError as e:
        bad = e.code
    check("sign-in: a bad address is refused by name", bad == "bad_email")
    cl.request_code("  New@Example.com ")
    try:
        cl.verify_code("new@example.com", "000000")
        wrong = None
    except shapes.AuthError as e:
        wrong = e.code
    check("sign-in: a wrong code says so", wrong == "wrong_code")
    got = cl.verify_code("new@example.com", store.otp["new@example.com"], "Anki on Linux")
    check("sign-in: a new address is a new account, asked for a name",
          got["new"] is True and got["name"] == "" and cl.signed_in and cl.email == "new@example.com")
    check("sign-in: the name is set with the first request", cl.set_display_name("Newbie")
          and store.users[got["uid"]]["name"] == "Newbie" and cl.display_name == "Newbie")
    check("sign-out: here at once", (cl.sign_out(), cl.signed_in)[1] is False)

    # the same account signing in again keeps what it knew; a 2.x session's keys go
    old = api.ApiClient(os.path.join(tempfile.mkdtemp(), "session.json"))
    old.session = {"user_id": "sam", "email": "sam@example.com", "display_name": "Sammy",
                   "id_token": "x", "refresh_token": "r", "friend_ids": ["dre"], "cheers_seen": {"dre": "t"},
                   "needs_restore": True, "restored_to": "x"}
    check("an old session: signed out", not old.signed_in)
    old.request_code("sam@example.com")
    got = old.verify_code("sam@example.com", store.otp["sam@example.com"])
    check("the same account: the same uid, no name asked, what it knew is kept",
          got == {"uid": "sam", "name": "Sammy", "new": False} and old.session["cheers_seen"] == {"dre": "t"})
    check("3.8.0: nothing from 2.x is kept or restored",
          not any(k in old.session for k in ("refresh_token", "id_token", "needs_restore", "restored_to")))
    n = len(store.log)
    old.push([TODAY.isoformat()], {})
    check("3.8.0: the first sync is just a sync", [p for _m, p, _s in store.log[n:]] == ["/sync"], str(store.log[n:]))
    other = api.ApiClient(os.path.join(tempfile.mkdtemp(), "session.json"))
    other.session = {"user_id": "someone-else", "refresh_token": "r", "friend_ids": ["x"]}
    other.request_code("sam@example.com")
    other.verify_code("sam@example.com", store.otp["sam@example.com"])
    check("another account: nothing carries over", "friend_ids" not in other.session)


def test_tip_clears_flag_v301():
    """3.0.1: the first tip on a flagged card takes the flag down for the
    whole crew, and a sync before the tip is read doesn't put it back."""
    from due_crew import app as appmod, together
    from due_crew.app import _state
    store = world({"sam": "Sammy", "dre": "Dre", "nia": "Nia"},
                  {"sam": ["dre"], "dre": ["sam"], "nia": ["dre"]})
    labels = [(TODAY - datetime.timedelta(days=i)).isoformat() for i in range(7)]
    tomorrow = (TODAY + datetime.timedelta(days=1)).isoformat()
    dre = new_client(store, "dre", "Dre")
    sam = new_client(store, "sam", "Sammy")
    dre.session["tricky"] = [{"guid": g, "text": "S3", "deck": "Cardio", "at": labels[0]} for g in ("g1", "g2")]
    dre.push(labels, {})
    store.weeks["dre"] = (store.weeks["dre"][0], "2026-08-01T00:00:00Z")
    flags = lambda: [t["guid"] for t in json.loads(store.weeks["dre"][0]).get("tricky", [])]

    sam.send_cheer("dre", "\U0001F389", "go")
    check("tip: a plain cheer leaves the flags alone", flags() == ["g1", "g2"])
    n = len(store.log)
    sam.send_cheer("dre", together.TIP_EMOJI, "Ken-tuck-y", guid="g1")
    check("tip: the first tip takes that flag down, in the one request, and only that one",
          flags() == ["g2"] and len(store.log) == n + 1)
    check("tip: a tip isn't Dre studying: his last-active stays", store.weeks["dre"][1] == "2026-08-01T00:00:00Z")
    seen = sam.fetch_board(labels, tomorrow=tomorrow)["entries"]
    check("tip: the crew's next refresh has it gone",
          [t["guid"] for t in next(e for e in seen if e["user_id"] == "dre")["tricky"]] == ["g2"])

    dre.push(labels, {})
    check("race: Dre's sync before he's read the tip doesn't put the flag back", flags() == ["g2"])
    data = acked(dre, dre.fetch_board(labels, tomorrow=tomorrow))
    check("race: the tip is still his to read", [c["guid"] for c in data["cheers"]] == ["g1"])
    real = together.client
    together.client = lambda: dre
    try:
        together.forget_tipped(data["cheers"])
        check("arrival: the tipped flag leaves this computer too",
              [f["guid"] for f in dre.session["tricky"]] == ["g2"])
        dre.push(labels, {})
        check("arrival: and stays down once the tip is read", flags() == ["g2"])
        together.forget_tipped([{"from": "sam", "guid": "", "note": "hi"}])
        check("arrival: a cheer without a card changes nothing", len(dre.session["tricky"]) == 1)
    finally:
        together.client = real
    dre.fetch_board(labels, tomorrow=tomorrow)  # the next refresh says the tip arrived
    dre.session["tricky"].append({"guid": "g1", "deck": "Cardio", "at": labels[0]})
    dre.push(labels, {})
    check("re-flag: flagging it again is Dre's to do", flags() == ["g2", "g1"])

    # Dre added Nia, and Nia never added Dre back: his flags were never hers to see
    nia = new_client(store, "nia", "Nia")
    store.befriend("dre", "nia")
    store.friends.discard(("nia", "dre"))
    nia_ok = nia.send_cheer("dre", together.TIP_EMOJI, "x", guid="g2")
    check("tip: only someone the flag was shown to can take it down", nia_ok and flags() == ["g2", "g1"])

    _state["entries"] = [dict(e) for e in seen]
    swaps = []
    real_swap, real_cfg = appmod.swap, together.cfg
    appmod.swap, together.cfg = (lambda c: swaps.append(1)), (lambda: {})
    try:
        together.hide_tipped("dre", "g2")
        check("tipper: my board hides the flag at once, no request",
              next(e for e in _state["entries"] if e["user_id"] == "dre")["tricky"] == [] and swaps == [1])
    finally:
        appmod.swap, together.cfg = real_swap, real_cfg
        _state["entries"] = None


def test_mute_and_report_v301():
    """3.0.1: right-click a crewmate: Mute cheers (silent, follows the
    account) and Report… (mails us, stores nothing, and mutes)."""
    from due_crew import account, app as appmod, social
    from due_crew.app import _pending_cheers, _state
    row ={"user_id": "dre", "name": "Dre", "you": False, "paused": False, "quiet": False, "stale": False,
           "last_updated": "", "reviews": 5, "time_ms": 1, "retention": None, "streak": 1, "exam": ""}
    html = board._row_html(row, "#1", {})
    mine = board._row_html(dict(row, user_id="sam", you=True), "#2", {})
    check("menu: a right-click on a crewmate's name asks for the menu; never on my own",
          ('oncontextmenu="pycmd(\'duecrew:rowmenu:dre|' + KK + '\'); return false;"') in html and "rowmenu" not in mine)
    check("menu: the uid is the only thing that rides the command",
          "rowmenu:xscriptalert1script|" + KK + "'" in board._row_html(dict(row, user_id="x'<script>alert(1)</script>"), "#1", {}))

    cheers = [{"from": "dre", "emoji": "\U0001F389"}, {"from": "kai", "emoji": "\U0001F525"}]
    knocks = [("dre", "Dre", ""), ("kai", "Kai", "sq")]
    got = social.drop_muted(cheers, knocks, {"dre"})
    check("mute: their cheers and knocks are dropped on arrival, everyone else's land",
          [c["from"] for c in got[0]] == ["kai"] and [k[0] for k in got[1]] == ["kai"])
    check("mute: nobody muted, nothing dropped", social.drop_muted(cheers, knocks, set()) == (cheers, knocks))
    check("mute: follows the account",
          "muted" in account.ACCOUNT_KEYS and account.pick({"muted": ["dre"]})["muted"] == ["dre"]
          and account.clean({"muted": ["dre", 5, "", "dre", "x" * 200, "kai"]})["muted"] == ["dre", "kai"]
          and account.apply({"muted": []}, {"muted": ["kai"]})["muted"] == ["kai"])

    conf = {"muted": ["kai"]}
    saved, swaps = [], []
    real = (social.cfg, social.save_cfg, appmod.swap)
    social.cfg = lambda: conf
    social.save_cfg = lambda c: (saved.append(dict(c)), conf.update(c))
    appmod.swap = lambda c: swaps.append(1)
    _state["knocks"] = [("dre", "Dre", "")]
    _pending_cheers[:] = [{"from": "dre", "emoji": "x"}]
    try:
        social.set_muted("dre", True)
        check("mute: saved to the config (and so the account), and what's waiting from them goes",
              conf["muted"] == ["kai", "dre"] and saved and _state["knocks"] == [] and _pending_cheers == []
              and swaps == [1])
        social.set_muted("dre", False)
        check("unmute: off the list, the rest kept", conf["muted"] == ["kai"])
    finally:
        social.cfg, social.save_cfg, appmod.swap = real
        _state["knocks"] = []
        _pending_cheers.clear()

    store = world({"sam": "Sammy", "dre": "Dre"}, {"sam": ["dre"], "dre": ["sam"]})
    sam = new_client(store, "sam", "Sammy")
    dre = new_client(store, "dre", "Dre")
    dre.send_cheer("sam", "\U0001F525", "hi")
    n = len(store.log)
    ok = sam.report("dre", "cheers", "too   many")
    rep = store.reports[0] if store.reports else {}
    check("report: one request, with who, what and why",
          ok and len(store.log) == n + 1 and rep.get("reporter") == "sam" and rep.get("uid") == "dre"
          and rep.get("name") == "Dre" and rep.get("reason") == "cheers" and rep.get("note") == "too many"
          and rep.get("cheer", {}).get("note") == "hi")
    check("report: never the reporter's address", "sam@example.com" not in json.dumps(rep))
    check("report: dre isn't told, and stays crew", store.mutual("sam", "dre") and ("sam", "dre") in store.cheers)
    check("report: the dialog's reasons are the ones the server takes",
          [r[0] for r in shapes.REPORT_REASONS] == ["cheers", "name", "other"]
          and all(sam.report("dre", r[0]) for r in shapes.REPORT_REASONS))
    bodies = [b for _m, p, b in store.bodies if p == "/reports"]
    check("report: the note goes as one line, and only when there is one",
          bodies[0] == {"uid": "dre", "reason": "cheers", "note": "too many"}
          and bodies[1] == {"uid": "dre", "reason": "cheers"})
    check("report: a reason it doesn't know is refused", sam.report("dre", "spam") is False)
    for _ in range(6):
        sam.report("dre", "other")
    try:
        eleventh = sam.report("dre", "other")
    except shapes.TransportError as e:
        eleventh = e.status
    check("report: ten an hour", len(store.reports) == 10 and eleventh == 429)


def test_mute_on_the_server_v381():
    """3.8.1, the audit (#3, #10): mute is an account setting, and the server
    keeps it too, so the site never shows a muted person's cheer: it goes
    nowhere at send, one waiting from before is dropped as read, and their
    knocks aren't listed. Knocks have ceilings; reports are kept."""
    store = world({"sam": "Sammy", "dre": "Dre"}, {"sam": ["dre"], "dre": ["sam"]})
    sam = new_client(store, "sam", "Sammy")
    dre = new_client(store, "dre", "Dre")
    labels = [TODAY.isoformat()]
    sid = "sq1"
    store.members.update({(sid, "sam"): {}, (sid, "dre"): {}})
    dre.send_cheer("sam", "\U0001F525", "before")
    dre.send_knock("sam", sid)
    check("mute: put_settings carries it to the server", sam.put_settings("2026-10-13T10:00:00Z", {"muted": ["dre"]}))
    got = acked(sam, sam.fetch_board(labels))
    check("mute: one waiting from before isn't delivered, nor their knock", got["cheers"] == [] and got["knocks"] == [])
    acked(sam, sam.fetch_board(labels))
    check("mute: and the next read lets the cheer go", not any(k[0] == "sam" for k in store.cheers))
    dre.send_cheer("sam", "\U0001F389", "after")
    check("mute: a new one reads as sent and isn't kept", not any(k[0] == "sam" for k in store.cheers))
    sam.put_settings("2026-10-13T10:05:00Z", {"muted": []})
    check("unmute: the knock that was kept shows again",
          [k[0] for k in acked(sam, sam.fetch_board(labels))["knocks"]] == ["dre"])
    store.knocks.clear()  # dismissed
    check("knocks: reads as sent", dre.send_knock("sam", sid) is not False)
    check("knocks: one a day a pair: a dismissed one isn't back today", store.knocks == {})
    check("reports: kept", sam.report("dre", "other") and store.reports[-1]["uid"] == "dre")


def test_not_yet_today_is_unranked():
    """A crewmate who synced but hasn't studied yet isn't a row of zeros
    with a rank: dashes, no rank, under everyone who studied, "not yet
    today"; their status still shows. The same on Week and a squad board."""
    labels = ["2026-09-27", "2026-09-26", "2026-09-25", "2026-09-24", "2026-09-23", "2026-09-22", "2026-09-21"]
    def ent(uid, name, days, you=False):
        return {"user_id": uid, "name": name, "you": you, "paused": False, "last_updated": "2026-09-27T10:00:00Z",
                "exam_date": "", "days": days, "decks": []}
    zero = {"studied": False, "reviews": 0, "studyTimeMs": 0, "accuracy": 0.0, "streak": 0, "status": "coffee first"}
    data = {"entries": [ent("sam", "Sammy", {labels[0]: {"studied": True, "reviews": 50, "studyTimeMs": 600000}}, you=True),
                        ent("dre", "Dre", {labels[0]: dict(zero)}),
                        ent("kai", "Kai", {labels[0]: {"studied": True, "reviews": 10, "studyTimeMs": 60000}})],
            "labels": labels, "tomorrow": "2026-09-28", "pending": []}
    fresh, dormant = board.build_rows(data["entries"], labels, data["tomorrow"], "today", {})
    check("not yet: the studied are ranked, the zero isn't", [r["name"] for r in fresh] == ["Sammy", "Kai"]
          and [r["name"] for r in dormant] == ["Dre"] and dormant[0]["notyet"])
    page = board.render(data, {"period": "today"}, 0)
    row = page[page.index(">Dre<"):]
    row = row[:row.index("</tr>")]
    check("not yet: dashes, a note with when we last heard, the status, still cheerable; no zeros", "nothing yet as of" in row and "coffee first" in row
          and ">0<" not in row and "0.0%" not in row and "cheerpick:dre" in row)
    kai = page[:page.index(">Kai<")]
    check("not yet: Kai is above Dre by the order alone; no medals, no places, no dash (3.9.9, Sam: the design mocks' 2)",
          '<td class="rk"></td>' in kai[kai.rfind("<tr"):]
          and '<td class="rk"></td>' in page[page.rfind("<tr", 0, page.index(">Dre<")):page.index(">Dre<")]
          and not any(m in page for m in ("&#129351;", "&#129352;", "&#129353;")) and re.search(r'class="rk">#\d', page) is None
          and 'td.rk:empty {' in page and '<table class="dc-s-reviews">' in page)
    week = dict(data, entries=[data["entries"][0], ent("dre", "Dre", {lb: dict(zero) for lb in labels[:3]})])
    wf, wd = board.build_rows(week["entries"], labels, week["tomorrow"], "week", {})
    check("not yet: a week of zeros is unranked on Week", [r["name"] for r in wd] == ["Dre"] and wd[0]["notyet"]
          and "nothing this week" in board.render(week, {"period": "week"}, 0))
    view = {"state": "ok", "squads": [{"id": "s", "name": "S"}], "current": "s", "name": "S", "open": True,
            "rows": [{"user_id": "a", "name": "Ann", "day": labels[0], "reviews": 0, "time_ms": 0, "week": 3},
                     {"user_id": "b", "name": "Bo", "day": labels[0], "reviews": 9, "time_ms": 60000, "week": 4}],
            "day": labels[0], "yesterday": labels[1], "people": 2, "reviews": 9}
    sq = board._squads_html(view, {})
    check("not yet: on a squad board the zero is under the ranked, with dashes", sq.index(">Bo<") < sq.index(">Ann<")
          and re.search(r'class="rk">(#\d|&mdash;)', sq) is None and sq.count('<td class="rk"></td>') == 2  # 3.9.9: no places on Squads either
          and "nothing yet today" in sq and "1 studying today" in sq
          and 'h("td", { class: "rk" }, rank)' in open(os.path.join(REPO, "site", "public", "app.js"), encoding="utf-8").read()
          and "`#${++n}`" not in open(os.path.join(REPO, "site", "public", "app.js"), encoding="utf-8").read())


def test_ui_review_board():
    """3.4 review: one chip beside a name (T1), a colour means one thing
    (T2), one banner at a time (H6), one way in (C4), day one is the
    invite (C5), and a friend's card says since when."""
    base = {"user_id": "u", "name": "Dre", "you": False, "paused": False, "quiet": False, "stale": False,
            "last_updated": "2026-09-27T10:00:00Z", "reviews": 700, "time_ms": 1, "retention": 90.0, "streak": 3}
    busy = board._row_html(dict(base, live=True, exam="exam Fri", back=True, away="back Sep 6",
                                recap={"n": 2, "name": "P"}), "#2", {})
    check("T1: a busy day shows one chip, the most time-bound", "studying now" in busy
          and "exam Fri" not in busy and "back today" not in busy and "week 2 done" not in busy)
    exam = board._row_html(dict(base, exam="exam Fri", back=True), "#2", {})
    check("T1/T2: then an exam, in amber, and nothing else", '<span class="chip exam">exam Fri</span>' in exam and "back today" not in exam)
    check("T2: when they last synced leaves a row that's studying", '<span class="la' not in exam)
    quiet = board._row_html(dict(base, quiet=True, last_updated="2026-09-20T10:00:00Z"), "&mdash;", {})
    check("T2: a quiet row keeps it, in grey", '<span class="la faded">(' in quiet)
    away = board._row_html(dict(base, away="back Sep 6"), "#2", {})
    check("T1: away reads as away, in grey", '<span class="chip">away · back Sep 6</span>' in away)
    evil = board._row_html(dict(base, room="<b>x</b>'s room"), "#2", {})
    check("T1: a room's title is escaped", "&lt;b&gt;" in evil and "<b>x" not in evil)
    labels = ["2026-09-27"]
    data = {"entries": [], "labels": labels, "tomorrow": "", "pending": []}
    bans = board.render(data, {"period": "today"}, 0, wrap={"reviews": 5, "time_ms": 1},
                        exam_eve={"people": [("m", "Marisa")]}, knocks=[{"name": "Priya", "uid": "p"}])
    check("H6: the most time-bound banner shows, the others wait behind 1 of 3",
          bans.count('<div class="dc-wrap') == 1 and bans.count("<div hidden class=\"dc-wrap") == 2
          and "1 of 3 &rsaquo;" in bans and bans.index("exam is tomorrow") < bans.index("Priya"))
    one = board.render(data, {"period": "today"}, 0, wrap={"reviews": 5, "time_ms": 1})
    check("H6: one banner has no counter", "of 1" not in one and "&rsaquo;</a>" not in one)
    out = board.signed_out_card({})
    check("C4: one way in", "Start with your email" in out and ">Join<" not in out and "setup:" not in out)
    me = {"user_id": "sam", "name": "Sammy", "emoji": "", "you": True, "paused": False, "last_updated": "",
          "exam_date": "", "days": {labels[0]: {"studied": True, "reviews": 3}}, "decks": []}
    solo = board.render({"entries": [me], "labels": labels, "tomorrow": "", "pending": [], "my_code": "K7Q2ZP"},
                        {"period": "today"}, 0)
    check("C5: alone, the invite is the board", 'class="dc-empty"' in solo and "K7Q2 ZP" in solo
          and "copyinvite" in solo and "duecrew:addcode:" in solo)
    waiting = board.render({"entries": [me], "labels": labels, "tomorrow": "", "pending": ["Sam <b>"], "my_code": "K7Q2ZP"},
                           {"period": "today"}, 0)
    check("3.5.0: alone, it names who I'm waiting on, escaped; the box takes any code, whole",
          "Waiting for Sam &lt;b&gt; to add you back." in waiting and "[^A-Z0-9 \\/]" in waiting and "{6}" not in waiting)
    from due_crew.backend.shapes import friend_code_from, long_code_from
    plan_invite = "Follow MS2 Block 1 on Due Crew \u00b7 code N4AP ULM2"
    check("3.5.0: a plan's code or invite is no friend code, and reads as the 8-character code",
          friend_code_from(plan_invite) == "" and long_code_from(plan_invite) == "N4APULM2"
          and long_code_from("n4ap-ulm2") == "N4APULM2" and long_code_from("K7Q2ZP") == ""
          and friend_code_from("STUDY WITH ME CODE K7Q2ZP") == "K7Q2ZP")
    card = board.profile_overlay_js({"name": "Dre", "you": False, "cells": [1, 0], "same_days": 42, "start": "2026-04-06"})
    check("card: the days in common, since the month the heatmap starts", "42 days</b> since April" in card, card[-400:])


def test_invite_link_v341():
    """3.5.0, option B: Copy invite makes a one-time link; whoever pastes it
    is crew with its maker at once, both edges. One use. A friend code in
    the same link still adds, and the other adds back."""
    from due_crew.backend.shapes import friend_code_from, invite_code_from, long_code_from
    from due_crew.share import friend_invite
    store = world({"sam": "Sam", "priya": "Priya", "kai": "Kai"})
    sam, priya, kai = (new_client(store, u) for u in ("sam", "priya", "kai"))
    invite = sam.create_invite()
    text = friend_invite(invite)
    check("invite: one line and a link, the code in it",
          text == f"Study with me on Due Crew: duecrew.com/i/{invite}" and "\n" not in text, text)
    # the board's box sends the paste as capitals, with / kept
    pasted = re.sub(r"[^A-Z0-9 /]", " ", text.upper())
    check("invite: read from the link, a paste or typed; never a friend, plan or squad code",
          invite_code_from(text) == invite == invite_code_from(pasted)
          and invite_code_from(f"{invite[:5]} {invite[5:]}".lower()) == invite
          and friend_code_from(text) == "" and long_code_from(text) == ""
          and invite_code_from("SAM123") == "")
    friend, err = priya.redeem_invite(pasted)
    check("invite: pasting it makes us crew at once, both edges, no knock",
          err is None and friend["user_id"] == "sam" and friend["mutual"]
          and ("sam", "priya") in store.friends and ("priya", "sam") in store.friends
          and not store.knocks, (friend, err))
    late, err = kai.redeem_invite(invite)
    check("invite: once only; after that it adds and knocks (a group chat); my own says so",
          err is None and late["knocked"] and not late["mutual"] and ("sam", "kai") not in store.friends
          and ("sam", "kai") in store.knocks
          and sam.redeem_invite(sam.create_invite())[1] == "That's your own invite.", (late, err))
    store.friends.discard(("kai", "sam"))
    store.knocks.clear()
    # offline, Copy invite falls back to my friend code in the same link
    code = store.users["sam"]["code"] or sam.ensure_friend_code(None)
    link = friend_invite(code)
    check("invite: a friend code's link still adds (then Add back)",
          friend_code_from(link) == code and invite_code_from(link) == ""
          and kai.add_friend(friend_code_from(link))[0]["knocked"], link)


def test_settings_in_board_v341():
    """3.5.0 (mock "Settings in the Board"): Settings in the board's place,
    one command per change, the same keys and rules as the dialog."""
    from due_crew import account
    check("settings: the accent follows the account (the site wears it); only an accent's name",
          "accent" in account.ACCOUNT_KEYS and account.clean({"accent": "rose"}) == {"accent": "rose"}
          and account.clean({"accent": "</style>"}) == {} and account.pick({"accent": "teal"})["accent"] == "teal")
    from due_crew.settings_model import change
    day = datetime.date(2026, 9, 28)
    cfg = {"hidden_tabs": ["squads"], "exam_date": "", "away_from": "", "away_to": ""}
    check("settings: a switch, a choice, only values it takes",
          change(["set", "calm", "1"], cfg) == {"calm": True}
          and change(["set", "accent", "rose"], cfg) == {"accent": "rose"}
          and change(["set", "accent", "red"], cfg) is None
          and change(["set", "api_base", "1"], cfg) is None
          and change(["set", "calm", "yes"], cfg) is None)
    check("settings: tabs hide and show; Today isn't one of them",
          change(["settabs", "plans", "0"], cfg) == {"hidden_tabs": ["squads", "plans"]}
          and change(["settabs", "squads", "1"], cfg) == {"hidden_tabs": []}
          and change(["settabs", "today", "0"], cfg) is None)
    check("settings: privacy is one of three, and the numbers keep their switches",
          change(["setprivacy", "showup"], cfg) == {"show_up": True, "paused": False}
          and change(["setprivacy", "paused"], cfg) == {"show_up": False, "paused": True}
          and change(["setprivacy", "numbers"], cfg) == {"show_up": False, "paused": False})
    check("settings: the exam on (a week out), a date, off; nonsense is nothing",
          change(["setexam", "on"], cfg, today=day) == {"exam_date": "2026-10-05"}
          and change(["setexam", "2026-11-02"], cfg, today=day) == {"exam_date": "2026-11-02"}
          and change(["setexam", "off"], {"exam_date": "2026-11-02"}, today=day) == {"exam_date": ""}  # (its own day: not passed yet)
          and change(["setexam", "soon"], cfg, today=day) is None)
    check("settings: away on (tomorrow to a week), dates in either order, off",
          change(["setaway", "on"], cfg, today=day) == {"away_from": "2026-09-29", "away_to": "2026-10-05"}
          and change(["setaway", "2026-10-09", "2026-10-02"], cfg) == {"away_from": "2026-10-02", "away_to": "2026-10-09"}
          and change(["setaway", "off"], cfg) == {"away_from": "", "away_to": ""}
          and change(["setaway", "2026-10-02", ""], cfg) is None)
    check("settings: the crew name, decoded, one line, 24 at most; empty is Crew",
          change(["setlabel", "Block%203%3A%20us"], cfg) == {"crew_label": "Block 3: us"}
          and len(change(["setlabel", "x" * 60], cfg)["crew_label"]) == 24
          and change(["setlabel", "%20"], cfg) == {"crew_label": "Crew"})
    reset = change(["setreset"], cfg)
    check("settings: Reset board puts the Board tab back, never Privacy",
          reset["hidden_tabs"] == [] and reset["accent"] == "green"
          and not any(k.startswith("share_") or k in ("show_up", "paused", "exam_date") for k in reset))
    view = {"tab": "you", "signed_in": True, "name": "Sam <b>", "emoji": "🦊", "status": 'coffee "&" cards',
            "sync": "sam@x.edu · Synced 2m ago · v3.5.0", "crew": 3, "squads": ["<i>ORCA</i>", "Block 3", "Lab"],
            "decks": ["Big Deck"]}
    you = board.settings_html(view, {"crew_label": "Crew"})
    check("settings: You, escaped; three squads read as two and 1 more",
          'id="due-crew"' in you and "Sam &lt;b&gt;" in you and "&lt;i&gt;ORCA&lt;/i&gt;, Block 3 and 1 more" in you
          and "coffee &quot;&amp;&quot; cards" in you and "3 in your crew" in you and "<i>ORCA" not in you
          and "duecrew:setclose" in you and "Delete account" in you, you[-600:])
    bd = board.settings_html(dict(view, tab="board"), {"crew_label": 'a"><script>', "accent": "teal",
                                                         "hidden_tabs": ["decks"], "calm": False})
    check("settings: Board, its switches and tabs as set; the crew's name has no row since 3.9.12",
          "<script>" not in bd and "Crew name in shares" not in bd
          and "duecrew:settabs:decks:1" in bd and "duecrew:settabs:plans:0" in bd
          and "settabs:week" not in bd
          and "duecrew:set:calm:1" in bd and 'aria-label="Teal" aria-pressed="true"' in bd)
    dated = {"show_up": True, "exam_date": "2026-10-14", "away_from": "", "away_to": "",
             "send_errs": False}  # 3.9.9's switch, off: its own test
    pv = board.settings_html(dict(view, tab="privacy"), dated)
    check("settings: Privacy, one choice checked; numbers only under My numbers",
          pv.count('role="radio" aria-checked="true"') == 1 and "duecrew:setprivacy:numbers" in pv
          and "share_reviews" not in pv, pv[-900:])
    # 3.9.9 (Settings by what it's about): my dates are on You, no longer under Privacy
    yo = board.settings_html(dict(view, tab="you", signed_in=True), dated)
    check("settings: You has my dates, exam on, away off; Privacy has none",
          '<div class="st-h">Your dates</div>' in yo and 'value="2026-10-14"' in yo and "duecrew:setexam:off" in yo
          and "duecrew:setaway:on" in yo and "setexam" not in pv and "setaway" not in pv, yo[-900:])
    out = board.settings_html({"tab": "nope", "signed_in": False}, {})
    check("settings: signed out, a way in; an unknown tab is You",
          "setsignin" in out and "follow your account" not in out)


def test_settings_messages_reach_the_panel():
    """3.5.0: the board's Settings clicks, sent as the board sends them
    (duecrew:settab:board), change the tab and the setting; routed through
    the add-on's own message handler, not only settings_model."""
    import due_crew as dc
    from aqt.deckbrowser import DeckBrowser
    if "aqt.reviewer" not in sys.modules:
        sys.modules["aqt.reviewer"] = types.SimpleNamespace(Reviewer=type("Reviewer", (), {}))
    conf = {"calm": False, "hidden_tabs": [], "accent": "green"}
    saved = (dc._swap, dc.cfg, dc.save_cfg)
    swaps = []
    dc._swap = lambda c, focus=None: swaps.append(focus)
    dc.cfg = lambda: conf
    dc.save_cfg = lambda c, **k: None
    try:
        send = lambda m: dc._on_js(False, as_board("duecrew:" + m), DeckBrowser())
        send("settab:board")
        tab = dc._state.get("settings_tab")
        send("set:calm:1")
        send("set:accent:rose")
        send("settabs:plans:0")
        send("setclose")
        check("settings: the board's clicks reach it (a tab, a switch, a choice, a tab hidden, back)",
              tab == "board" and conf["calm"] is True and conf["accent"] == "rose"
              and conf["hidden_tabs"] == ["plans"] and dc._state.get("settings_tab") is None and len(swaps) == 5,
              (tab, conf, swaps))
    finally:
        dc._swap, dc.cfg, dc.save_cfg = saved
        dc._state["settings_tab"] = None


def test_every_board_command_has_a_handler():
    """Every duecrew: command the add-on puts on a page (the board, the
    bars, the chip, Settings) has a handler (3.5.0: Settings shipped with
    its clicks going nowhere). Prefix families (plan*, room*, knows*) go
    to their modules, which must handle the name itself."""
    import glob
    src = {p: open(p).read() for p in glob.glob(os.path.join(REPO, "due_crew", "**", "*.py"), recursive=True)}
    emitted = set()
    for path, text in src.items():
        if os.sep + os.path.join("planner", "web") in path:
            continue  # the HTML plan window's own bridge ("dcplan:"), tests/test_plan_web.py's
        for rx in (r'_pycmd\(\s*f?["\']([a-z]+)', r'_st_click\(\s*f?["\']([a-z]+)', r'duecrew:([a-z]+)',
                   r'"(?:cmd|actcmd)":\s*f?"([a-z]+)'):
            emitted |= set(re.findall(rx, text))
    import due_crew as dc
    handled = set(dc.BOARD_CMDS)  # 3.9.8: the Decks screen's, one table
    for name in ("__init__.py", "plan_flow.py", "rooms.py", "cards.py", "due_flow.py", "team_flow.py"):
        text = srcs.due_src(name)
        handled |= set(re.findall(r'cmd == "([a-z0-9]+)"', text)) | set(re.findall(r'message == "duecrew:([a-z0-9]+)"', text))
        for group in re.findall(r'cmd in \(([^)]*)\)', text):
            handled |= set(re.findall(r'"([a-z0-9]+)"', group))
    prefixes = {"plan", "room", "knows"}  # 'duecrew:' + a name built at run time
    missing = sorted(c for c in emitted - handled - prefixes)
    check("commands: every one the add-on emits has a handler", not missing and len(emitted) > 60, missing)
    families = [f for f, _ in dc._FAMILIES]
    check("commands (3.9.8, the table): no name in it starts as a family does (a family's module takes those), "
          "each line a count, a check or none, and what it does",
          not [n for n in dc.BOARD_CMDS if any(n.startswith(f) for f in families)]
          and all(isinstance(need, int) and (ok is None or callable(ok)) and callable(run)
                  for need, ok, run in dc.BOARD_CMDS.values()) and len(dc.BOARD_CMDS) > 80)
    check("commands (3.9.8, the table): a name it hasn't, or values that don't pass its check or count, is nothing",
          dc._board_cmd("nosuch", ["duecrew", "nosuch"]) is None
          and dc._board_cmd("sort", ["duecrew", "sort", "nonsense"]) is None
          and dc._board_cmd("sort", ["duecrew", "sort"]) is None
          and dc._board_cmd("sheet", ["duecrew", "sheet", "k"]) is None
          and dc._board_cmd("fridgemove", ["duecrew", "fridgemove", "a", "x", "1", "2"]) is None
          and dc._board_cmd("fridgemove", ["duecrew", "fridgemove", "a", "l", "-12", "40"]) is not None
          and dc._board_cmd("noticex", ["duecrew", "noticex", "7a"]) is None
          and dc._board_cmd("planopen", ["duecrew", "planopen"]) is not None)


def _takes(mod, fn, *args):
    """A family's chain (fn) with its module's own steps stood in for, so
    nothing runs but the choice: True when it took the command (said True)."""
    from unittest import mock
    saved = {k: v for k, v in vars(mod).items() if not k.startswith("__") and v is not fn and callable(v)
             and not isinstance(v, type) and str(getattr(v, "__module__", "") or "").startswith(("due_crew", "aqt"))}
    for k in saved:
        setattr(mod, k, lambda *a, **kw: mock.MagicMock())
    if "mw" in vars(mod):  # Anki with a collection open (the fake's has none)
        saved["mw"] = mod.mw
        mod.mw = mock.MagicMock()
    try:
        return fn(*args) is True
    except Exception:  # noqa: BLE001 (a branch it took, on the stand-ins)
        return True
    finally:
        for k, v in saved.items():
            setattr(mod, k, v)


def check_every_board_click_is_taken():
    """Run after every test (main): each command the board drew a control
    for anywhere in the suite (BOARD_DREW, as _pycmd leaves it), sent down
    the board's own route: _on_js's room and knows families, BOARD_CMDS'
    count and check, and a family's own chain (plan_flow, team_flow,
    due_flow, song_flow, leech_flow, habits_flow, the closet's, Wrapped's,
    Settings' and Pip Party's). A name having a handler isn't enough: a
    plan family's chain that falls through, or values its check refuses,
    is a control that does nothing (Sam, 7 Nov, in the plan windows: two
    yeses that sent nothing, each with a test that never pressed it).
    A family's own steps are stood in for, so nothing runs but the choice."""
    import due_crew as dc
    from due_crew import (closet, gamenight_flow, habits_flow, leech_flow, plan_flow, team_flow, due_flow, song_flow, rooms,
                          settings_model, cards as crew_cards)
    takes = _takes
    party_src = open(gamenight_flow.__file__, encoding="utf-8").read()  # party:<what>: the names its chain reads
    party = set(re.findall(r'what == "([a-z]+)"', party_src)) | {
        w for g in re.findall(r'what in \(([^)]*)\)', party_src) for w in re.findall(r'"([a-z]+)"', g)}

    def taken(msg):
        p = msg.split(":")
        cmd, arg = p[1], p[2] if len(p) > 2 else ""
        if cmd.startswith("room"):
            return takes(rooms, rooms.on_message, cmd, p)
        if cmd.startswith("knows"):
            return takes(crew_cards, crew_cards.on_message, cmd, p)
        if dc._board_cmd(cmd, p) is None:
            return False
        if cmd.startswith("planteam"):
            return takes(team_flow, team_flow.on_message, cmd, p)
        if cmd.startswith("plan"):
            return takes(plan_flow, plan_flow.on_message, cmd, p)
        if cmd.startswith("due"):
            return takes(due_flow, due_flow.on_message, cmd, p)
        if cmd.startswith("ins") or cmd == "youins":
            x = p[3] if len(p) > 3 else ""
            if not arg.isdigit():
                return False  # team_flow says True to a deck that isn't a number, and does nothing
            if cmd == "insleech":
                return takes(leech_flow, leech_flow.on_message, int(arg), x, p[4] if len(p) > 4 else "")
            if cmd == "inshabits":
                return takes(habits_flow, habits_flow.on_message, x)
            return takes(team_flow, team_flow.on_message, cmd, p)
        if cmd.startswith(("song", "dance")):
            return takes(song_flow, song_flow.on_message, cmd, p)
        if cmd.startswith("closet"):
            return cmd in ("closet", "closetnew", "closethw", "closetclose", "closetoff") or (cmd == "closetwear" and arg in closet.BY) \
                or (cmd == "closettab" and arg.isdigit() and int(arg) < len(board.CLOSET_TABS))
        if cmd.startswith("wrapped"):
            return cmd == "wrappedx" and arg.isdigit() and len(arg) == 4
        if cmd.startswith("scrap"):
            return cmd in ("scrapbook", "scrapclose", "scrapempty", "scrappin", "scrapdel") or (arg.isdigit() and len(arg) == 4)
        if cmd == "settab":
            return arg in settings_model.TABS
        if cmd in ("setclose", "setname", "setemoji", "setstatus", "setsquads", "setsignin", "setsignout", "setdelete", "setfeedback"):
            return True
        if cmd in dc.SETTINGS_CMDS:
            return bool(settings_model.change([cmd] + p[2:], {}))
        if cmd == "party":
            return arg in party
        return True  # a line of BOARD_CMDS: its count and check passed
    drew = dict(BOARD_DREW)  # as the suite left it (a route taken may draw the board again)
    lost = sorted((m, where) for m, where in drew.items() if not taken(m))
    check(f"commands: every click the board drew in this suite ({len(drew)} commands) is taken by its route: its family's chain, "
          "BOARD_CMDS' count and check; none falls through or is refused", len(drew) > 300 and not lost, lost[:8])


def test_every_widget_press_is_taken():
    """The bars' widgets (room_widget.js), run in node and pressed: every
    one, in each state it has (a crew room before, in a round and in its
    break; a fifteen in its round, at its question, in its break; ▶
    Fifteen? and the Fifteen at 35), every onclick and Enter it sets
    called, and whatever it sends on its own. Each message goes through
    _on_js's own gate (room_model.trusted) as the page it's on sends it:
    the margin, the break, the question and the room's card sit on the
    review screen, where a card's script runs and only CARD_PAGE_CMDS
    count; then rooms.on_message must take it. A button the gate drops
    would do nothing (3.8.1: ▶ Fifteen? clicked to nothing the same way)."""
    import shutil
    import subprocess
    from due_crew import room_model as rm, rooms
    node = shutil.which("node")
    if not node:
        print("SKIP the widgets pressed: no node")
        return
    now = datetime.datetime.now(datetime.timezone.utc)
    acc = board.accent_pair("green")
    ents = [{"user_id": "sam", "name": "Sammy", "you": True, "accent": "blue", "look": []},
            {"user_id": "dre", "name": "Dre", "you": False, "accent": "teal", "look": []}]
    before = rm.make_room("sam", now + datetime.timedelta(minutes=20))
    going = rm.make_room("sam", now - datetime.timedelta(minutes=3))
    resting = rm.make_room("sam", now - datetime.timedelta(minutes=27), 2, 25, 5)
    fif = rm.make_fifteen("sam", now - datetime.timedelta(minutes=3))
    asking = rm.make_fifteen("sam", now - datetime.timedelta(minutes=16))
    fbreak = dict(rm.make_fifteen("sam", now - datetime.timedelta(minutes=17)), rounds=2)
    review = ("gutter", "break", "ask", "card")  # on the review screen: a card's own page
    cases = [(k, room) for k in ("chip", "bottom", "gutter", "card") for room in (before, going, fif)]
    cases += [("break", resting), ("break", fbreak), ("ask", asking), ("start", None), ("start", "sit")]

    def data(kind, room):
        if kind == "start":
            return rm.start_data(acc, "right", True, nap=False, sit=35 if room == "sit" else 0)
        return rm.widget_data(room, [dict(e, room=room) for e in ents], acc, cards=12, total=40)
    dom = r"""
class Sty { constructor() { this.cssText = ''; } setProperty(k, v) { this[k] = v; } }
class E {
  constructor(tag) { this.tag = tag; this.kids = []; this.style = new Sty(); this.textContent = ''; this.title = ''; this.attrs = {};
    this.classList = { add() {}, remove() {}, contains() { return false; }, toggle() {} }; }
  appendChild(k) { this.kids.push(k); k.parentNode = this; return k; }
  insertBefore(k) { return this.appendChild(k); }
  set innerHTML(h) { this.html = h; this.kids = []; const m = /^<([a-z]+)/.exec(h); if (m) { this.kids.push(new E(m[1])); } }
  get firstChild() { return this.kids[0] || null; }
  get isConnected() { let p = this; while (p.parentNode) { p = p.parentNode; } return p === body; }
  setAttribute(k, v) { this.attrs[k] = v; } getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; } removeAttribute(k) { delete this.attrs[k]; }
  querySelectorAll() { return []; } querySelector() { return null; } addEventListener() {} removeEventListener() {}
  remove() { if (this.parentNode) { this.parentNode.kids = this.parentNode.kids.filter((x) => x !== this); this.parentNode = null; } }
  focus() {} blur() {} getBoundingClientRect() { return { left: 0, top: 0, width: 80, height: 26, right: 80, bottom: 26 }; }
  animate() { return { finished: Promise.resolve(), cancel() {} }; }
}
let body;
const walk = (e, out) => { out.push(e); e.kids.forEach((k) => walk(k, out)); return out; };
const sent = [];
function fresh() {
  body = new E('body'); body.className = '';
  globalThis.window = globalThis; window.addEventListener = () => {}; window.removeEventListener = () => {}; window.innerWidth = 1200; window.innerHeight = 800;
  globalThis.document = { body, head: new E('head'), createElement: (t) => new E(t), createRange: () => ({ selectNodeContents() {}, getBoundingClientRect: () => ({ width: 10 }) }),
    getElementById: (id) => walk(body, []).find((x) => x.id === id) || null, activeElement: null,
    querySelector: () => null, querySelectorAll: () => [], addEventListener() {}, removeEventListener() {}, documentElement: new E("html") };
  globalThis.setInterval = () => 0; globalThis.clearInterval = () => {}; globalThis.setTimeout = () => 0; globalThis.clearTimeout = () => {};
  globalThis.matchMedia = () => ({ matches: false, addEventListener() {} }); globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
  globalThis.localStorage = { getItem: () => null, setItem() {} }; globalThis.requestAnimationFrame = () => 0;
  globalThis.pycmd = (m) => sent.push(m);
  for (const k of Object.keys(globalThis)) { if (/^dc/.test(k)) { delete globalThis[k]; } }
  (0, eval)(PROG);
}
const ev = { stopPropagation() {}, preventDefault() {}, key: 'Enter', button: 0 };
fresh();
const drew = sent.splice(0);
const n = walk(body, []).filter((e) => typeof e.onclick === 'function' || typeof e.onkeydown === 'function').length;
const presses = [];
for (let i = 0; i < n; i++) {
  fresh(); sent.length = 0;
  const el = walk(body, []).filter((e) => typeof e.onclick === 'function' || typeof e.onkeydown === 'function')[i];
  try { if (typeof el.onclick === 'function') { el.onclick(ev); } else { el.onkeydown(ev); } presses.push([el.textContent || el.title || el.tag, sent.slice()]); }
  catch (e) { presses.push([el.textContent || el.tag, ['error: ' + e.message]]); }
}
console.log(JSON.stringify({ drew, presses, n }));
"""
    got = []
    for kind, room in cases:
        prog = rm.widget_js(kind, data(kind, room))
        run = subprocess.run([node, "-e", dom.replace("(0, eval)(PROG);", "(0, eval)(" + json.dumps(prog) + ");")],
                             capture_output=True, text=True, timeout=60)
        try:
            got.append((kind, room, json.loads(run.stdout)))
        except ValueError:
            got.append((kind, room, {"error": run.stdout[-300:] + run.stderr[-1500:]}))
    broke = [(k, o.get("error") or [p for p in o["presses"] if any(m.startswith("error") for m in p[1])]) for k, _r, o in got
             if o.get("error") or any(m.startswith("error") for p in o["presses"] for m in p[1])]
    check(f"widgets pressed: each of {len(cases)} drawn in node and every control in it pressed, without an error "
          f"({sum(o.get('n', 0) for _k, _r, o in got)} controls)", not broke and all(o.get("n") for _k, _r, o in got), broke[:3])
    dropped, missed, idle = [], [], []
    for kind, _room, o in got:
        for label, msgs in o.get("presses", []) + [("as it's drawn", o.get("drew", []))]:
            if not msgs and label != "as it's drawn":
                idle.append((kind, label))
            for m in msgs:
                body, ok = rm.trusted(m, kind in review)
                if not ok:
                    dropped.append((kind, label, m.split("|")[0]))
                    continue
                p = body.split(":")
                if not _takes(rooms, rooms.on_message, p[1], p):
                    missed.append((kind, label, body))
    check("widgets pressed: every message a press sends gets through the gate of the page it's on "
          "(the review screen's widgets send only CARD_PAGE_CMDS, keyed)", not dropped, dropped[:6])
    check("widgets pressed: rooms.on_message takes every one", not missed, missed[:6])
    check("widgets pressed: every control sends something", not idle, idle[:6])


def test_take_back_an_ask():
    """3.5.0: an open ask on the Decks tab has Take back; it leaves my flags."""
    html = board._tricky_html([], [{"text": "The external iliac <b>", "who": [], "state": "open", "index": 1},
                                   {"text": "x", "who": ["Maya"], "state": "answered"}])
    check("asks: an open one offers Take back by its place; an answered one doesn't; text escaped",
          html.count("Take back") == 1 and "duecrew:unask:1" in html and "&lt;b&gt;" in html, html)
    from due_crew import together, app as appmod
    today = together._today()
    cl = together.client()
    cl.session["tricky"] = [{"guid": "g1", "text": "a", "deck": "", "at": today},
                            {"guid": "g2", "text": "b", "deck": "", "at": today}]
    saved = (appmod.swap, appmod.sync)
    appmod.swap, appmod.sync = (lambda c: None), (lambda **k: None)
    try:
        together.unask(1)
        together.unask(9)  # gone already, or never there: nothing
        check("asks: Take back drops that one and keeps the rest",
              [f["guid"] for f in cl.session["tricky"]] == ["g1"], cl.session["tricky"])
    finally:
        appmod.swap, appmod.sync = saved
        cl.session["tricky"] = []


def test_settings_saves_in_order_v341():
    """3.5.0: Settings in the board saves on every click, and the server keeps
    whichever save arrives last. One save at a time: a click while one is on
    its way goes after it, as the config is then."""
    from due_crew import account, app as appmod
    sent, queue = [], []
    now = {"cfg": {"share_time": True, "share_reviews": True}}

    class Stub:
        signed_in = True
        session = {}

        def _save_session(self):
            pass

        def put_settings(self, at, settings):
            sent.append(dict(settings))
            return True
    saved = (account.client, account.cfg, appmod._bg)
    account.client, account.cfg = (lambda: Stub()), (lambda: now["cfg"])
    appmod._bg = lambda job, done=None: queue.append((job, done))
    try:
        now["cfg"] = {"share_time": False, "share_reviews": True}
        account.push(now["cfg"])
        now["cfg"] = {"share_time": False, "share_reviews": False}
        account.push(now["cfg"])
        now["cfg"] = {"share_time": True, "share_reviews": False}
        account.push(now["cfg"])
        check("settings saves: one on its way at a time", len(queue) == 1)
        job, done = queue.pop(0)
        done(job())
        check("settings saves: the clicks meanwhile go as one save, of the config as it is now",
              len(queue) == 1)
        job, done = queue.pop(0)
        done(job())
        check("settings saves: two in all, in order, the last one the latest",
              [x["share_time"] for x in sent] == [False, True] and sent[-1]["share_reviews"] is False
              and not queue, sent)
    finally:
        account.client, account.cfg, appmod._bg = saved
        account._pushing.update(busy=False, again=False)


def test_retry_only_what_is_safe_twice():
    """Review: a request that fails is sent once more only when sending it
    twice can't do a thing twice. A POST that may have landed (a new squad)
    isn't repeated; a read, a sync, or one that never got out is."""
    store = world({"maya": "Maya"})
    cl = new_client(store, "maya", "Maya")
    for down, method, path, want in ((True, "POST", "/squads", 1), (True, "GET", "/friends", 2),
                                     (True, "POST", "/sync", 2), ("connect", "POST", "/squads", 2)):
        store.down, store.tries = down, 0
        try:
            cl._call(method, path, {"name": "x"} if method == "POST" else None)
        except shapes.TransportError:
            pass
        check(f"retry: {method} {path} ({'never sent' if down == 'connect' else 'may have landed'}) tried {want}x",
              store.tries == want, str(store.tries))
    store.down = False


def test_room_commands_from_the_card_page_need_the_key():
    """Review: the reviewer's page runs the card's own script too. From
    there a bare duecrew: command (a card cheering the room, joining or
    leaving it) is dropped; the room widget's own buttons carry a key that
    lives only in its script. The board and the bars need no key."""
    from due_crew import room_model as rm
    js = rm.widget_js("break", {"title": "x"})
    check("room: the widget's commands carry this run's key", rm.CMD_KEY in js and "'|'" in js)
    check("room: a keyed command from the card page counts, without its key",
          rm.trusted(f"duecrew:roomcheer|{rm.CMD_KEY}", True) == ("duecrew:roomcheer", True))
    check("room: a bare one from the card page doesn't", rm.trusted("duecrew:roomcheer", True)[1] is False)
    check("room: a wrong key doesn't either", rm.trusted("duecrew:roomleave|0000", True)[1] is False)
    check("room: the board's commands need none", rm.trusted("duecrew:roomjoin:abc:1", False) == ("duecrew:roomjoin:abc:1", True))
    check("room: from the card page, even keyed, nothing but the widget's own",
          rm.trusted(f"duecrew:roomjoin:abc|{rm.CMD_KEY}", True)[1] is False
          and rm.trusted(f"duecrew:cheerpick:u|{rm.CMD_KEY}", True)[1] is False)
    check("room: the Ask card's keyed clicks count from the card page, bare ones don't",
          rm.trusted(f"duecrew:knowsask|{rm.CMD_KEY}", True) == ("duecrew:knowsask", True)
          and rm.trusted("duecrew:knowshelped:u", True)[1] is False)


def test_room_card_pops_out_on_the_chips_side_v381():
    """3.8.1 (Sam): the room's card opened on the right even with the chip on
    the left. It opens at the chip's end, the chip hides while it's out and
    comes back when it closes (×, a click outside, Tuck, Leave, or the page
    going away), and it moves by its top row, remembered on that side."""
    import due_crew as dc
    from aqt.deckbrowser import DeckBrowser
    from due_crew import room_model as rm, rooms as R
    from due_crew.app import _state
    left = rm.widget_js("card", {"title": "x", "side": "left", "rounds": 2, "round": 25, "brk": 5, "start": 0,
                                 "names": [], "line": "", "accent": ["#2e7d32", "#81c784"]})
    right = rm.widget_js("card", {"title": "x", "side": "right"})
    check("card: at the chip's end, the left one too", "position:fixed;left:12px;top:10px" in left
          and "position:fixed;right:12px;top:10px" in right)
    check("card: closing it says so (the chip comes back), keyed, and that's one of the widget's own",
          "send('roomcardoff')" in left and "roomcardoff" in rm.CARD_PAGE_CMDS)
    check("card: moves by its top row, kept on screen, remembered for that side",
          "Drag to move" in left and "dcRoomCardAt" in left and "at.side === D.side" in left and "innerWidth - w - 4" in left)
    evals, saved = [], (R._webs, R._eval, R.my_room, R.cfg, R._where, R._card_web, R.room_model.widget_data, R._tweak)
    tops = types.SimpleNamespace(name="top")
    main = types.SimpleNamespace(name="main", evalWithCallback=lambda js, cb: cb(False))
    try:
        R._webs = lambda: (tops, None, None)
        R._eval = R._tweak = lambda web, js: evals.append((getattr(web, "name", None), js))
        R.my_room = lambda: {"host": "sam"}
        R.cfg = lambda: {"room_chip_side": "left"}
        R._where = lambda: "chip"
        R._card_web = lambda: main
        sides = []
        R.room_model.widget_data = lambda room, entries, acc, compact=False, side="right", **kw: (sides.append(side), {"side": side})[1]
        R.show_card()
        hid = [js for w, js in evals if w == "top" and "dc-room-chip" in js]
        check("card: popped out on the chip's side; the chip hides", sides == ["left"] and hid and "'hidden'" in hid[-1]
              and _state["room_card"] == "chip", str(sides))
        evals.clear()
        dc._on_js(False, as_board("duecrew:roomcardoff"), DeckBrowser())
        back = [js for w, js in evals if w == "top" and "dc-room-chip" in js]
        check("card: closed (through _on_js, as the card sends it), the chip is back",
              back and "visibility=''" in back[-1] and _state["room_card"] is None, str(back))
        R.show_card()
        evals.clear()
        R._card_still_out("chip")  # a redraw finds the page went away with the card
        check("card: a page that went away took the card: the chip comes back",
              _state["room_card"] is None and "visibility=''" in [js for w, js in evals if w == "top"][-1])
        R._where = lambda: "bottom"
        sides.clear()
        R.show_card()
        check("card: from the review bar's little one it opens at the right, and that one hides",
              sides == ["right"] and _state["room_card"] == "bottom")
    finally:
        R._webs, R._eval, R.my_room, R.cfg, R._where, R._card_web, R.room_model.widget_data, R._tweak = saved
        _state["room_card"] = None

def test_only_our_pages_act_bare():
    """3.7.1 review: a card's own script runs in the browser's preview and
    in Cards… too, not only on the review screen. Only the pages Due Crew
    draws on (Decks, Overview, the top bar, the reviewer's bottom bar) send
    bare commands; from anywhere else a room or card command needs the key."""
    import due_crew as dc
    from aqt.deckbrowser import DeckBrowser
    if "aqt.reviewer" not in sys.modules:
        sys.modules["aqt.reviewer"] = types.SimpleNamespace(Reviewer=type("Reviewer", (), {}))
    from due_crew import rooms as R, cards as CC, room_model as rm
    got, saved = [], (R.on_message, CC.on_message)
    R.on_message = lambda cmd, parts: (got.append(cmd), True)[1]
    CC.on_message = lambda cmd, parts: got.append(cmd)
    Previewer = type("Previewer", (), {})
    try:
        dc._on_js(False, "duecrew:roomcheer", Previewer())
        dc._on_js(False, "duecrew:knowshelped:sam", Previewer())
        dc._on_js(False, f"duecrew:roomcheer|{rm.CMD_KEY}", Previewer())  # the widget's own, keyed
        dc._on_js(False, as_board("duecrew:roomcheer"), DeckBrowser())
    finally:
        R.on_message, CC.on_message = saved
    check("a preview's card script can't cheer the room or mark a tip; the widget's keyed button and the board can",
          got == ["roomcheer", "roomcheer"], got)


def test_room_chip_side_v301():
    """3.0.1: the room chip goes left or right in the top bar (a setting
    on this computer; a question bank puts a chip on the right too)."""
    from due_crew import account, room_model as rm
    t0 = datetime.datetime(2026, 9, 24, 18, 0, tzinfo=datetime.timezone.utc)
    room = rm.make_room("dre", t0, 4, 25, 5)
    entries = [{"user_id": "dre", "name": "Dre", "you": False, "room": room}]
    left = rm.widget_js("chip", rm.widget_data(room, entries, ("#6b3fb5", "#b89cf0"), side="left"))
    right = rm.widget_js("chip", rm.widget_data(room, entries, ("#6b3fb5", "#b89cf0")))
    check("chip: left puts it 10px from the left, and nothing on the right",
          "position:fixed;left:10px;top:50%" in left and "right:10px" not in left)
    check("chip: right is the default, as before",
          "position:fixed;right:10px;top:50%" in right and "left:10px;top:50%" not in right)
    check("chip: anything else is right", rm.chip_side("middle") == "right" and rm.chip_side(None) == "right")
    check("chip: the rest of the runtime is unchanged by the side (but the card's end, 3.8.1)",
          left.replace("left:10px;top:50%", "X").replace("left:12px;top:10px", "Y").replace('"side": "left"', "S")
          == right.replace("right:10px;top:50%", "X").replace("right:12px;top:10px", "Y").replace('"side": "right"', "S"))
    check("chip: removing a widget needs no side", "__SIDE__" not in rm.widget_js("off"))
    check("chip: a per-computer setting, like the accent", "room_chip_side" not in account.ACCOUNT_KEYS)


# ---------------------------------------------------------------- 3.1: plans

def _day(n):
    return (TODAY + datetime.timedelta(days=n)).isoformat()


def _plan_units():
    return [
        {"id": "hf", "name": "Heart failure", "opens": _day(-7), "due": _day(-1),
         "tags": ["Step1::Cardio::Heart_failure"]},
        {"id": "ar", "name": "Arrhythmia", "opens": _day(0), "due": _day(6),
         "tags": ["Step1::Cardio::Arrhythmia"]},
        {"id": "ex", "name": "Extras", "opens": _day(3), "decks": ["Step 1::Extras"]},
        {"id": "cz", "name": "Cloze two", "opens": _day(7), "cards": [["guid000050", 1]]},
        {"id": "rn", "name": "Renal", "opens": _day(14), "tags": ["Step1::Renal"]},
    ]


def _plan_col(top="Step1"):
    """Step 1 (10) with Extras (11), and Other (20). Suspended unless said.
    1, 2: Heart failure (2 as a child tag, in another case); 3: Arrhythmia;
    4: in Extras, no tag; 5, 6: c1 and c2 of one cloze note (50); 7: tagged
    Heart failure but in Other; 8: Renal, open and seen; 9: Cardiology (a
    name that starts like Cardio, not under it)."""
    conn = sqlite3.connect(":memory:")
    fakes.make_collection(conn)
    fakes.add_card(conn, 1, did=10, queue=-1, tags=f"{top}::Cardio::Heart_failure")
    fakes.add_card(conn, 2, did=10, queue=-1, tags=f"{top.lower()}::cardio::heart_failure::HFrEF")
    fakes.add_card(conn, 3, did=10, queue=-1, tags=f"{top}::Cardio::Arrhythmia")
    fakes.add_card(conn, 4, did=11, queue=-1)
    fakes.add_card(conn, 5, did=10, queue=-1, nid=50, ord_=0)
    fakes.add_card(conn, 6, did=10, queue=-1, nid=50, ord_=1)
    fakes.add_card(conn, 7, did=20, queue=-1, tags=f"{top}::Cardio::Heart_failure")
    fakes.add_card(conn, 8, did=10, ctype=2, queue=2, tags=f"{top}::Renal")
    fakes.add_card(conn, 9, did=10, queue=-1, tags=f"{top}::Cardiology")
    col = fakes.FakeCol(conn, fakes.day_cutoff_for(TODAY))
    col.decks = fakes.FakeDecks({10: "Step 1", 11: "Step 1::Extras", 20: "Other"})
    return col


def _queues(col):
    return {cid: q for cid, q in col.db.all("SELECT id, queue FROM cards")}


def _open(col):
    return {cid for cid, q in _queues(col).items() if q != -1}


# Names of the parts after this one. The package sets them as each of those parts loads
# (an import here would load a later part before the ones between).
_LATER = ("_PlanGlue", "_SyncBg", "n", "t")
_PlanGlue = _SyncBg = n = t = None
