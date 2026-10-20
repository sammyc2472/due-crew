# Your plans, and the plan windows

Python-native plan work inside Anki: Your plans (the duecrew.com builder,
in Anki), New plan and Missed questions, in their own package,
`due_crew/planner/`. Built in labs (round three's mocks, "Resource tags
and a Python-native plan window", the design-spec artifact), for everyone
signed in since 3.9.3, and rebuilt in round five (Sam's picks on the
"Simpler Plan Builder" page: one screen to build a plan, a date changed
where it's shown, the plan's shape on one line, one way to start,
changes waiting to be sent, a paste box, a follower's Plan · Settings, Plan
· Settings, no Pip in the plan windows), then made plain and quick (no
AI look; one way to each thing; keys, Find, Month's drag, Latest first). Nothing
suggests what goes on a date (Sam's call, after the picks: plain rules
aren't trusted to choose cards, and it isn't AI): the author puts every
card on, from the deck beside the date or a search.

## Ways in

- **Tools › Due Crew › Plans**: Your plans…, New plan…, Follow a plan…;
  Missed questions…, Export cards for my AI….
- **You › Plans**: its head row, *Open plans* (Your plans) and *New plan
  ▾* (New plan…, or on duecrew.com); each plan card's *Open* (Your
  plans, on that plan).
- **Insights**: *Missed questions* for a deck with a bank's question tags.
- **Settings' Find a setting** finds the three windows by their words.
- **Labs** is what stays behind this computer's switch, `"labs": true` in
  the add-on's config (no window sets it): Claude's stand-in, session by
  session (New plan's labs link opens the calendar window), and What
  Claude would get. Set it in Anki's Debug
  Console (Ctrl+Shift+; on Windows and Linux, ⌘⇧; on a Mac), then
  restart Anki:

  ```python
  c = mw.addonManager.getConfig("2035408484"); c["labs"] = True; mw.addonManager.writeConfig("2035408484", c)
  ```

  (`"2035408484"` is the AnkiWeb folder; a copy installed by hand under
  another folder name uses that name.)
- **Nothing new on the server.** The windows' requests are routes the
  site's builder uses already: `GET /plans/mine`, `GET /plans/{id}`, an
  author's save, `PUT /plans/{id}`, its Undo, New plan, `POST /plans`
  (with Make a plan's `PUT /plans/trees`), its history (`GET
  /plans/{id}/log`) and posts (`GET`, `POST`, `DELETE /plans/{id}/posts`),
  A send's line rides its save (`PUT
  /plans/{id}`'s `post`, as the builder's Updates already send it). Each
  one on a click, in the background. A refresh and a sync are unchanged
  (`test_request_budget`).

## Your plans

Round five (Sam's picks on the "Simpler Plan Builder" page, all A): one
window, my plans picked on top (the ones I write first, then the ones I
follow), **Undo** (a button with its menu) and **New plan…** beside it.
Two tabs whoever I am: **Plan · Settings** (an author's Settings is the
plan's own; a follower's, my follow). No Pip in the plan windows (Sam's
pick 10). With no plans yet, the window is a welcome instead: what a plan
is, **New plan…** and **Follow a plan…**.

Every change is an op (`ops.py`, below). With anyone following, or with
changes already waiting, it **waits under the plan** (`draft.py`), kept on
this computer, till **Review and send**; with nobody following, it saves
at once and Undo takes it back. A save, its undo or a setting changes
the plan, never the deck: the window keeps the deck's index and tree (a
big deck's is seconds of work); picking a plan reads them again.

Every change names again the dates still named for what's on them, as
the builder's renameAll does (`edits.name_dates`, `build.auto_name`): a
tag with another date below it reads "Cardio · the rest", a date named
for a cut follows its plan tag's rename. A name an author typed stays.
Tags read and sort as the site's do (`build.tag_word`, `build.natural`).

### Plan (authors)

`plan_tab.py`, top to bottom:

- **The shape**, to read, label by label on one line (`view.shape_line`):
  Dates "Mon 12 Oct – Block 2 exam, Fri 13 Nov", Study days "Mon–Fri", New
  a day "20", Reviews peak "~115 a day, week 5", Last days "3 with no new
  cards", Catch-up "every 4th week"; with no end, "…, no end set". It's
  changed in Settings.
- **The toolbar**, over the list it acts on: **List | Month**, Earliest
  first / Latest first (the list's order; the line at today stays between
  past and to come), Find (a date or tag: only the dates whose name or
  cards have its words; Enter picks the first, Esc clears), Today, Needs
  a look (N), Expand all / Collapse all, **Add** (A date…, A quiz or
  exam…, A review day…, Lay out from the deck…). Needs a look
  (`view.needs_look`, shown only when something does) keeps the weeks
  with a date that has no cards here or a day over the pace.
- **The weeks**, each saying what it asks (`view.week_asks`: new cards a
  study day, a typical card's reviews a day: "9 new, 34 reviews a day";
  amber, "41 new a day (over your 20), 52 reviews", when a day of it is
  a quarter over the pace). Past weeks start collapsed; a line at today.
  Each date: its day, its name, its cards here, its sources on one muted
  line under it with their counts (`model.sources`, as the deck files
  them), "No cards yet" on an empty one, "not sent" on a date a waiting
  change touched. A quiz is one line, its name in bold and what it tests
  at the end; review days; the days with no new cards. The first heavy
  run gets "Over the pace" with its fixes: Split its biggest tag…, Let it
  finish by … (`build.heavy`, `give_till`). Month is the same plan on a
  month's grid; an author drags a date or a quiz onto another day to move
  it (the same op as its Cards open, `widgets.DayCell`).
- **Beside it, the picked date** (`date_panel.py`), changed where it's
  shown: its name; Cards open (a new day moves it; so do Alt+← → and
  Month's drag), Finish by (a day, or none); Tested on (a quiz, or a new
  one). **Its cards (N)**, a source a line (`widgets.Source`: its name,
  its count, ✕ takes it off; a click opens its menu: Show these in
  Browse, Split it…, Keep only cards also tagged (one of the plan's own
  tags), Leave out its extras (N cards), A note for followers on it…).
  **Add from the deck** puts the deck in the date's place, ticking for
  it, Done brings the date back; Add a search or IDs…; Show the N in
  Browse. **To do** (followers tick these in Due): Add a to-do…
  (Change its to-dos… once it has some); the plan's every-week lines that
  land on it, to read. **Notes on its day** (`day_notes.py`): what anyone
  in the plan wrote on that day, and a box to add one. Under **⋯**: Move
  this and the N dates after it… (`move_from`: review days move with
  them, quizzes stay), Keep only cards also tagged…, Spread its cards
  evenly to its finish-by day, Copy its search for Anki, Open its cards in
  my Anki now, Delete this date…. A quiz or exam and a review day get
  panels of their own.
- **The deck** (`deck_panel.py`, Lay it out's tree before), in the date's
  place while cards go on (no tab of its own: Add from the deck is the way
  in, Add › Lay out from the deck… with no date): by resource, by system,
  or More (the rest, subdecks, the plan's own tags: Rename…, Delete…, a
  note on it), and a search over every path. For a date, a line says so
  ("Ticks add to Mon 19 · Heart failure", Done) and a tick puts the tag on
  it or takes it off. With none, ticks are what the plan covers, and the
  part under them lays them out (`lay_out`, the builder's Fill): "212
  ticked, not on a date. At 20 a day they'd end Wed 2 Dec, 19 days after
  the exam." in red, with **Fit them before the exam: 31 a day**, Lay
  them out at 20 anyway, Next week only; or, fitting, Lay them out at 20
  a day. Save the ticks only keeps what's ticked without laying it out.
  Notes on cards (written in Browse) are taken off from here.
- **Paste plan lines or a new course calendar**, then **Show the
  changes**: plan lines go to the text's Add (read and shown first); a
  calendar (`reading.py`, on this computer) becomes dates on its days,
  named and with no cards, and its quizzes and exams as quizzes; asked
  first, one change. **The plan as text** (the Text window below). **AI
  prompt** (a button with its menu): Plan the dates, Tag by objective
  (`prompts.py`, builder.js's Prompts, the deck's tag names and counts,
  never a card).
- **The changes waiting**, the window's foot under a rule: "3 changes not
  sent: Shock moved, Shock changed, and 1 more", each a link that picks
  its date; **Discard** (asked first: nobody saw them), **Review and send**
  (`send.py`): each change in words with who it touches ("Open since Mon
  19: anyone who has its cards keeps them", "Not open for anyone yet"), a
  ✕ each, **Tell them why** filled in from the changes (`ops.why_line`,
  200 at most), **Send to N**: one save (`PUT /plans/{id}` with its
  `post`, the line followers get with it; past five a day the save goes
  all the same, `postWithSave`).

**Keys** (each in its button's tip): anywhere in the Plan tab, Ctrl+N a
date, Ctrl+E a quiz or exam, Ctrl+F Find, Ctrl+T Today, Ctrl+1 List,
Ctrl+2 Month, Ctrl+D the deck for the picked date, Ctrl+Z the last change
not sent (a save made at once is undone; a send opens Undo's menu),
Ctrl+Return Review and send. With the plan itself in focus (a click on a
row): ↑ ↓ the date before or after, Alt+← → a day earlier or later, Enter
or F2 its name (a double-click too), Delete takes it off (asked first).
A box keeps its own keys (Ctrl+Z in a box undoes the typing).

**No AI look, and one way to each thing** (Sam, after the site mock: "a
few of our UI elements are AI hallmarks; we are going for extreme
functionality"): no accent stripe on the picked row or today, no tinted
banners (the shape, today, behind, the deck's target, the send bar and
the code are plain lines), no chips (a date's sources are a line in the
list and a list in the panel), no ◆, no "+ A …" links, no capitals for
the changes' kinds, no ▾ or ↗ in words (a button that opens a menu has
the boxes' chevron), and what explained a control is its tip. An action
is a button, one kind with the boxes' corners and height (`widgets.tool`;
side-by-side choices are one control, rounded at its ends,
`widgets.segs`); a link is only a way to a date. Nothing is in two
places: no Study in the window (the board studies), no deck tab, no
−1/+1 day, no Followers tab, no Change… window.

**Undo**: take back the last change not sent; undo the last save or
send of this window's (the builder's Undo, `POST /plans/{id}/undo`: the
whole send at once); History: every save… (`HistoryDialog`, every save
who and what, the server keeps 30; Undo the latest).

Changes waiting are the ops and the version they started from, kept on
this computer per profile (`plan_drafts.json`), never sent till Send. The
plan they show is the ops replayed on the plan as the server has it: a
co-author's save meanwhile, or Anki restarting, loses nothing; an op that
no longer fits (its date taken off) is dropped and said. A send from an
older version comes back stale: the window puts the same changes on
theirs, to look over and send again. A change that changes nothing isn't
kept. Followers keep every card that opened; a change never shuts one.

### Settings (authors)

`settings_tab.py`'s `SettingsTab`, the builder's Settings, everything
about the plan as a whole in one place (Sam, round five: "rename sharing
to settings and move as much of the overall settings stuff there as we
can"):

- **The plan**: Name and One line; its dates and pace (`shape.py`'s
  `Shape`, rows of the form where the Change… window was): Starts (every
  date and quiz moves with it), Ends with (one of its quizzes or exams, a
  day, or nothing yet), Study days, New cards (Up to N a day, Fit to the
  end, I set each date), No new cards before the end, Catch-up weeks. A
  change says what it does under them before anything goes in ("Saving
  moves 18 dates and 2 quizzes"), with Put it back and Add to the changes
  (or Save, nobody following): `shift_all`, `set_end`, `set_pace`,
  `set_phases`, one go. Every week: the lines followers tick on the same
  weekday each week (Change…, `set_every`).
- **Sharing**: its code, Copy link (duecrew.com/p/CODE), Open its page;
  Where to get the deck (a change, `set_deck_url`); Offer it to one of my
  squads and Who can follow (the owner's); **Followers**: how many follow,
  and **Posts…** (`send.PostsDialog`, `history_tab.UpdatesTab`: what the
  authors said, each send's line among it, and a post of one line, five a
  day a plan). How far followers are, or whose Anki has the last send,
  isn't shown (Sam's call, round five: it added nothing; what followers
  do together is the plan's squad on the board's Squads tab). Co-authors
  (Ask one of my crew…, each says yes first; Hand it to them; Take them
  off; a co-author's Leave this plan); Library (the owner's).
- **This computer**: Your AI app, on or off, Set up… (AI hooks, below).
- **Copy it for next year**; **Copy as a table** (the dates tab-separated,
  for a spreadsheet); Delete this plan…, the owner's, asked first.

The `breather` op (every date still to come a study day later) stays for
the text and an AI app.

### Plan and Settings (a plan I follow)

Plan: **Today** with **Study now** (the date whose window has today in
it; else the next one), **N dates behind** with Study the N left, then
the same weeks and dates to read: what's open and left on each, what
each quiz tests and how much of it I've seen, a date's cards, its to-dos
and its notes. Settings (`mine_tab.py`): My dates (as the plan, or some
days later), Skipping (✕ to stop, Skip a date), Cards open (each morning
on their dates, or when I'm ready, Up next), Held back, its squad, Pause
until… / Resume, Make my own copy (a library plan), More (Change deck…,
Open everything now, Open early), Stop following…. Each is plan_flow's own
step, one request on a click; the window reads my follow again once it's
taken.

### The text

`text_tab.py`'s `TextDialog` (Edit the whole plan as text, or plan lines
pasted in), the builder's Text, its rules `text.py`'s, restated from
builder.js's toText and fromText: the plan as lines, a date a line
("2026-10-05 | Heart failure | tag:…, deck:… | due 2026-10-09 | even |
for Heme quiz | watch: Lecture 14"), an event ("… | event | Heme quiz"),
one of the plan's own tags ("tag | SLG 12 | notes:…"), a note for
followers ("note | tag:… | words"); "week 3" for the plan's third Monday;
a tag by its path in any case or its readable name. **The whole
format** opens duecrew.com/plan-text.

- **Add dates**: lines pasted in go on; a line with a date's own day and
  name adds to it (its tags, searches, IDs, picks, to-dos). Changes
  nothing already there.
- **Edit the whole plan**: the plan as text, edited. A date keeps its id
  (followers' skips, moves and progress) by its day and name, or, with
  neither, by its name on another day (moved) or by its cards under
  another name (renamed); a tag line with a new name and the same cards is
  that tag renamed (its dates follow). What the text leaves out goes, said
  first; a tag it leaves out that a date still uses asks: **Take them off
  those dates too** (a cut is its whole tag again; a date left with
  nothing goes) or **Keep the tags** (their lines back in the text).
- **Read it** shows what would change (each date with its cards here,
  moved from or was, a tag new or added to, notes; a tag the deck doesn't
  have; a day over the pace; "# Pick in Anki" lines; an AI's own notes,
  never kept), and nothing changes until **Add to the plan** (Add to the
  changes, with anyone following) or **Replace the plan's dates** (asked
  first when something goes): one change, the ops' `text`, read again on
  the plan as it is. **Copy the plan as text**.
- What it can't read is said a line at a time, in the builder's words
  (a date first, a search about one person's Anki, due before it opens,
  even with no due date, a "for" with no such event, an ID that isn't one).

## The picker

The deck's tags as it files them, a level at a time (#-parts first, then
^, then the rest; a bank's questions counted, not listed), each with its
cards and new ones here, then its subdecks; or a search over every tag's
path ("heart failure"). Tick what goes on the date; everything under a
ticked tag comes with it. Read from the deck index on the main thread.

## Missed questions

(Question IDs in labs.) After a practice block: paste the IDs of the
questions I missed, any way
the bank copies them. Every run of 3 to 9 digits is a number; only the
ones the deck has as a question count (a tag whose last part is that
number, under a bank's #part), so a date or a score pasted with them is
said as "isn't a question here", never guessed at. With two banks, the
one with the most of them, or the one picked.

- What they are here: open already, still shut, leeches that stay shut,
  and the dates of my plans they're on.
- **What they have in common**: the deck's own tags most of them share,
  by system and by resource ("Systems › Cardio · 9 of 15 questions"), a
  question counted once a thread, each line of tags named once at its
  deepest. Picking one makes Show in Browse, Study and Do it about it.
- **Open 6, bring back 8** (the button says what it does): the shut ones
  open (never a leech, new ones first in Anki's line) and, ticked, the ones
  seen before come due over the next 3 days (Anki's Set due date,
  intervals kept; not a card in a filtered deck; one due already or inside
  the 3 days is left as it is, so nothing is put later), one undo step,
  `actions.bring_back`. More than 200 to bring back asks first. **Study
  them now** (or this thread): a Due Crew deck of their open cards. The
  deck list is top decks (question tags are deck-wide); a bank I pick holds
  for this paste and deck only.
- **All my misses**: a paste I act on (Do it, Study) is kept on this
  computer, in this profile's `qids.json`: the numbers, by day, deck and
  bank, never card text, never sent (200 pastes, 20,000 numbers). All my
  misses reads every one kept for the deck and bank: its threads across
  blocks, and a deck of all of them. Forget my misses, with its Undo.
- The plan windows close with the profile.

## New plan

Round five's one way to start (`new_plan.py`; Tools › Due Crew › Plans ›
New plan…, You › Plans' New plan ▾, Your plans' New plan…; signed in:
it makes a plan on the server). **Name**, **Deck**, **Ends with** (the
exam's name and day, so the plan knows its end from the first minute;
empty for none), and **the course calendar if there is one**: pasted in or
its file dropped on the box (or Choose a file…), read on this computer as
it's typed ("Found 18 sessions and 2 quizzes or exams"; its name and its
exam fill the boxes above, unless typed in). **Make the plan**
(`edits.new_plan_doc`, then `POST /plans` and the builder's save): each
session a date on its day named as it is, with no cards (the author
puts them on in Your plans: nothing is picked for them); its quizzes and
the exam its events; each date tested on the next one; the pace fitting
what's ticked to the end. Your plans opens on it. Without a calendar it's
an empty plan with its exam and end: the deck beside it, to tick what the
exam covers and lay it out. **Following a friend's plan instead?** Their
code, Follow. In labs, a link opens the calendar window below, session by
session with Claude's stand-in.

## A plan from a block's calendar (labs)

The calendar window, session by session (`start_window.py`), behind the
labs switch since round five (New plan reads a calendar for everyone).
Paste the block's calendar, or drop its file on the box (dashed, and in
the accent while a file is over it; or **Choose a file…**), pick the
deck, **Read it** (a dropped file reads at once):

- **Its file** (`reading.from_file`, read on this computer, never sent): a
  calendar export (.ics: each event's day and title, its description's
  lines under it, the calendar's name first), a PDF (Qt's own reader, up
  to 400 pages; one whose text comes out in pieces says so), a Word file
  (.docx: its paragraphs, a list item as an objective, its tables' rows
  cell by cell), slides (.pptx: each slide's title, its lines by level,
  its tables' rows, in the deck's own order; never its pictures or
  notes), a CSV or a text file. A sheet says to save it as CSV, an old
  .ppt or Keynote file as .pptx or PDF, anything else to copy its text
  in. A PDF, Word file or deck up to 300 MB (their pictures weigh; only
  their words are read), a text file up to 5 MB.
- **A lecture's slides** (Add its slides…, or a .pptx or PDF dropped on a
  session's row): its objectives slide's lines, and any line labelled
  like one ("SLG 3 …"), join the session's objectives; the other slides'
  titles name what it covers (`reading.from_slides`; a deck title,
  Questions, References and the like left out). Its tags are found again
  with them, and What Claude would get carries the slides' titles, never
  their words.

- **The calendar** (`reading.read_calendar`, plain rules): a line that
  starts with a date ("Mon 10/26", "Oct 26", "26 October 2026",
  "2026-10-26") or a table's row with a date in a cell is a session; the
  lines under it its objectives ("SLG 1 …") and what it lists ("Watch:
  …"); "Week 2" numbers the ones after it (else weeks count from the first
  session's Monday); breaks and holidays are left out. A quiz or an exam
  becomes one of the plan's events, every other session a date on its
  day, named as the calendar names it (a room or hall at a title's end
  left off; a kind column, "LEC" or "Lecture:", too, but "Exam 1" stays
  whole). The plan's name is the calendar's head, the first line before
  its sessions that holds no date, else the file's name.
- **Its tags** (`reading.candidates`/`pick`): the deck's own tags its
  words name (tag names only: card text is never read), the title counting
  most; ticked where plain rules are sure (the title names it, or three of
  its words do), one a resource. A tag holding the same cards as one in
  already, or too broad to be one session's (600 cards), gives way.
  **Add tags…** opens the picker on a session.
- **What's on it…** on a quiz or exam: its line, as the syllabus says it.
  Weeks ("weeks 1-3"), numbered lectures ("lectures 1-12"), dates ("Oct 26
  to Nov 13", "through Nov 13") by plain rules; the dates it covers prep
  for it (a date's `for`), else each preps for the next event after it.
- **Make the plan**: asks once, then the builder's New plan (POST
  /plans) and its save (PUT, the dates and events), mine, nobody
  following; then the plan window, on it. A plan made whose dates didn't
  save says so, and Make tries its dates again on that plan, never a
  second one.

**Claude's jobs, a stand-in for now, labs only** (`claude.py`): plain rules go first
in every job, and Claude is asked only for what they leave. Until it's
connected, a stand-in answers in its place by looser rules of its own, so
each step can be click-tested, and each row it filled says "Claude's
stand-in" (with why, pointed at). Untick its box for plain rules alone.

| Job | What plain rules leave | What the stand-in does |
|---|---|---|
| calendar | no line starts with a date (prose, a file's text) | a date anywhere in a line ("we meet on Oct 26 for…") |
| pick | a session nothing matched | the title's words one at a time ("antiarrhythmic"), then a few abbreviations read as a reader would ("HFrEF" as systolic) |
| scope | some of a week ("week 4's two pharm lectures") | that week's sessions whose titles, or the tags ticked for them, have the words (diuretics are renal) |

**What Claude would get** shows, as JSON, each request the stand-in's
jobs would have sent: the calendar's words; a session's title, objectives
and what it lists, with the deck's tags it could have (its candidates, the
tags whose last part starts as its words do, and the ones beside what the
block has ticked, `reading.could_fit`), by name and card count; for an
exam's line, the sessions by title and the tags ticked for them. Never a
card's text, an id, or anything about anyone. Claude answers by number in
lists made here, never with a name it could invent, in the shape each
request carries. Nothing is sent: `claude.py` has no requests.

## AI hooks

Round five: an AI helps an author, never in their place. Every job's
answer is ops (`ops.py`), checked before anything changes, and waits
under the plan like any change (`draft.py`). `ai.py`, pure.

- **Jobs** (`ai.JOBS`), plain rules first in each: **calendar** (a block's
  calendar into sessions; `reading.read_calendar`, the AI only for a
  paste it finds no dates in), **pick** (a date's cards from the deck's
  paths it could take; the builder's Suggest first), **scope** (the dates
  an exam covers; reading's weeks, numbered lectures and dates first),
  **words** (a change in my own words, "push everything after the quiz a
  day", as ops), **tag** (Tag by objective's lines), **check** (lines
  worth a look; no changes) and **plan** (Plan the dates' lines: one
  `text` op, added; the whole plan in its place only when asked).
- **A request** (`ai.request`: `{job, v, input}`) carries the plan's
  names, days and counts, its own date and event ids, the deck's tag and
  subdeck paths with their card counts, and my words (an email in them
  goes as [email]). Never a card's text, a note's or card's id (a date's
  picked notes go as a count) or anyone's name: a key it doesn't know is
  refused, and one shaped like card text (fields, question, answer,
  notes, cids…) says why. A pick's path or a scope's date it wasn't
  given comes back refused.
- **An answer** (`ai.answer_ops`): only ops the registry knows, with
  only their own fields, each checked and tried in order on a copy, as
  the ones before it leave the plan; 200 at most (`ops.OPS_MAX`). What
  won't go on is said, never applied. `ai.vocabulary()` is every op, its
  fields and an example (the suite checks it against `ops.REG`); Split
  by its tags is Your plans' own, never offered to an AI.
- **Runners** (`ai.runner_for`): Off; Claude's stand-in (labs; its rules,
  said as its); **your own AI**: the prompt to copy (Plan the dates' and
  Tag by objective's are `prompts.py`'s; my words' lists the ops and the
  plan by date id) and its answer pasted back (`OwnAI.read`: the JSON out
  of a code fence and the words around it); **Claude**, through the
  Worker later ("Claude isn't connected yet."). Nothing new on the server.

### Your AI app (a local MCP server)

Off by default, this computer's own (`"mcp": {"on", "port", "token"}` in
the add-on's config; never an account key, never sent). On, an AI app
here (Claude Desktop, Claude Code, any other) reads my plans and puts
changes under one I write. It **never sends a plan**: the author reviews
and sends in Anki (Your plans › the plan › Review and send).

- **The server** (`mcp.py`, standard library, no Anki): Streamable HTTP
  with JSON answers, `POST http://127.0.0.1:PORT/mcp`, one message or a
  batch; GET is 405 (no stream). On 127.0.0.1 only;
  `Authorization: Bearer <token>` on every request (401); a Host that
  isn't `127.0.0.1:PORT` or `localhost:PORT`, or an Origin that isn't
  this computer's, is 403 (DNS rebinding); 1 MB a body. Nothing it's
  sent is logged, the token least of all.
- **Its tools**: `list_plans` (mine with my role and how many follow; the
  ones I follow), `read_plan` (its text, its dates by id with cards,
  sources and the quiz each preps for, its events, the changes waiting,
  shown in), `deck_tags` (paths and card counts; find, under, limit),
  `ops_vocabulary`, `preview_changes` (in words, with who each change
  touches; changes nothing) and `add_to_changes` (into the plan's draft
  here, authors only; each op marked `"by": "ai"` with the call's
  `why`; an open Your plans hears of it, `draft_changed(pid)`). Review
  and send says "From your AI app" under each such change, and when
  every change waiting is the AI app's with one reason, that reason is
  the line to followers (`ops.send_line`); the marks stay on this
  computer: the server gets the plan.
- **The glue** (`mcp_host.py`): my plans and a plan through `remote`, in
  the server's thread; the deck, the drafts and today on Anki's main
  thread, 30 s at most. On at profile open and sign-in, off at sign-out
  and profile close (`app.ai_app`); each host is one `app.generation`.
  The port it got is kept, so the setup stays right. A draft is kept
  only over the one it read (a change in Your plans meanwhile: read
  again).
- **Your AI app** (`mcp_dialog.py`): the switch; on, the address and
  the token (Copy, New token), **Copy setup** (the shim: `python3 -I
  mcp_shim.py --port N`, the token in its environment, never its command
  line) and **Copy HTTP setup** (the address with the bearer header).
- **The shim** (`planner/mcp_shim.py`, and `tools/due_crew_mcp.py`, byte
  for byte; the suite checks): stdio to the server for an app that starts
  a program. When Anki isn't running it says so on stderr, never the
  token, and each request gets an error back.

## Files

| File | What |
|---|---|
| `planner/__init__.py` | the labs switch (`enabled`) and Tools › Due Crew › Plans (`plans_menu`, from `__init__._tools_menu`) |
| `planner/model.py` | pure: a tag's kind and name, a date's sources, weeks, pace words, the picker's tree and search |
| `planner/qids.py` | pure: numbers, banks, a paste found, threads, the kept misses |
| `planner/edits.py` | pure: an author's changes to the doc (the builder's edits), the count, the history line |
| `planner/build.py` | pure: the builder's rules restated (Todo, Every, Remarks, Picks, Suggest, Work, Reviews, Tags, Fill, Split, layOut, What to cover) |
| `planner/text.py` | pure: the builder's Text (toText, fromText, Add and Replace, what it would change) |
| `planner/actions.py` | Bring back, the one collection step it adds |
| `planner/remote.py` | its requests (who I am, my plans, one plan, a save, its history and posts, its settings, a copy, day notes) |
| `planner/reading.py` | pure: a calendar read, a session's tags, an exam's line, by plain rules |
| `planner/claude.py` | pure: Claude's stand-in, and what Claude would get (`request`) |
| `planner/ai.py` | pure: the AI hooks (jobs, what a request carries, answers checked into ops, runners, the ops' vocabulary) |
| `planner/mcp.py`, `mcp_host.py`, `mcp_dialog.py`, `mcp_shim.py` | Your AI app: the local MCP server (standard library), its glue in Anki, its window, the stdio shim (`tools/due_crew_mcp.py`'s twin) |
| `planner/ops.py` | pure, round five: every change an op (its checks, the builder's edit it runs, its words, who it touches, the line to followers) |
| `planner/draft.py` | pure, round five: changes waiting to be sent (ops replayed on the plan as the server has it; one send) |
| `planner/view.py` | pure, round five: what the Plan tab shows (the shape line, each week's asks, needs a look, today) |
| `planner/prompts.py` | pure: the prompts for your own AI, builder.js's `Prompts` restated |
| `planner/flow.py` | the glue: the windows' asks (`Ops`, `StartOps`, `NewOps`, `QidOps`), `make_here`, `plan_drafts.json`, `qids.json` |
| `planner/window.py`, `plan_tab.py`, `date_panel.py`, `deck_panel.py`, `shape.py`, `send.py`, `followers_tab.py`, `settings_tab.py`, `mine_tab.py`, `new_plan.py`, `text_tab.py`, `history_tab.py`, `day_notes.py`, `date_dialogs.py`, `widgets.py`, `picker.py`, `qid_window.py`, `start_window.py` | the Qt windows and their parts, in the board's look |

Checks: `tests/test_planner.py` (the pure parts, `build.py` against
builder.js run in node, Fill, the save against the fake Worker's `PUT
/plans/{id}`, the labs switch, the rules of the road, the AI hooks and the
MCP server), `tests/test_plan_ops.py` (round five: the ops, their words
and who they touch, changes waiting and replayed on a co-author's save,
the Plan tab's arithmetic, no suggestion left, New plan's empty dates, a send's line kept by the fake Worker), the planner
renders in `tools/dialogs.py` (an author's tabs, Plan · Settings, a date's sources, a change
saved and undone, a stale save put on theirs, a new date with nothing
suggested,
Settings' dates and pace and Put it back, the deck in the date's place and Done, Lay out from the deck, the
text added and the whole plan, a calendar pasted, changes waiting with
people following (the foot's links), Review and send, Undo after a send, a co-author's
save under waiting changes, no Followers tab and Settings' Posts…, Settings, History, a
day's notes, Month and a date dragged to another day, Ctrl+Z, the Plan tab's keys, Expand all and Collapse all, Latest first, ↓ and Find, a follower's Plan and Settings, a plan that lost its
dates and a load that failed, no plans yet, New plan from a calendar,
no Pip anywhere in them, Missed questions, the calendar window in labs),
and `check_planner` in `tools/real_anki.py` (12,000 question tags, Bring
back and Anki's undo of it, the picker's timings).

## Next (with Sam, or once the API is connected)

From round three: a follower's own resources (videos, book, a bank) and
Watched it at my own pace; Waiting and Tell followers; the Browse sidebar
and column; a merge on a stale save. Claude connected in the stand-in's
place (the same requests, a key Sam holds, each answer checked against
its shape and the lists it numbers); matching objectives to cards.
