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

## Built (step 1)

| | |
|---|---|
| `GET /version` | `{api, minClient}`, no auth. Replaces the rules-marker probe. |
| `POST /auth/code {email}` | Sends a code: six digits, ten minutes, plain text, no links. The answer is the same whether or not the address has an account. |
| `POST /auth/verify {email, code, device}` | `{token, uid, new, name}`. An unknown address becomes a new account (ULID uid); `new` says to ask for a name. |
| `GET /auth/me` | `{uid, email, name, emoji}` for this session. |
| `POST /auth/signout` | Ends this session. |
| `POST /auth/signout-all` | Ends every session of mine. |
| `DELETE /account` | Removes everything of mine, sessions included, in one transaction. A squad I founded passes to its longest-standing member, or goes if I was the last one in it. |
| `POST /admin/import-users {users: [{uid, email, name?}]}` | The one-shot `firebase auth:export` import. Needs the `ADMIN_TOKEN` secret. Idempotent by uid; returns `{imported, skipped}`. |

**Sign-in details**
- Emails are trimmed and lower-cased before any comparison.
- Codes are stored as a SHA-256 hash; tokens as a SHA-256 of 32 random bytes (base64url), with a device label.
- A code works once. It dies after 5 wrong tries.
- **Limits**, per hour:
  - 5 codes per address and 20 per IP;
  - 60 verifies per IP;
  - the sixth wrong code in an hour locks the address (no sign-in, no new code) until the hour is up.
- **Sessions:** one indexed read per request. `last_used` is written at most once a day, and a session idle for 180 days ends.
- Emails, codes and tokens are never logged. With no Resend key, the log shows the code but not the address.

## Next (step 2): proposed shapes

- **`GET /board?labels=…&light=1`** — one request per refresh. It returns:
  - `me`: profile and code;
  - `friends`: mutual and pending, each with `name`, `emoji` and `mutual`, and for mutual friends `week` (the week doc) plus `decks` and `heatmap` when not `light`;
  - `cheers`, deleted server-side once read;
  - `knocks`.
- **`POST /sync`** — one body: `{profile, week, decks?, heatmap?, squads: {rows, ids}, settings?}`. Each part is hash-guarded server-side, so an unchanged part doesn't write.
- **Cheers, friends and codes:**
  - `POST /cheers/{to}`;
  - `PUT` / `DELETE /friends/{uid}`;
  - `POST /codes` (new code);
  - `POST /codes/{code}/add` (adds and knocks the owner).
- **Squads:**
  - `POST /squads` (create);
  - `GET /squads/{id}/peek`;
  - `POST /squads/{id}/join` (the only way in);
  - `PUT /squads/{id}/row` (never creates membership);
  - `DELETE /squads/{id}/members/{uid}` (leave or remove);
  - `POST /squads/{id}/ban/{uid}`;
  - `PATCH /squads/{id}` `{open?, founder?}`;
  - `GET /squads/{id}` (members, one query).
- **Settings:** `GET` / `PUT /settings` `{v, at, settings}`.
- **Knocks:** `GET` / `DELETE /knocks/{from}`.
- **Who can read a profile:** a non-friend gets `name` and `emoji` only.

## Schema

See `migrations/0001_init.sql`. It has the tables from the 3.0 brief, with
three changes:
- **No extra indexes where a key already covers the lookup.** `users.email` has a UNIQUE constraint, and `members(squad)`, `cheers(to_uid)` and `knocks(to_uid)` lead their primary keys, so they need no index of their own. Each extra index costs a write per row.
- **Added:** `sessions(uid)`, for sign-out-everywhere and deletion.
- **Added:** `codes(uid)`, for deletion.
