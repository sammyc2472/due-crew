"""Your plans (docs/planner.md; round five): the builder of duecrew.com,
in Anki, as one window, two tabs. An author's: Plan (the plan's shape on
top, its weeks and dates, the picked one beside them or the deck while
cards go on, a paste box, and the changes waiting to be sent) and
Settings (its name, dates and pace, every-week lines; its code, who can
follow, how many do and the posts to them, co-authors, the library; Your
AI app). A plan I follow: Plan (today, what's behind, its dates) and
Settings (my dates, skips, how its cards open). Undo on top.

Every change is an op (ops.py). With anyone following, it waits under
the plan (draft.py, kept on this computer) until Review and send, one
save with one line to followers; with nobody following, it saves at once
(PUT /plans/{id}, the version it started from) and Undo takes it back.
Show in Browse, Open and Study are plan_flow's (through flow.Ops). Names
are the authors' and the deck's: plain text everywhere, escaped in a
tooltip."""

import json

from aqt.qt import (
    QComboBox, QDate, QDateEdit, QDialog, QDialogButtonBox, QHBoxLayout, QPushButton, QTabWidget,
    QTimer, QVBoxLayout, QWidget,
)

from ..ui import attach_alive, heading, role
from .. import plans as P
from .. import schedule as S
from ..backend.shapes import clean_plan
from . import build as B
from . import edits as E
from . import model as M
from . import ops as O
from .widgets import fit, menu_button, plain, tip_keys

TABS = {"dates": "plan", "layout": "plan", "text": "plan", "plan": "plan", "history": "plan",
        "progress": "sharing", "updates": "sharing", "followers": "sharing",
        "settings": "sharing", "sharing": "sharing", "mine": "mine"}


def _whose(p):
    who = p.get("ownerName") if p.get("ownerName") not in (None, "", "?") else None  # the server's "?": a name it hasn't got
    if p.get("role") in ("owner", "editor"):
        return "yours" if p.get("role") == "owner" else (f"with {who}" if who else "a co-author")
    return f"{who}’s · following" if who else "following"


def _pick_label(p):
    bits = [str(p.get("name") or "Plan"), _whose(p)]
    if p.get("role") in ("owner", "editor"):
        n = int(p.get("followers") or 0)
        bits.append(f"{n:,} following" if n else "nobody following yet")
    return " · ".join(bits)


class DayDialog(QDialog):
    """One day, picked on a calendar: a new date's day, a quiz's."""

    def __init__(self, parent, title, words, day, yes, clear=None):
        super().__init__(parent)
        attach_alive(self)
        self.cleared = False
        self.setWindowTitle(title)
        root = QVBoxLayout(self)
        heading(self, root)
        root.addWidget(plain(words, muted=True))
        self.day = QDateEdit()
        self.day.setCalendarPopup(True)
        self.day.setDisplayFormat("ddd d MMM yyyy")
        d = QDate.fromString(str(day), "yyyy-MM-dd")
        self.day.setDate(d if d.isValid() else QDate.currentDate())
        root.addWidget(self.day)
        buttons = QDialogButtonBox()
        buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole).clicked.connect(self.reject)
        if clear:
            b = QPushButton(clear)
            b.clicked.connect(self._clear)
            buttons.addButton(b, QDialogButtonBox.ButtonRole.ActionRole)
        go = QPushButton(yes)
        go.setDefault(True)
        go.clicked.connect(self.accept)
        buttons.addButton(go, QDialogButtonBox.ButtonRole.AcceptRole)
        root.addWidget(buttons)

    def _clear(self):
        self.cleared = True
        self.accept()

    def value(self):
        return None if self.cleared else self.day.date().toString("yyyy-MM-dd")


def ask_day(parent, title, words, day, yes, clear=None):
    """The day picked ("YYYY-MM-DD"), None for `clear`, False when cancelled."""
    dlg = DayDialog(parent, title, words, day, yes, clear)
    return dlg.value() if dlg.exec() else False


class PlanWindow(QDialog):
    """plans: remote.my_plans' (cleaned, each with its role). ops: flow.Ops,
    or a render's or test's own."""

    def __init__(self, parent, col, plans, ops, select=None, tab=None):
        super().__init__(parent)
        self.col, self.ops = col, ops
        self.plans = [p for p in plans or [] if isinstance(p, dict) and p.get("id")]
        self.plans.sort(key=lambda p: (p.get("role") not in ("owner", "editor"), str(p.get("name") or "").lower()))
        self.plan = self.raw = self.doc = self.idx = self.swap = self.draft = None
        self.how = ""
        self.keep = None          # what the Plan tab picks once a plan (re)loads
        self.busy = False
        self.undoable = None      # (plan id, version) a save of this window's made, while its Undo shows
        self.sent = None          # (when, how many changes) the last send, for Undo's first line
        self._rows = {}           # uid -> model.sources, for this plan's index and doc
        self._tree = None
        attach_alive(self)
        self.setWindowTitle("Your plans")
        self.setModal(False)
        self.setMinimumSize(900, 560)
        self.setProperty("dcOwnSize", True)  # it scrolls its own: ui._fit never grows it to its words
        fit(self, 1180, 780)  # its first size; less on a small screen
        root = QVBoxLayout(self)
        self.head = heading(self, root, "Your plans")

        top = QHBoxLayout()
        self.pick = QComboBox()
        for p in self.plans:
            self.pick.addItem(_pick_label(p), p["id"])
        top.addWidget(self.pick, 1)
        self.undo_btn, self.undo_menu = menu_button("Undo", self._undo_entries)
        self.undo_btn.setToolTip(tip_keys("The last change not sent, your last save or send; History", "Ctrl+Z"))
        top.addWidget(self.undo_btn)
        self.new_btn = QPushButton("New plan…")
        self.new_btn.setAutoDefault(False)
        self.new_btn.clicked.connect(lambda: self.ops.new_plan())
        top.addWidget(self.new_btn)
        root.addLayout(top)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        root.addWidget(self.tabs, 1)
        self.welcome = self._welcome()  # no plans yet: in the tabs' place
        root.addWidget(self.welcome, 1)
        self.pages = {}
        from .plan_tab import PlanTab
        from .settings_tab import SettingsTab
        from .mine_tab import MineTab
        self._add_tab("plan", "Plan", PlanTab(self))
        self._add_tab("sharing", "Settings", SettingsTab(self))  # an author's: the plan's dates and pace, sharing it
        self._add_tab("mine", "Settings", MineTab(self))  # a follower's: my dates, skips, how its cards open
        self.want_tab = TABS.get(tab or "", tab)

        bottom = QHBoxLayout()
        self.status = plain(muted=True)
        bottom.addWidget(self.status, 1)
        close = QPushButton("Close")
        close.setAutoDefault(False)
        close.clicked.connect(self.reject)
        bottom.addWidget(close)
        root.addLayout(bottom)
        self.tabs.currentChanged.connect(self._tab_changed)

        if select and self.pick.findData(select) >= 0:
            self.pick.setCurrentIndex(self.pick.findData(select))  # before the signal: one load, of this one
        self.pick.currentIndexChanged.connect(self._load)
        # the same plan picked again after a load that failed: try it again
        self.pick.activated.connect(lambda _i: self._load() if self.plan is None and not self.busy else None)
        if self.plans:
            self._load()
        else:
            self._no_plans()

    def _welcome(self):
        """No plans yet: what a plan is, and the two ways to one."""
        page = QWidget()
        words = QVBoxLayout(page)
        words.setContentsMargins(0, 16, 0, 0)
        words.addWidget(role(plain("No plans yet"), "head"))
        words.addWidget(plain("A plan puts a block's lectures on dates, and opens each date's cards in Anki "
                              "as its day comes."))
        ways = QHBoxLayout()
        b = QPushButton("New plan…")
        b.setProperty("dc", "go")
        b.clicked.connect(lambda: self.ops.new_plan())
        ways.addWidget(b)
        f = QPushButton("Follow a plan…")
        f.clicked.connect(lambda: self.ops.follow_plan())
        ways.addWidget(f)
        ways.addStretch(1)
        words.addSpacing(8)
        words.addLayout(ways)
        words.addStretch(1)
        page.hide()
        return page

    def _no_plans(self):
        for w in (self.pick, self.undo_btn, self.new_btn, self.tabs):
            w.hide()
        self.welcome.show()
        self.setMinimumSize(640, 260)
        self.resize(720, 280)

    def go_to_plan(self, pid, tab=None):
        """The window, on this plan: True, or False when it doesn't list it."""
        i = self.pick.findData(pid)
        if i < 0:
            return False
        self.want_tab = TABS.get(tab or "", tab)
        if i != self.pick.currentIndex():
            self.pick.setCurrentIndex(i)
        else:
            self._show_tab(self.want_tab)
        return True

    # ---- the tabs ----

    def _add_tab(self, key, label, widget):
        self.pages[key] = widget
        self.tabs.addTab(widget, label)

    def _show_tab(self, key):
        page = self.pages.get(key or "")
        i = self.tabs.indexOf(page) if page is not None else -1
        if i >= 0 and self.tabs.isTabVisible(i):
            self.tabs.setCurrentIndex(i)

    def _role_tabs(self):
        """Plan always; Settings: an author's (SettingsTab) or a follower's (MineTab)."""
        for key, page in self.pages.items():
            shown = getattr(page, "shown", None)
            i = self.tabs.indexOf(page)
            self.tabs.setTabVisible(i, bool(shown(self)) if callable(shown) else True)
        for page in self.pages.values():
            fill = getattr(page, "plan_loaded", None)
            if callable(fill):
                fill(self)
        if self.want_tab:
            self._show_tab(self.want_tab)
            self.want_tab = None
        self._undo_button()

    def _tab_changed(self, _i):
        if not self.busy:
            self.status.setText("")

    # ---- a plan ----

    def author(self):
        return bool(self.plan) and self.plan.get("role") in ("owner", "editor") and self.raw is not None

    def followers(self):
        return int((self.plan or {}).get("followers") or 0)

    def waiting(self):
        """Changes wait to be sent: someone follows it, or some wait already (an AI app's)."""
        return self.author() and (self.followers() > 0 or bool(self.draft and len(self.draft)))

    def plan_name(self):
        return str((self.plan or {}).get("name") or "")

    def ctx(self):
        return O.Ctx(self.deck_tree(), self.ops.today(), self.plan_name(), S.plan_days(self.doc or {}))

    def _load(self, *_):
        pid = self.pick.currentData()
        if not pid:
            return
        self._busy(True, "Loading the plan…")
        self.undoable = None
        self.pages["plan"].forget()  # its notes are read again with it
        self.ops.load(self, pid, lambda got: self._loaded(pid, got))

    def _loaded(self, pid, got, keep=None, saved=False):
        if pid != self.pick.currentData():
            return  # another plan was picked since
        self._busy(False, "")
        if not got:
            self.plan = self.raw = self.doc = self.idx = self.draft = None
            self._tree = None
            self.status.setText("The plan didn't load: check your connection, then pick it again.")
            self._role_tabs()
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
        i = self.pick.findData(pid)
        if i >= 0:
            self.pick.setItemText(i, _pick_label(plan))
        self._role_tabs()

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
            self.status.setText(f"{len(dropped):,} waiting change{'s' if len(dropped) != 1 else ''} no longer fit "
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
        self.status.setText("Changes from your AI app are waiting under the plan: Review and send.")

    def _refresh(self, keep=None):
        """The doc changed here (a change waiting, or one taken out): every tab drawn again."""
        self._rows = {}
        self.keep = keep
        for page in self.pages.values():
            fill = getattr(page, "plan_loaded", None)
            if callable(fill):
                fill(self)
        self._undo_button()

    def rows(self, u):
        if self.idx is None:
            return []
        if u["id"] not in self._rows:
            self._rows[u["id"]] = M.sources(self.idx, u, self.doc, self.swap)
        return self._rows[u["id"]]

    def unit(self, uid):
        return next((u for u in P.units(self.doc or {}) if u["id"] == uid), None)

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
        self._refresh(self.pages["plan"].picked)

    # ---- an author's changes ----

    def _busy(self, on, words=None):
        self.busy = on
        if words is not None:
            self.status.setText(words)
        self.pick.setEnabled(not on)
        self.new_btn.setEnabled(not on)
        for page in self.pages.values():
            if callable(getattr(page, "busy_changed", None)):
                page.busy_changed(self)

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
                self.status.setText(str(e))
                then(False)
                return False
            self.ops.keep_draft(self.plan["id"], self.draft)
            self.doc = self.draft.doc(ctx)
            self._refresh(self._kept(keep, made))
            self.status.setText("")  # the bar under the plan says what's waiting
            then(True)
            return True
        return self._save(ops, keep, then, again=True)

    def _kept(self, keep, made):
        if keep == "made":
            have = {u["id"] for u in P.units(self.doc or {})}
            new = [x for x in made if x in have]
            return ("date", new[0]) if new else None
        return keep if keep is not None else self.pages["plan"].picked

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
            self.status.setText(str(e))
            then(False)
            return False
        if json.dumps(E.lean(doc), sort_keys=True) == json.dumps(E.lean(before), sort_keys=True):
            self.status.setText("Nothing to change: the plan has that already.")
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
        if pid != self.pick.currentData():
            then(False)
            return
        if not got:
            self.status.setText("That didn't save: check your connection, then try again.")
            then(False)
            return
        outcome, what = got
        if outcome == "refused":
            self.status.setText(str(what))
            then(False)
            return
        plan = clean_plan(what) or self.plan
        self._loaded(pid, (what, plan), keep=keep, saved=True)
        if outcome == "stale" and retry:
            # someone (or my Anki's note ids) saved since it loaded: the same change, once, on theirs
            self.status.setText("Someone saved this plan since it loaded: putting your change on theirs…")
            self._save(retry, keep, then, again=False)
            return
        then(outcome == "saved")
        if outcome == "saved":
            self.undoable = (pid, plan.get("version"))
            self._undo_button()
            self.status.setText("Saved.")
        else:
            self.status.setText("Someone saved this plan again since: it's up to date now. Make the change again.")

    # ---- the changes waiting ----

    def discard(self):
        from ..ui import confirm
        if not self.draft or not len(self.draft):
            return
        n = len(self.draft)
        if not confirm(self, f"Discard {n:,} change{'s' if n != 1 else ''}?", "They were never sent: nobody saw them.",
                       "Discard", danger=True):
            return
        self.draft.clear()
        self.ops.keep_draft(self.plan["id"], None)
        self.draft = None
        self.doc = self.raw["doc"]
        self._refresh()
        self.status.setText("Discarded.")

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

    def review_send(self):
        """Review and send: each change in words with who it touches, a ✕
        each, the line to followers filled in; Send is one save."""
        if not self.draft or not len(self.draft) or self.busy:
            return
        from .send import SendDialog
        dlg = SendDialog(self)
        if dlg.exec():
            self.send(dlg.why())

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
            if pid != self.pick.currentData():
                return
            if not got:
                self.status.setText("That didn't send: check your connection, then try again. Your changes are kept.")
                return
            outcome, what = got
            if outcome == "refused":
                self.status.setText(str(what))
                return
            if outcome == "stale":
                # a co-author saved since: the same changes on theirs, to look over again
                self._loaded(pid, (what, clean_plan(what) or self.plan), saved=True)
                self.status.setText("Someone saved this plan since your changes began: they're on theirs now. "
                                    "Look them over, then send.")
                return
            self.ops.keep_draft(pid, None)
            self.draft = None
            plan = clean_plan(what) or self.plan
            self._loaded(pid, (what, plan), saved=True)
            self.undoable = (pid, plan.get("version"))
            self.sent = (self.ops.now_words(), n)
            self._undo_button()
            self.status.setText(f"Sent to {self.followers():,} following. They get it at their next refresh.")
        self.ops.send(self, pid, version, doc, summary, post, done)

    # ---- Undo ----

    def _undo_button(self):
        self.undo_btn.setVisible(self.author())

    def _undo_entries(self):
        """Undo as it opens: the last change not sent, the last save or send of this window's, then History."""
        self.undo_menu.clear()
        if not self.author():
            return
        if self.draft and len(self.draft):
            last = self.draft.entries(self.ctx())[-1:] if self.draft.entries(self.ctx()) else []
            what = f"{last[0]['what']} {last[0]['verb'].lower()}" if last else "the last change"
            a = self.undo_menu.addAction(f"Take back the last change, not sent ({what})")
            a.triggered.connect(lambda: self.take_change(len(self.draft) - 1))
        if self.undoable and self.undoable[0] == (self.plan or {}).get("id"):
            label = (f"Undo your send of {self.sent[0]} ({self.sent[1]:,} change{'s' if self.sent[1] != 1 else ''})"
                     if self.sent else "Undo your last save")
            a = self.undo_menu.addAction(label)
            a.setEnabled(not self.busy)
            a.triggered.connect(self._undo)
        if not self.undo_menu.actions():
            a = self.undo_menu.addAction("Nothing of yours to undo here")
            a.setEnabled(False)
        self.undo_menu.addSeparator()
        self.undo_menu.addAction("History: every save…").triggered.connect(self._history)

    def undo_key(self):
        """Ctrl+Z (the Plan tab's, outside a box): the last change not sent
        taken back; a save made at once, undone; a send asks, by the menu."""
        if not self.author() or self.busy:
            return
        if self.draft and len(self.draft):
            self.take_change(len(self.draft) - 1)
            self.status.setText("Taken back.")
        elif self.undoable and self.undoable[0] == (self.plan or {}).get("id") and not self.sent:
            self._undo()
        elif self.undo_btn.isVisible():
            self.undo_btn.showMenu()

    def _history(self):
        from .send import HistoryDialog
        HistoryDialog(self).exec()

    def undo_latest(self, version):
        """History's Undo the latest."""
        self.undoable = (self.plan["id"], version)
        self._undo()

    def _undo(self):
        if not self.undoable or self.busy:
            return
        pid, version = self.undoable
        if pid != self.pick.currentData():
            self.undoable = None
            return
        self._busy(True, "Undoing…")
        self.undoable = None
        keep = self.pages["plan"].picked

        def done(got):
            self._busy(False, "")
            if pid != self.pick.currentData():
                return
            if not got:
                self.status.setText("That didn't undo: check your connection, then try again.")
                return
            outcome, what = got
            if outcome == "refused":
                self.status.setText(str(what))
                return
            self.sent = None
            self._loaded(pid, (what, clean_plan(what) or self.plan), keep=keep, saved=True)
            self.status.setText("Undone." if outcome == "saved"
                                else "Someone saved this plan since, so there's nothing of yours to undo now.")
        self.ops.undo(self, pid, version, done)

    def took(self, raw):
        """A settings change the server answered with the plan as it is now:
        the window on that, while it's still the plan picked."""
        pid = self.pick.currentData()
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
                self.status.setText("Nothing to open: its cards here are open already (leeches stay shut).")
        QTimer.singleShot(0, self.recount)

    def study(self, kind, key, cids=None, name=""):
        if self.plan is None:
            return
        if cids is None and kind in ("date", "event") and self.own_steps():
            (self.ops.study_date if kind == "date" else self.ops.study_quiz)(self.plan["id"], key)
            return
        if cids and self.ops.study_cards(self.idx, cids, name):
            self.close()  # Anki's Study screen is on it; the window would sit over it
