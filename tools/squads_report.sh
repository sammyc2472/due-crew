#!/usr/bin/env bash
# What squads there are and who's in them, from the live database (read-only).
#
#   tools/squads_report.sh            every squad, then its members
#   tools/squads_report.sh NAME       only squads whose name contains NAME
#   tools/squads_report.sh --emails   the members' emails too (only you see this)
#   tools/squads_report.sh --dev      the dev database instead
#
# Needs wrangler logged in to the account that holds duecrew.com
# (run from anywhere in the repo). Nothing is written. Squad codes are
# kept as hashes, so they can't be shown; /admin › Squads finds one by code.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)/worker"

DB="due-crew"; ENV=""
EMAIL="''"
LIKE=""
for a in "$@"; do
  case "$a" in
    --emails) EMAIL="COALESCE(u.email, '')" ;;
    --dev) DB="due-crew-dev"; ENV="dev" ;;
    -*) echo "unknown option: $a"; exit 1 ;;
    *) LIKE="${a//\'/\'\'}" ;;
  esac
done
WHERE="s.name LIKE '%$LIKE%'"
# seconds, or milliseconds from an older writer
day() { echo "date(CASE WHEN $1 > 100000000000 THEN $1 / 1000 ELSE $1 END, 'unixepoch')"; }

echo "== squads in $DB"
npx wrangler d1 execute "$DB" --remote --env="$ENV" --command "
SELECT
  s.name AS squad,
  COALESCE(f.name, '(deleted)') AS founder,
  CASE WHEN s.open = 1 THEN 'open' ELSE 'locked' END AS joining,
  (SELECT count(*) FROM members m WHERE m.squad = s.id) AS members,
  (SELECT count(*) FROM members m WHERE m.squad = s.id AND m.day >= date('now', '-7 days')) AS studied_7d,
  (SELECT count(*) FROM bans b WHERE b.squad = s.id) AS removed,
  $(day s.created_at) AS made,
  s.id AS id
FROM squads s LEFT JOIN users f ON f.uid = s.founder
WHERE $WHERE
ORDER BY members DESC, s.name;"

echo
echo "== who's in them"
npx wrangler d1 execute "$DB" --remote --env="$ENV" --command "
SELECT
  s.name AS squad,
  COALESCE(COALESCE(NULLIF(u.emoji, ''), NULLIF(m.emoji, '')) || ' ', '') || COALESCE(u.name, m.name) AS member,
  $EMAIL AS email,
  CASE WHEN m.uid = s.founder THEN 'founder' ELSE '' END AS role,
  $(day m.joined_at) AS joined,
  COALESCE(m.day, '') AS last_studied,
  COALESCE(u.client_version, '2.x') AS addon
FROM members m
JOIN squads s ON s.id = m.squad
LEFT JOIN users u ON u.uid = m.uid
WHERE $WHERE
ORDER BY s.name, m.joined_at;"

echo
echo "== totals"
npx wrangler d1 execute "$DB" --remote --env="$ENV" --command "
SELECT count(*) AS squads,
       (SELECT count(*) FROM members) AS memberships,
       (SELECT count(DISTINCT uid) FROM members) AS people_in_a_squad,
       (SELECT count(*) FROM squads s WHERE NOT EXISTS (SELECT 1 FROM members m WHERE m.squad = s.id)) AS empty
FROM squads;"
