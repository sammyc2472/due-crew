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
                "status", "emoji", "squads", "crew_label", "shared_decks")
_BOOLS = ("share_reviews", "share_time", "share_retention", "share_streak",
          "share_heatmap", "show_up", "paused")
_TEXT = {"exam_date": 10, "away_from": 10, "away_to": 10, "status": 80, "emoji": 16,
         "crew_label": 40}
MAX_SQUADS = 20
MAX_DECKS = 200


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


# ---- glue ----

_pending = []


def _today():
    return _state["labels"][0] if _state["labels"] else datetime.date.today().isoformat()


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
    app._bg(cl.get_settings, _pulled)


def _pulled(result):
    cl = client()
    doc, status = result if isinstance(result, tuple) else (None, 0)
    try:
        if status == 200 and isinstance(doc, dict):
            at = str(doc.get("at") or "")
            if at != cl.session.get("settings_seen"):
                mine = cl.session.get("settings_local_at")
                if cl.session.get("settings_dirty") and newer(mine, at):
                    push(cfg())  # this computer's save is the newest
                else:
                    c = apply(cfg(), doc.get("settings"), _resolve)
                    app.save_cfg(c, from_account=True)
                    cl.session.update(settings_seen=at, settings_dirty=False)
                    cl._save_session()
                    if app.swap:
                        app.swap(cfg())
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


def push(c):
    """Send this computer's account settings. The newest save wins."""
    cl = client()
    if not cl.signed_in:
        return
    at = _now()
    settings = pick(c, _deck_name)
    cl.session.update(settings_dirty=True, settings_local_at=at)
    cl._save_session()

    def done(ok):
        if ok:
            cl.session.update(settings_seen=at, settings_dirty=False)
            cl._save_session()

    app._bg(lambda: cl.put_settings(at, settings), done)


def on_change(c):
    """app.save_cfg calls this when an account setting changed here."""
    if not client().signed_in:
        return
    if _state["settings_ready"]:
        push(c)
    else:
        # not pulled yet: note the edit, pull, and let the newer side win
        cl = client()
        cl.session.update(settings_dirty=True, settings_local_at=_now())
        cl._save_session()
        ensure()
