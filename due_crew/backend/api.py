"""The Due Crew API client (3.0): one Cloudflare Worker at api.duecrew.com.

A refresh is one request (GET /board) and a sync is one request (POST
/sync). The server holds consent (who may read whom), shapes, and the
"don't write what didn't change" guards; the client sends what it has.

Sign-in is an emailed code; the session is a bearer token the Worker made,
kept in session.json. A 401 means that token is over (signed out elsewhere,
idle 180 days, account deleted), which is not the same as being offline:
it sets auth_dead, and the board asks for a sign-in instead of aging.

All calls have a 10s timeout and must run off the main thread. A request
that fails on the network is retried once, on a fresh connection; the
server's writes are idempotent (upserts keyed by their owner), so that's
safe.
"""

import hashlib
import json
import os
import threading

import requests

from ..room_model import clean_room, is_over
from .shapes import (
    AuthError, TransportError, TIMEOUT, WEEK_WINDOW, _clean_day, _clean_decks, _clean_member,
    _exam_value, _live_room, _week_days, away_range, clean_emoji, clean_note, clean_tricky,
    day_doc, friend_code_from, live_now,
)

API_BASE = "https://api.duecrew.com"
# session.json keys that belong to one account on this computer, and go
# when a different account signs in
_LEGACY_AUTH = ("id_token", "refresh_token", "auth_dead", "rules_check", "rules_stale_hint")


def _version_tuple(text):
    try:
        return tuple(int(x) for x in str(text or "").split(".")[:3])
    except ValueError:
        return ()


def _digest(obj):
    return hashlib.sha1(json.dumps(obj, sort_keys=True).encode()).hexdigest()


class ApiClient:
    def __init__(self, session_file, base=None):
        self.session_file = session_file
        self.base = (base or os.environ.get("DUE_CREW_API") or API_BASE).rstrip("/")
        self.http = requests.Session()
        self._session_lock = threading.Lock()
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
                os.chmod(tmp, 0o600)  # holds the session token
                os.replace(tmp, self.session_file)
            except OSError:
                pass

    @property
    def signed_in(self):
        return bool(self.session.get("token"))

    @property
    def session_dead(self):
        """The server refused my token outright (401). Cleared by signing in."""
        return bool(self.session.get("auth_dead"))

    @property
    def was_on_2x(self):
        """A session.json from before 3.0: signed in with Firebase, never
        with a code. The board asks for one sign-in, once."""
        return bool(self.session.get("refresh_token")) and not self.signed_in

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
        """Local at once; the server's copy of the session ends in the
        background (best effort: offline, it just idles out)."""
        token = self.session.get("token")
        if token:
            def bye():
                try:
                    self.http.request("POST", f"{self.base}/auth/signout", timeout=TIMEOUT,
                                      headers={"Authorization": f"Bearer {token}"})
                except Exception:
                    pass
            threading.Thread(target=bye, daemon=True).start()
        self.session = {}
        try:
            os.remove(self.session_file)
        except OSError:
            pass

    # ---- transport ----

    def _call(self, method, path, body=None, auth=True, retry=True):
        """(status, json). Raises TransportError when there's no answer, and
        on a 401 (after marking the session dead)."""
        headers = {}
        if auth:
            headers["Authorization"] = f"Bearer {self.session.get('token', '')}"
        kw = {"headers": headers, "timeout": TIMEOUT}
        if body is not None:
            kw["json"] = body
        try:
            r = self.http.request(method, f"{self.base}{path}", **kw)
        except requests.RequestException:
            if retry:
                return self._call(method, path, body, auth, retry=False)
            raise TransportError(f"{method} {path.split('?')[0]} failed")
        try:
            data = r.json() if r.content else {}
        except ValueError:
            data = {}
        if r.status_code == 401 and auth:
            self.session["auth_dead"] = True
            self._save_session()
            raise TransportError("signed out", 401)
        if r.status_code >= 500 or r.status_code == 429:
            raise TransportError(f"{method} {path.split('?')[0]}: {r.status_code}", r.status_code)
        return r.status_code, data if isinstance(data, dict) else {}

    # ---- sign-in (3.0: an emailed code; no passwords) ----

    def request_code(self, email):
        try:
            status, data = self._call("POST", "/auth/code", {"email": email}, auth=False)
        except TransportError as e:
            if e.status == 429:
                raise AuthError("slow_down")
            raise
        if status != 200:
            raise AuthError(str(data.get("error") or "bad_email"))

    def verify_code(self, email, code, device=""):
        """{uid, name, new}. The session becomes this account's; a session
        from before 3.0 for the same account keeps what it knew (friends,
        squads' state, seen cheers), and remembers to bring it back."""
        try:
            status, data = self._call("POST", "/auth/verify",
                                      {"email": email, "code": code, "device": device[:60]}, auth=False)
        except TransportError as e:
            if e.status == 429:
                raise AuthError("locked")
            raise
        if status != 200 or not data.get("token"):
            raise AuthError(str(data.get("error") or "wrong_code"))
        uid = str(data["uid"])
        same = self.session.get("user_id") == uid
        # what this computer knew comes back once per server: from 2.x, and
        # again on a server it hasn't restored to (a dev Worker, then the real one)
        from_2x = same and (bool(self.session.get("refresh_token"))
                            or (bool(self.session.get("friend_ids") or self.session.get("friend_code"))
                                and self.session.get("restored_to") != self.base))
        if not same:
            self.session = {}  # another account: nothing carries over
        for k in _LEGACY_AUTH:
            self.session.pop(k, None)
        name = str(data.get("name") or "") or (self.session.get("display_name", "") if same else "")
        self.session.update(user_id=uid, email=email.strip().lower(), token=data["token"],
                            display_name=name)
        if from_2x:
            self.session["needs_restore"] = True
        self._save_session()
        return {"uid": uid, "name": name, "new": bool(data.get("new")) or not name}

    def set_display_name(self, name):
        status, _ = self._call("POST", "/sync", {"profile": {"name": name}})
        if status != 200:
            return False
        self.session["display_name"] = name
        self._save_session()
        return True

    def delete_account(self):
        """Everything of mine, server-side, then signed out here."""
        status, _ = self._call("DELETE", "/account")
        if status != 200:
            raise TransportError(f"delete refused: {status}", status)
        self.session.pop("token", None)
        self.sign_out()

    # ---- the server's version ----

    def check_version(self, today_label, version):
        """One GET /version a day. Below the server's minClient, the footer
        says the server has moved on (rules_stale, the 2.x name)."""
        cached = self.session.get("version_check") or {}
        if cached.get("day") == today_label:
            return self.rules_stale
        try:
            status, data = self._call("GET", "/version", auth=False)
        except TransportError:
            return self.rules_stale
        if status == 200:
            stale = bool(_version_tuple(version)) and _version_tuple(version) < _version_tuple(data.get("minClient"))
            self.session["version_check"] = {"day": today_label, "stale": stale}
            self._save_session()
        return self.rules_stale

    @property
    def rules_stale(self):
        return bool((self.session.get("version_check") or {}).get("stale"))

    # ---- a refresh: one request ----

    def fetch_board(self, labels, tomorrow=None, with_decks=False):
        """Everything the board shows. labels: this week's day labels,
        newest first. Raises TransportError; the caller keeps its cache."""
        status, data = self._call("GET", "/board?decks=1" if with_decks else "/board")
        if status != 200:
            raise TransportError(f"board: {status}", status)
        span = list(labels) + ([tomorrow] if tomorrow else [])
        today = labels[0] if labels else ""
        me = data.get("me") or {}
        decks = data.get("decks") if with_decks else None
        people = [(me, True)] + [(f, False) for f in data.get("friends") or [] if f.get("mutual")]
        entries = []
        for p, you in people:
            uid = str(p.get("uid") or "")
            week = p.get("week") if isinstance(p.get("week"), dict) else {}
            days = {lb: _clean_day(d) for lb, d in _week_days(week, list(labels) if you else span).items()}
            stamps = [str(p.get("updatedAt") or "")]
            if you:
                stamps.append(str(self.session.get("last_ok") or ""))
            entries.append({
                "user_id": uid,
                "name": str(p.get("name") or (self.display_name if you else "") or "?"),
                "emoji": clean_emoji(p.get("emoji")),
                "you": you,
                "paused": bool(week.get("paused")),
                "last_updated": max(stamps),
                "exam_date": str(week.get("examDate") or ""),
                "days": days,
                "decks": None if decks is None else _clean_decks((decks or {}).get(uid)),
                # 2.10: studying now, and the cards they've flagged
                "live_until": str(self.session.get("live_until") or "") if you
                              else str(week.get("liveUntil") or ""),
                "tricky": [] if you else clean_tricky(week.get("tricky"), today),
                # 2.12: the study room they're in (mine from the session)
                "room": _live_room(self.session.get("room") if you else week.get("room")),
            })
        by_uid = {f.get("uid"): f for f in data.get("friends") or []}
        cheers = []
        for c in data.get("cheers") or []:
            emoji = clean_emoji(c.get("emoji"))
            sender = by_uid.get(c.get("from"))
            if not emoji or not sender or not sender.get("mutual"):
                continue
            cheers.append({"from": str(c["from"]), "name": str(sender.get("name") or "?"),
                           "emoji": emoji, "at": str(c.get("at") or ""),
                           "note": clean_note(c.get("note")), "luck": c.get("luck") is True,
                           "guid": str(c.get("guid") or "")[:40]})
        friends = [str(f.get("uid")) for f in data.get("friends") or [] if f.get("uid")]
        if friends != self.session.get("friend_ids"):
            self.session["friend_ids"] = friends
            self._save_session()
        return {"entries": entries,
                "pending": [str(f.get("name") or "?") for f in data.get("friends") or [] if not f.get("mutual")],
                "cheers": cheers,
                "my_friends": friends,
                "my_code": str(me.get("code") or ""),
                "knocks": self._knocks(data.get("knocks"))}

    @staticmethod
    def _knocks(rows):
        return [(str(k.get("from")), str(k.get("name") or "?"), str(k.get("squad") or ""))
                for k in rows or [] if isinstance(k, dict) and k.get("from")]

    def list_knocks(self):
        """[(sender_uid, name, squad_id)], for the Squads tab."""
        status, data = self._call("GET", "/knocks")
        if status != 200:
            raise TransportError(f"knocks: {status}", status)
        return self._knocks(data.get("knocks"))

    def fetch_decks(self):
        """{uid: decks} for the Decks tab: mine and my crew's."""
        status, data = self._call("GET", "/decks")
        if status != 200:
            raise TransportError(f"decks: {status}", status)
        return {str(u): _clean_decks(d) for u, d in (data.get("decks") or {}).items()}

    def fetch_heatmap(self, uid):
        """{day_label: n}, or None when they don't share one (or can't be read)."""
        try:
            status, data = self._call("GET", f"/heatmap/{uid}")
        except TransportError:
            return None
        counts = data.get("counts") if status == 200 else None
        if not isinstance(counts, dict):
            return None
        return {str(k): int(v) if isinstance(v, int) else 0 for k, v in counts.items()}

    def profile(self, uid):
        """{uid, name, emoji} for anyone, or None."""
        status, data = self._call("GET", f"/users/{uid}")
        return data if status == 200 else None

    # ---- a sync: one request ----

    def my_days(self, cfg, today_label=None):
        """My week as it goes out, from what this computer counted: {label:
        day}. Built fresh from the numbers each time, so a Privacy switch
        turned off takes that number off every day at once. Today's status
        rides today only."""
        raw = self.session.get("week_raw") or {}
        return {lb: day_doc(v, cfg, cfg.get("status") if lb == today_label else None)
                for lb, v in raw.items() if isinstance(v, dict)}

    def sent_days(self):
        """{label: numbers} this computer last sent (held_streak reads the
        streak from it while a phone's reviews are on their way)."""
        return dict(self.session.get("week_raw") or {})

    def _note_days(self, labels, stats, backfill):
        raw = dict(self.session.get("week_raw") or {})
        if stats is not None and labels:
            raw[labels[0]] = {"reviews": int(stats.reviews), "studyTimeMs": int(stats.time_ms),
                              "accuracy": None if stats.accuracy is None else float(stats.accuracy),
                              "streak": int(stats.streak),
                              "newCards": int(getattr(stats, "new_cards", 0) or 0)}
        for d in backfill or []:
            raw[d["label"]] = {"reviews": int(d["reviews"]), "studyTimeMs": int(d["time_ms"]),
                               "accuracy": None if d["accuracy"] is None else float(d["accuracy"]),
                               "streak": int(d["streak"]), "newCards": int(d.get("new_cards") or 0)}
        if backfill is not None and labels:
            # a full count: a past day it didn't find had no answers here
            found = {d["label"] for d in backfill}
            for lb in labels[1:]:
                if lb not in found:
                    raw.pop(lb, None)
        keep = sorted(raw)[-WEEK_WINDOW:]
        self.session["week_raw"] = {lb: raw[lb] for lb in keep}

    def week_doc(self, labels, cfg):
        """The week doc: my last eight days, the away spell as a range, and
        what rides along (studying now, flagged cards, my room)."""
        paused = bool(cfg.get("paused"))
        doc = {"v": 1, "days": {} if paused else self.my_days(cfg, labels[0] if labels else None),
               "paused": paused}
        if paused:
            return doc
        exam = _exam_value(cfg.get("exam_date"), labels[0]) if labels else None
        if exam:
            doc["examDate"] = exam
        rng = away_range(cfg)
        if rng:
            doc["awayFrom"], doc["awayTo"] = rng[0].isoformat(), rng[1].isoformat()
        live = self.session.get("live_until")
        if live and live_now(live):
            doc["liveUntil"] = str(live)
        # a flag goes out as its note's guid, its deck and its day: never the card's text
        tricky = [{k: t[k] for k in ("guid", "deck", "at")}
                  for t in clean_tricky(self.session.get("tricky"), labels[0] if labels else None)]
        if tricky:
            doc["tricky"] = tricky
        room = clean_room(self.session.get("room"))
        if room and not is_over(room):
            doc["room"] = room
        return doc

    def push(self, labels, cfg, stats=None, backfill=None, shared_decks=None, heatmap=None,
             squad_row=None, squads=(), version=None, clock=None):
        """One POST /sync with whatever this sync has. Returns (ok, gone):
        gone lists the squads I'm no longer in. heatmap: counts to share,
        "off" to take it down, None to leave it. Raises TransportError."""
        if self.session.get("needs_restore"):
            try:
                self.restore_from_2x(cfg)
            except TransportError:
                pass  # offline or the server's trouble: the next sync tries again
        body = {}
        profile = {"name": self.display_name or "Me"}
        emoji = clean_emoji(cfg.get("emoji"))
        profile["emoji"] = emoji or None
        if version:
            profile["clientVersion"] = str(version)[:20]
        if clock:
            profile["tz"] = int(clock.get("tz", 0))
            profile["rollover"] = int(clock.get("rollover", 4))
        body["profile"] = profile
        if stats is not None or backfill is not None:
            self._note_days(labels, stats, backfill)
        body["week"] = self.week_doc(labels, cfg)
        paused = bool(cfg.get("paused"))
        if shared_decks is not None and not paused and _digest(shared_decks) != self.session.get("decks_hash"):
            body["decks"] = shared_decks
        if heatmap is not None:
            want = {"counts": heatmap} if isinstance(heatmap, dict) and not paused else None
            if _digest(want) != self.session.get("heatmap_hash"):
                body["heatmap"] = want
        if squad_row is not None and squads and not paused:
            body["squads"] = {"row": squad_row, "ids": list(squads)}
        status, data = self._call("POST", "/sync", body)
        if status != 200:
            print(f"due crew: sync refused ({status}: {data.get('error', '?')})")
            self._save_session()
            return False, []
        if "decks" in body:
            self.session["decks_hash"] = _digest(body["decks"])
        if "heatmap" in body:
            self.session["heatmap_hash"] = _digest(body["heatmap"])
        self.session["last_ok"] = _now_iso()
        self._save_session()
        return True, [str(s) for s in data.get("gone") or []]

    # ---- 3.0's first sync: bring back what 2.x had ----

    def restore_from_2x(self, cfg):
        """Once, the first time an account from before 3.0 syncs: my code
        (when this computer knew it), my crew by uid, and my squads by their
        codes. Friendships re-form as each side updates; until then the
        other side reads as pending. Idempotent. No answer (offline, a 5xx)
        raises, and the next sync tries again; a refusal (a squad locked by
        whoever got there first, a name the server won't take) won't change
        by asking twice, so it's done."""
        code = friend_code_from(self.session.get("friend_code") or "")
        self._call("POST", "/codes", {"code": code} if code else {})
        ids = [f for f in self.session.get("friend_ids") or [] if isinstance(f, str)]
        if ids:
            self._call("PUT", "/friends", {"ids": ids[:500]})
        for sq in cfg.get("squads") or []:
            if not isinstance(sq, dict) or not sq.get("code"):
                continue
            self._call("POST", "/squads/restore", {
                "code": sq["code"], "name": clean_note(sq.get("name"), 24) or "squad",
                "founder": sq.get("founder") or ""})
        self.session.pop("needs_restore", None)
        self.session["restored_to"] = self.base
        self._save_session()
        return True

    # ---- settings (2.13) ----

    def get_settings(self):
        """(doc, status): {v, at, settings}; 404 when there's none yet."""
        status, data = self._call("GET", "/settings")
        return (data if status == 200 else None), status

    def put_settings(self, at, settings):
        status, _ = self._call("PUT", "/settings", {"v": 1, "at": at, "settings": settings})
        return status == 200

    # ---- friends and codes ----

    def friends_view(self):
        """(code, [(uid, name, emoji, mutual)], knocks) for the Friends
        dialog. A code is made on the spot for an account without one."""
        status, data = self._call("GET", "/friends")
        if status != 200:
            raise TransportError(f"friends: {status}", status)
        code = str(data.get("code") or "") or self.ensure_friend_code(None) or ""
        people = [(str(f["uid"]), str(f.get("name") or "?"), clean_emoji(f.get("emoji")), bool(f.get("mutual")))
                  for f in data.get("friends") or [] if f.get("uid")]
        return code, people, self._knocks(data.get("knocks"))

    def ensure_friend_code(self, existing=None):
        if existing:
            return existing
        status, data = self._call("POST", "/codes", {})
        return str(data.get("code") or "") or None if status == 200 else None

    def new_friend_code(self, old=None):
        """(code, error): a fresh code; the old one stops working."""
        try:
            status, data = self._call("POST", "/codes", {})
        except TransportError:
            return None, "Couldn't make a new code. Check your connection."
        if status != 200:
            return None, "Couldn't make a new code. Try again."
        return str(data["code"]), None

    def add_friend(self, code):
        """(info, error). Adding a code also knocks its owner, so their
        board offers Add back."""
        code = friend_code_from(code) or str(code or "").strip().upper()
        if not code:
            return None, "That code doesn't match anyone."
        status, data = self._call("POST", f"/codes/{code}/add")
        err = data.get("error")
        if status == 200:
            return {"user_id": str(data["uid"]), "name": str(data.get("name") or "?"),
                    "mutual": bool(data.get("mutual")), "knocked": bool(data.get("knocked"))}, None
        return None, {"own_code": "That's your own code.", "already": "Already in your crew.",
                      "no_match": "That code doesn't match anyone."}.get(err, "Couldn't add. Try again.")

    def add_back(self, uid):
        """Add someone by uid (Add back, a knock's Add). {uid, name, emoji,
        mutual} or None."""
        status, data = self._call("PUT", f"/friends/{uid}")
        return data if status == 200 else None

    def remove_friend(self, uid):
        status, _ = self._call("DELETE", f"/friends/{uid}")
        return status == 200

    # ---- cheers and knocks ----

    def send_cheer(self, to_uid, emoji, note=None, luck=False, guid=None):
        """One cheer; it replaces my last one to the same person."""
        emoji = clean_emoji(emoji)
        if not emoji:
            return False  # nothing that isn't one emoji is ever sent
        body = {"emoji": emoji}
        note = clean_note(note)
        if note:
            body["note"] = note
        if luck:
            body["luck"] = True
        if guid:
            body["guid"] = str(guid)[:40]
        status, _ = self._call("POST", f"/cheers/{to_uid}", body)
        return status == 200

    def send_knock(self, to_uid, squad):
        status, _ = self._call("POST", f"/knocks/{to_uid}", {"squad": str(squad)})
        return status == 200

    def delete_knock(self, sender_uid):
        status, _ = self._call("DELETE", f"/knocks/{sender_uid}")
        return status == 200

    # ---- squads ----

    def create_squad(self, name):
        status, data = self._call("POST", "/squads", {"name": name})
        if status != 200:
            return None
        return {k: data[k] for k in ("id", "code", "name", "founder")}

    def peek_squad(self, code):
        """The join preview: (info-or-None, status). 404 = no such squad."""
        status, data = self._call("GET", f"/squads/peek?code={code}")
        if status != 200:
            return None, status
        return {"id": data["id"], "code": data["code"], "name": data.get("name") or "?",
                "founder": str(data.get("founder") or ""), "open": data.get("open") is True}, status

    def join_squad(self, sid):
        """200, or 403 when the door is locked (or I'm blocked), 404 gone."""
        return self._call("POST", f"/squads/{sid}/join")[0]

    def leave_squad(self, sid):
        return self._call("DELETE", f"/squads/{sid}/members/{self.user_id}")[0] == 200

    def remove_member(self, sid, member_uid):
        return self._call("DELETE", f"/squads/{sid}/members/{member_uid}")[0] == 200

    def block_member(self, sid, member_uid):
        return self._call("POST", f"/squads/{sid}/block/{member_uid}")[0] == 200

    def set_founder(self, sid, member_uid):
        return self._call("PATCH", f"/squads/{sid}", {"founder": member_uid})[0] == 200

    def set_squad_open(self, sid, is_open):
        return self._call("PATCH", f"/squads/{sid}", {"open": bool(is_open)})[0] == 200

    def fetch_squad(self, sid):
        """The squad and every member's row, or None when it's gone. Raises
        TransportError (status 403: I'm not in it any more)."""
        status, data = self._call("GET", f"/squads/{sid}")
        if status == 404:
            return None
        if status != 200:
            raise TransportError(f"squad: {status}", status)
        return {"id": sid, "name": data.get("name") or "?", "founder": str(data.get("founder") or ""),
                "open": data.get("open") is True,
                "banned": [b for b in data.get("banned") or [] if isinstance(b, str)],
                "rows": [r for r in map(_clean_member, data.get("rows") or []) if r]}


def _now_iso():
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
