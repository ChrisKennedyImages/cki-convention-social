-- 2026-10-30, Chris: on a stage it is "Main Stage and stage panel (both)". The five photos the new sorter had called
-- "stage" (one speaker, any stage) are main_stage; the 3,621 old "stage panel" photos, a word that once meant anyone on a
-- stage, lose the label and are marked for the second look so the panels are told from the main stage (about $18 at
-- the measured half a cent).
UPDATE classifications SET shot_type = 'main_stage' WHERE shot_type = 'stage';
UPDATE final_checks SET shot_type = 'main_stage' WHERE shot_type = 'stage';
UPDATE final_checks SET room = 'main_stage' WHERE room = 'stage';
UPDATE classifications SET shot_type = NULL, rejudge = 1 WHERE shot_type = 'stage_panel';
