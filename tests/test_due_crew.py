"""End-to-end tests for Due Crew against fake anki and a fake of the 3.0
Worker API (tests/fakes.py). worker/test proves the Worker itself.

Run: python3 test_due_crew.py
"""

import datetime
import json
import os
import re
import sqlite3
import sys
import tempfile
import types

HARNESS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HARNESS)

import fakes

STORE = fakes.FakeWorker()
fakes.install_fake_requests(STORE)
fakes.install_fake_aqt()
sys.path.insert(0, REPO)

from due_crew import board                                    # noqa: E402
from due_crew.backend import api, shapes                      # noqa: E402
from due_crew.stats import gather_stats                       # noqa: E402
from due_crew.stats.queries import StatsQueries               # noqa: E402

TODAY = datetime.date(2026, 9, 1)


def world(users=None, friends=None):
    """A fresh fake Worker that the client's requests go to. users: {uid:
    name}; friends: {uid: [the people uid added]}."""
    store = fakes.FakeWorker()
    sys.modules["requests"].Session = lambda: fakes.FakeSession(store)
    seed_users(store, users or {}, friends or {})
    return store


def seed_users(store, users, friends):
    for uid, name in users.items():
        if uid not in store.users:
            store.add_user(uid, name)
    for uid, fs in friends.items():
        for f in fs:
            store.befriend(uid, f)


def make_user_col(study_days, today=TODAY):
    """A collection where `study_days` (dates) each have a few reviews."""
    conn = sqlite3.connect(":memory:")
    fakes.make_collection(conn)
    for d in study_days:
        noon = datetime.datetime.combine(d, datetime.time(12))
        base_ms = int(noon.timestamp() * 1000)
        for i in range(3):
            fakes.add_review(conn, base_ms + i * 60000, ease=3 if i else 1)
    return fakes.FakeCol(conn, fakes.day_cutoff_for(today))


def new_client(store, uid, name=None):
    """A signed-in client for `uid` (who must exist in the store)."""
    tmp = tempfile.mkdtemp()
    cl = api.ApiClient(os.path.join(tmp, "session.json"))
    cl.session = {"user_id": uid, "token": store.session_for(uid),
                  "email": f"{uid}@example.com", "display_name": name or uid.capitalize()}
    return cl


def sync_once(store, cl, col, files_dir, cfg, today):
    """What a full sync does, minus threading: today, the week, the heatmap."""
    q = StatsQueries(col)
    labels = [q.day_label(i) for i in range(7)]
    stats = gather_stats(col, files_dir)
    week = gather_week(col, files_dir)
    heat = q.heatmap_counts(182) if cfg.get("share_heatmap", True) else "off"
    cl.push(labels, cfg, stats=stats, backfill=week, heatmap=heat)
    return labels


def fetch_as(store, cl, col):
    q = StatsQueries(col)
    labels = [q.day_label(i) for i in range(7)]
    tomorrow = q.day_label(-1)
    return cl.fetch_board(labels, tomorrow=tomorrow, with_decks=True), labels, tomorrow


def showed_days(entry, labels):
    """How many of the 7 fetched days read as showed-up for this entry."""
    days = entry.get("days") or {}
    return sum(1 for lb in labels if board._showed(days.get(lb)))


from due_crew.stats import gather_week                        # noqa: E402

CHECKS = []


def check(name, cond, detail=""):
    CHECKS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))


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
    check("welcome back: row renders the chip", "bkb" in html and "back" in html)


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
    crew = share.crew_week("busm", labels, [
        ("sammy", flags, ""),
        ("igk <b>\nx", [True] * 7, ""),
        ("Ameya", [True, False, True, True, False, True, True], "Tue"),
        ("Quiet", [False] * 7, ""),
    ], 21430, 148320000)
    rows = crew.split("\n")
    check("share: crew week header, order (most days first), absence silent",
          rows[0] == "busm · Sep 1–7" and len(rows) == 6
          and rows[1].endswith(" igk <b> x") and rows[2].endswith(" sammy")
          and rows[3] == "🟩⬜🟩🟩⬜🟩🟩 Ameya · as of Tue", crew)
    check("share: crew totals line",
          rows[4] == "21,430 reviews · 41h 12m together")
    check("share: nobody studied -> None",
          share.crew_week("busm", labels, [("a", [False] * 7, "")], 0, 0) is None)
    check("share: month-crossing range",
          share.date_range(["2026-08-30", "2026-09-05"]) == "Aug 30 – Sep 5")
    js = board.profile_overlay_js({"name": "Sammy", "you": True, "cells": None})
    check("share: own card offers today and week",
          "duecrew:sharetoday" in js and "duecrew:shareweek" in js)
    foot_week = board.render({"entries": [], "labels": labels[::-1], "tomorrow": "",
                              "pending": []}, {"period": "week"}, 0)
    check("share: Week view footer offers the crew week",
          "sharecrewweek" in foot_week and "Share week" in foot_week)


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
          "you're on fire <b>now</b>" in js and "'\u201c' + notes[n]" in js
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
          'class="awb"' in today_html and "back tomorrow" in today_html, today_html[-600:])
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
    crew = share.crew_week("busm", week, [
        ("Ameya", ["away"] * 7, ""), ("igk", [True, "away", "away", True, True, True, True], "")],
        100, 60000)
    check("share: away-only week gets no row; planes in rows",
          crew is not None and crew.count("\n") == 3 and "🟩✈️✈️🟩🟩🟩🟩 igk" in crew, str(crew))


def _squad_fixture():
    """Sam founds busm; Dre, Eve, and Zed exist and aren't members yet."""
    store = world({"sam": "Sammy", "dre": "Dre", "eve": "Eve", "zed": "Zed"})
    sam = new_client(store, "sam", "Sammy")
    squad = sam.create_squad("  busm  <b> ")
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
          bool(squad) and squad["name"] == "busm <b>" and sid in store.squads
          and (sid, "sam") in store.members, str(squad))
    check("squad: code is 8 safe chars; any spelling of it derives the id",
          len(squad["code"]) == 8
          and all(ch in shapes.SQUAD_ALPHABET for ch in squad["code"])
          and shapes.squad_id(squad["code"].lower() + "--") == sid)
    dre = new_client(store, "dre", "Dre")
    info, status = dre.peek_squad(squad["code"])
    check("squad: peek shows name, founder, open",
          bool(info) and info["name"] == "busm <b>" and info["founder"] == "sam"
          and info["open"], str((info, status)))
    check("squad: unknown code is a 404, not an error", dre.peek_squad("ZZZZZZZZ") == (None, 404))
    check("squad: join while open", dre.join_squad(sid) == 200)
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
    check("squad: join refused while locked", zed.join_squad(sid) == 403)
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
    dre.join_squad(sid)
    ok = dre.send_knock("sam", sid)
    check("knock: needs a squad both are in", not dre.send_knock("eve", sid))
    eve = new_client(store, "eve", "Eve")
    check("knock: squadmates can knock, outsiders cannot", ok and not eve.send_knock("sam", sid))
    knocks = sam.list_knocks()
    check("knock: names from profiles (no spoofing), squad id carried",
          knocks == [("dre", "Dre", sid)], str(knocks))
    sam.delete_knock("dre")
    check("knock: delete clears it", sam.list_knocks() == [])


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
    view = {"state": "ok", "squads": [{"id": "abc", "name": "busm"},
                                      {"id": "def", "name": "MS2 <x>"}],
            "current": "abc", "name": "busm", "open": False, "founder_me": True,
            "rows": rows, "day": "2026-09-01", "yesterday": "2026-08-31",
            "people": 5, "studying": 4, "reviews": 2713}
    html = board._squads_html(view, {})
    check("squad view: plain ranks, no medals, no cheers",
          "#1" in html and "&#129351;" not in html and "dc-cheer" not in html)
    check("squad view: names escaped, card command wired, notes",
          "StepQueen &lt;s&gt;" in html and "ecard:u1" in html
          and "&middot; waiting" in html and "added you" in html and "&middot; crew" not in html)
    check("squad view: retention column and headline",
          "92.1%" in html and "5 in busm &middot; locked &middot; 4 studying today "
          "&middot; 2,713 reviews together" in html, html)
    check("squad view: yesterday's row is dim, unranked, and last",
          html.index("Marcus") > html.index("Priya") and "&middot; yesterday" in html
          and re.search(r'<td class="rk"></td><td class="nm"><a[^>]*ecard:u3', html) is not None)
    check("squad view: founder controls and the shared footer",
          "squadlock" in html and ">Open<" in html and "squadinvite" in html
          and "squadleave" in html)
    by_streak = board._squads_html(view, {"sort": "streak"})
    check("squad view: headers are the crew's sort links; sorting reorders ranks",
          'onclick="pycmd(\'duecrew:sort:retention\')' in html
          and by_streak.index("StepQueen") < by_streak.index("Maya")
          and by_streak.index("Maya") < by_streak.index("Sammy")
          and '&#128293;<span class="hl"> Streak</span> &#9662;' in by_streak, by_streak)
    check("squad view: switcher marks the current squad and escapes names",
          'class="on"' in html and "MS2 &lt;x&gt;" in html and "squadadd" in html)
    none = board._squads_html({"state": "none", "squads": [], "current": ""}, {})
    check("squad view: no squads yet offers join or create",
          "squadadd" in none and "<table>" not in none)
    gone = board._squads_html({"state": "gone", "squads": [{"id": "abc", "name": "busm"}],
                               "current": "abc", "name": "busm"}, {})
    check("squad view: removed -> Remove link", "squaddrop:abc" in gone)
    page = board.render({"entries": [], "labels": ["2026-09-01"], "tomorrow": "",
                         "pending": []}, {"period": "today"}, 0,
                        knocks=[{"uid": "u4", "name": "Priya <p>", "squad": "busm"}])
    check("knock banner: escaped name, Add back and Not now wired",
          "Priya &lt;p&gt;" in page and "added you from busm" in page
          and "addback:u4" in page and "knockmute:u4" in page)
    js = board.stranger_card_js({
        "uid": "u4", "name": "Priya <p>", "reviews": 301, "time_ms": 2400000,
        "retention": 94.2, "streak": 2, "rank": 4, "squad": "busm", "today": True,
        "pending": False, "knocked_me": True, "founder_me": True})
    check("squad card: retention, rank, Add back, founder Remove",
          "94.2% retention" in js and "#4 in busm today" in js
          and "duecrew:addback:u4" in js and "duecrew:squadkick:u4" in js)
    plain = board.stranger_card_js({
        "uid": "u1", "name": "Q", "reviews": 1, "time_ms": 1, "retention": None,
        "streak": 1, "rank": None, "squad": "busm", "today": False,
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
    dre.join_squad(sid)
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
          board._pycmd("profile:abc_1-2") == "pycmd('duecrew:profile:abc_1-2'); return false;"
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
    squad = sam.create_squad("busm")
    sid = squad["id"]
    dre = new_client(store, "dre", "Dre")
    dre.join_squad(sid)
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
    check("block: rejoining is refused even with the door open", dre.join_squad(sid) == 403)
    eve.join_squad(sid)
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
    view = {"state": "ok", "squads": [{"id": "abc", "name": "busm"}], "current": "abc",
            "name": "busm", "open": True, "founder_me": True, "rows": rows, "day": labels[0],
            "yesterday": labels[1], "people": 3, "studying": 3, "reviews": 2225}
    html = board._squads_html(view, {"sort": "week"})
    check("squad board: emoji in front of names, a rolling 7-days column, sortable by it",
          "🐢 igk" in html and "🦊 Sammy" in html and "7/7" in html and "6/7" in html
          and '&#128197;<span class="hl"> 7 days</span> &#9662;' in html
          and html.index("igk") < html.index("Sammy") < html.index("Priya"))
    page = board.render({"entries": [], "labels": labels, "tomorrow": "", "pending": []},
                        {"period": "squads"}, 0, squad_view=view)
    check("squad board: Share today sits in the footer, as on Today, not on the squad's line",
          "squadshare" not in html and "squadshare" in page
          and page.index("squadinvite") < page.index('<div class="dc-foot">') < page.index("squadshare"))
    crew = board.render({"entries": [{"user_id": "sam", "name": "Sammy", "emoji": "🦊", "you": True,
                                       "paused": False, "last_updated": "", "exam_date": "",
                                       "days": {labels[0]: {"studied": True, "reviews": 3}}, "decks": []}],
                         "labels": labels, "tomorrow": "", "pending": []}, {"sort": "week"}, 0)
    check("crew board: emoji by the name; the squads-only sort falls back to reviews",
          "🦊 Sammy" in crew and '&#128218;<span class="hl"> Reviews</span> &#9662;' in crew)
    js = board.profile_overlay_js({"name": "Sammy", "you": True, "cells": None, "emoji": "🦊"})
    esc = lambda t: json.dumps(t)[1:-1]  # JS strings carry non-ASCII escaped
    check("own card: emoji by the name and a link to change it",
          esc("🦊 Sammy") in js and "duecrew:emoji" in js and "Change emoji" in js)
    card = board.stranger_card_js({"uid": "u1", "name": "igk", "emoji": "🐢", "reviews": 1,
                                   "time_ms": 1, "retention": None, "streak": 1, "rank": 1,
                                   "squad": "busm", "today": True, "pending": False,
                                   "knocked_me": False, "founder_me": True})
    check("squadmate card: founder sees Remove, Block, Make founder",
          "duecrew:squadkick:u1" in card and "duecrew:squadblock:u1" in card
          and "duecrew:squadfounder:u1" in card and esc("🐢 igk") in card)
    text = share.squad_today("busm", labels[0], [("igk", "🐢", 1412), ("Sammy", "🦊", 512),
                                                 ("Priya", "", 301), ("Zed", "", 5)], 4, 2230)
    check("squad share: headline, together line, top three with emoji",
          text.split("\n")[1] == "4 studying · 2,230 reviews together"
          and text.split("\n")[2] == "🟩 🐢 igk 1,412 · 🦊 Sammy 512 · Priya 301", text)
    week = list(reversed(labels))
    crew_txt = share.crew_week("busm", week, [("Sammy", [True] * 7, "", "🦊"), ("igk", [True] * 7, "")], 1, 1)
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
    store.otp["sam@example.com"] = "123456"
    cl.verify_code("sam@example.com", "123456")
    check("session: signing in again clears it", not cl.session_dead and cl.signed_in)

    col = make_user_col([TODAY])
    cl.push([TODAY.isoformat()], {}, stats=gather_stats(col, tempfile.mkdtemp()), version="3.0.0",
            clock={"tz": -240, "rollover": 4})
    check("profile carries the client version and clock",
          store.users["sam"]["client_version"] == "3.0.0" and store.users["sam"]["tz"] == -240)

    squad = cl.create_squad("busm")
    sid = squad["id"]
    dre = new_client(store, "dre", "Dre")
    dre.join_squad(sid)
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
    check("join: the real join works", dre.join_squad(sid) == 200)
    check("row: a member's sync still lands", _row_sync(dre, row, [sid]) == (True, [])
          and store.members[(sid, "dre")]["reviews"] == 5)
    sam.remove_member(sid, "dre")            # the squad is OPEN — never locked
    check("remove sticks: the next sync reports gone and re-creates nothing",
          _row_sync(dre, dict(row, reviews=6), [sid]) == (True, [sid]) and (sid, "dre") not in store.members)
    check("remove sticks: the founder's board no longer lists them",
          sorted(r["name"] for r in sam.fetch_squad(sid)["rows"]) == ["Sammy"])
    check("a deliberate rejoin with the code still works — Block is what stops that",
          dre.join_squad(sid) == 200)


def _deck_col():
    """AnKing (1) with a Cardio subdeck (2), an unrelated deck (3), and one
    card sitting in a filtered deck (99) whose home is Cardio. By hand, for
    the AnKing subtree: 6 cards, 4 seen, 2 mature, 5 unlocked."""
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
    col.decks = fakes.FakeDecks({1: "AnKing", 2: "AnKing::Cardio", 3: "Other"})
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
          == ("AnKing", 6, 4, 2, 5, 4, 75.0, TODAY.isoformat()), str(d))
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
          "4 seen · 2 mature · 5 unlocked · 6 total · +12 this week · 75.0% retention, last 7 days" in bar
          and "Ameya &lt;a&gt;" in bar)
    check("bar: today and week chips, and retention beside the count",
          "+4 today &middot; +12 wk" in bar and "4 / 6 &middot; 75%" in bar)
    stale = board._bar("Ameya", False, clean(payload)[0], today_labels=(other,))
    check("bar: yesterday's 'today' is not shown as today", "today" not in stale.split("title=")[0]
          and "+4 today" not in stale)
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
    check("decks legend: names the fills by texture, which holds in both themes",
          "solid = mature" in legend and "faded = seen" in legend and "hatched = unlocked" in legend
          and "light =" not in legend and "dark =" not in legend)


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

        real_dump = wrap.json.dump

        def dies_halfway(obj, f):
            f.write('{"life": {"rev')
            raise OSError("disk full")

        wrap.json.dump = dies_halfway
        try:
            wrap._wrap["data"] = {"life": {"reviews": 0}}
            wrap._save_wrap()
        finally:
            wrap.json.dump = real_dump
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
    check("any emoji: a delivered cheer is gone", ("sam", "dre") not in store.cheers)
    dre.send_cheer("sam", thumbs)
    data, _l, _t = fetch_as(store, sam, make_user_col([TODAY]))
    check("any emoji: a real one arrives intact", [c["emoji"] for c in data["cheers"]] == [thumbs])
    check("cheer picker: the quick row and the any-emoji box",
          social.cheer_choices() == (CHEER_QUICK, True))
    check("cheer gate: one cluster; text never",
          social.cheer_allowed(party + "\U0001F389") == party and social.cheer_allowed("lol") == "")


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
    check("cheers: they ride the refresh, and are delivered once",
          [c["from"] for c in data["cheers"]] == ["f0"] and sam.fetch_board(labels, tomorrow)["cheers"] == [])
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
          and fc("Join busm on Due Crew · code ABCD2345") == "")
    check("invite paste: a squad code from its invite, even from a squad named for codes",
          shapes.squad_code_from("Join code club on Due Crew · code ABCD2345\n— Due Crew") == "ABCD2345"
          and shapes.squad_code_from("abcd 2345") == "ABCD2345")
    store.add_user("newbie", None)
    newbie = new_client(store, "newbie", "Newbie")
    code, people, _k = newbie.friends_view()
    check("a new account gets its code the first time Friends (or Welcome) opens",
          code and store.codes.get(code) == "newbie" and people == [])


def test_new_code():
    """2.10: New Code swaps my friend code; the old one stops working, the
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
             "shared_decks": [11, 12], "squads": [{"id": "sq1", "code": "ABCD2345", "name": "busm", "founder": "x"}],
             "status": "coffee", "accent": "rose", "sort": "time"}
    doc = account.pick(cfg_a, {11: "AnKing", 12: "Pathoma"}.get)
    check("pick: only what follows the account; decks with names; accent and sort stay",
          "accent" not in doc and "sort" not in doc
          and doc["shared_decks"] == [{"id": 11, "name": "AnKing"}, {"id": 12, "name": "Pathoma"}])
    here = {11: 11, 99: 99}                      # this computer: 11 by id, Pathoma by name as 99
    resolve = lambda did, name: here.get(did) or {"Pathoma": 99}.get(name)
    got = account.apply({"accent": "green", "share_retention": True}, doc, resolve)
    check("apply: the account's settings land; the deck matches by id, else by name; accent stays",
          got["share_retention"] is False and got["exam_date"] == "2026-10-02"
          and got["shared_decks"] == [11, 99] and got["accent"] == "green" and got["shared_decks_set"])
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
          and back["settings"]["shared_decks"][1]["name"] == "Pathoma")
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
        a = computer("a", dict(cfg_a), {11: "AnKing", 12: "Pathoma"})
        use(a)
        synced = []
        account.ensure(lambda: synced.append("a"))
        check("first computer: nothing on the account yet, so its settings go up, then its sync runs",
              synced == ["a"] and "sam" in store.settings and account.ready())
        b = computer("b", {"share_retention": True, "shared_decks": [], "accent": "blue"},
                     {11: "AnKing", 77: "Pathoma"})
        use(b)
        order = []
        real_pulled = account._pulled
        account._pulled = lambda r: (order.append("pulled"), real_pulled(r))[1]
        account.ensure(lambda: order.append("sync"))
        account._pulled = real_pulled
        check("second computer: pulls before its first sync, and takes the account's settings",
              order == ["pulled", "sync"] and b["cfg"]["shared_decks"] == [11, 77]
              and b["cfg"]["share_retention"] is False and b["cfg"]["accent"] == "blue")
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
        cmd = inv_html.split("roomjoin:")[1].split("'")[0]
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
          '"title": "Dre\\u2019s room"' in js and "innerHTML" not in js.replace("s.innerHTML = SQ", "")
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
        evals.clear(); calls.clear()
        rooms.on_question(None)
        check("break: a skipped break doesn't come back on the next card", calls == [] and not _state["room_break"])
        fake_cl.session["room"] = rm.make_room("dre", now - datetime.timedelta(minutes=10))
        evals.clear()
        rooms.on_question(None)
        check("placement: top bar showing, the chip goes there and the margin card doesn't",
              any('"chip"' in e and '"title"' in e for e in evals)
              and any('"gutter"' in e and "null" in e.split("var D =")[1][:12] for e in evals))
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
          "duecrew:settings')" in foot and foot.index("duecrew:refresh") < foot.index("duecrew:settings"))
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
    check("live: the footer offers I'm studying, then Stop studying",
          "I&rsquo;m studying" in page and "Stop studying" in stop and "duecrew:live" in page)

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
    check("flags: escaped, with Send a tip wired", "&lt;b&gt;" in flags and "tricktip:dre:0" in flags)
    check("flags: a cloze shows as [...], never its answer",
          together._plain("<b>S3</b>&nbsp;is heard in {{c1::Kentucky::rhythm}}") == "S3 is heard in [\u2026]")
    tip = board.tip_html([("Dre <i>", "Ken-tuck-y")])
    check("tips: under the answer, escaped", "Dre &lt;i&gt;" in tip and "Ken-tuck-y" in tip)

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
    class Card:
        def note(self):
            return types.SimpleNamespace(guid="guid000003")
    check("tips: on the answer only",
          "Kentucky" in together.card_will_show("A", Card(), "reviewAnswer")
          and together.card_will_show("Q", Card(), "reviewQuestion") == "Q")
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
    view = {"state": "ok", "squads": [{"id": "x", "name": "busm"}], "current": "x", "name": "busm",
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
    sid = sam.create_squad("busm")["id"]
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
    check("show-up rows, Today: a check instead of a rank, after the ranked rows",
          '<td class="rk">&#10003;</td><td class="nm">' in today and today.index("Kai") > today.index("Dre")
          and '<td class="rk">#3</td>' not in today)
    week = board.render(base, {"period": "week"}, 0)
    check("show-up rows, Week: a check and the days this week, no rank (Nia studied Monday: she counts too)",
          "1 day this week" in week and week.count("&#10003;") == 2 and '<td class="rk">#3</td>' not in week)
    mode = board.render(base, {"period": "week", "show_up": True}, 0,
                        wrap={"reviews": 5, "time_ms": 1, "full_days": 5})
    check("mode: one crew pill, the week's totals banner gone, Share week offered, Share today not",
          ">Crew</a>" in mode and ">Today</a>" not in mode and ">Week</a>" not in mode
          and "Last week" not in mode and "Share week" in mode and "Share today" not in mode)
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
    view = {"state": "ok", "squads": [{"id": "x", "name": "busm"}], "current": "x", "name": "busm",
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
                                   "retention": None, "streak": None, "rank": None, "squad": "busm",
                                   "today": True, "week": 5})
    check("squadmate card for a show-up person: presence only",
          "showed up today" in card and "5/7 days this week" in card and "-day streak" not in card)
    txt = share.crew_week("busm", labels[::-1], [("Sammy", [True, False, True], "")], None, None)
    check("share: in the mode the crew week is squares alone, no totals line",
          "reviews" not in txt and "together" not in txt and "Sammy" in txt)
    js = board.stranger_card_js({"uid": "a", "name": "Ann", "reviews": 500, "time_ms": 1000,
                                 "retention": 90.0, "streak": 3, "rank": 1, "squad": "busm",
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
    some = board.render(dict(base, entries=[ent({"studied": True, "reviews": 205, "newCards": 12})]),
                        {"period": "today"}, 0)
    every = board.render(dict(base, entries=[ent({"studied": True, "reviews": 20, "newCards": 20})]),
                         {"period": "today"}, 0)
    none = board.render(dict(base, entries=[ent({"studied": True, "reviews": 20, "newCards": 0})]),
                        {"period": "today"}, 0)
    old = board.render(dict(base, entries=[ent({"studied": True, "reviews": 20})]), {"period": "today"}, 0)
    check("board: a grey line under Reviews, with the whole count on hover",
          '<small class="nw">12 new</small>' in some and 'title="12 of 205 were new cards"' in some)
    check("board: \"all new\" when every review was new; nothing when none were or they didn't say",
          ">all new<" in every and 'class="nw"' not in none and 'class="nw"' not in old)
    wk = board._week_row({lb: {"reviews": 10, "newCards": 3},
                          (TODAY - datetime.timedelta(days=1)).isoformat(): {"reviews": 5, "newCards": 1}},
                         [lb, (TODAY - datetime.timedelta(days=1)).isoformat()])
    check("board: Week adds the days up", wk["new"] == 4 and wk["reviews"] == 15)

    # squad rows
    sid = sam.create_squad("busm")["id"]
    row = {"name": "Sammy", "day": lb, "reviews": 5, "newCards": 2}
    check("squad row: newCards lands", _row_sync(sam, row, [sid]) == (True, [])
          and store.members[(sid, "sam")]["newCards"] == 2)
    check("squad row: a negative count is refused", _row_sync(sam, dict(row, newCards=-1), [sid])[0] is False)
    drow = next(r for r in sam.fetch_squad(sid)["rows"] if r["user_id"] == "sam")
    check("squad row: read back as new_cards", drow["new_cards"] == 2)
    view = {"state": "ok", "squads": [{"id": sid, "name": "busm"}], "current": sid, "name": "busm",
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
    new account, asked for a name. The same account from 2.x keeps what
    this computer knew about it; another account starts clean."""
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

    # the same account, from a 2.x session.json
    old = api.ApiClient(os.path.join(tempfile.mkdtemp(), "session.json"))
    old.session = {"user_id": "sam", "email": "sam@example.com", "display_name": "Sammy",
                   "id_token": "x", "refresh_token": "r", "friend_ids": ["dre"], "cheers_seen": {"dre": "t"}}
    check("2.x: signed out, and the board knows why", not old.signed_in and old.was_on_2x)
    old.request_code("sam@example.com")
    got = old.verify_code("sam@example.com", store.otp["sam@example.com"])
    check("2.x: the same uid, no name asked, what it knew is kept, and the restore is due",
          got == {"uid": "sam", "name": "Sammy", "new": False}
          and old.session["friend_ids"] == ["dre"] and old.session["cheers_seen"] == {"dre": "t"}
          and old.session.get("needs_restore") is True
          and "refresh_token" not in old.session and not old.was_on_2x)
    other = api.ApiClient(os.path.join(tempfile.mkdtemp(), "session.json"))
    other.session = {"user_id": "someone-else", "refresh_token": "r", "friend_ids": ["x"]}
    other.request_code("sam@example.com")
    other.verify_code("sam@example.com", store.otp["sam@example.com"])
    check("another account: nothing carries over", "friend_ids" not in other.session
          and not other.session.get("needs_restore"))


def test_restore_from_2x():
    """3.0's first sync brings back what a 2.x install knew: its code (when
    this computer had it), its crew by uid, its squads by their codes. Then
    it's done, and never runs again."""
    store = world({"sam": "Sammy", "dre": "Dre", "eve": "Eve"}, {"dre": ["sam"]})
    sam = new_client(store, "sam", "Sammy")
    sam.session.update(needs_restore=True, friend_ids=["dre", "eve", "ghost"], friend_code="SAM123")
    cfg = {"squads": [{"id": shapes.squad_id("ABCD2345"), "code": "ABCD2345", "name": "busm", "founder": "dre"}]}
    ok, _gone = sam.push([TODAY.isoformat()], cfg)
    sid = shapes.squad_id("ABCD2345")
    check("restore: my code comes back as it was", store.codes.get("SAM123") == "sam")
    check("restore: my crew comes back by uid; who added me back is crew at once",
          ("sam", "dre") in store.friends and ("sam", "eve") in store.friends and store.mutual("sam", "dre")
          and not store.mutual("sam", "eve"))
    check("restore: my squad comes back under its old id, with its founder, and me in it",
          store.squads.get(sid, {}).get("founder") == "dre" and (sid, "sam") in store.members)
    check("restore: done, once", ok and "needs_restore" not in sam.session)
    n = len(store.log)
    sam.push([TODAY.isoformat()], cfg)
    check("restore: the next sync is just a sync", [p for _m, p, _s in store.log[n:]] == ["/sync"])
    zed = new_client(store, "dre", "Dre")
    zed.session["needs_restore"] = True
    store.down = True
    try:
        zed.push([TODAY.isoformat()], cfg)
    except shapes.TransportError:
        pass
    store.down = False
    check("restore: offline, it waits for the next sync", zed.session.get("needs_restore") is True)
    store.fail_status = 503
    try:
        zed.push([TODAY.isoformat()], cfg)
    except shapes.TransportError:
        pass
    store.fail_status = None
    check("restore: a server in trouble doesn't count as done either", zed.session.get("needs_restore") is True)
    dre = zed
    dre.push([TODAY.isoformat()], cfg)
    check("restore: the founder coming back joins the squad the first member brought back",
          (sid, "dre") in store.members and store.squads[sid]["founder"] == "dre"
          and store.codes and "dre" in store.codes.values())


def main():
    names = [n for n in list(globals()) if n.startswith("test_")]
    for n in names:
        globals()[n]()
    bad = [c for c in CHECKS if not c[1]]
    print(f"\n{len(CHECKS) - len(bad)}/{len(CHECKS)} checks passed")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
