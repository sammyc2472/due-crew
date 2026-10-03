-- The admin's tools (mock "Admin, grown up", A3–A5).
--
-- What the admin did, kept a year: the action, whose account or which
-- squad, and a short detail that never holds an email, a code or a token.
-- Names are looked up when the log is read, so a deleted account's rows
-- read "a deleted account".
CREATE TABLE admin_actions (
  id TEXT PRIMARY KEY,
  at INTEGER NOT NULL,
  action TEXT NOT NULL,
  uid TEXT,
  squad TEXT,
  detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX admin_actions_at ON admin_actions (at);
CREATE INDEX admin_actions_uid ON admin_actions (uid, at);
CREATE INDEX admin_actions_squad ON admin_actions (squad, at);

-- The admin's own note on an account; deleted with the account.
CREATE TABLE admin_notes (
  uid TEXT PRIMARY KEY,
  text TEXT NOT NULL,
  at INTEGER NOT NULL
);

-- An email change the admin started: it happens the first time someone
-- signs in with a code at the new address, so a typo never hands an
-- account to a stranger's inbox. A week, then it lapses.
CREATE TABLE email_changes (
  uid TEXT PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  at INTEGER NOT NULL
);

-- A squad's new code. A squad's id comes from its first code; a new code is
-- a row here (the new code's hash → the squad), and code_id on the squad
-- says which code is live, so the old one stops working and the id, which
-- every add-on and the 2.x bridge know, never changes.
CREATE TABLE squad_codes (
  code_id TEXT PRIMARY KEY,
  squad TEXT NOT NULL
);
CREATE INDEX squad_codes_squad ON squad_codes (squad);
ALTER TABLE squads ADD COLUMN code_id TEXT;
