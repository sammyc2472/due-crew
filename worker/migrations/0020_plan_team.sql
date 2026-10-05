-- 3.7.3 a plan's team: followers and authors who join (opt-in, per plan).
-- The team sees who showed up today (days: the last 60 Anki days I
-- answered one of the plan's cards), the questions asked of it, and its
-- bingo card (play: my squares, from the plan's cards only). Never numbers.
CREATE TABLE plan_team (
  plan TEXT NOT NULL,
  uid TEXT NOT NULL,
  joined_at INTEGER NOT NULL,
  days TEXT,
  last_day TEXT,
  play TEXT,
  PRIMARY KEY (plan, uid)
);
CREATE INDEX plan_team_uid ON plan_team (uid);

-- Questions to the team, and one level of replies (parent). A card question
-- carries the card as note guid + card number and a topic name, never its
-- text; each reader's Anki finds the card in its own copy.
CREATE TABLE plan_asks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  plan TEXT NOT NULL,
  uid TEXT NOT NULL,
  parent INTEGER,
  text TEXT NOT NULL,
  guid TEXT,
  ord INTEGER,
  topic TEXT,
  helped INTEGER NOT NULL DEFAULT 0,
  at INTEGER NOT NULL,
  act INTEGER NOT NULL,
  act_by TEXT
);
CREATE INDEX plan_asks_plan ON plan_asks (plan, parent, act);
CREATE INDEX plan_asks_parent ON plan_asks (parent);
CREATE INDEX plan_asks_uid ON plan_asks (uid);
