"""Firebase REST client for Due Crew.

Call budget is the design constraint: a refresh is one read per friend (their
week doc, or their day docs on a client older than 2.9) plus the cheers
list; profiles ride the day's first fetch. Stats are only requested for
people who added you back, so a pending invite can never fail the batch.
A batch holds at most FRIENDS_PER_BATCH friends: the rules' consent check
spends an access call per friend, and a multi-document read gets 20.

Failure is never conflated with absence: batch_get and list_friends raise
TransportError on any non-200, so callers keep their caches and their
server-side state instead of treating an outage as "everything was deleted".

All calls have a 10s timeout and must run off the main thread. Firestore
requests retry once on a transport error — a pooled socket the server closed
while idle resets on first use — which is safe because everything routed
through _req is idempotent (batchGet is a read despite the POST). Auth calls
never retry: sign-up isn't idempotent. Writes stay on self-owned documents,
with one deliberate exception: send_cheer writes to the recipient's
cheers/{sender} doc, which the deployed rules allow only for senders the
recipient has added.
"""

import datetime
import hashlib
import json
import os
import re
import secrets
import string
import threading

import requests

# A Firebase web API key is a public client identifier, not a secret: it
# ships inside the add-on to every install, and access control lives entirely
# in firestore.rules + Auth. Secret scanners will flag it; that is expected.
DEFAULT_API_KEY = "AIzaSyBgXxrfGhuZ1Zrf_DURu4Sd3B9VZw42Q9I"
DEFAULT_PROJECT_ID = "anki-leaderboard-f6691"
AUTH_URL = "https://identitytoolkit.googleapis.com/v1/accounts"
TOKEN_URL = "https://securetoken.googleapis.com/v1/token"
TIMEOUT = 10
KEEP_DAYS = 7
# a squad member doc's row fields (joinedAt is the membership, never touched)
MEMBER_FIELDS = ("name", "day", "reviews", "studyTimeMs", "accuracy", "streak",
                 "updatedAt", "week", "emoji")
# The rules generation this client needs. The deployed firestore.rules allow
# `get` on meta/{RULES_MARKER} (no doc exists): 404 = current, 403 = stale.
# Bump together with the marker block in firestore.rules.
RULES_MARKER = "rules-v9"
# Firestore allows 20 exists()/get() calls per multi-document read, and
# isFriend() spends one per friend (an edge doc), or two (edge missing, then
# the profile array). Past that the WHOLE batch is refused: measured in the
# emulator, 21 friends with edges fail, and 11 without. Ten per batch is
# safe either way.
FRIENDS_PER_BATCH = 10
# 2.9: each client also writes users/{me}/shared/week, its last eight days in
# one doc. A friend whose profile says 2.9 or newer is read from it.
WEEK_DOC_SINCE = (2, 9, 0)
WEEK_FIELDS = ("v", "days", "updatedAt", "paused", "examDate", "awayFrom", "awayTo")
# The token endpoint's verdicts that mean "this sign-in is over" — as opposed
# to a network failure or a 5xx, which must NEVER sign anyone out: going
# offline is not the same as being signed out.
TERMINAL_AUTH = ("TOKEN_EXPIRED", "USER_DISABLED", "USER_NOT_FOUND",
                 "INVALID_REFRESH_TOKEN")


def firestore_base(project_id):
    return (f"https://firestore.googleapis.com/v1/projects/{project_id}"
            f"/databases/(default)/documents")


def doc_root(project_id):
    return f"projects/{project_id}/databases/(default)/documents"


class AuthError(Exception):
    """Carries the Firebase error code, e.g. EMAIL_EXISTS."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


class TransportError(Exception):
    """Request failed (network, 5xx, 429, auth) — the data may still exist.
    `status` is the HTTP status when there was a response, else None."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def _fv(v):
    if isinstance(v, dict):
        if len(v) == 1 and next(iter(v)).endswith("Value"):
            return v  # pre-encoded, e.g. {"timestampValue": ...}
        return {"mapValue": {"fields": {k: _fv(x) for k, x in v.items()}}}
    if isinstance(v, bool):
        return {"booleanValue": v}
    if isinstance(v, int):
        return {"integerValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    if isinstance(v, list):
        return {"arrayValue": {"values": [_fv(x) for x in v]}}
    return {"stringValue": str(v)}


def _pv(f):
    if "integerValue" in f:
        return int(f["integerValue"])
    if "doubleValue" in f:
        return float(f["doubleValue"])
    if "booleanValue" in f:
        return f["booleanValue"]
    if "stringValue" in f:
        return f["stringValue"]
    if "timestampValue" in f:
        return f["timestampValue"]
    if "arrayValue" in f:
        return [_pv(x) for x in f["arrayValue"].get("values", [])]
    if "mapValue" in f:
        return {k: _pv(x) for k, x in f["mapValue"].get("fields", {}).items()}
    return None


def _parse(fields):
    return {k: _pv(v) for k, v in (fields or {}).items()}


def _now_ts():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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


EMOJI_MAX = 16  # code points: one emoji, with its modifiers and joiners


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
    """The rules cap the field at size() <= 16, and rules size() counts
    UTF-16 units — measured in the emulator on 2026-09-18 (5 astral chars,
    10 units, accepted; 9 astral chars, 18 units, refused), not assumed.
    Python's len() counts code points, so the cap is checked in the rules'
    own unit. Too long is refused whole: never truncated into a broken
    glyph, never sent to be rejected."""
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


def _clock_label(prof, now_utc):
    """The day label a friend's client is on right now, from the clock its
    profile carries since 2.7 (`tz`: minutes east of UTC, `rollover`: the
    hour the day rolls over), or None for an older client. A fetch can then
    skip the docs that client cannot have written yet."""
    tz = _as_int(prof.get("tz"))
    if tz is None or not -900 <= tz <= 900:
        return None
    roll = _as_int(prof.get("rollover"))
    if roll is None or not 0 <= roll <= 23:
        roll = 4
    local = now_utc + datetime.timedelta(minutes=tz) - datetime.timedelta(hours=roll)
    return local.date().isoformat()


def _wanted(prof, labels, tomorrow, now_utc, light):
    """Which of a friend's day docs to read. A full fetch reads the week,
    plus tomorrow when their clock (or an unknown one) may already be
    there. A light fetch reads the one doc they are writing right now:
    their current label when their clock says which, else today and
    tomorrow, as every fetch did before 2.7."""
    label = _clock_label(prof, now_utc)
    extra = [tomorrow] if tomorrow and (label is None or label > labels[0]) else []
    if not light:
        return list(labels) + extra
    if label is None:
        return [labels[0]] + extra
    if label == tomorrow:
        return [tomorrow]
    return [label] if label in labels else [labels[0]]


def _clean_day(doc):
    """Coerce a daily_stats doc to trusted types; None stays None."""
    if doc is None:
        return None
    out = {}
    for key, conv in (("reviews", _as_int), ("studyTimeMs", _as_int),
                      ("accuracy", _as_float), ("streak", _as_int)):
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


def _version(text):
    """"2.9.0" -> (2, 9, 0); anything unparsable -> ()."""
    try:
        return tuple(int(x) for x in str(text or "").split(".")[:3])
    except ValueError:
        return ()


def has_week_doc(prof):
    """Whether this profile's client writes the week doc (2.9+)."""
    return _version((prof or {}).get("clientVersion")) >= WEEK_DOC_SINCE


def _week_days(doc, labels):
    """A week doc -> {label: day doc} for `labels`, shaped like the day docs
    older clients write, so everything downstream reads one form. The away
    spell rides the doc as a range; each day inside it is flagged here, the
    way sync_away used to write a doc per day for it."""
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
           ("accuracy", "share_retention"), ("streak", "share_streak"))


def shared_numbers(values, cfg):
    """The numbers the Privacy switches let out of `values` (keyed by the
    fields in METRICS). One gate for the day docs and, since 2.9, the squad
    row, which until then carried all four whatever the switches said. Just
    show up (2.8) lets none out; the switches keep their settings under it."""
    if cfg.get("show_up"):
        return {}
    return {field: values[field] for field, key in METRICS
            if cfg.get(key, True) and values.get(field) is not None}


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
        # v2.6 extras, each optional: older clients simply don't send them
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
    a whole invite. Until 2.9 the box took six characters, so a pasted
    invite arrived as "Study " and was refused."""
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
    """The squad's document id derives from its invite code. Knowing the
    code is knowing the id, and the id is the only way in: no directory."""
    return hashlib.sha1(f"due-crew-squad:{normalize_code(code)}".encode()).hexdigest()[:24]


def clean_squad_name(name):
    one_line = " ".join(str(name or "").split())
    return "".join(ch for ch in one_line if ch.isprintable())[:SQUAD_NAME_MAX]


def _clean_member(uid, fields):
    """Coerce a squad member doc to a trusted row; None if unusable."""
    if not isinstance(fields, dict):
        return None
    day = str(fields.get("day") or "")
    try:
        datetime.date.fromisoformat(day)
    except ValueError:
        day = ""
    acc = _as_float(fields.get("accuracy"))
    week = _as_int(fields.get("week"))
    return {"user_id": str(uid),
            "name": str(fields.get("name", "?")),
            "emoji": clean_emoji(fields.get("emoji")),
            "day": day,
            "reviews": _as_int(fields.get("reviews")),
            "time_ms": _as_int(fields.get("studyTimeMs")),
            "retention": acc if acc is not None and 0 <= acc <= 100 else None,
            "streak": _as_int(fields.get("streak")),
            "week": week if week is not None and 0 <= week <= 7 else None}


class FirebaseClient:
    def __init__(self, session_file):
        self.session_file = session_file
        self.api_key = DEFAULT_API_KEY
        self.project_id = DEFAULT_PROJECT_ID
        self.base = firestore_base(self.project_id)
        self.doc_root = doc_root(self.project_id)
        self.http = requests.Session()
        self._session_lock = threading.Lock()
        self._refresh_lock = threading.Lock()
        self.session = self._load_session()
        self._people = None  # the day's profiles, for light refreshes

    # ---- local session ----

    def _load_session(self):
        try:
            with open(self.session_file) as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_session(self):
        with self._session_lock:
            try:
                os.makedirs(os.path.dirname(self.session_file), exist_ok=True)
                tmp = self.session_file + ".tmp"
                with open(tmp, "w") as f:
                    json.dump(dict(self.session), f)
                os.chmod(tmp, 0o600)  # holds the refresh token
                os.replace(tmp, self.session_file)
            except OSError:
                pass

    @property
    def signed_in(self):
        return bool(self.session.get("refresh_token"))

    @property
    def session_dead(self):
        """The server refused my refresh token outright. Until 2.5.1 this
        looked like a network blip forever: every upload and fetch failed
        quietly and the board just aged. Cleared by signing in again."""
        return bool(self.session.get("auth_dead"))

    @property
    def user_id(self):
        return self.session.get("user_id", "")

    @property
    def email(self):
        return self.session.get("email", "")

    @property
    def display_name(self):
        return self.session.get("display_name", "")

    def sign_out(self):
        self.session = {}
        try:
            os.remove(self.session_file)
        except OSError:
            pass

    # ---- auth ----

    def _auth_post(self, endpoint, payload):
        try:
            r = self.http.post(f"{AUTH_URL}:{endpoint}", params={"key": self.api_key},
                               json=payload, timeout=TIMEOUT)
        except requests.RequestException:
            raise TransportError("auth request failed")
        data = r.json() if r.content else {}
        if r.status_code != 200:
            code = data.get("error", {}).get("message", "UNKNOWN")
            raise AuthError(code.split(" ")[0].rstrip(":"))
        return data

    def _store_tokens(self, data, email):
        if data["localId"] != self.session.get("user_id"):
            # different account: per-account markers must not carry over
            self.session = {}
        self.session.update({
            "user_id": data["localId"],
            "email": email,
            "id_token": data["idToken"],
            "refresh_token": data["refreshToken"],
        })
        self.session.pop("auth_dead", None)
        self._save_session()

    def sign_up(self, email, password, display_name):
        data = self._auth_post("signUp", {
            "email": email, "password": password, "returnSecureToken": True})
        self._store_tokens(data, email)
        uid = data["localId"]
        self.patch_doc(f"users/{uid}", {
            "displayName": display_name,
            "friends": [],
            "createdAt": {"timestampValue": _now_ts()},
        })
        self.session["display_name"] = display_name
        self._save_session()
        try:
            # 2.9: the code exists from the start, so Copy invite always copies
            self.ensure_friend_code(uid, None)
        except Exception:
            pass  # the account is made; Friends makes the code later
        return uid, display_name

    def sign_in(self, email, password):
        data = self._auth_post("signInWithPassword", {
            "email": email, "password": password, "returnSecureToken": True})
        self._store_tokens(data, email)
        uid = data["localId"]
        doc, status = self.get_doc(f"users/{uid}")
        if doc is None and status != 404:
            # transient failure — never treat it as a missing profile
            raise TransportError(f"profile fetch failed: {status}")
        name = (doc or {}).get("displayName") or email.split("@")[0]
        if doc is None:
            # genuinely gone (404): recreate a minimal profile
            self.patch_doc(f"users/{uid}", {"displayName": name, "friends": []})
        self.session["display_name"] = name
        self._save_session()
        return uid, name

    def send_reset(self, email):
        self._auth_post("sendOobCode", {"requestType": "PASSWORD_RESET", "email": email})

    def _refresh(self):
        with self._refresh_lock:
            rt = self.session.get("refresh_token")
            if not rt:
                return False
            try:
                r = self.http.post(TOKEN_URL, params={"key": self.api_key},
                                   data={"grant_type": "refresh_token",
                                         "refresh_token": rt},
                                   timeout=TIMEOUT)
            except requests.RequestException:
                return False  # offline is not signed out
            if r.status_code != 200:
                if 400 <= r.status_code < 500:
                    try:
                        msg = str((r.json().get("error") or {}).get("message") or "")
                    except Exception:
                        msg = ""
                    if msg.split(" ")[0].rstrip(":") in TERMINAL_AUTH:
                        self.session["auth_dead"] = True
                        self._save_session()
                return False
            data = r.json()
            self.session["id_token"] = data["id_token"]
            self.session["refresh_token"] = data.get("refresh_token", rt)
            self.session.pop("auth_dead", None)
            self._save_session()
            return True

    # ---- firestore primitives ----

    def _req(self, method, url, retry=True, **kw):
        headers = {"Authorization": f"Bearer {self.session.get('id_token', '')}"}
        try:
            r = self.http.request(method, url, headers=headers, timeout=TIMEOUT, **kw)
        except requests.RequestException:
            if retry:
                # second attempt rides a fresh connection: urllib3 has
                # already dropped the broken socket from the pool
                return self._req(method, url, retry=False, **kw)
            raise TransportError(f"{method} failed")
        if r.status_code == 401 and retry and self._refresh():
            return self._req(method, url, retry=False, **kw)
        return r

    def get_doc(self, path):
        r = self._req("GET", f"{self.base}/{path}")
        if r.status_code != 200:
            return None, r.status_code
        return _parse(r.json().get("fields")), 200

    # Writes to my own documents can only be refused by rules drift; a 403
    # on any of these flips the footer's "server catching up" hint. Social
    # writes (cheers, knocks, squad admin) are refused by design in normal
    # use and must not.
    HINT_LABELS = ("profile", "daily stats", "shared decks", "heatmap", "away", "friend",
                   "week")

    def patch_doc(self, path, data, mask=None, label=None):
        """label: names the write in a console line when the server rejects
        it — a silent False here once hid a rules gap for weeks."""
        mask_q = "&".join(f"updateMask.fieldPaths={k}" for k in (mask or data))
        r = self._req("PATCH", f"{self.base}/{path}?{mask_q}",
                      json={"fields": {k: _fv(v) for k, v in data.items()}})
        ok = r.status_code in (200, 201)
        if not ok and label:
            print(f"due crew: {label} write rejected ({r.status_code}) at {path}"
                  " — if this persists, re-publish firestore.rules")
            if r.status_code == 403 and label in self.HINT_LABELS:
                # instant stale-rules hint; the daily probe can clear it
                self.session["rules_stale_hint"] = True
                self._save_session()
        return ok

    def delete_doc(self, path):
        return self._req("DELETE", f"{self.base}/{path}").status_code == 200

    # ---- rules freshness ----

    def check_rules(self, today_label):
        """One background GET per day against the marker doc the deployed
        rules expose. 404 = current (clears any hint), 403 = stale. Network
        trouble changes nothing — yesterday's answer stands."""
        cached = self.session.get("rules_check") or {}
        if cached.get("day") == today_label:
            return self.rules_stale
        r = self._req("GET", f"{self.base}/meta/{RULES_MARKER}")
        if r.status_code == 404:
            self.session["rules_check"] = {"day": today_label, "stale": False}
            self.session.pop("rules_stale_hint", None)
        elif r.status_code == 403:
            self.session["rules_check"] = {"day": today_label, "stale": True}
        else:
            return self.rules_stale  # inconclusive; don't cache
        self._save_session()
        return self.rules_stale

    @property
    def rules_stale(self):
        """No network: the last probe's verdict, or any write-403 hint."""
        return bool((self.session.get("rules_check") or {}).get("stale")
                    or self.session.get("rules_stale_hint"))

    def batch_get(self, paths):
        """Many docs, one round trip. {path: fields-or-None(missing)}.
        Raises TransportError on failure — missing and failed are distinct."""
        out = {p: None for p in paths}
        if not paths:
            return out
        r = self._req("POST", f"{self.base}:batchGet",
                      json={"documents": [f"{self.doc_root}/{p}" for p in paths]})
        if r.status_code != 200:
            raise TransportError(f"batchGet failed: {r.status_code}", r.status_code)
        for item in r.json():
            if "found" in item:
                name = item["found"]["name"]
                out[name[len(self.doc_root) + 1:]] = _parse(item["found"].get("fields"))
        return out

    def batch_get_people(self, paths, uid):
        """batch_get for docs that belong to several people, in batches of at
        most FRIENDS_PER_BATCH other people each (my own docs cost the rules
        nothing and ride the first), fetched side by side. The same reads as
        one batch. A failed batch fails the whole call, a 403 first, so the
        caller can tell "someone removed me" from an outage."""
        by_owner = {}
        for p in paths:
            parts = p.split("/")
            owner = parts[1] if len(parts) > 2 and parts[0] == "users" else ""
            by_owner.setdefault(owner, []).append(p)
        mine = by_owner.pop(uid, []) + by_owner.pop("", [])
        others = list(by_owner.values())
        groups = [[p for ps in others[i:i + FRIENDS_PER_BATCH] for p in ps]
                  for i in range(0, len(others), FRIENDS_PER_BATCH)] or [[]]
        groups[0] = mine + groups[0]
        if len(groups) == 1:
            return self.batch_get(groups[0])
        results, errors = [None] * len(groups), []

        def run(i):
            try:
                results[i] = self.batch_get(groups[i])
            except TransportError as e:
                errors.append(e)

        threads = [threading.Thread(target=run, args=(i,), daemon=True)
                   for i in range(len(groups))]
        for t in threads:
            t.start()
        for t in threads:
            t.join(3 * TIMEOUT)
        if errors or any(r is None for r in results):
            raise next((e for e in errors if e.status == 403), None) or (
                errors[0] if errors else TransportError("batchGet timed out"))
        out = {}
        for r in results:
            out.update(r)
        return out

    @staticmethod
    def _structured(collection, filters=(), order_by=None, limit=None):
        query = {"from": [{"collectionId": collection}]}
        if filters:
            query["where"] = {"compositeFilter": {"op": "AND", "filters": [
                {"fieldFilter": {"field": {"fieldPath": f}, "op": op,
                                 "value": _fv(v)}}
                for f, op, v in filters]}}
        if order_by:
            field, direction = order_by
            query["orderBy"] = [{"field": {"fieldPath": field},
                                 "direction": direction}]
        if limit:
            query["limit"] = int(limit)
        return query

    def run_query(self, collection, filters=(), parent="", order_by=None,
                  limit=300):
        """filters: [(field, op, value)] with op in EQUAL/GREATER_THAN/...;
        parent: document path whose subcollection is queried. orderBy on a
        single field needs only the automatic single-field index. Returns
        [(doc_id, fields)] in query order; raises TransportError."""
        url = f"{self.base}/{parent}:runQuery" if parent else f"{self.base}:runQuery"
        r = self._req("POST", url, json={"structuredQuery": self._structured(
            collection, filters, order_by, limit)})
        if r.status_code != 200:
            raise TransportError(f"query failed: {r.status_code}", r.status_code)
        out = []
        for item in r.json():
            doc = item.get("document")
            if doc:
                out.append((doc["name"].rsplit("/", 1)[-1],
                            _parse(doc.get("fields"))))
        return out

    def run_aggregation(self, collection, parent, aggregations, filters=()):
        """aggregations: {alias: "count"} or {alias: ("sum", field)}. One
        billed read per 1,000 index entries, however many rows match.
        Returns {alias: number}; raises TransportError."""
        aggs = []
        for alias, spec in aggregations.items():
            if spec == "count":
                aggs.append({"alias": alias, "count": {}})
            else:
                aggs.append({"alias": alias,
                             "sum": {"field": {"fieldPath": spec[1]}}})
        body = {"structuredAggregationQuery": {
            "structuredQuery": self._structured(collection, filters),
            "aggregations": aggs}}
        url = (f"{self.base}/{parent}:runAggregationQuery" if parent
               else f"{self.base}:runAggregationQuery")
        r = self._req("POST", url, json=body)
        if r.status_code != 200:
            raise TransportError(f"aggregation failed: {r.status_code}", r.status_code)
        out = {}
        for item in r.json():
            fields = (item.get("result") or {}).get("aggregateFields") or {}
            for alias, value in fields.items():
                out[alias] = _pv(value)
        return out

    # ---- friends ----

    def list_friends(self, uid, check_edges=False):
        """(own_fields, [(fid, prof, mutual)], pending_names).
        Mutual = they added me back: their profile array says so (clients up
        to 2.4) or their edge doc users/{fid}/friends/{me} exists (2.5+).
        The edge check is one batchGet, only for people the array can't
        vouch for, and only when asked (full fetches) — a read per pending
        friend per day. Raises TransportError on any failure, including a
        missing own profile, so callers never mistake an outage for an
        empty crew."""
        # One round trip, not two: my profile and my friends' ride one
        # batchGet, using the friend list remembered from last time. Anyone
        # added since (on another device, say) costs a second, smaller batch.
        cached = [f for f in (self.session.get("friend_ids") or []) if isinstance(f, str)]
        profiles = self.batch_get([f"users/{uid}"] + [f"users/{f}" for f in cached])
        own = profiles.pop(f"users/{uid}", None)
        if own is None:
            raise TransportError("own profile unavailable: 404", 404)
        friends = [f for f in (own.get("friends") or []) if isinstance(f, str)]
        unseen = [f for f in friends if f not in cached]
        if unseen:
            profiles.update(self.batch_get([f"users/{f}" for f in unseen]))
        if friends != cached:
            self.session["friend_ids"] = friends
            self._save_session()
        by_array = {fid for fid in friends
                    if uid in ((profiles.get(f"users/{fid}") or {}).get("friends") or [])}
        by_edge = set()
        unsure = [fid for fid in friends if fid not in by_array
                  and profiles.get(f"users/{fid}") is not None]
        if check_edges and unsure:
            edges = self.batch_get([f"users/{fid}/friends/{uid}" for fid in unsure])
            by_edge = {fid for fid in unsure if edges.get(f"users/{fid}/friends/{uid}") is not None}
        resolved, pending = [], []
        for fid in friends:
            prof = profiles.get(f"users/{fid}")
            if prof is None:
                continue  # deleted account; skip quietly
            mutual = fid in by_array or fid in by_edge
            resolved.append((fid, prof, mutual))
            if not mutual:
                pending.append(prof.get("displayName", "?"))
        return own, resolved, pending

    def sync_friend_edges(self, uid, friends):
        """Mirror my friends list as edge docs (users/{me}/friends/{fid}), the
        shape 2.5+ clients read for "did they add me back". Session-guarded:
        the steady state writes nothing; adding or removing a friend writes
        or deletes one doc. Returns True when the mirror matches."""
        want = sorted({f for f in friends if isinstance(f, str)})
        state = self.session.get("friend_edges") or {}
        have = set(state.get("ids") or [])
        if state.get("uid") == uid and sorted(have) == want:
            return True
        ok = True
        for fid in sorted(set(want) - have):
            if self.patch_doc(f"users/{uid}/friends/{fid}",
                              {"at": {"timestampValue": _now_ts()}}, label="friend"):
                have.add(fid)
            else:
                ok = False
        for fid in sorted(have - set(want)):
            if self.delete_doc(f"users/{uid}/friends/{fid}"):
                have.discard(fid)
            else:
                ok = False
        self.session["friend_edges"] = {"uid": uid, "ids": sorted(have)}
        self._save_session()
        return ok

    def ensure_friend_code(self, uid, existing):
        if existing:
            return existing
        for _ in range(3):
            code = "".join(secrets.choice(string.ascii_uppercase + string.digits)
                           for _ in range(6))
            # collision with someone else's code -> rules reject -> retry
            if self.patch_doc(f"friend_codes/{code}", {"userId": uid}):
                self.patch_doc(f"users/{uid}", {"friendCode": code})
                return code
        return None

    def add_friend(self, uid, code, own_friends, my_name=None):
        """Add by code. Since 2.9 the add also knocks, with their own code in
        the knock (rules-v9 lets that through), so their board offers a
        one-click Add back instead of waiting for my code to come back by
        chat. On older rules the knock is refused and "knocked" says so."""
        code = friend_code_from(code) or str(code or "").strip().upper()
        doc, _ = self.get_doc(f"friend_codes/{code}")
        fid = (doc or {}).get("userId")
        if not fid:
            return None, "That code doesn't match anyone."
        if fid == uid:
            return None, "That's your own code."
        if fid in own_friends:
            return None, "Already in your crew."
        prof, _ = self.get_doc(f"users/{fid}")
        if prof is None:
            return None, "That code doesn't match anyone."
        if not self.set_friends(uid, own_friends + [fid]):
            return None, "Couldn't save. Try again."
        mutual = uid in (prof.get("friends") or [])
        knocked = bool(my_name) and not mutual and self.send_code_knock(fid, uid, my_name, code)
        return {"user_id": fid,
                "name": prof.get("displayName", "?"),
                "mutual": mutual, "knocked": knocked}, None

    def set_friends(self, uid, friends):
        """The array (what every client reads today) and the edge mirror."""
        ok = self.patch_doc(f"users/{uid}", {"friends": friends})
        if ok:
            self.sync_friend_edges(uid, friends)
        return ok

    # ---- board ----

    def fetch_decks(self, uids):
        """{uid: decks} for the Decks tab, fetched when someone looks rather
        than on every refresh. One read per person, in batches the rules
        allow."""
        docs = self.batch_get_people([f"users/{u}/shared/decks" for u in uids], self.user_id)
        return {u: _clean_decks((docs.get(f"users/{u}/shared/decks") or {}).get("decks"))
                for u in uids}

    def list_cheers(self, uid):
        """{sender_uid: fields}: one list request, one read when empty.
        Until 2.7 every refresh batch-read a cheers path per friend, present
        or not. Raises TransportError."""
        r = self._req("GET", f"{self.base}/users/{uid}/cheers?pageSize=100")
        if r.status_code != 200:
            raise TransportError(f"cheers list failed: {r.status_code}", r.status_code)
        return {doc["name"].rsplit("/", 1)[-1]: _parse(doc.get("fields"))
                for doc in r.json().get("documents", [])}

    def delete_cheers(self, uid, senders):
        """A cheer is delivered once, then its doc goes, so the collection is
        empty in the steady state. A delete that fails leaves the doc for
        next time; the per-sender seen marks keep it from playing twice."""
        for sender in senders:
            self.delete_doc(f"users/{uid}/cheers/{sender}")

    def fetch_board(self, uid, labels, tomorrow=None, include_shared=True, check_edges=None,
                    light=False, own_days=None, cached_people=False, now_utc=None):
        """labels: the week's day labels, newest first. A friend on 2.9 or
        newer is one read, their week doc, on a full fetch or a light one.
        An older client's day docs are read as before: the week on a full
        fetch, the one doc they are writing now on a light one (_wanted).
        own_days: my own uploads by label, kept by the session; those are
        never read back. cached_people: reuse the day's profiles instead of
        reading them again; a 403 on the stats batch then means someone
        removed me, and the profiles are read once more. Shared-deck docs
        ride along when include_shared. Raises TransportError on failure;
        the caller keeps its cache."""
        if check_edges is None:
            check_edges = include_shared
        now_utc = now_utc or datetime.datetime.now(datetime.timezone.utc)
        day = labels[0] if labels else ""
        own_days = own_days or {}
        span = list(labels) + ([tomorrow] if tomorrow else [])

        def people(fresh):
            cache = self._people
            if (not fresh and cached_people and cache
                    and cache["uid"] == uid and cache["day"] == day):
                return cache["own"], cache["resolved"], cache["pending"], False
            own, resolved, pending = self.list_friends(uid, check_edges=check_edges)
            self._people = {"uid": uid, "day": day, "own": own,
                            "resolved": resolved, "pending": pending}
            return own, resolved, pending, True

        def plan(own, resolved, no_week=()):
            """(mutual, everyone, show, weekly, paths): `show` is the labels
            each person's row gets, `weekly` who is read from a week doc."""
            mutual = [(fid, prof) for fid, prof, m in resolved if m]
            everyone = [(uid, own)] + mutual
            show, weekly, paths = {}, set(), []
            for u, prof in everyone:
                use_week = has_week_doc(prof) and u not in no_week
                if u == uid:
                    show[u] = [labels[0]] if light else list(labels)
                    need = [lb for lb in show[u] if lb not in own_days]
                    if need and use_week:
                        weekly.add(u)
                        paths.append(f"users/{u}/shared/week")
                    else:
                        paths += [f"users/{u}/daily_stats/{lb}" for lb in need]
                elif use_week:
                    show[u] = span  # the whole week comes with the one read
                    weekly.add(u)
                    paths.append(f"users/{u}/shared/week")
                else:
                    show[u] = _wanted(prof, labels, tomorrow, now_utc, light)
                    paths += [f"users/{u}/daily_stats/{lb}" for lb in show[u]]
            if include_shared:
                paths += [f"users/{u}/shared/decks" for u, _ in everyone]
            return mutual, everyone, show, weekly, paths

        own, resolved, pending, fresh = people(fresh=False)
        mutual, everyone, show, weekly, paths = plan(own, resolved)
        try:
            docs = self.batch_get_people(paths, uid)
        except TransportError as e:
            if fresh or e.status != 403:
                raise
            own, resolved, pending, fresh = people(fresh=True)
            mutual, everyone, show, weekly, paths = plan(own, resolved)
            docs = self.batch_get_people(paths, uid)
        # a 2.9 client that hasn't pushed since updating has no week doc yet:
        # its day docs, in a second and smaller read
        late = {u for u in weekly if docs.get(f"users/{u}/shared/week") is None}
        if late:
            _m, _e, show2, _w, paths2 = plan(own, resolved, no_week=late)
            paths2 = [p for p in paths2 if "/daily_stats/" in p and p.split("/")[1] in late]
            if paths2:
                docs.update(self.batch_get_people(paths2, uid))
            for u in late:
                show[u] = show2[u]
            weekly -= late
        cheer_docs = self.list_cheers(uid)

        entries = []
        for u, prof in everyone:
            decks = None
            if include_shared:
                decks = _clean_decks(
                    (docs.get(f"users/{u}/shared/decks") or {}).get("decks"))
            week = docs.get(f"users/{u}/shared/week") if u in weekly else None
            from_week = _week_days(week, show[u]) if week is not None else {}
            head = week if week is not None else prof  # 2.9: the week doc is fresher
            days, stamps = {}, [str(prof.get("lastUpdated") or "")]
            if week is not None:
                stamps.append(str(week.get("updatedAt") or ""))
            for lb in show[u]:
                if u == uid and lb in own_days:
                    raw = own_days.get(lb)
                elif week is not None:
                    raw = from_week.get(lb)
                else:
                    raw = docs.get(f"users/{u}/daily_stats/{lb}")
                days[lb] = _clean_day(raw)
                stamps.append(str((raw or {}).get("updatedAt") or ""))
            if u == uid:
                stamps.append(str(self.session.get("last_ok") or ""))
            entries.append({
                "user_id": u,
                "name": str(prof.get("displayName", "?")),
                "emoji": clean_emoji(prof.get("emoji")),
                "you": u == uid,
                "paused": bool(head.get("paused")),
                # a profile may be a day old now; a day doc says when its
                # numbers last changed, which is what "last active" means
                "last_updated": max(stamps),
                "exam_date": str(head.get("examDate") or ""),
                "days": days,
                "decks": decks,  # None = not fetched this time
            })

        cheers = []
        for fid, prof in mutual:
            doc = cheer_docs.get(fid)
            # v2.7: any one emoji. What isn't one is dropped, whatever the
            # rules let through; the flurry never rains text.
            emoji = clean_emoji((doc or {}).get("emoji"))
            if doc and emoji:
                cheers.append({"from": fid,
                               # profile name, not the doc's: senders can't spoof
                               "name": str(prof.get("displayName", "?")),
                               "emoji": emoji,
                               "at": str(doc.get("at", "")),
                               "note": clean_note(doc.get("note"))})
        if cheer_docs:
            self.delete_cheers(uid, list(cheer_docs))  # delivered, or junk: either way done
        return {"entries": entries, "pending": pending, "cheers": cheers,
                "my_friends": [fid for fid, _p, _m in resolved],
                "my_code": str(own.get("friendCode") or "")}

    def send_cheer(self, to_uid, from_uid, from_name, emoji, note=None):
        """One write; overwrites any previous cheer to the same person.
        A note needs rules-v5: if the server still runs older rules the
        cheer goes again without it and the result is "no-note", so the
        sender hears that the words stayed behind."""
        emoji = clean_emoji(emoji)
        if not emoji:
            return False  # nothing that isn't one emoji is ever sent
        path = f"users/{to_uid}/cheers/{from_uid}"
        data = {"emoji": emoji, "name": from_name,
                "at": {"timestampValue": _now_ts()}}
        # note is always in the mask: a bare cheer must not re-deliver the
        # words from the last one (the doc is overwritten, not replaced)
        mask = list(data) + ["note"]
        note = clean_note(note)
        if note:
            if self.patch_doc(path, dict(data, note=note), mask, label="cheer note"):
                return True
            return "no-note" if self.patch_doc(path, data, mask) else False
        return self.patch_doc(path, data, mask)

    # ---- upload ----

    METRICS = METRICS

    def _day_doc(self, label, values, cfg):
        """(doc, mask) for one daily_stats write. Every field is always in
        the mask, so a toggled-off (or absent) metric is DELETED server-side,
        not left stale. `studied` is the numbers-free floor the Days view
        stands on; it shares whenever sharing isn't paused."""
        doc = {"date": label, "studied": bool(values.get("reviews"))}
        mask = ["date", "studied"] + [field for field, _key in METRICS]
        doc.update(shared_numbers(values, cfg))
        # v2.2: the status bubble (today's doc only — callers pass it) and
        # the away flag; both always in the mask, so clearing them clears.
        mask += ["status", "away", "awayTo"]
        status = clean_note(values.get("status"))
        if status:
            doc["status"] = status
        away_to = away_on(label, cfg)
        if away_to:
            doc["away"] = True
            doc["awayTo"] = away_to
        return doc, mask

    def _put_day(self, uid, label, values, cfg):
        """Write one day's doc, skipped when identical to the last success.
        The digest covers the post-toggle doc, so flipping a share toggle
        (not just new reviews) re-writes the day."""
        doc, mask = self._day_doc(label, values, cfg)
        digest = hashlib.sha1(
            json.dumps(doc, sort_keys=True).encode()).hexdigest()
        hashes = self.session.setdefault("day_hashes", {})
        # v2.7: what I uploaded, by label, so the board never reads my own
        # docs back (a session from before 2.7 learns them as it goes)
        mine = self.session.setdefault("own_days", {})
        if hashes.get(label) == digest:
            if label not in mine:
                mine[label] = doc
                self._save_session()
            return True
        # outside the digest: it says when the numbers last changed, and
        # must not itself be a change
        stamp = _now_ts()
        if not self.patch_doc(f"users/{uid}/daily_stats/{label}",
                              dict(doc, updatedAt={"timestampValue": stamp}),
                              mask + ["updatedAt"], label="daily stats"):
            return False
        hashes[label] = digest
        mine[label] = dict(doc, updatedAt=stamp)
        for old in sorted(hashes)[:-(KEEP_DAYS + 1)]:
            hashes.pop(old, None)
        for old in sorted(mine)[:-(KEEP_DAYS + 2)]:
            mine.pop(old, None)
        self._save_session()
        return True

    def upload_today(self, uid, display_name, label, stats, cfg, version=None, clock=None):
        """Today's day doc, then the profile. Since 2.9 the profile is written
        only when one of its fields changed or today's numbers did. Until then
        every push rewrote it to move lastUpdated, including each return to a
        stale Decks screen with nothing studied."""
        ok = True
        wrote_day = False
        if not cfg.get("paused"):
            values = {"reviews": int(stats.reviews),
                      "studyTimeMs": int(stats.time_ms),
                      "accuracy": None if stats.accuracy is None else float(stats.accuracy),
                      "streak": int(stats.streak),
                      "status": cfg.get("status")}
            before = (self.session.get("day_hashes") or {}).get(label)
            ok = self._put_day(uid, label, values, cfg)
            wrote_day = (self.session.get("day_hashes") or {}).get(label) != before
            ok = self.sync_away(uid, label, cfg) and ok
            self._cleanup(uid, label)
        profile = {
            "displayName": display_name,
            "paused": bool(cfg.get("paused")),
        }
        if clock:
            # v2.7: my clock, so a friend's client can tell which day label
            # I'm on and skip reading the docs I can't have written yet
            profile["tz"] = int(clock.get("tz", 0))
            profile["rollover"] = int(clock.get("rollover", 4))
        if version:
            # so "is this person on a broken build?" is one read, not a
            # conversation. Not a secret, not shown to anyone in the UI.
            profile["clientVersion"] = str(version)[:20]
        # examDate rides the always-in-the-mask pattern: unset, past, or
        # paused thereby DELETES it server-side, never stale. openBoard (the
        # v2.0–2.2 Everyone flag) is cleared the same way.
        mask = list(profile) + ["lastUpdated", "examDate", "openBoard", "emoji"]
        exam = _exam_value(cfg.get("exam_date"), label)
        if exam and not cfg.get("paused"):
            profile["examDate"] = exam
        emoji = clean_emoji(cfg.get("emoji"))
        if emoji:
            profile["emoji"] = emoji
        digest = hashlib.sha1(json.dumps(profile, sort_keys=True).encode()).hexdigest()
        if wrote_day or self.session.get("profile_hash") != digest:
            data = dict(profile, lastUpdated={"timestampValue": _now_ts()})
            if self.patch_doc(f"users/{uid}", data, mask, label="profile"):
                self.session["profile_hash"] = digest
            else:
                ok = False
        if ok:
            # Settings: "Synced 2m ago". Also when nothing needed writing: the
            # hashes say the server already holds exactly this.
            self.session["last_ok"] = _now_ts()
        self._save_session()
        own, _status = self.get_doc(f"users/{uid}") if not self.session.get("friend_edges") else (None, 0)
        if own is not None:  # first run on 2.5: mirror the existing list once
            self.sync_friend_edges(uid, [f for f in (own.get("friends") or []) if isinstance(f, str)])
        return ok

    def upload_week(self, uid, labels, cfg):
        """users/{me}/shared/week (2.9): my last eight days in one doc, built
        from what _put_day uploaded (the session's own_days), so a friend's
        refresh reads my whole week at the price of one doc. Hash-guarded like
        the day docs. The away spell rides as a range, and readers flag its
        days. Paused: the days go and the doc says so. Every field is always
        in the mask, so whatever isn't sent is deleted."""
        if not labels:
            return True
        try:
            oldest = datetime.date.fromisoformat(labels[-1])
        except ValueError:
            return True
        # one day past my week: a friend a day behind me still finds theirs
        window = list(labels) + [(oldest - datetime.timedelta(days=1)).isoformat()]
        paused = bool(cfg.get("paused"))
        mine = self.session.get("own_days") or {}
        days, stamps = {}, []
        if not paused:
            for lb in window:
                d = mine.get(lb)
                if not isinstance(d, dict):
                    continue
                stamps.append(str(d.get("updatedAt") or ""))
                days[lb] = {k: v for k, v in d.items()
                            if k not in ("updatedAt", "date", "away", "awayTo")}
        doc = {"v": 1, "days": days, "paused": paused}
        exam = _exam_value(cfg.get("exam_date"), labels[0])
        if exam and not paused:
            doc["examDate"] = exam
        rng = away_range(cfg)
        if rng and not paused:
            doc["awayFrom"], doc["awayTo"] = rng[0].isoformat(), rng[1].isoformat()
        digest = hashlib.sha1(json.dumps(doc, sort_keys=True).encode()).hexdigest()
        if self.session.get("week_hash") == digest:
            return True
        stamp = max(stamps) if stamps and max(stamps) else _now_ts()
        if not self.patch_doc(f"users/{uid}/shared/week",
                              dict(doc, updatedAt={"timestampValue": stamp}),
                              list(WEEK_FIELDS), label="week"):
            return False
        self.session["week_hash"] = digest
        self._save_session()
        return True

    def sync_away(self, uid, today_label, cfg):
        """Flag the days of an away spell so the crew sees the plane while
        the person is, by definition, not syncing: the coming 30 days plus
        the past week (today rides the day doc). Session-guarded, so the
        steady state adds zero writes; shrinking or clearing the spell
        unflags what it had flagged (future days lose their doc, past days
        keep their numbers)."""
        rng = away_range(cfg)
        base = datetime.date.fromisoformat(today_label)
        want = []
        if rng and not cfg.get("paused"):
            d = max(rng[0], base - datetime.timedelta(days=6))
            hi = min(rng[1], base + datetime.timedelta(days=30))
            while d <= hi:
                if d != base:
                    want.append(d.isoformat())
                d += datetime.timedelta(days=1)
        state = self.session.get("away") or {}
        key = [rng[0].isoformat(), rng[1].isoformat()] if rng else []
        written = set(state.get("labels") or [])
        ok = True
        if state.get("range") != key:
            for lb in sorted(written - set(want)):
                path = f"users/{uid}/daily_stats/{lb}"
                if lb > today_label:
                    ok = self.delete_doc(path) and ok
                else:
                    ok = self.patch_doc(path, {}, ["away", "awayTo"], label="away") and ok
            written &= set(want)
        for lb in want:
            if lb in written:
                continue
            if self.patch_doc(f"users/{uid}/daily_stats/{lb}",
                              {"away": True, "awayTo": rng[1].isoformat()},
                              label="away"):
                written.add(lb)
            else:
                ok = False
        if state.get("range") != key or set(state.get("labels") or []) != written:
            self.session["away"] = {"range": key, "labels": sorted(written)}
            self._save_session()
        return ok

    def upload_backfill(self, uid, days, cfg, labels=None):
        """Fill the last week's studied days the server missed — a day only
        exists server-side if a sync ran while it was 'today', which is how
        a 40-day streak could sit next to a half-empty dot row. Hash-guarded:
        steady state adds zero writes. labels: the window the days came
        from; its other days had nothing to write, and my own row can know
        they are empty without reading the server for them."""
        if cfg.get("paused"):
            return True
        ok = True
        for d in days or []:
            values = {"reviews": int(d["reviews"]),
                      "studyTimeMs": int(d["time_ms"]),
                      "accuracy": None if d["accuracy"] is None else float(d["accuracy"]),
                      "streak": int(d["streak"])}
            ok = self._put_day(uid, d["label"], values, cfg) and ok
        mine = self.session.setdefault("own_days", {})
        written = {d["label"] for d in days or []}
        empty = [lb for lb in (labels or [])[1:] if lb not in written and lb not in mine]
        for lb in empty:
            mine[lb] = None  # known empty: nothing to read back
        if empty:
            self._save_session()
        return ok

    def upload_shared(self, uid, decks):
        """Skips the write when nothing changed since the last upload."""
        digest = hashlib.sha1(
            json.dumps(decks, sort_keys=True).encode()).hexdigest()
        if self.session.get("shared_hash") == digest:
            return True
        if not self.patch_doc(f"users/{uid}/shared/decks", {"decks": decks},
                              label="shared decks"):
            return False
        self.session["shared_hash"] = digest
        self._save_session()
        return True

    def upload_heatmap(self, uid, counts):
        """counts: {day_label: n}. One doc; write skipped when unchanged."""
        digest = hashlib.sha1(
            json.dumps(counts, sort_keys=True).encode()).hexdigest()
        if self.session.get("heatmap_hash") == digest:
            return True
        if not self.patch_doc(f"users/{uid}/shared/heatmap", {"counts": counts},
                              label="heatmap"):
            return False
        self.session["heatmap_hash"] = digest
        self.session.pop("heatmap_deleted", None)
        self._save_session()
        return True

    def fetch_heatmap(self, uid):
        """{day_label: n} or None when the friend doesn't share (or 403)."""
        doc, _status = self.get_doc(f"users/{uid}/shared/heatmap")
        counts = (doc or {}).get("counts")
        if not isinstance(counts, dict):
            return None
        return {str(k): _as_int(v) or 0 for k, v in counts.items()}

    def delete_heatmap(self, uid):
        self.delete_doc(f"users/{uid}/shared/heatmap")
        self.session.pop("heatmap_hash", None)
        self.session["heatmap_deleted"] = True  # retract once, not per sync
        self._save_session()

    # ---- squads ----

    def create_squad(self, uid, name, my_name):
        """A squad doc under the id its invite code derives, plus my own
        member doc. Retries a fresh code if the id is somehow taken."""
        name = clean_squad_name(name)
        if not name:
            return None
        for _ in range(3):
            code = new_squad_code()
            sid = squad_id(code)
            if not self.patch_doc(f"squads/{sid}", {
                    "name": name, "founder": uid, "open": True,
                    "createdAt": {"timestampValue": _now_ts()}}):
                continue
            self.patch_doc(f"squads/{sid}/members/{uid}", {
                "name": my_name, "joinedAt": {"timestampValue": _now_ts()}})
            self.session.setdefault("squad_hashes", {}).pop(sid, None)
            self._save_session()
            return {"id": sid, "code": code, "name": name, "founder": uid}
        return None

    def peek_squad(self, code):
        """The join preview: (info-or-None, status). 404 = no such squad."""
        sid = squad_id(code)
        doc, status = self.get_doc(f"squads/{sid}")
        if doc is None:
            return None, status
        return {"id": sid, "code": normalize_code(code),
                "name": clean_squad_name(doc.get("name")) or "?",
                "founder": str(doc.get("founder") or ""),
                "open": doc.get("open") is True}, status

    def join_squad(self, uid, sid, my_name):
        """One write; rules refuse it when the door is locked (403)."""
        return self._patch_status(f"squads/{sid}/members/{uid}", {
            "name": my_name, "joinedAt": {"timestampValue": _now_ts()}})

    def leave_squad(self, uid, sid):
        self.session.get("squad_hashes", {}).pop(sid, None)
        self._save_session()
        return self.delete_doc(f"squads/{sid}/members/{uid}")

    def remove_member(self, sid, member_uid):
        """Founder only, by rule."""
        return self.delete_doc(f"squads/{sid}/members/{member_uid}")

    def block_member(self, sid, member_uid, banned):
        """Founder only, by rule: add to the ban list, then remove. `banned`
        is the current list (from the last fetch); the write replaces it."""
        new = sorted(set(banned or []) | {member_uid})[:200]
        if not self.patch_doc(f"squads/{sid}", {"banned": new}, ["banned"], label="squad block"):
            return False
        self.delete_doc(f"squads/{sid}/members/{member_uid}")
        return True

    def set_founder(self, sid, member_uid):
        """Founder only, by rule; the new founder must already be a member."""
        return self.patch_doc(f"squads/{sid}", {"founder": member_uid}, ["founder"],
                              label="squad founder")

    def set_squad_open(self, sid, is_open):
        """Founder only, by rule. Locked = no new members, existing stay."""
        return self.patch_doc(f"squads/{sid}", {"open": bool(is_open)}, ["open"],
                              label="squad lock")

    def fetch_squad(self, sid):
        """The squad doc plus every member's row — one read each; squads are
        the size of a class, not the world. None when the squad is gone.
        Raises TransportError (403 = not a member any more)."""
        doc, status = self.get_doc(f"squads/{sid}")
        if doc is None:
            if status == 404:
                return None
            raise TransportError(f"squad get failed: {status}", status)
        rows = []
        for uid, fields in self.run_query("members", parent=f"squads/{sid}",
                                          limit=1000):
            row = _clean_member(uid, fields)
            if row:
                rows.append(row)
        return {"id": sid, "name": clean_squad_name(doc.get("name")) or "?",
                "founder": str(doc.get("founder") or ""),
                "open": doc.get("open") is True,
                "banned": [b for b in (doc.get("banned") or []) if isinstance(b, str)],
                "rows": rows}

    def upload_squad_rows(self, uid, row, squad_ids):
        """My row into every squad I'm in: the member doc gets today's
        numbers (joinedAt stays). Hash-guarded per squad. Returns the ids
        whose write came back 403 — I was removed, or the squad is gone."""
        gone = []
        hashes = self.session.setdefault("squad_hashes", {})
        data = dict(row)
        data["updatedAt"] = {"timestampValue": _now_ts()}
        digest = hashlib.sha1(json.dumps(row, sort_keys=True).encode()).hexdigest()
        for sid in squad_ids:
            if hashes.get(sid) == digest:
                continue
            # must_exist: a row update may never CREATE membership. Until
            # 2.5.1 it could — a PATCH to a missing doc is an insert, so a
            # member the founder had removed rejoined an open squad on their
            # very next sync, and "Remove" quietly undid itself.
            # every row field is in the mask, so a number the row no longer
            # carries (show-up mode) is deleted, not left standing
            status = self._patch_status(f"squads/{sid}/members/{uid}", data,
                                        mask=list(MEMBER_FIELDS), must_exist=True)
            if status in (200, 201):
                hashes[sid] = digest
            elif 400 <= status < 500:
                # refused: either I'm out, or the rules disliked this row's
                # SHAPE. Only the first should forget the squad. My own member
                # doc is readable exactly while I'm a member, so ask.
                _doc, mine = self.get_doc(f"squads/{sid}/members/{uid}")
                if mine == 200:
                    print(f"due crew: squad row refused (403) at squads/{sid} but "
                          "membership stands — rules and client disagree on the row")
                    self.session["rules_stale_hint"] = True
                elif mine in (403, 404):
                    gone.append(sid)
        for sid in list(hashes):
            if sid not in squad_ids:
                hashes.pop(sid)
        self._save_session()
        return gone

    def _patch_status(self, path, data, mask=None, must_exist=False):
        """patch_doc without the rules-stale hint: a squad 403 means "not a
        member", not "rules drifted". must_exist turns the upsert into a
        pure update (Firestore's currentDocument precondition)."""
        mask_q = "&".join(f"updateMask.fieldPaths={k}" for k in (mask or data))
        if must_exist:
            mask_q += "&currentDocument.exists=true"
        r = self._req("PATCH", f"{self.base}/{path}?{mask_q}",
                      json={"fields": {k: _fv(v) for k, v in data.items()}})
        return r.status_code

    def send_knock(self, to_uid, from_uid, from_name, squad):
        """One write; overwrites my previous knock to the same person. Rules
        require both of us to be members of `squad`."""
        return self.patch_doc(f"users/{to_uid}/knocks/{from_uid}", {
            "name": from_name,
            "squad": str(squad),
            "at": {"timestampValue": _now_ts()},
        }, ["name", "squad", "at", "code"], label="knock")

    def send_code_knock(self, to_uid, from_uid, from_name, code):
        """rules-v9: a knock may carry the recipient's own friend code in
        place of a shared squad. Holding it means they gave it to me. No
        stale-rules hint on a refusal: the add itself went through."""
        return self._patch_status(f"users/{to_uid}/knocks/{from_uid}", {
            "name": from_name,
            "code": str(code),
            "at": {"timestampValue": _now_ts()},
        }, mask=["name", "code", "at", "squad"]) in (200, 201)

    def list_knocks(self, uid):
        """[(sender_uid, sender_profile_name, squad_id)] — names come from
        profiles, not the knock docs, so senders can't spoof. One list
        request per refresh. Raises TransportError."""
        r = self._req("GET", f"{self.base}/users/{uid}/knocks?pageSize=50")
        if r.status_code != 200:
            raise TransportError(f"knocks list failed: {r.status_code}", r.status_code)
        docs = {doc["name"].rsplit("/", 1)[-1]: _parse(doc.get("fields"))
                for doc in r.json().get("documents", [])}
        if not docs:
            return []
        profiles = self.batch_get([f"users/{u}" for u in docs])
        return [(u, str((profiles.get(f"users/{u}") or {}).get("displayName", "?")),
                 str(docs[u].get("squad") or "")) for u in docs]

    def delete_knock(self, uid, sender_uid):
        return self.delete_doc(f"users/{uid}/knocks/{sender_uid}")

    def _cleanup(self, uid, today_label):
        """Blind-delete the stats docs that just aged out — doc ids are date
        labels, so no listing (and no reads) needed. Once per day."""
        if self.session.get("cleaned") == today_label:
            return
        base = datetime.date.fromisoformat(today_label)
        for offset in range(KEEP_DAYS + 1, KEEP_DAYS + 4):
            label = (base - datetime.timedelta(days=offset)).isoformat()
            self.delete_doc(f"users/{uid}/daily_stats/{label}")
        self.session["cleaned"] = today_label
        self._save_session()

    # ---- account deletion ----

    def _delete_listed(self, collection_path):
        r = self._req("GET", f"{self.base}/{collection_path}?pageSize=100")
        if r.status_code == 200:
            for doc in r.json().get("documents", []):
                self.delete_doc(f"{collection_path}/{doc['name'].rsplit('/', 1)[-1]}")

    def delete_account(self, uid, friend_code, squad_ids=()):
        """Raises AuthError(CREDENTIAL_TOO_OLD_LOGIN_AGAIN) if Firebase wants
        a fresh sign-in; caller reauths and retries (the sweep is idempotent)."""
        self.session.pop("shared_hash", None)  # server docs are going away
        self._save_session()
        self._delete_listed(f"users/{uid}/daily_stats")
        self._delete_listed(f"users/{uid}/cheers")
        self._delete_listed(f"users/{uid}/knocks")
        self._delete_listed(f"users/{uid}/friends")
        self.delete_doc(f"users/{uid}/shared/decks")
        self.delete_doc(f"users/{uid}/shared/heatmap")
        self.delete_doc(f"users/{uid}/shared/week")
        for sid in squad_ids:
            self.delete_doc(f"squads/{sid}/members/{uid}")
        if friend_code:
            self.delete_doc(f"friend_codes/{friend_code}")
        self.delete_doc(f"users/{uid}")
        self._auth_post("delete", {"idToken": self.session.get("id_token")})
        self.sign_out()
