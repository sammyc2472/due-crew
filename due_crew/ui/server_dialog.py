"""Crew-server dialogs. Join: browse names, enter name + code, switch.
Register: paste a Firebase web config, get back a name + code to share.
Both talk only to the directory on the default project.

The join code is kept in the saved server config (next to the apiKey it
guards) so the Friends dialog can assemble a complete invite."""

import html

from aqt.qt import (
    QApplication, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QPushButton, Qt, QTimer, QVBoxLayout,
)
from aqt.utils import openLink, tooltip

from . import accent, attach_alive, copy_text, danger, run_bg
from ..backend import directory

WALKTHROUGH_URL = "https://github.com/sammyc2472/due-crew#run-your-own-crew-server"


class WelcomeDialog(QDialog):
    """First-run doors. self.choice: 'join', 'start', or 'signin'."""

    def __init__(self, parent):
        super().__init__(parent)
        self.choice = None
        self.setWindowTitle("Due Crew")
        self.setMinimumWidth(340)
        root = QVBoxLayout(self)

        intro = QLabel("Your friends' studying next to yours.\n"
                       "Crews run on their own servers.")
        intro.setAlignment(Qt.AlignmentFlag.AlignCenter)
        intro.setStyleSheet("font-size: 12.5px; margin-bottom: 6px;")
        root.addWidget(intro)

        self._door(root, "Join your crew",
                   "Someone sent you a name and a code.", "join", primary=True)
        self._door(root, "Start a new crew",
                   "One person sets up the server — about ten minutes, free.",
                   "start")

        signin = QPushButton("Already have an account? Sign in")
        signin.setFlat(True)
        signin.setCursor(Qt.CursorShape.PointingHandCursor)
        signin.setStyleSheet(f"color: {accent()}; border: none; font-size: 11.5px;")
        signin.clicked.connect(lambda: self._pick("signin"))
        root.addWidget(signin, alignment=Qt.AlignmentFlag.AlignCenter)

    def _door(self, root, label, sub, choice, primary=False):
        btn = QPushButton(label)
        btn.setMinimumHeight(34)
        if primary:
            btn.setDefault(True)
        btn.clicked.connect(lambda: self._pick(choice))
        root.addWidget(btn)
        sub_label = QLabel(sub)
        sub_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub_label.setStyleSheet("font-size: 11px; margin-bottom: 6px;")
        root.addWidget(sub_label)

    def _pick(self, choice):
        self.choice = choice
        self.accept()


class StartCrewDialog(QDialog):
    """Founder framing before the register form. accept() = continue."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Due Crew — Start a new crew")
        self.setMinimumWidth(380)
        root = QVBoxLayout(self)
        for line in (
            "• One person per crew does this — everyone else just joins "
            "with the name and code you'll get.",
            "• About ten minutes: create a Firebase project, flip two "
            "settings, paste two values.",
            "• Your crew's data lives on your project, on Firebase's free plan.",
        ):
            label = QLabel(line)
            label.setWordWrap(True)
            root.addWidget(label)

        guide = QPushButton("Open the step-by-step walkthrough")
        guide.setFlat(True)
        guide.setCursor(Qt.CursorShape.PointingHandCursor)
        guide.setStyleSheet(f"color: {accent()}; border: none; text-align: left;")
        guide.clicked.connect(lambda: openLink(WALKTHROUGH_URL))
        root.addWidget(guide, alignment=Qt.AlignmentFlag.AlignLeft)

        buttons = QHBoxLayout()
        buttons.addStretch()
        back = QPushButton("Back")
        back.clicked.connect(self.reject)
        buttons.addWidget(back)
        go = QPushButton("Continue")
        go.setDefault(True)
        go.clicked.connect(self.accept)
        buttons.addWidget(go)
        root.addLayout(buttons)


class JoinServerDialog(QDialog):
    """on_switch(config) performs the actual switch; {} means the default.
    on_register (optional) opens the founder flow from here, so creating a
    server is reachable before ever signing in."""

    def __init__(self, parent, current_name, on_switch, on_register=None):
        super().__init__(parent)
        self.on_switch = on_switch
        self.on_register = on_register
        self.current_name = current_name
        self.joined = False
        attach_alive(self)
        self._build()
        QTimer.singleShot(0, self._browse)

    def _build(self):
        self.setWindowTitle("Due Crew — Join a crew server")
        self.setMinimumWidth(380)
        root = QVBoxLayout(self)

        if self.current_name:
            current = QLabel(f"Current server: <b>{html.escape(self.current_name)}</b>")
            current.setStyleSheet("font-size: 12px;")
            root.addWidget(current)

        root.addWidget(QLabel("<b>Browse</b>"))
        self.listing = QListWidget()
        self.listing.setMaximumHeight(120)
        self.listing.itemClicked.connect(
            lambda item: self.name_input.setText(item.text()))
        root.addWidget(self.listing)

        root.addWidget(QLabel("<b>Name</b>"))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("brave-otter-4712")
        root.addWidget(self.name_input)
        root.addWidget(QLabel("<b>Code</b>"))
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("6-character code")
        self.code_input.setMaxLength(6)
        self.code_input.returnPressed.connect(self._join)
        root.addWidget(self.code_input)

        self.error = QLabel("")
        self.error.setWordWrap(True)
        self.error.setStyleSheet(f"color: {danger()}; font-size: 12px;")
        root.addWidget(self.error)

        buttons = QHBoxLayout()
        if self.on_register:
            register = QPushButton("Register your own…")
            register.clicked.connect(self._register)
            buttons.addWidget(register)
        if self.current_name:
            default_btn = QPushButton("Use the default server")
            default_btn.clicked.connect(self._use_default)
            buttons.addWidget(default_btn)
        buttons.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.join_btn = QPushButton("Join")
        self.join_btn.setDefault(True)
        self.join_btn.clicked.connect(self._join)
        buttons.addWidget(self.join_btn)
        root.addLayout(buttons)

    def _register(self):
        cb = self.on_register
        self.reject()
        if cb:
            QTimer.singleShot(0, cb)

    def _browse(self):
        self.listing.clear()
        self.listing.addItem("Loading…")

        def done(names, err):
            self.listing.clear()
            if err or names is None:
                self.listing.addItem("Couldn't load the list — type a name instead.")
                return
            if not names:
                self.listing.addItem("No servers registered yet.")
                return
            for n in names:
                self.listing.addItem(n)

        run_bg(self, directory.browse_names, done)

    def _use_default(self):
        self.joined = True
        self.on_switch({})
        self.accept()

    def _join(self):
        if not self.join_btn.isEnabled():
            return
        name = self.name_input.text().strip().lower()
        code = self.code_input.text().strip().upper()
        if not name or len(code) != 6:
            self.error.setText("Enter the server name and its 6-character code.")
            return
        self.error.setText("")
        self.join_btn.setEnabled(False)
        self.join_btn.setText("Joining…")

        def done(conf, err):
            self.join_btn.setEnabled(True)
            self.join_btn.setText("Join")
            if err:
                self.error.setText("Can't reach the directory. Check your connection.")
                return
            if conf is None:
                self.error.setText("No server matches that name and code.")
                return
            conf["code"] = code
            self.joined = True
            self.on_switch(conf)
            self.accept()

        run_bg(self, lambda: directory.lookup_server(name, code), done)


class RegisterServerDialog(QDialog):
    def __init__(self, parent, on_switch, prefill=None):
        super().__init__(parent)
        self.on_switch = on_switch
        self.prefill = prefill  # (api_key, project_id) of a custom server
        self.result = None  # (name, code, config)
        self.used = False
        attach_alive(self)
        self._build()

    def _build(self):
        self.setWindowTitle("Due Crew — Register your server")
        self.setMinimumWidth(420)
        root = QVBoxLayout(self)

        intro = QLabel("Runs your crew on your own Firebase project. The "
                       "README walks through the ten-minute setup; paste the "
                       "web config here when it's done.")
        intro.setWordWrap(True)
        intro.setStyleSheet("font-size: 12px;")
        root.addWidget(intro)

        root.addWidget(QLabel("<b>API key</b>"))
        self.key_input = QLineEdit()
        self.key_input.setPlaceholderText("AIzaSy…")
        root.addWidget(self.key_input)
        root.addWidget(QLabel("<b>Project ID</b>"))
        self.project_input = QLineEdit()
        self.project_input.setPlaceholderText("my-crew-firebase")
        root.addWidget(self.project_input)
        root.addWidget(QLabel("<b>Crew name</b> — optional"))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g. busm — blank for a generated name")
        self.name_input.setMaxLength(40)
        root.addWidget(self.name_input)
        name_note = QLabel("3–40 characters: lower-case letters, digits, "
                           "dashes. First come, first named — the code still "
                           "gates joining.")
        name_note.setStyleSheet("font-size: 11px;")
        name_note.setWordWrap(True)
        root.addWidget(name_note)
        if self.prefill and all(self.prefill):
            self.key_input.setText(self.prefill[0])
            self.project_input.setText(self.prefill[1])

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("font-size: 12px;")
        root.addWidget(self.status)

        self.result_box = QLabel("")
        self.result_box.setWordWrap(True)
        self.result_box.setTextInteractionFlags(
            self.result_box.textInteractionFlags())
        self.result_box.hide()
        root.addWidget(self.result_box)

        buttons = QHBoxLayout()
        self.check_btn = QPushButton("Check connection")
        self.check_btn.clicked.connect(self._check)
        buttons.addWidget(self.check_btn)
        self.copy_btn = QPushButton("Copy both")
        self.copy_btn.clicked.connect(self._copy)
        self.copy_btn.hide()
        buttons.addWidget(self.copy_btn)
        self.use_btn = QPushButton("Use this server now")
        self.use_btn.clicked.connect(self._use)
        self.use_btn.hide()
        buttons.addWidget(self.use_btn)
        buttons.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        self.go_btn = QPushButton("Register")
        self.go_btn.setDefault(True)
        self.go_btn.clicked.connect(self._register)
        buttons.addWidget(self.go_btn)
        root.addLayout(buttons)

    def _inputs(self):
        return self.key_input.text().strip(), self.project_input.text().strip()

    def _check(self):
        api_key, project = self._inputs()
        if not api_key or not project:
            self.status.setText("Paste both fields first.")
            return
        self.status.setText("Checking…")

        def done(ok, err):
            if err:
                self.status.setText("Can't reach Firebase. Check your connection.")
            elif ok:
                self.status.setText("Connection looks good — email sign-in is enabled.")
            else:
                self.status.setText("That API key didn't answer like a Firebase "
                                    "project with email sign-in. Re-check both "
                                    "fields and the auth setting.")

        run_bg(self, lambda: directory.check_project(api_key), done)

    def _register(self):
        if not self.go_btn.isEnabled():
            return
        api_key, project = self._inputs()
        if not api_key or not project:
            self.status.setText("Paste both fields first.")
            return
        custom = self.name_input.text().strip().lower()
        if custom and not directory.valid_custom_name(custom):
            self.status.setText("Crew names are 3–40 characters: lower-case "
                                "letters, digits, dashes.")
            return
        self.go_btn.setEnabled(False)
        self.go_btn.setText("Registering…")

        def done(result, err):
            self.go_btn.setEnabled(True)
            self.go_btn.setText("Register")
            if result == "TAKEN":
                self.status.setText(f"\u201c{custom}\u201d is taken — "
                                    f"pick another name.")
                return
            if err or not result:
                self.status.setText("Registration failed. Check your connection "
                                    "and that anonymous auth is enabled on the "
                                    "default project.")
                return
            name, code = result
            self.result = (name, code, {"apiKey": api_key, "projectId": project,
                                        "name": name, "code": code})
            self.status.setText("")
            self.result_box.setText(
                f"<b>Registered.</b><br>Name (say it aloud): <b>{name}</b><br>"
                f"Code (share privately): "
                f"<b style='font-family: monospace; letter-spacing: 2px;'>{code}</b>"
                f"<br><span style='font-size: 11px;'>Friends join from the "
                f"sign-in screen with these two.</span>")
            self.result_box.show()
            self.copy_btn.show()
            self.use_btn.show()

        def job():
            try:
                return directory.register_server(api_key, project,
                                                 custom_name=custom or None)
            except directory.NameTaken:
                return "TAKEN"

        run_bg(self, job, done)

    def _copy(self):
        if self.result:
            name, code, _conf = self.result
            copy_text(f"Server: {name}\nCode: {code}")
            tooltip("Copied.")

    def _use(self):
        if self.result:
            self.used = True
            self.on_switch(self.result[2])
            self.accept()
