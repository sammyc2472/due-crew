-- 3.7.6: a follower moves one date later on their own copy: {unit id: days
-- later}, on top of `shift`. Theirs only, like shift and skipped; the plan
-- never changes.
ALTER TABLE plan_follows ADD COLUMN moved TEXT;
