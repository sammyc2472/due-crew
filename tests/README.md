# Tests

Two layers, deliberately separate:

| Layer | Command | What it proves | What it cannot prove |
| --- | --- | --- | --- |
| Client (`test_due_crew.py`) | `python3 tests/test_due_crew.py` | Client behavior against an in-memory fake of the Worker API (`fakes.FakeWorker`): what a sync sends, what a refresh reads, the request budget (a refresh is one request), privacy switches, share text, board rendering. | Anything about the **real** server: the fake *restates* the Worker's rules; it is a model of intent. |
| Worker (`worker/test/`) | `cd worker && npm ci && npx vitest run` | The Worker itself, in real workerd with a local D1: sign-in by code (limits, lockout, replay), sessions, and the consent model. `consent.test.ts` restates every check the 2.x rules test had, in its order and under its label. | Live Anki behavior. |

`tools/smoke_worker.py` runs the real client against the real Worker
(`wrangler dev`, local D1): where the fake and the Worker's own tests each
prove one side, it proves they agree. Its docstring has the three commands;
CI runs it in the worker job.

`tests/test_planner.py` is the labs plan window's (`due_crew/planner`,
`docs/planner.md`), on the same fakes: `python3 tests/test_planner.py`.

Requirements: Python 3.9+ and the standard library for the first layer
(`sqlite3` backs the fake collection); Node 22 for the Worker. CI runs
both on every push.

Neither layer replaces a click-test in a running Anki: see
`docs/manual-anki-checklist.md`.

`tools/preview.py` renders the board HTML for every view and theme into
`tools/preview.html` (gitignored) for browser-side CSS verification. It
simulates Anki's night classes and, since v1.10, Anki 26's `.fancy table`
glass fill — it is a stand-in for the webview, not the webview.

## Motion (Chromium)

`tools/motion_audit.js` plays every motion in `tools/motion_preview.html`
with its frames held and stepped by hand, and counts the pixels that
differ between each one's last frame and the page once it has cleaned up
(a pill that ends square, a box that ends its padding too tall). It needs
Playwright's Chromium; it isn't in CI:

    python3 tools/motion_preview.py
    NODE_PATH=$(npm root -g) node tools/motion_audit.js [key,key] [--out DIR]

Over 500 pixels is a jump (a Pip's blink, a breathing chip or text drawn
in its own layer while it moves make a few hundred at most); it exits 1
and names them. `--out` keeps every frame.

## Dialogs (Qt)

The suite above runs without Qt, so it cannot see the dialogs. Render every
dialog offscreen against the fake Worker and get a PNG of each, or just
a non-zero exit if one fails to build:

    QT_QPA_PLATFORM=offscreen <python with PyQt6> tools/dialogs.py OUT_DIR

Both crashes shipped on 2026-09-10 (a PyQt6 enum mix and a shadowed tab
widget) fail here in under a second. Since 3.9.1 it also fails on what a
person would see as broken (`fits`): a button, tick or choice narrower
than its words, a box narrower than its words, two controls on top of each
other, a window shorter or narrower than its rows. It renders on a
laptop-sized screen (1440x900) in 13px type, as a Mac draws; `kitchen.png`
is every kind of control in one window. `DC_THEME=dark` renders the dark
look; `DC_APP_QSS=file.qss` puts an app-wide style sheet under the
windows', as Anki's own widget style does. Run it before any release that
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
