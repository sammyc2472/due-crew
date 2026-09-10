"""Test doubles for Due Crew: fake anki collection + strict fake Firestore.

The Firestore fake validates request shape the way the real REST API does
(typed values, updateMask semantics, rules from the repo), so a malformed
client payload fails loudly here instead of silently in production.
"""

import datetime
import json
import re
import sys
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
    conn.execute("CREATE TABLE revlog (id INTEGER PRIMARY KEY, ease INTEGER, "
                 "time INTEGER, type INTEGER)")
    return conn


def add_review(conn, ts_ms, ease=3, time_ms=6000, rtype=1):
    # revlog ids are epoch-ms and must be unique
    while conn.execute("SELECT 1 FROM revlog WHERE id=?", (ts_ms,)).fetchone():
        ts_ms += 1
    conn.execute("INSERT INTO revlog VALUES (?,?,?,?)", (ts_ms, ease, time_ms, rtype))
    return ts_ms


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
      "repo"        — current repository rules (rules-v6: markers v2..v6,
                      squads with member rows, knocks between squadmates,
                      boards/ and server_board retired)
      "v3"          — the previous paste: markers v2+v3, the UNSCOPED
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

    # -- rules ------------------------------------------------------------
    def _friends_of(self, uid):
        doc = self.docs.get(f"users/{uid}", {})
        arr = doc.get("friends", {}).get("arrayValue", {}).get("values", [])
        return [v.get("stringValue") for v in arr]

    def _open_board(self, uid):
        doc = self.docs.get(f"users/{uid}", {})
        return doc.get("openBoard", {}).get("booleanValue") is True

    SQUAD_FIELDS = {"name", "founder", "open", "createdAt"}
    MEMBER_FIELDS = {"name", "joinedAt", "day", "reviews", "studyTimeMs",
                     "accuracy", "streak", "updatedAt"}

    def _founder(self, sid):
        return (self.docs.get(f"squads/{sid}", {}).get("founder") or {}).get("stringValue")

    def _member(self, sid, uid):
        return uid is not None and f"squads/{sid}/members/{uid}" in self.docs

    def _squad_shape(self, f):
        name = (f.get("name") or {}).get("stringValue")
        return (set(f) <= self.SQUAD_FIELDS and isinstance(name, str)
                and 1 <= len(name) <= 24
                and isinstance((f.get("open") or {}).get("booleanValue"), bool))

    def _member_shape(self, f):
        if not set(f) <= self.MEMBER_FIELDS:
            return False
        if not isinstance((f.get("name") or {}).get("stringValue"), str):
            return False
        if "reviews" in f:
            r = f["reviews"] or {}
            if "integerValue" not in r or int(r["integerValue"]) < 0:
                return False
        if "day" in f and not self.DAY_RE.fullmatch((f["day"] or {}).get("stringValue", "")):
            return False
        return True

    CHEERS = {"\U0001F389", "\U0001F4AA", "\U0001F525"}
    MARKERS = {"repo": ("rules-v2", "rules-v3", "rules-v4", "rules-v5", "rules-v6"),
               "v3": ("rules-v2", "rules-v3"), "decks-only": ()}

    ROW_FIELDS = {"name", "reviews", "studyTimeMs", "streak", "updatedAt"}
    DAY_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")

    def _can_write(self, path, uid, method="PATCH", fields=None):
        m = re.fullmatch(r"users/([^/]+)", path)
        if m:
            return uid == m.group(1)
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
            if self.rules_mode == "repo":
                allowed.add("note")  # rules-v5: optional, <= 80 chars
            note = (f.get("note") or {}).get("stringValue")
            return (uid == sender and uid in self._friends_of(owner)
                    and set(f) <= allowed
                    and (f.get("emoji") or {}).get("stringValue") in self.CHEERS
                    and ("note" not in f
                         or (isinstance(note, str) and len(note) <= 80)))
        m = re.fullmatch(r"users/([^/]+)/knocks/([^/]+)", path)
        if m:
            owner, sender = m.groups()
            if self.rules_mode == "decks-only":
                return False
            if method == "DELETE":
                return uid == owner
            f = fields or {}
            if self.rules_mode != "repo":  # v1.8–2.2: both on the Everyone board
                return (uid == sender and self._open_board(owner)
                        and self._open_board(sender) and set(f) <= {"name", "at"})
            squad = (f.get("squad") or {}).get("stringValue")
            return (uid == sender and set(f) <= {"name", "at", "squad"}
                    and isinstance(squad, str) and self._member(squad, sender)
                    and self._member(squad, owner))
        m = re.fullmatch(r"boards/([^/]+)/rows/([^/]+)", path)
        if m:
            _day, owner = m.groups()
            # retired in v2.3: owners may still delete their rows
            return self.rules_mode == "repo" and method == "DELETE" and uid == owner
        m = re.fullmatch(r"server_board/([^/]+)", path)
        if m:
            if self.rules_mode == "repo":
                return method == "DELETE" and uid == m.group(1)
            return uid == m.group(1)  # v3 rules: still owner-writable
        m = re.fullmatch(r"squads/([^/]+)", path)
        if m:
            if self.rules_mode != "repo" or uid is None:
                return False
            f = fields or {}
            existing = self.docs.get(path)
            if method == "DELETE":
                return existing is not None and self._founder(m.group(1)) == uid
            if existing is None:
                return ((f.get("founder") or {}).get("stringValue") == uid
                        and self._squad_shape(f))
            merged = dict(existing, **f)
            return (self._founder(m.group(1)) == uid
                    and (merged.get("founder") or {}).get("stringValue") == uid
                    and self._squad_shape(merged))
        m = re.fullmatch(r"squads/([^/]+)/members/([^/]+)", path)
        if m:
            sid, member = m.groups()
            if self.rules_mode != "repo":
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
            return self._member_shape(dict(existing or {}, **(fields or {})))
        if re.fullmatch(r"friend_codes/[^/]+", path):
            return uid is not None
        return False

    def _can_read(self, path, uid, listing=False):
        m = re.fullmatch(r"users/([^/]+)", path)
        if m:
            return uid is not None
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
            return self.rules_mode == "repo" and uid is not None and not listing
        m = re.fullmatch(r"squads/([^/]+)/members/[^/]+", path)
        if m:
            return self.rules_mode == "repo" and self._member(m.group(1), uid)
        m = re.fullmatch(r"server_board/[^/]+", path)
        if m:
            return self.rules_mode == "v3" and self._open_board(uid)
        if re.fullmatch(r"friend_codes/[^/]+", path):
            return True
        return False

    # -- request handling --------------------------------------------------
    def handle(self, method, url, headers=None, json_body=None):
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
        return self.store.handle(method, url, headers=headers, json_body=kw.get("json"))

    def post(self, url, params=None, json=None, data=None, timeout=None):
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
                 "profile_did_open"):
        setattr(hooks, name, types.SimpleNamespace(append=lambda f: None))
    aqt.gui_hooks = hooks
    deckbrowser = types.ModuleType("aqt.deckbrowser")
    deckbrowser.DeckBrowser = type("DeckBrowser", (), {})
    qt = types.ModuleType("aqt.qt")
    for name in ("QAction", "QApplication", "QCursor", "QMenu"):
        setattr(qt, name, type(name, (), {"__init__": lambda self, *a, **k: None}))
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
