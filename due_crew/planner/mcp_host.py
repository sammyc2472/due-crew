"""Your AI app's glue (mcp.py, docs/planner.md): the local MCP server's host
in Anki, its switch in this computer's config ("mcp": {"on", "port",
"token"}; never sent, never an account key), and the server on with a
profile open and signed in, off at profile close, sign-out and sign-in
(app._reset_runtime and __init__'s profile close call follow() and stop()).

The server's threads call the host. A request (my plans, a plan) goes out
from there, as any request goes in the background; the collection, the
config and the drafts (plan_drafts.json) are read and written on Anki's
main thread, the caller waiting a while. Each host belongs to one
app.generation: once the profile or the account changes, it does nothing
more (the next one is started for the new one)."""

import json
import secrets
import threading
import time
import traceback

from aqt import mw

from .. import app, plan_flow
from . import build as B
from . import flow, mcp, remote

KEY = "mcp"
MAIN_WAIT = 30      # seconds a tool waits for Anki's main thread
TREE_SECS = 300     # a deck's tags read again after this (a big deck's are seconds of work)

_server = [None]    # the one running, or None
_said = [""]        # why it isn't on, when the switch says it should be


# ---- the switch: this computer's config ----

def settings(c=None):
    """{on, port, token}: this computer's switch. Main thread."""
    c = app.cfg() if c is None else c
    m = c.get(KEY) if isinstance(c.get(KEY), dict) else {}
    port = m.get("port")
    port = port if isinstance(port, int) and not isinstance(port, bool) and 0 <= port <= 65535 else 0
    return {"on": m.get("on") is True, "port": port, "token": str(m.get("token") or "")}


def _keep(m):
    c = app.cfg()
    c[KEY] = {"on": bool(m["on"]), "port": int(m["port"]), "token": str(m["token"])}
    app.save_cfg(c)


def running():
    srv = _server[0]
    return srv if srv is not None and srv.port else None


def follow():
    """The server as the switch says, with a profile open and signed in; off
    otherwise. Started again for this profile and account (main thread)."""
    stop()
    m = settings()
    _said[0] = ""
    if not m["on"] or not m["token"]:
        return None
    if not app.client().signed_in:
        _said[0] = "It starts once you're signed in to Due Crew."
        return None
    return _start(m)


def _start(m):
    host = Host(app.generation)
    for port in ([m["port"], 0] if m["port"] else [0]):
        try:
            srv = mcp.Server(host, m["token"], port).start()
        except OSError:
            continue  # its port is another program's now: any free one, kept, and the setup copied again
        _server[0] = srv
        if srv.port != m["port"]:
            _keep(dict(m, port=srv.port))  # the address stays the same from now on, so the AI app's setup does
        return srv
    _said[0] = "It couldn't start: no port on this computer was free."
    return None


def stop():
    srv, _server[0] = _server[0], None
    if srv is not None:
        try:
            srv.stop()
        except Exception:
            traceback.print_exc()


def set_on(on):
    """The window's switch: on (a token made the first time) or off. Main thread."""
    m = settings()
    m["on"] = bool(on)
    if m["on"] and not m["token"]:
        m["token"] = secrets.token_urlsafe(24)
    _keep(m)
    if m["on"]:
        follow()
    else:
        stop()
        _said[0] = ""
    return state()


def new_token():
    """New token: the old one stops working at once (the AI app's setup is copied again)."""
    m = settings()
    m["token"] = secrets.token_urlsafe(24)
    _keep(m)
    if m["on"]:
        follow()
    return state()


def state():
    """What the window shows: {on, running, port, url, token, said}."""
    m = settings()
    srv = running()
    return {"on": m["on"], "running": srv is not None, "port": srv.port if srv else m["port"],
            "url": srv.url if srv else "", "token": m["token"], "said": _said[0]}


def shim_path():
    """The stdio shim in this add-on (planner/mcp_shim.py; tools/due_crew_mcp.py is its twin)."""
    import os
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_shim.py")


class DialogOps:
    """What the Your AI app window asks (a render hands it its own)."""

    state = staticmethod(state)
    set_on = staticmethod(set_on)
    new_token = staticmethod(new_token)

    def setup(self, http=False):
        s = state()
        return mcp.setup(s["port"], s["token"], shim_path(), http=http)


# ---- the host: what the server asks of Anki ----

def _sig(d):
    return json.dumps(d.to_json(), sort_keys=True) if d is not None else None


class Host:
    """mcp.Server's host for one profile and account (app.generation)."""

    def __init__(self, gen):
        self.gen = gen
        self._docs = {}    # pid -> the doc last read (tree() reads its deck)
        self._trees = {}   # pid -> (when, deck, Tree or None)
        self._seen = {}    # pid -> the draft as last handed out (keep_draft keeps only over that one)

    def _live(self):
        if app.generation != self.gen:
            raise mcp.Unavailable("Anki changed profile or account. Try again.")

    live = _live  # mcp.Server asks before each tool

    def _main(self, fn, timeout=MAIN_WAIT):
        """fn() on Anki's main thread, this thread waiting for it; Unavailable
        when Anki is too busy to get to it (then it never runs)."""
        if threading.current_thread() is threading.main_thread():
            return fn()
        box, lock, done = {"state": "waiting"}, threading.Lock(), threading.Event()

        def run():
            with lock:
                if box["state"] != "waiting":
                    return
                box["state"] = "running"
            try:
                box["value"] = fn()
            except BaseException as e:  # noqa: BLE001 - handed back to the waiting thread
                box["error"] = e
            finally:
                done.set()
        mw.taskman.run_on_main(run)
        if not done.wait(timeout):
            with lock:
                if box["state"] == "waiting":
                    box["state"] = "gone"
                    raise mcp.Unavailable("Anki is busy. Try again in a moment.")
            done.wait()  # it had started: its end is near
        if "error" in box:
            raise box["error"]
        return box.get("value")

    def _client(self):
        self._live()
        cl = app.client()
        if not cl.signed_in:
            raise mcp.Unavailable("Sign in to Due Crew in Anki first.")
        return cl

    def plans(self):
        cl = self._main(self._client)
        got = remote.my_plans(cl)  # GET /plans/mine, here in the server's thread
        self._live()
        return got

    def plan(self, pid):
        cl = self._main(self._client)
        raw, _plan = remote.load(cl, pid)  # GET /plans/{id}
        self._live()
        if isinstance(raw.get("doc"), dict):
            self._docs[str(pid)] = raw["doc"]
        return raw

    def tree(self, pid):
        """The plan's deck here as the builder reads it (build.Tree), or None:
        the deck read on the main thread, its tags counted here."""
        pid = str(pid)
        doc = self._docs.get(pid)
        if doc is None:
            doc = self.plan(pid).get("doc") or {}
        deck = str(doc.get("deck") or "")
        hit = self._trees.get(pid)
        if hit and hit[1] == deck and time.monotonic() - hit[0] < TREE_SECS:
            return hit[2]

        def index():
            self._live()
            if not mw.col:
                return None
            return flow.Ops().context({"id": pid}, doc)[0]
        idx = self._main(index)
        tree = None
        if idx is not None:
            tags, decks = idx.tree()  # in memory: never on the main thread
            tree = B.Tree(tags, decks)
        self._trees[pid] = (time.monotonic(), deck, tree)
        return tree

    def today(self):
        def run():
            self._live()
            return plan_flow._today()
        return self._main(run)

    def draft(self, pid):
        def run():
            self._live()
            d = flow.Ops().draft(pid)
            self._seen[str(pid)] = _sig(d)
            return d
        return self._main(run)

    def keep_draft(self, pid, draft):
        """Kept over the draft as it was handed out; False when it changed in
        Anki meanwhile (Your plans' own change): the server reads it again."""
        def run():
            self._live()
            ops = flow.Ops()
            if _sig(ops.draft(pid)) != self._seen.get(str(pid)):
                return False
            ops.keep_draft(pid, draft)
            self._seen[str(pid)] = _sig(draft if draft is not None and len(draft) else None)
            return True
        return self._main(run)

    def changed(self, pid):
        """An open Your plans hears of it (draft_changed), on the main thread; nobody waits."""
        def run():
            if app.generation != self.gen:
                return
            w = flow._open.get("plans")
            if w is not None and getattr(w, "_alive", False) and hasattr(w, "draft_changed"):
                try:
                    w.draft_changed(pid)
                except Exception:
                    traceback.print_exc()
        mw.taskman.run_on_main(run)


def show(parent=None):
    """The Your AI app window (mcp_dialog.show)."""
    from . import mcp_dialog
    return mcp_dialog.show(parent)
