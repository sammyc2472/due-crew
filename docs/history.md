# Due Crew: how it got here

Every feature's notes, by version, moved out of `CLAUDE.md` (which keeps the
map and the rules). Each entry says what was built, where it lives, and why
it is the way it is; the mocks it names are on the design-spec artifact.
Read a feature's entry before changing it (search for its module, its
command or its mock's name), and add a bullet here, in the same voice, with
every release that changes how something works.

## The data model and the features, oldest first

- A refresh is one request: `GET /board` returns me, my crew (the people I
  added, each with their week when they added me back, name and emoji only
  when not yet), my cheers (3.7.2: kept until the next refresh's `got=`
  says the last reply's arrived; older add-ons, deleted as read), my knocks, and shared
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
  codes and invites carry their own names. Adding by uid (`PUT
  /friends/{uid}`: add back, a knock's Add) needs that connection already;
  a stranger's uid gets the same 404 as no such account.
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
  import sets it to 1, the first 3.x sync sets it to that time, and it's
  spent a week later, so a restore that failed once tries again); the
  client version alone was anyone's to set.
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
  (`[opened, seen, total]`; since 3.7.6 for every plan I follow, for my
  own views, counted for others only while I'm on its team) rides `POST
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
  The chip is on the answer side, never inside a card: since 3.7.1 a small
  card bottom right of the review screen while the card's own text and
  pictures leave that corner free (looked at again as pictures load, on
  scroll and resize), else beside Edit (`knowsbar`); its clicks are keyed
  (`CARD_PAGE_CMDS`), and This helped from there asks first. Who
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
  plan surface guesses minutes (we can't know a person's pace per deck);
  since 3.7.9 Insights may show time from the person's own measured pace
  in this deck, and only then.
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
- 3.7.2 (what the October bug run left): Due's ticks on an author's lines
  are keyed by the line (`due.line_keys`: FNV-1a of kind and text, a
  count for twins; `dueLineKeys` in app.js: change one, change both), so a
  reorder moves them; a 3.7.1 tick by place still reads. C5's `ids` are in
  a unit's sig and sources, so ids arriving after a date opened open what
  they add (a plan's first pass under 3.7.2 carries applied dates over as
  they stand, `sig2`). While an even date (or a 3.2 schedule) runs, Due
  counts what has opened so far, so its unseen slice is Behind; a date with
  nothing of it here is done once counted, so Due folds. Plain Undo leaves
  a date opened in slices to its schedule. The Worker's days are the
  person's Anki day (`ankiDay` on `users.tz`/`rollover`): plan history,
  cheer counts, Delete my log. An account's plans keep at most 24 MB
  (`PLAN_BYTES_MAX`: docs, library cards, Undo's copy, only the latest
  save's), its deck trees 6 MB (oldest go first); a save that shrinks is
  never refused. `PUT /settings` with the save the server has writes
  nothing.

- 3.7.3 plan updates (mock "Plan Updates", option B): every refresh sends the
  plans' stamp it last saw (`pv`, `session.plans_pv`) and the plans come
  again only when it moved (an author saved or posted, my own days changed
  on the site): no new requests. After the day's morning (`plans_day`)
  fresh plans never open on their own: `plan_flow.midday`, on the Decks
  screen only (it waits for Decks from the reviewer, `plans_midday`), dry-
  runs the morning (`run(dry=True)`) and keeps what an update adds to today
  and earlier in `_state["plan_updates"]` for the plan's note (Open, one undo
  step; Not today, `ask_later`: tomorrow's morning, still applied as it
  was) and Due's row. Future dates redraw at once. A follower who chose
  Hold back has new cards of later dates held too (`hold_new`, morning and
  midday). The change note says "updated" for a date whose picks changed
  (`snapshot`'s third item; C5 ids and refs don't count). Posts
  (`plan_posts`, migration 0019): authors post to followers on the plan
  page's Updates tab or with a save ("Tell followers…"); Anki shows the
  newest unread on the plan (`posts_seen` in plans.json, a week back at
  most), the site's home feed lists them. An author sees "This version is
  in N of M followers' Anki" (`seen_version`, written when a board carries
  it). A date that opened is never closed again by an update.

- 3.7.3 a plan's team and Insights (mocks "Plan Team and Insights", rounds
  1–6): the plan card has three tabs, Plan · Team · Insights
  (`_state["plan_sub"]`, per session). Team is opt-in per plan (migration
  0020, `worker/src/team.ts`, `team_flow.py` glue, `team.py` pure): joining
  shares that I showed up today (answered one of the plan's cards, my Anki
  day; `team` on the sync carries the last 8 such days, so a phone's come late; rows I hold only), my questions and answers, and
  my bingo squares (`bingo_flow.my_play`, the same as on my squad rows);
  never a number, never weak spots. The board carries counts (`teams`:
  shown, of, streak, faces, act, last) for the Plan tab's line and the
  badge (unread: `team_seen` in plans.json); the tab is one request when it
  opens (`GET /plans/{id}/team`), each click one more. Card questions carry
  guid + card number, never text; each reader's Anki says "on a card you
  have down" itself (`cards.i_know`), from the reviewer's "ask the team
  about this…". Team bingo is the squads' card, middle and all,
  each member's play the same as on their squad rows (one stamp counts
  everywhere), counts never who; `team.bingo_line` =
  `bingoLine` in builder.js. Insights are mine alone and Anki only
  (3.7.9's below). On the site a
  follower's plan page is Calendar · Team, the authors' newest post above
  the tabs until closed (per browser); authors keep Updates.
- 3.7.4: a plan team's bingo is the squads' card (one play, stamped
  everywhere); behind leaves out the new siblings Anki buries for an older
  note's review (`DeckIndex.buried_today`); the plan page no longer fails to
  open on a named date with no tag or subdeck in the deck's tree.
- 3.7.5: the Today box counts now (`schedule.today_view`'s `seen_now`):
  behind is what's still short of yesterday's quota, so catching up today
  clears it, and cards seen today fill the oldest dates first; today asks
  what wasn't seen by the morning, as the day's details and Due count. The
  ask chip beside Edit keeps the answer buttons centred (`BAR_BALANCE`
  sums each cell, leaves padding out) and, narrow, says who in short
  (`short`: "Ameya +1", "Ameya's tip"); a crewmate's ask shows their line;
  once I've asked, it says Asked.
- 3.7.6: `rooms.will_answer` takes Anki's filter shape, `((proceed, ease),
  reviewer, card)`; 3.7.2's took four arguments, so the first answer of a
  session raised and Anki dropped the break's guard. A plan's team and
  sharing my progress are one choice (migration 0021): on the team, my
  progress counts for its authors and the crew; off it, it's kept for my
  own views only. Follow's box is "Join this plan's team", unticked; `share`
  alone (older add-ons' box) no longer shares. Followers who shared before
  are asked once on the plan card (`teamAsk`: Join, or No thanks,
  `planteamno`) and count for nobody until they join.
  Your own days (mock "Your Own Days", migration 0022): Move… on a date
  from today on (`moved` on my follow: {unit: days later}, on top of
  `shift`; `plans.my_doc` marks it `_moved`; Put it back), Plan ▾ › Reset
  to default (shift, skips, moves and pause in one PATCH, after saying
  what; also on the site's plan page). Following late (`plans.late_start`):
  Start where everyone is (the passed dates skipped on my follow, so behind
  nowhere), Catch up over 1–3 weeks (G5's limit), or Start from the
  beginning (`shift`, warned when it runs past the plan's end or an
  event). While a catch-up runs, the Today box doesn't call it behind.
  The bottom bar's answer buttons are slid to its middle (measured,
  `translateX`, re-run when the bar changes), and the ask chip sits beside
  More, else Edit, whichever has room.
- 3.7.7: times from the server are Unix seconds, past `shapes._nat`'s
  10**9 cap, so they go through `shapes._when`; Team questions read
  "20733d" and the Team badge never lit before it.
- 3.7.8: someone with no emoji gets their name's first letter in an accent
  circle (`board.face`, `face` in builder.js: change one, change both),
  not the escaped "&#128100;". "Days of prep" counts days, not dates (the
  plan page, `plans.prep_for`, the .ics feed). The builder's day panel
  fits its rows (no sideways scroll). Trial, site only, admin only: plan
  load on Home's Plans tab (`planLoad` in app.js): each of my dates on my
  own day, one number (today to go, ahead what's new to me that day,
  i.e. still locked, past behind) and one bar a day (the day's size,
  filled with what it asks), from the progress Anki already sends.
- 3.7.81: the plan load in Anki's Plans tab too, more exact than the site's:
  `plans.load` counts each date's cards on my own days as [seen, open,
  locked], a card on its earliest date only and a suspended leech never
  (`plan_flow.loads` at the refresh, `_state["plan_load"]`, the same deck
  read as the progress). A day: one number (`plans.load_ask`: ahead, still
  locked; today and before, not seen) and one bar under its date
  (`board._abar`, the week's biggest is full width); a date's details
  `board._load_words`. No new requests; the site still reads progress.
- 3.7.9 Insights (mock "Insights", rounds 1-17, drawn on Sam's own
  collection with read-only snapshots): mine alone, Anki only, worked out
  when the tab opens (`team_flow._work_out`, kept 10 minutes, about 0.2 s
  on a 35,000-card deck), never sent. Text only where it's counted or is
  Anki's own memory model. The header: right on the deck's reviews (first
  answer of each card each day) against the 2 weeks before. The hero: the
  plan's started cards Anki won't show me before its next event (in 21
  days, else a week out) that FSRS has under my target by then
  (`team.recall`, the card's `s` and `decay`), with Study; FSRS on only.
  When dates prep for that event (`for`), only their cards, and the box
  wears its name; else the whole plan, and the box goes by the day
  ("Before Tue 13"), since the cards aren't all for it.
  Not sticking yet: per topic (20+ reviewed in 14 days), cards never right
  in a review yet, as of now, plus those forgotten after being right, the
  source from the tags (`team.source`), Study; no links. Behind: a line
  with Catch up. Your week in minutes: 7 days as studied, today, and the
  plan's next days at my own pace (seconds an answer; a new card's first
  week, from 50+ started 7-28 days ago, put on the day it opens). Optimize
  FSRS: when cards 1-3 days since their last review come back 3+ points
  under my target with 300+ answers (`lastIvl`); it opens the deck's
  options, Not now hides it 30 days (`ins_fsrs_hide`). Nothing to say:
  "Insights fill in after a week of reviews."
- 3.8.0 one kind of squad (mock "One kind of squad" on Next Round): a plan's
  team is that plan's squad, shown on the Squads tab beside my own squads
  as a pill named for the plan (`team_flow.plan_squads`, picked as
  `cfg["squad"] = "plan:<id>"`; with no squad of my own, it's the one
  shown). It shows who showed up today, its bingo, then Ask the squad and
  its threads, and "Open the plan · Leave" (`board._plan_squad_html`;
  `PlanSquad.view` in builder.js on the site's Home). The plan card's
  Team tab is gone: Plan · Insights, and a line "Squad: N of M showed up
  · Open ›" (or "Name asked ›"), or "Join its squad", which asks first and
  says what it shares (`planteamjoin:<id>:ask`). The badge rides the pill.
  The site's plan page lost its Team tab for the same line. The Worker is
  unchanged (`/plans/<id>/team`, `session["teams"]`), so the requests are
  the same: the squad is one request when it opens, cached a minute. On
  the site, being in it is `following.share` without `teamAsk` (3.7.6).
  Topics as links (3.8.0, asked for by Sam): each topic in a date's
  details on the Plans tab, and in the Today box's line, opens Anki's
  browser on that topic's cards in my copy (`plantopic:<plan>:<dates>:<i>`,
  i its place in `plans.topic_items` of those dates; `plan_flow.browse_topic`).
  `topic_items` keeps what each readable name stands for (its tags, subdeck,
  search or picks, merged by group and name), and `topics`/`topics_line`
  read from it, so the names and their clicks can't drift. The search is
  the tag itself, kept to the plan's deck (`"deck:X" tag:Y`, my copy's root
  when the plan's is swapped), when Anki finds exactly the plan's cards with
  it, so the search bar reads as the tag; otherwise the cards by id. A
  search run here; nothing is sent.
  More ways to the cards (3.8.0, Sam's picks 1-5 and 7): what's left of a
  day ("16 left", "2 behind", "3 to go" in its cell, which no longer opens
  the day when you click the number; "24 left" by Browse in its details),
  the Today box's "16 new behind" and Due's Behind "N cards to see" open
  Browse on those cards not seen yet (`planleft:<plan>[:<dates>]`,
  `browse_left`; behind is every date before today, opened cards only, by
  `DeckIndex.unseen`, which is `counts`' seen turned round). Due's plan rows
  link their topics as the Plans tab does. Insights: a topic's name and the
  hero's count open the same cards Study would (`planinsbrowse`). The plan
  card's "N leeches stay suspended" has See them (`planleeches`). In Anki's
  browser, right-click › "Due Crew: show on my plan" opens the board on the
  date that has the card: the Plans tab, its week, its details open
  (`show_on_plan`, `jump_to`; `_state["plan_focus"]`, let go when the week
  moves). The site's day panel has Copy search on each tag, subdeck and
  search (`Tags.ankiSearch`: `"tag:…"` with `_`, `*`, `"` escaped, a
  versioned root as `_v*` so any copy's version matches).
  Siblings by day (3.8.0): a day's new cards (`session_view`'s
  `new_by_day`, behind the missed-days question and the weekly recap) came
  from first answers only, so the siblings Anki buried behind a cloze's
  first card didn't count and a cloze-heavy day could read as missed. A
  new sibling of a started note now counts on its note's first day, as
  `counts` already calls it seen.
  The morning waits for Decks (3.8.0, Spring Clean): a sync that landed
  mid-review could open the day's cards under the reviewer, and its undo
  step then sat in the middle of my answers. The morning now opens only
  on the Decks screen (`mw.state == "deckBrowser"`); anywhere else it
  waits (`_state["plans_morning"]`) and runs at the next Decks render
  (`_morning_now`). A plan whose held cards went with it waits the same way.
  Firebase is gone (3.8.0, Spring Clean): the 2.x bridge and its quarter-hour
  cron, the identity import, `PUT /friends {ids}`, `POST /squads/restore`,
  `POST /codes {code}` (a code is always drawn), the admin's cutover and
  bridge panels, `firestore.rules`, `tests/rules/`, `firebase.json`, the
  rules CI job, the add-on's restore path and the import/restore tools.
  `ADMIN_TOKEN` and `FIREBASE_SA` are unused; deleting them and the Google
  project is Sam's (`docs/cloudflare-setup.md`). A 3.x add-on that still
  owes a restore gets a 404 there and counts it done. `bridge_last` and
  `users.from2x` stay until a later migration: migrations apply before the
  Worker deploys, and the old Worker still reads them in between.
  A refresh's plans: the add-on keeps its plans only when the board's
  `plans` is a list (`plans_came`), so a board without them never reads
  as "I follow nothing".
  The site's day is Anki's (3.8.0, Spring Clean): duecrew.com rolled its
  day over at midnight, so between midnight and a 4am rollover its today
  was a day ahead of the add-on's. `/auth/me` carries `rollover` (the hour
  the add-on last said), and `today()` in app.js counts from it.
  Due's digits (3.8.0): `due.when_word` read any script's digits (`\d`),
  the add box's preview (`board.DUE_JS`) only 0-9, so "١٢ oct" was a date
  in one and text in the other. Both read 0-9, and a parity test runs the
  JS against `due.parse` in node.
  An unreadable plans.json (3.8.0): it read as no plans and the next save
  wrote over it, losing the list of cards a plan held back. It's moved
  aside as plans.json.bad (bad2, ...) and said once (`plan_flow._set_aside`).
  Dead code out (3.8.0): `board._full_crew_days`, `_exam_badge`, `_pbar`
  and their CSS, `bingo.FAMILY_NAMES`, `SHARE_WORDS`, `team_flow.on_team`,
  `cards.ts TIP_MAX`.
  Crew, one tab (3.8.0, Sam's call): Today and Week are one Crew tab, picked
  under the pills as a squad is on the Squads tab (`board._crew_picker`, the
  same `.dc-sw`; `sqsw` on the site). The tabs are Crew · Decks · Squads ·
  Plans; the Crew pill goes back to the view last picked (`crew_view`, per
  computer; `dc-crew` on the site, where a saved Today or Week tab reads as
  Crew). Show-up mode keeps its one view, without a picker. Week is no longer
  a tab, so it can't be hidden (`HIDEABLE_TABS`).
  You, and your people (3.8.0, Sam's call after four rounds of mocks on the
  design spec): Due and Crew split. Over the board is what's mine, the You
  bubble (`board.you_html`; `#due-crew.dc-split`, the board its own
  `.dc-sheet` under it): Today, Upcoming and Later (Due's lists, while Due is
  on) and, after a gap, Plans and Insights. The board is my people: Crew,
  with Today · Week · Decks in its picker (`crew_views`; This week and Decks
  in show-up mode), and Squads. Plans and Insights left the board for the
  bubble; `due_tab` says which tab it's on (per computer), a link to one
  opens the bubble on it and shows it again if Settings hid it (`duetab`,
  `plan_flow.show_plans`, `team_flow.go_insights`). Due off hides only its
  lists; with Plans and Insights hidden too there's no bubble. Settings ›
  Shows: Crew always, then Decks, Squads, Plans, Insights. An older install's
  saved Plans tab opens in the bubble at profile open (`_settle_tabs`).
  One Today: the plan's Today box is gone; today's dates are Due's Today.
  What the box said that Today doesn't moved: paused (Resume now), a rest,
  catch-up or taper day (`board._plan_now`); "This morning opened N" with
  Put off to tomorrow (`plan_flow.morning_opened`, under Today, or on Plans
  when Due is off); behind's Catch up on the plan's behind line, whose menu
  has Push my dates back (the day details' Move my days back has that name
  too); opened N days early in the plan's line. The leeches line went to
  Insights (a leech is the deck's, not the plan's); `planleeches` went with
  it. The plan card's Plan · Insights tabs went (`plansub`, `_plan_tabs`);
  instead it carries the next exam's cards at risk, from Insights, with
  Study and Insights › (`card["ins"]`, `team_flow.plan_lines`). Offers to
  follow a squad's plan show on Squads and You › Plans.
  Insights for everyone (3.8.0): a deck at a time, picked as a squad is
  (`team_flow.you_decks`: the decks of plans I follow, the deck I last
  picked, then the decks I reviewed most in two weeks; five at most;
  `ins_deck` per computer). With a plan on the deck it's 3.7.9's; without
  one, my own exam date (Settings › Privacy) aims the box ("Your exam") over
  the whole deck, the deck's tags name the topics (`team.deck_topics`: each
  card under its most specific tags, rolled up a tag's own levels to the
  first with 20 reviewed, never to a hierarchy's root or a resource's level,
  never Anki's leech or marked), its subdecks when its cards have no tags,
  and the week ahead is what Anki has due with the deck's new cards a day.
  A deck's cards are SQL in the queries (`_deck_sql`), never 30,000 ids.
  Commands carry the deck's id (`ins*`, `youins`, a digit-only argument);
  Crew › Decks has "How it's sticking ›" on my own decks (`youins`). Cached
  per deck and per plan/exam (`_state["insights"]`), every ten minutes.
  On the site (the twin): the board is Crew · Squads with Today · Week ·
  Decks in Crew's picker; a saved Decks or Plans tab reads as Crew; the
  board's Plans tab went to the rail's Plans panel (following none, the
  ways in), and the admin's plan-load chart to the Log page, which has room
  for it. A stray `.ptab` rule that turned the builder's side tabs into a
  grid went with the old tab's CSS.
  Calmer (3.8.0, Sam: "still looks busy in places"), nothing taken away: the
  box's tabs are words, the one on screen underlined, Plans and Insights
  after a thin rule, and Hide a quiet word (the board's pills stay the
  buttons); its info lines lost their fill, and what's next and the exam
  are one line under Today ("Tomorrow: … · ★ Quiz Sat · Upcoming ›").
  A plan date's topics sit on their resource's row (P.parts groups as
  P.topics does), so its separate topics line is only for what has no
  resource. Behind is Today's alone (Upcoming repeated it). A to-do's day
  button is a word. On Plans, a note is a plain line under a rule, every
  day's details wait for a click (today's are Today's; Browse › Show on my
  plan still opens its day), and "Month on duecrew.com" is "Month ↗".
  Insights' decks and where its topics come from share a row ("From your
  plan …", "From this deck's tags"). The footer keeps one pill, I'm
  studying; Open a room and "N waiting" are words, on the site too.
  Simpler (3.8.0, Sam: "the due section has a border, but the crew
  doesn't"; trust the person over explaining): Anki paints the Decks
  screen #f5f5f5 (26.x), so the box and the board are the same white card,
  and the box lost its accent border (the preview draws on that grey now,
  so it shows what Anki shows). One underline for every word tab: the Crew
  picker, a squad's, Insights' decks (was dotted). Boxes inside cards went:
  Plans' three ways in, a plan squad's questions, the bingo card (rows
  between rules now). Words cut: Insights says nothing about where its
  topics come from (the plan's name links to it; with no exam date set,
  "Exam date…"); "Newest cards 85% right, Anki aims for 90%"; "3 suspended
  leeches"; no "Today" label under the Today tab, no "3 things" on a day
  that lists them, "Nothing here." on an empty Later; "No squads yet." and
  "No shared decks yet. Pick decks to share"; the week key's "longest =
  busiest day"; Settings' captions that restated their row, a shorter
  account line (KEEP_LINE) and save line.
  Smaller (3.8.0, Sam): Today ends with its list (the "Tomorrow: … ·
  Upcoming ›" line went; Upcoming says it), and Later has no tab while it
  holds nothing (a saved Later reads as Today; adding one shows it).
  Five small ones (3.8.0, from the dream list). The morning clears the
  filtered decks Due Crew built once they're empty (`plan_flow.tidy_decks`,
  `plans.tidy`): ours are the ids `_filtered` built (plans.json `built`, the
  last 200) or a filtered deck named "Due Crew · …" from before; one with
  cards in it stays (a checkpoint not done, a date half studied); it runs
  before the morning unsuspends, so Put off to tomorrow still undoes the
  morning. Reviews says "4 back at 9:42" while intraday learning cards come
  back later today, past Anki's learn-ahead (`collapseTime`), and stays
  open until they're done (`due_flow._reviews`: back, at). The morning's
  line has Sync now (Anki's own Sync) while this Anki signs in to AnkiWeb
  and the collection changed since its last sync (`col.mod` > `ls`, both
  ms). Insights takes my exam date in its head (on every deck since "Insights is the deck's" below)
  (`setexam`, as Settings; the crew sees it for the two weeks before).
  Insights says when Hard is 15% or more of 200+ review answers in four
  weeks ("Anki counts Hard as remembered"), with Not now for 30 days
  (`team.hard_habit`, `ins_hard_hide`); said, never changed.
  Repeating to-dos (3.8.0, D10): "every mon", "every mon and thu",
  "weekdays", "daily", "mondays" at the end of a to-do, or "every mon:"
  first (`due.parse_repeat`, twin of the add box's preview, node parity
  test). The item keeps `r` (its weekdays, Monday "0") and `done` as the
  last day ticked; it's on Today on its days, once in Upcoming (today's, or
  its next day once today's is ticked; a day ahead has no tick), never
  Behind or Later, never pruned, always open; its menu has Stop repeating
  (a one-off today). The site's Due panel puts it on its days too
  (`dueOnDay`). An add-on before 3.8.0 drops `r` when it next saves the
  list, and prunes a repeat a week after its last tick; both computers on
  3.8.0 keep it. The site's Your data counted ticked to-dos as open; fixed.
  No jumps (3.8.0, Sam: "things really drastically change size"): measured,
  the You box ran 35–633 px across its tabs and Squads 122 px while
  fetching, so a click moved everything under it. A redraw while the
  pointer is on Due Crew never makes the box or the board shorter
  (`board.swap_js`, which `_swap` draws through): each holds its height
  until the pointer leaves, then eases back; a part still fetching
  (`.dc-wait`) holds either way; Hide folds at once. The board sits under
  Anki's deck list, so the decks never moved.
  One Settings (3.8.0, Sam's pick from the mocks): Tools › Due Crew ›
  Settings… and the add-on's Config button open the board's Settings on
  the Decks screen (`open_settings`), from any screen, signed out or with
  the board turned off too (`_on_render` draws Settings first: it's how the
  board comes back). The Qt window (`ui/settings_dialog.py`, 570 lines that
  said it all twice) is gone. Tools › Due Crew › Show on the Decks screen
  is a check, the way back from the menu.
  Two keys (3.8.0): Ctrl+Shift+S, Study what's next (the menu's first item
  carries it), and Ctrl+Shift+Q, the reviewer's Ask the squad for the card
  on screen (`team_flow.ask_this_card`; off the review screen, a line says
  what it's for). Both clear of Anki's own (Ctrl+Shift+S is Reposition only
  inside Browse, its own window). Settings › Board › Shortcuts lists them
  with one switch (`shortcuts`, per computer; `_apply_keys`).
  Study today (3.8.0, Easier Anki §3): one button in the box's head and on
  its folded line, and Ctrl+Shift+S. The walk (`due.study_next`,
  `due_flow.study_today`): each plan's deck in plan order, then the deck
  with the most due (Anki's deck tree, its limits), then today's misses
  once (a filtered deck), each in Anki's own review; when Anki's review
  hands over to the overview with nothing left (`state_did_change`, the
  deck's counts at 0) it goes on, said in a line ("Next: Year 2"); leaving
  the review any other way ends it. Inside a deck, Anki orders reviews and
  new cards by the deck's options. At the end: "Done for today", or the
  learning cards back later.
  The topic map (3.8.0, Easier Anki §9, Sam: "you made a … plan thing by
  topic, where did those go?"): in Insights, my started cards in broad
  subjects (`team.subjects`), each a tile sized by its cards and shaded
  by how much I know now, FSRS's recall today (stability, days since its
  last answer) or with FSRS off the share whose last answer was right;
  70/80/90% shades. Plan or not, by the deck's own tags. Sam's first look:
  "mixed up / hyperspecific" (it named the plan's lecture topics, a card
  in several). Now a tag's family is what comes before its first level
  (under a resource's mark, "^Systems::Cardio" reads Cardio; else the
  tag's root), each family is cut at the shallowest level with two tiles
  of 20 cards, and the family whose tiles hold the most cards with one
  subject each wins, so a lecture tagged under two systems never makes
  the map. A card in two subjects counts once, in the bigger. Every tag
  under one root ("Step1::…"): what's under it. With no tags to say, the
  subdecks. Sam: "could clicking on a tile open up subtiles?": a tile that
  splits again (two of 10 cards, four levels at most) opens into its
  parts, with the trail back above them ("All › Cardio · 412 cards, 86% ·
  Browse all"; `insmap`, `insmapup`, `insmapall`, the keys opened in
  `_state["map_at"]`, per deck, this session); a tile that doesn't opens
  all of its cards in Browse (`team_flow._find_cids`: the deck's cards
  under the tag and its children, or the subdeck), new ones too. Names
  that read the same keep their numbers ("01 Chapter"). Twelve tiles a
  level at most, biggest first. About 1.2 s on a big shared deck's size
  (each tag read once), in Insights' ten-minute cache. A question bank's
  id tags ("…::Step::104523") are never a subject, in Not sticking yet
  too. Not sticking yet: a topic's name opens all of its cards in Browse
  (Sam: "that should open everything while the study XX opens the hard
  ones"); its Study keeps the ones not sticking.
  Insights is the deck's (3.8.0, Sam: "it honestly can always be
  organized by deck … the benefit of the plan is the more specific
  feedback"): its head is the decks and my exam date, on every deck; the
  plan's name and its way off to Plans went. The decks are listed by
  reviews in two weeks (a plan's deck not among them after, the one I
  picked always). A plan I follow on the deck only sharpens it: the exam
  box aims at the next of my exam date and the plan's events (a plan
  event counts its prep dates' cards; my exam, the whole deck), Not
  sticking yet names the plan's dates, the week counts its dates, and
  Behind has Catch up.
  The map, round three (Sam: "the tags are now too high level to be
  useful … look at the cards that are currently unsuspended"): tiles are
  the deck's cards in play (unsuspended, started or not), sized by them,
  and the cut is the one that splits them best (`team._score`): the share
  of cards in its tiles, each in one subject, times how many tiles' worth
  it makes (the exponential of the sizes' entropy; 5 or more is full
  marks, 3 inside a tile). Every family's every depth is tried, so one
  block open (all Cardio) shows Cardio's parts, named by the level above
  when two read the same ("Cardio · Physiology"). A tile is shaded by
  what I know of its started cards, a bar along its foot says how much
  of it is started, and none started reads "new". A tile's parts are
  worked out for the level on screen (its › is exact) and deeper when it
  opens (`team.expand`). On a big deck the cut is chosen on an even
  sample of 3,000 cards, then made of all of them: about 1.6 s with
  24,000 in play, in Insights' ten-minute cache.
  The map, round four (Sam, with yield tiers for tiles: "still giving me
  bad tag choices … a tough puzzle to crack"): a rating splits a deck as
  evenly as a topic does, so a cut now scores half when its cards have
  nothing below it (`_score`: a topic opens into parts, "1-HighYield"
  doesn't), and "$" and "!" mark a resource too. And the person decides:
  the map's heading says "by Systems ▾", a pick of the best few ways (each
  tag family that splits, and Subdecks), kept per deck on this computer
  (`ins_map_by`, `insmapby`); a pick no longer there falls back to the best.
  What I know, to share (Sam: "is there a way to make a bento
  shareable"; "is there a text-based version"): Share › on the map's key
  (`insmapshare`) opens a sheet with the level on screen as a 1080 square
  card (`mapcard.card`, drawn with QPainter in `ui/map_card_dialog.py`,
  the site's picture-card look: eyebrow, deck, tiles squarified, the
  board's shades and amber, duecrew.com at the foot), with Percentages
  (off: names and shades, a Less–More key), This week's change and Light
  or Dark, then Copy picture, Save… and Copy as text (`mapcard.text`: a
  square a subject, 🟩 80 and up, 🟨 from 70, 🟧 under, ⬜ new). Made in
  Anki and only goes where it's pasted: Insights are never sent. The
  change: once a week the map's know per tile is kept, per deck and way
  (`mapcard.keep_ways`, three a way, four ways a deck, in plans.json's
  `map_snaps`), and the card compares with the newest a week old or more
  (`week_ago`), on the top level only; until there is one the switch is
  off with "From next week".
  Every picture made in Anki (Sam: "make the copy picture do the same
  thing for all the other places it is instead of opening the website"):
  Share › As a picture › My day…, My week…, My year…, All time… no longer
  open duecrew.com; they open a sheet like the map's (`shares.picture`,
  `ui/share_card_dialog.py`) with the site's cards (`sharecard.py`, a
  port of cards.js: the same layouts, words and look, each card a list
  of things to draw, so the suite reads what a switch takes off), from
  my own reviews: the whole revlog read once a session (`_log_days`, a
  wait cursor; about a second for millions of reviews), then the last
  month again (a phone's late sync). A switch for each number, Story or
  Link (a year is a story), Light or Dark, a year picker with All time,
  then Copy picture and Save…. My day's and week's switches start where
  my Privacy switches stand (Just show up: every number off; "off in
  Privacy" by the switch), and stay mine to flip: the picture only goes
  where I paste it. How many of my crew studied too comes from the
  board's cache; the cheers my crew sent me (year, all time) are one
  read on a click, after the sheet opens (`GET /log?cheers=1`, `{cheers}`
  alone; an older Worker ignores it and sends the whole log, cheers in
  it), and the switch says "counting…", "sign in to count" or "couldn't
  count" until then.
  Why isn't this card showing? (pick 9 of The First Month): Browse ›
  right-click › "Due Crew: why isn't it showing?", signed in or not (it's
  Anki help). A suspended card, a buried one, one in a filtered deck, a
  new card past today's limit and a review not due till Friday all look
  the same in Anki: not there. `why.py` (pure) gives each its sentence in
  Anki's own words (Suspended, Buried, filtered deck) and Anki's own fix:
  Unsuspend, Show it today (unbury), Empty the filtered deck (it says how
  many cards go home: Anki can't send one alone), N more new or reviews
  today (Custom Study's own raise, by enough to reach the furthest card,
  its place counted among its deck's new cards), Study it now (Set Due
  Date 0), or Study the deck; a learning card comes back by itself.
  Alike cards go together ("3 suspended, 1 of them as leeches"), the first
  2,000 picked are read. `why_flow.py` reads the cards and each deck's
  room today from Anki's deck tree and runs a fix as one CollectionOp
  (Edit › Undo takes it back), then reads again; `ui/why_dialog.py` is the
  sheet, every line plain text. `tools/real_anki.py` checks it on Anki's
  engine: each state, each fix, and that the raise reaches the card.
  Find a setting (pick 28 of The First Month): a box in Settings' bar.
  A word finds a setting on any of the three tabs, by its label, its
  section or a plain synonym (`FIND_WORDS`: colour finds Accent, holiday
  finds Away, log out finds Sign out); Enter takes the first. The index
  (`settings_index`) is read from the tabs as they're drawn, so a new row
  is findable at once, and holds none of the person's own names, status,
  squads or decks. A pick on the tab on screen lights its row; on another
  tab it asks for that tab (`settab`) and the next draw lands there
  (`FIND_JS`, `dcFind`), the row lit (still, with Reduce motion).
  Board in Motion (Sam picked all seventeen on the mock page): the board
  is redrawn whole (`board.swap_js`), so `motion.js` (one file, byte for
  byte the same as `site/public/motion.js`) notes before each swap what
  its rules know (a tick, a bar, a count, a tab group, a crew cell keyed
  by person, column and view, a square, a deck bar, the map, a bingo
  stamp, the sparkline) and after it moves only what changed. A refresh
  that brings nothing new moves nothing; nothing moves with the system's
  Reduce motion; nothing sorts, so rows never slide past each other. The
  seventeen: a tick draws its check and the words get their line; the
  day's bar grows and its count rolls; finishing the day lights the box
  once and the open box says "✓ Done for today" as the folded line did;
  Add opens the new row into place, or flies a chip to Upcoming or Later
  (the Add box leaves a hint, `dcMotion.say`); learning cards back glow;
  Hide and Show ease the box's height; every tab group's line or pill
  slides to the pick and what's under it comes in, the box easing to its
  new height; a plan's day: the outline glides, its card slides in (a
  click, no redraw), and ‹ › slide the week; the map's tile grows to fill
  the map, its parts come in (All goes back out); a friend's numbers
  count up and glow; a newly studied square pops; Decks' bars grow in
  when Decks opens; a cheer sent floats up from their row (social.py
  asks once it's sent); ↻ turns while fetching and Updated comes in;
  a bingo stamp presses in, a line's squares ring, BINGO pops; Insights'
  line draws in; studying now breathes (CSS, the one that moves on its
  own). Hints expire in 4 s. The site's board wraps its draw the same
  way. `tools/motion_preview.py` plays each one on the real board.
  Board in Motion, round two (Sam picked all eighteen, and "a fun way to
  animate the logo"). What leaves now goes visibly: `motion.js` keeps a
  leaving thing's markup and place (`spot`: its path, its parent's class
  and heading) and puts it back for a moment after the swap (`putBack`,
  inert, ids stripped, never counted as there), then it folds and the
  rest close up: a banner (a knock, a notice), a note under the box's
  tabs, a face in the room's line (it shrinks out; a face joining comes
  in from the right), a topic in Not sticking yet (its bars shrink, it
  says "sticking now ✓", it folds; the last one brings its section back
  with it; one pushed out by a new topic says nothing), and Behind ("Caught
  up ✓", then gone). Only under the same tab and deck it left from
  (`leave.ctx`), so switching tabs never reads as something going.
  Settings and the board (and a bingo card) slide past each other, the
  board easing to the new height; a sort washes its column green once;
  a Streak cell that grew lets a 🔥 rise; a profile's card grows out of
  the name clicked and goes back into it (the card's script calls
  `dcMotion.open`, which makes its own `remove` the way back, so ✕,
  Escape and a click outside all do); a year's squares fill in as a
  wave, on a profile card and on duecrew.com's year; a plan week's bars
  grow in when Plans opens; a map tile eases into its new shade, its %
  counting there; a new note or banner opens into place; a bingo
  square's rule rises in; a copy says "Copied ✓" on the link itself
  (`ui.copy_text` tells the page, which knows the link clicked; the
  site's copy buttons the same); duecrew.com's sign-in code lands digit
  by digit and says "Signed in ✓"; the builder's calendar slides with ‹ ›
  and a date dragged to another day settles there (chips keyed by unit
  and source, `M.places`/`M.moved`). A friend arrives: the crew this
  profile's board has drawn is kept in wrap.json (`crew_seen`, by
  account, 300 at most; the first time, everyone's known); one new opens
  in with a "new" chip for four seconds (`_arrive_js` after a draw or a
  swap; the site keeps its own in the browser). Study today names the
  deck it opens first ("Study today › Pharm", `due_flow._next_deck`,
  from the deck tree the reviews count already read, so no new query).
  And a memory: Anki draws the Decks screen anew after a review (no
  swap), so `drawn()` (after every draw, `board.MOTION_DRAWN`) keeps
  what the board said in the page's session storage, and the next full
  draw on the same Anki day, within three hours, moves what changed while
  I was away: ticks, bars, counts, the day done, a topic that started
  sticking, Behind caught up (`MEMO`), never a tab, a fold or something
  merely new on screen. The logo: the crew does the wave. Its six studied
  days hop in turn and the day off sits it out ("a day off is fine"), by
  a move alone, never a fill or a shape, so it always lands on the
  artwork. It waves on a hover, with the first board of each Anki day and
  when the day turns Done for today. All of it still stops with Reduce
  motion (a Copied ✓ and a "new" chip still say so, without moving).
  One look for a set of cards (Sam: "the linked card sets appear
  differently on plan vs today/upcoming... pick one style and stick with
  it"): every link that opens cards in Browse (`a.tp`: a topic, "16
  left", "56 cards to see", an Insights topic) is the board's green with
  no underline until hovered, as Today's were; Plans' and Insights' grey
  dotted ones and their own rules are gone. Today writes a group as the
  Plans day does ("**Picked** · 3 single cards", not "Picked: …").
  Its head (Sam: "the exam thing … looks bad"; "the overall deck name
  doesn't show"): the deck's name always shows (one deck, its name; more,
  the picker), and the exam date is a link, Add exam date, that opens the
  date picker; once set it reads "Exam Mon 30 Nov" with × to take it off.
  One Study (3.8.0, Sam: "a ton of study buttons that all do the same
  thing"): the box's Study today, on its folded line too; the Study › on a
  plan's date and on Behind, and the misses suggestion, went (they're the
  walk's first and last steps). Study today opens real decks (Anki's own
  Study Now on each, a parent with its subdecks); only today's misses is
  a filtered deck. The no-jumps hold lets go at once, and on a window
  resize or blur (Sam: "a pretty big delay on window resizing"; the eased
  release lagged). On my own profile card, a studied day opens that Anki
  day's answered cards in Browse (`heatday`). "4 back at 9:42" flips to
  due when they come back while the Decks screen shows it (one timer, the
  earliest, `due_flow._flip_at`). The empty crew box: "Send a friend your
  invite. Once you've added each other, they're here." Recover leeches
  (Sam: "does not work"): it ran only in the morning; switched on, it
  recovers the leeches now, as one undo step, and says how many.
  One Due Crew deck (3.8.0, Sam's pick): the filtered decks Due Crew
  builds (a date's Study, Insights' Study, a checkpoint, today's misses)
  are "Due Crew::…" (`plans.our_deck`), so they fold under one parent in
  Anki's deck list; Anki makes the parent a normal deck. The morning's
  tidy (`plans.tidy`) also takes the parent once it's empty with nothing
  under it, when Due Crew made it (its id kept with the built ones), in
  the same Delete Deck step; old "Due Crew · …" decks still go once empty.
  Checked on Anki's engine (`tools/real_anki.py`).
  A squad's week (3.8.0, Sam's pick): under a squad's table, "Last 7
  days: 23 study days between 5 of you", each member's days of the last
  7 added up (`board.squad_week`, its twin `squadWeek` in app.js), on
  both sides, in the show-up view too. Totals only: nobody's ahead of
  anybody. Nothing new is sent or fetched: it's the rows' week.
  The board's head, option B (3.8.0, Sam's pick of four on the spec:
  "lots of dead white space"): Crew's views (Today · Week · Decks) sit in
  the table's top-left corner, where the header was empty
  (`board._corner`), and a squad's names in its table's. What that
  corner held goes under the table: show-up mode's "N showed up today",
  a squad's headline, then its week and its bingo card. Decks has no
  table, so its picker has a line of its own with the key at its right
  (under the bars when asks come between). With no table (nobody synced,
  loading, a plan's squad) a squad's names stay on top. The same on the
  site (`corner` in app.js). Crew and Share in the footer lost their
  carets (Sam), on both sides.
  The night's review (3.8.0, four reviewers over everything since
  2d4ed86; fixed, each with its test): Insights take the first plan on a
  deck (a second plan's line could Study the first's cards); the map's
  tile cards are found in any alphabet, the Tags way can be picked, a
  pick out of the ways shown falls back to the best, short numbers are
  names; a squad's long name is cut in the corner (its whole name on
  hover); the squad's week counts a sync's days only within the last 7
  (both twins); "N showed up today" reads a friend ahead's day first
  (both); no deck of mine shared says so; show-up mode keeps the
  invite; a second identical line can be ticked (a dot rides in
  commands); Escape stops Study today (Anki's review has no Escape of
  its own); the tidy leaves a "Due Crew" deck the person made; leeches
  are recovered on the Decks screen only; a half-typed to-do survives a
  redraw; a line's words reach Due as served, so ticks match the site's;
  Behind's Browse counts dates as Due does; on a Mac, Ask the squad is
  ⌃⇧Q (⌘⇧Q is the system's Log Out). The Worker: a date can't be
  called "every", twenty new codes a day, housekeeping skips the old
  bridge's cron; the fake answers as it does. The Google project was
  shut down before 3.8.0's Worker went out; the old bridge then fails
  before writing anything (`docs/cloudflare-setup.md`).
  A plan's weekly lines (3.8.0, Sam's pick: "every Fri: practice
  questions"): the doc's `every`, a date's line with its weekdays (six at
  most; `plans.ts` todoLine, `fakes.FakeWorker`, `shapes.clean_plan_doc`).
  Authors add them under the pace in the builder (kind, words, M–S, a
  link); followers see them there. In Due they come on their weekdays
  from the plan's first date as I run it to its last (or its last event,
  or end date; `due_flow.plan_every`), on Today and once in Upcoming, as
  my own repeats do; each is ticked for the day (`duetodo`, its key
  `pid:every:hash`, `due.every_keys`) and never behind. The site's Due
  panel shows them too (`dueEveryOn`, its twin). No new request: they
  ride the plan doc.
  The site, audited (3.8.0): a long word in the rail no longer widens the
  page; Squads hides columns by name (its line spans two, which hid the
  wrong ones under 560 px) and its line wraps; the cheer popup sits on the
  page (the table's scroll box clipped it) and opens upward near the
  bottom; the avatar has no stray ▾; the picker's underline is straight and
  a long squad name ends in an ellipsis; dim rows and faded notes read at
  the muted colour (the faint one was 2.4:1); a lone tile keeps a tile's
  width (the strip still fills its row); the board keeps 300 px so a short
  tab doesn't pull the page up, its footer at the bottom.
  Alone with nothing yet, my row has no medal, on the site and in Anki
  (the twin). The landing picture is the sample crew (it had the stress
  test's row), with a dark one; the README's are re-rendered too.
  Plan tags (3.8.0, Sam's picks on the Plan Tags mock: real tags, owner
  and co-authors only, made in Anki or on duecrew.com, also by an AI):
  a plan carries its own tags (SLG 12) in its doc, `tags` ({id, name,
  notes by guid, or tags/decks/searches it is made from}, 100 at most,
  5,000 notes each, counted into the doc's card ceiling) and `tagroot`,
  the plan's part fixed from its name when the first tag is made (so a
  renamed plan keeps its tags where they are), and its alone: two plans
  followed in one Anki must never share it, so a root another plan holds
  (case aside) makes `_2`, `_3`, with the dates that name it following
  (`plans.tagroot`, unique, migration 0023; `rooted`, `reroot`), and a
  library copy gets its own. In Anki each one is
  `DueCrew::<tagroot>::<name>` (MS2_Block_1::SLG_12); the name as a tag
  part is a twin of three: `plans.ts` tagPart/tagRoot, `plans.tag_part`,
  `Tags.part` in builder.js. The author tags in Browse (right-click ›
  Due Crew: tag for a plan…, `ui/tag_dialog.py`; one request on a click,
  `POST /plans/{id}/tags`, guids only, the plan's log says what changed)
  or on the site (This plan's tags, over What to cover: + puts one on a
  date, Rename and × move or drop it on every date that used it; Text's
  `tag | NAME | …` lines; Text › Tag by objective, a prompt of its own
  with the person's objectives and their own export, never sent to us).
  A follower's Anki writes them as soon as the plan's update is here,
  after the day's AnkiWeb sync and on the Decks screen (a tag on a stale
  note would win over an edit made on the phone), before what opens (a
  date can use a tag): `plans.sync_tags`, one undo step a plan, only
  DueCrew::<that plan> ever touched; renames and removals follow; the
  deck is read only when the tags changed or once an Anki day (a second
  on a big deck). The plan card says "New tags: …" once, with Browse
  them. Stop following asks, with a box ticked, before taking them off;
  a plan gone takes them along. A date's Overlap (and, but not, or) makes
  an Anki search of a plan tag and another (SLG 12 but not Pharm). An
  add-on before 3.8.0 gets no tags but still finds the dates' cards (the
  author's uploaded ids). No new request on refresh or sync: the tags
  ride the plan doc. `tools/real_anki.py` runs it on Anki's engine.
  The author's Anki carries them too (Sam's pick, after the build): the
  plans I write or co-author come on the day's first board with their
  name and own tags (`authored`), and `plan_flow.apply_authored_tags`
  writes them on the deck named like the plan's, at the follower's moment
  and by the same rules, for plans I don't follow (a follow takes them
  over; a plan I no longer write takes them off). So a tag made on the
  site counts in the builder, and its dates' note ids (`send_ids`, sent
  again when tags moved) reach followers on an older add-on. Followers
  see the tags on the plan's page too ("This plan's tags", each with Copy
  search for Browse; `followTags` in builder.js).
  Your own pace (3.8.0, Sam's picks on the Your Own Pace mock): a follow
  says how the plan's cards open, `own` on it (migration 0024; PATCH and
  Follow take it; the refresh's stamp moves with it): on the plan's dates
  (as before), When I'm ready (nothing opens by itself), or When I'm ready
  with the next opening once I've seen 90% of the last one's open cards
  (`P.next_by_itself`, one a morning, only after I've opened one). The plan
  still gives the order; its dates still show as the plan's; mine only.
  You › Plans trades Behind for Up next: Open (the next date, first in
  Anki's line of new cards, one undo step, `open_next`) and Open and study
  (then a Due Crew deck of its new cards, in deck order); the line after
  says what it did with Undo (`own_undo`, while it's Anki's latest step),
  or offers Put back (the last date's unseen cards shut again, never a
  seen one; it's Up next again, and Stop following opens them,
  `put_back_own`). Quiet lines: where the plan's dates are (`P.plan_at`),
  my pace (dates opened in the last 14 days) and, with an exam or an end,
  when that pace opens the last date (`P.finish_check`). A morning at my
  pace opens only what an author adds to dates I opened (`P.own_due`); an
  update asks first, as before. Due shows the dates I opened as today's
  until seen, never Behind or Upcoming. Hold back holds every date I
  haven't opened (`holdable(own=True)`), at Follow and when I switch; back
  on the plan's dates, what's opened by date since asks, as Resume does.
  The plan's ··· menu has How its cards open; Open early steps aside.
  Follow: How its cards open, two choices and the box; starting late isn't
  asked at my pace (earlier dates are just the next ones). The site: a
  follower's plan page says "At your pace · next: …" (from the progress
  Anki syncs) with the same choice, and no on-track line.
  Open from Browse (signed in or not: Anki help): a tag in the sidebar,
  Due Crew: open its cards… (its children too; a gui_hooks sidebar menu),
  or the picked cards, open these…. The sheet counts first (open, open
  already, leeches, which stay; the plans I follow that hold them,
  `ui/open_dialog.py`); First in Anki's line of new cards, ticked
  (`P.first_in_line`: Anki's Reposition, the rest shifted, inside the same
  undo step as the unsuspend); Open and study. Never suspends anything,
  unlike Anki's Toggle Suspend. At my pace, a date now all open counts as
  opened (`_claim_opened`). `tools/real_anki.py` checks first in line and
  its Undo on Anki's engine. No new request: all of it is local but the
  one PATCH of the choice.
  The README (and the AnkiWeb listing, from its tagline down) rewritten
  for 3.8.0: Your crew, Squads and bingo, Your day, Study plans (own
  pace, plan tags, a plan's squad), In Anki's browser, Share; no deck
  named by name. `tools/deploy.sh` deploys production by hand from a
  clean main (migrations, the API, the site, `check_prod.sh`), what the
  tag's job does once its secrets exist.
  A long tag list (after release, site only; an author's plan had 47
  SLG tags): the builder's "This plan's tags" sat in the side column,
  which is sticky, a screen tall and doesn't scroll, so past a dozen tags
  it pushed the rest of the tags and the deck's tree out of reach. The
  list scrolls in its own box now (`.ptlist`, at most 40% of the screen),
  and the side's two lists keep their place through a redraw (`draw()`),
  so Rename or + on a tag low in the list doesn't jump back to the top.
- 3.8.1 plan tags, round two (Sam's picks on the Plan Tags, Round Two
  mock). A video cut to an SLG: a date's `cut: [{tag, in, q}]` keeps a
  deck tag to the cards one of the plan's own tags holds (`in`, its id).
  `q` is the same as an Anki search (both tags) and stays in the date's
  `search`, so a 3.8.0 add-on opens the same cards; the Worker drops a cut
  whose plan tag went and gives the date its whole tag back
  (`planDoc`), a copy's new root reaches it (`reroot`), and `PUT
  /plans/{id}/ids` keeps a cut date's note ids only while its cuts match
  (a fourth item, `[[tag, in]]`). The add-on reads it in the video's row,
  "Cephalosporins · SLG 12" (`P.topic_items`, `nm` set by
  `shapes._plan_tag_refs`). In the builder: the chip's All of it / Only
  SLG 12, Overlap's and with a deck tag, or `tag:PATH in SLG 12` in the
  text; a rename follows it, a deleted tag gives the whole tag back.
  One cloze, not its siblings: a plan tag's `cards: [[guid, ord]]` (5,000
  a tag, counted with its notes into the plan's 50,000). Anki tags notes,
  so the tag goes on their notes; Due Crew reads just those cards
  (`P.plan_tag_cards`: all cards of whole notes and these), on a date and
  in Browse them. A tag line takes `cards:`; Tag for a plan in Browse still
  tags notes. An SLG that changes reaches dates that opened: a date that
  uses plan tags carries a fingerprint of them (`ptv`, in `unit_sig`), and
  what they held when it opened (`pt` in its sources), so opening it again
  opens just what the SLG added (`plan_flow._unit_cids`).
  Taking a tag off: Edit the whole plan names the dates in the text still
  using a tag it takes off (a date's tag, a cut, a search), with Take them
  off those dates too (a tag and its searches go, a cut is its whole tag,
  a date left with nothing goes), Keep the tags (their lines back in the
  text) or Replace anyway. What a date opened stays open.
  What the AI is given: the tagging prompt says the plan's root
  (DueCrew::<root>::NAME), lists the tags as they stand (their lines) and
  the `cards:` rule; Export cards for my AI has a `#cards` column (each
  note's card numbers from 1); the plan prompt gives the cut syntax.
  Insights and plan tags: a plan's DueCrew tags stay out of Insights' own
  picks (`team._ours`: topics and the map's first way); the map's "by"
  gets one way a plan, "<plan>'s tags" (`team_flow._plan_ways`, each tag
  a tile, `team.plan_tiles`), with the tags no card in the deck carries.
  An add-on before 3.8.1 opens a cut by its search, leaves a tag's single
  cards out, and doesn't see a tag made only of single cards.
  Found by the plans review before release (builder): a plan tag inside
  a search is matched whole (`tagRe`, bounded as `reroot` is), so
  renaming SLG 1 no longer rewrites SLG 12; a tag line writes each
  search as its own part, so Edit the whole plan reads it back; a cut
  chip dragged to another day moves as a cut; a cut's search is never
  trimmed off a full date (10 searches and cuts, said); a heavy day's
  Split takes only a whole tag or subdeck; and a redraw keeps the page
  where it was (on a phone the day panel is under the calendar).
  No new request; the Worker changed (deploy it before the add-on).
- 3.8.1, the plans review (the "Plans, Reviewed" page: four readers, every
  finding checked in the code; Sam's calls). A follower's Anki: Hold back's
  yes is its own flag (`hold_yes`); Put back's cards still sit in `held`
  for Stop but are never a yes (one Put back used to hold every later
  date's new cards each morning; a 3.8.0 state counts as a yes on the
  plan's dates, a no at my own pace). A card a date opened is never held,
  even after an author moves it. At my own pace: a plan first seen on a
  computer counts its all-open dates as opened instead of skipping every
  date that passed (`first_here`); an open from Browse claims only the
  dates it opened (`_claim_opened(touched)`); Not today keeps the date
  and opens the author's addition tomorrow; ending a pause doesn't ask;
  the week's Open now is Up next's Open. The morning's Hold back, catch-up
  and review-day steps come before its open, so Not today stays (the
  catch-up's limit was an undo step of its own). A date shut with Edit ›
  Undo offers Open now and opens whole. Move… names its event (by id). The
  3.2 missed-days answer has its own key (`missed`). One name each: Not
  today; Push my dates back; "once I've seen most of the last". Browse's
  authoring items show only for someone who writes a plan. The deck's tag
  tree goes up at the day's first refresh when it changed (`send_trees`,
  `trees_sent`; one PUT a changed deck, `test_request_budget`), and the
  builder says "Tags as of". Export cards for my AI asks for a plan I
  write but don't follow whole (`api.plan`): /plans/mine leaves a date's
  single cards out.
  The Worker: a tag root past `_50` takes the plan's id; a site save keeps
  a date's `ids` only while its tags, subdecks and cuts are the same; a
  post sent with a save that changes nothing is written; the 20 follows
  are those I can see (100 rows in all); each plan's totals (migration
  0025) are read from its row and counted again when over an hour old, so
  a board, the library and a link read one row, not every follower's (an
  author's `reached` and Progress stay live); adding cards from Anki and
  the ids upload have daily limits, and tagging counts the doc kept for
  Undo; Undo survives the author's daily ids upload; the refresh stamp
  covers plans I write and squad offers. The fake matches it.
  duecrew.com: Fill to a date stops there (the pace rises up to about
  double first, then it names what didn't fit); a new plan is named for
  the deck's last part and says why it failed; History › Undo and every
  save reload the pace; Edit the whole plan keeps a moved or renamed
  date's id (followers keep their progress) and reads the part after the
  date as its name; a plan tag's × names its dates first; the server's
  limits are said where they're hit, each refusal in its own words;
  Starts moves review days, events and the end; Move this day merges
  everything; failures say so. Undo (20 steps, Ctrl/Cmd+Z), Follow on a
  plan's link page, "Tags as of". Words: the day panel's refresh line,
  "one of my squads", neutral examples beside the med ones, a review
  day's deck, Progress per date from three in the squad.
  Docs: `docs/plans.md` (how plans work now), duecrew.com/plan-text (the
  text format, linked from the Format box and both prompts), three
  README lines, a date's id fields in the Worker README; no third-party
  deck named in the design notes, the click-test or the preview's data.
- 3.8.1, plans round three (Sam's eight picks on the "Plans, Round Three"
  mock, an outside reviewer's six notes, and Study on a date; built by
  four builders on one contract, then joined). Co-authors say yes first
  (migration 0026: `plan_editors.accepted_at`, `plans.handover`): an
  invite is nothing until a yes (no saves, no tags in their Anki, not in
  the library), shown on the day's first board (`planInvites`, Yes and No
  above the plans; Home on the site); an owner can hand the plan to a
  co-author who said yes, who says yes too, and the code, tag root and
  followers stay. Where to get the deck: an https link on the plan
  (`deckUrl`), on its page, poster and in Follow when no deck has its name.
  Notes for followers (`remarks`, in the doc): on a tag (under its topic
  in Anki, an ⓘ on the site) or one card (on the review screen when it
  comes up), written on the site, in Text (`note | tag:… | …`) or from
  Browse; an edited card note keeps its id. Picked cards keep their
  resource's name (`pl` from the author's Anki, `#lbl` on the ids upload,
  the board's authored plans now carrying single cards): "Herpes Viruses ·
  88 picked". A deck tag with an Extra part shows "64 + 22 extra" with
  With extras / Without. Revisions read as revisions: "updated Fri 16 Oct",
  "renamed 10 tags" (a renamed tag matched by what it holds keeps its id).
  A date that opens after its event is reinforcement, "after Heme quiz",
  and no prep day. Export cards for my AI starts with the plan (dates in
  the text format, tags, overlaps, notes; never card text). First steps
  on an empty plan. A follower's day: Welcome back (3 days with no study:
  Open them, Push my dates back, Not today), what the morning opened by
  date (each opens Browse), what Hold back keeps (Open them, Stop holding
  back), why a date left cards shut (leeches, picks not in this copy),
  any date in Up next opens at once with Undo, Study on every date (a
  random cram of its open cards, one undo step), and a day's line keeps
  what the plan opens apart from my own reviews. Anki's new filtered deck
  came with a second search (20 new cards of the current deck) that went
  into every Due Crew deck since 3.8.0; it's gone.
- 3.8.1, plans rethought (the "Plans, Rethought" page: where plans fail,
  five rules, moves mocked for Sam's call). Built: the builder reads a
  day's work, each date spread over the study days to its due date
  (`Work` in builder.js), so a week's date isn't "212 new on Monday"; the
  heavy note names the date most to blame with Split or Give it till, and
  every day's bar is its share. A date the author named shows its name
  above its chips; a tag's last word the deck has twice reads with its
  parent. A named date's day panel suggests the deck's tags its name
  points at (`Suggest`; words, never card text). Study for a quiz: from
  three days out, one deck of its prep dates' open cards, the shakiest
  first (`plans.quiz`, `planquiz:`). The morning keeps the plan docs it
  has: `same=1` on the day's first board, and an unmoved stamp sends each
  plan without its doc (a doc not kept here lets the stamp go).
  Two review rounds, fixed with tests: the add-on uses its kept docs only
  if the same add-on version kept them (`plans_by`), so an update that
  cleans docs differently fetches them whole once. The stamp names each
  plan's owner, so a hand-over reaches followers. An answer to an invite
  says which question it answers (`kind`), so a stale "co-write?" Yes
  never takes the plan. A hand-over drops the plan's pending invites and
  counts the new owner's listed plans and Undo copies. Invites have a
  ceiling, and a plan is offered only to a co-author who said yes. A deck
  link is printable ASCII. Hold back's sheet counts only cards still held
  (not ones on a date that opened). Study for a quiz takes only dates
  open by today. Editing a note never deletes it. A day's line says
  "opens N cards". The builder's suggestions keep a tag's numbers ("Week
  2"), a renamed tag's text follows it in the description, and Without
  extras keeps the tag.

- 3.8.1, the outside audit of 3.8.0 (ten findings, each checked against the
  code; #6, the default ranking, is Sam's call and stays). Mute is a block
  on the server too: a muted person's cheer reads as sent and goes nowhere,
  one waiting from before is dropped as read (the site's home showed it),
  and their knocks aren't listed (`mutedBy` in social.ts reads the `muted`
  list in my settings; the home feed already did). Knocks have ceilings:
  60 an hour a sender, one a day a pair, so a dismissed one isn't back
  within the day. Reports are kept for the admin's Inbox (`reports.ts`,
  migration 0027, 180 days, gone with either account, in Your data):
  without `REPORT_TO` they went nowhere while the reporter was told they
  were sent, and a mail that fails no longer fails the report. The site's
  sign-in says what went wrong (the mail being down isn't "that doesn't
  look like an email address"), sends one code a click, and the code box
  tells an outage from a miss; Anki's sign-in says the same about mail.
  Joining a squad on the site writes the settings only over a read that
  worked (a failed read wrote a doc of squads alone over everything). On a
  phone, the home puts people first: the board, what friends said, the
  invite box, then my own panels, my year last, and the board is as tall
  as its rows. `tools/real_anki.py` exits non-zero on any FAIL. A tag pass
  reads a deck once for every plan on it (`plan_flow._deck_index`),
  fresh again after a plan's tags move notes.
  Settings merge across computers (the audit's #2, migration 0028): a save
  replaced the whole doc, so two computers (or a computer and the site)
  saving close together lost one side's change, and the server kept
  whichever came last. Each save now moves `rev`; a save names the rev it
  started from (`base`), and one made over an older rev is turned away
  with the doc as it is (409). The add-on merges from the save both
  started from (`account.merge3`, kept in the session as `settings_base`):
  a key one side changed takes that side's; the muted, squads, shared
  decks and to-dos merge item by item (what one side added stays, what
  one side took off goes), ticks day by day; anything both changed takes
  the save being made now. An edit here not yet up when a pull brings a
  save from elsewhere merges the same way. Older add-ons and a sync's
  settings save without `base` and win as before; against a Worker before
  3.8.1 the add-on saves again without it. The site's squad join saves
  over the rev it read and redoes it once on a 409. And the study room's
  rings all fill as their time passes, a break's too (on the Decks screen
  the top bar's chip filled while the board's drained); the number is
  what's left.
  The room's card pops out at the chip's end of the screen (Sam: with the
  chip on the left it opened on the right), the chip hides while it's out
  (`rooms._little_shown`; the card says `roomcardoff` as it closes, and a
  redraw that finds the page took the card along brings the chip back),
  and it moves by its top row, kept on screen and remembered per side.
- 3.8.1, the Fifteen and Sev (the "Fifteen, Sev, Buddies" and "Sev Design"
  pages; Sam's picks). ▶ Fifteen? sits at the chip's end of Anki's top
  bar whenever I'm in no room, and the You box asks "Not started yet
  today. Fifteen?" once a day, only when nothing's studied, something's
  due and it's past my usual start (the middle of my first answers over
  the last two weeks, from three days of them; never on away days; ×
  says Not today). Start makes a fifteen (`room_model.make_fifteen`: a
  room of kind fifteen, 15 + 5, one round) and Study today opens. When
  the fifteen ends, once the card in front of me is answered, one
  question takes the next card's place, the break's way: Take five, then
  another fifteen (a round more after five minutes from the fifteen's
  end: the question waits those five, `ASK`); Another fifteen now (the
  start moves back so the next starts this minute: it's mine alone, so
  nobody holds the old one); Stop here. Each yes adds one, up to the
  room's eight. No answer in five minutes and it ends quietly, with the
  same line as a stop (Sam: no "it still counts", on the question or
  after). The Decks screen's lobby asks it too (the chip's clock tells
  the board when a phase changes, `roomtick`), and so does the chip's
  card. A fifteen never rides my week doc as a room (nobody joins one
  yet: the buddy comes later): my crew sees I'm studying now, to the end
  of its question (`room_model.live_until`), so a start, each yes and a
  stop are one write each, and its breaks cost no refresh. The end is a
  line on the board, a day long: fifteens begun, minutes in them, cards
  answered since the start. room_model.phase and the widgets' JS gained
  the question (`ask`) together; `test_fifteen_js_phase_matches_v381`
  runs both.
  Sev is Block (no belt, big round eyes, stubby arms, cheeks only when a
  cheer lands), drawn once by `sev.py`: the board draws it, and the
  widgets get its markup as data, so there's no JS twin. Every pose
  draws the same named parts and one sheet moves them; a moment that
  happens once (a hop, a cheer, the clock) plays once and rests when
  drawn again; a state (a nap, heads down, a break) loops gently. The
  still frame is the markup, and motion lives under the computer's own
  Reduce motion (Anki's is on unless switched off, so it isn't asked:
  Sam's call). Beside the logo, never on it, and only for a moment (Sam:
  not always there): something just happened (a cheer landed, the first
  day back from away, exam eve, the day done: the week's squares fly,
  Thursday's grey), the first time the board draws it; it pops in, plays
  it and goes after `sev.LOGO_SECONDS` (a redraw meanwhile keeps its
  place), and the logo's alone the rest of the time. In a fifteen: a jump to start,
  heads down (a blink every seven seconds, eyes along its card, the card
  turns now and then), the clock at the question, breathing along with
  the break (a square, four counts a side) or stretching, a square on
  its head for each fifteen at the end. Settings › Fifteen and Sev: the
  top bar's Fifteen? (and the nudge), Sev, and the break's Breathe or
  Stretch, all on this computer. Sev on crew rows was mocked on the real
  board and Sam said no: rows have emojis, and Sevs that differ only by
  colour would need to be more customisable to stand for people. Not
  yet: the buddy (Sam: still not there).
  In a room with my crew, each member is their Sev (Sam's pick): on the
  room's card and the Decks screen's lobby, where the initials were, each
  in its person's accent (by day or by night, as the widget or the board
  picks mine), and they started at different moments, so the blinks never
  line up (`sev.started`, each its own place in the blink, `--sv-d`;
  idle, still under Reduce motion). The accent rides `GET /board`, a
  mutual friend's only, from their settings in the friends query (no
  request, reads only, bounded by the crew); `shapes.clean_accent` keeps
  only one of ours and `board.accent_pair` makes it colours (anything
  else, the default's), so only those reach a style; a name is only a
  seat's label, as text. Sev off, or a fifteen (no members): the initials
  as before; the chip, the margin and the break keep them
  (`room_model.seats`, `test_crew_room_sevs_wear_their_accents_v381`).
  The privacy page says the crew sees my accent.
  Sev's spacing (Sam: review it wherever it shows): its body sits low in
  its drawing (the effects need the room above), so a box the drawing's
  size left it low and loose: 3 to 6 px under its neighbours' middle,
  nearly touching a chip's bottom edge, gaps that changed with the pose.
  It goes in a slot its body fills now (`sev.SLOT`, `sev.slot`, the same
  numbers in the widgets), and centres on its neighbours within a pixel
  on the board and in the top bar's and review bar's chips. The question
  and the break leave room under Sev's shadow; beside the logo it's a
  size smaller, its feet on the logo's line.
  ▶ Fifteen? clicked to nothing (Sam, in Anki): Anki tags the top bar's
  messages with a `TopToolbar` (a wrapper `Toolbar.draw` makes), and
  `_our_page` knew only `Toolbar`, so the top bar got a card page's rules
  and only the widgets' keyed commands passed; `room15` and the chip's
  `roomtick` were dropped. `TopToolbar` counts now, and the suite sends
  both from one (`test_top_bar_is_our_page_v381`); nothing had sent from
  the top bar as Anki tags it, which is how the suite missed it. Also: rooms.py
  asks one clock (`rooms._now`) whether a room is over, so the suite's
  fixed clock holds on any real date. Find a setting knows the new rows
  by other words too (timer, pomodoro, mascot, stretch: `FIND_WORDS`),
  and `tools/motion_preview.py` plays Sev's moments by the logo and the
  session's line. The session's line (Sam: funky spacing) kept 26 px
  over Sev for a full stack and its sparks, so one square left a gap on
  top and the words sat low. Its Sev is padded by what's drawn now
  (`sev.stack_reach`: one square or three, and the shadow), so the box
  has its own even padding (8.6 px over the stack and under the shadow)
  and the words and × centre on Sev and its stack together; its words
  are left-aligned when they wrap. The sparks as the stack lands are
  gone once it rests, and in the still frame, as the motion ends.
  The week card (Sam's pick, "Sev hops across the week"): Sev lands on
  the days I studied and hops over the rest. A picture is still, so the
  hops are its trail, a dotted arc from each day studied to the next
  (short between neighbours, long over days off, none over days to
  come), and Sev stands on the last day studied so far, in the card's
  accent. Today's card has Sev on today's square once it's studied, no
  arcs. Nothing studied, no Sev: the card is as it was; with Sev the
  story's squares and the numbers under them move down
  (`sharecard.ROOM`), every word kept, and a link has room above its
  squares already. `sev.still` is the one drawing, an SVG of its own with
  the colours given: Qt draws it with QtSvg, and cards.js keeps a copy
  (checked to the byte) it draws on the canvas from a data URL; Share,
  Copy picture and Download wait until it's drawn. Where things go is the
  twins' (`sharecard.landings`, `hops` ↔ `landings`, `hops` in cards.js,
  each dot by the same arithmetic); `test_week_card_sev_v381` runs both.
  In Anki the card follows Settings › Sev; the site has no switch and
  always draws it.
  Welcome back (Sam's pick, from the same mock): the window a plan's
  follower gets after three or more days away has Sev waving from its
  top left, still (a Qt window can't play the board's motion; it's the
  frame Reduce motion shows), in the accent and Anki's theme:
  `ui.sev_label` draws `sev.still` through the logo's SVG path
  (`ui._svg_pixmap`, which `logo_label` uses now too). Same words and
  buttons; Settings › Sev off, the window as it was (`plan_flow._ask_away`
  passes `sev_on()`). And the fifteen's question with Sev off showed no
  squares: its else sat inside a `//` comment (found merging the room
  seats); it draws the logo's squares now, as the checklist says.
  "Today's misses" built a deck nobody asked for (Sam, after a Fifteen):
  Study today's last step made `Due Crew::Today's misses` from every card
  answered Again today (352 of them), and a Fifteen starts Study today, so
  with nothing else due its first step built the deck and opened it,
  unsaid; the morning's tidy only clears empty decks, so it stayed, its
  cards out of their decks, rescheduling as they were studied. Sam's
  call: the walk has no misses step now (`due.study_next(plans, due)`,
  plans' decks, then the most due, then done), and it never builds a
  deck; going over the misses is the Today box's suggestion, a click that
  says so, which notes its day (`misses_day`, plans.json); a misses deck
  left from an earlier day is emptied back into its decks the next
  morning (`tidy_decks`, Anki's Empty) and goes with the tidy. A fifteen's
  card: the logo's squares head it again, as a room's, and Sev sits at
  the end of the clock's row, centred on the ring (Sam: its spacing was
  off in the header); "then your call" is gone from the card, the lobby
  and the chip (done), as exposition.
  Sev's places, Sam's picks (the "Sev's Places" mock, on the real board):
  two new places, and more moves (Sam: "variety!") wherever it already
  is. Signed out, Sev waves beside the card's words until you start
  (`board.signed_out_card(sev=)`, `rooms.signed_out_sev`: a hello from
  its mix the first time it's drawn while Anki's open, then it rests);
  not on an expired sign-in or a deleted account, which say just what
  happened. A crewmate's 100-day (or year) streak: the banner's emoji
  becomes Sev hopping (`rooms.milestone_sevs`, `render(milestone_sev=)`),
  once a banner, then it rests; Send 💯 as it was. The rest of the mock's
  places were a no (the day you join, following no plan, bingo, done for
  today, couldn't sync, the welcome screen, the year card, duecrew.com).
  The moves are `sev.MOVES`, each place's own first: the day done (hop,
  twirl, a little dance, a big jump), a cheer (catches it, hugs the gift,
  spins with it), back from away (pops in, walks in, up from below), exam
  eve (fingers crossed, a pep fist), a fifteen (reads, nods along,
  scratches its head, taps a foot), a break (stretch, shakes it out,
  marches, looks around), the question (the clock rings, points at it,
  jumps at it), the session's line (squares land, the tower wobbles,
  steps under them), the nudge (peeks, knocks, bobs up twice), and a
  room's seats (`SEAT_MOVES`: blinks, reads, nods, reaches, looks around).
  Each time Sev comes it plays a different one, never the same twice in a
  row: by the logo, the streak banner, the session's line and signed out
  it's `sev.pick` (at random, not the last), picked once a showing; the
  last kept with the session (`sev_last`) so a restart doesn't repeat it
  either. Where it stays a while it takes turns (`sev.nth`): a fifteen's
  heads-down, its break's stretch and its question change each round (the
  widgets' `vk` and the board's line, `room_model.vary_seed` the same on
  both), the nudge each day, a room's seats one each, side by side never
  the same. On a break the moves rotate only with Settings › On a break ›
  Stretch; Breathe stays itself. All transforms and opacity, each with
  its still frame for Reduce motion; and drawn again, a Sev that played
  rests with Reduce motion on too (landed, what flew gone), so a banner
  that stays isn't left mid-hop.

- 3.8.2, Pip's closet (the "Fun Round" page, round two; Sam: "costumes tied
  to achievements ... more more more", then "make sure someone can't enable
  multiple costumes at a time that conflict, one should replace the
  other"). 61 things Pip earns, `closet.THINGS` (the drawings in
  `closet_art`), in groups: showing up (days studied, days in a row,
  mornings before 8, evenings after 9, nothing left due seven days
  running, a whole Anki life's reviews, cards learned), Fifteens, the crew
  (a crewmate, a cheer landing, a room together, a day the whole crew
  studied, ten crewmates cheered, a 100-day streak cheered, cheers on 30
  days), squads (joined, a bingo line, a whole card, started one), plans
  (followed, every date done, exam and all), coming back (after a week,
  a month), card care (cards you added, leeches turned around: a card
  that lapsed 8 times now three weeks or more between reviews), the
  seasons (Halloween week a thing a day for five days, winter, the
  longest night, New Year, Friends' day, spring, summer: studied on the
  day, any year) and five secrets (Pi day, a Friday the 13th, a year with
  your Pip, the year turning, a leap day; a question mark until found).
  Never for getting cards right (Again stays honest), never for one big
  day, never bought, never taken away. Five more (a viking helmet, a book,
  a watch, the knight, the beast hood) wait for the Beast and Crew Town.
  A look is one thing in each place (`closet.SLOTS`: back, body, face,
  head, hand): `closet.wear` puts a thing on in place of whatever was
  there, a thing that reaches into another place takes it too (winter's
  earmuffs come with a scarf: `also`), and a costume covers the look,
  one at a time (a second replaces the first), the look waiting under it
  to come back when it comes off; anything else put on takes the costume
  off. `closet.clean` makes any look follow the same rules (an old one, a
  crewmate's off the server), `closet.shown` what shows. Pip wears it
  (`sev.svg(look=)`, `sev.still(look=)`): the back behind the body, the
  rest over it, and what it holds in the right arm (`sev._arms(pose,
  hand)`), so it follows a wave and stays upright; a pose whose hands are
  full (a card, the clock, the gift, the case, fingers crossed) holds its
  own (`sev.busy`). To let the arm hold something, the arms turn at their
  own origin (`transform-box: view-box`), pixel for pixel the same as
  before. What's earned is worked out here (`closet_flow`): the revlog's
  days and hours in one grouped query a day (today's read fresh), cards
  learned and leeches turned around (one query each), the board's crew,
  squads and plans, and tallies this computer keeps in wrap.json's
  "closet" (Fifteens, rooms with the crew, cheers sent and got, cards
  added in the Add window, days with nothing left due, bingo lines).
  `closet_flow.check` at each refresh adds what's new to the account's
  `sev_closet` ({thing: day}; one settings save, only when there's
  something), and the board says so in one line (`board.closet_line`:
  Wear it, or Be one, and the closet); the day it comes, one line for
  everything your days had already earned. `sev_look` and `sev_closet`
  are account keys: `account.merge3` merges two computers' closets thing
  by thing (nothing earned is lost) and takes my look. The look rides
  with the accent to mutual friends: `board.ts` `lookOf` (a handful of
  names, nothing else), the fake, `consent.test.ts`. The closet opens in
  place of the board, as Settings does (`board.closet_html`, the
  `closet*` commands). After Sam's first click-test ("the distinction
  between which items are active vs inactive aren't really that clear"),
  it's in two: Yours, your things by place on Pip, head to back and then
  the costumes, one at a time in each place, each tile saying what earned
  it; what's on is the accent, filled, with a tick (On), a thing a
  costume covers says Under, a new one New; a place with nothing yet says
  what's next. To earn: what you're close to (`closet.near`), then every
  thing you haven't got by how it's earned, greyed, with how far along
  (`closet.progress`), never a button (no try-on: Sam's call, nothing is
  worn before it's earned); secrets a question mark. On the left, your
  Pip big and what's on, place by place, each taking it off; Take it all
  off. No explainer under it (Sam: "too explainy"). Ways in: Settings ›
  Fifteen and Pip › Pip's closet, Tools › Due Crew › Pip's closet, your
  Pip (by the logo, on your row, on your card), the board's line. Your Pip
  wears your look wherever it shows (by the logo, ▶ Fifteen? in the top
  bar, the nudge, the session's line, a fifteen's chip, question and
  break, the signed-out card, Welcome back, the week picture card made in
  Anki), a crewmate's wears theirs (a room's seats, the streak banner),
  and crew rows and profile cards (`board.card_sev`) show each person's
  Pip in the emoji's place, in their colour and look (Sam: "move away
  from emojis toward Pips"; `board.row_sev`); with Pip off in Settings,
  the emoji as before. Your card keeps Change emoji (squads, bingo and
  older add-ons still show it) beside Pip's closet. A row with a Pip is a
  little taller (`tr.sv`): the name's cell clips what spills out, so a
  hat needs the room, and the whole row gets it so the name and the
  numbers stay on one line; Pip sits clear of the name, outside its
  underline. The site's picture cards keep the plain Pip (cards.js).

  Then, before it shipped: Sev is Pip (Sam's pick, from "Pip, Sevvy,
  Cubby, Bean, Moss": a pip is a little square, like the seven days in
  the logo). Everywhere a person reads it, in Anki, on the site, the
  README and the privacy page; the code keeps `sev` (sev.py, the `sev`,
  `sev_look`, `sev_closet` and `sev_break` keys, the `.sv` classes,
  sev.js's `Sev`), since the switch and the break shipped in 3.8.1 and
  renaming a key would reset them. And a held thing never just goes: while
  Pip's hands are full (the card in a fifteen, the clock, a gift) it's set
  down on the ground beside it (`closet.art`, `DOWN`), so a fifteen keeps
  the mug in view (Sam: "the thing in Pip's hand gets removed"). The
  ▶ Fifteen? chip and a fifteen's chips give Pip room so what it holds,
  or a costume's tail, clears the ▶ and the clock; a profile card puts Pip
  beside the name's line, the name and the streak on one baseline. The
  README's board picture is re-rendered with the crew's Pips.

- 3.8.21, Pips on Squads (Sam: "squads page still has the old emojis and
  not the new pips"). The Squads tab's people are Pips, as Crew's are: a
  squad's table, a plan's squad's faces (a size up) and who asked in its
  threads. Mine wears my colour and look; a crewmate's wears theirs, from
  the crew the board already has (`board.squad_pip`, `_squads_html`'s
  `crew_by`); anyone else is a plain Pip in the default colour, since a
  squadmate who isn't a mutual friend shares a name and an emoji, nothing
  more, and that's all they get here too. Nothing new is asked of the
  server. Pip off, the emojis as before. The site the same (`squadPip` in
  app.js's `Board`, `on.pip` into builder.js's `PlanSquad.view`). And in a
  study room (Sam, on the top bar's chip: "no pips here either!"): every
  room widget that showed initials shows each person's Pip, in their colour
  and look, as the room's card and the Decks lobby already did: the top
  bar's chip (four, then +N, so it never crowds the bar), the margin card
  beside the card and the break (everyone, wrapping, with room above for a
  hat). One helper draws them (`people` in `room_model`'s widget runtime),
  each Pip's slot the size of the face it replaces; the gap between them
  grows with their size, so a held mug clears the next one. Pip off, the
  initials as before. README's room picture re-rendered from the widget.

- 3.8.22, Pips on a plan card's squad line (Sam: "under squad we haven't
  switched to pips"). You › Plans, a plan's card: "Squad: N of M showed
  up" now leads with who showed up as their Pips, as on the Squads tab:
  mine in my look (it opens the closet), a crewmate's in their colour and
  look, anyone else plain. The board's summary of each plan squad I'm in
  carried only the emojis of who showed up, so it now names whose they
  are too (`who`, their uids, one for one with `faces`; the squad's own
  view already gives its members each other's uids). Still one request:
  it rides `GET /board`'s `teams`. The crew is the board's own entries
  (`you_html`'s `people`, down to `board._squad_line`). Pip off, or an
  older server without `who`, the emojis as before; an older add-on reads
  `faces` alone. The Pips sit a little above the line's text, so a hat
  clears the line before it.
  Then the rest (Sam: "all the places where there are emojis we should
  reflect pips, including bottom bars, we can make the bingo stamps bigger.
  remove emojis from the friends dialog. invites and text shares can stay
  as is"): the review screen's chip, in the bottom bar and as the card in
  the corner, leads "Dre knows this" and "Dre asked about this" with Dre's
  Pip (`cards.pips_by_uid`, `chip_view`'s `pips`; sev.py's own markup, a
  name only in its escaped label, its motion sheet carried once); a
  squadmate's card (not crew) has a plain Pip, as the Squads tab does;
  Settings › You shows my Pip, opening the closet (Emoji… stays: it shows
  with Pip off and in text shares); squad bingo's stamps are Pips, a size
  up from the emoji (`stamp_pip`, never a link inside the square's
  button); the Friends dialog lists names alone. duecrew.com: my Pip tops
  the account page, and a crewmate's leads "added you back" and their
  exam's Send good luck (`pipFor` in app.js, as `squadPip` draws them).
  Invites, text shares, cheers (the emoji someone sent) and the admin
  pages (a report can be about an emoji) keep their emojis. Pip off: the
  emojis everywhere, as before.
  Then three of the fun round's third round (Sam's picks; the round's page
  went deep on Wrapped, the Beast and Crew Town and mocked the rest):
  Halloween week, 24 to 31 Oct, shipped before the 24th: a line under the
  board's head with this week's days and the closet's five Halloween
  things in order (mine in colour), the next and when ("study today for
  the witch hat", "tomorrow: the bat wings"; `closet.halloween`, from my
  row's eight days, which are the whole week); three bats across that line
  on the day's first board, never over the logo, still with Reduce motion
  (`closet_flow.halloween_view`'s `bats`, kept like Pip by the logo's
  moment); and when every Pip on the crew's rows has a Halloween thing on
  (`closet.spooky`; a crewmate who isn't a mutual friend is a plain Pip, so
  never), a cobweb in its corner and "A spooky crew: all N of you dressed
  up." Its × hides it till next year (wrap.json `hw_hidden`; the closet
  keeps the things). Pip off, none of it. Cheers with Pips: when cheers
  land, each sender's Pip rises from the board's bottom edge in turn
  (three at most, in the order they came), tosses its cheer onto my row
  (a little burst, the row lit for a moment) and ducks back down, in place
  of the flurry; the banner names them in order, "Dre, Mo, Ana and 2 more"
  (`board.cheer_pips`, `and_more`, `flurry_js`'s `pips`). A cheer lands
  only from someone I added: a mutual friend comes in their colour and
  look, anyone else plain. With Reduce motion the Pips stand still in the
  banner. Pip off, the flurry as before. And the year counts (Sam: "Start
  the year counts in the next release: Yes"), so the first Wrapped has
  more than Anki's history: the closet's tallies keep a year too (wrap.json
  `closet.years`, six at most): Fifteens and the hour each began, rooms
  with the crew, cheers sent (new) and got, crew days, each squad card's
  lines (its most, once), and the days each thing Pip had on was worn
  (new, once a day). Nothing of it is sent.

- 3.9.0, your Wrapped (Sam's pick, the fun round's third round: "Build ·
  Start the year counts · Show the card you turned around, here only ·
  Night owl or early bird · Past years from Anki's history · 1 Dec to 15
  Jan"). Your own year as a short story, in the board's place (as the
  closet is): the board's line from 1 December to 15 January ("Your 2026
  so far is ready"; its x is for the year, on every computer: the
  account's `wrapped_seen`), and Tools › Due Crew › Your year… any time,
  any year Anki's history has. Made on this computer from one grouped query
  over the year's reviews (an hour a row; new cards met are first answers)
  and the year counts above; nothing is sent. Only the slides a year can
  fill (`wrapped.SLIDES` says when each is made): the cover (or "You and
  Anki met on…"), days with the year's squares and the steadiest month,
  the longest run (gold on the squares; "and still going"), coming back
  (nine weeks away gets its own big slide, and the days that followed when
  most were studied), night owl or early bird (30 days or more, half the
  reviews either side), the cards, the card you turned around (its front,
  plain text, drawn here and never on the picture; a switch on the page
  leaves it out), Fifteens and their favourite hour, Pip's things and what
  was worn most, you and your crew (your own numbers only), the beasts you
  beat, and the picture: days, longest run, reviews (or new cards), and
  Make the picture, the year card, made in Anki, with Pip hopping on it
  now (`sharecard.year`'s `sev`, cards.js the same). Kind, always: no
  missed days, no "fewer", no comparing; a test reads every slide of
  three made-up years for the words it never says (`wrapped.SAD`). The
  slides Due Crew only began counting in October say "Since October". It
  moves on by itself and waits under the pointer; the sides and the arrow
  keys move it; Reduce motion never moves it on; All on one page lists
  every slide as text (`board.wrapped_html`, `wrapped_js`, said to the
  page after each draw; `wrapped.py` pure, `wrapped_flow.py` the glue).
- 3.9.0, the Backlog Beast, yours (Sam's pick, round three: "Build ·
  Yours · Rule B · My beast on to start · Steady · In parts of three
  weeks"). When the overdue pile gets real it turns up as a creature
  whose kind says why the pile built (`beast.KINDS`: the Snoozasaurus after
  a week or more away, the Overdue Owl when half its cards are two weeks
  late, the Leech Lord when one in seven is a leech, the Pile at five usual
  days, the Backlog Beast otherwise). The pile is review cards due before
  today in decks studied in the last 30 days (a card in a filtered deck by
  its home's due), never new or learning ones. Rule B (the round's
  simulation: rule A was seven beasts in four months for someone on and
  off): two usual days (the middle of the days studied in the last four
  weeks) and 100 cards or more, a week after the last one left, never
  away or paused; looked for once an Anki day, after the day's AnkiWeb
  sync, as the plans' morning waits. It never grows: its cards are the
  ones overdue that morning, the most overdue for their interval first,
  at most three weeks of half a usual day (the rest after its rest). A
  card's a hit once Anki moves it to tomorrow or later, on any device
  (below: Sam's rule, 16 Oct); a card suspended, deleted or
  made new leaves it without a hit, and half gone that way it wanders off.
  Study them is a Due Crew deck of its cards not yet moved on, up to 200
  (`beast_flow.OPEN_MAX`), most overdue first (Anki's relative-overdue
  order, found by its name: Anki renumbered the orders, and on 26.09 the
  old number is retrievability, which builds nothing on SM-2, as
  `tools/real_anki.py` caught; one undo step; a deck left at the next
  morning is emptied back, as Today's misses is). As many as you like:
  there's no day's share. It breaks up as it's beaten (a horn at a quarter,
  the other at half with a sweat, dizzy at three quarters, smaller all the
  way; `beast_art`), and beaten it's a pet: on its page, on
  Wrapped's beasts slide, and the closet's three new things (the beast
  hood, the viking helmet at five, the knight at ten; Beasts is a group).
  Let it go: it waves and leaves, nobody's told. Where it is: a card in
  the You bubble on every tab (small on the folded line; the beast
  breathing, and a click anywhere on it but Study them opens its page),
  its page in the board's place (`board.beast_html`: the beast, one line
  of what it is, its health, Study them, Let it go and How it works'
  three lines), the switches in Settings (Board › Backlog beasts;
  Privacy › My beast). What's sent:
  with My beast on, my week's `beast` is its kind and how far
  (`beast.week_field`), never its size or its cards; a crewmate's shows
  after their name as the last thing a chip says (`board.beast_chip` ↔
  `beastChip` in app.js, its drawing from sev.js's kit), and a beaten one
  is a banner for two days with a cheer (a trophy). The account keeps the
  beast (`beast`: the one now and the last 50 met; `account.merge3` merges
  two computers' by `beast.merge`), so every computer has the same one;
  its cards stay here (`user_files/<profile>/beast.json`), and another
  computer works them out from Anki's history for that morning. Its hits
  are counted on each computer from Anki's history and never saved, so a
  review costs no request: the account is written when it comes and when
  it ends. The Worker checks the week's `beast` (validate.ts,
  the fake the same); an older Worker that refuses it gets the week
  without it, so deploy the Worker first. `beast.py` pure, `beast_flow.py`
  the glue, `beast_art.py` the drawings.
- 3.9.0, cheers land everywhere (Sam, 16 Oct: the Pips tossing a cheer
  were "less exciting", then "a different cheer every time, but ... the
  whole anki decks screen", "Tons of options! Tons of fun!"; his picks
  from the mock "Cheers, everywhere"). A landing cheer is a show over the
  whole Decks page (deck list and board, a fixed layer under Anki's top
  bar, which is its own page): the confetti cannon, the piñata (no
  "CRACK!"), fireworks (no name in the middle), a present to open, bubbles
  to pop, the deck wave, balloons, a rocket, a rubber stamp, the disco
  ball, the magic hat, the snow globe. `shows.next_show` deals them from a
  bag kept in this computer's config (`cheer_bag`): every one before any
  repeats, never the same twice in a row. `show.js` draws them with the
  senders' real Pips (`cheer_pips` now brings four poses, a first name and
  their note, which go in as text), three at most, so three cheers is the
  big version. `flurry_js` starts it in place of the toss, its banner (the
  names, the notes, send one back) at the top; a click anywhere but a
  present or a bubble, or Esc, ends it, and each ends on its own (a
  present nobody opens opens itself). Reduce motion: the Pips still in the
  banner, as before; Pip off: the flurry. Nothing new is sent.
  `tools/show_preview.py` plays each on a page like the Decks screen with
  the real board. The README's cheer picture is the balloons now.
- 3.9.0, the closet has the colour (Sam, 16 Oct: "add pip / overall
  color change to the closet page so people can more easily access
  overall color change stuff"). Under Pip on the closet page, Colour
  ("Pip and your board"): the accent's swatches, the same ones as
  Settings › Board (`board._accent_swatches`, one markup for both) and
  the same `set:accent` click, which redraws the closet in the new colour.
- 3.9.0, the review chip's Pip has room (Sam, 16 Oct: "this button is a
  bit too compact for the pip"). The bar chip was 18px tall with Pip
  pulled up into its border; with a Pip it pads to 30px and Pip sits in
  it head to feet (`cards._CHIP_JS`). The card-corner one had room.
- 3.9.0, a hit is a card moved to tomorrow (Sam, 16 Oct: "the beast gets
  beaten when the cards are moved to at least tomorrow"). Any review used
  to knock it, Again too; now a card is off the beast once Anki has it
  due tomorrow or later (`beast_flow.count`): a review since its morning
  that Anki logged a day or more ahead (Hard, Good, Easy; Again logs a
  step in seconds, so it counts once the card is got right), or the card
  due tomorrow or later now (Set due date, a relearning step of a day).
  The first keeps counting when the card comes due again later, so the
  beast never heals; a preview deck's review (ivl 0) moves nothing.
  `tools/real_anki.py` answers its cards with Anki's own scheduler to
  prove each case. Overdue is said plainly too: "due before today". The
  kinds' lines say why it came, the Pile's and the Backlog Beast's in
  your usual days ("380 overdue cards: about 3 days of your usual
  reviews."; `beast.subtitle`), from the mock "The Beast, plainly".
- 3.9.0, the beast made plain (Sam, 16 Oct, on the click-test build:
  "way too much explanation", the bite "doesn't make any sense",
  Gentle / Steady / Fast neither, the beast's words strange; his pick,
  "just the cards"). The bite, the paces, the speech bubble and Not for
  me are gone (and their commands, `beastpace`, `beastoff`); so is the
  page's Privacy line (Settings › Privacy › My beast stays). Its page
  says what it is in one line (`beast.subtitle`: "640 overdue cards from
  your week away."), then its health with what's left, Study them (its
  cards not yet reviewed, as many as you like) and Let it go, then How
  it works in three short lines (`board.BEAST_HOW`; a capped one says
  it's the oldest part of the pile). With no beast the page says what
  one is. The You bubble's card: its beast breathes (not with Reduce
  motion), and the whole card opens its page but Study them (Sam).
  Sizing a beast's parts still uses half a usual day (`beast.PACES`).
- 3.9.0, the closet's line (Sam, 16 Oct): Wear it floated mid-banner,
  apart from Closet. Each banner action pushes itself right with an auto
  margin, so two of them split the free space; a second one now sits
  beside the first (`.wc + .wc`), actions never break over two lines, and
  the line's words sit left when they wrap at phone width.
- 3.9.0, who knows it, the moment you miss it (Sam's picks, "Open calls"
  A and C, 16 Oct: "go with your recommendations"). The chip only knew
  about the cards I was stuck on at the last sync, so a card missed for
  the first time mid-session showed nothing till the next one. Now the
  day's first sync, light or full, also sends the note guids of the
  cards due today in the decks I share (`cards.due_today`: reviews due
  today or before, learning cards, the most overdue first, `DUE_MAX`
  1,000, not the stuck ones), and its reply (`cards`, the same mutual
  friends' knows and tips as the stuck ones', nothing kept) is kept for
  the day (`session["cards_due"]`, `due_day`). On the answer side a card
  I'm stuck on now (`cards.stuck_now`: lapsed twice, or Again today)
  uses it, so the second time a missed card comes up its chip is there.
  Still one request (`due` rides `POST /sync`, validated in both the
  Worker and the fake); a Worker without `due` gets the sync again
  without it and isn't asked again that day. And with Pip on, the corner
  card for who knows it is their Pip (`peek_pip`, waving, in their look)
  peeking up from the bottom of the review screen with a lightbulb:
  "I know this one", Ask Dre, Not now (more than one: "Dre and 2 more
  know this", Ask; asked: Asked). It pops up, the bubble after, the bulb
  glows twice; it ducks back down on the next card or Not now; none of it
  with Reduce motion. The bar's chip, tips, asks and plan notes are as
  they were; "Dre knows this" stays the words (E, his pick).
- 3.9.0, the beast, the way back (Sam's picks, "The way back" rounds 2
  and 3, 16 Oct: "go with your picks, build it for 3.9.0"). Three kinds:
  the Leech Lord, the Pile and the Backlog Beast (`beast.KINDS`; the
  Snoozasaurus and the Overdue Owl are gone, "implies laziness", and a
  test build's account beast of those kinds is the Backlog Beast now,
  `beast.WAS`). Its line under the name is the count ("1,507 overdue
  cards", `beast.subtitle`). Study opens your own deck: Anki's Study
  screen on the top deck holding most of its cards left
  (`beast_flow.home_deck`), whose usual order puts the most overdue
  first; no deck of its own any more (`OPEN_MAX`, `open_cards` and
  `overdue_order` are gone; `empty_old_deck` still empties one a test
  build left). A hit is a review that sends a card a day or more ahead;
  a card suspended, deleted, made new or moved ahead with Set due date
  just leaves it, no hit (`beast_flow.count`; `tools/real_anki.py`
  answers and sets due dates with Anki's own scheduler to prove it), and
  half gone that way it goes quietly, with nothing said (no "wandered
  off" card). Beaten, no pet: the card shows Pip, and the first one
  beaten puts the Beast hood in Pip's closet (five the Viking helmet, ten
  the Knight, as before), said on the card with Be one
  (`beast_flow.thing`; the beast is counted before the closet at a
  refresh so both land together, and the closet's own line leaves that
  thing to the card); its page shows Pip in it, and the pets on its page
  and Wrapped's slide are gone (the slide shows the beasts themselves).
  Nothing on a crew row (Sam: "the little icon on the crew page doesn't
  make sense"): `board.beast_chip`, app.js's `beastChip`/`beastOf` and
  the kit's beast drawings are gone, and my week carries a beast only
  once it's beaten, for two days, for the banner (`beast.week_field`;
  validate.ts and the fake take only that, `{k, p: 100, end}`). Let it go
  asks on its page, not in a window (`beastletyes`, `beastletno`). How it
  works says less. The pace (How fast? on the card) and a plan's days
  away as a line on its card, in place of Welcome back's window, are
  3.9.1 (his pick).
- 3.9.0, the beast's page in plain words (Sam, 16 Oct, on the test
  build: "nobody's told reads really strange", then "all the text on
  this page actually reads a bit paternalistic and faux nice"). Facts
  only: How it works is what its cards are, what takes one off, and the
  Beast hood (`board.BEAST_HOW`; no "No rush", no "till you get it
  right", no "due before today"); Let it go just asks ("Let it go?",
  Let it go · Cancel), and after it the page says "No beast right now.";
  beaten, its name and "Beaten · 1,150 cards in 6 days"; with none, "One
  turns up when 100 or more cards are overdue and that's at least two
  days of your usual reviews." The README's line ends "Let it go any
  time."
- 3.9.0, the peek, always (Sam, 16 Oct, on the test build: the plain "Adina
  and 1 more know this · Ask" pill "is also not the new version we agreed
  on"; a smaller peek squeezed into the bar wasn't either). The peek
  showed only when the card left the bottom-right corner free, and a full
  answer sent it back to the old chip. Now with Pip on, who knows it always
  peeks up in that corner as mocked ("Open calls" C), with no corner
  check; a spacer under the card (`dc-knows-pad`, gone with the peek) lets
  its last lines scroll clear. Pip off, the corner card and the bar's chip
  as before.
- 3.9.0 ships without the Backlog Beast (Sam, 16 Oct: "remove the beast
  business from this version because I don't think we're there yet";
  17 Oct: "divorce the beast from the codebase for this release"). The
  beast's bullets above are a build that never shipped. It's out of the
  code, not switched off: `beast.py`, `beast_flow.py`, `beast_art.py`, its
  card, page, banner and commands, Settings' Backlog beasts and Privacy's
  My beast, the account's `beast`, `beasts` and `share_beast`, the week's
  `beast` (validate.ts and the fake refuse it again), Wrapped's beasts
  slide, and the closet's three beast things (61 things again, every one
  offered). Git keeps it: it came in with 9915332 and was last whole at
  b96f20c. A "Due Crew::The …" deck an earlier test build made is no
  longer emptied for you; delete it in Anki and its cards go home.
- 3.9.0, the peek with Pip off (Sam, 16 Oct: "We should always get this
  version, it would just be without the pip"). Who knows it is the same
  bubble in the same corner with Pip off, saying who ("Dre knows this",
  Ask, Not now), always shown like the peek; it fades in and out.
- 3.9.0, the peek, 2D (Sam, 16 Oct, from the sheet: no lightbulb; up to
  three Pips). Who knows it peeks up with no lightbulb over their head,
  and when more than one crewmate knows the card their Pips stand side by
  side, three at most, the first nearest the corner; the words name them
  ("Adina and Mo know this", "Adina, Mo and Jo know this", "Adina, Mo, Jo
  and 1 more know this"; one alone still says "I know this one", Ask
  Adina). `cards.chip_view`'s peek carries `uids` (`PEEK_MAX` 3);
  `on_answer` draws each Pip in their look and colour (`peek.pips`). Ask
  still reaches everyone who has the card.
- 3.9.0, the peek's Pips blink on their own (Sam, 17 Oct: "they are
  blinking at the same time"). Side by side, two or three Pips shared
  one blink. Each now gets its own place in it (`sev.started(i)`, the
  `--sv-d` a study room's seats use), so no two blink together.
- 3.9.0, a bingo square's stamps blink on their own (Sam, 17 Oct: "they
  all blink at the same time on bingo"). A square's Pips move only while
  it's pointed at, so its two or three stamps started together and blinked
  as one; a plan card's squad line did the same. `board.row_sev` takes
  `nth`, its place among Pips that move together, for its own place in the
  blink (`sev.started`, as a room's seats and the peek's Pips); the
  stamps (`stamp_pip`) and the squad line (`squad_pip`) pass it. The site's
  Pips don't move, so nothing there to match.
- 3.9.0, Pips blink on their own clocks (Sam, 17 Oct: one after another
  "still looks kinda creepy", random "anywhere it is"). Side by side, a
  room's seats, the peek's Pips, a bingo square's stamps and a plan
  card's squad line used to share one cycle, each a fixed step behind the
  last, so they went round in turn. Now each has its own cycle (3.4 to
  6.4 s) and its own place in it (`sev.blink`, `--sv-b` and `--sv-d` on
  the wrapper; the blink reads both), spread so none start together, and
  they drift past each other, no order lasting. From the Pip's place in
  its group, so a redraw draws the same and nothing moves for it.
- 3.9.0, a dressed Pip peeks at the same height (Sam, 17 Oct: "why's the
  second pip so low?", a Pip in the pumpkin with the umbrella). The peek,
  the knock, the bounce and the pop-up moved the body by a share of its
  own box (`translateY(22%)`, the body's fill box), and what Pip has on is
  drawn in the body, so a hat and a held thing made the box taller and
  the share bigger: 22% of 86.7 units sank it 19, a plain Pip 10. Each
  now moves by the drawing's own units, a plain body's share (45.5 tall:
  22% is 10), so every Pip lands the same whatever it wears.
- 3.9.0, asks and tips (Sam's picks on the mock "Asks and tips", 17 Oct:
  A with W1, Folded until you open it, nothing new for a helped tip; and
  his note, "find a way to integrate the tipper's pip in the tip").
  An ask still goes to everyone in the crew who has the card (it rides
  my week, as before); the dialog now says so first: "Goes to everyone
  in your crew who has this card. Adina has it down. One line,
  optional." (`cards.ask`). On a one-by-one card the answer side opens
  with most of it hidden, and a tip's words, an ask's line or a plan's
  note gave the rest away the moment it opened. Now each says only who
  (`fold`: "Adina left a tip", "Sam asked about this card", "📌 A note
  from Block 1"), with Show; Show brings the words and what to do with
  them (This helped, Tip, +1 more). The bar's chip folds the same way
  and opens on a click; no words on a hover while folded. Who knows it
  never folds: it names people. A tip now peeks in like who knows it:
  the tipper's Pip waving from the bottom corner, the bubble beside it
  (with Pip off, the same bubble with 💡), always shown, with room under
  the card; its bubble wears the tipper's colour round its edge (mine
  with Pip off), so a tip doesn't look like who knows it (Sam: "too
  similar"), whose bubble keeps the plain line. Opened stays opened: This helped draws it again open
  (`on_answer(card, opened=True)`), and a move to the bar says so
  (`knowsbar:open`).
- 3.9.0, the motion audit (Sam, 17 Oct: Crew to Squads "visibly flicks
  from rectangular to fit the pill", "everything should be smooth!").
  `tools/motion_audit.js` plays every motion in `tools/motion_preview.html`
  with its frames held, steps through them, and counts what jumps between
  the last frame and the page once it has cleaned up. What it found, and
  the fixes (`motion.js`, the site's byte for byte):
  the pick's pill slid as a box and took its round end only once it
  landed; now each corner is read as drawn (a 99px radius draws as half
  the height), it rounds both ends on its way and lands in the new pick's
  shape, and the one it left keeps its picked words and edge until the
  pill has gone from under them, the new one takes it as the pill
  arrives, each edge in step with the fill (`slide`, `onIn`).
  Every height move overshot by the box's padding and border (the Due box
  12px top and bottom, a banner, a note) and jumped back at the end:
  offsetHeight is outside height and style.height inside. Now `inner` takes
  them off, from `tall`, the height to the fraction of a pixel (offsetHeight
  rounds, and half a pixel moved every line below at the end).
  A fold to nothing ended a few px short: a box with a border, children or
  a flex gap keeps its neighbours' margins apart, and a grid keeps its gap
  beside an empty row whatever the margins. `room` measures what's left
  and the fold (and unfold, and a room seat's shrink) takes it back as a
  margin; in a grid the neighbour closes the gap in step (`close`).
  A glow ended on nothing and then my row's tint came back; it ends on the
  box's own ground. A dimmed box (a day that's off) ended a fade at full
  and snapped back; `anim` keeps its own opacity. ↻ snapped from mid-turn
  to upright when the board redrew; the new one finishes the turn, and the
  ten-second stop waits for a turn's end.
  Elsewhere: a cheer's banner faded out but popped in, and a click took it
  in one frame; both fade now. A show ended by a click or Esc vanished;
  it fades in a quarter second, taking no clicks (`show.js` `stop`). The
  peek's Show swapped "Adina left a tip" for the words in one frame; the
  bubble grows into them and they fade in once there's room, and the bar's
  chip fades its words in. Settings' found row glowed back to nothing;
  to its own ground. Pip's moves, the bats, the logo's wave and the
  cheers' toss were already ending where they rest. The suite reads every
  keyframe list in the add-on and the site and fails one whose offsets go
  backwards, which a browser drops without a word.
- 3.9.1, doodle cheers (Sam, 17 Oct: "Like doodle idea! mock it", then
  "create the doodles thing", with the mock's picks: both, Pip holds it up,
  the fridge, your colour and black). The Cheer window has Draw and Sign
  under the emoji: a pad to draw on (paper, light in either theme; two
  pens, your accent's light shade and ink, thin or thick, Undo, Clear), or
  a few words (24 at most, shown on the paper as they'll look) for your
  Pip to hold up. Both are optional; a blank pad sends a plain cheer. It
  goes as one more field of the cheer, so sending is still one request: a
  drawing is its strokes, [pen, x, y, ...] in whole points on the 300 x
  170 pad (pen bit 0 thick, bit 1 ink), 200 strokes and 2,000 points at
  most, a few KB; never pixels, a colour of its own, markup or a link.
  `shapes.clean_doodle` is the client's gate both ways, `validate.doodle`
  the Worker's (the fake's `_doodle` the same); never on a tip or a
  good-luck line. Migration 0029 adds `cheers.doodle`; `/board` returns
  it with the cheer, `GET /account/data` with the ones waiting, a report
  says a sign's words or that it drew. A Worker from before it turns the
  field away (400, nothing written), so the add-on sends the cheer again
  without it. It lands as the cheer does, from mutual friends only, and
  in place of the show: the sender's Pip (their colour and look, arms up)
  rises at the board's corner holding it on two sticks and ducks down as
  the banner goes (`board.doodle_landing`, `flurry_js`'s `doodle`); with
  Pip off or Reduce motion it sits in the banner on its paper, still. The
  drawing is drawn back on my side (`board.doodle_html`: an SVG of paths,
  the sender's accent in its light shade). Every one that lands goes on
  the fridge, a third page of Pip's closet (Yours · To earn · Fridge):
  newest first, who and when, a × to take it down (`closetfridge`), the
  last 24, kept in wrap.json on this computer and never sent (`fridge.py`
  pure, `closet_flow.keep_doodles`/`fridge`/`take_down` the glue). The
  site's home says "cheered with a drawing" and leaves it for Anki.
- 3.9.1, cheers, clearer (Sam, 17 Oct: "Cheers, clearer: build these: 1 ·
  A 🎉 that looks pressable", then "also get rid of the current cheers
  click to the right of the stats", and "make the cheers and doodles
  modals in the design language of our add on, not in the native anki
  style"). The faint 🎉 column at the end of every crew row (12px, 30%,
  no word, past Streak) is gone; a crewmate's cheer is a "🎉 Cheer" pill
  right after the name and its chip, only while the pointer (or a key)
  is on the name (`td.nm:hover`; Sam, after a first try that showed it on
  every row for a crew's first two weeks: "cheer should only show up when
  scrolling on a name, not persistent all the time"). A long name ends a
  little sooner while its pill shows, so the pill is never cut off. The
  site's rows are the twin (`cpill`); on a phone, with no pointer,
  tapping the name opens their card, which has "🎉 Send a cheer". The Cheer window is drawn on the Decks screen in the
  board's own look (`board.cheer_overlay_js`: its tokens, so Theme and
  Accent hold; their Pip and name at the top; the quick emoji and any
  other; Draw · Sign on a canvas pad and a paper preview; the note; Send
  and Cancel; Esc or a press on the backdrop closes it, never a line
  drawn off the pad's edge), in place of the Qt window (`CheerDialog` and
  its `DoodlePad` are gone; the crew-emoji window keeps the picker). Send
  is one `duecrew:cheersend` command, its payload URI-encoded JSON, and
  `social.send_from_window` checks it all again: a crewmate on the board,
  one emoji, one line, a doodle `clean_doodle` keeps. The name goes in as
  text, never markup.
- 3.9.1, two buttons (Sam's picks from the mock "Two Buttons": a switch in
  Settings plus a link on the Hard habit line; 2, 3 and 4 count as Good;
  every deck; FSRS off allowed, with a one-line note). Review with Again
  and Good alone. `two_buttons.py` is the whole of it, on two of Anki's
  own hooks: `reviewer_will_init_answer_buttons` hands the bar Again (1)
  and Good (3) out of Anki's four, in its own words (a list that isn't the
  four, another add-on's, is left as it came), and
  `reviewer_will_answer_card`, the filter every answer passes through,
  keys and clicks alike, turns 2 and 4 into 3. A room's break shares that
  filter and its no still holds (filters chain; a no stays a no). Space
  and Enter are Good already. Nothing else about scheduling changes; past
  answers and Undo are untouched. It's a person's way of reviewing, so
  it's an account key (`two_buttons`, off by default) and follows them to
  another computer; Reset board leaves it. Settings › Board has a new
  Reviewing section: "Two buttons", "Again and Good. Hard and Easy hide;
  2, 3 and 4 count as Good. Phones keep four." (phones don't run desktop
  add-ons), and with FSRS off in this collection, "Works best with FSRS
  on." (`_settings_board`'s `fsrs`, from the glue's `_fsrs_on`). Find a
  setting finds it by hard, easy, buttons. Insights' Hard habit line gains
  "Try two buttons" (`instwo`): it's on, and the line says "Two buttons
  are on" with Undo (`instwono`) for as long as the board shows it; with
  two buttons on otherwise, the line doesn't come (there's no Hard to
  press). Nothing is sent but the setting, as Settings sends it.
- 3.9.1, the fridge moves onto the Decks screen, and a doodle has a
  caption (Sam, 17 Oct: "could the fridge just be the periphery of the
  decks window, like dragged around the anki window? / can we add text to
  the doodle, or put the included text in the message under like a
  caption with a from the pip person ya know with their name"). The
  doodles I'm sent are pinned around the board like magnets on a fridge
  (`board.fridge_html`, placed and made draggable by `fridge_js` after
  every draw and swap): in the gutters beside the board, newest highest,
  left then right; a small pile in the bottom right corner when the
  window has no room beside it. Drag one anywhere and it stays
  (`fridgemove`; no redraw); × takes it down (`fridgedown`). Twelve at most (`fridge.KEEP`, what fits
  around a board on a laptop); Pip's closet's Fridge page is gone. Each
  carries the note it came with under it, "from" their Pip and name, and
  the day; held up as it lands, the sign has the same caption and the
  note leaves the banner (`doodle_landing`'s `note`, `from`, `ni`). With
  a drawing or a sign, the Cheer window's note says "A caption under it
  (optional)". A sign's words are in the board's own font, bold, not a
  handwriting font (Sam: "consistent with our normal fonts").
- 3.9.1, the fridge's notes are Polaroids, and keep their place as the
  window changes (Sam's pick from the mock "Pinned Doodles", 17 Oct: "B ·
  Polaroid. Tilt: a little, each its own way. Also: Perfect but get rid
  of 'From' so there's more room for the Pip", then "make sure different
  window sizes are handled well... they should remain in their place for
  if window expanded again"). Each doodle sits in a white frame, the note
  on its wide bottom edge, then their Pip (now a crew row's size,
  `FRIDGE_PIP`) and name and the day, with no "from"; a strip of tape in
  their colour holds it up, see-through (`_tape`: rgba, since Anki's
  older webviews have no color-mix). The landing sign's caption keeps
  "from Priya": Pip is holding the sign there, not in its caption. A spot
  I drag one to is kept beside the board, not as a share of the window:
  which side (`l`, `r`), px from that edge of the board, px down
  (`fridge.move`, `duecrew:fridgemove:<key>:<side>:<dx>:<y>`), so as the
  window grows or shrinks it stays the same distance from the board. A
  spot the window's too small for waits on the corner pile, still
  draggable, and goes back when the window has room again (`fridge_js`
  places at every resize; the spot itself never changes till I drag).
  One that's too low is lifted into the window for now. Ones that come
  in later go round the ones I placed, not under them. A spot kept the
  older way (thousandths, in a test build) is dropped, and that doodle
  goes back beside the board.
- 3.9.1, the Cheer window, round two (Sam, 17 Oct: "the other button in
  the emoji for cheers selector doesn't pop up with the emoji drawer", and
  "make all of our colors available in the doodles feature, not just
  yours / black"). "other" was a box to type into, which needed the
  computer's own emoji picker (a page can't open it). It's a button now
  that opens a drawer in the window's look: Find (by words: "coffee",
  "owl"), a row of groups, and the emoji by group (`emoji_drawer.py`,
  170 or so, each one clean_emoji keeps whole, the suite checks). Picking
  one shuts it and "other" shows the pick; one typed or pasted into Find
  is picked too. Esc shuts the drawer before the window. The pad's
  colours are every accent, mine first ("My colour"), then black. A
  stroke's pen says which: bit 0 thick as before, pen >> 1 the colour (0
  the sender's accent, as every doodle so far; 1 black, as before; 2 to 7
  `shapes.DOODLE_INKS`, by place, so the list only ever grows at the
  end). Pens 0 to 15 now, in the three that check a doodle
  (`clean_doodle`, `validate.ts` `DOODLE_PEN_MAX`, the fake); the Worker
  has to go out before an add-on that sends them (an older Worker turns
  a pen past 3 away, and the add-on sends the cheer without its drawing).
  Each line lands in the colour it was drawn in, whatever the
  recipient's accent (`doodle_html`, the board's own shades on paper).
  Draw and Sign start shut (Sam: "they don't always need to send a
  doodle / sign... should they always be open?"): the window opens as
  the emoji, "Add Draw · Sign" with neither picked, the note and Send. A
  press opens one; a second press on it shuts it. Only an open one is
  sent; a drawing shut away stays on the pad for a reopen.
- 3.9.1, the README's License section says the name, the Seven days logo
  and Pip (its name and look) are trademarks, not part of either licence
  (Sam, 17 Oct, after a look at how another open-source app words it:
  "just the notice", then "nah do both"). And from that day the logo's
  and Pip's artwork leaves the open licences, as `worker/` and `site/`
  left MIT on 29 Sep: `docs/logo/`, `docs/images/`, `due_crew/logo.py`,
  `sev.py`, `closet_art.py`, and their copies in `site/` (logo and icon
  files, the board pictures, `sev.js`, the Pip in `cards.js`, the logo in
  `og_assets.ts`) are all rights reserved, to be copied and run only as
  part of Due Crew (the root LICENSE lists them; `site/LICENSE.md` and
  `worker/LICENSE.md` point there). Copies taken before stay under what
  they were published with. Nothing changes for anyone using Due Crew.
  The notice is in the part of the README that is the AnkiWeb listing:
  re-paste it there.
- 3.9.1, the efficiency run, the review screen (Sam: "We've made the add
  on chunkier over the past few days ... I don't want our add on to impact
  anki performance"). Measured on Anki's own pages: every card sent about
  230 KB of our script (ten evals, about 6 ms of Anki's main thread, several
  times Anki's own engine work for the card), because every widget was
  drawn again at every question though nothing in it had changed. Anki
  keeps the review screen's pages from card to card (it builds them at the
  first card; the room sounds note's "the review page reloads every card"
  was wrong), and the top bar's from screen to screen. Now: each page's
  widgets go as one piece
  and only when they'd come out different, or the page is new (`app.pages`,
  bumped by `webview_will_set_content`), or something else was drawn there
  (`rooms._draw`/`_DRAWN`); night mode draws them again (`theme_did_change`).
  Taking a widget down is the runtime's own few lines (`REMOVE_JS`), not the
  whole 35 KB runtime; the bottom bar's balance goes to the bottom bar only
  (it had been watching the top bar and the card's page for nothing); the
  sounds' 18 KB only once a sound is picked. The knows chip is taken down
  only when one's up (`cards._UP`; `CHIP_OFF`, `FLOAT_OFF`, which still
  duck), an answer draws only the Pips its chip could name
  (`cards.chip_people`), not the whole crew's, and Pip's motion sheet goes
  to a page once (`cards._SHEET`). Pip's drawing is kept once drawn
  (`sev.svg`, an lru_cache; a look that isn't a list is drawn as it comes),
  and the config is read from disk once and again only after a save
  (`app.cfg`; Anki read config.json and meta.json at every call, a few
  times a card). A usual card now sends nothing.
- 3.9.1, the security review. A reviewer read every input that crosses a
  trust line (the doodle pipeline, every `duecrew:` command, the Worker's
  consent and auth, the site, logging, the client's network code) and found
  them sound but for two. (1) On the way back to Decks, Anki's
  `DeckBrowser.show()` makes the main view's messages the Decks screen's at
  once, then builds the Decks page after a background query; leaving review
  doesn't take the review page down. In that gap a card's own script (or a
  deck description's, from Overview) could send any board command as the
  board, past the card-page rules (`room_model.trusted`). Now the Decks
  page's own commands carry `board.BOARD_KEY`, new each run and written only
  into that page (`_pycmd`, and `window.dcBK` for what its scripts build);
  without it a message from the Decks screen gets a card page's rules
  (`__init__._on_js`). And nothing is drawn on the board till the Decks
  page is the one going in (`app.board_eval`: `deck_browser_will_render_content`
  says so, `state_will_change` unsays it), so the key never lands on the
  page before. (2) The room sounds' web export, `sounds/.+\.ogg`, matched
  `sounds/../…` (Anki fullmatches it; a card's script can fetch from the
  media server): any `.ogg` in another add-on's folder was readable. Now
  `sounds/[^/]+\.ogg`, a file in sounds/ alone. No token or file of ours
  was reachable (none ends .ogg).
- 3.9.1, the bug hunt (the same housekeeping). Four found and fixed, each
  with its test. (1) On the site, the Cheer pill had gone in the middle of
  a row's if/else chain, so a crewmate's " · yesterday" and " · 3 days this
  week" never showed; the pill now follows the line (app.js `nameCell`,
  run in node on a stale crewmate). (2) A drawing that came in on the
  launch's first refresh went on the fridge in the default colour, and one
  from someone just become mutual in their old colour: the colour was read
  from the board before this refresh's crew (`_commit` now hands
  `keep_doodles` the refresh's own entries). (3) With room sounds at no
  volume, the session's check every 5 s woke the sound engine it had just
  put to sleep (`sounds.js` `play` resumes only above 0). (4) The break
  screen's Pip rested after a few rounds with Pip at rest, mid-exercise;
  the break is the one place it goes on (`--sv-on: infinite` on the break's
  root). And a cheer an older server took without its drawing (the 400
  fallback) no longer says "and a drawing" (`api.send_cheer` returns
  "plain").
- 3.9.1, the whole window dims, and the board's questions are sheets (Sam:
  "when cheering, the full background doesn't grey out ... also the modal
  for status update is still native, make sure all modals are in our
  style"). The top bar and the bottom bar are pages of their own, so a
  window over the board dimmed the board alone. Now the board's page
  watches for its windows (`board.VEIL_WATCH_JS`: the Cheer window, a
  profile card, a sheet) and says when one comes and when the last goes
  (a closing one gives up its id as it starts to fade, so the bars fade
  with it); the glue puts the same backdrop over both bars (`app.veil`),
  and a tap there is Esc on the board (`veiltap`, keyed: the Decks
  screen's bottom bar is Anki's page, not ours). A new page in the main
  view or leaving Decks takes it off. And every question the board asks
  (status, display name, sign out, delete account, edit a to-do, the plan
  squad's join, leave, reply, remove and Ask the squad, a good-luck line,
  a tip, Hold back, Reset to default, Change deck, Stop following, the
  founder's Leave, Block, Make founder, Remove) is a sheet in the Cheer
  window's look (`sheets.py`, `board.sheet_js`): one line, one of a few
  (a list in the board's look, with Find when it's long), a box to tick;
  a step that can't be taken back in the board's red, Cancel focused.
  Only a yes reaches the caller, and only an answer naming the open
  sheet's id (new each time) with the Decks page's key; a Decks page
  drawn anew puts the open one back. Off the board (the review screen,
  Browse, a Qt window in front) the Qt question asks, the same words.
  Found on the way: the Cheer window's close faded it, then motion.js's
  own close ran on top (the fade unfilled: a frame's snap back); now
  motion.js closes what it opened.
- 3.9.1, the Qt windows in the board's look (the same ask: "all modals").
  The windows that stay Qt (Friends, sign-in, Welcome, a plan's Follow,
  Schedule, Pause, Welcome back, Hold back, Squads, Report, the picture
  cards, and the questions asked off the board) wear the board's colours
  for its theme (Settings › Theme, not Anki's alone) and accent: its
  8px corners, the main action (the window's own default) in the accent,
  the rest outlined, boxes and lists on the board's well; a question in
  bold over its words, no icon, its yes in the accent or the board's red,
  Cancel focused (`ui.styled`, from `attach_alive` or its own call;
  `ui.QSS`). Ticks, radio dots and number boxes keep the computer's own
  drawing: styled, they lost their frames (an unticked box vanished) or
  their arrows. A styled window ignores its palette, so a label's own
  style sheet takes the board's colour (`ui.tone`), never palette(...);
  Schedule's chart paints in it too. The window's frame stays the
  computer's. Every render in `tools/dialogs.py` was looked at, light and
  dark; Friends is 50px wider for the code and its three buttons.
- 3.9.1, the Qt windows, round two (Sam, with Open a Study Room on a Mac:
  "washed out. bad spacing. not engaging"). The Mac's own style drew a
  dressed box's arrow in a box of its own and its list as a menu with a
  tick column that cut "15 min" to "15 m"; the number box kept the
  system's stepper; small print was 11px grey everywhere. Now every Due
  Crew window sits on Fusion (`ui.base_style`, a QProxyStyle: 22px at a
  window's sides, 8 between rows), so a Mac, Windows and Linux, under
  Anki's widget style or the system's, get the same window, and `ui.QSS`
  draws every part itself: a box's chevron and its list (a list, not a
  menu: `combobox-popup: 0`, rows a `QStyledItemDelegate` the sheet
  dresses), a number box's two buttons, ticks and radio dots in the
  accent, a tree's arrows and boxes (Shared Decks' 3.5.0 `box_css` goes),
  a calendar without red weekends or week numbers, thin scrollbars; boxes
  and buttons 30px high, a box's edge darker than the board's hairline, a
  ring where the keyboard is. The arrows and tick are SVGs in the window's
  colours, written once to `user_files/_qt` (a style sheet takes an image
  from a file). One type scale: 13px, a window's title 16px bold, a
  part's heading bold (`ui.role(label, "head")`), small print 12px in an
  ink between the board's muted and ink (`ui.note`, token `ink-2`). Every
  window says what it is in its title (`ui.heading`; a plan's or a
  person's name in it is plain text) and its frame says Due Crew, so the
  words aren't said twice; a question's box does too. Two sizing bugs
  under it, both in the shipped 3.9.0 windows: Qt sizes a new window from
  its widest-and-shortest wish and caps it at two thirds of the screen,
  so Follow a plan came out shorter than its wrapped lines and the plan's
  dates ran into each other; and a window with a minimum width of its own
  never widened for a row that grew after it opened (Friends' code, once
  it arrives: its Copy slid over the code). `ui._fit` grows a window to
  its rows and its words, never past its screen, never smaller; the tidy
  (`ui._tidy`) runs as a window is polished, before it takes its size. A
  style sheet's margin on a label sets its words in a few px too, so the
  headings' spacing is a layout margin now. `tools/dialogs.py` renders on
  a laptop's 1440x900 screen with a Mac's 13px type, adds a window of
  every control (`kitchen`), the questions off the board and Pick a day,
  and fails on a clipped button, a box narrower than its words, two
  controls on top of each other or a window shorter than its words
  (`fits`); `DC_THEME=dark` renders the dark look and `DC_APP_QSS` puts an
  app-wide style sheet under ours, as Anki's widget style does (checked
  with Anki 26.9.3's own sheet in loud colours: none shows through).
- 3.9.1, before release: the README's cheer line said "Tap 🎉 next to a
  friend's name" and its board picture had the 🎉 column; both follow the
  pill now, with a line each for drawings and room sounds. board.png is
  rendered by `tools/readme_images.py` (the board's own HTML, a sample
  crew in their looks) and `tools/readme_images.js` (Chromium, 2x), so the
  next change re-renders it in one step. The click-test list starts with a
  15-minute pass over what only a live Anki shows (the Decks page's key
  after a review, the bars' shade, sheets, the Qt look, the system emoji
  picker, Pip at rest).
- 3.9.1, before release: the fridge is the account's, and × has an Undo.
  wrap.json is the Anki profile's file, and more than one account can sign
  in on a profile: a second account saw the first one's drawings and their
  captions. Now the fridge keeps whose they are (`fridge_uid`), the board
  draws the signed-in account's alone (`closet_flow.fridge(uid)`), a
  drawing landing for another account starts a fridge of its own, and
  signing out empties it (`clear_fridge`). One from before this (no owner)
  is whoever's signed in. And × left nothing to change your mind with: now
  "Taken down · Undo" sits where the drawing was, in its sender's colour,
  for eight seconds, then fades and goes (`closet_flow.gone`/`put_back`,
  `duecrew:fridgeback`); Undo puts it back where it was, with its spot.
  Memory only, the last one taken down.
- 3.9.1, the efficiency run, the Decks screen (the same ask). Measured with
  a crew of thirteen and a full fridge (twelve drawings at 2,000 points):
  every click that redraws the board (a swap) sent 77 KB of script the page
  already had (motion.js, Due's add line, Find, the fridge's), each guarded
  so it only loads once; the fridge cost 40 ms of Python a draw, each
  drawing checked three times (`clean_doodle`) and drawn again; and a
  refresh saved wrap.json (200 KB with a full fridge) two or three times
  whether anything had changed or not, 22 ms each. Now: the scripts go to a
  page once (`_board_js`, by `app.pages`; a page drawn anew always gets
  them, so the memory of what the board said is compared as before), and a
  swap sends only what they do after a draw, 0.5 KB
  (`keep_me_in_view_js(scripts=False)`, `fridge_js(scripts=False)`; the
  fridge's script is `dcFridge`, loaded once a page). The fridge is checked
  when it changes and drawn again only then (`fridge.clean` and
  `board.fridge_html` kept on their contents, `fridge.fingerprint`:
  marshal's version 2, values only), the same markup byte for byte. Its
  script tilts every doodle, then reads every height at once: two layouts a
  draw, not thirteen; the same spots. wrap.json is written only when its
  text differs from what's on disk (`app._wrap["disk"]`), made by
  `json.dumps` (4 ms; `json.dump` into the file was the slow encoder, 23
  ms): a refresh that changes nothing writes nothing, and a profile opened
  again doesn't write it back. With the full fridge a draw went from 40 to
  3 ms of Python, a click from 44 to 4 ms, Chromium's share of a click from
  77 to 68 ms (27 to 24 without a fridge); on Anki's own engine, a Decks
  redraw from 63 to 22 ms and a click from 27 to 8. Not done: a run of
  strokes in one pen drawn as one path would be fewer elements, but its
  edges where strokes overlap come out a shade lighter (Chromium, pixel for
  pixel), so each stroke stays its own path.
- 3.9.1, the efficiency run, idle. Measured in Anki's own engine
  (QtWebEngine 6.11): a CSS loop that never ends keeps the page drawing 60
  frames a second, about two-thirds of it on Anki's own thread, even a
  blink that changes nothing most of the time. The ones nobody sees are
  gone: the Halloween bats' wings flapped on past the line's end after
  their 4.2 s flight (20 flaps now, the flight's length; `HW_CSS`);
  Wrapped's player ran a frame loop all along, held, hidden and on its
  last slide too (now one animation a slide, scaling its bar, paused when
  held or hidden, none on the last; `wrapped_js`); a fifteen's widgets
  ticked every second though they show minutes (now at the minute's turn
  or the phase's end, ten seconds at most; the break's mm:ss and the
  question still each second), and the bottom bar's balance ran at every
  tick and again from its watcher (now only when the room's words change;
  the watcher leaves the room's own changes to it, as the chip's). Room
  sounds sleep at volume 0 (a running context costs, silent or not) and,
  stopped, close the context and let go of what it held (a minute of a
  recording is about 23 MB as samples). Brown noise's wander (the made
  noise's slow drift, a third more than a recording costs) stays, for Sam's
  ear.
- 3.9.1, Pip at rest (Sam's picks on the "Pip at rest" page, 18 Oct: "agreed
  with your calls on pip"). Measured in Anki's own engine, Pip on ▶ Fifteen?
  cost 41 ms of CPU a second blinking and up to 129 napping or with a moving
  thing on, on every screen; a five-note fridge 353; the studying-now dot
  222. A: each of Pip's loops plays about twelve seconds once it's drawn
  (`var(--sv-on, n)` in sev.CSS, n the rounds that make about twelve, even
  for one that goes back and forth), then Pip rests; pointing at it plays
  it on (`.sv:hover, .sv-slot:hover .sv` set `--sv-on: infinite`). The
  break's breathing square and stretch go on for the break: they're the
  exercise. Crew rows (and faces, a plan card's crew, the bingo stamps)
  move while hovered, as before. C: the fridge's Pips are still until
  pointed at, as crew rows. D: the studying-now dot pulses a few times
  (seven halves, ending lit) and stays lit, in Anki and on the site. Back
  to Anki's own idle once they rest.
- 3.9.1, the efficiency run, plans and the deck tree (Sam: "please do an
  efficiency run"). Measured on Anki's own engine, a big collection (35,000
  notes, 1.1 million answers) following a 30-date plan: a refresh's plan
  work (`refresh_progress`: the deck read, each date's numbers, today's
  session) ran whole each time it was asked, and a sync asks twice (its
  payload, then its commit), about 280 ms each; today's session found the
  notes started before today with a pass over the whole deck for every date
  (`DeckIndex.buried_today`, 115 to 160 ms a refresh); and Anki's deck tree
  (8 to 17 ms) was read by Due's reviews again after every refresh, and by
  each plan's due on its own. Now `buried_today` finds them once per index
  and first_seen (the session 6 to 7 ms). `refresh_progress` keeps its last
  answer under one key of everything it reads (`_progress_key`: col.mod,
  which every answer and op moves, the day and Due's day, the session's
  plans, plans.json's state as it stands, the generation, and the due now
  of each plan deck on my schedule) and gives it again in under a
  millisecond while that holds; it keeps nothing when a part failed,
  without a col.mod, or when a date's search is about my own reviews
  (`is:due`, `rated:`…, read at every refresh as before). The deck tree is
  read once while it can't have changed (`due_flow.deck_tree`: col.mod,
  the day, and till a learning card comes inside Anki's learn-ahead,
  `collapseTime`, where the clock alone moves its count); Due's reviews, a
  plan's due (its node, as Anki's own `deck_due_tree(did)` finds it) and
  the bingo's week share it, and a refresh no longer throws it away with
  Due's count. On that collection, main thread: the push on open 532 → 244
  ms, the morning's sync 986 → 472 ms (the deck read three times to twice:
  the morning's own, before it opens, stays), a stale redraw's refresh 870
  → 338 ms, a second sync 1,261 → 883 ms; over a day of them (nine steps,
  open to a relaunch) our own deck tree reads 13 → 3. Each kept answer was
  compared with a fresh read while measuring, and is in
  `test_efficiency_plans_v391`; `tools/real_anki.py` checks it on Anki's
  engine (an answer, a learning card coming back, an unsuspend: read again)
  and that today's session takes under 20 ms. A change made by raw SQL
  doesn't move col.mod and waits for the next one, as Due's suggestions and
  my own load already did.
- 3.9.1, the efficiency run, history scans (the same ask). Measured on
  Anki's own engine (26.9.3) with a big collection (35,000 notes, 1.1
  million reviews over four years, a 1,459-day streak): four reads of the
  whole history are gone or cut, each held to the old answer by a test
  that keeps the old code. Pip's closet read the whole revlog by the hour
  at every launch's first refresh (350 to 680 ms on the main thread, while
  Anki's own sync ran) and walked all 35,000 hours in Python at every
  refresh (62 ms); kept in memory by the day alone, a second profile
  opened that day got the first one's. Now `closet_days.json` (per
  profile, never sent; `closet_flow._history`) keeps the days before the
  last week as the closet counts them (the days, the mornings' and
  evenings' dates, `closet.hour_sets`, the year turning, the answers), a
  day going in as it settles. Two counts check it at each refresh (the
  revlog's rows less those since its edge, half a millisecond); it's read
  whole again when they move (a sync brought older answers in) or its
  hours stop lining up with today's (rollover, time zone, DST). The last
  week is read fresh, so a phone's week counts the moment it syncs (until
  now, the next day). A launch is 19 ms, a refresh 8, a new day's first 20;
  the first launch on 3.9.1 reads it all once (`test_closet_history_v391`,
  against 3.8.2's whole read). The streak: the day after a day studied
  here, yesterday's run with the day before it still empty is the base,
  since the scan can't find more; a long streak's four widening scans (233
  to 373 ms on the day's first push) are gone (0.6 ms;
  `test_streak_shortcut_v391`, against 2.11.1's base). The history
  import's new cards (`new_cards_by_day`): over a year every answer looked
  for an earlier one, about 600 of the year's 700 to 770 ms. A window
  longer than a month now reads each card's first answer once, off
  revlog's card index (140 to 160 ms, the year 250 to 275, the first log's
  120 days 207 to 124); a short one keeps 2.13's form, the quicker there.
  Counting only learns (`type = 0`) was quicker still, but a card imported
  with its schedule, set due first or previewed in a filtered deck is new
  on an answer that isn't a learn; the count is 2.13's in every window
  (`test_new_cards_first_answer_v391`, and every window of the big
  collection with 3,000 such cards added). Closing: Anki's own sync as it
  closes ran the full gather (770 to 1,010 ms, 1.2 s with a plan, a year of
  the history import among it) before Anki could quit, for an upload on a
  thread that quitting may cut short. It's light now, today's numbers as
  the pushes on open send (2 ms; with a plan, its progress, 320), and
  nothing when the collection's mod, my day and my config are as the last
  push that went had them (`_on_anki_sync`, `test_close_sync_light_v391`).
  Leaving a room still goes: rooms.on_close pushes it itself.
- 3.9.1, "other" opens the computer's own emoji picker (Sam: "the emoji
  drawer is missing tons that are natively supported. want the other
  option to just open the native drawer?"). A page can't; Python can ask
  (`native_emoji.py`): a Mac's Character Viewer (what ⌃⌘Space opens,
  `orderFrontCharacterPalette:` through the Objective-C runtime) or
  Windows' emoji panel (Win + . pressed and let go). The window puts a
  focused box in other's place first ("pick one") and sends
  `duecrew:emojipicker`; whatever lands in the box is picked, Esc puts
  other back. Linux has no one picker to ask for: there, and whenever
  asking fails, the glue tells the window to open its own drawer
  (`dcCheerNoNative`), which stays as it was.
- 3.9.1, room sounds, round three (Sam, 17 Oct: "the waves sound isn't
  great so let's find another", then "A for waves. Fifteen sounds, my
  pick: A · Say it on the chip. Make an option to remove sounds in
  settings"). Waves are el_boss's "Evening Ocean Waves along the Pacific
  Coast" (CC0, freesound 587164), picked by ear from three loops cut the
  same way (a Cornish beach and a calm Whidbey Island shore were the
  others); 60.5 s from 6:08.5, the seam between two waves. The chip's
  speaker says what it is, from the mock "Fifteen Sounds": "Sound" in a
  quiet outline while it's off, the sound's name in your colour while
  one plays ("Rain"); the speaker alone when the chip is compact, and
  while the picker is out (it says it all). And Settings › Board ›
  Fifteen and Pip › Room sounds (on by default, this computer's, like the
  pick; Reset board turns it back on): off, the chip has no speaker, the
  player is told off, and a pick from the chip is ignored
  (`room_model.sounds_on`; the chip redraws on the switch).
  Spacing, measured in every state (Sam: "in one the sound symbol is a
  bit too close to the edge of the oval"): the outlined speaker sits 3 px
  inside the chip on all four sides (20 px tall with its border, as the
  chip's inside is 26), like a button nested in it; alone (compact, or
  the picker out) its icon is 6 px from the end, not 1; a solo fifteen's
  empty crewmate slot no longer doubles the gap before it (15 px to 7).
- 3.9.1, the sound picker folds back by itself (Sam: "the sounds chip
  should close after a second or two because now just stays open"): 1.5 s
  after a pick, 2 s after the volume last moved, 1 s after the pointer
  leaves the chip, 4 s after it opens if nothing's touched; moving in it
  keeps it out, and never while the volume is held mid-drag
  (`room_model`'s chip, `later`). Esc and a click elsewhere still close it
  at once.
- 3.9.1, room sounds, recorded (Sam, 17 Oct: "the background noises
  aren't the best. are there any open source sounds we can use with
  attribution instead?", then "keep the brown noise"). Rain, fire and
  waves are recordings now, CC0 from Freesound, each checked on its page
  (`due_crew/sounds/CREDITS.md`: who, where, which seconds): rain by
  speakwithanimals (the first pick, a "seamless rain", had left
  Freesound), a fireplace by inchadney, a Baltic shore by pulswelle.
  Each is a loop of a minute or so from the steadiest stretch of the
  recording (no block more than about 2 dB over the stretch's middle;
  the waves' seam sits between two waves), its end crossfaded into its
  start, levelled to the made brown noise's -23.3 LUFS (measured from an
  offline render of sounds.js), limited to -1 dBFS, Ogg Opus at 80 kbps
  (`tools/cut_sound.sh`): 1.6 MB for the three. In Anki's own Chromium
  they decode to the exact length and the wrap is an ordinary step, not
  a click. They play by an AudioBufferSourceNode that loops sample-exact,
  from a random point; only the playing one is decoded. The top bar's
  page fetches them from Anki's `/_addons/<folder>/sounds/`
  (`setWebExports`, `rooms._sound_files`, `room_model.sound_files`, the
  state's `files`); a file that won't load or decode plays the made
  sound instead, and brown noise is always made. The files are CC0, not
  MIT (the root LICENSE says so).
- 3.9.1, room sounds (Sam's picks from the Room Sounds page, 17 Oct: a
  speaker on the chip; in a crew room each person picks their own; off
  till you pick, the last pick remembered on this computer; made from
  noise only, no café or library). Brown noise, rain, fire and waves,
  made by Web Audio from noise (`sounds.js`, 16 KB, no sound files: the
  now-and-then things, a drop or a crackle, are drawn once into loops of
  different lengths; the waves are slow oscillators), each trimmed to the
  same loudness, with a safety limiter. They play in the top bar's page,
  which Anki keeps through review (the review page reloads every card),
  from a fifteen's or a room's start to its end, breaks and a fifteen's
  question included, fading in and out over 1.5 s; the player stops at the
  session's end by itself and when the room goes (`room_model.sound_state`,
  `SOUND_RUNTIME`, `rooms._sound` in `refresh_widgets`, and at profile
  close). The top bar's page may play without a click
  (`setPlaybackRequiresGesture(False)`, `rooms._allow_sound`), so a pick
  comes back by itself after the bar redraws. The control: a speaker at
  the chip's end (muted grey when off, the accent's waves when on); a click
  turns the chip into the picker (the bar is too short for anything under
  it): Off, Brown noise, Rain, Fire, Waves and the volume; Esc or a click
  elsewhere puts the chip back. A pick plays at once and is kept for this
  computer (`roomsound:<kind>:<volume>`, `room_sound` and `room_sound_vol`
  in the add-on's config, never an account key, never sent: nothing new
  on the wire, no Worker change). Only the top bar's chip may set it: a
  card's page can't (`room_model.CARD_PAGE_CMDS`). The bars' and the
  margin's little ones carry no speaker; the sound plays on under them.
  `tools/chip_preview.py` draws the chip with it, light, dark and narrow.
- 3.9.2, Reviews ahead (Sam's picks on the "Three Unknowns" page, round
  two, 18 Oct: "Most med students don't work by the 25 new a day, mostly
  unsuspend cards in batches tied to content ... put data at the forefront,
  don't make actions ambiguous, don't over explain"). Insights' Your week
  becomes one chart of a deck in cards a day, as Anki counts them: the last
  7 days as studied, today (done, and what's still due), 13 days by day, then
  4 weeks by week (a week's average day), my exam marked on its day. Counted,
  never modelled (`ahead.py`, pure): the cards I've started go on by how my
  own reviews have gone at their interval (missed, a pass's push in thirds,
  where a miss lands; my last 120 days); the cards I'll start by my own
  curve (of the cards I started 6 to 17 weeks ago, the share seen each day
  after; a typical one, `GENERIC`, until I have 60); and when I start them by
  my pace, by weekday (the last four weeks: a batch unlocked on Mondays lands
  on Mondays), never more than the deck has left, a plan's dates when I
  follow one. On simulated learners (FSRS's defaults, each card's memory off
  the model by its own amount) it came within about 10% six weeks out, where
  counting only what's due missed half by week two. The track record: three
  past days, each forecast with only what came before, against what I did
  (`backtest`, `trust`; a card suspended since is in the past it was still
  answered in, so a leech Anki suspended mid-window doesn't drop out of the
  start and make the record look worse than it is), worked out off the main
  thread once a week a deck and kept in plans.json (`ahead_trust`); it gives each bar's tip its band
  and the section's last line ("on your own past, within 9% a week"). The
  log's part (habits, curve, pace) is read once per Anki day a deck
  (`ahead_flow._day_part`, today left out); each draw reads only the cards
  as they are. A card in a filtered deck counts on its own due day (`odue`):
  Your week counted it today (the 3.8 bug).
- 3.9.2, Stop new cards (the same page, R2-A, "with a Do it button"). The
  chart's ways, pills switched on the page: my pace; with an exam 8+ days
  out, stop new a week before it; stop new now (to the exam, or with none,
  till I turn them back on); with no exam and the unlocked cards gone within
  two weeks at my pace, only what's unlocked (no button: what that leaves).
  Each way its own chart and a line of numbers ("Exam week: about 240 a day,
  not 320 · exam day about 210"). Do it says once what it does: each morning
  (after a catch-up's own limit) Anki's today-only new limit goes to 0 on the
  deck and its subdecks while it runs, the deck's options untouched; Turn new
  cards back on takes today's off and puts a catch-up's back. The pause is
  this profile's plans.json (`new_off`, {deck: {kind, at, exam}}): its exam
  is whichever date I have now, so it moves with it, and ends when it passes.
  Never a warning colour: a busy day is just a tall bar.
- 3.9.2, the board's line when reviews climb (R1-A): once a day, after the
  board draws, my most reviewed deck's forecast (Insights' own when a plan's
  on it); when the next two weeks' busiest three days run a quarter over this
  week and 20 cards more, one line: "Reviews in Big Step 1 climb to about 420
  a day by Mon 12 Oct · this week 310", See ahead (You › Insights on it), ×
  for a week (`ahead_line_x`). A redraw only when there's a line.
  On Sam's own deck (18 Oct, a plan, a batch of 1,295 the week before):
  a plan's date inside a stop still opens and its cards wait in the
  unlocked pile for after (`ahead.starts`), where the forecast had dropped
  them; `board.ahead_line` rounds its number itself, as the chart does.
  Round two, the same day, on how his numbers read (Sam: "improve our
  insights implementation based on your feedback from my data"): the
  week ahead was 44% new cards at his pace, a guess, in one number, so the
  line leads with the cards he'd started and adds new ones after ("Next 2
  weeks: 380 a day from cards you've started, +140 new at your pace"); a
  stop says what it holds back and when they start again, and a plan's
  share of them ("732 new cards wait till Sat 24, 434 of them your plan's
  dates": the cost was unsaid, and for a block exam those cards are the
  exam); the board's line names the cause when it's new cards
  (`ahead.cause`: 200 at least in two weeks, twice the two before: "you
  started 2,480 cards in 2 weeks"). The track record forecasts each past
  day as the chart would have then, the typical curve where his own wasn't
  old enough (a deck under 12 weeks, most first-years in the fall, had
  none), leaving out a day with under 100 cards started before it.
- 3.9.2, leeches, one button a card (S1-A, S2-A). Insights' line counts the
  leeches Anki stopped showing me and the cards one miss from it (the next
  lapse reaches the deck's leech threshold, or a half of it past, and the
  deck suspends leeches); See them opens a view in Insights' place
  (`leech_flow.py`): Insights › Leeches with the way back, the counts, Bring
  all back and Browse on top, then each card (its front from my own copy,
  a cloze's answer hidden; its topic, misses, since when, slow when 30 s a
  try or more, on my exam when the exam's scope is narrower than the deck),
  sorted by danger (on my exam, most missed, latest; a miss away: due
  soonest). One button: a crewmate's tip (in a sheet, Bring it back from
  there), else Ask who has it down (the card ask, a sheet), else Bring back;
  behind its dots, Learn it fresh, Edit (Browse on it) and Leave it out
  (`leech_out`). Bring back unsuspends with the leech tag off, schedule kept;
  Learn it fresh is Anki's Reset, lapses from zero; each one undo step. Who
  has it down and their tips are the stuck list's, back with each sync: no
  new request. A leech lapsed (`c.lapses > 0`, as Recover leeches has it):
  Anki tags the note, so on Sam's deck a sibling the shared deck ships
  suspended, never answered, counted as one.
- 3.9.2, the exam's scope (C1-A): my exam covers the cards I started since
  my last exam, when it was in the last 10 weeks, else the whole deck; an
  exam is kept once it's passed (`exam_last`, an account key, set when a new
  date takes its place), and a day I pick wins (`exam_since`: a date, or
  "all"; a new exam starts from the default). Said in the exam box ("Since
  Sat 5 Sep, the day after your last exam · 1,240 cards · Change"), Change
  the date picker, Whole deck and back. With nothing at risk the box is a
  line that still says it, with its Change.
- 3.9.2, the map by when I started them (C2-A, "getting there in reverse":
  a plan's dates, read back from my own log): a "by" on every deck's map, a
  week a tile for the last 8 weeks with cards (before them, one tile; the
  cards in play not started yet, one more), each named by its dates and what
  it was (`team.batch_name`: the deepest tag a third of it shares that
  isn't on nearly every card I've started, "This week · Cardio · Pharm"),
  shaded by what I know now, opening into its topics; Browse, its cards.
  Worked out only when picked (one more read of the deck's log). A long
  name ends on a whole word with an ellipsis (`team.clip`; Sam's deck had
  "Reproductive Physiolo").
- 3.9.2, the map and the right % read on Sam's deck (18 Oct). The map
  shaded by FSRS's recall today read 93 to 96% on all 12 of his systems
  and all 9 weeks while he passed 77% of his reviews: recall today says
  how lately a card was seen as much as what's known, and the scheduler
  keeps every card near the target. The old "right on their last review"
  counted a relearning step after a miss as right, and a last review alone
  saturates too (a missed card is back the next day and passes). The map
  now shades each card by the share of its reviews these 4 weeks it got
  right (each day's first; not due in them, its last review; never due,
  its last answer), FSRS or not (`team_flow._know`, "% right, 4 weeks"),
  and a week's snapshot is kept under a new key so the old shading is
  never compared. Week names prefer the map's own tag tree ("Microbiology ·
  Clinical Bacteriology", not a video series). The header's right % says
  the cards started these two weeks apart from the rest when they're a
  quarter of the reviews and 5 points apart (`team.right_split`: his 87%
  to 77% came with four times the reviews, mostly first ones).
- 3.9.2, the words three students tripped on (F1-A): "never passed" and
  "lapsed", as Anki's Stats say them; a map tile's % with its cards ("66% ·
  190") and a key that says what the % is and what the bar is; "86% right ·
  Anki aims for 90%"; "Study 53 early" (they aren't due yet).
- 3.9.2, the builder (R3-A, C3-A): under the calendar, the reviews a plan's
  dates bring, by week, a typical card's (`Reviews` in builder.js, its curve
  `ahead.GENERIC`'s cards, the suite checks the twins): "About 380 reviews a
  day by week 4 · Week by week: ...", cards never minutes. Share › Copy for
  next year: a copy of my own with every date 52 weeks on, weekdays kept
  (the existing copy, its first date set for me).
- 3.9.2, the Cheer window's "pick one" (Sam: "the custom picker doesn't
  accept the custom emoji choices"): the Mac's Character Viewer can't type
  into Anki's web page, so a Qt box of ours sits exactly over the page's
  (`native_emoji.catch`, the page's place and zoom), focused, takes the
  pick and hands it to the page (`window.dcCheerPicked`); Esc, the window's
  close or two minutes put it away. And Pip on a fridge Polaroid's caption
  is no longer clipped (Sam: "pips get cutoff on the polaroids"): the line
  never clips, only the name shortens, and Pip's slot has its head's room.
- 3.9.2, the Polaroids (Sam: "some of the dates on polaroids are wrong",
  "also need dark mode for polaroids"). A cheer's `at` comes from the server
  in UTC and the Polaroid showed its first ten characters, the UTC date, so
  a doodle sent on an American evening was dated the next day:
  `board._short_day` reads a moment on this computer's clock now (a plain
  day stays that day), and the quiet fold's month too. At night a
  Polaroid's frame and photo go dark, as Settings › Theme says (Match Anki:
  its night mode and the computer's): its colours are tokens on each one
  (`FRIDGE_LIGHT`, `FRIDGE_DARK`), a doodle's black ink reads light and each
  colour takes its night shade (`FRIDGE_INKS`, the board's own), and Pip and
  Undo the sender's night accent (`--fd` beside `--fa`). A theme change
  draws the fridge again (it's kept as last drawn).
- 3.9.2, the map by when I started them, by topic (Sam, on its week names:
  "the organization from when you started something tag name by original
  deck isn't helpful ... should be organized by topic"). A week is named by
  the map's own way only (`team.way_of`: a tag's family up to its first
  resource mark, or plain tags), the deepest of its topics a third of the
  week shares, else its two biggest ("21–27 Sep · Renal, GI"), else just its
  dates; never by the deck a card first came from, nor the way's own root.
  It opens into those topics, and each Browses that week's cards alone (the
  audit: a topic in it opened every card of the deck with its tag). The
  tiles are the last 8 weeks I started cards in, however long ago (a deck
  finished months back had none in 8 calendar weeks, one tile, and the pick
  did nothing). A card started but never reviewed is "too soon" on the map,
  not 100% (its last answer was the pass that graduated it, so the newest
  week read best known), on the picture card and its text too.
- 3.9.2, the release audit (Sam: "everything we ship must actually work, and
  shouldn't be something we've not got right yet"): four reviews of the
  release, Stop new and the leech buttons run on Anki's own engine
  (`tools/real_anki.py`'s `check_392`), and what they found fixed:
  Stop new says what the pause I made does (`pause` on the view: its kind,
  its exam; "to the exam" only for an exam ahead, named at any distance; the
  week before it, from its first day), one undo step for a deck and its
  subdecks (and none when nothing changes), set before I study too
  (`ahead_flow.on_state`: not signed in, or the morning waiting for
  AnkiWeb), a stop that holds nothing back isn't offered, today's bar
  counts a card still in its steps once, the track record caps a week I took
  off (never "within 411%"), and a plan's Raise, Catch up and Why stand aside
  for it (`ahead_flow.paused`: the plan card says new cards are stopped, with
  Turn them back on). Leeches: a miss away at Anki's own steps (half the
  threshold rounded up: at 5, 8, 11), a relearning card isn't one, a note
  keeps its leech tag while another of its cards is still out, the view is
  worked out again when the collection changed (`col.mod`), a card deleted
  since is no error, each card's front is its own question as Anki draws it
  (a reversed card's, a cloze's asked part hidden), and Leave it out has its
  way back at the foot of the list. The exam: "nothing at risk" only when
  FSRS looked (it's FSRS's), "Anki aims for 90%" only with FSRS on, the next
  exam set on the last one's day keeps it as the last, an upcoming exam
  moved keeps its scope, and a start is a real answer. A profile switch
  empties the views kept by deck id (the Default deck is 1 everywhere). The
  Cheer window's box over "pick one" goes with a quick pick, a scroll, a
  resize or a new page. The builder: Copy for next year copies the plan as
  saved (a save first; its first date from the saved plan, 364 days on), says
  a full account, and the reviews line's busiest week is one its list shows.
  No third-party deck or video names in code or tests (CLAUDE.md). Stop new
  is offered only on Anki's v3 scheduler (`ahead_flow._v3`: the old v2 has
  no today-only limit), and `docs/manual-anki-checklist.md` has the release's
  short click-test pass.
- 3.9.2, four small ones Sam okayed (19 Oct, "anything easy that requires me
  to approve first"). Tag Only leeches: since Anki 23.10 a preset's leech
  action is Tag Only, so Anki tags a leech and keeps showing it, and
  Insights' leeches line showed nothing for most new decks. They're counted
  now ("N leeches still in your reviews · See them") and listed last in the
  same view: a tagged card at its deck's leech count or past it, in a deck
  that tags (`leech_flow._kept`; a tag a shared deck shipped isn't one, nor a
  card I unsuspended by hand in a deck that suspends), with Learn it fresh,
  Edit and Leave it out behind its ⋯ and no Bring back (it never left); a
  note keeps its tag while another of its cards is one. Checked on Anki's
  engine: the eighth miss tags it and keeps it in relearning. The map by
  when I started them, when everything started in one week: one tile says
  nothing, so the map stays by topic and says why ("Everything you've
  started is from one week"). Copy for next year names the copy "… (next
  year)", not "(copy)": the builder renames it right after, the name alone
  (`library.test.ts` holds the call); its plan tags keep the root the copy
  took. The Cheer window's Other takes the emoji that are older than emoji
  (©, ®, ‼, ⁉, ™, ℹ, as the computer's picker sends them:
  `shapes.EMOJI_LOW`, `native_emoji.first_emoji`, the window's `oneEmoji`);
  a keycap (1️⃣) still isn't one, as the Worker counts.
- 3.9.2, the last QoL pass (Sam: "last check for little things"; three
  reviewers and a look at every new screen). The release blocker it found:
  the Cheer window did nothing (a `var moved` overwrote the scroll/resize
  handler the audit added, so every close threw); the handler is `away`
  and the suite now runs the window in node (`tests/fake_dom.js`, real
  EventTargets) through a quick pick and Send, Cancel, Esc, the backdrop
  and the computer's picker. Stop new: a pause that ends or moves (the exam
  moved or went, here or from another computer) takes today's 0 off at once
  and puts a catch-up's limit back (`ahead_flow.exam_moved`, the morning's
  idle pauses); Turn back on says so, is one undo step with the catch-up's
  limit in it, and the plan card's line follows; a stop that hasn't begun
  says "Keep them on", is named from its own day even past the chart, and
  never shows as "Paused" or compares a number with itself; an exam today
  isn't one ahead. Why names the deck the stop is on. Leeches: Insights'
  line counts as the collection is now (`leech_flow.line_counts`), keeps a
  way back when every one is left out, says "one miss from a leech" alone,
  and a sync's new tips work the open view out again; See ahead opens
  Insights, not a leeches view left open; the daily climb check waits when
  no board is drawn. Words: one card / one time, days with their month, an
  old leech's year, the scope's links apart and its picker stopping at
  today, the minutes with the weeks they're for ("1h 13m"), the map's key
  wrapping between its parts at phone width and naming the bar only when
  one shows, a leech's last day by my rollover. The Cheer window: England's,
  Scotland's and Wales's flags whole, a letter of any script (あ, 中) never
  an emoji (Python and the page agree, the suite runs both), Tab stays in
  the window and the board's sheets, focus goes back to what opened them,
  a quick pick keeps the key, Enter in Sign sends, the computer's picker
  hands the keys back to the page; a Polaroid's × is reachable by Tab. The
  builder: next year's copy never "(next year) (next year)" or "(copy)
  (next year)", cut at a word; offline and "no dates" said as themselves;
  a break between a plan's parts reads "0 for 24 weeks".
- 3.9.2, no error window offline (Sam's report, 19 Oct: Anki's error window
  with "GET /settings failed"). `app._bg` printed every exception's
  traceback, and Anki shows anything on stderr in its error window, so a
  settings pull (or any background request) that got no answer looked like
  a crash. A TransportError is now one line on stdout, as the refresh's
  already was; a real bug still prints its traceback.
  `test_offline_stays_off_stderr_v392` runs `_bg` both ways and checks no
  handler that prints a traceback around a request lets a TransportError
  reach it.
- 3.9.3, one leech is "it" (Sam, of Due's "Recovered 1 leech as new cards ·
  See them": "for a singular recovered card, should be 'see it'"). Due's
  morning note says "Recovered 1 leech as a new card · See it", the toast
  when Recover leeches is switched on "1 leech back as a new card. Edit ›
  Undo puts it back.", and Insights' leech line "See it" when it names one
  card. `test_one_leech_is_it_v393`.
- 3.9.3, Today's bars (Sam: "a similar progress bar for reviews as appears
  with the new cards... perhaps all of them should fill as cards are pushed
  to at least tomorrow"; the Today's Bars mock, his yes to its picks). One
  rule for every bar in the Today box: a card fills its bar once it's
  through for today, answered and next due tomorrow or later; answered and
  back later today (learning, relearning) is the bar's lighter part, so the
  bar moves with every answer and fills only when the day's done. Each bar
  is its row's, under its words and numbers, the row's whole width, so the
  bars line up. **Reviews** has a bar: the cards due from before today
  (reviews, relearning, learning carried in from an earlier day), "84 /
  140", and once started a line with the ones back later today and the ones
  due now ("6 back at 14:30 · 50 still due"). **A plan's date** counts the
  same way and ticks itself when its bar is full ("all done"; it said "all
  seen"); a date behind still counts what's been seen, so a card in its
  steps today doesn't put it behind. **New cards** (no plan's date today):
  the ones started today (a new card's first answer: type 0, lastIvl 0 in
  the revlog, checked on Anki's own engine) and what Anki's limits still
  give, a line a top deck when there's more than one. On a plan's day, the
  plan's dates are the new cards; **Other new cards** shows only once I've
  started some none of today's dates holds, so their steps keep the day
  open as the Reviews row did for every learning card (3.8.0). The plan's
  progress, the crew's "N of M done" and the server stay on "seen": they're
  about what's covered. Where: `due_flow.bars` (one pass over today's
  answers and today's learning cards; `_reviews` keeps Study today's
  count), `plans.DeckIndex.again` (a date's cards in their steps today,
  from the read it already makes) and `P.parts`' fourth number,
  `due_flow.parts` (`plan_later`, `plan_today`), `due.reviews_row` /
  `new_row` / `through`, `board._due_reviews` / `_due_new` / `_wbar2`;
  motion.js gives a bar's light part its own key (both copies). A count
  from before 3.9.3 still draws as a number. `test_todays_bars_v393`.
- 3.9.3, one meaning of a leech (Sam's pick A: Recover leeches took a
  leech at a fixed 8 lapses, Insights' Leeches at the deck's own count,
  so a deck at 5 showed 61 "still in your reviews" Recover never took).
  Recover leeches now takes a suspended leech, or one Anki kept in my
  reviews at its deck's leech count (`due_flow.leech_sets`, the deck's
  options read as `leech_flow._limits` reads them), never one I left out
  (Leeches' Leave it out). The first morning it would take ones the old
  line left, it takes what it always took and asks once on the board
  (`ask_reach`: "Learn 61 more leeches fresh?", Learn them fresh · Not
  these), the answer kept in this profile's plans.json (`leech_reach`:
  "deck", or "eight" to keep to 8 lapses); with nothing the old line
  left there's no question. Switching Recover off and on asks again.
  Settings › Due says which line it uses. `sheets.confirm` takes a
  `no_label` for the board's Cancel. `test_recover_by_deck_count_v393`.
- 3.9.3, a card counted once (Sam's pick: a date with a video's tag and a
  system's on the same notes read "14 of 28" in the Follow window with
  nothing missing). A date's count (`n`) is still the builder's, each tag's
  and subdeck's cards added up: the site has a count per tag, not which
  cards a tag holds, so it can't see two tags share them. The follower's
  Anki now counts its own copy the same way to find what's missing, then
  says it as cards (`plans._missing`): "14 of 14", or "12 of 14" with two
  notes gone. The site's numbers for such a date (the builder's load, the
  plan page, the calendar feed) still count a shared card twice.
- 3.9.3, Your plans for everyone, and the builder in Anki (Sam: "the plans
  one which doesn't actually need claude we can try to find a way to
  integrate into the public release"; then "go with your picks... your goal
  is to duplicate the website plans functionality in the add on"). The
  labs windows open for anyone signed in, named as the proposals page
  picked: Your plans (the plan window), New plan from a calendar, Missed
  questions (Question IDs). Ways in: Tools › Due Crew › Plans (a submenu
  with Follow a plan, New plan from a deck and Export cards for my AI), You
  › Plans' head row (Open plans, New plan ▾) and each card's Open, an
  Insights line for a deck with a bank's question tags (Missed questions),
  and Find a setting (`board.FIND_WINDOWS`; `planyours`, `plannew`,
  `planstart`, `planmissed`). Labs keeps Claude's stand-in and What Claude
  would get. Your plans has tabs. **Dates**: the builder's day panel as
  Change ▾ and New ▾ (a search or IDs, notes: and cards:, Suggested from
  its name, Split by its tags or evenly, a cut, without its extras, a note
  on a tag, prep for, spread evenly, to-dos, review days, quizzes and
  exams). **Lay it out**, for authors (`layout_tab.py`): What to cover by
  resource, system, the rest or subdecks (a tag holding two views covers
  this view's part of it), the pace (Starts moves every date, study days,
  Finish by a date or an event, Cards a day, placed by hand), Fill and Just
  next week (to an end, a tenth more a day until it fits, seven tries), Put
  it on a day (the builder's +), the day over the pace with Split and Give
  it till, the reviews line, the plan's own tags (rename and delete: the
  dates, cuts, searches, notes and names using them follow), Every week,
  Notes on cards. Ticks and the pace wait in the tab until Fill or Save the
  pace, one save, and a save tried again on someone else's uses what was
  set at the click. New plan from a deck makes the plan in Anki (a name,
  Make the plan, then Your plans on it at Lay it out; Open the builder
  instead is the site). The builder's rules are restated in
  `planner/build.py` and its edits in `planner/edits.py`, twins of
  builder.js (`test_builder_twins_v393` runs builder.js's Todo, Every,
  Remarks, Picks, Suggest, Work, Reviews and Tags in node against them);
  Fill, layOut and the tag edits are checked by hand-worked plans
  (`test_build_fill_v393`, `test_lay_out_v393`, `test_plan_edits_v393`).
  **Text**, for authors (`text_tab.py`, `text.py`, builder.js's toText and
  fromText restated): Add dates and Edit the whole plan, Read it's
  preview (moved, renamed, what goes, a tag a date still uses with Take
  them off those dates too or Keep the tags, a day over the pace), one
  save read again on the plan as it is (`test_plan_text_v393`). The
  window's height stays the window's: Lay it out's right side scrolls, and
  Text sits in a splitter with smaller size hints. **Updates** (posts to
  followers, five a day, taken back) and **History** (every save, Undo the
  latest), `history_tab.py`; the fake Worker gained plans.ts's log and
  posts (`test_history_and_posts_v393`). A history line says "1 search",
  not "1 searche". **Progress** (its squad's counts a date, three in it or
  more; the dates most of the class hasn't finished, with Look at that day
  and Give the class a day) and **Settings** (name and line, the deck's
  link, a squad and who can follow, co-authors asked from my crew, handed
  it, taken off or leaving, the end, catch-up weeks, review-only days, the
  library, Copy for next year, Delete), `settings_tab.py`; the fake Worker
  gained progress, listed, copy, delete and audience/squad in a save, and
  reads a follow's progress as the JSON text the Worker keeps
  (`test_settings_edits_v393`, `test_settings_remote_v393`). **Notes on a
  day** (`day_notes.py`), under a date, a quiz or a review day on Dates and
  by day under a week: read once when a plan is picked, added (one line),
  taken off by their writer or an author, authors only on a plan in the
  library; the fake Worker gained plans.ts's notes (`test_day_notes_v393`).
  Still the site's: the AI prompts. No new route, nothing on a refresh or a
  sync.
- 3.9.3, Your plans checked over (Sam: "check your work and find places to
  add pip / make things friendlier, clearer, and more efficient"). Three
  reviews of the new windows, then: **Pip and words**: with no plans, a
  welcome with Pip waving (as Settings › Pip says) and the three ways to
  start; Progress's "Nobody follows it yet" and, with no date behind,
  "The class is keeping up with every date so far." with Pip cheering; a
  tab's words go when another opens; one Undo on History. **Data**: Split
  by its tags kept the date it split (it made new ones, and the name, due
  date, prep, to-dos, review day and followers' progress went with the old
  id); an answer that comes back for a plan no longer picked is dropped,
  and Progress, History and Updates read again when the plan changed under
  them; the window closes at sign-out. Text says a day that isn't one on
  its own line and cuts names as the Worker counts them (an emoji whole);
  Settings keeps what's typed across a reload, and a wheel scrolls its
  page, not its boxes; Enter twice posts an update once. **Lay it out**:
  the dates are named as the site names them (`build.tag_word`, Tags.word:
  "5 · Renal", "Step 1"; one `build.auto_name` with cut names; renameAll
  on every save, `edits.name_dates`, so "· the rest" and a renamed plan
  tag reach the names, and a typed name stays), and the tree sorts as the
  site's (`build.natural`, localeCompare's order, checked in node on
  every pair). The pace saves as the builder saves it (5,000 a day at most,
  the top ticks in the deck's order, 500 at most: a Fill to a near end
  date was refused before); ticks that didn't save wait still; the day over
  the pace is one that isn't past; a plan with an end and no pace opens as
  Finish by; the start waits for a typed date, and a wheel over it
  scrolls; "²" in a cards: line is a bad token, not a crash; a cut's
  search goes on a date once. Fill says "Put 1 card on Mon 9 Nov." and
  "from … to …", and what to do about what didn't fit, on the site too
  (putWords). **Speed** on a big shared deck (12,244 tags, 60 dates):
  placed keys 1.8 s to 0.03, a Finish by date at every pace step 1.8 s to
  0.008, a Fill to an end date 7 s to 0.4 (the extras map worked out once
  a tree, `build.Placed` looking up above and below instead of scanning);
  the deck's index and tree kept through a save; searches wait for a
  pause in the typing; Change ▾ is built when it opens. No new route.
  `test_lay_out_review_fixes_v393`, `test_text_review_fixes_v393`,
  `test_split_keeps_the_date_v393`; `tools/dialogs.py` checks the welcome,
  the kept ticks and Finish by.
- 3.9.3, Pip in three more places of Your plans (Sam: "add the pip spots you
  suggested"): hopping beside Lay it out's words after a Fill that puts
  everything ticked on a date; waving beside "Posted." on Updates; peeking
  into a new plan's History ("No saves yet. Each one shows here, who made
  it and what it changed, and the latest can be undone."). Still, as
  Settings › Pip says, by `planner/pip_note.PipNote` (a line of words; the
  next words take Pip away). A Fill's words now show once it saved: one
  that didn't save no longer says it put cards (the window's foot says
  why), and Updates' "Posted." goes when another plan is picked.
  `tools/dialogs.py` renders each, and History with Settings › Pip off.
- 3.9.3, round five: Your plans rebuilt as one screen (Sam's ten picks on
  the "Simpler Plan Builder" page, all A, after four reviewers' pass; the
  mocks are its v2). **Every change is an op** (`planner/ops.py`: a small
  JSON object naming a date by its id, day or name, checked, run by the
  builder's own edits, said in words, with who it touches): the window's,
  a pasted calendar's and an AI's alike. **Changes wait to be sent** when
  anyone follows the plan (`draft.py`, kept per profile in
  `plan_drafts.json`, replayed on the plan as the server has it so a
  co-author's save or a restart loses nothing; one that no longer fits is
  dropped and said): "3 changes, not sent", Review and send (each change in
  words, who it touches, a ✕ each, Tell them why filled in), one save with
  its line to followers (`PUT /plans/{id}`'s `post`; the fake Worker
  gained postWithSave), Undo ▾ takes the whole send back. With nobody
  following, a change saves at once. **Tabs**: Plan · Followers · Sharing
  for authors, Plan · Mine for a follower; Dates, Lay it out and Text
  became the Plan tab (the deck beside the plan, `deck_panel.py`, ticking
  for the picked date or for what the plan covers, with Fit them before
  the exam when they'd run past it; the text a window of its own; History
  under Undo ▾). **The plan's shape** on one line with Change… (`shape.py`:
  start, end, study days, new cards, the last days, catch-up weeks; it says
  what moves first). **Each week** says what it asks (new cards and a
  typical card's reviews a day, amber with its fixes when over the pace,
  `view.py`). **A date** is changed where it's shown (`date_panel.py`:
  fields, −1/+1 day, This and every date after, its cards as chips with ✕,
  the rest under ⋯ in plain words). **No suggestions** of what goes on a date
  (Sam's call after the picks: plain rules aren't trusted to choose cards
  and it isn't AI), so a calendar's sessions, pasted or in New plan,
  become named dates with no cards, and the author puts every card on. **Followers** shows how many follow,
  whose Anki has the last send, and the posts; how far each date's class
  is came out (Sam's call: it added nothing; followers meet in the plan's
  squad). **The windows keep their size**: `ui._fit` grew a window to its
  wrapped words' height at every layout change, so each redraw of Your
  plans grew it toward the screen's height; a window that scrolls its
  own (`dcOwnSize`) grows only to its rows' minimum, opens sized to the
  screen (`widgets.fit`), and the renders fail any window past a
  1280x800 screen. Month is seven even columns, each name one line cut
  with … (`widgets.Elided`), two a day and +N more. **One New plan** (`new_plan.py`: name, deck, the exam it ends
  with, the calendar if there is one, read as it's typed; a friend's code
  instead) in place of New plan from a calendar and from a deck (the
  calendar window stays in labs). **A paste box** for plan lines or a new
  calendar, Edit the whole plan as text, and Copy a prompt for your AI
  (Plan the dates, Tag by objective: `prompts.py`, builder.js's Prompts
  restated, a twin). **No Pip in the plan windows** (pick 10;
  `pip_note.py` went). Behind the scenes, **the AI hooks** (`ai.py`: jobs
  whose requests carry tag names and counts, never a card; answers checked
  into ops; runners off, the stand-in in labs, your own AI by a copied
  prompt, Claude once connected) and **Your AI app** (`mcp.py`, off by
  default: a local MCP server on 127.0.0.1 with a bearer token that reads
  my plans and puts changes under one for me to send, never sending; a
  stdio shim). New ops beyond the builder's edits: `lay_out` (Fill as one
  change), `move_from`, `add_date` with no cards (`edits.add_empty_date`;
  the server keeps a date with none). Nothing new on the server.
  `tests/test_plan_ops.py`; `tools/dialogs.py` renders every state.
  **Then plain and quick** (Sam, after the site mock: "a few of our UI
  elements are AI hallmarks; we are going for extreme functionality"):
  the accent stripe on the picked row and today, the tinted banners (the
  shape, today and behind, the deck's target, the send bar, the code),
  chips, ◆, "+ A …" links, capitals for a change's kind, ▾ and ↗ in words,
  and lines that explained a control all went. The shape is label by
  label; a date's sources are a muted line in the list and a list (name,
  count, ✕) in the panel; a quiz is one line; adds are buttons that say
  what they do (the list's adds one Add menu in the toolbar); a button
  with a menu has the boxes' chevron (`ui.QSS` `dc="menu"`); explanations
  are tips. And quicker: **keys** (Ctrl+N a date, Ctrl+E a quiz, Ctrl+F
  Find, Ctrl+T Today, Ctrl+1/2 List/Month, Ctrl+D the deck, Ctrl+Z the
  last change not sent, Ctrl+Return Review and send; on the plan, ↑ ↓,
  Alt+← → a day, Enter/F2 its name, Delete), **Find** a date or tag,
  **Month's drag** to move a date or a quiz, the foot's **changes as
  links** to their dates, a double-click for a name.
  **Then one way to each thing** (Sam, at the click-test): no Followers
  tab (how many follow, and Posts…, are a line of Settings; the "last
  send is in N of M followers' Anki" line went with it); **Sharing became
  Settings**, with the plan's dates and pace in it as rows (no Change…
  window; Put it back), its every-week lines and Your AI app; a
  follower's Mine is their Settings. No deck tab: Add from the deck puts
  the deck in the date's place (Done brings the date back), Add › Lay out
  from the deck… with none picked. No Study them / Study these / Study for
  it (the board studies), no −1/+1 day (the date's field, Alt+← →,
  Month's drag), no ⋯ Split its biggest tag / Make it a review day /
  per-source extras (each source's own menu, Add › A review day), no
  row's Add from the deck link. Expand all / Collapse all for the weeks;
  List | Month first in the toolbar, over the list; Earliest first /
  Latest first. One button: every action the boxes' corners and height
  (`widgets.tool`), side-by-side choices one control rounded at its ends
  (`widgets.segs`), tabs underlined; a link is only a way to a date.
  **Then Insights** (Sam, before the click-test: "the tab we should have
  between plan and settings is an insights tab on workload / content /
  amount of the deck relative to the whole"), `planner/insights.py` (pure)
  and `insights_tab.py`, for authors and followers alike, worked out when
  it's looked at, never sent: **Workload**, a row a week from the first to
  the end, new cards a study day against the pace (a line down the
  column; a week over it amber, with its busiest day) and reviews a day,
  each on its own scale and never added (a study day and a day aren't the
  same day; Sam asked for the pictures to be thought through, and a first
  stacked bar summed the two), the week's quiz or exam beside it, the
  busiest week by its whole; **How much of the deck**, the plan's cards of
  the deck's as one bar (a follower's: seen, then to go), and of each part
  (a big shared deck's resources and its systems, else subdecks, else top
  tags) drawn on one scale, so a big part looks big, and the parts it
  holds none of named; **What's in it**, each quiz or exam and what its
  dates hold, the biggest dates (a click: that one on the Plan tab), cards
  on two dates, leeches that stay shut. `test_insights_tab`; renders with
  and without a pace, and a follower's. Then the deck's parts as the
  topic map's (Sam: "we need better insights … same organization problem
  we had for the bento where we're choosing to highlight strange
  resources"): the first cut took a tag's # part as a resource and the
  part under its ^ as a system, so a big shared deck showed its banks and
  sketch series side by side as if they split it. Now `team.subjects_by`
  over the whole deck chooses (the map's rules: topics over ratings, a
  bank's ids never), By ▾ is the map's own pick for the deck, the parts
  the plan holds come most held first, and the part it's mostly in
  opens into its own parts ("Inside Cardio", the ones left out named).
  Then the deck beside the plan (Sam, a screenshot of "helminth" found
  seven times as the same "Step 1 › B&B › 14 · Infectious Disease › 5 ·
  Parasites an…": "if in the search some tags are nested to each other,
  let's keep that structure"): a search matched every tag whose path had
  the word, so all of a found tag's children came too, flat and cut off
  at the right. Now a tag is found by its own name (or across parts of
  its path, from where the words start), each find sits under the tags
  above it, a line of tags with one way down reads as one row
  (`widgets.fit_parts`: "B&B › … › 5 · Parasites and Helminths", whole
  parts dropped from the middle as the panel narrows), a find with finds
  below it shows them, one without opens onto its own parts. By resource
  and By system narrow the search to their tags (before, they changed
  nothing while it was on), and a view without the word says which has
  it ("By system has 4", a click). And the buttons themselves ("check on
  these buttons"): `segs` marked each button's place with a property
  named `pos`, which is every widget's own position, so no rule for the
  rounded ends or the shared edge ever matched, and every side-by-side
  choice in Your plans drew as boxes stuck together; it's `seg` now, the
  edge between two keeps its width as the tick moves (no 1px shuffle),
  and More, which a click ticked while its menu was open, is ticked only
  while one of its own views shows.
  Then the board's You › Plans (Sam: "let's also consider the optimal UI
  for this surface", then "what happens when you click on a date?
  worried about overlap with the today page"): a day's click on the
  Plans tab's week opened what Due's Today and Upcoming already listed,
  so the dates now live there alone, and each opens its details under
  it, a click on its name (`board._date_more`: Browse its cards, the
  ones left, Open now ahead of its day or shut again, Move…, Skip it,
  Put it back, why it left cards shut; Upcoming's with its topics too).
  `due_flow.plan_dates` carries what they need (`moved`, `shut`, `why`,
  `own`) and `due._date_row` hands them on. The Plans tab is the plan's
  own card: its name, Your plans… (the head row's Open plans and New plan
  ▾ went, and the card's Open and Plan ▾: a follow's every setting is
  Your plans' Settings, whose More now has the next-once-seen pace, My
  schedule… and Reset to default…), its day in a line
  (`card_view`'s `status`, `board._plan_status`: "24 to go today, and 54
  behind since Monday", Catch up…; a catch-up running isn't called
  behind, and the older "new from earlier days waiting" note goes when
  the line has Catch up…), a quiz coming, the next exam's cards at risk
  (no Insights ›, the tab beside it), one note, its squad. The week stays
  for Due's lists off, and for the day Browse › Show on my plan asks for
  (with Done, no ‹ Today ›: a step lets the day go); no Month ↗. With no
  plan followed, the ways in end with Your plans… for the plans I write.
  `test_date_details_round5`; the plan card's checks in
  `test_plans_tab_v341`; renders in `tools/preview.py`.
  Then the tab again (Sam: "i don't know that I prefer this new plans
  tab, give some alternative options", five mocked on the spec page, and
  "let's go with option A and when a day is clicked, the full
  assignments for that day open in that plans tab (animate in and
  out)"): A, seven small days. Under its day's line, This week ‹ Today ›
  and the days (`board._week_html`), each its bar (amber when it's
  behind) and what's left ("16 left", "24 to go", "38 new", ✓, rest; a
  rest day keeps the bar's place, so every day's words sit on one
  line), a quiz's name under its day; narrow, the words go and a quiz
  day is underlined. A day's click opens its assignments under the week,
  whole: each date (`_day_unit`: its name, moved or for its quiz, seen of
  its cards and its bar, its topics by resource opening Browse with the
  authors' notes, the authors' lines by `_todo_lines`, a link opening by
  Due's `duelink` key, so `plans.week_view` carries `todo`; Browse, the
  ones left, Open now, Study, Move…, Skip it, Put it back, Undo skip,
  why it left cards shut) and a quiz by name (`_day_event`: Study for it
  stays the quiz row under the week, one way to it). The same click
  shuts them; another day's switches. motion.js 8 (the site's copy too)
  unfolds them, folds them on the second click (`shutDay`), and on a
  switch slides the ring and the words over while the box grows or
  shrinks from the last day's height; nothing with Reduce motion. The
  week shows with Due's lists on or off (last round's Done went), and
  Show on my plan's day opens in it. A day's Push my dates back… went:
  Settings › My dates has it. Today's and Upcoming's details on a date's
  name stay. `test_plans_tab_v341`, `test_plan_load_3781`;
  `tools/motion_preview.py`'s dayshut and dayswitch (the audit measures
  both); renders in `tools/preview.py`.
  Then two plans followed (Sam: "with multiple plans, we don't need two
  buttons for your plans. doesn't make too much sense. think through how
  to best present", four ways mocked on the spec page, then "Let's go
  with 3"): one at a time. With two or more, the card's head is their
  names as a switch (`board._plan_switch`: the one shown pressed, an
  amber dot on any that's behind, a catch-up running isn't; a name two
  plans share shows their whole titles), the shown plan's line ("week 3
  of 9 · 6 following") and one Your plans… on it; under it that plan's
  card as one plan has it. Which one: the plan Browse › Show on my plan
  jumped to, else this computer's pick (`plan_pick`, config; `planpick`
  sets it, lets a jumped-to day go and redraws; Show on my plan sets it
  too, so its plan stays shown), else the first (`board._picked_plan`).
  `card_view` carries the plan's `name` for the switch. One plan: as
  built. Switching slides (Sam: "switching plans should definitely
  slide"): motion.js 8's `.psw` rule moves the pressed name over, slides
  the plan in from its name's side and takes the box to its height.
  `test_plan_switch_round5`; `tools/motion_preview.py`'s planpick (the
  audit measures it); renders in `tools/preview.py`.
- 3.9.3, QBank QIDs (Sam, on Missed questions: "this is some …
  awesome functionality that others have specific add ons for", "We also
  have some overly-explanatory language here that doesn't trust the
  user", "should we put this in a more accessible place?"; options on the
  spec page, then "Let's go with 1 but maybe like QBank QIDs?"). The
  window is QBank QIDs now (`planner/qid_window.py`), opened from Today's
  head (`board._due_html`, `planmissed` with no deck: the one my plan runs
  on), shown only when a tag here ends in a question's number
  (`due_flow.has_qids`: Anki's tag list, not the notes, read once a
  profile and day), and from Insights' line, Tools › Due Crew › Plans and
  Find a setting as before. No intro and no privacy line; the counts in
  Anki's words ("5 questions · 14 cards · 10 suspended") with Browse
  after them (`qids.words`). Bring back went (Sam: "i just don't
  understand why it would do it over the next three days", then "we just
  do study now which then resets their intervals"): nothing moves a due
  date. Two buttons: Unsuspend N (new ones first in line,
  `actions.unsuspend`) and Study now, which unsuspends them and builds a
  Due Crew filtered deck over what's in it already and these, so each
  paste adds to it ("or add to a misses deck ya know"; named QBank cards,
  Sam: "not necessarily Missed Questions always"), rescheduling by my
  answers, one undo step (`actions.study`), then Anki's Study screen on
  it; Sam's line under it, "Study now adds them to Due Crew › QBank
  cards. Each card goes back to its own deck once you've done it." This
  paste only (Sam: "get rid of all 41 so far option"): All my misses,
  Forget and `qids.json` went, nothing is kept. In common went too (Sam:
  "this should be covered under insights"): what's not sticking is
  Insights' to say, from my answers. Which bank (Sam: "what does bank
  mean here?", then "yeah do both"): asked only when it's close, the
  runner-up with half as many of the numbers or more (`qids.close`; one
  stray number in another bank used to bring the box up), and labelled
  Question bank. `tests/test_planner.py`
  (`test_unsuspend_and_study`, `test_nothing_kept`, the glue),
  `test_due_crew`'s ways in; `tools/real_anki.py` runs both on Anki's
  engine (one undo step each, the second paste adding to the deck, undo
  taking both back whole); renders in `tools/dialogs.py`.
- 3.9.3, no Study today (Sam: "let's get rid of study today on the top
  right also"): the Due box's head and its folded line lose it, and with
  it the name of the deck it opened first (motion.js 35, `_next_deck`,
  `study_to`). Ctrl+Shift+S still walks the day (`due_flow.study_today`),
  a Fifteen still starts it, and a date's own Study stays.
