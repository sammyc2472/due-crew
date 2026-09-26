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
`duecrew.com/api/*`, routed to the same Worker, so the session is a
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
- Local state (config, per computer): `plans: {id: {deck_id, swap,
  applied: {unitId: version}, paused}}`. Follow and share are on the server.

## Tests

- Worker: access (author / follower / code / squad / stranger), version
  conflicts, caps, the link's single use and expiry, the board and sync
  additions, progress visibility (share off hides it, names only to mutual
  friends).
- Client (fakes.FakeWorker mirrors the Worker): matching with swap and
  single cards, never suspending, the undo step, joining late both ways,
  moved dates, pause, the request budget unchanged on a normal day.
