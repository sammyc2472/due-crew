-- 3.8.1 (the audit, #2): a settings save replaced the whole doc, so two computers
-- (or a computer and the site) saving close together lost one side's change. Each
-- save now moves `rev`; a save that names the rev it started from (`base`) is turned
-- away with the current doc when someone saved since, and the client merges.
ALTER TABLE settings ADD COLUMN rev INTEGER NOT NULL DEFAULT 0;
