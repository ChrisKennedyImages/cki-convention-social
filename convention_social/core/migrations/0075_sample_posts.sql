-- 2026-10-15: Post this on a design sample (agents/sample.py). Each press is one row: the samples folder, the design,
-- the photo ids the sample was made from (the hero first), and whether it was drafted and why not. The draft itself
-- takes the daily draft's road (agents/content.make_draft) and lands in content_queue like any other.
CREATE TABLE IF NOT EXISTS sample_posts (
    id         INTEGER PRIMARY KEY,
    folder     TEXT NOT NULL,
    design     TEXT NOT NULL,
    photo_ids  TEXT NOT NULL DEFAULT '[]',
    status     TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'drafting', 'drafted', 'failed')),
    queue_id   INTEGER,
    error      TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sample_posts_folder ON sample_posts (folder, design, id);
