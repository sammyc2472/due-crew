"""3.9.9, Know when it breaks (Sam's sign-off): each install counts its own
failures by code, never by content, and a day's counts go to Sam with the
first sync after that day is over (Anki's day), once. Both bugs of 3.9.8's
week (a plan's Send that sent nothing, a good-luck card that never showed)
were found only because Sam hit them himself.

A code is short, from [a-z0-9_.:-], at most 80 characters, and built only
from our own names, never from data:
  save:<error>         a plan save the server refused (planner/remote.py's
                       words' codes; any other is save:other)
  py:<module>:<function>:<type>
                       an exception the add-on caught and printed (oops):
                       the deepest frame in the add-on, its file (planner.flow
                       for planner/flow.py) and function, and the exception's
                       type; never its message, which can hold card text, a
                       name or a path
  cmd:<name>:bad       a board command of BOARD_CMDS whose values failed its check
  cmd:unknown          a name the table hasn't (it can come from a card's
                       script: never said)
  req:<route>:<status> a request that failed: its route as the Worker names
                       it (plans.:id, never an id or a code) and its status,
                       timeout or offline

Kept per profile (errs.json beside wrap.json): today and the DAYS_HELD days
before it, CODES_MAX codes a day, each count at most COUNT_MAX. Behind
Privacy's "Send Sam what went wrong" (the account's send_errs; off, nothing
is counted or kept). Standard library only: counted from any thread (a
lock), written by the main thread (errs_flow, the glue)."""

import datetime
import json
import os
import re
import sys
import threading
import time
import traceback

# Privacy's "Send Sam what went wrong" for someone who never set it. Sam may
# want it off by default: this line is the flip.
SEND_DEFAULT = True


def wanted(c):
    """Privacy's switch in a config: the account's send_errs, else SEND_DEFAULT."""
    v = c.get("send_errs") if isinstance(c, dict) else None
    return v if isinstance(v, bool) else SEND_DEFAULT


CODE_RE = re.compile(r"[a-z0-9_.:-]{1,80}")
CODE_MAX = 80
CODES_MAX = 50     # a day's distinct codes (MORE holds the rest, as the fiftieth)
COUNT_MAX = 9999   # one code's count a day
DAYS_HELD = 7      # finished days kept for the sync; older ones go unsent
MORE = "errs:more"
VERSION_RE = re.compile(r"\d{1,4}(\.\d{1,4}){0,3}")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
ROOT = os.path.dirname(os.path.abspath(__file__))  # the add-on's folder (2035408484 when AnkiWeb installs it)


# ---- codes ----

def clean_code(code):
    """The code, when it's one (the alphabet, the length), else None."""
    code = code if isinstance(code, str) else ""
    return code if CODE_RE.fullmatch(code) else None


def _word(text, most):
    """One of our names as part of a code: lower case, a-z 0-9 _ alone
    (<lambda> is lambda), at most `most`."""
    return re.sub(r"[^a-z0-9_]+", "", str(text or "").lower())[:most] or "x"


def _inside(path, root):
    try:
        p = os.path.normcase(os.path.abspath(path))
        r = os.path.normcase(os.path.abspath(root))
    except (TypeError, ValueError):
        return False
    return p.startswith(r + os.sep)


def _module(path, root):
    """planner/flow.py is planner.flow; the file stem, its folders before it
    (board/due.py and due.py are two)."""
    rel = os.path.relpath(os.path.abspath(path), os.path.abspath(root))
    parts = os.path.splitext(rel)[0].split(os.sep)
    return ".".join(_word(p, 24) for p in parts)[:24]


def py_code(kind, tb, root=ROOT):
    """py:<module>:<function>:<type> for an exception: the deepest frame of
    its traceback in the add-on's folder, and its type's name. Never its
    message (str(e)): one can hold a card's text, a name or a path."""
    where = None
    while tb is not None:
        code = tb.tb_frame.f_code
        if _inside(code.co_filename, root):
            where = (code.co_filename, code.co_name)
        tb = tb.tb_next
    module, func = (_module(where[0], root), _word(where[1], 28)) if where else ("other", "other")
    return clean_code(f"py:{module}:{func}:{_word(getattr(kind, '__name__', ''), 23)}"[:CODE_MAX])


# the Worker's routes (worker/src/index.ts), as a request's path names them:
# a part that's an id, a code or a number is :id, :code or :n (the suite
# checks this against index.ts, both ways)
ROUTES = (
    "/version", "/auth/code", "/auth/verify", "/auth/link/redeem", "/plans/ics", "/plans/public", "/auth/gone",
    "/links/email", "/auth/link", "/auth/me", "/auth/signout", "/auth/signout-all", "/auth/places", "/account",
    "/table", "/table/:code", "/table/:code/ws",
    "/board", "/sync", "/decks", "/heatmap/:id", "/settings",
    "/users/:id", "/friends", "/friends/:id", "/codes", "/codes/:code", "/codes/:code/add",
    "/invites/:code", "/invites", "/invites/:code/redeem", "/cheers/:id", "/knocks", "/knocks/:id", "/reports",
    "/tips/helped", "/hooks", "/log", "/account/data", "/account/todos",
    "/admin/stats", "/admin/trends", "/admin/people", "/admin/people/:id", "/admin/people/:id/signout",
    "/admin/people/:id/code", "/admin/people/:id/limits", "/admin/people/:id/email", "/admin/people/:id/note",
    "/admin/people/:id/crew", "/admin/people/:id/crew/:id", "/admin/actions", "/admin/squads/:id",
    "/admin/squads/:id/code", "/admin/squads/:id/remove/:id", "/admin/bingo", "/feedback", "/admin/feedback",
    "/admin/feedback/:id", "/admin/feedback/:id/reply", "/admin/reports", "/admin/reports/:id", "/admin/bingo/:id",
    "/admin/notices", "/admin/notices/:n", "/admin/field",
    "/plans/trees", "/plans/mine", "/plans/peek", "/plans/follow", "/plans", "/plans/:id", "/plans/:id/cards",
    "/plans/:id/tags", "/plans/:id/progress", "/plans/:id/follow", "/library", "/plans/:id/listed",
    "/plans/:id/copy", "/plans/:id/report", "/admin/library", "/admin/library/:id", "/plans/:id/log",
    "/plans/:id/ids", "/plans/:id/undo", "/plans/:id/editors", "/plans/:id/editors/:id", "/plans/:id/invite",
    "/plans/:id/owner", "/plans/:id/remarks", "/plans/:id/notes", "/plans/:id/notes/:n", "/plans/:id/posts",
    "/plans/:id/posts/:n", "/plans/:id/team", "/plans/:id/asks", "/plans/:id/asks/:n", "/plans/:id/asks/:n/helped",
    "/squads", "/squads/peek", "/squads/mine", "/squads/:id", "/squads/:id/join", "/squads/:id/row",
    "/squads/:id/members/:id", "/squads/:id/block/:id",
)
_ROUTE_PARTS = [(t, t.strip("/").split("/")) for t in ROUTES]


def route_of(path):
    """A request's route as ROUTES names it ("/plans/:id"), never its ids
    or codes; "other" for a path that's none of them. Among the routes of
    its length, the one whose fixed parts all match and are the most of
    them (/plans/trees before /plans/:id)."""
    bits = str(path or "").split("?")[0].split("#")[0].strip("/").split("/")
    best, most = "other", -1
    for t, parts in _ROUTE_PARTS:
        if len(parts) != len(bits):
            continue
        fixed = sum(1 for p in parts if not p.startswith(":"))
        if fixed > most and all(p.startswith(":") or p == b for p, b in zip(parts, bits)):
            best, most = t, fixed
    return best


def req_code(path, status):
    """req:<route>:<status>: plans.:id for /plans/:id (a code's alphabet has
    no slash); the status a number, "timeout" or "offline"."""
    route = route_of(path)
    word = route.strip("/").replace("/", ".") or "root"
    said = (status if status in ("timeout", "offline")
            else str(status) if isinstance(status, int) and not isinstance(status, bool) and 100 <= status <= 599
            else "other")
    return clean_code(f"req:{word}:{said}"[:CODE_MAX])


def save_code(error, known):
    """save:<error> for a refused save: the server's error when it's one of
    `known` (the window's words' codes), else save:other."""
    error = error if isinstance(error, str) else ""
    return clean_code(f"save:{error if error in known else 'other'}") or "save:other"


def cmd_code(name, table):
    """cmd:<name>:bad for a name in `table` whose values didn't pass; any
    other name is cmd:unknown, whatever it said."""
    return (clean_code(f"cmd:{name}:bad") if isinstance(name, str) and name in table else None) or "cmd:unknown"


# ---- a day, as Anki counts it ----

def _date(text):
    try:
        return datetime.date.fromisoformat(text) if isinstance(text, str) and DATE_RE.fullmatch(text) else None
    except ValueError:
        return None


def _shift(day, n):
    return (_date(day) + datetime.timedelta(days=n)).isoformat()


# ---- a profile's counts ----

class Tally:
    """{day: {code: n}}, in a small file (path; None: in memory only, the
    counts before a profile opens). Counted from any thread; saved by the
    main thread, and only when it changed."""

    def __init__(self, path=None):
        self.path = path
        self.days = {}
        self.dirty = False
        self.lock = threading.Lock()
        if path:
            self._load()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        days = data.get("days") if isinstance(data, dict) and data.get("v") == 1 else None
        if not isinstance(days, dict):
            return
        for day in sorted((d for d in days if _date(d)), reverse=True)[:DAYS_HELD + 1]:
            codes = days[day] if isinstance(days[day], dict) else {}
            kept = {}
            for code, n in codes.items():
                if (clean_code(code) and isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= COUNT_MAX
                        and len(kept) < CODES_MAX):
                    kept[code] = n
            if kept:
                self.days[day] = kept

    def add(self, code, day, n=1):
        """One more of `code` on `day` (n more); True when it counted. Past
        CODES_MAX - 1 codes a day, a new one counts as MORE."""
        code = clean_code(code)
        if code is None or _date(day) is None:
            return False
        with self.lock:
            codes = self.days.setdefault(day, {})
            if code not in codes and len([c for c in codes if c != MORE]) >= CODES_MAX - 1:
                code = MORE
            codes[code] = min(COUNT_MAX, codes.get(code, 0) + max(1, int(n)))
            lo = _shift(day, -DAYS_HELD)
            for d in [d for d in self.days if d < lo]:
                del self.days[d]
            self.dirty = True
        return True

    def has(self, code, day):
        with self.lock:
            return code in (self.days.get(day) or {})

    def merge(self, other):
        """What `other` counted, added in (the counts from before a profile opened)."""
        with other.lock:
            held = {d: dict(c) for d, c in other.days.items()}
        for day, codes in sorted(held.items()):
            for code, n in codes.items():
                self.add(code, day, n)

    def ready(self, today):
        """The finished days a sync sends: before `today`, the DAYS_HELD
        before it at most, {day: {code: n}}. Older ones go unsent."""
        if _date(today) is None:
            return {}
        lo = _shift(today, -DAYS_HELD)
        with self.lock:
            for d in [d for d in self.days if d < lo]:
                del self.days[d]
                self.dirty = True
            return {d: dict(c) for d, c in sorted(self.days.items()) if d < today and c}

    def of(self, day):
        with self.lock:
            return dict(self.days.get(day) or {})

    def drop(self, days):
        """Those days went (or may have): they never go again."""
        with self.lock:
            for d in days:
                if self.days.pop(d, None) is not None:
                    self.dirty = True

    def clear(self):
        with self.lock:
            if self.days:
                self.days = {}
                self.dirty = True

    def save(self):
        """Written whole, then swapped in; nothing when nothing changed."""
        if not self.path or not self.dirty:
            return
        with self.lock:
            text = json.dumps({"v": 1, "days": self.days}, sort_keys=True)
            self.dirty = False
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, self.path)
        except OSError:
            self.dirty = True


# ---- where counts go now ----

_now = {"tally": Tally(), "on": True, "day": None, "after": None}


def use(tally, on=True):
    """The open profile's tally (a Tally(None) between profiles). on: its
    switch; off, nothing is counted and nothing is kept."""
    _now["tally"] = tally
    switch(on)


def current():
    return _now["tally"]


def switch(on):
    _now["on"] = bool(on)
    if not on:
        _now["tally"].clear()


def after(fn):
    """fn(), after a count, from the thread that counted (the glue's save)."""
    _now["after"] = fn


def set_day(cutoff, label):
    """Main thread, from the collection: Anki's day cutoff (epoch seconds)
    and today's label, so any thread can say what day it is."""
    if _date(label) is not None:
        _now["day"] = (int(cutoff), label)


def today(now=None):
    """Anki's day now: the cutoff last read, a day further for each day
    since; before one, the calendar's day under Anki's default rollover (4am)."""
    now = time.time() if now is None else now
    ref = _now["day"]
    if ref:
        cutoff, label = ref
        if now < cutoff:
            return label
        return _shift(label, 1 + int((now - cutoff) // 86400))
    return (datetime.datetime.fromtimestamp(now) - datetime.timedelta(hours=4)).date().isoformat()


# ---- 3.9.9: what gets used ----
# Which parts of Due Crew were opened today, as codes on the same path ("use:insights"): once a day a
# part however often it's opened, with "use:any" beside them so a share has its whole. Never what was
# done there. Counted only once the person has been told (the account's use_told; errs_flow.told).

USE = (  # a board command's first letters -> its part (the longest first)
    ("planteam", "plansquad"), ("plan", "plans"), ("due", "due"), ("ins", "insights"), ("youins", "insights"),
    ("closet", "closet"), ("wrapped", "wrapped"), ("party", "party"), ("magic", "magic"), ("song", "songs"),
    ("dance", "songs"), ("bingo", "bingo"), ("cheer", "cheers"), ("fridge", "fridge"), ("squad", "squads"),
    ("knock", "squads"), ("room", "rooms"), ("knows", "knows"), ("settings", "settings"), ("friends", "friends"),
    ("profile", "profile"), ("sharemenu", "share"), ("decks", "crewdecks"),
)
USE_PARTS = tuple(sorted({p for _s, p in USE} | {"any", "planwin", "fifteen", "aiapp", "twobuttons"}))


def use_of(cmd):
    """The part a board command belongs to, or None."""
    cmd = str(cmd or "")
    for start, part in sorted(USE, key=lambda x: -len(x[0])):
        if cmd.startswith(start):
            return part
    return None


def use_ok(on):
    """The person has been told what's counted (the glue says so)."""
    _now["use_ok"] = bool(on)


def used(part):
    """`part` was opened today: its code once, and use:any once. Never raises."""
    try:
        if not part or part not in USE_PARTS or not _now["on"] or not _now.get("use_ok"):
            return
        day, t, hit = today(), _now["tally"], False
        for code in ("use:any", "use:" + part):
            if not t.has(code, day):
                hit = t.add(code, day) or hit
        if hit and _now["after"] is not None:
            _now["after"]()
    except Exception:
        pass


def count(code):
    """One more of `code` today, from any thread. Never raises: a count
    never stops what it counts."""
    try:
        if _now["on"] and _now["tally"].add(code, today()) and _now["after"] is not None:
            _now["after"]()
    except Exception:
        pass


def oops(quiet=False):
    """In an except block, in place of traceback.print_exc(): the traceback
    printed as it was (quiet: the caller says its own line), and counted as
    py:<module>:<function>:<type>, never what it said."""
    if not quiet:
        traceback.print_exc()
    try:
        kind, _e, tb = sys.exc_info()
        if kind is not None:
            count(py_code(kind, tb))
    except Exception:
        pass


# ---- what goes ----

def clean_version(v):
    v = str(v or "")
    return v if VERSION_RE.fullmatch(v) else "0"


def part(tally, today_label, version):
    """The sync's errs: {"days": {day: {code: n}}, "v": version} for the
    finished days, or None when there are none."""
    days = tally.ready(today_label)
    return {"days": days, "v": clean_version(version)} if days else None


SHEET_TITLE = "What the next sync sends"


def sheet_text(sending, why=""):
    """See what went's words: exactly what the next sync carries (sending,
    its errs part, or None), or why it carries none."""
    if why:
        return why
    if not sending:
        return "Nothing yet. A day's counts go with the first sync after it ends."
    lines = [f"Due Crew {sending['v']} sends:"]
    for day in sorted(sending["days"], reverse=True):
        lines.append("")
        lines.append(day)
        for code, n in sorted(sending["days"][day].items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"{code} × {n:,}")
    return "\n".join(lines)
