"""3.8.1, the plan's ··· menu › Held back: N cards…: what Hold back (or
Put back) keeps shut here, by date, and why; Open them (one undo step; a
leech stays shut; Hold back stays on for what an author adds later) ·
Stop holding back (opens them and turns it off) · Close. Local: no
request. Plan and date names are the author's: plain text only."""

from aqt.qt import QDialog, QDialogButtonBox, QLabel, QPushButton, Qt, QVBoxLayout

from . import attach_alive, tone


def _plain(text, muted=False, bold=False):
    w = QLabel(str(text))
    w.setTextFormat(Qt.TextFormat.PlainText)
    w.setWordWrap(True)
    if muted:
        w.setStyleSheet(f"color: {tone('muted')}; font-size: 11.5px;")
    elif bold:
        w.setStyleSheet("font-weight: 600;")
    return w


class HeldDialog(QDialog):
    """view: plan_flow.held_view ({name, n, lines, more, why, leeches,
    holding}). choice: "open", "stop" or None (Close)."""

    def __init__(self, parent, view):
        super().__init__(parent)
        attach_alive(self)
        self.choice = None
        n = int(view.get("n") or 0)
        self.setWindowTitle("Held back")
        self.setMinimumWidth(420)
        root = QVBoxLayout(self)
        root.addWidget(_plain(f"{view.get('name') or 'The plan'} holds back {n:,} card{'s' if n != 1 else ''}", bold=True))
        self.why = _plain(view.get("why") or "")
        root.addWidget(self.why)
        lines = [f"• {x}" for x in view.get("lines") or []]
        more = int(view.get("more") or 0)
        if more:
            lines.append(f"and {more:,} more date{'s' if more != 1 else ''}")
        self.list = _plain("\n".join(lines))
        self.list.setVisible(bool(lines))
        root.addWidget(self.list)
        lee = int(view.get("leeches") or 0)
        note = ("Open them: one undo step."
                + (f" {lee:,} more {'is a leech' if lee == 1 else 'are leeches'} and stay{'s' if lee == 1 else ''} shut."
                   if lee else "")
                + (" What an author adds to later dates is still held back." if view.get("holding") else ""))
        self.note = _plain(note, muted=True)
        root.addWidget(self.note)
        buttons = QDialogButtonBox()
        buttons.addButton("Close", QDialogButtonBox.ButtonRole.RejectRole).clicked.connect(self.reject)
        self.stop_btn = QPushButton("Stop holding back")
        self.stop_btn.setToolTip("Opens them, and nothing more is held back.")
        self.stop_btn.clicked.connect(lambda: self._go("stop"))
        buttons.addButton(self.stop_btn, QDialogButtonBox.ButtonRole.ActionRole)
        self.stop_btn.setVisible(bool(view.get("holding")))  # after addButton, which shows it
        self.open_btn = QPushButton("Open them")
        self.open_btn.setDefault(True)
        self.open_btn.clicked.connect(lambda: self._go("open"))
        buttons.addButton(self.open_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        root.addWidget(buttons)

    def _go(self, choice):
        self.choice = choice
        self.accept()


def ask_held(parent, view):
    dlg = HeldDialog(parent, view)
    return dlg.choice if dlg.exec() else None
