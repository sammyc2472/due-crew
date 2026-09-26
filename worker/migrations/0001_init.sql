-- Due Crew 3.0: everything the Firestore rules used to guard, as tables.
-- Keys are text everywhere (uids, guids, deck fingerprints).
-- Lookups by users.email, members.squad, cheers.to_uid and knocks.to_uid
-- ride the UNIQUE constraint and the primary keys (their first column), so
-- they need no index of their own; each extra index is a write per row.

CREATE TABLE users (
  uid TEXT PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  name TEXT,
  emoji TEXT,
  client_version TEXT,
  tz TEXT,
  rollover INTEGER,
  last_seen INTEGER,
  code TEXT,
  created_at INTEGER NOT NULL
);

CREATE TABLE sessions (
  token_hash TEXT PRIMARY KEY,
  uid TEXT NOT NULL,
  device TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL,
  last_used INTEGER NOT NULL
);
CREATE INDEX sessions_uid ON sessions(uid);

CREATE TABLE otp (
  email TEXT PRIMARY KEY,
  code_hash TEXT NOT NULL,
  expires_at INTEGER NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE limits (
  key TEXT PRIMARY KEY,
  count INTEGER NOT NULL,
  window_start INTEGER NOT NULL
);

CREATE TABLE friends (
  owner TEXT NOT NULL,
  friend TEXT NOT NULL,
  at INTEGER NOT NULL,
  PRIMARY KEY (owner, friend)
);
CREATE INDEX friends_friend ON friends(friend);

CREATE TABLE weeks (uid TEXT PRIMARY KEY, doc TEXT NOT NULL, updated_at INTEGER NOT NULL);
CREATE TABLE decks (uid TEXT PRIMARY KEY, json TEXT NOT NULL);
CREATE TABLE heatmaps (uid TEXT PRIMARY KEY, json TEXT NOT NULL);

CREATE TABLE cheers (
  to_uid TEXT NOT NULL,
  from_uid TEXT NOT NULL,
  emoji TEXT NOT NULL,
  note TEXT,
  luck INTEGER,
  guid TEXT,
  at INTEGER NOT NULL,
  PRIMARY KEY (to_uid, from_uid)
);

CREATE TABLE knocks (
  to_uid TEXT NOT NULL,
  from_uid TEXT NOT NULL,
  squad TEXT,
  at INTEGER NOT NULL,
  PRIMARY KEY (to_uid, from_uid)
);

CREATE TABLE squads (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  founder TEXT NOT NULL,
  open INTEGER NOT NULL DEFAULT 1,
  created_at INTEGER NOT NULL
);

CREATE TABLE members (
  squad TEXT NOT NULL,
  uid TEXT NOT NULL,
  name TEXT NOT NULL,
  joined_at INTEGER NOT NULL,
  day TEXT,
  reviews INTEGER,
  study_time_ms INTEGER,
  accuracy REAL,
  streak INTEGER,
  week INTEGER,
  emoji TEXT,
  new_cards INTEGER,
  updated_at INTEGER,
  PRIMARY KEY (squad, uid)
);

CREATE TABLE bans (squad TEXT NOT NULL, uid TEXT NOT NULL, PRIMARY KEY (squad, uid));

CREATE TABLE settings (uid TEXT PRIMARY KEY, v INTEGER NOT NULL, at TEXT NOT NULL, json TEXT NOT NULL);

CREATE TABLE codes (code TEXT PRIMARY KEY, uid TEXT NOT NULL);
CREATE INDEX codes_uid ON codes(uid);
