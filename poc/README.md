# Course on a Mac (proof of concept)

A separate add-on, beside Due Crew and not part of it. It never talks to Due
Crew's server, and Due Crew never reads it. You give it a block's calendar; for
each lecture, the Mac's own language model does the jobs Due Crew's two AI
prompts ask a chat to do today:

1. **Reads the calendar**: each session's date, kind and title, and its objectives.
2. **Gives the search words** a deck would use (HFrEF for "systolic").
3. **Picks the resources** Anki's search found (your deck's tags, grouped by
   video series or book): all of it (whole), some of it (part), or none (no).
4. **Reads the cards** of a part, about ten a call, against the objectives:
   which fit, and which cloze of a cloze card.

Plain code does the rest: the dates, the counting (what's new, what an
earlier lecture already opens, leeches stay shut, objectives nothing fits), and
writing it all down. You tick, then open by video as you watch, with one
Edit › Undo each time.

The model never sees a card id or a tag name it could invent. It answers by
position in lists Anki made, and every answer is checked against a fixed shape.
Card text is read on the Mac and goes nowhere. It uses the on-device model
only, never Private Cloud Compute.

## Install

1. Double-click `course_mac_poc.ankiaddon` (or Tools › Add-ons › Install from
   file), then restart Anki.
2. You'll find it under **Tools › Course on a Mac (PoC)**.

## Turn on the Mac's model (once)

Apple Intelligence has to be on (System Settings › Apple Intelligence & Siri),
on an Apple silicon Mac.

- **macOS 27: nothing to install.** The Mac's own `fm` command is the model.
  Tools › Course on a Mac (PoC) › **Settings…** says "the fm command, nothing
  to build"; press **Check the model** to try it. Leave Model on **Auto**.
- **macOS 26:** the add-on builds a small Swift helper on your Mac on Apple's
  FoundationModels framework. Building needs Apple's Command Line Tools: if
  `swiftc` isn't there, run `xcode-select --install` in Terminal first. If a
  full Xcode is installed but was never opened, Apple's tools first want its
  license accepted: Build says so, and `sudo xcodebuild -license accept` in
  Terminal does it once. Then **Settings…** › **Build the helper**. It takes a
  minute or two and says which build it kept. It tries four builds: with or
  without the permissive guardrails, and with or without the model's context
  size, so an older SDK still builds. On macOS 27 the helper is optional; it
  gives the model's answers in their exact shape, and reads PDFs.

**Check the model** says whether Apple Intelligence is ready, the window size
it reports, and how long one real call took. **Auto** takes the built helper,
else the `fm` command, else plain rules. If `fm` doesn't answer, **fm's
help** shows the flags this Mac's `fm` takes (they weren't settled in Apple's
docs when this was written).

No Mac model, or the build fails? **No model** runs the same flow on plain
rules: the title and objective words matched to tag names. It's useful as a
comparison too.

## Make a course

1. **Open…** › **New course…**: name it (MS2 Block 2) and pick your deck.
2. **Calendar…**: paste the block's calendar, or Load a file (text; a PDF
   works once the helper is built). **Read with the Mac model** or **Read as
   lines** (for a calendar already one line a session, its objectives indented
   under it). Untick anything that isn't a session, then **Add the ticked ones**.
3. Pick a lecture and check its objectives (one a line: `SLG 5 | what it says`).
4. **Read this lecture** (or **Read the unread lectures**). Each lecture shows
   its rows, already ticked where the model and the counts agree:
   - **whole**: a video or chapter for this lecture, all of it;
   - **part**: only the cards that fit (Cards says "21 of 46");
   - **found**: cards outside those tags whose text holds the words;
   - **no** / **later**: left out, or another lecture's title names it.
   Double-click a row to see its cards in Browse.
5. **Open ticked**, or **Open this row** for one video at a time. Either is one
   step in Edit › Undo. Opened cards go first in Anki's line of new cards (a
   setting).

Also there:
- **Tag the cards…** adds `Course::<course>::<date>_<title>` to the lecture's
  notes and `Course::<course>::SLG_5` to the cards that fit an objective, in
  one undo step.
- **Copy as plan text** copies the whole course in Due Crew's plan text, with
  plan tags, cuts (`tag:… in SLG 5`) and `for <quiz>`. Paste it into the
  builder's Text › Add dates and click Read it. It carries tag names and note
  ids, never card text.
- **Open each lecture's ticked cards on its day**: off by default. When it's
  on, Anki opens a lecture's ticked cards once its date comes, about 15
  seconds after the profile opens.
- In Browse, right-click a tag (a video) › **Course: what my course asks of
  this tag…**. It splits the tag's cards by lecture, with an Open for each.
  **Ask the Mac model** reads the cards no lecture has yet against the whole
  course.

## Measure it against your matchup

You follow a plan whose tags (`DueCrew::<plan>::SLG_12`) already pair your
school's SLGs with cards. That's an answer key.

1. Tools › Course on a Mac (PoC) › **Measure against my plan's tags…** (with
   the course's deck picked in the course window first).
2. Answer key: pick your plan's `DueCrew::…` root.
3. Paste a few objectives as `SLG 12 | what it says`. The label must match the
   plan's tag name. Set How many (5 is a good start), then click **Run**.
4. Each objective runs as its own lecture. You get: of the key's cards, how
   many it found; of what it chose, how many are in the key; seconds each; and
   the same for plain rules. **Copy the results** copies labels and numbers
   only. Paste them to me.

A whole video brings cards a single SLG tag doesn't hold, so "right" runs lower
than "found" by design. The plain-rules column is what the model has to beat.

## What to send back

- The measure results (copied).
- Settings › Check the model's text (which build, the window size, one call's time).
- If something went wrong: Settings › **Open the log**. It keeps one line a
  call: the job, its time, its size, and what went wrong. It keeps the
  model's answers only if you tick that setting.

## Limits, on purpose

- The model's window is small (4,096 tokens per Apple's WWDC26 Q&A). It reads
  one lecture at a time and about ten cards a call.
- It's never asked what's true: only which of what Anki found serves the
  objectives you gave.
- A call it refuses (guardrails) is retried once as plain text; if it's
  refused again, those cards stay unread and show as unread, never guessed.
- Nothing opens or gets tagged until you click, and each of those is one undo.

## Take it away

Tools › Add-ons › Course on a Mac (PoC) › Delete. Your courses are in its
user_files folder and go with it. To remove the tags it added, search Browse
for `tag:Course::*`, select all, then Notes › Remove Tags.

## For the code

`poc/course_mac/`: `model.py` (the helper, `fm`, no model), `helper.swift`,
`jobs.py` (the four jobs: prompts, shapes, checks, rules), `find.py` (tags by
resource, matching), `course.py` (rows, checks, plan text), `engine.py` (the
collection side), `cal.py`, `store.py`, `glue.py` and `ui.py` (Anki).
Tests: `python -m unittest poc/tests/test_course_mac.py` (needs `pip install
anki`); the windows offscreen: `QT_QPA_PLATFORM=offscreen python
poc/tests/render_course_mac.py OUT_DIR` (also needs PyQt6).
