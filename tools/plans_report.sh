#!/usr/bin/env bash
# What study plans there are and who's in them, from the live database
# (read-only).
#
#   tools/plans_report.sh            every plan, newest first, then its people
#   tools/plans_report.sh NAME       only plans whose name contains NAME
#   tools/plans_report.sh --emails   their emails too (only you see this)
#   tools/plans_report.sh --dev      the dev database instead
#
# Needs wrangler logged in to the account that holds duecrew.com
# (run from anywhere in the repo). Nothing is written.
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
WHERE="p.name LIKE '%$LIKE%'"

SQL="
SELECT
  p.name AS plan,
  CASE WHEN p.owner = '' THEN '(a former member)' ELSE COALESCE(u.name, '(deleted)') END AS made_by,
  $EMAIL AS email,
  COALESCE(json_extract(p.doc, '\$.deck'), '') AS deck,
  COALESCE(json_array_length(json_extract(p.doc, '\$.units')), 0) AS dates,
  (SELECT count(*) FROM plan_follows f WHERE f.plan = p.id) AS followers,
  (SELECT count(*) FROM plan_editors e WHERE e.plan = p.id) AS coauthors,
  p.audience || CASE WHEN p.listed = 1 THEN ', in library' WHEN p.listed = -1 THEN ', taken out' ELSE '' END AS shared,
  date(p.created_at, 'unixepoch') AS made,
  date(p.updated_at, 'unixepoch') AS last_saved
FROM plans p LEFT JOIN users u ON u.uid = p.owner
WHERE $WHERE
ORDER BY p.created_at DESC;
"

echo "== plans in $DB"
npx wrangler d1 execute "$DB" --remote --env="$ENV" --command "$SQL"
echo
echo "== who's in them"
# one row a person a plan: the owner, co-authors, then followers by when they followed
npx wrangler d1 execute "$DB" --remote --env="$ENV" --command "
SELECT plan, member, email, role, since, following, team, has_latest FROM (
  SELECT p.name AS plan, p.created_at AS pc, 0 AS k, p.created_at AS t,
    COALESCE(NULLIF(u.emoji, '') || ' ', '') || COALESCE(u.name, '(deleted)') AS member, $EMAIL AS email,
    'owner' AS role, date(p.created_at, 'unixepoch') AS since,
    '' AS following, '' AS team, '' AS has_latest
  FROM plans p JOIN users u ON u.uid = p.owner
  WHERE $WHERE
  UNION ALL
  SELECT p.name, p.created_at, 1, e.at,
    COALESCE(NULLIF(u.emoji, '') || ' ', '') || COALESCE(u.name, '(deleted)'), $EMAIL,
    'co-author', date(e.at, 'unixepoch'), '', '', ''
  FROM plan_editors e JOIN plans p ON p.id = e.plan LEFT JOIN users u ON u.uid = e.uid
  WHERE $WHERE
  UNION ALL
  SELECT p.name, p.created_at, 2, f.at,
    COALESCE(NULLIF(u.emoji, '') || ' ', '') || COALESCE(u.name, '(deleted)'), $EMAIL,
    'follower', date(f.at, 'unixepoch'),
    CASE WHEN f.paused = 1 OR f.pause_until >= date('now') THEN 'paused' ELSE 'yes' END
      || CASE WHEN f.share = 1 THEN ', shares progress' ELSE '' END,
    CASE WHEN EXISTS (SELECT 1 FROM plan_team t WHERE t.plan = f.plan AND t.uid = f.uid) THEN 'on team' ELSE '' END,
    CASE WHEN f.seen_version IS NULL THEN '' WHEN f.seen_version >= p.version THEN 'yes' ELSE 'not yet' END
  FROM plan_follows f JOIN plans p ON p.id = f.plan LEFT JOIN users u ON u.uid = f.uid
  WHERE $WHERE
) ORDER BY pc DESC, plan, k, t;"

echo
echo "== totals"
npx wrangler d1 execute "$DB" --remote --env="$ENV" --command "
SELECT count(*) AS plans,
       count(DISTINCT NULLIF(owner, '')) AS authors,
       (SELECT count(*) FROM plan_follows) AS follows,
       (SELECT count(DISTINCT uid) FROM plan_follows) AS people_following
FROM plans;"
