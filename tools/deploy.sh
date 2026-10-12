#!/usr/bin/env bash
# Deploy production by hand from a clean main: the D1 migrations, the API,
# then the site, then tools/check_prod.sh. What the tag's deploy job does
# once the GitHub secrets exist (docs/go-live.md, 2b). Runs from anywhere
# in the repo:
#
#   cd ~/Desktop/"due crew"/worker && git checkout main && git pull origin main
#   bash ../tools/deploy.sh
#
# The migrations only add, so the running API is fine between them and its
# deploy. Upload the .ankiaddon to AnkiWeb only after this finishes clean.
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION=$(python3 -c 'import json; print(json.load(open("due_crew/manifest.json"))["version"])')
say() { printf '\n== %s\n' "$*"; }

say "v$VERSION"
BRANCH=$(git rev-parse --abbrev-ref HEAD)
[ "$BRANCH" = "main" ] || { echo "on $BRANCH; deploy from main (merge the PR first)"; exit 1; }
[ -z "$(git status --porcelain)" ] || { echo "the tree has changes; commit or stash them"; exit 1; }
git fetch -q origin main
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || { echo "main differs from origin/main; pull first"; exit 1; }

cd worker
npm ci --silent
# On error 7403 (wrong account): npx wrangler logout && npx wrangler login
npx wrangler whoami >/dev/null 2>&1 || npx wrangler login

say "migrations (it lists any new ones and asks first)"
npx wrangler d1 migrations apply due-crew --remote --env=""

say "the API"
npx wrangler deploy --env=""

say "the site"
npx wrangler deploy --config ../site/wrangler.toml

cd ..
say "production checks"
tools/check_prod.sh

echo
echo "Deployed v$VERSION. Next:"
echo "  tools/release.sh --tag                       the checks, due_crew.ankiaddon, tag v$VERSION"
echo "  gh release create v$VERSION due_crew.ankiaddon --generate-notes"
echo "  AnkiWeb listing 2035408484, Branch 1: upload due_crew.ankiaddon"
echo "If anything's wrong: cd worker && npx wrangler rollback --env=\"\""
