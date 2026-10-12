-- Chris, 2026-10-12: "Portraits and headshots are the same". One shot type from here on; what the
-- sorter and the final check had called a headshot is a portrait.
UPDATE classifications SET shot_type = 'portrait' WHERE shot_type = 'headshot';
UPDATE final_checks SET shot_type = 'portrait' WHERE shot_type = 'headshot';
