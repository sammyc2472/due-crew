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
    def __init__(self, day_cutoff, db=None):
        self.day_cutoff = day_cutoff
        self.db = db
        self.col = None
        self.due = {}  # 3.6: {deck id: (reviews + learning due, new)} for deck_due_tree

    def deck_due_tree(self):
        """Anki's tree, flat under a root: each deck with what's due in it."""
        node = lambda did, rl, new, kids=(): types.SimpleNamespace(
            deck_id=did, review_count=rl, learn_count=0, new_count=new, children=list(kids))
        return node(0, 0, 0, [node(did, rl, new) for did, (rl, new) in self.due.items()])

    def unsuspend_cards(self, ids):
        """Anki's: a suspended card goes back to the queue its type says
        (new 0, learning 1, review 2, relearning 1). An undoable op."""
        ids = [int(i) for i in ids]
        for cid in ids:
            self.db.conn.execute("UPDATE cards SET queue = CASE type WHEN 0 THEN 0 WHEN 2 THEN 2 ELSE 1 END "
                                 "WHERE id = ? AND queue = -1", (cid,))
        if self.col is not None:
            self.col.undo_steps.append(("Unsuspend", ids))

    def schedule_cards_as_new(self, ids, restore_position=False, reset_counts=False):
        """Anki's Forget: new again (type and queue 0), lapses and reps reset when asked."""
        ids = [int(i) for i in ids]
        for cid in ids:
            self.db.conn.execute("UPDATE cards SET type = 0, queue = 0, ivl = 0"
                                 + (", lapses = 0" if reset_counts else "") + " WHERE id = ?", (cid,))
        if self.col is not None:
            self.col.undo_steps.append(("Forget", ids))

    def suspend_cards(self, ids):
        """Anki's: queue -1, whatever it was. An undoable op."""
        ids = [int(i) for i in ids]
        for cid in ids:
            self.db.conn.execute("UPDATE cards SET queue = -1 WHERE id = ?", (cid,))
        if self.col is not None:
            self.col.undo_steps.append(("Suspend", ids))


class FakeTags:
    def __init__(self, db):
        self.db = db

    def bulk_remove(self, nids, tags):
        """Anki's: those tags off those notes (any case)."""
        for nid in nids:
            row = self.db.conn.execute("SELECT tags FROM notes WHERE id = ?", (int(nid),)).fetchone()
            if row:
                kept = [t for t in str(row[0]).split() if t.lower() not in str(tags).lower().split()]
                self.db.conn.execute("UPDATE notes SET tags = ? WHERE id = ?", (" " + " ".join(kept) + " ", int(nid)))


class FakeCol:
    """A collection over a real sqlite database. The undo queue is a list
    of (name, card ids) steps, as far as the add-on uses it: a custom step,
    ops after it, and a merge that folds them into it."""

    def __init__(self, conn, day_cutoff):
        self.db = FakeDB(conn)
        self.sched = FakeSched(day_cutoff, self.db)
        self.sched.col = self
        self.undo_steps = []
        self.tags = FakeTags(self.db)

    def add_custom_undo_entry(self, name):
        self.undo_steps.append((name, []))
        return len(self.undo_steps) - 1

    def merge_undo_entries(self, pos):
        name, ids = self.undo_steps[pos]
        for _n, more in self.undo_steps[pos + 1:]:
            ids = ids + list(more)
        self.undo_steps[pos:] = [(name, ids)]
        return types.SimpleNamespace(card=True)

    def undo_status(self):
        return types.SimpleNamespace(undo=self.undo_steps[-1][0] if self.undo_steps else "")

    def undo(self):
        """The latest step, undone: its cards go back to suspended."""
        _name, ids = self.undo_steps.pop()
        for cid in ids:
            self.db.conn.execute("UPDATE cards SET queue = -1 WHERE id = ?", (cid,))


def make_collection(conn):
    """The slices of Anki's schema the add-on queries: revlog (with cid, so
    reviews can be credited to a deck), cards, and notes."""
    conn.execute("CREATE TABLE revlog (id INTEGER PRIMARY KEY, ease INTEGER, "
                 "time INTEGER, type INTEGER, cid INTEGER DEFAULT 0)")
    conn.execute("CREATE TABLE cards (id INTEGER PRIMARY KEY, nid INTEGER, did INTEGER, "
                 "odid INTEGER DEFAULT 0, type INTEGER DEFAULT 0, "
                 "queue INTEGER DEFAULT 0, ivl INTEGER DEFAULT 0, ord INTEGER DEFAULT 0, "
                 "due INTEGER DEFAULT 0, lapses INTEGER DEFAULT 0)")
    conn.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, guid TEXT, mid INTEGER DEFAULT 0, flds TEXT DEFAULT '', "
                 "tags TEXT DEFAULT '', mod INTEGER DEFAULT 0)")
    # Anki bumps a note's mod on every edit; the plan index keeps tags by it
    conn.execute("CREATE TRIGGER notes_mod AFTER UPDATE OF tags, guid, flds ON notes "
                 "BEGIN UPDATE notes SET mod = mod + 1 WHERE id = NEW.id; END")
    return conn


def add_review(conn, ts_ms, ease=3, time_ms=6000, rtype=1, cid=0):
    # revlog ids are epoch-ms and must be unique
    while conn.execute("SELECT 1 FROM revlog WHERE id=?", (ts_ms,)).fetchone():
        ts_ms += 1
    conn.execute("INSERT INTO revlog (id, ease, time, type, cid) VALUES (?,?,?,?,?)",
                 (ts_ms, ease, time_ms, rtype, cid))
    return ts_ms


def add_card(conn, cid, did, ctype=0, queue=0, ivl=0, odid=0, tags="", nid=None, ord_=0, due=0, lapses=0):
    """ctype 0 new / 2 review; queue -1 suspended; ivl >= 21 is mature.
    nid: a sibling of that note's other cards (a cloze's c2 is ord 1);
    tags: Anki's own " a b " spacing is not needed, space-separated is."""
    nid = cid if nid is None else nid
    if not conn.execute("SELECT 1 FROM notes WHERE id = ?", (nid,)).fetchone():
        conn.execute("INSERT INTO notes (id, guid, tags) VALUES (?, ?, ?)", (nid, f"guid{nid:06d}", f" {tags} "))
    conn.execute("INSERT INTO cards (id, nid, did, odid, type, queue, ivl, ord, due, lapses) VALUES (?,?,?,?,?,?,?,?,?,?)",
                 (cid, nid, did, odid, ctype, queue, ivl, ord_, due, lapses))


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


class ConnectTimeout(RequestException):
    """requests.exceptions.ConnectTimeout: the request never got out."""


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
        self.bingo_cards = {}  # 3.6: wk -> the card the Worker drew and kept (tests put them in)
        self.settings = {}   # uid -> {v, at, settings}
        self.codes = {}      # code -> uid
        self.invites = {}    # 3.5.0: code -> {uid, used_by} (the Worker keeps only a hash)
        self.reports = []    # what POST /reports mailed (the Worker stores none)
        self.feedback = []   # 3.6.5, P6: [{uid, text, ver}] for the admin's page
        self.otp = {}        # email -> code
        # 3.1: plans (worker/src/plans.ts)
        self.plans = {}      # id -> {code, owner, name, line, audience, squad, doc, version}
        self.plan_trees = {}  # (uid, deck) -> {tags, decks}
        self.follows = {}    # (plan, uid) -> {share, paused, progress (json text or None)}
        self.links = {}      # one-time site sign-in tokens -> uid
        # 3.2 (worker/src/cards.ts)
        self.knows = set()   # (uid, guid)
        self.tips = {}       # (guid, uid) -> {text, at}
        self.helped = set()  # (guid, tip_uid, by_uid)
        self.logs = {}       # uid -> {date: row}
        self.log_cut = {}    # 3.7.1: uid -> the oldest day taken again after Delete my log
        self.notices = []    # 3.2.1: [{id, text, link, below}], newest last (live ones only)
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
            self.tries = getattr(self, "tries", 0) + 1
            raise (ConnectTimeout if self.down == "connect" else RequestException)("offline")
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
        if path == "/auth/gone" and method == "GET":
            # Q4: a deleted-for-quiet uid, signed out
            return 200, {"gone": query.get("uid") in getattr(self, "gone", set())}
        if path == "/version" and method == "GET":
            return 200, {"api": 1, "minClient": self.min_client}
        if parts[:1] == ["auth"]:
            return self._auth(method, parts[1:], auth, body or {})
        me = self._me(auth)
        if m == ("GET", "board"):
            return 200, self._board(me, query.get("decks") == "1", query.get("wk"))
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
            if not u or not self._connected(me, parts[1]):  # 3.7.1, D5
                raise Bad(404, "no_user")
            return 200, {"uid": parts[1], "name": u["name"] or "?", "emoji": u["emoji"] or ""}
        if parts[:1] == ["friends"]:
            return self._friends(method, me, parts[1:], body)
        if parts[:1] == ["codes"]:
            return self._codes(method, me, parts[1:], body)
        if parts[:1] == ["invites"]:
            return self._invites(method, me, parts[1:])
        if m == ("POST", "cheers") and len(parts) == 2:
            return self._cheer(me, parts[1], body or {})
        if parts[:1] == ["knocks"]:
            return self._knock(method, me, parts[1:], body or {})
        if m == ("POST", "reports") and len(parts) == 1:
            return self._report(me, body)
        if m == ("POST", "feedback") and len(parts) == 1:  # 3.6.5, P6
            b = body or {}
            text = str(b.get("text") or "").strip() if isinstance(b.get("text"), str) else ""
            if not set(b) <= {"text", "ver"} or not text or len(text) > 2000:
                raise Bad(400, "bad_feedback")
            mine = [f for f in self.feedback if f["uid"] == me]
            if len(mine) >= 5:
                raise Bad(429, "too_many")
            self.feedback.append({"uid": me, "text": text, "ver": " ".join(str(b.get("ver") or "").split())[:120]})
            return 201, {"ok": True}
        if parts[:1] == ["squads"]:
            return self._squad(method, me, parts[1:], query, body or {})
        if parts[:1] == ["plans"]:
            return self._plans(method, me, parts[1:], query, body or {})
        if m == ("POST", "tips") and parts[1:] == ["helped"]:
            b = body or {}
            if not set(b) <= {"guid", "from", "helped"}:
                raise Bad(400, "bad_helped")
            g, frm = b.get("guid"), b.get("from")
            if (g, frm) not in self.tips or not self.mutual(me, frm):
                raise Bad(404, "no_tip")
            if b.get("helped") is False:
                self.helped.discard((g, frm, me))
            else:
                self.helped.add((g, frm, me))
            return 200, {"ok": True}
        if m == ("DELETE", "log"):  # 3.7.1, D2 (cards.ts deleteLog)
            self.logs[me] = {}
            self.log_cut[me] = (datetime.date.today() - datetime.timedelta(days=8)).isoformat()
            return 200, {"ok": True}
        if method == "DELETE" and parts == ["account", "todos"]:
            doc = self.settings.get(me)
            if doc:
                doc["settings"] = dict(doc["settings"], due_items=[], due_ticks={})
                doc["at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            return 200, {"ok": True}
        if m == ("GET", "log"):
            return 200, {"days": dict(self.logs.get(me) or {})}
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
        if what == "link" and method == "POST" and len(rest) == 1:
            token = f"link-{me}-{len(self.links)}".ljust(43, "x")[:43]
            self.links[token] = me
            return 200, {"token": token, "expiresIn": 300}
        if what == "signout" and method == "POST":
            self.tokens = {t: u for t, u in self.tokens.items() if t != auth[7:]}
            return 200, {"ok": True}
        raise Bad(404, "not_found")

    # -- board and sync ------------------------------------------------------
    def _week_of(self, uid):
        w = self.weeks.get(uid)
        return (json.loads(w[0]), w[1]) if w else (None, "")

    def _board(self, me, with_decks, wk=None):
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
               "friends": friends, "cheers": cheers, "knocks": self._knocks_of(me),
               "notice": self._notice_for(u.get("client_version")),
               "settingsAt": (self.settings.get(me) or {}).get("at") or ""}
        if with_decks:
            out["decks"] = self._decks_for(me)
            out.update(self._plans_for_board(me))  # 3.1
            # 3.6: the week's bingo card, to anyone in a squad
            if wk in self.bingo_cards and any(u == me for (_s, u) in self.members):
                out["bingo"] = self.bingo_cards[wk]
        return out

    def _notice_for(self, version):
        """3.2.1 (worker/src/notices.ts): the newest notice for this version."""
        ver = lambda v: [int(x) for x in str(v).split(".")]
        for n in reversed(self.notices):
            if not n.get("below") or (version and ver(version) < ver(n["below"])):
                return {"id": n["id"], "text": n["text"], "link": n.get("link")}
        return None

    def _decks_for(self, me):
        return {u: d for u, d in self.decks.items() if u == me or self.mutual(me, u)}

    def _knocks_of(self, me):
        return [{"from": frm, "name": self.users[frm]["name"] or "?", "emoji": self.users[frm]["emoji"] or "",
                 "squad": k.get("squad") or ""}
                for (to, frm), k in sorted(self.knocks.items()) if to == me and frm in self.users]

    WEEK_KEYS = {"v", "days", "paused", "examDate", "awayFrom", "awayTo", "liveUntil", "tricky", "room", "recap"}
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
            out["tricky"] = [dict({"guid": t["guid"], "deck": t.get("deck") or "", "at": t["at"]},
                                  **({"q": " ".join(t["q"].split())[:80]} if isinstance(t.get("q"), str) and t["q"].strip() else {}))
                             for t in w["tricky"]]
        if "recap" in w:
            r = w["recap"]
            if (not isinstance(r, dict) or not isinstance(r.get("name"), str) or not r["name"]
                    or not _is_int(r.get("n"), 1, 200) or not DATE_RE.fullmatch(str(r.get("day")))):
                raise Bad(400, "bad_week")
            out["recap"] = {"name": r["name"][:60], "n": r["n"], "day": r["day"]}
        return out

    ROW_KEYS = {"name", "day", "reviews", "studyTimeMs", "accuracy", "streak", "week", "emoji", "newCards", "play"}

    @staticmethod
    def _clean_play(v):
        """3.6 (validate.ts: play): short ids, whole numbers, wk as yyyyww."""
        if v is None:
            return None
        if not isinstance(v, dict) or len(v) > 24:
            raise Bad(400, "bad_play")
        for k, x in v.items():
            if not re.fullmatch(r"[a-z0-9]{1,8}", k) or not _is_int(x, 0, 2 ** 31 - 1):
                raise Bad(400, "bad_play")
        if not _is_int(v.get("wk"), 200001, 299953):
            raise Bad(400, "bad_play")
        return dict(v)

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
        out = {k: r.get(k) for k in self.ROW_KEYS - {"name"}}
        out["play"] = self._clean_play(r.get("play"))
        return out, r.get("name")

    def _sync(self, me, body):
        if not set(body) <= {"profile", "week", "decks", "heatmap", "squads", "settings", "plans", "knows", "stuck", "log"}:
            raise Bad(400, "bad_sync")
        prof = body.get("profile")
        if prof is not None:
            if "name" in prof and (not isinstance(prof["name"], str) or not prof["name"].strip() or len(prof["name"]) > 60):
                raise Bad(400, "bad_name")
            if prof.get("emoji") not in (None, "") and not _is_emoji(prof["emoji"]):
                raise Bad(400, "bad_emoji")
        week = self._clean_week(body["week"]) if "week" in body else None
        if week is not None:
            # 3.0.1: a flag whose tip is still waiting for me stays down
            tipped = {c.get("guid") for (to, frm), c in self.cheers.items()
                      if to == me and c.get("guid") and (frm, me) in self.friends}
            week = self._without_flags(week, tipped)
        progress = self._progress_part(body["plans"]) if "plans" in body else None
        knows = self._guids(body["knows"], {"reset", "add", "del"}) if "knows" in body else None
        stuck = body.get("stuck")
        if stuck is not None and (not isinstance(stuck, list) or len(stuck) > 300
                                  or not all(isinstance(g, str) and 0 < len(g) <= 40 for g in stuck)):
            raise Bad(400, "bad_stuck")
        log = body.get("log")
        if log is not None:
            days = log.get("days") if isinstance(log, dict) else None
            if (not isinstance(days, dict) or set(log) != {"days"} or len(days) > 400
                    or not all(DATE_RE.fullmatch(k) and isinstance(v, list) and len(v) == 4
                               and _is_int(v[0], 0, 1440) and _is_int(v[1]) and _is_int(v[2])
                               and (v[3] is None or (isinstance(v[3], (int, float)) and 0 <= v[3] <= 100))
                               for k, v in days.items())):
                raise Bad(400, "bad_log")
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
        if progress is not None:
            # only for plans I follow with sharing on, and only where it changed
            wrote["plans"] = False
            for pid, units in progress.items():
                f = self.follows.get((pid, me))
                text = json.dumps(units, sort_keys=True)
                if f and f["share"] and f["progress"] != text:
                    f["progress"] = text
                    wrote["plans"] = True
                    self._count("plan_follows")
        if knows is not None:
            before = set(self.knows)
            if knows.get("reset"):
                self.knows = {k for k in self.knows if k[0] != me}
            self.knows -= {(me, g) for g in knows["del"]}
            self.knows |= {(me, g) for g in knows["add"]}
            wrote["knows"] = bool(knows.get("reset") or knows["del"] or knows["add"])
            self._count("knows", len(self.knows ^ before))
        if log is not None:
            have = dict(self.logs.get(me) or {})
            new = dict(have, **{k: [v[0], v[1], v[2], None if v[3] is None else round(v[3], 1)]
                                for k, v in log["days"].items() if k >= self.log_cut.get(me, "")})
            new = dict(sorted(new.items())[-(15 * 366):])  # 3.7.1: the whole log (cards.ts LOG_KEEP)
            wrote["log"] = new != have
            if wrote["log"]:
                self.logs[me] = new
                self._count("logs")
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
        out = {"ok": True, "gone": gone, "wrote": wrote, "logAll": True}
        if me in self.log_cut:
            out["logCut"] = True
        if stuck is not None:
            out["cards"] = self._for_stuck(me, list(dict.fromkeys(stuck)))
        return 200, out

    def _guids(self, v, keys):
        if not isinstance(v, dict) or not set(v) <= keys:
            raise Bad(400, "bad_knows")
        out = {"reset": v.get("reset") is True}
        for k in ("add", "del"):
            xs = v.get(k) or []
            if not isinstance(xs, list) or len(xs) > 2000 or not all(isinstance(g, str) and 0 < len(g) <= 40 for g in xs):
                raise Bad(400, "bad_knows")
            out[k] = list(dict.fromkeys(xs))
        return out

    def _for_stuck(self, me, stuck):
        """Who among my mutual friends knows each card, and their tips (most helpful first)."""
        out = {}
        for g in stuck:
            knows = sorted(u for (u, gg) in self.knows if gg == g and self.mutual(me, u))[:5]
            tips = [(sum(1 for (hg, tu, _b) in self.helped if hg == g and tu == u), t["at"], u, t)
                    for (gg, u), t in self.tips.items() if gg == g and self.mutual(me, u)]
            tips.sort(key=lambda x: (-x[0], -x[1], x[2]))
            tips = [{"from": u, "text": t["text"], "at": t["at"], "helped": (g, u, me) in self.helped}
                    for _n, _a, u, t in tips[:3]]
            if knows or tips:
                out[g] = {"knows": knows, "tips": tips}
        return out

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
            self.invites = {c: i for c, i in self.invites.items() if i["uid"] != me}
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

    def _invites(self, method, me, rest):
        """3.5.0 (worker/src/invites.ts): a one-time invite makes us crew at
        once, both edges; one use."""
        if method == "POST" and not rest:
            code = f"I{len(self.invites):09d}"
            self.invites[code] = {"uid": me, "used_by": None}
            return 200, {"code": code}
        if method == "POST" and len(rest) == 2 and rest[1] == "redeem":
            inv = self.invites.get(rest[0].upper())
            if not inv:
                raise Bad(404, "no_match")
            owner = inv["uid"]
            if owner == me:
                raise Bad(400, "own_code")
            o = self.users[owner]
            info = {"uid": owner, "name": o["name"] or "?", "emoji": o["emoji"] or ""}
            if inv["used_by"] == me:
                return 200, {**info, "mutual": self.mutual(me, owner), "knocked": False}
            if not inv["used_by"]:
                inv["used_by"] = me
                self.friends |= {(me, owner), (owner, me)}
                self.knocks.pop((owner, me), None)
                self.knocks.pop((me, owner), None)
                return 200, {**info, "mutual": True, "knocked": False}
            # used: as their friend code (add, then their Add back)
            self.friends.add((me, owner))
            mutual = self.mutual(me, owner)
            if not mutual:
                self.knocks[(owner, me)] = {"squad": "", "at": _now()}
            return 200, {**info, "mutual": mutual, "knocked": not mutual}
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
        if body.get("guid") and body.get("note"):  # 3.2: a tip with words stays on its card
            self.tips[(body["guid"], me)] = {"text": " ".join(body["note"].split())[:80], "at": len(self.tips) + 1}
            self._count("tips")
        # 3.0.1: a tip from someone the flag was shown to takes it down
        if body.get("guid") and (me, to) in self.friends and to in self.weeks:
            text, at = self.weeks[to]
            new = json.dumps(self._without_flags(json.loads(text), {body["guid"]}), sort_keys=True)
            if new != text:
                self.weeks[to] = (new, at)  # a tip isn't the owner being active
                self._count("weeks")
        return 200, {"ok": True}

    @staticmethod
    def _without_flags(week, guids):
        flags = week.get("tricky")
        if not isinstance(flags, list) or not any(t.get("guid") in guids for t in flags):
            return week
        out = dict(week)
        left = [t for t in flags if t.get("guid") not in guids]
        if left:
            out["tricky"] = left
        else:
            out.pop("tricky")
        return out

    def _report(self, me, body):
        if not isinstance(body, dict) or not set(body) <= {"uid", "reason", "note"}:
            raise Bad(400, "bad_report")
        uid = body.get("uid")
        if not isinstance(uid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", uid):
            raise Bad(404, "no_user")
        if body.get("reason") not in ("cheers", "name", "other"):
            raise Bad(400, "bad_reason")
        note = body.get("note")
        if note is not None and (not isinstance(note, str) or len(note) > 500):
            raise Bad(400, "bad_note")
        if uid == me:
            raise Bad(400, "self")
        if uid not in self.users:
            raise Bad(404, "no_user")
        if sum(1 for r in self.reports if r["reporter"] == me) >= 10:
            raise Bad(429, "slow_down")
        # the Worker stores nothing and mails this; the fake keeps the mail
        u = self.users[uid]
        c = self.cheers.get((me, uid))
        self.reports.append({"reporter": me, "uid": uid, "name": u["name"] or "?", "emoji": u["emoji"] or "",
                             "reason": body["reason"], "note": " ".join(str(note or "").split()),
                             "cheer": dict(c) if c else None})
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
                                   "streak": None, "week": None, "emoji": None, "newCards": None, "play": None,
                                   "joined_day": datetime.date.today().isoformat()}

    def _connected(self, a, b):
        """social.ts connected: an edge or a knock either way, a squad or a
        plan in common."""
        if a == b or (a, b) in self.friends or (b, a) in self.friends:
            return True
        if (a, b) in self.knocks or (b, a) in self.knocks:
            return True
        sq = {s for s, u in self.members if u == a}
        if any(s in sq for s, u in self.members if u == b):
            return True

        def plans(uid):
            return ({p for p, v in self.plans.items() if v.get("owner") == uid}
                    | {p for p, u in self.follows if u == uid}
                    | {p for p, v in self.plans.items() if uid in (v.get("editors") or ())})
        return bool(plans(a) & plans(b))

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
            fu = self.users.get(self.squads[sid]["founder"]) or {}
            return 200, dict(self._info(sid, code), founderName=fu.get("name") or "")
        if method == "POST" and rest == ["restore"]:
            code = "".join(ch for ch in str(body.get("code", "")).upper() if ch in SQUAD_ALPHABET)
            sid = self.squad_id(code)
            if sid not in self.squads:
                founder = body.get("founder") if body.get("founder") in self.users else me
                self.squads[sid] = {"name": body.get("name") or "squad", "founder": founder, "open": True}
            st, info = self._squad("POST", me, [sid, "join"], {}, {"code": code})
            return st, dict(info, code=code)
        sid = rest[0] if rest else ""
        if sid not in self.squads:
            raise Bad(404, "no_squad")
        sq = self.squads[sid]
        if method == "POST" and rest[1:] == ["join"]:
            # 3.6.2: the code is required and must be this squad's (an id alone isn't a join)
            if not isinstance(body, dict) or not isinstance(body.get("code"), str) or self.squad_id(body["code"]) != sid:
                raise Bad(403, "wrong_code")
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
            out = dict(self._info(sid), banned=sorted(u for s2, u in self.bans if s2 == sid) if sq["founder"] == me else [],
                       rows=[dict({k: v for k, v in r.items() if k not in ("joined", "joined_day")}, uid=u, joined=r["joined_day"])
                             for u, r in rows])
            if query.get("wk") in self.bingo_cards:  # 3.6: the week's card with ?wk=
                out["bingo"] = self.bingo_cards[query["wk"]]
            return 200, out
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

    # -- plans (3.1): worker/src/plans.ts --------------------------------------
    UNIT_KEYS = {"id", "name", "opens", "due", "lead", "check", "tags", "decks", "cards", "n", "even", "search", "sn", "ids", "nids", "cids", "idn", "for", "notes", "idr", "pn"}
    UNIT_ID = re.compile(r"[a-z0-9]{1,12}")

    def add_plan(self, owner, name, deck, units, audience="code", squad=None, code=None):
        """Setup helper: a plan as the builder saved it. (id, code)."""
        pid = f"p{len(self.plans):015d}"
        code = code or "".join(SQUAD_ALPHABET[(len(self.plans) * 5 + i * 7 + 3) % 32] for i in range(8))
        self.plans[pid] = {"code": code, "owner": owner, "name": name, "line": "", "audience": audience,
                           "squad": squad, "doc": self._plan_doc({"deck": deck, "units": units}), "version": 1}
        return pid, code

    def edit_plan(self, pid, units):
        """The author saves new dates on the site: version + 1."""
        p = self.plans[pid]
        old = {u["id"]: u for u in p["doc"]["units"]}
        doc = self._plan_doc(dict(p["doc"], units=units))
        for u in doc["units"]:  # 3.6.5: idr only from the author's Anki, kept while the ids are
            o = old.get(u["id"]) or {}
            u.pop("idr", None)
            u.pop("pn", None)
            if o.get("idr") and o.get("nids") == u.get("nids") and o.get("cids") == u.get("cids"):
                u["idr"] = o["idr"]
            picks = lambda x: [x.get(k) or ([] if k != "opens" else None) for k in ("opens", "tags", "decks", "search", "nids", "cids", "notes")]
            if o.get("pn") and picks(o) == picks(u):
                u["pn"] = o["pn"]
        p["doc"] = doc
        p["version"] += 1

    def _plan_doc(self, v):
        if not isinstance(v, dict) or not set(v) <= {"deck", "exam", "end", "phases", "pace", "reviews", "units", "events"}:
            raise Bad(400, "plan")
        units = v.get("units")
        if not isinstance(v.get("deck"), str) or not v["deck"] or not isinstance(units, list) or len(units) > 200:
            raise Bad(400, "plan")
        out = []
        for u in units:
            if not isinstance(u, dict) or not set(u) <= self.UNIT_KEYS or not self.UNIT_ID.fullmatch(str(u.get("id"))):
                raise Bad(400, "plan")
            if not DATE_RE.fullmatch(str(u.get("opens"))) or (u.get("due") is not None and (
                    not DATE_RE.fullmatch(str(u["due"])) or u["due"] < u["opens"])):
                raise Bad(400, "plan")
            cards, seen = [], set()
            for c in u.get("cards") or []:
                if not (isinstance(c, (list, tuple)) and len(c) == 2 and isinstance(c[0], str)
                        and _is_int(c[1], 0, 1000)):
                    raise Bad(400, "plan")
                if f"{c[0]}:{c[1]}" not in seen:
                    seen.add(f"{c[0]}:{c[1]}")
                    cards.append([c[0], c[1]])
            nu = {"id": u["id"], "name": " ".join(str(u.get("name") or "").split())[:60] or "?",
                  "opens": u["opens"], "tags": list(dict.fromkeys(u.get("tags") or [])),
                  "decks": list(dict.fromkeys(u.get("decks") or [])), "cards": cards}
            if u.get("due"):
                nu["due"] = u["due"]
            if u.get("search"):
                nu["search"] = list(dict.fromkeys(u["search"]))
            if u.get("sn"):
                nu["sn"] = dict(u["sn"])
            if u.get("ids"):
                nu["ids"] = list(dict.fromkeys(u["ids"]))
            for k in ("nids", "cids"):  # E1
                got = u.get(k)
                if got is None:
                    continue
                if not isinstance(got, list) or len(got) > 5000 or not all(_is_int(x, 1, 2 ** 53) for x in got):
                    raise Bad(400, "plan")
                if got:
                    nu[k] = list(dict.fromkeys(got))
            notes = u.get("notes")  # 3.6.5: notes by guid
            if notes is not None:
                if not isinstance(notes, list) or len(notes) > 5000 or not all(isinstance(g, str) and 0 < len(g) <= 40 for g in notes):
                    raise Bad(400, "plan")
                if notes:
                    nu["notes"] = list(dict.fromkeys(notes))
            idr = u.get("idr")  # 3.6.5: the pasted ids as guid + card number, from the author's Anki
            if idr is not None:
                if not isinstance(idr, list) or len(idr) > 20000 or not all(
                        isinstance(c, (list, tuple)) and len(c) == 2 and isinstance(c[0], str) and _is_int(c[1], 0, 1000) for c in idr):
                    raise Bad(400, "plan")
                if idr and (nu.get("nids") or nu.get("cids")):
                    nu["idr"] = [[c[0], c[1]] for c in idr]
            if u.get("idn") is not None and (nu.get("nids") or nu.get("cids") or nu.get("notes")):
                nu["idn"] = u["idn"]
            pn = u.get("pn")  # 3.6.5, P1
            if pn is not None:
                if not isinstance(pn, list) or len(pn) != 3 or not all(_is_int(x, 0, 1_000_000) for x in pn):
                    raise Bad(400, "plan")
                nu["pn"] = list(pn)
            if u.get("for"):
                nu["for"] = u["for"]  # F1
            if u.get("even"):
                if u["even"] is not True or not u.get("due") or u["due"] == u["opens"]:
                    raise Bad(400, "plan")
                nu["even"] = True
            if u.get("check"):
                if not DATE_RE.fullmatch(str(u["check"])) or u["check"] < u["opens"]:
                    raise Bad(400, "plan")
                nu["check"] = u["check"]
            if u.get("n") is not None:
                if not _is_int(u["n"], 0, 1_000_000):
                    raise Bad(400, "plan")
                nu["n"] = u["n"]
            out.append(nu)
        if len({u["id"] for u in out}) != len(out) or sum(len(u["cards"]) for u in out) > 5000:
            raise Bad(400, "plan")
        out.sort(key=lambda u: u["opens"])
        doc = {"deck": v["deck"], "units": out}
        if v.get("exam"):
            doc["exam"] = v["exam"]
        evs = v.get("events") or []  # F1
        if len(evs) > 200 or not all(isinstance(e, dict) and set(e) <= {"id", "day", "name"} and e.get("id")
                                     and DATE_RE.fullmatch(str(e.get("day") or "")) and str(e.get("name") or "").strip() for e in evs):
            raise Bad(400, "plan")
        if evs:
            doc["events"] = sorted((dict(e) for e in evs), key=lambda e: e["day"])
        ev_ids = {e["id"] for e in evs}
        for u in out:
            if u.get("for") and u["for"] not in ev_ids:
                del u["for"]
        if v.get("end"):
            doc["end"] = v["end"]
        if v.get("reviews"):
            ids = {u["id"] for u in out}
            if not all(isinstance(r, dict) and r.get("from") in ids and r.get("to") in ids for r in v["reviews"]):
                raise Bad(400, "plan")
            doc["reviews"] = [dict(r) for r in v["reviews"]]
        if v.get("pace") is not None:
            pc = v["pace"]
            if (not isinstance(pc, dict) or not set(pc) <= {"mode", "days", "daily", "cover"}
                    or pc.get("mode") not in ("end", "daily", "placed")
                    or not isinstance(pc.get("days"), list) or len(pc["days"]) != 7
                    or not all(x in (0, 1) and not isinstance(x, bool) for x in pc["days"]) or not any(pc["days"])
                    or (pc.get("daily") is not None and not _is_int(pc["daily"], 1, 5000))
                    or not isinstance(pc.get("cover") or [], list) or len(pc.get("cover") or []) > 500):
                raise Bad(400, "plan")
            doc["pace"] = {k: pc[k] for k in ("mode", "days", "daily", "cover") if pc.get(k) is not None}
        ph = v.get("phases") or {}
        if ph.get("catchup") or ph.get("taper"):
            if ph.get("taper") and not v.get("end"):
                raise Bad(400, "plan")
            doc["phases"] = {"catchup": int(ph.get("catchup") or 0), "taper": int(ph.get("taper") or 0)}
        return doc

    def _may_read(self, p, pid, me, code=None):
        """The author, a follower, or whoever may follow it."""
        if p["owner"] == me or (pid, me) in self.follows:
            return True
        member = bool(p["squad"]) and (p["squad"], me) in self.members
        if p["audience"] == "squad":
            return member
        return (bool(code) and code == p["code"]) or member

    def _plan_view(self, pid, me):
        p = self.plans[pid]
        f = self.follows.get((pid, me))
        out = {"id": pid, "name": p["name"], "line": p["line"], "owner": p["owner"],
               "ownerName": (self.users.get(p["owner"]) or {}).get("name") or "?", "audience": p["audience"],
               "squad": p["squad"], "version": p["version"], "doc": json.loads(json.dumps(p["doc"])),
               "followers": sum(1 for (pl, _u) in self.follows if pl == pid)}
        if p["owner"] == me:
            out["code"] = p["code"]
        if f:
            out["following"] = {"share": f["share"], "paused": f["paused"], "sched": f.get("sched")}
        return out

    @staticmethod
    def _norm(code):
        return "".join(ch for ch in str(code or "").upper() if ch in SQUAD_ALPHABET)

    def _by_code(self, code):
        return next((pid for pid, p in self.plans.items() if p["code"] == code), None)

    def _plans(self, method, me, rest, query, body):
        if rest == ["trees"] and method == "PUT":
            if not isinstance(body.get("deck"), str) or not body["deck"]:
                raise Bad(400, "plan")
            def nested(v, prefix=0):
                for x in v:
                    if not (isinstance(x, list) and len(x) in (2, 3) and isinstance(x[0], str) and x[0]
                            and "::" not in x[0] and _is_int(x[1])):
                        raise Bad(400, "tree")
                    ln = prefix + (2 if prefix else 0) + len(x[0])
                    if ln > 200:
                        raise Bad(400, "tree")
                    if len(x) == 3:
                        nested(x[2], ln)
            for k in ("tags", "decks"):
                if body.get("v") == 2:
                    nested(body.get(k) or [])
                    continue
                for x in body.get(k) or []:
                    if not (isinstance(x, list) and len(x) == 2 and isinstance(x[0], str) and _is_int(x[1])):
                        raise Bad(400, "tree")
            doc = {"tags": body.get("tags") or [], "decks": body.get("decks") or []}
            if body.get("v") == 2:
                doc["v"] = 2
            if self.plan_trees.get((me, body["deck"])) != doc:
                self.plan_trees[(me, body["deck"])] = doc
                self._count("plan_trees")
            return 200, {"ok": True}
        if rest == ["mine"] and method == "GET":
            ids = [pid for pid, p in self.plans.items() if p["owner"] == me or (pid, me) in self.follows]
            return 200, {"plans": [self._plan_view(pid, me) for pid in ids]}
        if rest == ["peek"] and method == "GET":
            code = self._norm(query.get("code"))
            pid = self._by_code(code) if len(code) == 8 else None
            if not pid or not self._may_read(self.plans[pid], pid, me, code):
                raise Bad(404, "no_plan")
            return 200, self._plan_view(pid, me)
        if rest == ["follow"] and method == "POST":
            if not isinstance(body.get("code"), str):
                raise Bad(400, "code")
            code = self._norm(body["code"])
            pid = self._by_code(code)
            if not pid or not self._may_read(self.plans[pid], pid, me, code):
                raise Bad(404, "no_plan")
            old = self.follows.get((pid, me))
            sched = self._sched(body["sched"]) if "sched" in body else (old or {}).get("sched")
            self.follows[(pid, me)] = {"share": body.get("share") is not False, "paused": False,
                                       "progress": old["progress"] if old else None, "sched": sched}
            self._count("plan_follows")
            return 200, self._plan_view(pid, me)
        pid = rest[0] if rest else ""
        if rest[1:] == ["follow"] and method == "DELETE":
            self.follows.pop((pid, me), None)  # stopping: my progress goes with it
            return 200, {"ok": True}
        if pid not in self.plans:
            raise Bad(404, "no_plan")
        p = self.plans[pid]
        if rest[1:] == ["follow"] and method == "PATCH":
            if not set(body) <= {"share", "paused", "sched", "early", "shift", "until", "since", "skipped"} or (
                    "early" in body and not _is_int(body["early"], 0, 7)) or (
                    "shift" in body and not _is_int(body["shift"], 0, 365)) or any(
                    body.get(k) is not None and not DATE_RE.fullmatch(str(body[k])) for k in ("until", "since") if k in body) or (
                    "skipped" in body and not (isinstance(body["skipped"], list) and len(body["skipped"]) <= 200
                                               and all(isinstance(u, str) and u for u in body["skipped"]))):
                raise Bad(400, "follow")
            f = self.follows.get((pid, me))
            if not f:
                raise Bad(404, "not_following")
            share = body["share"] if isinstance(body.get("share"), bool) else f["share"]
            paused = body["paused"] if isinstance(body.get("paused"), bool) else f["paused"]
            sched = self._sched(body["sched"]) if "sched" in body else f.get("sched")
            early = body["early"] if "early" in body else f.get("early", 0)
            if (share, paused, sched, early) != (f["share"], f["paused"], f.get("sched"), f.get("early", 0)):
                f.update(share=share, paused=paused, sched=sched, early=early)
                if not share:
                    f["progress"] = None  # sharing off clears what I shared
                self._count("plan_follows")
            for k in ("shift", "until", "since"):  # G3, G4: my own days
                if k in body and body[k] != f.get(k):
                    f[k] = body[k]
                    self._count("plan_follows")
            if "skipped" in body and list(dict.fromkeys(body["skipped"])) != f.get("skipped", []):
                f["skipped"] = list(dict.fromkeys(body["skipped"]))
                self._count("plan_follows")
            return 200, {"share": share, "paused": paused, "sched": sched, "early": early,
                         "shift": f.get("shift", 0), "until": f.get("until"), "since": f.get("since"), "skipped": f.get("skipped", [])}
        if rest[1:] == ["ids"] and method == "PUT":
            if p["owner"] != me:
                raise Bad(403, "not_author")
            doc = json.loads(json.dumps(p["doc"]))
            for uid, v in (body.get("counts") or {}).items():
                u = next((x for x in doc["units"] if x["id"] == uid), None)
                if u:
                    sn = {q: n for q, n in v.items() if q in (u.get("search") or [])}
                    if sn:
                        u["sn"] = dict(u.get("sn") or {}, **sn)
                    if "#ids" in v and (u.get("nids") or u.get("cids") or u.get("notes")):
                        u["idn"] = v["#ids"]  # E1
                    pn = v.get("#pn")  # 3.6.5, P1
                    if isinstance(pn, list) and len(pn) == 3 and all(isinstance(x, int) and not isinstance(x, bool) and 0 <= x <= 1_000_000 for x in pn):
                        u["pn"] = list(pn)
            for uid, (nids, cids, refs) in (body.get("refs") or {}).items():  # 3.6.5
                u = next((x for x in doc["units"] if x["id"] == uid), None)
                if u and (u.get("nids") or []) == nids and (u.get("cids") or []) == cids:
                    if refs:
                        u["idr"] = [list(r) for r in refs]
                    else:
                        u.pop("idr", None)
            for uid, (tags, decks, ids) in (body.get("units") or {}).items():
                u = next((x for x in doc["units"] if x["id"] == uid), None)
                if u and u["tags"] == tags and u["decks"] == decks:
                    if ids:
                        u["ids"] = list(ids)
                    else:
                        u.pop("ids", None)
            clean = self._plan_doc(doc)
            if clean != p["doc"]:
                p["doc"] = clean
                p["version"] += 1
                self._count("plans")
            return 200, {"version": p["version"]}
        if rest[1:] == ["cards"] and method == "POST":
            if p["owner"] != me:
                raise Bad(403, "not_author")
            search = body.get("search")
            cards = [] if search else body.get("cards")
            if search is not None and (not isinstance(search, str) or not search or not _is_int(body.get("n"), 0, 10 ** 6)):
                raise Bad(400, "cards")
            if not search and (not isinstance(cards, list) or not cards):
                raise Bad(400, "cards")
            doc = json.loads(json.dumps(p["doc"]))
            if "unit" in body:
                u = next((x for x in doc["units"] if x["id"] == body["unit"]), None)
                if not u:
                    raise Bad(404, "no_unit")
            else:
                if not DATE_RE.fullmatch(str(body.get("opens"))):
                    raise Bad(400, "opens")
                u = {"id": f"n{len(doc['units']):07d}", "name": body.get("name") or f"Cards · {body['opens']}",
                     "opens": body["opens"], "tags": [], "decks": [], "cards": []}
                doc["units"].append(u)
            u["cards"] = u["cards"] + list(cards)
            if search:
                u["search"] = list(dict.fromkeys((u.get("search") or []) + [search]))
                u["sn"] = dict(u.get("sn") or {}, **{search: body["n"]})
            clean = self._plan_doc(doc)
            if clean != p["doc"]:
                p["doc"] = clean
                p["version"] += 1
                self._count("plans")
            return 200, self._plan_view(pid, me)
        if len(rest) == 1 and method == "GET":
            if not self._may_read(p, pid, me, self._norm(query.get("code"))):
                raise Bad(404, "no_plan")
            return 200, self._plan_view(pid, me)
        raise Bad(405, "method")

    @staticmethod
    def _sched(v):
        if v is None:
            return None
        days = v.get("days") if isinstance(v, dict) else None
        if (not isinstance(v, dict) or not set(v) <= {"start", "days", "minutes"} or not isinstance(days, list)
                or len(days) != 7 or not all(_is_int(x, 0, 2) for x in days) or not any(days)
                or not _is_int(v.get("minutes"), 10, 600)
                or (v.get("start") is not None and not DATE_RE.fullmatch(str(v["start"])))):
            raise Bad(400, "bad_sched")
        out = {"days": list(days), "minutes": v["minutes"]}
        if v.get("start"):
            out["start"] = v["start"]
        return out

    def _progress_part(self, v):
        if not isinstance(v, dict) or len(v) > 50:
            raise Bad(400, "plans")
        out = {}
        for pid, units in v.items():
            if not re.fullmatch(r"[a-z0-9]{1,32}", pid) or not isinstance(units, dict) or len(units) > 200:
                raise Bad(400, "plans")
            out[pid] = {}
            for uid, t in units.items():
                if (not self.UNIT_ID.fullmatch(uid) or not isinstance(t, list) or len(t) != 3
                        or not all(_is_int(n) for n in t) or t[0] > t[2] or t[1] > t[2]):
                    raise Bad(400, "plans")
                out[pid][uid] = list(t)
        return out

    def _plans_for_board(self, me):
        """The plans I follow (with crew counts), and squad offers."""
        plans = []
        for (pid, uid), f in sorted(self.follows.items()):
            if uid != me or pid not in self.plans:
                continue
            p = self.plans[pid]
            rows = [g for (pl, _u), g in self.follows.items() if pl == pid]
            done = {}
            for g in rows:
                if g["share"] and g["progress"]:
                    for unit, (_o, seen, total) in json.loads(g["progress"]).items():
                        if total > 0 and seen >= total:
                            done[unit] = done.get(unit, 0) + 1
            plans.append({"id": pid, "name": p["name"], "owner": p["owner"],
                          "ownerName": (self.users.get(p["owner"]) or {}).get("name") or "?",
                          "version": p["version"], "doc": json.loads(json.dumps(p["doc"])),
                          "share": f["share"], "paused": f["paused"], "sched": f.get("sched"), "early": f.get("early", 0),
                          "shift": f.get("shift", 0), "until": f.get("until"), "since": f.get("since"), "skipped": f.get("skipped", []),
                          "followers": len(rows), "crewDone": done})
        offers = [{"id": pid, "name": p["name"], "code": p["code"], "squad": p["squad"],
                   "ownerName": (self.users.get(p["owner"]) or {}).get("name") or "?"}
                  for pid, p in sorted(self.plans.items())
                  if p["squad"] and (p["squad"], me) in self.members and p["owner"] != me
                  and (pid, me) not in self.follows]
        authored = [{"id": pid, "version": p["version"], "doc": {"deck": p["doc"]["deck"], "units": [
            dict({"id": u["id"], "tags": u["tags"], "decks": u["decks"]}, **({"search": u["search"]} if u.get("search") else {}),
                 **{k: u[k] for k in ("nids", "cids", "notes", "opens") if u.get(k)})
            for u in p["doc"]["units"] if u["tags"] or u["decks"] or u.get("search") or u.get("nids") or u.get("cids")
            or u.get("notes")]}}
            for pid, p in sorted(self.plans.items()) if p["owner"] == me]
        return {"plans": plans, "planOffers": offers, "authored": authored}

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
        mine = {pid for pid, p in self.plans.items() if p["owner"] == me}
        self.follows = {k: v for k, v in self.follows.items() if k[1] != me and k[0] not in mine}
        self.plans = {pid: p for pid, p in self.plans.items() if pid not in mine}
        self.knows = {k for k in self.knows if k[0] != me}
        self.tips = {k: v for k, v in self.tips.items() if k[1] != me}
        self.helped = {k for k in self.helped if me not in (k[1], k[2])}
        self.logs.pop(me, None)
        self.plan_trees = {k: v for k, v in self.plan_trees.items() if k[0] != me}
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
        if kw.get("params"):
            from urllib.parse import urlencode
            url += ("&" if "?" in url else "?") + urlencode(kw["params"])
        with self.store.lock:
            return self.store.handle(method, url, headers=headers, json_body=kw.get("json"))


def install_fake_requests(store):
    """Make `import requests` inside due_crew resolve to the fake."""
    mod = types.ModuleType("requests")
    mod.Session = lambda: FakeSession(store)
    mod.RequestException = RequestException
    mod.exceptions = types.SimpleNamespace(ConnectTimeout=ConnectTimeout, RequestException=RequestException)
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
                 "reviewer_did_show_answer", "state_did_change", "top_toolbar_did_redraw",
                 "browser_will_show_context_menu"):
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
