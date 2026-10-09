-- 0030: what the learner suggested, search text for photos, and the weekly site check.
-- Everything here is internal: nothing in these tables leaves the Mini on its own.

-- One row per learner run: what it saw, what it suggested, whether it was applied.
-- status 'suggested' (dry run, not applied) | 'applied' (live; pacing and the picker read it).
CREATE TABLE IF NOT EXISTS learner_history (
    id          INTEGER PRIMARY KEY,
    created_at  TEXT NOT NULL,
    run_id      INTEGER,
    status      TEXT NOT NULL CHECK (status IN ('suggested', 'applied')),
    applied     INTEGER NOT NULL DEFAULT 0,
    posts_seen  INTEGER NOT NULL DEFAULT 0,
    note        TEXT NOT NULL,
    times       TEXT NOT NULL DEFAULT '{}',          -- JSON {network: {weekday, weekend, ...}}
    weights     TEXT NOT NULL DEFAULT '{}',          -- JSON {shot_type: {..}, event_kind: {..}}
    detail      TEXT NOT NULL DEFAULT '{}'           -- JSON: the numbers behind the note
);
CREATE INDEX IF NOT EXISTS idx_learner_history_created ON learner_history (created_at);

-- Search text for a photo: the website, the sitemap and post alt text read it.
-- model: 'template' or the Claude model that answered. edited_at is set when Chris
-- corrects the text on the dashboard; the agent never rewrites a row after that.
CREATE TABLE IF NOT EXISTS photo_seo (
    photo_id    INTEGER PRIMARY KEY REFERENCES photos(id) ON DELETE CASCADE,
    slug        TEXT NOT NULL UNIQUE,
    title       TEXT NOT NULL,
    alt         TEXT NOT NULL,
    description TEXT NOT NULL,
    keywords    TEXT NOT NULL DEFAULT '[]',          -- JSON list of 5 to 10 phrases
    model       TEXT NOT NULL,
    written_at  TEXT NOT NULL,
    edited_at   TEXT
);

-- The weekly read-only look at the public site, one row per page per run.
-- The *_ok columns are NULL where they do not apply (sitemap.xml, robots.txt).
CREATE TABLE IF NOT EXISTS site_checks (
    id              INTEGER PRIMARY KEY,
    run_id          INTEGER,
    checked_at      TEXT NOT NULL,
    path            TEXT NOT NULL,
    url             TEXT NOT NULL,
    status_code     INTEGER,
    ok              INTEGER NOT NULL DEFAULT 0,
    title_ok        INTEGER,
    description_ok  INTEGER,
    h1_ok           INTEGER,
    alt_ok          INTEGER,
    problems        TEXT NOT NULL DEFAULT '[]'       -- JSON list, plain words
);
CREATE INDEX IF NOT EXISTS idx_site_checks_checked ON site_checks (checked_at);
