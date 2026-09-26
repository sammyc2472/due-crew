"""Sign in (3.0): an email, then the six-digit code it gets, then a display
name when the account doesn't have one yet. No passwords. Network runs in
the background; the dialog never blocks Anki. On success, self.user holds
(user_id, display_name) and self.joined says whether it was a new account
(the welcome screen follows)."""

import platform

from aqt.qt import (
    QDialog, QDialogButtonBox, QLabel, QLineEdit, QPushButton, QStackedWidget, QVBoxLayout,
    QWidget, Qt,
)

from . import accent, attach_alive, danger, logo_label, run_bg

ERRORS = {
    "bad_email": "That doesn't look like an email address.",
    "wrong_code": "That code isn't right.",
    "expired": "That code has expired. Send a new one.",
    "locked": "Too many tries. Wait an hour, then send a new code.",
    "slow_down": "Too many codes. Wait a bit, then try again.",
    "NETWORK": "Can't reach the server. Check your connection.",
}


def _device():
    try:
        return f"Anki on {platform.system() or 'a computer'}"
    except Exception:
        return "Anki"


class AuthDialog(QDialog):
    def __init__(self, parent, client, join=None):
        """join: kept for callers from 2.x; one flow signs in and joins."""
        super().__init__(parent)
        self.client = client
        self.user = None
        self.joined = False
        self._uid = ""
        attach_alive(self)
        self._build()

    def _build(self):
        self.setWindowTitle("Due Crew")
        self.setMinimumWidth(380)
        root = QVBoxLayout(self)
        logo = logo_label()
        if logo is not None:
            root.addWidget(logo)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._email_page())
        self.pages.addWidget(self._code_page())
        self.pages.addWidget(self._name_page())
        root.addWidget(self.pages)

        self.error = QLabel("")
        self.error.setWordWrap(True)
        self.error.setStyleSheet(f"color: {danger()}; font-size: 12px;")
        root.addWidget(self.error)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        self.go = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.go.setDefault(True)
        self.go.clicked.connect(self._submit)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._show(0)

    def _field(self, layout, label, placeholder):
        if label:
            layout.addWidget(QLabel(label))
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        edit.returnPressed.connect(self._submit)
        layout.addWidget(edit)
        return edit

    def _link(self, text, slot):
        b = QPushButton(text)
        b.setFlat(True)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet(f"color: {accent()}; text-align: left; border: none;")
        b.clicked.connect(slot)
        return b

    def _email_page(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.email = self._field(lay, "Email", "you@example.com")
        self.email.setText(self.client.email)
        note = QLabel("We'll email you a code. No password.")
        note.setStyleSheet("font-size: 12px; opacity: 0.7;")
        lay.addWidget(note)
        lay.addStretch()
        return w

    def _code_page(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.sent_to = QLabel("")
        self.sent_to.setWordWrap(True)
        self.sent_to.setTextFormat(Qt.TextFormat.PlainText)
        # two lines, always: an address long enough to wrap mustn't be clipped
        self.sent_to.setMinimumHeight(2 * self.sent_to.fontMetrics().lineSpacing() + 4)
        lay.addWidget(self.sent_to)
        self.code = self._field(lay, "", "123 456")
        self.code.setMaxLength(9)
        lay.addWidget(self._link("Send a new code", self._resend), alignment=Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(self._link("Use a different email", lambda: self._show(0)),
                      alignment=Qt.AlignmentFlag.AlignLeft)
        lay.addStretch()
        return w

    def _name_page(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.name = self._field(lay, "Display name", "How your crew sees you")
        self.name.setMaxLength(60)
        lay.addStretch()
        return w

    def _show(self, page):
        self.pages.setCurrentIndex(page)
        self.error.setText("")
        self.go.setText(("Send Code", "Sign In", "Done")[page])
        (self.email, self.code, self.name)[page].setFocus()

    # ---- actions ----

    def _busy(self, on, text=None):
        self.go.setEnabled(not on)
        self.pages.setEnabled(not on)
        if text:
            self.go.setText(text)

    def _fail(self, err, again):
        self._busy(False, again)
        self.error.setStyleSheet(f"color: {danger()}; font-size: 12px;")
        self.error.setText(ERRORS.get(err, ERRORS["NETWORK"]))

    def _submit(self):
        if not self.go.isEnabled():
            return  # returnPressed while a request is in flight
        self.error.setText("")
        page = self.pages.currentIndex()
        if page == 0:
            self._send()
        elif page == 1:
            self._verify()
        else:
            self._save_name()

    def _send(self):
        email = self.email.text().strip()
        if "@" not in email:
            self.error.setText(ERRORS["bad_email"])
            return
        self._busy(True, "Sending…")

        def done(_result, err):
            if err:
                self._fail(err, "Send Code")
                return
            self._busy(False)
            self.sent_to.setText(f"We sent a code to {email}. It works for 10 minutes.")
            self.code.clear()
            self._show(1)

        run_bg(self, lambda: self.client.request_code(email) or True, done)

    def _resend(self):
        if not self.go.isEnabled():
            return
        self._show(0)
        self._send()

    def _verify(self):
        code = "".join(ch for ch in self.code.text() if ch.isdigit())
        if len(code) != 6:
            self.error.setText("The code is six digits.")
            return
        email = self.email.text().strip()
        self._busy(True, "Signing in…")

        def done(result, err):
            if err or not result:
                self._fail(err, "Sign In")
                return
            self._busy(False)
            self._uid = result["uid"]
            self.joined = bool(result["new"])
            if result["name"] and not result["new"]:
                self.user = (result["uid"], result["name"])
                self.accept()
                return
            self.name.setText(result["name"] or "")
            self._show(2)

        run_bg(self, lambda: self.client.verify_code(email, code, _device()), done)

    def _save_name(self):
        name = " ".join(self.name.text().split())
        if not name:
            self.error.setText("Pick a display name.")
            return
        self._busy(True, "Saving…")

        def done(ok, err):
            if err or not ok:
                self._fail(err, "Done")
                return
            self.user = (self._uid, name)
            self.accept()

        run_bg(self, lambda: self.client.set_display_name(name), done)
