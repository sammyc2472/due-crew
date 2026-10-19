"""Your plans' Settings and Progress tabs (3.9.3), the builder's, for a
plan's authors. Settings: its name and one line, where to get the deck,
whether it's offered to one of my squads and who can follow (the
owner's), its co-authors (asked, handed it, taken off; a co-author
leaves), when it ends, catch-up weeks and review-only days at the end,
the library (the owner's), a copy for next year, and taking it down.
Progress: its squad's counts a date (three sharing or more), and the dates
most of the class hasn't finished, with Give the class a day. Each change
is one request, at once; names are the server's and the authors': plain."""

from aqt.qt import (
    QButtonGroup, QCheckBox, QComboBox, QDate, QDateEdit, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPushButton, QRadioButton, QScrollArea, QSpinBox, Qt, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..ui import ask_item, confirm, esc, note, role, sev_label
from .. import plans as P
from .. import schedule as S
from . import edits as E
from . import remote
from .history_tab import _Lazy

CATCHUP = ((0, "None"), (3, "Every 3rd week"), (4, "Every 4th week"))


class _Said(QLabel):
    """A line that takes no room while it has nothing to say."""

    def setText(self, text):
        super().setText(text)
        self.setVisible(bool(text))


def _plain(text="", muted=False, said=False):
    w = (_Said if said else QLabel)(str(text))
    w.setTextFormat(Qt.TextFormat.PlainText)
    w.setWordWrap(True)
    if said:
        w.setVisible(bool(text))
    return note(w) if muted else w


def _link(text, fn):
    b = QPushButton(text)
    b.setFlat(True)
    b.clicked.connect(fn)
    return b


class SettingsTab(QWidget):
    """One plan's Settings, for its authors (some of it its owner's)."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self._loading = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 8, 0, 0)
        scroll = QScrollArea()  # the window keeps its height; this scrolls
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        scroll.viewport().setAutoFillBackground(False)  # the window's own ground behind it
        body.setAutoFillBackground(False)  # after setWidget, which turns it on
        form = QFormLayout(body)
        form.setContentsMargins(0, 0, 12, 0)
        self.form = form

        self.name = QLineEdit()
        self.name.setMaxLength(60)
        self.line = QLineEdit()
        self.line.setMaxLength(120)
        self.line.setPlaceholderText("Organ systems, one a week, done by January.")
        for w in (self.name, self.line):
            w.textChanged.connect(self._meta_changed)
        self.meta_btn = QPushButton("Save the name and line")
        self.meta_btn.clicked.connect(self._save_meta)
        form.addRow("Name", self.name)
        form.addRow("One line", self.line)
        form.addRow("", self.meta_btn)

        row = QHBoxLayout()
        self.url = QLineEdit()
        self.url.setMaxLength(300)
        self.url.setPlaceholderText("https://…")
        self.url.textChanged.connect(lambda _t: self._buttons())
        row.addWidget(self.url, 1)
        self.url_btn = QPushButton("Save the link")
        self.url_btn.clicked.connect(self._save_url)
        row.addWidget(self.url_btn)
        form.addRow("Where to get the deck", row)
        self.url_said = _plain(muted=True)
        form.addRow("", self.url_said)

        self.squad = QComboBox()
        self.squad.currentIndexChanged.connect(lambda _i: self._who())
        form.addRow("Offer it to one of my squads", self.squad)
        who = QVBoxLayout()
        self.aud = QButtonGroup(self)
        self.by_code = QRadioButton("Anyone with the code")
        self.by_squad = QRadioButton("Only people in that squad of mine")
        for i, b in enumerate((self.by_code, self.by_squad)):
            self.aud.addButton(b, i)
            who.addWidget(b)
        self.aud.idClicked.connect(lambda _i: self._who())
        self.owner_only = _plain("Its owner sets who can follow.", muted=True)
        who.addWidget(self.owner_only)
        form.addRow("Who can follow", who)

        self.coas = QTreeWidget()
        self.coas.setHeaderHidden(True)
        self.coas.setRootIsDecorated(False)
        self.coas.setColumnCount(2)
        self.coas.setMaximumHeight(120)
        h = self.coas.header()
        h.setStretchLastSection(False)
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.coas.itemSelectionChanged.connect(self._buttons)
        coa = QVBoxLayout()
        coa.addWidget(_plain("They edit it with you, and its tags go on their notes in Anki. Each one says yes first.", muted=True))
        coa.addWidget(self.coas)
        row = QHBoxLayout()
        self.add_btn = _link("Ask one of my crew…", self._ask_coauthor)
        self.hand_btn = _link("Hand it to them", self._hand)
        self.unhand_btn = _link("Take the offer back", lambda: self._offer(None))
        self.off_btn = _link("Take them off", self._take_off)
        self.leave_btn = _link("Leave this plan", self._leave)
        for b in (self.add_btn, self.hand_btn, self.unhand_btn, self.off_btn, self.leave_btn):
            row.addWidget(b)
        row.addStretch(1)
        coa.addLayout(row)
        self.coa_said = _plain(muted=True, said=True)
        coa.addWidget(self.coa_said)
        form.addRow("Co-authors", coa)

        row = QHBoxLayout()
        self.has_end = QCheckBox("Ends")
        self.has_end.toggled.connect(lambda _on: self._end())
        self.end = QDateEdit()
        self.end.setCalendarPopup(True)
        self.end.setDisplayFormat("ddd d MMM yyyy")
        self.end.dateChanged.connect(lambda _d: self._end())
        row.addWidget(self.has_end)
        row.addWidget(self.end)
        row.addWidget(_plain("the exam, or the course's last day", muted=True), 1)
        form.addRow("End", row)
        self.catchup = QComboBox()
        for v, label in CATCHUP:
            self.catchup.addItem(label, v)
        self.catchup.currentIndexChanged.connect(lambda _i: self._phases())
        form.addRow("Catch-up weeks (nothing new)", self.catchup)
        row = QHBoxLayout()
        self.taper = QSpinBox()
        self.taper.setRange(0, 60)
        self.taper.setSuffix(" days")
        self.taper.editingFinished.connect(self._phases)
        row.addWidget(self.taper)
        row.addWidget(_plain("before the end date: no new cards", muted=True), 1)
        form.addRow("Review-only days at the end", row)

        lib = QVBoxLayout()
        self.listed = QCheckBox("List it in the library")
        self.listed.toggled.connect(self._listed)
        lib.addWidget(self.listed)
        self.lib_said = _plain(muted=True)
        lib.addWidget(self.lib_said)
        form.addRow("Library", lib)

        row = QHBoxLayout()
        self.copy_btn = _link("Copy for next year", self._next_year)
        row.addWidget(self.copy_btn)
        row.addStretch(1)
        self.delete_btn = QPushButton("Delete this plan…")
        self.delete_btn.setProperty("dc", "bad")
        self.delete_btn.clicked.connect(self._delete)
        row.addWidget(self.delete_btn)
        form.addRow("", row)
        self.said = _plain(said=True)
        form.addRow(self.said)

    # ---- the window asks ----

    def shown(self, win):
        return win.author()

    def _raw(self):
        return self.win.raw or {}

    def _owner(self):
        return (self.win.plan or {}).get("role") == "owner"

    def plan_loaded(self, win):
        if not win.author():
            return
        raw, doc = self._raw(), self._raw().get("doc") or {}
        self._loading = True
        try:
            self.name.setText(str(raw.get("name") or ""))
            self.line.setText(str(raw.get("line") or ""))
            self.url.setText(str(doc.get("deckUrl") or ""))
            self.url_said.setText(f"On its link page and poster, and in Anki for anyone with no deck called {doc.get('deck') or '?'}.")
            self.squad.clear()
            self.squad.addItem("No squad", None)
            for sq in win.ops.my_squads():
                self.squad.addItem(str(sq.get("name") or "?"), sq.get("id"))
            if raw.get("squad") and self.squad.findData(raw["squad"]) < 0:
                self.squad.addItem("A squad of mine", raw["squad"])
            self.squad.setCurrentIndex(max(0, self.squad.findData(raw.get("squad"))))
            (self.by_squad if raw.get("audience") == "squad" else self.by_code).setChecked(True)
            end = QDate.fromString(str(doc.get("end") or ""), "yyyy-MM-dd")
            self.has_end.setChecked(end.isValid())
            days = [str(u.get("due") or u.get("opens")) for u in P.units(doc)] + \
                [str(e["day"]) for e in doc.get("events") or [] if isinstance(e, dict) and e.get("day")]
            self.end.setDate(end if end.isValid() else QDate.fromString(max(days + [win.ops.today()]), "yyyy-MM-dd"))
            ph = doc.get("phases") or {}
            self.catchup.setCurrentIndex(max(0, self.catchup.findData(int(ph.get("catchup") or 0))))
            if int(ph.get("catchup") or 0) and self.catchup.findData(int(ph["catchup"])) < 0:
                self.catchup.addItem(f"Every {int(ph['catchup'])}th week", int(ph["catchup"]))
                self.catchup.setCurrentIndex(self.catchup.count() - 1)
            self.taper.setValue(int(ph.get("taper") or 0))
            self.listed.setChecked(raw.get("listed") == 1)
        finally:
            self._loading = False
        self._coauthors()
        self._buttons()

    def busy_changed(self, win):
        if win.author():
            self._buttons()

    def _buttons(self):
        raw, doc, owner, busy = self._raw(), self._raw().get("doc") or {}, self._owner(), self.win.busy
        changed = (" ".join(self.name.text().split()) != raw.get("name") or " ".join(self.line.text().split()) != (raw.get("line") or ""))
        self.meta_btn.setEnabled(changed and bool(self.name.text().strip()) and not busy)
        self.url_btn.setEnabled(self.url.text().strip() != (doc.get("deckUrl") or "") and not busy)
        for w in (self.squad, self.by_code, self.by_squad):
            w.setEnabled(owner and not busy)
        self.by_squad.setEnabled(owner and not busy and bool(self.squad.currentData()))
        self.owner_only.setVisible(not owner)
        self.has_end.setEnabled(not busy)
        self.end.setEnabled(self.has_end.isChecked() and not busy)
        self.catchup.setEnabled(not busy)
        self.taper.setEnabled(bool(doc.get("end")) and not busy)
        listed = raw.get("listed")
        why = ("Only a plan anyone with the code can follow goes in the library." if raw.get("audience") != "code"
               else "Put some dates on it first." if not P.units(doc) else "")
        self.listed.setVisible(owner and listed != -1)
        self.listed.setEnabled(owner and not busy and (not why or listed == 1))
        self.lib_said.setText(
            f"Taken out of the library. {raw.get('listedNote') or ''} It stays yours, and its followers keep following. "
            "Send feedback if it's a mistake." if listed == -1
            else "Its owner lists it in the library." if not owner
            else why or "Anyone signed in can find it, look at its calendar, follow it, or copy it into a plan of their own. "
                        "Your name shows as its author, and its code shows there.")
        self.copy_btn.setEnabled(bool(E.first_day(doc)) and not busy)
        self.delete_btn.setVisible(owner)
        self.delete_btn.setEnabled(not busy)
        it = self.coas.currentItem()
        e = self._eds()[it.data(0, Qt.ItemDataRole.UserRole)] if it is not None else None
        offered = raw.get("handover")
        self.add_btn.setVisible(owner and len(self._eds()) < 10)
        self.hand_btn.setVisible(owner and bool(e) and not e.get("pending") and not offered)
        self.unhand_btn.setVisible(owner and bool(offered))
        self.off_btn.setVisible(owner and bool(e))
        self.off_btn.setText("Take back the invite" if e and e.get("pending") else "Take them off")
        self.leave_btn.setVisible(not owner)
        for b in (self.add_btn, self.hand_btn, self.unhand_btn, self.off_btn, self.leave_btn):
            b.setEnabled(not busy)

    # ---- name, line, the deck's link, who can follow ----

    def _meta_changed(self, _t):
        if not self._loading:
            self._buttons()

    def _took(self, got, said, retry=None):
        """A settings request's answer: the plan as it is now (in the window), or why not."""
        if not got:
            self.said.setText("That didn't work: check your connection, then try again.")
            return
        outcome, what = got
        if outcome == "stale" and retry:
            self.win.took(what)
            retry()
            return
        if outcome != "saved":
            self.said.setText(str(what))
            self.plan_loaded(self.win)
            return
        self.win.took(what)
        self.said.setText(said)

    def _send(self, fields, summary, said):
        pid, version = self.win.plan["id"], self._raw().get("version")

        def again():
            v = self._raw().get("version")
            self.win.ops.ask(self.win, lambda cl: remote.save_meta(cl, pid, v, fields, summary), lambda got: self._took(got, said))
        self.win.ops.ask(self.win, lambda cl: remote.save_meta(cl, pid, version, fields, summary),
                         lambda got: self._took(got, said, again))

    def _save_meta(self):
        name, line = " ".join(self.name.text().split()), " ".join(self.line.text().split())
        if name:
            self._send({"name": name, "line": line}, "renamed it", "Saved. Followers see the new name at their next refresh.")

    def _save_url(self):
        url = self.url.text().strip()
        self.said.setText("")
        self.win._apply(lambda d: E.set_deck_url(d, url))

    def _who(self):
        if self._loading or not self._owner():
            return
        squad = self.squad.currentData()
        audience = "squad" if self.by_squad.isChecked() and squad else "code"
        raw = self._raw()
        if (squad, audience) == (raw.get("squad"), raw.get("audience")):
            self._buttons()
            return
        self._send({"audience": audience, "squad": squad}, "who can follow",
                   "Only people in that squad can follow it now." if audience == "squad" else "Anyone with the code can follow it.")

    # ---- co-authors ----

    def _eds(self):
        return [e for e in self._raw().get("editors") or [] if isinstance(e, dict)]

    def _coauthors(self):
        self.coas.clear()
        offered = self._raw().get("handover")
        for i, e in enumerate(self._eds()):
            name = str(e.get("name") or "?")
            what = "invited, waiting for a yes" if e.get("pending") else "offered the plan" if e.get("uid") == offered else "co-author"
            it = QTreeWidgetItem([name, what])
            it.setData(0, Qt.ItemDataRole.UserRole, i)
            it.setToolTip(0, f"<span>{esc(name)}</span>")
            self.coas.addTopLevelItem(it)
        self.coas.setVisible(bool(self._eds()))

    def _picked_ed(self):
        it = self.coas.currentItem()
        return self._eds()[it.data(0, Qt.ItemDataRole.UserRole)] if it is not None else None

    def _ask_coauthor(self):
        have = {self._raw().get("owner")} | {e.get("uid") for e in self._eds()}

        def got(crew):
            if crew is None:
                self.coa_said.setText("Couldn't load your crew. Try again.")
                return
            crew = [(uid, name) for uid, name in crew if uid not in have]
            if not crew:
                self.coa_said.setText("Co-authors come from your crew: you add each other.")
                return
            name, ok = ask_item(self, "Ask a co-author", "From your crew:", [n for _u, n in crew])
            if not ok:
                return
            uid = next(u for u, n in crew if n == name)
            pid = self.win.plan["id"]
            self.win.ops.ask(self.win, lambda cl: remote.add_editor(cl, pid, uid),
                             lambda r: self._took(r, f"Asked {name}. They'll see it on their home page and in Anki."))
        self.win.ops.ask(self.win, remote.crew, got)

    def _hand(self):
        e = self._picked_ed()
        if e and not e.get("pending"):
            self._offer(e["uid"])

    def _offer(self, uid):
        pid = self.win.plan["id"]
        self.win.ops.ask(self.win, lambda cl: remote.offer(cl, pid, uid),
                         lambda r: self._took(r, "They'll see it on their home page and in Anki. It's theirs once they say yes."
                                              if uid else "Taken back."))

    def _take_off(self):
        e = self._picked_ed()
        if not e:
            return
        pid, uid, name = self.win.plan["id"], e["uid"], str(e.get("name") or "?")

        def done(ok):
            if not ok:
                self.coa_said.setText(f"{name} is still {'asked' if e.get('pending') else 'a co-author'}. Try again.")
                return
            self.win._load()
        self.win.ops.ask(self.win, lambda cl: remote.remove_editor(cl, pid, uid), done)

    def _leave(self):
        if not confirm(self, f"Leave {self._raw().get('name') or 'this plan'}?",
                       "You stop co-writing it. Its tags stay on your notes until you take them off.", "Leave"):
            return
        pid, me = self.win.plan["id"], self.win.ops.me()

        def done(ok):
            if ok:
                self.win.ops.reopen(None)
            else:
                self.said.setText("That didn't work. Try again.")
        self.win.ops.ask(self.win, lambda cl: remote.remove_editor(cl, pid, me), done)

    # ---- the end, catch-up weeks, review-only days ----

    def _end(self):
        if self._loading:
            return
        end = self.end.date().toString("yyyy-MM-dd") if self.has_end.isChecked() else None
        if end == (self._raw().get("doc") or {}).get("end"):
            self._buttons()
            return
        self.win._apply(lambda d: E.set_end(d, end))

    def _phases(self):
        if self._loading:
            return
        doc = self._raw().get("doc") or {}
        ph = doc.get("phases") or {}
        c, t = int(self.catchup.currentData() or 0), int(self.taper.value()) if doc.get("end") else 0
        if (c, t) == (int(ph.get("catchup") or 0), int(ph.get("taper") or 0)):
            return
        self.win._apply(lambda d: E.set_phases(d, catchup=c, taper=t if d.get("end") else None))

    # ---- the library, next year, taking it down ----

    def _listed(self, on):
        if self._loading or not self._owner():
            return
        pid = self.win.plan["id"]
        self.win.ops.ask(self.win, lambda cl: remote.set_listed(cl, pid, on),
                         lambda r: self._took(r, "In the library." if on else "Out of the library."))

    def _next_year(self):
        doc = self._raw().get("doc") or {}
        first = E.first_day(doc)
        if not first:
            self.said.setText("The plan has no dates to copy.")
            return
        pid, name = self.win.plan["id"], E.next_year_name(self._raw().get("name"))
        start = E._later(first, 364)
        self.said.setText("Copying…")

        def job(cl):
            got = remote.copy(cl, pid, start)
            if got[0] == "saved":
                named = remote.save_meta(cl, got[1]["id"], got[1]["version"], {"name": name}, "named for next year")
                if named[0] == "saved":
                    return named
            return got

        def done(got):
            if not got:
                self.said.setText("That didn't copy: check your connection, then try again.")
            elif got[0] != "saved":
                self.said.setText(str(got[1]))
            else:
                self.said.setText(f"Copied: {got[1].get('name')}, its first date {P.fmt_day(start)}.")
                self.win.ops.reopen(got[1]["id"])
        self.win.ops.ask(self.win, job, done)

    def _delete(self):
        if not self._owner() or not confirm(
                self, f"Delete {self._raw().get('name') or 'this plan'}?",
                "It's gone for everyone. Followers keep every card they have open; nothing is suspended.", "Delete it", danger=True):
            return
        pid = self.win.plan["id"]

        def done(ok):
            if ok:
                self.win.ops.reopen(None)
            else:
                self.said.setText("That didn't work. Try again.")
        self.win.ops.ask(self.win, lambda cl: remote.delete(cl, pid), done)


class ProgressTab(_Lazy):
    """Its squad's counts a date, and the dates most of the class hasn't finished."""

    def __init__(self, win):
        super().__init__(win)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 8, 0, 0)
        self.hints = QWidget()  # the dates behind, made again at each read
        QVBoxLayout(self.hints).setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.hints)
        self.root = root
        self.said = _plain(muted=True)
        root.addWidget(self.said)
        self.list = QTreeWidget()
        self.list.setHeaderLabels(["Date", "Opened", "Done"])
        self.list.setRootIsDecorated(False)
        h = self.list.header()
        h.setStretchLastSection(False)
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in (1, 2):
            h.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.again_btn = _link("Try again", self._read)
        row.addWidget(self.again_btn)
        root.addLayout(row)
        self._show(None, "")

    def _read(self):
        now = self._now()
        if now is None:
            return
        self.loading = True
        self._show(None, "Loading…")
        pid = now[0]
        self.win.ops.ask(self.win, lambda cl: remote.progress(cl, pid), lambda got: self._got(now, got))

    def _got(self, now, pr):
        if now != self._now():
            return
        self.loading = False
        if pr is None:
            self._show(None, "Couldn't load it.", again=True)
            return
        self.got = now
        sharing, followers = int(pr.get("sharing") or 0), int(pr.get("followers") or 0)
        if not followers:
            self._show(None, "Nobody follows it yet. Once 3 or more who follow it are in its squad, "
                             "each date's counts show here.")
            return
        if sharing < 3:
            self._show(None, f"{followers:,} follow{'s' if followers == 1 else ''} it, {sharing} in its squad. "
                             "Each date's counts show once 3 or more are in it.")
            return
        self._show(pr, f"{sharing:,} of the {followers:,} following it are in its squad: these counts are theirs.")

    def _clear_hints(self):
        old, self.hints = self.hints, QWidget()
        QVBoxLayout(self.hints).setContentsMargins(0, 0, 0, 0)
        self.root.replaceWidget(old, self.hints)
        old.hide()  # off the page now, not when Qt gets round to deleting it
        old.deleteLater()

    def _show(self, pr, said, again=False):
        self._clear_hints()
        self.list.clear()
        self.said.setText(said)
        self.said.setVisible(bool(said))
        self.again_btn.setVisible(again)
        self.list.setVisible(bool(pr))
        if not pr:
            return
        doc, sharing = self.win.doc or {}, int(pr["sharing"])
        for u in sorted(P.units(doc), key=lambda u: str(u.get("opens"))):
            c = (pr.get("units") or {}).get(u["id"]) or {}
            pct = lambda k: f"{round(100 * int(c.get(k) or 0) / sharing)}% · {int(c.get(k) or 0)}"  # noqa: E731
            it = QTreeWidgetItem([f"{P.fmt_day(u['opens'])} · {u.get('name') or '?'}", pct("opened"), pct("done")])
            self.list.addTopLevelItem(it)
        today = self.win.ops.today()
        later = [u for u in P.units(doc) if str(u.get("opens")) > today]
        behind = E.behind(doc, pr, today)
        if not behind and any(E._later(u.get("due") or u["opens"], 2) <= today for u in P.units(doc)):
            row = QHBoxLayout()  # no date behind (at least half of them done with each): a word, and Pip, as Settings › Pip says
            pip = sev_label("ready", 40, "Pip, cheering") if self.win.ops.pip() else None
            if pip is not None:
                row.addWidget(pip)
            row.addWidget(_plain("The class is keeping up with every date so far."), 1)
            self.hints.layout().addLayout(row)
        for u, done, late in behind:
            row = QHBoxLayout()
            row.addWidget(role(_plain(f"{u.get('name') or '?'}: {done} of {sharing} finished, {late} days after its date."), "head"), 1)
            row.addWidget(_link("Look at that day", lambda _=False, uid=u["id"]: self._look(uid)))
            if later:
                row.addWidget(_link("Give the class a day", self._breather))
            self.hints.layout().addLayout(row)

    def _look(self, uid):
        self.win._show_tab("dates")
        self.win._go_to(("date", uid))

    def _breather(self):
        days = S.plan_days(self.win.raw["doc"])
        today = self.win.ops.today()
        if not confirm(self, "Give the class a day?",
                       "Every date still to come moves one study day later, for everyone following it; quizzes and exams stay "
                       "on their days.", "Move them"):
            return
        self.win._apply(lambda d: E.breather(d, today, days)[0])
