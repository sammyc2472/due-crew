"""Make a plan from a deck (3.1, mock 1.1): the deck's tag and subdeck
names with card counts go to Due Crew, and the builder opens on the site,
signed in by a one-time link. Names and counts only, never card text.

The deck is read on the main thread (one query per deck picked); the two
requests (PUT /plans/trees, POST /auth/link) run in the background."""

from urllib.parse import quote

from aqt.qt import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QVBoxLayout,
)

from . import attach_alive, esc, run_bg
from .. import plans as P

class MakePlanDialog(QDialog):
    def __init__(self, parent, client, col, site, open_link=None):
        super().__init__(parent)
        self.client, self.col, self.site = client, col, site
        self.open_link = open_link   # tests pass their own; Anki's openLink otherwise
        self.indexes = {}            # did -> DeckIndex, read once per deck
        self.url = None
        attach_alive(self)
        self.setWindowTitle("Make a plan")
        self.setMinimumWidth(440)
        root = QVBoxLayout(self)

        form = QFormLayout()
        self.deck = QComboBox()
        for did, name in P.deck_choices(col):
            self.deck.addItem(name, did)
        form.addRow("Deck", self.deck)
        root.addLayout(form)
        # a plan is one deck and everything under it
        two = QLabel("To plan two decks, put them under one parent deck in Anki.")
        two.setWordWrap(True)
        two.setStyleSheet("font-size: 12px;")
        root.addWidget(two)

        self.found = QLabel("")
        self.found.setWordWrap(True)
        self.found.setStyleSheet("font-size: 12px;")
        root.addWidget(self.found)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("font-size: 12px;")
        root.addWidget(self.status)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                        | QDialogButtonBox.StandardButton.Cancel)
        self.go = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.go.setText("Open the builder")
        self.buttons.accepted.connect(self._open)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)

        self.deck.currentIndexChanged.connect(self._update)
        self._update()

    def _tree(self):
        did = self.deck.currentData()
        if did is None:
            return None, [], []
        if did not in self.indexes:
            self.indexes[did] = P.DeckIndex(self.col, did)
        tags, decks = self.indexes[did].tree()
        # the server takes paths of up to 200 characters, one line each
        ok = lambda path: len(path) <= 200 and path.isprintable()
        return (self.indexes[did].name, [t for t in tags if ok(t[0])], [d for d in decks if ok(d[0])])

    def _update(self, *_):
        name, tags, decks = self._tree()
        if name is None:
            self.found.setText("No decks yet.")
            self.go.setEnabled(False)
            return
        self.found.setText("Sends its tag and subdeck names with card counts. Never card text.")
        self.go.setEnabled(bool(tags or decks))
        if not (tags or decks):
            self.found.setText(f"{esc(name)} has no cards yet.")

    def _open(self):
        name, tags, decks = self._tree()
        if not name:
            return
        self.go.setEnabled(False)
        self.status.setText("Opening the builder…")
        cl, site = self.client, self.site

        def job():
            if not cl.put_tree(name, tags, decks):
                return None
            token = cl.site_link()
            # the token rides the fragment, which never reaches a server log
            return f"{site}/plans/new?deck={quote(name, safe='')}#{token}" if token else None

        def done(url, err):
            if not url:
                self.go.setEnabled(True)
                self.status.setText("Couldn't reach Due Crew. Check your connection.")
                return
            self.url = url
            opener = self.open_link
            if opener is None:
                from aqt.utils import openLink as opener
            opener(url)
            self.accept()

        run_bg(self, job, done)
