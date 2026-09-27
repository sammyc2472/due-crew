# Going live: 3.3.0

Production already runs 3.x: the API at `api.duecrew.com` and the site at
`duecrew.com`, deployed by hand from Sam's Mac. The tags' deploy job has
always stood down, because the GitHub secrets (§0, `CLOUDFLARE_API_TOKEN`
and `CLOUDFLARE_ACCOUNT_ID`) aren't set. So a tag deploys nothing: deploy
by hand (step 2b). The 2.x accounts were imported at 3.0 (`ADMIN_TOKEN` is
gone, as the import leaves it), and the bridge's `FIREBASE_SA` is set.

What 3.3.0 adds: migration 0006, the API, the site, and the add-on on
AnkiWeb. Commands run from the repo root unless they say `cd worker`.

## 0. One-time setup (`docs/cloudflare-setup.md`)

Tick each one before tagging; the deploy job skips everything if §5 is missing.

- [ ] §1 `cd worker && npm ci && npx wrangler login` on the account that holds duecrew.com
- [ ] §2 both D1 databases exist (the ids are already in `worker/wrangler.toml`)
- [ ] §3 mail: Workers Paid, and `duecrew.com` verified in Email Service
      (the `EMAIL` binding is already in `wrangler.toml`)
- [ ] §4 `npx wrangler secret put ADMIN_TOKEN --env=""`, and keep the value for step 3
- [ ] §5 GitHub → Settings → Secrets → Actions: `CLOUDFLARE_API_TOKEN`
      (Workers + D1 edit) and `CLOUDFLARE_ACCOUNT_ID`. The deploy job runs in
      the `production` environment: if that environment has required
      reviewers, you approve the run in Actions.
- [ ] §7 no DNS records on `duecrew.com`, `www` or `api` (custom domains won't attach over one)
- [ ] §8 Bot Fight Mode off; SSL Full (strict); Always Use HTTPS on

## 1. Try it on dev first (optional; ~10 minutes)

```
cd worker
npx wrangler d1 migrations apply due-crew-dev --remote --env dev
npx wrangler deploy --env dev
cd .. && API=https://api-dev.duecrew.com SITE=https://duecrew.com tools/check_prod.sh
```

Only the API half applies to dev (the site binds to production). To point
an Anki at dev, add `"api_base": "https://api-dev.duecrew.com"` to the
add-on's config, sign in, and click through `docs/manual-anki-checklist.md`.
Remove the key when you're done.

## 2. Merge the PR, then tag

Merge the PR into `main` once its checks are green. Then:

```
git checkout main && git pull
tools/release.sh           # the checks and due_crew.ankiaddon; nothing is pushed
tools/release.sh --tag     # the same, then tags v3.3.0 and pushes the tag
```

Until the GitHub secrets exist, the tag's deploy job stands down. Deploy by hand:

### 2b. By hand, from `worker/`

```
npx wrangler d1 migrations apply due-crew --remote --env=""
npx wrangler deploy --env=""
npx wrangler deploy --config ../site/wrangler.toml
```

The migration only adds tables, so the running API is fine before its deploy.

## 3. The 2.x accounts (done at 3.0; only for a fresh setup)

Until this runs, someone who signs in on the site with a 2.x email gets a
brand-new account instead of their old one, so do it straight away:

```
firebase auth:export users.json --format=json --project anki-leaderboard-f6691
DUE_CREW_ADMIN_TOKEN=... python3 tools/import_users.py users.json --firestore        # dry run
DUE_CREW_ADMIN_TOKEN=... python3 tools/import_users.py users.json --firestore --go
rm users.json
```

It's safe to run twice. Then the 2.x bridge, so 2.x and 3.x crewmates
still see each other (`docs/cloudflare-setup.md`, "The 2.x bridge"):

```
cd worker && npx wrangler secret put FIREBASE_SA --env="" < ~/Downloads/<key>.json
```

## 4. Check production

```
tools/check_prod.sh
```

It signs nobody in and sends no mail. Then by hand, on a phone and a
computer: sign in at duecrew.com (the code arrives by email), open a
plan's link while signed out, and try "Email it" on the phone.

## 5. The add-on

```
gh release create v3.3.0 due_crew.ankiaddon --generate-notes
```

Install that file by hand in your own Anki first (Tools › Add-ons ›
Install from file; it replaces the AnkiWeb copy and keeps your
user_files). Click through `docs/manual-anki-checklist.md` against
production. Then AnkiWeb: listing 2035408484 › update Branch 1 with the
file, and paste README.md from the tagline down (it changed).

## 6. After

- Optional: from `/admin`, post a notice. Only 3.2.1+ add-ons show it, so
  it's for the next release, not this one.
- Watch the logs for a day: `cd worker && npx wrangler tail --env=""`.
- Compare the two backends now and then: `tools/bridge_check.py`.

## If something breaks

- **API or site:** `cd worker && npx wrangler rollback --env=""`, or for
  the site `npx wrangler rollback --config ../site/wrangler.toml`. Either
  goes back to the previous version in seconds.
- **Data:** the migrations only add, so an older Worker still runs on the
  new schema. For a bad write, D1 Time Travel:
  `npx wrangler d1 time-travel restore due-crew --timestamp=<before>`.
- **Add-on:** upload the previous .ankiaddon to AnkiWeb again. Raising
  `MIN_CLIENT` in `worker/wrangler.toml` (and redeploying) shows older
  clients "server catching up"; use it only if one misbehaves.
