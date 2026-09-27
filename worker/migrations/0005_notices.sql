-- 3.2.1: a notice from the admin (an update to get, something new), one line
-- at the top of the board. See docs/plans-design.md ("3.2.1").
CREATE TABLE notices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  text TEXT NOT NULL,
  link TEXT,             -- https only, shown as "More"
  below TEXT,            -- only to add-ons older than this version; NULL: everyone
  created_at INTEGER NOT NULL,
  until INTEGER NOT NULL -- it stops showing after this
);
