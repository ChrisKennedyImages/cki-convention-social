-- D1 schema for the eventcaliber.com Worker. Apply once:
--   wrangler d1 execute eventcaliber-booking --remote --file worker/schema.sql
CREATE TABLE IF NOT EXISTS quote_requests (
  id TEXT PRIMARY KEY,
  received_at TEXT NOT NULL,
  ip TEXT,
  body TEXT NOT NULL          -- JSON of the form; deleted once the Mini has it
);
CREATE INDEX IF NOT EXISTS idx_quote_requests_ip ON quote_requests (ip, received_at);
CREATE TABLE IF NOT EXISTS booked_days (
  day TEXT PRIMARY KEY        -- YYYY-MM-DD, nothing else: no names, no events
);
-- Opt-outs from outreach emails: the random token from the email's link, never the address.
-- Deleted once the Mini has pulled them and put the address on its do-not-contact list.
CREATE TABLE IF NOT EXISTS unsubscribes (
  token TEXT PRIMARY KEY,     -- 32 hex characters
  received_at TEXT NOT NULL,
  ip TEXT                     -- for the hourly limit only
);
CREATE INDEX IF NOT EXISTS idx_unsubscribes_ip ON unsubscribes (ip, received_at);
