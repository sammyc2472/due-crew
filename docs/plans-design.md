# Plans (3.1): design

Signed-off mock: the "Due Crew Plans" artifact (Dre builds, Maya follows).
This file is how it's built. What users see is in the mock; ask the maintainer before
changing any of it.

## Words

- **Plan**: a named list of **dates** for one shared deck, made by its
  **author**. Each date is a **unit**: a name, an opens date, an optional due
  date, an optional lead, and its cards.
- A unit's cards are any mix of **tags** (a tag path; everything under it
  counts), **subdecks** (a path below the plan's deck), and **single cards**
  (`[note guid, card ord]`, picked in Anki's browser; only that card, never
  its siblings).
- **Following**: a person runs a plan on one of their decks. Each morning
  the add-on unsuspends the cards whose unit has opened. It never suspends.

## Rules

- Card text never leaves Anki. The server holds names (tags, subdecks),
  counts, note guids with card ords, dates and progress counts.
- Nothing is ever suspended by a plan: not on unfollow, not when a unit is
  removed, not when a date moves later.
- Progress is shared only when the follower's switch is on, and then as
  counts per unit. Names appear only to mutual friends, as on the board.
- Requests: the plan rides the day's first `GET /board` (with `decks=1`);
  progress rides `POST /sync`. Following, authoring and uploading a deck's
  tree are one request each, on a click. No new requests on a normal day.

## Server (migration 0002)

```
plans         (id PK, code UNIQUE, owner, name, line, audience, squad,
               doc JSON, version, created_at, updated_at)
plan_trees    (uid, deck, doc JSON, at)            PK (uid, deck)
plan_follows  (plan, uid, share, paused, progress JSON, at)  PK (plan, uid)
login_links   (hash PK, uid, expires_at)
```

`plans.doc` is `{deck, exam?, units: [{id, name, opens, due?, lead?,
tags: [path], decks: [path], cards: [[guid, ord]]}]}`: one row, so an edit
is one compare-before-write and `version` goes up by one. Caps: 200 units,
5,000 single cards, 256 KB.

`audience` is `code` (anyone with the code) or `squad` (members of `squad`).
A plan offered to a squad shows as an offer on that squad's members' boards.

### Endpoints

| | |
|---|---|
| `PUT /plans/trees` `{deck, tags: [[path, n]], decks: [[path, n]]}` | The add-on's "Make a plan from a deck". Names and counts only; `GET /plans/trees` lists mine. |
| `POST /auth/link` | A one-time sign-in token for the site (five minutes, hashed, single use). |
| `POST /auth/link/redeem` `{token}` | The site trades it for a session cookie (`HttpOnly; Secure; SameSite=Strict`). Cookie requests that change anything must carry `x-due-crew: 1`. |
| `POST /plans` `{name, deck, line?}` | A new plan, no dates yet; I'm its author. |
| `GET /plans/mine` | Plans I wrote and plans I follow. |
| `GET /plans/peek?code=` | The plan behind a code, before following (60 an hour). |
| `GET /plans/{id}` | The author, a follower, or (with `?code=`) anyone who may follow it. |
| `PUT /plans/{id}` `{version, name?, line?, audience?, squad?, doc?}` | Author only. A stale `version` gets 409 with the current one. An unchanged save writes nothing. |
| `POST /plans/{id}/cards` `{cards, unit? \| opens (+ name?)}` | Author only: single cards onto a date that exists, or a new date. |
| `DELETE /plans/{id}` | Author only. Followers keep every card they have open. |
| `POST /plans/follow` `{code, share?}` | Follow. A squad plan needs membership as well as the code. |
| `PATCH /plans/{id}/follow` `{share?, paused?}` / `DELETE` | Change or stop. Sharing off clears my stored progress. |
| `GET /plans/{id}/progress` | Author: per unit, how many sharing followers have it opened and done. Counts only. |

`GET /board?decks=1` gains `plans` (the docs and versions of plans I follow)
and `planOffers`. `POST /sync` gains `plans: {id: {unitId: [opened, seen,
total]}}`, written only when it changed.

### Site sign-in

The site is served from `duecrew.com`; its API calls go to
`duecrew.com/api/*`, which the site's Worker hands to the API Worker by
service binding, so the session is a
same-site `HttpOnly; Secure; SameSite=Strict` cookie and no token is ever
in page script. The add-on opens `duecrew.com/plans/new#<one-time token>`;
the fragment never reaches a server log.

## Add-on

- `plans.py` (pure): matching and progress. `plan_dialog.py`,
  `follow_dialog.py` in `ui/`.
- **Matching**, per unit, inside the chosen deck and its subdecks:
  tags by path (case-insensitive, children included), after the follower's
  **prefix swap** (`Step1::` read as `Step1_v11::`, found once at follow
  time); subdecks by path under the chosen deck; single cards by
  `notes.guid` and `cards.ord`.
- **The morning**: on the day's first sync (or first open without a sync),
  for each followed, unpaused plan: the units whose `opens` ≤ today, not yet
  applied on this computer. The suspended cards among them are unsuspended
  in one undo step, "Due Crew: open <unit>". Applied units are remembered
  per plan version, so a unit whose date moves earlier opens the next
  morning, and one that moves later stays open.
- **Joining late**: "Open them now" applies every opened unit at once;
  "Start from the next unit" marks them applied without opening.
- **Progress** per unit: `total` found, `opened` = found and not suspended,
  `seen` = reviewed at least once. Done = seen == total.
- Local state (per profile and computer, `user_files/<profile>/plans.json`):
  `plans: {id: {deck_id, swap, applied: {unitId: sig | "skip:" + sig},
  src: {unitId: [deck_id, swap, tags, decks, cards]}, seen_version,
  snapshot}}`. A unit's sig (`plans.unit_sig`) names its sources, the deck
  and the swap: a date that moves keeps it, a unit the author adds cards
  to gets a new one, and then only the cards the new sources add to what
  `src` matched open (a card suspended since stays so). A leech never
  opens. Follow, share and pause are on the server.

## Tests

- Worker: access (author / follower / code / squad / stranger), version
  conflicts, caps, the link's single use and expiry, the board and sync
  additions, progress visibility (share off hides it, names only to mutual
  friends).
- Client (fakes.FakeWorker mirrors the Worker): matching with swap and
  single cards, never suspending, the undo step, joining late both ways,
  moved dates, pause, the request budget unchanged on a normal day.

## 3.2: plans as training

Signed-off mock: "Plans that train you" (T1–T7, N1–N3, W1, K2–K4; K1, the
switch, is dropped: who knows a card follows the decks I already share).
The idea is a marathon plan: the author says what and by when, and each
follower says when they study.

### The plan (the author's, on the site)

- `end`: the plan's last day (an exam, a course's end), optional.
- `phases: {catchup, taper}`: every `catchup`th week (3 or 4; 0 none) opens
  nothing new; the `taper` is the last N days up to `end`, with no new
  cards. Weeks count from the Monday of the first date.
- A date's `check`: a checkpoint, on or after it opens.
- Unit leads and the exam projection are gone (the server still reads
  3.1 docs that have them; the builder drops them on save).

### My schedule (mine, on my follow)

`sched: {start?, days, minutes}`: `days` Monday first, 0 a rest day, 1 a
study day, 2 a double share; `minutes` a day (10 to 600); `start` when I
begin later than the plan, which moves all my dates by the difference.
PATCH `/plans/{id}/follow {sched}`; `null` takes it off (dates open whole,
as in 3.1). The add-on asks right after following, and from Plan ▾.

`schedule.py` (and `Sched` in the site's app.js; keep them the same):

- A date's window is its opens to its due, or to the day before the next
  date opens, or its opens alone; all shifted by my start.
- `quota(date, day)`: the cards that should be open (and seen) by the end
  of my `day`: the window's study-day weights up to `day` over all of
  them, rounded up. A window with no study day in it opens on my next
  study day after it.
- The morning opens up to today's quota, the first cards in the deck's
  order (seen before, then new by position), never a leech, and marks the
  date applied once its window is over (from then on as in 3.1).
- Behind: yesterday's quota less what I'd seen by this morning. A missed
  study day saw under a quarter of its share. After one, the plan card
  asks once: spread what's waiting (a quarter of it on top of each day's
  share), push my dates back by the missed study days (never past `end`),
  or leave it open with no target. `catch` in plans.json.
- The load ahead: new cards a day from the schedule, each bringing reviews
  1, 3, 7, 16, 35 and 80 days later (and 12% lapses), on top of what's
  already due; against my minutes, with my own seconds a review and a new
  card from the last 30 days.
- The recap: on the first day of a plan week, last week's sessions kept,
  new cards and whether I'm on track. It rides my week (`recap`) for the
  crew's rows that day.
- A checkpoint's morning (up to 3 mornings late): Anki's own filtered deck
  "Checkpoint · <date>", the date's seen cards with most lapses first (60).
  The score (right first time since it was built) stays on this computer.

### Who knows this one

- Known: in the decks I share, a review card at 21+ days with no Again in
  30. Sent as note guids, as changes (`knows: {reset?, add, del}`, 2,000
  a sync), with `known.json` beside the session saying what went.
- Stuck: 2+ lapses, or Again today, in those decks; at most 300, most
  lapses first, on every sync (`stuck`). The answer comes in the same
  request: which mutual friends know each, and their tips (most helpful
  first, 3). Nothing about the question is kept.
- The chip, on the answer side of a card, beside Edit: a tip (click:
  the tips, This helped), else who knows it (Ask), else a crewmate's ask
  on a card I have (Tip). Never inside the card. The 2.10 in-card tip is
  gone; its tips show in the chip.
- Ask is a flag with my line (`q` on my week's `tricky`). The board lists
  asks on cards I know first: "Sam asks about a card you know". The first
  tip takes it down, as in 3.0.1, and a tip with words stays on the card
  for everyone in the crew stuck on it (`tips`).

### Tables (migration 0004)

```
plan_follows.sched    my schedule (JSON)
knows      (uid, guid)                     PK (uid, guid), index guid
tips       (guid, uid, text, at)           PK (guid, uid)
tip_helped (guid, tip_uid, by_uid)         PK all three
logs       (uid PK, json, at)              {days: {date: [min, reviews, new, retention]}}
```

### The site

- `/` signed in goes to `/home`: this week, today (from my last sync),
  cheers waiting (`GET /board?keep=1` leaves them for Anki), my plans and
  whether I'm on track, the crew (show-up when my settings say so) with
  Cheer, and squads.
- `/log`: this week, 12 weeks (minutes, reviews, new, retention), and each
  plan's cards seen against my schedule.
- `/admin`: counts only, for `ADMIN_UIDS` (a secret: comma-separated uids).

## 3.3: the builder is a calendar

Signed-off mock: "Building a Plan" (P1–P8, H1). P6 is a prompt for the
person's own AI, not one the server runs; P8 (co-authors, suggestions,
comments, the change log) comes after, save-based.

- **What to cover**: every tag, named readably ("#AK_Step1_v12::#Pathoma::
  01_Growth" reads "Step 1 › Pathoma › 1 · Growth", the raw tag beneath),
  in three views when the deck has them: by resource (a `#` tag), by
  system (a `^` tag), other tags; and subdecks. Ticking a tag covers
  everything under it; a tag holding more than one view covers only what
  the view shows (AnKing's top tag holds the same cards twice).
- **The pace**: the plan's study days (`pace.days`), and one of: finish by
  the end date (cards a day follow), cards a day (the finish follows), or
  day by day (each day is what's on it, as a class's syllabus).
- **Lay it out** puts what's ticked and not yet on a day onto the study
  days from the day after the last date, in the tree's order, chapters
  whole where they fit the day; a bigger one splits by its own tags, the
  cards only on it go last, and one with nothing below splits evenly.
  Catch-up weeks and the taper are skipped. **Plan next week** does the
  same for one week only, so a plan can be made a week at a time.
- **The calendar**: month, week or list; drag a chip to another day, a tag
  from the left onto a day, or use + and the day panel. A day shows its
  cards and a load bar against the pace; a heavy day offers a split.
- **Split**: by its tags (over the next study days at the pace), evenly
  over N study days (`even`), or single cards in Anki (the browser search
  to copy; Due Crew: add to a plan, onto that date).
- **As text** has "Copy the prompt": the plan's dates and pace, the line
  format, and the deck's tags with counts (what's ticked, or three levels,
  at most 600); never a card. The answer pasted back is read with a
  preview (tags matched in any case or by their readable name; `#` lines
  that ask for single cards listed to pick in Anki), then Replace or Add.

### Even dates

`{opens, due, even: true}`: the date's cards open in slices over its
window, on the plan's study days, skipping catch-up weeks and the taper;
the same slices for everyone, in the deck's order. With a schedule of my
own, my schedule spreads it as any date. `schedule.quota` does this for a
follower without a schedule, and the morning runs such a plan through the
3.2 spread. A 3.2.x add-on drops `even` and opens the date whole.

## 3.3: following is simpler, and plans are made together

### Following: do what's on the day

The maintainer's call: a follower doesn't set study days or minutes. Each date opens
on its day, whole, or in slices when the author split it evenly over the
plan's study days (`pace.days`). The plan card shows today's new cards,
reviews due and minutes left, on track or behind, from the plan's own
days. A 3.2 schedule keeps working (Plan ▾ › My schedule… changes or
takes it off); nothing asks for a new one. The board has a Plans tab while
I follow a plan: a card each, one bar a date, "crew 3/6".

### The tree

The add-on sends the deck's tags nested, each name once (`plans.nest`):
the most useful first (tags that aren't question-bank ids, shallow before
deep, big before small) while it fits 1.4 MB; the Worker takes up to
1.5 MB for `PUT /plans/trees` only. A 3.2 server gets the old lists.

### Together (save-based; migration 0006)

```
plan_editors (plan, uid, at)                     PK (plan, uid)
plan_notes   (id, plan, uid, day, text, at)      index (plan, day)
plan_log     (plan, version, uid, at, summary, prev)   PK (plan, version)
```

- **Co-authors**: the owner adds them from their crew (mutual friends);
  they edit everything but the audience, the co-authors and deleting the
  plan, and can leave. Up to 10.
- **Notes on a day**: anyone in the plan (authors and followers) writes a
  line on a day; the writer or an author takes it down. They show as 💬 on
  the calendar and in the day's panel. This is also how a follower
  suggests a change.
- **History**: every save logs who, a few words the site writes ("moved
  Heme 2 to Tue 6 Oct"), and the doc it replaced; the last 30 stay. The
  latest can be undone (itself a save, so it can be undone too).
- **Two authors at once**: a save that meets a newer version merges in
  the page: my changes (against what I loaded) go onto theirs, date by
  date, then save again. No live connection, nothing running when nobody
  has the plan open.
- `/plans/{id}` is the one page: authors get Calendar, As text, Progress,
  History (and the owner Settings); a follower gets the calendar, their
  on-track line and the notes.

### Hold back, and a deck with no tags (3.3)

- A teacher's deck, imported by students, has every card active: a plan
  can't hold anything back. Follow shows, checked when there's anything
  to hold, "Hold back N cards of later dates until their day"
  (`plans.holdable`: new, never studied, not suspended, not a leech, on
  a date that hasn't opened and on no date that has). Following
  suspends them in one undo step (`plans.hold_cards`) and keeps their ids
  in `held`; the morning opens them on their day as any suspended card;
  Stop following opens what's still held. Nothing else ever suspends.
- A plan followed elsewhere (the site's code box, another computer) asks
  the same question once, on its first morning here (`plan_flow.offer_hold`,
  "… is new on this computer"), in one undo step.
- The deck itself is in the tree (`DeckIndex.tree`), so a deck with no
  tags or subdecks is planned in its own order: tick it, 20 a day, Fill
  the calendar.
- From Anki, Make a plan opens the new plan's calendar directly (named
  after the deck; the title edits in place), at 20 new cards a day.
- The shared link (`/p/CODE`) is three steps for someone new: Anki, the
  add-on's code, Follow a plan with this code.

## 3.3: a class through Step (C1–C5)

Signed-off mock: "A class through Step", with the maintainer's picks (the preset:
a copy when shared; keep note ids for tag and subdeck dates).

- **C1 Anki's daily limit.** `plan_flow.new_limit` reads what Anki will
  show today (the deck's today-only or own limit, else its preset). When
  today's target is above it, the card says so with Raise to N:
  `raise_limit` sets the deck's own limit (Deck Options › This deck), so
  no other deck changes and no preset is copied. Anki records that as an
  undo step (a preset change it doesn't), so Edit › Undo puts it back;
  checked against the real engine (`tools/real_anki.py`).
- **C2 Open early.** `early` on my follow, 0–7 days, from Plan ▾ › Open
  early. The morning runs as if it were that many days later
  (`run(..., when)`); the tiles and "behind" stay on today.
- **C3 Searches.** A date's `search: [q]` runs through
  `col.find_cards(q)` and is kept to the plan's deck; `unit_sig` includes
  searches, so a new one opens what it adds. From Anki's browser, Add to
  a plan offers the search in the box (with its count, `sn`) or exactly
  the selected cards (those, when any are selected). On the site a day
  takes a pasted search. A search about one person's own Anki
  (`deck:current`, the browser's default; `is:due`, `flag:`, `rated:`…)
  finds different cards for everyone, so neither side takes it
  (`plans.shareable_search`, `PERSONAL` in builder.js). 50,000 single
  cards a plan (docs up to 1.5 MB).
- **C4 Study and review days.** Study on a date's row builds "Due Crew ·
  <date>" (its seen cards, most lapses first) and opens it. `reviews:
  [{day, from, to}]`: on that morning (up to three late) "Review · A – B",
  the dates from A to B, 200 cards. The site's day panel sets them
  (+ Review day); a 3.2 checkpoint loads as a one-date review day.
- **C5 AnKing updates.** A date's `ids`: the note ids behind its tags and
  subdecks in the author's copy. The day's first board carries
  `authored` (my plans, lean); `send_ids` computes each plan's ids from
  the deck of the same name and sends them when they changed
  (`PUT /plans/{id}/ids`, kept only while the tags are the same). A
  follower's tag or subdeck that finds nothing falls back to the ids;
  the card says so once.

### Speed (3.3)

A deck's tags, note ids and subdecks are kept between refreshes
(`plans._STATIC`) while a fingerprint holds (card count, newest note
edit, newest card, deck and card-number sums; a few ms); only each
card's state is read again, and so are a date's searches (they depend
on notes and cards, never on reviews). On a 35,000-card AnKing-shaped
deck a refresh's plan work is ~50 ms after the first (~550 ms). `tools/real_anki.py`
checks it, with Anki's own package, before a release.

## 3.4: a pasted search's count, and the plan in your calendar

Signed-off mock "Plans 3.4" (D1, D2).

- **D1.** The plans I write ride the day's first board (`authored`) with
  their searches. My Anki counts each (`plans.search_counts`, kept to the
  plan's deck) and sends the counts with the note ids (`PUT
  /plans/{id}/ids {units, counts}`), one request a plan, only when
  something changed. The site shows a pasted search as "counted in your
  Anki soon" until then, and "finds nothing" when it finds none.
- **D2.** `duecrew.com/p/CODE.ics` (the site's Worker passes it to `GET
  /plans/ics?code=`, no sign-in, 120 an hour a code, cached 3 hours):
  each date an all-day event ("name · N new"; an even date spans to its
  due date), each review day one too, a link back to the plan, nobody's
  name. A plan for one squad has none. Add to calendar (plan page for its
  authors and code-plan followers, and the shared link's page): Google
  Calendar (subscribe by URL), Apple Calendar or Outlook (`webcal:`), or
  the link. Followers of a code plan now see its code.

### Cards by ID, and printing (E1, E2)

- A date can hold note ids (`nids`: every card of each note) and card ids
  (`cids`: that card), pasted as a list in the day's Add cards box (a
  spreadsheet column, or ids with commas or spaces) or as `nids:1,2` in
  Text. Up to 5,000 of each a date, counted into the plan's 50,000 single
  cards. They're numbers, so they work wherever the deck is the same (an
  AnKing copy, a class deck imported from one file); a follower missing
  some gets the rest. Each follower's Anki finds them inside the plan's
  deck; the author's Anki counts them at its next refresh (`"#ids"`, kept
  as `idn`), as it does a pasted search. They are not C5's `ids` (guids
  behind a date's tags).
- Print (a view beside Month, Week, List and Text, for authors and
  followers): the dates from a range as a list, one row per study day by
  week, a box to tick, the day's topics grouped by resource (B&B, Pathoma,
  Sketchy), searches by name, ids and picked cards as counts; review days
  shaded; notes and days off optional. The page's own print style; no
  server change.

### Events, and the dates that prep for them (F1)

- An event is a named day (`events: [{id, day, name}]`): a lecture, a
  quiz, the block exam. It holds no cards and opens nothing. A date's
  `for` names the event it preps for; the calendar marks the event with
  its count of prep days and each prep day with "for Micro quiz", and
  pointing at an event lights its prep days up.
- In the builder: Prep for on a day (or + New event), Make it an event on
  an empty day, and the event's own box (rename, Move it, Take it off).
  Finish by can aim at an event: the finish date is the day before it,
  and the dates Fill makes are for it.
- Text: `2026-10-15 | event | Micro quiz`, and a date line ends with
  `for Micro quiz`. The print list, the calendar feed and the add-on's
  plan card (`plans.prep_for`: "For Micro quiz on Thu · 2 more days of
  prep") show them.

### A follower's own days (G1-G7)

A plan is the crew's shared guide; a follower can shuffle their own week.
Only their copy changes: never the plan, the author's calendar, or anyone
else's cards; events never move.

- **Open now** (G1) on the next date's row: that date, today, one undo
  step; the morning leaves it.
- **Not today** (G2) replaces the morning's Undo: Anki's undo, then those
  dates open on tomorrow's morning (`later` in plans.json).
- **Skip a date** (G3): it never opens for me and isn't "waiting"; the
  row stays, crossed out, with Undo skip. Kept on my follow (`skipped`).
- **Pause until…** (G4), filled in from my Away dates. The morning after
  it asks: move my dates later by the days I was away (`shift`), or open
  what opened meanwhile. **Push my dates back…** sets `shift` directly.
- **Catch up** (G5): "N new cards from earlier dates waiting · Catch up…"
  over 3, 5 or 7 days: each of those mornings sets Anki's today-only
  new-card limit on the plan's deck (its own plus the extra). Nothing to
  put back: a today-only limit ends at midnight.
- **My progress on the site** (G6): a follower who shares their progress
  sees it on each date, and their skips; nobody else does.

## 3.5: plans that spread (mock "Plans that spread")

### A: a plan's link previews as the plan

A pasted `duecrew.com/p/CODE` shows the plan in a chat or a post: the site
Worker puts its name and one line in the page head (`og:` and `twitter:`
tags, escaped), and `/p/CODE.png` is a 1200x630 picture of it: the logo,
the name (two lines at most), whose it is, the deck, its dates, followers,
its weeks as a strip (darker with more new cards, an event's week
outlined) and the code. Only what the signed-out page already shows
(`/plans/public`), so a squad's plan gets the plain head. The picture is
drawn pixel by pixel in `site/src/og.ts` from glyphs and the logo drawn
once by `tools/og_assets.py` (Inter, OFL), with no font engine or
WebAssembly; a missing glyph (a script Inter doesn't have) is left out,
and a name with nothing left reads "A study plan". The peek is cached five
minutes and each version's picture a week, whatever `?v=` asks.

### B: the library

An owner lists a plan from its Settings ("anyone with the code" plans with
dates, 20 a person). Anyone signed in finds it at `/library` by deck,
length and words, newest first: the follower count shows on each card
but never orders the list. Look opens its calendar (a listed plan reads
like one shared by code), Follow follows it, Copy makes a plan of my own
starting on a day I pick (dates, events and review days move together;
no followers, notes or co-authors) that says whose it was based on. A
plan made for a squad leaves the library. Report mails the admin; the admin's Take
out removes it with a line its author reads on Settings, and it can't be
listed again until the admin puts it back. Deleting an account takes its name
out of copies' credit.

### C: classes

`/classes` says how a class lead runs a class's deck (static, linked from
the landing page). The Progress tab says when most of the class is
behind: a date finished by under half of those sharing (3 or more), two
days after its date, with "Look at that day" and "Give the class a day"
(every date after today one study day later; events stay; the author
saves). Print has a Poster: the plan's name, a QR code of its link
(`site/public/qr.js`, byte mode, error correction M, checked against a
reference encoder and a decoder), the code, and how to follow.

