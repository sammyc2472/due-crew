-- 3.7.6: a plan's team and sharing my progress are one choice. Joining the
-- team shares my progress counts with its authors; leaving stops both.
-- Team members share from now on. Followers who shared without being on
-- the team (the old box was ticked by default) are asked once on the plan
-- card (team_ask) and stop sharing until they join. Progress is kept either
-- way: it's mine, for my own views; only sharing puts it in anyone's counts.
ALTER TABLE plan_follows ADD COLUMN team_ask INTEGER NOT NULL DEFAULT 0;

UPDATE plan_follows SET share = 1
 WHERE share = 0 AND EXISTS (SELECT 1 FROM plan_team t WHERE t.plan = plan_follows.plan AND t.uid = plan_follows.uid);

UPDATE plan_follows SET share = 0, team_ask = 1
 WHERE share = 1 AND NOT EXISTS (SELECT 1 FROM plan_team t WHERE t.plan = plan_follows.plan AND t.uid = plan_follows.uid);
