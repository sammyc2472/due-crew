# Due Crew — project context

Consent-based friends leaderboard add-on for Anki. Sam Caplan is the sole
maintainer. The repo is the source of truth; there is no build step.

## Layout

- `due_crew/` — the add-on. `__init__.py` (hooks/glue, main-thread rules in
  its docstring), `board.py` (pure HTML rendering), `backend/` (Firebase
  REST + server directory), `stats/` (local SQL), `ui/` (Qt dialogs).
- `firestore.rules` — deployed to the one hosted Firebase project
  (anki-leaderboard-f6691; Sam pays past the free tier). Friendship consent
  and squads (private boards behind an invite code) are enforced here. v2.0 removed crew
  servers, the directory, and custom projects — nobody but Sam ever used
  them.
- `README.md` — doubles verbatim as the AnkiWeb listing description; keep
  them in sync when it changes.
- `tests/` — `python3 tests/test_due_crew.py` (client behavior against a
  fake Firestore; standard library only) and `tests/rules/` (the real
  rules, in the Firestore emulator — needs firebase-tools + Java). See
  `tests/README.md`. `docs/manual-anki-checklist.md` is the click-test.
- `.github/workflows/tests.yml` runs four jobs on every push: pyflakes,
  the suite, the offscreen dialog build, and the rules in the emulator.
  Green on all four is the release gate. The rules job is the only place
  the deployed rules text is ever proven; pyflakes is the only thing that
  reads most of the glue, which the suite never imports.
- Friendship data lives twice during the 2.5 changeover: the profile's
  `friends` array (what clients up to 2.4 read) and edge docs
  `users/{me}/friends/{fid}` (what 2.5+ reads for add-backs, and what the
  rules honour). A later release stops writing the array once the crew
  is on 2.5+ (check `clientVersion` on their profiles first).
- Day stats live twice during the 2.9 changeover: `daily_stats/{label}`
  docs (what clients up to 2.8 read) and `shared/week`, a person's last
  eight days in one doc (what 2.9+ reads for a friend whose profile says
  2.9+, falling back to day docs when it's missing). The same later
  release stops writing day docs, `sync_away`'s future-day docs, and the
  profile's crew-only fields (`examDate`, `paused`, `tz`, `rollover`),
  which the week doc already carries. Profiles are readable by any
  signed-in user with the uid (squadmates have it), so that step is also
  a privacy fix; the README says so until then.
- 2.10's together features add no reads: "studying now" (`liveUntil`) and
  flagged cards (`tricky`) ride the week doc; good-luck lines (`luck`) and
  card tips (`guid`) ride cheers (rules-v10), and on arrival they're kept
  in wrap.json (`luck`, `tips`), not played. A flag shows at most the first
  60 characters of the card's first field, clozes as […], and only to
  crewmates whose collection has the same note guid.
- "Week" is the calendar week, Monday to Sunday (`board.week_labels`).
  The squad board's "7 days" column is the one rolling count, and is
  labelled as such. Crew totals accrue through the per-day ledger in
  wrap.json: a day is added to the all-time total exactly once, when it
  leaves the seven-day window. Never accrue from a rolling sum.

## Releasing

1. Bump `due_crew/manifest.json` version.
2. If `firestore.rules` changed: add the new `meta/{marker}` version there
   (the list is cumulative — older clients keep probing older markers) AND
   bump `RULES_MARKER` in `backend/firebase.py`, run the emulator rules
   test, and re-publish in the Firebase console
   BEFORE the add-on release (users can't fix rules; the footer shows
   "server catching up" until the paste lands). A rules change that closes
   a path older clients use (v2.0 closed `server_board` and the directory)
   is a breaking change: say so in the release notes. A removal-only
   change (dropping a retired path) or a tightening no shipped client
   trips (bounds, `get` instead of `read`) needs no marker bump: no
   client depends on it — but it still needs the console paste.
3. `cd due_crew && zip -r ../due_crew.ankiaddon . -x "*.DS_Store" -x "user_files/*"`
4. Commit, push, wait for the Actions run: all four jobs green (lint,
   suite, dialogs, rules in the emulator) is the release gate — no zip
   goes out on a red run. Then `gh release create vX.Y.Z due_crew.ankiaddon`.
5. Sam updates AnkiWeb by hand: listing 2035408484, update Branch 1 with the
   new file, re-paste README if it changed. The listing can lag releases.

## Rules of the road

- Simplicity is the product rule. Friendship framing, never competition —
  "crew", no "compete/rivals". Copy is terse, no AI-speak.
- Firebase reads cost money at scale: minimize document reads. A light
  refresh is one doc per friend (their week doc) plus the cheers list;
  knocks are listed on the day's first fetch, on Refresh, on the Squads
  tab, and at most hourly otherwise. Profiles are read once a day, and my
  own row comes from my own uploads (`session.own_days`). A squad board
  is one get plus one query, a read per member, fetched lazily. Every
  friend read also costs a rules read (`isFriend()`'s `exists()`), billed
  like a document: `test_reads_diet` and `test_week_doc_v29` count both
  and pin them; changing a number there is changing what the add-on costs
  per user, and must be deliberate. Don't add polling, per-friend
  fetches, or unbounded queries.
- A multi-document read gets 20 rules access calls, and `isFriend()`
  spends one per friend (two without an edge doc); past that the whole
  batch is refused. Batches of friends' docs go through
  `batch_get_people`, ten friends at a time. Measured in the emulator.
- Threading: collection access, config writes, and cache commits on the main
  thread only; all HTTP in background threads with timeouts.
- A PATCH to a missing Firestore doc is an INSERT. Any write meant as an
  update must say so (`must_exist=True`), and any rule guarding a "join"
  must demand something only a real join sends. This bit squads for six
  releases: Remove undid itself because a row sync re-created the member.
- When testing a permission, test it in the state users are actually in.
  The 2.3 removal test locked the squad first, which hid the bug above.
- Escape every server-sourced string before webviews, tooltips, or rich-text
  labels.
- Process: propose features as mockups on the design-spec artifact first
  (ask Sam for the link if needed), build after sign-off.
- Code changes are compile- and logic-tested here; anything under
  `due_crew/ui/` also gets `tools/dialogs.py` (offscreen PyQt6 render of
  every dialog, see tests/README.md); flows still deserve a click-test in
  a live Anki, which only Sam can do.
