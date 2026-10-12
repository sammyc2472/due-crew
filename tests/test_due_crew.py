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
    return acked(cl, cl.fetch_board(labels, tomorrow=tomorrow, with_decks=True)), labels, tomorrow


def acked(cl, data):
    """What the main thread's commit does with a refresh's cheers (3.7.2):
    the next refresh tells the server they arrived."""
    cl.session["cheers_got"] = data.get("cheers_at") or 0
    return data


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
    check("share: the footer's Share menu offers the crew week (3.7.1, H3)",
          "crewmenu" in foot_week and "sharemenu" in foot_week
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
          and '<span class="hi">&#128293;</span><span class="hl">Streak</span> &#9662;' in by_streak, by_streak)
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
    squad = sam.create_squad("busm")
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
    view = {"state": "ok", "squads": [{"id": "abc", "name": "busm"}], "current": "abc",
            "name": "busm", "open": True, "founder_me": True, "rows": rows, "day": labels[0],
            "yesterday": labels[1], "people": 3, "studying": 3, "reviews": 2225}
    html = board._squads_html(view, {"sort": "week"})
    check("squad board: emoji in front of names, a rolling 7-days column, sortable by it",
          "🐢 igk" in html and "🦊 Sammy" in html and "7/7" in html and "6/7" in html
          and '<span class="hl">7 days</span> &#9662;' in html
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
                         "labels": labels, "tomorrow": "", "pending": []}, {"sort": "week"}, 0)
    check("crew board: emoji by the name; the squads-only sort falls back to reviews",
          "🦊 Sammy" in crew and '<span class="hl">Reviews</span> &#9662;' in crew)
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

    squad = cl.create_squad("busm")
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
          "4 seen · 2 mature · 5 unlocked · 6 total · +12 this week · 75.0% retention, last 7 days" in bar
          and "Ameya &lt;a&gt;" in bar)
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
          '<i class="fm"></i>mature<i class="fs"></i>seen<i class="fo"></i>unlocked' in legend
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
          "stopPropagation" in js and "duecrew:" in js and "textContent" in js and "innerHTML" not in js)
    from due_crew import room_model as rm
    check("bottom bar: the chip, a room beside Edit, and removing them keep the answer buttons centred",
          "dcBarBalance" in js and "dcBarBalance" in crew_cards.chip_js(None)
          and all("window.dcBarBalance = function" in rm.widget_js(k, None) for k in ("bottom", "off"))
          and "window.dcBarBalance = function" not in rm.widget_js("chip", None))
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
          and rm.CMD_KEY in fj and "textContent" in fj and "innerHTML" not in fj
          and "dc-knows-card" in crew_cards.float_js(None) and "return false" in crew_cards.float_js(None))
    import aqt.utils as _au
    calls, asked = [], []
    real_toggle, real_ask = crew_cards.helped_toggle, _au.askUser
    crew_cards.helped_toggle = calls.append
    real_tip = crew_cards._tip_from
    crew_cards._tip_from = lambda uid: {"name": "Eve Park", "helped": False, "from": uid}
    try:
        _au.askUser = lambda q, *a, **k: asked.append(q) or False
        crew_cards.on_message("knowshelped", ["duecrew", "knowshelped", "eve"], from_card_page=True)
        no = list(calls)
        _au.askUser = lambda q, *a, **k: asked.append(q) or True
        crew_cards.on_message("knowshelped", ["duecrew", "knowshelped", "eve"], from_card_page=True)
        crew_cards.on_message("knowshelped", ["duecrew", "knowshelped", "eve"])
    finally:
        crew_cards.helped_toggle, _au.askUser, crew_cards._tip_from = real_toggle, real_ask, real_tip
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
          'oncontextmenu="pycmd(\'duecrew:rowmenu:dre\'); return false;"' in html and "rowmenu" not in mine)
    check("menu: the uid is the only thing that rides the command",
          "rowmenu:xscriptalert1script'" in board._row_html(dict(row, user_id="x'<script>alert(1)</script>"), "#1", {}))

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
    check("not yet: Kai keeps silver, and Dre's rank is a dash", kai.rfind("&#129352;") > kai.rfind("<tr")
          and '<td class="rk">&mdash;</td>' in page[page.rfind("<tr", 0, page.index(">Dre<")):page.index(">Dre<")])
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
          and "#1" in sq and "#2" not in sq and "nothing yet today" in sq and "1 studying today" in sq)


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
          change(["set", "compact", "1"], cfg) == {"compact": True}
          and change(["set", "accent", "rose"], cfg) == {"accent": "rose"}
          and change(["set", "accent", "red"], cfg) is None
          and change(["set", "api_base", "1"], cfg) is None
          and change(["set", "compact", "yes"], cfg) is None)
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
          and change(["setexam", "2026-11-02"], cfg) == {"exam_date": "2026-11-02"}
          and change(["setexam", "off"], {"exam_date": "2026-11-02"}) == {"exam_date": ""}
          and change(["setexam", "soon"], cfg) is None)
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
            "sync": "sam@x.edu · Synced 2m ago · v3.5.0", "crew": 3, "squads": ["<i>BUSM</i>", "Block 3", "Lab"],
            "decks": ["Big Deck"]}
    you = board.settings_html(view, {"crew_label": "Crew"})
    check("settings: You, escaped; three squads read as two and 1 more",
          'id="due-crew"' in you and "Sam &lt;b&gt;" in you and "&lt;i&gt;BUSM&lt;/i&gt;, Block 3 and 1 more" in you
          and "coffee &quot;&amp;&quot; cards" in you and "3 in your crew" in you and "<i>BUSM" not in you
          and "duecrew:setclose" in you and "Delete account" in you, you[-600:])
    bd = board.settings_html(dict(view, tab="board"), {"crew_label": 'a"><script>', "accent": "teal",
                                                         "hidden_tabs": ["decks"], "compact": True})
    check("settings: Board, its switches and tabs as set, the crew name escaped",
          'value="a&quot;&gt;&lt;script&gt;"' in bd and "<script>" not in bd
          and "duecrew:settabs:decks:1" in bd and "duecrew:settabs:plans:0" in bd
          and "settabs:week" not in bd
          and "duecrew:set:compact:0" in bd and 'aria-label="Teal" aria-pressed="true"' in bd)
    pv = board.settings_html(dict(view, tab="privacy"), {"show_up": True, "exam_date": "2026-10-14",
                                                           "away_from": "", "away_to": ""})
    check("settings: Privacy, one choice checked; numbers only under My numbers; exam on, away off",
          pv.count('aria-checked="true"') == 2 and "duecrew:setprivacy:numbers" in pv
          and "share_reviews" not in pv and 'value="2026-10-14"' in pv
          and "duecrew:setexam:off" in pv and "duecrew:setaway:on" in pv, pv[-900:])
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
    conf = {"compact": False, "hidden_tabs": [], "accent": "green"}
    saved = (dc._swap, dc.cfg, dc.save_cfg)
    swaps = []
    dc._swap = lambda c, focus=None: swaps.append(focus)
    dc.cfg = lambda: conf
    dc.save_cfg = lambda c, **k: None
    try:
        send = lambda m: dc._on_js(False, "duecrew:" + m, DeckBrowser())
        send("settab:board")
        tab = dc._state.get("settings_tab")
        send("set:compact:1")
        send("set:accent:rose")
        send("settabs:plans:0")
        send("setclose")
        check("settings: the board's clicks reach it (a tab, a switch, a choice, a tab hidden, back)",
              tab == "board" and conf["compact"] is True and conf["accent"] == "rose"
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
    for text in src.values():
        for rx in (r'_pycmd\(\s*f?["\']([a-z]+)', r'_st_click\(\s*f?["\']([a-z]+)', r'duecrew:([a-z]+)',
                   r'"(?:cmd|actcmd)":\s*f?"([a-z]+)'):
            emitted |= set(re.findall(rx, text))
    handled = set()
    for name in ("__init__.py", "plan_flow.py", "rooms.py", "cards.py", "due_flow.py", "team_flow.py"):
        text = src[os.path.join(REPO, "due_crew", name)]
        handled |= set(re.findall(r'cmd == "([a-z0-9]+)"', text))
        for group in re.findall(r'cmd in \(([^)]*)\)', text) + re.findall(r'SETTINGS_CMDS = \(([^)]*)\)', text):
            handled |= set(re.findall(r'"([a-z0-9]+)"', group))
    prefixes = {"plan", "room", "knows"}  # 'duecrew:' + a name built at run time
    missing = sorted(c for c in emitted - handled - prefixes)
    check("commands: every one the add-on emits has a handler", not missing and len(emitted) > 60, missing)


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
        dc._on_js(False, "duecrew:roomcheer", DeckBrowser())
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
    check("chip: the rest of the runtime is unchanged by the side",
          left.replace("left:10px;top:50%", "X").replace('"side": "left"', "S")
          == right.replace("right:10px;top:50%", "X").replace('"side": "right"', "S"))
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


def test_plans_events_f1():
    """F1: events are named days the dates prep for; the plan card says
    what today's studying leads up to, and how many prep days are left."""
    from due_crew import plans as P, board
    from due_crew.backend import shapes
    doc = shapes.clean_plan_doc({"deck": "Step 1",
        "events": [{"id": "q1", "day": "2026-10-15", "name": "Micro <quiz>"}, {"id": "x", "day": "soon", "name": "bad"}],
        "units": [{"id": "a", "name": "Staph", "opens": "2026-10-12", "for": "q1"},
                  {"id": "b", "name": "Strep", "opens": "2026-10-13", "for": "q1"},
                  {"id": "c", "name": "Entero", "opens": "2026-10-14", "for": "q1"},
                  {"id": "d", "name": "Clostridium", "opens": "2026-10-16"}]})
    check("events: cleaned on arrival, a bad day dropped", [e["id"] for e in doc.get("events", [])] == ["q1"], str(doc.get("events")))
    pf = P.prep_for(doc, "2026-10-12")
    check("events: today preps for the quiz, two more days to go", pf == {"name": "Micro <quiz>", "day": "2026-10-15", "left": 2, "today": False}, str(pf))
    check("events: on its day it says so", P.prep_for(doc, "2026-10-15")["today"] is True)
    check("events: nothing once it's past", P.prep_for(doc, "2026-10-16") is None)
    html = board._plan_card_html({"id": "p", "title": "Plan", "prep": dict(pf, when="Thu")})
    check("events: the card line, the name escaped",
          "For <b>Micro &lt;quiz&gt;</b> on Thu &middot; 2 more days of prep" in html, html)


def test_plans_buried_siblings():
    """A new card whose note has a card answered counts as seen: Anki
    buries and spaces siblings, so the date is done and never behind for
    them, and Due says when they come back. A suspended sibling stays out."""
    from due_crew import plans as P, due
    col = _plan_col()
    col.db.conn.execute("UPDATE cards SET queue = 2, type = 2 WHERE id = 5")
    col.db.conn.execute("UPDATE cards SET queue = -3, type = 0 WHERE id = 6")
    idx = P.DeckIndex(col, 10)
    check("siblings: c2 buried behind a studied c1 counts as seen", idx.counts({5, 6}) == [2, 2, 2], str(idx.counts({5, 6})))
    check("siblings: counted, and buried today", idx.siblings({5, 6}) == (1, 1))
    doc = {"units": [{"id": "u", "name": "Cloze", "opens": "2026-01-01", "due": "2026-01-02"}]}
    check("siblings: a past date isn't behind for them", P.ahead_behind(doc, {"u": idx.counts({5, 6})}, "2026-03-01") == [])
    col.db.conn.execute("UPDATE cards SET queue = -1 WHERE id = 6")
    idx = P.DeckIndex(col, 10)
    check("siblings: a suspended sibling isn't seen", idx.counts({5, 6}) == [1, 1, 2] and idx.siblings({5, 6}) == (0, 0))
    col.db.conn.execute("UPDATE cards SET queue = 0 WHERE id = 6")
    idx = P.DeckIndex(col, 10)
    check("siblings: unburied, they come back later", idx.siblings({5, 6}) == (1, 0))
    x = {"pid": "p", "uid": "u", "name": "Cloze", "opens": "2026-01-01", "seen": 2, "total": 2}
    check("siblings: Due says when they come back",
          due._date_row(dict(x, sibs=[12, 12]), set(), "2026-03-01")["n"] == "done \u00b7 12 siblings tomorrow"
          and due._date_row(dict(x, sibs=[1, 0]), set(), "2026-03-01")["n"] == "done \u00b7 1 sibling later"
          and due._date_row(x, set(), "2026-03-01")["n"] == "all seen"
          and due._date_row(dict(x, sibs=[1, 0]), set(), "2026-03-01")["done"])
    # 3.7.3: a review card of an older note, due today, buries its new sibling;
    # that sibling was seen before today, so it isn't today's progress, nor behind
    from due_crew import plan_flow as F
    col.db.conn.execute("UPDATE cards SET queue = -3 WHERE id = 6")
    idx = P.DeckIndex(col, 10)
    check("siblings: buried today for a note started before today isn't today's", idx.buried_today({5, 6}, {}) == 0)
    check("siblings: buried today for a note started today is", idx.buried_today({5, 6}, {5: 0}) == 1)
    plan = {"id": "p", "doc": {"deck": "Step 1", "units": [
        {"id": "u", "name": "Cloze", "opens": _day(-3), "cards": [["guid000050", 0], ["guid000050", 1]]}]}}
    v = F.session_view(plan, {"deck_id": 10}, idx, {}, _day(0))
    check("behind: a sibling buried by an older note's review today isn't behind", v["behind"] == 0 and v["done"] == 0, v)
    v = F.session_view(plan, {"deck_id": 10}, idx, {5: 0}, _day(0))
    check("behind: a past date's cards seen today (one buried by a note started today) clear it",
          v["done"] == 0 and v["behind"] == 0, v)
    # 3.8.0: a day's new cards count the siblings Anki buried behind the ones seen,
    # so a cloze-heavy day isn't a missed one (the missed-days question, the recap)
    for o in (2, 3, 4):  # a five-card cloze: Anki shows c1, buries c2-c5
        fakes.add_card(col.db.conn, 60 + o, did=10, queue=-3, nid=50, ord_=o)
    idx = P.DeckIndex(col, 10)
    plan2 = {"id": "p", "sched": {"days": [1] * 7, "minutes": 60}, "doc": {"deck": "Step 1", "units": [
        {"id": "u", "name": "Cloze", "opens": _day(-1), "cards": [["guid000050", o] for o in range(5)]}]}}
    v2 = F.session_view(plan2, {"deck_id": 10}, idx, {5: 1}, _day(0))
    check("siblings: a day whose note started then, its buried sibling with it, isn't missed", _day(-1) not in v2["missed"], v2["missed"])


def test_bug_squash_oct():
    """The October bug run: settings that never reach the account or that a
    new computer's defaults overwrite; show-up and pause leaking numbers;
    recover leeches touching a leech's siblings; a stale deck index; Hold
    back re-closing early dates; Behind counting even dates' shut slices;
    placeholders in names; Overview's description trusted."""
    from due_crew import account, app as appmod, plans as P, due_flow as F, room_model as rm, cards as K
    from due_crew.app import _state
    import due_crew as dc
    saved = (account.cfg, account.client, appmod.save_cfg, appmod._bg, appmod.swap, account.mw.col)

    def _bg(job, done=None):
        try:
            r = job()
        except Exception:
            r = None
        if done:
            done(r)
    try:
        appmod._bg, appmod.swap, account.mw.col = _bg, None, None
        store = world({"sam": "Sammy"}, {})
        a = new_client(store, "sam", "Sammy")
        a.put_settings("2026-10-01T00:00:00.000000Z", {"shared_decks": [{"id": 11, "name": "Big"}], "muted": ["troll"],
                       "share_retention": False})
        b = new_client(store, "sam", "Sammy")
        box = {"cfg": {"share_retention": True, "shared_decks": [], "emoji": ""}}
        account.cfg, account.client = (lambda: dict(box["cfg"])), (lambda: b)
        appmod.save_cfg = lambda c, from_account=False: box["cfg"].update(c)
        _state.update(settings_ready=False, settings_pulling=False)
        real = b.get_settings
        b.get_settings = lambda: (None, 0)  # the first pull doesn't answer
        account.ensure()
        b.get_settings = real
        box["cfg"]["emoji"] = "\U0001F525"
        account.on_change(box["cfg"])
        kept = store.settings["sam"]["settings"]
        check("settings: a new computer whose first pull failed doesn't put its defaults over the account",
              kept.get("muted") == ["troll"] and kept.get("share_retention") is False, kept)

        # an edit whose upload failed goes at the next good pull
        _state.update(settings_ready=False, settings_pulling=False)
        b.session["settings_day"] = ""
        account.ensure()  # pulled now: this computer holds the account's save
        real_put = b.put_settings
        b.put_settings = lambda at, s: False  # offline
        box["cfg"]["share_retention"] = True
        account.on_change(box["cfg"])
        b.put_settings = real_put
        check("settings: the failed upload leaves the edit dirty", b.session.get("settings_dirty") is True)
        _state.update(settings_ready=False, settings_pulling=False)
        b.session["settings_day"] = ""
        account.ensure()
        check("settings: the next pull with nothing newer up there sends it",
              store.settings["sam"]["settings"].get("share_retention") is True and not b.session.get("settings_dirty"),
              store.settings["sam"])
    finally:
        account.cfg, account.client, appmod.save_cfg, appmod._bg, appmod.swap, account.mw.col = saved

    # recover leeches: a leech's never-lapsed sibling stays shut
    col = _plan_col()
    col.db.conn.execute("UPDATE cards SET type = 2, lapses = 8, queue = -1 WHERE id = 5")
    col.db.conn.execute("UPDATE notes SET tags = ' leech ' WHERE id = 50")
    col.db.conn.execute("UPDATE cards SET type = 0, lapses = 0, queue = -1 WHERE id = 6")
    sql = []
    real_all = col.db.all
    col.db.all = lambda q, *a: (sql.append(q), real_all(q, *a))[1]
    try:
        F.recover_leeches(col)
    except Exception:
        pass
    col.db.all = real_all
    check("recover leeches: only cards that lapsed themselves", any("c.lapses > 0" in q for q in sql), sql)

    # the deck index sees a retag older than the newest note
    col = _plan_col()
    idx = P.DeckIndex(col, 10)
    col.db.conn.execute("UPDATE notes SET tags = 'Step1::Renal::New', mod = 1 WHERE id = (SELECT nid FROM cards WHERE id = 3)")
    check("deck index: a note edited with an older mtime is read again",
          P.DeckIndex(col, 10).tag_cards("Step1::Renal::New") == {3})

    # hold back leaves dates opened early alone; Behind counts what's open
    doc = {"units": [{"id": "a", "opens": "2026-09-01", "tags": ["Step1::Cardio::Arrhythmia"]},
                     {"id": "b", "opens": "2026-09-03", "tags": ["Step1::Renal"]}]}
    col = _plan_col()
    col.db.conn.execute("UPDATE cards SET queue = 0, type = 0 WHERE id IN (3, 8)")
    idx = P.DeckIndex(col, 10)
    check("hold back: a later date already opened here isn't held",
          P.holdable(idx, doc, "2026-09-01", applied={"b": "sig"}) == set()
          and 8 in P.holdable(idx, doc, "2026-09-01") | {8})
    check("Behind: opened and unseen only (an even date's later slices are shut on purpose)",
          P.waiting_new({"units": [{"id": "u", "opens": "2026-09-01"}]}, {"u": [2, 2, 10]}, "2026-09-05") == 0)

    # a crewmate's name holding a placeholder stays text
    js = rm.widget_js("bottom", {"title": "Al__KEY__x", "names": ["Al__KEY__x"]})
    check("widgets: a name with __KEY__ in it isn't replaced", "Al__KEY__x" in js and K.float_js({"text": "__KEY__"}).count("__KEY__") == 1)

    # Overview runs a deck's description: not one of our pages
    import inspect
    check("trust: Overview (a deck's description runs there) isn't one of our pages",
          '"aqt.overview"' not in inspect.getsource(dc._our_page))


def test_plans_ids_e1():
    """E1: note ids and card ids pasted onto a date: a note id brings every
    card of it, a card id that one card, only inside the plan's deck; they
    change the date's sig; the author's Anki counts them as "#ids"."""
    from due_crew import plans as P
    from due_crew.backend import shapes
    col = _plan_col()
    idx = P.DeckIndex(col, 10)
    check("ids: a note id brings both cards of the cloze", idx.match({"nids": [50]}) == {5, 6})
    check("ids: a card id brings just that card", idx.match({"cids": [6]}) == {6})
    check("ids: never outside the deck the plan runs on", idx.match({"nids": [7], "cids": [7]}) == set())
    check("ids: an id this copy doesn't have finds nothing", idx.match({"nids": [999999]}) == set())
    base = {"id": "u1", "tags": [], "decks": [], "cards": []}
    check("ids: new ids give the date a new sig (so they open)",
          P.unit_sig(base) != P.unit_sig(dict(base, nids=[50])) != P.unit_sig(dict(base, nids=[50], cids=[3])))
    counts = P.search_counts(idx, {"units": [dict(base, nids=[50, 999999], cids=[1])]})
    check("ids: the author's Anki counts what they find", counts["u1"]["#ids"] == 3, str(counts))
    u = shapes._clean_unit({"id": "u1", "name": "x", "opens": "2026-10-06", "nids": [50, "x", True, -1, 7], "cids": []})
    check("ids: cleaned on arrival to positive whole numbers", u.get("nids") == [50, 7] and "cids" not in u, str(u))
    rows = P.match_rows(idx, {"deck": "Step 1", "units": [{"id": "a", "name": "Staph", "opens": "2026-10-06",
                                                          "tags": [], "decks": [], "cards": [], "nids": [50]}]})
    check("ids: the follow dialog's row says what they found", rows == [("Staph", "2 cards", False)], str(rows))


def test_plans_portable_picks_365():
    """3.6.5: a date's pasted ids also travel as the cards the author's Anki
    found (`idr`, guid + card number), so a copy whose ids differ still finds
    them; `notes` picks every card of a note by its guid; ids that only mean
    something in one collection can't be a search."""
    from due_crew import plans as P
    from due_crew.backend import shapes
    col = _plan_col()
    idx = P.DeckIndex(col, 10)
    g50 = "guid000050"
    check("notes: a note's guid brings every card of it", idx.match({"notes": [g50]}) == {5, 6})
    check("notes: a guid this copy lacks finds nothing", idx.match({"notes": ["nope"]}) == set())
    # the author's copy: note 50 is a cloze; the refs are what its ids found
    unit = {"id": "u1", "nids": [50], "cids": [3]}
    refs = P.id_refs(idx, col, {"units": [dict(unit, tags=[]), {"id": "u2", "tags": ["x"]}]})
    check("refs: one entry a date with ids, the ids it was worked out from",
          list(refs) == ["u1"] and refs["u1"][:2] == [[50], [3]], str(refs))
    check("refs: the cards as guid and card number",
          sorted(map(tuple, refs["u1"][2])) == [("guid000003", 0), (g50, 0), (g50, 1)], str(refs))
    check("refs: capped", len(P.id_refs(idx, col, {"units": [unit]}, cap=2)["u1"][2]) == 2)
    # a classmate whose copy gave the same notes other ids
    other = sqlite3.connect(":memory:")
    fakes.make_collection(other)
    fakes.add_card(other, 103, did=10, queue=-1, nid=903)
    fakes.add_card(other, 105, did=10, queue=-1, nid=950, ord_=0)
    fakes.add_card(other, 106, did=10, queue=-1, nid=950, ord_=1)
    other.execute("UPDATE notes SET guid = 'guid000003' WHERE id = 903")
    other.execute("UPDATE notes SET guid = ? WHERE id = 950", (g50,))
    ocol = fakes.FakeCol(other, fakes.day_cutoff_for(TODAY))
    ocol.decks = fakes.FakeDecks({10: "Step 1"})
    oidx = P.DeckIndex(ocol, 10)
    check("refs: without them, other ids find nothing", oidx.match(unit) == set())
    check("refs: with them, the same cards", oidx.match(dict(unit, idr=refs["u1"][2])) == {103, 105, 106})
    check("notes: by guid in any copy", oidx.match({"notes": [g50]}) == {105, 106})
    check("missing: single cards and notes this copy lacks, of all of them",
          oidx.exact_missing({"cards": [[g50, 1], ["gone", 0]], "notes": [g50, "gone2"]}) == (2, 4))
    base = {"id": "u1", "tags": [], "decks": [], "cards": [], "nids": [50]}
    check("sig: notes, or refs arriving, give the date a new sig (so what they add opens)",
          len({P.unit_sig(base), P.unit_sig(dict(base, notes=[g50])), P.unit_sig(dict(base, idr=[[g50, 0]]))}) == 3)
    check("sig: a date with neither keeps the sig it had", P.unit_sig(base) == P.unit_sig(dict(base, notes=[], idr=[])))
    counts = P.search_counts(idx, {"units": [{"id": "n", "notes": [g50, "gone"]}]})
    check("notes: counted by the author's Anki", counts["n"]["#ids"] == 2 and counts["n"]["#pn"] == [2, 0, 1], str(counts))
    pn = P.date_counts(idx, {"deck": "Step 1", "units": [
        {"id": "b", "opens": "2026-10-06", "tags": ["Step1::Cardio"], "decks": []},
        {"id": "a", "opens": "2026-10-05", "tags": ["Step1::Cardio::Heart_failure"], "decks": [], "notes": [g50, "gone"]}]})
    check("counts (P1): in date order, what's new to a date, what an earlier one opens, notes not here",
          pn == {"a": [4, 0, 1], "b": [1, 2, 0]}, str(pn))
    rows = P.match_rows(idx, {"deck": "Step 1", "units": [{"id": "a", "name": "Staph", "opens": "2026-10-06",
                                                          "tags": [], "decks": [], "cards": [], "notes": [g50]}]})
    check("notes: the follow dialog's row says what they found", rows == [("Staph", "2 cards", False)], str(rows))
    u = shapes._clean_unit({"id": "u1", "name": "x", "opens": "2026-10-06", "notes": [g50, 5, ""],
                            "idr": [[g50, 0], ["x"], [g50, "1"], [3, 0]]})
    check("clean: notes are guids, refs [guid, number]",
          u.get("notes") == [g50] and u.get("idr") == [[g50, 0]], str(u))
    for q in ("nid:50", "cid:3,4", "deck:x nid:1"):
        check(f"search: {q} means nothing in someone else's Anki", not P.shareable_search(q))
    check("search: a plain one still goes", P.shareable_search("tag:x nidus"))


def test_plans_selector_365():
    """3.6.5: Anki's browser copies picked notes or cards as plan text that
    reads the same in anyone's copy: guids, card numbers from 1."""
    from due_crew import plans as P
    col = _plan_col()
    check("selector: notes by guid", P.selector(col, nids=[50, 3, 50]) == ("notes:guid000003 guid000050", 2))
    check("selector: cards as guid:number", P.selector(col, cids=[6, 5]) == ("cards:guid000050:1 guid000050:2", 2))
    check("selector: nothing picked", P.selector(col) == ("", 0))
    idx = P.DeckIndex(col, 10)
    text, _n = P.selector(col, cids=[6])
    g, n = text[len("cards:"):].rsplit(":", 1)
    check("selector: reads back to that card", idx.match({"cards": [[g, int(n) - 1]]}) == {6})


def test_export_for_my_ai_365():
    """3.6.5, P3: a plan's notes, or a deck's, in Anki's own plain-text
    format with the unique identifier first, for the person's own AI. To
    a file only; formatting and media out unless asked."""
    from due_crew import plans as P
    col = _plan_col()
    col.db.conn.execute("UPDATE notes SET flds = ? WHERE id = 1", ("<b>Heart</b> failure\x1f{{c1::BNP}} rises<br>[sound:x.mp3]\tand \"so\"",))
    idx = P.DeckIndex(col, 10)
    doc = {"deck": "Step 1", "units": [{"id": "hf", "opens": "2026-10-05", "tags": ["Step1::Cardio::Heart_failure"], "decks": []}],
           "pace": {"cover": ["tag:Step1::Cardio", "deck:Step 1::Extras"]}}
    check("export: what the plan's dates open, as notes", P.export_scope(idx, doc, "dates") == {1, 2})
    check("export: what the plan covers (the builder's ticks)", P.export_scope(idx, doc, "cover") == {1, 2, 3, 4})
    check("export: the whole deck", P.export_scope(idx, doc, "deck") == {1, 2, 3, 4, 50, 8, 9})
    text, n = P.export_notes(col, {1, 50})
    lines = text.splitlines()
    check("export: Anki's header, the guid column first", lines[:6] == ["#separator:tab", "#html:false", "#guid column:1",
          "#notetype column:2", "#deck column:3", "#tags column:4"] and n == 2, str(lines[:6]))
    row = next(x for x in lines if x.startswith("guid000001"))
    cells = row.split("\t")
    check("export: a row is guid, notetype, deck, tags, then the fields, as plain text",
          cells[2] == "Step 1" and "Step1::Cardio::Heart_failure" in cells[3] and cells[4] == "Heart failure"
          and cells[5] == '"{{c1::BNP}} rises and ""so"""', str(cells))
    check("export: one line a note, no tabs inside a field", len(lines) == 8 and all(x.count("\t") >= 4 for x in lines[6:]))
    raw, _ = P.export_notes(col, {1}, plain=False)
    check("export: formatting kept when asked", "#html:true" in raw and "<b>Heart</b>" in raw)
    check("export: a size estimate errs high", P.export_size(col, {1, 50}) >= len(text) - 200)


def test_feedback_365():
    """3.6.5, P6: Send feedback, from Tools › Due Crew and Settings
    (the board's You tab, and the dialog), with the versions if ticked."""
    from due_crew import app as appmod
    store = world({"maya": "Maya"})
    maya = new_client(store, "maya", "Maya")
    check("feedback: sent with the versions, once", maya.send_feedback("  Plans tab is great  ", "add-on 3.6.5 ·\nAnki 24.11") == 201
          and store.feedback == [{"uid": "maya", "text": "Plans tab is great", "ver": "add-on 3.6.5 · Anki 24.11"}])
    for i in range(4):
        maya.send_feedback(f"more {i}")
    check("feedback: five a day", maya.send_feedback("one too many") == 429 and len(store.feedback) == 5)
    v = appmod.feedback_versions("3.6.5")
    check("feedback: the versions line", v.startswith("add-on 3.6.5 · Anki ") and v.count(" · ") == 2, v)
    html = board.settings_html({"tab": "you", "signed_in": True, "name": "Maya"}, {})
    check("feedback: a row on Settings › You, sent as setfeedback", "duecrew:setfeedback" in html and "Feedback" in html)
    check("feedback: not on the signed-out You tab", "setfeedback" not in board.settings_html({"tab": "you", "signed_in": False}, {}))
    import due_crew as dc
    from aqt.deckbrowser import DeckBrowser
    if "aqt.reviewer" not in sys.modules:
        sys.modules["aqt.reviewer"] = types.SimpleNamespace(Reviewer=type("Reviewer", (), {}))
    opened, saved = [], dc.open_feedback
    dc.open_feedback = lambda: opened.append(1)
    try:
        dc._on_js(False, "duecrew:setfeedback", DeckBrowser())
    finally:
        dc.open_feedback = saved
    check("feedback: the board's click reaches it", opened == [1])


def test_plans_what_in_a_day_p7():
    """3.6.5, P7: a date's topics on the Plans tab, as the site's print list
    groups them, with Browse; and one line of today's in the Today box."""
    from due_crew import plans as P
    u = {"id": "a", "name": "SLGs 1-3", "opens": "2026-10-03",
         "tags": ["#Big_Step1_v12::#V&B::02_Basic_Pharmacology::01_General::05_Pharmacokinetics",
                  "#Big_Step1_v12::#Lectures::Pharmacology::02_Pharmacokinetics::02_Drug_Elimination",
                  "#Big_Step1_v12::#Lectures::Pharmacology::02_Pharmacokinetics::05_Effect_of_Urine_pH",
                  "Step1::Renal"],
         "decks": ["Big Step 1::03_Extras"], "search": ["tag:x"], "notes": ["g1", "g2"], "nids": [5], "cards": [["g", 0]]}
    got = P.topics(u)
    check("topics: grouped by the resource part after the root, readable, order numbers off",
          got[:2] == [["V&B", ["Pharmacokinetics"]], ["Lectures", ["Drug Elimination", "Effect of Urine pH"]]], str(got))
    check("topics: tags with no resource part, and subdecks, under no heading",
          ["", ["Renal", "Extras"]] in got, str(got))
    check("topics: searches, notes picked by ID, single cards",
          ["Search", ["tag:x"]] in got and ["Picked by ID", ["3 notes"]] in got and ["Picked", ["1 single card"]] in got, str(got))
    line = P.topics_line([u, {"id": "b", "tags": ["#Big::#V&B::05_Biostats::07_Clinical_Trials"]}])
    check("today's line: one line, the same resource's topics together",
          line.startswith("V&B: Pharmacokinetics, Clinical Trials · Lectures: Drug Elimination"), line)
    from due_crew import board
    week = [{"day": "2026-10-03", "dow": "Sat", "num": 3, "today": True, "past": False, "rest": False, "prep": False, "events": [],
             "new": 109, "seen": 0, "units": [{"uid": "a", "name": "SLGs <1-3>", "total": 85, "seen": 0, "state": "open",
                                               "prep": False, "what": [["V&B", [["Pharma<b>", 0]]]]}]}]
    card = {"id": "p1", "title": "Plan", "sub": "", "rows": [], "lines": [], "change": None, "no_deck": False, "paused": False,
            "week": week, "week_offset": 0, "session": {"kind": "study", "target": 109, "done": 0, "due": 0, "behind": 0}}
    h = board._plan_card_html(card)
    check("day: what's in a block, escaped, with Browse sent as planbrowse",
          '<span class="g"><b>V&amp;B</b> &middot; <a class="tp"' in h and "Pharma&lt;b&gt;</a></span>" in h
          and "duecrew:planbrowse:p1:a" in h and "Browse 85 cards" in h and "<b>Pharma" not in h)
    check("day: 3.8.0, each topic opens its cards (plan, date, its place)", "duecrew:plantopic:p1:a:0" in h, h)
    check("today: 3.8.0, no Today box on the plan (Due's Today has today's dates and their topics)",
          'class="tw"' not in h and 'class="ptoday' not in h and "planstudy:p1" not in h, h)
    import due_crew as dc
    from due_crew import plan_flow as F
    from aqt.deckbrowser import DeckBrowser
    if "aqt.reviewer" not in sys.modules:
        sys.modules["aqt.reviewer"] = types.SimpleNamespace(Reviewer=type("Reviewer", (), {}))
    asked, saved = [], F.browse_date
    F.browse_date = lambda pid, uid: asked.append((pid, uid))
    try:
        dc._on_js(False, "duecrew:planbrowse:p1:a", DeckBrowser())
    finally:
        F.browse_date = saved
    check("browse: the board's click reaches it", asked == [("p1", "a")], str(asked))
    asked, saved = [], F.browse_topic
    F.browse_topic = lambda pid, uids, i: asked.append((pid, uids, i))
    try:
        dc._on_js(False, "duecrew:plantopic:p1:a-b:1", DeckBrowser())
        dc._on_js(False, "duecrew:plantopic:p1:a:x", DeckBrowser())
    finally:
        F.browse_topic = saved
    check("topic: the board's click reaches it, its dates and its place; a bad place is no place",
          asked == [("p1", ["a", "b"], 1), ("p1", ["a"], -1)], str(asked))


def test_browse_from_the_board_380():
    """3.8.0: what's left on a day, what's behind, a plan's leeches, a topic,
    and Browse › Show on my plan, each finding its own cards here, from the
    board's click (or the browser's menu)."""
    from due_crew import plans as P, plan_flow as F, board, due as DUE
    from due_crew.app import _state
    import due_crew as dc
    from aqt import mw
    from aqt.deckbrowser import DeckBrowser
    col = _plan_col()
    conn = col.db.conn
    conn.execute("UPDATE cards SET queue = 0 WHERE id = 1")  # Heart failure: 1 opened, 2 still shut
    fakes.add_card(conn, 10, did=10, ctype=2, queue=-1, tags="Step1::Cardio::Heart_failure leech")  # a leech Anki set aside
    plan = {"id": "pB", "name": "Step", "doc": {"deck": "Step 1", "units": [
        {"id": "a", "name": "Heart", "opens": _day(-1), "tags": ["Step1::Cardio::Heart_failure"]},
        {"id": "b", "name": "Renal", "opens": _day(-2), "tags": ["Step1::Renal"]},
        {"id": "c", "name": "Rhythm", "opens": _day(4), "tags": ["Step1::Cardio::Arrhythmia"]}]}}
    shown, said = [], []
    saved = (F.followed, F._state_cfg, F._today, F._browse, F.tooltip, F.app.swap, F.save_cfg, mw.col)
    try:
        F.followed = lambda: [plan]
        applied = {"a": _day(-1), "b": _day(-2)}
        F._state_cfg = lambda c=None: {"pB": {"deck_id": 10, "applied": applied}}
        F._today = lambda: _day(0)
        F._browse = lambda cids, q=None, empty="": shown.append((sorted(cids), q)) if cids else said.append(empty)
        F.tooltip = lambda msg, **k: said.append(msg)
        F.app.swap = lambda c=None: None
        F.save_cfg = lambda c: None
        mw.col = col
        dc._on_js(False, "duecrew:planleft:pB:a", DeckBrowser())
        check("left: a date's cards I haven't seen, shut ones too (its \"left\" counts them); a seen leech isn't left",
              shown[-1][0] == [1, 2], shown)
        dc._on_js(False, "duecrew:planleft:pB:a-b", DeckBrowser())
        check("left: a day's two dates together; a seen card isn't left", 8 not in shown[-1][0] and 1 in shown[-1][0], shown)
        dc._on_js(False, "duecrew:planleft:pB", DeckBrowser())
        check("behind: every date before today, what's opened and not seen", shown[-1][0] == [1], shown)
        applied["a"] = "skip:" + _day(-1)
        n = len(shown)
        dc._on_js(False, "duecrew:planleft:pB", DeckBrowser())
        check("behind: a date skipped here isn't behind, as Due counts it (the review)",
              len(shown) == n and said[-1] == "Nothing left to see.", (shown[-1], said[-1:]))
        applied["a"] = _day(-1)
        dc._on_js(False, "duecrew:plantopic:pB:c:0", DeckBrowser())
        check("topic: a date ahead's topic finds its cards", shown[-1][0] == [3], shown)
        n = len(shown)
        dc._on_js(False, "duecrew:planleft:pB:zz", DeckBrowser())
        check("left: a date that isn't there finds nothing, and says so", len(shown) == n and said[-1] == "Nothing left to see.", said)
        browser = types.SimpleNamespace(selected_cards=lambda: [3])
        F.show_on_plan(browser)
        week = (datetime.date.fromisoformat(P.week_start(_day(4))) - datetime.date.fromisoformat(P.week_start(_day(0)))).days // 7
        check("show on my plan: the Plans tab on that date's week, the day open",
              _state["plan_week"].get("pB") == week and _state["plan_focus"] == {"pB": _day(4)} and "Rhythm" in said[-1], said[-1])
        F.show_on_plan(types.SimpleNamespace(selected_cards=lambda: [7]))
        check("show on my plan: a card in no plan I follow says so", said[-1] == "It isn't on a plan you follow.", said[-1])
        wk = P.week_view(F.mine(plan)["doc"], {}, _day(0), P.week_start(_day(4)))
        html = board._week_html({"week": wk, "week_offset": week, "focus": _day(4)}, "pB")
        i = next(k for k, d in enumerate(wk) if d["day"] == _day(4))
        check("show on my plan: the board opens that day's details", f'id="dc-pd-pB-{i}"' in html
              and f'id="dc-pd-pB-{i}" hidden' not in html, html[-600:])
        dc._on_js(False, "duecrew:planweek:pB:0", DeckBrowser())
        check("show on my plan: moving the week lets go of the day", "plan_focus" not in _state)
    finally:
        (F.followed, F._state_cfg, F._today, F._browse, F.tooltip, F.app.swap, F.save_cfg, mw.col) = saved
        _state.pop("plan_focus", None)
        _state.get("plan_week", {}).pop("pB", None)
    # the board: a date's details say what's left, the Today box's behind, the leeches line, Due's rows
    week = [{"day": _day(0), "dow": "Sat", "num": 3, "today": True, "past": False, "rest": False, "prep": False, "events": [],
             "new": 40, "seen": 10, "units": [{"uid": "a", "name": "Heart", "total": 40, "seen": 10, "state": "open", "prep": False,
                                               "what": [["", [["Heart failure", 0]]]]}]}]
    card = {"id": "pB", "title": "Plan", "sub": "", "rows": [], "lines": [], "change": None, "no_deck": False, "paused": False,
            "week": week, "week_offset": 0, "waiting": 16,
            "aside": [3, 0, 0], "aside_ok": [0, 0], "session": {"kind": "study", "target": 40, "done": 10, "due": 0, "behind": 0}}
    h = board._plan_card_html(card)
    check("details: Browse 40 cards and the 30 left", "duecrew:planbrowse:pB:a" in h and "duecrew:planleft:pB:a" in h and "30 left</a>" in h, h)
    check("waiting: new from earlier days, with Catch up (Due's Behind opens them)",
          "<b>16</b> new from earlier days waiting" in h and "duecrew:plancatch:pB" in h, h)
    check("leeches: 3.8.0, not on the plan (they're the deck's: Insights)", "leech" not in h, h)
    dv = DUE.view(_day(0), [{"pid": "pB", "uid": "a", "plan": "Step", "name": "Heart", "opens": _day(0), "seen": 1, "total": 4,
                             "counted": True, "what": "Heart failure", "topics": [["", [["Heart failure", 0]]]]},
                            {"pid": "pB", "uid": "b", "plan": "Step", "name": "Renal", "opens": _day(-2), "seen": 1, "total": 9,
                             "counted": True, "what": "Renal", "topics": []}], [], {})
    dh = board._due_html(dv)
    check("due: a date's topics open their cards; Behind's cards to see open what's behind",
          "duecrew:plantopic:pB:a:0" in dh and "pycmd('duecrew:planleft:pB')" in dh and "8 cards to see</a>" in dh, dh)


def test_topic_items_380():
    """3.8.0: what each topic name stands for, so its click finds its cards:
    the same names and order as topics(), merged across dates by group and
    name, each with its own sources (unit-shaped, for DeckIndex.match)."""
    from due_crew import plans as P
    a = {"id": "a", "tags": ["#Big::#V&B::05_Biostats::07_Clinical_Trials", "Step1::Renal", "#Big::#Lectures::Pharm::02_Drug_Elimination"],
         "decks": ["Big Step 1::03_Extras"], "search": ["tag:x"], "notes": ["g1"], "nids": [5], "idr": [["g1", 0]], "cards": [["g", 0]]}
    b = {"id": "b", "tags": ["#Big::#V&B::05_Biostats::07_Clinical_Trials::01_Bias", "#Big::#V&B::02_Pharm::03_Kinetics"]}
    items = P.topic_items([a, b])
    names = [(g, x) for g, x, _s in items]
    check("topic items: one per group and name, in first-seen order",
          names == [("V&B", "Clinical Trials"), ("", "Renal"), ("Lectures", "Drug Elimination"), ("", "Extras"),
                    ("Search", "tag:x"), ("Picked by ID", "2 notes"), ("Picked", "1 single card"), ("V&B", "Bias"),
                    ("V&B", "Kinetics")], names)
    src = {(g, x): s for g, x, s in items}
    check("topic items: each with what it stands for",
          src[("", "Renal")] == {"tags": ["Step1::Renal"]} and src[("", "Extras")] == {"decks": ["Big Step 1::03_Extras"]}
          and src[("Search", "tag:x")] == {"search": ["tag:x"]}
          and src[("Picked by ID", "2 notes")] == {"notes": ["g1"], "nids": [5], "idr": [["g1", 0]]}
          and src[("Picked", "1 single card")] == {"cards": [["g", 0]]}, src)
    view = P.topic_view([a, b])
    check("topic view: grouped for the page, each name with its place in the items",
          view[0] == ["V&B", [["Clinical Trials", 0], ["Bias", 7], ["Kinetics", 8]]] and ["", [["Renal", 1], ["Extras", 3]]] in view, view)
    check("topics and the Today line read as before",
          P.topics(a)[0] == ["V&B", ["Clinical Trials"]]
          and P.topics_line([a, b]).startswith("V&B: Clinical Trials, Bias, Kinetics · Renal, Extras · Lectures: Drug Elimination"),
          P.topics_line([a, b]))
    idx = P.DeckIndex(_plan_col(), 10)
    got = [idx.match(s) for _g, _x, s in P.topic_items([{"id": "u", "tags": ["Step1::Cardio::Heart_failure", "Step1::Renal"]}])]
    check("topic items: each finds just its own cards here (children too, this deck only)", got == [{1, 2}, {8}], got)


def test_plans_matching_v31():
    """3.1: a unit's tags (children too, any case), subdecks, and single
    cards (that card, never its sibling), inside the chosen deck only."""
    from due_crew import plans as P
    col = _plan_col()
    idx = P.DeckIndex(col, 10)
    u = {x["id"]: x for x in _plan_units()}
    check("match: a tag brings its children, in any case, and nothing that only starts like it",
          idx.match(u["hf"], None, "Step 1") == {1, 2})
    check("match: only inside the deck it runs on", 7 not in idx.match(u["hf"], None, "Step 1"))
    check("match: a subdeck by its path under the plan's deck", idx.match(u["ex"], None, "Step 1") == {4})
    check("match: a single card is that card, not its cloze sibling",
          idx.match(u["cz"], None, "Step 1") == {6})
    check("match: a whole tag tree", idx.match({"tags": ["Step1::Cardio"]}) == {1, 2, 3})
    other = _plan_col("Step1_v11")
    oidx = P.DeckIndex(other, 10)
    doc = {"deck": "Step 1", "units": _plan_units()}
    swap = P.detect_swap(oidx, doc)
    check("swap: my tags start differently, and the add-on sees how", swap == ("Step1", "Step1_v11"), str(swap))
    check("swap: read through it, the plan lines up",
          oidx.match(u["hf"], swap, "Step 1") == {1, 2} and oidx.match(u["hf"], None, "Step 1") == set())
    check("swap: none when the tags already line up", P.detect_swap(idx, doc) is None)
    check("best deck: the one named like the plan's", P.best_deck(col, doc) == (10, None))
    col.decks = fakes.FakeDecks({10: "Big Deck v11", 11: "Big Deck v11::Extras", 20: "Other"})
    check("best deck: else the one where most of it is found", P.best_deck(col, doc)[0] == 10)
    prog = P.progress(idx, doc)
    check("progress: [opened, seen, total] per unit",
          prog["hf"] == [0, 0, 2] and prog["rn"] == [1, 1, 1] and prog["cz"] == [0, 0, 1])
    tags, decks = P.DeckIndex(_plan_col(), 10).tree()
    check("tree: names and counts only, a tag counting everything under it",
          ["Step1::Cardio", 3] in tags and ["Step 1::Extras", 1] in decks
          and all(isinstance(n, int) for _p, n in tags + decks))
    FD = P
    counted = dict(u["hf"], n=3)  # the author's copy had 3 under that tag; this one has 2
    rows = FD.match_rows(idx, {"deck": "Step 1", "units": [counted, u["ar"], u["cz"]]})
    check("follow: found of the author's count when the plan has one, else cards found",
          rows[0] == ("Heart failure", "2 of 3", False) and rows[1] == ("Arrhythmia", "1 card", False)
          and rows[2] == ("Cloze two", "1 of 1", False), str(rows))
    missing = FD.match_rows(idx, {"deck": "Step 1", "units": [dict(u["rn"], tags=["Nope"], n=40)]})
    check("follow: a date with none of its cards here says so", missing == [("Renal", "not in your copy", True)])
    check("code: typed, spaced, or a pasted link",
          P.code_from("7kq4 mx2d") == "7KQ4MX2D" == P.code_from("https://duecrew.com/p/7KQ4MX2D"))


def test_plans_morning_v31():
    """3.1: the morning opens what's due in one undo step and never
    suspends: not on a stop, not when a unit goes, not when a date moves
    later. Late joins both ways, dates moved earlier, cards added."""
    from due_crew import plan_flow as F
    from due_crew import plans as P
    store = world({"dre": "Dre", "maya": "Maya"})
    pid, code = store.add_plan("dre", "Step 1", "Step 1", _plan_units())
    maya = new_client(store, "maya", "Maya")
    plan, status = maya.follow_plan(code)
    plan0 = plan
    col = _plan_col()
    state = {pid: F.new_state(col, plan)}
    check("follow: runs on the deck named like the plan's", status == 200 and state[pid]["deck_id"] == 10)
    res = F.run(col, [plan], state, _day(0))
    check("morning: what has opened opens, and only that",
          _open(col) == {1, 2, 3, 8} and res["n"] == 3, str(_open(col)))
    check("morning: one undo step, named for it",
          [s[0] for s in col.undo_steps] == ["Due Crew: open 2 dates"]
          and sorted(col.undo_steps[0][1]) == [1, 2, 3] and res["label"] == P.step_label(["a", "b"]))
    check("morning: the toast's names and count", res["names"] == ["Heart failure", "Arrhythmia"]
          and res["per"][pid] == [["Heart failure", "Arrhythmia"], 3])
    again = F.run(col, [plan], state, _day(0))
    check("morning: a second run the same day does nothing, and makes no step",
          again["n"] == 0 and len(col.undo_steps) == 1)
    one = F.run(col, [plan], state, _day(3))
    check("morning: one unit's step says its name", col.undo_steps[-1][0] == "Due Crew: open Extras"
          and one["n"] == 1 and 4 in _open(col))
    col.undo()
    check("undo: Anki's undo puts that step's cards back, nothing else", 4 not in _open(col) and 1 in _open(col))

    # nothing suspends: a unit taken out, a date moved later, a stop
    col = _plan_col()
    state = {pid: F.new_state(col, plan)}
    F.run(col, [plan], state, _day(0))
    before = _queues(col)
    units = [dict(u, opens=_day(10), due=_day(12)) if u["id"] == "ar" else u for u in _plan_units() if u["id"] != "hf"]
    store.edit_plan(pid, units)
    moved = maya.fetch_board([_day(0)], with_decks=True)["plans"][0]
    F.run(col, [moved], state, _day(1))
    check("never suspends: a unit taken out, a date moved later", _queues(col) == before)
    later = F.run(col, [moved], state, _day(10))
    check("moved later: its cards stay open, and it isn't opened again when the date comes",
          "Arrhythmia" not in later["names"] and 3 in _open(col))
    was_open = _open(col)
    maya.unfollow_plan(pid)
    state.pop(pid)
    check("never suspends: stopping", _open(col) == was_open and store.follows.get((pid, "maya")) is None
          and not maya.session["plans"])

    # moved earlier, and cards added to an applied unit: both the next morning
    store.edit_plan(pid, _plan_units())
    plan, _ = maya.follow_plan(code)
    col = _plan_col()
    state = {pid: F.new_state(col, plan)}
    F.run(col, [plan], state, _day(0))
    store.edit_plan(pid, [dict(u, opens=_day(1)) if u["id"] == "cz" else u for u in _plan_units()])
    got, status = new_client(store, "dre", "Dre").add_plan_cards(pid, [["guid000009", 0]], unit="hf")
    check("add cards: the author puts a single card on a date", status == 200
          and got["doc"]["units"][0]["cards"] == [["guid000009", 0]] and got["version"] == store.plans[pid]["version"])
    plan = maya.fetch_board([_day(1)], with_decks=True)["plans"][0]
    res = F.run(col, [plan], state, _day(1))
    check("moved earlier: it opens the next morning (the cloze's c2, not c1)",
          6 in _open(col) and 5 not in _open(col))
    check("cards added to an opened unit open the next morning, and only they",
          9 in _open(col) and res["n"] == 2, f"{res}")

    # joining late, both ways
    plan = plan0
    col = _plan_col()
    state = {pid: F.new_state(col, plan)}
    check("late join: what's waiting", F.waiting(col, plan, state[pid], _day(0)) == (2, 3))
    F.run(col, [plan], state, _day(0), mode="skip")
    check("late join, start from the next unit: nothing opens now, or later",
          _open(col) == {8} and F.run(col, [plan], state, _day(2))["n"] == 0 and not col.undo_steps)
    F.run(col, [plan], state, _day(3))
    check("late join: the next unit opens on its morning", _open(col) == {4, 8})
    F.run(col, [plan], state, _day(3), everything=True)
    check("open everything now: the whole plan, skipped units too, in one step",
          _open(col) == {1, 2, 3, 4, 6, 8} and len(col.undo_steps) == 2
          and col.undo_steps[-1][0].startswith("Due Crew: open "))

    # Change deck: opened units open on the new deck, skipped ones stay skipped
    col = _plan_col()
    state = {pid: F.new_state(col, plan)}
    F.run(col, [plan], state, _day(0))
    col.decks = fakes.FakeDecks({10: "Step 1", 11: "Step 1::Extras", 20: "Other"})
    state[pid]["deck_id"] = 20
    F.run(col, [plan], state, _day(0))
    check("change deck: what had opened opens on the new deck", 7 in _open(col))


def test_plans_glue_v31():
    """3.1 glue: the morning waits for the AnkiWeb sync and runs once a
    day; pause; progress rides the sync only when it changed and only
    while sharing; the board's plans only on decks=1; the budget."""
    from due_crew import plan_flow as F
    from due_crew.app import _state
    store = world({"dre": "Dre", "maya": "Maya", "kai": "Kai"})
    pid, code = store.add_plan("dre", "Step 1 <i>", "Step 1", _plan_units())
    maya = new_client(store, "maya", "Maya")
    col = _plan_col()
    box = {"cfg": {}}
    toasts = []
    saved = {k: getattr(F, k) for k in ("cfg", "save_cfg", "_pcfg", "_psave", "client", "_today", "tooltip")}
    saved_col, saved_swap = F.mw.col, F.app.swap
    F.cfg = F._pcfg = lambda: box["cfg"]
    F.save_cfg = F._psave = lambda c: box.update(cfg=c)
    F.client = lambda: maya
    today = {"d": _day(0)}
    F._today = lambda: today["d"]
    F.tooltip = lambda text, **kw: toasts.append(text)
    F.mw.col = col
    F.app.swap = lambda c: None
    labels = [_day(-i) for i in range(7)]
    try:
        plan, _ = maya.follow_plan(code, team=True)  # 3.7.6: on its team, so her progress counts
        # followed here before its first date, and Anki not opened since
        box["cfg"]["plans"] = {pid: F.new_state(col, plan)}
        n = len(store.log)
        light = maya.fetch_board(labels)
        full = maya.fetch_board(labels, with_decks=True)
        again = maya.fetch_board(labels)
        check("board: plans ride the decks=1 refresh, and a light one when their stamp moved (3.7.3: never seen here)",
              len(store.log) - n == 3 and full["plans_fresh"] and light["plans_fresh"] and light["plans_update"]
              and not again["plans_fresh"] and full["plans"][0]["id"] == pid and again["plans"][0]["id"] == pid)
        F.maybe_morning(awaiting_sync=True, fresh=True)
        check("morning: waits for the day's AnkiWeb sync", _open(col) == {8} and "plans_day" not in box["cfg"])
        F.maybe_morning(awaiting_sync=False)
        check("morning: then runs, on the deck that matches, and says so",
              _open(col) == {1, 2, 3, 8} and box["cfg"]["plans_day"] == _day(0)
              and toasts == ["Due Crew opened 2 dates: 3 cards"], str(toasts))
        F.maybe_morning(awaiting_sync=False)
        check("morning: once a day", len(col.undo_steps) == 1)

        # progress: the sync carries it when it changed, while sharing
        prog = F.for_sync()
        check("progress: per unit, [opened, seen, total]", prog[pid]["hf"] == [2, 0, 2] and prog[pid]["rn"] == [1, 1, 1])
        n = len(store.log)
        maya.push(labels, {}, plans=prog)
        maya.push(labels, {}, plans=F.for_sync())
        sent = [b for m, p, b in store.bodies if p == "/sync"][-2:]
        check("progress: one sync is one request, and an unchanged one isn't sent again",
              len(store.log) - n == 2 and "plans" in sent[0] and "plans" not in sent[1])
        check("progress: the server keeps it", json.loads(store.follows[(pid, "maya")]["progress"])["hf"] == [2, 0, 2])
        kai = new_client(store, "kai", "Kai")
        kai.follow_plan(code, team=True)
        store.follows[(pid, "kai")]["progress"] = json.dumps({"hf": [2, 2, 2]})
        board_plan = maya.fetch_board(labels, with_decks=True)["plans"][0]
        check("crew: followers and units done, counts only",
              board_plan["followers"] == 2 and board_plan["crewDone"] == {"hf": 1, "rn": 1}, str(board_plan))
        maya.set_follow(pid, share=False)
        check("sharing off (3.7.6: off the team): out of everyone's counts, still mine for my own views",
              store.follows[(pid, "maya")]["progress"] is not None and (pid, "maya") not in store.team
              and maya.fetch_board(labels, with_decks=True)["plans"][0]["crewDone"] == {"hf": 1})
        check("sharing off: the sync still carries it, for my own views", pid in F.for_sync())
        maya.set_follow(pid, share=True)
        maya.push(labels, {}, plans=F.for_sync())
        check("sharing back on: the next sync sends it whole",
              json.loads(store.follows[(pid, "maya")]["progress"] or "{}").get("hf") == [2, 0, 2])

        # pause: no mornings until resumed
        maya.set_follow(pid, paused=True)
        today["d"] = _day(3)
        F.maybe_morning(awaiting_sync=False)
        check("pause: the morning skips a paused plan", 4 not in _open(col)
              and box["cfg"]["plans_day"] == _day(3))
        maya.set_follow(pid, paused=False)
        check("resume: what opened meanwhile is waiting",
              F.waiting(col, F.followed()[0], box["cfg"]["plans"][pid], _day(3)) == (1, 1))

        # the card: names escaped, crew counts, today's step, ahead and behind, the change note
        _state["labels"] = labels
        _state["plan_progress"] = F.progress(col, F.followed(), box["cfg"]["plans"])
        box["cfg"]["plans_opened"] = {"day": _day(0), "label": "Due Crew: open 2 dates",
                                      "per": {pid: [["Heart <b>failure", "Arrhythmia"], 3]}}
        col.undo_steps.append(("Due Crew: open 2 dates", []))
        today["d"] = _day(0)
        view = F.board_view(box["cfg"])
        html = board.render({"entries": [], "labels": labels, "tomorrow": "", "pending": []},
                            {"period": "today"}, 0, plans=view, you={"tab": "plans", "plans": view})
        check("card: You › Plans, the plan's title, week and followers",
              "Step 1 &lt;i&gt; · Dre’s plan" in html and "week 2 of 4 · 2 following" in html)
        check("card: the crew line; no Today box (Due's Today has today), names escaped",
              "Crew: 1 done with" in html and "ptoday" not in html and "planstudy:" not in html
              and "<b>failure" not in html, re.sub(r"<style.*?</style>", "", html, flags=re.S)[-2500:])
        check("morning: what it opened, while it's still Anki's latest step", F.morning_opened()["n"] == 3, F.morning_opened())
        from due_crew import due as DUE
        dv = dict(DUE.view(_day(0), [], [], {}), opened=F.morning_opened())
        dh = board.you_html({}, dv, {"tab": "today", "plans": view})
        check("morning: Due's Today says so, with Put off to tomorrow",
              "This morning opened 3 new cards." in dh and "duecrew:plannottoday" in dh, dh[-800:])
        ph = board.you_html({}, dv, {"tab": "plans", "plans": view, "opened": F.morning_opened()})
        check("morning: with Due on, not again on Plans", "plannottoday" not in ph)
        ph = board.you_html({}, None, {"tab": "plans", "plans": view, "opened": F.morning_opened()})
        check("morning: with Due off, on Plans", "This morning opened 3 new cards." in ph and "duecrew:plannottoday" in ph)
        check("morning: no Sync now while AnkiWeb has it all", "plansync" not in dh)
        mw = F.mw
        sv_pm, sv_col = getattr(mw, "pm", None), mw.col
        synced = []
        try:
            mw.pm = types.SimpleNamespace(sync_auth=lambda: object())
            mw.col = types.SimpleNamespace(mod=2000, db=types.SimpleNamespace(scalar=lambda q: 1000))
            ahead = F._unsynced()
            mw.col = types.SimpleNamespace(mod=2000, db=types.SimpleNamespace(scalar=lambda q: 2000))
            even = F._unsynced()
            mw.pm = types.SimpleNamespace(sync_auth=lambda: None)
            mw.col = types.SimpleNamespace(mod=2000, db=types.SimpleNamespace(scalar=lambda q: 0))
            nologin = F._unsynced()
            check("morning: Sync now only with an AnkiWeb login and changes since its last sync",
                  ahead is True and even is False and nologin is False, (ahead, even, nologin))
            mw.col = sv_col
            sh = board.you_html({}, dict(dv, opened={"n": 3, "sync": True}), {"tab": "today", "plans": view})
            check("morning: Sync now beside Put off to tomorrow", "duecrew:plansync" in sh and "Sync now</a>" in sh
                  and sh.index("plansync") < sh.index("plannottoday"))
            mw.on_sync_button_clicked = lambda: synced.append(1)
            import due_crew as dc
            from aqt.deckbrowser import DeckBrowser
            dc._on_js(False, "duecrew:plansync", DeckBrowser())
            check("morning: Sync now is Anki's own Sync", synced == [1], synced)
        finally:
            mw.col = sv_col
            if sv_pm is None:
                mw.__dict__.pop("pm", None)
            else:
                mw.pm = sv_pm
            mw.__dict__.pop("on_sync_button_clicked", None)
        col.undo_steps.append(("Edit note", []))
        check("morning: no Put off to tomorrow once Anki has done something since", F.morning_opened() is None)
        today["d"] = _day(1)
        col.undo_steps.pop()
        check("morning: nor on another day", F.morning_opened() is None)
        today["d"] = _day(3)
        html = board.render({"entries": [], "labels": labels, "tomorrow": "", "pending": []},
                            {"period": "today"}, 0, plans=view, you={"tab": "plans", "plans": view})
        check("card: behind, only for me",
              "Heart failure</b> was due Mon. 2 cards not seen yet." in html
              or "was due Monday. 2 cards not seen yet." in html, "")
        store.edit_plan(pid, [dict(u, name="Arrhythmia & co") if u["id"] == "ar" else
                              dict(u, opens=_day(21)) if u["id"] == "rn" else u for u in _plan_units()])
        maya.fetch_board(labels, with_decks=True)
        card = F.card_view(F.followed()[0], box["cfg"]["plans"][pid], {}, _day(0))
        check("change note: the author moved a date", card["change"] is not None
              and "moved " in "".join(t for t, _b in card["change"]) and "Renal" in [t for t, _b in card["change"]])
        F.seen_change(pid)
        check("change note: OK puts it away",
              F.card_view(F.followed()[0], box["cfg"]["plans"][pid], {}, _day(0))["change"] is None)
        ahead = F.card_view(F.followed()[0], dict(box["cfg"]["plans"][pid]), {"ex": [1, 0, 1]}, _day(1))
        check("ahead: the next unit already open",
              ahead["lines"][0][0] == "ahead" and "early" in "".join(t for t, _b in ahead["lines"][0][1]))

        # offers: from my squads, escaped, Look opens the follow
        sq = new_client(store, "dre", "Dre").create_squad("busm")
        store._join(sq["id"], "maya")
        store.add_plan("dre", "Pharm <script>", "Pharm", [], audience="squad", squad=sq["id"])
        box["cfg"]["squads"] = [dict(sq)]
        maya.fetch_board(labels, with_decks=True)
        view = F.board_view(box["cfg"])
        html = board.render({"entries": [], "labels": labels, "tomorrow": "", "pending": []},
                            {"period": "squads"}, 0, plans=view)
        check("offer: my squad's plan, as a banner with Look, escaped",
              "offered busm a plan: Pharm &lt;script&gt;" in html and "duecrew:planlook:" in html
              and "<script>" not in html)
        opt = next(o for o in maya.session["plan_offers"])
        check("offer: a squad plan can't be followed from outside the squad",
              new_client(store, "kai", "Kai").peek_plan(opt["code"])[1] == 404
              and maya.peek_plan(opt["code"])[1] == 200)
        box["cfg"]["plan_offers_dismissed"] = [opt["id"]]
        check("offer: waved off, it stays off", F.board_view(box["cfg"])["offers"] == [])
        check("site link: one request, a token for the fragment", maya.site_link() and
              store.log[-1] == ("POST", "/auth/link", 200))
        check("tree: names and counts go up", maya.put_tree("Step 1", [["Step1::Cardio", 3]], [])
              and store.plan_trees[("maya", "Step 1")]["tags"] == [["Step1", 0, [["Cardio", 3]]]])
        check("add cards: only the author", new_client(store, "kai", "Kai").add_plan_cards(
            pid, [["guid000001", 0]], unit="hf")[1] == 403)
        mine = maya.my_plans()
        check("my plans: the ones I follow", [p["id"] for p in mine] == [pid] and mine[0]["following"])
    finally:
        for k, v in saved.items():
            setattr(F, k, v)
        F.mw.col, F.app.swap = saved_col, saved_swap
        _state["labels"], _state["plan_progress"] = [], {}


# ---------------------------------------------------------------- 3.1.1: review fixes

_PLAN_KEYS = ("plans", "plans_day", "plans_opened", "plan_offers_dismissed")


class _PlanGlue:
    """plan_flow's glue pointed at a test world: a shared add-on config
    (the one every profile sees), per-profile folders, and a client and a
    collection per profile. Restores everything on exit."""

    def __init__(self, clients, cols, today=None):
        from due_crew import plan_flow as F
        self.F = F
        self.glob = {"cfg": {}}
        self.dirs = {name: tempfile.mkdtemp() for name in clients}
        self.clients, self.cols = clients, cols
        self.toasts = []
        self.today = {"d": today or _day(0)}

    def __enter__(self):
        F = self.F
        self.saved = {k: getattr(F, k, None) for k in ("cfg", "save_cfg", "_files", "client", "_today", "tooltip")}
        self.saved_mw = (F.mw.col, F.mw.pm.name, F.app.swap)
        F.cfg = lambda: self.glob["cfg"]
        F.save_cfg = lambda c: self.glob.update(cfg=c)
        F._files = lambda: self.dirs[F.mw.pm.name]
        F.client = lambda: self.clients[F.mw.pm.name]
        F._today = lambda: self.today["d"]
        F.tooltip = lambda text, **kw: self.toasts.append(text)
        F.app.swap = lambda c: None
        self.forget()
        self.profile(next(iter(self.clients)))
        return self

    def forget(self):
        """Drop plan_flow's cache of this profile's file."""
        if hasattr(self.F, "_store"):
            self.F._store.update(profile=None, data=None)

    def state(self):
        """This profile's plan state (before 3.1.1: the shared config)."""
        return self.F._pcfg() if hasattr(self.F, "_pcfg") else self.glob["cfg"]

    def profile(self, name):
        self.F.mw.pm.name = name
        self.F.mw.col = self.cols[name]

    def __exit__(self, *exc):
        F = self.F
        for k, v in self.saved.items():
            if v is None:
                delattr(F, k)
            else:
                setattr(F, k, v)
        F.mw.col, F.mw.pm.name, F.app.swap = self.saved_mw
        self.forget()
        from due_crew.app import _state
        _state["labels"], _state["plan_progress"] = [], {}
        return False


def test_plans_file_kept_when_unreadable_v380():
    """3.8.0: a plans.json that won't read was taken as no plans and written
    over at the next save, losing the list of cards a plan held back. It's
    moved aside as plans.json.bad (bad2, ... after that) and said once."""
    store = world({"maya": "Maya"})
    maya = new_client(store, "maya", "Maya")
    with _PlanGlue({"A": maya}, {"A": _plan_col()}) as g:
        F = g.F
        path = os.path.join(g.dirs["A"], "plans.json")
        with open(path, "w") as f:
            f.write('{"plans": {"p1": {"held": [1, 2')
        g.forget()
        check("plans file: an unreadable one reads as no plans", g.state() == {})
        check("plans file: moved aside, said once",
              os.path.exists(path + ".bad") and not os.path.exists(path)
              and len([t for t in g.toasts if "plans.json.bad" in t]) == 1, (os.listdir(g.dirs["A"]), g.toasts))
        g.state()
        check("plans file: read again from the cache, not said again", len(g.toasts) == 1, g.toasts)
        F._psave({"plans": {}})
        with open(path + ".bad") as f:
            kept = f.read()
        check("plans file: the next save leaves the old one alone", "held" in kept, kept)
        with open(path, "w") as f:
            f.write("not json")
        g.forget()
        g.state()
        check("plans file: a second bad one doesn't replace the first",
              os.path.exists(path + ".bad2") and "held" in open(path + ".bad").read(), os.listdir(g.dirs["A"]))


def test_plans_per_profile_v311():
    """3.1.1: plan state is the profile's, not the add-on's. Profile B's
    fresh board used to prune A's plans (A then reopened every past unit),
    and B's morning set the day for A. The old shared state moves once, to
    the profile whose decks it names."""
    store = world({"dre": "Dre", "maya": "Maya", "kai": "Kai"})
    pid, code = store.add_plan("dre", "Step 1", "Step 1", _plan_units())
    maya, kai = new_client(store, "maya", "Maya"), new_client(store, "kai", "Kai")
    col_b = _plan_col()
    col_b.decks = fakes.FakeDecks({30: "Biochem"})
    with _PlanGlue({"A": maya, "B": kai}, {"A": _plan_col(), "B": col_b}) as g:
        F = g.F
        plan, _ = maya.follow_plan(code)
        F.open_schedule = _skip_schedule
        F.on_followed(plan, 10, None, "open")
        col_a = g.cols["A"]
        g.profile("B")
        F.maybe_morning(False, fresh=True)  # B follows nothing
        g.profile("A")
        st = g.state().get("plans", {}).get(pid)
        check("profiles: B's fresh board leaves A's plan state alone",
              bool(st) and st["applied"].get("hf") and st["applied"].get("ar"), str(st))
        check("profiles: no plan state in the config every profile shares",
              not any(k in g.glob["cfg"] for k in _PLAN_KEYS), str(g.glob["cfg"]))
        col_a.db.conn.execute("UPDATE cards SET queue = -1 WHERE id = 1")  # suspended again by hand
        g.today["d"] = _day(1)
        maya.fetch_board([_day(1)], with_decks=True)
        F.maybe_morning(False, fresh=True)
        check("profiles: A's next morning doesn't reopen what it opened before", 1 not in _open(col_a))

    # the old shared config: each profile takes the plans on its own decks, once
    with _PlanGlue({"C": maya, "D": kai}, {"C": _plan_col(), "D": col_b}) as g:
        F = g.F
        g.glob["cfg"] = {"plans": {"pa": {"deck_id": 10, "applied": {"hf": "x"}},
                                   "pb": {"deck_id": 30, "applied": {}}},
                         "plans_day": _day(0), "plans_opened": {"day": _day(0), "label": "L"},
                         "plan_offers_dismissed": ["o1"], "sort": "reviews"}
        c_state = g.state()
        check("migrate: a profile takes the plans on its decks, with the day and the Undo",
              list(c_state["plans"]) == ["pa"] and c_state.get("plans_day") == _day(0)
              and c_state.get("plans_opened", {}).get("label") == "L"
              and c_state.get("plan_offers_dismissed") == ["o1"], str(c_state))
        check("migrate: the rest wait in the config for their own profile",
              list(g.glob["cfg"].get("plans") or {}) == ["pb"] and "plans_day" not in g.glob["cfg"])
        g.profile("D")
        d_state = g.state()
        check("migrate: the other profile takes its own, and the config lets go",
              list(d_state["plans"]) == ["pb"] and "plans_day" not in d_state
              and not any(k in g.glob["cfg"] for k in _PLAN_KEYS) and g.glob["cfg"].get("sort") == "reviews",
              f"{d_state} {g.glob['cfg']}")
        g.profile("C")
        g.forget()
        check("migrate: once; the profile's file is kept", list(g.state()["plans"]) == ["pa"])


def test_plans_followed_elsewhere_v311():
    """3.1.1: a plan first seen here (followed on another computer, or on
    the site) opens today's unit only; what opened before came with the
    AnkiWeb sync, or was skipped there on purpose. Following again here
    keeps what was applied."""
    store = world({"dre": "Dre", "maya": "Maya"})
    pid, code = store.add_plan("dre", "Step 1", "Step 1", _plan_units())
    maya = new_client(store, "maya", "Maya")
    with _PlanGlue({"A": maya}, {"A": _plan_col()}) as g:
        F, col = g.F, g.cols["A"]
        plan, _ = maya.follow_plan(code)
        maya.fetch_board([_day(0)], with_decks=True)
        F.maybe_morning(False, fresh=True)
        st = g.state()["plans"][pid]
        check("elsewhere: only today's unit opens", _open(col) == {3, 8}, str(_open(col)))
        check("elsewhere: the units before today are marked skipped", st["applied"]["hf"].startswith("skip:"))
        F.open_schedule = _skip_schedule
        F.on_followed(plan, 10, None, "open")
        check("follow again: what was applied here is kept (the skipped unit stays shut)",
              _open(col) == {3, 8} and g.state()["plans"][pid]["applied"]["hf"].startswith("skip:"),
              str(_open(col)))
        # 3.4 review, H1: a plan first seen here (followed on the site) asks
        # Follow's hold-back question, once, only when there's something to hold
        asked = []
        F.offer_hold([pid], ask=lambda name, n: asked.append(n) or False)
        check("hold on first sight: nothing active to hold, nothing asked", asked == [], str(asked))
        col.db.conn.execute("UPDATE cards SET queue = 0 WHERE queue = -1")  # a deck imported all active
        before = _open(col)
        F.offer_hold([pid], ask=lambda name, n: asked.append(n) or False)
        check("hold on first sight: asked, and a no leaves everything open", asked and _open(col) == before, str(asked))
        F.offer_hold([pid], ask=lambda name, n: True)
        held = g.state()["plans"][pid].get("held") or []
        check("hold on first sight: a yes holds back the later dates' cards, remembered for stop",
              held and all(c not in _open(col) for c in held) and len(held) == asked[-1], str(held))


def test_plans_changed_unit_v311():
    """3.1.1: when the author changes a unit already opened here, only the
    cards the change adds open. A card suspended since (by hand, or a
    leech Anki suspended) stays suspended; a leech never opens."""
    from due_crew import plan_flow as F
    from due_crew import plans as P
    store = world({"dre": "Dre", "maya": "Maya"})
    pid, code = store.add_plan("dre", "Step 1", "Step 1", _plan_units())
    plan, _ = new_client(store, "maya", "Maya").follow_plan(code)
    col = _plan_col()
    state = {pid: F.new_state(col, plan)}
    F.run(col, [plan], state, _day(0))
    conn = col.db.conn
    conn.execute("UPDATE cards SET queue = -1 WHERE id = 1")                          # by hand
    fakes.add_card(conn, 12, did=10, queue=-1, tags="Step1::Cardio::Heart_failure leech")  # Anki's leech
    fakes.add_card(conn, 13, did=10, queue=-1, tags="Step1::Cardiology leech")
    units = [dict(u, tags=u["tags"] + ["Step1::Cardiology"]) if u["id"] == "hf" else u
             for u in _plan_units()]
    changed = dict(plan, doc=dict(plan["doc"], units=units))
    check("changed unit: what's waiting is only what the change adds",
          F.waiting(col, changed, state[pid], _day(1)) == (1, 2))
    res = F.run(col, [changed], state, _day(1))
    check("changed unit: only the card it adds opens", 9 in _open(col) and res["n"] == 1, f"{res} {_open(col)}")
    check("changed unit: a card suspended since stays suspended", 1 not in _open(col))
    check("changed unit: a leech never opens", 12 not in _open(col) and 13 not in _open(col))
    check("open cards: never a leech, even asked directly", P.open_cards(col, {12, 13}, "x") == 0)
    F.run(col, [changed], state, _day(1), everything=True)
    check("open everything: still no leech", 12 not in _open(col) and 13 not in _open(col) and 1 in _open(col))
    # 3.6.5: the plan card says what it left shut, once
    check("aside: the leeches a date leaves shut, counted when it opens",
          F.aside(changed, state[pid]) == [2, 0, 0], str(state[pid].get("leeches")))
    from due_crew import board
    card = {"id": pid, "aside": F.aside(changed, state[pid]), "aside_ok": [0, 0]}
    html = board._plan_notes(card, pid)
    check("aside: 3.8.0, leeches aren't the plan's to say (Insights has the deck's)", not any("leech" in x for x in html), str(html))
    card = {"id": pid, "aside": [0, 2, 5], "aside_ok": [0, 0]}
    html = board._plan_notes(card, pid)
    check("aside: exact cards not in my deck, with OK",
          any("2 of 5 exact cards aren\u2019t in your deck." in x and f"planasideok:{pid}" in x for x in html), str(html))
    check("aside: said once, until it grows", not board._plan_notes(dict(card, aside_ok=[0, 2]), pid)
          and board._plan_notes(dict(card, aside=[0, 3, 5], aside_ok=[0, 2]), pid))
    import due_crew as dc
    from aqt.deckbrowser import DeckBrowser
    if "aqt.reviewer" not in sys.modules:
        sys.modules["aqt.reviewer"] = types.SimpleNamespace(Reviewer=type("Reviewer", (), {}))
    pc = {}
    saved = (F._state_cfg, F.followed, F._pcfg, F._psave, F.app.swap)
    F._state_cfg, F.followed, F._pcfg = (lambda c=None: state), (lambda: [changed]), (lambda: pc)
    F._psave, F.app.swap = (lambda d: None), (lambda c: None)
    try:
        dc._on_js(False, f"duecrew:planasideok:{pid}", DeckBrowser())
    finally:
        F._state_cfg, F.followed, F._pcfg, F._psave, F.app.swap = saved
    check("aside: OK, sent as the board sends it, remembers what was said", pc.get("aside_ok", {}).get(pid) == [2, 0], str(pc))


def test_plans_changed_unit_with_search_and_ids():
    """A date with a search (C3) or pasted ids (E1) that the author changes
    after it opened here: the morning opens what the change adds, and no
    more (it used to stop on the date's longer record)."""
    from due_crew import plan_flow as F
    store = world({"dre": "Dre", "maya": "Maya"})
    units = [dict(u, search=["tag:Step1::Cardio::Arrhythmia"], nids=[50]) if u["id"] == "hf" else u for u in _plan_units()]
    pid, code = store.add_plan("dre", "Step 1", "Step 1", units)
    plan, _ = new_client(store, "maya", "Maya").follow_plan(code)
    col = _plan_col()
    state = {pid: F.new_state(col, plan)}
    F.run(col, [plan], state, _day(0))
    check("search+ids: the first morning opens the tag, the search and the note", {1, 2, 3, 5, 6} <= _open(col), str(_open(col)))
    conn = col.db.conn
    conn.execute("UPDATE cards SET queue = -1 WHERE id IN (3, 5)")   # closed since, by hand
    changed_units = [dict(u, tags=u["tags"] + ["Step1::Cardiology"]) if u["id"] == "hf" else u for u in units]
    changed = dict(plan, doc=dict(plan["doc"], units=changed_units))
    res = F.run(col, [changed], state, _day(1))
    check("search+ids: after the author's change only the added card opens", res["n"] == 1 and 9 in _open(col), f"{res} {_open(col)}")
    check("search+ids: what was closed by hand since stays closed", 3 not in _open(col) and 5 not in _open(col))


def test_plans_follower_days_g():
    """G1-G5: a follower's own days. My dates run `shift` days later and
    the ones I skip never open (the plan never changes, events never move);
    one date opens now and the morning leaves it; Not today opens it on
    tomorrow's morning, not today's; what's waiting from earlier dates is
    counted; the card offers Open now, Undo skip and Catch up."""
    from due_crew import plan_flow as F
    from due_crew import plans as P
    doc = {"deck": "Step 1", "units": _plan_units(), "events": [{"id": "q", "day": _day(5), "name": "Quiz"}],
           "reviews": [{"day": _day(4), "from": "hf", "to": "ar"}]}
    mine = P.my_doc(doc, 2, ["ex"])
    check("my view: dates, due dates and review days two days later; a skipped date gone; events stay",
          [u["id"] for u in mine["units"]] == ["hf", "ar", "cz", "rn"] and mine["units"][1]["opens"] == _day(2)
          and mine["units"][1]["due"] == _day(8) and mine["reviews"][0]["day"] == _day(6)
          and mine["events"][0]["day"] == _day(5) and doc["units"][1]["opens"] == _day(0), str(mine["units"][1]))
    check("my view: nothing to change, the plan itself", P.my_doc(doc) is doc)

    store = world({"dre": "Dre", "maya": "Maya"})
    pid, code = store.add_plan("dre", "Step 1", "Step 1", _plan_units())
    plan, _ = new_client(store, "maya", "Maya").follow_plan(code)
    col = _plan_col()
    state = {pid: F.new_state(col, plan)}
    shifted = dict(plan, shift=2, skipped=["hf"])
    F.run(col, [shifted], state, _day(0))
    check("shift: today's date waits two days; a skipped date never opens", _open(col) == {8}, str(_open(col)))
    F.run(col, [shifted], state, _day(2))
    check("shift: two days later it opens", 3 in _open(col) and 1 not in _open(col), str(_open(col)))

    col = _plan_col()
    state = {pid: F.new_state(col, plan)}
    res = F.open_one(col, plan, state[pid], "ex", _day(0))
    check("open now: one date, one undo step, today", res["n"] == 1 and 4 in _open(col) and res["names"] == ["Extras"])
    before = len(col.undo_steps)
    F.run(col, [plan], state, _day(3))
    check("open now: its morning leaves it be", 4 in _open(col) and "Extras" not in str(col.undo_steps[before:]))

    col = _plan_col()
    state = {pid: F.new_state(col, plan)}
    res = F.run(col, [plan], state, _day(0))
    check("the morning says which dates it opened", set(res["units"][pid]) == {"hf", "ar"}, str(res["units"]))
    conn = col.db.conn
    conn.execute("UPDATE cards SET queue = -1 WHERE id IN (1, 2, 3)")  # Anki's undo put them back
    F.put_off(state[pid], res["units"][pid], _day(0))
    again = F.run(col, [plan], state, _day(0))
    check("not today: not again today", again["n"] == 0 and not ({1, 2, 3} & _open(col)))
    tomorrow = F.run(col, [plan], state, _day(1))
    check("not today: tomorrow's morning opens them", {1, 2, 3} <= _open(col) and tomorrow["n"] == 3, str(tomorrow))

    check("waiting: new cards of earlier dates not seen yet",
          P.waiting_new({"units": _plan_units()}, {"hf": [2, 0, 2], "ar": [1, 1, 1]}, _day(1)) == 2)
    card = F.card_view(dict(plan, skipped=["ex"]), state[pid], {"hf": [2, 0, 2]}, _day(1))
    rows = {r["name"]: r for r in card["rows"]}
    check("card: the skipped date, with its id, crossed out", rows.get("Extras", {}).get("state") == "skip", str(card["rows"]))
    check("card: the next date carries its id, for Open now", rows.get("Cloze two", {}).get("uid") == "cz")
    check("card: what's waiting from earlier dates", card["waiting"] == 2)
    from due_crew import board
    html = board._plan_card_html(dict(card, id=pid))
    weeks = lambda day: (datetime.date.fromisoformat(P.week_start(day)) - datetime.date.fromisoformat(P.week_start(_day(1)))).days // 7
    in_week = lambda day: board._plan_card_html(dict(F.card_view(dict(plan, skipped=["ex"]), state[pid], {"hf": [2, 0, 2]},
                                                                   _day(1), week_offset=weeks(day)), id=pid))
    check("card: Open now (the next date's day), Undo skip (the skipped one's day) and Catch up",
          f"plannow:{pid}:cz" in in_week(_day(7)) and f"planunskip:{pid}:ex" in in_week(_day(3))
          and f"plancatch:{pid}" in html and "Skip it" in in_week(_day(7)), html[:400])


def test_your_own_days_376():
    """3.7.6: one date moved later on my copy, Reset to default, and the
    three ways to start a plan that began before I followed."""
    import due_crew as dc
    from aqt.deckbrowser import DeckBrowser
    from due_crew import plan_flow as F
    from due_crew import plans as P
    from due_crew import board
    doc = {"deck": "Step 1", "units": _plan_units(), "events": [{"id": "q", "day": _day(5), "name": "Quiz"}]}
    mine = P.my_doc(doc, 1, (), {"ar": 2})
    ar = next(u for u in mine["units"] if u["id"] == "ar")
    check("moved: that date runs its days later again, on top of the shift; the rest only the shift",
          ar["opens"] == _day(3) and ar["due"] == _day(9) and ar.get("_moved") == 2
          and next(u for u in mine["units"] if u["id"] == "ex")["opens"] == _day(4) and doc["units"][1]["opens"] == _day(0))
    week = P.week_view(mine, {}, _day(0), P.week_start(_day(3)))
    check("moved: the week marks it", any(u.get("moved") for d in week for u in d["units"] if u["uid"] == "ar"))
    ls = P.late_start(dict(doc, end=_day(16)), _day(0))
    check("late: the passed dates, how far back the start is, where it would end and what it runs past",
          ls["passed"] == ["hf"] and ls["shift"] == 7 and ls["ends"] == _day(21) and ls["after"] == ("the plan's end", _day(16)), ls)
    check("late: nothing passed, nothing to ask", P.late_start({"units": _plan_units()[1:]}, _day(0))["passed"] == [])
    check("reset: says exactly what goes back, and nothing when nothing changed",
          F.reset_lines({"doc": doc, "shift": 3, "skipped": ["ex"], "moved": {"ar": 2}, "until": _day(4)})
          == ["Your dates run 3 days later: back on time", "1 skipped date comes back: Extras",
              "1 moved date goes back: Arrhythmia", "Your pause ends"]
          and F.reset_lines({"doc": doc}) == [])

    store = world({"dre": "Dre", "maya": "Maya"})
    pid, code = store.add_plan("dre", "Step 1", "Step 1", _plan_units())
    maya = new_client(store, "maya", "Maya")
    col = _plan_col()
    labels = [_day(-i) for i in range(7)]
    saved = (F._bg, F.confirm if hasattr(F, "confirm") else None)
    with _PlanGlue({"A": maya}, {"A": col}):
        F._bg = lambda job, done=None: done(job()) if done else job()
        try:
            plan, _ = maya.follow_plan(code)
            F.on_followed(plan, 10, None, "skip:hf")
            check("late, where everyone is: the passed date is skipped on my follow, so behind nowhere",
                  store.follows[(pid, "maya")].get("skipped") == ["hf"] and 1 not in _open(col) and 3 in _open(col),
                  (store.follows[(pid, "maya")], _open(col)))
            maya.fetch_board(labels, with_decks=True)
            card = F.card_view(next(x for x in F.followed() if x["id"] == pid), F._state_cfg()[pid], {}, _day(0))
            html = board._plan_card_html(dict(card, id=pid))
            check("move: a date from today on has Move…", f"planmove:{pid}:ar" in html, html[:300])
            dc._on_js(False, f"duecrew:planskip:{pid}:ex", DeckBrowser())  # a command the board sends, for the handler list
            F.move_date(pid, "cz", 2)
            check("move: kept on my follow; the plan itself unchanged",
                  store.follows[(pid, "maya")].get("moved") == {"cz": 2} and store.plans[pid]["doc"]["units"][3]["opens"] == _day(7))
            card = F.card_view(next(x for x in F.followed() if x["id"] == pid), F._state_cfg()[pid], {}, _day(0),
                               week_offset=(datetime.date.fromisoformat(P.week_start(_day(9))) - datetime.date.fromisoformat(P.week_start(_day(0)))).days // 7)
            html = board._plan_card_html(dict(card, id=pid))
            check("move: on its new day, marked moved, with Put it back", "&middot; moved" in html and f"planmoveback:{pid}:cz" in html)
            dc._on_js(False, f"duecrew:planmoveback:{pid}:cz", DeckBrowser())
            check("move: Put it back (sent as the board does) takes it off", not store.follows[(pid, "maya")].get("moved"))
            F.move_date(pid, "cz", 2)
            maya.set_days(pid, shift=3)
            asked = []
            F.confirm = lambda *a: asked.append(a[2]) or True
            from due_crew import ui as UI
            real_confirm, UI.confirm = UI.confirm, F.confirm
            try:
                dc._on_js(False, f"duecrew:planreset:{pid}", DeckBrowser())
            finally:
                UI.confirm = real_confirm
            f = store.follows[(pid, "maya")]
            check("reset to default: one question saying what goes back, then all of it at once",
                  asked and "Reset to default?" in asked[0] and "Your dates run 3 days later" in asked[0]
                  and f.get("shift", 0) == 0 and not f.get("skipped") and not f.get("moved"), (asked, f))
        finally:
            F._bg = saved[0]
    store2 = world({"dre": "Dre", "kai": "Kai"})
    pid2, code2 = store2.add_plan("dre", "Step 1", "Step 1", _plan_units())
    kai = new_client(store2, "kai", "Kai")
    col2 = _plan_col()
    with _PlanGlue({"B": kai}, {"B": col2}):
        F._bg = lambda job, done=None: done(job()) if done else job()
        try:
            plan, _ = kai.follow_plan(code2)
            F.on_followed(plan, 10, None, "begin:7")
            check("late, from the beginning: my dates run that many days later; the first opens today",
                  store2.follows[(pid2, "kai")]["shift"] == 7 and 1 in _open(col2) and 3 not in _open(col2), str(_open(col2)))
        finally:
            F._bg = saved[0]
    store4 = world({"dre": "Dre", "bo": "Bo"})
    pid4, code4 = store4.add_plan("dre", "Step 1", "Step 1", _plan_units())
    bo = new_client(store4, "bo", "Bo")
    col4 = _plan_col()
    with _PlanGlue({"D": bo}, {"D": col4}):
        F._bg = lambda job, done=None: done(job()) if done else job()
        try:
            plan, _ = bo.follow_plan(code4)
            bo.set_days = lambda *a, **k: None  # offline
            F.on_followed(plan, 10, None, "skip:hf")
            check("late, offline: the passed date never opens (skipped here), today's does",
                  1 not in _open(col4) and 3 in _open(col4), str(_open(col4)))
        finally:
            F._bg = saved[0]
    store5 = world({"dre": "Dre", "cy": "Cy"})
    pid5, code5 = store5.add_plan("dre", "Step 1", "Step 1", _plan_units())
    cy = new_client(store5, "cy", "Cy")
    col5 = _plan_col()
    col5.db.conn.execute("UPDATE cards SET queue = 0 WHERE queue = -1")  # a deck imported all active
    with _PlanGlue({"E": cy}, {"E": col5}):
        F._bg = lambda job, done=None: done(job()) if done else job()
        try:
            plan, _ = cy.follow_plan(code5)
            F.on_followed(plan, 10, None, "begin:7", hold=True)
            st5 = F._state_cfg()[pid5]
            check("late, from the beginning with Hold back: what's later for me (the plan's today) is held",
                  3 in (st5.get("held") or []) and 1 not in (st5.get("held") or []), st5.get("held"))
        finally:
            F._bg = saved[0]
    store3 = world({"dre": "Dre", "lu": "Lu"})
    pid3, code3 = store3.add_plan("dre", "Step 1", "Step 1", _plan_units())
    lu = new_client(store3, "lu", "Lu")
    col3 = _plan_col()
    with _PlanGlue({"C": lu}, {"C": col3}):
        F._bg = lambda job, done=None: done(job()) if done else job()
        try:
            plan, _ = lu.follow_plan(code3)
            F.on_followed(plan, 10, None, "catch:1:14")
            st = F._state_cfg()[pid3]
            check("late, catch up: the passed date opens and a week's catch-up runs (+2 a day)",
                  1 in _open(col3) and st.get("catch", {}).get("extra") == 2 and st["catch"]["until"] == _day(6), st.get("catch"))
            card = F.card_view(next(x for x in F.followed() if x["id"] == pid3), st, {"hf": [2, 0, 2]}, _day(0))
            h = board._plan_card_html(dict(card, session={"kind": "study", "target": 3, "done": 0, "behind": 2}))
            check("late, catch up: what it's catching up on isn't called behind",
                  "Catching up: +2 new a day" in h and "pn warn" not in h and "behind" not in h, h)
        finally:
            F._bg = saved[0]


def test_plans_fresh_after_cached_morning_v311():
    """3.1.1: the morning at the sync can run on yesterday's cached plans;
    the day's fresh ones, arriving after, still get their look."""
    store = world({"dre": "Dre", "maya": "Maya"})
    pid, code = store.add_plan("dre", "Step 1", "Step 1", _plan_units())
    maya = new_client(store, "maya", "Maya")
    with _PlanGlue({"A": maya}, {"A": _plan_col()}) as g:
        F, col = g.F, g.cols["A"]
        plan, _ = maya.follow_plan(code)
        maya.session["plans"] = []           # the cache: from before the follow
        F.maybe_morning(False)               # at the sync, before the refresh
        check("fresh: the morning ran on the cache, and found nothing", g.state().get("plans_day") == _day(0)
              and _open(col) == {8})
        maya.fetch_board([_day(0)], with_decks=True)
        F.maybe_morning(False, fresh=True)   # the refresh
        check("fresh: the day's plans still open what's due today", 3 in _open(col), str(_open(col)))
        n = len(col.undo_steps)
        F.maybe_morning(False, fresh=True)
        check("fresh: a second look opens nothing twice, and makes no step", len(col.undo_steps) == n)


def test_plans_undo_waits_v311():
    """3.1.1: the board's Undo clears the card and counts only once Anki's
    undo has actually happened (a CollectionOp, run in the background)."""
    store = world({"dre": "Dre", "maya": "Maya"})
    pid, code = store.add_plan("dre", "Step 1", "Step 1", _plan_units())
    maya = new_client(store, "maya", "Maya")
    pending = []

    class Op:
        def __init__(self, parent, op):
            self.op, self.ok = op, None

        def success(self, fn):
            self.ok = fn
            return self

        def failure(self, fn):
            return self

        def run_in_background(self):
            pending.append(self)

    ops = types.ModuleType("aqt.operations")
    ops.CollectionOp = Op
    coll = types.ModuleType("aqt.operations.collection")
    coll.undo = lambda parent=None: pending.append(None)
    sys.modules["aqt.operations"], sys.modules["aqt.operations.collection"] = ops, coll
    try:
        with _PlanGlue({"A": maya}, {"A": _plan_col()}) as g:
            F, col = g.F, g.cols["A"]
            plan, _ = maya.follow_plan(code)
            F.open_schedule = _skip_schedule
            F.on_followed(plan, 10, None, "open")
            check("undo: set up", g.state().get("plans_opened", {}).get("label") == "Due Crew: open 2 dates")
            F.undo_morning()
            check("undo: nothing is cleared before the undo has happened",
                  bool(g.state().get("plans_opened")) and 1 in _open(col))
            op = next((p for p in pending if p is not None), None)
            if op is not None:
                op.ok(op.op(col))
            check("undo: once it has, the step's cards are back and the card forgets it",
                  op is not None and 1 not in _open(col) and not g.state().get("plans_opened")
                  and F._state["plan_progress"][pid]["hf"][0] == 0)
    finally:
        sys.modules.pop("aqt.operations", None)
        sys.modules.pop("aqt.operations.collection", None)


def test_plans_notes_mode_v311():
    """3.1.1: Add to a plan in the browser's Notes mode would take every
    card of the picked notes; it asks for Cards mode instead."""
    maya = new_client(world({"maya": "Maya"}), "maya", "Maya")
    with _PlanGlue({"A": maya}, {"A": _plan_col()}) as g:
        asked = []
        browser = types.SimpleNamespace(table=types.SimpleNamespace(is_notes_mode=lambda: True),
                                        selected_cards=lambda: asked.append(1) or [5])
        try:
            g.F.add_to_plan(browser)
        except Exception:
            pass
        check("notes mode: no cards are taken, and it says to switch to Cards",
              not asked and g.toasts and "Cards" in g.toasts[-1], str(g.toasts))


def test_plan_search_is_the_decks_v34():
    """3.4 review: the browser's search goes to a plan only when it finds the
    same cards in everyone's copy. Anki's own deck:current (the browser's
    default) would open a follower's whole deck; is:due, flags and ratings
    are one person's."""
    from due_crew import plans
    for q in ("deck:current", '"deck:current" tag:x', "is:due", "-is:suspended tag:a", "flag:1", "(rated:1 or tag:x)", " "):
        check(f"search: {q!r} isn't a plan's", not plans.shareable_search(q))
    for q in ("tag:*Cardio* -tag:*Pharm*", "tag:Step1::Renal", "current events", '"deck:Step 1::Renal"'):
        check(f"search: {q!r} is", plans.shareable_search(q))
    maya = new_client(world({"maya": "Maya"}), "maya", "Maya")
    with _PlanGlue({"A": maya}, {"A": _plan_col()}) as g:
        edit = types.SimpleNamespace(lineEdit=lambda: types.SimpleNamespace(text=lambda: "deck:current"))
        browser = types.SimpleNamespace(table=types.SimpleNamespace(is_notes_mode=lambda: False),
                                        form=types.SimpleNamespace(searchEdit=edit), selected_cards=lambda: [])
        try:
            g.F.add_to_plan(browser)
        except Exception:
            pass
        check("search: the default search with nothing picked asks for a search or cards",
              g.toasts and "Search for the cards" in g.toasts[-1], str(g.toasts))
        check("review: a filtered deck sits under Due Crew; a date named with :: makes no deeper one",
              g.F._deck_name("Checkpoint · Renal::Pharm") == "Due Crew::Checkpoint · Renal: Pharm"
              and g.F._deck_name("  ") == "Due Crew::Cards")


def test_sign_in_keeps_anki_synced_v311():
    """3.1.1: signing in or out mid-session doesn't forget that AnkiWeb has
    synced (it's about the collection); the plans' morning isn't held back."""
    import due_crew as dc
    from due_crew.app import _state
    saved = sys.modules.get("due_crew.ui.auth_dialog")
    fake = types.ModuleType("due_crew.ui.auth_dialog")

    class Dlg:
        def __init__(self, *a, **k):
            self.user, self.joined = ("sam", "Sam"), False

        def exec(self):
            return True
    fake.AuthDialog = Dlg
    sys.modules["due_crew.ui.auth_dialog"] = fake
    saved_fns = (dc.client, dc._on_sync_done)
    signed_in = new_client(world({"sam": "Sam"}), "sam", "Sam")
    dc.client, dc._on_sync_done = (lambda: signed_in), (lambda **kw: None)
    try:
        _state["anki_synced"] = True
        dc._on_signed_out()
        out_ok = _state["anki_synced"] is True
        _state["anki_synced"] = True
        try:
            dc.open_auth()
        except Exception:
            pass
        check("sign-in: AnkiWeb having synced survives signing out and in",
              out_ok and _state["anki_synced"] is True)
    finally:
        if saved is not None:
            sys.modules["due_crew.ui.auth_dialog"] = saved
        else:
            sys.modules.pop("due_crew.ui.auth_dialog", None)
        dc.client, dc._on_sync_done = saved_fns
        _state["anki_synced"] = False


def test_refresh_generation_v311():
    """3.1.1: a refresh still running when the profile switches doesn't
    land in the next profile, and doesn't hold back that profile's own."""
    import due_crew as dc
    from due_crew import app as appmod
    from due_crew.app import _state
    store = world({"sam": "Sammy", "dre": "Dre", "eve": "Eve"}, {"sam": ["dre"], "dre": ["sam"]})
    sam, eve = new_client(store, "sam", "Sammy"), new_client(store, "eve", "Eve")
    jobs = []

    class Thread:
        def __init__(self, target, daemon=None):
            self.target = target

        def start(self):
            jobs.append(self.target)

    who = {"cl": sam}
    saved = (dc.client, dc.threading, dc.account.ensure, dc._menu_done, dc.mw.col,
             dc.plan_flow.maybe_morning, dc._update_wrap, dc._update_returns)
    dc.client = lambda: who["cl"]
    dc.threading = types.SimpleNamespace(Thread=Thread)
    dc.account.ensure = lambda *a, **k: None
    dc._menu_done = True
    dc.plan_flow.maybe_morning = lambda *a, **k: None
    dc._update_wrap = lambda *a, **k: None
    dc._update_returns = lambda *a, **k: []
    dc.mw.col = make_user_col([TODAY])
    try:
        dc._reset_runtime()
        dc.refresh_board()
        old_job = jobs[-1] if jobs else None
        who["cl"] = eve
        n = len(jobs)
        dc._on_profile_open()
        check("profile switch: the new profile's first refresh isn't held back by the old one's",
              len(jobs) == n + 1)
        if old_job:
            old_job()
        check("profile switch: the old profile's board doesn't land in the new one",
              _state["entries"] is None and _state["my_code"] == "", str(_state["entries"])[:120])
        if len(jobs) > n:
            jobs[n]()
        check("profile switch: the new profile's own board does",
              bool(_state["entries"]) and _state["entries"][0]["user_id"] == "eve")
        gen = appmod.generation
        dc._on_profile_close()
        check("profile close: nothing in flight commits after it", not dc._current(gen))
    finally:
        (dc.client, dc.threading, dc.account.ensure, dc._menu_done, dc.mw.col,
         dc.plan_flow.maybe_morning, dc._update_wrap, dc._update_returns) = saved
        dc._closing = False
        dc._fetching = False
        dc._reset_runtime()


def test_morning_not_while_closing_v311():
    """3.1.1: Anki's close runs its own AnkiWeb sync after profile_will_close;
    the plans' morning doesn't run on it."""
    import due_crew as dc
    ran = []
    saved = dc.plan_flow.maybe_morning
    dc.plan_flow.maybe_morning = lambda *a, **k: ran.append(a)
    try:
        dc._closing = True
        dc._sync_failed()
        dc._morning_fallback()
        check("closing: no morning", ran == [], str(ran))
    finally:
        dc.plan_flow.maybe_morning = saved
        dc._closing = False


def test_morning_waits_for_decks_v380():
    """3.8.0: the morning never unsuspends on the review screen (its undo
    step would sit on top of the last answer). It waits for the Decks
    screen, which runs it as the call would have."""
    import sys as _sys
    import due_crew as dc
    from due_crew import plan_flow as F
    from due_crew.app import _state
    store = world({"dre": "Dre", "maya": "Maya"})
    pid, code = store.add_plan("dre", "Step 1", "Step 1", _plan_units())
    maya = new_client(store, "maya", "Maya")
    col = _plan_col()
    box = {"cfg": {}}
    saved = {k: getattr(F, k) for k in ("cfg", "save_cfg", "_pcfg", "_psave", "client", "_today", "tooltip")}
    saved_col, saved_swap, saved_state = F.mw.col, F.app.swap, F.mw.state
    saved_dc = {k: getattr(dc, k) for k in ("_awaiting_phone", "_swap", "client")}
    qt = _sys.modules["aqt.qt"]
    saved_timer = qt.QTimer
    F.cfg = F._pcfg = lambda: box["cfg"]
    F.save_cfg = F._psave = lambda c: box.update(cfg=c)
    F.client = dc.client = lambda: maya
    F._today = lambda: _day(0)
    F.tooltip = lambda text, **kw: None
    F.mw.col = col
    F.app.swap = lambda c: None
    try:
        plan, _ = maya.follow_plan(code)
        box["cfg"]["plans"] = {pid: F.new_state(col, plan)}
        maya.fetch_board([_day(0)], with_decks=True)
        F.mw.state = "review"
        F.maybe_morning(False)  # what the 3-minute fallback calls
        check("morning: not on the review screen: nothing unsuspends, no undo step",
              _open(col) == {8} and not col.undo_steps and "plans_day" not in box["cfg"])
        check("morning: it waits for the Decks screen, as called",
              _state["plans_morning"] == {"awaiting": False, "fresh": False}, str(_state["plans_morning"]))
        F.maybe_morning(True, fresh=True)  # a refresh while still reviewing, before any AnkiWeb sync
        check("morning: a later call still waiting for AnkiWeb leaves the waiting morning as it was",
              _state["plans_morning"] == {"awaiting": False, "fresh": False} and _open(col) == {8},
              str(_state["plans_morning"]))
        F.mw.state = "deckBrowser"
        qt.QTimer = type("QTimer", (), {"singleShot": staticmethod(lambda ms, fn: fn())})
        dc._awaiting_phone = lambda: True  # still no AnkiWeb sync: the fallback's word stands
        dc._swap = lambda c: None
        dc._on_did_render(None)
        check("morning: the Decks screen runs it, in one undo step",
              _open(col) == {1, 2, 3, 8} and len(col.undo_steps) == 1 and box["cfg"]["plans_day"] == _day(0)
              and _state["plans_morning"] is None, str(_open(col)))
        dc._on_did_render(None)
        check("morning: once", len(col.undo_steps) == 1)
    finally:
        for k, v in saved.items():
            setattr(F, k, v)
        for k, v in saved_dc.items():
            setattr(dc, k, v)
        qt.QTimer = saved_timer
        F.mw.col, F.app.swap, F.mw.state = saved_col, saved_swap, saved_state
        _state["plans_morning"] = None


def test_plain_prompts_v311():
    """3.1.1: prompts that carry a crewmate's name are plain-text labels."""
    from due_crew import together, ui
    got = []
    saved = getattr(ui, "ask_text", None)
    ui.ask_text = lambda parent, title, label, text="": (got.append(label), ("", False))[1]
    try:
        try:
            together._ask_line("Good-luck card", "A line for <b>Dre</b>")
        except Exception:
            pass
        check("prompts: a crewmate's name goes through the plain-text prompt", got == ["A line for <b>Dre</b>"])
    finally:
        if saved is not None:
            ui.ask_text = saved


def test_anki_day_labels_v311():
    """3.1.1: the Anki day before the first refresh (account._today), and
    day labels across a DST change with rollover at midnight."""
    import time as _time
    from due_crew import account
    from due_crew.app import _state
    saved_col = account.mw.col
    account.mw.col = make_user_col([])
    _state["labels"] = []
    try:
        check("account: before the first refresh, today is Anki's day", account._today() == TODAY.isoformat())
    finally:
        account.mw.col = saved_col
    if not hasattr(_time, "tzset"):
        return
    old_tz = os.environ.get("TZ")
    os.environ["TZ"] = "America/New_York"
    _time.tzset()
    try:
        # clocks go forward on Sun 8 Mar 2026: a 23-hour day
        cutoff = int(datetime.datetime(2026, 3, 9, 0, 0).timestamp())
        q = StatsQueries(types.SimpleNamespace(sched=types.SimpleNamespace(day_cutoff=cutoff)))
        got = [q.day_label(i) for i in (-1, 0, 1, 2)]
        check("day labels: rollover at midnight, across the spring DST change",
              got == ["2026-03-09", "2026-03-08", "2026-03-07", "2026-03-06"], str(got))
        cutoff = int(datetime.datetime(2026, 11, 2, 0, 0).timestamp())  # back on Sun 1 Nov
        q = StatsQueries(types.SimpleNamespace(sched=types.SimpleNamespace(day_cutoff=cutoff)))
        check("day labels: and the autumn one", [q.day_label(i) for i in (0, 1)] == ["2026-11-01", "2026-10-31"])
        cutoff = int(datetime.datetime(2026, 3, 9, 4, 0).timestamp())
        q = StatsQueries(types.SimpleNamespace(sched=types.SimpleNamespace(day_cutoff=cutoff)))
        check("day labels: unchanged at a 4am rollover", q.day_label(0) == "2026-03-08")
    finally:
        if old_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old_tz
        _time.tzset()


def _skip_schedule(pid, then=None):
    """The schedule dialog, as if Cancel was pressed (no Qt here)."""
    if then:
        then()


def _spread_col(n=10):
    """Step 1 (10): n suspended new cards tagged Renal, positions n..1 (so
    the deck's order is the reverse of their ids), one of them a leech."""
    conn = sqlite3.connect(":memory:")
    fakes.make_collection(conn)
    for i in range(n):
        fakes.add_card(conn, 100 + i, did=10, queue=-1, tags="Step1::Renal" + (" leech" if i == 0 else ""), due=n - i)
    col = fakes.FakeCol(conn, fakes.day_cutoff_for(TODAY))
    col.decks = fakes.FakeDecks({10: "Step 1"})
    return col


def test_schedule_model_v32():
    """3.2: a unit's cards spread over my study days in its window; rest
    days, catch-up weeks and the taper take none; a later start moves only
    my dates; pushing back can't pass the end date."""
    from due_crew import schedule as S
    D = S.d
    mon = D("2026-10-05")  # a Monday
    unit = {"id": "rn", "name": "Renal", "opens": "2026-10-05", "due": "2026-10-11"}
    doc = {"deck": "Step 1", "units": [unit]}
    five = {"days": [1, 1, 1, 1, 1, 0, 0], "minutes": 60}
    q = [S.quota(doc, unit, five, 100, mon + datetime.timedelta(days=i)) for i in range(7)]
    check("spread: five study days take a fifth each, and the weekend none",
          q == [20, 40, 60, 80, 100, 100, 100], str(q))
    double = {"days": [1, 1, 1, 1, 1, 2, 0], "minutes": 60}
    q2 = [S.quota(doc, unit, double, 70, mon + datetime.timedelta(days=i)) for i in range(7)]
    check("spread: a double day takes twice the share", q2[4] - q2[3] == 10 and q2[5] - q2[4] == 20, str(q2))
    check("spread: no schedule opens the unit whole on its first day, as 3.1 did",
          S.quota(doc, unit, None, 100, mon) == 100 and S.quota(doc, unit, None, 100, mon - datetime.timedelta(days=1)) == 0)
    check("spread: the last day of the window has it all open", S.quota(doc, unit, five, 7, D("2026-10-11")) == 7)
    weekend = {"id": "w", "name": "W", "opens": "2026-10-10", "due": "2026-10-11"}
    check("spread: a window with no study day opens whole on my next study day",
          S.quota({"units": [weekend]}, weekend, five, 9, D("2026-10-11")) == 0
          and S.quota({"units": [weekend]}, weekend, five, 9, D("2026-10-12")) == 9)
    nodue = [{"id": "a", "name": "A", "opens": "2026-10-05"}, {"id": "b", "name": "B", "opens": "2026-10-08"}]
    check("window: without a due date, up to the day before the next date opens",
          S.window({"units": nodue}, nodue[0]) == (mon, D("2026-10-07")))
    later = dict(five, start="2026-10-12")
    check("start later: my dates move by the difference, the plan's don't",
          S.shift_days(doc, later) == 7 and S.quota(doc, unit, later, 100, D("2026-10-09")) == 0
          and S.quota(doc, unit, later, 100, D("2026-10-12")) == 20)
    ph = {"deck": "x", "end": "2026-11-15", "phases": {"catchup": 4, "taper": 7},
          "units": [dict(unit, due=None)]}
    check("phases: every 4th week is a catch-up week",
          S.phase(ph, D("2026-10-26")) == "catchup" and S.phase(ph, D("2026-10-19")) == "build")
    check("phases: the taper is the last 7 days up to the end",
          S.phase(ph, D("2026-11-09")) == "taper" and S.phase(ph, D("2026-11-08")) == "build"
          and S.weight(ph, five, D("2026-11-10")) == 0)
    long_unit = {"id": "l", "name": "L", "opens": "2026-10-19", "due": "2026-11-01"}
    lp = dict(ph, units=[dict(unit, due=None), long_unit])
    q3 = [S.quota(lp, long_unit, five, 50, D("2026-10-19") + datetime.timedelta(days=i)) for i in range(14)]
    check("spread: a catch-up week in the window opens nothing new",
          q3[6] == 50 and q3[7] == 50 and q3[4] == 50, str(q3))
    check("push back: a later start, as a date", S.pushed_start(doc, five, 2)["start"] == "2026-10-07")
    check("push back: never past the plan's end date",
          S.pushed_start(dict(doc, end="2026-10-12"), five, 2) is None
          and S.pushed_start(dict(doc, end="2026-10-13"), five, 2) is not None)
    view = S.today_view(doc, five, {"rn": 100}, {"rn": 10}, 5, D("2026-10-07"), catch="spread")
    check("today: my share, plus a quarter of what I'm behind when I chose to spread it",
          view["share"] == 20 and view["behind"] == 30 and view["target"] == 28 and view["done"] == 5, str(view))
    leave = S.today_view(doc, five, {"rn": 100}, {"rn": 10}, 0, D("2026-10-07"), catch="leave")
    check("today: leaving it open keeps just the share", leave["target"] == 20)
    caught = S.today_view(doc, five, {"rn": 100}, {"rn": 10}, 30, D("2026-10-07"), catch="leave", seen_now={"rn": 40})
    check("today: catching up today clears behind (it's counted now, not this morning)",
          caught["behind"] == 0 and caught["target"] == 20 and caught["done"] == 0, str(caught))
    ahead = S.today_view(doc, five, {"rn": 100}, {"rn": 10}, 50, D("2026-10-07"), seen_now={"rn": 60})
    check("today: past what was behind, the rest is today's", ahead["behind"] == 0 and ahead["done"] == 20, str(ahead))
    sib = S.today_view(doc, five, {"rn": 100}, {"rn": 45}, 15, D("2026-10-07"), seen_now={"rn": 60})
    check("today: what was already seen (a started note's siblings) isn't asked again",
          sib["target"] == 15 and sib["done"] == 15 and sib["behind"] == 0, str(sib))
    rest = S.today_view(doc, five, {"rn": 100}, {"rn": 100}, 0, D("2026-10-10"))
    check("today: a rest day says so", rest["kind"] == "rest" and rest["target"] == 0)
    missed = S.missed_study_days(doc, five, D("2026-10-08"), {"2026-10-05": 20, "2026-10-06": 2},
                                 {"2026-10-05": 20, "2026-10-06": 20, "2026-10-07": 20})
    check("missed: study days under a quarter of their share, back to the last one kept",
          missed == [D("2026-10-07"), D("2026-10-06")], str(missed))
    lv = S.load_view(doc, five, {"rn": 500}, mon, [100] * 60, 8.0, 30.0)
    check("load: weeks of expected reviews, the new cards' reviews on top of what's due",
          lv["weeks"][0][1] > 100 and lv["new_a_day"] == 100 and lv["cap"] == S.cap_reviews(60, 8.0, 30.0, 100))
    check("load: a week over my time is called out", lv["over"] == [l for l, v, o in lv["weeks"] if o])
    check("plan week: 1 the week the first date opens",
          S.plan_week(doc, D("2026-10-07")) == 1 and S.plan_week(doc, D("2026-10-13")) == 2 and S.plan_week(doc, D("2026-10-01")) == 0)


def test_schedule_morning_v32():
    """3.2: the morning opens up to today's quota, first cards in the
    deck's order, never a leech; again the same day opens nothing; the
    last day opens the rest and marks the unit applied."""
    from due_crew import plan_flow as F
    store = world({"dre": "Dre", "maya": "Maya"})
    start = TODAY
    unit = {"id": "rn", "name": "Renal", "opens": _day(0), "due": _day(4), "tags": ["Step1::Renal"]}
    pid, code = store.add_plan("dre", "Step 1", "Step 1", [unit])
    maya = new_client(store, "maya", "Maya")
    every = {"days": [1] * 7, "minutes": 60}
    plan, status = maya.follow_plan(code, sched=every)
    check("follow: my schedule goes with the follow, and comes back", status == 200 and plan["sched"] == every)
    maya.remember_plan(plan)
    col = _spread_col()
    state = {pid: F.new_state(col, plan)}
    res = F.run(col, [plan], state, _day(0))
    check("morning: a fifth of the unit, the first in the deck's order (highest ids first here)",
          _open(col) == {109, 108} and res["n"] == 2, str(_open(col)))
    check("morning: again the same day opens nothing", F.run(col, [plan], state, _day(0))["n"] == 0)
    F.run(col, [plan], state, _day(2))
    check("morning: a missed morning catches up to today's quota, not more", len(_open(col)) == 6, str(_open(col)))
    F.run(col, [plan], state, _day(4))
    check("morning: the last day opens the rest, never the leech", _open(col) == set(range(101, 110)))
    check("morning: then the unit is applied, as in 3.1", "rn" in state[pid]["applied"])
    got = maya.set_schedule(pid, dict(every, start=_day(3)))
    check("my schedule: changed with one request, kept on the cached plan",
          got["start"] == _day(3) and maya.session["plans"][0]["sched"]["start"] == _day(3)
          and store.follows[(pid, "maya")]["sched"]["start"] == _day(3))
    b = maya.fetch_board([_day(0)], with_decks=True)
    check("board: my schedule rides the day's first refresh", b["plans"][0]["sched"]["start"] == _day(3))
    check("my schedule: a bad one doesn't take", maya.set_schedule(pid, {"days": [0] * 7, "minutes": 60}) is False)
    del start


def test_tree_nested_v33():
    """3.3: the tree goes up nested, each name once, so deep tags fit: the
    most useful first (question ids last), a kept tag keeps its parents,
    and it stays under the server's body limit."""
    from due_crew import plans as P
    rows = [["#Big", 9000], ["#Big::#Lectures", 3000], ["#Big::#Lectures::Cardiology", 900],
            ["#Big::#Lectures::Cardiology::02_Anatomy", 120],
            ["#Big::#Lectures::Cardiology::02_Anatomy::04_Penetrating_Cardiac_Trauma", 7],
            ["#Big::#QBank", 5000]]
    rows += [[f"#Big::#QBank::{10000 + i}", 2] for i in range(40000)]
    tree, kept, left = P.nest(rows, budget=60_000)
    flat = []

    def walk(level, pre=""):
        for x in level:
            p = f"{pre}::{x[0]}" if pre else x[0]
            flat.append(p)
            if len(x) == 3:
                walk(x[2], p)
    walk(tree)
    check("tree: a tag five levels down goes up", "#Big::#Lectures::Cardiology::02_Anatomy::04_Penetrating_Cardiac_Trauma" in flat)
    check("tree: question ids fill what's left, and some are left out", left > 0 and kept == len(flat))
    check("tree: every kept tag has its parents", all("::" not in p or p.rsplit("::", 1)[0] in set(flat) for p in flat))
    check("tree: it fits the budget", len(json.dumps(tree)) <= 60_000, str(len(json.dumps(tree))))
    store = world({"dre": "Dre"})
    dre = new_client(store, "dre", "Dre")
    check("tree: the server takes it", dre.put_tree("Step 1", rows[:6], []) and store.plan_trees[("dre", "Step 1")].get("v") == 2)


def test_hold_back_v33():
    """3.3: a deck whose cards are all active (a teacher's shared deck):
    Follow offers to hold back later dates' never-studied cards; asked,
    they're suspended in one undo step, open on their day, and stopping
    opens them again. Nothing studied, and nothing on an opened date, is held."""
    from due_crew import plans as P
    conn = sqlite3.connect(":memory:")
    fakes.make_collection(conn)
    for i in range(6):  # 100-102 unidad 1 (today), 103-105 unidad 2 (in three days); 105 already studied
        fakes.add_card(conn, 100 + i, did=10, queue=2 if i == 5 else 0, ctype=2 if i == 5 else 0,
                       tags="Unidad_1" if i < 3 else "Unidad_2", due=i)
    col = fakes.FakeCol(conn, fakes.day_cutoff_for(TODAY))
    col.decks = fakes.FakeDecks({10: "Español 1"})
    doc = {"deck": "Español 1", "units": [
        {"id": "u1", "name": "Unidad 1", "opens": _day(0), "tags": ["Unidad_1"], "decks": [], "cards": []},
        {"id": "u2", "name": "Unidad 2", "opens": _day(3), "tags": ["Unidad_2"], "decks": [], "cards": []}]}
    idx = P.DeckIndex(col, 10)
    held = P.holdable(idx, doc, _day(0))
    check("hold: only later dates' new, active cards", held == {103, 104}, str(held))
    n = P.hold_cards(col, held, "Due Crew: hold back Español")
    check("hold: suspended, one undo step", n == 2 and _open(col) == {100, 101, 102, 105}
          and col.undo_steps[-1][0] == "Due Crew: hold back Español")
    check("hold: nothing left to hold after", P.holdable(P.DeckIndex(col, 10), doc, _day(0)) == set())
    P.open_cards(col, held, "Due Crew: stop Español")
    check("hold: stopping opens them again", _open(col) == {100, 101, 102, 103, 104, 105})


def test_class_through_step_v33():
    """3.3, C1-C5: Anki's own limit shows on the card with the fix; a date
    opens days early; an Anki search is a date's contents; a renamed tag
    falls back to the author's note ids; the author's ids go up once."""
    from due_crew import plans as P
    from due_crew import plan_flow as F
    col = _spread_col()
    idx = P.DeckIndex(col, 10)
    # C3: a search, run by this collection and kept to the deck
    col.find_cards = lambda q: [101, 102, 999] if q == "tag:L14" else []
    idx = P.DeckIndex(col, 10)
    got = idx.match({"id": "s", "tags": [], "decks": [], "cards": [], "search": ["tag:L14"]}, None, "Step 1")
    check("search: its cards, only those in the plan's deck", got == {101, 102}, str(got))
    check("search: a unit's sig changes with its searches, and stays for one without",
          P.unit_sig({"tags": ["a"]}) == P.unit_sig({"tags": ["a"], "search": []})
          and P.unit_sig({"tags": ["a"]}) != P.unit_sig({"tags": ["a"], "search": ["tag:x"]}))
    # C5: a tag this copy doesn't have: the author's note ids find it
    guids = {cid: g for (g, _o), cid in idx.by_ref.items()}
    u = {"id": "r", "tags": ["Step1_v13::Renal"], "decks": [], "cards": [], "ids": [guids[103], guids[104]]}
    got = idx.match(u, None, "Step 1")
    check("renamed tag: matched by the author's note ids, and noted", got == {103, 104} and "r" in idx.fell_back, str(got))
    idx2 = P.DeckIndex(col, 10)
    check("renamed tag: a tag that matches doesn't use them", idx2.match(dict(u, tags=["Step1::Renal"]), None, "Step 1")
          == set(range(100, 110)) and not idx2.fell_back)
    snap = P.ids_snapshot(idx2, {"deck": "Step 1", "units": [{"id": "r", "tags": ["Step1::Renal"], "decks": []}]})
    check("snapshot: the note ids behind a date's tags, with the tags they came from",
          snap["r"][0] == ["Step1::Renal"] and len(snap["r"][2]) == 10)
    # C1 and C2 on the card
    week = [{"day": "2026-09-0%d" % (i + 1), "dow": "Mon", "num": i + 1, "today": i == 0, "past": False, "rest": False, "prep": False,
             "events": [], "units": [{"uid": "u1", "name": "L14", "total": 9, "seen": 3, "state": "open", "prep": False}] if i == 0 else [],
             "new": 9 if i == 0 else 0, "seen": 3 if i == 0 else 0} for i in range(7)]
    card = {"id": "p1", "title": "Block", "sub": "", "week": week, "rows": [{"name": "L14", "uid": "u1", "state": "now", "seen": [3, 9], "n": "crew 1/2"}],
            "lines": [], "change": None, "no_deck": False, "paused": False,
            "session": {"kind": "study", "target": 60, "done": 0, "due": 10, "minutes": 20, "behind": 0, "limit": 20, "fell_back": 3}}
    html = board._plan_card_html(card)
    check("limit: the card says Anki shows fewer, with Raise", "Anki shows 20 new a day" in html and "planlimit:p1" in html)
    check("limit: not when Anki shows enough", "planlimit" not in board._plan_card_html(
        dict(card, session=dict(card["session"], limit=80))))
    check("study: a day's date builds its deck, in the day's details", "planstudydate:p1:u1" in html and 'class="pday"' in html)
    enough = dict(card, session=dict(card["session"], limit=80))  # one note at a time: the limit comes first
    check("renamed tags: said once, with OK", "3 dates use tags your deck names differently" in board._plan_card_html(enough)
          and "planidsok:p1" not in board._plan_card_html(dict(enough, fallback_ok=True)))
    # C2: the morning looks ahead
    store = world({"dre": "Dre", "maya": "Maya"})
    unit = {"id": "rn", "name": "Renal", "opens": _day(2), "tags": ["Step1::Renal"]}
    pid, code = store.add_plan("dre", "Step 1", "Step 1", [unit])
    maya = new_client(store, "maya", "Maya")
    plan, _ = maya.follow_plan(code)
    maya.remember_plan(plan)
    col = _spread_col()
    state = {pid: F.new_state(col, plan)}
    F.run(col, [plan], state, _day(0))
    check("early: off, a date two days out stays shut", _open(col) == set())
    check("early: set with one request, kept on the plan", maya.set_early(pid, 2) and store.follows[(pid, "maya")]["early"] == 2)
    F.run(col, [dict(plan, early=2)], state, _day(0))
    check("early: two days early, it opens today", _open(col) == set(range(101, 110)))
    check("early: the plan's line says so", "· opens 2 days early ·" in F.card_view(dict(plan, early=2), state[pid], {}, _day(0))["sub"])
    # C5: the author's Anki sends the ids behind its plan's tags
    dre = new_client(store, "dre", "Dre")
    dre.fetch_board([_day(0)], with_decks=True)
    check("authored: my plans ride the day's first board", [a["id"] for a in dre.session.get("plans_authored") or []] == [pid])
    ok = dre.put_ids(pid, {"rn": [["Step1::Renal"], [], ["g1", "g2"]]})
    check("ids: kept on the date", ok and store.plans[pid]["doc"]["units"][0].get("ids") == ["g1", "g2"])
    # 3.4, D1: a pasted search's count, from my Anki, with the same request
    store.plans[pid]["doc"]["units"][0]["search"] = ["tag:L14"]
    dre.fetch_board([_day(0)], with_decks=True)
    lean = dre.session["plans_authored"][0]["doc"]
    check("authored: carries its searches", lean["units"][0]["search"] == ["tag:L14"])
    scol = _spread_col()
    scol.find_cards = lambda q: [101, 102, 103] if q == "tag:L14" else []
    counts = P.search_counts(P.DeckIndex(scol, 10), lean)
    check("search count: from my copy", counts["rn"]["tag:L14"] == 3, str(counts))
    check("search count: rides the ids request", dre.put_ids(pid, {}, counts)
          and store.plans[pid]["doc"]["units"][0].get("sn") == {"tag:L14": 3})
    # 3.6.5: pasted ids go up as the cards they are, kept while the ids hold
    store.plans[pid]["doc"]["units"][0].update(nids=[50], notes=["guid000003"])
    dre.fetch_board([_day(0)], with_decks=True)
    lean = dre.session["plans_authored"][0]["doc"]
    check("authored: carries its ids and notes", lean["units"][0].get("nids") == [50]
          and lean["units"][0].get("notes") == ["guid000003"], str(lean))
    acol = _plan_col()
    refs = P.id_refs(P.DeckIndex(acol, 10), acol, lean)
    check("refs: ride the ids request, kept on the date", dre.put_ids(pid, {}, None, refs)
          and sorted(map(tuple, store.plans[pid]["doc"]["units"][0].get("idr") or [])) == [("guid000050", 0), ("guid000050", 1)])
    stale = {"rn": [[51], [], [["guid000051", 0]]]}
    check("refs: worked out from ids the date no longer has: dropped", dre.put_ids(pid, {}, None, stale)
          and len(store.plans[pid]["doc"]["units"][0]["idr"]) == 2)
    doc = json.loads(json.dumps(store.plans[pid]["doc"]))
    doc["units"][0]["idr"] = [["forged", 0]]
    store.edit_plan(pid, doc["units"])
    check("refs: a site save can't set them, and keeps them while the ids hold",
          len(store.plans[pid]["doc"]["units"][0]["idr"]) == 2, str(store.plans[pid]["doc"]["units"][0].get("idr")))
    doc["units"][0]["nids"] = [51]
    store.edit_plan(pid, doc["units"])
    check("refs: new ids drop them until the author's Anki sends the new ones",
          "idr" not in store.plans[pid]["doc"]["units"][0])
    # 3.6.5, P1: what each date opens, counted here, kept while its picks are
    check("counts (P1): ride the ids request", dre.put_ids(pid, {}, {"rn": {"#pn": [80, 3, 1]}})
          and store.plans[pid]["doc"]["units"][0].get("pn") == [80, 3, 1])
    doc = json.loads(json.dumps(store.plans[pid]["doc"]))
    doc["units"][0]["pn"] = [1, 1, 1]
    store.edit_plan(pid, doc["units"])
    check("counts (P1): a site save keeps the stored ones while the picks hold", store.plans[pid]["doc"]["units"][0].get("pn") == [80, 3, 1])
    doc["units"][0]["tags"] = ["Step1::Cardio"]
    store.edit_plan(pid, doc["units"])
    check("counts (P1): and drops them when they change", "pn" not in store.plans[pid]["doc"]["units"][0])


def test_plans_tab_v33():
    """3.3: plans have their own place (a Plans tab; You › Plans since
    3.8.0); Decks is decks again."""
    from due_crew import board
    card = {"id": "p1", "title": "Step 1 · Dre’s plan", "sub": "week 1 of 4", "rows": [], "lines": [], "change": None,
            "no_deck": False, "paused": False}
    data = {"entries": [], "labels": [TODAY.isoformat()], "tomorrow": "", "pending": []}
    plans, empty = {"cards": [card], "offers": []}, {"cards": [], "offers": []}
    with_plan = board.render(data, {"period": "today"}, 0, plans=plans, you={"tab": "plans", "plans": plans})
    check("You › Plans: the card on it, the tab beside Insights",
          "duecrew:duetab:plans" in with_plan and "duecrew:duetab:insights" in with_plan and "Step 1 · Dre’s plan" in with_plan)
    check("the board: Crew and Squads, no Plans tab", "period:plans" not in with_plan and "period:squads" in with_plan)
    decks = board.render(data, {"period": "decks"}, 0, plans=plans, you={"tab": "insights", "plans": plans})
    check("plans: the card isn't on Crew › Decks, nor under Insights", "Step 1 · Dre’s plan" not in decks)
    none = board.render(data, {"period": "today"}, 0, plans=empty, you={"tab": "plans", "plans": empty})
    check("You › Plans: following nothing, three ways in",
          "Follow a plan" in none and "planlibrary" in none and "planmake" in none and "dc-plancode" in none)
    hidden = board.render(data, {"period": "plans", "hidden_tabs": ["plans", "decks"]}, 0, plans=plans,
                          you={"tab": "plans", "plans": plans})
    check("tabs: hidden in Settings, gone, and a saved Plans period falls back to Crew's Today",
          "duetab:plans" not in hidden and "Step 1 · Dre" not in hidden and "period:decks" not in hidden
          and "period:squads" in hidden and 'dc-pill on" href="#" onclick="pycmd(\'duecrew:period:today' in hidden)
    bare = board.render(data, {"hidden_tabs": ["plans", "insights"]}, 0, plans=plans, you={"tab": "plans", "plans": plans})
    check("You: Due off, Plans and Insights hidden: no bubble at all", 'class="du' not in bare and "duetab" not in bare)
    old = board.render(data, {"hidden_tabs": ["today", "week"]}, 0)
    check("tabs: Crew can't be hidden, nor Week (Crew's picker since 3.8.0)",
          "period:today" in old and "period:week" in old)


def test_even_split_v33():
    """3.3: a date the author split evenly opens in the same slices for
    someone without a schedule: the plan's days, the deck's order; the
    server keeps `even` and the pace, and an old add-on's shapes drop them."""
    from due_crew import plan_flow as F
    from due_crew.backend import shapes
    store = world({"dre": "Dre", "maya": "Maya"})
    unit = {"id": "rn", "name": "Renal", "opens": _day(0), "due": _day(4), "tags": ["Step1::Renal"], "even": True}
    pid, code = store.add_plan("dre", "Step 1", "Step 1", [unit])
    check("even: kept on the plan", store.plans[pid]["doc"]["units"][0].get("even") is True)
    bad = None
    try:
        store._plan_doc({"deck": "x", "units": [dict(unit, due=_day(0))]})
    except fakes.Bad as e:
        bad = e
    check("even: needs a window of more than one day", bad is not None)
    maya = new_client(store, "maya", "Maya")
    plan, status = maya.follow_plan(code)
    check("even: followed without a schedule", status == 200 and not plan.get("sched") and plan["doc"]["units"][0].get("even"))
    maya.remember_plan(plan)
    col = _spread_col()
    state = {pid: F.new_state(col, plan)}
    F.run(col, [plan], state, _day(0))
    check("even: day one opens a fifth, first in the deck's order", _open(col) == {109, 108}, str(_open(col)))
    F.run(col, [plan], state, _day(2))
    check("even: a missed morning catches up to the day's slice", len(_open(col)) == 6, str(_open(col)))
    F.run(col, [plan], state, _day(4))
    check("even: the last day opens the rest, then it's applied",
          _open(col) == set(range(101, 110)) and "rn" in state[pid]["applied"])
    doc = shapes.clean_plan_doc({"deck": "x", "pace": {"mode": "end", "days": [1, 1, 1, 1, 1, 0, 0], "daily": 90, "cover": ["tag:a"]},
                                 "units": [dict(unit), dict(unit, id="b", even="yes")]})
    check("shapes: even, the plan's days and what it covers (3.6.5, for the export) come through, nothing else of the pace",
          doc["pace"] == {"days": [1, 1, 1, 1, 1, 0, 0], "cover": ["tag:a"]} and doc["units"][0]["even"] is True and "even" not in doc["units"][1])


def _knows_col():
    """Step 1 (10) with Sub (11), and Other (20). 1: mature and clean;
    2: mature but missed yesterday; 3: lapsed three times; 4: young, missed
    today; 5: mature, in Other; 6: mature, in Sub."""
    conn = sqlite3.connect(":memory:")
    fakes.make_collection(conn)
    fakes.add_card(conn, 1, did=10, ctype=2, queue=2, ivl=40)
    fakes.add_card(conn, 2, did=10, ctype=2, queue=2, ivl=40)
    fakes.add_card(conn, 3, did=10, ctype=2, queue=2, ivl=3, lapses=3)
    fakes.add_card(conn, 4, did=10, ctype=2, queue=2, ivl=2)
    fakes.add_card(conn, 5, did=20, ctype=2, queue=2, ivl=90)
    fakes.add_card(conn, 6, did=11, ctype=2, queue=2, ivl=30)
    noon = int(datetime.datetime.combine(TODAY, datetime.time(12)).timestamp() * 1000)
    fakes.add_review(conn, noon - 86400000, ease=1, cid=2)
    fakes.add_review(conn, noon, ease=1, cid=4)
    fakes.add_review(conn, noon + 60000, ease=3, time_ms=90000, rtype=0, cid=4)
    col = fakes.FakeCol(conn, fakes.day_cutoff_for(TODAY))
    col.decks = fakes.FakeDecks({10: "Step 1", 11: "Step 1::Sub", 20: "Other"})
    return col


def test_who_knows_v32():
    """3.2: the cards I know and the ones I'm stuck on (in decks I share),
    sent as changes; who knows mine comes back in the same sync; the chip;
    an ask; This helped; my log."""
    from due_crew import cards as K
    col = _knows_col()
    known, stuck = K.known_and_stuck(col, [10], fakes.day_cutoff_for(TODAY))
    check("known: mature, no miss in 30 days, in the deck I share and its subdecks",
          known == {"guid000001", "guid000006"}, str(known))
    check("stuck: lapsed twice or more, or missed today; most lapses first",
          stuck == ["guid000003", "guid000004"], str(stuck))
    check("known and stuck: nothing without a shared deck", K.known_and_stuck(col, [], 0) == (set(), []))
    labels = [_day(0)]
    store = world({"sam": "Sam", "dre": "Dre", "mo": "Mo"},
                  {"sam": ["dre", "mo"], "dre": ["sam"], "mo": ["sam"]})
    sam, dre = new_client(store, "sam", "Sam"), new_client(store, "dre", "Dre")
    ok, _g = dre.push(labels, {}, known={"guid000003", "guid000009"})
    check("knows: the first upload starts from nothing", ok and store.bodies[-1][2]["knows"]["reset"] is True
          and store.knows == {("dre", "guid000003"), ("dre", "guid000009")})
    dre.push(labels, {}, known={"guid000003", "guid000010"})
    check("knows: then only what changed", store.bodies[-1][2]["knows"] == {"add": ["guid000010"], "del": ["guid000009"]})
    dre.push(labels, {}, known={"guid000003", "guid000010"})
    check("knows: nothing changed, nothing sent", "knows" not in store.bodies[-1][2])
    many = {f"g{i:05d}" for i in range(2500)}
    other = new_client(store, "mo", "Mo")
    other.push(labels, {}, known=many)
    other.push(labels, {}, known=many)
    check("knows: at most 2,000 a sync, the rest at the next",
          len(store.bodies[-2][2]["knows"]["add"]) == 2000 and len(store.bodies[-1][2]["knows"]["add"]) == 500
          and sum(1 for u, _g in store.knows if u == "mo") == 2500)
    dre.send_cheer("sam", "\U0001F4A1", "Loop of Henle", guid="guid000003")
    sam.push(labels, {}, stuck=["guid000003", "guid000004"])
    cardsin = sam.session["cards"]
    check("stuck: who knows it and their tips come back in the same sync",
          cardsin == {"guid000003": {"knows": ["dre"], "tips": [{"from": "dre", "text": "Loop of Henle", "helped": False}]}},
          str(cardsin))
    check("helped: one request, and the session keeps it",
          sam.tip_helped("guid000003", "dre") and cardsin["guid000003"]["tips"][0]["helped"] is True
          and ("guid000003", "dre", "sam") in store.helped)
    names = {"dre": ("Dre Ng", "\U0001F419"), "mo": ("Mo", "")}
    v = K.chip_view({"knows": ["dre", "mo"], "tips": []}, [], names)
    check("chip: who knows it, and Ask", v["text"] == "\U0001F419 Dre and 1 more know this" and v["cmd"] == "knowsask")
    check("chip: a tip comes first", K.chip_view(cardsin["guid000003"], [], names)["cmd"] == "knowstip")
    both = K.chip_view(cardsin["guid000003"], [{"from": "dre", "name": "Dre Ng", "note": "same tip"},
                                               {"from": "mo", "name": "Mo", "note": "another"}], names)
    check("chip: one tip per person, the rest counted, This helped for the first",
          both["more"] == 1 and both["actcmd"] == "knowshelped:dre" and both["act"] == "\u2713 Helped", str(both))
    check("chip: nobody I can name, nothing", K.chip_view({"knows": ["zed"], "tips": []}, [], names) is None)
    asked = K.chip_view(None, [], names, asks=[("dre", 1)])
    check("chip: a crewmate's ask on a card I have, with Tip", asked["cmd"] == "knowsreply:dre:1" and asked["act"] == "Tip")
    asked_q = K.chip_view(None, [], names, asks=[("dre", 1, "why axillary?")])
    check("chip: a crewmate's ask shows their line, and a short form for a narrow bar",
          asked_q["text"] == "\U0001F419 Dre: \u201cwhy axillary?\u201d" and asked_q["short"] == "\U0001F419 Dre asked"
          and asked["text"] == "\U0001F419 Dre asked about this", str(asked_q))
    check("chip: once I've asked, it says so (Asked changes my line)",
          K.chip_view({"knows": ["dre"]}, [], names, mine=True)["act"] == "Asked" and v["act"] == "Ask"
          and v["short"] == "\U0001F419 Dre +1")
    check("chip: a tip's short form names whose tip it is",
          K.chip_view(cardsin["guid000003"], [], names)["short"] == "\U0001F4A1 Dre's tip")
    js = K.chip_js({"text": "</span><script>x</script>", "cmd": "knowsask", "act": "Ask", "accent": "#0a0"})
    check("chip: text goes in as text", "textContent" in js and "innerHTML" not in js)
    acked(sam, sam.fetch_board(labels))  # Dre's tip is read, and the next refresh
    sam.fetch_board(labels)               # says so: a flag on that card may go up again
    sam.session["tricky"] = [{"guid": "guid000003", "deck": "Step 1", "at": _day(0), "text": "A card", "q": "Trick?"}]
    from due_crew import together
    from due_crew.app import _state
    real_client, real_entries, real_labels = together.client, _state["entries"], _state["labels"]
    together.client = lambda: sam
    _state["labels"] = labels
    col.db.conn.execute("UPDATE notes SET flds = ? WHERE guid = 'guid000001'", ("Insulin drives {{c1::K}} in\x1fback",))
    _state["entries"] = [{"user_id": "dre", "name": "Dre Ng", "you": False}]
    sam.session.setdefault("cards", {})["guid000003"] = {"knows": ["dre"], "tips": []}
    w = together._wrap_data()
    w["tips"] = {"guid000001": [{"from": "dre", "name": "Dre Ng", "note": "x", "day": _day(0)}]}
    sys.modules["aqt"].mw.col = col
    asks = together.my_asks_view()
    sys.modules["aqt"].mw.col = None
    check("your asks (K3): my open ask says who has it down; an answered one reads its text from my copy",
          [(a["guid"], a["state"], a["who"]) for a in asks] == [("guid000003", "open", ["Dre"]), ("guid000001", "answered", ["Dre"])]
          and asks[1]["text"] == "Insulin drives [\u2026] in", str(asks))
    w.pop("tips", None)
    together.client, _state["entries"], _state["labels"] = real_client, real_entries, real_labels
    doc = sam.week_doc(labels, {})
    check("ask: rides my week as the guid and my line, never the card's text",
          doc["tricky"] == [{"guid": "guid000003", "deck": "Step 1", "at": _day(0), "q": "Trick?"}])
    sam.push(labels, {})
    board_ = dre.fetch_board(labels)
    check("ask: the crewmate reads it", board_["entries"][1]["tricky"][0]["q"] == "Trick?")
    check("ask: a card I know is known", K.i_know(col, ["guid000001", "guid000003"]) == {"guid000001"})
    log = K.log_days(col, 8)
    check("log: minutes, reviews, new cards and retention, studied days only",
          log == {_day(-1): [0, 1, 1, 0.0], _day(0): [2, 2, 1, 50.0]}, str(log))
    sam.push(labels, {}, log={f"2026-0{m}-1{d}": [1, 1, 0, None] for m in (5, 6) for d in range(9)}, log_window="full")
    check("log: the long first upload marks it sent", sam.session["log_full"] == "sam" and len(store.logs["sam"]) == 18)
    dre.session.pop("log_full", None)
    dre.push(labels, {}, log={}, log_window="full")
    check("log: a first window with nothing in it (months away) still counts as sent, so the history import can start",
          dre.session.get("log_full") == "dre")
    sam.push(labels, {}, log={"2026-06-19": [1, 1, 0, None]})
    sam.push(labels, {}, log={"2026-06-19": [1, 1, 0, None]})
    check("log: unchanged, not sent again", "log" not in store.bodies[-1][2])
    got = sam._call("GET", "/log")[1]
    check("log: mine to read", len(got["days"]) == 19)
    sam.session["recap"] = {"name": "Step 1", "n": 3, "day": _day(0)}
    sam.push(labels, {})
    check("recap: rides my week, and a crewmate sees it",
          dre.fetch_board(labels)["entries"][1]["recap"] == {"name": "Step 1", "n": 3, "day": _day(0)})


def test_older_server_v32():
    """3.2 against a Worker still on 3.1 (merged, not yet deployed): a sync
    it refuses for 3.2's parts goes again without them, and the day's
    numbers still land. Nothing 3.2 is marked sent."""
    store = world({"sam": "Sam"})
    real = store._sync

    def old_sync(me, body):
        if set(body) - {"profile", "week", "decks", "heatmap", "squads", "settings", "plans"} or "recap" in (body.get("week") or {}):
            raise fakes.Bad(400, "bad_sync")
        return real(me, body)
    store._sync = old_sync
    sam = new_client(store, "sam", "Sam")
    sam.session["recap"] = {"name": "Step 1", "n": 2, "day": _day(0)}
    ok, _g = sam.push([_day(0)], {}, known={"g1"}, stuck=["g2"], log={_day(0): [1, 1, 0, None]})
    sent = [b for m, p, b in store.bodies if p == "/sync"]
    check("older server: the sync still goes, without 3.2's parts", ok and len(sent) == 2
          and not {"knows", "stuck", "log"} & set(sent[1]) and "recap" not in sent[1]["week"])
    check("older server: nothing 3.2 is marked sent", "log_hash" not in sam.session and sam._load_known()[1] is None)


def test_admin_notice_v321():
    """3.2.1: the admin's notice rides the board (for my version), shows on
    top of every tab escaped, with More only for an https link, and a
    dismiss that sticks by id."""
    store = world({"sam": "Sam"})
    store.notices = [{"id": 1, "text": "Everyone <b>hi</b>", "link": "https://duecrew.com/plans"},
                     {"id": 2, "text": "Please update", "below": "3.2.1", "link": "javascript:x"}]
    sam = new_client(store, "sam", "Sam")
    sam.push([_day(0)], {}, version="3.1.1")
    got = sam.fetch_board([_day(0)])["notice"]
    check("notice: an older add-on gets the one for older versions, and no unsafe link",
          got == {"id": 2, "text": "Please update", "link": ""}, str(got))
    sam.push([_day(0)], {}, version="3.2.1")
    got = sam.fetch_board([_day(0)])["notice"]
    check("notice: a current one gets the one for everyone", got["id"] == 1 and got["link"] == "https://duecrew.com/plans")
    html_ = board.notice_html(got)
    check("notice: escaped, More opens it from Python, dismiss by id",
          "&lt;b&gt;hi&lt;/b&gt;" in html_ and "noticeopen" in html_ and "noticex:1" in html_ and "duecrew.com/plans" not in html_)
    check("notice: no link, no More", "noticeopen" not in board.notice_html({"id": 3, "text": "x", "link": ""}))
    page = board.render({"entries": [], "labels": [_day(0)], "tomorrow": "", "pending": []}, {"period": "week"}, 0,
                        notice=got)
    check("notice: on top of the board", "noticex:1" in page)


def test_session_card_v32():
    """3.2: today's session on my schedule, the missed-days question, the
    recap on a new plan week, checkpoints; the board draws them escaped."""
    from due_crew import plan_flow as F
    from due_crew import plans as P
    col = _spread_col(20)
    start = TODAY - datetime.timedelta(days=3)  # opened three days ago, due in four
    unit = {"id": "rn", "name": "Renal <i>", "opens": start.isoformat(), "due": _day(3), "tags": ["Step1::Renal"],
            "check": _day(0)}
    plan = {"id": "p1", "name": "Step 1", "ownerName": "Dre", "version": 1, "followers": 3,
            "doc": {"deck": "Step 1", "units": [unit]}, "sched": {"days": [1] * 7, "minutes": 60}}
    st = F.new_state(col, plan)
    F.run(col, [plan], {"p1": st}, _day(0))
    idx = P.DeckIndex(col, 10)
    # nothing seen on the three days before: all three missed
    v = F.session_view(plan, st, idx, {}, _day(0), (8.0, 30.0), due=40)
    check("session: today's share and what's waiting", v["share"] == 3 and v["behind"] == 9 and v["kind"] == "study", str(v))
    check("session: the question, with how much spreading adds a day and how far pushing goes",
          v["ask"] and v["ask"]["waiting"] == 9 and v["ask"]["spread"] == 3 and v["ask"]["push"] == 3
          and len(v["ask"]["days"]) == 3, str(v["ask"]))
    check("session: minutes from my pace: reviews due and today's new", v["minutes"] == round((40 * 8 + 3 * 30) / 60))
    st["catch"] = {"mode": "spread", "day": _day(0)}
    v2 = F.session_view(plan, st, idx, {}, _day(0), (8.0, 30.0), due=40)
    check("session: answered, the question goes, and spreading adds a quarter a day",
          v2["ask"] is None and v2["target"] == 3 + 3)
    seen_today = {c: 0 for c in list(idx.cards)[:4]}
    for c in seen_today:
        col.db.conn.execute("UPDATE cards SET type = 2, queue = 2 WHERE id = ?", (c,))
    v3 = F.session_view(plan, dict(st, catch=None), F_idx := P.DeckIndex(col, 10), seen_today, _day(0))
    check("session: cards seen today fill what's behind first (the oldest dates), then today's",
          v3["behind"] == 5 and v3["done"] == 0, str(v3))
    idx = F_idx
    html_ = board._plan_card_html(F.card_view(plan, st, {}, _day(0), session=v2))
    check("board: 3.8.0, no Today box on the plan (Due's Today has today's cards); names escaped",
          'class="ptoday' not in html_ and "planstudy:p1" not in html_
          and "<i>" not in html_.replace("<i style", "").replace("<i class", ""), html_[:600])
    html_q = board._plan_card_html(F.card_view(plan, st, {}, _day(0), session=v))
    check("board: the missed-days question, three ways",
          "planspread:p1" in html_q and "planpush:p1" in html_q and "planleave:p1" in html_q and "Missed" in html_q)
    check("board: 3.3, no schedule to set: the plan's days are it", "plansched:p1" not in board._plan_card_html(
        F.card_view(dict(plan, sched=None), st, {}, _day(0))))
    v0 = F.session_view(dict(plan, sched=None), st, idx, seen_today, _day(0))
    check("session: 3.3, without a schedule the plan's own days give today, and no missed-days question",
          v0 is not None and v0["ask"] is None and "target" in v0)
    # the recap: on the first day of a plan week
    monday = TODAY + datetime.timedelta(days=(7 - TODAY.weekday()) % 7)
    mon_plan = dict(plan, doc=dict(plan["doc"], units=[dict(unit, opens=(monday - datetime.timedelta(days=7)).isoformat(),
                                                             due=(monday + datetime.timedelta(days=6)).isoformat())]))
    rv = F.session_view(mon_plan, st, idx, {}, monday.isoformat())
    check("recap: week 1 done, the first day of week 2", rv["recap"] and rv["recap"]["n"] == 1
          and rv["recap"]["sessions"][1] == 7, str(rv["recap"]))
    # checkpoints
    due = F.checks_due(plan["doc"], st, plan["sched"], _day(0))
    check("checkpoint: due on its morning", [k for k, _n, _us, _c in due] == ["rn"])
    rdoc = dict(plan["doc"], reviews=[{"day": _day(0), "from": "rn", "to": "rn"}])
    rdue = F.checks_due(rdoc, st, plan["sched"], _day(0))
    check("review day: 3.3, due on its morning with its dates, named for them",
          [(k, n) for k, n, _us, _c in rdue][-1] == (f"r:{_day(0)}:rn:rn", "Review · Renal <i>") and rdue[-1][3] == 200)
    check("checkpoint: not built late past three mornings", F.checks_due(plan["doc"], st, plan["sched"], _day(4)) == [])
    col.db.conn.execute("UPDATE cards SET type = 2, queue = 2, lapses = id - 100 WHERE id IN (105, 106, 107)")
    idx = P.DeckIndex(col, 10)
    picked = F.check_cards(col, idx, idx.match(unit, None, "Step 1"), n=2)
    check("checkpoint: seen cards, most lapses first", picked == [107, 106], str(picked))
    st["checks"] = {"rn": {"day": _day(0), "at": 0, "cids": [107, 106]}}
    cv = F.session_view(plan, st, idx, {}, _day(0), answered={107: (3, 1), 106: (1, 2)})
    check("checkpoint: the score, first answers since it was built",
          cv["checks"] == [{"name": "Renal <i>", "n": 2, "answered": 2, "right": 1, "day": _day(0)}])
    ch = board._plan_card_html(F.card_view(plan, st, {}, _day(0), session=cv))
    check("board: the checkpoint's score, its name escaped", "1 of 2" in ch and "Renal &lt;i&gt;" in ch)
    rows_ = board.build_rows([{"user_id": "dre", "name": "Dre", "you": False, "paused": False, "last_updated": "",
                               "days": {}, "recap": {"name": "Step 1", "n": 3, "day": _day(0)}}],
                             [_day(0)], "", "today", {})
    allrows = rows_[0] + rows_[1]
    check("recap: on a crewmate's row the day it's new", allrows and allrows[0]["recap"]["n"] == 3)


def test_schedule_parity_v32():
    """3.2: the site's schedule arithmetic (Sched in site/public/app.js) gives
    the add-on's quota on every case here. Needs node; skipped without it."""
    import shutil
    import subprocess
    from due_crew import schedule as S
    node = shutil.which("node")
    if not node:
        print("SKIP schedule parity: no node")
        return
    js = open(os.path.join(REPO, "site", "public", "app.js")).read()
    head = js[js.index("const MONTHS"):js.index("const today =")]
    sched_js = js[js.index("const Sched = (() => {"):js.index("// ---- 3.2: home")]
    docs = [
        {"deck": "x", "end": "2026-12-06", "phases": {"catchup": 4, "taper": 10},
         "units": [{"id": "a", "name": "A", "opens": "2026-10-05", "due": "2026-10-25"},
                   {"id": "b", "name": "B", "opens": "2026-10-26"},
                   {"id": "c", "name": "C", "opens": "2026-11-02", "due": "2026-11-30"}]},
        {"deck": "x", "units": [{"id": "a", "name": "A", "opens": "2026-10-10", "due": "2026-10-11"},
                                {"id": "b", "name": "B", "opens": "2026-10-12", "due": "2026-10-20"}]},
        # 3.3: even splits, over the plan's own days (weekends off) without a schedule
        {"deck": "x", "pace": {"mode": "placed", "days": [1, 1, 1, 1, 1, 0, 0]}, "phases": {"catchup": 3, "taper": 0},
         "units": [{"id": "a", "name": "A", "opens": "2026-10-05", "due": "2026-10-09", "even": True},
                   {"id": "b", "name": "B", "opens": "2026-10-07"},
                   {"id": "c", "name": "C", "opens": "2026-10-10", "due": "2026-10-11", "even": True},
                   {"id": "d", "name": "D", "opens": "2026-10-12", "due": "2026-10-30", "even": True}]},
    ]
    scheds = [None, {"days": [1, 1, 1, 1, 1, 2, 0], "minutes": 60},
              {"days": [1, 0, 1, 0, 1, 0, 0], "minutes": 60, "start": "2026-10-14"}]
    cases = []
    for di, doc in enumerate(docs):
        for si, sc in enumerate(scheds):
            for u in doc["units"]:
                for k in range(0, 70, 3):
                    day = (datetime.date(2026, 10, 1) + datetime.timedelta(days=k)).isoformat()
                    cases.append([di, si, u["id"], 97, day, S.quota(doc, u, sc, 97, S.d(day))])
    prog = head + "\n" + sched_js + (
        f"const docs = {json.dumps(docs)}; const scheds = {json.dumps(scheds)}; const cases = {json.dumps(cases)};\n"
        "let bad = 0; for (const [di, si, uid, total, day, want] of cases) {"
        " const doc = docs[di]; const u = doc.units.find((x) => x.id === uid);"
        " if (Sched.quota(doc, u, scheds[si], total, day) !== want) bad++; }"
        " console.log(bad);")
    out = subprocess.run([node, "-e", prog], capture_output=True, text=True, timeout=60)
    check("schedule: the site's arithmetic is the add-on's", out.stdout.strip() == "0", out.stdout + out.stderr)


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
    check("week: the site's calendar look; names escaped; today's date filled; 3.8.0, every day's details shut "
          "until its click (today's are the box's Today)",
          'class="pwk"' in h and "V&amp;B &lt;i&gt;" in h and "<i>" not in h.replace("<i class", "").replace("<i style", "")
          and 'class="pc now"' in h and " sel\"" not in h and '<b class="td">' in h
          and f'id="dc-pd-p1-{tidx}" hidden>' in h and h.count('class="pday"') == h.count('" hidden>')
          and "onclick=\"var w=this.parentNode" in h and "Cardio quiz" in h and "plansite:p1" in h and "Month &#8599;" in h
          and "planweek:p1:next" in h and "planweek:p1:prev" in h and 'class="tb here"' in h)
    seen_day = board._plan_card_html(dict(base, focus=week[tidx + 1]["day"]))
    check("week: Show on my plan's day opens, the box on it", f'id="dc-pd-p1-{tidx + 1}">' in seen_day
          and seen_day.count(" sel\"") == 1)
    check("week: a later day offers Open now, Skip it and Push my dates back",
          "plannow:p1:d" in h and "planskip:p1:d" in h and "planshift:p1" in h and "Push my dates back" in h and "Undo skip" in h)
    check("crew: in words", "Crew: 5 done with Path Book 1" in h)
    moved = board._plan_card_html(dict(base, week_offset=1))
    check("week: moved, it says which, Today between the arrows, the details shut",
          "Week of 5 Oct" in moved and 'class="tb" onclick' in moved and "planweek:p1:0" in moved
          and " sel\"" not in moved and moved.count('class="pday"') == moved.count('" hidden>'))
    rest = board._plan_card_html(dict(base, session={"kind": "rest", "due": 212}))
    check("now: a rest day says no new cards", "Today is a rest day: reviews, and no new cards." in rest)
    taper = board._plan_card_html(dict(base, session={"kind": "taper", "due": 212}))
    check("now: so does the taper", "in its taper" in taper)
    behind = board._plan_card_html(dict(base, lines=[("behind", [("Path Book 1", True), (" was due Mon. 2 cards not seen yet.", False)])]))
    check("behind: said on the card, with Catch up (Push my dates back is in its menu)",
          'class="pn warn"' in behind and "<b>Path Book 1</b> was due Mon." in behind and "plancatch:p1" in behind)
    paused = board._plan_card_html(dict(base, paused=True, sub="paused until Mon 12 Oct", session=None))
    check("now: paused, with Resume now", "paused until Mon 12 Oct" in paused and "No new cards while it&rsquo;s paused." in paused
          and "planresume:p1" in paused)
    ins = board._plan_card_html(dict(base, ins={"n": 12, "did": 10, "name": "Cardio <quiz>", "day": "2026-10-09"}))
    check("now: the next exam's cards at risk, from Insights, with Study and the way there",
          "12 cards</a> Anki won&rsquo;t show you before <b>Cardio &lt;quiz&gt;</b> on Fri 9" in ins
          and "duecrew:insbrowse:10:h" in ins and "duecrew:insstudy:10:h" in ins and "duecrew:youins:10" in ins, ins)
    check("now: none at risk, no line", "insstudy" not in board._plan_card_html(dict(base, ins={"n": 0, "did": 10})))
    notes = board._plan_card_html(dict(base, waiting=16, put_off=["Path Book 2"], change=[("Dre moved a date", False)]))
    check("notes: one at a time, the most pressing first", notes.count('class="pn') == 1 and "planok:p1" in notes)
    plans = {"cards": [base], "offers": []}
    css = board.render({"entries": [], "labels": ["2026-10-07"], "tomorrow": "", "pending": []}, {"period": "today"}, 0,
                       plans=plans, you={"tab": "plans", "plans": plans})
    check("narrow: the week becomes a list", "#due-crew .pwk {{ grid-template-columns: 1fr; }}".replace("{{", "{").replace("}}", "}") in css)


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
    text = B.share_text(_bingo_card(), locked, "busm <b>")
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
          "names": {"sam": ("Sammy", "😺"), "dre": ("Dre <x>", "")}, "squad": "busm <b>", "squad_id": "sq1",
          "new": True, "closest": B.closest(card, ev), "withheld": ["days"], "today": "2026-09-01"}
    full = board.bingo_html(bv, {})
    check("bingo: the card escapes the server's words and names",
          "Early &lt;i&gt;" in full and "Picture &lt;b&gt;" in full and "busm &lt;b&gt;" in full and "Dre &lt;x&gt;" in full
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
    sv = {"state": "ok", "name": "busm", "rows": [], "people": 0, "day": "2026-09-01", "squads": [], "current": "sq1", "bingo": bv}
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
    conf = {"period": "squads", "squads": [{"id": sid, "code": squad["code"], "name": "busm"}]}
    copied, swaps = [], []
    saved = (dc._swap, dc.cfg, dc.save_cfg, dc._fetch_squad, dc.copy_text, dc._bingo_view, bingo_flow.seen)
    dc._swap = lambda c, focus=None: swaps.append(1)
    dc.cfg = lambda: conf
    dc.save_cfg = lambda c, **k: None
    dc._fetch_squad = lambda force=False: None
    dc.copy_text = copied.append
    card = B.clean_card(store.bingo_cards[wk])
    dc._bingo_view = lambda c: {"card": card, "ev": B.evaluate(card, []), "squad": "busm"}
    bingo_flow.seen = lambda: None
    try:
        send = lambda m: dc._on_js(False, "duecrew:" + m, DeckBrowser())
        send("bingo")
        opened = dc._state.get("bingo_open")
        send("bingocopy")
        send("bingoback")
        back = dc._state.get("bingo_open")
        send("bingo")
        send("period:today")
        check("bingo: Open, Copy and back reach their handlers; another tab closes the card",
              opened is True and back is False and dc._state.get("bingo_open") is False
              and copied and copied[0].startswith("busm · squad bingo") and len(swaps) >= 4, (opened, back, copied))
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
    pick = lambda h: _re.search(r'<div class="dc-sw">(.*?)</div>', h).group(1)
    check("crew: the picker, Today picked, then Week picked",
          '<a class="on" href="#" onclick="pycmd(\'duecrew:period:today\'); return false;">Today</a>' in pick(today)
          and '<a href="#" onclick="pycmd(\'duecrew:period:week\'); return false;">Week</a>' in pick(today)
          and '<a href="#" onclick="pycmd(\'duecrew:period:decks\'); return false;">Decks</a>' in pick(today)
          and '<a class="on" href="#" onclick="pycmd(\'duecrew:period:week\'); return false;">Week</a>' in pick(week))
    sq = board.render(data, {"period": "squads", "crew_view": "decks"}, 0)
    check("crew: from Squads, the Crew pill goes back to the last view picked (Decks too, since 3.8.0)",
          ("decks", "Crew") in pills(sq) and "period:today'); return false;\">Today</a>" not in sq)
    decks = board.render(data, {"period": "decks", "crew_view": "decks"}, 0)
    check("crew: Decks is Crew's third view, picked", ("decks", "Crew") in pills(decks)
          and '<a class="on" href="#" onclick="pycmd(\'duecrew:period:decks\'); return false;">Decks</a>' in pick(decks))
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
          and '<a class="on" href="#" onclick="pycmd(\'duecrew:period:today\'); return false;">This week</a>' in pick(mode)
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
        dc._on_js(False, "duecrew:period:week", DeckBrowser())
        week_set = (conf.get("period"), conf.get("crew_view"))
        dc._on_js(False, "duecrew:period:decks", DeckBrowser())
        decks_set = (conf.get("period"), conf.get("crew_view"))
        dc._on_js(False, "duecrew:period:squads", DeckBrowser())
        check("crew: the picker's click reaches its handler and is remembered; Squads keeps it",
              week_set == ("week", "week") and decks_set == ("decks", "decks")
              and conf.get("period") == "squads" and conf.get("crew_view") == "decks", (week_set, decks_set, conf))
        dc._on_js(False, "duecrew:period:plans", DeckBrowser())
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
          "<b>Video Series</b> &middot; <a class=\"tp\"" in th and "Kidney &lt;b&gt;</a>" in th and "<b>Kidney" not in th
          and "duecrew:plantopic:p1:u1:1" in th and "<b>Search</b> &middot; <a" in th and "Video Series</b> &middot; <a" in th
          and th.count("Video Series") == 1, th[:3000])
    up = board._due_html(dict(dv2, tab="upcoming"))
    check("simpler: Today ends with its list; tomorrow and the exam are Upcoming's, the exam escaped",
          "du-next" not in th and "Tomorrow:" not in th and "Quiz" not in th and "Upcoming &rsaquo;" not in th
          and "Heart" in up and "Quiz &lt;q&gt;" in up and "Quiz <q>" not in up)
    check("simpler: no Later tab while Later is empty; a saved Later falls back to Today",
          "duetab:later" not in th and "duetab:later" not in board._due_html(dict(dv2, tab="later"))
          and 'class="on" onclick="pycmd(\'duecrew:duetab:today\')' in board._due_html(dict(dv2, tab="later")))
    dv3 = DUE.view(lb0, dates, [{"id": "item01", "t": "Some day", "d": "", "done": False}], {}, tab="later")
    l3 = board._due_html(dv3)
    check("simpler: Later shows, with its count, once it holds something",
          ">Later 1</a>" in l3 and "Some day" in l3 and 'class="on" onclick="pycmd(\'duecrew:duetab:later\')' in l3, l3[:1500])
    check("refined: Behind is Today's alone", "du-sec warn" in th and "du-sec warn" not in up and "Old" not in up)
    bh = board.render(dict(data, pending=["Jules"]), {"period": "today"}, 0, due=dv2, plans=plans, you={"tab": "today", "plans": plans})
    check("refined: the box's tabs are words, Hide a word", 'class="du-tabs du-more"' in bh and "border: 1px solid var(--dc-line);\n"
          "      border-radius: 99px; padding: 2px 10px" not in bh and ">Hide &#9652;</a>" in bh)
    foot = bh.split('class="dc-foot"')[1]
    check("refined: one pill in the footer, I'm studying; Open a room and who's waiting are words",
          foot.count('class="pb') == 1 and ">Open a room</a>" in foot and 'class="warn"' in foot and "1 waiting" in foot)
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
        dc._on_js(False, "duecrew:duetab:plans", DeckBrowser())
        check("duetab: a tab's click picks it, opens the bubble, and shows a hidden one again",
              conf["due_tab"] == "plans" and conf["due_fold"] == {"day": labels[0], "folded": False}
              and conf["hidden_tabs"] == ["decks"], conf)
        dc._on_js(False, "duecrew:duetab:insights", DeckBrowser())
        check("duetab: Insights too", conf["due_tab"] == "insights")
        dc._on_js(False, "duecrew:duetab:squads", DeckBrowser())
        check("duetab: not a tab of the bubble, nothing", conf["due_tab"] == "insights")
        conf["due_show"] = False
        dc._on_js(False, "duecrew:duefold", DeckBrowser())
        check("duefold: Due off, Hide folds the bubble for today", conf["due_fold"] == {"day": labels[0], "folded": True})
        dc._on_js(False, "duecrew:duefold", DeckBrowser())
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
    check("settings: Shows, Crew always, then Decks, Squads, Plans and Insights, each a switch",
          '<button class="st-pill on" disabled aria-pressed="true">Crew</button>' in st
          and "settabs:plans:1" in st and "settabs:decks:0" in st and "settabs:squads:0" in st
          and "settabs:insights:0" in st and "Today, Upcoming, Later" in st)
    from due_crew import settings_model
    check("settings: the hideable tabs are the board's", set(settings_model.HIDEABLE) == {k for k, _l in board.HIDEABLE_TABS})
    # Crew › Decks: my own deck, to how it's sticking
    me = dict(data["entries"][0], decks=[{"name": "Step <1>", "sig": "s", "total": 10, "seen": 5, "mature": 2, "open": 6}])
    dk = board.render(dict(data, entries=[me]), {"period": "decks"}, 0, sticking={"Step <1>": 10})
    check("decks: my deck's way to Insights", "duecrew:youins:10" in dk and "How it&rsquo;s sticking &rsaquo;" in dk
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
           "settings": {"squads": [{"id": "sq1", "code": "ABCD2345", "name": "busm", "founder": "x"}],
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
    box = {"cfg": {"squads": [{"id": "sq1", "code": "ABCD2345", "name": "busm", "founder": "x"}]}}
    SQ.cfg = lambda: dict(box["cfg"])
    SQ.save_cfg = lambda c: box.update(cfg=c)
    _state["squads_left"] = {"sqLeft"}
    try:
        SQ.heal_squads([{"id": "sq1", "name": "busm", "founder": "x"}, {"id": "sq2", "name": "ms2", "founder": "y"},
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
    text = open(os.path.join(REPO, "due_crew", "__init__.py")).read()
    for fn, nxt, keys in (
            ("def _crew_menu", "def _share_menu", {k for _l, k in board.crew_menu_items()}),
            ("def _share_menu", "def open_friends",
             {k for show_up in (False, True) for _l, k in board.share_menu_items(show_up, True) if _l})):
        run = text[text.index(fn):text.index(nxt)]
        handled = set(re.findall(r'"([a-z]+)": lambda', run))
        check(f"{fn[4:]}: every key handled", keys <= handled, sorted(keys - handled))
    full = board.share_menu_items(False, True)
    check("share menu: as text, then as a picture, year and all time made here (3.8.0)",
          [l or k for l, k in full] == ["As text", "My day", "Our week", "The squad's day", "As a picture",
                                        "My day…", "My week…", "My year…", "All time…"]
          and "head.setEnabled(False)" in text
          and 'share_picture("picturealltime")' in text and 'share_picture("pictureyear")' in text)
    check("crew menu: people only",
          [k for _l, k in board.crew_menu_items()] == ["friends", "copyinvite", "decks"])
    import due_crew as dc
    import aqt.utils as au
    from aqt.deckbrowser import DeckBrowser
    if "aqt.reviewer" not in sys.modules:
        sys.modules["aqt.reviewer"] = types.SimpleNamespace(Reviewer=type("Reviewer", (), {}))
    got, saved, saved_link = [], dc._share_menu, getattr(au, "openLink", None)
    dc._share_menu = lambda c: got.append("share")
    au.openLink = lambda url: got.append(url)
    try:
        dc._on_js(False, "duecrew:sharemenu", DeckBrowser())
        dc._on_js(False, "duecrew:privacypage", DeckBrowser())
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
    st = board.settings_html({"tab": "board", "signed_in": True}, {})
    check("due settings: three switches on Board", all(f"duecrew:set:{k}:" in st for k in ("due_show", "due_suggest", "due_leeches")))
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
        send = lambda m: dc._on_js(False, "duecrew:" + m, DeckBrowser())
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
        dc._on_js(False, "duecrew:set:due_leeches:1", DeckBrowser())
        check("leeches: switched on, today's come back at once, and it says so",
              conf2.get("due_leeches") is True and said and said[-1].startswith("1 leech back as new cards"), (said, store))
        dc._on_js(False, "duecrew:set:due_leeches:1", DeckBrowser())
        check("leeches: on again changes nothing", len(said) == 1)
    finally:
        (dc.cfg, dc.save_cfg, F.cfg, F.mw.col, F.tooltip, F._today, F._pf) = saved2
        dc._state["settings_tab"] = None


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
    init_src = open(os.path.join(REPO, "due_crew", "__init__.py"), encoding="utf-8").read()
    check("cheers: the main thread's commit is what says they arrived (cheers_got from the reply's cheers_at)",
          'got = data.get("cheers_at") or 0' in init_src and 'cl.session["cheers_got"] = got' in init_src)
    check("ticks: the site hashes lines the same way (FNV-1a, code points)",
          "0x811c9dc5" in app_js and "0x01000193" in app_js and "codePointAt" in app_js
          and _re.search(r"ticks\[keys\[i\]\]", app_js))


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
    F._pf = lambda: types.SimpleNamespace(_state_cfg=lambda: {"p1": st}, followed=lambda: [plan], _deck_ok=lambda col, d: True)
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
          "plans_opened": {"day": "2026-10-05", "label": "Due Crew: open 2 dates",
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
            dc._on_js(False, "duecrew:planupdlater:" + pid, DeckBrowser())
            check("updates: Not today: nothing opens, tomorrow's morning will (still applied as it was)",
                  4 not in _open(col) and pid not in _state["plan_updates"]
                  and (g.state()["plans"][pid].get("later") or {}).get("ar") == _day(1)
                  and g.state()["plans"][pid]["applied"].get("ar"))
            g.state()["plans"][pid]["later"].pop("ar")
            F.maybe_morning(False, fresh=True, update=True)
            dc._on_js(False, "duecrew:planupdopen:" + pid, DeckBrowser())
            check("updates: Open opens what it adds, in one step", 4 in _open(col) and pid not in _state["plan_updates"])
            dc._on_js(False, "duecrew:planpostok:" + pid, DeckBrowser())
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
            dc._on_js(False, f"duecrew:plansub:{pid}:team", DeckBrowser())
            check("3.8.0: an older page's Team link, not in its squad: nothing happens, nothing's asked",
                  len(store.log) == n_log and (_state.get("plan_sub") or {}).get(pid) != "team" and not conf["cfg"].get("squad"))
            check("3.7.6: following alone shares nothing", not store.follows[(pid, "maya")]["share"]
                  and [b for m, pa, b in store.bodies if pa == "/plans/follow"][0].get("team") is False)
            dc._on_js(False, f"duecrew:planteamjoin:{pid}:ask", DeckBrowser())
            check("team: Join puts me on it", (pid, "maya") in store.team and pid in maya.session["teams"])
            ps = TF.plan_squads()
            check("3.8.0: its squad is a pill on the Squads tab at once, named for the plan",
                  [(q["id"], q["name"]) for q in ps] == [("plan:" + pid, "Step 1")], ps)
            check("3.8.0: with no squad of my own, it's the one the tab shows", TF.picked(conf["cfg"])["pid"] == pid)
            pline = board._plan_card_html(F.board_view({})["cards"][0])
            check("3.8.0: the plan card's line goes to it", f"duecrew:squadplan:{pid}" in pline and "Join its squad" not in pline)
            n_log = len(store.log)
            dc._on_js(False, f"duecrew:squadplan:{pid}", DeckBrowser())
            check("3.8.0: Open picks it on the Squads tab; what the join brought back is fresh, nothing's asked",
                  conf["cfg"].get("squad") == "plan:" + pid and conf["cfg"].get("period") == "squads"
                  and _state["team_view"][pid]["data"]["on"] and len(store.log) == n_log, (conf["cfg"], store.log[n_log:]))
            _state["team_view"].pop(pid)
            dc._on_js(False, f"duecrew:squadplan:{pid}", DeckBrowser())
            check("3.8.0: and fetches it when it isn't (one request)",
                  _state["team_view"][pid]["data"]["on"] and len(store.log) == n_log + 1, store.log[n_log:])
            sv = dc._squad_view_with_bingo(conf["cfg"])
            shtml = board._squads_html(sv, conf["cfg"])
            check("3.8.0: the Squads tab draws it: its pill on, who showed up, Ask the squad",
                  sv["kind"] == "plan" and "Showed up today" in shtml and "Ask the squad" in shtml
                  and f"<a class=\"on\" href=\"#\" title=\"Step 1\" onclick=\"pycmd('duecrew:squadplan:{pid}')" in shtml, shtml[:600])
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
            dc._on_js(False, f"duecrew:planteamno:{pid}", DeckBrowser())
            TF.client = lambda: maya
            check("3.7.6: No thanks ends the ask without a question, and shares nothing",
                  not store.follows[(pid, "kai")].get("teamAsk") and not store.follows[(pid, "kai")]["share"]
                  and (pid, "kai") not in store.team)
            kai.team_join(pid)
            kai.team_ask(pid, "Does Friday's quiz include complement?")
            dc._on_js(False, f"duecrew:planteamask:{pid}:" + quote("Same question: does it? <b>"), DeckBrowser())
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
            dc._on_js(False, f"duecrew:planteamleave:{pid}", DeckBrowser())
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
    check("load: today says what's to go, ahead what's new", "2 to go" in html and "2 new" in html, html[:500])
    check("load: one bar a day on top, to the week's scale, and a key", html.count('class="abar') == 2 and 'width:100%' in html
          and 'width:75%' in html and "new to you" in html and "busiest" not in html)
    check("load: a date ahead's details say what's new and what's seen before",
          "2 of 3 new &middot; 1 already seen or in your Anki" in html and "2 of 4 seen" in html)
    past = P.week_view({"units": [{"id": "a", "name": "A", "opens": "2026-10-07"}]}, {}, "2026-10-08", "2026-10-05", ld=ld)
    hp = board._week_html({"week": past, "week_offset": 0}, "pid1")
    check("load: a past date says behind, in the warm colour; 3.8.0: it opens those cards in Browse, not the day",
          '<span class="late"><a class="tp"' in hp and '2 behind</a></span>' in hp and 'abar late' in hp
          and "event.stopPropagation();pycmd('duecrew:planleft:pid1:a')" in hp, hp)


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
          T.source(["Big::#B&B::Basic_Pharmacology::General::Pharmacokinetics"]) == "B&B › General"
          and T.source(["Big::#Video_Series::Renal"]) == "Video Series" and T.source(["Renal"]) == "")
    topics = [("renal", "Renal", [], ["t:r"], []), ("thin", "Thin", [], ["t:t"], [])]
    of = {"t:r": set(range(1, 31)), "t:t": set(range(40, 50))}
    rows = T.not_sticking(topics, lambda t: of[t], set(range(1, 31)) | set(range(40, 50)), {1, 2, 3, 40, 41}, {3, 4, 5})
    check("not sticking: never right yet, plus forgot (not counted twice); a thin topic stays out",
          [(r["name"], r["of"], r["stuck"], r["forgot"], r["cids"]) for r in rows] == [("Renal", 30, 3, 2, [1, 2, 3, 4, 5])], rows)
    w = T.week([("d1", 40), ("d2", 60)], [("d3", 10, 60), ("d4", 0, 0)], 54, 9)
    check("week: minutes at my pace, the average ahead and before",
          w["ahead"][0] == ("d3", 18, 10, 60) and w["avg"] == 9 and w["was"] == 50, w)
    check("week: none without a measured pace or anything new ahead",
          T.week([], [("d", 5, 0)], None, 9) is None and T.week([], [("d", 0, 9)], 54, 9) is None)
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
            "week": {"past": [("2026-08-31", 40)], "ahead": [("2026-09-01", 120, 100, 50), ("2026-09-04", 200, 200, 30)],
                     "avg": 160, "was": 40, "today_done": 30, "src": "plan"},
            "fsrs": {"right": 85, "n": 486, "target": 90}, "leeches": 2}
    html = board._insights_html(10, view)
    check("insights: the board escapes the plan's words", "<img" not in html and "&lt;img" in html)
    check("insights: header, hero with Study, behind with Catch up (3.8.0: a deck's id in each command)",
          "<b>86%</b>" in html and "87% the 2 weeks before" in html and "3 cards</a> Anki won&rsquo;t show you before Fri" in html
          and "duecrew:insstudy:10:h" in html and "12 new cards behind" in html and "duecrew:plancatch:p1" in html, html[:900])
    check("insights: not sticking yet, one Study a row",
          "Not sticking yet" in html and "<b>10</b> of 27" in html and "duecrew:insstudy:10:0" in html and "Re-watch" not in html)
    check("insights: the week in time, today marked, the event named",
          "about 2 h 40 a day to Fri" in html and "the last 7 days: 40 min" in html and ">Today<" in html)
    check("insights: Optimize FSRS and Not now",
          "Newest cards 85% right, Anki aims for 90%" in html and "duecrew:insfsrs:10" in html
          and "duecrew:insfsrsno:10" in html)
    check("insights: 3.8.0, the deck's leeches, from the plan card, with See them",
          "2 suspended leeches &middot;" in html and "duecrew:insleeches:10" in html)
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
          and "duecrew:inshardno:10" in hh and "640 reviews in 4 weeks" in hh, hh)
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
          'class="tmt"' in deep and "duecrew:insmapup:10:0'); return false;\">All</a>" in deep
          and "duecrew:insmapup:10:1'); return false;\">&lt;b&gt;Cardio</a>" in deep and "<b>Valves</b> &middot; 20 cards, 70%" in deep
          and "duecrew:insmapall:10" in deep and ">Mitral<" in deep and ">Aortic<" in deep and ">Rhythm<" not in deep, deep)
    nw = board._ins_map(10, [dict(leaf("a", "Verbs", 40, 80), started=20), dict(leaf("b", "Nouns", 30, None), started=0)], "fsrs")
    check("map: none started yet reads new, with its swatch; a bar along the foot says how much is started",
          'class="tm sn"' in nw and "<b>new</b>" in nw and '<i class="sw sn"></i>new' in nw
          and '<i class="tmb" style="width:50%"></i>' in nw and "40 cards, 20 started, 80%" in nw
          and "30 cards, none started yet" in nw and '<i class="sw sn">' not in mh, nw)
    wy = board._ins_map(10, nest, "fsrs", (), [{"key": "a", "name": "Systems", "on": True}, {"key": "b", "name": "<Yield>", "on": False}])
    check("map: more than one way, a pick in the heading, the one on screen chosen, escaped",
          'aria-label="Split by"' in wy and "duecrew:insmapby:10:" in wy and '<option value="0" selected>Systems</option>' in wy
          and '<option value="1">&lt;Yield&gt;</option>' in wy and "by topic, now" not in wy
          and "Split by" not in board._ins_map(10, nest, "fsrs", (), [{"key": "a", "name": "Systems", "on": True}]), wy)
    check("map: one tile says nothing", board._ins_map(10, nest[:1], "fsrs") == ""
          and "right on their last review" in board._ins_map(10, nest, "right"))
    check("insights: nothing yet says so", "Insights fill in after a week of reviews." in board._insights_html(10, {"right": {"now": [1, 2]}}))
    ins = {"decks": [{"did": 10, "name": "Step 1", "full": "Step 1"}, {"did": 20, "name": bad, "full": bad}],
           "did": 10, "exam": False, "plan": {"id": "p1", "name": bad}, "view": view}
    yh = board._you_insights(ins)
    check("you › insights: the decks picked as a squad is, mine escaped",
          'class="dc-sw"' in yh and '<a class="on" href="#" title="Step 1" onclick="pycmd(\'duecrew:insdeck:10\')' in yh
          and "duecrew:insdeck:20" in yh and "<img" not in yh, yh[:600])
    check("you › insights: the deck's, plan or not: no way off to the plan, my exam date right here",
          "duecrew:duetab:plans" not in yh and 'aria-label="Exam date"' in yh and "<img" not in yh)
    lone = board._you_insights(dict(ins, decks=ins["decks"][:1], plan=None))
    check("you › insights: one deck, no picker; no plan, my exam date set right here",
          'class="dc-sw"' not in lone and 'aria-label="Exam date"' in lone and 'value=""' in lone
          and "duecrew:setexam:" in lone and "this.value||" in lone and "settings:privacy" not in lone)
    mine = board._you_insights(dict(ins, plan=None, exam="2026-11-30"))
    check("you › insights: my exam date shows in it, on every deck",
          'value="2026-11-30"' in mine and 'class="dc-sw"' in mine and "setexam" in yh
          and 'value=""' in board._you_insights(dict(ins, plan=None, exam='"><img x>')))
    check("you › insights: 3.8.0 (Sam), one deck still says its name; no date, Add exam date opens the picker",
          '<b class="ideck" title="Step 1">Step 1</b>' in lone and ">Add exam date</a>" in lone and "showPicker()" in lone
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
    fakes.add_card(conn, 700, did=10, ctype=2, queue=-1, tags="Step1::Renal leech")  # a leech Anki set aside
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
        F._filtered = lambda c, name, cids: built.append((name, sorted(cids))) or False
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
        wk = v.get("week") or {}
        check("glue: the week ahead in minutes: tomorrow's 20 new at my pace (54 s a new card), the plan's",
              [(d, n) for d, _m, n, _r in wk.get("ahead") or []][:2] == [(_day(0), 0), (_day(1), 20)]
              and wk["ahead"][1][1] == 19 and wk.get("src") == "plan", wk)
        check("glue: not behind; the plan named for its Catch up", v.get("behind") == 0 and v.get("pid") == "pI")
        check("glue: 3.8.0, the deck's suspended leeches", v.get("leeches") == 1, v.get("leeches"))
        dc._on_js(False, "duecrew:insstudy:10:h", DeckBrowser())
        dc._on_js(False, "duecrew:insstudy:10:0", DeckBrowser())
        check("glue: no date preps for the quiz: the whole plan, the box by the day", v["aim"]["scoped"] is False)
        check("glue: Study builds the hero's deck and a topic's", built == [("Due Crew::Before Fri 4", list(range(210, 220))),
              ("Due Crew::Renal", [200, 201, 202, 203, 204, 205, 206, 207, 210, 211, 212])], built)
        dc._on_js(False, "duecrew:insbrowse:10:h", DeckBrowser())
        dc._on_js(False, "duecrew:insbrowse:10:0", DeckBrowser())
        dc._on_js(False, "duecrew:insleeches:10", DeckBrowser())
        check("glue: 3.8.0, Browse: the box's cards; a topic's name, all of its cards (Study, the hard ones); See them, the leeches",
              shown == [list(range(210, 220)), list(range(200, 230)), [700]], shown)
        n = len(built) + len(shown)
        for cmd in ("insstudy:x:h", "insstudy:10:zz", "insbrowse:10:", "insdeck:", "youins:abc"):
            dc._on_js(False, "duecrew:" + cmd, DeckBrowser())
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
        dc._on_js(False, "duecrew:insstudy:10:h", DeckBrowser())
        check("glue: Renal preps for the quiz too: its weak cards, the deck by the event's name",
              v3.get("hero") == list(range(210, 220)) and built == [("Due Crew::Before Quiz", list(range(210, 220)))], built)
        # the same deck with no plan: my exam date, the deck's own tags, what Anki has due
        for i in range(12):
            fakes.add_card(conn, 600 + i, did=10, queue=0, tags="Step1::New")
        col.decks.config_dict_for_deck_id = lambda did: {"new": {"perDay": 5}, "desiredRetention": 0.9}
        w0 = TF.insights(10, None, _day(3))
        hero = set(w0.get("hero") or [])
        check("glue, no plan: my exam date aims the box over the whole deck",
              w0["aim"] == {"day": _day(3), "name": "Your exam", "in": 3, "scoped": False, "kind": "exam"}
              and set(range(210, 220)) <= hero and not hero & (set(range(200, 210)) | set(range(220, 230)) | set(range(500, 520))),
              (w0["aim"], sorted(hero)))
        check("glue, no plan: the deck's tags name the topics, the resource's part as the source",
              [(r["name"], r["src"], r["of"], r["stuck"], r["forgot"]) for r in w0.get("rows") or []]
              == [("Renal", "Videos › Kidney", 30, 8, 3)], w0.get("rows"))
        wk0 = w0.get("week") or {}
        check("glue, no plan: the week ahead is what Anki has due, its new cards a day; no behind",
              [n for _d, _m, n, _r in wk0.get("ahead") or []] == [5, 5, 2, 0, 0, 0, 0] and wk0.get("src") == "anki"
              and "behind" not in w0 and "pid" not in w0, wk0)
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
        dc._on_js(False, "duecrew:insdeck:20", DeckBrowser())
        check("picker: a deck's click picks it (this computer's)", conf.get("ins_deck") == 20)
        yv = TF.you_view(conf)
        check("you view: the deck picked, no plan on it", yv["did"] == 20 and not yv["view"].get("pid"))
        dc._on_js(False, "duecrew:insdeck:30", DeckBrowser())
        check("picker: a deck it doesn't list isn't picked", conf.get("ins_deck") == 20)
        conf.update(hidden_tabs=["insights", "decks"], due_tab="today")
        _state["labels"] = [_day(0)]
        dc._on_js(False, "duecrew:youins:30", DeckBrowser())
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
        dc._on_js(False, "duecrew:inshardno:10", DeckBrowser())
        check("glue: Not now puts the Hard habit away for a while", pc.get("ins_hard_hide") and not TF.insights(10, "pI").get("hard"))
        # 3.8.0: the topic map
        vp, vd = TF.insights(10, "pI"), TF.insights(10)
        check("map: the deck's cards in play by its own tags, plan or not, new ones too; all under one root, what's under it",
              [(t["name"], t["n"]) for t in vp.get("map") or []] == [("Started", 50), ("New", 12), ("Other", 10)]
              and vp.get("map_by") == "fsrs" and [t["name"] for t in vd.get("map") or []] == ["Started", "New", "Other"]
              and 0 <= vp["map"][0]["know"] <= 100 and vp["map"][1]["know"] is None, vp.get("map"))
        shown.clear()
        dc._on_js(False, "duecrew:insmap:10:2", DeckBrowser())
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
        dc._on_js(False, "duecrew:insmap:30:0", DeckBrowser())
        yv = TF.you_view(dict(conf, ins_deck=30))
        check("map: a tile that splits opens into its parts, the trail back above them",
              (_state.get("map_at") or {}).get(30) == ["cardio"] and yv["view"].get("map_at") == ["cardio"]
              and ">Rhythm<" in board._ins_map(30, m, "fsrs", yv["view"]["map_at"]), _state.get("map_at"))
        shown.clear()
        dc._on_js(False, "duecrew:insmap:30:0", DeckBrowser())
        dc._on_js(False, "duecrew:insmapall:30", DeckBrowser())
        check("map: inside, a part opens its cards; Browse all, the open subject's, new ones too",
              shown == [list(range(900, 920)) + [990], list(range(900, 940)) + [990]], shown)
        dc._on_js(False, "duecrew:insmapup:30:0", DeckBrowser())
        check("map: All goes back to the top", (_state.get("map_at") or {}).get(30) == [])
        ways = TF.insights(30).get("map_ways") or []
        check("map: its ways, the systems first, the yield tiers to pick", [(w["name"], w["on"]) for w in ways]
              == [("Sys", True), ("Yield", False)], ways)
        dc._on_js(False, "duecrew:insmap:30:0", DeckBrowser())
        dc._on_js(False, "duecrew:insmapby:30:1", DeckBrowser())
        yv = TF.you_view(dict(conf, ins_deck=30))
        check("map: picked by Yield, this deck's, kept on this computer; it starts from the top",
              (conf.get("ins_map_by") or {}).get("30") == ways[1]["key"] and sorted(t["name"] for t in yv["view"].get("map") or [])
              == ["High", "Low"] and not (_state.get("map_at") or {}).get(30), (conf.get("ins_map_by"), yv["view"].get("map")))
        dc._on_js(False, "duecrew:insmapby:30:9", DeckBrowser())
        check("map: no such way, nothing", (conf.get("ins_map_by") or {}).get("30") == ways[1]["key"])
        dc._on_js(False, "duecrew:insmapby:30:0", DeckBrowser())
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
            dc._on_js(False, "duecrew:insmapshare:30", DeckBrowser())
            check("share: the deck's map, its name and today, shown", made and made[0][:4] == ("Unused", _day(0), ["Cardio", "Pulm", "Renal"], "fsrs")
                  and made[-1] == "shown", made)
            check("share: no map a week old yet, no change", made[0][4] is None and made[0][5] == "")
            sys30 = ((pc.get("map_snaps") or {}).get("30") or {}).get("med::^sys") or []
            check("share: today's map kept for next week's change, by way, in this profile's plans file",
                  [x["day"] for x in sys30] == [_day(0)] and "med::$yield" in pc["map_snaps"]["30"], pc.get("map_snaps"))
            sys30[0]["day"] = _day(-8)
            _state["insights"].pop(30, None)
            TF.you_view(dict(conf, ins_deck=30))
            dc._on_js(False, "duecrew:insmapshare:30", DeckBrowser())
            check("share: a week on, the change since then; today's kept too", made[-2][4] and made[-2][5] == _day(-8)
                  and [x["day"] for x in pc["map_snaps"]["30"]["med::^sys"]] == [_day(-8), _day(0)], (made[-2], pc["map_snaps"]["30"]))
            dc._on_js(False, "duecrew:insmap:30:0", DeckBrowser())
            dc._on_js(False, "duecrew:insmapshare:30", DeckBrowser())
            check("share: opened, the parts on screen, named by the trail; the change is the deck's level only",
                  made[-2][0] == "Unused · Cardio" and made[-2][2] == ["Valves", "Rhythm"] and made[-2][4] is None
                  and made[-2][6] is True and made[0][6] is False, made[-2])
            dc._on_js(False, "duecrew:insmapup:30:0", DeckBrowser())
        finally:
            sys.modules.pop("due_crew.ui.map_card_dialog", None)
        dc._on_js(False, "duecrew:insmap:30:9", DeckBrowser())
        dc._on_js(False, "duecrew:insmapall:30", DeckBrowser())
        check("map: no such tile, or nothing open: nothing", len(shown) == 2 and not (_state.get("map_at") or {}).get(30))
        dc._on_js(False, "duecrew:insfsrsno:10", DeckBrowser())
        check("glue: Not now puts Optimize FSRS away, on every deck", pc.get("ins_fsrs_hide") and not TF.insights(10, "pI").get("fsrs")
              and not TF.insights(10).get("fsrs"))
        opened = []
        sys.modules["aqt.deckoptions"] = types.SimpleNamespace(display_options_for_deck_id=opened.append)
        dc._on_js(False, "duecrew:insfsrs:10", DeckBrowser())
        check("glue: Optimize FSRS opens the deck's options", opened == [10], opened)
        dc._on_js(False, "duecrew:setexam:2026-11-30", DeckBrowser())
        check("youins: the exam date set in Insights is my exam date, there too",
              conf.get("exam_date") == "2026-11-30" and TF.you_view(conf)["exam"] == "2026-11-30", conf.get("exam_date"))
        dc._on_js(False, "duecrew:setexam:off", DeckBrowser())
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
    col = types.SimpleNamespace(decks=Decks(), db=types.SimpleNamespace(scalar=lambda q, *a: cards.get(a[0], 0)))
    pc = {"built": [3, 2, 8, 77, "x"]}
    saved = (F._pcfg, F._psave)
    try:
        F._pcfg, F._psave = (lambda: pc), (lambda c: None)
        n = F.tidy_decks(col)
        check("tidy: one step, the empty ones of ours; the parent stays while a deck under it has cards",
              n == 3 and col.decks.removed == [[1, 3, 6]] and pc["built"] == [2, 8], (n, col.decks.removed, pc))
        cards[2] = 0
        n = F.tidy_decks(col)
        check("tidy: the last one under it studied, it goes with the parent, one step",
              n == 2 and col.decks.removed[1:] == [[2, 8]] and pc["built"] == [] and 8 not in col.decks.d, (n, col.decks.removed, pc))
        check("tidy: again, nothing to do", F.tidy_decks(col) == 0 and len(col.decks.removed) == 2)
        F._note_built(5)
        F._note_built(2)
        check("tidy: a deck built is remembered once, newest last", pc["built"] == [5, 2], pc)
    finally:
        F._pcfg, F._psave = saved


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
    init_src = open(os.path.join(REPO, "due_crew", "__init__.py"), encoding="utf-8").read()
    check("no jumps: _swap redraws through swap_js", "board.swap_js(html_out)" in init_src and "replaceChild" in js)
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
        init_src = open(os.path.join(REPO, "due_crew", "__init__.py"), encoding="utf-8").read()
        check("one settings: no Qt window left", "settings_dialog" not in init_src
              and not os.path.exists(os.path.join(REPO, "due_crew", "ui", "settings_dialog.py")))
        # the keys: listed, one switch, and it applies at once
        st = board.settings_html({"tab": "board", "signed_in": True}, conf)
        check("keys: Settings › Board lists both, with one switch", "Ctrl+Shift+S" in st and "Ctrl+Shift+Q" in st
              and "duecrew:set:shortcuts:0" in st)
        check("keys: the switch is a setting, on by default", SM.change(["set", "shortcuts", "0"], {}) == {"shortcuts": False}
              and SM.BOARD_DEFAULTS["shortcuts"] is True and "shortcuts" not in __import__("due_crew.account", fromlist=["x"]).ACCOUNT_KEYS)
        applied = []
        dc._apply_keys = lambda: applied.append(1)
        _state["settings_tab"] = "board"
        dc._on_js(False, "duecrew:set:shortcuts:0", DeckBrowser())
        check("keys: turning them off applies at once", conf.get("shortcuts") is False and applied == [1], (conf, applied))
        said = []
        TF.tooltip = lambda m, **k: said.append(m)
        mw.state = "deckBrowser"
        TF.ask_this_card()
        check("keys: Ctrl+Shift+Q off the review screen says what it's for", said and "reviewing" in said[0], said)
        # Study today: the walk's order
        check("study: the plans' decks first, in plan order", D.study_next([5, 3], {5: 0, 3: 4, 9: 40}, 12, False) == ("deck", 3))
        check("study: then the deck with the most due", D.study_next([5], {5: 0, 7: 3, 9: 40}, 12, False) == ("deck", 9))
        check("study: then today's misses, once", D.study_next([5], {5: 0, 9: 0}, 12, False) == ("misses", 12)
              and D.study_next([5], {5: 0}, 12, True) is None and D.study_next([], {}, 0, False) is None)
        # the walk, through Anki's screens
        sel = []
        F.tooltip = lambda m, **k: said.append(m)
        due = {"n": {3: 4, 9: 0}}
        counts = {"left": (0, 0, 0)}
        mw.col = types.SimpleNamespace(
            decks=types.SimpleNamespace(select=lambda d: sel.append(d), name=lambda d: f"Deck {d}", id_for_name=lambda n: 77),
            sched=types.SimpleNamespace(counts=lambda: counts["left"]))
        sv = (F._plan_decks, F._due_now, F._misses_today, F._reviews)
        F._plan_decks = lambda: [3]
        F._due_now = lambda col, dids: dict(due["n"])
        F._misses_today = lambda col: []
        F._reviews = lambda: {"back": 0, "at": ""}
        calls.clear()
        try:
            dc._on_js(False, "duecrew:duestudy", DeckBrowser())
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
        finally:
            F._plan_decks, F._due_now, F._misses_today, F._reviews = sv
            mw.col = None
        T0 = "2026-10-03"
        v = D.view(T0, [{"pid": "p", "uid": "u", "plan": "P", "name": "A", "opens": T0, "seen": 2, "total": 5}], [], {},
                   reviews={"due": 10, "done": 0})
        h = board._due_html(v)
        check("study: Today's head has Study today", "duecrew:duestudy" in h and "Study today &rsaquo;" in h)
        check("study: the folded line's Study is the same walk", "duecrew:duestudy" in board._due_html(dict(v, folded=True)))
        nothing = D.view(T0, [], [], {}, reviews={"due": 0, "done": 5})
        check("study: nothing to walk, no button", "duestudy" not in board._due_html(nothing))
        one = D.view(T0, [{"pid": "p", "uid": "u", "plan": "P", "name": "A", "opens": T0, "seen": 2, "total": 5},
                          {"pid": "p", "uid": "o", "plan": "P", "name": "Old", "opens": "2026-09-30", "seen": 0, "total": 4}], [], {},
                     reviews={"due": 10, "done": 0})
        oh = board._due_html(one)
        check("study: one Study in the box, Study today (no Study on a date or on Behind)",
              oh.count("Study") == 1 and "planstudy:" not in oh and "plancatch:p" in oh, oh[:2500])
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
    check("site audit: alone with nothing yet, no medal (the add-on)", "&#129351;" not in lone and "&mdash;" in lone)
    js = open(os.path.join(REPO, "site", "public", "app.js"), encoding="utf-8").read()
    css = open(os.path.join(REPO, "site", "public", "app.css"), encoding="utf-8").read()
    check("site audit: alone with nothing yet, no medal (the site, its twin)",
          "if (blank(r)) return tr(r, \"—\")" in js)
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
          and f"duecrew:duetodo:{keys[1]}'" in board._pycmd("duetodo:" + keys[1]), (keys, board._pycmd("duetodo:" + keys[1])))
    check("review: nothing that closes a quote rides", board._pycmd("x'y\"z<>;.") == "pycmd('duecrew:xyz.'); return false;")
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
    saved = (F._day_state, F.recover_leeches, F._put_day, F._today, getattr(dc_mw(), "state", None), dc_mw().col)
    try:
        st = {}
        F._day_state = lambda: ({}, st)
        F._put_day = lambda pc, s: None
        F.recover_leeches = lambda col: got.append("ran") or []
        F._today = lambda: T0
        dc_mw().col = object()
        dc_mw().state = "review"
        F.morning({"due_leeches": True})
        check("review: mid-review, the leeches wait (their undo step would sit on my answer)", got == [] and not st.get("leeches_done"))
        dc_mw().state = "deckBrowser"
        F.morning({"due_leeches": True})
        check("review: on the Decks screen, they're recovered", got == ["ran"] and st.get("leeches_done"))
    finally:
        F._day_state, F.recover_leeches, F._put_day, F._today, dc_mw().state, dc_mw().col = saved
    js = board.swap_js("<div id='due-crew'></div>")
    check("review: a half-typed to-do survives a redraw while it has focus; a sent one is cleared",
          "document.activeElement === din && din.value" in js and "n1.value = keep.v" in js
          and "inp.value = '';  // sent" in open(board.__file__, encoding="utf-8").read())
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
          corner + '<a class="on" href="#" onclick="pycmd(\'duecrew:period:today\'); return false;">Today</a>' in today
          and today.index(corner) > today.index("<table>") and "<th></th><th></th>" not in today
          and today.count('<div class="dc-sw">') == 1)
    week = board.render(data, {"period": "week"}, 0)
    check("head row B: Week too, Week picked", corner in week
          and '<a class="on" href="#" onclick="pycmd(\'duecrew:period:week\'); return false;">Week</a>' in week)
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
          line is not None and "period:decks'); return false;\">Decks</a>" in line.group(1)
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
    sq = {"state": "ok", "name": "<b>BUSM", "squads": [{"id": "x", "name": "<i>busm"}, {"id": "y", "name": "MS2"}],
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
          and "&lt;i&gt;busm" in html and "<i>busm" not in html and not html.startswith('<div class="dc-sw">'))
    check("head row B: the squad's headline, its week and its bingo card under the table, in that order",
          html.index("</table>") < html.index("2 in &lt;b&gt;BUSM &middot; 2 studying today &middot; 40 reviews together")
          < html.index("Last 7 days") < html.index("BINGO") < html.index("squadinvite"), html[-700:])
    check("head row B: show-up mode the same, its own headline", "dc-corner" in up
          and up.index("</table>") < up.index("2 in &lt;b&gt;BUSM &middot; 2 showed up today") and "&#128197; 7 days" in up)
    check("head row B: no table (nobody synced), the names stay on top",
          empty.startswith('<div class="dc-sw">') and "dc-corner" not in empty)
    for st in ("none", "loading", "error"):
        check(f"head row B: {st}, the names on top",
              board._squads_html({"state": st, "squads": [{"id": "x", "name": "x"}]}, {}).startswith('<div class="dc-sw">'))
    check("footer: Crew and Share without carets (Sam)",
          "duecrew:crewmenu'); return false;\">Crew</a>" in today and "duecrew:sharemenu'); return false;\">Share</a>" in today
          and "Crew &#9662;" not in today and "Share &#9662;" not in today)
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
    sq = {"state": "ok", "name": "<b>BUSM", "day": T0, "yesterday": "", "people": 3,
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
        send = lambda m: dc._on_js(False, "duecrew:" + m, DeckBrowser())
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
            "squads": ["busm <b>"], "decks": ["Private Deck"], "sync": "now", "tab": "board"}
    ix = board.settings_index(view, {})
    by = {x["l"]: x for x in ix}
    check("find: rows from all three tabs, each with where it lives",
          by["Accent"]["t"] == "board" and by["Accent"]["w"] == "Board \u203a How it looks"
          and by["\u2708\ufe0f Away"]["t"] == "privacy" and by["Sign out"]["t"] == "you" and len(ix) >= 30, sorted(by))
    words = lambda q: [x["l"] for x in ix if all((" " + x["k"]).find(" " + w) >= 0 for w in q.split())]  # noqa: E731
    check("find: by label, by a word it doesn't say (colour, holiday, test, log out), by its section",
          words("accent") == ["Accent"] and words("colour") == ["Accent"] and words("holiday") == ["\u2708\ufe0f Away"]
          and "\U0001f4d6 Exam" in words("test") and words("log out") == ["Sign out"] and "Study time" in words("study time"),
          (words("colour"), words("holiday"), words("test")))
    check("find: a switch is found whichever way it's set (its command without the state)",
          by["Study time"]["f"] == "set:share_time:" and by["Compact rows"]["f"] == "set:compact:")
    text = repr(ix)
    check("find: the person's name, status, squads and decks stay out of it",
          not any(x in text for x in ("Sammy", "secret", "busm", "Private Deck")), text[:300])
    page = board.settings_html(view, {})
    got = re.search(r'<input type="search" class="st-in" placeholder="Find a setting"[^>]*data-ix="([^"]*)"', page)
    check("find: the box sits in Settings' bar with its index, which reads back the same",
          got and json.loads(H.unescape(got.group(1))) == ix and 'oninput="dcFind.type(this)"' in page)
    js = board.FIND_JS
    check("find: what's found is written as text, never markup; another tab is asked for by a command the add-on has",
          "innerHTML" not in js and "textContent = h.l" in js and "pycmd('duecrew:settab:' + h.t)" in js
          and js in board.keep_me_in_view_js()
          and 'cmd == "settab"' in open(os.path.join(REPO, "due_crew", "__init__.py")).read())


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
    drawn = open(os.path.join(REPO, "due_crew", "board.py"), encoding="utf-8").read()
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
    for sel in ("th > a.on", ".dc-wrap", ".du-line", ".dc-room .fc > i", ".irow", ".tmap .tm", ".du-bh", ".du-go .nm"):
        check(f"motion 2: a rule for {sel}", f'sel: "{sel}"' in js)
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
    check("motion 2: Study today names the deck it opens first, escaped, open or folded; none, no name",
          'Study today &rsaquo; <span class="nm">&lt;Cardio&gt;</span>' in full and '<span class="nm">&lt;Cardio&gt;</span>' in one
          and 'class="nm"' not in board._due_html(v), full[:400])
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
    src = open(os.path.join(REPO, "due_crew", "__init__.py"), encoding="utf-8").read()
    check("arrive: both draws carry it", "board.keep_me_in_view_js() + _arrive_js()" in src
          and "board.swap_js(html_out) + board.keep_me_in_view_js() + _arrive_js()" in src)
    from due_crew import due_flow as F
    node = lambda did, n, kids=(): types.SimpleNamespace(deck_id=did, review_count=n, learn_count=0, new_count=0, children=list(kids))  # noqa: E731
    tree = types.SimpleNamespace(children=[node(1, 5, [node(11, 3)]), node(2, 40)])
    names = {1: "Big Step 1", 11: "Big Step 1::Cardio", 2: "Languages::Spanish"}
    saved = (F._plan_decks, dc_mw().col)
    try:
        dc_mw().col = types.SimpleNamespace(decks=types.SimpleNamespace(name=lambda d: names[d]))
        F._plan_decks = lambda: [11]
        a = F._next_deck(tree)
        F._plan_decks = lambda: []
        b = F._next_deck(tree)
        tree0 = types.SimpleNamespace(children=[node(1, 0), node(2, 0)])
        c = F._next_deck(tree0)
        check("study: the button names a plan's deck first (its last name), else the most due, else nothing",
              (a, b, c) == ("Cardio", "Spanish", ""), (a, b, c))
    finally:
        F._plan_decks, dc_mw().col = saved
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


def test_plan_tags_glue_v380():
    """3.8.0, plan tags in the add-on: Browse sends the picked notes' guids
    to the plan (owner or co-author) and tags them here; a follower's Anki
    takes them as soon as the plan's update is here (the morning, a mid-day
    update, a new follow), before what opens; the plan card says so once;
    Stop asks before taking them off; a plan gone takes them along."""
    import due_crew as dc
    from due_crew import plan_flow as F, plans as P, board
    from aqt.deckbrowser import DeckBrowser
    w = world({"dre": "Dre", "maya": "Maya", "kai": "Kai"})
    pid, _code = w.add_plan("dre", "MS2 Block 1", "Step 1", [])
    w.plans[pid]["editors"] = {"maya"}
    dre = new_client(w, "dre", "Dre")
    got, status = dre.tag_plan_notes(pid, "SLG 12", add=["guid000001", "guid000002"])
    check("tags: Browse's notes reach the plan by guid, the plan's part made from its name",
          status == 200 and got["doc"]["tagroot"] == "MS2_Block_1"
          and got["doc"]["tags"][0]["name"] == "SLG 12" and got["doc"]["tags"][0]["notes"] == ["guid000001", "guid000002"], str(got and got["doc"]))
    maya = new_client(w, "maya", "Maya")
    check("tags: a co-author tags too", maya.tag_plan_notes(pid, "SLG 13", add=["guid000003"])[1] == 200)
    kai = new_client(w, "kai", "Kai")
    check("tags: anyone else can't", kai.tag_plan_notes(pid, "SLG 12", add=["guid000009"])[1] == 403)
    check("tags: taken off, the last one takes the tag", maya.tag_plan_notes(pid, "slg 13", remove=["guid000003"])[0]["doc"]["tags"][0]["name"] == "SLG 12")
    # a follower's Anki: the morning, an update, a new follow
    col = _tag_col()
    plan = dict(w._plan_view(pid, "kai"), deck_id=10)
    from due_crew.backend import shapes
    plan = dict(shapes.clean_plan(plan), id=pid)
    pc = {"plans": {pid: {"deck_id": 10, "applied": {}}}}
    saved = (F._pcfg, F._psave, dc_mw().col, F._today, F.tooltip)
    said = []
    try:
        F._pcfg, F._psave = (lambda: pc), (lambda c: None)
        dc_mw().col = col
        F._today = lambda: TODAY.isoformat()
        F.tooltip = lambda msg, **k: said.append(msg)
        line = F.apply_tags([plan])
        st = pc["plans"][pid]
        check("tags: a follower's notes carry the plan's tag, remembered by its id, said once",
              st["tags"] == {plan["doc"]["tags"][0]["id"]: "DueCrew::MS2_Block_1::SLG_12"}
              and "DueCrew::MS2_Block_1::SLG_12" in _tags_of(col, 1) and line and "SLG 12" in line
              and st["tag_news"]["names"] == ["SLG 12"], str((st, line)))
        reads = []
        real_idx = P.DeckIndex
        P.DeckIndex = lambda *a, **k: reads.append(1) or real_idx(*a, **k)
        try:
            again = F.apply_tags([plan])
            edited = dict(plan, doc=dict(plan["doc"], tags=[dict(plan["doc"]["tags"][0], notes=["guid000001"])]))
            F.apply_tags([edited])
            F._today = lambda: (TODAY + datetime.timedelta(days=1)).isoformat()
            F.apply_tags([edited])
        finally:
            P.DeckIndex = real_idx
            F._today = lambda: TODAY.isoformat()
        check("tags: the deck is read again only when the plan's tags change, or the next Anki day",
              again is None and len(reads) == 2 and "DueCrew::MS2_Block_1::SLG_12" not in _tags_of(col, 2), str(reads))
        F.apply_tags([plan])
        view = F.card_view(plan, st, {}, TODAY.isoformat())
        html = board._plan_card_html(dict(view, tag_news=dict(view["tag_news"], names=["<SLG 12>"]), id=pid))
        check("tags: the plan card says it the day it happens, escaped, with Browse them and OK",
              "New tags: <b>&lt;SLG 12&gt;</b>" in html and f"duecrew:plantags:{pid}" in html and f"duecrew:plantagsok:{pid}" in html, html[:300])
        opened = []
        before = F.tags_seen
        F.tags_seen = lambda p, swap=True: opened.append(("seen", p))
        try:
            dc._on_js(False, f"duecrew:plantagsok:{pid}", DeckBrowser())
        finally:
            F.tags_seen = before
        check("tags: the card's OK reaches its handler", opened == [("seen", pid)], str(opened))
        F.tags_seen(pid, swap=False)
        check("tags: OK clears the line", "tag_news" not in pc["plans"][pid])
        src = open(os.path.join(REPO, "due_crew", "plan_flow.py"), encoding="utf-8").read()
        morning = src[src.index("def maybe_morning"):src.index("def _morning_waits")]
        check("tags: the morning tags before what opens, after the sync and on Decks",
              morning.index("apply_tags(plan_list, toast=False)") < morning.index("_open_now([p for p in plan_list if not p.get(\"paused\")]")
              and morning.index("if awaiting_sync or") < morning.index("apply_tags(plan_list") and morning.index("if not here:") < morning.index("apply_tags(plan_list"))
        mid = src[src.index("def midday"):src.index("def hold_new")]
        check("tags: an update later in the day tags at once (on Decks), before what it opens",
              mid.index('if getattr(mw, "state", "") != "deckBrowser"') < mid.index("apply_tags(plan_list") < mid.index("dry = run("))
        fol = src[src.index("def on_followed"):src.index("def open_make")]
        check("tags: a new follow tags before its first dates open", fol.index("apply_tags([fresh])") < fol.index("res = _open_now([fresh]"))
        check("tags: a plan gone takes its tags off (and waits for Decks to)",
              '_drop_plan_tags(was, "a plan you followed")' in morning and '.get("tags") for pid in gone)' in morning)
        stop = src[src.index("def stop_following"):src.index("# ---- following ----")]
        check("tags: Stop asks with a box to tick before taking them off", "confirm_check(" in stop and "if untag:" in stop)
        n = F._drop_plan_tags(pc["plans"][pid], "MS2 Block 1")
        check("tags: taking them off on Stop", n == 2 and not any(t.startswith("DueCrew") for t in _tags_of(col, 1)))
        # Browse › tag for a plan: the sheet sends the guids; this Anki tags them at once, and a plan
        # I follow myself doesn't call the tag new when its update comes
        import types
        caught = {}

        class Sheet:
            def __init__(self, parent, cl, guids, on_done=None):
                caught.update(guids=guids, done=on_done)

            def exec(self):
                return 0
        was_mod, was_in = sys.modules.get("due_crew.ui.tag_dialog"), F._signed_in
        sys.modules["due_crew.ui.tag_dialog"] = types.SimpleNamespace(TagDialog=Sheet)
        F._signed_in = lambda: True
        try:
            class Browser:
                def selected_notes(self):
                    return [4, 5]
            F.tag_for_plan(Browser())
            g45 = caught["guids"]
            mine_plan, _st = dre.tag_plan_notes(pid, "SLG 15", add=g45)
            caught["done"](dict(mine_plan, id=pid), "SLG 15", "DueCrew::MS2_Block_1::SLG_15", g45, [])
            fresh = dict(shapes.clean_plan(dict(w._plan_view(pid, "kai"), deck_id=10)), id=pid)
            pc["plans"][pid].pop("tag_news", None)
            F.apply_tags([fresh])
            news = (pc["plans"][pid].get("tag_news") or {}).get("names") or []
            check("tags: Browse's notes carry the tag here at once, and my own update doesn't call it new",
                  len(g45) == 2 and all("DueCrew::MS2_Block_1::SLG_15" in _tags_of(col, n) for n in (4, 5))
                  and "SLG 15" not in news and any("as SLG 15" in x for x in said), str((news, said[-1:])))
        finally:
            F._signed_in = was_in
            if was_mod is None:
                sys.modules.pop("due_crew.ui.tag_dialog", None)
            else:
                sys.modules["due_crew.ui.tag_dialog"] = was_mod
    finally:
        F._pcfg, F._psave, dc_mw().col, F._today, F.tooltip = saved
    menu = open(os.path.join(REPO, "due_crew", "plan_flow.py"), encoding="utf-8").read()
    check("tags: Browse's menu has it, signed in", 'menu.addAction("Due Crew: tag for a plan…")' in menu
          and menu.index('if not client().signed_in') < menu.index('"Due Crew: tag for a plan…"'))


def test_why_not_showing_v380():
    """3.8.0, pick 9: Browse › why isn't it showing? (why, pure): one plain
    sentence a card, in Anki's words, and Anki's own fix beside it;
    alike cards together."""
    from due_crew import why as W
    rooms = {1: {"new": 0, "rev": 30, "new_limit": 20, "rev_limit": 200},
             2: {"new": 5, "rev": 0, "new_limit": 20, "rev_limit": 100},
             3: {"new": 0, "rev": 0, "new_limit": 0, "rev_limit": 0}}
    names = {1: "Anatomy", 2: "Pharm", 3: "Archive", 9: "Custom Study Session"}
    ranks = {}
    ctx = {"today": 500, "now": 1_000_000, "ahead": 1200, "deck": lambda d: names.get(d, "?"),
           "left": lambda d: rooms.get(d, {}), "rank": lambda c: ranks.get(c["id"], 1),
           "size": lambda d: 12, "day": lambda n: f"day {n}", "clock": lambda t: "15:40", "fsrs": True}
    card = lambda i, **kw: dict({"id": i, "did": 1, "odid": 0, "queue": 0, "due": 0, "lapses": 0, "leech": False}, **kw)  # noqa: E731
    r = lambda c: W.reason(c, ctx)  # noqa: E731
    check("why: suspended, and a leech says how often it was forgotten; both unsuspend",
          r(card(1, queue=-1))["say"] == "Suspended, so Anki never shows it." and r(card(1, queue=-1))["fix"] == ("unsuspend",)
          and r(card(2, queue=-1, leech=True, lapses=8))["say"] == "Suspended as a leech: forgotten 8 times.")
    check("why: buried by a sibling or by me, both shown today with Anki's unbury",
          "another card from its note" in r(card(1, queue=-2))["say"] and r(card(1, queue=-3))["say"] == "Buried by you till tomorrow."
          and r(card(1, queue=-3))["fix"] == ("unbury",))
    f = r(card(1, did=9, odid=1, queue=2, due=400))
    check("why: in a filtered deck, named, with how many go home if it's emptied",
          f["say"] == "In Custom Study Session, a filtered deck, not in Anatomy: it shows when you study Custom Study Session. "
          "Emptying it sends its 12 cards home." and f["fix"] == ("empty", 9), f)
    ranks[5] = 43
    n1 = r(card(5))
    check("why: new, past today's limit: the limit's done, and enough more to reach it",
          n1["say"] == "New: today's 20 new cards in Anatomy are done." and n1["fix"] == ("more_new", 1, 43), n1)
    ranks[6] = 9
    n2 = r(card(6, did=2))
    check("why: new, further in line than what's left: how far, and the difference",
          n2["say"] == "New: about 8 new cards come before it, and Pharm has 5 left today." and n2["fix"] == ("more_new", 2, 4), n2)
    ranks[7] = 3
    check("why: new and within today's: study the deck",
          r(card(7, did=2))["fix"] == ("study", 2) and "in today's new cards" in r(card(7, did=2))["say"])
    check("why: a deck that takes no new cards says so", r(card(8, did=3))["say"] == "New, and Archive takes no new cards a day.")
    check("why: learning, back at a time; nothing to do",
          r(card(1, queue=1, due=1_000_000 + 3600))["say"].startswith("Learning: back at 15:40.")
          and r(card(1, queue=1, due=1_000_000 + 3600))["fix"] is None
          and r(card(1, queue=1, due=1_000_000 + 600))["fix"] == ("study", 1))
    nd = r(card(1, queue=2, due=505))
    check("why: a review not due yet, by FSRS; Study it now sets its due date to today",
          nd["say"] == "Not due till day 505, by FSRS." and nd["fix"] == ("due_now",)
          and W.label(nd["fix"], 1, ctx) == "Study it now" and W.label(nd["fix"], 3, ctx) == "Study them now")
    rd = r(card(1, did=2, queue=2, due=499))
    check("why: due, but the day's reviews are done: more reviews today",
          rd["say"] == "Due, but today's 100 reviews in Pharm are done." and rd["fix"] == ("more_rev", 2, W.REV_MORE))
    check("why: due and within today's: study the deck", r(card(1, queue=2, due=500))["fix"] == ("study", 1))
    ranks.update({11: 30, 12: 50})
    gs = W.groups([card(10, queue=-1), card(11), card(12), card(13, queue=-1, leech=True), card(14, queue=-1),
                   card(15, queue=2, due=510), card(16, queue=2, due=503)], ctx)
    by = {g["group"]: g for g in gs}
    check("why: alike cards together, the most first, said by how many",
          gs[0]["group"] == "suspended" and by["suspended"]["say"] == "3 suspended, 1 of them as leeches."
          and by["suspended"]["label"] == "Unsuspend them" and by["suspended"]["cids"] == [10, 13, 14]
          and by["not_due"]["say"] == "2 not due yet, the soonest day 503.", [(g["group"], g["say"]) for g in gs])
    check("why: new cards past the limit get enough for the furthest in line",
          by["new:1"]["fix"] == ("more_new", 1, 50) and by["new:1"]["label"] == "50 more new today"
          and by["new:1"]["say"] == "2 new, past today's 20 new cards in Anatomy.", by["new:1"])
    one = W.groups([card(1, did=9, odid=1, queue=2)], ctx)
    check("why: one card says its own sentence; Empty names the deck", one[0]["say"].startswith("In Custom Study Session")
          and one[0]["label"] == "Empty Custom Study Session")


def test_why_not_showing_glue_v380():
    """3.8.0, pick 9: the glue reads the picked cards (a leech by its tag,
    the order kept), asks Anki's deck tree for each deck's room, and runs
    each fix as Anki's own operation, then reads again; Browse's menu has
    it signed in or not."""
    from due_crew import why_flow as WF, plan_flow as PF
    col = make_user_col([TODAY])
    conn = col.db.conn
    for cid, nid, q, due, tags in ((1, 1, -1, 0, " leech marked "), (2, 2, 0, 7, ""), (3, 3, 0, 3, ""), (4, 4, 2, 9999, "")):
        conn.execute("INSERT INTO notes (id, guid, tags) VALUES (?, ?, ?)", (nid, f"g{nid}", tags))
        conn.execute("INSERT INTO cards (id, nid, did, queue, due, lapses) VALUES (?, ?, 1, ?, ?, 4)", (cid, nid, q, due))
    got = WF.facts(col, [4, 1, 99, 2])
    check("glue: the picked cards in order, a leech by its tag, one not there left out",
          [c["id"] for c in got] == [4, 1, 2] and got[1]["leech"] and not got[0]["leech"] and got[1]["lapses"] == 4, got)
    node = types.SimpleNamespace(new_count=1, review_count=0)
    col.decks = types.SimpleNamespace(name=lambda d: "Big Step 1::Anatomy", find_deck_in_tree=lambda tree, d: node,
                                      config_dict_for_deck_id=lambda d: {"new": {"perDay": 20}, "rev": {"perDay": 200}},
                                      deck_and_child_ids=lambda d: [1])
    col.sched.deck_due_tree = lambda: "tree"
    ctx = WF.context(col)
    check("glue: a deck by its own name, its room today from Anki's tree, a new card's place in line",
          ctx["deck"](1) == "Anatomy" and ctx["left"](1) == {"new": 1, "rev": 0, "new_limit": 20, "rev_limit": 200}
          and ctx["rank"]({"id": 2, "did": 1, "due": 7}) == 2 and ctx["rank"]({"id": 3, "did": 1, "due": 3}) == 1)
    gs = WF.W.groups(WF.facts(col, [1, 2, 3]), ctx)
    check("glue: the leech, the new card past what's left, the one in today's",
          [g["group"] for g in gs] == ["new:1", "study:1", "suspended"] and gs[2]["say"] == "Suspended as a leech: forgotten 4 times.",
          [(g["group"], g["say"]) for g in gs])
    ran, shown = [], []
    saved = sys.modules.get("aqt.operations")

    class Op:
        def __init__(self, parent=None, op=None):
            self.op = op

        def success(self, f):
            self.f = f
            return self

        def run_in_background(self):
            ran.append(self.op(types.SimpleNamespace(sched=types.SimpleNamespace(
                unsuspend_cards=lambda ids: ("unsuspend", ids), unbury_cards=lambda ids: ("unbury", ids),
                set_due_date=lambda ids, d: ("due", ids, d), empty_filtered_deck=lambda d: ("empty", d),
                custom_study=lambda req: ("custom", req)))))
            self.f(None)
    sys.modules["aqt.operations"] = types.SimpleNamespace(CollectionOp=Op)
    sys.modules["anki.scheduler.base"] = types.SimpleNamespace(CustomStudyRequest=lambda **kw: kw)
    dlg = types.SimpleNamespace(show_groups=lambda gs: shown.append([g["group"] for g in gs]))
    saved_col = sys.modules["aqt"].mw.col
    sys.modules["aqt"].mw.col = col
    try:
        WF.fix({"fix": ("unsuspend",), "cids": [1]}, dlg, [1, 2])
        WF.fix({"fix": ("due_now",), "cids": [4]}, dlg, [4])
        WF.fix({"fix": ("more_new", 1, 6), "cids": [2]}, dlg, [2])
        WF.fix({"fix": ("more_rev", 1, 50), "cids": [4]}, dlg, [4])
        WF.fix({"fix": ("empty", 9), "cids": [4]}, dlg, [4])
        WF.fix({"fix": ("unbury",), "cids": [3]}, dlg, [3])
        check("glue: each fix is Anki's own (unsuspend, due today, more new or reviews today, empty, unbury), then a fresh read",
              ran == [("unsuspend", [1]), ("due", [4], "0"), ("custom", {"deck_id": 1, "new_limit_delta": 6}),
                      ("custom", {"deck_id": 1, "review_limit_delta": 50}), ("empty", 9), ("unbury", [3])] and len(shown) == 6, ran)
    finally:
        sys.modules["aqt"].mw.col = saved_col
        if saved is None:
            sys.modules.pop("aqt.operations", None)
        else:
            sys.modules["aqt.operations"] = saved
        sys.modules.pop("anki.scheduler.base", None)
    acts = []

    class Menu:
        def addSeparator(self):
            pass

        def addAction(self, label):
            acts.append(label)
            return types.SimpleNamespace(triggered=types.SimpleNamespace(connect=lambda f: None))
    saved_client = PF.client
    PF.client = lambda: types.SimpleNamespace(signed_in=False)
    try:
        PF.browser_menu(types.SimpleNamespace(), Menu())
    finally:
        PF.client = saved_client
    check("glue: Browse's right-click asks why, signed out too (Anki help, not the account)",
          acts == ["Due Crew: why isn't it showing?"], acts)


def test_card_set_links_one_look_v380():
    """3.8.0 (Sam: "the linked card sets appear differently on plan vs
    today/upcoming... pick one style and stick with it"): a link that
    opens a set of cards (a.tp) is the board's green everywhere, with no
    per-screen look of its own; Today writes a group as Plans does."""
    rules = re.findall(r"#due-crew[^{}]*a\.tp[^{}]*\{[^}]*\}", board._css({}))
    check("card-set links: one rule sets their colour, the green; none grey or dotted",
          rules and all("dotted" not in r and "inherit;" not in r.split("color:")[1][:12] for r in rules if "color:" in r)
          and sum(1 for r in rules if "color:" in r) == 1 and "var(--dc-accent)" in [r for r in rules if "color:" in r][0], rules)


def test_share_pictures_v380():
    """3.8.0: Share › As a picture, made in Anki (sharecard, pure): the
    site's cards (cards.js) from my own reviews: my week's squares and
    numbers, my year's calendar and best day, all time's bar a year; the
    switches, starting from my Privacy switches; what each card draws."""
    from due_crew import sharecard as S
    measure = lambda s, px, w: len(s) * px * 0.55  # noqa: E731
    texts = lambda ops: [o[1] for o in ops if o[0] == "text"]  # noqa: E731
    today = "2026-10-14"  # a Wednesday
    days = {"2026-10-12": (100, 30 * 60000), "2026-10-13": (40, 5 * 60000), "2026-10-14": (60, 20 * 60000),
            "2026-10-09": (10, 60000), "2025-03-03": (5, 60000), "2025-03-04": (7, 60000), "2025-03-05": (300, 90 * 60000),
            "2024-12-31": (2, 60000)}
    wk = S.week(days, today, False, {"2026-10-12": 3, "2026-10-14": 9, "2026-10-09": 50}, 4, 2)
    check("week: Monday to Sunday, the days so far studied, today ringed, tomorrow on",
          [c["label"] for c in wk["days"]] == list("MTWTFSS") and [c["studied"] for c in wk["days"]][:3] == [True] * 3
          and wk["days"][2]["today"] and [c["future"] for c in wk["days"]] == [False] * 3 + [True] * 4
          and wk["studied"] == 3 and wk["elapsed"] == 3, wk["days"])
    check("week: the numbers this week only, new cards too (last Friday's aren't in it)",
          wk["reviews"] == 200 and wk["time"] == 55 * 60000 and wk["newCards"] == 12 and wk["range"] == "12 Oct – 18 Oct"
          and wk["streak"] == 4 and wk["crew"] == 2, wk)
    one = S.week(days, today, True, {"2026-10-14": 9}, 4, 1)
    check("today: today's numbers, its day in the eyebrow",
          one["reviews"] == 60 and one["newCards"] == 9 and one["range"] == "Wed 14 Oct" and one["studied"] == 1, one)
    on = {k: True for k in ("time", "reviews", "streak", "crew", "best", "cheers")}
    W, H, ops = S.draw("week", "story", wk, on, "light", measure)
    t = texts(ops)
    check("week card: a story, the logo, time studied the big number, the reviews, new cards and streak under it",
          (W, H) == (1080, 1350) and ops[0] == ("logo", 78, 78, 40) and "MY WEEK · 12 OCT – 18 OCT" in t and "55m" in t
          and "200" in t and "12" in t and "🔥 4" in t and "with 2 crew this week" in t and "duecrew.com" in t
          and "studied, 3 of 3 days so far" in t, t)
    _w, _h, ops = S.draw("week", "story", wk, dict(on, time=False, streak=False, crew=False), "light", measure)
    t = texts(ops)
    check("week card: a switch off takes its number off the card",
          "55m" not in t and "200 reviews" in t and not any("🔥" in x for x in t) and not any(x.startswith("with ") for x in t), t)
    _w, _h, ops = S.draw("week", "story", wk, {}, "dark", measure)
    t = texts(ops)
    check("week card: every number off, the days studied are left", "3 days" in t and not any(x.isdigit() and x != "3" for x in t)
          and not any("reviews" in x or "new" in x for x in t), t)
    W, H, ops = S.draw("today", "link", one, on, "light", measure)
    t = texts(ops)
    check("today, a link: wide, the numbers on one line", (W, H) == (1200, 630) and "TODAY · WED 14 OCT" in t
          and "20m" in t and "60 reviews · 9 new · 🔥 4" in t and "with 1 crew today · duecrew.com" in t, t)
    big = S._Ops(measure, S.LOOKS["light"]).fit("123,456 reviews", 300, 150, 90, 700)
    check("a big number too wide shrinks, then ends in …", big[1] == 90 and big[0].endswith("…") and len(big[0]) < 15, big)

    yr = S.year(days, "2025", today, 7)
    first = S.year(days, "2024", today)
    check("year: the calendar year in Monday-first columns, days before my first review dashed",
          yr["cols"] == 53 and len(yr["cells"]) == 53 * 7 and yr["cells"][:2] == [{"out": True}] * 2
          and yr["cells"][2] == {"lvl": 0} and yr["since"] == "" and yr["studied"] == 3
          and first["cells"][0] == {"pre": True} and first["since"] == "31 Dec" and first["studied"] == 1,
          (yr["cells"][:3], first["cells"][:2], first["since"]))
    check("year: its streak, best day, reviews and cheers",
          yr["streak"] == 3 and yr["best"] == {"n": 300, "day": "5 Mar"} and yr["reviews"] == 312 and yr["cheers"] == 7, yr)
    now = S.year(days, "2026", today)
    check("year: this year's days to come are drawn faint; its first day isn't 'since'",
          now["cells"][-1] == {"out": True} and {"fut": True} in now["cells"] and now["since"] == "" and now["cheers"] is None)
    _w, _h, ops = S.draw("year", "link", yr, on, "light", measure)
    t = texts(ops)
    check("year card: story only, its eyebrow, days, the four numbers, my crew's cheers",
          (_w, _h) == (1080, 1350) and "MY YEAR IN ANKI · 2025" in t and "3 days" in t and "studied in 2025" in t
          and "312" in t and "2h" in t and "300" in t and "biggest day · 5 Mar" in t and "🎉 Cheered on 7 times by my crew" in t, t)
    al = S.alltime(days, today, 12)
    check("all time: a bar a year, the longest streak and its year, the best year",
          [r["days"] for r in al["years"]] == [1, 3, 4] and al["since"] == "Dec 2024" and al["streak"] == 3
          and al["streakYear"] == 2025 and al["bestYear"]["year"] == 2026 and al["days"] == 8 and al["cheers"] == 12, al)
    _w, _h, ops = S.draw("alltime", "story", al, dict(on, best=False), "dark", measure)
    t = texts(ops)
    check("all-time card: reviews big, a bar a year labelled, best year off",
          "524" in t and "’24" in t and "’26" in t and "longest streak · 2025" in t and not any("best year" in x for x in t), t)
    check("all time: nothing before my first review", S.alltime({}, today) is None)
    check("picker: the years I studied in and this one, newest first, then All time",
          S.year_options(days, today) == [("2026", "2026"), ("2025", "2025"), ("2024", "2024"), ("all", "All time")]
          and S.year_options({}, today) == [("2026", "2026"), ("all", "All time")])

    sw = {k: (note, start, en) for k, _l, note, start, en in S.switches("week", wk, S.privacy({"share_time": False}))}
    check("switches: a number my Privacy keeps home starts off, and says so; I can still turn it on",
          sw["time"] == ("off in Privacy", False, True) and sw["reviews"] == ("", True, True) and sw["crew"][1:] == (True, True), sw)
    sw = {k: (note, start, en) for k, _l, note, start, en in S.switches("today", dict(one, streak=0, crew=0), S.privacy({"show_up": True}))}
    check("switches: Just show up starts every number off; no streak or crew can't be on",
          not sw["time"][1] and not sw["reviews"][1] and sw["streak"] == ("none yet", False, False)
          and sw["crew"] == ("none yet today", False, False), sw)
    sw = {k: (note, start, en) for k, _l, note, start, en in S.switches("year", dict(yr, cheers=None), {}, "counting…")}
    check("switches: cheers wait for their count, then none yet or on",
          sw["cheers"] == ("counting…", False, False)
          and {k: v for k, _l, v, _s, _e in S.switches("year", dict(yr, cheers=0))}["cheers"] == "none yet"
          and [x for x in S.switches("year", yr) if x[0] == "cheers"][0][3:] == (True, True), sw)
    check("switches: all time over one year has no best year",
          [x for x in S.switches("alltime", dict(al, bestYear=None)) if x[0] == "best"][0][2:] == ("one year so far", False, False))


def test_share_pictures_glue_v380():
    """3.8.0: Share › As a picture opens the card made in Anki, not the
    website: my week from my reviews and my crew's days; my year with
    my crew's cheers counted with one request, after it opens."""
    from due_crew import shares as SH
    from due_crew.app import _state
    text = open(os.path.join(REPO, "due_crew", "__init__.py")).read()
    check("menu: every picture is made here, none opens the site",
          "/home?card=" not in text and all(f'share_picture("{k}")' in text
                                            for k in ("picturetoday", "pictureweek", "pictureyear", "picturealltime")))
    store = world({"sam": "Sam", "dre": "Dre"}, {"sam": ["dre"], "dre": ["sam"]})
    cl = new_client(store, "sam")
    d0 = datetime.date.today()
    col = make_user_col([d0 - datetime.timedelta(days=k) for k in (0, 1, 400)], today=d0)
    made, bg = [], []

    class Dlg:
        def __init__(self, parent, choose, options=None, value=None, priv=None, tooltip=None, cheers_say=""):
            self.choose, self.options, self.value, self.priv, self.cheers_say = choose, options, value, priv, cheers_say
            self.refreshed = 0
            made.append(self)

        def refresh(self):
            self.refreshed += 1

        def show(self):
            self.shown = True
    saved = (SH.client, SH._bg, SH.cfg, SH._profile_files, sys.modules["aqt"].mw.col, _state.get("entries"), _state.get("labels"))
    files = tempfile.mkdtemp()
    sys.modules["due_crew.ui.share_card_dialog"] = types.SimpleNamespace(ShareCardDialog=Dlg)
    try:
        SH.client, SH._bg, SH.cfg, SH._profile_files = (lambda: cl), (lambda job, done: bg.append((job, done))), \
            (lambda: {"share_reviews": False}), (lambda: files)
        sys.modules["aqt"].mw.col = col
        q = StatsQueries(col)
        labels = [q.day_label(i) for i in range(7)]
        _state["labels"] = labels
        _state["entries"] = [{"you": True, "days": {}}, {"you": False, "days": {labels[0]: {"studied": True}}},
                             {"you": False, "days": {labels[0]: {"studied": False}}}]
        _state.pop("pic_log", None)
        SH.picture("picturetoday")
        dlg = made[-1]
        card = dlg.choose(None)
        check("my day: today's card, my reviews, one of my crew studied too, Reviews starting off as Privacy keeps it",
              card["kind"] == "today" and card["data"]["reviews"] == 3 and card["data"]["crew"] == 1
              and dlg.priv == {"time": True, "reviews": False, "streak": True} and dlg.shown and not bg
              and _state["share_card"] is dlg, (card["data"], dlg.priv))
        SH.picture("pictureyear")
        dlg = made[-1]
        check("my year: this year first, the years I studied in, All time; cheers being counted",
              dlg.value == labels[0][:4] and dlg.options[-1] == ("all", "All time") and len(dlg.options) >= 2
              and dlg.cheers_say == "counting…" and dlg.choose(dlg.value)["data"]["cheers"] is None and len(bg) == 1)
        check("my year: the whole log was read once, the year before last's day in it",
              (d0 - datetime.timedelta(days=400)).isoformat() in _state["pic_log"]["days"])
        dre = new_client(store, "dre")
        dre.send_cheer("sam", "🎉")
        job, done = bg[-1]
        got = job()
        check("cheers: one read, mine by year", got == {str(datetime.date.today().year): 1}
              and store.requests("GET", "/log") and len(store.requests("GET", "/log")) == 1, got)
        done(got)
        check("cheers: in the card once counted, the sheet redrawn",
              dlg.refreshed == 1 and dlg.choose(str(datetime.date.today().year))["data"]["cheers"] == 1
              and dlg.choose("all")["data"]["cheers"] == 1)
        SH.picture("picturealltime")
        dlg2 = made[-1]
        bg[-1][1](None)
        check("all time: opens on All time; a count that failed says so", dlg2.value == "all"
              and dlg2.cheers_say == "couldn't count" and dlg2.choose("all")["data"]["cheers"] is None)
        app_gen = SH.app.generation
        SH.picture("pictureyear")
        SH.app.generation += 1
        bg[-1][1]({"2026": 5})
        check("cheers: a profile closed while counting draws nothing", made[-1].refreshed == 0)
        SH.app.generation = app_gen
        signed_out = types.SimpleNamespace(signed_in=False)
        SH.client = lambda: signed_out
        n = len(bg)
        SH.picture("pictureyear")
        check("signed out: no request, the switch says why", len(bg) == n and made[-1].cheers_say == "sign in to count")
    finally:
        (SH.client, SH._bg, SH.cfg, SH._profile_files, sys.modules["aqt"].mw.col, _state["entries"], _state["labels"]) = saved
        sys.modules.pop("due_crew.ui.share_card_dialog", None)
        _state.pop("share_card", None)
        _state.pop("pic_log", None)


def test_map_card_v380():
    """3.8.0: "What I know" as a picture card and as text (mapcard, pure):
    tiles laid out to fill the card, the board's shades, the foot; the
    text's squares; last week's map kept once a week, for the change."""
    from due_crew import mapcard as M
    rects = M.squarify([50, 30, 20], 0, 0, 100, 100)
    check("card: the tiles fill the space, sized by cards", abs(sum(w * h for _x, _y, w, h in rects) - 10000) < 1e-6
          and abs(rects[0][2] * rects[0][3] - 5000) < 1e-6 and all(0 <= x and 0 <= y and x + w <= 100.0001 and y + h <= 100.0001
                                                                   for x, y, w, h in rects), rects)
    tiles = [{"key": "cardio", "name": "Cardio", "n": 412, "know": 86, "started": 400},
             {"key": "renal", "name": "Renal", "n": 318, "know": 77, "started": 300},
             {"key": "neuro", "name": "Neuro", "n": 190, "know": 66, "started": 190},
             {"key": "msk", "name": "MSK", "n": 64, "know": 94, "started": 64},
             {"key": "heme", "name": "Heme", "n": 120, "know": None, "started": 0}]
    c = M.card("Big Step 1", "2026-10-12", tiles)
    check("card: the eyebrow, the deck, biggest first, shades as the board's, nothing started has no number",
          c["eyebrow"] == "WHAT I KNOW · 12 OCT" and c["title"] == "Big Step 1"
          and [(t["name"], t["k"], t["shade"]) for t in c["tiles"]] == [("Cardio", 86, 2), ("Renal", 77, 1), ("Neuro", 66, 0),
                                                                         ("Heme", None, None), ("MSK", 94, 3)], c["tiles"])
    check("card: inside the card, room left at the foot", all(M.PAD - 1 <= t["x"] and t["x"] + t["w"] <= M.SIZE - M.PAD + 1
                                                             and M.TOP - 1 <= t["y"] and t["y"] + t["h"] <= M.SIZE - M.FOOT + 1
                                                             for t in c["tiles"]), c["tiles"])
    check("card: the foot, over the started cards", c["foot"] == "80% I’d remember now · 1,104 cards", c["foot"])
    check("card: without FSRS it says so", "right on their last review" in M.card("D", "2026-10-12", tiles, by="right")["foot"])
    shape = M.card("Big Step 1", "2026-10-12", tiles, pct=False)
    check("card: Percentages off, no numbers anywhere, the shades in words", shape["foot"] == "" and shape["key"] is True)
    prev = {"cardio": 82, "renal": 79, "gone": 50}
    ch = M.card("Big Step 1", "2026-10-12", tiles, prev=prev, since="2026-10-05")
    check("card: this week's change on the tiles that were there, and at the foot",
          [(t["name"], t["d"]) for t in ch["tiles"]][:3] == [("Cardio", 4), ("Renal", -2), ("Neuro", None)]
          and ch["foot"] == "80% now · up 1 since 5 Oct", ch["foot"])
    tx = M.text("Big Step 1", "2026-10-12", tiles)
    check("card as text: a square and a line a subject, the foot, the add-on",
          tx.splitlines()[:6] == ["What I know · Big Step 1 · 12 Oct", "🟩 Cardio 86%", "🟨 Renal 77%", "🟧 Neuro 66%",
                                  "⬜ Heme new", "🟩 MSK 94%"] and "80% I’d remember now · 1,104 cards" in tx
          and tx.endswith("Anki add-on 2035408484"), tx)
    check("card as text: no numbers when they're off; the change when it's on",
          "🟩 Cardio\n" in M.text("D", "2026-10-12", tiles, pct=False) and "%" not in M.text("D", "2026-10-12", tiles, pct=False)
          and "🟩 Cardio 86% ↑4" in M.text("D", "2026-10-12", tiles, prev=prev, since="2026-10-05"))
    s1 = M.keep([], "2026-10-01", tiles)
    check("week: the first map kept", [x["day"] for x in s1] == ["2026-10-01"] and s1[0]["k"]["cardio"] == 86 and "heme" not in s1[0]["k"])
    check("week: not again inside the week", M.keep(s1, "2026-10-06", tiles) == s1)
    s2 = M.keep(s1, "2026-10-08", tiles)
    s3 = M.keep(M.keep(s2, "2026-10-15", tiles), "2026-10-22", tiles)
    check("week: a week on, another; three kept", [x["day"] for x in s2] == ["2026-10-01", "2026-10-08"]
          and [x["day"] for x in s3] == ["2026-10-08", "2026-10-15", "2026-10-22"], s3)
    w1 = M.keep_ways({}, "sys", "2026-10-01", tiles)
    w2 = M.keep_ways(M.keep_ways(w1, "yield", "2026-10-03", tiles), "sys", "2026-10-03", tiles)
    check("week: by way, so switching ways never pushes out a week", w2["sys"] == w1["sys"] and list(w2) == ["sys", "yield"], w2)
    many = {f"w{i}": [{"day": f"2026-09-0{i}", "k": {"a": 1}}] for i in range(1, 6)}
    check("week: four ways at most, the longest unseen go", sorted(M.keep_ways(many, "w1", "2026-10-03", tiles)) == ["w1", "w3", "w4", "w5"])
    check("week: the map a week ago or more, for the change", M.week_ago(s2, "2026-10-12") == (s2[0]["k"], "2026-10-01")
          and M.week_ago(s2, "2026-10-15")[1] == "2026-10-08" and M.week_ago(s2, "2026-10-05") == (None, "")
          and M.week_ago(None, "2026-10-15") == (None, ""))


def test_learning_back_flip_v380():
    """3.8.0: the box flips "4 back at 9:42" to due when they come back:
    one timer, the earliest, a redraw on the Decks screen; none after the
    profile closed."""
    import time as _t
    from due_crew import due_flow as F, app as A
    from due_crew.app import _state
    import aqt.qt as Q
    timers, swaps = [], []
    saved = (Q.QTimer, F._swap, F.mw.state, _state.get("back_timer"))
    Q.QTimer = type("QTimer", (), {"singleShot": staticmethod(lambda ms, fn: timers.append((ms, fn)))})
    F._swap = lambda c: swaps.append(1)
    try:
        _state["back_timer"] = None
        now = int(_t.time())
        F._flip_at(now + 600)
        F._flip_at(now + 900)
        check("flip: one timer, at the first card's time", len(timers) == 1 and 600000 <= timers[0][0] <= 604000, timers)
        F._flip_at(now + 300)
        check("flip: an earlier card moves it up", len(timers) == 2)
        _state["due_reviews"] = (now, {"due": 0})
        F.mw.state = "deckBrowser"
        timers[0][1]()
        check("flip: the old timer does nothing", swaps == [] and _state["due_reviews"] is not None)
        timers[1][1]()
        check("flip: the box counts again and redraws", swaps == [1] and _state["due_reviews"] is None and _state["back_timer"] is None)
        F._flip_at(now + 60)
        A.generation += 1
        timers[-1][1]()
        check("flip: not after the profile changed", swaps == [1])
    finally:
        Q.QTimer, F._swap, F.mw.state, _state["back_timer"] = saved


def test_heatmap_day_v380():
    """3.8.0: on my own card, a day I studied opens its cards in Browse;
    a friend's card has no clicks."""
    import due_crew as dc
    from due_crew import plan_flow as F
    from due_crew.app import _state
    from aqt.deckbrowser import DeckBrowser
    prof = {"name": "Sam", "you": True, "cells": [0, 3, 12], "start": "2026-09-28", "streak": 2, "last_active": ""}
    js = board.profile_overlay_js(prof)
    check("heat: my studied days open Browse; a day with none doesn't", "duecrew:heatday:2026-09-29" in js
          and "duecrew:heatday:2026-09-30" in js and "duecrew:heatday:2026-09-28" not in js and "12 reviews" in js)
    check("heat: a friend's card has no clicks", "heatday" not in board.profile_overlay_js(dict(prof, you=False)))
    conn = sqlite3.connect(":memory:")
    fakes.make_collection(conn)
    cut = fakes.day_cutoff_for(TODAY)
    for i, ago in enumerate((0, 1, 1, 2)):
        fakes.add_card(conn, 900 + i, did=10)
        fakes.add_review(conn, (cut - ago * 86400 - 3600) * 1000, ease=3, cid=900 + i)
    shown = []
    saved = (F._browse, dc.mw.col, _state.get("labels"))
    try:
        F._browse = lambda cids, q=None, empty="": shown.append(sorted(cids) if cids else empty)
        dc.mw.col = fakes.FakeCol(conn, cut)
        _state["labels"] = [TODAY.isoformat()]
        y = (TODAY - datetime.timedelta(days=1)).isoformat()
        dc._on_js(False, "duecrew:heatday:" + y, DeckBrowser())
        check("heat: that Anki day's answered cards, in Browse", shown == [[901, 902]], shown)
        dc._on_js(False, "duecrew:heatday:nope", DeckBrowser())
        dc._on_js(False, "duecrew:heatday:" + (TODAY + datetime.timedelta(days=3)).isoformat(), DeckBrowser())
        check("heat: not a day, or a day ahead: nothing", shown == [[901, 902]])
    finally:
        F._browse, dc.mw.col, _state["labels"] = saved


def main():
    names = [n for n in list(globals()) if n.startswith("test_")]
    for n in names:
        globals()[n]()
    bad = [c for c in CHECKS if not c[1]]
    print(f"\n{len(CHECKS) - len(bad)}/{len(CHECKS)} checks passed")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()

