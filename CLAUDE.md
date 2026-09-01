# Due Crew — project context

Consent-based friends leaderboard add-on for Anki. Sam Caplan is the sole
maintainer. The repo is the source of truth; there is no build step.

## Layout

- `due_crew/` — the add-on. `__init__.py` (hooks/glue, main-thread rules in
  its docstring), `board.py` (pure HTML rendering), `backend/` (Firebase
  REST + server directory), `stats/` (local SQL), `ui/` (Qt dialogs).
- `firestore.rules` — deployed to the Firebase project. Friendship consent
  and the crew-server directory are enforced here.
- `README.md` — doubles verbatim as the AnkiWeb listing description; keep
  them in sync when it changes.

## Releasing

1. Bump `due_crew/manifest.json` version.
2. If `firestore.rules` changed: bump the `meta/{marker}` version there AND
   `RULES_MARKER` in `backend/firebase.py`, copy the file to
   `due_crew/firestore.rules` (the in-app rules dialog ships that copy), and
   re-publish in the Firebase console.
3. `cd due_crew && zip -r ../due_crew.ankiaddon . -x "*.DS_Store" -x "user_files/*"`
4. Commit, push, `gh release create vX.Y.Z due_crew.ankiaddon`.
5. Sam updates AnkiWeb by hand: listing 2035408484, update Branch 1 with the
   new file, re-paste README if it changed. The listing can lag releases.

## Rules of the road

- Simplicity is the product rule. Friendship framing, never competition —
  "crew", no "compete/rivals". Copy is terse, no AI-speak.
- Firebase is on the free plan: minimize document reads. The board loads in
  3 requests; don't add polling or per-friend fetches.
- Threading: collection access, config writes, and cache commits on the main
  thread only; all HTTP in background threads with timeouts.
- Escape every server-sourced string before webviews, tooltips, or rich-text
  labels.
- Process: propose features as mockups on the design-spec artifact first
  (ask Sam for the link if needed), build after sign-off.
- Code changes are compile- and logic-tested here; flows still deserve a
  click-test in a live Anki, which only Sam can do.
