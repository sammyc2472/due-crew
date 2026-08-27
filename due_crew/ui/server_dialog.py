"""Crew-server dialogs. Join: browse names, enter name + code, switch.
Register: paste a Firebase web config, get back a name + code to share.
Both talk only to the directory on the default project."""

from aqt.qt import (
    QApplication, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QPushButton, QTimer, QVBoxLayout,
)
from aqt.utils import tooltip

from . import attach_alive, run_bg
from ..backend import directory


class JoinServerDialog(QDialog):
    """on_switch(config) performs the actual switch; {} means the default.
    on_register (optional) opens the founder flow from here, so creating a
    server is reachable before ever signing in."""

    def __init__(self, parent, current_name, on_switch, on_register=None):
        super().__init__(parent)
        self.on_switch = on_switch
        self.on_register = on_register
        self.current_name = current_name
        attach_alive(self)
        self._build()
        QTimer.singleShot(0, self._browse)

    def _build(self):
        self.setWindowTitle("Due Crew — Join a crew server")
        self.setMinimumWidth(380)
        root = QVBoxLayout(self)

        if self.current_name:
            current = QLabel(f"Current server: <b>{self.current_name}</b>")
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
        self.error.setStyleSheet("color: #d32f2f; font-size: 12px;")
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
            self.on_switch(conf)
            self.accept()

        run_bg(self, lambda: directory.lookup_server(name, code), done)


class RegisterServerDialog(QDialog):
    def __init__(self, parent, on_switch):
        super().__init__(parent)
        self.on_switch = on_switch
        self.result = None  # (name, code, config)
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
        self.go_btn.setEnabled(False)
        self.go_btn.setText("Registering…")

        def done(result, err):
            self.go_btn.setEnabled(True)
            self.go_btn.setText("Register")
            if err or not result:
                self.status.setText("Registration failed. Check your connection "
                                    "and that anonymous auth is enabled on the "
                                    "default project.")
                return
            name, code = result
            self.result = (name, code, {"apiKey": api_key, "projectId": project,
                                        "name": name})
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

        run_bg(self, lambda: directory.register_server(api_key, project), done)

    def _copy(self):
        if self.result:
            name, code, _conf = self.result
            QApplication.clipboard().setText(f"Server: {name}\nCode: {code}")
            tooltip("Copied.")

    def _use(self):
        if self.result:
            self.on_switch(self.result[2])
            self.accept()
