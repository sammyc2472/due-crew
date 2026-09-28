#!/usr/bin/env bash
# After a deploy: does production answer, and is it this release's code?
# Signs nobody in and sends no mail. Base URLs can be overridden:
#   API=https://api-dev.duecrew.com SITE=https://duecrew.com tools/check_prod.sh
set -uo pipefail
API=${API:-https://api.duecrew.com}
SITE=${SITE:-https://duecrew.com}
fail=0

check() {  # name, expected status, curl args...
  local name=$1 want=$2; shift 2
  local got
  got=$(curl -s -o /dev/null -m 15 -w '%{http_code}' "$@")
  if [ "$got" = "$want" ]; then echo "ok    $name ($got)"; else echo "FAIL  $name: $got, wanted $want"; fail=1; fi
}

echo "API $API"
curl -fsS -m 15 "$API/version" && echo || { echo "FAIL  /version"; fail=1; }
check "unknown route"                     404 "$API/nope"
check "board needs sign-in"               401 "$API/board"
check "a code look-up needs sign-in"      401 "$API/codes/ABC123"
check "plan peek, no such code"           404 "$API/plans/public?code=ZZZZ2345"
check "invite, no such code"              404 "$API/invites/ZZZZZZZZZZ"
check "email link, not from the site"     403 -X POST -H 'content-type: application/json' \
      -d '{"email":"x@example.com","path":"/"}' "$API/links/email"

echo
echo "site $SITE"
check "landing"                           200 "$SITE/"
check "board.png"                         200 "$SITE/board.png"
check "the app"                           200 "$SITE/app.js"
check "/api reaches the API"              200 "$SITE/api/version"
check "a plan page"                       200 "$SITE/p/ZZZZ2345"
check "an invite page"                    200 "$SITE/i/ZZZZZZZZZZ"
case $SITE in https://*) check "www" 200 -L "https://www.${SITE#https://}/" ;; esac

echo
[ $fail = 0 ] && echo "All good." || { echo "Something's off (above)."; exit 1; }
