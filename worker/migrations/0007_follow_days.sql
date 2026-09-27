-- G3, G4: a follower's own days. `shift`: how many days my dates run later
-- than the plan's (pushed back, or back from a pause); `pause_until` and
-- `pause_since`: a pause with an end; `skipped`: the dates I skip, a JSON
-- array of unit ids. Mine only; the plan never changes.
ALTER TABLE plan_follows ADD COLUMN shift INTEGER NOT NULL DEFAULT 0;
ALTER TABLE plan_follows ADD COLUMN pause_until TEXT;
ALTER TABLE plan_follows ADD COLUMN pause_since TEXT;
ALTER TABLE plan_follows ADD COLUMN skipped TEXT;
