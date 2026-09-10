"""Squads: join with a code, or create one. Network runs in threads and
lands on the main thread; the dialog never blocks Anki."""

import threading

from aqt import mw
from aqt.qt import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
)

from ..backend.firebase import SQUAD_CODE_LEN, SQUAD_NAME_MAX, normalize_code
from . import copy_text

FOOTER = "— Due Crew · Anki add-on 2035408484"


def invite_text(name, code):
    return f"Join {name} on Due Crew · code {code}\n{FOOTER}"


class SquadDialog(QDialog):
    def __init__(self, parent, client, on_joined):
        super().__init__(parent)
        self.client = client
        self.on_joined = on_joined   # main thread: {id, code, name, founder}
        self.peek = None
        self.setWindowTitle("Squads")
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)

        lay.addWidget(QLabel("<b>Join</b>"))
        row = QHBoxLayout()
        self.code_edit = QLineEdit()
        self.code_edit.setPlaceholderText("Invite code")
        self.code_edit.setMaxLength(12)
        self.code_edit.textChanged.connect(self._code_changed)
        self.code_edit.returnPressed.connect(self._look_up)
        self.look_btn = QPushButton("Look up")
        self.look_btn.clicked.connect(self._look_up)
        row.addWidget(self.code_edit)
        row.addWidget(self.look_btn)
        lay.addLayout(row)
        self.peek_label = QLabel("")
        self.peek_label.setWordWrap(True)
        lay.addWidget(self.peek_label)
        jrow = QHBoxLayout()
        jrow.addStretch()
        self.join_btn = QPushButton("Join")
        self.join_btn.setEnabled(False)
        self.join_btn.clicked.connect(self._join)
        jrow.addWidget(self.join_btn)
        lay.addLayout(jrow)

        lay.addSpacing(10)
        lay.addWidget(QLabel("<b>Create</b>"))
        row2 = QHBoxLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Squad name")
        self.name_edit.setMaxLength(SQUAD_NAME_MAX)
        self.name_edit.returnPressed.connect(self._create)
        self.create_btn = QPushButton("Create")
        self.create_btn.clicked.connect(self._create)
        row2.addWidget(self.name_edit)
        row2.addWidget(self.create_btn)
        lay.addLayout(row2)
        self.made_label = QLabel("")
        self.made_label.setWordWrap(True)
        self.made_label.setTextInteractionFlags(
            self.made_label.textInteractionFlags() | 0x1)  # selectable
        lay.addWidget(self.made_label)

        note = QLabel("Squadmates see your name and today's reviews, time, "
                      "retention, and streak. Leave anytime.")
        note.setStyleSheet("font-size: 11px;")
        note.setWordWrap(True)
        lay.addWidget(note)
        crow = QHBoxLayout()
        crow.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        crow.addWidget(close)
        lay.addLayout(crow)

    # ---- join ----
    def _code_changed(self, _text=""):
        self.peek = None
        self.join_btn.setEnabled(False)
        self.peek_label.setText("")

    def _look_up(self):
        code = normalize_code(self.code_edit.text())
        if len(code) != SQUAD_CODE_LEN:
            self.peek_label.setText(f"Codes are {SQUAD_CODE_LEN} letters and numbers.")
            return
        self.look_btn.setEnabled(False)
        self.peek_label.setText("Looking up…")
        cl = self.client

        def job():
            try:
                info, status = cl.peek_squad(code)
                founder = ""
                if info and info.get("founder"):
                    prof, _s = cl.get_doc(f"users/{info['founder']}")
                    founder = str((prof or {}).get("displayName") or "")
            except Exception:
                info, status, founder = None, 0, ""
            mw.taskman.run_on_main(lambda: self._peeked(info, status, founder))

        threading.Thread(target=job, daemon=True).start()

    def _peeked(self, info, status, founder):
        self.look_btn.setEnabled(True)
        if info is None:
            self.peek_label.setText("No squad with that code." if status == 404
                                    else "Couldn't look it up. Check your connection.")
            return
        self.peek = info
        bits = [f"<b>{_esc(info['name'])}</b>"]
        if founder:
            bits.append(f"founded by {_esc(founder)}")
        bits.append("open" if info["open"] else "locked")
        self.peek_label.setText(" · ".join(bits))
        self.join_btn.setEnabled(bool(info["open"]))

    def _join(self):
        info = self.peek
        if not info:
            return
        self.join_btn.setEnabled(False)
        cl = self.client
        uid, my_name = cl.user_id, cl.display_name or "Me"

        def job():
            try:
                status = cl.join_squad(uid, info["id"], my_name)
            except Exception:
                status = 0
            mw.taskman.run_on_main(lambda: self._joined(info, status))

        threading.Thread(target=job, daemon=True).start()

    def _joined(self, info, status):
        if status in (200, 201):
            self.on_joined({"id": info["id"], "code": info["code"],
                            "name": info["name"], "founder": info["founder"]})
            self.accept()
            return
        self.join_btn.setEnabled(True)
        self.peek_label.setText("Locked." if status == 403
                                else "Couldn't join. Check your connection.")

    # ---- create ----
    def _create(self):
        name = " ".join(self.name_edit.text().split())[:SQUAD_NAME_MAX]
        if not name:
            self.made_label.setText("Give it a name.")
            return
        self.create_btn.setEnabled(False)
        cl = self.client
        uid, my_name = cl.user_id, cl.display_name or "Me"

        def job():
            try:
                squad = cl.create_squad(uid, name, my_name)
            except Exception:
                squad = None
            mw.taskman.run_on_main(lambda: self._created(squad))

        threading.Thread(target=job, daemon=True).start()

    def _created(self, squad):
        self.create_btn.setEnabled(True)
        if not squad:
            self.made_label.setText("Couldn't create it. Check your connection.")
            return
        copy_text(invite_text(squad["name"], squad["code"]))
        self.made_label.setText(f"<b>{_esc(squad['name'])}</b> · code "
                                f"<b>{squad['code']}</b> · invite copied")
        self.name_edit.setText("")
        self.on_joined(squad)


def _esc(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))
