# Plans (3.1): design

Signed-off mock: the "Due Crew Plans" artifact (Dre builds, Maya follows).
This file is how it's built. What users see is in the mock; ask Sam before
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
