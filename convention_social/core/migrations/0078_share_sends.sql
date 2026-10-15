-- 2026-10-15: Post to Event Caliber, the iPhone's share sheet (agents/phone.py pull). `via` says where a send came from:
-- 'page' (the Send a photo page, waits for his Approve) or 'share' (the share sheet, approved by the act of sending).
-- `remote_id` is the send's name at eventcaliber.com (private/sends/<id> in R2), so a send kept before its delete at
-- the site went through is never kept twice.
ALTER TABLE phone_sends ADD COLUMN via TEXT NOT NULL DEFAULT 'page';
ALTER TABLE phone_sends ADD COLUMN remote_id TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_phone_sends_remote ON phone_sends (remote_id) WHERE remote_id IS NOT NULL;
