"""End-to-end tests for Due Crew against fake anki + strict fake Firestore.

Run: python3 test_due_crew.py
"""

import datetime
import json
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
    from due_crew import share, shares
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


def test_hardening_v24():
    """The audit fixes that have a pure edge: command whitelist, error
    status, and per-sender cheer bookkeeping."""
    from due_crew import social
    check("pycmd: ids and keys pass, quote-breakers are dropped",
          board._pycmd("profile:abc_1-2") == "pycmd('duecrew:profile:abc_1-2'); return false;"
          and "'" not in board._pycmd("x:a')alert(1)//").replace("pycmd('duecrew:", "", 1)[:-len("'); return false;")])
    err = firebase.TransportError("query failed: 403", 403)
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
    store = fakes.FakeFirestore()
    sys.modules["requests"].Session = lambda: fakes.FakeSession(store)
    seed_users(store, {"sam": "Sammy"}, {"sam": []})
    cl = new_client(store, "sam", "Sammy")
    check("rules: users and codes cannot be listed",
          cl._req("GET", f"{cl.base}/users?pageSize=50").status_code == 403
          and cl._req("GET", f"{cl.base}/friend_codes?pageSize=50").status_code == 403)
    check("rules: a 61-char display name is refused, 60 is fine",
          not cl.patch_doc("users/sam", {"displayName": "x" * 61})
          and cl.patch_doc("users/sam", {"displayName": "x" * 60}))
    check("hint: a refused social write does not flip the rules-stale hint",
          not cl.patch_doc("users/zed/knocks/sam", {"name": "S", "squad": "x",
                                                    "at": {"timestampValue": "t"}}, label="knock")
          and not cl.session.get("rules_stale_hint"))


def test_v25_edges_emoji_week():
    """2.5: friend edges mirror the array (and vouch for add-backs on their
    own), crew emoji, the squad week count, block list, founder handoff."""
    from due_crew import share, shares
    from due_crew.stats import week_days
    ce = firebase.clean_emoji
    check("emoji: one glyph passes, with skin tone and joiners; text does not",
          ce("🦊") == "🦊" and ce(" 🐢 ") == "🐢" and ce("👍🏽") == "👍🏽"
          and ce("👩‍💻") == "👩‍💻" and ce("🇺🇸") == "🇺🇸" and ce("🦊🐢") == "🦊"
          and ce("A") == "" and ce("<b>") == "" and ce("") == "" and ce(None) == "")
    store = fakes.FakeFirestore()
    sys.modules["requests"].Session = lambda: fakes.FakeSession(store)
    seed_users(store, {"sam": "Sammy", "dre": "Dre", "eve": "Eve"},
               {"sam": ["dre"], "dre": [], "eve": ["sam"]})
    sam = new_client(store, "sam", "Sammy")
    col = make_user_col([TODAY])
    files = tempfile.mkdtemp()
    stats = gather_stats(col, files)
    sam.upload_today("sam", "Sammy", TODAY.isoformat(), stats, {"emoji": "🦊"})
    check("edges: first upload mirrors the existing array once, and the emoji lands",
          "users/sam/friends/dre" in store.docs
          and store.docs["users/sam"]["emoji"] == {"stringValue": "🦊"}
          and sam.session["friend_edges"] == {"uid": "sam", "ids": ["dre"]})
    n0 = len(store.log)
    sam.upload_today("sam", "Sammy", TODAY.isoformat(), stats, {"emoji": "🦊"})
    check("edges: steady state writes no edge",
          not any(p.startswith("users/sam/friends/") for m, p, st in store.log[n0:] if m == "PATCH"))
    sam.set_friends("sam", ["dre", "eve"])
    check("edges: adding writes one edge; the array stays for older clients",
          "users/sam/friends/eve" in store.docs
          and [v["stringValue"] for v in store.docs["users/sam"]["friends"]["arrayValue"]["values"]] == ["dre", "eve"])
    sam.set_friends("sam", ["eve"])
    check("edges: removing deletes the edge", "users/sam/friends/dre" not in store.docs)
    # eve added sam by array only (an older client); dre will add sam by edge only (a 2.6 client)
    store.docs["users/dre"]["friends"] = fakes.fv_str("") if False else store.docs["users/dre"]["friends"]
    store.docs["users/dre"]["friends"] = {"arrayValue": {"values": []}}
    store.docs["users/dre/friends/sam"] = {"at": {"timestampValue": "t"}}
    sam.set_friends("sam", ["dre", "eve"])
    _own, resolved, pending = sam.list_friends("sam", check_edges=True)
    mutual = {fid: m for fid, _p, m in resolved}
    check("edges: an add-back is seen through the edge alone, or the array alone",
          mutual == {"dre": True, "eve": True} and pending == [], str(mutual))
    _own, resolved, _p = sam.list_friends("sam", check_edges=False)
    check("edges: without the edge check, an edge-only add-back reads pending (cheap path)",
          {fid: m for fid, _p, m in resolved} == {"dre": False, "eve": True})
    store.auth_uid = "eve"
    eve = new_client(store, "eve", "Eve")
    check("edges: only the two people on an edge can read it",
          eve._req("GET", f"{eve.base}/users/sam/friends/eve").status_code == 200
          and eve._req("GET", f"{eve.base}/users/sam/friends/dre").status_code == 403
          and eve._req("GET", f"{eve.base}/users/sam/friends?pageSize=50").status_code == 403)
    # rules: isFriend honours the edge — dre reads sam's stats via the edge, eve via the array
    store.auth_uid = "dre"
    dre = new_client(store, "dre", "Dre")
    check("edges: rules grant stats to an edge friend",
          dre._req("GET", f"{dre.base}/users/sam/daily_stats/{TODAY.isoformat()}").status_code == 200)

    # ---- squads: week + emoji on rows, block, handoff ----
    store.auth_uid = "sam"
    squad = sam.create_squad("sam", "busm", "Sammy")
    sid = squad["id"]
    store.auth_uid = "dre"
    dre.join_squad("dre", sid, "Dre")
    row = {"name": "Dre", "reviews": 10, "studyTimeMs": 1000, "streak": 1, "week": 5, "emoji": "🐢"}
    check("squad row: week and emoji ride along", dre.upload_squad_rows("dre", dict(row, day=TODAY.isoformat()), [sid]) == [])
    check("squad row: week outside 0..7 is refused",
          dre._patch_status(f"squads/{sid}/members/dre", {"week": 9}, ["week"]) == 403)
    check("week_days counts the last seven days from the revlog",
          week_days(StatsQueries(make_user_col([TODAY, TODAY - datetime.timedelta(days=1),
                                                TODAY - datetime.timedelta(days=9)]))) == 2)
    store.auth_uid = "sam"
    data = sam.fetch_squad(sid)
    drow = next(r for r in data["rows"] if r["user_id"] == "dre")
    check("squad fetch: week, emoji, and the ban list come back",
          drow["week"] == 5 and drow["emoji"] == "🐢" and data["banned"] == [])
    store.auth_uid = "dre"
    check("block: non-founder cannot", not dre.block_member(sid, "sam", []))
    store.auth_uid = "sam"
    check("block: founder blocks; the member is gone",
          sam.block_member(sid, "dre", data["banned"]) and f"squads/{sid}/members/dre" not in store.docs)
    store.auth_uid = "dre"
    check("block: rejoining is refused even with the door open",
          dre.join_squad("dre", sid, "Dre") == 403)
    store.auth_uid = "eve"
    eve.join_squad("eve", sid, "Eve")
    store.auth_uid = "sam"
    check("handoff: only to a member",
          not sam.set_founder(sid, "dre") and sam.set_founder(sid, "eve")
          and store.docs[f"squads/{sid}"]["founder"] == {"stringValue": "eve"})
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
          and "&#128197; 7 days &#9662;" in html and "squadshare" in html
          and html.index("igk") < html.index("Sammy") < html.index("Priya"))
    crew = board.render({"entries": [{"user_id": "sam", "name": "Sammy", "emoji": "🦊", "you": True,
                                       "paused": False, "last_updated": "", "exam_date": "",
                                       "days": {labels[0]: {"studied": True, "reviews": 3}}, "decks": []}],
                         "labels": labels, "tomorrow": "", "pending": []}, {"sort": "week"}, 0)
    check("crew board: emoji by the name; the squads-only sort falls back to reviews",
          "🦊 Sammy" in crew and "&#128218; Reviews &#9662;" in crew)
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
    """2.5.1: a refused sign-in is detected (and only a REFUSED one — offline
    is not signed out), the build number rides the profile, a refused squad
    row isn't mistaken for removal, and staleness has a retry guard."""
    import due_crew
    store = fakes.FakeFirestore()
    sys.modules["requests"].Session = lambda: fakes.FakeSession(store)
    seed_users(store, {"sam": "Sammy", "dre": "Dre"}, {"sam": [], "dre": []})
    cl = new_client(store, "sam", "Sammy")
    check("session: alive to begin with", cl.signed_in and not cl.session_dead)

    store.force_401 = True
    store.token_reply = "network"
    _doc, status = cl.get_doc("users/sam")
    check("session: offline during refresh is NOT signed out", status == 401 and not cl.session_dead)
    store.token_reply = (503, {})
    cl.get_doc("users/sam")
    check("session: a 5xx from the token endpoint is NOT signed out", not cl.session_dead)
    store.token_reply = (400, {"error": {"message": "API key not valid. Please pass a valid API key."}})
    cl.get_doc("users/sam")
    check("session: an unrelated 400 is NOT signed out", not cl.session_dead)
    store.token_reply = (400, {"error": {"message": "TOKEN_EXPIRED"}})
    cl.get_doc("users/sam")
    check("session: a refused refresh token marks the session dead", cl.session_dead and cl.signed_in)
    cl2 = new_client(store, "sam", "Sammy")
    cl2.session["auth_dead"] = True
    cl2._store_tokens({"localId": "sam", "idToken": "t-sam", "refreshToken": "r"}, "s@example.com")
    check("session: signing in again clears it", not cl2.session_dead)
    store.force_401 = False
    store.token_reply = None

    col = make_user_col([TODAY])
    cl3 = new_client(store, "sam", "Sammy")
    cl3.upload_today("sam", "Sammy", TODAY.isoformat(), gather_stats(col, tempfile.mkdtemp()), {}, version="2.5.1")
    check("profile carries the client version",
          store.docs["users/sam"].get("clientVersion") == {"stringValue": "2.5.1"})

    squad = cl3.create_squad("sam", "busm", "Sammy")
    sid = squad["id"]
    store.auth_uid = "dre"
    dre = new_client(store, "dre", "Dre")
    dre.join_squad("dre", sid, "Dre")
    bad = {"name": "Dre", "reviews": 1, "studyTimeMs": 1, "streak": 1, "week": 9, "day": TODAY.isoformat()}
    gone = dre.upload_squad_rows("dre", bad, [sid])
    check("squad: a row the rules refuse is NOT read as removal; it raises the rules hint",
          gone == [] and dre.session.get("rules_stale_hint") is True
          and f"squads/{sid}/members/dre" in store.docs)
    store.auth_uid = "sam"
    cl3.remove_member(sid, "dre")
    store.auth_uid = "dre"
    good = dict(bad, week=3)
    check("squad: once actually removed, the same 403 does mean gone",
          dre.upload_squad_rows("dre", good, [sid]) == [sid])

    ce, too_long = firebase.clean_emoji, firebase.emoji_too_long
    family = "\U0001F468\u200d\U0001F469\u200d\U0001F467\u200d\U0001F466"   # 11 UTF-16 units
    monster = "\U0001F468" + "\u200d\U0001F469" * 6                            # 20 units
    units = lambda t: len(t.encode("utf-16-le")) // 2
    check("emoji: the cap is the rules' own unit (UTF-16), so a family emoji passes",
          ce(family) == family and units(family) == 11 and not too_long(family))
    check("emoji: past 16 units it is refused whole, never truncated or sent",
          units(monster) == 20 and ce(monster) == "" and too_long(monster)
          and not too_long("abc") and not too_long("🦊"))
    check("emoji: everything the client accepts fits the rules' 16 units",
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
    """Found 2026-09-18: on an OPEN squad, Remove undid itself. Clients PATCH
    their daily row; a PATCH to a missing doc is an insert; so the removed
    person's next sync re-created their membership. The 2.3 test missed it by
    locking the squad first. Two layers now: rules demand joinedAt on a
    create, and 2.5.1 row writes are update-only."""
    store, sam, squad = _squad_fixture()
    sid = squad["id"]
    path = f"squads/{sid}/members/dre"
    store.auth_uid = "dre"
    dre = new_client(store, "dre", "Dre")
    check("join: a join without joinedAt is refused",
          dre._patch_status(path, {"name": "Dre"}) == 403)
    check("join: the real join works", dre.join_squad("dre", sid, "Dre") in (200, 201))
    row = {"name": "Dre", "reviews": 5, "studyTimeMs": 1, "streak": 1, "day": TODAY.isoformat()}
    check("row: a member's sync still lands", dre.upload_squad_rows("dre", row, [sid]) == []
          and store.docs[path]["reviews"] == {"integerValue": "5"})
    store.auth_uid = "sam"
    sam.remove_member(sid, "dre")            # the squad is OPEN — never locked
    store.auth_uid = "dre"
    check("remove sticks: a 2.5.1 sync reports gone and re-creates nothing",
          dre.upload_squad_rows("dre", dict(row, reviews=6), [sid]) == [sid] and path not in store.docs)
    old_client = dict(row, reviews=7, updatedAt={"timestampValue": "2026-09-18T10:00:00Z"})
    check("remove sticks: an old client's plain PATCH is refused by the rules",
          dre._patch_status(path, old_client) == 403 and path not in store.docs)
    store.auth_uid = "sam"
    check("remove sticks: the founder's board no longer lists them",
          sorted(r["name"] for r in sam.fetch_squad(sid)["rows"]) == ["Sammy"])
    store.auth_uid = "dre"
    check("a deliberate rejoin with the code still works — Block is what stops that",
          dre.join_squad("dre", sid, "Dre") in (200, 201))


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
    clean = firebase._clean_decks
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


def main():
    names = [n for n in list(globals()) if n.startswith("test_")]
    for n in names:
        globals()[n]()
    bad = [c for c in CHECKS if not c[1]]
    print(f"\n{len(CHECKS) - len(bad)}/{len(CHECKS)} checks passed")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
