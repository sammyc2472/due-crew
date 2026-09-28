-- 3.5, B: the plan library. An author lists a plan ("anyone with the
-- code" plans only); anyone signed in can look at it, follow it, or copy
-- it. `listed`: 0 not listed, 1 listed, -1 taken out by the admin (the
-- author reads why in `listed_note` and can't list it again until the
-- admin puts it back). `lib`: the few numbers a library card shows,
-- kept on every save so the library never reads a plan's doc.
-- `based_on`: a copy's credit, {id, name, owner} as it was when copied.
ALTER TABLE plans ADD COLUMN listed INTEGER NOT NULL DEFAULT 0;
ALTER TABLE plans ADD COLUMN listed_at INTEGER;
ALTER TABLE plans ADD COLUMN listed_note TEXT;
ALTER TABLE plans ADD COLUMN lib TEXT;
ALTER TABLE plans ADD COLUMN based_on TEXT;
CREATE INDEX plans_listed ON plans(listed, listed_at);
