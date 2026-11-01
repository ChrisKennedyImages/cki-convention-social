-- 2026-11-01, Chris: "I would rather them all just be converted to drafts and the events need to be at least 3 months out."
-- Every scouted event three months or more out becomes a draft once a person's address and its dates are read off its own
-- site (outreach/emails.py, outreach/dates.py).
-- person_looked_at: when the site was walked for a person's address (the walk of 2026-11-01). An event that holds only a
--   shared inbox (info@, register@) or no address, read by the earlier walk, is walked once more, then never again.
-- dates_checked_at, dates_note: when its dates were read off its own page (one small Claude read, once), and what the page
--   said ('read off <page>: "<the words>"') or why there are none.
ALTER TABLE scout_events ADD COLUMN person_looked_at TEXT;
ALTER TABLE scout_events ADD COLUMN dates_checked_at TEXT;
ALTER TABLE scout_events ADD COLUMN dates_note TEXT;
