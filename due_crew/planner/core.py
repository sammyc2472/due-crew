"""The plan windows' logic, Qt-free: a plan loaded (an author's own
dates, or mine as my follow moves them), the changes waiting under it
(draft.py), a save made at once when nobody follows, a send, Undo. The
Qt window (window.py) and the HTML window (web.py) are its two faces;
each says how it shows things through the hooks at the bottom.

Every change is an op (ops.py). With anyone following, it waits under
the plan, kept on this computer, till Review and send: one save with one
line to followers. With nobody following, it saves at once (PUT
/plans/{id}, the version it started from) and Undo takes it back."""

import json

from .. import plans as P
from .. import schedule as S
from ..backend.shapes import clean_plan
from . import build as B
from . import edits as E
from . import model as M
from . import ops as O


def whose(p):
    who = p.get("ownerName") if p.get("ownerName") not in (None, "", "?") else None  # the server's "?": a name it hasn't got
    if p.get("role") in ("owner", "editor"):
        return "yours" if p.get("role") == "owner" else (f"with {who}" if who else "a co-author")
    return f"{who}’s · following" if who else "following"


def others(p):
    """Who follows a plan besides me: an author studying their own plan
    (New plan's Start it) isn't someone its changes wait for."""
    n = int((p or {}).get("followers") or 0)
    return max(0, n - (1 if (p or {}).get("following") else 0))


def pick_label(p):
    bits = [str(p.get("name") or "Plan"), whose(p)]
    if p.get("role") in ("owner", "editor"):
        n = others(p)
        bits.append(f"{n:,} following" if n else "nobody following yet")
    return " · ".join(bits)


def sort_plans(plans):
    out = [p for p in plans or [] if isinstance(p, dict) and p.get("id")]
    out.sort(key=lambda p: (p.get("role") not in ("owner", "editor"), str(p.get("name") or "").lower()))
    return out


class PlanCore:
    """The state and steps of a plan window. A face sets col, ops, plans
    and calls core_init(); it implements the hooks below."""

    def core_init(self, col, plans, ops):
        self.col, self.ops = col, ops
        self.plans = sort_plans(plans)
        self.plan = self.raw = self.doc = self.idx = self.swap = self.draft = None
        self.how = ""
        self.keep = None          # what the Plan tab picks once a plan (re)loads
        self.busy = False
        self.undoable = None      # (plan id, version) a save of this window's made, while its Undo shows
        self.sent = None          # (when, how many changes) the last send, for Undo's first line
        self._rows = {}           # uid -> model.sources, for this plan's index and doc
        self._tree = None

    # ---- the hooks a face implements ----

    def current_pid(self):
        """The plan picked in the window (its id)."""
        raise NotImplementedError

    def say(self, text):
        """A line in the window's status."""
        raise NotImplementedError

    def busy_shown(self):
        """Busy changed (self.busy): controls enabled or not."""

    def plan_shown(self):
        """A plan (re)loaded or a load failed: every part drawn again, the tab wanted shown."""

    def doc_shown(self):
        """The doc changed here (a change waiting, or one taken out): every part drawn again."""

    def undo_shown(self):
        """Undo has something new (a save or a send of this window's)."""

    def picked_key(self):
        """What the Plan tab has picked: ("date", id) | ("event", id) | ("review", day) | None."""
        return None

    def label_changed(self, pid, plan):
        """The plan's line in the picker, with its name and followers now."""

    def forget_notes(self):
        """A plan (re)loads: its day notes are read again with it."""

    def ask_discard(self, n):
        """True to discard the n changes waiting (a face asks)."""
        return True

    def later(self, fn):
        """fn, once the event loop is free (an open's recount)."""
        fn()

    # ---- a plan ----

    def author(self):
        return bool(self.plan) and self.plan.get("role") in ("owner", "editor") and self.raw is not None

    def followers(self):
        return others(self.plan)

    def waiting(self):
        """Changes wait to be sent: someone follows it, or some wait already (an AI app's)."""
        return self.author() and (self.followers() > 0 or bool(self.draft and len(self.draft)))

    def plan_name(self):
        return str((self.plan or {}).get("name") or "")

    def ctx(self):
        return O.Ctx(self.deck_tree(), self.ops.today(), self.plan_name(), S.plan_days(self.doc or {}))

    def load(self, pid=None):
        pid = pid or self.current_pid()
        if not pid:
            return
        self._busy(True, "Loading the plan…")
        self.undoable = None
        self.forget_notes()
        self.ops.load(self, pid, lambda got: self._loaded(pid, got))

    def _loaded(self, pid, got, keep=None, saved=False):
        if pid != self.current_pid():
            return  # another plan was picked since
        self._busy(False, "")
        if not got:
            self.plan = self.raw = self.doc = self.idx = self.draft = None
            self._tree = None
            self.say("The plan didn't load: check your connection, then pick it again.")
            self.plan_shown()
            return
        raw, plan = got
        same = (saved and self.idx is not None and (self.plan or {}).get("id") == pid
                and str((self.doc or {}).get("deck") or "") == str((plan.get("doc") or {}).get("deck") or ""))
        if plan.get("role") in ("owner", "editor") and isinstance(raw, dict):
            mig = E.migrate_checks(raw.get("doc") or {})  # as the builder loads it: an old checkpoint, a review day
            if mig is not raw.get("doc"):
                raw, plan = dict(raw, doc=mig), dict(plan, doc=mig)
        fresh = (self.plan or {}).get("id") != pid
        self.plan = plan
        self.raw = raw if plan.get("role") in ("owner", "editor") else None
        # an author's view is the plan's own dates; a follower's, mine (as my follow moves them)
        self.doc = plan["doc"] if self.raw is not None else self.ops.my_doc(plan)
        if not same:
            self.idx, self.swap, self.how = self.ops.context(plan, self.doc)
            self._tree = None
        if fresh:
            self.sent = None
        self.keep = keep
        self._take_draft(pid)
        for i, p in enumerate(self.plans):
            if p.get("id") == pid:
                self.plans[i] = dict(p, **{k: plan.get(k) for k in ("name", "followers", "role", "following") if k in plan})
        self.label_changed(pid, plan)
        self.plan_shown()

    def _take_draft(self, pid):
        """The changes waiting on this plan here, replayed on it as the
        server has it now: what no longer fits (its date taken off since)
        is dropped, and said."""
        self.draft = self.ops.draft(pid) if self.raw is not None else None
        self._rows = {}
        if self.draft is None:
            return
        if self.draft.version != self.raw.get("version"):
            self.draft.rebase(self.raw["doc"], self.raw.get("version"))
        doc, _changes, dropped = self.draft.replay(self.ctx())
        if dropped:
            self.ops.keep_draft(pid, self.draft)
            self.say(f"{len(dropped):,} waiting change{'s' if len(dropped) != 1 else ''} no longer fit "
                     f"the plan and {'were' if len(dropped) != 1 else 'was'} dropped: "
                     + "; ".join(w for _o, w in dropped[:3]))
        if len(self.draft):
            self.doc = doc
        else:
            self.draft = None

    def draft_changed(self, pid):
        """An AI app put changes under this plan (mcp_host): the window shows them."""
        if (self.plan or {}).get("id") != pid or self.raw is None or self.busy:
            return
        self.doc = self.raw["doc"]
        self._take_draft(pid)
        self._refresh()
        self.say("Changes from your AI app are waiting under the plan: Review and send.")

    def _refresh(self, keep=None):
        """The doc changed here: every part drawn again."""
        self._rows = {}
        self.keep = keep
        self.doc_shown()

    def rows(self, u):
        if self.idx is None:
            return []
        if u["id"] not in self._rows:
            self._rows[u["id"]] = M.sources(self.idx, u, self.doc, self.swap)
        return self._rows[u["id"]]

    def unit(self, uid):
        return next((u for u in P.units(self.doc or {}) if u["id"] == uid), None)

    def event_of(self, eid):
        return next((e for e in (self.doc or {}).get("events") or [] if isinstance(e, dict) and e.get("id") == eid), None)

    def review_of(self, day):
        return next((r for r in (self.doc or {}).get("reviews") or [] if isinstance(r, dict) and r.get("day") == day), None)

    def deck_tree(self):
        """The deck's tags and subdecks here as the builder reads them (build.Tree),
        read once a plan's load (a big deck's tree is a few seconds' work once)."""
        if self.idx is None:
            return None
        if self._tree is None:
            tags, decks = self.idx.tree()
            self._tree = B.Tree(tags, decks)
        return self._tree

    def recount(self):
        """After an open: the cards' states read again, the picked one kept."""
        if self.plan is None:
            return
        self.idx, self.swap, self.how = self.ops.context(self.plan, self.doc)
        self._refresh(self.picked_key())

    # ---- an author's changes ----

    def _busy(self, on, words=None):
        self.busy = on
        if words is not None:
            self.say(words)
        self.busy_shown()

    def change(self, o, keep=None, then=None):
        """One change (an op): with anyone following, it waits under the
        plan; otherwise it saves now. keep: what to pick after it ("made",
        the date it makes; ("date", id); ("gone",); None, what's picked).
        then(ok) once it's in (True) or not (False)."""
        return self.changes([o], keep, then)

    def changes(self, ops, keep=None, then=None):
        then = then or (lambda _ok: None)
        if not self.author() or self.busy or not ops:
            then(False)
            return False
        ctx = self.ctx()
        if self.waiting():
            if self.draft is None:
                from .draft import Draft
                self.draft = Draft(self.plan["id"], self.raw["doc"], self.raw.get("version"))
            made, n0 = set(), len(self.draft)
            try:
                for o in ops:
                    _entries, touched = self.draft.add(o, ctx)
                    made |= touched
            except E.Refused as e:
                del self.draft.ops[n0:]  # all of them or none
                self.draft._cache = None
                self.say(str(e))
                then(False)
                return False
            self.ops.keep_draft(self.plan["id"], self.draft)
            self.doc = self.draft.doc(ctx)
            self._refresh(self._kept(keep, made))
            self.say("")  # the bar under the plan says what's waiting
            then(True)
            return True
        return self._save(ops, keep, then, again=True)

    def _kept(self, keep, made):
        if keep == "made":
            have = {u["id"] for u in P.units(self.doc or {})}
            new = [x for x in made if x in have]
            return ("date", new[0]) if new else None
        return keep if keep is not None else self.picked_key()

    def _save(self, ops, keep, then, again):
        """The ops on the plan as the server has it, saved now (nobody follows it)."""
        before = self.raw["doc"]
        ctx = self.ctx()
        doc, made, checked = before, set(), []
        try:
            for o in ops:
                o = O.check(doc, o)
                doc, _entries, touched = O.apply(doc, o, ctx)
                made |= touched
                checked.append(o)
        except E.Refused as e:
            self.say(str(e))
            then(False)
            return False
        if json.dumps(E.lean(doc), sort_keys=True) == json.dumps(E.lean(before), sort_keys=True):
            self.say("Nothing to change: the plan has that already.")
            then(False)
            return False
        have = {u["id"] for u in doc.get("units") or []}
        if self.idx is not None and made & have:
            doc = E.recount(doc, self.idx, made & have, self.swap)
        summary = E.what_changed(before, doc)
        pid, version = self.plan["id"], self.raw.get("version")
        if keep == "made":  # the date the change made, in the plan after it
            had = {u.get("id") for u in before.get("units") or []}
            new = [x for x in made if x in have and x not in had]
            keep_now = ("date", new[0]) if new else None
        else:
            keep_now = keep
        self._busy(True, "Saving…")
        self.undoable = None
        self.ops.save(self, pid, version, doc, summary,
                      lambda got: self._saved(pid, got, keep_now, checked if again else None, then))
        return True

    def _saved(self, pid, got, keep, retry=None, then=None):
        then = then or (lambda _ok: None)
        self._busy(False, "")
        if pid != self.current_pid():
            then(False)
            return
        if not got:
            self.say("That didn't save: check your connection, then try again.")
            then(False)
            return
        outcome, what = got
        if outcome == "refused":
            self.say(str(what))
            then(False)
            return
        plan = clean_plan(what) or self.plan
        self._loaded(pid, (what, plan), keep=keep, saved=True)
        if outcome == "stale" and retry:
            # someone (or my Anki's note ids) saved since it loaded: the same change, once, on theirs
            self.say("Someone saved this plan since it loaded: putting your change on theirs…")
            self._save(retry, keep, then, again=False)
            return
        then(outcome == "saved")
        if outcome == "saved":
            self.undoable = (pid, plan.get("version"))
            self.undo_shown()
            self.say("Saved.")
        else:
            self.say("Someone saved this plan again since: it's up to date now. Make the change again.")

    # ---- the changes waiting ----

    def discard(self):
        if not self.draft or not len(self.draft):
            return
        if not self.ask_discard(len(self.draft)):
            return
        self.draft.clear()
        self.ops.keep_draft(self.plan["id"], None)
        self.draft = None
        self.doc = self.raw["doc"]
        self._refresh()
        self.say("Discarded.")

    def take_change(self, i):
        """One waiting change out (Review's ✕, or Undo's first line)."""
        if not self.draft or not (0 <= i < len(self.draft)):
            return
        self.draft.take(i)
        self.ops.keep_draft(self.plan["id"], self.draft if len(self.draft) else None)
        if not len(self.draft):
            self.draft = None
            self.doc = self.raw["doc"]
        else:
            self.doc = self.draft.doc(self.ctx())
        self._refresh()

    def send(self, why):
        if not self.draft or not len(self.draft) or self.busy:
            return
        ctx = self.ctx()
        doc, summary, _line = self.draft.payload(ctx, self.idx, self.swap)
        pid, version, n = self.plan["id"], self.draft.version, len(self.draft)
        post = " ".join(str(why or "").split())[:O.WHY_MAX] or None
        self._busy(True, "Sending…")

        def done(got):
            self._busy(False, "")
            if pid != self.current_pid():
                return
            if not got:
                self.say("That didn't send: check your connection, then try again. Your changes are kept.")
                return
            outcome, what = got
            if outcome == "refused":
                self.say(str(what))
                return
            if outcome == "stale":
                # a co-author saved since: the same changes on theirs, to look over again
                self._loaded(pid, (what, clean_plan(what) or self.plan), saved=True)
                self.say("Someone saved this plan since your changes began: they're on theirs now. "
                         "Look them over, then send.")
                return
            self.ops.keep_draft(pid, None)
            self.draft = None
            plan = clean_plan(what) or self.plan
            self._loaded(pid, (what, plan), saved=True)
            self.undoable = (pid, plan.get("version"))
            self.sent = (self.ops.now_words(), n)
            self.undo_shown()
            self.say(f"Sent to {self.followers():,} following. They get it at their next refresh.")
        self.ops.send(self, pid, version, doc, summary, post, done)

    # ---- Undo ----

    def undo_entries(self):
        """Undo as it opens: [(label, what, enabled)], what one of
        ("take", i), ("undo",), ("history",), None (a line to read)."""
        out = []
        if not self.author():
            return out
        if self.draft and len(self.draft):
            es = self.draft.entries(self.ctx())
            last = es[-1:] if es else []
            what = f"{last[0]['what']} {last[0]['verb'].lower()}" if last else "the last change"
            out.append((f"Take back the last change, not sent ({what})", ("take", len(self.draft) - 1), True))
        if self.undoable and self.undoable[0] == (self.plan or {}).get("id"):
            label = (f"Undo your send of {self.sent[0]} ({self.sent[1]:,} change{'s' if self.sent[1] != 1 else ''})"
                     if self.sent else "Undo your last save")
            out.append((label, ("undo",), not self.busy))
        if not out:
            out.append(("Nothing of yours to undo here", None, False))
        out.append(("History: every save…", ("history",), True))
        return out

    def undo_key(self):
        """Ctrl+Z: the last change not sent taken back; a save made at
        once, undone. True when it did something; False: a send (the menu asks)."""
        if not self.author() or self.busy:
            return True
        if self.draft and len(self.draft):
            self.take_change(len(self.draft) - 1)
            self.say("Taken back.")
            return True
        if self.undoable and self.undoable[0] == (self.plan or {}).get("id") and not self.sent:
            self.undo()
            return True
        return False

    def undo_latest(self, version):
        """History's Undo the latest."""
        self.undoable = (self.plan["id"], version)
        self.undo()

    def undo(self):
        if not self.undoable or self.busy:
            return
        pid, version = self.undoable
        if pid != self.current_pid():
            self.undoable = None
            return
        self._busy(True, "Undoing…")
        self.undoable = None
        keep = self.picked_key()

        def done(got):
            self._busy(False, "")
            if pid != self.current_pid():
                return
            if not got:
                self.say("That didn't undo: check your connection, then try again.")
                return
            outcome, what = got
            if outcome == "refused":
                self.say(str(what))
                return
            self.sent = None
            self._loaded(pid, (what, clean_plan(what) or self.plan), keep=keep, saved=True)
            self.say("Undone." if outcome == "saved"
                     else "Someone saved this plan since, so there's nothing of yours to undo now.")
        self.ops.undo(self, pid, version, done)

    def took(self, raw):
        """A settings change the server answered with the plan as it is now:
        the window on that, while it's still the plan picked."""
        pid = self.current_pid()
        if not isinstance(raw, dict) or str(raw.get("id") or pid) != str(pid) or (self.plan or {}).get("id") != pid:
            return
        plan = clean_plan(raw) or self.plan
        self._loaded(pid, (raw, plan), saved=True)

    # ---- show, open, study (plan_flow's) ----

    def own_steps(self):
        """The plan's own open and study (its state kept): I follow it here, this version."""
        return self.ops.followed_here(self.plan["id"], self.plan.get("version"))

    def open_date(self, uid, cids=None, name=""):
        if self.plan is None:
            return
        if cids is None and self.own_steps():
            self.ops.open_date(self.plan["id"], uid)
        else:
            u = self.unit(uid)
            cids = cids if cids is not None else (self.idx.match(u, self.swap, self.doc) if u and self.idx else set())
            if not self.ops.open_cards(cids, name or str((u or {}).get("name") or "date")):
                self.say("Nothing to open: its cards here are open already (leeches stay shut).")
        self.later(self.recount)

    def study(self, kind, key, cids=None, name=""):
        """True when Anki's Study screen took it (the window gets out of its way)."""
        if self.plan is None:
            return False
        if cids is None and kind in ("date", "event") and self.own_steps():
            (self.ops.study_date if kind == "date" else self.ops.study_quiz)(self.plan["id"], key)
            return False
        return bool(cids and self.ops.study_cards(self.idx, cids, name))
