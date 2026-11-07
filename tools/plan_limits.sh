#!/usr/bin/env bash
# Which plans, and which accounts, are at or near a ceiling the Worker holds a
# plan's save to (worker/src/plans.ts), from the live database (read-only).
# A save that goes past one is refused; the add-on says only "The plan didn't
# take that change", the site "Something in the plan isn't valid".
#
#   tools/plan_limits.sh          plans at 80% of a ceiling or more, and accounts near theirs
#   tools/plan_limits.sh --all    every plan's numbers
#   tools/plan_limits.sh --dev    the dev database instead
#
# Needs wrangler logged in to the account that holds duecrew.com. Nothing is written.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)/worker"

DB="due-crew"; ENV=""; NEAR="WHERE sets >= 160 OR events >= 160 OR review_days >= 48 OR picks >= 40000 OR ids >= 40000 OR idr >= 40000 OR tags >= 80 OR kb >= 1228"
for a in "$@"; do
  case "$a" in
    --all) NEAR="" ;;
    --dev) DB="due-crew-dev"; ENV="dev" ;;
    *) echo "unknown option: $a"; exit 1 ;;
  esac
done

# the ceilings, as plans.ts has them: sets 200, events 200, review days 60, tags 100,
# picked cards and IDs 50,000 in all (with the plan tags' notes), note ids 50,000, refs 50,000,
# a doc 1,536 KB; an account's plans 24 MB in all (docs, library cards, Undo's copies), 50 plans;
# saves 500 a day a person.
PLANS="
WITH p AS (
  SELECT p.id, p.name, COALESCE(u.name, '(deleted)') AS owner_name,
    COALESCE(json_array_length(p.doc, '\$.units'), 0) AS sets,
    COALESCE(json_array_length(p.doc, '\$.events'), 0) AS events,
    COALESCE(json_array_length(p.doc, '\$.reviews'), 0) AS review_days,
    COALESCE(json_array_length(p.doc, '\$.tags'), 0) AS tags,
    (SELECT COALESCE(SUM(COALESCE(json_array_length(x.value, '\$.cards'), 0) + COALESCE(json_array_length(x.value, '\$.nids'), 0)
        + COALESCE(json_array_length(x.value, '\$.cids'), 0) + COALESCE(json_array_length(x.value, '\$.notes'), 0)), 0)
       FROM json_each(p.doc, '\$.units') x)
     + (SELECT COALESCE(SUM(COALESCE(json_array_length(t.value, '\$.notes'), 0) + COALESCE(json_array_length(t.value, '\$.cards'), 0)), 0)
       FROM json_each(p.doc, '\$.tags') t) AS picks,
    (SELECT COALESCE(SUM(COALESCE(json_array_length(x.value, '\$.ids'), 0)), 0) FROM json_each(p.doc, '\$.units') x) AS ids,
    (SELECT COALESCE(SUM(COALESCE(json_array_length(x.value, '\$.idr'), 0)), 0) FROM json_each(p.doc, '\$.units') x) AS idr,
    LENGTH(p.doc) / 1024 AS kb,
    date(p.updated_at, 'unixepoch') AS last_saved
  FROM plans p LEFT JOIN users u ON u.uid = p.owner
)
SELECT name AS plan, owner_name AS owner, sets, events, review_days, tags, picks, ids, idr, kb, last_saved
FROM p $NEAR ORDER BY kb DESC;
"

ACCOUNTS="
SELECT COALESCE(u.name, '(deleted)') AS owner, COUNT(*) AS plans,
  (SUM(LENGTH(p.doc) + COALESCE(LENGTH(p.lib), 0))
   + COALESCE((SELECT SUM(LENGTH(l.prev)) FROM plan_log l JOIN plans q ON q.id = l.plan
               WHERE q.owner = p.owner AND l.prev IS NOT NULL), 0)) / 1048576.0 AS mb_of_24,
  COALESCE((SELECT count FROM limits WHERE key = 'planput:' || p.owner AND window_start > unixepoch() - 86400), 0) AS saves_today_of_500
FROM plans p LEFT JOIN users u ON u.uid = p.owner
GROUP BY p.owner
ORDER BY mb_of_24 DESC
LIMIT 15;
"

echo "== plans near a ceiling in $DB (sets 200 · events 200 · review days 60 · tags 100 · picks, ids, idr 50,000 · 1,536 KB)"
npx wrangler d1 execute "$DB" --remote --env="$ENV" --command "$PLANS"
echo "== accounts: plans (50), MB kept (24), saves today (500)"
npx wrangler d1 execute "$DB" --remote --env="$ENV" --command "$ACCOUNTS"
