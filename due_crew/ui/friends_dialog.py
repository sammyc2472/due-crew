"""Friends dialog: your code, add by code, the crew list with mutual/pending.

Opens instantly and loads in the background. Add and Remove stay DISABLED
until a load has actually succeeded — writes are built from the loaded list,
and writing from an empty or failed snapshot would overwrite the server-side
friends array. self.changed tells the caller to refresh the board.
"""

import html

from aqt.qt import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QPushButton, QTimer, QVBoxLayout, QWidget, Qt,
)
from aqt.utils import tooltip

from ..backend.firebase import friend_code_from
from . import accent, attach_alive, confirm, copy_text, run_bg


def _with_emoji(prof):
    from ..backend.firebase import clean_emoji
    name = str(prof.get("displayName", "?"))
    emoji = clean_emoji(prof.get("emoji"))
    return f"{emoji} {name}" if emoji else name


def invite_text(friend_code):
    from ..share import friend_invite   # one wording, also used by the board
    return friend_invite(friend_code)


class FriendsDialog(QDialog):
    def __init__(self, parent, client, muted=None, on_mute=None, focus_add=False):
        super().__init__(parent)
        self.focus_add = focus_add  # the board's "Add a code" opens straight to it
        self.client = client
        self.uid = client.user_id
        self.muted = set(muted or [])
        self.on_mute = on_mute or (lambda uid: None)
        self.code = None
        self.friends = []      # [(fid, name, mutual)] — valid only when loaded
        self.knocks = []       # [(sender_uid, name)] from squads
        self.loaded = False
        self.changed = False
        self.new_code = None   # set when the code was swapped: the board shows it
        attach_alive(self)
        self._build()
        QTimer.singleShot(0, self._load)

    def _build(self):
        self.setWindowTitle("Friends")
        self.setMinimumWidth(420)
        root = QVBoxLayout(self)

        root.addWidget(QLabel("<b>Your code</b>"))
        code_row = QHBoxLayout()
        self.code_label = QLabel("······")
        self.code_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.code_label.setStyleSheet(
            "font-family: Menlo, monospace; font-size: 20px; font-weight: bold;"
            "letter-spacing: 3px; padding: 6px 12px;"
            # the one styled well in the Qt surfaces: palette roles track
            # night mode on their own, the accent comes from the theme
            f"color: {accent()}; background: palette(alternate-base);"
            "border: 1px solid palette(mid); border-radius: 6px;")
        code_row.addWidget(self.code_label)
        copy = QPushButton("Copy")
        copy.clicked.connect(self._copy)
        code_row.addWidget(copy)
        invite = QPushButton("Copy Invite")
        invite.setToolTip("Everything a friend needs, in one paste")
        invite.clicked.connect(self._copy_invite)
        code_row.addWidget(invite)
        # 2.10: a code also knocks now, so one posted too widely needs a way out
        self.new_btn = QPushButton("New Code")
        self.new_btn.setToolTip("Retire this code and get a fresh one. Your crew stays.")
        self.new_btn.clicked.connect(self._new_code)
        code_row.addWidget(self.new_btn)
        code_row.addStretch()
        root.addLayout(code_row)
        hint = QLabel("You're crew once you've both added each other's codes.")
        hint.setStyleSheet("font-size: 11px;")
        root.addWidget(hint)

        root.addSpacing(8)
        root.addWidget(QLabel("<b>Add a friend</b>"))
        add_row = QHBoxLayout()
        self.code_input = QLineEdit()
        # 2.9: the whole invite pastes in; the code is taken from it
        self.code_input.setPlaceholderText("Their code, or paste their invite")
        self.code_input.returnPressed.connect(self._add)
        add_row.addWidget(self.code_input)
        self.add_btn = QPushButton("Add")
        self.add_btn.clicked.connect(self._add)
        add_row.addWidget(self.add_btn)
        root.addLayout(add_row)

        self.knocks_host = QWidget()
        self.knocks_lay = QVBoxLayout(self.knocks_host)
        self.knocks_lay.setContentsMargins(0, 8, 0, 0)
        root.addWidget(self.knocks_host)
        self.knocks_host.hide()

        root.addSpacing(8)
        root.addWidget(QLabel("<b>Your crew</b>"))
        self.list = QListWidget()
        root.addWidget(self.list)

        buttons = QHBoxLayout()
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.clicked.connect(self._remove)
        buttons.addWidget(self.remove_btn)
        self.retry_btn = QPushButton("Retry")
        self.retry_btn.clicked.connect(self._load)
        self.retry_btn.hide()
        buttons.addWidget(self.retry_btn)
        buttons.addStretch()
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.accept)
        buttons.addWidget(close)
        root.addLayout(buttons)

        self._set_writable(False)

    def _set_writable(self, on):
        self.new_btn.setEnabled(on)
        self.add_btn.setEnabled(on)
        self.code_input.setEnabled(on)
        self.remove_btn.setEnabled(on)

    # ---- load ----

    def _load(self):
        self.loaded = False
        self._set_writable(False)
        self.retry_btn.hide()
        self.list.clear()
        self.list.addItem("Loading…")

        def job():
            own, resolved, _pending = self.client.list_friends(self.uid)
            code = self.client.ensure_friend_code(self.uid, own.get("friendCode"))
            try:
                knocks = self.client.list_knocks(self.uid)
            except Exception:
                knocks = []  # knocks are a bonus; never fail the dialog
            return (code, [(fid, _with_emoji(prof), mutual)
                           for fid, prof, mutual in resolved], knocks)

        def done(result, err):
            if err or result is None:
                self.list.clear()
                self.list.addItem("Couldn't load your crew. "
                                  "Check your connection and retry.")
                self.retry_btn.show()
                return
            self.code, self.friends, knocks = result
            have = {fid for fid, _n, _m in self.friends}
            self.knocks = [(k[0], k[1]) for k in knocks
                           if k[0] not in have and k[0] not in self.muted]
            self.loaded = True
            self.code_label.setText(self.code or "?")
            self._set_writable(True)
            self._render_knocks()
            self._render_list()
            if self.focus_add:
                self.code_input.setFocus()

        run_bg(self, job, done)

    def _render_knocks(self):
        """From squads: one row per knock, Add back or ignore."""
        while self.knocks_lay.count():
            item = self.knocks_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                lay = item.layout()
                while lay.count():
                    sub = lay.takeAt(0)
                    if sub.widget():
                        sub.widget().deleteLater()
        if not self.knocks:
            self.knocks_host.hide()
            return
        title = QLabel("<b>Added you</b>")
        self.knocks_lay.addWidget(title)
        for kuid, kname in self.knocks:
            row = QHBoxLayout()
            # server-sourced name: force plain text
            label = QLabel()
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setText(f"{kname} added you")
            row.addWidget(label)
            row.addStretch()
            add = QPushButton("Add Back")
            add.clicked.connect(
                lambda _=False, u=kuid, n=kname: self._add_back(u, n))
            row.addWidget(add)
            ignore = QPushButton("Ignore")
            ignore.setFlat(True)
            ignore.clicked.connect(
                lambda _=False, u=kuid: self._ignore_knock(u))
            row.addWidget(ignore)
            self.knocks_lay.addLayout(row)
        self.knocks_host.show()

    def _add_back(self, kuid, kname):
        if not self.loaded:
            return
        self._set_writable(False)
        remaining = [f for f, _, _ in self.friends] + [kuid]

        def done(ok, err):
            self._set_writable(True)
            if err or not ok:
                tooltip("Couldn't save. Try again.")
                return
            # they knocked, so I'm already in their list: instantly mutual
            self.friends.append((kuid, kname, True))
            self.knocks = [(u, n) for u, n in self.knocks if u != kuid]
            self.changed = True
            self._render_knocks()
            self._render_list()
            tooltip(f"You and {html.escape(kname)} are crew.")

        def job():
            ok = self.client.set_friends(self.uid, remaining)
            if ok:
                self.client.delete_knock(self.uid, kuid)
            return ok

        run_bg(self, job, done)

    def _ignore_knock(self, kuid):
        self.knocks = [(u, n) for u, n in self.knocks if u != kuid]
        self.muted.add(kuid)
        self.on_mute(kuid)   # local mute: their re-knocks stay hidden
        self._render_knocks()
        run_bg(self, lambda: self.client.delete_knock(self.uid, kuid),
               lambda _ok, _err: None)

    def _render_list(self):
        self.list.clear()
        if not self.friends:
            self.list.addItem("No one yet. Swap codes with a friend.")
            return
        for _, name, mutual in self.friends:
            if mutual:
                self.list.addItem(f"✓ {name}")
            else:
                self.list.addItem(f"⏳ {name} — waiting")

    # ---- actions ----

    def _copy(self):
        if self.code:
            copy_text(self.code)
            tooltip("Copied.")

    def _copy_invite(self):
        if self.code:
            copy_text(invite_text(self.code))
            tooltip("Invite copied.")

    def _new_code(self):
        if not self.loaded or not self.code:
            return
        if not confirm(self, "New Code",
                       "Get a new code? This one stops working, and so does any invite "
                       "with it in. Your crew stays as it is.", "New Code"):
            return
        old = self.code
        self.new_btn.setEnabled(False)

        def done(result, err):
            self.new_btn.setEnabled(self.loaded)
            if err or result is None:
                tooltip("Couldn't reach the server. Your code is unchanged.")
                return
            code, problem = result
            if code:
                self.code = self.new_code = code
                self.code_label.setText(code)
            tooltip(problem or "New code. The old one no longer works.")

        run_bg(self, lambda: self.client.new_friend_code(self.uid, old), done)

    def _add(self):
        if not self.loaded:
            return
        code = friend_code_from(self.code_input.text())
        if not code:
            tooltip("Codes are 6 letters and numbers. Pasting the whole invite works too.")
            return
        if self.code and code == self.code:
            tooltip("That's your own code.")
            return
        self._set_writable(False)
        self.add_btn.setText("Adding…")
        own_ids = [fid for fid, _, _ in self.friends]

        def done(result, err):
            self.add_btn.setText("Add")
            self._set_writable(True)
            friend, add_err = result if result else (None, None)
            if not friend:
                tooltip(html.escape(add_err or "Couldn't add. Check your connection."))
                return
            self.friends.append((friend["user_id"], friend["name"], friend["mutual"]))
            self.changed = True
            self.code_input.clear()
            self._render_list()
            name = html.escape(friend["name"])
            if friend["mutual"]:
                tooltip(f"You and {name} are crew.")
            elif friend.get("knocked"):
                # 2.9: the add knocked; their board offers Add back
                tooltip(f"Added {name}. They'll see it on their board.")
            else:
                tooltip(f"Added {name}. Send them your code to finish.")

        my_name = self.client.display_name or "A friend"
        run_bg(self, lambda: self.client.add_friend(self.uid, code, own_ids, my_name), done)

    def _remove(self):
        if not self.loaded:
            return
        row = self.list.currentRow()
        if row < 0 or row >= len(self.friends):
            tooltip("Pick someone in the list first.")
            return
        fid, name, _ = self.friends[row]
        # plain text (confirm): names are server-sourced
        if not confirm(self, "Remove?", f"Remove {name}?\n\nThey leave your board and "
                       "stop seeing your stats.", "Remove"):
            return
        self._set_writable(False)
        remaining = [f for f, _, _ in self.friends if f != fid]

        def done(ok, err):
            self._set_writable(True)
            if err or not ok:
                tooltip("Couldn't save. Try again.")
                return
            self.friends = [t for t in self.friends if t[0] != fid]
            self.changed = True
            self._render_list()

        run_bg(self, lambda: self.client.set_friends(self.uid, remaining), done)
