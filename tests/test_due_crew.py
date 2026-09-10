"""End-to-end tests for Due Crew against fake anki + strict fake Firestore.

Run: python3 test_due_crew.py
"""

import datetime
import os
import re
import sqlite3
import sys
import tempfile

HARNESS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HARNESS)

import fakes

STORE = fakes.FakeFirestore()
fakes.install_fake_requests(STORE)
fakes.install_fake_aqt()
sys.path.insert(0, REPO)

from due_crew import board                                    # noqa: E402
from due_crew.backend import firebase                         # noqa: E402
from due_crew.stats import gather_stats                       # noqa: E402
from due_crew.stats.queries import StatsQueries               # noqa: E402

TODAY = datetime.date(2026, 9, 1)


def fv_str(s):
    return {"stringValue": s}


def seed_users(store, users, friends):
    for uid, name in users.items():
        store.docs[f"users/{uid}"] = {
            "displayName": fv_str(name),
            "friends": {"arrayValue": {"values": [fv_str(f) for f in friends[uid]]}},
        }


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
    tmp = tempfile.mkdtemp()
    cl = firebase.FirebaseClient(os.path.join(tmp, "session.json"))
    cl.session = {"user_id": uid, "id_token": "t-" + uid, "refresh_token": "r",
                  "display_name": name or uid.capitalize()}
    store.auth_uid = uid
    return cl


def sync_once(store, cl, col, files_dir, cfg, today):
    """What refresh_board's job does on sync, minus threading."""
    q = StatsQueries(col)
    labels = [q.day_label(i) for i in range(7)]
    stats = gather_stats(col, files_dir)
    cl.upload_today(cl.user_id, cl.display_name or "Me", labels[0], stats, cfg)
    if hasattr(firebase.FirebaseClient, "upload_backfill"):
        week = gather_week(col, files_dir)
        cl.upload_backfill(cl.user_id, week, cfg)
    heat = q.heatmap_counts(182)
    if cfg.get("share_heatmap", True) and not cfg.get("paused"):
        cl.upload_heatmap(cl.user_id, heat)
    elif not cl.session.get("heatmap_deleted"):
        cl.delete_heatmap(cl.user_id)
    return labels


def fetch_as(store, cl, col):
    q = StatsQueries(col)
    labels = [q.day_label(i) for i in range(7)]
    tomorrow = q.day_label(-1)
    return cl.fetch_board(cl.user_id, labels, tomorrow=tomorrow), labels, tomorrow


def showed_days(entry, labels):
    """How many of the 7 fetched days read as showed-up for this entry."""
    days = entry.get("days") or {}
    return sum(1 for lb in labels if board._showed(days.get(lb)))


try:
    from due_crew.stats import gather_week                    # noqa: E402
except ImportError:
    gather_week = None

CHECKS = []


def check(name, cond, detail=""):
    CHECKS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))


# ---------------------------------------------------------------- scenarios

def test_payload_shapes():
    """Client payloads are well-formed Firestore values (strict validation)."""
    store = fakes.FakeFirestore()
    sys.modules["requests"].Session = lambda: fakes.FakeSession(store)
    seed_users(store, {"sam": "Sammy"}, {"sam": []})
    cl = new_client(store, "sam", "Sammy")
    files = tempfile.mkdtemp()
    days = [TODAY - datetime.timedelta(days=i) for i in range(16)]
    col = make_user_col(days)
    cfg = {}
    sync_once(store, cl, col, files, cfg, TODAY)
    heat_ok = any(p.endswith("shared/heatmap") and s == 200 for m, p, s in store.log)
    daily_ok = any("daily_stats" in p and s == 200 for m, p, s in store.log)
    check("payloads: daily_stats PATCH accepted", daily_ok)
    check("payloads: heatmap PATCH accepted by strict validator", heat_ok)
    check("payloads: heatmap_hash recorded after success",
          bool(cl.session.get("heatmap_hash")))


def test_rules_drift_reproduces_live_state():
    """shared/decks-only rules -> decks hash set, heatmap hash never set."""
    store = fakes.FakeFirestore(rules_mode="decks-only")
    sys.modules["requests"].Session = lambda: fakes.FakeSession(store)
    seed_users(store, {"sam": "Sammy"}, {"sam": []})
    cl = new_client(store, "sam", "Sammy")
    ok_decks = cl.upload_shared("sam", [{"name": "X", "sig": ["a"], "total": 5,
                                         "seen": 1, "mature": 0}])
    ok_heat = cl.upload_heatmap("sam", {"2026-08-31": 12})
    check("drift: decks upload succeeds", ok_decks and cl.session.get("shared_hash"))
    check("drift: heatmap upload silently fails", not ok_heat)
    check("drift: heatmap_hash absent (matches live session.json)",
          not cl.session.get("heatmap_hash"))


def test_dots_gap():
    """Studies daily, syncs rarely -> server has holes; streak stays high.
    With backfill (fix), the holes fill on the next sync."""
    store = fakes.FakeFirestore()
    sys.modules["requests"].Session = lambda: fakes.FakeSession(store)
    seed_users(store, {"sam": "Sammy", "dre": "Dre"},
               {"sam": ["dre"], "dre": ["sam"]})
    files = tempfile.mkdtemp()
    cfg = {}
    cl = new_client(store, "sam", "Sammy")
    study_days = [TODAY - datetime.timedelta(days=i) for i in range(16)]

    # synced two days ago and today only (studied every day)
    for sync_day in (TODAY - datetime.timedelta(days=2), TODAY):
        store.auth_uid = "sam"
        col = make_user_col([d for d in study_days if d <= sync_day], today=sync_day)
        sync_once(store, cl, col, files, cfg, sync_day)

    # Dre (studied+synced today only) views the board
    dre = new_client(store, "dre", "Dre")
    dre_col = make_user_col([TODAY])
    data, labels, tomorrow = fetch_as(store, dre, dre_col)
    sam_entry = next(e for e in data["entries"] if e["user_id"] == "sam")
    filled = showed_days(sam_entry, labels)
    doc = sam_entry["days"].get(labels[0]) or {}
    streak_shown = doc.get("streak")
    fixed = hasattr(firebase.FirebaseClient, "upload_backfill")
    if fixed:
        check(f"backfill: full week on the server ({filled}/7, streak {streak_shown})",
              filled == 7 and streak_shown == 16)
    else:
        check(f"backfill: REPRO — streak {streak_shown} but only {filled}/7 days",
              filled < 7 and (streak_shown or 0) >= 14)
    return filled, streak_shown


def test_backfill_costs():
    """Second sync the same day must not re-PATCH unchanged past days."""
    if not hasattr(firebase.FirebaseClient, "upload_backfill"):
        return
    store = fakes.FakeFirestore()
    sys.modules["requests"].Session = lambda: fakes.FakeSession(store)
    seed_users(store, {"sam": "Sammy"}, {"sam": []})
    cl = new_client(store, "sam", "Sammy")
    files = tempfile.mkdtemp()
    col = make_user_col([TODAY - datetime.timedelta(days=i) for i in range(9)])
    cfg = {}
    sync_once(store, cl, col, files, cfg, TODAY)
    n_daily = lambda: sum(1 for m, p, s in store.log
                          if "daily_stats" in p and m == "PATCH")
    n0 = n_daily()
    sync_once(store, cl, col, files, cfg, TODAY)       # nothing changed
    unchanged = n_daily() - n0
    noon = datetime.datetime.combine(TODAY, datetime.time(13))
    fakes.add_review(col.db.conn, int(noon.timestamp() * 1000))
    n1 = n_daily()
    sync_once(store, cl, col, files, cfg, TODAY)       # one new review today
    after_review = n_daily() - n1
    check(f"backfill: no-change sync writes 0 daily docs (got {unchanged})",
          unchanged == 0)
    check(f"backfill: new-review sync writes exactly today (got {after_review})",
          after_review == 1)


def test_studied_field_privacy():
    """All share_* off: no numbers reach the server, dots still work."""
    if not hasattr(firebase.FirebaseClient, "upload_backfill"):
        return
    store = fakes.FakeFirestore()
    sys.modules["requests"].Session = lambda: fakes.FakeSession(store)
    seed_users(store, {"sam": "Sammy", "dre": "Dre"},
               {"sam": ["dre"], "dre": ["sam"]})
    cl = new_client(store, "sam", "Sammy")
    files = tempfile.mkdtemp()
    col = make_user_col([TODAY - datetime.timedelta(days=i) for i in (0, 1, 3)])
    cfg = {"share_reviews": False, "share_time": False,
           "share_retention": False, "share_streak": False}
    sync_once(store, cl, col, files, cfg, TODAY)
    today_label = StatsQueries(col).day_label(0)
    doc = store.docs.get(f"users/sam/daily_stats/{today_label}", {})
    leaked = {k for k in doc if k in ("reviews", "studyTimeMs", "accuracy", "streak")}
    dre = new_client(store, "dre", "Dre")
    dre_col = make_user_col([TODAY])
    data, labels, tomorrow = fetch_as(store, dre, dre_col)
    sam_entry = next(e for e in data["entries"] if e["user_id"] == "sam")
    filled = showed_days(sam_entry, labels)
    check("privacy: no numeric fields uploaded when shares off", not leaked, str(leaked))
    check(f"privacy: studied flag still marks showed-up days ({filled}/7)", filled == 3)


def test_heatmap_roundtrip():
    store = fakes.FakeFirestore()
    sys.modules["requests"].Session = lambda: fakes.FakeSession(store)
    seed_users(store, {"sam": "Sammy", "dre": "Dre"},
               {"sam": ["dre"], "dre": ["sam"]})
    cl = new_client(store, "sam", "Sammy")
    counts = {(TODAY - datetime.timedelta(days=i)).isoformat(): i * 3 for i in range(60)}
    ok = cl.upload_heatmap("sam", counts)
    store.auth_uid = "dre"
    dre = new_client(store, "dre", "Dre")
    got = dre.fetch_heatmap("sam")
    check("heatmap: friend roundtrip preserves counts",
          ok and got == {k: int(v) for k, v in counts.items()})


def test_heatmap_retraction():
    """Share off deletes the doc once; share back on re-uploads."""
    store = fakes.FakeFirestore()
    sys.modules["requests"].Session = lambda: fakes.FakeSession(store)
    seed_users(store, {"sam": "Sammy"}, {"sam": []})
    cl = new_client(store, "sam", "Sammy")
    files = tempfile.mkdtemp()
    col = make_user_col([TODAY])
    sync_once(store, cl, col, files, {}, TODAY)
    doc_path = "users/sam/shared/heatmap"
    was_up = doc_path in store.docs
    off = {"share_heatmap": False}
    sync_once(store, cl, col, files, off, TODAY)
    gone = doc_path not in store.docs
    n0 = sum(1 for m, p, s in store.log if m == "DELETE" and p == doc_path)
    sync_once(store, cl, col, files, off, TODAY)
    n1 = sum(1 for m, p, s in store.log if m == "DELETE" and p == doc_path)
    sync_once(store, cl, col, files, {}, TODAY)
    back = doc_path in store.docs
    check("retract: heatmap uploaded, deleted once on share-off, restored on share-on",
          was_up and gone and n0 == 1 and n1 == 1 and back)


def test_rules_probe():
    """Marker probe: current rules -> fine; drifted -> stale; 403 hint."""
    store = fakes.FakeFirestore()
    sys.modules["requests"].Session = lambda: fakes.FakeSession(store)
    seed_users(store, {"sam": "Sammy"}, {"sam": []})
    cl = new_client(store, "sam", "Sammy")
    ok_state = cl.check_rules("2026-09-01")
    drifted = fakes.FakeFirestore(rules_mode="decks-only")
    sys.modules["requests"].Session = lambda: fakes.FakeSession(drifted)
    seed_users(drifted, {"sam": "Sammy"}, {"sam": []})
    cl2 = new_client(drifted, "sam", "Sammy")
    stale_state = cl2.check_rules("2026-09-01")
    cl3 = new_client(drifted, "sam", "Sammy")
    cl3.upload_heatmap("sam", {"2026-08-31": 3})  # rejected write -> hint
    check("rules: probe says current on repo rules", ok_state is False)
    check("rules: probe says stale on drifted rules", stale_state is True)
    check("rules: rejected write flips the flag instantly", cl3.rules_stale)


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
    import due_crew
    tmp = tempfile.mkdtemp()
    due_crew._profile_files = lambda: tmp
    due_crew._wrap["profile"] = None
    due_crew._wrap["data"] = {}
    return due_crew


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
    check("exam eve: banner renders, name escaped, cheer wired",
          "exam is tomorrow" in html and "Priya &lt;x&gt;" in html
          and "cheerpick:p1" in html and "evedismiss" in html)
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
    check("accents: overlays read --dc-accent instead of hard-coding green",
          "--dc-accent" in js and "--dc-accent-ink" in js
          and "duecrew:cheerpick" in js)

def _render(data, labels, tomorrow, period):
    return board.render({"entries": data["entries"], "labels": labels,
                         "tomorrow": tomorrow, "pending": [], "decks": {},
                         "my_friends": []}, {"period": period}, 0)


def test_cheer_notes():
    """v2.2: a cheer may carry a note (rules-v5); the fake caps it like the
    rules; on older rules the cheer still lands, without the note."""
    store = fakes.FakeFirestore()
    sys.modules["requests"].Session = lambda: fakes.FakeSession(store)
    seed_users(store, {"sam": "Sammy", "dre": "Dre"}, {"sam": ["dre"], "dre": ["sam"]})
    dre = new_client(store, "dre", "Dre")
    fire = "\U0001F525"
    ok = dre.send_cheer("sam", "dre", "Dre", fire, "you're on fire  this\nweek")
    doc = store.docs.get("users/sam/cheers/dre") or {}
    check("cheer note: stored as one line", ok is True
          and doc.get("note") == fv_str("you're on fire this week"), str(doc))
    long = dre.send_cheer("sam", "dre", "Dre", fire, "x" * 200)
    check("cheer note: client trims to 80 before sending", long is True
          and len(store.docs["users/sam/cheers/dre"]["note"]["stringValue"]) == 80)
    bare = dre.send_cheer("sam", "dre", "Dre", "\U0001F389")
    check("cheer note: no note, no field", bare is True
          and "note" not in store.docs["users/sam/cheers/dre"])
    dre.send_cheer("sam", "dre", "Dre", "\U0001F4AA", "big day")
    sam = new_client(store, "sam", "Sammy")
    data, _labels, _t = fetch_as(store, sam, make_user_col([TODAY]))
    ch = (data["cheers"] or [{}])[0]
    check("cheer note: arrives with the cheer, name from the profile",
          ch.get("note") == "big day" and ch.get("name") == "Dre"
          and ch.get("emoji") == "\U0001F4AA", str(data["cheers"]))
    old = fakes.FakeFirestore(rules_mode="v3")
    sys.modules["requests"].Session = lambda: fakes.FakeSession(old)
    seed_users(old, {"sam": "Sammy", "dre": "Dre"}, {"sam": ["dre"], "dre": ["sam"]})
    dre_old = new_client(old, "dre", "Dre")
    res = dre_old.send_cheer("sam", "dre", "Dre", fire, "hello")
    check("cheer note: older rules -> cheer lands without the note, sender told",
          res == "no-note" and "note" not in old.docs["users/sam/cheers/dre"]
          and old.docs["users/sam/cheers/dre"]["emoji"] == fv_str(fire), str(res))
    js = board.flurry_js([fire], "Dre sent cheers", back=("dre", fire),
                         notes=["you're on fire <b>now</b>"])
    check("cheer note: flurry shows the note as text, longer linger",
          "you're on fire <b>now</b>" in js and "'\u201c' + notes[n]" in js
          and "notes.length ? 2500" in js)


def test_status_bubble():
    """v2.2: a one-line status rides today's doc (crew-only by the same
    rules as stats), shows as a bubble under the name on Today only, and
    clears when emptied."""
    store = fakes.FakeFirestore()
    sys.modules["requests"].Session = lambda: fakes.FakeSession(store)
    seed_users(store, {"sam": "Sammy", "dre": "Dre"}, {"sam": ["dre"], "dre": ["sam"]})
    col = make_user_col([TODAY])
    files = tempfile.mkdtemp()
    dre = new_client(store, "dre", "Dre")
    labels = sync_once(store, dre, col, files,
                       {"status": "coffee, then <b>400</b> cards\nnow"}, TODAY)
    doc = store.docs["users/dre/daily_stats/" + labels[0]]
    check("status: uploaded as one line",
          doc.get("status") == fv_str("coffee, then <b>400</b> cards now"), str(doc))
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
    store.auth_uid = "dre"  # the fake signs requests as the last client made
    sync_once(store, dre, col, files, {"status": ""}, TODAY)
    check("status: emptied -> removed server-side",
          "status" not in store.docs["users/dre/daily_stats/" + labels[0]])
    js = board.profile_overlay_js({"name": "Sammy", "you": True, "cells": None})
    check("status: own card offers to set one", "duecrew:status" in js and "Set a status" in js)
    js = board.profile_overlay_js({"name": "Dre", "you": False, "cells": None,
                                   "status": "hi <i>there</i>"})
    check("status: friend's card shows it escaped, no edit link",
          "hi &lt;i&gt;there&lt;/i&gt;" in js and "duecrew:status" not in js)
    junk = firebase._clean_day({"status": 5, "away": "yes", "awayTo": "soon"})
    good = firebase._clean_day({"status": "  hi\n there ", "away": True, "awayTo": "2026-09-04"})
    check("status/away: junk from the server is dropped",
          "status" not in junk and "away" not in junk
          and good == {"status": "hi there", "away": True, "awayTo": "2026-09-04"}, str((junk, good)))


def test_away_flag():
    """v2.2: away dates flag day docs (friend-gated like stats) — the
    coming days ahead of time, so the crew sees the plane while the person
    isn't syncing; shrinking or clearing unflags; week shares show planes
    and still count only studied days."""
    import due_crew
    from due_crew import share
    store = fakes.FakeFirestore()
    sys.modules["requests"].Session = lambda: fakes.FakeSession(store)
    seed_users(store, {"sam": "Sammy", "dre": "Dre"}, {"sam": ["dre"], "dre": ["sam"]})
    col = make_user_col([TODAY, TODAY - datetime.timedelta(days=2)])
    files = tempfile.mkdtemp()
    dre = new_client(store, "dre", "Dre")
    d = lambda n: (TODAY + datetime.timedelta(days=n)).isoformat()
    path = lambda n: f"users/dre/daily_stats/{d(n)}"
    on = {"booleanValue": True}
    sync_once(store, dre, col, files, {"away_from": d(-1), "away_to": d(3)}, TODAY)
    docs = store.docs
    check("away: today's doc carries the flag and the end date",
          docs[path(0)].get("away") == on and docs[path(0)].get("awayTo") == fv_str(d(3))
          and "reviews" in docs[path(0)], str(docs.get(path(0))))
    check("away: the coming days are flagged ahead of time, nothing beyond",
          all(docs.get(path(n), {}).get("away") == on for n in (1, 2, 3))
          and path(4) not in docs)
    check("away: yesterday (unstudied) flagged, no numbers invented",
          docs.get(path(-1), {}).get("away") == on and "reviews" not in docs.get(path(-1), {}))
    check("away: a studied day outside the spell is untouched",
          "away" not in docs[path(-2)] and "reviews" in docs[path(-2)])
    snapshot = {k: dict(v) for k, v in docs.items()}
    dre.sync_away("dre", d(0), {"away_from": d(-1), "away_to": d(3)})
    check("away: steady state changes nothing", snapshot == {k: dict(v) for k, v in docs.items()})
    sync_once(store, dre, col, files, {"away_from": d(-1), "away_to": d(1)}, TODAY)
    check("away: shrinking the spell drops the future docs it made",
          path(2) not in docs and path(3) not in docs
          and docs[path(1)].get("away") == on and docs[path(0)].get("awayTo") == fv_str(d(1)))
    sync_once(store, dre, col, files, {}, TODAY)
    check("away: clearing unflags everything (numbers stay)",
          path(1) not in docs and "away" not in docs[path(0)] and "reviews" in docs[path(0)]
          and "away" not in docs.get(path(-1), {}))
    sync_once(store, dre, col, files, {"away_from": d(0), "away_to": d(0)}, TODAY)
    sam = new_client(store, "sam", "Sammy")
    data, labels, tomorrow = fetch_as(store, sam, col)
    today_html = _render(data, labels, tomorrow, "today")
    check("away: Today row says when they're back",
          'class="awb"' in today_html and "back tomorrow" in today_html, today_html[-600:])
    doc3 = {"away": True, "awayTo": d(3)}
    check("away: badge names the return day",
          board._away_text(doc3, d(0)) == f"back {TODAY + datetime.timedelta(days=4):%b} {(TODAY + datetime.timedelta(days=4)).day}"
          and board._away_text({"away": True}, d(0)) == "away")
    check("away: day flags are three-state",
          due_crew._day_flag({"studied": True, "away": True}) is True
          and due_crew._day_flag({"away": True}) == "away"
          and due_crew._day_flag({}) is False and due_crew._day_flag(None) is False)
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
    store = fakes.FakeFirestore()
    sys.modules["requests"].Session = lambda: fakes.FakeSession(store)
    seed_users(store, {"sam": "Sammy", "dre": "Dre", "eve": "Eve", "zed": "Zed"},
               {"sam": [], "dre": [], "eve": [], "zed": []})
    sam = new_client(store, "sam", "Sammy")
    squad = sam.create_squad("sam", "  busm  <b> ", "Sammy")
    return store, sam, squad


def _denied(fn):
    try:
        fn()
        return False
    except firebase.TransportError:
        return True


def test_squads():
    """The door: create, peek, join while open, lock, remove, leave. The
    board: members read every row (with retention), nobody else does."""
    store, sam, squad = _squad_fixture()
    sid = squad["id"]
    check("squad: create makes the doc and the founder's member row",
          bool(squad) and squad["name"] == "busm <b>"
          and f"squads/{sid}" in store.docs
          and f"squads/{sid}/members/sam" in store.docs, str(squad))
    check("squad: code is 8 safe chars; any spelling of it derives the id",
          len(squad["code"]) == 8
          and all(ch in firebase.SQUAD_ALPHABET for ch in squad["code"])
          and firebase.squad_id(squad["code"].lower() + "--") == sid)
    check("squad: squads cannot be listed",
          sam._req("GET", f"{sam.base}/squads?pageSize=50").status_code == 403)
    dre = new_client(store, "dre", "Dre")
    info, status = dre.peek_squad(squad["code"])
    check("squad: peek shows name, founder, open",
          bool(info) and info["name"] == "busm <b>" and info["founder"] == "sam"
          and info["open"], str((info, status)))
    check("squad: unknown code is a 404, not an error",
          dre.peek_squad("ZZZZZZZZ") == (None, 404))
    check("squad: join while open", dre.join_squad("dre", sid, "Dre") in (200, 201))
    eve = new_client(store, "eve", "Eve")
    check("squad: non-member cannot read the board",
          _denied(lambda: eve.fetch_squad(sid)))
    day = TODAY.isoformat()
    row = {"name": "Dre", "reviews": 812, "studyTimeMs": 7440000,
           "accuracy": 91.25, "streak": 41}
    store.auth_uid = "dre"
    before = sum(1 for m, pth, st in store.log
                 if pth == f"squads/{sid}/members/dre" and m == "PATCH")
    gone = dre.upload_squad_rows("dre", dict(row, day=day), [sid])
    dre.upload_squad_rows("dre", dict(row, day=day), [sid])
    after = sum(1 for m, pth, st in store.log
                if pth == f"squads/{sid}/members/dre" and m == "PATCH")
    check("squad: row upserts once, hash skips repeats", gone == [] and after - before == 1)
    check("squad: extra fields rejected by rules",
          dre._patch_status(f"squads/{sid}/members/dre", {"name": "Dre", "server": "x"}) == 403)
    check("squad: negative reviews rejected",
          dre._patch_status(f"squads/{sid}/members/dre", {"name": "Dre", "reviews": -1}) == 403)
    check("squad: cannot write someone else's row",
          dre._patch_status(f"squads/{sid}/members/sam", {"name": "x"}) == 403)
    store.auth_uid = "sam"
    data = sam.fetch_squad(sid)
    dre_row = next((r for r in data["rows"] if r["user_id"] == "dre"), None)
    check("squad: members read every row, retention included",
          sorted(r["name"] for r in data["rows"]) == ["Dre", "Sammy"]
          and dre_row and dre_row["retention"] == 91.25 and dre_row["day"] == day
          and data["open"] and data["founder"] == "sam", str(data))
    check("squad: founder locks", sam.set_squad_open(sid, False))
    zed = new_client(store, "zed", "Zed")
    check("squad: join refused while locked", zed.join_squad("zed", sid, "Zed") == 403)
    store.auth_uid = "dre"
    check("squad: existing member still writes while locked",
          dre._patch_status(f"squads/{sid}/members/dre", {"reviews": 900}, ["reviews"]) == 200)
    check("squad: non-founder cannot lock or remove",
          not dre.set_squad_open(sid, True) and not dre.remove_member(sid, "sam"))
    store.auth_uid = "sam"
    check("squad: founder removes a member",
          sam.remove_member(sid, "dre") and f"squads/{sid}/members/dre" not in store.docs)
    store.auth_uid = "dre"
    check("squad: a removed member's next row write reports the squad gone",
          dre.upload_squad_rows("dre", dict(row, day=day, reviews=1), [sid]) == [sid]
          and _denied(lambda: dre.fetch_squad(sid)))
    store.auth_uid = "sam"
    check("squad: leave deletes my member doc",
          sam.leave_squad("sam", sid) and f"squads/{sid}/members/sam" not in store.docs)


def test_knocks_squad():
    """Knocks need a squad both people are in; names come from profiles."""
    store, sam, squad = _squad_fixture()
    sid = squad["id"]
    dre = new_client(store, "dre", "Dre")
    dre.join_squad("dre", sid, "Dre")
    ok = dre.send_knock("sam", "dre", "TOTALLY FAKE NAME", sid)
    check("knock: needs a squad both are in",
          not dre.send_knock("eve", "dre", "Dre", sid))
    check("knock: extra fields rejected",
          not dre.patch_doc("users/sam/knocks/dre", {"name": "Dre", "squad": sid, "crew": "x"}))
    eve = new_client(store, "eve", "Eve")
    eve_ok = eve.send_knock("sam", "eve", "Eve", sid)
    check("knock: squadmates can knock, outsiders cannot", ok and not eve_ok)
    store.auth_uid = "sam"
    knocks = sam.list_knocks("sam")
    check("knock: names from profiles (no spoofing), squad id carried",
          knocks == [("dre", "Dre", sid)], str(knocks))
    sam.delete_knock("sam", "dre")
    check("knock: delete clears it", sam.list_knocks("sam") == [])


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
          and "knocked" in html and "added you" in html and "&middot; crew" not in html)
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
          and "&#128293; Streak &#9662;" in by_streak, by_streak)
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


def test_marker_compat():
    """Cumulative markers: old clients stay green on newer rules; a v2.3
    client on v1.9-era rules sees squads denied and the probe stale."""
    v6 = fakes.FakeFirestore(rules_mode="repo")
    sys.modules["requests"].Session = lambda: fakes.FakeSession(v6)
    seed_users(v6, {"sam": "Sammy"}, {"sam": []})
    cl = new_client(v6, "sam", "Sammy")
    check("markers: v2.3 client current on v6 rules", cl.check_rules(TODAY.isoformat()) is False)
    check("markers: v1.7 client still green on v6 rules",
          cl._req("GET", f"{cl.base}/meta/rules-v2").status_code == 404)
    v3 = fakes.FakeFirestore(rules_mode="v3")
    sys.modules["requests"].Session = lambda: fakes.FakeSession(v3)
    seed_users(v3, {"sam": "Sammy"}, {"sam": []})
    cl3 = new_client(v3, "sam", "Sammy")
    check("markers: v2.3 client on v3 rules — squads denied, probe stale",
          _denied(lambda: cl3.fetch_squad("a" * 24))
          and cl3.check_rules(TODAY.isoformat()) is True)


def test_deletion_sweep():
    store, sam, squad = _squad_fixture()
    real_post = fakes.FakeSession.post
    fakes.FakeSession.post = lambda self, url, **kw: fakes.FakeResponse(200, {})
    try:
        sid = squad["id"]
        dre = new_client(store, "dre", "Dre")
        dre.join_squad("dre", sid, "Dre")
        dre.send_knock("sam", "dre", "Dre", sid)
        store.auth_uid = "sam"
        sam.delete_account("sam", None, [sid])
        check("deletion: squad membership and knocks are swept",
              f"squads/{sid}/members/sam" not in store.docs
              and not any(p.startswith("users/sam/knocks/") for p in store.docs))
    finally:
        fakes.FakeSession.post = real_post

def main():
    names = [n for n in list(globals()) if n.startswith("test_")]
    for n in names:
        globals()[n]()
    bad = [c for c in CHECKS if not c[1]]
    print(f"\n{len(CHECKS) - len(bad)}/{len(CHECKS)} checks passed")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
