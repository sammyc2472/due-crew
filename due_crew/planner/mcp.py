"""Your AI app (round five, docs/planner.md): a local MCP server, off by
default, this computer's own, so the author's own AI app (Claude Desktop,
Claude Code, any other) reads their plans and puts changes under a plan as
changes waiting (draft.py). It never sends a plan: the author reviews and
sends in Anki (Your plans › the plan › Review and send).

127.0.0.1 only. A bearer token (this computer's config, made when it's
turned on) on every request; a Host that isn't this address, or an Origin
that isn't this computer's, is turned away (DNS rebinding); 1 MB a body at
most. Streamable HTTP with JSON answers: POST /mcp, one message or a batch;
GET is 405 (no stream). Nothing it's sent is logged, the token least of all.

The host does what needs Anki (mcp_host.Host there, a fake in the suite):
plans() and plan(pid) (requests, in this server's threads), tree(pid),
today(), draft(pid) and keep_draft(pid, draft) (Anki's main thread), and
changed(pid) (an open Your plans hears of it); live(), if it has one,
raises Unavailable once its profile or account is gone. keep_draft
returning False means the draft changed under it meanwhile: it's read and
tried again.

Standard library only; nothing here imports Anki."""

import hmac
import http.server
import json
import os
import re
import socketserver
import sys
import threading
import time

from . import ai
from . import build as B
from . import draft as D
from . import edits as E
from . import ops as O
from . import text as T
from .. import plans as P

PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")  # newest first: one asked for is echoed, else the newest
BODY_MAX = 1 << 20
BATCH_MAX = 50
TAGS_MAX = 1000
CACHE_SECS = 30     # my plans and a plan, read again after this (requests are the budget)
NAME = "due-crew"
SEND = "Review and send them in Anki: Your plans › the plan › Review and send."
INSTRUCTIONS = (
    "Due Crew's study plans, from Anki on this computer. list_plans names them; read_plan shows one, its dates by "
    "id; ops_vocabulary lists the changes a plan takes; preview_changes tries them; add_to_changes puts them under "
    "the plan as changes waiting. Nothing is sent from here: the author reviews and sends them in Anki. Name a "
    "date by its id from read_plan. Never put card text in a plan.")


def version():
    """The add-on's version (its manifest), for serverInfo."""
    try:
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "manifest.json")) as f:
            return str(json.load(f).get("version") or "")
    except (OSError, ValueError):
        return ""


class Unavailable(Exception):
    """What the host can't do now, in words (signed out, Anki busy, offline)."""


class ToolError(Exception):
    """A tool's failure, in words: an isError result, never a crash."""


class _RpcError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _err(mid, code, message):
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


_ORIGIN = re.compile(r"^https?://(?:localhost|127\.0\.0\.1)(?::\d{1,5})?$", re.I)


def local_origin(origin):
    """An Origin a page on this computer sends (or none: an app sends none)."""
    o = str(origin or "").strip()
    return o in ("", "null") or bool(_ORIGIN.match(o))


# ---- the tools ----

PLAN = {"type": "string", "description": "The plan's id, or its name."}
OPS = {"type": "array", "maxItems": O.OPS_MAX, "description": "Ops, done in order (ops_vocabulary has them).",
       "items": {"type": "object", "required": ["op"], "properties": {"op": {"type": "string", "enum": sorted(O.REG)}}}}

TOOLS = [
    {"name": "list_plans",
     "description": "The plans you write or co-write (id, name, your role, how many follow it) and the ones you follow (id, name).",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "read_plan",
     "description": "One plan: its text (the plan text format), its dates by id with what's on each, its quizzes "
                    "and exams, and the changes waiting under it. The plan is shown with those changes in.",
     "inputSchema": {"type": "object", "properties": {"plan": PLAN}, "required": ["plan"]}},
    {"name": "deck_tags",
     "description": "The plan's deck in this Anki: its tags and subdecks with their card counts, as paths a date "
                    "takes. find: words in the path; under: a tag or subdeck to list below; limit: 200 unless said "
                    "(1,000 at most).",
     "inputSchema": {"type": "object", "required": ["plan"], "properties": {
         "plan": PLAN, "find": {"type": "string"}, "under": {"type": "string"},
         "limit": {"type": "integer", "minimum": 1, "maximum": TAGS_MAX}}}},
    {"name": "ops_vocabulary",
     "description": "The changes a plan takes, each an op: what it does, its fields, an example.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "preview_changes",
     "description": "What these ops would change, in words, and who each change touches; or why one won't go on. "
                    "Tried on the plan with the changes already waiting. Changes nothing.",
     "inputSchema": {"type": "object", "required": ["plan", "ops"], "properties": {"plan": PLAN, "ops": OPS}}},
    {"name": "add_to_changes",
     "description": "Puts these ops under the plan as changes waiting, on this computer. Nothing is sent: the "
                    "author reviews and sends them in Anki. Authors only. why: one line for followers (optional).",
     "inputSchema": {"type": "object", "required": ["plan", "ops"], "properties": {
         "plan": PLAN, "ops": OPS, "why": {"type": "string", "maxLength": O.WHY_MAX}}}},
]


def _ops_arg(v):
    """The ops a client sent: a list (or a JSON string of one)."""
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            raise ToolError("ops is a list of changes (ops_vocabulary has them).") from None
    if isinstance(v, dict):
        v = v.get("ops") if isinstance(v.get("ops"), list) else [v]
    if not isinstance(v, list) or not v:
        raise ToolError("ops is a list of changes (ops_vocabulary has them).")
    if len(v) > O.OPS_MAX:
        raise ToolError(f"At most {O.OPS_MAX:,} changes at once.")
    return v


def _words(x):
    return {k: x.get(k) for k in ("verb", "what", "detail", "who") if x.get(k)}


def setup(port, token, shim, http=False, python=None):
    """The MCP client setup to copy: one that starts the shim (python3
    shim --port N, the token in its environment, never on the command line),
    or the address with the bearer header. JSON, as a client's mcpServers."""
    if http:
        entry = {"type": "http", "url": f"http://127.0.0.1:{int(port)}/mcp", "headers": {"Authorization": f"Bearer {token}"}}
    else:
        py = python or ("python" if sys.platform == "win32" else "python3")
        entry = {"command": py, "args": ["-I", str(shim), "--port", str(int(port))], "env": {"DUE_CREW_MCP_TOKEN": str(token)}}
    return json.dumps({"mcpServers": {NAME: entry}}, indent=2)


# ---- the server ----

class Server:
    """The MCP server: Server(host, token, port).start(); .port, .url; .stop().
    handle(message) answers one JSON-RPC message or a batch (None: nothing to
    answer, 202)."""

    def __init__(self, host, token, port=0, cache_secs=CACHE_SECS):
        if not token:
            raise ValueError("a token first")
        self.host, self.token = host, str(token)
        self.want = int(port or 0)
        self.port = None
        self.cache_secs = cache_secs
        self._httpd = None
        self._cache = {}
        self._lock = threading.Lock()
        self._plan_locks = {}
        self._tools = {"list_plans": self._list_plans, "read_plan": self._read_plan, "deck_tags": self._deck_tags,
                       "ops_vocabulary": self._vocabulary, "preview_changes": self._preview,
                       "add_to_changes": self._add}

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}/mcp" if self.port else ""

    def start(self):
        """Bound to 127.0.0.1 (OSError when the port is taken), serving in its own thread."""
        httpd = _HTTPServer(("127.0.0.1", self.want), _Handler)
        httpd.mcp = self
        self._httpd = httpd
        self.port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True,
                         name="due-crew-mcp").start()
        return self

    def stop(self):
        """Off: a connection still open is turned away from now on (its port is gone), nothing kept is shown."""
        httpd, self._httpd = self._httpd, None
        self.port = None
        with self._lock:
            self._cache.clear()
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()

    # ---- JSON-RPC ----

    def handle(self, msg):
        if isinstance(msg, list):
            if not msg:
                return _err(None, -32600, "An empty batch.")
            out = [r for r in (self._one(m) for m in msg[:BATCH_MAX]) if r is not None]
            out += [_err(m.get("id") if isinstance(m, dict) else None, -32600, f"A batch is {BATCH_MAX} messages at most.")
                    for m in msg[BATCH_MAX:] if isinstance(m, dict) and "id" in m]
            return out or None
        return self._one(msg)

    def _one(self, m):
        if not isinstance(m, dict) or m.get("jsonrpc") != "2.0":
            return _err(m.get("id") if isinstance(m, dict) else None, -32600, "That isn't a JSON-RPC 2.0 message.")
        if "method" not in m:
            return None  # an answer to a request this server never makes
        mid, method = m.get("id"), m.get("method")
        if "id" not in m:
            return None  # a notification (notifications/initialized, a cancel): nothing to say
        if not isinstance(method, str):
            return _err(mid, -32600, "Its method is a name.")
        params = m.get("params") if isinstance(m.get("params"), dict) else {}
        try:
            return {"jsonrpc": "2.0", "id": mid, "result": self._call(method, params)}
        except _RpcError as e:
            return _err(mid, e.code, str(e))
        except Exception as e:  # noqa: BLE001 - a bug here is an error answer, never a dead server
            print(f"due crew: the AI app's server: {type(e).__name__}")
            return _err(mid, -32603, "Something went wrong in Anki.")

    def _call(self, method, params):
        if method == "initialize":
            want = params.get("protocolVersion")
            return {"protocolVersion": want if want in PROTOCOLS else PROTOCOLS[0],
                    "capabilities": {"tools": {}}, "serverInfo": {"name": NAME, "version": version()},
                    "instructions": INSTRUCTIONS}
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": TOOLS}
        if method == "tools/call":
            name = params.get("name")
            if name not in self._tools:
                raise _RpcError(-32602, f"There's no tool called {name}.")
            args = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
            return self._tool(name, args)
        raise _RpcError(-32601, f"There's no method called {method}.")

    def _tool(self, name, args):
        try:
            live = getattr(self.host, "live", None)
            if live is not None:
                live()  # its profile and account still: nothing kept is shown past them
            data = self._tools[name](args)
        except (ToolError, Unavailable, E.Refused) as e:
            return {"content": [{"type": "text", "text": str(e)}], "isError": True}
        except Exception as e:  # noqa: BLE001
            words = ("Due Crew couldn't be reached. Try again in a minute." if type(e).__name__ == "TransportError"
                     else "That didn't work in Anki. Try again.")
            if type(e).__name__ != "TransportError":
                print(f"due crew: the AI app's {name}: {type(e).__name__}")
            return {"content": [{"type": "text", "text": words}], "isError": True}
        return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, indent=1)}],
                "structuredContent": data, "isError": False}

    # ---- what the host has, kept a moment ----

    def _kept(self, key, fn):
        if self.cache_secs:
            with self._lock:
                hit = self._cache.get(key)
            if hit and time.monotonic() - hit[0] < self.cache_secs:
                return hit[1]
        v = fn()
        with self._lock:
            self._cache[key] = (time.monotonic(), v)
        return v

    def _plans(self):
        return [p for p in self._kept("plans", self.host.plans) or [] if isinstance(p, dict) and p.get("id")]

    def _find(self, args):
        ref = str(args.get("plan") or "").strip()
        if not ref:
            raise ToolError("Which plan? list_plans names them.")
        plans = self._plans()
        hit = [p for p in plans if str(p["id"]) == ref]
        hit = hit or [p for p in plans if " ".join(str(p.get("name") or "").lower().split()) == " ".join(ref.lower().split())]
        if len(hit) == 1:
            return hit[0]
        if hit:
            raise ToolError(f"{len(hit)} of your plans are called {ref}: name it by its id.")
        raise ToolError(f"No plan of yours is {ref}. list_plans names them.")

    def _raw(self, p):
        """(raw, doc, author): the plan as the server has it (GET /plans/{id}),
        its doc as the builder loads it, and whether I write it."""
        pid = str(p["id"])
        raw = self._kept(("plan", pid), lambda: self.host.plan(pid))
        if not isinstance(raw, dict) or not isinstance(raw.get("doc"), dict):
            raise ToolError("That plan didn't load.")
        role = raw.get("role") or p.get("role")
        return raw, E.migrate_checks(raw["doc"]), role in ("owner", "editor")

    def _ctx(self, pid, raw, doc):
        days = (doc.get("pace") or {}).get("days") if isinstance(doc.get("pace"), dict) else None
        return O.Ctx(self.host.tree(pid), self.host.today(), raw.get("name") or "", days)

    def _draft(self, pid, raw, doc):
        """The changes waiting on it here, on the plan as the server has it now (a co-author's save since: rebased)."""
        d = self.host.draft(pid)
        if d is None:
            return D.Draft(pid, doc, raw.get("version"))
        if d.version != raw.get("version"):
            d.rebase(doc, raw.get("version"))
        return d

    def _plan_lock(self, pid):
        with self._lock:
            return self._plan_locks.setdefault(pid, threading.Lock())

    # ---- the tools ----

    def _list_plans(self, args):
        mine, follow = [], []
        for p in self._plans():
            if p.get("role") in ("owner", "editor"):
                mine.append({"id": p["id"], "name": p.get("name") or "Plan", "role": p["role"],
                             "followers": int(p.get("followers") or 0)})
            else:
                follow.append({"id": p["id"], "name": p.get("name") or "Plan"})
        return {"authored": mine, "following": follow}

    def _read_plan(self, args):
        p = self._find(args)
        pid = str(p["id"])
        raw, doc, author = self._raw(p)
        ctx = self._ctx(pid, raw, doc)
        waiting, dropped = [], []
        if author:
            d = self.host.draft(pid)
            if d is not None and len(d):
                if d.version != raw.get("version"):
                    d.rebase(doc, raw.get("version"))
                doc, changes, gone = d.replay(ctx)
                waiting = [_words(x) for c in changes for x in c["entries"]]
                dropped = [{"op": o, "why": w} for o, w in gone]
        tree = ctx.tree
        placed = B.placed_keys(doc, tree) if tree is not None else None
        evs = {e["id"]: e for e in ai._events(doc)}
        dates = []
        for u in sorted(P.units(doc), key=lambda u: str(u.get("opens") or "")):
            ev = evs.get(u.get("for"))
            x = {"id": u["id"], "day": u.get("opens"), "name": u.get("name") or "", "cards": ai.date_cards(u, tree, placed),
                 "sources": ai.sources(u, doc),
                 "tested_on": {"id": ev["id"], "day": ev.get("day"), "name": ev.get("name")} if ev else None}
            if u.get("due"):
                x["due"] = u["due"]
            if u.get("even"):
                x["even"] = True
            dates.append(x)
        out = {"id": pid, "name": raw.get("name") or p.get("name") or "Plan", "role": raw.get("role") or p.get("role"),
               "version": raw.get("version"), "deck": doc.get("deck") or "",
               "deck_here": tree is not None, "text": T.to_text(doc), "dates": dates,
               "events": [{"id": e["id"], "day": e.get("day"), "name": e.get("name") or ""} for e in ai._events(doc)],
               "plan_tags": [{"id": t["id"], "name": t.get("name") or ""} for t in P.plan_tags(doc)],
               "waiting": waiting}
        if dropped:
            out["dropped"] = dropped
        n = len(waiting)
        out["note"] = (f"The plan with the {n:,} change{'s' if n != 1 else ''} waiting under it, not sent. {SEND}" if waiting
                       else "The plan as Due Crew has it." if author
                       else "You follow this plan: only its authors change it.")
        return out

    def _deck_tags(self, args):
        p = self._find(args)
        pid = str(p["id"])
        raw, doc, _author = self._raw(p)
        tree = self.host.tree(pid)
        if tree is None:
            raise ToolError(f"The plan's deck ({doc.get('deck') or '?'}) isn't in this Anki.")
        try:
            limit = max(1, min(TAGS_MAX, int(args.get("limit") or 200)))
        except (TypeError, ValueError):
            limit = 200
        under = str(args.get("under") or "").strip()
        if under and not under.startswith(("tag:", "deck:")):
            under = f"tag:{under}" if tree.has(f"tag:{under}") else f"deck:{under}"
        find = [w for w in str(args.get("find") or "").lower().split() if w]
        rows = []
        for k, n in ai.deck_rows(tree):
            if under and not B.under(under, k):
                continue
            low = B.path_of(k).lower()
            if find and not all(w in low or w in B.tag_name(B.path_of(k)).lower() for w in find):
                continue
            rows.append({"path": k, "cards": n, "name": B.tag_name(B.path_of(k))})
        return {"deck": doc.get("deck") or "", "tags": rows[:limit], "more": max(0, len(rows) - limit)}

    def _vocabulary(self, args):
        return {"ops": ai.vocabulary(for_ai=True),
                "dates": "Name a date by its id (read_plan), its day, its name, or \"YYYY-MM-DD name\"; "
                         "a quiz or exam the same way.",
                "note": "Changes go under the plan as changes waiting; the author sends them in Anki."}

    def _preview(self, args):
        p = self._find(args)
        pid = str(p["id"])
        ops_in = _ops_arg(args.get("ops"))
        raw, doc, author = self._raw(p)
        ctx = self._ctx(pid, raw, doc)
        if author:
            doc = self._draft(pid, raw, doc).doc(ctx)
        kept, refused, _after = ai.try_ops(ops_in, doc, ctx)
        return {"changes": [{"op": o, "entries": [_words(x) for x in entries]} for o, entries in kept],
                "refused": [{"op": o, "why": w} for o, w in refused],
                "note": "Nothing changed." + ("" if author else " You follow this plan: only its authors change it.")}

    def _add(self, args):
        p = self._find(args)
        pid = str(p["id"])
        ops_in = _ops_arg(args.get("ops"))
        why = " ".join(str(args.get("why") or "").split())[:O.WHY_MAX]
        raw, doc, author = self._raw(p)
        if not author:
            raise ToolError("You follow this plan: only its authors change it.")
        ctx = self._ctx(pid, raw, doc)
        with self._plan_lock(pid):
            for _try in range(3):
                d = self._draft(pid, raw, doc)
                added, refused = [], []
                for x in ops_in:
                    o, words = ai.clean_op(x)
                    if o is None:
                        refused.append({"op": x, "why": words})
                        continue
                    o["by"] = "ai"  # who asked: shown with the change, never sent (the server sees only the plan)
                    if why:
                        o["why"] = why
                    try:
                        entries, _touched = d.add(o, ctx)
                    except E.Refused as e:
                        refused.append({"op": o, "why": str(e)})
                        continue
                    except Exception:  # noqa: BLE001 - fields its kind doesn't take
                        refused.append({"op": o, "why": "That change doesn't fit this plan."})
                        continue
                    for e_ in entries:
                        e_["who"] = O.who(e_, ctx.today)
                    added.append({"op": d.ops[-1], "entries": [_words(e_) for e_ in entries]})
                if not added:
                    break
                if self.host.keep_draft(pid, d) is not False:
                    self.host.changed(pid)
                    break
            else:
                raise ToolError("The plan's changes kept changing in Anki meanwhile. Try again.")
        return {"added": added, "refused": refused, "waiting": len(d),
                "note": (f"{len(added):,} change{'s' if len(added) != 1 else ''} waiting to be sent, "
                         f"{len(d):,} in all. {SEND}") if added else "Nothing was added."}


class _HTTPServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = sys.platform != "win32"  # Windows lets a second program take a reused port
    mcp = None

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)  # never a reverse lookup of 127.0.0.1 (slow on some Macs)
        self.server_name, self.server_port = "127.0.0.1", self.server_address[1]


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "DueCrew"
    sys_version = ""
    timeout = 60  # an idle connection let go

    def log_message(self, *args):
        pass  # nothing logged: not a path, not a header, not a body

    def _send(self, code, body=None, headers=()):
        data = b"" if body is None else json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(code)
        if body is not None:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        if data:
            self.wfile.write(data)

    def _turned_away(self):
        """(status, words) for a request that isn't for this server from this computer, else None."""
        port = self.server.mcp.port
        host = (self.headers.get("Host") or "").strip().lower()
        if host not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            return 403, "That isn't this computer's address."
        if not local_origin(self.headers.get("Origin")):
            return 403, "Only an app on this computer talks to it."
        auth = str(self.headers.get("Authorization") or "")
        given = auth[7:].strip() if auth[:7].lower() == "bearer " else ""
        if not given or not hmac.compare_digest(given.encode("utf-8"), self.server.mcp.token.encode("utf-8")):
            return 401, "The token doesn't match. Copy the setup again from Anki (Your AI app)."
        return None

    def _path(self):
        return self.path.split("?", 1)[0]

    def do_POST(self):
        if self._path() != "/mcp":
            self.close_connection = True
            return self._send(404, _err(None, -32600, "Not here: /mcp."))
        away = self._turned_away()
        if away:
            self.close_connection = True
            code, words = away
            return self._send(code, _err(None, -32001, words), [("WWW-Authenticate", 'Bearer realm="due-crew"')] if code == 401 else ())
        try:
            n = int(self.headers.get("Content-Length") or "")
        except ValueError:
            self.close_connection = True
            return self._send(411, _err(None, -32600, "It needs a Content-Length."))
        if n < 0 or n > BODY_MAX:
            self.close_connection = True
            return self._send(413, _err(None, -32600, "That's more than 1 MB."))
        try:
            msg = json.loads(self.rfile.read(n).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return self._send(400, _err(None, -32700, "That isn't JSON."))
        out = self.server.mcp.handle(msg)
        if out is None:
            return self._send(202)
        self._send(200, out)

    def do_GET(self):
        self.close_connection = True
        if self._path() != "/mcp":
            return self._send(404, _err(None, -32600, "Not here: /mcp."))
        self._send(405, _err(None, -32601, "POST only: this server sends no stream."), [("Allow", "POST")])

    do_PUT = do_PATCH = do_DELETE = do_GET
