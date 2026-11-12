"""What the robot sees: every message a page sends and whether a handler
ran for it, everything that raised, every window that opened, every link
that would have left Anki, and every attempt at the network. Installed
around Anki and the add-on without changing either: hooks, wrappers, a
profiler for the length of one command.

A handler ran when, while Anki handled the message, the add-on ran code of
its own beyond the code that only routes it (the hook, the command table's
lookup and checks, a family's dispatcher before it picks a branch). A
command the table hasn't got, or a family's name its module doesn't know,
runs only routing code: no handler."""

import os
import socket
import sys
import time
import traceback

LOOPBACK = ("127.0.0.1", "::1", "localhost", "0.0.0.0")


def _rel(path):
    i = path.find("due_crew" + os.sep)
    return path[i:] if i >= 0 else os.path.basename(path)


class Probe:
    def __init__(self):
        self.t0 = time.perf_counter()
        self.step = "start"           # what the robot is doing, for whatever happens now
        self.messages = []            # every page message: {at, step, ctx, msg, handled, handler, raised, secs}
        self.plan_messages = []       # the plan window's ("dcplan:"): {at, step, msg, name, handled}
        self.errors = []              # {at, step, kind, text}
        self.windows = []             # {at, step, kind, title}
        self.tooltips = []            # {at, step, text}
        self.links = []               # {at, step, url}
        self.network = []             # {at, step, host}
        self.js_errors = []           # {at, step, src, line, text, view}
        self.states = []              # {at, step, new, old}: Anki's screens, in turn
        self.print_exc = 0
        self.threads = []             # the add-on's own background threads
        self.futures = []             # Anki's background ops (taskman.run_in_background), the add-on's and its own
        self._busy = 0                # a message being handled now (and how deep)
        self.routing = set()
        self.deep = set()
        self.root = None

    def now(self):
        return round(time.perf_counter() - self.t0, 3)

    def note(self, into, **kw):
        getattr(self, into).append(dict(kw, at=self.now(), step=self.step))

    # ---- before Anki: the network, and Chromium's ----
    def guard_network(self):
        """No connection leaves this machine. The add-on's API is the fake
        in this process; anything else that tries is refused and noted."""
        probe = self
        real_connect = socket.socket.connect
        real_connect_ex = socket.socket.connect_ex

        def host_of(addr):
            return addr[0] if isinstance(addr, tuple) and addr else None

        def ok(addr):
            h = host_of(addr)
            return h is None or str(h) in LOOPBACK or str(h).startswith("127.")

        def connect(sock, addr):
            if not ok(addr):
                probe.note("network", host=str(host_of(addr)))
                raise ConnectionRefusedError(f"the click test allows no network ({host_of(addr)})")
            return real_connect(sock, addr)

        def connect_ex(sock, addr):
            if not ok(addr):
                probe.note("network", host=str(host_of(addr)))
                return 111
            return real_connect_ex(sock, addr)
        socket.socket.connect = connect
        socket.socket.connect_ex = connect_ex
        # QtWebEngine: everything but this machine goes to a proxy that isn't there
        flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
        if "--proxy-server" not in flags:
            os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (flags + " --proxy-server=http://127.0.0.1:9").strip()

    # ---- once aqt is imported, before Anki runs ----
    def patch_anki(self):
        import aqt.errors
        import aqt.main
        import aqt.utils
        import aqt.webview
        from aqt.qt import QDesktopServices
        probe = self

        # stderr: Anki shows anything written there in its error window; here it's noted, no window
        real_write = aqt.errors.ErrorHandler.write

        def write(handler, data):
            if data and data.strip():
                probe._stderr(data)
            return real_write(handler, data)

        def on_timeout(handler):
            handler.pool = ""
        aqt.errors.ErrorHandler.write = write
        aqt.errors.ErrorHandler.onTimeout = on_timeout

        real_print_exc = traceback.print_exc

        def print_exc(*a, **k):
            probe.print_exc += 1
            return real_print_exc(*a, **k)
        traceback.print_exc = print_exc

        real_hook = sys.excepthook

        def excepthook(etype, value, tb):
            probe.note("errors", kind="uncaught", text="".join(traceback.format_exception(etype, value, tb))[-4000:])
            if real_hook is not None:
                real_hook(etype, value, tb)
        sys.excepthook = excepthook

        # nothing leaves Anki: links and folders are noted, not opened
        def open_link(link, *a, **k):
            probe.note("links", url=str(link))

        def open_url(url, *a, **k):
            probe.note("links", url=url.toString() if hasattr(url, "toString") else str(url))
            return True
        aqt.utils.openLink = open_link
        aqt.utils.openFolder = open_link
        if hasattr(aqt.webview, "openLink"):
            aqt.webview.openLink = open_link
        QDesktopServices.openUrl = staticmethod(open_url)

        real_tooltip = aqt.utils.tooltip

        def tooltip(msg, *a, **k):
            probe.note("tooltips", text=str(msg)[:200])
            return real_tooltip(msg, *a, **k)
        aqt.utils.tooltip = tooltip

        # Anki's own update checks ask AnkiWeb: not here
        aqt.main.AnkiQt.maybe_check_for_addon_updates = lambda mw, on_done=None: on_done([]) if on_done else None
        aqt.main.AnkiQt.setup_auto_update = lambda mw, _log=None: None

        # the pages' console errors (Anki prints them to stdout)
        real_console = aqt.webview.AnkiWebPage.javaScriptConsoleMessage

        def console(page, level, msg, line, src):
            from aqt.qt import QWebEnginePage
            if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
                try:
                    from aqt.qt import QWebEngineView
                    view = QWebEngineView.forPage(page)
                    title = str(getattr(view, "title", "") or type(view).__name__)
                except Exception:
                    title = "?"
                probe.note("js_errors", src=str(src or "")[-80:], line=line, text=str(msg)[:400], view=title)
            return real_console(page, level, msg, line, src)
        aqt.webview.AnkiWebPage.javaScriptConsoleMessage = console

        # the add-on's background threads, to know when it has settled
        import threading
        real_start = threading.Thread.start

        def start(th):
            target = getattr(th, "_target", None)
            if target is not None and str(getattr(target, "__module__", "")).startswith("due_crew"):
                probe.threads.append(th)
            return real_start(th)
        threading.Thread.start = start

        import aqt.taskman
        real_bg = aqt.taskman.TaskManager.run_in_background

        def run_in_background(tm, *a, **k):
            fut = real_bg(tm, *a, **k)
            probe.futures.append(fut)
            return fut
        aqt.taskman.TaskManager.run_in_background = run_in_background

    def _stderr(self, data):
        text = str(data)
        if "DeprecationWarning" in text and "Traceback" not in text:
            return
        last = self.errors[-1] if self.errors else None
        if last and last["kind"] == "uncaught" and self.now() - last["at"] < 0.5:
            return  # the excepthook's own copy (Anki's hook writes it to stderr)
        if last and last["kind"] == "stderr" and last["step"] == self.step and self.now() - last["at"] < 0.5:
            last["text"] = (last["text"] + text)[-6000:]  # one traceback comes in many writes
            return
        self.note("errors", kind="stderr", text=text[-6000:])

    # ---- once the add-on has loaded ----
    def watch_addon(self, dc):
        """The add-on's message hook, wrapped; its routing code, listed."""
        from aqt import gui_hooks
        import importlib
        self.root = os.path.dirname(dc.__file__) + os.sep
        hooks = gui_hooks.webview_did_receive_js_message._hooks
        i = hooks.index(dc._on_js)
        real = hooks[i]
        probe = self

        def on_js(handled, message, context):
            return probe._handle(real, handled, message, context)
        hooks[i] = on_js
        gui_hooks.state_did_change.append(lambda new, old: probe.note("states", new=new, old=old))
        mods = {n: importlib.import_module("due_crew." + n) for n in (
            "app", "plan_flow", "due_flow", "team_flow", "song_flow", "gamenight_flow", "rooms",
            "room_model", "settings_model", "cards")}
        shallow = [dc._on_js, dc._board_cmd, dc._team, dc._song, dc._settings_family, dc._settings_cmd,
                   dc._closet_cmd, dc._scrap_cmd, mods["plan_flow"].on_message, mods["due_flow"].on_message,
                   mods["team_flow"].on_message, mods["song_flow"].on_message, mods["gamenight_flow"].on_message,
                   mods["rooms"].on_message, mods["cards"].on_message]
        shallow += [run for _start, run in dc._FAMILIES]
        sheets = importlib.import_module("due_crew.sheets")
        shallow += [dc.BOARD_CMDS["party"][2], dc.BOARD_CMDS["sheet"][2], sheets.answer]
        deep = [mods["app"].cfg, mods["room_model"].trusted, mods["rooms"].swallow, mods["settings_model"].change,
                mods["gamenight_flow"]._state, mods["gamenight_flow"].level, mods["gamenight_flow"]._keep_state]
        deep += [ok for _need, ok, _run in dc.BOARD_CMDS.values() if ok is not None]
        if hasattr(dc, "_our_page"):
            deep.append(dc._our_page)
        self.routing = set()
        for fn in shallow:
            self.routing |= _codes(fn.__code__)
        self.deep = {fn.__code__ for fn in deep}

    def watch_plan_window(self):
        """The plan window's page messages ("dcplan:" + JSON), and whether
        its face has the command they name (webface._on_cmd's own lookup)."""
        import importlib
        import json
        wf = importlib.import_module("due_crew.planner.webface")
        real = wf.WebFace._on_cmd
        probe = self

        def on_cmd(face, msg):
            rec = {"msg": str(msg)[:300], "name": "", "handled": False}
            try:
                data = json.loads(str(msg)[len(wf.PREFIX):])
                name = str(data.get("c") or "") if isinstance(data, dict) else ""
            except ValueError:
                name = ""
            rec["name"] = name
            blocked = face.new is not None and name not in wf.NEW_CMDS
            fn = getattr(face, "c_" + name, None) if name.replace("_", "").isalnum() else None
            rec["handled"] = bool(fn) and not blocked
            if blocked:
                rec["why"] = "New plan's screen takes only its own commands"
            probe.note("plan_messages", **rec)
            return real(face, msg)
        wf.WebFace._on_cmd = on_cmd

    def _handle(self, real, handled, message, context):
        msg = str(message)
        ours = msg.startswith("duecrew:")
        rec = {"msg": clean(msg), "ctx": type(context).__name__, "handled": None, "handler": None, "raised": None}
        if ours:
            self.note("messages", **rec)
            rec = self.messages[-1]
        t = time.perf_counter()
        self._busy += 1
        tracer = _Tracer(self.root, self.routing, self.deep) if ours else None
        try:
            if tracer:
                tracer.start()
            try:
                return real(handled, message, context)
            finally:
                if tracer:
                    tracer.stop()
        except Exception:
            if ours:
                rec["raised"] = traceback.format_exc()[-3000:]
            raise
        finally:
            self._busy -= 1
            if ours:
                rec["handled"] = tracer.hit is not None
                rec["handler"] = tracer.hit
                rec["secs"] = round(time.perf_counter() - t, 3)

    # ---- the robot asks ----
    def handling(self):
        """A message is being handled now (a window it opened may be waiting)."""
        return self._busy > 0

    def settled(self, mw):
        """Nothing is running: no message being handled, no background job
        (the add-on's threads, Anki's ops), nothing waiting for the main thread."""
        if self._busy:
            return False
        self.threads = [t for t in self.threads if t.is_alive()]
        self.futures = [f for f in self.futures if not f.done()]
        if self.threads or self.futures:
            return False
        tm = getattr(mw, "taskman", None)
        return not (tm is not None and getattr(tm, "_closures", None))


def _codes(code):
    """A function's code and every code nested in it (its comprehensions, lambdas)."""
    out = {code}
    for c in code.co_consts:
        if hasattr(c, "co_code"):
            out |= _codes(c)
    return out


def clean(msg):
    """A message as kept in the report: the page's key (a per-run random
    token that only proves the board sent it) is shown as KEY."""
    body, sep, key = msg.rpartition("|")
    if sep and len(key) >= 12 and key.isalnum():
        return body + "|KEY"
    return msg[:500]


class _Tracer:
    """For one command: the first function of the add-on's own that isn't
    routing. Stops profiling as soon as it finds one."""

    def __init__(self, root, routing, deep):
        self.root, self.routing, self.deep = root, routing, deep
        self.hit = None
        self.inside = []  # frames of deep routing code: whatever they call is routing too
        self.prev = None

    def start(self):
        self.prev = sys.getprofile()
        sys.setprofile(self._profile)

    def stop(self):
        if sys.getprofile() == self._profile:
            sys.setprofile(self.prev)

    def _profile(self, frame, event, arg):
        if event == "return":
            if self.inside and self.inside[-1] is frame:
                self.inside.pop()
            return
        if event != "call":
            return
        co = frame.f_code
        if self.inside:
            return
        if co in self.deep:
            self.inside.append(frame)
            return
        if co in self.routing or not self.root or not co.co_filename.startswith(self.root):
            return
        self.hit = f"{co.co_name} ({_rel(co.co_filename)}:{co.co_firstlineno})"
        sys.setprofile(self.prev)
