# Due Crew — project context

Consent-based friends leaderboard add-on for Anki. Sam Caplan is the sole
maintainer. The repo is the source of truth; there is no build step for the
add-on.

## Layout

- `due_crew/` — the add-on. `__init__.py` (hooks/glue, main-thread rules in
  its docstring), `board.py` (pure HTML rendering), `backend/` (`api.py`,
  the Worker client; `shapes.py`, the pure helpers and payload shapes),
  `stats/` (local SQL), `ui/` (Qt dialogs).
- `worker/` — the server (3.0): one Cloudflare Worker in TypeScript on D1,
  served at `https://api.duecrew.com` (a dev one at `api-dev.duecrew.com`).
  Consent, shapes, sign-in by emailed code, and sessions all live here;
  `worker/README.md` has the API, `migrations/` the schema.
  `docs/cloudflare-setup.md` is the one-time setup (Sam's). Nothing runs on
  Google after the cutover.
  `worker/` and `site/` are PolyForm Shield 1.0.0 (their LICENSE.md) since
  29 Sep 2026: readable and runnable, not for a competing service. The
  add-on, tests and tools stay MIT (root LICENSE).
- `site/` — duecrew.com: the landing page, and the app (`public/app.*`,
  plain JS, no framework: sign-in, plans, the builder). Its Worker
  (`site/src/index.ts`) sends `/api/*` to the API by service binding, so
  the site's session is a same-site HttpOnly cookie, and draws a plan
  link's preview (`site/src/og.ts`).
- `firestore.rules` and `tests/rules/` — the 2.x backend, still live for 2.x
  clients until the cutover, then read-only, then gone with the Firebase
  project (anki-leaderboard-f6691). Delete both, the rules CI job and
  `firebase.json` when it goes.
- `README.md` — from the tagline down, doubles verbatim as the AnkiWeb
  listing description; keep them in sync when it changes. The logo block
  above the tagline is GitHub-only (AnkiWeb shows its own title).
  Its images live in `docs/images/` and are linked by full
  raw.githubusercontent.com URLs on `main`, so the same text works on
  AnkiWeb. They're renders of the add-on's own board, overlays and room
  widget (sample crew), not mockups; re-render them when those change.
- `docs/logo/` — the logo ("Seven days"), final artwork: never redraw or
  re-typeset it. Green on GitHub; inside the add-on, `due_crew/logo.py`
  colours the studied days with the user's accent: the board's title is
  the one-line logo (inline SVG on the `--dc-*` tokens), and the stacked
  one tops the sign-in and welcome screens.
- `tests/` — `python3 tests/test_due_crew.py` (client behavior against
  `fakes.FakeWorker`, a Python restatement of the Worker; standard library
  only). `worker/test/` is the Worker itself in real workerd with D1
  (`cd worker && npx vitest run`); `consent.test.ts` there is the consent
  model, restating every check of the old rules test. See
  `tests/README.md`. `docs/manual-anki-checklist.md` is the click-test.
- `.github/workflows/tests.yml` runs on every push: pyflakes, the suite,
  the offscreen dialog build, the Worker (typecheck + vitest), and, until
  the cutover, the Firestore rules in the emulator. Green on all of them is
  the release gate. pyflakes is the only thing that reads most of the glue,
  which the suite never imports. A `v*` tag also deploys the Worker, after
  every job is green.

## How the data moves (the invariants)

Every feature's full notes, with the why, are in `docs/history.md`, by
version. Read a feature's entry there before changing it (search for its
module, its `duecrew:` command or its mock's name). These hold everything up:

- A refresh is one request (`GET /board`: me, my crew, cheers, knocks; on
  the day's first, `decks=1`, shared decks, plans, squads and the bingo
  card), and a sync is one (`POST /sync`: profile, my week, decks, heatmap,
  squad rows, plan progress, plan squad days). The server writes only what
  changed. `test_request_budget` pins this: a change there is a change in
  what the add-on costs, and must be deliberate. A new feature rides one
  of the two, or is one request on a click.
- My week is the one shape for day stats (last eight days, away spell,
  exam, paused, `liveUntil`, flags, room, recap). The client rebuilds it
  from `session.week_raw` with the current Privacy switches at every sync,
  so turning a switch off takes that number off every day.
- Consent: friendship is two edges (`friends(owner, friend)`); only mutual
  friends read my week, decks and heatmap; a cheer lands only if its
  recipient added the sender; a knock needs a squad in common or my code.
  Someone connected to me gets a name and an emoji, nothing more; a
  stranger's uid gets the same 404 as no account.
  `worker/test/consent.test.ts` is the model.
- A squad row is an UPDATE, never an insert; the join (with its code) is
  the only way in.
- Card text never leaves the computer: flags, asks, knows, plan picks and
  plan squad questions carry a note guid and card number, and each reader's Anki
  reads its own copy.
- Settings that belong to a person (`account.ACCOUNT_KEYS`) live on the
  server; an install pulls before it uploads (`account.ensure()`), and the
  newest save wins. Theme, sort, tab, hidden tabs and the room chip's side
  stay per computer.
- Plans: the plan says what and by when; my follow (shift, skips, moves,
  pause, catch-up) says when for me (`plan_flow.mine` → `plans.my_doc`),
  and never changes the plan. The morning opens what's due once per Anki
  day, after the AnkiWeb sync, in one undo step. A plan never suspends on
  its own (Hold back is the one suspend, and only when asked), a date that
  opened never closes again, and a leech never opens. Plan state is per
  profile (`user_files/<profile>/plans.json`), never the shared config:
  deck ids belong to one collection. `plans.py` is pure, `plan_flow.py`
  the glue.
- Mine alone, never sent: Insights, my progress on each bingo square,
  checkpoint scores, `wrap.json`. A plan's squad (its team on the server) shares only
  that I showed up, my questions and answers, and bingo stamps; never a
  number, never weak spots.
- Days are the person's Anki day (their rollover), on both sides (`ankiDay`
  in the Worker).
- Background jobs capture `app.generation` (bumped at profile open/close,
  sign-in/out) and drop their commit when it changed.
- The 2.x backend (Firestore, `worker/src/bridge.ts`, `firestore.rules`,
  `tests/rules/`) lives until the cutover ends; then all of it goes, with
  its cron, the `FIREBASE_SA` secret, the rules CI job and `firebase.json`.

## Twins: change one, change both

Logic that runs in two places, restated by hand. Change both sides in the
same commit, each with its test:

- `board.build_rows` and the board ↔ `Board` in `site/public/app.js` (rows,
  chip order, notes, show-up view, Decks, Squads, bingo mini card)
- `schedule.py` ↔ `Sched` in app.js (a date's window, quota, behind)
- `bingo.evaluate` ↔ `evaluate` in `worker/src/bingo.ts`
- `due.parse` ↔ `board.DUE_JS` (the add box's preview)
- `due.line_keys` ↔ `dueLineKeys` in app.js
- `board.face` ↔ `face` in `site/public/builder.js`
- `team.bingo_line` ↔ `bingoLine` in builder.js (`PlanSquad`)
- `board._plan_squad_html` ↔ `PlanSquad.view` in builder.js (a plan's squad)
- `room_model.phase` ↔ the room widget's JS
- the Worker ↔ `tests/fakes.FakeWorker` (the suite's server)

## Where things live

| Feature | Add-on | Worker, site |
|---|---|---|
| Crew board, Today/Week tabs | `board.py`, `__init__.py`, `backend/api.py`, `stats/` | `board.ts`, `social.ts`; `Board` in app.js |
| Cheers, status, profile card | `social.py`, `wrap.py` | `social.ts` |
| Settings | `settings_model.py`, `account.py`, `board.settings_html`, `ui/settings_dialog.py` | `GET/PUT /settings` |
| Squads, knocks, bingo | `squads.py`, `bingo.py`, `bingo_flow.py` | `squads.ts`, `bingo.ts`, `adminsquads.ts` |
| Who knows this, asks, tips | `cards.py`, `together.py` | `cards.ts` |
| Study rooms | `rooms.py`, `room_model.py` | rides my week |
| Plans (follow, morning, week, load) | `plans.py`, `schedule.py`, `plan_flow.py` | `plans.ts`, `library.ts`; `builder.js`, app.js |
| A plan's squad (3.8.0, on the Squads tab; its team on the server) and Insights | `team.py`, `team_flow.py` | `team.ts`; `PlanSquad` in builder.js |
| Due | `due.py`, `due_flow.py`, `board._due_html` | settings doc |
| Invites, codes | `__init__.py`, `ui/friends_dialog.py`, `ui/welcome_dialog.py` | `invites.ts`, `social.ts` |
| Sign-in, sessions, quiet accounts | `ui/auth_dialog.py`, `backend/api.py` | `auth.ts`, `quiet.ts`, `mydata.ts` |
| Shares: text, and picture cards | `share.py`, `shares.py` | `site/public/cards.js` |
| Admin, notices, feedback | | `admin.ts`, `people.ts`, `notices.ts`, `feedback.ts` |
| Previews of a plan or invite link | | `site/src/og.ts` |

## Releasing

1. Bump `due_crew/manifest.json` version, and add the release's bullet to
   `docs/history.md` (what changed, where, why).
2. If the Worker changed in a way an older client depends on, deploy it
   first (the tag does), and raise `MIN_CLIENT` in `worker/wrangler.toml`
   only when older clients must stop (they show "server catching up"). A
   new D1 migration goes in `worker/migrations/`, numbered; the deploy job
   applies it before the Worker. Never edit a migration that has shipped.
3. `cd due_crew && zip -r ../due_crew.ankiaddon . -x "*.DS_Store" -x "user_files/*"`
   `manifest.json`'s `package` is `2035408484`, AnkiWeb's folder name, so a
   file installed by hand replaces the AnkiWeb copy (and keeps its
   user_files) instead of running beside it.
4. Commit, push, wait for the Actions run: every job green is the release
   gate — no zip goes out on a red run. Then tag and
   `gh release create vX.Y.Z due_crew.ankiaddon`; the tag deploys the
   Worker.
5. Sam updates AnkiWeb by hand: listing 2035408484, update Branch 1 with the
   new file, re-paste README if it changed. The listing can lag releases.

`tools/release.sh` does 3–4 from a clean `main` (`--tag` tags and pushes);
`tools/check_prod.sh` checks the live API and site after the deploy
(no sign-in, no mail). The tags' deploy job stands down until the GitHub
secrets exist, so production is deployed by hand from `worker/`: the
migrations, the API, then the site (`docs/go-live.md`, 2b).

## Rules of the road

- Simplicity is the product rule. Friendship framing, never competition —
  "crew", no "compete/rivals". Copy is terse, no AI-speak.
- Requests, not reads, are the budget now: a refresh is one request and a
  sync is one. Don't add polling, per-friend requests, or unbounded
  queries. D1 writes cost more than reads: the server compares before it
  writes, and `last_used`/`last_seen` are written at most daily/hourly.
- Never store or return card text. No ranking anywhere new.
- Code, comments and test data name no third-party deck, question bank
  or video series (trademarks): "a big shared deck", "Big Step 1".
- Threading: collection access, config writes, and cache commits on the main
  thread only; all HTTP in background threads with timeouts.
- Anything meant as an update must never create (a row is not a join), and
  anything guarding a join must demand what only a join sends.
- When testing a permission, test it in the state users are actually in.
  The 2.3 removal test locked the squad first, which hid the bug above.
- Escape every server-sourced string before webviews, tooltips, or rich-text
  labels.
- The board lives in Anki's Decks screen, which sits in a `<center>` and
  styles every button (margin, shadow, rounded corners). The board's older
  parts are centred by it on purpose; a new part sets `text-align: left`
  itself, and buttons start from the reset in `_css`. `tools/preview.py`
  renders inside the same `<center>` and button style: look at a new part
  there (light, dark, narrow) before calling it done.
- Every `duecrew:` command a page emits needs a handler
  (`test_every_board_command_has_a_handler`), and a new one gets a test
  that sends it through `_on_js` as the board does (3.5.0's Settings went
  out with its clicks reaching nothing). Anything a click adds has its way
  back on the same screen.
- A card's own script runs on the review screen, in the browser's preview
  and in Cards…, and a deck's description runs on Overview: from any page
  but the ones Due Crew draws on (Decks, the top bar, the reviewer's bottom
  bar: `_our_page`) only the widgets' keyed commands in
  `room_model.CARD_PAGE_CMDS` are taken
  (`room_model.trusted`); anything that acts for me elsewhere comes from
  the board, the bars or a dialog.
- A failed request is sent again only when twice can't do a thing twice
  (`api._call`: reads, PUT/PATCH/DELETE, a sync, one that never got out).
  What a person or a request adds on the server has a ceiling.
- Never log emails, codes or tokens (the Worker, and the client's prints).
- Process: propose features as mockups on the design-spec artifact first
  (ask Sam for the link if needed), build after sign-off. Ask Sam before
  changing anything users see.
- Before a release, `tools/real_anki.py` runs the plan code on Anki's own
  engine with an AnKing-sized collection (searches, suspend and undo,
  deck limits, filtered decks, timings); `pip install anki` in a venv.
- Code changes are compile- and logic-tested here; anything under
  `due_crew/ui/` also gets `tools/dialogs.py` (offscreen PyQt6 render of
  every dialog, see tests/README.md); flows still deserve a click-test in
  a live Anki, which only Sam can do.
