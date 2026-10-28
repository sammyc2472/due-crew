"""3.9.5, game night's TV: the table page (duecrew.com/t/CODE#anki) in a
window of Anki's own, handed tonight's pack once it loads. Drag it to the
big screen; the page's Full screen fills it. Its web profile is off the
record (nothing kept), and the pack goes only to a page of the site.

Qt's web engine is imported here alone, when the TV opens: the suite's Qt
and tools/dialogs.py have none of it."""

import json

_PROFILE = []  # one off-the-record profile for every TV, kept for Anki's life: a page goes before its profile


def _profile():
    from aqt.qt import QApplication, QWebEngineProfile
    if not _PROFILE:
        _PROFILE.append(QWebEngineProfile(QApplication.instance()))  # no name: off the record
    return _PROFILE[0]


def open_tv(parent, site, payload):
    from aqt.qt import QUrl, QVBoxLayout, QWidget, Qt
    from aqt.qt import QWebEnginePage, QWebEngineSettings, QWebEngineView

    class TvWindow(QWidget):
        def __init__(self):
            super().__init__(None, Qt.WindowType.Window)
            self.setWindowTitle("Due Crew · Game night")
            self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)  # closed, its socket goes, and the table knows
            self.handed = False
            self.page = QWebEnginePage(_profile(), self)
            self.page.settings().setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, True)
            self.page.fullScreenRequested.connect(self._full)
            self.page.loadFinished.connect(self._loaded)
            self.view = QWebEngineView(self)
            self.view.setPage(self.page)
            box = QVBoxLayout(self)
            box.setContentsMargins(0, 0, 0, 0)
            box.addWidget(self.view)
            self.site = QUrl(site)
            code = str(payload.get("code") or "BOTS")
            self.view.setUrl(QUrl(f"{site}/t/{code}#anki"))
            self.resize(1280, 820)

        def _loaded(self, ok):
            url = self.page.url()
            if not ok or self.handed or url.host() != self.site.host() or url.port() != self.site.port():
                return
            self.handed = True
            self.page.runJavaScript("window.__dcAnki = %s; window.dcAnki && window.dcAnki(window.__dcAnki);" % json.dumps(payload))

        def _full(self, req):
            req.accept()
            if req.toggleOn():
                self.showFullScreen()
            else:
                self.showNormal()

    w = TvWindow()
    tvs = getattr(parent, "_due_crew_tvs", None)
    if tvs is None:
        tvs = parent._due_crew_tvs = []
    tvs[:] = [t for t in tvs if t.isVisible()] + [w]  # kept alive while open
    w.show()
    w.raise_()
    return w
