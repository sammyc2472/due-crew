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
WIDTH, START_H, MIN_H = 660, 190, 140  # a box and its filters; it grows with what it finds
ASK_SECS = 3.0  # how long a height asked for stays ours when the window manager reports it late


class MagicWindow(QDialog):
    def __init__(self, parent, face):
        super().__init__(parent)
        self.face = face
        attach_alive(self)
        # 3.9.7 (the energy review): closed, it goes, its page and its deck's index with it (each open
        # had left the last window hidden for the rest of the session), as the plan window does
        from aqt.qt import Qt
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("Magic search")
        self.setModal(False)
        # round 2 (Sam: "WAY too big and should change size according to content"): as wide
        # as its how-to's two columns, as tall as what's in it (the page says, size)
        self.setMinimumSize(480, MIN_H)
        self.setProperty("dcOwnSize", True)
        self._fitting, self._mine, self._top = False, False, None
        try:
            from ..planner.widgets import fit
            fit(self, WIDTH, START_H)
        except Exception:
            self.resize(WIDTH, START_H)
        # the heights asked for lately: a resize to one of them is ours, even when the window manager says so
        # late (3.9.9, Sam's Mac: two asks in a row, as when it opens on a search already typed, and the first
        # one's late word looked like a drag; the window then kept its first size whatever it found)
        self._asks = [(0.0, self.height())]
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        from aqt.webview import AnkiWebView
        self.web = AnkiWebView(self, title="due crew magic search")
        self.web.set_bridge_command(self._on_cmd, self)
        lay.addWidget(self.web)
        face.push = self.push
        face.close_win = self.close
        self.web.stdHtml(page_html(face.view(), cfg()), css=[], js=[], context=self)

    def closeEvent(self, e):  # noqa: N802 (Qt's)
        try:
            self.web.cleanup()
        except Exception:
            pass
        super().closeEvent(e)

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
        if not isinstance(a, dict) or not isinstance(a.get("cmd"), str):
            return
        if a["cmd"] == "size":
            try:
                self.fit_to(int(a.get("h") or 0))
            except (TypeError, ValueError):
                pass
            return
        self.face.on(a["cmd"], a)

    # -- its size: what's in it --

    def showEvent(self, e):
        super().showEvent(e)
        if self._top is None:
            # a search box sits high, as Spotlight's does: it grows down from there
            par = self.parentWidget()
            room = self._room()
            if par is not None and par.isVisible():
                g = par.frameGeometry()
                x, y = g.x() + (g.width() - self.width()) // 2, g.y() + max(40, g.height() // 8)
            elif room is not None:
                x, y = room.x() + (room.width() - self.width()) // 2, room.y() + room.height() // 8
            else:
                x, y = self.x(), self.y()
            if room is not None:
                x = max(room.x(), min(x, room.x() + room.width() - self.width()))
                y = max(room.y(), y)
            self.move(x, y)
            self._top = self.y()

    def _room(self):
        from aqt.qt import QGuiApplication
        scr = self.screen() if hasattr(self, "screen") and self.screen() is not None else QGuiApplication.primaryScreen()
        return scr.availableGeometry() if scr is not None else None

    def fit_to(self, h):
        """The page's height: the window's, between its least and what the
        screen has below its top (then it moves up, then the page scrolls).
        Not once I've sized it myself."""
        if self._mine or h <= 0 or not getattr(self, "_alive", False):
            return
        room = self._room()
        frame = self.frameGeometry().height() - self.geometry().height()
        most = int(room.height() * 0.9) - frame if room is not None else 900
        want = max(MIN_H, min(int(h), most))
        if want == self.height():
            return
        self._fitting = True
        self._ask(want)
        try:
            self.resize(self.width(), want)
            if room is not None:
                top = self._top if self._top is not None else self.y()
                low = room.y() + room.height() - want - frame
                self.move(self.x(), max(room.y(), min(top, low)))
        finally:
            self._fitting = False

    def _ask(self, h):
        import time
        now = time.monotonic()
        self._asks = [(t, a) for t, a in self._asks[-7:] if now - t < ASK_SECS] + [(now, h)]

    def _ours(self, h):
        """Is a resize to h one this window asked for (the last, or any in the last few seconds)?"""
        import time
        now = time.monotonic()
        return any(abs(h - a) <= 6 for t, a in self._asks[:-1] if now - t < ASK_SECS) or abs(h - self._asks[-1][1]) <= 6

    def resizeEvent(self, e):
        super().resizeEvent(e)
        h = e.size().height()
        if self._fitting or self._ours(h) or not self.isVisible() or self._top is None:
            return
        if e.oldSize().isValid() and e.oldSize().height() != h:
            self._mine = True  # dragged to a size: it keeps it
