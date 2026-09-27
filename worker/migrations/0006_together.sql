-- 3.3: plans together. Co-authors (they edit; the owner alone deletes the
-- plan, picks who can follow, and adds or removes co-authors), notes on a
-- day from anyone in the plan, and the last 30 saves with what each
-- replaced, so the latest can be undone.
CREATE TABLE plan_editors (
  plan TEXT NOT NULL,
  uid TEXT NOT NULL,
  at INTEGER NOT NULL,
  PRIMARY KEY (plan, uid)
);
CREATE INDEX plan_editors_uid ON plan_editors(uid);

CREATE TABLE plan_notes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  plan TEXT NOT NULL,
  uid TEXT NOT NULL,
  day TEXT NOT NULL,
  text TEXT NOT NULL,
  at INTEGER NOT NULL
);
CREATE INDEX plan_notes_plan ON plan_notes(plan, day);
CREATE INDEX plan_notes_uid ON plan_notes(uid);

CREATE TABLE plan_log (
  plan TEXT NOT NULL,
  version INTEGER NOT NULL,
  uid TEXT NOT NULL,
  at INTEGER NOT NULL,
  summary TEXT NOT NULL,
  prev TEXT,
  PRIMARY KEY (plan, version)
);

-- 3.3, C2: open each date this many days early (for studying on a phone)
ALTER TABLE plan_follows ADD COLUMN early INTEGER NOT NULL DEFAULT 0;
