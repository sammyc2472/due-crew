-- 3.9.1, doodle cheers (Sam's pick): a cheer can carry a little drawing (its
-- strokes, as numbers) or a few words for the sender's Pip to hold up, kept
-- as canonical JSON by validate.doodle. Null for every cheer before it, and
-- for a tip or a good-luck line, which never carry one.
ALTER TABLE cheers ADD COLUMN doodle TEXT;
