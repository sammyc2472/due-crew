"""Server-rules update dialog, opened from the board's stale-rules notice.

The add-on ships the rules text it needs (firestore.rules, kept identical to
the repo's root copy), so the fix is one paste for whoever runs the crew's
Firebase project. No network in here.
"""

import html
import os

from aqt.qt import (
    QApplication, QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QVBoxLayout,
)
from aqt.utils import tooltip

from . import attach_alive

CONSOLE_URL = "https://console.firebase.google.com"


def rules_text():
    path = os.path.join(os.path.dirname(__file__), "..", "firestore.rules")
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return ""


class RulesUpdateDialog(QDialog):
    def __init__(self, parent, server_label=""):
        super().__init__(parent)
        self.setWindowTitle("Due Crew — Server rules update")
        self.setMinimumWidth(480)
        attach_alive(self)
        root = QVBoxLayout(self)

        where = (f"the crew server <b>{html.escape(server_label)}</b>"
                 if server_label else "this crew's server")
        intro = QLabel(
            f"The Firestore rules on {where} are older than this version of "
            f"Due Crew needs, so some sharing quietly fails. Whoever runs the "
            f"crew's Firebase project fixes it in about a minute:")
        intro.setWordWrap(True)
        root.addWidget(intro)

        steps = QLabel(
            f"1. Open {CONSOLE_URL} and pick the crew's project.<br>"
            "2. Build → Firestore Database → Rules.<br>"
            "3. Replace everything with the rules below → Publish.")
        steps.setWordWrap(True)
        steps.setStyleSheet("font-size: 12px;")
        root.addWidget(steps)

        self.rules = QPlainTextEdit()
        self.rules.setPlainText(rules_text() or "(rules file missing from "
                                "this install — copy firestore.rules from "
                                "the Due Crew repository instead)")
        self.rules.setReadOnly(True)
        self.rules.setMinimumHeight(180)
        self.rules.setStyleSheet("font-family: Menlo, monospace; font-size: 11px;")
        root.addWidget(self.rules)

        note = QLabel("Nothing is lost in the meantime — sharing catches up "
                      "on the first sync after the rules are published.")
        note.setWordWrap(True)
        note.setStyleSheet("font-size: 11px;")
        root.addWidget(note)

        buttons = QHBoxLayout()
        copy = QPushButton("Copy rules")
        copy.setDefault(True)
        copy.clicked.connect(self._copy)
        buttons.addWidget(copy)
        buttons.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        root.addLayout(buttons)

    def _copy(self):
        text = rules_text()
        if text:
            QApplication.clipboard().setText(text)
            tooltip("Rules copied — paste them into the Firebase console.")
