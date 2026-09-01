"""Settings dialog. Save hands back ONLY the keys this dialog owns, so it
can never clobber config changed by flows launched from inside it (sign-in,
Shared decks). The Account tab rebuilds by swapping one child widget, which
cleans up nested layouts correctly."""

import html

from aqt import mw
from aqt.qt import (
    QCheckBox, QComboBox, QDate, QDateEdit, QDialog, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QTabWidget,
    QTimer, QVBoxLayout, QWidget, Qt,
)
from aqt.utils import tooltip

from . import attach_alive, danger, run_bg

DEFAULTS = {
    "show_leaderboard": True, "period": "today", "sort": "reviews",
    "show_stale": True, "sync_notifications": True,
    "theme": "auto", "compact": False, "show_last_active": True,
    "highlight_me": True, "share_reviews": True, "share_time": True,
    "share_retention": True, "share_streak": True, "share_heatmap": True,
    "server_board": False, "paused": False, "exam_date": "",
}

SORTS = [("reviews", "Reviews"), ("time", "Study time"),
         ("retention", "Retention"), ("streak", "Streak")]
THEMES = [("auto", "Match Anki"), ("light", "Light"), ("dark", "Dark")]


class SettingsDialog(QDialog):
    def __init__(self, parent, client, config, on_saved, open_auth,
                 open_friends, on_signed_out, open_decks,
                 server_label="", open_server_join=None,
                 open_server_register=None):
        super().__init__(parent)
        self.client = client
        self.config = dict(config)
        self.on_saved = on_saved
        self.open_auth = open_auth
        self.open_friends = open_friends
        self.on_signed_out = on_signed_out
        self.open_decks = open_decks
        self.server_label = server_label
        self.open_server_join = open_server_join
        self.open_server_register = open_server_register
        self._binds = {}
        attach_alive(self)
        self._build()

    def _build(self):
        self.setWindowTitle("Due Crew — Settings")
        self.setMinimumWidth(440)
        root = QVBoxLayout(self)

        tabs = QTabWidget()
        tabs.addTab(self._account_tab(), "Account")
        tabs.addTab(self._board_tab(), "Leaderboard")
        tabs.addTab(self._look_tab(), "Appearance")
        tabs.addTab(self._privacy_tab(), "Privacy")
        root.addWidget(tabs)

        buttons = QHBoxLayout()
        restore = QPushButton("Restore Defaults")
        restore.clicked.connect(self._restore)
        buttons.addWidget(restore)
        buttons.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        save = QPushButton("Save")
        save.setDefault(True)
        save.clicked.connect(self._save)
        buttons.addWidget(save)
        root.addLayout(buttons)

    # ---- account ----

    def _account_tab(self):
        self.account_host = QWidget()
        self.account_host_layout = QVBoxLayout(self.account_host)
        self.account_host_layout.setContentsMargins(0, 0, 0, 0)
        self.account_inner = None
        self._fill_account()
        return self.account_host

    def _fill_account(self):
        if self.account_inner is not None:
            self.account_host_layout.removeWidget(self.account_inner)
            self.account_inner.deleteLater()
        self.account_inner = QWidget()
        lay = QVBoxLayout(self.account_inner)
        self.account_host_layout.addWidget(self.account_inner)

        if not self.client.signed_in:
            lay.addWidget(QLabel("Not signed in."))
            sign_in = QPushButton("Sign in…")
            sign_in.clicked.connect(self._sign_in)
            lay.addWidget(sign_in)
            lay.addStretch()
            self._server_rows(lay)
            return

        self.who_label = QLabel(self._who_text())
        lay.addWidget(self.who_label)

        row = QHBoxLayout()
        rename = QPushButton("Change name…")
        rename.clicked.connect(self._rename)
        row.addWidget(rename)
        friends = QPushButton("Friends…")
        friends.clicked.connect(lambda: self.open_friends())
        row.addWidget(friends)
        decks = QPushButton("Shared decks…")
        decks.clicked.connect(lambda: self.open_decks())
        row.addWidget(decks)
        row.addStretch()
        lay.addLayout(row)

        out = QPushButton("Sign out")
        out.clicked.connect(self._sign_out)
        lay.addWidget(out)
        note = QLabel("Sign out stops syncing on this device. "
                      "Your account and stats stay.")
        note.setStyleSheet("font-size: 11px;")
        note.setWordWrap(True)
        lay.addWidget(note)

        lay.addStretch()
        self._server_rows(lay)
        delete = QPushButton("Delete account…")
        delete.setStyleSheet(f"color: {danger()};")
        delete.clicked.connect(self._delete)
        lay.addWidget(delete)

    def _server_rows(self, lay):
        row = QHBoxLayout()
        label = QLabel(f"Server: <b>{html.escape(self.server_label) or 'default'}</b>")
        label.setStyleSheet("font-size: 12px;")
        row.addWidget(label)
        if self.open_server_join:
            switch = QPushButton("Switch…")
            switch.clicked.connect(lambda: self._server(self.open_server_join))
            row.addWidget(switch)
        if self.open_server_register:
            register = QPushButton("Register your own…")
            register.clicked.connect(
                lambda: self._server(self.open_server_register))
            row.addWidget(register)
        row.addStretch()
        lay.addLayout(row)

    def _server(self, cb):
        # server dialogs replace this dialog's client — close first
        self.accept()
        if cb:
            QTimer.singleShot(0, cb)

    def _who_text(self):
        name = html.escape(self.client.display_name or "?")
        email = html.escape(self.client.email)
        return (f"Signed in as <b>{name}</b><br>"
                f"<span style='font-size: 11px;'>{email}</span>")

    def _sign_in(self):
        self.open_auth()
        self._fill_account()

    def _rename(self):
        current = self.client.display_name
        name, ok = QInputDialog.getText(self, "Display name", "New name:",
                                        QLineEdit.EchoMode.Normal, current)
        name = name.strip()
        if not ok or not name or name == current:
            return
        uid = self.client.user_id

        def done(ok_result, err):
            if err or not ok_result:
                tooltip("Couldn't save the name. Try again.")
                return
            self.client.session["display_name"] = name
            self.client._save_session()
            try:
                self.who_label.setText(self._who_text())
            except RuntimeError:
                pass  # account tab was rebuilt meanwhile
            tooltip("Name changed.")

        run_bg(self, lambda: self.client.patch_doc(
            f"users/{uid}", {"displayName": name}), done)

    def _sign_out(self):
        answer = QMessageBox.question(
            self, "Sign out?", "Sign out on this device?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.client.sign_out()
        self.on_signed_out()
        self._fill_account()

    def _delete(self):
        answer = QMessageBox.question(
            self, "Delete account?",
            "This deletes your stats, your code, and your account for good. "
            "No undo.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._delete_attempt(password=None)

    def _delete_attempt(self, password):
        uid = self.client.user_id
        email = self.client.email

        def job():
            if password:
                self.client.sign_in(email, password)
            own, _ = self.client.get_doc(f"users/{uid}")
            self.client.delete_account(uid, (own or {}).get("friendCode"))
            return True

        run_bg(self, job, self._delete_done)

    def _delete_done(self, result, err):
        if err and err.startswith("CREDENTIAL_TOO_OLD"):
            pw, ok = QInputDialog.getText(
                self, "Confirm", "Enter your password to confirm deletion:",
                QLineEdit.EchoMode.Password)
            if ok and pw:
                self._delete_attempt(password=pw)
            return
        if err or not result:
            tooltip("Couldn't delete. Check your connection and try again.")
            return
        self.on_signed_out()
        self._fill_account()
        tooltip("Account deleted.")

    # ---- other tabs ----

    def _check(self, lay, key, label):
        box = QCheckBox(label)
        box.setChecked(bool(self.config.get(key, DEFAULTS[key])))
        lay.addWidget(box)
        self._binds[key] = box

    def _combo(self, lay, key, label, options):
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        combo = QComboBox()
        current = self.config.get(key, DEFAULTS[key])
        for i, (value, text) in enumerate(options):
            combo.addItem(text, value)
            if value == current:
                combo.setCurrentIndex(i)
        row.addWidget(combo)
        row.addStretch()
        lay.addLayout(row)
        self._binds[key] = combo

    def _board_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self._check(lay, "show_leaderboard", "Show Due Crew on the Decks screen")
        self._combo(lay, "sort", "Sort by", SORTS)
        self._check(lay, "show_stale", "Show yesterday for friends who haven't synced today")
        self._check(lay, "sync_notifications", "Toast when a friend syncs")
        note = QLabel("The board refreshes when Anki syncs, or when you "
                      "click Refresh on it.")
        note.setStyleSheet("font-size: 11px;")
        note.setWordWrap(True)
        lay.addWidget(note)
        lay.addStretch()
        return w

    def _look_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self._combo(lay, "theme", "Colors", THEMES)
        self._check(lay, "compact", "Compact rows")
        self._check(lay, "show_last_active", 'Show "last active" next to names')
        self._check(lay, "highlight_me", "Highlight my row")
        lay.addStretch()
        return w

    def _privacy_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("<b>Share with your crew</b>"))
        self._check(lay, "share_reviews", "Reviews")
        self._check(lay, "share_time", "Study time")
        self._check(lay, "share_retention", "Retention")
        self._check(lay, "share_streak", "Streak")
        self._check(lay, "share_heatmap", "My heatmap (shown on my profile card)")
        lay.addSpacing(8)
        lay.addWidget(QLabel("<b>Server board</b>"))
        self._check(lay, "server_board",
                    "Share on the server board (off = hidden both ways)")
        board_note = QLabel("Your name and today's numbers, visible to "
                            "everyone on this server who's also sharing — "
                            "and theirs to you. Adding someone from the "
                            "board starts a knock; you're crew when they "
                            "add back.")
        board_note.setStyleSheet("font-size: 11px;")
        board_note.setWordWrap(True)
        lay.addWidget(board_note)
        lay.addSpacing(8)
        exam_row = QHBoxLayout()
        self.exam_on = QCheckBox("Share an exam date")
        exam_row.addWidget(self.exam_on)
        self.exam_edit = QDateEdit()
        self.exam_edit.setCalendarPopup(True)
        stored = QDate.fromString(str(self.config.get("exam_date", "")),
                                  Qt.DateFormat.ISODate)
        if stored.isValid():
            self.exam_on.setChecked(True)
            self.exam_edit.setDate(stored)
        else:
            self.exam_edit.setDate(QDate.currentDate().addDays(7))
        self.exam_edit.setEnabled(self.exam_on.isChecked())
        self.exam_on.toggled.connect(self.exam_edit.setEnabled)
        exam_row.addWidget(self.exam_edit)
        exam_row.addStretch()
        lay.addLayout(exam_row)
        exam_note = QLabel("\U0001F4D6 shows by your name for the two weeks "
                           "before the date, then clears itself.")
        exam_note.setStyleSheet("font-size: 11px;")
        exam_note.setWordWrap(True)
        lay.addWidget(exam_note)
        lay.addSpacing(8)
        self._check(lay, "paused", 'Pause sharing (your crew sees "on a break")')
        note = QLabel("Applies when you save. Pausing hides your stats; your "
                      "streak keeps counting as long as you keep studying. "
                      "Turning a stat off removes what was already shared "
                      "this week.")
        note.setStyleSheet("font-size: 11px;")
        note.setWordWrap(True)
        lay.addWidget(note)
        lay.addStretch()
        return w

    # ---- footer ----

    def _restore(self):
        self.exam_on.setChecked(False)
        for key, widget in self._binds.items():
            if isinstance(widget, QCheckBox):
                widget.setChecked(bool(DEFAULTS[key]))
            elif isinstance(widget, QComboBox):
                for i in range(widget.count()):
                    if widget.itemData(i) == DEFAULTS[key]:
                        widget.setCurrentIndex(i)
                        break

    def _save(self):
        changed = {}
        for key, widget in self._binds.items():
            if isinstance(widget, QCheckBox):
                changed[key] = widget.isChecked()
            elif isinstance(widget, QComboBox):
                changed[key] = widget.currentData()
        changed["exam_date"] = (
            self.exam_edit.date().toString(Qt.DateFormat.ISODate)
            if self.exam_on.isChecked() else "")
        self.on_saved(changed)
        self.accept()
