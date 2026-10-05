-- 3.8 plan updates: a plan's authors post to its followers (one line, any
-- time, or with a save), and an author sees how many followers' Anki has the
-- latest version (seen_version, written when a board carries it to them).
CREATE TABLE plan_posts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  plan TEXT NOT NULL,
  uid TEXT NOT NULL,
  text TEXT NOT NULL,
  version INTEGER,
  at INTEGER NOT NULL
);
CREATE INDEX plan_posts_plan ON plan_posts (plan, id);
CREATE INDEX plan_posts_uid ON plan_posts (uid);
ALTER TABLE plan_follows ADD COLUMN seen_version INTEGER;
