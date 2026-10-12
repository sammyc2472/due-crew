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

## 3. Mail: Cloudflare Email Service (or Resend)

The Worker sends sign-in codes through Cloudflare Email Service when its
`send_email` binding (`EMAIL`) is configured, else through Resend when
`RESEND_API_KEY` is set, else it logs each code (`npx wrangler tail`),
which is how the dev Worker can be tried before mail works.

**Cloudflare Email Service** (needs Workers Paid, $5/month; 3,000 emails a
month included):

1. Workers & Pages → Plans: move to Workers Paid.
2. Email Service: add `duecrew.com` as a sending domain and let it add its
   DNS records.
3. The `send_email` binding goes in `wrangler.toml` (both environments),
   allowed to send only from `codes@duecrew.com`; then deploy.

**Resend** instead: make an account, add `duecrew.com`, add the DNS records
it lists in Cloudflare DNS, add a DMARC record (`TXT _dmarc`,
`v=DMARC1; p=none`), and `npx wrangler secret put RESEND_API_KEY` for each
environment.

## 4. The admin token (gone in 3.8.0)

3.0's one-shot import from Firebase needed `ADMIN_TOKEN`; the import went
with Firebase in 3.8.0. If it's still set, delete it:
`npx wrangler secret delete ADMIN_TOKEN --env=""`.

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

## 7. The website

`site/` is duecrew.com: static files, plus a small Worker (`site/src/index.ts`)
that sends `/api/*` to the API Worker through a service binding, and serves
the app (sign-in, plans, the builder). The API must be deployed first. The tag deploys it with the
Worker; the first time, or any time by hand, from `worker/`:

```
npx wrangler deploy --config ../site/wrangler.toml
```

It claims `duecrew.com` and `www.duecrew.com`. If either already has a DNS
record (a parking page, say), delete that record first; Cloudflare won't
attach a custom domain over one.

## 8. Settings to check

- Security → Bots: leave **Bot Fight Mode off**. It challenges requests
  that don't come from a browser, and the add-on's requests don't.
- SSL/TLS: Full (strict), and Always Use HTTPS on.
- Optional: Email Routing, for an address like `hello@duecrew.com` that
  forwards to you, and for DMARC reports.
- The free Workers plan covers a crew of this size: 100,000 requests a
  day, and D1's free tier (5 million reads, 100,000 writes a day). The $5
  paid plan raises all of it; move when the dashboard says you're near.

## Firebase is gone (3.8.0)

3.0 moved the 2.x accounts across; 3.8.0 took out the bridge, the import
and every 2.x path.

The Google project (anki-leaderboard-f6691) was shut down on 12 Oct 2026,
before 3.8.0's Worker went out. Nothing in it can be read (2.x crewmates
included), and Google deletes it for good 30 days on, Firestore and the
`due-crew-bridge` service account with it. Don't restore it. Until 3.8.0
is live, the old Worker's bridge fails every 15 minutes and stops before
writing anything (no token, or a 403 on its first read), and a deleted
account's 2.x copies (`forget()`) fail inside a try after D1 has
deleted the account. Had the project stayed up, Firestore had to be emptied
right after the deploy, never before: the old bridge would copy 3.x people
back in, and read an empty Firestore as 2.x heatmaps turned off.

What's left, any time:

1. `npx wrangler secret delete FIREBASE_SA --env=""` (and `--env=dev` if
   it was set there). Without it the old bridge doesn't run at all.
