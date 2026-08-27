"""Firebase REST client for Due Crew.

Call budget is the design constraint: the whole board loads in 3 requests
(own profile, all friend profiles, one batchGet for stats + shared decks +
cheers). Stats are only requested for people who added you back, so a
pending invite can never fail the batch.

Failure is never conflated with absence: batch_get and list_friends raise
TransportError on any non-200, so callers keep their caches and their
server-side state instead of treating an outage as "everything was deleted".

All calls have a 10s timeout and must run off the main thread. Writes stay
on self-owned documents, with one deliberate exception: send_cheer writes to
the recipient's cheers/{sender} doc, which the deployed rules allow only for
senders the recipient has added.
"""

import datetime
import hashlib
import json
import os
import secrets
import string
import threading

import requests

API_KEY = "AIzaSyBgXxrfGhuZ1Zrf_DURu4Sd3B9VZw42Q9I"
PROJECT_ID = "anki-leaderboard-f6691"
AUTH_URL = "https://identitytoolkit.googleapis.com/v1/accounts"
TOKEN_URL = "https://securetoken.googleapis.com/v1/token"
BASE = f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}/databases/(default)/documents"
DOC_ROOT = f"projects/{PROJECT_ID}/databases/(default)/documents"
TIMEOUT = 10
KEEP_DAYS = 7


class AuthError(Exception):
    """Carries the Firebase error code, e.g. EMAIL_EXISTS."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


class TransportError(Exception):
    """Request failed (network, 5xx, 429, auth) — the data may still exist."""


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
    """Coerce a daily_stats doc to trusted numeric types; None stays None."""
    if doc is None:
        return None
    out = {}
    for key, conv in (("reviews", _as_int), ("studyTimeMs", _as_int),
                      ("accuracy", _as_float), ("streak", _as_int)):
        if key in doc:
            v = conv(doc[key])
            if v is not None:
                out[key] = v
    return out


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
        out.append({
            "name": str(d.get("name", "?")),
            "sig": [str(s) for s in sig if isinstance(s, str)],
            "total": total,
            "seen": _as_int(d.get("seen")) or 0,
            "mature": _as_int(d.get("mature")) or 0,
        })
    return out


class FirebaseClient:
    def __init__(self, session_file):
        self.session_file = session_file
        self.http = requests.Session()
        self._session_lock = threading.Lock()
        self._refresh_lock = threading.Lock()
        self.session = self._load_session()

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
                os.replace(tmp, self.session_file)
            except OSError:
                pass

    @property
    def signed_in(self):
        return bool(self.session.get("refresh_token"))

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
            r = self.http.post(f"{AUTH_URL}:{endpoint}", params={"key": API_KEY},
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
                r = self.http.post(TOKEN_URL, params={"key": API_KEY},
                                   data={"grant_type": "refresh_token",
                                         "refresh_token": rt},
                                   timeout=TIMEOUT)
            except requests.RequestException:
                return False
            if r.status_code != 200:
                return False
            data = r.json()
            self.session["id_token"] = data["id_token"]
            self.session["refresh_token"] = data.get("refresh_token", rt)
            self._save_session()
            return True

    # ---- firestore primitives ----

    def _req(self, method, url, retry=True, **kw):
        headers = {"Authorization": f"Bearer {self.session.get('id_token', '')}"}
        try:
            r = self.http.request(method, url, headers=headers, timeout=TIMEOUT, **kw)
        except requests.RequestException:
            raise TransportError(f"{method} failed")
        if r.status_code == 401 and retry and self._refresh():
            return self._req(method, url, retry=False, **kw)
        return r

    def get_doc(self, path):
        r = self._req("GET", f"{BASE}/{path}")
        if r.status_code != 200:
            return None, r.status_code
        return _parse(r.json().get("fields")), 200

    def patch_doc(self, path, data, mask=None):
        mask_q = "&".join(f"updateMask.fieldPaths={k}" for k in (mask or data))
        r = self._req("PATCH", f"{BASE}/{path}?{mask_q}",
                      json={"fields": {k: _fv(v) for k, v in data.items()}})
        return r.status_code in (200, 201)

    def delete_doc(self, path):
        return self._req("DELETE", f"{BASE}/{path}").status_code == 200

    def batch_get(self, paths):
        """Many docs, one round trip. {path: fields-or-None(missing)}.
        Raises TransportError on failure — missing and failed are distinct."""
        out = {p: None for p in paths}
        if not paths:
            return out
        r = self._req("POST", f"{BASE}:batchGet",
                      json={"documents": [f"{DOC_ROOT}/{p}" for p in paths]})
        if r.status_code != 200:
            raise TransportError(f"batchGet failed: {r.status_code}")
        for item in r.json():
            if "found" in item:
                name = item["found"]["name"]
                out[name[len(DOC_ROOT) + 1:]] = _parse(item["found"].get("fields"))
        return out

    # ---- friends ----

    def list_friends(self, uid):
        """(own_fields, [(fid, prof, mutual)], pending_names).
        Raises TransportError on any failure, including a missing own profile,
        so callers never mistake an outage for an empty crew."""
        own, status = self.get_doc(f"users/{uid}")
        if own is None:
            raise TransportError(f"own profile unavailable: {status}")
        friends = [f for f in (own.get("friends") or []) if isinstance(f, str)]
        profiles = self.batch_get([f"users/{f}" for f in friends])
        resolved, pending = [], []
        for fid in friends:
            prof = profiles.get(f"users/{fid}")
            if prof is None:
                continue  # deleted account; skip quietly
            mutual = uid in (prof.get("friends") or [])
            resolved.append((fid, prof, mutual))
            if not mutual:
                pending.append(prof.get("displayName", "?"))
        return own, resolved, pending

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

    def add_friend(self, uid, code, own_friends):
        doc, _ = self.get_doc(f"friend_codes/{code.upper()}")
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
        if not self.patch_doc(f"users/{uid}", {"friends": own_friends + [fid]}):
            return None, "Couldn't save. Try again."
        return {"user_id": fid,
                "name": prof.get("displayName", "?"),
                "mutual": uid in (prof.get("friends") or [])}, None

    def set_friends(self, uid, friends):
        return self.patch_doc(f"users/{uid}", {"friends": friends})

    # ---- board ----

    def fetch_board(self, uid, labels, tomorrow=None, include_shared=True):
        """labels: day labels to fetch, newest-first. `tomorrow` (my next
        label) is fetched too so friends ahead of my timezone stay live.
        Shared-deck docs only ride along when include_shared (full fetches).
        Raises TransportError on failure — the caller keeps its cache."""
        own, resolved, pending = self.list_friends(uid)
        mutual = [(fid, prof) for fid, prof, m in resolved if m]
        people = [(uid, own)] + mutual

        want = list(labels) + ([tomorrow] if tomorrow else [])
        paths = [f"users/{u}/daily_stats/{lb}" for u, _ in people for lb in want]
        if include_shared:
            paths += [f"users/{u}/shared/decks" for u, _ in people]
        paths += [f"users/{uid}/cheers/{fid}" for fid, _ in mutual]
        docs = self.batch_get(paths)

        entries = []
        for u, prof in people:
            decks = None
            if include_shared:
                decks = _clean_decks(
                    (docs.get(f"users/{u}/shared/decks") or {}).get("decks"))
            entries.append({
                "user_id": u,
                "name": str(prof.get("displayName", "?")),
                "you": u == uid,
                "paused": bool(prof.get("paused")),
                "last_updated": prof.get("lastUpdated", ""),
                "days": {lb: _clean_day(docs.get(f"users/{u}/daily_stats/{lb}"))
                         for lb in want},
                "decks": decks,  # None = not fetched this time
            })

        cheers = []
        for fid, prof in mutual:
            doc = docs.get(f"users/{uid}/cheers/{fid}")
            if doc and doc.get("emoji"):
                cheers.append({"from": fid,
                               # profile name, not the doc's: senders can't spoof
                               "name": str(prof.get("displayName", "?")),
                               "emoji": str(doc.get("emoji")),
                               "at": str(doc.get("at", ""))})
        return {"entries": entries, "pending": pending, "cheers": cheers}

    def send_cheer(self, to_uid, from_uid, from_name, emoji):
        """One write; overwrites any previous cheer to the same person."""
        return self.patch_doc(f"users/{to_uid}/cheers/{from_uid}", {
            "emoji": emoji,
            "name": from_name,
            "at": {"timestampValue": _now_ts()},
        })

    # ---- upload ----

    METRICS = (("reviews", "share_reviews"), ("studyTimeMs", "share_time"),
               ("accuracy", "share_retention"), ("streak", "share_streak"))

    def upload_today(self, uid, display_name, label, stats, cfg):
        ok = self.patch_doc(f"users/{uid}", {
            "displayName": display_name,
            "lastUpdated": {"timestampValue": _now_ts()},
            "paused": bool(cfg.get("paused")),
        })
        if cfg.get("paused"):
            return ok
        values = {"reviews": int(stats.reviews),
                  "studyTimeMs": int(stats.time_ms),
                  "accuracy": None if stats.accuracy is None else float(stats.accuracy),
                  "streak": int(stats.streak)}
        doc = {"date": label}
        # every metric is always in the mask: a toggled-off (or absent) metric
        # is thereby DELETED server-side, not left stale
        mask = ["date"]
        for field, share_key in self.METRICS:
            mask.append(field)
            if cfg.get(share_key, True) and values[field] is not None:
                doc[field] = values[field]
        ok = self.patch_doc(f"users/{uid}/daily_stats/{label}", doc, mask) and ok
        self._cleanup(uid, label)
        return ok

    def upload_shared(self, uid, decks):
        """Skips the write when nothing changed since the last upload."""
        digest = hashlib.sha1(
            json.dumps(decks, sort_keys=True).encode()).hexdigest()
        if self.session.get("shared_hash") == digest:
            return True
        if not self.patch_doc(f"users/{uid}/shared/decks", {"decks": decks}):
            return False
        self.session["shared_hash"] = digest
        self._save_session()
        return True

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
        r = self._req("GET", f"{BASE}/{collection_path}?pageSize=100")
        if r.status_code == 200:
            for doc in r.json().get("documents", []):
                self.delete_doc(f"{collection_path}/{doc['name'].rsplit('/', 1)[-1]}")

    def delete_account(self, uid, friend_code):
        """Raises AuthError(CREDENTIAL_TOO_OLD_LOGIN_AGAIN) if Firebase wants
        a fresh sign-in; caller reauths and retries (the sweep is idempotent)."""
        self.session.pop("shared_hash", None)  # server docs are going away
        self._save_session()
        self._delete_listed(f"users/{uid}/daily_stats")
        self._delete_listed(f"users/{uid}/cheers")
        self.delete_doc(f"users/{uid}/shared/decks")
        if friend_code:
            self.delete_doc(f"friend_codes/{friend_code}")
        self.delete_doc(f"users/{uid}")
        self._auth_post("delete", {"idToken": self.session.get("id_token")})
        self.sign_out()
