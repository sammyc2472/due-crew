-- 3.5, X: the admin's history, counts only (never who). One row per count
-- per day: the daily cron writes a snapshot of /admin/stats's counts, and
-- sign-in steps and the bridge's runs add to today's counters.
CREATE TABLE admin_days (
  day TEXT NOT NULL,
  key TEXT NOT NULL,
  n INTEGER NOT NULL,
  PRIMARY KEY (day, key)
);
-- the 2.x bridge's last run: when, how long, how many each way, the first
-- line of its error when it failed
CREATE TABLE bridge_last (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  at INTEGER NOT NULL,
  ms INTEGER NOT NULL,
  pulled INTEGER NOT NULL,
  pushed INTEGER NOT NULL,
  error TEXT
);
-- a notice taken down keeps its row (the admin's list of past notices)
ALTER TABLE notices ADD COLUMN taken_at INTEGER;
-- 3.5, L: my plan's history for my log, {date: [opened, seen]}, the last
-- 120 days, kept when my progress changes; mine only
ALTER TABLE plan_follows ADD COLUMN hist TEXT;
