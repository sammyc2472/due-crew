# Your plans, and the plan windows

Python-native plan work inside Anki: Your plans (the duecrew.com builder,
in Anki), New plan from a calendar and Missed questions, in their own
package, `due_crew/planner/`. Built in labs (round three's mocks,
"Resource tags and a Python-native plan window", the design-spec
artifact) and, since 3.9.3, for everyone signed in (Sam's picks on the
proposals page: the ways in below, the names "Your plans" and "Missed
questions", authors edit in Anki). What it can't do yet stays the
builder's on duecrew.com (Not here yet, below).

## Ways in

- **Tools › Due Crew › Plans**: Your plans…, New plan from a calendar…,
  New plan from a deck…, Follow a plan…; Missed questions…, Export cards
  for my AI….
- **You › Plans**: its head row, *Open plans* (Your plans) and *New plan
  ▾*; each plan card's *Open* (Your plans, on that plan).
- **Insights**: *Missed questions* for a deck with a bank's question tags.
- **Settings' Find a setting** finds the three windows by their words.
- **Labs** is what stays behind this computer's switch, `"labs": true` in
  the add-on's config (no window sets it): Claude's stand-in in New plan
  from a calendar, and What Claude would get. Set it in Anki's Debug
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
  /plans/{id}/log`) and posts (`GET`, `POST`, `DELETE /plans/{id}/posts`). Each one on a click, in
  the background. A refresh and a sync are unchanged
  (`test_request_budget`).

## Your plans

My plans (the ones I write first, then the ones I follow), one at a time,
in tabs: **Dates** for everyone; **Lay it out**, **Text**, **Updates** and
**History** for a plan's authors.
**Reload** reads the plan again (an edit on the site meanwhile); **New ▾**
makes a date, a quiz or exam, a review day, or a new plan.

### Dates

Left, the plan's weeks ("Week 3 · 9–13 Nov", this week bold and open),
each date with its cards here, its events (in italics) and review days.
Right, the picked one:

- **A date**: when it opens, its due date and checkpoint, what it preps
  for; its cards here, new, still shut, the leeches that stay shut, and at
  the plan's pace "over 3 study days, about 35 a day"; its to-dos; then
  each source on its own row, grouped as the deck files it: by resource
  (#Videos, #Book…), by system (^Systems), other tags, a bank's questions
  (one row a bank), the plan's own tags, subdecks, searches, picked cards.
  Each row: cards, new, shut. A tag this copy names differently says so
  (the notes behind it found the cards).
- **A week**: its dates, with their numbers. **An event**: the dates that
  prep for it. **A review day**: the dates it reviews.
- **Notes on the day** (`day_notes.py`, the builder's day notes): under a
  date, a quiz or a review day, what anyone in the plan wrote on that day
  ("Lab day, keep it light"), and a box to add one (one line, 280); under
  a week, its days' notes, each with its day. Read once when a plan is
  picked or reloaded (`GET /plans/{id}/notes`, one request on that click; a
  save doesn't read them again). A note's writer takes it off, or an
  author. On a plan in the library only its authors write, and a
  stranger's note isn't shown. A note is on the plan's own day: a
  follower's date that moved shows the notes of its day in the plan.
- **Show in Browse**, **Open its cards**, **Study it** / **Study for it**;
  with a source row picked, **Open these** and **Study these** act on that
  row alone. For a whole date of a plan I follow here, while the board's
  copy is the version the window shows, Open is the plan's own (at my own
  pace, Up next's) and Study a date's or a quiz's Study; otherwise Browse's
  open (one undo step, never a leech, new ones first in line, and it says
  so when there's nothing to open) and a Due Crew deck of the open cards,
  and the window closes for Anki's Study screen. What the window opens, the
  morning and Not today count as they count Browse's.

An author (owner or co-author) sees the plan's own dates, and **Change ▾**
on the picked one, the builder's day panel as a menu:

- On a date: Add from the deck… (the picker, below), Add cards: a search
  or IDs… (a search counted here, note or card IDs, or a paste's notes:
  and cards:), Suggested from its name (the deck's tags its name points
  at, `build.suggest`), Take the picked one off, Split the picked one… (by
  its tags, chapters whole at the pace, or evenly over its study days),
  Only what one of this plan's tags holds (a cut), Without its extras, A
  note for followers on it…, Prep for (an event), Spread evenly to its
  due date, To do…, Make it a review day…, Rename…, Move to another day…
  (its due date and checkpoint the same days later), Due date…, Delete
  this date… (its review days with it).
- On an event: rename, move, delete (the dates that prepped for it let
  go). On a review day: its dates, or no review day.
- Each change is one save: `edits.py` changes the doc as the server keeps
  it (every field, so nothing it doesn't touch is lost), counts the dates
  it touched in this copy as the builder counts them (a follower's "204 of
  212"), and `remote.save` sends it with the version it started from, a
  history line ("Mon 9 Nov: added 1 tag (in Anki)"). What only the
  author's Anki sends (a date's note ids, refs, counts, pick names) isn't
  sent: the server keeps its own (`keepIdr`). A change that changes nothing
  isn't saved. A save from an older version (someone on the site, or my
  Anki's note ids at the day's first refresh) comes back stale: the window
  reloads and puts the same change on theirs, once. A refused one says why
  in the builder's words; a ceiling (429) says so too.
- **Undo**, after a save, is the builder's (`POST /plans/{id}/undo`): what
  the last save changed, back, for everyone.
- Tags picked in a copy whose top tag is named differently go in as the
  plan names them; a subdeck as the plan's deck writes it. A tag under
  another ticked one is left out (it comes with it). A day that has a date
  already asks before a second one lands on it.

### Lay it out (authors)

The builder's side panel and pace row (`layout_tab.py`, its rules
`build.py`'s, restated from builder.js):

- **What to cover**: the deck's tags by resource (#), by system (^), the
  rest, or its subdecks (the views the deck has), or a search over every
  path. Ticking a tag covers it and all below it; a tag that holds more
  than one view (a big shared deck's top tag holds resources and systems,
  the same cards twice) covers what this view shows of it. One already on
  the calendar is muted. "120 cards ticked · 80 not on a day yet."
  **Put it on …** puts the picked one on the next study day after the
  last date (the builder's +).
- **The pace**: Starts (moving it, once there are dates, moves every
  date, quiz, review day and the end with it, asked first); study days;
  Finish by a date, or a quiz or exam (the day before it, and the new
  dates prep for it); Cards a day ("done ≈ Fri 13 Nov"); or I'll place
  each day.
- **Fill** lays what's ticked and not on a date yet on the study days
  after the last date: chapters whole while they fit the pace, a bigger
  one by its own tags (the part only on it last), one with nothing below
  it spread evenly over its days. To an end date, a little more a day
  (about a tenth, up to seven times) until it all fits; past that it stops
  there and says what's left. **Just next week** stops at that week's
  Sunday. Fill and **Save the pace** save the ticks and the pace with the
  dates, one save; till then they wait here (another change's save keeps
  them).
- **What the plan asks**: the first run of days a quarter over the pace
  ("Mon 9 Nov asks 70 new a day (pace 30): Videos, 110 by Wed 11 Nov"),
  with **Split …** (its biggest tag, on the Dates tab) and **Give it till
  …** (the study days the pace needs); the reviews the dates bring, a
  typical card's, by week.
- **This plan's tags**: each with its cards here; Rename… (the dates, a
  cut kept to it, a search using it, its note, and a date named for it
  follow), Delete… (says first what goes: a date with nothing else, its
  review days; a cut is its whole tag again), Put it on a day. Tagging
  stays Browse's (right-click › Due Crew: tag for a plan…).
- **Every week**: the plan's weekly lines, Edit…. **Notes on cards**:
  the ones written in Browse, Take it off.

**New plan from a deck** (Tools › Due Crew › Plans, New ▾, You › Plans'
New plan ▾) now makes the plan here: the deck, a name, **Make the
plan** (its tree to the site, as before, then `POST /plans`), and Your
plans opens on it at Lay it out. **Open the builder instead** is the site.

### Text (authors)

The builder's Text (`text_tab.py`, its rules `text.py`'s, restated from
builder.js's toText and fromText): the plan as lines, a date a line
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
  never kept), and nothing changes until **Add to the plan** or **Replace
  the plan's dates** (asked first when something goes): one save, read
  again on the plan as it is when it saves. **Copy the plan as text**.
- What it can't read is said a line at a time, in the builder's words
  (a date first, a search about one person's Anki, due before it opens,
  even with no due date, a "for" with no such event, an ID that isn't one).

### Updates and History (authors)

`history_tab.py`, each read when its tab opens (one request), again after
a save.

- **Updates**: what the authors said to followers, newest first (who, a
  co-author marked, "with a save", when), and a post of one line, 200
  characters, five a day a plan (`POST /plans/{id}/posts`); its writer or
  the owner takes one back. "This version is in N of M followers' Anki"
  when the server says so.
- **History**: every save, who and what, newest first (the server keeps
  30); **Undo the latest** is the builder's Undo.

### Progress (authors)

`settings_tab.py`'s `ProgressTab`, read when the tab opens (one request,
`GET /plans/{id}/progress`). Its squad's counts a date, opened and done,
as a share of those in it; under three in it, how many are and nothing
more (counts, never names). Above the list, the builder's class hints
(`edits.behind`): a date most of the class hasn't finished two days after
it, the latest two, each with **Look at that day** (Dates, on it) and,
while dates are still to come, **Give the class a day** (`edits.breather`:
every date still to come one study day later, review days too; quizzes
and exams stay on their days), one save.

### Settings (authors)

`settings_tab.py`'s `SettingsTab`, the builder's Settings, in a scroll so
the window keeps its height. Each change is one request at once:

- **Name** and **One line**: Save the name and line (`PUT /plans/{id}`
  with only those and the version; someone else's save since is read and
  the change sent again).
- **Where to get the deck**: Save the link, a save of the doc (`deckUrl`).
- **Offer it to one of my squads** and **Who can follow** (anyone with
  the code, or only that squad): the owner's.
- **Co-authors**: Ask one of my crew… (mutual friends, `GET /friends`),
  each says yes first; Hand it to them (one who said yes), Take the offer
  back, Take them off or Take back the invite; a co-author's Leave this
  plan.
- **End**, **Catch-up weeks** and **Review-only days at the end**: saves
  of the doc's `end` and `phases`.
- **Library**: the owner's switch (only a plan anyone with the code can
  follow, with dates); taken out by the admin says so.
- **Copy for next year**: every date 52 weeks on, named "… (next year)",
  then Your plans on the copy. **Delete this plan…**, the owner's, asks
  first; followers keep every card they have open.

### Not here yet

The prompts for your own AI (the builder's "copy a prompt" boxes) stay on
duecrew.com.

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

## A plan from a block's calendar

Tools › Due Crew › Plans › New plan from a calendar, or You › Plans'
New plan ▾ (signed in: it makes a plan on the server). Paste the
block's calendar, or drop its file on the box (dashed, and in the accent
while a file is over it; or **Choose a file…**), pick the deck, **Read
it** (a dropped file reads at once):

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
| `planner/remote.py` | its requests (who I am, my plans, one plan, a save, its history and posts, its settings, progress, a copy, day notes) |
| `planner/reading.py` | pure: a calendar read, a session's tags, an exam's line, by plain rules |
| `planner/claude.py` | pure: Claude's stand-in, and what Claude would get (`request`) |
| `planner/flow.py` | the glue: the windows' asks (`Ops`, `StartOps`, `QidOps`), `make_here`, `qids.json` |
| `planner/window.py`, `layout_tab.py`, `text_tab.py`, `history_tab.py`, `settings_tab.py`, `day_notes.py`, `date_dialogs.py`, `picker.py`, `qid_window.py`, `start_window.py` | the Qt windows and their tabs, in the board's look |

Checks: `tests/test_planner.py` (the pure parts, `build.py` against
builder.js run in node, Fill and Lay it out, the save against the fake
Worker's `PUT /plans/{id}`, the labs switch, the rules of the road), the
planner renders in `tools/dialogs.py` (an author's window, a change saved
end to end, Change ▾ and New ▾, a review day, a search and a to-do saved,
Lay it out ticked, filled and its tags renamed, Text's Add dates and the
whole plan replaced, Updates' post, History's Undo, Progress with
Give the class a day, Settings' name and link saved and Copy for next
year, a day's notes (added, by day in a week, taken off), Make the plan
here, the
picker, Missed questions with its threads, Do it and All my misses, a
calendar read and made into a plan, What Claude would get, the Plans
menu), and `check_planner` in `tools/real_anki.py` (12,000
question tags, Bring back and Anki's undo of it, the picker's timings).

## Next (with Sam, or once the API is connected)

From round three: a follower's own resources (videos, book, a bank) and
Watched it at my own pace; Waiting and Tell followers; the Browse sidebar
and column; a merge on a stale save. Claude connected in the stand-in's
place (the same requests, a key Sam holds, each answer checked against
its shape and the lists it numbers); matching objectives to cards.
