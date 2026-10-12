"""3.8.0, plan tags: the notes picked in Anki's browser put on one of a
plan's own tags (SLG 12), or taken off it. Only plans I own or co-author.
What goes to the plan is the tag's name and each note's guid, never its
text; everyone following gets the tag on their own notes with the plan's
next update. Two requests, both on a click: my plans when the sheet opens,
and the tag."""

from aqt.qt import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QPushButton, Qt, QVBoxLayout,
)

from . import attach_alive, run_bg
from .. import plans as P

PER_TAG = 5000  # plans.ts IDLIST_MAX: a tag's notes


class TagDialog(QDialog):
    """guids: the picked notes' guids. on_done(plan, name, path, added, taken)
    runs on the main thread once the plan has it."""

    def __init__(self, parent, client, guids, on_done=None):
        super().__init__(parent)
        self.client, self.guids = client, list(dict.fromkeys(guids))
        self.on_done = on_done
        self.plans = []
        attach_alive(self)
        n = len(self.guids)
        self.setWindowTitle("Tag for a plan")
        self.setMinimumWidth(440)
        root = QVBoxLayout(self)
        head = QLabel(f"Tag {n:,} note{'s' if n != 1 else ''} for a plan")
        head.setStyleSheet("font-weight: 600;")
        root.addWidget(head)
        form = QFormLayout()
        self.plan = QComboBox()
        self.plan.currentIndexChanged.connect(self._plan_changed)
        form.addRow("Plan", self.plan)
        self.tag = QComboBox()
        self.tag.setEditable(True)
        self.tag.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.tag.lineEdit().setMaxLength(40)
        self.tag.lineEdit().setPlaceholderText("SLG 12")
        self.tag.currentTextChanged.connect(self._tag_changed)
        form.addRow("Tag", self.tag)
        root.addLayout(form)
        self.where = QLabel("")
        self.where.setTextFormat(Qt.TextFormat.PlainText)  # names come from the server
        self.where.setWordWrap(True)
        self.where.setStyleSheet("color: palette(placeholder-text); font-size: 11.5px;")
        root.addWidget(self.where)
        self.status = QLabel("Looking for your plans…")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.take_btn = QPushButton("Take off")
        self.take_btn.setVisible(False)
        self.take_btn.clicked.connect(lambda: self._send(take=True))
        self.buttons.addButton(self.take_btn, QDialogButtonBox.ButtonRole.ActionRole)
        self.add_btn = QPushButton(f"Tag {n:,} note{'s' if n != 1 else ''}")
        self.add_btn.setDefault(True)
        self.add_btn.setEnabled(False)
        self.add_btn.clicked.connect(lambda: self._send(take=False))
        self.buttons.addButton(self.add_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)
        if n > PER_TAG:
            self.status.setText(f"A tag holds up to {PER_TAG:,} notes. Pick fewer, or split them over two tags.")
            return
        me = client.user_id
        run_bg(self, client.my_plans, lambda plans, err: self._loaded(
            None if err else [p for p in plans or [] if p.get("owner") == me or p.get("role") == "editor"]))

    def _loaded(self, plans):
        if plans is None:
            self.status.setText("Couldn't reach Due Crew. Check your connection.")
            return
        self.plans = plans
        if not plans:
            self.status.setText("Only a plan's author or co-authors tag for it. "
                                "Make one: Tools › Due Crew › Make a plan from a deck…")
            return
        self.status.setText("")
        for p in plans:
            self.plan.addItem(P.plan_title(p), p["id"])  # a combo shows plain text
        self._plan_changed()

    def _current(self):
        pid = self.plan.currentData()
        return next((p for p in self.plans if p["id"] == pid), None)

    def _existing(self, name):
        p = self._current()
        part = P.tag_part(name).lower()
        return next((t for t in P.plan_tags((p or {}).get("doc")) if P.tag_part(t.get("name")).lower() == part), None)

    def _plan_changed(self, *_):
        p = self._current()
        typed = self.tag.currentText()
        self.tag.blockSignals(True)
        self.tag.clear()
        for t in P.plan_tags((p or {}).get("doc")):
            n = len(t.get("notes") or [])
            self.tag.addItem(t["name"], t["id"])
            self.tag.setItemData(self.tag.count() - 1, f"{n:,} notes" if n else "made from tags", Qt.ItemDataRole.ToolTipRole)
        self.tag.setCurrentIndex(-1)
        self.tag.setEditText(typed)
        self.tag.blockSignals(False)
        self._tag_changed()

    def _path(self, name):
        p = self._current() or {}
        doc = p.get("doc") or {}
        root = doc.get("tagroot") or P.tag_root(p.get("name"))
        return P.tag_path({"tagroot": root}, {"name": name})

    def _tag_changed(self, *_):
        p = self._current()
        name = self.tag.currentText().strip()
        t = self._existing(name) if name else None
        inside = len(set(self.guids) & set((t or {}).get("notes") or []))
        self.take_btn.setVisible(bool(inside))
        self.take_btn.setText(f"Take {inside:,} off")
        self.add_btn.setEnabled(bool(p) and bool(name) and len(self.guids) <= PER_TAG)
        if p and name:
            self.where.setText(f"Everyone following {p.get('name') or 'it'} gets it with the plan's next update, "
                               f"as {self._path(name)}. Only the notes' IDs go to the plan; their text stays here.")
        else:
            self.where.setText("")

    def _send(self, take):
        p = self._current()
        name = self.tag.currentText().strip()[:40]
        if not p or not name:
            return
        self.add_btn.setEnabled(False)
        self.take_btn.setEnabled(False)
        self.status.setText("Taking them off…" if take else "Tagging…")
        cl, pid = self.client, p["id"]
        before = set(((self._existing(name) or {}).get("notes")) or [])
        guids = [g for g in self.guids if g in before] if take else self.guids

        def done(result, err):
            got, status = result if result else (None, 0)
            if got is None:
                self.add_btn.setEnabled(True)
                self.take_btn.setEnabled(True)
                self.status.setText({403: "Only the plan's author or co-authors tag for it.",
                                     404: "That tag is gone already.",
                                     400: "That's more notes than one tag holds (5,000)."}.get(
                    status, "Couldn't tag them. Check your connection."))
                return
            doc = got.get("doc") or {}
            path = P.tag_path(doc, {"name": name})
            if self.on_done:
                self.on_done(got, name, path, [] if take else guids, guids if take else [])
            self.accept()

        run_bg(self, lambda: cl.tag_plan_notes(pid, name, remove=guids) if take
               else cl.tag_plan_notes(pid, name, add=guids), done)
