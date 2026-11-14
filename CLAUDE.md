# Due Crew — project context

Consent-based friends leaderboard add-on for Anki. Sam is the sole
maintainer. The repo is the source of truth; there is no build step for the
add-on.

## Layout

- `due_crew/` — the add-on. `__init__.py` (the main-thread rules in its docstring; since 3.9.12 the
  glue itself is `glue/`, a package by part: `refresh`, `render`, `sync`, `commands`, `windows`,
  `settings`, `profile`, `table` (`BOARD_CMDS`), `joined` (Anki's hooks); one namespace, so
  `due_crew._on_js` reads as before; the five flags it sets as it runs are `glue.refresh._run`),
  `plan_flow/` (the plans' glue, twelve parts the same way: `plan_flow.X` as before), `board/` (pure HTML rendering; since 3.9.8 a package by
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
  (board.png: `tools/readme_images.py`, then `node tools/readme_images.js`;
  magic, insights, closet, party, dance: `tools/preview.py`, `tools/readme_shots.py`,
  then `node tools/readme_shots.js`).
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
- `tests/` — `python3 tests/test_due_crew.py` (it runs `tests/suite/`, eight parts in the order the
  tests were written, one namespace, 3.9.12; `tests/srcs.py` reads a module that became a package as one
  text; client behavior against
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

Every feature's full notes, with the why, are in `docs/history/`, by
version (`docs/history.md` is its index). Read a feature's entry there before changing it
(`grep -rn` its module, its `duecrew:` command or its mock's name in that folder). These hold everything up:

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
  deck ids belong to one collection. `plans.py` is pure, `plan_flow/`
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

## Twins, and where things live

- **Twins** (`docs/twins.md`): logic that runs in two places, restated by hand (the board and
  app.js's `Board`, `schedule.py` and `Sched`, `bingo.evaluate` and bingo.ts, the planner and
  builder.js, the Worker and `tests/fakes.FakeWorker`, and more). Before changing anything that has
  a copy on the site or the server, read that list: change both sides in the same commit, each with
  its test.
- **Where things live** (`docs/where.md`): one row a feature, with its files in the add-on and on
  the server and site. Look a feature up there before searching for it.

## Releasing

1. Bump `due_crew/manifest.json` version, and add the release's bullet to
   the newest file in `docs/history/` (what changed, where, why).
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

`tools/gate.sh` runs the whole gate here, one line a check (`--quick`: pyflakes and the suites;
`ANKI_PY=<a Python with aqt>` adds the dialogs and the click test, last and alone), and
`tools/ship.sh` writes `ship/` (the package, the AnkiWeb README, the deploy block).
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
  a **tip** is a tip (3.9.11 called it a hook for two days; my own tips live in `hooks.py`,
  `hooks.json` and `PUT /hooks`, names kept from then: a person never reads "hook");
  **Pip** is `sev`; **Pip Party** is `gamenight` (its tab says Party); the
  **scrapbook** took Wrapped's place (`wrapped*` is the year's numbers);
  **unsuspended**, never unlocked; a plan's **set** on the site is a date in
  the add-on's code.
- What a page is told to draw has a named shape in `views.py` (3.9.12: the
  review chip, a plan's card, Insights, the dance floor), checked where it's drawn
  (`views.seen`): a slip counts as `view:<name>` and is drawn anyway; the suite's last
  check is that nothing it drew slipped. A new surface's view gets its shape there.
- A big module is a package by part, one namespace (board/, plan_flow/, glue/, tests/suite/):
  a new function goes in the part its subject names; a part reads an earlier part's names by
  import and a later part's through `_LATER` (the package sets them); a part is never named
  after a module beside it; a flag a function sets lives in a holder, not a module-level name.
- A button on the board starts from `board.button_reset(selector, extra)` (3.9.12, one
  core for every part; a part adds only its own and never restates it); a page of its
  own carries `base.page_reset(scope)`'s text (Magic search, the plan window); the site's
  pages carry `board.SITE_RESET`.
- What a person reads is said through `words.py` (3.10.0; `docs/languages.md`): `t("phrase")`, English the
  key, a phrase whole (never built from halves), each language's in `due_crew/lang/`. A new phrase gets all
  four languages in the same commit (`python3 tools/words.py`). Surfaces not wrapped yet read English.
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
