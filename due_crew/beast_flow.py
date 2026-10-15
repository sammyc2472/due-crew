"""3.9.0: the Backlog Beast, the glue (beast.py says what it is; board draws
it). At each refresh: the beast now counts what's been reviewed of its
cards (on any device: Anki's history, after an AnkiWeb sync) and what's
gone without a review; once an Anki day with none, a look at the pile for
a new one (rule B). Its cards stay on this computer (user_files/<profile>/
beast.json); another computer works them out from Anki's own history for
that morning. The account keeps the beast itself (`beast`), so every
computer has the same one.

Study the bite: a Due Crew deck of the bite's cards, the most overdue for
their interval first (Anki's relative overdueness), Anki rescheduling them
as it would; one undo step of Anki's own.

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
DUE_PRIORITY = 8  # Anki's filtered-deck order: relative overdueness
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
    c = c or cfg()
    return bool(c.get(ON_KEY, True)) and not B.clean(c.get(KEY)).get("off")


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


def gap(col, counts=None):
    """Days off just before today (since the last day studied before it)."""
    _cut_, today = _cut(col)
    counts = counts if counts is not None else day_counts(col, 60)
    before = sorted(d for d, n in counts.items() if n and d < today.isoformat())
    if not before:
        return 0
    return (today - datetime.date.fromisoformat(before[-1])).days - 1


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
    """(reviewed since its morning, gone without a review: deleted,
    suspended, or new again). Any review counts, Again too."""
    s_ms = _day_start_ms(col, day)
    hit, here = set(), set()
    for i in range(0, len(cids), CHUNK):
        chunk = ",".join(str(int(c)) for c in cids[i:i + CHUNK])
        hit |= {int(c) for (c,) in col.db.all(f"SELECT DISTINCT cid FROM revlog WHERE id >= ? AND ease > 0 AND cid IN ({chunk})", s_ms) or []}
        here |= {int(c) for (c,) in col.db.all(f"SELECT id FROM cards WHERE id IN ({chunk}) AND queue != -1 AND type != 0") or []}
    gone = {int(c) for c in cids} - here - hit
    return len(hit), len(gone), hit


# ---- at a refresh ----

def _away(c, t):
    """Away (Privacy's dates) or paused: no new beast, and one here naps."""
    from .backend.shapes import away_range
    rng = away_range(c)
    return bool(rng and rng[0] <= t <= rng[1]) or bool(c.get("paused"))


def check(today=None, look=True):
    """At a refresh and before a sync, on the main thread: count the beast
    now (its end, when it's beaten or wandered off), else once a day look
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
        k = B.kind(gap(col, counts), len(p), usual, [od for _c, od, _i, _l in p],
                   sum(1 for *_x, lapses in p if lapses >= B.LEECH_LAPSES))
        s = dict(s, now=B.turn_up(today, k, ids, usual, B.DEFAULT_PACE, capped, len(p)))
        _write(today, ids)
        _save(s)
        _state["beast_news"] = {"k": k, "how": "came", "day": today}
        return s
    except Exception:
        traceback.print_exc()
        return s


def week_field(today, c=None):
    """What rides my week (api.week_doc reads session["beast"]): the kind
    and how far, with My beast on and my numbers shared; None otherwise."""
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

def bite_cards(col, now):
    """The bite: the beast's cards not yet reviewed, the most overdue for
    their interval first, a bite's worth."""
    ids = cards(col, now)
    _n, _g, hit = count(col, ids, now["day"])
    left = [c for c in ids if c not in hit]
    today = int(col.sched.today)
    rows = []
    for i in range(0, len(left), CHUNK):
        chunk = ",".join(str(c) for c in left[i:i + CHUNK])
        rows += col.db.all(f"SELECT id, CASE WHEN odid THEN odue ELSE due END, ivl FROM cards WHERE id IN ({chunk}) "
                           "AND queue != -1 AND type != 0") or []
    rows.sort(key=lambda r: (-((today - int(r[1])) / max(1, int(r[2] or 1))), int(r[0])))
    return [int(r[0]) for r in rows[:B.bite(int(now.get("usual") or 0), now.get("pace"))]]


def study_bite():
    """Study the bite: a Due Crew deck of it, then Anki's Study screen on it."""
    from aqt.utils import tooltip
    from . import plan_flow as pf, plans as P
    s = state()
    now = s.get("now")
    if not now or mw.col is None:
        return
    ids = bite_cards(mw.col, now)
    if not ids:
        tooltip("Nothing left in its bite today.")
        return
    name = P.our_deck(B.KINDS[now["k"]]["name"])
    if pf._filtered(mw.col, name, ids, order=DUE_PRIORITY):
        c = pf._pcfg()
        c["bite_day"] = pf._today()  # the next morning empties it back if it's left
        pf._psave(c)
        pf._after_change()
        did = mw.col.decks.id_for_name(name)
        if did:
            mw.col.decks.select(did)
            mw.moveToState("overview")


def empty_old_bite(col, normal):
    """The morning (plan_flow.tidy_decks): a bite left from an earlier day
    goes back to its decks first (Anki's Empty), as Today's misses does, so
    its cards are never kept out of their own decks; then the tidy takes
    the empty deck. normal: the ids of the decks that aren't filtered."""
    from . import plan_flow as pf, plans as P
    c = pf._pcfg()
    if not c.get("bite_day") or c.get("bite_day") == pf._today():
        return
    for k in B.KINDS.values():
        did = col.decks.id_for_name(P.our_deck(k["name"]))
        if did and int(did) not in normal:
            col.sched.empty_filtered_deck(int(did))
    c.pop("bite_day", None)
    pf._psave(c)


def set_pace(pace):
    s = state()
    if s.get("now") and pace in B.PACES and s["now"].get("pace") != pace:
        s["now"] = dict(s["now"], pace=pace)
        _save(s)
        return True
    return False


def let_go(today):
    """Let it go: it waves and leaves; nobody's told; a week's rest."""
    s = state()
    if s.get("now"):
        _save(B.end(s, "let", today))
        _state["beast_news"] = {"k": s["now"]["k"], "how": "let", "day": today}
        return True
    return False


def not_for_me():
    """Not for me: beasts off (Settings › Fifteen and Pip brings them back);
    one now leaves quietly."""
    c = dict(cfg())
    s = state(c)
    c[ON_KEY] = False
    if s.get("now"):
        c[KEY] = B.end(s, "let", _cut(mw.col)[1].isoformat() if mw.col else datetime.date.today().isoformat())
    save_cfg(c)


def beaten_in(year):
    """For Wrapped: [{k, name, days}] beaten in a year."""
    return B.beaten(state(), year)


def seen_news():
    """The x on the card's line (beaten, wandered off): it's said."""
    _state["beast_news"] = None


def view(c=None, page=False):
    """The You bubble's card: {now, frac, left, says, bite, days, naps,
    met, news} or None. page: the fight page's, which is drawn without a
    beast too (and says whether beasts are on and mine is shared)."""
    c = c or cfg()
    s = state(c)
    now = s.get("now")
    news = _state.get("beast_news")
    if mw.col is not None and news and news.get("day") != _cut(mw.col)[1].isoformat():
        news = _state["beast_news"] = None  # yesterday's news: said
    if (not now and not news or not on(c)) and not page:
        return None  # nothing to say, or beasts off (Settings)
    out = {"news": news, "met": s.get("met") or [], "on": on(c),
           "share": bool(week_field(_cut(mw.col)[1].isoformat() if mw.col else "", c)) if now else False,
           "naps": bool(now) and mw.col is not None and _away(c, _cut(mw.col)[1])}
    if now:
        frac, left = B.progress(now)
        out.update(now=now, frac=frac, left=left, says=B.says(now["k"], frac),
                   bite=B.bite(int(now.get("usual") or 0), now.get("pace")),
                   days=B.days_left(left, int(now.get("usual") or 0), now.get("pace")))
    return out
