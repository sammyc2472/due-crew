-- 3.2: plans as training, who knows this, the log. See docs/plans-design.md.

-- a follower's own schedule for a plan: {start?, days: [7], minutes}
ALTER TABLE plan_follows ADD COLUMN sched TEXT;

-- cards I have down, by note guid, in decks I share (never their text)
CREATE TABLE knows (
  uid TEXT NOT NULL,
  guid TEXT NOT NULL,
  PRIMARY KEY (uid, guid)
) WITHOUT ROWID;
CREATE INDEX knows_guid ON knows(guid);

-- a tip on a card, by its author; one per author per card, the latest
CREATE TABLE tips (
  guid TEXT NOT NULL,
  uid TEXT NOT NULL,
  text TEXT NOT NULL,
  at INTEGER NOT NULL,
  PRIMARY KEY (guid, uid)
) WITHOUT ROWID;
CREATE INDEX tips_uid ON tips(uid);

-- "This helped": who a tip helped, for ordering only; never shown as counts
CREATE TABLE tip_helped (
  guid TEXT NOT NULL,
  tip_uid TEXT NOT NULL,
  by_uid TEXT NOT NULL,
  PRIMARY KEY (guid, tip_uid, by_uid)
) WITHOUT ROWID;
CREATE INDEX tip_helped_by ON tip_helped(by_uid);
CREATE INDEX tip_helped_tip ON tip_helped(tip_uid);

-- my study log, only mine: {days: {date: [minutes, reviews, new, retention|null]}}
CREATE TABLE logs (
  uid TEXT PRIMARY KEY,
  json TEXT NOT NULL,
  at INTEGER NOT NULL
);
