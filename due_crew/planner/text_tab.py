"""Your plans' Text tab (3.9.3), the builder's Text in Anki, for a plan's
authors: Add dates (lines pasted in go on; a line with a date's own day
and name adds to it) and Edit the whole plan (the plan as text: what the
text leaves out goes). Read it shows what would change, nothing does
until Add to the plan or Replace the plan's dates, one save. The rules
are text.py's (builder.js's toText and fromText). Names, tags and the
authors' words: plain text everywhere."""

from aqt.qt import (
    QApplication, QButtonGroup, QHBoxLayout, QHeaderView, QLabel, QPlainTextEdit, QPushButton, QSize, QSplitter, Qt,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..ui import confirm, esc, note
from .. import plans as P
from . import build as B
from . import edits as E
from . import text as T

FORMAT = "/plan-text"
ADD_HINT = ("Paste new lines here: an AI's answer, or your own.\n"
            "2026-10-07 | Adrenergics | tag:… | for Quiz 2\n2026-10-08 | Chapter 4 | tag:… | read: Chapter 4")


def _plain(text="", muted=False):
    w = QLabel(str(text))
    w.setTextFormat(Qt.TextFormat.PlainText)
    w.setWordWrap(True)
    return note(w) if muted else w


class _Short:
    """A box that asks for less height than Qt's 192: the window sizes to what its tabs ask."""
    ASK = 120

    def sizeHint(self):
        s = super().sizeHint()
        return QSize(s.width(), min(s.height(), self.ASK))


class _TextBox(_Short, QPlainTextEdit):
    ASK = 150


class _Preview(_Short, QTreeWidget):
    ASK = 110


class TextTab(QWidget):
    """One plan's Text, for its authors. win: the PlanWindow."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.whole = False
        self.pending = None    # Add or Replace sent: its whole, till the save lands
        self.put = ""          # the plan's text as this tab last put it in the box (Edit the whole plan)
        self.read_now = None   # (text, whole, r, using, gone) once Read it has read it
        self.kept = []         # Keep the tags: their names, said once
        self.taken = None      # Take them off those dates too: what it did, date by date
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 8, 0, 0)
        # all of it in a splitter: the window keeps its own height whatever the wrapped lines here would like
        split = QSplitter(Qt.Orientation.Vertical)
        split.setChildrenCollapsible(False)
        outer.addWidget(split)
        upper = QWidget()
        root = QVBoxLayout(upper)
        root.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.modes = QButtonGroup(self)
        for i, label in enumerate(("Add dates", "Edit the whole plan")):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setChecked(i == 0)
            self.modes.addButton(b, i)
            row.addWidget(b)
        self.modes.idClicked.connect(self._mode)
        row.addStretch(1)
        self.format_btn = QPushButton("The whole format")
        self.format_btn.setFlat(True)
        self.format_btn.setToolTip("<span>Every kind of line, on duecrew.com</span>")
        self.format_btn.clicked.connect(lambda: self.win.ops.open_page(FORMAT))
        row.addWidget(self.format_btn)
        root.addLayout(row)
        self.hint = _plain(muted=True)
        root.addWidget(self.hint)
        self.box = _TextBox()
        self.box.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.box.setPlaceholderText(ADD_HINT)
        self.box.textChanged.connect(self._changed)
        self.box.setMinimumHeight(90)
        root.addWidget(self.box, 1)
        split.addWidget(upper)  # the text over what it would change, each as tall as it's dragged
        lower = QWidget()
        low = QVBoxLayout(lower)
        low.setContentsMargins(0, 6, 0, 0)
        row = QHBoxLayout()
        self.read_btn = QPushButton("Read it")
        self.read_btn.clicked.connect(self._read)
        row.addWidget(self.read_btn)
        self.copy_btn = QPushButton("Copy the plan as text")
        self.copy_btn.setFlat(True)
        self.copy_btn.clicked.connect(self._copy)
        row.addWidget(self.copy_btn)
        row.addStretch(1)
        low.addLayout(row)
        self.status = _plain()
        low.addWidget(self.status)
        self.preview = _Preview()
        self.preview.setMinimumHeight(70)
        self.preview.setHeaderLabels(["", "", "", ""])
        self.preview.setRootIsDecorated(False)
        self.preview.setHeaderHidden(True)
        h = self.preview.header()
        h.setStretchLastSection(False)
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        low.addWidget(self.preview, 1)
        self.said = _plain()
        low.addWidget(self.said)
        row = QHBoxLayout()
        self.take_btn = QPushButton("Take them off those dates too")
        self.take_btn.clicked.connect(self._take_all)
        self.keep_btn = QPushButton("Keep the tags")
        self.keep_btn.clicked.connect(self._keep_tags)
        self.go_btn = QPushButton("Add to the plan")
        self.go_btn.setDefault(True)
        self.go_btn.clicked.connect(self._go)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setFlat(True)
        self.cancel_btn.clicked.connect(self._clear)
        for b in (self.take_btn, self.keep_btn):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(self.cancel_btn)
        row.addWidget(self.go_btn)
        low.addLayout(row)
        split.addWidget(lower)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        self._loading = False
        self._clear()

    # ---- the window asks ----

    def shown(self, win):
        return win.author()

    def plan_loaded(self, win):
        if not win.author():
            return
        self._hint()
        if self.whole and self.box.toPlainText() == self.put:
            self._fill_whole()  # untouched: the plan as it is now
        elif self.whole:
            self._clear()
            self.status.setText("The plan changed since this text was made: Read it shows what it would change now.")
            return
        self._clear()

    def busy_changed(self, win):
        if win.author():
            self._buttons()

    def saved(self, win):
        """A save landed: one of this tab's, the box emptied (Add) or the plan's text again (Replace)."""
        if self.pending is None:
            return
        whole, self.pending = self.pending, None
        n = len(P.units(self._doc()))
        if whole:
            self._fill_whole()
        else:
            self._loading = True
            self.box.setPlainText("")
            self._loading = False
        self._clear()
        self.status.setText(f"{'Added. ' if not whole else ''}Now {n:,} date{'s' if n != 1 else ''}.")

    # ---- the text ----

    def _doc(self):
        return self.win.raw["doc"]

    def _name(self):
        return (self.win.plan or {}).get("name") or ""

    def _start(self):
        return B.plan_start(self._doc(), B.next_monday(self.win.ops.today()))

    def _hint(self):
        n = len(P.units(self._doc()))
        self.hint.setText(f"Adds to the plan's {n:,} date{'s' if n != 1 else ''}. Changes nothing already there."
                          if not self.whole else "Read it shows what would change. Nothing does until you Replace the plan's dates.")

    def _fill_whole(self):
        self._loading = True
        self.put = T.to_text(self._doc())
        self.box.setPlainText(self.put)
        self._loading = False

    def _mode(self, i):
        self.whole = i == 1
        self.box.setPlaceholderText("" if self.whole else ADD_HINT)
        if self.whole:
            self._fill_whole()
        else:
            self._loading = True
            self.box.setPlainText("")
            self._loading = False
        self._hint()
        self._clear()

    def _changed(self):
        if not self._loading and self.read_now is not None:
            self._clear(keep_status=False)

    def _copy(self):
        QApplication.clipboard().setText(T.to_text(self._doc()))
        self.status.setText("Copied: the plan as text.")

    def _read_text(self, doc, text, whole):
        return T.from_text(doc, self.win.deck_tree(), text, whole=whole, start=B.plan_start(doc, self._start()),
                           plan_name=self._name(), new_id=lambda: E.new_id(doc))

    # ---- Read it, and what it would change ----

    def _clear(self, keep_status=False):
        self.read_now, self.taken = None, None
        self.preview.clear()
        self.preview.setVisible(False)
        self.said.setText("")
        self.said.setVisible(False)
        if not keep_status:
            self.status.setText("")
        self._buttons()

    def _buttons(self):
        r = self.read_now[2] if self.read_now else None
        busy = self.win.busy
        self.read_btn.setEnabled(not busy and bool(self.box.toPlainText().strip()))
        using = bool(self.read_now and self.read_now[3])
        for b in (self.take_btn, self.keep_btn):
            b.setVisible(using)
            b.setEnabled(not busy)
        anything = bool(r and (r["units"] or r["events"] or r["tags"] or r["remarks"]))
        self.go_btn.setVisible(bool(r) and (self.whole or anything))
        self.go_btn.setEnabled(not busy)
        self.go_btn.setText("Replace anyway" if self.whole and using else "Replace the plan's dates" if self.whole else "Add to the plan")
        self.go_btn.setProperty("dc", "bad" if self.whole and self.read_now and self.read_now[4] else "go")
        self.go_btn.style().unpolish(self.go_btn)
        self.go_btn.style().polish(self.go_btn)
        self.cancel_btn.setVisible(bool(r))

    def _read(self):
        text, whole, doc = self.box.toPlainText(), self.whole, self._doc()
        r = self._read_text(doc, text, whole)
        if self.taken is not None:
            T.take_all(doc, r, self.win.deck_tree(), self._name())
        self._show(text, whole, r)

    def _show(self, text, whole, r):
        doc, tree = self._doc(), self.win.deck_tree()
        self.preview.clear()
        if r["errors"]:
            self.read_now = None
            self.status.setText(" ".join(r["errors"][:6]))
            self.preview.setVisible(False)
            self.said.setVisible(False)
            self._buttons()
            return
        if not (r["units"] or r["events"] or r["why"] or r["notes"] or r["tags"] or r["remarks"]):
            self.read_now = None
            self.status.setText("Nothing to read yet.")
            self._buttons()
            return
        bits = [f"{len(r['units'])} date{'s' if len(r['units']) != 1 else ''}"]
        for key, word in (("events", "event"), ("tags", "tag"), ("remarks", "note")):
            if r[key]:
                bits.append(f"{len(r[key])} {word}{'s' if len(r[key]) != 1 else ''}")
        miss = r["missing"]
        self.status.setText(", ".join(bits) + "." + (f" Not in your deck (they'd find nothing): "
                                                     f"{', '.join(B.path_of(k) for k in miss[:5])}{'…' if len(miss) > 5 else ''}" if miss else ""))
        placed = {k for u in r["units"] for k in B.srcs(u)}
        ours = f"tag:DueCrew::{T.root_of(doc, self._name())}::".lower()
        olds = {u["id"]: u for u in P.units(doc)}

        def row(a, b, c="", d=""):
            it = QTreeWidgetItem([str(a), str(b), str(c), str(d)])
            it.setToolTip(2, f"<span>{esc(c)}</span>")
            self.preview.addTopLevelItem(it)
        for t in r["tags"]:
            was = next((x for x in P.plan_tags(doc) if x.get("id") == t["id"]), None)
            what = ", ".join(p for p in (f"{len(t['notes']):,} note{'s' if len(t['notes']) != 1 else ''}" if t.get("notes") else "",
                                         f"{len(t['cards']):,} single card{'s' if len(t['cards']) != 1 else ''}" if t.get("cards") else "",
                                         f"from {', '.join(T.ptag_from(t))}" if T.ptag_from(t) else "") if p)
            extra = " · adds to it" if not whole and was else f" · was {was['name']}" if was and was.get("name") != t["name"] else ""
            row("Tag" if was else "New tag", f"{t['name']}{extra}", what)
        for u in sorted(r["units"], key=lambda u: u["opens"]):
            old = olds.get(u["id"])
            extra = (" · adds to this date" if not whole and old else
                     f" · moved from {P.fmt_day(old['opens'])}" if whole and old and old["opens"] != u["opens"] else
                     f" · was {old.get('name')}" if whole and old and str(old.get("name")).strip() != str(u["name"]).strip() else "")
            names = [B.label(tree, k, placed) if (tree is not None and tree.has(k)) or k.lower().startswith(ours) else f"{B.path_of(k)} (not found)"
                     for k in B.srcs(u)]
            names += [f"{P._word(c['tag'].split('::')[-1])} · {self._ptag_name(r, c['in'])}" for c in u.get("cut") or []]
            uncounted = bool(u.get("cut")) or any(k.lower().startswith(ours) for k in B.srcs(u))
            n = B.unit_total(tree, u, placed) if tree is not None else 0
            cards = "counted in your Anki after you save" if not n and uncounted else f"{n:,}{'+' if uncounted else ''} cards"
            when = f"to {P.fmt_day(u['due'])}{', evenly' if u.get('even') else ''} · " if u.get("due") else ""
            row(P.fmt_day(u["opens"]), f"{u['name']}{extra}", ", ".join(names), when + cards)
        for x in r["remarks"]:
            on = (f"{x['card'][0]} · card {int(x['card'][1]) + 1}" if x.get("card") else
                  next((t.get("name") for t in r["tags"] + P.plan_tags(doc)
                        if T.ptag_path(doc, t, self._name()).lower() == str(x["tag"]).lower()), None) or T._name(x["tag"]))
            row("Note" if any(B.remark_same(x, y) for y in T._remarks(doc)) else "New note", on, x["text"])
        gone_units, gone_tags, gone_rmk = T.gone(doc, r, whole)
        uses = T.using(doc, r, whole, self._name()) if self.taken is None else []
        said = []
        if gone_units:
            said.append(f"Takes off {len(gone_units)} date{'s' if len(gone_units) != 1 else ''}: "
                        + " · ".join(f"{P.fmt_day(u['opens'])}, {u.get('name')}" for u in gone_units[:6])
                        + (f" and {len(gone_units) - 6} more" if len(gone_units) > 6 else "") + ".")
        if gone_rmk:
            said.append(f"Takes off {len(gone_rmk)} note{'s' if len(gone_rmk) != 1 else ''}.")
        if self.kept:
            said.append(f"{', '.join(self.kept)} stay{'s' if len(self.kept) == 1 else ''}: "
                        f"{'its line is' if len(self.kept) == 1 else 'their lines are'} back in the text.")
            self.kept = []
        if gone_tags and uses:
            said.append(f"Takes off {len(gone_tags)} tag{'s' if len(gone_tags) != 1 else ''}: {', '.join(t.get('name') for t in gone_tags)}. "
                        f"{len(uses)} date{' still uses' if len(uses) == 1 else 's still use'} {'it' if len(gone_tags) == 1 else 'them'}: "
                        + "; ".join(f"{P.fmt_day(u['opens'])} · {u['name']} ({why})" for u, why in uses[:8])
                        + (f"; and {len(uses) - 8} more" if len(uses) > 8 else "") + ". What these dates already opened stays open.")
        elif gone_tags:
            said.append(f"Takes off {len(gone_tags)} tag{'s' if len(gone_tags) != 1 else ''}: {', '.join(t.get('name') for t in gone_tags)}."
                        + (" " + " ".join(self.taken[:8]) if self.taken else ""))
        pace = dict({"mode": "placed", "days": [1] * 7, "daily": 20}, **(doc.get("pace") or {}))
        runs, cap = T.heavy_after(doc, tree, r, whole, pace, self._start())
        if runs:
            said.append("Over your pace: " + " · ".join(
                f"{P.fmt_day(x['a']) if x['a'] == x['b'] else P.fmt_day(x['a']) + ' – ' + P.fmt_day(x['b'])}, {x['top']:,} new a day"
                for x in runs[:6]) + f" (pace {cap:,} a day).")
        said += r["warns"][:4]
        if r["notes"]:
            said.append("To pick in Anki: " + " · ".join(T.pick_note(n) for n in r["notes"]))
        if r["why"]:
            said.append(f"Its notes ({len(r['why'])}), not kept: " + " · ".join(w[:300] for w in r["why"][:6]))
        self.said.setText("\n".join(said))
        self.said.setVisible(bool(said))
        self.preview.setVisible(self.preview.topLevelItemCount() > 0)
        self.read_now = (text, whole, r, bool(uses), bool(gone_units or gone_tags or gone_rmk))
        self._buttons()

    def _ptag_name(self, r, tid):
        return next((t.get("name") for t in r["tags"] + P.plan_tags(self._doc()) if t.get("id") == tid), "?")

    def _take_all(self):
        if not self.read_now:
            return
        text, whole, r = self.read_now[:3]
        self.taken = T.take_all(self._doc(), r, self.win.deck_tree(), self._name())
        self._show(text, whole, r)

    def _keep_tags(self):
        if not self.read_now:
            return
        text, whole, r = self.read_now[:3]
        new, self.kept = T.keep_tags(self._doc(), text, r)
        self._loading = True
        self.box.setPlainText(new)
        self._loading = False
        self._read()

    # ---- Add to the plan, Replace the plan's dates ----

    def _go(self):
        if not self.read_now:
            return
        text, whole, r = self.read_now[:3]
        gone_units, gone_tags, gone_rmk = T.gone(self._doc(), r, whole)
        if whole and (gone_units or gone_tags or gone_rmk) and not confirm(
                self, "Replace the plan's dates?", "What the text leaves out comes off the plan, for everyone following it. "
                "What their dates already opened stays open.", "Replace them", danger=True):
            return
        take = self.taken is not None
        made = {}

        def change(doc):
            got = self._read_text(doc, text, whole)
            if got["errors"]:
                raise E.Refused(" ".join(got["errors"][:3]))
            if take:
                T.take_all(doc, got, self.win.deck_tree(), self._name())
            made["ids"] = {u["id"] for u in got["units"]}
            return T.apply(doc, got, whole, self._name(), new_id=lambda: E.new_id(doc))
        self.pending = whole
        self.win._apply(change, lambda: made.get("ids", ()))
        if not self.win.busy and self.pending is not None:
            self.pending = None  # refused before it went, or nothing to change: the window says which
