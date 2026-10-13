-- 3.8.1 (the audit): a report went only by mail, and with REPORT_TO unset it went
-- nowhere while the reporter was told it was sent. Each one is now kept for the
-- admin's Inbox (and still mailed when REPORT_TO is set): who reported whom or which
-- plan, the reason, the note, and what came with it (their last cheer to me, or the
-- plan's name and link). Kept 180 days; a report goes with either person's account.
CREATE TABLE reports (
  id TEXT PRIMARY KEY,
  by_uid TEXT NOT NULL,
  kind TEXT NOT NULL,
  target TEXT NOT NULL,
  reason TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  detail TEXT NOT NULL DEFAULT '',
  at INTEGER NOT NULL,
  done INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX reports_open ON reports (done, at);
CREATE INDEX reports_by ON reports (by_uid);
CREATE INDEX reports_target ON reports (target);
