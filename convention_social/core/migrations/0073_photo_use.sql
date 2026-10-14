-- 2026-10-14: every surface spreads across the whole approved pool, least recently used first (Chris: "you keep
-- using the same photos for everything when I have approved at least 40 by now"). One row per photo per use;
-- `surface` says where (a post draft, a site build, the design samples) and `ref` which one, so a draft that is
-- undone (a shot word corrected) can give its photos back. library/report.py rotate() reads it, record_use()
-- writes it; drafts made before this table existed are filled in once from content_queue (ensure_use_history).
CREATE TABLE IF NOT EXISTS photo_use (
    id        INTEGER PRIMARY KEY,
    photo_id  INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    surface   TEXT NOT NULL CHECK (surface IN ('post', 'site', 'sample')),
    ref       TEXT NOT NULL DEFAULT '',
    used_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_photo_use_photo ON photo_use (photo_id, used_at);
CREATE INDEX IF NOT EXISTS idx_photo_use_ref ON photo_use (ref);
