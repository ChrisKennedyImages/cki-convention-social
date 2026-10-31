-- 2026-10-30, Chris: "I haven't received one email to send. Not one outreach email has been sent." The scout's eight
-- events had no organizer email, so nothing was drafted. outreach/emails.py now reads an address off the event's own
-- website; each event is looked at once and the result, or the reason there is none, is kept on the row.
ALTER TABLE scout_events ADD COLUMN email_checked_at TEXT;
ALTER TABLE scout_events ADD COLUMN email_note TEXT;
