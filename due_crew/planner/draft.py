"""Changes that wait to be sent (round five, docs/planner.md): an author's
changes to a plan with people following it gather here, each an op
(ops.py), and go out together as one save with one line to followers
(PUT /plans/{id} with its post), one Undo. A plan nobody follows saves as
it changes (the window sends each at once).

A draft is the version it started from and its ops, nothing else: the
plan it shows is those ops replayed on the plan as the server has it, so
a co-author's save in between, or Anki restarting, loses nothing (an op
that no longer fits, its date taken off meanwhile, is dropped and said).
Kept on this computer, per profile (flow.py: plan_drafts.json), never
sent till Send.

Pure."""

import copy
import json

from . import edits as E
from . import ops as O


class Draft:
    """pid, base (the doc the ops were made on, as the server had it),
    version (base's), ops [op]."""

    def __init__(self, pid, base, version, ops=()):
        self.pid = str(pid)
        self.base = copy.deepcopy(base or {})
        self.version = version
        self.ops = [dict(o) for o in ops]
        self._cache = None

    # ---- what it holds ----

    def __len__(self):
        return len(self.ops)

    def replay(self, ctx):
        """(doc, [entries a change], [(op, words)] dropped): the ops on the
        base, in order; one that won't go on any more is dropped, said."""
        key = (json.dumps(self.ops, sort_keys=True), id(ctx.tree), ctx.today)
        if self._cache and self._cache[0] == key:
            return self._cache[1]
        doc, changes, dropped, kept = copy.deepcopy(self.base), [], [], []
        for o in self.ops:
            try:
                after, entries, touched = O.apply(doc, o, ctx)
            except E.Refused as e:
                dropped.append((o, str(e)))
                continue
            for x in entries:
                x["who"] = O.who(x, ctx.today)
            changes.append({"op": o, "entries": entries, "touched": touched})
            kept.append(o)
            doc = after
        self.ops = kept
        out = (doc, changes, dropped)
        self._cache = (json.dumps(self.ops, sort_keys=True), id(ctx.tree), ctx.today), out
        return out

    def doc(self, ctx):
        return self.replay(ctx)[0]

    def entries(self, ctx):
        return [x for c in self.replay(ctx)[1] for x in c["entries"]]

    def touched(self, ctx):
        out = set()
        for c in self.replay(ctx)[1]:
            out |= set(c["touched"])
        return out

    # ---- changing it ----

    def add(self, o, ctx):
        """One op more, checked on the plan as the draft has it now:
        (entries it made, the ids it touched); Refused with the words."""
        if len(self.ops) >= O.OPS_MAX:
            raise E.Refused(f"{O.OPS_MAX} changes are waiting: send them first.")
        doc = self.doc(ctx)
        o = O.check(doc, o)
        after, entries, touched = O.apply(doc, o, ctx)
        if json.dumps(E.lean(after), sort_keys=True) == json.dumps(E.lean(doc), sort_keys=True):
            raise E.Refused("Nothing to change: the plan has that already.")
        self.ops.append(o)
        self._cache = None
        return entries, touched

    def take(self, i):
        """The change at i out (its op); the rest replayed without it."""
        if 0 <= i < len(self.ops):
            del self.ops[i]
            self._cache = None

    def clear(self):
        self.ops = []
        self._cache = None

    def rebase(self, base, version):
        """The plan as the server has it now (a co-author's save, or a
        stale send): the same ops, on that."""
        self.base, self.version = copy.deepcopy(base or {}), version
        self._cache = None

    # ---- sending ----

    def payload(self, ctx, idx=None, swap=None):
        """(doc to save, its history line, the line to followers) for one
        send: the doc as a save sends it, the dates it touched counted again
        in this copy (the builder's count)."""
        doc, changes, _dropped = self.replay(ctx)
        touched = set()
        for c in changes:
            touched |= set(c["touched"])
        if idx is not None and touched:
            have = {u.get("id") for u in doc.get("units") or []}
            doc = E.recount(doc, idx, touched & have, swap)
        summary = E.what_changed(self.base, doc)
        why = O.why_line([x for c in changes for x in c["entries"]])
        return doc, summary, why

    # ---- kept on this computer ----

    def to_json(self):
        return {"version": self.version, "base": self.base, "ops": self.ops}

    @classmethod
    def from_json(cls, pid, data):
        if not isinstance(data, dict) or not isinstance(data.get("ops"), list):
            return None
        return cls(pid, data.get("base") or {}, data.get("version"), [o for o in data["ops"] if isinstance(o, dict)])
