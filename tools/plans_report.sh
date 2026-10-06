#!/usr/bin/env bash
# Who has made study plans, from the live database (read-only).
#
#   tools/plans_report.sh            every plan, newest first, with its author
#   tools/plans_report.sh --emails   the authors' emails too (only you see this)
#   tools/plans_report.sh --dev      the dev database instead
#
# Needs wrangler logged in to the account that holds duecrew.com
# (run from anywhere in the repo). Nothing is written.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)/worker"

DB="due-crew"; ENV=""
EMAIL="''"
for a in "$@"; do
  case "$a" in
    --emails) EMAIL="COALESCE(u.email, '')" ;;
    --dev) DB="due-crew-dev"; ENV="dev" ;;
    *) echo "unknown option: $a"; exit 1 ;;
  esac
done

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
ORDER BY p.created_at DESC;
"

echo "== plans in $DB"
npx wrangler d1 execute "$DB" --remote --env="$ENV" --command "$SQL"
echo
echo "== totals"
npx wrangler d1 execute "$DB" --remote --env="$ENV" --command "
SELECT count(*) AS plans,
       count(DISTINCT NULLIF(owner, '')) AS authors,
       (SELECT count(*) FROM plan_follows) AS follows,
       (SELECT count(DISTINCT uid) FROM plan_follows) AS people_following
FROM plans;"
