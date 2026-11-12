-- 3.9.10: the board's "I'm studying" button went (the studying dot shows by itself, an hour after a
-- person's last review), so the squad's middle square that counted presses of it can't be earned by
-- a press. Its key (lv) stays: the add-on counts it the first time in a day a person studies while a
-- crewmate is studying. Only its words change, and only where the admin hasn't rewritten them.
UPDATE bingo_pool SET json = '{"group":"crew","icon":"🟢","name":"Studying together","rule":"A quarter of you study while a crewmate is","detail":"A quarter of you (at least 2) study while someone in your crew is studying this week.","type":"people","params":{"key":"lv"},"goal":"quarter","unit":"did"}' WHERE id = 'buddy' AND updated_at = 0;
