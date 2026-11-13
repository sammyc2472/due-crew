#!/usr/bin/env bash
# Everything a release hands over, in one folder (3.9.12): ship/
#   due_crew.ankiaddon     the file for AnkiWeb (listing 2035408484, Branch 1)
#   README-ankiweb.md      the listing's description: the README from its tagline down
#   deploy.txt             the block to paste in Terminal (the server first, then the site)
# From the tree as it is; it checks nothing (tools/gate.sh does) and pushes nothing.
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION=$(python3 -c 'import json; print(json.load(open("due_crew/manifest.json"))["version"])')
rm -rf ship && mkdir ship
(cd due_crew && zip -qr ../ship/due_crew.ankiaddon . -x "*.DS_Store" -x "user_files/*" -x "*__pycache__*" -x "*.pyc")
unzip -p ship/due_crew.ankiaddon manifest.json | grep -q "\"$VERSION\"" || { echo "the zip's manifest isn't $VERSION"; exit 1; }
sed -n '/^<\/picture>$/,$p' README.md | sed '1d' | sed '/./,$!d' > ship/README-ankiweb.md
[ -s ship/README-ankiweb.md ] || { echo "README.md has no logo block to cut at"; exit 1; }
NEW=$(git diff --name-only origin/main...HEAD -- worker/migrations 2>/dev/null | wc -l | tr -d ' ')
cat > ship/deploy.txt <<TXT
cd ~/Desktop/"due crew"
git stash -u
git checkout main
git pull origin main
bash tools/deploy.sh
git stash pop
TXT
echo "ship/ for v$VERSION:"
ls -la ship | tail -3 | awk '{print "  " $5, $9}'
echo "  new migrations since main: $NEW (deploy.sh lists them and asks before applying)"
echo "After the deploy runs clean: upload the .ankiaddon to AnkiWeb, paste README-ankiweb.md if it changed."
