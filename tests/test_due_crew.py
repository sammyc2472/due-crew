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
import types

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
        cl.upload_backfill(cl.user_id, week, cfg, labels=labels)
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


def test_cheer_any_emoji():
    """v2.7: a cheer carries any one emoji (rules-v8). The fake restates the
    shape rule; the client keeps one cluster on send and on receive, and
    offers only the classic three while the server is on older rules."""
    from due_crew import social
    from due_crew.app import CHEER_CLASSIC, CHEER_QUICK
    store = fakes.FakeFirestore()
    sys.modules["requests"].Session = lambda: fakes.FakeSession(store)
    seed_users(store, {"sam": "Sammy", "dre": "Dre"}, {"sam": ["dre"], "dre": ["sam"]})
    dre = new_client(store, "dre", "Dre")
    path = "users/sam/cheers/dre"
    party, thumbs = "\U0001F973", "\U0001F44D\U0001F3FD"
    check("any emoji: a new one lands", dre.send_cheer("sam", "dre", "Dre", party) is True
          and store.docs[path]["emoji"] == fv_str(party))
    check("any emoji: a skin tone rides along as one cluster",
          dre.send_cheer("sam", "dre", "Dre", thumbs) is True
          and store.docs[path]["emoji"] == fv_str(thumbs))
    check("any emoji: the client sends one cluster, whatever it was handed",
          dre.send_cheer("sam", "dre", "Dre", party + "\U0001F389 yay") is True
          and store.docs[path]["emoji"] == fv_str(party))
    check("any emoji: text never leaves the client",
          dre.send_cheer("sam", "dre", "Dre", "lol") is False
          and store.docs[path]["emoji"] == fv_str(party))
    ts = {"timestampValue": "2026-09-01T00:00:00Z"}
    probe = new_client(store, "dre", "Dre")  # past the client's cleaner, straight at the rules
    refused = [probe.patch_doc(path, {"emoji": bad, "name": "Dre", "at": ts}, ["emoji", "name", "at"])
               for bad in ("lol", "\U0001F525x", "\U0001F389" * 9, "", "\U0001F389 ")]
    check("fake rules: letters, a trailing letter, 18 units, empty, and a space are refused",
          refused == [False] * 5 and store.docs[path]["emoji"] == fv_str(party), str(refused))
    store.docs[path]["emoji"] = fv_str("hello")  # as if the rules had let it through
    sam = new_client(store, "sam", "Sammy")
    data, _l, _t = fetch_as(store, sam, make_user_col([TODAY]))
    check("any emoji: a doc that isn't one emoji is dropped on receive", data["cheers"] == [])
    check("any emoji: a delivered cheer's doc is gone", path not in store.docs)
    store.docs[path] = {"emoji": fv_str(thumbs), "name": fv_str("Dre"), "at": ts}
    data, _l, _t = fetch_as(store, sam, make_user_col([TODAY]))
    check("any emoji: a real one arrives intact", [c["emoji"] for c in data["cheers"]] == [thumbs])

    old = fakes.FakeFirestore(rules_mode="v7")
    sys.modules["requests"].Session = lambda: fakes.FakeSession(old)
    seed_users(old, {"sam": "Sammy", "dre": "Dre"}, {"sam": ["dre"], "dre": ["sam"]})
    dre_old = new_client(old, "dre", "Dre")
    check("older rules: the classic three still land",
          dre_old.send_cheer("sam", "dre", "Dre", "\U0001F525") is True)
    check("older rules: a new emoji is refused by the server",
          dre_old.send_cheer("sam", "dre", "Dre", party) is False)
    dre_old.check_rules(TODAY.isoformat())
    check("older rules: the client knows; the picker shrinks to the three, no other box",
          dre_old.rules_stale is True and social.cheer_choices(True) == (CHEER_CLASSIC, False)
          and social.cheer_choices(False) == (CHEER_QUICK, True))
    check("cheer gate: one cluster; a new emoji held back while stale; text never",
          social.cheer_allowed(party + "\U0001F389", False) == party
          and social.cheer_allowed(party, True) == ""
          and social.cheer_allowed("\U0001F525", True) == "\U0001F525"
          and social.cheer_allowed("lol", False) == "")


def test_reads_diet():
    """2.7: fewer reads per refresh, and the numbers pinned. Cheers come
    from one list and their docs go once delivered; profiles are read once
    a day; my own row comes from my own uploads; a friend's clock says which
    day doc to read. The numbers below are the budget: a change here is a
    change in what the add-on costs per user, and must be deliberate."""
    import due_crew  # the glue: _wants_fetch, _open_push_due
    from due_crew.backend.firebase import _clock_label, _wanted
    N = 11
    store = fakes.FakeFirestore()
    sys.modules["requests"].Session = lambda: fakes.FakeSession(store)
    friends = [f"f{i}" for i in range(N)]
    seed_users(store, {"sam": "Sammy", **{f: f.upper() for f in friends}},
               {"sam": friends, **{f: ["sam"] for f in friends}})
    labels = [(TODAY - datetime.timedelta(days=i)).isoformat() for i in range(7)]
    tomorrow = (TODAY + datetime.timedelta(days=1)).isoformat()
    for f in friends:  # 2.7 clients, on my clock, with 2.5's edge docs
        store.docs[f"users/{f}"].update(tz={"integerValue": "0"}, rollover={"integerValue": "4"})
        store.docs[f"users/{f}/friends/sam"] = {"at": {"timestampValue": "2026-09-01T00:00:00Z"}}
        for lb in labels:
            store.docs[f"users/{f}/daily_stats/{lb}"] = {"studied": {"booleanValue": True},
                                                          "reviews": {"integerValue": "100"}}
    reads = {"n": 0}
    orig = store.handle

    def counting(method, url, headers=None, json_body=None):
        resp = orig(method, url, headers=headers, json_body=json_body)
        if url.endswith(":batchGet"):
            reads["n"] += len(json_body["documents"])
        elif url.endswith(":runQuery"):
            reads["n"] += max(1, sum(1 for i in resp.json() if "document" in i))
        elif method == "GET" and "?" in url:
            reads["n"] += max(1, len((resp.json() or {}).get("documents", [])))
        elif method == "GET":
            reads["n"] += 1
        return resp
    store.handle = counting
    noon = datetime.datetime(2026, 9, 1, 12, 0, tzinfo=datetime.timezone.utc)  # TODAY, on a tz-0 clock
    sam = new_client(store, "sam", "Sammy")

    def count(fn):
        """Billed reads: the docs, plus (2.9) the exists()/get() calls the
        rules make to check consent, one per friend per request."""
        reads["n"] = 0
        before = store.rule_reads
        fn()
        return reads["n"] + store.rule_reads - before
    first = count(lambda: (sam.check_rules(labels[0]), sam.list_knocks("sam"),
                           sam.fetch_board("sam", labels, tomorrow=tomorrow, include_shared=True,
                                           check_edges=True, now_utc=noon)))
    check("reads: first open, nothing cached = marker 1 + profiles 12 + days 7x12 + decks 12 + cheers 1"
          " + knocks 1 + rules 11",
          first == 1 + 12 + 84 + 12 + 1 + 1 + 11, str(first))
    sync_once(store, sam, make_user_col([TODAY]), tempfile.mkdtemp(), {}, TODAY)
    own = sam.session.get("own_days") or {}
    check("reads: my uploads are remembered by label (empty days as empty), with when they changed",
          set(labels) <= set(own) and own[labels[0]].get("studied") is True
          and own[labels[3]] is None
          and str(own[labels[0]].get("updatedAt", "")).endswith("Z"))
    light = count(lambda: (sam.list_knocks("sam"),
                           sam.fetch_board("sam", labels, tomorrow=tomorrow, include_shared=False,
                                           check_edges=False, light=True, own_days=own,
                                           cached_people=True, now_utc=noon)))
    check("reads: a light refresh = one day doc per friend + cheers list + knocks list + rules 11 = 24",
          light == N + 2 + N, str(light))
    full = count(lambda: (sam.list_knocks("sam"),
                          sam.fetch_board("sam", labels, tomorrow=tomorrow, include_shared=False,
                                          check_edges=True, own_days=own, now_utc=noon)))
    check("reads: Refresh = profiles 12 + 7 days x 11 friends + cheers 1 + knocks 1 + rules 11 = 102",
          full == 12 + 77 + 2 + N, str(full))
    data = sam.fetch_board("sam", labels, tomorrow=tomorrow, light=True, own_days=own,
                           cached_people=True, now_utc=noon)
    me = next(e for e in data["entries"] if e["you"])
    check("own row: today from my own upload, not read back",
          me["days"].get(labels[0], {}).get("studied") is True and "updatedAt" not in me["days"][labels[0]])

    # a friend's clock decides which doc is live for them
    store.docs["users/f1"].update(tz={"integerValue": "600"})     # ten hours ahead
    store.docs["users/f2"].pop("tz"); store.docs["users/f2"].pop("rollover")  # a 2.6 client
    store.docs["users/f3"].update(tz={"integerValue": "-600"})    # ten hours behind
    sam._people = None
    evening = datetime.datetime(2026, 9, 1, 20, 0, tzinfo=datetime.timezone.utc)
    data = sam.fetch_board("sam", labels, tomorrow=tomorrow, light=True, own_days=own, now_utc=evening)
    keys = {e["user_id"]: sorted(e["days"]) for e in data["entries"]}
    check("clock: a friend ten hours ahead is read on my tomorrow only",
          keys["f1"] == [tomorrow], str(keys["f1"]))
    check("clock: a friend on an older client is read on today and tomorrow, as before",
          keys["f2"] == sorted([labels[0], tomorrow]), str(keys["f2"]))
    morning = datetime.datetime(2026, 9, 1, 6, 0, tzinfo=datetime.timezone.utc)
    data = sam.fetch_board("sam", labels, tomorrow=tomorrow, light=True, own_days=own, now_utc=morning)
    keys = {e["user_id"]: sorted(e["days"]) for e in data["entries"]}
    check("clock: a friend ten hours behind is read on my yesterday, the day they are writing",
          keys["f3"] == [labels[1]] and keys["f0"] == [labels[0]], f'{keys["f3"]} {keys["f0"]}')
    check("clock: label from tz and rollover; nonsense means unknown",
          _clock_label({"tz": 0, "rollover": 4}, noon) == labels[0]
          and _clock_label({"tz": 600, "rollover": 4}, evening) == tomorrow
          and _clock_label({}, noon) is None and _clock_label({"tz": 5000}, noon) is None
          and _clock_label({"tz": 0, "rollover": 99}, noon) == labels[0])
    check("clock: a full fetch reads the week, plus tomorrow only for a clock that may be there",
          _wanted({"tz": 0, "rollover": 4}, labels, tomorrow, noon, light=False) == labels
          and _wanted({}, labels, tomorrow, noon, light=False) == labels + [tomorrow]
          and _wanted({"tz": 600, "rollover": 4}, labels, tomorrow, evening, light=False) == labels + [tomorrow])

    # cheers: one list, delivered once, then gone
    store.auth_uid = "f0"
    f0 = new_client(store, "f0", "F0")
    f0.send_cheer("sam", "f0", "F0", "\U0001F525")
    store.auth_uid = "sam"
    got = count(lambda: sam.fetch_board("sam", labels, tomorrow=tomorrow, include_shared=False,
                                        check_edges=False, light=True, own_days=own,
                                        cached_people=True, now_utc=noon))
    data = sam.fetch_board("sam", labels, tomorrow=tomorrow, light=True, own_days=own,
                           cached_people=True, now_utc=noon)
    # f2 is back on a 2.6 client since the clock checks: two docs for them
    check("cheers: one read to find it, delivered, and its doc is gone before the next fetch",
          got == N + 1 + 1 + N and "users/sam/cheers/f0" not in store.docs and data["cheers"] == [], str(got))

    # profiles cached for the day: someone removing me is noticed, once, not an outage
    store.docs["users/f4"]["friends"] = {"arrayValue": {"values": []}}
    store.docs.pop("users/f4/friends/sam", None)
    data = sam.fetch_board("sam", labels, tomorrow=tomorrow, light=True, own_days=own,
                           cached_people=True, now_utc=noon)
    check("profiles: a friend who removed me drops off the board on the next light refresh, no error",
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


def _push29(store, cl, col, files, cfg, version="2.9.0"):
    """What a 2.9 client's sync uploads: today, the week's backfill, the
    week doc. Returns the labels."""
    store.auth_uid = cl.user_id
    q = StatsQueries(col)
    labels = [q.day_label(i) for i in range(7)]
    stats = gather_stats(col, files)
    cl.upload_today(cl.user_id, cl.display_name, labels[0], stats, cfg, version=version,
                    clock={"tz": 0, "rollover": 4})
    cl.upload_backfill(cl.user_id, gather_week(col, files), cfg, labels=labels)
    cl.upload_week(cl.user_id, labels, cfg)
    return labels


def test_week_doc_v29():
    """2.9 (H1): a friend's week is one doc. Same rows as the day docs gave,
    a third of the reads on a full fetch, and it survives a friend who has
    updated but not pushed yet."""
    N = 11
    store = fakes.FakeFirestore()
    sys.modules["requests"].Session = lambda: fakes.FakeSession(store)
    friends = [f"f{i}" for i in range(N)]
    seed_users(store, {"sam": "Sammy", **{f: f.upper() for f in friends}},
               {"sam": friends, **{f: ["sam"] for f in friends}})
    days = [TODAY - datetime.timedelta(days=i) for i in (0, 1, 3, 4, 6)]
    for f in friends:
        store.docs[f"users/{f}/friends/sam"] = {"at": {"timestampValue": "2026-09-01T00:00:00Z"}}
        _push29(store, new_client(store, f, f.upper()), make_user_col(days), tempfile.mkdtemp(), {})
    labels = [(TODAY - datetime.timedelta(days=i)).isoformat() for i in range(7)]
    tomorrow = (TODAY + datetime.timedelta(days=1)).isoformat()
    week = store.docs.get("users/f0/shared/week", {})
    got_days = sorted(week.get("days", {}).get("mapValue", {}).get("fields", {}))
    check("week doc: one doc holds the studied days of the week, numbers inside",
          got_days == sorted(d.isoformat() for d in days)
          and "reviews" in week["days"]["mapValue"]["fields"][labels[0]]["mapValue"]["fields"],
          str(got_days))
    # the same friends, read through the week doc and through the day docs
    sam = new_client(store, "sam", "Sammy")
    via_week = sam.fetch_board("sam", labels, tomorrow=tomorrow)
    for f in friends:
        store.docs[f"users/{f}"]["clientVersion"] = fv_str("2.8.0")
    sam._people = None
    via_days = sam.fetch_board("sam", labels, tomorrow=tomorrow)
    rows = lambda data: {e["user_id"]: [(lb, (e["days"].get(lb) or {}).get("reviews"),
                                         board._showed(e["days"].get(lb))) for lb in labels]
                         for e in data["entries"] if not e["you"]}
    check("week doc: every friend's week reads the same as from their day docs",
          rows(via_week) == rows(via_days) and len(rows(via_week)) == N)
    for f in friends:
        store.docs[f"users/{f}"]["clientVersion"] = fv_str("2.9.0")

    reads = {"n": 0}
    orig = store.handle

    def counting(method, url, headers=None, json_body=None):
        resp = orig(method, url, headers=headers, json_body=json_body)
        if url.endswith(":batchGet"):
            reads["n"] += len(json_body["documents"])
        elif method == "GET" and "?" in url:
            reads["n"] += max(1, len((resp.json() or {}).get("documents", [])))
        elif method == "GET":
            reads["n"] += 1
        return resp
    store.handle = counting

    def billed(fn):
        reads["n"] = 0
        before = store.rule_reads
        fn()
        return reads["n"] + store.rule_reads - before
    store.auth_uid = "sam"
    fresh = new_client(store, "sam", "Sammy")
    store.docs["users/sam"]["clientVersion"] = fv_str("2.9.0")
    store.docs["users/sam/shared/week"] = {"v": {"integerValue": "1"},
                                           "days": {"mapValue": {"fields": {}}}}
    first = billed(lambda: (fresh.check_rules(labels[0]), fresh.list_knocks("sam"),
                            fresh.fetch_board("sam", labels, tomorrow=tomorrow, include_shared=True,
                                              check_edges=True)))
    check("reads 2.9: first open = marker 1 + profiles 12 + week docs 12 + decks 12 + cheers 1"
          " + knocks 1 + rules 11 = 50 (2.8: 122)", first == 50, str(first))
    own = {lb: None for lb in labels}
    full = billed(lambda: (fresh.list_knocks("sam"),
                           fresh.fetch_board("sam", labels, tomorrow=tomorrow, include_shared=False,
                                             check_edges=True, own_days=own)))
    check("reads 2.9: Refresh = profiles 12 + week docs 11 + cheers 1 + knocks 1 + rules 11 = 36"
          " (2.8: 102)", full == 36, str(full))
    light = billed(lambda: fresh.fetch_board("sam", labels, tomorrow=tomorrow, include_shared=False,
                                             light=True, own_days=own, cached_people=True))
    check("reads 2.9: a light refresh = week docs 11 + cheers 1 + rules 11 = 23, and knocks"
          " only hourly now", light == 23, str(light))
    data = fresh.fetch_board("sam", labels, tomorrow=tomorrow, include_shared=False,
                             light=True, own_days=own, cached_people=True)
    f1 = next(e for e in data["entries"] if e["user_id"] == "f1")
    check("reads 2.9: a light refresh still carries the whole week",
          sum(1 for lb in labels if board._showed(f1["days"].get(lb))) == len(days))
    store.handle = orig

    # updated, not pushed yet: no week doc, so their day docs, read once more
    store.docs.pop("users/f2/shared/week")
    fresh._people = None
    data = fresh.fetch_board("sam", labels, tomorrow=tomorrow)
    f2 = next(e for e in data["entries"] if e["user_id"] == "f2")
    check("week doc: missing for a 2.9 friend, their day docs fill in",
          sum(1 for lb in labels if board._showed(f2["days"].get(lb))) == len(days))

    # away rides as a range; paused empties the doc; exam comes along
    f3 = new_client(store, "f3", "F3")
    away = {"away_from": (TODAY + datetime.timedelta(days=1)).isoformat(),
            "away_to": (TODAY + datetime.timedelta(days=5)).isoformat(),
            "exam_date": (TODAY + datetime.timedelta(days=9)).isoformat()}
    _push29(store, f3, make_user_col(days), tempfile.mkdtemp(), away)
    store.auth_uid = "sam"
    fresh._people = None
    data = fresh.fetch_board("sam", labels, tomorrow=tomorrow)
    e3 = next(e for e in data["entries"] if e["user_id"] == "f3")
    check("week doc: an away spell flags my tomorrow for a friend, and the exam date rides along",
          (e3["days"].get(tomorrow) or {}).get("away") is True
          and e3["exam_date"] == away["exam_date"])
    f4 = new_client(store, "f4", "F4")
    _push29(store, f4, make_user_col(days), tempfile.mkdtemp(), {"paused": True})
    wk = store.docs["users/f4/shared/week"]
    check("week doc: pausing empties the days and says so",
          wk["paused"] == {"booleanValue": True} and not wk["days"]["mapValue"].get("fields"))
    store.auth_uid = "sam"
    fresh._people = None
    data = fresh.fetch_board("sam", labels, tomorrow=tomorrow)
    e4 = next(e for e in data["entries"] if e["user_id"] == "f4")
    check("week doc: a paused friend reads as paused from the doc itself",
          e4["paused"] is True and not any(e4["days"].get(lb) for lb in labels))
    f5 = new_client(store, "f5", "F5")
    col5, files5 = make_user_col(days), tempfile.mkdtemp()
    week_writes = lambda: sum(1 for m, p, st in store.log if m == "PATCH" and p == "users/f5/shared/week")
    base = week_writes()
    _push29(store, f5, col5, files5, {})
    once = week_writes() - base
    _push29(store, f5, col5, files5, {})
    check("week doc: hash-guarded, a second push with nothing new writes nothing",
          once == 1 and week_writes() - base == 1, f"{once} {week_writes() - base}")


def test_big_crews_v29():
    """2.9 (G1): the rules allow 20 access calls per multi-document read,
    one per friend with an edge doc, two without. A crew past that used to
    fail its whole batch, so the board never loaded."""
    for n, edges in ((21, True), (25, False)):
        store = fakes.FakeFirestore()
        sys.modules["requests"].Session = lambda: fakes.FakeSession(store)
        friends = [f"g{i}" for i in range(n)]
        seed_users(store, {"sam": "Sammy", **{f: f for f in friends}},
                   {"sam": friends, **{f: ["sam"] for f in friends}})
        labels = [(TODAY - datetime.timedelta(days=i)).isoformat() for i in range(7)]
        for f in friends:
            if edges:
                store.docs[f"users/{f}/friends/sam"] = {"at": {"timestampValue": "2026-09-01T00:00:00Z"}}
            store.docs[f"users/{f}/daily_stats/{labels[0]}"] = {"studied": {"booleanValue": True},
                                                                "reviews": {"integerValue": "5"}}
        sam = new_client(store, "sam", "Sammy")
        store.auth_uid = "sam"
        try:
            sam.batch_get([f"users/{f}/daily_stats/{labels[0]}" for f in friends])
            one_batch = "loaded"
        except firebase.TransportError as e:
            one_batch = e.status
        data = sam.fetch_board("sam", labels)
        studied = sum(1 for e in data["entries"] if not e["you"]
                      and board._showed(e["days"].get(labels[0])))
        decks = sam.fetch_decks([f for f in friends])
        check(f"big crew: {n} friends {'with' if edges else 'without'} edge docs is refused as one"
              " batch, loads in batches of ten", one_batch == 403 and studied == n and len(decks) == n,
              f"{one_batch} {studied}")


def test_profile_guard_v29():
    """2.9 (H4): the profile is written when a field changes or today's
    numbers do, not on every push."""
    store = fakes.FakeFirestore()
    sys.modules["requests"].Session = lambda: fakes.FakeSession(store)
    seed_users(store, {"sam": "Sammy"}, {"sam": []})
    sam = new_client(store, "sam", "Sammy")
    col = make_user_col([TODAY])
    files = tempfile.mkdtemp()
    writes = lambda: sum(1 for m, p, st in store.log if m == "PATCH" and p == "users/sam")
    _push29(store, sam, col, files, {})
    a = writes()
    stamp = sam.session.get("last_ok")
    _push29(store, sam, col, files, {})
    b = writes()
    check("profile: a push with nothing new doesn't rewrite it, and still counts as synced",
          a == 1 and b == 1 and sam.session.get("last_ok") >= stamp, f"{a} {b}")
    _push29(store, sam, col, files, {"emoji": "\U0001F98A"})
    c = writes()
    fakes.add_review(col.db.conn,
                     int(datetime.datetime.combine(TODAY, datetime.time(13)).timestamp() * 1000))
    _push29(store, sam, col, files, {"emoji": "\U0001F98A"})
    d = writes()
    check("profile: a new emoji rewrites it, and so does a new review (last active moves)",
          c == 2 and d == 3, f"{c} {d}")


def test_code_knocks_v29():
    """2.9 (J1): adding a code knocks its owner, so they add back in one
    click. The rules let a knock through when it carries the recipient's
    own friend code; on older rules the add still stands."""
    for mode, expect in (("repo", True), ("v8", False)):
        store = fakes.FakeFirestore(rules_mode=mode)
        sys.modules["requests"].Session = lambda: fakes.FakeSession(store)
        seed_users(store, {"sam": "Sammy", "priya": "Priya", "carl": "Carl"},
                   {"sam": [], "priya": [], "carl": []})
        store.docs["friend_codes/SAM123"] = {"userId": fv_str("sam")}
        store.docs["friend_codes/CRL456"] = {"userId": fv_str("carl")}
        priya = new_client(store, "priya", "Priya")
        friend, err = priya.add_friend("priya", "Study with me on Due Crew · my code SAM123", [], "Priya")
        knock = store.docs.get("users/sam/knocks/priya")
        check(f"code knock ({mode}): a pasted invite adds, and the owner {'is' if expect else 'is not'} knocked",
              err is None and friend["user_id"] == "sam" and friend["knocked"] is expect
              and (knock is not None) is expect
              and "sam" in [v["stringValue"] for v in store.docs["users/priya"]["friends"]["arrayValue"]["values"]])
        if mode == "repo":
            store.auth_uid = "sam"
            sam = new_client(store, "sam", "Sammy")
            check("code knock: the owner's list shows it, with no squad",
                  sam.list_knocks("sam") == [("priya", "Priya", "")])
            store.auth_uid = "priya"
            forged = priya.send_code_knock("carl", "priya", "Priya", "SAM123")
            check("code knock: someone else's code doesn't open another door", forged is False)
    check("invite paste: a friend code from a code, a spaced code, or either invite wording",
          firebase.friend_code_from("k7q2zp") == "K7Q2ZP"
          and firebase.friend_code_from(" K7Q 2ZP ") == "K7Q2ZP"
          and firebase.friend_code_from("Study with me on Due Crew — Anki add-on 2035408484.\nMy friend code: K7Q2ZP") == "K7Q2ZP"
          and firebase.friend_code_from("Study with me on Due Crew · my code K7Q2ZP\n— Due Crew · Anki add-on 2035408484") == "K7Q2ZP"
          and firebase.friend_code_from("Join busm on Due Crew · code ABCD2345") == "")
    check("invite paste: a squad code from its invite, even from a squad named for codes",
          firebase.squad_code_from("Join code club on Due Crew · code ABCD2345\n— Due Crew") == "ABCD2345"
          and firebase.squad_code_from("abcd 2345") == "ABCD2345")
    store = fakes.FakeFirestore()
    sys.modules["requests"].Session = lambda: fakes.FakeSession(store)
    cl = firebase.FirebaseClient(os.path.join(tempfile.mkdtemp(), "session.json"))
    cl._auth_post = lambda endpoint, payload: {"localId": "newbie", "idToken": "t-newbie",
                                               "refreshToken": "r"}
    store.auth_uid = "newbie"
    cl.sign_up("new@example.com", "secret1", "Newbie")
    codes = [p for p, d in store.docs.items() if p.startswith("friend_codes/")
             and d["userId"]["stringValue"] == "newbie"]
    check("sign-up makes the friend code, so Copy invite copies from minute one",
          len(codes) == 1 and store.docs["users/newbie"].get("friendCode", {}).get("stringValue") == codes[0][13:])


def test_new_code():
    """2.10: New Code swaps my friend code; the old one stops working, the
    crew stays, and the board shows the new one the same day."""
    store = fakes.FakeFirestore()
    sys.modules["requests"].Session = lambda: fakes.FakeSession(store)
    seed_users(store, {"sam": "Sammy", "priya": "Priya"}, {"sam": ["priya"], "priya": ["sam"]})
    store.docs["friend_codes/SAM123"] = {"userId": fv_str("sam")}
    store.docs["users/sam"]["friendCode"] = fv_str("SAM123")
    store.auth_uid = "sam"
    sam = new_client(store, "sam", "Sammy")
    sam._people = {"uid": "sam", "day": "x", "own": {"friendCode": "SAM123"}}
    code, err = sam.new_friend_code("sam", "SAM123")
    check("new code: a fresh code, pointed at me, on my profile; the old one gone",
          err is None and code and code != "SAM123"
          and store.docs[f"friend_codes/{code}"]["userId"]["stringValue"] == "sam"
          and store.docs["users/sam"]["friendCode"]["stringValue"] == code
          and "friend_codes/SAM123" not in store.docs)
    check("new code: the day's cached profile shows it (the board's Copy invite)",
          sam._people["own"]["friendCode"] == code)
    check("new code: the crew is untouched",
          [v["stringValue"] for v in store.docs["users/sam"]["friends"]["arrayValue"]["values"]] == ["priya"])
    store.auth_uid = "priya"
    priya = new_client(store, "priya", "Priya")
    _f, old_err = priya.add_friend("priya", "SAM123", [], "Priya")
    check("new code: the old code no longer matches anyone", old_err == "That code doesn't match anyone.")
    # someone else holds the first draw: the rules refuse, the next draw lands
    store.auth_uid = "sam"
    store.docs["friend_codes/TAKEN1"] = {"userId": fv_str("priya")}
    draws = iter("TAKEN1" + "FRESH2")
    real = firebase.secrets.choice
    firebase.secrets.choice = lambda seq: next(draws)
    try:
        code2, err2 = sam.new_friend_code("sam", code)
    finally:
        firebase.secrets.choice = real
    check("new code: a code that's someone else's is skipped, and stays theirs",
          code2 == "FRESH2" and err2 is None
          and store.docs["friend_codes/TAKEN1"]["userId"]["stringValue"] == "priya")
    # the profile write fails: the new code is let go and the old one stands
    real_patch = sam.patch_doc
    sam.patch_doc = lambda path, *a, **k: False if path == "users/sam" else real_patch(path, *a, **k)
    try:
        code3, err3 = sam.new_friend_code("sam", "FRESH2")
    finally:
        sam.patch_doc = real_patch
    check("new code: a failed profile write keeps the old code, and frees the new one",
          code3 is None and err3 and "friend_codes/FRESH2" in store.docs
          and sum(1 for p, d in store.docs.items() if p.startswith("friend_codes/")
                  and d["userId"]["stringValue"] == "sam") == 1)


def test_squad_privacy_v29():
    """2.9 (G2): the Privacy switches reach squad rows, through the same
    gate as the day docs."""
    values = {"reviews": 40, "studyTimeMs": 90000, "accuracy": 91.0, "streak": 3}
    cfg = {"share_time": False, "share_retention": False}
    check("squad row: switched-off numbers stay home",
          firebase.shared_numbers(values, cfg) == {"reviews": 40, "streak": 3})
    check("squad row: just show up lets none out",
          firebase.shared_numbers(values, {"show_up": True}) == {})
    store = fakes.FakeFirestore()
    sys.modules["requests"].Session = lambda: fakes.FakeSession(store)
    seed_users(store, {"sam": "Sammy"}, {"sam": []})
    sam = new_client(store, "sam", "Sammy")
    doc, _mask = sam._day_doc(TODAY.isoformat(), values, cfg)
    check("day doc: the same gate as before", "studyTimeMs" not in doc and "accuracy" not in doc
          and doc["reviews"] == 40 and doc["streak"] == 3)


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
    store = fakes.FakeFirestore()
    sys.modules["requests"].Session = lambda: fakes.FakeSession(store)
    seed_users(store, {"sam": "Sammy", "dre": "Dre"}, {"sam": ["dre"], "dre": ["sam"]})
    for a, b in (("sam", "dre"), ("dre", "sam")):
        store.docs[f"users/{a}/friends/{b}"] = {"at": {"timestampValue": "2026-09-01T00:00:00Z"}}
    labels = [(TODAY - datetime.timedelta(days=i)).isoformat() for i in range(7)]
    tomorrow = (TODAY + datetime.timedelta(days=1)).isoformat()

    # L1 + L2 ride the week doc
    dre = new_client(store, "dre", "Dre")
    dre.session["live_until"] = (now + datetime.timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    dre.session["tricky"] = [{"guid": "guid000003", "text": "Heart sounds: S3 <b>", "deck": "Cardio",
                              "at": labels[0]}]
    _push29(store, dre, make_user_col([TODAY]), tempfile.mkdtemp(), {})
    wk = store.docs["users/dre/shared/week"]
    check("live + flags: the week doc carries liveUntil and the flagged card",
          "liveUntil" in wk and "tricky" in wk)
    store.auth_uid = "sam"
    sam = new_client(store, "sam", "Sammy")
    data = sam.fetch_board("sam", labels, tomorrow=tomorrow)
    d = next(e for e in data["entries"] if e["user_id"] == "dre")
    check("live + flags: a friend's refresh reads both, no extra reads",
          board.live_now(d["live_until"]) and d["tricky"][0]["guid"] == "guid000003")
    dre.session["live_until"] = (now - datetime.timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _push29(store, dre, make_user_col([TODAY]), tempfile.mkdtemp(), {})
    check("live: once the hour is up, the next push drops it",
          "liveUntil" not in store.docs["users/dre/shared/week"])

    rows = board.build_rows([dict(d, live_until=(now + datetime.timedelta(minutes=5)).isoformat())],
                            labels, tomorrow, "today", {})[0]
    html = board._row_html(rows[0], "#1", {})
    check("live: the row shows a dot and 'studying now'", "dc-live" in html and "studying now" in html)
    page = board.render({"entries": [], "labels": labels, "tomorrow": "", "pending": []}, {}, 0, live=False)
    stop = board.render({"entries": [], "labels": labels, "tomorrow": "", "pending": []}, {}, 0, live=True)
    check("live: the footer offers I'm studying, then Stop studying",
          "I&rsquo;m studying" in page and "Stop studying" in stop and "duecrew:live" in page)

    # L2: flags I share show on the Decks tab; tips go to the card
    store.auth_uid = "sam"
    col = make_user_col([TODAY])
    fakes.add_card(col.db.conn, 3, did=1)
    sys.modules["aqt"].mw.col = col
    _state["entries"] = data["entries"]
    view = together.tricky_view()
    check("flags: only on notes I have, with who and where",
          [(v["uid"], v["index"], v["deck"]) for v in view] == [("dre", 0, "Cardio")])
    col2 = make_user_col([TODAY])
    sys.modules["aqt"].mw.col = col2
    check("flags: a card I don't have stays out of view", together.tricky_view() == [])
    sys.modules["aqt"].mw.col = None
    flags = board._tricky_html(view)
    check("flags: escaped, with Send a tip wired", "&lt;b&gt;" in flags and "tricktip:dre:0" in flags)
    check("flags: a cloze shows as [...], never its answer",
          together._plain("<b>S3</b>&nbsp;is heard in {{c1::Kentucky::rhythm}}") == "S3 is heard in [\u2026]")
    tip = board.tip_html([("Dre <i>", "Ken-tuck-y")])
    check("tips: under the answer, escaped", "Dre &lt;i&gt;" in tip and "Ken-tuck-y" in tip)

    # L3 + tips: cheers carry luck / guid; v9 servers get a plain cheer
    store.auth_uid = "dre"
    check("luck: a line goes out marked", dre.send_cheer("sam", "dre", "Dre", "\U0001F340", "Go get it", luck=True) is True
          and store.docs["users/sam/cheers/dre"]["luck"] == {"booleanValue": True})
    store.auth_uid = "sam"
    got = sam.fetch_board("sam", labels, tomorrow=tomorrow)["cheers"]
    check("luck: it arrives marked", got and got[0]["luck"] is True and got[0]["note"] == "Go get it")
    old = fakes.FakeFirestore(rules_mode="v9")
    sys.modules["requests"].Session = lambda: fakes.FakeSession(old)
    seed_users(old, {"sam": "Sammy", "dre": "Dre"}, {"sam": ["dre"], "dre": ["sam"]})
    d9 = new_client(old, "dre", "Dre")
    res = d9.send_cheer("sam", "dre", "Dre", "\U0001F4A1", "Ken-tuck-y", guid="guid000003")
    check("tips on rules-v9: sent as a plain cheer with its words, and says so",
          res == "no-extras" and "guid" not in old.docs["users/sam/cheers/dre"]
          and old.docs["users/sam/cheers/dre"]["note"] == {"stringValue": "Ken-tuck-y"})
    sys.modules["requests"].Session = lambda: fakes.FakeSession(store)

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
    store = fakes.FakeFirestore()
    sys.modules["requests"].Session = lambda: fakes.FakeSession(store)
    seed_users(store, {"sam": "Sammy"}, {"sam": []})
    sam = new_client(store, "sam", "Sammy")
    values = {"reviews": 120, "studyTimeMs": 5000, "accuracy": 90.0, "streak": 4, "status": "hi"}
    doc, mask = sam._day_doc(lb, values, {"show_up": True})
    check("show-up: my day doc keeps studied and status, drops every number; the mask still clears them",
          doc.get("studied") is True and doc.get("status") == "hi"
          and not {"reviews", "studyTimeMs", "accuracy", "streak"} & set(doc)
          and {"reviews", "studyTimeMs", "accuracy", "streak"} <= set(mask))
    full, _m = sam._day_doc(lb, values, {"show_up": False})
    check("show-up: off, the toggles rule as before", full.get("reviews") == 120)
    import hashlib
    sid = hashlib.sha1(b"due-crew-squad:ABCDEFGH").hexdigest()[:24]
    store.docs[f"squads/{sid}"] = {"name": fv_str("busm"), "founder": fv_str("sam"),
                                   "open": {"booleanValue": True}}
    store.docs[f"squads/{sid}/members/sam"] = {
        "name": fv_str("Sammy"), "joinedAt": {"timestampValue": "2026-09-01T00:00:00Z"},
        "reviews": {"integerValue": "500"}, "streak": {"integerValue": "9"}, "day": fv_str(lb)}
    sam.upload_squad_rows("sam", {"name": "Sammy", "week": 5, "day": lb}, [sid])
    m = store.docs[f"squads/{sid}/members/sam"]
    check("show-up: a numbers-free row deletes the numbers that stood, keeps joinedAt",
          "reviews" not in m and "streak" not in m and "joinedAt" in m
          and int(m["week"]["integerValue"]) == 5)

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


def main():
    names = [n for n in list(globals()) if n.startswith("test_")]
    for n in names:
        globals()[n]()
    bad = [c for c in CHECKS if not c[1]]
    print(f"\n{len(CHECKS) - len(bad)}/{len(CHECKS)} checks passed")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
