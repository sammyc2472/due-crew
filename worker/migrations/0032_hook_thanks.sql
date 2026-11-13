-- 3.9.11, hooks: "This helped" reaches the hook's author once, with their next refresh
-- (cards.ts thanksFor). What was marked helped before this was never told, and isn't now.
ALTER TABLE tip_helped ADD COLUMN told INTEGER NOT NULL DEFAULT 0;
UPDATE tip_helped SET told = 1;
