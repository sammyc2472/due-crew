"""Test doubles for Due Crew: fake anki collection + strict fake Firestore.

The Firestore fake validates request shape the way the real REST API does
(typed values, updateMask semantics, rules from the repo), so a malformed
client payload fails loudly here instead of silently in production.
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
    conn.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, guid TEXT)")
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


# ------------------------------------------------------------ fake firestore

VALUE_KEYS = {"stringValue", "integerValue", "doubleValue", "booleanValue",
              "timestampValue", "mapValue", "arrayValue", "nullValue"}


def _check_value(v, path="$"):
    """Strict Firestore Value validation; raises ValueError on bad shape."""
    if not isinstance(v, dict) or len(v) != 1:
        raise ValueError(f"{path}: value must be a single-key dict, got {v!r}")
    key = next(iter(v))
    if key not in VALUE_KEYS:
        raise ValueError(f"{path}: unknown value type {key!r}")
    inner = v[key]
    if key == "integerValue":
        if not isinstance(inner, str) or not re.fullmatch(r"-?\d+", inner):
            raise ValueError(f"{path}: integerValue must be a string int")
    elif key == "doubleValue":
        if not isinstance(inner, (int, float)) or isinstance(inner, bool):
            raise ValueError(f"{path}: doubleValue must be a number")
    elif key == "booleanValue":
        if not isinstance(inner, bool):
            raise ValueError(f"{path}: booleanValue must be a bool")
    elif key == "stringValue":
        if not isinstance(inner, str):
            raise ValueError(f"{path}: stringValue must be a str")
    elif key == "timestampValue":
        if not isinstance(inner, str):
            raise ValueError(f"{path}: timestampValue must be a str")
    elif key == "mapValue":
        fields = inner.get("fields", {})
        if not isinstance(fields, dict):
            raise ValueError(f"{path}: mapValue.fields must be a dict")
        for k, x in fields.items():
            if not isinstance(k, str) or not k:
                raise ValueError(f"{path}: bad map key {k!r}")
            _check_value(x, f"{path}.{k}")
    elif key == "arrayValue":
        for i, x in enumerate(inner.get("values", [])):
            _check_value(x, f"{path}[{i}]")


def _num(value):
    """A Firestore Value -> number, or None."""
    if not isinstance(value, dict):
        return None
    if "integerValue" in value:
        return int(value["integerValue"])
    if "doubleValue" in value:
        return float(value["doubleValue"])
    return None


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.content = json.dumps(self._payload).encode()

    def json(self):
        return self._payload


class RequestException(Exception):
    pass


class FakeFirestore:
    """In-memory store; enforces the repo's firestore.rules for /users/**.

    rules_mode:
      "repo"        — current repository rules (rules-v11: v10 plus my own
                      settings doc, users/{me}/private/settings)
      "v10"         — the paste before it (v2.10–v2.12): a cheer may carry
                      `luck` or a card's `guid`
      "v9"          — the paste before it (v2.9): knocks may carry the
                      recipient's own friend code
      "v8"          — the paste before it (v2.7–v2.8): any one emoji in a
                      cheer, knocks between squadmates only
      "v7"          — the paste before it (v2.5–v2.6): squads with member
                      rows, friend edges, knocks between squadmates, cheers
                      limited to the three classic emoji
      "v3"          — an old paste: markers v2+v3, the UNSCOPED
                      server_board, knocks gated only on openBoard
      "v2"          — marker v2 only, no board/knocks
      "decks-only"  — ancient drift: shared/decks literal, no markers

    This fake RESTATES the rules; it is a model of intent. Only
    tests/rules/ (the emulator) proves what the deployed text enforces.
    """

    def __init__(self, rules_mode="repo"):
        self.docs = {}          # path -> {field: Value}
        self.auth_uid = None    # uid the bearer token maps to
        self.log = []           # (method, path, status)
        self.rules_mode = rules_mode
        self.force_401 = False  # every Firestore call says "token expired"
        self.token_reply = None  # (status, payload) from the token endpoint,
                                 # or "network" to make the refresh call fail
        self.rule_reads = 0     # exists()/get() the rules made: billed as reads
        self.lock = threading.RLock()  # batches run side by side since 2.9

    # -- rules ------------------------------------------------------------
    def _friends_of(self, uid):
        """Who `uid` has added: the profile array (clients to 2.4) plus the
        edge docs (2.5+) — the rules honour both during the changeover."""
        doc = self.docs.get(f"users/{uid}", {})
        arr = doc.get("friends", {}).get("arrayValue", {}).get("values", [])
        ids = [v.get("stringValue") for v in arr]
        prefix = f"users/{uid}/friends/"
        ids += [p[len(prefix):] for p in self.docs if p.startswith(prefix) and p.count("/") == 3]
        return ids

    def _open_board(self, uid):
        doc = self.docs.get(f"users/{uid}", {})
        return doc.get("openBoard", {}).get("booleanValue") is True

    SQUAD_FIELDS = {"name", "founder", "open", "createdAt", "banned"}
    MEMBER_FIELDS = {"name", "joinedAt", "day", "reviews", "studyTimeMs",
                     "accuracy", "streak", "updatedAt", "week", "emoji"}

    def _founder(self, sid):
        return (self.docs.get(f"squads/{sid}", {}).get("founder") or {}).get("stringValue")

    def _member(self, sid, uid):
        return uid is not None and f"squads/{sid}/members/{uid}" in self.docs

    def _squad_shape(self, f):
        name = (f.get("name") or {}).get("stringValue")
        banned = (f.get("banned") or {}).get("arrayValue", {}).get("values", [])
        return (set(f) <= self.SQUAD_FIELDS and isinstance(name, str)
                and 1 <= len(name) <= 24
                and isinstance((f.get("open") or {}).get("booleanValue"), bool)
                and ("banned" not in f or ("arrayValue" in f["banned"] and len(banned) <= 200)))

    def _banned(self, sid):
        arr = (self.docs.get(f"squads/{sid}", {}).get("banned") or {}).get("arrayValue", {}).get("values", [])
        return [v.get("stringValue") for v in arr]

    def _member_shape(self, f):
        if not set(f) <= self.MEMBER_FIELDS:
            return False
        if not self._str_ok(f, "name", 60) or "name" not in f:
            return False
        for key in ("reviews", "studyTimeMs", "streak"):
            if key in f:
                r = f[key] or {}
                if "integerValue" not in r or int(r["integerValue"]) < 0:
                    return False
        if "accuracy" in f:
            a = _num(f["accuracy"])
            if a is None or not 0 <= a <= 100:
                return False
        if "week" in f:
            w = f["week"] or {}
            if "integerValue" not in w or not 0 <= int(w["integerValue"]) <= 7:
                return False
        if not self._str_ok(f, "emoji", 16):
            return False
        if "day" in f and not self.DAY_RE.fullmatch((f["day"] or {}).get("stringValue", "")):
            return False
        return True

    CHEERS = {"\U0001F389", "\U0001F4AA", "\U0001F525"}  # all that rules before v8 accept
    MARKERS = {"repo": ("rules-v2", "rules-v3", "rules-v4", "rules-v5", "rules-v6", "rules-v7", "rules-v8",
                        "rules-v9", "rules-v10", "rules-v11"),
               "v10": ("rules-v2", "rules-v3", "rules-v4", "rules-v5", "rules-v6", "rules-v7", "rules-v8",
                       "rules-v9", "rules-v10"),
               "v9": ("rules-v2", "rules-v3", "rules-v4", "rules-v5", "rules-v6", "rules-v7", "rules-v8",
                      "rules-v9"),
               "v8": ("rules-v2", "rules-v3", "rules-v4", "rules-v5", "rules-v6", "rules-v7", "rules-v8"),
               "v7": ("rules-v2", "rules-v3", "rules-v4", "rules-v5", "rules-v6", "rules-v7"),
               "v3": ("rules-v2", "rules-v3"), "decks-only": ()}
    MODERN = ("repo", "v10", "v9", "v8", "v7")  # everything v2.5 brought is in all of these
    ANY_EMOJI = ("repo", "v10", "v9", "v8")      # rules-v8: any one emoji in a cheer
    CODE_KNOCKS = ("repo", "v10", "v9")          # rules-v9: a knock may carry a friend code
    # Firestore: 20 exists()/get() calls per multi-document read, and
    # isFriend() spends one per friend with an edge doc, two without
    ACCESS_CALLS = 20

    ROW_FIELDS = {"name", "reviews", "studyTimeMs", "streak", "updatedAt"}
    DAY_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")

    @staticmethod
    def _str_ok(f, key, limit):
        if key not in f:
            return True
        v = (f[key] or {}).get("stringValue")
        return isinstance(v, str) and len(v) <= limit

    def _can_write(self, path, uid, method="PATCH", fields=None):
        m = re.fullmatch(r"users/([^/]+)", path)
        if m:
            f = fields or {}
            friends = (f.get("friends") or {}).get("arrayValue", {}).get("values", [])
            return (uid == m.group(1) and self._str_ok(f, "displayName", 60)
                    and self._str_ok(f, "emoji", 16)
                    and ("friends" not in f or ("arrayValue" in f["friends"]
                                                and len(friends) <= 500)))
        m = re.fullmatch(r"users/([^/]+)/friends/([^/]+)", path)
        if m:
            if self.rules_mode not in self.MODERN or uid != m.group(1):
                return False
            return method == "DELETE" or set(fields or {}) <= {"at"}
        m = re.fullmatch(r"users/([^/]+)/daily_stats/[^/]+", path)
        if m:
            return uid == m.group(1)
        m = re.fullmatch(r"users/([^/]+)/shared/([^/]+)", path)
        if m:
            if self.rules_mode == "decks-only" and m.group(2) != "decks":
                return False
            return uid == m.group(1)
        m = re.fullmatch(r"users/([^/]+)/cheers/([^/]+)", path)
        if m:
            owner, sender = m.groups()
            if method == "DELETE":
                return uid == owner
            f = fields or {}
            allowed = {"emoji", "name", "at"}
            if self.rules_mode in self.MODERN:
                allowed.add("note")  # rules-v5: optional, <= 80 chars
            if self.rules_mode in ("repo", "v10"):
                allowed |= {"luck", "guid"}  # rules-v10
            note = (f.get("note") or {}).get("stringValue")
            emoji = (f.get("emoji") or {}).get("stringValue")
            if self.rules_mode in self.ANY_EMOJI:
                # rules-v8: any one emoji, by shape — no letters, digits or
                # spaces, at most 16 UTF-16 units (the unit size() counts)
                emoji_ok = (isinstance(emoji, str)
                            and len(emoji.encode("utf-16-le")) // 2 <= 16
                            and re.fullmatch(r"[^A-Za-z0-9 ]+", emoji) is not None)
            else:
                emoji_ok = emoji in self.CHEERS
            return (uid == sender and uid in self._friends_of(owner)
                    and set(f) <= allowed
                    and emoji_ok
                    and self._str_ok(f, "name", 60)
                    and "timestampValue" in (f.get("at") or {})
                    and ("note" not in f
                         or (isinstance(note, str) and len(note) <= 80))
                    and ("luck" not in f or isinstance((f["luck"] or {}).get("booleanValue"), bool))
                    and ("guid" not in f or len((f["guid"] or {}).get("stringValue", "x" * 99)) <= 40))
        m = re.fullmatch(r"users/([^/]+)/knocks/([^/]+)", path)
        if m:
            owner, sender = m.groups()
            if self.rules_mode == "decks-only":
                return False
            if method == "DELETE":
                return uid == owner
            f = fields or {}
            if self.rules_mode not in self.MODERN:  # v1.8–2.2: both on the Everyone board
                return (uid == sender and self._open_board(owner)
                        and self._open_board(sender) and set(f) <= {"name", "at"})
            squad = (f.get("squad") or {}).get("stringValue")
            code = (f.get("code") or {}).get("stringValue")
            keys = {"name", "at", "squad", "code"} if self.rules_mode in self.CODE_KNOCKS else {"name", "at", "squad"}
            by_squad = (isinstance(squad, str) and len(squad) <= 40
                        and self._member(squad, sender) and self._member(squad, owner))
            # rules-v9: or the recipient's own friend code, which only they hand out
            by_code = (self.rules_mode in self.CODE_KNOCKS and isinstance(code, str) and len(code) == 6
                       and ((self.docs.get(f"friend_codes/{code}") or {}).get("userId") or {})
                       .get("stringValue") == owner)
            return (uid == sender and set(f) <= keys
                    and self._str_ok(f, "name", 60)
                    and "timestampValue" in (f.get("at") or {})
                    and (by_squad or by_code))
        m = re.fullmatch(r"boards/([^/]+)/rows/([^/]+)", path)
        if m:
            # v2.0–v2.2 Everyone rows: no rule at all since v2.3.1
            return False
        m = re.fullmatch(r"server_board/([^/]+)", path)
        if m:
            return self.rules_mode == "v3" and uid == m.group(1)  # v1.8–1.9 only
        m = re.fullmatch(r"squads/([^/]+)", path)
        if m:
            if self.rules_mode not in self.MODERN or uid is None:
                return False
            f = fields or {}
            existing = self.docs.get(path)
            if method == "DELETE":
                return existing is not None and self._founder(m.group(1)) == uid
            if existing is None:
                return ((f.get("founder") or {}).get("stringValue") == uid
                        and self._squad_shape(f))
            merged = dict(existing, **f)
            new_founder = (merged.get("founder") or {}).get("stringValue")
            return (self._founder(m.group(1)) == uid
                    and (new_founder == uid or self._member(m.group(1), new_founder))
                    and self._squad_shape(merged))
        m = re.fullmatch(r"squads/([^/]+)/members/([^/]+)", path)
        if m:
            sid, member = m.groups()
            if self.rules_mode not in self.MODERN:
                return False
            if method == "DELETE":
                return uid == member or (uid is not None and self._founder(sid) == uid)
            if uid != member:
                return False
            existing = self.docs.get(path)
            if existing is None:
                sq = self.docs.get(f"squads/{sid}")
                if not sq or (sq.get("open") or {}).get("booleanValue") is not True:
                    return False
                if uid in self._banned(sid):
                    return False
                # a join carries joinedAt; a row update turned insert does not
                if "timestampValue" not in ((fields or {}).get("joinedAt") or {}):
                    return False
            return self._member_shape(dict(existing or {}, **(fields or {})))
        m = re.fullmatch(r"users/([^/]+)/private/([^/]+)", path)
        if m:
            if self.rules_mode != "repo" or uid != m.group(1):
                return False
            if method == "DELETE":
                return True
            f = fields or {}
            return (m.group(2) == "settings" and set(f) <= {"v", "at", "settings"}
                    and "mapValue" in (f.get("settings") or {}))
        if re.fullmatch(r"friend_codes/[^/]+", path):
            # as the rules: a new code names its maker; an existing one
            # changes or goes only at its owner's hand, and stays theirs
            owner = ((self.docs.get(path) or {}).get("userId") or {}).get("stringValue")
            if uid is None or (path in self.docs and owner != uid):
                return False
            if method == "DELETE":
                return True
            return ((fields or {}).get("userId") or {}).get("stringValue") == uid
        return False

    def _can_read(self, path, uid, listing=False):
        m = re.fullmatch(r"users/([^/]+)", path)
        if m:
            return uid is not None and not listing
        m = re.fullmatch(r"users/([^/]+)/friends/([^/]+)", path)
        if m:
            owner, friend = m.groups()
            if self.rules_mode not in self.MODERN:
                return False
            if listing:
                return uid == owner
            return uid == owner or uid == friend
        m = re.fullmatch(r"users/([^/]+)/(daily_stats|shared)/([^/]+)", path)
        if m:
            owner = m.group(1)
            if (self.rules_mode == "decks-only" and m.group(2) == "shared"
                    and m.group(3) != "decks" and uid != owner):
                return False
            return uid == owner or uid in self._friends_of(owner)
        m = re.fullmatch(r"users/([^/]+)/(cheers|knocks)/[^/]+", path)
        if m:
            return uid == m.group(1)
        m = re.fullmatch(r"meta/(.+)", path)
        if m:
            return m.group(1) in self.MARKERS[self.rules_mode]
        m = re.fullmatch(r"boards/[^/]+/rows/[^/]+", path)
        if m:
            return False  # retired in v2.3
        m = re.fullmatch(r"squads/([^/]+)", path)
        if m:
            return self.rules_mode in self.MODERN and uid is not None and not listing
        m = re.fullmatch(r"squads/([^/]+)/members/[^/]+", path)
        if m:
            return self.rules_mode in self.MODERN and self._member(m.group(1), uid)
        m = re.fullmatch(r"server_board/[^/]+", path)
        if m:
            return self.rules_mode == "v3" and self._open_board(uid)
        m = re.fullmatch(r"users/([^/]+)/private/[^/]+", path)
        if m:
            return self.rules_mode == "repo" and uid == m.group(1)
        if re.fullmatch(r"friend_codes/[^/]+", path):
            return not listing
        return False

    def _access_calls(self, paths, uid):
        """The exists()/get() calls the rules make to read `paths`: one per
        other person whose stats are read (their edge doc), two when that
        doc is missing (then their profile). Calls repeat per document but
        are cached per request, so each person counts once."""
        calls = 0
        for owner in {m.group(1) for m in (re.fullmatch(r"users/([^/]+)/(?:daily_stats|shared)/[^/]+", p)
                                          for p in paths) if m and m.group(1) != uid}:
            calls += 1 if f"users/{owner}/friends/{uid}" in self.docs else 2
        return calls

    # -- request handling --------------------------------------------------
    def handle(self, method, url, headers=None, json_body=None):
        if self.force_401:
            return FakeResponse(401, {"error": {"message": "UNAUTHENTICATED"}})
        uid = self.auth_uid if (headers or {}).get("Authorization", "").startswith("Bearer t-") else None
        m = re.match(r"https://firestore\.googleapis\.com/v1/projects/[^/]+/"
                     r"databases/\(default\)/documents(?::(\w+))?/?([^?]*)(?:\?(.*))?$", url)
        if not m:
            return FakeResponse(404, {"error": {"message": "bad url"}})
        action, path, query = m.group(1), m.group(2), m.group(3) or ""

        # :runQuery / :runAggregationQuery may hang off a parent document
        parent = ""
        if action is None and ":" in path:
            path, action = path.rsplit(":", 1)
            parent = path
        if action in ("runQuery", "runAggregationQuery"):
            body = json_body or {}
            sq = (body.get("structuredQuery")
                  or body.get("structuredAggregationQuery", {}).get("structuredQuery", {}))
            coll = sq.get("from", [{}])[0].get("collectionId", "")
            prefix = f"{parent}/{coll}" if parent else coll
            if not self._can_read(prefix + "/probe", uid, listing=True):
                self.log.append((method, action + ":" + prefix, 403))
                return FakeResponse(403, {"error": {"message": "PERMISSION_DENIED"}})
            matches = []
            for pth, fields in self.docs.items():
                if not re.fullmatch(re.escape(prefix) + r"/([^/]+)", pth):
                    continue
                ok = True
                for f in sq.get("where", {}).get("compositeFilter", {}).get("filters", []):
                    ff = f["fieldFilter"]
                    fp = ff["field"]["fieldPath"]
                    have, want = _num(fields.get(fp)), _num(ff["value"])
                    op = ff["op"]
                    if op == "EQUAL":
                        ok = ok and fields.get(fp) == ff["value"]
                    elif have is None or want is None:
                        ok = False
                    elif op == "GREATER_THAN":
                        ok = ok and have > want
                    elif op == "GREATER_THAN_OR_EQUAL":
                        ok = ok and have >= want
                    elif op == "LESS_THAN":
                        ok = ok and have < want
                if ok:
                    matches.append((pth, fields))
            if action == "runAggregationQuery":
                result = {}
                for agg in body["structuredAggregationQuery"].get("aggregations", []):
                    if "count" in agg:
                        result[agg["alias"]] = {"integerValue": str(len(matches))}
                    else:
                        field = agg["sum"]["field"]["fieldPath"]
                        result[agg["alias"]] = {"integerValue": str(sum(
                            _num(f.get(field)) or 0 for _p, f in matches))}
                self.log.append((method, action + ":" + prefix, 200))
                return FakeResponse(200, [{"result": {"aggregateFields": result}}])
            order = (sq.get("orderBy") or [{}])[0]
            if order:
                field = order["field"]["fieldPath"]
                matches.sort(key=lambda pf: _num(pf[1].get(field)) or 0,
                             reverse=order.get("direction") == "DESCENDING")
            out = [{"document": {"name": f"d/{pth}", "fields": fields}}
                   for pth, fields in matches[:sq.get("limit", 300)]]
            self.log.append((method, action + ":" + prefix, 200))
            return FakeResponse(200, out)

        if method == "GET" and len(path.split("/")) % 2 == 1:
            # collection list (odd segment count): needs read on children
            if not self._can_read(path + "/probe", uid, listing=True):
                self.log.append((method, path, 403))
                return FakeResponse(403, {"error": {"message": "PERMISSION_DENIED"}})
            docs = [{"name": f"d/{pth}", "fields": fields}
                    for pth, fields in self.docs.items()
                    if re.fullmatch(re.escape(path) + r"/[^/]+", pth)]
            self.log.append((method, path, 200))
            return FakeResponse(200, {"documents": docs})

        if action == "batchGet":
            calls = self._access_calls([full.split("/documents/")[-1]
                                        for full in json_body.get("documents", [])], uid)
            self.rule_reads += calls
            if calls > self.ACCESS_CALLS:
                self.log.append((method, "batchGet", 403))
                return FakeResponse(403, {"error": {"message": "PERMISSION_DENIED: access call limit"}})
            out = []
            for full in json_body.get("documents", []):
                p = full.split("/documents/")[-1]
                if not self._can_read(p, uid):
                    self.log.append((method, p, 403))
                    return FakeResponse(403, {"error": {"message": "PERMISSION_DENIED"}})
                if p in self.docs:
                    out.append({"found": {"name": full, "fields": self.docs[p]}})
                else:
                    out.append({"missing": full})
            self.log.append((method, "batchGet", 200))
            return FakeResponse(200, out)

        if method == "GET":
            self.rule_reads += self._access_calls([path], uid)
            if not self._can_read(path, uid):
                self.log.append((method, path, 403))
                return FakeResponse(403, {"error": {"message": "PERMISSION_DENIED"}})
            if path in self.docs:
                self.log.append((method, path, 200))
                return FakeResponse(200, {"name": f"d/{path}", "fields": self.docs[path]})
            self.log.append((method, path, 404))
            return FakeResponse(404, {"error": {"message": "NOT_FOUND"}})

        if method == "PATCH":
            fields = (json_body or {}).get("fields", {})
            try:
                for k, v in fields.items():
                    if not isinstance(k, str) or not k:
                        raise ValueError("bad field name")
                    _check_value(v, k)
            except ValueError as e:
                self.log.append((method, path, 400))
                return FakeResponse(400, {"error": {"message": f"INVALID_ARGUMENT: {e}"}})
            if "currentDocument.exists=true" in query and path not in self.docs:
                # 403, as the real emulator answers (observed 2026-09-18): the
                # rules see an update of nothing and refuse before NOT_FOUND
                self.log.append((method, path, 403))
                return FakeResponse(403, {"error": {"message": "PERMISSION_DENIED"}})
            if not self._can_write(path, uid, "PATCH", fields):
                self.log.append((method, path, 403))
                return FakeResponse(403, {"error": {"message": "PERMISSION_DENIED"}})
            mask = [p.split("=", 1)[1] for p in query.split("&")
                    if p.startswith("updateMask.fieldPaths=")]
            doc = self.docs.setdefault(path, {})
            for field in mask or list(fields):
                if field in fields:
                    doc[field] = fields[field]
                else:
                    doc.pop(field, None)   # masked but absent -> delete
            if not mask:
                self.docs[path] = dict(fields)
            self.log.append((method, path, 200))
            return FakeResponse(200, {"name": f"d/{path}", "fields": doc})

        if method == "DELETE":
            if not self._can_write(path, uid, "DELETE"):
                self.log.append((method, path, 403))
                return FakeResponse(403, {"error": {"message": "PERMISSION_DENIED"}})
            self.docs.pop(path, None)
            self.log.append((method, path, 200))
            return FakeResponse(200, {})

        return FakeResponse(405, {"error": {"message": "bad method"}})


class FakeSession:
    def __init__(self, store):
        self.store = store

    def request(self, method, url, headers=None, timeout=None, **kw):
        with self.store.lock:
            return self.store.handle(method, url, headers=headers, json_body=kw.get("json"))

    def post(self, url, params=None, json=None, data=None, timeout=None):
        reply = self.store.token_reply
        if "securetoken" in url and reply is not None:
            if reply == "network":
                raise RequestException("offline")
            return FakeResponse(*reply)
        raise RequestException("auth endpoints not faked")


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
