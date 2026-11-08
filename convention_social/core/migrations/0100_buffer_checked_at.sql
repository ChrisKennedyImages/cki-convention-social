-- Chris, 2026-11-08: "Buffer 24hr api was just reached". A post past its time that Buffer had neither sent nor failed
-- was asked about on every ten-minute run (post 70's LinkedIn part, due 2026-11-06 14:00 UTC, two requests a run),
-- which kept the suite at its 24-hour Buffer ceiling. buffer_checked_at: when the publisher last asked Buffer about
-- this row, so a late post is asked about hourly, then every six hours (agents/publisher.verify_scheduled).
ALTER TABLE content_queue ADD COLUMN buffer_checked_at TEXT;
