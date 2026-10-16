"""3.9.0: the Backlog Beast, the glue (beast.py says what it is; board draws
it). At each refresh: the beast now counts its cards reviewed a day or
more ahead (on any device: Anki's history, after an AnkiWeb sync) and the
ones that left it; once an Anki day with none, a look at the pile for a
new one (rule B). Its cards stay on this computer (user_files/<profile>/
beast.json); another computer works them out from Anki's own history for
that morning. The account keeps the beast itself (`beast`), so every
computer has the same one.

Study: your own deck, the top one holding most of its cards left (Sam's
round 3: no deck of its own); Anki's order puts the most overdue first.
Study as many as you like.

Main thread: the collection and the config. No network here: what my crew
sees rides my week (api.week_doc, session["beast"]).
"""

import datetime
import json
import os
import traceback

from aqt import mw

from . import beast as B
from .app import _profile_files, _state, cfg, client, save_cfg

KEY = "beast"  # the account's (account.ACCOUNT_KEYS)
ON_KEY = "beasts"  # the account's: beasts at all (Settings; the beast's Not for me)
SHARE_KEY = "share_beast"  # the account's: My beast, in Privacy
FILE = "beast.json"
DECK_DAY = "beast_deck_day"  # plans.json: set by 3.9.0's test builds, which built a deck of its cards
OLD_DECKS = ("The Snoozasaurus", "The Overdue Owl", "The Leech Lord", "The Pile", "The Backlog Beast")
CHUNK = 500


def state(c=None):
    """The account's beast, with what's been counted of it here since (its
    hits and cards gone stay on this computer: every computer counts them
    from Anki's history, so a review never costs a request)."""
    s = B.clean((c or cfg()).get(KEY))
    n, k = s.get("now"), _state.get("beast_count")
    if n and k and k.get("day") == n["day"]:
        s["now"] = dict(n, hit=min(n["size"], max(n["hit"], k["hit"])), gone=min(n["size"], k["gone"]))
    return s


def _save(s):
    c = dict(cfg())
    c[KEY] = B.clean(s)
    save_cfg(c)


def on(c=None):
    """Beasts at all: ready (beast.READY, off in 3.9.0), Settings' switch, not turned off."""
    c = c or cfg()
    return B.READY and bool(c.get(ON_KEY, True)) and not B.clean(c.get(KEY)).get("off")


# ---- the collection ----

def _cut(col):
    cut = int(col.sched.day_cutoff)
    today = datetime.date.fromtimestamp(cut) - datetime.timedelta(days=1)
    return cut, today


def _day_start_ms(col, day):
    """When an Anki day began, in revlog's ms."""
    cut, today = _cut(col)
    return (cut - 86400 * ((today - datetime.date.fromisoformat(str(day))).days + 1)) * 1000


def day_counts(col, days=B.USUAL_WINDOW + 1):
    """{Anki day: reviews} for the last few weeks, one grouped query."""
    cut, today = _cut(col)
    rows = col.db.all("SELECT CAST((? - id / 1000) / 86400 AS INTEGER), COUNT(*) FROM revlog "
                      "WHERE ease > 0 AND id >= ? GROUP BY 1", cut - 1, (cut - 86400 * days) * 1000)
    return {(today - datetime.timedelta(days=int(d))).isoformat(): int(n) for d, n in rows or []}


def studied_decks(col, days=B.DECK_DAYS):
    cut, _t = _cut(col)
    return {int(d) for (d,) in col.db.all(
        "SELECT DISTINCT CASE WHEN c.odid THEN c.odid ELSE c.did END FROM revlog r JOIN cards c ON c.id = r.cid "
        "WHERE r.ease > 0 AND r.id >= ?", (cut - 86400 * days) * 1000) or []}


def pile(col):
    """The pile: review cards due before today (in a Due Crew deck, by their
    home deck's due) in decks studied lately: [(card id, days overdue,
    interval, lapses)]."""
    today = int(col.sched.today)
    decks = studied_decks(col)
    rows = col.db.all("SELECT id, CASE WHEN odid THEN odid ELSE did END, CASE WHEN odid THEN odue ELSE due END, ivl, lapses "
                      "FROM cards WHERE queue = 2 AND (CASE WHEN odid THEN odue ELSE due END) < ?", today)
    return [(int(c), today - int(due), max(1, int(ivl or 1)), int(lapses or 0)) for c, did, due, ivl, lapses in rows or []
            if int(did) in decks]


def derive(col, now):
    """Another computer's beast: its cards, worked out from Anki's history
    for its morning (the last review before then left each one due before
    it), the most overdue for their interval first, as many as it has."""
    s_ms = _day_start_ms(col, now["day"])
    rows = col.db.all("SELECT r.cid, r.id, r.ivl FROM revlog r JOIN (SELECT cid, MAX(id) AS m FROM revlog "
                      "WHERE id < ? AND ease > 0 GROUP BY cid) l ON r.id = l.m WHERE r.ivl > 0", s_ms)
    decks = studied_decks(col)
    home = {}
    ids = [int(r[0]) for r in rows or []]
    for i in range(0, len(ids), CHUNK):
        chunk = ",".join(str(c) for c in ids[i:i + CHUNK])
        for cid, did in col.db.all(f"SELECT id, CASE WHEN odid THEN odid ELSE did END FROM cards WHERE id IN ({chunk}) "
                                   "AND queue >= 0 AND type = 2") or []:
            home[int(cid)] = int(did)
    cards = []
    for cid, rid, ivl in rows or []:
        before = (s_ms // 1000 - int(rid) // 1000) // 86400 + 1  # days before that morning it was reviewed
        if int(cid) in home and home[int(cid)] in decks and int(ivl) < before:
            cards.append((int(cid), before - int(ivl), int(ivl)))
    order = sorted(cards, key=lambda c: (-(c[1] / max(1, c[2])), -c[1], c[0]))
    return [c[0] for c in order[:int(now["size"])]]


def _file():
    return os.path.join(_profile_files(), FILE)


def cards(col, now):
    """The beast's cards: this computer's list, or worked out (and kept)."""
    try:
        with open(_file()) as f:
            d = json.load(f)
        if d.get("day") == now["day"] and isinstance(d.get("cids"), list):
            return [int(c) for c in d["cids"] if isinstance(c, int)]
    except Exception:
        pass
    ids = derive(col, now)
    _write(now["day"], ids)
    return ids


def _write(day, cids):
    tmp = _file() + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump({"day": day, "cids": list(cids)}, f)
        os.replace(tmp, _file())
    except Exception:
        traceback.print_exc()


def count(col, cids, day):
    """(hits, cards gone, the hits' ids). A hit: a review since its morning
    that sent the card a day or more ahead (Hard, Good, Easy; Again only
    once it's got right: Anki logs a learning step in seconds). It keeps
    counting after the card comes due again, so the beast never heals; a
    preview deck's review (ivl 0) is no hit. Gone (Sam's round 3): left it
    without one, so deleted, suspended, new again, or due tomorrow or
    later with no review (Set due date). Still to hit: the rest, overdue
    or due today, or in (re)learning after Again."""
    s_ms = _day_start_ms(col, day)
    today = int(col.sched.today)
    hit, waiting = set(), set()
    for i in range(0, len(cids), CHUNK):
        chunk = ",".join(str(int(c)) for c in cids[i:i + CHUNK])
        hit |= {int(c) for (c,) in col.db.all(
            f"SELECT DISTINCT cid FROM revlog WHERE id >= ? AND ease > 0 AND ivl > 0 AND cid IN ({chunk})", s_ms) or []}
        # learning queues (1, 3) and relearning (type 3) are still Again's; a review card's day number, due by today
        waiting |= {int(c) for (c,) in col.db.all(
            f"SELECT id FROM cards WHERE id IN ({chunk}) AND queue != -1 AND type != 0 AND (queue IN (1, 3) OR type = 3 "
            "OR (CASE WHEN odid THEN odue ELSE due END) <= ?)", today) or []}
    gone = {int(c) for c in cids} - hit - waiting
    return len(hit), len(gone), hit


# ---- at a refresh ----

def _away(c, t):
    """Away (Privacy's dates) or paused: no new beast."""
    from .backend.shapes import away_range
    rng = away_range(c)
    return bool(rng and rng[0] <= t <= rng[1]) or bool(c.get("paused"))


def check(today=None, look=True):
    """At a refresh and before a sync, on the main thread: count the beast
    now (its end, when it's beaten or gone quietly), else once a day look
    for a new one. look: False while the day's AnkiWeb sync hasn't come
    (a phone's reviews may not be here yet), as the plans' morning waits.
    The account is saved only when something changed. Returns the state."""
    col = mw.col
    if col is None:
        return {}
    c = cfg()
    s = state(c)
    if not on(c):
        return s  # beasts off (Settings): one here waits, uncounted, till they're back on
    try:
        _cut_, t = _cut(col)
        today = str(today or t.isoformat())
        now = s.get("now")
        if now:
            ids = cards(col, now)
            hit, gone, _h = count(col, ids, now["day"])
            _state["beast_count"] = {"day": now["day"], "hit": hit, "gone": gone}
            s2 = B.update(s, hit, gone, today)
            if not s2.get("now"):
                _save(s2)  # it ended: that the account keeps
                last = s2["met"][-1]
                if last["how"] == "beaten":  # one that went quietly says nothing (Sam's round 3)
                    _state["beast_news"] = {"k": last["k"], "how": last["how"], "day": today}
            return s2
        if not look or _state.get("beast_looked") == today:
            return s
        _state["beast_looked"] = today
        counts = day_counts(col, 60)
        usual = B.usual(counts, today)
        p = pile(col)
        if not B.should_turn_up(len(p), usual, s, today, _away(c, t)):
            return s
        ids, capped = B.pick([(cid, od, ivl) for cid, od, ivl, _l in p], usual, B.DEFAULT_PACE)
        k = B.kind(len(p), usual, sum(1 for *_x, lapses in p if lapses >= B.LEECH_LAPSES))
        s = dict(s, now=B.turn_up(today, k, ids, usual, B.DEFAULT_PACE, capped, len(p)))
        _write(today, ids)
        _save(s)
        _state["beast_news"] = {"k": k, "how": "came", "day": today}
        return s
    except Exception:
        traceback.print_exc()
        return s


def week_field(today, c=None):
    """What rides my week (api.week_doc reads session["beast"]): a beaten
    one for two days, with My beast on and my numbers shared; None otherwise."""
    c = c or cfg()
    share = bool(c.get(SHARE_KEY, True)) and not c.get("show_up") and not c.get("paused") and on(c)
    return B.week_field(state(c), today, share)


def note_week(today=None, c=None):
    """Put what my week carries of the beast in the session, for the next sync."""
    try:
        cl = client()
        if today is None:
            today = _cut(mw.col)[1].isoformat() if mw.col else datetime.date.today().isoformat()
        v = week_field(today, c)
        if cl.session.get("beast") != v:
            if v is None:
                cl.session.pop("beast", None)
            else:
                cl.session["beast"] = v
            cl._save_session()
    except Exception:
        traceback.print_exc()


# ---- the clicks ----

def home_deck(col, now):
    """Where Study goes: the top deck holding most of its cards not hit yet
    (by their home deck), or None when none are left."""
    ids = cards(col, now)
    _n, _g, hit = count(col, ids, now["day"])
    left = [c for c in ids if c not in hit]
    tally = {}
    for i in range(0, len(left), CHUNK):
        chunk = ",".join(str(c) for c in left[i:i + CHUNK])
        for did, n in col.db.all(f"SELECT CASE WHEN odid THEN odid ELSE did END, COUNT(*) FROM cards WHERE id IN ({chunk}) "
                                 "AND queue != -1 AND type != 0 GROUP BY 1") or []:
            d = col.decks.get(int(did), default=False)
            if d:
                top = str(d["name"]).split("::")[0]
                tally[top] = tally.get(top, 0) + int(n)
    if not tally:
        return None
    return col.decks.id_for_name(max(sorted(tally), key=tally.get))


def study():
    """Study: Anki's Study screen on your own deck (home_deck). No deck of
    its own (Sam's round 3): Anki's order puts the most overdue first."""
    from aqt.utils import tooltip
    s = state()
    now = s.get("now")
    if not now or mw.col is None:
        return
    did = home_deck(mw.col, now)
    if not did:
        tooltip("None of its cards are left to review.")
        return
    mw.col.decks.select(did)
    mw.moveToState("overview")


def empty_old_deck(col, normal):
    """The morning (plan_flow.tidy_decks): a beast's deck one of 3.9.0's
    test builds left goes back to its decks (Anki's Empty), as Today's
    misses does, so its cards are never kept out of their own decks; then
    the tidy takes the empty deck. normal: the ids of the decks that aren't
    filtered."""
    from . import plan_flow as pf, plans as P
    c = pf._pcfg()
    if not c.get(DECK_DAY) or c.get(DECK_DAY) == pf._today():
        return
    for name in OLD_DECKS:
        did = col.decks.id_for_name(P.our_deck(name))
        if did and int(did) not in normal:
            col.sched.empty_filtered_deck(int(did))
    c.pop(DECK_DAY, None)
    pf._psave(c)


def let_go(today):
    """Let it go: it leaves (its cards stay as they are); a week's rest."""
    s = state()
    if s.get("now"):
        _save(B.end(s, "let", today))
        _state["beast_news"] = {"k": s["now"]["k"], "how": "let", "day": today}
        return True
    return False


def beaten_in(year):
    """For Wrapped: [{k, name, days}] beaten in a year (none while it isn't ready)."""
    return B.beaten(state(), year) if B.READY else []


def seen_news():
    """The x on the beaten card: it's said, and so is the closet thing it showed."""
    news = _state.get("beast_news") or {}
    _state["beast_news"] = None
    if news.get("how") == "beaten":
        _drop_thing()


BEAST_THINGS = ("beasthood", "viking", "knight")  # Pip's closet's beast things (closet.THINGS, group Beasts)


def thing():
    """A beast thing just come in Pip's closet (its line's news), for the beaten card to say."""
    keys = list((_state.get("closet_new") or {}).get("keys") or [])
    return next((k for k in reversed(keys) if k in BEAST_THINGS), None)


def _drop_thing():
    cn = _state.get("closet_new")
    if cn and cn.get("keys"):
        keys = [k for k in cn["keys"] if k not in BEAST_THINGS]
        _state["closet_new"] = dict(cn, keys=keys) if keys else None


def view(c=None, page=False):
    """The You bubble's card: {now, frac, left, met, news, on, share} or
    None. page: the fight page's, which is drawn without a beast too."""
    c = c or cfg()
    if not B.READY:
        return None
    s = state(c)
    now = s.get("now")
    news = _state.get("beast_news")
    if mw.col is not None and news and news.get("day") != _cut(mw.col)[1].isoformat():
        news = _state["beast_news"] = None  # yesterday's news: said
    if (not now and not news or not on(c)) and not page:
        return None  # nothing to say, or beasts off (Settings)
    out = {"news": news, "met": s.get("met") or [], "on": on(c), "share": bool(c.get(SHARE_KEY, True))}
    if news and news.get("how") == "beaten":
        out["thing"] = thing()  # the beaten card says it, so the closet's own line doesn't
    if now:
        frac, left = B.progress(now)
        out.update(now=now, frac=frac, left=left, letting=bool(page and _state.get("beast_letting")))
    return out
