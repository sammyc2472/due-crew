-- Quiet accounts ("The next round", Q1-Q6): an account with no activity
-- for 12 months (24 when paused) is deleted by the daily job. This keeps
-- only a one-way hash of each such uid, for a year, so an add-on that
-- comes back can say why it was signed out. Nothing else about them.
CREATE TABLE gone (
  h TEXT PRIMARY KEY,
  at INTEGER NOT NULL
);
CREATE INDEX gone_at ON gone (at);
