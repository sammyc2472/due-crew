"""The HTML plan window's face (web.py is its Qt shell): the core's
hooks, the view it draws (webmodel's, put together), and what each click
on the page does. Qt-free: a dialog that isn't HTML yet is opened lazily
by the one click that needs it, so tests and the preview drive this
without Anki. Names are the authors' and the deck's: the page sets them
as text, never as markup."""

import json

from .. import plans as P
from . import build as B
from . import edits as E
from . import model as M
from . import view as V
from . import webmodel as WM
from .core import PlanCore
from .webnew import NewPlan

PREFIX = "dcplan:"
TABS = {"insights": "insights", "settings": "settings", "sharing": "settings", "mine": "settings"}


class _Said:
    """win.status, as the Qt dialogs this window still opens use it."""

    def __init__(self, win):
        self.win = win

    def setText(self, text):  # noqa: N802 (Qt's name)
        self.win.say(text)

    def text(self):
        return self.win._status


class WebFace(NewPlan, PlanCore):
    """The window's state and clicks. A shell sets eval_js (the page's
    script, run) and calls web_init."""

    def web_init(self, col, plans, ops, select=None, tab=None, cfg=None, new=None):
        self.core_init(col, plans, ops)
        self.cfg = cfg or {}
        self.status = _Said(self)
        self._status = ""
        self.pid = None
        self.tab = TABS.get(tab or "", "plan")
        self.picked = None
        self.side = "panel"            # the picked one's panel, or the deck beside the plan
        self.deck = WM.DeckState()
        self.notes, self.notes_of = [], None
        self._plan_cache = (None, None)
        self._ver = 0
        self._ready = False
        if self.plans:
            self.pid = select if any(p["id"] == select for p in self.plans) else self.plans[0]["id"]
        if new is not None or not self.plans:
            self.new_open(**{k: v for k, v in (new or {}).items() if k in ("finish_by", "exam", "start")})

    def eval_js(self, js):
        """The page's script, run (the shell's)."""
        raise NotImplementedError

    def alive(self):
        return getattr(self, "_alive", True)

    def close(self):
        """The window, shut (the shell's: QDialog.close)."""
        self._closed = True

    # ---- the core's hooks ----

    def current_pid(self):
        return self.pid

    def say(self, text):
        self._status = str(text or "")
        self.push(status_only=True)

    def busy_shown(self):
        self.push()

    def plan_shown(self):
        self._ver += 1
        self.deck.reset((self.plan or {}).get("id"), self.doc)
        if self.doc is not None:
            keep, self.keep = self.keep, None
            if keep == ("gone",):
                self.picked = None
            elif keep is not None:
                self.picked = tuple(keep)
            if self.picked and not self._exists(self.picked):
                self.picked = None
            if self.picked is None:
                u, _now = V.today_date(self.doc, self.ops.today())
                us = P.units(self.doc)
                u = u or (sorted(us, key=lambda x: str(x.get("opens")))[-1] if us else None)
                self.picked = ("date", u["id"]) if u else None
            self._read_notes()
            self.new_loaded()
        if self.tab == "settings" and not self.author() and self.doc is None:
            self.tab = "plan"
        self.push()

    def doc_shown(self):
        self.plan_shown()

    def undo_shown(self):
        self.push()

    def picked_key(self):
        return self.picked

    def forget_notes(self):
        self.notes_of = None

    def _exists(self, key):
        kind, k = key[0], key[1] if len(key) > 1 else None
        return {"date": self.unit, "event": self.event_of, "review": self.review_of}.get(kind, lambda _k: None)(k) is not None

    # ---- the view ----

    def view(self, status_only=False):
        st = {"head": WM.head(self), "status": self._status, "tab": self.tab, "picked": list(self.picked) if self.picked else None,
              "side": self.side}
        if status_only:
            return st
        if self.doc is not None:
            if self._plan_cache[0] != self._ver:
                self._plan_cache = (self._ver, WM.plan_tab(self))
            st["plan"] = self._plan_cache[1]
            st["panel"] = WM.panel(self, self.picked)
            if st["panel"].get("kind") == "date":
                st["panel"]["notes"] = self._notes_view(self.note_day(st["panel"]["uid"], st["panel"]["opens"]),
                                                        st["panel"]["opens"])
            if self.side == "deck" and self.author():
                st["deck"] = WM.deck_panel(self, self.deck)
            if self.tab == "insights":
                st["insights"] = self._insights()
            elif self.tab == "settings":
                st["settings"] = self._settings()
        else:
            st["plan"] = None
            st["welcome"] = not self.plans and self.new is None
        if self.new is not None:
            st["new"] = self.new_view()
        return st

    def push(self, status_only=False):
        """The page, drawn again from the view (status_only: the status line alone)."""
        if not self._ready or not self.alive():
            return
        try:
            data = self.view(status_only)
        except Exception:
            import traceback
            traceback.print_exc()
            data = {"status": "Something went wrong drawing the plan. Close the window and open it again."}
            status_only = True
        self.eval_js(f"dcPlan.{'status' if status_only else 'show'}({json.dumps(data, ensure_ascii=True)})")

    def sheet(self, sheet):
        """A question or a form in the page: {title, words, fields, yes, cmd, args, danger}."""
        self.eval_js(f"dcPlan.sheet({json.dumps(sheet, ensure_ascii=True)})")

    def ask(self, title, words, yes, cmd, args=None, danger=False):
        """Sure? A sheet; its yes sends cmd with args and sure=true."""
        self.sheet({"title": title, "words": words, "yes": yes, "danger": danger, "cmd": cmd,
                    "args": dict(args or {}, sure=True)})

    # ---- the page's clicks ----

    def _on_cmd(self, msg):
        if not isinstance(msg, str) or not msg.startswith(PREFIX):
            return
        try:
            data = json.loads(msg[len(PREFIX):])
        except ValueError:
            return
        if not isinstance(data, dict):
            return
        name = str(data.get("c") or "")
        fn = getattr(self, "c_" + name, None) if name.replace("_", "").isalnum() else None
        if fn is None:
            return
        args = data.get("a") if isinstance(data.get("a"), dict) else {}
        try:
            fn(**args)
        except TypeError:
            import traceback
            traceback.print_exc()
        except E.Refused as e:
            self.say(str(e))

    # -- the window --

    def c_ready(self):
        self.push()

    def c_pick_plan(self, pid):
        if self.new is not None and not self.new["busy"] and any(p["id"] == pid for p in self.plans):
            self.new = None
            if pid == self.pid and self.plan is not None:
                self.push()
                return
        if pid != self.pid and any(p["id"] == pid for p in self.plans) and not self.busy:
            self.pid, self.picked, self.side = pid, None, "panel"
            self.load(pid)
        elif pid == self.pid and self.plan is None and not self.busy:
            self.load(pid)  # the same plan again after a load that failed

    def c_tab(self, tab):
        if tab in ("plan", "insights", "settings"):
            self.tab = tab
            self.push()

    def c_close(self):
        self.close()

    def c_follow_plan(self):
        self.ops.follow_plan()

    # -- Undo, and the changes waiting --

    def c_undo(self, what):
        if not isinstance(what, list) or not what:
            return
        if what[0] == "take" and len(what) > 1:
            self.take_change(int(what[1]))
        elif what[0] == "undo":
            self.undo()
        elif what[0] == "history":
            self.c_tabcmd("history")  # a sheet in the page (webtabs)

    def c_undo_key(self):
        if not self.undo_key():
            self.eval_js("dcPlan.openUndo()")

    def c_discard(self, sure=False):
        if not self.draft or not len(self.draft):
            return
        if not sure:
            n = len(self.draft)
            self.ask(f"Discard {n:,} change{'s' if n != 1 else ''}?", "They were never sent: nobody saw them.",
                     "Discard", "discard", danger=True)
            return
        self.discard()

    def c_review_send(self):
        if not self.draft or not len(self.draft) or self.busy:
            return
        self.sheet(self._send_view())

    def _send_view(self):
        from . import ops as O
        _doc, changes, _dropped = self.draft.replay(self.ctx())
        rows = []
        for i, c in enumerate(changes):
            for j, x in enumerate(c["entries"]):
                rows.append({"i": i if j == 0 else None, "verb": str(x["verb"]).capitalize(), "what": x["what"],
                             "detail": x.get("detail") or "", "who": x.get("who") or "",
                             "warn": str(x.get("who") or "").startswith("Open since"),
                             "ai": bool(j == 0 and c["op"].get("by") == "ai")})
        n, f = len(self.draft), self.followers()
        return {"kind": "send", "title": (f"Send {n:,} change{'s' if n != 1 else ''} to {f:,} following" if f
                                          else f"Save {n:,} change{'s' if n != 1 else ''}"),
                "rows": rows, "why": O.send_line(changes), "max": O.WHY_MAX, "yes": f"Send to {f:,}" if f else "Save"}

    def c_take_change(self, i, again=False):
        self.take_change(int(i))
        if again and self.draft and len(self.draft):
            self.sheet(self._send_view())

    def c_send(self, why=""):
        self.send(str(why or ""))

    # -- picking --

    def c_pick(self, key):
        if not isinstance(key, list) or len(key) < 2:
            return
        self.picked = tuple(key)
        if self.side == "deck":
            if key[0] == "date" and self.deck.target:
                self.deck.target = key[1]
            elif key[0] != "date":
                self.side = "panel"
        self.push()

    # -- a lesson --

    def _u(self, uid):
        u = self.unit(uid)
        if u is None:
            self.say("That set isn't on the plan now.")
        return u

    def _day_taken(self, day, uid=None):
        """The lesson already on that day, if another."""
        return next((x for x in P.units(self.doc) if x.get("opens") == day and x.get("id") != uid), None)

    def c_rename(self, uid, name):
        u = self._u(uid)
        name = " ".join(str(name or "").split())[:60]
        if u is not None and name and name != u.get("name"):
            self.change({"op": "rename", "date": uid, "name": name})

    def c_move(self, uid, to, sure=False):
        u = self._u(uid)
        if u is None or not to or to == u["opens"]:
            return
        other = self._day_taken(to, uid)
        if other is not None and not sure:
            self.ask(f"{P.fmt_day(to)} has {other.get('name') or 'a set'} already",
                     "Put this one on that day too? Followers see both.", "Put it on", "move", {"uid": uid, "to": to})
            self.push()  # the day it was, back in its box
            return
        self.change({"op": "move", "date": uid, "to": to}, keep=("date", uid))

    def c_set_due(self, uid, due):
        u = self._u(uid)
        if u is None:
            return
        due = due or None
        if due and due < u["opens"]:
            due = None
        if due != (u.get("due") or None):
            self.change({"op": "set_due", "date": uid, "due": due})

    def c_set_for(self, uid, eid):
        u = self._u(uid)
        if u is None:
            return
        if eid == "new":
            self.c_new_event_form(for_uid=uid)
            return
        if (eid or None) != u.get("for"):
            self.change({"op": "set_for", "date": uid, "event": eid or None})

    def c_nudge(self, k):
        if not self.author() or not self.picked:
            return
        k = 1 if int(k) > 0 else -1
        if self.picked[0] == "date":
            u = self.unit(self.picked[1])
            if u is not None:
                self.c_move(u["id"], E._later(u["opens"], k))
        elif self.picked[0] == "event":
            e = self.event_of(self.picked[1])
            if e is not None:
                self.change({"op": "move_event", "event": e["id"], "to": E._later(e["day"], k)}, keep=("event", e["id"]))

    def c_op(self, op, keep=None):
        if isinstance(op, dict) and op.get("op"):
            self.change(op, keep=tuple(keep) if isinstance(keep, list) else keep)

    def c_spread(self, key):
        """Spread… (was Split) on a tag or a subdeck of the picked lesson: by its tags, or evenly over N study days."""
        from . import date_dialogs as DD
        u = self.unit(self.picked[1]) if self.picked and self.picked[0] == "date" else None
        t = self.deck_tree()
        if u is None or t is None or not isinstance(key, list) or len(key) < 2 or key[0] not in ("tag", "deck"):
            return
        field, path = ("tags" if key[0] == "tag" else "decks"), key[1]
        tk = f"{key[0]}:{path}"
        placed = B.placed_keys(self.doc, t)
        others = placed - {tk}
        kids = [k for k in t.kids(tk) if not B.is_placed(k, others) and B.eff(t, k, others) > 0] if not self.swap else []
        total = B.eff(t, tk, others) or len(self.idx.match(u, self.swap, self.doc))
        pace = (self.doc.get("pace") or {})
        cap = 0 if pace.get("mode") == "placed" else max(1, int(pace.get("daily") or 20))
        days = pace.get("days") or [1] * 7
        rest = t.only(tk) if kids else 0
        parts = " · ".join(f"{B.tag_word(B.path_of(k).split('::')[-1])} {B.eff(t, k, others):,}" for k in kids[:6])
        if len(kids) > 6:
            parts += f" · {len(kids) - 6} more"
        if kids and rest > 0:
            parts += f" · the rest {rest:,}"
        dlg = DD.SplitDialog(self, B.tag_word(path.split("::")[-1]), total, parts, cap, -(-total // cap) if cap else 3)
        if not dlg.exec():
            return
        how = dlg.value()
        if how[0] == "even":
            dd = B._Days(self.doc, days)
            ds, d = [], dd.first(u["opens"])
            while len(ds) < how[1]:
                ds.append(d)
                d = dd.next(d)
            self.change({"op": "split_even", "date": u["id"], "source": [key[0], path], "days": ds})
            return
        items = [{"key": k, "n": B.eff(t, k, others)} for k in kids]
        if rest > 0:
            items.append({"key": tk, "n": rest, "rest": True, "even": bool(cap) and rest > cap})
        self.change({"op": "split_tags", "date": u["id"], "field": field, "path": path, "items": items,
                     "cap": cap, "days": days})

    def c_spread_heavy(self, kind, path, uid):
        self.picked = ("date", uid)
        self.c_spread([kind, path])

    def c_set_cut(self, tag, ptag=None):
        if self.picked and self.picked[0] == "date":
            self.change({"op": "set_cut", "date": self.picked[1], "tag": tag, "ptag": ptag})

    def c_keep_only(self, ptag):
        u = self.unit(self.picked[1]) if self.picked and self.picked[0] == "date" else None
        if u is None:
            return
        ops = [{"op": "set_cut", "date": u["id"], "tag": r["key"][1], "ptag": ptag}
               for r in self.rows(u) if r["key"][0] == "tag" and not WM.own_tag(self.doc, r["key"][1])]
        if ops:
            self.changes(ops)

    def c_remark(self, path, text=None):
        had = next((r for r in self.doc.get("remarks") or [] if isinstance(r, dict) and r.get("tag")
                    and str(r["tag"]).lower() == str(path).lower()), None)
        if text is None:
            self.sheet({"title": "A note for followers", "words": f"On {M.label(path)}, shown in their Anki when it comes up. "
                        "Empty takes it off.", "fields": [{"name": "text", "value": str((had or {}).get("text") or ""), "max": 280}],
                        "yes": "Save the note", "cmd": "remark", "args": {"path": path}})
            return
        self.change({"op": "set_tag_remark", "tag": path, "text": " ".join(str(text).split())})

    def copy(self, text):
        """The clipboard (the shell's)."""

    def save_file(self, name, text):
        """A file the person saves where they pick (the shell's: a save
        dialog); True once it's written."""
        self._saved_file = (name, text)
        return True

    def c_calendar(self):
        """Add to my calendar: the plan's sets, quizzes and exams and review
        days as an .ics file (ics.py), mine as I run it when I follow it."""
        if self.doc is None:
            return
        from . import ics
        counts = {}
        if self.idx is not None:
            for u in P.units(self.doc):
                rows = self.rows(u)
                counts[u["id"]] = len(set().union(*[set(r["cids"]) for r in rows])) if rows else 0
        skipped = [] if self.author() else list((self.plan or {}).get("skipped") or [])
        name = self.plan_name()
        text = ics.calendar((self.plan or {}).get("id") or "plan", name, self.doc, counts, skipped)
        if self.save_file(ics.file_name(name), text):
            self.say("Saved. Open the file to add the plan to your calendar.")

    def _copy(self, text, said):
        self.copy(text)
        self.say(said)

    def _source(self, i):
        """(lesson, its i'th source's key) of the picked lesson, or (None, None)."""
        u = self.unit(self.picked[1]) if self.picked and self.picked[0] == "date" else None
        rows = self.rows(u) if u else []
        try:
            i = int(i)
        except (TypeError, ValueError):
            return None, None
        return (u, rows[i]["key"]) if 0 <= i < len(rows) else (None, None)

    def c_move_source_form(self, i, day=None):
        """Move to › Another day…: a day's first lesson takes it, or a new one there."""
        u, key = self._source(i)
        if u is None:
            return
        if day is None:
            self.sheet({"title": "Move it to a day", "words": "That day's set takes it, or it gets a set of its own there.",
                        "fields": [{"name": "day", "type": "date", "value": u.get("opens") or ""}], "yes": "Move it",
                        "cmd": "move_source_form", "args": {"i": i}})
            return
        day = str(day or "")
        if len(day) == 10 and day != u.get("opens"):
            self.change({"op": "move_source", "date": u["id"], "key": list(key), "day": day})

    def c_copy_source(self, i):
        u, key = self._source(i)
        if u is None:
            return
        q = M.source_search(u, list(key), self.swap)
        if not q:
            self.say("Its cards are picked one by one: Show in Browse finds them.")
            return
        self._copy(q, "Copied: its search, for Anki's Browse.")

    def c_copy_search(self):
        u = self.unit(self.picked[1]) if self.picked and self.picked[0] == "date" else None
        if u is None:
            return
        parts = [B.anki_search("tag", t) for t in u.get("tags") or []] + [B.anki_search("deck", d) for d in u.get("decks") or []]
        parts += [f"({q})" for q in u.get("search") or []]
        if not parts:
            self.say("Its cards are picked one by one: Show in Browse finds them.")
            return
        self._copy(" OR ".join(parts) if len(parts) > 1 else parts[0], "Copied: its search, for Anki's Browse.")

    def c_open_now(self):
        u = self.unit(self.picked[1]) if self.picked and self.picked[0] == "date" else None
        if u is not None:
            cids = None if self.own_steps() else (self.idx.match(u, self.swap, self.doc) if self.idx else set())
            self.open_date(u["id"], cids, str(u.get("name") or ""))

    def c_delete(self, sure=False):
        if not self.author() or not self.picked:
            return
        kind, key = self.picked[0], self.picked[1]
        if kind == "date":
            u = self.unit(key)
            if u is None:
                return
            if not sure:
                opened = str(u["opens"]) <= self.ops.today()
                self.ask(f"Delete {P.fmt_day(u['opens'])} · {u.get('name') or '?'}?",
                         ("It comes off the plan. What opened stays open." if opened else "It comes off the plan.")
                         + (" With people following, it waits with your other changes till you send them." if self.waiting() else ""),
                         "Delete", "delete", danger=True)
                return
            self.change({"op": "delete_date", "date": key}, keep=("gone",))
        elif kind == "event":
            e = self.event_of(key)
            if e is None:
                return
            if not sure:
                n = len(V.prep(self.doc, e))
                self.ask(f"Take {e.get('name') or 'it'} off?",
                         f"{n:,} set{'s' if n != 1 else ''} lead up to it; they stay, leading up to nothing." if n
                         else "It comes off the plan.", "Take it off", "delete", danger=True)
                return
            self.change({"op": "take_event", "event": key}, keep=("gone",))
        elif kind == "review":
            self.change({"op": "take_review", "day": key}, keep=("gone",))

    def c_move_from(self):
        from .date_panel import MoveFromDialog
        u = self.unit(self.picked[1]) if self.picked and self.picked[0] == "date" else None
        if u is None:
            return
        after = sum(1 for x in P.units(self.doc) if str(x.get("opens")) > str(u["opens"]))
        dlg = MoveFromDialog(self, u.get("name") or "this set", after)
        if dlg.exec():
            self.change({"op": "move_from", "date": u["id"], "days": dlg.days()})

    def c_add_search(self):
        from . import date_dialogs as DD
        u = self.unit(self.picked[1]) if self.picked and self.picked[0] == "date" else None
        idx = self.idx
        if u is None:
            return

        def peek(q):
            if idx is None:
                return None
            try:
                return sum(1 for c in idx.col.find_cards(str(q)) if int(c) in idx.cards)
            except Exception:
                return 0
        dlg = DD.AddCardsDialog(self, f"Add cards to {P.fmt_day(u['opens'])}", peek)
        if not dlg.exec():
            return
        what = dlg.what()
        if not what:
            return
        kind, x = what
        if kind == "search":
            n = len(idx.search_cards(x)) if idx is not None else None
            self.change({"op": "add_search", "date": u["id"], "q": x, "n": n})
        elif kind in ("nids", "cids"):
            self.change({"op": "add_ids", "date": u["id"], "kind": kind, "ids": list(x)})
        else:
            self.change({"op": "add_picks", "date": u["id"], "notes": list(x["notes"]), "cards": [list(c) for c in x["cards"]]})

    def c_todo(self):
        from . import date_dialogs as DD
        u = self.unit(self.picked[1]) if self.picked and self.picked[0] == "date" else None
        if u is None:
            return
        dlg = DD.LinesDialog(self, f"To do on {P.fmt_day(u['opens'])}", u.get("todo") or [])
        if dlg.exec():
            self.change({"op": "set_todo", "date": u["id"], "lines": dlg.lines()})

    def c_todo_off(self, i):
        u = self.unit(self.picked[1]) if self.picked and self.picked[0] == "date" else None
        if u is None:
            return
        lines = [x for x in u.get("todo") or [] if isinstance(x, dict)]
        if 0 <= int(i) < len(lines):
            self.change({"op": "set_todo", "date": u["id"], "lines": [y for j, y in enumerate(lines) if j != int(i)]})

    def c_browse(self, key=None, i=None):
        """Show in Browse: a source's cards (i), a lesson's (key), or the picked lesson's."""
        if self.idx is None:
            return
        key = tuple(key) if isinstance(key, list) else self.picked
        u = self.unit(key[1]) if key and key[0] == "date" else None
        if u is None:
            return
        if i is not None:
            rows = self.rows(u)
            cids = set(rows[int(i)]["cids"]) if 0 <= int(i) < len(rows) else set()
        else:
            cids = self.idx.match(u, self.swap, self.doc)
        if cids:
            self.ops.browse(cids)

    def c_study(self, kind, key=None):
        if kind == "today":
            u = self.unit(key)
            if u is None:
                return
            if self.own_steps():
                self.study("date", u["id"])
            else:
                self.study("date", u["id"], self.idx.match(u, self.swap, self.doc) if self.idx else set(), str(u.get("name") or "today"))
        elif kind == "behind":
            cids = set()
            for uid in key or []:
                u = self.unit(uid)
                if u is not None and self.idx is not None:
                    cids |= self.idx.match(u, self.swap, self.doc)
            self.study("behind", None, cids, "what's behind")
        elif kind == "date" and key:
            u = self.unit(key)
            if u is not None:
                self.study("date", key, None if self.own_steps() else (self.idx.match(u, self.swap, self.doc) if self.idx else set()),
                           str(u.get("name") or ""))

    def study(self, kind, key, cids=None, name=""):
        if PlanCore.study(self, kind, key, cids, name):
            self.close()  # Anki's Study screen is on it; the window would sit over it

    # -- new lessons, quizzes, review days --

    def _after_picked(self):
        u = self.unit(self.picked[1]) if self.picked and self.picked[0] == "date" else None
        dd = B._Days(self.doc, V.pace_of(self.doc).get("days") or [1] * 7)
        if u is not None:
            return dd.next(u["opens"])
        ld = B.last_day(self.doc)
        return dd.first(E._later(ld, 1) if ld else self.ops.today())

    def c_new_date_form(self):
        if not self.author():
            return
        self.sheet({"title": "A new set", "words": "Its name as followers see it, and the day its cards open.",
                    "fields": [{"name": "name", "label": "Name", "value": "", "max": 60},
                               {"name": "day", "label": "Opens", "type": "date", "value": self._after_picked()}],
                    "yes": "Put it on", "cmd": "new_date"})

    def c_new_date(self, name="", day="", sure=False):
        name = " ".join(str(name or "").split())[:60]
        if not name or not day:
            return
        other = self._day_taken(day)
        if other is not None and not sure:
            self.ask(f"{P.fmt_day(day)} has {other.get('name') or 'a set'} already",
                     "Put this one on that day too? Followers see both.", "Put it on", "new_date", {"name": name, "day": day})
            return
        self.change({"op": "add_date", "day": day, "name": name}, keep="made")

    def c_new_event_form(self, for_uid=None):
        if not self.author():
            return
        u = self.unit(for_uid) if for_uid else None
        start = E._later(u["opens"], 3) if u else self._after_picked()
        self.sheet({"title": "A quiz, exam or day", "words": "Sets before it can lead up to it.",
                    "fields": [{"name": "name", "label": "Name", "value": "", "max": 60,
                                "hint": "Cardio quiz 1, Block 2 exam, a lecture"},
                               {"name": "day", "label": "Day", "type": "date", "value": start}],
                    "yes": "Put it on", "cmd": "new_event", "args": {"for_uid": for_uid}})

    def c_new_event(self, name="", day="", for_uid=None):
        name = " ".join(str(name or "").split())[:60]
        if not name or not day:
            return
        ops = [{"op": "add_event", "day": day, "name": name}]
        if for_uid:
            ops.append({"op": "set_for", "date": for_uid, "event": f"{day} {name}"})
        self.changes(ops, keep=("date", for_uid) if for_uid else None)

    def c_rename_event(self, eid, name):
        e = self.event_of(eid)
        name = " ".join(str(name or "").split())[:60]
        if e is not None and name and name != e.get("name"):
            self.change({"op": "rename_event", "event": eid, "name": name})

    def c_move_event(self, eid, to):
        e = self.event_of(eid)
        if e is not None and to and to != e.get("day"):
            self.change({"op": "move_event", "event": eid, "to": to}, keep=("event", eid))

    def c_new_review_form(self):
        if not self.author():
            return
        self.sheet({"title": "A review day", "words": "The morning followers get a deck of what they've seen so far.",
                    "fields": [{"name": "day", "label": "Day", "type": "date", "value": self._after_picked()}],
                    "yes": "Next", "cmd": "review_day"})

    def c_review_day(self, day):
        from . import date_dialogs as DD
        before = [u for u in sorted(P.units(self.doc), key=lambda x: str(x.get("opens") or "")) if str(u["opens"]) <= day]
        if not before:
            self.say("A review day comes after the sets it reviews: none open by then.")
            return
        r = self.review_of(day)
        dlg = DD.ReviewDialog(self, f"Review day · {P.fmt_day(day)}", [(u["id"], M.date_label(u)) for u in before],
                              (r.get("from"), r.get("to")) if r else None)
        if not dlg.exec():
            return
        v = dlg.value()
        if v[0] == "off":
            self.change({"op": "take_review", "day": day}, keep=("gone",))
        else:
            self.change({"op": "set_review", "day": day, "from": v[1], "to": v[2]}, keep=("review", day))

    # -- the deck beside the plan --

    def c_deck(self, uid=None):
        """Add from the deck (uid: the lesson ticks add to) or Lay out from the deck (none)."""
        if not self.author() or self.deck_tree() is None:
            return
        if uid:
            self.picked = ("date", uid)
        self.deck.target = uid or None
        self.side = "deck"
        self.push()

    def c_deck_done(self):
        uid = self.deck.target
        self.deck.target = None
        self.side = "panel"
        if uid:
            self.picked = ("date", uid)
        self.push()

    def c_deck_view(self, view):
        if view in dict(WM.VIEWS):
            self.deck.view = view
            self.push()

    def c_deck_find(self, text):
        self.deck.find = str(text or "")[:80]
        self.push()

    def c_deck_open(self, key, on=True):
        (self.deck.opened.add if on else self.deck.opened.discard)(key)
        self.push()

    def c_deck_tick(self, key, on):
        if self.busy or not key:
            return
        st = self.deck
        if st.target:
            u = self.unit(st.target)
            if u is None:
                return
            kind, path = B.kind_of(key), B.path_of(key)
            if on:
                tags, decks = ([path], []) if kind == "tag" else ([], [path])
                if self.swap:
                    tags = [P.swapped(x, (self.swap[1], self.swap[0])) for x in tags]
                self.change({"op": "add_cards", "date": u["id"], "tags": tags, "decks": decks}, keep=("date", u["id"]))
            else:
                self.change({"op": "take_cards", "date": u["id"], "key": [kind, path]}, keep=("date", u["id"]))
            return
        st.cover = B.toggle(st.cover, self.deck_tree(), key, st.view, st.kinds)
        st.dirty = True
        self.push()

    def c_deck_lay(self, how, upto=None):
        """Lay them out (how: [mode, next week only, [end, aim] or None]); upto: before that quiz or exam."""
        if not isinstance(how, list) or len(how) < 3 or self.busy:
            return
        mode, week_ahead, fitting = how
        pace = V.pace_of(self.doc)
        o = {"op": "lay_out", "pace": {"mode": mode, "days": pace.get("days") or [1] * 7, "daily": int(pace.get("daily") or 20)},
             "cover": sorted(self.deck.cover), "start": B.plan_start(self.doc, B.next_monday(self.ops.today())),
             "week_ahead": bool(week_ahead)}
        if fitting:
            o["end"], o["aim"] = fitting[0], fitting[1]
        if upto:
            o["upto"] = str(upto)

        def done(ok):
            if ok:
                self.deck.dirty = False
        self.change(o, then=done)

    def c_lesson_from(self, key, day="next", sure=False):
        """A tag's or a subdeck's row › A lesson of its own: on the next free
        study day (day "next"), or a day asked for (day None: the form)."""
        if self.busy or not key or not self.author():
            return
        kind, path = B.kind_of(key), B.path_of(key)
        if kind not in ("tag", "deck"):
            return
        if day is None:
            self.sheet({"title": "A set of its own", "words": f"{M.label(path)}, on a day.",
                        "fields": [{"name": "day", "type": "date", "value": self.ops.today()}], "yes": "Add it",
                        "cmd": "lesson_from", "args": {"key": key}})
            return
        tags, decks = ([path], []) if kind == "tag" else ([], [path])
        if self.swap:
            tags = [P.swapped(x, (self.swap[1], self.swap[0])) for x in tags]
        self.change({"op": "add_date", "day": str(day), "tags": tags, "decks": decks, "today": self.ops.today()})

    def c_breather(self, sure=False):
        """Give everyone a day: every lesson still to come a study day later; quizzes and exams stay."""
        if self.busy or not self.author():
            return
        if not sure:
            ahead = sum(1 for u in P.units(self.doc or {}) if str(u.get("opens") or "") > self.ops.today())
            if not ahead:
                self.say("Nothing is still to come to move.")
                return
            self.ask("Give everyone a day?", f"The {ahead:,} set{'s' if ahead != 1 else ''} still to come move a study day later, "
                     "their finish-by days and review days with them. Quizzes and exams stay.", "Move them", "breather")
            return
        self.change({"op": "breather", "today": self.ops.today()})

    def c_deck_week(self):
        self.c_deck_lay(["daily", True, None])

    def c_deck_keep(self):
        pace = V.pace_of(self.doc)
        t = self.deck_tree()

        def done(ok):
            if ok:
                self.deck.dirty = False
                self.push()
        self.change({"op": "set_pace", "mode": pace.get("mode") or "daily", "days": pace.get("days") or [1] * 7,
                     "daily": pace.get("daily"), "cover": B.cover_items(t, self.deck.cover) if t is not None else sorted(self.deck.cover)},
                    then=done)

    def c_ptag_rename(self, ptag, name=None):
        t = next((x for x in P.plan_tags(self.doc) if x.get("id") == ptag), None)
        if t is None:
            return
        if name is None:
            self.sheet({"title": "Rename the tag", "words": "Its name (40 characters); the sets, searches and notes using it change with it.",
                        "fields": [{"name": "name", "value": str(t.get("name") or ""), "max": 40}], "yes": "Rename",
                        "cmd": "ptag_rename", "args": {"ptag": ptag}})
            return
        name = " ".join(str(name).split())
        if name and name != t.get("name"):
            self.change({"op": "rename_plan_tag", "tag": ptag, "name": name})

    def c_ptag_delete(self, ptag, sure=False):
        t = next((x for x in P.plan_tags(self.doc) if x.get("id") == ptag), None)
        if t is None:
            return
        if not sure:
            self.ask(f"Delete {t.get('name') or 'the tag'}?", E.drop_say(self.doc, ptag) + " Followers' Anki takes it off their notes.",
                     "Delete it", "ptag_delete", {"ptag": ptag}, danger=True)
            return
        self.change({"op": "delete_plan_tag", "tag": ptag})

    def c_card_note_off(self, rid):
        self.change({"op": "take_remark", "id": rid})

    # -- paste, the plan as text, AI prompts --

    def c_paste(self, text):
        """Plan lines pasted: the text's Add, shown before they go on. (A course
        calendar isn't read here yet: Sam, "not quite sure our calendar import is working".)"""
        from . import text as T
        text = str(text or "")
        if not text.strip() or self.doc is None:
            return
        r = T.from_text(self.doc, self.deck_tree(), text, whole=False,
                        start=B.plan_start(self.doc, B.next_monday(self.ops.today())),
                        plan_name=self.plan_name(), new_id=lambda: E.new_id(self.doc))
        if not r["errors"] and (r["units"] or r["events"] or r["tags"] or r["remarks"]):
            if self._text(False, text):
                self.eval_js("dcPlan.pasted()")
            return
        self.say(" ".join(r["errors"][:2]) if r["errors"] else
                 "Nothing in that reads as plan lines: a set's line starts with its day (2026-11-02 | Cell injury | tag:…).")

    def _text(self, whole, pasted=""):
        from .text_tab import TextDialog
        dlg = TextDialog(self, whole, pasted)
        ok = bool(dlg.exec())
        self.push()
        return ok

    def c_text(self):
        self._text(True)

    def _prompt_text(self, which):
        from . import prompts
        t = self.deck_tree()
        if t is None:
            self.say("The plan's deck isn't in this Anki: a prompt needs its tags.")
            return None
        if which == "plan":
            return prompts.for_plan(self.doc, t, self.plan_name(), B.plan_start(self.doc, B.next_monday(self.ops.today())),
                                    self.deck.cover or None)
        return prompts.for_tags(self.doc, t, self.plan_name())

    def c_prompt(self, which):
        text = self._prompt_text(which)
        if text:
            self._copy(text, "Copied. Paste it in your AI; paste what it answers in the box below, then Show the changes. "
                             "It has the deck's tag names and counts, never a card.")

    def c_see_prompt(self, which):
        text = self._prompt_text(which)
        if text:
            self.sheet({"kind": "read", "title": "The prompt, as your AI gets it", "text": text, "yes": "Copy it",
                        "cmd": "prompt", "args": {"which": which}})

    # ---- notes on a day ----

    def _read_notes(self):
        pid = (self.plan or {}).get("id")
        if not pid or self.notes_of == pid:
            return
        from . import remote
        self.notes, self.notes_of = [], None

        def done(got):
            if (self.plan or {}).get("id") != pid:
                return
            self.notes = got or []
            self.notes_of = pid if got is not None else None
            if got is None:
                self.say("Its notes didn't load. Close and open the window to try again.")
            self._ver += 1
            self.push()
        self.ops.ask(self, lambda cl: remote.notes(cl, pid), done)

    def _notes_view(self, day, shown=None):
        writes = self.notes_of is not None and not ((self.raw or {}).get("library") is True and not self.author())
        rows = sorted((x for x in self.notes if x.get("day") == day), key=lambda x: (str(x["day"]), x["id"]))
        return {"rows": [{"id": x["id"], "who": "You" if x.get("mine") else str(x.get("name") or "?"),
                          "text": str(x.get("text") or ""), "remove": bool(x.get("remove"))} for x in rows],
                "writes": writes, "day": day, "dayw": P.fmt_day(shown or day), "loading": self.notes_of is None}

    def note_days(self):
        return {x.get("day") for x in self.notes}

    def c_note_add(self, day, text):
        from . import remote
        text, pid = " ".join(str(text or "").split())[:280], self.notes_of
        if not text or not pid:
            return

        def done(got):
            if pid != self.notes_of:
                return
            if not got:
                self.say("That note didn't post. Try again.")
            elif got[0] != "saved":
                self.say(str(got[1]))
            else:
                self.notes.append({"id": got[1]["id"], "day": day, "text": str(got[1].get("text") or text),
                                   "name": "You", "mine": True, "remove": True})
                self._ver += 1
            self.push()
        self.ops.ask(self, lambda cl: remote.add_note(cl, pid, day, text), done)

    def c_note_off(self, nid):
        from . import remote
        pid = self.notes_of
        x = next((y for y in self.notes if y.get("id") == nid), None)
        if not x or not x.get("remove") or not pid:
            return

        def done(ok):
            if pid != self.notes_of:
                return
            if ok:
                self.notes = [y for y in self.notes if y is not x]
                self._ver += 1
            else:
                self.say("That note didn't go. Try again.")
            self.push()
        self.ops.ask(self, lambda cl: remote.remove_note(cl, pid, nid), done)

    # ---- Insights and Settings: the Qt tabs' work, drawn here ----

    def _insights(self):
        try:
            from . import webtabs
            return webtabs.insights(self)
        except ImportError:
            return {"todo": True}

    def _settings(self):
        try:
            from . import webtabs
            return webtabs.settings(self)
        except ImportError:
            return {"todo": True}

    def c_tabcmd(self, name, args=None, **more):
        """Insights' and Settings' own clicks (webtabs); a sheet's fields and sure come as more."""
        try:
            from . import webtabs
        except ImportError:
            return
        fn = getattr(webtabs, "c_" + str(name), None) if str(name).replace("_", "").isalnum() else None
        if fn is not None:
            fn(self, **dict(args if isinstance(args, dict) else {}, **more))

    # ---- from elsewhere ----

    def go_to_plan(self, pid, tab=None):
        if not any(p["id"] == pid for p in self.plans):
            return False
        if tab:
            self.tab = TABS.get(tab, "plan")
        if pid != self.pid:
            self.c_pick_plan(pid)
        else:
            self.push()
        return True
