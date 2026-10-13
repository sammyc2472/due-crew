-- A plan's totals, kept on its row: how many follow it, how many of those
-- (its owner aside) have its version in their Anki, and per date how many
-- sharing followers have it done. Counts only, never who. Worked out again
-- from every follow when they're read over an hour old (totals_at), so a
-- board, a plan's page or the library reads one row, not every follower's.
-- totals: {"v": version, "n": followers, "m": followers but the owner,
--          "r": of those, with version v, "done": {date id: n}}
ALTER TABLE plans ADD COLUMN totals TEXT;
ALTER TABLE plans ADD COLUMN totals_at INTEGER;
