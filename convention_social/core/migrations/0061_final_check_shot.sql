-- Chris, 2026-10-11: "it calls a stage shot a portrait which, never can happen!" The local sorter's
-- shot type is a guess; Claude's final check, which already looks at every photo picked for a post,
-- now says what the photo shows, and that word is the one every caption and label uses.
ALTER TABLE final_checks ADD COLUMN shot_type TEXT;
