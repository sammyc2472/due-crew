-- 3.8.0: how a plan's cards open for me: NULL on the plan's dates (as
-- before), 'ready' when I open them, 'next' when I open the first and each
-- next one opens once I've seen the last. Mine only, like shift and pause.
ALTER TABLE plan_follows ADD COLUMN own TEXT;
