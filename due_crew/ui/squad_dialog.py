"""Squads: join with a code, or create one. Network runs in the background
and lands on the main thread; the dialog never blocks Anki."""

from aqt.qt import (
    QDialog, QDialogButtonBox, QGridLayout, QLabel, QLineEdit, QPushButton,
    QVBoxLayout, Qt,
)

from ..backend.shapes import SQUAD_CODE_LEN, SQUAD_NAME_MAX, squad_code_from
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
    def __init__(self, parent, client, on_joined, note=None, code=""):
        super().__init__(parent)
        self.client = client
        self.on_joined = on_joined   # main thread: {id, code, name, founder}
        self.peek = None
        attach_alive(self)
        self.setWindowTitle("Squads")
        self.setMinimumWidth(400)
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        # one grid, so both fields and both buttons line up (3.5.0)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(0, 1)

        grid.addWidget(_head("Join a squad"), 0, 0, 1, 2)
        self.code_edit = QLineEdit()
        self.code_edit.setPlaceholderText("Its code, or paste the invite")
        self.code_edit.textChanged.connect(self._code_changed)
        self.code_edit.returnPressed.connect(self._look_up)
        self.look_btn = QPushButton("Look Up")
        self.look_btn.clicked.connect(self._look_up)
        grid.addWidget(self.code_edit, 1, 0)
        grid.addWidget(self.look_btn, 1, 1)
        # what the code is, with Join under Look Up (the buttons' column, so
        # it's never squeezed by a long name); nothing at all until then
        self.peek_label = QLabel("")
        self.peek_label.setWordWrap(True)
        self.peek_label.setVisible(False)
        self.join_btn = QPushButton("Join")
        self.join_btn.setVisible(False)
        self.join_btn.setDefault(True)
        self.join_btn.clicked.connect(self._join)
        grid.addWidget(self.peek_label, 2, 0)
        grid.addWidget(self.join_btn, 2, 1, Qt.AlignmentFlag.AlignTop)

        grid.addWidget(_head("Start a squad"), 3, 0, 1, 2)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Its name")
        self.name_edit.setMaxLength(SQUAD_NAME_MAX)
        self.name_edit.returnPressed.connect(self._create)
        self.create_btn = QPushButton("Create")
        self.create_btn.clicked.connect(self._create)
        grid.addWidget(self.name_edit, 4, 0)
        grid.addWidget(self.create_btn, 4, 1)
        self.made_label = QLabel("")
        self.made_label.setWordWrap(True)
        self.made_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.made_label.setVisible(False)
        grid.addWidget(self.made_label, 5, 0, 1, 2)
        width = max(b.sizeHint().width() for b in (self.look_btn, self.create_btn, self.join_btn))
        for b in (self.look_btn, self.create_btn, self.join_btn):
            b.setMinimumWidth(width)
            b.setMinimumHeight(b.sizeHint().height())
        lay.addLayout(grid)

        lay.addSpacing(6)
        hint = QLabel(note or shared_note({}))
        hint.setStyleSheet("font-size: 11px; color: palette(placeholder-text);")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        if code:
            self.code_edit.setText(code)
            self._look_up()

    # ---- join ----
    def _code_changed(self, _text=""):
        self.peek = None
        self._say("")

    def _say(self, text, join=False):
        """The line under the code: what it is, or what went wrong."""
        self.peek_label.setText(text)
        self.join_btn.setVisible(join)
        self.join_btn.setEnabled(join)
        self.peek_label.setVisible(bool(text))
        # the dialog grows to fit the row (it was drawn without it)
        self.adjustSize()

    def _look_up(self):
        # a pasted invite works too: the code is taken from after "code"
        code = squad_code_from(self.code_edit.text())
        if len(code) != SQUAD_CODE_LEN:
            self._say(f"Codes are {SQUAD_CODE_LEN} letters and numbers.")
            return
        self.look_btn.setEnabled(False)
        self._say("Looking up…")
        cl = self.client

        def job():
            info, status = cl.peek_squad(code)
            founder = (info or {}).get("founder_name") or ""
            if info and info.get("founder") and not founder:  # a server before 3.7.1
                founder = str((cl.profile(info["founder"]) or {}).get("name") or "")
            return info, status, founder

        def done(result, err):
            info, status, founder = result if result else (None, 0, "")
            self._peeked(info, status, founder)

        run_bg(self, job, done)

    def _peeked(self, info, status, founder):
        self.look_btn.setEnabled(True)
        if info is None:
            self._say("No squad with that code." if status == 404
                      else "Couldn't look it up. Check your connection.")
            return
        self.peek = info
        bits = [f"<b>{_esc(info['name'])}</b>"]
        if founder:
            bits.append(f"founded by {_esc(founder)}")
        if not info["open"]:
            bits.append("locked")
        self._say(" · ".join(bits), join=bool(info["open"]))

    def _join(self):
        info = self.peek
        if not info:
            return
        self.join_btn.setEnabled(False)
        cl = self.client
        # joins and creates report back even if the dialog was closed
        # meanwhile: the server has the membership, so the board must too
        _bg(lambda: cl.join_squad(info["id"], info.get("code") or ""),
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
        self._say("Locked." if status == 403 else "Couldn't join. Check your connection.",
                  join=status != 403)

    # ---- create ----
    def _made(self, text):
        self.made_label.setText(text)
        self.made_label.setVisible(bool(text))

    def _create(self):
        name = " ".join(self.name_edit.text().split())[:SQUAD_NAME_MAX]
        if not name:
            self._made("Give it a name.")
            return
        self.create_btn.setEnabled(False)
        cl = self.client
        _bg(lambda: cl.create_squad(name), self._created)

    def _created(self, squad):
        if squad:
            copy_text(invite_text(squad["name"], squad["code"]))
            self.on_joined(squad)
        if not self._alive:
            return
        self.create_btn.setEnabled(True)
        if not squad:
            self._made("Couldn't create it. Check your connection.")
            return
        self._made(f"<b>{_esc(squad['name'])}</b> · code <b>{squad['code']}</b> · invite copied")
        self.name_edit.setText("")


def _head(text):
    label = QLabel(f"<b>{text}</b>")
    label.setStyleSheet("margin-top: 4px;")
    return label


def _esc(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))
