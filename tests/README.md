# Tests

Two layers, deliberately separate:

| Layer | Command | What it proves | What it cannot prove |
| --- | --- | --- | --- |
| Unit + behavior (`test_due_crew.py`) | `python3 tests/test_due_crew.py` | Client behavior against an in-memory Firestore fake: upload shapes, backfill costs, privacy toggles, share text, board rendering, rename-follow, clipboard paths. | Anything about the **real** rules — the fake *restates* `firestore.rules`; it is a model of intent, not evidence of enforcement. |
| Rules (`rules/`) | `firebase emulators:exec --only firestore "python3 tests/rules/emulator_rules_test.py"` | That the deployed rules text actually enforces friendship consent, squads (the invite-derived id, open/locked joins, member-only reads, founder removal), member row shape, knocks between squadmates, and the retired collections. | Live Anki behavior. |

Requirements: Python 3.9+ and the standard library only for the first layer
(`sqlite3` backs the fake collection). The rules layer needs
[firebase-tools](https://firebase.google.com/docs/cli) and a Java runtime;
it was **not run** on the machine that authored it (neither was installed).
Run it before deploying any rules change.

Neither layer replaces a click-test in a running Anki: see
`docs/manual-anki-checklist.md`.

`tools/preview.py` renders the board HTML for every view and theme into
`tools/preview.html` (gitignored) for browser-side CSS verification. It
simulates Anki's night classes and, since v1.10, Anki 26's `.fancy table`
glass fill — it is a stand-in for the webview, not the webview.
