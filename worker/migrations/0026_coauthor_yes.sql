-- 3.8.1: a co-author says yes first, and a plan can be handed over.
-- A plan_editors row is an invite until its co-author says yes
-- (accepted_at); until then they write nothing, tag nothing in Anki, and
-- aren't listed as a co-author but to the plan's authors. Everyone who is a
-- co-author now said yes when they were added.
ALTER TABLE plan_editors ADD COLUMN accepted_at INTEGER;
UPDATE plan_editors SET accepted_at = at;
-- The co-author the owner offered the plan to (their uid), or NULL. On a
-- yes they're its owner and the owner a co-author; the code, the tag root
-- and the followers stay.
ALTER TABLE plans ADD COLUMN handover TEXT;
-- the day's first board asks "offered to me?": by this index, not every plan
CREATE INDEX plans_handover ON plans(handover) WHERE handover IS NOT NULL;
