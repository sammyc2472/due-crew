"""Shapes and the small pure helpers the add-on shares: what a day, a week,
a deck row or a squad row looks like on the way out and on the way back,
codes as people type them, notes and emoji. No network here (api.py has
that), and no Qt.

Until 3.0 these lived in backend/firebase.py, next to the Firestore client.
"""

import datetime
import hashlib
import re
import secrets

from ..room_model import clean_room, is_over

TIMEOUT = 10
LIVE_MINUTES = 60   # 2.10: "studying now" lasts this long unless stopped
TRICKY_MAX = 3      # 2.10: cards flagged "this one's getting me", newest kept
TRICKY_DAYS = 7     # ...for this long
GUID_MAX = 40
WEEK_WINDOW = 8     # the week doc: my last eight days (the week, and one before)
# 3.0.1: POST /reports: (the Worker's value, what the dialog says)
REPORT_REASONS = (("cheers", "Unwanted cheers or knocks"),
                  ("name", "A name or emoji that shouldn't be here"),
                  ("other", "Something else"))
REPORT_NOTE_MAX = 500


class AuthError(Exception):
    """A sign-in step the server refused. `code` is the server's word for
    it: bad_email, wrong_code, expired, locked, slow_down."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


class TransportError(Exception):
    """Request failed (network, 5xx, 429, auth) — the data may still exist.
    `status` is the HTTP status when there was a response, else None."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def _exam_value(iso, today_label):
    """The exam date to publish: a valid ISO date not yet passed, else None."""
    try:
        d = datetime.date.fromisoformat(str(iso))
        t = datetime.date.fromisoformat(str(today_label))
    except (TypeError, ValueError):
        return None
    return str(iso) if d >= t else None


NOTE_MAX = 80


def clean_note(text, limit=NOTE_MAX):
    """One printable line, at most `limit` chars; '' for anything else.
    Used for cheer notes and statuses in both directions."""
    if not isinstance(text, str):
        return ""
    one_line = " ".join(text.split())
    return "".join(ch for ch in one_line if ch.isprintable())[:limit]


EMOJI_MAX = 16  # UTF-16 units: one emoji, with its modifiers and joiners


def clean_emoji(text):
    """One emoji (a single grapheme, joiners and modifiers included) or ''.
    Letters, digits, and punctuation never pass — this is a face, not a
    second name field."""
    if not isinstance(text, str):
        return ""
    text = text.strip()
    if not text:
        return ""
    out = _first_grapheme(text)
    return out if out and emoji_fits(out) else ""


def _first_grapheme(text):
    """The first emoji cluster of `text` (joiners, variation selectors, skin
    tones, flag pairs), or '' when it doesn't start with one."""
    text = str(text or "").strip()
    if not text or ord(text[0]) < 0x2190 or not text[0].isprintable():
        return ""
    out = ""
    for i, ch in enumerate(text[:32]):
        code = ord(ch)
        joiner = code in (0x200D, 0xFE0F) or 0x1F3FB <= code <= 0x1F3FF or 0x1F1E6 <= code <= 0x1F1FF
        if i > 0 and not joiner and ord(text[i - 1]) != 0x200D:
            break
        out += ch
    return out


def emoji_fits(emoji):
    """The server caps an emoji at 16 UTF-16 units (what the Firestore rules'
    size() counted, measured in the emulator, and what the Worker's .length
    counts). Too long is refused whole: never truncated into a broken glyph,
    never sent to be rejected."""
    return len(emoji.encode("utf-16-le")) // 2 <= EMOJI_MAX


def emoji_too_long(text):
    """True when `text` starts with a real emoji that just doesn't fit."""
    g = _first_grapheme(text)
    return bool(g) and not emoji_fits(g)


def away_range(cfg):
    """(from, to) dates of a configured away spell, or None."""
    try:
        a = datetime.date.fromisoformat(str(cfg.get("away_from") or ""))
        b = datetime.date.fromisoformat(str(cfg.get("away_to") or ""))
    except ValueError:
        return None
    return (a, b) if a <= b else (b, a)


def away_on(label, cfg):
    """The spell's last day (ISO) when `label` falls inside it, else None."""
    rng = away_range(cfg)
    if not rng:
        return None
    try:
        d = datetime.date.fromisoformat(str(label))
    except ValueError:
        return None
    return rng[1].isoformat() if rng[0] <= d <= rng[1] else None


def _as_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _as_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _clean_day(doc):
    """Coerce one day of a week doc to trusted types; None stays None."""
    if doc is None:
        return None
    out = {}
    for key, conv in (("reviews", _as_int), ("studyTimeMs", _as_int),
                      ("accuracy", _as_float), ("streak", _as_int), ("newCards", _as_int)):
        if key in doc:
            v = conv(doc[key])
            if v is not None:
                out[key] = v
    if isinstance(doc.get("studied"), bool):
        out["studied"] = doc["studied"]
    status = clean_note(doc.get("status"))
    if status:
        out["status"] = status
    if doc.get("away") is True:
        out["away"] = True
        try:
            out["awayTo"] = datetime.date.fromisoformat(str(doc.get("awayTo"))).isoformat()
        except ValueError:
            pass
    return out


def _week_days(doc, labels):
    """A week doc -> {label: day} for `labels`, the form everything
    downstream reads. The away spell rides the doc as a range; each day
    inside it is flagged here."""
    days = doc.get("days") if isinstance(doc.get("days"), dict) else {}
    lo, hi = str(doc.get("awayFrom") or ""), str(doc.get("awayTo") or "")
    out = {}
    for lb in labels:
        d = days.get(lb)
        d = dict(d) if isinstance(d, dict) else None
        if lo and hi and lo <= lb <= hi:
            d = dict(d or {}, away=True, awayTo=hi)
        out[lb] = d
    return out


# the number fields and the Privacy switch each one answers to
METRICS = (("reviews", "share_reviews"), ("studyTimeMs", "share_time"),
           ("accuracy", "share_retention"), ("streak", "share_streak"),
           # 2.13: of the reviews, cards answered for the first time; it goes
           # out under the Reviews switch, never on its own
           ("newCards", "share_reviews"))


def shared_numbers(values, cfg):
    """The numbers the Privacy switches let out of `values` (keyed by the
    fields in METRICS). One gate for my week and my squad rows. Just show
    up (2.8) lets none out; the switches keep their settings under it."""
    if cfg.get("show_up"):
        return {}
    return {field: values[field] for field, key in METRICS
            if cfg.get(key, True) and values.get(field) is not None}


def day_doc(values, cfg, status=None):
    """One day of my week as it goes out: `studied` (the numbers-free floor
    the Days view stands on), the numbers my switches let out, and the
    status bubble when it's today's."""
    doc = {"studied": bool(values.get("reviews"))}
    doc.update(shared_numbers(values, cfg))
    status = clean_note(status)
    if status:
        doc["status"] = status
    return doc


def clean_tricky(value, today_label=None):
    """Flagged cards (2.10), coerced: [{guid, deck, at}] and, for my own
    flags kept locally, `text`. At most TRICKY_MAX, none older than
    TRICKY_DAYS when a day is given. Since 3.0 a flag leaves this computer
    without its text; crewmates read the text from their own copy of the
    note."""
    out = []
    if not isinstance(value, list):
        return out
    oldest = ""
    if today_label:
        try:
            oldest = (datetime.date.fromisoformat(today_label)
                      - datetime.timedelta(days=TRICKY_DAYS)).isoformat()
        except ValueError:
            oldest = ""
    for t in value:
        if not isinstance(t, dict):
            continue
        guid = str(t.get("guid") or "")[:GUID_MAX]
        at = str(t.get("at") or "")[:10]
        if not guid or (oldest and at < oldest):
            continue
        flag = {"guid": guid, "deck": clean_note(t.get("deck"), 40), "at": at}
        text = clean_note(t.get("text"), 60)
        if text:
            flag["text"] = text
        out.append(flag)
    return out[-TRICKY_MAX:]


def _live_room(value):
    room = clean_room(value)
    return None if is_over(room) else room


def live_now(until, now_utc=None):
    """Whether a "studying now" time (ISO, UTC) is still ahead."""
    try:
        t = datetime.datetime.fromisoformat(str(until).replace("Z", "+00:00"))
    except ValueError:
        return False
    now_utc = now_utc or datetime.datetime.now(datetime.timezone.utc)
    return t > now_utc


def _clean_decks(value):
    """Validate a friend's shared-decks payload down to a known shape."""
    if not isinstance(value, list):
        return []
    out = []
    for d in value:
        if not isinstance(d, dict):
            continue
        sig = d.get("sig")
        total = _as_int(d.get("total"))
        if not isinstance(sig, list) or not total:
            continue
        seen = min(max(_as_int(d.get("seen")) or 0, 0), total)
        entry = {
            "name": str(d.get("name", "?")),
            "sig": [str(s) for s in sig if isinstance(s, str)],
            "total": total,
            "seen": seen,
            "mature": min(max(_as_int(d.get("mature")) or 0, 0), seen),
        }
        # v2.6 extras, each optional
        opened = _as_int(d.get("open"))
        if opened is not None:
            entry["open"] = min(max(opened, seen), total)
        today = _as_int(d.get("today"))
        day = str(d.get("day") or "")
        if today is not None and today >= 0 and len(day) == 10:
            entry["today"], entry["day"] = today, day
        ret = _as_float(d.get("ret"))
        if ret is not None and 0 <= ret <= 100:
            entry["ret"] = ret
        out.append(entry)
    return out


SQUAD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I
SQUAD_CODE_LEN = 8
SQUAD_NAME_MAX = 24


def new_squad_code():
    return "".join(secrets.choice(SQUAD_ALPHABET) for _ in range(SQUAD_CODE_LEN))


def normalize_code(code):
    """What a person typed -> the code: uppercase, alphabet only."""
    return "".join(ch for ch in str(code or "").upper() if ch in SQUAD_ALPHABET)


FRIEND_CODE_LEN = 6


def _code_after_word(text, length):
    """The last `length`-character code that follows the word "code" in a
    pasted invite, or ''. Last, because a squad may be named "code club"."""
    found = re.findall(r"CODE:?\s*([A-Z0-9]{%d})(?![A-Z0-9])" % length, str(text or "").upper())
    return found[-1] if found else ""


def friend_code_from(text):
    """A friend code from whatever was typed or pasted: the code itself, or
    a whole invite."""
    code = _code_after_word(text, FRIEND_CODE_LEN)
    if code:
        return code
    bare = re.sub(r"[^A-Z0-9]", "", str(text or "").upper())
    return bare if len(bare) == FRIEND_CODE_LEN else ""


def squad_code_from(text):
    """A squad code from a typed code or a pasted squad invite, normalized.
    The caller checks the length."""
    return normalize_code(_code_after_word(text, SQUAD_CODE_LEN) or text)


def squad_id(code):
    """The squad's id derives from its invite code (the Worker computes the
    same): knowing the code is knowing the id, and there's no directory."""
    return hashlib.sha1(f"due-crew-squad:{normalize_code(code)}".encode()).hexdigest()[:24]


def clean_squad_name(name):
    one_line = " ".join(str(name or "").split())
    return "".join(ch for ch in one_line if ch.isprintable())[:SQUAD_NAME_MAX]


def _clean_member(row):
    """A squad member row from the server, coerced; None if unusable."""
    if not isinstance(row, dict) or not isinstance(row.get("uid"), str):
        return None
    day = str(row.get("day") or "")
    try:
        datetime.date.fromisoformat(day)
    except ValueError:
        day = ""
    acc = _as_float(row.get("accuracy"))
    week = _as_int(row.get("week"))
    return {"user_id": row["uid"],
            "name": str(row.get("name") or "?"),
            "emoji": clean_emoji(row.get("emoji")),
            "day": day,
            "reviews": _as_int(row.get("reviews")),
            "new_cards": _as_int(row.get("newCards")),
            "time_ms": _as_int(row.get("studyTimeMs")),
            "retention": acc if acc is not None and 0 <= acc <= 100 else None,
            "streak": _as_int(row.get("streak")),
            "week": week if week is not None and 0 <= week <= 7 else None}


# ---- 3.1: plans ----

_UNIT_ID = re.compile(r"[a-z0-9]{1,12}")
_PLAN_ID = re.compile(r"[a-z0-9]{1,32}")
_ISO = re.compile(r"\d{4}-\d{2}-\d{2}")


def _clean_unit(u):
    if not isinstance(u, dict) or not _UNIT_ID.fullmatch(str(u.get("id") or "")):
        return None
    if not _ISO.fullmatch(str(u.get("opens") or "")):
        return None
    out = {"id": u["id"], "name": clean_note(u.get("name"), 60) or "?", "opens": u["opens"],
           "tags": [t for t in u.get("tags") or [] if isinstance(t, str) and t][:50],
           "decks": [d for d in u.get("decks") or [] if isinstance(d, str) and d][:50],
           "cards": [[c[0], c[1]] for c in u.get("cards") or []
                     if isinstance(c, list) and len(c) == 2 and isinstance(c[0], str)
                     and isinstance(c[1], int) and not isinstance(c[1], bool)]}
    if _ISO.fullmatch(str(u.get("due") or "")):
        out["due"] = u["due"]
    if _ISO.fullmatch(str(u.get("check") or "")):
        out["check"] = u["check"]  # 3.2: a checkpoint's morning
    if isinstance(u.get("n"), int) and not isinstance(u.get("n"), bool) and u["n"] >= 0:
        out["n"] = u["n"]
    return out


def clean_sched(s):
    """3.2: my schedule for a plan, {days: [7 of 0-2], minutes, start?}; None if unusable."""
    if not isinstance(s, dict):
        return None
    days = s.get("days")
    if (not isinstance(days, list) or len(days) != 7
            or not all(isinstance(x, int) and not isinstance(x, bool) and 0 <= x <= 2 for x in days)
            or not any(days)):
        return None
    minutes = s.get("minutes")
    if not isinstance(minutes, int) or isinstance(minutes, bool) or not 10 <= minutes <= 600:
        return None
    out = {"days": list(days), "minutes": minutes}
    if _ISO.fullmatch(str(s.get("start") or "")):
        out["start"] = s["start"]
    return out


def clean_plan_doc(doc):
    """{deck, units}: units sorted by when they open, as plans.py reads them."""
    doc = doc if isinstance(doc, dict) else {}
    units = [u for u in map(_clean_unit, doc.get("units") or []) if u][:200]
    units.sort(key=lambda u: u["opens"])
    out = {"deck": str(doc.get("deck") or ""), "units": units}
    if _ISO.fullmatch(str(doc.get("end") or "")):
        out["end"] = doc["end"]
    ph = doc.get("phases") if isinstance(doc.get("phases"), dict) else {}
    catchup, taper = ph.get("catchup"), ph.get("taper")
    ok = lambda v, hi: isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= hi
    if (ok(catchup, 8) and catchup != 1) or ok(taper, 60):
        out["phases"] = {"catchup": catchup if ok(catchup, 8) and catchup != 1 else 0,
                         "taper": taper if ok(taper, 60) and out.get("end") else 0}
    return out


def clean_plan(p):
    """A plan from GET /board or /plans/*, coerced; None if unusable. The
    board's rows carry share/paused; the others carry `following`."""
    if not isinstance(p, dict) or not _PLAN_ID.fullmatch(str(p.get("id") or "")):
        return None
    following = p.get("following") if isinstance(p.get("following"), dict) else {}
    crew = p.get("crewDone") if isinstance(p.get("crewDone"), dict) else {}
    return {"id": p["id"], "name": clean_note(p.get("name"), 60) or "Plan",
            "owner": str(p.get("owner") or ""), "ownerName": clean_note(p.get("ownerName"), 60) or "?",
            "version": _as_int(p.get("version")) or 0, "doc": clean_plan_doc(p.get("doc")),
            "share": bool(p.get("share", following.get("share", True))),
            "paused": bool(p.get("paused", following.get("paused", False))),
            "followers": _as_int(p.get("followers")) or 0,
            "crewDone": {str(k): _as_int(v) for k, v in crew.items() if _as_int(v) is not None},
            "code": normalize_code(p.get("code")) if p.get("code") else "",
            "following": bool(following) or "share" in p,
            "sched": clean_sched(p.get("sched", following.get("sched")))}


def clean_offer(o):
    """A plan offered to one of my squads, from the board."""
    if not isinstance(o, dict) or not _PLAN_ID.fullmatch(str(o.get("id") or "")):
        return None
    return {"id": o["id"], "name": clean_note(o.get("name"), 60) or "Plan",
            "code": normalize_code(o.get("code")), "squad": str(o.get("squad") or ""),
            "ownerName": clean_note(o.get("ownerName"), 60) or "?"}
