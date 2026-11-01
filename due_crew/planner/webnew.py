"""New plan in the HTML window ("Plans end to end", Sam's pick): the one way
to start a plan, in the tabs' place. A resource, at my pace (its chapters
in the deck's order, one lesson each, on my study days: edits.resource_plan);
someone's plan (a code, or the library on duecrew.com); or start empty (a
name, the deck, the exam it ends with, then the deck beside it to lay out).
A class's calendar waits (Sam: not yet). Nothing is sent until Make: Make
it puts the plan on duecrew.com as mine (POST /plans, then the builder's
save); Start it also follows it here (my own plan, nobody waits on my
changes for me), today's lesson in my deck or its own (the follow's
lesson deck, changeable in Settings later).

A mixin of WebFace's: self.new is the screen's state while it's up,
new_view() its view, c_new_* its clicks. Qt-free."""

import datetime

from .. import plans as P
from . import edits as E
from . import model as M

STEPS = ("pick", "resource", "someone", "empty")
PACES = ("daily", "by", "ready")
DAILY = 20


def _day(iso, n):
    return (datetime.date.fromisoformat(str(iso)) + datetime.timedelta(days=n)).isoformat()


def _iso(v):
    try:
        return datetime.date.fromisoformat(str(v)).isoformat()
    except ValueError:
        return None


def _pl(n, one, many=None):
    return f"{n:,} {one if n == 1 else (many or one + 's')}"


class NewPlan:
    new = None

    # ---- the screen ----

    def new_open(self, finish_by=None, exam=None, start=None):
        """New plan, on its first screen; finish_by and exam come from the
        board's exam line (Plan the way there), start from a link."""
        today = str(self.ops.today())
        decks = [(d, str(n), int(c)) for d, n, c in (self.ops.top_decks() or [])]
        got = getattr(self.ops, "new_defaults", None)
        try:
            dflt = (got() if callable(got) else None) or {}
        except Exception:  # noqa: BLE001 (no defaults: the plain ones)
            dflt = {}
        if _iso(dflt.get("exam")) and str(dflt["exam"]) > today and (not finish_by or finish_by == dflt["exam"]):
            finish_by, exam = dflt["exam"], exam or "Exam"  # my exam (Settings): Finish by it
        by = _iso(finish_by) if finish_by else None
        mine = dflt.get("deck")
        days = dflt.get("days")
        days = [1 if x else 0 for x in days] if isinstance(days, list) and len(days) == 7 and any(days) else [1, 1, 1, 1, 1, 0, 0]
        self.new = {"step": "pick", "decks": decks,
                    "deck": mine if any(d == mine for d, _n, _c in decks) else decks[0][0] if decks else None, "name": "", "named": "",
                    "end_name": " ".join(str(exam or "").split())[:60], "end_day": by or _day(today, 28),
                    "lesson": "deck", "said": "", "busy": False, "made": None,
                    "res": None, "only": None, "pace": "by" if by else "daily", "daily": DAILY, "by": by or _day(today, 42),
                    "days": days, "starts": _iso(start) or _day(today, 1), "code": "",
                    "_ctx": None}
        self.push()

    def new_view(self):
        st = self.new
        out = {"step": st["step"], "back": bool(self.plans), "busy": st["busy"], "said": st["said"],
               "decks": [{"id": d, "label": f"{n} · {c:,} cards"} for d, n, c in st["decks"]], "deck": st["deck"],
               "deckName": self._new_deck_name(), "name": st["name"], "endName": st["end_name"], "endDay": st["end_day"],
               "lesson": st["lesson"], "code": st["code"], "today": str(self.ops.today())}
        if st["step"] == "resource":
            out["resource"] = self._resource_view()
            out["name"] = st["name"] or (out["resource"].get("name") or "")
        out["canMake"] = bool(out["name"].strip()) and st["deck"] is not None and not st["busy"] and (
            st["step"] != "resource" or bool((out.get("resource") or {}).get("ok")))
        return out

    def _new_deck_name(self):
        st = self.new
        return next((n for d, n, _c in st["decks"] if d == st["deck"]), "")

    # ---- a resource ----

    def _new_ctx(self):
        """(idx, tree, parts) for the deck picked, read once a deck."""
        st = self.new
        if st["_ctx"] is None or st["_ctx"][0] != st["deck"]:
            idx = self.ops.index(st["deck"]) if st["deck"] is not None else None
            tree = parts = None
            if idx is not None:
                from .build import Tree
                tree = Tree(*idx.tree())
                parts = M.resource_parts(idx, tree)
            st["_ctx"] = (st["deck"], idx, tree, parts or [])
            if parts and st["res"] not in [p["path"] for p in parts]:
                st["res"], st["only"] = parts[0]["path"], None
        return st["_ctx"][1:]

    def _resource_view(self):
        st = self.new
        idx, tree, parts = self._new_ctx()
        out = {"parts": [{"path": p["path"], "name": p["name"], "sub": self._part_sub(p), "cards": p["cards"],
                          "on": p["path"] == st["res"]} for p in parts],
               "pace": st["pace"], "daily": st["daily"], "by": st["by"], "days": st["days"], "starts": st["starts"],
               "only": [], "onlyOn": st["only"], "ok": False}
        if idx is None or not st["res"]:
            out["empty"] = "Nothing in this deck reads as a resource: chapters under a # tag." if idx is not None else ""
            return out
        out["only"] = [{"path": t, "label": M.label(t), "n": n} for t, n in M.also_tagged(idx, idx.tag_cards(st["res"]),
                                                                                         skip=[st["res"]], most=12)]
        if st["only"]:
            kept, total = M.only_count(idx, st["res"], st["only"])
            out["onlyCount"] = f"{kept:,} of {total:,}"
        out["name"] = M.resource_name(st["res"], st["only"])
        try:
            doc, sm = self._resource_doc(idx, tree)
        except E.Refused as e:
            out["said"] = str(e)
            return out
        dates = sm.get("dates") or []
        out["ok"] = bool(dates)
        out["summary"] = (f"{_pl(int(sm.get('lessons') or len(dates)), 'set')}, {int(sm.get('new') or 0):,} new · "
                          f"{P.fmt_day(sm['first'])} – {P.fmt_day(sm['last'])}" if dates else "")
        if dates and sm.get("busiest"):
            out["summary"] += f" · busiest day {int(sm['busiest']):,} new"
        out["note"] = str(sm.get("note") or "")
        out["dates"] = [{"n": i + 1, "name": str(u.get("name") or ""), "when": self._when(u), "cards": int(u.get("n") or 0)}
                        for i, u in enumerate(dates[:3])]
        out["more"] = max(0, len(dates) - 3)
        out["path"] = self._path_view(doc, dates)
        out["pace"] = st["pace"]
        if st["pace"] != "daily":
            out["daily"] = int(sm.get("daily") or st["daily"])
        return out

    @staticmethod
    def _path_view(doc, dates):
        """3.9.6, day one (Sam's pick): the plan laid out set by set, as the
        board's path will draw it: {n, first, end, event}: how many sets,
        the first one's day, and what it ends with (its exam, or its last day)."""
        if not dates:
            return None
        end = P.path_end(doc) or {}
        when = P.fmt_day(end.get("day")) if end.get("day") else ""
        return {"n": len(dates), "first": P.fmt_day(dates[0].get("opens")), "event": bool(end.get("event")),
                "end": (f"{end.get('name') or 'Exam'} · {when}" if end.get("event") else f"Ends {when}" if when else "")}

    @staticmethod
    def _part_sub(p):
        if p.get("chapters"):
            return _pl(int(p["chapters"]), "chapter")
        return "questions" if p.get("questions") else ""

    @staticmethod
    def _when(u):
        a, b = u.get("opens"), u.get("due")
        if not b or b == a:
            return P.fmt_day(a)
        return f"{P.fmt_day(a)} – {P.fmt_day(b)}"

    def _resource_doc(self, idx, tree):
        st = self.new
        name = st["name"].strip() or None
        by = st["by"] if st["pace"] == "by" else None
        return E.resource_plan(idx, tree, st["res"], st["starts"], days=tuple(st["days"]),
                               daily=None if by else int(st["daily"] or DAILY), by=by, only=st["only"],
                               deck=self._new_deck_name() or None, name=name,
                               exam=(st["end_name"].strip() or None) if by else None)

    # ---- clicks ----

    def c_new_plan(self, finish_by=None, exam=None, start=None):
        if not self.busy:
            self.new_open(finish_by, exam, start)

    def c_new_step(self, step):
        if self.new is not None and step in STEPS and not self.new["busy"]:
            self.new["step"], self.new["said"] = step, ""
            self.push()

    def c_new_cancel(self):
        if self.new is None or self.new["busy"]:
            return
        self.new = None
        if not self.plans:
            self.close()
            return
        self.push()

    def c_new_set(self, key, value=None):
        st = self.new
        if st is None or st["busy"]:
            return
        if key == "deck":
            if any(d == value for d, _n, _c in st["decks"]):
                st["deck"], st["res"], st["only"] = value, None, None
        elif key in ("name", "end_name", "code"):
            st[key] = " ".join(str(value or "").split())[:60 if key != "code" else 40]
        elif key in ("end_day", "by", "starts"):
            got = _iso(value)
            if got and got >= str(self.ops.today()):
                st[key] = got
        elif key == "lesson" and value in ("deck", "own"):
            st["lesson"] = value
        elif key == "res":
            _idx, _tree, parts = self._new_ctx()
            if any(p["path"] == value for p in parts):
                st["res"], st["only"] = value, None
        elif key == "only":
            st["only"] = str(value) if value else None
        elif key == "pace" and value in PACES:
            st["pace"] = value
        elif key == "daily":
            try:
                st["daily"] = max(1, min(500, int(value)))
            except (TypeError, ValueError):
                pass
        elif key == "day":
            try:
                i = int(value)
            except (TypeError, ValueError):
                return
            if 0 <= i < 7 and (not st["days"][i] or sum(st["days"]) > 1):
                st["days"][i] = 0 if st["days"][i] else 1
        else:
            return
        st["said"] = ""
        self.push()

    def c_new_library(self):
        self.ops.open_page("/library")

    def c_new_follow(self, code=None):
        code = " ".join(str(code if code is not None else (self.new or {}).get("code") or "").split())
        if code:
            self.ops.follow_code(code)

    def _new_doc(self):
        """(name, doc, words) as Make would make it."""
        st = self.new
        if st["step"] == "resource":
            idx, tree, _parts = self._new_ctx()
            doc, sm = self._resource_doc(idx, tree)
            name = st["name"].strip() or M.resource_name(st["res"], st["only"])
            n = int(sm.get("lessons") or len(sm.get("dates") or []))
            words = (f"{_pl(n, 'set')} from {M.label(st['res'])}, {int(sm.get('new') or 0):,} new, "
                     f"{P.fmt_day(sm['first'])} to {P.fmt_day(sm['last'])}. ") if n else ""
            return name, doc, words
        name = st["name"].strip()
        end_name = st["end_name"].strip()
        doc, _uids = E.new_plan_doc(self._new_deck_name(), [], end_name, st["end_day"])
        words = ("An empty plan that ends with " + (f"{end_name}, " if end_name else "") + f"{P.fmt_day(doc['end'])}. "
                 if doc.get("end") else "An empty plan. ")
        return name, doc, words

    def c_new_make(self, start=False, sure=False):
        st = self.new
        if st is None or st["busy"] or st["deck"] is None:
            return
        try:
            name, doc, words = self._new_doc()
        except E.Refused as e:
            st["said"] = str(e)
            self.push()
            return
        if not name:
            return
        start = bool(start)
        if not sure and st["made"] is None:
            tail = ("It starts in your Anki" + (" as its own deck each day. " if st["lesson"] == "own" else ". ")
                    if start else "It's yours to start when you like. ")
            self.ask(f"Make {name}?", words + tail + "Nobody else sees it till you share its code.",
                     "Start it" if start else "Make it", "new_make", {"start": start})
            return
        st["busy"], st["said"] = True, "Making it…"
        self.push()
        self.ops.make(self, name, doc, lambda got: self._new_made(got, start, name), pid=st["made"])

    def _new_made(self, got, start, name):
        st = self.new
        if st is None:
            return
        st["busy"] = False
        if not got:
            st["said"] = "That didn't make it: check your connection, then try again."
            self.push()
            return
        if got[0] == "made":
            st["made"] = got[1]
            st["said"] = f"The plan is on duecrew.com, but its sets didn't save. {got[2]} Make tries them again, on it."
            self.push()
            return
        outcome, raw = got
        if outcome != "saved":
            st["said"] = str(raw)
            self.push()
            return
        pid = raw.get("id")
        empty = st["step"] != "resource"
        own = "ready" if st["step"] == "resource" and st["pace"] == "ready" else None
        lesson_deck = st["lesson"] == "own"
        did = st["deck"]
        self.plans = [p for p in self.plans if p.get("id") != pid] + [{
            "id": pid, "name": raw.get("name") or name, "role": "owner", "followers": 0, "code": raw.get("code")}]
        self.new = None

        def opened(_ok=None):
            self.pid, self.tab, self.picked = pid, "plan", None
            self.side = "panel"
            self._lay_out_next = empty  # an empty plan: the deck beside it, to tick what it covers
            self.load(pid)
        if start:
            self._status = "Starting it…"
            self.push()
            self.ops.start_own(self, raw, did, own, lesson_deck, opened)
        else:
            opened()

    # an empty plan's first look: the deck beside it (plan_shown asks)
    _lay_out_next = False

    def new_loaded(self):
        """After a load: an empty plan just made opens on the deck, to lay it out."""
        if self._lay_out_next and self.author() and self.deck_tree() is not None:
            self._lay_out_next = False
            self.deck.target = None
            self.side = "deck"
