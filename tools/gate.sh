#!/usr/bin/env bash
# The whole gate in one go, in the order that keeps it honest, one line a check (3.9.12).
#
#   tools/gate.sh            everything this computer can run
#   tools/gate.sh --quick    pyflakes and the suites only (seconds)
#
# The real-Anki checks (dialogs, the click test) run when there's a Python with aqt:
#   ANKI_PY=/path/to/venv/bin/python tools/gate.sh
# and the click test runs last and alone: with anything beside it, its timings fail it.
# The Worker's checks run when worker/node_modules is there (npm ci in worker/ once).
set -uo pipefail
cd "$(dirname "$0")/.."
QUICK=0; [ "${1:-}" = "--quick" ] && QUICK=1
OUT=$(mktemp -d)
BAD=0
line() { printf '%-34s %s\n' "$1" "$2"; }
run() {  # name, the last line to show (a command reading the log), then the check itself
  local name="$1" show="$2"; shift 2
  if "$@" >"$OUT/log" 2>&1; then line "$name" "ok   $(eval "$show" 2>/dev/null | tail -1)"
  else line "$name" "FAILED   (tail: $(tail -3 "$OUT/log" | tr '\n' ' ' | cut -c1-200))"; BAD=1; cp "$OUT/log" "$OUT/$(echo "$name" | tr ' /' '__').log"; fi
}

run "pyflakes" "echo" python3 -m pyflakes due_crew tests tools
for t in tests/test_*.py; do
  run "$(basename "$t" .py)" "tail -1 $OUT/log" python3 "$t" -q
done
run "site scripts parse" "echo" bash -c 'for f in site/public/*.js site/public/planpage/*.js; do node --check "$f" || exit 1; done'

if [ "$QUICK" = 0 ]; then
  if [ -d worker/node_modules ]; then
    run "worker: typecheck" "echo" bash -c 'cd worker && npx tsc --noEmit'
    run "worker: vitest" "grep -E 'Tests ' $OUT/log" bash -c 'cd worker && npx vitest run'
  else line "worker" "skipped (npm ci in worker/ first)"; fi
  PY="${ANKI_PY:-}"
  if [ -n "$PY" ] && "$PY" -c 'import aqt' 2>/dev/null; then
    run "dialogs (offscreen Qt)" "tail -1 $OUT/log" env QT_QPA_PLATFORM=offscreen "$PY" tools/dialogs.py "$OUT/dialogs"
    run "click test (real Anki, alone)" "grep 'No failures' $OUT/click.log" bash -c "QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS=--no-sandbox '$PY' tools/click_test.py --out '$OUT/click' 2>&1 | tee '$OUT/click.log' | grep -q 'No failures'"
  else line "dialogs, click test" "skipped (set ANKI_PY to a Python with aqt)"; fi
fi
echo
[ "$BAD" = 0 ] && echo "Gate: green." || echo "Gate: RED. Logs in $OUT"
exit "$BAD"
