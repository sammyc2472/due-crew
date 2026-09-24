"""Settings dialog. Save hands back ONLY the keys this dialog owns, so it
can never clobber config changed by flows launched from inside it (sign-in,
Shared decks, the emoji and status editors). The You tab rebuilds by
swapping one child widget, which cleans up nested layouts correctly.

2.9: three tabs, You, Board, Privacy (Board and Appearance were two, and
your emoji and status lived only on your card). Privacy is one choice of
three instead of three switches that overruled each other unannounced. The
reset button resets the Board tab only: Restore Defaults used to turn every
sharing switch back on."""

import html

from aqt.qt import (
    QButtonGroup, QCheckBox, QColor, QComboBox, QDate, QDateEdit, QDialog,
    QDialogButtonBox, QFrame, QHBoxLayout, QIcon, QInputDialog, QLabel, QLineEdit,
    QPixmap, QPushButton, QRadioButton, QSizePolicy, QTabWidget, QTimer, QVBoxLayout,
    QWidget, Qt,
)
from aqt.utils import tooltip

from . import _night, attach_alive, confirm, danger, run_bg

DEFAULTS = {
    "show_leaderboard": True, "period": "today", "sort": "reviews",
    "show_stale": True, "sync_notifications": True,
    "theme": "auto", "compact": False, "show_last_active": True,
    "highlight_me": True, "share_reviews": True, "share_time": True,
    "share_retention": True, "share_streak": True, "share_heatmap": True,
    "show_up": False,
    "paused": False, "exam_date": "",
    "crew_label": "Crew", "accent": "green",
    "away_from": "", "away_to": "",
}
# what Reset Board puts back: the Board tab, and never anything on Privacy
BOARD_KEYS = ("show_leaderboard", "show_stale", "show_last_active", "sync_notifications",
              "theme", "accent", "compact", "highlight_me", "crew_label")
TABS = ("you", "board", "privacy")

THEMES = [("auto", "Match Anki"), ("light", "Light"), ("dark", "Dark")]
ACCENTS = [("green", "Green"), ("blue", "Blue"), ("purple", "Purple"),
           ("teal", "Teal"), ("amber", "Amber"), ("rose", "Rose")]
NUMBERS, SHOW_UP, PAUSED = 0, 1, 2   # the three Privacy choices


class SettingsDialog(QDialog):
    def __init__(self, parent, client, config, on_saved, open_auth,
                 open_friends, on_signed_out, open_decks, open_squads=None,
                 edit_emoji=None, edit_status=None, tab=None):
        """edit_emoji / edit_status: the card's editors (they save on their
        own and return the new value, or None). tab: "you", "board", or
        "privacy", the tab to open on (your card's Privacy… opens Privacy)."""
        super().__init__(parent)
        self.client = client
        self.config = dict(config)
        self.on_saved = on_saved
        self.open_auth = open_auth
        self.open_friends = open_friends
        self.on_signed_out = on_signed_out
        self.open_decks = open_decks
        self.open_squads = open_squads
        self.edit_emoji = edit_emoji
        self.edit_status = edit_status
        self._binds = {}
        self._kept = {}  # combo key -> a stored value its list doesn't offer
        attach_alive(self)
        self._build()
        if tab in TABS:
            self.tabs.setCurrentIndex(TABS.index(tab))

    def _build(self):
        self.setWindowTitle("Due Crew Settings")
        self.setMinimumWidth(460)
        root = QVBoxLayout(self)

        tabs = QTabWidget()
        tabs.addTab(self._you_tab(), "You")
        tabs.addTab(self._board_tab(), "Board")
        tabs.addTab(self._privacy_tab(), "Privacy")
        root.addWidget(tabs)
        self.tabs = tabs
        # size to the tab on screen, not to the tallest one
        tabs.currentChanged.connect(self._fit_tab)
        self._fit_tab(tabs.currentIndex())

        if self.client.signed_in:
            # 2.13: what's in the account follows it; the look is per computer
            follow = QLabel("Privacy, dates, status, squads and shared decks are saved to "
                            "your account, so they follow you to other computers. "
                            "Colours and layout stay on this one.")
            follow.setWordWrap(True)
            follow.setStyleSheet("font-size: 11px;")
            root.addWidget(follow)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel
                                   | QDialogButtonBox.StandardButton.Save)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _fit_tab(self, index):
        for i in range(self.tabs.count()):
            page = self.tabs.widget(i)
            page.setSizePolicy(
                QSizePolicy.Policy.Preferred,
                QSizePolicy.Policy.Preferred if i == index
                else QSizePolicy.Policy.Ignored)
        QTimer.singleShot(0, self._shrink)

    def _shrink(self):
        # QTabWidget's sizeHint still spans every page; its minimum hint
        # follows the Ignored policies above, so size to that
        self.layout().activate()
        # +12: wrapped notes report a hint a hair short of their last line
        self.resize(self.width(), self.minimumSizeHint().height() + 12)

    @staticmethod
    def _note(lay, text, indent=0):
        note = QLabel(text)
        note.setStyleSheet(f"font-size: 11px; margin-left: {indent}px;")
        note.setWordWrap(True)
        lay.addWidget(note)
        return note

    @staticmethod
    def _rule(lay):
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        lay.addWidget(line)

    # ---- you ----

    def _you_tab(self):
        self.you_host = QWidget()
        self.you_host_layout = QVBoxLayout(self.you_host)
        self.you_host_layout.setContentsMargins(0, 0, 0, 0)
        self.you_inner = None
        self._fill_you()
        return self.you_host

    def _fill_you(self):
        if self.you_inner is not None:
            self.you_host_layout.removeWidget(self.you_inner)
            self.you_inner.deleteLater()
        self.you_inner = QWidget()
        lay = QVBoxLayout(self.you_inner)
        self.you_host_layout.addWidget(self.you_inner)

        if not self.client.signed_in:
            lay.addWidget(QLabel("Not signed in."))
            sign_in = QPushButton("Sign In…")
            sign_in.clicked.connect(self._sign_in)
            lay.addWidget(sign_in, alignment=Qt.AlignmentFlag.AlignLeft)
            lay.addStretch()
            return

        who = QHBoxLayout()
        self.who_label = QLabel(self._who_text())
        who.addWidget(self.who_label)
        who.addStretch()
        if self.edit_emoji is not None:
            emoji = QPushButton("Emoji…")
            emoji.setToolTip("In front of your name, for your crew and squads")
            emoji.clicked.connect(self._emoji)
            who.addWidget(emoji)
        rename = QPushButton("Name…")
        rename.clicked.connect(self._rename)
        who.addWidget(rename)
        lay.addLayout(who)

        if self.edit_status is not None:
            srow = QHBoxLayout()
            self.status_label = QLabel()
            self.status_label.setTextFormat(Qt.TextFormat.PlainText)
            self.status_label.setWordWrap(True)
            self._show_status()
            srow.addWidget(self.status_label, 1)
            status = QPushButton("Status…")
            status.setToolTip("One line under your name on Today, for your crew")
            status.clicked.connect(self._status)
            srow.addWidget(status)
            lay.addLayout(srow)
        self.sync_label = QLabel(self._sync_line())
        self.sync_label.setStyleSheet("font-size: 11px;")
        lay.addWidget(self.sync_label)

        lay.addSpacing(6)
        self._rule(lay)
        lay.addWidget(QLabel("<b>Your crew</b>"))
        row = QHBoxLayout()
        for label, opener in (("Friends…", self.open_friends),
                              ("Squads…", self.open_squads),
                              ("Shared Decks…", self.open_decks)):
            if opener is None:
                continue
            btn = QPushButton(label)
            btn.clicked.connect(lambda _=False, f=opener: f())
            row.addWidget(btn)
        row.addStretch()
        lay.addLayout(row)

        lay.addSpacing(6)
        self._rule(lay)
        bottom = QHBoxLayout()
        out = QPushButton("Sign Out")
        out.setToolTip("Stops syncing on this device. Your account and stats stay.")
        out.clicked.connect(self._sign_out)
        bottom.addWidget(out)
        bottom.addStretch()
        delete = QPushButton("Delete Account…")
        delete.setStyleSheet(f"color: {danger()};")
        delete.clicked.connect(self._delete)
        bottom.addWidget(delete)
        lay.addLayout(bottom)

    def _who_text(self):
        name = html.escape(self.client.display_name or "?")
        emoji = html.escape(str(self.config.get("emoji") or ""))
        return f"<b style='font-size: 14px;'>{emoji + ' ' if emoji else ''}{name}</b>"

    def _show_status(self):
        status = str(self.config.get("status") or "")
        self.status_label.setText(f"“{status}”" if status else "No status")

    def _sync_line(self):
        email = self.client.email
        return f"{email} · {self._sync_text()}" if email else self._sync_text()

    def _sync_text(self):
        """"Is it syncing for me?" answered where people look for it. The
        time is the last upload the server ACCEPTED, not the last attempt."""
        from ..app import ADDON_VERSION
        from ..board import _ago
        if self.client.session_dead:
            state = "Sign-in expired"
        else:
            ago, _tone = _ago(self.client.session.get("last_ok", ""))
            state = f"Synced {ago}" if ago else "Not synced yet"
        return f"{state} · v{ADDON_VERSION}" if ADDON_VERSION else state

    def _emoji(self):
        new = self.edit_emoji(self)
        if new is not None:
            self.config["emoji"] = new  # shown here; the editor saved it
            self.who_label.setText(self._who_text())

    def _status(self):
        new = self.edit_status(self)
        if new is not None:
            self.config["status"] = new
            self._show_status()

    def _sign_in(self):
        self.open_auth()
        self._fill_you()

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
                pass  # the You tab was rebuilt meanwhile
            tooltip("Name changed.")

        run_bg(self, lambda: self.client.patch_doc(
            f"users/{uid}", {"displayName": name}), done)

    def _sign_out(self):
        if not confirm(self, "Sign out?", "Sign out on this device? Your account and "
                       "stats stay.", "Sign Out"):
            return
        self.client.sign_out()
        self.on_signed_out()
        self._fill_you()

    def _delete(self):
        if not confirm(self, "Delete account?", "This deletes your stats, your code, and "
                       "your account for good. No undo.", "Delete Account"):
            return
        self._delete_attempt(password=None)

    def _delete_attempt(self, password):
        uid = self.client.user_id
        email = self.client.email

        def job():
            if password:
                self.client.sign_in(email, password)
            own, _ = self.client.get_doc(f"users/{uid}")
            self.client.delete_account(
                uid, (own or {}).get("friendCode"),
                [sq.get("id") for sq in (self.config.get("squads") or [])
                 if isinstance(sq, dict) and sq.get("id")])
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
        self._fill_you()
        tooltip("Account deleted.")

    # ---- board ----

    def _check(self, lay, key, label, indent=0):
        box = QCheckBox(label)
        box.setChecked(bool(self.config.get(key, DEFAULTS[key])))
        if indent:
            box.setStyleSheet(f"margin-left: {indent}px;")
        lay.addWidget(box)
        self._binds[key] = box
        return box

    def _text(self, lay, key, label, placeholder=""):
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        edit.setMaxLength(24)
        edit.setText(str(self.config.get(key, DEFAULTS[key]) or ""))
        row.addWidget(edit)
        row.addStretch()
        lay.addLayout(row)
        self._binds[key] = edit

    def _combo(self, lay, key, label, options, icons=None):
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        combo = QComboBox()
        current = self.config.get(key, DEFAULTS[key])
        for i, (value, text) in enumerate(options):
            if icons and value in icons:
                combo.addItem(icons[value], text, value)
            else:
                combo.addItem(text, value)
            if value == current:
                combo.setCurrentIndex(i)
        if current not in [value for value, _text in options]:
            # a stored value the list doesn't offer: Save keeps it unless
            # the list is touched
            self._kept[key] = (current, combo.currentIndex())
        row.addWidget(combo)
        row.addStretch()
        lay.addLayout(row)
        self._binds[key] = combo

    @staticmethod
    def _swatches():
        """A dot of each accent, in the shade for Anki's current theme."""
        from ..board import ACCENTS as TRIOS
        shade = "dark" if _night() else "light"
        icons = {}
        for name, trio in TRIOS.items():
            pix = QPixmap(12, 12)
            pix.fill(QColor(trio[shade][0]))
            icons[name] = QIcon(pix)
        return icons

    def _board_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("<b>What it shows</b>"))
        self._check(lay, "show_leaderboard", "Show Due Crew on the Decks screen")
        self._check(lay, "show_stale", "Show yesterday for friends who haven't synced today")
        self._check(lay, "show_last_active", 'Show "last active" next to names')
        self._check(lay, "sync_notifications", "Tell me when my crew studies")
        lay.addSpacing(6)
        lay.addWidget(QLabel("<b>How it looks</b>"))
        self._combo(lay, "theme", "Theme", THEMES)
        try:
            icons = self._swatches()
        except Exception:
            icons = None
        self._combo(lay, "accent", "Accent", ACCENTS, icons)
        self._check(lay, "compact", "Compact rows")
        self._check(lay, "highlight_me", "Highlight my row")
        lay.addSpacing(6)
        self._text(lay, "crew_label", "Crew name in shares", "Crew")
        # two short lines, unwrapped: a wrapped note got clipped by _shrink
        hint = QLabel("Refreshes when Anki opens or syncs, and with Refresh.<br>"
                      "Sort by clicking the board's headers.")
        hint.setStyleSheet("font-size: 11px;")
        lay.addWidget(hint)
        reset_row = QHBoxLayout()
        reset_row.addStretch()
        reset = QPushButton("Reset Board")
        reset.setToolTip("Puts this tab back as it was. Privacy stays as you set it.")
        reset.clicked.connect(self._reset_board)
        reset_row.addWidget(reset)
        lay.addLayout(reset_row)
        lay.addStretch()
        return w

    def _reset_board(self):
        """This tab only. Until 2.9 Restore Defaults reset Privacy too, and
        since the defaults share the most, a reset only ever widened what
        went out."""
        for key in BOARD_KEYS:
            widget = self._binds.get(key)
            if isinstance(widget, QCheckBox):
                widget.setChecked(bool(DEFAULTS[key]))
            elif isinstance(widget, QComboBox):
                self._kept.pop(key, None)
                for i in range(widget.count()):
                    if widget.itemData(i) == DEFAULTS[key]:
                        widget.setCurrentIndex(i)
                        break
            elif isinstance(widget, QLineEdit):
                widget.setText(str(DEFAULTS[key]))

    # ---- privacy ----

    def _privacy_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("<b>What your crew and squads see</b>"))
        self.choice = QButtonGroup(w)
        numbers = QRadioButton("My numbers")
        self.choice.addButton(numbers, NUMBERS)
        lay.addWidget(numbers)
        self.number_boxes = []
        grid = QHBoxLayout()
        grid.setContentsMargins(22, 0, 0, 0)
        for key, label in (("share_reviews", "Reviews"), ("share_time", "Study time"),
                           ("share_retention", "Retention"), ("share_streak", "Streak")):
            box = QCheckBox(label)
            box.setChecked(bool(self.config.get(key, DEFAULTS[key])))
            self._binds[key] = box
            self.number_boxes.append(box)
            grid.addWidget(box)
        grid.addStretch()
        lay.addLayout(grid)
        heat = self._check(lay, "share_heatmap", "My heatmap · crew only, on my card", indent=22)
        self.number_boxes.append(heat)

        show_up = QRadioButton("Just that I studied")
        self.choice.addButton(show_up, SHOW_UP)
        lay.addWidget(show_up)
        self._note(lay, "Squares for the days you studied, no numbers. You see "
                        "everyone else the same way.", indent=22)
        paused = QRadioButton("Nothing for now")
        self.choice.addButton(paused, PAUSED)
        lay.addWidget(paused)
        self._note(lay, 'Your crew sees "on a break". Your streak keeps counting.', indent=22)
        # paused wins over show-up: it shares less
        start = (PAUSED if self.config.get("paused") else
                 SHOW_UP if self.config.get("show_up") else NUMBERS)
        self.choice.button(start).setChecked(True)
        self.choice.idToggled.connect(lambda _id, _on: self._numbers_enabled())
        self._numbers_enabled()

        lay.addSpacing(6)
        self._rule(lay)
        lay.addWidget(QLabel("<b>Dates your crew sees</b>"))
        exam_row = QHBoxLayout()
        self.exam_on = QCheckBox("Exam")
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
        exam_row.addWidget(QLabel("\U0001F4D6 for the two weeks before"))
        exam_row.addStretch()
        lay.addLayout(exam_row)
        away_row = QHBoxLayout()
        self.away_on = QCheckBox("Away")
        away_row.addWidget(self.away_on)
        self.away_from = QDateEdit()
        self.away_to = QDateEdit()
        start_d = QDate.fromString(str(self.config.get("away_from", "")),
                                   Qt.DateFormat.ISODate)
        end_d = QDate.fromString(str(self.config.get("away_to", "")),
                                 Qt.DateFormat.ISODate)
        if start_d.isValid() and end_d.isValid():
            self.away_on.setChecked(True)
            self.away_from.setDate(start_d)
            self.away_to.setDate(end_d)
        else:
            self.away_from.setDate(QDate.currentDate().addDays(1))
            self.away_to.setDate(QDate.currentDate().addDays(7))
        for edit in (self.away_from, self.away_to):  # not `w`: that's the tab
            edit.setCalendarPopup(True)
            edit.setEnabled(self.away_on.isChecked())
            self.away_on.toggled.connect(edit.setEnabled)
        away_row.addWidget(self.away_from)
        away_row.addWidget(QLabel("to"))
        away_row.addWidget(self.away_to)
        away_row.addWidget(QLabel("✈️ on those days"))
        away_row.addStretch()
        lay.addLayout(away_row)
        self._note(lay, "Turning a number off also removes what's already shared this week.")
        lay.addStretch()
        return w

    def _numbers_enabled(self):
        on = self.choice.checkedId() == NUMBERS
        for box in self.number_boxes:
            box.setEnabled(on)

    # ---- footer ----

    def _save(self):
        changed = {}
        for key, widget in self._binds.items():
            if isinstance(widget, QCheckBox):
                changed[key] = widget.isChecked()
            elif isinstance(widget, QComboBox):
                kept = self._kept.get(key)
                untouched = kept is not None and widget.currentIndex() == kept[1]
                changed[key] = kept[0] if untouched else widget.currentData()
            elif isinstance(widget, QLineEdit):
                changed[key] = widget.text().strip()[:24]
        choice = self.choice.checkedId()
        # the numbers keep their settings under the other two choices, for
        # when "My numbers" comes back
        changed["show_up"] = choice == SHOW_UP
        changed["paused"] = choice == PAUSED
        changed["exam_date"] = (
            self.exam_edit.date().toString(Qt.DateFormat.ISODate)
            if self.exam_on.isChecked() else "")
        if self.away_on.isChecked():
            start, end = self.away_from.date(), self.away_to.date()
            if end < start:
                start, end = end, start
            changed["away_from"] = start.toString(Qt.DateFormat.ISODate)
            changed["away_to"] = end.toString(Qt.DateFormat.ISODate)
        else:
            changed["away_from"] = changed["away_to"] = ""
        self.on_saved(changed)
        self.accept()
