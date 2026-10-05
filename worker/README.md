# Due Crew API (3.0)

One Cloudflare Worker with D1 underneath, served at `https://api.duecrew.com`.
Every consent rule that `firestore.rules` holds today lives in this code.
JSON in and out. Errors are `{error: "<code>"}` with a status, and 429s also
carry `retryAfter` (seconds) and a `retry-after` header.

```
npm ci
npx vitest run      # real workerd, local D1, migrations applied per test
npx tsc --noEmit
npx wrangler dev    # local; with DEV_MAIL_LOG=1 in .dev.vars and no mail, codes are logged, not sent
```

## Endpoints

Everything but `/version`, `/auth/code`, `/auth/verify` and the admin
import takes `Authorization: Bearer <token>`.

### Sign-in and account

| | |
|---|---|
| `GET /version` | `{api, minClient}`, no auth. Replaces the rules-marker probe. |
| `POST /auth/code {email}` | Sends a code: six digits, ten minutes, plain text, no links. The answer is the same whether or not the address has an account. |
| `POST /auth/verify {email, code, device}` | `{token, uid, new, name}`. An unknown address becomes a new account (ULID uid); `new` says to ask for a name. |
| `GET /auth/me` | `{uid, email, name, emoji, accent}` (3.5.0: the accent from my settings, else green; the site wears it). |
| `POST /auth/signout`, `POST /auth/signout-all` | This session; every session of mine. |
| `POST /links/email {email, path}` | The site's "Email it" on a phone: one fixed message with `https://duecrew.com{path}`, where `path` is `/`, `/p/CODE` or `/i/CODE`. Only with `x-due-crew`; 5 an hour an address, 3 a day to one inbox. |
| `GET /account/data` | 3.7.1, D2: everything kept about me as one JSON file (profile, settings, week, decks, heatmap, log, cheers counted, crew by name, squad rows, plans made and followed, notes, tips, cards I have down, feedback, sign-ins; never a token or anyone else's email). 10 a day. |
| `DELETE /account/todos` | 3.7.1, D2: my Due to-dos and ticks, under a fresh save time; each add-on takes it at its next refresh (`settingsAt`). |
| `DELETE /log` | 3.7.1, D2: my log and my cheers counted. Days older than 8 days before the delete are never taken again (`cut`, first in the log's JSON), and every sync reply says `logCut` so the add-on's history import stops. |
| `DELETE /account` | Everything of mine, in one transaction. A squad I founded passes to its longest-standing member, or goes if I was the last one in it. |
| `POST /admin/import-users {users: [{uid, email, name?, code?}]}` | The one-shot `firebase auth:export` import (`ADMIN_TOKEN`), with each profile's name and friend code when `tools/import_users.py --firestore` read them. Idempotent by uid; `{imported, skipped}`. |

**Sign-in details**
- Codes and tokens are stored as SHA-256 hashes; tokens are 32 random bytes, base64url.
- A code works once, and dies after 5 wrong tries.
- **Limits.** An address from one IP comes first, so someone who knows my
  address can't use up my codes or lock me out from where they are:
  - codes: 5 an hour and 8 a day to an address from one IP; 10 an hour and
    20 a day to an address from anywhere; 20 an hour from one IP;
  - 60 verifies an hour per IP;
  - the sixth wrong code in an hour locks the address from that IP; 20 wrong
    in a day, from anywhere, lock it for the day.
- **Other sites:** a request that changes anything (a POST, PUT, PATCH or
  DELETE, sign-in included) is refused (`403 csrf`) when its `Origin` is a
  page that isn't duecrew.com's. The add-on sends no `Origin`.
- **Sessions:** `last_used` is written at most daily, and a session idle for 180 days ends.
- Emails, codes and tokens are never logged.

### A refresh and a sync

| | |
|---|---|
| `GET /board[?decks=1][&keep=1]` | `{me: {uid, name, emoji, code, week, updatedAt}, friends: [...], cheers: [...], knocks: [...], decks?, settingsAt}`. `settingsAt` (3.7.1) is when my settings were last saved: an add-on pulls a save it hasn't seen. One request is a whole refresh. A friend who added me back comes with `week` and `updatedAt`; one who hasn't is `{uid, name, emoji, mutual: false}`. Cheers come from mutual friends only, and each is deleted as it's read, except with `keep=1` (3.2, the site's home: it shows them and leaves them for Anki). |
| `POST /sync` | `{profile?, week?, decks?, heatmap?, squads?: {row, ids}, settings?, plans?, knows?, stuck?, log?}` → `{ok, gone, wrote, cards?}`. Every part is validated before anything is written, and a part the server already holds verbatim isn't written again. `heatmap: null` takes the heatmap down. Squad rows are UPDATEs only; `gone` lists the squads I'm no longer in. 3.2: `knows: {reset?, add, del}` (note guids I have down, in decks I share; at most 2,000 of each, 100,000 kept a person), `stuck: [guid]` (at most 300; answered in `cards: {guid: {knows: [uid], tips: [{from, text, at, helped}]}}`, mutual friends only, and nothing about the question is kept), `log: {days: {date: [minutes, reviews, new, retention]}}` (merged, 15 years kept since 3.7.1, mine only; the reply's `logAll` lets the add-on's history import move on). |
| `POST /tips/helped {guid, from, helped?}` | 3.2: "This helped" on a mutual friend's tip. It orders tips (the most helpful first); nobody sees a count. |
| `GET /log` | 3.2: my log, for the site, and since 3.7.1 `cheers: {year: n}` (cheers my crew sent me, a sender once a day, tips not counted). Mine only. |
| `GET` / `POST /admin/notices {text, link?, below?, days?}`, `DELETE /admin/notices/{id}` | 3.2.1: the admin's notice (at most 200 characters, an https link, only to add-ons older than `below`, 14 days unless said). `GET /board` carries the newest live one for the asking add-on's version as `notice: {id, text, link}`. |
| `GET /admin/stats` | 3.2: counts only (accounts, on 3.x, seen, friendships, squads, plans, tips, versions), for the admin (`ADMINS` in wrangler.toml, and the `ADMIN_UIDS` secret); 404 for everyone else. `GET /auth/me` says `admin: true` for them. |
| `GET /admin/people?q=` | The admin's account lookup: an exact email, uid or friend code, or up to 10 whose name starts with `q` (3+ characters), emails partly hidden; a squad's code gives `squad`. `GET /admin/people/{uid}`: one account (name, emoji, email, code, joined, last seen, version, tz, how many places signed in, squads with ids, plans made and followed, counts of crew, added-not-back and muted, the per-address sign-in limits, a pending email change, the admin's note and what the admin did there). Never their week, days, heatmap, decks, log, plan progress, settings, or who their crew are. `POST /admin/people/{uid}/signout` ends their sessions; `DELETE /admin/people/{uid} {email}` deletes the account as their own Delete does, with their email typed as confirmation (never the admin's own). 404 for everyone else. |
| `POST /admin/people/{uid}/code` | Sign-in help: a fresh code to their address past the limits, for someone at the code box; the admin never sees it. `POST /admin/people/{uid}/limits` clears the per-address code and wrong-code counts and any half-used code. `PUT /admin/people/{uid}/email {email}` starts moving the account (both addresses told); it moves at the first code sign-in at the new address within 7 days (`email_changes`), `DELETE` stops it. `PUT /admin/people/{uid}/note {text}` is the admin's own note (2,000 characters; empty takes it off). |
| `GET /auth/places` | Where I'm signed in, as counts: `{computers, browsers}` (S6, the site's Account). |
| `GET /auth/gone?uid=` | Signed out ("The next round", Q4): was this account deleted for being quiet? `{gone, after}`; the server keeps only a hash of such uids, a year. The daily job (`quiet.ts`) trims after 6 months without activity (shared decks, heatmap, plan trees, cards known: what a sync rebuilds) and deletes after 12 (24 when paused), 50 a day; a plan someone follows passes to its first co-author or stays ownerless ("a former member"). `GET /admin/stats` carries `housekeeping {folded, quiet, dueSoon}`. |
| `GET /admin/people/{uid}/crew` | An account's crew ("The next round", F1): everyone on either side of a friendship with them, by name and emoji, with when each side added the other (`mine`, `theirs`). Never how anyone studies. Each look goes in the audit log. `DELETE /admin/people/{uid}/crew/{other}?side=mine\|theirs` takes away one side on their request (F3): `mine` is what their own Remove does, `theirs` takes them off the other person's list. Never adds anyone; they get one email. |
| `GET /admin/actions[?before=id]` | The audit log (A5): everything done from the admin's page, 100 a page, names looked up as it's read; kept a year. Never an email, a code or a token. |
| `GET /admin/squads/{id}` | One squad (A4): name, founder, open, made, members by name and emoji (never their numbers), how many removed, and what the admin did there. `PATCH {open?, name?, founder?}` as its founder would (a founder must already be in it); `POST .../code` a new code, in the answer once and the founder's email, the old one opening nothing (`squad_codes`, the id unchanged); `POST .../remove/{uid} {why?}` removes and blocks (never the founder); `DELETE {name}` the squad, its name typed out. The founder is emailed for each. |
| `GET /decks` | Shared-deck progress: mine and my mutual friends'. |
| `GET /heatmap/{uid}` | Mine or a mutual friend's; `{counts: null}` when they don't share one. |
| `GET` / `PUT /settings` | `{v, at, settings}`, mine only, up to 64 KB (Due's own to-dos ride it). |

**The week doc** is 2.9's `shared/week`:
- `{v, days: {label: {studied, reviews, studyTimeMs, accuracy, streak, newCards, status}}, paused, examDate, awayFrom, awayTo, liveUntil, tricky, room}`.
- At most 9 days.
- A flagged card (`tricky`) is `{guid, deck, at}`. Any `text` is dropped on the way in; crewmates read the text from their own copy of the note.
- A flag with a tip still waiting for me is dropped on the way in, so a sync before I've read the tip doesn't put it back up.
- 3.2: a flag may carry `q`, my one line asking whoever has the card down (an ask). `recap: {name, n, day}` is my last plan week done. Neither goes to Firestore.

### People

| | |
|---|---|
| `GET /users/{uid}` | `{uid, name, emoji}`, and nothing more, and since 3.7.1 (D5) only to someone connected: a crew edge or a knock either way, or a squad or a plan in common. Anyone else gets `404 no_user`, as for no such account. |
| `PUT /friends/{uid}` | Add someone (an add-back, a knock's Add). Clears their knock. `{uid, name, emoji, mutual}`. |
| `DELETE /friends/{uid}` | Their reads of my numbers end with this request. |
| `PUT /friends {ids}` | 3.0's first sync re-adds the crew by uid. Add-only; unknown uids are skipped. |
| `POST /codes [{code}]` | A new friend code; the old one stops working. `code` asks for a particular one (the one I already handed out), if it's free. |
| `GET /codes/{code}` | Whose code it is, before adding: `{uid, name, emoji, mine, added}`. Adds nobody; shares the add's 30 an hour. |
| `POST /invites` | 3.5.0: a one-time invite, `{code, expiresAt}`: 10 characters, returned once and kept as a hash; 14 days; 20 a day. A new friend code ends all of mine. |
| `GET /invites/{code}` | Signed out (the `/i/CODE` page): `{kind, name, emoji, state}` for an invite (`ok`, `used`, `expired`) or a friend code (`kind: "code"`). 300 an hour an address. |
| `POST /invites/{code}/redeem` | The first use within 14 days: I'm crew with its maker at once, both edges, knocks between us cleared. After that (used, or old) it works as their friend code: I add them and they're knocked (`{mutual, knocked}`). 400 `own_code`. The same person again writes nothing. Shares the add's 30 an hour; rows are kept a year. |
| `POST /codes/{code}/add` | Add the code's owner, and knock them unless they already added me. 30 tries an hour. |
| `POST /cheers/{to} {emoji, note?, luck?, guid?}` | Only to someone who added me. One per sender; it overwrites the last. A cheer with a `guid` (a tip) from a mutual friend takes that flag off the recipient's week, for the whole crew (3.0.1). 3.2: a tip with words is also kept on its card (`tips`), one per author per card (5,000 a person), for mutual friends stuck on it. |
| `GET /knocks`, `DELETE /knocks/{from}` | Mine. Names come from profiles, never the knock. |
| `POST /knocks/{to} {squad}` | Only between two members of that squad. |
| `POST /reports {uid, reason, note?}` | `reason` is `cheers`, `name` or `other`; `note` at most 500. Stores nothing: mails `REPORT_TO` the reporter's and the reported uid, the reported name and emoji, the reason, the note, and their cheer to me if one is still unread. Never the reporter's email. Without `REPORT_TO` it logs "report received" and nothing else. 10 an hour. Muting is the client's (a `muted` list in settings); nobody is told. |
| `POST /feedback {text, ver?}` | 3.6.5, P6: feedback for the admin's page. `text` 1–2,000 characters, `ver` one line of at most 120 (the add-on's and Anki's versions, or the site page it came from). 5 a day a person (429 `too_many`). Kept a year (housekeeping) and deleted with the account. `GET /admin/feedback?state=new\|done\|all` (newest first, 100, with each sender's name and emoji, never an email, and `open`, the count not done), `PATCH /admin/feedback/{id} {done}`, `DELETE /admin/feedback/{id}`, `POST /admin/feedback/{id}/reply {text}` (mailed from Due Crew to the sender with what they wrote quoted; marks it replied and done). 404 for everyone else. |

### Plans (3.1)

See `docs/plans-design.md` for the endpoints (`/plans/*`, `/auth/link`), the
doc shape and the rules. `GET /board?decks=1` adds `plans` (the plans I
follow) and `planOffers` (plans offered to my squads); `POST /sync` takes
`plans: {id: {unitId: [opened, seen, total]}}`. 3.2: a plan's doc may have
`end`, `phases: {catchup, taper}` and a date's `check` (a checkpoint); a
follow may carry my `sched: {start?, days, minutes}`, and my own view of a
plan I follow carries my schedule and my progress. 3.3: a date may be
`even` (split evenly from its opens to its due date, which must be later),
and the doc may carry the builder's `pace: {mode: "end" | "daily" |
"placed", days: [7 of 0/1], daily?, cover?: ["tag:…" | "deck:…"]}`.
3.3 together: `role` and `editors` on a plan's view; `PUT /plans/{id}` for
the owner and co-authors (with an optional `summary` for the history);
`POST /plans/{id}/editors {uid}` and `DELETE /plans/{id}/editors/{uid}`;
`GET/POST /plans/{id}/notes` and `DELETE /plans/{id}/notes/{nid}` (on a
plan in the library only its authors post, `403 authors_only`, and the
list and the home feed show only theirs, plus my own from before);
`GET /plans/{id}/log` and `POST /plans/{id}/undo {version}` (the latest
save only). `PUT /plans/trees` takes `{v: 2}` nested trees up to 1.5 MB;
`GET /plans/trees?deck=` returns that deck's.

3.7.3 plan updates: `GET /board?pv=STAMP` (an add-on sends the stamp it last
saw on every refresh) answers `pv` (a short hash of the plans I follow:
their versions, my follow's own days, their newest post; never my
progress) and carries `plans`, `planOffers` and `authored` again only when
it moved, so a save reaches followers at their next refresh with no
request of its own. Each plan on the board has `posts` (its newest 3:
`{id, name, text, withSave, at}`), and the board marks the version as
reached (`plan_follows.seen_version`, written only when it changed).
`GET /plans/{id}/posts` (anyone in the plan), `POST /plans/{id}/posts
{text}` and `DELETE /plans/{id}/posts/{pid}` (authors; the owner removes
any): one line, 200 characters, 5 a day per plan (`429 too_many_posts`),
the newest 50 kept. `PUT /plans/{id}` takes `post` too: it rides the save
(`posted: {id, text}`, or `{error: "too_many_posts"}` while the save still
stands). An author's view has `reached: [n, of]`, the followers (not the
owner) whose Anki has this version. The home feed (`feed=1`) lists posts
as `kind: "post"`.
3.7.3 a plan's team (`team.ts`, migration 0020), opt-in, for anyone in the
plan (its authors and followers): `POST /plans/{id}/team` joins, `DELETE`
leaves, `GET /plans/{id}/team[?wk=]` is the tab: `{on, count, shown,
streak, faces: [{uid, name, emoji, shown}] (24, then more), asks, bingo?}`,
or `{on: false, count}` off the team. Showed up: a member answered one of
the plan's cards on their own Anki day; it rides the sync as `team:
{planId: {days, play?}}` (the last 8 days with one, so a phone's arrive late; rows I hold only, written when changed; `play`
is my squares from the plan's cards only). The streak is days in a row
when more than half the team showed up. `asks`: the newest 30 threads by
activity, `{id, uid, name, emoji, text, at, act, topic, guid?, ord?, mine,
remove, author, replies: [...]}`. `POST /plans/{id}/asks
{text, parent? | guid, ord, topic?}` (team only; 280 characters; 10 new
questions a person a plan a day, `429 too_many_asks`; 50 replies a
thread; a plan keeps its newest 200), `DELETE /plans/{id}/asks/{aid}` (its
writer or an author; a question takes its replies), `POST
.../asks/{aid}/helped {on}` (the asker, on a reply). Muted people's words are left out. The bingo is the week's
squares (`cardFor`) with the team's own middle (asks, answers, 3 days),
counts only. `GET /board` carries `teams: {planId: {shown, of, streak,
faces, act, last?}}` for an add-on (not `keep=1`), and the week's card
for a team member as for a squad member.
C1–C5: `PATCH /plans/{id}/follow {early}` (0–7); a date's `search`
(up to 10) and `sn` (their counts), `ids` (note ids, 50,000 a plan);
`reviews: [{day, from, to}]` on the doc; 50,000 single cards and 1.5 MB
docs; `POST /plans/{id}/cards {search, n}`; `PUT /plans/{id}/ids
{units: {unitId: [tags, decks, [guid]]}}` (kept only while the date's
tags are unchanged); `GET /board?decks=1` adds `authored` (the plans I
write, lean) and each plan's `early`.
3.4: `PUT /plans/{id}/ids` also takes `counts: {unitId: {search: n}}`;
the lean `authored` docs carry each date's searches. `GET
/plans/ics?code=` (no sign-in) is the plan as iCalendar; the site serves
it at `/p/CODE.ics` (1,000 an hour an address). `POST /plans/follow`
shares peek's 60 an hour. `GET /plans/mine` leaves each doc's single
cards and note ids out; `GET /plans/{id}/progress` is for co-authors too.
The UI review: `GET /plans/public?code=` (no sign-in, code plans only) is
what a plan's link shows before signing in: `{name, ownerName, line,
deck, followers, units: [{name, opens, due?, n}]}`, days and counts, never
what's in them (300 an hour an address).
E1: a date may carry `nids` and `cids` (positive whole numbers, up to 5,000
each), counted into the plan's 50,000 single cards; `PUT /plans/{id}/ids`
takes `counts: {unitId: {"#ids": n}}`, kept as the date's `idn`, and the
lean `authored` docs carry them.
3.6.5: a date may carry `notes` (note guids, up to 5,000, every card of
each; they count into the 50,000 and `#ids`). `PUT /plans/{id}/ids` also
takes `refs: {unitId: [nids, cids, [[guid, ord]]]}`: the cards a date's
pasted ids are in the author's copy, kept as the date's `idr` (20,000 a
date, 50,000 a plan) only while its `nids` and `cids` are still the ones
sent. A site save never sets `idr`: it keeps the stored one while the ids
are unchanged and drops it when they change. P1: `counts` may carry
`{"#pn": [new, repeat, missing]}` per date (what it opens in the author's
copy, in date order); kept as `pn` the same way as `idr`, while the date's
`opens`, tags, subdecks, searches, ids and notes are unchanged. The lean
`authored` docs carry each date's `opens` for it.
Due: a date may carry `todo: [{k, t, url?}]` (up to 8): `k` watch, read
or do, `t` up to 140 characters, `url` an https link. Followers tick them
by hand in the add-on; the ticks are theirs (`due_ticks` in their settings).
F1: the doc may carry `events: [{id, day, name}]` (up to 200) and a date
`for` (an event's id; one naming no event is dropped). The calendar feed
has each event as its own day, with how many dates prep for it.
G3, G4 (migration 0007): `PATCH /plans/{id}/follow` also takes `shift`
(0-365 days my dates run later), `until` and `since` (a pause's last and
first day, or null) and `skipped` (unit ids, up to 200). They're mine
only, on the board's plans and on the plan's `following`.
3.5, A: `GET /plans/public` also carries `v` (the plan's version, which
keys its preview picture) and `events: [{day, name}]`.
3.5, B, the library (migration 0008): `PUT /plans/{id}/listed {listed}`
(the owner; a plan anyone with the code can follow, with dates; up to 20
listed a person); `GET /library?deck=&len=short|mid|long&q=&page=` (24 a
page, newest first, a search puts name matches first; never by
followers), each with its card (`deck, dates, from, to, days, n, perDay,
reviews, events, ids`, kept on the plan as `lib` at every save while
listed), `code`, `ownerName`, `followers`, `mine`, and `decks: [[deck,
n]]`. A listed plan reads like one shared by code (`GET /plans/{id}`
without it); a plan's view says `library` and, for its authors, `listed`
(1, 0, or -1 when the admin took it out, with `listedNote`), and a copy's
`basedOn: {id, name, owner}`. `POST /plans/{id}/copy {start}`: a plan of
my own from a listed one (or one I write), its first date on `start`,
without followers, notes or co-authors. `POST /plans/{id}/report {reason:
spam|copied|other, note?}` mails REPORT_TO and stores nothing. The admin:
`POST /admin/library/{id} {note}` takes one out, `DELETE` puts it back,
`GET /admin/library` lists those taken out.
3.5, H/L/X (migration 0009): `GET /board?keep=1&feed=1` (the site's home
only) adds `feed`: who added me back, notes on days of plans I'm in, and
others' saves to those plans (`summary`), the last 14 days, 20 at most,
none from someone I muted. My follow carries `hist` (`{date: [opened,
seen]}`, 120 days, kept with each progress write) on `following`.
`/admin/stats` adds `cutover {on3, active2, quiet}`, `codes {sent, ok,
wrong, out, limited}` (the last 7 days), `bridge` (its last run and
today's runs) and the library's `listed`/`takenOut`; `GET
/admin/trends?days=30|90|365` is each kept count by day (the daily cron
keeps them in `admin_days`; accounts come from `created_at`). `GET
/admin/notices?all=1` is the last 20 with their `state`; taking one down
keeps its row.

### Squads

| | |
|---|---|
| `POST /squads {name}` | `{id, code, name, founder, open}`; I'm the founder and a member. |
| `GET /squads/peek?code=` | The join preview, with `founderName` since 3.7.1. 60 an hour. |
| `POST /squads/{id}/join {code}` | The only way in: the squad's code (since 3.6.2 always; an id alone is not a join), the door open, I mustn't be blocked, and it holds at most 500. |
| `POST /squads/restore {code, name, founder}` | 3.0's first sync: recreates a 2.x squad with the founder its members remember, or joins it if it's back already. Block lists don't come back. 30 a day. |
| `GET /squads/{id}[?wk=2026-W40]` | Members only: `{id, name, founder, open, banned, rows}`. `banned` is the founder's to see. 3.6: each row has `joined` (a date) and `play`; with `wk`, `bingo` is that week's card. |
| `PUT /squads/{id}/row` | My numbers, as an update. Never a join. |
| `DELETE /squads/{id}/members/{uid}` | Leave, or (founder) remove. |
| `POST /squads/{id}/block/{uid}` | Founder: out, and can't rejoin. |
| `PATCH /squads/{id} {open?, founder?}` | Founder. A squad passes only to a member. |

Squad ids are 2.x's (`sha1("due-crew-squad:" + code)[:24]`), so squads in a 2.x config keep their ids.

3.6, squad bingo (migration 0011, `src/bingo.ts`): every squad plays the
same 3×3 card each week. The server draws it the first time anyone asks
(`draw`: one square from each of eight families, 3 easy, 3 medium, 2 hard,
four of them team squares; a middle that's a season's, free every sixth
week, else study and crew weeks in turn) and keeps it in `bingo_cards`, so
an edit to the pool shows from the next week. `GET /board?decks=1&wk=` and
`GET /squads/{id}?wk=` (last week, this or next only) bring it to anyone in
a squad. A squad row's `play` is the member's own week as short ids and
whole numbers (which squares they passed as bits of `s`, days studied,
cheers sent, and so on); the Worker checks only its shape, and boards add
the rows up (`evaluate`, restated in `due_crew/bingo.py`). The daily cron
keeps counts per square in `bingo_cards.stats`. `GET /admin/bingo` is the
pool (off entries too) and the last few cards with their counts; `PUT
/admin/bingo/{id} {kind, entry, enabled}` adds or changes an entry, checked
against the rule types the add-on knows.

3.6.1 (migration 0012): a team square's `need` and a middle's `goal` can be
a share (`half`, `third`, `quarter`: at least 2, never more than there are
of you), so a bigger squad needs more of you. The draw makes every square
a team square except one hard one: easy ones half, medium a third, the
other hard one a quarter. A rule's `row: true` wants its days in a row;
a medium or hard square is a streak whenever its family has one at that
level (`isStreak`; migration 0013 gives every family one, and turns off
the "ask about a card" middle and the beat-the-day-before streak, which
paid for a small first day: `rel` takes `days`/`row` instead, against my
usual day). A share is of everyone studying this
week: members whose add-on plays (`active`) and those on an older add-on
(`older`, who can't stamp; the card says so). `GET
/board?decks=1` also returns `squads` (the squads I'm a member of), so an
add-on whose config lost them puts them back.

## Tests

- `test/consent.test.ts` restates every check of `tests/rules/emulator_rules_test.py` (the 2.x Firestore rules) against the Worker, in its order and under its label.
- `test/auth.test.ts` and `test/account.test.ts` cover sign-in, sessions, limits, deletion and the import.
- `test/board.test.ts` covers the board, sync, codes and squads.
- `test/bingo.test.ts` covers squad bingo: weeks, the draw, the kept card, play on rows, a squad's card from its rows, the admin's pool and the daily counts.

## Schema

See `migrations/0001_init.sql`. It has the tables from the 3.0 brief, with
three changes:
- **No extra indexes where a key already covers the lookup.** `users.email` has a UNIQUE constraint, and `members(squad)`, `cheers(to_uid)` and `knocks(to_uid)` lead their primary keys, so they need no index of their own. Each extra index costs a write per row.
- **Added:** `sessions(uid)`, for sign-out-everywhere and deletion.
- **Added:** `codes(uid)`, for deletion.
