"""Your plans, as an HTML window in the board's look (Sam's pick after
"Plans end to end": the plan maker as a page, beside your decks). Its
logic is core.PlanCore's, the same the Qt window (window.py) runs; its
clicks and view are webface's; its page is webpage's (page/plan.html,
.css, .js, inlined). This is the Qt shell: a dialog, Anki's web view,
the bridge, the clipboard.

The page says what was clicked as "dcplan:" + JSON through Anki's
bridge (set_bridge_command: only this window's own page, no card's
script, reaches it), and the window answers with the whole view
(dcPlan.show)."""

from aqt.qt import QApplication, QDialog, QTimer, QVBoxLayout

from ..ui import attach_alive
from .webface import WebFace
from .webpage import colors, page_html
from .widgets import fit


class PlanWeb(QDialog, WebFace):
    """Your plans. plans: remote.my_plans' (each with its role); ops: flow.Ops."""

    def __init__(self, parent, col, plans, ops, select=None, tab=None, cfg=None, new=None):
        super().__init__(parent)
        self.web_init(col, plans, ops, select, tab, cfg, new)
        attach_alive(self)
        self.setWindowTitle("Your plans")
        self.setModal(False)
        self.setMinimumSize(900, 580)
        self.setProperty("dcOwnSize", True)
        fit(self, 1240, 820)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        from aqt.webview import AnkiWebView
        self.web = AnkiWebView(self, title="due crew plans")
        self.web.set_bridge_command(self._on_cmd, self)
        lay.addWidget(self.web)
        night = False
        try:
            from aqt.theme import theme_manager
            night = bool(theme_manager.night_mode)
        except Exception:
            pass
        self.web.stdHtml(page_html(self.view(), colors(self.cfg), night), css=[], js=[], context=self)
        self._ready = True
        if self.pid:
            self.load(self.pid)

    def eval_js(self, js):
        self.web.eval(js)

    def later(self, fn):
        QTimer.singleShot(0, fn)

    def copy(self, text):
        QApplication.clipboard().setText(text)

    def save_file(self, name, text):
        import os
        from aqt.qt import QFileDialog, QStandardPaths
        where = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation) or os.path.expanduser("~")
        path, _f = QFileDialog.getSaveFileName(self, "Add to my calendar", os.path.join(where, name), "Calendar (*.ics)")
        if not path:
            return False
        try:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(text)
        except OSError:
            self.say("That file couldn't be saved there. Try another folder.")
            return False
        return True

    def closeEvent(self, e):  # noqa: N802 (Qt's)
        self._ready = False
        try:
            self.web.cleanup()
        except Exception:
            pass
        super().closeEvent(e)


def open_new(start=None, finish_by=None, exam=None):
    """New plan, in this window (the board's ways in call it): flow's."""
    from .flow import open_new as go
    go(start=start, finish_by=finish_by, exam=exam)
