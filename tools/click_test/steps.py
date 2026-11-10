"""The scenario: what the robot does, in order, and what it writes down.

    boot     the Decks screen, the board, signed in with a crew; Magic search's
             how-to, which comes over the board once
    plans    Tools › Due Crew › Plans › Your plans…: New plan › Start empty,
             Start it, a set (saved at once); a crewmate follows; another set,
             Review and send › Send; the fake server has both
    due      two things added in the You box (one for later, one tomorrow)
    windows  the board's windows (dcPop): the Cheer window (Esc, Send, the grey
             top bar), a crewmate's card, a sheet (Esc, then its yes)
    views    each view and tab, and in each every control that sends a
             duecrew: command, pressed (the sweep); Magic search's window
    bars     the top bar's widget (▶ Fifteen? and the chip it becomes)
    study    a deck, Study Now, the first card timed, five answered, then the
             board's clicks after a review
    energy   back on the Decks screen, CPU at rest for a minute

Each part records its own failures and the next one goes on; the report
(report.py) says what failed and the exit code follows."""

import json
import os
import time

from . import pagejs
from .probe import clean
from .robot import BLOCKED, Robot, Timeout

FIRST_CARD_MAX_S = 3.0
BOARD_MAX_S = 4.0  # the Decks screen to the board with its crew, on the fake server (a warning: not measured before 3.9.9)
# CPU at rest, % of one core, from REST_FROM_S after the last input: the page rests at 12 s (sev.REST_JS) and
# its loops play their round out by about 20. Measured on the code of 8 Nov 2026 (3.9.8, a 4-core container):
# 0.1-0.2% from 20 s on (about 30% awake, about 10% from 15 to 20 s); a page that never rests stays near 30%.
# Five leaves room for a slower machine, not for a loop.
CPU_REST_MAX = 5.0
REST_FROM_S = 20.0
REST_STATE = ("JSON.stringify({hidden: document.hidden, focus: document.hasFocus(), "
              "rest: !!(window.dcRest && dcRest.resting())})")
PRESS_SECS = 12.0

# controls the sweep never presses, and why (a press would leave Anki, need
# the real network, or end the run's account): by a command's name, or the whole command
SKIP = {
    "party:host": "hosts a table: the TV window plays duecrew.com/t/CODE, which needs the network for real",
    "privacypage": "opens duecrew.com's privacy page in the browser: leaves Anki",
    "noticeopen": "opens the admin notice's link in the browser: leaves Anki",
    "duelink": "opens a to-do's link in the browser: leaves Anki",
    "songlisten": "Listen opens a music app or its site: leaves Anki",
    "songapple": "opens the song on its music service's site: leaves Anki",
    "plansync": "Anki's own sync with AnkiWeb: needs the network for real",
    "setsignout": "signs out: the rest of the run needs the account",
    "setdelete": "deletes the account: the rest of the run needs it",
}

# a command repeated once per row (a crewmate, a deck, a thing in the closet):
# its first few are pressed, the rest are the same wiring
REPEATS = {"profile": 2, "cheerpick": 2, "rowmenu": 2, "heatday": 2, "ecard": 2, "closetwear": 3,
           "duetick": 2, "dueitem": 2, "duedo": 2, "duex": 2, "squadkick": 1, "squadblock": 1,
           "squadfounder": 1, "knock": 1, "addback": 1, "cheerback": 2, "insdeck": 2, "insmap": 2,
           "insmapup": 2, "insmapby": 2, "insstudy": 2, "insbrowse": 2, "plantopic": 2, "plantopicstudy": 2,
           "planbrowse": 2, "plannow": 2, "closettab": 4}

# the views, each reached from the board by pressing these in turn
VIEWS = (
    ("Crew · Today", ("period:today",)),
    ("Crew · Week", ("period:week",)),
    ("Crew · Decks", ("period:decks",)),
    ("Squads", ("period:squads",)),
    ("You · Today", ("duetab:today",)),
    ("You · Upcoming", ("duetab:upcoming",)),
    ("You · Later", ("duetab:later",)),
    ("You · Plans", ("duetab:plans",)),
    ("You · Insights", ("duetab:insights",)),
    ("Pip Party", ("duetab:party",)),
    ("Settings · You", ("settings",)),
    ("Settings · Board", ("settings", "settab:board")),
    ("Settings · Privacy", ("settings", "settab:privacy")),
    ("Pip's closet", ("closet",)),
)

NAV = {cmd for _name, path in VIEWS for cmd in path}  # pressed on the way to each view, not in the sweep
VIEW_CFG = ("period", "crew_view", "due_tab", "due_fold", "show_leaderboard", "hidden_tabs")
VIEW_STATE = ("settings_tab", "closet_open", "wrapped_open", "bingo_open", "team_bingo_open")


def _name(cmd):
    return cmd.split(":")[0]


class Run:
    def __init__(self, probe, world, out, args, built):
        self.probe, self.world, self.out, self.args, self.built = probe, world, out, args, built
        self.parts = {}        # part -> {ok, secs, notes}
        self.presses = []      # every press of the sweep (and the views' tabs)
        self.skipped = {}      # key -> reason
        self.views = []        # {name, ok, shot, controls}
        self.windows = []      # the dcPop checks
        self.checks = []       # {name, ok, detail}: the scripted checks (plans, windows, study)
        self.timings = {}
        self.cpu = {}
        self.shots = []
        self.pressed = set()
        self.per_name = {}
        self.pointer = None    # where the robot's pointer last rested over the board (CSS px)
        self.only = set(x for x in (args.only or "").split(",") if x)

    # ---- the driver ----
    def start(self, finished):
        from aqt.qt import QTimer
        import aqt
        self.mw = aqt.mw
        self.finished = finished
        self.r = Robot(lambda ms, fn: QTimer.singleShot(ms, fn), lambda: finished({"done": True}),
                       lambda text: finished({"crash": text}))
        self.r.run(self.scenario())

    def scenario(self):
        yield from self.part("boot", self.boot)
        for name, fn in (("plans", self.plans), ("due", self.due_items), ("windows", self.dc_windows),
                         ("views", self.sweep_views), ("bars", self.top_bar), ("study", self.study),
                         ("energy", self.energy)):
            if not self.only or name in self.only:
                yield from self.part(name, fn)

    def part(self, name, fn):
        t = time.perf_counter()
        self.probe.step = name
        rec = self.parts[name] = {"ok": True, "secs": None, "notes": []}
        try:
            yield from fn()
        except Timeout as e:
            rec["ok"] = False
            rec["notes"].append(f"timed out: {e}")
            self.shot(f"fail-{name}")
        except Exception as e:  # the robot's own slip: noted, and the run goes on
            import traceback
            rec["ok"] = False
            rec["notes"].append(f"robot error: {type(e).__name__}: {e}\n{traceback.format_exc()[-2000:]}")
            self.shot(f"fail-{name}")
        rec["secs"] = round(time.perf_counter() - t, 1)
        # whatever a part left open goes before the next
        try:
            yield from self.tidy()
        except Exception:
            pass

    def check(self, name, ok, detail="", warn=False):
        """A scripted check. warn: reported, never the exit code (the exit is for a
        control that reaches no handler, anything raised, the first card, CPU at rest)."""
        self.checks.append({"name": name, "ok": bool(ok), "detail": str(detail)[:600], "step": self.probe.step,
                            "warn": warn})
        return ok

    def shot(self, name, web=None):
        """A picture of a web view (the main one unless given)."""
        try:
            path = os.path.join(self.out, "shots", "".join(c if c.isalnum() or c in "-_." else "-" for c in name) + ".png")
            (web or self.mw).grab().save(path)  # the main window: its bars with the board
            self.shots.append(os.path.relpath(path, self.out))
            return os.path.relpath(path, self.out)
        except Exception:
            return None

    def snap(self, name, web=None):
        """A picture once the page has painted what's on it (a web view's
        picture is its last frame: taken at once it can be the screen before)."""
        if web is None or _open(web):
            try:
                yield from self.painted(web)
                yield self.r.pause(60)
            except Timeout:
                pass
        return self.shot(name, web)

    # ---- small helpers ----
    @property
    def dc(self):
        import due_crew
        return due_crew

    def js(self, code, web=None, secs=10.0):
        return self.r.js(web or self.mw.web, code, secs)

    def helper(self, web=None):
        """The page's helper, installed (again, after a reload)."""
        got = yield self.js(pagejs.HELPER, web)
        return got

    def anki_idle(self):
        """Anki's three main web views have their pages and nothing waiting to run."""
        mw = self.mw
        for web in (mw.web, getattr(mw.toolbar, "web", None), getattr(mw, "bottomWeb", None)):
            if web is not None and (not getattr(web, "_domDone", True) or getattr(web, "_pendingActions", None)):
                return False
        return self.probe.settled(mw)

    def board_up(self):
        dc = self.dc
        return (self.mw.state == "deckBrowser" and dc.app.board_up() and dc._state.get("board_shown")
                and self.probe.settled(self.mw))

    def wait_board(self, what="the board"):
        yield self.r.until(self.board_up, 30, what)
        yield from self.helper()
        yield self.r.until(lambda: self.probe.settled(self.mw), 15, "the add-on to settle")
        yield from self.painted()

    def painted(self, web=None):
        """The page has painted twice since now (any page: no helper needed)."""
        yield self.js(pagejs.PAINT, web)
        for _ in range(50):
            got = yield self.js("window.__ctPainted === true", web)
            if got:
                return
            yield self.r.pause(20)

    def qt_open(self):
        """What Qt has open over Anki: a modal window, a popup menu, a window of its own."""
        from aqt.qt import QApplication
        out = []
        m = QApplication.activeModalWidget()
        if m is not None:
            out.append(("modal", m))
        p = QApplication.activePopupWidget()
        if p is not None:
            out.append(("popup", p))
        for w in QApplication.topLevelWidgets():
            if (w.isVisible() and w is not self.mw and id(w) not in self.baseline and w is not m and w is not p
                    and not type(w).__name__.startswith("QTip") and type(w).__name__ != "CustomLabel"):  # tooltips
                out.append(("window", w))
        return out

    def tidy_qt(self, keep=()):
        """Close what Qt has open, as a person would (Esc on a modal one, the
        window's close on the rest); return what it was. keep: class names left open."""
        seen, asked = [], {}
        for _ in range(8):
            found = [(k, w) for k, w in self.qt_open() if type(w).__name__ not in keep]
            if not found:
                break
            for kind, w in found:
                if id(w) in asked:
                    if asked[id(w)] < 2:  # still closing (Anki's Browser saves its note first)
                        asked[id(w)] += 1
                        continue
                    if hasattr(w, "_closeWindow"):
                        w._closeWindow()  # its editor never loaded offscreen: closed without the save
                    continue
                asked[id(w)] = 0
                desc = {"kind": kind, "cls": type(w).__name__, "title": _title(w)}
                if kind == "popup" and hasattr(w, "actions"):
                    desc["items"] = [a.text() for a in w.actions() if a.text()][:20]
                seen.append(desc)
                self.probe.note("windows", **desc)
                try:
                    w._may_close = True  # the plan window: closing with changes waiting asks first
                    if kind == "modal" and hasattr(w, "reject"):
                        w.reject()
                    else:
                        w.close()
                except RuntimeError:
                    pass
            yield self.r.until(lambda: self.probe.settled(self.mw), 10, "the add-on to settle after a window closed")
            yield self.r.pause(30)
        return seen

    def tidy_page(self):
        """Close what's open over the board (dcPop): Esc, as a person would."""
        closed = []
        if self.mw.state != "deckBrowser":
            return closed
        for _ in range(4):
            pop = yield self.js(pagejs.call("pop"))
            if not pop:
                break
            closed.append(pop)
            yield self.js(pagejs.call("esc"))
            yield self.r.until(lambda: self.probe.settled(self.mw), 10, "the add-on to settle after Esc")
        return closed

    def tidy(self):
        yield from self.tidy_qt()
        yield from self.tidy_page()

    # ---- boot ----
    def boot(self):
        mw = self.mw
        yield self.r.until(lambda: getattr(mw, "col", None) is not None and mw.state == "deckBrowser", 60,
                           "the Decks screen")
        dc = self.dc
        t_decks = time.perf_counter()  # 3.9.9: the Decks screen is up; from here to the board with its crew on it
        yield self.r.until(lambda: dc._state.get("entries") is not None, 30, "the board's first refresh")
        from aqt.qt import QApplication
        self.baseline = {id(w) for w in QApplication.topLevelWidgets() if w.isVisible()}
        yield from self.wait_board()
        first = time.perf_counter() - t_decks
        self.timings["board_first_draw_ms"] = round(first * 1000)
        self.check(f"boot: the board is drawn within {BOARD_MAX_S:g} s of the Decks screen", first <= BOARD_MAX_S,
                   f"{first:.1f} s", warn=True)
        # Magic search's how-to comes over the Decks screen once a person, a moment after it's drawn
        mf = __import__("due_crew.magic_flow", fromlist=["board_howto"])
        pop, t = "", time.perf_counter()
        while mf.board_howto() is not None and time.perf_counter() - t < 15:
            pop = yield self.js(pagejs.call("pop"))
            if pop:
                break
            yield self.r.pause(50)
        self.check("boot: Magic search's how-to comes over the board once", pop == "dc-magic", repr(pop), warn=True)
        rows = yield self.js("document.querySelectorAll('#due-crew [onclick*=\"duecrew:profile:\"]').length")
        self.check("boot: the board shows the crew", (rows or 0) >= 4, f"{rows} profile links")
        yield from self.snap("00-board")
        if pop:
            yield from self.snap("00-howto")
            yield from self.esc_check(pop, None, "Magic search's how-to (shown by itself)")
        self.base_cfg = json.loads(json.dumps(dc.cfg()))
        self.base_state = {k: dc._state.get(k) for k in VIEW_STATE}

    # ---- the board's windows (dcPop) ----
    def real_key(self, web, key):
        """A key pressed in a web view, as Qt delivers a person's."""
        from aqt.qt import QApplication, QEvent, QKeyEvent, Qt
        web.setFocus()
        target = web.focusProxy() or web
        for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            QApplication.sendEvent(target, QKeyEvent(kind, key, Qt.KeyboardModifier.NoModifier))

    def esc_check(self, pop, opener, label):
        """Esc closes the window over the board, and the key goes back to what opened it."""
        from aqt.qt import Qt
        self.probe.step = f"windows: {label}: Esc"
        self.real_key(self.mw.web, Qt.Key.Key_Escape)
        how = "a real Esc"
        gone = False
        for _ in range(40):
            now = yield self.js(pagejs.call("pop"))
            if now != pop:
                gone = True
                break
            yield self.r.pause(25)
        if not gone:
            how = "Esc in the page (Qt's key didn't reach it)"
            now = yield self.js(pagejs.call("esc"))
            gone = now != pop
        yield self.r.until(lambda: self.probe.settled(self.mw), 10, "settle")
        for _ in range(50):  # its fade (160 ms): the window leaves the page, then the key is wherever it went
            there = yield self.js("!!document.querySelector('[data-pop=\"%s\"]')" % pop)
            if not there:
                break
            yield self.r.pause(20)
        focus = yield self.js(pagejs.call("focusDesc"))
        rec = {"window": label, "id": pop, "esc_closes": gone, "how": how, "focus_after": focus, "opener": opener,
               "focus_back": (opener is None) or focus == opener}
        self.windows.append(rec)
        self.check(f"windows: Esc closes {label}", gone, how)
        if opener is not None:
            # 3.9.9: a failure, not a warning, once the Cheer window's key came back (its 🎉 pill hides
            # while the window's up; board/windows.py's close finds it again)
            self.check(f"windows: the key goes back to what opened {label}", rec["focus_back"],
                       f"focus on {focus!r}, opened by {opener!r}")

    def open_pop(self, cmd, want, label):
        """Press a board control that opens a window over the board; returns its id."""
        res = yield from self.press_cmd(cmd, view="windows", keep_open=True)
        if not res:
            self.check(f"windows: {label} opens", False, f"no control sends {cmd}")
            return ""
        pop = ""
        for _ in range(100):
            pop = yield self.js(pagejs.call("pop"))
            if pop:
                break
            yield self.r.pause(25)
        self.check(f"windows: {label} opens", pop == want, f"open: {pop!r}")
        if pop and self.pointer is not None:
            # the pointer is still where it pressed: what's under it now is the window's shade (Chromium
            # moves the hover there itself a moment after; offscreen it may not, so the robot says so)
            self.pointer_over(self.mw.web, *self.pointer)
            yield self.r.pause(40)
        if pop:
            yield from self.snap(f"10-{want}")
        return pop

    def dc_windows(self):
        yield from self.to_base()
        st = self.world.store
        # the Cheer window: Esc, then again and Send
        pop = yield from self.open_pop("cheerpick:dre", "dc-cheer", "the Cheer window")
        if pop:
            yield from self.esc_check(pop, "click cheerpick:dre", "the Cheer window")
        pop = yield from self.open_pop("cheerpick:dre", "dc-cheer", "the Cheer window (again)")
        if pop:
            self.probe.step = "windows: the Cheer window: Send"
            res = json.loads((yield self.js(pagejs.press_text("#dc-cheer button", "\U0001F389 Send"))))
            self.check("windows: the Cheer window's Send sends", res.get("found") and any(
                s.startswith("duecrew:cheersend:") for s in res.get("sent", [])), res)
            yield self.r.until(lambda: ("dre", "me") in st.cheers and self.probe.settled(self.mw), 10,
                               "the cheer to reach the server")
            self.check("windows: the cheer reached Dre (the fake server has it)", ("dre", "me") in st.cheers)
        # the bars grey with the window over the board; a click on the grey top bar closes it (app.veil)
        pop = yield from self.open_pop("cheerpick:dre", "dc-cheer", "the Cheer window (the bars' shade)")
        if pop:
            self.probe.step = "windows: the Cheer window: a click on the grey top bar"
            bar = self.mw.toolbar.web
            veiled = False
            for _ in range(100):
                veiled = yield self.js("(function(){var v=document.getElementById('dc-veil');"
                                       "return !!v && getComputedStyle(v).opacity !== '0'"
                                       " && v.style.pointerEvents === 'auto';})()", bar)
                if veiled:
                    break
                yield self.r.pause(20)
            self.check("windows: the top bar greys with the Cheer window", veiled)
            if veiled:
                n0 = len(self.probe.messages)
                yield self.js("document.getElementById('dc-veil').click()", bar)
                gone = False
                for _ in range(100):
                    gone = not (yield self.js(pagejs.call("pop")))
                    if gone:
                        break
                    yield self.r.pause(20)
                taps = [m for m in self.probe.messages[n0:] if m["msg"].startswith("duecrew:veiltap")]
                self.check("windows: a click on the grey top bar closes the Cheer window",
                           gone and taps and taps[0]["handled"], {"closed": gone, "sent": [m["msg"] for m in taps]})
                yield self.r.until(lambda: self.probe.settled(self.mw), 10, "settle")
                clear = yield self.js("(function(){var v=document.getElementById('dc-veil');"
                                      "return !v || v.style.pointerEvents === 'none';})()", bar)
                self.check("windows: the top bar clears with it", clear)
        # a crewmate's card
        pop = yield from self.open_pop("profile:max", "dc-profile", "a crewmate's card")
        if pop:
            yield from self.esc_check(pop, "click profile:max", "a crewmate's card")
        # 3.9.9: the board redrawn under it (a refresh landing while it's up, as it did now and then here):
        # the name that opened it is a new copy, and that copy gets the key back
        pop = yield from self.open_pop("profile:max", "dc-profile", "a crewmate's card, redrawn under it")
        if pop:
            self.probe.step = "windows: a crewmate's card: the board redrawn under it"
            yield self.js("[].forEach.call(document.querySelectorAll('#due-crew a'), function (a) {"
                          " if ((a.getAttribute('onclick') || '').indexOf('duecrew:profile:max|') >= 0)"
                          " { a.setAttribute('data-robot-old', '1'); } })")
            self.dc._swap(self.dc.cfg())
            yield self.r.until(lambda: self.probe.settled(self.mw), 10, "settle")
            fresh = yield self.js("!document.querySelector('[data-robot-old]') && !!document.querySelector('[data-pop=\"dc-profile\"]')")
            self.check("windows: a redraw under a crewmate's card puts new rows under it, the card still up", fresh)
            yield from self.esc_check(pop, "click profile:max", "a crewmate's card, redrawn under it")
        # a sheet: Settings › You › the name's change; Esc, then its yes
        yield from self.press_cmd("settings", view="windows")
        yield from self.wait_board("Settings")
        pop = yield from self.open_pop("setname", "dc-sheet", "a sheet (Display name)")
        if pop:
            yield from self.esc_check(pop, "click setname", "a sheet")
        pop = yield from self.open_pop("setname", "dc-sheet", "a sheet (again)")
        if pop:
            self.probe.step = "windows: a sheet: its yes"
            yield self.js(pagejs.type_into("#dc-sheet input", "Robin Robot"))
            n0 = len(self.probe.messages)
            res = json.loads((yield self.js(pagejs.press_text("#dc-sheet .ft button.go", ""))) or "{}")
            yield self.r.until(lambda: st.users["me"]["name"] == "Robin Robot" and self.probe.settled(self.mw), 10,
                               "the new name to reach the server")
            got = [m for m in self.probe.messages[n0:] if m["msg"].startswith("duecrew:sheet:")]
            self.check("windows: a sheet's yes reaches its handler and the server",
                       got and got[0]["handled"] and st.users["me"]["name"] == "Robin Robot", res)
        yield from self.to_base()

    # ---- presses ----
    def press_cmd(self, cmd, view, keep_open=False, ev="click", keep=()):
        """Press the first control on the board that sends cmd."""
        items = yield from self.controls()
        it = next((x for x in items if x["cmd"] == cmd and x["ev"] == ev), None)
        if it is None:
            return None
        rec = yield from self.press(view, it, keep_open=keep_open, keep=keep)
        return rec

    def controls(self):
        got = yield self.js(pagejs.call("list", None))
        if got is None:
            yield from self.helper()
            got = yield self.js(pagejs.call("list", None))
        return json.loads(got or "[]")

    def blocking(self):
        """A modal window or a popup menu is up (a click's handler waits in it)."""
        return any(k in ("modal", "popup") for k, _w in self.qt_open())

    def press(self, view, it, keep_open=False, keep=()):
        """One press, as a person's: the control, then what Anki and the add-on
        did. keep_open: a window it opens over the board stays (the windows'
        checks); keep: the class names of Qt windows it opens that stay."""
        probe, mw = self.probe, self.mw
        key = f"{it['ev']} {it['cmd']}"
        self.pressed.add(key)
        self.per_name[_name(it["cmd"])] = self.per_name.get(_name(it["cmd"]), 0) + 1
        probe.step = f"{view}: {it['cmd']}"
        marks = {k: len(getattr(probe, k)) for k in ("messages", "errors", "js_errors", "windows", "links", "tooltips",
                                                       "network")}
        t = time.perf_counter()
        rec = {"view": view, "cmd": it["cmd"], "ev": it["ev"], "text": it.get("text", ""), "tag": it.get("tag"),
               "shown": it.get("shown"), "verdict": "ok", "why": ""}
        windows, pops = [], []
        try:
            if not it.get("shown"):
                # it shows on hover (a crewmate's Cheer pill): the pointer goes over its row first
                spot = yield self.js(pagejs.call("spot", it["ev"], it["cmd"], it["n"]))
                if spot:
                    xy = json.loads(spot)
                    self.pointer_over(mw.web, xy["x"], xy["y"])
                    yield self.r.pause(40)
                rec["hovered"] = bool((yield self.js(pagejs.call("shown", it["ev"], it["cmd"], it["n"]))))
            res = yield from self._press_js(it, False, windows)
            if not res.get("found"):
                rec.update(verdict="gone", why="the control left the page before its turn")
                self.presses.append(rec)
                return rec
            sent = res.get("sent") or []
            if not sent and it.get("reads"):
                res = yield from self._press_js(it, True, windows)
                sent = res.get("sent") or []
                rec["filled"] = True
            rec.update(did=res.get("did"), over=res.get("over") or "", sent=[clean(s) for s in sent])
            ours = [s for s in sent if s.startswith("duecrew:")]
            if ours:
                def arrived():
                    got = probe.messages[marks["messages"]:]
                    return (len(got) >= len(ours) and not probe.handling() and probe.settled(mw)) or self.blocking()
                yield self.r.until(arrived, PRESS_SECS, f"the add-on to handle {it['cmd']}")
                windows += (yield from self.tidy_qt(keep))
                yield self.r.until(lambda: not probe.handling() and probe.settled(mw), PRESS_SECS,
                                   f"the add-on to settle after {it['cmd']}")
            # what came over the board, closed as a person would
            if mw.state == "deckBrowser":
                if keep_open:
                    pop = yield self.js(pagejs.call("pop"))
                    pops = [pop] if pop else []
                else:
                    pops = yield from self.tidy_page()
            windows += (yield from self.tidy_qt(keep))
            if mw.state == "deckBrowser":
                yield self.js("1")  # what the handler drew on the board has run
        except Timeout as e:
            rec.update(verdict="stuck", why=str(e))
            try:
                windows += (yield from self.tidy_qt())
            except Timeout:
                pass
        got = probe.messages[marks["messages"]:]
        rec["secs"] = round(time.perf_counter() - t, 3)
        rec["windows"] = [w["cls"] + (": " + w["title"] if w.get("title") else "") for w in windows] + [
            "board window " + p for p in pops] + [f"{k} (kept open)" for k in keep]
        rec["links"] = [x["url"] for x in probe.links[marks["links"]:]]
        rec["tooltips"] = [x["text"] for x in probe.tooltips[marks["tooltips"]:]]
        rec["network"] = [x["host"] for x in probe.network[marks["network"]:]]
        rec["errors"] = [x["text"][-1500:] for x in probe.errors[marks["errors"]:]]
        rec["js_errors"] = [f"{x['src']}:{x['line']} {x['text']}" for x in probe.js_errors[marks["js_errors"]:]]
        # the verdict
        if rec["verdict"] == "ok":
            pending = list(got)
            handlers = []
            ours = [s for s in rec.get("sent", []) if s.startswith("duecrew:")]
            for c in ours:
                m = next((x for x in pending if x["msg"] == c), None)
                if m is None:
                    rec.update(verdict="lost", why=f"the page sent {c} and Anki never got it")
                    break
                pending.remove(m)
                handlers.append(m["handler"])
                if m.get("raised"):
                    rec.update(verdict="raised", why=m["raised"][-600:])
                elif not m["handled"] and rec["verdict"] == "ok":
                    rec.update(verdict="no handler", why=f"{c} reached Anki and nothing of the add-on's ran for it")
            rec["handlers"] = handlers
            if not ours and rec["verdict"] == "ok":
                rec.update(verdict="dead", why="pressed, and the page sent nothing")
        if rec["errors"] and rec["verdict"] in ("ok", "stuck"):
            rec.update(verdict="raised", why=rec["errors"][0][-600:])
        if rec["verdict"] not in ("ok", "gone"):
            rec["shot"] = self.shot(f"fail-{len(self.presses):03d}-{it['cmd'][:30]}")
        self.presses.append(rec)
        return rec

    def _press_js(self, it, fill, windows):
        """The press in the page; when a modal window holds the page's answer
        back, the window is closed first and what the page sent read after."""
        code = pagejs.call("press", it["ev"], it["cmd"], it["n"], fill)
        res = yield self.r.js(self.mw.web, code, 10.0, unless=self.blocking)
        if res is BLOCKED:
            yield self.r.until(lambda: self.probe.handling() or self.blocking(), 2, "the handler")
            windows += (yield from self.tidy_qt())
            res = yield self.js("JSON.stringify({found: true, blocked: true, sent: window.__ct ? window.__ct.sent : []})")
        return json.loads(res or "{}")

    # ---- views ----
    def sig(self):
        dc = self.dc
        c, st = dc.cfg(), dc._state
        return json.dumps([self.mw.state, [c.get(k) for k in VIEW_CFG],
                           [st.get(k) if k != "closet_open" else (st.get(k) or {}).get("tab") for k in VIEW_STATE]],
                          default=str, sort_keys=True)

    def snapshot(self):
        dc = self.dc
        return {"cfg": {k: json.loads(json.dumps(dc.cfg().get(k))) for k in VIEW_CFG if k in dc.cfg()},
                "state": {k: _copy(dc._state.get(k)) for k in VIEW_STATE}}

    def restore(self, snap, full_cfg=None):
        """Back to a view: its keys as they were, and the board drawn again."""
        dc, mw = self.dc, self.mw
        c = json.loads(json.dumps(full_cfg)) if full_cfg is not None else dc.cfg()
        for k in VIEW_CFG:
            if k in snap["cfg"]:
                c[k] = _copy(snap["cfg"][k])
            else:
                c.pop(k, None)
        dc.save_cfg(c)
        for k, v in snap["state"].items():
            dc._state[k] = _copy(v)
        if mw.state != "deckBrowser":
            yield self.r.do(lambda: mw.moveToState("deckBrowser"))
            yield self.r.until(lambda: mw.state == "deckBrowser", 15, "the Decks screen")
        else:
            yield self.r.do(dc._rerender)
        yield from self.wait_board()

    def rebase(self):
        """What a part set up (a plan, the You box's list) stays for the rest:
        the base config is now's, but for the view's own keys."""
        c = json.loads(json.dumps(self.dc.cfg()))
        for k in VIEW_CFG:
            if k in self.base_cfg:
                c[k] = self.base_cfg[k]
            else:
                c.pop(k, None)
        self.base_cfg = c

    def to_base(self):
        yield from self.tidy()
        yield from self.restore({"cfg": {k: self.base_cfg.get(k) for k in VIEW_CFG if k in self.base_cfg},
                                 "state": dict(self.base_state)}, full_cfg=self.base_cfg)

    def sweep_views(self):
        quick = self.args.quick
        pick = [w.strip().lower() for w in (self.args.views or "").split(",") if w.strip()]
        for name, path in VIEWS:
            if pick and not any(w in name.lower() for w in pick):
                continue
            yield from self.to_base()
            ok = True
            for cmd in path:
                self.probe.step = f"{name}: to it"
                rec = yield from self.press_cmd(cmd, view=name)
                if rec is None or rec["verdict"] != "ok":
                    ok = False
                    self.check(f"views: {name} is reached by {cmd}", False,
                               "no control sends it" if rec is None else rec["why"])
                    break
                if self.mw.state == "deckBrowser":
                    yield from self.wait_board(name)
            if not ok:
                self.views.append({"name": name, "ok": False})
                continue
            snap, sig = self.snapshot(), self.sig()
            shot = yield from self.snap("20-" + name)
            items = yield from self.controls()
            view = {"name": name, "ok": True, "shot": shot, "controls": len(items), "pressed": 0,
                    "commands": sorted({f"{it['ev']} {it['cmd']}" for it in items})}
            self.views.append(view)
            self.check(f"views: {name} shows", True, f"{len(items)} controls")
            for _ in range(8 if quick else 150):
                items = yield from self.controls()
                todo = [it for it in items if self.wanted(it)]
                if not todo:
                    break
                yield from self.press(name, todo[0])
                view["pressed"] += 1
                if self.sig() != sig or self.mw.state != "deckBrowser":
                    yield from self.tidy()
                    yield from self.restore(snap)
                else:
                    yield from self.helper()
        yield from self.to_base()
        yield from self.magic_window()

    def wanted(self, it):
        key = f"{it['ev']} {it['cmd']}"
        if key in self.pressed or it["cmd"] in NAV:
            return False
        name = _name(it["cmd"])
        why = SKIP.get(it["cmd"]) or SKIP.get(name)
        if why:
            self.skipped.setdefault(it["cmd"], why)
            return False
        if it.get("off"):
            self.skipped.setdefault(it["cmd"], "disabled where it was")
            return False
        if name in REPEATS and self.per_name.get(name, 0) >= REPEATS[name]:
            self.skipped.setdefault(name + ":…", f"the same wiring as the first {REPEATS[name]}")
            return False
        return True

    def magic_window(self):
        """Magic search's window: open from the board, a search typed, closed."""
        from aqt.qt import QApplication
        self.probe.step = "Magic search: open"
        rec = yield from self.press_cmd("magic", view="Magic search", keep=("MagicWindow",))
        win = yield self.r.until(lambda: next((w for w in QApplication.topLevelWidgets()
                                               if type(w).__name__ == "MagicWindow" and w.isVisible()), None),
                                 10, "Magic search's window")
        yield self.r.until(lambda: self.probe.settled(self.mw), 10, "settle")
        ready = False
        for _ in range(100):
            ready = yield self.js("!!(window.dcMagic && document.querySelector('input, textarea'))", win.web)
            if ready:
                break
            yield self.r.pause(30)
        self.check("Magic search: its window opens from the board", rec is not None and rec["verdict"] == "ok" and ready,
                   rec and rec.get("windows"))
        yield self.js(pagejs.type_into("input, textarea", "Cardio"), win.web)
        try:
            yield self.r.until(lambda: str(win.face.text).strip() == "Cardio" and not win.face.busy
                               and self.probe.settled(self.mw), 10, "Magic search to read what was typed")
            self.check("Magic search: what's typed reaches it", True)
        except Timeout:
            self.check("Magic search: what's typed reaches it", False, repr(win.face.text))
        yield from self.snap("30-magic-search", win.web)
        self.probe.step = "Magic search: close"
        win.close()
        yield self.r.until(lambda: not any(type(w).__name__ == "MagicWindow" and w.isVisible()
                                           for w in QApplication.topLevelWidgets()), 10, "the window to close")
        self.check("Magic search: its window closes", True)

    # ---- the top bar's widget (a script's own buttons: the Fifteen's chip, the room's) ----
    def top_bar(self):
        """Every button the top bar's Due Crew widget has, pressed in turn as
        it changes (▶ Fifteen? starts one; its chip then has its own). A
        script's button that sends nothing may be the page's own (a fold):
        noted, not failed; one that sends a command no handler takes fails."""
        mw, probe = self.mw, self.probe
        yield from self.to_base()
        web = mw.toolbar.web
        yield from self.helper(web)
        sel = '[id^="dc-room-"]'
        done = set()
        for _ in range(4 if self.args.quick else 12):
            items = json.loads((yield self.js(pagejs.call("scripted", sel), web)) or "[]")
            todo = [x for x in items if x["key"] not in done]
            if not todo:
                break
            it = todo[0]
            done.add(it["key"])
            probe.step = f"top bar: {it['key']}"
            m0, e0 = len(probe.messages), len(probe.errors)
            res = yield self.r.js(web, pagejs.call("pressScripted", sel, it["i"]), 10.0, unless=self.blocking)
            windows = []
            if res is BLOCKED:
                windows += (yield from self.tidy_qt())
                res = yield self.js("JSON.stringify({found: true, sent: window.__ct ? window.__ct.sent : []})", web)
            res = json.loads(res or "{}")
            ours = [clean(x) for x in res.get("sent", []) if x.startswith("duecrew:")]
            try:
                yield self.r.until(lambda: (len(probe.messages) - m0 >= len(ours) and not probe.handling()
                                            and probe.settled(mw)) or self.blocking(), PRESS_SECS, "the handler")
                windows += (yield from self.tidy_qt())
            except Timeout as e:
                self.check(f"top bar: {it['key']} settles", False, e)
            if mw.state != "deckBrowser":
                yield from self.restore(self.snapshot())
            pops = yield from self.tidy_page()
            got = probe.messages[m0:]
            verdict, why, handlers = "ok", "", []
            for c in ours:
                m = next((x for x in got if x["msg"] == c), None)
                if m is None:
                    verdict, why = "lost", f"the page sent {c} and Anki never got it"
                    break
                handlers.append(m["handler"])
                if not m["handled"]:
                    verdict, why = "no handler", f"{c} reached Anki and nothing of the add-on's ran for it"
            errs = [x["text"][-1500:] for x in probe.errors[e0:]]
            if errs and verdict == "ok":
                verdict, why = "raised", errs[0][-600:]
            self.presses.append({"view": "Top bar", "cmd": ",".join(c.split("|")[0][8:] for c in ours) or "(none)",
                                 "ev": "click", "text": it["key"],
                                 "verdict": verdict if ours or verdict != "ok" else "page only",
                                 "why": why or ("" if ours else "a script's own button: it sent nothing to Anki"),
                                 "sent": ours, "handlers": handlers, "errors": errs,
                                 "windows": [w["cls"] for w in windows] + ["board window " + p for p in pops]})
            yield from self.helper(web)
        yield from self.snap("35-top-bar")
        # a Fifteen it started stops, from the board, as a person stops it (the rest runs without one)
        rooms = __import__("due_crew.rooms", fromlist=["my_room"])
        if rooms.room_model.is_fifteen(rooms.my_room()):
            yield from self.to_base()
            rec = yield from self.press_cmd("room15stop", view="Top bar")
            self.check("top bar: the Fifteen it started stops from the board", rec is not None and rec["verdict"] == "ok"
                       and not rooms.room_model.is_fifteen(rooms.my_room()), rec and rec["why"])

    # ---- the You box: two things to do ----
    def due_items(self):
        """Two things to do, typed into the You box's add line and Enter pressed:
        one for tomorrow (Upcoming), one for Later (its tab shows once it holds one)."""
        yield from self.to_base()
        for text in ("Robot notes later", "Robot quiz tomorrow"):
            self.probe.step = f"due: add {text!r}"
            n0 = len(self.probe.messages)
            ok = yield self.js(pagejs.type_into("#du-in", text))
            self.check(f"due: the You box takes {text!r}", ok)
            if not ok:
                return
            yield self.js("(function(){var i=document.getElementById('du-in');i.dispatchEvent(new KeyboardEvent("
                          "'keydown',{key:'Enter',bubbles:true,cancelable:true}));})()")
            adds = lambda: [m for m in self.probe.messages[n0:] if m["msg"].startswith("duecrew:dueadd:")]  # noqa: E731
            yield self.r.until(lambda: adds() and self.probe.settled(self.mw), 10, "the add to be handled")
            self.check(f"due: {text!r} is added", adds()[0]["handled"], adds()[0])
            yield from self.wait_board()
        items = (self.dc.cfg().get("due_items") or [])
        self.check("due: both are in my list", sum(1 for x in items if "Robot" in json.dumps(x)) >= 2,
                   f"{len(items)} items")
        self.rebase()

    # ---- plans ----
    def plan_window(self):
        """Tools › Due Crew › Plans › Your plans…, as a person picks it; the window once its page is up."""
        from aqt.qt import QApplication
        mw, probe = self.mw, self.probe
        probe.step = "plans: Tools › Due Crew › Plans › Your plans…"
        act = _menu_action(mw.form.menuTools, ("Due Crew", "Plans", "Your plans…"))
        self.check("plans: Tools › Due Crew › Plans › Your plans… is there", act is not None)
        if act is None:
            return None
        yield self.r.do(act.trigger)
        win = yield self.r.until(lambda: next((w for w in QApplication.topLevelWidgets()
                                               if type(w).__name__ == "PlanWeb" and w.isVisible()), None),
                                 20, "the plan window")
        yield self.r.until(lambda: probe.settled(mw) and not win.busy, 15, "the plan window to load")
        for _ in range(200):
            ready = yield self.js("!!(window.dcPlan && document.querySelector('#dcp .top'))", win.web)
            if ready:
                break
            yield self.r.pause(25)
        yield from self.helper(win.web)
        return win

    def plan_press(self, win, words, sel="button", nth=0, what=None, sends=True):
        """A button in the plan window by its words, as a pointer presses it.
        sends: it must send the window a command, and a handler must take it."""
        probe, mw, web = self.probe, self.mw, win.web
        probe.step = f"plans: {what or words}"
        n0 = len(probe.plan_messages)
        res = yield self.r.js(web, pagejs.press_text(sel, words, nth), 10.0, unless=lambda: not _open(win))
        if res is BLOCKED or res is None:
            # the window closed with the press (Close): its page's answer went with it; Anki's side says what came
            got = probe.plan_messages[n0:]
            res = json.dumps({"found": bool(got), "sent": [m["msg"] for m in got], "closed": True})
        res = json.loads(res or "{}")
        there = bool(res.get("found") and not res.get("off"))
        if not sends:  # a menu's button: the page opens the menu, nothing goes to Anki
            self.check(f"plans: {what or words} is there", there, res)
            return there
        sent = [x for x in res.get("sent", []) if x.startswith("dcplan:")]
        self.check(f"plans: {what or words} sends its command", there and sent,
                   res if not there else ("pressed, and the page sent nothing" if not sent else sent))
        if not (there and sent):
            self.shot(f"fail-plans-{(what or words)[:24]}", web)
            return False
        yield self.r.until(lambda: len(probe.plan_messages) >= n0 + len(sent) and probe.settled(mw)
                           and not (_open(win) and win.busy), 15, f"the plan window to handle {words}")
        got = probe.plan_messages[n0:]
        ok = got and all(m["handled"] for m in got)
        self.check(f"plans: {what or words} reaches its handler", ok, [(m["name"], m["handled"]) for m in got])
        if _open(win):
            yield self.r.js(web, "1", 10.0, unless=lambda: not _open(win))
        return ok

    def add_set(self, win, name):
        """Add › A set…, its name typed, Put it on."""
        web = win.web
        if not (yield from self.plan_press(win, "Add", "button.b.pri", what="Add", sends=False)):
            return False
        if not (yield from self.plan_press(win, "A set", ".menu .mi", what="Add › A set…")):
            return False
        yield self.js(pagejs.type_into(".veil .sheet input.in", name), web)
        return (yield from self.plan_press(win, "Put it on", ".veil .sheet .acts button", what="the set's Put it on"))

    def plans(self):
        yield from self.to_base()
        mw, probe, st = self.mw, self.probe, self.world.store
        # New plan › Start empty: a name, the deck, Start it
        win = yield from self.plan_window()
        if win is None:
            return
        web = win.web
        self.check("plans: no plans yet, so it opens on New plan", win.new is not None)
        yield from self.snap("40-plan-new", web)
        if not (yield from self.plan_press(win, "Start empty")):
            return
        yield self.r.until(lambda: (win.new or {}).get("step") == "empty", 10, "Start empty's screen")
        yield self.js(pagejs.type_into(".newp input.in", "Robot plan"), web)
        course = self.built["decks"]["Course"]
        yield self.js("(function(){var s=document.querySelector('.newp select.in');s.value=%s;"
                      "s.dispatchEvent(new Event('change',{bubbles:true}));})()" % json.dumps(str(course)), web)
        yield self.r.until(lambda: (win.new or {}).get("deck") == course and probe.settled(mw), 10,
                           "the deck to be picked")
        yield from self.snap("41-plan-empty", web)
        if not (yield from self.plan_press(win, "Start it", ".nfoot button")):
            return
        if not (yield from self.plan_press(win, "Start it", ".veil .sheet .acts button", what="the sheet's Start it")):
            return
        yield self.r.until(lambda: win.new is None and win.pid and win.doc is not None and not win.busy
                           and probe.settled(mw), 30, "the new plan to load")
        pid = win.pid
        self.check("plans: the server has the new plan", pid in st.plans, pid)
        yield from self.tidy_plan_sheet(web)
        yield from self.snap("42-plan-made", web)
        # a set, saved at once: nobody else follows it yet
        saves = len(st.plan_log)
        if not (yield from self.add_set(win, "Robot set 1")):
            return
        yield self.r.until(lambda: len(st.plan_log) > saves and probe.settled(mw) and not win.busy, 15,
                           "the set to be saved")
        self.check("plans: with nobody else following, a set saves at once",
                   "Robot set 1" in _unit_names(self.world, pid))
        yield from self.plan_press(win, "Close", ".foot button", what="Close")
        yield self.r.until(lambda: not _open(win), 10, "the plan window to close")
        # Dre follows it: a change now waits under the plan till Review and send
        code = st.plans[pid].get("code")
        status, _ = self.world.call("dre", "POST", "/plans/follow", {"code": code})
        self.check("plans: Dre follows the plan (on his own computer)", status == 200, status)
        win = yield from self.plan_window()
        if win is None:
            return
        web = win.web
        yield self.r.until(lambda: win.pid == pid and win.doc is not None and probe.settled(mw), 15, "the plan")
        self.check("plans: the window counts Dre as following", win.followers() >= 1, win.followers())
        if not (yield from self.add_set(win, "Robot set 2")):
            return
        yield self.r.until(lambda: win.draft is not None and len(win.draft) >= 1 and probe.settled(mw), 10,
                           "the set to wait under the plan")
        yield from self.snap("43-plan-waiting", web)
        saves = len(st.plan_log)
        if not (yield from self.plan_press(win, "Review and send")):
            return
        ready = yield self.js("!!document.querySelector('.veil .sheet.wide')", web)
        self.check("plans: Review and send shows the changes", ready)
        yield from self.snap("44-plan-review", web)
        yes = yield self.js("(function(){var b=document.querySelector('.veil .sheet .acts button.pri');"
                            "return b?b.textContent:''})()", web)
        yield from self.plan_press(win, yes or "Send", ".veil .sheet .acts button",
                                   what="Review and send › " + (yes or "Send"))
        try:
            yield self.r.until(lambda: len(st.plan_log) > saves and probe.settled(mw) and not win.busy, 15,
                               "the send to reach the server")
        except Timeout:
            pass
        names = _unit_names(self.world, pid)
        self.check("plans: the fake server got the send (Robot set 2 is on the plan)",
                   len(st.plan_log) > saves and "Robot set 2" in names,
                   {"saves": len(st.plan_log) - saves, "sets": names})
        yield from self.snap("45-plan-sent", web)
        self.rebase()
        yield from self.plan_press(win, "Close", ".foot button", what="Close")
        try:
            yield self.r.until(lambda: not _open(win), 10, "the plan window to close")
            self.check("plans: the window closes", True)
        except Timeout:
            self.check("plans: the window closes", False, "still open (changes waiting?)")
            win._may_close = True
            win.close()

    def tidy_plan_sheet(self, web):
        """A first look at a new plan may come with a sheet (what it covers): closed, as Esc does."""
        open_ = yield self.js("!!document.querySelector('.veil')", web)
        if open_:
            yield from self.snap("42-plan-first-sheet", web)
            yield self.js("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))", web)

    # ---- study ----
    def study(self):
        mw, probe = self.mw, self.probe
        yield from self.to_base()
        probe.step = "study: the deck"
        yield self.r.until(self.anki_idle, 10, "Anki's pages to load")
        res = json.loads((yield self.js(
            "(function(){var a=[].slice.call(document.querySelectorAll('a.deck')).filter(function(x){"
            "return x.textContent.trim()==='Course'})[0];if(!a)return '{}';a.click();return JSON.stringify({ok:1});})()"))
            or "{}")
        self.check("study: the deck is on the Decks screen", res.get("ok"))
        if not res.get("ok"):
            return
        t = time.perf_counter()
        yield self.r.until(lambda: mw.state == "overview", 10, "the deck's overview")
        for _ in range(200):
            ok = yield self.js("!!document.getElementById('study')")
            if ok:
                break
            yield self.r.pause(15)
        self.timings["deck_to_overview_ms"] = round((time.perf_counter() - t) * 1000)
        yield from self.snap("50-overview")
        probe.step = "study: Study Now"
        yield self.r.until(self.anki_idle, 10, "the overview's pages to load")
        yield self.js("document.getElementById('study').click()")
        t = time.perf_counter()
        n = 0
        while True:
            got = yield self.js("(function(){var q=document.getElementById('qa');return q?q.innerHTML.length:0;})()")
            n += 1
            if got and mw.state == "review":
                break
            if time.perf_counter() - t > 20:
                raise Timeout("no card 20 s after Study Now")
            yield self.r.pause(10)
        first = time.perf_counter() - t
        self.timings["first_card_ms"] = round(first * 1000)
        self.check(f"study: the first card shows within {FIRST_CARD_MAX_S:g} s of Study Now", first <= FIRST_CARD_MAX_S,
                   f"{first * 1000:.0f} ms")
        yield from self.snap("51-first-card")
        answers = []
        for i in range(5):
            probe.step = f"study: card {i + 1}"
            cid = mw.reviewer.card.id if mw.reviewer.card else None
            yield self.r.until(lambda: mw.reviewer.state == "question" and self.anki_idle(), 10, "the question")
            yield self.r.until(lambda: True, 1, "")
            t = time.perf_counter()
            yield self.js("(function(){var b=document.getElementById('ansbut');if(b){b.click();return 1}return 0})()",
                          mw.reviewer.bottom.web)
            try:
                yield self.r.until(lambda: mw.reviewer.state == "answer" and self.anki_idle(), 10, "the answer")
            except Timeout:
                bottom = yield self.js("document.body ? document.body.innerHTML.slice(0, 400) : ''",
                                       mw.reviewer.bottom.web)
                self.check("study: Show Answer shows the answer", False,
                           {"state": mw.state, "reviewer": mw.reviewer.state, "bottom bar": bottom,
                            "screens": self.probe.states[-8:]})
                raise
            if i == 0:
                yield from self.snap("52-answer")
            yield self.js("(function(){var b=document.querySelector('button[data-ease=\"3\"]');"
                          "if(b){b.click();return 1}return 0})()", mw.reviewer.bottom.web)
            yield self.r.until(lambda: mw.state != "review" or (mw.reviewer.card and mw.reviewer.card.id != cid
                                                                 and mw.reviewer.state == "question"),
                               10, "the next card")
            answers.append(round((time.perf_counter() - t) * 1000))
            if mw.state != "review":
                break
        self.timings["answers_ms"] = answers
        self.check("study: five cards answered (Show Answer, Good)", len(answers) == 5, answers)
        probe.step = "study: back to Decks"
        yield self.r.do(lambda: mw.moveToState("deckBrowser"))
        yield from self.wait_board("the board after studying")
        yield from self.snap("53-board-after")
        # the board's clicks after a review (3.9.1's release blocker: the Decks page's key): each still lands
        for cmd in ("period:week", "profile:dre", "refresh", "settings", "setclose", "duetab:upcoming", "duetick:"):
            items = yield from self.controls()
            it = next((x for x in items if x["ev"] == "click" and (x["cmd"] == cmd or
                                                                  (cmd.endswith(":") and x["cmd"].startswith(cmd)))), None)
            if it is None:
                self.check(f"study: after a review, {cmd} is on the board", False)
                continue
            rec = yield from self.press("After a review", it)
            self.check(f"study: after a review, {it['cmd']} still reaches its handler", rec["verdict"] == "ok", rec["why"])
            if mw.state != "deckBrowser":
                yield from self.to_base()

    # ---- energy ----
    def energy(self):
        """A minute on the Decks screen with no input, after a person's last
        move over the board: CPU in 5 s slices. The page rests 12 s after the
        last input (sev.REST_JS); from REST_FROM_S on is "at rest", and that
        is what's held to CPU_REST_MAX. The whole minute is reported too."""
        from . import cpu
        mw = self.mw
        secs = self.args.rest if self.args.rest is not None else (30.0 if self.args.quick else 60.0)
        yield from self.to_base()
        self.probe.step = "energy: at rest"
        self.pointer_over(mw.web)  # the last input, then hands off
        state0 = yield self.js(REST_STATE)
        slices, step = [], 5.0
        a = cpu.sample()
        t0 = a["at"]
        while a["at"] - t0 < secs - 0.5:
            yield self.r.pause(int(step * 1000))
            b = cpu.sample()
            s = cpu.percent(a, b)
            s["from"] = round(a["at"] - t0, 1)
            slices.append(s)
            a = b
        wall = a["at"] - t0
        state1 = yield self.js(REST_STATE)

        def mean(xs):
            return round(sum(x["total"] * x["secs"] for x in xs) / max(0.001, sum(x["secs"] for x in xs)), 1)
        rest = [x for x in slices if x["from"] >= REST_FROM_S]
        self.cpu = {"secs": round(wall, 1), "whole": mean(slices), "at_rest": mean(rest) if rest else None,
                    "rest_from_s": REST_FROM_S, "max_at_rest": CPU_REST_MAX, "slices": slices,
                    "page_before": json.loads(state0 or "{}"), "page_after": json.loads(state1 or "{}"),
                    "how": cpu.HOW, "cores": os.cpu_count()}
        if rest:
            self.check(f"energy: the board at rest (from {REST_FROM_S:g} s after the last input) uses at most "
                       f"{CPU_REST_MAX:g}% of one core", self.cpu["at_rest"] <= CPU_REST_MAX,
                       f"{self.cpu['at_rest']}% at rest, {self.cpu['whole']}% over the whole {wall:.0f} s")
        self.check("energy: the page says it's resting by the end", self.cpu["page_after"].get("rest"),
                   self.cpu["page_after"], warn=True)
        yield from self.snap("60-at-rest")

    def pointer_over(self, web, x=None, y=None):
        """A pointer moved over the web view, as a person's: to (x, y) in the page's CSS px, else its middle."""
        from aqt.qt import QApplication, QEvent, QMouseEvent, QPointF, Qt
        self.pointer = (x, y) if x is not None else None
        target = web.focusProxy() or web
        z = web.zoomFactor() or 1.0
        p = QPointF(web.width() / 2, web.height() / 3) if x is None else QPointF(x * z, y * z)
        ev = QMouseEvent(QEvent.Type.MouseMove, p, web.mapToGlobal(p), Qt.MouseButton.NoButton,
                         Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(target, ev)


def _open(w):
    """A window that's still there and showing (a closed one may be gone already)."""
    try:
        return w.isVisible()
    except RuntimeError:
        return False


def _title(w):
    try:
        return str(w.windowTitle() or "")[:80]
    except Exception:
        return ""


def _copy(v):
    if isinstance(v, set):
        return set(v)
    try:
        return json.loads(json.dumps(v))
    except (TypeError, ValueError):
        return v


def _unit_names(world, pid):
    doc = world.plan_docs().get(pid) or {}
    return [u.get("name") for u in (doc.get("units") or [])]


def _menu_action(menu, path):
    """An action in a menu, by the words of each level."""
    want, rest = path[0], path[1:]
    for a in menu.actions():
        if a.text().replace("&", "") != want:
            continue
        if not rest:
            return a
        sub = a.menu()
        return _menu_action(sub, rest) if sub is not None else None
    return None
