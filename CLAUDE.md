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
- `.github/workflows/tests.yml` runs all three on every push: the suite,
  the offscreen dialog build, and the rules in the emulator. Green on all
  three is the release gate; the rules job is the only place the deployed
  rules text is ever proven.
- Friendship data lives twice during the 2.5 changeover: the profile's
  `friends` array (what clients up to 2.4 read) and edge docs
  `users/{me}/friends/{fid}` (what 2.5+ reads for add-backs, and what the
  rules honour). 2.6 stops writing the array once the crew is on 2.5.

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
4. Commit, push, wait for the Actions run: all three jobs green (suite,
   dialogs, rules in the emulator) is the release gate — no zip goes out
   on a red run. Then `gh release create vX.Y.Z due_crew.ankiaddon`.
5. Sam updates AnkiWeb by hand: listing 2035408484, update Branch 1 with the
   new file, re-paste README if it changed. The listing can lag releases.

## Rules of the road

- Simplicity is the product rule. Friendship framing, never competition —
  "crew", no "compete/rivals". Copy is terse, no AI-speak.
- Firebase reads cost money at scale: minimize document reads. The crew
  board loads in 4 requests (profiles, stats, cheers, knocks); a squad
  board is one get plus one query, a read per member, fetched lazily. Don't add polling, per-friend
  fetches, or unbounded queries.
- Threading: collection access, config writes, and cache commits on the main
  thread only; all HTTP in background threads with timeouts.
- Escape every server-sourced string before webviews, tooltips, or rich-text
  labels.
- Process: propose features as mockups on the design-spec artifact first
  (ask Sam for the link if needed), build after sign-off.
- Code changes are compile- and logic-tested here; anything under
  `due_crew/ui/` also gets `tools/dialogs.py` (offscreen PyQt6 render of
  every dialog, see tests/README.md); flows still deserve a click-test in
  a live Anki, which only Sam can do.
