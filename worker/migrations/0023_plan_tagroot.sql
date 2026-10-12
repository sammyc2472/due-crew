-- 3.8.0: a plan's own part of its tags (DueCrew::<tagroot>::SLG_12) is its
-- alone: two plans followed in one Anki must never share it, and Anki's tags
-- ignore case. Set when the plan's first tag is made; a taken one gets _2.
ALTER TABLE plans ADD COLUMN tagroot TEXT;
CREATE UNIQUE INDEX plans_tagroot ON plans(tagroot COLLATE NOCASE);
