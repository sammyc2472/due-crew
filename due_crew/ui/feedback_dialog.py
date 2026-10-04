"""Send feedback (3.6.5, P6): one box, and the versions if ticked.
It goes to the admin page with my name and emoji; the admin can write back to
my email from Due Crew. One request, on Send, in the background."""

from aqt.qt import QCheckBox, QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, Qt, QVBoxLayout

from . import attach_alive, run_bg
from ..app import feedback_versions as versions
from ..backend.api import FEEDBACK_MAX


class FeedbackDialog(QDialog):
    def __init__(self, parent, client, addon_version, on_sent=None):
        super().__init__(parent)
        self.client, self.addon_version, self.on_sent = client, addon_version, on_sent
        attach_alive(self)
        self.setWindowTitle("Send feedback")
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        self.box = QPlainTextEdit()
        self.box.setPlaceholderText("What's working, what isn't, what you'd add…")
        self.box.setMinimumHeight(120)
        self.box.textChanged.connect(self._changed)
        lay.addWidget(self.box)
        self.ver = QCheckBox("Include my Due Crew and Anki versions")
        self.ver.setChecked(True)
        lay.addWidget(self.ver)
        note = QLabel("Due Crew sees your name and emoji with it, and can write back to your email. Nobody else sees it.")
        note.setWordWrap(True)
        note.setStyleSheet("color: palette(placeholder-text);")
        lay.addWidget(note)
        self.status = QLabel("")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.send_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.send_btn.setText("Send")
        self.send_btn.setEnabled(False)
        buttons.accepted.connect(self._send)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _text(self):
        return self.box.toPlainText().strip()

    def _changed(self):
        n = len(self._text())
        self.send_btn.setEnabled(0 < n <= FEEDBACK_MAX)
        self.status.setText(f"{n:,} of {FEEDBACK_MAX:,} characters: shorten it a little." if n > FEEDBACK_MAX else "")

    def _send(self):
        text = self._text()
        if not text or len(text) > FEEDBACK_MAX:
            return
        ver = versions(self.addon_version) if self.ver.isChecked() else ""
        self.send_btn.setEnabled(False)
        self.status.setText("Sending…")

        def done(status, err):
            if status == 201:
                if self.on_sent:
                    self.on_sent()
                self.accept()
                return
            self.send_btn.setEnabled(True)
            self.status.setText("That's five today. Send more tomorrow." if status == 429
                                else "Couldn't send it. Check your connection and try again.")

        run_bg(self, lambda: self.client.send_feedback(text, ver), done)
