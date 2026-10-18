"""3.8.0: "Why isn't it showing?", the sheet: for the cards picked in
Browse, a line a reason (why.groups) and Anki's own fix beside it. A fix
runs as one undo step and the lines are read again (why_flow.fix).
Plain text only: deck names are the person's own, but a QLabel would
read them as rich text, so it's told not to."""

from aqt.qt import QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, Qt, QVBoxLayout, QWidget

from . import attach_alive, tone


class WhyDialog(QDialog):
    """groups: [{say, label, fix, n}]; on_fix(group) runs one; more: only
    the first why.MOST of the picked cards were read."""

    def __init__(self, parent, groups, on_fix, more=False):
        super().__init__(parent)
        attach_alive(self)
        self.setWindowTitle("Why isn't it showing?")
        self.setMinimumWidth(460)
        self._fix = on_fix
        lay = QVBoxLayout(self)
        self.list = QVBoxLayout()
        self.list.setSpacing(8)
        lay.addLayout(self.list)
        self.note = QLabel()
        self.note.setTextFormat(Qt.TextFormat.PlainText)
        self.note.setStyleSheet(f"color: {tone('muted')}; font-size: 11px;")
        self.note.setWordWrap(True)
        lay.addWidget(self.note)
        foot = QHBoxLayout()
        foot.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        foot.addWidget(close)
        lay.addLayout(foot)
        self._more = more
        self.show_groups(groups)

    def show_groups(self, groups):
        while self.list.count():
            w = self.list.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        self.rows = []
        for i, g in enumerate(groups):
            if i:
                line = QFrame()
                line.setFrameShape(QFrame.Shape.HLine)
                line.setStyleSheet("color: rgba(128,128,128,0.3);")
                self.list.addWidget(line)
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            say = QLabel(g["say"])
            say.setTextFormat(Qt.TextFormat.PlainText)
            say.setWordWrap(True)
            h.addWidget(say, 1)
            btn = None
            if g.get("fix") and g.get("label"):
                btn = QPushButton(g["label"])
                btn.clicked.connect(lambda _=False, g=g, b=btn: self._go(g, b))
                h.addWidget(btn, 0, Qt.AlignmentFlag.AlignTop)
            self.list.addWidget(row)
            self.rows.append((say, btn))
        if not groups:
            say = QLabel("Nothing to say about these cards.")
            self.list.addWidget(say)
            self.rows.append((say, None))
        bits = []
        if self._more:
            bits.append("Only the first 2,000 picked cards were read.")
        if any(g.get("fix") and g["fix"][0] != "study" for g in groups):
            bits.append("Each fix is Anki's own, and Edit › Undo takes it back.")
        self.note.setText(" ".join(bits))
        self.note.setVisible(bool(bits))

    def _go(self, g, btn):
        btn.setEnabled(False)
        btn.setText("…")
        self._fix(g)
