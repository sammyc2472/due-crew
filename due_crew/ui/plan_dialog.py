"""Make a plan from a deck (3.1, mock 1.1): the deck's tag and subdeck
names with card counts go to Due Crew, and the builder opens on the site,
signed in by a one-time link. Names and counts only, never card text.

The deck is read on the main thread (one query per deck picked); the two
requests (PUT /plans/trees, POST /auth/link) run in the background."""

from urllib.parse import quote

from aqt.qt import (
    QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
    QRadioButton, QVBoxLayout,
)

from . import attach_alive, esc, run_bg
from .. import plans as P

KINDS = (("both", "Tags and subdecks"), ("tags", "Tags only"), ("decks", "Subdecks only"))


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

        root.addWidget(QLabel("Units can be"))
        row = QHBoxLayout()
        self.kinds = QButtonGroup(self)
        for i, (_key, label) in enumerate(KINDS):
            b = QRadioButton(label)
            b.setChecked(i == 0)
            self.kinds.addButton(b, i)
            row.addWidget(b)
        row.addStretch()
        root.addLayout(row)

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
        self.kinds.idToggled.connect(lambda *_: self._update())
        self._update()

    def _kind(self):
        return KINDS[max(0, self.kinds.checkedId())][0]

    def _tree(self):
        did = self.deck.currentData()
        if did is None:
            return None, [], []
        if did not in self.indexes:
            self.indexes[did] = P.DeckIndex(self.col, did)
        kind = self._kind()
        tags, decks = self.indexes[did].tree(with_tags=kind != "decks", with_decks=kind != "tags")
        # the server takes paths of up to 200 characters, one line each
        ok = lambda path: len(path) <= 200 and path.isprintable()
        return (self.indexes[did].name, [t for t in tags if ok(t[0])], [d for d in decks if ok(d[0])])

    def _update(self, *_):
        name, tags, decks = self._tree()
        if name is None:
            self.found.setText("No decks yet.")
            self.go.setEnabled(False)
            return
        kind = self._kind()
        parts = []
        if kind != "decks":
            parts.append(f"<b>{len(tags):,}</b> tag name{'s' if len(tags) != 1 else ''}")
        if kind != "tags":
            parts.append(f"<b>{len(decks):,}</b> subdeck name{'s' if len(decks) != 1 else ''}")
        self.found.setText(f"Sends {' and '.join(parts)}, with how many cards each has. No card text.")
        self.go.setEnabled(bool(tags or decks))
        if not (tags or decks):
            self.found.setText(f"{esc(name)} has no {'tags' if kind == 'tags' else 'subdecks' if kind == 'decks' else 'tags or subdecks'} "
                               "to make units from.")

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
