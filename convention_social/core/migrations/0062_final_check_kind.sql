-- Chris, 2026-10-11: "the main photo when you open the website is from a damn wedding!" The local sorter
-- called a wedding an event. Claude's final check now says what kind of occasion the photo is from, and
-- a wedding or a private occasion is never used.
ALTER TABLE final_checks ADD COLUMN event_kind TEXT;
