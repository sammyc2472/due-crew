# Tests

Two layers, deliberately separate:

| Layer | Command | What it proves | What it cannot prove |
| --- | --- | --- | --- |
| Unit + behavior (`test_due_crew.py`) | `python3 tests/test_due_crew.py` | Client behavior against an in-memory Firestore fake: upload shapes, backfill costs, privacy toggles, share text, board rendering, rename-follow, clipboard paths. | Anything about the **real** rules — the fake *restates* `firestore.rules`; it is a model of intent, not evidence of enforcement. |
| Rules (`rules/`) | `firebase emulators:exec --only firestore --project demo-due-crew "python3 tests/rules/emulator_rules_test.py"` (repo root) | That the deployed rules text actually enforces friendship consent, squads (the invite-derived id, open/locked joins, member-only reads, founder removal), member row shape, knocks between squadmates or with the recipient's own code (2.9), the 20-call cap a batch of friends' docs runs into, and the retired collections. | Live Anki behavior. |

The fake also models what the rules cost and where they stop: it counts the
`exists()`/`get()` calls the consent check makes (`store.rule_reads`, billed
as reads, and counted by the reads-budget tests) and refuses a batch past 20
of them, as the emulator does.

Requirements: Python 3.9+ and the standard library only for the first layer
(`sqlite3` backs the fake collection). The rules layer needs
[firebase-tools](https://firebase.google.com/docs/cli) and a Java runtime;
Run it before deploying any rules change (CI runs it on every push).

Neither layer replaces a click-test in a running Anki: see
`docs/manual-anki-checklist.md`.

`tools/preview.py` renders the board HTML for every view and theme into
`tools/preview.html` (gitignored) for browser-side CSS verification. It
simulates Anki's night classes and, since v1.10, Anki 26's `.fancy table`
glass fill — it is a stand-in for the webview, not the webview.

## Dialogs (Qt)

The suite above runs without Qt, so it cannot see the dialogs. Render every
dialog offscreen against the fake Firestore and get a PNG of each, or just
a non-zero exit if one fails to build:

    QT_QPA_PLATFORM=offscreen <python with PyQt6> tools/dialogs.py OUT_DIR

Both crashes shipped on 2026-09-10 (a PyQt6 enum mix and a shadowed tab
widget) fail here in under a second. Run it before any release that
touches `due_crew/ui/`. Without OUT_DIR it writes `dialog-shots/` in the
working directory (gitignored; CI uploads it as an artifact).

`mw.col` here is a real in-memory collection from the suite's builders.
Until 2.6 it was a stub that answered every query with nothing, so Shared
Decks only ever rendered its empty state. A dialog is only covered in the
states the harness puts it in: when one grows a new state, seed it here.

## Continuous integration

`.github/workflows/tests.yml` runs on every push and pull request:

| Job | What it proves |
| --- | --- |
| `lint` | pyflakes over the add-on, tests, and tools. The suite never imports most of the glue, so this is what catches a NameError there. |
| `suite` | `python3 tests/test_due_crew.py` on a clean Python 3.12. |
| `dialogs` | Every Qt dialog builds under PyQt6 offscreen; the PNGs are attached as an artifact so you can look at them. |
| `rules` | `firestore.rules` enforced by the real Firestore emulator (firebase-tools + Java on the runner) — the check this machine cannot run. |
