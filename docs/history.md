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
