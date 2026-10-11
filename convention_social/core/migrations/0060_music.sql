-- Music for the reels (Chris, 2026-10-11: "we need to find good music"). A track is used only with
-- its record complete: where Chris got it and what that source allows. No record, no music.
CREATE TABLE IF NOT EXISTS music_tracks (
    id          INTEGER PRIMARY KEY,
    file        TEXT NOT NULL UNIQUE,         -- a name inside DATA_ROOT/music
    title       TEXT NOT NULL,
    artist      TEXT NOT NULL,
    source      TEXT NOT NULL,                -- a link, or the library it came from
    terms       TEXT NOT NULL,                -- what that source allows, in Chris's words
    added_at    TEXT NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1
);
