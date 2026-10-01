-- 3.6.5, P6: Send feedback, from the add-on and the site, to /admin.
-- The text, who sent it and from which version; kept a year, and deleted
-- with the account. Replies go by mail from Due Crew; the address isn't kept here.
CREATE TABLE feedback (
  id TEXT PRIMARY KEY,
  uid TEXT NOT NULL,
  at INTEGER NOT NULL,
  text TEXT NOT NULL,
  ver TEXT NOT NULL DEFAULT '',
  done INTEGER NOT NULL DEFAULT 0,
  replied INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX feedback_open ON feedback (done, at);
CREATE INDEX feedback_uid ON feedback (uid, at);
