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
- 3.0.1 mute is the client's: a muted person's cheers and knocks are
  dropped on arrival, nobody is told, and you stay friends. `POST /reports`
  stores nothing; it mails REPORT_TO (never the reporter's email).
- Friendship is two edges, one per person (`friends(owner, friend)`).
  Mutual = both exist. Only mutual friends read my week, decks and heatmap;
  a cheer lands only if its recipient added the sender; a knock needs a
  squad in common or comes from adding the recipient's code. Someone
  connected to me (a crew edge or a knock either way, a squad or a plan in
  common) gets a name and an emoji for my uid, nothing more (3.7.1, D5);
  codes and invites carry their own names.
- A squad row is an UPDATE on the server, never an insert; the join
  (`POST /squads/{id}/join {code}`, the code required since 3.6.2, with
  `MIN_CLIENT` 3.1.0) is the only way in. That is what keeps Remove
  removed (the 2.3–2.5 bug: a row sync re-created the member).
- Cutover from 2.x: no data is migrated. Sam imports the Firebase accounts
  (`tools/import_users.py`), so a first 3.0 sign-in lands on the old uid.
  That client's first sync then brings back what this computer knew
  (`ApiClient.restore_from_2x`): its code (when `session.friend_code` has
  it), its crew by uid (`session.friend_ids`), its squads by their codes
  (config), with ids unchanged. Friendships re-form as each side updates.
  Only an imported account restores (`users.from2x`, migration 0018: the
  import sets it, the first 3.x sync clears it); the client version alone
  was anyone's to set.
- The 2.x bridge (`worker/src/bridge.ts`, every 15 minutes, only with the
  `FIREBASE_SA` secret): for people still on 2.x, Firestore is the truth
  and their week, name and emoji, shared decks, heatmap and squad rows
  come into D1; for people on 3.x, D1 is the truth and the same go out to
  Firestore (no flags). Squad rows are updates only both ways: the bridge
  never makes anyone a member. Cheers, knocks and memberships don't cross.
  It reads only people a 3.x screen can show (3.x users, and 2.x people a
  3.x user added or shares a squad with). A 3.x person's Firestore friend
  edges are kept to their D1 mutual friends, so a removal also ends 2.x
  reads, and deleting an account deletes its 2.x copies.
  `tools/bridge_check.py` compares both sides. Delete it all, its cron and
  the secret with Firestore.
- 2.10's together features: "studying now" and flags ride my week;
  good-luck lines (`luck`) and card tips (`guid`) ride cheers, and on
  arrival they're kept in wrap.json (`luck`, `tips`), not played.
  3.0.1: the first tip on a flag takes it down for the whole crew: the
  Worker drops that guid from the recipient's week when the tip is stored,
  and a sync drops a flag whose tip is still unread; on arrival the client
  drops it from `session.tricky`, so it stays down.
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
  crew label, shared decks by id and name, muted uids, and since 3.5.0 the
  accent, which `/auth/me` hands the site to wear) live on the server
  (`GET/PUT /settings`), mine only. Theme, sort, tab and the room chip's
  side stay per computer. An install pulls before it uploads:
  `_on_sync_done` waits for `account.ensure()` at profile open, sign-in and the day's first sync, so
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
- 3.1 plans (`docs/plans-design.md`): a plan is dates (units) of tags,
  subdecks and single cards (`[note guid, card ord]`) for one deck. The
  plans I follow and squad offers ride the day's first `GET /board`
  (`decks=1`) and are cached in the session; progress per unit
  (`[opened, seen, total]`, only for plans I share it on) rides `POST
  /sync` when it changed (`plans_hash`). Follow, pause, stop, the deck's
  tree, the site link and adding cards are one request each, on a click.
  `plans.py` is pure (matching, progress, the undo step); `plan_flow.py`
  is the glue: per-profile state in `user_files/<profile>/plans.json`
  (`plans`, `plans_day`, `plans_opened`, `plan_offers_dismissed`; deck
  ids belong to one collection, so never the shared add-on config; 3.1.1
  moved them out of it once), and the morning, once per Anki day
  (`plans_day`) after the day's AnkiWeb sync, or at the first refresh
  when the profile doesn't sync (a fallback three minutes after opening),
  never while Anki closes; the day's fresh plans get one more look: due
  units' suspended cards open in one undo step. A plan first seen here
  (followed elsewhere) opens today's unit only. A unit the author changes
  opens only what its new sources add (`src`, what it matched with when
  applied); a leech never opens. A plan never suspends anything: not on
  stop, not when a unit goes or a date moves later. Background jobs
  capture `app.generation` (bumped at profile open/close, sign-in/out)
  and drop their commit when it changed.

- 3.2 plans as training (`docs/plans-design.md`, "3.2"): the plan says
  what and by when; my schedule (`sched` on my follow: days, a double
  share or a rest day each, minutes a day, a later start) says when.
  `schedule.py` is pure: a date's window, catch-up weeks and the taper
  (`phases`, nothing new opens), today's quota, what I'm behind, the load
  ahead. The morning opens up to today's quota in the deck's order and
  never more; the same arithmetic runs on the site (`Sched` in app.js):
  change one, change both. Missed study days ask once on the plan card
  (spread, push my dates back, leave open); a checkpoint's morning builds
  Anki's own filtered deck, and its score stays on this computer. The
  recap rides my week (`recap`). My log rides a full sync (`log`, 120 days
  once, then 8), read only by me on the site.
- 3.2 who knows this one (`cards.py`): no switch. In the decks I share,
  a card I have down (review, 21+ days, no Again in 30) goes up as its
  guid (`knows`, as changes, `known.json` beside the session); the cards
  I'm stuck on (2+ lapses, or Again today) ride every sync (`stuck`) and
  come back with who knows each and their tips (`cards` in the session).
  The chip is beside Edit on the answer side, never inside a card: who
  knows it (Ask: a flag with my line, `q`), a tip (This helped), or a
  crewmate's ask (Tip). A tip with words stays on its card (`tips`).
  3.5.0 (mock "Card Help Flow"): the chip shows a tip's own words (its
  first tip, one per person, "+N more" opens the rest) with This helped
  as its own click (`knowshelped`); asking is one thing, "ask my crew
  about this…" from the chip or the reviewer's menu on any card, a line
  optional; the Decks tab heads "Asked of you" and "Your asks" (open
  ones say who has the card down, answered ones who answered), from
  local data only (`together.my_asks_view`).
- 3.2 the site: signed in, `/` goes to `/home` (`GET /board?keep=1`,
  which leaves the cheers for Anki); `/log`; `/admin` for the admin.
- 3.2.1 the admin's notice: the admin is Sam's "sammy" account (`ADMINS`
  in wrangler.toml, plus the optional `ADMIN_UIDS` secret). From `/admin`
  Sam posts one line (a link optional, only to add-ons older than a
  version optional, for N days); `GET /board` carries the newest live one
  for the asking add-on's version (`notices`, migration 0005), and the
  board shows it on top of every tab until it's dismissed (by id, in
  wrap.json). Only 3.2.1 and later show it.
- 3.3 the builder is a calendar (`site/public/builder.js`, loaded before
  app.js): tags named readably with the raw tag under (`Tags`), by
  resource / by system / other, ticked into what the plan covers; the pace
  (finish by, cards a day, or day by day, and the plan's study days) and
  Lay it out / Plan next week put it on days. A date can be split evenly
  over its window (`even` on a unit): everyone gets the same slices on the
  plan's study days (`pace.days`), with or without a schedule of their own
  (`schedule.quota`; `Sched.quota` the same). `pace` is otherwise the
  builder's (`mode`, `daily`, `cover`); an add-on keeps only its days, and
  3.2.x add-ons open an even date whole. As text carries a prompt for the
  person's own AI (tag names and counts, never a card) and reads its
  answer back with a preview. The site home is the add-on's board.
- 3.3 following is simpler: a follower does each date on its day (the
  plan's study days, `schedule.weight` falls back to `pace.days`); the
  add-on no longer asks for a schedule, and a 3.2 `sched` still runs. The
  add-on's board has a Plans tab (the cards left Decks). The tree goes up nested (`plans.nest`, up to 1.5 MB, question
  ids last), so deep tags reach the builder.
- 3.3 hold back (Sam's call): a deck imported with every card active
  can't wait for its days, so Follow offers (checked) "Hold back N cards
  of later dates until their day": the never-studied new cards of dates
  not yet open, suspended once in one undo step and kept in `held`;
  stopping opens them again. The only suspend, and only when asked; a
  plan still never suspends on its own. The whole deck is coverable
  (a deck with no tags or subdecks), and a new plan goes straight from
  Anki to its calendar at 20 new cards a day.
- 3.3 a class through Step (C1–C5, mock "A class through Step"):
  C1 the plan card says when Anki's new cards/day is below today's plan
  (Raise: the deck's own limit, which Anki can undo; no other deck changes). C2 `early` on my follow
  (0–7 days): the morning looks that far ahead, for studying on a phone.
  C3 a date's `search` (Anki searches, run in each follower's Anki, kept
  to the plan's deck; `sn` the count when added from the browser); a plan
  holds 50,000 single cards. C4 Study on a date's row (its filtered deck)
  and review days (`reviews: [{day, from, to}]`, replacing checkpoints on
  the site). C5 `ids` on a date: the author's Anki sends the note ids
  behind its tags (`PUT /plans/{id}/ids`, one request a plan when they
  changed, on the day's first refresh; `authored` rides that board); a
  follower whose tag matches nothing falls back to them.
- 3.4: a pasted search's count comes from an author's Anki with the
  note-id request (`counts`), and `/p/CODE.ics` is the plan as a calendar
  to subscribe to (no sign-in, code plans only, nobody's name).
- 3.3 plans together (migration 0006): co-authors from the owner's crew
  (`plan_editors`; they edit, the owner alone deletes, picks the audience
  and the co-authors), notes on a day from anyone in the plan
  (`plan_notes`), and the history (`plan_log`, the last 30 saves with who,
  a summary the site writes, and what each replaced; the latest undoes).
  Save-based: a save that meets another merges onto it in the page
  (`merge` in builder.js). `/plans/{id}` is the one plan page: the authors
  edit, a follower sees the calendar and the notes.
- 3.4 the UI review (`docs/ui-review.md`, mocks on "Due Crew UI Review"):
  a row carries at most one chip (studying now > exam > back > away,
  coloured), headings are words (icons only when narrow), the ago text
  only on quiet rows, new cards only on the Week tab; banners show one at
  a time; the footer is Crew ▾ plus Refresh and Settings; one person's
  board is an invite card with a code box. The site's "Got a code?" box
  (home, Plans) looks a code up first (`GET /codes/{code}`, `GET
  /plans/public`) and says what it is: add a friend, follow a plan, join
  a squad (a squad goes into the settings doc, so Anki shows it next
  open). A plan's link shows the plan signed out (`/plans/public`), and a
  phone can email itself the link (`POST /links/email`, fixed text). The
  "last active" switch is gone.
- The builder, calmer (mock "Builder, calmer"): one side panel with two
  tabs (What to cover, the picked day), so never three columns; the pace
  is one line with a menu; one fill button named for the pace (none when
  placing by hand); Share holds the code, Add to calendar and co-authors;
  the plan as text is a view (Text), not a tab; Save is a pill only while
  something's unsaved (⌘S). The calendar sits in its own card. A plan is
  one deck and everything under it: two decks go under one parent.
- E1 cards by ID: a date's `nids` (note ids: all their cards) and `cids`
  (card ids: that card), pasted in the day's Add cards box or `nids:` in
  Text; up to 5,000 each a date, inside the plan's 50,000 single cards.
  Each follower's Anki finds them inside the plan's deck
  (`DeckIndex.id_cards`); the author's Anki counts them (`"#ids"` in the
  counts, kept as `idn`). Numbers only. Not C5's `ids`, which are guids.
  E2 print: a Print view (authors and followers) lays the dates out as a
  list by week, topics grouped by resource, for printing or a PDF.
- F1 events: `events: [{id, day, name}]` on the plan (a lecture, a quiz,
  the exam; they open nothing), and a date's `for` names the one it preps
  for (a `for` whose event went is dropped by the Worker). The calendar
  marks the event ("3 days of prep") and its prep days; Fill can aim at an
  event (finish the day before; the new dates are for it); Text writes
  `DATE | event | Name` and `for Name`; the calendar feed and the print
  show them; the add-on's plan card says what today preps for
  (`plans.prep_for`).
- G1-G7 a follower's own days (migration 0007): `shift` (my dates run
  that many days later), a pause's `since`/`until`, and `skipped` (dates
  that never open for me) live on my follow (`PATCH /plans/{id}/follow`),
  mine only; the plan never changes and events never move.
  `plan_flow.mine` gives the add-on my view (`plans.my_doc`); the
  snapshot and change notes keep reading the plan itself (`_plan_doc`).
  On the plan card: Open now on the next date (`open_one`), Not today in
  place of Undo (the undo, then `put_off`: tomorrow's morning opens them),
  Undo skip, "N new cards from earlier dates waiting · Catch up…" (G5:
  Anki's today-only deck limit, set each morning while it runs, so
  nothing to put back). Pause until… (from my Away dates), and the day
  after it asks: move my dates later by the days away, or open what I
  missed. The site shows a follower their own progress per date (G6).
- 3.5 plans that spread (mock "Plans that spread", `docs/plans-design.md`
  "3.5"), site and Worker only. A: a plan's link previews as the plan:
  the site Worker writes its `og:`/`twitter:` tags (escaped) and draws
  `/p/CODE.png` (`site/src/og.ts`, glyphs and logo from
  `tools/og_assets.py`: re-run it only to change the fonts or the logo),
  from `/plans/public` only, cached per version. B: the library
  (migration 0008): an owner lists a code plan (`listed`, `lib` kept at
  every save while listed); `/library` is newest first, never by
  followers; Copy makes my own plan crediting the original (`based_on`);
  the admin's Take out (`listed = -1`) is sticky; while listed, only its
  authors write notes (anyone can follow), and only theirs are shown. C: `/classes`, the
  Progress tab's hint (under half of 3+ sharing finished, two days after
  a date), and Print's Poster with a QR code (`site/public/qr.js`).
  `worker/tsconfig.json` includes `site/src`, and `worker/test/site.test.ts`
  runs the site Worker with the API behind its binding.
- 3.5 the site's own pages (mock "Home, Log, Admin", migration 0009).
  Home: a today strip (from my plans and my week), the board as it was,
  my year (from my log), and a rail with "since you were here" (`feed=1`
  on the site's board: added me back, notes, others' saves; the cutoff
  is per browser), crewmates' exams with Send good luck (a `luck` cheer),
  plans and friends. Log: tiles against last week so far, the year, this
  week and last, averages over days studied, 30 days by date (never by
  size), each plan's history (`hist` on my follow), CSV; the year fills
  in as the log grows (the server keeps 400 days). Admin: counts only; the
  daily cron keeps them (`admin_days`), sign-in steps and bridge runs are
  counters there (`admin.bump`), `bridge_last` is the bridge's last run,
  the cutover is 3.x / 2.x still studying / quiet, notices keep their
  history.
- 3.5.0 the Plans tab (mock "Plans Tab Review"): a Today box in the day's
  state (study, rest, done with what's next, behind with Catch up and
  Move my days back, paused), then one week in the site calendar's look
  (`plans.week_view`, my own shifted days; a list under 560px; ‹ › move a
  week, not saved), a day's cell opening its details (Open now, Skip it,
  Undo skip, Study, Move my days back), one note at most (the most
  pressing first, `board._plan_notes`), and the crew in words. The tab is
  always there; following nothing it's three ways in (a code, the
  library, make one). Settings › Board › Tabs hides any tab but Today
  (`hidden_tabs`, per computer). A code box anywhere (welcome, the
  board's) takes a friend's, a plan's or a squad's code
  (`shapes.long_code_from`).
- 3.5.0 invites (mock "Invite Page", option B, migration 0010): Copy
  invite makes a one-time code (10, `POST /invites`, kept as a hash, one
  use, 14 days, 20 a day) and copies "Study with me on Due Crew:
  duecrew.com/i/CODE". Whoever redeems it (`POST /invites/{code}/redeem`,
  any code box, or the page signed in) is crew with its maker at once,
  both edges: sending it was the maker's yes. Asking again writes
  nothing, so a removal since stays a removal; a new friend code ends my
  invites. Offline, the link carries my friend code, which adds
  and knocks as before. After its first use, or after 14 days, an invite
  works as the maker's friend code (add, knock, their Add back), so a link
  in a group chat is never a dead end; rows are kept a year for that.
  `/i/CODE` on the site (`invitePage`) says who
  (`GET /invites/{code}`, signed out: a name and an emoji, 300 an hour an
  address), the three steps on a computer, Email it on a phone; the site
  Worker writes its preview ("Sam invited you", `drawInvite`).
- 3.5.0 Settings in the board (mock "Settings in the Board"): the board's
  Settings opens in the board's place (`board.settings_html`, You, Board,
  Privacy; ‹ Board goes back), in its own tokens, so night mode and the
  accent just work. Each click is one command (`settings_model.change`:
  whitelisted keys and values, pure) and applies at once; no Save. A
  sharing change pushes 2.5 seconds after the last click (one sync for a
  run of them). Name, Emoji, Status, Friends, Squads and Shared Decks open
  their dialogs. The Qt dialog stays for when the board isn't on screen
  (turned off, signed out, another screen, Tools › Due Crew › Settings
  from the reviewer).
- 3.6 squad bingo (mock "Squad Bingo", migration 0011): every squad plays
  the same 3×3 card a week: eight squares about studying (one from each
  family: early, spread out, focus, bigger day, new cards, showing up,
  keeping up, wildcard; 3 easy, 3 medium, 2 hard; since 3.6.1 all team
  squares but one hard one: easy ones half of you, medium a third, the
  other hard one a quarter) around a middle the squad unlocks together (studying together
  or Due Crew weeks in turn, a season's first, free every sixth week). The
  only part about Due Crew is the middle. Every mark is passed on the way
  up, never stopped on; bigger days are against my own usual (30 days).
  The Worker draws and keeps the card (`bingo.ts`) from the pool the admin
  edits on /admin, and never works a square out: my add-on does, from my
  own reviews at the sync (`bingo_flow.for_row`, `bingo.progress`), and
  sends `play` on my squad rows (the same in every squad; squares as bits,
  days, counts for the middle), which boards add up (`bingo.evaluate` =
  `bingo.ts evaluate`: change one, change both). Show-up mode and the
  Privacy switches keep the squares built from hidden numbers home
  (`withheld`). My progress on each square stays on this computer.
  bingo.json per profile keeps the week's due-zero and new-done days (seen
  at a sync) and the middle's counts. The card rides the day's first
  refresh and the squad fetch (`wk=`): no new requests. The Squads tab
  shows it small; Open puts it in the board's place (`bingo`,
  `bingoback`, `bingocopy`).
  3.6.1 (migrations 0012, 0013): a share (`half`, `third`, `quarter`)
  is of everyone studying this week, older add-ons too, at least 2 and
  never more than there are of you (`how_many`), so a bigger squad needs
  more of you; a middle's goal can be one too. A square shows the number
  ("2 of you"), never the share. `row: true` on a rule wants its days in
  a row, and every medium and hard square is a streak (`isStreak`: the
  draw picks one when the family has one at that level). Only members
  whose add-on plays can stamp; ones on an older add-on are one line
  under the card. The middle never asks you to ask about a card, and its
  rule line has no fraction (the number is under it). No square pays for
  studying less: volume streaks are against my usual (`rel` with days),
  not the day before. My own row is the one this sync worked out, not
  the fetched one, and follows a redrawn card at once.
- 3.6.1 a reset config: a copy installed into another folder starts from
  defaults while the session remembers the account save it saw. The config
  now remembers it too (`account.SEEN_KEY`); one that doesn't takes the
  account's settings. And `GET /board?decks=1` returns my squads
  (membership): one missing from the config comes back (`heal_squads`,
  no code on this computer), never one I left this session.
- 3.6.5 picks that work in anyone's copy: a date's `notes` (note guids,
  every card of each) and `cards` read the same in every copy of a deck;
  pasted `nids`/`cids` are one collection's numbers, so the author's Anki
  sends what they are as guid + card number (`refs` on `PUT
  /plans/{id}/ids`, kept as `idr` only while those ids are unchanged; a
  site save never sets it) and followers union them (`DeckIndex.id_cards`).
  A unit's sig and sources take `notes` and `idr`, so refs arriving later
  open what they add. `nid:`/`cid:` aren't shareable searches. Text has
  `notes:G G` and `cards:G:N` (N from 1), read before the line is split,
  since a guid can hold `|` and backticks (`Picks` in builder.js); Anki's
  browser copies them (Due Crew: copy as plan selector,
  `plans.selector`). The morning counts what a date leaves shut
  (`plan_flow._tally`: leeches, exact picks this copy lacks) and the plan
  card says it once (`planasideok`). Adding to an opened date says
  followers get it tomorrow morning; Text's Add is the first button and
  Replace asks twice. The AI prompt can take the person's own cards (Anki's
  Notes in Plain Text export, with the unique identifier: `#guid column`)
  to pick by resource and add `notes:` the tags miss; their cards go only
  to their AI. It stays deck-neutral (any video, lecture or book), and its
  `#` lines come back as the AI's notes in the preview, never imported.
- 3.6.5 also (mock "Picks and Previews", P1–P6): P1 the author's Anki
  counts what each date opens (`plans.date_counts`: new, repeat, notes
  not here, in date order) on the ids request (`#pn`), kept as `pn` like
  `idr`; shown under a day, in the Text preview and in the prompt. P2
  Text opens on Add dates (an empty box that only adds; a line with a
  date's day and name adds to it) or Edit the whole plan (Replace lists
  what it takes off). P4 the prompt checks its own answer (`# Problem:`,
  `# Tradeoff:`, `# Question:`). P3 Tools › Due Crew › Export cards for my
  AI (`plans.export_notes`, Anki's own plain-text format with the guid
  first) and the browser's "export for my AI": to a file only. P5 the
  Plans tab's Today sits between ‹ ›, the box marks the open day, today
  keeps a filled date. P6 Send feedback (Tools, the board's Settings ›
  You, the Settings dialog, the site's footer) to /admin › Feedback
  (migration 0014; 2,000 characters, 5 a day, kept a year, deleted with
  the account); Reply mails from Due Crew, the address never shown. No
  plan surface guesses minutes any more (we can't know a person's pace
  per deck).
- P7 what's in a day (mock "Picks and Previews"): the Plans tab's day
  details list each date's topics as the site's print does
  (`plans.topics`: a tag under the first `#`/`^` part after its root,
  read as words; searches and picked cards as counts), Browse N cards
  opens Anki's browser on what the date matches here
  (`plan_flow.browse_date`, `planbrowse`), and the Today box has one
  line of them (`today_what`). Names and counts only, from the plan.
- Not yet today (3.6.7): a crewmate who synced but hasn't studied (a day
  doc with `studied` false, or a day inside an away spell) is no row of
  zeros with a rank: dashes, no rank, "· nothing yet as of 2h ago" (when
  we last heard: a phone's reviews reach us only at their computer's next
  AnkiWeb sync; Week: "nothing this week"), under everyone who studied,
  status and cheers kept
  (`build_rows`' `notyet`). A squad row synced today with 0 reviews and
  no time is the same. Ranks are only for rows with something to rank.
- The site's home board is board.py, restated in `Board` in app.js: the
  same rows (`rows` = `build_rows`, away days flagged from the week's
  spell as `shapes._week_days` does, the week's streak from its newest
  day), one chip (room > studying now > exam > away > week done), the
  notes, plan statuses, the show-up view, Decks (`+N today`, retention),
  Squads one at a time behind a switcher with Lock/Open and Leave, a
  Plans tab, and the footer's Crew ▾ and "N waiting". The bingo mini card
  too: the site never works squares out, so `GET /squads/{id}?wk=` carries
  `bingoEv` (the Worker's evaluate, done or not per square, never who).
  Change one, change both. The site can't show "back today" (the add-on's own history) or
  Copy invite for a squad (its code lives only in Anki).
- The site, together ("Site, together" S1–S7, built with "The next
  round"): every page in one 1180px frame (`main.wide` the same); pages to
  read (sign-in, account, feedback, a plan's or an invite's link) use a
  narrower column inside it (`reading()`), left-aligned with the logo. One
  footer on every page (`renderFoot`; `index.html` and `classes.html`
  match it by hand). A page opens with `phead(title, line, button)`: at
  most one filled button, on the title's line. Buttons climb one ladder:
  filled for the main thing, `ghost` (outlined), `quiet`, `linkish`, and
  the warm `danger`/`warn` only for removing; a library card is Look
  (filled), Copy (outlined), and ⋯ for Report and Take out. Account shows
  my code, where I'm signed in (`GET /auth/places`, counts only) and my
  data.
- Share cards (mock "Share Cards", K1–K5): my week (story or link
  size, the crew count a number only), my year in Anki (from my log), a
  squad's bingo (never who stamped what), a plan finished (its code only
  on a code plan). Drawn in the browser on a canvas (`site/public/cards.js`)
  from what the page already has; nothing is sent or kept, no link: the
  phone's share sheet, or a download. A number my Privacy switches keep
  home isn't in my week, so its switch is off. The cards keep their own
  green, light or dark, and the one-line logo from its file
  (`site/public/logo-line*.svg`, copies of `docs/logo`).
  K6–K8 ("The next round"): today's card is the week card with today's
  numbers (`one`); Anki's Crew ▾ "as a picture…" opens
  `/home?card=today|week` signed in (`plan_flow.open_site`) with the
  sheet open, so cards are drawn in one place; on a computer the sheet
  copies the picture (Copy picture); from 1 Dec to 7 Jan Home's rail opens
  with the year's card once a season per browser (`yearNudge`).
- Quiet accounts ("The next round", Q1–Q6, migration 0016,
  `worker/src/quiet.ts`). Activity is the newest of a sync or a board read
  (`last_seen`), a week the 2.x bridge brought in, and creation. After 90
  days crewmates' boards fold them into one "N quiet" line (add-on
  `_quiet_fold`, squads too, and the site's `Board.table`, from when they
  last synced: no request); after 6 months the daily job drops what a sync
  rebuilds (decks, heatmap, plan trees, knows); after 12 months (24 when
  paused) it deletes the account as Delete my account does, 50 a day,
  never an admin, except that a plan someone follows passes to its first
  co-author or stays ownerless ("a former member": followable, never
  edited). A hash of the uid is kept a year (`gone`), so an add-on refused
  by the server asks once (`GET /auth/gone?uid=`) and says "deleted after
  12 months" (`signed_out_card(gone=)`). The sentence is in the README
  (AnkiWeb), Settings (`board.KEEP_LINE`, the dialog too), the Pause choice
  and the site's Account. Admin Today has the housekeeping counts; each
  deletion is in the audit log.
- The admin's account lookup (mock "Admin Account Lookup", `people.ts`):
  one person at a time, never a list of everyone. A search is an exact
  email, uid or friend code, or up to 10 names that start with it,
  emails partly hidden; one account shows who they are, where they are
  (squads, plans) and counts of their crew, never how they study or
  their settings. Sign out everywhere, and Delete with their email typed
  out. Who their crew are only behind a click ("The next round", F1–F3,
  `People.crew`), each look in the audit log; one side of a friendship
  can go on their request (`removeEdge`, they're emailed), and admin
  never makes anyone crew. README's privacy section says so.
- Admin, grown up (mock "Admin, grown up", migration 0015): /admin is a
  sidebar of pages (Today with Needs you, People, Squads, Plans & library,
  Inbox, Notices, Bingo, System, Audit log), one gap scale. Sign-in help
  on an account: Email them a fresh code (past the limits; the add-on
  signs in by a code typed into Anki, so never a link), clear the
  per-address limits, Change their email (`email_changes`: it moves at
  the new address's first code sign-in, within a week, so a typo hands
  nothing over). The admin's note per account (`admin_notes`). A squad
  by its code or from an account (`adminsquads.ts`): members by name,
  Remove (block), New code, Open/Close, Rename, Make founder, Delete,
  the founder emailed each time. A new code is a row in `squad_codes`
  and `squads.code_id` marks the live one (`squads.idForCode`): the id
  never changes, so add-ons and the bridge are untouched, and the old
  code opens nothing (peek, join, restore). Everything done there goes
  in `admin_actions` (the audit log, a year; names looked up on read,
  never an email or a code). README's privacy line says Sam can look up
  an account and its squads when someone writes in.
- Due (mock "My List", L1–L15): the day's to-do in a box above the
  board on every tab (`due.py` pure, `due_flow.py` the glue,
  `board._due_html`; the name is `due.NAME`). Three tabs: Today (the day
  in full), Upcoming (today in short, then 14 days, empty days folded)
  and Later (my own items with no day). No going back a day: whatever
  isn't done sits under Behind on Today and Upcoming (my items one by
  one, a plan's past dates as one line with Catch up). A plan's date is
  on its day (my shifted, unskipped days; past ones only if they opened
  here) and ticks itself when its cards are seen and its author's lines
  are ticked; each resource's numbers come from the refresh's deck reads
  (`plans.parts`, kept in `_state["plan_parts"]`). An author's lines are
  `todo: [{k, t, url?}]` on a unit (watch/read/do, 8 at most, an https
  link opened by Anki, `duelink`), written in the builder's day panel or
  Text (`watch: Lecture 14 https://…`). My own items (`due_items`: 60
  open, 140 characters, ticked ones go after a week) and my ticks
  (`due_ticks`) are account keys, so the settings doc's cap is 64 KB; the
  site's home rail shows them read-only (ticking and adding are Anki's,
  which counts the cards and pulls settings once a day). Adding: the day
  button starts on the tab's day, a day said at the end of the text wins
  (`due.parse`, restated for the preview in `board.DUE_JS`: change one,
  change both), and an item added out of sight says where it went.
  Suggestions (`due_suggest`, at most two: today's misses, new leeches)
  and Recover leeches (`due_leeches`, per computer, off: each morning a
  leech, suspended or 8+ lapses, gets its tag off and Anki's Forget, one
  undo step) are in Settings › Board. No new requests: items ride the
  settings push.
- 3.7.1 (mocks "History", "Due fold", "What Due Crew Keeps", "Insights"):
  the history import (`cards.history_part`: a year of my log per full
  sync once the first 120 days went, up to 15 years, advanced only when
  the reply says `logAll`; the server keeps 15 years). Share cards for
  any year and all time (`/home?card=year|alltime`). Crew ▾ is people
  (`board.crew_menu_items`), Share ▾ is what you post, as text then as a
  picture (`share_menu_items`), in Anki and on the site. Due folds itself
  once the day is done (`due.fold_state`); Hide/Show holds for the day.
  Cheers received are counted (`cheer_counts`, migration 0017), shown
  only on my own cards. Privacy: `site/public/privacy.html` is the table
  of what's kept (change it in the same commit as what it describes);
  Account › Your data downloads it all (`GET /account/data`), deletes my
  log (`DELETE /log`: `cut`, and `logCut` ends the import) or my to-dos
  (`DELETE /account/todos`; the board's `settingsAt` makes Anki pull a
  save it hasn't seen, `account.saved_elsewhere`). Log has four insights
  (`logInsights`). Copy: say what isn't on screen; never narrate what is.
  Seen, for a plan, includes a new card whose note has a card answered
  (`DeckIndex.counts`): Anki buries and spaces siblings, so a date whose
  notes are all started is done and never behind for them; Due says
  "done · N siblings tomorrow/later" (`DeckIndex.siblings`). Suspended
  siblings stay out.

## Releasing

1. Bump `due_crew/manifest.json` version.
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
  and in Cards…: from any page but the ones Due Crew draws on (Decks,
  Overview, the top bar, the reviewer's bottom bar: `_our_page`) only the
  room widget's keyed commands in `room_model.CARD_PAGE_CMDS` are taken
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
