-- 3.7.1 review: the 2.x restore (PUT /friends {ids}, a wanted friend code,
-- POST /squads/restore) is for accounts that came from 2.x, once, not for
-- anyone who sets their client version to "2.9". The import sets it; an
-- account's first sync from a 3.x add-on clears it.
ALTER TABLE users ADD COLUMN from2x INTEGER NOT NULL DEFAULT 0;
UPDATE users SET from2x = 1 WHERE client_version IS NULL OR client_version NOT LIKE '3.%';

-- GET /board reads the live notices: by their end, not a scan of every one
CREATE INDEX notices_until ON notices (until);
