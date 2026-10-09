-- 0001_init: the whole first schema. Timestamps are ISO-8601 UTC text.
-- People-safety rule written into the data: nothing is cleared by default.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT PRIMARY KEY,
    applied_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- ---------------------------------------------------------------- the library
-- Every Drive folder that holds at least one image (plus its ancestors).
-- clearance: not_cleared (default) | cleared | excluded. Only Chris changes it.
CREATE TABLE IF NOT EXISTS drive_folders (
    drive_id        TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    parent_id       TEXT,
    path            TEXT,                     -- "Top/Sub/Leaf", resolved at scan time
    modified_time   TEXT,
    image_count     INTEGER NOT NULL DEFAULT 0,
    clearance       TEXT NOT NULL DEFAULT 'not_cleared'
                    CHECK (clearance IN ('not_cleared', 'cleared', 'excluded')),
    clearance_at    TEXT,
    convention_id   INTEGER REFERENCES conventions(id) ON DELETE SET NULL,
    note            TEXT,
    first_seen_at   TEXT NOT NULL,
    last_seen_at    TEXT NOT NULL
);

-- One row per image file Drive can render. Nothing here is ever written back to Drive.
-- clearance: inherit (follow the folder) | cleared | blocked (per-photo override).
CREATE TABLE IF NOT EXISTS photos (
    id              INTEGER PRIMARY KEY,
    drive_id        TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    mime_type       TEXT,
    md5             TEXT,
    size_bytes      INTEGER,
    folder_id       TEXT REFERENCES drive_folders(drive_id) ON DELETE SET NULL,
    width           INTEGER,
    height          INTEGER,
    rotation        INTEGER,
    taken_at        TEXT,
    camera          TEXT,
    description     TEXT,                     -- the Drive file description, read only
    thumbnail_link  TEXT,
    modified_time   TEXT,
    trashed         INTEGER NOT NULL DEFAULT 0,
    clearance       TEXT NOT NULL DEFAULT 'inherit'
                    CHECK (clearance IN ('inherit', 'cleared', 'blocked')),
    clearance_at    TEXT,
    local_path      TEXT,                     -- full-size copy, only once chosen
    public_url      TEXT,
    first_seen_at   TEXT NOT NULL,
    last_seen_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_photos_folder ON photos (folder_id);
CREATE INDEX IF NOT EXISTS idx_photos_md5 ON photos (md5);

-- What the classifier decided, cached. possible_minor NULL means not yet
-- checked, and an unchecked photo is never eligible (fail closed).
CREATE TABLE IF NOT EXISTS classifications (
    photo_id         INTEGER PRIMARY KEY REFERENCES photos(id) ON DELETE CASCADE,
    method           TEXT NOT NULL,           -- folder | vision
    is_convention    INTEGER,                 -- 1 yes, 0 no, NULL unknown
    convention_name  TEXT,
    event_kind       TEXT,                    -- fan | business | unknown
    shot_type        TEXT,                    -- cosplay_portrait | portrait | group | candid | stage | vendor_hall | booth | backstage | dinner | other
    quality          INTEGER,                 -- 1..5 technical quality
    orientation      TEXT,                    -- portrait | landscape | square
    people_count     INTEGER,
    personal_details TEXT,                    -- JSON list: badge_name, plate, screen, document
    possible_minor   INTEGER,                 -- 1 maybe a minor, 0 confident none, NULL unchecked
    summary          TEXT,
    model            TEXT,
    classified_at    TEXT NOT NULL
);

-- Takedowns and anything Chris never wants used. Honoured everywhere.
CREATE TABLE IF NOT EXISTS do_not_use (
    id          INTEGER PRIMARY KEY,
    kind        TEXT NOT NULL CHECK (kind IN ('photo', 'folder', 'person', 'handle')),
    value       TEXT NOT NULL,                -- drive id, person name or @handle (lowercased)
    reason      TEXT,
    added_at    TEXT NOT NULL,
    UNIQUE (kind, value)
);

-- Credits and consent, read from Chris's sheet. One row per sheet row.
CREATE TABLE IF NOT EXISTS credits (
    id          INTEGER PRIMARY KEY,
    scope       TEXT NOT NULL CHECK (scope IN ('photo', 'folder')),
    drive_id    TEXT NOT NULL,                -- the photo's or folder's Drive id
    person_name TEXT,
    handle      TEXT,                         -- e.g. @name, credited as written
    consent     TEXT NOT NULL DEFAULT 'unknown' CHECK (consent IN ('yes', 'no', 'unknown')),
    sheet_row   INTEGER,
    synced_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_credits_ref ON credits (scope, drive_id);

-- ----------------------------------------------------------- the calendar
-- official = 1 only when Chris confirms the company is the event's photographer.
CREATE TABLE IF NOT EXISTS conventions (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'unknown' CHECK (kind IN ('fan', 'business', 'unknown')),
    start_date  TEXT,
    end_date    TEXT,
    city        TEXT,
    venue       TEXT,
    attending   INTEGER NOT NULL DEFAULT 0,
    official    INTEGER NOT NULL DEFAULT 0,
    url         TEXT,
    notes       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- ------------------------------------------------------------- publishing
CREATE TABLE IF NOT EXISTS channels (
    id                  INTEGER PRIMARY KEY,
    buffer_channel_id   TEXT NOT NULL UNIQUE,
    service             TEXT NOT NULL,        -- instagram | facebook | pinterest
    display_name        TEXT,
    connected           INTEGER NOT NULL DEFAULT 1,
    last_checked_at     TEXT
);

CREATE TABLE IF NOT EXISTS content_queue (
    id              INTEGER PRIMARY KEY,
    kind            TEXT NOT NULL CHECK (kind IN ('photo', 'appearance', 'booking', 'promo')),
    photo_ids       TEXT NOT NULL DEFAULT '[]',   -- JSON list of photos.id
    convention_id   INTEGER REFERENCES conventions(id) ON DELETE SET NULL,
    targets         TEXT NOT NULL,                -- JSON list of services
    caption         TEXT NOT NULL,                -- JSON {service: text}
    render_paths    TEXT,                         -- JSON {aspect: [path]}
    status          TEXT NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft', 'approved', 'rejected', 'would_publish',
                                      'scheduled', 'published', 'failed')),
    rule_report     TEXT,
    dry_run         INTEGER NOT NULL DEFAULT 1,
    buffer_post_ids TEXT,                         -- JSON {service: post_id}
    payload         TEXT,                         -- JSON of the exact Buffer payload (dry runs too)
    scheduled_for   TEXT,
    approved_at     TEXT,
    last_error      TEXT,
    published_at    TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS post_history (
    id                  INTEGER PRIMARY KEY,
    buffer_post_id      TEXT NOT NULL UNIQUE,
    queue_id            INTEGER REFERENCES content_queue(id) ON DELETE SET NULL,
    service             TEXT NOT NULL,
    sent_at             TEXT,
    caption             TEXT,
    metrics             TEXT,
    metrics_updated_at  TEXT
);

CREATE TABLE IF NOT EXISTS post_metrics (
    id                  INTEGER PRIMARY KEY,
    buffer_post_id      TEXT NOT NULL,
    service             TEXT,
    ours                INTEGER NOT NULL DEFAULT 0,
    sent_at             TEXT,
    text                TEXT,
    captured_on         TEXT NOT NULL,
    metrics             TEXT NOT NULL,
    metrics_updated_at  TEXT,
    UNIQUE (buffer_post_id, captured_on)
);

-- ------------------------------------------------------------- operations
CREATE TABLE IF NOT EXISTS api_usage (
    id          INTEGER PRIMARY KEY,
    ts          TEXT NOT NULL,
    provider    TEXT NOT NULL,                -- anthropic | buffer | drive | smtp
    agent       TEXT NOT NULL,
    units       REAL NOT NULL DEFAULT 1,
    unit_kind   TEXT,
    cost_usd    REAL NOT NULL DEFAULT 0,
    detail      TEXT
);
CREATE INDEX IF NOT EXISTS idx_api_usage_ts ON api_usage (provider, ts);

CREATE TABLE IF NOT EXISTS agent_runs (
    id          INTEGER PRIMARY KEY,
    agent       TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    ok          INTEGER,
    dry_run     INTEGER NOT NULL DEFAULT 1,
    summary     TEXT
);
CREATE INDEX IF NOT EXISTS idx_agent_runs_agent ON agent_runs (agent, started_at);

CREATE TABLE IF NOT EXISTS errors (
    id          INTEGER PRIMARY KEY,
    ts          TEXT NOT NULL,
    agent       TEXT NOT NULL,
    kind        TEXT NOT NULL,
    message     TEXT NOT NULL,
    traceback   TEXT,
    alerted     INTEGER NOT NULL DEFAULT 0,
    notified_at TEXT
);
