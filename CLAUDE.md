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

## How the data moves (3.0)

- A refresh is one request: `GET /board` returns me, my crew (the people I
  added, each with their week when they added me back, name and emoji only
  when not yet), my cheers (deleted as they're read), my knocks, and shared
  decks on the day's first refresh. A sync is one request: `POST /sync`
  with my profile, my week, decks, heatmap and squad row. The server writes
  only what changed. `test_request_budget` pins this: a change there is a
  change in what the add-on costs, and must be deliberate.
- My week (2.9's week doc) is the one shape for day stats: my last eight
  days, the away spell as a range (readers flag the days inside it), exam
  date, paused, `liveUntil`, flagged cards and my room. The client builds
  it from `session.week_raw` (the numbers it counted) with the current
  Privacy switches every time, so turning a switch off takes that number
  off every day at the next sync, light or full.
- A flagged card (`tricky`) leaves this computer as its note guid, deck and
  day, never its text; a crewmate's client reads the text from its own
  copy of the note (`together.tricky_view`), so it shows only to crewmates
  who have the same note. At most the first 60 characters, clozes as […].
- Friendship is two edges, one per person (`friends(owner, friend)`).
  Mutual = both exist. Only mutual friends read my week, decks and heatmap;
  a cheer lands only if its recipient added the sender; a knock needs a
  squad in common or comes from adding the recipient's code. Anyone signed
  in gets a name and an emoji for a uid, nothing more.
- A squad row is an UPDATE on the server, never an insert; the join
  (`POST /squads/{id}/join`) is the only way in. That is what keeps Remove
  removed (the 2.3–2.5 bug: a row sync re-created the member).
- Cutover from 2.x: no data is migrated. Sam imports the Firebase accounts
  (`tools/import_users.py`), so a first 3.0 sign-in lands on the old uid.
  That client's first sync then brings back what this computer knew
  (`ApiClient.restore_from_2x`): its code (when `session.friend_code` has
  it), its crew by uid (`session.friend_ids`), its squads by their codes
  (config), with ids unchanged. Friendships re-form as each side updates.
- 2.10's together features: "studying now" and flags ride my week;
  good-luck lines (`luck`) and card tips (`guid`) ride cheers, and on
  arrival they're kept in wrap.json (`luck`, `tips`), not played.
- 2.12's study rooms: a room is `{host, start, rounds, round, brk}` on my
  week (`room`), joining copies it to mine, and every screen computes the
  clock from `start` (`room_model.phase`, and the same arithmetic in its
  JS). Nothing is ever drawn inside a card: while reviewing, the room goes
  in Anki's top bar (A), else beside Edit in the bottom bar (B), else a
  margin card that shows only while the card leaves the margin free (C).
  The one exception is the break, which replaces the next card and turns
  the review shortcuts off until it ends or is skipped. Under the break,
  answer messages are dropped, the card's audio stops, and its timer
  restarts when the break ends. Each break costs one refresh, once per
  round, only while reviewing: that is how the chip learns who joined.
  Closing Anki leaves the room.
- 2.13: settings that belong to a person (`account.ACCOUNT_KEYS`: privacy
  switches, show-up, paused, exam and away dates, status, emoji, squads,
  crew label, shared decks by id and name) live on the server
  (`GET/PUT /settings`), mine only. Accent, theme, sort and tab stay per
  computer. An install pulls before it uploads: `_on_sync_done` waits for
  `account.ensure()` at profile open, sign-in and the day's first sync, so
  a new computer never sends defaults over the account's. Newest save
  wins. `app.save_cfg` pushes when an account key changes. An install that
  has never set a deck list (and couldn't pull one) doesn't upload an
  empty one.
- 2.13 also says how many reviews were new cards (`newCards`): a card
  whose first answer ever was that day (`StatsQueries.new_cards_by_day`,
  an index probe per answer, no full-revlog scan); relearned and
  Forget-reset cards are reviews. It rides my week and squad rows under
  the Reviews switch (`METRICS`). Shown under Reviews, on the profile card,
  in Share today and week. Sorting is unchanged.
- "Week" is the calendar week, Monday to Sunday (`board.week_labels`).
  The squad board's "7 days" column is the one rolling count, and is
  labelled as such. Crew totals accrue through the per-day ledger in
  wrap.json: a day is added to the all-time total exactly once, when it
  leaves the seven-day window. Never accrue from a rolling sum.

## Releasing

1. Bump `due_crew/manifest.json` version.
2. If the Worker changed in a way an older client depends on, deploy it
   first (the tag does), and raise `MIN_CLIENT` in `worker/wrangler.toml`
   only when older clients must stop (they show "server catching up"). A
   new D1 migration goes in `worker/migrations/`, numbered; the deploy job
   applies it before the Worker. Never edit a migration that has shipped.
3. `cd due_crew && zip -r ../due_crew.ankiaddon . -x "*.DS_Store" -x "user_files/*"`
4. Commit, push, wait for the Actions run: every job green is the release
   gate — no zip goes out on a red run. Then tag and
   `gh release create vX.Y.Z due_crew.ankiaddon`; the tag deploys the
   Worker.
5. Sam updates AnkiWeb by hand: listing 2035408484, update Branch 1 with the
   new file, re-paste README if it changed. The listing can lag releases.

## Rules of the road

- Simplicity is the product rule. Friendship framing, never competition —
  "crew", no "compete/rivals". Copy is terse, no AI-speak.
- Requests, not reads, are the budget now: a refresh is one request and a
  sync is one. Don't add polling, per-friend requests, or unbounded
  queries. D1 writes cost more than reads: the server compares before it
  writes, and `last_used`/`last_seen` are written at most daily/hourly.
- Never store or return card text. No ranking anywhere new.
- Threading: collection access, config writes, and cache commits on the main
  thread only; all HTTP in background threads with timeouts.
- Anything meant as an update must never create (a row is not a join), and
  anything guarding a join must demand what only a join sends.
- When testing a permission, test it in the state users are actually in.
  The 2.3 removal test locked the squad first, which hid the bug above.
- Escape every server-sourced string before webviews, tooltips, or rich-text
  labels.
- Never log emails, codes or tokens (the Worker, and the client's prints).
- Process: propose features as mockups on the design-spec artifact first
  (ask Sam for the link if needed), build after sign-off. Ask Sam before
  changing anything users see.
- Code changes are compile- and logic-tested here; anything under
  `due_crew/ui/` also gets `tools/dialogs.py` (offscreen PyQt6 render of
  every dialog, see tests/README.md); flows still deserve a click-test in
  a live Anki, which only Sam can do.
