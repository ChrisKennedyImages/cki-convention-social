-- 2026-10-14: galleries shared with Chris (his brothers' Drives) are scanned like his own folders;
-- who shared each one is shown, a name only, never an address.
ALTER TABLE drive_folders ADD COLUMN shared_by TEXT;
