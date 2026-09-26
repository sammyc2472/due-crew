# Due Crew API (3.0)

One Cloudflare Worker with D1 underneath, served at `https://api.duecrew.com`.
Every consent rule that `firestore.rules` holds today lives in this code.
JSON in and out. Errors are `{error: "<code>"}` with a status, and 429s also
carry `retryAfter` (seconds) and a `retry-after` header.

```
npm ci
npx vitest run      # real workerd, local D1, migrations applied per test
npx tsc --noEmit
npx wrangler dev    # local; no RESEND_API_KEY, so codes are logged, not sent
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
| `GET /auth/me` | `{uid, email, name, emoji}`. |
| `POST /auth/signout`, `POST /auth/signout-all` | This session; every session of mine. |
| `DELETE /account` | Everything of mine, in one transaction. A squad I founded passes to its longest-standing member, or goes if I was the last one in it. |
| `POST /admin/import-users {users: [{uid, email, name?}]}` | The one-shot `firebase auth:export` import (`ADMIN_TOKEN`). Idempotent by uid; `{imported, skipped}`. |

**Sign-in details**
- Codes and tokens are stored as SHA-256 hashes; tokens are 32 random bytes, base64url.
- A code works once, and dies after 5 wrong tries.
- **Limits**, per hour:
  - 5 codes per address and 20 per IP;
  - 60 verifies per IP;
  - the sixth wrong code locks the address for the hour.
- **Sessions:** `last_used` is written at most daily, and a session idle for 180 days ends.
- Emails, codes and tokens are never logged.

### A refresh and a sync

| | |
|---|---|
| `GET /board[?decks=1]` | `{me: {uid, name, emoji, code, week, updatedAt}, friends: [...], cheers: [...], knocks: [...], decks?}`. One request is a whole refresh. A friend who added me back comes with `week` and `updatedAt`; one who hasn't is `{uid, name, emoji, mutual: false}`. Cheers come from mutual friends only, and each is deleted as it's read. |
| `POST /sync` | `{profile?, week?, decks?, heatmap?, squads?: {row, ids}, settings?}` → `{ok, gone, wrote}`. Every part is validated before anything is written, and a part the server already holds verbatim isn't written again. `heatmap: null` takes the heatmap down. Squad rows are UPDATEs only; `gone` lists the squads I'm no longer in. |
| `GET /decks` | Shared-deck progress: mine and my mutual friends'. |
| `GET /heatmap/{uid}` | Mine or a mutual friend's; `{counts: null}` when they don't share one. |
| `GET` / `PUT /settings` | `{v, at, settings}`, mine only. |

**The week doc** is 2.9's `shared/week`:
- `{v, days: {label: {studied, reviews, studyTimeMs, accuracy, streak, newCards, status}}, paused, examDate, awayFrom, awayTo, liveUntil, tricky, room}`.
- At most 9 days.
- A flagged card (`tricky`) is `{guid, deck, at}`. Any `text` is dropped on the way in; crewmates read the text from their own copy of the note.

### People

| | |
|---|---|
| `GET /users/{uid}` | `{uid, name, emoji}`, and nothing more, for anyone signed in. |
| `PUT /friends/{uid}` | Add someone (an add-back, a knock's Add). Clears their knock. `{uid, name, emoji, mutual}`. |
| `DELETE /friends/{uid}` | Their reads of my numbers end with this request. |
| `PUT /friends {ids}` | 3.0's first sync re-adds the crew by uid. Add-only; unknown uids are skipped. |
| `POST /codes [{code}]` | A new friend code; the old one stops working. `code` asks for a particular one (the one I already handed out), if it's free. |
| `POST /codes/{code}/add` | Add the code's owner, and knock them unless they already added me. 30 tries an hour. |
| `POST /cheers/{to} {emoji, note?, luck?, guid?}` | Only to someone who added me. One per sender; it overwrites the last. |
| `GET /knocks`, `DELETE /knocks/{from}` | Mine. Names come from profiles, never the knock. |
| `POST /knocks/{to} {squad}` | Only between two members of that squad. |

### Squads

| | |
|---|---|
| `POST /squads {name}` | `{id, code, name, founder, open}`; I'm the founder and a member. |
| `GET /squads/peek?code=` | The join preview. 60 an hour. |
| `POST /squads/{id}/join` | The only way in: the door must be open and I mustn't be blocked. |
| `POST /squads/restore {code, name, founder}` | 3.0's first sync: recreates a 2.x squad with the founder its members remember, or joins it if it's back already. Block lists don't come back. |
| `GET /squads/{id}` | Members only: `{id, name, founder, open, banned, rows}`. `banned` is the founder's to see. |
| `PUT /squads/{id}/row` | My numbers, as an update. Never a join. |
| `DELETE /squads/{id}/members/{uid}` | Leave, or (founder) remove. |
| `POST /squads/{id}/block/{uid}` | Founder: out, and can't rejoin. |
| `PATCH /squads/{id} {open?, founder?}` | Founder. A squad passes only to a member. |

Squad ids are 2.x's (`sha1("due-crew-squad:" + code)[:24]`), so squads in a 2.x config keep their ids.

## Tests

- `test/consent.test.ts` restates every check of `tests/rules/emulator_rules_test.py` (the 2.x Firestore rules) against the Worker, in its order and under its label.
- `test/auth.test.ts` and `test/account.test.ts` cover sign-in, sessions, limits, deletion and the import.
- `test/board.test.ts` covers the board, sync, codes and squads.

## Schema

See `migrations/0001_init.sql`. It has the tables from the 3.0 brief, with
three changes:
- **No extra indexes where a key already covers the lookup.** `users.email` has a UNIQUE constraint, and `members(squad)`, `cheers(to_uid)` and `knocks(to_uid)` lead their primary keys, so they need no index of their own. Each extra index costs a write per row.
- **Added:** `sessions(uid)`, for sign-out-everywhere and deletion.
- **Added:** `codes(uid)`, for deletion.
