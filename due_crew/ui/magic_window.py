"""Magic search's window (3.9.7): a dialog, Anki's web view and the bridge.
Its logic is magic_flow.Search's; its page magic_html's. The page says what
was clicked as "dcmagic:" + JSON through Anki's bridge (set_bridge_command:
only this window's own page reaches it, never a card's script), and the
window answers with the whole view (dcMagic.show)."""

import json

from aqt.qt import QDialog, QVBoxLayout

from ..app import cfg
from ..magic_html import page_html
from . import attach_alive

PREFIX = "dcmagic:"


class MagicWindow(QDialog):
    def __init__(self, parent, face):
        super().__init__(parent)
        self.face = face
        attach_alive(self)
        self.setWindowTitle("Magic search")
        self.setModal(False)
        self.setMinimumSize(520, 420)
        self.setProperty("dcOwnSize", True)
        try:
            from ..planner.widgets import fit
            fit(self, 780, 680)
        except Exception:
            self.resize(780, 680)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        from aqt.webview import AnkiWebView
        self.web = AnkiWebView(self, title="due crew magic search")
        self.web.set_bridge_command(self._on_cmd, self)
        lay.addWidget(self.web)
        face.push = self.push
        face.close_win = self.close
        self.web.stdHtml(page_html(face.view(), cfg()), css=[], js=[], context=self)

    def push(self):
        if getattr(self, "_alive", False):
            self.web.eval("dcMagic.show(%s);" % json.dumps(self.face.view(), ensure_ascii=True).replace("<", "\\u003c"))

    def _on_cmd(self, msg):
        if not isinstance(msg, str) or not msg.startswith(PREFIX):
            return
        try:
            a = json.loads(msg[len(PREFIX):])
        except ValueError:
            return
        if isinstance(a, dict) and isinstance(a.get("cmd"), str):
            self.face.on(a["cmd"], a)
