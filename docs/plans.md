# How plans work

The one current description of study plans: what a plan is, what a
follow is, what each side keeps, and what happens each morning. The why
of each piece, by version, is in `docs/history.md` (search for the
feature); `docs/plans-design.md` is the 3.1–3.5 design notes, kept for
their reasoning. The plan text format (what Text and an AI write) is
`site/public/plan-text.html`, served at duecrew.com/plan-text.

## The parts

| Part | Where it lives | Who writes it |
|---|---|---|
| The plan: name, line, audience, its doc | D1 `plans` (`worker/src/plans.ts`) | its owner and co-authors (each said yes to an invite, 3.8.1; an owner can hand the plan to one), on duecrew.com (and the author's Anki, below) |
| A follow: my shift, skips, moves, pause, early, own pace, my progress | D1 `plan_follows` | me (Anki or the site) |
| My state for each plan on this computer | `user_files/<profile>/plans.json` | my Anki (`plan_flow.py`) |
| The deck's tag tree, for the builder | D1 `plan_trees` | the author's Anki (`PUT /plans/trees`) |
| A plan's squad (its team) | D1 `plan_team` and friends | its members (`worker/src/team.ts`) |

The plan says what and by when. My follow says when for me and never
changes the plan (`plans.my_doc`: every date `shift` days later, my
skips left out, my moved dates moved). Card text is never stored or sent:
a plan names tags, subdecks, searches, and notes by guid with card
numbers; each follower's Anki reads its own copy.

## The plan doc

Top level: `deck` (the deck's name, matched by name in each follower's
Anki), `units` (the dates), and optionally `exam`, `end`, `phases`
(`catchup`, `taper`), `pace` (the builder's choices and what to cover),
`reviews` (review days), `events` (named days with no cards), `every`
(weekly to-do lines), `tags` and `tagroot` (the plan's own tags), and
since 3.8.1 `deckUrl` (where to get the deck, https) and `remarks`
(`[{id, tag | card, text}]`: the authors' notes for followers on a deck tag
or one card, shown under that topic and on the review screen; at most
300, 280 characters each).

A date (`unit`):

| Field | What | Written by |
|---|---|---|
| `id`, `name`, `opens`, `due`, `even`, `check`, `for` | the date: when it opens, by when, spread evenly to its due date, a checkpoint, the event it preps for | the builder |
| `tags`, `decks` | the deck's tags and subdecks whose cards it opens (a plan tag is `DueCrew::<tagroot>::<part>`) | the builder |
| `cut` | `[{tag, in, q}]`: a deck tag kept to the cards of plan tag `in`; `q` is the same as an Anki search and is one of `search` (3.8.1) | the builder |
| `search`, `sn` | Anki searches, and how many cards each found in the author's copy | the builder; `sn` the author's Anki |
| `cards` | single cards: `[[guid, ord]]` | the builder, the author's Anki (Add to a plan) |
| `notes` | whole notes by guid | the builder |
| `nids`, `cids` | numeric ids pasted from one Anki (they mean nothing in another copy) | the builder |
| `idr` | those ids as `[[guid, ord]]`, from the author's Anki, kept while `nids`/`cids` are unchanged | the author's Anki |
| `ids` | the author's note guids behind the date's tags and subdecks, kept while its tags, subdecks and cuts are unchanged; a follower whose copy names a tag differently still gets the date | the author's Anki |
| `idn`, `pn`, `n` | counts: what pasted ids found; new / repeat / missing in the author's copy; a total | the author's Anki |
| `todo` | up to 8 lines ticked by hand (watch / read / do) | the builder |
| `pl` | what the date's picked cards are: `[[deck tag, n]]` (at most 3), so "Herpes Viruses · 88 picked" | the author's Anki (`#lbl` on the ids upload), kept while the picks are unchanged |

Limits (`worker/src/plans.ts`, top): 200 dates, 200 events, 10 searches
a date (each under 500 characters), 5,000 ids pasted on one date, 50,000
single cards and 50,000 kept ids a plan, 100 plan tags (5,000 notes and
5,000 single cards each), 8 to-dos a date, 6 weekly lines, 60 review
days, a 1.5 MB doc, 10 co-authors, 50 plans an account and 24 MB of plans
in all, 20 follows a person.

A plan's own tags (`tags`): `{id, name, notes?, cards?, tags?, decks?,
search?, n?}`. Each follower's Anki puts each one on its notes as
`DueCrew::<tagroot>::<tag_part(name)>`, one undo step a sync; a date uses
one as any tag, and Due Crew reads it by what it holds (a tag's single
cards exactly, though Anki's tag is on their whole notes).
`tagroot` is fixed with the first tag, unique among plans (case aside).

## A follow

On the server (`plan_follows`): `shift`, `skipped`, `moved` (dates I
moved, and by how much), `pause_until`/`pause_since`, `early` (days
ahead, for a phone), `own` (null: on the plan's dates; "ready": nothing
opens by itself; "next": the next date opens once I've seen most of the
last), `sched` (3.2 schedules), `share` (in the plan's squad),
`progress` (per date: opened, seen, total), `seen_version`.

On this computer (`plans.json`, per profile, never the shared config:
deck ids belong to one collection): `plan_flow.py`'s module docstring
lists every key. The ones that matter most: `deck_id` and `swap` (which
deck runs the plan here, and tag renames), `applied` (each date's
signature when it opened here, or `skip:` + signature), `src` (what each
opened date matched, so an update opens just what it adds), `held`
(every card the plan shut here when asked: Hold back's and Put back's,
which Stop following opens), `hold_yes` (I said yes to Hold back; Put
back never sets it), `later` (dates put off to a later morning),
`own_opened`, `catch` (a catch-up's extra), `missed` (a 3.2 schedule's
missed-days answer), and the plan tags this computer wrote. Per profile,
`trees_sent` (what this computer last sent of each authored deck's tags).

## A day's work, in the builder

The builder reads each date as a span: its cards spread over the study
days from the day it opens to its due date (or to the day before the
next date opens), as the plan's days and phases weigh them (`Work` in
`builder.js`, on `Sched`). A day's bar and the heavy warning are that
daily share, summed over the dates; what opens on a day is the number in
its corner. The warning names the date most to blame, with Split (its
biggest tag) or Give it till (the due date the pace needs). The Text
preview's "Over your pace" reads the same work. A follower's Anki opens
a date whole on its day; the spread is what keeping up takes, not when
cards open.

## The morning

Once per Anki day, on the Decks screen, after AnkiWeb's sync
(`plan_flow.morning`):

1. A plan new on this computer (followed on the site or another
   computer) gets its state; on the plan's dates, dates that passed are
   marked as done there (they came with the sync); at my own pace, a date
   whose cards are all open here counts as opened, and the rest stay Up
   next.
2. Tidy: Due Crew's empty filtered decks go.
3. Plan tags go on (or come off) notes, mine and, for plans I write,
   the author's own (`apply_tags`, `apply_authored_tags`).
4. Hold back (only for someone who said yes, `hold_yes`) shuts what an
   author added to later dates, never a card a date opened here; a
   catch-up sets today's limit; review days build their deck. These run
   before the open, so the open is Anki's latest step and Not today can
   undo it.
5. Open: for each plan, what's due by my dates (`run`), in one undo
   step: a date opens its cards, never a leech, never shuts one again.
   A date whose plan changed since it opened opens just what the change
   adds (`_unit_cids`, the `pt` snapshot for plan tags). At my own pace
   it opens only what an author added to dates I opened, and ("next")
   the next date once I've seen most of the last.
6. A pause that ended asks its question; a plan new here asks Follow's
   Hold back question. 3.8.1, Welcome back: when the open would take in
   dates from 3 or more days with no study at all (not at my own pace, on
   a 3.2 schedule or with even dates), those dates wait in `later` and the
   morning asks: Open them · Push my dates back N days (the follow's
   shift, one PATCH) · Not today (asks again tomorrow).

The line under the board says what opened, by date since 3.8.1 (each
name opens Browse on that date's new cards), with Not today (Anki's undo,
then those dates open tomorrow morning; at my own pace the date stays
opened and only the author's addition waits) while it's still Anki's
latest step. An author's update that arrives later in the day is asked,
not opened (`midday`). A date closed with Edit › Undo offers Open now,
which opens it whole.

## A follower's plan box (3.8.1)

The week marks a date after its event "after X" (reinforcement: no prep
day), says under a date what stayed shut (leeches, picks not in this
copy), and keeps what the plan opens apart from my own reviews due. Every
date with open cards has Study: a Due Crew filtered deck of them, new and
review, due or not, random (`study_date`). From three days before an
event, its line has Study for it: every prep date's open cards in one
deck, the shakiest first (`plans.quiz`, `study_quiz`). The plan's menu
says what Hold back keeps, with Open them (one undo step; Hold back stays
on) and Stop holding back. At my own pace, any date after Then opens at
once, with Undo. All of it is read here; nothing is sent.

## What the author's Anki sends

On the day's first refresh, for each plan I write or co-author whose
deck I have (by its name): the note ids behind each date (`PUT
/plans/{id}/ids`: `ids`, `idr`, counts, and since 3.8.1 `#lbl`, the deck
tags a date's picked cards sit under), only when they changed; the
deck's tag tree, only when it changed (`send_trees`, `PUT /plans/trees`;
the builder says "Tags as of" its date); and the plan's own tags go on
my notes. Make a plan from a deck sends the tree at once. A tag change
made later in the day reaches the builder the next day.

## Older add-ons and newer fields

Each add-on cleans a plan on arrival (`backend/shapes.clean_plan_doc`)
and drops fields it doesn't know, so a newer field must leave the plan
usable without it:

- 3.8.1 `deckUrl`, `remarks` and a date's `pl`: an older add-on shows
  none of them; the plan works the same. A co-author invited but not yet
  answered is no co-author to any add-on. An older add-on never sends
  `same=1`, so its morning brings every doc as before.
- 3.8.1 cuts keep their search in `search`: an older add-on opens the
  same cards by the search.
- 3.8.1 single cards in a plan tag: an older add-on leaves them out, and
  doesn't see a tag made only of single cards.
- 3.8.1 `hold_yes`: a 3.8.0 state with held cards counts as a yes on the
  plan's dates and a no at my own pace (Put back put cards there too),
  settled once.
- 3.8.0 plan tags: before 3.8.0 a date using one finds nothing until the
  author's ids (`ids`) are there; then it falls back to them.

`MIN_CLIENT` in `worker/wrangler.toml` stops a client too old to work at
all; raising it is a decision, not a habit.

## Requests

A refresh is one request and a sync is one. Plans ride them: the day's
first refresh (`decks=1`) brings my plans, plans I write, squad offers
and the stamp (`pv`) that moves when one changes; the sync sends my
progress. Since 3.8.1 that first refresh asks with `same=1`: when the
stamp hasn't moved, each plan comes without its doc and the add-on keeps
the one it has (`api._with_kept_docs`); a doc it doesn't have lets the
stamp go, so the next refresh brings them all. Everything else is one request on a click (follow, save, a
post, a choice), or the author's uploads above, only when something
changed. `test_request_budget` pins this.

## Where the code is

| | Add-on | Worker | Site |
|---|---|---|---|
| The doc, its shape | `backend/shapes.py` | `plans.ts` `planDoc` | `builder.js` |
| Matching cards | `plans.DeckIndex` | | counts from the author's Anki |
| The morning, updates, own pace | `plan_flow.py` (glue), `plans.py` (pure) | `plans.ts` follow | `paceBox` in builder.js |
| A date's window, quota, behind | `schedule.py` | | `Sched` in app.js (twin) |
| Plan tags, cuts | `plans.sync_tags`, `plans.match` | `plans.ts` `tagNotes`, `reroot` | `setCut`, `syncCuts`, the Text tab |
| Tests | `tests/test_due_crew.py`, `tools/real_anki.py` | `worker/test/plans*.test.ts`, `plantags.test.ts` | the suite's source checks |
