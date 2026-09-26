"""Test doubles for Due Crew: a fake anki collection, and a fake of the
3.0 Worker API (worker/) in memory, so the client suite runs on the
standard library alone. The fake restates the Worker's consent and shape
rules; worker/test proves the real thing in workerd with D1.
"""

import datetime
import json
import re
import sys
import threading
import types


# ---------------------------------------------------------------- fake anki

class FakeDB:
    """Backed by a real sqlite3 database with a revlog table."""

    def __init__(self, conn):
        self.conn = conn

    def scalar(self, sql, *args):
        row = self.conn.execute(sql, args).fetchone()
        return row[0] if row else None

    def first(self, sql, *args):
        return self.conn.execute(sql, args).fetchone()

    def all(self, sql, *args):
        return self.conn.execute(sql, args).fetchall()

    def list(self, sql, *args):
        return [r[0] for r in self.conn.execute(sql, args).fetchall()]


class FakeSched:
    def __init__(self, day_cutoff):
        self.day_cutoff = day_cutoff


class FakeCol:
    def __init__(self, conn, day_cutoff):
        self.db = FakeDB(conn)
        self.sched = FakeSched(day_cutoff)


def make_collection(conn):
    """The slices of Anki's schema the add-on queries: revlog (with cid, so
    reviews can be credited to a deck), cards, and notes."""
    conn.execute("CREATE TABLE revlog (id INTEGER PRIMARY KEY, ease INTEGER, "
                 "time INTEGER, type INTEGER, cid INTEGER DEFAULT 0)")
    conn.execute("CREATE TABLE cards (id INTEGER PRIMARY KEY, nid INTEGER, did INTEGER, "
                 "odid INTEGER DEFAULT 0, type INTEGER DEFAULT 0, "
                 "queue INTEGER DEFAULT 0, ivl INTEGER DEFAULT 0)")
    conn.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, guid TEXT, flds TEXT DEFAULT '')")
    return conn


def add_review(conn, ts_ms, ease=3, time_ms=6000, rtype=1, cid=0):
    # revlog ids are epoch-ms and must be unique
    while conn.execute("SELECT 1 FROM revlog WHERE id=?", (ts_ms,)).fetchone():
        ts_ms += 1
    conn.execute("INSERT INTO revlog (id, ease, time, type, cid) VALUES (?,?,?,?,?)",
                 (ts_ms, ease, time_ms, rtype, cid))
    return ts_ms


def add_card(conn, cid, did, ctype=0, queue=0, ivl=0, odid=0):
    """ctype 0 new / 2 review; queue -1 suspended; ivl >= 21 is mature."""
    conn.execute("INSERT INTO notes (id, guid) VALUES (?, ?)", (cid, f"guid{cid:06d}"))
    conn.execute("INSERT INTO cards (id, nid, did, odid, type, queue, ivl) VALUES (?,?,?,?,?,?,?)",
                 (cid, cid, did, odid, ctype, queue, ivl))


class FakeDecks:
    """{did: name}, children by the "Parent::Child" naming Anki uses."""
    def __init__(self, names):
        self.names = dict(names)

    def get(self, did, default=True):
        return {"id": did, "name": self.names[did], "dyn": 0} if did in self.names else False

    def name(self, did):
        return self.names.get(did, "?")

    def deck_and_child_ids(self, did):
        root = self.names.get(did, "\0")
        return [d for d, n in self.names.items() if d == did or n.startswith(root + "::")]

    def all_names_and_ids(self):
        return [types.SimpleNamespace(id=d, name=n) for d, n in self.names.items()]


# ------------------------------------------------------------ fake worker

class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.content = json.dumps(self._payload).encode()

    def json(self):
        return self._payload


class RequestException(Exception):
    pass


DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
EMOJI_RE = re.compile(r"[^A-Za-z0-9 ]+")
SQUAD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _u16(s):
    return len(s.encode("utf-16-le")) // 2


def _is_emoji(v):
    return isinstance(v, str) and 1 <= _u16(v) <= 16 and bool(EMOJI_RE.fullmatch(v))


def _is_int(v, lo=0, hi=None):
    return isinstance(v, int) and not isinstance(v, bool) and v >= lo and (hi is None or v <= hi)


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Bad(Exception):
    def __init__(self, status, code):
        super().__init__(code)
        self.status, self.code = status, code


class FakeWorker:
    """The Worker's API in memory: worker/src restated in Python, so the
    client suite needs nothing but the standard library. It's a model of
    the Worker, as the old fake was of the Firestore rules; worker/test is
    what proves the real one (in workerd, with D1).

    Every request is logged as (method, path, status): the request budget
    tests count them. `writes` counts rows the server wrote."""

    def __init__(self):
        self.users = {}      # uid -> {email, name, emoji, code, client_version, tz, rollover}
        self.tokens = {}     # token -> uid
        self.friends = set()  # (owner, friend)
        self.weeks = {}      # uid -> (json text, updatedAt)
        self.decks = {}      # uid -> list
        self.heat = {}       # uid -> {"counts": {...}}
        self.cheers = {}     # (to, from) -> {emoji, note, luck, guid, at}
        self.knocks = {}     # (to, from) -> {squad, at}
        self.squads = {}     # id -> {name, founder, open}
        self.members = {}    # (sid, uid) -> row
        self.bans = set()    # (sid, uid)
        self.settings = {}   # uid -> {v, at, settings}
        self.codes = {}      # code -> uid
        self.otp = {}        # email -> code
        self.log = []        # (method, path, status)
        self.bodies = []     # (method, path, json body)
        self.writes = 0      # rows written, all tables
        self.wrote = {}      # table -> rows written
        self.min_client = "3.0.0"
        self.down = False    # no network at all
        self.fail_status = None  # every request answers this (a 5xx, say)
        self.lock = threading.RLock()
        self._seq = 0

    # -- setup helpers ---------------------------------------------------
    def add_user(self, uid, name, email=None, code=None):
        self.users[uid] = {"email": email or f"{uid}@example.com", "name": name, "emoji": None,
                           "code": code, "client_version": None, "tz": None, "rollover": None}
        if code:
            self.codes[code] = uid
        return self.session_for(uid)

    def session_for(self, uid):
        """A fresh session token for an existing user."""
        token = f"tok-{uid}-{len(self.tokens)}".ljust(43, "x")[:43]
        self.tokens[token] = uid
        return token

    def _count(self, table, n=1):
        self.writes += n
        self.wrote[table] = self.wrote.get(table, 0) + n

    def befriend(self, a, b):
        self.friends.add((a, b))

    def mutual(self, a, b):
        return (a, b) in self.friends and (b, a) in self.friends

    def requests(self, method=None, prefix=""):
        return [(m, p, s) for m, p, s in self.log
                if (method is None or m == method) and p.startswith(prefix)]

    # -- transport ---------------------------------------------------------
    def handle(self, method, url, headers=None, json_body=None):
        if self.down:
            raise RequestException("offline")
        if self.fail_status:
            self.log.append((method, url.split("?")[0], self.fail_status))
            return FakeResponse(self.fail_status, {"error": "server"})
        path = url.split("://", 1)[-1]
        path = "/" + path.split("/", 1)[1] if "/" in path else "/"
        route, _, query = path.partition("?")
        auth = (headers or {}).get("Authorization", "")
        try:
            self.bodies.append((method, route, json_body))
            status, body = self._route(method, route, dict(p.split("=", 1) for p in query.split("&") if "=" in p),
                                       auth, json_body)
        except Bad as e:
            status, body = e.status, {"error": e.code}
        self.log.append((method, route, status))
        return FakeResponse(status, body)

    def _me(self, auth):
        token = auth[7:] if auth.startswith("Bearer ") else ""
        uid = self.tokens.get(token)
        if not uid or uid not in self.users:
            raise Bad(401, "auth")
        return uid

    def _route(self, method, path, query, auth, body):
        parts = [p for p in path.split("/") if p]
        m = (method, parts[0] if parts else "")
        if path == "/version" and method == "GET":
            return 200, {"api": 1, "minClient": self.min_client}
        if parts[:1] == ["auth"]:
            return self._auth(method, parts[1:], auth, body or {})
        me = self._me(auth)
        if m == ("GET", "board"):
            return 200, self._board(me, query.get("decks") == "1")
        if m == ("POST", "sync"):
            return self._sync(me, body or {})
        if m == ("GET", "decks"):
            return 200, {"decks": self._decks_for(me)}
        if m == ("GET", "heatmap") and len(parts) == 2:
            uid = parts[1]
            if uid != me and not self.mutual(me, uid):
                raise Bad(403, "not_friends")
            return 200, {"counts": (self.heat.get(uid) or {}).get("counts")}
        if m == ("GET", "settings"):
            if me not in self.settings:
                raise Bad(404, "no_settings")
            return 200, dict(self.settings[me])
        if m == ("PUT", "settings"):
            self._put_settings(me, body)
            return 200, {"ok": True}
        if m == ("GET", "users") and len(parts) == 2:
            u = self.users.get(parts[1])
            if not u:
                raise Bad(404, "no_user")
            return 200, {"uid": parts[1], "name": u["name"] or "?", "emoji": u["emoji"] or ""}
        if parts[:1] == ["friends"]:
            return self._friends(method, me, parts[1:], body)
        if parts[:1] == ["codes"]:
            return self._codes(method, me, parts[1:], body)
        if m == ("POST", "cheers") and len(parts) == 2:
            return self._cheer(me, parts[1], body or {})
        if parts[:1] == ["knocks"]:
            return self._knock(method, me, parts[1:], body or {})
        if parts[:1] == ["squads"]:
            return self._squad(method, me, parts[1:], query, body or {})
        if m == ("DELETE", "account"):
            self._delete_account(me)
            return 200, {"ok": True}
        raise Bad(404, "not_found")

    # -- auth --------------------------------------------------------------
    def _auth(self, method, rest, auth, body):
        what = rest[0] if rest else ""
        if what == "code" and method == "POST":
            email = str(body.get("email") or "").strip().lower()
            if "@" not in email:
                raise Bad(400, "bad_email")
            self.otp[email] = "%06d" % ((len(self.otp) + 1) * 7919 % 1000000)
            return 200, {"ok": True}
        if what == "verify" and method == "POST":
            email = str(body.get("email") or "").strip().lower()
            if self.otp.get(email) is None:
                raise Bad(400, "expired")
            if str(body.get("code")) != self.otp[email]:
                raise Bad(400, "wrong_code")
            del self.otp[email]
            uid = next((u for u, d in self.users.items() if d["email"] == email), None)
            new = uid is None
            if new:
                self._seq += 1
                uid = f"U{self._seq:025d}"
                self.users[uid] = {"email": email, "name": None, "emoji": None, "code": None,
                                   "client_version": None, "tz": None, "rollover": None}
            token = f"tok-{uid}-{len(self.tokens)}".ljust(43, "x")[:43]
            self.tokens[token] = uid
            return 200, {"token": token, "uid": uid, "new": new, "name": self.users[uid]["name"]}
        me = self._me(auth)
        if what == "me" and method == "GET":
            u = self.users[me]
            return 200, {"uid": me, "email": u["email"], "name": u["name"], "emoji": u["emoji"]}
        if what == "signout" and method == "POST":
            self.tokens = {t: u for t, u in self.tokens.items() if t != auth[7:]}
            return 200, {"ok": True}
        raise Bad(404, "not_found")

    # -- board and sync ------------------------------------------------------
    def _week_of(self, uid):
        w = self.weeks.get(uid)
        return (json.loads(w[0]), w[1]) if w else (None, "")

    def _board(self, me, with_decks):
        u = self.users[me]
        week, at = self._week_of(me)
        friends = []
        for owner, fid in sorted(self.friends):
            if owner != me or fid not in self.users:
                continue
            f = self.users[fid]
            if self.mutual(me, fid):
                fw, fat = self._week_of(fid)
                friends.append({"uid": fid, "name": f["name"] or "?", "emoji": f["emoji"] or "",
                                "mutual": True, "week": fw, "updatedAt": fat})
            else:
                friends.append({"uid": fid, "name": f["name"] or "?", "emoji": f["emoji"] or "",
                                "mutual": False})
        cheers = []
        for (to, frm), c in sorted(self.cheers.items()):
            if to != me:
                continue
            if self.mutual(me, frm):
                cheers.append({"from": frm, "name": self.users[frm]["name"] or "?", "emoji": c["emoji"],
                               "note": c.get("note") or "", "luck": bool(c.get("luck")),
                               "guid": c.get("guid") or "", "at": c["at"]})
        for key in [k for k in self.cheers if k[0] == me]:
            del self.cheers[key]
        out = {"me": {"uid": me, "name": u["name"] or "", "emoji": u["emoji"] or "", "code": u["code"] or "",
                      "week": week, "updatedAt": at},
               "friends": friends, "cheers": cheers, "knocks": self._knocks_of(me)}
        if with_decks:
            out["decks"] = self._decks_for(me)
        return out

    def _decks_for(self, me):
        return {u: d for u, d in self.decks.items() if u == me or self.mutual(me, u)}

    def _knocks_of(self, me):
        return [{"from": frm, "name": self.users[frm]["name"] or "?", "emoji": self.users[frm]["emoji"] or "",
                 "squad": k.get("squad") or ""}
                for (to, frm), k in sorted(self.knocks.items()) if to == me and frm in self.users]

    WEEK_KEYS = {"v", "days", "paused", "examDate", "awayFrom", "awayTo", "liveUntil", "tricky", "room"}
    DAY_KEYS = {"studied", "reviews", "studyTimeMs", "streak", "newCards", "accuracy", "status"}

    def _clean_week(self, w):
        if not isinstance(w, dict) or not set(w) <= self.WEEK_KEYS:
            raise Bad(400, "bad_week")
        days = w.get("days") or {}
        if not isinstance(days, dict) or len(days) > 9:
            raise Bad(400, "bad_week")
        for lb, d in days.items():
            if not DATE_RE.fullmatch(lb) or not isinstance(d, dict) or not set(d) <= self.DAY_KEYS:
                raise Bad(400, "bad_week")
            for k in ("reviews", "studyTimeMs", "streak", "newCards"):
                if k in d and not _is_int(d[k]):
                    raise Bad(400, "bad_week")
            if "accuracy" in d and not (isinstance(d["accuracy"], (int, float)) and 0 <= d["accuracy"] <= 100):
                raise Bad(400, "bad_week")
            if "status" in d and (not isinstance(d["status"], str) or len(d["status"]) > 80):
                raise Bad(400, "bad_week")
        out = dict(w, v=1, days=days, paused=bool(w.get("paused")))
        if "tricky" in w:
            if not isinstance(w["tricky"], list) or len(w["tricky"]) > 3:
                raise Bad(400, "bad_week")
            out["tricky"] = [{"guid": t["guid"], "deck": t.get("deck") or "", "at": t["at"]} for t in w["tricky"]]
        return out

    ROW_KEYS = {"name", "day", "reviews", "studyTimeMs", "accuracy", "streak", "week", "emoji", "newCards"}

    def _clean_row(self, r):
        if not isinstance(r, dict) or not set(r) <= self.ROW_KEYS:
            raise Bad(400, "bad_row")
        for k in ("reviews", "studyTimeMs", "streak", "newCards"):
            if r.get(k) is not None and not _is_int(r[k]):
                raise Bad(400, "bad_row")
        if r.get("week") is not None and not _is_int(r["week"], 0, 7):
            raise Bad(400, "bad_row")
        if r.get("accuracy") is not None and not (isinstance(r["accuracy"], (int, float)) and 0 <= r["accuracy"] <= 100):
            raise Bad(400, "bad_row")
        if r.get("day") is not None and not DATE_RE.fullmatch(str(r["day"])):
            raise Bad(400, "bad_row")
        if r.get("emoji") is not None and (not isinstance(r["emoji"], str) or _u16(r["emoji"]) > 16):
            raise Bad(400, "bad_row")
        return {k: r.get(k) for k in self.ROW_KEYS - {"name"}}, r.get("name")

    def _sync(self, me, body):
        if not set(body) <= {"profile", "week", "decks", "heatmap", "squads", "settings"}:
            raise Bad(400, "bad_sync")
        prof = body.get("profile")
        if prof is not None:
            if "name" in prof and (not isinstance(prof["name"], str) or not prof["name"].strip() or len(prof["name"]) > 60):
                raise Bad(400, "bad_name")
            if prof.get("emoji") not in (None, "") and not _is_emoji(prof["emoji"]):
                raise Bad(400, "bad_emoji")
        week = self._clean_week(body["week"]) if "week" in body else None
        row = names = None
        if "squads" in body:
            row, names = self._clean_row(body["squads"].get("row"))
        wrote = {}
        u = self.users[me]
        if prof is not None:
            changed = False
            for k, key in (("name", "name"), ("emoji", "emoji"), ("clientVersion", "client_version"),
                           ("tz", "tz"), ("rollover", "rollover")):
                if k in prof and u[key] != (prof[k] or None):
                    u[key] = prof[k] or None
                    changed = True
            wrote["profile"] = changed
            self._count("users", changed)
        if week is not None:
            text = json.dumps(week, sort_keys=True)
            wrote["week"] = self.weeks.get(me, ("",))[0] != text
            if wrote["week"]:
                self.weeks[me] = (text, _now())
                self._count("weeks")
        if "decks" in body:
            wrote["decks"] = self.decks.get(me) != body["decks"]
            self.decks[me] = body["decks"]
            self._count("decks", wrote["decks"])
        if "heatmap" in body:
            want = body["heatmap"]
            wrote["heatmap"] = self.heat.get(me) != want
            if want is None:
                self.heat.pop(me, None)
            else:
                self.heat[me] = want
            self._count("heatmaps", wrote["heatmap"])
        if "settings" in body:
            self._put_settings(me, body["settings"])
        gone = []
        if "squads" in body:
            wrote["squads"] = False
            for sid in body["squads"].get("ids") or []:
                key = (sid, me)
                if key not in self.members:
                    gone.append(sid)  # an update, never an insert
                    continue
                new = dict(self.members[key], **row, name=names or self.members[key]["name"])
                if new != self.members[key]:
                    self.members[key] = new
                    wrote["squads"] = True
                    self._count("members")
        return 200, {"ok": True, "gone": gone, "wrote": wrote}

    def _put_settings(self, me, doc):
        if not isinstance(doc, dict) or set(doc) != {"v", "at", "settings"} or not isinstance(doc["settings"], dict):
            raise Bad(400, "bad_settings")
        self.settings[me] = {"v": doc["v"], "at": doc["at"], "settings": doc["settings"]}
        self._count("settings")

    # -- people ------------------------------------------------------------
    def _friends(self, method, me, rest, body):
        if method == "GET" and not rest:
            return 200, {"code": self.users[me]["code"] or "",
                         "friends": [{"uid": f, "name": self.users[f]["name"] or "?",
                                      "emoji": self.users[f]["emoji"] or "", "mutual": self.mutual(me, f)}
                                     for o, f in sorted(self.friends) if o == me and f in self.users],
                         "knocks": self._knocks_of(me)}
        if method == "PUT" and not rest:
            ids = (body or {}).get("ids")
            if not isinstance(ids, list):
                raise Bad(400, "bad_ids")
            added = sorted({i for i in ids if i in self.users and i != me})
            for f in added:
                self.friends.add((me, f))
                if (f, me) in self.friends:
                    self.knocks.pop((me, f), None)
                else:
                    self.knocks.setdefault((f, me), {"squad": "", "at": _now()})
            return 200, {"added": added}
        fid = rest[0] if rest else ""
        if method == "PUT":
            if fid == me:
                raise Bad(400, "self")
            if fid not in self.users:
                raise Bad(404, "no_user")
            self.friends.add((me, fid))
            self.knocks.pop((me, fid), None)
            f = self.users[fid]
            return 200, {"uid": fid, "name": f["name"] or "?", "emoji": f["emoji"] or "", "mutual": self.mutual(me, fid)}
        if method == "DELETE":
            self.friends.discard((me, fid))
            return 200, {"ok": True}
        raise Bad(405, "method")

    def _codes(self, method, me, rest, body):
        if method == "POST" and not rest:
            want = (body or {}).get("code")
            old = self.users[me]["code"]
            if want and want == old:
                return 200, {"code": old}
            n = 0
            code = want if want and want not in self.codes else None
            while code is None:
                n += 1
                cand = f"C{abs(hash((me, n, len(self.codes)))) % 10**5:05d}"
                code = cand if cand not in self.codes else None
            self.codes = {c: u for c, u in self.codes.items() if u != me}
            self.codes[code] = me
            self.users[me]["code"] = code
            return 200, {"code": code}
        if method == "POST" and len(rest) == 2 and rest[1] == "add":
            code = rest[0].upper()
            owner = self.codes.get(code)
            if not owner:
                raise Bad(404, "no_match")
            if owner == me:
                raise Bad(400, "own_code")
            if (me, owner) in self.friends:
                raise Bad(409, "already")
            self.friends.add((me, owner))
            mutual = self.mutual(me, owner)
            if not mutual:
                self.knocks[(owner, me)] = {"squad": "", "at": _now()}
            o = self.users[owner]
            return 200, {"uid": owner, "name": o["name"] or "?", "emoji": o["emoji"] or "",
                         "mutual": mutual, "knocked": not mutual}
        raise Bad(405, "method")

    def _cheer(self, me, to, body):
        if not set(body) <= {"emoji", "note", "luck", "guid"} or not _is_emoji(body.get("emoji")):
            raise Bad(400, "bad_cheer")
        if body.get("note") is not None and (not isinstance(body["note"], str) or len(body["note"]) > 80):
            raise Bad(400, "bad_note")
        if "luck" in body and not isinstance(body["luck"], bool):
            raise Bad(400, "bad_luck")
        if body.get("guid") is not None and (not isinstance(body["guid"], str) or len(body["guid"]) > 40):
            raise Bad(400, "bad_guid")
        if (to, me) not in self.friends:
            raise Bad(403, "not_friends")
        self.cheers[(to, me)] = {"emoji": body["emoji"], "note": body.get("note"), "luck": body.get("luck") is True,
                                 "guid": body.get("guid"), "at": _now()}
        return 200, {"ok": True}

    def _knock(self, method, me, rest, body):
        if method == "GET" and not rest:
            return 200, {"knocks": self._knocks_of(me)}
        to = rest[0] if rest else ""
        if method == "DELETE":
            self.knocks.pop((me, to), None)
            return 200, {"ok": True}
        if method == "POST":
            if set(body) != {"squad"}:
                raise Bad(400, "bad_knock")
            sid = body["squad"]
            if to == me or (sid, me) not in self.members or (sid, to) not in self.members:
                raise Bad(403, "no_squad_in_common")
            self.knocks[(to, me)] = {"squad": sid, "at": _now()}
            return 200, {"ok": True}
        raise Bad(405, "method")

    # -- squads ------------------------------------------------------------
    @staticmethod
    def squad_id(code):
        import hashlib
        code = "".join(ch for ch in code.upper() if ch in SQUAD_ALPHABET)
        return hashlib.sha1(f"due-crew-squad:{code}".encode()).hexdigest()[:24]

    def _join(self, sid, me):
        self.members[(sid, me)] = {"name": self.users[me]["name"] or "?", "joined": len(self.members),
                                   "day": None, "reviews": None, "studyTimeMs": None, "accuracy": None,
                                   "streak": None, "week": None, "emoji": None, "newCards": None}

    def _info(self, sid, code=None):
        sq = self.squads[sid]
        out = {"id": sid, "name": sq["name"], "founder": sq["founder"], "open": sq["open"]}
        if code:
            out["code"] = code
        return out

    def _squad(self, method, me, rest, query, body):
        if method == "POST" and not rest:
            if set(body) != {"name"} or not str(body["name"]).strip() or len(body["name"].strip()) > 24:
                raise Bad(400, "bad_name")
            n = len(self.squads)
            while True:
                code = "".join(SQUAD_ALPHABET[(n * 7 + i * 13) % 32] for i in range(8))
                sid = self.squad_id(code)
                if sid not in self.squads:
                    break
                n += 1
            self.squads[sid] = {"name": " ".join(body["name"].split()), "founder": me, "open": True}
            self._join(sid, me)
            return 200, self._info(sid, code)
        if method == "GET" and rest == ["peek"]:
            code = "".join(ch for ch in str(query.get("code", "")).upper() if ch in SQUAD_ALPHABET)
            sid = self.squad_id(code)
            if len(code) != 8 or sid not in self.squads:
                raise Bad(404, "no_squad")
            return 200, self._info(sid, code)
        if method == "POST" and rest == ["restore"]:
            code = "".join(ch for ch in str(body.get("code", "")).upper() if ch in SQUAD_ALPHABET)
            sid = self.squad_id(code)
            if sid not in self.squads:
                founder = body.get("founder") if body.get("founder") in self.users else me
                self.squads[sid] = {"name": body.get("name") or "squad", "founder": founder, "open": True}
            st, info = self._squad("POST", me, [sid, "join"], {}, {})
            return st, dict(info, code=code)
        sid = rest[0] if rest else ""
        if sid not in self.squads:
            raise Bad(404, "no_squad")
        sq = self.squads[sid]
        if method == "POST" and rest[1:] == ["join"]:
            if (sid, me) in self.members:
                return 200, self._info(sid)
            if (sid, me) in self.bans:
                raise Bad(403, "blocked")
            if not sq["open"]:
                raise Bad(403, "locked")
            self._join(sid, me)
            return 200, self._info(sid)
        if method == "GET" and len(rest) == 1:
            if (sid, me) not in self.members:
                raise Bad(403, "not_member")
            rows = sorted(((u, r) for (s2, u), r in self.members.items() if s2 == sid), key=lambda x: x[1]["joined"])
            return 200, dict(self._info(sid), banned=sorted(u for s2, u in self.bans if s2 == sid) if sq["founder"] == me else [],
                             rows=[dict({k: v for k, v in r.items() if k != "joined"}, uid=u) for u, r in rows])
        if method == "PUT" and rest[1:] == ["row"]:
            row, name = self._clean_row(body)
            if (sid, me) not in self.members:
                raise Bad(403, "not_member")
            self.members[(sid, me)].update(row, name=name or self.members[(sid, me)]["name"])
            return 200, {"ok": True}
        if method == "DELETE" and rest[1:2] == ["members"]:
            who = rest[2]
            if who != me and sq["founder"] != me:
                raise Bad(403, "not_founder")
            self.members.pop((sid, who), None)
            return 200, {"ok": True}
        if method == "POST" and rest[1:2] == ["block"]:
            if sq["founder"] != me:
                raise Bad(403, "not_founder")
            self.bans.add((sid, rest[2]))
            self.members.pop((sid, rest[2]), None)
            return 200, {"ok": True}
        if method == "PATCH" and len(rest) == 1:
            if sq["founder"] != me:
                raise Bad(403, "not_founder")
            if "founder" in body:
                if (sid, body["founder"]) not in self.members:
                    raise Bad(403, "not_member")
                sq["founder"] = body["founder"]
            if "open" in body:
                sq["open"] = bool(body["open"])
            return 200, self._info(sid)
        raise Bad(405, "method")

    def _delete_account(self, me):
        email = self.users[me]["email"]
        for sid, sq in list(self.squads.items()):
            if sq["founder"] == me:
                others = sorted((r["joined"], u) for (s2, u), r in self.members.items() if s2 == sid and u != me)
                if others:
                    sq["founder"] = others[0][1]
                else:
                    del self.squads[sid]
        self.members = {k: v for k, v in self.members.items() if k[1] != me}
        self.friends = {e for e in self.friends if me not in e}
        self.cheers = {k: v for k, v in self.cheers.items() if me not in k}
        self.knocks = {k: v for k, v in self.knocks.items() if me not in k}
        for table in (self.weeks, self.decks, self.heat, self.settings):
            table.pop(me, None)
        self.codes = {c: u for c, u in self.codes.items() if u != me}
        self.tokens = {t: u for t, u in self.tokens.items() if u != me}
        self.otp.pop(email, None)
        del self.users[me]


class FakeSession:
    def __init__(self, store):
        self.store = store

    def request(self, method, url, headers=None, timeout=None, **kw):
        with self.store.lock:
            return self.store.handle(method, url, headers=headers, json_body=kw.get("json"))


def install_fake_requests(store):
    """Make `import requests` inside due_crew resolve to the fake."""
    mod = types.ModuleType("requests")
    mod.Session = lambda: FakeSession(store)
    mod.RequestException = RequestException
    mod.request = lambda method, url, **kw: FakeSession(store).request(
        method, url, headers=kw.get("headers"), json=kw.get("json"))
    sys.modules["requests"] = mod


def install_fake_aqt():
    """Minimal aqt/anki surface so due_crew modules import."""
    aqt = types.ModuleType("aqt")
    aqt.mw = types.SimpleNamespace(
        pm=types.SimpleNamespace(name="TestProfile"),
        col=None, state="deckBrowser",
        addonManager=types.SimpleNamespace(
            getConfig=lambda name: {}, writeConfig=lambda n, c: None,
            setConfigAction=lambda n, f: None),
        taskman=types.SimpleNamespace(
            run_on_main=lambda f: f(), run_in_background=lambda f: f()),
        web=types.SimpleNamespace(eval=lambda js: None),
        deckBrowser=types.SimpleNamespace(refresh=lambda: None),
        form=types.SimpleNamespace(menuTools=types.SimpleNamespace(addAction=lambda a: None)),
    )
    hooks = types.ModuleType("aqt.gui_hooks")
    for name in ("deck_browser_will_render_content", "deck_browser_did_render",
                 "sync_did_finish", "webview_did_receive_js_message",
                 "profile_did_open", "profile_will_close", "card_will_show",
                 "reviewer_will_show_context_menu", "reviewer_did_show_question",
                 "reviewer_did_show_answer", "state_did_change", "top_toolbar_did_redraw"):
        setattr(hooks, name, types.SimpleNamespace(append=lambda f: None))
    aqt.gui_hooks = hooks
    deckbrowser = types.ModuleType("aqt.deckbrowser")
    deckbrowser.DeckBrowser = type("DeckBrowser", (), {})
    qt = types.ModuleType("aqt.qt")
    for name in ("QAction", "QApplication", "QCursor", "QMenu"):
        setattr(qt, name, type(name, (), {"__init__": lambda self, *a, **k: None}))
    # deferred calls are recorded, never run: tests drive the glue directly
    qt.QTimer = type("QTimer", (), {"singleShot": staticmethod(lambda ms, fn: None)})
    utils = types.ModuleType("aqt.utils")
    utils.tooltip = lambda *a, **k: None
    utils.askUser = lambda *a, **k: True
    sys.modules["aqt"] = aqt
    sys.modules["aqt.gui_hooks"] = hooks
    sys.modules["aqt.deckbrowser"] = deckbrowser
    sys.modules["aqt.qt"] = qt
    sys.modules["aqt.utils"] = utils
    return aqt


def day_cutoff_for(today, rollover_hour=4):
    """Epoch seconds of today's rollover-end (like Anki's day_cutoff)."""
    dt = datetime.datetime.combine(today + datetime.timedelta(days=1),
                                   datetime.time(rollover_hour))
    return int(dt.timestamp())
