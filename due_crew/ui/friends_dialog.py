"""Friends dialog: your code, add by code, the crew list with mutual/pending.

Opens instantly and loads in the background. Add and Remove stay DISABLED
until a load has actually succeeded — writes are built from the loaded list,
and writing from an empty or failed snapshot would overwrite the server-side
friends array. self.changed tells the caller to refresh the board.
"""

import html

from aqt import mw
from aqt.qt import (
    QApplication, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QMessageBox, QPushButton, QTimer, QVBoxLayout, QWidget, Qt,
)
from aqt.utils import tooltip

from . import accent, attach_alive, run_bg


def invite_text(server_name, server_code, friend_code):
    """One paste with everything a friend needs. The server line rides only
    when both halves are known (custom servers store the code at join)."""
    lines = ["Study with me on Due Crew — Anki add-on 2035408484."]
    if server_name and server_code:
        lines.append(f"Crew server: {server_name} · code {server_code}")
    lines.append(f"My friend code: {friend_code}")
    return "\n".join(lines)


class FriendsDialog(QDialog):
    def __init__(self, parent, client, server=None, muted=None, on_mute=None):
        super().__init__(parent)
        self.client = client
        self.uid = client.user_id
        conf = server or {}
        self.server_name = str(conf.get("name") or "")
        self.server_code = str(conf.get("code") or "")
        self.muted = set(muted or [])
        self.on_mute = on_mute or (lambda uid: None)
        self.code = None
        self.friends = []      # [(fid, name, mutual)] — valid only when loaded
        self.knocks = []       # [(sender_uid, name)] from the server board
        self.loaded = False
        self.changed = False
        attach_alive(self)
        self._build()
        QTimer.singleShot(0, self._load)

    def _build(self):
        self.setWindowTitle("Due Crew — Friends")
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
        invite = QPushButton("Copy invite")
        invite.setToolTip("Everything a friend needs, in one paste")
        invite.clicked.connect(self._copy_invite)
        code_row.addWidget(invite)
        code_row.addStretch()
        root.addLayout(code_row)
        hint = QLabel("You're crew once you've both added each other's codes.")
        hint.setStyleSheet("font-size: 11px;")
        root.addWidget(hint)

        root.addSpacing(8)
        root.addWidget(QLabel("<b>Add a friend</b>"))
        add_row = QHBoxLayout()
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("Their 6-character code")
        self.code_input.setMaxLength(6)
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
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        root.addLayout(buttons)

        self._set_writable(False)

    def _set_writable(self, on):
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
            return (code, [(fid, prof.get("displayName", "?"), mutual)
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
            self.knocks = [(u, n) for u, n in knocks
                           if u not in have and u not in self.muted]
            self.loaded = True
            self.code_label.setText(self.code or "?")
            self._set_writable(True)
            self._render_knocks()
            self._render_list()

        run_bg(self, job, done)

    def _render_knocks(self):
        """From the server board: one row per knock, Add back or ignore."""
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
        title = QLabel("<b>Knocks</b>")
        self.knocks_lay.addWidget(title)
        for kuid, kname in self.knocks:
            row = QHBoxLayout()
            # server-sourced name: force plain text
            label = QLabel()
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setText(f"{kname} — wants to be crew")
            row.addWidget(label)
            row.addStretch()
            add = QPushButton("Add back")
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
                self.list.addItem(f"⏳ {name} — waiting for them to add you")

    # ---- actions ----

    def _copy(self):
        if self.code:
            QApplication.clipboard().setText(self.code)
            tooltip("Copied.")

    def _copy_invite(self):
        if self.code:
            QApplication.clipboard().setText(
                invite_text(self.server_name, self.server_code, self.code))
            tooltip("Invite copied.")

    def _add(self):
        if not self.loaded:
            return
        code = self.code_input.text().strip().upper()
        if len(code) != 6:
            tooltip("Codes are 6 characters.")
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
            else:
                tooltip(f"Added {name}. Send them your code to finish.")

        run_bg(self, lambda: self.client.add_friend(self.uid, code, own_ids), done)

    def _remove(self):
        if not self.loaded:
            return
        row = self.list.currentRow()
        if row < 0 or row >= len(self.friends):
            tooltip("Pick someone in the list first.")
            return
        fid, name, _ = self.friends[row]
        # plain text: names are server-sourced and QMessageBox auto-detects
        # rich text, so markup in a name must never render
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Remove?")
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(f"Remove {name}?\n\nThey leave your board and stop seeing "
                    f"your stats. You may still see theirs until they remove "
                    f"you too.")
        box.setStandardButtons(QMessageBox.StandardButton.Yes
                               | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        if box.exec() != QMessageBox.StandardButton.Yes:
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
