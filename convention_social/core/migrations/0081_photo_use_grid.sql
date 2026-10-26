-- 2026-10-26: the wall of approved photos around a reel's own counts as a use ("grid"), so the next reel's wall
-- reaches for other photos (Chris: "it keeps posting the same photos again"; the strongest 28 had stood on every
-- reel's wall). SQLite cannot widen a CHECK in place, so the table is rebuilt with its rows.
CREATE TABLE photo_use_new (
    id        INTEGER PRIMARY KEY,
    photo_id  INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    surface   TEXT NOT NULL CHECK (surface IN ('post', 'site', 'sample', 'grid')),
    ref       TEXT NOT NULL DEFAULT '',
    used_at   TEXT NOT NULL
);
INSERT INTO photo_use_new (id, photo_id, surface, ref, used_at) SELECT id, photo_id, surface, ref, used_at FROM photo_use;
DROP TABLE photo_use;
ALTER TABLE photo_use_new RENAME TO photo_use;
CREATE INDEX IF NOT EXISTS idx_photo_use_photo ON photo_use (photo_id, used_at);
CREATE INDEX IF NOT EXISTS idx_photo_use_ref ON photo_use (ref);
