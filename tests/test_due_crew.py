"""End-to-end tests for Due Crew against fake anki + strict fake Firestore.

Run: python3 test_due_crew.py
"""

import datetime
import os
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
          "Server rules need an update" in html and "duecrew:rules" in html)
    two = b.render(data, {}, 0, exam_eve={"people": [("p1", "Priya"), ("p2", "Theo")]})
    check("exam eve: two exams merge into one line",
          two.count("dc-wrap eve") == 1 and "have exams tomorrow" in two)


def _opt_in(store, uid):
    store.docs[f"users/{uid}"]["openBoard"] = {"booleanValue": True}


KEY_A = "a" * 40
KEY_B = "b" * 40
ROW = {"name": "Sammy", "day": "2026-09-01", "dayStart": 1756717200,
       "reviews": 512, "studyTimeMs": 4320000, "streak": 12}


def test_server_board_flow():
    """Rows live under the crew key; reads are crew-scoped AND symmetric;
    opt-out retracts; membership is created once, by path."""
    store = fakes.FakeFirestore()
    sys.modules["requests"].Session = lambda: fakes.FakeSession(store)
    seed_users(store, {"sam": "Sammy", "dre": "Dre", "eve": "Eve", "zed": "Zed"},
               {"sam": [], "dre": [], "eve": [], "zed": []})
    for u in ("sam", "dre", "eve"):
        _opt_in(store, u)
    sam = new_client(store, "sam", "Sammy")
    ok1 = sam.upload_board_row(KEY_A, "sam", ROW)
    n0 = sum(1 for m, pth, st in store.log if pth == f"servers/{KEY_A}/board/sam" and m == "PATCH")
    ok2 = sam.upload_board_row(KEY_A, "sam", ROW)
    n1 = sum(1 for m, pth, st in store.log if pth == f"servers/{KEY_A}/board/sam" and m == "PATCH")
    members = sum(1 for m, pth, st in store.log if "/members/" in pth and m == "PATCH")
    check("board: row upserts once under the crew key, hash skips repeats",
          ok1 and ok2 and n0 == 1 and n1 == 1 and members == 1)
    dre = new_client(store, "dre", "Dre")
    dre.ensure_membership(KEY_A, "dre")
    rows = dre.fetch_server_board(KEY_A)
    check("board: a sharing member of the same crew sees the row",
          len(rows) == 1 and rows[0]["name"] == "Sammy" and rows[0]["day_start"] == ROW["dayStart"])

    def denied(cl, key):
        try:
            cl.fetch_server_board(key)
            return False
        except firebase.TransportError:
            return True
    eve = new_client(store, "eve", "Eve")
    eve.ensure_membership(KEY_B, "eve")            # sharing, but on crew B
    check("board: a sharer on ANOTHER crew is denied crew A", denied(eve, KEY_A))
    zed = new_client(store, "zed", "Zed")
    zed.ensure_membership(KEY_A, "zed")            # member, but not sharing
    check("board: a member who is not sharing cannot peek", denied(zed, KEY_A))
    check("board: a non-member cannot write a row into crew A",
          not zed.patch_doc(f"servers/{KEY_B}/board/zed", ROW, label="x"))
    store.auth_uid = "sam"
    sam.delete_board_row("sam")
    check("board: opt-out deletes the row under the key it was written to",
          f"servers/{KEY_A}/board/sam" not in store.docs
          and f"servers/{KEY_A}/members/sam" in store.docs)


def test_crew_scoping_by_path():
    """Two crews on one project never see each other; membership can only
    be created for yourself, and only under a key you can name."""
    store = fakes.FakeFirestore()
    sys.modules["requests"].Session = lambda: fakes.FakeSession(store)
    seed_users(store, {"sam": "Sammy", "kim": "Kim"}, {"sam": [], "kim": []})
    _opt_in(store, "sam"); _opt_in(store, "kim")
    sam = new_client(store, "sam", "Sammy")
    sam.upload_board_row(KEY_A, "sam", ROW)
    kim = new_client(store, "kim", "Kim")
    kim.upload_board_row(KEY_B, "kim", dict(ROW, name="Kim"))
    a_rows = [r["name"] for r in kim.fetch_server_board(KEY_B)]
    try:
        kim.fetch_server_board(KEY_A)
        crossed = True
    except firebase.TransportError:
        crossed = False
    forged = kim.patch_doc(f"servers/{KEY_A}/members/sam",
                           {"at": {"timestampValue": "t"}}, label="x")
    check("scoping: each crew sees only itself", a_rows == ["Kim"] and not crossed)
    check("scoping: cannot create a membership for someone else", not forged)


def test_old_rules_new_client():
    """A v1.10 client on a project still running the v1.8/1.9 rules: the
    board fails closed and the tripwire says the rules are stale."""
    store = fakes.FakeFirestore(rules_mode="v3")
    sys.modules["requests"].Session = lambda: fakes.FakeSession(store)
    seed_users(store, {"sam": "Sammy"}, {"sam": []})
    _opt_in(store, "sam")
    sam = new_client(store, "sam", "Sammy")
    wrote = sam.upload_board_row(KEY_A, "sam", ROW)
    try:
        sam.fetch_server_board(KEY_A)
        read = True
    except firebase.TransportError:
        read = False
    check("old rules: v1.10 cannot write or read the scoped board", not wrote and not read)
    check("old rules: the v4 marker probe flags stale", sam.check_rules("2026-09-01") is True)


def test_old_row_retirement():
    store = fakes.FakeFirestore()
    sys.modules["requests"].Session = lambda: fakes.FakeSession(store)
    seed_users(store, {"sam": "Sammy"}, {"sam": []})
    store.docs["server_board/sam"] = {"name": fv_str("Sammy")}
    sam = new_client(store, "sam", "Sammy")
    sam.retire_old_board_row("sam")
    sam.retire_old_board_row("sam")
    deletes = sum(1 for m, pth, st in store.log if pth == "server_board/sam" and m == "DELETE")
    check("retirement: the unscoped v1.8 row is deleted once",
          "server_board/sam" not in store.docs and deletes == 1)


def test_alias_and_key():
    """Join lookups hand back the crew key — the name's own, or the crew it
    was registered as an alias of — and keys normalize name/code."""
    from due_crew.backend import directory
    store = fakes.FakeFirestore()
    sys.modules["requests"].Session = lambda: fakes.FakeSession(store)
    sys.modules["requests"].request = lambda m, u, **kw: fakes.FakeSession(
        store).request(m, u, headers=kw.get("headers"), json=kw.get("json"))
    k1 = directory.crew_key("busm", "ABC123")
    check("key: normalizes case and whitespace",
          k1 == directory.crew_key(" BUSM ", "abc123") and len(k1) == 40)
    own = directory.crew_key("busm-2027", "ZZZ999")
    store.docs[f"servers/{own}"] = {"apiKey": fv_str("k"), "projectId": fv_str("p"),
                                   "name": fv_str("busm-2027"), "crewKey": fv_str(k1)}
    conf = directory.lookup_server("busm-2027", "ZZZ999")
    check("alias: joining the new name lands on the original crew's key",
          conf and conf["key"] == k1 and conf["name"] == "busm-2027")
    plain = directory.crew_key("solo", "111111")
    store.docs[f"servers/{plain}"] = {"apiKey": fv_str("k"), "projectId": fv_str("p"),
                                     "name": fv_str("solo")}
    conf2 = directory.lookup_server("solo", "111111")
    check("alias: a plain name keys itself", conf2 and conf2["key"] == plain)


def test_knock_flow():
    """Knocks need both memberships in the named crew and both sharing;
    names come from profiles, not the doc."""
    store = fakes.FakeFirestore()
    sys.modules["requests"].Session = lambda: fakes.FakeSession(store)
    seed_users(store, {"sam": "Sammy", "dre": "Dre", "eve": "Eve", "kim": "Kim"},
               {"sam": [], "dre": [], "eve": [], "kim": []})
    for u in ("sam", "dre", "eve", "kim"):
        _opt_in(store, u)
    for u, key in (("sam", KEY_A), ("dre", KEY_A), ("kim", KEY_B)):
        c = new_client(store, u)
        c.ensure_membership(key, u)
    dre = new_client(store, "dre", "Dre")
    ok = dre.send_knock("sam", "dre", "TOTALLY FAKE NAME", KEY_A)
    kim = new_client(store, "kim", "Kim")
    cross = kim.send_knock("sam", "kim", "Kim", KEY_B)      # kim's crew, sam isn't in it
    cross2 = kim.send_knock("sam", "kim", "Kim", KEY_A)     # sam's crew, kim isn't in it
    eve = new_client(store, "eve", "Eve")
    nomember = eve.send_knock("sam", "eve", "Eve", KEY_A)   # sharing, no membership
    sam = new_client(store, "sam", "Sammy")
    knocks = sam.list_knocks("sam")
    sam.delete_knock("sam", "dre")
    left = sam.list_knocks("sam")
    check("knock: same crew, both sharing -> allowed", ok)
    check("knock: cross-crew and non-member knocks are rejected",
          not cross and not cross2 and not nomember)
    check("knock: names come from profiles (no spoofing)", knocks == [("dre", "Dre")], str(knocks))
    check("knock: delete clears it", left == [])


def test_marker_compat():
    """Cumulative markers: old clients stay green on newer rules; a new
    client flags older rules."""
    v4 = fakes.FakeFirestore(rules_mode="repo")
    sys.modules["requests"].Session = lambda: fakes.FakeSession(v4)
    seed_users(v4, {"sam": "Sammy"}, {"sam": []})
    cl = new_client(v4, "sam", "Sammy")
    check("markers: v4 client current on v4 rules", cl.check_rules("2026-09-01") is False)
    check("markers: v1.7 (v2) and v1.8 (v3) probes still 404 on v4 rules",
          cl._req("GET", f"{cl.base}/meta/rules-v2").status_code == 404
          and cl._req("GET", f"{cl.base}/meta/rules-v3").status_code == 404)
    v3 = fakes.FakeFirestore(rules_mode="v3")
    sys.modules["requests"].Session = lambda: fakes.FakeSession(v3)
    seed_users(v3, {"sam": "Sammy"}, {"sam": []})
    cl3 = new_client(v3, "sam", "Sammy")
    check("markers: v4 client flags v3 rules as stale", cl3.check_rules("2026-09-01") is True)


def test_server_view_html():
    from due_crew import board as b
    rows = [
        {"user_id": "u1", "name": "StepQueen <s>", "day": "2026-09-01",
         "reviews": 1412, "time_ms": 10920000, "streak": 88},
        {"user_id": "sam", "name": "Sammy", "day": "2026-09-01",
         "reviews": 512, "time_ms": 4320000, "streak": 12, "you": True},
        {"user_id": "u2", "name": "Maya", "day": "2026-09-01",
         "reviews": 488, "time_ms": 3900000, "streak": 31, "pending": True},
    ]
    html = b._server_html({"state": "ok", "rows": rows, "server": "busm"}, {})
    optin = b._server_html({"state": "optin", "server": "busm"}, {})
    check("server view: plain ranks, no medals, no cheers",
          "#1" in html and "&#129351;" not in html and "dc-cheer" not in html)
    check("server view: names escaped, card command wired, knocked note",
          "StepQueen &lt;s&gt;" in html and "scard:u1" in html
          and "knocked" in html)
    check("server view: opt-in card gates non-sharers",
          "Privacy" in optin and "scard" not in optin)


def test_stranger_card():
    from due_crew import board as b
    js = b.stranger_card_js({"uid": "u1", "name": "Maya <m>", "reviews": 488,
                             "time_ms": 3900000, "streak": 31, "pending": False})
    pend = b.stranger_card_js({"uid": "u1", "name": "Maya", "reviews": 488,
                               "time_ms": 3900000, "streak": 31, "pending": True})
    check("stranger card: escaped, Add knocks, no cheer/heatmap",
          "Maya \\u003cm\\u003e" in js or "Maya &lt;m&gt;" in js)
    check("stranger card: Add wired to knock", "duecrew:knock:u1" in js)
    check("stranger card: pending has no action command", '"duecrew:knock' not in pend)


def test_deletion_sweep():
    store = fakes.FakeFirestore()
    real_post = fakes.FakeSession.post
    fakes.FakeSession.post = lambda self, url, **kw: fakes.FakeResponse(200, {})
    try:
        sys.modules["requests"].Session = lambda: fakes.FakeSession(store)
        seed_users(store, {"sam": "Sammy", "dre": "Dre"},
                   {"sam": ["dre"], "dre": ["sam"]})
        _opt_in(store, "sam"); _opt_in(store, "dre")
        sam = new_client(store, "sam", "Sammy")
        sam.upload_board_row(KEY_A, "sam", ROW)
        dre = new_client(store, "dre", "Dre")
        dre.ensure_membership(KEY_A, "dre")
        dre.send_knock("sam", "dre", "Dre", KEY_A)
        store.auth_uid = "sam"
        sam.delete_account("sam", None)
        check("deletion: board row, membership, and knocks are swept",
              f"servers/{KEY_A}/board/sam" not in store.docs
              and f"servers/{KEY_A}/members/sam" not in store.docs
              and not any(p.startswith("users/sam/knocks/") for p in store.docs))
    finally:
        fakes.FakeSession.post = real_post


def test_rename_follow():
    """Founder renames via console: members follow; junk targets don't."""
    store = fakes.FakeFirestore()
    sys.modules["requests"].Session = lambda: fakes.FakeSession(store)
    sys.modules["requests"].request = lambda m, u, **kw: fakes.FakeSession(
        store).request(m, u, headers=kw.get("headers"), json=kw.get("json"))
    from due_crew.backend import directory
    store.docs["server_names/breezy-newt-6261"] = {
        "createdAt": {"timestampValue": "t"},
        "renamedTo": {"stringValue": "busm"}}
    store.docs["server_names/busm"] = {"createdAt": {"timestampValue": "t"},
                                       "custom": {"booleanValue": True}}
    store.docs["server_names/oldname"] = {
        "createdAt": {"timestampValue": "t"},
        "renamedTo": {"stringValue": "BAD NAME!!"}}
    check("rename: members follow the console rename",
          directory.follow_rename("breezy-newt-6261") == "busm")
    check("rename: no rename means None",
          directory.follow_rename("busm") is None)
    check("rename: invalid targets are ignored",
          directory.follow_rename("oldname") is None)
    check("rename: unknown server is None",
          directory.follow_rename("nope") is None)


def test_shares():
    """The three paste-ready shares, exact text — reviews, not cards."""
    from due_crew import share
    hourly = [0] * 24
    hourly[7], hourly[8], hourly[12], hourly[20], hourly[21] = 40, 22, 5, 30, 60
    tape = share.my_today_tape(512, 4320000, 17, 91.6, hourly)
    spark = share.my_today_spark(512, 4320000, 17, 91.6, hourly)
    check("share: tape has the stat split, AM/PM rows, footer, 'reviews'",
          tape.split("\n") == [
              "Today 📚 512 reviews · 1h 12m",
              "🌅 ⬜⬜⬜⬜⬜⬜⬜🟩🟩⬜⬜⬜",
              "🌙 🟨⬜⬜⬜⬜⬜⬜⬜🟩🟩⬜⬜",
              "🔥17 · 🎯 91.6%",
              share.FOOTER], tape)
    line = spark.split("\n")[1]
    body = line[len("🕐 "):]
    check("share: sparkline is 24 slots, ░ idle, █ at the peak",
          line.startswith("🕐 ") and len(body) == 24 and body[0] == "░"
          and body[7] == "▆" and body[8] == "▄" and body[12] in "▁▂"
          and body[21] == "█" and body[23] == "░", line)
    check("share: no retention -> streak only",
          share.my_today_spark(3, 60000, 1, None, hourly).split("\n")[2] == "🔥1")

    # crew: rows already on my timeline; one order, honest totals
    lv_a = share.hour_levels(hourly)
    lv_b = [0] * 24; lv_b[2] = 2; lv_b[3] = 2
    lv_c = [0] * 24; lv_c[14] = 1
    crew = share.crew_today("busm", [("sammy", lv_a), ("igk <b>\nx", lv_b),
                                     ("Ameya", lv_c), ("Quiet", [0] * 24)], 2841)
    rows = crew.split("\n")
    check("share: crew rows only for people with hours, ordered by first hour",
          rows[0] == "busm today 🕐" and len(rows) == 6
          and rows[1].endswith(" igk <b> x") and rows[2].endswith(" sammy")
          and rows[3].endswith(" Ameya"), crew)
    check("share: crew tape merges hour pairs and counts covered hours",
          rows[1].startswith("⬜🟩⬜") and rows[3].startswith("⬜⬜⬜⬜⬜⬜⬜🟨")
          and rows[4] == "we covered 8 hours · 2,841 reviews", crew)
    honest = share.crew_today("busm", [("sammy", lv_a)], 512, partial=True, unshared=2)
    check("share: missing data is named, never drawn as idle",
          honest.split("\n")[2] == "we covered 5 hours · 512 reviews (partial) · 2 not sharing hours",
          honest)
    check("share: nobody with hours -> None",
          share.crew_today("busm", [("a", [0] * 24)], 0) is None)
    check("share: malformed hours strings are rejected",
          share.levels_from_str("0" * 24) == [0] * 24
          and share.levels_from_str("3" * 24) is None
          and share.levels_from_str("01") is None)

    # projection: a friend three hours ahead lands three slots later on my day
    theirs = [0] * 24; theirs[0] = 2; theirs[22] = 1
    mine_start = 1_000_000
    placed = share.project_levels(theirs, mine_start + 3 * 3600, mine_start)
    check("share: friends' hours are placed by absolute time on my day",
          placed[3] == 2 and sum(placed) == 2 and placed[22] == 0 and placed[23] == 0, str(placed))
    check("share: unknown day start -> nothing is placed (never faked as zero)",
          share.project_levels(theirs, None, mine_start) == [0] * 24)


def test_hours_upload():
    """hours rides the daily doc under share_time; off deletes it."""
    store = fakes.FakeFirestore()
    sys.modules["requests"].Session = lambda: fakes.FakeSession(store)
    seed_users(store, {"sam": "Sammy", "dre": "Dre"}, {"sam": ["dre"], "dre": ["sam"]})
    conn = sqlite3.connect(":memory:")
    fakes.make_collection(conn)
    for hour, n in ((7, 20), (21, 3)):
        base = int(datetime.datetime.combine(TODAY, datetime.time(hour)).timestamp() * 1000)
        for i in range(n):
            fakes.add_review(conn, base + i * 1000, ease=3)
    col = fakes.FakeCol(conn, fakes.day_cutoff_for(TODAY))
    sam = new_client(store, "sam", "Sammy")
    files = tempfile.mkdtemp()
    sync_once(store, sam, col, files, {}, TODAY)
    doc = store.docs.get(f"users/sam/daily_stats/{TODAY.isoformat()}", {})
    hours = doc.get("hours", {}).get("stringValue")
    day_start = doc.get("dayStart", {}).get("integerValue")
    expected_start = fakes.day_cutoff_for(TODAY) - 86400
    check("hours: 24 levels anchored on the 4 AM rollover (7am -> slot 3, 9pm -> slot 17)",
          hours is not None and len(hours) == 24 and hours[3] == "2"
          and hours[17] == "1" and hours[7] == "0", str(hours))
    check("hours: the day start rides along so friends can place the hours",
          day_start is not None and int(day_start) == expected_start, str(day_start))
    sync_once(store, sam, col, files, {"share_time": False}, TODAY)
    doc = store.docs.get(f"users/sam/daily_stats/{TODAY.isoformat()}", {})
    check("hours: share_time off removes it server-side", "hours" not in doc)
    store.auth_uid = "sam"
    sync_once(store, sam, col, files, {}, TODAY)   # share_time back on
    dre = new_client(store, "dre", "Dre")          # switches auth to dre
    data, labels, _t = fetch_as(store, dre, make_user_col([TODAY]))
    sam_entry = next(e for e in data["entries"] if e["user_id"] == "sam")
    got = (sam_entry["days"].get(labels[0]) or {}).get("hours") or ""
    ds = (sam_entry["days"].get(labels[0]) or {}).get("dayStart")
    check("hours: friends receive hours + dayStart cleaned",
          len(got) == 24 and got[3] == "2" and isinstance(ds, int) and ds > 0, got)


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


def main():
    test_payload_shapes()
    test_rules_drift_reproduces_live_state()
    test_dots_gap()
    test_backfill_costs()
    test_studied_field_privacy()
    test_heatmap_roundtrip()
    test_heatmap_retraction()
    test_rules_probe()
    test_duet_runs()
    test_welcome_back()
    test_milestones()
    test_exam_eve_and_rules_render()
    test_server_board_flow()
    test_crew_scoping_by_path()
    test_old_rules_new_client()
    test_old_row_retirement()
    test_alias_and_key()
    test_knock_flow()
    test_marker_compat()
    test_server_view_html()
    test_stranger_card()
    test_deletion_sweep()
    test_rename_follow()
    test_shares()
    test_hours_upload()
    test_copy_text()
    bad = [c for c in CHECKS if not c[1]]
    print(f"\n{len(CHECKS) - len(bad)}/{len(CHECKS)} checks passed")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
