-- 3.6.1: a medium or hard square is now a streak when its family has one
-- (the draw's choice, no pool change), and a share counts everyone
-- studying, older add-ons too. The middle no longer asks you to ask the
-- crew about a card. This week's card is drawn again under these rules.

UPDATE bingo_pool SET enabled = 0 WHERE id = 'ask';

-- a streak for every family at medium and hard, so those squares always are
INSERT INTO bingo_pool (id, kind, json, enabled, updated_at) VALUES ('sampm3', 'square', '{"fam":"spread","diff":"h","icon":"🌓","title":"Both ends","rule":"Before noon and after 6, 3 days in a row","detail":"A review before 12:00 and another after 18:00 on the same day, three days in a row.","type":"parts","params":{"parts":[[0,12],[18,24]],"days":3,"row":true},"team":true}', 1, 0) ON CONFLICT(id) DO NOTHING;
INSERT INTO bingo_pool (id, kind, json, enabled, updated_at) VALUES ('f40x3', 'square', '{"fam":"focus","diff":"h","icon":"🎧","title":"Deep work","rule":"40 minutes, no break, 3 days in a row","detail":"A 40-minute stretch without a 5-minute gap, three days in a row.","type":"focus","params":{"minutes":40,"gap":5,"days":3,"row":true},"team":true}', 1, 0) ON CONFLICT(id) DO NOTHING;
-- more than the day before, days running, pays for a small first day:
-- volume streaks are against my own usual instead, where more is better
UPDATE bingo_pool SET enabled = 0 WHERE id = 'vup3';
INSERT INTO bingo_pool (id, kind, json, enabled, updated_at) VALUES ('vus3', 'square', '{"fam":"volume","diff":"m","icon":"📶","title":"Steady","rule":"Your usual day, 3 days in a row","detail":"At least as many reviews as your usual day (your average over the days you studied in the last 30), three days in a row.","type":"rel","params":{"x":1,"days":3,"row":true},"team":true}', 1, 0) ON CONFLICT(id) DO NOTHING;
INSERT INTO bingo_pool (id, kind, json, enabled, updated_at) VALUES ('vbig2', 'square', '{"fam":"volume","diff":"h","icon":"🚀","title":"Big back to back","rule":"1.3× your usual, 2 days in a row","detail":"At least 1.3 times your usual day of reviews, two days in a row.","type":"rel","params":{"x":1.3,"days":2,"row":true},"team":true}', 1, 0) ON CONFLICT(id) DO NOTHING;
INSERT INTO bingo_pool (id, kind, json, enabled, updated_at) VALUES ('o5row', 'square', '{"fam":"often","diff":"h","icon":"⛓️","title":"Five in a row","rule":"Study 5 days in a row","detail":"At least one review on five days in a row.","type":"days","params":{"days":5,"row":true},"team":true}', 1, 0) ON CONFLICT(id) DO NOTHING;

-- the middle says what; the number under it says how many of you (a
-- share reads oddly in a small squad)
UPDATE bingo_pool SET json = json_set(json, '$.rule', 'Before 8am, together on one day') WHERE id = 'dawn' AND updated_at = 0;
UPDATE bingo_pool SET json = json_set(json, '$.rule', 'Due zero, a few of you') WHERE id = 'clean' AND updated_at = 0;
UPDATE bingo_pool SET json = json_set(json, '$.rule', 'Send a cheer') WHERE id = 'hi' AND updated_at = 0;
UPDATE bingo_pool SET json = json_set(json, '$.rule', 'Join a study room') WHERE id = 'room' AND updated_at = 0;
UPDATE bingo_pool SET json = json_set(json, '$.rule', 'Turn on I''m studying') WHERE id = 'buddy' AND updated_at = 0;
UPDATE bingo_pool SET json = json_set(json, '$.rule', 'Write a tip on a card') WHERE id = 'tip' AND updated_at = 0;
UPDATE bingo_pool SET json = json_set(json, '$.rule', 'Share a deck') WHERE id = 'deck' AND updated_at = 0;
UPDATE bingo_pool SET json = json_set(json, '$.rule', 'Set a status') WHERE id = 'status' AND updated_at = 0;
UPDATE bingo_pool SET json = json_set(json, '$.rule', 'After 10pm, together on one night') WHERE id = 'spooky' AND updated_at = 0;

DELETE FROM bingo_cards;
