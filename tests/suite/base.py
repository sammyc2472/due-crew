"""The suite's world: the fake server, the stand-in Anki, the helpers every test leans on."""


import datetime
import os
import sqlite3
import sys
import tempfile

# 3.9.12: the suite is a package of parts (tests/suite/); a test that reads a file beside the suite
# still names it from tests/test_due_crew.py, where they all were
SUITE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "test_due_crew.py")
HARNESS = os.path.dirname(SUITE_FILE)
REPO = os.path.dirname(HARNESS)
sys.path.insert(0, HARNESS)

import fakes

STORE = fakes.FakeWorker()
fakes.install_fake_requests(STORE)
fakes.install_fake_aqt()
sys.path.insert(0, REPO)

from due_crew import board                                    # noqa: E402
from due_crew.backend import api                      # noqa: E402
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
BOARD_DREW = {}  # every duecrew: command the board drew a control for (board._pycmd), across the suite: routed at the end


def _record_board_commands():
    """Each command as the page sends it (what _pycmd keeps of it), with the
    part of the board that drew it; check_every_board_click_is_taken sends
    them down the board's own route."""
    import inspect
    real = board._pycmd

    def seen(cmd):
        out = real(cmd)
        at = inspect.currentframe().f_back
        if os.sep + os.path.join("due_crew", "board") + os.sep in at.f_code.co_filename:  # the board's own, not a test's own call
            BOARD_DREW.setdefault(out[len("pycmd('"):].split("|")[0], f"{os.path.basename(at.f_code.co_filename)}:{at.f_code.co_name}")
        return out
    board._pycmd = seen  # each part of the board that has it (board._Board)


_record_board_commands()


KK = board.BOARD_KEY  # 3.9.1: what the Decks page's own commands carry


def as_board(message):
    """A message as the Decks page sends it (3.9.1): with the board's key,
    unless it carries a widget's own."""
    from due_crew import board as _b
    return message if "|" in message else message + "|" + _b.BOARD_KEY


QUIET = [False]  # -q: only what failed is said


def check(name, cond, detail=""):
    CHECKS.append((name, bool(cond), detail))
    if cond and QUIET[0]:
        return
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))
