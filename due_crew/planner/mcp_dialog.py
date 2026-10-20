"""Your AI app (docs/planner.md): the switch for the local MCP server
(mcp.py), off by default and this computer's own; when it's on, its
address, its token (Copy, New token) and the setup to copy into an AI app
here (Copy setup: through the shim, mcp_shim.py; Copy HTTP setup: the
address with the bearer header). Nothing is sent from Anki by it."""

from aqt.qt import (
    QCheckBox, QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, Qt,
    QVBoxLayout, QWidget,
)

from ..ui import attach_alive, confirm, copy_text, heading, note

SWITCH = "Let an AI app on this computer read my plans and add changes for me to send"
ABOUT = ("An AI app on this computer (Claude Desktop, Claude Code or another) reads your plans and the deck's tags "
         "through Anki, and puts changes under a plan you write.")
SETUP = ("Copy setup is for an app that starts a program for its tools (it needs Python 3 here); Copy HTTP setup "
         "for one that takes an address. Paste either under mcpServers in the app's setup.")
NOTHING_SENT = "Nothing is sent from Anki by it: changes wait under the plan for you to Review and send."

_open = []  # the one window


def _plain(text="", wrap=True):
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(wrap)
    return label


class AiAppDialog(QDialog):
    """ops: state() -> {on, running, port, url, token, said}; set_on(on) and
    new_token() -> state; setup(http) -> the JSON to copy."""

    def __init__(self, parent, ops):
        super().__init__(parent)
        self.ops = ops
        attach_alive(self)
        self.setWindowTitle("Your AI app")
        self.setMinimumWidth(520)
        root = QVBoxLayout(self)
        heading(self, root)
        root.addWidget(_plain(ABOUT))
        self.switch = QCheckBox(SWITCH)
        self.switch.toggled.connect(self._switch)
        root.addWidget(self.switch)

        self.on_box = QWidget()
        box = QVBoxLayout(self.on_box)
        box.setContentsMargins(0, 0, 0, 0)
        grid = QGridLayout()
        self.address = QLineEdit()
        self.address.setReadOnly(True)
        self.token = QLineEdit()
        self.token.setReadOnly(True)
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.copy_token = QPushButton("Copy")
        self.copy_token.clicked.connect(lambda: self._copy(self.ops.state()["token"], "Token copied."))
        self.new_btn = QPushButton("New token")
        self.new_btn.clicked.connect(self._new_token)
        grid.addWidget(_plain("Address", wrap=False), 0, 0)
        grid.addWidget(self.address, 0, 1, 1, 3)
        grid.addWidget(_plain("Token", wrap=False), 1, 0)
        grid.addWidget(self.token, 1, 1)
        grid.addWidget(self.copy_token, 1, 2)
        grid.addWidget(self.new_btn, 1, 3)
        grid.setColumnStretch(1, 1)
        box.addLayout(grid)
        row = QHBoxLayout()
        self.setup_btn = QPushButton("Copy setup")
        self.setup_btn.clicked.connect(lambda: self._copy(self.ops.setup(http=False), "Setup copied."))
        self.http_btn = QPushButton("Copy HTTP setup")
        self.http_btn.clicked.connect(lambda: self._copy(self.ops.setup(http=True), "HTTP setup copied."))
        row.addWidget(self.setup_btn)
        row.addWidget(self.http_btn)
        row.addStretch(1)
        box.addLayout(row)
        box.addWidget(note(_plain(SETUP)))
        root.addWidget(self.on_box)

        root.addWidget(note(_plain(NOTHING_SENT)))
        self.said = _plain("")
        root.addWidget(self.said)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._show(self.ops.state())

    def _show(self, s, said=None):
        self.switch.blockSignals(True)
        self.switch.setChecked(bool(s.get("on")))
        self.switch.blockSignals(False)
        live = bool(s.get("running"))
        self.on_box.setVisible(bool(s.get("on")))
        self.address.setText(s.get("url") or "")
        self.token.setText(s.get("token") or "")
        for b in (self.copy_token, self.setup_btn, self.http_btn):
            b.setEnabled(live)
        self.new_btn.setEnabled(bool(s.get("on")))
        words = said if said is not None else (s.get("said") or "")
        if s.get("on") and not live and not words:
            words = "It isn't running. Turn it off and on again."
        self.said.setText(words)
        self.said.setVisible(bool(words))

    def _switch(self, on):
        self._show(self.ops.set_on(bool(on)))

    def _new_token(self):
        if confirm(self, "New token?", "The AI app's setup stops working until you copy it again.", "New token"):
            self._show(self.ops.new_token(), "New token. Copy the setup again into your AI app.")

    def _copy(self, text, words):
        copy_text(text)
        self._show(self.ops.state(), words)


def show(parent=None, ops=None):
    """The one Your AI app window, raised when it's open already."""
    w = _open[0] if _open else None
    if w is not None and getattr(w, "_alive", False):
        w.raise_()
        w.activateWindow()
        return w
    if ops is None:
        from . import mcp_host
        ops = mcp_host.DialogOps()
    if parent is None:
        from aqt import mw
        parent = mw
    w = AiAppDialog(parent, ops)
    _open[:] = [w]
    w.show()
    return w
