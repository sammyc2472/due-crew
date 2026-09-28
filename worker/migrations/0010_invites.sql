-- 3.4.1: a one-time invite. Copy invite makes one; whoever redeems it is
-- crew with the one who made it, both edges at once (sending the link is
-- their yes). Single use, 14 days, and only its hash is kept.
CREATE TABLE invites (
  hash TEXT PRIMARY KEY,
  uid TEXT NOT NULL,
  expires_at INTEGER NOT NULL,
  used_by TEXT,
  used_at INTEGER
);
CREATE INDEX invites_uid ON invites (uid);
