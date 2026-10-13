-- Chris, 2026-10-13: the scout armed, around Washington DC (DC, Maryland and Virginia). It searches by
-- itself (one research call a week, about a dollar, inside the monthly cap); organizer notes still leave
-- only on his Approve, and the outreach lane stays in dry run until he switches it on the Agents page.
INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES ('scout.dry_run', 'false', strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'));
