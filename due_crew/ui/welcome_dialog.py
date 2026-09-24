"""The one screen after Join (2.9): the three ways not to be alone on the
board, and what the crew will see, said at the moment sharing starts (the
first upload waits for this screen to close). Shown once. Later closes it;
everything on it stays reachable from the board and Settings."""

import html

from aqt.qt import (
    QCheckBox, QDialog, QDialogButtonBox, QFrame, QGridLayout, QLabel, QLineEdit,
    QPushButton, QVBoxLayout, Qt,
)
from aqt.utils import tooltip

from ..backend.firebase import friend_code_from
from . import accent, attach_alive, copy_text, logo_label, run_bg, shared_words


class WelcomeDialog(QDialog):
    def __init__(self, parent, client, cfg, open_squads):
        super().__init__(parent)
        self.client = client
        self.uid = client.user_id
        self.open_squads = open_squads
        self.code = None
        self.friends = []      # my list as the server has it, once loaded
        self.loaded = False
        self.changed = False   # someone was added: the board refreshes
        self.show_up = False
        self.offered = False   # the Just show up choice was on screen
        attach_alive(self)
        self.setWindowTitle("Due Crew")
        self.setMinimumWidth(460)
        root = QVBoxLayout(self)
        logo = logo_label()
        if logo is not None:
            root.addWidget(logo)

        hello = QLabel(f"You're in, {html.escape(client.display_name or 'friend')}.")
        hello.setStyleSheet("font-size: 16px; font-weight: bold;")
        root.addWidget(hello)
        root.addSpacing(4)

        grid = QGridLayout()
        grid.setColumnStretch(0, 1)
        grid.addWidget(QLabel("Invite a friend"), 0, 0)
        self.code_label = QLabel("······")
        self.code_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.code_label.setStyleSheet(
            "font-family: Menlo, Consolas, monospace; font-size: 15px; font-weight: bold;"
            f"letter-spacing: 2px; padding: 2px 8px; color: {accent()};"
            "background: palette(base); border: 1px solid palette(mid); border-radius: 6px;")
        grid.addWidget(self.code_label, 0, 1)
        self.copy_btn = QPushButton("Copy Invite")
        self.copy_btn.setEnabled(False)
        self.copy_btn.clicked.connect(self._copy)
        grid.addWidget(self.copy_btn, 0, 2)

        grid.addWidget(QLabel("Have a code?"), 1, 0)
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("Paste an invite or a code")
        self.code_input.setMinimumWidth(170)
        self.code_input.returnPressed.connect(self._add)
        grid.addWidget(self.code_input, 1, 1)
        self.add_btn = QPushButton("Add")
        self.add_btn.setEnabled(False)
        self.add_btn.clicked.connect(self._add)
        grid.addWidget(self.add_btn, 1, 2)

        grid.addWidget(QLabel("A class or study group?"), 2, 0)
        squads = QPushButton("Join a Squad…")
        squads.clicked.connect(lambda: self.open_squads())
        grid.addWidget(squads, 2, 1, 1, 2, Qt.AlignmentFlag.AlignRight)
        root.addLayout(grid)
        self.status = QLabel("")
        self.status.setTextFormat(Qt.TextFormat.PlainText)  # friend names land here
        self.status.setStyleSheet("font-size: 12px;")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(line)
        words = shared_words(cfg)
        seen = (f"Your crew and squads will see your {words}." if words
                else "Your crew and squads will see which days you studied.")
        note = QLabel(seen)
        note.setWordWrap(True)
        note.setStyleSheet("font-size: 12px;")
        root.addWidget(note)
        self.show_up_box = QCheckBox("Just show up instead: only which days you studied")
        self.show_up_box.setChecked(bool(cfg.get("show_up")))
        self.offered = bool(words)
        self.show_up_box.setVisible(self.offered)
        root.addWidget(self.show_up_box)

        buttons = QDialogButtonBox()
        later = buttons.addButton("Later", QDialogButtonBox.ButtonRole.RejectRole)
        done = buttons.addButton("Done", QDialogButtonBox.ButtonRole.AcceptRole)
        done.setDefault(True)
        later.setAutoDefault(False)
        buttons.accepted.connect(self._done)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._load()

    def _load(self):
        uid = self.uid
        cl = self.client

        def job():
            own, _status = cl.get_doc(f"users/{uid}")
            code = cl.ensure_friend_code(uid, (own or {}).get("friendCode"))
            friends = [f for f in ((own or {}).get("friends") or []) if isinstance(f, str)]
            return code, friends, own is not None

        def done(result, err):
            if err or not result:
                self.status.setText("Couldn't reach the server. The Friends dialog has all of this.")
                return
            self.code, self.friends, self.loaded = result
            self.code_label.setText(self.code or "?")
            self.copy_btn.setEnabled(bool(self.code))
            self.add_btn.setEnabled(self.loaded)

        run_bg(self, job, done)

    def _copy(self):
        from ..share import friend_invite
        if self.code:
            copy_text(friend_invite(self.code))
            tooltip("Invite copied.")

    def _add(self):
        if not self.loaded or not self.add_btn.isEnabled():
            return
        code = friend_code_from(self.code_input.text())
        if not code:
            self.status.setText("Codes are 6 letters and numbers. Pasting the whole invite works too.")
            return
        if code == self.code:
            self.status.setText("That's your own code.")
            return
        self.add_btn.setEnabled(False)
        cl, uid, mine = self.client, self.uid, list(self.friends)
        my_name = cl.display_name or "A friend"

        def done(result, err):
            self.add_btn.setEnabled(True)
            friend, add_err = result if result else (None, None)
            if not friend:
                self.status.setText(add_err or "Couldn't add. Check your connection.")
                return
            self.friends.append(friend["user_id"])
            self.changed = True
            self.code_input.clear()
            name = friend["name"]
            if friend["mutual"]:
                self.status.setText(f"You and {name} are crew.")
            elif friend.get("knocked"):
                self.status.setText(f"Added {name}. They'll see it on their board.")
            else:
                self.status.setText(f"Added {name}. Send them your code to finish.")

        run_bg(self, lambda: cl.add_friend(uid, code, mine, my_name), done)

    def _done(self):
        self.show_up = self.offered and self.show_up_box.isChecked()
        self.accept()
