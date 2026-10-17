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
  `docs/cloudflare-setup.md` is the one-time setup (Sam's). The 2.x
  backend (Firebase) is gone since 3.8.0.
  `worker/` and `site/` are PolyForm Shield 1.0.0 (their LICENSE.md) since
  29 Sep 2026: readable and runnable, not for a competing service. The
  add-on, tests and tools stay MIT (root LICENSE).
- `site/` — duecrew.com: the landing page, and the app (`public/app.*`,
  plain JS, no framework: sign-in, plans, the builder). Its Worker
  (`site/src/index.ts`) sends `/api/*` to the API by service binding, so
  the site's session is a same-site HttpOnly cookie, and draws a plan
  link's preview (`site/src/og.ts`).
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
  squad rows, plan progress, plan squad days). The server writes only what
  changed. `test_request_budget` pins this: a change there is a change in
  what the add-on costs, and must be deliberate. A new feature rides one
  of the two, or is one request on a click.
- My week is the one shape for day stats (last eight days, away spell,
  exam, paused, `liveUntil`, flags, room, recap). The client rebuilds it
  from `session.week_raw` with the current Privacy switches at every sync,
  so turning a switch off takes that number off every day.
- Consent: friendship is two edges (`friends(owner, friend)`); only mutual
  friends read my week, decks, heatmap and accent; a cheer lands only if its
  recipient added the sender; a knock needs a squad in common or my code.
  Someone connected to me gets a name and an emoji, nothing more; a
  stranger's uid gets the same 404 as no account.
  `worker/test/consent.test.ts` is the model.
- A squad row is an UPDATE, never an insert; the join (with its code) is
  the only way in.
- Card text never leaves the computer: flags, asks, knows, plan picks,
  plan tags and plan squad questions carry a note guid and card number, and
  each reader's Anki reads its own copy.
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
  I opened (and, "next", the next once I've seen most of the last). A plan never suspends on
  its own (Hold back is the one suspend, and only when asked), a date that
  opened never closes again, and a leech never opens. Plan state is per
  profile (`user_files/<profile>/plans.json`), never the shared config:
  deck ids belong to one collection. `plans.py` is pure, `plan_flow.py`
  the glue.
- Mine alone, never sent: Insights, my progress on each bingo square,
  checkpoint scores, `wrap.json` (3.8.2: and the closet's tallies in it;
  3.9.1: the fridge, the doodles I was sent and where I pinned them) and Wrapped.
  Pip's closet is mine (an account key only I read); what my Pip has on
  rides with my accent to mutual friends, as names. A plan's squad (its team on the server) shares only
  that I showed up, my questions and answers, and bingo stamps; never my
  numbers by name, never weak spots. While I'm in it, my per-date progress
  joins the counts its authors see (Progress, never named, per date only
  from three people up).
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
  `_doodle` (a doodle cheer's strokes or sign, 3.9.1)
- the Worker ↔ `tests/fakes.FakeWorker` (the suite's server)

## Where things live

| Feature | Add-on | Worker, site |
|---|---|---|
| The board, your people: Crew (Today · Week · Decks picker) and Squads | `board.py`, `__init__.py`, `backend/api.py`, `stats/` | `board.ts`, `social.ts`; `Board` in app.js |
| The You bubble over it (3.8.0): Today, Upcoming, Later, Plans, Insights | `board.you_html`, `__init__._you`, `due_flow.py` | the rail on /home |
| Cheers, status, profile card (3.9.0: a landing cheer is a show over the whole Decks screen, a different one each time: `shows.py` the bag, `show.js` the twelve, started by `board.flurry_js`; 3.9.1: a drawing or a sign from the Cheer window's Draw · Sign, held up by the sender's Pip as it lands, its note under it as a caption with who it's from, then pinned around the Decks screen (the fridge: drag one anywhere, × takes it down); a cheer is a "🎉 Cheer" pill after a crewmate's name, the 🎉 column is gone) | `social.py` (`_cheer_menu`, `send_from_window`), `wrap.py`, `shows.py`, `show.js`, `board.cheer_overlay_js` (the Cheer window, on the Decks screen in the board's look since 3.9.1), `board.doodle_html`/`doodle_landing`, `fridge.py` and `board.fridge_html`/`fridge_js` | `social.ts`, `validate.doodle` (migration 0029) |
| Settings (one: the board's, 3.8.0) | `settings_model.py`, `account.py`, `board.settings_html` | `GET/PUT /settings` |
| Squads, knocks, bingo | `squads.py`, `bingo.py`, `bingo_flow.py` | `squads.ts`, `bingo.ts`, `adminsquads.ts` |
| Who knows this, asks, tips (3.9.0: the day's first sync asks about the cards due today too, so a first miss shows it; with Pip on, the knower's Pip peeks in from the corner, and a tip's tipper's; a tip's, an ask's or a plan note's words fold till Show, so a one-by-one card isn't given away) | `cards.py`, `together.py` | `cards.ts` |
| Study rooms | `rooms.py`, `room_model.py` | rides my week |
| The Fifteen (3.8.1): ▶ Fifteen? in the top bar, the nudge, the question at its end, Take five / Another now / Stop | `room_model.make_fifteen`/`fifteen_next`, `rooms.start_fifteen`/`fifteen_answer` | studying now only (never a room on my week) |
| Pip (3.8.1, Block; called Sev until 3.8.2, and still `sev` in code: sev.py, the `sev*` keys, `.sv`, sev.js's `Sev`): by the logo for a moment, in a fifteen's chip, question and break, the nudge, the session's line; hopping across the week picture card; a study room's seats, each crewmate's in their accent; waving in Welcome back and on the signed-out card; hopping on a crewmate's big-streak banner (not on crew rows: Sam's no). Each place has its mix of moves (`sev.MOVES`), never the same twice in a row | `sev.py` (one drawing; the widgets get its markup, the week card and Welcome back `sev.still`; `pick`/`nth` the variety), `rooms.board_sev`/`pick`/`milestone_sevs`/`signed_out_sev`, `sharecard.hops`, `room_model.seats`/`vary_seed`, `ui.sev_label` | never sent; cards.js keeps a copy of `sev.still` (the suite checks it) |
| Pip's closet (3.8.2): 61 things earned by showing up, coming back, together, plans, card care, seasons, secrets; one per place, a costume over the look; in place of the board (Yours by place, To earn by how); each crew row's, profile card's and (3.8.21) squadmate's Pip in the emoji's place (3.8.22: a plan card's squad line too, by `who` on `/board`'s `teams`; the review chip, a squadmate's card, Settings › You, bingo stamps; the site's account page and home feed, `pipFor`; the Friends dialog is names alone) | `closet.py` (pure: things, wear/clean/shown, facts from days and hours; 3.8.22: `halloween`/`spooky`), `closet_art.py` (the drawings), `closet_flow.py` (facts, tallies in wrap.json, a year of them for Wrapped, earned, worn, `halloween_view`), `board.closet_html`/`closet_line`/`row_sev`/`card_sev`/`squad_pip`/`halloween_html` | account keys `sev_look`, `sev_closet`; a mutual friend's look on /board (`lookOf` in `board.ts`) |
| Plans (follow, morning, week, load; You › Plans) | `plans.py`, `schedule.py`, `plan_flow.py` | `plans.ts`, `library.ts`; `builder.js`, app.js |
| A plan's squad (3.8.0, on the Squads tab; its team on the server) | `team.py`, `team_flow.py` | `team.ts`; `PlanSquad` in builder.js |
| Insights (the deck's, a plan only sharpens it; You › Insights; the topic map, tiles open into parts; its card and text, shared by hand) | `team.py`, `team_flow.py`, `mapcard.py`, `ui/map_card_dialog.py` | never sent |
| Due (the bubble's Today, Upcoming, Later; Study today, 3.8.0) | `due.py`, `due_flow.py`, `board._due_html` | settings doc |
| Invites, codes | `__init__.py`, `ui/friends_dialog.py`, `ui/welcome_dialog.py` | `invites.ts`, `social.ts` |
| Sign-in, sessions, quiet accounts | `ui/auth_dialog.py`, `backend/api.py` | `auth.ts`, `quiet.ts`, `mydata.ts` |
| Shares: text, and picture cards (made in Anki since 3.8.0) | `share.py`, `shares.py`, `sharecard.py`, `ui/share_card_dialog.py` | `site/public/cards.js` |
| Admin, notices, feedback, reports (kept for the Inbox, 3.8.1) | | `admin.ts`, `people.ts`, `notices.ts`, `feedback.ts`, `reports.ts` |
| Your Wrapped (3.9.0): the year's story in the board's place, the board's line 1 Dec to 15 Jan, Tools › Your year… | `wrapped.py` (pure: facts, slides, words, SAD), `wrapped_flow.py` (one query, counts, the card), `board.wrapped_html`/`wrapped_js`/`wrapped_line`, `sharecard.year`'s Pip | never sent; the account's `wrapped_seen`; cards.js draws the year card's Pip the same |
| Why isn't this card showing? (Browse right-click, 3.8.0) | `why.py`, `why_flow.py`, `ui/why_dialog.py` | never sent |
| Two buttons (3.9.1): Again and Good alone, 2, 3 and 4 count as Good; Settings › Board › Reviewing, and Try two buttons on Insights' Hard habit line | `two_buttons.py` (on `reviewer_will_init_answer_buttons` and `reviewer_will_answer_card`), `board._settings_board`, `team_flow.try_two` | account key `two_buttons` |
| Plan tags: DueCrew::<plan>::SLG_12 on followers' notes (Browse right-click, the builder, Tag by objective; 3.8.0) | `plans.sync_tags`, `plan_flow.apply_tags`, `ui/tag_dialog.py` | `plans.ts` tagNotes; This plan's tags in builder.js |
| Cuts (a video kept to an SLG) and a tag's single cards; taking a tag off (3.8.1) | `plans.match`/`plan_tag_cards`/`topic_items`, `plan_flow._unit_cids` | `planDoc`/`putIds` in `plans.ts`; `setCut`/`syncCuts` and the Text preview in builder.js |
| Your own pace (Up next, Open, Put back); Browse › open its cards / open these (3.8.0) | `plans.up_next`, `plan_flow.open_next`, `plan_flow.open_cards_now`, `ui/open_dialog.py` | follow `own` (`plans.ts`); `paceBox` in builder.js |
| Co-authors who said yes, handing a plan over (3.8.1) | `board._invite_lines`, `plan_flow.answer_invite` | `plans.ts` addEditor/answerInvite/offerPlan; `coauthorsBox` in builder.js, Home's invites |
| Notes for followers on a tag or a card (`remarks`, 3.8.1) | `plans.topic_remarks`, `cards.remark_view`, `ui/remark_dialog.py` | `plans.ts` remarks; `Remarks`, `remarkOn` in builder.js |
| A follower's day (3.8.1): Welcome back, what Hold back keeps, Study a date or a quiz | `plan_flow.welcome_back`/`show_held`/`study_date`/`study_quiz`, `plans.quiz`, `ui/away_dialog.py`, `ui/held_dialog.py` | never sent (Push my dates back is the follow's shift) |
| The builder's day's work and suggestions (3.8.1) | | `Work`, `Suggest` in builder.js |
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
secrets exist, so production is deployed by hand: `tools/deploy.sh` from a
clean `main` does the migrations, the API, then the site, then
`check_prod.sh` (`docs/go-live.md`, 2b).

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
  `tools/motion_preview.py` plays each motion on the real board; a
  redraw's motion lives in `motion.js` (only what changed moves, nothing
  with Reduce motion, no row ever slides past another; what leaves is put
  back inert for a moment, and a full draw compares with the page's
  session memory). The logo may move, never change: transforms only.
  A move ends exactly where the page lands, so nothing jumps when it
  cleans up (heights by `tall`/`inner`, folds by `room`, never
  offsetHeight); `tools/motion_audit.js` measures each one's last frame
  against the settled page (3.9.0).
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
