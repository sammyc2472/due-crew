-- 3.9.9, Know when it breaks (Sam's sign-off): what went wrong in the add-on,
-- by code, never by content (save:bad_plan, py:plan_flow:maybe_morning:keyerror,
-- req:plans.:id:400). Each install counts its own and sends a day's counts
-- once, with the first sync after that day ends (its Anki day). Kept here only
-- added up: a day, a version and a code, how many times (n) and how many
-- people sent it (people: a person sends a day once). No uid. Kept 30 days
-- (housekeeping). The number 0030 was written once for 3.9.5's starter plans,
-- which never shipped (docs/history.md); this is the first 0030 to ship.
CREATE TABLE field_errs (
  day TEXT NOT NULL,
  version TEXT NOT NULL,
  code TEXT NOT NULL,
  n INTEGER NOT NULL,
  people INTEGER NOT NULL,
  PRIMARY KEY (day, version, code)
) WITHOUT ROWID;
