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
