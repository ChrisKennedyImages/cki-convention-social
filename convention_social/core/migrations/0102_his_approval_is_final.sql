-- 2026-11-08, Chris: "NOTHING IS PRIVATE because I have hand approved every photo! No one can override MY approvals and
-- that is a law"; then "Yes, override everything". Nothing reads these columns now. The LinkedIn logo skip of 2026-11-01
-- is gone with its judgement (photos.prominent_logo, prominent_logo_at). The final check's readable details and kind of
-- occasion are labels kept where they are read (classifications.personal_details and event_kind; the hero's card keeps
-- its own), never vetoes, so final_checks keeps its summary, its label and its room only. SQLite drops a column in place
-- from 3.35 (the Mini's Python links 3.53.1, read on 2026-11-09); no index or trigger names them.
ALTER TABLE photos DROP COLUMN prominent_logo;
ALTER TABLE photos DROP COLUMN prominent_logo_at;
ALTER TABLE final_checks DROP COLUMN personal_details;
ALTER TABLE final_checks DROP COLUMN event_kind;
