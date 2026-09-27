#!/usr/bin/env bash
# Build a release from main: run the local checks, build due_crew.ankiaddon,
# and (with --tag) tag vX.Y.Z from manifest.json and push the tag, which
# deploys the database, the API and the site once CI is green.
#
#   tools/release.sh            checks + the .ankiaddon, nothing pushed
#   tools/release.sh --tag      the same, then tag and push the tag
#
# After the tag's Actions run is green:
#   gh release create vX.Y.Z due_crew.ankiaddon --generate-notes
#   tools/check_prod.sh
set -euo pipefail
cd "$(dirname "$0")/.."

TAG=0
[ "${1:-}" = "--tag" ] && TAG=1

VERSION=$(python3 -c 'import json; print(json.load(open("due_crew/manifest.json"))["version"])')
PACKAGE=$(python3 -c 'import json; print(json.load(open("due_crew/manifest.json"))["package"])')
say() { printf '\n== %s\n' "$*"; }

say "v$VERSION (package $PACKAGE)"
[ "$PACKAGE" = "2035408484" ] || { echo "manifest package must be 2035408484 (AnkiWeb's folder)"; exit 1; }

BRANCH=$(git rev-parse --abbrev-ref HEAD)
[ "$BRANCH" = "main" ] || { echo "on $BRANCH; release from main"; exit 1; }
[ -z "$(git status --porcelain)" ] || { echo "the tree has changes; commit or stash them"; exit 1; }
git fetch -q origin main
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || { echo "main differs from origin/main; pull first"; exit 1; }
if git rev-parse -q --verify "refs/tags/v$VERSION" >/dev/null; then
  echo "v$VERSION is already tagged; bump due_crew/manifest.json"; exit 1
fi

say "pyflakes"
python3 -m pyflakes due_crew tests tools
say "add-on suite"
python3 tests/test_due_crew.py | tail -1
say "Worker: typecheck and tests"
(cd worker && npm ci --silent && npx tsc --noEmit && npx vitest run 2>&1 | grep -E "Tests|Test Files")
say "site JS"
node --check site/public/app.js && node --check site/public/builder.js && echo ok

say "due_crew.ankiaddon"
rm -f due_crew.ankiaddon
(cd due_crew && zip -qr ../due_crew.ankiaddon . -x "*.DS_Store" -x "user_files/*" -x "*__pycache__*" -x "*.pyc")
unzip -l due_crew.ankiaddon | tail -1
unzip -p due_crew.ankiaddon manifest.json | grep -q "\"$VERSION\"" || { echo "the zip's manifest isn't $VERSION"; exit 1; }

if [ "$TAG" = 1 ]; then
  say "tag v$VERSION"
  git tag -a "v$VERSION" -m "Due Crew $VERSION"
  git push origin "v$VERSION"
  echo "Pushed. The tag's Actions run migrates D1, deploys the API, then the site."
  echo "When it's green: gh release create v$VERSION due_crew.ankiaddon --generate-notes"
  echo "Then: tools/check_prod.sh"
else
  echo
  echo "Ready. Re-run with --tag to tag v$VERSION and deploy."
fi
