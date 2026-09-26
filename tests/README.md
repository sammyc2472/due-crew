# Tests

Three layers, deliberately separate:

| Layer | Command | What it proves | What it cannot prove |
| --- | --- | --- | --- |
| Client (`test_due_crew.py`) | `python3 tests/test_due_crew.py` | Client behavior against an in-memory fake of the Worker API (`fakes.FakeWorker`): what a sync sends, what a refresh reads, the request budget (a refresh is one request), privacy switches, the 2.x restore, share text, board rendering. | Anything about the **real** server: the fake *restates* the Worker's rules; it is a model of intent. |
| Worker (`worker/test/`) | `cd worker && npm ci && npx vitest run` | The Worker itself, in real workerd with a local D1: sign-in by code (limits, lockout, replay), sessions, and the consent model. `consent.test.ts` restates every check the Firestore rules test had, in its order and under its label. | Live Anki behavior. |
| Rules (`rules/`), until the Firebase project goes | `firebase emulators:exec --only firestore --project demo-due-crew "python3 tests/rules/emulator_rules_test.py"` (repo root) | That `firestore.rules`, still live for 2.x clients until the cutover, enforces what it says. | Anything about 3.0. |

`tools/smoke_worker.py` runs the real client against the real Worker
(`wrangler dev`, local D1): where the fake and the Worker's own tests each
prove one side, it proves they agree. Its docstring has the three commands;
CI runs it in the worker job.

Requirements: Python 3.9+ and the standard library for the first layer
(`sqlite3` backs the fake collection); Node 22 for the Worker; the rules
layer needs [firebase-tools](https://firebase.google.com/docs/cli) and a
Java runtime. CI runs all three on every push.

Neither layer replaces a click-test in a running Anki: see
`docs/manual-anki-checklist.md`.

`tools/preview.py` renders the board HTML for every view and theme into
`tools/preview.html` (gitignored) for browser-side CSS verification. It
simulates Anki's night classes and, since v1.10, Anki 26's `.fancy table`
glass fill — it is a stand-in for the webview, not the webview.

## Dialogs (Qt)

The suite above runs without Qt, so it cannot see the dialogs. Render every
dialog offscreen against the fake Worker and get a PNG of each, or just
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
