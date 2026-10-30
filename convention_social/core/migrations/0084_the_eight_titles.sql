-- 2026-10-29, Chris: "It's only one of these: main stage, stage panel, stage, breakout, portrait, backstage, candid (if
-- you can't identify where) and reception! Stop calling a single face in a frame a portrait!" One vocabulary from
-- here: the sorter's shot type, the final check's room and the title on a post are the same word. What is already
-- sorted maps where the old word was plain; "portrait" and "group" (3,815 and 2,452 from the local model, 570 and
-- 293 from Claude) lose their label and are marked for the sorter to judge again under the strict rule (rejudge;
-- classify.queue takes them like unsorted photos, cleared folders first). The costume rule leaves the shot-type list
-- and becomes its own answer.
ALTER TABLE classifications ADD COLUMN costume INTEGER;
ALTER TABLE classifications ADD COLUMN rejudge INTEGER NOT NULL DEFAULT 0;
UPDATE classifications SET rejudge = 1 WHERE shot_type IN ('portrait', 'group');
UPDATE classifications SET costume = 1 WHERE shot_type = 'cosplay_portrait';
UPDATE classifications SET shot_type = CASE shot_type
    WHEN 'dinner_reception' THEN 'reception'
    WHEN 'cosplay_portrait' THEN 'candid'
    WHEN 'crowd' THEN 'candid' WHEN 'vendor_hall' THEN 'candid' WHEN 'venue' THEN 'candid' WHEN 'other' THEN 'candid'
    WHEN 'portrait' THEN NULL WHEN 'group' THEN NULL
    ELSE shot_type END
 WHERE shot_type IS NOT NULL;
UPDATE final_checks SET shot_type = CASE shot_type
    WHEN 'dinner_reception' THEN 'reception' WHEN 'cosplay_portrait' THEN 'candid'
    WHEN 'crowd' THEN 'candid' WHEN 'vendor_hall' THEN 'candid' WHEN 'venue' THEN 'candid' WHEN 'other' THEN 'candid'
    WHEN 'portrait' THEN NULL WHEN 'group' THEN NULL
    ELSE shot_type END
 WHERE shot_type IS NOT NULL;
UPDATE final_checks SET room = CASE room
    WHEN 'after_dark' THEN 'reception' WHEN 'the_crowd' THEN 'candid' WHEN 'expo_floor' THEN 'candid'
    WHEN 'portraits' THEN 'portrait' WHEN 'the_venue' THEN NULL
    ELSE room END
 WHERE room IS NOT NULL;
