# Twins: change one, change both

(Moved out of `CLAUDE.md` in 3.9.12, which keeps the rule and this pointer.)

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

