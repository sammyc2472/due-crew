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
`docs/manual-anki-checklist.md`, and the robot below.

## The robot click-test (real Anki)

`tools/click_test.py` runs real Anki 25.02.7, offscreen, with the add-on
copied from `due_crew/` into a fresh Anki folder and a collection it makes
itself (`tools/click_test/collection.py`: a few hundred made-up notes in
two decks, hierarchical tags, a month of reviews). It signs in to
`fakes.FakeWorker` in its own process, with a crew of four, a squad and a
cheer waiting, then goes through the add-on the way the manual click-test
does:

- New plan › Start empty, a set, a crewmate follows, another set, Review
  and send › Send (the fake server has it); two to-dos in the You box;
- the board's windows (the Cheer window, a crewmate's card, a sheet): Esc
  closes each and the key goes back to what opened it; the Cheer window's
  Send and a sheet's yes reach the server; a click on the grey top bar
  closes the window;
- every view and tab (Crew's Today, Week, Decks; Squads; You's Today,
  Upcoming, Later, Plans, Insights; Pip Party; Settings' three; Pip's
  closet), and in each every control that sends a `duecrew:` command,
  pressed with a DOM click (a control that shows on hover gets a pointer
  over its row first); Magic search's window; the top bar's ▶ Fifteen?;
- a deck, Study Now, the first card timed, five answered, then a few board
  clicks after the review;
- a minute on the Decks screen with no input, CPU sampled in 5 s slices.

It fails (exit 1) when a press reaches no handler (the page sent nothing, or
sent a command nothing of the add-on's ran for), anything raises (stderr,
`traceback.print_exc`, `sys.excepthook`, or a page's script error in a view
the add-on draws), the first card takes over 3 s, or CPU from 20 s after the
last input is over 5% of one core (`steps.py`'s `CPU_REST_MAX`). Exit 2: the
robot itself broke. A few checks only warn, in the summary's own list: the
key not going back to what opened a window, Magic search's how-to not
showing, the page's rest flag not set. The controls it never presses, each with its reason, are `SKIP` in
`tools/click_test/steps.py` (links that leave Anki, Listen, Anki's own sync,
hosting a party table, sign out, delete account). No network: the add-on's
requests go to the fake, song search answers from a list, any other
connection is refused and listed.

    python3 -m venv /tmp/ankienv
    /tmp/ankienv/bin/pip install "aqt==25.02.7" "anki==25.02.7" "PyQt6==6.11.0" "PyQt6-WebEngine==6.11.0"
    QT_QPA_PLATFORM=offscreen QTWEBENGINE_DISABLE_SANDBOX=1 \
    QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox --disable-gpu" \
        /tmp/ankienv/bin/python tools/click_test.py --out click-test

About a minute and a half (the minute at rest is most of it). `--quick` is a
dry run (a few presses a view, 30 s at rest); `--only plans,views` runs
those parts after boot (`plans`, `due`, `windows`, `views`, `bars`, `study`,
`energy`); `--views squads,settings` narrows the views. It writes
`click-test/summary.txt` (read this first), `report.json` (every press: where,
what it sent, the handler that ran or none, what raised, what opened, the
timings, CPU) and `shots/` (each view and window, and each failure).
Proven on Linux, as CI runs it; Ubuntu needs the libraries the workflow's
`click` job installs.

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

By area (3.9.12): `python3 tests/test_due_crew.py hook magic` runs only the tests with one of those words in their name, `-q` says only what failed, `--list` names them. CI runs it whole.
| `dialogs` | Every Qt dialog builds under PyQt6 offscreen; the PNGs are attached as an artifact so you can look at them. |
| `click` | The robot click-test above, in real Anki 25.02.7 (PyQt6 6.11); its report and screenshots are the `click-test` artifact, red or green. |

## The speed budget (3.9.9)

`python3 tools/speed_budget.py` (needs `pip install "anki==25.02.7"`) makes a
big collection on Anki's own engine (`tools/speed/make_big.py`: 30,000 notes,
a million answers, 500 decks) and times what a person waits on against a
budget each: a sync's gathering, Insights first and again, Pip Party's tab,
Schedule ahead's read. Over a budget marked `fail` is exit 1; one marked
`warn` is said and passes (Insights' first open of the day, 2 to 4 s against
1.5 s: red once it's met). CI runs it in the click test's job, before the
robot; the first card after Study and CPU at rest stay the robot's.
`--keep DIR` keeps the collection between runs.
