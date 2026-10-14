-- 2026-10-14: a photo from Chris's phone while he is shooting becomes a draft post (agents/phone.py). `source`
-- tells the weekly Drive pass which photos are Drive's: only those are marked trashed when Drive no longer lists
-- them. phone_sends is the page's record of each send: his line about it, whether it was drafted, and why not.
ALTER TABLE photos ADD COLUMN source TEXT NOT NULL DEFAULT 'drive';
CREATE TABLE IF NOT EXISTS phone_sends (
    id         INTEGER PRIMARY KEY,
    photo_id   INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    note       TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'drafting', 'drafted', 'failed')),
    queue_id   INTEGER,
    error      TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
