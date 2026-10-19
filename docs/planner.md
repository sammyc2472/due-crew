# The plan window (labs)

Python-native plan work inside Anki, built before the Claude API is
connected and kept apart from the rest of the add-on while it's tried:
its own package, `due_crew/planner/`, and nothing of it runs for anyone
who hasn't turned it on. The mocks are round three's ("Resource tags and
a Python-native plan window", the design-spec artifact).

## Who sees it

- **Labs switch.** This computer's add-on config has `"labs": true`. No
  window sets it and `config.json` doesn't have it. Anki's Config button
  opens the board's Settings, so set it in Anki's Debug Console
  (Ctrl+Shift+; on Windows and Linux, ⌘⇧; on a Mac), then restart Anki:

  ```python
  c = mw.addonManager.getConfig("2035408484"); c["labs"] = True; mw.addonManager.writeConfig("2035408484", c)
  ```

  (`"2035408484"` is the AnkiWeb folder; a copy installed by hand under
  another folder name uses that name.) `False`, or taking the key out,
  turns it off after the next restart.
- **Tools › Due Crew** then has *Plan window (labs)…*, *New plan from a
  calendar (labs)…* and *Question IDs (labs)…*, after its own entries.
- **The plan window, and a plan from a calendar, are the admin's account
  only.** Its click asks the
  server who this account is (`GET /auth/me`, whose `admin` is
  `worker/src/notices.isAdmin`: Sam's "sammy" account), once an Anki
  session, and opens only for that account; anyone else is told it's the
  admin's while it's in labs. Question IDs touch nothing but this
  collection, so the labs switch alone opens them.
- **Nothing new on the server.** The window's requests are routes the
  site's builder uses already: `GET /auth/me`, `GET /plans/mine`,
  `GET /plans/{id}`, an author's save, `PUT /plans/{id}`, its Undo, and
  New plan, `POST /plans`. Each one on a click, in the background. A
  refresh and a sync are unchanged (`test_request_budget`).

## The plan window

My plans (the ones I write first, then the ones I follow), one at a
time. Left, the plan's weeks ("Week 3 · 9–13 Nov", this week bold and
open), each date with its cards here, and its events (in italics). Right,
the picked one:

- **A date**: when it opens, its due date and checkpoint, what it preps
  for; its cards here, new, still shut, the leeches that stay shut, and at
  the plan's pace "over 3 study days, about 35 a day"; its to-dos; then
  each source on its own row, grouped as the deck files it: by resource
  (#Videos, #Book…), by system (^Systems), other tags, a bank's questions
  (one row a bank), the plan's own tags, subdecks, searches, picked cards.
  Each row: cards, new, shut. A tag this copy names differently says so
  (the notes behind it found the cards).
- **A week**: its dates, with their numbers. **An event**: the dates that
  prep for it.
- **Show in Browse**, **Open its cards**, **Study it** / **Study for it**;
  with a source row picked, **Open these** and **Study these** act on that
  row alone. For a whole date of a plan I follow here, while the board's
  copy is the version the window shows, Open is the plan's own (at my own
  pace, Up next's) and Study a date's or a quiz's Study; otherwise Browse's
  open (one undo step, never a leech, new ones first in line, and it says
  so when there's nothing to open) and a Due Crew deck of the open cards,
  and the window closes for Anki's Study screen. What the window opens, the
  morning and Not today count as they count Browse's. **Reload** reads the
  plan again (an edit on the site meanwhile).

An author (owner or co-author) sees the plan's own dates, and **Change**
and **New date…**:

- Add from the deck… (the picker, below), Take the picked one off (a tag,
  a subdeck, a tag kept to a plan tag, with its search, or a bank's
  questions; not the last thing on a date), Rename…, Move to another day…
  (its due date and checkpoint the same days later, as the builder's
  move), Due date… (or none; an even split goes with it), Delete this
  date… (its review days with it), New date… (pick what it opens, then its
  day).
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
- Not here yet: events, searches, picked cards, cuts made, to-dos, the
  pace, co-authors; those stay the builder's on duecrew.com.

## The picker

The deck's tags as it files them, a level at a time (#-parts first, then
^, then the rest; a bank's questions counted, not listed), each with its
cards and new ones here, then its subdecks; or a search over every tag's
path ("heart failure"). Tick what goes on the date; everything under a
ticked tag comes with it. Read from the deck index on the main thread.

## Question IDs

After a practice block: paste the IDs of the questions I missed, any way
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
- The labs windows close with the profile.

## A plan from a block's calendar

Tools › Due Crew › New plan from a calendar (labs), the admin's account
only, as the plan window (it makes a plan on the server). Paste the
block's calendar, pick the deck, **Read it**:

- **The calendar** (`reading.read_calendar`, plain rules): a line that
  starts with a date ("Mon 10/26", "Oct 26", "26 October 2026",
  "2026-10-26") or a table's row with a date in a cell is a session; the
  lines under it its objectives ("SLG 1 …") and what it lists ("Watch:
  …"); "Week 2" numbers the ones after it (else weeks count from the first
  session's Monday); breaks and holidays are left out. A quiz or an exam
  becomes one of the plan's events, every other session a date on its
  day, named as the calendar names it. The plan's name is the first line
  that names something and holds no date.
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

**Claude's jobs, a stand-in for now** (`claude.py`): plain rules go first
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
| `planner/__init__.py` | the switch (`enabled`) and the menu entries (`install`, from `__init__._tools_menu`) |
| `planner/model.py` | pure: a tag's kind and name, a date's sources, weeks, pace words, the picker's tree and search |
| `planner/qids.py` | pure: numbers, banks, a paste found, threads, the kept misses |
| `planner/edits.py` | pure: an author's changes to the doc, the count, the history line |
| `planner/actions.py` | Bring back, the one collection step it adds |
| `planner/remote.py` | its requests (who I am, my plans, one plan, a save) |
| `planner/reading.py` | pure: a calendar read, a session's tags, an exam's line, by plain rules |
| `planner/claude.py` | pure: Claude's stand-in, and what Claude would get (`request`) |
| `planner/flow.py` | the glue: the gate, the windows' asks (`Ops`, `StartOps`, `QidOps`), `qids.json` |
| `planner/window.py`, `picker.py`, `qid_window.py`, `start_window.py` | the Qt windows, in the board's look |

Checks: `tests/test_planner.py` (the pure parts, the save against the fake
Worker's `PUT /plans/{id}`, the gate, the rules of the road), the planner
renders in `tools/dialogs.py` (an author's window, a change saved end to
end, the picker, Question IDs with its threads, Do it and All my misses,
a calendar read and made into a plan, What Claude would get, the labs
menu), and `check_planner` in `tools/real_anki.py` (12,000
question tags, Bring back and Anki's undo of it, the picker's timings).

## Next (with Sam, or once the API is connected)

From round three: a follower's own resources (videos, book, a bank) and
Watched it at my own pace; Waiting and Tell followers; the Browse sidebar
and column; a merge on a stale save. Claude connected in the stand-in's
place (the same requests, a key Sam holds, each answer checked against
its shape and the lists it numbers); matching objectives to cards.
