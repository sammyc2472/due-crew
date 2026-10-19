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
- **Tools › Due Crew** then has *Plan window (labs)…* and *Question IDs
  (labs)…*, after its own entries.
- **The plan window is the admin's account only.** Its click asks the
  server who this account is (`GET /auth/me`, whose `admin` is
  `worker/src/notices.isAdmin`: Sam's "sammy" account), once an Anki
  session, and opens only for that account; anyone else is told it's the
  admin's while it's in labs. Question IDs touch nothing but this
  collection, so the labs switch alone opens them.
- **Nothing new on the server.** The window's requests are routes the
  site's builder uses already: `GET /auth/me`, `GET /plans/mine`,
  `GET /plans/{id}`, and an author's save, `PUT /plans/{id}`. Each one on a
  click, in the background. A refresh and a sync are unchanged
  (`test_request_budget`).

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
- **Show in Browse** (the picked row's cards, else the date's), **Open its
  cards**, **Study it** / **Study for it**. These are plan_flow's own steps:
  for a plan I follow here, a date's Open is the plan's (at my own pace, Up
  next's) and Study is a date's or a quiz's Study; otherwise Browse's open
  (one undo step, never a leech, new ones first in line) and a Due Crew
  deck of the open cards. What the window opens, the morning and Not today
  count as they count Browse's.

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
  sent: the server keeps its own (`keepIdr`). A save from an older version
  comes back stale: the window reloads and says to make the change again
  (no merge yet). A refused one says why in words.
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
- **Do it**: the shut ones open (never a leech, new ones first in Anki's
  line) and, asked, the ones seen before come due over the next 3 days
  (Anki's Set due date, intervals kept; not a card in a filtered deck),
  one undo step, `actions.bring_back`. **Study them now** (or this thread):
  a Due Crew deck of their open cards.
- **All my misses**: a paste I act on (Do it, Study) is kept on this
  computer, in this profile's `qids.json`: the numbers, by day, deck and
  bank, never card text, never sent (200 pastes, 20,000 numbers). All my
  misses reads every one kept for the deck: its threads across blocks,
  and a deck of all of them. Forget my misses, with its Undo.

## Files

| File | What |
|---|---|
| `planner/__init__.py` | the switch (`enabled`) and the menu entries (`install`, from `__init__._tools_menu`) |
| `planner/model.py` | pure: a tag's kind and name, a date's sources, weeks, pace words, the picker's tree and search |
| `planner/qids.py` | pure: numbers, banks, a paste found, threads, the kept misses |
| `planner/edits.py` | pure: an author's changes to the doc, the count, the history line |
| `planner/actions.py` | Bring back, the one collection step it adds |
| `planner/remote.py` | its requests (who I am, my plans, one plan, a save) |
| `planner/flow.py` | the glue: the gate, the windows' asks (`Ops`, `QidOps`), `qids.json` |
| `planner/window.py`, `picker.py`, `qid_window.py` | the Qt windows, in the board's look |

Checks: `tests/test_planner.py` (the pure parts, the save against the fake
Worker's `PUT /plans/{id}`, the gate, the rules of the road), the planner
renders in `tools/dialogs.py` (an author's window, a change saved end to
end, the picker, Question IDs with its threads, Do it and All my misses,
the labs menu), and `check_planner` in `tools/real_anki.py` (12,000
question tags, Bring back and Anki's undo of it, the picker's timings).

## Next (with Sam, or once the API is connected)

From round three: a follower's own resources (videos, book, a bank) and
Watched it at my own pace; Waiting and Tell followers; starting a plan
from a block's calendar and matching objectives (Claude's jobs); the
Browse sidebar and column; a merge on a stale save.
