-- 3.1: plans. A plan is one row (its units live in `doc`), so an edit is
-- one compare-before-write. See docs/plans-design.md.

CREATE TABLE plans (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  owner TEXT NOT NULL,
  name TEXT NOT NULL,
  line TEXT NOT NULL DEFAULT '',
  audience TEXT NOT NULL DEFAULT 'code',   -- 'code' | 'squad'
  squad TEXT,                              -- the squad it's offered to (and limited to, for 'squad')
  doc TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE INDEX plans_owner ON plans(owner);
CREATE INDEX plans_squad ON plans(squad);

-- a deck's tag and subdeck names with card counts, for the builder
CREATE TABLE plan_trees (
  uid TEXT NOT NULL,
  deck TEXT NOT NULL,
  doc TEXT NOT NULL,
  at INTEGER NOT NULL,
  PRIMARY KEY (uid, deck)
);

CREATE TABLE plan_follows (
  plan TEXT NOT NULL,
  uid TEXT NOT NULL,
  share INTEGER NOT NULL DEFAULT 1,
  paused INTEGER NOT NULL DEFAULT 0,
  progress TEXT,
  at INTEGER NOT NULL,
  PRIMARY KEY (plan, uid)
);
CREATE INDEX plan_follows_uid ON plan_follows(uid);

-- one-time links that sign the site in from the add-on
CREATE TABLE login_links (
  hash TEXT PRIMARY KEY,
  uid TEXT NOT NULL,
  expires_at INTEGER NOT NULL
);
