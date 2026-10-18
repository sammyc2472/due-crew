"""3.8.1, Browse › Due Crew: note for the plan's followers…: one line on
one card, for everyone following a plan I write or co-author. It rides the
plan (a version, in its History), so followers' Anki shows it when that
card comes up, with no request of its own. What goes to the plan is the
card's guid and card number and my words, never the card's text. One note
a card a plan: the one there is edited or taken off here. Requests, all on
a click: my plans when the sheet opens, then the note (an edit adds the new
words, then takes the old ones off)."""

from aqt.qt import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QPushButton, Qt, QVBoxLayout,
)

from . import attach_alive, run_bg, tone
from .. import plans as P

TEXT_MAX = 280  # the server's: one line, 1 to 280


class RemarkDialog(QDialog):
    """guid, ord_: the card (its note's guid, its card number from 0).
    on_done(message) runs on the main thread once the plan has it."""

    def __init__(self, parent, client, guid, ord_, on_done=None):
        super().__init__(parent)
        self.client, self.card, self.on_done = client, [str(guid), int(ord_)], on_done
        self.plans = []
        attach_alive(self)
        self.setWindowTitle("Note for the plan's followers")
        self.setMinimumWidth(440)
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.plan = QComboBox()
        self.plan.currentIndexChanged.connect(self._plan_changed)
        form.addRow("Plan", self.plan)
        self.text = QLineEdit()
        self.text.setMaxLength(TEXT_MAX)
        self.text.setPlaceholderText("One line, shown with this card")
        self.text.textChanged.connect(lambda *_: self._ready())
        form.addRow("Note", self.text)
        root.addLayout(form)
        self.where = QLabel("")
        self.where.setTextFormat(Qt.TextFormat.PlainText)  # plan names come from the server
        self.where.setWordWrap(True)
        self.where.setStyleSheet(f"color: {tone('muted')}; font-size: 11.5px;")
        root.addWidget(self.where)
        self.status = QLabel("Looking for your plans…")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.remove_btn = QPushButton("Take it off")
        self.remove_btn.setVisible(False)
        self.remove_btn.clicked.connect(lambda: self._send(remove=True))
        self.buttons.addButton(self.remove_btn, QDialogButtonBox.ButtonRole.ActionRole)
        self.save_btn = QPushButton("Save")
        self.save_btn.setDefault(True)
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(lambda: self._send(remove=False))
        self.buttons.addButton(self.save_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)
        me = client.user_id
        run_bg(self, client.my_plans, lambda plans, err: self._loaded(
            None if err else [p for p in plans or [] if p.get("owner") == me or p.get("role") == "editor"]))

    def _loaded(self, plans):
        if plans is None:
            self.status.setText("Couldn't reach Due Crew. Check your connection.")
            return
        self.plans = plans
        if not plans:
            self.status.setText("Only a plan's author or co-authors write notes for its followers.")
            return
        self.status.setText("")
        self.plan.blockSignals(True)
        for p in plans:
            self.plan.addItem(P.plan_title(p), p["id"])  # a combo shows plain text
        # the plan that already has a note on this card, else the first
        have = next((i for i, p in enumerate(plans) if self._existing(p)), 0)
        self.plan.setCurrentIndex(have)
        self.plan.blockSignals(False)
        self._plan_changed()

    def _current(self):
        pid = self.plan.currentData()
        return next((p for p in self.plans if p["id"] == pid), None)

    def _existing(self, p):
        """The note this plan has on this card, or None."""
        return next((r for r in ((p or {}).get("doc") or {}).get("remarks") or []
                     if r.get("card") and [str(r["card"][0]), int(r["card"][1])] == self.card), None)

    def _plan_changed(self, *_):
        p = self._current()
        had = self._existing(p)
        self.text.setText((had or {}).get("text") or "")
        self.remove_btn.setVisible(bool(had))
        self.where.setText(f"Everyone following {p.get('name') or 'it'} sees it when this card comes up. "
                           "Only the card's ID goes to the plan; its text stays here." if p else "")
        self._ready()

    def _ready(self):
        p = self._current()
        words = " ".join(self.text.text().split())
        self.save_btn.setEnabled(bool(p) and bool(words) and words != ((self._existing(p) or {}).get("text") or ""))

    def _send(self, remove):
        p = self._current()
        words = " ".join(self.text.text().split())[:TEXT_MAX]
        if not p or (not remove and not words):
            return
        had = self._existing(p)
        if remove and not had:
            return
        self.save_btn.setEnabled(False)
        self.remove_btn.setEnabled(False)
        self.status.setText("Taking it off…" if remove else "Saving…")
        cl, pid, card = self.client, p["id"], list(self.card)

        def job():
            if remove:
                return cl.plan_remark(pid, remove=had["id"])
            got, status = cl.plan_remark(pid, add={"card": card, "text": words})
            # the Worker changes a card's note in place (same id, new words); only
            # if the old one were still there with its old words would it go
            old = next((r for r in ((got or {}).get("doc") or {}).get("remarks") or [] if had and r.get("id") == had["id"]), None)
            if got is not None and old is not None and old.get("text") != words:
                got, status = cl.plan_remark(pid, remove=had["id"])
            return got, status

        def done(result, err):
            got, status = result if result else (None, 0)
            if got is None:
                self.save_btn.setEnabled(True)
                self.remove_btn.setEnabled(True)
                self.status.setText({403: "Only the plan's author or co-authors write notes for its followers.",
                                     404: "That note is gone already." if remove else "That plan is gone.",
                                     400: "That note didn't take. Try it shorter, on one line.",
                                     409: "That's more than the plan holds: 300 notes a plan."}.get(
                    status, "Couldn't save it. Check your connection."))
                return
            if self.on_done:
                name = p.get("name") or "the plan"
                self.on_done(f"Took the note off this card in {name}." if remove
                             else f"Saved. Everyone following {name} sees it when this card comes up.")
            self.accept()

        run_bg(self, job, done)
