"""Squads: join with a code, or create one. Network runs in the background
and lands on the main thread; the dialog never blocks Anki."""

from aqt.qt import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QVBoxLayout, Qt,
)

from ..backend.firebase import SQUAD_CODE_LEN, SQUAD_NAME_MAX, squad_code_from
from ..app import _bg
from . import attach_alive, copy_text, run_bg, shared_words


def invite_text(name, code):
    from ..share import squad_invite   # one shape for both invites
    return squad_invite(name, code)


def shared_note(cfg):
    """What squadmates see, from the Privacy switches (2.9: they apply to
    squads too). Until then this always listed all four numbers."""
    if cfg.get("paused"):
        return "Sharing is paused: squadmates see your name and nothing new."
    words = "" if cfg.get("show_up") else shared_words(cfg)
    if not words:
        return "Squadmates see your name and which days you studied."
    return f"Squadmates see your name and today's {words}."


class SquadDialog(QDialog):
    def __init__(self, parent, client, on_joined, note=None):
        super().__init__(parent)
        self.client = client
        self.on_joined = on_joined   # main thread: {id, code, name, founder}
        self.peek = None
        attach_alive(self)
        self.setWindowTitle("Squads")
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)

        lay.addWidget(QLabel("<b>Join</b>"))
        row = QHBoxLayout()
        self.code_edit = QLineEdit()
        self.code_edit.setPlaceholderText("Invite code, or paste the invite")
        self.code_edit.textChanged.connect(self._code_changed)
        self.code_edit.returnPressed.connect(self._look_up)
        self.look_btn = QPushButton("Look Up")
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
            Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.made_label)

        hint = QLabel(note or shared_note({}))
        hint.setStyleSheet("font-size: 11px;")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    # ---- join ----
    def _code_changed(self, _text=""):
        self.peek = None
        self.join_btn.setEnabled(False)
        self.peek_label.setText("")

    def _look_up(self):
        # a pasted invite works too: the code is taken from after "code"
        code = squad_code_from(self.code_edit.text())
        if len(code) != SQUAD_CODE_LEN:
            self.peek_label.setText(f"Codes are {SQUAD_CODE_LEN} letters and numbers.")
            return
        self.look_btn.setEnabled(False)
        self.peek_label.setText("Looking up…")
        cl = self.client

        def job():
            info, status = cl.peek_squad(code)
            founder = ""
            if info and info.get("founder"):
                prof, _s = cl.get_doc(f"users/{info['founder']}")
                founder = str((prof or {}).get("displayName") or "")
            return info, status, founder

        def done(result, err):
            info, status, founder = result if result else (None, 0, "")
            self._peeked(info, status, founder)

        run_bg(self, job, done)

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
        # joins and creates report back even if the dialog was closed
        # meanwhile: the server has the membership, so the board must too
        _bg(lambda: cl.join_squad(uid, info["id"], my_name),
            lambda status: self._joined(info, status or 0))

    def _joined(self, info, status):
        if status in (200, 201):
            self.on_joined({"id": info["id"], "code": info["code"],
                            "name": info["name"], "founder": info["founder"]})
            if self._alive:
                self.accept()
            return
        if not self._alive:
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
        _bg(lambda: cl.create_squad(uid, name, my_name), self._created)

    def _created(self, squad):
        if squad:
            copy_text(invite_text(squad["name"], squad["code"]))
            self.on_joined(squad)
        if not self._alive:
            return
        self.create_btn.setEnabled(True)
        if not squad:
            self.made_label.setText("Couldn't create it. Check your connection.")
            return
        self.made_label.setText(f"<b>{_esc(squad['name'])}</b> · code "
                                f"<b>{squad['code']}</b> · invite copied")
        self.name_edit.setText("")


def _esc(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))
