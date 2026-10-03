-- 3.7.1: how many cheers my crew sent me, by year, for my own year card.
-- Received only (never sent), seen only by me, deleted with my account.
-- A sender's cheers count once a day: a run of them is one.
CREATE TABLE cheer_counts (
  uid TEXT NOT NULL,
  year INTEGER NOT NULL,
  n INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (uid, year)
);
