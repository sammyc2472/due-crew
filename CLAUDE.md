# Due Crew — project context

Consent-based friends leaderboard add-on for Anki. Sam is the sole
maintainer. The repo is the source of truth; there is no build step for the
add-on.

## Layout

- `due_crew/` — the add-on. `__init__.py` (hooks/glue, main-thread rules in
  its docstring), `board/` (pure HTML rendering; since 3.9.8 a package by
  feature: `base`, `style`, `crew`, `squads`, `plancards`, `planweek`,
  `insights`, `party`, `due`, `settings`, `closet`, `scrapbook`, `pip`,
  `lobby`, `cheers`, `fridge`, `dance`, `windows`, `page`, `draw` (render);
  one namespace, so `board.X` reads as before), `backend/` (`api.py`,
  the Worker client; `shapes.py`, the pure helpers and payload shapes),
  `stats/` (local SQL), `ui/` (Qt dialogs).
- `worker/` — the server (3.0): one Cloudflare Worker in TypeScript on D1,
  served at `https://api.duecrew.com` (a dev one at `api-dev.duecrew.com`).
  Consent, shapes, sign-in by emailed code, and sessions all live here;
  `worker/README.md` has the API, `migrations/` the schema.
  `docs/cloudflare-setup.md` is the one-time setup (Sam's). The 2.x
  backend (Firebase) is gone since 3.8.0.
  `worker/` and `site/` are PolyForm Shield 1.0.0 (their LICENSE.md) since
  29 Sep 2026: readable and runnable, not for a competing service. The
  add-on, tests and tools stay MIT (root LICENSE), but for the logo's and
  Pip's artwork (`docs/logo/`, `docs/images/`, `logo.py`, `sev.py`,
  `closet_art.py` and their copies in `site/`), all rights reserved since
  17 Oct 2026; the name, logo and Pip are trademarks (README's "Name, logo
  and Pip"). A new file that draws Pip or the logo joins that list in the
  root LICENSE.
- `site/` — duecrew.com: the landing page, and the app (`public/app.*`,
  plain JS, no framework: sign-in, plans, the builder). Its Worker
  (`site/src/index.ts`) sends `/api/*` to the API by service binding, so
  the site's session is a same-site HttpOnly cookie, and draws a plan
  link's preview (`site/src/og.ts`). Pip Party (3.9.5; called Game night
  until 3.9.5's last round, still gamenight in code): started from You ›
  Pip Party alone (Tools › Due Crew opens the tab), the TV is a window of
  Anki's (`gamenight_flow.py`, `ui/game_night_tv.py`) running the site's `/t/CODE#anki` page (`public/table.*`) on a pack of
  your own cards (`gamenight.py`); phones join at `/t/CODE`; its tables a
  Durable Object on the API (`worker/src/table.ts`).
- `README.md` — from the tagline down, doubles verbatim as the AnkiWeb
  listing description; keep them in sync when it changes. The logo block
  above the tagline is GitHub-only (AnkiWeb shows its own title).
  Its images live in `docs/images/` and are linked by full
  raw.githubusercontent.com URLs on `main`, so the same text works on
  AnkiWeb. They're renders of the add-on's own board, overlays and room
  widget (sample crew), not mockups; re-render them when those change
  (board.png: `tools/readme_images.py`, then `node tools/readme_images.js`).
- `docs/logo/` — the logo ("Seven days"), final artwork: never redraw or
  re-typeset it. Green on GitHub; inside the add-on, `due_crew/logo.py`
  colours the studied days with the user's accent: the board's title is
  the one-line logo (inline SVG on the `--dc-*` tokens), and the stacked
  one tops the sign-in and welcome screens.
- `due_crew/planner/` — `docs/planner.md`: Your plans (the duecrew.com
  builder in Anki; round six: a page in the board's look, `web.py` a
  Qt shell on Anki's web view, `webface.py` its clicks ("dcplan:" + JSON),
  `webmodel.py`/`webtabs.py`/`webnew.py` its pure views, `page/` its
  scripts; `core.PlanCore` its logic (the Qt plan window went in
  3.9.9; two Qt windows it still opens, the plan as text and Move from
  here, stay: `text_tab.py`, `date_dialogs.py`); New plan its first screen: a
  resource at my pace, someone's plan, start empty; round five: Plan · Insights · Settings (Insights: the
  workload by week, how much of the deck and of each part, what's in it;
  an author's Settings: the plan's dates and pace, sharing, posts; a
  follower's: my follow), Undo on top, no Pip, one way to each thing), New plan (one way
  to start: a name, the deck, the exam it ends with, the calendar if
  there is one)
  (QBank QIDs was one till 3.9.7: Magic search's now, `planner/qids.py`
  its find), Python-native, for everyone signed
  in since 3.9.3 (Tools › Due Crew › Plans, You › Plans, Find a
  setting). Every change is an op (`ops.py`, pure), waiting under the
  plan till Review and send when anyone follows it (`draft.py`, kept per
  profile in `plan_drafts.json`); `view.py` works out the Plan tab. AI
  hooks: `prompts.py` (the prompts for your own AI), `ai.py` (jobs whose
  requests carry names and counts, answers checked into ops), `mcp.py`
  (Your AI app: a local MCP server, off by default, 127.0.0.1 and a
  bearer token, that puts changes under a plan and never sends). Labs
  (this computer's `"labs": true`, no window sets it) keeps only Claude's
  stand-in (`claude.py`, sends nothing), the calendar window session by
  session, and What Claude would get. Routes the builder uses already;
  nothing new on the server. Its tests: `tests/test_planner.py`,
  `tests/test_plan_ops.py`.
- `poc/course_mac/` — Course on a Mac, a separate add-on proof of concept
  (Sam's; not part of Due Crew and never talks to its server): a
  block's calendar read, each lecture's cards found by Apple's on-device model
  (a Swift helper built on the Mac, or the `fm` command) or plain rules, ticked
  and opened; Copy as plan text is its one bridge to the builder. Its own
  tests, `poc/tests/`, and `poc/README.md`; CI doesn't run them.
- `tests/` — `python3 tests/test_due_crew.py` (client behavior against
  `fakes.FakeWorker`, a Python restatement of the Worker; standard library
  only). `worker/test/` is the Worker itself in real workerd with D1
  (`cd worker && npx vitest run`); `consent.test.ts` there is the consent
  model, restating every check of the old rules test. See
  `tests/README.md`. `docs/manual-anki-checklist.md` is the click-test.
- `tools/click_test.py` — the robot click-test: real Anki 25.02.7 offscreen on the fake server, every board control pressed, its windows, a plan sent, a deck studied, a minute at rest; red on a press no handler takes, anything raised, a slow first card or CPU at rest (CI's `click test (real Anki)`, part of the gate; `tests/README.md`).
- `.github/workflows/tests.yml` runs on every push: pyflakes, the suite,
  the offscreen dialog build, and the Worker (typecheck + vitest). Green on
  all of them is the release gate. pyflakes is the only thing that reads most of the glue,
  which the suite never imports. A `v*` tag also deploys the Worker, after
  every job is green.

## How the data moves (the invariants)

Every feature's full notes, with the why, are in `docs/history.md`, by
version. Read a feature's entry there before changing it (search for its
module, its `duecrew:` command or its mock's name). These hold everything up:

- A refresh is one request (`GET /board`: me, my crew, cheers, knocks; on
  the day's first, `decks=1`, shared decks, plans, squads and the bingo
  card), and a sync is one (`POST /sync`: profile, my week, decks, heatmap,
  squad rows, plan progress, plan squad days; 3.9.9: `errs`, what went wrong
  here by code, a finished day's counts once with the first sync after it,
  only after `/board` has said `errs: true`). The server writes only what
  changed. `test_request_budget` pins this: a change there is a change in
  what the add-on costs, and must be deliberate. A new feature rides one
  of the two, or is one request on a click.
- My week is the one shape for day stats (last eight days, away spell,
  exam, paused, `liveUntil`, flags, room, recap). The client rebuilds it
  from `session.week_raw` with the current Privacy switches at every sync,
  so turning a switch off takes that number off every day.
- Consent: friendship is two edges (`friends(owner, friend)`); only mutual
  friends read my week, decks, heatmap, accent and song of the moment; a cheer lands only if its
  recipient added the sender; a knock needs a squad in common or my code.
  Someone connected to me gets a name and an emoji, nothing more; a
  stranger's uid gets the same 404 as no account.
  `worker/test/consent.test.ts` is the model.
- A squad row is an UPDATE, never an insert; the join (with its code) is
  the only way in, and since 3.9.5 its checks are the insert's own
  conditions, one statement; 20 squads a person (`squads.SQUADS_MAX`).
- Card text never leaves the computer: flags, asks, knows, plan picks,
  plan tags and plan squad questions carry a note guid and card number, and
  each reader's Anki reads its own copy. The one exception is Pip Party
  (3.9.5, Sam's yes): Rounds' black card, hands and plays, and Links'
  board when a scope's topics run short (both with answers from the cards
  around the scope, `gamenight_flow.near`), pass through a table to phones
  in the room, never kept; Trivia's words stay on the TV (phones get shapes).
- Settings that belong to a person (`account.ACCOUNT_KEYS`) live on the
  server; an install pulls before it uploads (`account.ensure()`). Since
  3.8.1 a save names the rev it started from; one made over an older rev
  comes back with the doc as it is, and the two merge (`account.merge3`:
  each side's own changes, lists item by item, both: the save being made
  now). Theme, sort, tab, hidden tabs and the room chip's side stay per
  computer.
- Plans (`docs/plans.md` is how they work now: the doc, a follow,
  plans.json, the morning, the limits): the plan says what and by when; my follow (shift, skips, moves,
  pause, catch-up, and since 3.8.0 `own`, my own pace) says when for me
  (`plan_flow.mine` → `plans.my_doc`), and never changes the plan. The
  morning opens what's due once per Anki day, after the AnkiWeb sync, in
  one undo step; at my own pace it opens only what an author adds to dates
  I opened (and, "next", the next once I've seen most of the last). 3.9.10,
  catching up: three sets behind (or one a week old) and a plan on its
  dates waits in line (plans.json's `line`): a morning opens no new date,
  the card lists each day owed with Study and Ignore, and the plan's dates
  never move (`plans.line_view`, `plan_flow.line_sync`/`line_study`/`line_off`). Today's set (3.9.6) is a
  plan's choice here: in its deck (A, the default) or also each open
  set a filtered deck of its own (B: new and learning due now, never a
  review), built in the open's undo step. A plan never suspends on
  its own (Hold back is the one suspend, and only when asked; 3.9.9:
  Magic search's Schedule ahead, asked the same way, holds a later day's
  open new cards back and moves its due reviews, `magic_flow.Ops.spread`), a date that
  opened never closes again, and a leech never opens. Plan state is per
  profile (`user_files/<profile>/plans.json`), never the shared config:
  deck ids belong to one collection. `plans.py` is pure, `plan_flow.py`
  the glue.
- Mine alone, never sent: Insights, my progress on each bingo square,
  checkpoint scores, `wrap.json` (3.8.2: and the closet's tallies in it;
  3.9.1: the fridge, the doodles I was sent and where I pinned them),
  `closet_days.json` (3.9.1: the closet's older days, kept so the revlog
  isn't read whole at every launch) and the scrapbook (3.9.10:
  `scrapbook.json`, by account, kept through sign-out).
  3.9.11: my hooks (`hooks.json`: my own line on a card I keep missing, by note guid; one I
  share is my tip on that card on the server, read by mutual friends stuck on it, never the card's text).
  3.9.2: Reviews ahead, its track record and the pause it asks for, and
  the leeches view (plans.json: `new_off`, `ahead_trust`, `ahead_line_x`,
  `leech_out`); my exam's scope rides my settings (`exam_last`, `exam_since`).
  3.9.5: How you study; Pip Party's kept picks (`game_night.json`).
  3.9.9: `errs.json` (beside `wrap.json`) is the exception: what went wrong
  in this install by code (`errs.py`: `save:`, `py:`, `cmd:`, `req:`; never a
  message, card text, a name or an id), sent to Sam as counts behind
  Privacy's "Send Sam what went wrong" (`send_errs`, an account key, on by
  `errs.SEND_DEFAULT`), kept on the server only added up by day, version and
  code, no uid (`field_errs`, 30 days). A caught exception is printed with
  `oops()` (errs.py), never `traceback.print_exc()`: it prints as before and counts.
  Pip's closet is mine (an account key only I read); what my Pip has on
  rides with my accent to mutual friends, as names. A plan's squad (its team on the server) shares only
  that I showed up, my questions and answers, and bingo stamps; never my
  numbers by name, never weak spots. While I'm in it, my per-date progress
  joins the counts its authors see (Progress, never named, per date only
  from three in its squad, an author on the team among them, and from two
  besides whoever reads them; since 3.9.5 the server holds to that,
  `plans.COUNTS_MIN`/`IN_SQUAD`/`BESIDES_MIN`, and counts only who may
  still see the plan, `plans.COUNTED`).
- Days are the person's Anki day (their rollover), on both sides (`ankiDay`
  in the Worker).
- Background jobs capture `app.generation` (bumped at profile open/close,
  sign-in/out) and drop their commit when it changed.

## Twins: change one, change both

Logic that runs in two places, restated by hand. Change both sides in the
same commit, each with its test:

- `board.build_rows` and the board ↔ `Board` in `site/public/app.js` (rows,
  chip order, notes, show-up view, Decks, Squads, bingo mini card)
- `board.row_sev` ↔ `who` in app.js's `Board` (a crew row's Pip in the
  emoji's place, its accent and look; mine from `/board`'s `me.look`, 3.8.2);
  `board.squad_pip` ↔ `squadPip` (Squads' Pips: a crewmate's in colour,
  anyone else plain, 3.8.21).
  The drawing isn't restated: `sev.site_kit()` is written into
  `site/public/sev.js` by `tools/gen_sev_js.py` (run it when Pip or the
  closet changes); its `clean`/`shown` restate `closet.clean`/`shown`. The
  suite checks the kit is current and runs the JS in node against both
- `schedule.py` ↔ `Sched` in app.js (a date's window, quota, behind)
- `bingo.evaluate` ↔ `evaluate` in `worker/src/bingo.ts`
- `due.parse` ↔ `board.DUE_JS` (the add box's preview)
- `due.line_keys` ↔ `dueLineKeys` in app.js; `due.every_on` ↔ `dueEveryOn`
  (a plan's weekly lines, 3.8.0)
- `board.face` ↔ `face` in `site/public/builder.js`
- `team.bingo_line` ↔ `bingoLine` in builder.js (`PlanSquad`)
- `plans.tag_part`/`tag_root` ↔ `tagPart`/`tagRoot` in `worker/src/plans.ts`
  ↔ `Tags.part`/`Tags.root` in builder.js (a plan tag's name in Anki, 3.8.0)
- `plans.topic_items`' cut row ↔ `cutName` in builder.js ("Cephalosporins ·
  SLG 12", 3.8.1); a cut's `q` ↔ `cutQ` in builder.js ↔ `reroot` in plans.ts
- `board._plan_squad_html` ↔ `PlanSquad.view` in builder.js (a plan's squad)
- `plans.reinforces` ↔ `afterEv` in builder.js (a date after its event is
  reinforcement, "after Heme quiz", 3.8.1)
- `plans.topic_remarks` ↔ `remarkOn` in builder.js (a topic shows its tag's
  note or the nearest parent's); `plans._date_line` (the export) ↔ a date's
  line in builder.js `toText`; the picked row's "X · N picked" ↔ `picksText`
- `room_model.phase` ↔ the room widget's JS (3.8.1: a fifteen's question too; `test_fifteen_js_phase_matches_v381`)
- `sharecard.py` ↔ `site/public/cards.js` (the picture cards' layouts and words, 3.8.0)
- `due_crew/motion.js` = `site/public/motion.js`, byte for byte (the board's motion, 3.8.0; the suite checks)
- `shapes.clean_doodle` ↔ `doodle` in `worker/src/validate.ts` ↔ the fake's
  `_doodle` (a doodle cheer's strokes or sign, 3.9.1; a pen's colour is a
  place in `shapes.DOODLE_INKS`: add only at the end, and raise
  `DOODLE_PEN_MAX` in all three)
- `ahead.GENERIC`'s cards ↔ `Reviews.CURVE` in builder.js (a typical card's
  next six weeks, 3.9.2; the suite checks)
- `planner/build.py` ↔ builder.js (3.9.3): Todo, Every, Remarks, Picks,
  Suggest, Work, Reviews, `Tags.ankiSearch`, `Tags.word`/`name`/`natural`,
  searchName (checked in node); pieces, fill, layOut and its putWords,
  autoName (with renameAll, `edits.name_dates` on every save), What to
  cover's toggle and inView, heavyNote (checked by hand-worked plans);
  `planner/edits.py` ↔ the builder's edits
  (a date's sources, cuts, splits, events, review days, retag and dropSay);
  `planner/text.py` ↔ toText, fromText and the Text tab's use, takeOff
  (its date line is `plans._date_line`); `text.pick_note` ↔ `pickNote`
  (Read it's "To pick in Anki:" line)
- `planner/prompts.py` ↔ `Prompts` in builder.js (round five: Plan the
  dates and Tag by objective, the prompts for your own AI; checked in node)
- `due_crew/planner/page/*` = `site/public/planpage/*`, byte for byte (the
  plan window's page, the same on duecrew.com, 3.9.6; `tools/gen_plan_page.py`
  writes the copies, the suite checks); `planner/webface.py` and its views
  (`webmodel`, `webtabs`, `webnew`) ↔ `site/public/planface.js` (the same
  view and commands from builder.js's state; `tests/planface_test.js`);
  `planner/ics.py` ↔ `Ics` in planface.js (Add to my calendar, the suite
  checks byte for byte); `plans.my_doc` ↔ `myDoc` in planface.js (a
  follower's own days)
- `planner/build.CEILINGS`/`ceiling_counts` ↔ `Ceilings.MAX`/`counts` in
  builder.js ↔ the Worker's ceilings in `plans.ts` (a plan's limits and how
  they're counted, 3.9.9; the suite checks all three); `remote.LIMIT_WORDS`/
  `NEAR_WORDS` ↔ `Ceilings.WORDS`/`NEAR` (a refused save's words, Review and send's
  lines past 90%)
- `gamenight.NEEDS` → `NEEDS` in `site/public/table.js`, and `planner/build.CEILINGS`/`SAVES_A_DAY`
  → `MAX`/`SAVES_A_DAY` in builder.js: written, not restated (3.9.12, `tools/gen_twins.py`; run it
  after changing the Python, the suite checks it changes nothing). A new shared constant goes there
- the Worker ↔ `tests/fakes.FakeWorker` (the suite's server)

## Where things live

| Feature | Add-on | Worker, site |
|---|---|---|
| The board, your people: Crew (Today · Week · Decks picker) and Squads | `board/` (`crew.py`, `squads.py`, `draw.py`), `__init__.py`, `backend/api.py`, `stats/` | `board.ts`, `social.ts`; `Board` in app.js |
| The You bubble over it (3.8.0): Today, Upcoming, Later, Plans, Insights | `board.you_html`, `__init__._you`, `due_flow.py` | the rail on /home |
| Cheers, status, profile card (3.9.0: a landing cheer is a show over the whole Decks screen, a different one each time: `shows.py` the bag, `show.js` the twelve, started by `board.flurry_js`; 3.9.1: a drawing or a sign from the Cheer window's Draw · Sign, held up by the sender's Pip as it lands, its note under it as a caption with who it's from, then pinned around the Decks screen as Polaroids (the fridge: drag one anywhere and it keeps its place beside the board as the window changes, × takes it down into the scrapbook (3.9.10), with an Undo in its place for a few seconds; it's the signed-in account's, emptied at sign-out); a cheer is a "🎉 Cheer" pill after a crewmate's name, the 🎉 column is gone) | `social.py` (`_cheer_menu`, `send_from_window`), `wrap.py`, `shows.py`, `show.js`, `board.cheer_overlay_js` (the Cheer window, on the Decks screen in the board's look since 3.9.1; "other" opens the computer's own emoji picker, `native_emoji.py`, or on Linux the drawer, `emoji_drawer.py`), `board.doodle_html`/`doodle_landing`, `fridge.py` and `board.fridge_html`/`fridge_js` | `social.ts`, `validate.doodle` (migration 0029) |
| Settings (one: the board's, 3.8.0; 3.9.9: four tabs by what a setting is about, You (me, my dates, my people) · Board (the Decks screen, look, crew rows, Pip, soundtrack) · Study (Today, Magic search, reviewing, the Fifteen, keys) · Privacy; a new row goes on the tab its subject names) | `settings_model.py`, `account.py`, `board.settings_html` (`_settings_you`/`_settings_board`/`_settings_study`/`_settings_privacy`) | `GET/PUT /settings` |
| The board's questions (3.9.1): a sheet over the Decks screen in the Cheer window's look (confirm, one line, one of a few), Qt off the board; the top and bottom bars dim with any window over the board | `sheets.py`, `board.sheet_js`, `board.VEIL_WATCH_JS`, `app.veil` | never sent |
| Squads, knocks, bingo | `squads.py`, `bingo.py`, `bingo_flow.py` | `squads.ts`, `bingo.ts`, `adminsquads.ts` |
| Who knows this, asks, tips (3.9.0: the day's first sync asks about the cards due today too, so a first miss shows it; with Pip on, the knower's Pip peeks in from the corner, and a tip's tipper's; a tip's, an ask's or a plan note's words fold till Show, so a one-by-one card isn't given away) | `cards.py`, `together.py` | `cards.ts` |
| Hooks (3.9.11): my own line on a card I keep missing, folded till Show when I'm stuck on it ("You left a hook"), offered beside Edit on a second miss and once when a card has stuck ("What made it click?"); shared (a tick on each, on by default) it's my tip on the card: a mutual friend stuck on it reads it ("Dre left a hook", This helped, Hide this hook), and This helped reaches me once (a tooltip, a scrapbook line); who knows it keeps its bubble on a card I've no hook on; the reviewer's More menu | `hooks.py` (the rules, the views, `hooks.json`: mine, what waits to be sent, what I hid), `ui/hook_dialog.py`, `cards._with_hook`/`hook_edit`/`flush_hooks`/`hook_thanks`/`hide_hook`, `together.reviewer_menu` | `PUT /hooks` (`cards.ts putHook`, the tips table), `thanksFor` on `/board` (`thanks`, `tip_helped.told`, migration 0032) |
| Study rooms (room sounds were here, 3.9.1 to 3.9.7; gone in 3.9.8, Sam's call) | `rooms.py`, `room_model.py` (the chip; its scripts `room_widget.js`, `bar_balance.js`, 3.9.8) | rides my week |
| The Fifteen (3.8.1): ▶ Fifteen? in the top bar, the nudge, the question at its end, Take five / Another now / Stop | `room_model.make_fifteen`/`fifteen_next`, `rooms.start_fifteen`/`fifteen_answer` | studying now only (never a room on my week) |
| Pip (3.8.1, Block; called Sev until 3.8.2, and still `sev` in code: sev.py, the `sev*` keys, `.sv`, sev.js's `Sev`): by the logo for a moment, in a fifteen's chip, question and break, the nudge, the session's line; hopping across the week picture card; a study room's seats, each crewmate's in their accent; waving in Welcome back and on the signed-out card; hopping on a crewmate's big-streak banner (not on crew rows: Sam's no); never in the plan windows (round five, Sam's pick); Pip Party's TV corner, phones and lobby seats (3.9.5, `sev.GAME_PLACES`, the site kit's `stage`), and You › Pip Party's tab, at its places, still till pointed at. Each place has its mix of moves (`sev.MOVES`), never the same twice in a row. 3.9.1: its loops play about twelve seconds and rest (`--sv-on`), pointing plays them on; 3.9.8: a pointer resting 12 s, or Anki not in front, isn't pointing (`sev.REST_JS`, `.dc-rest`, `--sv-hover`): no loop is forever on its own; the break's breathing goes on; the fridge's are still till pointed at | `sev.py` (one drawing; the widgets get its markup, the week card and Welcome back `sev.still`; `pick`/`nth` the variety), `rooms.board_sev`/`pick`/`milestone_sevs`/`signed_out_sev`, `sharecard.hops`, `room_model.seats`/`vary_seed`, `ui.sev_label` | never sent; cards.js keeps a copy of `sev.still` (the suite checks it) |
| Pip's closet (3.8.2): 61 things earned by showing up, coming back, together, plans, card care, seasons, secrets; one per place, a costume over the look; in place of the board (Yours by place, To earn by how); each crew row's, profile card's and (3.8.21) squadmate's Pip in the emoji's place (3.8.22: a plan card's squad line too, by `who` on `/board`'s `teams`; the review chip, a squadmate's card, Settings › You, bingo stamps; the site's account page and home feed, `pipFor`; the Friends dialog is names alone) | `closet.py` (pure: things, wear/clean/shown, facts from days and hours; 3.8.22: `halloween`/`spooky`), `closet_art.py` (the drawings), `closet_flow.py` (facts, tallies in wrap.json, a year of them for Wrapped, earned, worn, `halloween_view`), `board.closet_html`/`closet_line`/`row_sev`/`card_sev`/`squad_pip`/`halloween_html` | account keys `sev_look`, `sev_closet`; a mutual friend's look on /board (`lookOf` in `board.ts`) |
| Plans (follow, morning, week, load; You › Plans: the plan's card, the whole plan as a path above the week and Behind… (Slide, Fit it in, Skip what's left; round six, `plan_board.py`), seven small days, a day's click opening its assignments under them, round five pick A; two or more plans one at a time, their names a switch, pick 3 (`plan_pick`); a date's details on its name in Today and Upcoming; 3.9.9: the plan's exam, an event with `kind: "exam"`, asked once on a follower's card, account keys `exam_from`, `exam_asked`; Everything this week under the card when two plans share the next seven days: reviews and each plan's new cards a day at my pace, a heavy day's one move, `plans.load_week`, `plan_flow.load_view`/`load_move`, `plancards._load_html`) | `plans.py` (`path`, `behind_sheet`, `exam_way`, `exam_offer`), `plan_flow.exam_answer`, `schedule.py`, `plan_flow.py`, `plan_board.py`, `board._plan_card_html`/`_plan_switch`/`_week_html`/`_day_unit`/`_date_more`/`_plan_path`/`_plan_behind` | `plans.ts`; `builder.js`, app.js |
| Your plans (3.9.3: the builder in Anki; round five: Plan · Insights · Settings for authors and followers, changes waiting to be sent), New plan, the AI hooks and Your AI app (QBank QIDs: Magic search's since 3.9.7) | `planner/` (the HTML window: `web.py`, `webface.py`, `webmodel.py`, `webtabs.py`, `webnew.py`, `webpage.py`, `page/`, on `core.py`; Qt windows it opens: `text_tab.py`, `date_dialogs.py`, `picker.py`; pure: `ops.py`, `draft.py`, `view.py`, `insights.py`, `prompts.py`, `ai.py`, `build.py`, `edits.py`, `text.py`; `mcp.py`, `mcp_host.py`, `mcp_dialog.py`; `flow.py`) | routes the builder uses; `builder.js` the twin |
| The plan joys (3.9.6: a set done's pop and Pip's hop on the path, milestones, Caught up, Day one, the finish line's show over the Decks screen and its share card; Finisher's ribbon, Folded map, Kite in the closet; one moment at a time, each once, plans.json's `joy`) | `plans.py` (the moments' facts), `plan_flow.py`, `board/plancards.py` (the card's lines), `motion.js`, `show.js`/`shows.py` (the finish), `sharecard.py` (the plan card), `closet.py`/`closet_art.py`/`closet_flow.py`; `tests/test_plan_joy.py` | never sent; `site/public/cards.js`'s K4 the share card's twin |
| A plan's squad (3.8.0, on the Squads tab; its team on the server) | `team.py`, `team_flow.py` | `team.ts`; `PlanSquad` in builder.js |
| Insights (the deck's, a plan only sharpens it; You › Insights; the topic map, tiles open into parts, or by the week I started them (3.9.2); its card and text, shared by hand; my exam's scope, since my last exam (3.9.2); 3.9.5: `team_flow.study_deck` for every Study's deck; a Study only with a date ahead, `team_flow.dated`) | `team.py`, `team_flow.py`, `mapcard.py`, `ui/map_card_dialog.py` | never sent |
| How you study (3.9.5: a line atop Insights, the view in its place: matured a week, Slow but right (See them; with an exam set, its cards join the exam box's Study), long sittings; the Fifteen at 35 in the top bar; a finding only once it clears its bar) | `habits.py` (pure), `habits_flow.py`, `board` (its view), `rooms.take_five` | never sent |
| Reviews ahead (3.9.2: six weeks of a deck counted from my log; its ways and Stop new cards, Anki's today-only limit each morning; the track record; the board's line when reviews climb) | `ahead.py` (pure), `ahead_flow.py`, `board._ins_ahead`/`ahead_line` | never sent; the builder's `Reviews` (a typical curve) |
| Leeches (3.9.2: in Insights' place; one button a card, Bring back, Learn it fresh, Leave it out) | `leech_flow.py`, `board._ins_leeches` | never sent (tips ride the stuck list) |
| Due (the bubble's Today, Upcoming, Later; 3.9.3: no Study today button, Ctrl+Shift+S walks the day; Magic search in the box's head, every tab and folded (QBank QIDs' place till 3.9.7); 3.9.5: today's misses by part under a done Reviews row (each part Browse); an exam date comes off the day after; a plan topic's Study (its new and due cards, a deck of its own) and Browse beside its name; Sam's FSRS rule: a deck only for a date ahead, cards not started, a miss outside Anki; Super decks, Next up and a deck-ran-out line built and taken out before shipping) | `due.py`, `due_flow.py` (`_misses`, `exam_gone`), `board._due_html`/`_topic_go`, `plan_flow.study_topic`/`_free`/`untils` | settings doc |
| Invites, codes | `__init__.py`, `ui/friends_dialog.py`, `ui/welcome_dialog.py` | `invites.ts`, `social.ts` |
| Sign-in, sessions, quiet accounts | `ui/auth_dialog.py`, `backend/api.py` | `auth.ts`, `quiet.ts`, `mydata.ts` |
| Shares: text, and picture cards (made in Anki since 3.8.0) | `share.py`, `shares.py`, `sharecard.py`, `ui/share_card_dialog.py` | `site/public/cards.js` |
| Admin, notices, feedback, reports (kept for the Inbox, 3.8.1) | | `admin.ts`, `people.ts`, `notices.ts`, `feedback.ts`, `reports.ts` |
| The scrapbook (3.9.10; took Wrapped's place, 3.9.0): in the board's place (`_state["wrapped_open"]`), the year's page (numbers, Share my year) then months of keepsakes: a polaroid off the fridge (×, pushed out, sign-out), a good-luck line once shown, a tip that helped, a cheer with words, what I did (plan finished, bingo line, what Pip earned); Pin up, Delete, Empty; the foot's Scrapbook, Tools › Scrapbook…, the board's line 1 Dec to 15 Jan | `scrapbook.py` (pure), `scrap_flow.py` (`scrapbook.json` by account, the hooks, the view), `board/scrapbook.py`, `_scrap_cmd`; `wrapped.facts`, `wrapped_flow.year_rows`/`banner` (the year's numbers, the line) | never sent; the account's `wrapped_seen`; cards.js draws the year card's Pip the same |
| The board's foot (3.9.10): Friends, Scrapbook, Share my stats; Share a deck… on Crew › Decks; Open a room under the top bar's ▶ Fifteen? ▾ | `draw.py`, `crew._decks_body`, `rooms.start_menu` | app.js's foot |
| The studying dot by itself (3.9.10): a sync within an hour of my last review sets `liveUntil`; Privacy › While you study; told once on the board | `together.auto_live`/`live_on`/`live_told`, `queries.last_review_ms` | rides my week; account keys `show_studying`, `live_told`; bingo `lv` (migration 0031) |
| Study soundtrack and the dance floor (3.9.6; song of the moment in code): one song from Apple's public catalog, shown to my mutual friends; the Decks screen's bottom-right corner, my Pip DJing and my crew's Pips dancing with their songs' bubbles (Gentle by default, one bubble at a time, folds to a chip, starts folded where it would cover the board); the first dancer beside the booth, the rest toward the middle, no lights, each Pip blinking on its own clock; a song's card with its cover, "Song and cover courtesy of Apple Music" and Apple's badge at its foot (the search's: "Song search courtesy…"), no preview (Apple's terms stream them only); Listen in my music app (picked on the card the first time) | `songs.py` (pure), `song_flow.py` (search, Use this, Listen, the floor's view), `board.dance_html`/`DANCE_JS`/`_settings_songs`, `social._open_profile`; `tests/test_songs.py`, `tests/test_dance_floor.py` | account key `song`; `songOf` in `board.ts` (me and mutual friends, beside the look) |
| Magic search (3.9.7): one box that reads the deck's own tags (topics, a row each with its tree, every tag to its end under its resource, and its Also; round 3, Sam's; its resources and short names, chapters by number; and/or another topic, both/AND/with the cards in both), filters (a row always under the box), words in quotes (the cards' own text, alone or narrowing a topic, 3.9.10), how many, but not, QBank QIDs (pasted any way a bank copies them, Their topics; QBank QIDs' own window went in round 2) and ids, what's coming up (a quiz, an exam, away, push or pause my plan) and plan lines; what it found (due, new, not due, its time at my pace); four tiles, Study now, Schedule ahead (My plan, or a plan I write's Review and send), Make a new filtered deck, Unsuspend, the one that fits filled; Add to a filtered deck and Study all under them; a field under Anki's deck list, over its "Studied…" line (3.9.9, `board.magic_field`: a glint round its edge about twelve seconds, then at rest; one example in it, the next each time the page is drawn; the start of `content.stats`, since `content.tree` is inside Anki's table; Enter opens the window on what's typed; in the You box's head till then), Ctrl+F, Browse's put on a day…, Tools; its how-to on the Decks screen once a person, ? in the window; the window as tall as what's in it; 3.9.11: the answer in the box as it's typed (its count rolling up as it lands), did you mean (`magic.mean`), nothing found says what's waiting today (`Search.none_view`), a picked day wears its share | `magic.py` (pure: the rules, `HOWTO`, `examples`, `tag_row`/`tag_list`), `magic_flow.py` (the window's logic, `Search`, Anki's steps, `Ops`, and the Decks screen's how-to, `board_howto`), `magic_html.py` and `magicpage/` (its page), `ui/magic_window.py` (its size), `board.magic_link`/`magic_howto_js`; `planner/qids.py` (QIDs' find); `tests/test_magic.py` | never sent but My plan's dates (the plan routes); account keys `magic_search`, `magic_seen` |
| What gets used (3.9.9): `use:<part>` once a day on the error counts' path, told once (`use_told`), one Privacy switch that names nobody | `errs.used`/`USE`/`use_of`, `errs_flow.tell_once`, `_on_js` | rides `POST /sync`'s `errs`; admin's Used in `fieldPanel` (app.js) |
| The calm board (3.9.9): a new account's board is Crew and Today; a part appears when it has something to show (a line: Open, ×), Show all, Settings › Board › Calm board | `calm.py` (pure), `board.hidden_tabs`, `_calm_check`/`_calm_cmd`, `draw._calm_line` | never sent (this computer's `calm`, `calm_open`, `calm_news`) |
| The speed budget (3.9.9): each wait against its budget on a big collection, in CI's click job | `tools/speed_budget.py`, `tools/speed/make_big.py` | |
| Why isn't this card showing? (Browse right-click, 3.8.0) | `why.py`, `why_flow.py`, `ui/why_dialog.py` | never sent |
| Browse's Due says when a plan opens a suspended card (3.9.5, Sam's pick: "Thu 5 Nov · Heme 2"; not at my own pace, not a leech) | `plans.opens_ahead`/`opens_words`, `plan_flow.opens_map`/`browser_row` (on `browser_did_fetch_row`; never raises) | never sent |
| Two buttons (3.9.1): Again and Good alone, 2, 3 and 4 count as Good; Settings › Study › Reviewing, and Try two buttons on Insights' Hard habit line | `two_buttons.py` (on `reviewer_will_init_answer_buttons` and `reviewer_will_answer_card`), `board._settings_board`, `team_flow.try_two` | account key `two_buttons` |
| Plan tags: DueCrew::<plan>::SLG_12 on followers' notes (Browse right-click, the builder, Tag by objective; 3.8.0) | `plans.sync_tags`, `plan_flow.apply_tags`, `ui/tag_dialog.py` | `plans.ts` tagNotes; This plan's tags in builder.js |
| Cuts (a video kept to an SLG) and a tag's single cards; taking a tag off (3.8.1) | `plans.match`/`plan_tag_cards`/`topic_items`, `plan_flow._unit_cids` | `planDoc`/`putIds` in `plans.ts`; `setCut`/`syncCuts` and the Text preview in builder.js |
| Your own pace (Up next, Open, Put back); Browse › open its cards / open these (3.8.0) | `plans.up_next`, `plan_flow.open_next`, `plan_flow.open_cards_now`, `ui/open_dialog.py` | follow `own` (`plans.ts`); `paceBox` in builder.js |
| Co-authors who said yes, handing a plan over (3.8.1) | `board._invite_lines`, `plan_flow.answer_invite` | `plans.ts` addEditor/answerInvite/offerPlan; `coauthorsBox` in builder.js, Home's invites |
| Notes for followers on a tag or a card (`remarks`, 3.8.1) | `plans.topic_remarks`, `cards.remark_view`, `ui/remark_dialog.py` | `plans.ts` remarks; `Remarks`, `remarkOn` in builder.js |
| A follower's day (3.8.1): Welcome back, what Hold back keeps, Study a date or a quiz | `plan_flow.welcome_back`/`show_held`/`study_date`/`study_quiz`, `plans.quiz`, `ui/away_dialog.py`, `ui/held_dialog.py` | never sent (Push my dates back is the follow's shift) |
| The builder's day's work and suggestions (3.8.1) | | `Work`, `Suggest` in builder.js |
| Previews of a plan or invite link | | `site/src/og.ts` |
| Pip Party (3.9.5; called Game night until its last round, still gamenight in code; its You tab says Party since 3.9.10): party games on your own cards, on the menu Trivia (a subject picked on the TV for the block, `gamenight.rounds`/`area_of`; after each reveal the card's sentence and its Extra, the TV's alone), Imposter (its end: what tells the two apart, as their cards say it) and Links as two teams (`gamenight.GAMES` = table.js's ORDER; Rounds, Draw it and Somewhere between are off it since Sam's first nights, their code kept), each saying its kind in our own words (no other game named: trademarks), the TV a window of Anki's, phones at duecrew.com/t/CODE; started from You › Pip Party alone (round three, Sam: no Party from Today or anywhere else; Tools › Due Crew › Pip Party… opens the tab; its tab says Beta, `board.BETA_TABS`): the three games up top (each its picture, tonight's count, First up), What you know by Systems (Insights' own map), Tags or Decks (tap picks, › opens, Find, question numbers folded), Of their cards, the picks at the foot (tap leaves out, × drops), Keep this pick, Host; nothing picked, the tiles on the map are the night; then the TV's code and Copy link; the tab's state is this computer's `party` config, worked out only on screen and kept a while (`gamenight_flow.tab_view`); each pick's share of what Host reads, with the cards around them for answer choices (`near`); every question, word and pair marked with its pick or subject, the TV's lobby a vote on them (phones vote with names alone, the host's taps win, `Vote` in table.js); written cards in `gamenight.py` (Rounds' WRITTEN, a quarter of the black cards, never alone; Draw it's DRAWS; Somewhere between's SCALES); a card's topic by what its tags agree on (`topic_of`), no question from a thin answer or a giveaway, wrong answers scored by shared tags, the same blank and the answer's sort (`_Pool`; `test_game_night_questions_make_sense_v395`, tried on a big shared deck's export); each seat whispered its own part; the door (the host's crew straight in, anyone else waits till let in; crew only, open, lock, turn away); Pip and reactions; since its release (Beta) anyone signed in has the tab (hidden in Settings › Board as the other tabs are; Tools › Due Crew › Pip Party… shows it again) and opens a table (ten an hour, twenty a day), /table is anyone's and each game starts at its own min; `gamenight_flow.TESTERS` (a tuple), `ADMINS_ONLY` in table.ts, `TABLE_ADMINS_ONLY` in site/src/index.ts and `FEW = 1` in table.js make it a tester's again (`test_pip_party_for_everyone_v395`) | `gamenight.py` (pure: the pack, its picks for the vote, the written cards), `gamenight_flow.py` (the tab: picks, maps, find, counts, kept picks; near, the request, the TV), `board.party_html`/`party_map_html`, `ui/game_night_tv.py`; `test_game_night_from_your_cards_v395`, `test_pip_party_v395`, `test_pip_party_the_table_votes_v395` | `site/public/table.js` (engine, games), `table.css`, `table.html`, `sev.js`'s `stage`; `worker/src/table.ts` (a Durable Object a table, whispers, nothing kept); `test/table.test.ts`, `test_game_night_one_player_v395` |

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
secrets exist, so production is deployed by hand: `tools/deploy.sh` from a
clean `main` does the migrations, the API, then the site, then
`check_prod.sh` (`docs/go-live.md`, 2b).

## Rules of the road

- Simplicity is the product rule. Friendship framing, never competition —
  "crew", no "compete/rivals". Copy is terse, no AI-speak.
- Words (3.9.12; `test_copy_rules_v3912` checks them): buttons, headings and
  menu items are sentence case; nothing a person reads says rank, rival,
  compete or leaderboard. One name a thing, and the code's older name for it:
  a **hook** is `tip` in code, routes and tables (`tips`, `/tips/helped`);
  **Pip** is `sev`; **Pip Party** is `gamenight` (its tab says Party); the
  **scrapbook** took Wrapped's place (`wrapped*` is the year's numbers);
  **unsuspended**, never unlocked; a plan's **set** on the site is a date in
  the add-on's code.
- What a page is told to draw has a named shape in `views.py` (3.9.12; the
  review chip is the first), checked as it crosses to the page: a slip counts
  as `view:<name>` and is drawn anyway. A new surface's view gets its shape there.
- A file Due Crew keeps is written by `store.py` (3.9.12: whole to a .tmp,
  swapped in; `load`/`save` for one kept in memory), never by a module's own
  open-and-replace. The colours are `board.palette`: every add-on page reads
  it, and the site's shared tokens are checked against it.
- Requests, not reads, are the budget now: a refresh is one request and a
  sync is one. Don't add polling, per-friend requests, or unbounded
  queries. D1 writes cost more than reads: the server compares before it
  writes, and `last_used`/`last_seen` are written at most daily/hourly.
- Never store or return card text. No ranking anywhere new.
- Code, comments and test data name no third-party deck, question bank,
  video series or game (trademarks): "a big shared deck", "Big Step 1";
  Pip Party's games say what kind of game they are in our own words.
  Music apps are named only where Listen can't work without them (its
  chooser, their link hosts; Sam, 3.9.6), never a logo; Apple's covers only
  beside Apple's own badge and a "… courtesy of Apple Music" line; no previews
  (Apple's terms: streamed only, and Anki can't).
- Threading: collection access, config writes, and cache commits on the main
  thread only; all HTTP in background threads with timeouts.
- Anything meant as an update must never create (a row is not a join), and
  anything guarding a join must demand what only a join sends.
- When testing a permission, test it in the state users are actually in.
  The 2.3 removal test locked the squad first, which hid the bug above.
- Escape every server-sourced string before webviews, tooltips, or rich-text
  labels.
- The board lives in Anki's Decks screen, which sits in a `<center>` and
  styles every button (margin, shadow, rounded corners). A card of ours
  wears the deck list's shadow (`base.CARD_SHADOW`, 3.9.9). The board's older
  parts are centred by it on purpose; a new part sets `text-align: left`
  itself, and buttons start from the reset in `_css`. `tools/preview.py`
  renders inside the same `<center>` and button style: look at a new part
  there (light, dark, narrow) before calling it done. A control starts
  from its page's reset (`appearance: none`: macOS draws any other
  natively, Liquid Glass over ours; a focus ring on a button needs
  `!important` under Anki's `outline: none !important`);
  `tools/control_audit.js` checks every control against Anki's
  webview.css and a native stand-in (the plan window's and the site's
  pages as they are, `--site`; the board's preview a section at a time,
  `AUDIT_WITHIN`).
  A swap carries the board alone: its leading stylesheets go once a page
  into `#dc-css` (`board.split_css`, 3.9.8), again only when they change.
  `tools/motion_preview.py` plays each motion on the real board; a
  redraw's motion lives in `motion.js` (only what changed moves, nothing
  with Reduce motion, no row ever slides past another; what leaves is put
  back inert for a moment, and a full draw compares with the page's
  session memory). The logo may move, never change: transforms only.
  A move ends exactly where the page lands, so nothing jumps when it
  cleans up (heights by `tall`/`inner`, folds by `room`, never
  offsetHeight); `tools/motion_audit.js` measures each one's last frame
  against the settled page (3.9.0).
- A window over the board is a `dcPop` (`board.POP_JS`, 3.9.8: the shade,
  Esc, Tab kept inside, the key back, the bars' shade, the motion layer);
  its styles name it by its id through `pop.css`, so its look outlasts the
  id as it closes.
- A question the board asks goes through `sheets.py` (then-callbacks, only
  a yes reaches them), never a bare QMessageBox/QInputDialog/askUser; the
  Qt ones in `ui` are its fallback off the board. A Qt window wears the
  board's look (`ui.styled`, via `attach_alive`): Fusion under it
  (`ui.base_style`), every box, arrow and tick drawn by `ui.QSS`. It says
  what it is with `ui.heading` (its frame says Due Crew), a part's heading
  is `ui.role(label, "head")`, small print `ui.note`; no window sets its
  own font sizes or margins in a style sheet (a margin there sets a
  label's words in), and its labels' own style sheets take
  `ui.tone(...)`, never palette(...). `tools/dialogs.py` fails on a
  clipped button, a squeezed box, two controls on top of each other or a
  window shorter than its words: a new window or state gets a render there.
- Every `duecrew:` command a page emits needs a handler (a Decks-screen
  one is a line of `BOARD_CMDS` in `__init__.py`, 3.9.8, or a family's module;
  `test_every_board_command_has_a_handler`), and a new one gets a test
  that sends it through `_on_js` as the board does (3.5.0's Settings went
  out with its clicks reaching nothing). Anything a click adds has its way
  back on the same screen.
- A card's own script runs on the review screen, in the browser's preview
  and in Cards…, and a deck's description runs on Overview: from any page
  but the ones Due Crew draws on (Decks, the top bar, the reviewer's bottom
  bar: `_our_page`) only the widgets' keyed commands in
  `room_model.CARD_PAGE_CMDS` are taken
  (`room_model.trusted`); anything that acts for me elsewhere comes from
  the board, the bars or a dialog. The board's own commands carry
  `board.BOARD_KEY` (3.9.1: `_pycmd`, or `+ '|' + window.dcBK` in a script
  that builds one): Anki calls a message the Decks screen's before the page
  before has gone, and a Decks-screen message without the key gets the card
  page's rules. Draw on the board with `app.board_eval`, never into a page
  that isn't the Decks page.
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
