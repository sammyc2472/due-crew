"""Sign in / Join dialog. Network runs in the background; the dialog never
blocks Anki. On success, self.user holds (user_id, display_name)."""

from aqt.qt import (
    QDialog, QLabel, QLineEdit, QPushButton, QHBoxLayout, QVBoxLayout,
    QTabWidget, QTimer, QWidget, Qt,
)

from . import attach_alive, run_bg

ERRORS = {
    "INVALID_LOGIN_CREDENTIALS": "Email or password is incorrect.",
    "INVALID_PASSWORD": "Incorrect password.",
    "EMAIL_NOT_FOUND": "No account for that email.",
    "EMAIL_EXISTS": "That email already has an account. Sign in instead.",
    "WEAK_PASSWORD": "Password needs at least 6 characters.",
    "INVALID_EMAIL": "That doesn't look like an email address.",
    "TOO_MANY_ATTEMPTS_TRY_LATER": "Too many tries. Wait a few minutes.",
    "NETWORK": "Can't reach the server. Check your connection.",
}


class AuthDialog(QDialog):
    def __init__(self, parent, client, server_label="", on_join_server=None):
        super().__init__(parent)
        self.client = client
        self.server_label = server_label
        self.on_join_server = on_join_server
        self.user = None
        attach_alive(self)
        self._build()

    def _build(self):
        self.setWindowTitle("Due Crew")
        self.setMinimumWidth(380)
        root = QVBoxLayout(self)

        if self.server_label:
            server = QLabel(f"Server: <b>{self.server_label}</b>")
            server.setStyleSheet("font-size: 11px;")
            root.addWidget(server)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._signin_tab(), "Sign in")
        self.tabs.addTab(self._join_tab(), "Join")
        self.tabs.currentChanged.connect(self._tab_changed)
        root.addWidget(self.tabs)

        self.error = QLabel("")
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #d32f2f; font-size: 12px;")
        root.addWidget(self.error)

        buttons = QHBoxLayout()
        if self.on_join_server:
            other = QPushButton("Use a different crew server…")
            other.setFlat(True)
            other.setCursor(Qt.CursorShape.PointingHandCursor)
            other.setStyleSheet("color: #2e7d32; border: none; font-size: 11px;")
            other.clicked.connect(self._other_server)
            buttons.addWidget(other)
        buttons.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.go = QPushButton("Sign in")
        self.go.setDefault(True)
        self.go.clicked.connect(self._submit)
        buttons.addWidget(self.go)
        root.addLayout(buttons)

    def _other_server(self):
        cb = self.on_join_server
        self.reject()
        if cb:
            QTimer.singleShot(0, cb)

    def _field(self, layout, label, placeholder, password=False):
        layout.addWidget(QLabel(label))
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        if password:
            edit.setEchoMode(QLineEdit.EchoMode.Password)
        edit.returnPressed.connect(self._submit)
        layout.addWidget(edit)
        return edit

    def _signin_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.in_email = self._field(lay, "Email", "you@example.com")
        self.in_email.setText(self.client.email)
        self.in_pw = self._field(lay, "Password", "", password=True)
        forgot = QPushButton("Forgot password?")
        forgot.setFlat(True)
        forgot.setCursor(Qt.CursorShape.PointingHandCursor)
        forgot.setStyleSheet("color: #2e7d32; text-align: left; border: none;")
        forgot.clicked.connect(self._reset)
        lay.addWidget(forgot, alignment=Qt.AlignmentFlag.AlignLeft)
        lay.addStretch()
        return w

    def _join_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.up_email = self._field(lay, "Email", "you@example.com")
        self.up_pw = self._field(lay, "Password (6+ characters)", "", password=True)
        self.up_name = self._field(lay, "Display name", "How your crew sees you")
        lay.addStretch()
        return w

    def _tab_changed(self, i):
        self.error.setText("")
        self.go.setText("Sign in" if i == 0 else "Join")

    # ---- actions ----

    def _busy(self, on, text=None):
        self.go.setEnabled(not on)
        self.tabs.setEnabled(not on)
        if text:
            self.go.setText(text)

    def _submit(self):
        if not self.go.isEnabled():
            return  # returnPressed while a request is in flight
        self.error.setStyleSheet("color: #d32f2f; font-size: 12px;")
        self.error.setText("")
        joining = self.tabs.currentIndex() == 1
        if joining:
            email = self.up_email.text().strip()
            pw = self.up_pw.text()
            name = self.up_name.text().strip()
            if not name:
                self.error.setText("Pick a display name.")
                return
        else:
            email = self.in_email.text().strip()
            pw = self.in_pw.text()
        if "@" not in email:
            self.error.setText(ERRORS["INVALID_EMAIL"])
            return
        if len(pw) < 6:
            self.error.setText(ERRORS["WEAK_PASSWORD"])
            return

        self._busy(True, "Joining…" if joining else "Signing in…")
        job = ((lambda: self.client.sign_up(email, pw, name)) if joining
               else (lambda: self.client.sign_in(email, pw)))

        def done(result, err):
            self._busy(False, "Join" if joining else "Sign in")
            if err:
                self.error.setText(
                    ERRORS.get(err, err.replace("_", " ").capitalize()))
                return
            self.user = result
            self.accept()

        run_bg(self, job, done)

    def _reset(self):
        if not self.go.isEnabled():
            return
        email = self.in_email.text().strip()
        if "@" not in email:
            self.error.setText("Enter your email first, then tap Forgot password.")
            return
        self._busy(True)

        def done(_, err):
            self._busy(False)
            if err:
                self.error.setText(ERRORS.get(err, ERRORS["NETWORK"]))
            else:
                self.error.setStyleSheet("color: #2e7d32; font-size: 12px;")
                self.error.setText(f"Reset link sent to {email}.")

        run_bg(self, lambda: self.client.send_reset(email) or True, done)
