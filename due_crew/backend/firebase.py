"""Firebase REST client for Due Crew.

Call budget is the design constraint: the whole board loads in 3 requests
(own profile, all friend profiles, one batchGet for stats + shared decks +
cheers). Stats are only requested for people who added you back, so a
pending invite can never fail the batch.

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
# The rules generation this client needs. The deployed firestore.rules allow
# `get` on meta/{RULES_MARKER} (no doc exists): 404 = current, 403 = stale.
# Bump together with the marker block in firestore.rules.
RULES_MARKER = "rules-v3"


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


def _exam_value(iso, today_label):
    """The exam date to publish: a valid ISO date not yet passed, else None."""
    try:
        d = datetime.date.fromisoformat(str(iso))
        t = datetime.date.fromisoformat(str(today_label))
    except (TypeError, ValueError):
        return None
    return str(iso) if d >= t else None


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
    hours = doc.get("hours")
    if (isinstance(hours, str) and len(hours) == 24
            and all(c in "012" for c in hours)):
        out["hours"] = hours
    return out


def _clean_board_row(uid, fields):
    """Coerce a server_board row to a trusted shape; None if unusable."""
    if not isinstance(fields, dict):
        return None
    day = fields.get("day")
    if not isinstance(day, str):
        return None
    return {"user_id": str(uid),
            "name": str(fields.get("name", "?")),
            "day": day,
            "reviews": _as_int(fields.get("reviews")) or 0,
            "time_ms": _as_int(fields.get("studyTimeMs")) or 0,
            "streak": _as_int(fields.get("streak")) or 0}


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
    def __init__(self, session_file, api_key=None, project_id=None):
        self.session_file = session_file
        self.api_key = api_key or DEFAULT_API_KEY
        self.project_id = project_id or DEFAULT_PROJECT_ID
        self.base = firestore_base(self.project_id)
        self.doc_root = doc_root(self.project_id)
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
                r = self.http.post(TOKEN_URL, params={"key": self.api_key},
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
            if r.status_code == 403:
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
            raise TransportError(f"batchGet failed: {r.status_code}")
        for item in r.json():
            if "found" in item:
                name = item["found"]["name"]
                out[name[len(self.doc_root) + 1:]] = _parse(item["found"].get("fields"))
        return out

    def run_query(self, collection, filters, page_size=300):
        """Equality-only query on a root collection: [(field, value), ...].
        No orderBy, so no composite index for founders to create. Returns
        {doc_id: fields}; raises TransportError on failure."""
        where = {"compositeFilter": {"op": "AND", "filters": [
            {"fieldFilter": {"field": {"fieldPath": f},
                             "op": "EQUAL", "value": _fv(v)}}
            for f, v in filters]}}
        query = {"structuredQuery": {
            "from": [{"collectionId": collection}],
            "where": where, "limit": page_size}}
        r = self._req("POST", f"{self.base}:runQuery", json=query)
        if r.status_code != 200:
            raise TransportError(f"query failed: {r.status_code}")
        out = {}
        for item in r.json():
            doc = item.get("document")
            if doc:
                out[doc["name"].rsplit("/", 1)[-1]] = _parse(doc.get("fields"))
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
                "exam_date": str(prof.get("examDate") or ""),
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
        return {"entries": entries, "pending": pending, "cheers": cheers,
                "my_friends": [fid for fid, _p, _m in resolved]}

    def send_cheer(self, to_uid, from_uid, from_name, emoji):
        """One write; overwrites any previous cheer to the same person."""
        return self.patch_doc(f"users/{to_uid}/cheers/{from_uid}", {
            "emoji": emoji,
            "name": from_name,
            "at": {"timestampValue": _now_ts()},
        })

    # ---- upload ----

    METRICS = (("reviews", "share_reviews"), ("studyTimeMs", "share_time"),
               ("accuracy", "share_retention"), ("streak", "share_streak"),
               ("hours", "share_time"))  # 24-char intensity string, crew tape

    def _day_doc(self, label, values, cfg):
        """(doc, mask) for one daily_stats write. Every field is always in
        the mask, so a toggled-off (or absent) metric is DELETED server-side,
        not left stale. `studied` is the numbers-free floor the Days view
        stands on; it shares whenever sharing isn't paused."""
        doc = {"date": label, "studied": bool(values.get("reviews"))}
        mask = ["date", "studied"]
        for field, share_key in self.METRICS:
            mask.append(field)
            if cfg.get(share_key, True) and values.get(field) is not None:
                doc[field] = values.get(field)
        return doc, mask

    def _put_day(self, uid, label, values, cfg):
        """Write one day's doc, skipped when identical to the last success.
        The digest covers the post-toggle doc, so flipping a share toggle
        (not just new reviews) re-writes the day."""
        doc, mask = self._day_doc(label, values, cfg)
        digest = hashlib.sha1(
            json.dumps(doc, sort_keys=True).encode()).hexdigest()
        hashes = self.session.setdefault("day_hashes", {})
        if hashes.get(label) == digest:
            return True
        if not self.patch_doc(f"users/{uid}/daily_stats/{label}", doc, mask,
                              label="daily stats"):
            return False
        hashes[label] = digest
        for old in sorted(hashes)[:-(KEEP_DAYS + 1)]:
            hashes.pop(old, None)
        self._save_session()
        return True

    def upload_today(self, uid, display_name, label, stats, cfg):
        profile = {
            "displayName": display_name,
            "lastUpdated": {"timestampValue": _now_ts()},
            "paused": bool(cfg.get("paused")),
        }
        # examDate and openBoard ride the always-in-the-mask pattern: unset,
        # past, off, or paused thereby DELETES them server-side, never stale.
        # openBoard is what the rules read to gate the server board both ways.
        mask = list(profile) + ["examDate", "openBoard"]
        exam = _exam_value(cfg.get("exam_date"), label)
        if exam and not cfg.get("paused"):
            profile["examDate"] = exam
        if cfg.get("server_board") and not cfg.get("paused"):
            profile["openBoard"] = True
        ok = self.patch_doc(f"users/{uid}", profile, mask, label="profile")
        if cfg.get("paused"):
            return ok
        from ..share import hour_levels, levels_str
        hourly = getattr(stats, "hourly", None)
        values = {"reviews": int(stats.reviews),
                  "studyTimeMs": int(stats.time_ms),
                  "accuracy": None if stats.accuracy is None else float(stats.accuracy),
                  "streak": int(stats.streak),
                  "hours": levels_str(hour_levels(hourly)) if hourly else None}
        ok = self._put_day(uid, label, values, cfg) and ok
        self._cleanup(uid, label)
        return ok

    def upload_backfill(self, uid, days, cfg):
        """Fill the last week's studied days the server missed — a day only
        exists server-side if a sync ran while it was 'today', which is how
        a 40-day streak could sit next to a half-empty dot row. Hash-guarded:
        steady state adds zero writes."""
        if cfg.get("paused"):
            return True
        ok = True
        for d in days or []:
            values = {"reviews": int(d["reviews"]),
                      "studyTimeMs": int(d["time_ms"]),
                      "accuracy": None if d["accuracy"] is None else float(d["accuracy"]),
                      "streak": int(d["streak"])}
            ok = self._put_day(uid, d["label"], values, cfg) and ok
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

    def upload_board_row(self, uid, row):
        """Upsert my compact public row; skipped when unchanged."""
        digest = hashlib.sha1(
            json.dumps(row, sort_keys=True).encode()).hexdigest()
        if self.session.get("board_row_hash") == digest:
            return True
        data = dict(row)
        data["updatedAt"] = {"timestampValue": _now_ts()}
        if not self.patch_doc(f"server_board/{uid}", data,
                              mask=list(row) + ["updatedAt"],
                              label="server board"):
            return False
        self.session["board_row_hash"] = digest
        self.session.pop("board_row_deleted", None)
        self._save_session()
        return True

    def delete_board_row(self, uid):
        self.delete_doc(f"server_board/{uid}")
        self.session.pop("board_row_hash", None)
        self.session["board_row_deleted"] = True  # retract once, not per sync
        self._save_session()

    def fetch_server_board(self, server):
        """All rows for my server (client filters days and sorts). One
        equality-only query; raises TransportError on failure."""
        docs = self.run_query("server_board", [("server", str(server))])
        rows = [_clean_board_row(uid, fields) for uid, fields in docs.items()]
        return [r for r in rows if r]

    def send_knock(self, to_uid, from_uid, from_name):
        """One write; overwrites my previous knock to the same person."""
        return self.patch_doc(f"users/{to_uid}/knocks/{from_uid}", {
            "name": from_name,
            "at": {"timestampValue": _now_ts()},
        }, label="knock")

    def list_knocks(self, uid):
        """[(sender_uid, sender_profile_name)] — names come from profiles,
        not the knock docs, so senders can't spoof. Raises TransportError."""
        r = self._req("GET", f"{self.base}/users/{uid}/knocks?pageSize=50")
        if r.status_code != 200:
            raise TransportError(f"knocks list failed: {r.status_code}")
        senders = [doc["name"].rsplit("/", 1)[-1]
                   for doc in r.json().get("documents", [])]
        if not senders:
            return []
        profiles = self.batch_get([f"users/{u}" for u in senders])
        return [(u, str((profiles.get(f"users/{u}") or {})
                        .get("displayName", "?"))) for u in senders]

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

    def delete_account(self, uid, friend_code):
        """Raises AuthError(CREDENTIAL_TOO_OLD_LOGIN_AGAIN) if Firebase wants
        a fresh sign-in; caller reauths and retries (the sweep is idempotent)."""
        self.session.pop("shared_hash", None)  # server docs are going away
        self._save_session()
        self._delete_listed(f"users/{uid}/daily_stats")
        self._delete_listed(f"users/{uid}/cheers")
        self._delete_listed(f"users/{uid}/knocks")
        self.delete_doc(f"users/{uid}/shared/decks")
        self.delete_doc(f"users/{uid}/shared/heatmap")
        self.delete_doc(f"server_board/{uid}")  # the public row goes first
        if friend_code:
            self.delete_doc(f"friend_codes/{friend_code}")
        self.delete_doc(f"users/{uid}")
        self._auth_post("delete", {"idToken": self.session.get("id_token")})
        self.sign_out()
