"""Export cards for my AI (3.6.5, P3): the notes a plan covers, in Anki's
own plain-text format with each note's unique identifier, written to a
file the person picks. The cards go to that file only: nothing is sent.
3.8.1: with a plan picked, the plan itself (its dates as its text writes
them, with each date's cards here and what overlaps; its tags; its notes)
as comment lines at the top, ticked by default; never a card's text there.
One request, on a click: the plans I write (my_plans), for their docs;
and (3.8.1) one more when I pick a plan I write but don't follow, for all
of its doc (my_plans leaves a date's single cards out)."""

import os
import re

from aqt.qt import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QLabel, QVBoxLayout,
)

from . import attach_alive, run_bg
from .. import plans as P

BIG = 2 * 1024 * 1024  # past this, most AI chats want it in parts


def _kb(n):
    return f"{max(1, round(n / 1024)):,} KB" if n < 1024 * 1024 else f"{n / 1024 / 1024:.1f} MB"


class ExportDialog(QDialog):
    def __init__(self, parent, col, client, followed=(), state=None, on_saved=None):
        """followed: the plans I follow (the session's, with docs); state:
        plan_flow's per-plan state, for the deck and tag swap I run them on."""
        super().__init__(parent)
        self.col, self.client, self.state = col, client, state or {}
        self.on_saved = on_saved
        self.plans = [p for p in followed or [] if p.get("doc")]
        attach_alive(self)
        self.setWindowTitle("Export cards for my AI")
        self.setMinimumWidth(440)
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.plan = QComboBox()
        self.deck = QComboBox()
        self.scope = QComboBox()
        form.addRow("Plan", self.plan)
        form.addRow("Deck", self.deck)
        form.addRow("Cards", self.scope)
        root.addLayout(form)
        self.size = QLabel("")
        self.size.setWordWrap(True)
        root.addWidget(self.size)
        self.plain = QCheckBox("Leave out formatting and images (smaller)")
        self.plain.setChecked(True)
        root.addWidget(self.plain)
        # 3.8.1: the plan itself at the top of the file, as comment lines (never card text)
        self.with_plan = QCheckBox("With the plan (its dates, tags, notes and what overlaps)")
        self.with_plan.setChecked(True)
        root.addWidget(self.with_plan)
        note = QLabel("Saved as a file on this computer, for you to attach to your AI chat. "
                      "Due Crew doesn't send it anywhere.")
        note.setWordWrap(True)
        note.setStyleSheet("color: palette(placeholder-text);")
        root.addWidget(note)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.go = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.go.setText("Export…")
        self.buttons.accepted.connect(self._export)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)

        self.decks = P.deck_choices(col)  # [(did, name)]
        for did, name in self.decks:
            self.deck.addItem(name, did)
        self._fill_plans()
        self.plan.currentIndexChanged.connect(self._plan_changed)
        self.deck.currentIndexChanged.connect(self._update)
        self.scope.currentIndexChanged.connect(self._update)
        self._plan_changed()
        if client is not None and getattr(client, "signed_in", False):
            run_bg(self, client.my_plans, lambda got, err: self._mine(None if err else got))

    # -- plans --

    def _fill_plans(self):
        keep = self.plan.currentData()
        self.plan.blockSignals(True)
        self.plan.clear()
        for p in self.plans:
            self.plan.addItem(P.plan_title(p), p["id"])
        self.plan.addItem("None: a whole deck", "")
        i = self.plan.findData(keep) if keep is not None else -1
        self.plan.setCurrentIndex(i if i >= 0 else 0)
        self.plan.blockSignals(False)

    def _mine(self, got):
        have = {p["id"] for p in self.plans}
        self.plans += [dict(p, _lean=True) for p in got or [] if p.get("doc") and p["id"] not in have]
        self._fill_plans()
        self._plan_changed()

    def _current(self):
        pid = self.plan.currentData()
        return next((p for p in self.plans if p["id"] == pid), None)

    def _full(self, pid, got):
        if not got or not got.get("doc"):
            return
        self.plans = [got if x["id"] == pid else x for x in self.plans]
        if self.plan.currentData() == pid:
            self._update()

    def _plan_changed(self, *_):
        p = self._current()
        if p and p.get("_lean") and self.client is not None:
            p["_lean"] = False  # once: its whole doc, for what its dates open
            run_bg(self, lambda pid=p["id"]: self.client.plan(pid), lambda got, err, pid=p["id"]: self._full(pid, None if err else got))
        did = None
        if p:
            st = self.state.get(p["id"]) or {}
            did = st.get("deck_id")
            if did is None:
                want = str(p["doc"].get("deck") or "").lower()
                did = next((d for d, n in self.decks if n.lower() == want), None)
        if did is not None:
            i = self.deck.findData(did)
            if i >= 0:
                self.deck.setCurrentIndex(i)
        self.deck.setEnabled(not p or did is None)
        self.with_plan.setVisible(bool(p))
        self.scope.blockSignals(True)
        self.scope.clear()
        if p:
            self.scope.addItem("What the plan's dates open", "dates")
            if ((p["doc"].get("pace") or {}).get("cover")):
                self.scope.addItem("What the plan covers", "cover")
        self.scope.addItem("The whole deck", "deck")
        self.scope.blockSignals(False)
        self._update()

    # -- what goes in --

    def _nids(self):
        did = self.deck.currentData()
        if did is None:
            return set()
        p = self._current()
        idx = P.DeckIndex(self.col, did)
        swap = ((self.state.get(p["id"]) or {}).get("swap") if p else None) or None
        return P.export_scope(idx, p["doc"] if p else {}, self.scope.currentData() or "deck", swap)

    def _update(self, *_):
        nids = self._nids()
        if not nids:
            self.size.setText("Nothing to export here.")
            self.go.setEnabled(False)
            return
        size = P.export_size(self.col, nids)
        line = f"{len(nids):,} notes · about {_kb(size)}."
        line += (" That's big for one AI chat: try what the plan's dates open, or a smaller deck."
                 if size > BIG else " Most AI chats take a file this size.")
        self.size.setText(line)
        self.go.setEnabled(True)

    def _export(self):
        nids = self._nids()
        if not nids:
            return
        p = self._current()
        base = re.sub(r"[^A-Za-z0-9]+", "-", (p or {}).get("name") or self.deck.currentText() or "cards").strip("-") or "cards"
        desk = os.path.join(os.path.expanduser("~"), "Desktop")
        start = os.path.join(desk if os.path.isdir(desk) else os.path.expanduser("~"), f"{base[:60]}-cards.txt")
        path, _ = QFileDialog.getSaveFileName(self, "Export cards for my AI", start, "Text (*.txt)")
        if not path:
            return
        save(self.col, nids, path, self.plain.isChecked(), self.on_saved, plan_lines=self.plan_lines())
        self.accept()

    def plan_lines(self):
        """3.8.1: the picked plan as comment lines for the file's top (P.export_plan_lines),
        or None: no plan, or With the plan unticked. The plan itself, not my shifted days."""
        p = self._current()
        did = self.deck.currentData()
        if not p or did is None or not self.with_plan.isChecked():
            return None
        swap = (self.state.get(p["id"]) or {}).get("swap") or None
        return P.export_plan_lines(P.DeckIndex(self.col, did), p.get("plan_doc") or p["doc"], p.get("name") or "", swap)


def save(col, nids, path, plain=True, on_saved=None, plan_lines=None):
    """Write the notes to `path` (main thread: it reads the collection);
    3.8.1, with the plan's lines at the top when given."""
    text, n = P.export_notes(col, nids, plain, plan_lines=plan_lines)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    if on_saved:
        on_saved(n, path)
    return n
