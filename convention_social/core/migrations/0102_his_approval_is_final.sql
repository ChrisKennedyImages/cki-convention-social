-- 2026-11-08, Chris: "NOTHING IS PRIVATE because I have hand approved every photo! No one can override MY approvals and
-- that is a law"; then "Yes, override everything". Nothing reads these columns now. The LinkedIn logo skip of 2026-11-01
-- is gone with its judgement (photos.prominent_logo, prominent_logo_at). The final check's readable details and kind of
-- occasion are labels, never vetoes: the kind is copied to classifications.event_kind, and the details are read off the
-- answer by the phone's own sort and the uploaded hero's card; final_checks keeps its summary, its label and its room. SQLite drops a column in place
-- from 3.35 (the Mini's Python links 3.53.1, read on 2026-11-09); no index or trigger names them.
-- one transaction: all four go, or none does
BEGIN;
ALTER TABLE photos DROP COLUMN prominent_logo;
ALTER TABLE photos DROP COLUMN prominent_logo_at;
ALTER TABLE final_checks DROP COLUMN personal_details;
ALTER TABLE final_checks DROP COLUMN event_kind;
COMMIT;
