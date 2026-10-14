"""2.13: settings that belong to a person follow their account.

Until 2.13 every setting lived in Anki's add-on config on one computer,
which AnkiWeb doesn't sync. A second computer started from the defaults:
shared decks empty (and its first upload emptied them for the crew), the
privacy switches all on, no squads, no exam date. Now the settings in
ACCOUNT_KEYS live on the server too (GET/PUT /settings), readable only by
me. What's about the screen (accent, theme, sort, tab) stays
per computer.

The one rule that matters: an install pulls before it uploads. Profile
open, sign-in and the day's first sync pull the doc (one read a day), and
uploads wait for it. The newest save wins between computers. A new install
takes what the account has.

Main-thread rules as in __init__: config writes and collection access on
the main thread, the network off it.
"""

import datetime
import time

from aqt import mw

from . import app
from .app import _state, cfg, client

ACCOUNT_KEYS = ("share_reviews", "share_time", "share_retention", "share_streak",
                "share_heatmap", "show_up", "paused", "exam_date", "away_from", "away_to",
                "status", "emoji", "squads", "crew_label", "shared_decks", "muted",
                "accent",  # 3.5.0: the site wears it too
                "due_items", "due_ticks", "due_show", "due_suggest",  # Due: my own to-dos, on every computer
                "sev_look", "sev_closet")  # 3.8.2: Sev's closet: what it has on, what it's earned
ACCENT_NAMES = ("green", "blue", "purple", "teal", "amber", "rose")
_BOOLS = ("share_reviews", "share_time", "share_retention", "share_streak",
          "share_heatmap", "show_up", "paused", "due_show", "due_suggest")
_TEXT = {"exam_date": 10, "away_from": 10, "away_to": 10, "status": 80, "emoji": 16,
         "crew_label": 40}
MAX_SQUADS = 20
SEEN_KEY = "account_seen"  # 3.6: in the config: the account save this config holds
MAX_DECKS = 200
MAX_MUTED = 500


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# ---- pure ----

def pick(c, deck_name=lambda did: ""):
    """The account's share of a config. Shared decks go by id and name, so a
    computer whose collection didn't come through AnkiWeb still matches."""
    out = {}
    for k in ACCOUNT_KEYS:
        if k == "shared_decks":
            decks = []
            for d in c.get(k) or []:
                try:
                    did = int(d)
                except (TypeError, ValueError):
                    continue
                decks.append({"id": did, "name": str(deck_name(did) or "")})
            out[k] = decks
        elif k in c:
            out[k] = c[k]
    return out


def clean(s):
    """A settings doc from the server, coerced to what the config holds."""
    out = {}
    if not isinstance(s, dict):
        return out
    for k in _BOOLS:
        if isinstance(s.get(k), bool):
            out[k] = s[k]
    for k, n in _TEXT.items():
        if isinstance(s.get(k), str):
            out[k] = s[k][:n]
    if isinstance(s.get("squads"), list):
        squads = []
        for q in s["squads"]:
            if len(squads) >= MAX_SQUADS:
                break
            if isinstance(q, dict) and isinstance(q.get("id"), str) and q["id"]:
                squads.append({f: str(q.get(f) or "")[:64] for f in ("id", "code", "name", "founder")})
        out["squads"] = squads
    if isinstance(s.get("shared_decks"), list):
        decks = []
        for d in s["shared_decks"]:
            if len(decks) >= MAX_DECKS:
                break
            if isinstance(d, dict):
                try:
                    decks.append({"id": int(d.get("id")), "name": str(d.get("name") or "")[:200]})
                except (TypeError, ValueError):
                    continue
        out["shared_decks"] = decks
    if s.get("accent") in ACCENT_NAMES:
        out["accent"] = s["accent"]
    if isinstance(s.get("due_items"), list):
        from .due import clean_items
        out["due_items"] = clean_items(s["due_items"])
    if isinstance(s.get("due_ticks"), dict):
        from .due import clean_ticks
        out["due_ticks"] = clean_ticks(s["due_ticks"])
    if isinstance(s.get("sev_look"), list):
        from .closet import clean as clean_look
        out["sev_look"] = clean_look(s["sev_look"])
    if isinstance(s.get("sev_closet"), dict):
        from .closet import clean_closet
        out["sev_closet"] = clean_closet(s["sev_closet"])
    if isinstance(s.get("muted"), list):
        # 3.0.1: the people whose cheers and knocks I don't get, by uid
        out["muted"] = list(dict.fromkeys(
            u for u in s["muted"] if isinstance(u, str) and 0 < len(u) <= 128))[:MAX_MUTED]
    return out


def apply(c, s, resolve=lambda did, name: did):
    """The config with the account's settings in it. `resolve(id, name)`
    finds the deck here (by id, else by name) or None."""
    out = dict(c)
    for k, v in clean(s).items():
        if k == "shared_decks":
            dids = []
            for d in v:
                did = resolve(d["id"], d["name"])
                if did is not None and did not in dids:
                    dids.append(did)
            out[k] = dids
        else:
            out[k] = v
    if "shared_decks" in (s or {}):
        out["shared_decks_set"] = True
    return out


def newer(a, b):
    """Whether timestamp a is after b (ISO strings; '' is the dawn of time)."""
    return str(a or "") > str(b or "")


# 3.8.1 (the audit, #2): two saves from one start, merged. A save replaced the
# whole doc, so two computers (or a computer and the site) saving close together
# lost one side's change. The server now names each save's rev and turns away a
# save made over an older one; this merges the two from the doc both started from.
_LISTS = {"muted": None, "squads": "id", "shared_decks": "id", "due_items": "id"}
_GONE = object()


def _one(b, m, t):
    """One value three ways: the side that changed it; both did, mine (the save
    being made now)."""
    if m is _GONE:
        return t
    if t is _GONE:
        return m
    return t if m == b else m


def _by(v, key):
    out = {}
    for x in v if isinstance(v, list) else []:
        k = x if key is None else (x.get(key) if isinstance(x, dict) else None)
        if isinstance(k, (str, int)) and not isinstance(k, bool) and k not in out:
            out[k] = x
    return out


def _merge_keys(b, m, t):
    """Keyed things three ways: what one side added stays, what one side took
    off goes, what one side changed takes that change. Theirs' order, then
    my new ones."""
    out = []
    for k in list(t) + [k for k in m if k not in t]:
        if k in b and (k not in m or k not in t):
            continue
        out.append((k, _one(b.get(k, _GONE), m.get(k, _GONE), t.get(k, _GONE))))
    return out


def merge3(base, mine, theirs):
    """The account's settings from my save and theirs, both made from `base`.
    A key one side changed takes that side's. A key both changed: the muted,
    squads, shared decks and to-dos merge item by item, the to-do ticks day
    by day, the closet thing by thing (3.8.2: nothing earned is lost), and
    anything else (a switch, a status, Sev's look) takes mine. Pure."""
    base, mine, theirs = (x if isinstance(x, dict) else {} for x in (base, mine, theirs))
    out = {}
    for k in list(theirs) + [k for k in mine if k not in theirs]:
        b, m, t = base.get(k, _GONE), mine.get(k, _GONE), theirs.get(k, _GONE)
        if m == b:
            v = t
        elif t == b:
            v = m
        elif k in _LISTS and isinstance(m, list) and isinstance(t, list):
            key = _LISTS[k]
            v = [x for _k, x in _merge_keys(_by(b, key), _by(m, key), _by(t, key))]
        elif k == "due_ticks" and isinstance(m, dict) and isinstance(t, dict):
            v = dict(_merge_keys(b if isinstance(b, dict) else {}, m, t))
        elif k == "sev_closet":
            from .closet import merge_closets
            v = merge_closets(m if isinstance(m, dict) else {}, t if isinstance(t, dict) else {})  # earned is never lost
        else:
            v = m
        if v is not _GONE:
            out[k] = v
    return out


# ---- glue ----

_pending = []


def _today():
    """The Anki day: before the first refresh too, so the hours between
    midnight and the rollover don't read as a new day (one GET /settings)."""
    if _state["labels"]:
        return _state["labels"][0]
    if mw.col:
        try:
            from .stats.queries import StatsQueries
            return StatsQueries(mw.col).day_label(0)
        except Exception:
            pass
    return datetime.date.today().isoformat()


def _deck_name(did):
    try:
        return mw.col.decks.name(did) if mw.col else ""
    except Exception:
        return ""


def _resolve(did, name):
    col = mw.col
    if col is None:
        return None
    try:
        if col.decks.get(did, default=False):
            return did
    except Exception:
        pass
    if not name:
        return None
    try:
        found = col.decks.id_for_name(name) if hasattr(col.decks, "id_for_name") \
            else (col.decks.by_name(name) or {}).get("id")
        return int(found) if found else None
    except Exception:
        return None


RETRY_SECS = 600  # after a pull the network refused, uploads go; a new pull waits this long


def ready():
    """Pulled this session and today: uploads may go. After a pull the
    network refused, they go too (holding them would hold everything), and
    the next pull waits RETRY_SECS, so offline syncs don't loop."""
    cl = client()
    if not cl.signed_in:
        return True
    if not _state["settings_ready"]:
        return False
    if cl.session.get("settings_day") == _today():
        return True
    return time.time() - _state["settings_failed_ts"] < RETRY_SECS


def ensure(then=None):
    """Pull my settings, once per day and on open or sign-in, then run
    `then`. While a pull is out, callers queue behind it."""
    if ready():
        if then:
            then()
        return
    if then:
        _pending.append(then)
    if _state["settings_pulling"]:
        return
    cl = client()
    _state["settings_pulling"] = True
    gen = app.generation
    app._bg(cl.get_settings, lambda result: _pulled(result, gen))


def _pulled(result, gen=None):
    cl = client()
    doc, status = result if isinstance(result, tuple) else (None, 0)
    if gen is not None and gen != app.generation:
        # another profile or account since it went out: not theirs to apply
        _state["settings_pulling"] = False
        return
    try:
        if status == 200 and isinstance(doc, dict):
            at = str(doc.get("at") or "")
            # 3.6: the config remembers which save it holds, as the session
            # does. A config that doesn't (reset: a reinstall into another
            # folder starts from the defaults, while user_files and the
            # session survive) takes the account's, whatever the session says,
            # and is never "newer" than it
            here = cfg().get(SEEN_KEY)
            base = _base()
            if at != cl.session.get("settings_seen") or here != at:
                mine = cl.session.get("settings_local_at")
                if here and cl.session.get("settings_dirty") and base is not None:
                    # 3.8.1: an edit here not yet up, and a save from elsewhere: both
                    merge_in(doc, base)
                    push(cfg())
                elif here and cl.session.get("settings_dirty") and newer(mine, at):
                    push(cfg())  # no save kept to merge from (before 3.8.1): the newest wins
                else:
                    c = apply(cfg(), doc.get("settings"), _resolve)
                    c[SEEN_KEY] = at
                    app.save_cfg(c, from_account=True)
                    cl.session.update(settings_seen=at, settings_dirty=False)
                    _keep_base(doc)
                    cl._save_session()
                    if app.swap:
                        app.swap(cfg())
            elif cl.session.get("settings_dirty"):
                push(cfg())  # an edit whose upload failed: nothing newer up there
            elif base is None:
                _keep_base(doc)  # this computer holds the account's save: the start for the next
                cl._save_session()
        elif status == 404:
            push(cfg())  # the account's first settings: this computer's
    finally:
        # a refusal waits for tomorrow; no network tries again at the next
        # sync. Either way uploads carry on rather than wait forever.
        _state["settings_pulling"] = False
        _state["settings_ready"] = True
        if status in (200, 403, 404):
            cl.session["settings_day"] = _today()
            cl._save_session()
        else:
            _state["settings_failed_ts"] = time.time()
        waiting = list(_pending)
        _pending.clear()
        for fn in waiting:
            try:
                fn()
            except Exception:
                import traceback
                traceback.print_exc()


def saved_elsewhere(at):
    """3.7.1: the board says when my settings were last saved. A save this
    computer hasn't seen (another computer, or the site's Delete my to-dos)
    is pulled now rather than tomorrow; one of this computer's own still on
    its way isn't."""
    cl = client()
    if not at or not cl.signed_in or _state["settings_pulling"] or _pushing["busy"]:
        return
    if at == cl.session.get("settings_seen") or cl.session.get("settings_dirty"):
        return
    cl.session["settings_day"] = ""
    _state["settings_failed_ts"] = 0
    ensure()


def _base():
    """The save this computer last had in common with the server (its rev and
    doc), the start a merge works from; None before 3.8.1's first pull."""
    sess = client().session
    rev, doc = sess.get("settings_rev"), sess.get("settings_base")
    return doc if isinstance(rev, int) and isinstance(doc, dict) else None


def _keep_base(doc, rev=None):
    """Remember the server's doc as the start for the next save (main thread)."""
    sess = client().session
    rev = doc.get("rev") if rev is None else rev
    settings = doc.get("settings") if isinstance(doc.get("settings"), dict) else None
    if isinstance(rev, int) and not isinstance(rev, bool) and settings is not None:
        sess.update(settings_rev=rev, settings_base=settings)
    else:
        sess.pop("settings_rev", None)
        sess.pop("settings_base", None)


def merge_in(doc, base):
    """3.8.1: someone saved since this computer's last save: theirs and mine
    merged, here now and up next (the caller pushes). A key the config
    doesn't hold reads as unchanged. Main thread."""
    cl = client()
    theirs = doc.get("settings") if isinstance(doc.get("settings"), dict) else {}
    mine = dict(base)
    mine.update(pick(cfg(), _deck_name))
    c = apply(cfg(), merge3(base, mine, theirs), _resolve)
    app.save_cfg(c, from_account=True)
    _keep_base(doc)
    cl._save_session()
    if app.swap:
        app.swap(cfg())


_pushing = {"busy": False, "again": False}
MERGES = 3  # turned away this many times in a row: the next pull sorts it out


def push(c, _merged=0):
    """Send this computer's account settings. The newest save wins. One
    save at a time (3.5.0: Settings in the board saves on every click, and
    the server keeps whichever arrives last): a change made while one is
    on its way goes after it, as the config is then, so a run of clicks is
    at most two saves and never lands out of order."""
    cl = client()
    if not cl.signed_in:
        return
    at = _now()
    cl.session.update(settings_dirty=True, settings_local_at=at)
    cl._save_session()
    if _pushing["busy"]:
        _pushing["again"] = True
        return
    _pushing["busy"] = True
    settings = pick(c, _deck_name)
    gen = app.generation
    base = _base()
    rev = cl.session.get("settings_rev") if base is not None else None

    def done(res):
        _pushing["busy"] = False
        again, _pushing["again"] = _pushing["again"], False
        ours = gen == app.generation
        conflict = getattr(res, "conflict", None)
        if res and ours:
            # what the server holds now is this save: the start for the next
            _keep_base({"settings": settings}, getattr(res, "rev", None))
            if not again:
                cl.session.update(settings_seen=at, settings_dirty=False)
            cl._save_session()
            if not again:
                c2 = cfg()
                c2[SEEN_KEY] = at
                app.save_cfg(c2, from_account=True)
        elif conflict and ours and base is not None and _merged < MERGES:
            # 3.8.1: someone saved since this one started: merge, and save that
            merge_in(conflict, base)
            push(cfg(), _merged + 1)
            return
        if again:
            push(cfg())  # whoever is signed in now, as the config is now

    if rev is None:
        app._bg(lambda: cl.put_settings(at, settings), done)
    else:
        app._bg(lambda: cl.put_settings(at, settings, base=rev), done)


def on_change(c):
    """app.save_cfg calls this when an account setting changed here."""
    if not client().signed_in:
        return
    cl = client()
    if _state["settings_ready"] and (cfg().get(SEEN_KEY) or cl.session.get("settings_day") == _today()):
        push(c)
    else:
        # not pulled yet, or the pull failed on a config that has never held
        # the account's settings: pushing now would put this computer's
        # defaults over them. Note the edit, pull, and let the newer side win
        cl.session.update(settings_dirty=True, settings_local_at=_now())
        cl._save_session()
        ensure()
