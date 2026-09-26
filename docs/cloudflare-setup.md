# Cloudflare setup for 3.0 (once)

What Sam does by hand before the Worker can go live. Everything else
(code, tests, the deploy job) is in the repo. Run the `wrangler` commands
from `worker/`, after `npm ci` there.

## 1. Sign in

```
cd worker
npx wrangler login          # opens a browser; the account that holds duecrew.com
```

## 2. The databases

```
npx wrangler d1 create due-crew
npx wrangler d1 create due-crew-dev
```

Each prints a `database_id`. Paste them into `worker/wrangler.toml`: the
first under `[[d1_databases]]` and the second under
`[[env.dev.d1_databases]]`, in place of the zeros. Commit that change. The
ids aren't secrets.

Then create the tables:

```
npx wrangler d1 migrations apply due-crew --remote --env=""
npx wrangler d1 migrations apply due-crew-dev --remote --env dev
```

## 3. Mail (Resend)

1. Make a Resend account, and add the domain `duecrew.com`.
2. Resend lists DNS records to add: SPF and an MX on a sending subdomain,
   and a DKIM key. Add them in Cloudflare → duecrew.com → DNS exactly as
   Resend shows them, then click Verify in Resend.
3. Add a DMARC record in Cloudflare DNS: type `TXT`, name `_dmarc`,
   content `v=DMARC1; p=none; rua=mailto:you@duecrew.com` (any address
   you read). Tighten `p=` to `quarantine` once mail has gone out cleanly
   for a few weeks.
4. Create a Resend API key with sending access only, then:

```
npx wrangler secret put RESEND_API_KEY --env=""
npx wrangler secret put RESEND_API_KEY --env dev
```

Until the key is set, the Worker logs each code (`npx wrangler tail`)
instead of sending it. That's how the dev Worker can be tried before mail
works.

## 4. The admin token (for the identity import)

Any long random string, for example from `openssl rand -base64 32`:

```
npx wrangler secret put ADMIN_TOKEN --env=""
```

Keep it somewhere safe until the import at cutover. After that it can be
deleted (`npx wrangler secret delete ADMIN_TOKEN --env=""`); with no token
the import endpoint doesn't exist.

## 5. Deploys from GitHub

1. In Cloudflare, go to My Profile → API Tokens and create a token from
   the "Edit Cloudflare Workers" template. Add the D1 Edit permission, and
   limit it to the one account and the duecrew.com zone.
2. In GitHub, go to the repo → Settings → Secrets and variables → Actions
   and add two secrets:
   - `CLOUDFLARE_API_TOKEN`: that token.
   - `CLOUDFLARE_ACCOUNT_ID`: shown on the Cloudflare dashboard's
     overview.

From then on, a `v*` tag deploys once all five test jobs are green: it
migrates the database, deploys the Worker, and checks that
`https://api.duecrew.com/version` answers. Until the secrets and the
database id exist, the deploy job only posts a notice, so 2.x tags stay
green.

## 6. The dev Worker, by hand

```
npx wrangler deploy --env dev
curl https://api-dev.duecrew.com/version
```

`api-dev.duecrew.com` is the Worker a 3.0 client is tried against before
anyone else sees it. Deploying the dev Worker is manual on purpose.

## At cutover

1. Export the Firebase accounts:
   `firebase auth:export users.json --format=json --project anki-leaderboard-f6691`.
2. Feed them to the import (uid, email, and the display name when there
   is one): `DUE_CREW_ADMIN_TOKEN=... python3 tools/import_users.py
   users.json --firestore --go` (without `--go` it's a dry run; `--firestore`
   carries each name and friend code across, with your `gcloud` login).
3. Tag 3.0.0. The crew updates; the Firebase project stays up read-only
   for stragglers, then goes.
