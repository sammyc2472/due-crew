-- 3.9.5: starter plans. The admin marks a few plans in the library as
-- starters (POST /admin/library/{id}/starter): the library shows them in a
-- row of their own, under Due Crew, and the day's first board offers them
-- to someone who owns and follows no plan. 1 a starter, 0 not; only a
-- listed plan is one, and a plan leaves the starters as it leaves the
-- library. The index holds the starters alone, newest listed first.
ALTER TABLE plans ADD COLUMN starter INTEGER NOT NULL DEFAULT 0;
CREATE INDEX plans_starter ON plans(listed_at) WHERE starter = 1;
