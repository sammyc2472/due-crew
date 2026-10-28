"""3.9.5, Tools › Due Crew › Game night…: what to play from tonight, then
the TV (game_night_tv.py) or Try it with bots. Custom builds a scope:
decks and tags in or out, which of their cards, and the Anki search it
comes to, which can be edited. The counts are the collection's, worked out
here on the main thread a moment after each change; nothing is sent until
Open the TV (one request, gamenight_flow.Ops.start)."""

from aqt.qt import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                    QPushButton, QRadioButton, QSpinBox, Qt, QTimer, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from . import attach_alive, heading, note, role

FLAGS = (("Red", 1), ("Orange", 2), ("Green", 3), ("Blue", 4))
MARK = {"in": "✓ ", "out": "– ", "": ""}
GAMES = (("trivia", "Trivia"), ("rounds", "Rounds"), ("links", "Links"), ("imposter", "Imposter"), ("draw", "Draw it"), ("between", "Somewhere between"))


class GameNightWindow(QDialog):
    def __init__(self, parent, ops):
        super().__init__(parent)
        attach_alive(self)
        self.ops = ops
        self.marks = {}
        self.setWindowTitle("Game night")
        root = QVBoxLayout(self)
        heading(self, root)
        root.addWidget(role(QLabel("Play from"), "head"))
        self.radios = []
        self.sources = ops.sources()
        for s in self.sources:
            r = QRadioButton(f"{s['label']} · {s['n']:,} card{'s' if s['n'] != 1 else ''}")
            r.setProperty("key", s["key"])
            r.setProperty("label", s["label"])
            r.toggled.connect(self._picked)
            root.addWidget(r)
            self.radios.append(r)
        self.custom_r = QRadioButton("Custom…")
        self.custom_r.setProperty("key", "custom")
        self.custom_r.setProperty("label", "Custom")
        self.custom_r.toggled.connect(self._picked)
        root.addWidget(self.custom_r)
        self.radios.append(self.custom_r)
        first = next((r for r, s in zip(self.radios, self.sources) if s["n"]), self.custom_r)
        first.setChecked(True)

        self.custom = QWidget()
        cols = QHBoxLayout(self.custom)
        cols.setContentsMargins(0, 6, 0, 0)
        cols.addLayout(self._tree_col(), 3)
        cols.addLayout(self._which_col(), 3)
        cols.addLayout(self._result_col(), 2)
        root.addWidget(self.custom)

        self.said = note(QLabel(""))
        self.said.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(self.said)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.bots_btn = QPushButton("Try it with bots")
        self.bots_btn.clicked.connect(lambda: self._start(bots=True))
        self.tv_btn = QPushButton("Open the TV")
        self.tv_btn.setDefault(True)
        self.tv_btn.clicked.connect(lambda: self._start(bots=False))
        buttons.addButton(self.bots_btn, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(self.tv_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(300)
        self.timer.timeout.connect(self.refresh)
        self._picked()

    # ---- the custom scope ----

    def _tree_col(self):
        col = QVBoxLayout()
        col.addWidget(role(QLabel("Decks and tags"), "head"))
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumWidth(220)
        self.tree.setToolTip("Click once to put it in, again to leave it out, again to clear.")
        roots = {"deck": QTreeWidgetItem(self.tree, ["Decks"]), "tag": QTreeWidgetItem(self.tree, ["Tags"])}
        stack = {"deck": [], "tag": []}
        for key, label, depth in self.ops.tree():
            kind = key.split(":", 1)[0]
            if kind not in roots:
                continue
            st = stack[kind]
            del st[depth:]
            parent = st[-1] if st else roots[kind]
            item = QTreeWidgetItem(parent, [label])
            item.setData(0, Qt.ItemDataRole.UserRole, key)
            item.setData(0, Qt.ItemDataRole.UserRole + 1, label)
            st.append(item)
        for r in roots.values():
            r.setExpanded(True)
        self.tree.itemClicked.connect(self._mark)
        col.addWidget(self.tree)
        return col

    def _mark(self, item, _col=0):
        key = item.data(0, Qt.ItemDataRole.UserRole)
        if not key:
            return
        now = {"": "in", "in": "out", "out": ""}[self.marks.get(key, "")]
        if now:
            self.marks[key] = now
        else:
            self.marks.pop(key, None)
        item.setText(0, MARK[now] + item.data(0, Qt.ItemDataRole.UserRole + 1))
        self._changed()

    def _which_col(self):
        col = QVBoxLayout()
        col.addWidget(role(QLabel("Which of their cards"), "head"))
        self.seen = QCheckBox("Seen before")
        self.seen.setChecked(True)
        col.addWidget(self.seen)
        self.missed, self.missed_n = self._numbered(col, "Missed in the last", 7, 1, 365, "days")
        self.due, self.due_n = self._numbered(col, "Due in the next", 3, 1, 365, "days")
        self.hard, self.hard_n = self._numbered(col, "Missed", 3, 2, 99, "times or more")
        row = QHBoxLayout()
        self.flagged = QCheckBox("Flagged")
        row.addWidget(self.flagged)
        self.flags = []
        for name, n in FLAGS:
            b = QCheckBox(name)
            b.setProperty("flag", n)
            b.toggled.connect(self._changed)
            row.addWidget(b)
            self.flags.append(b)
        row.addStretch(1)
        col.addLayout(row)
        self.slow = QCheckBox("Slow but right")
        col.addWidget(self.slow)
        row = QHBoxLayout()
        self.from_plan = QCheckBox("From")
        self.plan = QComboBox()
        for pid, name in self.ops.plans():
            self.plan.addItem(f"{name}, this week", pid)
        row.addWidget(self.from_plan)
        row.addWidget(self.plan, 1)
        self.from_plan.setVisible(self.plan.count() > 0)
        self.plan.setVisible(self.plan.count() > 0)
        col.addLayout(row)
        for w in (self.seen, self.flagged, self.slow, self.from_plan):
            w.toggled.connect(self._changed)
        self.plan.currentIndexChanged.connect(self._changed)
        row = QHBoxLayout()
        row.addWidget(role(QLabel("Search"), "head"))
        row.addStretch(1)
        self.edit = QPushButton("Edit")
        self.edit.setCheckable(True)
        self.edit.toggled.connect(self._editing)
        row.addWidget(self.edit)
        col.addLayout(row)
        self.search = QPlainTextEdit()
        self.search.setReadOnly(True)
        self.search.setMaximumHeight(70)
        self.search.textChanged.connect(lambda: self.edit.isChecked() and self._changed())
        col.addWidget(self.search)
        col.addStretch(1)
        return col

    def _numbered(self, col, words, value, lo, hi, after):
        row = QHBoxLayout()
        box = QCheckBox(words)
        n = QSpinBox()
        n.setRange(lo, hi)
        n.setValue(value)
        n.valueChanged.connect(self._changed)
        box.toggled.connect(self._changed)
        row.addWidget(box)
        row.addWidget(n)
        row.addWidget(QLabel(after))
        row.addStretch(1)
        col.addLayout(row)
        return box, n

    def _result_col(self):
        col = QVBoxLayout()
        col.addWidget(role(QLabel("Tonight"), "head"))
        self.count = role(QLabel(""), "title")
        col.addWidget(self.count)
        self.fit = QLabel("")
        self.fit.setTextFormat(Qt.TextFormat.PlainText)
        col.addWidget(self.fit)
        col.addWidget(role(QLabel("Sample questions"), "head"))
        self.samples = note(QLabel(""))
        self.samples.setTextFormat(Qt.TextFormat.PlainText)  # card text, plain
        col.addWidget(self.samples)
        row = QHBoxLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("Name")
        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self._save)
        row.addWidget(self.name, 1)
        row.addWidget(self.save_btn)
        col.addLayout(row)
        col.addStretch(1)
        return col

    def _editing(self, on):
        self.search.setReadOnly(not on)
        self.edit.setText("Use the ticks" if on else "Edit")
        self._changed()

    def scope(self):
        """The custom scope as the window has it (gamenight.scope_search's)."""
        return {
            "in": sorted(k for k, v in self.marks.items() if v == "in"),
            "out": sorted(k for k, v in self.marks.items() if v == "out"),
            "seen": self.seen.isChecked(),
            "missed": self.missed_n.value() if self.missed.isChecked() else 0,
            "due": self.due_n.value() if self.due.isChecked() else 0,
            "lapses": self.hard_n.value() if self.hard.isChecked() else 0,
            "flags": [b.property("flag") for b in self.flags if b.isChecked()] if self.flagged.isChecked() else [],
            "slow": self.slow.isChecked(),
            "plan": self.plan.currentData() if self.from_plan.isChecked() and self.plan.count() else None,
            "search": self.search.toPlainText().strip() if self.edit.isChecked() else "",
        }

    def _changed(self, *_):
        self.timer.start()

    def refresh(self):
        if not self.custom_r.isChecked():
            return
        got = self.ops.preview(self.scope())
        if not self.edit.isChecked():
            self.search.blockSignals(True)
            self.search.setPlainText(got["search"])
            self.search.blockSignals(False)
        n = got["n"]
        self.count.setText(f"{n:,} card{'s' if n != 1 else ''}")
        have = got.get("fit") or {}
        self.fit.setText("\n".join(f"{name}: {have.get(g, 0)}" for g, name in GAMES))
        self.samples.setText("\n\n".join(f"{q['q']}\n→ {q['opts'][q['ans']]}" for q in got.get("samples") or []) or "None yet.")

    def _picked(self, *_):
        if not hasattr(self, "custom"):
            return
        self.custom.setVisible(self.custom_r.isChecked())
        self.said.setText("")
        if self.custom_r.isChecked():
            self.refresh()
        self.adjustSize()

    def _save(self):
        name = self.ops.save(self.name.text(), self.scope())
        self.said.setText(f"Saved as {name}." if name else "Couldn't save it.")

    # ---- going ----

    def _chosen(self):
        r = next((x for x in self.radios if x.isChecked()), self.custom_r)
        return r.property("key"), r.property("label")

    def _start(self, bots):
        key, label = self._chosen()
        scope = self.scope() if key == "custom" else None
        if key == "custom" and self.name.text().strip():
            label = self.name.text().strip()
        for b in (self.bots_btn, self.tv_btn):
            b.setEnabled(False)
        self.said.setText("" if bots else "Opening a table…")

        def done(err):
            if not getattr(self, "_alive", False):
                return
            for b in (self.bots_btn, self.tv_btn):
                b.setEnabled(True)
            if err:
                self.said.setText(err)
            else:
                self.accept()
        self.ops.start(key, scope, label, bots, done)
